"""
diagnose_time_decay.py — Diagnosi dell'effetto del time-decay (peso temporale
Dixon-Coles) sulle previsioni Poisson walk-forward.

NON tocca SoccerMath/app.py, config.py, models/: importa in sola lettura
load_league/LEAGUES da backtest_experiment_all.py. Riusa la stessa logica
walk-forward no-leakage per lambda_home/lambda_away di diagnose_ou_gg.py, ma con
media PESATA nel tempo invece della media semplice.

Contenuto:
  1. Peso temporale standard Dixon-Coles: phi(t) = exp(-xi * t), t = giorni tra la
     partita passata e quella da prevedere. Applicato come peso nelle medie att/def
     per squadra (home_gf/home_ga/away_gf/away_ga) sia nel calcolo di lambda sia
     nella stima di xi.
  2. Stima xi via MLE (max log-verosimiglianza Poisson sui gol reali) SOLO su
     training 2022/23+2023/24, walk-forward:
       - XI_LEGA   : xi separato per lega
       - XI_GLOBALE: xi unico pooling le 5 leghe
       - XI_ZERO   : xi = 0 (media semplice, equivalente a produzione)
  3. Applicazione di un rho Dixon-Coles FISSO e pooling (=-0.0470, stimato nel
     precedente diagnose_dixon_coles_rho.py) a TUTTE e 3 le varianti, cosi' il
     confronto isola il solo effetto del time-decay. Il rho NON viene ristimato.
  4. Metriche su VALIDATION 2024/25 + TEST 2025/26, 5 leghe: Brier/LogLoss su
     1X2, Over/Under 2.5, GG/NG. (Niente "risultato esatto": evita la leakage sui
     top-6 punteggi.) Valore di xi (globale e per lega) + emivita ln(2)/xi.
  5. Output: audit/results/time_decay_diagnosis.md
"""
import os
import sys
import math
import numpy as np
import pandas as pd
from scipy.stats import poisson as scipy_poisson
from scipy.optimize import minimize_scalar

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from backtest_experiment_all import load_league, LEAGUES  # sola lettura

TRAIN_SEASONS = ("2022/23", "2023/24")
EVAL_SEASONS = ("2024/25", "2025/26")   # validation + test
RHO_POOLED = -0.0470                    # fisso, da diagnose_dixon_coles_rho.py
XI_BOUND = 0.02
MAX_GOALS = 15

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "time_decay_diagnosis.md")


class TeamDecay:
    __slots__ = ("S", "W", "anchor")

    def __init__(self, day0):
        self.S = {"home_gf": 0.0, "home_ga": 0.0, "away_gf": 0.0, "away_ga": 0.0}
        self.W = {"home_gf": 0.0, "home_ga": 0.0, "away_gf": 0.0, "away_ga": 0.0}
        self.anchor = day0


def _advance(t, day, xi):
    dt = (day - t.anchor).days
    if dt > 0 and xi > 0:
        f = math.exp(-xi * dt)
        for k in t.S:
            t.S[k] *= f
            t.W[k] *= f
    t.anchor = day


def run_walkforward_decay(df, xi, report_seasons):
    """Walk-forward no-leakage con medie squadra pesate exp(-xi*days).
    Ritorna DataFrame con season, lambda_h, lambda_a, FTHG, FTAG, real_1x2,
    real_uo, real_gg SOLO per le stagioni in report_seasons."""
    state = {}
    tot_fthg = tot_ftag = tot_n = 0.0
    rows = []
    for _, row in df.iterrows():
        day = row.Date
        h, a = row.HomeClean, row.AwayClean
        avg_h = max(tot_fthg / tot_n, 0.1) if tot_n else 0.1
        avg_a = max(tot_ftag / tot_n, 0.1) if tot_n else 0.1

        if h in state:
            _advance(state[h], day, xi)
        else:
            state[h] = TeamDecay(day)
        if a in state:
            _advance(state[a], day, xi)
        else:
            state[a] = TeamDecay(day)
        th, ta = state[h], state[a]

        hg_home = (th.S["home_gf"] / th.W["home_gf"]) / avg_h if th.W["home_gf"] else 1.0
        hg_away = (th.S["away_gf"] / th.W["away_gf"]) / avg_a if th.W["away_gf"] else 1.0
        hd_home = (th.S["home_ga"] / th.W["home_ga"]) / avg_a if th.W["home_ga"] else 1.0
        hd_away = (th.S["away_ga"] / th.W["away_ga"]) / avg_h if th.W["away_ga"] else 1.0
        att_h = (hg_home + hg_away) / 2.0
        def_h = (hd_home + hd_away) / 2.0

        ag_home = (ta.S["home_gf"] / ta.W["home_gf"]) / avg_h if ta.W["home_gf"] else 1.0
        ag_away = (ta.S["away_gf"] / ta.W["away_gf"]) / avg_a if ta.W["away_gf"] else 1.0
        ad_home = (ta.S["home_ga"] / ta.W["home_ga"]) / avg_a if ta.W["home_ga"] else 1.0
        ad_away = (ta.S["away_ga"] / ta.W["away_ga"]) / avg_h if ta.W["away_ga"] else 1.0
        att_a = (ag_home + ag_away) / 2.0
        def_a = (ad_home + ad_away) / 2.0

        lam_h = att_h * def_a * avg_h
        lam_a = att_a * def_h * avg_a

        fthg, ftag = int(row.FTHG), int(row.FTAG)
        totg = fthg + ftag
        if row.season in report_seasons:
            rows.append({
                "season": row.season,
                "lambda_h": lam_h, "lambda_a": lam_a,
                "FTHG": fthg, "FTAG": ftag,
                "real_1x2": "1" if fthg > ftag else ("2" if ftag > fthg else "X"),
                "real_uo": "OVER" if totg > 2.5 else "UNDER",
                "real_gg": "GG" if fthg > 0 and ftag > 0 else "NG",
            })

        # aggiornamento stato dopo la previsione (no-leakage)
        tot_fthg += fthg; tot_ftag += ftag; tot_n += 1
        th.S["home_gf"] += fthg; th.W["home_gf"] += 1.0
        th.S["home_ga"] += ftag; th.W["home_ga"] += 1.0
        ta.S["away_gf"] += ftag; ta.W["away_gf"] += 1.0
        ta.S["away_ga"] += fthg; ta.W["away_ga"] += 1.0

    return pd.DataFrame(rows)


