#!/usr/bin/env python3
"""bookmaker_source_test.py — Quale bookmaker basta? (audit, SOLA LETTURA).

DOMANDA (punto 1 della commessa). Sulle 5 leghe del progetto, una quota media
de-vigata (``Avg``), il massimo del mercato (``Max``), Pinnacle (``PS``) o un
consenso fra bookmaker valgono quanto Bet365 come base di partenza? Serve a
sapere se una fonte dal vivo deve per forza portare Bet365.

PROTOCOLLO: identico a quello della PR #49 (``audit/onex2_market_test.py``),
di cui si RIUSANO le funzioni, non si riscrivono:
  * stagioni valutate 2024/25 e 2025/26 (file ``SoccerMath/database/<Lega>_2024.csv``
    e ``_2025.csv``), nessuna modifica ai CSV;
  * de-vig PROPORZIONALE (``backtest_experiment_all.devig_1x2``) come decisione
    e de-vig SHIN a 3 esiti (``onex2_market_test.devig_shin3``) come sensibilita';
  * metriche ``summary``: LogLoss, Brier, RPS, BSS contro il base rate del train
    (stagioni precedenti della lega, ``onex2_market_test.train_base_rate``) e
    reliability/resolution per esito a 10 bin (``baserate_oos.decomp``);
  * regola Top Mix di produzione: esito piu' probabile ammesso se >= 0.55;
  * bootstrap a blocchi (lega x stagione x giornata), 2000 repliche, seed 20261008.

FONTIE CONFRONTATE (colonne pre-chiusura dei CSV football-data):
  singoli book: B365 (riferimento), BFD (Betfred), BMGM (BetMGM), BV (BetVictor),
  BW (Bet&Win/bwin), CL (Coral), LB (Ladbrokes), PS (Pinnacle);
  scambio:      BFE (Betfair Exchange, senza commissione);
  aggregati:    Avg (media di mercato), Max (massimo di mercato);
  consenso:     media delle probabilita' de-vigate dei singoli book disponibili
                (>= 3 book validi sulla stessa partita).
  Contesto (chiude il confronto, informazione tardiva): B365 e Pinnacle di
  CHIUSURA (colonne con la ``C``).

REGOLA DI DECISIONE, FISSATA PRIMA DI GUARDARE I NUMERI.
Una fonte alternativa A "vale quanto B365" (esito ``EQUIVALENTE``) se, sul
campione comune, valgono TUTTE e tre le condizioni:
  C1  l'IC 95% di Delta LogLoss (A - B365) NON e' tutta > 0 (A non e'
      significativamente peggiore di B365);
  C2  l'IC 95% di Delta hit rate Top Mix (A - B365), APPAIATO sulle partite
      ammesse da ENTRAMBE le fonti, NON e' tutta < 0;
  C3  l'IC 95% dello scarto di calibrazione di A (confidence media - hit rate)
      contiene lo zero.
Se una condizione manca: ``NON EQUIVALENTE``, con i criteri non soddisfatti e la
direzione dello scarto dichiarati dal codice.

Nessuna modifica a ``SoccerMath/``.

Uso: ``python audit/bookmaker_source_test.py [--reps 2000] [--seed 20261008]``
Output: ``audit/output/bookmaker_source_test.json`` (non versionato) e
``audit/results/bookmaker_source_test.md`` (referto).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
from collections import OrderedDict

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

DB_DIR = os.path.join(_REPO_ROOT, "SoccerMath", "database")
DATA_DIR = os.path.join(_AUDIT_DIR, "data", "live_odds_probe")
OUT_DIR = os.path.join(_AUDIT_DIR, "output")
RESULTS_DIR = os.path.join(_AUDIT_DIR, "results")
REPORT_PATH = os.path.join(RESULTS_DIR, "bookmaker_source_test.md")


@contextlib.contextmanager
def _silence_fd2():
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
    import onex2_market_test as O  # PR #49: protocollo riusato, non riscritto
    from backtest_experiment_all import LEAGUES, devig_1x2  # noqa: E402
    from baserate_oos import decomp as murphy_decomp  # noqa: E402
    from team_aliases import clean_name  # noqa: E402

# ---------------------------------------------------------------------------
# Costanti (fissate prima di guardare i numeri)
# ---------------------------------------------------------------------------
EVAL_SEASONS = ("2024/25", "2025/26")
SEASON_FILE = OrderedDict([("2024/25", "2024"), ("2025/26", "2025")])
DEFAULT_REPS = 2000
DEFAULT_SEED = 20261008
BINS = O.BINS                 # 10
TOPMIX_MIN = O.TOPMIX_MIN     # 0.55 (soglia di produzione)
LABELS = O.LABELS             # ("1", "X", "2")
P_CLIP = O.P_CLIP

# singoli bookmaker presenti nelle colonne pre-chiusura dei CSV
BOOKS = OrderedDict([
    ("B365", ("Bet365 (riferimento PR #49)", ("B365H", "B365D", "B365A"))),
    ("BFD", ("Betfred", ("BFDH", "BFDD", "BFDA"))),
    ("BMGM", ("BetMGM", ("BMGMH", "BMGMD", "BMGMA"))),
    ("BV", ("BetVictor", ("BVH", "BVD", "BVA"))),
    ("BW", ("Bet&Win / bwin", ("BWH", "BWD", "BWA"))),
    ("CL", ("Coral", ("CLH", "CLD", "CLA"))),
    ("LB", ("Ladbrokes", ("LBH", "LBD", "LBA"))),
    ("PS", ("Pinnacle", ("PSH", "PSD", "PSA"))),
])
EXCHANGE = OrderedDict([
    ("BFE", ("Betfair Exchange (senza commissione)", ("BFEH", "BFED", "BFEA"))),
])
AGGREGATES = OrderedDict([
    ("Avg", ("Media di mercato (Avg)", ("AvgH", "AvgD", "AvgA"))),
    ("Max", ("Massimo di mercato (Max)", ("MaxH", "MaxD", "MaxA"))),
])
CLOSING = OrderedDict([
    ("B365C", ("Bet365 chiusura (contesto)", ("B365CH", "B365CD", "B365CA"))),
    ("PSC", ("Pinnacle chiusura (contesto)", ("PSCH", "PSCD", "PSCA"))),
])

# colonne lette dai CSV
NEED = ["Date", "HomeTeam", "AwayTeam", "FTR", "FTHG", "FTAG"]
ODDS_COLS = [c for bk in list(BOOKS.values()) + list(EXCHANGE.values()) + list(AGGREGATES.values())
             + list(CLOSING.values()) for c in bk[1]]

# Bookmaker The Odds API (regioni eu,uk) misurati dal probe: serve a dire se un
# book dei CSV e' effettivamente disponibile nella fonte dal vivo candidata.
LIVE_CANONICAL = {
    "B365": ["bet365", "bet365_au"],
    "BFD": ["betfred_uk"],
    "BMGM": ["betmgm", "betmgm_ca_on", "betmgm_se"],
    "BV": ["betvictor"],
    "BW": ["bwin", "betwin"],
    "CL": ["coral"],
    "LB": ["ladbrokes_uk", "ladbrokes_au"],
    "PS": ["pinnacle"],
    "BFE": ["betfair_ex_eu", "betfair_ex_uk", "betfair_ex_au"],
}


# ---------------------------------------------------------------------------
# Caricamento (stessa pulizia di onex2_market_test.load_1x2_odds, piu' colonne)
# ---------------------------------------------------------------------------
def load_odds(prefix: str, league: str) -> pd.DataFrame:
    frames = []
    for season, suffix in SEASON_FILE.items():
        path = os.path.join(DB_DIR, f"{prefix}_{suffix}.csv")
        df = pd.read_csv(path, on_bad_lines="warn", low_memory=False)
        cols = NEED + [c for c in ODDS_COLS if c in df.columns]
        df = df[cols].copy()
        for c in ODDS_COLS:
            if c not in df.columns:
                df[c] = np.nan
        df["season"] = season
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["league"] = league
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    for c in ("FTHG", "FTAG"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTR", "FTHG", "FTAG"])
    df = df.sort_values("Date", kind="stable").reset_index(drop=True)
    df["home"] = df["HomeTeam"].map(clean_name)
    df["away"] = df["AwayTeam"].map(clean_name)
    df = df.drop_duplicates(subset=["league", "season", "home", "away", "Date"],
                            keep="last").reset_index(drop=True)
    df["date_day"] = df["Date"].dt.normalize()
    df["y_code"] = df["FTR"].astype(str).str.strip().str.upper().map({"H": 0, "D": 1, "A": 2})
    df = df[df["y_code"].notna()].reset_index(drop=True)
    df["y_code"] = df["y_code"].astype(int)
    return df


def devig_rows(df: pd.DataFrame, cols) -> np.ndarray:
    """Probabilita' de-vigate (proporzionale) per riga; NaN dove la terna non e' valida."""
    o = df[list(cols)].to_numpy(float)
    out = np.full((len(df), 3), np.nan)
    for i in range(len(df)):
        p = devig_1x2(o[i, 0], o[i, 1], o[i, 2])
        if p is None or p[0] is None:
            continue
        out[i] = p
    return out


def devig_rows_shin(df: pd.DataFrame, cols) -> np.ndarray:
    o = df[list(cols)].to_numpy(float)
    out = np.full((len(df), 3), np.nan)
    for i in range(len(df)):
        p = O.devig_shin3(o[i])
        if p is not None:
            out[i] = p
    return out


def consensus_rows(df: pd.DataFrame, keys) -> tuple:
    """Media delle probabilita' de-vigate dei singoli book validi (>= 3)."""
    probs, valid = [], []
    for k in keys:
        P = devig_rows(df, BOOKS[k][1])
        probs.append(P)
        valid.append(np.isfinite(P).all(axis=1))
    P = np.full((len(df), 3), np.nan)
    V = np.sum(np.array(valid), axis=0)
    acc = np.zeros((len(df), 3))
    for p in probs:
        acc += np.nan_to_num(p, nan=0.0)
    ok = V >= 3
    P[ok] = acc[ok] / V[ok][:, None]
    return P, V


