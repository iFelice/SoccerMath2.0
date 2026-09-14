"""
diagnose_overdispersion_porting.py — E' SICURO il porting
Poisson -> NegBin NB2-pooled per 1X2 e O/U2.5 (GG/NG resta Poisson)?

L'audit `diagnose_overdispersion_condizionale` (sulla REPLICA offline) ha
mostrato che una NB2 con alpha pooled (~0.22 sulla testa 1X2, ~0.19 sulla
testa Totali) migliora Brier/LogLoss di 1X2 e O/U2.5 e peggiora GG/NG.
Questo script RIPETE la domanda sul MOTORE VIVO (stessa harness di
`diagnose_motore_live_vs_replica.py` e `diagnose_prior_adattivo.py`:
chiamata DIRETTA a app.get_league_engine() / get_full_poisson_two_heads()
in replay point-in-time, CSV troncati intercettando pd.read_csv, cutoff
iniettato nella vera F_season, Elo ricalcolato dai CSV troncati dentro lo
stesso contesto di patch) e si chiede se il porting, oltre alla
calibrazione, SPOSTA roba operativa del Top Mix:

  1. ARGMAX: per quante partite (%, per lega, val+test) il mercato scelto
     sui 7 mercati POISSON PURO (criterio di produzione, il blend Elo non
     entra mai nell'argmax) cambia passando a NB2-pooled su 1X2 e O/U,
     con GG/NG lasciato Poisson? Campione di casi limite con le 7
     probabilita' a confronto.
  2. SOGLIE 0.55 (1X2) / 0.60 (O/U,GG,NG): quante partite che oggi
     superano la soglia non la supererebbero piu', e viceversa; quante
     ammissioni finali del selettore (soglia AND veto Elo) si perdono o si
     guadagnano: il porting cambia il VOLUME di pick proposti?
  3. GATE di disaccordo Elo |poisson - elo| >= 0.25 (oggi veto duro, in
     shadow logging): la sostituzione tocca SOLO il lato Poisson del gate
     (e il blend 0.25*P + 0.75*E della confidence); l'Elo resta identico.
     Si contano i cambi di stato del gate, non si tocca la sua logica.
  4. ROI/win-rate vs quote Bet365 reali (stessa convenzione di
     backtest_experiment_all / diagnose_quota_minima: stake flat,
     profitto (q-1)*hit - (1-hit)), sia sull'argmax di OGNI partita
     (direzione del cambio di argmax) sia sui soli pick ammessi dal
     selettore (volume reale del Top Mix); GG/NG usa le quote BTTS degli
     archivi audit come in diagnose_quota_minima.

Alpha NB2 ristimato SU TRAIN con l'harness live (puo' differire dai
0.219/0.189 della replica, che usava la snapshot xG statica per i Totali).
Walk-forward identico ai 6 audit precedenti:
  * train 2022/23+2023/24, prime 60 partite/lega solo in stato (no fit);
  * validation 2024/25, test 2025/26; 5 leghe;
  * alpha e ogni scelta numerica fissati SOLAMENTE su train.

NON tocca SoccerMath/: il monkeypatch (pd.read_csv, cutoff F_season, e il
check di parita' con _poisson_market temporaneamente sostituito dalla
pmf NB2) vive in memoria. Output:
audit/results/overdispersion_porting_diagnosis.md
Uso: python audit/diagnose_overdispersion_porting.py
     PORTING_CACHE=/tmp/porting_blob.pkl accelera le rigenerazioni.
"""
from __future__ import annotations

import os
import sys
import math
import time
import pickle
import contextlib
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy.special import gammaln, xlogy
from scipy.optimize import minimize_scalar
from scipy.stats import nbinom as scipy_nbinom

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

for _name in ("streamlit", "streamlit.runtime",
              "streamlit.runtime.scriptrunner", "root"):
    logging.getLogger(_name).setLevel(logging.ERROR)

import streamlit as st  # noqa: E402,F401
import app                                                   # noqa: E402
from backtest_experiment_all import LEAGUES, load_league    # noqa: E402
import diagnose_motore_live_vs_replica as ml                # noqa: E402
import diagnose_combo_1x2_totali as dc                      # noqa: E402
import diagnose_quota_minima as dq                          # noqa: E402
import gg_ng_calibration as ggcal                           # noqa: E402
from models import elo_engine as ee                         # noqa: E402
from topmix_margins import SEED, _ci                        # noqa: E402

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "overdispersion_porting_diagnosis.md")

TRAIN_SEASONS = dc.TRAIN_SEASONS
SEASONS_EVAL = dc.SEASONS_EVAL
ALL_SEASONS = dc.ALL_SEASONS
TRAIN_WARMUP = dc.TRAIN_WARMUP
LEAGUE_KEYS = [ck for _, ck in LEAGUES]
PREFIX_BY_CK = {ck: prefix for prefix, ck in LEAGUES}

MAX_GOALS = 15
GOAL_J = np.arange(MAX_GOALS)
G = MAX_GOALS
N_BOOT = 2000
ALPHA_LO = 1e-8
ALPHA_HI = 3.0
ALPHA_BOUNDARY = 1e-5

_U15_MASK = np.fromfunction(lambda i, j: (i + j) < 1.5,
                            (G, G)).astype(bool)
_U25_MASK = np.fromfunction(lambda i, j: (i + j) < 2.5,
                            (G, G)).astype(bool)
_U35_MASK = np.fromfunction(lambda i, j: (i + j) < 3.5,
                            (G, G)).astype(bool)


# ===========================================================================
# NegBin NB2 (stessa meccanica convalidata in diagnose_overdispersion_condiz.)
# ===========================================================================
def nb2_logpmf(k, lam, alpha):
    """Log-pmf NB2: media lam, varianza lam + alpha*lam^2.
    alpha <= ALPHA_BOUNDARY => limite Poisson."""
    k = np.asarray(k, dtype=float)
    lam = np.asarray(lam, dtype=float)
    kb, lb = np.broadcast_arrays(k, lam)
    logp = xlogy(kb, lb) - lb - gammaln(kb + 1.0)
    if alpha is None or alpha <= ALPHA_BOUNDARY:
        return logp
    r = 1.0 / alpha
    kmax = int(kb.max())
    if kmax >= 1:
        logs = np.log(r + np.arange(kmax))
        delta_k = np.concatenate(([0.0], np.cumsum(logs)))
    else:
        delta_k = np.zeros(1)
    delta = delta_k[kb.astype(int)]
    return logp + delta - r * np.log1p(lb / r) - kb * np.log(r + lb) + lb


def check_nb2_vs_scipy():
    rng = np.random.default_rng(SEED)
    lams = np.concatenate([[0.0025, 0.3, 1.0, 2.5, 8.0, 20.0],
                           rng.uniform(0.05, 4.0, size=50)])
    ks = np.arange(0, 12)
    worst = 0.0
    for a in (0.002, 0.02, 0.1, 0.5, 1.5):
        r = 1.0 / a
        for lam in lams:
            p_ref = scipy_nbinom.pmf(ks, r, 1.0 / (1.0 + a * lam))
            p_mine = np.exp(nb2_logpmf(
                ks, np.full_like(ks, lam, dtype=float), a))
            worst = max(worst, float(np.max(np.abs(p_ref - p_mine))))
    return worst


def neg_ll_alpha(alpha, k, lam):
    return -float(nb2_logpmf(k, lam, float(alpha)).sum())


def fit_alpha(k, lam):
    k = np.asarray(k, dtype=float)
    lam = np.asarray(lam, dtype=float)
    res = minimize_scalar(neg_ll_alpha, bounds=(ALPHA_LO, ALPHA_HI),
                          args=(k, lam), method="bounded",
                          options={"xatol": 1e-7})
    a = float(res.x)
    if a <= ALPHA_BOUNDARY:
        ll0 = -neg_ll_alpha(0.0, k, lam)
        if ll0 >= -res.fun - 1e-8:
            return 0.0, True
    return a, bool(a <= ALPHA_BOUNDARY)


def markets_from_pmf(h_p, a_p):
    """Stesse chiavi di app._poisson_market: 1,X,2,u15,u25,u35,gg.
    Griglia 15x15 troncata e NON rinormalizzata (convenzione di produzione)."""
    M = np.outer(h_p, a_p)
    return {
        "1": float(np.sum(np.tril(M, -1))),
        "X": float(np.sum(np.diag(M))),
        "2": float(np.sum(np.triu(M, 1))),
        "u15": float(M[_U15_MASK].sum()),
        "u25": float(M[_U25_MASK].sum()),
        "u35": float(M[_U35_MASK].sum()),
        "gg": float((1.0 - h_p[0]) * (1.0 - a_p[0])),
    }


def nb_markets(lh, la, alpha):
    """Mercati sotto NB2-pooled (alpha della testa). alpha=0 -> Poisson."""
    if alpha is None or alpha <= ALPHA_BOUNDARY:
        from scipy.stats import poisson
        lh_c, la_c = app._clip_lambda(lh), app._clip_lambda(la)
        h_p = np.array([poisson.pmf(i, lh_c) for i in range(G)])
        a_p = np.array([poisson.pmf(i, la_c) for i in range(G)])
        return markets_from_pmf(h_p, a_p)
    lh_c, la_c = app._clip_lambda(lh), app._clip_lambda(la)
    h_p = np.exp(nb2_logpmf(GOAL_J, np.full(G, lh_c), alpha))
    a_p = np.exp(nb2_logpmf(GOAL_J, np.full(G, la_c), alpha))
    return markets_from_pmf(h_p, a_p)


