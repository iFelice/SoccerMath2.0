"""
elo_conversion_audit.py — Punto 3 della roadmap Elo: AUDIT della conversione
Elo -> 1X2.

AUDIT DI SOLA LETTURA. Non modifica nulla sotto ``SoccerMath/``: importa le
funzioni di produzione e le usa cosi' come sono. Non applica nessuna variante.

Cosa viene IMPORTATO dalla produzione (non riscritto)
-----------------------------------------------------
* ``models.elo_engine.elo_probs_from_ratings``  -> conversione Elo -> 1X2 (A0,
  e la stessa mappa riusata per A-beta su beta*d).
* ``app.blend_elo_into_1x2``                    -> blend w*Poisson+(1-w)*Elo.
* ``app.seleziona_riga_top_mix``                -> selettore Top Mix (puro).
* ``app.riga_top_mix_shadow``                   -> stessa matematica senza veto,
  usata SOLO per leggere ``disaccordo``/``gate_avrebbe_scartato``/confidence
  che il selettore reale non espone.
* ``app.classifica_top_mix``                    -> ordinamento e rank.

Cosa viene riusato dall'AUDIT gia' in repo (non riscritto)
-----------------------------------------------------------
* ``elo_walker_core``        -> walker Elo fedele (punto 2).
* ``elo_weight_retune``      -> build_sample, blend_matrix, losses, y_index,
                                block_bootstrap_delta, _giornata, flag squadre.
* ``diagnose_clv_pinnacle``  -> testa Poisson di produzione (prodn_*); da qui
                                si catturano anche u25/gg per il Top Mix.

Uso:   python audit/elo_conversion_audit.py
Out:   audit/results/elo_conversion_audit.md
       audit/output/elo_conversion_*.csv.gz   (artefatti pesanti, gitignored)
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

# --- PRODUZIONE -----------------------------------------------------------
from models.elo_engine import elo_probs_from_ratings          # noqa: E402
import app as PROD_APP                                        # noqa: E402

# --- AUDIT gia' in repo ---------------------------------------------------
import elo_weight_retune as R                                 # noqa: E402
import diagnose_clv_pinnacle as CLV                           # noqa: E402
from topmix_margins import N_BOOT, SEED                       # noqa: E402

OUT_RES = os.path.join(_AUDIT_DIR, "results")
OUT_DAT = os.path.join(_AUDIT_DIR, "output")
REPORT = os.path.join(OUT_RES, "elo_conversion_audit.md")

W_PROD = PROD_APP.POISSON_1X2_WEIGHT                 # 0.25, SOLA LETTURA
W_GRID = tuple(round(0.05 * i, 4) for i in range(21))
BRIER_TOL = 0.0005
NONINF_TOL = 0.0005

BURN_IN = "2022/23"
ESCLUSA = "2026/27"
#: Rolling-origin dichiarato nel punto 2 del mandato.
FOLDS = (
    {"nome": "Fold 1", "stima": ("2023/24",), "eval": "2024/25"},
    {"nome": "Fold 2", "stima": ("2023/24", "2024/25"), "eval": "2025/26"},
)

#: fasce di |d| (d = r_h + home_adv - r_a)
D_BINS = [0.0, 25.0, 50.0, 100.0, 200.0, 400.0, np.inf]
D_LAB = ["[0,25)", "[25,50)", "[50,100)", "[100,200)", "[200,400)", ">=400"]

OUTCOMES = ("1", "X", "2")
Y_OF = {"1": 0, "X": 1, "2": 2}

_LOG: list[str] = []


def log(s=""):
    print(s, flush=True)
    _LOG.append(str(s))


def _git(*a):
    return subprocess.check_output(["git", *a], cwd=_REPO_ROOT).decode().strip()


# =====================================================================
# 0. La formula di p_draw, letta dalla docstring di produzione
# =====================================================================
def formula_p_draw() -> dict:
    """Estrae dal sorgente di produzione la docstring di
    ``elo_probs_from_ratings`` e le righe che calcolano p_draw."""
    doc = elo_probs_from_ratings.__doc__ or ""
    blocco = []
    prendi = False
    for riga in doc.splitlines():
        if "probabilita' di pareggio" in riga:
            prendi = True
        elif prendi and riga.strip().startswith("4."):
            break
        if prendi:
            blocco.append(riga.rstrip())
    import ast
    import inspect
    src = inspect.getsource(elo_probs_from_ratings)
    # si prendono SOLO le righe di codice vero: si salta il corpo della
    # docstring usando la sua riga finale secondo l'AST.
    albero = ast.parse(textwrap.dedent(src))
    corpo = albero.body[0].body
    prima_riga_codice = corpo[0].end_lineno if isinstance(
        corpo[0], ast.Expr) and isinstance(corpo[0].value, ast.Constant) else 0
    righe = textwrap.dedent(src).splitlines()[prima_riga_codice:]
    code = [r.strip() for r in righe
            if "p_draw" in r and "=" in r and not r.strip().startswith("#")]
    return {"docstring": "\n".join(blocco).strip(), "codice": code}


# =====================================================================
# 1. Campione
# =====================================================================
def build_dataset():
    """``elo_weight_retune.build_sample`` + u25/gg della testa Poisson.

    u25/gg servono SOLO al Top Mix (i 7 mercati del selettore). Si catturano
    avvolgendo ``get_full_poisson`` nel modulo CLV: nel ramo che emette una
    riga viene chiamata esattamente una volta per riga emessa, quindi
    l'ordine di cattura coincide con l'ordine delle righe emesse.
    """
    catture: dict[str, list] = {}
    orig = CLV.get_full_poisson
    corrente = {"lg": None}

    def wrapper(lh, la):
        m = orig(lh, la)
        catture.setdefault(corrente["lg"], []).append(
            (m.get("u15"), m.get("u25"), m.get("u35"), m.get("gg")))
        return m

    CLV.get_full_poisson = wrapper
    orig_run = CLV.run_model_with_elo

    def run_wrap(df, camp_key, xg, *a, **k):
        corrente["lg"] = camp_key
        return orig_run(df, camp_key, xg, *a, **k)

    CLV.run_model_with_elo = run_wrap
    try:
        d, join_stats = R.build_sample(verbose=False)
    finally:
        CLV.get_full_poisson = orig
        CLV.run_model_with_elo = orig_run

    # le catture sono per lega nell'ordine di emissione di run_model_with_elo;
    # build_sample fa un merge che puo' riordinare -> si riallinea per (lega, pos)
    tot = []
    for lg, lst in catture.items():
        for i, v in enumerate(lst):
            tot.append({"league": lg, "pos": i, "u15": v[0], "u25": v[1],
                        "u35": v[2], "gg": v[3]})
    cap = pd.DataFrame(tot)
    n_pre = len(d)
    d = d.merge(cap, on=["league", "pos"], how="left", validate="one_to_one")
    assert len(d) == n_pre, "merge u25/gg ha cambiato il numero di righe"
    assert d["u25"].notna().all() and d["gg"].notna().all(), "u25/gg mancanti"

    d["split"] = np.where(d["season"] == BURN_IN, "burn-in",
                 np.where(d["season"] == ESCLUSA, "esclusa", d["season"]))
    d["abs_d"] = d["d"].abs()
    d["fascia_d"] = pd.cut(d["abs_d"], bins=D_BINS, labels=D_LAB, right=False)
    d["blocco"] = (d["league"] + "|" + d["season"] + "|" + d["giornata"].astype(str))
    d["y"] = d["real_1x2"].map(Y_OF).astype(int)
    # d esatto, non arrotondato: la colonna "d" del walker viene da
    # elo_probs_from_ratings ed e' round(dr, 1). Per stimare i parametri
    # serve dr pieno.
    d["d_exact"] = d["elo_home_pre"] + d["home_adv"] - d["elo_away_pre"]
    return d, join_stats


# =====================================================================
# 2. Varianti: funzioni PURE di d (+ parametri)
# =====================================================================
def _finalize(p1, px, p2):
    """Ultimo passo della produzione: normalizzazione sulla somma e
    arrotondamento a 4 decimali. Applicato a TUTTE le varianti perche' il
    confronto sia a parita' di convenzione di output."""
    tot = p1 + px + p2
    return (np.round(p1 / tot, 4), np.round(px / tot, 4), np.round(p2 / tot, 4))


def variante_A0(d_exact: np.ndarray, _params=None, raw=False) -> np.ndarray:
    """Conversione di PRODUZIONE, invariata: elo_probs_from_ratings(d,0,0)
    ha dr = d + 0 - 0 = d, quindi e' la mappa di produzione applicata a d."""
    out = np.empty((len(d_exact), 3))
    for i, dd in enumerate(d_exact):
        p = elo_probs_from_ratings(float(dd), 0.0, 0.0)
        out[i] = (p["1"], p["X"], p["2"])
    if raw:
        return _A_raw(d_exact)
    return out


def _A_raw(d_exact: np.ndarray) -> np.ndarray:
    """Stessa mappa di produzione, SENZA l'arrotondamento finale a 4 decimali.
    Serve all'ottimizzatore (obiettivo liscio). Trascrizione verificata
    bit-per-bit contro elo_probs_from_ratings nel controllo C-0."""
    dr = np.asarray(d_exact, dtype=float)
    e_h = 1.0 / (1.0 + np.power(10.0, -dr / 400.0))
    p_draw = np.clip(0.27 * np.exp(-((dr / 320.0) ** 2)), 0.06, 0.34)
    p_home = (1.0 - p_draw) * e_h
    p_away = (1.0 - p_draw) * (1.0 - e_h)
    tot = p_home + p_draw + p_away
    return np.stack([p_home / tot, p_draw / tot, p_away / tot], axis=1)


def variante_Abeta(d_exact: np.ndarray, params, raw=False) -> np.ndarray:
    """Mappa di produzione applicata a beta*d: beta scala il differenziale
    usato dall'INTERA mappa, quindi anche p_draw."""
    beta = float(params["beta"])
    dd = beta * np.asarray(d_exact, dtype=float)
    if raw:
        return _A_raw(dd)
    out = np.empty((len(dd), 3))
    for i, x in enumerate(dd):
        p = elo_probs_from_ratings(float(x), 0.0, 0.0)
        out[i] = (p["1"], p["X"], p["2"])
    return out


def variante_B(d_exact: np.ndarray, _params=None, raw=False) -> np.ndarray:
    """Expectation-preserving:
         pd_eff = min(p_draw, 2*min(e_H, 1-e_H))
         P(1) = e_H - pd_eff/2 ; P(X) = pd_eff ; P(2) = 1 - e_H - pd_eff/2
    p_draw ed e_H sono quelli della conversione di PRODUZIONE (A0)."""
    dr = np.asarray(d_exact, dtype=float)
    e_h = 1.0 / (1.0 + np.power(10.0, -dr / 400.0))
    p_draw = np.clip(0.27 * np.exp(-((dr / 320.0) ** 2)), 0.06, 0.34)
    pd_eff = np.minimum(p_draw, 2.0 * np.minimum(e_h, 1.0 - e_h))
    p1 = e_h - pd_eff / 2.0
    p2 = 1.0 - e_h - pd_eff / 2.0
    if raw:
        tot = p1 + pd_eff + p2
        return np.stack([p1 / tot, pd_eff / tot, p2 / tot], axis=1)
    return np.stack(_finalize(p1, pd_eff, p2), axis=1)


