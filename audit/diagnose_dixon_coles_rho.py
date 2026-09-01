"""
diagnose_dixon_coles_rho.py — Diagnosi dell'effetto della correzione tau di
Dixon-Coles (1997) sulle previsioni walk-forward Poisson.

NON tocca SoccerMath/app.py, config.py, models/: importa in sola lettura
load_league/LEAGUES da backtest_experiment_all.py e replica SOLO il calcolo dei
lambda (stessa logica no-leakage di diagnose_ou_gg.py). La funzione get_full_poisson
viene importata ma non usata per i calcoli di tau (ne serve la matrice).

Contenuto:
  1. tau(x,y,lambda_h,lambda_a,rho) sulle 4 celle basse della matrice congiunta
     Poisson (0-0, 1-0, 0-1, 1-1), poi rinormalizzazione a somma 1.
  2. Stima MLE di rho (max log-verosimiglianza sui risultati esatti) SOLO su
     training 2022/23+2023/24, usando gli stessi lambda_home/lambda_away del
     walk-forward (no-leakage):
       - RHO_LEGA   : un rho per ciascuna lega
       - RHO_GLOBALE: un rho pooling tutte le 5 leghe
       - RHO_ZERO   : rho = 0 (Poisson puro, baseline)
  3. Applicazione dei 3 rho (fissi, stimati solo su training) alle predizioni di
     VALIDATION 2024/25 + TEST 2025/26, 5 leghe. Per ogni variante, per lega e
     aggregato: Brier/LogLoss su 1X2, Over/Under 2.5, GG/NG, risultato esatto
     (top-6 punteggi + "altro").
  4. Output: audit/results/dixon_coles_rho_diagnosis.md
"""
import os
import sys
import numpy as np
import pandas as pd
from collections import Counter
from scipy.stats import poisson as scipy_poisson
from scipy.optimize import minimize_scalar

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from backtest_experiment_all import load_league, LEAGUES  # sola lettura

SEASONS = ["2024/25", "2025/26"]     # validation + test
TRAIN_SEASONS = ("2022/23", "2023/24")
MAX_GOALS = 15
RHO_BOUND = 0.3
EXACT_TOP = 6

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "dixon_coles_rho_diagnosis.md")


class Agg:
    """Somme/contatori cumulativi per-team (Variante A: tutto lo storico).
    Riproduce esattamente il calcolo di run_walkforward (no-leakage)."""
    __slots__ = ("home_gf", "home_ga", "away_gf", "away_ga",
                 "home_gf_n", "home_ga_n", "away_gf_n", "away_ga_n")

    def __init__(self):
        self.home_gf = self.home_ga = self.away_gf = self.away_ga = 0.0
        self.home_gf_n = self.home_ga_n = self.away_gf_n = self.away_ga_n = 0


def team_attr(st, avg_h, avg_a):
    """Combined att/def ratio per team (same as stat() in run_walkforward)."""
    if st is None:
        return 1.0, 1.0
    att_h_ratio = (st.home_gf / st.home_gf_n) / avg_h if st.home_gf_n else 1.0
    def_h_ratio = (st.home_ga / st.home_ga_n) / avg_a if st.home_ga_n else 1.0
    att_a_ratio = (st.away_gf / st.away_gf_n) / avg_a if st.away_gf_n else 1.0
    def_a_ratio = (st.away_ga / st.away_ga_n) / avg_h if st.away_ga_n else 1.0
    att = (att_h_ratio + att_a_ratio) / 2
    def_ = (def_h_ratio + def_a_ratio) / 2
    return att, def_


