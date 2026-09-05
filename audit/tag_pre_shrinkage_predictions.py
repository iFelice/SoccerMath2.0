#!/usr/bin/env python3
"""
audit/tag_pre_shrinkage_predictions.py

Migrazione esplicita del Registro Predizioni per separare le predizioni
generate PRIMA del fix di shrinkage/lambda-zero da quelle generate dal motore
corretto (PRIOR_MATCHES=6, _shrunk_ratio, _clip_lambda NaN-safe).

Comportamento
-------------
    python audit/tag_pre_shrinkage_predictions.py                  # dry-run (locale -> remoto)
    python audit/tag_pre_shrinkage_predictions.py --remote         # dry-run sul registro REALE JSONBin
    python audit/tag_pre_shrinkage_predictions.py --verify-backup  # preflight: backup completo del bin
    python audit/tag_pre_shrinkage_predictions.py --apply          # migra SOLO il file locale

Solo ``--apply`` modifica i dati. Nessuna entry viene cancellata; pronostico,
probabilita', risultato reale, esito, quota e timestamp restano invariati.

Fonti
-----
Per default usa ``config.PREDICTIONS_FILE`` (SoccerMath/database/predictions.json)
e, se il file locale non esiste, ripiega sul remoto JSONBin in sola lettura.

``--remote`` forza la lettura del registro REALE JSONBin ignorando il file
locale: e' la modalita' che replica la precedenza di ``app.load_predictions()``
(remoto prima, locale in fallback) ed e' quella corretta per fotografare cio'
che l'app mostra davvero.

Con ``--source FILE`` e' possibile analizzare un qualsiasi file nel formato
``{"data": [...]}`` o lista diretta (es. uno snapshot storico di Git).

Sicurezza scritture
-------------------
- il dry-run esegue esclusivamente richieste GET;
- ``--apply`` scrive solo il file locale (con backup preventivo);
- ``--push-remote`` e' l'unico percorso che tocca JSONBin e ABORTISCE se non
  riesce prima a salvare un backup integrale del bin remoto.

Il cutoff e' derivato dal repository Git, non inventato:
  - commit fix:  ae8784d643575593f77241c54a1930e7bd48145f (2026-09-04 15:40:10 UTC)
  - merge main:  dc192d5eaa36968380f8bde823ca1abe9792e65d (2026-09-04 16:50:17 UTC)
Le predizioni salvate nell'intervallo tra i due timestamp sono classificate
come AMBIGUE e non vengono taggate automaticamente.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
    MODEL_LABEL_LEGACY,
    MODEL_LABEL_PRE_FIX,
    TARGET_SEASON,
    classify_entry,
    entry_generation_time,
    load_predictions_file,
    model_label,
    normalize_season,
    season_from_entry,
    should_tag_pre_fix,
    tag_pre_fix,
    write_predictions_file,
    backup_prediction_file,
)

JSONBIN_READ_URL = "https://api.jsonbin.io/v3/b/{bin_id}/latest"
JSONBIN_WRITE_URL = "https://api.jsonbin.io/v3/b/{bin_id}"


# ---------------------------------------------------------------------------
# Verifica del cutoff contro il repository Git (il cutoff non e' inventato)
# ---------------------------------------------------------------------------
def _git_commit_info(sha: str) -> Optional[Dict[str, str]]:
    """Legge da Git autore/timestamp/oggetto del commit. None se non disponibile."""
    try:
        out = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "show", "-s",
             "--format=%H%x1f%aI%x1f%s", sha],
            capture_output=True, text=True, timeout=15,
        )
        if out.returncode != 0:
            return None
        parts = out.stdout.strip().split("\x1f")
        if len(parts) != 3:
            return None
        return {"sha": parts[0], "authored": parts[1], "subject": parts[2]}
    except Exception:
        return None


def _cutoff_verification_lines() -> List[str]:
    """Righe di verifica: il commit del cutoff esiste e ha il timestamp atteso."""
    lines: List[str] = []
    for sha, expected_dt, label in (
        (CUTOFF_COMMIT, CUTOFF_COMMIT_TIME, "commit fix"),
        (CUTOFF_MERGE_COMMIT, CUTOFF_MERGE_TIME, "merge main"),
    ):
        info = _git_commit_info(sha)
        if info is None:
            lines.append(f"  [!] {label}: commit {sha[:7]} NON verificabile in questo clone")
            continue
        try:
            actual = datetime.fromisoformat(info["authored"])
            match = actual == expected_dt
        except Exception:
            match = False
        flag = "OK" if match else "MISMATCH"
        lines.append(f"  [{flag}] {label}: {info['sha'][:7]} {info['authored']}")
    return lines


# ---------------------------------------------------------------------------
# Lettura sorgenti
# ---------------------------------------------------------------------------
def _require_remote_config() -> None:
    if not (JSONBIN_API_KEY and JSONBIN_BIN_ID):
        raise RuntimeError(
            "JSONBin non configurato: servono JSONBIN_API_KEY e JSONBIN_BIN_ID "
            "(variabili d'ambiente, SoccerMath/.env oppure st.secrets). "
            "Senza credenziali il registro REALE non e' leggibile."
        )


def _fetch_remote_records(timeout: int = 15) -> Tuple[List[Dict], str]:
    """GET in sola lettura del registro JSONBin. Nessuna scrittura.

    Solleva RuntimeError con messaggio esplicito se la lettura fallisce: il
    dry-run sul registro reale non deve MAI degradare silenziosamente a 0 entry.
    """
    _require_remote_config()
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("Modulo 'requests' non installato: impossibile leggere JSONBin") from exc

    url = JSONBIN_READ_URL.format(bin_id=JSONBIN_BIN_ID)
    try:
        resp = requests.get(url, headers={"X-Master-Key": JSONBIN_API_KEY}, timeout=timeout)
    except Exception as exc:
        raise RuntimeError(f"Lettura JSONBin fallita (rete): {type(exc).__name__}: {exc}") from exc

    if resp.status_code != 200:
        raise RuntimeError(f"Lettura JSONBin fallita: HTTP {resp.status_code} {resp.text[:200]}")

    rec = resp.json().get("record", {})
    if isinstance(rec, dict) and isinstance(rec.get("data"), list):
        records = rec["data"]
    elif isinstance(rec, list):
        records = rec
    else:
        raise RuntimeError("Formato JSONBin non riconosciuto: atteso {'data': [...]} o lista")
    return records, f"JSONBin {JSONBIN_BIN_ID} (sola lettura)"


def _load_source(args) -> Tuple[List[Dict], str, str]:
    """Carica i record dalla fonte richiesta.

    Ritorna (records, label, mode) dove mode e' 'local', 'remote' o 'source'.
    """
    if getattr(args, "source", None):
        p = Path(args.source)
        if not p.exists():
            raise FileNotFoundError(f"Fonte non trovata: {p}")
        return load_predictions_file(p), str(p), "source"

    # --remote: registro REALE, precedenza identica ad app.load_predictions().
    if getattr(args, "remote", False):
        records, label = _fetch_remote_records()
        return records, label, "remote"

    local = Path(PREDICTIONS_FILE)
    if local.exists():
        return load_predictions_file(local), str(local), "local"

    if JSONBIN_API_KEY and JSONBIN_BIN_ID:
        try:
            records, label = _fetch_remote_records()
            return records, label, "remote"
        except RuntimeError as exc:
            print(f"[WARN] {exc}", file=sys.stderr)

    return [], "(nessun file locale e nessun JSONBin leggibile)", "remote"


# ---------------------------------------------------------------------------
# Backup del registro remoto (preflight di sicurezza)
# ---------------------------------------------------------------------------
def _default_backup_path(ts: Optional[datetime] = None) -> Path:
    stamp = (ts or datetime.now()).strftime("%Y%m%d_%H%M%S")
    # ``database/*.json.bak`` e' gia' in SoccerMath/.gitignore.
    return Path(PREDICTIONS_FILE).with_name(f"predictions_jsonbin_{stamp}.json.bak")


def backup_remote_registry(dest: Optional[Path] = None) -> Tuple[Path, int]:
    """Scarica il bin e ne salva una copia integrale su file locale.

    Esegue SOLO una GET verso JSONBin. Ritorna (path, n_entry).
    """
    records, _ = _fetch_remote_records()
    path = Path(dest) if dest else _default_backup_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"data": records}, fh, ensure_ascii=False, indent=2)
    return path, len(records)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def _short_match(entry: Dict) -> str:
    home = str(entry.get("home", "?")).strip()
    away = str(entry.get("away", "?")).strip()
    return f"{home} - {away}"


def _fmt_utc(dt: Optional[datetime]) -> str:
    return f"{dt:%Y-%m-%d %H:%M:%S} UTC" if dt else "n/d"


def _report(records: List[Dict], source_label: str, mode: str, apply: bool,
            explain_match: Optional[str] = None) -> Dict[str, object]:
    total = len(records)
    counters: Counter = Counter()
    times: List[datetime] = []
    pre_fix_times: List[datetime] = []
    missing_time = 0
    season_target = 0
    to_tag_rows: List[Tuple[Optional[datetime], Dict]] = []

    for entry in records:
        info = classify_entry(entry)
        counters[info["status"]] += 1
        if normalize_season(season_from_entry(entry)) == TARGET_SEASON:
            season_target += 1
        dt, _ = entry_generation_time(entry)
        if dt is None:
            missing_time += 1
        else:
            times.append(dt)
        if info["status"] == "to_tag_pre_shrinkage":
            pre_fix_times.append(dt) if dt else None
            to_tag_rows.append((dt, entry))

    pre_after = counters["to_tag_pre_shrinkage"] + counters["already_pre_shrinkage"]

    print("=" * 78)
    print("DRY-RUN REGISTRO PREDIZIONI - CUTOFF SHRINKAGE/LAMBDA-ZERO")
    print("=" * 78)
    print(f"Fonte          : {source_label}")
    print(f"Modalita'      : {'APPLICAZIONE' if apply else 'DRY RUN (nessuna modifica, solo GET)'}")
    print(f"Commit fix     : {CUTOFF_COMMIT_SHORT} {CUTOFF_COMMIT}  ({CUTOFF_COMMIT_TIME:%Y-%m-%d %H:%M:%S} UTC)")
    print(f"  {CUTOFF_COMMIT_MESSAGE}")
    print(f"Merge in main  : {CUTOFF_MERGE_COMMIT_SHORT} {CUTOFF_MERGE_COMMIT}  ({CUTOFF_MERGE_TIME:%Y-%m-%d %H:%M:%S} UTC)")
    print(f"  {CUTOFF_MERGE_COMMIT_MESSAGE}")
    print("Verifica cutoff contro Git:")
    for line in _cutoff_verification_lines():
        print(line)
    print("-" * 78)
    print(f"TOTALE entry nel registro        : {total}")
    print(f"  di cui stagione {TARGET_SEASON}   : {season_target}")
    print("-" * 78)
    print("CLASSIFICAZIONE (dry-run, nessuna scrittura)")
    print(f"  pre_shrinkage (dopo migrazione): {pre_after}"
          f"   [da taggare ora: {counters['to_tag_pre_shrinkage']},"
          f" gia' taggate: {counters['already_pre_shrinkage']}]")
    print(f"  legacy (altre stagioni)        : {counters['legacy']}")
    print(f"  post_shrinkage_v1              : {counters['already_post_shrinkage_v1']}")
    print(f"  ambiguous                      : {counters['ambiguous']}")
    undefined = max(0, total - sum(counters.values()))
    if undefined:
        print(f"  non classificabili             : {undefined}")
    print("-" * 78)
    if pre_fix_times:
        print("Intervallo entry taggate PRE-FIX :"
              f" {min(pre_fix_times):%Y-%m-%d %H:%M:%S} UTC"
              f" -> {max(pre_fix_times):%Y-%m-%d %H:%M:%S} UTC")
    else:
        print("Intervallo entry taggate PRE-FIX : (nessuna entry da taggare)")
    if times:
        print("Intervallo 'salvato_il' (tutte)  :"
              f" {min(times):%Y-%m-%d %H:%M:%S} UTC"
              f" -> {max(times):%Y-%m-%d %H:%M:%S} UTC")
    print(f"Record senza 'salvato_il'        : {missing_time}")
    print("=" * 78)

    # Elenco sintetico: cosa cambierebbe da "Legacy" a "Pre-fix" nella UI.
    print(f"\nCAMBIO ETICHETTA UI: '{MODEL_LABEL_LEGACY}' -> '{MODEL_LABEL_PRE_FIX}'"
          f"  ({len(to_tag_rows)} predizioni)")
    if to_tag_rows:
        print("(la colonna 'prob' e' mostrata solo a titolo informativo:"
              " NON entra nel criterio di classificazione)")
        print(f"{'#':>3}  {'salvato_il (UTC)':<20} {'data match':<17} "
              f"{'campionato':<16} {'partita':<34} {'pronostico':<26} {'prob':>7}")
        for i, (dt, entry) in enumerate(sorted(to_tag_rows, key=lambda r: (r[0] is None, r[0])), 1):
            print(f"{i:>3}  {(dt.strftime('%Y-%m-%d %H:%M') if dt else 'n/d'):<20} "
                  f"{str(entry.get('data', 'n/d'))[:17]:<17} "
                  f"{str(entry.get('campionato', 'n/d'))[:16]:<16} "
                  f"{_short_match(entry)[:34]:<34} "
                  f"{str(entry.get('pronostico_sicuro', 'n/d'))[:26]:<26} "
                  f"{str(entry.get('prob_sicuro', 'n/d')):>7}")

    # Dettaglio per categoria.
    print("\nDETTAGLIO PER STATO")
    by_season: Dict[str, Counter] = {}
    for entry in records:
        info = classify_entry(entry)
        season = info.get("season") or "Sconosciuta"
        by_season.setdefault(info["status"], Counter())[season] += 1
    for status, n in counters.most_common():
        print(f"  {status:<26} {n:>4}  {dict(by_season.get(status, {}))}")

    if explain_match:
        _explain(records, explain_match)

    return {
        "total": total,
        "season_target": season_target,
        "pre_shrinkage_after": pre_after,
        "to_tag": counters["to_tag_pre_shrinkage"],
        "already_pre": counters["already_pre_shrinkage"],
        "legacy": counters["legacy"],
        "post_shrinkage_v1": counters["already_post_shrinkage_v1"],
        "ambiguous": counters["ambiguous"],
        "missing_time": missing_time,
        "pre_fix_window": (min(pre_fix_times), max(pre_fix_times)) if pre_fix_times else None,
        "to_tag_rows": to_tag_rows,
    }


def _explain(records: List[Dict], needle: str) -> None:
    """Spiega la classificazione delle entry che contengono ``needle``.

    Serve a dimostrare che il tag pre-fix dipende da stagione + timestamp +
    model_version, e MAI dalla probabilita' o dal mercato.
    """
    needle_low = needle.lower()
    hits = [e for e in records
            if needle_low in (str(e.get("home", "")) + " " + str(e.get("away", ""))).lower()]
    print(f"\nSPIEGAZIONE CLASSIFICAZIONE per '{needle}' ({len(hits)} match)")
    if not hits:
        print("  nessuna entry corrispondente nel registro analizzato")
        return
    for entry in hits:
        info = classify_entry(entry)
        dt, field = entry_generation_time(entry)
        print(f"  - {_short_match(entry)}")
        print(f"      pronostico      : {entry.get('pronostico_sicuro', 'n/d')}"
              f"  (prob {entry.get('prob_sicuro', 'n/d')} - NON usata per classificare)")
        print(f"      stagione        : {info['season']}  (target {TARGET_SEASON})")
        print(f"      {str(field or 'salvato_il'):<16}: {_fmt_utc(dt)}")
        print(f"      era vs cutoff   : {info['era']}"
              f"  (pre < {CUTOFF_COMMIT_TIME:%Y-%m-%d %H:%M} UTC"
              f" <= ambiguous < {CUTOFF_MERGE_TIME:%Y-%m-%d %H:%M} UTC <= post)")
        print(f"      model_version   : {info['model_version']}")
        print(f"      etichetta UI    : {model_label(entry)}")
        print(f"      stato migrazione: {info['status']}  (will_tag={info['will_tag']})")


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
def _apply(records: List[Dict], output: Path, push_remote: bool,
           remote_backup: Optional[Path] = None) -> Tuple[int, int, Optional[Path], Optional[Path]]:
    """Applica la migrazione locale. Il remoto non viene mai toccato senza flag.

    Con ``push_remote`` viene PRIMA salvato un backup integrale del bin: se il
    backup fallisce, la PUT non parte.
    """
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

    remote_backup_path: Optional[Path] = None
    if push_remote:
        _require_remote_config()
        # SICUREZZA: nessuna scrittura remota senza backup integrale riuscito.
        remote_backup_path, n_backup = backup_remote_registry(remote_backup)
        print(f"[SAFE] Backup remoto salvato: {remote_backup_path} ({n_backup} entry)")
        import requests
        resp = requests.put(
            JSONBIN_WRITE_URL.format(bin_id=JSONBIN_BIN_ID),
            json={"data": migrated_records},
            headers={"X-Master-Key": JSONBIN_API_KEY, "Content-Type": "application/json"},
            timeout=15,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"PUT JSONBin fallita: HTTP {resp.status_code} {resp.text[:200]}. "
                f"Backup integrale disponibile in {remote_backup_path}"
            )
    return changed, kept, backup, remote_backup_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="Applica la migrazione (senza flag: dry-run).")
    parser.add_argument("--remote", action="store_true",
                        help="Dry-run sul registro REALE JSONBin (sola lettura, ignora il file locale).")
    parser.add_argument("--source", default=None,
                        help="File JSON da analizzare in alternativa al registro locale.")
    parser.add_argument("--output", default=None,
                        help="File di destinazione con --apply (default: config.PREDICTIONS_FILE).")
    parser.add_argument("--push-remote", action="store_true",
                        help="Con --apply, aggiorna anche JSONBin DOPO backup integrale del bin.")
    parser.add_argument("--verify-backup", action="store_true",
                        help="Preflight: verifica di poter scaricare e salvare un backup completo del bin. Non scrive nulla sul remoto.")
    parser.add_argument("--backup-path", default=None,
                        help="Percorso del backup del bin (default: database/predictions_jsonbin_<ts>.json.bak).")
    parser.add_argument("--explain-match", default=None,
                        help="Spiega la classificazione delle entry il cui nome squadra contiene questa stringa.")
    args = parser.parse_args(argv)

    if args.remote and args.source:
        parser.error("--remote e --source sono mutuamente esclusivi")

    # Preflight di sicurezza: nessuna scrittura remota, solo GET + file locale.
    if args.verify_backup:
        try:
            path, n = backup_remote_registry(Path(args.backup_path) if args.backup_path else None)
        except RuntimeError as exc:
            print(f"[BACKUP][KO] {exc}", file=sys.stderr)
            print("[BACKUP][KO] Backup completo NON possibile: non procedere con alcuna scrittura.",
                  file=sys.stderr)
            return 2
        print(f"[BACKUP][OK] Backup completo del bin riuscito: {path} ({n} entry)")
        print("[BACKUP][OK] Una futura migrazione avrebbe un punto di ripristino.")
        if not args.apply:
            return 0

    try:
        records, source_label, mode = _load_source(args)
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"[ERRORE] {exc}", file=sys.stderr)
        return 2

    if args.remote and not records:
        print("[ERRORE] Registro remoto vuoto o non leggibile: dry-run non significativo.",
              file=sys.stderr)
        return 2

    if args.apply:
        output = Path(args.output) if args.output else Path(PREDICTIONS_FILE)
        if not output.exists() and source_label != str(Path(PREDICTIONS_FILE)):
            print(f"[INFO] Il registro locale non esiste: verra' creato {output} "
                  f"(nessuna sovrascrittura remota).")
        changed, kept, backup, remote_backup = _apply(
            records, output, args.push_remote,
            Path(args.backup_path) if args.backup_path else None,
        )
        print(f"[APPLY] {changed} record taggati pre_shrinkage; {kept} invariati.")
        print(f"[APPLY] Backup locale: {backup}")
        print(f"[APPLY] Output locale: {output}")
        if args.push_remote:
            print(f"[APPLY] JSONBin aggiornato (backup integrale: {remote_backup}).")
        else:
            print("[APPLY] JSONBin NON aggiornato: verificare il file locale prima del push.")
    else:
        _report(records, source_label, mode, apply=False, explain_match=args.explain_match)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
