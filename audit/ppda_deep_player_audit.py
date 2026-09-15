"""
ppda_deep_player_audit.py - Audit di copertura e qualita' dei due archivi NUOVI
PPDA/deep completions e statistiche giocatore per partita.

Produce, dalla stessa forma di ``audit/xg_pipeline_audit.py``:

  1. ``audit/results/ppda_deep_player_feasibility.md``
     Rapporto di fattibilita': copertura per lega e stagione rispetto
     all'archivio xG esistente, analisi point-in-time (stessa fonte degli xG di
     squadra o in ritardo?), distribuzione dei minuti giocati per partita,
     limiti dichiarati. Nessun collegamento al motore Poisson/Elo.
  2. ``audit/results/ppda_deep_player_feasibility.json``
     Gli stessi numeri in forma leggibile da una macchina.

Il rapporto e' GENERATO, non scritto a mano: in CI gira sui dati appena
acquisiti in una cartella non versionata (``--database-dir``) e sul report di
acquisizione (``--acquisition-report``), e il markdown prodotto viene poi
committato in ``audit/results/`` come referto della verifica.

Uso:
    python audit/ppda_deep_player_audit.py
    python audit/ppda_deep_player_audit.py \
        --database-dir /tmp/verify/database \
        --acquisition-report /tmp/verify/reports/acquisizione.json \
        --results-dir /tmp/verify/reports \
        --run-url https://github.com/.../actions/runs/123
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from match_stats_archive import (  # noqa: E402
    PLAYER_FILES,
    PLAYER_KIND,
    PPDA_FILES,
    PPDA_KIND,
    clean_text,
    describe_distribution,
    load_ppda,
    load_player,
    name_resolution_report,
    parse_bool,
    parse_int,
    parse_kickoff,
    parse_season,
    percentile,
    ppda_gap_kind,
    record_completeness,
    player_summary,
    ppda_summary,
)
from xg_archive import LEAGUES, load_archive  # noqa: E402

REPO_DB_DIR = os.path.join(_REPO_ROOT, "SoccerMath", "database")
RESULTS_DIR = os.path.join(_AUDIT_DIR, "results")

REPORT_BASENAME = "ppda_deep_player_feasibility"

# Campi realmente esposti da soccerdata 1.9.1 (verificati sul sorgente della
# versione pinnata, ``soccerdata/understat.py``) e campi NON esposti.
SOCCERDATA_EXPOSED = {
    "read_team_match_stats": [
        "*_ppda", "*_deep_completions", "*_xg", "*_np_xg", "*_expected_points",
        "*_points", "*_goals",
    ],
    "read_player_match_stats": [
        "minutes", "position", "goals", "own_goals", "shots", "xg", "xg_chain",
        "xg_buildup", "assists", "xa", "key_passes", "yellow_cards", "red_cards",
    ],
}
SOCCERDATA_NOT_EXPOSED = [
    "un canale d'errore per singola partita in ``read_player_match_stats()``: "
    "``Understat._read_match`` inghiotte ``ConnectionError`` e restituisce "
    "``None``, quindi la partita viene saltata in silenzio (qui contata come "
    "MANCANTE, mai come 0 righe)",
    "la data della partita nelle righe giocatore (bisogna derivarla dal prefisso "
    "di ``game``, oppure incrociare il calendario: entrambe le vie sono usate e "
    "confrontate)",
    "un rate limit per Understat: ``Understat._request_api`` chiama "
    "``self._session.get()`` senza ``rate_limit`` ne' delay (a differenza di "
    "``BaseRequestsReader._download_and_save``), quindi il ritmo dipende solo "
    "dalla latenza e dal parallelismo scelto",
    "i minuti ufficiali del campionato: ``minutes`` e' il campo ``time`` di "
    "Understat e include il recupero (valori > 90)",
    "qualsiasi forma di snapshot datato lato Understat: la disponibilita' "
    "storica reale dei dati non e' ricostruibile a posteriori",
]


# ---------------------------------------------------------------------------
# Utilità
# ---------------------------------------------------------------------------
def file_metadata(path: str) -> dict:
    if not os.path.exists(path):
        return {"exists": False}
    size = os.path.getsize(path)
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return {"exists": True, "bytes": size,
            "sha256": digest.hexdigest()[:16],
            "modified": datetime.fromtimestamp(os.path.getmtime(path),
                                               tz=timezone.utc).isoformat()}


def _kickoff(record: dict):
    return parse_kickoff(record.get("date"))[0]


def _season_matches(records: Sequence[dict]) -> Dict[int, Dict[int, List[dict]]]:
    """{stagione: {id partita: [record]}}, per il confronto col perimetro.

    Una lista (non un record singolo) perche' l'archivio giocatore ha molte
    righe per partita e serve contarle, non sovrascriverle.
    """
    index: Dict[int, Dict[int, List[dict]]] = {}
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        season = parse_season(rec.get("season"))
        match_id = parse_int(rec.get("id"))
        if season is None or match_id is None:
            continue
        index.setdefault(season, {}).setdefault(match_id, []).append(rec)
    return index


def xg_perimeter(league: str, xg_dir: str,
                 errors: Optional[List[str]] = None) -> Dict[int, Dict[int, dict]]:
    """Partite concluse con entrambi gli xG nell'archivio xG (per stagione).

    Se l'archivio xG della lega non e' leggibile il denominatore non esiste: il
    caso viene dichiarato in ``errors`` (e quindi nel referto), mai nascosto.
    """
    perimeter: Dict[int, Dict[int, dict]] = {}
    try:
        archive = load_archive(league, xg_dir) or []
    except Exception as exc:  # archivio assente o corrotto
        if errors is not None:
            errors.append(f"archivio xG non leggibile in {xg_dir}: {exc}")
        return perimeter
    for rec in archive:
        if not isinstance(rec, dict) or not parse_bool(rec.get("is_result")):
            continue
        home_xg, away_xg = rec.get("home_xg"), rec.get("away_xg")
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                   for value in (home_xg, away_xg)):
            continue
        season = parse_season(rec.get("season"))
        match_id = parse_int(rec.get("id"))
        if season is None or match_id is None:
            continue
        perimeter.setdefault(season, {})[match_id] = rec
    return perimeter


def coverage_block(records: Sequence[dict], perimeter: Dict[int, Dict[int, dict]],
                   kind: str) -> dict:
    """Copertura per stagione rispetto al perimetro dell'archivio xG."""
    index = _season_matches(records)
    seasons = sorted(set(perimeter) | set(index))
    seasons_out: Dict[str, dict] = {}
    totals = {"reference_matches": 0, "present_matches": 0, "rows": 0,
              "complete": 0, "partial": 0, "structural_ppda_na": 0,
              "record_without_values": 0,
              "no_record": 0, "missing_matches": 0,
              "with_home_ppda": 0, "with_away_ppda": 0,
              "with_home_deep": 0, "with_away_deep": 0}
    for season in seasons:
        reference = perimeter.get(season, {})
        present = index.get(season, {})
        entry = {
            "reference_matches": len(reference),
            "present_matches": len(present),
            "missing_matches": 0,
            "complete": 0,
            "partial": 0,
            "structural_ppda_na": 0,
            "record_without_values": 0,
            "no_record": 0,
            "with_home_ppda": 0, "with_away_ppda": 0,
            "with_home_deep": 0, "with_away_deep": 0,
            "rows": sum(len(rows) for rows in present.values()),
            "missing_sample": [],
        }
        for match_id, rec in sorted(reference.items()):
            got = present.get(match_id)
            if not got:
                entry["no_record"] += 1
                if len(entry["missing_sample"]) < 15:
                    entry["missing_sample"].append({
                        "id": match_id,
                        "date": (rec.get("date") or "")[:10],
                        "home_team": rec.get("home_team"),
                        "away_team": rec.get("away_team"),
                    })
                continue
            if kind == PPDA_KIND:
                got = got[-1]
                completeness = record_completeness(got)
                gap = ppda_gap_kind(got)
                if completeness == "completo":
                    entry["complete"] += 1
                elif gap == "strutturale":
                    # PPDA non calcolabile (denominatore difensivo nullo) con
                    # deep completions presente: il campo esiste, il rapporto no
                    entry["structural_ppda_na"] += 1
                elif completeness == "parziale":
                    entry["partial"] += 1
                else:
                    entry["record_without_values"] += 1
                for side in ("home", "away"):
                    entry[f"with_{side}_ppda"] += 1 if got.get(f"{side}_ppda") is not None else 0
                    entry[f"with_{side}_deep"] += 1 if got.get(
                        f"{side}_deep_completions") is not None else 0
            else:
                entry["complete"] += 1
        entry["missing_matches"] = (entry["no_record"] + entry["partial"]
                                    + entry["record_without_values"])
        entry["complete_ratio"] = (entry["complete"] / entry["reference_matches"]
                                   if entry["reference_matches"] else None)
        entry["presence_ratio"] = (entry["present_matches"] / entry["reference_matches"]
                                   if entry["reference_matches"] else None)
        # partite presenti nei dati ma NON nel perimetro dell'archivio xG:
        # novita' fra la scrittura dell'archivio e questa acquisizione
        entry["newer_than_archive"] = sum(1 for match_id in present
                                          if match_id not in reference)
        seasons_out[str(season)] = entry
        for key in ("reference_matches", "present_matches", "complete", "partial",
                    "structural_ppda_na", "record_without_values", "no_record",
                    "missing_matches", "with_home_ppda", "with_away_ppda",
                    "with_home_deep", "with_away_deep"):
            totals[key] += entry[key]
        totals["rows"] += entry["rows"]
    totals["complete_ratio"] = (totals["complete"] / totals["reference_matches"]
                               if totals["reference_matches"] else None)
    totals["presence_ratio"] = (totals["present_matches"] / totals["reference_matches"]
                               if totals["reference_matches"] else None)
    return {"kind": kind, "totals": totals, "seasons": seasons_out,
            "own_records": sum(len(v) for v in index.values())}


