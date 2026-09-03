"""
diagnose_ou_gg.py — Diagnosi della sotto-discriminazione su Over 2.5 e GG/NG.

Usa le predizioni walk-forward (stessa logica no-leakage di
backtest_experiment_all.run_walkforward) su VALIDATION 2024/25 + TEST 2025/26,
tutte e 5 le leghe. Non tocca backtest_experiment_all.py, analyze_all.py,
app.py, config.py, models/: importa in sola lettura load_league/get_full_poisson/
devig_2way/LEAGUES e replica SOLO il loop Poisson (che non scrive le lambda nel
dataframe esistente) per estrarre lambda_home + lambda_away per ogni partita.

Produce audit/results/ou_gg_diagnosis.md con:
  1. Istogramma (bin 0.05) della distribuzione delle probabilita' previste
     per O/U2.5 e GG/NG, per lega e aggregato (quanto si concentrano in 0.45-0.55).
  2. Deviazione standard delle probabilita' previste vs deviazione standard
     delle probabilita' implicite di mercato de-vig (O/U2.5; per GG non esistono
     quote BTTS nel dataset, vedi nota).
  3. O/U2.5: std dev di lambda_totale = lambda_home + lambda_away tra partite,
     per lega, confrontata con std dev del totale gol reali (proxy variabilita'
     "vera").
  4. Reliability diagram a 10 decili (bin quantili) per O/U2.5 e GG/NG.
"""
import os
import sys
import json
import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from backtest_experiment_all import (load_league, get_full_poisson, devig_2way,
                                     LEAGUES)

SEASONS = ["2024/25", "2025/26"]  # validation + test
HIST_BINS = [round(i * 0.05, 2) for i in range(21)]  # 0.00 .. 1.00

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "ou_gg_diagnosis.md")


def run_poisson_lambda(df, camp_key):
    """Replica il loop Poisson di run_walkforward (no-leakage) e per ogni partita
    di validation+test registra: poisson_o25, poisson_gg, real_uo, real_gg,
    lambda_home, lambda_away, fair_b365_o25, B365>2.5, real totale gol."""
    train_cutoff = df[df["season"].isin(("2022/23", "2023/24"))]["Date"].max()
    rows = []
    for idx, row in df.iterrows():
        h, a = row.HomeClean, row.AwayClean
        ftr = str(row.FTR).strip().upper()
        if row.Date <= train_cutoff:
            continue
        train = df.iloc[:idx]
        avg_h = max(float(train["FTHG"].mean()), 0.1)
        avg_a = max(float(train["FTAG"].mean()), 0.1)
        home_gf = train.groupby("HomeClean")["FTHG"].mean()
        home_ga = train.groupby("HomeClean")["FTAG"].mean()
        away_gf = train.groupby("AwayClean")["FTAG"].mean()
        away_ga = train.groupby("AwayClean")["FTHG"].mean()

        def stat(t):
            att_h = home_gf[t] if t in home_gf.index else avg_h
            def_h = home_ga[t] if t in home_ga.index else avg_a
            att_a = away_gf[t] if t in away_gf.index else avg_a
            def_a = away_ga[t] if t in away_ga.index else avg_h
            return {"att": (att_h / avg_h + att_a / avg_a) / 2,
                    "def": (def_h / avg_a + def_a / avg_h) / 2}

        hs, as_ = stat(h), stat(a)
        lam_h = hs["att"] * as_["def"] * avg_h
        lam_a = as_["att"] * hs["def"] * avg_a
        m_p = get_full_poisson(lam_h, lam_a)

        fair_uo = devig_2way(row["B365>2.5"], row["B365<2.5"])
        real_uo = "OVER" if (row.FTHG + row.FTAG) > 2.5 else "UNDER"
        real_gg = "GG" if row.FTHG > 0 and row.FTAG > 0 else "NG"

        rows.append({
            "season": row.season, "real_uo": real_uo, "real_gg": real_gg,
            "poisson_o25": 1 - m_p["u25"], "poisson_gg": m_p["gg"],
            "lambda_home": lam_h, "lambda_away": lam_a, "lambda_total": lam_h + lam_a,
            "real_total_goals": row.FTHG + row.FTAG,
            "fair_b365_o25": fair_uo[0] if fair_uo else np.nan,
            "B365_o25": row["B365>2.5"],
        })
    return pd.DataFrame(rows)


