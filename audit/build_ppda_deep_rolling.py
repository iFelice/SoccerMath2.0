"""
build_ppda_deep_rolling.py - Archivio POINT-IN-TIME (rolling, no-leakage) di
PPDA e deep completions, costruito sull'archivio acquisito da
``update_all_ppda_player_db.py`` (``SoccerMath/database/ppda_deep_<lega>.json``).

Che cosa produce
----------------
Per OGNI partita di OGNI lega e per OGNI squadra in campo, la media mobile
delle ultime N partite di quella squadra con calcio d'inizio STRETTAMENTE
precedente al kickoff della partita in esame, su quattro misure:

    own_ppda    PPDA proprio       (pressione della squadra)
    own_deep    deep completions generati
    faced_ppda  PPDA subito        (PPDA dell'avversario in quelle partite)
    faced_deep  deep completions subiti

con N = 5 e N = 10 (entrambe riportate: la letteratura indica che il PPDA di
singola partita e' troppo rumoroso e serve una finestra di quest'ordine, ma la
scelta della finestra NON viene fatta a priori qui).

Regola anti-leakage (l'unica che conta)
---------------------------------------
Una partita entra nella finestra di una squadra solo se il suo kickoff e'
STRETTAMENTE precedente al kickoff della partita in esame. Due conseguenze
dichiarate:

  * le partite dello STESSO GIORNO sono escluse quando manca l'orario
    (``parse_kickoff`` restituisce ``has_time=False``): senza orario non si puo'
    stabilire l'ordine, quindi l'intero giorno resta fuori, come vuole la
    convenzione di ``xg_archive.parse_kickoff``. Sull'archivio Understat tutti i
    kickoff hanno l'orario, quindi il caso non si presenta: il codice lo tratta
    comunque e il report lo conta;
  * la partita stessa non entra mai nella propria finestra.

Il test di leakage (punto 6 della richiesta) e' ESEGUITO, non assunto:
``--leakage-sample N`` ricostruisce l'archivio due volte su un campione di
partite - (a) togliendo dal sorgente tutte le partite con data >= kickoff e
(b) INIETTANDO nel sorgente partite sintetiche estreme con data >= kickoff - e
verifica che i valori rolling della partita campione restino identici al bit.
Il massimo scarto misurato finisce nel riepilogo.

Finestre non piene (nessun riempimento silenzioso)
--------------------------------------------------
  * ``n < MIN_MATCHES`` partite precedenti        -> NaN su tutte e quattro le
    misure, ``status="insufficient"``: non si inventa un valore. E' il caso
    delle prime giornate della 2022/23, dove l'archivio PPDA/deep non ha
    alcuno storico precedente (parte dalla 2022/23).
  * ``MIN_MATCHES <= n < N``                     -> media sulle n partite
    disponibili, ``status="partial"`` con ``n`` dichiarato: e' una finestra
    corta, non una media di lega e non un'imputazione.
  * ``n >= N``                                   -> ``status="full"``.

Nessuna media di lega, nessun carry-forward, nessun riempimento: chi consuma
l'archivio vede ``n`` e ``status`` e decide. Il conteggio per status finisce nel
riepilogo.

La finestra NON si azzera a inizio stagione (una squadra puo' avere in finestra
partite della stagione precedente): per questo ogni riga riporta anche
``*_age_days``, l'eta' in giorni della partita piu' vecchia della finestra, cosi'
la staleness attraverso la pausa estiva e' visibile invece che nascosta.

PPDA non calcolabile (``null`` nel sorgente, caso strutturale di soccerdata con
denominatore difensivo nullo): il valore nullo NON entra nella media e la riga
riporta quanti valori sono stati usati (``*_n_ppda``). Una finestra senza alcun
PPDA valido da' NaN, non 0.

Nomi delle squadre: resolver condiviso della PR #15
(``team_names.resolve_team_name``). Un nome non riconosciuto viene contato e
riportato nel riepilogo, mai indovinato.

Nessun collegamento al motore: questo script non tocca ``app.py``, ``config.py``,
``models/``, soglie, pesi o ``PRIOR_MATCHES``.

Uso:
    python audit/build_ppda_deep_rolling.py
    python audit/build_ppda_deep_rolling.py --leakage-sample 25 --seed 20260916
    python audit/build_ppda_deep_rolling.py --output audit/data/ppda_deep_rolling.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from match_stats_archive import PPDA_FILES, parse_int  # noqa: E402
from team_names import resolve_team_name  # noqa: E402
from xg_archive import parse_kickoff, parse_season  # noqa: E402

# Finestre richieste: entrambe, nessuna scelta a priori.
WINDOWS: Tuple[int, ...] = (5, 10)

# Sotto questa soglia di partite precedenti non si inventa nulla: NaN.
MIN_MATCHES = 3

# Le quattro misure per lato. "own" = della squadra, "faced" = dell'avversario
# in quelle partite (cioe' quello che la squadra ha subito).
MEASURES: Tuple[str, ...] = ("own_ppda", "own_deep", "faced_ppda", "faced_deep")

# Colonne dell'archivio sorgente (schema di update_all_ppda_player_db.py).
REQUIRED_FIELDS = ("season", "id", "date", "home_team", "away_team")

# Campione per il test di leakage (per lega).
DEFAULT_LEAKAGE_SAMPLE = 25


def _num(value) -> Optional[float]:
    """Numero finito o None. ``None`` = valore non calcolabile (non 0)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def strictly_before(candidate: datetime, cand_has_time: bool,
                    target: datetime, target_has_time: bool) -> bool:
    """Ordine fra due kickoff con la regola conservativa sul giorno.

    Se entrambi hanno l'orario: confronto esatto. Se anche uno solo dei due ha
    soltanto il giorno, il giorno della partita candidata deve essere
    STRETTAMENTE precedente (l'intero giorno del target resta fuori), perche'
    senza orario l'ordine dentro il giorno non e' conoscibile.
    """
    if cand_has_time and target_has_time:
        return candidate < target
    return candidate.date() < target.date()