_LAM_FLOOR = 1e-3


def _neg_ll_league(df, xi, seasons):
    rl = run_walkforward_decay(df, xi, seasons)
    if rl.empty:
        return 0.0
    lam_h = np.maximum(rl["lambda_h"].to_numpy(), _LAM_FLOOR)
    lam_a = np.maximum(rl["lambda_a"].to_numpy(), _LAM_FLOOR)
    return -np.sum(scipy_poisson.logpmf(rl["FTHG"].astype(int), lam_h)) \
           - np.sum(scipy_poisson.logpmf(rl["FTAG"].astype(int), lam_a))


def estimate_xi(dfs, seasons):
    """MLE bounded di xi su training delle leghe date (dfs = lista DataFrames)."""
    def f(x):
        return float(sum(_neg_ll_league(d, x, seasons) for d in dfs))
    grid = np.linspace(0.0, XI_BOUND, 51)
    vals = np.array([f(x) for x in grid])
    i0 = int(np.argmin(vals))
    lo = grid[max(0, i0 - 2)]
    hi = grid[min(len(grid) - 1, i0 + 2)]
    if hi <= lo:
        hi = XI_BOUND
    res = minimize_scalar(f, bounds=(lo, hi), method="bounded", options={"xatol": 1e-7})
    best = float(np.clip(res.x, 0.0, XI_BOUND))
    return best


def build_matrix(lam_h, lam_a, rho):
    h_p = np.array([scipy_poisson.pmf(i, lam_h) for i in range(MAX_GOALS)])
    a_p = np.array([scipy_poisson.pmf(i, lam_a) for i in range(MAX_GOALS)])
    M = np.outer(h_p, a_p)
    if rho != 0.0:
        M[0, 0] *= 1 - lam_h * lam_a * rho
        M[1, 0] *= 1 + lam_a * rho
        M[0, 1] *= 1 + lam_h * rho
        M[1, 1] *= 1 - rho
        M = np.maximum(M, 0.0)
        s = M.sum()
        if s > 0:
            M = M / s
    return M


def market_probs(M):
    p1 = float(np.sum(np.tril(M, -1)))
    pX = float(np.sum(np.diag(M)))
    p2 = float(np.sum(np.triu(M, 1)))
    po25 = sum(float(M[i, j]) for i in range(MAX_GOALS) for j in range(MAX_GOALS) if i + j > 2.5)
    pgg = float(np.sum(M[1:, 1:]))
    return p1, pX, p2, po25, pgg


