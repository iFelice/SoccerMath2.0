"""
update_all_xg_db.py - UNICA acquisizione dei dati Understat di SoccerMath.

Scarica via ``soccerdata`` il calendario con xG per-partita delle cinque leghe
e lo salva in ``SoccerMath/database/xG archivio <lega>.json``:

    {"season": 2026, "id": 30012, "date": "2026-08-22 18:45:00",
     "home_team": "Inter", "away_team": "Torino",
     "home_goals": 3, "away_goals": 1,
     "home_xg": 2.41, "away_xg": 0.77, "is_result": true}

Le medie stagionali usate dall'app (``database/xg_<lega>.json``) NON vengono
piu' scaricate a parte: si derivano da questo archivio con
``python SoccerMath/update_xg.py`` (stesso snapshot, stessi nomi).

Robustezza (nessun file vuoto o parziale in produzione):
  * i tipi pandas nullable vengono normalizzati in tipi JSON nativi
    (``pd.NA``/``NaT`` -> ``null``, ``numpy.int64`` -> ``int``);
  * l'archivio nuovo viene validato PRIMA di sostituire quello vecchio
    (schema, date, id duplicati, xG delle partite concluse, copertura
    stagionale minima);
  * il nuovo snapshot viene confrontato con l'ultimo valido PARTITA PER PARTITA
    (chiave stagione + id, non il totale delle righe): spariscono partite gia'
    concluse con xG, o regrediscono a "non giocata"/senza xG? Si rifiuta.
    Restano invece ammesse - e riportate - le variazioni legittime: partite
    nuove, correzioni di xG sulla stessa partita, fixture non ancora giocate
    tolte dal calendario. Ridurre le stagioni richieste e' possibile solo con
    ``--allow-dropping-seasons``;
  * la scrittura e' atomica (file temporaneo + ``os.replace``);
  * se una lega fallisce, l'ultimo archivio valido resta al suo posto e lo
    script esce con codice diverso da zero (il workflow non pubblica nulla).

Uso:
    python update_all_xg_db.py
    python update_all_xg_db.py --league "Serie A" --seasons 2526 2627
    python update_all_xg_db.py --dry-run
    python update_all_xg_db.py --output-dir /tmp/verify \
        --baseline-dir SoccerMath/database        # verifica senza toccare i dati
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from typing import Dict, List, Optional

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from xg_archive import (  # noqa: E402
    ARCHIVE_FILES,
    LEAGUES,
    REQUIRED_FIELDS,
    SOCCERDATA_LEAGUES,
    compare_snapshots,
    parse_season,
    validate_archive,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("update_all_xg_db")

# Stagioni richieste a soccerdata: dalla 2022/23 alla 2026/27.
SEASONS: List[str] = ["2223", "2324", "2425", "2526", "2627"]

# Colonne di Understat.read_schedule() usate (verificate su soccerdata 1.9.1).
OUTPUT_COLUMNS = {
    "season_id": "season",
    "game_id": "id",
    "date": "date",
    "home_team": "home_team",
    "away_team": "away_team",
    "home_goals": "home_goals",
    "away_goals": "away_goals",
    "home_xg": "home_xg",
    "away_xg": "away_xg",
    "is_result": "is_result",
}

DEFAULT_OUTPUT_DIR = os.path.join(_REPO_ROOT, "SoccerMath", "database")

# Rete di sicurezza GROSSOLANA, secondaria rispetto a compare_snapshots(): un
# archivio che perde piu' di questa frazione di RIGHE rispetto al precedente e'
# comunque sospetto anche quando le righe perse sono solo fixture non giocate.
MAX_SHRINK_RATIO = 0.10

# Versione di soccerdata verificata per queste colonne/questo formato.
REQUIRED_SOCCERDATA_VERSION = "1.9.1"


def _json_safe(value):
    """Converte i tipi pandas/numpy in tipi JSON nativi (NA -> None)."""
    if value is None:
        return None
    # pd.NA / pd.NaT / numpy.nan
    try:
        if value is not None and not isinstance(value, (str, bytes, list, dict)):
            import pandas as pd  # import locale: lo script gira anche senza pandas
            if pd.isna(value):
                return None
    except (TypeError, ValueError, ImportError):
        pass
    if isinstance(value, bool):
        return bool(value)
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (AttributeError, ValueError):
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def records_from_schedule(df) -> List[dict]:
    """DataFrame di ``Understat.read_schedule()`` -> record JSON-safe."""
    missing = [c for c in OUTPUT_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            "colonne mancanti nel risultato di read_schedule(): "
            f"{missing} (trovate: {sorted(df.columns)})")
    selected = df[list(OUTPUT_COLUMNS)].rename(columns=OUTPUT_COLUMNS)
    selected = selected.copy()
    selected["date"] = selected["date"].astype(str)
    records = []
    for row in selected.to_dict(orient="records"):
        clean = {key: _json_safe(row.get(key)) for key in REQUIRED_FIELDS}
        clean["season"] = parse_season(clean["season"])
        clean["is_result"] = bool(clean["is_result"])
        if clean["date"] in ("NaT", "None", ""):
            clean["date"] = None
        records.append(clean)
    return records


def check_soccerdata_version(strict: bool = False) -> str:
    """Verifica la versione di soccerdata effettivamente installata.

    Le colonne di ``read_schedule()`` sono state verificate su
    ``REQUIRED_SOCCERDATA_VERSION``: una versione diversa non viene rifiutata
    in silenzio, viene dichiarata nei log (o rifiutata con ``strict``).
    """
    try:
        from importlib.metadata import version
        installed = version("soccerdata")
    except Exception:  # pragma: no cover - dipende dall'ambiente
        installed = "sconosciuta"
    if installed != REQUIRED_SOCCERDATA_VERSION:
        message = (f"soccerdata {installed} != versione verificata "
                   f"{REQUIRED_SOCCERDATA_VERSION}")
        if strict:
            raise RuntimeError(message)
        log.warning("%s: le colonne di read_schedule() sono verificate solo "
                    "sulla versione dichiarata", message)
    else:
        log.info("soccerdata %s (versione verificata)", installed)
    return installed


def fetch_league(sd_league: str, seasons: List[str], no_cache: bool = True) -> List[dict]:
    """Scarica il calendario con xG di una lega (unica chiamata a Understat)."""
    import soccerdata as sd  # import locale: i test non richiedono la libreria

    check_soccerdata_version()

    understat = sd.Understat(leagues=sd_league, seasons=seasons, no_cache=no_cache)
    df = understat.read_schedule().reset_index()
    return records_from_schedule(df)


def _load_existing(path: str) -> Optional[List[dict]]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else None
    except Exception:
        return None


def _write_atomic(path: str, records: List[dict]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def update_league(
    league: str,
    seasons: List[str],
    output_dir: str,
    *,
    dry_run: bool = False,
    fetcher=fetch_league,
    baseline_dir: Optional[str] = None,
    allow_dropping_seasons: bool = False,
) -> Dict:
    """Scarica, valida e (solo se valido) sostituisce l'archivio della lega."""
    result: Dict = {"league": league, "written": False, "matches": 0, "errors": []}
    path = os.path.join(output_dir, ARCHIVE_FILES[league])
    result["path"] = path

    try:
        records = fetcher(SOCCERDATA_LEAGUES[league], seasons)
    except Exception as exc:
        result["errors"].append(f"download fallito: {exc}")
        return result

    expected = [parse_season(s) for s in seasons]
    problems = validate_archive(
        records, league=league, min_matches=100,
        expected_seasons=[s for s in expected if s],
    )
    if problems:
        result["errors"].extend(problems)
        return result

    # Baseline = ultimo archivio valido. In modalita' verifica l'output va in
    # una cartella temporanea, ma il confronto deve restare contro i dati veri.
    baseline_path = path
    if baseline_dir:
        baseline_path = os.path.join(baseline_dir, ARCHIVE_FILES[league])
    result["baseline_path"] = baseline_path
    previous = _load_existing(baseline_path)
    if previous:
        result["previous_matches"] = len(previous)
        diff = compare_snapshots(
            previous, records, league=league,
            requested_seasons=[s for s in expected if s],
            allow_dropping_seasons=allow_dropping_seasons,
        )
        result["diff"] = diff.to_dict()
        blocking = diff.blocking_problems
        if blocking:
            result["errors"].extend(blocking)
            result["errors"].append(
                "archivio esistente lasciato invariato (nessuna media pubblicata)")
            return result
        if diff.new_matches or diff.xg_corrections or diff.dropped_unplayed:
            log.info(
                "%s: variazioni ammesse - %d partite nuove, %d correzioni xG, "
                "%d fixture non giocate rimosse",
                league, len(diff.new_matches), len(diff.xg_corrections),
                len(diff.dropped_unplayed))

        # Rete secondaria sul volume, confrontando solo le stagioni RICHIESTE
        # (ridurre le stagioni non e' un crollo dello scrape).
        wanted = {s for s in expected if s}
        in_scope = [r for r in previous
                    if isinstance(r, dict)
                    and (not wanted or parse_season(r.get("season")) in wanted)]
        if in_scope:
            shrink = 1.0 - (len(records) / len(in_scope))
            if shrink > MAX_SHRINK_RATIO:
                result["errors"].append(
                    f"archivio nuovo con {len(records)} partite contro le "
                    f"{len(in_scope)} precedenti sulle stesse stagioni "
                    f"(-{shrink:.0%}): scrape parziale, archivio esistente "
                    "lasciato invariato")
                return result

    result["matches"] = len(records)
    if not dry_run:
        _write_atomic(path, records)
        result["written"] = True
    return result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Unica acquisizione Understat: archivio xG per-partita")
    parser.add_argument("--league", action="append", dest="leagues",
                        choices=list(LEAGUES), help="limita a una lega (ripetibile)")
    parser.add_argument("--seasons", nargs="+", default=SEASONS,
                        help=f"stagioni soccerdata (default: {' '.join(SEASONS)})")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--baseline-dir", default=None,
                        help="cartella dell'ultimo archivio valido con cui "
                             "confrontare lo snapshot (default: --output-dir). "
                             "Serve alla modalita' verifica, che scrive altrove "
                             "ma deve confrontarsi con i dati veri")
    parser.add_argument("--allow-dropping-seasons", action="store_true",
                        help="autorizza esplicitamente la scomparsa delle "
                             "stagioni non piu' richieste")
    parser.add_argument("--dry-run", action="store_true",
                        help="scarica e valida senza scrivere")
    parser.add_argument("--report", default=None, help="riepilogo JSON")
    args = parser.parse_args(argv)

    leagues = args.leagues or list(LEAGUES)
    results, failures = [], 0

    for league in leagues:
        log.info("Scaricamento %s (stagioni: %s)...", league, ", ".join(args.seasons))
        res = update_league(league, list(args.seasons), args.output_dir,
                            dry_run=args.dry_run,
                            baseline_dir=args.baseline_dir,
                            allow_dropping_seasons=args.allow_dropping_seasons)
        results.append(res)
        if res["errors"]:
            failures += 1
            for err in res["errors"]:
                log.error("%s: %s", league, err)
        else:
            log.info("%s: %d partite%s", league, res["matches"],
                     "" if res["written"] else " [dry-run, non scritto]")

    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)) or ".", exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

    log.info("Completato: %d/%d archivi aggiornati", len(leagues) - failures, len(leagues))
    if failures:
        log.error("Acquisizione fallita per %d leghe: i dati validi precedenti "
                  "NON sono stati sovrascritti.", failures)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