def hist_table(series, label):
    """Istogramma a bin 0.05. Ritorna stringa markdown."""
    counts, _ = np.histogram(series, bins=HIST_BINS)
    total = counts.sum()
    lines = [f"**Istogramma {label}** (bin 0.05):", "", "| bin | n | % |", "|---|---|---|"]
    for i in range(len(counts)):
        lo = HIST_BINS[i]
        hi = HIST_BINS[i + 1]
        pct = counts[i] / total * 100 if total else 0.0
        lines.append(f"| {lo:.2f}-{hi:.2f} | {counts[i]} | {pct:.1f} |")
    # concentrazione 0.45-0.55
    mask = (series >= 0.45) & (series < 0.55)
    frac = mask.mean() * 100 if len(series) else 0.0
    lines.append("")
    lines.append(f"Concentrazione in [0.45, 0.55): **{frac:.1f}%** (n={mask.sum()}/{len(series)})")
    return "\n".join(lines)


def std_row(sub, pcol, faircol=None):
    pred_std = sub[pcol].std()
    pred_mean = sub[pcol].mean()
    if faircol is not None:
        fair_std = sub[faircol].std()
        return pred_mean, pred_std, fair_std
    return pred_mean, pred_std, None


def reliability_table(sub, pcol, real_col, target, label):
    """Reliability diagram a 10 decili (bin quantili)."""
    d = sub.dropna(subset=[pcol, real_col]).copy()
    y = (d[real_col] == target).astype(int).to_numpy()
    p = d[pcol].to_numpy(dtype=float)
    # decili quantili (10 bin)
    try:
        q, bins = pd.qcut(p, 10, retbins=True, duplicates="drop")
    except Exception:
        q, bins = pd.qcut(p, 10, retbins=True)
    dfq = pd.DataFrame({"q": q, "y": y, "p": p})
    lines = [f"**Reliability diagram {label}** (decili):", "",
             "| bin | n | prob media | freq empirica |", "|---|---|---|---|"]
    for i, interval in enumerate(dfq["q"].cat.categories):
        g = dfq[dfq["q"] == interval]
        lines.append(f"| {interval} | {len(g)} | {g['p'].mean()*100:.1f} | {g['y'].mean()*100:.1f} |")
    return "\n".join(lines)


