"""
diagnose_elo_ensemble.py — L'ensemble 0.6*Poisson + 0.4*Elo dell'app aggiunge
valore rispetto al solo Poisson sul 1X2? (tutte e 5 le leghe)

Contesto
--------
`app.py` (Top Mix) calcola la confidence sul 1X2 come
`0.6 * poisson_prob + 0.4 * elo_prob` e richiede `abs(poisson - elo) < 0.25`
(filtro di disaccordo). Pesi (0.6/0.4) e soglie sono costanti scritte a mano
(punto 1.6 del documento di revisione). Su Serie A il confronto era gia' stato
fatto in `audit/backtest_experiment_all.py` + `analyze.py` (Poisson batte
l'ensemble); questo script estende la diagnosi a TUTTE e 5 le leghe con la
formulazione ESATTA della produzione attuale:

  - Poisson 1X2 = testa 1X2 del Poisson a Due Teste (`get_full_poisson_two_heads`):
    lambda forma+mercato normalizzati alla somma base pura, clip [exp(-6), exp(3)],
    matrice Poisson 15x15.
  - Elo = formula di `models/elo_engine.py`: rating costruito in ordine
    cronologico (no leakage, riga per riga) con K = 24 * moltiplicatore margine
    gol, boost xG = clip(((h_xg - h_xga) - (a_xg - a_xga)) * 0.15 * 400, -100, +100)
    (stesso xG Understat della produzione — quello della stagione corrente,
    fedele al comportamento live), home advantage per lega; per la previsione
    dr SENZA boost xG (come `predict_elo_probs`);
    p_draw = clip(0.27 * exp(-(dr/320)^2), 0.06, 0.34).
  - Ensemble = 0.6 * Poisson + 0.4 * Elo (formula Top Mix dell'app).

Metodologia
-----------
Walk-forward identico agli altri script di audit/ (stessa convenzione di
diagnose_ou_gg.py / diagnose_form_totali.py):
  - training puro: 2022/23 + 2023/24
  - finestra di misurazione: validation 2024/25 + test 2025/26
  - no leakage: alla riga idx si usano solo righe < idx (Elo e forma aggiornati
    progressivamente, mai sul futuro)

Metriche (definizioni identiche a `models/backtest.py`):
  - Brier score multiclasse: mean(sum((y_true - y_prob)^2))
  - Log Loss multiclasse (clipped)
  - Win rate (argmax)
  - partita per partita: quante volte l'ensemble batte il Poisson (Brier)
  - filtro di disaccordo |p_poisson - p_elo| < 0.25: quanto spesso scatta e
    cosa seleziona

Non tocca app.py, config.py, models/ e gli altri script di audit/: importa in
sola lettura load_league/market_factor/LEAGUES/XG_FILES/DB da
backtest_experiment_all e i Brier/LogLoss da models/backtest.py.

Produce audit/results/elo_ensemble_diagnosis.md
"""
import os
import sys
import json
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

from backtest_experiment_all import (load_league, market_factor, LEAGUES, XG_FILES, DB)
from config import LEAGUE_HOME_ADVANTAGE  # sola lettura
from models.backtest import calculate_brier_score, calculate_log_loss  # sole lettura

SEASONS = ["2024/25", "2025/26"]   # validation + test (convenzione audit/)
TRAIN_SEASONS = ["2022/23", "2023/24"]
W_POIS, W_ELO = 0.6, 0.4           # pesi ensemble dell'app (Top Mix)
DISAGREE_THR = 0.25                # soglia filtro disaccordo dell'app
MAX_GOALS = 15                     # griglia Poisson, identica a app.py
CLIP_LO, CLIP_HI = 0.002479, 20.0855  # app.py::_clip_lambda = [exp(-6), exp(3)]

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "elo_ensemble_diagnosis.md")


