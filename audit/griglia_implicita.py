#!/usr/bin/env python3
"""griglia_implicita.py — fattibilita' della griglia implicita nelle quote (audit, SOLA LETTURA).

Domanda: la griglia di punteggi implicita nelle quote (Dixon-Coles con rho stimato per
partita, su 1X2 + Over/Under 2,5 de-vig proporzionale) predice meglio dei mercati
derivati la griglia del motore Poisson di produzione, sulle stesse partite?

Nessuna modifica a SoccerMath/ (app.py incluso). Nessun replay --write. Nessuna chiave.

FONTI
  * Modello di produzione: ``ppda_residual_test.production_totali`` (walk-forward in
    ordine cronologico, come in produzione) con intercettazione delle uscite di
    ``app.get_full_poisson_two_heads``:
        1X2  -> testa 1X2 (lambda normalizzati alla somma base);
        O/U 1,5/2,5/3,5 e Gol/No Gol -> testa Totali (lambda puri);
        combinazioni (1+Over 1,5, ecc.) -> griglia congiunta Poisson costruita dai
        lambda puri della testa Totali (la produzione non produce griglie congiunte).
    Parita' verificata riga per riga con le colonne engine_u25 / engine_gg.
  * Griglia implicita (principale): fit per partita su 1X2 + Over 2,5 B365 anticipate
    (de-vig proporzionale). Griglia Poisson pura implicita (rho = 0) come confronto.
  * Sensibilita': stesso fit su Pinnacle di chiusura (PSCH/D/A + PC>2,5/PC<2,5),
    solo sul sottoinsieme in cui le quote esistono.

Campione: stagioni 2024/25 e 2025/26 delle 5 leghe (CSV football-data in
SoccerMath/database, come la PR #49). Blocchi del bootstrap: lega x stagione x data
(la giornata non e' nel CSV: la data e' il proxy, come in onex2_market_test).

Output:
  * audit/results/griglia_implicita.md   referto (generato);
  * audit/output/griglia_implicita.json  payload (non versionato);
  * audit/output/griglia_matches.csv.gz  partita per partita (non versionato);
  * audit/output/griglia_production_cache.pkl  cache della cattura di produzione.

Uso: ``python audit/griglia_implicita.py [--no-cache] [--reps 2000] [--seed 20261010]``
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import subprocess
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))
DB_DIR = os.path.join(_REPO_ROOT, "SoccerMath", "database")
OUT_DIR = os.path.join(_AUDIT_DIR, "output")
REPORT_PATH = os.path.join(_AUDIT_DIR, "results", "griglia_implicita.md")
PB_JSON = os.path.join(OUT_DIR, "griglia_penaltyblog_check.json")
CACHE_PATH = os.path.join(OUT_DIR, "griglia_production_cache.pkl")

from griglia_core import (  # noqa: E402
    BANDS, HIGH_BANDS, MARKET_NAMES, N, brier_per_match, block_bootstrap_mean_diff,
    calibration_rows, decide_replace, devig_prop, dc_matrix, fit_implicit, grid_markets,
    outcome_matrix, overround,
)


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
    import app as prod_app  # noqa: E402  (solo lettura)
    from backtest_experiment_all import LEAGUES  # noqa: E402
    from config import clean_name  # noqa: E402
    from ppda_residual_test import production_totali  # noqa: E402

import streamlit.logger as _st_logger  # noqa: E402

_st_logger.set_log_level("CRITICAL")

EVAL_SEASONS = ("2024/25", "2025/26")
SEASON_FILE = OrderedDict([("2024/25", "2024"), ("2025/26", "2025")])
DEFAULT_REPS = 2000
DEFAULT_SEED = 20261010
MAX_GOALS_OK = N - 1

QCOLS = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR",
         "B365H", "B365D", "B365A", "B365>2.5", "B365<2.5",
         "PSH", "PSD", "PSA", "P>2.5", "P<2.5",
         "PSCH", "PSCD", "PSCA", "PC>2.5", "PC<2.5",
         "B365CH", "B365CD", "B365CA", "B365C>2.5", "B365C<2.5"]


# ---------------------------------------------------------------------------
# 1. Cattura del modello di produzione (walk-forward, testa intercettata)
# ---------------------------------------------------------------------------
def capture_production(prefix: str, league: str) -> pd.DataFrame:
    """Riga per partita: uscite complete di get_full_poisson_two_heads + lambda puri."""
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
        "league": league,
        "righe": int(len(prod)),
        "max_scarto_u25_vs_banco": float(np.max(np.abs(c_u25 - prod["engine_u25"].to_numpy()))),
        "max_scarto_gg_vs_banco": float(np.max(np.abs(c_gg - prod["engine_gg"].to_numpy()))),
        "max_scarto_somma_1X2_da_1": float(np.max(np.abs(
            np.array([o["1"] + o["X"] + o["2"] for o in captured]) - 1.0))),
    }
    out = pd.DataFrame({
        "league": league,
        "season": prod["season"].to_numpy(),
        "date_day": pd.to_datetime(prod["date"]).dt.normalize().to_numpy(),
        "home": prod["home"].to_numpy(),
        "away": prod["away"].to_numpy(),
        "fthg": prod["fthg"].astype(int).to_numpy(),
        "ftag": prod["ftag"].astype(int).to_numpy(),
        "mod_p1": [o["1"] for o in captured],
        "mod_pX": [o["X"] for o in captured],
        "mod_p2": [o["2"] for o in captured],
        "mod_u15": [o["u15"] for o in captured],
        "mod_u25": [o["u25"] for o in captured],
        "mod_u35": [o["u35"] for o in captured],
        "mod_gg": [o["gg"] for o in captured],
        "lam_h_tot": prod["lambda_home"].to_numpy(float),
        "lam_a_tot": prod["lambda_away"].to_numpy(float),
    })
    out.attrs["parity"] = parity
    return out


def load_production(use_cache: bool) -> tuple[pd.DataFrame, list[dict]]:
    if use_cache and os.path.exists(CACHE_PATH):
        cached = pd.read_pickle(CACHE_PATH)
        return cached["frame"], cached["parity"]
    frames, parity = [], []
    for prefix, league in LEAGUES:
        t0 = time.time()
        f = capture_production(prefix, league)
        parity.append(dict(f.attrs["parity"], secondi=round(time.time() - t0, 1)))
        frames.append(f)
    frame = pd.concat(frames, ignore_index=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    pd.to_pickle({"frame": frame, "parity": parity}, CACHE_PATH)
    return frame, parity


# ---------------------------------------------------------------------------
# 2. Quote dai CSV football-data (stagioni di valutazione)
# ---------------------------------------------------------------------------
def load_quotes(prefix: str, league: str) -> pd.DataFrame:
    frames = []
    for season, suffix in SEASON_FILE.items():
        raw = pd.read_csv(os.path.join(DB_DIR, f"{prefix}_{suffix}.csv"),
                          encoding="utf-8-sig", on_bad_lines="warn", low_memory=False)
        cols = {c: (raw[c] if c in raw.columns else np.nan) for c in QCOLS}
        df = pd.DataFrame(cols)
        df["season"] = season
        df["league"] = league
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    for c in QCOLS[3:]:
        if c not in ("FTR",):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    df["home"] = df["HomeTeam"].map(clean_name)
    df["away"] = df["AwayTeam"].map(clean_name)
    df["date_day"] = df["Date"].dt.normalize()
    df = df.drop_duplicates(subset=["league", "date_day", "home", "away"], keep="last")
    return df.reset_index(drop=True)


def coverage_table(q: pd.DataFrame, prod: pd.DataFrame) -> list[dict]:
    rows = []
    for (lg, se), g in q.groupby(["league", "season"], sort=False):
        m = prod[(prod.league == lg) & (prod.season == se)]
        ok1x2 = g[["B365H", "B365D", "B365A"]].notna().all(axis=1)
        oou = g[["B365>2.5", "B365<2.5"]].notna().all(axis=1)
        pin_c = g[["PSCH", "PSCD", "PSCA"]].notna().all(axis=1)
        pin_ou = g[["PC>2.5", "PC<2.5"]].notna().all(axis=1)
        rows.append({
            "lega": lg, "stagione": se, "partite_csv": int(len(g)),
            "con_modello": int(len(m)),
            "B365 1X2 ant.": int(ok1x2.sum()),
            "B365 O/U 2,5 ant.": int(oou.sum()),
            "Pinnacle 1X2 chiusura": int(pin_c.sum()),
            "Pinnacle O/U 2,5 chiusura": int(pin_ou.sum()),
            "Pinnacle chiusura completa (1X2+O/U)": int((pin_c & pin_ou).sum()),
        })
    return rows


# ---------------------------------------------------------------------------
# 3. Matrici per partita
# ---------------------------------------------------------------------------
def implicit_block(p_trip, p_ou, n_rows: int):
    """Fit DC e Poisson puro per ciascuna riga. Restituisce dict di array."""
    out = {k: np.zeros(n_rows) for k in ("dc_lam", "dc_mu", "dc_rho", "dc_res", "dc_res_ou",
                                         "po_lam", "po_mu", "po_res", "dc_conv", "po_conv")}
    P_dc = np.zeros((n_rows, 20))
    P_po = np.zeros((n_rows, 20))
    for i in range(n_rows):
        p1, pX, p2 = p_trip[i]
        pO = p_ou[i]
        f = fit_implicit(p1, pX, p2, pO, rho_free=True)
        g = fit_implicit(p1, pX, p2, pO, rho_free=False)
        out["dc_lam"][i], out["dc_mu"][i], out["dc_rho"][i] = f["lam"], f["mu"], f["rho"]
        out["dc_res"][i], out["dc_res_ou"][i] = f["max_abs_resid_1x2"], f["resid_ou25"]
        out["po_lam"][i], out["po_mu"][i], out["po_res"][i] = g["lam"], g["mu"], g["max_abs_resid"]
        out["dc_conv"][i], out["po_conv"][i] = f["converged"], g["converged"]
        P_dc[i] = grid_markets(dc_matrix(f["lam"], f["mu"], f["rho"]))
        P_po[i] = grid_markets(dc_matrix(g["lam"], g["mu"], 0.0))
    return out, P_dc, P_po


def model_matrix(prod: pd.DataFrame) -> np.ndarray:
    """Probabilita' del modello di produzione per i 20 mercati (ordine MARKET_NAMES)."""
    from scipy.stats import poisson
    NN = N
    P = np.zeros((len(prod), 20))
    names = MARKET_NAMES
    p1 = prod["mod_p1"].to_numpy(); pX = prod["mod_pX"].to_numpy(); p2 = prod["mod_p2"].to_numpy()
    P[:, names.index("1")] = p1
    P[:, names.index("X")] = pX
    P[:, names.index("2")] = p2
    P[:, names.index("1X")] = p1 + pX
    P[:, names.index("X2")] = pX + p2
    P[:, names.index("12")] = p1 + p2
    P[:, names.index("Over 1.5")] = 1 - prod["mod_u15"].to_numpy()
    P[:, names.index("Under 1.5")] = prod["mod_u15"].to_numpy()
    P[:, names.index("Over 2.5")] = 1 - prod["mod_u25"].to_numpy()
    P[:, names.index("Under 2.5")] = prod["mod_u25"].to_numpy()
    P[:, names.index("Over 3.5")] = 1 - prod["mod_u35"].to_numpy()
    P[:, names.index("Under 3.5")] = prod["mod_u35"].to_numpy()
    P[:, names.index("Gol")] = prod["mod_gg"].to_numpy()
    P[:, names.index("No Gol")] = 1 - prod["mod_gg"].to_numpy()
    # combinazioni: griglia congiunta Poisson dai lambda puri della testa Totali
    from griglia_core import _H, _D, _A, _T, _GG
    for i, (lh, la) in enumerate(zip(prod["lam_h_tot"].to_numpy(), prod["lam_a_tot"].to_numpy())):
        m = np.outer(poisson.pmf(np.arange(NN), lh), poisson.pmf(np.arange(NN), la))
        m = m / m.sum()
        P[i, names.index("1+Over 1.5")] = m[_H & (_T > 1.5)].sum()
        P[i, names.index("2+Over 1.5")] = m[_A & (_T > 1.5)].sum()
        P[i, names.index("1X+Over 1.5")] = m[(_H | _D) & (_T > 1.5)].sum()
        P[i, names.index("X2+Under 3.5")] = m[(_D | _A) & (_T < 3.5)].sum()
        P[i, names.index("1+Gol")] = m[_H & _GG].sum()
        P[i, names.index("2+Gol")] = m[_A & _GG].sum()
    return P


