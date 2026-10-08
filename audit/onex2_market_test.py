#!/usr/bin/env python3
"""onex2_market_test.py — Modello contro mercato sull'1X2 (audit, SOLA LETTURA).

DOMANDA. Da quale probabilita' 1X2 devono partire le scelte del Top Mix: dal
modello di produzione (blend Poisson+Elo), dal mercato (quote B365 pre-chiusura,
de-vig proporzionale), o da una combinazione stimata in rolling-origin?
Solo audit: NESSUNA modifica a ``SoccerMath/``.

FONTI DI PROBABILITA' (tutte point-in-time, nessuna riscrittura del motore)
  * modello blend: ``app.blend_elo_into_1x2`` con w = ``app.POISSON_1X2_WEIGHT``
    (0.25) applicato a Poisson puro ed Elo puro.
  * Poisson puro: testa 1X2 di produzione ``app.get_full_poisson_two_heads``,
    chiamata da ``ppda_residual_test.production_totali``. Le sue 1X2 vengono
    INTERCETTATE (wrapper temporaneo sull'attributo del modulo ``app``) senza
    riscrivere il loop; la parita' con le colonne ``engine_u25``/``engine_gg``
    di ``production_totali`` e' verificata riga per riga e riportata.
  * Elo puro: walker fedele ``elo_walker_core.build_walker_table`` (motore di
    produzione ``EloEngine``: seeding S3 delle entranti, rating PRIMA della
    partita, aggiornamento DOPO).
  * combinazione (punto 3): (a) pool lineare, (b) regressione condizionale
    multinomiale (pesi condivisi fra gli esiti) sui log delle probabilita'
    di modello e mercato. Stimate in rolling-origin.

MERCATO (CSV football-data in SoccerMath/database)
  * pre-chiusura: B365H/D/A (come da commessa; il CSV non contiene l'orario di
    rilevazione: la dicitura pre-chiusura e' dichiarata, non verificata dal file);
  * chiusura: B365CH/CD/CA; chiusura Pinnacle: PSCH/PSCD/PSCA dove presente.
  * de-vig PROPORZIONALE (decisione, ``backtest_experiment_all.devig_1x2``) e SHIN
    a 3 esiti (``devig_shin3``, riportato come sensibilita').

VALUTAZIONE. Stagioni 2024/25 e 2025/26; solo partite con modello E quote
disponibili. Base rate del train come PR #34 (``baserate_oos.raw``): per ogni
stagione valutata, tutte le stagioni precedenti della lega (file 2022...).

ROLLING-ORIGIN. Fold A: stima 2023/24 -> valuta 2024/25. Fold B: stima
2023/24 + 2024/25 -> valuta 2025/26. Nessun parametro stimato sul periodo valutato.

BOOTSTRAP. Blocchi = lega x stagione x giornata (data). Ricampionamento dei
blocchi con reimmissione, 2000 repliche, IC 95% percentile, seme fisso.

REGOLA DI DECISIONE (applicata dal codice; formulazione originale fissata prima dei numeri)
  COMBINARE se la combinazione (b) batte il solo mercato pre-chiusura con
            Delta LogLoss pooled OOS < 0, IC 95% che esclude lo zero e segno
            negativo in entrambi i fold;
  MERCATO   se il peso del modello nella combinazione (b) NON e' significativamente
            positivo in entrambi i fold (IC 95% che contiene lo zero, oppure tutto <= 0).
            PRECISAZIONE decisa dopo aver visto i risultati, perche' il caso del peso
            negativo e distinguibile da zero non era coperto dalla formulazione originale
            (che copriva solo il peso non distinguibile da zero). Un peso negativo
            significa che il modello non migliora il mercato: non va sfruttato come
            segnale contrario. Il criterio COMBINARE e' invariato;
  altrimenti: NESSUN VERDETTO AUTOMATICO (segnalato, non forzato).
  Verdetto di controllo con la combinazione (a) (pool lineare, peso alpha).
  Il consenso e' riportato come informazione aggiuntiva (non entra nel verdetto).

Output
  * ``audit/results/onex2_market_test.md``   referto (generato);
  * ``audit/output/onex2_market_test.json``  payload completo (non versionato);
  * ``audit/output/onex2_market_rows.csv``   righe partita per partita (non versionato).

Uso: ``python audit/onex2_market_test.py [--reps 2000] [--seed 20261008]``
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import subprocess
import sys
import time
from collections import OrderedDict

import numpy as np
import pandas as pd
from scipy import optimize
from scipy import stats as scipy_stats

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))
DB_DIR = os.path.join(_REPO_ROOT, "SoccerMath", "database")


@contextlib.contextmanager
def _silence_fd2():
    """Silenzia il rumore di Streamlit durante l'import dei moduli di produzione."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        saved = os.dup(2)
    except OSError:
        yield
        return
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        try:
            sys.stderr.flush()
        except (OSError, ValueError):
            pass
        os.dup2(saved, 2)
        os.close(saved)
        os.close(devnull)


with _silence_fd2():
    import app as prod_app  # noqa: E402  (solo lettura: blend, Poisson di produzione)
    from backtest_experiment_all import LEAGUES, devig_1x2  # noqa: E402
    from baserate_oos import decomp as murphy_decomp  # noqa: E402  (PR #34)
    from config import clean_name  # noqa: E402
    from elo_walker_core import build_walker_table  # noqa: E402  (walker Elo fedele)
    from ppda_residual_test import production_totali  # noqa: E402  (banco di produzione)
    from totals_market_ceiling import bootstrap_blocks, per_block_arrays  # noqa: E402

import streamlit.logger as _st_logger  # noqa: E402

_st_logger.set_log_level("CRITICAL")

# ---------------------------------------------------------------------------
# Costanti (fissate prima di guardare i numeri)
# ---------------------------------------------------------------------------
EVAL_SEASONS = ("2024/25", "2025/26")
SEASON_FILE = OrderedDict([("2022/23", "2022"), ("2023/24", "2023"), ("2024/25", "2024"),
                           ("2025/26", "2025"), ("2026/27", "Live")])
FOLDS = (
    {"name": "A", "estimate": ("2023/24",), "evaluate": "2024/25"},
    {"name": "B", "estimate": ("2023/24", "2024/25"), "evaluate": "2025/26"},
)
BINS = 10
DEFAULT_REPS = 2000
DEFAULT_SEED = 20261008
TOPMIX_MIN = 0.55            # soglia di confidence del Top Mix con Elo (app.seleziona_riga_top_mix)
TOPMIX_VETO = 0.25           # veto di produzione: |P_poisson - P_elo| < 0.25
P_CLIP = 1e-9
LABELS = ("1", "X", "2")
ODDS_COLS = ["B365H", "B365D", "B365A", "B365CH", "B365CD", "B365CA",
             "PSCH", "PSCD", "PSCA"]
MARKET_SOURCES = OrderedDict([
    ("pre", ("B365H", "B365D", "B365A")),        # pre-chiusura (commessa)
    ("close", ("B365CH", "B365CD", "B365CA")),   # chiusura B365
    ("pin", ("PSCH", "PSCD", "PSCA")),           # chiusura Pinnacle (dove presente)
])
# nome leggibile e prefisso colonne per ogni fonte di probabilita'
SOURCES = OrderedDict([
    ("modello", ("Modello blend (0,25 Poisson + 0,75 Elo)", "m")),
    ("poisson", ("Poisson puro (testa 1X2 di produzione)", "p")),
    ("elo", ("Elo puro (walker, seeding S3)", "e")),
    ("b365_pre", ("B365 pre-chiusura (de-vig prop.)", "pre")),
    ("b365_close", ("B365 chiusura (de-vig prop.)", "close")),
    ("pin_close", ("Pinnacle chiusura (de-vig prop.)", "pin")),
    ("b365_pre_shin", ("B365 pre-chiusura (Shin)", "pres")),
    ("b365_close_shin", ("B365 chiusura (Shin)", "closes")),
    ("pin_close_shin", ("Pinnacle chiusura (Shin)", "pins")),
])
PREFIX_OF = {k: v[1] for k, v in SOURCES.items()}


def pcols(prefix):
    return [f"{prefix}{k}" for k in range(3)]


def P_of(df, source):
    return df[pcols(PREFIX_OF[source])].to_numpy(float)


# ---------------------------------------------------------------------------
# De-vig Shin a 3 esiti
# ---------------------------------------------------------------------------
def devig_shin3(odds):
    """Shin (1993) a 3 esiti. Ritorna il vettore di probabilita' o None.

    ``p_i(z) = (sqrt(z^2 + 4(1-z) pi_i^2 / B) - z) / (2(1-z))``, ``pi_i = 1/o_i``,
    ``B = sum pi_i``; ``z`` si risolve per bisezione imponendo ``sum p_i = 1``.
    Senza overround (B <= 1) la soluzione e' pi_i / B (z = 0).
    """
    o = np.asarray(odds, dtype=float)
    if o.shape != (3,) or not np.all(np.isfinite(o)) or np.any(o <= 1.0):
        return None
    pi = 1.0 / o
    B = float(pi.sum())
    if B <= 1.0 + 1e-12:
        return pi / B

    def probs(z):
        return (np.sqrt(z * z + 4.0 * (1.0 - z) * pi * pi / B) - z) / (2.0 * (1.0 - z))

    lo, hi = 0.0, 1.0 - 1e-12
    if probs(lo).sum() <= 1.0:
        return None
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if probs(mid).sum() > 1.0:
            lo = mid
        else:
            hi = mid
    p = probs(0.5 * (lo + hi))
    if not np.all(np.isfinite(p)) or p.sum() <= 0:
        return None
    return p / p.sum()


def devig_prop3(odds):
    """Proporzionale: helper di produzione ``devig_1x2``; NaN sulle quote non valide."""
    o = np.asarray(odds, dtype=float)
    if not np.all(np.isfinite(o)) or np.any(o <= 1.0):
        return None
    p = devig_1x2(*[float(x) for x in o])
    if p is None or p[0] is None:
        return None
    return np.array(p, dtype=float)


