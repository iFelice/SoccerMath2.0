"""
xg_rolling_walkforward.py — Confronto xG ROLLING (media ultime 5 partite) vs xG STAGIONALE
nel calcolo Elo, walk-forward sulle 5 leghe (stesso split di backtest_experiment_all.py).

Punto di partenza (già validato in precedenza):
  - backtest_experiment_all.py::run_walkforward calcola "elo_fix"/"smfix" usando xG_avg/xGA_avg
    STAGIONALI (da database/xg_<lega>.json, costanti per squadra) con la formula xG-fix di
    produzione (simmetrica, *0.15) già implementata in models/elo_engine.py.
  - Questo script NON modifica models/, app.py, config.py né i file esistenti: importa in
    sola lettura load_league/get_full_poisson/devig_1x2/market_factor/LEAGUES da
    backtest_experiment_all.py e re-implementa SOLO la parte Elo con xG rolling.

Cosa fa:
  Per ogni lega costruisce lo storico per-partita di xG/xGA da "database/xG archivio <lega>.json"
  (fonte Understat, stagioni 2024/25 in avanti) allineato ai nomi CSV/app via clean_name + una
  traduzione esplicita per le leghe con convenzioni di nome diverse (La Liga, Bundesliga, Ligue 1).
  Poi, nello stesso giro walk-forward cronologico e no-leakage, calcola DUE Elo paralleli:
    - Elo stagionale (elo_fix): usa xG_avg/xGA_avg costanti per squadra (baseline, come produzione)
    - Elo rolling (elo_roll): usa la media degli ultimi <=5 xG/xGA GIOCATI dalla squadra prima
      della partita corrente (no-leakage). Se la squadra non ha ancora match nel dataset
      per-partita, fallback a xG_avg/xGA_avg stagionale.
  E i rispettivi ensemble 0.6*Poisson + 0.4*Elo (smfix stagionale, sm_roll rolling).

Output per lega, per stagione (validation 2024/25 e test 2025/26):
  - Brier / LogLoss / ROI (vs B365, edge 1X2) per: Elo stagionale, Elo rolling,
    ensemble stagionale, ensemble rolling.
  - Niente commenti interpretativi: solo numeri.

Uso:
  .venv-audit/bin/python audit/xg_rolling_walkforward.py > audit/xg_rolling_walkforward_results.txt
"""
import os
import sys
import json
import math
import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from config import clean_name, LEAGUE_HOME_ADVANTAGE  # sola lettura
from backtest_experiment_all import (load_league, get_full_poisson, devig_1x2,
                                     market_factor, LEAGUES)

DB = os.path.join(_REPO_ROOT, "SoccerMath", "database")

# File archivio per-partita (nuova fonte, da main) per ciascuna lega
ARCHIVE_FILES = {
    "Serie A": "xG archivio serie A.json",
    "Premier League": "xG archivio premier league.json",
    "La Liga": "xG archivio la liga.json",
    "Bundesliga": "xG archivio bundesliga.json",
    "Ligue 1": "xG archivio ligue 1.json",
}

# File xG stagionale (baseline, costanti per squadra) — stessa fonte di models/elo_engine.py
XG_FILES = {
    "Serie A": "xg_serie_a.json",
    "Premier League": "xg_premier_league.json",
    "La Liga": "xg_la_liga.json",
    "Bundesliga": "xg_bundesliga.json",
    "Ligue 1": "xg_ligue_1.json",
}