# ---------------------------------------------------------------------------
# Costruzione del frame delle fonti
# ---------------------------------------------------------------------------
def build_frame() -> pd.DataFrame:
    parts = []
    for prefix, league in LEAGUES:
        df = load_odds(prefix, league)
        for k, (_lab, cols) in BOOKS.items():
            df[f"p_{k}"] = list(devig_rows(df, cols))
        for k, (_lab, cols) in list(EXCHANGE.items()) + list(AGGREGATES.items()) + list(CLOSING.items()):
            df[f"p_{k}"] = list(devig_rows(df, cols))
        Pcons, nbooks = consensus_rows(df, list(BOOKS))
        df["p_CONS"] = list(Pcons)
        df["n_libri_consenso"] = nbooks
        # sensibilita' Shin sulle fonti aggregate e su B365
        df["p_B365_shin"] = list(devig_rows_shin(df, BOOKS["B365"][1]))
        df["p_Avg_shin"] = list(devig_rows_shin(df, AGGREGATES["Avg"][1]))
        df["p_PS_shin"] = list(devig_rows_shin(df, BOOKS["PS"][1]))
        df["p_CONS_shin"] = list(devig_rows_shin(df, BOOKS["B365"][1]))  # placeholder, vedi sotto
        # base rate del train (PR #49: stagioni precedenti della lega)
        base = np.full((len(df), 3), np.nan)
        for season in SEASON_FILE:
            m = (df["season"] == season).to_numpy()
            if m.any():
                base[m] = O.train_base_rate(prefix, season)
        df["base"] = list(base)
        parts.append(df)
    d = pd.concat(parts, ignore_index=True)
    # consenso Shin: media delle probabilita' de-vigate con Shin (sensibilita')
    acc, V = np.zeros((len(d), 3)), np.zeros(len(d))
    for k in BOOKS:
        P = devig_rows_shin(d, BOOKS[k][1])
        v = np.isfinite(P).all(axis=1)
        acc += np.nan_to_num(P, nan=0.0)
        V += v
    Pc = np.full((len(d), 3), np.nan)
    ok = V >= 3
    Pc[ok] = acc[ok] / V[ok][:, None]
    d["p_CONS_shin"] = list(Pc)
    return d


