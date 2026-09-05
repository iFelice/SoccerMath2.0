"""
xg_archive.py - Lettura, validazione e aggregazione dell'archivio xG per-partita.

L'unica acquisizione da Understat e' ``update_all_xg_db.py``, che salva in
``SoccerMath/database/xG archivio <lega>.json`` una lista di partite:

    {"season": 2026, "id": 30012, "date": "2026-08-22 18:45:00",
     "home_team": "Inter", "away_team": "Torino",
     "home_goals": 3, "away_goals": 1,
     "home_xg": 2.41, "away_xg": 0.77, "is_result": true}

Da qui si derivano le medie stagionali usate dall'app
(``database/xg_<lega>.json``):

    squadra di casa   -> xG = home_xg, xGA = away_xg
    squadra ospite    -> xG = away_xg, xGA = home_xg
    matches           -> numero di partite valide effettivamente incluse

Regole di validita' (nessuna invenzione di dati):
  * solo partite concluse (``is_result`` vero);
  * entrambi gli xG devono essere numerici, finiti e non negativi;
  * lo 0.0 e' un valore VALIDO (0.00 xG in una partita esiste); un dato
    mancante (``None``/NaN) non diventa mai 0;
  * niente doppi conteggi: deduplica per ``id`` (o per chiave stagione + data
    + squadre se l'id manca) e i conflitti vengono segnalati, non mediati;
  * niente mescolanza di stagioni: si aggrega una sola ``season`` per volta;
  * nessuno shrinkage qui: resta in ``app.get_league_engine`` (PRIOR_MATCHES).

Il cutoff temporale (`cutoff`) rende l'aggregazione riutilizzabile per audit
point-in-time: include solo le partite concluse PRIMA dell'istante indicato.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from config import DATABASE_DIR, LEAGUES_CONFIG
from team_names import canonical_team_name, resolve_team_name

# ---------------------------------------------------------------------------
# File
# ---------------------------------------------------------------------------
ARCHIVE_FILES: Dict[str, str] = {
    "Serie A": "xG archivio serie A.json",
    "Premier League": "xG archivio premier league.json",
    "La Liga": "xG archivio la liga.json",
    "Bundesliga": "xG archivio bundesliga.json",
    "Ligue 1": "xG archivio ligue 1.json",
}

# Nomi Understat delle leghe usati da soccerdata (unica acquisizione).
SOCCERDATA_LEAGUES: Dict[str, str] = {
    "Serie A": "ITA-Serie A",
    "Premier League": "ENG-Premier League",
    "La Liga": "ESP-La Liga",
    "Bundesliga": "GER-Bundesliga",
    "Ligue 1": "FRA-Ligue 1",
}

LEAGUES: Tuple[str, ...] = tuple(ARCHIVE_FILES)

# Colonne attese in ogni record dell'archivio.
REQUIRED_FIELDS: Tuple[str, ...] = (
    "season", "id", "date", "home_team", "away_team",
    "home_goals", "away_goals", "home_xg", "away_xg", "is_result",
)

# Gli orari dell'archivio sono i kickoff pubblicati da Understat, senza offset.
# Li si interpreta in UTC per avere confronti di date deterministici: la scelta
# e' esplicita e documentata (vedi audit/results/xg_pipeline_consolidation.md),
# NON una verifica del fuso reale usato da Understat.
ARCHIVE_TIMEZONE = timezone.utc

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def archive_path(league: str, base_dir=None) -> str:
    base = str(base_dir) if base_dir is not None else str(DATABASE_DIR)
    return os.path.join(base, ARCHIVE_FILES[league])


def averages_path(league: str, base_dir=None) -> str:
    cfg = LEAGUES_CONFIG[league]
    if base_dir is None:
        return str(cfg["xg_json"])
    return os.path.join(str(base_dir), os.path.basename(str(cfg["xg_json"])))


# ---------------------------------------------------------------------------
# Parsing helper
# ---------------------------------------------------------------------------
def parse_season(value) -> Optional[int]:
    """Stagione come anno di inizio (2026 = 2026/27). None se illeggibile."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if float(value).is_integer() else None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        if len(text) == 4:
            # "2026" = anno; "2627" = formato stagione soccerdata (2026/27)
            if text.startswith(("19", "20")):
                return int(text)
            first, second = int(text[:2]), int(text[2:])
            if second in (first + 1, (first + 1) % 100):
                return 2000 + first
            return None
        if len(text) == 2:  # "26" -> 2026
            return 2000 + int(text)
        return None
    m = re.match(r"^(\d{4})\s*[/-]\s*\d{2,4}$", text)  # "2026/2027", "2026-27"
    if m:
        return int(m.group(1))
    return None


