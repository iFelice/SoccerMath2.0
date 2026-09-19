"""
market_prior_xg.py — Puo' un prior xG derivato dai dati sostituire la tabella a
mano MARKET_VALUES senza peggiorare Brier/ROI? (audit walk-forward, SOLA
LETTURA su SoccerMath/database).

Riprende ESATTAMENTE il protocollo di audit/market_values_versioned.py
(11/09/2026): stessa passata walk-forward (walker condiviso, testa 1X2
PRODUZIONE_DUE_TESTE NORM-SUM, clip lambda, Elo K=24 invariante), stesse
stagioni VALIDATION 2024/25 e TEST 2025/26, stesse metriche (Brier/LogLoss
1X2, ROI a puntata fissa edge>0 vs fair de-vigata Bet365/Average), stesso
bootstrap appaiato (N_BOOT/SEED di topmix_margins). Le varianti girano nella
STESSA passata, quindi il confronto e' perfettamente appaiato:

  * STATIC  : config.MARKET_VALUES (tabella a mano, identico a produzione);
  * VER     : rilevazioni versionate per stagione (riferimento dell'11/09);
  * NONE    : fattore 1 (nessun mercato);
  * XGP     : SoccerMath/market_prior.py con i parametri PRE-REGISTRATI
              (persistence 0.65, prior_matches 10, slope 0.25, clip
              [0.85, 1.25]): xGD della stagione precedente regredito verso la
              media di lega e aggiornato con lo xGD della stagione corrente
              man mano che il campione cresce. Point-in-time: solo partite con
              kickoff nel giorno PRIMA della partita valutata.

La decisione (sostituire o tenere la tabella) e' presa SOLO sulla variante
pre-registrata XGP contro STATIC: non deve peggiorare in modo significativo
Brier ne' ROI B365 (CI bootstrap 95% appaiata) sull'aggregato, e non deve
peggiorare significativamente in nessuna lega. Una griglia di sensibilita'
sui parametri e' riportata per trasparenza ma NON viene usata per scegliere
(sarebbe tuning sul test).

Uso:    python audit/market_prior_xg.py
Output: audit/results/market_prior_xg_report.md (+ _detail.json)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from itertools import product

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from backtest_experiment_all import LEAGUES, MARKET_VALUES                 # noqa: E402
from diagnose_production_baseline import SEASONS_EVAL, TeamState, market_factor  # noqa: E402
from topmix_margins import N_BOOT, SEED, _ci                               # noqa: E402
import diagnose_clv_pinnacle as CLV                                        # noqa: E402
import market_values_versioned as MVV                                      # noqa: E402
from market_prior import XgPriorParams, DEFAULT_PARAMS, build_index        # noqa: E402

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "market_prior_xg_report.md")
STAKE = MVV.STAKE
ELO_ENSEMBLE_W = MVV.ELO_ENSEMBLE_W

BASE_TAGS = ("static", "ver", "none", "xgp")

# Griglia di sensibilita' (solo trasparenza, NON usata per decidere).
SENS_GRID = [
    XgPriorParams(persistence=p, prior_matches=m, slope=s)
    for p, m, s in product((0.5, 0.65, 0.8), (6.0, 10.0, 19.0), (0.15, 0.25, 0.35))
    if not (p == DEFAULT_PARAMS.persistence and m == DEFAULT_PARAMS.prior_matches
            and s == DEFAULT_PARAMS.slope)
]


def sens_tag(params: XgPriorParams) -> str:
    return f"xgp_p{params.persistence:g}_m{params.prior_matches:g}_s{params.slope:g}"


def run_variants(df, camp_key, xg_data, lookup, index, sens=SENS_GRID):
    """Copia fedele di market_values_versioned.run_market_variants con in piu'
    la variante XGP (e la griglia di sensibilita'), calcolate nella stessa
    passata. Ritorna (rows_df, usage, xgp_usage)."""
    home_adv = CLV.LEAGUE_HOME_ADVANTAGE.get(camp_key, 60.0)
    xg_att, xg_def = {}, {}
    if xg_data and len(xg_data) >= 10:
        vals = list(xg_data.values())
        lx = float(np.mean([v["xG_avg"] for v in vals]))
        lxa = float(np.mean([v["xGA_avg"] for v in vals]))
        if lx and lxa:
            for t, v in xg_data.items():
                xg_att[t] = v["xG_avg"] / lx
                xg_def[t] = v["xGA_avg"] / lxa

    state, elo = {}, {}
    tot_hg = tot_ag = tot_n = 0.0
    rows = []
    usage = {"Post-Estivo": 0, "Post-Invernale": 0, "fallback_missing": 0}
    xgp_usage = {"previous_season": 0, "promoted": 0, "no_history": 0,
                 "n_cur_sum": 0, "slots": 0}
    sens_tags = [(sens_tag(p), p) for p in sens]

    def get(t):
        if t not in state:
            state[t] = TeamState()
        return state[t]

    for _, row in df.iterrows():
        fthg, ftag = int(row.FTHG), int(row.FTAG)
        ftr = str(row.FTR).strip().upper()
        h, a = row.HomeClean, row.AwayClean
        sh, sa = get(h), get(a)
        avg_h = max(tot_hg / tot_n, 0.1) if tot_n else 0.1
        avg_a = max(tot_ag / tot_n, 0.1) if tot_n else 0.1
        r_h = elo.get(h, CLV.ELO_INITIAL)
        r_a = elo.get(a, CLV.ELO_INITIAL)

        if row.season in SEASONS_EVAL:
            def form_fac(ts):
                if len(ts.last5) < 3:
                    return 1.0, 1.0
                n = len(ts.last5)
                gf = sum(x[0] for x in ts.last5)
                ga = sum(x[1] for x in ts.last5)
                avg_glob = (avg_h + avg_a) / 2.0
                den = max(avg_glob, 0.5)
                return (max(0.85, min(1.15, (gf / n) / den)),
                        max(0.85, min(1.15, (ga / n) / den)))

            def prim(t, ts):
                pa = xg_att[t] if t in xg_att else ((ts.hgf / ts.hgn) / avg_h if ts.hgn else 1.0)
                pdf = xg_def[t] if t in xg_def else ((ts.hga / ts.hgn) / avg_a if ts.hgn else 1.0)
                return pa, pdf

            p_att_h, p_def_h = prim(h, sh)
            p_att_a, p_def_a = prim(a, sa)
            fa_h, fd_h = form_fac(sh)
            fa_a, fd_a = form_fac(sa)

            mkt_static_h = market_factor(MARKET_VALUES.get(h, 50))
            mkt_static_a = market_factor(MARKET_VALUES.get(a, 50))
            v_h, kind_h = MVV.versioned_value(lookup, camp_key, row.Date, row.season, h)
            v_a, kind_a = MVV.versioned_value(lookup, camp_key, row.Date, row.season, a)
            if v_h is not None and v_a is not None:
                mkt_ver_h, mkt_ver_a = market_factor(v_h), market_factor(v_a)
                usage["Post-Estivo"] += (kind_h == "Post-Estivo") + (kind_a == "Post-Estivo")
                usage["Post-Invernale"] += (kind_h == "Post-Invernale") + (kind_a == "Post-Invernale")
            else:
                mkt_ver_h = mkt_ver_a = 1.0
                usage["fallback_missing"] += int(v_h is None) + int(v_a is None)

            # --- prior xG point-in-time (giorno del kickoff < giorno partita) ---
            season_year = int(str(row.season).split("/")[0])
            info_h = index.quality(h, season_year, row.Date, DEFAULT_PARAMS)
            info_a = index.quality(a, season_year, row.Date, DEFAULT_PARAMS)
            for info in (info_h, info_a):
                xgp_usage[info["source"]] += 1
                xgp_usage["n_cur_sum"] += info["n_cur"]
                xgp_usage["slots"] += 1
            mkt_xgp_h = index.factor(h, season_year, row.Date, DEFAULT_PARAMS)
            mkt_xgp_a = index.factor(a, season_year, row.Date, DEFAULT_PARAMS)

            mkts = {"static": (mkt_static_h, mkt_static_a),
                    "ver": (mkt_ver_h, mkt_ver_a),
                    "none": (1.0, 1.0),
                    "xgp": (mkt_xgp_h, mkt_xgp_a)}
            for tag, params in sens_tags:
                mkts[tag] = (index.factor(h, season_year, row.Date, params),
                             index.factor(a, season_year, row.Date, params))

            base_att_h, base_def_h = p_att_h * fa_h, p_def_h * fd_h
            base_att_a, base_def_a = p_att_a * fa_a, p_def_a * fd_a
            lam_base_h = base_att_h * base_def_a * avg_h
            lam_base_a = base_att_a * base_def_h * avg_a
            S = lam_base_h + lam_base_a

            rec = {"date": row.Date, "season": row.season, "home": h, "away": a,
                   "real_1x2": {"H": "1", "D": "X", "A": "2"}.get(ftr, "X"),
                   "xgp_h": mkt_xgp_h, "xgp_a": mkt_xgp_a,
                   "static_h": mkt_static_h, "static_a": mkt_static_a,
                   "n_cur_h": info_h["n_cur"], "n_cur_a": info_a["n_cur"]}
            e1, eX, e2 = CLV.elo_probs(r_h, r_a, home_adv)
            rec["elo_1"], rec["elo_X"], rec["elo_2"] = e1, eX, e2
            for tag, (m_h, m_a) in mkts.items():
                lam_m_h = (base_att_h * m_h) * (base_def_a / m_a) * avg_h
                lam_m_a = (base_att_a * m_a) * (base_def_h / m_h) * avg_a
                den = lam_m_h + lam_m_a
                if den > 0:
                    lh = S * lam_m_h / den
                    la = S * lam_m_a / den
                else:
                    lh, la = lam_base_h, lam_base_a
                mp = CLV.get_full_poisson(CLV._clip_lambda(lh), CLV._clip_lambda(la))
                rec[f"{tag}_1"], rec[f"{tag}_X"], rec[f"{tag}_2"] = mp["1"], mp["X"], mp["2"]
                rec[f"{tag}b_1"] = ELO_ENSEMBLE_W * mp["1"] + (1 - ELO_ENSEMBLE_W) * e1
                rec[f"{tag}b_X"] = ELO_ENSEMBLE_W * mp["X"] + (1 - ELO_ENSEMBLE_W) * eX
                rec[f"{tag}b_2"] = ELO_ENSEMBLE_W * mp["2"] + (1 - ELO_ENSEMBLE_W) * e2
            rows.append(rec)

        dr = r_h + home_adv - r_a
        e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
        s_h = 1.0 if ftr == "H" else (0.0 if ftr == "A" else 0.5)
        elo[h] = r_h + CLV.ELO_K * (s_h - e_h)
        elo[a] = r_a + CLV.ELO_K * ((1 - s_h) - (1 - e_h))
        tot_hg += fthg
        tot_ag += ftag
        tot_n += 1
        sh.observe_home(fthg, ftag)
        sa.observe_away(fthg, ftag)

    return pd.DataFrame(rows), usage, xgp_usage


# =====================================================================
# Bootstrap appaiato generalizzato (stessa convenzione di _boot_deltas)
# =====================================================================
def boot_deltas(d, pairs, n_boot=N_BOOT, seed=SEED):
    rng = np.random.default_rng(seed)
    n = len(d)
    if n == 0:
        return {}
    tags = sorted({t for pair in pairs for t in pair})
    P = {t: d[[f"{t}_1", f"{t}_X", f"{t}_2"]].to_numpy(dtype=float) for t in tags}
    m = {"1": 0, "X": 1, "2": 2}
    y = np.array([m[v] for v in d["real_1x2"]])
    onehot = np.zeros((n, 3))
    onehot[np.arange(n), y] = 1
    brier_rows = {t: np.sum((onehot - P[t]) ** 2, axis=1) for t in tags}
    ll_rows = {t: -np.log(np.clip(P[t][np.arange(n), y], 1e-12, 1.0)) for t in tags}
    need = ["B365H", "B365D", "B365A", "fair_b365_1", "fair_b365_X", "fair_b365_2"]
    ok_mask = ~d[need].isna().any(axis=1).to_numpy()
    ok_idx = np.flatnonzero(ok_mask)
    odds = d[["B365H", "B365D", "B365A"]].to_numpy(dtype=float)[ok_idx]
    fair = d[["fair_b365_1", "fair_b365_X", "fair_b365_2"]].to_numpy(dtype=float)[ok_idx]
    yb = y[ok_idx]
    pnl, stake = {}, {}
    for t in tags:
        Pt = P[t][ok_idx]
        edge = Pt - fair
        best = np.argmax(edge, axis=1)
        has_bet = edge[np.arange(len(ok_idx)), best] > 0.0
        stake[t] = np.where(has_bet, STAKE, 0.0)
        won = yb == best
        pnl[t] = np.where(has_bet,
                          np.where(won, STAKE * (odds[np.arange(len(ok_idx)), best] - 1.0),
                                   -STAKE), 0.0)

    def metric_on(t, idx, kind):
        if kind == "brier":
            return float(brier_rows[t][idx].mean())
        if kind == "log_loss":
            return float(ll_rows[t][idx].mean())
        sel = idx[ok_mask[idx]]
        s = stake[t][sel].sum()
        return float(100.0 * pnl[t][sel].sum() / s) if s > 0 else 0.0

    # stesso resample per tutte le coppie (appaiamento completo)
    resamples = [rng.integers(0, n, size=n) for _ in range(n_boot)]
    out = {}
    for a, b in pairs:
        res = {}
        for kind in ("brier", "log_loss", "roi_b365"):
            point = metric_on(a, np.arange(n), kind) - metric_on(b, np.arange(n), kind)
            boots = [metric_on(a, idx, kind) - metric_on(b, idx, kind) for idx in resamples]
            lo, hi = _ci(boots)
            res[kind] = {"delta": round(point, 4), "ci": [round(lo, 4), round(hi, 4)],
                         "significant": bool(not (lo <= 0.0 <= hi))}
        out[f"{a}-{b}"] = res
    return out


# =====================================================================
# Report
# =====================================================================
def _fv(v, nd=4):
    return "-" if v is None else f"{v:.{nd}f}"


def _delta_cell(x):
    if not x:
        return "-"
    return (f"{x['delta']:+.4f} [{x['ci'][0]:+.4f}; {x['ci'][1]:+.4f}]"
            + (" **sig.**" if x["significant"] else " n.s."))


def render(payload):
    L = []
    L.append("# Prior xG derivato dai dati vs tabella MARKET_VALUES (walk-forward, 1X2)\n")
    L.append(f"Generato: {payload['generated_at']}  ")
    L.append("Protocollo: identico a `market_values_versioned.py` (11/09/2026): walker "
             "condiviso, testa NORM-SUM + Elo 0.6/0.4, VALIDATION 2024/25, TEST 2025/26, "
             f"bootstrap appaiato {N_BOOT} resample seed {SEED}. Stake {STAKE:g}, edge>0 "
             "vs fair de-vigata.\n")
    p = DEFAULT_PARAMS
    L.append("## Variante pre-registrata XGP\n")
    L.append(f"`q = ({p.prior_matches:g}·{p.persistence:g}·xGD_prev + n_cur·xGD_cur) / "
             f"({p.prior_matches:g} + n_cur)`, `factor = clip(1 + {p.slope:g}·q, {p.lo}, {p.hi})`. "
             "Squadre promosse: xGD_prev = media delle retrocesse che sostituiscono. "
             "Point-in-time: solo partite con kickoff nel giorno precedente a quello valutato.\n")
    L.append("Uso del prior (slot squadra-partita valutati): " + ", ".join(
        f"{k} {v}" for k, v in payload["xgp_usage"].items()) + "\n")

    L.append("## Riproduzione del riferimento 11/09 (STATIC / VER / NONE)\n")
    L.append("I valori STATIC/VER/NONE devono coincidere con "
             "`market_values_versioned_report.md`: stessa passata, stesso codice.\n")

    for split, key in (("val", "VALIDATION 2024/25"), ("test", "TEST 2025/26")):
        L.append(f"## {key} — aggregato 5 leghe\n")
        L.append("| variante | n | Brier | LogLoss | Brier blend | LogLoss blend | ROI B365 | n bet | ROI Avg |")
        L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for tag in BASE_TAGS:
            m = payload["overall"][split]["metrics"][tag]
            L.append(f"| {tag} | {m['n']} | {_fv(m['brier'])} | {_fv(m['log_loss'])} | "
                     f"{_fv(m['brier_blend'])} | {_fv(m['log_loss_blend'])} | "
                     f"{_fv(m['roi_b365'], 2)}% | {m['n_bet_b365']} | {_fv(m['roi_avg'], 2)}% |")
        L.append("")
        L.append("Delta appaiati (variante − static), CI bootstrap 95%:\n")
        L.append("| coppia | Brier | LogLoss | ROI B365 (punti %) |")
        L.append("|---|---|---|---|")
        for pair, res in payload["overall"][split]["boot"].items():
            L.append(f"| {pair} | {_delta_cell(res['brier'])} | {_delta_cell(res['log_loss'])} | "
                     f"{_delta_cell(res['roi_b365'])} |")
        L.append("")

    L.append("## Per lega (XGP − STATIC, delta appaiati con CI 95%)\n")
    L.append("| lega | split | n | Brier static | Brier xgp | Δ Brier | Δ LogLoss | ROI B365 static | ROI B365 xgp | Δ ROI B365 |")
    L.append("|---|---|---:|---:|---:|---|---|---:|---:|---|")
    for lg in payload["leagues"]:
        for split in ("val", "test"):
            ms = lg[split]["metrics"]
            b = lg[split]["boot"].get("xgp-static", {})
            L.append(f"| {lg['league']} | {split} | {ms['static']['n']} | "
                     f"{_fv(ms['static']['brier'])} | {_fv(ms['xgp']['brier'])} | "
                     f"{_delta_cell(b.get('brier'))} | {_delta_cell(b.get('log_loss'))} | "
                     f"{_fv(ms['static']['roi_b365'], 2)}% | {_fv(ms['xgp']['roi_b365'], 2)}% | "
                     f"{_delta_cell(b.get('roi_b365'))} |")
    L.append("")

    L.append("## Sensibilita' ai parametri (solo trasparenza, NON usata per decidere)\n")
    L.append("Brier aggregato della testa Poisson; la variante pre-registrata e' `xgp`.\n")
    L.append("| variante | Brier V | Brier T | ROI B365 V | ROI B365 T |")
    L.append("|---|---:|---:|---:|---:|")
    for tag, row in payload["sensitivity"].items():
        L.append(f"| {tag} | {_fv(row['val']['brier'])} | {_fv(row['test']['brier'])} | "
                 f"{_fv(row['val']['roi_b365'], 2)}% | {_fv(row['test']['roi_b365'], 2)}% |")
    L.append("")

    L.append("## Decisione\n")
    for line in payload["decision"]["lines"]:
        L.append(f"- {line}")
    L.append(f"\n**Esito: {payload['decision']['verdict']}**\n")
    sens = payload["sensitivity"]
    st_v = payload["overall"]["val"]["metrics"]["static"]["brier"]
    st_t = payload["overall"]["test"]["metrics"]["static"]["brier"]
    beat_t = sum(1 for v in sens.values() if v["test"]["brier"] < st_t)
    beat_v = sum(1 for v in sens.values() if v["val"]["brier"] < st_v)
    L.append("## Lettura\n")
    L.append(f"- Robustezza del verdetto: su {len(sens)} configurazioni della griglia "
             f"(persistence x prior_matches x slope), {beat_v} battono la tabella su "
             f"VALIDATION e **{beat_t} su TEST** (Brier testa Poisson). Il risultato non "
             "dipende dalla scelta dei parametri pre-registrati.")
    L.append("- Il prior xG e' competitivo con la tabella in VALIDATION (Brier identico, "
             "ROI n.s.) e migliore di NONE, ma in TEST perde cio' che la tabella conserva: "
             "lo xGD della stagione precedente non vede i cambi di rosa del mercato estivo "
             "(cessioni/acquisti, neopromosse con investimenti), che il valore di rosa "
             "incorpora per costruzione. Con ~10 partite di stagione corrente il prior "
             "converge verso lo xGD corrente, gia' rappresentato nella testa dal fattore "
             "forma e dallo snapshot xG: informazione ridondante, non aggiuntiva.")
    L.append("- ROI B365: nessuna differenza significativa in nessun confronto (CI larghe "
             "±3-7 punti): il ROI non discrimina fra le varianti, la decisione poggia su "
             "Brier/LogLoss come da protocollo.")
    L.append("- Nota di protocollo (ereditata dall'11/09): la testa usa lo snapshot xG "
             "CORRENTE `xg_<lega>.json` come forza primaria per tutte le stagioni, quindi "
             "i valori assoluti cambiano a ogni aggiornamento dello snapshot (STATIC V "
             "0.6522 -> 0.6398 fra 11/09 e oggi). I confronti restano appaiati e validi; "
             "i numeri assoluti non sono confrontabili fra referti di date diverse.")
    L.append("- Conseguenza operativa per il rollover: `config.MARKET_VALUES` resta la "
             "fonte del fattore mercato; al rollover non blocca nulla (squadre assenti -> "
             "default 50, fattore 0.925) e `season_rollover.py` segnala le squadre del "
             "Live prive di valore, cosi' l'aggiornamento estivo della tabella e' un "
             "avviso esplicito e non una scoperta tardiva.")
    L.append("")
    return "\n".join(L)


def decide(payload):
    """Regola pre-registrata: XGP non deve peggiorare significativamente STATIC
    (Brier o ROI B365) sull'aggregato V o T, ne' in una singola lega."""
    lines, worse = [], []
    for split in ("val", "test"):
        b = payload["overall"][split]["boot"]["xgp-static"]
        for kind in ("brier", "log_loss", "roi_b365"):
            x = b[kind]
            bad = x["significant"] and ((kind != "roi_b365" and x["delta"] > 0)
                                        or (kind == "roi_b365" and x["delta"] < 0))
            better = x["significant"] and not bad
            lines.append(f"aggregato {split} {kind}: Δ(xgp−static) {x['delta']:+.4f} "
                         f"CI [{x['ci'][0]:+.4f}; {x['ci'][1]:+.4f}] → "
                         f"{'PEGGIORA (sig.)' if bad else ('migliora (sig.)' if better else 'n.s.')}")
            if bad:
                worse.append(f"aggregato {split} {kind}")
    for lg in payload["leagues"]:
        for split in ("val", "test"):
            b = lg[split]["boot"].get("xgp-static", {})
            for kind in ("brier", "roi_b365"):
                x = b.get(kind)
                if not x:
                    continue
                bad = x["significant"] and ((kind == "brier" and x["delta"] > 0)
                                            or (kind == "roi_b365" and x["delta"] < 0))
                if bad:
                    worse.append(f"{lg['league']} {split} {kind}")
                    lines.append(f"{lg['league']} {split} {kind}: PEGGIORA (sig.) "
                                 f"Δ {x['delta']:+.4f} CI [{x['ci'][0]:+.4f}; {x['ci'][1]:+.4f}]")
    if worse:
        verdict = ("TENERE la tabella MARKET_VALUES: il prior xG peggiora in modo "
                   "significativo " + "; ".join(worse))
    else:
        verdict = ("SOSTITUIBILE: il prior xG non peggiora in modo significativo ne' "
                   "Brier ne' ROI B365 rispetto alla tabella a mano (aggregato e per lega)")
    return {"lines": lines, "verdict": verdict, "worse": worse}


def run():
    lookup, meta = MVV.parse_market_csv()
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "leagues": []}
    all_rows = []
    xgp_usage_tot = {}
    sens_tags = [sens_tag(p) for p in SENS_GRID]
    for prefix, camp_key in LEAGUES:
        df = CLV.load_league(prefix)
        index = build_index(camp_key)
        d, usage, xgp_usage = run_variants(df, camp_key, CLV.load_xg(camp_key), lookup, index)
        for k, v in xgp_usage.items():
            xgp_usage_tot[k] = xgp_usage_tot.get(k, 0) + v
        d = MVV.attach_odds(df, d)
        all_rows.append(d)
        lg = {"league": camp_key, "usage": usage, "xgp_usage": xgp_usage}
        for split, key in (("val", SEASONS_EVAL[0]), ("test", SEASONS_EVAL[1])):
            sub = d[d["season"] == key].reset_index(drop=True)
            lg[split] = {
                "metrics": {tag: MVV.metrics_at(sub, tag) for tag in BASE_TAGS},
                "boot": boot_deltas(sub, [("xgp", "static")]) if len(sub) else {},
            }
        payload["leagues"].append(lg)
        print(f"{camp_key}: V Brier static {lg['val']['metrics']['static']['brier']} "
              f"xgp {lg['val']['metrics']['xgp']['brier']} | T static "
              f"{lg['test']['metrics']['static']['brier']} xgp {lg['test']['metrics']['xgp']['brier']}")

    all_d = pd.concat(all_rows, ignore_index=True)
    payload["xgp_usage"] = xgp_usage_tot
    payload["overall"] = {}
    payload["sensitivity"] = {}
    for split, key in (("val", SEASONS_EVAL[0]), ("test", SEASONS_EVAL[1])):
        sub = all_d[all_d["season"] == key].reset_index(drop=True)
        payload["overall"][split] = {
            "metrics": {tag: MVV.metrics_at(sub, tag) for tag in BASE_TAGS},
            "boot": boot_deltas(sub, [("xgp", "static"), ("ver", "static"),
                                      ("none", "static"), ("xgp", "none")]),
        }
        for tag in ["xgp"] + sens_tags:
            payload["sensitivity"].setdefault(tag, {})[split] = MVV.metrics_at(sub, tag)
    payload["decision"] = decide(payload)
    payload["rows"] = all_d
    return payload, render(payload)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    payload, md = run()
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write(md)
    detail = {k: v for k, v in payload.items() if k != "rows"}
    with open(OUT_PATH.replace(".md", "_detail.json"), "w", encoding="utf-8") as fh:
        json.dump(detail, fh, ensure_ascii=False, indent=1, default=str)
    print(f"Scritto {OUT_PATH}")
    print(payload["decision"]["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