SOURCES = OrderedDict([
    ("B365", "Bet365 pre-chiusura (de-vig prop.) — RIFERIMENTO"),
    ("Avg", "Media di mercato Avg (de-vig prop.)"),
    ("Max", "Massimo di mercato Max (de-vig prop.)"),
    ("PS", "Pinnacle (de-vig prop.)"),
    ("CONS", "Consenso: media delle prob. de-vigate dei singoli book"),
    ("BFD", "Betfred (de-vig prop.)"),
    ("BMGM", "BetMGM (de-vig prop.)"),
    ("BV", "BetVictor (de-vig prop.)"),
    ("BW", "Bet&Win / bwin (de-vig prop.)"),
    ("CL", "Coral (de-vig prop.)"),
    ("LB", "Ladbrokes (de-vig prop.)"),
])
SENS_SHIN = OrderedDict([
    ("B365_shin", "Bet365 pre-chiusura (de-vig Shin)"),
    ("Avg_shin", "Media di mercato Avg (de-vig Shin)"),
    ("PS_shin", "Pinnacle (de-vig Shin)"),
    ("CONS_shin", "Consenso (de-vig Shin)"),
])
CONTEXT = OrderedDict([
    ("B365C", "Bet365 chiusura (contesto, de-vig prop.)"),
    ("PSC", "Pinnacle chiusura (contesto, de-vig prop.)"),
    ("BFE", "Betfair Exchange (senza commissione, de-vig prop.)"),
])