def parse_kickoff(value) -> Tuple[Optional[datetime], bool]:
    """Ritorna ``(kickoff_aware, has_time)``.

    ``has_time`` e' False quando l'archivio conserva soltanto il giorno (o un
    orario 00:00:00, che Understat non usa mai per un calcio d'inizio reale):
    in quel caso il chiamante deve escludere conservativamente l'intero giorno.
    """
    if value is None or isinstance(value, bool):
        return None, False
    if isinstance(value, datetime):
        dt = value
        has_time = dt.time() != time(0, 0)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ARCHIVE_TIMEZONE)
        return dt, has_time
    if isinstance(value, date):
        return datetime.combine(value, time(0, 0), tzinfo=ARCHIVE_TIMEZONE), False
    text = str(value).strip()
    if not text:
        return None, False
    if _DATE_ONLY_RE.match(text):
        try:
            d = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None, False
        return d.replace(tzinfo=ARCHIVE_TIMEZONE), False
    normalized = text.replace("T", " ")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(normalized, fmt)
        except ValueError:
            continue
        return dt.replace(tzinfo=ARCHIVE_TIMEZONE), dt.time() != time(0, 0)
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None, False
    has_time = dt.time() != time(0, 0)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ARCHIVE_TIMEZONE)
    return dt, has_time


def parse_xg(value) -> Optional[float]:
    """xG valido: numerico, finito, non negativo. Lo 0.0 e' valido."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or x < 0:
        return None
    return x


def is_played(record) -> bool:
    value = record.get("is_result")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "t"}
    return False


def as_utc(value, default_tz=ARCHIVE_TIMEZONE) -> Optional[datetime]:
    """Converte un cutoff (datetime/date/str ISO) in datetime timezone-aware."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, time(0, 0))
    else:
        dt, _ = parse_kickoff(value)
        if dt is None:
            raise ValueError(f"cutoff non interpretabile: {value!r}")
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return dt


# ---------------------------------------------------------------------------
# Risultato dell'aggregazione
# ---------------------------------------------------------------------------
@dataclass
class SeasonAggregate:
    """Medie stagionali derivate dall'archivio + diagnostica completa."""

    league: str
    season: int
    cutoff: Optional[datetime] = None
    averages: Dict[str, Dict[str, float]] = field(default_factory=dict)
    matches_used: int = 0
    matches_in_season: int = 0
    skipped: Dict[str, int] = field(default_factory=dict)
    duplicates: List[dict] = field(default_factory=list)
    conflicts: List[dict] = field(default_factory=list)
    unmapped_names: Dict[str, int] = field(default_factory=dict)
    teams_seen: Dict[str, int] = field(default_factory=dict)

    @property
    def teams_without_valid_matches(self) -> List[str]:
        """Squadre viste in stagione ma senza nemmeno una partita valida.

        Non finiscono nel file delle medie (nessuna statistica inventata):
        i consumatori cadono sul fallback gia' esistente in
        ``get_league_engine`` (rapporto sui gol con shrinkage).
        """
        return sorted(t for t in self.teams_seen if t not in self.averages)

    def to_dict(self) -> dict:
        return {
            "league": self.league,
            "season": self.season,
            "cutoff": self.cutoff.isoformat() if self.cutoff else None,
            "teams": len(self.averages),
            "matches_used": self.matches_used,
            "matches_in_season": self.matches_in_season,
            "skipped": dict(sorted(self.skipped.items())),
            "duplicates": self.duplicates,
            "conflicts": self.conflicts,
            "unmapped_names": dict(sorted(self.unmapped_names.items())),
            "teams_without_valid_matches": self.teams_without_valid_matches,
        }


def _bump(counter: Dict[str, int], key: str, amount: int = 1) -> None:
    counter[key] = counter.get(key, 0) + amount