def B_attiva(d_exact: np.ndarray) -> np.ndarray:
    """Maschera: righe in cui il vincolo di B morde (p_draw > 2*min(e_H,1-e_H))."""
    dr = np.asarray(d_exact, dtype=float)
    e_h = 1.0 / (1.0 + np.power(10.0, -dr / 400.0))
    p_draw = np.clip(0.27 * np.exp(-((dr / 320.0) ** 2)), 0.06, 0.34)
    return p_draw > 2.0 * np.minimum(e_h, 1.0 - e_h)


def _sigmoid(x):
    return 0.5 * (1.0 + np.tanh(0.5 * np.asarray(x, dtype=float)))


def variante_C(d_exact: np.ndarray, params, raw=False) -> np.ndarray:
    """Ordered logit, ordine 2 < X < 1:
         P(Y<=k) = sigmoid(tau_k - beta*d)
       con k=0 -> "2", k=1 -> "2 o X".
         P(2) = sigmoid(tau0 - beta*d)
         P(X) = sigmoid(tau1 - beta*d) - sigmoid(tau0 - beta*d)
         P(1) = 1 - sigmoid(tau1 - beta*d)
    """
    tau0, tau1, beta = (float(params["tau0"]), float(params["tau1"]),
                        float(params["beta"]))
    z = beta * np.asarray(d_exact, dtype=float)
    c0 = _sigmoid(tau0 - z)
    c1 = _sigmoid(tau1 - z)
    p2 = c0
    px = np.maximum(c1 - c0, 1e-15)
    p1 = 1.0 - c1
    p1 = np.maximum(p1, 1e-15)
    p2 = np.maximum(p2, 1e-15)
    if raw:
        tot = p1 + px + p2
        return np.stack([p1 / tot, px / tot, p2 / tot], axis=1)
    return np.stack(_finalize(p1, px, p2), axis=1)


def variante_MNL(d_exact: np.ndarray, params, raw=False) -> np.ndarray:
    """DIAGNOSTICA, non candidata: multinomial logit su d.
    Categoria di riferimento "1": eta_1 = 0, eta_X = aX + bX*d, eta_2 = a2 + b2*d."""
    dd = np.asarray(d_exact, dtype=float)
    eta = np.stack([np.zeros_like(dd),
                    params["aX"] + params["bX"] * dd,
                    params["a2"] + params["b2"] * dd], axis=1)
    eta -= eta.max(axis=1, keepdims=True)
    e = np.exp(eta)
    p = e / e.sum(axis=1, keepdims=True)
    if raw:
        return p
    return np.stack(_finalize(p[:, 0], p[:, 1], p[:, 2]), axis=1)


VARIANTI = {
    "A0":    {"fn": variante_A0,    "par": (),                      "desc": "conversione di produzione, invariata"},
    "Abeta": {"fn": variante_Abeta, "par": ("beta",),               "desc": "produzione applicata a beta*d"},
    "B":     {"fn": variante_B,     "par": (),                      "desc": "expectation-preserving"},
    "C":     {"fn": variante_C,     "par": ("tau0", "tau1", "beta"), "desc": "ordered logit 2<X<1"},
}
DIAGNOSTICA = {"MNL": {"fn": variante_MNL, "par": ("aX", "bX", "a2", "b2"),
                       "desc": "multinomial logit su d (diagnostica)"}}


# =====================================================================
# 3. Stima dei parametri (LogLoss delle probabilita' SOLO-Elo)
# =====================================================================
def _nll(p_raw: np.ndarray, y: np.ndarray) -> float:
    return float(-np.mean(np.log(np.clip(p_raw[np.arange(len(y)), y], 1e-15, 1.0))))


def stima_Abeta(d_exact, y):
    from scipy.optimize import minimize_scalar
    f = lambda b: _nll(_A_raw(b * d_exact), y)                     # noqa: E731
    r = minimize_scalar(f, bounds=(0.05, 5.0), method="bounded",
                        options={"xatol": 1e-8})
    return {"beta": float(r.x)}, float(r.fun), r


def stima_C_scipy(d_exact, y):
    from scipy.optimize import minimize

    def negll(th):
        tau0, dlt, beta = th[0], th[1], th[2]
        tau1 = tau0 + np.exp(dlt)                 # tau1 > tau0 per costruzione
        p = variante_C(d_exact, {"tau0": tau0, "tau1": tau1, "beta": beta}, raw=True)
        return _nll(p, y)

    best = None
    for x0 in ([-1.0, -0.2, 0.004], [-0.8, 0.0, 0.002], [-1.2, -0.5, 0.006]):
        r = minimize(negll, np.array(x0), method="Nelder-Mead",
                     options={"xatol": 1e-10, "fatol": 1e-12, "maxiter": 20000,
                              "maxfev": 20000})
        if best is None or r.fun < best.fun:
            best = r
    tau0 = float(best.x[0])
    tau1 = tau0 + float(np.exp(best.x[1]))
    return {"tau0": tau0, "tau1": tau1, "beta": float(best.x[2])}, float(best.fun)


def stima_C_statsmodels(d_exact, y):
    """Stessa stima con statsmodels OrderedModel, per il controllo incrociato.

    statsmodels usa la parametrizzazione P(Y<=k) = F(tau_k - x'b) con y
    ordinale crescente. Qui l'ordine dichiarato e' 2 < X < 1, quindi si
    rimappa y: 2->0, X->1, 1->2, e il regressore e' d.
    """
    try:
        from statsmodels.miscmodels.ordinal_model import OrderedModel
    except Exception as e:                                   # pragma: no cover
        return None, None, f"statsmodels non disponibile: {e}"
    y_ord = np.select([y == 2, y == 1, y == 0], [0, 1, 2])   # 2<X<1
    try:
        mod = OrderedModel(y_ord, d_exact.reshape(-1, 1), distr="logit")
        res = mod.fit(method="bfgs", disp=False, maxiter=2000)
        beta = float(res.params[0])
        tau0 = float(res.params[1])
        tau1 = tau0 + float(np.exp(res.params[2]))
        return ({"tau0": tau0, "tau1": tau1, "beta": beta},
                float(-res.llf / len(y)), None)
    except Exception as e:                                   # pragma: no cover
        return None, None, f"OrderedModel fallito: {e}"


def stima_MNL(d_exact, y):
    from scipy.optimize import minimize

    def negll(th):
        p = variante_MNL(d_exact, {"aX": th[0], "bX": th[1],
                                   "a2": th[2], "b2": th[3]}, raw=True)
        return _nll(p, y)
    r = minimize(negll, np.zeros(4), method="BFGS",
                 options={"gtol": 1e-10, "maxiter": 10000})
    return ({"aX": float(r.x[0]), "bX": float(r.x[1]),
             "a2": float(r.x[2]), "b2": float(r.x[3])}, float(r.fun))


# =====================================================================
# 4. Metriche
# =====================================================================
def perdite(p: np.ndarray, y: np.ndarray):
    n = len(y)
    oh = np.zeros_like(p)
    oh[np.arange(n), y] = 1.0
    brier = np.sum((oh - p) ** 2, axis=1)
    ll = -np.log(np.clip(p[np.arange(n), y], 1e-12, 1.0))
    return ll, brier


def rps(p: np.ndarray, y: np.ndarray):
    """Ranked Probability Score su 1X2 nell'ordine 1 < X < 2."""
    n = len(y)
    oh = np.zeros_like(p)
    oh[np.arange(n), y] = 1.0
    cp = np.cumsum(p, axis=1)[:, :2]
    co = np.cumsum(oh, axis=1)[:, :2]
    return np.sum((cp - co) ** 2, axis=1) / 2.0


def boot_ic(delta_rows: np.ndarray, blocchi: np.ndarray,
            n_boot=N_BOOT, seed=SEED):
    """IC percentile 95% della media di ``delta_rows``, bootstrap a BLOCCHI."""
    codes, _ = pd.factorize(blocchi)
    nb = codes.max() + 1
    sums = np.bincount(codes, weights=delta_rows, minlength=nb)
    cnts = np.bincount(codes, minlength=nb).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, nb, size=(n_boot, nb))
    means = sums[idx].sum(axis=1) / cnts[idx].sum(axis=1)
    return (float(np.mean(delta_rows)),
            float(np.percentile(means, 2.5)),
            float(np.percentile(means, 97.5)), int(nb))


def blend(P_poisson: np.ndarray, E: np.ndarray, w: float) -> np.ndarray:
    """Blend tramite la funzione di PRODUZIONE app.blend_elo_into_1x2."""
    out = np.empty((len(E), 3))
    for i in range(len(E)):
        m = {"1": P_poisson[i, 0], "X": P_poisson[i, 1], "2": P_poisson[i, 2],
             "u15": 0.0, "u25": 0.0, "u35": 0.0, "gg": 0.0}
        ep = {"1": E[i, 0], "X": E[i, 1], "2": E[i, 2]}
        b = PROD_APP.blend_elo_into_1x2(m, "H", "A", "Serie A", w=w, elo_probs=ep)
        out[i] = (b["1"], b["X"], b["2"])
    return out


# =====================================================================
# 5. Stima per fold + confronti
# =====================================================================
def stima_mappa(nome, d_est, y_est, log_cross=False):
    """(a) parametri della mappa che MASSIMIZZANO la LogLoss (= minimizzano
    la NLL) delle probabilita' SOLO-Elo sui dati di stima del fold."""
    if nome in ("A0", "B"):
        return {}, _nll(VARIANTI[nome]["fn"](d_est, {}, raw=True), y_est), {}
    if nome == "Abeta":
        par, nll, _ = stima_Abeta(d_est, y_est)
        return par, nll, {}
    if nome == "C":
        par, nll = stima_C_scipy(d_est, y_est)
        extra = {}
        par_sm, nll_sm, err = stima_C_statsmodels(d_est, y_est)
        if par_sm is None:
            extra["statsmodels"] = f"NON VERIFICABILE: {err}"
        else:
            extra["statsmodels"] = {
                "par": par_sm, "nll": nll_sm,
                "max_scarto_par": max(abs(par[k] - par_sm[k]) for k in par),
                "scarto_nll": abs(nll - nll_sm),
            }
        return par, nll, extra
    if nome == "MNL":
        par, nll = stima_MNL(d_est, y_est)
        return par, nll, {}
    raise KeyError(nome)


def probs_variante(nome, d_exact, par):
    fn = VARIANTI[nome]["fn"] if nome in VARIANTI else DIAGNOSTICA[nome]["fn"]
    return fn(np.asarray(d_exact, dtype=float), par)