# ---------------------------------------------------------------------------
# 4. Valutazione
# ---------------------------------------------------------------------------
def evaluate(P_imp, P_mod, Y, blocks, reps, seed, label):
    """Brier per mercato, differenza modello - griglia con IC a blocchi, decisione."""
    rng = np.random.default_rng(seed)
    B_imp = brier_per_match(P_imp, Y)
    B_mod = brier_per_match(P_mod, Y)
    rows = []
    for j, name in enumerate(MARKET_NAMES):
        d = B_mod[:, j] - B_imp[:, j]          # > 0: la griglia implicita e' migliore
        bs = block_bootstrap_mean_diff(d, blocks, reps, rng)
        rows.append({
            "mercato": name, "n": int(len(d)),
            "brier_implicita": float(B_imp[:, j].mean()),
            "brier_modello": float(B_mod[:, j].mean()),
            "delta_mod_meno_imp": bs["mean"], "ic_lo": bs["lo"], "ic_hi": bs["hi"],
            "blocchi": bs["n_blocchi"],
            "decisione": decide_replace(bs["lo"], bs["hi"]),
            "fonte": label,
        })
    return rows


def calibration_block(P, Y, bands):
    out = OrderedDict()
    for j, name in enumerate(MARKET_NAMES):
        out[name] = calibration_rows(P[:, j], Y[:, j], bands)
    return out


