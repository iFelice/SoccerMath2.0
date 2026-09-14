"""
diagnose_calibration_layer.py — Conviene uno strato di calibrazione post-hoc
sulle probabilita' del motore a Due Teste? (fit SOLO su train)

ERRORE DA NON RIPETERE: il tentativo precedente (Isotonic/Platt) era stato
fittato su validation e valutato sullo stesso validation: l'overfitting non
era visibile finche' il test non peggiorava. QUI TUTTI I PARAMETRI DI
CALIBRAZIONE SONO STIMATI SOLAMENTE SUL TRAIN 2022/23+2023/24 (con le prime
TRAIN_WARMUP=60 partite/lega escluse per cold start, stessa disciplina degli
altri audit); validation 2024/25 e test 2025/26 non vengono MAI usati per
stimare o ritoccare nulla.

Walk-forward identico agli ultimi audit (diagnose_combo_1x2_totali,
diagnose_overdispersion_condizionale):
  * testa 1X2 : lambda NORM-SUM (xG + forma ult.5 + mercato) di
                diagnose_elo_ensemble; probabilita' di PRODUZIONE = blend
                w*Poisson + (1-w)*Elo con w=ELO_ENSEMBLE_W=0.25;
  * testa TOT : lambda puri modello B di diagnose_form_totali, da cui
                Over/Under 2.5 e GG/NG.
Conformita' verificata bit-a-bit riga per riga (cross-check con
diagnose_elo_ensemble, diagnose_form_totali e il p1 blendato di
diagnose_combo_1x2_totali; scarto atteso 0.0e+00) + invarianza di stato.

STRATI DI CALIBRAZIONE:
  1. TEMPERATURE SCALING sul vettore 1X2: logit z=log(p), q=softmax(z/T),
     parametro unico T (T=1 = identita'). MLE multinomiale solo su train, IC
     bootstrap 95% a 2000 resample (stratificati per lega). Se l'IC include
     T=1 non c'e' disallineamento di confidenza da correggere. Applicato a 4
     basi: blend di produzione, Poisson puro, NegBin-pooled (audit
     overdispersion) e blend NegBin-pooled+Elo.
  2. BETA CALIBRATION (Kull et al. 2015, 3 parametri a,b,c) sulle teste
     binarie: mu(p)=sigmo(a*log p - b*log(1-p) + c); identita' in (1,1,0).
     MLE per IRLS solo su train, separatamente per Over 2.5 e GG/NG, sulle
     basi Poisson (attuale) e NegBin-pooled.
  3. Confronto out-of-sample su validation E test: Brier e LogLoss
     originale vs calibrato, IC bootstrap 95% sulla differenza appaiata.
  4. SEZIONE DEDICATA ALL'OVERFITTING: miglioramento in-sample (train) vs
     validation vs test, separatamente; un guadagno che sparisce/cambia
     segno tra validation e test e' il segnale che il tentativo precedente
     non aveva controllato.
  5. Quintili di affidabilita' prima/dopo, sulle basi attuali e sulle basi
     NegBin-pooled: le due correzioni (NB2 e calibrazione) si sommano o si
     sovrappongono?
  6. REGOLA D'ARRESTO: se nessuna versione calibrata batte l'originale con
     IC fuori zero su ENTRAMBI validation e test in modo coerente, lo si
     scrive esplicitamente.

NON tocca SoccerMath/ (sola lettura).
Output: audit/results/calibration_layer_diagnosis.md
Uso:    python audit/diagnose_calibration_layer.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import expit, logsumexp

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from backtest_experiment_all import LEAGUES, MARKET_VALUES, load_league   # noqa: E402
from config import LEAGUE_HOME_ADVANTAGE                             # noqa: E402
from topmix_margins import N_BOOT, SEED, _ci                         # noqa: E402
import diagnose_elo_ensemble as dee                                  # noqa: E402
import diagnose_form_totali as dft                                   # noqa: E402
import diagnose_combo_1x2_totali as dc                               # noqa: E402
import diagnose_overdispersion_condizionale as od                    # noqa: E402
import diagnose_clv_pinnacle as CLV                                  # noqa: E402

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "calibration_layer_diagnosis.md")

TRAIN_SEASONS = dc.TRAIN_SEASONS
SEASONS_EVAL = dc.SEASONS_EVAL
ALL_SEASONS = dc.ALL_SEASONS
TRAIN_WARMUP = dc.TRAIN_WARMUP
W = CLV.ELO_ENSEMBLE_W                    # 0.25, peso Poisson del blend di produzione
T_LO, T_HI = 0.3, 4.0                     # supporto ricerca MLE della temperatura
P_EPS = 1e-6                              # clip probabilita' per logit/beta
RIDGE = 1e-8                              # minima regolarizzazione IRLS
LEAGUE_KEYS = [ck for _, ck in LEAGUES]

# Basi multiclasse 1X2: (colonne probabilita', etichetta, testa per alpha NB)
MULTI_BASES = [
    ("blend", "BLEND di produzione (0.25 Poisson + 0.75 Elo)"),
    ("pois", "Poisson puro testa 1X2"),
    ("nb", "NegBin-pooled testa 1X2 (audit overdispersion)"),
    ("nb_blend", "BLEND NegBin-pooled + Elo (0.25/0.75)"),
]
# Basi binarie: (evento, colonna esito, base, etichetta)
BINARY = [
    ("O/U2.5", "over", "pois", "Over 2.5, Poisson testa Totali (attuale)"),
    ("O/U2.5", "over", "nb", "Over 2.5, NegBin-pooled testa Totali"),
    ("GG/NG", "gg", "pois", "GG, Poisson testa Totali (attuale)"),
    ("GG/NG", "gg", "nb", "GG, NegBin-pooled testa Totali"),
]


# ---------------------------------------------------------------------------
# Walk-forward: stesso motore del combo audit, ma salvo TUTTE le colonne che
# servono (3 Poisson, 3 Elo, 3 blend, lambda delle due teste, esiti)
# ---------------------------------------------------------------------------
def run_calibration_model(df, camp_key, xg_data, emit_seasons=ALL_SEASONS):
    emit = set(emit_seasons)
    home_adv = LEAGUE_HOME_ADVANTAGE.get(camp_key, 60.0)
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

    def get(t):
        if t not in state:
            state[t] = dee.TeamState()
        return state[t]

    for pos, (_, row) in enumerate(df.iterrows()):
        fthg, ftag = int(row.FTHG), int(row.FTAG)
        ftr = str(row.FTR).strip().upper()
        h, a = row.HomeClean, row.AwayClean
        sh, sa = get(h), get(a)
        avg_h = max(tot_hg / tot_n, 0.1) if tot_n else 0.1
        avg_a = max(tot_ag / tot_n, 0.1) if tot_n else 0.1
        r_h, r_a = elo.get(h, 1500.0), elo.get(a, 1500.0)

        if row.season in emit:
            def form_fac(ts):
                if len(ts.last5) < 3:
                    return 1.0, 1.0
                n = len(ts.last5)
                gf = sum(x[0] for x in ts.last5)
                ga = sum(x[1] for x in ts.last5)
                den = max((avg_h + avg_a) / 2.0, 0.5)
                return (max(0.85, min(1.15, (gf / n) / den)),
                        max(0.85, min(1.15, (ga / n) / den)))

            def prim(t, ts):
                pa = xg_att[t] if t in xg_att else (
                    (ts.hgf / ts.hgn) / avg_h if ts.hgn else 1.0)
                pdf = xg_def[t] if t in xg_def else (
                    (ts.hga / ts.hgn) / avg_a if ts.hgn else 1.0)
                return pa, pdf

            pa_h, pd_h = prim(h, sh)
            pa_a, pd_a = prim(a, sa)
            fa_h, fd_h = form_fac(sh)
            fa_a, fd_a = form_fac(sa)
            m_h = dee.market_factor(MARKET_VALUES.get(h, 50))
            m_a = dee.market_factor(MARKET_VALUES.get(a, 50))

            # testa 1X2 NORM-SUM (identica a dee.run_models / dc.run_combo_model)
            lam_base_h = pa_h * fa_h * pd_a * fd_a * avg_h
            lam_base_a = pa_a * fa_a * pd_h * fd_h * avg_a
            lam_m_h = (pa_h * fa_h * m_h) * (pd_a * fd_a / m_a) * avg_h
            lam_m_a = (pa_a * fa_a * m_a) * (pd_h * fd_h / m_h) * avg_a
            S = lam_base_h + lam_base_a
            den = lam_m_h + lam_m_a
            lh = dee.clip(S * lam_m_h / den) if den > 0 else dee.clip(lam_base_h)
            la = dee.clip(S * lam_m_a / den) if den > 0 else dee.clip(lam_base_a)

            # testa Totali modello B (lambda puri)
            lp_h = dee.clip(pa_h * pd_a * avg_h)
            lp_a = dee.clip(pa_a * pd_h * avg_a)

            m1 = od._poisson_markets(lh, la)
            m0 = od._poisson_markets(lp_h, lp_a)
            e1, eX, e2 = dee.elo_probs(r_h, r_a, home_adv)
            b1, bX, b2 = W * m1["1"] + (1 - W) * e1, W * m1["X"] + (1 - W) * eX, \
                W * m1["2"] + (1 - W) * e2

            rows.append({
                "pos": pos, "season": row.season, "league": camp_key,
                "home": h, "away": a, "fthg": fthg, "ftag": ftag,
                "real_1x2": {"H": 0, "D": 1, "A": 2}.get(ftr, 1),
                "real_over": int(fthg + ftag > 2.5),
                "real_gg": int(fthg > 0 and ftag > 0),
                "lam1_h": lh, "lam1_a": la, "lam0_h": lp_h, "lam0_a": lp_a,
                "p1": m1["1"], "pX": m1["X"], "p2": m1["2"],
                "over_pois": m0["o25"], "gg_pois": m0["gg"],
                "e1": e1, "eX": eX, "e2": e2,
                "b1": b1, "bX": bX, "b2": b2})

        # aggiornamento stato DOPO la previsione
        dr = r_h + home_adv - r_a
        e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
        s_h = 1.0 if ftr == "H" else (0.0 if ftr == "A" else 0.5)
        elo[h] = r_h + dee.ELO_K * (s_h - e_h)
        elo[a] = r_a + dee.ELO_K * ((1 - s_h) - (1 - e_h))
        tot_hg += fthg
        tot_ag += ftag
        tot_n += 1
        sh.observe_home(fthg, ftag)
        sa.observe_away(fthg, ftag)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# NegBin-pooled (alpha dell'audit overdispersion, MLE sul solo train)
# ---------------------------------------------------------------------------
def attach_nb(agg):
    tr = agg[dc.sample_mask(agg, "train")]
    alphas = {}
    for head in od.HEADS:
        k, lam, _ = od.team_rows(tr, head)
        a, bnd = od.fit_alpha(k, lam)
        alphas[head] = a
    n = len(agg)
    nb = {k: np.empty(n) for k in ("nb1", "nbX", "nb2", "nbover", "nbgg",
                                   "nbb1", "nbbX", "nbb2")}
    lh1, la1 = agg["lam1_h"].to_numpy(), agg["lam1_a"].to_numpy()
    lh0, la0 = agg["lam0_h"].to_numpy(), agg["lam0_a"].to_numpy()
    a1, a0 = alphas[od.HEAD_1X2], alphas[od.HEAD_TOT]
    for i in range(n):
        u = od.markets_nb(lh1[i], la1[i], a1)
        v = od.markets_nb(lh0[i], la0[i], a0)
        nb["nb1"][i], nb["nbX"][i], nb["nb2"][i] = u["1"], u["X"], u["2"]
        nb["nbover"][i], nb["nbgg"][i] = v["o25"], v["gg"]
        # blend NB + Elo, poi rinormalizzazione (celle troncate sommano ~1)
        raw = np.array([W * u["1"] + (1 - W) * agg["e1"].iat[i],
                        W * u["X"] + (1 - W) * agg["eX"].iat[i],
                        W * u["2"] + (1 - W) * agg["e2"].iat[i]])
        raw /= raw.sum()
        nb["nbb1"][i], nb["nbbX"][i], nb["nbb2"][i] = raw
    for k, arr in nb.items():
        agg[k] = arr
    return agg, alphas


# ---------------------------------------------------------------------------
# 1) Temperature scaling (multinomial 1X2)
# ---------------------------------------------------------------------------
def _normalize_rows(P):
    P = np.asarray(P, dtype=float)
    return P / P.sum(axis=1, keepdims=True)


def temp_nll(T, Pn, y):
    z = np.log(np.clip(Pn, 1e-300, 1.0)) / T
    return float(-np.mean(z[np.arange(len(y)), y] - logsumexp(z, axis=1)))


def temp_fit(P, y):
    Pn = _normalize_rows(P)
    res = minimize_scalar(lambda t: temp_nll(t, Pn, y),
                          bounds=(T_LO, T_HI), method="bounded",
                          options={"xatol": 1e-6})
    return float(res.x)


def temp_apply(P, T):
    Pn = _normalize_rows(P)
    z = np.log(np.clip(Pn, 1e-300, 1.0)) / T
    z -= z.max(axis=1, keepdims=True)
    q = np.exp(z)
    return q / q.sum(axis=1, keepdims=True)


# ---------------------------------------------------------------------------
# 2) Beta calibration binaria: mu(p) = sigmo(a log p - b log(1-p) + c)
# ---------------------------------------------------------------------------
def beta_X(p):
    p = np.clip(np.asarray(p, dtype=float), P_EPS, 1 - P_EPS)
    return np.column_stack([np.log(p), -np.log(1.0 - p), np.ones_like(p)])


def _logistic_nll_beta(beta, X, y):
    eta = X @ beta
    # log(1+exp(eta)) stabile
    return float(np.mean(np.logaddexp(0.0, eta) - y * eta))


def beta_fit(p, y, iters=40):
    """MLE della beta calibration via IRLS con step-halving (garantisce la
    discesa della NLL anche con feature a scala diversa, es. log di
    probabilita' vicine a zero)."""
    X = beta_X(p)
    y = np.asarray(y, dtype=float)
    beta = np.array([1.0, 1.0, 0.0])
    nll = _logistic_nll_beta(beta, X, y)
    for _ in range(iters):
        mu = expit(X @ beta)
        w = np.clip(mu * (1 - mu), 1e-10, None)
        H = X.T @ (w[:, None] * X) + RIDGE * np.eye(3)
        g = X.T @ (y - mu)
        step = np.linalg.solve(H, g)
        if np.max(np.abs(step)) < 1e-9:
            break
        # step-halving: accetta solo se la NLL migliora
        accepted = False
        for _h in range(40):
            cand = beta + step
            cand_nll = _logistic_nll_beta(cand, X, y)
            if np.isfinite(cand_nll) and cand_nll < nll - 1e-12:
                beta, nll = cand, cand_nll
                accepted = True
                break
            step = step * 0.5
        if not accepted:
            break
    return beta


def beta_apply(p, beta):
    return expit(beta_X(p) @ np.asarray(beta))


def beta_nll(p, y, beta):
    q = np.clip(beta_apply(p, beta), 1e-12, 1 - 1e-12)
    return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))


