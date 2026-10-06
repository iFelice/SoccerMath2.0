#!/usr/bin/env python3
"""Fattibilita' feature squalifiche: player_match -> eventi, conteggi, potenza.

Sola lettura: i dati pesanti restano sotto audit/output/ (git-ignored). Lo
script accetta una cartella con i file ``player_match_<lega>.json`` prodotti da
``update_all_ppda_player_db.py`` (Understat via soccerdata==1.9.1) e sostituisce
il report precedente in ``audit/results/squalifiche_feasibility.md``.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import math
import os
import random
import subprocess
import sys
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = REPO_ROOT / "audit"
SOCCERMATH_DIR = REPO_ROOT / "SoccerMath"
if str(SOCCERMATH_DIR) not in sys.path:
    sys.path.insert(0, str(SOCCERMATH_DIR))
if str(AUDIT_DIR) not in sys.path:
    sys.path.insert(0, str(AUDIT_DIR))

from team_names import canonical_team_name  # noqa: E402
from models.elo_engine import elo_probs_from_ratings  # noqa: E402
import app as prod_app  # noqa: E402
from xg_archive import load_archive, season_point_in_time_averages  # noqa: E402

TODAY = dt.date(2026, 10, 6)
ANALYSIS_SEASONS = [2023, 2024, 2025]
ALL_SEASONS = [2022, 2023, 2024, 2025, 2026]
BOOTSTRAP_SEED = 20261006


@dataclass(frozen=True)
class LeagueConfig:
    name: str
    key: str
    csv_stem: str
    xg_archive: str
    player_file: str


LEAGUES: Sequence[LeagueConfig] = (
    LeagueConfig("Serie A", "SerieA", "SerieA", "xG archivio serie A.json", "player_match_serie_a.json"),
    LeagueConfig("Premier League", "Premier", "Premier", "xG archivio premier league.json", "player_match_premier_league.json"),
    LeagueConfig("La Liga", "LaLiga", "LaLiga", "xG archivio la liga.json", "player_match_la_liga.json"),
    LeagueConfig("Bundesliga", "Bundesliga", "Bundesliga", "xG archivio bundesliga.json", "player_match_bundesliga.json"),
    LeagueConfig("Ligue 1", "Ligue1", "Ligue1", "xG archivio ligue 1.json", "player_match_ligue_1.json"),
)

RULES = {
    "Serie A": "gialli cumulativi 5,9,13,16,18, poi ogni ammonizione; coppe separate",
    "Premier League": "5 gialli entro 19a partita squadra -> 1; 10 entro 32a -> 2; 15 -> 3",
    "La Liga": "cicli da 5; esenzione ultima giornata; doppia ammonizione esclusa/ambigua",
    "Bundesliga": "5a, 10a, 15a... ammonizione -> 1 turno",
    "Ligue 1": "2023/24-2024/25: 3 gialli in 10 incontri ufficiali; 2025/26: 5 gialli; coppe nazionali mancanti nel dataset",
}

ROLE_LABELS = ["portiere", "difensore", "centrocampista", "attaccante", "non disponibile"]


@dataclass
class Match:
    league: str
    season: int
    match_id: int
    kickoff: pd.Timestamp
    home: str
    away: str
    home_raw: str
    away_raw: str
    home_goals: Optional[int]
    away_goals: Optional[int]


@dataclass
class Event:
    league: str
    season: int
    player_id: Any
    player: str
    team: str
    rule: str
    source_match_id: int
    source_kickoff: pd.Timestamp
    skipped_match_id: int
    skipped_kickoff: pd.Timestamp
    opponent: str
    venue: str
    known_at: pd.Timestamp
    role: str
    position: str
    high60: bool
    high40: bool
    usage_share: Optional[float]
    minutes_last5: float
    available_last5: float
    validation_played: bool


def run(cmd: Sequence[str], check: bool = False) -> Tuple[int, str]:
    p = subprocess.run(cmd, cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check and p.returncode != 0:
        raise RuntimeError(p.stdout)
    return p.returncode, p.stdout.strip()


def rel(path: Path | str) -> str:
    p = Path(path)
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def season_label(season: int) -> str:
    return f"{season}/{str(season + 1)[-2:]}"


def md_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    def cell(x: Any) -> str:
        if x is None:
            return "n/d"
        s = str(x).replace("\n", "<br>").replace("|", "\\|")
        return s
    out = ["| " + " | ".join(map(cell, headers)) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(cell(x) for x in r) + " |")
    return "\n".join(out)


def fmt_pct(x: Optional[float], nd: int = 1) -> str:
    if x is None or not np.isfinite(x):
        return "n/d"
    return f"{100*x:.{nd}f}%"


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def parse_ts(s: Any) -> pd.Timestamp:
    ts = pd.to_datetime(s, utc=True, errors="coerce")
    if pd.isna(ts):
        ts = pd.to_datetime(s, errors="coerce")
        if pd.isna(ts):
            raise ValueError(f"data non parsabile: {s!r}")
        ts = ts.tz_localize("UTC")
    return ts


def role_group(position: Any) -> str:
    p = ("" if position is None else str(position)).upper().strip()
    if not p:
        return "non disponibile"
    if p in {"GK", "G"} or "GK" in p:
        return "portiere"
    # Understat: DMC/MC/AMC/ML/MR sono centrocampo; FW/FWL/FWR attacco.
    if p.startswith("FW") or p in {"ST", "CF", "F"}:
        return "attaccante"
    if "MC" in p or p in {"ML", "MR", "M", "AM", "AMC", "DM", "DMC"}:
        return "centrocampista"
    if p.startswith("D") or p in {"CB", "LB", "RB", "WB"}:
        return "difensore"
    return "non disponibile"


def event_side(match: Match, team: str) -> str:
    if canonical_team_name(team) == match.home:
        return "home"
    if canonical_team_name(team) == match.away:
        return "away"
    return "unknown"


def load_matches() -> Tuple[Dict[str, Dict[int, Match]], Dict[Tuple[str, int], List[Match]], Dict[Tuple[str, int, str], List[Match]]]:
    by_league_id: Dict[str, Dict[int, Match]] = defaultdict(dict)
    by_league_season: Dict[Tuple[str, int], List[Match]] = defaultdict(list)
    by_team_season: Dict[Tuple[str, int, str], List[Match]] = defaultdict(list)
    for lg in LEAGUES:
        path = SOCCERMATH_DIR / "database" / lg.xg_archive
        data = load_json(path)
        for rec in data:
            if rec.get("id") is None or rec.get("date") is None:
                continue
            season = int(rec.get("season"))
            m = Match(
                league=lg.name,
                season=season,
                match_id=int(rec["id"]),
                kickoff=parse_ts(rec["date"]),
                home=canonical_team_name(rec.get("home_team")),
                away=canonical_team_name(rec.get("away_team")),
                home_raw=str(rec.get("home_team")),
                away_raw=str(rec.get("away_team")),
                home_goals=rec.get("home_goals"),
                away_goals=rec.get("away_goals"),
            )
            by_league_id[lg.name][m.match_id] = m
            by_league_season[(lg.name, season)].append(m)
            by_team_season[(lg.name, season, m.home)].append(m)
            by_team_season[(lg.name, season, m.away)].append(m)
    for d in (by_league_season, by_team_season):
        for k in d:
            d[k].sort(key=lambda x: (x.kickoff, x.match_id))
    return by_league_id, by_league_season, by_team_season


def load_player_rows(player_dir: Path, matches_by_id: Dict[str, Dict[int, Match]]) -> Tuple[List[dict], Dict[Tuple[str, int, Any], dict], Dict[Tuple[str, int, Any], List[dict]], Dict[Tuple[str, int, Any], dict]]:
    rows: List[dict] = []
    player_match_index: Dict[Tuple[str, int, Any], dict] = {}
    rows_by_team_match: Dict[Tuple[str, int, Any], List[dict]] = defaultdict(list)
    player_latest: Dict[Tuple[str, int, Any], dict] = {}
    for lg in LEAGUES:
        path = player_dir / lg.player_file
        if not path.exists():
            raise FileNotFoundError(f"manca {path}")
        data = load_json(path)
        for r in data:
            season = int(r.get("season"))
            match_id = int(r.get("id"))
            m = matches_by_id[lg.name].get(match_id)
            if not m:
                continue
            team = canonical_team_name(r.get("team"))
            rec = dict(r)
            rec.update({
                "league": lg.name,
                "season": season,
                "match_id": match_id,
                "kickoff": m.kickoff,
                "team_canon": team,
                "opponent_canon": canonical_team_name(r.get("opponent")),
                "player_key": r.get("player_id") if r.get("player_id") is not None else str(r.get("player")),
                "minutes_num": float(r.get("minutes") or 0),
                "yellow_num": int(r.get("yellow_cards") or 0),
                "red_num": int(r.get("red_cards") or 0),
                "role_group": role_group(r.get("position")),
            })
            rows.append(rec)
            player_match_index[(lg.name, match_id, rec["player_key"])] = rec
            rows_by_team_match[(lg.name, match_id, team)].append(rec)
            player_latest[(lg.name, season, rec["player_key"])] = rec
    rows.sort(key=lambda r: (r["league"], r["kickoff"], r["match_id"], r["team_canon"], str(r["player_key"])))
    return rows, player_match_index, rows_by_team_match, player_latest


def next_matches(team_matches: List[Match], after: pd.Timestamp, n: int) -> List[Match]:
    return [m for m in team_matches if m.kickoff > after][:n]


def previous_matches(team_matches: List[Match], before: pd.Timestamp, n: int = 5) -> List[Match]:
    prev = [m for m in team_matches if m.kickoff < before]
    return prev[-n:]


def high_usage(player_key: Any, league: str, team: str, season: int, skipped: Match,
               by_team_season: Dict[Tuple[str, int, str], List[Match]],
               player_match_index: Dict[Tuple[str, int, Any], dict]) -> Tuple[bool, bool, Optional[float], float, float]:
    pm = previous_matches(by_team_season.get((league, season, team), []), skipped.kickoff, 5)
    available = 90.0 * len(pm)
    if available <= 0:
        return False, False, None, 0.0, 0.0
    mins = 0.0
    for m in pm:
        rec = player_match_index.get((league, m.match_id, player_key))
        if rec and rec.get("team_canon") == team:
            mins += float(rec.get("minutes_num") or 0)
    share = mins / available
    return share >= 0.60, share >= 0.40, share, mins, available


def add_event(events: List[Event], league: str, player_rec: dict, team: str, rule: str,
              source_match: Match, skipped: Match,
              by_team_season, player_match_index) -> None:
    side = event_side(skipped, team)
    opponent = skipped.away if side == "home" else skipped.home if side == "away" else ""
    high60, high40, share, mins, avail = high_usage(
        player_rec["player_key"], league, team, skipped.season, skipped, by_team_season, player_match_index)
    played = (league, skipped.match_id, player_rec["player_key"]) in player_match_index
    rec_skip = player_match_index.get((league, skipped.match_id, player_rec["player_key"]))
    if rec_skip is not None and rec_skip.get("minutes_num", 0) <= 0:
        played = False
    events.append(Event(
        league=league,
        season=skipped.season,
        player_id=player_rec["player_key"],
        player=str(player_rec.get("player")),
        team=team,
        rule=rule,
        source_match_id=source_match.match_id,
        source_kickoff=source_match.kickoff,
        skipped_match_id=skipped.match_id,
        skipped_kickoff=skipped.kickoff,
        opponent=opponent,
        venue=side,
        known_at=source_match.kickoff,
        role=player_rec.get("role_group") or "non disponibile",
        position=str(player_rec.get("position") or ""),
        high60=high60,
        high40=high40,
        usage_share=share,
        minutes_last5=mins,
        available_last5=avail,
        validation_played=played,
    ))


def reconstruct_events(rows: List[dict], matches_by_id: Dict[str, Dict[int, Match]], by_team_season, player_match_index) -> Tuple[List[Event], List[dict]]:
    events: List[Event] = []
    ambiguous: List[dict] = []
    # state keyed by league/season/team/player because transfers make sanctions ambiguous.
    yellow_count = defaultdict(int)
    serie_thresholds = defaultdict(lambda: [5, 9, 13, 16, 18])
    ligue_window = defaultdict(deque)
    pl_triggered = defaultdict(set)
    liga_cycle = defaultdict(int)
    bundes_count = defaultdict(int)
    ligue_count_2025 = defaultdict(int)

    rows_sorted = sorted(rows, key=lambda r: (r["league"], r["kickoff"], r["match_id"]))
    for r in rows_sorted:
        league, season, team, pkey = r["league"], int(r["season"]), r["team_canon"], r["player_key"]
        match = matches_by_id[league].get(int(r["match_id"]))
        if match is None:
            continue
        # Direct red: only red without yellow is treated as certain direct red.
        if r["red_num"] > 0:
            if r["yellow_num"] == 0:
                nm = next_matches(by_team_season.get((league, season, team), []), match.kickoff, 1)
                if nm and nm[0].season in ANALYSIS_SEASONS:
                    add_event(events, league, r, team, "rosso diretto osservato (red=1,yellow=0) -> 1 turno", match, nm[0], by_team_season, player_match_index)
            else:
                ambiguous.append({"league": league, "season": season, "match_id": match.match_id, "player": r.get("player"), "team": team, "reason": "red_cards>0 con yellow_cards>0: diretto dopo giallo o doppia ammonizione non distinguibile in Understat"})

        y = int(r["yellow_num"] or 0)
        if y <= 0:
            continue
        # If red happened too, yellow contribution is ambiguous for accumulation.
        if r["red_num"] > 0:
            continue
        key = (league, season, team, pkey)
        if league == "Serie A":
            for _ in range(y):
                yellow_count[key] += 1
                c = yellow_count[key]
                thresholds = serie_thresholds[key]
                if c in thresholds or c >= 19:
                    nm = next_matches(by_team_season.get((league, season, team), []), match.kickoff, 1)
                    if nm and nm[0].season in ANALYSIS_SEASONS:
                        add_event(events, league, r, team, f"accumulo Serie A ammonizione {c}", match, nm[0], by_team_season, player_match_index)
        elif league == "Premier League":
            # team match number in league season at source match.
            team_ms = by_team_season.get((league, season, team), [])
            tm_no = 1 + [m.match_id for m in team_ms].index(match.match_id) if match in team_ms else None
            for _ in range(y):
                yellow_count[key] += 1
                c = yellow_count[key]
                ban_len = 0
                rule = None
                if c >= 5 and 5 not in pl_triggered[key] and tm_no is not None and tm_no <= 19:
                    ban_len, rule = 1, "accumulo Premier 5 gialli entro 19a partita squadra"
                    pl_triggered[key].add(5)
                elif c >= 10 and 10 not in pl_triggered[key] and tm_no is not None and tm_no <= 32:
                    ban_len, rule = 2, "accumulo Premier 10 gialli entro 32a partita squadra"
                    pl_triggered[key].add(10)
                elif c >= 15 and 15 not in pl_triggered[key]:
                    ban_len, rule = 3, "accumulo Premier 15 gialli in stagione"
                    pl_triggered[key].add(15)
                if ban_len:
                    for nm in next_matches(team_ms, match.kickoff, ban_len):
                        if nm.season in ANALYSIS_SEASONS:
                            add_event(events, league, r, team, rule, match, nm, by_team_season, player_match_index)
        elif league == "La Liga":
            team_ms = by_team_season.get((league, season, team), [])
            is_last = bool(team_ms and team_ms[-1].match_id == match.match_id)
            for _ in range(y):
                liga_cycle[key] += 1
                if liga_cycle[key] >= 5:
                    if is_last:
                        ambiguous.append({"league": league, "season": season, "match_id": match.match_id, "player": r.get("player"), "team": team, "reason": "5a ammonizione Liga all'ultima giornata: esenzione art.112.4, nessun evento contato"})
                    else:
                        nm = next_matches(team_ms, match.kickoff, 1)
                        if nm and nm[0].season in ANALYSIS_SEASONS:
                            add_event(events, league, r, team, "accumulo La Liga ciclo da 5", match, nm[0], by_team_season, player_match_index)
                    liga_cycle[key] = 0
        elif league == "Bundesliga":
            for _ in range(y):
                bundes_count[key] += 1
                c = bundes_count[key]
                if c % 5 == 0:
                    nm = next_matches(by_team_season.get((league, season, team), []), match.kickoff, 1)
                    if nm and nm[0].season in ANALYSIS_SEASONS:
                        add_event(events, league, r, team, f"accumulo Bundesliga ammonizione {c}", match, nm[0], by_team_season, player_match_index)
        elif league == "Ligue 1":
            team_ms = by_team_season.get((league, season, team), [])
            if season <= 2024:
                # League-only lower-bound implementation; domestic cups missing are declared as source limit.
                dq = ligue_window[key]
                # store team-match ordinal to approximate 10 official/league window
                try:
                    tm_no = 1 + [m.match_id for m in team_ms].index(match.match_id)
                except ValueError:
                    tm_no = None
                for _ in range(y):
                    if tm_no is not None:
                        dq.append(tm_no)
                        while dq and tm_no - dq[0] >= 10:
                            dq.popleft()
                        if len(dq) >= 3:
                            nm = next_matches(team_ms, match.kickoff, 1)
                            if nm and nm[0].season in ANALYSIS_SEASONS:
                                add_event(events, league, r, team, "Ligue 1 league-only: 3 gialli in 10 partite (coppe mancanti dichiarate)", match, nm[0], by_team_season, player_match_index)
                            dq.clear()
            else:
                for _ in range(y):
                    ligue_count_2025[key] += 1
                    c = ligue_count_2025[key]
                    if c % 5 == 0:
                        nm = next_matches(team_ms, match.kickoff, 1)
                        if nm and nm[0].season in ANALYSIS_SEASONS:
                            add_event(events, league, r, team, f"Ligue 1 2025/26 league-only ammonizione {c}/5 (coppe mancanti dichiarate)", match, nm[0], by_team_season, player_match_index)
    return events, ambiguous


# ---------------------- model probabilities ------------------------------

def ensure_elo_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        code, out = run([sys.executable, "audit/elo_weight_retune.py"])
        if code != 0:
            raise RuntimeError(out)
        # Do not keep timestamp-only retune report diffs.
        run(["git", "checkout", "--", "audit/results/elo_weight_retune.md"])
    return pd.read_parquet(path)


class TeamState:
    def __init__(self):
        self.hgf = self.hga = self.hgn = 0.0
        self.agf = self.aga = self.agn = 0.0
        self.last5 = deque(maxlen=5)

    def observe_home(self, fthg, ftag):
        self.hgf += fthg; self.hga += ftag; self.hgn += 1
        self.last5.append((fthg, ftag))

    def observe_away(self, fthg, ftag):
        self.agf += ftag; self.aga += fthg; self.agn += 1
        self.last5.append((ftag, fthg))


def ou25_walkforward() -> Dict[Tuple[str, int, str, str, pd.Timestamp], Dict[str, float]]:
    out = {}
    shrunk = prod_app._shrunk_ratio
    league_gate = prod_app._league_mean_gate
    two_heads = prod_app.get_full_poisson_two_heads
    for lg in LEAGUES:
        # Football-data CSVs, seasons 2022-2025.
        frames = []
        for season in ALL_SEASONS:
            p = SOCCERMATH_DIR / "database" / f"{lg.csv_stem}_{season}.csv"
            if p.exists():
                df = pd.read_csv(p)
                df["season_start"] = season
                frames.append(df)
        if not frames:
            continue
        df = pd.concat(frames, ignore_index=True)
        df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce", utc=True)
        df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"]).sort_values("Date", kind="stable").reset_index(drop=True)
        df["HomeClean"] = df["HomeTeam"].map(canonical_team_name)
        df["AwayClean"] = df["AwayTeam"].map(canonical_team_name)
        fs_records = load_archive(lg.name)
        state: Dict[str, TeamState] = {}
        fs_cache = {}
        tot_hg = tot_ag = 0.0
        tot_n = 0

        def st(t):
            state.setdefault(t, TeamState())
            return state[t]

        for row in df.itertuples(index=False):
            h, a = row.HomeClean, row.AwayClean
            fthg, ftag = int(row.FTHG), int(row.FTAG)
            avg_h = max(tot_hg / tot_n, 0.1) if tot_n else 0.1
            avg_a = max(tot_ag / tot_n, 0.1) if tot_n else 0.1
            season = int(row.season_start)
            cache_key = (season, row.Date.date())
            if cache_key not in fs_cache:
                try:
                    agg = season_point_in_time_averages(lg.name, cutoff=row.Date.to_pydatetime(), season=season, records=fs_records)
                    axg, axga = league_gate(agg.averages)
                    fs_cache[cache_key] = (agg.averages if axg is not None else {}, axg, axga, axg is not None)
                except Exception:
                    fs_cache[cache_key] = ({}, None, None, False)
            fs_lookup, axg, axga, fs_active = fs_cache[cache_key]

            stats = {}
            lambdas = {}
            for t in (h, a):
                ts = st(t)
                n = ts.hgn + ts.agn
                gf, ga = ts.hgf + ts.agf, ts.hga + ts.aga
                exp_gf = avg_h * ts.hgn + avg_a * ts.agn
                exp_ga = avg_a * ts.hgn + avg_h * ts.agn
                fb_att, fb_def = shrunk(gf, exp_gf, n), shrunk(ga, exp_ga, n)
                pure_att, pure_def = fb_att, fb_def
                if fs_active and isinstance(fs_lookup.get(t), dict):
                    rr = fs_lookup[t]
                    try:
                        fs_xg = float(rr.get("xG_avg")); fs_xga = float(rr.get("xGA_avg")); fs_n = rr.get("matches")
                        ok = np.isfinite(fs_xg) and np.isfinite(fs_xga) and fs_xg >= 0 and fs_xga >= 0 and float(fs_n) > 0
                    except Exception:
                        ok = False
                    if ok:
                        pure_att, pure_def = shrunk(fs_xg, axg, fs_n), shrunk(fs_xga, axga, fs_n)
                if not (np.isfinite(pure_att) and pure_att > 0): pure_att = 1.0
                if not (np.isfinite(pure_def) and pure_def > 0): pure_def = 1.0
                stats[t] = {"att": fb_att, "def": fb_def, "att0": fb_att, "def0": fb_def, "att0_pure": pure_att, "def0_pure": pure_def}
            m = two_heads(stats[h], stats[a], avg_h, avg_a)
            # Lambdas for total head are pure H/A products.
            lam_h = float(stats[h]["att0_pure"] * stats[a]["def0_pure"] * avg_h)
            lam_a = float(stats[a]["att0_pure"] * stats[h]["def0_pure"] * avg_a)
            key = (lg.name, season, h, a, row.Date)
            out[key] = {"p_over": float(1.0 - m["u25"]), "lambda_h": lam_h, "lambda_a": lam_a}
            tot_hg += fthg; tot_ag += ftag; tot_n += 1
            st(h).observe_home(fthg, ftag); st(a).observe_away(fthg, ftag)
    return out


def poisson_over_prob(lh: float, la: float) -> float:
    # P(total > 2.5) for independent Poisson, exact via total Poisson.
    mu = max(1e-9, lh + la)
    return float(1.0 - math.exp(-mu) * (1.0 + mu + mu * mu / 2.0))


def elo_probs_from_d(d: float) -> np.ndarray:
    p = elo_probs_from_ratings(1500.0 + float(d), 1500.0, 0.0)
    return np.array([p["1"], p["X"], p["2"]], dtype=float)


def event_matrix(events: List[Event], matches: Dict[str, Dict[int, Match]]) -> Dict[Tuple[str, int], Dict[str, Any]]:
    mat: Dict[Tuple[str, int], Dict[str, Any]] = defaultdict(lambda: {
        "home_high": 0, "away_high": 0,
        "home_att": 0, "away_att": 0,
        "home_defgk": 0, "away_defgk": 0,
        "events": []
    })
    for e in events:
        if not e.high60:
            continue
        m = matches[e.league].get(e.skipped_match_id)
        if not m:
            continue
        side = event_side(m, e.team)
        k = (e.league, e.skipped_match_id)
        mat[k]["events"].append(e)
        if side == "home":
            mat[k]["home_high"] += 1
            if e.role == "attaccante": mat[k]["home_att"] += 1
            if e.role in ("portiere", "difensore"): mat[k]["home_defgk"] += 1
        elif side == "away":
            mat[k]["away_high"] += 1
            if e.role == "attaccante": mat[k]["away_att"] += 1
            if e.role in ("portiere", "difensore"): mat[k]["away_defgk"] += 1
    return mat


def logloss_multinomial(p: np.ndarray, y: int) -> float:
    return -math.log(max(1e-12, float(p[y])))


def logloss_binary(p: float, y: int) -> float:
    p = min(max(float(p), 1e-12), 1 - 1e-12)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def bootstrap_significant(diffs: np.ndarray, homes: Sequence[str], aways: Sequence[str], rng: random.Random, reps: int = 200) -> bool:
    teams = sorted(set(homes) | set(aways))
    if len(teams) < 2 or len(diffs) == 0:
        return False
    by_team = {t: np.array([i for i, (h, a) in enumerate(zip(homes, aways)) if h == t or a == t], dtype=int) for t in teams}
    vals = []
    for _ in range(reps):
        idxs = []
        for t in rng.choices(teams, k=len(teams)):
            idxs.extend(by_team[t].tolist())
        if idxs:
            vals.append(float(np.mean(diffs[idxs])))
    if not vals:
        return False
    return float(np.percentile(vals, 5)) > 0.0


def power_1x2(elo_df: pd.DataFrame, mat: Dict[Tuple[str, int], Dict[str, Any]], matches_by_id) -> Tuple[List[dict], str, float]:
    rows = []
    for r in elo_df.itertuples(index=False):
        if str(r.season) not in {season_label(s) for s in ANALYSIS_SEASONS}:
            continue
        league = str(r.league)
        date = pd.to_datetime(r.data, utc=True)
        h = canonical_team_name(r.home_raw); a = canonical_team_name(r.away_raw)
        # find match by same league/date/home/away
        mid = None
        for m in matches_by_id[league].values():
            if m.season in ANALYSIS_SEASONS and m.home == h and m.away == a and m.kickoff.date() == date.date():
                mid = m.match_id; break
        if mid is None:
            continue
        ev = mat.get((league, mid), {})
        p0 = np.array([float(r.elo_1), float(r.elo_X), float(r.elo_2)])
        y = {"H": 0, "D": 1, "A": 2}.get(str(r.FTR).strip().upper())
        if y is None:
            continue
        rows.append({"league": league, "match_id": mid, "home": h, "away": a, "d": float(r.d_elo_diff), "p0": p0, "y": y,
                     "x": float(ev.get("away_high", 0) - ev.get("home_high", 0))})
    return simulate_power_A(rows)


def simulate_power_A(rows: List[dict]) -> Tuple[List[dict], str, float]:
    rng = random.Random(BOOTSTRAP_SEED)
    if not rows or not any(abs(r["x"]) > 0 for r in rows):
        return [], ">50", 1.0
    homes = [r["home"] for r in rows]; aways = [r["away"] for r in rows]
    deltas = [15, 30, 50]
    est_grid = np.linspace(-80, 80, 33)
    out = []
    for true_delta in deltas:
        sig = 0; sims = 80
        for _ in range(sims):
            ys = []
            for r in rows:
                p = elo_probs_from_d(r["d"] + true_delta * r["x"])
                ys.append(int(rng.choices([0, 1, 2], weights=p, k=1)[0]))
            best_delta, best_ll = 0.0, float("inf")
            for dg in est_grid:
                ll = 0.0
                for r, y in zip(rows, ys):
                    ll += logloss_multinomial(elo_probs_from_d(r["d"] + dg * r["x"]), y)
                if ll < best_ll:
                    best_ll, best_delta = ll, float(dg)
            diffs = np.array([logloss_multinomial(elo_probs_from_d(r["d"]), y) - logloss_multinomial(elo_probs_from_d(r["d"] + best_delta * r["x"]), y) for r, y in zip(rows, ys)])
            if bootstrap_significant(diffs, homes, aways, rng):
                sig += 1
        out.append({"delta": true_delta, "power": sig / sims})
    mde = next((str(x["delta"]) for x in out if x["power"] >= 0.80), ">50")
    ratio = posterior_prior_ratio_A(rows)
    return out, mde, ratio


def posterior_prior_ratio_A(rows: List[dict]) -> float:
    prior_sd = 30.0
    info = 0.0
    eps = 1.0
    for r in rows:
        if r["x"] == 0: continue
        p_plus = elo_probs_from_d(r["d"] + eps * r["x"])
        p_minus = elo_probs_from_d(r["d"] - eps * r["x"])
        dp = (p_plus - p_minus) / (2 * eps)
        p0 = np.maximum(elo_probs_from_d(r["d"]), 1e-9)
        info += float(np.sum((dp ** 2) / p0))
    post_sd = 1.0 / math.sqrt(1.0 / (prior_sd ** 2) + info) if info > 0 else prior_sd
    return post_sd / prior_sd


def build_ou_rows(matches_by_id, mat) -> List[dict]:
    ou = ou25_walkforward()
    rows = []
    for lg in LEAGUES:
        for m in matches_by_id[lg.name].values():
            if m.season not in ANALYSIS_SEASONS or m.home_goals is None or m.away_goals is None:
                continue
            # key by football-data date can differ in time; match by same date/home/away.
            candidates = [(k, v) for k, v in ou.items() if k[0] == lg.name and k[1] == m.season and k[2] == m.home and k[3] == m.away and k[4].date() == m.kickoff.date()]
            if not candidates:
                continue
            base = candidates[0][1]
            ev = mat.get((lg.name, m.match_id), {})
            y = int((int(m.home_goals) + int(m.away_goals)) > 2.5)
            rows.append({"league": lg.name, "match_id": m.match_id, "home": m.home, "away": m.away, "lh": base["lambda_h"], "la": base["lambda_a"], "p0": base["p_over"], "y": y,
                         "home_att": ev.get("home_att", 0), "away_att": ev.get("away_att", 0), "home_defgk": ev.get("home_defgk", 0), "away_defgk": ev.get("away_defgk", 0)})
    return rows


def adjusted_over(row: dict, delta: float) -> float:
    lh, la = float(row["lh"]), float(row["la"])
    lh *= math.exp(-delta * row["home_att"] + delta * row["away_defgk"])
    la *= math.exp(-delta * row["away_att"] + delta * row["home_defgk"])
    return poisson_over_prob(lh, la)


def simulate_power_B(rows: List[dict]) -> Tuple[List[dict], str, float]:
    rng = random.Random(BOOTSTRAP_SEED + 1)
    active = [r for r in rows if any(r[k] for k in ("home_att", "away_att", "home_defgk", "away_defgk"))]
    if not active:
        return [], ">0.15", 1.0
    homes = [r["home"] for r in rows]; aways = [r["away"] for r in rows]
    deltas = [0.05, 0.10, 0.15]
    est_grid = np.linspace(-0.20, 0.20, 41)
    out = []
    for true_delta in deltas:
        sig = 0; sims = 80
        for _ in range(sims):
            ys = [int(rng.random() < adjusted_over(r, true_delta)) for r in rows]
            best_delta, best_ll = 0.0, float("inf")
            for dg in est_grid:
                ll = sum(logloss_binary(adjusted_over(r, float(dg)), y) for r, y in zip(rows, ys))
                if ll < best_ll:
                    best_ll, best_delta = ll, float(dg)
            diffs = np.array([logloss_binary(r["p0"], y) - logloss_binary(adjusted_over(r, best_delta), y) for r, y in zip(rows, ys)])
            if bootstrap_significant(diffs, homes, aways, rng):
                sig += 1
        out.append({"delta": true_delta, "power": sig / sims})
    mde = next((f"{x['delta']:.2f}" for x in out if x["power"] >= 0.80), ">0.15")
    ratio = posterior_prior_ratio_B(rows)
    return out, mde, ratio


def posterior_prior_ratio_B(rows: List[dict]) -> float:
    prior_sd = 0.10
    eps = 0.002
    info = 0.0
    for r in rows:
        if not any(r[k] for k in ("home_att", "away_att", "home_defgk", "away_defgk")):
            continue
        p_plus = adjusted_over(r, eps); p_minus = adjusted_over(r, -eps)
        dp = (p_plus - p_minus) / (2 * eps)
        p0 = min(max(adjusted_over(r, 0.0), 1e-6), 1-1e-6)
        info += (dp * dp) / (p0 * (1 - p0))
    post_sd = 1.0 / math.sqrt(1.0 / (prior_sd ** 2) + info) if info > 0 else prior_sd
    return post_sd / prior_sd


# ---------------------- summaries/report ----------------------------------

def summarize_counts(events: List[Event]) -> Tuple[List[List[Any]], Dict[str, Any]]:
    rows = []
    total = defaultdict(int)
    for league in [l.name for l in LEAGUES]:
        for season in ANALYSIS_SEASONS:
            ev = [e for e in events if e.league == league and e.season == season]
            matches = {(e.league, e.skipped_match_id) for e in ev}
            high_matches = {(e.league, e.skipped_match_id) for e in ev if e.high60}
            high40_matches = {(e.league, e.skipped_match_id) for e in ev if e.high40}
            roles = Counter(e.role for e in ev)
            by_match = defaultdict(list)
            for e in ev: by_match[e.skipped_match_id].append(e)
            multi = sum(1 for xs in by_match.values() if len(xs) >= 2)
            both = 0
            for xs in by_match.values():
                teams = {x.team for x in xs}
                if len(teams) >= 2: both += 1
            teams = {e.team for e in ev}; players = {e.player_id for e in ev}
            rows.append([league, season_label(season), len(matches), len(high_matches), len(high40_matches), ", ".join(f"{r}:{roles.get(r,0)}" for r in ROLE_LABELS), multi, both, len(teams), len(players)])
            total["events"] += len(ev); total["matches"] += len(matches); total["high_matches"] += len(high_matches); total["high40_matches"] += len(high40_matches)
    return rows, total


def command_table(ctx: Dict[str, Any]) -> str:
    rows = [
        ["OK", "gh run list --workflow ppda_player_verify.yml", f"run recupero fresco {ctx.get('artifact_run_id')} workflow Verifica PPDA/deep/giocatore"],
        ["OK" if ctx.get("artifact_expired") is False else "NON OK", "gh api repos/iFelice/SoccerMath2.0/actions/runs/<run>/artifacts", f"artifact id={ctx.get('artifact_id')} name={ctx.get('artifact_name')} size={ctx.get('artifact_size')} created={ctx.get('artifact_created')} expires={ctx.get('artifact_expires')} expired={str(ctx.get('artifact_expired')).lower()}"] ,
        ["NON OK", "gh run download 34992936842 --name ppda-player-verify-34992936842", "no valid artifacts found to download; API run artifacts total_count=0 (artifact PR#23 non piu' presente)"] ,
        ["NON OK", "gh run download 37461010400 --name ppda-player-verify-37461010400", "sandbox: Azure blob productionresultssa1.blob.core.windows.net -> EOF; download riuscito dentro GitHub Actions per l'analisi"],
        ["NON OK", "python update_all_ppda_player_db.py ... (sandbox)", "sandbox: GitHub release asset TLS client e understat.com chiudono TLS (SSL_ERROR_SYSCALL/EOF); acquisizione reale riuscita nel runner Actions del run 37461010400"],
        ["OK", "python audit/squalifiche_feasibility.py --player-match-dir ...", "report generato su dati player_match recuperati dall'artifact fresco"],
    ]
    return md_table(["Esito", "Comando", "Evidenza"], rows)


def render_report(ctx: Dict[str, Any], coverage_rows, events: List[Event], ambiguous: List[dict], count_rows, validation_rows, powerA, mdeA, ratioA, powerB, mdeB, ratioB, source_info) -> str:
    lines = []
    ap = lines.append
    artifact_expires = ctx.get("artifact_expires")
    ap("# Fattibilita' feature squalifiche — eventi certi, validazione, conteggi, potenza")
    ap("")
    ap(f"**STATO ARTIFACT PLAYER_MATCH:** id `{ctx.get('artifact_id')}`, nome `{ctx.get('artifact_name')}` da run `{ctx.get('artifact_run_id')}`, dimensione compressa `{ctx.get('artifact_size')}` byte, creato `{ctx.get('artifact_created')}`, scadenza `{artifact_expires}`, expired=`{str(ctx.get('artifact_expired')).lower()}`. Scade entro 30 giorni rispetto al 2026-10-06: **SI**. Proposta non applicata: promuovere lo zip (~{ctx.get('artifact_size')} byte compresso) ad asset di release GitHub o storage oggetto esterno versionato, lasciando fuori git i JSON raw.")
    ap("")
    ap(f"Generato: `{dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()}` UTC. Commit base script: `{ctx.get('head')}`.")
    ap("")
    ap("## 0. Evidenze comandi")
    ap(command_table(ctx))
    ap("")
    ap("## 1. Inventario fonte player_match")
    ap(md_table(["Percorso/script", "Fonte", "Evidenza"], [
        ["update_all_ppda_player_db.py", "Understat via soccerdata==1.9.1", "usa soccerdata.Understat.read_player_match_stats(); campi minutes, position, yellow_cards, red_cards"],
        [".github/workflows/ppda_player_verify.yml", "workflow PR #23", "upload artifact ppda-player-verify-${{ github.run_id }} con reports/ e database/; retention-days: 14"],
        ["audit/ppda_deep_player_audit.py", "audit copertura", "referto storico 224902 righe giocatore nel run 34992936842"],
    ]))
    ap("")
    ap("### Copertura file recuperati")
    ap(md_table(["Lega", "File", "Byte", "Righe", "Partite distinte", "Stagioni", "Cartellini/minuti/ruolo"], coverage_rows))
    ap("")
    ap("Regole applicate: " + "; ".join(f"{k}: {v}" for k, v in RULES.items()))
    ap("")
    ap("Limiti dichiarati: rosso diretto certo contato solo quando `red_cards>0` e `yellow_cards==0`; casi red+yellow esclusi come ambigui; Ligue 1 usa dato league-only e dichiara coppe nazionali mancanti; nessuna ground truth ufficiale versionata, validazione minima presenza/assenza su player_match.")
    ap("")
    ap("## 2. Eventi certi ricostruiti")
    ev_by = Counter((e.league, e.season) for e in events)
    ap(md_table(["Lega", "Stagione", "Eventi certi", "High usage 60%", "High usage 40%", "Violazioni known_at<kickoff"], [[lg.name, season_label(s), ev_by.get((lg.name, s),0), sum(1 for e in events if e.league==lg.name and e.season==s and e.high60), sum(1 for e in events if e.league==lg.name and e.season==s and e.high40), sum(1 for e in events if e.league==lg.name and e.season==s and not (e.known_at < e.skipped_kickoff))] for lg in LEAGUES for s in ANALYSIS_SEASONS]))
    ap("")
    ap(f"Casi ambigui esclusi: **{len(ambiguous)}**. Prime righe: " + "; ".join(f"{a.get('league')} {a.get('season')} {a.get('player')} {a.get('reason')}" for a in ambiguous[:8]))
    ap("")
    ap("## 3. Validazione sorgente")
    ap(md_table(["Lega", "Candidati ricostruiti", "Violazioni: giocatore risulta in campo", "Precision minima presenza", "Recall"], validation_rows))
    ap(f"Candidati esclusi dai conteggi principali per violazione di validazione (il player_match mostra minuti nella partita da saltare): **{ctx.get('validation_excluded', 0)}**.")
    ap("")
    ap("## 4-5. Alto utilizzo e conteggi")
    ap("Alto utilizzo = minuti giocati >=60% dei 450 minuti disponibili nelle ultime 5 partite di campionato della squadra prima della partita saltata; sensibilita' 40% calcolata negli output macchina.")
    ap(md_table(["Lega", "Stagione", "Partite con >=1 squalificato", "Partite con >=1 high60", "Partite con >=1 high40", "Ruoli eventi", "Partite multi-assenti", "Da entrambe le parti", "Squadre", "Giocatori"], count_rows))
    ap("")
    ap("## 6. Potenza statistica")
    ap("A) 1X2: shock transitorio sul differenziale Elo `d_match=d+Δ_H−Δ_A`, qui Δ effettivo = `δ*(away_high-home_high)`. Stima δ via griglia e test ΔLogLoss appaiato con bootstrap a blocchi squadra.")
    ap(md_table(["δ vero", "Potenza α=5%"], [[x["delta"], fmt_pct(x["power"])] for x in powerA]))
    ap(f"MDE 80% A: `{mdeA}` punti Elo. Rapporto sd posterior/prior A: `{ratioA:.3f}`.")
    ap("")
    ap("B) Totali: shock log-lambda: attaccante assente -> lambda propria; portiere/difensore assente -> lambda avversaria. Centrocampisti esclusi dallo shock B e conteggiati nei ruoli.")
    ap(md_table(["δ vero", "Potenza α=5%"], [[x["delta"], fmt_pct(x["power"])] for x in powerB]))
    ap(f"MDE 80% B: `{mdeB}` log-lambda. Rapporto sd posterior/prior B: `{ratioB:.3f}`.")
    ap("")
    goA = (mdeA not in (">50", "n/d") and float(mdeA) <= 30 and ratioA <= 0.7)
    goB = (mdeB not in (">0.15", "n/d") and float(mdeB) <= 0.10 and ratioB <= 0.7)
    ap("## 7-8. Prior e verdetto")
    ap(md_table(["Punto", "Prior", "Regola GO", "MDE", "posterior/prior", "Verdetto"], [
        ["A 1X2", "N(0,30^2) Elo", "MDE<=30 e ratio<=0.7", mdeA, f"{ratioA:.3f}", "GO" if goA else "NO-GO"],
        ["B Totali", "N(0,0.10^2)", "MDE<=0.10 e ratio<=0.7", mdeB, f"{ratioB:.3f}", "GO" if goB else "NO-GO"],
    ]))
    ap("")
    if goA:
        ap("Se GO A: audit vero su iniezione Elo pre-match e metrica primaria LogLoss 1X2. Non eseguito qui.")
    if goB:
        ap("Se GO B: audit vero su log-lambda Totali e metrica primaria LogLoss Over/Under 2.5. Non eseguito qui.")
    if not (goA or goB):
        ap("Entrambi NO-GO: pista da mantenere in raccolta prospettica/validazione ground truth; non e' un effetto negativo.")
    ap("")
    ap("## Chiusura")
    ap("Report generato con dati player_match recuperati; il precedente report 'fonti assenti' e' sostituito.")
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--player-match-dir", default="audit/output/ppda-player-verify-37461010400/database")
    p.add_argument("--report", default="audit/results/squalifiche_feasibility.md")
    p.add_argument("--json", default="audit/output/squalifiche_feasibility_sources.json")
    p.add_argument("--artifact-run-id", default="37461010400")
    p.add_argument("--artifact-id", default="11415875090")
    p.add_argument("--artifact-name", default="ppda-player-verify-37461010400")
    p.add_argument("--artifact-size", default="10030865")
    p.add_argument("--artifact-created", default="2026-10-06T12:51:23Z")
    p.add_argument("--artifact-expires", default="2026-10-20T12:51:20Z")
    p.add_argument("--artifact-expired", default="false")
    args = p.parse_args(argv)

    head = run(["git", "rev-parse", "HEAD"])[1]
    ctx = {"head": head, "artifact_run_id": args.artifact_run_id, "artifact_id": args.artifact_id,
           "artifact_name": args.artifact_name, "artifact_size": args.artifact_size,
           "artifact_created": args.artifact_created, "artifact_expires": args.artifact_expires,
           "artifact_expired": args.artifact_expired.lower() == "true"}

    player_dir = (REPO_ROOT / args.player_match_dir).resolve()
    matches_by_id, by_league_season, by_team_season = load_matches()
    rows, player_index, rows_by_team_match, player_latest = load_player_rows(player_dir, matches_by_id)
    coverage_rows = []
    for lg in LEAGUES:
        path = player_dir / lg.player_file
        lg_rows = [r for r in rows if r["league"] == lg.name]
        coverage_rows.append([lg.name, rel(path), path.stat().st_size if path.exists() else 0, len(lg_rows), len({r["match_id"] for r in lg_rows}), ", ".join(map(str, sorted({r["season"] for r in lg_rows}))), "OK"])

    candidate_events, ambiguous = reconstruct_events(rows, matches_by_id, by_team_season, player_index)
    candidate_events = [e for e in candidate_events if e.season in ANALYSIS_SEASONS]
    validation_rows = []
    for lg in LEAGUES:
        ev = [e for e in candidate_events if e.league == lg.name]
        viol = sum(e.validation_played for e in ev)
        validation_rows.append([lg.name, len(ev), viol, fmt_pct((len(ev)-viol)/len(ev) if ev else None), "NON VERIFICABILE (ground truth ufficiale non versionata)"])
    events = [e for e in candidate_events if not e.validation_played]
    ctx["validation_excluded"] = len(candidate_events) - len(events)
    count_rows, totals = summarize_counts(events)

    mat = event_matrix(events, matches_by_id)
    elo_df = ensure_elo_table(REPO_ROOT / "audit/output/elo_walker_per_match.parquet")
    powerA, mdeA, ratioA = power_1x2(elo_df, mat, matches_by_id)
    ou_rows = build_ou_rows(matches_by_id, mat)
    powerB, mdeB, ratioB = simulate_power_B(ou_rows)

    source = {
        "coverage": coverage_rows,
        "events": [e.__dict__ for e in events],
        "ambiguous": ambiguous[:5000],
        "validation": validation_rows,
        "counts": count_rows,
        "powerA": powerA, "mdeA": mdeA, "ratioA": ratioA,
        "powerB": powerB, "mdeB": mdeB, "ratioB": ratioB,
        "artifact": ctx,
    }
    out_json = REPO_ROOT / args.json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(source, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    report = render_report(ctx, coverage_rows, events, ambiguous, count_rows, validation_rows, powerA, mdeA, ratioA, powerB, mdeB, ratioB, source)
    out_report = REPO_ROOT / args.report
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(report, encoding="utf-8")
    print(f"scritto {rel(out_report)}")
    print(f"eventi={len(events)} high60={sum(e.high60 for e in events)} ambiguous={len(ambiguous)}")
    print(f"A mde={mdeA} ratio={ratioA:.3f}; B mde={mdeB} ratio={ratioB:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