def metrics(df, rho):
    p1x2 = []; y1x2 = []; p_uo = []; y_uo = []; p_gg = []; y_gg = []
    for _, r in df.iterrows():
        M = build_matrix(r["lambda_h"], r["lambda_a"], rho)
        p1, pX, p2, po25, pgg = market_probs(M)
        p1x2.append([p1, pX, p2]); y1x2.append({"1": 0, "X": 1, "2": 2}[r["real_1x2"]])
        p_uo.append([po25, 1 - po25]); y_uo.append(0 if r["real_uo"] == "OVER" else 1)
        p_gg.append([pgg, 1 - pgg]); y_gg.append(0 if r["real_gg"] == "GG" else 1)

    def bll(probs, y):
        probs = np.array(probs); y = np.array(y); n = len(y)
        onehot = np.zeros_like(probs); onehot[np.arange(n), y] = 1
        brier = float(np.mean(np.sum((onehot - probs) ** 2, axis=1)))
        pc = np.clip(probs[np.arange(n), y], 1e-12, 1.0)
        ll = float(-np.mean(np.log(pc)))
        return brier, ll

    return {"1X2": bll(p1x2, y1x2), "O/U2.5": bll(p_uo, y_uo), "GG/NG": bll(p_gg, y_gg)}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    dfs = [load_league(prefix) for prefix, _ in LEAGUES]

    # --- stima xi su training ---
    xi_glob = estimate_xi(dfs, TRAIN_SEASONS)
    xi_lega = {}
    for i, (prefix, camp_key) in enumerate(LEAGUES):
        xi_lega[camp_key] = estimate_xi([dfs[i]], TRAIN_SEASONS)

    half = lambda x: "inf" if x == 0 else f"{math.log(2)/x:.0f} gg"
    lines = []
    lines.append("# Diagnosi time-decay (peso temporale Dixon-Coles) — effetto isolato")
    lines.append("")
    lines.append("Peso phi(t)=exp(-xi*giorni) sulle medie att/def per squadra. xi stimato "
                 "con MLE (Poisson sui gol reali) SOLO su training 2022/23+2023/24. "
                 "Tutte le metriche applicano lo stesso rho Dixon-Coles pooling fisso "
                 "RHO=%.4f (da diagnose_dixon_coles_rho.py), cosi' il confronto isola il "
                 "solo effetto del time-decay." % RHO_POOLED)
    lines.append("")
    lines.append("## Valori di xi stimati")
    lines.append("")
    lines.append("| Variante | xi | emivita (ln2/xi) |")
    lines.append("|---|---|---|")
    lines.append(f"| XI_ZERO | 0 | inf |")
    lines.append(f"| XI_GLOBALE (pooled) | {xi_glob:.6f} | {half(xi_glob)} |")
    for prefix, camp_key in LEAGUES:
        lines.append(f"| XI_LEGA ({camp_key}) | {xi_lega[camp_key]:.6f} | {half(xi_lega[camp_key])} |")
    lines.append("")

    # --- valutazione per lega ---
    for i, (prefix, camp_key) in enumerate(LEAGUES):
        xlega = xi_lega[camp_key]
        res = {}
        n = 0
        for name, xi in [("XI_ZERO", 0.0), ("XI_GLOBALE", xi_glob), ("XI_LEGA", xlega)]:
            rl = run_walkforward_decay(dfs[i], xi, EVAL_SEASONS)
            res[name] = metrics(rl, RHO_POOLED)
            n = len(rl)
        lines.append(f"\n## {camp_key.upper()}  (N={n} val+test)")
        lines.append("")
        lines.append("| Mercato | metrica | XI_ZERO | XI_GLOBALE | XI_LEGA |")
        lines.append("|---|---|---|---|---|")
        for market in ["1X2", "O/U2.5", "GG/NG"]:
            bz, lz = res["XI_ZERO"][market]
            bg, lg = res["XI_GLOBALE"][market]
            bl, ll = res["XI_LEGA"][market]
            lines.append(f"| {market} | Brier | {bz:.4f} | {bg:.4f} | {bl:.4f} |")
            lines.append(f"| {market} | LogLoss | {lz:.4f} | {lg:.4f} | {ll:.4f} |")
        lines.append("")

    # --- aggregato ---
    dfs_eval = {name: [] for name in ("XI_ZERO", "XI_GLOBALE")}
    for i, (prefix, camp_key) in enumerate(LEAGUES):
        for name, xi in [("XI_ZERO", 0.0), ("XI_GLOBALE", xi_glob)]:
            dfs_eval[name].append(run_walkforward_decay(dfs[i], xi, EVAL_SEASONS))
    n_agg = sum(len(d) for d in dfs_eval["XI_ZERO"])
    lines.append("\n## AGGREGATO — 5 LEGHE  (N=%d val+test)" % n_agg)
    lines.append("")
    lines.append("| Mercato | metrica | XI_ZERO | XI_GLOBALE |")
    lines.append("|---|---|---|---|")
    for market in ["1X2", "O/U2.5", "GG/NG"]:
        row_vals = {}
        for name in ("XI_ZERO", "XI_GLOBALE"):
            allrl = pd.concat(dfs_eval[name], ignore_index=True)
            m = metrics(allrl, RHO_POOLED)
            row_vals[name] = m[market]
        lines.append(f"| {market} | Brier | {row_vals['XI_ZERO'][0]:.4f} | "
                     f"{row_vals['XI_GLOBALE'][0]:.4f} |")
        lines.append(f"| {market} | LogLoss | {row_vals['XI_ZERO'][1]:.4f} | "
                     f"{row_vals['XI_GLOBALE'][1]:.4f} |")
    lines.append("_(nell'aggregato XI_LEGA coincide con XI_GLOBALE: un solo xi pooled; "
                 "il confronto per-lega XI_LEGA vs XI_GLOBALE e' sopra)_")
    lines.append("")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("xi_glob=%.6f  %s" % (xi_glob, {k: round(v, 6) for k, v in xi_lega.items()}))
    print(f"Scritto: {OUT_PATH}")


if __name__ == "__main__":
    main()
