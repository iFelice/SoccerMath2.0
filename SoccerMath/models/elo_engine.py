"""
models/elo_engine.py - Motore di Calcolo Elo Rating Dinamico per M4-analist
"""

import glob
import math
import os
from datetime import datetime
from typing import Dict, List

import numpy as np
import pandas as pd

from config import (
    DATABASE_DIR,
    DEFAULT_MARKET_VALUE,
    LEAGUES_CONFIG,
    LEAGUE_PREFIX_MAP,
    LEAGUE_HOME_ADVANTAGE,
    clean_name,
    get_market_values,
)
from scraper_xg import get_understat_xg

DEFAULT_INITIAL_RATING = 1500.0
HOME_ADVANTAGE = 65.0
BASE_K_FACTOR = 24.0


def calculate_goal_margin_multiplier(goal_diff: int) -> float:
    diff = abs(goal_diff)
    if diff <= 1:
        return 1.0
    elif diff == 2:
        return 1.5
    elif diff == 3:
        return 1.75
    else:
        return 1.75 + (diff - 3) / 8.0


class EloEngine:

    def __init__(self, league_name: str, home_adv: float = None, base_k: float = BASE_K_FACTOR):
        self.league_name = league_name
        self.home_adv = home_adv if home_adv is not None else LEAGUE_HOME_ADVANTAGE.get(league_name, HOME_ADVANTAGE)
        self.base_k = base_k
        self.ratings: Dict[str, float] = {}
        self.history: Dict[str, List[dict]] = {}
        self.team_stats: Dict[str, dict] = {}
        self.is_computed = False
        self.matches_df = pd.DataFrame()

    def _get_league_files(self) -> List[str]:
        prefix = LEAGUE_PREFIX_MAP.get(self.league_name)
        if not prefix:
            return []
        pattern_storici = str(DATABASE_DIR / f"{prefix}_20*.csv")
        file_live = str(DATABASE_DIR / f"{prefix}_Live.csv")
        file_base = str(DATABASE_DIR / f"{prefix}.csv")
        files = sorted(glob.glob(pattern_storici))
        if os.path.exists(file_base) and file_base not in files:
            files.append(file_base)
        if os.path.exists(file_live) and file_live not in files:
            files.append(file_live)
        return files

    def load_and_preprocess_matches(self) -> pd.DataFrame:
        files = self._get_league_files()
        if not files:
            return pd.DataFrame()
        dfs = []
        for f in files:
            try:
                df_tmp = pd.read_csv(f, on_bad_lines="skip", low_memory=False)
                if not df_tmp.empty and "HomeTeam" in df_tmp.columns and "AwayTeam" in df_tmp.columns:
                    dfs.append(df_tmp)
            except Exception:
                continue
        if not dfs:
            return pd.DataFrame()
        df = pd.concat(dfs, ignore_index=True)
        df = df.dropna(subset=["HomeTeam", "AwayTeam", "FTR"])
        df["HomeClean"] = df["HomeTeam"].apply(clean_name)
        df["AwayClean"] = df["AwayTeam"].apply(clean_name)
        df["Date_Parsed"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
        df = df.dropna(subset=["Date_Parsed"])
        df = df.drop_duplicates(subset=["Date_Parsed", "HomeClean", "AwayClean"], keep="last")
        df = df.sort_values("Date_Parsed").reset_index(drop=True)
        self.matches_df = df
        return df

    def compute_ratings(self) -> Dict[str, float]:
        df = self.load_and_preprocess_matches()
        if df.empty:
            self.is_computed = True
            return self.ratings
        all_teams = set(df["HomeClean"].unique()).union(set(df["AwayClean"].unique()))
        xg_data = get_understat_xg(self.league_name) or {}
        for team in all_teams:
            self.ratings[team] = DEFAULT_INITIAL_RATING
            self.history[team] = []
            self.team_stats[team] = {
                "matches": 0, "wins": 0, "draws": 0, "losses": 0,
                "goals_for": 0, "goals_against": 0,
                "peak_elo": DEFAULT_INITIAL_RATING, "min_elo": DEFAULT_INITIAL_RATING,
            }
        for idx, row in df.iterrows():
            h_team = row["HomeClean"]
            a_team = row["AwayClean"]
            ftr = str(row["FTR"]).strip().upper()
            fthg = row.get("FTHG")
            ftag = row.get("FTAG")
            try:
                fthg = int(fthg) if pd.notna(fthg) else 0
                ftag = int(ftag) if pd.notna(ftag) else 0
            except Exception:
                fthg, ftag = 0, 0

            r_h = self.ratings.get(h_team, DEFAULT_INITIAL_RATING)
            r_a = self.ratings.get(a_team, DEFAULT_INITIAL_RATING)

            if ftr == "H" or fthg > ftag:
                s_h, s_a = 1.0, 0.0
            elif ftr == "A" or ftag > fthg:
                s_h, s_a = 0.0, 1.0
            else:
                s_h, s_a = 0.5, 0.5

            margin = abs(fthg - ftag)
            margin_mult = calculate_goal_margin_multiplier(margin)

            xg_adj = 0.0
            if xg_data and h_team in xg_data and a_team in xg_data:
                h_xg = xg_data[h_team].get("xG_avg", 1.3)
                a_xg = xg_data[a_team].get("xGA_avg", 1.3)
                xg_adj = (h_xg - a_xg) * 0.15

            xg_elo_boost = max(-100, min(100, xg_adj * 400))
            dr = r_h + self.home_adv - r_a + xg_elo_boost
            expected_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
            expected_a = 1.0 - expected_h

            k_eff = self.base_k * margin_mult
            delta_h = k_eff * (s_h - expected_h)
            delta_a = k_eff * (s_a - expected_a)
            new_r_h = r_h + delta_h
            new_r_a = r_a + delta_a
            self.ratings[h_team] = new_r_h
            self.ratings[a_team] = new_r_a

            st_h = self.team_stats[h_team]
            st_a = self.team_stats[a_team]
            st_h["matches"] += 1
            st_a["matches"] += 1
            st_h["goals_for"] += fthg
            st_h["goals_against"] += ftag
            st_a["goals_for"] += ftag
            st_a["goals_against"] += fthg
            if s_h == 1.0:
                st_h["wins"] += 1
                st_a["losses"] += 1
            elif s_h == 0.0:
                st_h["losses"] += 1
                st_a["wins"] += 1
            else:
                st_h["draws"] += 1
                st_a["draws"] += 1
            st_h["peak_elo"] = max(st_h["peak_elo"], new_r_h)
            st_h["min_elo"] = min(st_h["min_elo"], new_r_h)
            st_a["peak_elo"] = max(st_a["peak_elo"], new_r_a)
            st_a["min_elo"] = min(st_a["min_elo"], new_r_a)

            date_val = row["Date_Parsed"]
            self.history[h_team].append({
                "date": date_val, "opponent": a_team, "is_home": True,
                "score": f"{fthg}-{ftag}",
                "result": "V" if s_h == 1.0 else ("P" if s_h == 0.0 else "X"),
                "elo_before": r_h, "elo_after": new_r_h, "delta": delta_h
            })
            self.history[a_team].append({
                "date": date_val, "opponent": h_team, "is_home": False,
                "score": f"{ftag}-{fthg}",
                "result": "V" if s_a == 1.0 else ("P" if s_a == 0.0 else "X"),
                "elo_before": r_a, "elo_after": new_r_a, "delta": delta_a
            })
        self.is_computed = True
        return self.ratings

    def get_leaderboard(self) -> pd.DataFrame:
        if not self.is_computed:
            self.compute_ratings()
        rows = []
        for team, rating in self.ratings.items():
            stats = self.team_stats.get(team, {})
            hist = self.history.get(team, [])
            last_5 = hist[-5:] if hist else []
            last_5_delta = sum(m["delta"] for m in last_5) if last_5 else 0.0
            last_5_form = "".join([m["result"] for m in last_5]) if last_5 else "—"
            rows.append({
                "Squadra": team, "Elo Rating": round(rating, 1),
                "PG": stats.get("matches", 0), "V": stats.get("wins", 0),
                "N": stats.get("draws", 0), "P": stats.get("losses", 0),
                "GF": stats.get("goals_for", 0), "GS": stats.get("goals_against", 0),
                "DR": stats.get("goals_for", 0) - stats.get("goals_against", 0),
                "Delta 5G": round(last_5_delta, 1), "Forma 5G": last_5_form,
                "Peak Elo": round(stats.get("peak_elo", rating), 1),
            })
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("Elo Rating", ascending=False).reset_index(drop=True)
            df.index = df.index + 1
            df.index.name = "Rank"
        return df


_ELO_ENGINES_CACHE: Dict[str, EloEngine] = {}


def get_elo_engine(league_name: str) -> EloEngine:
    if league_name not in _ELO_ENGINES_CACHE:
        engine = EloEngine(league_name)
        engine.compute_ratings()
        _ELO_ENGINES_CACHE[league_name] = engine
    return _ELO_ENGINES_CACHE[league_name]


def get_current_elo(league_name: str) -> Dict[str, float]:
    engine = get_elo_engine(league_name)
    return {team: round(score, 1) for team, score in engine.ratings.items()}


def get_elo_leaderboard(league_name: str) -> pd.DataFrame:
    engine = get_elo_engine(league_name)
    return engine.get_leaderboard()


def predict_elo_probs(home_team: str, away_team: str, league_name: str) -> dict:
    engine = get_elo_engine(league_name)
    h_cl = clean_name(home_team)
    a_cl = clean_name(away_team)
    r_h = engine.ratings.get(h_cl, DEFAULT_INITIAL_RATING)
    r_a = engine.ratings.get(a_cl, DEFAULT_INITIAL_RATING)
    dr = r_h + engine.home_adv - r_a
    e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
    e_a = 1.0 - e_h
    p_draw = 0.27 * math.exp(-((dr / 320.0) ** 2))
    p_draw = max(0.06, min(0.34, p_draw))
    p_home = (1.0 - p_draw) * e_h
    p_away = (1.0 - p_draw) * e_a
    total = p_home + p_draw + p_away
    return {
        "1": round(p_home / total, 4),
        "X": round(p_draw / total, 4),
        "2": round(p_away / total, 4),
        "elo_home": round(r_h, 1), "elo_away": round(r_a, 1),
        "elo_diff": round(dr, 1), "home_adv": engine.home_adv,
        "expected_score_home": round(e_h, 4), "expected_score_away": round(e_a, 4),
    }


def get_team_elo_history(team_name: str, league_name: str) -> pd.DataFrame:
    engine = get_elo_engine(league_name)
    t_cl = clean_name(team_name)
    hist = engine.history.get(t_cl, [])
    if not hist:
        return pd.DataFrame()
    return pd.DataFrame(hist)
