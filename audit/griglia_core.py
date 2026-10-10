#!/usr/bin/env python3
"""griglia_core.py — matematica pura della griglia implicita nelle quote (audit).

Nessuna dipendenza da Streamlit ne' da SoccerMath/: solo numpy/scipy/pandas, cosi'
gira sia nel venv di audit sia nel venv di penaltyblog (verifica di libreria).

Contenuto:
  * de-vig proporzionale (1X2 e Over/Under 2,5);
  * griglia Dixon-Coles sul punteggio 0..K x 0..K, con la stessa convenzione tau
    di produzione (``SoccerMath/models/dixon_coles.tau_correction``):
      (0,0): 1 - lam*mu*rho   (0,1): 1 + lam*rho   (1,0): 1 + mu*rho   (1,1): 1 - rho
    con x = gol casa, y = gol trasferta, poi normalizzazione;
  * fit IMPLICITO per partita: (lam, mu, rho) che riproducono P(1), P(X), P(2) e
    P(Over 2,5) de-vig. Con rho libero: 3 incognite, 4 equazioni (la somma 1X2 e'
    gia' 1), i residui riportati. Il Poisson puro e' il caso rho = 0 (2 incognite);
  * lo stesso fit generalizzato a una LINEA TOTALS QUALUNQUE (``fit_implicit_line``):
    linee a meta' (1,5 / 2,5 / 3,5) a probabilita' diretta; linee intere (2 / 3) col
    rimborso sul pareggio di linea, p = P(sopra)/(1 - P(uguale)); linee a quarti
    (2,25 / 2,75) con mezza puntata su ciascuna delle due linee adiacenti e quota
    equa dalla condizione di valore atteso nullo secondo le regole di pagamento;
  * 20 mercati derivati dalla griglia (1X2, doppia chance, Over/Under, Gol/No Gol,
    combinazioni);
  * Brier per mercato, calibrazione per fasce, bootstrap a blocchi.
"""

from __future__ import annotations

from collections import OrderedDict

import numpy as np
from scipy.optimize import least_squares
from scipy.stats import poisson

K = 15                       # gol massimi per squadra (griglia (K+1)x(K+1)); come produzione
N = K + 1
GOALS = np.arange(N)
I, J = np.indices((N, N))

RHO_BOUNDS = (-0.5, 0.5)     # come penaltyblog.goal_expectancy_extended
LOG_LAM_BOUNDS = (-3.0, 3.0)  # lam in [exp(-3), exp(3)], come penaltyblog

# maschere 16x16 dei mercati, costruite una volta
_H = I > J
_D = I == J
_A = I < J
_T = I + J
_GG = (I > 0) & (J > 0)
MARKET_SPEC = OrderedDict([
    ("1", _H),
    ("X", _D),
    ("2", _A),
    ("1X", _H | _D),
    ("X2", _D | _A),
    ("12", _H | _A),
    ("Over 1.5", _T > 1.5),
    ("Under 1.5", _T < 1.5),
    ("Over 2.5", _T > 2.5),
    ("Under 2.5", _T < 2.5),
    ("Over 3.5", _T > 3.5),
    ("Under 3.5", _T < 3.5),
    ("Gol", _GG),
    ("No Gol", ~_GG),
    ("1+Over 1.5", _H & (_T > 1.5)),
    ("2+Over 1.5", _A & (_T > 1.5)),
    ("1X+Over 1.5", (_H | _D) & (_T > 1.5)),
    ("X2+Under 3.5", (_D | _A) & (_T < 3.5)),
    ("1+Gol", _H & _GG),
    ("2+Gol", _A & _GG),
])
MARKET_NAMES = list(MARKET_SPEC.keys())
MASK = np.stack([m.ravel() for m in MARKET_SPEC.values()], axis=1).astype(float)  # 256 x 20
_IDX_O25 = MARKET_NAMES.index("Over 2.5")


