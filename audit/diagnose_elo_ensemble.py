"""
diagnose_elo_ensemble.py — Vale la pena combinare Poisson ed Elo sulla testa 1X2?

In app.py (tab Value Bets / Top Mix) la confidence 1X2 e' `0.6 * poisson +
0.4 * elo`. Questo script misura, walk-forward no-leakage su 5 leghe
(VALIDATION 2024/25 + TEST 2025/26), Brier e LogLoss multiclasse 1X2 di:

  - POISSON       : testa 1X2 di produzione a Due Teste (xG primario + forma
                    ult.5 + mercato, lambda normalizzati alla somma base
                    S = base_h + base_a con att0/def0)
  - ELO           : Elo sequenziale (K=24, home advantage per lega da config,
                    pareggio gaussiano 0.27*exp(-(dr/320)^2) clip [0.06,0.34]),
                    stessa formula del backtest in-app (run_historical_backtest)
  - ENSEMBLE w    : w*Poisson + (1-w)*Elo per w in {0.5, 0.6, 0.7, 0.8, 0.9}

NON tocca SoccerMath/app.py, config.py, models/ (sola lettura).
Output: audit/results/elo_ensemble_diagnosis.md
"""
import os
import sys
import math
import json
from collections import deque
import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from backtest_experiment_all import load_league, get_full_poisson, LEAGUES, MARKET_VALUES
from config import LEAGUE_HOME_ADVANTAGE

XG_FILES = {
    "Serie A": "xg_serie_a.json",
    "Premier League": "xg_premier_league.json",
    "La Liga": "xg_la_liga.json",
    "Bundesliga": "xg_bundesliga.json",
    "Ligue 1": "xg_ligue_1.json",
}
DB = os.path.join(_REPO_ROOT, "SoccerMath", "database")
SEASONS_EVAL = ("2024/25", "2025/26")
LAM_LO, LAM_HI = math.exp(-6.0), math.exp(3.0)
WEIGHTS = [0.5, 0.6, 0.7, 0.8, 0.9]
ELO_K = 24.0

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "elo_ensemble_diagnosis.md")


class TeamState:
    __slots__ = ("hgf", "hga", "hgn", "agf", "aga", "agn", "last5")

    def __init__(self):
        self.hgf = self.hga = 0.0; self.hgn = 0
        self.agf = self.aga = 0.0; self.agn = 0
        self.last5 = deque(maxlen=5)

    def observe_home(self, fthg, ftag):
        self.hgf += fthg; self.hga += ftag; self.hgn += 1; self.last5.append((fthg, ftag))

    def observe_away(self, fthg, ftag):
        self.agf += ftag; self.aga += fthg; self.agn += 1; self.last5.append((ftag, fthg))


def clip(x):
    return max(LAM_LO, min(LAM_HI, x))


def market_factor(val):
    return max(0.85, min(1.25, 1.0 + (math.log10(max(val, 10)) - 2.0) / 4.0))


def elo_probs(r_h, r_a, home_adv):
    dr = r_h + home_adv - r_a
    e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
    p_draw = max(0.06, min(0.34, 0.27 * math.exp(-((dr / 320.0) ** 2))))
    return (1.0 - p_draw) * e_h, p_draw, (1.0 - p_draw) * (1.0 - e_h)


def load_xg(camp_key):
    path = os.path.join(DB, XG_FILES[camp_key])
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f) or {}


def run_models(df, camp_key, xg_data):
    home_adv = LEAGUE_HOME_ADVANTAGE.get(camp_key, 60.0)
    xg_att, xg_def = {}, {}
    if xg_data and len(xg_data) >= 10:
        vals = list(xg_data.values())
        lx = float(np.mean([v["xG_avg"] for v in vals])); lxa = float(np.mean([v["xGA_avg"] for v in vals]))
        if lx and lxa:
            for t, v in xg_data.items():
                xg_att[t] = v["xG_avg"] / lx; xg_def[t] = v["xGA_avg"] / lxa

    state, elo = {}, {}
    tot_hg = tot_ag = tot_n = 0.0
    rows = []

    def get(t):
        if t not in state:
            state[t] = TeamState()
        return state[t]

    for _, row in df.iterrows():
        fthg, ftag = int(row.FTHG), int(row.FTAG)
        ftr = str(row.FTR).strip().upper()
        h, a = row.HomeClean, row.AwayClean
        sh, sa = get(h), get(a)
        avg_h = max(tot_hg / tot_n, 0.1) if tot_n else 0.1
        avg_a = max(tot_ag / tot_n, 0.1) if tot_n else 0.1
        r_h, r_a = elo.get(h, 1500.0), elo.get(a, 1500.0)

        if row.season in SEASONS_EVAL:
            def form_fac(ts):
                if len(ts.last5) < 3:
                    return 1.0, 1.0
                n = len(ts.last5); gf = sum(x[0] for x in ts.last5); ga = sum(x[1] for x in ts.last5)
                den = max((avg_h + avg_a) / 2.0, 0.5)
                return max(0.85, min(1.15, (gf / n) / den)), max(0.85, min(1.15, (ga / n) / den))

            def prim(t, ts):
                pa = xg_att[t] if t in xg_att else ((ts.hgf / ts.hgn) / avg_h if ts.hgn else 1.0)
                pdf = xg_def[t] if t in xg_def else ((ts.hga / ts.hgn) / avg_a if ts.hgn else 1.0)
                return pa, pdf

            pa_h, pd_h = prim(h, sh); pa_a, pd_a = prim(a, sa)
            fa_h, fd_h = form_fac(sh); fa_a, fd_a = form_fac(sa)
            m_h, m_a = market_factor(MARKET_VALUES.get(h, 50)), market_factor(MARKET_VALUES.get(a, 50))
            # testa 1X2 di produzione: base CON forma (att0/def0), lambda con
            # forma+mercato normalizzati alla somma base S
            lam_base_h = pa_h * fa_h * pd_a * fd_a * avg_h
            lam_base_a = pa_a * fa_a * pd_h * fd_h * avg_a
            lam_m_h = (pa_h * fa_h * m_h) * (pd_a * fd_a / m_a) * avg_h
            lam_m_a = (pa_a * fa_a * m_a) * (pd_h * fd_h / m_h) * avg_a
            S = lam_base_h + lam_base_a; den = lam_m_h + lam_m_a
            lh = clip(S * lam_m_h / den) if den > 0 else clip(lam_base_h)
            la = clip(S * lam_m_a / den) if den > 0 else clip(lam_base_a)
            mp = get_full_poisson(lh, la)
            e1, eX, e2 = elo_probs(r_h, r_a, home_adv)
            rows.append({"season": row.season,
                         "y": {"H": 0, "D": 1, "A": 2}.get(ftr, 1),
                         "p1": mp["1"], "pX": mp["X"], "p2": mp["2"],
                         "e1": e1, "eX": eX, "e2": e2})

        # aggiornamento stato (dopo la predizione)
        dr = r_h + home_adv - r_a
        e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
        s_h = 1.0 if ftr == "H" else (0.0 if ftr == "A" else 0.5)
        elo[h] = r_h + ELO_K * (s_h - e_h); elo[a] = r_a + ELO_K * ((1 - s_h) - (1 - e_h))
        tot_hg += fthg; tot_ag += ftag; tot_n += 1
        sh.observe_home(fthg, ftag); sa.observe_away(fthg, ftag)

    return pd.DataFrame(rows)