class Match:
    """Una partita dell'archivio PPDA/deep, normalizzata."""

    __slots__ = ("league", "season", "id", "kickoff", "has_time",
                 "home_raw", "away_raw", "home", "away",
                 "home_ppda", "away_ppda", "home_deep", "away_deep")

    def __init__(self, league, season, match_id, kickoff, has_time,
                 home_raw, away_raw, home, away,
                 home_ppda, away_ppda, home_deep, away_deep):
        self.league = league
        self.season = season
        self.id = match_id
        self.kickoff = kickoff
        self.has_time = has_time
        self.home_raw = home_raw
        self.away_raw = away_raw
        self.home = home
        self.away = away
        self.home_ppda = home_ppda
        self.away_ppda = away_ppda
        self.home_deep = home_deep
        self.away_deep = away_deep


def load_matches(league: str, db_dir: str,
                 problems: Optional[List[str]] = None) -> List[Match]:
    """Legge ``ppda_deep_<lega>.json`` e restituisce le partite ordinate.

    Una partita senza kickoff leggibile o senza chiave (stagione, id) NON entra
    nell'archivio: viene contata in ``problems``. Non viene ne' indovinata ne'
    messa a zero.
    """
    path = os.path.join(db_dir, PPDA_FILES[league])
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"archivio PPDA/deep assente: {path} (eseguire "
            f"update_all_ppda_player_db.py o il workflow update_ppda_player.yml)")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out: List[Match] = []
    seen = set()
    for rec in raw or []:
        if not isinstance(rec, dict):
            continue
        missing = [k for k in REQUIRED_FIELDS if k not in rec]
        if missing:
            if problems is not None:
                problems.append(f"{league}: record senza campi {missing}")
            continue
        kickoff, has_time = parse_kickoff(rec.get("date"))
        season = parse_season(rec.get("season"))
        match_id = parse_int(rec.get("id"))
        if kickoff is None or season is None or match_id is None:
            if problems is not None:
                problems.append(f"{league}: kickoff/stagione/id non leggibili "
                                f"in {rec.get('date')!r}/{rec.get('season')!r}/"
                                f"{rec.get('id')!r}")
            continue
        key = (season, match_id)
        if key in seen:
            if problems is not None:
                problems.append(f"{league}: partita duplicata {key}")
            continue
        seen.add(key)
        home_raw = str(rec.get("home_team") or "").strip()
        away_raw = str(rec.get("away_team") or "").strip()
        out.append(Match(
            league=league, season=season, match_id=match_id,
            kickoff=kickoff, has_time=has_time,
            home_raw=home_raw, away_raw=away_raw,
            home=resolve_team_name(home_raw).canonical,
            away=resolve_team_name(away_raw).canonical,
            home_ppda=_num(rec.get("home_ppda")),
            away_ppda=_num(rec.get("away_ppda")),
            home_deep=_num(rec.get("home_deep_completions")),
            away_deep=_num(rec.get("away_deep_completions")),
        ))
    out.sort(key=lambda m: (m.kickoff, m.season, m.id))
    return out