# ---------------------------------------------------------------------------
# De-vig
# ---------------------------------------------------------------------------
def devig_prop(odds) -> np.ndarray | None:
    """Proporzionale: p_i = (1/o_i) / sum_j(1/o_j). None se una quota non e' valida."""
    o = np.asarray(odds, dtype=float)
    if o.ndim != 1 or not np.all(np.isfinite(o)) or np.any(o <= 1.0):
        return None
    q = 1.0 / o
    return q / q.sum()


def devig_shin(odds) -> np.ndarray | None:
    """Shin (1993): rimuove il margine ipotizzando una quota di insider.

    z e' risolta da sum_i p_i(z) = 1, con
        p_i(z) = ( sqrt(z^2 + 4 (1-z) pi_i^2 / Pi) - z ) / (2 (1 - z)),
    pi_i = 1/o_i e Pi = sum_i pi_i. Con margine nullo (Pi <= 1) Shin degenera
    nel proporzionale: caso degenere, dichiarato (nessun margine da rimuovere).
    """
    from scipy.optimize import brentq

    o = np.asarray(odds, dtype=float)
    if o.ndim != 1 or not np.all(np.isfinite(o)) or np.any(o <= 1.0):
        return None
    pi = 1.0 / o
    Pi = float(pi.sum())
    if Pi <= 1.0 + 1e-12:
        return pi / Pi

    def p_of(z):
        return (np.sqrt(z * z + 4.0 * (1.0 - z) * pi * pi / Pi) - z) / (2.0 * (1.0 - z))

    z = brentq(lambda z: p_of(z).sum() - 1.0, 1e-12, 1.0 - 1e-12, xtol=1e-15)
    p = p_of(z)
    return p / p.sum()


def devig_power(odds) -> np.ndarray | None:
    """Metodo a potenza: p_i = pi_i^k, con k >= 1 risolto da sum_i pi_i^k = 1.

    k = 1 (nessun margine) ridà il proporzionale; k > 1 schiaccia di piu' le
    code basse (i favoriti) via via che il margine cresce. Caso degenere
    Pi <= 1: nessun margine, k = 1, coincide col proporzionale (dichiarato).
    """
    from scipy.optimize import brentq

    o = np.asarray(odds, dtype=float)
    if o.ndim != 1 or not np.all(np.isfinite(o)) or np.any(o <= 1.0):
        return None
    pi = 1.0 / o
    if float(pi.sum()) <= 1.0 + 1e-12:
        return pi / pi.sum()
    k = brentq(lambda k: float(np.sum(pi ** k)) - 1.0, 1.0, 10.0, xtol=1e-15)
    p = pi ** k
    return p / p.sum()


DEVIG = OrderedDict([("proporzionale", devig_prop), ("Shin", devig_shin), ("potenza", devig_power)])


def overround(odds) -> float:
    """Margine = sum(1/o) - 1 (nessun de-vig)."""
    o = np.asarray(odds, dtype=float)
    return float(np.sum(1.0 / o) - 1.0)


# ---------------------------------------------------------------------------
# Griglia Dixon-Coles
# ---------------------------------------------------------------------------
def dc_matrix(lam: float, mu: float, rho: float = 0.0) -> np.ndarray:
    """Griglia (N x N) normalizzata: P(casa = x, trasferta = y)."""
    m = np.outer(poisson.pmf(GOALS, lam), poisson.pmf(GOALS, mu))
    if rho != 0.0:
        m[0, 0] *= max(1.0 - lam * mu * rho, 0.0)
        m[0, 1] *= max(1.0 + lam * rho, 0.0)
        m[1, 0] *= max(1.0 + mu * rho, 0.0)
        m[1, 1] *= max(1.0 - rho, 0.0)
    s = m.sum()
    return m / s


def grid_markets(m: np.ndarray) -> np.ndarray:
    """Probabilita' dei 20 mercati (ordine MARKET_NAMES) da una griglia (N x N)."""
    return m.ravel() @ MASK