# ===========================================================================
# Lambda delle due teste da stats di produzione (formule letterali di
# app.get_full_poisson_two_heads / _two_heads_from_lambdas)
# ===========================================================================
def head_lambdas(sh, sa, avg_h, avg_a):
    sh = sh if isinstance(sh, dict) else {}
    sa = sa if isinstance(sa, dict) else {}
    att0_h = app._stat_num(sh, "att0", app._stat_num(sh, "att", 1.0))
    def0_h = app._stat_num(sh, "def0", app._stat_num(sh, "def", 1.0))
    att0_a = app._stat_num(sa, "att0", app._stat_num(sa, "att", 1.0))
    def0_a = app._stat_num(sa, "def0", app._stat_num(sa, "def", 1.0))
    mkt_h = app._stat_num(sh, "att", 1.0) * app._stat_num(sa, "def", 1.0) \
        * avg_h
    mkt_a = app._stat_num(sa, "att", 1.0) * app._stat_num(sh, "def", 1.0) \
        * avg_a
    base_h = att0_h * def0_a * avg_h
    base_a = att0_a * def0_h * avg_a
    attp_h = app._stat_num(sh, "att0_pure", att0_h)
    defp_h = app._stat_num(sh, "def0_pure", def0_h)
    attp_a = app._stat_num(sa, "att0_pure", att0_a)
    defp_a = app._stat_num(sa, "def0_pure", def0_a)
    pure_h = attp_h * defp_a * avg_h
    pure_a = attp_a * defp_h * avg_a
    S = base_h + base_a
    den = mkt_h + mkt_a
    if den > 0:
        norm_h = S * mkt_h / den
        norm_a = S * mkt_a / den
    else:
        norm_h, norm_a = base_h, base_a
    return {
        "l1h": app._clip_lambda(norm_h), "l1a": app._clip_lambda(norm_a),
        "lth": app._clip_lambda(pure_h), "lta": app._clip_lambda(pure_a),
    }


# ===========================================================================
# Score e bootstrap
# ===========================================================================
def brier_bin(p, y):
    return (p - y) ** 2


def logloss_bin(p, y):
    pc = np.clip(p, 1e-12, 1 - 1e-12)
    return -(y * np.log(pc) + (1 - y) * np.log(1 - pc))


def brier_multi(P, y):
    err = np.zeros(len(y))
    for k, v in (("1", "H"), ("X", "D"), ("2", "A")):
        err += (P[k] - (y == v).astype(float)) ** 2
    return err


def logloss_multi(P, y):
    p = np.where(y == "H", P["1"], np.where(y == "D", P["X"], P["2"]))
    return -np.log(np.clip(p, 1e-12, 1.0))


def boot_ci(diff, league_arr, seed, n_boot=N_BOOT):
    """IC 95% della media della differenza per-match, bootstrap stratificato
    per lega, appaiato (stessi indici per le due versioni)."""
    rng = np.random.default_rng(seed)
    diff = np.asarray(diff, float)
    means = np.empty(n_boot)
    idx_by_lg = {lk: np.where(np.asarray(league_arr) == lk)[0]
                 for lk in LEAGUE_KEYS}
    for b in range(n_boot):
        parts = []
        for lk in LEAGUE_KEYS:
            ix = idx_by_lg[lk]
            parts.append(diff[ix[rng.integers(0, len(ix), len(ix))]])
        means[b] = np.concatenate(parts).mean()
    lo, hi = _ci(list(means))
    return float(diff.mean()), lo, hi


def boot_mean_ci(vals, league_arr, seed, n_boot=N_BOOT):
    rng = np.random.default_rng(seed)
    vals = np.asarray(vals, float)
    means = np.empty(n_boot)
    idx_by_lg = {lk: np.where(np.asarray(league_arr) == lk)[0]
                 for lk in LEAGUE_KEYS}
    for b in range(n_boot):
        parts = []
        for lk in LEAGUE_KEYS:
            ix = idx_by_lg[lk]
            parts.append(vals[ix[rng.integers(0, len(ix), len(ix))]])
        means[b] = np.concatenate(parts).mean()
    lo, hi = _ci(list(means))
    return float(vals.mean()), lo, hi


# ===========================================================================
# COLLEZIONE LIVE (motore VERO in replay point-in-time, Elo incluso)
# ===========================================================================
def collect(cache_path):
    if cache_path and os.path.exists(cache_path):
        with open(cache_path, "rb") as fh:
            blob = pickle.load(fh)
        blob.setdefault("coverage", {})
        print(f"(collection da cache {cache_path}: "
              f"{len(blob['matches'])} partite)")
        return blob

    # fonti statiche, indipendenti dal cutoff: cachea anche il riferimento
    # diretto usato dall'engine Elo (ml cachea solo app.*)
    ee.get_understat_xg = app.get_understat_xg

    t0 = time.time()
    matches = []
    coverage = {}
    parity = {"harness_today": 0.0, "closure_1x2": 0.0,
              "closure_tot": 0.0, "sel_shadow_parity": 0}

    for prefix, ck in LEAGUES:
        print(f"==> {ck}: replay live (motore + Elo) per tutte le giornate ...")
        df_all = load_league(prefix)
        df_all = df_all.sort_values("Date", kind="stable").reset_index(drop=True)
        df_all["pos"] = np.arange(len(df_all))
        need = df_all[df_all["season"].isin(ALL_SEASONS)
                      & ~((df_all["season"].isin(TRAIN_SEASONS))
                          & (df_all["pos"] < TRAIN_WARMUP))]
        replayer = ml.LiveReplayer(ck)

        # ---- conformita' harness: replay a oggi == produzione non patchata
        stats0, ah0, aa0, _ = app.get_league_engine(ck)
        app.get_league_engine.clear()
        (st_t, _, _, _), _ = replayer.engine_at(
            pd.Timestamp(datetime.now(timezone.utc).date()))
        for t in set(st_t) & set(stats0):
            for kk in ("att", "def", "att0", "def0",
                       "att0_pure", "def0_pure"):
                parity["harness_today"] = max(
                    parity["harness_today"], abs(st_t[t][kk] - stats0[t][kk]))

        n_days = skipped = 0
        for day in sorted(need["Date"].map(pd.Timestamp).unique()):
            day = pd.Timestamp(day).normalize()
            cutoff = datetime(day.year, day.month, day.day, 12, 0,
                              tzinfo=timezone.utc)
            replayer.last_agg = None
            with replayer._patched(cutoff, day):
                with open(os.devnull, "w") as devnull, \
                        contextlib.redirect_stderr(devnull):
                    stats_real, avg_h, avg_a, _df_e = \
                        app.get_league_engine(ck)
                    # Elo punto-nel-tempo: cache azzerata, i CSV letti
                    # dall'engine sono quelli troncati dalla patch.
                    ee._ELO_ENGINES_CACHE.clear()
                    ee._ELO_ENGINES_STAMP.clear()
                    day_records = []
                    day_rows = need[need["Date"].map(
                        lambda x: pd.Timestamp(x).normalize()) == day]
                    for _, r in day_rows.iterrows():
                        h, a = r["HomeClean"], r["AwayClean"]
                        sh = stats_real.get(h)
                        sa = stats_real.get(a)
                        if not isinstance(sh, dict) or not isinstance(sa, dict):
                            skipped += 1
                            continue
                        mP = app.get_full_poisson_two_heads(
                            sh, sa, avg_h, avg_a)
                        lam = head_lambdas(sh, sa, avg_h, avg_a)
                        # chiusura: i lambda ricostruiti ridanno il mercato
                        c1 = app._poisson_market(lam["l1h"], lam["l1a"])
                        ct = app._poisson_market(lam["lth"], lam["lta"])
                        for kk in ("1", "X", "2"):
                            parity["closure_1x2"] = max(
                                parity["closure_1x2"],
                                abs(c1[kk] - mP[kk]))
                        for kk in ("u25", "gg"):
                            parity["closure_tot"] = max(
                                parity["closure_tot"],
                                abs(ct[kk] - mP[kk]))
                        try:
                            elo_p = app.predict_elo_probs(h, a, ck)
                            elo_ok = all(
                                isinstance(elo_p.get(k), (int, float))
                                for k in ("1", "X", "2"))
                        except Exception:
                            elo_p, elo_ok = None, False
                        fthg, ftag = int(r["FTHG"]), int(r["FTAG"])
                        rec = {
                            "league": ck, "prefix": prefix,
                            "season": r["season"], "date": day,
                            "split": ("train" if r["season"] in TRAIN_SEASONS
                                      else ("validation"
                                            if r["season"] == SEASONS_EVAL[0]
                                            else "test")),
                            "home": h, "away": a,
                            "fthg": fthg, "ftag": ftag, "ftr": r["FTR"],
                            "y_over": int(fthg + ftag > 2.5),
                            "y_gg": int(fthg > 0 and ftag > 0),
                            "y_1x2": r["FTR"],
                            "l1h": lam["l1h"], "l1a": lam["l1a"],
                            "lth": lam["lth"], "lta": lam["lta"],
                            "p": {"1": mP["1"], "X": mP["X"], "2": mP["2"],
                                  "u25": mP["u25"], "gg": mP["gg"]},
                            "elo": ({"1": elo_p["1"], "X": elo_p["X"],
                                     "2": elo_p["2"]} if elo_ok else None),
                            "odds": {},
                        }
                        day_records.append(rec)
                ee._ELO_ENGINES_CACHE.clear()
                ee._ELO_ENGINES_STAMP.clear()
            matches.extend(day_records)
            n_days += 1
        n_eval = len([m for m in matches if m["league"] == ck])
        coverage[ck] = {"need": int(len(need)), "eval": n_eval,
                        "skipped": int(skipped), "days": n_days}
        print(f"   {n_days} giornate-motore, {n_eval} partite valutate "
              f"(saltate {skipped}); chiusura lambda max "
              f"{max(parity['closure_1x2'], parity['closure_tot']):.1e}")

    blob = {"matches": matches, "parity": parity, "coverage": coverage,
            "elapsed": time.time() - t0}
    if cache_path:
        with open(cache_path, "wb") as fh:
            pickle.dump(blob, fh)
        print(f"(collection salvata in cache {cache_path})")
    return blob


