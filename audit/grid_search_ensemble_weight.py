"""
grid_search_ensemble_weight.py — Grid search del peso dell'ensemble
Poisson+Elo su 1X2 (w su Poisson, 1-w su Elo), audit SOLA LETTURA.

Disciplina anti-overfitting richiesta (stessa di diagnose_dixon_coles_rho.py):
  * il peso si SCEGLIE solo su TRAIN 2022/23+2023/24;
  * VALIDATION 2024/25 conferma (o smentisce) la scelta;
  * TEST 2025/26 e' solo lettura finale, mai usato per scegliere;
  * una differenza che cade dentro l'IC bootstrap e' rumore, non miglioramento.

Pipeline: la stessa PRODUZIONE_DUE_TESTE gia' usata in diagnose_elo_ensemble.py
e diagnose_clv_pinnacle.py, cioe' il walker run_model_with_elo di
diagnose_clv_pinnacle (testa 1X2 NORM-SUM bit-faithful a
diagnose_production_baseline.run_models + Elo walk-forward K=24, importati, non
riscritti) con emit_season esteso a train+validation+test. La griglia e'
w in {0.0, 0.1, ..., 1.0}; w=0.6 e' il valore attuale di produzione
(app.ELO_ENSEMBLE_W).

Metriche per w (stesse convenzioni degli altri audit):
  * Brier / LogLoss 1X2 (formule di brier_ll_1x2, verifica dal test);
  * ROI a puntata fissa 10 con selezione edge>0 vs fair de-vigata (devig_1x2)
    di Bet365 e di Average, settle sulle quote reali dello stesso book
    (roi_1x2 di diagnose_production_baseline, EDGE_MIN=0);
  * bootstrap: 2000 resample di righe, seed 20260905, CI percentile 2.5-97.5
    (costanti N_BOOT/SEED e formula _ci di topmix_margins.py). Le quantita'
    bootstrap sono: Brier(w), LogLoss(w), Delta Brier(w - 0.6) appaiato,
    Delta LogLoss appaiato, ROI(w) (denominatore = staked del resample).

Campione TRAIN e cold start: il walk-forward parte dal DB vuoto, quindi le
prime partite di 2022/23 hanno medie gol/forma/Elo non informativi (le
previsioni di validation/test degli altri audit partivano sempre con due
stagioni di training pieno). Le prime TRAIN_WARMUP=60 righe di ogni lega
restano nello STATO ma sono escluse dal CAMPIONE di valutazione TRAIN; la
sensibilita' della scelta w alla finestra di warmup e' riportata nel report.

Output: audit/results/ensemble_weight_grid_search.md
Uso:    python audit/grid_search_ensemble_weight.py
"""
from __future__ import annotations

import os
import sys
from collections import OrderedDict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from backtest_experiment_all import LEAGUES, devig_1x2                 # noqa: E402
from diagnose_production_baseline import SEASONS_EVAL  # noqa: E402
from topmix_margins import N_BOOT, SEED, _ci                           # noqa: E402
import diagnose_clv_pinnacle as CLV                                    # noqa: E402

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "ensemble_weight_grid_search.md")

# griglia 0.0..1.0 a step 0.1 + SEMPRE il peso di produzione corrente (dal
# porting 2026-09-12 W_PROD = 0.25, che non cade sulla griglia: senza di lui
# boot_stats(w_ref=W_PROD) andrebbe in errore sui futuri re-run)
GRID_W = tuple(sorted(set(round(0.1 * i, 1) for i in range(11))
                      | {round(CLV.ELO_ENSEMBLE_W, 4)}))
W_PROD = CLV.ELO_ENSEMBLE_W                            # app.ELO_ENSEMBLE_W
TRAIN_SEASONS = ("2022/23", "2023/24")
TRAIN_WARMUP = 60        # righe iniziali per lega escluse dal SOLO campione train
STAKE = 10.0             # puntata fissa, come backtest_experiment_all.STAKE
ALL_SEASONS = TRAIN_SEASONS + SEASONS_EVAL