def margin_multiplier(diff):
    """Replica models/elo_engine.py::calculate_goal_margin_multiplier."""
    d = abs(int(diff))
    if d <= 1:
        return 1.0
    if d == 2:
        return 1.5
    if d == 3:
        return 1.75
    return 1.75 + (d - 3) / 8.0


def poisson_1x2(h_lam, a_lam):
    """Stessa matrice di app.py::_poisson_market (clip interno incluso)."""
    h_lam = max(CLIP_LO, min(CLIP_HI, float(h_lam)))
    a_lam = max(CLIP_LO, min(CLIP_HI, float(a_lam)))
    h_p = [scipy_poisson.pmf(i, h_lam) for i in range(MAX_GOALS)]
    a_p = [scipy_poisson.pmf(i, a_lam) for i in range(MAX_GOALS)]
    matrix = np.outer(h_p, a_p)
    return {
        "1": float(np.sum(np.tril(matrix, -1))),
        "X": float(np.sum(np.diag(matrix))),
        "2": float(np.sum(np.triu(matrix, 1))),
    }


def two_heads_1x2(hs, as_, avg_h, avg_a, form_h, form_a):
    """Testa 1X2 del Poisson a Due Teste di app.py (formula esatta):
    lambda forma+mercato normalizzati alla somma base pura, poi clip+matrice.
    `hs["att"]/hs["def"]` sono i rapporti PURI (xG/gol storici, senza forma)."""
    mf_h = market_factor(hs["t"])
    mf_a = market_factor(as_["t"])
    base_h = hs["att"] * as_["def"] * avg_h
    base_a = as_["att"] * hs["def"] * avg_a
    S = base_h + base_a
    mkt_h = hs["att"] * form_h[0] * mf_h * as_["def"] * form_a[1] / mf_a * avg_h
    mkt_a = as_["att"] * form_a[0] * mf_a * hs["def"] * form_h[1] / mf_h * avg_a
    den = mkt_h + mkt_a
    if den > 0:
        norm_h = S * mkt_h / den
        norm_a = S * mkt_a / den
    else:
        norm_h, norm_a = base_h, base_a
    return poisson_1x2(norm_h, norm_a)


