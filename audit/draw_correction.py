"""
draw_correction.py — Correzione a bassa varianza della probabilità di pareggio (X) sulle 5 leghe.

Nuovo script di SOLA analisi: legge le colonne gia' esistenti del walk-forward
(smfix_1/X/2 = SoccerMath con Elo xG-fix, real_1x2) e le quote B365 / Average.
Non tocca backtest_experiment_all.py, analyze_all.py, app.py, config.py, models/.

Metodo (per ogni lega):
1. FIT SOLO su 2024/25 (validation): allena LogisticRegression() (Platt scaling,
   2 parametri: intercetta + coefficiente) sulla prob. grezza smfix_X come singola
   feature, target binario real_1x2 == "X". NIENTE Isotonic (metodo gia' scartato).
2. CONGELA e APPLICA SOLO su 2025/26 (test): trasforma smfix_X in smfix_X_corrected
   con il calibratore fittato. Ricalcola smfix_1 e smfix_2 proporzionalmente cosi'
   che i tre sommino a 1 (mantiene il rapporto originale tra 1 e 2, scala solo lo
   spazio rimasto dopo aver fissato X).
3. Sul test confronta PRIMA vs DOPO:
   - Brier/LogLoss binari specifici sull'esito X
   - tabella di calibrazione fine sui pareggi (bins 0-20/20-24/24-28/28-32/32-36/
     36-50/50-101%)
   - sull'intero 1X2 con le prob. corrette: Brier/LogLoss/ROI/win rate vs B365 e
     vs Average Market (stesso simulate_roi_1x2 gia' usato ovunque).
"""
import os
import sys
import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from sklearn.linear_model import LogisticRegression

from backtest_experiment_all import load_league, run_walkforward, LEAGUES, STAKE, EDGE_MIN
from analyze_all import simulate_roi_1x2, calibration_table


# Fasce fine sui pareggi (come richiesto)
DRAW_BINS = [0, 0.20, 0.24, 0.28, 0.32, 0.36, 0.50, 1.01]


def brier_binary(y_true, y_prob):
    return float(np.mean((y_true - y_prob) ** 2))


def log_loss_binary(y_true, y_prob):
    eps = 1e-15
    p = np.clip(y_prob, eps, 1 - eps)
    return float(-np.mean(y_true * np.log(p) + (1 - y_true) * np.log(1 - p)))


def fit_draw_calibrator(val_df):
    """Fit LogisticRegression su validation: smfix_X -> P(esito X)."""
    X = val_df["smfix_X"].to_numpy(dtype=float).reshape(-1, 1)
    y = (val_df["real_1x2"] == "X").astype(int).to_numpy()
    lr = LogisticRegression()
    lr.fit(X, y)
    return lr


def apply_draw_correction(lr, test_df):
    """
    Applica il calibratore al test: corregge smfix_X, poi rinormalizza 1 e 2
    proporzionalmente (mantiene il rapporto originale 1:2, scala lo spazio rimasto).
    Ritorna una copia del test con colonne smfix_X_corrected / smfix_1_corrected /
    smfix_2_corrected.
    """
    out = test_df.copy()
    X = out["smfix_X"].to_numpy(dtype=float).reshape(-1, 1)
    x_corr = lr.predict_proba(X)[:, 1]
    out["smfix_X_corrected"] = x_corr

    p1 = out["smfix_1"].to_numpy(dtype=float)
    p2 = out["smfix_2"].to_numpy(dtype=float)
    denom = p1 + p2
    # evita divisione per zero (fallback: ripartizione uguale)
    ratio1 = np.where(denom > 0, p1 / np.where(denom > 0, denom, 1.0), 0.5)
    remaining = 1.0 - x_corr
    out["smfix_1_corrected"] = remaining * ratio1
    out["smfix_2_corrected"] = remaining * (1.0 - ratio1)
    return out