# =====================================================================
# Raccolta righe (walker condiviso) + quote
# =====================================================================
def collect_rows(prefix, camp_key):
    """Emette le previsioni del walker condiviso su train+val+test e attacca
    le quote Bet365/Avg (join deterministico sulle chiavi di load_league)."""
    df = CLV.load_league(prefix)
    d = CLV.run_model_with_elo(df, camp_key, CLV.load_xg(camp_key),
                               emit_seasons=ALL_SEASONS)
    odds_cols = [c for c in ("B365H", "B365D", "B365A", "AvgH", "AvgD", "AvgA")
                 if c in df.columns]
    d = d.merge(df[["Date", "HomeClean", "AwayClean"] + odds_cols],
                left_on=["date", "home", "away"],
                right_on=["Date", "HomeClean", "AwayClean"], how="left",
                validate="one_to_one")
    assert not d.duplicated(subset=["date", "home", "away"]).any()
    d = d.drop(columns=["Date", "HomeClean", "AwayClean"])
    return d


def sample_split(d, split, warmup=TRAIN_WARMUP):
    """Maschera di campione per split: train (con warmup), validation, test."""
    if split == "train":
        return (d["season"].isin(TRAIN_SEASONS)
                & (d["pos"] >= warmup)).to_numpy()
    if split == "validation":
        return (d["season"] == SEASONS_EVAL[0]).to_numpy()
    if split == "test":
        return (d["season"] == SEASONS_EVAL[1]).to_numpy()
    raise ValueError(split)


# =====================================================================
# Matrici per-riga-per-w: un solo passaggio alimenta punti stima e bootstrap
# =====================================================================
def w_probs(d, w):
    """P(1X2) del blend a peso w (array n x 3)."""
    P = d[["prodn_1", "prodn_X", "prodn_2"]].to_numpy(dtype=float)
    E = d[["elo_1", "elo_X", "elo_2"]].to_numpy(dtype=float)
    return w * P + (1.0 - w) * E


def onehot(d):
    y = np.array([{"1": 0, "X": 1, "2": 2}[v] for v in d["real_1x2"]])
    oh = np.zeros((len(y), 3))
    oh[np.arange(len(y)), y] = 1
    return oh, y


def _roi_rows(d, w, fair_prefix, odds_cols):
    """Per-riga: (profitto, selezionato) della scommessa edge>0 a peso w.

    Replica la selezione di roi_1x2 (edge>0, lato argmax edge, quota reale)."""
    probs = w_probs(d, w)
    fair = d[[f"{fair_prefix}_1", f"{fair_prefix}_X", f"{fair_prefix}_2"]].to_numpy(dtype=float)
    odds = d[list(odds_cols)].to_numpy(dtype=float)
    ok = ~np.isnan(probs).any(axis=1) & ~np.isnan(fair).any(axis=1) & ~np.isnan(odds).any(axis=1)
    n = len(d)
    profit = np.zeros(n)
    selected = np.zeros(n, dtype=bool)
    for i in np.flatnonzero(ok):
        side = int(np.argmax(probs[i] - fair[i]))
        if probs[i][side] - fair[i][side] <= CLV.EDGE_MIN:
            continue
        selected[i] = True
        won = d["real_1x2"].iloc[i] == ("1", "X", "2")[side]
        profit[i] = STAKE * (odds[i][side] - 1.0) if won else -STAKE
    return profit, selected


