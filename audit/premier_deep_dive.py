"""
premier_deep_dive.py — Deep dive Dixon-Coles SOLO su Premier League (entrambe le stagioni 2024/25 e 2025/26).

Analisi nuova e separata (non tocca backtest_experiment_all.py / analyze_all.py / app.py /
config.py / models/). Usa le colonne gia' esistenti dc_1/X/2, quote B365 e Average:

1. ROI / win rate / edge medio per Dixon-Coles contro Average Market (oltre a B365 gia' fatto),
   stesso metodo simulate_roi_1x2 usato per gli altri modelli.
2. Sweep di soglia edge minimo (0, 2, 4, 6, 8, 10%) su Dixon-Coles Premier League,
   sia vs B365 sia vs Average Market: n.bet / win rate / ROI per ogni soglia.
3. Intervallo di confidenza bootstrap al 95% sul ROI di Dixon-Coles vs B365 (edge_min=0):
   ricampiona le scommesse con rimpiazzo 2000 volte, ROI per ciascun ricampionamento,
   2.5° e 97.5° percentile della distribuzione.

Limitato alla Premier League: non ripete nulla sulle altre leghe.
"""
import sys
import os
import numpy as np

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AUDIT_DIR)
from backtest_experiment_all import load_league, run_walkforward, STAKE, EDGE_MIN
from analyze_all import simulate_roi_1x2


def collect_bets(df, prob_cols, fair_cols, odd_cols, edge_min=EDGE_MIN):
    """
    Come simulate_roi_1x2 ma ritorna la serie delle singole scommesse
    (profit e vincita) invece delle metriche aggregate. Serve per il bootstrap.
    """
    p1, pX, p2 = prob_cols
    f1, fX, f2 = fair_cols
    o1, oX, o2 = odd_cols
    outcomes = ["1", "X", "2"]
    bets = []
    for _, row in df.iterrows():
        probs = {"1": row[p1], "X": row[pX], "2": row[p2]}
        fair = {"1": row[f1], "X": row[fX], "2": row[f2]}
        odds = {"1": row[o1], "X": row[oX], "2": row[o2]}
        if any(pd_isna(v) for v in fair.values()):
            continue
        if any(pd_isna(v) for v in probs.values()):
            continue
        edge_by_out = {k: probs[k] - fair[k] for k in outcomes}
        best = max(edge_by_out, key=edge_by_out.get)
        edge = edge_by_out[best]
        if edge <= edge_min:
            continue
        won = row["real_1x2"] == best
        profit = STAKE * (odds[best] - 1) if won else -STAKE
        bets.append({"profit": profit, "won": won, "odd": odds[best], "edge": edge})
    return bets


def pd_isna(v):
    return v is None or (isinstance(v, float) and np.isnan(v))


def bootstrap_roi_ci(bets, n_resamples=2000, seed=42, percentile=(2.5, 97.5)):
    """
    Bootstrap non parametrico al 95% sul ROI: ricampiona con rimpiazzo le n_bet
    scommesse, calcola il ROI di ogni ricampionamento, ritorna i percentili.
    """
    if not bets:
        return {"n_bet": 0, "ci_low": 0.0, "ci_high": 0.0, "roi_obs": 0.0}
    profits = np.array([b["profit"] for b in bets])
    n_bet = len(profits)
    rng = np.random.default_rng(seed)
    rois = []
    for _ in range(n_resamples):
        sample = rng.choice(profits, size=n_bet, replace=True)
        roi = (sample.sum() / (n_bet * STAKE) * 100)
        rois.append(roi)
    rois = np.array(rois)
    lo, hi = np.percentile(rois, percentile)
    roi_obs = (profits.sum() / (n_bet * STAKE) * 100)
    return {"n_bet": n_bet, "ci_low": lo, "ci_high": hi, "roi_obs": roi_obs}


def premier_deep_dive():
    camp_key = "Premier League"
    prefix = "Premier"
    df_all = load_league(prefix)
    bt = run_walkforward(df_all, camp_key=camp_key)

    dc_prob = ("dc_1", "dc_X", "dc_2")
    b365_fair = ("fair_b365_1", "fair_b365_X", "fair_b365_2")
    avg_fair = ("fair_avg_1", "fair_avg_X", "fair_avg_2")
    b365_odd = ("B365H", "B365D", "B365A")
    avg_odd = ("AvgH", "AvgD", "AvgA")

    seasons = {"2024/25 (validation)": "2024/25", "2025/26 (test)": "2025/26"}
    thresholds = [0.0, 0.02, 0.04, 0.06, 0.08, 0.10]

    for label, season in seasons.items():
        sub = bt[bt["season"] == season]
        print(f"\n{'='*78}\nPREMIER LEAGUE — {label}  (N={len(sub)} partite)\n{'='*78}")
        if sub.empty:
            print("Nessuna partita in questo periodo.")
            continue

        # --- Punto 1: Dixon-Coles vs B365 e vs Average Market (edge_min=0) ---
        print("\n-- Punto 1: Dixon-Coles — ROI / win rate / edge medio, B365 vs Average Market --")
        rows = []
        for mkt, fair_cols, odd_cols in [
            ("B365", b365_fair, b365_odd),
            ("Average Market", avg_fair, avg_odd),
        ]:
            res = simulate_roi_1x2(sub, dc_prob, fair_cols, odd_cols)
            rows.append({"Mercato": mkt, "Edge medio %": round(res["edge_medio"], 2),
                         "ROI %": round(res["roi"], 2), "N. bet": res["n_bet"],
                         "Win rate %": round(res["win_rate"], 1)})
        print(pd_table(rows))

        # --- Punto 2: sweep soglia edge minimo, B365 e Average Market ---
        print("\n-- Punto 2: Sweep soglia edge minimo — Dixon-Coles, vs B365 --")
        print(sweep_table(sub, dc_prob, b365_fair, b365_odd, thresholds, "B365"))
        print("\n-- Punto 2: Sweep soglia edge minimo — Dixon-Coles, vs Average Market --")
        print(sweep_table(sub, dc_prob, avg_fair, avg_odd, thresholds, "Average Market"))

        # --- Punto 3: bootstrap 95% ROI Dixon-Coles vs B365 (edge_min=0) ---
        print("\n-- Punto 3: Bootstrap 95% ROI — Dixon-Coles vs B365 (edge_min=0), 2000 ricampionamenti --")
        bets = collect_bets(sub, dc_prob, b365_fair, b365_odd, edge_min=0.0)
        ci = bootstrap_roi_ci(bets)
        print(f"N. bet: {ci['n_bet']}   ROI osservato: {ci['roi_obs']:.2f}%   "
              f"IC 95%: [{ci['ci_low']:.2f}%, {ci['ci_high']:.2f}%]")


def pd_table(rows):
    import pandas as pd
    return pd.DataFrame(rows).to_string(index=False)


def sweep_table(sub, prob_cols, fair_cols, odd_cols, thresholds, mkt_label):
    import pandas as pd
    rows = []
    for t in thresholds:
        res = simulate_roi_1x2(sub, prob_cols, fair_cols, odd_cols, edge_min=t)
        rows.append({"Soglia edge": f"{int(t*100)}%",
                     "N. bet": res["n_bet"],
                     "Win rate %": round(res["win_rate"], 1),
                     "ROI %": round(res["roi"], 2)})
    return pd.DataFrame(rows).to_string(index=False)


if __name__ == "__main__":
    premier_deep_dive()