def team_timeline(matches: Sequence[Match],
                  unresolved: Optional[Dict[str, int]] = None
                  ) -> Dict[str, List[Tuple[Match, str]]]:
    """{squadra: [(partita, lato)]} in ordine cronologico.

    Il lato e' ``"home"`` o ``"away"``: serve a leggere dal record il PPDA e le
    deep completions della squadra (own) e dell'avversaria (faced).
    """
    timeline: Dict[str, List[Tuple[Match, str]]] = {}
    for match in matches:
        for team, side in ((match.home, "home"), (match.away, "away")):
            if not team:
                if unresolved is not None:
                    raw = match.home_raw if side == "home" else match.away_raw
                    unresolved[raw or "(vuoto)"] = unresolved.get(raw or "(vuoto)", 0) + 1
                continue
            timeline.setdefault(team, []).append((match, side))
    for team in timeline:
        timeline[team].sort(key=lambda item: (item[0].kickoff, item[0].season,
                                              item[0].id))
    return timeline


def _side_values(match: Match, side: str) -> Tuple[Optional[float], ...]:
    """(own_ppda, own_deep, faced_ppda, faced_deep) per la squadra su ``side``."""
    if side == "home":
        return (match.home_ppda, match.home_deep,
                match.away_ppda, match.away_deep)
    return (match.away_ppda, match.away_deep,
            match.home_ppda, match.home_deep)


def rolling_values(entries: Sequence[Tuple[Match, str]], index: int,
                   window: int) -> dict:
    """Media mobile sulle ultime ``window`` partite PRIMA di ``entries[index]``.

    Restituisce anche ``n`` (partite eleggibili disponibili), ``n_*`` (valori
    validi usati per ciascuna misura), ``status`` e ``age_days``.
    """
    target, target_has_time = entries[index][0].kickoff, entries[index][0].has_time
    # Taglio conservativo: tutto cio' che non e' strettamente precedente resta
    # fuori. Con gli orari presenti equivale a ``index``, ma la regola e' unica.
    cut = 0
    for j in range(index):
        # Le partite sono ordinate per kickoff: appena una non e' strettamente
        # precedente, non lo e' nemmeno nessuna delle successive.
        if strictly_before(entries[j][0].kickoff, entries[j][0].has_time,
                           target, target_has_time):
            cut = j + 1
        else:
            break
    chunk = entries[max(0, cut - window):cut]
    n = len(chunk)
    acc = {m: [] for m in MEASURES}
    for match, side in chunk:
        for measure, value in zip(MEASURES, _side_values(match, side)):
            if value is not None:
                acc[measure].append(value)
    out = {"n": n,
           "status": ("insufficient" if n < MIN_MATCHES
                      else "full" if n >= window else "partial"),
           "age_days": ((target - chunk[0][0].kickoff).total_seconds() / 86400.0
                        if chunk else None)}
    for measure in MEASURES:
        values = acc[measure]
        out[measure] = (sum(values) / len(values)) if values else None
        out[f"n_{measure}"] = len(values)
    if out["status"] == "insufficient":
        # Nessuna statistica inventata: sotto MIN_MATCHES l'archivio non
        # dichiara nulla, nemmeno una media su 1-2 partite.
        for measure in MEASURES:
            out[measure] = None
    return out


