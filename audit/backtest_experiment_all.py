"""
backtest_experiment_all.py — Esperimento controllato: SoccerMath ha un edge storico sulle 5 leghe?

Replica IDENTICA della logica di backtest_experiment.py (Serie A) estesa alle altre
4 leghe. Non tocca app.py, config.py, ne' i motori Poisson/Elo/Dixon-Coles esistenti.
Replica la STESSA logica di run_historical_backtest() (walk-forward, no leakage) ma:
  - usa confini di stagione reali invece di una finestra fissa di N partite
  - registra probabilita' + quote pre-match + de-vig, non solo vinto/perso
  - calcola Brier Score / Log Loss (models/backtest.py, finora mai usate)
  - simula ROI con quota REALE (non de-vigata) e stake flat

L'unica cosa che cambia rispetto a backtest_experiment.py (Serie A) e':
  - il prefisso dei file CSV (SerieA_* -> Premier_* / LaLiga_* / Bundesliga_* / Ligue1_*)
  - il nome lega passato a LEAGUE_HOME_ADVANTAGE.get()

Split temporale (identico a Serie A):
  2022/23 + 2023/24  -> training puro (nessuna predizione registrata)
  2024/25            -> validation
  2025/26            -> test finale storico
  2026/27 (Live)     -> monitoraggio live (poche partite, solo osservativo)
"""
import os
import sys
import json
import math
import numpy as np
import pandas as pd
from scipy.stats import poisson as scipy_poisson

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)          # .../SoccerMath2.0
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))
from config import clean_name, LEAGUE_HOME_ADVANTAGE  # motore invariato, solo lettura

DB = os.path.join(_REPO_ROOT, "SoccerMath", "database")
STAKE = 10.0
EDGE_MIN = 0.0  # soglia sperimentale: bet se edge > 0. Non e' una soglia dell'app.

ODDS_COLS = ["B365H", "B365D", "B365A", "AvgH", "AvgD", "AvgA",
             "B365>2.5", "B365<2.5", "Avg>2.5", "Avg<2.5"]
REQUIRED = ["Date", "HomeTeam", "AwayTeam", "FTR", "FTHG", "FTAG"]

# (prefisso file CSV, chiave in LEAGUE_HOME_ADVANTAGE)
LEAGUES = [
    ("SerieA", "Serie A"),
    ("Premier", "Premier League"),
    ("LaLiga", "La Liga"),
    ("Bundesliga", "Bundesliga"),
    ("Ligue1", "Ligue 1"),
]

# file xG per lega (stessa fonte di models/elo_engine.py via scraper_xg.get_understat_xg)
XG_FILES = {
    "Serie A": "xg_serie_a.json",
    "Premier League": "xg_premier_league.json",
    "La Liga": "xg_la_liga.json",
    "Bundesliga": "xg_bundesliga.json",
    "Ligue 1": "xg_ligue_1.json",
}


def load_league(prefix):
    files = {
        "2022/23": f"{DB}/{prefix}_2022.csv",
        "2023/24": f"{DB}/{prefix}_2023.csv",
        "2024/25": f"{DB}/{prefix}_2024.csv",
        "2025/26": f"{DB}/{prefix}_2025.csv",
        "2026/27": f"{DB}/{prefix}_Live.csv",
    }
    dfs = []
    for season, path in files.items():
        df = pd.read_csv(path, on_bad_lines="warn", low_memory=False)
        cols = REQUIRED + [c for c in ODDS_COLS if c in df.columns]
        df = df[cols].copy()
        for c in ODDS_COLS:
            if c not in df.columns:
                df[c] = np.nan
        df["season"] = season
        dfs.append(df)
    df = pd.concat(dfs, ignore_index=True)
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df["FTHG"] = pd.to_numeric(df["FTHG"], errors="coerce")
    df["FTAG"] = pd.to_numeric(df["FTAG"], errors="coerce")
    df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTR", "FTHG", "FTAG"])
    df = df.sort_values("Date", kind="stable").reset_index(drop=True)
    df["HomeClean"] = df["HomeTeam"].apply(clean_name)
    df["AwayClean"] = df["AwayTeam"].apply(clean_name)
    df = df.drop_duplicates(subset=["Date", "HomeClean", "AwayClean"], keep="last").reset_index(drop=True)
    return df


