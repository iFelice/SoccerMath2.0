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

Cutoff temporale (audit point-in-time)
--------------------------------------
``cutoff`` rende l'aggregazione riutilizzabile per ricostruire cosa era
DAVVERO noto a un certo istante. Il criterio predefinito
(``cutoff_policy="previous_day"``) e' conservativo:

    entrano solo le partite dei GIORNI STRETTAMENTE PRECEDENTI al giorno del
    cutoff, nel fuso dichiarato da ``day_timezone`` (default UTC).

Motivo: il fatto che il calcio d'inizio sia anteriore al cutoff NON dimostra
che la partita fosse finita, ne' che gli xG fossero gia' pubblicati (kickoff
18:00, cutoff 18:30 -> partita ancora in corso). L'archivio contiene solo
``is_result`` allo stato ODIERNO, quindi usarlo insieme al kickoff
retrodaterebbe informazione. Non si assume alcuna durata fissa della partita:
non e' un dato verificato ne' disponibile nell'archivio, quindi si esclude
l'intero giorno del cutoff.

``cutoff_policy="kickoff_unsafe"`` (opt-in) confronta direttamente il kickoff
con il cutoff: piu' permissivo, NON verificato, da usare solo per esperimenti
dichiarati come tali. Anche in questa modalita', se il record ha la sola data
(senza orario) vale la regola del giorno intero.

Limiti dichiarati, non risolvibili con questi dati:
  * gli xG di Understat possono essere RIVISTI dopo la partita: l'archivio
    conserva l'ultimo valore, quindi una ricostruzione point-in-time usa xG
    potenzialmente piu' recenti di quelli visibili all'epoca;
  * il fuso degli orari Understat non e' documentato nel dato: si interpreta
    in ``ARCHIVE_TIMEZONE`` (UTC) per scelta esplicita, e ``day_timezone``
    permette di dichiarare il fuso in cui si contano i giorni.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone, tzinfo
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

# Politiche di taglio temporale (vedi docstring del modulo).
#   "previous_day"   -> default conservativo: solo i giorni precedenti a quello
#                       del cutoff, nel fuso `day_timezone`.
#   "kickoff_unsafe" -> confronto diretto kickoff < cutoff. NON verificato:
#                       puo' includere partite ancora in corso all'istante del
#                       cutoff. Solo su richiesta esplicita.
CUTOFF_POLICIES: Tuple[str, ...] = ("previous_day", "kickoff_unsafe")
DEFAULT_CUTOFF_POLICY = "previous_day"

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_OFFSET_RE = re.compile(r"^[+-]\d{2}:?\d{2}$")


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


def resolve_timezone(value) -> timezone:
    """Fuso in cui contare i giorni: ``tzinfo``, nome IANA o offset "+02:00"."""
    if value is None:
        return ARCHIVE_TIMEZONE
    if isinstance(value, tzinfo):
        return value
    text = str(value).strip()
    if not text or text.upper() == "UTC":
        return ARCHIVE_TIMEZONE
    if _OFFSET_RE.match(text):
        sign = -1 if text[0] == "-" else 1
        hh, mm = text[1:].split(":") if ":" in text else (text[1:3], text[3:5])
        return timezone(sign * timedelta(hours=int(hh), minutes=int(mm or 0)))
    try:
        from zoneinfo import ZoneInfo
    except ImportError as exc:  # pragma: no cover - Python < 3.9
        raise ValueError(f"fuso non supportato: {value!r}") from exc
    try:
        return ZoneInfo(text)
    except Exception as exc:
        raise ValueError(f"fuso non riconosciuto: {value!r}") from exc


def timezone_label(tz) -> str:
    """Etichetta leggibile del fuso, per i report e i file di diagnostica."""
    if tz is None:
        return "UTC"
    key = getattr(tz, "key", None)
    if key:
        return str(key)
    if tz == timezone.utc:
        return "UTC"
    return str(tz)


