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
            st_h["