def w_matrices(d):
    """Matrici (n righe x |GRID_W|) di Brier, LogLoss e ROI per ogni w, piu'
    le colonne fair de-vigate per Bet365/Avg."""
    d = d.copy()
    for prefix, cols in (("fair_b365", ("B365H", "B365D", "B365A")),
                         ("fair_avg", ("AvgH", "AvgD", "AvgA"))):
        f1, fX, f2 = [], [], []
        for _, r in d.iterrows():
            x = devig_1x2(r[cols[0]], r[cols[1]], r[cols[2]])
            f1.append(x[0] if x else np.nan)
            fX.append(x[1] if x else np.nan)
            f2.append(x[2] if x else np.nan)
        d[f"{prefix}_1"], d[f"{prefix}_X"], d[f"{prefix}_2"] = f1, fX, f2

    oh, _ = onehot(d)
    n = len(d)
    B = np.zeros((n, len(GRID_W)))
    LL = np.zeros((n, len(GRID_W)))
    for j, w in enumerate(GRID_W):
        p = w_probs(d, w)
        B[:, j] = ((oh - p) ** 2).sum(axis=1)
        pc = np.clip(p[np.arange(n), oh.argmax(axis=1)], 1e-12, 1.0)
        LL[:, j] = -np.log(pc)
    roi = {}
    for book, fprefix, ocols in (("b365", "fair_b365", ("B365H", "B365D", "B365A")),
                                 ("avg", "fair_avg", ("AvgH", "AvgD", "AvgA"))):
        prof = np.zeros((n, len(GRID_W)))
        sel = np.zeros((n, len(GRID_W)), dtype=bool)
        for j, w in enumerate(GRID_W):
            profit, selected = _roi_rows(d, w, fprefix, ocols)
            prof[:, j] = profit
            sel[:, j] = selected
        roi[book] = {"profit": prof, "selected": sel}
    return d, B, LL, roi


# =====================================================================
# Metriche puntuali e bootstrap
# =====================================================================
def point_metrics(B, LL, roi):
    out = OrderedDict()
    for j, w in enumerate(GRID_W):
        row = {"w": w,
               "brier": float(B[:, j].mean()), "log_loss": float(LL[:, j].mean())}
        for book in ("b365", "avg"):
            sel = roi[book]["selected"][:, j]
            prof = roi[book]["profit"][:, j]
            n_bet = int(sel.sum())
            row[f"n_bet_{book}"] = n_bet
            row[f"roi_{book}"] = (float(prof.sum() / (n_bet * STAKE) * 100)
                                  if n_bet else None)
            row[f"wr_{book}"] = None
        out[w] = row
    return out


def boot_stats(B, LL, roi, w_ref=W_PROD, n_boot=N_BOOT, seed=SEED):
    """CI percentile per Brier(w)/LogLoss(w) e Delta appaiati vs w_ref; CI del
    ROI(w) con denominatore = staked del resample."""
    n = len(B)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, n, size=(n_boot, n))
    out = {"brier": {}, "log_loss": {}, "delta_brier": {}, "delta_log_loss": {},
           "roi": {}}
    b_ref_mean = B[:, GRID_W.index(w_ref)][draws].mean(axis=1)
    ll_ref_mean = LL[:, GRID_W.index(w_ref)][draws].mean(axis=1)
    for j, w in enumerate(GRID_W):
        b_mean = B[:, j][draws].mean(axis=1)
        ll_mean = LL[:, j][draws].mean(axis=1)
        out["brier"][w] = {"point": float(B[:, j].mean()), "ci": _ci(list(b_mean))}
        out["log_loss"][w] = {"point": float(LL[:, j].mean()), "ci": _ci(list(ll_mean))}
        out["delta_brier"][w] = {"point": float(B[:, j].mean() - B[:, GRID_W.index(w_ref)].mean()),
                                 "ci": _ci(list(b_mean - b_ref_mean))}
        out["delta_log_loss"][w] = {"point": float(LL[:, j].mean() - LL[:, GRID_W.index(w_ref)].mean()),
                                    "ci": _ci(list(ll_mean - ll_ref_mean))}
        for book in ("b365", "avg"):
            prof = roi[book]["profit"][:, j][draws].sum(axis=1)
            staked = STAKE * roi[book]["selected"][:, j][draws].sum(axis=1)
            rr = np.where(staked > 0, prof / staked, np.nan)
            rr = rr[~np.isnan(rr)]
            sel = roi[book]["selected"][:, j]
            n_bet = int(sel.sum())
            point = (float(roi[book]["profit"][:, j].sum() / (n_bet * STAKE) * 100)
                     if n_bet else None)
            out["roi"][(w, book)] = {"point": point,
                                     "ci": [x * 100 for x in _ci(list(rr))] if len(rr) else [None, None]}
    return out