def grid_1x2_ou(m: np.ndarray) -> np.ndarray:
    """[P1, PX, P2, P(Over 2.5)] da una griglia."""
    return np.array([np.sum(np.tril(m, -1)), np.sum(np.diag(m)),
                     np.sum(np.triu(m, 1)), m.ravel() @ MASK[:, _IDX_O25]])


# ---------------------------------------------------------------------------
# Linea totals QUALUNQUE (mezza, intera, a quarti)
# ---------------------------------------------------------------------------
# Convenzioni di pagamento (regole standard dei mercati Over/Under):
#   * linea MEZZA (1,5 / 2,5 / 3,5 ...): vinta se i gol totali superano la linea,
#     persa altrimenti. Nessun rimborso.
#   * linea INTERA (2 / 3 ...): vinta se i gol totali superano la linea, PERSA se
#     sono sotto, RIMBORSATA (push) se i gol totali sono ESATTI uguali alla linea.
#   * linea A QUARTI (2,25 / 2,75 ...): mezza puntata su ciascuna delle due linee
#     adiacenti (2,25 = ½ su 2,0 + ½ su 2,5; 2,75 = ½ su 2,5 + ½ su 3,0), con le
#     regole di pagamento di ciascuna meta'.
#
# Quota equa dalla condizione di valore atteso nullo: una puntata S sulla linea ha
#   EV = W · S(o − 1) − Lp · S + 0 · Pp = 0   ⇒   o_equa = 1 + Lp / W,
# dove W e' la frazione di puntata che VINCE e Lp la frazione che PERDE (il resto,
# Pp = 1 − W − Lp, e' rimborsato). La "probabilita' giusta" della scommessa e'
#   p_equa = 1 / o_equa = W / (W + Lp),
# cioe' la probabilita' di vincere CONDIZIONATA alla risoluzione (il push non
# conta). Casi particolari, tutti coerenti:
#   * linea mezza:  W = P(sopra), Lp = P(sotto) = 1 − P(sopra)  ⇒ p_equa = P(sopra);
#   * linea intera: W = P(sopra), Lp = P(sotto)                 ⇒ p_equa = P(sopra)/(1 − P(uguale));
#   * a quarti:     media pesata delle due meta'.
# Con questa definizione p_equa(sopra) + p_equa(sotto) = 1 per ogni tipo di linea,
# quindi il de-vig a due vie (proporzionale, potenza, Shin) e' applicabile senza
# correzioni: e' il motivo per cui si usa p_equa e non P(sopra) grezza.

T_MAX = 2 * K                     # gol totali massimi sulla griglia
_GOALS_T = np.arange(T_MAX + 1)   # asse dei gol TOTALI (0..2K)
_LINE_CACHE: dict = {}


def _line_weights(line: float, side: str):
    """(w_win, w_lose) su t = 0..T_MAX: frazione di puntata che vince / perde.

    Ritorna anche i vettori appiattiti sulla griglia (256,) per il prodotto
    scalare con ``m.ravel()``. Arithmetic intera su 4·linea: nessun errore di
    rappresentazione sulle mezze e sui quarti.
    """
    key = (float(line), str(side).lower())
    if key in _LINE_CACHE:
        return _LINE_CACHE[key]
    if str(side).lower() not in ("over", "under"):
        raise ValueError(f"side deve essere 'over' o 'under', non {side!r}")
    n4 = line * 4.0
    if abs(n4 - round(n4)) > 1e-9 or round(n4) <= 0:
        raise ValueError(f"linea non ammessa (attesa un multiplo di 0,25 positivo): {line!r}")
    n4 = int(round(n4))
    t4 = 4 * _GOALS_T

    def one(n: int):
        if str(side).lower() == "over":
            return (t4 > n).astype(float), (t4 < n).astype(float)
        return (t4 < n).astype(float), (t4 > n).astype(float)

    if n4 % 4 in (0, 2):                     # intera (2, 3...) o mezza (1,5; 2,5...)
        w, l = one(n4)
    else:                                    # a quarti: ½ sulla linea sotto + ½ su quella sopra
        w1, l1 = one(n4 - 1)
        w2, l2 = one(n4 + 1)
        w, l = 0.5 * (w1 + w2), 0.5 * (l1 + l2)
    flat = (w[I + J].ravel(), l[I + J].ravel())
    _LINE_CACHE[key] = (w, l, flat[0], flat[1])
    return _LINE_CACHE[key]