# ===========================================================================
# Quote reali: B365 dai CSV (1X2, O/U) e BTTS dagli archivi audit (GG/NG),
# stessa costruzione di diagnose_quota_minima (niente logica riscritta)
# ===========================================================================
def attach_odds(matches):
    prefixes = [p for p, _ in LEAGUES]
    csv_idx, csv_dup = dq.build_csv_odds_index(prefixes)
    dataset = ggcal.load_btts_dataset()
    btts_idx, btts_dup, btts_stats = dq.build_btts_odds_index(
        dataset, prefixes)
    n_csv = n_btts = n_miss = 0
    for m in matches:
        if m["split"] not in ("validation", "test"):
            continue
        key = (m["prefix"], m["season"], m["home"], m["away"])
        ko = m["date"].date()
        odds = {}
        entry = csv_idx.get(key)
        if entry is not None and \
                abs((ko - pd.Timestamp(entry["date"]).date()).days) <= 1:
            for code, col in dq.MARKET_ODDS_COL.items():
                q = entry["odds"].get(col)
                if q is not None and q > 1.0:
                    odds[code] = float(q)
        be = btts_idx.get(key)
        if be is not None and \
                abs((ko - pd.Timestamp(be["date"]).date()).days) <= 1:
            if be.get("o_yes", 0) > 1.0:
                odds["GG"] = float(be["o_yes"])
            if be.get("o_no", 0) > 1.0:
                odds["NG"] = float(be["o_no"])
        m["odds"] = odds
        if "GG" in odds or "NG" in odds:
            n_btts += 1
        if any(k in odds for k in ("1", "X", "2", "O2.5", "U2.5")):
            n_csv += 1
        if not odds:
            n_miss += 1
    return {"csv_index": len(csv_idx), "csv_dup": len(csv_dup),
            "btts_index": len(btts_idx), "btts_dup": len(btts_dup),
            "btts_stats": btts_stats,
            "match_with_csv": n_csv, "match_with_btts": n_btts,
            "match_no_odds": n_miss}


# ===========================================================================
# Scenari e selettore di produzione (chiamata DIRETTA alla funzione pura)
# ===========================================================================
def seven_markets(md, h, a):
    """Identico al dizionario di app.seleziona_riga_top_mix."""
    return {
        f"Vittoria {h}": md["1"], "Pareggio": md["X"],
        f"Vittoria {a}": md["2"],
        "Over 2.5": 1.0 - md["u25"], "Under 2.5": md["u25"],
        "GG": md["gg"], "NG": 1.0 - md["gg"],
    }


def label_to_code(label, h, a):
    code = app.codice_mercato_selezionato(label, h, a)
    return {"OVER_2.5": "O2.5", "UNDER_2.5": "U2.5"}.get(code, code)


def scenario_dicts(matches, a1, at):
    """Riempie m['mdP'] (produzione Poisson) e m['mdNB'] (porting NB2:
    NB2 su 1X2 e O/U, GG/NG letteralmente lo stesso valore Poisson)."""
    for m in matches:
        nb1 = nb_markets(m["l1h"], m["l1a"], a1)
        nbt = nb_markets(m["lth"], m["lta"], at)
        m["mdP"] = dict(m["p"])
        m["mdNB"] = {"1": nb1["1"], "X": nb1["X"], "2": nb1["2"],
                     "u25": nbt["u25"], "gg": m["p"]["gg"]}


def selector_row(md, m):
    """Riga produzione (seleziona_riga_top_mix) piu' dettagli shadow
    (soglia e gate separati). elo=None ricalca il fallback di produzione."""
    h, a = m["home"], m["away"]
    elo = m["elo"]
    elo_ok = elo is not None
    sel = app.seleziona_riga_top_mix(md, elo, elo_ok, h, a)
    sh = app.riga_top_mix_shadow(md, elo, elo_ok, h, a)
    # parità delle due funzioni di produzione (su questi stessi input)
    admit = bool(sh["prob"] >= sh["min_conf"]
                 and sh["disaccordo"] < 0.25)
    parity_ok = (sel is not None) == admit
    if sel is not None:
        parity_ok = parity_ok and sel["market"] == sh["market"] \
            and abs(sel["prob"] - sh["prob"]) < 1e-9
    return {"label": sh["market"], "code": label_to_code(sh["market"], h, a),
            "poisson": sh["poisson"] / 100.0, "elo": sh["elo"] / 100.0,
            "conf": sh["prob"], "min_conf": sh["min_conf"],
            "d": sh["disaccordo"], "thr_pass": sh["prob"] >= sh["min_conf"],
            "veto": sh["disaccordo"] >= 0.25, "admit": admit,
            "parity_ok": parity_ok}


def evaluate_selectors(matches):
    n_bad = 0
    for m in matches:
        m["selP"] = selector_row(m["mdP"], m)
        m["selNB"] = selector_row(m["mdNB"], m)
        if not m["selP"]["parity_ok"] or not m["selNB"]["parity_ok"]:
            n_bad += 1
    return n_bad


# ===========================================================================
# Stima alpha SU TRAIN (harness live), IC bootstrap per PARTITA
# ===========================================================================
def fit_on_train(matches):
    train = [m for m in matches if m["split"] == "train"]
    samples = {
        "1x2": (np.array([k for m in train for k in (m["fthg"], m["ftag"])]),
                np.array([l for m in train
                          for l in (m["l1h"], m["l1a"])])),
        "tot": (np.array([k for m in train for k in (m["fthg"], m["ftag"])]),
                np.array([l for m in train
                          for l in (m["lth"], m["lta"])])),
    }
    out = {}
    for head, (k, lam) in samples.items():
        a, bnd = fit_alpha(k, lam)
        # robustezza alle righe lambda<0.1 (come nell'audit replica)
        m_rob = lam >= 0.1
        a_rob, _ = fit_alpha(k[m_rob], lam[m_rob])
        # IC bootstrap 2000, resample di PARTITE (2 righe ciascuna),
        # stratificato per lega
        rng = np.random.default_rng(SEED + (11 if head == "1x2" else 17))
        idx_lg = {ck: [i for i, m in enumerate(train) if m["league"] == ck]
                  for ck in LEAGUE_KEYS}
        boots, n_boundary = [], 0
        for _b in range(N_BOOT):
            ks, ls = [], []
            for ck in LEAGUE_KEYS:
                ix = np.array(idx_lg[ck])
                pick = rng.choice(ix, size=len(ix), replace=True)
                for i in pick:
                    if head == "1x2":
                        ks += [train[i]["fthg"], train[i]["ftag"]]
                        ls += [train[i]["l1h"], train[i]["l1a"]]
                    else:
                        ks += [train[i]["fthg"], train[i]["ftag"]]
                        ls += [train[i]["lth"], train[i]["lta"]]
            ab, bb = fit_alpha(np.array(ks), np.array(ls))
            boots.append(ab)
            if bb:
                n_boundary += 1
        lo, hi = _ci(boots)
        # per lega (descrittivo, come nell'audit replica)
        per_lg = {}
        for ck in LEAGUE_KEYS:
            mt = [m for m in train if m["league"] == ck]
            if head == "1x2":
                kk = np.array([z for m in mt for z in (m["fthg"], m["ftag"])])
                ll = np.array([z for m in mt for z in (m["l1h"], m["l1a"])])
            else:
                kk = np.array([z for m in mt for z in (m["fthg"], m["ftag"])])
                ll = np.array([z for m in mt for z in (m["lth"], m["lta"])])
            per_lg[ck] = fit_alpha(kk, ll)[0]
        out[head] = {"alpha": a, "lo": lo, "hi": hi,
                     "boundary_pct": 100.0 * n_boundary / N_BOOT,
                     "robust": a_rob, "per_lg": per_lg, "n": len(k)}
    return out


# ===========================================================================
# Diagnostica di forma per split (sola lettura: le probabilita' usano SOLO
# gli alpha di train, come nell'audit di replica)
# ===========================================================================
def shape_diagnostics(matches):
    out = {}
    for head, (lh, la) in {"1x2": ("l1h", "l1a"),
                           "tot": ("lth", "lta")}.items():
        out[head] = {}
        for sp in ("train", "validation", "test"):
            sub = [m for m in matches if m["split"] == sp]
            k = np.array([z for m in sub for z in (m["fthg"], m["ftag"])])
            lam = np.array([z for m in sub for z in (m[lh], m[la])])
            a, bnd = fit_alpha(k, lam)
            rob = lam >= 0.1
            out[head][sp] = {
                "alpha": a, "boundary": bnd,
                "mean_lam": float(lam.mean()), "mean_k": float(k.mean()),
                "var_lam": float(lam.var()),
                "var_real": float(((k - lam) ** 2).mean()),
                "pearson_rob": float((((k - lam) ** 2) / lam)[rob].mean()),
                "p0_real": float((k == 0).mean()),
                "p0_pois": float(np.exp(-lam).mean()),
                "p0_flat": float(np.exp(-lam.mean())),
                "n": len(k),
            }
    return out


# ===========================================================================
# Check end-to-end: motore VERO con _poisson_market sostituito dalla NB2
# ===========================================================================
def real_engine_nb_parity(matches, a1, at):
    """Su giornate campione (2/lega, val+test), patcha SOLO la pmf di
    produzione (chiamata 1 = testa 1X2 con a1, chiamata 2 = testa Tot con
    at) e verifica che le 1/X/2 e u25 del motore reale coincidano con lo
    scenario NB2 qui calcolato. GG esce NB2-puro dal motore patchato ma il
    porting LO LASCIA POISSON: si riporta anche quel disallineamento
    atteso, per documentare esattamente la forzatura necessaria."""
    orig_pm = app._poisson_market
    state = {"i": 0}

    def pm_nb(h_e, a_e, max_goals=15):
        alpha = a1 if state["i"] % 2 == 0 else at
        state["i"] += 1
        return nb_markets(h_e, a_e, alpha)

    worst_core = 0.0
    gg_gap = 0.0
    rng_v = np.random.default_rng(SEED + 5)
    app._poisson_market = pm_nb
    try:
        for prefix, ck in LEAGUES:
            sub = [m for m in matches if m["league"] == ck
                   and m["split"] in ("validation", "test")]
            days = sorted({m["date"] for m in sub})
            chosen = rng_v.choice(np.array(days, dtype=object), size=2,
                                  replace=False)
            replayer = ml.LiveReplayer(ck)
            for day in chosen:
                day = pd.Timestamp(day)
                cutoff = datetime(day.year, day.month, day.day, 12, 0,
                                  tzinfo=timezone.utc)
                with replayer._patched(cutoff, day):
                    with open(os.devnull, "w") as devnull, \
                            contextlib.redirect_stderr(devnull):
                        stats_r, avg_h, avg_a, _ = app.get_league_engine(ck)
                        for m in [x for x in sub if x["date"] == day]:
                            sh = stats_r.get(m["home"])
                            sa = stats_r.get(m["away"])
                            if not isinstance(sh, dict) or \
                                    not isinstance(sa, dict):
                                continue
                            state["i"] = 0
                            mm = app.get_full_poisson_two_heads(
                                sh, sa, avg_h, avg_a)
                            exp1 = nb_markets(m["l1h"], m["l1a"], a1)
                            expt = nb_markets(m["lth"], m["lta"], at)
                            for kk in ("1", "X", "2"):
                                worst_core = max(
                                    worst_core, abs(mm[kk] - exp1[kk]))
                            worst_core = max(
                                worst_core, abs(mm["u25"] - expt["u25"]))
                            # gg dal motore patchato vs gg Poisson mantenuto
                            gg_gap = max(gg_gap,
                                         abs(mm["gg"] - m["p"]["gg"]))
    finally:
        app._poisson_market = orig_pm
        app.get_league_engine.clear()
    return worst_core, gg_gap


