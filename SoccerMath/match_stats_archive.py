"""
match_stats_archive.py - Schema, validazione e confronto dei due archivi NUOVI
acquisiti da Understat con la stessa fonte dell'archivio xG:

  1. ``database/ppda_deep_<lega>.json``  -> PPDA e deep completions squadra per
     partita (``soccerdata.Understat.read_team_match_stats()``):

        {"season": 2022, "id": 16960, "date": "2022-08-13 18:45:00",
         "home_team": "Inter", "away_team": "Torino", "is_result": true,
         "home_ppda": 8.13, "away_ppda": 11.2,
         "home_deep_completions": 12, "away_deep_completions": 5}

  2. ``database/player_match_<lega>.json`` -> statistiche giocatore PER PARTITA
     (``soccerdata.Understat.read_player_match_stats()``), una riga per
     giocatore per partita:

        {"season": 2022, "id": 16960, "date": "2022-08-13", "team": "Inter",
         "opponent": "Torino", "venue": "home", "player_id": 2371,
         "player": "...", "position": "FW", "minutes": 90, "goals": 1, ...}

Perche' un modulo separato e non un'estensione di ``xg_archive.py``:
l'archivio xG e' la fonte della testa Totali in produzione e ha un formato
congelato; qui si aggiungono file NUOVI, con schema e regole di validita'
proprie, senza toccare ne' l'archivio xG ne' i suoi consumatori. Nessuno di
questi file e' letto da ``app.py``, ``config.py`` o ``models/``: sono dati di
audit finche' un secondo intervento non decide il contrario.

Nomi delle squadre: i file conservano i nomi GREZZI della fonte, come fa
l'archivio xG. La normalizzazione NON viene duplicata qui: si usa il resolver
condiviso della PR #15 (``team_names.resolve_team_name`` -> ``team_aliases``,
unione di ``TEAM_NAME_MAP`` e ``UNDERSTAT_NAME_MAP``). Nessuna quarta tabella.

Regole di validita' (nessun dato inventato, nessun fallback silenzioso):
  * ``None`` significa "la fonte non ha dato questo valore" e resta ``None``:
    non diventa mai 0. Lo 0.0/0 sono valori VALIDI (una partita con 0 deep
    completions esiste);
  * i record sono per partita (PPDA/deep) e per giocatore per partita
    (statistiche giocatore); chiavi duplicate => file rifiutato;
  * una partita CONCLUSA senza PPDA o senza deep completions e' una copertura
    incompleta: viene contata e, sopra la soglia dichiarata, BLOCCA il file
    (l'acquisizione non sovrascrive l'ultimo valido ed esce diverso da zero);
  * confronto partita-per-partita con l'ultimo file valido: perdere una partita
    che aveva PPDA/deep/righe giocatore NON e' ammesso (eccezione dichiarata:
    la frontiera, cioe' le partite piu' recenti di ``frontier_days``);
  * scrittura atomica (file temporaneo + ``os.replace``).

Limiti dichiarati (non risolvibili con questi dati, verificati nel report
``audit/results/ppda_deep_player_feasibility.md``):
  * ``read_player_match_stats()`` non espone un canale d'errore per singola
    partita: una partita senza righe puo' essere un payload assente, un
    ``ConnectionError`` inghiottito da soccerdata o un roster vuoto. Qui i tre
    casi sono trattati allo stesso modo: MANCANTE, contato e bloccante oltre la
    tolleranza dichiarata, mai confuso con "zero giocatori";
  * non esiste uno snapshot datato lato Understat: la disponibilita' storica
    reale dei dati non e' ricostruibile a posteriori, si misura solo la
    frontiera (vedi il report di fattibilita').
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from config import LEAGUES_CONFIG
from team_names import resolve_team_name
from xg_archive import (  # noqa: F401  (LEAGUES ri-esportata per i consumatori)
    ARCHIVE_FILES,
    LEAGUES,
    as_utc,
    load_archive,
    match_key,
    parse_kickoff,
    parse_season,
)

# ---------------------------------------------------------------------------
# File e schema
# ---------------------------------------------------------------------------
# I nomi usano lo slug Understat gia' usato da config.LEAGUES_CONFIG
# (``understat_slug``) e la stessa forma di ``xg_<slug>.json``: nessuna tabella
# nuova, solo una derivazione dal config esistente.
PPDA_KIND = "ppda_deep"
PLAYER_KIND = "player_match"

PPDA_FIELDS: Tuple[str, ...] = (
    "season", "id", "date", "home_team", "away_team", "is_result",
    "home_ppda", "away_ppda",
    "home_deep_completions", "away_deep_completions",
)

PLAYER_FIELDS: Tuple[str, ...] = (
    "season", "id", "date", "team", "opponent", "venue",
    "player_id", "player", "position", "minutes",
    "goals", "own_goals", "shots", "xg", "xg_chain", "xg_buildup",
    "assists", "xa", "key_passes", "yellow_cards", "red_cards",
)

# Soglie di default (sovrascrivibili dalla riga di comando).
DEFAULT_MIN_PLAYED_FIELD_COVERAGE = 0.95   # PPDA/deep completi sulle concluse
DEFAULT_MAX_THIN_MATCHES_RATIO = 0.02      # partite con roster "sottile"
DEFAULT_MIN_ROWS_PER_MATCH = 5             # sotto questa soglia il roster e' thin
DEFAULT_FRONTIER_DAYS = 1.0                # finestra in cui la perdita e' ammessa

VENUES: Tuple[str, ...] = ("home", "away")

# Quanti elementi di ogni lista finiscono nel report (le liste sono diagnostica,
# non devono far esplodere la dimensione del JSON).
SAMPLE_LIMIT = 20


def _slug(league: str) -> str:
    slug = (LEAGUES_CONFIG.get(league) or {}).get("understat_slug")
    if not slug:
        raise KeyError(f"lega senza 'understat_slug' in config.LEAGUES_CONFIG: {league!r}")
    return str(slug)


def ppda_filename(league: str) -> str:
    return f"{PPDA_KIND}_{_slug(league)}.json"


def player_filename(league: str) -> str:
    return f"{PLAYER_KIND}_{_slug(league)}.json"


def archive_files(kind: str) -> Dict[str, str]:
    """{lega: nome file} per ``kind`` in ``PPDA_KIND``/``PLAYER_KIND``."""
    if kind == PPDA_KIND:
        return {league: ppda_filename(league) for league in LEAGUES}
    if kind == PLAYER_KIND:
        return {league: player_filename(league) for league in LEAGUES}
    raise ValueError(f"tipo di archivio non riconosciuto: {kind!r}")


PPDA_FILES: Dict[str, str] = archive_files(PPDA_KIND)
PLAYER_FILES: Dict[str, str] = archive_files(PLAYER_KIND)


def archive_path(kind: str, league: str, base_dir=None) -> str:
    from config import DATABASE_DIR

    base = str(base_dir) if base_dir is not None else str(DATABASE_DIR)
    return os.path.join(base, archive_files(kind)[league])


def _assert_not_xg_archive(path: str) -> None:
    """Rete di sicurezza: mai scrivere dentro l'archivio xG o le medie."""
    name = os.path.basename(path)
    reserved = set(ARCHIVE_FILES.values()) | {
        os.path.basename(str(cfg["xg_json"])) for cfg in LEAGUES_CONFIG.values()}
    if name in reserved:
        raise ValueError(
            f"percorso riservato all'archivio xG: {name} (i nuovi file devono "
            "avere nomi propri: ppda_deep_<lega>.json / player_match_<lega>.json)")