def minutes_block(rows: Sequence[dict]) -> dict:
    """Distribuzione dei minuti giocati per partita + analisi del minutaggio.

    Serve a rispondere a due domande pratiche: una media "per 90 minuti" ha
    senso cosi' com'e', o serve un minutaggio minimo prima di usare il dato?
    """
    minutes: List[int] = []
    minutes_by_season: Dict[int, List[int]] = {}
    rows_per_match: Dict[tuple, int] = {}
    players_minutes: Dict[tuple, int] = {}
    players_rows: Dict[tuple, int] = {}
    positions: Dict[str, int] = {}
    none_minutes = 0
    rows_by_season: Dict[int, int] = {}
    for rec in rows or []:
        if not isinstance(rec, dict):
            continue
        season = parse_season(rec.get("season"))
        value = rec.get("minutes")
        if value is None:
            none_minutes += 1
        else:
            minutes.append(int(value))
            minutes_by_season.setdefault(season, []).append(int(value))
        rows_by_season[season] = rows_by_season.get(season, 0) + 1
        match_id = parse_int(rec.get("id"))
        if match_id is not None:
            key = (season, match_id)
            rows_per_match[key] = rows_per_match.get(key, 0) + 1
        player_id = parse_int(rec.get("player_id"))
        if player_id is not None:
            player_key = (season, player_id)
            players_rows[player_key] = players_rows.get(player_key, 0) + 1
            if value is not None:
                players_minutes[player_key] = (players_minutes.get(player_key, 0)
                                               + int(value))
        position = clean_text(rec.get("position"))
        if position:
            positions[position] = positions.get(position, 0) + 1

    thresholds = (0, 90, 270, 450, 900)
    total_minutes = sum(minutes)
    per_threshold = []
    for threshold in thresholds:
        kept_players = [key for key, value in players_minutes.items()
                        if value >= threshold]
        kept_set = set(kept_players)
        kept_rows = sum(count for key, count in players_rows.items()
                        if key in kept_set)
        kept_minutes = sum(players_minutes[key] for key in kept_players)
        per_threshold.append({
            "threshold": threshold,
            "players": len(kept_players),
            "players_share": (len(kept_players) / len(players_minutes)
                              if players_minutes else None),
            "rows": kept_rows,
            "rows_share": (kept_rows / len(rows or [])) if rows else None,
            "minutes": kept_minutes,
            "minutes_share": (kept_minutes / total_minutes) if total_minutes else None,
        })

    return {
        "rows": len(rows or []),
        "matches": len(rows_per_match),
        "players": len(players_minutes),
        "teams": len({clean_text(rec.get("team")) for rec in rows or []
                      if isinstance(rec, dict) and clean_text(rec.get("team"))}),
        "minutes_missing": none_minutes,
        "minutes": describe_distribution(minutes),
        "minutes_by_season": {str(season): describe_distribution(values)
                              for season, values in sorted(minutes_by_season.items())},
        "rows_by_season": {str(season): count
                           for season, count in sorted(rows_by_season.items())},
        "players_per_match": describe_distribution(list(rows_per_match.values())),
        "zero_minutes_rows": sum(1 for value in minutes if value == 0),
        "zero_minutes_share": (sum(1 for value in minutes if value == 0) / len(minutes)
                               if minutes else None),
        "used_rows": sum(1 for value in minutes if value > 0),
        "positions": dict(sorted(positions.items(), key=lambda item: -item[1])),
        "season_minutes": describe_distribution(list(players_minutes.values())),
        "thresholds": per_threshold,
        "season_minutes_low": [
            {"season": key[0], "player_id": key[1], "minutes": value}
            for key, value in sorted(players_minutes.items(),
                                     key=lambda item: item[1])[:10]
        ],
    }


