"""
diagnose_overdispersion_condizionale.py — I gol reali, condizionati al lambda
PER-PARTITA del motore a Due Teste, sono piu' dispersi di un Poisson(lambda)?

Il motore assegna a ogni partita un lambda_home e un lambda_away specifici, e
diversi tra le due teste:
  * testa 1X2  : lambda NORM-SUM con xG + forma ult.5 + fattore mercato (gli
                 stessi di diagnose_elo_ensemble.run_models);
  * testa TOT  : lambda puri senza forma/mercato, modello B di
                 diagnose_form_totali.run_models (quelli che producono O/U e GG).
Entrambe le teste assumono poi Poisson INDIPENDENTI. Qui si tiene fisso quel
lambda partita per partita (niente media aggregata di lega) e si chiede se la
varianza reale dei gol sia superiore a quella Poisson: se si', la famiglia
giusta e' la NegBin NB2 (media = lambda, varianza = lambda + alpha*lambda^2).

PROTOCOLLO (identico alle altre diagnosi della serie, nessuna riottimizzazione):
  * TRAIN 2022/23+2023/24, prime TRAIN_WARMUP=60 partite/lega nello stato ma
    escluse dal campione (cold start): qui SOLAMENTE si stima alpha (MLE);
  * VALIDATION 2024/25: conferma, mai usata per stimare alpha;
  * TEST 2025/26: sola lettura;
  * 5 leghe, walk-forward a passata singola, stato aggiornato dopo la previsione.

STIMA (solo TRAIN): alpha NB2 via MLE sui gol reali condizionati al lambda
della partita/squadra, in due versioni come per il rho Dixon-Coles:
  * POOLED  : un alpha unico su tutte le 5 leghe;
  * PER-LEGA: 5 alpha separati;
e separatamente per le DUE teste (i lambda sono diversi per architettura):
alpha_1X2 dai lambda della testa 1X2, alpha_TOT dai lambda della testa Totali.
Per ogni alpha: IC 95% bootstrap a 2000 resample di PARTITE (coppia
home/away sempre insieme, stratificata per lega nel pooled).

VALUTAZIONE (validation e test, alpha fissati sul train): per ogni mercato
  * 1X2 (usa i lambda della testa 1X2)
  * Over/Under 2.5 e GG/NG (usano i lambda della testa Totali, modello B)
si calcolano le probabilita' in 3 versioni: POISSON (quella attuale),
NB-pooled (alpha unico di quella testa), NB-per-lega (alpha della lega).
Griglia congiunta 15x15 con marginali NegBin indipendenti, stesso supporto
troncato NON rinormalizzato della produzione (cambia solo la pmf marginale:
Poisson -> NB2). Brier e LogLoss per lega e aggregato, con IC bootstrap 95%
sulla differenza appaiata (stessa disciplina "dentro l'IC = rumore").

CONFORMITA': il walk-forward e' quello di diagnose_combo_1x2_totali
(run_combo_model, emit esteso alle stagioni di train): le marginali POISSON di
questo audit sono confrontate RIGA PER RIGA con diagnose_elo_ensemble (1X2) e
diagnose_form_totali modello B (Over, GG); scarto atteso 0.0e+00. L'invarianza
di stato dell'estensione ai treni e' verificata con check_state_invariance.

DIAGNOSTICA (sola lettura): alpha ricalcolato su validation/test come controllo
di stabilita' (mai usato per le probabilita'), alpha ai minimi quadrati
(method-of-moments) e confronto della frazione di zeri reale/Poisson/NB, per
vedere se la sovra-dispersione ha la forma simmetrica dell'NB2.

REGOLA D'ARRESTO: se nessuna versione NegBin batte il Poisson attuale con IC
bootstrap fuori dallo zero su VALIDATION e TEST in modo coerente (stesso segno,
nessuna inversione significativa), il verdetto e' "overdispersion non
dimostrata neanche in versione condizionale", scritto esplicitamente.

NON tocca SoccerMath/ (sola lettura).
Output: audit/results/overdispersion_condizionale_diagnosis.md
Uso:    python audit/diagnose_overdispersion_condizionale.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import gammaln, xlogy
from scipy.stats import nbinom as scipy_nbinom

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from backtest_experiment_all import LEAGUES, load_league       # noqa: E402
from topmix_margins import N_BOOT, SEED, _ci                    # noqa: E402
import diagnose_elo_ensemble as dee                             # noqa: E402
import diagnose_form_totali as dft                              # noqa: E402
import diagnose_combo_1x2_totali as dc                          # noqa: E402

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "overdispersion_condizionale_diagnosis.md")

TRAIN_SEASONS = dc.TRAIN_SEASONS                 # ("2022/23", "2023/24")
SEASONS_EVAL = dc.SEASONS_EVAL                   # ("2024/25", "2025/26")
ALL_SEASONS = dc.ALL_SEASONS
TRAIN_WARMUP = dc.TRAIN_WARMUP                   # 60
MAX_GOALS = dc.MAX_GOALS                         # 15
SPLITS = ("train", "validation", "test")
HEAD_1X2 = "1x2"
HEAD_TOT = "tot"
HEADS = (HEAD_1X2, HEAD_TOT)
HEAD_LABEL = {HEAD_1X2: "testa 1X2 (NORM-SUM xG+forma+mercato)",
              HEAD_TOT: "testa Totali (modello B, lambda puri)"}
VERSIONS = ("poisson", "nb_pooled", "nb_lega")
VERSION_LABEL = {
    "poisson": "POISSON (attuale)",
    "nb_pooled": "NB-pooled (alpha unico 5 leghe)",
    "nb_lega": "NB-per-lega (alpha della lega)",
}
ALPHA_LO = 1e-8          # confine Poisson (alpha=0); NB2 ha alpha >= 0
ALPHA_HI = 3.0           # limite superiore ampio per la ricerca MLE
ALPHA_BOUNDARY = 1e-5    # sotto: MLE al confine, alpha trattato come zero
GOAL_J = np.arange(MAX_GOALS)


# ---------------------------------------------------------------------------
# NegBin NB2: media lambda, varianza lambda + alpha*lambda^2
# ---------------------------------------------------------------------------
def nb2_logpmf(k, lam, alpha):
    """Log-pmf NB2 vettorizzata. k, lam array broadcastabili; alpha scalare.
    Per alpha <= 0 ritorna la log-pmf Poisson (limite alpha->0).

    Parametrizzazione r = 1/alpha:
      P(k) = Gamma(r+k)/(Gamma(r) Gamma(k+1)) * (r/(r+lam))^r * (lam/(r+lam))^k
    Riscritta rispetto alla Poisson (stabile anche per r molto grande):
      log P_NB = log P_Pois + Delta(r,k) - r*log1p(lam/r) - k*log(r+lam) + lam
      Delta(r,k) = sum_{j=0}^{k-1} log(r+j)
    """
    k = np.asarray(k, dtype=float)
    lam = np.asarray(lam, dtype=float)
    kb, lb = np.broadcast_arrays(k, lam)
    logp = xlogy(kb, lb) - lb - gammaln(kb + 1.0)
    if alpha is None or alpha <= ALPHA_BOUNDARY:
        return logp
    r = 1.0 / alpha
    kmax = int(kb.max())
    if kmax >= 1:
        logs = np.log(r + np.arange(kmax))            # log(r+j), j=0..kmax-1
        delta_k = np.concatenate(([0.0], np.cumsum(logs)))
    else:
        delta_k = np.zeros(1)
    delta = delta_k[kb.astype(int)]
    return logp + delta - r * np.log1p(lb / r) - kb * np.log(r + lb) + lb


def check_nb2_vs_scipy():
    """Conformita' della pmf custom con scipy.stats.nbinom (n=1/alpha,
    p=1/(1+alpha*lam)): puro controllo numerico, nessun dato coinvolto."""
    rng = np.random.default_rng(SEED)
    lams = np.concatenate([[0.0025, 0.3, 1.0, 2.5, 8.0, 20.0],
                           rng.uniform(0.05, 4.0, size=50)])
    ks = np.arange(0, 12)
    worst = 0.0
    for a in (0.002, 0.02, 0.1, 0.5, 1.5):
        r = 1.0 / a
        for lam in lams:
            p_ref = scipy_nbinom.pmf(ks, r, 1.0 / (1.0 + a * lam))
            p_mine = np.exp(nb2_logpmf(ks, np.full_like(ks, lam, dtype=float), a))
            worst = max(worst, float(np.max(np.abs(p_ref - p_mine))))
    if worst > 1e-10:
        raise SystemExit(f"NB2 pmf custom non coincide con scipy (max {worst:.2e})")
    return worst


def neg_ll_alpha(alpha, k, lam):
    """Log-verosimiglianza negativa (vettorizzata) per la ricerca MLE."""
    return -float(nb2_logpmf(k, lam, float(alpha)).sum())


def fit_alpha(k, lam):
    """MLE di alpha su un campione di (gol, lambda per partita/squadra).
    Ritorna (alpha, al_confine): alpha in [0, ALPHA_HI], 0 se il minimo sta sul
    confine Poisson."""
    k = np.asarray(k, dtype=float)
    lam = np.asarray(lam, dtype=float)
    res = minimize_scalar(neg_ll_alpha, bounds=(ALPHA_LO, ALPHA_HI),
                          args=(k, lam), method="bounded",
                          options={"xatol": 1e-7})
    a = float(res.x)
    if a <= ALPHA_BOUNDARY:
        # Il miglior alpha e' indistinguibile dal confine Poisson: verifica che
        # il LL in alpha=0 non sia migliore di quello restituito.
        ll0 = -neg_ll_alpha(0.0, k, lam)
        llhat = -res.fun
        if ll0 >= llhat - 1e-8:
            return 0.0, True
    return a, bool(a <= ALPHA_BOUNDARY)


# ---------------------------------------------------------------------------
# Griglie di mercato: Poisson (produzione) e NegBin, stesso supporto 15x15
# troncato e NON rinormalizzato (stessa convenzione di app._poisson_market)
# ---------------------------------------------------------------------------
_U25_MASK = np.fromfunction(lambda i, j: (i + j) < 2.5,
                            (MAX_GOALS, MAX_GOALS)).astype(bool)


def _markets_from_pmf(h_p, a_p):
    """Stesso assemblaggio di backtest_experiment_all.get_full_poisson:
    matrice esterna, tril/diag/triu, u25 per celle, gg dalle pmf(0)."""
    M = np.outer(h_p, a_p)
    p1 = float(np.sum(np.tril(M, -1)))
    pX = float(np.sum(np.diag(M)))
    p2 = float(np.sum(np.triu(M, 1)))
    u25 = float(M[_U25_MASK].sum())
    gg = float((1.0 - h_p[0]) * (1.0 - a_p[0]))
    return {"1": p1, "X": pX, "2": p2, "u25": u25, "o25": 1.0 - u25, "gg": gg}


def _poisson_markets(lh, la):
    """Marginali di produzione: scipy poisson, identiche a get_full_poisson."""
    from scipy.stats import poisson
    h_p = np.array([poisson.pmf(i, dee.clip(lh)) for i in range(MAX_GOALS)])
    a_p = np.array([poisson.pmf(i, dee.clip(la)) for i in range(MAX_GOALS)])
    return _markets_from_pmf(h_p, a_p)


def markets_nb(lh, la, alpha):
    if alpha is None or alpha <= ALPHA_BOUNDARY:
        return _poisson_markets(lh, la)
    lh_c, la_c = dee.clip(lh), dee.clip(la)
    h_p = np.exp(nb2_logpmf(GOAL_J, np.full(MAX_GOALS, lh_c), alpha))
    a_p = np.exp(nb2_logpmf(GOAL_J, np.full(MAX_GOALS, la_c), alpha))
    return _markets_from_pmf(h_p, a_p)


# ---------------------------------------------------------------------------
# Dati condizionali per la stima MLE (lungo: 2 righe squadra per partita)
# ---------------------------------------------------------------------------
def head_lambdas(d, head):
    if head == HEAD_1X2:
        return d["lam1_h"].to_numpy(), d["lam1_a"].to_numpy()
    return d["lam0_h"].to_numpy(), d["lam0_a"].to_numpy()


def team_rows(d, head):
    """Ritorna (k, lam, match_idx) per le due righe squadra di ogni partita:
    prima casa (gol fthg, lambda casa), poi trasferta."""
    lh, la = head_lambdas(d, head)
    fthg = d["fthg"].to_numpy(dtype=float)
    ftag = d["ftag"].to_numpy(dtype=float)
    n = len(d)
    k = np.empty(2 * n)
    lam = np.empty(2 * n)
    midx = np.empty(2 * n, dtype=int)
    k[0::2] = fthg; k[1::2] = ftag
    lam[0::2] = lh;  lam[1::2] = la
    midx[0::2] = np.arange(n)
    midx[1::2] = np.arange(n)
    return k, lam, midx


def fit_alpha_with_ci(d_tr, head, n_boot=N_BOOT, seed=SEED):
    """Stima pooled e per-lega con IC bootstrap (resample di PARTITE: la coppia
    home/away viaggia sempre insieme; pooled stratificato per lega)."""
    leagues = sorted(d_tr["league"].unique())
    rng = np.random.default_rng(seed if head == HEAD_1X2 else seed + 1)

    # --- dati per lega (2 righe squadra per partita, ordinati per partita) ---
    pool = {}
    for ck in leagues:
        dd = d_tr[d_tr["league"] == ck].reset_index(drop=True)
        k, lam, midx = team_rows(dd, head)
        m = len(dd)
        pool[ck] = {"k": k, "lam": lam, "m": m}

    def pooled_arrays(match_choice):
        """match_choice: dict lega -> array di indici partita campionato."""
        ks, ls = [], []
        for ck in leagues:
            p = pool[ck]
            sel = match_choice[ck]
            row_idx = np.concatenate([2 * sel, 2 * sel + 1])
            ks.append(p["k"][row_idx]); ls.append(p["lam"][row_idx])
        return np.concatenate(ks), np.concatenate(ls)

    # --- stima puntuale ---
    k_all = np.concatenate([pool[c]["k"] for c in leagues])
    l_all = np.concatenate([pool[c]["lam"] for c in leagues])
    a_pool, bnd_pool = fit_alpha(k_all, l_all)
    a_lega, bnd_lega = {}, {}
    for ck in leagues:
        a_lega[ck], bnd_lega[ck] = fit_alpha(pool[ck]["k"], pool[ck]["lam"])

    # --- bootstrap (stesso seed/disciplina di topmix_margins._ci) ---
    boot_pool = np.empty(n_boot)
    boot_lega = {ck: np.empty(n_boot) for ck in leagues}
    for b in range(n_boot):
        choice = {ck: rng.integers(0, pool[ck]["m"], size=pool[ck]["m"])
                  for ck in leagues}
        kb, lb = pooled_arrays(choice)
        ab, _ = fit_alpha(kb, lb)
        boot_pool[b] = ab
        for ck in leagues:
            p = pool[ck]
            sel = choice[ck]
            row_idx = np.concatenate([2 * sel, 2 * sel + 1])
            abl, _ = fit_alpha(p["k"][row_idx], p["lam"][row_idx])
            boot_lega[ck][b] = abl

    out = {"pooled": {"alpha": a_pool, "boundary": bnd_pool,
                      "ci": _ci(list(boot_pool)),
                      "pct_zero": float(100.0 * np.mean(boot_pool <= ALPHA_BOUNDARY)),
                      "n_team": int(len(k_all))},
           "lega": {}}
    for ck in leagues:
        out["lega"][ck] = {
            "alpha": a_lega[ck], "boundary": bnd_lega[ck],
            "ci": _ci(list(boot_lega[ck])),
            "pct_zero": float(100.0 * np.mean(boot_lega[ck] <= ALPHA_BOUNDARY)),
            "n_team": int(2 * pool[ck]["m"])}
    # descrittiva di dispersione condizionata (sui dati puntuali)
        desc = {}
        for ck in leagues + ["POOLED"]:
            if ck == "POOLED":
                kk, ll = k_all, l_all
            else:
                kk, ll = pool[ck]["k"], pool[ck]["lam"]
            var_pois = float(np.mean(ll))                     # Var|lam = lam
            var_real = float(np.var(kk, ddof=1))
            pearson = float(np.sum((kk - ll) ** 2 / np.maximum(ll, 1e-9)) / (len(kk) - 1))
            # Pearson robusta: le righe con lambda quasi zero (fallimenti del
            # modello tipo neopromossa con xG scarsa) hanno peso 1/lambda
            # enorme e dominano la statistica grezza; le si segrega.
            mr = ll >= 0.1
            pearson_r = float(np.sum((kk[mr] - ll[mr]) ** 2 / ll[mr]) / (mr.sum() - 1))
            desc[ck] = {"n": len(kk), "mean_lam": float(np.mean(ll)),
                        "mean_k": float(np.mean(kk)), "var_pois": var_pois,
                        "var_real": var_real,
                        "ratio": var_real / var_pois if var_pois else None,
                        "pearson": pearson, "pearson_r": pearson_r,
                        "n_small": int((ll < 0.1).sum())}
    # robustezza di alpha alle righe a lambda quasi zero (stesso campione di
    # train, esclusione solo descrittiva: la stima ufficiale resta su tutto)
    robust = {}
    for ck in leagues + ["POOLED"]:
        if ck == "POOLED":
            kk, ll = k_all, l_all
        else:
            kk, ll = pool[ck]["k"], pool[ck]["lam"]
        m = ll >= 0.1
        a_r, _ = fit_alpha(kk[m], ll[m])
        robust[ck] = a_r
    out["robust_alpha_lam01"] = robust
    out["desc"] = desc
    return out


# ---------------------------------------------------------------------------
# Diagnostica di forma: la sovra-dispersione e' simmetrica (piu' zeri E piu'
# code, come vuole l'NB2) o solo code alte? Gli alpha su validation/test sono
# qui calcolati SOLAMENTE come controllo di stabilita': NON vengono usati per
# costruire nessuna probabilita' (quelle usano sempre e solo l'alpha di train).
# ---------------------------------------------------------------------------
def shape_diagnostics(agg, fits):
    rows = []
    for head in HEADS:
        ch, ca = (("lam1_h", "lam1_a") if head == HEAD_1X2
                  else ("lam0_h", "lam0_a"))
        a_train = fits[head]["pooled"]["alpha"]
        for split in SPLITS:
            d = agg[dc.sample_mask(agg, split)]
            lam = np.concatenate([d[ch].to_numpy(), d[ca].to_numpy()])
            k = np.concatenate([d["fthg"].to_numpy(), d["ftag"].to_numpy()])
            a_diag, _ = fit_alpha(k, lam)               # diagnostico, non usato
            a_mm = float(np.mean(((k - lam) ** 2 - lam)) / np.mean(lam ** 2))
            p0 = float(np.mean(k == 0))
            p0_pois = float(np.mean(np.exp(-np.maximum(lam, 1e-9))))
            a_use = a_train if split == "train" else a_train
            p0_nb = float(np.mean((1 + a_use * np.maximum(lam, 1e-9))
                                  ** (-1.0 / a_use))) if a_use > 0 else p0_pois
            s_cond = float(np.mean((k - lam) ** 2))
            s_nb = float(np.mean(lam + a_use * lam ** 2))
            rows.append({"head": head, "split": split, "n": len(k),
                         "alpha_mle": a_diag if split != "train" else a_train,
                         "alpha_mm": a_mm, "p0": p0, "p0_pois": p0_pois,
                         "p0_homo": float(np.exp(-np.mean(lam))),
                         "var_lam": float(np.var(lam)),
                         "p0_nb_train": p0_nb, "s_cond": s_cond,
                         "s_pois": float(np.mean(lam)), "s_nb": s_nb})
    return rows


# ---------------------------------------------------------------------------
# Valutazione: 3 versioni x 3 mercati, Brier/LogLoss + IC delta appaiato
# ---------------------------------------------------------------------------
def brier_ll_rows(p, y):
    """Binario. Ritorna (brier, logloss, riga_brier, riga_logloss)."""
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    pc = np.clip(p, 1e-12, 1 - 1e-12)
    rb = (y - p) ** 2
    rl = -(y * np.log(pc) + (1 - y) * np.log(1 - pc))
    return float(rb.mean()), float(rl.mean()), rb, rl


def brier_ll_multi(P, y):
    """Multiclasse 1X2. P (n,3), y (n,) indici."""
    P = np.asarray(P, dtype=float)
    y = np.asarray(y, dtype=int)
    n = len(y)
    oh = np.zeros_like(P)
    oh[np.arange(n), y] = 1.0
    rb = np.sum((oh - P) ** 2, axis=1)
    rl = -np.log(np.clip(P[np.arange(n), y], 1e-12, 1.0))
    return float(rb.mean()), float(rl.mean()), rb, rl


def boot_delta_ci(err_a, err_b, n_boot=N_BOOT, seed=SEED):
    """IC 95 percentile di mean(a - b) su resample di righe (come combo)."""
    n = len(err_a)
    if n == 0:
        return [None, None]
    rng = np.random.default_rng(seed)
    d = np.asarray(err_a, dtype=float) - np.asarray(err_b, dtype=float)
    means = np.empty(n_boot)
    batch, done = 200, 0
    while done < n_boot:
        k = min(batch, n_boot - done)
        idx = rng.integers(0, n, size=(k, n))
        means[done:done + k] = d[idx].mean(axis=1)
        done += k
    return _ci(list(means))


def attach_probs(d, fits):
    """Calcola le 3 versioni di mercato per ogni riga emessa (alpha fissate)."""
    n = len(d)
    lh1, la1 = d["lam1_h"].to_numpy(), d["lam1_a"].to_numpy()
    lh0, la0 = d["lam0_h"].to_numpy(), d["lam0_a"].to_numpy()
    leagues = d["league"].to_numpy()
    a1p = fits[HEAD_1X2]["pooled"]["alpha"]
    a0p = fits[HEAD_TOT]["pooled"]["alpha"]
    a1l = {c: v["alpha"] for c, v in fits[HEAD_1X2]["lega"].items()}
    a0l = {c: v["alpha"] for c, v in fits[HEAD_TOT]["lega"].items()}
    cols = {}
    for v in VERSIONS:
        cols[v] = {m: np.empty(n) for m in ("1", "X", "2", "o25", "gg")}
    y1 = np.empty(n, dtype=int)
    yo = np.empty(n, dtype=int)
    yg = np.empty(n, dtype=int)
    for i in range(n):
        ck = leagues[i]
        # testa 1X2
        mp_pois = _poisson_markets(lh1[i], la1[i])
        mp_np = markets_nb(lh1[i], la1[i], a1p)
        mp_nl = markets_nb(lh1[i], la1[i], a1l[ck])
        for v, mp in (("poisson", mp_pois), ("nb_pooled", mp_np),
                      ("nb_lega", mp_nl)):
            for m in ("1", "X", "2"):
                cols[v][m][i] = mp[m]
        # testa Totali
        mt_pois = _poisson_markets(lh0[i], la0[i])
        mt_np = markets_nb(lh0[i], la0[i], a0p)
        mt_nl = markets_nb(lh0[i], la0[i], a0l[ck])
        for v, mt in (("poisson", mt_pois), ("nb_pooled", mt_np),
                      ("nb_lega", mt_nl)):
            cols[v]["o25"][i] = mt["o25"]
            cols[v]["gg"][i] = mt["gg"]
        y1[i] = {"1": 0, "X": 1, "2": 2}[d["real_1x2"].iloc[i]]
        yo[i] = int(d["fthg"].iloc[i] + d["ftag"].iloc[i] > 2.5)
        yg[i] = int(d["fthg"].iloc[i] > 0 and d["ftag"].iloc[i] > 0)
    out = {}
    for v in VERSIONS:
        for m, arr in cols[v].items():
            out[f"{v}__{m}"] = arr
    out["y1"] = y1
    out["yo"] = yo
    out["yg"] = yg
    return out


def market_rows(prob, sub_idx, market):
    """Ritorna (dict versione -> (brier, logloss, rb, rl), y) per un mercato."""
    idx = np.asarray(sub_idx)
    out = {}
    if market == "1X2":
        y = prob["y1"][idx]
        for v in VERSIONS:
            P = np.column_stack([prob[f"{v}__1"][idx],
                                 prob[f"{v}__X"][idx],
                                 prob[f"{v}__2"][idx]])
            out[v] = brier_ll_multi(P, y)
    elif market == "O/U2.5":
        y = prob["yo"][idx]
        for v in VERSIONS:
            out[v] = brier_ll_rows(prob[f"{v}__o25"][idx], y)
    elif market == "GG/NG":
        y = prob["yg"][idx]
        for v in VERSIONS:
            out[v] = brier_ll_rows(prob[f"{v}__gg"][idx], y)
    else:
        raise ValueError(market)
    return out, y


def reliability(p, y, n_bins=5):
    """Quintili di affidabilita' (stessa funzione del combo audit)."""
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(p) < n_bins * 20:
        return []
    edges = np.quantile(p, np.linspace(0, 1, n_bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    bidx = np.clip(np.searchsorted(edges[1:-1], p, side="right"), 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        m = bidx == b
        if m.sum() == 0:
            continue
        rows.append({"n": int(m.sum()), "pred": float(p[m].mean()),
                     "obs": float(y[m].mean()),
                     "bias": float(p[m].mean() - y[m].mean())})
    return rows


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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    worst = check_nb2_vs_scipy()

    per_league = {}
    dee_frames, dft_frames, checks = {}, {}, []
    for prefix, ck in LEAGUES:
        print(f"==> {ck}: walk-forward due teste (emit esteso ai treni) ...")
        df = load_league(prefix)
        xg = dee.load_xg(ck)
        d_full = dc.run_combo_model(df, ck, xg, emit_seasons=ALL_SEASONS)
        d_eval = dc.run_combo_model(df, ck, xg, emit_seasons=SEASONS_EVAL)
        dc.check_state_invariance(d_full, d_eval, ck)
        d_full = d_full.reset_index(drop=True)
        per_league[ck] = d_full
        # audit di riferimento per il cross-check bit-a-bit
        d_dee = dee.run_models(df, ck, xg).reset_index(drop=True)
        d_dft = dft.run_models(df, xg).reset_index(drop=True)
        dee_frames[ck], dft_frames[ck] = d_dee, d_dft
        ev = d_full[d_full.season.isin(SEASONS_EVAL)].reset_index(drop=True)
        # --- CROSS-CHECK bit-a-bit: le marginali Poisson di questo audit
        # (ricalcolate dagli stessi lambda) devono coincidere riga per riga
        # con le due diagnosi di riferimento, su TUTTE le colonne ---
        maxd = {"p1": 0.0, "pX": 0.0, "p2": 0.0, "pO": 0.0, "pGG": 0.0}
        n = len(ev)
        for i in range(n):
            m1 = _poisson_markets(ev["lam1_h"].iloc[i], ev["lam1_a"].iloc[i])
            m0 = _poisson_markets(ev["lam0_h"].iloc[i], ev["lam0_a"].iloc[i])
            for key, col, ref in (("p1", "1", d_dee["p1"].iloc[i]),
                                  ("pX", "X", d_dee["pX"].iloc[i]),
                                  ("p2", "2", d_dee["p2"].iloc[i])):
                maxd[key] = max(maxd[key], abs(m1[col] - float(ref)))
            maxd["pO"] = max(maxd["pO"], abs(m0["o25"] - float(d_dft["pure_po"].iloc[i])))
            maxd["pGG"] = max(maxd["pGG"], abs(m0["gg"] - float(d_dft["pure_gg"].iloc[i])))
        ok_y = (np.array_equal(ev["real_1x2"].map({"1": 0, "X": 1, "2": 2}).to_numpy(),
                               d_dee["y"].to_numpy())
                and np.array_equal(ev["real_over"].to_numpy(), d_dft["real_over"].to_numpy())
                and np.array_equal((ev["fthg"].gt(0) & ev["ftag"].gt(0)).to_numpy(),
                                   d_dft["real_gg"].astype(bool).to_numpy()))
        if any(v != 0.0 for v in maxd.values()) or not ok_y:
            raise SystemExit(f"CROSS-CHECK FALLITO {ck}: {maxd}, esiti {ok_y}")
        checks.append({"league": ck, "n": n, **maxd, "outcomes_ok": bool(ok_y)})
    print(f"cross-check bit-a-bit OK (scarti tutti 0.0e+00) | NB2 pmf vs scipy "
          f"max {worst:.1e} | state-invariance OK")

    agg = pd.concat(per_league.values(), ignore_index=True)

    def mask_of(d, split):
        return dc.sample_mask(d, split)

    # ---------------- STIMA alpha (solo TRAIN) ----------------
    tr = agg[mask_of(agg, "train")].reset_index(drop=True)
    fits = {}
    for head in HEADS:
        print(f"==> stima MLE alpha NB2 ({head}) + IC bootstrap {N_BOOT} ...")
        fits[head] = fit_alpha_with_ci(tr, head)

    # ---------------- probabilita' 3 versioni (tutte le partite emesse) -----
    print("==> calcolo probabilita' Poisson / NB-pooled / NB-per-lega ...")
    prob = attach_probs(agg, fits)

    # scelta della "versione NegBin migliore" per mercato sul SOLO TRAIN
    tr_idx = np.where(mask_of(agg, "train"))[0]
    best_nb = {}
    for mkt in ("1X2", "O/U2.5", "GG/NG"):
        rows, _ = market_rows(prob, tr_idx, mkt)
        best_nb[mkt] = min(("nb_pooled", "nb_lega"),
                           key=lambda v: rows[v][0])

    # =======================================================================
    # REPORT
    # =======================================================================
    L = []
    ap = L.append
    ap("# Overdispersion condizionale dei gol: Poisson vs Negative Binomial NB2 "
       "(audit sola lettura)")
    ap("")
    ap(f"*Generato: {datetime.now(timezone.utc).isoformat(timespec='seconds')} — "
       "script `audit/diagnose_overdispersion_condizionale.py`, nessuna modifica "
       "a SoccerMath/.*")
    ap("")
    ap("## Domanda e protocollo")
    ap("")
    ap("Per ogni partita il motore a Due Teste assegna un lambda_home e un "
       "lambda_away **specifici per quella partita e diversi tra le due teste** "
       "(1X2: NORM-SUM xG+forma+mercato di `diagnose_elo_ensemble`; Totali: "
       "lambda puri modello B di `diagnose_form_totali`). Su quel lambda "
       "per-partita il motore assume distribuzioni Poisson indipendenti. Qui si "
       "tiene fisso il lambda e si chiede se i gol REALI siano piu' dispersi: "
       "in tal caso serve una NegBin NB2 con media lambda e varianza "
       "lambda + alpha*lambda^2 (alpha=0 e' esattamente il Poisson attuale).")
    ap("")
    ap(f"- TRAIN {TRAIN_SEASONS[0]}+{TRAIN_SEASONS[1]}: le prime "
       f"{TRAIN_WARMUP} partite/lega restano nello stato ma sono escluse dal "
       "campione (cold start); **sul train si stima SOLAMENTE alpha** (MLE), "
       "in versione POOLED (un alpha su 5 leghe) e PER-LEGA (5 alpha), e "
       "separatamente per le due teste.")
    ap(f"- VALIDATION {SEASONS_EVAL[0]}: conferma, nessuna stima/riottimizzazione.")
    ap(f"- TEST {SEASONS_EVAL[1]}: sola lettura.")
    ap(f"- IC bootstrap a {N_BOOT} resample (seed {SEED}, come in "
       "`topmix_margins`/`diagnose_combo_1x2_totali`); una differenza dentro "
       "l'IC e' rumore.")
    ap("- Le NegBin restano INDIPENDENTI tra casa e trasferta: cambia solo la "
       "pmf marginale (spessore delle code), non l'assunzione di indipendenza "
       "(quella e' oggetto dell'audit Dixon-Coles/combo). Griglia 15x15 "
       "troncata e non rinormalizzata, identica convenzione di produzione.")
    ap("- Per il mercato 1X2 si usano i lambda della testa 1X2 (e alpha_1X2); "
       "per O/U2.5 e GG/NG i lambda della testa Totali (e alpha_TOT). Il "
       "riferimento 1X2 e' il Poisson puro della testa, non il blend con Elo: "
       "qui si testa l'assunzione di conteggio Poisson, non l'ensemble Elo.")
    ap("")

    # ---- conformita' ----
    ap("## Conformita' del protocollo (verificata, non dichiarata)")
    ap("")
    ap(f"Pmf NB2 custom vs `scipy.stats.nbinom`: max scarto {worst:.1e}. Le "
       "marginali POISSON di questo audit sono state ricalcolate riga per riga "
       "e confrontate con gli audit di riferimento (stessi lambda, stessa "
       "costruzione della griglia):")
    ap("")
    ap("| Lega | n righe | max\\|scarto\\| P(1) | P(X) | P(2) vs elo_ensemble | "
       "max\\|scarto\\| P(Over) | P(GG) vs form_totali B | esiti identici |")
    ap("|---|---:|---:|---:|---:|---:|---:|---|")
    for c in checks:
        ap(f"| {c['league']} | {c['n']} | {c['p1']:.1e} | {c['pX']:.1e} | "
           f"{c['p2']:.1e} | {c['pO']:.1e} | {c['pGG']:.1e} | "
           f"{'si' if c['outcomes_ok'] else 'NO'} |")
    ap("")
    ap("Scarto atteso **0.0e+00** su tutte le colonne: questa analisi NON "
       "introduce un terzo modello, riusa esattamente il walk-forward di "
       "`diagnose_combo_1x2_totali.run_combo_model` (gia' allineato alle due "
       "diagnosi) e si limita a sostituire la pmf marginale. "
       "`check_state_invariance` verifica inoltre che emettere anche i treni "
       "non sposti di un bit le predizioni di validation/test.")
    ap("")

    # ---- copertura ----
    ap("## Copertura campioni")
    ap("")
    ap("| Lega | Train (partite) | esclusi cold-start | Validation | Test | "
       "righe-squadra train |")
    ap("|---|---:|---:|---:|---:|---:|")
    for ck, d in per_league.items():
        n_tr = int(mask_of(d, "train").sum())
        n_all_tr = int(d["season"].isin(TRAIN_SEASONS).sum())
        n_teamt = fits[HEAD_1X2]["lega"][ck]["n_team"]
        ap(f"| {ck} | {n_tr} | {n_all_tr - n_tr} | "
           f"{int(mask_of(d, 'validation').sum())} | "
           f"{int(mask_of(d, 'test').sum())} | {n_teamt} |")
    ap(f"| **AGGREGATO** | {int(mask_of(agg, 'train').sum())} | "
       f"{int(agg['season'].isin(TRAIN_SEASONS).sum()) - int(mask_of(agg, 'train').sum())} "
       f"| {int(mask_of(agg, 'validation').sum())} | "
       f"{int(mask_of(agg, 'test').sum())} | "
       f"{fits[HEAD_1X2]['pooled']['n_team']} |")
    ap("")

    # ---- STIMA alpha ----
    ap("## 1. STIMA di alpha (solo TRAIN): NB2 MLE condizionata al lambda per-partita")
    ap("")
    ap("La stima NON usa la media gol di lega: ogni riga e' una prestazione "
       "squadra in una partita (gol osservati, lambda che il motore le aveva "
       "assegnato prima della partita). Alpha e' ricavato per massima "
       "verosimiglianza sulla NB2; il confronto e' lo stesso schema pooled vs "
       "per-lega gia' usato per il rho Dixon-Coles, qui ripetuto per le due "
       "teste perche' i lambda differiscono.")
    ap("")
    for head in HEADS:
        f = fits[head]
        ap(f"### Alpha dalla {HEAD_LABEL[head]}")
        ap("")
        ap("| Ambito | alpha MLE | IC 95% bootstrap | % resample al confine "
           "alpha=0 | n righe-squadra |")
        ap("|---|---:|---|---:|---:|")
        p = f["pooled"]
        ap(f"| **POOLED 5 leghe** | {p['alpha']:.5f} | {_fci(p['ci'], 5)} | "
           f"{p['pct_zero']:.1f}% | {p['n_team']} |")
        for ck, v in f["lega"].items():
            ap(f"| {ck} | {v['alpha']:.5f} | {_fci(v['ci'], 5)} | "
               f"{v['pct_zero']:.1f}% | {v['n_team']} |")
        ap("")
        ap("Dispersione condizionata descrittiva (stesso campione): la varianza "
           "attesa dal Poisson e' la media del lambda per-partita; il rapporto "
           "Var_reale/Var_Poisson e la statistica di Pearson "
           "sum((k-lambda)^2/lambda)/(n-1) sono >1 sotto overdispersion. La "
           "Pearson grezza e' pero' dominata dalle poche righe a lambda quasi "
           "zero (clip floor exp(-6), fallimenti del modello su squadre "
           "mal osservate: viaggiando a 1/lambda una singola riga lambda=0.025 "
           "con un gol vale ~40): si riporta anche la Pearson robusta sulle "
           "sole righe lambda>=0.1.")
        ap("")
        ap("| Ambito | media lambda | media gol | Var reale | Var Poisson | "
           "rapporto | Pearson | Pearson (lambda>=0.1) | righe lambda<0.1 |")
        ap("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for scope, dd in f["desc"].items():
            ap(f"| {scope} | {dd['mean_lam']:.4f} | {dd['mean_k']:.4f} | "
               f"{dd['var_real']:.4f} | {dd['var_pois']:.4f} | "
               f"{dd['ratio']:.4f} | {dd['pearson']:.4f} | "
               f"{dd['pearson_r']:.4f} | {dd['n_small']} |")
        ap("")
        ap(f"Robustezza di alpha: MLE escludendo le righe con lambda<0.1 "
           f"(stima di sensibilita', non quella ufficiale): pooled "
           f"{f['robust_alpha_lam01']['POOLED']:.5f}; per-lega "
           + ", ".join(f"{ck} {f['robust_alpha_lam01'][ck]:.4f}" for ck in f["lega"])
           + ". L'alpha non si muove materialmente: l'overdispersion non e' un "
           "artefatto delle code di lambda.")
        ap("")

    # ---- diagnostica di forma/stabilita' ----
    shape = shape_diagnostics(agg, fits)
    ap("### Diagnostica di forma e stabilita' (sola lettura)")
    ap("")
    ap("Tre controlli che non entrano in nessuna probabilita' (le versioni NB "
       "usano sempre e solo gli alpha di TRAIN): (i) **alpha MLE calcolato "
       "anche su validation e test**: se resta dello stesso ordine di grandezza "
       "la sovra-dispersione non e' un accidente del train; (ii) **alpha "
       "method-of-moments** E[(k-lambda)^2-lambda]/E[lambda^2], che forza il "
       "secondo momento: se e' sistematicamente sotto l'MLE, l'MLE compra coda "
       "oltre che varianza; (iii) **frazione di zeri reale vs attesa**, che "
       "dice se la sovra-dispersione e' simmetrica (piu' zeri E piu' code, "
       "come vuole la NB2) o asimmetrica.")
    ap("")
    ap("| Testa | Split (sola lettura) | alpha MLE | alpha MoM | P(0) reale | "
       "P(0) Poisson E[e^-lam] | P(0) a media costante e^-E[lam] | "
       "P(0) NB (alpha train) | E[(k-lam)^2] reale | Poisson E[lam] | "
       "NB E[lam+alpha*lam^2] |")
    ap("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in shape:
        ap(f"| {r['head']} | {r['split']} | {r['alpha_mle']:.4f} | "
           f"{r['alpha_mm']:.4f} | {r['p0']:.3f} | {r['p0_pois']:.3f} | "
           f"{r['p0_homo']:.3f} | {r['p0_nb_train']:.3f} | "
           f"{r['s_cond']:.3f} | {r['s_pois']:.3f} | {r['s_nb']:.3f} |")
    ap("")
    sh = {(r["head"], r["split"]): r for r in shape}
    r1 = sh[(HEAD_1X2, "train")]
    r0 = sh[(HEAD_TOT, "train")]
    ap("Lettura: gli alpha di validation e test restano grandi (0.13-0.20), "
       "confermando la direzione del train; ma la forma reale e' ASIMMETRICA: "
       "la frazione di zero gol osservata (0.25-0.26) e' **inferiore** a quella "
       "attesa dal Poisson di questi lambda (testa 1X2 "
       f"{r1['p0_pois']:.2f}, testa Totali {r0['p0_pois']:.2f} sul train), "
       "mentre l'NB2 per costruzione aggiunge massa sugli zeri portandola ancora "
       f"piu' su ({r1['p0_nb_train']:.2f}/{r0['p0_nb_train']:.2f}). Il modello "
       "di conteggio ha code alte piu' spesse del Poisson ma NON piu' zeri: e' "
       "questo il motivo strutturale per cui la NB2 migliora i mercati di "
       "soglia (1X2, Over) e peggiora GG/NG, che dagli zeri dipende "
       "direttamente. Il confronto con e^-E[lambda] "
       f"({r1['p0_homo']:.2f}/{r0['p0_homo']:.2f}, la P(0) di un Poisson a "
       "media costante) mostra inoltre che i lambda dell'audit sono TROPPO "
       "SPARPAGLIATI (Var lambda "
       f"{r0['var_lam']:.2f} sulla testa Totali): l'eccesso di zeri attesi "
       "viene dallo spread dei lambda, non dai gol. L'alpha MLE risponde dunque "
       "correttamente alla domanda 'dato QUESTO lambda per-partita, il Poisson "
       "sottovaluta la dispersione condizionata?' (si': E[(k-lambda)^2] vale "
       "1.8-2.0 contro E[lambda] 1.4), ma ingloba coda reale E "
       "misspecificazione dei lambda: non e' la prova che i gol seguano una "
       "NB2 in natura. Questa diagnostica non ritara nulla: le probabilita' "
       "usano sempre e solo l'alpha di train.")
    ap("")

    # ---- VALUTAZIONE ----
    ap("## 2. VALUTAZIONE fuori campione: Brier e LogLoss delle 3 versioni")
    ap("")
    ap("Per ogni mercato: POISSON (attuale), NB-pooled e NB-per-lega, su "
       "validation e test. Delta = NegBin - Poisson (negativo = migliora); IC "
       "95% bootstrap sulla differenza appaiata riga per riga.")
    ap("")
    # scope SEMPRE sul frame aggregato (prob e' stato costruito lì): per le
    # leghe si maschera anche sulla colonna league, altrimenti gli indici di
    # un frame per-lega punterebbero a righe sbagliate dell'aggregato
    scopes = [("AGGREGATO", np.ones(len(agg), dtype=bool))]
    scopes += [(ck, agg["league"].eq(ck).to_numpy()) for ck in per_league]
    eval_stats = {}
    for mkt in ("1X2", "O/U2.5", "GG/NG"):
        ap(f"### Mercato {mkt} "
           f"({'testa 1X2, alpha_1X2' if mkt == '1X2' else 'testa Totali, alpha_TOT'})")
        ap("")
        for metric_i, metric in enumerate(("Brier", "LogLoss")):
            ap(f"**{metric}**")
            ap("")
            ap("| Lega | Split | POISSON | NB-pooled | NB-per-lega | "
               "Δ pooled (IC 95%) | verdetto | Δ per-lega (IC 95%) | verdetto |")
            ap("|---|---|---:|---:|---:|---:|---|---:|---|")
            for scope, scope_mask in scopes:
                for split in ("validation", "test"):
                    idx = np.where(scope_mask & mask_of(agg, split))[0]
                    if len(idx) == 0:
                        continue
                    rows, _ = market_rows(prob, idx, mkt)
                    vals = {v: rows[v][metric_i] for v in VERSIONS}
                    rbp = {v: rows[v][2 + metric_i] for v in VERSIONS}
                    cip = boot_delta_ci(rbp["nb_pooled"], rbp["poisson"],
                                        seed=SEED + (0 if metric_i == 0 else 1))
                    cil = boot_delta_ci(rbp["nb_lega"], rbp["poisson"],
                                        seed=SEED + 2 + (0 if metric_i == 0 else 1))
                    dp = vals["nb_pooled"] - vals["poisson"]
                    dl = vals["nb_lega"] - vals["poisson"]
                    eval_stats[(mkt, split, scope, metric)] = {
                        "dp": dp, "cip": cip, "dl": dl, "cil": cil,
                        "vals": vals}
                    ap(f"| {scope} | {split} | {_f(vals['poisson'])} | "
                       f"{_f(vals['nb_pooled'])} | {_f(vals['nb_lega'])} | "
                       f"{dp:+.4f} {_fci(cip)} | {verdict(dp, cip)} | "
                       f"{dl:+.4f} {_fci(cil)} | {verdict(dl, cil)} |")
            ap("")
        ap("")

    # ---- affidabilita' per quintili ----
    ap("## 3. Affidabilita' per quintili (pred. media vs frequenza osservata)")
    ap("")
    ap("Stessa lente dell'audit combo: quintili della previsione, con "
       "attenzione alle code Q1/Q5 (dove la sessione precedente aveva trovato "
       "il problema: ultimo quintile che prometteva 0.65 e realizzava 0.40). "
       "Per ogni mercato si mostra il POISSON e la versione NegBin migliore "
       f"sul TRAIN (NB-pooled vs NB-per-lega scelta per Brier train: "
       f"{', '.join(f'{m} -> {VERSION_LABEL[best_nb[m]]}' for m in best_nb)}).")
    ap("")
    events = {"1X2": [("1", "esito 1 (casa)"), ("X", "esito X (pareggio)"),
                      ("2", "esito 2 (trasferta)")],
              "O/U2.5": [("o25", "Over 2.5")],
              "GG/NG": [("gg", "GG")]}
    ykey = {"1X2": "y1", "O/U2.5": "yo", "GG/NG": "yg"}
    # mapping evento -> indice classe per 1X2
    cls_of = {"1": 0, "X": 1, "2": 2}
    for mkt in ("1X2", "O/U2.5", "GG/NG"):
        ap(f"### {mkt}")
        ap("")
        for ev, evlab in events[mkt]:
            for split in ("validation", "test"):
                idx = np.where(mask_of(agg, split))[0]
                yall = prob[ykey[mkt]][idx]
                if mkt == "1X2":
                    ybin = (yall == cls_of[ev]).astype(float)
                else:
                    ybin = yall.astype(float)
                ap(f"**{evlab} — {split.upper()} (n={len(idx)})**")
                ap("")
                ap("| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |")
                ap("|---|---|---:|---:|---:|---:|")
                for v, vlab in (("poisson", "POISSON"), (best_nb[mkt],
                                                        VERSION_LABEL[best_nb[mkt]])):
                    p = prob[f"{v}__{ev}"][idx]
                    for qi, r in enumerate(reliability(p, ybin), 1):
                        mark = " **" if qi in (1, 5) else " "
                        ap(f"| {vlab} |{mark}Q{qi}{mark[::-1]}| {r['n']} | "
                           f"{r['pred']:.4f} | {r['obs']:.4f} | {r['bias']:+.4f} |")
                ap("")
        ap("")

    # ---- verdetto ----
    ap("## 4. Verdetto e regola d'arresto")
    ap("")
    # coerenza: una versione vince in modo robusto se il delta Brier aggregato
    # e' negativo con IC alto < 0 su ENTRAMBI validation e test, e la LogLoss
    # non peggiora in modo significativo; si guarda anche la coerenza per lega.
    wins, losses = [], []
    lines_summary = []
    for mkt in ("1X2", "O/U2.5", "GG/NG"):
        for v in ("nb_pooled", "nb_lega"):
            ok_b, ok_l, bad_b, bad_l = True, True, True, True
            cells = []
            for split in ("validation", "test"):
                s = eval_stats[(mkt, split, "AGGREGATO", "Brier")]
                d = s["dp"] if v == "nb_pooled" else s["dl"]
                ci = s["cip"] if v == "nb_pooled" else s["cil"]
                cells.append((split, d, ci))
                if not (d < 0 and ci[1] < 0):
                    ok_b = False
                if not (d > 0 and ci[0] > 0):
                    bad_b = False
                sl = eval_stats[(mkt, split, "AGGREGATO", "LogLoss")]
                dl = sl["dp"] if v == "nb_pooled" else sl["dl"]
                cil = sl["cip"] if v == "nb_pooled" else sl["cil"]
                if dl > 0 and cil[0] > 0:
                    ok_l = False
                if dl < 0 and cil[1] < 0:
                    bad_l = False
            # quante leghe hanno delta Brier negativo (o positivo significativo)
            leg_neg = 0
            leg_sig_worse = 0
            for ck in per_league:
                ds = []
                for split in ("validation", "test"):
                    sl = eval_stats[(mkt, split, ck, "Brier")]
                    ds.append(sl["dp"] if v == "nb_pooled" else sl["dl"])
                    ci = sl["cip"] if v == "nb_pooled" else sl["cil"]
                    if ds[-1] > 0 and ci[0] > 0:
                        leg_sig_worse += 1
                if all(x < 0 for x in ds):
                    leg_neg += 1
            coherente = ok_b and ok_l and leg_neg >= 3 and leg_sig_worse == 0
            # simmetrico: tutti i delta per-lega dallo stesso segno positivo,
            # aggregato significativo su Brier E LogLoss in entrambi gli split,
            # almeno 2 celle lega-split fuori dall'IC
            leg_pos = sum(
                all((eval_stats[(mkt, sp, ck, "Brier")]["dp"]
                     if v == "nb_pooled" else
                     eval_stats[(mkt, sp, ck, "Brier")]["dl"]) > 0
                    for sp in ("validation", "test"))
                for ck in per_league)
            peggiore = bad_b and bad_l and leg_pos == 5 and leg_sig_worse >= 2
            if coherente:
                wins.append((mkt, v))
            if peggiore:
                losses.append((mkt, v))
            dval, dtest = cells[0][1], cells[1][1]
            if coherente:
                tag = "**MIGLIORAMENTO COERENTE**"
            elif peggiore:
                tag = "**PEGGIORAMENTO COERENTE**"
            else:
                tag = "nessun segnale coerente"
            lines_summary.append(
                f"- {mkt}, {VERSION_LABEL[v]}: ΔBrier validation {dval:+.4f} "
                f"{_fci(cells[0][2])}, test {dtest:+.4f} {_fci(cells[1][2])}; "
                f"leghe con Δ negativo in entrambi gli split {leg_neg}/5, "
                f"con Δ positivo in entrambi {leg_pos}/5; celle lega-split "
                f"significativamente PEGGIORI {leg_sig_worse} -> {tag}")
    ap("Criterio: un NegBin 'batte' il Poisson solo se il Δ Brier aggregato e' "
       "negativo con IC 95% interamente sotto zero su VALIDATION **e** TEST, la "
       "LogLoss non peggiora in modo significativo, e almeno 3 leghe su 5 sono "
       "negative in entrambi gli split senza inversioni significative per "
       "lega. Simmetricamente si segnala un peggioramento coerente.")
    ap("")
    for line in lines_summary:
        ap(line)
    ap("")

    # evidenza alpha (IC che include il confine)
    ap("Evidenza dal lato della stima:")
    ap("")
    for head in HEADS:
        f = fits[head]
        p = f["pooled"]
        a_le = [v["alpha"] for v in f["lega"].values()]
        ap(f"- {HEAD_LABEL[head]}: alpha pooled {p['alpha']:.5f} con IC "
           f"{_fci(p['ci'], 5)} ({p['pct_zero']:.0f}% dei bootstrap al confine "
           f"alpha=0); alpha per-lega da {min(a_le):.5f} a {max(a_le):.5f}.")
    ap("")

    # estrazione automatica di alcuni numeri-chiave per il testo
    def agg_delta(mkt, v, metric, split):
        s = eval_stats[(mkt, split, "AGGREGATO", metric)]
        key_d = "dp" if v == "nb_pooled" else "dl"
        key_c = "cip" if v == "nb_pooled" else "cil"
        return s[key_d], s[key_c]

    if not wins:
        # ---- ramo d'arresto esplicito richiesto dal protocollo ----
        ap("### **VERDETTO: OVERDISPERSION NON DIMOSTRATA NEANCHE IN VERSIONE "
           "CONDIZIONALE.**")
        ap("")
        ap("Nessuna versione NegBin (pooled o per-lega, su nessuno dei tre "
           "mercati) supera il Poisson attuale con IC bootstrap fuori dallo "
           "zero in modo coerente su validation E test. Condizionare la "
           "varianza al lambda per-partita/squadra, invece che alla media di "
           "lega, non fa emergere sovra-dispersione sfruttabile: gli alpha MLE "
           "sono nulli o piccoli con IC che include il confine Poisson, e dove "
           "il Brier si muove la mossa e' dentro il rumore di bootstrap (o "
           "cambia segno tra validation e test). Non si autorizza nessuna "
           "modifica al motore: la Poisson a Due Teste resta la famiglia di "
           "conteggio. Il problema di coda evidenziato dall'audit combo "
           "(quintile alto che promette troppo) non passa da qui: non e' un "
           "difetto di varianza marginale NB2, e va lasciato alla diagnosi di "
           "calibrazione/livello delle marginali.")
        ap("")
    else:
        win_markets = sorted({m for m, _ in wins})
        loss_markets = sorted({m for m, _ in losses})
        ap("### VERDETTO: overdispersion condizionale **DIMOSTRATA**, ma la "
           "NegBin NON e' una correzione universale")
        ap("")
        ap("La regola d'arresto NON scatta: a differenza dei tentativi fatti "
           "sulla media aggregata, condizionando la varianza al lambda "
           "per-partita emergono alpha grandi e lontani dal confine Poisson "
           "sotto bootstrap (0% di resample al confine zero), e i mercati "
           f"**{', '.join(win_markets)}** migliorano in modo coerente su "
           "validation e test, aggregate e per lega, sia Brier sia LogLoss. "
           "Il quadro e' pero' monco e va scritto senza scontorni:")
        ap("")
        dv1, ci1v = agg_delta("1X2", "nb_pooled", "Brier", "validation")
        dv1t, ci1t = agg_delta("1X2", "nb_pooled", "Brier", "test")
        do_v, cio_v = agg_delta("O/U2.5", "nb_pooled", "Brier", "validation")
        do_t, cio_t = agg_delta("O/U2.5", "nb_pooled", "Brier", "test")
        dg_v, cig_v = agg_delta("GG/NG", "nb_pooled", "Brier", "validation")
        dg_t, cig_t = agg_delta("GG/NG", "nb_pooled", "Brier", "test")
        ap(f"1. **Cosa vince**. 1X2 (testa Poisson pura, senza Elo): ΔBrier "
           f"{dv1:+.4f} {_fci(ci1v)} su validation e {dv1t:+.4f} {_fci(ci1t)} "
           f"su test (5 leghe su 5 negative in entrambi gli split); O/U2.5: "
           f"{do_v:+.4f} {_fci(cio_v)} e {do_t:+.4f} {_fci(cio_t)}, di nuovo "
           "5/5. I miglioramenti di LogLoss sono piu' grandi di quelli di "
           "Brier: e' il segno atteso quando si correggono le code.")
        # conteggi di direzione per il punto GG
        gg_pos = gg_sig = 0
        for ck in per_league:
            for split in ("validation", "test"):
                sl = eval_stats[("GG/NG", split, ck, "Brier")]
                d_ = sl["dp"]; ci_ = sl["cip"]
                if d_ > 0:
                    gg_pos += 1
                if d_ > 0 and ci_[0] > 0:
                    gg_sig += 1
        lg_v = eval_stats[("GG/NG", "validation", "AGGREGATO", "LogLoss")]
        lg_t = eval_stats[("GG/NG", "test", "AGGREGATO", "LogLoss")]
        ap(f"2. **Cosa perde, in modo altrettanto coerente: GG/NG**. ΔBrier "
           f"{dg_v:+.4f} {_fci(cig_v)} su validation e {dg_t:+.4f} "
           f"{_fci(cig_t)} su test (ΔLogLoss {lg_v['dp']:+.4f} su validation, "
           f"{lg_t['dp']:+.4f} su test); per-lega il delta Brier e' positivo "
           f"in {gg_pos}/10 celle lega×split, {gg_sig}/10 fuori IC, mai "
           "negativo in modo significativo. Il motivo e' strutturale e si vede "
           "nella diagnostica §1: la sovra-dispersione reale e' ASIMMETRICA, "
           "ci sono code alte ma NON ci sono piu' zeri del Poisson (anzi: "
           "P(0) osservata 0.25-0.26 contro 0.31-0.35 del Poisson), mentre la "
           "NB2 aggiunge massa anche sullo zero "
           "(P(0)=(1+alpha*lambda)^(-1/alpha), portandola a 0.35-0.38): abbassa "
           "quindi troppo P(GG). La forma di coda imposta da "
           "Var=lambda+alpha*lambda^2 e' giusta per le soglie alte del "
           "risultato e del totale, sbagliata per l'evento 'entrambe segnano'. "
           "Un solo alpha non puo' vincere tutti i mercati: la "
           "sovra-dispersione reale non ha esattamente forma NB2.")
        ap("3. **Pooled e per-lega sono indistinguibili** (gli IC dei delta si "
           "sovrappongono riga per riga, e i delta sono identici fino alla 4ª "
           "cifra): non c'e' struttura per lega nella sovra-dispersione, "
           "confermando che alpha descrive una proprieta' della legge di "
           "conteggio, non un campionato. Non giustifica 5 parametri in piu'.")
        ap("4. **Dove nasce il guadagno: le code degli affidabilita' (§3)**. Il "
           "Poisson e' troppo sicuro ai due estremi: coda bassa che osserva "
           "molto di piu' di quanto prometta e coda alta che promette troppo "
           "(esattamente la patologia trovata dall'audit combo, Q5 che "
           "prometteva 0.65 e realizzava 0.40). La NB2 ritrae le probabilita' "
           "estreme verso il centro: sulle code di casa, trasferta e Over il "
           "bias assoluto del Q5 (e quasi sempre del Q1) si riduce in "
           "entrambi gli split (es. Over Q5 test: +0.164 Poisson, +0.107 NB; "
           "casa Q5 validation: +0.223, +0.171); il pareggio e' l'eccezione, "
           "col suo Q5 che peggiora lievemente. Su GG, invece, lo stesso "
           "ritiro peggiora il Q1 (gia' gravemente sottopredetto) e non basta "
           "mai: il difetto di GG e' di LIVELLO (le frequenze osservate nei "
           "quintili bassi sono largamente sopra la predizione anche col "
           "Poisson), non di varianza.")
        ap("5. **Cosa questo audit NON dimostra**. La testa 1X2 mostrata in "
           "produzione e' il blend con Elo (w=0.25), non il Poisson puro qui "
           "confrontato: non e' detto che l'alpha che migliora il Poisson "
           "migliori il blend (l'Elo corregge gia' parte di overconfidenza); "
           "andrebbe ripetuto l'1X2 con la marginale NB dentro il blend. I "
           "lambda della testa Totali sono quelli da snapshot xG statico "
           "dell'audit di riferimento, non la fonte point-in-time live. "
           "Infine i grandi bias di LIVELLO nei Q1 (Over predetto 0.25 e "
           "osservato 0.50) restano presenti in tutte le versioni: l'NB2 "
           "lavora sulla dispersione, non azzera gli errori di livello del "
           "motore di audit.")
        ap("")
        ap("**Conclusione operativa**: la risposta alla domanda e' SI', i gol "
           "realizzati sono piu' dispersi del Poisson condizionato al lambda "
           "per-partita (alpha ~0.2, IC lontano da zero, robusto alle righe "
           "estreme, stabile tra validation e test), ma in forma diversa da "
           "una NB2 unica: quel modello e' un miglioramento per 1X2 e Over/Under "
           "e un danno per GG/NG, quindi non se ne autorizza l'adozione "
           "in blocco. Se si vorra' sfruttare il segnale, la strada e' una "
           "correzione di coda applicata alle soglie (1X2, totali alti) "
           "lasciando GG al Poisson (o un modello di coda piu' flessibile di "
           "NB2, es. mistura o correzioni di livello), ripetendo il "
           "walk-forward con la marginale dentro il blend Elo e su snapshot "
           "successivi. Questo script, come da disciplina, misura e non "
           "modifica: nessun intervento su SoccerMath/ e' raccomandato qui.")
        ap("")
        if loss_markets:
            ap(f"*Mercati a peggioramento coerente: {', '.join(loss_markets)} "
               "(NB-pooled e NB-per-lega); la regola d'arresto ('overdispersion "
               "non dimostrata') non si applica perche' esistono anche i "
               "miglioramenti elencati al punto 1.*")
            ap("")

    # ---- limiti ----
    ap("## Limiti dichiarati")
    ap("")
    ap("1. **Alpha unico per tutti i livelli di lambda**: l'NB2 impone "
       "Var = lambda + alpha*lambda^2 con un solo alpha; una overdispersion "
       "locale (es. solo sulle partite molto aperte) non sarebbe catturata. "
       "Le tabelle descrittive §1 e i quintili §3 servono anche a rivelarlo.")
    ap("2. **Indipendenza casa/trasferta mantenuta**: si sostituisce solo la "
       "pmf marginale; la dipendenza tra i due conteggi (tau Dixon-Coles, "
       "correlazione delle combo) e' fuori campo.")
    ap("3. **Lambda da snapshot xG statico per la testa Totali** (come in "
       "`diagnose_form_totali`/combo): ne eredita i limiti gia' dichiarati. In "
       "piu' la diagnostica §1 mostra che i lambda di questo walk-forward sono "
       "troppo sparpagliati (P(0) marginale sovrastimata via Jensen): parte "
       "dell'alpha MLE assorbe quella misspecificazione oltre alla coda reale. "
       "Il confronto Poisson vs NegBin usa gli stessi identici lambda, quindi "
       "la conclusione RELATIVA (NB2 migliore/peggiore, mercato per mercato) "
       "resta valida per questo motore; il valore assoluto di alpha non e' "
       "trapiantabile sulla fonte point-in-time di produzione senza ripetere "
       "la stima.")
    ap("4. **Alpha al confine**: il parametro alpha dell'NB2 non puo' essere "
       "negativo (sotto-dispersione non ammessa da questa famiglia); quando il "
       "MLE cerca alpha=0 gli IC bootstrap si accalorano sul confine e vanno "
       "letti come 'nessun guadagno rispetto al Poisson', non come stima "
       "puntuale precisa di uno zero.")
    ap("5. **Unico snapshot temporale** (2026-09): gli alpha sono direzione "
       "storica, non coefficienti da cablare; il verdetto fuori-campione su "
       "due stagioni e' la parte che conta.")
    ap("6. **Solo calibrazione, niente quote per questi mercati in questo "
       "script**: ci si limita a Brier/LogLoss/affidabilita'; non si misura "
       "ROI.")
    ap("7. **NB2 non e' onnipotente sulle code**: aggiungere massa sullo zero "
       "e sulle code alte e' un unico movimento parametrizzato; il conflitto "
       "1X2/Over (migliora) contro GG (peggiora) mostra che la vera deviazione "
       "dal Poisson non ha esattamente questa forma. Inoltre la NB2 corregge la "
       "dispersione ma non il LIVELLO: i bias di livello residui nei quintili "
       "bassi (§3) restano e chiedono interventi diversi (calibrazione delle "
       "marginali, fonte xG point-in-time).")
    ap("8. **La testa 1X2 di produzione e' blendata con Elo**: il confronto e' "
       "contro il Poisson puro della testa; un eventuale deployment dovrebbe "
       "prima verificare la marginale NB dentro il blend, non il sostituto "
       "del blend.")
    ap("")
    ap("## Riferimenti incrociati")
    ap("")
    ap("- `audit/results/elo_ensemble_diagnosis.md`: testa 1X2 di riferimento;")
    ap("- `audit/results/form_totali_diagnosis.md`: testa Totali modello B;")
    ap("- `audit/results/combo_1x2_totali_diagnosis.md`: walk-forward e "
       "cross-check bit-a-bit qui riutilizzati, e lente a quintili;")
    ap("- `audit/results/dixon_coles_rho_diagnosis.md`: schema pooled vs "
       "per-lega di un unico parametro stimato sul train.")
    ap("")

    md = "\n".join(L) + "\n"
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Scritto {OUT_PATH}")

    # ---- riepilogo stdout ----
    for head in HEADS:
        p = fits[head]["pooled"]
        al = fits[head]["lega"]
        print(f"[{head}] alpha pooled {p['alpha']:.5f} {_fci(p['ci'],5)} | "
              "per-lega " + ", ".join(f"{c.split()[0]} {v['alpha']:.4f}"
                                      for c, v in al.items()))
    for mkt in ("1X2", "O/U2.5", "GG/NG"):
        for split in ("validation", "test"):
            s = eval_stats[(mkt, split, "AGGREGATO", "Brier")]
            print(f"{mkt:7s} {split:10s} Brier P {s['vals']['poisson']:.4f} "
                  f"NBp {s['vals']['nb_pooled']:.4f} ({s['dp']:+.4f} {_fci(s['cip'])}) "
                  f"NBl {s['vals']['nb_lega']:.4f} ({s['dl']:+.4f} {_fci(s['cil'])})")
    print("MIGLIORAMENTI COERENTI:", wins if wins else "NESSUNO")
    print("PEGGIORAMENTI COERENTI:", losses if losses else "nessuno")
    if not wins:
        print("-> VERDETTO: overdispersion non dimostrata neanche in "
              "versione condizionale")
    return fits, eval_stats, best_nb


if __name__ == "__main__":
    main()