def full_1x2_metrics(df, prob_cols, fair_cols, odd_cols):
    """Brier/LogLoss (1X2) + ROI/win rate/edge medio via simulate_roi_1x2."""
    # Brier/LogLoss multiclasse 1X2
    onehot = {"1": [1, 0, 0], "X": [0, 1, 0], "2": [0, 0, 1]}
    y_true = np.array([onehot[r] for r in df["real_1x2"]])
    y_prob = df[list(prob_cols)].to_numpy(dtype=float)
    brier = float(np.mean(np.sum((y_true - y_prob) ** 2, axis=1)))
    p_clip = np.clip(y_prob, 1e-15, 1 - 1e-15)
    logloss = float(-np.mean(np.sum(y_true * np.log(p_clip), axis=1)))

    res = simulate_roi_1x2(df, prob_cols, fair_cols, odd_cols)
    return {
        "Brier": round(brier, 4), "LogLoss": round(logloss, 4),
        "Edge medio %": round(res["edge_medio"], 2), "ROI %": round(res["roi"], 2),
        "N. bet": res["n_bet"], "Win rate %": round(res["win_rate"], 1),
    }


def run_draw_correction(prefix, camp_key):
    df_all = load_league(prefix)
    bt = run_walkforward(df_all, camp_key=camp_key)

    val = bt[bt["season"] == "2024/25"]
    test = bt[bt["season"] == "2025/26"]
    print(f"\n{'='*80}\n{camp_key.upper()}  (val N={len(val)}, test N={len(test)})\n{'='*80}")

    # 1+2: fit su validation, applica su test
    lr = fit_draw_calibrator(val)
    test_corr = apply_draw_correction(lr, test)

    # --- 3a: Brier/LogLoss binari su X, prima vs dopo ---
    yX = (test["real_1x2"] == "X").astype(int).to_numpy()
    pX_before = test["smfix_X"].to_numpy(dtype=float)
    pX_after = test_corr["smfix_X_corrected"].to_numpy(dtype=float)
    print("\n-- Esito X (binario) su TEST 2025/26: PRIMA vs DOPO --")
    print(f"  PRIMA (smfix_X):    Brier={brier_binary(yX, pX_before):.4f}  LogLoss={log_loss_binary(yX, pX_before):.4f}")
    print(f"  DOPO  (corrected):  Brier={brier_binary(yX, pX_after):.4f}  LogLoss={log_loss_binary(yX, pX_after):.4f}")

    # --- 3b: tabella di calibrazione fine sui pareggi ---
    print("\n-- Calibrazione fine sui pareggi su TEST 2025/26: PRIMA (smfix_X) --")
    print(calibration_table(test, "smfix_X", target="X", bins=DRAW_BINS).to_string())
    print("\n-- Calibrazione fine sui pareggi su TEST 2025/26: DOPO (smfix_X_corrected) --")
    print(calibration_table(test_corr, "smfix_X_corrected", target="X", bins=DRAW_BINS).to_string())

    # --- 3c: 1X2 completo, B365 e Average, prima vs dopo ---
    fair_b365 = ("fair_b365_1", "fair_b365_X", "fair_b365_2")
    fair_avg = ("fair_avg_1", "fair_avg_X", "fair_avg_2")
    odd_b365 = ("B365H", "B365D", "B365A")
    odd_avg = ("AvgH", "AvgD", "AvgA")

    print("\n-- 1X2 completo su TEST 2025/26, vs B365: PRIMA vs DOPO --")
    print(pd.DataFrame([
        {"Prob": "smfix (PRIMA)", **full_1x2_metrics(test, ("smfix_1", "smfix_X", "smfix_2"), fair_b365, odd_b365)},
        {"Prob": "corrected (DOPO)", **full_1x2_metrics(test_corr, ("smfix_1_corrected", "smfix_X_corrected", "smfix_2_corrected"), fair_b365, odd_b365)},
    ]).to_string(index=False))

    print("\n-- 1X2 completo su TEST 2025/26, vs Average Market: PRIMA vs DOPO --")
    print(pd.DataFrame([
        {"Prob": "smfix (PRIMA)", **full_1x2_metrics(test, ("smfix_1", "smfix_X", "smfix_2"), fair_avg, odd_avg)},
        {"Prob": "corrected (DOPO)", **full_1x2_metrics(test_corr, ("smfix_1_corrected", "smfix_X_corrected", "smfix_2_corrected"), fair_avg, odd_avg)},
    ]).to_string(index=False))


def main():
    for prefix, camp_key in LEAGUES:
        run_draw_correction(prefix, camp_key)


if __name__ == "__main__":
    main()