def build_league(league: str, matches: Sequence[Match],
                 windows: Sequence[int] = WINDOWS,
                 unresolved: Optional[Dict[str, int]] = None) -> List[dict]:
    """Una riga per partita, con le feature rolling di entrambe le squadre."""
    timeline = team_timeline(matches, unresolved=unresolved)
    positions: Dict[int, Dict[str, int]] = {}
    for team, entries in timeline.items():
        for index, (match, _side) in enumerate(entries):
            positions.setdefault(id(match), {})[team] = index
    rows: List[dict] = []
    for match in matches:
        row = {
            "league": league,
            "season": match.season,
            "id": match.id,
            "kickoff": match.kickoff.isoformat(),
            "has_time": int(bool(match.has_time)),
            "home_raw": match.home_raw,
            "away_raw": match.away_raw,
            "home": match.home,
            "away": match.away,
            "home_ppda": match.home_ppda,
            "away_ppda": match.away_ppda,
            "home_deep": match.home_deep,
            "away_deep": match.away_deep,
        }
        for team, side in ((match.home, "home"), (match.away, "away")):
            entries = timeline.get(team)
            index = positions.get(id(match), {}).get(team)
            if entries is None or index is None:
                for window in windows:
                    for measure in MEASURES:
                        row[f"{side}_r{window}_{measure}"] = None
                        row[f"{side}_r{window}_n_{measure}"] = None
                    row[f"{side}_r{window}_n"] = None
                    row[f"{side}_r{window}_status"] = "insufficient"
                    row[f"{side}_r{window}_age_days"] = None
                continue
            for window in windows:
                rolled = rolling_values(entries, index, window)
                for measure in MEASURES:
                    row[f"{side}_r{window}_{measure}"] = rolled[measure]
                    row[f"{side}_r{window}_n_{measure}"] = rolled[f"n_{measure}"]
                row[f"{side}_r{window}_n"] = rolled["n"]
                row[f"{side}_r{window}_status"] = rolled["status"]
                row[f"{side}_r{window}_age_days"] = rolled["age_days"]
        rows.append(row)
    return rows


def build_all(db_dir: str, leagues: Sequence[str],
              windows: Sequence[int] = WINDOWS,
              problems: Optional[List[str]] = None,
              unresolved: Optional[Dict[str, int]] = None,
              sources: Optional[Dict[str, List[Match]]] = None
              ) -> List[dict]:
    """Archivio rolling per tutte le leghe."""
    rows: List[dict] = []
    for league in leagues:
        matches = (sources or {}).get(league)
        if matches is None:
            matches = load_matches(league, db_dir, problems=problems)
        rows.extend(build_league(league, matches, windows=windows,
                                 unresolved=unresolved))
    return rows


# ---------------------------------------------------------------------------
# Test di leakage (punto 6): eseguito, non assunto
# ---------------------------------------------------------------------------
def _row_key(row: dict) -> Tuple:
    return (row["league"], row["season"], row["id"])


def _feature_columns(windows: Sequence[int]) -> List[str]:
    cols: List[str] = []
    for side in ("home", "away"):
        for window in windows:
            for measure in MEASURES:
                cols.append(f"{side}_r{window}_{measure}")
            cols.extend([f"{side}_r{window}_n",
                         f"{side}_r{window}_status",
                         f"{side}_r{window}_age_days"])
    return cols