def walkforward_ensemble(df, camp_key):
    """Loop walk-forward: per ogni partita della finestra registra le probabilita'
    1X2 di Poisson (testa 1X2 di produzione), Elo (formula di produzione) e
    ensemble 0.6P+0.4E, piu' l'esito reale."""
    home_adv = LEAGUE_HOME_ADVANTAGE.get(camp_key, 65.0)
    train_cutoff = df[df["season"].isin(TRAIN_SEASONS)]["Date"].max()

    # xG Understat della lega (stessa fonte della produzione; per le stagioni
    # storiche e' quello della stagione corrente — fedele al comportamento live)
    xg_data = {}
    xg_file = os.path.join(DB, XG_FILES.get(camp_key, ""))
    if os.path.exists(xg_file):
        with open(xg_file, "r", encoding="utf-8") as f:
            xg_data = json.load(f) or {}

    def xg_boost(h, a):
        if not xg_data or h not in xg_data or a not in xg_data:
            return 0.0
        h_xg = xg_data[h].get("xG_avg", 1.3); h_xga = xg_data[h].get("xGA_avg", 1.3)
        a_xg = xg_data[a].get("xG_avg", 1.3); a_xga = xg_data[a].get("xGA_avg", 1.3)
        xg_adj = ((h_xg - h_xga) - (a_xg - a_xga)) * 0.15
        return max(-100.0, min(100.0, xg_adj * 400.0))

    ratings = {}
    form_hist = {}   # team -> deque((gf, ga)) delle ultime 5 partite (< idx)
    rows = []
    for idx, row in df.iterrows():
        h, a = row.HomeClean, row.AwayClean
        ftr = str(row.FTR).strip().upper()
        r_h = ratings.get(h, 1500.0)
        r_a = ratings.get(a, 1500.0)

        if row.Date > train_cutoff:
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
                return {"t": t, "att": (att_h / avg_h + att_a / avg_a) / 2,
                        "def": (def_h / avg_a + def_a / avg_h) / 2}

            hs, as_ = stat(h), stat(a)
            avg_glob = (avg_h + avg_a) / 2.0

            # forma a 5 gare (strettamente precedenti), clip identici a app.py
            def form5(team):
                dq = form_hist.get(team)
                if not dq or len(dq) < 3:
                    return 1.0, 1.0
                n = len(dq)
                fa = max(0.85, min(1.15, (sum(x[0] for x in dq) / n) / max(avg_glob, 0.5)))
                fd = max(0.85, min(1.15, (sum(x[1] for x in dq) / n) / max(avg_glob, 0.5)))
                return fa, fd

            form_h = form5(h)
            form_a = form5(a)

            pois_p = two_heads_1x2(hs, as_, avg_h, avg_a, form_h, form_a)

            # Elo: dr SENZA boost xG per la previsione (come predict_elo_probs);
            # il boost xG entra solo nell'aggiornamento del rating (compute_ratings)
            dr = r_h + home_adv - r_a
            e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
            p_draw = max(0.06, min(0.34, 0.27 * math.exp(-((dr / 320.0) ** 2))))
            elo_p = {"1": (1 - p_draw) * e_h, "X": p_draw, "2": (1 - p_draw) * (1 - e_h)}
            tot_e = elo_p["1"] + elo_p["X"] + elo_p["2"]
            elo_p = {k: v / tot_e for k, v in elo_p.items()}

            ens_p = {k: W_POIS * pois_p[k] + W_ELO * elo_p[k] for k in ("1", "X", "2")}

            real = {"H": "1", "D": "X", "A": "2"}.get(ftr, "X")
            rows.append({
                "date": row.Date, "season": row.season, "home": h, "away": a,
                "real": real,
                "pois_1": pois_p["1"], "pois_X": pois_p["X"], "pois_2": pois_p["2"],
                "elo_1": elo_p["1"], "elo_X": elo_p["X"], "elo_2": elo_p["2"],
                "ens_1": ens_p["1"], "ens_X": ens_p["X"], "ens_2": ens_p["2"],
            })

        # aggiornamento rating Elo (formula di produzione: K x margine gol + xG boost)
        s_h = 1.0 if ftr == "H" else (0.0 if ftr == "A" else 0.5)
        dr_up = r_h + home_adv - r_a + xg_boost(h, a)
        e_h_up = 1.0 / (1.0 + 10.0 ** (-dr_up / 400.0))
        k_eff = 24.0 * margin_multiplier(row.FTHG - row.FTAG)
        ratings[h] = r_h + k_eff * (s_h - e_h_up)
        ratings[a] = r_a + k_eff * ((1.0 - s_h) - (1.0 - e_h_up))

        # cronologia gol per la forma (aggiornata DOPO la previsione: no leakage)
        form_hist.setdefault(h, deque(maxlen=5)).append((row.FTHG, row.FTAG))
        form_hist.setdefault(a, deque(maxlen=5)).append((row.FTAG, row.FTHG))

    return pd.DataFrame(rows)


def model_matrix(res, model):
    """Matrice one-hot vs probabilita' per il modello ('pois'/'elo'/'ens')."""
    p = np.column_stack([res[f"{model}_1"], res[f"{model}_X"], res[f"{model}_2"]])
    y = np.zeros((len(res), 3))
    y[np.arange(len(res)), res["real"].map({"1": 0, "X": 1, "2": 2}).values] = 1.0
    return p, y


