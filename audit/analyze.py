import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "/home/claude/SoccerMath2.0/SoccerMath")
from models.backtest import calculate_brier_score, calculate_log_loss  # finalmente usate

from backtest_experiment import load_serie_a, run_walkforward, STAKE, EDGE_MIN

pd.set_option("display.width", 140)
pd.set_option("display.float_format", lambda x: f"{x:,.3f}")


def onehot_1x2(real_series):
    m = {"1": [1, 0, 0], "X": [0, 1, 0], "2": [0, 0, 1]}
    return np.array([m[r] for r in real_series])


def model_metrics_1x2(df, prob_cols, real_col="real_1x2"):
    """prob_cols = (col_1, col_X, col_2). Ritorna Brier, LogLoss."""
    y_true = onehot_1x2(df[real_col])
    y_prob = df[list(prob_cols)].to_numpy(dtype=float)
    brier = calculate_brier_score(y_true, y_prob)
    logloss = calculate_log_loss(y_true, y_prob)
    return brier, logloss


def simulate_roi_1x2(df, prob_cols, fair_cols, odd_cols, stake=STAKE, edge_min=EDGE_MIN):
    """
    Per ogni riga sceglie l'esito (1/X/2) con edge massimo = P_modello - P_fair.
    Scommette (quota REALE, non de-vigata) solo se edge > edge_min.
    Ritorna: n_bet, win_rate, roi, edge_medio, bankroll_history, max_drawdown.
    """
    p1, pX, p2 = prob_cols
    f1, fX, f2 = fair_cols
    o1, oX, o2 = odd_cols
    outcomes = ["1", "X", "2"]

    bankroll = 0.0
    history = [0.0]
    edges, n_bet, wins = [], 0, 0

    for _, row in df.iterrows():
        probs = {"1": row[p1], "X": row[pX], "2": row[p2]}
        fair = {"1": row[f1], "X": row[fX], "2": row[f2]}
        odds = {"1": row[o1], "X": row[oX], "2": row[o2]}
        if any(pd.isna(v) for v in fair.values()):
            continue
        edge_by_out = {k: probs[k] - fair[k] for k in outcomes}
        best = max(edge_by_out, key=edge_by_out.get)
        edge = edge_by_out[best]
        if edge <= edge_min:
            continue
        n_bet += 1
        edges.append(edge)
        if row["real_1x2"] == best:
            profit = stake * (odds[best] - 1)
            wins += 1
        else:
            profit = -stake
        bankroll += profit
        history.append(bankroll)

    roi = (bankroll / (n_bet * stake) * 100) if n_bet else 0.0
    win_rate = (wins / n_bet * 100) if n_bet else 0.0
    edge_medio = (np.mean(edges) * 100) if edges else 0.0
    hist = np.array(history)
    running_max = np.maximum.accumulate(hist)
    drawdown = hist - running_max
    max_dd = drawdown.min()
    return {"n_bet": n_bet, "win_rate": win_rate, "roi": roi,
            "edge_medio": edge_medio, "bankroll_finale": bankroll,
            "max_drawdown": max_dd, "history": history}


def simulate_roi_ou(df, prob_over_col, fair_over_col, fair_under_col,
                     odd_over_col, odd_under_col, stake=STAKE, edge_min=EDGE_MIN):
    bankroll, history, edges, n_bet, wins = 0.0, [0.0], [], 0, 0
    for _, row in df.iterrows():
        p_over = row[prob_over_col]
        f_over, f_under = row[fair_over_col], row[fair_under_col]
        o_over, o_under = row[odd_over_col], row[odd_under_col]
        if any(pd.isna(v) for v in (f_over, f_under, o_over, o_under)):
            continue
        p_under = 1 - p_over
        edge_over = p_over - f_over
        edge_under = p_under - f_under
        if edge_over >= edge_under:
            side, edge, odd = "OVER", edge_over, o_over
        else:
            side, edge, odd = "UNDER", edge_under, o_under
        if edge <= edge_min:
            continue
        n_bet += 1
        edges.append(edge)
        real = row["real_uo"]
        won = (side == "OVER" and real == "OVER") or (side == "UNDER" and real == "UNDER")
        profit = stake * (odd - 1) if won else -stake
        wins += won
        bankroll += profit
        history.append(bankroll)
    roi = (bankroll / (n_bet * stake) * 100) if n_bet else 0.0
    win_rate = (wins / n_bet * 100) if n_bet else 0.0
    edge_medio = (np.mean(edges) * 100) if edges else 0.0
    hist = np.array(history)
    max_dd = (hist - np.maximum.accumulate(hist)).min()
    return {"n_bet": n_bet, "win_rate": win_rate, "roi": roi,
            "edge_medio": edge_medio, "bankroll_finale": bankroll, "max_drawdown": max_dd}


def gg_calibration(df):
    """Solo calibrazione/Brier binario: nessuna quota GG/NG disponibile nel dataset."""
    y = (df["real_gg"] == "GG").astype(int).to_numpy()
    p = df["poisson_gg"].to_numpy(dtype=float)
    brier = np.mean((y - p) ** 2)
    eps = 1e-15
    p_c = np.clip(p, eps, 1 - eps)
    logloss = -np.mean(y * np.log(p_c) + (1 - y) * np.log(1 - p_c))
    return brier, logloss