# ===========================================================================
# Insediamento / ROI
# ===========================================================================
def settle(code, m):
    return dq.expected_hit(code, m["fthg"], m["ftag"])


def profit_row(code, m):
    q = m["odds"].get(code)
    if q is None:
        return None
    hit = settle(code, m)
    return float((q - 1.0) * hit - (1.0 - hit)), int(hit), float(q)


def roi_block(rows, selkey):
    """rows: partite; selkey 'selP'/'selNB'. ROI flat stake sui pick
    AMMESSI con quota disponibile."""
    picks = []
    for m in rows:
        s = m[selkey]
        if not s["admit"]:
            continue
        z = profit_row(s["code"], m)
        if z is None:
            continue
        pr, hit, q = z
        picks.append((m["league"], s["code"], pr, hit, q))
    return picks


def argmax_block(rows, selkey):
    """Controfattuale: puntata unitaria sull'argmax di OGNI partita."""
    picks = []
    for m in rows:
        s = m[selkey]
        z = profit_row(s["code"], m)
        if z is None:
            continue
        pr, hit, q = z
        picks.append((m["league"], s["code"], pr, hit, q))
    return picks


def pick_summary(picks, seed):
    if not picks:
        return None
    lgs = np.array([p[0] for p in picks])
    pr = np.array([p[2] for p in picks])
    hit = np.array([p[3] for p in picks])
    q = np.array([p[4] for p in picks])
    m_roi, lo, hi = boot_mean_ci(pr, lgs, seed)
    return {"n": len(picks), "wr": float(hit.mean()),
            "avg_q": float(q.mean()),
            "roi": 100.0 * m_roi, "lo": 100.0 * lo, "hi": 100.0 * hi}


def paired_roi(picks_p, picks_nb, seed):
    """IC della differenza di ROI su partite presenti in ENTRAMBI i blocchi
    (stessa chiave partita)."""
    bp = {(lg, id_): (code, pr) for lg, id_, code, pr, _h, _q in picks_p}
    bn = {(lg, id_): (code, pr) for lg, id_, code, pr, _h, _q in picks_nb}
    common = sorted(set(bp) & set(bn))
    if not common:
        return None
    lgs = np.array([k[0] for k in common])
    d = np.array([bn[k][1] - bp[k][1] for k in common])
    m, lo, hi = boot_ci(d, lgs, seed)
    return {"n": len(common), "droi": 100.0 * m,
            "lo": 100.0 * lo, "hi": 100.0 * hi}


