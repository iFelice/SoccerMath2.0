"""
calibration_check.py — Verifica di ricalibrazione del modello SoccerMath (xG fix) sulle 5 leghe.

Nuovo script di SOLA analisi: legge le colonne gia' esistenti del walk-forward
(smfix_1/X/2 = SoccerMath con Elo xG-fix, real_1x2) e le quote B365 / Average.
Non tocca backtest_experiment_all.py, analyze_all.py, app.py, config.py, models/.

Procedura (per ogni lega):
1. FIT SOLO su 2024/25 (validation): per ciascuno dei 3 esiti (1, X, 2) allena DUE
   calibratori binari — IsotonicRegression(increasing=True, out_of_bounds="clip") e
   LogisticRegression() (proxy Platt scaling, fit sulla prob. grezza come singola
   feature) — sul target reale binario (real_1x2 == esito).
2. SELEZIONE SOLO su validation: confronta Brier e Log Loss dei due calibratori
   (Isotonic vs Platt) SEMPRE su 2024/25, mai sul test. Vince il calibratore con
   Log Loss migliore (metrica di proper scoring). Riporta entrambi i punteggi.
3. CONGELA e APPLICA SOLO su 2025/26 (test): usa il calibratore vincente (gia'
   fittato) per trasformare smfix_1/X/2 in sm_cal_1/X/2, poi rinormalizza a somma 1.
4. Sul test ricalcola Brier/LogLoss/ROI/win rate/edge medio (vs B365 e vs Average
   Market) con le prob. calibrate, a confronto diretto con quelle non calibrate.
5. Tabella di calibrazione (stesse fasce gia' usate per Serie A) per l'esito "1",
   prima e dopo la ricalibrazione, sul test.
"""
import os
import sys
import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from backtest_experiment_all import load_league, run_walkforward, LEAGUES, STAKE, EDGE_MIN
from analyze_all import model_metrics_1x2, simulate_roi_1x2, calibration_table


OUTCOMES = ["1", "X", "2"]
PROB_COLS = {"1": "smfix_1", "X": "smfix_X", "2": "smfix_2"}


def log_loss_binary(y_true, y_prob):
    eps = 1e-15
    p = np.clip(y_prob, eps, 1 - eps)
    return float(-np.mean(y_true * np.log(p) + (1 - y_true) * np.log(1 - p)))


def brier_binary(y_true, y_prob):
    return float(np.mean((y_true - y_prob) ** 2))


def fit_and_select_calibrators(val_df):
    """
    Per ciascun esito: fitta Isotonic e Platt (Logistic) su validation, calcola
    Brier/LogLoss binari su validation per entrambi, e sceglie il vincitore.
    Ritorna un dict {esito: {"winner": "isotonic"/"platt", "model": <calibratore>,
                             "isotonic": (brier, logloss), "platt": (brier, logloss)}}.
    """
    result = {}
    for outcome in OUTCOMES:
        raw = val_df[PROB_COLS[outcome]].to_numpy(dtype=float)
        y = (val_df["real_1x2"] == outcome).astype(int).to_numpy()

        # --- Isotonic ---
        iso = IsotonicRegression(increasing=True, out_of_bounds="clip")
        iso.fit(raw, y)
        p_iso = iso.predict(raw)
        iso_metrics = (brier_binary(y, p_iso), log_loss_binary(y, p_iso))

        # --- Platt scaling (Logistic regression su prob grezza come feature) ---
        X = raw.reshape(-1, 1)
        lr = LogisticRegression()
        lr.fit(X, y)
        p_lr = lr.predict_proba(X)[:, 1]
        lr_metrics = (brier_binary(y, p_lr), log_loss_binary(y, p_lr))

        # selezione: vince chi ha Log Loss piu' basso
        winner = "isotonic" if iso_metrics[1] <= lr_metrics[1] else "platt"
        result[outcome] = {
            "winner": winner,
            "model": iso if winner == "isotonic" else lr,
            "isotonic": iso_metrics,
            "platt": lr_metrics,
        }
    return result


