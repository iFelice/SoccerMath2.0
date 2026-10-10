#!/usr/bin/env python3
"""griglia_varianti.py — audit SOLA LETTURA: varianti della griglia implicita e calibrazione.

Copre i punti 2-6 del brief (il punto 1, sonda totals, e' in totals_probe_per_lega.py).

Nessuna modifica a SoccerMath/ (app.py incluso). Nessuna chiamata di rete. Nessuna chiave.
NON importa ``griglia_implicita.py`` (che importa ``app.py`` a livello di modulo): il
caricamento dei CSV e' ricopiato qui; la matematica viene da ``griglia_core.py``.
Il tau di produzione e' importato da ``SoccerMath/models/dixon_coles.py`` (sola lettura).

CAMPIONE (come PR #58): stagioni 2024/25 e 2025/26 delle 5 leghe, CSV football-data in
SoccerMath/database, partite con B365 1X2 e B365 O/U 2,5 completi: 3504.
Sottocampione di sensibilita': con anche Pinnacle di chiusura completa (PSC 1X2 + PC O/U 2,5).

VARIANTI (per partita, su 1X2 + O/U 2,5 de-vig proporzionale):
  A. Dixon-Coles con rho per partita (fit come PR #58: 3 parametri).
  B. Dixon-Coles con rho FISSO: mediana dei rho impliciti di A nella 2024/25, applicata alla
     2025/26; per la 2024/25 rho = 0 (dichiarato). lambda e mu rifittati per partita.
  C. Poisson indipendente (rho = 0), lambda e mu per partita.

REGOLE DICHIARATE (scritte qui PRIMA di eseguire lo script; non modificate dopo i numeri):
  R2 (tau). Confronto cella per cella (0,0), (0,1), (1,0), (1,1) tra: produzione
     (SoccerMath/models/dixon_coles.tau_correction), formula di Dixon & Coles 1997 come citata
     in arXiv:2103.07272 eq. (2) con x = gol casa e lambda = media casa, e convenzione di
     penaltyblog 1.13.1 (letta dal sorgente). Se la produzione fosse invertita, NON si corregge:
     si misura l'effetto sui derivati e lo si segnala.
  R3 (scelta della variante). Metrica: Brier binario per partita sul mercato Gol (No Gol e'
     identico). d = Brier(X) - Brier(Y); d < 0 => X migliore. Bootstrap a blocchi
     (lega x stagione x data), 2000 repliche, seme 20261010, IC 95% percentile.
     Passo 1: si adotta A solo se l'IC 95% di A-B e' interamente sotto zero.
     Passo 2 (altrimenti): si adotta B se l'IC 95% di B-C e' interamente sotto zero.
     Passo 3 (altrimenti): si adotta C.
     Interpretazione: il brief dice "altrimenti B" al passo 1 e "si adotta B invece di C con lo
     stesso criterio" al passo 2; si legge come B candidata al posto di A e poi confrontata con C.
     Il sottocampione Pinnacle applica la stessa procedura: solo sensibilita', non decide.
  R4 (calibrazione). Per ogni coppia evento / complemento e per partita si considera l'esito
     con probabilita' piu' alta (p >= 0,5). Fasce di p: [0,55-0,65), [0,65-0,75), >= 0,75.
     IC 95% di f - p con bootstrap a blocchi (rapporto), 2000 repliche, seme 20261011.
     REGOLA: un mercato entra nella lista delle giocate se in OGNI fascia con n >= 100 l'IC di
     f - p contiene zero, OPPURE |f - p| <= 0,03. Se nessuna fascia ha n >= 100, il mercato e'
     "non valutabile" e resta fuori (decisione dichiarata qui: lettura conservativa).
  R5 (punto 5). Descrittivo, nessuna regola di decisione. IC 95% bootstrap a blocchi, seme 20261012.
  R6 (punto 6). Descrittivo. Stima come PR #58: R = q_B365 / p_depurata_Pinnacle di apertura,
     stimato su 2024/25 per lega x tipo x fascia di quota equa Pinnacle; testato su 2025/26.
     Errore relativo = q_stimata / q_reale - 1, in valore assoluto; riportato anche in punti di
     quota. Fasce per QUOTA REALE bet365: [1,20-1,50), [1,50-2,00), [2,00-3,00), >= 3,00.
  Derivati valutati (punti 3-4): Gol/No Gol, Over/Under 1,5 e 3,5, doppia chance 1X / X2 / 12,
     1+Over 1,5, 2+Over 1,5, 1X+Over 1,5, 1X+Under 3,5 (elenco del brief). X2+Under 3,5, presente
     in PR #58 e NON nell'elenco del brief, e' calcolato e segnalato come extra; non decide nulla.
     1X2 e O/U 2,5 restano fuori dalla valutazione dei derivati.

Output: audit/results/griglia_varianti.md (referto), audit/output/griglia_varianti.json e
audit/output/griglia_varianti_fits.pkl (non versionati).
Uso: python audit/griglia_varianti.py [--no-cache]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy.optimize import brentq, least_squares
from scipy.stats import poisson

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO, "SoccerMath"))  # config.clean_name, models.dixon_coles.tau

from config import clean_name  # noqa: E402
from models.dixon_coles import tau_correction  # noqa: E402  (produzione, sola lettura)
from griglia_core import (  # noqa: E402
    LOG_LAM_BOUNDS, N, _A, _D, _GG, _H, _T,
    block_bootstrap_mean_diff, brier_per_match, dc_matrix, devig_prop, fit_implicit,
    grid_1x2_ou,
)

DB_DIR = os.path.join(_REPO, "SoccerMath", "database")
OUT_DIR = os.path.join(_AUDIT_DIR, "output")
REPORT = os.path.join(_AUDIT_DIR, "results", "griglia_varianti.md")
JSON_OUT = os.path.join(OUT_DIR, "griglia_varianti.json")
CACHE = os.path.join(OUT_DIR, "griglia_varianti_fits.pkl")

LEAGUES = [("SerieA", "Serie A"), ("Premier", "Premier League"), ("LaLiga", "La Liga"),
           ("Bundesliga", "Bundesliga"), ("Ligue1", "Ligue 1")]
SEASON_FILE = OrderedDict([("2024/25", "2024"), ("2025/26", "2025")])
REPS = 2000
SEED_R3, SEED_R4, SEED_R5, SEED_R6 = 20261010, 20261011, 20261012, 20261013
EDGE_RHO = 0.49
TOL_PT = 0.03                # |f - p| entro 3 punti: regola R4
CAL_BANDS = OrderedDict([("0,55-0,65", (0.55, 0.65)), ("0,65-0,75", (0.65, 0.75)),
                         ("≥0,75", (0.75, 1.0000001))])
HIGH = (0.65, 1.0000001)

QCOLS = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR",
         "B365H", "B365D", "B365A", "B365>2.5", "B365<2.5",
         "PSH", "PSD", "PSA", "P>2.5", "P<2.5",
         "PSCH", "PSCD", "PSCA", "PC>2.5", "PC<2.5",
         "B365CH", "B365CD", "B365CA", "B365C>2.5", "B365C<2.5"]

_STARTS_POI = ((np.log(1.4), np.log(1.1)), (np.log(1.1), np.log(1.4)), (np.log(1.7), np.log(1.7)))

# Eventi derivati: nome -> (maschera 16x16 dell'evento primario, nome del complemento).
EVENTS = OrderedDict([
    ("Gol", (_GG, "No Gol")),
    ("Over 1.5", (_T > 1.5, "Under 1.5")),
    ("Over 3.5", (_T > 3.5, "Under 3.5")),
    ("1X", (_H | _D, "2")),
    ("X2", (_D | _A, "1")),
    ("12", (_H | _A, "X")),
    ("1+Over 1.5", (_H & (_T > 1.5), "non (1 + Over 1,5)")),
    ("2+Over 1.5", (_A & (_T > 1.5), "non (2 + Over 1,5)")),
    ("1X+Over 1.5", ((_H | _D) & (_T > 1.5), "non (1X + Over 1,5)")),
    ("1X+Under 3.5", ((_H | _D) & (_T < 3.5), "non (1X + Under 3,5)")),
    ("X2+Under 3.5", ((_D | _A) & (_T < 3.5), "non (X2 + Under 3,5)")),  # extra PR #58
])
EXTRA = {"X2+Under 3.5"}
EV_NAMES = list(EVENTS.keys())
EV_MASK = np.stack([m.ravel() for m, _ in EVENTS.values()], axis=1).astype(float)  # 256 x 11
EV_IDX = {k: i for i, k in enumerate(EV_NAMES)}


# ---------------------------------------------------------------------------
# 1. Caricamento (come PR #58: load_quotes + dedup su lega/data/casa/trasferta)
# ---------------------------------------------------------------------------
def load_quotes(prefix: str, league: str) -> pd.DataFrame:
    frames = []
    for season, suffix in SEASON_FILE.items():
        raw = pd.read_csv(os.path.join(DB_DIR, f"{prefix}_{suffix}.csv"),
                          encoding="utf-8-sig", on_bad_lines="warn", low_memory=False)
        df = pd.DataFrame({c: (raw[c] if c in raw.columns else np.nan) for c in QCOLS})
        df["season"] = season
        df["league"] = league
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    for c in QCOLS[3:]:
        if c != "FTR":
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    df["home"] = df["HomeTeam"].map(clean_name)
    df["away"] = df["AwayTeam"].map(clean_name)
    df["date_day"] = df["Date"].dt.normalize()
    df = df.drop_duplicates(subset=["league", "date_day", "home", "away"], keep="last")
    return df.reset_index(drop=True)


def load_all() -> pd.DataFrame:
    return pd.concat([load_quotes(p, l) for p, l in LEAGUES], ignore_index=True)


# ---------------------------------------------------------------------------
# 2. De-vig: proporzionale (griglia_core), Shin (1993), potenza
# ---------------------------------------------------------------------------
def devig_shin(odds):
    o = np.asarray(odds, dtype=float)
    if o.ndim != 1 or not np.all(np.isfinite(o)) or np.any(o <= 1.0):
        return None
    pi = 1.0 / o
    Pi = pi.sum()
    if Pi <= 1.0 + 1e-12:            # nessun margine (o arbitraggio): Shin degenera nel proporzionale
        return pi / Pi

    def p_of(z):
        return (np.sqrt(z * z + 4.0 * (1.0 - z) * pi * pi / Pi) - z) / (2.0 * (1.0 - z))

    z = brentq(lambda z: p_of(z).sum() - 1.0, 1e-12, 1.0 - 1e-12, xtol=1e-15)
    p = p_of(z)
    return p / p.sum()


def devig_power(odds):
    o = np.asarray(odds, dtype=float)
    if o.ndim != 1 or not np.all(np.isfinite(o)) or np.any(o <= 1.0):
        return None
    pi = 1.0 / o
    if pi.sum() <= 1.0 + 1e-12:
        return pi / pi.sum()
    k = brentq(lambda k: np.sum(pi ** k) - 1.0, 1.0, 10.0, xtol=1e-15)
    return pi ** k


DEVIG = OrderedDict([("proporzionale", devig_prop), ("Shin", devig_shin), ("potenza", devig_power)])


# ---------------------------------------------------------------------------
# 3. Fit delle varianti
# ---------------------------------------------------------------------------
def fit_fixed_rho(p1, pX, p2, pO, rho: float):
    """lambda, mu per partita con rho fisso; least squares su 1X2 + Over 2,5 (2 parametri)."""
    target = np.array([p1, pX, p2, pO], dtype=float)

    def resid(x):
        return grid_1x2_ou(dc_matrix(float(np.exp(x[0])), float(np.exp(x[1])), rho)) - target

    lo = [LOG_LAM_BOUNDS[0]] * 2
    hi = [LOG_LAM_BOUNDS[1]] * 2
    best = None
    for x0 in _STARTS_POI:
        res = least_squares(resid, np.asarray(x0, dtype=float), bounds=(lo, hi),
                            xtol=1e-12, ftol=1e-12, gtol=1e-12, max_nfev=2000)
        if best is None or res.cost < best.cost:
            best = res
    return float(np.exp(best.x[0])), float(np.exp(best.x[1])), float(np.max(np.abs(resid(best.x))))


def event_probs(m: np.ndarray) -> np.ndarray:
    return m.ravel() @ EV_MASK


def fit_all(p_trip: np.ndarray, p_ou: np.ndarray, seasons: np.ndarray) -> dict:
    n = len(p_ou)
    diag = {k: np.zeros(n) for k in ("A_lam", "A_mu", "A_rho", "A_res",
                                     "B_lam", "B_mu", "B_res", "C_lam", "C_mu", "C_res")}
    P = {k: np.zeros((n, len(EV_NAMES))) for k in ("A", "B", "C")}
    t0 = time.time()
    for i in range(n):
        p1, pX, p2 = p_trip[i]
        pO = p_ou[i]
        fa = fit_implicit(p1, pX, p2, pO, rho_free=True)
        diag["A_lam"][i], diag["A_mu"][i], diag["A_rho"][i] = fa["lam"], fa["mu"], fa["rho"]
        diag["A_res"][i] = fa["max_abs_resid"]
        P["A"][i] = event_probs(dc_matrix(fa["lam"], fa["mu"], fa["rho"]))
        fc = fit_implicit(p1, pX, p2, pO, rho_free=False)
        diag["C_lam"][i], diag["C_mu"][i], diag["C_res"][i] = fc["lam"], fc["mu"], fc["max_abs_resid"]
        P["C"][i] = event_probs(dc_matrix(fc["lam"], fc["mu"], 0.0))
    rho_fix = float(np.median(diag["A_rho"][seasons == "2024/25"]))
    for i in range(n):
        rho_b = 0.0 if seasons[i] == "2024/25" else rho_fix
        p1, pX, p2 = p_trip[i]
        lam, mu, res = fit_fixed_rho(p1, pX, p2, p_ou[i], rho_b)
        diag["B_lam"][i], diag["B_mu"][i], diag["B_res"][i] = lam, mu, res
        P["B"][i] = event_probs(dc_matrix(lam, mu, rho_b))
    return {"diag": diag, "P": P, "rho_fix": rho_fix, "secondi": time.time() - t0}


# ---------------------------------------------------------------------------
# 4. Bootstrap a blocchi
# ---------------------------------------------------------------------------
def block_setup(blocks: np.ndarray, reps: int, seed: int):
    labels, inv = np.unique(blocks, return_inverse=True)
    nb = len(labels)
    rng = np.random.default_rng(seed)
    draws = rng.multinomial(nb, np.full(nb, 1.0 / nb), size=reps).astype(float)
    return inv, nb, draws


def boot_mean(d, inv, nb, draws):
    """Media per partita di d e IC 95% ricampionando blocchi (come griglia_core)."""
    S = np.bincount(inv, weights=d, minlength=nb)
    Nb = np.bincount(inv, minlength=nb).astype(float)
    stat = (draws @ S) / np.maximum(draws @ Nb, 1.0)
    lo, hi = np.percentile(stat, [2.5, 97.5])
    return float(np.mean(d)), float(lo), float(hi)


def boot_fp(num, den, inv, nb, draws):
    """IC 95% di sum(num)/sum(den) ricampionando blocchi (per f - p in una fascia)."""
    S_n = np.bincount(inv, weights=num, minlength=nb)
    S_d = np.bincount(inv, weights=den, minlength=nb)
    n_b = draws @ S_n
    d_b = draws @ S_d
    stat = np.where(d_b > 0, n_b / np.maximum(d_b, 1e-12), np.nan)
    lo, hi = np.nanpercentile(stat, [2.5, 97.5])
    return float(lo), float(hi)


# ---------------------------------------------------------------------------
# 5. Esiti e campioni
# ---------------------------------------------------------------------------
def outcome_indicators(fthg: np.ndarray, ftag: np.ndarray):
    Yev = EV_MASK[fthg * N + ftag, :]                        # n x 11
    O1X2 = np.stack([fthg > ftag, fthg == ftag, fthg < ftag], axis=1).astype(float)
    return Yev, O1X2


def build_main(q: pd.DataFrame):
    ok = (q[["B365H", "B365D", "B365A"]].notna().all(axis=1)
          & q[["B365>2.5", "B365<2.5"]].notna().all(axis=1))
    m = q[ok].reset_index(drop=True)
    p_trip = [devig_prop([a, b, c]) for a, b, c in zip(m.B365H, m.B365D, m.B365A)]
    p_ou = [devig_prop([a, b]) for a, b in zip(m["B365>2.5"], m["B365<2.5"])]
    valid = np.array([t is not None and o is not None for t, o in zip(p_trip, p_ou)])
    m = m[valid].reset_index(drop=True)
    p_trip = np.array([t for t, v in zip(p_trip, valid) if v])
    p_ou = np.array([o[0] for o, v in zip(p_ou, valid) if v])
    return m, p_trip, p_ou


def build_pin(q: pd.DataFrame):
    ok = (q[["PSCH", "PSCD", "PSCA"]].notna().all(axis=1)
          & q[["PC>2.5", "PC<2.5"]].notna().all(axis=1))
    m = q[ok].reset_index(drop=True)
    p_trip = [devig_prop([a, b, c]) for a, b, c in zip(m.PSCH, m.PSCD, m.PSCA)]
    p_ou = [devig_prop([a, b]) for a, b in zip(m["PC>2.5"], m["PC<2.5"])]
    valid = np.array([t is not None and o is not None for t, o in zip(p_trip, p_ou)])
    m = m[valid].reset_index(drop=True)
    p_trip = np.array([t for t, v in zip(p_trip, valid) if v])
    p_ou = np.array([o[0] for o, v in zip(p_ou, valid) if v])
    return m, p_trip, p_ou


def blocks_of(m: pd.DataFrame) -> np.ndarray:
    return (m["league"] + "|" + m["season"] + "|" + m["date_day"].dt.strftime("%Y-%m-%d")).to_numpy()


def get_fits(use_cache: bool, m_main, pt_main, po_main, m_pin, pt_pin, po_pin):
    if use_cache and os.path.exists(CACHE):
        return pd.read_pickle(CACHE)
    fits = {"main": fit_all(pt_main, po_main, m_main["season"].to_numpy()),
            "pin": fit_all(pt_pin, po_pin, m_pin["season"].to_numpy())}
    os.makedirs(OUT_DIR, exist_ok=True)
    pd.to_pickle(fits, CACHE)
    return fits


# ---------------------------------------------------------------------------
# 6. Punto 2: tau cella per cella
# ---------------------------------------------------------------------------
def tau_table(lam: float, mu: float, rho: float):
    """Tre convenzioni, celle (0,0) (0,1) (1,0) (1,1); x = gol casa, lambda = media casa."""
    cells = [(0, 0), (0, 1), (1, 0), (1, 1)]
    prod = {c: tau_correction(c[0], c[1], lam, mu, rho) for c in cells}
    articolo = {(0, 0): 1 - lam * mu * rho, (0, 1): 1 + lam * rho,
                (1, 0): 1 + mu * rho, (1, 1): 1 - rho}
    # penaltyblog 1.13.1, football_probability_grid.py ~l.530-535 (letto dal wheel):
    #   grid[1,0] *= 1 + rho*home_lambda ; grid[0,1] *= 1 + rho*away_lambda
    pb = {(0, 0): 1 - rho * lam * mu, (0, 1): 1 + rho * mu, (1, 0): 1 + rho * lam, (1, 1): 1 - rho}
    return [(c, prod[c], articolo[c], pb[c]) for c in cells]


def tau_effect_on_derivatives(p_lam, p_mu, rho_v):
    """Effetto sui derivati della convenzione INVERTITA (quella di penaltyblog: celle (0,1)/(1,0)
    con lambda e mu scambiati), rispetto alla produzione, a parita' di lambda, mu, rho per partita.
    NON e' applicata in produzione: serve solo a quantificare la differenza."""
    res = []
    for lam, mu, rho in zip(p_lam, p_mu, rho_v):
        base = dc_matrix(lam, mu, rho)
        m = np.outer(poisson.pmf(np.arange(N), lam), poisson.pmf(np.arange(N), mu))
        m[0, 0] *= max(1 - lam * mu * rho, 0.0)
        m[0, 1] *= max(1 + mu * rho, 0.0)     # invertita
        m[1, 0] *= max(1 + lam * rho, 0.0)    # invertita
        m[1, 1] *= max(1 - rho, 0.0)
        m = m / m.sum()
        res.append(event_probs(m) - event_probs(base))
    return np.array(res)