def pmat(d, key):
    return np.asarray([np.asarray(p, float) if p is not None else np.full(3, np.nan)
                       for p in d[f"p_{key}"]], float)


def valid_mask(d, key):
    return np.isfinite(pmat(d, key)).all(axis=1)


# ---------------------------------------------------------------------------
# Metriche
# ---------------------------------------------------------------------------
def source_summary(d, key):
    P = pmat(d, key)
    yi = d["y_code"].to_numpy(int)
    B = np.asarray([np.asarray(b, float) for b in d["base"]], float)
    s = O.summary(P, yi, B)
    s["fonte"] = key
    s["n"] = int(np.isfinite(P).all(axis=1).sum())
    return s


def topmix_stats(d, sample, key):
    P = pmat(d, key)
    yi = d["y_code"].to_numpy(int)
    return O.topmix_block(sample, P, yi)


def paired_hitrate(d, sample, a, b):
    """Delta hit rate APPAIATO sulle partite ammesse da ENTRAMBE le fonti."""
    ya = d["y_code"].to_numpy(int)
    ia, ca, ada = O.topmix_pick(pmat(d, a))
    ib, cb, adb = O.topmix_pick(pmat(d, b))
    both = ada & adb
    hit_a = (ia == ya).astype(float)
    hit_b = (ib == ya).astype(float)
    pt, draws = sample.ratio((hit_a - hit_b) * both, both.astype(float))
    return {"n_intersezione": int(both.sum()),
            "delta": pt, "ci": list(O.ci(draws)),
            "n_a": int(ada.sum()), "n_b": int(adb.sum())}