def brier_ll(P, y):
    P = np.asarray(P, dtype=float); y = np.asarray(y, dtype=int); n = len(y)
    oh = np.zeros_like(P); oh[np.arange(n), y] = 1
    return (float(np.mean(np.sum((oh - P) ** 2, axis=1))),
            float(-np.mean(np.log(np.clip(P[np.arange(n), y], 1e-12, 1.0)))))


def model_matrix(d, w):
    P = d[["p1", "pX", "p2"]].to_numpy(); E = d[["e1", "eX", "e2"]].to_numpy()
    return w * P + (1 - w) * E


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    per_league = {ck: run_models(load_league(pf), ck, load_xg(ck)) for pf, ck in LEAGUES}
    agg = pd.concat(per_league.values(), ignore_index=True)
    models = [("POISSON (prod 1X2)", 1.0), ("ELO", 0.0)] + [(f"ENSEMBLE w={w}", w) for w in WEIGHTS]

    lines = ["# Ensemble Poisson + Elo sulla testa 1X2", "",
             "Walk-forward no-leakage, 5 leghe, VALIDATION 2024/25 + TEST 2025/26. "
             "Poisson = testa 1X2 di produzione (xG + forma + mercato, somma normalizzata "
             "alla base con forma att0/def0). Elo = sequenziale K=24, home advantage per "
             "lega, pareggio gaussiano (stessa formula del backtest in-app). "
             "Ensemble = w*Poisson + (1-w)*Elo. In produzione (Value Bets) w = 0.6.", ""]
    win_counts = {name: 0 for name, _ in models}
    total = 0

    def section(name, d):
        nonlocal total
        out = [f"\n## {name.upper()}  (VAL {len(d[d.season=='2024/25'])} + TEST {len(d[d.season=='2025/26'])} partite)", "",
               "| Modello | Brier V | LogLoss V | Brier T | LogLoss T |", "|---|---|---|---|---|"]
        for s in SEASONS_EVAL:
            sub = d[d.season == s]
            if name != "AGGREGATO":
                total += 1
                best = min(models, key=lambda m: brier_ll(model_matrix(sub, m[1]), sub["y"])[0])
                win_counts[best[0]] += 1
        for mname, w in models:
            v = {s: brier_ll(model_matrix(d[d.season == s], w), d[d.season == s]["y"]) for s in SEASONS_EVAL}
            out.append(f"| {mname} | {v['2024/25'][0]:.4f} | {v['2024/25'][1]:.4f} | "
                       f"{v['2025/26'][0]:.4f} | {v['2025/26'][1]:.4f} |")
        return out

    for ck, d in per_league.items():
        lines += section(ck, d)
    lines += section("AGGREGATO", agg)

    lines += ["", "## Sintesi", "", f"Miglior Brier 1X2 per (lega x stagione), su {total} casi:", ""]
    for mname, _ in models:
        lines.append(f"- {mname}: {win_counts[mname]}")
    ranked = sorted(models, key=lambda m: brier_ll(model_matrix(agg, m[1]), agg["y"])[0])
    lines += ["", "Classifica aggregata (Brier 1X2, V+T, 5 leghe):", ""]
    for i, (mname, w) in enumerate(ranked, 1):
        b, ll = brier_ll(model_matrix(agg, w), agg["y"])
        lines.append(f"{i}. {mname}: Brier {b:.4f} | LogLoss {ll:.4f}")
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[-12:]))
    print(f"\nReport: {OUT_PATH}")


if __name__ == "__main__":
    main()
