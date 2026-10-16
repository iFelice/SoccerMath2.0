"""O/U di mercato, separato dal selettore 1X2. Nessuna rete o import audit.

Matematica portata da griglia_core; parità numerica verificata sullo snapshot
16/10/2026. Linee intere e a quarti usano la probabilità equa W/(W+L).
"""
from __future__ import annotations

import math
from functools import lru_cache
from statistics import median

import numpy as np
from scipy.optimize import least_squares
from scipy.stats import poisson

from market_odds import probabilita_mercato

TOTALS_VERSION = "totals_mercato_v1"
SOGLIA_OU = 0.67
K = 15
N = K + 1
GOALS = np.arange(N)
I = np.indices((N, N))[0]
J = np.indices((N, N))[1]
_H = I > J
_D = I == J
_A = I < J
RHO_BOUNDS = (-0.5, 0.5)
LOG_LAM_BOUNDS = (-3.0, 3.0)

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


def devig_totals(quote):
    """Due vie proporzionali; dati incompleti/invalidi non sono una fonte."""
    if not isinstance(quote, dict):
        return None
    values = [quote.get("Over"), quote.get("Under")]
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not math.isfinite(v) or v <= 1 for v in values):
        return None
    inv = [1 / v for v in values]
    return inv[0] / sum(inv)


def linee_valide(libro):
    out = []
    totals = libro.get("totals") or {}
    if not isinstance(totals, dict):
        return out
    for key, quote in totals.items():
        try:
            line = float(key)
        except (ValueError, TypeError):
            continue
        if not math.isfinite(line) or line <= 0 or abs(line * 4 - round(line * 4)) > 1e-9:
            continue
        p = devig_totals(quote)
        if p is not None:
            out.append((line, p))
    return sorted(out)


@lru_cache(maxsize=1024)
def _fit_grid(p1, px, p2, target, line):
    fit = fit_implicit_line(p1, px, p2, target, line)
    if not fit["converged"] or not math.isfinite(fit["max_abs_resid"]) or fit["max_abs_resid"] > 1e-5:
        return None
    m = dc_matrix(fit["lam"], fit["mu"], fit["rho"])
    return m if np.all(np.isfinite(m)) else None


def calcola_totals(libri, esito_1x2=""):
    """Probabilità e congiunta da riquadri della griglia, mai dal prodotto.

    {} significa fonte/fit assente. La congiunta esiste solo se entrambi i
    pronostici sono ammessi; esito_1x2 deve provenire dal selettore invariato.
    """
    libri = [b for b in (libri or []) if isinstance(b, dict)]
    mkt = probabilita_mercato(libri)
    probs = mkt.get("probs")
    if not probs:
        return {}
    pin = next((b for b in libri if str(b.get("key", "")).lower() == "pinnacle"), {})
    lines = linee_valide(pin)
    if lines:
        # La fonte primaria richiede ANCHE la terna Pinnacle valida.
        pin_probs = probabilita_mercato([pin]).get("probs")
        if not pin_probs:
            return {}
        probs = pin_probs
        line, target = lines[0]
        fonte = f"pinnacle_linea_{line:g}"
        linea_pin = line
    else:
        consensus = {}
        for b in libri:
            for line, p in linee_valide(b):
                if line == 2.5:
                    consensus[str(b.get("key") or "").lower()] = p
        if len(consensus) < 3:
            return {}
        line, target = 2.5, median(consensus.values())
        fonte, linea_pin = "consenso_2.5", ""
    m = _fit_grid(*(probs[e] for e in ("1", "X", "2")), target, line)
    if m is None:
        return {}
    over = float(m[I + J > 2.5].sum())
    under = 1.0 - over
    pronostico = ("Over" if over >= under else "Under") if max(over, under) >= SOGLIA_OU else ""
    out = {"p_over": over, "p_under": under, "pronostico": pronostico,
           "fonte": fonte, "linea_pinnacle": linea_pin, "linea_fit": line,
           "target": target, "probs_1x2": probs}
    if pronostico and esito_1x2 in ("1", "X", "2"):
        mask = {"1": I > J, "X": I == J, "2": I < J}[esito_1x2]
        gol = I + J > 2.5 if pronostico == "Over" else I + J < 2.5
        out["p_congiunta"] = float(m[mask & gol].sum())
        out["esito_1x2"] = esito_1x2
    return out


def celle_totals(totals):
    if not totals.get("pronostico"):
        return {"Gol": "", "Insieme %": ""}
    side = totals["pronostico"]
    p = totals["p_over"] if side == "Over" else totals["p_under"]
    joint = totals.get("p_congiunta")
    return {"Gol": f"{side} 2,5 · {p:.0%}",
            "Insieme %": f"{100 * joint:.0f}" if joint is not None else ""}


def frase_totals(totals):
    if not totals:
        return ""
    if not totals.get("pronostico"):
        return f"Gol: P(Over 2,5) {totals['p_over']:.0%} · nessun pronostico"
    frase = "Gol: " + celle_totals(totals)["Gol"].replace(" · ", " ")
    if "p_congiunta" in totals:
        frase += f" · insieme all'{totals['esito_1x2']}: {totals['p_congiunta']:.0%}"
    return frase + " · Modello %: n/d"