def evaluate_sample(d, keys, reps, seed):
    """Qualita', Top Mix e differenze appaiate contro B365 su un sotto-campione.

    Ogni fonte e' valutata sulle righe in cui e' VALIDA (la copertura non e'
    uguale per tutte: Pinnacle pre-chiusura e Betfair Exchange mancano su parte
    delle partite). I confronti appaiati con B365 usano le righe in cui ENTRAMBE
    le fonti sono valide: il numero di righe del confronto e' riportato.
    """
    quality, topmix, diffs = [], [], {}
    for i, k in enumerate(keys):
        P = pmat(d, k)
        m = np.isfinite(P).all(axis=1)
        dk = d[m].reset_index(drop=True)
        if len(dk) == 0:
            continue
        yi = dk["y_code"].to_numpy(int)
        s = O.summary(pmat(dk, k), yi, np.asarray([np.asarray(b, float) for b in dk["base"]], float))
        quality.append({"fonte": k, "n": int(len(dk)),
                        "logloss": s["logloss"], "brier": s["brier"], "rps": s["rps"],
                        "bss_brier": s.get("bss_brier"), "bss_logloss": s.get("bss_logloss"),
                        "bss_rps": s.get("bss_rps"),
                        "rel": {lab: s[f"rel_{lab}"] for lab in LABELS},
                        "res": {lab: s[f"res_{lab}"] for lab in LABELS}})
        sk = O.Sample(dk, reps, np.random.default_rng(seed + 1000 + i))
        t = O.topmix_block(sk, pmat(dk, k), yi)
        topmix.append({"fonte": k, "n_scelte": t["n"], "pct_righe": t["pct_righe"],
                       "hit": t["hit"], "hit_ci": t["hit_ci"], "conf": t["conf"],
                       "conf_ci": t["conf_ci"], "gap": t["gap"], "gap_ci": t["gap_ci"]})
        if k == "B365":
            continue
        m2 = m & valid_mask(d, "B365")
        if int(m2.sum()) == 0:
            continue
        dab = d[m2].reset_index(drop=True)
        sab = O.Sample(dab, reps, np.random.default_rng(seed + 2000 + i))
        ya = dab["y_code"].to_numpy(int)
        la = O.row_losses(pmat(dab, k), ya)
        lb = O.row_losses(pmat(dab, "B365"), ya)
        res = {}
        for nome, a, b in (("logloss", la[0], lb[0]), ("brier", la[1], lb[1]), ("rps", la[2], lb[2])):
            # Sample.mean_diff restituisce gia' (punto, IC bootstrap)
            res[nome] = sab.mean_diff(a, b)
        diffs[k] = {"n_confronto": int(len(dab)),
                    "delta_logloss": res["logloss"][0], "ci_logloss": list(res["logloss"][1]),
                    "delta_brier": res["brier"][0], "ci_brier": list(res["brier"][1]),
                    "delta_rps": res["rps"][0], "ci_rps": list(res["rps"][1]),
                    "hit_appaiato": paired_hitrate(dab, sab, k, "B365"),
                    "resolution": O.resolution_diff(sab, pmat(dab, k), pmat(dab, "B365"),
                                                    ya, reps, seed + 3000 + i)}
    return {"quality": quality, "topmix": topmix, "diffs": diffs}