def ppda_values_block(records: Sequence[dict]) -> dict:
    """Valori PPDA/deep completions (intervallo e quantili), per sanita' del dato."""
    ppda: List[float] = []
    deep: List[float] = []
    per_season: Dict[int, List[float]] = {}
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        season = parse_season(rec.get("season"))
        for side in ("home", "away"):
            value = rec.get(f"{side}_ppda")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                ppda.append(float(value))
                per_season.setdefault(season, []).append(float(value))
            value = rec.get(f"{side}_deep_completions")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                deep.append(float(value))
    return {
        "ppda": describe_distribution(ppda),
        "ppda_by_season": {str(season): describe_distribution(values)
                           for season, values in sorted(per_season.items())},
        "deep_completions": describe_distribution(deep),
    }


def acquisition_blocks(acquisition: Optional[dict]) -> dict:
    """Estrae dal report di acquisizione i blocchi utili all'analisi temporale."""
    if not acquisition:
        return {"available": False}
    blocks: Dict[str, dict] = {"available": True,
                               "generated_at": acquisition.get("generated_at"),
                               "soccerdata_version": acquisition.get("soccerdata_version"),
                               "seasons": acquisition.get("seasons"),
                               "player_seasons": acquisition.get("player_seasons"),
                               "parallel_leagues": acquisition.get("parallel_leagues"),
                               "retries": acquisition.get("retries"),
                               "frontier_days": acquisition.get("frontier_days"),
                               "missing_tolerance_ratio": acquisition.get(
                                   "missing_tolerance_ratio"),
                               "sample_matches_per_league": acquisition.get(
                                   "sample_matches_per_league"),
                               "failures": acquisition.get("failures"),
                               "leagues": {}}
    for outcome in acquisition.get("leagues") or []:
        entry = {"schedule": outcome.get("schedule"),
                 "schedule_duplicates": outcome.get("schedule_duplicates"),
                 "seconds": outcome.get("seconds"),
                 "errors": outcome.get("errors"),
                 "datasets": {}}
        for dataset, payload in (outcome.get("datasets") or {}).items():
            entry["datasets"][dataset] = {
                "errors": payload.get("errors"),
                "seconds": payload.get("seconds"),
                "coverage": payload.get("coverage"),
                "written": payload.get("written"),
                "baseline_found": payload.get("baseline_found"),
                "diff": payload.get("diff"),
                "retry_rounds": payload.get("retry_rounds"),
                "missing_matches_sample": payload.get("missing_matches_sample"),
                "requested_matches": payload.get("requested_matches"),
                "returned_matches": payload.get("returned_matches"),
                "rows": payload.get("rows"),
                "matches": payload.get("matches"),
                "matches_per_second": payload.get("matches_per_second"),
                "duplicates": payload.get("duplicates"),
                "unreadable_matches": payload.get("unreadable_matches"),
                "unreadable_sample": payload.get("unreadable_sample"),
                "structural_na_sample": payload.get("structural_na_sample"),
                "shrink_ratio": payload.get("shrink_ratio"),
            }
        blocks["leagues"][outcome.get("league")] = entry
    return blocks


# ---------------------------------------------------------------------------
# Analisi per lega
# ---------------------------------------------------------------------------
def analyse_league(league: str, db_dir: str, xg_dir: str, *,
                   reference: datetime, acquisition: Optional[dict]) -> dict:
    result: dict = {"league": league, "files": {}, "coverage": {}, "names": {},
                    "errors": []}
    perimeter = xg_perimeter(league, xg_dir, errors=result["errors"])
    result["perimeter_matches"] = sum(len(matches) for matches in perimeter.values())
    result["perimeter_by_season"] = {str(season): len(matches)
                                     for season, matches in sorted(perimeter.items())}

    ppda_path = os.path.join(db_dir, PPDA_FILES[league])
    result["files"][PPDA_KIND] = file_metadata(ppda_path)
    ppda_records: List[dict] = []
    if result["files"][PPDA_KIND]["exists"]:
        try:
            ppda_records = load_ppda(league, db_dir)
        except Exception as exc:
            result["errors"].append(f"{PPDA_KIND}: non leggibile ({exc})")
    if ppda_records:
        result["coverage"][PPDA_KIND] = coverage_block(ppda_records, perimeter, PPDA_KIND)
        result["summary_ppda"] = ppda_summary(ppda_records)
        result["names"][PPDA_KIND] = name_resolution_report(ppda_records, kind=PPDA_KIND)
        result["values"] = ppda_values_block(ppda_records)

    player_path = os.path.join(db_dir, PLAYER_FILES[league])
    result["files"][PLAYER_KIND] = file_metadata(player_path)
    player_rows: List[dict] = []
    if result["files"][PLAYER_KIND]["exists"]:
        try:
            player_rows = load_player(league, db_dir)
        except Exception as exc:
            result["errors"].append(f"{PLAYER_KIND}: non leggibile ({exc})")
    if player_rows:
        result["coverage"][PLAYER_KIND] = coverage_block(player_rows, perimeter,
                                                         PLAYER_KIND)
        result["summary_player"] = player_summary(player_rows)
        result["names"][PLAYER_KIND] = name_resolution_report(player_rows,
                                                              kind=PLAYER_KIND)
        result["minutes"] = minutes_block(player_rows)

    # Analisi temporale sui dati (senza report di acquisizione): eta' delle
    # partite mancanti rispetto al perimetro committato.
    for kind, records in ((PPDA_KIND, ppda_records), (PLAYER_KIND, player_rows)):
        if not records:
            continue
        index = _season_matches(records)
        missing = []
        last_present = None
        for season, matches in perimeter.items():
            for match_id, rec in matches.items():
                if match_id in index.get(season, {}):
                    kickoff = _kickoff(rec)
                    if kickoff and (last_present is None or kickoff > last_present):
                        last_present = kickoff
                    continue
                missing.append({"id": match_id, "season": season,
                                "date": (rec.get("date") or "")[:10],
                                "home_team": rec.get("home_team"),
                                "away_team": rec.get("away_team"),
                                "kickoff": _kickoff(rec)})
        ages = []
        undated = 0
        for entry in missing:
            if entry["kickoff"] is None:
                undated += 1
                continue
            ages.append((reference - entry["kickoff"]).total_seconds() / 86400.0)
        ages.sort()
        result.setdefault("timing", {})[kind] = {
            "perimeter_missing": len(missing),
            "perimeter_missing_undated": undated,
            "age_days": describe_distribution(ages),
            "age_days_p90": percentile(ages, 0.90),
            "age_days_max": ages[-1] if ages else None,
            "older_than_frontier": sum(1 for age in ages if age > 1.0),
            "sample": [entry for entry in sorted(missing,
                                                 key=lambda item: item["date"])[-15:]],
            "last_date_present": last_present.date().isoformat() if last_present else None,
        }

    if acquisition:
        # blocco per lega gia' normalizzato da ``acquisition_blocks()``
        result["acquisition"] = acquisition
    return result