def apply_calibrators(cal_info, df):
    """Trasforma smfix_1/X/2 -> sm_cal_1/X/2 usando il calibratore vincente per esito."""
    cal = {}
    for outcome in OUTCOMES:
        raw = df[PROB_COLS[outcome]].to_numpy(dtype=float)
        model = cal_info[outcome]["model"]
        if cal_info[outcome]["winner"] == "isotonic":
            cal[outcome] = model.predict(raw)
        else:
            cal[outcome] = model.predict_proba(raw.reshape(-1, 1))[:, 1]
    # rinormalizza a somma 1
    total = sum(cal[o] for o in OUTCOMES)
    out = df.copy()
    out["sm_cal_1"] = cal["1"] / total
    out["sm_cal_X"] = cal["X"] / total
    out["sm_cal_2"] = cal["2"] / total
    return out


def metric_block(df, prob_cols, fair_cols, odd_cols, label):
    brier, logloss = model_metrics_1x2(df, prob_cols)
    res = simulate_roi_1x2(df, prob_cols, fair_cols, odd_cols)
    return {
        "Prob": label, "Brier": round(brier, 4), "LogLoss": round(logloss, 4),
        "Edge medio %": round(res["edge_medio"], 2), "ROI %": round(res["roi"], 2),
        "N. bet": res["n_bet"], "Win rate %": round(res["win_rate"], 1),
    }


def run_calibration_check(prefix, camp_key):
    df_all = load_league(prefix)
    bt = run_walkforward(df_all, camp_key=camp_key)

    val = bt[bt["season"] == "2024/25"]
    test = bt[bt["season"] == "2025/26"]
    print(f"\n{'='*80}\n{camp_key.upper()}  (val N={len(val)}, test N={len(test)})\n{'='*80}")

    # 1+2: fit e selezione su validation
    cal_info = fit_and_select_calibrators(val)

    print("\n-- Selezione calibratore su VALIDATION 2024/25 (Isotonic vs Platt) --")
    for outcome in OUTCOMES:
        ci = cal_info[outcome]
        ib, il = ci["isotonic"]; pb, pl = ci["platt"]
        print(f"  Esito {outcome}: vincitore = {ci['winner']}  | "
              f"Isotonic Brier={ib:.4f} LogLoss={il:.4f}  |  "
              f"Platt Brier={pb:.4f} LogLoss={pl:.4f}")

    # 3: applica su test
    test_cal = apply_calibrators(cal_info, test)

    # 4: metriche su test, calibrate vs non calibrate
    fair_b365 = ("fair_b365_1", "fair_b365_X", "fair_b365_2")
    fair_avg = ("fair_avg_1", "fair_avg_X", "fair_avg_2")
    odd_b365 = ("B365H", "B365D", "B365A")
    odd_avg = ("AvgH", "AvgD", "AvgA")
    cal_cols = ("sm_cal_1", "sm_cal_X", "sm_cal_2")
    raw_cols = ("smfix_1", "smfix_X", "smfix_2")

    print(f"\n-- TEST 2025/26: Brier/LogLoss + ROI, non calibrato vs calibrato (vs B365) --")
    print(pd.DataFrame([
        metric_block(test, raw_cols, fair_b365, odd_b365, "sm_fix (non cal)"),
        metric_block(test_cal, cal_cols, fair_b365, odd_b365, "sm_cal (ricalibrato)"),
    ]).to_string(index=False))

    print(f"\n-- TEST 2025/26: Brier/LogLoss + ROI, non calibrato vs calibrato (vs Average Market) --")
    print(pd.DataFrame([
        metric_block(test, raw_cols, fair_avg, odd_avg, "sm_fix (non cal)"),
        metric_block(test_cal, cal_cols, fair_avg, odd_avg, "sm_cal (ricalibrato)"),
    ]).to_string(index=False))

    # 5: tabella di calibrazione esito "1" sul test, prima e dopo
    print(f"\n-- Calibrazione esito '1' su TEST 2025/26: PRIMA (sm_fix_1) --")
    print(calibration_table(test, "smfix_1", target="1").to_string())
    print(f"\n-- Calibrazione esito '1' su TEST 2025/26: DOPO (sm_cal_1) --")
    print(calibration_table(test_cal, "sm_cal_1", target="1").to_string())


def main():
    for prefix, camp_key in LEAGUES:
        run_calibration_check(prefix, camp_key)


if __name__ == "__main__":
    main()