# ---------------------------------------------------------------------------
# Aggregazione
# ---------------------------------------------------------------------------
def aggregate_season(
    records: Iterable[dict],
    season: int,
    *,
    league: str = "",
    cutoff=None,
    resolver=canonical_team_name,
    round_digits: int = 3,
) -> SeasonAggregate:
    """Medie xG/xGA della sola ``season`` a partire dalle partite dell'archivio.

    Parameters
    ----------
    records:
        partite dell'archivio (lista di dizionari).
    season:
        anno di inizio stagione (2026 = 2026/27).
    cutoff:
        se valorizzato, include SOLO le partite concluse prima di quell'istante
        (timezone esplicita). Se l'archivio conserva soltanto il giorno, l'intero
        giorno del cutoff viene escluso.
    resolver:
        funzione nome grezzo -> nome canonico. Default: la tabella condivisa di
        ``team_names`` (nessun fuzzy matching).
    """
    season_int = parse_season(season)
    if season_int is None:
        raise ValueError(f"stagione non valida: {season!r}")
    cutoff_dt = as_utc(cutoff)

    agg = SeasonAggregate(league=league, season=season_int, cutoff=cutoff_dt)
    totals: Dict[str, List[float]] = {}
    seen_keys: Dict[object, dict] = {}

    for raw in records or []:
        if not isinstance(raw, dict):
            _bump(agg.skipped, "record_non_valido")
            continue

        rec_season = parse_season(raw.get("season"))
        if rec_season is None:
            _bump(agg.skipped, "stagione_illeggibile")
            continue
        if rec_season != season_int:
            _bump(agg.skipped, "altra_stagione")
            continue

        agg.matches_in_season += 1

        home_res = resolve_team_name(raw.get("home_team"))
        away_res = resolve_team_name(raw.get("away_team"))
        home, away = home_res.canonical, away_res.canonical
        if not home or not away:
            _bump(agg.skipped, "squadra_mancante")
            continue
        for res in (home_res, away_res):
            if not res.mapped:
                _bump(agg.unmapped_names, res.raw)
        _bump(agg.teams_seen, home)
        _bump(agg.teams_seen, away)

        if not is_played(raw):
            _bump(agg.skipped, "non_giocata")
            continue

        kickoff, has_time = parse_kickoff(raw.get("date"))
        if cutoff_dt is not None:
            if kickoff is None:
                # senza data non si puo' garantire il point-in-time
                _bump(agg.skipped, "data_illeggibile_con_cutoff")
                continue
            if has_time:
                if kickoff >= cutoff_dt:
                    _bump(agg.skipped, "dopo_cutoff")
                    continue
            else:
                # solo il giorno: si esclude conservativamente l'intero giorno
                # del cutoff (e ogni giorno successivo).
                if kickoff.date() >= cutoff_dt.astimezone(kickoff.tzinfo).date():
                    _bump(agg.skipped, "stesso_giorno_o_dopo_cutoff")
                    continue

        home_xg = parse_xg(raw.get("home_xg"))
        away_xg = parse_xg(raw.get("away_xg"))
        if home_xg is None or away_xg is None:
            _bump(agg.skipped, "xg_mancante_o_non_valido")
            continue

        match_id = raw.get("id")
        if match_id is None or isinstance(match_id, bool):
            key = (season_int, home, away, kickoff.date() if kickoff else None)
        else:
            key = ("id", str(match_id))

        previous = seen_keys.get(key)
        if previous is not None:
            same = (
                previous["home"] == home and previous["away"] == away
                and math.isclose(previous["home_xg"], home_xg, rel_tol=0, abs_tol=1e-9)
                and math.isclose(previous["away_xg"], away_xg, rel_tol=0, abs_tol=1e-9)
            )
            entry = {
                "key": list(key) if isinstance(key, tuple) else key,
                "home": home, "away": away,
                "kept": {"home_xg": previous["home_xg"], "away_xg": previous["away_xg"]},
                "discarded": {"home_xg": home_xg, "away_xg": away_xg},
            }
            if same:
                agg.duplicates.append(entry)
                _bump(agg.skipped, "duplicato")
            else:
                agg.conflicts.append(entry)
                _bump(agg.skipped, "conflitto")
            continue

        seen_keys[key] = {"home": home, "away": away,
                          "home_xg": home_xg, "away_xg": away_xg}

        totals.setdefault(home, [0.0, 0.0, 0])
        totals.setdefault(away, [0.0, 0.0, 0])
        # casa: xG = home_xg, xGA = away_xg — trasferta: speculare
        totals[home][0] += home_xg
        totals[home][1] += away_xg
        totals[home][2] += 1
        totals[away][0] += away_xg
        totals[away][1] += home_xg
        totals[away][2] += 1
        agg.matches_used += 1

    for team, (sum_xg, sum_xga, n) in sorted(totals.items()):
        if n <= 0:  # difensivo: non dovrebbe accadere
            continue
        agg.averages[team] = {
            "xG_avg": round(sum_xg / n, round_digits),
            "xGA_avg": round(sum_xga / n, round_digits),
            "matches": n,
        }
    return agg


