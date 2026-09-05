"""Replay storico A vs B del selettore Top Mix (sola lettura).

Esegue il §4.1 di ``audit/topmix_selector_audit_protocol.md``:
confronto fra il selettore di produzione (A: argmax Poisson, poi Elo solo sul
mercato gia' scelto, poi filtri sull'intera partita) e il selettore alternativo
gia' implementato in ``audit/reconstruct_topmix_match.py`` (B: confidence
finale per tutti e sette i mercati, filtri per mercato, poi massimo ammissibile).

Vincoli rispettati (nessuna deroga):
  * NON si modificano formule, soglie (0.55 / 0.60 / 0.25), pesi (0.6/0.4),
    dedup o JSONBin: le soglie sono importate da
    ``audit.reconstruct_topmix_match`` che a sua volta le trascrive da
    ``fetch_and_calc_top_mix`` (un test AST del repo verifica la coincidenza);
  * NON si scrive sul registro, NON si chiama JSONBin, NON si chiama
    ``fetch_and_calc_top_mix`` / ``analisi_rapida_giornata`` / ``save_*``;
  * il motore e' quello di produzione: ``get_league_engine``,
    ``get_full_poisson_two_heads``, ``predict_elo_probs``,
    ``select_next_matchday_matches`` (con ``now`` esplicito);
  * i dati sono point-in-time: CSV troncati al cutoff e medie xG ricostruite
    con ``xg_archive.season_averages(..., cutoff=..., cutoff_policy=
    "previous_day")``. Il database di produzione non viene toccato: si scrive
    solo in una directory temporanea a cui i moduli vengono reindirizzati
    (helper gia' esistenti in ``reconstruct_topmix_match``).

Stagioni: 2024/25 e 2025/26. Sono **validation storica gia' esaminata**
(due teste, forma sui totali, shrinkage, ensemble Elo sono stati scelti su
queste stesse stagioni): NON sono un test intatto. L'etichetta e' riportata
in ogni output.

Uso::

    python audit/topmix_selector_replay.py --out audit/results

Nessun ``--apply``, nessuna scrittura fuori da ``--out`` e dalla tmpdir.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
if _AUDIT_DIR not in sys.path:
    sys.path.insert(0, _AUDIT_DIR)

# reconstruct_topmix_match mette SoccerMath in sys.path e importa le funzioni
# di produzione. Riusarlo evita una seconda copia dei numeri di produzione.
import reconstruct_topmix_match as R  # noqa: E402

import pandas as pd  # noqa: E402

from config import (  # noqa: E402
    DATABASE_DIR as ORIGINAL_DATABASE_DIR,
    LEAGUES_CONFIG,
    clean_name,
    get_league_config,
)
import xg_archive  # noqa: E402

# --- funzioni/costanti di produzione (nessuna ridefinizione) ---------------
get_league_engine = R.get_league_engine
get_full_poisson_two_heads = R.get_full_poisson_two_heads
predict_elo_probs = R.predict_elo_probs
select_next_matchday_matches = R.select_next_matchday_matches
apply_selector_A = R.apply_selector_A
apply_selector_B = R.apply_selector_B
seven_markets = R.seven_markets
TOP_MIX_ROUND_WINDOW_DAYS = R.TOP_MIX_ROUND_WINDOW_DAYS
TOP_N = R.TOP_N

LEAGUES: Tuple[str, ...] = (
    "Serie A", "Premier League", "La Liga", "Bundesliga", "Ligue 1",
)
# anno di inizio stagione -> etichetta
SEASONS: Tuple[int, ...] = (2024, 2025)
SEASON_LABEL = {2024: "2024/25", 2025: "2025/26"}

SEASON_STATUS = (
    "validation storica GIA' ESAMINATA (2024/25 e 2025/26 sono state usate per "
    "scegliere due teste, forma fuori dai totali, shrinkage PRIOR_MATCHES=6 e "
    "per confermare i pesi 0.6/0.4): NON e' un test intatto."
)

MARKET_CODE_FIXED = {
    "Pareggio": "X",
    "Over 2.5": "O2.5",
    "Under 2.5": "U2.5",
    "GG": "GG",
    "NG": "NG",
}


# ---------------------------------------------------------------------------
# 1. Fixture storiche dai CSV di produzione (stessa fonte del motore)
# ---------------------------------------------------------------------------
def _kickoff_series(df: pd.DataFrame) -> pd.Series:
    """Kickoff UTC dichiarato: Date (dayfirst) + Time se presente.

    ASSUNZIONE dichiarata: gli orari dei CSV football-data.co.uk sono trattati
    come UTC. Non e' il fuso reale di ogni campionato: sposta il cutoff di
    1-2 ore, mai di un giorno intero, e vale identico per A e per B.
    """
    dates = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    if "Time" in df.columns:
        times = df["Time"].fillna("").astype(str).str.strip()
        combo = dates.dt.strftime("%Y-%m-%d") + " " + times.where(times != "", "00:00")
        parsed = pd.to_datetime(combo, errors="coerce")
        dates = parsed.fillna(dates)
    return dates.dt.tz_localize(timezone.utc)


def load_league_frames(league: str) -> Dict[str, pd.DataFrame]:
    """CSV della lega letti UNA volta come stringhe (riscrittura fedele)."""
    info = get_league_config(league)
    prefix = info.get("db_prefix")
    frames: Dict[str, pd.DataFrame] = {}
    base = str(ORIGINAL_DATABASE_DIR)
    for fname in sorted(os.listdir(base)):
        if not fname.endswith(".csv"):
            continue
        if not (fname.startswith(f"{prefix}_") or fname == f"{prefix}.csv"
                or fname == os.path.basename(str(info.get("base_csv") or ""))):
            continue
        path = os.path.join(base, fname)
        try:
            df = pd.read_csv(path, dtype=str, keep_default_na=False,
                             on_bad_lines="warn", low_memory=False)
        except Exception:
            continue
        if df.empty or "Date" not in df.columns:
            continue
        df = df.copy()
        df["_kick"] = _kickoff_series(df)
        df = df[df["_kick"].notna()]
        frames[fname] = df
    return frames


def derive_matchdays(kicks: Sequence[datetime], homes: Sequence[str],
                     aways: Sequence[str]) -> List[int]:
    """Giornata approssimata: partita n-esima di ciascuna squadra.

    I CSV football-data.co.uk NON hanno il campo ``matchday`` dell'API
    football-data.org. Si ricostruisce in ordine cronologico con
    ``md = max(partite gia' giocate da casa, da trasferta) + 1``: coincide con
    la giornata reale a calendario regolare e degrada in modo prevedibile sui
    recuperi (una partita rinviata prende la giornata in cui viene giocata).
    APPROSSIMAZIONE DICHIARATA (protocollo §6): identica per A e per B.
    """
    played: Dict[str, int] = defaultdict(int)
    order = sorted(range(len(kicks)), key=lambda i: (kicks[i], homes[i], aways[i]))
    out = [0] * len(kicks)
    for i in order:
        h, a = homes[i], aways[i]
        md = max(played[h], played[a]) + 1
        out[i] = md
        played[h] += 1
        played[a] += 1
    return out


def season_fixtures(league: str, season: int,
                    frames: Dict[str, pd.DataFrame]) -> List[Dict[str, Any]]:
    """Partite della stagione in formato API-like per select_next_matchday_matches."""
    info = get_league_config(league)
    prefix = info.get("db_prefix")
    fname = f"{prefix}_{season}.csv"
    df = frames.get(fname)
    if df is None or df.empty:
        return []
    need = {"HomeTeam", "AwayTeam", "FTHG", "FTAG"}
    if not need.issubset(df.columns):
        return []
    df = df[(df["HomeTeam"].astype(str).str.strip() != "")
            & (df["AwayTeam"].astype(str).str.strip() != "")].copy()
    df = df.sort_values("_kick", kind="stable").reset_index(drop=True)
    kicks = list(df["_kick"])
    homes = [str(x).strip() for x in df["HomeTeam"]]
    aways = [str(x).strip() for x in df["AwayTeam"]]
    mds = derive_matchdays(kicks, homes, aways)
    fixtures: List[Dict[str, Any]] = []
    for i in range(len(df)):
        try:
            fthg = int(float(df["FTHG"].iloc[i]))
            ftag = int(float(df["FTAG"].iloc[i]))
        except (TypeError, ValueError):
            continue  # partita senza risultato: non valutabile
        fixtures.append({
            "id": f"{prefix}|{season}|{i}",
            "matchday": int(mds[i]),
            "utcDate": kicks[i].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "homeTeam": {"shortName": homes[i]},
            "awayTeam": {"shortName": aways[i]},
            "_kick": kicks[i],
            "_fthg": fthg,
            "_ftag": ftag,
        })
    return fixtures


def replay_units(fixtures: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Giornate ricostruite chiamando la funzione di produzione con ``now`` esplicito.

    Si simula un'apertura del Top Mix un istante prima del primo calcio d'inizio
    della giornata: ``now = primo kickoff - 1s``. La selezione dei candidati e'
    ``select_next_matchday_matches`` di produzione, non una regola nuova.
    """
    if not fixtures:
        return []
    by_id = {m["id"]: m for m in fixtures}
    api_matches = [{k: v for k, v in m.items() if not k.startswith("_")} for m in fixtures]
    first = min(m["_kick"] for m in fixtures)
    now = first - timedelta(seconds=1)
    units: List[Dict[str, Any]] = []
    guard = 0
    while guard < 200:
        guard += 1
        sel = select_next_matchday_matches(api_matches, now=now)
        if not sel:
            break
        rows = [by_id[m["id"]] for m in sel]
        cutoff = min(r["_kick"] for r in rows)
        last = max(r["_kick"] for r in rows)
        md = sel[0]["matchday"]
        # partite della stessa giornata escluse dalla finestra di round
        in_round = [m for m in fixtures if m["matchday"] == md and m["_kick"] > now]
        units.append({
            "matchday": md,
            "cutoff": cutoff,
            "matches": rows,
            "n_round_total_future": len(in_round),
            "n_excluded_window": len(in_round) - len(rows),
        })
        now = last + timedelta(seconds=1)
    return units


# ---------------------------------------------------------------------------
# 2. Database point-in-time (nessuna scrittura nel database di produzione)
# ---------------------------------------------------------------------------
class PointInTimeDB:
    """Directory temporanea con CSV troncati al cutoff e medie xG al cutoff."""

    def __init__(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="sm_selector_replay_")
        self.db = os.path.join(self.tmp, "database")
        os.makedirs(self.db, exist_ok=True)
        self._snap = R._snapshot_db_paths()
        R._redirect_database_dir(self.db)
        R.clear_production_caches()

    def close(self) -> None:
        R._restore_db_paths(self._snap)
        R.clear_production_caches()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def materialize(self, league: str, season: int, cutoff: datetime,
                    frames: Dict[str, pd.DataFrame],
                    archive: Sequence[dict]) -> Dict[str, Any]:
        """Scrive lo stato dei dati conosciuto all'istante ``cutoff``."""
        for fname in os.listdir(self.db):
            os.remove(os.path.join(self.db, fname))
        rows_written = 0
        files_written = 0
        for fname, df in frames.items():
            sub = df[df["_kick"] < cutoff]
            if sub.empty:
                continue
            out = sub.drop(columns=["_kick"])
            out.to_csv(os.path.join(self.db, fname), index=False)
            rows_written += len(out)
            files_written += 1
        agg = xg_archive.season_averages(
            league, season, records=archive, cutoff=cutoff,
            cutoff_policy="previous_day",
        )
        xg_path = os.path.join(self.db, os.path.basename(
            LEAGUES_CONFIG[league]["xg_json"]))
        xg_archive.write_averages(agg, xg_path)
        R.clear_production_caches()
        return {
            "csv_files": files_written,
            "csv_rows": rows_written,
            "xg_matches_used": agg.matches_used,
            "xg_teams": len(agg.averages),
        }


# ---------------------------------------------------------------------------
# 3. Esiti dei sette mercati
# ---------------------------------------------------------------------------
def market_code(market: str, home: str, away: str) -> str:
    if market in MARKET_CODE_FIXED:
        return MARKET_CODE_FIXED[market]
    if market == f"Vittoria {home}":
        return "1"
    if market == f"Vittoria {away}":
        return "2"
    return market


def market_outcome(code: str, fthg: int, ftag: int) -> int:
    tot = fthg + ftag
    if code == "1":
        return int(fthg > ftag)
    if code == "X":
        return int(fthg == ftag)
    if code == "2":
        return int(ftag > fthg)
    if code == "O2.5":
        return int(tot > 2.5)
    if code == "U2.5":
        return int(tot < 2.5)
    if code == "GG":
        return int(fthg > 0 and ftag > 0)
    if code == "NG":
        return int(not (fthg > 0 and ftag > 0))
    raise ValueError(f"mercato sconosciuto: {code!r}")


# ---------------------------------------------------------------------------
# 4. Replay
# ---------------------------------------------------------------------------
def replay(leagues: Sequence[str] = LEAGUES,
           seasons: Sequence[int] = SEASONS,
           progress: bool = True) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    units_meta: List[Dict[str, Any]] = []
    coverage_meta: List[Dict[str, Any]] = []
    pit = PointInTimeDB()
    try:
        for league in leagues:
            frames = load_league_frames(league)
            archive = xg_archive.load_archive(
                league, base_dir=str(ORIGINAL_DATABASE_DIR))
            for season in seasons:
                fixtures = season_fixtures(league, season, frames)
                units = replay_units(fixtures)
                candidate_ids = {m["id"] for u in units for m in u["matches"]}
                never = [m for m in fixtures if m["id"] not in candidate_ids]
                coverage_meta.append({
                    "league": league, "season": season,
                    "n_fixtures": len(fixtures),
                    "n_replay_matchdays": len(units),
                    "n_candidates": len(candidate_ids),
                    "n_never_candidate": len(never),
                    "never_candidate_examples": [
                        f"{m['homeTeam']['shortName']}-{m['awayTeam']['shortName']} "
                        f"{m['utcDate']} (md {m['matchday']})" for m in never[:5]
                    ],
                })
                if progress:
                    print(f"  {league} {SEASON_LABEL[season]}: "
                          f"{len(fixtures)} partite, {len(units)} giornate replay, "
                          f"{len(never)} mai candidate", flush=True)
                for unit in units:
                    data_meta = pit.materialize(league, season, unit["cutoff"],
                                                frames, archive)
                    engine = get_league_engine(league)
                    if not engine:
                        units_meta.append({
                            "league": league, "season": season,
                            "matchday": unit["matchday"],
                            "cutoff": unit["cutoff"].isoformat(),
                            "n_candidates": 0, "engine": False, **data_meta,
                        })
                        continue
                    team_stats, avg_h, avg_a, _df = engine
                    for m in unit["matches"]:
                        rows.append(_score_match(
                            league, season, unit, m, team_stats, avg_h, avg_a))
                    units_meta.append({
                        "league": league, "season": season,
                        "matchday": unit["matchday"],
                        "cutoff": unit["cutoff"].isoformat(),
                        "n_candidates": len(unit["matches"]),
                        "n_excluded_window": unit["n_excluded_window"],
                        "engine": True, **data_meta,
                    })
    finally:
        pit.close()
    return {"rows": rows, "units": units_meta, "fixture_coverage": coverage_meta}


def _score_match(league: str, season: int, unit: Dict[str, Any],
                 m: Dict[str, Any], team_stats: Dict[str, Any],
                 avg_h: float, avg_a: float) -> Dict[str, Any]:
    h = m["homeTeam"]["shortName"]
    a = m["awayTeam"]["shortName"]
    h_s = team_stats.get(clean_name(h), {"att": 1.0, "def": 1.0})
    a_s = team_stats.get(clean_name(a), {"att": 1.0, "def": 1.0})
    m_poisson = get_full_poisson_two_heads(h_s, a_s, avg_h, avg_a)
    mercati = seven_markets(h, a, m_poisson)
    elo_p = None
    try:
        elo_p = predict_elo_probs(h, a, league)
    except Exception:
        elo_p = None
    sel_a = apply_selector_A(mercati, h, a, elo_p)
    sel_b = apply_selector_B(mercati, h, a, elo_p)

    fthg, ftag = m["_fthg"], m["_ftag"]
    a_code = market_code(sel_a["best_market"], h, a)
    a_hit = market_outcome(a_code, fthg, ftag)
    if sel_b["best_market"] is not None:
        b_code = market_code(sel_b["best_market"], h, a)
        b_hit = market_outcome(b_code, fthg, ftag)
        b_conf = float(sel_b["confidence"])
    else:
        b_code, b_hit, b_conf = None, None, None

    per_market = {}
    for r_ in sel_b["all_markets"]:
        code = market_code(r_["market"], h, a)
        per_market[code] = {
            "poisson": round(float(r_["poisson_prob"]), 6),
            "conf": round(float(r_["confidence"]), 6),
            "admitted": bool(r_["admitted"]),
            "hit": market_outcome(code, fthg, ftag),
        }

    return {
        "league": league,
        "season": season,
        "season_label": SEASON_LABEL[season],
        "matchday": unit["matchday"],
        "cutoff": unit["cutoff"].isoformat(),
        "match_id": m["id"],
        "home": h,
        "away": a,
        "kickoff": m["utcDate"],
        "fthg": fthg,
        "ftag": ftag,
        "team_stats_missing": int(clean_name(h) not in team_stats)
                              + int(clean_name(a) not in team_stats),
        "elo_available": elo_p is not None,
        "A_market": a_code,
        "A_poisson": round(float(sel_a["poisson_prob"]), 6),
        "A_conf": round(float(sel_a["confidence"]), 6),
        "A_disagree": round(float(sel_a["disagree"]), 6),
        "A_min_conf": sel_a["min_conf"],
        "A_admitted": bool(sel_a["admitted"]),
        "A_hit": a_hit,
        "B_market": b_code,
        "B_conf": None if b_conf is None else round(b_conf, 6),
        "B_admitted": bool(sel_b["admitted"]),
        "B_n_admitted_markets": int(sel_b["n_admitted"]),
        "B_hit": b_hit,
        "per_market": per_market,
    }


# ---------------------------------------------------------------------------
# 5. Metriche
# ---------------------------------------------------------------------------
def _brier(pairs: Sequence[Tuple[float, int]]) -> Optional[float]:
    if not pairs:
        return None
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def _mean(values: Sequence[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _stats_block(pairs: Sequence[Tuple[float, int]]) -> Dict[str, Any]:
    n = len(pairs)
    if n == 0:
        return {"n": 0, "mean_prob": None, "hit_rate": None, "brier": None,
                "gap": None}
    mp = sum(p for p, _ in pairs) / n
    hr = sum(y for _, y in pairs) / n
    return {"n": n, "mean_prob": mp, "hit_rate": hr,
            "brier": _brier(pairs), "gap": mp - hr}


def dedup_rows(rows: Sequence[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """Una sola osservazione per (match_id, selettore): §5.5 del protocollo."""
    seen = set()
    out = []
    dups = 0
    for r in rows:
        key = (r["league"], r["season"], r["match_id"])
        if key in seen:
            dups += 1
            continue
        seen.add(key)
        out.append(r)
    return out, dups


def block_bootstrap_delta(rows: Sequence[Dict[str, Any]],
                          metric: str,
                          n_boot: int = 2000,
                          seed: int = 20260905) -> Dict[str, Any]:
    """Bootstrap a blocchi (blocco = giornata) del delta A-B, coppie appaiate."""
    blocks: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        blocks[(r["league"], r["season"], r["matchday"])].append(r)
    keys = list(blocks)
    if not keys:
        return {"n_blocks": 0, "point": None, "ci95": [None, None]}

    def _delta(sample_rows: Sequence[Dict[str, Any]]) -> Optional[float]:
        pa = [(r["A_conf"], r["A_hit"]) for r in sample_rows]
        pb = [(r["B_conf"], r["B_hit"]) for r in sample_rows]
        if not pa:
            return None
        if metric == "brier":
            return _brier(pa) - _brier(pb)
        if metric == "hit_rate":
            return (sum(y for _, y in pa) / len(pa)) - (sum(y for _, y in pb) / len(pb))
        raise ValueError(metric)

    point = _delta(list(rows))
    rng = random.Random(seed)
    draws = []
    for _ in range(n_boot):
        sample: List[Dict[str, Any]] = []
        for _ in range(len(keys)):
            sample.extend(blocks[keys[rng.randrange(len(keys))]])
        d = _delta(sample)
        if d is not None:
            draws.append(d)
    draws.sort()
    if not draws:
        return {"n_blocks": len(keys), "point": point, "ci95": [None, None]}
    lo = draws[int(0.025 * (len(draws) - 1))]
    hi = draws[int(0.975 * (len(draws) - 1))]
    return {"n_blocks": len(keys), "point": point, "ci95": [lo, hi],
            "n_boot": len(draws)}


def compute_metrics(rows: Sequence[Dict[str, Any]],
                    units: Sequence[Dict[str, Any]],
                    fixture_coverage: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    rows, n_dups = dedup_rows(rows)

    def subset_metrics(sub: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        n = len(sub)
        both = [r for r in sub if r["A_admitted"] and r["B_admitted"]]
        a_only = [r for r in sub if r["A_admitted"] and not r["B_admitted"]]
        b_only = [r for r in sub if r["B_admitted"] and not r["A_admitted"]]
        neither = [r for r in sub if not r["A_admitted"] and not r["B_admitted"]]
        diff_both = [r for r in both if r["A_market"] != r["B_market"]]
        diff_raw = [r for r in sub
                    if r["B_market"] is not None and r["A_market"] != r["B_market"]]
        # (3) partite scartate da A ma accettate da B: il caso dell'esempio
        rescued_reason = Counter()
        rescued_market = Counter()
        for r in b_only:
            below = r["A_conf"] < r["A_min_conf"]
            disag = r["A_disagree"] >= R.ELO_DISAGREE_MAX
            if below and disag:
                rescued_reason["A: confidence sotto soglia + disaccordo Elo"] += 1
            elif below:
                rescued_reason["A: confidence sotto soglia"] += 1
            elif disag:
                rescued_reason["A: disaccordo Elo >= 0.25"] += 1
            rescued_market[r["B_market"]] += 1
        return {
            "n_candidates": n,
            "n_A_admitted": sum(1 for r in sub if r["A_admitted"]),
            "n_B_admitted": sum(1 for r in sub if r["B_admitted"]),
            "n_both": len(both),
            "n_A_only": len(a_only),
            "n_B_only": len(b_only),
            "n_neither": len(neither),
            "coverage_A": (sum(1 for r in sub if r["A_admitted"]) / n) if n else None,
            "coverage_B": (sum(1 for r in sub if r["B_admitted"]) / n) if n else None,
            "disagreement": {
                "n_both_admitted": len(both),
                "n_diff_market_both_admitted": len(diff_both),
                "freq_diff_given_both": (len(diff_both) / len(both)) if both else None,
                "n_diff_market_any_B": len(diff_raw),
                "freq_diff_over_candidates": (len(diff_raw) / n) if n else None,
            },
            "on_disagreement": {
                "A": _stats_block([(r["A_conf"], r["A_hit"]) for r in diff_both]),
                "B": _stats_block([(r["B_conf"], r["B_hit"]) for r in diff_both]),
            },
            "on_all_shown": {
                "A": _stats_block([(r["A_conf"], r["A_hit"])
                                   for r in sub if r["A_admitted"]]),
                "B": _stats_block([(r["B_conf"], r["B_hit"])
                                   for r in sub if r["B_admitted"]]),
            },
            "on_both_admitted": {
                "A": _stats_block([(r["A_conf"], r["A_hit"]) for r in both]),
                "B": _stats_block([(r["B_conf"], r["B_hit"]) for r in both]),
            },
            "rescued_by_B": {
                "n": len(b_only),
                "reasons": dict(rescued_reason),
                "markets": dict(rescued_market),
                "stats_B": _stats_block([(r["B_conf"], r["B_hit"]) for r in b_only]),
                "stats_A_would_have_been": _stats_block(
                    [(r["A_conf"], r["A_hit"]) for r in b_only]),
            },
            "lost_by_B": {
                "n": len(a_only),
                "note": ("Per costruzione dev'essere 0: il mercato scelto da A e' "
                         "valutato da B con la stessa formula, quindi se passa i "
                         "filtri per A passa anche per B."),
            },
            "market_mix_A": dict(Counter(r["A_market"] for r in sub if r["A_admitted"])),
            "market_mix_B": dict(Counter(r["B_market"] for r in sub if r["B_admitted"])),
            "market_mix_A_prefilter": dict(Counter(r["A_market"] for r in sub)),
        }

    out: Dict[str, Any] = {
        "n_rows_raw": len(rows) + n_dups,
        "n_duplicate_rows_dropped": n_dups,
        "aggregate": subset_metrics(rows),
        "by_league": {},
        "by_season": {},
        "by_league_season": {},
    }
    for lg in sorted({r["league"] for r in rows}):
        out["by_league"][lg] = subset_metrics([r for r in rows if r["league"] == lg])
    for se in sorted({r["season"] for r in rows}):
        out["by_season"][SEASON_LABEL.get(se, str(se))] = subset_metrics(
            [r for r in rows if r["season"] == se])
    for lg in sorted({r["league"] for r in rows}):
        for se in sorted({r["season"] for r in rows}):
            key = f"{lg} | {SEASON_LABEL.get(se, se)}"
            out["by_league_season"][key] = subset_metrics(
                [r for r in rows if r["league"] == lg and r["season"] == se])

    # --- incertezza: bootstrap a blocchi (giornata) sul sottoinsieme di disaccordo
    diff_rows = [r for r in rows
                 if r["A_admitted"] and r["B_admitted"]
                 and r["A_market"] != r["B_market"]]
    both_rows = [r for r in rows if r["A_admitted"] and r["B_admitted"]]
    out["uncertainty"] = {
        "disagreement_subset": {
            "brier_delta_A_minus_B": block_bootstrap_delta(diff_rows, "brier"),
            "hit_rate_delta_A_minus_B": block_bootstrap_delta(diff_rows, "hit_rate"),
        },
        "both_admitted": {
            "brier_delta_A_minus_B": block_bootstrap_delta(both_rows, "brier"),
            "hit_rate_delta_A_minus_B": block_bootstrap_delta(both_rows, "hit_rate"),
        },
        "note": ("Blocchi = giornata (league, season, matchday); coppie appaiate "
                 "sulla stessa partita. Nessun bootstrap i.i.d. delle righe."),
    }

    # --- copertura per giornata
    per_unit: Dict[Tuple[Any, ...], Dict[str, int]] = defaultdict(
        lambda: {"cand": 0, "A": 0, "B": 0})
    for r in rows:
        k = (r["league"], r["season"], r["matchday"])
        per_unit[k]["cand"] += 1
        per_unit[k]["A"] += int(r["A_admitted"])
        per_unit[k]["B"] += int(r["B_admitted"])
    cov_by_league: Dict[str, Dict[str, Any]] = {}
    for lg in sorted({k[0] for k in per_unit}):
        vals = [v for k, v in per_unit.items() if k[0] == lg]
        cov_by_league[lg] = {
            "n_matchdays": len(vals),
            "cand_per_matchday": _mean([v["cand"] for v in vals]),
            "A_per_matchday": _mean([v["A"] for v in vals]),
            "B_per_matchday": _mean([v["B"] for v in vals]),
            "matchdays_with_zero_A": sum(1 for v in vals if v["A"] == 0),
            "matchdays_with_zero_B": sum(1 for v in vals if v["B"] == 0),
        }
    all_vals = list(per_unit.values())
    out["coverage_per_matchday"] = {
        "aggregate": {
            "n_matchdays": len(all_vals),
            "cand_per_matchday": _mean([v["cand"] for v in all_vals]),
            "A_per_matchday": _mean([v["A"] for v in all_vals]),
            "B_per_matchday": _mean([v["B"] for v in all_vals]),
            "matchdays_with_zero_A": sum(1 for v in all_vals if v["A"] == 0),
            "matchdays_with_zero_B": sum(1 for v in all_vals if v["B"] == 0),
        },
        "by_league": cov_by_league,
    }

    # --- baseline: calibrazione dei sette mercati PRIMA di qualsiasi selettore
    baseline: Dict[str, Any] = {}
    for code in ("1", "X", "2", "O2.5", "U2.5", "GG", "NG"):
        pairs = [(r["per_market"][code]["poisson"], r["per_market"][code]["hit"])
                 for r in rows if code in r["per_market"]]
        baseline[code] = _stats_block(pairs)
    out["baseline_seven_markets_poisson"] = baseline

    # --- top 10 globale per weekend (pool sulle 5 leghe)
    out["top10"] = _top10_metrics(rows)

    # --- affidabilita' per bucket sull'evento selezionato
    out["reliability"] = {
        "A": _reliability([(r["A_conf"], r["A_hit"]) for r in rows if r["A_admitted"]]),
        "B": _reliability([(r["B_conf"], r["B_hit"]) for r in rows if r["B_admitted"]]),
    }

    out["units"] = {
        "n_replay_matchdays": len(units),
        "n_excluded_by_round_window": sum(u.get("n_excluded_window", 0) for u in units),
        "n_fixtures_in_seasons": sum(c.get("n_fixtures", 0) for c in fixture_coverage),
        "n_never_candidate": sum(c.get("n_never_candidate", 0) for c in fixture_coverage),
        "fixture_coverage": list(fixture_coverage),
    }
    # esempi concreti del caso dell'esempio: A scarta tutta la partita,
    # B la tiene con un altro mercato ammissibile
    rescued = sorted([r for r in rows if r["B_admitted"] and not r["A_admitted"]],
                     key=lambda r: r["B_conf"], reverse=True)
    out["rescued_examples"] = [{
        "league": r["league"], "season": r["season_label"], "matchday": r["matchday"],
        "match": f"{r['home']} - {r['away']}", "score": f"{r['fthg']}-{r['ftag']}",
        "A_market": r["A_market"], "A_conf": r["A_conf"],
        "A_disagree": r["A_disagree"], "A_min_conf": r["A_min_conf"],
        "B_market": r["B_market"], "B_conf": r["B_conf"], "B_hit": r["B_hit"],
    } for r in rescued[:10]]
    return out


def _reliability(pairs: Sequence[Tuple[float, int]]) -> List[Dict[str, Any]]:
    edges = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 1.01]
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = [(p, y) for p, y in pairs if lo <= p < hi]
        blk = _stats_block(sel)
        blk["bucket"] = f"[{lo:.2f},{hi:.2f})"
        out.append(blk)
    return out


def _iso_week(cutoff_iso: str) -> str:
    dt = datetime.fromisoformat(cutoff_iso)
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def _top10_metrics(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Pool globale sulle 5 leghe, taglio a 10, come in produzione.

    APPROSSIMAZIONE DICHIARATA: il pool live e' 'le prossime giornate delle 5
    leghe al momento del click'. Nel replay si raggruppa per settimana ISO del
    cutoff: e' l'unita' piu' vicina al weekend di campionato ricostruibile senza
    snapshot API. Identica per A e per B.
    """
    pools: Dict[Tuple[str, int], List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        pools[(_iso_week(r["cutoff"]), r["season"])].append(r)
    a_pairs: List[Tuple[float, int]] = []
    b_pairs: List[Tuple[float, int]] = []
    a_mix, b_mix = Counter(), Counter()
    n_pools = 0
    a_slots, b_slots = [], []
    for _, pool in sorted(pools.items()):
        n_pools += 1
        a_sel = sorted([r for r in pool if r["A_admitted"]],
                       key=lambda r: r["A_conf"], reverse=True)[:TOP_N]
        b_sel = sorted([r for r in pool if r["B_admitted"]],
                       key=lambda r: r["B_conf"], reverse=True)[:TOP_N]
        a_slots.append(len(a_sel))
        b_slots.append(len(b_sel))
        for r in a_sel:
            a_pairs.append((r["A_conf"], r["A_hit"]))
            a_mix[r["A_market"]] += 1
        for r in b_sel:
            b_pairs.append((r["B_conf"], r["B_hit"]))
            b_mix[r["B_market"]] += 1
    return {
        "n_pools": n_pools,
        "pool_rule": "settimana ISO del cutoff, 5 leghe insieme, taglio a 10",
        "A": {**_stats_block(a_pairs), "mean_slots_filled": _mean(a_slots),
              "market_mix": dict(a_mix)},
        "B": {**_stats_block(b_pairs), "mean_slots_filled": _mean(b_slots),
              "market_mix": dict(b_mix)},
        "bootstrap_pool": _top10_bootstrap(pools),
    }


def _top10_bootstrap(pools: Dict[Any, List[Dict[str, Any]]],
                     n_boot: int = 2000, seed: int = 20260905) -> Dict[str, Any]:
    """Bootstrap a blocchi sul pool (blocco = weekend): delta NON appaiato.

    Le righe della top 10 di A e di B non sono le stesse partite: il confronto e'
    fra due insiemi selezionati, quindi il blocco (il pool) e' l'unita' di
    ricampionamento, non la riga.
    """
    keys = list(pools)
    if not keys:
        return {"n_blocks": 0}

    def _agg(sample_keys: Sequence[Any]) -> Tuple[Optional[float], Optional[float],
                                                  Optional[float], Optional[float]]:
        ap: List[Tuple[float, int]] = []
        bp: List[Tuple[float, int]] = []
        for k in sample_keys:
            pool = pools[k]
            for r in sorted([x for x in pool if x["A_admitted"]],
                            key=lambda x: x["A_conf"], reverse=True)[:TOP_N]:
                ap.append((r["A_conf"], r["A_hit"]))
            for r in sorted([x for x in pool if x["B_admitted"]],
                            key=lambda x: x["B_conf"], reverse=True)[:TOP_N]:
                bp.append((r["B_conf"], r["B_hit"]))
        if not ap or not bp:
            return None, None, None, None
        return (_brier(ap), _brier(bp),
                sum(y for _, y in ap) / len(ap), sum(y for _, y in bp) / len(bp))

    ba, bb, ha, hb = _agg(keys)
    rng = random.Random(seed)
    d_brier, d_hit = [], []
    for _ in range(n_boot):
        sample = [keys[rng.randrange(len(keys))] for _ in range(len(keys))]
        x = _agg(sample)
        if x[0] is None:
            continue
        d_brier.append(x[0] - x[1])
        d_hit.append(x[2] - x[3])
    d_brier.sort()
    d_hit.sort()

    def _ci(v):
        if not v:
            return [None, None]
        return [v[int(0.025 * (len(v) - 1))], v[int(0.975 * (len(v) - 1))]]

    return {
        "n_blocks": len(keys),
        "brier_delta_A_minus_B": {
            "point": None if ba is None else ba - bb, "ci95": _ci(d_brier)},
        "hit_rate_delta_A_minus_B": {
            "point": None if ha is None else ha - hb, "ci95": _ci(d_hit)},
        "note": "Blocco = pool (weekend). Delta non appaiato: insiemi diversi di partite.",
    }


# ---------------------------------------------------------------------------
# 6. Report
# ---------------------------------------------------------------------------
def _f(x: Optional[float], nd: int = 4) -> str:
    if x is None:
        return "n/d"
    return f"{x:.{nd}f}"


def _pct(x: Optional[float]) -> str:
    if x is None:
        return "n/d"
    return f"{100 * x:.1f}%"


def render_report(metrics: Dict[str, Any], meta: Dict[str, Any]) -> str:
    agg = metrics["aggregate"]
    L: List[str] = []
    L.append("# Replay A vs B del selettore Top Mix — risultati numerici")
    L.append("")
    L.append(f"*Generato*: {meta['generated_at']} · *commit codice*: `{meta['git_sha'][:12]}`")
    L.append("")
    L.append("> **Etichetta dei dati.** " + SEASON_STATUS)
    L.append("> Non e' un hold-out. Nessuna soglia e' stata cercata o cambiata in "
             "questo giro: 0.55 / 0.60 / 0.25 e pesi 0.6/0.4 sono quelli di "
             "`fetch_and_calc_top_mix`. Nessun `--apply`, nessuna scrittura sul "
             "registro, nessuna chiamata JSONBin, nessun merge in produzione.")
    L.append("")
    L.append("## 0. Perimetro effettivo")
    L.append("")
    L.append(f"- Leghe: {', '.join(meta['leagues'])}")
    L.append(f"- Stagioni: {', '.join(meta['seasons'])}")
    L.append(f"- Giornate ricostruite: **{metrics['units']['n_replay_matchdays']}**")
    L.append(f"- Partite in calendario nelle stagioni replicate: "
             f"**{metrics['units'].get('n_fixtures_in_seasons', 0)}**")
    L.append(f"- Partite candidate (dopo `select_next_matchday_matches`): "
             f"**{agg['n_candidates']}**")
    L.append(f"- Partite mai candidate (recuperi fuori finestra o giocati mentre la "
             f"giornata successiva era gia' aperta): "
             f"**{metrics['units'].get('n_never_candidate', 0)}**")
    L.append(f"- Partite della giornata escluse dalla finestra di round "
             f"(`TOP_MIX_ROUND_WINDOW_DAYS={TOP_MIX_ROUND_WINDOW_DAYS}`): "
             f"**{metrics['units']['n_excluded_by_round_window']}**")
    L.append(f"- Righe duplicate scartate (una sola per `match_id`): "
             f"{metrics['n_duplicate_rows_dropped']}")
    L.append("")

    L.append("## 1. Frequenza di disaccordo sul mercato")
    L.append("")
    L.append("Due letture: (a) sulle partite che **entrambi** mostrano, quante volte "
             "il mercato scelto e' diverso; (b) su tutte le candidate, quante volte "
             "cio' che B mostrerebbe e' diverso dall'argmax Poisson di A (include le "
             "partite che A scarta del tutto).")
    L.append("")
    L.append("| Lega | Candidate | Ammesse A | Ammesse B | Entrambi ammessi | Mercato diverso (a) | Freq. (a) | Mercato diverso (b) | Freq. (b) |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, blk in list(metrics["by_league"].items()) + [("**AGGREGATO**", agg)]:
        d = blk["disagreement"]
        L.append(f"| {name} | {blk['n_candidates']} | {blk['n_A_admitted']} | "
                 f"{blk['n_B_admitted']} | {d['n_both_admitted']} | "
                 f"{d['n_diff_market_both_admitted']} | "
                 f"{_pct(d['freq_diff_given_both'])} | "
                 f"{d['n_diff_market_any_B']} | "
                 f"{_pct(d['freq_diff_over_candidates'])} |")
    L.append("")
    L.append("| Stagione | Candidate | Ammesse A | Ammesse B | Mercato diverso | Freq. disaccordo (su entrambi) |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for name, blk in metrics["by_season"].items():
        d = blk["disagreement"]
        L.append(f"| {name} | {blk['n_candidates']} | {blk['n_A_admitted']} | "
                 f"{blk['n_B_admitted']} | {d['n_diff_market_both_admitted']} | "
                 f"{_pct(d['freq_diff_given_both'])} |")
    L.append("")

    L.append("## 2. Partite in disaccordo: hit rate e Brier sull'evento scelto da ciascuno")
    L.append("")
    L.append("Ogni selettore e' valutato sull'evento che ha selezionato lui, con la "
             "probabilita' che avrebbe mostrato (`confidence`).")
    L.append("")
    L.append("| Lega | n | prob media A | hit A | Brier A | prob media B | hit B | Brier B | ΔBrier (A−B) |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, blk in list(metrics["by_league"].items()) + [("**AGGREGATO**", agg)]:
        a, b = blk["on_disagreement"]["A"], blk["on_disagreement"]["B"]
        db = None if (a["brier"] is None or b["brier"] is None) else a["brier"] - b["brier"]
        L.append(f"| {name} | {a['n']} | {_pct(a['mean_prob'])} | {_pct(a['hit_rate'])} | "
                 f"{_f(a['brier'])} | {_pct(b['mean_prob'])} | {_pct(b['hit_rate'])} | "
                 f"{_f(b['brier'])} | {_f(db)} |")
    L.append("")
    L.append("| Stagione | n | hit A | Brier A | hit B | Brier B | ΔBrier (A−B) |")
    L.append("|---|---:|---:|---:|---:|---:|---:|")
    for name, blk in metrics["by_season"].items():
        a, b = blk["on_disagreement"]["A"], blk["on_disagreement"]["B"]
        db = None if (a["brier"] is None or b["brier"] is None) else a["brier"] - b["brier"]
        L.append(f"| {name} | {a['n']} | {_pct(a['hit_rate'])} | {_f(a['brier'])} | "
                 f"{_pct(b['hit_rate'])} | {_f(b['brier'])} | {_f(db)} |")
    L.append("")
    u = metrics["uncertainty"]["disagreement_subset"]
    L.append("Incertezza (bootstrap a blocchi, blocco = giornata, coppie appaiate):")
    L.append("")
    L.append(f"- ΔBrier A−B = {_f(u['brier_delta_A_minus_B']['point'])} "
             f"(IC95% {_f(u['brier_delta_A_minus_B']['ci95'][0])} … "
             f"{_f(u['brier_delta_A_minus_B']['ci95'][1])}, "
             f"{u['brier_delta_A_minus_B']['n_blocks']} blocchi)")
    L.append(f"- Δhit rate A−B = {_f(u['hit_rate_delta_A_minus_B']['point'])} "
             f"(IC95% {_f(u['hit_rate_delta_A_minus_B']['ci95'][0])} … "
             f"{_f(u['hit_rate_delta_A_minus_B']['ci95'][1])})")
    L.append("")
    ub = metrics["uncertainty"]["both_admitted"]
    L.append(f"Su tutte le partite ammesse da entrambi (n = {agg['n_both']}): "
             f"ΔBrier A−B = {_f(ub['brier_delta_A_minus_B']['point'])} "
             f"(IC95% {_f(ub['brier_delta_A_minus_B']['ci95'][0])} … "
             f"{_f(ub['brier_delta_A_minus_B']['ci95'][1])}), "
             f"Δhit = {_f(ub['hit_rate_delta_A_minus_B']['point'])} "
             f"(IC95% {_f(ub['hit_rate_delta_A_minus_B']['ci95'][0])} … "
             f"{_f(ub['hit_rate_delta_A_minus_B']['ci95'][1])}).")
    L.append("")

    L.append("## 3. Partite scartate da A e accettate da B (e viceversa)")
    L.append("")
    L.append("| Lega | Scartate da A / accettate da B | Scartate da B / accettate da A | prob media B (recuperate) | hit B | Brier B |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for name, blk in list(metrics["by_league"].items()) + [("**AGGREGATO**", agg)]:
        rb = blk["rescued_by_B"]
        s = rb["stats_B"]
        L.append(f"| {name} | {rb['n']} | {blk['lost_by_B']['n']} | "
                 f"{_pct(s['mean_prob'])} | {_pct(s['hit_rate'])} | {_f(s['brier'])} |")
    L.append("")
    L.append("Motivo per cui A aveva scartato l'intera partita (aggregato):")
    L.append("")
    for reason, n in sorted(agg["rescued_by_B"]["reasons"].items(),
                            key=lambda kv: -kv[1]):
        L.append(f"- {reason}: **{n}**")
    L.append("")
    L.append("Mercato con cui B recupera la partita (aggregato):")
    L.append("")
    for mkt, n in sorted(agg["rescued_by_B"]["markets"].items(), key=lambda kv: -kv[1]):
        L.append(f"- {mkt}: **{n}**")
    L.append("")
    L.append(f"Nota: {agg['lost_by_B']['note']} Il replay lo conferma "
             f"empiricamente ({agg['n_A_only']} casi).")
    L.append("")
    if metrics.get("rescued_examples"):
        L.append("Esempi (prime 10 per confidence di B) del caso descritto: il mercato "
                 "migliore veniva buttato via perche' il primo scelto non passava i filtri.")
        L.append("")
        L.append("| Lega | Stagione | G. | Partita | Risultato | A: mercato | A: conf | A: disacc. Elo | B: mercato | B: conf | B: esito |")
        L.append("|---|---|---:|---|---|---|---:|---:|---|---:|---:|")
        for e in metrics["rescued_examples"]:
            L.append(f"| {e['league']} | {e['season']} | {e['matchday']} | {e['match']} | "
                     f"{e['score']} | {e['A_market']} | {_pct(e['A_conf'])} | "
                     f"{_f(e['A_disagree'], 3)} | {e['B_market']} | {_pct(e['B_conf'])} | "
                     f"{'sì' if e['B_hit'] else 'no'} |")
        L.append("")

    L.append("## 4. Copertura")
    L.append("")
    cov = metrics["coverage_per_matchday"]
    L.append("| Lega | Giornate | Candidate/giornata | Ammesse A/giornata | Ammesse B/giornata | Giornate con 0 righe A | con 0 righe B |")
    L.append("|---|---:|---:|---:|---:|---:|---:|")
    for name, blk in list(cov["by_league"].items()) + [("**AGGREGATO**", cov["aggregate"])]:
        L.append(f"| {name} | {blk['n_matchdays']} | {_f(blk['cand_per_matchday'], 2)} | "
                 f"{_f(blk['A_per_matchday'], 2)} | {_f(blk['B_per_matchday'], 2)} | "
                 f"{blk['matchdays_with_zero_A']} | {blk['matchdays_with_zero_B']} |")
    L.append("")
    L.append(f"Copertura sulle candidate: A {_pct(agg['coverage_A'])} "
             f"({agg['n_A_admitted']}/{agg['n_candidates']}), "
             f"B {_pct(agg['coverage_B'])} "
             f"({agg['n_B_admitted']}/{agg['n_candidates']}).")
    L.append("")
    t = metrics["top10"]
    L.append(f"Pool globale + taglio a {TOP_N} ({t['pool_rule']}, {t['n_pools']} pool):")
    L.append("")
    L.append("| Selettore | righe | slot medi riempiti | prob media | hit rate | Brier |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for key in ("A", "B"):
        b = t[key]
        L.append(f"| {key} | {b['n']} | {_f(b['mean_slots_filled'], 2)} | "
                 f"{_pct(b['mean_prob'])} | {_pct(b['hit_rate'])} | {_f(b['brier'])} |")
    L.append("")
    tb = t.get("bootstrap_pool", {})
    if tb.get("n_blocks"):
        L.append(f"Bootstrap a blocchi sul pool ({tb['n_blocks']} weekend, delta non "
                 f"appaiato): ΔBrier A−B = "
                 f"{_f(tb['brier_delta_A_minus_B']['point'])} "
                 f"(IC95% {_f(tb['brier_delta_A_minus_B']['ci95'][0])} … "
                 f"{_f(tb['brier_delta_A_minus_B']['ci95'][1])}), "
                 f"Δhit = {_f(tb['hit_rate_delta_A_minus_B']['point'])} "
                 f"(IC95% {_f(tb['hit_rate_delta_A_minus_B']['ci95'][0])} … "
                 f"{_f(tb['hit_rate_delta_A_minus_B']['ci95'][1])}).")
        L.append("")
    L.append("Tutte le righe che ciascun selettore mostrerebbe (insiemi di dimensione "
             "diversa, confronto non appaiato):")
    L.append("")
    L.append("| Lega | n righe A | hit A | Brier A | n righe B | hit B | Brier B |")
    L.append("|---|---:|---:|---:|---:|---:|---:|")
    for name, blk in list(metrics["by_league"].items()) + [("**AGGREGATO**", agg)]:
        a, b = blk["on_all_shown"]["A"], blk["on_all_shown"]["B"]
        L.append(f"| {name} | {a['n']} | {_pct(a['hit_rate'])} | {_f(a['brier'])} | "
                 f"{b['n']} | {_pct(b['hit_rate'])} | {_f(b['brier'])} |")
    L.append("")

    L.append("## 5. Composizione per mercato (conteggi)")
    L.append("")
    codes = ["1", "X", "2", "O2.5", "U2.5", "GG", "NG"]
    L.append("| Insieme | " + " | ".join(codes) + " |")
    L.append("|---" * (len(codes) + 1) + "|")
    for label, key in (("A (pre-filtri, argmax Poisson)", "market_mix_A_prefilter"),
                       ("A (mostrate)", "market_mix_A"),
                       ("B (mostrate)", "market_mix_B")):
        mix = agg[key]
        L.append(f"| {label} | " + " | ".join(str(mix.get(c, 0)) for c in codes) + " |")
    L.append("")
    L.append("Top 10: " + ", ".join(
        f"A {c}={t['A']['market_mix'].get(c, 0)}/B {c}={t['B']['market_mix'].get(c, 0)}"
        for c in codes))
    L.append("")

    L.append("## 6. Baseline: calibrazione dei sette mercati prima di qualsiasi selettore")
    L.append("")
    L.append("Probabilita' Poisson di produzione su TUTTE le partite candidate "
             "(nessuna selezione): serve a distinguere un difetto del modello da un "
             "effetto dell'ordine di selezione (protocollo §5).")
    L.append("")
    L.append("| Mercato | n | prob media | frequenza reale | gap | Brier |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for code in codes:
        b = metrics["baseline_seven_markets_poisson"][code]
        L.append(f"| {code} | {b['n']} | {_pct(b['mean_prob'])} | {_pct(b['hit_rate'])} | "
                 f"{_f(b['gap'], 3)} | {_f(b['brier'])} |")
    L.append("")

    L.append("## 7. Affidabilita' per bucket sull'evento selezionato")
    L.append("")
    L.append("| Bucket | n A | prob media A | hit A | n B | prob media B | hit B |")
    L.append("|---|---:|---:|---:|---:|---:|---:|")
    for ra, rb in zip(metrics["reliability"]["A"], metrics["reliability"]["B"]):
        L.append(f"| {ra['bucket']} | {ra['n']} | {_pct(ra['mean_prob'])} | "
                 f"{_pct(ra['hit_rate'])} | {rb['n']} | {_pct(rb['mean_prob'])} | "
                 f"{_pct(rb['hit_rate'])} |")
    L.append("")

    L.append("## 8. Dettaglio per lega e stagione")
    L.append("")
    L.append("| Lega / stagione | Cand. | A amm. | B amm. | disacc. | hit A | Brier A | hit B | Brier B |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, blk in metrics["by_league_season"].items():
        a, b = blk["on_disagreement"]["A"], blk["on_disagreement"]["B"]
        L.append(f"| {name} | {blk['n_candidates']} | {blk['n_A_admitted']} | "
                 f"{blk['n_B_admitted']} | {a['n']} | {_pct(a['hit_rate'])} | "
                 f"{_f(a['brier'])} | {_pct(b['hit_rate'])} | {_f(b['brier'])} |")
    L.append("")

    L.append("## 9. Limiti dichiarati (protocollo §6)")
    L.append("")
    for lim in meta["limits"]:
        L.append(f"- {lim}")
    L.append("")
    return "\n".join(L)


LIMITS = [
    "Nessuno snapshot dello stato TIMED/SCHEDULED dell'API: i candidati sono le "
    "partite della giornata ricostruita dai CSV, non il feed del click.",
    "`matchday` non esiste nei CSV football-data.co.uk: e' ricostruito come "
    "n-esima partita di ciascuna squadra (max fra casa e trasferta). Sui recuperi "
    "differisce dalla numerazione ufficiale. Identico per A e per B.",
    "I nomi passati a `clean_name` sono quelli dei CSV, non gli `shortName` "
    "dell'API football-data.org.",
    "`MARKET_VALUES` e' statico e non versionato per stagione: applicato al "
    "2024/25 e al 2025/26 e' leakage gia' dichiarato. Identico per A e per B.",
    "Gli xG di Understat vengono rivisti: l'archivio conserva l'ultimo valore, "
    "quindi il cutoff esclude le partite del giorno ma non le revisioni.",
    "Gli orari dei CSV sono trattati come UTC (fuso reale non dichiarato nel dato).",
    "La forma a 5 partite e' calcolata sul df multi-stagione, come in produzione: "
    "per una neopromossa include partite di stagioni precedenti.",
    "Il pool del taglio a 10 e' la settimana ISO del cutoff, non il pool live delle "
    "5 leghe al momento del click.",
    "Elo non persistito: e' ricalcolato dai CSV troncati al cutoff.",
]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join(_AUDIT_DIR, "results"),
                    help="directory di output (default: audit/results)")
    ap.add_argument("--leagues", nargs="*", default=list(LEAGUES))
    ap.add_argument("--seasons", nargs="*", type=int, default=list(SEASONS))
    ap.add_argument("--rows-json", action="store_true",
                    help="salva anche le righe per-partita in JSON")
    args = ap.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    print("Replay A vs B (sola lettura, nessuna soglia toccata)…", flush=True)
    data = replay(args.leagues, args.seasons)
    metrics = compute_metrics(data["rows"], data["units"],
                              data.get("fixture_coverage", []))
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": R.git_sha(),
        "leagues": list(args.leagues),
        "seasons": [SEASON_LABEL.get(s, str(s)) for s in args.seasons],
        "season_status": SEASON_STATUS,
        "thresholds": {
            "min_conf_1x2": R.MIN_CONF_1X2,
            "min_conf_ou_gg": R.MIN_CONF_OU_GG,
            "elo_disagree_max": R.ELO_DISAGREE_MAX,
            "poisson_weight": R.POISSON_WEIGHT,
            "elo_weight": R.ELO_WEIGHT,
            "top_n": TOP_N,
            "round_window_days": TOP_MIX_ROUND_WINDOW_DAYS,
            "prior_matches": R.PRIOR_MATCHES,
            "note": "invariate: nessuna ricerca di parametri in questo giro",
        },
        "forbidden_functions_not_called": list(R._FORBIDDEN_CALLS),
        "limits": LIMITS,
    }
    payload = {"meta": meta, "metrics": metrics, "units": data["units"]}
    if args.rows_json:
        payload["rows"] = data["rows"]
    json_path = os.path.join(args.out, "topmix_selector_replay.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(R._json_safe(payload), f, ensure_ascii=False, indent=2)
    md_path = os.path.join(args.out, "topmix_selector_replay.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_report(metrics, meta))
    csv_path = os.path.join(args.out, "topmix_selector_replay_rows.csv")
    _write_rows_csv(data["rows"], csv_path)
    print(f"JSON  -> {json_path}")
    print(f"MD    -> {md_path}")
    print(f"CSV   -> {csv_path}")
    return 0


def _write_rows_csv(rows: Sequence[Dict[str, Any]], path: str) -> None:
    import csv
    cols = ["league", "season_label", "matchday", "cutoff", "match_id", "home",
            "away", "kickoff", "fthg", "ftag", "elo_available",
            "team_stats_missing", "A_market", "A_poisson", "A_conf",
            "A_disagree", "A_min_conf", "A_admitted", "A_hit", "B_market",
            "B_conf", "B_admitted", "B_n_admitted_markets", "B_hit"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


if __name__ == "__main__":
    raise SystemExit(main())