def run_walkforward_lambda(df):
    """Per ogni partita (in ordine cronologico) calcola lambda_home/lambda_away
    con la logica walk-forward no-leakage. Ritorna DataFrame con season,
    lambda_h, lambda_a, FTHG, FTAG, real_1x2, real_uo, real_gg."""
    state = {}
    tot_fthg = tot_ftag = tot_n = 0.0
    rows = []
    for _, row in df.iterrows():
        h, a = row.HomeClean, row.AwayClean
        ftr = str(row.FTR).strip().upper()
        avg_h = max(tot_fthg / tot_n, 0.1) if tot_n else 0.1
        avg_a = max(tot_ftag / tot_n, 0.1) if tot_n else 0.1
        st_h = state.get(h)
        st_a = state.get(a)
        att_h, def_h = team_attr(st_h, avg_h, avg_a)
        att_a, def_a = team_attr(st_a, avg_h, avg_a)
        lam_h = att_h * def_a * avg_h
        lam_a = att_a * def_h * avg_a

        real_1x2 = {"H": "1", "D": "X", "A": "2"}.get(ftr, "X")
        tot_goals = row.FTHG + row.FTAG
        real_uo = "OVER" if tot_goals > 2.5 else "UNDER"
        real_gg = "GG" if row.FTHG > 0 and row.FTAG > 0 else "NG"

        rows.append({
            "season": row.season,
            "lambda_h": lam_h, "lambda_a": lam_a,
            "FTHG": row.FTHG, "FTAG": row.FTAG,
            "real_1x2": real_1x2, "real_uo": real_uo, "real_gg": real_gg,
        })

        # aggiorna dopo la previsione (no-leakage)
        tot_fthg += row.FTHG; tot_ftag += row.FTAG; tot_n += 1
        if h not in state:
            state[h] = Agg()
        if a not in state:
            state[a] = Agg()
        state[h].home_gf += row.FTHG; state[h].home_gf_n += 1
        state[h].home_ga += row.FTAG; state[h].home_ga_n += 1
        state[a].away_gf += row.FTAG; state[a].away_gf_n += 1
        state[a].away_ga += row.FTHG; state[a].away_ga_n += 1

    return pd.DataFrame(rows)


def build_matrix(lam_h, lam_a, rho, max_goals=MAX_GOALS):
    """Matrice congiunta Poisson + tau di Dixon-Coles (4 celle basse) + rinorm."""
    h_p = np.array([scipy_poisson.pmf(i, lam_h) for i in range(max_goals)])
    a_p = np.array([scipy_poisson.pmf(i, lam_a) for i in range(max_goals)])
    M = np.outer(h_p, a_p)
    if rho != 0.0:
        M[0, 0] *= 1 - lam_h * lam_a * rho
        M[1, 0] *= 1 + lam_a * rho
        M[0, 1] *= 1 + lam_h * rho
        M[1, 1] *= 1 - rho
        M = np.maximum(M, 0.0)      # sicurezza (tau puo' rendere negativa una cella)
        s = M.sum()
        if s > 0:
            M = M / s
    return M


def market_probs_from_matrix(M):
    p1 = float(np.sum(np.tril(M, -1)))
    pX = float(np.sum(np.diag(M)))
    p2 = float(np.sum(np.triu(M, 1)))
    po25 = 0.0
    n = M.shape[0]
    for i in range(n):
        for j in range(n):
            if i + j > 2.5:
                po25 += M[i, j]
    pgg = float(np.sum(M[1:, 1:]))
    return {"1": p1, "X": pX, "2": p2, "o25": po25, "gg": pgg, "M": M}


def exact_probs_from_matrix(M, top_scores, max_goals=MAX_GOALS):
    """Probabilita' per i top-score + 'altro'."""
    p = []
    for s in top_scores:
        i, j = int(s[0]), int(s[1])
        if i < max_goals and j < max_goals:
            p.append(float(M[i, j]))
        else:
            p.append(0.0)
    resto = 1.0 - sum(p)
    return p + [max(resto, 0.0)]


def match_ll(lam_h, lam_a, x, y, rho):
    """Log-verosimiglianza di una singola partita (risultato esatto x-y)."""
    if x == 0 and y == 0:
        tau = 1 - lam_h * lam_a * rho
    elif x == 1 and y == 0:
        tau = 1 + lam_a * rho
    elif x == 0 and y == 1:
        tau = 1 + lam_h * rho
    elif x == 1 and y == 1:
        tau = 1 - rho
    else:
        tau = 1.0
    tau = max(tau, 1e-8)
    return float(np.log(tau))  # i termini Poisson non dipendono da rho