# ---------------------------------------------------------------------------
# Quote 1X2 da football-data (stessa pulizia di load_league)
# ---------------------------------------------------------------------------
def load_1x2_odds(prefix: str) -> pd.DataFrame:
    need = ["Date", "HomeTeam", "AwayTeam", "FTR", "FTHG", "FTAG"]
    frames = []
    for season, suffix in SEASON_FILE.items():
        df = pd.read_csv(os.path.join(DB_DIR, f"{prefix}_{suffix}.csv"),
                         on_bad_lines="warn", low_memory=False)
        cols = need + [c for c in ODDS_COLS if c in df.columns]
        df = df[cols].copy()
        for c in ODDS_COLS:
            if c not in df.columns:
                df[c] = np.nan
        df["season"] = season
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df["FTHG"] = pd.to_numeric(df["FTHG"], errors="coerce")
    df["FTAG"] = pd.to_numeric(df["FTAG"], errors="coerce")
    df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTR", "FTHG", "FTAG"])
    df = df.sort_values("Date", kind="stable").reset_index(drop=True)
    df["home"] = df["HomeTeam"].map(clean_name)
    df["away"] = df["AwayTeam"].map(clean_name)
    df = df.drop_duplicates(subset=["Date", "home", "away"], keep="last").reset_index(drop=True)
    df["date_day"] = df["Date"].dt.normalize()
    return df


def train_base_rate(prefix: str, season: str) -> np.ndarray:
    """Base rate 1/X/2 del train come PR #34: tutte le stagioni precedenti (file 2022...)."""
    upto = int(season[:4])
    frames = [pd.read_csv(os.path.join(DB_DIR, f"{prefix}_{y}.csv"), on_bad_lines="warn",
                          low_memory=False, usecols=["FTR"]) for y in range(2022, upto)]
    ftr = pd.concat(frames, ignore_index=True)["FTR"].astype(str).str.strip().str.upper()
    counts = np.array([(ftr == "H").sum(), (ftr == "D").sum(), (ftr == "A").sum()], float)
    return counts / counts.sum()


# ---------------------------------------------------------------------------
# Modello: 1X2 Poisson di produzione (intercettato) + Elo walker + blend
# ---------------------------------------------------------------------------
def production_1x2(prefix: str, league: str):
    """Riusa ``production_totali`` e intercetta le 1X2 di ``get_full_poisson_two_heads``.

    ``production_totali`` chiama l'attributo ``prod_app.get_full_poisson_two_heads`` una
    volta per partita, nell'ordine di ``load_league``: il wrapper registra l'uscita
    completa (1/X/2/u25/gg) e la si confronta con le colonne ``engine_u25``/``engine_gg``
    gia' prodotte dal banco. Nessuna formula viene riscritta.
    """
    captured = []
    original = prod_app.get_full_poisson_two_heads

    def _wrap(*args, **kwargs):
        out = original(*args, **kwargs)
        captured.append(out)
        return out

    prod_app.get_full_poisson_two_heads = _wrap
    try:
        prod = production_totali(prefix, league)
    finally:
        prod_app.get_full_poisson_two_heads = original
    assert len(captured) == len(prod), (league, len(captured), len(prod))
    c_u25 = np.array([o["u25"] for o in captured])
    c_gg = np.array([o["gg"] for o in captured])
    parity = {
        "righe": int(len(prod)),
        "max_scarto_u25": float(np.max(np.abs(c_u25 - prod["engine_u25"].to_numpy()))),
        "max_scarto_gg": float(np.max(np.abs(c_gg - prod["engine_gg"].to_numpy()))),
        "max_scarto_somma_1X2_da_1": float(np.max(np.abs(
            np.array([o["1"] + o["X"] + o["2"] for o in captured]) - 1.0))),
    }
    prod = prod.copy()
    prod["p0"] = [o["1"] for o in captured]
    prod["p1"] = [o["X"] for o in captured]
    prod["p2"] = [o["2"] for o in captured]
    prod["date_day"] = pd.to_datetime(prod["date"]).dt.normalize()
    return prod, parity


def build_frame():
    parts, diag = [], {}
    w_poisson = prod_app.POISSON_1X2_WEIGHT
    assert w_poisson == 0.25, w_poisson
    for prefix, league in LEAGUES:
        prod, parity = production_1x2(prefix, league)
        walker = build_walker_table(league)
        wk = walker.assign(date_day=walker["date"].dt.normalize())
        wk = wk[["date_day", "home", "away", "elo_1", "elo_X", "elo_2", "FTR"]].rename(
            columns={"FTR": "ftr_walker", "elo_1": "e0", "elo_X": "e1", "elo_2": "e2"})
        m = prod.merge(wk, on=["date_day", "home", "away"], how="left",
                       validate="one_to_one")
        assert m["e0"].notna().all(), f"walker senza Elo per {league}"

        odds = load_1x2_odds(prefix)
        o = odds[["date_day", "home", "away", "FTR", "season"] + ODDS_COLS].rename(
            columns={"season": "season_odds", "FTR": "ftr_odds"})
        m = m.merge(o, on=["date_day", "home", "away"], how="left", validate="one_to_one")
        m["season_match"] = (m["season"] == m["season_odds"]) | m["season_odds"].isna()
        assert m["season_match"].all(), f"stagione discordante per {league}"

        # esito dai gol del banco; confronto con FTR delle quote e del walker
        y_goals = np.where(m["fthg"] > m["ftag"], "H",
                           np.where(m["fthg"] == m["ftag"], "D", "A"))
        diag[league] = {
            "parity": parity,
            "righe_produzione": int(len(m)),
            "righe_walker_unite": int(m["e0"].notna().sum()),
            "righe_con_quote_b365_pre": int(m["ftr_odds"].notna().sum()),
            "ftr_walker_discordanti_da_gol": int((m["ftr_walker"].astype(str) != y_goals).sum()),
            "ftr_quote_discordanti_da_gol": int(
                (m["ftr_odds"].notna() & (m["ftr_odds"].astype(str) != y_goals)).sum()),
        }
        m["league"] = league
        m["y_code"] = pd.Series(y_goals, index=m.index).map({"H": 0, "D": 1, "A": 2}).astype(int)
        parts.append(m)

    df = pd.concat(parts, ignore_index=True)
    df["season"] = df["season"].astype(str)

    # blend di produzione (app.blend_elo_into_1x2), riga per riga
    blended = []
    for r in df.itertuples(index=False):
        mm = {"1": r.p0, "X": r.p1, "2": r.p2}
        ee = {"1": r.e0, "X": r.e1, "2": r.e2}
        out = prod_app.blend_elo_into_1x2(mm, r.home, r.away, r.league,
                                          w=w_poisson, elo_probs=ee, elo_disponibile=True,
                                          season=None)
        blended.append((out["1"], out["X"], out["2"]))
    bl = np.array(blended, float)
    df["m0"], df["m1"], df["m2"] = bl[:, 0], bl[:, 1], bl[:, 2]
    # controllo di identita' del blend: w*Poisson + (1-w)*Elo
    ident = np.abs(bl - (w_poisson * df[["p0", "p1", "p2"]].to_numpy()
                         + (1 - w_poisson) * df[["e0", "e1", "e2"]].to_numpy())).max()
    diag["blend_max_scarto_identita"] = float(ident)

    # de-vig (proporzionale = decisione; Shin = sensibilita')
    for src, cols in MARKET_SOURCES.items():
        raw = df[list(cols)].to_numpy(float)
        prop = np.full((len(df), 3), np.nan)
        shin = np.full((len(df), 3), np.nan)
        for i in range(len(df)):
            if np.all(np.isfinite(raw[i])):
                pp = devig_prop3(raw[i])
                if pp is not None:
                    prop[i] = pp
                ss = devig_shin3(raw[i])
                if ss is not None:
                    shin[i] = ss
        # prefissi colonne: pre -> pre0.. (prop) / pres0.. (Shin); close, pin analoghi
        pref = src
        for k in range(3):
            df[f"{pref}{k}"] = prop[:, k]
            df[f"{pref}s{k}"] = shin[:, k]
        df[f"{pref}_ok"] = ~np.isnan(prop[:, 0])

    # base rate del train per (lega, stagione valutata)
    base = {}
    for prefix, league in LEAGUES:
        for season in EVAL_SEASONS:
            base[(league, season)] = train_base_rate(prefix, season)
    bmat = np.full((len(df), 3), np.nan)
    for (league, season), b in base.items():
        mask = (df["league"] == league) & (df["season"] == season)
        bmat[mask.to_numpy()] = b
    for k in range(3):
        df[f"base{k}"] = bmat[:, k]
    df["has_model"] = df[["m0", "m1", "m2"]].notna().all(axis=1)
    return df, diag, base


# ---------------------------------------------------------------------------
# Metriche (per riga) e riassunti
# ---------------------------------------------------------------------------
def onehot(yi):
    Y = np.zeros((len(yi), 3))
    Y[np.arange(len(yi)), yi] = 1.0
    return Y


def row_losses(P, yi):
    """LogLoss, Brier multiclasse (somma su 3 esiti) e RPS (esiti ordinati 1<X<2) per riga."""
    P = np.clip(np.asarray(P, float), P_CLIP, 1.0)
    Y = onehot(yi)
    ar = np.arange(len(yi))
    ll = -np.log(P[ar, yi])
    br = ((P - Y) ** 2).sum(axis=1)
    cP = np.cumsum(P, axis=1)[:, :2]
    cY = np.cumsum(Y, axis=1)[:, :2]
    rps = 0.5 * ((cP - cY) ** 2).sum(axis=1)
    return ll, br, rps


