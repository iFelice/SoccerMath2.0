#!/usr/bin/env python3
"""
audit/tag_pre_shrinkage_predictions.py

Migrazione esplicita del Registro Predizioni per separare le predizioni
generale PRIMA del fix di shrinkage/lambda-zero da quelle generate dal motore
corretto (PRIOR_MATCHES=6, _shrunk_ratio, _clip_lambda NaN-safe).

Comportamento
-------------
    python audit/tag_pre_shrinkage_predictions.py            # dry-run
    python audit/tag_pre_shrinkage_predictions.py --apply    # migra SOLO il file locale

Solo ``--apply`` modifica i dati. Nessuna entry viene cancellata; pronostico,
probabilita', risultato reale, esito, quota e timestamp restano invariati.

Fonti
-----
Per default usa ``config.PREDICTIONS_FILE`` (SoccerMath/database/predictions.json).
Se il file locale non esiste e sono configurate le credenziali JSONBin, il
dry-run legge il remoto SOLO in lettura (cache in memoria, nessuna scrittura).
Il remoto NON viene mai sovrascritto da ``--apply``: serve ``--push-remote``.

Con ``--source FILE`` e' possibile analizzare un qualsiasi file nel formato
``{"data": [...]}`` o lista diretta (es. uno snapshot storico di Git).

Il cutoff e' derivato dal repository Git, non inventato:
  - commit fix:  ae8784d643575593f77241c54a1930e7bd48145f (2026-09-04 15:40:10 UTC)
  - merge main:  dc192d5eaa36968380f8bde823ca1abe9792e65d (2026-09-04 16:50:17 UTC)
Le predizioni salvate nell'intervallo tra i due timestamp sono classificate
come AMBIGUE e non vengono taggate automaticamente.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SOCCERMATH_DIR = _REPO_ROOT / "SoccerMath"
sys.path.insert(0, str(_SOCCERMATH_DIR))

from config import JSONBIN_BIN_ID, JSONBIN_API_KEY, PREDICTIONS_FILE  # noqa: E402
from prediction_registry import (  # noqa: E402
    CUTOFF_COMMIT,
    CUTOFF_COMMIT_MESSAGE,
    CUTOFF_COMMIT_SHORT,
    CUTOFF_COMMIT_TIME,
    CUTOFF_MERGE_COMMIT,
    CUTOFF_MERGE_COMMIT_MESSAGE,
    CUTOFF_MERGE_COMMIT_SHORT,
    CUTOFF_MERGE_TIME,
    classify_entry,
    entry_generation_time,
    load_predictions_file,
    should_tag_pre_fix,
    tag_pre_fix,
    write_predictions_file,
    backup_prediction_file,
)


def _load_source(args) -> tuple[List[Dict], str, str]:
    """Carica i record dalla fonte richiesta.

    Ritorna (records, label, mode) dove mode e' 'local', 'remote' o 'source'.
    """
    if getattr(args, "source", None):
        p = Path(args.source)
        if not p.exists():
            raise FileNotFoundError(f"Fonte non trovata: {p}")
        records = load_predictions_file(p)
        return records, str(p), "source"

    local = Path(PREDICTIONS_FILE)
    if local.exists():
        records = load_predictions_file(local)
        return records, str(local), "local"

    if JSONBIN_API_KEY and JSONBIN_BIN_ID:
        try:
            import requests  # noqa: F401
        except ImportError:
            return [], "(JSONBin configurato ma requests non installato)", "remote"
        try:
            r = requests.get(
                f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest",
                headers={"X-Master-Key": JSONBIN_API_KEY},
                timeout=8,
            )
            if r.status_code == 200:
                rec = r.json().get("record", {})
                if isinstance(rec, dict) and isinstance(rec.get("data"), list):
                    return rec["data"], f"JSONBin {JSONBIN_BIN_ID} (lettura)", "remote"
                if isinstance(rec, list):
                    return rec, f"JSONBin {JSONBIN_BIN_ID} (lettura)", "remote"
        except Exception as exc:  # pragma: no cover
            print(f"[WARN] Lettura JSONBin fallita: {exc}", file=sys.stderr)

    return [], "(nessun file locale e nessun JSONBin configurato)", "remote"


def _report(records: List[Dict], source_label: str, mode: str, apply: bool) -> None:
    total = len(records)
    counters = Counter()
    times: List[datetime] = []
    missing_time = 0
    for entry in records:
        info = classify_entry(entry)
        counters[info["status"]] += 1
        dt, _ = entry_generation_time(entry)
        if dt is None:
            missing_time += 1
        else:
            times.append(dt)

    print("=" * 78)
    print("SONDAGGIO REGISTRO PREDIZIONI - CUTOFF SHRINKAGE/LAMBDA-ZERO")
    print("=" * 78)
    print(f"Fonte          : {source_label}")
    print(f"Modalita'      : {'APPLICAZIONE' if apply else 'DRY RUN (nessuna modifica)'}")
    print(f"Commit fix     : {CUTOFF_COMMIT_SHORT} {CUTOFF_COMMIT}  ({CUTOFF_COMMIT_TIME:%Y-%m-%d %H:%M:%S} UTC)")
    print(f"  {CUTOFF_COMMIT_MESSAGE}")
    print(f"Merge in main  : {CUTOFF_MERGE_COMMIT_SHORT} {CUTOFF_MERGE_COMMIT}  ({CUTOFF_MERGE_TIME:%Y-%m-%d %H:%M:%S} UTC)")
    print(f"  {CUTOFF_MERGE_COMMIT_MESSAGE}")
    print("-" * 78)
    print(f"TOTALE entry                     : {total}")
    print(f"  da taggare 'pre_shrinkage'     : {counters['to_tag_pre_shrinkage']}")
    print(f"  gia' 'pre_shrinkage'           : {counters['already_pre_shrinkage']}")
    print(f"  gia' 'post_shrinkage_v1'       : {counters['already_post_shrinkage_v1']}")
    print(f"  legacy (stagioni precedenti)   : {counters['legacy']}")
    print(f"  ambiguo (stagione 2026/27, no  : {counters['ambiguous']}")
    print(f"        timestamp certo o finestra)")
    print("-" * 78)
    undefined = max(0, total - sum(counters.values()))
    if undefined:
        print(f"  record non classificabili       : {undefined}")
    used_times = [t for t in times]
    if used_times:
        print(f"Intervallo 'salvato_il'          :"
              f" {min(used_times):%Y-%m-%d %H:%M:%S} UTC"
              f" -> {max(used_times):%Y-%m-%d %H:%M:%S} UTC")
    print(f"Record senza 'salvato_il'        : {missing_time}")
    print("=" * 78)

    # Dettaglio per categoria (utile per capire cosa cambierebbe).
    print("\nDETTAGLIO")
    print(f"{'status':<28} {'n':>4} {'stagioni coinvolte'}")
    by_season: Dict[str, Counter] = {}
    for entry in records:
        info = classify_entry(entry)
        season = info.get("season") or "Sconosciuta"
        by_season.setdefault(info["status"], Counter())[season] += 1
    for status, n in counters.most_common():
        seasons = dict(by_season.get(status, {}))
        print(f"  {status:<26} {n:>4}  {seasons}")


def _apply(records: List[Dict], output: Path, push_remote: bool) -> tuple[int, int, Path | None]:
    """Applica la migrazione locale. Non sovrascrive mai il remoto senza flag."""
    changed = 0
    kept = 0
    migrated_records: List[Dict] = []
    for entry in records:
        if should_tag_pre_fix(entry):
            migrated_records.append(tag_pre_fix(entry))
            changed += 1
        else:
            migrated_records.append(entry)
            kept += 1

    backup = backup_prediction_file(output) if output.exists() else None
    write_predictions_file(output, migrated_records)

    if push_remote:
        if not (JSONBIN_API_KEY and JSONBIN_BIN_ID):
            raise RuntimeError("--push-remote richiede JSONBIN_API_KEY e JSONBIN_BIN_ID")
        import requests
        requests.put(
            f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}",
            json={"data": migrated_records},
            headers={"X-Master-Key": JSONBIN_API_KEY, "Content-Type": "application/json"},
            timeout=10,
        )
    return changed, kept, backup


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Applica la migrazione (senza flag: dry-run).")
    parser.add_argument("--source", default=None,
                        help="File JSON da analizzare in alternativa al registro locale.")
    parser.add_argument("--output", default=None,
                        help="File di destinazione con --apply (default: config.PREDICTIONS_FILE).")
    parser.add_argument("--push-remote", action="store_true",
                        help="Con --apply, aggiorna anche JSONBin DOPO la scrittura locale.")
    args = parser.parse_args(argv)

    records, source_label, mode = _load_source(args)

    if args.apply:
        if args.source and args.output:
            output = Path(args.output)
        elif args.output:
            output = Path(args.output)
        else:
            output = Path(PREDICTIONS_FILE)
        # In apply, se la fonte e' remota e non c'e' un output esplicito,
        # scriviamo comunque il file locale: il remoto non viene mai toccato
        # senza --push-remote.
        if not output.exists() and source_label != str(Path(PREDICTIONS_FILE)):
            print(f"[INFO] Il registro locale non esiste: verra' creato {output} (nessuna sovrascrittura remota).")
        changed, kept, backup = _apply(records, output, args.push_remote)
        print(f"[APPLY] {changed} record taggati pre_shrinkage; {kept} invariati.")
        print(f"[APPLY] Backup locale: {backup}")
        print(f"[APPLY] Output locale: {output}")
        if args.push_remote:
            print("[APPLY] JSONBin aggiornato dopo la scrittura locale.")
        else:
            print("[APPLY] JSONBin NON aggiornato: verificare il file locale prima del push.")
    else:
        _report(records, source_label, mode, apply=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