def estimate_rho(train_df):
    """MLE di rho su risultati esatti. train_df: lambda_h, lambda_a, FTHG, FTAG."""
    lh = train_df["lambda_h"].to_numpy()
    la = train_df["lambda_a"].to_numpy()
    x = train_df["FTHG"].astype(int).to_numpy()
    y = train_df["FTAG"].astype(int).to_numpy()

    def neg_ll(rho):
        s = 0.0
        for i in range(len(lh)):
            s += match_ll(lh[i], la[i], x[i], y[i], rho)
        return -s

    res = minimize_scalar(neg_ll, bounds=(-RHO_BOUND, RHO_BOUND), method="bounded")
    return float(res.x)


def brier_logloss(probs, y_true):
    """probs: (n, n_class); y_true: (n,) indici di classe. Ritorna (brier, logloss)."""
    n = len(y_true)
    onehot = np.zeros_like(probs)
    onehot[np.arange(n), y_true] = 1
    brier = float(np.mean(np.sum((onehot - probs) ** 2, axis=1)))
    pc = np.clip(probs[np.arange(n), y_true], 1e-12, 1.0)
    logloss = float(-np.mean(np.log(pc)))
    return brier, logloss


def class_index(values, y_true_map):
    """values: array di valori veri; y_true_map: dict valore->indice. Ritorna array indici."""
    return np.array([y_true_map[v] for v in values])


def top_scores(df, k=EXACT_TOP):
    c = Counter(zip(df["FTHG"].astype(int), df["FTAG"].astype(int)))
    return [[int(a), int(b)] for (a, b), _ in c.most_common(k)]