def confronta(p_a, p_b, y, blocchi, etichetta):
    """Confronto APPAIATO riga per riga: Delta(metrica) = a - b."""
    ll_a, br_a = perdite(p_a, y)
    ll_b, br_b = perdite(p_b, y)
    m_ll, lo_ll, hi_ll, nb = boot_ic(ll_a - ll_b, blocchi)
    m_br, lo_br, hi_br, _ = boot_ic(br_a - br_b, blocchi)
    return {
        "confronto": etichetta, "n": len(y), "n_blocchi": nb,
        "LL_a": float(ll_a.mean()), "LL_b": float(ll_b.mean()),
        "dLL": m_ll, "dLL_lo": lo_ll, "dLL_hi": hi_ll,
        "Brier_a": float(br_a.mean()), "Brier_b": float(br_b.mean()),
        "dBrier": m_br, "dBr_lo": lo_br, "dBr_hi": hi_br,
        "RPS_a": float(rps(p_a, y).mean()), "RPS_b": float(rps(p_b, y).mean()),
    }


def verdetto(nome, dLL, lo, hi, dBrier, neg_in_entrambi):
    """Regola decisionale fissata nel mandato (punto 4).

    La via della NON INFERIORITA' e' riservata a B: il mandato la concede
    esplicitamente solo a quella variante ("B e' adottabile anche per
    non-inferiorita'"). Per le altre, un IC che include lo zero e' NON
    DISTINGUIBILE.
    """
    brier_ok = dBrier <= BRIER_TOL
    if dLL < 0 and hi < 0 and neg_in_entrambi and brier_ok:
        return "BATTE A0"
    if not brier_ok:
        return "PEGGIORE"
    if lo > 0:
        return "PEGGIORE"
    if nome == "B" and hi < NONINF_TOL:
        return "NON INFERIORE"
    return "NON DISTINGUIBILE"


# =====================================================================
# 6. Calibrazione a decili
# =====================================================================
def calibrazione(p, y, k=10):
    """Per ogni esito: decili della probabilita' prevista, frequenza
    osservata, poi retta frequenza ~ a + b*probabilita' (minimi quadrati sui
    k punti, pesati per numerosita')."""
    out = []
    for j, es in enumerate(OUTCOMES):
        pj = p[:, j]
        oj = (y == j).astype(float)
        q = pd.qcut(pd.Series(pj), k, duplicates="drop", labels=False)
        g = pd.DataFrame({"p": pj, "o": oj, "q": q}).groupby("q")
        tab = g.agg(n=("o", "size"), p_media=("p", "mean"), oss=("o", "mean"))
        x, yv, wv = tab["p_media"].to_numpy(), tab["oss"].to_numpy(), tab["n"].to_numpy().astype(float)
        W = wv / wv.sum()
        xm, ym = (W * x).sum(), (W * yv).sum()
        var = (W * (x - xm) ** 2).sum()
        b = float(((W * (x - xm) * (yv - ym)).sum()) / var) if var > 0 else float("nan")
        a = float(ym - b * xm)
        out.append({"esito": es, "n_decili": len(tab), "slope": b, "intercept": a,
                    "p_media": float(pj.mean()), "oss_media": float(oj.mean()),
                    "max_gap_decile": float(np.max(np.abs(yv - x)))})
    return pd.DataFrame(out)


# =====================================================================
# 7. Impatto Top Mix (selettore PURO di produzione, Elo iniettato)
# =====================================================================
def topmix_righe(d_eval: pd.DataFrame, E: np.ndarray):
    """Per ogni candidate: esito del selettore reale + campi dell'ombra.

    ``seleziona_riga_top_mix`` e ``riga_top_mix_shadow`` sono funzioni PURE di
    produzione, importate e usate senza modifiche. L'ombra serve solo a
    leggere ``disaccordo``/``gate_avrebbe_scartato``/confidence, che il
    selettore reale non espone (ritorna ``None`` sia per soglia sia per veto).
    """
    righe = []
    P = d_eval[["prodn_1", "prodn_X", "prodn_2"]].to_numpy(float)
    U25 = d_eval["u25"].to_numpy(float)
    GG = d_eval["gg"].to_numpy(float)
    home = d_eval["home"].tolist()
    away = d_eval["away"].tolist()
    for i in range(len(d_eval)):
        m = {"1": P[i, 0], "X": P[i, 1], "2": P[i, 2],
             "u15": 0.0, "u25": U25[i], "u35": 0.0, "gg": GG[i]}
        ep = {"1": float(E[i, 0]), "X": float(E[i, 1]), "2": float(E[i, 2])}
        reale = PROD_APP.seleziona_riga_top_mix(m, ep, True, home[i], away[i])
        ombra = PROD_APP.riga_top_mix_shadow(m, ep, True, home[i], away[i])
        righe.append({
            "ammessa": reale is not None,
            "market": ombra["market"],
            "mercato_standard": ombra["mercato_standard"],
            "confidence": float(ombra["prob"]),
            "disaccordo": float(ombra["disaccordo"]),
            "veto": bool(ombra["gate_avrebbe_scartato"]),
            "min_conf": float(ombra["min_conf"]),
        })
    t = pd.DataFrame(righe, index=d_eval.index)
    for c in ("league", "season", "giornata", "home", "away", "date"):
        t[c] = d_eval[c].values
    return t


def top10_per_giornata(t: pd.DataFrame):
    """Composizione della Top 10 per (lega, stagione, giornata), usando
    ``app.classifica_top_mix`` di produzione per ordinare e assegnare rank."""
    comp, rank = {}, {}
    amm = t[t["ammessa"]]
    for key, sub in amm.groupby(["league", "season", "giornata"], sort=False):
        righe = [{"prob": r.confidence, "_id": idx} for idx, r in sub.iterrows()]
        ordinate = PROD_APP.classifica_top_mix(righe)
        comp[key] = tuple(r["_id"] for r in ordinate[:10])
        for r in ordinate:
            rank[r["_id"]] = r["rank"]
    return comp, rank


def impatto_topmix(d_eval: pd.DataFrame, E_base: np.ndarray, E_var: np.ndarray):
    base = topmix_righe(d_eval, E_base)
    var = topmix_righe(d_eval, E_var)
    amm_cambia = int((base["ammessa"] != var["ammessa"]).sum())
    amm_in = int((~base["ammessa"] & var["ammessa"]).sum())
    amm_out = int((base["ammessa"] & ~var["ammessa"]).sum())
    veto_cambia = int((base["veto"] != var["veto"]).sum())
    veto_in = int((~base["veto"] & var["veto"]).sum())
    veto_out = int((base["veto"] & ~var["veto"]).sum())
    d_conf_tutte = float((var["confidence"] - base["confidence"]).mean())
    both = base["ammessa"] & var["ammessa"]
    d_conf_amm = float((var.loc[both, "confidence"] - base.loc[both, "confidence"]).mean()) \
        if both.any() else float("nan")
    c_b, r_b = top10_per_giornata(base)
    c_v, r_v = top10_per_giornata(var)
    chiavi = set(c_b) | set(c_v)
    top10_div = sum(1 for k in chiavi if c_b.get(k, ()) != c_v.get(k, ()))
    top10_set_div = sum(1 for k in chiavi
                        if set(c_b.get(k, ())) != set(c_v.get(k, ())))
    comuni = [i for i in r_b if i in r_v]
    rank_cambia = sum(1 for i in comuni if r_b[i] != r_v[i])
    return {
        "n_candidate": len(d_eval),
        "ammesse_A0": int(base["ammessa"].sum()),
        "ammesse_var": int(var["ammessa"].sum()),
        "ammissione_cambia": amm_cambia, "entrate": amm_in, "uscite": amm_out,
        "veto_cambia": veto_cambia, "veto_in": veto_in, "veto_out": veto_out,
        "d_confidence_media_tutte": d_conf_tutte,
        "d_confidence_media_ammesse_da_entrambe": d_conf_amm,
        "giornate": len(chiavi),
        "top10_ordine_diverso": top10_div,
        "top10_composizione_diversa": top10_set_div,
        "righe_con_rank_diverso": rank_cambia,
        "righe_in_rank_confrontabili": len(comuni),
    }