def md_table(headers, rows):
    head = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join(["---"] * len(headers)) + "|"
    body = ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join([head, sep] + body)


def fmt(x, nd=4):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/d"
    return f"{x:.{nd}f}".replace(".", ",")


def fci(d, lo, hi, nd=4):
    return f"{fmt(d, nd)} [{fmt(lo, nd)}; {fmt(hi, nd)}]"


def git_facts():
    def run(*a):
        try:
            return subprocess.check_output(["git", *a], cwd=_REPO_ROOT, text=True,
                                           stderr=subprocess.DEVNULL).strip()
        except Exception:
            return "n/d"
    return {"commit": run("rev-parse", "HEAD"), "branch": run("rev-parse", "--abbrev-ref", "HEAD")}


# ---------------------------------------------------------------------------
# 5. Bet365 vs Pinnacle (sezione D)
# ---------------------------------------------------------------------------
def bet365_pairs(q: pd.DataFrame) -> pd.DataFrame:
    """Una riga per (partita, lato): quota B365, quota Pinnacle, esito e fascia di quota."""
    recs = []
    specs = [
        ("1X2 ant.", ["B365H", "B365D", "B365A"], ["PSH", "PSD", "PSA"], ["1", "X", "2"]),
        ("O/U 2,5 ant.", ["B365<2.5", "B365>2.5"], ["P<2.5", "P>2.5"], ["U", "O"]),
        ("1X2 chiusura", ["B365CH", "B365CD", "B365CA"], ["PSCH", "PSCD", "PSCA"], ["1", "X", "2"]),
        ("O/U 2,5 chiusura", ["B365C<2.5", "B365C>2.5"], ["PC<2.5", "PC>2.5"], ["U", "O"]),
    ]
    for mkt, bcols, pcols, labels in specs:
        sub = q[["league", "season", "date_day", "home", "away"] + bcols + pcols].dropna()
        for _, r in sub.iterrows():
            b = r[bcols].to_numpy(float)
            p = r[pcols].to_numpy(float)
            fair = devig_prop(p)
            if fair is None or np.any(b <= 1.0):
                continue
            ov_b = overround(b)
            ov_p = overround(p)
            for k, lab in enumerate(labels):
                recs.append({
                    "mercato": mkt, "lega": r["league"], "stagione": r["season"],
                    "date_day": r["date_day"], "home": r["home"], "away": r["away"],
                    "esito": lab, "quota_b365": b[k], "quota_pin": p[k],
                    "p_fair_pin": fair[k], "ov_b365": ov_b, "ov_pin": ov_p,
                    "r_b365_pin": (1.0 / b[k]) / fair[k],
                })
    return pd.DataFrame(recs)


FAIR_ODD_BANDS = [(0.0, 1.5, "<1,50"), (1.5, 2.0, "1,50-2,00"), (2.0, 3.0, "2,00-3,00"),
                  (3.0, 5.0, "3,00-5,00"), (5.0, 1e9, "≥5,00")]


def odd_band(fair_odd: np.ndarray) -> np.ndarray:
    out = np.empty(len(fair_odd), dtype=object)
    for lo, hi, lab in FAIR_ODD_BANDS:
        m = (fair_odd >= lo) & (fair_odd < hi)
        out[m] = lab
    return out