def calibration_table(df, prob_col, real_col="real_1x2", target="1", bins=None):
    if bins is None:
        bins = [0, .50, .55, .60, .65, .70, .75, .80, 1.01]
    p = df[prob_col].to_numpy(dtype=float)
    real_hit = (df[real_col] == target).to_numpy()
    labels = [f"{int(bins[i]*100)}-{int(bins[i+1]*100)}%" for i in range(len(bins)-1)]
    cat = pd.cut(p, bins=bins, labels=labels, right=False)
    out = pd.DataFrame({"bucket": cat, "hit": real_hit}).groupby("bucket", observed=True).agg(
        n=("hit", "size"), tasso_reale=("hit", "mean"))
    out["tasso_reale"] = (out["tasso_reale"] * 100).round(1)
    return out


def main():
    df_all = load_serie_a()
    bt = run_walkforward(df_all)

    seasons = {"2024/25 (validation)": "2024/25", "2025/26 (test)": "2025/26", "2026/27 (monitor)": "2026/27"}

    for label, season in seasons.items():
        sub = bt[bt["season"] == season]
        print(f"\n{'='*70}\nSERIE A — {label}  (N={len(sub)} partite)\n{'='*70}")
        if sub.empty:
            print("Nessuna partita in questo periodo.")
            continue

        # --- Tabella 1: confronto modelli (Brier/LogLoss + ROI su B365) ---
        rows_t1 = []
        for name, cols in [("Poisson", ("poisson_1", "poisson_X", "poisson_2")),
                            ("Elo", ("elo_1", "elo_X", "elo_2")),
                            ("SoccerMath (0.6P+0.4Elo)", ("sm_1", "sm_X", "sm_2"))]:
            brier, logloss = model_metrics_1x2(sub, cols)
            roi_res = simulate_roi_1x2(sub, cols, ("fair_b365_1", "fair_b365_X", "fair_b365_2"),
                                        ("B365H", "B365D", "B365A"))
            rows_t1.append({"Modello": name, "Brier": round(brier, 4), "LogLoss": round(logloss, 4),
                             "N.bet": roi_res["n_bet"], "Win rate %": round(roi_res["win_rate"], 1),
                             "ROI % (vs B365)": round(roi_res["roi"], 2)})
        print("\n-- Tabella 1: Accuratezza & ROI per modello (1X2, edge vs B365) --")
        print(pd.DataFrame(rows_t1).to_string(index=False))

        # --- Tabella 2: SoccerMath completo, B365 vs Average market ---
        rows_t2 = []
        for mkt, fair_cols, odd_cols in [
            ("B365", ("fair_b365_1", "fair_b365_X", "fair_b365_2"), ("B365H", "B365D", "B365A")),
            ("Average Market", ("fair_avg_1", "fair_avg_X", "fair_avg_2"), ("AvgH", "AvgD", "AvgA")),
        ]:
            res = simulate_roi_1x2(sub, ("sm_1", "sm_X", "sm_2"), fair_cols, odd_cols)
            rows_t2.append({"Mercato": mkt, "Edge medio %": round(res["edge_medio"], 2),
                             "ROI %": round(res["roi"], 2), "N. value bet": res["n_bet"],
                             "Max drawdown €": round(res["max_drawdown"], 1)})
        print("\n-- Tabella 2: SoccerMath completo — 1X2, B365 vs Average Market --")
        print(pd.DataFrame(rows_t2).to_string(index=False))

        # --- Over/Under 2.5 ---
        ou_b365 = simulate_roi_ou(sub, "poisson_o25", "fair_b365_o25", "fair_b365_u25", "B365_o25", "B365_u25")
        ou_avg = simulate_roi_ou(sub, "poisson_o25", "fair_avg_o25", "fair_avg_u25", "Avg_o25", "Avg_u25")
        print("\n-- Over/Under 2.5 (Poisson), B365 vs Average Market --")
        print(pd.DataFrame([
            {"Mercato": "B365", "Edge medio %": round(ou_b365["edge_medio"], 2), "ROI %": round(ou_b365["roi"], 2),
             "N. value bet": ou_b365["n_bet"], "Max drawdown €": round(ou_b365["max_drawdown"], 1)},
            {"Mercato": "Average Market", "Edge medio %": round(ou_avg["edge_medio"], 2), "ROI %": round(ou_avg["roi"], 2),
             "N. value bet": ou_avg["n_bet"], "Max drawdown €": round(ou_avg["max_drawdown"], 1)},
        ]).to_string(index=False))

        # --- GG/NG: solo calibrazione, niente quote ---
        gg_brier, gg_logloss = gg_calibration(sub)
        print(f"\n-- GG/NG: solo probabilita'/calibrazione (nessuna quota BTTS nel dataset) --")
        print(f"Brier: {gg_brier:.4f}   LogLoss: {gg_logloss:.4f}")

    # --- Calibrazione dettagliata sul TEST storico (2025/26), SoccerMath, esito '1' ---
    test = bt[bt["season"] == "2025/26"]
    if not test.empty:
        print(f"\n{'='*70}\nCalibrazione dettagliata — SoccerMath, esito '1' (casa vince) — TEST 2025/26\n{'='*70}")
        print(calibration_table(test, "sm_1", target="1").to_string())


if __name__ == "__main__":
    main()