# ---------------------------------------------------------------------------
# I/O archivio
# ---------------------------------------------------------------------------
def load_archive(league: str, base_dir=None) -> List[dict]:
    path = archive_path(league, base_dir)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path}: atteso un elenco di partite, trovato {type(data).__name__}")
    return data


def validate_archive(
    records: Sequence[dict],
    *,
    league: str = "",
    min_matches: int = 100,
    expected_seasons: Optional[Sequence[int]] = None,
) -> List[str]:
    """Controlli di integrita' sull'archivio. Ritorna la lista dei problemi.

    Un archivio che non passa questi controlli NON deve sovrascrivere l'ultimo
    insieme valido (vedi ``update_all_xg_db.py``).
    """
    problems: List[str] = []
    prefix = f"{league}: " if league else ""
    if not isinstance(records, list):
        return [f"{prefix}formato non valido (atteso elenco)"]
    if len(records) < min_matches:
        problems.append(f"{prefix}solo {len(records)} partite (minimo {min_matches})")

    seasons: Dict[int, int] = {}
    ids: Dict[object, int] = {}
    missing_fields = 0
    bad_dates = 0
    played_without_xg = 0

    for rec in records:
        if not isinstance(rec, dict):
            missing_fields += 1
            continue
        if any(field_name not in rec for field_name in REQUIRED_FIELDS):
            missing_fields += 1
            continue
        s = parse_season(rec.get("season"))
        if s is None:
            problems.append(f"{prefix}stagione illeggibile: {rec.get('season')!r}")
        else:
            seasons[s] = seasons.get(s, 0) + 1
        kickoff, _ = parse_kickoff(rec.get("date"))
        if kickoff is None:
            bad_dates += 1
        rid = rec.get("id")
        if rid is not None:
            ids[rid] = ids.get(rid, 0) + 1
        if is_played(rec) and (parse_xg(rec.get("home_xg")) is None
                               or parse_xg(rec.get("away_xg")) is None):
            played_without_xg += 1

    if missing_fields:
        problems.append(f"{prefix}{missing_fields} record senza i campi richiesti")
    if bad_dates:
        problems.append(f"{prefix}{bad_dates} record con data illeggibile")
    duplicated = sorted(k for k, v in ids.items() if v > 1)
    if duplicated:
        problems.append(f"{prefix}{len(duplicated)} id duplicati (es. {duplicated[:5]})")
    if played_without_xg:
        problems.append(
            f"{prefix}{played_without_xg} partite concluse senza xG numerici")
    if expected_seasons:
        missing = [s for s in expected_seasons if seasons.get(s, 0) == 0]
        if missing:
            problems.append(f"{prefix}stagioni assenti: {missing}")
    return problems


def season_averages(
    league: str,
    season: int,
    *,
    base_dir=None,
    cutoff=None,
    records: Optional[Sequence[dict]] = None,
) -> SeasonAggregate:
    """Carica l'archivio della lega e ne deriva le medie della stagione."""
    data = list(records) if records is not None else load_archive(league, base_dir)
    return aggregate_season(data, season, league=league, cutoff=cutoff)


def write_averages(aggregate: SeasonAggregate, path: str) -> None:
    """Scrive ``xg_<lega>.json`` in modo atomico (tmp + os.replace)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        # le squadre sono gia' in ordine alfabetico: sort_keys=False preserva
        # l'ordine dei campi (xG_avg, xGA_avg, matches) nel record
        json.dump(aggregate.averages, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