# Traduzione nome Understat (raw, da archivio) -> nome pulito CSV/app (clean_name).
# Serie A e Premier coincidono via clean_name; per La Liga/Bundesliga/Ligue 1 le
# convenzioni di nome differiscono tra Understat e football-data, quindi mappatura esplicita.
NAME_TRANSLATE = {
    "La Liga": {
        "Athletic Club": "Ath Bilbao", "Atletico Madrid": "Ath Madrid",
        "Celta Vigo": "Celta", "Espanyol": "Espanol", "Real Betis": "Betis",
        "Real Sociedad": "Sociedad", "Real Valladolid": "Valladolid",
        "Rayo Vallecano": "Vallecano", "Real Oviedo": "Oviedo",
        # Deportivo La Coruna / Malaga / Racing Santander / Elche / Levante / Las Palmas:
        # presenti in archivio (stagioni diverse) ma non nel CSV testato -> si ignora il match.
    },
    "Bundesliga": {
        "Bayer Leverkusen": "Leverkusen", "Bayern Munich": "Bayern",
        "Borussia Dortmund": "Dortmund", "Borussia M.Gladbach": "M'gladbach",
        "Eintracht Frankfurt": "Ein Frankfurt", "FC Cologne": "Koln",
        "FC Heidenheim": "Heidenheim", "Hamburger SV": "Hamburg",
        "Mainz 05": "Mainz", "RasenBallsport Leipzig": "Leipzig",
        "St. Pauli": "St Pauli", "VfB Stuttgart": "Stuttgart",
    },
    "Ligue 1": {
        "Paris Saint Germain": "PSG", "Saint-Etienne": "St Etienne",
    },
}

K_ROLLING = 5  # finestra mobile: media ultime 5 partite


def trans_name(league, raw):
    t = NAME_TRANSLATE.get(league, {}).get(raw)
    return clean_name(t) if t else clean_name(raw)


def load_archive(league):
    """Ritorna {squadra: DataFrame(ts, xg_for, xg_against)} dall'archivio per-partita.
    xg_for  = xG segnato dalla squadra in quel match (come casa o trasferta)
    xg_against = xG subito dalla squadra in quel match
    Solo partite giocate (is_result). Ordinati per data.
    """
    path = os.path.join(DB, ARCHIVE_FILES[league])
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    teams = {}
    for m in data:
        if not m.get("is_result"):
            continue
        ts = pd.to_datetime(m["date"], errors="coerce")
        if pd.isna(ts):
            continue
        h = trans_name(league, m["home_team"])
        a = trans_name(league, m["away_team"])
        home_xg = float(m["home_xg"])
        away_xg = float(m["away_xg"])
        for team, xg_for, xg_against in ((h, home_xg, away_xg), (a, away_xg, home_xg)):
            teams.setdefault(team, []).append((ts, xg_for, xg_against))
    out = {}
    for team, rows in teams.items():
        df = pd.DataFrame(rows, columns=["ts", "xg_for", "xg_against"]).sort_values("ts")
        out[team] = df
    return out


def load_seasonal_xg(league):
    """xG_avg/xGA_avg stagionali (baseline), da database/xg_<lega>.json."""
    path = os.path.join(DB, XG_FILES[league])
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f) or {}


def rolling_xg(team_df, before_ts, k=K_ROLLING):
    """Media degli ultimi <=k match GIOCATI (ts < before_ts) per xg_for e xg_against.
    Ritorna (xg_for_mean, xg_against_mean). Se nessun match precedente -> None."""
    if team_df is None or team_df.empty or "ts" not in team_df.columns:
        return None
    prior = team_df[team_df["ts"] < before_ts]
    if prior.empty:
        return None
    tail = prior.tail(k)
    return tail["xg_for"].mean(), tail["xg_against"].mean()