def grid_line_prob(m: np.ndarray, line: float, side: str = "over") -> float:
    """Probabilita' giusta (de-vig-abile) della linea: p_equa = W / (W + Lp)."""
    _w, _l, wf, lf = _line_weights(line, side)
    flat = np.asarray(m, dtype=float).ravel()
    W = float(flat @ wf)
    Lp = float(flat @ lf)
    den = W + Lp
    if den <= 0.0:
        return float("nan")
    return W / den


def grid_line_parts(m: np.ndarray, line: float, side: str = "over"):
    """(W, Lp, Pp): frazione che vince, che perde, che e' rimborsata."""
    _w, _l, wf, lf = _line_weights(line, side)
    flat = np.asarray(m, dtype=float).ravel()
    W = float(flat @ wf)
    Lp = float(flat @ lf)
    return W, Lp, max(0.0, 1.0 - W - Lp)


def grid_line_fair_odds(m: np.ndarray, line: float, side: str = "over") -> float:
    """Quota equa dalla condizione di EV nullo: o = 1 + Lp / W."""
    W, Lp, _ = grid_line_parts(m, line, side)
    if W <= 0.0:
        return float("inf")
    return 1.0 + Lp / W


_FLAT_H = np.asarray(_H, dtype=float).ravel()   # casa > trasferta  -> "1"
_FLAT_D = np.asarray(_D, dtype=float).ravel()   # pareggio          -> "X"
_FLAT_A = np.asarray(_A, dtype=float).ravel()   # casa < trasferta  -> "2"


def grid_1x2_line(m: np.ndarray, line: float, side: str = "over") -> np.ndarray:
    """[P1, PX, P2, p_equa(linea, lato)] da una griglia: i 4 vincoli del fit."""
    flat = np.asarray(m, dtype=float).ravel()
    return np.array([float(flat @ _FLAT_H), float(flat @ _FLAT_D), float(flat @ _FLAT_A),
                     grid_line_prob(m, line, side)])


# ---------------------------------------------------------------------------
# Fit implicito per partita
# ---------------------------------------------------------------------------
_STARTS_RHO = ((np.log(1.4), np.log(1.1), -0.05),
               (np.log(1.1), np.log(1.4), -0.10),
               (np.log(1.7), np.log(1.7), 0.05))
_STARTS_POI = ((np.log(1.4), np.log(1.1)),
               (np.log(1.1), np.log(1.4)),
               (np.log(1.7), np.log(1.7)))