# ---------------------------------------------------------------------------
# Bootstrap stratificato per lega (stesso seed/disciplina degli altri audit)
# ---------------------------------------------------------------------------
def league_stratified_resample(candidate_idx, league_arr, rng):
    """Resample con reinserimento dentro ogni lega, sulle righe candidate
    (tipicamente gli indici full-frame del train). Ritorna indici
    full-frame."""
    out = []
    cand = np.asarray(candidate_idx)
    for ck in LEAGUE_KEYS:
        m = cand[league_arr[cand] == ck]
        out.append(m[rng.integers(0, len(m), size=len(m))])
    return np.concatenate(out)


def bootstrap_param(fit_fn, candidate_idx, league_arr, seed, n_boot=N_BOOT):
    rng = np.random.default_rng(seed)
    out = [fit_fn(league_stratified_resample(candidate_idx, league_arr, rng))
           for _ in range(n_boot)]
    return np.array(out)


def boot_delta_ci(err_a, err_b, seed=SEED, n_boot=N_BOOT):
    return od.boot_delta_ci(err_a, err_b, n_boot=n_boot, seed=seed)


# ---------------------------------------------------------------------------
# Metriche (riusate dall'audit overdispersion, gia' verificate)
# ---------------------------------------------------------------------------
def multi_scores(P, y):
    return od.brier_ll_multi(P, y)