def verdicts(payload_common, eps=1e-6):
    """Applica la regola fissata prima dei numeri (C1, C2, C3)."""
    topmix = {t["fonte"]: t for t in payload_common["topmix"]}
    diffs = payload_common["diffs"]
    out = {}
    for k, dd in diffs.items():
        lo_ll, hi_ll = dd["ci_logloss"]
        lo_h, hi_h = dd["hit_appaiato"]["ci"]
        tm = topmix[k]
        lo_g, hi_g = tm["gap_ci"]
        c1 = not (lo_ll > eps)                 # non significativamente peggiore
        c2 = not (hi_h < -eps)                 # hit rate appaiato non peggiore
        c3 = (lo_g - eps) <= 0 <= (hi_g + eps)  # scarto di calibrazione ~ zero
        motivi = []
        if not c1:
            motivi.append(f"C1 non soddisfatto: Delta LogLoss {dd['delta_logloss']:+.4f} "
                          f"IC [{lo_ll:+.4f}; {hi_ll:+.4f}] (tutta > 0: peggiore)")
        if not c2:
            motivi.append(f"C2 non soddisfatto: Delta hit rate appaiato "
                          f"{dd['hit_appaiato']['delta']:+.4f} IC [{lo_h:+.4f}; {hi_h:+.4f}] "
                          f"(tutta < 0: peggiore)")
        if not c3:
            motivi.append(f"C3 non soddisfatto: scarto di calibrazione {tm['gap']:+.4f} "
                          f"IC [{lo_g:+.4f}; {hi_g:+.4f}] (non contiene lo zero)")
        out[k] = {"esito": "EQUIVALENTE" if (c1 and c2 and c3) else "NON EQUIVALENTE",
                  "c1": c1, "c2": c2, "c3": c3, "motivi": motivi}
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def live_availability():
    """Bookmaker misurati dal probe (The Odds API, regioni eu+uk), se presente."""
    path = os.path.join(DATA_DIR, "probe_summary.json")
    if not os.path.exists(path):
        return {"disponibile": False, "per_libro": {}}
    with open(path, encoding="utf-8") as fh:
        s = json.load(fh)
    books = set()
    for lg, v in s.get("odds_api", {}).get("leagues", {}).items():
        books |= set(v.get("bookmakers") or [])
    per = {}
    for csv_key, api_keys in LIVE_CANONICAL.items():
        found = sorted(b for b in books if b in api_keys)
        per[csv_key] = {"chiavi_api": api_keys, "trovato": found, "disponibile": bool(found)}
    return {"disponibile": True, "snapshot": s.get("generato_il"),
            "tutti_i_book_misurati": sorted(books), "per_libro": per}


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |")
    return "\n".join(out)


def f(x, nd=4):
    return O.fmt(x, nd)


def fci(pt, ci_, nd=4):
    return O.fci(pt, ci_, nd)