# ---------------------------------------------------------------------------
# Rendering del rapporto
# ---------------------------------------------------------------------------
def _dataset_errors(entry: dict, dataset: str) -> str:
    """Motivo (dal report di acquisizione) per cui un dataset non ha un file.

    L'ordine di lettura segue la causa reale: prima l'errore del dataset, poi
    l'errore della lega (la lega puo' essere fallita prima di acquisire), poi la
    semplice assenza dal perimetro richiesto.
    """
    acquisition = entry.get("acquisition") or {}
    datasets = acquisition.get("datasets") or {}
    errors = list((datasets.get(dataset) or {}).get("errors") or [])
    if errors:
        return "; ".join(str(error) for error in errors)
    if acquisition:
        if dataset in datasets:
            return ("acquisito ma nessun file scritto (dry-run, scrittura "
                    "saltata per errori di validazione)")
        other = sorted(name for name in datasets if name != dataset)
        if other:
            return ("non acquisito in questa esecuzione (dataset richiesti e "
                    f"presenti nel report: {', '.join(other)})")
        league_errors = acquisition.get("errors") or []
        if league_errors:
            return "; ".join(str(error) for error in league_errors)
        return "non acquisito (nessun dataset scritto per questa lega)"
    return ""


def _pct(value: Optional[float], digits: int = 1) -> str:
    return "n/d" if value is None else f"{value * 100:.{digits}f}%"


def _count(value) -> str:
    """Numero intero leggibile anche quando il dato non c'e' (mai ``None``)."""
    if value is None:
        return "n/d"
    if isinstance(value, float):
        return f"{value:.0f}"
    return str(value)


def _num(value, digits: int = 2) -> str:
    if value is None:
        return "n/d"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _bytes(value: Optional[int]) -> str:
    if value is None:
        return "n/d"
    if value < 1024:
        return f"{value} B"
    if value < 1024 ** 2:
        return f"{value / 1024:.1f} KiB"
    return f"{value / 1024 ** 2:.1f} MiB"