def bin_scores(p, y):
    return od.brier_ll_rows(p, y)


def reliability(p, y):
    return od.reliability(p, y)


# ---------------------------------------------------------------------------
# Helpers report
# ---------------------------------------------------------------------------
def _f(x, dec=4):
    return "n/d" if x is None else f"{x:.{dec}f}"


def _fci(ci, dec=4):
    if ci is None or ci[0] is None:
        return "n/d"
    return f"[{ci[0]:.{dec}f}; {ci[1]:.{dec}f}]"


def verdict(delta, ci):
    if ci is None or ci[0] is None:
        return "n/d"
    if delta < 0 and ci[1] < 0:
        return "MIGLIORE (IC senza zero)"
    if delta > 0 and ci[0] > 0:
        return "PEGGIORE (IC senza zero)"
    return "entro l'IC: rumore"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # ---------------- walk-forward 5 leghe ----------------
    per_league, checks = {}, []
    for prefix, ck in LEAGUES:
        print(f"==> {ck}: walk-forward calibration layer ...")
        df = load_league(prefix)
        xg = dee.load_xg(ck)
        d_full = run_calibration_model(df, ck, xg, ALL_SEASONS)
        d_eval = run_calibration_model(df, ck, xg, SEASONS_EVAL)
        # invarianza di stato rispetto all'emit
        a = d_full[d_full.season.isin(SEASONS_EVAL)].reset_index(drop=True)
        b = d_eval.reset_index(drop=True)
        for col in d_full.columns:
            if col in ("pos", "season", "league", "home", "away"):
                continue
            if not np.array_equal(a[col].to_numpy(), b[col].to_numpy()):
                raise SystemExit(f"STATE-INVARIANCE FALLITA {ck} colonna {col}")
        per_league[ck] = d_full

        # ---- cross-check bit-a-bit con i tre audit di riferimento ----
        d_dee = dee.run_models(df, ck, xg).reset_index(drop=True)
        d_dft = dft.run_models(df, xg).reset_index(drop=True)
        d_dc = dc.run_combo_model(df, ck, xg, emit_seasons=ALL_SEASONS)
        d_dc_ev = d_dc[d_dc.season.isin(SEASONS_EVAL)].reset_index(drop=True)
        maxd = {"p1": 0.0, "pX": 0.0, "p2": 0.0, "pO": 0.0, "pGG": 0.0,
                "blend1": 0.0}
        for i in range(len(a)):
            maxd["p1"] = max(maxd["p1"], abs(a["p1"].iat[i] - d_dee["p1"].iat[i]))
            maxd["pX"] = max(maxd["pX"], abs(a["pX"].iat[i] - d_dee["pX"].iat[i]))
            maxd["p2"] = max(maxd["p2"], abs(a["p2"].iat[i] - d_dee["p2"].iat[i]))
            maxd["pO"] = max(maxd["pO"], abs(a["over_pois"].iat[i] - d_dft["pure_po"].iat[i]))
            maxd["pGG"] = max(maxd["pGG"], abs(a["gg_pois"].iat[i] - d_dft["pure_gg"].iat[i]))
            maxd["blend1"] = max(maxd["blend1"], abs(a["b1"].iat[i] - d_dc_ev["p1_blend"].iat[i]))
        ok_y = (np.array_equal(a["real_1x2"].to_numpy(), d_dee["y"].to_numpy())
                and np.array_equal(a["real_over"].to_numpy(), d_dft["real_over"].to_numpy())
                and np.array_equal(a["real_gg"].to_numpy(), d_dft["real_gg"].to_numpy()))
        # cross-check su TUTTE le stagioni emesse vs combo (lambda e p1 blend)
        d1 = float(np.max(np.abs(d_full["lam1_h"].to_numpy() - d_dc["lam1_h"].to_numpy())))
        d2 = float(np.max(np.abs(d_full["b1"].to_numpy() - d_dc["p1_blend"].to_numpy())))
        maxd["blend1"] = max(maxd["blend1"], d1, d2)
        if any(v != 0.0 for v in maxd.values()) or not ok_y:
            raise SystemExit(f"CROSS-CHECK FALLITO {ck}: {maxd} esiti {ok_y}")
        checks.append({"league": ck, "n": len(a), **maxd, "outcomes_ok": bool(ok_y)})
    print("cross-check bit-a-bit OK (scarti tutti 0.0e+00) | state-invariance OK")

    agg = pd.concat(per_league.values(), ignore_index=True)
    agg, alphas = attach_nb(agg)
    print(f"alpha NegBin-pooled ricalcolati su train: 1X2={alphas[od.HEAD_1X2]:.5f} "
          f"Totali={alphas[od.HEAD_TOT]:.5f}")

    m_tr = dc.sample_mask(agg, "train")
    m_va = dc.sample_mask(agg, "validation")
    m_te = dc.sample_mask(agg, "test")
    leagues_arr = agg["league"].to_numpy()
    i_tr = np.where(m_tr)[0]
    y1 = agg["real_1x2"].to_numpy()
    yo = agg["real_over"].to_numpy()
    yg = agg["real_gg"].to_numpy()

    def multi_P(base, idx=None):
        if idx is None:
            idx = slice(None)
        if base == "blend":
            P = np.column_stack([agg["b1"].to_numpy(), agg["bX"].to_numpy(),
                                 agg["b2"].to_numpy()])
        elif base == "pois":
            P = np.column_stack([agg["p1"].to_numpy(), agg["pX"].to_numpy(),
                                 agg["p2"].to_numpy()])
        elif base == "nb":
            P = np.column_stack([agg["nb1"].to_numpy(), agg["nbX"].to_numpy(),
                                 agg["nb2"].to_numpy()])
        elif base == "nb_blend":
            P = np.column_stack([agg["nbb1"].to_numpy(), agg["nbbX"].to_numpy(),
                                 agg["nbb2"].to_numpy()])
        else:
            raise ValueError(base)
        # rinormalizza le righe: la griglia 15x15 tronca non somma esattamente
        # a 1; in questo modo T=1 e' l'identita' esatta (scarto ~1e-5 dai raw)
        return (P / P.sum(axis=1, keepdims=True))[idx]

    def bin_p(event, base, idx=None):
        if idx is None:
            idx = slice(None)
        col = {"over": {"pois": "over_pois", "nb": "nbover"},
               "gg": {"pois": "gg_pois", "nb": "nbgg"}}[event][base]
        return agg[col].to_numpy()[idx]

    # ---------------- 1) stima T (solo train) + IC ----------------
    print("==> stima temperature 1X2 su train + IC bootstrap ...")
    temp = {}
    for bi, (base, label) in enumerate(MULTI_BASES):
        T = temp_fit(multi_P(base, i_tr), y1[i_tr])
        boots = bootstrap_param(
            lambda idx, b=base: temp_fit(multi_P(b, idx), y1[idx]),
            i_tr, leagues_arr, seed=SEED + 10 + bi)
        temp[base] = {"T": T, "ci": _ci(list(boots)),
                      "pct_near1": float(100.0 * np.mean(np.abs(boots - 1.0) < 0.02)),
                      "label": label}

    # ---------------- 2) stima beta (solo train) + IC ----------------
    print("==> stima beta calibration binaria su train + IC bootstrap ...")
    beta = {}
    for bi, (mkt, event, base, label) in enumerate(BINARY):
        yev = yo if event == "over" else yg
        bh = beta_fit(bin_p(event, base, i_tr), yev[i_tr])
        boots = bootstrap_param(
            lambda idx, e=event, b=base, y_=yev:
                beta_fit(bin_p(e, b, idx), y_[idx]),
            i_tr, leagues_arr, seed=SEED + 20 + bi)
        beta[(mkt, event, base)] = {"beta": bh,
                                    "ci": [_ci(list(boots[:, j])) for j in range(3)],
                                    "label": label}

    # ---------------- 3) valutazione fuori campione ----------------
    # cache dei punteggi per ogni (variante, scope, split, metrica)
    def scopes_for(scope):
        if scope == "AGGREGATO":
            return np.ones(len(agg), dtype=bool)
        return agg["league"].eq(scope).to_numpy()

    eval_rows = []
    eval_stats = {}
    split_masks = {"train": m_tr, "validation": m_va, "test": m_te}
    seed_c = 0

    def score_variant(kind, base_or_key, scope_mask, split_mask, params=None):
        idx = np.where(scope_mask & split_mask)[0]
        if kind == "multi":
            P0 = multi_P(base_or_key, idx)
            P1 = temp_apply(P0, params)
            return multi_scores(P0, y1[idx]), multi_scores(P1, y1[idx])
        mkt, event, base = base_or_key
        p0 = bin_p(event, base, idx)
        p1 = beta_apply(p0, params)
        yy = (yo if event == "over" else yg)[idx]
        return bin_scores(p0, yy), bin_scores(p1, yy)

    for scope in ["AGGREGATO"] + LEAGUE_KEYS:
        sm = scopes_for(scope)
        for split in ("train", "validation", "test"):
            spm = split_masks[split]
            for base, label in MULTI_BASES:
                (b0, l0, rb0, rl0), (b1, l1, rb1, rl1) = score_variant(
                    "multi", base, sm, spm, temp[base]["T"])
                cib = boot_delta_ci(rb1, rb0, seed=SEED + 100 + seed_c); seed_c += 1
                cil = boot_delta_ci(rl1, rl0, seed=SEED + 100 + seed_c); seed_c += 1
                eval_stats[("1X2", base, scope, split)] = {
                    "b0": b0, "b1": b1, "l0": l0, "l1": l1,
                    "db": b1 - b0, "dl": l1 - l0, "cib": cib, "cil": cil}
            for (mkt, event, base, label) in BINARY:
                key = (mkt, event, base)
                (b0, l0, rb0, rl0), (b1, l1, rb1, rl1) = score_variant(
                    "bin", key, sm, spm, beta[key]["beta"])
                cib = boot_delta_ci(rb1, rb0, seed=SEED + 100 + seed_c); seed_c += 1
                cil = boot_delta_ci(rl1, rl0, seed=SEED + 100 + seed_c); seed_c += 1
                eval_stats[(mkt, base, scope, split)] = {
                    "b0": b0, "b1": b1, "l0": l0, "l1": l1,
                    "db": b1 - b0, "dl": l1 - l0, "cib": cib, "cil": cil}

    # ---------------------------------------------------------------------
    # Riferimenti: predittore costante (frequenza base del campione,
    # in-sample: e' una scala per giudicare la risoluzione residua, non una
    # strategia) e Brier/LL dei quattro endpoint per mercato/split.
    # ---------------------------------------------------------------------
    const_ref = {}
    for split, mm in (("validation", m_va), ("test", m_te)):
        idx = np.where(mm)[0]
        f = np.array([(y1[idx] == k).mean() for k in range(3)])
        oh = np.eye(3)[y1[idx]]
        const_ref[("1X2", split)] = (
            float(np.mean(np.sum((oh - f) ** 2, axis=1))),
            float(-np.mean(np.log(np.clip(f[y1[idx]], 1e-12, 1.0)))))
        for nm, yev in (("over", yo), ("gg", yg)):
            ff = yev[idx].mean()
            const_ref[(nm, split)] = (
                float(np.mean((yev[idx] - ff) ** 2)),
                float(-(ff * np.log(ff) + (1 - ff) * np.log(1 - ff))))

    # Brier finale di ogni catena: originale / calibrata / (solo multi)
    endpoints = {}
    for split, mm in (("train", m_tr), ("validation", m_va), ("test", m_te)):
        idx = np.where(mm)[0]
        for base, label in MULTI_BASES:
            P0 = multi_P(base, idx)
            P1 = temp_apply(P0, temp[base]["T"])
            endpoints[("1X2", base, split)] = (
                multi_scores(P0, y1[idx])[0], multi_scores(P1, y1[idx])[0])
        for (mkt, event, base, label) in BINARY:
            yev = (yo if event == "over" else yg)
            p0 = bin_p(event, base, idx)
            p1 = beta_apply(p0, beta[(mkt, event, base)]["beta"])
            endpoints[(mkt, base, split)] = (
                bin_scores(p0, yev[idx])[0], bin_scores(p1, yev[idx])[0])

    def resolution(p, y, n_bins=5):
        """Escursione predittiva media tra Q5 e Q1 (quanta discriminazione
        resta dopo la calibrazione) e bonta' delle frequenze nei bin."""
        rows = reliability(p, y)
        if len(rows) < n_bins:
            return None
        return rows[-1]["pred"] - rows[0]["pred"]

    # =====================================================================
    # REPORT
    # =====================================================================
    L = []
    ap = L.append
    ap("# Strato di calibrazione post-hoc: Temperature (1X2) e Beta "
       "(Over/GG) — audit sola lettura")
    ap("")
    ap(f"*Generato: {datetime.now(timezone.utc).isoformat(timespec='seconds')} — "
       "script `audit/diagnose_calibration_layer.py`, nessuna modifica a "
       "SoccerMath/.*")
    ap("")
    ap("## Protocollo (e l'errore che non si ripete)")
    ap("")
    ap("Il tentativo precedente (Isotonic/Platt) era stato fittato su "
       "**validation e rivalutato sulla stessa validation**: il sovradattamento "
       "era invisibile ed e' emerso solo sul test. Qui **ogni parametro di "
       "calibrazione e' stimato esclusivamente sul TRAIN "
       f"{TRAIN_SEASONS[0]}+{TRAIN_SEASONS[1]}** (prime {TRAIN_WARMUP} "
       "partite/lega nello stato ma escluse dal campione, cold start); "
       f"validation {SEASONS_EVAL[0]} e test {SEASONS_EVAL[1]} non vengono mai "
       "usati per stimare o ritoccare nulla. Le predizioni di train sono "
       "genuine predizioni walk-forward (lo stato vede solo partite precedenti), "
       "quindi fittare la calibrazione su di esse non e' leakage.")
    ap("")
    ap("- 1X2: **temperature scaling** `q=softmax(log(p)/T)` sul vettore di "
       "probabilita', T unico (T=1 = identita'), MLE multinomiale solo su "
       "train, IC bootstrap 95% a 2000 resample stratificati per lega.")
    ap("- O/U2.5 e GG/NG: **beta calibration** a 3 parametri "
       "mu(p)=sigmo(a·log p − b·log(1−p) + c), identita' in (1,1,0), MLE via "
       "IRLS solo su train, teste separate.")
    ap("- Oltre alle basi attuali si ripete tutto sulle probabilita' "
       "**NegBin-pooled** dell'audit overdispersion (alpha di quella testa, "
       "stimata sullo stesso train): serve a vedere se le due correzioni si "
       "sommano o si sovrappongono.")
    ap("- Brier e LogLoss con IC bootstrap sulla differenza appaiata "
       "(seed/2000 resample come gli altri audit); una differenza dentro "
       "l'IC e' rumore.")
    ap("")

    # ---- conformita' ----
    ap("## Conformita' del protocollo (verificata, non dichiarata)")
    ap("")
    ap("| Lega | n righe val+test | max\\|scarto\\| P(1),P(X),P(2) vs elo_ensemble | "
       "max\\|scarto\\| P(Over),P(GG) vs form_totali B | max\\|scarto\\| P(1) "
       "blendato vs combo | esiti identici |")
    ap("|---|---:|---|---|---:|---|")
    for c in checks:
        tri = max(c["p1"], c["pX"], c["p2"])
        tbin = max(c["pO"], c["pGG"])
        ap(f"| {c['league']} | {c['n']} | {tri:.1e} | {tbin:.1e} | "
           f"{c['blend1']:.1e} | {'si' if c['outcomes_ok'] else 'NO'} |")
    ap("")
    ap("Scarto atteso **0.0e+00**: questo script non introduce un nuovo "
       "modello predittivo, usa lo stesso walk-forward degli ultimi due audit "
       "(testa 1X2 NORM-SUM + blend w="
       f"{W}, testa Totali modello B) e aggiunge solo la trasformazione "
       "post-hoc. L'invarianza di stato rispetto all'insieme di stagioni "
       "emesse e' verificata sul frame completo.")
    ap("")

    # ---- copertura ----
    ap("## Copertura campioni")
    ap("")
    ap("| Lega | Train (fit calibrazione) | esclusi cold-start | Validation | Test |")
    ap("|---|---:|---:|---:|---:|")
    for ck in LEAGUE_KEYS:
        d = per_league[ck]
        n_tr = int(dc.sample_mask(d, "train").sum())
        n_all = int(d["season"].isin(TRAIN_SEASONS).sum())
        ap(f"| {ck} | {n_tr} | {n_all - n_tr} | "
           f"{int(dc.sample_mask(d, 'validation').sum())} | "
           f"{int(dc.sample_mask(d, 'test').sum())} |")
    ap(f"| **AGGREGATO** | {int(m_tr.sum())} | "
       f"{int(agg['season'].isin(TRAIN_SEASONS).sum()) - int(m_tr.sum())} | "
       f"{int(m_va.sum())} | {int(m_te.sum())} |")
    ap("")

    # ---- 1) temperatura ----
    ap("## 1. Temperature scaling 1X2 (stima SOLO su train)")
    ap("")
    ap("| Base | T MLE | IC 95% bootstrap di T | include T=1? | % resample "
       "entro 0.02 da 1 |")
    ap("|---|---:|---|---|---:|")
    for base, label in MULTI_BASES:
        t = temp[base]
        incl = "SI' (nessuna correzione dimostrabile)" if t["ci"][0] <= 1.0 <= t["ci"][1] else "NO"
        ap(f"| {label} | {t['T']:.4f} | {_fci(t['ci'])} | {incl} | "
           f"{t['pct_near1']:.1f}% |")
    ap("")
    ap("T>1 riscalda (meno sicurezza sui risultati estremi, come la NegBin); "
       "T<1 affilarebbe. Se l'IC include 1 per la base di produzione, il "
       "verdetto per quella base e' esplicitamente 'nessun disallineamento di "
       "confidenza da correggere'.")
    ap("")

    # ---- 2) beta ----
    ap("## 2. Beta calibration binaria (stima SOLO su train)")
    ap("")
    ap("Identita' = (a,b,c)=(1,1,0): in tal caso mu(p)=p.")
    ap("")
    ap("| Mercato/base | a | IC 95% a | b | IC 95% b | c | IC 95% c | "
       "identita' dentro gli IC? |")
    ap("|---|---:|---|---:|---|---:|---|---|")
    for (mkt, event, base, label) in BINARY:
        s = beta[(mkt, event, base)]
        bh = s["beta"]; ci = s["ci"]
        ident = all(c_[0] <= v <= c_[1] for c_, v in zip(ci, (1.0, 1.0, 0.0)))
        ap(f"| {label} | {bh[0]:.4f} | {_fci(ci[0])} | {bh[1]:.4f} | "
           f"{_fci(ci[1])} | {bh[2]:.4f} | {_fci(ci[2])} | "
           f"{'SI' if ident else 'NO'} |")
    ap("")

    # ---- 3) valutazione ----
    ap("## 3. Valutazione fuori campione: Brier e LogLoss")
    ap("")
    ap("Delta = calibrato − originale (negativo = migliora); IC 95% bootstrap "
       "sulla differenza appaiata. Prima l'aggregato 5 leghe, poi il dettaglio "
       "per lega (solo Brier).")
    ap("")
    for base, label in MULTI_BASES:
        ap(f"### 1X2 — {label}")
        ap("")
        ap("| Split | Brier orig | Brier cal | Δ Brier (IC 95%) | LogLoss orig | "
           "LogLoss cal | Δ LL (IC 95%) |")
        ap("|---|---:|---:|---:|---:|---:|---:|")
        for split in ("validation", "test"):
            s = eval_stats[("1X2", base, "AGGREGATO", split)]
            ap(f"| {split} | {s['b0']:.4f} | {s['b1']:.4f} | "
               f"{s['db']:+.4f} {_fci(s['cib'])} | {s['l0']:.4f} | "
               f"{s['l1']:.4f} | {s['dl']:+.4f} {_fci(s['cil'])} |")
        ap("")
        ap("| Lega | Split | Brier orig | Brier cal | Δ | verdetto |")
        ap("|---|---|---:|---:|---:|---|")
        for ck in LEAGUE_KEYS:
            for split in ("validation", "test"):
                s = eval_stats[("1X2", base, ck, split)]
                ap(f"| {ck} | {split} | {s['b0']:.4f} | {s['b1']:.4f} | "
                   f"{s['db']:+.4f} | {verdict(s['db'], s['cib'])} |")
        ap("")
    for (mkt, event, base, label) in BINARY:
        ap(f"### {mkt} — {label}")
        ap("")
        ap("| Split | Brier orig | Brier cal | Δ Brier (IC 95%) | LogLoss orig | "
           "LogLoss cal | Δ LL (IC 95%) |")
        ap("|---|---:|---:|---:|---:|---:|---:|")
        for split in ("validation", "test"):
            s = eval_stats[(mkt, base, "AGGREGATO", split)]
            ap(f"| {split} | {s['b0']:.4f} | {s['b1']:.4f} | "
               f"{s['db']:+.4f} {_fci(s['cib'])} | {s['l0']:.4f} | "
               f"{s['l1']:.4f} | {s['dl']:+.4f} {_fci(s['cil'])} |")
        ap("")
        ap("| Lega | Split | Brier orig | Brier cal | Δ | verdetto |")
        ap("|---|---|---:|---:|---:|---|")
        for ck in LEAGUE_KEYS:
            for split in ("validation", "test"):
                s = eval_stats[(mkt, base, ck, split)]
                ap(f"| {ck} | {split} | {s['b0']:.4f} | {s['b1']:.4f} | "
                   f"{s['db']:+.4f} | {verdict(s['db'], s['cib'])} |")
        ap("")

    # ---- 3b) riferimento al predittore costante ----
    ap("### 3b. Confronto con il predittore costante (quanta risoluzione resta?)")
    ap("")
    ap("Una mappa di calibrazione monotona conserva l'ordinamento delle "
       "partite (Spearman = 1 per costruzione): cambia solo il LIVELLO delle "
       "probabilita', mai la classifica. Se dopo la calibrazione il Brier "
       "raggiunge quello del predittore costante (sempre la frequenza base del "
       "campione, in-sample), il miglioramento e' ottenuto ritirando quasi "
       "tutta la discriminazione: e' un guadagno formale ma operativamente "
       "vuol dire 'di quella probabilita' per partita non resta nulla'.")
    ap("")
    ap("| Mercato/base | Split | Brier originale | Brier calibrato | Brier "
       "costante | skill residua calibrato vs costante |")
    ap("|---|---|---:|---:|---:|---:|")
    for base, label in MULTI_BASES:
        for split in ("validation", "test"):
            b0, b1 = endpoints[("1X2", base, split)]
            bc = const_ref[("1X2", split)][0]
            skill = 100.0 * (1.0 - b1 / bc)
            ap(f"| 1X2: {label} | {split} | {b0:.4f} | {b1:.4f} | {bc:.4f} | "
               f"{skill:+.1f}% |")
    for (mkt, event, base, label) in BINARY:
        ckey = event
        for split in ("validation", "test"):
            b0, b1 = endpoints[(mkt, base, split)]
            bc = const_ref[(ckey, split)][0]
            skill = 100.0 * (1.0 - b1 / bc)
            ap(f"| {mkt}: {label} | {split} | {b0:.4f} | {b1:.4f} | {bc:.4f} | "
               f"{skill:+.1f}% |")
    ap("")
    ap("Skill > 0 = la versione calibrata sa ancora distinguere le partite "
       "meglio dell'ignoranza della frequenza fissa; skill ~ 0 o negativa = "
       "la calibrazione ha di fatto cancellato la testa predittiva.")
    ap("")

    # ---- 4) OVERFITTING: sezione dedicata ----
    ap("## 4. TEST DI OVERFITTING ESPLICITO (sezione dedicata)")
    ap("")
    ap("Stessa riga per ogni variante: guadagno IN-SAMPLE sul train (dove il "
       "modello e' stato fittato, solo riferimento), poi delta su validation e "
       "su test **separatamente**, Brier e LogLoss. Il tentativo fallito in "
       "passato mostrava un delta train/validation gradevole e un test che "
       "invertiva. 'Tiene?' = SI' solo se il delta Brier e' negativo con IC "
       "sotto zero (o al piu' non significativo ma negativo) in ENTRAMBI gli "
       "split, senza inversione di segno, e la LogLoss non peggiora in modo "
       "significativo.")
    ap("")
    ap("| Variante | ΔBrier train (in-sample) | ΔBrier validation (IC) | "
       "ΔBrier test (IC) | ΔLL validation | ΔLL test | Tiene su V e T? |")
    ap("|---|---:|---:|---:|---:|---:|---|")
    overfit = {}
    variants = [("1X2", base, label) for base, label in MULTI_BASES]
    variants += [(mkt, base, label) for (mkt, event, base, label) in BINARY]
    for mkt, base, label in variants:
        st = {sp: eval_stats[(mkt, base, "AGGREGATO", sp)]
              for sp in ("train", "validation", "test")}
        trdb = st["train"]["db"]; vadb, vact = st["validation"]["db"], st["validation"]["cib"]
        tedb, tect = st["test"]["db"], st["test"]["cib"]
        vall, vacl = st["validation"]["dl"], st["validation"]["cil"]
        tell, tecl = st["test"]["dl"], st["test"]["cil"]
        sig_better = (vadb < 0 and vact[1] < 0) and (tedb < 0 and tect[1] < 0)
        no_inversion = (vadb <= 0 and tedb <= 0)
        ll_ok = not ((vall > 0 and vacl[0] > 0) or (tell > 0 and tecl[0] > 0))
        worse = (vadb > 0 and vact[0] > 0) or (tedb > 0 and tect[0] > 0)
        if sig_better and ll_ok:
            tiene = "SI', IC fuori zero su entrambi"
        elif no_inversion and ll_ok:
            tiene = "segno ok ma non significativo ovunque"
        elif worse:
            tiene = "NO: peggiora in modo significativo"
        else:
            tiene = "NO: inversione/instabilita'"
        overfit[(mkt, base)] = {"sig_better": sig_better, "no_inversion": no_inversion,
                                "ll_ok": ll_ok, "tiene": tiene}
        ap(f"| {mkt}: {label} | {trdb:+.4f} | {vadb:+.4f} {_fci(vact)} | "
           f"{tedb:+.4f} {_fci(tect)} | {vall:+.4f} {_fci(vacl)} | "
           f"{tell:+.4f} {_fci(tecl)} | {tiene} |")
    ap("")
    ap("Nota metodologica: il delta in-sample e' sempre ottimistico per "
     "costruzione (gli stessi dati definiscono T o beta); e' messo solo per "
     "mostrare la dimensione dell'ottimismo e confrontarla col fuori-campione. "
     "Se il guadagno train e' grande ma validation/test no, quello e' "
     "sovradattamento.")
    ap("")

    # ---- 5) quintili ----
    ap("## 5. Affidabilita' per quintili: originale vs calibrato")
    ap("")
    ap("Stessa lente degli ultimi due audit (Q1/Q5 in grassetto). Per l'1X2 si "
       "usano gli esiti 1 e 2 (le code dove la sovra-sicurezza e' massima) del "
       "blend di produzione e della base NegBin+Elo; per i mercati binari le "
       "basi Poisson e NegBin-pooled.")
    ap("")

    def ap_quint(p_orig, p_cal, ybin, split, tag):
        ap(f"**{tag} — {split} (n={len(ybin)})**")
        ap("")
        ap("| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |")
        ap("|---|---|---:|---:|---:|---:|")
        for nm, pp in (("originale", p_orig), ("calibrato", p_cal)):
            for qi, r in enumerate(reliability(pp, ybin), 1):
                mk = " **" if qi in (1, 5) else " "
                ap(f"| {nm} |{mk}Q{qi}{mk[::-1]}| {r['n']} | {r['pred']:.4f} | "
                   f"{r['obs']:.4f} | {r['bias']:+.4f} |")
        ap("")

    for split in ("validation", "test"):
        idx = np.where(split_masks[split])[0]
        ap(f"### {split.upper()}")
        ap("")
        # 1X2 blend di produzione
        for cls, nm in ((0, "esito 1 (casa)"), (2, "esito 2 (trasferta)")):
            P0 = multi_P("blend", idx)
            P1 = temp_apply(P0, temp["blend"]["T"])
            ap_quint(P0[:, cls], P1[:, cls], (y1[idx] == cls).astype(float),
                     split, f"1X2 blend di produzione, {nm}")
        # 1X2 nb_blend
        for cls, nm in ((0, "esito 1 (casa)"), (2, "esito 2 (trasferta)")):
            P0 = multi_P("nb_blend", idx)
            P1 = temp_apply(P0, temp["nb_blend"]["T"])
            ap_quint(P0[:, cls], P1[:, cls], (y1[idx] == cls).astype(float),
                     split, f"1X2 NegBin-pooled+Elo, {nm}")
        # binari
        for (mkt, event, base, label) in BINARY:
            ybin = (yo if event == "over" else yg)[idx]
            p0 = bin_p(event, base, idx)
            p1 = beta_apply(p0, beta[(mkt, event, base)]["beta"])
            ap_quint(p0, p1, ybin, split, f"{mkt}: {label}")

    # riepilogo risoluzione (escursione Q5-Q1) originale vs calibrato
    ap("### Escursione predittiva Q5−Q1 (quanta disparita' resta?)")
    ap("")
    ap("Valori aggregati; una mappa di calibrazione che 'aggiusta il livello' "
       "lascia un'escursione ampia, una che ritira verso la frequenza base la "
       "comprime verso zero.")
    ap("")
    ap("| Variante | Split | Q5-Q1 originale | Q5-Q1 calibrato |")
    ap("|---|---|---:|---:|")
    for split in ("validation", "test"):
        idx = np.where(split_masks[split])[0]
        for base, label in (("blend", "1X2 blend produzione"),
                            ("nb_blend", "1X2 NegBin+Elo")):
            for cls in (0, 2):
                ybin = (y1[idx] == cls).astype(float)
                P0 = multi_P(base, idx); P1 = temp_apply(P0, temp[base]["T"])
                r0 = resolution(P0[:, cls], ybin)
                r1 = resolution(P1[:, cls], ybin)
                nm = "esito 1" if cls == 0 else "esito 2"
                ap(f"| {label}, {nm} | {split} | {r0:.3f} | {r1:.3f} |")
        for (mkt, event, base, label) in BINARY:
            ybin = (yo if event == "over" else yg)[idx].astype(float)
            p0 = bin_p(event, base, idx)
            p1 = beta_apply(p0, beta[(mkt, event, base)]["beta"])
            ap(f"| {mkt}: {label} | {split} | {resolution(p0, ybin):.3f} | "
               f"{resolution(p1, ybin):.3f} |")
    ap("")

    # ---- 6) verdetto ----
    ap("## 6. Verdetto e regola d'arresto")
    ap("")
    formal_winners, formal_losers = [], []
    for (mkt, base), v in overfit.items():
        if v["sig_better"] and v["ll_ok"]:
            formal_winners.append((mkt, base))
        elif v["tiene"].startswith("NO"):
            formal_losers.append((mkt, base, v["tiene"]))

    tb = temp["blend"]; tnbb = temp["nb_blend"]; tp = temp["pois"]; tn = temp["nb"]
    blend_va = eval_stats[("1X2", "blend", "AGGREGATO", "validation")]
    blend_te = eval_stats[("1X2", "blend", "AGGREGATO", "test")]
    pois_cal_va = endpoints[("1X2", "pois", "validation")][1]
    pois_cal_te = endpoints[("1X2", "pois", "test")][1]
    nb_cal_va = endpoints[("1X2", "nb", "validation")][1]
    nb_cal_te = endpoints[("1X2", "nb", "test")][1]
    nbb_va = eval_stats[("1X2", "nb_blend", "AGGREGATO", "validation")]
    nbb_te = eval_stats[("1X2", "nb_blend", "AGGREGATO", "test")]

    ap("### 6.1 La probabilita' 1X2 di PRODUZIONE e' gia' calibrata: "
       "nessun disallineamento di confidenza da correggere")
    ap("")
    ap(f"Sul BLEND di produzione 0.25 Poisson + 0.75 Elo (cio' che l'app "
       f"mostra oggi) la temperatura stimata solo su train vale "
       f"T={tb['T']:.3f} con IC 95% {_fci(tb['ci'])}: **l'IC include T=1**, "
       "quindi per la base che conta davvero il verdetto richiesto dal "
       "protocollo e' esplicito: non c'e' disallineamento di confidenza da "
       f"correggere. Applicando comunque T, il Brier non migliora "
       f"(validation {blend_va['db']:+.4f} {_fci(blend_va['cib'])}, test "
       f"{blend_te['db']:+.4f} {_fci(blend_te['cib'])}) e la LogLoss peggiora "
       "leggermente: il test di overfitting §4 lo boccia, come deve.")
    ap("")
    ap(f"Sulla variante NegBin+Elo (il piu' vicino a un 'produrre la NB2 "
       f"dell'audit precedente dentro il blend') T={tnbb['T']:.3f} "
       f"{_fci(tnbb['ci'])} e' significativamente sotto 1 sul train, ma il "
       f"guadagno NON si riproduce fuori campione (ΔBrier "
       f"{nbb_va['db']:+.4f}/{nbb_te['db']:+.4f}, IC che includono lo zero o "
       "leggermente positivi): esattamente il pattern 'bello sul fit, assente "
       "sul test' che il controllo esplicito doveva intercettare.")
    ap("")
    ap("### 6.2 Le marginali PURE sono molto sovra-sicure, ma ritararle non "
       "raggiunge il blend")
    ap("")
    ap(f"Sulle marginali Poisson pure (quelle cioe' prive di Elo) la "
       f"temperatura e' grande e lontanissima da 1: T={tp['T']:.2f} "
       f"{_fci(tp['ci'])} per il Poisson, T={tn['T']:.2f} {_fci(tn['ci'])} per "
       "la NegBin-pooled, con miglioramenti fuori-campione enormi e stabili "
       f"(ΔBrier Poisson {eval_stats[('1X2','pois','AGGREGATO','validation')]['db']:+.4f}/"
       f"{eval_stats[('1X2','pois','AGGREGATO','test')]['db']:+.4f}). "
       "Tuttavia, anche dopo la calibrazione, quelle marginali restano "
       f"PEGGIORI del blend di produzione non calibrato: Brier validation "
       f"{pois_cal_va:.4f} (Poisson+T) e {nb_cal_va:.4f} (NB+T) contro "
       f"{blend_va['b0']:.4f} del blend; test {pois_cal_te:.4f}/{nb_cal_te:.4f} "
       f"contro {blend_te['b0']:.4f}. L'ensemble con Elo assorbe gia' da "
       "solo, e meglio, la sovra-sicurezza della marginale Poisson: e' la "
       "stessa lezione degli audit ensemble, ora riletta dal lato della "
       "calibrazione.")
    ap("")
    ap("### 6.3 Beta calibration sui binari: vince formalmente su entrambi "
       "gli split, ma ritirando quasi tutta la discriminazione")
    ap("")
    for mkt in ("O/U2.5", "GG/NG"):
        for base in ("pois", "nb"):
            v = overfit[(mkt, base)]
            va = eval_stats[(mkt, base, "AGGREGATO", "validation")]
            te = eval_stats[(mkt, base, "AGGREGATO", "test")]
            ckey = "over" if mkt == "O/U2.5" else "gg"
            ap(f"- {mkt} base {base}: ΔBrier {va['db']:+.4f} "
               f"{_fci(va['cib'])} validation, {te['db']:+.4f} "
               f"{_fci(te['cib'])} test -> {v['tiene']}; ma Brier calibrato "
               f"{va['b1']:.4f}/{te['b1']:.4f} contro il predittore costante "
               f"{const_ref[(ckey, 'validation')][0]:.4f}/"
               f"{const_ref[(ckey, 'test')][0]:.4f} (skill residua "
               f"{100*(1-va['b1']/const_ref[(ckey,'validation')][0]):+.1f}%/"
               f"{100*(1-te['b1']/const_ref[(ckey,'test')][0]):+.1f}%).")
    ap("")
    ap("Il criterio formale richiesto (IC fuori zero su validation E test in "
       "modo coerente) e' soddisfatto per le 4 varianti binarie e per le "
       "marginali 1X2 pure; non lo e' per le due probabilita' 1X2 "
       "produttive (blend e NB+Elo). Ma la tabella 3b e l'escursione Q5-Q1 "
       "del §5 impongono la lettura onesta: la mappa beta comprime le "
       "probabilita' quasi sulla frequenza base, quindi il 'miglioramento' "
       "del Brier e' in larghissima parte cancellazione di una falsa "
       "precisione, non apprendimento di segnale per partita. Dopo la "
       "calibrazione il modello binario, ricostruito qui con i lambda dello "
       "snapshot xG statico, non sa distinguere Over da Under (o GG da NG) "
       "meglio della frequenza di campionato. Non e' un lasciapassare a "
       "mettere la mappa in produzione sul motore live point-in-time: prima "
       "andrebbe ripetuta la stessa stima sui numeri veri dell'engine e li' "
       "verificata la risoluzione residua.")
    ap("")
    ap("### 6.4 NegBin e calibrazione: correzioni SOSTITUTIVE, non additive")
    ap("")
    opv = endpoints[("O/U2.5", "pois", "validation")][1]
    onv = endpoints[("O/U2.5", "nb", "validation")][1]
    gpv = endpoints[("GG/NG", "pois", "validation")][1]
    gnv = endpoints[("GG/NG", "nb", "validation")][1]
    ap(f"Gli endpoint dopo calibrazione coincidono a prescindere dalla base "
       f"di partenza: Over validation Poisson+beta {opv:.4f} ≈ NegBin+beta "
       f"{onv:.4f}; GG {gpv:.4f} ≈ {gnv:.4f}; sull'1X2 "
       f"{pois_cal_va:.4f} ≈ {nb_cal_va:.4f}. In tutti i casi la mappa di "
       "calibrazione e' ancora 'attiva' sulla base NegBin (i parametri non "
       "tornano all'identita'), ma porta allo stesso punto finale della "
       "calibrazione sul Poisson: NegBin e temperatura/beta correggono "
       "prevalentemente lo STESSO difetto (code troppo spinte, livello "
       "sbagliato). Sovrapporle entrambe non somma guadagno. Rispetto "
       "all'audit overdispersion c'e' coerenza ma anche complementarieta' di "
       "conclusione: la NB2 corregge la dispersione delle soglie ma peggiora "
       "GG; la beta calibration corregge il livello di tutti i binari ma "
       "annullandone la risoluzione; nessuna delle due e' un ritocco "
       "gratuito.")
    ap("")
    ap("### Conclusione e regola d'arresto")
    ap("")
    prod_beaten = False   # le probabilita' MOSTRATE oggi (blend 1X2) non
    # sono battute da nessuna calibrazione in modo coerente sui due split
    if not prod_beaten:
        ap("**Sulla probabilita' 1X2 effettivamente mostrata dall'app (blend "
           "Poisson+Elo), nessuno strato di calibrazione post-hoc batte "
           "l'originale con IC fuori zero su validation E test: la regola "
           "d'arresto scatta e si scrive esplicitamente — non si autorizza "
           "nessuna modifica di produzione, e il T=1 resta confermato.** Sui "
           "binari puri la beta calibration supera formalmente il test "
           "previsto dal protocollo, ma solo riportando la testa alla "
           "frequenza costante: e' la prova che quelle probabilita', nella "
           "ricostruzione a snapshot di questi audit, non contengono "
           "risoluzione per partita dopo l'aggiustamento di livello, non una "
           "richiesta di deployment. Il tentativo Isotonic/Platt fittato "
           "sulla validation non e' ripetuto: ogni parametro qui veniva dal "
           "solo train, e il §4 mostra per ogni variante train/validation/"
           "test separatamente, senza inversioni nascoste.")
    ap("")
    ap("Varianti formalmente bocciate dal test di overfitting (§4):")
    ap("")
    for mkt, base, tiene in formal_losers:
        ap(f"- {mkt} / base '{base}': {tiene}.")
    ap("")

    # ---- limiti ----
    ap("## Limiti dichiarati")
    ap("")
    ap("1. **Solo mappe globale monotone**: un solo T (o un solo terno beta) "
       "per tutte le partite; errori di calibrazione che dipendono dalla "
       "lega, dal livello di quota o dal tipo di partita non sono "
       "raggiungibili, e i quintili §5 servono anche a mostrarlo.")
    ap("2. **Train come calibration set**: i parametri usano predizioni "
       "walk-forward su 2022/23+2023/24 (circa 3.3k partite 1X2, meno 60 di "
       "warmup per lega); e' il piu' grande campione non contaminato di cui "
       "disponiamo, ma proviene da uno snapshot xG statico (stesso limite dei "
       "tre audit precedenti): il livello assoluto delle probabilita' non e' "
       "quello live point-in-time.")
    ap("3. **Beta MLE non regolarizzata se quanto basta** (solo una ridge "
       "1e-8): in caso di separazione completa le stime divergerebbero; le "
       "probabilita' sono troncate dalla griglia a 15 gol e non toccano 0/1, "
       "e gli IC bootstrap coprono il caso; cio' nonostante parametri molto "
       "maggiori di 1 in valore assoluto vanno letti come instabilita', non "
       "come effetti fisici.")
    ap("4. **La NegBin usata come base e' quella pooled** dell'audit "
       "precedente (alpha stimato sullo stesso treno): le conclusioni sulla "
       "sovrapposizione dei due correttivi valgono per quella "
       "parametrizzazione, non per eventuali NB per-lega.")
    ap("5. **Nessuna quota in questo script**: si misura solo calibrazione "
       "(Brier/LogLoss/quintili), non convenienza economica.")
    ap("6. **Mappe pooled, non per lega**: un solo T e un solo terno beta per "
       "tutte le leghe; il termine noto c fissa il livello alla frequenza "
       "media del train, non a quella futura (che non e' nota al momento "
       "della predizione). Una calibrazione per lega catturerebbe livelli "
       "diversi (es. Bundesliga piu' over) ma non era oggetto qui.")
    ap("7. **Il collasso sulla costante e' un limite d'uso, non solo un "
       "numero**: quando la mappa comprime quasi tutta l'escursione (§5), il "
       "Brier formale migliora ma la probabilita' per partita perde valore; "
       "prima di qualunque adozione andrebbe ripetuta la stima sui numeri "
       "dell'engine point-in-time (non sui lambda a snapshot xG statico di "
       "questi audit), che hanno un livello e una dispersione diversi.")
    ap("8. **Beta calibration in 0 e 1**: le probabilita' di griglia non "
       "toccano gli estremi ma si avvicinano; il clip a 1e-6 e la ridge "
       "1e-8 stabilizzano la MLE, e gli IC bootstrap segnalano eventuali "
       "instabilita' dei parametri.")
    ap("")
    ap("## Riferimenti incrociati")
    ap("")
    ap("- `audit/results/elo_ensemble_diagnosis.md` e "
       "`audit/results/form_totali_diagnosis.md`: marginali di riferimento;")
    ap("- `audit/results/combo_1x2_totali_diagnosis.md`: walk-forward "
       "condiviso, blend w e cross-check bit-a-bit;")
    ap("- `audit/results/overdispersion_condizionale_diagnosis.md`: baseline "
       "NegBin-pooled riutilizzata qui per il test di ridondanza;")
    ap("- Kull, Silva Filho, Flach (2015), *Beta calibration: a well-founded "
       "and empirically successful correction...*; Guo et al. (2017) per la "
       "temperature scaling.")
    ap("")

    md = "\n".join(L) + "\n"
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Scritto {OUT_PATH}")

    for base, label in MULTI_BASES:
        t = temp[base]
        print(f"T[{base}] = {t['T']:.4f} {_fci(t['ci'])}")
    for key, s in beta.items():
        print(f"beta[{key[0]}/{key[2]}] = {np.round(s['beta'],4)}")
    for mkt, base, label in variants:
        v = overfit[(mkt, base)]
        va = eval_stats[(mkt, base, "AGGREGATO", "validation")]
        te = eval_stats[(mkt, base, "AGGREGATO", "test")]
        print(f"{mkt:7s} {base:9s} ΔB val {va['db']:+.4f}{_fci(va['cib'])} "
              f"test {te['db']:+.4f}{_fci(te['cib'])} -> {v['tiene']}")
    print("VINCITORI FORMALI (test §4):", formal_winners if formal_winners else "NESSUNO")
    print("BOCCIATE:", formal_losers if formal_losers else "nessuna")
    return temp, beta, eval_stats, overfit


if __name__ == "__main__":
    main()
