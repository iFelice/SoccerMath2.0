"""
diagnose_lambda_compression.py — Compressione dei rapporti attacco/difesa: finestra
piena (Variante A) vs finestra rolling ultime N partite per squadra (Variante B).

Riusa la logica no-leakage di diagnose_ou_gg.py (train = solo righe precedenti nel
tempo, stesso calcolo att/def, lambda_home/lambda_away, poisson_o25, poisson_gg),
ma per il calcolo delle medie squadra (home_gf, home_ga, away_gf, away_ga) confronta:

  VARIANTE A: media su tutto lo storico disponibile (df.iloc[:idx], nessun limite).
  VARIANTE B: media solo sulle ultime N partite per squadra (N=38 ~ una stagione),
              scartando lo storico piu' vecchio.

Entrambe le varianti usano la stessa media di lega avg_h/avg_a (su tutto lo storico):
solo le statistiche di squadra cambiano tra A e B. Nessun leakage: al punto di
previsione idx si usano SOLO i match con riga < idx.

Non tocca backtest_experiment_all.py, analyze_all.py, app.py, config.py, models/:
importa in sola lettura load_league/get_full_poisson/LEAGUES.

Produce audit/results/lambda_compression_diagnosis.md con, per le 5 leghe su
validation 2024/25 + test 2025/26:
  1. Std dev dei rapporti att_h, def_h, att_a, def_a TRA squadre a meta' stagione
     (15a giornata), confronto A vs B.
  2. Std dev di lambda_totale per partita, A vs B.
  3. Rapporto std_gol_reali / std_lambda, A vs B.
  4. Brier Score e Log Loss su O/U2.5 e GG, A vs B, per stagione.
"""
import os
import sys
from collections import deque
import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from backtest_experiment_all import (load_league, get_full_poisson, LEAGUES)

SEASONS = ["2024/25", "2025/26"]  # validation + test
N_ROLL = 38          # finestra Variante B (ultime N partite per squadra)
MID_MATCHDAY = 15    # snapshot a meta' stagione (15a giornata)

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "lambda_compression_diagnosis.md")


class TeamState:
    """Stato per-team delle statistiche attacco/difesa.
    Variante A: somme/contatori cumulativi (tutto lo storico).
    Variante B: deque con ultime N osservazioni per ruolo/statistica."""
    __slots__ = ("sum", "cnt", "roll")

    def __init__(self):
        self.sum = {"home_gf": 0.0, "home_ga": 0.0, "away_gf": 0.0, "away_ga": 0.0}
        self.cnt = {"home_gf": 0, "home_ga": 0, "away_gf": 0, "away_ga": 0}
        self.roll = {k: deque(maxlen=N_ROLL) for k in ("home_gf", "home_ga", "away_gf", "away_ga")}

    def observe(self, role_stat, value):
        self.sum[role_stat] += value
        self.cnt[role_stat] += 1
        self.roll[role_stat].append(value)

    def stats_A(self, avg_h, avg_a):
        """Valori completi (media su tutto lo storico), con fallback a media di lega."""
        c = self.cnt
        att_h = self.sum["home_gf"] / c["home_gf"] if c["home_gf"] else avg_h
        def_h = self.sum["home_ga"] / c["home_ga"] if c["home_ga"] else avg_a
        att_a = self.sum["away_gf"] / c["away_gf"] if c["away_gf"] else avg_a
        def_a = self.sum["away_ga"] / c["away_ga"] if c["away_ga"] else avg_h
        return att_h, def_h, att_a, def_a

    def stats_B(self, avg_h, avg_a):
        """Valori rolling (media ultime N), con fallback a media di lega se nessun match."""
        r = self.roll
        att_h = np.mean(r["home_gf"]) if r["home_gf"] else avg_h
        def_h = np.mean(r["home_ga"]) if r["home_ga"] else avg_a
        att_a = np.mean(r["away_gf"]) if r["away_gf"] else avg_a
        def_a = np.mean(r["away_ga"]) if r["away_ga"] else avg_h
        return att_h, def_h, att_a, def_a


def ratios(att_h, def_h, att_a, def_a, avg_h, avg_a):
    """Rapporti normalizzati per la media di lega."""
    return {
        "att_h": att_h / avg_h,
        "def_h": def_h / avg_a,
        "att_a": att_a / avg_a,
        "def_a": def_a / avg_h,
    }