def bet365_analysis(pairs: pd.DataFrame):
    """Margine per lega e fascia, stima R(lega, fascia, tipo) su 2024/25, test su 2025/26."""
    res = {}
    summ_rows, margin_rows, est_rows = [], [], []
    pre = pairs[pairs.mercato.isin(["1X2 ant.", "O/U 2,5 ant."])].copy()
    pre["tipo"] = np.where(pre.mercato == "1X2 ant.", "1X2", "O/U 2,5")
    pre["fascia"] = odd_band(1.0 / pre["p_fair_pin"].to_numpy())
    # margine per lega (una riga per partita e tipo)
    per_match = pre.drop_duplicates(subset=["mercato", "lega", "stagione", "date_day", "home", "away"])
    for (mkt, lg), g in per_match.groupby(["mercato", "lega"]):
        margin_rows.append([mkt, lg, len(g),
                            fmt(g.ov_b365.median() * 100, 2) + " %",
                            fmt(g.ov_pin.median() * 100, 2) + " %",
                            fmt((g.ov_b365 - g.ov_pin).median() * 100, 2) + " pt",
                            fmt((g.ov_b365 - g.ov_pin).quantile(0.1) * 100, 2) + " pt",
                            fmt((g.ov_b365 - g.ov_pin).quantile(0.9) * 100, 2) + " pt"])
    # margine effettivo per fascia di quota equa (r = q_B365 / p_pin)
    for (tipo, fb), g in pre.groupby(["tipo", "fascia"], sort=False):
        summ_rows.append([tipo, fb, len(g), fmt(g.r_b365_pin.median(), 4),
                          fmt((g.r_b365_pin.median() - 1) * 100, 2) + " %"])
    # stima: R per (lega, fascia, tipo) su 2024/25, test su 2025/26
    tr = pre[pre.stagione == "2024/25"]
    te = pre[pre.stagione == "2025/26"]
    R_loc = tr.groupby(["lega", "tipo", "fascia"])["r_b365_pin"].median()
    R_tipo = tr.groupby(["tipo", "fascia"])["r_b365_pin"].median()
    R_glob = tr.groupby(["tipo"])["r_b365_pin"].median()
    R_fixed = tr["r_b365_pin"].median()
    res["R_loc"] = {f"{a}|{b}|{c}": float(v) for (a, b, c), v in R_loc.items()}

    def predict(sub, mode):
        if mode == "lega x fascia x tipo":
            R = [R_loc.get((r.lega, r.tipo, r.fascia), np.nan) for r in sub.itertuples()]
        elif mode == "fascia x tipo (senza lega)":
            R = [R_tipo.get((r.tipo, r.fascia), np.nan) for r in sub.itertuples()]
        elif mode == "tipo (senza fascia)":
            R = [R_glob.get(r.tipo, np.nan) for r in sub.itertuples()]
        else:
            R = [R_fixed] * len(sub)
        R = np.asarray(R, float)
        pred_odd = 1.0 / (sub["p_fair_pin"].to_numpy() * R)
        return pred_odd

    for mode in ("lega x fascia x tipo", "fascia x tipo (senza lega)",
                 "tipo (senza fascia)", "costante (nessuna segmentazione)"):
        for label, data in (("test 2025/26 (fuori campione)", te), ("in campione 2024/25", tr)):
            po = predict(data, mode)
            ok = np.isfinite(po)
            b = data["quota_b365"].to_numpy(float)[ok]
            p = po[ok]
            err_pct = (p / b - 1.0)
            p_true = 1.0 / b
            p_hat = 1.0 / p
            est_rows.append([mode, label, int(ok.sum()),
                             fmt(np.median(np.abs(err_pct)) * 100, 2) + " %",
                             fmt(np.mean(np.abs(err_pct)) * 100, 2) + " %",
                             fmt(np.quantile(np.abs(err_pct), 0.9) * 100, 2) + " %",
                             fmt(np.mean(err_pct) * 100, 2) + " %",
                             fmt(np.mean(np.abs(p_hat - p_true)) * 100, 2) + " pt"])
    res["estimate_test_note"] = ("R = q_B365 / p_depurata_Pinnacle stimato in 2024/25; "
                                 "test sul 2025/26. Errore = quota stimata / quota reale - 1.")
    res["n_pre_1x2_ou"] = int(len(pre))
    return summ_rows, margin_rows, est_rows, res