def run_walkforward_rolling(df_all, league, home_adv, seasonal_xg, archive):
    """Stesso giro walk-forward di backtest_experiment_all.py ma con due Elo paralleli:
    stagionale (xG_avg) e rolling (media ultime 5). Produce righe con le prob. 1X2 di entrambi.
    Nessun leakage: l'Elo e' costruito riga per riga in ordine cronologico, e il rolling
    usa solo match con data < quella corrente."""
    train_cutoff = df_all[df_all["season"].isin(("2022/23", "2023/24"))]["Date"].max()
    rows = []
    elo_fix = {}   # Elo stagionale
    elo_roll = {}  # Elo rolling

    for idx, row in df_all.iterrows():
        h, a = row.HomeClean, row.AwayClean
        ftr = str(row.FTR).strip().upper()
        r_fix_h = elo_fix.get(h, 1500.0)
        r_fix_a = elo_fix.get(a, 1500.0)
        r_roll_h = elo_roll.get(h, 1500.0)
        r_roll_a = elo_roll.get(a, 1500.0)

        # --- xG stagionale (baseline) ---
        sgh = seasonal_xg.get(h, {})
        sga = seasonal_xg.get(a, {})
        h_xg_s = sgh.get("xG_avg", 1.3)
        h_xga_s = sgh.get("xGA_avg", 1.3)
        a_xg_s = sga.get("xG_avg", 1.3)
        a_xga_s = sga.get("xGA_avg", 1.3)
        xg_adj_fix = ((h_xg_s - h_xga_s) - (a_xg_s - a_xga_s)) * 0.15
        xg_boost_fix = max(-100.0, min(100.0, xg_adj_fix * 400.0))
        dr_fix = r_fix_h + home_adv - r_fix_a + xg_boost_fix
        e_h_fix = 1.0 / (1.0 + 10.0 ** (-dr_fix / 400.0))

        # --- xG rolling (media ultime 5 giocate, no-leakage) ---
        rh = rolling_xg(archive.get(h, pd.DataFrame()), row.Date)
        ra = rolling_xg(archive.get(a, pd.DataFrame()), row.Date)
        if rh is None:
            h_xg_r, h_xga_r = h_xg_s, h_xga_s
        else:
            h_xg_r, h_xga_r = rh
        if ra is None:
            a_xg_r, a_xga_r = a_xg_s, a_xga_s
        else:
            a_xg_r, a_xga_r = ra
        xg_adj_roll = ((h_xg_r - h_xga_r) - (a_xg_r - a_xga_r)) * 0.15
        xg_boost_roll = max(-100.0, min(100.0, xg_adj_roll * 400.0))
        dr_roll = r_roll_h + home_adv - r_roll_a + xg_boost_roll
        e_h_roll = 1.0 / (1.0 + 10.0 ** (-dr_roll / 400.0))

        if row.Date > train_cutoff:
            train = df_all.iloc[:idx]
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

            # ensemble Elo stagionale
            p_draw_fix = max(0.06, min(0.34, 0.27 * math.exp(-((dr_fix / 320.0) ** 2))))
            elo_fix_p = {"1": (1 - p_draw_fix) * e_h_fix, "X": p_draw_fix,
                         "2": (1 - p_draw_fix) * (1 - e_h_fix)}
            sm_fix_p = {k: 0.6 * m_p[k] + 0.4 * elo_fix_p[k] for k in ("1", "X", "2")}

            # ensemble Elo rolling
            p_draw_roll = max(0.06, min(0.34, 0.27 * math.exp(-((dr_roll / 320.0) ** 2))))
            elo_roll_p = {"1": (1 - p_draw_roll) * e_h_roll, "X": p_draw_roll,
                          "2": (1 - p_draw_roll) * (1 - e_h_roll)}
            sm_roll_p = {k: 0.6 * m_p[k] + 0.4 * elo_roll_p[k] for k in ("1", "X", "2")}

            fair = devig_1x2(row.B365H, row.B365D, row.B365A)
            real_1x2 = {"H": "1", "D": "X", "A": "2"}.get(ftr, "X")

            rows.append({
                "date": row.Date, "season": row.season, "real_1x2": real_1x2,
                "elo_fix_1": elo_fix_p["1"], "elo_fix_X": elo_fix_p["X"], "elo_fix_2": elo_fix_p["2"],
                "elo_roll_1": elo_roll_p["1"], "elo_roll_X": elo_roll_p["X"], "elo_roll_2": elo_roll_p["2"],
                "sm_fix_1": sm_fix_p["1"], "sm_fix_X": sm_fix_p["X"], "sm_fix_2": sm_fix_p["2"],
                "sm_roll_1": sm_roll_p["1"], "sm_roll_X": sm_roll_p["X"], "sm_roll_2": sm_roll_p["2"],
                "B365H": row.B365H, "B365D": row.B365D, "B365A": row.B365A,
                "fair_b365_1": fair[0] if fair else np.nan,
                "fair_b365_X": fair[1] if fair else np.nan,
                "fair_b365_2": fair[2] if fair else np.nan,
            })

        # --- aggiornamento Elo paralleli (stesso K=24, stesso home_adv) ---
        s_h = 1.0 if ftr == "H" else (0.0 if ftr == "A" else 0.5)
        k = 24.0
        elo_fix[h] = r_fix_h + k * (s_h - e_h_fix)
        elo_fix[a] = r_fix_a + k * ((1 - s_h) - (1 - e_h_fix))
        elo_roll[h] = r_roll_h + k * (s_h - e_h_roll)
        elo_roll[a] = r_roll_a + k * ((1 - s_h) - (1 - e_h_roll))

    return pd.DataFrame(rows)


