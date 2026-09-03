"""
ou_gg_calibration.py — Calibrazione su Over 2.5 e GG (Poisson), 5 leghe, validation + test.

Nuovo script di SOLA analisi: legge le colonne gia' esistenti del walk-forward
generato da backtest_experiment_all.run_walkforward (poisson_o25 = P(Over 2.5),
poisson_gg = P(GG), real_uo = OVER/UNDER, real_gg = GG/NG).
Non tocca backtest_experiment_all.py, analyze_all.py, app.py, config.py, models/.

Per ciascuna lega, su VALIDATION 2024/25 e TEST 2025/26:
1. Brier / Log Loss binari su Over 2.5 e su GG, separatamente.
2. Tabella di calibrazione fine per Over 2.5 (bins 0-40/40-45/45-50/50-55/55-60/60-101%)
   e per GG (stessi bins).
3. Media probabilita' dichiarata vs tasso reale, per entrambi i mercati
   (come gia' fatto per i pareggi).
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
from draw_correction import brier_binary, log_loss_binary


# Fasce fine per Over/Under 2.5 e GG
BINS_OU = [0, 0.40, 0.45, 0.50, 0.55, 0.60, 1.01]


def fine_calib_table(df, prob_col, real_col, target, bins):
    p = df[prob_col].to_numpy(dtype=float)
    real_hit = (df[real_col] == target).to_numpy()
    labels = [f"{int(bins[i]*100)}-{int(bins[i+1]*100)}%" for i in range(len(bins)-1)]
    cat = pd.cut(p, bins=bins, labels=labels, right=False)
    grp = pd.DataFrame({"bucket": cat, "hit": real_hit, "prob": p}).groupby("bucket", observed=True)
    out = grp.agg(n=("hit", "size"), tasso_reale=("hit", "mean"), prob_media=("prob", "mean"))
    out["tasso_reale"] = (out["tasso_reale"] * 100).round(1)
    out["prob_media"] = (out["prob_media"] * 100).round(1)
    return out


def market_calibration(sub, prob_col, real_col, target, label, bins=BINS_OU):
    y = (sub[real_col] == target).astype(int).to_numpy()
    p = sub[prob_col].to_numpy(dtype=float)
    print(f"  {label}: Brier={brier_binary(y, p):.4f}  LogLoss={log_loss_binary(y, p):.4f}")
    print(f"  {label} — media prob. dichiarata {p.mean()*100:.1f}% vs tasso reale {y.mean()*100:.1f}%")
    print(fine_calib_table(sub, prob_col, real_col, target, bins).to_string())


def run_ou_gg(prefix, camp_key):
    df_all = load_league(prefix)
    bt = run_walkforward(df_all, camp_key=camp_key)

    print(f"\n{'='*80}\n{camp_key.upper()}\n{'='*80}")

    for label, season in [("VALIDATION 2024/25", "2024/25"), ("TEST 2025/26", "2025/26")]:
        sub = bt[bt["season"] == season]
        if sub.empty:
            print(f"\n{label}: nessuna partita.")
            continue
        print(f"\n-- {label} --")
        print("\n[Over 2.5]")
        market_calibration(sub, "poisson_o25", "real_uo", "OVER", "Over 2.5 (poisson_o25)")
        print("\n[GG]")
        market_calibration(sub, "poisson_gg", "real_gg", "GG", "GG (poisson_gg)")


def main():
    for prefix, camp_key in LEAGUES:
        run_ou_gg(prefix, camp_key)


if __name__ == "__main__":
    main()