# ---------------------------------------------------------------------------
# 6. Report
# ---------------------------------------------------------------------------
def build_report(p: dict) -> str:
    T = []
    A = T.append
    A("# Griglia implicita nelle quote: fattibilita' sui mercati gol (sola lettura)\n")
    A(f"Generato da `audit/griglia_implicita.py` il {p['generato_il']} "
      f"(commit `{p['git']['commit'][:12]}`, branch `{p['git']['branch']}`). "
      "Nessuna modifica a `SoccerMath/` (app.py incluso), nessun replay `--write`, "
      "nessuna chiave API. Probabilita' di `topmix_mercato_v3` invariate: il codice non le tocca.\n")
    A("**Stato: fattibilita' di audit. Nessuna regola di selezione delle giocate cambia.**\n")

    A("## 0. Ambiente e fonti\n")
    A(md_table(["voce", "valore"], [
        ["Python", p["python"]], ["numpy / pandas / scipy", p["versioni"]],
        ["Campione", "2024/25 + 2025/26, 5 leghe (CSV football-data in SoccerMath/database)"],
        ["Griglia implicita", "Dixon-Coles, (lambda, mu, rho) per partita su 1X2 + O/U 2,5 de-vig proporzionale; "
                              "tau come `models/dixon_coles.tau_correction`; griglia 0..15"],
        ["Griglia Poisson implicita (confronto)", "stesso fit con rho = 0"],
        ["Modello di produzione", "Poisson walk-forward: `ppda_residual_test.production_totali` + "
                                  "`app.get_full_poisson_two_heads` intercettata (1X2 dalla testa 1X2, O/U e Gol dalla testa Totali)"],
        ["Combinazioni del modello", "griglia Poisson congiunta dai lambda puri della testa Totali (limite dichiarato)"],
        ["Bootstrap", f"{p['reps']} repliche, blocchi lega x stagione x data, IC 95% percentile, seme {p['seed']}"],
        ["Tempo di esecuzione", p["tempo"]],
    ]))
    A("")

    A("### 0.1 Parita' della cattura di produzione (intercettata vs banco)\n")
    A("Le uscite intercettate devono coincidere con le colonne del banco `production_totali`; scarto atteso 0.\n")
    A(md_table(["lega", "righe", "max |u25 intercettato − banco|", "max |gg intercettato − banco|",
                "max |1+X+2 − 1|"],
               [[x["league"], x["righe"], f"{x['max_scarto_u25_vs_banco']:.2e}",
                 f"{x['max_scarto_gg_vs_banco']:.2e}", f"{x['max_scarto_somma_1X2_da_1']:.2e}"]
                for x in p["parity"]]))
    A("")

    A("## 1. Copertura per lega e stagione (prima di qualsiasi valutazione)\n")
    A("Righe dei CSV, righe con modello, quote disponibili per il campione. "
      "Il campione principale usa solo le partite con modello E terna B365 1X2 e B365 O/U 2,5 complete.\n")
    hdr = list(p["coverage"][0].keys())
    A(md_table(hdr, [list(r.values()) for r in p["coverage"]]))
    A("")
    A(f"Campione principale: **{p['n_main']}** partite (2024/25 + 2025/26). "
      f"Sottocampione Pinnacle chiusura completa (sensibilita'): **{p['n_pin']}**.\n")
    A("Nota: su 2025/26 le quote Pinnacle di chiusura (PSC*) sono presenti solo per una parte "
      "delle partite (CSV football-data, campo non sempre valorizzato): e' la ragione del sottocampione.\n")

    A("## 2. Verifica di riproduzione della griglia implicita\n")
    A("Errore massimo |predetto − di partenza| sulle 4 quote di partenza (1, X, 2, Over 2,5), "
      "per partita, sul campione principale.\n")
    A(md_table(["griglia", "max", "p99", "mediana", "partite con residuo > 1e-6", "convergenza"], [
        ["Dixon-Coles (rho stimato)", fmt(p["res_dc"]["max"], 8), fmt(p["res_dc"]["p99"], 8),
         fmt(p["res_dc"]["med"], 8), p["res_dc"]["n_gt"], f"{p['res_dc']['conv']} / {p['n_main']}"],
        ["Poisson puro implicito (rho = 0)", fmt(p["res_po"]["max"], 8), fmt(p["res_po"]["p99"], 8),
         fmt(p["res_po"]["med"], 8), p["res_po"]["n_gt"], f"{p['res_po']['conv']} / {p['n_main']}"],
    ]))
    A("")
    A("Lettura: la griglia Dixon-Coles ha 3 parametri per 4 quote di partenza, quindi riproduce "
      "il punto esatto quando il sistema e' risolvibile; il Poisson puro ha 2 parametri e NON "
      "riproduce in generale tutte e 4 le quote. Il residuo del Poisson puro e' informazione, "
      "non un errore del codice.\n")
    A(f"Rho stimati (DC): mediana {fmt(p['rho_med'],3)}, 5°-95° percentile "
      f"[{fmt(p['rho_p05'],3)}; {fmt(p['rho_p95'],3)}]; quota di partite al bordo di rho "
      f"(|rho| ≥ 0,49): {fmt(p['rho_bordo']*100,1)} %.\n")

    A("## 3. Brier per mercato: griglia implicita vs modello di produzione (campione principale)\n")
    A("Brier binario medio (piu' basso = meglio). Δ = Brier(modello) − Brier(griglia implicita): "
      "Δ > 0 significa che la griglia implicita e' migliore. IC 95% con bootstrap a blocchi. "
      "Regola dichiarata: la griglia implicita sostituisce il modello sul mercato se il suo Brier "
      "e' migliore con IC che esclude lo zero.\n")
    rows = []
    for r in p["main_rows"]:
        rows.append([r["mercato"], r["n"], fmt(r["brier_implicita"]), fmt(r["brier_modello"]),
                     fci(r["delta_mod_meno_imp"], r["ic_lo"], r["ic_hi"]), r["decisione"]])
    A(md_table(["mercato", "n", "Brier griglia implicita (DC)", "Brier modello (Poisson di produzione)",
                "Δ modello − griglia [IC 95%]", "esito della regola"], rows))
    A("")
    A("**Attenzione alla lettura.** (1) Le 20 righe non sono 20 prove indipendenti: 1X e' il complemento "
      "di 2, X2 di 1, 12 di X, Under di Over (stessa linea), No Gol di Gol. Per costruzione hanno lo stesso "
      "Brier: le informazioni distinte sono 10. (2) La griglia implicita viene dalle quote bet365 "
      "pre-partita de-vig: il vantaggio sul Brier misura quanta informazione contengono le quote, "
      "NON un edge sul banco. Il Brier non dice nulla sul valore di una giocata a quota.\n")

    A("### 3.1 Confronto aggiuntivo: Dixon-Coles implicito vs Poisson puro implicito\n")
    A("Stesso input (1X2 + O/U 2,5 B365), solo rho diverso. Non e' la regola di sostituzione: "
      "serve a dire se il rho stimato dalle quote aggiunge informazione.\n")
    A(md_table(["mercato", "Brier DC", "Brier Poisson puro", "Δ Poisson − DC [IC 95%]"],
               [[r["mercato"], fmt(r["b_dc"]), fmt(r["b_po"]), fci(r["d"], r["lo"], r["hi"])]
                for r in p["dc_vs_po"]]))
    A("")

    A("## 4. Calibrazione per fasce di probabilita' (campione principale)\n")
    A("Per ogni mercato: partite con probabilita' dichiarata dell'evento nella fascia; "
      "n, probabilita' media dichiarata (p) e frequenza osservata (f). Celle vuote = n = 0.\n")
    for label, cal in (("4.1 Griglia implicita (Dixon-Coles)", p["cal_imp"]),
                       ("4.2 Modello di produzione (Poisson)", p["cal_mod"])):
        A(f"### {label}\n")
        rows = []
        for mkt, rs in cal.items():
            cells = []
            for rr in rs:
                cells.append(f"n={rr['n']}; p={fmt(rr['p_media'],3)}; f={fmt(rr['freq_osservata'],3)}"
                             if rr["n"] else "—")
            rows.append([mkt] + cells)
        A(md_table(["mercato"] + list(BANDS.keys()), rows))
        A("")

    A("## 5. Fascia alta (≥ 0,65): quella da cui si scelgono le giocate\n")
    A("Calibrazione separata nella fascia alta. Per ogni mercato e fonte: n, p media dichiarata, "
      "frequenza osservata, differenza f − p (in punti percentuali).\n")
    rows = []
    for mkt in MARKET_NAMES:
        ri = p["high_imp"][mkt]
        rm = p["high_mod"][mkt]
        def cell(r):
            if r["n"] == 0:
                return "—"
            return (f"n={r['n']}; p={fmt(r['p_media'],3)}; f={fmt(r['freq_osservata'],3)}; "
                    f"f−p={fmt((r['freq_osservata']-r['p_media'])*100,1)} pt")
        rows.append([mkt, cell(_agg(ri)), cell(_agg(rm))])
    A(md_table(["mercato", "griglia implicita (≥ 0,65)", "modello di produzione (≥ 0,65)"], rows))
    A("")
    A("Fasce alte per mercato (griglia implicita): " + "; ".join(
        f"**{k}**" for k in HIGH_BANDS) + ".\n")
    rows = []
    for mkt in MARKET_NAMES:
        cells = []
        for src in (p["high_imp_bands"], p["high_mod_bands"]):
            rs = src[mkt]
            cells.append(" · ".join(f"{x['fascia']}: n={x['n']}" + (
                f", p={fmt(x['p_media'],2)}, f={fmt(x['freq_osservata'],2)}" if x["n"] else "")
                for x in rs))
        rows.append([mkt] + cells)
    A(md_table(["mercato", "griglia implicita: fasce ≥0,65", "modello: fasce ≥0,65"], rows))
    A("")

    A("## 6. Conclusione per mercato (regola dichiarata)\n")
    A("Regola applicata come dichiarata prima di guardare i risultati: la griglia implicita sostituisce il modello sul mercato se il suo Brier e' migliore con IC 95% che esclude lo zero; altrimenti \"nessuna differenza dimostrata\". "
      "La decisione e' riportata per tutti i 20 mercati, anche se sono 10 informazioni distinte (vedi §3).\n")
    A(md_table(["mercato", "decisione", "motivo"],
               [[r["mercato"], r["decisione"],
                 f"Δ {fci(r['delta_mod_meno_imp'], r['ic_lo'], r['ic_hi'])}, n={r['n']}"]
                for r in p["main_rows"]]))
    A("")
    A(f"Mercati in cui la griglia implicita sostituisce il modello: **{p['n_sost']}** su {len(MARKET_NAMES)}. "
      "Per gli altri: nessuna differenza dimostrata, oppure modello migliore dimostrato (vedi colonna).\n")

    A("## 7. Sensibilita': Pinnacle di chiusura (sottocampione)\n")
    A(f"Stessa regola, con griglia implicita da Pinnacle di chiusura, su **{p['n_pin']}** partite "
      "con quote complete. Non cambia la conclusione principale: e' informativa.\n")
    A(md_table(["mercato", "n", "Brier griglia (Pin. ch.)", "Brier modello", "Δ [IC 95%]", "esito"],
               [[r["mercato"], r["n"], fmt(r["brier_implicita"]), fmt(r["brier_modello"]),
                 fci(r["delta_mod_meno_imp"], r["ic_lo"], r["ic_hi"]), r["decisione"]]
                for r in p["pin_rows"]]))
    A("")

    A("## 8. Bet365 vs Pinnacle: margine e stima della quota (sezione D)\n")
    A("Margine = Σ(1/quota) − 1 per libro. Fasce per **quota equa Pinnacle** (1/p depurata). "
      "Per la stima: R = q_B365 / p_depurata_Pinnacle, con p depurata proporzionale. "
      "La stima della quota bet365 e' q̂ = 1 / (p_depurata · R̂).\n")
    A("### 8.1 Margine per lega (partite del campione 2024/25 + 2025/26, quote anticipate)\n")
    A(md_table(["mercato", "lega", "partite", "margine mediano B365", "margine mediano Pinnacle",
                "B365 − Pinnacle (mediana)", "P10", "P90"], p["bet_margin_rows"]))
    A("")
    A("### 8.2 Margine effettivo per fascia di quota equa (r = q_B365 / p_depurata − 1)\n")
    A(md_table(["tipo", "fascia di quota equa", "n esiti", "r mediano", "margine effettivo mediano"],
               p["bet_band_rows"]))
    A("")
    A("### 8.3 Errore della stima della quota bet365 (fuori campione)\n")
    A(p["bet_est_note"] + "\n")
    A(md_table(["modello di stima", "campione", "n", "errore assoluto mediano (quota)",
                "errore assoluto medio", "P90 errore assoluto", "errore medio con segno",
                "errore medio in probabilita'"], p["bet_est_rows"]))
    A("")

    A("## 9. Limiti e cosa non e' verificato\n")
    for x in p["limiti"]:
        A(f"- {x}")
    A("")
    A("## 10. Libreria penaltyblog (sezione A)\n")
    A(p["pb_section"])
    A("")
    return "\n".join(T)