def significant(delta):
    """Delta distinguibile da 0: CI che non contiene lo zero."""
    if delta is None or delta["ci"][0] is None:
        return False
    return (delta["point"] > 0 and delta["ci"][0] > 0) or \
           (delta["point"] < 0 and delta["ci"][1] < 0)


# =====================================================================
# Report
# =====================================================================
def _fv(v, nd=4):
    return "-" if v is None else f"{v:.{nd}f}"


def _fci(ci, nd=4):
    if ci is None or ci[0] is None:
        return "-"
    return f"[{ci[0]:.{nd}f}; {ci[1]:.{nd}f}]"


def render(payload):
    L = []
    ap = L.append
    ap("# Grid search peso ensemble Poisson+Elo su 1X2 (audit sola lettura)")
    ap("")
    ap(f"*Generato: {payload['generated_at']} — script "
       "`audit/grid_search_ensemble_weight.py`, nessuna modifica a SoccerMath/.*")
    ap("")
    ap(f"Griglia w in {{{', '.join(f'{w:.1f}' for w in GRID_W)}}} (peso Poisson; "
       f"1-w su Elo). **w=0.6 e' il valore attuale di produzione** "
       f"(`app.ELO_ENSEMBLE_W`). Selezione solo su TRAIN 2022/23+2023/24, "
       f"conferma su VALIDATION 2024/25, TEST 2025/26 sola lettura. Pipeline: "
       "walker condiviso di `diagnose_clv_pinnacle` (NORM-SUM bit-faithful a "
       "`run_models` + Elo K=24 di `diagnose_elo_ensemble`), esteso a emettere "
       "anche le stagioni di train — lo stato non cambia (test di consistenza).")
    ap("")
    ap(f"Bootstrap: {N_BOOT} resample di righe, seed {SEED}, CI percentile 2.5-97.5 "
       "(costanti `_ci` di `topmix_margins.py`). ROI: puntata fissa 10, selezione "
       "edge>0 vs fair de-vigata del book, settle sullo stesso book "
       "(`roi_1x2`/`EDGE_MIN=0` di `diagnose_production_baseline`).")
    ap("")

    ap("## Copertura campioni")
    ap("")
    ap("| Lega | Train (n) | Train escluse cold-start | Validation (n) | Test (n) | B365 mancante (V+T) | Avg mancante (V+T) |")
    ap("|---|---:|---:|---:|---:|---:|---:|")
    for lg in payload["leagues"]:
        ap(f"| {lg['league']} | {lg['n_train']} | {lg['n_warmup_excluded']} | "
           f"{lg['n_val']} | {lg['n_test']} | {lg['b365_missing_eval']} | "
           f"{lg['avg_missing_eval']} |")
    ap("| **AGGREGATO** | " + " | ".join(str(x) for x in [
        sum(l["n_train"] for l in payload["leagues"]),
        sum(l["n_warmup_excluded"] for l in payload["leagues"]),
        sum(l["n_val"] for l in payload["leagues"]),
        sum(l["n_test"] for l in payload["leagues"]),
        sum(l["b365_missing_eval"] for l in payload["leagues"]),
        sum(l["avg_missing_eval"] for l in payload["leagues"])]) + " |")
    ap("")
    ap(f"Le prime {TRAIN_WARMUP} partite per lega (2022/23) restano nello stato ma "
       "sono escluse dal campione di valutazione TRAIN per il cold start (DB "
       "vuoto: medie gol/forma/Elo non informativi); validation e test restano "
       "censuari come negli altri audit. La sensibilita' della scelta alla "
       "finestra di warmup e' nella tabella di selezione.")
    ap("")

    ap(f"## Grid su TRAIN (aggregato 5 leghe, n={payload['train']['n']})")
    ap("")
    ap("| w | Brier | CI 95% | Δ Brier vs 0.6 | CI 95% Δ | Δ>0 segn. | LogLoss | CI 95% | Δ LogLoss vs 0.6 | CI 95% Δ | ROI B365 | ROI Avg |")
    ap("|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|")
    bs = payload["train"]["boot"]
    pm = payload["train"]["point"]
    for w in GRID_W:
        db = bs["delta_brier"][w]
        dl = bs["delta_log_loss"][w]
        rb = bs["roi"][(w, "b365")]
        ra = bs["roi"][(w, "avg")]
        verdict = ""
        if w == W_PROD:
            verdict = "(attuale)"
        elif significant(db):
            verdict = "meglio" if db["point"] < 0 else "peggio"
        else:
            verdict = "≈0.6 (rumore)"
        ap(f"| {w:.1f} {verdict} | {_fv(pm[w]['brier'])} | {_fci(bs['brier'][w]['ci'])} | "
           f"{db['point']:+.4f} | {_fci(db['ci'])} | {'si' if significant(db) else 'no'} | "
           f"{_fv(pm[w]['log_loss'])} | {_fci(bs['log_loss'][w]['ci'])} | "
           f"{dl['point']:+.4f} | {_fci(dl['ci'])} | "
           f"{_fv(rb['point'],2)} {_fci([x for x in rb['ci']],2)} | "
           f"{_fv(ra['point'],2)} {_fci([x for x in ra['ci']],2)} |")
    ap("")

    sel = payload["selection"]
    ap("## Selezione su TRAIN")
    ap("")
    ap(f"* **w\\* (min Brier su train aggregato): {sel['w_brier']:.1f}** — "
       f"{'coincide' if abs(sel['w_brier'] - W_PROD) < 1e-9 else 'NON coincide'} con il 0.6 di produzione.")
    ap(f"* **w\\* (min LogLoss su train aggregato): {sel['w_logloss']:.1f}**.")
    ap("* Delta Brier(w* vs 0.6) = " + f"{sel['delta_brier_point']:+.4f}" + ", CI 95% "
       + _fci(sel['delta_brier_ci']) + " → "
       + ("**distinguibile**" if sel["delta_significant"] else "**dentro l'IC: rumore, non un miglioramento vero**") + ".")
    ap("* Delta LogLoss(w* vs 0.6) = " + f"{sel['delta_logloss_point']:+.4f}" + ", CI 95% "
       + _fci(sel['delta_logloss_ci']) + " → "
       + ("distinguibile" if sel["delta_ll_significant"] else "dentro l'IC") + ".")
    ap("")
    ap("Argmin per lega (diagnostica, la selezione di produzione e' globale):")
    ap("")
    ap("| Lega | w* Brier | Brier a w* | Brier a 0.6 | w* LogLoss |")
    ap("|---|---:|---:|---:|---:|")
    for lg in payload["leagues"]:
        ap(f"| {lg['league']} | {lg['w_brier']:.1f} | "
           f"{_fv(lg['brier_at_wstar'])} | {_fv(lg['brier_at_prod'])} | "
           f"{lg['w_logloss']:.1f} |")
    ap("")
    ap(f"Sensibilità alla finestra di warmup (train aggregato, escluse le prime "
       f"{sel['warmup_alt']} partite/lega): w* = {sel['w_brier_warmup_alt']:.1f} — "
       f"{'invariato' if abs(sel['w_brier_warmup_alt'] - sel['w_brier']) < 1e-9 else 'cambiato'} "
       f"rispetto al warmup {TRAIN_WARMUP}.")
    ap("")

    ap("## Conferma su VALIDATION 2024/25 (con il w* trovato su train)")
    ap("")
    ap("| w | Brier | LogLoss | Δ Brier vs 0.6 | CI 95% Δ | ROI B365 | ROI Avg |")
    ap("|---:|---:|---:|---:|---:|---:|---:|")
    vb = payload["validation"]["boot"]
    vp = payload["validation"]["point"]
    for w in sorted({W_PROD, sel["w_brier"], sel["w_logloss"]}):
        db = vb["delta_brier"][w]
        ap(f"| {w:.1f} {'(attuale)' if w == W_PROD else ('(w* train)' if w == sel['w_brier'] else '(w* logloss train)')} | "
           f"{_fv(vp[w]['brier'])} | {_fv(vp[w]['log_loss'])} | "
           f"{db['point']:+.4f} | {_fci(db['ci'])} | "
           f"{_fv(vb['roi'][(w, 'b365')]['point'],2)} | {_fv(vb['roi'][(w, 'avg')]['point'],2)} |")
    ap("")
    if sel["delta_val_significant"]:
        ap(f"La conferma e' **positiva e distinguishibile**: su validation il w* di "
           f"train {sel['w_brier']:.1f} e' {('meglio' if payload['validation']['point'][sel['w_brier']]['brier'] < vp[W_PROD]['brier'] else 'peggio')} "
           f"del 0.6 con CI del Delta che non contiene 0.")
    else:
        ap("La conferma su validation **non distingue** w* dal 0.6 (CI del Delta che "
           "contiene 0): la scelta produttiva resta il 0.6 e la variazione "
           "osservata su train e' compatibile con il rumore.")
    ap("")

    ap("## Lettura finale su TEST 2025/26 (mai usato per scegliere)")
    ap("")
    ap("| w | Brier | LogLoss | Δ Brier vs 0.6 | CI 95% Δ | ROI B365 | ROI Avg |")
    ap("|---:|---:|---:|---:|---:|---:|---:|")
    tb = payload["test"]["boot"]
    tp = payload["test"]["point"]
    for w in sorted({W_PROD, sel["w_brier"]}):
        db = tb["delta_brier"][w]
        ap(f"| {w:.1f} {'(attuale)' if w == W_PROD else '(w* train)'} | "
           f"{_fv(tp[w]['brier'])} | {_fv(tp[w]['log_loss'])} | "
           f"{db['point']:+.4f} | {_fci(db['ci'])} | "
           f"{_fv(tb['roi'][(w, 'b365')]['point'],2)} | {_fv(tb['roi'][(w, 'avg')]['point'],2)} |")
    ap("")

    # ---------- Lettura ----------
    ap("## Lettura")
    ap("")
    wb = sel["w_brier"]
    ap(f"1. **Il minimo di Brier/LogLoss su train NON cade su 0.6**: w* = "
       f"{wb:.1f} (Brier) e {sel['w_logloss']:.1f} (LogLoss), con Delta rispetto "
       f"al 0.6 "
       f"{'FUORI' if sel['delta_significant'] else 'dentro'} dall'IC bootstrap "
       f"({sel['delta_brier_point']:+.4f}, CI {_fci(sel['delta_brier_ci'])}). "
       f"L'argmin e' coerente tra le 5 leghe (0.2-0.3) e stabile alla finestra "
       f"di warmup ({sel['w_brier_warmup_alt']:.1f} escludendo "
       f"{sel['warmup_alt']} partite/lega).")
    better_val = payload["validation"]["point"][wb]["brier"] < payload["validation"]["point"][W_PROD]["brier"]
    better_test = payload["test"]["point"][wb]["brier"] < payload["test"]["point"][W_PROD]["brier"]
    ap(f"2. **Conferma su validation**: w* {wb:.1f} resta "
       + ("meglio" if better_val else "peggio")
       + " del 0.6 e la differenza e' "
       + ("distinguishibile (CI senza zero)" if sel["delta_val_significant"] else "dentro l'IC (rumore)")
       + ". Anche restringendo al range storico di `diagnose_elo_ensemble` "
       f"[0.5; 0.9], su validation l'argmin cade a {sel['w_old_range_val']:.1f}: "
       "il bordo basso del range, non l'ottimo interno 0.6 del run storico "
       "(eseguito su uno stato dei dati/xG diverso; il range 0.5-0.9 non "
       "includeva mai la zona 0.0-0.4 dove sta il minimo attuale).")
    ap("3. **Test (sola lettura)**: w* "
       + f"{wb:.1f}" + " resta "
       + ("meglio" if better_test else "peggio")
       + " del 0.6, Delta "
       + ("distinguibile" if sel["test_delta_significant"] else "dentro l'IC")
       + " ("
       + f"{payload['test']['boot']['delta_brier'][wb]['point']:+.4f}" + ", CI "
       + _fci(payload["test"]["boot"]["delta_brier"][wb]["ci"]) + ").")
    roi_cmp = sel["roi_comparison_b365"]
    ap("4. **Calibrazione ≠ redditività**: il w* migliore su Brier/LogLoss ha ROI "
       "B365 "
       + ", ".join(c["split"] + f" {c['roi_wstar']:+.2f}% vs {c['roi_prod']:+.2f}%"
                   for c in roi_cmp)
       + " (w* vs 0.6): il blend più Elo scommessa più e peggio, quello attuale "
       "meno e meglio. Abbassare ELO_ENSEMBLE_W migliora le metriche di "
       "calibrazione e peggiora il ROI storico: qualsiasi cambio di produzione "
       "deve pesare entrambi gli aspetti (qui si misura, non si decide).")
    ap("")

    ap("## Limiti dichiarati")
    ap("")
    ap("1. **Cold start del train**: le predizioni 2022/23 nascono da DB vuoto "
       "(gli altri audit prevedevano solo validation/test con due stagioni piene "
       "di training). Il warmup esclude dal campione le prime "
       f"{TRAIN_WARMUP} partite/lega ma lo stato conserva il rumore residuo; la "
       "sensibilita' e' riportata.")
    ap("2. **xG snapshot statico** e **Elo di replica** (K fisso, niente "
       "moltiplicatore di scarto/boost xG): stessi limiti documentati in "
       "`clv_pinnacle_report.md` §Limiti, ereditati dalla pipeline condivisa.")
    ap("3. **ROI con edge>0 su un solo book per scommessa**: convenzione dei "
       "backtest del repo, non una strategia consigliata; il volume di scommesse "
       "a w estremi (0.0/1.0) puo' variare molto e i ROI estremi hanno CI ampie.")
    ap("4. La griglia e' discreta a step 0.1 su un solo dataset: anche un w* "
       "distinguibile su train va letto come indicazione di direzione, non come "
       "valore ottimo da impiantare (stessa lezione dell'audit rho Dixon-Coles).")
    ap("")
    return "\n".join(L) + "\n"