def evaluate_sample(df, rho_map, league):
    """Applica rho_map = {'RHO_ZERO':0.0,'RHO_GLOBALE':rg,'RHO_LEGA':rl} alle partite di df.
    Ritorna dict variante -> {market: (brier, logloss)} e la matrice ex.top score."""
    top6 = top_scores(df)
    class_of_score = {tuple(s): i for i, s in enumerate(top6)}
    n_altro = EXACT_TOP

    results = {}
    for var, rho in rho_map.items():
        p1x2 = []; y1x2 = []
        p_uo = []; y_uo = []
        p_gg = []; y_gg = []
        p_ex = []; y_ex = []
        for _, r in df.iterrows():
            M = build_matrix(r["lambda_h"], r["lambda_a"], rho)
            m = market_probs_from_matrix(M)
            p1x2.append([m["1"], m["X"], m["2"]])
            y1x2.append({"1": 0, "X": 1, "2": 2}[r["real_1x2"]])
            p_uo.append([m["o25"], 1 - m["o25"]])
            y_uo.append(0 if r["real_uo"] == "OVER" else 1)
            p_gg.append([m["gg"], 1 - m["gg"]])
            y_gg.append(0 if r["real_gg"] == "GG" else 1)
            pe = exact_probs_from_matrix(M, top6)
            p_ex.append(pe)
            y_ex.append(class_of_score.get((int(r["FTHG"]), int(r["FTAG"])), n_altro))
        results[var] = {
            "1X2": brier_logloss(np.array(p1x2), np.array(y1x2)),
            "O/U2.5": brier_logloss(np.array(p_uo), np.array(y_uo)),
            "GG/NG": brier_logloss(np.array(p_gg), np.array(y_gg)),
            "Risultato esatto": brier_logloss(np.array(p_ex), np.array(y_ex)),
        }
        results[var]["_top6"] = top6
    return results


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    # --- raccogli lambda per tutte le partite di ogni lega ---
    league_dfs = {}
    all_train = []
    all_eval = []
    for prefix, camp_key in LEAGUES:
        df = load_league(prefix)
        rl = run_walkforward_lambda(df)
        league_dfs[camp_key] = rl
        tr = rl[rl["season"].isin(TRAIN_SEASONS)]
        ev = rl[rl["season"].isin(SEASONS)]
        all_train.append(tr)
        all_eval.append(ev)

    train_all = pd.concat(all_train, ignore_index=True)
    eval_all = pd.concat(all_eval, ignore_index=True)

    # --- stima rho ---
    rho_lega = {}
    for prefix, camp_key in LEAGUES:
        tr = league_dfs[camp_key]
        tr = tr[tr["season"].isin(TRAIN_SEASONS)]
        rho_lega[camp_key] = estimate_rho(tr)
    rho_globale = estimate_rho(train_all)

    lines = []
    lines.append("# Diagnosi rho Dixon-Coles (tau su 4 celle basse)")
    lines.append("")
    lines.append("Stima MLE di rho su training 2022/23+2023/24 (solo dati di training, "
                 "lambda walk-forward no-leakage). Applicazione su VALIDATION 2024/25 + "
                 "TEST 2025/26. Baseline RHO_ZERO = rho 0 (Poisson puro).")
    lines.append("")

    # --- rho stimati ---
    lines.append("## Valori di rho stimati")
    lines.append("")
    lines.append("| Variante | Lega | rho |")
    lines.append("|---|---|---|")
    lines.append(f"| RHO_ZERO | tutte | 0.0000 |")
    lines.append(f"| RHO_GLOBALE | pooled 5 leghe | {rho_globale:.4f} |")
    for prefix, camp_key in LEAGUES:
        lines.append(f"| RHO_LEGA | {camp_key} | {rho_lega[camp_key]:.4f} |")
    lines.append("")

    # --- valutazione per lega ---
    for prefix, camp_key in LEAGUES:
        ev = league_dfs[camp_key]
        ev = ev[ev["season"].isin(SEASONS)]
        rho_map = {"RHO_ZERO": 0.0, "RHO_GLOBALE": rho_globale, "RHO_LEGA": rho_lega[camp_key]}
        res = evaluate_sample(ev, rho_map, camp_key)
        lines.append(f"\n## {camp_key.upper()}  (N={len(ev)} val+test)")
        lines.append("")
        lines.append("| Mercato | metrica | RHO_ZERO | RHO_GLOBALE | RHO_LEGA |")
        lines.append("|---|---|---|---|---|")
        for market in ["1X2", "O/U2.5", "GG/NG", "Risultato esatto"]:
            bz, lz = res["RHO_ZERO"][market]
            bg, lg = res["RHO_GLOBALE"][market]
            bl, ll = res["RHO_LEGA"][market]
            lines.append(f"| {market} | Brier | {bz:.4f} | {bg:.4f} | {bl:.4f} |")
            lines.append(f"| {market} | LogLoss | {lz:.4f} | {lg:.4f} | {ll:.4f} |")
        lines.append(f"_(top-6 punteggi esatti: "
                     f"{', '.join(f'{a}-{b}' for a,b in res['RHO_ZERO']['_top6'])})_")
        lines.append("")

    # --- aggregato ---
    rho_map_agg = {"RHO_ZERO": 0.0, "RHO_GLOBALE": rho_globale, "RHO_LEGA": rho_globale}
    # per aggregato RHO_LEGA coincide con il pooling (un solo rho)
    res_agg = evaluate_sample(eval_all, {"RHO_ZERO": 0.0, "RHO_GLOBALE": rho_globale}, None)
    lines.append("\n## AGGREGATO — 5 LEGHE  (N=%d val+test)" % len(eval_all))
    lines.append("")
    lines.append("| Mercato | metrica | RHO_ZERO | RHO_GLOBALE |")
    lines.append("|---|---|---|---|")
    for market in ["1X2", "O/U2.5", "GG/NG", "Risultato esatto"]:
        bz, lz = res_agg["RHO_ZERO"][market]
        bg, lg = res_agg["RHO_GLOBALE"][market]
        lines.append(f"| {market} | Brier | {bz:.4f} | {bg:.4f} |")
        lines.append(f"| {market} | LogLoss | {lz:.4f} | {lg:.4f} |")
    lines.append(f"_(nota: nell'aggregato RHO_LEGA coincide con RHO_GLOBALE perche' il "
                 f"pooling ha un unico rho; il confronto per-lega RHO_LEGA vs RHO_GLOBALE e' "
                 f"sopra)_")
    lines.append("")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Scritto: {OUT_PATH}")


if __name__ == "__main__":
    main()