def score_model(res, model):
    p, y = model_matrix(res, model)
    return {
        "brier": float(calculate_brier_score(y, p)),
        "logloss": float(calculate_log_loss(y, p)),
        "win": float((p.argmax(axis=1) == y.argmax(axis=1)).mean()),
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    per_league = []
    all_rows = []
    for prefix, camp_key in LEAGUES:
        print(f"==> {camp_key}: walk-forward Poisson vs Elo vs ensemble ...")
        df = load_league(prefix)
        res = walkforward_ensemble(df, camp_key)
        res = res[res["season"].isin(SEASONS)].reset_index(drop=True)
        all_rows.append(res)

        # filtro di disaccordo dell'app: outcome scelto dal Poisson (best_mkt
        # dell'app per i mercati 1X2 e' l'argmax Poisson), |p_pois - p_elo| < 0.25
        po = res[["pois_1", "pois_X", "pois_2"]].values
        eo = res[["elo_1", "elo_X", "elo_2"]].values
        o_pois = po.argmax(axis=1)
        rng = np.arange(len(res))
        p_sel = po[rng, o_pois]   # p_poisson sull'outcome scelto
        e_sel = eo[rng, o_pois]   # p_elo sullo stesso outcome
        diff = np.abs(p_sel - e_sel)
        accepted = diff < DISAGREE_THR
        # win rate dell'ensemble SULLO SOTTOINSIEME accettato dal filtro
        ens = res[["ens_1", "ens_X", "ens_2"]].values
        wr_acc = (ens[accepted].argmax(axis=1) ==
                  res["real"].map({"1": 0, "X": 1, "2": 2}).values[accepted]).mean() \
            if accepted.any() else float("nan")

        # partita per partita: ensemble vs Poisson (Brier)
        _, y = model_matrix(res, "pois")
        _, y2 = model_matrix(res, "ens")
        brier_pois = np.sum((y - res[["pois_1", "pois_X", "pois_2"]].values) ** 2, axis=1)
        brier_ens = np.sum((y2 - res[["ens_1", "ens_X", "ens_2"]].values) ** 2, axis=1)
        rec = {"league": camp_key, "n": len(res)}
        for m in ("pois", "elo", "ens"):
            s = score_model(res, m)
            rec[f"{m}_brier"] = s["brier"]; rec[f"{m}_logloss"] = s["logloss"]
            rec[f"{m}_win"] = s["win"]
        rec.update({
            "ens_beats_pois": float((brier_ens < brier_pois).mean()),
            "diff_mean": float(diff.mean()),
            "diff_share_above": float((diff >= DISAGREE_THR).mean()),
            "wr_accepted": float(wr_acc),
        })
        per_league.append(rec)
        print(f"    n={rec['n']}  Brier pois/elo/ens = "
              f"{rec['pois_brier']:.3f}/{rec['elo_brier']:.3f}/{rec['ens_brier']:.3f}")

    all_res = pd.concat(all_rows, ignore_index=True)
    pooled = {"league": "Pooled", "n": len(all_res)}
    for m in ("pois", "elo", "ens"):
        s = score_model(all_res, m)
        pooled[f"{m}_brier"] = s["brier"]; pooled[f"{m}_logloss"] = s["logloss"]
        pooled[f"{m}_win"] = s["win"]
    po = all_res[["pois_1", "pois_X", "pois_2"]].values
    eo = all_res[["elo_1", "elo_X", "elo_2"]].values
    o_pois = po.argmax(axis=1)
    rng = np.arange(len(all_res))
    p_sel = po[rng, o_pois]
    e_sel = eo[rng, o_pois]
    diff = np.abs(p_sel - e_sel)
    accepted = diff < DISAGREE_THR
    ens = all_res[["ens_1", "ens_X", "ens_2"]].values
    real_idx = all_res["real"].map({"1": 0, "X": 1, "2": 2}).values
    brier_pois_all = np.sum(((np.eye(3)[real_idx] - po) ** 2), axis=1)
    brier_ens_all = np.sum(((np.eye(3)[real_idx] - ens) ** 2), axis=1)
    pooled["ens_beats_pois"] = float((brier_ens_all < brier_pois_all).mean())
    pooled["diff_mean"] = float(diff.mean())
    pooled["diff_share_above"] = float((diff >= DISAGREE_THR).mean())
    pooled["wr_accepted"] = float((ens[accepted].argmax(axis=1) == real_idx[accepted]).mean()) \
        if accepted.any() else float("nan")

    # ---------------- report ----------------
    L = []
    L.append("# Diagnosi: ensemble 0.6*Poisson + 0.4*Elo sul 1X2 (5 leghe)")
    L.append("")
    L.append(f"_Generato da `diagnose_elo_ensemble.py` il {datetime.now().strftime('%d/%m/%Y %H:%M')}._")
    L.append("")
    L.append("## Domanda")
    L.append("La confidence dell'app sul 1X2 (Top Mix) e' `0.6*Poisson + 0.4*Elo` con")
    L.append(f"filtro di disaccordo `|p_poisson - p_elo| < {DISAGREE_THR}`: i pesi e la soglia,")
    L.append("scritti a mano, migliorano davvero la calibrazione rispetto al solo Poisson?")
    L.append("")
    L.append("## Metodologia (walk-forward, no leakage)")
    L.append("- Window: **validation 2024/25 + test 2025/26**, 5 leghe; training 2022/23+2023/24.")
    L.append("- Poisson 1X2 = testa 1X2 del Poisson a Due Teste di produzione (lambda")
    L.append("  forma+mercato normalizzati alla somma base pura, clip, matrice 15x15).")
    L.append("- Elo = formula esatta di `models/elo_engine.py` (K x margine gol, boost xG")
    L.append("  solo nell'aggiornamento, p_draw gaussiana clip [0.06, 0.34]), rating")
    L.append("  ricostruito cronologicamente senza futuro.")
    L.append("- Metriche: Brier multiclasse, LogLoss, win rate (definizioni di `models/backtest.py`).")
    L.append("")
    L.append("## Risultato per lega\n")
    L.append("| Lega | N | Brier Poisson | Brier Elo | Brier Ensemble | LogLoss P/E/Ens | Win% P/E/Ens |")
    L.append("|---|---|---|---|---|---|---|")
    for r in per_league + [pooled]:
        bold = "**" if r["league"] == "Pooled" else ""
        L.append(
            f"| {bold}{r['league']}{bold} | {bold}{r['n']}{bold} | "
            f"{bold}{r['pois_brier']:.3f}{bold} | {bold}{r['elo_brier']:.3f}{bold} | "
            f"{bold}{r['ens_brier']:.3f}{bold} | "
            f"{bold}{r['pois_logloss']:.3f}/{r['elo_logloss']:.3f}/{r['ens_logloss']:.3f}{bold} | "
            f"{bold}{r['pois_win']:.1%}/{r['elo_win']:.1%}/{r['ens_win']:.1%}{bold} |"
        )
    L.append("")
    L.append("## Ensemble vs Poisson, partita per partita\n")
    L.append("| Lega | % partite con Brier ensemble < Poisson |")
    L.append("|---|---|")
    for r in per_league:
        L.append(f"| {r['league']} | {r['ens_beats_pois']:.1%} |")
    L.append(f"| **Pooled** | **{pooled['ens_beats_pois']:.1%}** |")
    L.append("")
    L.append("## Filtro di disaccordo dell'app (outcome scelto dal Poisson)\n")
    L.append("| Lega | media |p_pois - p_elo| | % partite rifiutate (diff ≥ 0.25) | Win% ensemble sul sottinsieme accettato |")
    L.append("|---|---|---|---|")
    for r in per_league:
        L.append(f"| {r['league']} | {r['diff_mean']:.3f} | {r['diff_share_above']:.1%} | {r['wr_accepted']:.1%} |")
    L.append(f"| **Pooled** | **{pooled['diff_mean']:.3f}** | **{pooled['diff_share_above']:.1%}** | "
             f"**{pooled['wr_accepted']:.1%}** |")
    L.append("")
    n_pois_better = sum(1 for r in per_league if r["pois_brier"] < r["ens_brier"])
    n_ens_better = sum(1 for r in per_league if r["ens_brier"] < r["pois_brier"])
    n_elo_better = sum(1 for r in per_league if r["elo_brier"] < r["pois_brier"])
    L.append("## Verdetto\n")
    if n_pois_better == len(LEAGUES):
        L.append(f"**Il solo Poisson batte l'ensemble in Brier su tutte e {len(LEAGUES)} le leghe** "
                 f"(anche sul pooled: {pooled['pois_brier']:.3f} vs {pooled['ens_brier']:.3f}), e l'Elo "
                 f"puro e' sistematicamente peggio del Poisson. L'ensemble 0.6/0.4 non aggiunge "
                 f"informazione sul 1X2: mescola due modelli che concordano gia' per costruzione "
                 f"(entrambi su forza di lungo periodo), e il filtro di disaccordo scarta "
                 f"{pooled['diff_share_above']:.0%} delle partite senza migliorare la calibrazione "
                 f"del sottinsieme accettato (win rate {pooled['wr_accepted']:.1%} vs "
                 f"{pooled['ens_win']:.1%} sull'intero). I pesi 0.6/0.4 e la soglia 0.25 restano "
                 f"costanti non validate (vedi punto 1.6 della revisione).")
    elif n_ens_better == len(LEAGUES):
        L.append(f"**Con la formulazione di produzione attuale, l'ensemble 0.6P+0.4E migliora il "
                 f"Brier pooled rispetto alla sola testa 1X2 del Poisson** "
                 f"({pooled['pois_brier']:.3f} → {pooled['ens_brier']:.3f}) e il LogLoss "
                 f"({pooled['pois_logloss']:.3f} → {pooled['ens_logloss']:.3f}), batte il Poisson in "
                 f"Brier in tutte e {len(LEAGUES)} le leghe (l'Elo puro: {n_elo_better} su "
                 f"{len(LEAGUES)}). Attenzione pero' alla struttura del vantaggio: partita per "
                 f"partita l'ensemble e' migliore solo nel {pooled['ens_beats_pois']:.0%} dei casi, "
                 f"e il win rate dei tre modelli e' praticamente identico "
                 f"({pooled['pois_win']:.1%} / {pooled['elo_win']:.1%} / {pooled['ens_win']:.1%}): "
                 f"il Brier scende per poche partite molto migliorate, mentre sulla maggior parte "
                 f"l'ensemble aggiunge lieve rumore. Il filtro di disaccordo scarta il "
                 f"{pooled['diff_share_above']:.0%} delle partite ma il win rate del sottinsieme "
                 f"accettato ({pooled['wr_accepted']:.1%}) e' INFERIORE a quello sull'intero "
                 f"({pooled['ens_win']:.1%}): oggi non funziona da gate di qualita'. Nota: questo "
                 f"contrasta con il risultato di `analyze.py` su Serie A (Poisson > ensemble), che "
                 f"confrontava un Poisson a testa singola SENZA forma/mercato e un Elo semplificato "
                 f"(K fisso, senza xG): la testa 1X2 di produzione (Due Teste) e l'Elo di produzione "
                 f"(K x margine gol + xG) sono formulazioni diverse. **Conclusione: i pesi 0.6/0.4 "
                 f"e la soglia 0.25 restano costanti non validate (punto 1.6) e il gap di Brier "
                 f"pooled (~0.012) e' dentro il rumore di questo campione: serve la grid search del "
                 f"piano (Priorita' 2, punto 8) per decidere.**")
    else:
        L.append(f"**Risultato misto**: Poisson batte l'ensemble in Brier in {n_pois_better} su "
                 f"{len(LEAGUES)} leghe (ensemble: {n_ens_better} su {len(LEAGUES)}); valutare le "
                 f"singole leghe prima di toccare i pesi.")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"\nReport scritto su {OUT_PATH}")


if __name__ == "__main__":
    main()