def fit_implicit_line(p1: float, pX: float, p2: float, target: float,
                      line: float = 2.5, side: str = "over",
                      rho_free: bool = True) -> dict:
    """Fit (lam, mu[, rho]) su 1X2 + UNA LINEA TOTALS QUALUNQUE.

    E' ``fit_implicit`` generalizzata: il quarto vincolo non e' piu' la sola
    P(Over 2,5) ma la probabilita' giusta ``p_equa`` di una linea qualsiasi
    (mezza, intera o a quarti) sul lato ``side``, calcolata con le regole di
    pagamento (vedi il commento sopra ``_line_weights``).

    Il sistema resta 3 incognite / 3 vincoli indipendenti (P1 + PX + P2 = 1
    piu' la linea), quindi la terna 1X2 e' riprodotta esattamente e la linea
    pure: il residuo atteso e' al livello di macchina.
    """
    tgt = np.array([p1, pX, p2, target], dtype=float)

    def unpack(x):
        lam, mu = float(np.exp(x[0])), float(np.exp(x[1]))
        rho = float(x[2]) if rho_free else 0.0
        return lam, mu, rho

    def resid(x):
        lam, mu, rho = unpack(x)
        return grid_1x2_line(dc_matrix(lam, mu, rho), line, side) - tgt

    if rho_free:
        starts = _STARTS_RHO
        lo = [LOG_LAM_BOUNDS[0], LOG_LAM_BOUNDS[0], RHO_BOUNDS[0]]
        hi = [LOG_LAM_BOUNDS[1], LOG_LAM_BOUNDS[1], RHO_BOUNDS[1]]
    else:
        starts = tuple(s[:2] for s in _STARTS_POI)
        lo = [LOG_LAM_BOUNDS[0], LOG_LAM_BOUNDS[0]]
        hi = [LOG_LAM_BOUNDS[1], LOG_LAM_BOUNDS[1]]

    best = None
    for x0 in starts:
        res = least_squares(resid, np.asarray(x0, dtype=float), bounds=(lo, hi),
                            xtol=1e-14, ftol=1e-14, gtol=1e-14, max_nfev=5000)
        if best is None or res.cost < best.cost:
            best = res
    lam, mu, rho = unpack(best.x)
    r = resid(best.x)
    return {
        "lam": lam, "mu": mu, "rho": rho,
        "resid": r, "max_abs_resid": float(np.max(np.abs(r))),
        "max_abs_resid_1x2": float(np.max(np.abs(r[:3]))),
        "resid_linea": float(abs(r[3])),
        "converged": bool(best.success),
    }


def fit_implicit(p1: float, pX: float, p2: float, pO: float, rho_free: bool = True) -> dict:
    """Fit (lam, mu[, rho]) su 1X2 + Over 2,5 de-vig.

    rho_free=True  -> Dixon-Coles con rho stimato (3 parametri);
    rho_free=False -> Poisson puro (rho = 0, 2 parametri).
    Restituisce lam, mu, rho, residui per target e il massimo |pred - target|.
    """
    target = np.array([p1, pX, p2, pO], dtype=float)

    def unpack(x):
        lam, mu = float(np.exp(x[0])), float(np.exp(x[1]))
        rho = float(x[2]) if rho_free else 0.0
        return lam, mu, rho

    def resid(x):
        lam, mu, rho = unpack(x)
        return grid_1x2_ou(dc_matrix(lam, mu, rho)) - target

    if rho_free:
        starts = _STARTS_RHO
        lo = [LOG_LAM_BOUNDS[0], LOG_LAM_BOUNDS[0], RHO_BOUNDS[0]]
        hi = [LOG_LAM_BOUNDS[1], LOG_LAM_BOUNDS[1], RHO_BOUNDS[1]]
    else:
        starts = tuple(s[:2] for s in _STARTS_POI)
        lo = [LOG_LAM_BOUNDS[0], LOG_LAM_BOUNDS[0]]
        hi = [LOG_LAM_BOUNDS[1], LOG_LAM_BOUNDS[1]]

    best = None
    for x0 in starts:
        res = least_squares(resid, np.asarray(x0, dtype=float), bounds=(lo, hi),
                            xtol=1e-12, ftol=1e-12, gtol=1e-12, max_nfev=2000)
        if best is None or res.cost < best.cost:
            best = res
    lam, mu, rho = unpack(best.x)
    r = resid(best.x)
    return {
        "lam": lam, "mu": mu, "rho": rho,
        "resid": r, "max_abs_resid": float(np.max(np.abs(r))),
        "max_abs_resid_1x2": float(np.max(np.abs(r[:3]))),
        "resid_ou25": float(abs(r[3])),
        "converged": bool(best.success),
    }