def render_markdown(analysis: dict, *, generated_at: str, run_url: Optional[str],
                    run_id: Optional[str], args) -> str:
    leagues = analysis["leagues"]
    acquisition = analysis["acquisition"]
    out: List[str] = []
    add = out.append

    add("# Fattibilita' PPDA, deep completions e medie giocatore per partita "
        "— audit di sola acquisizione")
    add("")
    add("Rapporto **generato** da `audit/ppda_deep_player_audit.py` sui dati "
        "acquisiti da `update_all_ppda_player_db.py` (stessa fonte Understat "
        "della pipeline xG, `soccerdata==1.9.1`).")
    add("")
    add("Nessuna modifica a `SoccerMath/app.py`, `SoccerMath/config.py`, "
        "`SoccerMath/models/`, a formule, soglie (`0.55`/`0.60`/`0.25`), pesi "
        "(`0.6`/`0.4`) o `PRIOR_MATCHES`: **questi dati non sono collegati al "
        "motore Poisson/Elo**, ne' lo diventano con questo intervento.")
    add("")
    add(f"- generato: `{generated_at}`")
    add(f"- istante di riferimento per le eta': `{analysis['reference_time']}`")
    add("- dataset analizzati: "
        + ", ".join(f"`{name}`" for name in analysis["datasets"]))
    add("- leghe: " + ", ".join(f"`{league}`" for league in leagues))
    if run_url:
        add(f"- esecuzione reale (workflow sola lettura): {run_url}")
    if run_id:
        add(f"- artifact: `ppda-player-verify-{run_id}`")
    add(f"- cartella dati analizzata: `{analysis['database_dir']}`")
    add(f"- archivio xG di riferimento (perimetro): `{analysis['xg_dir']}`")
    if acquisition.get("available"):
        add(f"- report di acquisizione: `{analysis['acquisition_report']}` "
            f"(soccerdata {acquisition.get('soccerdata_version')}, "
            f"fallimenti: {acquisition.get('failures')})")
    else:
        add("- report di acquisizione: **assente** — le sezioni che dipendono "
            "dall'istantanea di acquisizione sono marcate come non disponibili")
    add("")

    # ---------------------------------------------------------------- sintesi
    add("## 1. Sintesi")
    add("")
    total_reference = 0
    total_ppda_complete = 0
    total_ppda_no_record = 0
    total_player_matches = 0
    total_player_rows = 0
    for league in leagues:
        entry = leagues[league]
        ppda = (entry.get("coverage") or {}).get(PPDA_KIND) or {}
        player = (entry.get("coverage") or {}).get(PLAYER_KIND) or {}
        total_reference += (entry.get("perimeter_matches")
                            or (ppda.get("totals") or {}).get("reference_matches", 0))
        total_ppda_complete += (ppda.get("totals") or {}).get("complete", 0)
        total_ppda_no_record += (ppda.get("totals") or {}).get("no_record", 0)
        total_player_matches += (player.get("totals") or {}).get("present_matches", 0)
        total_player_rows += (player.get("totals") or {}).get("rows", 0)
    add(f"- perimetro di riferimento (partite concluse con xG nell'archivio xG): "
        f"**{total_reference}**")
    add(f"- PPDA/deep **completi** su entrambi i lati: **{total_ppda_complete}** "
        f"({_pct(total_ppda_complete / total_reference if total_reference else None)})"
        f"; partite senza alcun record: **{total_ppda_no_record}**")
    add(f"- partite con statistiche giocatore: **{total_player_matches}** "
        f"({_pct(total_player_matches / total_reference if total_reference else None)})"
        f", per **{total_player_rows}** righe giocatore-partita")
    if acquisition.get("available"):
        fresh_missing = []
        for league in leagues:
            datasets = (acquisition["leagues"].get(league) or {}).get("datasets") or {}
            coverage = (datasets.get(PLAYER_KIND) or {}).get("coverage") or {}
            fresh_missing.append(f"{league}: {coverage.get('missing_total', 'n/d')}")
        add("- partite senza righe giocatore sull'istantanea fresca (perimetro "
            "fresco, non archivio): " + ", ".join(fresh_missing))
    add("")

    # -------------------------------------------------------------- copertura
    add("## 2. Copertura per lega e stagione (rispetto all'archivio xG)")
    add("")
    add("Denominatore: partite **concluse con entrambi gli xG** nell'archivio xG "
        "committato (`SoccerMath/database/xG archivio <lega>.json`). Per PPDA e "
        "deep completions una partita e' \"completa\" solo se **tutti e quattro** "
        "i valori (2 lati x 2 campi) sono presenti.")
    add("")
    for league in leagues:
        entry = leagues[league]
        ppda = (entry.get("coverage") or {}).get(PPDA_KIND) or {}
        add(f"### {league}")
        add("")
        for error in entry.get("errors") or []:
            add(f"- **nota**: {error}")
        if entry.get("errors"):
            add("")
        add(f"Perimetro nell'archivio xG: **{entry.get('perimeter_matches', 0)}** "
            "partite concluse con xG ("
            + ", ".join(f"{season}: {count}"
                        for season, count in (entry.get("perimeter_by_season") or {}).items())
            + ").")
        add("")
        if not entry["files"].get(PPDA_KIND, {}).get("exists"):
            reason = _dataset_errors(entry, PPDA_KIND)
            add("- file PPDA/deep **assente**"
                + (f" (motivo: {reason})" if reason else ""))
        else:
            meta = entry["files"][PPDA_KIND]
            add(f"- file: `{PPDA_FILES[league]}` ({_bytes(meta.get('bytes'))}, "
                f"sha256 `{meta.get('sha256')}`, modificato `{meta.get('modified')}`)")
            add("")
            add("| Stagione | Concluse con xG | Con record | Complete | "
                "PPDA non calcolabile | Parziali (deep assente) | "
                "Record senza valori | Senza record | Copertura completa |")
            add("|---|---|---|---|---|---|---|---|---|")
            for season, bucket in (ppda.get("seasons") or {}).items():
                add(f"| {season} | {bucket['reference_matches']} | "
                    f"{bucket['present_matches']} | {bucket['complete']} | "
                    f"{bucket.get('structural_ppda_na', 0)} | "
                    f"{bucket['partial']} | {bucket['record_without_values']} | "
                    f"{bucket['no_record']} | {_pct(bucket['complete_ratio'])} |")
            totals = ppda.get("totals") or {}
            add(f"| **totale** | **{totals.get('reference_matches')}** | "
                f"**{totals.get('present_matches')}** | **{totals.get('complete')}** | "
                f"**{totals.get('structural_ppda_na', 0)}** | "
                f"**{totals.get('partial')}** | "
                f"**{totals.get('record_without_values')}** | "
                f"**{totals.get('no_record')}** | "
                f"**{_pct(totals.get('complete_ratio'))}** |")
            add("")
            add("\"PPDA non calcolabile\" = deep completions presente su "
                "entrambi i lati e PPDA nullo: soccerdata 1.9.1 restituisce "
                "`pd.NA` quando il denominatore difensivo del PPDA e' 0. E' un "
                "caso strutturale della fonte, non un campo perduto, ed e' "
                "contato a parte.")
            add("")
            reference = totals.get("reference_matches") or 0
            add("Valori presenti sul perimetro committato, lato per lato "
                f"(denominatore {_count(reference)}): "
                f"PPDA casa {_count(totals.get('with_home_ppda'))}, "
                f"PPDA trasferta {_count(totals.get('with_away_ppda'))}, "
                f"deep casa {_count(totals.get('with_home_deep'))}, "
                f"deep trasferta {_count(totals.get('with_away_deep'))}.")
            add("")
            values = entry.get("values") or {}
            dist = values.get("ppda") or {}
            deep = values.get("deep_completions") or {}
            if dist.get("n"):
                add(f"Valori PPDA (tutte le squadre, tutte le stagioni): mediana "
                    f"{_num(dist.get('p50'))}, p05 {_num(dist.get('p05'))}, "
                    f"p95 {_num(dist.get('p95'))}, minimo {_num(dist.get('min'))}, "
                    f"massimo {_num(dist.get('max'))}, zeri {dist.get('zeros')}.")
                add("")
            if deep.get("n"):
                add(f"Deep completions: mediana {_num(deep.get('p50'))}, minimo "
                    f"{_num(deep.get('min'))}, massimo {_num(deep.get('max'))}, "
                    f"zeri {deep.get('zeros')}.")
                add("")
        player = (entry.get("coverage") or {}).get(PLAYER_KIND) or {}
        if not entry["files"].get(PLAYER_KIND, {}).get("exists"):
            reason = _dataset_errors(entry, PLAYER_KIND)
            add("- file statistiche giocatore **assente**"
                + (f" (motivo: {reason})" if reason else ""))
            add("")
            continue
        meta = entry["files"][PLAYER_KIND]
        add(f"- file: `{PLAYER_FILES[league]}` ({_bytes(meta.get('bytes'))}, "
            f"sha256 `{meta.get('sha256')}`)")
        add("")
        add("| Stagione | Concluse con xG | Con righe giocatore | Righe | Copertura |")
        add("|---|---|---|---|---|")
        for season, bucket in (player.get("seasons") or {}).items():
            add(f"| {season} | {bucket['reference_matches']} | "
                f"{bucket['present_matches']} | {bucket['rows']} | "
                f"{_pct(bucket['presence_ratio'])} |")
        totals = player.get("totals") or {}
        add(f"| **totale** | **{totals.get('reference_matches')}** | "
            f"**{totals.get('present_matches')}** | **{totals.get('rows')}** | "
            f"**{_pct(totals.get('presence_ratio'))}** |")
        add("")

    # ------------------------------------------------------------ point-in-time
    add("## 3. Point-in-time: stessa tempistica degli xG o in ritardo?")
    add("")
    add("Due letture indipendenti, entrambe misurate:")
    add("")
    add("1. **stessa sorgente, stessa istantanea** — `read_team_match_stats()` e "
        "`read_schedule()` leggono lo **stesso documento** `getLeagueData/<lega>/"
        "<stagione>` (`datesData` per il calendario, `teamsData.history` per PPDA/"
        "deep). Il confronto e' quindi fatto a livello di partita sull'istantanea "
        "fresca: se una partita ha gli xG ma non PPDA/deep, il ritardo e' di "
        "*campo*, non di *endpoint*;")
    add("2. **endpoint diverso** — `read_player_match_stats()` non usa il payload "
        "di lega: chiama `getMatchData/<id>`, **una richiesta HTTP per partita** "
        "(`rostersData`). Qui il ritardo puo' essere reale e va misurato.")
    add("")
    if not acquisition.get("available"):
        add("> Il report di acquisizione non e' disponibile: le tabelle per-partita "
            "sull'istantanea fresca non sono calcolabili. Restano le misure "
            "derivate dal confronto con l'archivio xG committato.")
        add("")
    for league in leagues:
        entry = leagues[league]
        timing = entry.get("timing") or {}
        add(f"### {league}")
        add("")
        if not timing:
            acquisition_entry = entry.get("acquisition") or {}
            reason = "; ".join(str(error)
                               for error in (acquisition_entry.get("errors") or []))
            add("- nessun dato acquisito per questa lega"
                + (f": {reason}" if reason else "."))
            add("")
            continue
        ppda_timing = timing.get(PPDA_KIND)
        player_timing = timing.get(PLAYER_KIND)
        if ppda_timing:
            dist = ppda_timing.get("age_days") or {}
            add(f"- PPDA/deep: partite del perimetro committato assenti dal file: "
                f"**{ppda_timing['perimeter_missing']}**"
                + (f" (di cui senza data: {ppda_timing['perimeter_missing_undated']})"
                   if ppda_timing.get("perimeter_missing_undated") else "")
                + f"; eta' mediana {_num(dist.get('p50'), 1)} giorni, p90 "
                  f"{_num(ppda_timing.get('age_days_p90'), 1)}, massima "
                  f"{_num(ppda_timing.get('age_days_max'), 1)}; partite piu' "
                  f"vecchie di 1 giorno: **{ppda_timing['older_than_frontier']}**")
            add(f"- ultima data con PPDA/deep: `{ppda_timing.get('last_date_present')}`")
        if player_timing:
            dist = player_timing.get("age_days") or {}
            add(f"- statistiche giocatore: partite del perimetro committato senza "
                f"righe: **{player_timing['perimeter_missing']}**"
                + f"; eta' mediana {_num(dist.get('p50'), 1)} giorni, massima "
                  f"{_num(player_timing.get('age_days_max'), 1)}; partite piu' "
                  f"vecchie di 1 giorno: **{player_timing['older_than_frontier']}**")
            add(f"- ultima data con righe giocatore: `{player_timing.get('last_date_present')}`")
        acquisition_entry = entry.get("acquisition") or {}
        schedule = acquisition_entry.get("schedule") or {}
        if schedule:
            add(f"- istantanea fresca: {schedule.get('scheduled_matches')} partite a "
                f"calendario, {schedule.get('played_with_xg')} concluse con xG, "
                f"ultima data giocata `{schedule.get('last_played_date')}`; "
                f"acquisizione in {acquisition_entry.get('seconds')} s")
        for dataset in (PPDA_KIND, PLAYER_KIND):
            payload = (acquisition_entry.get("datasets") or {}).get(dataset) or {}
            coverage = payload.get("coverage") or {}
            if not coverage:
                continue
            errors = payload.get("errors") or []
            detail = (f"- {dataset}, copertura sull'istantanea fresca: mancanti "
                      f"**{_count(coverage.get('missing_total'))}** su "
                      f"{_count(coverage.get('reference_matches'))} "
                      f"(frontiera {_count(coverage.get('missing_frontier'))}, "
                      f"non frontiera {_count(coverage.get('missing_old'))}, "
                      f"senza data {_count(coverage.get('missing_undated'))})")
            if coverage.get("complete") is not None:
                detail += (f"; record completi {_count(coverage.get('complete'))}"
                           f" ({_pct(coverage.get('complete_ratio'))})")
            if coverage.get("returned_matches") is not None:
                detail += f"; partite restituite {_count(coverage.get('returned_matches'))}"
            if coverage.get("ppda_missing_but_deep_present"):
                detail += ("; coppie con deep presente e PPDA assente (denominatore "
                           "difensivo nullo): "
                           + _count(coverage.get("ppda_missing_but_deep_present")))
            if payload.get("retry_rounds"):
                detail += f"; tentativi di recupero {payload.get('retry_rounds')}"
            duplicates = payload.get("duplicates") or {}
            if duplicates.get("duplicate_rows"):
                detail += (f"; righe doppie tolte {_count(duplicates.get('duplicate_rows'))} "
                           f"su {_count(duplicates.get('input_rows'))} "
                           f"({_pct(duplicates.get('duplicate_ratio'))}, "
                           f"{_count(duplicates.get('duplicate_matches'))} partite)")
            if payload.get("unreadable_matches"):
                detail += (f"; partite illeggibili (payload che rompe soccerdata) "
                           f"{_count(payload.get('unreadable_matches'))}")
            if errors:
                detail += f"; **errori**: {'; '.join(str(e) for e in errors)}"
            add(detail)
            unreadable = payload.get("unreadable_sample") or []
            if unreadable:
                add("- partite illeggibili (id: errore): "
                    + "; ".join(f"`{item.get('id')}`: {item.get('error')}"
                                for item in unreadable[:5]))
            sample = payload.get("missing_matches_sample") or []
            if sample:
                add("- esempi di partite mancanti sull'istantanea fresca (max 8): "
                    + "; ".join(str(item) for item in sample[:8]))
        add("")

    # --------------------------------------------------------------- minuti
    add("## 4. Minuti giocati per partita (statistiche giocatore)")
    add("")
    add("Serve a decidere se una media \"per 90 minuti\" e' utilizzabile cosi' "
        "com'e' o se serve un minutaggio minimo: le righe con 0 minuti non hanno "
        "un denominatore per-90, e le rose Understat includono chi non entra.")
    add("")
    add("| Lega | Righe | Partite | Giocatori | Minuti p50 | Minuti p95 | "
        "Righe a 0 minuti | Giocatori/partita (p50) |")
    add("|---|---|---|---|---|---|---|---|")
    global_rows = 0
    global_zero = 0
    for league in leagues:
        entry = leagues[league]
        minutes = entry.get("minutes")
        if not minutes:
            continue
        dist = minutes.get("minutes") or {}
        players_per_match = minutes.get("players_per_match") or {}
        add(f"| {league} | {minutes['rows']} | {minutes['matches']} | "
            f"{minutes['players']} | {_num(dist.get('p50'), 1)} | "
            f"{_num(dist.get('p95'), 1)} | {minutes['zero_minutes_rows']} "
            f"({_pct(minutes['zero_minutes_share'])}) | "
            f"{_num(players_per_match.get('p50'), 1)} |")
        global_rows += minutes["rows"]
        global_zero += minutes["zero_minutes_rows"]
    add("")
    if global_rows:
        add(f"Totale: {global_rows} righe giocatore-partita, {global_zero} con 0 "
            f"minuti ({_pct(global_zero / global_rows)}), "
            f"{_pct(1 - global_zero / global_rows)} con minuti > 0 "
            "(le sole utilizzabili in una media per-90 senza moltiplicatori).")
        add("")
    add("### Minutaggio minimo: quanto dato si perderebbe")
    add("")
    add("Soglia sul **totale stagionale per giocatore** (somma dei minuti delle "
        "partite acquisite), calcolata su tutte le leghe insieme:")
    add("")
    add("| Soglia minuti | Giocatori | Righe | Quota righe | Minuti | Quota minuti |")
    add("|---|---|---|---|---|---|")
    aggregated: Dict[int, dict] = {}
    for league in leagues:
        minutes = leagues[league].get("minutes")
        if not minutes:
            continue
        for bucket in minutes["thresholds"]:
            slot = aggregated.setdefault(bucket["threshold"], {
                "players": 0, "rows": 0, "minutes": 0})
            slot["players"] += bucket["players"]
            slot["rows"] += bucket["rows"]
            slot["minutes"] += bucket["minutes"]
    total_rows_all = sum((leagues[league].get("minutes") or {}).get("rows", 0)
                         for league in leagues)
    total_minutes_all = sum((leagues[league].get("minutes") or {})
                            .get("minutes", {}).get("mean", 0)
                            * (leagues[league].get("minutes") or {}).get("minutes", {}).get("n", 0)
                            for league in leagues)
    for threshold in sorted(aggregated):
        slot = aggregated[threshold]
        add(f"| >= {threshold} | {slot['players']} | {slot['rows']} | "
            f"{_pct(slot['rows'] / total_rows_all if total_rows_all else None)} | "
            f"{slot['minutes']:.0f} | "
            f"{_pct(slot['minutes'] / total_minutes_all if total_minutes_all else None)} |")
    add("")

    # ------------------------------------------------------------------ nomi
    add("## 5. Nomi delle squadre (resolver condiviso della PR #15)")
    add("")
    add("Nessuna tabella nuova: i file conservano i nomi grezzi di Understat e "
        "l'audit li risolve con `team_names.resolve_team_name` (unione di "
        "`TEAM_NAME_MAP` e `UNDERSTAT_NAME_MAP`). Un nome non risolto non viene "
        "indovinato.")
    add("")
    add("| Lega | Dataset | Nomi grezzi | Non risolti | Collisioni |")
    add("|---|---|---|---|---|")
    for league in leagues:
        for dataset in (PPDA_KIND, PLAYER_KIND):
            names = (leagues[league].get("names") or {}).get(dataset)
            if not names:
                continue
            add(f"| {league} | {dataset} | {names['raw_names']} | "
                f"{len(names['unmapped'])} | {len(names['collisions'])} |")
    add("")
    for league in leagues:
        for dataset in (PPDA_KIND, PLAYER_KIND):
            names = (leagues[league].get("names") or {}).get(dataset)
            if not names:
                continue
            if names["unmapped"]:
                add(f"- {league}/{dataset}: non risolti "
                    + ", ".join(f"`{name}` ({count})"
                                for name, count in list(names["unmapped"].items())[:20]))
            if names["collisions"]:
                add(f"- {league}/{dataset}: collisioni "
                    + "; ".join(f"`{canonical}` <- {raws}"
                                for canonical, raws in list(names["collisions"].items())[:10]))
    add("")

    # ------------------------------------------------------- campi disponibili
    add("## 6. Cosa espone `soccerdata==1.9.1` e cosa non espone")
    add("")
    add("Verificato sul sorgente della versione pinnata "
        "(`soccerdata/understat.py`), non dedotto dai risultati.")
    add("")
    add("**Esposti**")
    add("")
    for method, fields in SOCCERDATA_EXPOSED.items():
        add(f"- `Understat.{method}()`: " + ", ".join(f"`{field}`" for field in fields))
    add("")
    add("**Non esposti (dichiarati, non aggirati con ripieghi silenziosi)**")
    add("")
    for item in SOCCERDATA_NOT_EXPOSED:
        add(f"- {item}")
    add("")

    # ------------------------------------------------------------------ costi
    add("## 7. Costo dell'acquisizione (misurato)")
    add("")
    add("| Lega | Secondi (lega) | Partite richieste (giocatore) | Righe | "
        "Tentativi di recupero | File PPDA/deep | File giocatore |")
    add("|---|---|---|---|---|---|---|")
    for league in leagues:
        entry = leagues[league]
        acquisition_entry = entry.get("acquisition") or {}
        player_payload = (acquisition_entry.get("datasets") or {}).get(PLAYER_KIND) or {}
        add(f"| {league} | {acquisition_entry.get('seconds', 'n/d')} | "
            f"{player_payload.get('requested_matches', 'n/d')} | "
            f"{(entry.get('summary_player') or {}).get('rows', 'n/d')} | "
            f"{player_payload.get('retry_rounds', 'n/d')} | "
            f"{_bytes((entry['files'].get(PPDA_KIND) or {}).get('bytes'))} | "
            f"{_bytes((entry['files'].get(PLAYER_KIND) or {}).get('bytes'))} |")
    add("")
    if acquisition.get("available"):
        add(f"- `--parallel-leagues`: {acquisition.get('parallel_leagues')}; "
            f"`--retries`: {acquisition.get('retries')}; "
            f"`--frontier-days`: {acquisition.get('frontier_days')}; "
            f"tolleranza partite non di frontiera: "
            f"{acquisition.get('missing_tolerance_ratio')}")
        if acquisition.get("sample_matches_per_league"):
            add(f"- **campione dichiarato**: solo le "
                f"{acquisition['sample_matches_per_league']} partite piu' recenti "
                "per lega (il perimetro non e' completo)")
        add("")
        add("Chiamate HTTP per lega (soccerdata 1.9.1): 1 payload di lega per "
            "`read_schedule()` + 1 per `read_team_match_stats()` "
            "(~4 MB ciascuno) + **1 richiesta per partita** per "
            "`read_player_match_stats()`.")
        add("")

    # --------------------------------------------------------------- limiti
    add("## 8. Limiti dichiarati")
    add("")
    add("- Understat non pubblica **snapshot datati**: la disponibilita' reale al "
        "momento della partita non e' ricostruibile a posteriori, si misura solo "
        "la frontiera (confronto fra il file acquisito e l'archivio xG committato, "
        "piu' il confronto a partita sull'istantanea fresca);")
    add("- gli xG di Understat possono essere **rivisti** dopo la partita: l'ultimo "
        "valore non e' quello pubblicato all'epoca;")
    add("- il ritardo misurato vale per **questo** istante di acquisizione: un "
        "buco su una partita vecchia e' strutturale, un buco sull'ultima giornata "
        "puo' essere solo un ritardo di pubblicazione;")
    add("- le righe doppie sulla chiave primaria sono **tolte e contate** "
        "(tenuta la riga piu' ricca): nascono da partite elencate due volte nel "
        "payload di lega, che soccerdata percorre due volte; sopra la soglia "
        "dichiarata la lega non viene pubblicata;")
    add("- `PPDA` nullo con `deep completions` presente su entrambi i lati e' il "
        "caso strutturale di `pd.NA` (denominatore difensivo 0): non e' un campo "
        "perduto, e' contato a parte e non entra fra le partite mancanti;")
    add("- `read_player_match_stats()` non distingue \"payload assente\" da "
        "`ConnectionError` inghiottito: le partite senza righe sono trattate come "
        "mancanti e riprovate, mai come 0 giocatori;")
    add("- la copertura e' misurata rispetto all'**archivio xG** (partite concluse "
        "con entrambi gli xG): partite assenti dall'archivio non entrano nel "
        "denominatore;")
    add("- le statistiche giocatore sono per **partita**, non per 90 minuti "
        "ufficiali: i minuti sono il campo `time` di Understat (include il "
        "recupero);")
    add("- nessuna soglia, formula o peso del motore e' stato toccato: nessuna "
        "delle tre feature e' collegata al motore Poisson/Elo in questa fase.")
    add("")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def build_report(args) -> dict:
    acquisition_path = args.acquisition_report
    acquisition = None
    if acquisition_path and os.path.exists(acquisition_path):
        with open(acquisition_path, "r", encoding="utf-8") as f:
            acquisition = json.load(f)
    reference = None
    if acquisition and acquisition.get("generated_at"):
        parsed, _ = parse_kickoff(acquisition["generated_at"])
        reference = parsed
    reference = reference or datetime.now(timezone.utc)

    blocks = acquisition_blocks(acquisition)
    leagues: Dict[str, dict] = {}
    for league in LEAGUES:
        leagues[league] = analyse_league(
            league, args.database_dir, args.xg_dir, reference=reference,
            acquisition=(blocks.get("leagues") or {}).get(league))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reference_time": reference.isoformat(),
        "database_dir": os.path.abspath(args.database_dir),
        "xg_dir": os.path.abspath(args.xg_dir),
        "acquisition_report": (os.path.abspath(acquisition_path)
                               if acquisition_path else None),
        "datasets": list(args.datasets),
        "run_url": args.run_url,
        "run_id": args.run_id,
        "leagues": leagues,
        "acquisition": blocks,
        "soccerdata_exposed": SOCCERDATA_EXPOSED,
        "soccerdata_not_exposed": SOCCERDATA_NOT_EXPOSED,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit di copertura e qualita' di PPDA/deep completions e "
                    "statistiche giocatore per partita")
    parser.add_argument("--database-dir", default=REPO_DB_DIR,
                        help="cartella con i nuovi archivi (default: SoccerMath/database)")
    parser.add_argument("--xg-dir", default=REPO_DB_DIR,
                        help="cartella dell'archivio xG di riferimento "
                             "(default: SoccerMath/database)")
    parser.add_argument("--acquisition-report", default=None,
                        help="report JSON prodotto da update_all_ppda_player_db.py")
    parser.add_argument("--results-dir", default=RESULTS_DIR,
                        help="cartella dei report (default: audit/results)")
    parser.add_argument("--datasets", nargs="+", default=[PPDA_KIND, PLAYER_KIND],
                        choices=[PPDA_KIND, PLAYER_KIND])
    parser.add_argument("--run-url", default=None,
                        help="URL dell'esecuzione reale (per il referto)")
    parser.add_argument("--run-id", default=None,
                        help="id dell'esecuzione (nome dell'artifact)")
    args = parser.parse_args(argv)

    report = build_report(args)
    markdown = render_markdown(
        report, generated_at=report["generated_at"], run_url=args.run_url,
        run_id=args.run_id, args=args)

    os.makedirs(args.results_dir, exist_ok=True)
    markdown_path = os.path.join(args.results_dir, f"{REPORT_BASENAME}.md")
    json_path = os.path.join(args.results_dir, f"{REPORT_BASENAME}.json")
    with open(markdown_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")

    print(markdown)
    print(f"\nReport scritti in: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