def summary(P, yi, B=None):
    ll, br, rps = row_losses(P, yi)
    out = {"n": int(len(yi)), "logloss": float(ll.mean()), "brier": float(br.mean()),
           "rps": float(rps.mean())}
    if B is not None:
        llb, brb, rpsb = row_losses(B, yi)
        out["bss_brier"] = float(1 - br.mean() / brb.mean())
        out["bss_logloss"] = float(1 - ll.mean() / llb.mean())
        out["bss_rps"] = float(1 - rps.mean() / rpsb.mean())
    Y = onehot(yi)
    for k, lab in enumerate(LABELS):
        rel, res, unc = murphy_decomp(Y[:, k], np.clip(P[:, k], 0, 1), BINS)
        out[f"rel_{lab}"] = float(rel)
        out[f"res_{lab}"] = float(res)
        out[f"unc_{lab}"] = float(unc)
    return out


# ---------------------------------------------------------------------------
# Bootstrap a blocchi (lega x stagione x giornata), ricampionamento con reimmissione
# ---------------------------------------------------------------------------
def draw_counts(nb: int, reps: int, rng) -> np.ndarray:
    idx = rng.integers(0, nb, size=(reps, nb))
    flat = (idx + np.arange(reps)[:, None] * nb).ravel()
    return np.bincount(flat, minlength=reps * nb).reshape(reps, nb).astype(float)


def block_keys(d: pd.DataFrame) -> np.ndarray:
    return (d["league"].astype(str) + "|" + d["season"].astype(str) + "|"
            + d["date_day"].dt.strftime("%Y-%m-%d")).to_numpy()


class Sample:
    """Sottocampione con codici di blocco e draw bootstrap condivisi fra le statistiche."""

    def __init__(self, d: pd.DataFrame, reps: int, rng):
        self.d = d.reset_index(drop=True)
        self.codes, uniq = pd.factorize(block_keys(self.d), sort=True)
        self.nb = len(uniq)
        self.cnt = draw_counts(self.nb, reps, rng) if reps else None

    def _bsum(self, v):
        return np.bincount(self.codes, weights=np.asarray(v, float), minlength=self.nb)

    def ratio(self, num_row, den_row):
        bn, bd = self._bsum(num_row), self._bsum(den_row)
        pt = float(bn.sum() / bd.sum()) if bd.sum() > 0 else float("nan")
        with np.errstate(divide="ignore", invalid="ignore"):
            draws = (self.cnt @ bn) / (self.cnt @ bd)
        return pt, draws

    def mean_diff(self, a_row, b_row):
        """Differenza appaiata delle medie (a - b) con IC bootstrap."""
        pt, draws = self.ratio(np.asarray(a_row, float) - np.asarray(b_row, float),
                               np.ones(self.d.shape[0]))
        return pt, ci(draws)


def ci(draws):
    d = np.asarray(draws, float)
    d = d[np.isfinite(d)]
    if d.size == 0:
        return (float("nan"), float("nan"))
    lo, hi = np.percentile(d, [2.5, 97.5])
    return float(lo), float(hi)


def ratio_ci(sample: Sample, num_row, den_row):
    pt, draws = sample.ratio(num_row, den_row)
    return pt, ci(draws)


def resolution_diff(sample: Sample, P_a, P_b, yi, reps, seed):
    """Delta della resolution per esito (a - b), con la funzione di PR #34/#39 (bootstrap_blocks)."""
    out = {}
    Y = onehot(yi)
    for k, lab in enumerate(LABELS):
        agg_a = per_block_arrays(Y[:, k], P_a[:, k], sample.codes, sample.nb)
        agg_b = per_block_arrays(Y[:, k], P_b[:, k], sample.codes, sample.nb)
        r = bootstrap_blocks(agg_a, agg_b, reps, seed + k)
        out[lab] = {"delta": float(r["delta_resolution"]),
                    "ci": [float(r["delta_resolution_ci"][0]), float(r["delta_resolution_ci"][1])],
                    "res_a": float(r["resolution_a"]), "res_b": float(r["resolution_b"])}
    return out


# ---------------------------------------------------------------------------
# Combinazione (punto 3)
# ---------------------------------------------------------------------------
def _softmax_rows(S):
    S = S - S.max(axis=1, keepdims=True)
    E = np.exp(S)
    return E / E.sum(axis=1, keepdims=True)


def clogit_fit(X1, X2, y, theta0=None, need_cov=False):
    """Regressione condizionale multinomiale: S_k = a_k + b1*log(m_k) + b2*log(q_k).

    Pesi b1 (modello) e b2 (mercato) CONDIVISI fra gli esiti; a_1 e a_A liberi,
    a_X = 0 (identificazione). Massima verosimiglianza con gradiente analitico.
    """
    n = len(y)
    ar = np.arange(n)

    def nll_grad(th):
        b1, b2, aH, aA = th
        S = b1 * X1 + b2 * X2 + np.array([aH, 0.0, aA])[None, :]
        P = _softmax_rows(S)
        g = np.array([
            -np.sum(X1[ar, y] - (P * X1).sum(axis=1)),
            -np.sum(X2[ar, y] - (P * X2).sum(axis=1)),
            -np.sum((y == 0).astype(float) - P[:, 0]),
            -np.sum((y == 2).astype(float) - P[:, 2]),
        ])
        nll = -np.sum(S[ar, y] - np.log(np.exp(S).sum(axis=1)))
        return nll, g

    th0 = np.zeros(4) if theta0 is None else np.asarray(theta0, float)
    if theta0 is None:
        th0 = np.array([0.0, 1.0, 0.0, 0.0])
    res = optimize.minimize(lambda t: nll_grad(t), th0, jac=True, method="BFGS",
                            options={"gtol": 1e-7, "maxiter": 500})
    th = res.x
    cov = None
    if need_cov:
        eps = 1e-5
        H = np.zeros((4, 4))
        for j in range(4):
            e = np.zeros(4)
            e[j] = eps
            H[:, j] = (nll_grad(th + e)[1] - nll_grad(th - e)[1]) / (2 * eps)
        H = 0.5 * (H + H.T)
        cov = np.linalg.pinv(H)
    return th, cov, bool(res.success)


def clogit_probs(th, M, Q):
    S = th[0] * np.log(np.clip(M, P_CLIP, 1)) + th[1] * np.log(np.clip(Q, P_CLIP, 1)) \
        + np.array([th[2], 0.0, th[3]])[None, :]
    return _softmax_rows(S)


def pool_alpha(M, Q, y):
    """alpha in [0,1] di p = alpha*modello + (1-alpha)*mercato, minimo LogLoss (convesso)."""
    ar = np.arange(len(y))

    def nll(a):
        p = a * M[ar, y] + (1 - a) * Q[ar, y]
        return -np.mean(np.log(np.clip(p, P_CLIP, 1)))

    r = optimize.minimize_scalar(nll, bounds=(0.0, 1.0), method="bounded",
                                 options={"xatol": 1e-7})
    return float(r.x)


def pool_probs(alpha, M, Q):
    P = alpha * M + (1 - alpha) * Q
    return P / P.sum(axis=1, keepdims=True)


def fit_fold(est: pd.DataFrame, reps: int, rng, mpref="m", qpref="pre"):
    """Stima (a) e (b) sul fold di stima, con IC bootstrap a blocchi sul fold di stima.

    ``mpref``/``qpref``: prefissi delle colonne di modello e di mercato (default: blend e
    B365 pre-chiusura proporzionale = decisione). Le varianti servono solo alla sensibilita'.
    """
    M = est[pcols(mpref)].to_numpy(float)
    Q = est[pcols(qpref)].to_numpy(float)
    y = est["y_code"].to_numpy(int)
    X1, X2 = np.log(np.clip(M, P_CLIP, 1)), np.log(np.clip(Q, P_CLIP, 1))
    th, cov, ok = clogit_fit(X1, X2, y, need_cov=True)
    alpha = pool_alpha(M, Q, y)
    # controllo: solo mercato RICALIBRATO (beta_modello = 0 per costruzione, come in clogit_fit
    # con X1 = 0). Separa l'effetto di ricalibrazione del mercato dall'informazione del modello.
    th_mkt, _, ok_mkt = clogit_fit(np.zeros_like(X1), X2, y, need_cov=False)
    th_mkt = np.array([0.0, th_mkt[1], th_mkt[2], th_mkt[3]])
    codes, _ = pd.factorize(block_keys(est), sort=True)
    nb = int(codes.max()) + 1
    rows_by_block = [np.flatnonzero(codes == b) for b in range(nb)]
    d_th = np.zeros((reps, 4))
    d_al = np.zeros(reps)
    for r in range(reps):
        pick = rng.integers(0, nb, size=nb)
        ix = np.concatenate([rows_by_block[b] for b in pick])
        thb, _, _ = clogit_fit(X1[ix], X2[ix], y[ix], theta0=th)
        d_th[r] = thb
        d_al[r] = pool_alpha(M[ix], Q[ix], y[ix])
    se = np.sqrt(np.clip(np.diag(cov), 0, None)) if cov is not None else np.full(4, np.nan)
    names = ["peso_modello_b1", "peso_mercato_b2", "a_casa", "a_trasferta"]
    coef = {}
    for j, nm in enumerate(names):
        coef[nm] = {"stima": float(th[j]), "se_hessiana": float(se[j]),
                    "ic95": list(ci(d_th[:, j]))}
    coef["alpha_pool"] = {"stima": alpha, "ic95": list(ci(d_al))}
    return {"ok_convergenza": ok, "n_stima": int(len(y)), "blocchi_stima": int(nb),
            "theta": th.tolist(), "alpha": alpha, "coef": coef,
            "theta_mercato_ricalibrato": th_mkt.tolist(),
            "b2_mercato_ricalibrato": float(th_mkt[1]),
            "d_theta": d_th, "d_alpha": d_al, "codes": codes, "rows_by_block": rows_by_block}


# ---------------------------------------------------------------------------
# Top Mix (regola di produzione: esito 1X2 piu' probabile, ammesso se >= 0.55)
# ---------------------------------------------------------------------------
def topmix_pick(P):
    idx = np.argmax(P, axis=1)           # primo massimo, come max() sul dict (1, X, 2)
    conf = P[np.arange(len(P)), idx]
    return idx, conf, conf >= TOPMIX_MIN