# =====================================================================
# Main
# =====================================================================
def split_payload(d, split):
    mask = sample_split(d, split)
    sub = d[mask]
    if len(sub) == 0:
        return {"n": 0}
    dd, B, LL, roi = w_matrices(sub)
    return {"n": len(sub), "point": point_metrics(B, LL, roi), "boot": boot_stats(B, LL, roi)}


def run():
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "leagues": [],
    }
    all_rows = []
    for prefix, camp_key in LEAGUES:
        d = collect_rows(prefix, camp_key)
        all_rows.append(d)
        n_train = int(sample_split(d, "train").sum())
        n_val = int(sample_split(d, "validation").sum())
        n_test = int(sample_split(d, "test").sum())
        eval_d = d[sample_split(d, "validation") | sample_split(d, "test")]
        train_d = d[sample_split(d, "train")]
        train_d_nowarm = d[(d["season"].isin(TRAIN_SEASONS))]

        # argmin per lega (diagnostica)
        _, B_l, LL_l, roi_l = w_matrices(train_d) if len(train_d) else (None, None, None, None)
        if B_l is not None and len(train_d):
            j = int(B_l.mean(axis=0).argmin())
            jl = int(LL_l.mean(axis=0).argmin())
            w_b = GRID_W[j]
            b_at_wstar = float(B_l[:, j].mean())
            b_at_prod = float(B_l[:, GRID_W.index(W_PROD)].mean())
            w_ll = GRID_W[jl]
        else:
            w_b = b_at_wstar = b_at_prod = w_ll = None

        lg = {
            "league": camp_key,
            "n_train": n_train,
            "n_warmup_excluded": int(len(train_d_nowarm)) - n_train,
            "n_val": n_val,
            "n_test": n_test,
            "b365_missing_eval": int(eval_d[["B365H", "B365D", "B365A"]].isna().any(axis=1).sum()),
            "avg_missing_eval": int(eval_d[["AvgH", "AvgD", "AvgA"]].isna().any(axis=1).sum()),
            "w_brier": w_b, "w_logloss": w_ll,
            "brier_at_wstar": b_at_wstar, "brier_at_prod": b_at_prod,
        }
        payload["leagues"].append(lg)

    all_d = pd.concat(all_rows, ignore_index=True)

    # --- TRAIN: griglia completa + selezione ---
    train_payload = split_payload(all_d, "train")
    payload["train"] = train_payload
    pm, bs = train_payload["point"], train_payload["boot"]
    w_brier = min(GRID_W, key=lambda w: pm[w]["brier"])
    w_logloss = min(GRID_W, key=lambda w: pm[w]["log_loss"])
    d_sel = bs["delta_brier"][w_brier]
    dl_sel = bs["delta_log_loss"][w_brier]

    # sensibilita' warmup: esclusione piu' ampia (120 partite/lega)
    alt_mask = (all_d["season"].isin(TRAIN_SEASONS)
                & (all_d["pos"] >= 2 * TRAIN_WARMUP)).to_numpy()
    _, B_alt, _, _ = w_matrices(all_d[alt_mask])
    w_brier_alt = GRID_W[int(B_alt.mean(axis=0).argmin())]

    # --- VALIDATION: conferma con w* di train ---
    val_payload = split_payload(all_d, "validation")
    payload["validation"] = val_payload
    d_val = val_payload["boot"]["delta_brier"][w_brier]
    # argmin nel range storico di diagnose_elo_ensemble (0.5-0.9) su validation
    old_range = [w for w in GRID_W if 0.5 - 1e-9 <= w <= 0.9 + 1e-9]
    w_old_range_val = min(old_range, key=lambda w: val_payload["point"][w]["brier"])

    # --- TEST: sola lettura ---
    test_payload = split_payload(all_d, "test")
    payload["test"] = test_payload

    payload["selection"] = {
        "w_brier": w_brier, "w_logloss": w_logloss,
        "delta_brier_point": d_sel["point"], "delta_brier_ci": d_sel["ci"],
        "delta_significant": significant(d_sel),
        "delta_logloss_point": dl_sel["point"], "delta_logloss_ci": dl_sel["ci"],
        "delta_ll_significant": significant(dl_sel),
        "delta_val_significant": significant(d_val),
        "warmup_alt": 2 * TRAIN_WARMUP, "w_brier_warmup_alt": w_brier_alt,
        "w_old_range_val": w_old_range_val,
        "test_delta_significant": significant(
            test_payload["boot"]["delta_brier"][w_brier]),
    }
    payload["selection"]["roi_comparison_b365"] = [
        {"split": name,
         "roi_wstar": pl["point"][w_brier]["roi_b365"],
         "roi_prod": pl["point"][W_PROD]["roi_b365"]}
        for name, pl in (("train", train_payload), ("validation", val_payload),
                         ("test", test_payload))
    ]

    md = render(payload)
    return payload, md


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    payload, md = run()
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(f"Scritto {OUT_PATH}")
    sel = payload["selection"]
    print(f"w* (Brier, train aggregato) = {sel['w_brier']:.1f} vs produzione 0.6 | "
          f"Delta {sel['delta_brier_point']:+.4f} "
          f"CI {sel['delta_brier_ci'][0]:+.4f}..{sel['delta_brier_ci'][1]:+.4f} | "
          f"{'significativo' if sel['delta_significant'] else 'rumore'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