def leakage_test(db_dir: str, leagues: Sequence[str], sample_per_league: int,
                 seed: int, windows: Sequence[int] = WINDOWS,
                 problems: Optional[List[str]] = None) -> dict:
    """Due varianti, entrambe devono lasciare la partita campione IDENTICA.

    (a) TRONCAMENTO: dal sorgente spariscono tutte le partite con kickoff >=
        quello della partita campione (resta la partita campione stessa, senza
        la quale non esiste la riga da confrontare);
    (b) INIEZIONE: al sorgente vengono AGGIUNTE partite sintetiche estreme
        (PPDA e deep completioni fuori scala) con kickoff >= quello della
        partita campione, incluse partite delle due squadre in campo.

    Se la finestra guardasse avanti, almeno una delle due varianti cambierebbe
    il valore della partita campione.
    """
    rng = random.Random(seed)
    columns = _feature_columns(windows)
    tested = 0
    max_abs_diff = 0.0
    differences: List[str] = []
    injected_total = 0
    per_league: Dict[str, dict] = {}

    for league in leagues:
        matches = load_matches(league, db_dir, problems=problems)
        full_rows = {_row_key(r): r
                     for r in build_league(league, matches, windows=windows)}
        # Campione deterministico: partite in cui entrambe le squadre hanno
        # gia' una finestra piena alla N maggiore (altrimenti il confronto
        # sarebbe fra due NaN e non proverebbe nulla).
        eligible = []
        for match in matches:
            base = full_rows[_row_key({"league": league, "season": match.season,
                                       "id": match.id})]
            if all(base[f"{side}_r{max(windows)}_status"] == "full"
                   for side in ("home", "away")):
                eligible.append(match)
        if not eligible:
            per_league[league] = {"tested": 0, "reason": "nessuna partita con finestra piena"}
            continue
        rng.shuffle(eligible)
        sample = eligible[:sample_per_league]
        league_tested = 0
        for match in sample:
            key = (league, match.season, match.id)
            base_row = full_rows[key]
            # --- (a) troncamento -------------------------------------------
            truncated = [m for m in matches
                         if strictly_before(m.kickoff, m.has_time,
                                            match.kickoff, match.has_time)]
            truncated.append(match)
            trunc_rows = {_row_key(r): r
                          for r in build_league(league, truncated, windows=windows)}
            # --- (b) iniezione di futuro estremo ---------------------------
            future_kickoff = match.kickoff + timedelta(hours=1)
            injected = list(matches)
            n_injected = 0
            for offset in range(6):
                kickoff = future_kickoff + timedelta(days=7 * (offset + 1))
                injected.append(Match(
                    league=league, season=match.season,
                    match_id=9_000_000 + offset * 3,
                    kickoff=kickoff, has_time=True,
                    home_raw=match.home_raw, away_raw=match.away_raw,
                    home=match.home, away=match.away,
                    home_ppda=999.0, away_ppda=0.001,
                    home_deep=999.0, away_deep=999.0))
                injected.append(Match(
                    league=league, season=match.season,
                    match_id=9_000_001 + offset * 3,
                    kickoff=kickoff + timedelta(hours=2), has_time=True,
                    home_raw=match.away_raw, away_raw=match.home_raw,
                    home=match.away, away=match.home,
                    home_ppda=0.001, away_ppda=999.0,
                    home_deep=999.0, away_deep=999.0))
                injected.append(Match(
                    league=league, season=match.season,
                    match_id=9_000_002 + offset * 3,
                    kickoff=kickoff + timedelta(hours=4), has_time=True,
                    home_raw=match.home_raw, away_raw=match.away_raw,
                    home=match.home, away=match.away,
                    home_ppda=999.0, away_ppda=999.0,
                    home_deep=999.0, away_deep=999.0))
                n_injected += 3
            injected_total += n_injected
            inj_rows = {_row_key(r): r
                        for r in build_league(league, injected, windows=windows)}
            # --- confronto -------------------------------------------------
            for variant, other in (("troncato", trunc_rows), ("iniettato", inj_rows)):
                row = other.get(key)
                if row is None:
                    differences.append(f"{league} {key}: riga assente nella variante {variant}")
                    continue
                for column in columns:
                    a, b = base_row[column], row[column]
                    if isinstance(a, float) and isinstance(b, float):
                        diff = abs(a - b)
                        max_abs_diff = max(max_abs_diff, diff)
                        if diff > 0:
                            differences.append(
                                f"{league} {key} {column} {variant}: "
                                f"{a!r} -> {b!r}")
                    elif a != b:
                        differences.append(
                            f"{league} {key} {column} {variant}: {a!r} -> {b!r}")
            league_tested += 1
            tested += 1
        per_league[league] = {"tested": league_tested,
                              "eligible": len(eligible),
                              "matches": len(matches)}
    return {
        "windows": list(windows),
        "seed": seed,
        "sample_per_league": sample_per_league,
        "matches_tested": tested,
        "injected_future_matches": injected_total,
        "max_abs_difference": max_abs_diff,
        "differences": differences[:20],
        "difference_count": len(differences),
        "per_league": per_league,
    }