# ---------------------------------------------------------------------------
# 7. Report
# ---------------------------------------------------------------------------
def fmt(x, nd=4):
    """Numero con virgola decimale (stile dei referti di audit)."""
    if x is None or (isinstance(x, (float, np.floating)) and not np.isfinite(x)):
        return "n/d"
    return f"{float(x):.{nd}f}".replace(".", ",")


def pct(x, nd=2):
    """Frazione -> percentuale con virgola."""
    if x is None:
        return "n/d"
    return fmt(100.0 * float(x), nd) + " %"


def pts(x, nd=1):
    """Frazione -> punti percentuali con virgola."""
    if x is None:
        return "n/d"
    return fmt(100.0 * float(x), nd) + " pt"


def md_table(headers, rows):
    head = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join(["---"] * len(headers)) + "|"
    return "\n".join([head, sep] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


REGOLE_MD = """## 0. Regole dichiarate (scritte prima dei numeri)

Le regole sono nel codice (`audit/griglia_varianti.py`, docstring) e nel referto qui sotto; non sono state
modificate dopo aver visto i numeri.

- **R2 (tau).** Confronto cella per cella tra la produzione (`SoccerMath/models/dixon_coles.tau_correction`),
  la formula di Dixon & Coles (1997) come citata in arXiv:2103.07272 eq. (2) con x = gol casa e λ = media casa,
  e la convenzione di penaltyblog 1.13.1. Se la produzione fosse invertita, non si corregge: si misura l'effetto.
- **R3 (scelta della variante).** Metrica: Brier binario per partita sul mercato Gol (No Gol identico).
  d = Brier(X) − Brier(Y); d < 0 ⇒ X migliore. Bootstrap a blocchi lega × stagione × data, 2000 repliche,
  seme 20261010, IC 95% percentile. Passo 1: adottare A solo se l'IC 95% di A−B è interamente sotto zero.
  Passo 2 (altrimenti): adottare B solo se l'IC 95% di B−C è interamente sotto zero. Passo 3 (altrimenti): C.
  Lettura del brief: "altrimenti B" al passo 1 = B è la candidata al posto di A, poi confrontata con C.
  Il sottocampione Pinnacle applica la stessa procedura: è sensibilità, non decide.
- **R4 (calibrazione).** Per ogni coppia evento/complemento e partita si valuta l'esito con p più alta (p ≥ 0,5).
  Fasce di p: [0,55-0,65), [0,65-0,75), ≥ 0,75. IC 95% di f − p con bootstrap a blocchi, 2000 repliche,
  seme 20261011. **Regola:** un mercato entra nella lista delle giocate se in *ogni* fascia con n ≥ 100 l'IC
  di f − p contiene lo zero *oppure* |f − p| ≤ 0,03. Se nessuna fascia ha n ≥ 100, il mercato è
  «non valutabile» e resta fuori (lettura conservativa, dichiarata qui).
- **R5 (punto 5).** Descrittivo, senza regola di decisione. IC 95% bootstrap a blocchi, seme 20261012.
- **R6 (punto 6).** Descrittivo. Stima come PR #58 (R = q_B365 / p_depurata_Pinnacle di apertura, stimato in
  2024/25 per lega × tipo × fascia di quota equa Pinnacle; testato su 2025/26). Errore relativo
  |q̂/q − 1| e assoluto in punti di quota. Fasce per **quota reale** bet365.
- **Derivati (punti 3–4).** Gol/No Gol; Over/Under 1,5 e 3,5; doppia chance 1X, X2, 12; 1+Over 1,5; 2+Over 1,5;
  1X+Over 1,5; 1X+Under 3,5 (elenco del brief). X2+Under 3,5 (in PR #58, non nel brief) è calcolato e marcato
  «extra»; non decide nulla. 1X2 e O/U 2,5 restano fuori.
"""


def build_report(F, meta) -> tuple[str, dict]:
    T = []
    A = T.append
    J = {}
    A("# Griglia implicita: varianti, tau, calibrazione e stima bet365 (audit, sola lettura)\n")
    A(f"Generato da `audit/griglia_varianti.py` il {meta['generato']} · campione principale {meta['n_main']} "
      f"partite · sottocampione Pinnacle {meta['n_pin']} · nessuna modifica a `SoccerMath/`, nessun `--write`, "
      "nessuna chiamata di rete, nessuna chiave.\n")
    A(REGOLE_MD)

    fm, fp = F["main"], F["pin"]
    dm, dp = fm["diag"], fp["diag"]
    ptm, pop = meta["PT_main"], meta["PO_main"]
    A("## 1. Campione e controlli di riproduzione\n")
    rows = []
    for (lg, se), g in meta["m_main"].groupby(["league", "season"], sort=False):
        rows.append([lg, se, len(g)])
    A(md_table(["lega", "stagione", "partite nel campione"], rows))
    A("")
    A(md_table(["variante", "residuo massimo sulle 4 quote (1, X, 2, O 2,5)",
                "partite con residuo > 1e-6"], [
        ["A (DC, rho per partita)", f"max {dm['A_res'].max():.1e}", int((dm["A_res"] > 1e-6).sum())],
        ["B (DC, rho fisso)", f"max {fmt(dm['B_res'].max(), 4)} · mediana {fmt(np.median(dm['B_res']), 4)}",
         int((dm["B_res"] > 1e-6).sum())],
        ["C (Poisson, rho = 0)", f"max {fmt(dm['C_res'].max(), 4)} · mediana {fmt(np.median(dm['C_res']), 4)}",
         int((dm["C_res"] > 1e-6).sum())],
    ]))
    A("")
    A(f"Riferimento PR #58: A riproduce le quote con residuo ≤ 1e-12 (qui: max {dm['A_res'].max():.1e}); "
      f"C ha residuo massimo 0,061 nel referto PR #58 (qui: max {fmt(dm['C_res'].max(), 3)}).\n")
    rho = dm["A_rho"]
    qs = [1, 5, 25, 50, 75, 95, 99]
    A("## 2. Punto 2 — convenzione tau (produzione vs articolo vs penaltyblog)\n")
    lam_ex, mu_ex = 1.0, 1.5
    tt = tau_table(lam_ex, mu_ex, -0.10)
    A(f"Esempio numerico: λ = {fmt(lam_ex, 1)}, μ = {fmt(mu_ex, 1)}, ρ = −0,10 (λ e μ sono i gol attesi di casa e trasferta).\n")
    A(md_table(["cella (x gol casa, y gol trasferta)", "produzione `tau_correction`",
                "Dixon & Coles 1997 (eq. 2 come citata)", "penaltyblog 1.13.1 (letta dal sorgente)"],
               [[f"({c[0]},{c[1]})", fmt(p, 4), fmt(a, 4), fmt(b, 4)] for c, p, a, b in tt]))
    A("")
    J["tau_match_produzione_articolo"] = all(abs(p - a) < 1e-12 for _, p, a, _ in tt)
    J["tau_match_penaltyblog"] = all(abs(p - b) < 1e-12 for _, p, _, b in tt)
    A(f"Produzione = articolo: **{'SÌ' if J['tau_match_produzione_articolo'] else 'NO'}** · "
      f"produzione = penaltyblog: **{'SÌ' if J['tau_match_penaltyblog'] else 'NO'}**.\n")
    A("**Conclusione:** la produzione coincide con l'articolo; è penaltyblog a usare λ e μ scambiati nelle "
      "celle (0,1) e (1,0). La produzione **non** è invertita e non viene modificata. Per quantificare la "
      "differenza che la convenzione penaltyblog produrrebbe sui derivati (scenario NON in produzione), "
      "con i parametri di A per partita:\n")
    A(md_table(["evento", "max abs Δ prob.", "mediana abs Δ"],
               [[nm, fmt(float(np.max(np.abs(meta["tau_eff"][:, j]))), 5),
                 fmt(float(np.median(np.abs(meta["tau_eff"][:, j]))), 6)] for j, nm in enumerate(EV_NAMES)]))
    A("")

    A("## 3. Punto 3 — ρ per partita e confronto delle varianti\n")
    A("### 3.1 Distribuzione di ρ in A (campione principale)\n")
    A(md_table(["percentile"] + [f"p{q}" for q in qs],
               [["ρ"] + [fmt(float(np.percentile(rho, q)), 3) for q in qs]]))
    A("")
    edge = float(np.mean(np.abs(rho) >= EDGE_RHO))
    # quota con cella tau < 0 (clip attivo) in A
    lamA, muA = dm["A_lam"], dm["A_mu"]
    clip = np.mean((1 - lamA * muA * rho < 0) | (1 + lamA * rho < 0) | (1 + muA * rho < 0) | (1 - rho < 0))
    J["rho_edge"] = edge
    J["rho_clip"] = float(clip)
    J["rho_pct"] = {str(q): float(np.percentile(rho, q)) for q in qs}
    A(f"Partite al bordo dei limiti (|ρ| ≥ 0,49, con limiti ±0,5 come in `griglia_core`): **{pct(edge)}**. "
      f"Partite con almeno una cella tau negativa (clip a 0 attivo): **{pct(float(clip))}**. "
      f"ρ mediano 2024/25 = {fmt(float(np.median(rho[meta['s_main'] == '2024/25'])), 3)}, "
      f"2025/26 = {fmt(float(np.median(rho[meta['s_main'] == '2025/26'])), 3)}; "
      f"ρ fisso applicato da B al 2025/26 = **{fmt(fm['rho_fix'], 4)}**.\n")

    A("### 3.2 Brier appaiato su Gol (regola R3)\n")
    res_main = meta["r3_main"]
    A(md_table(["confronto", "ΔBrier (X − Y) per partita", "IC 95% a blocchi", "esito"],
               [[k, fmt(v[0], 5), f"[{fmt(v[1], 5)}; {fmt(v[2], 5)}]",
                 ("X migliore (IC < 0)" if v[2] < 0 else ("Y migliore (IC > 0)" if v[1] > 0 else "nessuna differenza dimostrata"))]
                for k, v in res_main["cmp"].items()]))
    A("")
    A(f"**Decisione R3 (campione principale): variante {res_main['scelta']}.**\n")
    J["r3_main"] = {"scelta": res_main["scelta"], "cmp": res_main["cmp"]}
    A("### 3.3 Tutti i derivati: Brier(A) − Brier(B) e Brier(A) − Brier(C)\n")
    rows = []
    for name in EV_NAMES:
        ab = res_main["all"][name]["AB"]
        ac = res_main["all"][name]["AC"]
        rows.append([name + (" (extra)" if name in EXTRA else ""),
                     f"{fmt(ab[0], 5)} [{fmt(ab[1], 5)}; {fmt(ab[2], 5)}]",
                     f"{fmt(ac[0], 5)} [{fmt(ac[1], 5)}; {fmt(ac[2], 5)}]"])
    A(md_table(["evento (primario)", "A − B: media [IC 95%]", "A − C: media [IC 95%]"], rows))
    A("\nNegativo = A migliore. Il Brier di un evento e del suo complemento è identico.\n")

    A("### 3.4 Sensibilità: sottocampione Pinnacle di chiusura\n")
    res_pin = meta["r3_pin"]
    A(md_table(["confronto", "ΔBrier (X − Y)", "IC 95%", "esito"],
               [[k, fmt(v[0], 5), f"[{fmt(v[1], 5)}; {fmt(v[2], 5)}]",
                 ("X migliore (IC < 0)" if v[2] < 0 else ("Y migliore (IC > 0)" if v[1] > 0 else "nessuna differenza dimostrata"))]
                for k, v in res_pin["cmp"].items()]))
    A(f"\nDecisione sul sottocampione Pinnacle (sola sensibilità): variante {res_pin['scelta']}. "
      f"{'Concorda con il campione principale.' if res_pin['scelta'] == res_main['scelta'] else 'DIVERGE dal campione principale.'}\n")
    J["r3_pin"] = {"scelta": res_pin["scelta"], "cmp": res_pin["cmp"]}

    # ---- punto 4: calibrazione della variante scelta
    scelta = res_main["scelta"]
    P_scelta = F["main_P"][scelta]
    A(f"## 4. Punto 4 — calibrazione dei derivati, variante {scelta}\n")
    A("Per ogni coppia evento/complemento: esito con p più alta per partita (p ≥ 0,5). Fasce [0,55-0,65), "
      "[0,65-0,75), ≥ 0,75. f − p con IC 95% a blocchi (R4).\n")
    Y = meta["Yev"]
    inv4, nb4, dr4 = meta["setup_r4"]
    rows = []
    verdict = []
    for j, name in enumerate(EV_NAMES):
        p_ev = P_scelta[:, j]
        y_ev = Y[:, j]
        side_is_ev = p_ev >= 0.5
        p = np.where(side_is_ev, p_ev, 1 - p_ev)
        y = np.where(side_is_ev, y_ev, 1 - y_ev)
        bandrows = []
        ok_all = True
        n_val = 0
        for bname, (lo, hi) in CAL_BANDS.items():
            m = (p >= lo) & (p < hi)
            n = int(m.sum())
            if n == 0:
                bandrows.append((bname, 0, None, None, None, None, None))
                continue
            d = np.where(m, y - p, 0.0)
            ind = m.astype(float)
            ci_lo, ci_hi = boot_fp(d, ind, inv4, nb4, dr4)
            fp = float(y[m].mean() - p[m].mean())
            bandrows.append((bname, n, float(p[m].mean()), float(y[m].mean()), fp, ci_lo, ci_hi))
            if n >= 100:
                n_val += 1
                passa = (ci_lo <= 0 <= ci_hi) or abs(fp) <= TOL_PT
                ok_all = ok_all and passa
        if n_val == 0:
            esito = "non valutabile (nessuna fascia n ≥ 100)"
        elif ok_all:
            esito = "CALIBRATO: entra nella lista"
        else:
            esito = "non calibrato: resta fuori"
        verdict.append((name, esito))
        rows.append((name, bandrows, esito))
    J["calibr"] = {}
    for name, bandrows, esito in rows:
        A(f"### {name}" + (" (extra)" if name in EXTRA else "") + f" — esiti: {EVENTS[name][1]} / {name}\n")
        tab = []
        for bname, n, p, f, fp, lo, hi in bandrows:
            if n == 0:
                tab.append([bname, 0, "n/d", "n/d", "n/d", "n/d"])
            else:
                tab.append([bname, n, pct(p), pct(f), f"{pts(fp)} [{pts(lo)}; {pts(hi)}]", "sì" if n >= 100 else "no"])
        A(md_table(["fascia di p", "n", "p media", "frequenza f", "f − p [IC 95%]", "conta (n ≥ 100)"], tab))
        A(f"\n**Esito R4: {esito}.**\n")
        J["calibr"][name] = {"esito": esito, "bande": [
            {"fascia": b[0], "n": b[1], "p": b[2], "f": b[3], "fp": b[4], "lo": b[5], "hi": b[6]} for b in bandrows]}
    A("### Lista delle giocate (R4)\n")
    lista = [n for n, e in verdict if e.startswith("CALIBRATO") and n not in EXTRA]
    extra_ok = [n for n, e in verdict if e.startswith("CALIBRATO") and n in EXTRA]
    A("Entrano nella lista (elenco del brief): " + (", ".join(lista) if lista else "**nessun mercato**") + ".\n")
    A("Extra fuori elenco (PR #58, non decide nulla): " + (", ".join(extra_ok) if extra_ok else "nessuno") + ".\n")
    J["lista_giocate"] = lista
    J["extra_calibrati"] = extra_ok

    # ---- punto 5
    A("## 5. Punto 5 — fascia alta su 1X2 (p ≥ 0,65), IC 95%\n")
    A("Stessa tabella con tre metodi di de-vig su B365 (campione principale, 3504) e con il confronto "
      "Pinnacle proporzionale vs B365 sullo stesso sottocampione (2623).\n")
    rows5 = []
    J["punto5"] = {}
    out5 = meta["punto5"]
    for src, methods in out5.items():
        for meth, per_out in methods.items():
            for out_name, rr in per_out.items():
                n, pm, f, fp, lo, hi = rr
                rows5.append([src, meth, out_name, n, pct(pm) if n else "n/d", pct(f) if n else "n/d",
                              f"{pts(fp)} [{pts(lo)}; {pts(hi)}]" if n else "n/d"])
                J["punto5"].setdefault(src, {}).setdefault(meth, {})[out_name] = {
                    "n": n, "p": pm, "f": f, "fp": fp, "lo": lo, "hi": hi}
    A(md_table(["campione / bookmaker", "de-vig", "esito", "n", "p media", "frequenza", "f − p [IC 95%]"], rows5))
    A("")

    # ---- punto 6
    A("## 6. Punto 6 — stima della quota bet365 (fit 2024/25, test 2025/26), coda dell'errore\n")
    e6 = meta["punto6"]
    A("Modello della PR #58 (`lega × tipo × fascia di quota equa Pinnacle`). Fasce per quota **reale** bet365. "
      "Errore relativo = |q̂/q − 1|; errore assoluto = |q̂ − q| in punti di quota.\n")
    rows6 = []
    for band, v in e6["bande"].items():
        if v["n"] == 0:
            rows6.append([band, 0, "n/d", "n/d", "n/d", "n/d", "n/d", "n/d"])
            continue
        rows6.append([band, v["n"], pct(v["med"]), pct(v["p90"]), pct(v["p99"]),
                      fmt(v["abs_med"], 3), fmt(v["abs_p90"], 3), fmt(v["abs_p99"], 3)])
    rows6.append(["**tutte le quote**", e6["n_tot"], pct(e6["tot"]["med"]), pct(e6["tot"]["p90"]),
                  pct(e6["tot"]["p99"]), fmt(e6["tot"]["abs_med"], 3), fmt(e6["tot"]["abs_p90"], 3),
                  fmt(e6["tot"]["abs_p99"], 3)])
    A(md_table(["fascia di quota reale", "n", "errore rel. mediano", "P90", "P99",
                "errore assoluto mediano (quota)", "P90 (quota)", "P99 (quota)"], rows6))
    A(f"\nFuori dalle quattro fasce (quota < 1,20): {e6['fuori']} osservazioni. "
      f"Controllo di parità con PR #58 (errore relativo mediano complessivo, test 2025/26, "
      f"lega × fascia × tipo): {pct(e6['pr_check']['med'])} (PR: 1,36 %); P90 {pct(e6['pr_check']['p90'])} "
      "(PR: 4,09 %).\n")
    J["punto6"] = e6

    A("## 7. Limiti\n")
    A("- Il campione usa la data come proxy della giornata (il CSV non ha la giornata), come PR #58.")
    A("- Le quote B365 «ant.» sono dichiarate pre-partita come in PR #58; l'orario di rilevazione non è nel CSV.")
    A("- Pinnacle di apertura (PS*) per la stima bet365 (punto 6), chiusura (PSC*) per il punto 5: come PR #58.")
    A("- I derivati 1X+Under 3,5 e Over/Under 1,5 / 3,5 non sono quotati nel campione: sono ricavati dalla griglia, "
      "quindi la calibrazione misura la griglia, non una quota diretta.")
    A("- La calibrazione non dice nulla sul valore economico di una giocata a quota.")
    A("- Il tau di produzione e il fit per partita sono quelli di PR #58; nessuna variante tocca la produzione.\n")
    return "\n".join(T) + "\n", J


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args(argv)
    t0 = time.time()

    q = load_all()
    m_main, pt_main, po_main = build_main(q)
    m_pin, pt_pin, po_pin = build_pin(q)
    n_main, n_pin = len(m_main), len(m_pin)
    if n_main != 3504:
        raise SystemExit(f"campione principale {n_main} != 3504 (PR #58)")
    if n_pin != 2623:
        raise SystemExit(f"sottocampione Pinnacle {n_pin} != 2623 (PR #58)")
    print(f"[varianti] campione {n_main} · Pinnacle {n_pin}", flush=True)

    F = get_fits(not args.no_cache, m_main, pt_main, po_main, m_pin, pt_pin, po_pin)
    F_main, F_pin = F["main"], F["pin"]
    print(f"[varianti] fit in {F_main['secondi'] + F_pin['secondi']:.0f}s", flush=True)

    blocks_m = blocks_of(m_main)
    blocks_p = blocks_of(m_pin)
    Yev_m, O_m = outcome_indicators(m_main["FTHG"].to_numpy().astype(int), m_main["FTAG"].to_numpy().astype(int))
    Yev_p, O_p = outcome_indicators(m_pin["FTHG"].to_numpy().astype(int), m_pin["FTAG"].to_numpy().astype(int))

    # --- punto 3: decisione R3 (campione principale e Pinnacle)
    def decide(Pdict, Yev, blocks):
        inv, nb, dr = block_setup(blocks, REPS, SEED_R3)
        jG = EV_IDX["Gol"]
        Ba, Bb, Bc = (brier_per_match(Pdict[k], Yev)[:, jG] for k in ("A", "B", "C"))
        ab = boot_mean(Ba - Bb, inv, nb, dr)
        bc = boot_mean(Bb - Bc, inv, nb, dr)
        if ab[2] < 0:
            scelta = "A"
        elif bc[2] < 0:
            scelta = "B"
        else:
            scelta = "C"
        cmp = {"A − B (Gol)": ab, "B − C (Gol)": bc}
        allm = {}
        BA_ = brier_per_match(Pdict["A"], Yev)
        BB_ = brier_per_match(Pdict["B"], Yev)
        BC_ = brier_per_match(Pdict["C"], Yev)
        for j, name in enumerate(EV_NAMES):
            allm[name] = {"AB": boot_mean(BA_[:, j] - BB_[:, j], inv, nb, dr),
                          "AC": boot_mean(BA_[:, j] - BC_[:, j], inv, nb, dr)}
        return {"scelta": scelta, "cmp": cmp, "all": allm}

    r3_main = decide(F_main["P"], Yev_m, blocks_m)
    r3_pin = decide(F_pin["P"], Yev_p, blocks_p)
    print(f"[varianti] R3 campione principale: {r3_main['scelta']} · Pinnacle: {r3_pin['scelta']}", flush=True)

    # --- bootstrap R4, R5
    setup_r4 = block_setup(blocks_m, REPS, SEED_R4)
    setup_r5 = block_setup(blocks_m, REPS, SEED_R5)
    setup_r5p = block_setup(blocks_p, REPS, SEED_R5)

    # --- punto 5
    punto5 = OrderedDict()
    specs5 = [("B365 (3504)", m_main, O_m, setup_r5, "B365"),
              ("B365 (2623)", m_pin, O_p, setup_r5p, "B365"),
              ("Pinnacle (2623)", m_pin, O_p, setup_r5p, "PIN")]
    for src, mm, Ouc, (inv5_, nb5_, dr5_), book in specs5:
        if book == "B365":
            cols, methods = ["B365H", "B365D", "B365A"], list(DEVIG.items())
        else:
            cols, methods = ["PSCH", "PSCD", "PSCA"], [("proporzionale", devig_prop)]
        block_out = OrderedDict()
        for meth, fn in methods:
            P3 = np.array([fn([a, b, c]) for a, b, c in zip(mm[cols[0]], mm[cols[1]], mm[cols[2]])], dtype=float)
            outs = OrderedDict()
            for k, oname in enumerate(["1", "X", "2"]):
                p = P3[:, k]
                mask = (p >= HIGH[0]) & (p < HIGH[1])
                n = int(mask.sum())
                if n == 0:
                    outs[oname] = (0, None, None, None, None, None)
                    continue
                y = Ouc[:, k]
                d = np.where(mask, y - p, 0.0)
                lo, hi = boot_fp(d, mask.astype(float), inv5_, nb5_, dr5_)
                outs[oname] = (n, float(p[mask].mean()), float(y[mask].mean()),
                               float(y[mask].mean() - p[mask].mean()), lo, hi)
            block_out[meth] = outs
        punto5[src] = block_out
    # --- punto 6: stima bet365 (PR #58 §8.3)
    e6 = punto6(q)

    # --- punto 2
    mm_lam = F_main["diag"]["A_lam"]
    mm_mu = F_main["diag"]["A_mu"]
    rho_all = F_main["diag"]["A_rho"]
    tau_eff = tau_effect_on_derivatives(mm_lam, mm_mu, rho_all)

    meta = {
        "generato": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_main": n_main, "n_pin": n_pin, "m_main": m_main, "s_main": m_main["season"].to_numpy(),
        "PT_main": pt_main, "PO_main": po_main,
        "r3_main": r3_main, "r3_pin": r3_pin,
        "Yev": Yev_m, "setup_r4": setup_r4, "setup_r5": setup_r5, "setup_r5p": setup_r5p,
        "punto5": punto5, "punto6": e6, "tau_eff": tau_eff,
    }
    F_out = {"main": F_main, "pin": F_pin, "main_P": F_main["P"]}
    text, J = build_report(F_out, meta)
    J["tau_effetto_derivati_se_invertita"] = {
        "max_abs_delta_per_evento": {EV_NAMES[j]: float(np.max(np.abs(tau_eff[:, j]))) for j in range(len(EV_NAMES))},
    }
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write(text)
    with open(JSON_OUT, "w", encoding="utf-8") as fh:
        json.dump(J, fh, ensure_ascii=False, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
    print(f"[varianti] referto: {REPORT} · {time.time() - t0:.0f}s", flush=True)
    return 0


def punto6(q: pd.DataFrame) -> dict:
    """Replica della stima bet365 di PR #58 §8.3 (fit 2024/25, test 2025/26)."""
    recs = []
    specs = [
        ("1X2", ["B365H", "B365D", "B365A"], ["PSH", "PSD", "PSA"]),
        ("O/U 2,5", ["B365<2.5", "B365>2.5"], ["P<2.5", "P>2.5"]),
    ]
    for tipo, bcols, pcols in specs:
        sub = q[["league", "season", "date_day", "home", "away"] + bcols + pcols].dropna()
        for r in sub.to_dict("records"):
            b = np.array([r[c] for c in bcols], dtype=float)
            p = np.array([r[c] for c in pcols], dtype=float)
            fair = devig_prop(p)
            if fair is None or np.any(b <= 1.0):
                continue
            for k in range(len(bcols)):
                fb = 1.0 / fair[k]
                band = "<1,50" if fb < 1.5 else "1,50-2,00" if fb < 2.0 else "2,00-3,00" if fb < 3.0 else \
                    "3,00-5,00" if fb < 5.0 else "≥5,00"
                recs.append({"tipo": tipo, "lega": r["league"], "stagione": r["season"], "quota_b": b[k],
                             "p_fair": fair[k], "fascia": band, "r": (1.0 / b[k]) / fair[k]})
    pre = pd.DataFrame(recs)
    tr = pre[pre.stagione == "2024/25"]
    te = pre[pre.stagione == "2025/26"].copy()
    Rd = tr.groupby(["lega", "tipo", "fascia"])["r"].median().to_dict()
    keys = list(zip(te.lega, te.tipo, te.fascia))
    Rv = np.array([Rd.get(k, np.nan) for k in keys], dtype=float)
    ok = np.isfinite(Rv)
    pred = 1.0 / (te["p_fair"].to_numpy()[ok] * Rv[ok])
    b = te["quota_b"].to_numpy()[ok]
    rel = np.abs(pred / b - 1.0)
    ab = np.abs(pred - b)
    bins = OrderedDict([("1,20-1,50", (1.20, 1.50)), ("1,50-2,00", (1.50, 2.00)),
                        ("2,00-3,00", (2.00, 3.00)), ("oltre 3,00", (3.00, 1e9))])
    out = {"n_tot": int(ok.sum()), "tot": {"med": float(np.median(rel)), "p90": float(np.quantile(rel, 0.9)),
                                          "p99": float(np.quantile(rel, 0.99)),
                                          "abs_med": float(np.median(ab)), "abs_p90": float(np.quantile(ab, 0.9)),
                                          "abs_p99": float(np.quantile(ab, 0.99))},
           "bande": {}, "fuori": int(np.sum((b < 1.20)))}
    for name, (lo, hi) in bins.items():
        m = (b >= lo) & (b < hi)
        if m.sum() == 0:
            out["bande"][name] = {"n": 0, "med": None, "p90": None, "p99": None,
                                  "abs_med": None, "abs_p90": None, "abs_p99": None}
            continue
        out["bande"][name] = {"n": int(m.sum()), "med": float(np.median(rel[m])),
                              "p90": float(np.quantile(rel[m], 0.9)), "p99": float(np.quantile(rel[m], 0.99)),
                              "abs_med": float(np.median(ab[m])), "abs_p90": float(np.quantile(ab[m], 0.9)),
                              "abs_p99": float(np.quantile(ab[m], 0.99))}
    out["pr_check"] = {"med": out["tot"]["med"], "p90": out["tot"]["p90"]}
    return out


if __name__ == "__main__":
    sys.exit(main())