# ---------------------------------------------------------------------------
# Risultato dell'aggregazione
# ---------------------------------------------------------------------------
@dataclass
class SeasonAggregate:
    """Medie stagionali derivate dall'archivio + diagnostica completa."""

    league: str
    season: int
    cutoff: Optional[datetime] = None
    cutoff_policy: str = DEFAULT_CUTOFF_POLICY
    day_timezone: str = "UTC"
    averages: Dict[str, Dict[str, float]] = field(default_factory=dict)
    matches_used: int = 0
    matches_in_season: int = 0
    skipped: Dict[str, int] = field(default_factory=dict)
    duplicates: List[dict] = field(default_factory=list)
    conflicts: List[dict] = field(default_factory=list)
    unmapped_names: Dict[str, int] = field(default_factory=dict)
    teams_seen: Dict[str, int] = field(default_factory=dict)
    # nome grezzo dell'archivio -> nome canonico (per la validazione bloccante
    # dei nomi in update_xg.derive_league)
    raw_to_canonical: Dict[str, str] = field(default_factory=dict)

    @property
    def name_collisions(self) -> Dict[str, List[str]]:
        """Nomi canonici raggiunti da PIU' nomi grezzi diversi nella stagione.

        Non e' automaticamente un errore (un archivio puo' contenere due grafie
        della stessa squadra), ma non e' distinguibile dal caso in cui due club
        diversi vengono fusi: la decisione sta a chi valida
        (``update_xg.derive_league`` blocca se la collisione non e' dichiarata).
        """
        grouped: Dict[str, List[str]] = {}
        for raw, canonical in self.raw_to_canonical.items():
            grouped.setdefault(canonical, []).append(raw)
        return {c: sorted(v) for c, v in sorted(grouped.items()) if len(v) > 1}

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
            "cutoff_policy": self.cutoff_policy,
            "day_timezone": self.day_timezone,
            "teams": len(self.averages),
            "matches_used": self.matches_used,
            "matches_in_season": self.matches_in_season,
            "skipped": dict(sorted(self.skipped.items())),
            "duplicates": self.duplicates,
            "conflicts": self.conflicts,
            "unmapped_names": dict(sorted(self.unmapped_names.items())),
            "name_collisions": self.name_collisions,
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
    cutoff_policy: str = DEFAULT_CUTOFF_POLICY,
    day_timezone=ARCHIVE_TIMEZONE,
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
        se valorizzato, ricostruisce lo stato point-in-time (vedi docstring del
        modulo). Un cutoff senza fuso viene interpretato in ``ARCHIVE_TIMEZONE``.
    cutoff_policy:
        ``"previous_day"`` (default, conservativo): entrano solo le partite dei
        giorni precedenti a quello del cutoff, quindi nessuna partita ancora in
        corso all'istante del cutoff puo' entrare.
        ``"kickoff_unsafe"``: confronto diretto ``kickoff < cutoff``; puo'
        includere partite non ancora finite. Opt-in, non verificato.
    day_timezone:
        fuso in cui si contano i giorni (``tzinfo``, nome IANA come
        ``"Europe/Rome"`` o offset ``"+02:00"``). Default UTC, coerente con
        ``ARCHIVE_TIMEZONE``. Cambia quali partite serali finiscono nel giorno
        precedente: e' una scelta dichiarata, non un dato dell'archivio.
    resolver:
        funzione nome grezzo -> nome canonico. Default: la tabella condivisa di
        ``team_names`` (nessun fuzzy matching).
    """
    season_int = parse_season(season)
    if season_int is None:
        raise ValueError(f"stagione non valida: {season!r}")
    if cutoff_policy not in CUTOFF_POLICIES:
        raise ValueError(
            f"cutoff_policy non valida: {cutoff_policy!r} (attese: {list(CUTOFF_POLICIES)})")
    cutoff_dt = as_utc(cutoff)
    day_tz = resolve_timezone(day_timezone)
    cutoff_day = cutoff_dt.astimezone(day_tz).date() if cutoff_dt is not None else None

    agg = SeasonAggregate(
        league=league, season=season_int, cutoff=cutoff_dt,
        cutoff_policy=cutoff_policy, day_timezone=timezone_label(day_tz),
    )
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
            agg.raw_to_canonical[res.raw] = res.canonical
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
            if cutoff_policy == "kickoff_unsafe" and has_time:
                # opt-in: confronto diretto, puo' includere partite in corso
                if kickoff >= cutoff_dt:
                    _bump(agg.skipped, "dopo_cutoff")
                    continue
            else:
                # default conservativo (e unico criterio possibile quando il
                # record ha la sola data): l'intero giorno del cutoff, e ogni
                # giorno successivo, restano fuori. Una partita iniziata alle
                # 18:00 con cutoff alle 18:30 poteva essere ancora in corso:
                # includerla significherebbe usare informazione non disponibile.
                if kickoff.astimezone(day_tz).date() >= cutoff_day:
                    _bump(agg.skipped, "giorno_del_cutoff_o_dopo")
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


# ---------------------------------------------------------------------------
# Confronto fra due snapshot dell'archivio (protezione dagli scrape parziali)
# ---------------------------------------------------------------------------
def match_key(record: dict) -> Tuple:
    """Chiave stabile di una partita: (stagione, id) o (stagione, casa, ospite).

    L'id di Understat e' l'identificatore naturale; il fallback serve solo agli
    archivi storici senza id (non presenti nei dati attuali: 0 record senza id).
    """
    season = parse_season(record.get("season"))
    rid = record.get("id")
    if rid is None or isinstance(rid, bool):
        return (season, str(record.get("home_team") or "").strip(),
                str(record.get("away_team") or "").strip())
    return (season, str(rid))


def _finished_with_xg(record: dict) -> bool:
    return (is_played(record)
            and parse_xg(record.get("home_xg")) is not None
            and parse_xg(record.get("away_xg")) is not None)


def _describe(key: Tuple, record: dict) -> str:
    season = key[0]
    home = record.get("home_team")
    away = record.get("away_team")
    ident = key[1] if len(key) == 2 else "senza id"
    return f"[{season}] {home} - {away} (id {ident})"


@dataclass
class SnapshotDiff:
    """Differenze fra l'ultimo archivio valido e quello appena scaricato.

    Distingue le variazioni LEGITTIME (nuove partite, correzioni di xG sulla
    stessa partita, fixture non giocate rimosse dal calendario) dalle
    variazioni che indicano uno scrape parziale o un dato perso:
      * ``missing_finished``  partite CONCLUSE con xG valido sparite;
      * ``regressed``         partite concluse tornate "non giocata"/senza xG;
      * ``dropped_seasons``   stagioni con risultati sparite dallo snapshot.
    Solo queste tre categorie sono bloccanti.
    """

    league: str = ""
    previous_matches: int = 0
    current_matches: int = 0
    missing_finished: List[str] = field(default_factory=list)
    regressed: List[str] = field(default_factory=list)
    dropped_seasons: List[int] = field(default_factory=list)
    new_matches: List[str] = field(default_factory=list)
    xg_corrections: List[dict] = field(default_factory=list)
    dropped_unplayed: List[str] = field(default_factory=list)

    @property
    def blocking_problems(self) -> List[str]:
        prefix = f"{self.league}: " if self.league else ""
        problems: List[str] = []
        if self.missing_finished:
            problems.append(
                f"{prefix}{len(self.missing_finished)} partite CONCLUSE con xG "
                f"presenti nell'archivio precedente e assenti nel nuovo "
                f"(es. {'; '.join(self.missing_finished[:5])})")
        if self.regressed:
            problems.append(
                f"{prefix}{len(self.regressed)} partite regredite da conclusa "
                f"con xG a non giocata/senza xG "
                f"(es. {'; '.join(self.regressed[:5])})")
        if self.dropped_seasons:
            problems.append(
                f"{prefix}stagioni con risultati sparite dallo snapshot: "
                f"{self.dropped_seasons} (se la riduzione e' voluta, usare "
                "--allow-dropping-seasons)")
        return problems

    def to_dict(self) -> dict:
        return {
            "league": self.league,
            "previous_matches": self.previous_matches,
            "current_matches": self.current_matches,
            "missing_finished": self.missing_finished,
            "regressed": self.regressed,
            "dropped_seasons": self.dropped_seasons,
            "new_matches": len(self.new_matches),
            "new_matches_sample": self.new_matches[:5],
            "xg_corrections": len(self.xg_corrections),
            "xg_corrections_sample": self.xg_corrections[:5],
            "dropped_unplayed": len(self.dropped_unplayed),
            "dropped_unplayed_sample": self.dropped_unplayed[:5],
            "blocking_problems": self.blocking_problems,
        }


def compare_snapshots(
    previous: Optional[Sequence[dict]],
    current: Sequence[dict],
    *,
    league: str = "",
    requested_seasons: Optional[Sequence[int]] = None,
    allow_dropping_seasons: bool = False,
) -> SnapshotDiff:
    """Confronta due snapshot partita per partita (chiave stagione + id).

    Il totale delle partite non basta: uno snapshot puo' avere lo STESSO numero
    di righe e aver perso un risultato (una partita conclusa sostituita da una
    nuova fixture). Qui si confronta identita' e stato di ogni partita.

    ``requested_seasons``: stagioni chieste a monte. Le stagioni presenti nel
    vecchio archivio ma NON richieste sono una scelta esplicita solo se
    ``allow_dropping_seasons`` e' vero, altrimenti bloccano.
    """
    diff = SnapshotDiff(league=league, current_matches=len(current or []))
    if not previous:
        return diff
    diff.previous_matches = len(previous)

    prev_index: Dict[Tuple, dict] = {}
    for rec in previous:
        if isinstance(rec, dict):
            prev_index[match_key(rec)] = rec
    cur_index: Dict[Tuple, dict] = {}
    for rec in current or []:
        if isinstance(rec, dict):
            cur_index[match_key(rec)] = rec

    kept_seasons = set(requested_seasons or []) or None

    for key, old in prev_index.items():
        season = key[0]
        season_dropped = (
            kept_seasons is not None and season is not None
            and season not in kept_seasons)
        new = cur_index.get(key)
        if new is None:
            if not _finished_with_xg(old):
                diff.dropped_unplayed.append(_describe(key, old))
            elif season_dropped:
                if season is not None and season not in diff.dropped_seasons:
                    diff.dropped_seasons.append(season)
            else:
                diff.missing_finished.append(_describe(key, old))
            continue
        if _finished_with_xg(old) and not _finished_with_xg(new):
            diff.regressed.append(_describe(key, new))
            continue
        if _finished_with_xg(old) and _finished_with_xg(new):
            old_h, old_a = parse_xg(old.get("home_xg")), parse_xg(old.get("away_xg"))
            new_h, new_a = parse_xg(new.get("home_xg")), parse_xg(new.get("away_xg"))
            if (not math.isclose(old_h, new_h, rel_tol=0, abs_tol=1e-9)
                    or not math.isclose(old_a, new_a, rel_tol=0, abs_tol=1e-9)):
                # correzione legittima: Understat rivede gli xG di una partita
                diff.xg_corrections.append({
                    "match": _describe(key, new),
                    "before": [old_h, old_a],
                    "after": [new_h, new_a],
                })

    for key, new in cur_index.items():
        if key not in prev_index:
            diff.new_matches.append(_describe(key, new))

    diff.dropped_seasons.sort()
    if allow_dropping_seasons:
        # riduzione dichiarata delle stagioni: non blocca, ma resta nel report
        diff.dropped_seasons = []
    return diff


def season_averages(
    league: str,
    season: int,
    *,
    base_dir=None,
    cutoff=None,
    cutoff_policy: str = DEFAULT_CUTOFF_POLICY,
    day_timezone=ARCHIVE_TIMEZONE,
    records: Optional[Sequence[dict]] = None,
) -> SeasonAggregate:
    """Carica l'archivio della lega e ne deriva le medie della stagione."""
    data = list(records) if records is not None else load_archive(league, base_dir)
    return aggregate_season(
        data, season, league=league, cutoff=cutoff,
        cutoff_policy=cutoff_policy, day_timezone=day_timezone,
    )


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