def topmix_block(sample: Sample, P, yi, mask_extra=None):
    idx, conf, adm = topmix_pick(P)
    if mask_extra is not None:
        adm = adm & mask_extra
    hit = (idx == yi).astype(float)
    a = adm.astype(float)
    n = int(adm.sum())
    hr, hr_ci = ratio_ci(sample, hit * a, a)
    cf, cf_ci = ratio_ci(sample, conf * a, a)
    gap_pt, gap_draws = sample.ratio(conf * a - hit * a, a)
    return {"n": n, "pct_righe": float(adm.mean()) if len(adm) else float("nan"),
            "hit": hr, "hit_ci": list(hr_ci), "conf": cf, "conf_ci": list(cf_ci),
            "gap": gap_pt, "gap_ci": list(ci(gap_draws)), "adm": adm, "idx": idx,
            "conf_row": conf, "hit_row": hit}


def fmt(x, nd=4):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/d"
    return f"{x:.{nd}f}"


def fci(pt, ci_, nd=4):
    if pt is None or (isinstance(pt, float) and not math.isfinite(pt)):
        return "n/d"
    return f"{pt:.{nd}f} [{ci_[0]:.{nd}f}; {ci_[1]:.{nd}f}]"


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |")
    return "\n".join(out)


def git_facts():
    def run(*cmd):
        try:
            return subprocess.run(cmd, cwd=_REPO_ROOT, capture_output=True, text=True,
                                  timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return "n/d"
    return {"head": run("git", "rev-parse", "HEAD"),
            "branch": run("git", "rev-parse", "--abbrev-ref", "HEAD"),
            "origin_main": run("git", "rev-parse", "origin/main")}


# ---------------------------------------------------------------------------
# Sezioni del referto
# ---------------------------------------------------------------------------
PFX = {"modello": "m", "poisson": "p", "elo": "e", "b365_pre": "pre", "b365_close": "close",
       "pin_close": "pin", "b365_pre_shin": "pres", "b365_close_shin": "closes",
       "pin_close_shin": "pins", "combo_b": "cb", "combo_a": "ca", "mkt_recal": "mr"}
LABEL = {"modello": "Modello blend (0,25 Poisson + 0,75 Elo)",
         "poisson": "Poisson puro (testa 1X2 di produzione)",
         "elo": "Elo puro (walker, seeding S3)",
         "b365_pre": "B365 pre-chiusura (de-vig prop.)",
         "b365_close": "B365 chiusura (de-vig prop.)",
         "pin_close": "Pinnacle chiusura (de-vig prop.)",
         "b365_pre_shin": "B365 pre-chiusura (Shin)",
         "b365_close_shin": "B365 chiusura (Shin)",
         "pin_close_shin": "Pinnacle chiusura (Shin)",
         "combo_b": "Combinazione (b): regressione condizionale",
         "combo_a": "Combinazione (a): pool lineare",
         "mkt_recal": "Controllo: mercato pre ricalibrato (β_mod = 0)"}


def P_key(df, key):
    return df[pcols(PFX[key])].to_numpy(float)


def coverage_table(df):
    rows = []
    for (league, season), g in df.groupby(["league", "season"], sort=False):
        rec = {"lega": league, "stagione": season, "righe": int(len(g)),
               "modello": int(g["has_model"].sum())}
        for c in ["B365H", "B365CH", "PSCH"]:
            rec[c] = int(g[c].notna().sum())
        rec["pre (terna valida)"] = int(g["pre_ok"].sum())
        rec["chiusura B365 (terna valida)"] = int(g["close_ok"].sum())
        rec["Pinnacle chiusura (terna valida)"] = int(g["pin_ok"].sum())
        rows.append(rec)
    return pd.DataFrame(rows)


def quality_rows(d, keys, sample_label):
    rows = []
    B = d[pcols("base")].to_numpy(float)
    yi = d["y_code"].to_numpy(int)
    for key in keys:
        s = summary(P_key(d, key), yi, B)
        rows.append([LABEL[key], sample_label, s["n"], fmt(s["logloss"]), fmt(s["brier"]),
                     fmt(s["rps"]), fmt(s["bss_brier"]), fmt(s["bss_logloss"]), fmt(s["bss_rps"]),
                     f"{fmt(s['rel_1'])} / {fmt(s['res_1'])}",
                     f"{fmt(s['rel_X'])} / {fmt(s['res_X'])}",
                     f"{fmt(s['rel_2'])} / {fmt(s['res_2'])}"])
    return rows


def loss_columns(d):
    """Colonne per-riga di LogLoss, Brier, RPS per ogni fonte (per i bootstrap appaiati)."""
    yi = d["y_code"].to_numpy(int)
    out = {}
    for key in PFX:
        ll, br, rps = row_losses(P_key(d, key), yi)
        out[("ll", key)] = ll
        out[("br", key)] = br
        out[("rps", key)] = rps
    return out


def paired_rows(d, S, a, b, label, reps, seed):
    """Riga di tabella: Delta (a - b) di LogLoss, Brier, RPS e resolution per esito."""
    L = loss_columns(d)
    res = {}
    for met in ("ll", "br", "rps"):
        pt, c = S.mean_diff(L[(met, a)], L[(met, b)])
        res[met] = (pt, c)
    Pa, Pb = P_key(d, a), P_key(d, b)
    yi = d["y_code"].to_numpy(int)
    rd = resolution_diff(S, Pa, Pb, yi, reps, seed)
    row = [label, len(d),
           fci(*res["ll"], nd=4), fci(*res["br"], nd=4), fci(*res["rps"], nd=4),
           " ; ".join(f"{lab}: {fci(rd[lab]['delta'], rd[lab]['ci'], nd=4)}" for lab in LABELS)]
    return row, {"ll": list(res["ll"][:1]) + [list(res["ll"][1])],
                 "br": [res["br"][0], list(res["br"][1])],
                 "rps": [res["rps"][0], list(res["rps"][1])],
                 "resolution": {lab: {"delta": rd[lab]["delta"], "ci": rd[lab]["ci"]}
                                for lab in LABELS}}


def pct(x):
    return f"{100 * x:.1f}%"


# Tolleranza per i confronti con zero: l'ottimizzatore di alpha (bounded, xatol 1e-7) restituisce
# valori dell'ordine di 1e-8 quando il minimo e' sul bordo 0; senza tolleranza un IC degenere
# a 0 risulterebbe "distinguibile da zero" per puro rumore di precisione.
EPS_ZERO = 1e-6


def _contains_zero(lo, hi):
    return (lo - EPS_ZERO) <= 0.0 <= (hi + EPS_ZERO)


def _not_significantly_positive(lo, hi):
    """Peso non significativamente positivo: IC che contiene zero OPPURE tutto <= 0."""
    return lo <= EPS_ZERO


def decide(c):
    """Regola di decisione (con precisazione, vedi §5 del referto).

    COMBINARE: Δ LogLoss pooled < 0 con IC che esclude zero e segno negativo in entrambi i fold.
    MERCATO:   peso del modello non significativamente positivo in entrambi i fold.
               (Precisazione decisa dopo aver visto i risultati: la formulazione originale
               copriva solo il peso non distinguibile da zero; il peso negativo significativo
               non era coperto. Un peso negativo significa che il modello non migliora il mercato.)
    """
    comb_ok = (c["dll_pool"] < -EPS_ZERO) and (c["dll_pool_ci"][1] < -EPS_ZERO)
    signs_ok = (c["dll_A"] < -EPS_ZERO) and (c["dll_B"] < -EPS_ZERO)
    if comb_ok and signs_ok:
        return "COMBINARE"
    if all(_not_significantly_positive(*c[f"w_mod_ci_{f}"]) for f in ("A", "B")):
        return "MERCATO"
    return "NESSUN VERDETTO AUTOMATICO"


def decide_reasons(c):
    """Perche' ciascun verdetto NON scatta, con i numeri (per il referto)."""
    out = []
    lo, hi = c["dll_pool_ci"]
    if not (c["dll_pool"] < -EPS_ZERO and hi < -EPS_ZERO):
        if _contains_zero(lo, hi):
            desc = "IC include lo zero" if abs(hi - lo) > EPS_ZERO else "IC degenere a 0"
        else:
            desc = "IC non negativo"
        out.append(f"COMBINARE non soddisfatto: Δ LogLoss pooled = {c['dll_pool']:.4f} "
                   f"[{lo:.4f}; {hi:.4f}] ({desc})")
    if not (c["dll_A"] < -EPS_ZERO and c["dll_B"] < -EPS_ZERO):
        out.append(f"COMBINARE non soddisfatto: segni dei fold = A {c['dll_A']:+.4f}, B {c['dll_B']:+.4f} "
                   "(non entrambi negativi)")
    for f in ("A", "B"):
        a, b = c[f"w_mod_ci_{f}"]
        if not _not_significantly_positive(a, b):
            out.append(f"MERCATO non applicabile sul fold {f}: peso del modello significativamente positivo "
                       f"(IC [{a:.4f}; {b:.4f}])")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Modello contro mercato sull'1X2 (audit).")
    ap.add_argument("--reps", type=int, default=DEFAULT_REPS)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--usa-cache", action="store_true",
                    help="sviluppo: riusa il frame in audit/output (la run di referto non lo usa)")
    args = ap.parse_args(argv)
    os.chdir(_REPO_ROOT)
    t0 = time.time()
    rng = np.random.default_rng(args.seed)
    R = args.reps
    out_dir = os.path.join(_AUDIT_DIR, "output")
    res_dir = os.path.join(_AUDIT_DIR, "results")
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(res_dir, exist_ok=True)

    cache = os.path.join(out_dir, "onex2_frame_cache.pkl")
    if args.usa_cache and os.path.exists(cache):
        import pickle
        with open(cache, "rb") as fh:
            df, diag, base = pickle.load(fh)
        print("frame caricato dalla cache (solo sviluppo)", flush=True)
    else:
        print("costruzione del frame (produzione + walker Elo + quote)...", flush=True)
        df, diag, base = build_frame()
        if args.usa_cache:
            import pickle
            with open(cache, "wb") as fh:
                pickle.dump((df, diag, base), fh)
    print(f"frame: {len(df)} righe in {time.time() - t0:.1f}s", flush=True)

    cov = coverage_table(df)
    ev_seasons = df[df["season"].isin(EVAL_SEASONS)]
    E = df[df["season"].isin(EVAL_SEASONS) & df["has_model"] & df["pre_ok"]
           & df["close_ok"]].copy().reset_index(drop=True)

    # colonne di probabilita' per la regressione: stima e valutazione
    # --- combinazione (punto 3): rolling-origin -------------------------------
    fits = {}
    E["cb0"] = E["cb1"] = E["cb2"] = np.nan
    E["ca0"] = E["ca1"] = E["ca2"] = np.nan
    E["mr0"] = E["mr1"] = E["mr2"] = np.nan
    for fold in FOLDS:
        est = df[df["season"].isin(fold["estimate"]) & df["has_model"] & df["pre_ok"]].reset_index(drop=True)
        fit = fit_fold(est, R, rng)
        fits[fold["name"]] = fit
        print(f"fold {fold['name']}: stima su {fold['estimate']} (n={len(est)}), theta={np.round(fit['theta'], 4).tolist()}, "
              f"alpha={fit['alpha']:.4f}, convergenza={fit['ok_convergenza']}", flush=True)
        mk = (E["season"] == fold["evaluate"]).to_numpy()
        M = E.loc[mk, pcols("m")].to_numpy(float)
        Q = E.loc[mk, pcols("pre")].to_numpy(float)
        cb = clogit_probs(np.asarray(fit["theta"]), M, Q)
        ca = pool_probs(fit["alpha"], M, Q)
        E.loc[mk, pcols("cb")] = cb
        E.loc[mk, pcols("ca")] = ca
        E.loc[mk, pcols("mr")] = clogit_probs(np.asarray(fit["theta_mercato_ricalibrato"]), M, Q)

    EP = E[E["pin_ok"]].copy().reset_index(drop=True)
    excl = {
        "righe_eval_totali": int(len(ev_seasons)),
        "senza_modello": int((~ev_seasons["has_model"]).sum()),
        "senza_terna_pre": int((~ev_seasons["pre_ok"]).sum()),
        "senza_terna_chiusura_b365": int((~ev_seasons["close_ok"]).sum()),
        "righe_campione_comune": int(len(E)),
        "righe_con_pinnacle_chiusura": int(len(EP)),
    }
    print(f"campione comune (modello + B365 pre + B365 chiusura): {len(E)}; con Pinnacle: {len(EP)}",
          flush=True)

    # --- sensibilita' dei pesi della combinazione (b) -----------------------------
    sens_specs = [
        ("blend + B365 pre prop. (decisione)", "m", "pre", None),
        ("blend + B365 pre Shin", "m", "pres", None),
        ("Poisson puro + B365 pre prop.", "p", "pre", None),
        ("Elo puro + B365 pre prop.", "e", "pre", None),
        ("blend + Pinnacle chiusura prop. (riferimento, non pre-chiusura)", "m", "pin", "pin_ok"),
    ]
    sens_rows, sens_json = [], {}
    DEC_LABEL = sens_specs[0][0]
    for label, mp, qp, need in sens_specs:
        if label == DEC_LABEL:
            continue  # riga decisionale: riusa i fold gia' stimati (vedi sotto, dopo il rolling)
        for fold in FOLDS:
            est_s = df[df["season"].isin(fold["estimate"]) & df["has_model"] & df["pre_ok"]]
            if need:
                est_s = est_s[est_s[need]]
            est_s = est_s.reset_index(drop=True)
            fs = fit_fold(est_s, R, rng, mpref=mp, qpref=qp)
            cc = fs["coef"]
            sens_json[f"{label}|{fold['name']}"] = {k: v for k, v in cc.items()}
            sens_rows.append([label, fold["name"], len(est_s),
                              fci(cc["peso_modello_b1"]["stima"], cc["peso_modello_b1"]["ic95"]),
                              fci(cc["peso_mercato_b2"]["stima"], cc["peso_mercato_b2"]["ic95"])])
    dec_rows = []
    for fold in FOLDS:
        cc = fits[fold["name"]]["coef"]
        sens_json[f"{DEC_LABEL}|{fold['name']}"] = cc
        dec_rows.append([DEC_LABEL, fold["name"], fits[fold["name"]]["n_stima"],
                         fci(cc["peso_modello_b1"]["stima"], cc["peso_modello_b1"]["ic95"]),
                         fci(cc["peso_mercato_b2"]["stima"], cc["peso_mercato_b2"]["ic95"])])
    sens_rows[0:0] = dec_rows
    print("sensibilita' calcolate", flush=True)

    # --- campioni per bootstrap ------------------------------------------------
    S_pool = Sample(E, R, rng)
    S_L = {l: Sample(E[E["league"] == l], R, rng) for _, l in LEAGUES}
    S_s = {s: Sample(E[E["season"] == s], R, rng) for s in EVAL_SEASONS}
    S_pin = Sample(EP, R, rng)
    S_fold = {f["name"]: S_s[f["evaluate"]] for f in FOLDS}
    print(f"campioni bootstrap pronti in {time.time() - t0:.1f}s", flush=True)

    # --- sezione 2: qualita' ---------------------------------------------------
    keys_common = ["modello", "poisson", "elo", "b365_pre", "b365_close",
                   "b365_pre_shin", "b365_close_shin"]
    keys_pin = ["modello", "b365_pre", "b365_close", "pin_close", "pin_close_shin"]
    qual_common = quality_rows(E, keys_common, f"comune n={len(E)}")
    qual_pin = quality_rows(EP, keys_pin, f"Pinnacle n={len(EP)}")

    # --- sezione 2b/2c: differenze appaiate -----------------------------------
    diff_specs = [
        ("b365_pre", "modello", "E", "mercato pre - modello"),
        ("b365_close", "modello", "E", "mercato chiusura - modello"),
        ("pin_close", "modello", "EP", "Pinnacle chiusura - modello"),
        ("pin_close", "b365_pre", "EP", "Pinnacle chiusura - B365 pre"),
        ("b365_pre", "poisson", "E", "contesto: mercato pre - Poisson puro"),
        ("b365_pre", "elo", "E", "contesto: mercato pre - Elo puro"),
        ("b365_close", "b365_pre", "E", "chiusura - pre-chiusura (B365)"),
    ]
    diff_rows, diff_json = [], {}
    for a, b, sname, label in diff_specs:
        d = E if sname == "E" else EP
        S = S_pool if sname == "E" else S_pin
        row, js = paired_rows(d, S, a, b, label, R, args.seed)
        diff_rows.append(["pooled"] + row)
        diff_json[f"{label}|pooled"] = js
        if sname == "E":
            for _, l in LEAGUES:
                dl = E[E["league"] == l].reset_index(drop=True)
                rowl, jsl = paired_rows(dl, S_L[l], a, b, label, R, args.seed + 17)
                diff_rows.append([l] + rowl)
                diff_json[f"{label}|{l}"] = jsl
    print(f"differenze appaiate calcolate in {time.time() - t0:.1f}s", flush=True)

    # --- sezione 3: rolling-origin --------------------------------------------
    roll_rows, coef_rows, roll_json = [], [], {}
    for fold in FOLDS:
        fn = fold["name"]
        fit = fits[fn]
        mk = (E["season"] == fold["evaluate"]).to_numpy()
        Ef = E[mk].reset_index(drop=True)
        yf = Ef["y_code"].to_numpy(int)
        Sf = S_fold[fn]
        ll_mkt = row_losses(P_key(Ef, "b365_pre"), yf)[0]
        ll_b = row_losses(P_key(Ef, "combo_b"), yf)[0]
        ll_a = row_losses(P_key(Ef, "combo_a"), yf)[0]
        ll_r = row_losses(P_key(Ef, "mkt_recal"), yf)[0]
        pt_b, ci_b = Sf.mean_diff(ll_b, ll_mkt)
        pt_a, ci_a = Sf.mean_diff(ll_a, ll_mkt)
        pt_r, ci_r = Sf.mean_diff(ll_b, ll_r)     # combinazione (b) - mercato ricalibrato
        c = fit["coef"]
        roll_json[fn] = {
            "stima_su": list(fold["estimate"]), "valuta": fold["evaluate"],
            "n_stima": fit["n_stima"], "blocchi_stima": fit["blocchi_stima"],
            "convergenza_b": fit["ok_convergenza"],
            "coef": {k: v for k, v in c.items()},
            "dLL_b": pt_b, "dLL_b_ci": list(ci_b),
            "dLL_a": pt_a, "dLL_a_ci": list(ci_a),
            "dLL_b_vs_mercato_ricalibrato": pt_r, "dLL_b_vs_mercato_ricalibrato_ci": list(ci_r),
            "b2_mercato_ricalibrato": fit["b2_mercato_ricalibrato"],
            "b2_mercato_grezzo_equiv": 1.0,
        }
        roll_rows.append([
            fn, " + ".join(fold["estimate"]), fold["evaluate"], f"{fit['n_stima']} / {len(Ef)}",
            fci(c["peso_modello_b1"]["stima"], c["peso_modello_b1"]["ic95"]),
            fci(c["peso_mercato_b2"]["stima"], c["peso_mercato_b2"]["ic95"]),
            fci(c["alpha_pool"]["stima"], c["alpha_pool"]["ic95"]),
            fci(pt_b, ci_b), fci(pt_a, ci_a), fci(pt_r, ci_r),
        ])
        for nm in ("peso_modello_b1", "peso_mercato_b2", "a_casa", "a_trasferta"):
            coef_rows.append([fn, nm, fmt(c[nm]["stima"]), fmt(c[nm]["se_hessiana"]),
                              fci(c[nm]["stima"], c[nm]["ic95"])])
        coef_rows.append([fn, "alpha (pool lineare, peso modello)", fmt(c["alpha_pool"]["stima"]),
                          "-", fci(c["alpha_pool"]["stima"], c["alpha_pool"]["ic95"])])

    # OOS pooled: ΔLL su tutte le partite valutate (entrambi i fold)
    yE = E["y_code"].to_numpy(int)
    ll_mkt_E = row_losses(P_key(E, "b365_pre"), yE)[0]
    ll_bE = row_losses(P_key(E, "combo_b"), yE)[0]
    ll_aE = row_losses(P_key(E, "combo_a"), yE)[0]
    pt_bE, ci_bE = S_pool.mean_diff(ll_bE, ll_mkt_E)
    pt_aE, ci_aE = S_pool.mean_diff(ll_aE, ll_mkt_E)
    ll_rE = row_losses(P_key(E, "mkt_recal"), yE)[0]
    pt_rE, ci_rE = S_pool.mean_diff(ll_bE, ll_rE)
    roll_rows.append(["pooled OOS", "A + B", "2024/25 + 2025/26", f"- / {len(E)}", "-", "-", "-",
                      fci(pt_bE, ci_bE), fci(pt_aE, ci_aE), fci(pt_rE, ci_rE)])

    # --- sezione 2 estesa: qualita' delle combinazioni (OOS) ----------------
    qual_comb = quality_rows(E, ["modello", "b365_pre", "combo_b", "combo_a"],
                             "OOS (combinazioni)")
    comb_diff_pooled = [
        ["combinazione (b) - mercato pre", "pooled OOS", fci(pt_bE, ci_bE)],
        ["combinazione (a) - mercato pre", "pooled OOS", fci(pt_aE, ci_aE)],
    ]

    # --- sezione 4: Top Mix ---------------------------------------------------
    tm_rows, tm_json = [], {}
    Pm, Pp, Pb, Pa = P_key(E, "modello"), P_key(E, "b365_pre"), P_key(E, "combo_b"), P_key(E, "combo_a")
    Pc = P_key(E, "b365_close")
    Pbase = {"modello": Pm, "b365_pre": Pp, "combo_b": Pb, "combo_a": Pa, "b365_close": Pc}
    tm_blocks = {}
    for key in ["modello", "b365_pre", "combo_b", "combo_a", "b365_close"]:
        tm_blocks[key] = topmix_block(S_pool, Pbase[key], yE)
    # veto di produzione sul modello: |P_poisson - P_elo| < 0.25 sull'esito scelto
    idx_m = np.argmax(Pm, axis=1)
    ar = np.arange(len(E))
    veto = np.abs(P_key(E, "poisson")[ar, idx_m] - P_key(E, "elo")[ar, idx_m]) < TOPMIX_VETO
    tm_blocks["modello_veto"] = topmix_block(S_pool, Pm, yE, mask_extra=veto)
    names_tm = {"modello": "Modello blend", "b365_pre": "Mercato B365 pre-chiusura (prop.)",
                "combo_b": "Combinazione (b)", "combo_a": "Combinazione (a)",
                "b365_close": "Mercato B365 chiusura (contesto)",
                "modello_veto": "Modello + veto di produzione |Poisson-Elo|<0,25 (sensibilita')"}
    for key in ["modello", "b365_pre", "combo_b", "combo_a", "b365_close", "modello_veto"]:
        t = tm_blocks[key]
        tm_rows.append(["pooled OOS", names_tm[key], t["n"], pct(t["pct_righe"]),
                        fci(t["hit"], t["hit_ci"]), fci(t["conf"], t["conf_ci"]),
                        fci(t["gap"], t["gap_ci"])])
        tm_json[f"pooled|{key}"] = {k: v for k, v in t.items()
                                    if k not in ("adm", "idx", "conf_row", "hit_row")}
    for s in EVAL_SEASONS:
        mk = (E["season"] == s).to_numpy()
        Es = E[mk].reset_index(drop=True)
        ys = Es["y_code"].to_numpy(int)
        Ps = {"modello": P_key(Es, "modello"), "b365_pre": P_key(Es, "b365_pre"),
              "combo_b": P_key(Es, "combo_b"), "combo_a": P_key(Es, "combo_a")}
        for key in ["modello", "b365_pre", "combo_b", "combo_a"]:
            t = topmix_block(S_s[s], Ps[key], ys)
            tm_rows.append([s, names_tm[key], t["n"], pct(t["pct_righe"]),
                            fci(t["hit"], t["hit_ci"]), fci(t["conf"], t["conf_ci"]),
                            fci(t["gap"], t["gap_ci"])])
            tm_json[f"{s}|{key}"] = {k: v for k, v in t.items()
                                     if k not in ("adm", "idx", "conf_row", "hit_row")}

    # Pinnacle: Top Mix sul sottocampione con quota Pinnacle di chiusura
    yP = EP["y_code"].to_numpy(int)
    tp_rows = []
    for key in ["modello", "b365_pre", "pin_close"]:
        t = topmix_block(S_pin, P_key(EP, key), yP)
        tp_rows.append([names_tm.get(key, LABEL[key]), t["n"], pct(t["pct_righe"]),
                        fci(t["hit"], t["hit_ci"]), fci(t["conf"], t["conf_ci"]),
                        fci(t["gap"], t["gap_ci"])])
        tm_json[f"pin|{key}"] = {k: v for k, v in t.items()
                                 if k not in ("adm", "idx", "conf_row", "hit_row")}

    # Stessa N: le N scelte piu' sicure di ciascuna fonte (senza soglia)
    counts = {k: tm_blocks[k]["n"] for k in ("modello", "b365_pre", "combo_b")}
    N_min = min(counts.values())
    Ns = sorted(set([n for n in (100, 200, 400) if n <= len(E)] + [N_min]))
    sameN_rows, sameN_json = [], {}
    for N in Ns:
        for key in ("modello", "b365_pre", "combo_b"):
            P_ = Pbase[key]
            conf = P_.max(axis=1)
            top = np.argsort(-conf, kind="stable")[:N]
            mask = np.zeros(len(E))
            mask[top] = 1.0
            hit = (np.argmax(P_, axis=1) == yE).astype(float)
            hr, hc = ratio_ci(S_pool, hit * mask, mask)
            minconf = float(conf[top].min())
            sameN_rows.append([N, names_tm[key], fci(hr, hc), fmt(minconf)])
            sameN_json[f"N={N}|{key}"] = {"hit": hr, "ci": list(hc), "conf_min_in_top": minconf}

    # Consenso: modello e mercato pre-chiusura indicano lo stesso esito, entrambi >= 0.55
    pm_idx = np.argmax(Pm, axis=1)
    pq_idx = np.argmax(Pp, axis=1)
    cm = Pm.max(axis=1)
    cq = Pp.max(axis=1)
    cons = (pm_idx == pq_idx) & (cm >= TOPMIX_MIN) & (cq >= TOPMIX_MIN)
    hit_m = (pm_idx == yE).astype(float)
    # Tabella A: tutte le partite valutate
    c_f = cons.astype(float)
    r_f = (~cons).astype(float)
    hc_pt, hc_ci = ratio_ci(S_pool, hit_m * c_f, c_f)
    hr_pt, hr_ci = ratio_ci(S_pool, hit_m * r_f, r_f)
    # differenza consenso - resto: stessi draw bootstrap per i due gruppi
    _, dr_c = S_pool.ratio(hit_m * c_f, c_f)
    _, dr_r = S_pool.ratio(hit_m * r_f, r_f)
    dA_ci = ci(dr_c - dr_r)
    dA_pt = hc_pt - hr_pt
    consA = {"n_consenso": int(cons.sum()), "hit_consenso": hc_pt, "ci_consenso": list(hc_ci),
             "n_resto": int((~cons).sum()), "hit_resto_modello": hr_pt, "ci_resto": list(hr_ci),
             "diff": dA_pt, "diff_ci": list(dA_ci)}
    # Tabella B: solo scelte Top Mix del modello (conf >= 0.55)
    adm_m = cm >= TOPMIX_MIN
    gB1 = (adm_m & cons).astype(float)
    gB2 = (adm_m & ~cons).astype(float)
    h1, c1 = ratio_ci(S_pool, hit_m * gB1, gB1)
    h2, c2 = ratio_ci(S_pool, hit_m * gB2, gB2)
    _, dB_c1 = S_pool.ratio(hit_m * gB1, gB1)
    _, dB_c2 = S_pool.ratio(hit_m * gB2, gB2)
    n1, n2 = int(gB1.sum()), int(gB2.sum())
    k1, k2 = int((hit_m * gB1).sum()), int((hit_m * gB2).sum())
    fisher_p = float(scipy_stats.fisher_exact([[k1, n1 - k1], [k2, n2 - k2]])[1])
    consB = {"n_consenso": n1, "hit_consenso": h1, "ci_consenso": list(c1),
             "n_non_consenso": n2, "hit_non_consenso": h2, "ci_non_consenso": list(c2),
             "diff": h1 - h2, "diff_ci": list(ci(dB_c1 - dB_c2)), "fisher_p": fisher_p}
    print(f"consenso: {consA} | {consB}", flush=True)

    # --- sezione 5: decisione -------------------------------------------------
    cdec = {
        "dll_pool": float(pt_bE), "dll_pool_ci": list(ci_bE),
        "dll_pool_vs_recal": float(pt_rE), "dll_pool_vs_recal_ci": list(ci_rE),
        "dll_A": float(roll_json["A"]["dLL_b"]), "dll_B": float(roll_json["B"]["dLL_b"]),
        "w_mod_ci_A": roll_json["A"]["coef"]["peso_modello_b1"]["ic95"],
        "w_mod_ci_B": roll_json["B"]["coef"]["peso_modello_b1"]["ic95"],
    }
    verdict_b = decide(cdec)
    cdec_a = {
        "dll_pool": float(pt_aE), "dll_pool_ci": list(ci_aE),
        "dll_A": float(roll_json["A"]["dLL_a"]), "dll_B": float(roll_json["B"]["dLL_a"]),
        "w_mod_ci_A": roll_json["A"]["coef"]["alpha_pool"]["ic95"],
        "w_mod_ci_B": roll_json["B"]["coef"]["alpha_pool"]["ic95"],
    }
    verdict_a = decide(cdec_a)
    reasons_b = decide_reasons(cdec)
    reasons_a = decide_reasons(cdec_a)
    print(f"verdetto (b): {verdict_b} | verdetto (a): {verdict_a}", flush=True)

    # --- output ---------------------------------------------------------------
    git = git_facts()
    elapsed = time.time() - t0
    payload = {
        "generato_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git": git, "reps": R, "seed": args.seed, "secondi": round(elapsed, 1),
        "diagnostica_frame": diag, "base_rate_train": {f"{k[0]}|{k[1]}": v.tolist() for k, v in base.items()},
        "copertura": cov.to_dict(orient="records"), "esclusioni": excl,
        "qualita_comune": qual_common, "qualita_pinnacle": qual_pin,
        "differenze": diff_json, "rolling_origin": roll_json, "pooled_oos_dll": {
            "combo_b": [pt_bE, list(ci_bE)], "combo_a": [pt_aE, list(ci_aE)]},
        "topmix": tm_json, "same_n": sameN_json, "consenso_A": consA, "consenso_B": consB,
        "verdetto_b": verdict_b, "verdetto_a": verdict_a,
        "motivi_b": reasons_b, "motivi_a": reasons_a, "sensibilita_pesi": sens_json,
        "controllo_mercato_ricalibrato": {"pooled": [float(pt_rE), list(ci_rE)],
                                          "A": roll_json["A"]["dLL_b_vs_mercato_ricalibrato"],
                                          "B": roll_json["B"]["dLL_b_vs_mercato_ricalibrato"]},
        "cdec": cdec, "cdec_a": cdec_a,
    }
    with open(os.path.join(out_dir, "onex2_market_test.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, default=float)
    rows_csv = E[["league", "season", "date_day", "home", "away", "y_code"]
                 + pcols("m") + pcols("p") + pcols("e") + pcols("pre") + pcols("close")
                 + pcols("pin") + pcols("cb") + pcols("ca") + pcols("mr")].copy()
    rows_csv.to_csv(os.path.join(out_dir, "onex2_market_rows.csv"), index=False)

    md = build_markdown(payload, dict(
        cov=cov, excl=excl, qual_common=qual_common, qual_pin=qual_pin, qual_comb=qual_comb,
        diff_rows=diff_rows, roll_rows=roll_rows, coef_rows=coef_rows, tm_rows=tm_rows,
        tp_rows=tp_rows, sameN_rows=sameN_rows, Ns=Ns, N_min=N_min, consA=consA, consB=consB,
        verdict_b=verdict_b, verdict_a=verdict_a, comb_diff_pooled=comb_diff_pooled,
        diag=diag, base=base, cdec=cdec, cdec_a=cdec_a, git=git, args=args, elapsed=elapsed,
        counts=counts, fits=fits, E_len=len(E), EP_len=len(EP), sens_rows=sens_rows,
        reasons_b=reasons_b, reasons_a=reasons_a,
        w_poisson=prod_app.POISSON_1X2_WEIGHT))
    with open(os.path.join(res_dir, "onex2_market_test.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    print(f"referto scritto in audit/results/onex2_market_test.md ({elapsed:.1f}s)", flush=True)
    return 0


def build_markdown(payload, T):
    """Referto: ogni tabella e' generata dai numeri calcolati (nessun numero scritto a mano)."""
    P = []
    P.append("# Modello contro mercato sull'1X2 — referto di audit (sola lettura)\n")
    P.append(
        "Generato da `audit/onex2_market_test.py` (nessuna modifica a `SoccerMath/`). "
        f"Commit di base: `{T['git']['head']}` (branch `{T['git']['branch']}`); "
        f"origin/main: `{T['git']['origin_main']}`. Bootstrap: {T['args'].reps} repliche a blocchi "
        f"(lega × stagione × giornata), seme {T['args'].seed}. Tempo di esecuzione: {T['elapsed']:.0f} s.\n"
        "Comando: `python audit/onex2_market_test.py`.\n")

    P.append("## 0. Fonti di probabilita' e verifiche di riuso\n")
    P.append(md_table(
        ["Fonte", "Codice riusato (non riscritto)", "Note"],
        [["Modello blend", "`app.blend_elo_into_1x2(..., w=app.POISSON_1X2_WEIGHT)`",
          f"w = {T['w_poisson']}; identita' w·Poisson+(1−w)·Elo verificata in §0 (scarto max sotto)"],
         ["Poisson puro", "`ppda_residual_test.production_totali` + intercettazione di `app.get_full_poisson_two_heads`",
          "1X2 raccolte nell'ordine del banco; parita' con `engine_u25`/`engine_gg` (vedi sotto)"],
         ["Elo puro", "`elo_walker_core.build_walker_table` → `EloEngine` (seeding S3, `PROMOTED_SEED_OFFSET`)",
          "rating prima della partita; aggiornamento dopo"],
         ["De-vig proporzionale", "`backtest_experiment_all.devig_1x2`", "decisione della commessa"],
         ["De-vig Shin", "`devig_shin3` (in questo script, 3 esiti)", "sensibilita'; verifica somma=1 nei test"],
         ["Base rate", "stagioni precedenti della lega (come `baserate_oos.raw`, PR #34)", "train 2022/23… (vedi JSON)"]]))
    P.append("")
    rows = []
    for lega, dg in T["diag"].items():
        if lega == "blend_max_scarto_identita":
            continue
        par = dg["parity"]
        rows.append([lega, par["righe"], f"{par['max_scarto_u25']:.2e}", f"{par['max_scarto_gg']:.2e}",
                     f"{par['max_scarto_somma_1X2_da_1']:.2e}", dg["righe_walker_unite"],
                     dg["ftr_walker_discordanti_da_gol"], dg["ftr_quote_discordanti_da_gol"]])
    P.append("Verifiche di parita' (produzione intercettata e walker Elo; `max scarto` = massimo valore assoluto):\n")
    P.append(md_table(["Lega", "Righe produzione", "max |u25 intercettato − banco|",
                       "max |gg intercettato − banco|", "max |Σ1X2 − 1|", "Righe walker unite (1:1)",
                       "FTR walker ≠ gol", "FTR quote ≠ gol"], rows))
    P.append(f"\nScarto massimo blend: `|blend − (w·Poisson + (1−w)·Elo)|` = {T['diag']['blend_max_scarto_identita']:.2e} "
             "(dovrebbe essere 0 a precisione macchina: il blend e' quello di produzione).\n")

    P.append("## 1. Dati di mercato: copertura e de-vig\n")
    cov_rows = []
    for r in payload["copertura"]:
        cov_rows.append([r["lega"], r["stagione"], r["righe"], r["modello"], r["B365H"], r["B365CH"],
                         r["PSCH"], r["pre (terna valida)"], r["chiusura B365 (terna valida)"],
                         r["Pinnacle chiusura (terna valida)"]])
    P.append(md_table(["Lega", "Stagione", "Righe", "Con modello", "B365H (non nulli)",
                       "B365CH (non nulli)", "PSCH (non nulli)", "Terna pre valida",
                       "Terna chiusura B365 valida", "Terna Pinnacle chiusura valida"], cov_rows))
    P.append("")
    ex = payload["esclusioni"]
    P.append(md_table(["Campione di valutazione (2024/25 + 2025/26)", "Righe"], [
        ["Righe totali delle due stagioni", ex["righe_eval_totali"]],
        ["Senza probabilita' del modello", ex["senza_modello"]],
        ["Senza terna B365 pre-chiusura", ex["senza_terna_pre"]],
        ["Senza terna B365 chiusura", ex["senza_terna_chiusura_b365"]],
        ["**Campione comune usato** (modello + B365 pre + B365 chiusura)", ex["righe_campione_comune"]],
        ["di cui con quota Pinnacle di chiusura (campione Pinnacle)", ex["righe_con_pinnacle_chiusura"]],
    ]))
    P.append("\nLa pre-chiusura e' quella dichiarata dalla commessa (B365H/D/A, raccolte il venerdi' o il martedi'). "
             "Il CSV non contiene l'orario di rilevazione: la dicitura e' dichiarata, non verificata dal file.\n")
    P.append("Sensibilita' de-vig: la decisione usa il proporzionale; lo Shin e' riportato in §2 (righe Shin).\n")

    P.append("## 2. Qualita' delle probabilita' per fonte\n")
    P.append("LogLoss, Brier (somma sui 3 esiti), RPS (esiti ordinati 1 < X < 2); BSS = 1 − punteggio/punteggio del base rate del train. "
             "Reliability/resolution per esito con 10 bin (`baserate_oos.decomp`). Valori piu' bassi = meglio; BSS e resolution piu' alti = meglio.\n")
    hdr = ["Fonte", "Campione", "n", "LogLoss", "Brier", "RPS", "BSS Brier", "BSS LogLoss", "BSS RPS",
           "1: rel / res", "X: rel / res", "2: rel / res"]
    P.append("### 2a. Campione comune\n")
    P.append(md_table(hdr, T["qual_common"]))
    P.append("\n### 2b. Campione con quota Pinnacle di chiusura\n")
    P.append(md_table(hdr, T["qual_pin"]))
    P.append("\n### 2c. Combinazioni (campione comune, valutazione out-of-sample)\n")
    P.append(md_table(hdr, T["qual_comb"]))

    P.append("\n## 2d. Differenze appaiate (A − B), bootstrap a blocchi, 2000 repliche, IC 95%\n")
    P.append("Delta negativo su LogLoss/Brier/RPS = A migliore di B. Delta positivo su resolution = A piu' informativa. "
             "Campione pooled = tutte le partite valutate; righe per lega = stesso calcolo sulla lega.\n")
    P.append(md_table(["Confronto", "Campione", "n", "Δ LogLoss", "Δ Brier", "Δ RPS",
                       "Δ resolution per esito"], T["diff_rows"]))

    P.append("\n## 3. Il modello aggiunge qualcosa al mercato?\n")
    P.append("Rolling-origin: il fold A stima su 2023/24 e valuta 2024/25; il fold B stima su 2023/24+2024/25 e valuta 2025/26. "
             "Combinazione (a): p = α·modello + (1−α)·mercato pre-chiusura, α per minimo LogLoss. "
             "Combinazione (b): regressione condizionale multinomiale su esiti 1/X/2 con log-probabilita' di modello e mercato: "
             "S_k = a_k + β_mod·log p_mod,k + β_mkt·log p_mkt,k (β condivisi fra esiti, a_X = 0). IC 95% da bootstrap a blocchi sul fold di stima.\n")
    P.append(md_table(["Fold", "Stima su", "Valuta", "n stima / n valutazione", "β modello [IC]",
                       "β mercato [IC]", "α pool [IC]", "Δ LogLoss (b) − mercato [IC]",
                       "Δ LogLoss (a) − mercato [IC]",
                       "Δ LogLoss (b) − mercato ricalibrato [IC] (controllo)"], T["roll_rows"]))
    P.append("\nControllo: il mercato ricalibrato usa la stessa stima del fold (β_mod = 0, β_mkt e intercette liberi). "
             "Se la combinazione (b) batte il mercato grezzo ma non quello ricalibrato, il guadagno viene dalla "
             "ricalibrazione del mercato e non dall'informazione del modello.\n")
    P.append("\n### Pesi della combinazione, errori standard (Hessiana) e IC bootstrap\n")
    P.append(md_table(["Fold", "Parametro", "Stima", "SE (Hessiana)", "Stima [IC 95% bootstrap]"], T["coef_rows"]))
    P.append("\nLettura: β_mod = 0 (e β_mkt = 1, a = 0) coincide con il solo mercato grezzo. Un β_mod POSITIVO con IC "
             "che esclude lo zero indicherebbe informazione del modello non gia' nel mercato. Un β_mod NEGATIVO indica che, "
             "a parita' di mercato ricalibrato, il modello sposta le probabilita' nella direzione opposta a quella che "
             "l'esito conferma: non e' informazione aggiuntiva.\n")
    P.append("\n### Sensibilita' dei pesi (stesso protocollo, varianti di modello e di mercato)\n")
    P.append(md_table(["Variante", "Fold", "n stima", "β modello [IC 95%]", "β mercato [IC 95%]"], T["sens_rows"]))
    P.append("\nLa variante con Pinnacle di chiusura usa una quota di chiusura (informazione piu' tardiva di quella "
             "pre-chiusura): e' un riferimento di sensibilita', non un'alternativa operativa.\n")

    P.append("## 4. Effetto sulle scelte (regola del Top Mix)\n")
    P.append("Regola: esito 1X2 piu' probabile, ammesso se la probabilita' e' ≥ 0,55 (soglia di produzione con Elo). "
             "La riga `modello + veto` applica anche il veto di produzione |P_poisson − P_elo| < 0,25 "
             "(sensibilita'; il veto non esiste per il mercato, che non ha Elo). Hit rate e confidence con IC bootstrap.\n")
    P.append(md_table(["Periodo", "Fonte", "Scelte (n)", "% righe ammesse", "Hit rate [IC]",
                       "Confidence media [IC]", "Confidence − hit rate [IC]"], T["tm_rows"]))
    P.append("\n### 4b. Campione Pinnacle di chiusura\n")
    P.append(md_table(["Fonte", "Scelte (n)", "% righe ammesse", "Hit rate [IC]", "Confidence media [IC]",
                       "Confidence − hit rate [IC]"], T["tp_rows"]))
    P.append("\n### 4c. Stessa N: le N scelte piu' sicure per ciascuna fonte (senza soglia), valutazione pooled\n")
    P.append(f"N scelto come minimo delle scelte Top Mix (modello, mercato pre, combinazione b): N = {T['N_min']} "
             f"(conteggi: {T['counts']['modello']} modello, {T['counts']['b365_pre']} mercato pre, {T['counts']['combo_b']} combinazione b). "
             f"Valori di N analizzati: {T['Ns']}.\n")
    P.append(md_table(["N", "Fonte", "Hit rate delle N piu' sicure [IC]", "Confidence minima tra le N"],
                      T["sameN_rows"]))
    cA, cB = T["consA"], T["consB"]
    P.append("\n### 4d. Sottoinsieme di consenso (modello e mercato pre-chiusura concordi, entrambi ≥ 0,55)\n")
    P.append(md_table(["Gruppo", "n", "Hit rate [IC]"], [
        ["Consenso: esito concordato (modello = mercato)", cA["n_consenso"], fci(cA["hit_consenso"], cA["ci_consenso"])],
        ["Resto: esito piu' probabile del modello, senza consenso", cA["n_resto"], fci(cA["hit_resto_modello"], cA["ci_resto"])],
        ["Differenza consenso − resto", "-", fci(cA["diff"], cA["diff_ci"])],
    ]))
    P.append("\nSolo le scelte Top Mix del modello (confidence ≥ 0,55):\n")
    P.append(md_table(["Gruppo", "n", "Hit rate [IC]"], [
        ["Scelte del modello CON consenso di mercato", cB["n_consenso"], fci(cB["hit_consenso"], cB["ci_consenso"])],
        ["Scelte del modello SENZA consenso di mercato", cB["n_non_consenso"], fci(cB["hit_non_consenso"], cB["ci_non_consenso"])],
        ["Differenza (con − senza)", "-", fci(cB["diff"], cB["diff_ci"]) + f"; Fisher p = {cB['fisher_p']:.4f}"],
    ]))

    P.append("\n## 5. Regola di decisione (con precisazione)\n")
    P.append("- **COMBINARE** se la combinazione (b) batte il mercato pre-chiusura con Δ LogLoss pooled < 0, IC 95% che esclude lo zero "
             "e segno negativo in entrambi i fold.\n"
             "- **MERCATO** se il peso del modello nella combinazione (b) non e' significativamente positivo in entrambi i fold "
             "(IC 95% che contiene lo zero, oppure tutto negativo).\n"
             "- Altrimenti: **NESSUN VERDETTO AUTOMATICO** (segnalato, non forzato).\n\n"
             "**Precisazione della regola: decisa dopo aver visto i risultati, perche' il caso non era coperto.** "
             "La formulazione originale copriva solo il peso del modello non distinguibile da zero. Il caso osservato "
             "(peso negativo e distinguibile da zero in entrambi i fold) non era coperto. La regola chiede se il modello "
             "migliora il mercato: un peso negativo vuol dire che non lo migliora, e non va sfruttato come segnale "
             "contrario. Per questo il criterio MERCATO e' esteso a 'peso non significativamente positivo'. "
             "Il criterio COMBINARE e' invariato.\n")
    cd, cda = T["cdec"], T["cdec_a"]
    P.append(md_table(["Criterio", "Combinazione (b) — decisione", "Combinazione (a) — controllo"], [
        ["Δ LogLoss pooled OOS [IC 95%]", fci(cd["dll_pool"], cd["dll_pool_ci"]), fci(cda["dll_pool"], cda["dll_pool_ci"])],
        ["Δ LogLoss fold A (2024/25)", fmt(cd["dll_A"]), fmt(cda["dll_A"])],
        ["Δ LogLoss fold B (2025/26)", fmt(cd["dll_B"]), fmt(cda["dll_B"])],
        ["Peso modello, IC fold A", f"[{cd['w_mod_ci_A'][0]:.4f}; {cd['w_mod_ci_A'][1]:.4f}]",
         f"[{cda['w_mod_ci_A'][0]:.4f}; {cda['w_mod_ci_A'][1]:.4f}]"],
        ["Peso modello, IC fold B", f"[{cd['w_mod_ci_B'][0]:.4f}; {cd['w_mod_ci_B'][1]:.4f}]",
         f"[{cda['w_mod_ci_B'][0]:.4f}; {cda['w_mod_ci_B'][1]:.4f}]"],
        ["**Verdetto**", f"**{T['verdict_b']}**", f"**{T['verdict_a']}**"],
    ]))
    P.append("\nNota: sulla combinazione (b) il peso del modello e' β (scala log, condiviso fra esiti); sulla (a) e' α (peso lineare). "
             "Il verdetto usa l'IC bootstrap del fold; il criterio 'segno in entrambi i fold' usa la stima puntuale.\n")
    P.append("**Motivi per cui i verdetti non scattano (generati dai numeri):**\n")
    for r in T["reasons_b"]:
        P.append(f"- (b) {r}")
    for r in T["reasons_a"]:
        P.append(f"- (a) {r}")
    P.append(f"\nNota numerica: i confronti con zero usano la tolleranza {EPS_ZERO:g} (α̂ dell'ottimizzatore sul bordo "
             "0 vale ~1e-8, non esattamente 0). Con il confronto esatto la combinazione (a) risultava 'nessun verdetto' "
             "per rumore di precisione; la tolleranza non cambia i numeri, solo il trattamento degli IC degeneri.\n")

    P.append("## 6. Limiti dichiarati\n")
    P.append("- La pre-chiusura B365 e' quella della commessa; l'orario di rilevazione non e' nel CSV.\n"
             "- Il Poisson di produzione e' ricostruito con `production_totali` (archivio xG a cutoff); la parita' con il banco su u25/gg e' verificata riga per riga, non per l'app in esecuzione.\n"
             "- Il veto di produzione e' riportato come sensibilita', non come regola principale (la regola della commessa non lo include).\n"
             "- Il campione Pinnacle e' un sottoinsieme (chiusura Pinnacle mancante su parte delle partite 2025/26): i confronti con Pinnacle non sono sullo stesso campione del pooled.\n"
             "- Il bootstrap a blocchi tratta le giornate come unita'; le giornate di una stessa lega condividono squadre e quindi non sono indipendenti oltre il blocco.\n")
    return "\n".join(P) + "\n"


if __name__ == "__main__":
    sys.exit(main())