def onehot_1x2(real_series):
    m = {"1": [1, 0, 0], "X": [0, 1, 0], "2": [0, 0, 1]}
    return np.array([m[r] for r in real_series])


def brier_ll(df, prob_cols):
    df = df.dropna(subset=list(prob_cols))
    y = onehot_1x2(df["real_1x2"])
    p = df[list(prob_cols)].to_numpy(dtype=float)
    brier = np.mean(np.sum((y - p) ** 2, axis=1))
    eps = 1e-15
    pc = np.clip(p, eps, 1 - eps)
    logloss = -np.mean(np.sum(y * np.log(pc), axis=1))
    return brier, logloss


def roi_1x2(df, prob_cols, fair_cols, odd_cols, stake=10.0, edge_min=0.0):
    outcomes = ["1", "X", "2"]
    bankroll, n_bet, wins = 0.0, 0, 0
    for _, row in df.iterrows():
        probs = {o: row[prob_cols[i]] for i, o in enumerate(outcomes)}
        fair = {o: row[fair_cols[i]] for i, o in enumerate(outcomes)}
        odds = {o: row[odd_cols[i]] for i, o in enumerate(outcomes)}
        if any(pd.isna(v) for v in fair.values()) or any(pd.isna(v) for v in probs.values()):
            continue
        edge_by = {o: probs[o] - fair[o] for o in outcomes}
        best = max(edge_by, key=edge_by.get)
        if edge_by[best] <= edge_min:
            continue
        n_bet += 1
        if row["real_1x2"] == best:
            bankroll += stake * (odds[best] - 1)
            wins += 1
        else:
            bankroll -= stake
    roi = (bankroll / (n_bet * stake) * 100) if n_bet else 0.0
    wr = (wins / n_bet * 100) if n_bet else 0.0
    return n_bet, wr, roi


def analyze_league(prefix, league):
    df_all = load_league(prefix)
    home_adv = LEAGUE_HOME_ADVANTAGE.get(league, 65.0)
    seasonal_xg = load_seasonal_xg(league)
    archive = load_archive(league)
    bt = run_walkforward_rolling(df_all, league, home_adv, seasonal_xg, archive)

    print(f"\n{'='*72}\n{league.upper()} — xG ROLLING (media ultime {K_ROLLING}) vs xG STAGIONALE nel calcolo Elo\n{'='*72}")

    for label, season in [("VALIDATION 2024/25", "2024/25"), ("TEST 2025/26", "2025/26")]:
        sub = bt[bt["season"] == season]
        print(f"\n-- {label}  (N={len(sub)} partite) --")
        hdr = ("Modello", "Brier", "LogLoss", "N.bet", "Win rate %", "ROI % (vs B365)")
        print(f"{'':4s}" + " ".join(f"{h:>18s}" for h in hdr))
        for name, pcols in [
            ("Elo stagionale", ("elo_fix_1", "elo_fix_X", "elo_fix_2")),
            ("Elo rolling", ("elo_roll_1", "elo_roll_X", "elo_roll_2")),
            ("Ensemble stagionale (0.6P+0.4Elo)", ("sm_fix_1", "sm_fix_X", "sm_fix_2")),
            ("Ensemble rolling", ("sm_roll_1", "sm_roll_X", "sm_roll_2")),
        ]:
            b, ll = brier_ll(sub, pcols)
            n, wr, roi = roi_1x2(sub, pcols, ("fair_b365_1", "fair_b365_X", "fair_b365_2"),
                                 ("B365H", "B365D", "B365A"))
            print(f"{'':4s}{name:>40s} {b:8.4f} {ll:8.4f} {n:8d} {wr:11.1f} {roi:14.2f}")


def main():
    for prefix, league in LEAGUES:
        analyze_league(prefix, league)


if __name__ == "__main__":
    main()