# ---------------------------------------------------------------------------
# Esiti reali e metriche
# ---------------------------------------------------------------------------
def outcome_matrix(fthg: np.ndarray, ftag: np.ndarray) -> np.ndarray:
    """Y (n x 20): 1 se il mercato e' realizzato dal punteggio reale."""
    fthg = np.asarray(fthg, dtype=int)
    ftag = np.asarray(ftag, dtype=int)
    if fthg.size and (fthg.max() > K or ftag.max() > K or fthg.min() < 0 or ftag.min() < 0):
        raise ValueError("punteggio fuori dalla griglia")
    return MASK[fthg * N + ftag, :]


def brier_per_match(P: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """Brier binario per partita e mercato: (p - y)^2 (n x 20)."""
    return (P - Y) ** 2


def block_bootstrap_mean_diff(d_match: np.ndarray, blocks: np.ndarray, reps: int,
                              rng: np.random.Generator) -> dict:
    """IC al 95% (percentile) della media di d_match ri-campionando i BLOCCHI.

    d_match: vettore (n,) di differenze per partita (es. Brier_modello - Brier_griglia).
    blocks:  etichetta di blocco per partita (lega x stagione x giornata).
    Ricampionamento con reimmissione dei blocchi; la statistica e' la media
    delle differenze sulle partite dei blocchi estratti (media ponderata per partita).
    """
    labels, inv = np.unique(blocks, return_inverse=True)
    nb = len(labels)
    S = np.bincount(inv, weights=d_match, minlength=nb)
    Nb = np.bincount(inv, minlength=nb).astype(float)
    draws = rng.multinomial(nb, np.full(nb, 1.0 / nb), size=reps).astype(float)
    num = draws @ S
    den = draws @ Nb
    stat = num / np.maximum(den, 1.0)
    lo, hi = np.percentile(stat, [2.5, 97.5])
    return {"mean": float(np.mean(d_match)), "lo": float(lo), "hi": float(hi),
            "n_blocchi": int(nb), "reps": int(reps)}


def decide_replace(ci_lo_diff: float, ci_hi_diff: float) -> str:
    """Regola dichiarata. d = Brier(modello) - Brier(griglia implicita).

    * griglia sostituisce il modello: d > 0 e IC 95% con estremo inferiore > 0
      (la griglia implicita ha Brier migliore con IC che esclude lo zero);
    * modello migliore dimostrato: IC tutto < 0 (la griglia NON sostituisce);
    * altrimenti: nessuna differenza dimostrata.
    """
    if ci_lo_diff > 0:
        return "SOSTITUISCE (griglia implicita)"
    if ci_hi_diff < 0:
        return "NO: modello migliore (dimostrato)"
    return "nessuna differenza dimostrata"


# Fasce di calibrazione (probabilita' dichiarata dell'evento)
BANDS = OrderedDict([
    ("0,50-0,60", (0.50, 0.60)),
    ("0,60-0,70", (0.60, 0.70)),
    ("0,70-0,80", (0.70, 0.80)),
    ("0,80-0,90", (0.80, 0.90)),
    ("≥0,90", (0.90, 1.0000001)),
])
HIGH_BANDS = OrderedDict([
    ("0,65-0,70", (0.65, 0.70)),
    ("0,70-0,80", (0.70, 0.80)),
    ("0,80-0,90", (0.80, 0.90)),
    ("≥0,90", (0.90, 1.0000001)),
])


def calibration_rows(p: np.ndarray, y: np.ndarray, bands: dict) -> list[dict]:
    rows = []
    for name, (lo, hi) in bands.items():
        m = (p >= lo) & (p < hi)
        n = int(m.sum())
        rows.append({
            "fascia": name, "n": n,
            "p_media": float(np.mean(p[m])) if n else float("nan"),
            "freq_osservata": float(np.mean(y[m])) if n else float("nan"),
        })
    return rows