def get_full_poisson(h_e, a_e, max_goals=15):
    h_p = [scipy_poisson.pmf(i, h_e) for i in range(max_goals)]
    a_p = [scipy_poisson.pmf(i, a_e) for i in range(max_goals)]
    matrix = np.outer(h_p, a_p)
    u25 = sum(matrix[i, j] for i in range(max_goals) for j in range(max_goals) if i + j < 2.5)
    return {
        "1": float(np.sum(np.tril(matrix, -1))),
        "X": float(np.sum(np.diag(matrix))),
        "2": float(np.sum(np.triu(matrix, 1))),
        "u25": float(u25),
        "gg": float((1 - h_p[0]) * (1 - a_p[0])),
    }


def devig_1x2(oh, od, oa):
    if any(pd.isna(x) or x <= 1.0 for x in (oh, od, oa)):
        return None, None, None
    ih, idr, ia = 1 / oh, 1 / od, 1 / oa
    tot = ih + idr + ia
    return ih / tot, idr / tot, ia / tot


def devig_2way(o_over, o_under):
    if any(pd.isna(x) or x <= 1.0 for x in (o_over, o_under)):
        return None, None
    io, iu = 1 / o_over, 1 / o_under
    tot = io + iu
    return io / tot, iu / tot


def run_walkforward(df, camp_key="Serie A", min_train_seasons=("2022/23", "2023/24")):
    home_adv = LEAGUE_HOME_ADVANTAGE.get(camp_key, 65.0)
    train_cutoff = df[df["season"].isin(min_train_seasons)]["Date"].max()
    rows = []
    elo_ratings = {}
    elo_ratings_fix = {}   # Elo parallelo con formula xG corretta (xg_adj_fix)

    # Carica xG per la lega (stessa fonte JSON di models/elo_engine.py). Nessun
    # accesso al motore: solo lettura del dato grezzo, formattato {nome: {xG_avg, xGA_avg}}.
    xg_data = {}
    xg_file = os.path.join(DB, XG_FILES.get(camp_key, ""))
    if os.path.exists(xg_file):
        with open(xg_file, "r", encoding="utf-8") as f:
            xg_data = json.load(f) or {}

    # Elo va costruito incrementalmente in ordine cronologico su TUTTO lo storico
    # (identico a run_historical_backtest: ricalcolato di riga in riga, mai sul futuro)
    for idx, row in df.iterrows():
        h, a = row.HomeClean, row.AwayClean
        ftr = str(row.FTR).strip().upper()
        r_h = elo_ratings.get(h, 1500.0)
        r_a = elo_ratings.get(a, 1500.0)
        rf_h = elo_ratings_fix.get(h, 1500.0)
        rf_a = elo_ratings_fix.get(a, 1500.0)

        # --- xG: formula corretta da testare in parallelo (solo dentro lo script) ---
        # h_xg   = attacco casa (xG_avg)
        # h_xga  = difesa casa (xGA_avg)
        # a_xg   = attacco ospite
        # a_xga  = difesa ospite
        # xg_adj_fix = ((att_h - dif_h) - (att_a - dif_a)) * 0.15
        # (la produzione usa xg_adj = (h_xg - a_xga) * 0.15, strutturalmente asimmetrica)
        xg_h = xg_data.get(h, {})
        xg_a = xg_data.get(a, {})
        h_xg = xg_h.get("xG_avg", 1.3)
        h_xga = xg_h.get("xGA_avg", 1.3)
        a_xg = xg_a.get("xG_avg", 1.3)
        a_xga = xg_a.get("xGA_avg", 1.3)
        xg_adj_fix = ((h_xg - h_xga) - (a_xg - a_xga)) * 0.15
        xg_boost_fix = max(-100.0, min(100.0, xg_adj_fix * 400.0))  # stesso boost dell'engine
        dr_fix = rf_h + home_adv - rf_a + xg_boost_fix
        e_h_fix = 1.0 / (1.0 + 10.0 ** (-dr_fix / 400.0))

        if row.Date > train_cutoff:
            train = df.iloc[:idx]
            avg_h = max(float(train["FTHG"].mean()), 0.1)
            avg_a = max(float(train["FTAG"].mean()), 0.1)
            home_gf = train.groupby("HomeClean")["FTHG"].mean()
            home_ga = train.groupby("HomeClean")["FTAG"].mean()
            away_gf = train.groupby("AwayClean")["FTAG"].mean()
            away_ga = train.groupby("AwayClean")["FTHG"].mean()

            def stat(t):
                att_h = home_gf[t] if t in home_gf.index else avg_h
                def_h = home_ga[t] if t in home_ga.index else avg_a
                att_a = away_gf[t] if t in away_gf.index else avg_a
                def_a = away_ga[t] if t in away_ga.index else avg_h
                return {"att": (att_h / avg_h + att_a / avg_a) / 2,
                        "def": (def_h / avg_a + def_a / avg_h) / 2}

            hs, as_ = stat(h), stat(a)
            m_p = get_full_poisson(hs["att"] * as_["def"] * avg_h, as_["att"] * hs["def"] * avg_a)

            dr = r_h + home_adv - r_a
            e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
            p_draw = max(0.06, min(0.34, 0.27 * math.exp(-((dr / 320.0) ** 2))))
            elo_p = {"1": (1 - p_draw) * e_h, "X": p_draw, "2": (1 - p_draw) * (1 - e_h)}

            sm_p = {k: 0.6 * m_p[k] + 0.4 * elo_p[k] for k in ("1", "X", "2")}  # ensemble app attuale

            # Elo parallelo con formula xG corretta (stesso K-factor 24, stesso home advantage)
            p_draw_fix = max(0.06, min(0.34, 0.27 * math.exp(-((dr_fix / 320.0) ** 2))))
            elo_fix_p = {"1": (1 - p_draw_fix) * e_h_fix, "X": p_draw_fix, "2": (1 - p_draw_fix) * (1 - e_h_fix)}
            sm_fix_p = {k: 0.6 * m_p[k] + 0.4 * elo_fix_p[k] for k in ("1", "X", "2")}  # ensemble con Elo xG-fix

            fair_b365 = devig_1x2(row.B365H, row.B365D, row.B365A)
            fair_avg = devig_1x2(row.AvgH, row.AvgD, row.AvgA)
            fair_uo_b365 = devig_2way(row["B365>2.5"], row["B365<2.5"])
            fair_uo_avg = devig_2way(row["Avg>2.5"], row["Avg<2.5"])

            real_1x2 = {"H": "1", "D": "X", "A": "2"}.get(ftr, "X")
            tot_goals = row.FTHG + row.FTAG
            real_uo = "OVER" if tot_goals > 2.5 else "UNDER"
            real_gg = "GG" if row.FTHG > 0 and row.FTAG > 0 else "NG"

            rows.append({
                "date": row.Date, "season": row.season, "home": h, "away": a,
                "real_1x2": real_1x2, "real_uo": real_uo, "real_gg": real_gg,
                "poisson_1": m_p["1"], "poisson_X": m_p["X"], "poisson_2": m_p["2"],
                "poisson_o25": 1 - m_p["u25"], "poisson_gg": m_p["gg"],
                "elo_1": elo_p["1"], "elo_X": elo_p["X"], "elo_2": elo_p["2"],
                "sm_1": sm_p["1"], "sm_X": sm_p["X"], "sm_2": sm_p["2"],
                "elo_fix_1": elo_fix_p["1"], "elo_fix_X": elo_fix_p["X"], "elo_fix_2": elo_fix_p["2"],
                "smfix_1": sm_fix_p["1"], "smfix_X": sm_fix_p["X"], "smfix_2": sm_fix_p["2"],
                "B365H": row.B365H, "B365D": row.B365D, "B365A": row.B365A,
                "AvgH": row.AvgH, "AvgD": row.AvgD, "AvgA": row.AvgA,
                "B365_o25": row["B365>2.5"], "B365_u25": row["B365<2.5"],
                "Avg_o25": row["Avg>2.5"], "Avg_u25": row["Avg<2.5"],
                "fair_b365_1": fair_b365[0] if fair_b365 else np.nan,
                "fair_b365_X": fair_b365[1] if fair_b365 else np.nan,
                "fair_b365_2": fair_b365[2] if fair_b365 else np.nan,
                "fair_avg_1": fair_avg[0] if fair_avg else np.nan,
                "fair_avg_X": fair_avg[1] if fair_avg else np.nan,
                "fair_avg_2": fair_avg[2] if fair_avg else np.nan,
                "fair_b365_o25": fair_uo_b365[0] if fair_uo_b365 else np.nan,
                "fair_b365_u25": fair_uo_b365[1] if fair_uo_b365 else np.nan,
                "fair_avg_o25": fair_uo_avg[0] if fair_uo_avg else np.nan,
                "fair_avg_u25": fair_uo_avg[1] if fair_uo_avg else np.nan,
            })

        s_h = 1.0 if ftr == "H" else (0.0 if ftr == "A" else 0.5)
        dr = r_h + home_adv - r_a
        e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
        k = 24.0
        elo_ratings[h] = r_h + k * (s_h - e_h)
        elo_ratings[a] = r_a + k * ((1 - s_h) - (1 - e_h))

        # Elo parallelo (xG fix): stesso K-factor, stesso home advantage
        elo_ratings_fix[h] = rf_h + k * (s_h - e_h_fix)
        elo_ratings_fix[a] = rf_a + k * ((1 - s_h) - (1 - e_h_fix))

    return pd.DataFrame(rows)