# ---------------------------------------------------------------------------
# Riepilogo
# ---------------------------------------------------------------------------
def summarize(rows: Sequence[dict], windows: Sequence[int] = WINDOWS) -> dict:
    """Copertura e stato delle finestre, per lega e in totale."""
    per_league: Dict[str, dict] = {}
    for row in rows:
        entry = per_league.setdefault(row["league"], {
            "matches": 0, "first_kickoff": None, "last_kickoff": None,
            "no_time_kickoffs": 0, "unresolved_names": 0,
            "windows": {}})
        entry["matches"] += 1
        kickoff = row["kickoff"]
        if entry["first_kickoff"] is None or kickoff < entry["first_kickoff"]:
            entry["first_kickoff"] = kickoff
        if entry["last_kickoff"] is None or kickoff > entry["last_kickoff"]:
            entry["last_kickoff"] = kickoff
        if not row["has_time"]:
            entry["no_time_kickoffs"] += 1
        if not row["home"] or not row["away"]:
            entry["unresolved_names"] += 1
        for side in ("home", "away"):
            for window in windows:
                block = entry["windows"].setdefault(
                    f"{side}_r{window}",
                    {"full": 0, "partial": 0, "insufficient": 0,
                     "n_min": None, "n_max": None, "age_days_max": None,
                     "ppda_nan_full_windows": 0})
                status = row[f"{side}_r{window}_status"]
                block[status] += 1
                n = row[f"{side}_r{window}_n"]
                if n is not None:
                    block["n_min"] = n if block["n_min"] is None else min(block["n_min"], n)
                    block["n_max"] = n if block["n_max"] is None else max(block["n_max"], n)
                age = row[f"{side}_r{window}_age_days"]
                if age is not None:
                    block["age_days_max"] = (age if block["age_days_max"] is None
                                             else max(block["age_days_max"], age))
                if (status == "full"
                        and row[f"{side}_r{window}_n_own_ppda"] == 0):
                    block["ppda_nan_full_windows"] += 1
    totals = {"matches": sum(e["matches"] for e in per_league.values()),
              "no_time_kickoffs": sum(e["no_time_kickoffs"] for e in per_league.values()),
              "unresolved_names": sum(e["unresolved_names"] for e in per_league.values())}
    return {"per_league": per_league, "totals": totals,
            "windows": list(windows), "min_matches": MIN_MATCHES}


def write_csv(rows: Sequence[dict], path: str,
              windows: Sequence[int] = WINDOWS) -> int:
    if not rows:
        raise ValueError("nessuna riga da scrivere")
    base = ["league", "season", "id", "kickoff", "has_time",
            "home_raw", "away_raw", "home", "away",
            "home_ppda", "away_ppda", "home_deep", "away_deep"]
    columns = base + _feature_columns(windows)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out = {}
            for column in columns:
                value = row.get(column)
                out[column] = "" if value is None else value
            writer.writerow(out)
    return len(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Archivio point-in-time rolling di PPDA e deep completions")
    parser.add_argument("--database-dir",
                        default=os.path.join(_REPO_ROOT, "SoccerMath", "database"))
    parser.add_argument("--league", action="append", dest="leagues",
                        choices=list(PPDA_FILES), help="limita a una lega (ripetibile)")
    parser.add_argument("--windows", nargs="+", type=int, default=list(WINDOWS))
    parser.add_argument("--output",
                        default=os.path.join(_AUDIT_DIR, "data",
                                             "ppda_deep_rolling.csv"))
    parser.add_argument("--summary",
                        default=os.path.join(_AUDIT_DIR, "data",
                                             "ppda_deep_rolling_summary.json"))
    parser.add_argument("--leakage-sample", type=int, default=DEFAULT_LEAKAGE_SAMPLE,
                        help="partite per lega nel test di leakage (0 = salta)")
    parser.add_argument("--seed", type=int, default=20260916)
    parser.add_argument("--no-write", action="store_true",
                        help="calcola e riporta senza scrivere CSV/JSON")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    leagues = args.leagues or list(PPDA_FILES)
    windows = tuple(args.windows)
    problems: List[str] = []
    unresolved: Dict[str, int] = {}

    rows = build_all(args.database_dir, leagues, windows=windows,
                     problems=problems, unresolved=unresolved)
    summary = summarize(rows, windows=windows)
    summary["problems"] = problems
    summary["unresolved_names"] = dict(sorted(unresolved.items()))
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    summary["source_dir"] = args.database_dir

    if args.leakage_sample:
        summary["leakage_test"] = leakage_test(
            args.database_dir, leagues, args.leakage_sample, args.seed,
            windows=windows, problems=problems)

    if not args.no_write:
        written = write_csv(rows, args.output, windows=windows)
        summary["output_csv"] = args.output
        summary["rows_written"] = written
        os.makedirs(os.path.dirname(args.summary) or ".", exist_ok=True)
        with open(args.summary, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
            f.write("\n")

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    test = summary.get("leakage_test")
    if test:
        if test["difference_count"] or test["max_abs_difference"] > 0:
            print(f"\nLEAKAGE: {test['difference_count']} differenze, "
                  f"scarto massimo {test['max_abs_difference']}", file=sys.stderr)
            return 1
        print(f"\nLEAKAGE OK: {test['matches_tested']} partite campionate, "
              f"{test['injected_future_matches']} partite future iniettate, "
              f"scarto massimo {test['max_abs_difference']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