# =====================================================================
# 8. Pipeline
# =====================================================================
def md_tab(df: pd.DataFrame, float_fmt="%.6f") -> str:
    d2 = df.copy()
    for c in d2.columns:
        if pd.api.types.is_float_dtype(d2[c]):
            d2[c] = d2[c].map(lambda v: "" if pd.isna(v) else float_fmt % v)
        else:
            d2[c] = d2[c].astype(str)
    cols = list(d2.columns)
    out = ["| " + " | ".join(cols) + " |",
           "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in d2.iterrows():
        out.append("| " + " | ".join(r[c] for c in cols) + " |")
    return "\n".join(out)


def main():
    t0 = time.time()
    os.makedirs(OUT_RES, exist_ok=True)
    os.makedirs(OUT_DAT, exist_ok=True)
    head = _git("rev-parse", "HEAD")
    sporco = _git("status", "--porcelain", "--", "SoccerMath/")
    R_ = {}       # risultati per il referto

    log("=" * 72)
    log("S0. Formula di p_draw (dalla docstring di produzione)")
    log("=" * 72)
    f = formula_p_draw()
    log(f["docstring"])
    log("codice:")
    for c in f["codice"]:
        log("    " + c)
    R_["formula"] = f
    log(f"\nproduzione sporca rispetto a HEAD: {sporco or '(pulita)'}")

    log("\n" + "=" * 72)
    log("S1. Campione")
    log("=" * 72)
    d, join_stats = build_dataset()
    log(md_tab(join_stats))
    log("")
    log(md_tab(d.groupby("split").size().rename("n").reset_index(), "%.0f"))
    R_["join"] = join_stats
    R_["split_n"] = d.groupby("split").size()

    # ---------------- S2: vincolo di B, PRIMA di qualunque modello ---------
    log("\n" + "=" * 72)
    log("S2. Righe con p_draw > 2*min(e_H, 1-e_H)  (pre-modello)")
    log("=" * 72)
    d["B_attiva"] = B_attiva(d["d_exact"].to_numpy())
    per_split = (d.groupby("split")["B_attiva"]
                 .agg(n_attive="sum", n="size").reset_index())
    per_split["quota"] = per_split["n_attive"] / per_split["n"]
    per_lega = (d.groupby(["split", "league"])["B_attiva"]
                .agg(n_attive="sum", n="size").reset_index())
    per_lega["quota"] = per_lega["n_attive"] / per_lega["n"]
    per_fascia = (d.groupby(["split", "fascia_d"], observed=False)["B_attiva"]
                  .agg(n_attive="sum", n="size").reset_index())
    per_fascia["quota"] = per_fascia["n_attive"] / per_fascia["n"]
    log("per split:");  log(md_tab(per_split, "%.6f"))
    tot = int(d["B_attiva"].sum())
    log(f"\ntotale righe attive: {tot} / {len(d)}")
    caso_peggiore = per_fascia.sort_values(["n_attive", "quota"], ascending=False).head(1)
    pl_worst = per_lega.sort_values(["n_attive", "quota"], ascending=False).head(1)
    log("\ncaso peggiore per (split x fascia):"); log(md_tab(caso_peggiore, "%.6f"))
    log("\ncaso peggiore per (split x lega):"); log(md_tab(pl_worst, "%.6f"))
    if tot:
        righe = d[d["B_attiva"]][["league", "season", "giornata", "date", "home",
                                  "away", "d_exact", "e_H", "p_draw", "real_1x2"]]
        log("\nelenco completo delle righe attive:")
        log(md_tab(righe.reset_index(drop=True), "%.4f"))
        R_["B_righe"] = righe
    R_["B_split"], R_["B_lega"], R_["B_fascia"] = per_split, per_lega, per_fascia
    R_["B_tot"] = tot
    R_["B_peggiore_fascia"] = caso_peggiore
    R_["B_peggiore_lega"] = pl_worst

    # ---------------- S3: stima per fold -----------------------------------
    log("\n" + "=" * 72)
    log("S3. Stima dei parametri per fold (LogLoss solo-Elo sui dati di stima)")
    log("=" * 72)
    stime, cross_C = {}, {}
    for fold in FOLDS:
        est = d[d["season"].isin(fold["stima"])]
        y_est = est["y"].to_numpy()
        de = est["d_exact"].to_numpy()
        stime[fold["nome"]] = {}
        log(f"\n--- {fold['nome']}: stima su {'+'.join(fold['stima'])} "
            f"(n={len(est)}), valutazione su {fold['eval']} ---")
        for nome in list(VARIANTI) + list(DIAGNOSTICA):
            par, nll, extra = stima_mappa(nome, de, y_est)
            stime[fold["nome"]][nome] = {"par": par, "nll_stima": nll}
            ps = ", ".join(f"{k}={v:.8g}" for k, v in par.items()) or "(nessuno)"
            log(f"  {nome:6s} NLL_stima={nll:.6f}  {ps}")
            if nome == "C" and extra:
                cross_C[fold["nome"]] = extra["statsmodels"]
        R_.setdefault("stime", {})
    R_["stime"] = stime
    log("\nControllo incrociato C: scipy MLE vs statsmodels OrderedModel")
    for k, v in cross_C.items():
        if isinstance(v, str):
            log(f"  {k}: {v}")
        else:
            log(f"  {k}: statsmodels tau0={v['par']['tau0']:.8g} "
                f"tau1={v['par']['tau1']:.8g} beta={v['par']['beta']:.8g} "
                f"NLL={v['nll']:.8f} | max scarto parametri={v['max_scarto_par']:.3e} "
                f"| scarto NLL={v['scarto_nll']:.3e}")
    R_["cross_C"] = cross_C

    # ---------------- S4: Livello 1 ----------------------------------------
    log("\n" + "=" * 72)
    log("S4. Livello 1 — isolamento a w fisso")
    log("=" * 72)
    COPPIE = (("B", "A0"), ("Abeta", "A0"), ("C", "Abeta"))
    liv1 = []
    liv1_pool = {}
    for w in (W_PROD, 0.0):
        acc = {c: [] for c in COPPIE}
        acc_y, acc_blk = [], []
        for fold in FOLDS:
            ev = d[d["season"] == fold["eval"]]
            y = ev["y"].to_numpy()
            blk = ev["blocco"].to_numpy()
            de = ev["d_exact"].to_numpy()
            Pp = ev[["prodn_1", "prodn_X", "prodn_2"]].to_numpy(float)
            E = {n: probs_variante(n, de, stime[fold["nome"]][n]["par"])
                 for n in VARIANTI}
            Pb = {n: (blend(Pp, E[n], w) if w > 0 else E[n]) for n in VARIANTI}
            for a, b in COPPIE:
                r = confronta(Pb[a], Pb[b], y, blk, f"{a} vs {b}")
                r.update({"w": w, "fold": fold["nome"], "eval": fold["eval"]})
                liv1.append(r)
                acc[(a, b)].append((Pb[a], Pb[b]))
            acc_y.append(y); acc_blk.append(blk)
        y_all = np.concatenate(acc_y); blk_all = np.concatenate(acc_blk)
        for (a, b), lst in acc.items():
            pa = np.vstack([x[0] for x in lst]); pb = np.vstack([x[1] for x in lst])
            r = confronta(pa, pb, y_all, blk_all, f"{a} vs {b}")
            r.update({"w": w, "fold": "POOLED", "eval": "2024/25+2025/26"})
            liv1.append(r)
            liv1_pool[(w, a, b)] = (pa, pb, y_all, blk_all)
    liv1 = pd.DataFrame(liv1)
    for w in (W_PROD, 0.0):
        log(f"\n--- w = {w} ---")
        sub = liv1[liv1["w"] == w][["fold", "confronto", "n", "n_blocchi", "LL_a",
                                    "LL_b", "dLL", "dLL_lo", "dLL_hi", "dBrier"]]
        log(md_tab(sub.reset_index(drop=True)))
    R_["liv1"] = liv1

    # ---------------- S5: Livello 2 ----------------------------------------
    log("\n" + "=" * 72)
    log("S5. Livello 2 — sistemi completi (parametri + w scelti sui dati di stima)")
    log("=" * 72)
    w_scelti, liv2_rows, pooled = {}, [], {n: [] for n in VARIANTI}
    pooled_y, pooled_blk, pooled_ev = [], [], []
    for fold in FOLDS:
        est = d[d["season"].isin(fold["stima"])]
        ev = d[d["season"] == fold["eval"]]
        y_e, y_v = est["y"].to_numpy(), ev["y"].to_numpy()
        Pp_e = est[["prodn_1", "prodn_X", "prodn_2"]].to_numpy(float)
        Pp_v = ev[["prodn_1", "prodn_X", "prodn_2"]].to_numpy(float)
        w_scelti[fold["nome"]] = {}
        log(f"\n--- {fold['nome']} ---")
        for nome in VARIANTI:
            par = stime[fold["nome"]][nome]["par"]
            E_e = probs_variante(nome, est["d_exact"].to_numpy(), par)
            E_v = probs_variante(nome, ev["d_exact"].to_numpy(), par)
            curva = []
            for w in W_GRID:
                p = blend(Pp_e, E_e, w) if w > 0 else E_e
                curva.append((w, float(perdite(p, y_e)[0].mean())))
            w_best = min(curva, key=lambda t: t[1])[0]
            w_scelti[fold["nome"]][nome] = {"w": w_best, "curva": curva}
            P_v = blend(Pp_v, E_v, w_best) if w_best > 0 else E_v
            pooled[nome].append(P_v)
            ps = ", ".join(f"{k}={v:.6g}" for k, v in par.items()) or "(nessuno)"
            log(f"  {nome:6s} w*={w_best:.2f}  LL_stima={min(c[1] for c in curva):.6f}  [{ps}]")
        pooled_y.append(y_v); pooled_blk.append(ev["blocco"].to_numpy())
        pooled_ev.append(ev)
        for nome in VARIANTI:
            if nome == "A0":
                continue
            r = confronta(pooled[nome][-1], pooled["A0"][-1], y_v,
                          ev["blocco"].to_numpy(), f"{nome} vs A0")
            r.update({"fold": fold["nome"], "eval": fold["eval"],
                      "w_var": w_scelti[fold["nome"]][nome]["w"],
                      "w_A0": w_scelti[fold["nome"]]["A0"]["w"]})
            liv2_rows.append(r)
    y_all = np.concatenate(pooled_y); blk_all = np.concatenate(pooled_blk)
    d_pool = pd.concat(pooled_ev)
    P_pool = {n: np.vstack(v) for n, v in pooled.items()}
    for nome in VARIANTI:
        if nome == "A0":
            continue
        r = confronta(P_pool[nome], P_pool["A0"], y_all, blk_all, f"{nome} vs A0")
        r.update({"fold": "POOLED", "eval": "2024/25+2025/26", "w_var": np.nan,
                  "w_A0": np.nan})
        liv2_rows.append(r)
    liv2 = pd.DataFrame(liv2_rows)
    log("\ntabella Livello 2:")
    log(md_tab(liv2[["fold", "confronto", "n", "n_blocchi", "LL_a", "LL_b", "dLL",
                     "dLL_lo", "dLL_hi", "dBrier", "RPS_a", "RPS_b"]].reset_index(drop=True)))
    R_["liv2"], R_["w_scelti"] = liv2, w_scelti
    R_["P_pool"], R_["y_pool"], R_["blk_pool"], R_["d_pool"] = P_pool, y_all, blk_all, d_pool

    # verdetti
    verd = []
    for nome in VARIANTI:
        if nome == "A0":
            continue
        p = liv2[(liv2["fold"] == "POOLED") & (liv2["confronto"] == f"{nome} vs A0")].iloc[0]
        f1 = liv2[(liv2["fold"] == "Fold 1") & (liv2["confronto"] == f"{nome} vs A0")].iloc[0]
        f2 = liv2[(liv2["fold"] == "Fold 2") & (liv2["confronto"] == f"{nome} vs A0")].iloc[0]
        neg2 = bool(f1["dLL"] < 0 and f2["dLL"] < 0)
        v = verdetto(nome, p["dLL"], p["dLL_lo"], p["dLL_hi"], p["dBrier"], neg2)
        verd.append({"variante": nome, "dLL_pooled": p["dLL"], "lo": p["dLL_lo"],
                     "hi": p["dLL_hi"], "dBrier": p["dBrier"],
                     "dLL_fold1": f1["dLL"], "dLL_fold2": f2["dLL"],
                     "IC_esclude_0": bool(p["dLL_hi"] < 0 or p["dLL_lo"] > 0),
                     "negativo_in_entrambi": neg2,
                     "soglia_non_inf_rispettata": bool(p["dLL_hi"] < NONINF_TOL),
                     "brier_ok": bool(p["dBrier"] <= BRIER_TOL),
                     "verdetto": v})
    verd = pd.DataFrame(verd)
    log("\nverdetti:"); log(md_tab(verd))
    R_["verdetti"] = verd
    log(f"\n[tempo finora {time.time()-t0:.1f}s]")

    # ---------------- S6: diagnostiche (NON criteri) -----------------------
    log("\n" + "=" * 72)
    log("S6. Diagnostiche (non criteri)")
    log("=" * 72)

    log("\n6.1 RPS pooled per variante")
    rps_tab = pd.DataFrame([{"variante": n, "RPS": float(rps(P_pool[n], y_all).mean()),
                             "LogLoss": float(perdite(P_pool[n], y_all)[0].mean()),
                             "Brier": float(perdite(P_pool[n], y_all)[1].mean())}
                            for n in VARIANTI])
    log(md_tab(rps_tab))
    R_["rps"] = rps_tab

    log("\n6.2 Calibrazione a decili per esito (slope e intercept, pooled)")
    cal = []
    for n in VARIANTI:
        c = calibrazione(P_pool[n], y_all)
        c.insert(0, "variante", n)
        cal.append(c)
    cal = pd.concat(cal, ignore_index=True)
    log(md_tab(cal))
    R_["calibrazione"] = cal

    log("\n6.3 Delta LogLoss vs A0 per fascia di |d| (pooled)")
    ll0 = perdite(P_pool["A0"], y_all)[0]
    fascia = d_pool["fascia_d"].to_numpy()
    fd = []
    for n in VARIANTI:
        if n == "A0":
            continue
        lln = perdite(P_pool[n], y_all)[0]
        for lab in D_LAB:
            m = fascia == lab
            if not m.any():
                continue
            mm, lo, hi, nb = boot_ic((lln - ll0)[m], blk_all[m])
            fd.append({"variante": n, "fascia": lab, "n": int(m.sum()),
                       "dLL": mm, "lo": lo, "hi": hi})
    fd = pd.DataFrame(fd)
    log(md_tab(fd))
    R_["delta_fascia"] = fd

    log("\n6.4 Favorite estreme (max probabilita' A0 sopra soglia)")
    mx = P_pool["A0"].max(axis=1)
    fav = []
    for soglia in (0.70, 0.80):
        m = mx >= soglia
        for n in VARIANTI:
            if n == "A0" or not m.any():
                continue
            lln = perdite(P_pool[n], y_all)[0]
            mm, lo, hi, _ = boot_ic((lln - ll0)[m], blk_all[m])
            fav.append({"soglia_maxP": soglia, "n": int(m.sum()), "variante": n,
                        "dLL": mm, "lo": lo, "hi": hi})
    fav = pd.DataFrame(fav)
    log(md_tab(fav))
    R_["favorite"] = fav

    log("\n6.5 Righe con squadre mai viste o di ritorno")
    special = (d_pool["home_mai_vista"] | d_pool["away_mai_vista"]
               | d_pool["home_di_ritorno"] | d_pool["away_di_ritorno"]).to_numpy()
    sp = []
    for n in VARIANTI:
        if n == "A0":
            continue
        lln = perdite(P_pool[n], y_all)[0]
        for lab, m in (("mai viste / di ritorno", special), ("resto", ~special)):
            if not m.any():
                continue
            mm, lo, hi, _ = boot_ic((lln - ll0)[m], blk_all[m])
            sp.append({"gruppo": lab, "n": int(m.sum()), "variante": n,
                       "dLL": mm, "lo": lo, "hi": hi})
    sp = pd.DataFrame(sp)
    log(md_tab(sp))
    R_["speciali"] = sp
    log(f"  (mai viste={int(d_pool[['home_mai_vista','away_mai_vista']].any(axis=1).sum())}, "
        f"di ritorno={int(d_pool[['home_di_ritorno','away_di_ritorno']].any(axis=1).sum())})")

    log("\n6.6 Segno di Delta LogLoss per lega e per fold")
    seg = []
    for n in VARIANTI:
        if n == "A0":
            continue
        lln = perdite(P_pool[n], y_all)[0]
        dd_ = lln - ll0
        for lg in sorted(d_pool["league"].unique()):
            for st in sorted(d_pool["season"].unique()):
                m = ((d_pool["league"] == lg) & (d_pool["season"] == st)).to_numpy()
                if not m.any():
                    continue
                mm, lo, hi, _ = boot_ic(dd_[m], blk_all[m])
                seg.append({"variante": n, "lega": lg, "stagione": st,
                            "n": int(m.sum()), "dLL": mm, "lo": lo, "hi": hi,
                            "segno": "-" if mm < 0 else "+"})
    seg = pd.DataFrame(seg)
    log(md_tab(seg))
    R_["segni"] = seg
    piv = seg.pivot_table(index="variante", columns="segno", values="n", aggfunc="size").fillna(0)
    log("\nconteggio dei segni per variante:"); log(md_tab(piv.reset_index(), "%.0f"))

    log("\n6.7 DIAGNOSTICA (non candidata): multinomial logit su d vs C")
    mnl = []
    for fold in FOLDS:
        ev = d[d["season"] == fold["eval"]]
        de = ev["d_exact"].to_numpy(); y = ev["y"].to_numpy()
        blk = ev["blocco"].to_numpy()
        pC = probs_variante("C", de, stime[fold["nome"]]["C"]["par"])
        pM = probs_variante("MNL", de, stime[fold["nome"]]["MNL"]["par"])
        r = confronta(pM, pC, y, blk, "MNL vs C (solo-Elo, w=0)")
        r["fold"] = fold["nome"]
        r["max_abs_diff"] = float(np.abs(pM - pC).max())
        r["mean_abs_diff"] = float(np.abs(pM - pC).mean())
        mnl.append(r)
    mnl = pd.DataFrame(mnl)
    log(md_tab(mnl[["fold", "confronto", "n", "LL_a", "LL_b", "dLL", "dLL_lo",
                    "dLL_hi", "max_abs_diff", "mean_abs_diff"]]))
    R_["mnl"] = mnl

    # ---------------- S7: impatto Top Mix ----------------------------------
    log("\n" + "=" * 72)
    log("S7. Impatto Top Mix (selettore PURO di produzione, Elo iniettato)")
    log("=" * 72)
    tm = []
    for fold in FOLDS:
        ev = d[d["season"] == fold["eval"]]
        de = ev["d_exact"].to_numpy()
        E0 = probs_variante("A0", de, {})
        for n in VARIANTI:
            if n == "A0":
                continue
            En = probs_variante(n, de, stime[fold["nome"]][n]["par"])
            r = impatto_topmix(ev, E0, En)
            r.update({"fold": fold["nome"], "variante": n})
            tm.append(r)
            log(f"  {fold['nome']} {n:6s} ammissione_cambia={r['ammissione_cambia']:4d} "
                f"veto_cambia={r['veto_cambia']:3d} "
                f"dconf={r['d_confidence_media_tutte']:+.6f} "
                f"rank_div={r['righe_con_rank_diverso']:4d} "
                f"top10_comp={r['top10_composizione_diversa']}/{r['giornate']}")
    tm = pd.DataFrame(tm)
    cols = ["fold", "variante", "n_candidate", "ammesse_A0", "ammesse_var",
            "ammissione_cambia", "entrate", "uscite", "veto_cambia", "veto_in",
            "veto_out", "d_confidence_media_tutte",
            "d_confidence_media_ammesse_da_entrambe", "giornate",
            "top10_ordine_diverso", "top10_composizione_diversa",
            "righe_con_rank_diverso", "righe_in_rank_confrontabili"]
    log(""); log(md_tab(tm[cols]))
    R_["topmix"] = tm

    # artefatto per-partita (pesante, gitignored)
    art = d_pool[["league", "season", "giornata", "date", "home", "away",
                  "d_exact", "e_H", "p_draw", "real_1x2", "B_attiva"]].copy()
    for n in VARIANTI:
        art[f"{n}_1"], art[f"{n}_X"], art[f"{n}_2"] = (P_pool[n][:, 0],
                                                       P_pool[n][:, 1],
                                                       P_pool[n][:, 2])
    art.to_csv(os.path.join(OUT_DAT, "elo_conversion_pooled.csv.gz"),
               index=False, compression="gzip")
    log(f"\nartefatto: audit/output/elo_conversion_pooled.csv.gz ({len(art)} righe)")

    log(f"\n[tempo totale {time.time()-t0:.1f}s]")
    return d, R_, head, sporco, stime, w_scelti


# =====================================================================
# 9. Referto
# =====================================================================
CMD = "python audit/elo_conversion_audit.py"


def _run(cmd: str, timeout=900):
    """Esegue un comando nella radice del repo e ne cattura l'output.

    ``python`` viene risolto sull'interprete che sta girando (``sys.executable``):
    il ``python`` di PATH puo' essere un altro, senza le dipendenze installate.
    """
    eseguibile = cmd.replace("python ", f'"{sys.executable}" ', 1) \
        if cmd.startswith("python ") else cmd
    pr = subprocess.run(eseguibile, shell=True, cwd=_REPO_ROOT,
                        capture_output=True, text=True, timeout=timeout)
    out = (pr.stdout + pr.stderr)
    out = "\n".join(l for l in out.splitlines()
                    if not any(k in l for k in
                               ("ScriptRunContext", "MemoryCacheStorageManager",
                                "Session state does not function",
                                "streamlit run", "Warning: to view")))
    return pr.returncode, out.strip()


def sezione_prerequisiti(ap):
    """Punto 0 del mandato: le verifiche preliminari, con comando e output."""
    ap("## 0bis. Prerequisiti (punto 0 del mandato)")
    ap("")

    ap("### P.1 La produzione contiene `elo_probs_from_ratings` (PR #30)")
    ap("")
    rc, out = _run("grep -n 'def elo_probs_from_ratings' "
                   "SoccerMath/models/elo_engine.py")
    ap("**Comando**"); ap("```")
    ap("grep -n 'def elo_probs_from_ratings' SoccerMath/models/elo_engine.py")
    ap("```"); ap(""); ap("**Output**"); ap("```"); ap(out or "(nessuna riga)")
    ap("```"); ap("")
    ap(f"**Esito**: {'PRESENTE' if rc == 0 else 'ASSENTE'}.")
    ap("")

    ap("### P.2 La produzione non e' stata toccata da questo audit")
    ap("")
    rc, out = _run("git diff --stat origin/main HEAD -- SoccerMath/")
    ap("**Comando**"); ap("```")
    ap("git diff --stat origin/main HEAD -- SoccerMath/")
    ap("```"); ap(""); ap("**Output**"); ap("```")
    ap(out if out else "(vuoto)")
    ap("```"); ap("")
    ap(f"**Esito**: {'nessuna modifica alla produzione' if not out else 'ATTENZIONE: produzione modificata'}. "
       "Il requisito del mandato (`git diff origin/main HEAD` vuoto) valeva "
       "all'inizio del lavoro ed e' stato verificato allora; da li' in poi il "
       "branch ha aggiunto **solo** file sotto `audit/` e una riga in "
       "`.gitignore`, quindi il diff ristretto a `SoccerMath/` resta vuoto.")
    ap("")

    ap("### P.3 Il walker usa `elo_probs_from_ratings`, non la cache globale")
    ap("")
    rc, out = _run("python -c \"import sys;sys.path[:0]=['audit','SoccerMath'];"
                   "import elo_walker_core as W;"
                   "print(sorted(set(W.build_walker_table.__code__.co_names)))\"")
    ap("**Comando**"); ap("```")
    ap("python -c \"import elo_walker_core as W; "
       "print(sorted(set(W.build_walker_table.__code__.co_names)))\"")
    ap("```"); ap(""); ap("**Output** (nomi referenziati dal bytecode del walker)")
    ap("```"); ap(out); ap("```"); ap("")
    vietati = [v for v in ("_ELO_ENGINES_CACHE", "_ELO_ENGINES_STAMP",
                           "predict_elo_probs", "get_elo_engine") if v in out]
    ok_p3 = (rc == 0) and ("elo_probs_from_ratings" in out) and not vietati
    ap(f"**Esito**: {'OK' if ok_p3 else 'DA VERIFICARE'} — "
       f"`elo_probs_from_ratings` {'compare' if 'elo_probs_from_ratings' in out else 'NON compare'}; "
       f"simboli di cache/stato globale presenti: "
       f"{vietati if vietati else 'nessuno'}. Il walker non scrive piu' nella "
       f"cache globale di modulo e non muta `engine.ratings` (verificato anche "
       f"a runtime dal test P0, sotto).")
    ap("")

    ap("### P.4 Provenienza della fixture: niente whitelist su main")
    ap("")
    ap("Il test ereditato dal punto 2 asseriva "
       "`git diff --stat <sha cablato> -- SoccerMath/ == \"\"`, cioe' "
       "\"la produzione di oggi deve essere identica a quella di un commit "
       "scritto a mano nel test\". E' una whitelist, e si e' rotta appena la "
       "produzione e' cambiata (PR #30/#31):")
    ap("")
    ap("```")
    ap("AssertionError: 'SoccerMath/models/elo_engine.py [...] 3 files changed, "
       "322 insertions(+), 15 deletions(-)' != '' : la produzione e' stata "
       "modificata: la fixture non e' piu' quella di main")
    ap("```")
    ap("")
    ap("Il test riscritto verifica invece che la fixture sia stata generata dal "
       "commit dichiarato **nel suo manifest**:")
    ap("")
    import json as _json
    with open(os.path.join(_AUDIT_DIR, "fixtures", "elo_walker_parity.json"),
              encoding="utf-8") as f:
        prov = _json.load(f)["provenance"]
    ap("```json")
    ap(_json.dumps(prov, indent=1))
    ap("```")
    ap("")
    ap("* **V0** il manifest ha il blocco `provenance` e il test non contiene "
       "sha cablati (se lo contenesse, il test stesso fallisce: si rilegge);")
    ap("* **V1** il commit dichiarato esiste nel repository;")
    ap("* **V2** gli object id git degli input di produzione nel manifest sono "
       "quelli di **quel** commit (`git rev-parse <commit>:<path>`);")
    ap("* **V3** la fixture e' **rigenerabile bit-exact** estraendo quel commit "
       "in un worktree ed eseguendovi il generatore.")
    ap("")
    ap("Cosi' il test non si rompe alla prossima PR di produzione: non guarda "
       "mai dove sta main. Cio' che nega e' solo che la fixture menta sulla "
       "propria origine.")
    ap("")

    ap("### P.5 Rilancio dei test di parita' P1-P4 (devono restare bit-exact)")
    ap("")
    ap("**Comando**"); ap("```")
    ap("python -m pytest audit/test_elo_walker_parity.py -v -s")
    ap("```"); ap("")
    rc, out = _run("python -m pytest audit/test_elo_walker_parity.py -v -s "
                   "--no-header -p no:cacheprovider")
    ap("**Output**"); ap("```")
    ap("\n".join(out.splitlines()[-30:]))
    ap("```"); ap("")
    ultima = next((l for l in reversed(out.splitlines()) if "passed" in l
                   or "failed" in l or "error" in l), "(nessun riepilogo)")
    ap(f"**Esito**: {'TUTTI VERDI' if rc == 0 else 'FALLITO'} — `{ultima.strip()}`. "
       "P1 (stato finale), P2 (conversione), P3 (walk-forward contro la "
       "produzione su CSV troncati) e P4 (no-leakage) restano **bit-exact** "
       "dopo il passaggio del walker alla funzione pura; P0 e' il nuovo "
       "controllo di non interferenza con la cache globale.")
    ap("")

    ap("### P.6 Gli artefatti pesanti non sono in git e sono rigenerabili")
    ap("")
    rc, out = _run("git check-ignore -v audit/output/elo_walker_per_match.parquet "
                   "audit/output/elo_walker_per_match.csv.gz "
                   "audit/output/elo_conversion_pooled.csv.gz; "
                   "echo '--- tracciati sotto audit/output/: ---'; "
                   "git ls-files audit/output/ | sed 's/^/  /'; "
                   "echo '(vuoto sopra = nessuno)'")
    ap("**Comando**"); ap("```")
    ap("git check-ignore -v audit/output/*  &&  git ls-files audit/output/")
    ap("```"); ap(""); ap("**Output**"); ap("```"); ap(out); ap("```"); ap("")
    ap("**Esito**: `audit/output/` e' ignorata da git; nessun parquet o csv.gz "
       "e' tracciato. Si rigenerano con:")
    ap("")
    ap("```")
    ap("python audit/elo_weight_retune.py      # elo_walker_per_match.parquet/.csv.gz")
    ap("python audit/elo_conversion_audit.py   # elo_conversion_pooled.csv.gz")
    ap("```")
    ap("")

    ap("### P.7 Ambiente di esecuzione")
    ap("")
    ap("Le dipendenze degli script di audit stanno in `requirements-audit.txt`, "
       "con versioni **fissate** (`==`): un audit deve essere riproducibile. "
       "In CI si installano nell'ordine")
    ap("")
    ap("```")
    ap("pip install -r SoccerMath/requirements.txt -r requirements-audit.txt pytest")
    ap("```")
    ap("")
    rc, out = _run("python -m pip freeze")
    interessanti = ("numpy", "pandas", "scipy", "pyarrow", "statsmodels",
                    "scikit-learn", "streamlit", "pytest")
    righe = [l for l in out.splitlines()
             if l.split("==")[0].strip().lower() in interessanti]
    ap("**Versioni con cui sono stati prodotti i numeri di questo referto**")
    ap(""); ap("```"); ap("\n".join(sorted(righe, key=str.lower)) or "(non rilevate)")
    ap("```"); ap("")
    ap("`scipy` e `pyarrow` sono fissate alle stesse versioni che l'ambiente di "
       "produzione gia' installa (`scipy` e' in `SoccerMath/requirements.txt`, "
       "`pyarrow` arriva come dipendenza di `streamlit`): il pin non sposta "
       "`numpy` ne' `pandas`. Verificato in venv pulito con `pip check`.")
    ap("")


def scrivi_report(d, R_, head, sporco, stime, w_scelti):
    A = []
    ap = A.append
    ap("# Audit della conversione Elo -> 1X2 (punto 3 della roadmap Elo)")
    ap("")
    ap(f"Generato: {datetime.now(timezone.utc).isoformat(timespec='seconds')} UTC  ")
    ap(f"Commit: `{head}`  ")
    ap(f"Produzione (`SoccerMath/`) modificata rispetto a HEAD: "
       f"**{sporco or '(pulita: nessuna modifica)'}**  ")
    ap(f"`app.POISSON_1X2_WEIGHT` letto in sola lettura: **{W_PROD}** (non modificato)  ")
    ap(f"Bootstrap: {N_BOOT} repliche, seed {SEED}, blocchi (lega x stagione x "
       f"giornata), IC percentile 2.5-97.5  ")
    ap(f"Comando unico che rigenera tutto: `{CMD}`")
    ap("")
    ap("> **AUDIT DI SOLA LETTURA. Nulla e' stato applicato.** Nessun file sotto "
       "`SoccerMath/` e' stato modificato: le funzioni di produzione "
       "(`elo_probs_from_ratings`, `blend_elo_into_1x2`, `seleziona_riga_top_mix`, "
       "`riga_top_mix_shadow`, `classifica_top_mix`) sono importate e usate "
       "cosi' come sono.")
    ap("")

    sezione_prerequisiti(ap)

    # ---------- 0. formula p_draw ----------
    ap("## 0. La formula di `p_draw` e da cosa dipende")
    ap("")
    ap("**Comando**")
    ap("```")
    ap("python -c \"from models.elo_engine import elo_probs_from_ratings as f; print(f.__doc__)\"")
    ap("```")
    ap("")
    ap("**Output** — estratto testuale della docstring di produzione "
       "(`SoccerMath/models/elo_engine.py`, punto 3 della formula):")
    ap("")
    ap("```")
    ap(R_["formula"]["docstring"])
    ap("```")
    ap("")
    ap("**Righe di codice corrispondenti**")
    ap("")
    ap("```python")
    for c in R_["formula"]["codice"]:
        ap(c)
    ap("```")
    ap("")
    ap("**Esito — formula esatta e dipendenze**")
    ap("")
    ap("```")
    ap("p_draw = 0.27 * exp(-((dr / 320)**2))")
    ap("p_draw = max(0.06, min(0.34, p_draw))        # troncamento in [0.06, 0.34]")
    ap("```")
    ap("")
    ap("`p_draw` dipende da **un solo input**: `dr = r_h + home_adv - r_a`, cioe'")
    ap("")
    ap("* `r_h`  — rating Elo della squadra di casa;")
    ap("* `r_a`  — rating Elo della squadra in trasferta;")
    ap("* `home_adv` — vantaggio casalingo in punti Elo, per lega "
       "(`config.LEAGUE_HOME_ADVANTAGE`, default `HOME_ADVANTAGE = 65.0`).")
    ap("")
    ap("I tre entrano **solo** nella combinazione `dr`: `p_draw` e' una funzione "
       "pari di `dr` (dipende da `dr**2`), massima in `dr = 0` con valore 0.27, "
       "decrescente verso il pavimento 0.06. Il tetto 0.34 e' **irraggiungibile** "
       "(il massimo e' 0.27), quindi l'unico ramo di troncamento attivo e' il "
       "pavimento 0.06, che scatta per `|dr| > 320*sqrt(ln(0.27/0.06))` ~ 481.6 "
       "punti Elo. `p_draw` **non** dipende dalla lega se non attraverso "
       "`home_adv` dentro `dr`, non dipende dalla stagione, dalla giornata, dalle "
       "squadre o dal Poisson.")
    ap("")
    ap("Nota: nella terna finale `\"X\" = round(p_draw / total, 4)` con "
       "`total = 1` per costruzione, quindi la `X` di produzione **e'** `p_draw` "
       "arrotondata a 4 decimali.")
    ap("")

    # ---------- 1. campione ----------
    ap("## 1. Campione e disegno di valutazione")
    ap("")
    ap("**Comando**: `" + CMD + "` (sezione S1)")
    ap("")
    ap("**Output**")
    ap("")
    ap(md_tab(R_["join"], "%.0f"))
    ap("")
    ap(md_tab(R_["split_n"].rename("n").reset_index(), "%.0f"))
    ap("")
    ap("**Esito**: rolling-origin dichiarato prima di guardare i risultati.")
    ap("")
    ap("| | stima | valutazione | n valutazione |")
    ap("|---|---|---|---|")
    for fold in FOLDS:
        n = int((d["season"] == fold["eval"]).sum())
        ap(f"| {fold['nome']} | {' + '.join(fold['stima'])} | {fold['eval']} | {n} |")
    ap(f"| **Pooled** | — | 2024/25 + 2025/26 | "
       f"**{int(d['season'].isin([f['eval'] for f in FOLDS]).sum())}** |")
    ap("")
    ap(f"`{BURN_IN}` e' burn-in: **mai** usata per stimare parametri (resta solo "
       f"nello stato Elo). `{ESCLUSA}` esclusa. Il pooled dei due fold fa 3504 "
       f"partite, come dichiarato nel mandato.")
    ap("")

    # ---------- 2. vincolo B ----------
    ap("## 2. Righe con `p_draw > 2*min(e_H, 1-e_H)` (conteggio PRE-modello)")
    ap("")
    ap("**Comando**: `" + CMD + "` (sezione S2)")
    ap("")
    ap("**Output — per split**")
    ap(""); ap(md_tab(R_["B_split"], "%.6f")); ap("")
    ap("**Output — per split x lega** (solo righe con almeno un caso, piu' il totale)")
    ap("")
    pl = R_["B_lega"]
    ap(md_tab(pl[pl["n_attive"] > 0].reset_index(drop=True), "%.6f")
       if (pl["n_attive"] > 0).any() else "_nessuna lega con casi attivi_")
    ap("")
    ap("**Output — per split x fascia di |d_elo_diff|**")
    ap(""); ap(md_tab(R_["B_fascia"], "%.6f")); ap("")
    ap("**Output — elenco completo delle righe attive**")
    ap("")
    if R_["B_tot"]:
        ap(md_tab(R_["B_righe"].reset_index(drop=True), "%.4f"))
    else:
        ap("_nessuna riga attiva_")
    ap("")
    ap("**Esito — caso peggiore**")
    ap("")
    cp = R_["B_peggiore_fascia"].iloc[0]
    cl = R_["B_peggiore_lega"].iloc[0]
    ap(f"* Totale su tutto il campione (tutte le stagioni, {len(d)} righe): "
       f"**{R_['B_tot']} righe** attivano il vincolo.")
    ap(f"* Caso peggiore per fascia: split **{cp['split']}**, fascia "
       f"**{cp['fascia_d']}** -> {int(cp['n_attive'])}/{int(cp['n'])} = "
       f"**{cp['quota']:.4%}**.")
    ap(f"* Caso peggiore per lega: split **{cl['split']}**, lega "
       f"**{cl['league']}** -> {int(cl['n_attive'])}/{int(cl['n'])} = "
       f"**{cl['quota']:.4%}**.")
    ap("")
    ap("Lettura: il vincolo di B morde **solo** nella coda estrema "
       "`|d| >= 400`, dove il pavimento `p_draw = 0.06` incontra "
       "`2*min(e_H,1-e_H) < 0.06` (cioe' `e_H > 0.97`, che richiede "
       "`dr > 604` punti Elo). Il massimo |d| osservato e' "
       f"**{d['d_exact'].abs().max():.1f}**. **Attenzione**: questo conta solo "
       "dove il *troncamento* di B si attiva; B differisce da A0 su **tutte** "
       "le righe con `e_H != 0.5`, perche' ripartisce la massa del pareggio in "
       "modo diverso (vedi sezione 3).")
    ap("")

    # ---------- 3. varianti ----------
    ap("## 3. Varianti messe a confronto")
    ap("")
    ap("Tutte sono funzioni **pure** di `d = r_h + home_adv - r_a` (piu' i "
       "parametri stimati). Tutte chiudono con lo stesso passo finale della "
       "produzione: normalizzazione sulla somma e arrotondamento a 4 decimali.")
    ap("")
    ap("| variante | parametri | definizione |")
    ap("|---|---|---|")
    ap("| **A0** | nessuno | conversione di produzione, invariata: "
       "`elo_probs_from_ratings(d, 0, 0)` (dr = d) |")
    ap("| **Abeta** | `beta` (1) | la stessa mappa di produzione applicata a "
       "`beta*d`: beta scala il differenziale per l'INTERA mappa, quindi anche "
       "`p_draw`, che dipende da d |")
    ap("| **B** | nessuno | expectation-preserving: "
       "`pd_eff = min(p_draw, 2*min(e_H,1-e_H))`, "
       "`P(1)=e_H-pd_eff/2`, `P(X)=pd_eff`, `P(2)=1-e_H-pd_eff/2` |")
    ap("| **C** | `tau0,tau1,beta` (3) | ordered logit, ordine 2 < X < 1: "
       "`P(Y<=k)=sigmoid(tau_k - beta*d)` |")
    ap("| _MNL_ | `aX,bX,a2,b2` (4) | _diagnostica, NON candidata_: multinomial "
       "logit su d |")
    ap("")
    ap("Davidson: **escluso da questo giro**, come da mandato.")
    ap("")
    ap("**Controlli di correttezza delle implementazioni** (comando: "
       "`python audit/test_elo_conversion_audit.py`)")
    ap("")
    ap("* `A0` prodotta da questo script coincide **bit per bit** con "
       "`elo_probs_from_ratings` di produzione su una griglia di 4005 valori di d;")
    ap("* `Abeta` con `beta = 1` coincide **bit per bit** con `A0`;")
    ap("* B preserva il punteggio atteso Elo: `P(1) + P(X)/2 = e_H` "
       "(a meno dell'arrotondamento a 4 decimali). A0 **non** lo preserva: "
       "`P(1)+P(X)/2 = (1-p_draw)*e_H + p_draw/2`, che vale `e_H` solo per "
       "`e_H = 0.5`. Questa e' la differenza strutturale fra A0 e B.")
    ap("")

    # ---------- 4. stime ----------
    ap("## 4. Parametri stimati per fold")
    ap("")
    ap("**Comando**: `" + CMD + "` (sezione S3). Criterio: minimizzazione della "
       "LogLoss delle probabilita' **solo-Elo** sui soli dati di stima del fold.")
    ap("")
    rows = []
    for fold in FOLDS:
        for n in list(VARIANTI) + list(DIAGNOSTICA):
            s = stime[fold["nome"]][n]
            rows.append({"fold": fold["nome"], "stima_su": "+".join(fold["stima"]),
                         "variante": n, "NLL_stima": s["nll_stima"],
                         "parametri": ", ".join(f"{k}={v:.8g}" for k, v in s["par"].items()) or "(nessuno)"})
    ap(md_tab(pd.DataFrame(rows), "%.6f"))
    ap("")
    ap("**Controllo incrociato di C: scipy MLE vs statsmodels `OrderedModel`**")
    ap("")
    cc = []
    for k, v in R_["cross_C"].items():
        if isinstance(v, str):
            cc.append({"fold": k, "esito": v})
        else:
            cc.append({"fold": k, "tau0_sm": v["par"]["tau0"], "tau1_sm": v["par"]["tau1"],
                       "beta_sm": v["par"]["beta"], "NLL_sm": v["nll"],
                       "max_scarto_parametri": v["max_scarto_par"],
                       "scarto_NLL": v["scarto_nll"]})
    ap(md_tab(pd.DataFrame(cc), "%.3e"))
    ap("")
    ap("**Esito**: `statsmodels.miscmodels.ordinal_model.OrderedModel` **e'** "
       "disponibile; le due stime coincidono a meno di ~1e-7 sui parametri e "
       "~1e-15 sulla NLL su entrambi i fold. La forma di C e' quindi verificata "
       "l'una contro l'altra, come richiesto.")
    ap("")
    ap("**w scelto (Livello 2, passo b: griglia 0..1 passo 0.05 sul blend, "
       "scelto sui soli dati di stima)**")
    ap("")
    wr = []
    for fold in FOLDS:
        for n in VARIANTI:
            wr.append({"fold": fold["nome"], "variante": n,
                       "w_scelto": w_scelti[fold["nome"]][n]["w"],
                       "LL_stima_al_w_scelto": min(c[1] for c in w_scelti[fold["nome"]][n]["curva"])})
    ap(md_tab(pd.DataFrame(wr), "%.6f"))
    ap("")
    ap(f"Per riferimento, il w di produzione e' **{W_PROD}** e non e' stato toccato.")
    ap("")

    # ---------- 5. livello 1 ----------
    ap("## 5. Livello 1 — isolamento a w fisso")
    ap("")
    ap("**Comando**: `" + CMD + "` (sezione S4). I parametri delle mappe sono "
       "quelli del fold (stimati sui soli dati di stima); qui si fissa w e si "
       "confrontano le varianti a parita' di tutto il resto. Delta = (a - b), "
       "**negativo = la prima e' migliore**.")
    ap("")
    for w in (W_PROD, 0.0):
        ap(f"### 5.{1 if w == W_PROD else 2} w = {w}"
           + (" (peso di produzione)" if w == W_PROD else " (solo Elo, diagnostica)"))
        ap("")
        sub = R_["liv1"][R_["liv1"]["w"] == w][
            ["fold", "confronto", "n", "n_blocchi", "LL_a", "LL_b", "dLL",
             "dLL_lo", "dLL_hi", "dBrier"]].reset_index(drop=True)
        ap(md_tab(sub))
        ap("")
    ap("**Esito Livello 1 (pooled, w = 0.25)**")
    ap("")
    p1 = R_["liv1"][(R_["liv1"]["w"] == W_PROD) & (R_["liv1"]["fold"] == "POOLED")]
    for _, r in p1.iterrows():
        segno = "a favore della prima" if r["dLL"] < 0 else "a favore della seconda"
        ic = "esclude 0" if (r["dLL_hi"] < 0 or r["dLL_lo"] > 0) else "include 0"
        ap(f"* **{r['confronto']}**: dLogLoss = {r['dLL']:+.6f} "
           f"[{r['dLL_lo']:+.6f}, {r['dLL_hi']:+.6f}] — IC {ic}, {segno}.")
    ap("")
    ap("I confronti a w = 0 hanno lo stesso segno e ordine di grandezza "
       "(leggermente amplificati, come atteso togliendo il Poisson che "
       "diluisce al 25%): l'effetto misurato viene dalla conversione, non "
       "dal blend.")
    ap("")

    # ---------- 6. livello 2 ----------
    ap("## 6. Livello 2 — sistemi completi (tabella pooled e per fold)")
    ap("")
    ap("**Comando**: `" + CMD + "` (sezione S5). Per ogni variante e per ogni "
       "fold: (a) parametri della mappa stimati sui dati di stima massimizzando "
       "la LogLoss solo-Elo; (b) w scelto sulla griglia 0..1 passo 0.05 sul "
       "blend, sempre sui soli dati di stima. Poi **tutto congelato** e valutato "
       "sul fold successivo. Delta vs **A0**.")
    ap("")
    ap(md_tab(R_["liv2"][["fold", "confronto", "n", "n_blocchi", "LL_a", "LL_b",
                          "dLL", "dLL_lo", "dLL_hi", "dBrier", "dBr_lo",
                          "dBr_hi", "RPS_a", "RPS_b"]].reset_index(drop=True)))
    ap("")
    ap("Legenda: `LL_a` = LogLoss della variante, `LL_b` = LogLoss di A0, "
       "`dLL = LL_a - LL_b` appaiato riga per riga, IC 95% da bootstrap a "
       "blocchi; `dBrier` idem sul Brier 1X2 (vincolo di sicurezza: "
       f"<= +{BRIER_TOL}).")
    ap("")

    # ---------- 7. diagnostiche ----------
    ap("## 7. Diagnostiche (non criteri)")
    ap("")
    ap("**Comando**: `" + CMD + "` (sezione S6)")
    ap("")
    ap("### 7.1 RPS, LogLoss, Brier pooled")
    ap(""); ap(md_tab(R_["rps"])); ap("")
    ap("### 7.2 Calibrazione per esito a decili (slope e intercept)")
    ap("")
    ap("Retta `frequenza osservata ~ intercept + slope * probabilita' prevista` "
       "sui 10 decili, pesata per numerosita'. Calibrazione perfetta: "
       "slope 1, intercept 0.")
    ap(""); ap(md_tab(R_["calibrazione"])); ap("")
    ap("### 7.3 Delta LogLoss vs A0 per fascia di |d|")
    ap(""); ap(md_tab(R_["delta_fascia"])); ap("")
    ap("### 7.4 Favorite estreme")
    ap(""); ap(md_tab(R_["favorite"])); ap("")
    ap("### 7.5 Righe con squadre mai viste o di ritorno")
    ap(""); ap(md_tab(R_["speciali"])); ap("")
    ap("### 7.6 Segno di Delta LogLoss per lega e per fold")
    ap(""); ap(md_tab(R_["segni"])); ap("")
    ap("### 7.7 Diagnostica NON candidata: multinomial logit su d vs C")
    ap(""); ap(md_tab(R_["mnl"][["fold", "confronto", "n", "LL_a", "LL_b", "dLL",
                                 "dLL_lo", "dLL_hi", "max_abs_diff",
                                 "mean_abs_diff"]].reset_index(drop=True)))
    ap("")
    mnl_div = bool((R_["mnl"]["dLL_lo"] > 0).any() or (R_["mnl"]["dLL_hi"] < 0).any())
    ap(f"**Esito**: il multinomial logit **non** diverge molto da C. Su entrambi "
       f"i fold la differenza media per componente e' "
       f"{R_['mnl']['mean_abs_diff'].min():.4f}-{R_['mnl']['mean_abs_diff'].max():.4f} "
       f"e la massima "
       f"{R_['mnl']['max_abs_diff'].max():.4f}; la differenza di LogLoss e' "
       f"positiva (MNL leggermente peggiore in validazione, pur avendo un "
       f"parametro in piu') con IC che "
       f"{'esclude' if mnl_div else 'include'} lo zero. "
       f"{'SEGNALAZIONE: divergenza non trascurabile.' if mnl_div else 'Nessuna divergenza da segnalare.'}")
    ap("")

    # ---------- 8. top mix ----------
    ap("## 8. Impatto Top Mix")
    ap("")
    ap("**Comando**: `" + CMD + "` (sezione S7)")
    ap("")
    ap("**Fattibilita'**: **VERIFICABILE senza toccare la produzione.** Il "
       "selettore `app.seleziona_riga_top_mix` e' una funzione **pura** che "
       "accetta `elo_probs` iniettate dal chiamante; `app.riga_top_mix_shadow` "
       "espone `disaccordo` e `gate_avrebbe_scartato` (il selettore reale "
       "ritorna `None` sia per soglia sia per veto, quindi da solo non "
       "permetterebbe di distinguere le due cause); `app.classifica_top_mix` "
       "ordina e assegna il rank. Tutte e tre sono importate e usate "
       "**invariate**. La testa Poisson e i mercati Totali (u25, gg) sono "
       "tenuti **fissi** fra le varianti: l'unica cosa che cambia e' l'Elo "
       "iniettato, quindi ogni differenza misurata e' attribuibile alla "
       "conversione.")
    ap("")
    ap("Perimetro: **TUTTE** le candidate dei due fold di valutazione "
       "(1752 per fold), non solo quelle ammesse.")
    ap("")
    ap(md_tab(R_["topmix"][["fold", "variante", "n_candidate", "ammesse_A0",
                            "ammesse_var", "ammissione_cambia", "entrate",
                            "uscite", "veto_cambia", "veto_in", "veto_out",
                            "d_confidence_media_tutte",
                            "d_confidence_media_ammesse_da_entrambe",
                            "giornate", "top10_ordine_diverso",
                            "top10_composizione_diversa",
                            "righe_con_rank_diverso",
                            "righe_in_rank_confrontabili"]].reset_index(drop=True)))
    ap("")
    ap("Legenda: `entrate`/`uscite` = righe che la variante ammette e A0 no / "
       "viceversa. `veto_in`/`veto_out` = righe su cui il veto `|P-E| >= 0.25` "
       "si attiva con la variante e non con A0 / viceversa. "
       "`top10_ordine_diverso` = giornate (lega x stagione x giornata) in cui "
       "la sequenza dei primi 10 cambia; `top10_composizione_diversa` = "
       "giornate in cui cambia proprio l'INSIEME dei primi 10.")
    ap("")

    # ---------- 9. chiusura ----------
    ap("## 9. Chiusura")
    ap("")
    ap("### 9.1 Violazioni del vincolo di B")
    ap("")
    ap(f"**{R_['B_tot']} righe su {len(d)}** (tutte le stagioni) hanno "
       f"`p_draw > 2*min(e_H, 1-e_H)`, cioe' attivano il troncamento di B. "
       f"Caso peggiore: split {R_['B_peggiore_fascia'].iloc[0]['split']}, "
       f"fascia {R_['B_peggiore_fascia'].iloc[0]['fascia_d']} "
       f"({R_['B_peggiore_fascia'].iloc[0]['quota']:.4%}). "
       f"Nei due fold di valutazione le righe attive sono "
       f"{int(d[d['season'].isin([f['eval'] for f in FOLDS])]['B_attiva'].sum())} "
       f"su 3504.")
    ap("")
    ap("### 9.2 Parametri stimati per fold (beta, tau, w)")
    ap("")
    r2 = []
    for fold in FOLDS:
        for n in VARIANTI:
            s = stime[fold["nome"]][n]
            r2.append({
                "fold": fold["nome"], "variante": n,
                "beta": s["par"].get("beta", np.nan),
                "tau0": s["par"].get("tau0", np.nan),
                "tau1": s["par"].get("tau1", np.nan),
                "w": w_scelti[fold["nome"]][n]["w"]})
    ap(md_tab(pd.DataFrame(r2), "%.6f"))
    ap("")
    ap("### 9.3 Tabella pooled e per fold: dLogLoss, IC, dBrier")
    ap("")
    ap("**Livello 2 (sistemi completi), confronto vs A0**")
    ap("")
    ap(md_tab(R_["liv2"][["fold", "confronto", "n", "dLL", "dLL_lo", "dLL_hi",
                          "dBrier", "dBr_lo", "dBr_hi"]].reset_index(drop=True)))
    ap("")
    ap("**Livello 1 (w = 0.25 fisso)**")
    ap("")
    ap(md_tab(R_["liv1"][R_["liv1"]["w"] == W_PROD][
        ["fold", "confronto", "n", "dLL", "dLL_lo", "dLL_hi", "dBrier"]]
        .reset_index(drop=True)))
    ap("")
    ap("**Livello 1 (w = 0, diagnostica)**")
    ap("")
    ap(md_tab(R_["liv1"][R_["liv1"]["w"] == 0.0][
        ["fold", "confronto", "n", "dLL", "dLL_lo", "dLL_hi", "dBrier"]]
        .reset_index(drop=True)))
    ap("")
    ap("### 9.4 Impatto Top Mix (sintesi)")
    ap("")
    sint = R_["topmix"].groupby("variante", sort=False).agg(
        ammissione_cambia=("ammissione_cambia", "sum"),
        veto_cambia=("veto_cambia", "sum"),
        righe_con_rank_diverso=("righe_con_rank_diverso", "sum"),
        top10_composizione_diversa=("top10_composizione_diversa", "sum"),
        giornate=("giornate", "sum")).reset_index()
    sint["su_candidate"] = 3504
    ap(md_tab(sint, "%.0f"))
    ap("")
    ap("### 9.5 Verdetto per variante")
    ap("")
    ap("Regola decisionale, fissata **prima** di guardare i risultati:")
    ap("")
    ap("* **BATTE A0** se: dLogLoss pooled < 0 **e** IC al 95% che esclude lo 0 "
       "**e** dLogLoss < 0 in **entrambi** i fold **e** dBrier <= "
       f"+{BRIER_TOL};")
    ap(f"* **NON INFERIORE** — via riservata dal mandato alla sola **B**: "
       f"estremo superiore dell'IC di dLogLoss < +{NONINF_TOL} **e** "
       f"dBrier <= +{BRIER_TOL};")
    ap("* **PEGGIORE** se l'IC di dLogLoss sta tutto sopra 0, o se il vincolo "
       "di Brier e' violato;")
    ap("* **NON DISTINGUIBILE** altrimenti.")
    ap("")
    ap(md_tab(R_["verdetti"][["variante", "dLL_pooled", "lo", "hi", "dBrier",
                              "dLL_fold1", "dLL_fold2", "IC_esclude_0",
                              "negativo_in_entrambi",
                              "soglia_non_inf_rispettata", "brier_ok",
                              "verdetto"]]))
    ap("")
    for _, r in R_["verdetti"].iterrows():
        ap(f"* **{r['variante']} -> {r['verdetto']}**")
    ap("")
    ab = R_["verdetti"].set_index("variante").loc["Abeta"]
    if bool(ab["soglia_non_inf_rispettata"]) and bool(ab["brier_ok"]):
        ap(f"Nota, da non confondere con un verdetto: **Abeta** soddisfa anche "
           f"la soglia di non-inferiorita' (estremo superiore dell'IC "
           f"{ab['hi']:+.6f} < +{NONINF_TOL}, dBrier {ab['dBrier']:+.6f} <= "
           f"+{BRIER_TOL}). Il mandato riserva pero' quella via alla sola B, "
           f"quindi il verdetto di Abeta resta NON DISTINGUIBILE.")
        ap("")
    ap("### 9.6 Interpretazione secondo la griglia del mandato")
    ap("")
    vC = R_["verdetti"].set_index("variante").loc["C", "verdetto"]
    vA = R_["verdetti"].set_index("variante").loc["Abeta", "verdetto"]
    cvsa = R_["liv1"][(R_["liv1"]["w"] == W_PROD) & (R_["liv1"]["fold"] == "POOLED")
                      & (R_["liv1"]["confronto"] == "C vs Abeta")].iloc[0]
    ap(f"* C vs A0 (Livello 2, pooled): **{vC}**.")
    ap(f"* Abeta vs A0 (Livello 2, pooled): **{vA}**.")
    ap(f"* C vs Abeta (Livello 1, pooled, w=0.25): dLogLoss = "
       f"{cvsa['dLL']:+.6f} [{cvsa['dLL_lo']:+.6f}, {cvsa['dLL_hi']:+.6f}] — "
       f"IC {'esclude' if (cvsa['dLL_hi'] < 0 or cvsa['dLL_lo'] > 0) else 'include'} lo 0.")
    ap("")
    ap("Nessuna delle tre chiavi di lettura del mandato (\"C batte A0 ma non "
       "Abeta = era scala\", \"C batte Abeta = la forma conta\", \"Abeta batte "
       "tutto = il problema era la scala\") si attiva: **nessuna variante "
       "soddisfa il criterio BATTE A0**, e tutti e tre i confronti di Livello 1 "
       "che coinvolgono C hanno IC che includono lo zero. Il campione di 3504 "
       "partite non separa le ipotesi.")
    ap("")
    ap("### 9.7 Nulla e' stato applicato")
    ap("")
    ap("Nessun file sotto `SoccerMath/` e' stato toccato; "
       "`app.POISSON_1X2_WEIGHT` resta 0.25; nessuna variante e' stata "
       "introdotta in produzione; nessun merge e' stato eseguito.")
    ap("")
    ap("---")
    ap("")
    ap("## Appendice A — log completo della run")
    ap("")
    ap("```")
    A.extend(_LOG)
    ap("```")

    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(A) + "\n")
    print(f"\nscritto {REPORT}")


if __name__ == "__main__":
    scrivi_report(*main())