def _agg(rs):
    """Aggrega le fasce ≥0,65 in un'unica riga (n, media ponderata di p e di f)."""
    n = sum(r["n"] for r in rs)
    if n == 0:
        return {"n": 0}
    p_m = sum(r["n"] * r["p_media"] for r in rs if r["n"]) / n
    f_m = sum(r["n"] * r["freq_osservata"] for r in rs if r["n"]) / n
    return {"n": n, "p_media": p_m, "freq_osservata": f_m}


def _pb_section() -> str:
    if not os.path.exists(PB_JSON):
        return ("Verifica penaltyblog non ancora eseguita: vedi `audit/griglia_penaltyblog_check.py` "
                "(venv separato, non nel campione di produzione).")
    with open(PB_JSON, encoding="utf-8") as fh:
        d = json.load(fh)
    return d["sezione_md"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-cache", action="store_true", help="ricalcola la cattura di produzione")
    ap.add_argument("--reps", type=int, default=DEFAULT_REPS)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--report", default=REPORT_PATH)
    ap.add_argument("--json", default=os.path.join(OUT_DIR, "griglia_implicita.json"))
    args = ap.parse_args(argv)
    t_start = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)

    prod, parity = load_production(use_cache=not args.no_cache)
    prod = prod[prod.season.isin(EVAL_SEASONS)].copy()

    quotes = pd.concat([load_quotes(pfx, lg) for pfx, lg in LEAGUES], ignore_index=True)
    cov_src = quotes.copy()
    cov_prod = prod.copy()
    coverage = coverage_table(cov_src, cov_prod)

    key = ["league", "date_day", "home", "away"]
    q_cols = key + ["season", "FTHG", "FTAG", "B365H", "B365D", "B365A", "B365>2.5", "B365<2.5",
                    "PSCH", "PSCD", "PSCA", "PC>2.5", "PC<2.5",
                    "PSH", "PSD", "PSA", "P>2.5", "P<2.5",
                    "B365CH", "B365CD", "B365CA", "B365C>2.5", "B365C<2.5"]
    m = prod.merge(quotes[q_cols], on=key, how="left", validate="one_to_one", suffixes=("", "_q"))
    matched = m["season_q"].notna()
    assert (m.loc[matched, "season"] == m.loc[matched, "season_q"]).all(), "stagione discordante"
    assert (m.loc[matched, "fthg"] == m.loc[matched, "FTHG"]).all(), "gol discordanti"
    assert (m.loc[matched, "ftag"] == m.loc[matched, "FTAG"]).all(), "gol discordanti"
    print(f"[griglia] partite del modello senza quote CSV: {int((~matched).sum())}", flush=True)
    m = m.reset_index(drop=True)

    # campione principale: modello + B365 1X2 + B365 O/U 2,5 completi
    ok = (m[["B365H", "B365D", "B365A"]].notna().all(axis=1)
          & m[["B365>2.5", "B365<2.5"]].notna().all(axis=1))
    main = m[ok].reset_index(drop=True)
    n_main = len(main)

    p_trip = np.array([devig_prop([r.B365H, r.B365D, r.B365A]) for r in main.itertuples()])
    p_ou = np.array([devig_prop([a, b])[0] for a, b in zip(main["B365>2.5"], main["B365<2.5"])])
    assert np.all(np.isfinite(p_trip)) and np.all(np.isfinite(p_ou))

    print(f"[griglia] campione principale: {n_main} partite; fit implicito...", flush=True)
    t0 = time.time()
    fit, P_dc, P_po = implicit_block(p_trip, p_ou, n_main)
    print(f"[griglia] fit in {time.time()-t0:.1f}s", flush=True)
    P_mod = model_matrix(main)
    Y = outcome_matrix(main["fthg"].to_numpy(), main["ftag"].to_numpy())
    blocks = (main["league"] + "|" + main["season"] + "|" + main["date_day"].dt.strftime("%Y-%m-%d")).to_numpy()

    rng_seed = args.seed
    main_rows = evaluate(P_dc, P_mod, Y, blocks, args.reps, rng_seed, "B365 ant.")

    # DC vs Poisson puro implicito (stesso input)
    rng = np.random.default_rng(rng_seed + 1)
    B_dc = brier_per_match(P_dc, Y)
    B_po = brier_per_match(P_po, Y)
    dc_vs_po = []
    for j, name in enumerate(MARKET_NAMES):
        d = B_po[:, j] - B_dc[:, j]
        bs = block_bootstrap_mean_diff(d, blocks, args.reps, rng)
        dc_vs_po.append({"mercato": name, "b_dc": float(B_dc[:, j].mean()),
                         "b_po": float(B_po[:, j].mean()), "d": bs["mean"],
                         "lo": bs["lo"], "hi": bs["hi"]})

    # calibrazione
    cal_imp = calibration_block(P_dc, Y, BANDS)
    cal_mod = calibration_block(P_mod, Y, BANDS)
    high_imp_bands = calibration_block(P_dc, Y, HIGH_BANDS)
    high_mod_bands = calibration_block(P_mod, Y, HIGH_BANDS)
    high_imp = {mk: calibration_rows(P_dc[:, j], Y[:, j], {"≥0,65": (0.65, 1.0000001)})
                for j, mk in enumerate(MARKET_NAMES)}
    high_mod = {mk: calibration_rows(P_mod[:, j], Y[:, j], {"≥0,65": (0.65, 1.0000001)})
                for j, mk in enumerate(MARKET_NAMES)}

    # griglia: errori di riproduzione
    def stats(v):
        v = np.asarray(v, float)
        return {"max": float(v.max()), "p99": float(np.quantile(v, 0.99)),
                "med": float(np.median(v)), "n_gt": int((v > 1e-6).sum())}
    res_dc = stats(np.maximum(fit["dc_res"], fit["dc_res_ou"]))
    res_dc["conv"] = int(fit["dc_conv"].sum())
    res_po = stats(fit["po_res"])
    res_po["conv"] = int(fit["po_conv"].sum())
    rho = fit["dc_rho"]
    rho_stats = {"rho_med": float(np.median(rho)), "rho_p05": float(np.quantile(rho, 0.05)),
                 "rho_p95": float(np.quantile(rho, 0.95)),
                 "rho_bordo": float(np.mean(np.abs(rho) >= 0.49))}

    # sensibilita': Pinnacle di chiusura
    pin_ok = main[["PSCH", "PSCD", "PSCA", "PC>2.5", "PC<2.5"]].notna().all(axis=1)
    pin_cand = main[pin_ok].reset_index(drop=True)
    tr_pin = [devig_prop([a, b, c]) for a, b, c in zip(pin_cand.PSCH, pin_cand.PSCD, pin_cand.PSCA)]
    ou_pin = [devig_prop([a, b]) for a, b in zip(pin_cand["PC>2.5"], pin_cand["PC<2.5"])]
    valid_pin = np.array([t is not None and o is not None for t, o in zip(tr_pin, ou_pin)], bool)
    print(f"[griglia] sensibilita' Pinnacle: quote non valide scartate: {int((~valid_pin).sum())}", flush=True)
    pin = pin_cand[valid_pin].reset_index(drop=True)
    n_pin = len(pin)
    pin_rows = []
    if n_pin:
        p_trip_pin = np.array([t for t, v in zip(tr_pin, valid_pin) if v])
        p_ou_pin = np.array([o[0] for o, v in zip(ou_pin, valid_pin) if v])
        fit_pin, P_pin, _ = implicit_block(p_trip_pin, p_ou_pin, n_pin)
        P_mod_pin = model_matrix(pin)
        Y_pin = outcome_matrix(pin.fthg.to_numpy(), pin.ftag.to_numpy())
        blocks_pin = (pin["league"] + "|" + pin["season"] + "|" + pin["date_day"].dt.strftime("%Y-%m-%d")).to_numpy()
        pin_rows = evaluate(P_pin, P_mod_pin, Y_pin, blocks_pin, args.reps, rng_seed + 2, "Pin. ch.")

    # bet365 vs Pinnacle (su tutto il campione delle due stagioni, non solo la parte con modello)
    pairs = bet365_pairs(quotes[quotes.season.isin(EVAL_SEASONS)])
    band_rows, margin_rows, est_rows, bet_info = bet365_analysis(pairs)

    # penaltyblog: sezione A (se la verifica e' gia' stata eseguita)
    pb_section = _pb_section()

    main_sust = [r for r in main_rows if r["decisione"].startswith("SOSTITUISCE")]
    limiti = [
        "Il fit implicito usa 1X2 e Over 2,5 B365 ANTICIPATE: sono quote 'pre' senza orario di rilevazione nel CSV; la dicitura pre-chiusura e' dichiarata, non verificata dal file.",
        "Quote Pinnacle: colonne PS*/P>2,5 usate come anticipate e PSC*/PC>2,5 come chiusura, per convenzione football-data; non verificato dal file quale sia apertura o chiusura per ogni campo.",
        "I mercati Over/Under 1,5 e 3,5 e Gol/No Gol NON sono quotati nel campione: sono ricavati dalla griglia implicita (1X2 + O/U 2,5). La loro qualita' dipende dalla forma della griglia, non da una quota diretta.",
        "Combinazioni (1+Over 1,5, ecc.) del modello: nessuna griglia congiunta di produzione; usata la griglia Poisson dai lambda puri della testa Totali. Non e' la griglia che produce il 1X2 del modello: confronto con un'approssimazione dichiarata.",
        "Il bootstrap usa la data come giornata (il CSV non ha la giornata): i blocchi possono essere piu' fini della giornata reale per turni spezzati su piu' date.",
        "Il Brier non e' pesato per quota: non dice nulla sul valore economico (EV) di una giocata. Questo referto valuta la probabilita', non il profitto.",
        "Nessun replay del Registro, nessuna scrittura: le probabilita' di topmix_mercato_v3 non sono state rigenerate in questo referto.",
    ]
    payload = {
        "generato_il": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git": git_facts(),
        "python": platform.python_version(),
        "versioni": "numpy {}, pandas {}, scipy {}".format(
            np.__version__, pd.__version__, __import__("scipy").__version__),
        "reps": args.reps, "seed": args.seed,
        "tempo": f"{time.time() - t_start:.0f} s",
        "parity": parity,
        "coverage": coverage,
        "n_main": n_main, "n_pin": n_pin,
        "res_dc": res_dc, "res_po": res_po, **rho_stats,
        "main_rows": main_rows, "dc_vs_po": dc_vs_po,
        "cal_imp": cal_imp, "cal_mod": cal_mod,
        "high_imp": high_imp, "high_mod": high_mod,
        "high_imp_bands": high_imp_bands, "high_mod_bands": high_mod_bands,
        "pin_rows": pin_rows, "n_sost": len(main_sust),
        "bet_margin_rows": margin_rows, "bet_band_rows": band_rows,
        "bet_est_rows": est_rows, "bet_est_note": bet_info["estimate_test_note"],
        "limiti": limiti, "pb_section": pb_section,
    }
    report = build_report(payload)
    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as fh:
        fh.write(report)

    # output non versionati
    serial = {k: v for k, v in payload.items() if k not in ("coverage",)}
    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump(serial, fh, ensure_ascii=False, indent=2, default=str)
    rows_out = main[["league", "season", "date_day", "home", "away", "fthg", "ftag"]].copy()
    for j, name in enumerate(MARKET_NAMES):
        rows_out[f"imp|{name}"] = P_dc[:, j]
        rows_out[f"mod|{name}"] = P_mod[:, j]
    rows_out["dc_lam"], rows_out["dc_mu"], rows_out["dc_rho"] = fit["dc_lam"], fit["dc_mu"], fit["dc_rho"]
    rows_out.to_csv(os.path.join(OUT_DIR, "griglia_matches.csv.gz"), index=False, compression="gzip")
    print(f"[griglia] referto: {args.report}", flush=True)
    print(f"[griglia] tempo totale: {time.time()-t_start:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