def analyze_league(prefix, camp_key, agg_rows):
    df_all = load_league(prefix)
    rl = run_poisson_lambda(df_all, camp_key)
    rl = rl[rl["season"].isin(SEASONS)].copy()

    md = [f"\n## {camp_key.upper()}\n"]

    # --- 1. Istogrammi ---
    md.append(hist_table(rl["poisson_o25"], "Over 2.5 (poisson_o25)"))
    md.append("")
    md.append(hist_table(rl["poisson_gg"], "GG (poisson_gg)"))
    md.append("")

    # --- 2. Std dev predette vs mercato de-vig (O/U2.5) ---
    sub = rl.dropna(subset=["poisson_o25", "fair_b365_o25"])
    pred_mean, pred_std, fair_std = std_row(sub, "poisson_o25", "fair_b365_o25")
    md.append(f"**Std dev O/U2.5 — {camp_key}** (N={len(sub)}):")
    md.append("")
    md.append(f"- Prob. previste (poisson_o25): media={pred_mean*100:.2f}%  std={pred_std:.4f}")
    md.append(f"- Prob. implicite mercato de-vig (fair_b365_o25): std={fair_std:.4f}")
    md.append(f"- Rapporto mercato/modello: **{fair_std/pred_std:.2f}**" if pred_std > 0 else "-")
    md.append("")

    # GG: nessuna quota BTTS -> solo std previste, con nota
    gg_std = rl["poisson_gg"].std()
    md.append(f"- GG (poisson_gg): std previste={gg_std:.4f}  (nessuna quota BTTS nel dataset, "
              f"confronto con mercato non disponibile)")
    md.append("")

    # --- 3. lambda totale vs gol reali (O/U2.5) ---
    lam_std = rl["lambda_total"].std()
    goals_std = rl["real_total_goals"].std()
    md.append(f"**Variabilita' lambda totale vs gol reali — {camp_key}** (N={len(rl)}):")
    md.append("")
    md.append(f"- lambda_totale (lambda_home+lambda_away): media={rl['lambda_total'].mean():.3f}  "
              f"std={lam_std:.4f}")
    md.append(f"- Totale gol reali: media={rl['real_total_goals'].mean():.3f}  std={goals_std:.4f}")
    md.append(f"- Rapporto std_gol/std_lambda: **{goals_std/lam_std:.2f}**" if lam_std > 0 else "-")
    md.append("")

    # --- 4. Reliability diagram (10 decili) ---
    md.append(reliability_table(rl, "poisson_o25", "real_uo", "OVER", "Over 2.5"))
    md.append("")
    md.append(reliability_table(rl, "poisson_gg", "real_gg", "GG", "GG"))
    md.append("")

    agg_rows["rl"].append(rl)
    return "\n".join(md)


def aggregate_section(agg_rows):
    rl_all = pd.concat(agg_rows["rl"], ignore_index=True)
    md = [f"\n## AGGREGATO — 5 LEGHE\n"]

    # 1. istogrammi aggregati
    md.append(hist_table(rl_all["poisson_o25"], "Over 2.5 (poisson_o25)"))
    md.append("")
    md.append(hist_table(rl_all["poisson_gg"], "GG (poisson_gg)"))
    md.append("")

    # 2. std aggregati
    sub = rl_all.dropna(subset=["poisson_o25", "fair_b365_o25"])
    pred_std = sub["poisson_o25"].std()
    fair_std = sub["fair_b365_o25"].std()
    md.append(f"**Std dev O/U2.5 aggregato** (N={len(sub)}):")
    md.append(f"- Previste std={pred_std:.4f} | Mercato de-vig std={fair_std:.4f} | "
              f"rapporto={fair_std/pred_std:.2f}")
    md.append(f"- GG previste std={rl_all['poisson_gg'].std():.4f} (nessun mercato BTTS)")
    md.append("")

    # 3. lambda aggregato
    md.append(f"**Variabilita' lambda totale aggregato** (N={len(rl_all)}):")
    md.append(f"- lambda_totale std={rl_all['lambda_total'].std():.4f}")
    md.append(f"- gol reali std={rl_all['real_total_goals'].std():.4f}")
    md.append(f"- rapporto std_gol/std_lambda={rl_all['real_total_goals'].std()/rl_all['lambda_total'].std():.2f}")
    md.append("")

    return "\n".join(md)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    agg_rows = {"rl": []}

    parts = []
    header = [
        "# Diagnosi O/U2.5 e GG/NG — sotto-discriminazione",
        "",
        "Campione: walk-forward no-leakage, VALIDATION 2024/25 + TEST 2025/26, 5 leghe.",
        "Modello Poisson (stesso calcolo di backtest_experiment_all.run_walkforward).",
        "",
    ]
    parts.append("\n".join(header))

    for prefix, camp_key in LEAGUES:
        parts.append(analyze_league(prefix, camp_key, agg_rows))

    parts.append(aggregate_section(agg_rows))

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    print(f"Scritto: {OUT_PATH}")


if __name__ == "__main__":
    main()