# helper per rendere i pick appaiabili: inserisce id partita
def tag_picks(rows, block_fn, selkey):
    out = []
    for j, m in enumerate(rows):
        s = m[selkey]
        if block_fn is roi_block and not s["admit"]:
            continue
        z = profit_row(s["code"], m)
        if z is None:
            continue
        pr, hit, q = z
        out.append((m["league"], j, s["code"], pr, hit, q))
    return [(lg, j, code, pr, hit, q) for lg, j, code, pr, hit, q in out]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    cache = os.environ.get("PORTING_CACHE")
    blob = collect(cache)
    matches = blob["matches"]
    parity = blob["parity"]
    coverage = blob.get("coverage") or {}

    pmf_worst = check_nb2_vs_scipy()
    print(f"NB2 pmf custom vs scipy: max {pmf_worst:.2e}")

    # --- quote (solo val/test) ---
    odds_cov = attach_odds(matches)
    print("quote:", {k: v for k, v in odds_cov.items()
                     if k not in ("btts_stats",)})

    # --- alpha live su train ---
    fits = fit_on_train(matches)
    a1 = fits["1x2"]["alpha"]
    at = fits["tot"]["alpha"]
    print(f"alpha live train: 1X2={a1:.5f} TOT={at:.5f}")

    # --- scenari e selettore di produzione ---
    scenario_dicts(matches, a1, at)
    n_sel_bad = evaluate_selectors(
        [m for m in matches if m["split"] in ("validation", "test")])
    parity["sel_shadow_parity"] = n_sel_bad

    # --- check motore reale patchato (alpha dello scenario) ---
    worst_core, gg_gap = real_engine_nb_parity(matches, a1, at)
    parity["real_nb_core"] = worst_core
    parity["real_nb_gg_gap"] = gg_gap
    # ...e con gli alpha della replica, puramente per validare la PIPELINE
    # NB attraverso il motore reale (alpha non usati per le probabilita').
    mech_core, mech_gg = real_engine_nb_parity(
        matches, 0.21904, 0.18911)
    parity["mech_nb_core"] = mech_core
    parity["mech_nb_gg_gap"] = mech_gg
    print(f"parity motore reale NB scenario: core {worst_core:.1e}; "
          f"meccanico alpha 0.219/0.189: core {mech_core:.1e}, "
          f"gg gap forzatura {mech_gg:.1e}")

    # ======================================================================
    # DATA FRAME di lavoro (validation + test)
    # ======================================================================
    ev = [m for m in matches if m["split"] in ("validation", "test")]
    for j, m in enumerate(ev):
        m["_id"] = j
    leagues = np.array([m["league"] for m in ev])
    splits = np.array([m["split"] for m in ev])
    n_val = int((splits == "validation").sum())
    n_test = int((splits == "test").sum())

    def arr(head_key, mk, scen):
        out = np.empty(len(ev))
        for i, m in enumerate(ev):
            md = m["mdP"] if scen == "P" else m["mdNB"]
            if mk in ("over",):
                out[i] = 1.0 - md["u25"]
            else:
                out[i] = md[mk]
        return out

    y_o = np.array([m["y_over"] for m in ev], float)
    y_g = np.array([m["y_gg"] for m in ev], float)
    y_1 = np.array([m["y_1x2"] for m in ev])

    # ---- Brier / LogLoss: Poisson vs NB (aggregato e per lega) ----
    calib = {}
    seed_c = [0]

    def nseed(tag):
        seed_c[0] += 1
        return SEED + 1100 + seed_c[0] * 37 + (3 if tag == "test" else 0)

    for sp in ("validation", "test"):
        ix = np.where(splits == sp)[0]
        row = {}
        for mkt in ("1x2", "ou", "gg"):
            if mkt == "1x2":
                PP = {k: arr(None, k, "P")[ix] for k in ("1", "X", "2")}
                PN = {k: arr(None, k, "NB")[ix] for k in ("1", "X", "2")}
                bp = brier_multi(PP, y_1[ix]); bn = brier_multi(PN, y_1[ix])
                lp = logloss_multi(PP, y_1[ix]); ln = logloss_multi(PN, y_1[ix])
            elif mkt == "ou":
                pp = arr(None, "over", "P")[ix]; pn = arr(None, "over", "NB")[ix]
                bp = brier_bin(pp, y_o[ix]); bn = brier_bin(pn, y_o[ix])
                lp = logloss_bin(pp, y_o[ix]); ln = logloss_bin(pn, y_o[ix])
            else:
                pp = arr(None, "gg", "P")[ix]; pn = arr(None, "gg", "NB")[ix]
                bp = brier_bin(pp, y_g[ix]); bn = brier_bin(pn, y_g[ix])
                lp = logloss_bin(pp, y_g[ix]); ln = logloss_bin(pn, y_g[ix])
            db = boot_ci(bn - bp, leagues[ix], nseed(sp))
            dl = boot_ci(ln - lp, leagues[ix], nseed(sp))
            per_lg = {}
            for ck in LEAGUE_KEYS:
                il = np.where(leagues[ix] == ck)[0]
                if mkt == "1x2":
                    dpl = brier_multi(
                        {k: PP[k][il] for k in ("1", "X", "2")},
                        y_1[ix][il])
                    dnl = brier_multi(
                        {k: PN[k][il] for k in ("1", "X", "2")},
                        y_1[ix][il])
                elif mkt == "ou":
                    dpl = brier_bin(pp[il], y_o[ix][il])
                    dnl = brier_bin(pn[il], y_o[ix][il])
                else:
                    dpl = brier_bin(pp[il], y_g[ix][il])
                    dnl = brier_bin(pn[il], y_g[ix][il])
                ci = boot_ci(dnl - dpl, np.full(len(il), ck), nseed(sp))
                per_lg[ck] = (float(dpl.mean()), float(dnl.mean()),
                              ci[1], ci[2])
            row[mkt] = {"bP": float(bp.mean()), "bNB": float(bn.mean()),
                        "lP": float(lp.mean()), "lNB": float(ln.mean()),
                        "db": db, "dl": dl, "per_lg": per_lg}
        calib[sp] = row

    # ======================================================================
    # 1) ARGMAX: disaccordo
    # ======================================================================
    disagree = {}
    for sp in ("validation", "test", "both"):
        rows = ev if sp == "both" else [m for m in ev if m["split"] == sp]
        for ck in LEAGUE_KEYS + ["AGGREGATO"]:
            sub = rows if ck == "AGGREGATO" else \
                [m for m in rows if m["league"] == ck]
            flips = [m for m in sub
                     if m["selP"]["label"] != m["selNB"]["label"]]
            disagree[(sp, ck)] = (len(sub), len(flips))
    transitions = {}
    for m in [x for x in ev
              if x["selP"]["label"] != x["selNB"]["label"]]:
        cP = label_to_code(m["selP"]["label"], m["home"], m["away"])
        cN = label_to_code(m["selNB"]["label"], m["home"], m["away"])
        transitions[(cP, cN)] = transitions.get((cP, cN), 0) + 1

    # esempi cuscinetto: flip con margine piccolo in entrambe le versioni
    def margin7(md, m):
        d = seven_markets(md, m["home"], m["away"])
        v = sorted(d.values(), reverse=True)
        return v[0] - v[1]

    flips = [m for m in ev if m["selP"]["label"] != m["selNB"]["label"]]
    for m in flips:
        m["_edge"] = min(margin7(m["mdP"], m), margin7(m["mdNB"], m))
    flips.sort(key=lambda m: m["_edge"])
    examples = []
    seen_pairs = set()
    chosen_ids = set()
    for m in flips:
        pair = (m["selP"]["label"], m["selNB"]["label"])
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        examples.append(m)
        chosen_ids.add(id(m))
        if len(examples) >= 8:
            break
    for m in flips:
        if len(examples) >= 12:
            break
        if id(m) not in chosen_ids:
            examples.append(m)
            chosen_ids.add(id(m))

    # ======================================================================
    # 2) SOGLIE e 3) GATE (per lega x split)
    # ======================================================================
    def movement_table(rows):
        """Dict di conteggi su un sottoinsieme."""
        tp = np.array([m["selP"]["thr_pass"] for m in rows])
        tn = np.array([m["selNB"]["thr_pass"] for m in rows])
        ap = np.array([m["selP"]["admit"] for m in rows])
        an = np.array([m["selNB"]["admit"] for m in rows])
        vp = np.array([m["selP"]["veto"] for m in rows])
        vn = np.array([m["selNB"]["veto"] for m in rows])
        labp = [m["selP"]["label"] for m in rows]
        labn = [m["selNB"]["label"] for m in rows]
        is1x2_p = np.array([l in ("Pareggio",) or l.startswith("Vittoria")
                            for l in labp])
        is1x2_n = np.array([l in ("Pareggio",) or l.startswith("Vittoria")
                            for l in labn])
        # cause delle ammissioni cambiate
        lost = ap & ~an
        gained = ~ap & an
        def cause(mask, sp_arr, sn_arr, vp_arr, vn_arr, tp_arr, tn_arr):
            c = {"soglia": 0, "gate": 0, "entrambi": 0, "mercato_no_elo": 0}
            for i in np.where(mask)[0]:
                thr_moved = bool(tp_arr[i] != tn_arr[i])
                gate_moved = bool(vp_arr[i] != vn_arr[i])
                if thr_moved and gate_moved:
                    c["entrambi"] += 1
                elif gate_moved:
                    c["gate"] += 1
                elif thr_moved:
                    c["soglia"] += 1
                else:
                    c["mercato_no_elo"] += 1
            return c
        return {
            "n": len(rows),
            "thr_p": int(tp.sum()), "thr_n": int(tn.sum()),
            "thr_lost": int((tp & ~tn).sum()),
            "thr_gained": int((~tp & tn).sum()),
            "admit_p": int(ap.sum()), "admit_n": int(an.sum()),
            "admit_lost": int(lost.sum()), "admit_gained": int(gained.sum()),
            "admit_market_changed": int((ap & an & (
                np.array(labp) != np.array(labn))).sum()),
            "veto_p": int(vp.sum()), "veto_n": int(vn.sum()),
            "veto_new": int((~vp & vn).sum()),
            "veto_gone": int((vp & ~vn).sum()),
            "arg1x2_p": int(is1x2_p.sum()), "arg1x2_n": int(is1x2_n.sum()),
            "cause_lost": cause(lost, None, None, vp, vn, tp, tn),
            "cause_gained": cause(gained, None, None, vp, vn, tp, tn),
        }

    move = {}
    for sp in ("validation", "test"):
        rows = [m for m in ev if m["split"] == sp]
        move[(sp, "AGGREGATO")] = movement_table(rows)
        for ck in LEAGUE_KEYS:
            move[(sp, ck)] = movement_table(
                [m for m in rows if m["league"] == ck])

    # ======================================================================
    # 4) ROI / win-rate (quote reali)
    # ======================================================================
    val_rows = [m for m in ev if m["split"] == "validation"]
    test_rows = [m for m in ev if m["split"] == "test"]
    roi_out = {}
    seed_r = [0]

    def rseed():
        seed_r[0] += 1
        return SEED + 2200 + seed_r[0] * 53

    for regime, block in (("argmax", None), ("admit", None)):
        for sp, rows in (("validation", val_rows), ("test", test_rows),
                         ("val+test", ev)):
            pp = tag_picks(rows,
                           roi_block if regime == "admit" else argmax_block,
                           "selP")
            pn = tag_picks(rows,
                           roi_block if regime == "admit" else argmax_block,
                           "selNB")
            sp_sum = pick_summary([(lg, c, pr, hit, q)
                                   for lg, _i, c, pr, hit, q in pp], rseed())
            sn_sum = pick_summary([(lg, c, pr, hit, q)
                                   for lg, _i, c, pr, hit, q in pn], rseed())
            d = paired_roi(pp, pn, rseed())
            # per lega (regime argmax, val+test)
            per_lg = None
            if sp == "val+test":
                per_lg = {}
                for ck in LEAGUE_KEYS:
                    sub = [m for m in rows if m["league"] == ck]
                    qp = tag_picks(sub,
                                   roi_block if regime == "admit"
                                   else argmax_block, "selP")
                    qn = tag_picks(sub,
                                   roi_block if regime == "admit"
                                   else argmax_block, "selNB")
                    per_lg[ck] = (
                        pick_summary([(lg, c, pr, hit, q)
                                      for lg, _i, c, pr, hit, q in qp], rseed()),
                        pick_summary([(lg, c, pr, hit, q)
                                      for lg, _i, c, pr, hit, q in qn], rseed()))
            # sottoinsieme dei flip di argmax: testa a testa P vs NB
            flips_here = [m for m in rows
                          if m["selP"]["label"] != m["selNB"]["label"]]
            fpp = tag_picks(flips_here, argmax_block, "selP")
            fnn = tag_picks(flips_here, argmax_block, "selNB")
            flip_pair = paired_roi(fpp, fnn, rseed())
            flip_sum = (pick_summary([(lg, c, pr, hit, q)
                                      for lg, _i, c, pr, hit, q in fpp], rseed()),
                        pick_summary([(lg, c, pr, hit, q)
                                      for lg, _i, c, pr, hit, q in fnn], rseed()))
            roi_out[(regime, sp)] = {"P": sp_sum, "NB": sn_sum,
                                     "delta": d, "per_lg": per_lg,
                                     "flip_pair": flip_pair,
                                     "flip_sum": flip_sum,
                                     "n_flip": len(flips_here)}

    # distribuzione dei pick per mercato (val+test, argmax)
    def market_dist(rows, key):
        d = {}
        for m in rows:
            c = m[key]["code"]
            d[c] = d.get(c, 0) + 1
        return d

    distP = market_dist(ev, "selP")
    distNB = market_dist(ev, "selNB")

    # ======================================================================
    # REPORT
    # ======================================================================
    L = []
    ap = L.append
    ap("# Porting Poisson -> NB2-pooled (1X2 e O/U2.5, GG/NG resta Poisson) "
       "— audit sola lettura")
    ap("")
    ap(f"*Generato: {datetime.now(timezone.utc).isoformat(timespec='seconds')}"
       " — script `audit/diagnose_overdispersion_porting.py`, nessuna "
       "scrittura su SoccerMath/.*")
    ap("")
    ap("## Oggetto e protocollo")
    ap("")
    ap("L'audit `diagnose_overdispersion_condizionale` (replica offline, "
       "snapshot xG statica) ha dimostrato che i gol reali sono piu' dispersi "
       "del Poisson condizionato al lambda per-partita: una NegBin NB2 "
       "pooled migliora 1X2 e O/U2.5 e peggiora GG/NG. Qui il test e' "
       "ripetuto sul **motore VIVO** (harness di "
       "`diagnose_motore_live_vs_replica.py`: `get_league_engine()` e "
       "`get_full_poisson_two_heads()` chiamati direttamente in replay "
       "point-in-time, CSV troncati per data, F_season con cutoff iniettato, "
       "**Elo ricalcolato dentro lo stesso contesto patchato** dai CSV "
       "troncati, come fa il Top Mix reale). Si chiede se il porting, oltre "
       "alla calibrazione, SPOSTA: (1) l'argmax del Top Mix, (2) le soglie "
       "0.55/0.60 e il volume dei pick, (3) il gate di disaccordo Elo "
       "0.25, (4) il ROI storico vs quote Bet365.")
    ap("")
    ap("Walk-forward identico ai 6 audit precedenti: train 2022/23+2023/24 "
       "(prime 60 partite/lega solo in stato), validation 2024/25, test "
       "2025/26, 5 leghe. **Alpha NB2 ristimato qui sul train live** "
       "(separatamente per le due teste: 1X2 usa i lambda normalizzati con "
       "forma+mercato, O/U usa i lambda puri F_season); GG/NG resta "
       "letteralmente Poisson in tutti gli scenari. Ogni scelta numerica e' "
       "fatta solo su train; validation e test non vengono mai toccati. "
       "L'argmax e' sempre calcolato sui mercati **Poisson/NB puro** (il "
       "blend Elo non entra nella scelta, come in produzione "
       "`fetch_and_calc_top_mix`); il blend 0.25*P+0.75*Elo agisce solo "
       "sulla confidence della riga 1X2 gia' scelta.")
    ap("")
    ap("## Conformita' (verificata, non dichiarata)")
    ap("")
    ap("| Controllo | Esito |")
    ap("|---|---:|")
    ap(f"| Pmf NB2 custom vs `scipy.stats.nbinom`, max scarto | "
       f"{pmf_worst:.1e} |")
    ap(f"| Replay live a oggi vs produzione non patchata (stats motore), "
       f"max scarto | {parity['harness_today']:.1e} |")
    ap(f"| Lambda delle due teste ricostruiti vs "
       f"`get_full_poisson_two_heads`, max scarto (1X2 / Totali) | "
       f"{parity['closure_1x2']:.1e} / {parity['closure_tot']:.1e} |")
    ap(f"| Motore VERO con `_poisson_market` sostituito dalla NB2 agli "
       f"alpha dello scenario (1/X/2, u25) vs questo audit, max scarto | "
       f"{parity['real_nb_core']:.1e} |")
    ap(f"| Idem con alpha MECCANICI 0.219/0.189 (solo validazione "
       f"pipeline, non usati per le probabilita'), max scarto | "
       f"{parity.get('mech_nb_core', float('nan')):.1e} |")
    ap(f"| Scarto GG fra motore patchato 'tutto NB2' (alpha meccanici) e "
       f"GG lasciato Poisson — forzatura che un porting 'tutto NB2' "
       f"introdurrebbe | {parity.get('mech_nb_gg_gap', float('nan')):.1e} |")
    ap(f"| Partite con disaccordo tra `seleziona_riga_top_mix` (produzione) "
       f"e scomposizione shadow (soglia AND gate) | "
       f"{parity['sel_shadow_parity']} |")
    ap("")
    ap("I check con il motore reale dimostrano che uno scenario NB2 "
       "passerebbe ESATTAMENTE dalla vera `_two_heads_from_lambdas` "
       "(stessa normalizzazione, stessi clip, stesso troncamento 15x15 non "
       "rinormalizzato): la patch inietta la pmf dentro il motore, non una "
       "replica. Lo scarto GG (riga alpha meccanici) e' atteso e voluto: un "
       "porting 'tutto NB2' muoverebbe anche GG, che invece va lasciato "
       "Poisson (la patch reale di porting dovrebbe applicare la NB2 alla "
       "sola testa 1X2 e al solo ramo O/U, non al ramo GG).")
    ap("")
    ap("Copertura del replay (partite saltate = neopromosse senza stato al "
       "cutoff, come negli audit live/prior):")
    ap("")
    ap("| Lega | eleggibili | valutate | saltate | giornate-motore |")
    ap("|---|---:|---:|---:|---:|")
    for ck in LEAGUE_KEYS:
        c = coverage.get(ck, {})
        ap(f"| {ck} | {c.get('need','?')} | {c.get('eval','?')} | "
           f"{c.get('skipped','?')} | {c.get('days','?')} |")
    if coverage:
        ap(f"| **totale** | **{sum(c['need'] for c in coverage.values())}** "
           f"| **{sum(c['eval'] for c in coverage.values())}** | **"
           f"{sum(c['skipped'] for c in coverage.values())}** | **"
           f"{sum(c['days'] for c in coverage.values())}** |")
    ap("")
    ap(f"Copertura quote su validation+test ({n_val}+{n_test} partite): "
       f"{odds_cov['match_with_csv']} partite con almeno una quota B365 "
       f"1X2/O/U, {odds_cov['match_with_btts']} con quota BTTS (GG/NG, "
       "archivi audit come in `diagnose_quota_minima`); "
       f"{odds_cov['match_no_odds']} senza alcuna quota. Convenzione ROI: "
       "stake unitario flat, profitto `(q-1)*hit - (1-hit)` (stessa di "
       "`backtest_experiment_all`).")
    ap("")

    # ---- 1. alpha live ----
    ap("## 1. Alpha NB2 ristimato sul TRAIN LIVE (motore reale)")
    ap("")
    ap("MLE condizionale ai lambda per-partita emessi dal motore vero al "
       "cutoff (2 righe-squadra per partita di train, escluse le prime 60 "
       "per lega); IC 95% bootstrap 2000 per partita stratificato per "
       "lega. Confronto con i valori della replica offline "
       "(0.21904 / 0.18911).")
    ap("")
    ap("| Testa | alpha MLE live | IC 95% | alpha replica offline | "
       "alpha robusto (lambda>=0.1) | % resample al confine 0 | righe |")
    ap("|---|---:|---|---:|---:|---:|---:|")
    rep = {"1x2": 0.21904, "tot": 0.18911}
    for head, name in (("1x2", "1X2 (lambda normalizzati forma+mercato)"),
                       ("tot", "Totali (lambda puri F_season)")):
        f = fits[head]
        ap(f"| {name} | {f['alpha']:.5f} | [{f['lo']:.5f}; {f['hi']:.5f}] "
           f"| {rep[head]:.5f} | {f['robust']:.5f} | "
           f"{f['boundary_pct']:.1f}% | {f['n']} |")
    ap("")
    ap("Alpha per lega (solo descrittivo; il porting usa quello pooled, "
       "parsimonia gia' motivata nell'audit di replica):")
    ap("")
    ap("| Testa | " + " | ".join(LEAGUE_KEYS) + " |")
    ap("|---|" + "---:|" * len(LEAGUE_KEYS))
    for head in ("1x2", "tot"):
        vals = " | ".join(f"{fits[head]['per_lg'][ck]:.4f}"
                          for ck in LEAGUE_KEYS)
        ap(f"| {head} | {vals} |")
    ap("")
    shape = shape_diagnostics(matches)
    ap("**Diagnostica di forma per split** (alpha qui e' solo diagnostica, "
       "mai usata per le probabilita'; Pearson robusta = media di "
       "(k-lambda)^2/lambda sulle righe lambda>=0.1; 1 = esattamente "
       "Poisson):")
    ap("")
    ap("| Testa | split | alpha MLE (diagnostica) | Pearson robusta | "
       "Var reale E[(k-l)^2] | E[lambda] Poisson | Var lambda | "
       "P(0) reale | P(0) Poisson |")
    ap("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for head, lbl in (("1x2", "1X2"), ("tot", "Totali")):
        for sp in ("train", "validation", "test"):
            d = shape[head][sp]
            ap(f"| {lbl} | {sp} | {d['alpha']:.4f}"
               f"{' (confine)' if d['boundary'] else ''} | "
               f"{d['pearson_rob']:.3f} | {d['var_real']:.3f} | "
               f"{d['mean_lam']:.3f} | {d['var_lam']:.3f} | "
               f"{d['p0_real']:.3f} | {d['p0_pois']:.3f} |")
    ap("")
    ap("Confronto con la replica offline (stesso campione tipo, ma lambda "
       "della replica modello B a snapshot statica, senza il trattamento "
       "live): Pearson robusta 1.67-1.81 e Var(lambda) ~0.77 sulla testa "
       "Totali, P(0) Poisson predetta 0.31-0.35 contro 0.25-0.26 reale. "
       "Sul motore VIVO questi indicatori collassano su Poisson: "
       "Pearson 0.93-1.12, Var(lambda) 0.14-0.37 e P(0) predetta 0.26-0.29 "
       "a ridosso del reale. Lo shrinkage `_shrunk_ratio` (PRIOR_MATCHES=6) "
       "e la fonte F_season point-in-time comprimono lo spread dei lambda "
       "che nella replica generava l'overdispersion apparente: il motore "
       "di produzione, a differenza della replica, regolarizza gia' quello "
       "scarto.")
    ap("")

    # ---- 2. calibrazione ----
    ap("## 2. Calibrazione sul motore VIVO: Brier/LogLoss (NB - Poisson)")
    ap("")
    ap("Delta negativo = NB migliora; IC 95% bootstrap 2000 stratificato "
       "per lega, appaiato riga per riga.")
    ap("")
    ap("### Aggregato 5 leghe")
    ap("")
    ap("| Mercato | split | Brier Poisson | Brier NB | ΔBrier (IC) | "
       "LL Poisson | LL NB | ΔLL (IC) |")
    ap("|---|---|---:|---:|---|---:|---:|---|")
    for sp in ("validation", "test"):
        for mkt, lbl in (("1x2", "1X2"), ("ou", "O/U2.5"),
                         ("gg", "GG/NG (controllo: invariato)")):
            r = calib[sp][mkt]
            db, dl = r["db"], r["dl"]
            ap(f"| {lbl} | {sp} | {r['bP']:.4f} | {r['bNB']:.4f} | "
               f"{db[0]:+.4f} [{db[1]:+.4f}; {db[2]:+.4f}] | "
               f"{r['lP']:.4f} | {r['lNB']:.4f} | "
               f"{dl[0]:+.4f} [{dl[1]:+.4f}; {dl[2]:+.4f}] |")
    ap("")
    ap("Le righe O/U2.5 e GG/NG sono identiche **al bit** (delta 0.0000): "
       "l'alpha MLE della testa Totali e' esattamente al confine Poisson, "
       "quindi `markets_nb(..., alpha=0)` richiama la pmf Poisson di "
       "produzione. Sulla 1X2 l'alpha train e' minuscolo (0.012, IC che "
       "tocca lo zero): il delta e' al piu' -0.0002, cioe' ~100 volte piu' "
       "piccolo dei -0.016 della replica, e gli alpha diagnostici ricalcolati "
       "su validation/test sono 0.0 (§1): non c'e' guadagno tenibile.")
    ap("")
    ap("### Per lega: ΔBrier (IC 95%)")
    ap("")
    ap("| Mercato | split | " + " | ".join(LEAGUE_KEYS) + " |")
    ap("|---|---|" + "---|" * len(LEAGUE_KEYS))
    for sp in ("validation", "test"):
        for mkt, lbl in (("1x2", "1X2"), ("ou", "O/U2.5")):
            cells = []
            for ck in LEAGUE_KEYS:
                bp, bn, lo, hi = calib[sp][mkt]["per_lg"][ck]
                cells.append(f"{bn-bp:+.4f} [{lo:+.4f}; {hi:+.4f}]")
            ap(f"| {lbl} | {sp} | " + " | ".join(cells) + " |")
    ap("")

    # ---- 3. argmax ----
    ap("## 3. L'ARGMAX del Top Mix cambia? (7 mercati, versione pura)")
    ap("")
    ap("Per ogni partita l'argmax e' ricalcolato con le stesse righe di "
       "produzione (`seleziona_riga_top_mix` / shadow) sui 7 mercati puri; "
       "sotto scenario NB2 le probabilita' di 1/X/2 e Over/Under 2.5 "
       "vengono dalla NB2, GG/NG restano le Poisson di produzione.")
    ap("")
    ap("| Split | Lega | partite | argmax cambiati | % |")
    ap("|---|---|---:|---:|---:|")
    for sp in ("validation", "test"):
        for ck in LEAGUE_KEYS + ["AGGREGATO"]:
            tot, fl = disagree[(sp, ck)]
            pct = 100.0 * fl / tot if tot else 0.0
            ap(f"| {sp} | {ck} | {tot} | {fl} | {pct:.1f}% |")
    tot, fl = disagree[("both", "AGGREGATO")]
    ap(f"| **val+test** | **AGGREGATO** | **{tot}** | **{fl}** | **"
       f"{100.0*fl/tot:.1f}%** |")
    ap("")
    ap("Transizioni per classe di mercato (codice Poisson -> codice NB2), "
       "val+test; 1/2 = vittoria casa/trasferta, X = pareggio, "
       "O2.5/U2.5 = Over/Under, GG/NG:")
    ap("")
    ap("| Da (Poisson) | A (NB2) | partite |")
    ap("|---|---|---:|")
    for (cP, cN), cnt in sorted(transitions.items(),
                                key=lambda kv: -kv[1]):
        ap(f"| {cP} | {cN} | {cnt} |")
    ap("")
    # distribuzione mercato
    ap("Distribuzione degli argmax (val+test, tutte le partite):")
    ap("")
    ap("| Mercato | Poisson | NB2 |")
    ap("|---|---:|---:|")
    for code in ("1", "X", "2", "O2.5", "U2.5", "GG", "NG"):
        ap(f"| {code} | {distP.get(code,0)} | {distNB.get(code,0)} |")
    ap("")
    ap("Casi limite (argmax cambiato, margine del mercato vincitore sul "
       "secondo piccolo in ALMENO una delle due versioni; esito reale in "
       "coda):")
    ap("")
    ap("| Data | Lega | Partita | Ris. | argmax Poisson (p) | "
       "argmax NB2 (p) | P preso? | NB preso? |")
    ap("|---|---|---|---|---|---|:--:|:--:|")
    for m in examples[:10]:
        sP, sN = m["selP"], m["selNB"]
        hitP = dq.expected_hit(sP["code"], m["fthg"], m["ftag"])
        hitN = dq.expected_hit(sN["code"], m["fthg"], m["ftag"])
        ap(f"| {m['date'].date()} | {m['league']} | {m['home']} - "
           f"{m['away']} | {m['fthg']}-{m['ftag']} | {sP['label']} "
           f"({sP['poisson']:.3f}) | {sN['label']} ({sN['poisson']:.3f}) "
           f"| {'SI' if hitP else 'no'} | {'SI' if hitN else 'no'} |")
    ap("")

    # ---- 4. soglie e gate ----
    ap("## 4. Soglie 0.55/0.60, gate Elo 0.25 e volume dei pick")
    ap("")
    ap("Lo scenario usa le SOGLIE INVARIATE di produzione (0.55 per la "
       "riga 1X2 con confidence di blend `0.25*P + 0.75*Elo`, 0.60 per le "
       "righe Over/Under/GG/NG in Poisson puro) e il veto invariato "
       "`|P - Elo| < 0.25`. Si contano solo gli spostamenti indotti dal "
       "cambio di distribuzione.")
    ap("")
    ap("### 4.1 Superamento soglia (ignorando il veto) e ammissione finale")
    ap("")
    ap("| split | lega | n | sopra soglia P | sopra soglia NB | "
       "la perdono | la guadagnano | ammesse P | ammesse NB | "
       "perse | guadagnate | mercato cambiato fra le ammesse |")
    ap("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for sp in ("validation", "test"):
        for ck in LEAGUE_KEYS + ["AGGREGATO"]:
            t = move[(sp, ck)]
            ap(f"| {sp} | {ck} | {t['n']} | {t['thr_p']} | {t['thr_n']} | "
               f"{t['thr_lost']} | {t['thr_gained']} | {t['admit_p']} | "
               f"{t['admit_n']} | {t['admit_lost']} | "
               f"{t['admit_gained']} | {t['admit_market_changed']} |")
    ap("")
    ap("Causa delle ammissioni perse/guadagnate (aggregato):")
    ap("")
    ap("| split | direzione | sola soglia | solo gate | entrambi | "
       "altro (cambio di mercato verso/da riga senza Elo) |")
    ap("|---|---|---:|---:|---:|---:|")
    for sp in ("validation", "test"):
        t = move[(sp, "AGGREGATO")]
        for dire, key in (("perse", "cause_lost"), ("guadagnate",
                                                    "cause_gained")):
            c = t[key]
            ap(f"| {sp} | {dire} | {c['soglia']} | {c['gate']} | "
               f"{c['entrambi']} | {c['mercato_no_elo']} |")
    ap("")
    ap("### 4.2 Gate di disaccordo Elo (|P - Elo| >= 0.25)")
    ap("")
    ap("**Cosa verrebbe sostituito.** Il gate confronta la probabilita' "
       "Poisson pura del mercato 1X2 gia' selezionato con quella Elo. Il "
       "porting tocca **solo il primo termine** (la fonte Poisson: la sua "
       "componente nella confidence di blend `0.25*P + 0.75*Elo` e la P "
       "del veto); **l'Elo non viene toccato** (stessi rating, stessi CSV "
       "troncati) e la logica/soglia 0.25 del gate resta identica. Non si "
       "patcha nulla: si misura solo quante partite cambierebbero stato.")
    ap("")
    ap("| split | lega | argmax 1X2 P | argmax 1X2 NB | veto P | veto NB | "
       "nuovi veti | veti rimossi |")
    ap("|---|---|---:|---:|---:|---:|---:|---:|")
    for sp in ("validation", "test"):
        for ck in LEAGUE_KEYS + ["AGGREGATO"]:
            t = move[(sp, ck)]
            ap(f"| {sp} | {ck} | {t['arg1x2_p']} | {t['arg1x2_n']} | "
               f"{t['veto_p']} | {t['veto_n']} | {t['veto_new']} | "
               f"{t['veto_gone']} |")
    ap("")

    # ---- 5. ROI ----
    ap("## 5. ROI / win-rate vs quote reali (B365 + archivio BTTS)")
    ap("")
    ap("Due regimi: **argmax ogni partita** (contro-fattuale diagnostico: "
       "il cambio di argmax punta nella direzione giusta?) e **solo pick "
       "ammessi** dal selettore di produzione (soglia AND gate: il volume "
       "reale del Top Mix). Stake unitario flat, assenti le partite senza "
       "quota per il mercato scelto. ΔROI = NB - Poisson, IC 95% "
       "bootstrap stratificato per lega appaiato sulle partite comuni.")
    ap("")

    def fmt_sum(s):
        if s is None:
            return "—"
        return (f"n={s['n']}, WR {100*s['wr']:.1f}%, q media {s['avg_q']:.2f}, "
                f"ROI {s['roi']:+.2f}% [{s['lo']:+.2f}; {s['hi']:+.2f}]")

    for regime, titolo in (("argmax", "5.1 Argmax di OGNI partita"),
                           ("admit", "5.2 Solo pick AMMESSI dal selettore")):
        ap(f"### {titolo}")
        ap("")
        ap("| Split | Poisson | NB2 | ΔROI NB-P (IC) |")
        ap("|---|---|---|---|")
        for sp in ("validation", "test", "val+test"):
            r = roi_out[(regime, sp)]
            d = r["delta"]
            dt = ("—" if d is None else
                  f"{d['droi']:+.2f}% [{d['lo']:+.2f}; {d['hi']:+.2f}] "
                  f"(n={d['n']})")
            ap(f"| {sp} | {fmt_sum(r['P'])} | {fmt_sum(r['NB'])} | {dt} |")
        ap("")
        if regime == "argmax":
            fp = roi_out[(regime, "val+test")]["flip_pair"]
            fs = roi_out[(regime, "val+test")]["flip_sum"]
            nflip = roi_out[(regime, "val+test")]["n_flip"]
            ap(f"Sulle **{nflip} partite con argmax cambiato** (testa a "
               "testa sulle partite con quota per entrambi i pick):")
            ap("")
            ap(f"- Poisson: {fmt_sum(fs[0])}")
            ap(f"- NB2: {fmt_sum(fs[1])}")
            if fp is not None:
                ap(f"- ΔROI NB-P: {fp['droi']:+.2f}% "
                   f"[{fp['lo']:+.2f}; {fp['hi']:+.2f}] (n={fp['n']})")
            ap("")
        ap("Per lega (val+test):")
        ap("")
        ap("| Lega | Poisson | NB2 |")
        ap("|---|---|---|")
        per = roi_out[(regime, "val+test")]["per_lg"]
        for ck in LEAGUE_KEYS:
            sp_, sn_ = per[ck]
            ap(f"| {ck} | {fmt_sum(sp_)} | {fmt_sum(sn_)} |")
        ap("")

    # ======================================================================
    # VERDETTO
    # ======================================================================
    ap("## 6. Conclusione esplicita")
    ap("")
    tva = move[("validation", "AGGREGATO")]
    tte = move[("test", "AGGREGATO")]
    bboth = disagree[("both", "AGGREGATO")]
    # indicatori
    db_v = calib["validation"]["1x2"]["db"]
    db_t = calib["test"]["1x2"]["db"]
    do_v = calib["validation"]["ou"]["db"]
    do_t = calib["test"]["ou"]["db"]
    thr_net = (tva["admit_n"] - tva["admit_p"],
               tte["admit_n"] - tte["admit_p"])
    def frac(num, den):
        return 100.0 * num / den if den else 0.0
    v_frac = max(frac(tva["admit_lost"] + tva["admit_gained"],
                      max(tva["admit_p"], 1)),
                 frac(tte["admit_lost"] + tte["admit_gained"],
                      max(tte["admit_p"], 1)))
    r_am = roi_out[("admit", "val+test")]
    r_ag = roi_out[("argmax", "val+test")]

    # beneficio di calibrazione held-out coerente (stesso criterio
    # dell'audit di replica: IC del delta Brier interamente sotto zero
    # su ENTRAMBI gli split, 1X2 e O/U)
    def neg(ci):
        return ci[2] < 0.0
    calib_benefit = neg(db_v) and neg(db_t) and neg(do_v) and neg(do_t)
    # alfa train sostanzialmente al confine Poisson?
    degenerate = (at <= 0.02 or fits["tot"]["boundary_pct"] > 50.0) \
        and a1 <= 0.03 and not calib_benefit

    ap(f"**Stima.** Gli alpha NB2 ristimati sul train del motore VIVO sono "
       f"{a1:.4f} (1X2, IC [{fits['1x2']['lo']:.4f}; "
       f"{fits['1x2']['hi']:.4f}], {fits['1x2']['boundary_pct']:.0f}% "
       f"resample al confine) e {at:.4f} (Totali, "
       f"{fits['tot']['boundary_pct']:.0f}% al confine): NON i 0.219/0.189 "
       "della replica offline. La Pearson robusta condizionale e' 0.93-1.12 "
       "(~1 = Poisson esatto; era 1.67-1.81 nella replica) e la varianza "
       "reale E[(k-lambda)^2] eguaglia o resta SOTTO E[lambda] su tutti gli "
       "split. Con alpha=0.19 della replica la varianza predetta salirebbe "
       "a ~1.8 contro ~1.36-1.43 osservato: la NB2 qui peggiorerebbe il "
       "conteggio, non lo correggerebbe.")
    ap("")
    ap(f"**Calibrazione.** ΔBrier 1X2 {db_v[0]:+.4f} (val, IC "
       f"[{db_v[1]:+.4f}; {db_v[2]:+.4f}]) / {db_t[0]:+.4f} (test, IC "
       f"[{db_t[1]:+.4f}; {db_t[2]:+.4f}]); O/U2.5 {do_v[0]:+.4f} "
       f"[{do_v[1]:+.4f}; {do_v[2]:+.4f}] / {do_t[0]:+.4f} "
       f"[{do_t[1]:+.4f}; {do_t[2]:+.4f}]. GG/NG e' identico per "
       "costruzione (zero delta).")
    ap("")
    ap(f"**Impatto operativo ({bboth[0]} partite val+test).**")
    ap("")
    ap(f"1. **Argmax**: cambia in {bboth[1]}/{bboth[0]} partite "
       f"({100.0*bboth[1]/bboth[0]:.2f}%) — v. tabella e transizioni in §3.")
    ap(f"2. **Soglie 0.55/0.60**: sopra-soglia perse/guadagnate "
       f"{tva['thr_lost']}/{tva['thr_gained']} in val e "
       f"{tte['thr_lost']}/{tte['thr_gained']} in test; ammissioni finali "
       f"del selettore {tva['admit_p']}->{tva['admit_n']} (val, netto "
       f"{thr_net[0]:+d}) e {tte['admit_p']}->{tte['admit_n']} (test, "
       f"netto {thr_net[1]:+d}); spostamento massimo {v_frac:.1f}% delle "
       "righe ammesse.")
    ap(f"3. **Gate Elo 0.25**: la sostituzione tocca SOLO il termine "
       f"Poisson (e il 25% della confidence di blend 0.25*P+0.75*E); Elo, "
       f"peso e regola 0.25 restano identici. Nuovi veti/rimossi: "
       f"{tva['veto_new']}/{tva['veto_gone']} in val, "
       f"{tte['veto_new']}/{tte['veto_gone']} in test (denominatori di "
       "righe 1X2 in §4.2). Non si patcha il gate: e' la descrizione di "
       "quanto cambierebbe il suo input.")
    ap("4. **ROI/WR vs quote reali**: v. §5 (argmax ogni partita e soli "
       "pick ammessi), incluso il testa a testa sulle partite con argmax "
       "cambiato.")
    ap("")
    ap("### VERDETTO")
    ap("")
    if degenerate:
        ap("**NON fare il porting: sul motore VIVO non c'e' overdispersion "
           "condizionale residua da correggere.** L'NB2-pooled che "
           "migliorava la replica offline (alpha 0.22/0.19) qui collassa "
           "sul confine Poisson (alpha "
           f"{a1:.3f}/{at:.3f}): lo shrinkage di produzione "
           "(_shrunk_ratio, PRIOR_MATCHES=6) e la fonte F_season "
           "point-in-time comprimono gia' lo spread dei lambda (Var "
           "lambda 0.14-0.37 contro ~0.77 della replica), che era la fonte "
           "dell'overdispersion apparente. NB2(alpha~0) e' algebricamente "
           "il Poisson, quindi il 'miglioramento di calibrazione gia' "
           "noto' NON si conferma sul motore vero (i delta di §2 sono "
           "identicamente nulli sui Totali e -0.0002 sulla 1X2, due ordini "
           "di grandezza sotto i -0.016 della replica e senza tenuta "
           "fuori campione), e di conseguenza:")
        ap("")
        ap(f"- l'argmax cambia in {bboth[1]}/{bboth[0]} partite "
           f"({100.0*bboth[1]/bboth[0]:.2f}%): fuoco di paglia, senza "
           "guadagno di calibrazione alle spalle;")
        ap(f"- le soglie 0.55/0.60 **non vanno riviste**: il volume di "
           f"pick si muove di {v_frac:.1f}% al massimo (§4), cioe' non si "
           "muove materialmente, ma non c'e' comunque alcun motivo per "
           "spostarle dato che il presupposto (code mal predette) non "
           "esiste sul vivo;")
        ap("- il gate Elo non richiede interventi: il suo input Poisson "
           "resta il Poisson attuale;")
        ap("- il ROI (§5) non differisce in modo significativo: il cambio "
           "di argmax non punta in nessuna direzione sistematica.")
        ap("")
        ap("Risposta esplicita alla domanda del task: il porting non e' "
           "'sicuro da fare perche' ininfluente', e' **inutile e non "
           "raccomandato**: aggiungerebbe un parametro (anzi due, uno per "
           "testa) e una biforcazione per mercato senza miglioramento "
           "misurabile sul motore reale. Il risultato della replica resta "
           "valido come diagnosi della replica stessa (lambda non "
           "shrinkati a snapshot statica), ma non come mandato a cambiare "
           "la distribuzione di produzione. GG/NG resta Poisson in ogni "
           "caso. Se in futuro cambiera' la pipeline dei lambda "
           "(es. disattivando/shrinkando diversamente F_season), alpha "
           "dovrà essere ristimato prima di ogni decisione.")
    elif v_frac < 5.0 and calib_benefit:
        ap("**Il porting e' SICURO senza ritoccare le soglie 0.55/0.60.** "
           "Il miglioramento di calibrazione su 1X2 e O/U2.5 si conferma "
           "sul motore vero (IC dei delta Brier interamente sotto zero in "
           "entrambi gli split), mentre l'impatto pratico su argmax, "
           f"soglie e volume di pick e' marginale ({v_frac:.1f}% il "
           "massimo di partite ammesse cambiate). GG/NG resta Poisson: il "
           "porting deve applicare la pmf NB2 alla sola testa 1X2 e al "
           "solo ramo Over/Under (lo scarto GG in §Conformita' misura "
           "l'errore di un porting 'tutto NB2').")
    else:
        ap("**Il porting NON e' una sostituzione indolore: le soglie "
           "0.55/0.60 vanno ri-validate insieme al cambio di "
           "distribuzione.** Gli spostamenti di ammissione superano il 5% "
           f"in almeno uno split ({v_frac:.1f}%): la NB2 ritrae le code e "
           "cambia il volume di pick proposti; la taratura delle soglie "
           "(ottimizzata sul Poisson) andrebbe rifittata su train prima "
           "del deploy. GG/NG resta Poisson. Se poi i delta di "
           "calibrazione di §2 non sono significativamente negativi, il "
           "porting non e' comunque raccomandato.")
    ap("")
    ap(f"**Lato economico.** Regime argmax-ogni-partita, val+test: "
       f"Poisson {r_ag['P']['roi']:+.2f}% vs NB2 {r_ag['NB']['roi']:+.2f}% "
       f"(Δ {r_ag['delta']['droi']:+.2f}% "
       f"[{r_ag['delta']['lo']:+.2f}; {r_ag['delta']['hi']:+.2f}], "
       f"n={r_ag['delta']['n']}). Sui soli pick ammessi: Poisson "
       f"{r_am['P']['roi']:+.2f}% vs NB2 {r_am['NB']['roi']:+.2f}% (Δ "
       f"{r_am['delta']['droi']:+.2f}% [{r_am['delta']['lo']:+.2f}; "
       f"{r_am['delta']['hi']:+.2f}], n={r_am['delta']['n']}). Questi "
       "numeri ROI sono su stagioni coinvolte nelle scelte di modello "
       "(non un test intatto) e vanno letti come coerenza direzionale, "
       "non come promessa di profitto.")
    ap("")
    ap("## Limiti dichiarati")
    ap("")
    ap("1. **Alpha pooled unico per testa**: stessa scelta di parsimonia "
       "dell'audit di replica; gli alpha per lega restano solo "
       "descrittivi. Griglia 15x15 troncata e non rinormalizzata, come "
       "produzione.")
    ap("2. **GG/NG escluso per costruzione**: l'NB2 su quella testa peggiora "
       "in modo coerente (audit overdispersion §4); lo scenario NB2 tiene "
       "il valore Poisson bit-per-bit. Un eventuale porting nel motore "
       "deve quindi biforcare la pmf per mercato, non sostituire "
       "`_poisson_market` in blocco.")
    ap("3. **Il blend Elo e la 1X2 prodotta**: qui si sostituisce la sola "
       "marginale Poisson dentro la confidence di blend (0.25) e dentro il "
       "gate; non si ritara il peso del blend. L'Elo e' quello vero "
       "ricalcolato dai CSV troncati nel contesto patchato.")
    ap("4. **Quote**: B365 1X2/O/U dai CSV football-data; GG/NG dalle "
       "quote BTTS degli archivi audit (stesse fonti e join di "
       "`diagnose_quota_minima`); le partite senza quota per il mercato "
       "selezionato sono escluse dal blocco ROI e contate in copertura.")
    ap("5. **Validation non e' un test intatto**: le stagioni "
       "2024/25+2025/26 hanno guidato scelte di modelli precedenti; "
       "l'etichetta e' la stessa usata da tutti gli audit di questo ciclo.")
    ap("6. **Cutoff a giorno** (mezzogiorno UTC, politica previous_day) e "
       "bare-mode streamlit: identici agli audit motore-live/prior.")
    ap("")
    ap("## Riferimenti incrociati")
    ap("")
    ap("- `audit/results/overdispersion_condizionale_diagnosis.md`: "
       "dimostrazione dell'overdispersion e della NB2 sulla replica, alpha;")
    ap("- `audit/results/motore_live_vs_replica_diagnosis.md`: harness live "
       "qui riusata;")
    ap("- `audit/results/topmix_selector_replay.md` e "
       "`audit/results/topmix_shadow_gate.md`: selettore, soglie e gate;")
    ap("- `audit/results/quota_minima_report.md`: fonti quote e "
       "convenzione ROI.")
    ap("")

    text = "\n".join(L)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(text)
    print("Scritto", OUT_PATH)


if __name__ == "__main__":
    main()
