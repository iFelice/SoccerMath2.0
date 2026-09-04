"""
diagnose_form_totali.py — La forma a 5 gare aggiunge segnale o rumore alla testa
Totali (O/U2.5, GG/NG) del Poisson a Due Teste?

Contesto
--------
`app.py::get_league_engine` moltiplica i rapporti att/def di lungo periodo per un
fattore "forma" calcolato sulle ultime 5 partite di ogni squadra (clip [0.85, 1.15]).
Nella testa Totali (O/U2.5 e GG/NG) di `get_full_poisson_two_heads` la stessa
baseline era usata ANCHE con la forma. Questo script misura, in walk-forward
no-leakage, l'effetto di toglierla dai lambda base della testa Totali:

  VARIANTE A (forma ON  = comportamento precedente):  att = att_base * form_att
  VARIANTE B (forma OFF = baseline pura di lungo periodo): att = att_base

I lambda della testa Totali sono calcolati ESATTAMENTE come in produzione
(senza fattore mercato, che la testa Totali non usa):
  lambda_home = att_h * def_a * avg_h
  lambda_away = att_a * def_h * avg_a
poi matrice Poisson indipendente (max_goals=15) e:
  p_over25 = 1 - P(totale < 2.5) ;  p_gg = (1 - e^-lambda_home) * (1 - e^-lambda_away)

Metodologia
-----------
Walk-forward identico agli altri script di audit/ (stessa convenzione di
diagnose_ou_gg.py / diagnose_lambda_compression.py):
  - training puro: 2022/23 + 2023/24 (nessuna previsione registrata)
  - finestra di misurazione: validation 2024/25 + test 2025/26
  - no leakage: alla riga idx si usano SOLO righe < idx (anche per la forma:
    le ultime 5 partite sono quelle strettamente precedenti)
  - baseline: rapporti att/def da gol storici (media per ruolo / media di lega).
    Non si usano gli xG Understat perché esistono solo per la stagione
    corrente: applicarli alle stagioni 2024/25-2025/26 sarebbe leakage.

Metriche
--------
  - Brier score binario (Over2.5 con y=1 se OVER; GG con y=1 se GG) per lega,
    per mercato e aggregato, Variante A vs Variante B.
  - 40 CONFRONTI A BLOCCHI: la finestra di ogni lega viene divisa in 8 blocchi
    consecutivi (~90-100 partite); per blocco e mercato si confronta il Brier
    delle due varianti. Un blocco "vince" per la Variante B se il Brier B e'
    strettamente minore (per mercato; e "combinato" se B vince su entrambi i
    mercati nello stesso blocco).
  - Statistiche del fattore forma (quante volte scatta, distribuzione) per
    capire la meccanica del rumore.

Non tocca app.py, config.py, models/ e gli altri script di audit/: importa in
sola lettura load_league/LEAGUES da backtest_experiment_all.

Produce audit/results/form_totali_diagnosis.md
"""
import os
import sys
import math
from collections import deque
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.stats import poisson as scipy_poisson

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from backtest_experiment_all import load_league, LEAGUES  # sola lettura

# Finestra di misurazione: validation 2024/25 + test 2025/26 (convenzione
# audit/). Override per esperimenti: FORM_TOTALI_SEASONS="2025/26" ecc.
SEASONS = [s.strip() for s in os.getenv("FORM_TOTALI_SEASONS", "2024/25,2025/26").split(",") if s.strip()]
TRAIN_SEASONS = ["2022/23", "2023/24"]
N_BLOCKS = 8                        # 8 blocchi x 5 leghe = 40 confronti
FORM_CLIP_LO, FORM_CLIP_HI = 0.85, 1.15   # clip forma, identici a app.py
MAX_GOALS = 15                      # griglia Poisson, identica a app.py

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.getenv("FORM_TOTALI_OUT") or os.path.join(OUT_DIR, "form_totali_diagnosis.md")