def build_report(payload):
    P = payload
    L = []
    A = L.append
    A("# Quale bookmaker basta? — referto di audit (sola lettura)\n")
    A(f"Generato da `audit/bookmaker_source_test.py` (nessuna modifica a `SoccerMath/`). "
      f"Base: `{P['base_commit']}` su branch `{P['branch']}`. "
      f"Bootstrap: {P['reps']} repliche a blocchi (lega × stagione × giornata), seme {P['seed']}. "
      f"Tempo: {P['secondi']} s. Comando: `python audit/bookmaker_source_test.py`.\n")
    A("Protocollo: identico alla PR #49 (`audit/onex2_market_test.py`), di cui si riusano "
      "de-vig, metriche, base rate del train, regola Top Mix (>= 0,55) e bootstrap a blocchi. "
      "Stagioni valutate: 2024/25 e 2025/26.\n")

    A("## 1. Copertura delle colonne (righe con terna valida)\n")
    rows = []
    for r in P["copertura"]:
        rows.append([r["lega"], r["stagione"], r["righe"]] +
                    [r["fonti"].get(k, 0) for k in P["copertura_fonti"]])
    A(md_table(["Lega", "Stagione", "Righe"] + P["copertura_fonti"], rows))
    A("")
    A("| Campione | Righe |")
    A("|---|---|")
    for k, v in P["campioni"].items():
        A(f"| {k} | {v} |")
    A("")

    A("## 2. Qualita' delle probabilita' (campione comune)\n")
    A("LogLoss / Brier / RPS piu' bassi = meglio; BSS e resolution piu' alti = meglio. "
      "Reliability/resolution per esito con 10 bin, base rate del train come PR #34.\n")
    rows = []
    for q in P["comune"]["quality"]:
        rows.append([P["etichette"][q["fonte"]], q["n"], f(q["logloss"]), f(q["brier"]),
                     f(q["rps"]), f(q["bss_brier"]), f(q["bss_logloss"]), f(q["bss_rps"]),
                     " ; ".join(f"{lab}: {f(q['rel'][lab])}/{f(q['res'][lab])}" for lab in LABELS)])
    A(md_table(["Fonte", "n", "LogLoss", "Brier", "RPS", "BSS Brier", "BSS LogLoss",
                "BSS RPS", "rel/res per esito"], rows))
    A("")

    A("### 2b. Campione Pinnacle (dove la terna PS pre-chiusura e' valida)\n")
    rows = []
    for q in P["pinnacle"]["quality"]:
        rows.append([P["etichette"][q["fonte"]], q["n"], f(q["logloss"]), f(q["brier"]),
                     f(q["rps"]), f(q["bss_logloss"])])
    A(md_table(["Fonte", "n", "LogLoss", "Brier", "RPS", "BSS LogLoss"], rows))
    A("")

    A("## 3. Scelte Top Mix (esito piu' probabile se >= 0,55)\n")
    rows = []
    for t in P["comune"]["topmix"]:
        rows.append([P["etichette"][t["fonte"]], t["n_scelte"],
                     f"{100 * t['pct_righe']:.1f}%",
                     fci(t["hit"], t["hit_ci"]), fci(t["conf"], t["conf_ci"]),
                     fci(t["gap"], t["gap_ci"])])
    A(md_table(["Fonte", "Scelte", "% righe ammesse", "Hit rate [IC]",
                "Confidence media [IC]", "Confidence − hit rate [IC]"], rows))
    A("")

    A("## 4. Differenze appaiate contro Bet365 (A − B365), IC 95% bootstrap\n")
    A("Delta negativo su LogLoss/Brier/RPS = A migliore di B365. "
      "L'hit rate e' appaiato sulle partite ammesse da ENTRAMBE le fonti.\n")
    rows = []
    for k, d in P["comune"]["diffs"].items():
        rows.append([P["etichette"][k], fci(d["delta_logloss"], d["ci_logloss"]),
                     fci(d["delta_brier"], d["ci_brier"]), fci(d["delta_rps"], d["ci_rps"]),
                     f"{d['hit_appaiato']['delta']:+.4f} "
                     f"[{d['hit_appaiato']['ci'][0]:+.4f}; {d['hit_appaiato']['ci'][1]:+.4f}] "
                     f"(n={d['hit_appaiato']['n_intersezione']})"])
    A(md_table(["Fonte (A)", "Δ LogLoss", "Δ Brier", "Δ RPS", "Δ hit rate appaiato (n)"], rows))
    A("")

    A("## 5. Verdetti (regola fissata prima dei numeri: C1 e C2 e C3)\n")
    A("C1 = Δ LogLoss non significativamente peggiore; C2 = Δ hit rate appaiato non "
      "peggiore; C3 = scarto di calibrazione con IC che contiene lo zero.\n")
    rows = []
    for k, v in P["verdetti"].items():
        rows.append([P["etichette"][k], v["esito"],
                     "sì" if v["c1"] else "NO", "sì" if v["c2"] else "NO",
                     "sì" if v["c3"] else "NO"])
    A(md_table(["Fonte", "Esito", "C1", "C2", "C3"], rows))
    A("")
    if P["motivi"]:
        A("**Motivi per cui i verdetti non scattano (generati dai numeri):**\n")
        for m in P["motivi"]:
            A(f"- {m}")
        A("")

    A("## 6. Disponibilita' dei book dei CSV nella fonte dal vivo candidata\n")
    liv = P["live_availability"]
    if not liv["disponibile"]:
        A("Snapshot del probe non disponibile: voce NON VERIFICABILE.\n")
    else:
        A(f"Bookmaker misurati da The Odds API (regioni eu,uk, snapshot {liv['snapshot']}) "
          f"sulle 5 leghe: {len(liv['tutti_i_book_misurati'])}. "
          "La colonna 'disponibile live' dice se lo stesso book e' tornato nelle risposte reali.\n")
        rows = []
        for k, v in liv["per_libro"].items():
            rows.append([k, P["etichette"].get(k, BOOKS.get(k, ("", ))[0] if k in BOOKS else k),
                         "sì" if v["disponibile"] else "NO",
                         ", ".join(v["trovato"]) or "—"])
        A(md_table(["Colonna CSV", "Bookmaker", "Disponibile live (misurato)",
                    "Chiavi API trovate"], rows))
        A("")

    A("## 7. Limiti dichiarati\n")
    for lim in P["limiti"]:
        A(f"- {lim}")
    A("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
def build_payload(reps=DEFAULT_REPS, seed=DEFAULT_SEED):
    import time
    t0 = time.time()
    rng = np.random.default_rng(seed)
    d = build_frame()
    # campione comune: B365 pre + Avg + Max validi (il minimo comune denominatore
    # delle fonti aggregate); campione Pinnacle: comune + PS pre valido
    mask_comune = valid_mask(d, "B365") & valid_mask(d, "Avg") & valid_mask(d, "Max")
    mask_ps = mask_comune & valid_mask(d, "PS")
    keys = list(SOURCES) + list(SENS_SHIN) + list(CONTEXT)
    etichette = dict(SOURCES)
    etichette.update(SENS_SHIN)
    etichette.update(CONTEXT)
    etichette["B365_shin"] = SENS_SHIN["B365_shin"]

    dc = d[mask_comune].reset_index(drop=True)
    dp = d[mask_ps].reset_index(drop=True)
    comune = evaluate_sample(dc, keys, reps, seed)
    pinnacle = evaluate_sample(dp, keys, reps, seed)

    copertura = []
    for (lega, stagione), g in d.groupby(["league", "season"], sort=False):
        rec = {"lega": lega, "stagione": stagione, "righe": int(len(g)), "fonti": {}}
        for k in keys:
            rec["fonti"][k] = int(valid_mask(g, k).sum())
        copertura.append(rec)

    verdetti = verdicts(comune)
    motivi = [m for v in verdetti.values() for m in v["motivi"]]

    def git(*cmd):
        try:
            return subprocess.run(cmd, cwd=_REPO_ROOT, capture_output=True, text=True,
                                  timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return "n/d"

    payload = {
        "generato_il": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base_commit": git("git", "rev-parse", "HEAD"),
        "branch": git("git", "rev-parse", "--abbrev-ref", "HEAD"),
        "reps": reps, "seed": seed,
        "secondi": round(time.time() - t0, 1),
        "etichette": etichette,
        "copertura": copertura,
        "copertura_fonti": keys,
        "campioni": {"comune (B365+Avg+Max validi)": int(mask_comune.sum()),
                     "di cui con Pinnacle pre valido": int(mask_ps.sum()),
                     "righe totali delle due stagioni": int(len(d))},
        "comune": comune,
        "pinnacle": pinnacle,
        "verdetti": verdetti,
        "motivi": motivi,
        "live_availability": live_availability(),
        "limiti": [
            "Le colonne pre-chiusura sono quelle dichiarate dalla commessa: il CSV non "
            "contiene l'orario di rilevazione della quota.",
            "Avg e Max sono aggregati di mercato calcolati dalla fonte (Betbrain/Oddsportal): "
            "la composizione del paniere non e' nel CSV e puo' cambiare nel tempo.",
            "Il de-vig proporzionale e' la decisione (come PR #49); lo Shin e' sensibilita'. "
            "Sulle quote dello scambio (BFE) il de-vig non tiene conto della commissione.",
            "Il campione Pinnacle e' un sottoinsieme (PS pre mancante su parte delle partite "
            "2025/26): i valori non sono confrontabili riga per riga con il campione comune.",
            "Il bootstrap a blocchi tratta le giornate come unita'; giornate della stessa lega "
            "condividono le squadre e non sono indipendenti oltre il blocco.",
            "La disponibilita' live dei book e' MISURATA su uno snapshot del probe "
            "(The Odds API, regioni eu e uk): puo' cambiare senza preavviso.",
        ],
    }
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description="Confronto fra bookmaker sull'1X2 (sola lettura)")
    ap.add_argument("--reps", type=int, default=DEFAULT_REPS)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", default=OUT_DIR)
    args = ap.parse_args(argv)

    payload = build_payload(reps=args.reps, seed=args.seed)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "bookmaker_source_test.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    md = build_report(payload)
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(f"referto: {REPORT_PATH}")
    print(f"json:    {os.path.join(args.out, 'bookmaker_source_test.json')}")
    print(f"secondi: {payload['secondi']}")
    for k, v in payload["verdetti"].items():
        print(f"  {k}: {v['esito']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