def run_walkforward_ab(df, camp_key):
    """Loop walk-forward no-leakage calcolando A e B in parallelo.
    Ritorna (rows_df, mid_snapshots) dove mid_snapshots[season] = dict con std
    dei rapporti tra squadre a meta' stagione per A e B."""
    train_cutoff = df[df["season"].isin(("2022/23", "2023/24"))]["Date"].max()
    state = {}  # team -> TeamState
    rows = []
    mid_snapshots = {}  # season -> {"A": {stat: std}, "B": {stat: std}}
    mid_captured = set()
    season_counter = {}
    mid_target = {}  # season -> numero partite per chiudere la 15a giornata

    for idx, row in df.iterrows():
        h, a = row.HomeClean, row.AwayClean
        ftr = str(row.FTR).strip().upper()

        # --- avg di lega su tutto lo storico precedente (identico per A e B) ---
        train = df.iloc[:idx]
        avg_h = max(float(train["FTHG"].mean()), 0.1)
        avg_a = max(float(train["FTAG"].mean()), 0.1)

        if row.Date > train_cutoff:
            st_h = state.get(h)
            st_a = state.get(a)
            if st_h is None or st_a is None:
                # team mai visto prima dello split: stato vuoto -> fallback media di lega
                st_h = st_h or TeamState()
                st_a = st_a or TeamState()
            a_att_h, a_def_h, a_att_a, a_def_a = st_h.stats_A(avg_h, avg_a)
            b_att_h, b_def_h, b_att_a, b_def_a = st_h.stats_B(avg_h, avg_a)
            a_atth2, a_defh2, a_atta2, a_defa2 = st_a.stats_A(avg_h, avg_a)
            b_atth2, b_defh2, b_atta2, b_defa2 = st_a.stats_B(avg_h, avg_a)

            # att/def combinati (stesso calcolo di run_walkforward)
            attA_h = (a_att_h / avg_h + a_att_a / avg_a) / 2
            defA_h = (a_def_h / avg_a + a_def_a / avg_h) / 2
            attA_a = (a_atth2 / avg_h + a_atta2 / avg_a) / 2
            defA_a = (a_defh2 / avg_a + a_defa2 / avg_h) / 2
            attB_h = (b_att_h / avg_h + b_att_a / avg_a) / 2
            defB_h = (b_def_h / avg_a + b_def_a / avg_h) / 2
            attB_a = (b_atth2 / avg_h + b_atta2 / avg_a) / 2
            defB_a = (b_defh2 / avg_a + b_defa2 / avg_h) / 2

            lamA_h = attA_h * defA_a * avg_h
            lamA_a = attA_a * defA_h * avg_a
            lamB_h = attB_h * defB_a * avg_h
            lamB_a = attB_a * defB_h * avg_a

            m_pA = get_full_poisson(lamA_h, lamA_a)
            m_pB = get_full_poisson(lamB_h, lamB_a)

            real_uo = "OVER" if (row.FTHG + row.FTAG) > 2.5 else "UNDER"
            real_gg = "GG" if row.FTHG > 0 and row.FTAG > 0 else "NG"

            rows.append({
                "season": row.season,
                "real_uo": real_uo, "real_gg": real_gg,
                "lambda_total_A": lamA_h + lamA_a, "lambda_total_B": lamB_h + lamB_a,
                "poisson_o25_A": 1 - m_pA["u25"], "poisson_o25_B": 1 - m_pB["u25"],
                "poisson_gg_A": m_pA["gg"], "poisson_gg_B": m_pB["gg"],
                "real_total_goals": row.FTHG + row.FTAG,
            })

        # --- aggiornamento stato dopo la previsione (no-leakage: solo righe < idx) ---
        if h not in state:
            state[h] = TeamState()
        if a not in state:
            state[a] = TeamState()
        fthg = row.FTHG
        ftag = row.FTAG
        state[h].observe("home_gf", fthg)
        state[h].observe("home_ga", ftag)
        state[a].observe("away_gf", ftag)
        state[a].observe("away_ga", fthg)

        # --- snapshot a meta' stagione (15a giornata) ---
        season = row.season
        if season in SEASONS:
            season_counter[season] = season_counter.get(season, 0) + 1
            if season not in mid_target:
                # numero di squadre nella stagione corrente -> partite per chiudere la 15a giornata
                teams_season = set(df[df["season"] == season]["HomeClean"]) | set(
                    df[df["season"] == season]["AwayClean"])
                mid_target[season] = MID_MATCHDAY * (len(teams_season) // 2)
            if season_counter[season] == mid_target[season] and season not in mid_captured:
                mid_captured.add(season)
                # stato include la partita corrente (fine 15a giornata)
                ra = {}
                rb = {}
                for team, st in state.items():
                    ra[team] = ratios(*st.stats_A(avg_h, avg_a), avg_h, avg_a)
                    rb[team] = ratios(*st.stats_B(avg_h, avg_a), avg_h, avg_a)
                dfA = pd.DataFrame.from_dict(ra, orient="index")
                dfB = pd.DataFrame.from_dict(rb, orient="index")
                mid_snapshots[season] = {"A": dfA.std().to_dict(),
                                         "B": dfB.std().to_dict()}

    return pd.DataFrame(rows), mid_snapshots


def brier_binary(y, p):
    return float(np.mean((y - p) ** 2))


def log_loss_binary(y, p):
    eps = 1e-15
    p = np.clip(p, eps, 1 - eps)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def league_section(prefix, camp_key):
    df_all = load_league(prefix)
    rl, mid = run_walkforward_ab(df_all, camp_key)
    rl = rl[rl["season"].isin(SEASONS)].copy()

    lines = [f"\n## {camp_key.upper()}\n"]

    # --- 1. Std dev rapporti att/def tra squadre a meta' stagione ---
    lines.append("### 1. Std dev rapporti att/def TRA squadre — meta' stagione (15a giornata)")
    lines.append("")
    lines.append("| Stagione | rapporto | std A (tutto storico) | std B (ult. %d) |" % N_ROLL)
    lines.append("|---|---|---|---|")
    for s in SEASONS:
        snap = mid.get(s)
        if not snap:
            lines.append(f"| {s} | — | — | — |")
            continue
        for stat_name in ("att_h", "def_h", "att_a", "def_a"):
            sa = snap["A"].get(stat_name, float("nan"))
            sb = snap["B"].get(stat_name, float("nan"))
            lines.append(f"| {s} | {stat_name} | {sa:.4f} | {sb:.4f} |")
    lines.append("")

    # --- 2. Std dev lambda_totale per partita (A vs B) ---
    lamA = rl["lambda_total_A"].std()
    lamB = rl["lambda_total_B"].std()
    lines.append("### 2. Std dev lambda_totale per partita (N=%d, val+test)" % len(rl))
    lines.append("")
    lines.append(f"- Variante A: **{lamA:.4f}**")
    lines.append(f"- Variante B: **{lamB:.4f}**")
    lines.append("")

    # --- 3. Rapporto std_gol_reali/std_lambda ---
    goals_std = rl["real_total_goals"].std()
    ratioA = goals_std / lamA if lamA else float("nan")
    ratioB = goals_std / lamB if lamB else float("nan")
    lines.append("### 3. Rapporto std_gol_reali / std_lambda")
    lines.append("")
    lines.append(f"- std gol reali: {goals_std:.4f}")
    lines.append(f"- Variante A: **{ratioA:.2f}**")
    lines.append(f"- Variante B: **{ratioB:.2f}**")
    lines.append("")

    # --- 4. Brier / LogLoss su O/U2.5 e GG, per stagione ---
    lines.append("### 4. Brier / LogLoss su O/U2.5 e GG (A vs B)")
    lines.append("")
    lines.append("| Stagione | mercato | metric | A | B |")
    lines.append("|---|---|---|---|---|")
    for s in SEASONS:
        sub = rl[rl["season"] == s]
        y_uo = (sub["real_uo"] == "OVER").astype(int).to_numpy()
        y_gg = (sub["real_gg"] == "GG").astype(int).to_numpy()
        for market, y, pA, pB in [("O/U2.5", y_uo, sub["poisson_o25_A"], sub["poisson_o25_B"]),
                                  ("GG", y_gg, sub["poisson_gg_A"], sub["poisson_gg_B"])]:
            bA, bB = brier_binary(y, pA.to_numpy()), brier_binary(y, pB.to_numpy())
            llA, llB = log_loss_binary(y, pA.to_numpy()), log_loss_binary(y, pB.to_numpy())
            lines.append(f"| {s} | {market} | Brier | {bA:.4f} | {bB:.4f} |")
            lines.append(f"| {s} | {market} | LogLoss | {llA:.4f} | {llB:.4f} |")
    lines.append("")
    return "\n".join(lines)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    parts = [
        "# Diagnosi compressione lambda — Variante A (tutto storico) vs Variante B (ultime %d partite)" % N_ROLL,
        "",
        "Campione: walk-forward no-leakage, VALIDATION 2024/25 + TEST 2025/26, 5 leghe.",
        "Modello Poisson, stesso calcolo di diagnose_ou_gg.py. Media di lega avg_h/avg_a identica "
        "per entrambe le varianti (solo le statistiche di squadra cambiano).",
        "",
    ]
    for prefix, camp_key in LEAGUES:
        parts.append(league_section(prefix, camp_key))

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    print(f"Scritto: {OUT_PATH}")


if __name__ == "__main__":
    main()