# ---------------------------------------------------------------------------
# Conversione dei tipi (senza inventare valori)
# ---------------------------------------------------------------------------
def json_safe(value):
    """Converte tipi pandas/numpy in tipi JSON nativi (NA/NaT/NaN -> None)."""
    if value is None:
        return None
    try:
        if not isinstance(value, (str, bytes, list, dict)):
            import pandas as pd  # import locale: il modulo vive anche senza pandas

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


def parse_int(value, *, minimum: Optional[int] = None,
              maximum: Optional[int] = None) -> Optional[int]:
    """Intero valido (o None). Nessuna coercizione creativa: "abc" -> None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if isinstance(value, float) and not float(value).is_integer():
        return None
    if minimum is not None and number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return number


def parse_ppda(value) -> Optional[float]:
    """PPDA valida: numerica, finita, non negativa. 0.0 e' un valore valido."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or number > 1000:
        return None
    return number


def parse_minutes(value) -> Optional[int]:
    """Minuti giocati: intero in [0, 150] oppure None (mai 0 al posto di None)."""
    return parse_int(value, minimum=0, maximum=150)


def parse_non_negative(value) -> Optional[int]:
    return parse_int(value, minimum=0)


def parse_rate(value) -> Optional[float]:
    """Grandezza di conteggio/rate non negativa e finita (xg, xa, xg_chain...)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "t"}
    return False


def clean_text(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_ppda_record(raw: dict) -> dict:
    """Record grezzo -> tipi canonici (chiavi di ``PPDA_FIELDS``)."""
    return {
        "season": parse_season(raw.get("season")),
        "id": parse_int(raw.get("id")),
        "date": clean_text(raw.get("date")),
        "home_team": clean_text(raw.get("home_team")),
        "away_team": clean_text(raw.get("away_team")),
        "is_result": parse_bool(raw.get("is_result")),
        "home_ppda": parse_ppda(raw.get("home_ppda")),
        "away_ppda": parse_ppda(raw.get("away_ppda")),
        "home_deep_completions": parse_non_negative(raw.get("home_deep_completions")),
        "away_deep_completions": parse_non_negative(raw.get("away_deep_completions")),
    }


def normalize_player_record(raw: dict) -> dict:
    """Record grezzo -> tipi canonici (chiavi di ``PLAYER_FIELDS``)."""
    venue = clean_text(raw.get("venue"))
    venue = venue.lower() if venue else None
    return {
        "season": parse_season(raw.get("season")),
        "id": parse_int(raw.get("id")),
        "date": clean_text(raw.get("date")),
        "team": clean_text(raw.get("team")),
        "opponent": clean_text(raw.get("opponent")),
        "venue": venue if venue in VENUES else None,
        "player_id": parse_int(raw.get("player_id")),
        "player": clean_text(raw.get("player")),
        "position": clean_text(raw.get("position")),
        "minutes": parse_minutes(raw.get("minutes")),
        "goals": parse_non_negative(raw.get("goals")),
        "own_goals": parse_non_negative(raw.get("own_goals")),
        "shots": parse_non_negative(raw.get("shots")),
        "xg": parse_rate(raw.get("xg")),
        "xg_chain": parse_rate(raw.get("xg_chain")),
        "xg_buildup": parse_rate(raw.get("xg_buildup")),
        "assists": parse_non_negative(raw.get("assists")),
        "xa": parse_rate(raw.get("xa")),
        "key_passes": parse_non_negative(raw.get("key_passes")),
        "yellow_cards": parse_non_negative(raw.get("yellow_cards")),
        "red_cards": parse_non_negative(raw.get("red_cards")),
    }


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------
def load_ppda(league: str, base_dir=None) -> List[dict]:
    return load_records(archive_path(PPDA_KIND, league, base_dir), PPDA_KIND)


def load_player(league: str, base_dir=None) -> List[dict]:
    return load_records(archive_path(PLAYER_KIND, league, base_dir), PLAYER_KIND)


def load_records(path: str, kind: str) -> List[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path}: atteso un elenco di record, trovato {type(data).__name__}")
    return data


def write_atomic(path: str, records: Sequence[dict], *, compact: bool = False) -> None:
    """Scrittura atomica (tmp + ``os.replace``).

    ``compact`` scrive JSON su una riga: i file giocatore sono ~200.000 righe e
    l'indentazione li gonfierebbe di oltre il doppio, senza alcun consumatore
    umano (si leggono con ``json.load``). Restano comunque JSON validi.
    """
    _assert_not_xg_archive(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if compact:
            json.dump(records, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(records, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Validazione di schema
# ---------------------------------------------------------------------------
def _played(record: dict) -> bool:
    return parse_bool(record.get("is_result"))


def _completeness_key(record: dict) -> str:
    """Esito di ``record_completeness`` come chiave di conteggio."""
    return {"completo": "complete", "parziale": "partial",
            "vuoto": "empty"}[record_completeness(record)]


def _side_data(record: dict, side: str) -> Tuple[bool, bool]:
    """(ha PPDA, ha deep completions) per un lato. False = valore assente."""
    return (record.get(f"{side}_ppda") is not None,
            record.get(f"{side}_deep_completions") is not None)


def record_completeness(record: dict) -> str:
    """"completo" | "parziale" | "vuoto" sui quattro valori (2 lati x 2 campi)."""
    present = sum(
        1 for side in VENUES for value in _side_data(record, side) if value)
    if present == 4:
        return "completo"
    if present == 0:
        return "vuoto"
    return "parziale"


def ppda_gap_kind(record: dict) -> Optional[str]:
    """Perche' un record PPDA/deep non e' completo: ``None`` se lo e'.

    Distingue due cause che NON sono la stessa cosa e vanno contate a parte:

    * ``"strutturale"`` - deep completions e' presente su **entrambi** i lati e
      l'unico valore assente e' PPDA: e' il caso in cui soccerdata 1.9.1
      restituisce ``pd.NA`` perche' il denominatore difensivo del PPDA e' 0. Il
      campo esiste, il rapporto non e' definito (non e' un dato perso);
    * ``"assente"`` - manca almeno un valore di deep completions (o piu' valori,
      o l'intero record): la fonte non ha pubblicato quei campi.
    """
    if record_completeness(record) == "completo":
        return None
    sides = {side: _side_data(record, side) for side in VENUES}
    if all(has_deep for _, has_deep in sides.values()):
        return "strutturale"
    return "assente"


def _record_key(record: dict, kind: str) -> Optional[Tuple]:
    """Chiave primaria di un record d'archivio (None se inutilizzabile)."""
    season = parse_season(record.get("season"))
    match_id = parse_int(record.get("id"))
    if season is None or match_id is None:
        return None
    if kind == PLAYER_KIND:
        player_id = parse_int(record.get("player_id"))
        team = clean_text(record.get("team"))
        if player_id is None or not team:
            return None
        return (season, match_id, team, player_id)
    return (season, match_id)


def _record_richness(record: dict, kind: str) -> Tuple:
    """Quanto un record e' "ricco": a parita' di chiave si tiene il migliore."""
    if kind == PLAYER_KIND:
        minutes = parse_minutes(record.get("minutes"))
        filled = sum(1 for key in ("xg", "xa", "xg_chain", "xg_buildup",
                                   "goals", "shots", "assists")
                     if record.get(key) is not None)
        return (minutes if minutes is not None else -1, filled)
    return (sum(1 for side in VENUES for value in _side_data(record, side) if value),)


def dedupe_records(records: Sequence[dict], *,
                   kind: str = PPDA_KIND) -> Tuple[List[dict], dict]:
    """Toglie le righe doppie sulla chiave primaria, tenendo la piu' ricca.

    La chiave di una riga e' (stagione, id partita) per PPDA/deep e
    (stagione, id partita, squadra, giocatore) per le statistiche giocatore: due
    righe con la stessa chiave sono lo **stesso** dato acquisito due volte (per
    esempio una partita elencata due volte nel payload di lega, che soccerdata
    percorre due volte), non due osservazioni diverse. Il dedup e' quindi
    dichiarato e contato, mai silenzioso: il chiamante decide se il numero di
    righe tolte e' accettabile.
    """
    kept: Dict[Tuple, dict] = {}
    order: List[Tuple] = []
    unusable = 0
    duplicates = 0
    per_match: Dict[Tuple, int] = {}
    alternative = 0
    for rec in records or []:
        if not isinstance(rec, dict):
            unusable += 1
            continue
        key = _record_key(rec, kind)
        if key is None:
            unusable += 1
            continue
        previous = kept.get(key)
        if previous is None:
            kept[key] = rec
            order.append(key)
            continue
        duplicates += 1
        per_match[key[:2]] = per_match.get(key[:2], 0) + 1
        if _record_richness(rec, kind) != _record_richness(previous, kind):
            alternative += 1
        if _record_richness(rec, kind) > _record_richness(previous, kind):
            kept[key] = rec
    stats = {
        "kind": kind,
        "input_rows": len(records or []),
        "rows": len(kept),
        "duplicate_rows": duplicates,
        "duplicate_keys": len(per_match),
        "duplicate_matches": len({key[1] for key in per_match}),
        "duplicate_differing_rows": alternative,
        "unusable_rows": unusable,
        "duplicate_ratio": (duplicates / len(records or [])
                            if records else 0.0),
        "sample_matches": [{"season": season, "id": match_id, "rows": count}
                           for (season, match_id), count
                           in sorted(per_match.items())[:10]],
    }
    return [kept[key] for key in order], stats


def validate_ppda(
    records: Sequence[dict],
    *,
    league: str = "",
    min_matches: int = 100,
    expected_seasons: Optional[Sequence[int]] = None,
    min_played_field_coverage: float = DEFAULT_MIN_PLAYED_FIELD_COVERAGE,
) -> List[str]:
    """Controlli di integrita' sull'archivio PPDA/deep. Lista dei problemi."""
    problems: List[str] = []
    prefix = f"{league}: " if league else ""
    if not isinstance(records, list):
        return [f"{prefix}formato non valido (atteso elenco)"]
    if len(records) < min_matches:
        problems.append(f"{prefix}solo {len(records)} partite (minimo {min_matches})")

    seasons: Dict[int, int] = {}
    keys: Dict[Tuple, int] = {}
    missing_fields = 0
    bad_dates = 0
    bad_ids = 0
    bad_names = 0
    bad_values = 0
    played = 0
    played_without_ppda = 0
    played_without_deep = 0
    played_complete = 0
    played_partial = 0
    played_empty = 0
    unplayed_records = 0

    for rec in records:
        if not isinstance(rec, dict) or any(f not in rec for f in PPDA_FIELDS):
            missing_fields += 1
            continue
        season = parse_season(rec.get("season"))
        if season is None:
            problems.append(f"{prefix}stagione illeggibile: {rec.get('season')!r}")
            continue
        seasons[season] = seasons.get(season, 0) + 1

        match_id = parse_int(rec.get("id"))
        if match_id is None:
            bad_ids += 1
        else:
            key = (season, match_id)
            keys[key] = keys.get(key, 0) + 1

        if parse_kickoff(rec.get("date"))[0] is None:
            bad_dates += 1
        home = clean_text(rec.get("home_team"))
        away = clean_text(rec.get("away_team"))
        if not home or not away or home == away:
            bad_names += 1

        # I valori grezzi devono ESSERE gia' canonici: se una stringa diventa
        # None nella normalizzazione, la fonte ha dato qualcosa di non valido.
        for side in VENUES:
            raw_ppda = rec.get(f"{side}_ppda")
            raw_deep = rec.get(f"{side}_deep_completions")
            if (raw_ppda is not None and parse_ppda(raw_ppda) is None) or (
                    raw_deep is not None and parse_non_negative(raw_deep) is None):
                bad_values += 1

        if _played(rec):
            played += 1
            has_ppda = any(_side_data(rec, side)[0] for side in VENUES)
            has_deep = any(_side_data(rec, side)[1] for side in VENUES)
            if not has_ppda:
                played_without_ppda += 1
            if not has_deep:
                played_without_deep += 1
            completeness = record_completeness(rec)
            if completeness == "completo":
                played_complete += 1
            elif completeness == "parziale":
                played_partial += 1
            else:
                played_empty += 1
        else:
            unplayed_records += 1

    if missing_fields:
        problems.append(f"{prefix}{missing_fields} record senza i campi richiesti")
    if bad_ids:
        problems.append(f"{prefix}{bad_ids} record senza id partita valido")
    if bad_dates:
        problems.append(f"{prefix}{bad_dates} record con data illeggibile")
    if bad_names:
        problems.append(f"{prefix}{bad_names} record con squadre mancanti/coincidenti")
    if bad_values:
        problems.append(f"{prefix}{bad_values} valori PPDA/deep non validi "
                        "(negativi, non finiti o non numerici)")
    duplicated = sorted(k for k, v in keys.items() if v > 1)
    if duplicated:
        problems.append(f"{prefix}{len(duplicated)} partite duplicate "
                        f"(stagione, id) (es. {duplicated[:5]})")

    if expected_seasons:
        missing = [s for s in expected_seasons if seasons.get(s, 0) == 0]
        if missing:
            problems.append(f"{prefix}stagioni assenti: {missing}")

    # Copertura dei campi richiesti sulle partite concluse: e' il controllo che
    # rende rumorosa (non silenziosa) l'assenza di PPDA/deep nella fonte.
    if played:
        coverage = played_complete / played
        if coverage < min_played_field_coverage:
            problems.append(
                f"{prefix}copertura PPDA/deep completa solo su {played_complete}/"
                f"{played} partite concluse ({coverage:.1%} < "
                f"{min_played_field_coverage:.0%}): la fonte non espone i campi "
                "su tutte le partite concluse")
    return problems


def ppda_summary(records: Sequence[dict]) -> dict:
    """Statistiche descrittive del file PPDA/deep (per report e audit)."""
    by_season: Dict[int, dict] = {}
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        season = parse_season(rec.get("season"))
        if season is None:
            continue
        bucket = by_season.setdefault(season, {
            "matches": 0, "played": 0, "complete": 0, "partial": 0, "empty": 0,
            "with_home_ppda": 0, "with_away_ppda": 0,
            "with_home_deep": 0, "with_away_deep": 0,
            "unplayed": 0, "min_date": None, "max_date": None,
            "max_played_date": None,
        })
        bucket["matches"] += 1
        if _played(rec):
            bucket["played"] += 1
            bucket[_completeness_key(rec)] += 1
        else:
            bucket["unplayed"] += 1
        for side in VENUES:
            has_ppda, has_deep = _side_data(rec, side)
            bucket[f"with_{side}_ppda"] += 1 if has_ppda else 0
            bucket[f"with_{side}_deep"] += 1 if has_deep else 0
        kickoff, _ = parse_kickoff(rec.get("date"))
        if kickoff is not None:
            day = kickoff.date().isoformat()
            bucket["min_date"] = day if bucket["min_date"] is None else min(bucket["min_date"], day)
            bucket["max_date"] = day if bucket["max_date"] is None else max(bucket["max_date"], day)
            if _played(rec):
                bucket["max_played_date"] = (
                    day if bucket["max_played_date"] is None
                    else max(bucket["max_played_date"], day))
    return {"matches": len(records or []),
            "seasons": {str(k): v for k, v in sorted(by_season.items())}}


def validate_player(
    records: Sequence[dict],
    *,
    league: str = "",
    min_rows: int = 100,
    expected_seasons: Optional[Sequence[int]] = None,
    min_rows_per_match: int = DEFAULT_MIN_ROWS_PER_MATCH,
    max_thin_matches_ratio: float = DEFAULT_MAX_THIN_MATCHES_RATIO,
) -> List[str]:
    """Controlli di integrita' sull'archivio statistiche giocatore."""
    problems: List[str] = []
    prefix = f"{league}: " if league else ""
    if not isinstance(records, list):
        return [f"{prefix}formato non valido (atteso elenco)"]
    if len(records) < min_rows:
        problems.append(f"{prefix}solo {len(records)} righe (minimo {min_rows})")

    seasons: Dict[int, int] = {}
    keys: Dict[Tuple, int] = {}
    rows_per_match: Dict[Tuple, int] = {}
    missing_fields = 0
    bad_dates = 0
    bad_ids = 0
    bad_names = 0
    bad_venue = 0
    bad_values = 0

    for rec in records:
        if not isinstance(rec, dict) or any(f not in rec for f in PLAYER_FIELDS):
            missing_fields += 1
            continue
        season = parse_season(rec.get("season"))
        if season is None:
            problems.append(f"{prefix}stagione illeggibile: {rec.get('season')!r}")
            continue
        seasons[season] = seasons.get(season, 0) + 1

        match_id = parse_int(rec.get("id"))
        if match_id is None:
            bad_ids += 1
        if parse_kickoff(rec.get("date"))[0] is None:
            bad_dates += 1
        team = clean_text(rec.get("team"))
        opponent = clean_text(rec.get("opponent"))
        if not team or not opponent or team == opponent:
            bad_names += 1
        venue = rec.get("venue")
        if venue not in VENUES:
            bad_venue += 1
        player_id = parse_int(rec.get("player_id"))
        if player_id is None or not clean_text(rec.get("player")):
            bad_values += 1
        for field_name in ("minutes", "goals", "own_goals", "shots", "assists",
                           "key_passes", "yellow_cards", "red_cards"):
            raw = rec.get(field_name)
            parser = parse_minutes if field_name == "minutes" else parse_non_negative
            if raw is not None and parser(raw) is None:
                bad_values += 1
        for field_name in ("xg", "xa", "xg_chain", "xg_buildup"):
            raw = rec.get(field_name)
            if raw is not None and parse_rate(raw) is None:
                bad_values += 1
        if match_id is not None:
            key = (season, match_id, team, player_id)
            keys[key] = keys.get(key, 0) + 1
            rows_per_match[(season, match_id)] = rows_per_match.get((season, match_id), 0) + 1

    if missing_fields:
        problems.append(f"{prefix}{missing_fields} righe senza i campi richiesti")
    if bad_ids:
        problems.append(f"{prefix}{bad_ids} righe senza id partita valido")
    if bad_dates:
        problems.append(f"{prefix}{bad_dates} righe con data illeggibile")
    if bad_names:
        problems.append(f"{prefix}{bad_names} righe con squadra/avversario mancanti o uguali")
    if bad_venue:
        problems.append(f"{prefix}{bad_venue} righe senza 'venue' valido (home/away)")
    if bad_values:
        problems.append(f"{prefix}{bad_values} valori non validi "
                        "(player_id/player assenti, minuti o conteggi fuori scala)")
    duplicated = sorted(k for k, v in keys.items() if v > 1)
    if duplicated:
        problems.append(f"{prefix}{len(duplicated)} righe duplicate (stagione, id, "
                        f"squadra, giocatore) (es. {duplicated[:3]})")

    if expected_seasons:
        missing = [s for s in expected_seasons if seasons.get(s, 0) == 0]
        if missing:
            problems.append(f"{prefix}stagioni assenti: {missing}")

    if rows_per_match:
        thin = {k: v for k, v in rows_per_match.items() if v < min_rows_per_match}
        ratio = len(thin) / len(rows_per_match)
        if ratio > max_thin_matches_ratio:
            problems.append(
                f"{prefix}{len(thin)} partite su {len(rows_per_match)} con meno di "
                f"{min_rows_per_match} righe giocatore ({ratio:.1%} > "
                f"{max_thin_matches_ratio:.0%}): roster incompleti, non 0 giocatori")
    return problems


def player_summary(records: Sequence[dict]) -> dict:
    """Statistiche descrittive del file giocatore (per report e audit)."""
    by_season: Dict[int, dict] = {}
    matches_seen: Dict[Tuple[int, int], int] = {}
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        season = parse_season(rec.get("season"))
        match_id = parse_int(rec.get("id"))
        if season is None:
            continue
        bucket = by_season.setdefault(season, {
            "rows": 0, "matches": 0, "players": set(), "teams": set(),
            "minutes_zero": 0, "minutes_none": 0, "minutes_sum": 0,
            "yellow_cards": 0, "red_cards": 0, "goals": 0,
            "min_date": None, "max_date": None,
        })
        bucket["rows"] += 1
        player_id = parse_int(rec.get("player_id"))
        if player_id is not None:
            bucket["players"].add(player_id)
        team = clean_text(rec.get("team"))
        if team:
            bucket["teams"].add(team)
        minutes = rec.get("minutes")
        if minutes is None:
            bucket["minutes_none"] += 1
        else:
            bucket["minutes_sum"] += minutes
            if minutes == 0:
                bucket["minutes_zero"] += 1
        for field_name in ("goals", "yellow_cards", "red_cards"):
            value = parse_non_negative(rec.get(field_name))
            if value:
                bucket[field_name] += value
        kickoff, _ = parse_kickoff(rec.get("date"))
        if kickoff is not None:
            day = kickoff.date().isoformat()
            bucket["min_date"] = day if bucket["min_date"] is None else min(bucket["min_date"], day)
            bucket["max_date"] = day if bucket["max_date"] is None else max(bucket["max_date"], day)
        if match_id is not None:
            key = (season, match_id)
            matches_seen[key] = matches_seen.get(key, 0) + 1

    per_season_matches: Dict[int, int] = {}
    for (season, _match_id), count in matches_seen.items():
        per_season_matches[season] = per_season_matches.get(season, 0) + 1
    for season, bucket in by_season.items():
        bucket["matches"] = per_season_matches.get(season, 0)
        bucket["players"] = len(bucket["players"])
        bucket["teams"] = len(bucket["teams"])
    return {"rows": len(records or []),
            "matches": len(matches_seen),
            "seasons": {str(k): v for k, v in sorted(by_season.items())}}


# ---------------------------------------------------------------------------
# Normalizzazione dei nomi (resolver condiviso, nessuna tabella nuova)
# ---------------------------------------------------------------------------
def name_resolution_report(records: Iterable[dict], *, kind: str = PPDA_KIND) -> dict:
    """Nomi grezzi non risolti dal resolver condiviso + collisioni.

    Usa ``team_names.resolve_team_name`` (stessa tabella della PR #15). Non
    blocca nulla: e' la misura che alimenta il report di fattibilita'.
    """
    raw_to_canonical: Dict[str, str] = {}
    unmapped: Dict[str, int] = {}
    if kind == PPDA_KIND:
        names = (name for rec in records or [] if isinstance(rec, dict)
                 for name in (rec.get("home_team"), rec.get("away_team")))
    else:
        names = (rec.get("team") for rec in records or [] if isinstance(rec, dict))
    for name in names:
        text = clean_text(name)
        if not text:
            continue
        resolution = resolve_team_name(text)
        raw_to_canonical[text] = resolution.canonical
        if not resolution.mapped:
            unmapped[text] = unmapped.get(text, 0) + 1
    grouped: Dict[str, List[str]] = {}
    for raw, canonical in raw_to_canonical.items():
        grouped.setdefault(canonical, []).append(raw)
    collisions = {c: sorted(v) for c, v in sorted(grouped.items()) if len(v) > 1}
    return {
        "raw_names": len(raw_to_canonical),
        "unmapped": dict(sorted(unmapped.items())),
        "collisions": collisions,
        "raw_to_canonical": dict(sorted(raw_to_canonical.items())),
    }


# ---------------------------------------------------------------------------
# Confronto con l'ultimo snapshot valido - PPDA/deep
# ---------------------------------------------------------------------------
def _side_signature(record: dict, side: str) -> Tuple:
    return (record.get(f"{side}_ppda"), record.get(f"{side}_deep_completions"))


def _describe(key: Tuple, record: dict) -> str:
    season = key[0]
    ident = key[1] if len(key) > 1 else "senza id"
    return (f"[{season}] {record.get('home_team')} - {record.get('away_team')} "
            f"(id {ident})")


@dataclass
class PpdaDiff:
    """Differenze fra l'ultimo PPDA/deep valido e quello appena scaricato.

    Bloccano: partite concluse con dati sparite, lati che avevano dati e ora non
    ne hanno, stagioni con dati scomparse, copertura sotto soglia (controllata
    da ``validate_ppda``).
    Sono ammessi e riportati: partite nuove, correzioni di PPDA/deep sulla
    stessa partita, record non giocati spariti, passaggio completo <-> parziale.
    """

    league: str = ""
    previous_matches: int = 0
    current_matches: int = 0
    missing_played: List[str] = field(default_factory=list)
    regressed: List[str] = field(default_factory=list)
    dropped_seasons: List[int] = field(default_factory=list)
    new_matches: List[str] = field(default_factory=list)
    corrections: List[dict] = field(default_factory=list)
    dropped_unplayed: List[str] = field(default_factory=list)
    diminished: List[str] = field(default_factory=list)
    improved: List[str] = field(default_factory=list)

    @property
    def blocking_problems(self) -> List[str]:
        prefix = f"{self.league}: " if self.league else ""
        problems: List[str] = []
        if self.missing_played:
            problems.append(
                f"{prefix}{len(self.missing_played)} partite CONCLUSE con PPDA/deep "
                f"presenti nell'ultimo file valido e assenti nel nuovo "
                f"(es. {'; '.join(self.missing_played[:5])})")
        if self.regressed:
            problems.append(
                f"{prefix}{len(self.regressed)} partite con PPDA/deep spariti "
                f"(es. {'; '.join(self.regressed[:5])})")
        if self.dropped_seasons:
            problems.append(
                f"{prefix}stagioni con dati sparite dallo snapshot: "
                f"{self.dropped_seasons} (se la riduzione e' voluta, usare "
                "--allow-dropping-seasons)")
        return problems

    def to_dict(self) -> dict:
        return {
            "league": self.league,
            "previous_matches": self.previous_matches,
            "current_matches": self.current_matches,
            "missing_played": len(self.missing_played),
            "missing_played_sample": self.missing_played[:5],
            "regressed": len(self.regressed),
            "regressed_sample": self.regressed[:5],
            "dropped_seasons": self.dropped_seasons,
            "new_matches": len(self.new_matches),
            "new_matches_sample": self.new_matches[:5],
            "corrections": len(self.corrections),
            "corrections_sample": self.corrections[:5],
            "dropped_unplayed": len(self.dropped_unplayed),
            "diminished": len(self.diminished),
            "improved": len(self.improved),
            "blocking_problems": self.blocking_problems,
        }


def compare_ppda_snapshots(
    previous: Optional[Sequence[dict]],
    current: Sequence[dict],
    *,
    league: str = "",
    requested_seasons: Optional[Sequence[int]] = None,
    allow_dropping_seasons: bool = False,
) -> PpdaDiff:
    """Confronto partita per partita (chiave stagione + id), non sul totale."""
    diff = PpdaDiff(league=league, current_matches=len(current or []))
    if not previous:
        return diff
    diff.previous_matches = len(previous)

    prev_index = {match_key(rec): rec for rec in previous if isinstance(rec, dict)}
    cur_index = {match_key(rec): rec for rec in current or [] if isinstance(rec, dict)}
    kept_seasons = set(requested_seasons or []) or None

    for key, old in prev_index.items():
        season = key[0]
        season_dropped = (kept_seasons is not None and season is not None
                          and season not in kept_seasons)
        new = cur_index.get(key)
        had_data = any(any(_side_data(old, side)) for side in VENUES)
        if new is None:
            if not _played(old) or not had_data:
                diff.dropped_unplayed.append(_describe(key, old))
            elif season_dropped:
                if season is not None and season not in diff.dropped_seasons:
                    diff.dropped_seasons.append(season)
            else:
                diff.missing_played.append(_describe(key, old))
            continue

        # Perdita di un valore che c'era: campo per campo (una partita puo'
        # perdere solo le PPDA e mantenere le deep completions).
        lost = []
        for side in VENUES:
            old_ppda, old_deep = _side_data(old, side)
            new_ppda, new_deep = _side_data(new, side)
            if old_ppda and not new_ppda:
                lost.append(f"{side}_ppda")
            if old_deep and not new_deep:
                lost.append(f"{side}_deep_completions")
        if lost:
            diff.regressed.append(_describe(key, new)
                                  + " [valori persi: " + ",".join(lost) + "]")
            continue

        before, after = record_completeness(old), record_completeness(new)
        if before == "completo" and after != "completo":
            diff.diminished.append(f"{_describe(key, new)} ({before} -> {after})")
        elif before != "completo" and after == "completo":
            diff.improved.append(f"{_describe(key, new)} ({before} -> {after})")

        for side in VENUES:
            for field_name in ("ppda", "deep_completions"):
                old_value = old.get(f"{side}_{field_name}")
                new_value = new.get(f"{side}_{field_name}")
                if old_value is None or new_value is None:
                    continue
                if isinstance(old_value, float) or isinstance(new_value, float):
                    same = math.isclose(float(old_value), float(new_value),
                                        rel_tol=0, abs_tol=1e-9)
                else:
                    same = old_value == new_value
                if not same:
                    diff.corrections.append({
                        "match": _describe(key, new),
                        "side": side,
                        "field": field_name,
                        "before": old_value,
                        "after": new_value,
                    })

    for key, new in cur_index.items():
        if key not in prev_index:
            diff.new_matches.append(_describe(key, new))

    diff.dropped_seasons.sort()
    if allow_dropping_seasons:
        diff.dropped_seasons = []
    return diff


# ---------------------------------------------------------------------------
# Confronto con l'ultimo snapshot valido - statistiche giocatore
# ---------------------------------------------------------------------------
@dataclass
class PlayerDiff:
    """Differenze fra l'ultimo file giocatore valido e quello appena scaricato.

    Bloccano: partite con righe giocatore sparite al di fuori della finestra di
    frontiera (``frontier_days``), partite che perdono oltre meta' delle righe,
    stagioni con dati scomparse.
    Sono ammesse e riportate: partite nuove, partite di frontiera ancora senza
    righe, cali di righe contenuti (correzioni di roster), aumenti di righe.
    """

    league: str = ""
    previous_matches: int = 0
    current_matches: int = 0
    previous_rows: int = 0
    current_rows: int = 0
    frontier_days: float = DEFAULT_FRONTIER_DAYS
    missing_matches: List[str] = field(default_factory=list)
    frontier_missing_matches: List[str] = field(default_factory=list)
    collapsed_matches: List[str] = field(default_factory=list)
    shrunk_matches: List[dict] = field(default_factory=list)
    grown_matches: List[dict] = field(default_factory=list)
    dropped_seasons: List[int] = field(default_factory=list)
    new_matches: List[str] = field(default_factory=list)

    @property
    def blocking_problems(self) -> List[str]:
        prefix = f"{self.league}: " if self.league else ""
        problems: List[str] = []
        if self.missing_matches:
            problems.append(
                f"{prefix}{len(self.missing_matches)} partite con statistiche "
                f"giocatore presenti nell'ultimo file valido e assenti nel nuovo, "
                f"fuori dalla finestra di {self.frontier_days:g} giorni "
                f"(es. {'; '.join(self.missing_matches[:5])})")
        if self.collapsed_matches:
            problems.append(
                f"{prefix}{len(self.collapsed_matches)} partite con oltre meta' "
                f"delle righe giocatore perse (es. "
                f"{'; '.join(self.collapsed_matches[:5])})")
        if self.dropped_seasons:
            problems.append(
                f"{prefix}stagioni con righe giocatore sparite: "
                f"{self.dropped_seasons} (se la riduzione e' voluta, usare "
                "--allow-dropping-seasons)")
        return problems

    def to_dict(self) -> dict:
        return {
            "league": self.league,
            "previous_matches": self.previous_matches,
            "current_matches": self.current_matches,
            "previous_rows": self.previous_rows,
            "current_rows": self.current_rows,
            "frontier_days": self.frontier_days,
            "missing_matches": len(self.missing_matches),
            "missing_matches_sample": self.missing_matches[:5],
            "frontier_missing_matches": len(self.frontier_missing_matches),
            "frontier_missing_sample": self.frontier_missing_matches[:5],
            "collapsed_matches": len(self.collapsed_matches),
            "collapsed_sample": self.collapsed_matches[:5],
            "shrunk_matches": len(self.shrunk_matches),
            "shrunk_sample": self.shrunk_matches[:5],
            "grown_matches": len(self.grown_matches),
            "dropped_seasons": self.dropped_seasons,
            "new_matches": len(self.new_matches),
            "new_matches_sample": self.new_matches[:5],
            "blocking_problems": self.blocking_problems,
        }


def _match_rows(records: Sequence[dict]) -> Dict[Tuple, dict]:
    """{(stagione, id): {"rows": n, "date": ..., "teams": (casa, ospite)}}."""
    index: Dict[Tuple, dict] = {}
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        season = parse_season(rec.get("season"))
        match_id = parse_int(rec.get("id"))
        if season is None or match_id is None:
            continue
        key = (season, match_id)
        entry = index.setdefault(key, {"rows": 0, "date": None, "teams": None})
        entry["rows"] += 1
        if entry["teams"] is None:
            team, opponent, venue = (clean_text(rec.get("team")),
                                     clean_text(rec.get("opponent")),
                                     rec.get("venue"))
            if team and opponent:
                entry["teams"] = ((team, opponent) if venue == "home"
                                  else (opponent, team))
        if entry["date"] is None:
            kickoff, _ = parse_kickoff(rec.get("date"))
            if kickoff is not None:
                entry["date"] = kickoff
    return index


def compare_player_snapshots(
    previous: Optional[Sequence[dict]],
    current: Sequence[dict],
    *,
    league: str = "",
    requested_seasons: Optional[Sequence[int]] = None,
    allow_dropping_seasons: bool = False,
    frontier_days: float = DEFAULT_FRONTIER_DAYS,
    now: Optional[datetime] = None,
) -> PlayerDiff:
    """Confronto partita per partita delle righe giocatore (chiave stagione + id)."""
    diff = PlayerDiff(league=league, previous_rows=len(previous or []),
                      current_rows=len(current or []), frontier_days=frontier_days)
    if not previous:
        return diff

    prev_index = _match_rows(previous)
    cur_index = _match_rows(current)
    diff.previous_matches = len(prev_index)
    diff.current_matches = len(cur_index)
    reference = as_utc(now) if now is not None else datetime.now(timezone.utc)
    kept_seasons = set(requested_seasons or []) or None

    def label(key: Tuple, entry: dict) -> str:
        teams = entry.get("teams") or ("?", "?")
        date = entry.get("date")
        day = date.date().isoformat() if date else "data n/d"
        return f"[{key[0]}] {teams[0]} - {teams[1]} (id {key[1]}, {day})"

    for key, old in prev_index.items():
        season = key[0]
        new = cur_index.get(key)
        if new is None or new["rows"] == 0:
            date = old.get("date")
            age_days = (reference - date).total_seconds() / 86400.0 if date else None
            if season is not None and kept_seasons is not None and season not in kept_seasons:
                if season not in diff.dropped_seasons:
                    diff.dropped_seasons.append(season)
                continue
            if age_days is not None and age_days <= frontier_days:
                diff.frontier_missing_matches.append(label(key, old))
            else:
                suffix = "" if age_days is None else f", eta' {age_days:.1f} giorni"
                diff.missing_matches.append(label(key, old) + suffix)
            continue

        if new["rows"] <= old["rows"] * 0.5 and old["rows"] >= 10:
            diff.collapsed_matches.append(
                f"{label(key, new)}: {old['rows']} -> {new['rows']} righe")
        elif new["rows"] < old["rows"]:
            diff.shrunk_matches.append({"match": label(key, new),
                                        "before": old["rows"], "after": new["rows"]})
        elif new["rows"] > old["rows"]:
            diff.grown_matches.append({"match": label(key, new),
                                       "before": old["rows"], "after": new["rows"]})

    for key, new in cur_index.items():
        if key not in prev_index:
            diff.new_matches.append(label(key, new))

    diff.dropped_seasons.sort()
    if allow_dropping_seasons:
        diff.dropped_seasons = []
    return diff


# ---------------------------------------------------------------------------
# Perimetro di riferimento (archivio xG) e copertura
# ---------------------------------------------------------------------------
def perimeter_from_xg_archive(league: str, base_dir=None) -> List[dict]:
    """Partite CONCLUSE con entrambi gli xG nell'archivio xG esistente.

    E' il denominatore dei report di copertura: stesso perimetro di leghe e
    stagioni dell'archivio, senza inventare un secondo calendario.
    """
    perimeter: List[dict] = []
    for rec in load_archive(league, base_dir) or []:
        if not isinstance(rec, dict):
            continue
        if not parse_bool(rec.get("is_result")):
            continue
        home_xg = rec.get("home_xg")
        away_xg = rec.get("away_xg")
        if not isinstance(home_xg, (int, float)) or isinstance(home_xg, bool):
            continue
        if not isinstance(away_xg, (int, float)) or isinstance(away_xg, bool):
            continue
        kickoff, _ = parse_kickoff(rec.get("date"))
        perimeter.append({
            "season": parse_season(rec.get("season")),
            "id": parse_int(rec.get("id")),
            "date": kickoff,
            "home_team": clean_text(rec.get("home_team")),
            "away_team": clean_text(rec.get("away_team")),
        })
    return perimeter


def _as_date(value):
    """Data del perimetro -> datetime (accetta datetime, date o stringa)."""
    if value is None or isinstance(value, (datetime, date)):
        return value
    parsed, _ = parse_kickoff(value)
    return parsed


def coverage_against_perimeter(
    records: Sequence[dict],
    perimeter: Sequence[dict],
    *,
    kind: str = PPDA_KIND,
    seasons: Optional[Sequence[int]] = None,
) -> dict:
    """Copertura dell'archivio rispetto al perimetro (archivio xG), per stagione.

    Per ``PPDA_KIND`` distingue i quattro valori (2 lati x PPDA/deep); per
    ``PLAYER_KIND`` conta le partite con almeno una riga giocatore.
    """
    reference: Dict[Tuple, dict] = {}
    for rec in perimeter or []:
        season = parse_season(rec.get("season"))
        match_id = parse_int(rec.get("id"))
        if season is None or match_id is None:
            continue
        if seasons:
            wanted = {parse_season(s) for s in seasons}
            if season not in wanted:
                continue
        reference[(season, match_id)] = rec

    per_season: Dict[int, dict] = {
        season: {"reference_matches": 0, "present_matches": 0,
                 "with_home_ppda": 0, "with_away_ppda": 0,
                 "with_home_deep": 0, "with_away_deep": 0,
                 "complete": 0, "partial": 0, "empty": 0,
                 "missing_matches": []}
        for season in sorted({key[0] for key in reference})
    }
    for key in reference:
        per_season[key[0]]["reference_matches"] += 1

    seen: Dict[Tuple, dict] = {}
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        season = parse_season(rec.get("season"))
        match_id = parse_int(rec.get("id"))
        if season is None or match_id is None or (season, match_id) not in reference:
            continue
        seen[(season, match_id)] = rec
        bucket = per_season.setdefault(season, {
            "reference_matches": 0, "present_matches": 0,
            "with_home_ppda": 0, "with_away_ppda": 0,
            "with_home_deep": 0, "with_away_deep": 0,
            "complete": 0, "partial": 0, "empty": 0, "missing_matches": []})
        bucket["present_matches"] += 1
        if kind == PPDA_KIND:
            for side in VENUES:
                has_ppda, has_deep = _side_data(rec, side)
                bucket[f"with_{side}_ppda"] += 1 if has_ppda else 0
                bucket[f"with_{side}_deep"] += 1 if has_deep else 0
            bucket[_completeness_key(rec)] += 1
        else:
            bucket["complete"] += 1

    def _sort_key(item):
        date = _as_date(item[1].get("date"))
        return date or datetime.min.replace(tzinfo=timezone.utc)

    for (season, match_id), ref in sorted(reference.items(), key=_sort_key):
        if (season, match_id) in seen:
            continue
        entry = per_season.setdefault(season, {
            "reference_matches": 0, "present_matches": 0,
            "with_home_ppda": 0, "with_away_ppda": 0,
            "with_home_deep": 0, "with_away_deep": 0,
            "complete": 0, "partial": 0, "empty": 0, "missing_matches": []})
        date = _as_date(ref.get("date"))
        entry["missing_matches"].append({
            "id": match_id,
            "date": date.date().isoformat() if hasattr(date, "date") else None,
            "home_team": ref.get("home_team"),
            "away_team": ref.get("away_team"),
        })

    for bucket in per_season.values():
        reference_count = bucket["reference_matches"]
        bucket["presence_ratio"] = (bucket["present_matches"] / reference_count
                                    if reference_count else 0.0)
        if kind == PPDA_KIND:
            bucket["complete_ratio"] = (bucket["complete"] / reference_count
                                        if reference_count else 0.0)
        bucket["missing_matches_total"] = len(bucket["missing_matches"])
        bucket["missing_matches"] = bucket["missing_matches"][:SAMPLE_LIMIT]
    return {"kind": kind,
            "reference_matches": len(reference),
            "present_matches": len(seen),
            "seasons": {str(k): v for k, v in sorted(per_season.items())}}


def age_histogram(entries: Sequence[dict], reference: datetime, *,
                  buckets: Sequence[float] = (1, 3, 7, 30)) -> dict:
    """Distribuzione delle eta' (giorni) delle partite mancanti.

    Serve a distinguere un ritardo di frontiera (solo le partite piu' recenti)
    da un buco sistematico (partite vecchie mancanti).
    """
    reference = as_utc(reference) or reference
    counts: Dict[str, int] = {f"<={b:g}g": 0 for b in buckets}
    counts[f">{buckets[-1]:g}g"] = 0
    unknown = 0
    ages: List[float] = []
    for entry in entries or []:
        date = entry.get("date")
        if isinstance(date, str):
            parsed, _ = parse_kickoff(date)
            date = parsed
        if date is None:
            unknown += 1
            continue
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        age = (reference - date).total_seconds() / 86400.0
        ages.append(age)
        placed = False
        for bound in buckets:
            if age <= bound:
                counts[f"<={bound:g}g"] += 1
                placed = True
                break
        if not placed:
            counts[f">{buckets[-1]:g}g"] += 1
    return {"counts": counts, "unknown_date": unknown, "ages": sorted(ages),
            "n": len(entries or [])}


def percentile(sorted_values: Sequence[float], fraction: float) -> Optional[float]:
    """Percentile nearest-rank su una sequenza gia' ordinata (nessuna dipendenza)."""
    if not sorted_values:
        return None
    if fraction <= 0:
        return float(sorted_values[0])
    if fraction >= 1:
        return float(sorted_values[-1])
    index = max(0, min(len(sorted_values) - 1,
                       math.ceil(fraction * len(sorted_values)) - 1))
    return float(sorted_values[index])


def describe_distribution(values: Sequence[float]) -> dict:
    """Sintesi di una distribuzione (n, media, percentili, zeri)."""
    clean = sorted(float(v) for v in values if v is not None)
    if not clean:
        return {"n": 0}
    return {
        "n": len(clean),
        "mean": sum(clean) / len(clean),
        "min": clean[0],
        "p05": percentile(clean, 0.05),
        "p25": percentile(clean, 0.25),
        "p50": percentile(clean, 0.50),
        "p75": percentile(clean, 0.75),
        "p90": percentile(clean, 0.90),
        "p95": percentile(clean, 0.95),
        "max": clean[-1],
        "zeros": sum(1 for v in clean if v == 0.0),
    }
