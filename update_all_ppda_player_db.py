"""
update_all_ppda_player_db.py - Acquisizione Understat di DUE archivi NUOVI,
nella stessa forma di ``update_all_xg_db.py`` (unico posto in cui si scarica, un
solo snapshot, validazione prima della sostituzione):

  1. ``SoccerMath/database/ppda_deep_<lega>.json``
     PPDA (passes allowed per defensive action) e deep completions, per squadra
     per partita, da ``soccerdata.Understat.read_team_match_stats()``.

         {"season": 2022, "id": 16960, "date": "2022-08-13 18:45:00",
          "home_team": "Inter", "away_team": "Torino", "is_result": true,
          "home_ppda": 8.13, "away_ppda": 11.2,
          "home_deep_completions": 12, "away_deep_completions": 5}

  2. ``SoccerMath/database/player_match_<lega>.json``
     Statistiche giocatore per partita, da
     ``soccerdata.Understat.read_player_match_stats()``: una riga per giocatore
     per partita (minuti, gol, tiri, xG, xA, xGChain, xGBuildup, cartellini).

Nessuno dei due file viene letto da ``app.py``, ``config.py`` o ``models/``:
l'archivio xG (``xG archivio <lega>.json``) e le medie derivate restano
intoccati, questi sono file NUOVI di acquisizione/audit.

Disciplina di pubblicazione (la stessa dell'archivio xG):
  * i tipi pandas nullable vengono normalizzati in tipi JSON nativi
    (``pd.NA``/``NaT`` -> ``null``);
  * schema e copertura vengono validati PRIMA di sostituire il file precedente;
  * il nuovo snapshot viene confrontato con l'ultimo valido PARTITA PER PARTITA
    (chiave stagione + id): perdere una partita che aveva i dati, o una stagione
    intera, blocca; le partite "di frontiera" (piu' recenti di
    ``--frontier-days``, default 1 giorno) possono mancare senza bloccare, ma
    vengono contate e riportate;
  * la scrittura e' atomica (file temporaneo + ``os.replace``);
  * se una lega fallisce, l'ultimo file valido resta al suo posto e lo script
    esce con codice diverso da zero (il workflow non pubblica nulla).

Copertura e "nessun fallback silenzioso":
  * il perimetro di riferimento e' lo snapshot FRESCO del calendario
    (``read_schedule()``, stessa fonte, stessa istantanea) ristretto alle
    partite concluse con entrambi gli xG: e' il denominatore dei conteggi di
    copertura, confrontabile con l'archivio xG committato;
  * per PPDA/deep si contano quattro esiti per partita (completo, parziale,
    record senza valori, record assente). Una partita NON di frontiera che non
    e' completa oltre la tolleranza dichiarata (``--missing-tolerance-ratio``,
    default 0.0) fa FALLIRE la lega: la fonte non ha dato quei campi e non si
    ripiega su un'altra fonte. Le partite di frontiera sono riportate;
  * per le statistiche giocatore una partita del perimetro senza righe e'
    MANCANTE: soccerdata non espone un canale d'errore per singola partita
    (``_read_match`` inghiotte ``ConnectionError`` e salta la partita), quindi
    non si assume che "nessuna riga" significhi "nessun giocatore". Le partite
    mancanti vengono riprovate (``--retries``) con cache disattivata;
  * se una colonna richiesta non esiste nel DataFrame di soccerdata (per
    esempio PPDA/deep o i roster in una release diversa), la lega fallisce con
    l'elenco delle colonne trovate.

Difetti della fonte osservati sull'acquisizione reale del 2026-09-15 e come
vengono trattati (tutti dichiarati nel report, nessuno silenzioso):
  * **partite elencate due volte** nel payload di lega: soccerdata le percorre
    due volte e le righe giocatore escono doppie (La Liga: 91 righe su ~48.000).
    Il calendario viene deduplicato su (stagione, id) prima di costruire il
    perimetro, le righe doppie sono tolte tenendo la piu' ricca e il numero di
    righe tolte finisce nel report; sopra ``--max-duplicate-rows-ratio``
    (default 2%) la lega non viene pubblicata;
  * **PPDA non calcolabile** (denominatore difensivo 0): soccerdata restituisce
    ``pd.NA`` mentre ``deep completions`` e' presente sullo stesso lato
    (Bundesliga: 1 partita su 1251). Non e' un campo perduto: e' contato come
    caso strutturale, non blocca e non entra fra le partite mancanti, ma sopra
    ``--max-structural-na-ratio`` (default 1%) la lega non viene pubblicata;
  * **payload che rompe soccerdata**: un formato inatteso (per esempio
    ``rosters`` come lista) fa fallire l'INTERA chiamata per-partita, perdendo
    le partite gia' lette. La richiesta viene ripetuta a meta' fino a isolare la
    partita rotta, che viene dichiarata illeggibile (id + errore) e resta
    MANCANTE nella copertura; le altre partite non vanno perse.

Nomi delle squadre: i file conservano i nomi grezzi di Understat, come fa
l'archivio xG; la normalizzazione resta quella condivisa della PR #15
(``team_names.resolve_team_name``). Qui non esiste nessuna tabella di nomi.

Uso:
    python update_all_ppda_player_db.py
    python update_all_ppda_player_db.py --league "Serie A" --seasons 2526
    python update_all_ppda_player_db.py --datasets ppda_deep
    python update_all_ppda_player_db.py --sample-matches-per-league 50 --dry-run
    python update_all_ppda_player_db.py \
        --output-dir /tmp/verify/database --baseline-dir SoccerMath/database \
        --report /tmp/verify/acquisizione.json      # modalita' verifica
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from match_stats_archive import (  # noqa: E402
    DEFAULT_FRONTIER_DAYS,
    DEFAULT_MAX_THIN_MATCHES_RATIO,
    DEFAULT_MIN_PLAYED_FIELD_COVERAGE,
    DEFAULT_MIN_ROWS_PER_MATCH,
    PLAYER_KIND,
    PPDA_FILES,
    PPDA_KIND,
    archive_path,
    clean_text,
    compare_player_snapshots,
    compare_ppda_snapshots,
    dedupe_records,
    json_safe,
    name_resolution_report,
    normalize_player_record,
    normalize_ppda_record,
    parse_bool,
    parse_int,
    parse_season,
    player_summary,
    ppda_gap_kind,
    ppda_summary,
    record_completeness,
    validate_player,
    validate_ppda,
    write_atomic,
)
from xg_archive import (  # noqa: E402
    SOCCERDATA_LEAGUES,
    parse_kickoff,
    parse_xg,
)

sys.path.insert(0, _REPO_ROOT)
from update_all_xg_db import derive_seasons  # noqa: E402  (stessa finestra dell'archivio xG)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("update_all_ppda_player_db")

# Stagioni richieste a soccerdata: le stesse dell'archivio xG, finestra mobile
# derivata dalla data (stagione corrente + 4 precedenti, confine 1° luglio).
SEASONS: List[str] = derive_seasons()

# Versione di soccerdata verificata per queste colonne/questo formato.
REQUIRED_SOCCERDATA_VERSION = "1.9.1"

DEFAULT_OUTPUT_DIR = os.path.join(_REPO_ROOT, "SoccerMath", "database")

# Colonne di Understat.read_team_match_stats() usate (verificate su 1.9.1).
TEAM_STATS_COLUMNS: Dict[str, str] = {
    "season_id": "season_id",
    "game_id": "game_id",
    "date": "date",
    "home_team": "home_team",
    "away_team": "away_team",
    "home_ppda": "home_ppda",
    "away_ppda": "away_ppda",
    "home_deep_completions": "home_deep_completions",
    "away_deep_completions": "away_deep_completions",
}

# Colonne di Understat.read_player_match_stats() usate (verificate su 1.9.1).
PLAYER_STATS_COLUMNS: Tuple[str, ...] = (
    "season_id", "game_id", "game", "team", "player", "player_id", "position", "minutes",
    "goals", "own_goals", "shots", "xg", "xg_chain", "xg_buildup",
    "assists", "xa", "key_passes", "yellow_cards", "red_cards",
)

# Rete di sicurezza GROSSOLANA sul volume, secondaria rispetto al confronto
# partita-per-partita: un file che perde piu' di questa frazione di righe o di
# partite rispetto al precedente e' sospetto anche senza perdite "identificate".
MAX_SHRINK_RATIO = 0.10

# Minimi di schema per "questo file e' plausibile": partite attese per stagione
# richiesta (archivio xG) e righe giocatore attese per stagione richiesta.
MIN_MATCHES_PER_SEASON = 100
MIN_ROWS_PER_SEASON = 200

# Righe doppie tolte sulla chiave primaria: sotto questa frazione e' un difetto
# puntuale della fonte (dichiarato nel report), sopra non e' piu' puntuale.
MAX_DUPLICATE_ROWS_RATIO = 0.02

# Partite con PPDA non calcolabile (denominatore difensivo nullo, deep presente):
# e' un caso strutturale, non un campo perso, ma se diventa sistematico vuol dire
# che la fonte non espone piu' il campo per un'intera stagione.
MAX_STRUCTURAL_NA_RATIO = 0.01


# ---------------------------------------------------------------------------
# Ambiente / versione della libreria
# ---------------------------------------------------------------------------
def check_soccerdata_version(strict: bool = False) -> str:
    """Versione di soccerdata installata (colonne verificate su 1.9.1)."""
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
        log.warning("%s: le colonne di read_team_match_stats()/read_player_match_stats() "
                    "sono verificate solo sulla versione dichiarata", message)
    else:
        log.info("soccerdata %s (versione verificata)", installed)
    return installed


def _cache_subdir(cache_dir: str, league: str) -> str:
    """Sottocartella di cache per lega (nessuna scrittura concorrente)."""
    safe = "".join(ch if ch.isalnum() else "_" for ch in league).lower()
    return os.path.join(cache_dir, safe)


def _make_reader(sd_league: str, seasons: Sequence[str], cache_dir: str, *,
                 no_cache: bool):
    """Istanza di ``sd.Understat`` con cache isolata nella cartella indicata.

    La cache vive in una cartella del run (``--cache-dir``): nessun file puo'
    arrivare da un'esecuzione precedente. Serve a non riscaricare i payload di
    lega (~4 MB ciascuno) che soccerdata richiede piu' volte nello stesso run:
    la prima lettura e' di rete, le successive leggono il payload scritto pochi
    secondi prima, cioe' la stessa istantanea.
    """
    import soccerdata as sd
    from pathlib import Path

    return sd.Understat(leagues=sd_league, seasons=list(seasons),
                        no_cache=no_cache, no_store=False,
                        data_dir=Path(cache_dir))


# ---------------------------------------------------------------------------
# Conversione dei DataFrame di soccerdata in record JSON
# ---------------------------------------------------------------------------
def _format_kickoff(kickoff) -> Optional[str]:
    """Data nel formato dell'archivio xG: "YYYY-MM-DD HH:MM:SS", senza offset.

    ``xg_archive.parse_kickoff`` interpreta i record senza offset in UTC
    (``ARCHIVE_TIMEZONE``): scrivere l'offset qui sarebbe una seconda
    convenzione per lo stesso dato.
    """
    if kickoff is None:
        return None
    return kickoff.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def perimeter_from_schedule(df) -> List[dict]:
    """Calendario fresco -> perimetro delle partite CONCLUSE con entrambi gli xG.

    Questo snapshot e' usato solo in memoria: definisce il denominatore dei
    conteggi di copertura e l'elenco delle partite richieste a soccerdata. Non
    viene scritto da nessuna parte (l'archivio xG resta di
    ``update_all_xg_db.py``).
    """
    if df is None or len(df) == 0:
        return []
    frame = df.reset_index()
    required = ("season_id", "game_id", "date", "home_team", "away_team",
                "home_xg", "away_xg", "is_result")
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise ValueError(
            "colonne mancanti nel risultato di read_schedule(): "
            f"{missing} (trovate: {sorted(frame.columns)})")
    records: List[dict] = []
    for row in frame.to_dict(orient="records"):
        home_xg_raw = json_safe(row.get("home_xg"))
        away_xg_raw = json_safe(row.get("away_xg"))
        home_xg = parse_xg(home_xg_raw)
        away_xg = parse_xg(away_xg_raw)
        kickoff, _ = parse_kickoff(json_safe(row.get("date")))
        records.append({
            "season": parse_season(json_safe(row.get("season_id"))),
            "id": parse_int(json_safe(row.get("game_id"))),
            "date": _format_kickoff(kickoff),
            "home_team": clean_text(json_safe(row.get("home_team"))),
            "away_team": clean_text(json_safe(row.get("away_team"))),
            "is_result": parse_bool(json_safe(row.get("is_result"))),
            # "ha dati" e' la definizione usata da soccerdata in
            # read_schedule(include_matches_without_data=False): xG presente.
            "has_data": home_xg_raw is not None or away_xg_raw is not None,
            "both_xg": home_xg is not None and away_xg is not None,
        })
    return records


def records_from_team_match_stats(df, schedule: Sequence[dict]) -> List[dict]:
    """DataFrame di ``read_team_match_stats()`` -> record PPDA/deep.

    ``is_result`` non e' esposto da ``read_team_match_stats()`` ma viene dallo
    STESSO documento JSON (``datesData``) letto nello stesso istante: il join
    per ``game_id`` usa lo snapshot del calendario del run. Un ``game_id``
    assente dal calendario resta ``None`` e viene contato, non inventato.
    """
    if df is None or len(df) == 0:
        return []
    frame = df.reset_index()
    missing = [c for c in TEAM_STATS_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(
            "colonne mancanti nel risultato di read_team_match_stats(): "
            f"{missing} (trovate: {sorted(frame.columns)}). Se PPDA/deep non "
            "esistono nella versione di soccerdata installata, questa "
            "acquisizione NON ripiega su un'altra fonte.")
    by_id = {rec.get("id"): rec for rec in schedule if rec.get("id") is not None}
    records: List[dict] = []
    for row in frame.to_dict(orient="records"):
        values = {key: json_safe(row.get(column))
                  for key, column in TEAM_STATS_COLUMNS.items()}
        match_id = parse_int(values.get("game_id"))
        reference = by_id.get(match_id)
        kickoff, _ = parse_kickoff(values.get("date"))
        records.append(normalize_ppda_record({
            "season": parse_season(values.get("season_id")),
            "id": match_id,
            "date": _format_kickoff(kickoff),
            "home_team": values.get("home_team"),
            "away_team": values.get("away_team"),
            "is_result": reference.get("is_result") if reference else None,
            "home_ppda": values.get("home_ppda"),
            "away_ppda": values.get("away_ppda"),
            "home_deep_completions": values.get("home_deep_completions"),
            "away_deep_completions": values.get("away_deep_completions"),
        }))
    return records


def records_from_player_match_stats(df, schedule: Sequence[dict], *,
                                    match_ids: Optional[Sequence[int]] = None) -> List[dict]:
    """DataFrame di ``read_player_match_stats()`` -> righe per giocatore.

    La data non e' una colonna di questo output: soccerdata la incorpora
    nell'indice ``game`` ("YYYY-MM-DD Casa-Ospite", vedi
    ``_common.make_game_id``). La data viene quindi derivata dal prefisso di
    ``game`` e INCROCIATA con il calendario fresco dello stesso run: se le due
    versioni della stessa informazione non coincidono, la riga viene marcata
    (``date_mismatch``) e la lega fallisce.

    ``team``/``opponent``/``venue`` derivano da ``team`` + ``home_team``/
    ``away_team`` dello stesso record (nomi grezzi Understat).
    """
    if df is None or len(df) == 0:
        return []
    frame = df.reset_index()
    missing = [c for c in PLAYER_STATS_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(
            "colonne mancanti nel risultato di read_player_match_stats(): "
            f"{missing} (trovate: {sorted(frame.columns)}). Se i roster non "
            "esistono nella versione di soccerdata installata, questa "
            "acquisizione NON ripiega su un'altra fonte.")
    allowed = set(match_ids) if match_ids is not None else None
    by_id = {rec.get("id"): rec for rec in schedule if rec.get("id") is not None}
    records: List[dict] = []
    for row in frame.to_dict(orient="records"):
        values = {key: json_safe(row.get(key)) for key in PLAYER_STATS_COLUMNS}
        match_id = parse_int(values.get("game_id"))
        if allowed is not None and match_id not in allowed:
            continue
        reference = by_id.get(match_id) or {}
        game_text = clean_text(values.get("game")) or ""
        derived_date = game_text[:10] if len(game_text) >= 10 else None
        reference_date = (reference.get("date") or "")[:10] or None
        kickoff, _ = parse_kickoff(reference.get("date"))
        frame_season = parse_season(values.get("season_id"))
        reference_season = reference.get("season")
        record = normalize_player_record({
            # la stagione e' un dato della riga (season_id di soccerdata); il
            # calendario serve da incrocio, non da sostituto silenzioso
            "season": frame_season if frame_season is not None else reference_season,
            "id": match_id,
            "date": kickoff.date().isoformat() if kickoff else derived_date,
            "team": values.get("team"),
            "opponent": None,
            "venue": None,
            "player_id": values.get("player_id"),
            "player": values.get("player"),
            "position": values.get("position"),
            "minutes": values.get("minutes"),
            "goals": values.get("goals"),
            "own_goals": values.get("own_goals"),
            "shots": values.get("shots"),
            "xg": values.get("xg"),
            "xg_chain": values.get("xg_chain"),
            "xg_buildup": values.get("xg_buildup"),
            "assists": values.get("assists"),
            "xa": values.get("xa"),
            "key_passes": values.get("key_passes"),
            "yellow_cards": values.get("yellow_cards"),
            "red_cards": values.get("red_cards"),
        })
        team = record.get("team")
        home = reference.get("home_team")
        away = reference.get("away_team")
        if team and home and away:
            if team == home:
                record["opponent"], record["venue"] = away, "home"
            elif team == away:
                record["opponent"], record["venue"] = home, "away"
        record["date_mismatch"] = bool(
            derived_date and reference_date and derived_date != reference_date)
        record["season_mismatch"] = bool(
            frame_season is not None and reference_season is not None
            and frame_season != reference_season)
        record["date_source"] = ("schedule" if kickoff else
                                 ("game_id_prefix" if derived_date else None))
        records.append(record)
    return records


# ---------------------------------------------------------------------------
# Perimetro, copertura, frontiera
# ---------------------------------------------------------------------------
def _dedupe_schedule(records: Sequence[dict]) -> Tuple[List[dict], dict]:
    """Una sola riga per (stagione, id partita).

    Il payload di lega puo' elencare due volte la stessa partita: soccerdata
    percorrerebbe due volte quella riga e le statistiche giocatore verrebbero
    acquisite due volte per gli stessi giocatori. Si tiene la variante piu'
    informativa (con xG su entrambi i lati) e si CONTANO le righe tolte.
    """
    kept: Dict[Tuple, dict] = {}
    order: List[Tuple] = []
    duplicates = 0
    for rec in records or []:
        key = (rec.get("season"), rec.get("id"))
        previous = kept.get(key)
        if previous is None:
            kept[key] = rec
            order.append(key)
            continue
        duplicates += 1
        def rank(item: dict) -> Tuple:
            return (bool(item.get("both_xg")), bool(item.get("has_data")),
                    bool(item.get("date")))
        if rank(rec) > rank(previous):
            kept[key] = rec
    stats = {"scheduled_rows": len(records or []), "rows": len(kept),
             "duplicate_rows": duplicates,
             "duplicate_ratio": (duplicates / len(records or []) if records else 0.0)}
    return [kept[key] for key in order], stats


def played_perimeter(schedule: Sequence[dict]) -> List[dict]:
    """Partite concluse con entrambi gli xG numerici (denominatore di copertura)."""
    return [rec for rec in schedule
            if rec.get("is_result") and rec.get("both_xg") and rec.get("id") is not None]


def _age_days(entry: dict, reference: datetime) -> Optional[float]:
    kickoff, _ = parse_kickoff(entry.get("date"))
    if kickoff is None:
        return None
    return (reference - kickoff).total_seconds() / 86400.0


def _entry_label(entry: dict) -> str:
    return (f"[{entry.get('season')}] {entry.get('home_team')} - "
            f"{entry.get('away_team')} (id {entry.get('id')}, "
            f"{(entry.get('date') or 'data n/d')[:10]})")


def _missing_split(missing: Sequence[dict], reference: datetime,
                   frontier_days: float) -> Tuple[List[dict], List[dict], List[dict]]:
    """Divide le partite mancanti in (frontiera, vecchie, senza data)."""
    frontier: List[dict] = []
    old: List[dict] = []
    undated: List[dict] = []
    for entry in missing:
        enriched = dict(entry)
        enriched["age_days"] = _age_days(entry, reference)
        enriched["label"] = _entry_label(entry)
        if enriched["age_days"] is None:
            undated.append(enriched)
        elif enriched["age_days"] <= frontier_days:
            frontier.append(enriched)
        else:
            old.append(enriched)
    return frontier, old, undated


def _frontier_status(missing: Sequence[dict], reference_matches: int,
                     reference: datetime, frontier_days: float,
                     extra: Optional[dict] = None) -> dict:
    """Sintesi di copertura con separazione frontiera / partite vecchie.

    Bloccano solo le partite NON di frontiera (o senza data, che non si possono
    dimostrare recenti) oltre la tolleranza dichiarata: e' la stessa regola
    usata nel confronto fra snapshot, applicata al perimetro fresco.
    """
    frontier, old, undated = _missing_split(missing, reference, frontier_days)
    blocking = old + undated
    ratio = len(blocking) / reference_matches if reference_matches else 0.0
    status = {
        "reference_matches": reference_matches,
        "missing_total": len(missing),
        "missing_frontier": len(frontier),
        "missing_old": len(old),
        "missing_undated": len(undated),
        "missing_blocking_ratio": ratio,
        "frontier_days": frontier_days,
        "reference_time": reference.isoformat(),
        "missing_sample": [entry["label"] for entry in (blocking + frontier)[:20]],
    }
    if extra:
        status.update(extra)
    return status


def _load_baseline(path: str) -> Optional[List[dict]]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else None
    except Exception:
        return None


def _shrink_ratio(previous: Sequence[dict], current: Sequence[dict],
                  seasons: Sequence[Optional[int]]) -> Optional[float]:
    """Variazione di volume sulle sole stagioni richieste (rete secondaria)."""
    wanted = {s for s in seasons if s}
    in_scope = [rec for rec in previous
                if isinstance(rec, dict)
                and (not wanted or parse_season(rec.get("season")) in wanted)]
    if not in_scope:
        return None
    return 1.0 - (len(current) / len(in_scope))


def _names_for_report(records: Sequence[dict], kind: str) -> dict:
    report = name_resolution_report(records, kind=kind)
    return {"raw_names": report["raw_names"],
            "unmapped": report["unmapped"],
            "collisions": report["collisions"]}


# ---------------------------------------------------------------------------
# Acquisizione per lega - PPDA / deep completions
# ---------------------------------------------------------------------------
def acquire_ppda_deep(league: str, sd_league: str, seasons: Sequence[str], *,
                      output_dir: str, baseline_dir: Optional[str], cache_dir: str,
                      dry_run: bool, schedule: Sequence[dict],
                      allow_dropping_seasons: bool,
                      min_played_field_coverage: float, retries: int,
                      frontier_days: float, missing_tolerance_ratio: float,
                      max_duplicate_rows_ratio: float,
                      max_structural_na_ratio: float) -> dict:
    """PPDA/deep di una lega: scarica, valida, confronta e (se valido) scrive."""
    result: dict = {"dataset": PPDA_KIND, "league": league, "written": False,
                    "matches": 0, "errors": [], "retry_rounds": 0}
    path = archive_path(PPDA_KIND, league, output_dir)
    result["path"] = path

    perimeter = played_perimeter(schedule)
    perimeter_ids = {rec["id"] for rec in perimeter}
    result["requested_matches"] = len(perimeter)
    reference_time = datetime.now(timezone.utc)

    records: List[dict] = []
    try:
        for attempt in range(0, max(1, int(retries) + 1)):
            reader = _make_reader(sd_league, seasons, cache_dir, no_cache=True)
            fetched = records_from_team_match_stats(reader.read_team_match_stats(),
                                                    schedule)
            # unione per (stagione, id): un tentativo successivo puo' completare
            # i record arrivati senza i valori
            by_key = {(_key(rec)): rec for rec in records}
            for rec in fetched:
                key = _key(rec)
                previous = by_key.get(key)
                if previous is None or (
                        record_completeness(previous) != "completo"
                        and record_completeness(rec) == "completo"):
                    by_key[key] = rec
            records = list(by_key.values())
            result["retry_rounds"] = attempt
            incomplete = [rec for rec in records
                          if _key(rec)[1] not in perimeter_ids
                          or record_completeness(rec) != "completo"]
            if not incomplete:
                break
            if attempt < int(retries):
                log.info("%s: %d partite non complete, nuovo tentativo (%d/%d)",
                         league, len(incomplete), attempt + 1, retries)
    except Exception as exc:  # nessun file parziale, nessuna scrittura
        result["errors"].append(f"download/conversione falliti: {exc}")
        return result

    # Righe doppie sulla chiave (stagione, id): tolte e CONTATE (un payload di
    # lega che elenca due volte una partita produce record ripetuti).
    records, duplicates = dedupe_records(records, kind=PPDA_KIND)
    result["duplicates"] = duplicates
    if duplicates["duplicate_ratio"] > max_duplicate_rows_ratio:
        result["errors"].append(
            f"{duplicates['duplicate_rows']} record su {duplicates['input_rows']} "
            f"sono doppi sulla chiave (stagione, id partita) "
            f"({duplicates['duplicate_ratio']:.2%} > "
            f"{max_duplicate_rows_ratio:.2%}): la fonte ripete intere partite, "
            "il file non viene pubblicato")

    expected = [parse_season(s) for s in seasons]
    problems = validate_ppda(
        records, league=league,
        min_matches=MIN_MATCHES_PER_SEASON * max(1, len(seasons)),
        expected_seasons=[s for s in expected if s],
        min_played_field_coverage=min_played_field_coverage)
    result["summary"] = ppda_summary(records)
    result["names"] = _names_for_report(records, PPDA_KIND)

    # Copertura rispetto al perimetro fresco: un esito per partita. Il caso
    # "strutturale" (deep presente su entrambi i lati, PPDA nullo perche' il
    # denominatore difensivo e' 0) NON e' un campo perso: viene contato a parte
    # e non blocca, ma se diventa sistematico la lega fallisce.
    by_id = {_key(rec)[1]: rec for rec in records}
    counts = {"complete": 0, "partial": 0, "record_without_values": 0,
              "no_record": 0, "structural_ppda_na": 0,
              "ppda_missing_but_deep_present": 0}
    missing: List[dict] = []
    structural: List[dict] = []
    for entry in perimeter:
        record = by_id.get(entry["id"])
        if record is None:
            counts["no_record"] += 1
            missing.append(entry)
            continue
        completeness = record_completeness(record)
        if completeness == "completo":
            counts["complete"] += 1
            continue
        for side in ("home", "away"):
            has_ppda, has_deep = record.get(f"{side}_ppda"), record.get(
                f"{side}_deep_completions")
            if has_ppda is None and has_deep is not None:
                counts["ppda_missing_but_deep_present"] += 1
        if ppda_gap_kind(record) == "strutturale":
            counts["structural_ppda_na"] += 1
            structural.append(entry)
            continue
        counts["partial" if completeness == "parziale" else "record_without_values"] += 1
        missing.append(entry)
    if structural:
        result["structural_na_sample"] = [_entry_label(entry)
                                          for entry in structural[:20]]
    if (counts["structural_ppda_na"] / len(perimeter)
            if perimeter else 0.0) > max_structural_na_ratio:
        result["errors"].append(
            f"{counts['structural_ppda_na']} partite su {len(perimeter)} con PPDA "
            "non calcolabile (deep presente): sopra la soglia dichiarata "
            f"{max_structural_na_ratio:.2%} non e' piu' un caso puntuale della "
            "fonte, la lega non viene pubblicata")
    result["coverage"] = _frontier_status(
        missing, len(perimeter), reference_time, frontier_days, extra=counts)
    if perimeter:
        result["coverage"]["complete_ratio"] = counts["complete"] / len(perimeter)

    if problems:
        result["errors"].extend(problems)
    if (result["coverage"].get("missing_blocking_ratio", 0.0)
            > missing_tolerance_ratio):
        result["errors"].append(
            f"{result['coverage']['missing_old'] + result['coverage']['missing_undated']} "
            f"partite su {len(perimeter)} NON di frontiera senza PPDA/deep completi "
            f"({result['coverage']['missing_blocking_ratio']:.2%} > tolleranza "
            f"{missing_tolerance_ratio:.2%}): la fonte non espone quei campi su "
            "queste partite (esiti: "
            f"parziali {counts['partial']}, record senza valori "
            f"{counts['record_without_values']}, record assenti {counts['no_record']}) "
            "- nessun ripiego su un'altra fonte")
    if result["errors"]:
        return result

    baseline_path = path
    if baseline_dir:
        baseline_path = archive_path(PPDA_KIND, league, baseline_dir)
    result["baseline_path"] = baseline_path
    previous = _load_baseline(baseline_path)
    result["baseline_found"] = bool(previous)
    if previous:
        result["previous_matches"] = len(previous)
        diff = compare_ppda_snapshots(
            previous, records, league=league,
            requested_seasons=[s for s in expected if s],
            allow_dropping_seasons=allow_dropping_seasons)
        result["diff"] = diff.to_dict()
        if diff.blocking_problems:
            result["errors"].extend(diff.blocking_problems)
            result["errors"].append("file PPDA/deep precedente lasciato invariato")
            return result
        shrink = _shrink_ratio(previous, records, expected)
        result["shrink_ratio"] = shrink
        if shrink is not None and shrink > MAX_SHRINK_RATIO:
            result["errors"].append(
                f"file nuovo con {len(records)} partite contro le "
                f"{len(previous)} precedenti sulle stesse stagioni "
                f"(-{shrink:.0%}): acquisizione parziale, file esistente "
                "lasciato invariato")
            return result

    result["matches"] = len(records)
    if not dry_run:
        write_atomic(path, records)
        result["written"] = True
    return result


def _key(record: dict) -> Tuple[Optional[int], Optional[int]]:
    return (parse_season(record.get("season")), parse_int(record.get("id")))


def fetch_player_stats(reader_factory, match_ids: Sequence[int], *,
                       base_dir: str, schedule: Sequence[dict],
                       unreadable: List[dict]) -> List[dict]:
    """Righe giocatore per le partite richieste, isolando quelle illeggibili.

    ``Understat.read_player_match_stats()`` chiama ``getMatchData`` una volta per
    partita e inghiotte SOLO ``ConnectionError``: qualunque altro errore (un
    payload con una forma diversa, una risposta HTTP non 2xx) interrompe l'intera
    chiamata, perdendo le migliaia di partite gia' lette. Qui, se la richiesta
    fallisce, l'intervallo viene ripetuto a meta' fino a isolare la singola
    partita: quella viene dichiarata illeggibile (id + errore, nel report) e le
    altre proseguono. Le partite illeggibili restano MANCANTI nella copertura.
    """
    records: List[dict] = []
    stack: List[List[int]] = [list(match_ids)]
    while stack:
        chunk = stack.pop()
        if not chunk:
            continue
        try:
            frame = reader_factory(base_dir).read_player_match_stats(match_id=chunk)
        except Exception as exc:
            if len(chunk) == 1:
                unreadable.append({"id": chunk[0],
                                   "error": f"{type(exc).__name__}: {exc}"})
                continue
            middle = len(chunk) // 2
            stack.append(chunk[:middle])
            stack.append(chunk[middle:])
            continue
        if frame is None or len(frame) == 0:
            # nessuna riga per questo intervallo: soccerdata non distingue il
            # payload assente dal ConnectionError inghiottito, quindi la partita
            # resta mancante e viene riprovata (mai contata come 0 giocatori)
            continue
        records.extend(records_from_player_match_stats(
            frame, schedule, match_ids=chunk))
    return records


# ---------------------------------------------------------------------------
# Acquisizione per lega - statistiche giocatore
# ---------------------------------------------------------------------------
def acquire_player_match(league: str, sd_league: str, seasons: Sequence[str], *,
                         output_dir: str, baseline_dir: Optional[str], cache_dir: str,
                         dry_run: bool, schedule: Sequence[dict],
                         allow_dropping_seasons: bool, retries: int,
                         frontier_days: float, missing_tolerance_ratio: float,
                         sample_matches: Optional[int],
                         min_rows_per_match: int,
                         max_thin_matches_ratio: float,
                         max_duplicate_rows_ratio: float) -> dict:
    """Statistiche giocatore di una lega: scarica, valida, confronta e scrive."""
    result: dict = {"dataset": PLAYER_KIND, "league": league, "written": False,
                    "rows": 0, "matches": 0, "errors": [], "retry_rounds": 0,
                    "seconds": None}
    path = archive_path(PLAYER_KIND, league, output_dir)
    result["path"] = path

    perimeter = played_perimeter(schedule)
    if sample_matches:
        ordered = sorted(perimeter, key=lambda rec: rec.get("date") or "")
        perimeter = ordered[-int(sample_matches):]
        result["sample"] = {"requested": int(sample_matches), "mode": "most_recent"}
    match_ids = [rec["id"] for rec in perimeter]
    result["requested_matches"] = len(match_ids)
    reference_time = datetime.now(timezone.utc)
    if not match_ids:
        result["errors"].append("perimetro vuoto: nessuna partita conclusa con xG "
                                "nelle stagioni richieste")
        return result

    started = time.monotonic()
    records: List[dict] = []
    unreadable: List[dict] = []

    def factory(no_cache: bool):
        return lambda base_dir: _make_reader(sd_league, seasons, base_dir,
                                             no_cache=no_cache)

    try:
        records = fetch_player_stats(factory(False), match_ids, base_dir=cache_dir,
                                     schedule=schedule, unreadable=unreadable)
    except Exception as exc:  # difensivo: la scomposizione assorbe i singoli errori
        result["errors"].append(f"download/conversione falliti: {exc}")
        result["seconds"] = round(time.monotonic() - started, 1)
        return result

    # Round di recupero sulle partite rimaste senza righe. soccerdata non
    # distingue "payload assente" da "ConnectionError inghiottito": si riprova
    # con cache disattivata e si CONTANO le partite ancora mancanti.
    for attempt in range(1, max(0, int(retries)) + 1):
        present = {parse_int(rec.get("id")) for rec in records}
        missing_ids = [match_id for match_id in match_ids if match_id not in present]
        if not missing_ids:
            break
        result["retry_rounds"] = attempt
        log.info("%s: %d partite senza righe giocatore, tentativo %d/%d",
                 league, len(missing_ids), attempt, retries)
        try:
            records.extend(fetch_player_stats(
                factory(True), missing_ids, base_dir=cache_dir, schedule=schedule,
                unreadable=unreadable))
        except Exception as exc:
            result["errors"].append(f"tentativo {attempt} di recupero fallito: {exc}")
            break
    result["seconds"] = round(time.monotonic() - started, 1)
    result["unreadable_matches"] = len(unreadable)
    if unreadable:
        result["unreadable_sample"] = unreadable[:20]

    # Data e stagione delle righe devono coincidere col calendario: sono due
    # versioni della stessa informazione (endpoint per-partita e payload di lega).
    mismatches = [rec for rec in records if rec.get("date_mismatch")]
    season_mismatches = [rec for rec in records if rec.get("season_mismatch")]
    if mismatches or season_mismatches:
        result["errors"].append(
            f"{len(mismatches)} righe con data derivata da 'game' diversa dal "
            f"calendario e {len(season_mismatches)} con stagione diversa (es. id "
            + ", ".join(str(rec.get("id")) for rec in (mismatches
                                                       + season_mismatches)[:5]) + ")")
        return result
    result["rows_without_date"] = sum(1 for rec in records if not rec.get("date"))

    present_ids = {parse_int(rec.get("id")) for rec in records}
    missing = [entry for entry in perimeter if entry["id"] not in present_ids]
    result["coverage"] = _frontier_status(
        missing, len(match_ids), reference_time, frontier_days,
        extra={"returned_matches": len(present_ids)})
    result["returned_matches"] = len(present_ids)
    result["missing_matches"] = len(missing)
    result["missing_matches_sample"] = [_entry_label(entry) for entry in missing[:20]]
    if (result["coverage"]["missing_blocking_ratio"] > missing_tolerance_ratio):
        result["errors"].append(
            f"{result['coverage']['missing_old'] + result['coverage']['missing_undated']} "
            f"partite su {len(match_ids)} NON di frontiera senza righe giocatore "
            f"({result['coverage']['missing_blocking_ratio']:.2%} > tolleranza "
            f"{missing_tolerance_ratio:.2%}): soccerdata non espone l'errore per "
            "singola partita, quindi la partita e' trattata come MANCANTE e la "
            "lega non viene pubblicata (usare --missing-tolerance-ratio per "
            "accettarlo in modo dichiarato)")

    # Righe doppie sulla chiave (stagione, id partita, squadra, giocatore): un
    # payload di lega che elenca due volte una partita fa percorrere due volte la
    # stessa partita a soccerdata. Tolte e CONTATE (mai silenziose).
    records, duplicates = dedupe_records(records, kind=PLAYER_KIND)
    result["duplicates"] = duplicates
    if duplicates["duplicate_ratio"] > max_duplicate_rows_ratio:
        result["errors"].append(
            f"{duplicates['duplicate_rows']} righe su {duplicates['input_rows']} "
            "sono doppie sulla chiave (stagione, id partita, squadra, giocatore) "
            f"(es. {duplicates['sample_matches'][:3]}): "
            f"{duplicates['duplicate_ratio']:.2%} > "
            f"{max_duplicate_rows_ratio:.2%}, la lega non viene pubblicata")

    expected = [parse_season(s) for s in seasons]
    min_rows = (min(len(match_ids), int(sample_matches)) * 5 if sample_matches
                else MIN_ROWS_PER_SEASON * max(1, len(seasons)))
    problems = validate_player(
        records, league=league, min_rows=min_rows,
        expected_seasons=None if sample_matches else [s for s in expected if s],
        min_rows_per_match=min_rows_per_match,
        max_thin_matches_ratio=max_thin_matches_ratio)
    result["rows"] = len(records)
    result["matches"] = len(present_ids)
    result["summary"] = player_summary(records)
    result["names"] = _names_for_report(records, PLAYER_KIND)
    if problems:
        result["errors"].extend(problems)
    if result["errors"]:
        # copertura incompleta o schema non valido: niente confronto, niente
        # scrittura, il file precedente resta valido
        return result

    baseline_path = path
    if baseline_dir:
        baseline_path = archive_path(PLAYER_KIND, league, baseline_dir)
    result["baseline_path"] = baseline_path
    previous = _load_baseline(baseline_path)
    result["baseline_found"] = bool(previous)
    if previous:
        result["previous_rows"] = len(previous)
        diff = compare_player_snapshots(
            previous, records, league=league,
            requested_seasons=[s for s in expected if s],
            allow_dropping_seasons=allow_dropping_seasons,
            frontier_days=frontier_days, now=reference_time)
        result["diff"] = diff.to_dict()
        if diff.blocking_problems:
            result["errors"].extend(diff.blocking_problems)
            result["errors"].append("file giocatore precedente lasciato invariato")
            return result
        shrink = _shrink_ratio(previous, records, expected)
        result["shrink_ratio"] = shrink
        if shrink is not None and shrink > MAX_SHRINK_RATIO:
            result["errors"].append(
                f"file nuovo con {len(records)} righe contro le "
                f"{len(previous)} precedenti sulle stesse stagioni "
                f"(-{shrink:.0%}): acquisizione parziale, file esistente "
                "lasciato invariato")
            return result

    if not dry_run:
        write_atomic(path, records, compact=True)
        result["written"] = True
    return result


# ---------------------------------------------------------------------------
# Acquisizione per lega
# ---------------------------------------------------------------------------
def _rolling_window_adjustments(league: str, seasons: Sequence[str],
                                player_seasons: Sequence[str], schedule: Sequence[dict],
                                datasets: Sequence[str], output_dir: str,
                                baseline_dir: Optional[str]) -> dict:
    """Tolleranze di rollover valide SOLO per la finestra mobile derivata dalla
    data (mai con ``--seasons`` esplicito), le stesse di update_all_xg_db:

      * ``season_not_started``: la stagione piu' recente della finestra non ha
        ancora partite nel calendario Understat (pre-stagione, luglio-agosto) e
        nessuna baseline la conteneva -> viene tolta dalle stagioni richieste
        in questa esecuzione;
      * ``seasons_aged_out``: le baseline contengono SOLO stagioni piu' vecchie
        della finestra fra quelle non richieste -> la loro scomparsa e'
        fisiologica e ``allow_dropping_seasons`` viene attivato per questa
        lega. Una stagione dentro la finestra che manca resta bloccante.
    """
    requested = sorted({parse_season(s) for s in list(seasons) + list(player_seasons)
                        if parse_season(s)})
    adj = {"seasons": list(seasons), "player_seasons": list(player_seasons),
           "allow_dropping_seasons": False, "season_not_started": None,
           "seasons_aged_out": []}
    if not requested:
        return adj
    current = max(requested)
    window_start = min(requested)

    baseline_seasons: set = set()
    for kind in datasets:
        base_dir = baseline_dir or output_dir
        previous = _load_baseline(archive_path(kind, league, base_dir))
        for rec in previous or []:
            if isinstance(rec, dict):
                season = parse_season(rec.get("season"))
                if season is not None:
                    baseline_seasons.add(season)

    scheduled = {parse_season(rec.get("season")) for rec in schedule
                 if isinstance(rec, dict)}
    if current not in scheduled and current not in baseline_seasons:
        adj["season_not_started"] = current
        code = f"{current % 100:02d}{(current + 1) % 100:02d}"
        adj["seasons"] = [s for s in seasons if s != code]
        adj["player_seasons"] = [s for s in player_seasons if s != code]
        log.info("%s: stagione %d/%d non ancora su Understat (pre-stagione): "
                 "acquisizione limitata alle stagioni %s", league, current,
                 current + 1, " ".join(adj["seasons"]))

    not_requested = sorted(s for s in baseline_seasons if s not in requested)
    aged_out = [s for s in not_requested if s < window_start]
    if not_requested and aged_out == not_requested:
        adj["allow_dropping_seasons"] = True
        adj["seasons_aged_out"] = aged_out
        log.info("%s: stagioni %s uscite dalla finestra mobile: la loro "
                 "scomparsa dagli archivi non blocca", league, aged_out)
    return adj


def acquire_league(league: str, seasons: Sequence[str], player_seasons: Sequence[str], *,
                   output_dir: str, baseline_dir: Optional[str], cache_dir: str,
                   datasets: Sequence[str], dry_run: bool,
                   allow_dropping_seasons: bool, retries: int,
                   frontier_days: float, missing_tolerance_ratio: float,
                   sample_matches: Optional[int],
                   min_played_field_coverage: float,
                   min_rows_per_match: int,
                   max_thin_matches_ratio: float,
                   max_duplicate_rows_ratio: float,
                   max_structural_na_ratio: float,
                   rolling_window: bool = False) -> dict:
    """Acquisisce i dataset richiesti per una lega (un solo snapshot per lega).

    ``rolling_window``: le stagioni sono la finestra mobile derivata dalla data
    (non una scelta esplicita) e valgono le tolleranze di rollover di
    ``_rolling_window_adjustments``."""
    sd_league = SOCCERDATA_LEAGUES[league]
    outcome: dict = {"league": league, "sd_league": sd_league,
                     "datasets": {}, "errors": []}
    started = time.monotonic()
    league_cache = _cache_subdir(cache_dir, league)
    # Il calendario e' la base di tutto (perimetro, id delle partite, date): se
    # la lettura fallisce la lega si perde per intero. La verifica reale ha
    # mostrato che un singolo rifiuto di connessione di Understat
    # ("connect: connection refused") puo' far cadere una lega dopo decine di
    # minuti di download: si riprova con attese crescenti e si CONTANO i
    # tentativi (finiscono nel report).
    schedule = None
    schedule_attempts = 0
    last_error: Optional[Exception] = None
    total_attempts = max(1, int(retries)) + 1
    for schedule_attempts in range(1, total_attempts + 1):
        try:
            schedule_reader = _make_reader(
                sd_league, sorted(set(seasons) | set(player_seasons)),
                league_cache, no_cache=True)
            schedule = perimeter_from_schedule(schedule_reader.read_schedule())
            schedule, schedule_duplicates = _dedupe_schedule(schedule)
            break
        except Exception as exc:
            last_error = exc
            if schedule_attempts < total_attempts:
                wait = min(60, 10 * schedule_attempts)
                log.warning("%s: calendario non acquisito (tentativo %d/%d): %s "
                            "- nuovo tentativo fra %d s",
                            league, schedule_attempts, total_attempts, exc, wait)
                time.sleep(wait)
    if schedule is None:
        outcome["errors"].append(
            f"calendario non acquisito dopo {schedule_attempts} tentativi: "
            f"{last_error}")
        outcome["schedule_attempts"] = schedule_attempts
        outcome["seconds"] = round(time.monotonic() - started, 1)
        return outcome
    outcome["schedule_attempts"] = schedule_attempts

    played = played_perimeter(schedule)
    season_counts: Dict[str, dict] = {}
    for rec in schedule:
        season = rec.get("season")
        if season is None:
            continue
        bucket = season_counts.setdefault(str(season), {
            "scheduled": 0, "played_with_xg": 0, "has_data": 0})
        bucket["scheduled"] += 1
        if rec.get("has_data"):
            bucket["has_data"] += 1
    for rec in played:
        bucket = season_counts.setdefault(str(rec.get("season")), {
            "scheduled": 0, "played_with_xg": 0, "has_data": 0})
        bucket["played_with_xg"] += 1
    outcome["schedule"] = {
        "scheduled_matches": len(schedule),
        "has_data": sum(1 for rec in schedule if rec.get("has_data")),
        "played_with_xg": len(played),
        "first_date": next((rec["date"] for rec in sorted(
            schedule, key=lambda r: r.get("date") or "")), None),
        "last_played_date": (sorted(
            (rec["date"] for rec in played if rec.get("date")) or [None])[-1]),
        "seasons": dict(sorted(season_counts.items())),
        "duplicate_rows": schedule_duplicates["duplicate_rows"],
        "attempts": schedule_attempts,
    }
    outcome["schedule_duplicates"] = schedule_duplicates

    if rolling_window:
        adj = _rolling_window_adjustments(
            league, seasons, player_seasons, schedule, datasets,
            output_dir, baseline_dir)
        seasons = adj["seasons"]
        player_seasons = adj["player_seasons"]
        allow_dropping_seasons = allow_dropping_seasons or adj["allow_dropping_seasons"]
        outcome["rolling_window"] = {
            "seasons": list(seasons),
            "player_seasons": list(player_seasons),
            "season_not_started": adj["season_not_started"],
            "seasons_aged_out": adj["seasons_aged_out"],
        }

    if PPDA_KIND in datasets:
        outcome["datasets"][PPDA_KIND] = acquire_ppda_deep(
            league, sd_league, seasons, output_dir=output_dir,
            baseline_dir=baseline_dir, cache_dir=league_cache, dry_run=dry_run,
            schedule=schedule, allow_dropping_seasons=allow_dropping_seasons,
            min_played_field_coverage=min_played_field_coverage, retries=retries,
            frontier_days=frontier_days,
            missing_tolerance_ratio=missing_tolerance_ratio,
            max_duplicate_rows_ratio=max_duplicate_rows_ratio,
            max_structural_na_ratio=max_structural_na_ratio)
    if PLAYER_KIND in datasets:
        outcome["datasets"][PLAYER_KIND] = acquire_player_match(
            league, sd_league, player_seasons, output_dir=output_dir,
            baseline_dir=baseline_dir, cache_dir=league_cache, dry_run=dry_run,
            schedule=schedule, allow_dropping_seasons=allow_dropping_seasons,
            retries=retries, frontier_days=frontier_days,
            missing_tolerance_ratio=missing_tolerance_ratio,
            sample_matches=sample_matches, min_rows_per_match=min_rows_per_match,
            max_thin_matches_ratio=max_thin_matches_ratio,
            max_duplicate_rows_ratio=max_duplicate_rows_ratio)

    for dataset, entry in outcome["datasets"].items():
        outcome["errors"].extend(f"{dataset}: {err}" for err in entry.get("errors", []))
    outcome["seconds"] = round(time.monotonic() - started, 1)
    return outcome


# ---------------------------------------------------------------------------
# Riga di comando
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Acquisizione Understat di PPDA/deep completions (squadra "
                    "per partita) e statistiche giocatore per partita")
    parser.add_argument("--league", action="append", dest="leagues",
                        choices=list(PPDA_FILES), help="limita a una lega (ripetibile)")
    parser.add_argument("--seasons", nargs="+", default=None,
                        help="stagioni soccerdata esplicite per PPDA/deep "
                             "(controlli rigorosi). Default: finestra mobile "
                             f"derivata dalla data, oggi {' '.join(SEASONS)}")
    parser.add_argument("--player-seasons", nargs="+", default=None,
                        help="stagioni per le statistiche giocatore "
                             "(default: le stesse di --seasons)")
    parser.add_argument("--datasets", nargs="+", default=[PPDA_KIND, PLAYER_KIND],
                        choices=[PPDA_KIND, PLAYER_KIND],
                        help="quali archivi acquisire (default: entrambi)")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--baseline-dir", default=None,
                        help="cartella dell'ultimo archivio valido con cui "
                             "confrontare lo snapshot (default: --output-dir). "
                             "Serve alla modalita' verifica, che scrive altrove "
                             "ma deve confrontarsi con i dati committati")
    parser.add_argument("--cache-dir", default=None,
                        help="cartella di cache di soccerdata, isolata per run "
                             "(default: cartella temporanea del processo)")
    parser.add_argument("--parallel-leagues", type=int, default=1,
                        help="quante leghe acquisire in parallelo (default: 1). "
                             "soccerdata non applica nessun rate limit a "
                             "Understat: le richieste al secondo crescono con "
                             "questo valore")
    parser.add_argument("--retries", type=int, default=2,
                        help="tentativi aggiuntivi per completare i dati mancanti "
                             "(default: 2)")
    parser.add_argument("--sample-matches-per-league", type=int, default=None,
                        help="acquisisce solo le N partite piu' recenti per lega "
                             "(campione DICHIARATO nel report; default: perimetro "
                             "intero, nessun campione)")
    parser.add_argument("--missing-tolerance-ratio", type=float, default=0.0,
                        help="frazione di partite del perimetro NON di frontiera "
                             "che puo' restare senza dati (default: 0.0, nessuna)")
    parser.add_argument("--min-played-field-coverage", type=float,
                        default=DEFAULT_MIN_PLAYED_FIELD_COVERAGE,
                        help="copertura minima dei quattro valori PPDA/deep sulle "
                             "partite concluse del file "
                             f"(default: {DEFAULT_MIN_PLAYED_FIELD_COVERAGE})")
    parser.add_argument("--min-rows-per-match", type=int,
                        default=DEFAULT_MIN_ROWS_PER_MATCH,
                        help="sotto questa soglia il roster di una partita e' "
                             f"'sottile' (default: {DEFAULT_MIN_ROWS_PER_MATCH})")
    parser.add_argument("--max-thin-matches-ratio", type=float,
                        default=DEFAULT_MAX_THIN_MATCHES_RATIO,
                        help="frazione massima di partite con roster sottile "
                             f"(default: {DEFAULT_MAX_THIN_MATCHES_RATIO})")
    parser.add_argument("--max-duplicate-rows-ratio", type=float,
                        default=MAX_DUPLICATE_ROWS_RATIO,
                        help="frazione massima di righe doppie sulla chiave "
                             "primaria tolte dal dedup prima di far fallire la "
                             f"lega (default: {MAX_DUPLICATE_ROWS_RATIO})")
    parser.add_argument("--max-structural-na-ratio", type=float,
                        default=MAX_STRUCTURAL_NA_RATIO,
                        help="frazione massima di partite con PPDA non "
                             "calcolabile (denominatore difensivo nullo, deep "
                             "presente): oltre la soglia non e' un caso "
                             f"puntuale (default: {MAX_STRUCTURAL_NA_RATIO})")
    parser.add_argument("--frontier-days", type=float, default=DEFAULT_FRONTIER_DAYS,
                        help="finestra (giorni) in cui una partita puo' restare "
                             "senza dati senza bloccare (default: "
                             f"{DEFAULT_FRONTIER_DAYS})")
    parser.add_argument("--allow-dropping-seasons", action="store_true",
                        help="autorizza esplicitamente la scomparsa delle "
                             "stagioni non piu' richieste")
    parser.add_argument("--dry-run", action="store_true",
                        help="scarica e valida senza scrivere")
    parser.add_argument("--report", default=None, help="riepilogo JSON")
    parser.add_argument("--require-soccerdata-version", action="store_true",
                        help="rifiuta una versione di soccerdata diversa da quella "
                             "verificata (default: avviso nei log)")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    leagues = args.leagues or list(PPDA_FILES)
    # Finestra mobile (default, tolleranze di rollover attive) oppure elenco
    # esplicito (nessuna tolleranza automatica).
    rolling_window = not args.seasons
    seasons = derive_seasons() if rolling_window else list(args.seasons)
    player_seasons = list(args.player_seasons or seasons)
    if rolling_window:
        log.info("Stagioni derivate dalla data (finestra mobile di %d): %s",
                 len(seasons), " ".join(seasons))
    datasets = list(dict.fromkeys(args.datasets))
    cache_dir = args.cache_dir or tempfile.mkdtemp(prefix="soccermath-understat-")
    os.makedirs(cache_dir, exist_ok=True)

    try:
        soccerdata_version = check_soccerdata_version(
            strict=args.require_soccerdata_version)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 2

    log.info("Perimetro: leghe %s; stagioni %s; stagioni giocatore %s; dataset %s",
             ", ".join(leagues), " ".join(seasons), " ".join(player_seasons),
             " ".join(datasets))
    log.info("Cache soccerdata isolata: %s", cache_dir)

    def run(league: str) -> dict:
        log.info("[%s] acquisizione in corso...", league)
        return acquire_league(
            league, seasons, player_seasons, output_dir=args.output_dir,
            baseline_dir=args.baseline_dir, cache_dir=cache_dir,
            datasets=datasets, dry_run=args.dry_run,
            allow_dropping_seasons=args.allow_dropping_seasons,
            retries=args.retries, frontier_days=args.frontier_days,
            missing_tolerance_ratio=args.missing_tolerance_ratio,
            sample_matches=args.sample_matches_per_league,
            min_played_field_coverage=args.min_played_field_coverage,
            min_rows_per_match=args.min_rows_per_match,
            max_thin_matches_ratio=args.max_thin_matches_ratio,
            max_duplicate_rows_ratio=args.max_duplicate_rows_ratio,
            max_structural_na_ratio=args.max_structural_na_ratio,
            rolling_window=rolling_window)

    results: List[dict] = []
    if args.parallel_leagues > 1 and len(leagues) > 1:
        with ThreadPoolExecutor(max_workers=int(args.parallel_leagues)) as pool:
            futures = {pool.submit(run, league): league for league in leagues}
            for future in as_completed(futures):
                league = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:  # pragma: no cover - difensivo
                    results.append({"league": league, "datasets": {}, "errors": [
                        f"acquisizione interrotta: {exc}"]})
    else:
        for league in leagues:
            results.append(run(league))
    results.sort(key=lambda item: leagues.index(item["league"]))

    failures = 0
    for outcome in results:
        if outcome["errors"] and not outcome["datasets"]:
            failures += 1
            for err in outcome["errors"]:
                log.error("%s: %s", outcome["league"], err)
        for dataset, entry in outcome["datasets"].items():
            label = f"{outcome['league']}/{dataset}"
            if entry.get("errors"):
                failures += 1
                for err in entry["errors"]:
                    log.error("%s: %s", label, err)
                continue
            detail = (f"{entry['rows']} righe, {entry['matches']} partite"
                      if dataset == PLAYER_KIND else f"{entry['matches']} partite")
            log.info("%s: %s%s", label, detail,
                     "" if entry.get("written") else " [dry-run, non scritto]")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "soccerdata_version": soccerdata_version,
        "required_soccerdata_version": REQUIRED_SOCCERDATA_VERSION,
        "seasons": seasons,
        "player_seasons": player_seasons,
        "datasets": datasets,
        "leagues_requested": leagues,
        "output_dir": os.path.abspath(args.output_dir),
        "baseline_dir": (os.path.abspath(args.baseline_dir)
                         if args.baseline_dir else os.path.abspath(args.output_dir)),
        "cache_dir": cache_dir,
        "dry_run": bool(args.dry_run),
        "parallel_leagues": int(args.parallel_leagues),
        "retries": int(args.retries),
        "frontier_days": float(args.frontier_days),
        "missing_tolerance_ratio": float(args.missing_tolerance_ratio),
        "sample_matches_per_league": args.sample_matches_per_league,
        "max_duplicate_rows_ratio": float(args.max_duplicate_rows_ratio),
        "max_structural_na_ratio": float(args.max_structural_na_ratio),
        "min_played_field_coverage": float(args.min_played_field_coverage),
        "min_rows_per_match": int(args.min_rows_per_match),
        "max_thin_matches_ratio": float(args.max_thin_matches_ratio),
        "leagues": results,
        "failures": failures,
    }
    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)) or ".", exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write("\n")

    log.info("Completato: %d leghe, %d fallimenti", len(leagues), failures)
    if failures:
        log.error("Acquisizione fallita per %d dataset: i file validi precedenti "
                  "NON sono stati sovrascritti.", failures)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