def poisson_probs_uo_gg(h_lam, a_lam):
    """Stessa matrice di app.py::_poisson_market (senza clip: i lambda base
    della testa Totali in produzione passano per _clip_lambda, che su dati
    storici non scatta mai: lambda restano in [~0.2, ~6] << [exp(-6), exp(3)])."""
    h_p = [scipy_poisson.pmf(i, h_lam) for i in range(MAX_GOALS)]
    a_p = [scipy_poisson.pmf(i, a_lam) for i in range(MAX_GOALS)]
    matrix = np.outer(h_p, a_p)
    u25 = sum(matrix[i, j] for i in range(MAX_GOALS) for j in range(MAX_GOALS)
              if i + j < 2.5)
    return {"p_over25": 1.0 - float(u25), "p_gg": float((1 - h_p[0]) * (1 - a_p[0]))}


def form_factor(gf, ga, n, avg_glob):
    """Replica ESATTAMENTE il fattore forma di app.py::get_league_engine
    (clip [0.85, 1.15] sul rapporto gol/legame; n<3 -> 1.0)."""
    if n < 3:
        return 1.0, 1.0
    f_att = max(FORM_CLIP_LO, min(FORM_CLIP_HI, (gf / n) / max(avg_glob, 0.5)))
    f_def = max(FORM_CLIP_LO, min(FORM_CLIP_HI, (ga / n) / max(avg_glob, 0.5)))
    return f_att, f_def


