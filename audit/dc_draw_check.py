"""
dc_draw_check.py — Confronto Dixon-Coles vs SoccerMath (smfix) SOLO sull'esito pareggio (X), 5 leghe.

Nuovo script di SOLA analisi: legge le colonne gia' esistenti del walk-forward
generato da backtest_experiment_all.run_walkforward (dc_X da Dixon-Coles, smfix_X
= SoccerMath Poisson+Elo, real_1x2). La prob. di pareggio Dixon-Coles qui e' gia'
calcolata con lo stesso refit ogni 10 partite (fit su storico strettamente
precedente, no-leakage) gia' usato in dixon_coles_comparison.txt.
Non tocca backtest_experiment_all.py, analyze_all.py, app.py, config.py, models/.

Confronto SOLO su X (esito pareggio), sia su VALIDATION 2024/25 sia su TEST 2025/26:
- Brier / Log Loss binari (real_1x2 == 'X') per dc_X vs smfix_X
- tabella di calibrazione fine sui pareggi (bins 0-20/20-24/24-28/28-32/32-36/36-50/50-101%)
  per dc_X vs smfix_X
"""
import os
import sys
import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from backtest_experiment_all import load_league, run_walkforward, LEAGUES
from analyze_all import calibration_table
from draw_correction import DRAW_BINS, brier_binary, log_loss_binary


def dc_draw_check(prefix, camp_key):
    df_all = load_league(prefix)
    bt = run_walkforward(df_all, camp_key=camp_key)

    print(f"\n{'='*80}\n{camp_key.upper()}\n{'='*80}")

    for label, season in [("VALIDATION 2024/25", "2024/25"), ("TEST 2025/26", "2025/26")]:
        sub = bt[bt["season"] == season]
        if sub.empty:
            print(f"\n{label}: nessuna partita.")
            continue
        yX = (sub["real_1x2"] == "X").astype(int).to_numpy()

        print(f"\n-- {label} — Brier/LogLoss binari su esito X (dc_X vs smfix_X) --")
        p_dc = sub["dc_X"].to_numpy(dtype=float)
        p_sm = sub["smfix_X"].to_numpy(dtype=float)
        print(f"  Dixon-Coles (dc_X):   Brier={brier_binary(yX, p_dc):.4f}  LogLoss={log_loss_binary(yX, p_dc):.4f}")
        print(f"  SoccerMath (smfix_X):  Brier={brier_binary(yX, p_sm):.4f}  LogLoss={log_loss_binary(yX, p_sm):.4f}")

        print(f"\n-- {label} — Calibrazione fine esito X: Dixon-Coles (dc_X) --")
        print(calibration_table(sub, "dc_X", target="X", bins=DRAW_BINS).to_string())

        print(f"\n-- {label} — Calibrazione fine esito X: SoccerMath (smfix_X) --")
        print(calibration_table(sub, "smfix_X", target="X", bins=DRAW_BINS).to_string())


def main():
    for prefix, camp_key in LEAGUES:
        dc_draw_check(prefix, camp_key)


if __name__ == "__main__":
    main()