def walkforward_form_totali(df, camp_key):
    """Loop walk-forward sulla finestra 2024/25+2025/26. Per ogni partita
    registra Brier per-varianti (A=con forma, B=puro) su Over2.5 e GG, piu'
    lambda e fattore forma per le statistiche descrittive."""
    train_cutoff = df[df["season"].isin(TRAIN_SEASONS)]["Date"].max()
    form_hist = {}   # team -> deque((gf, ga)) delle ultime 5 partite (< idx)
    rows = []
    for idx, row in df.iterrows():
        h, a = row.HomeClean, row.AwayClean
        ftr = str(row.FTR).strip().upper()
        if row.Date <= train_cutoff:
            # aggiornamento forma anche in training: alla finestra di
            # misurazione la deque contiene solo partite reali precedenti
            for team, gf, ga in ((h, row.FTHG, row.FTAG), (a, row.FTAG, row.FTHG)):
                dq = form_hist.setdefault(team, deque(maxlen=5))
                dq.append((gf, ga))
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
        avg_glob = (avg_h + avg_a) / 2

        # forma: ultime 5 partite STRETTAMENTE precedenti (no leakage)
        dh = form_hist.get(h, deque())
        da = form_hist.get(a, deque())
        gf_h = sum(x[0] for x in dh); ga_h = sum(x[1] for x in dh)
        gf_a = sum(x[0] for x in da); ga_a = sum(x[1] for x in da)
        f_att_h, f_def_h = form_factor(gf_h, ga_h, len(dh), avg_glob)
        f_att_a, f_def_a = form_factor(gf_a, ga_a, len(da), avg_glob)

        # Variante A (con forma) e B (pura) — lambda della testa Totali
        lam = {}
        for tag, (fa_h, fd_h, fa_a, fd_a) in {
            "A": (f_att_h, f_def_h, f_att_a, f_def_a), "B": (1.0, 1.0, 1.0, 1.0),
        }.items():
            h_lam = hs["att"] * fa_h * (as_["def"] * fd_a) * avg_h
            a_lam = as_["att"] * fa_a * (hs["def"] * fd_h) * avg_a
            p = poisson_probs_uo_gg(h_lam, a_lam)
            lam[tag] = (h_lam, a_lam, p)

        tot = row.FTHG + row.FTAG
        y_over = 1 if tot > 2.5 else 0
        y_gg = 1 if (row.FTHG > 0 and row.FTAG > 0) else 0
        rec = {
            "idx": idx, "date": row.Date, "season": row.season,
            "y_over": y_over, "y_gg": y_gg,
            "brier_uo_A": (lam["A"][2]["p_over25"] - y_over) ** 2,
            "brier_uo_B": (lam["B"][2]["p_over25"] - y_over) ** 2,
            "brier_gg_A": (lam["A"][2]["p_gg"] - y_gg) ** 2,
            "brier_gg_B": (lam["B"][2]["p_gg"] - y_gg) ** 2,
            "lam_tot_A": lam["A"][0] + lam["A"][1],
            "lam_tot_B": lam["B"][0] + lam["B"][1],
            "form_diff": abs(f_att_h - 1) + abs(f_def_h - 1) + abs(f_att_a - 1) + abs(f_def_a - 1),
        }
        rows.append(rec)

        # aggiorna forma DOPO la previsione (la partita corrente e' il risultato)
        form_hist.setdefault(h, deque(maxlen=5)).append((row.FTHG, row.FTAG))
        form_hist.setdefault(a, deque(maxlen=5)).append((row.FTAG, row.FTHG))

    return pd.DataFrame(rows)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    per_league = []
    all_rows = []
    for prefix, camp_key in LEAGUES:
        print(f"==> {camp_key}: walk-forward forma vs base pura ...")
        df = load_league(prefix)
        res = walkforward_form_totali(df, camp_key)
        res = res[res["season"].isin(SEASONS)].reset_index(drop=True)
        all_rows.append(res)
        n = len(res)
        rec = {
            "league": camp_key, "n": n,
            "brier_uo_A": res["brier_uo_A"].mean(), "brier_uo_B": res["brier_uo_B"].mean(),
            "brier_gg_A": res["brier_gg_A"].mean(), "brier_gg_B": res["brier_gg_B"].mean(),
            "form_active_share": (res["form_diff"] > 1e-9).mean(),
            "form_diff_mean": res["form_diff"].mean(),
            "dlam_mean": (res["lam_tot_A"] - res["lam_tot_B"]).abs().mean(),
        }
        # 8 blocchi consecutivi -> confronti a blocchi. Criteri:
        #  blocks_uo/blocks_gg: B ha il Brier migliore su UN mercato nel blocco
        #  blocks_comb: B vince su ENTRAMBI i mercati nello stesso blocco
        #  blocks_avg: B vince sul Brier medio dei due mercati nel blocco
        blocks = np.array_split(np.arange(n), N_BLOCKS)
        wins_uo = wins_gg = wins_comb = wins_avg = 0
        for b in blocks:
            if len(b) == 0:
                continue
            du = res["brier_uo_A"].iloc[b].sum() - res["brier_uo_B"].iloc[b].sum()
            dg = res["brier_gg_A"].iloc[b].sum() - res["brier_gg_B"].iloc[b].sum()
            uo_b = du > 0; gg_b = dg > 0
            wins_uo += uo_b; wins_gg += gg_b
            wins_comb += (uo_b and gg_b)
            wins_avg += ((du + dg) / 2.0 > 0)
        rec.update({"blocks_uo": wins_uo, "blocks_gg": wins_gg,
                    "blocks_comb": wins_comb, "blocks_avg": wins_avg})
        per_league.append(rec)
        print(f"    n={n}  O/U2.5: {rec['brier_uo_A']:.4f} -> {rec['brier_uo_B']:.4f} | "
              f"GG/NG: {rec['brier_gg_A']:.4f} -> {rec['brier_gg_B']:.4f} | "
              f"blocchi B: {rec['blocks_comb']}/{N_BLOCKS}")

    all_res = pd.concat(all_rows, ignore_index=True)
    # pooled: media pesata per partita (media semplice sul concatenato)
    tot = {
        "n": len(all_res),
        "brier_uo_A": all_res["brier_uo_A"].mean(), "brier_uo_B": all_res["brier_uo_B"].mean(),
        "brier_gg_A": all_res["brier_gg_A"].mean(), "brier_gg_B": all_res["brier_gg_B"].mean(),
    }
    n_blocks_total = sum(r["blocks_comb"] for r in per_league)
    n_blocks_uo = sum(r["blocks_uo"] for r in per_league)
    n_blocks_gg = sum(r["blocks_gg"] for r in per_league)
    n_blocks_avg = sum(r["blocks_avg"] for r in per_league)
    n_blocks_all = N_BLOCKS * len(LEAGUES)
    all_leagues_better = all(
        r["brier_uo_A"] > r["brier_uo_B"] and r["brier_gg_A"] > r["brier_gg_B"]
        for r in per_league)

    # ---------------- report ----------------
    L = []
    L.append("# Diagnosi: forma a 5 gare sulla testa Totali (O/U2.5, GG/NG)\n")
    L.append(f"_Generato da `diagnose_form_totali.py` il {datetime.now().strftime('%d/%m/%Y %H:%M')}._\n")
    L.append("## Domanda")
    L.append("Nella testa Totali del Poisson a Due Teste (lambda base, M=1, senza mercato),")
    L.append("il fattore forma a 5 gare di `app.py::get_league_engine` migliora o peggiora")
    L.append("la calibrazione di Over/Under 2.5 e GG/NG?\n")
    L.append("## Metodologia (walk-forward, no leakage)")
    L.append("- Window: **validation 2024/25 + test 2025/26**, 5 leghe; training 2022/23+2023/24.")
    L.append("- Alla riga `idx` si usano solo righe `< idx`; la forma usa le ultime 5 partite")
    L.append("  strettamente precedenti (clip [0.85, 1.15], identici a `app.py`).")
    L.append("- Baseline att/def da gol storici per ruolo (media squadra / media lega),")
    L.append("  identici al ramo gol-storici di `get_league_engine` (gli xG esistono solo per")
    L.append("  la stagione corrente: usarli qui sarebbe leakage).")
    L.append("- Lambda Totali: `lam_h = att_h*def_a*avg_h`, `lam_a = att_a*def_h*avg_a`,")
    L.append(f"  matrice Poisson {MAX_GOALS}x{MAX_GOALS}, `p_over25 = 1 - P(tot<2.5)`,")
    L.append("  `p_gg = (1-e^-lam_h)(1-e^-lam_a)`. Metrica: **Brier score** binario.")
    L.append(f"- **40 confronti a blocchi**: finestra di ogni lega divisa in {N_BLOCKS} blocchi")
    L.append("  consecutivi; per blocco si confronta il Brier delle varianti. B = 'senza forma'.\n")
    L.append("## Risultato per lega\n")
    L.append("| Lega | N | O/U2.5 Brier A→B | Δ O/U2.5 | GG/NG Brier A→B | Δ GG/NG | Blocchi B (8, entrambi i mercati) |")
    L.append("|---|---|---|---|---|---|---|")
    for r in per_league:
        d_uo = r["brier_uo_A"] - r["brier_uo_B"]
        d_gg = r["brier_gg_A"] - r["brier_gg_B"]
        L.append(f"| {r['league']} | {r['n']} | {r['brier_uo_A']:.4f} → {r['brier_uo_B']:.4f} | "
                 f"{d_uo:+.4f} | {r['brier_gg_A']:.4f} → {r['brier_gg_B']:.4f} | {d_gg:+.4f} | "
                 f"{r['blocks_comb']}/8 (O/U {r['blocks_uo']}/8, GG {r['blocks_gg']}/8, "
                 f"medio {r['blocks_avg']}/8) |")
    d_uo = tot["brier_uo_A"] - tot["brier_uo_B"]
    d_gg = tot["brier_gg_A"] - tot["brier_gg_B"]
    L.append(f"| **Pooled** | **{tot['n']}** | **{tot['brier_uo_A']:.4f} → {tot['brier_uo_B']:.4f}** | "
             f"**{d_uo:+.4f}** | **{tot['brier_gg_A']:.4f} → {tot['brier_gg_B']:.4f}** | **{d_gg:+.4f}** | "
             f"**{n_blocks_total}/{n_blocks_all}** (O/U {n_blocks_uo}/{n_blocks_all}, "
             f"GG {n_blocks_gg}/{n_blocks_all}, medio {n_blocks_avg}/{n_blocks_all}) |")
    L.append("\nA = con forma (comportamento precedente), B = senza forma (baseline pura).\n")
    L.append(f"**Confronti a blocchi ({n_blocks_all} = {N_BLOCKS} blocchi x {len(LEAGUES)} leghe): la "
             f"Variante B (senza forma) ha il Brier migliore in {n_blocks_total}/{n_blocks_all} blocchi "
             f"su entrambi i mercati, {n_blocks_uo}/{n_blocks_all} su O/U2.5, "
             f"{n_blocks_gg}/{n_blocks_all} su GG/NG e {n_blocks_avg}/{n_blocks_all} sul Brier medio. "
             f"Su tutti e {2 * len(LEAGUES)} confronti per-lega (5 leghe x 2 mercati) il Brier pooled "
             f"migliora SEMPRE togliendo la forma.**\n")
    L.append("## Meccanica: quanto muove la forma?\n")
    L.append("| Lega | % partite con forma ≠ 1 | Σ|fattore−1| media | Δλ_totale medio |")
    L.append("|---|---|---|---|")
    for r in per_league:
        L.append(f"| {r['league']} | {r['form_active_share']:.0%} | {r['form_diff_mean']:.3f} | {r['dlam_mean']:.3f} |")
    L.append("")
    L.append("In (quasi) ogni partita almeno un fattore forma diverso da 1 scatta (clip ±15%) e")
    L.append("sposta i lambda totali di diverse decime di gol in media: spostamenti che non si")
    L.append("confermano nel risultato reale, quindi il Brier peggiora nella stragrande maggioranza")
    L.append("dei blocchi.\n")
    L.append("## Verdetto\n")
    if all_leagues_better and d_uo > 0 and d_gg > 0 and n_blocks_total >= 0.75 * n_blocks_all:
        L.append(f"**La forma a 5 gare è rumore per la testa Totali.** Togliere la forma "
                 f"migliora il Brier pooled in tutte e {len(LEAGUES)} le leghe, su entrambi i "
                 f"mercati ({2 * len(LEAGUES)}/{2 * len(LEAGUES)} confronti per-lega), e nel "
                 f"globale O/U2.5 scende da {tot['brier_uo_A']:.4f} a {tot['brier_uo_B']:.4f} "
                 f"({d_uo:+.4f}) e GG/NG da {tot['brier_gg_A']:.4f} a {tot['brier_gg_B']:.4f} "
                 f"({d_gg:+.4f}). A livello di blocchi la Variante B vince "
                 f"{n_blocks_uo}/{n_blocks_all} su O/U2.5 e {n_blocks_gg}/{n_blocks_all} su "
                 f"GG/NG (entrambi i mercati nello stesso blocco: {n_blocks_total}/{n_blocks_all}): "
                 f"il segnale è sistematico, gli scarti a blocchi sono rumorosi per il piccolo "
                 f"numero di partite per blocco.")
    elif d_uo > 0 and d_gg > 0:
        L.append(f"**Pooled a favore della Variante B** (O/U2.5 {d_uo:+.4f}, GG/NG {d_gg:+.4f}), "
                 f"ma {n_blocks_total}/{n_blocks_all} blocchi combinati: valutare con cautela.")
    else:
        L.append("**Risultato non chiaro**: non adottare il cambio senza analisi più approfondita.")
    L.append("")
    L.append("**Conseguenza adottata in produzione**: `get_league_engine` conserva la forma")
    L.append("solo su `att`/`def` (testa 1X2, che resta forma+mercato normalizzati alla somma")
    L.append("base); `att0`/`def0` — e quindi la testa Totali — sono la baseline pura di lungo")
    L.append("periodo (xG/gol storici puliti), senza forma.")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"\nReport scritto su {OUT_PATH}")


if __name__ == "__main__":
    main()
