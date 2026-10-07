#!/usr/bin/env python3
"""totals_market_ceiling.py — Capacita' predittiva dei Totali: modello contro mercato.

DOMANDA. Quanto margine pratico resta alla testa Totali (O/U 2.5 e GG/NG) sui dati
nuovi, cioe' quanto dista la capacita' predittiva del modello da quella del mercato
(apertura e chiusura)? Solo audit: NESSUNA modifica a ``SoccerMath/``.

CHE COSA FA (punti 1-6 della commessa)

1. Modello. Le probabilita' point-in-time dei Totali sono quelle GIA' prodotte dai
   banchi esistenti, importate e non riscritte:
     * testa Totali di PRODUZIONE (``ppda_residual_test.production_totali``): il banco
       usato dai test sul residuo (PPDA, tiri, PR #39) — P(Under 2.5) = ``engine_u25``
       (quindi P(Over 2.5) = 1 - engine_u25), P(GG) = ``engine_gg``, lambda totale =
       ``lambda_total``. Questa e' la colonna PRIMARIA;
     * banco walk-forward ``backtest_experiment_all.run_walkforward`` (colonne
       ``poisson_o25``/``poisson_gg`` del referto PR #34 ``ev_and_baserate_fix.md``).
       SECONDA colonna, riportata per intero: la commessa cita entrambi i precedenti e
       i due NON sono lo stesso codice.
   Per GG/NG il modello di produzione viene anche ricalcolato dall'altro banco
   (``gg_ng_calibration.walk_forward_gg_predictions``) e incrociato riga per riga con
   ``production_totali``: lo scarto massimo finisce nel referto.

2. Mercato.
   * Over/Under 2.5 dai CSV football-data: apertura ``B365>2.5``/``B365<2.5``,
     chiusura ``B365C>2.5``/``B365C<2.5`` e ``PC>2.5``/``PC<2.5`` (Pinnacle) dove
     presenti. Copertura riportata per lega, stagione e colonna.
   * GG/NG da ``audit/data/*_btts.json`` (Oddsportal: un solo snapshot per partita,
     nessuna apertura/chiusura, nessun Pinnacle).
   * De-vig PROPORZIONALE (decisione) e SHIN, entrambi riportati.

3. Valutazione su 2024/25 e 2025/26, solo sulle partite in cui modello E quota sono
   entrambi disponibili. Base rate di riferimento = quello del TRAIN come nella
   PR #34 (``baserate_oos.raw``: tutte le stagioni precedenti a quella valutata).

4. Metriche per mercato e per fonte: Brier, LogLoss, scomposizione di Murphy
   (reliability / resolution / uncertainty, 10 bin come ``baserate_oos.decomp``),
   Brier Skill Score contro il base rate del train. Differenze appaiate di resolution
   e LogLoss mercato-contro-modello con bootstrap a blocchi (lega x stagione x
   giornata = data, come nei banchi esistenti), 2000 repliche, IC 95%, pooled e per
   lega. Piu' la differenza chiusura-contro-apertura (stessa fonte, B365) che misura
   il valore delle informazioni dell'ultima settimana.

5. Dispersione dei lambda implicata dal mercato: la P(Over 2.5) de-vigata di chiusura
   viene invertita in un lambda totale Poisson (la somma di due Poisson indipendenti
   e' Poisson, quindi l'inversione e' esatta); media e deviazione standard di
   log lambda per lega, confrontate con il lambda totale del modello.

6. Il modello aggiunge qualcosa al mercato? Regressione logistica (encompassing)
   dell'esito su logit(p_modello) e logit(p_mercato di chiusura), stimata in
   rolling-origin (2023/24 -> 2024/25; 2023/24+2024/25 -> 2025/26), con DeltaLogLoss
   fuori campione della combinazione contro il solo mercato.

LETTURA (fissata a priori, applicata meccanicamente dal codice)
  TETTO RAGGIUNTO   se resolution(chiusura) - resolution(modello) < 0.002 (pooled)
                    oppure se l'IC 95% della differenza include lo zero;
  MARGINE ESISTENTE se la differenza e' >= 0.002 con IC che esclude lo zero; in quel
                    caso si riporta quanta parte del margine c'e' gia' in apertura e
                    quanta compare solo in chiusura.
Verdetto separato per O/U 2.5 e GG/NG.

Output
  * ``audit/results/totals_market_ceiling.md``      referto (generato);
  * ``audit/output/totals_market_ceiling.json``     payload completo (non versionato);
  * ``audit/output/totals_market_ceiling_rows.csv`` righe partita per partita (non
    versionato).

Uso: ``python audit/totals_market_ceiling.py [--reps 2000] [--seed 20261007]``
     (lo script si sposta da solo alla radice del repo: ``baserate_oos.raw`` legge
     percorsi relativi).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone

import contextlib  # noqa: E402

import streamlit.logger as _st_logger  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import statsmodels.api as sm  # noqa: E402

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

@contextlib.contextmanager
def _silence_fd2():
    """Silenzia il rumore di Streamlit durante l'import dei banchi.

    ``app`` (importato da ``ppda_residual_test``/``gg_ng_calibration``) chiama API
    Streamlit a livello di modulo e, senza sessione, emette decine di warning su
    stderr con un handler gia' costruito: alzare il livello del logger non basta
    (config lo riabbassa). Si devia il DESCRITTORE 2, cosi' qualunque handler che
    scriva su stderr resta zitto per la durata dell'import.
    """
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
    from backtest_experiment_all import (  # noqa: E402
        LEAGUES, load_league, run_walkforward, run_market_value_old, devig_2way,
    )
    from baserate_oos import raw as train_base_rate  # noqa: E402  (convenzione PR #34)
    from baserate_oos import decomp as murphy_decomp  # noqa: E402  (scomposizione PR #34)
    from ppda_residual_test import production_totali  # noqa: E402  (banco PR #33/#39)
    import gg_ng_calibration as ggn  # noqa: E402  (banco GG/NG con quote Oddsportal)
    import app as prod_app  # noqa: E402  (solo lettura: funzioni di produzione)
    from xg_archive import load_archive, season_point_in_time_averages  # noqa: E402

_st_logger.set_log_level("CRITICAL")   # resta zitto anche dopo l'import

OUT_DIR = os.path.join(_AUDIT_DIR, "output")
RESULTS_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_MD = os.path.join(RESULTS_DIR, "totals_market_ceiling.md")
OUT_JSON = os.path.join(OUT_DIR, "totals_market_ceiling.json")
OUT_ROWS = os.path.join(OUT_DIR, "totals_market_ceiling_rows.csv")

# ---------------------------------------------------------------------------
# Costanti fissate PRIMA di guardare i numeri
# ---------------------------------------------------------------------------
MARKETS = ("OU2.5", "GG/NG")
EVAL_SEASONS = ("2024/25", "2025/26")
FOLDS = (
    {"estimate": ("2023/24",), "evaluate": "2024/25"},
    {"estimate": ("2023/24", "2024/25"), "evaluate": "2025/26"},
)
BINS = 10                       # bin di Murphy, come baserate_oos.decomp (PR #34)
DEFAULT_REPS = 2000
DEFAULT_SEED = 20261007         # stesso seme del test tiri (PR #39)
CEILING_EPS = 0.002             # soglia di lettura fissata dalla commessa
LAMBDA_LO, LAMBDA_HI = 1e-3, 20.0855   # range di clip di produzione [exp(-6), exp(3)]
P_CLIP = 1e-9

OU_ODDS_COLS = ["B365>2.5", "B365<2.5", "B365C>2.5", "B365C<2.5", "PC>2.5", "PC<2.5"]
OU_SOURCES = OrderedDict([
    ("apertura_b365", ("B365>2.5", "B365<2.5")),
    ("chiusura_b365", ("B365C>2.5", "B365C<2.5")),
    ("chiusura_pinnacle", ("PC>2.5", "PC<2.5")),
])
SOURCES = tuple(OU_SOURCES)
# etichette delle fonti di mercato che entrano nel verdetto (chiusura)
VERDICT_MARKET_TOKENS = {"OU2.5": ("mercato_chiusura_b365", "mercato_chiusura_pinnacle"),
                         "GG/NG": ("mercato_gg_oddsportal",)}
# etichette delle fonti di MERCATO (chiusura) usate nei verdetti


# ---------------------------------------------------------------------------
# De-vig
# ---------------------------------------------------------------------------
def devig_prop(o_a: float, o_b: float):
    """Proporzionale: helper di produzione riusato (``devig_2way``).

    ``devig_2way`` ritorna ``(None, None)`` sui mercati non utilizzabili: qui il
    caso diventa un NaN esplicito, mai un'imputazione.
    """
    p = devig_2way(o_a, o_b)
    if p is None or p[0] is None:
        return None
    return float(p[0])


def devig_shin(o_a: float, o_b: float):
    """Shin (1993) a due esiti.

    ``p_i(z) = (sqrt(z^2 + 4(1-z) pi_i^2 / B) - z) / (2(1-z))`` con ``pi_i = 1/o_i``
    e ``B = sum pi_i``; ``z`` (quota di informati) si risolve imponendo ``sum p_i = 1``
    per bisezione. Ritorna ``(p_a, z)`` o ``None`` se il mercato non e' utilizzabile.
    """
    try:
        o_a, o_b = float(o_a), float(o_b)
    except (TypeError, ValueError):
        return None
    if not (np.isfinite(o_a) and np.isfinite(o_b)) or o_a <= 1.0 or o_b <= 1.0:
        return None
    pi = np.array([1.0 / o_a, 1.0 / o_b])
    B = float(pi.sum())

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
    z = 0.5 * (lo + hi)
    p = probs(z)
    if not np.all(np.isfinite(p)) or p.sum() <= 0:
        return None
    p = p / p.sum()
    return float(p[0]), float(z)


# ---------------------------------------------------------------------------
# Poisson: P(Under 2.5) di un lambda totale e inversione
# ---------------------------------------------------------------------------
def under25_of_lambda(lam):
    lam = np.asarray(lam, dtype=float)
    return np.exp(-lam) * (1.0 + lam + lam * lam / 2.0)


def lambda_from_under25(p_under):
    """Inversione esatta e monotona di ``under25_of_lambda`` (bisezione vettorizzata)."""
    p = np.clip(np.asarray(p_under, dtype=float), 1e-15, 1 - 1e-15)
    lo = np.full(p.shape, LAMBDA_LO)
    hi = np.full(p.shape, LAMBDA_HI)
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        too_low = under25_of_lambda(mid) > p
        lo = np.where(too_low, mid, lo)
        hi = np.where(too_low, hi, mid)
    return 0.5 * (lo + hi)


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), P_CLIP, 1 - P_CLIP)
    return np.log(p / (1.0 - p))


def brier(y, p) -> float:
    y = np.asarray(y, float)
    p = np.clip(np.asarray(p, float), P_CLIP, 1 - P_CLIP)
    return float(np.mean((y - p) ** 2))


def logloss(y, p) -> float:
    y = np.asarray(y, float)
    p = np.clip(np.asarray(p, float), P_CLIP, 1 - P_CLIP)
    return float(np.mean(-(y * np.log(p) + (1 - y) * np.log(1 - p))))


# ---------------------------------------------------------------------------
# Dati: quote Over/Under 2.5 dai CSV football-data
# ---------------------------------------------------------------------------
_CLEAN_CACHE: dict = {}


def clean_name_cached(name):
    if name not in _CLEAN_CACHE:
        from config import clean_name
        _CLEAN_CACHE[name] = clean_name(name)
    return _CLEAN_CACHE[name]


def load_ou_odds(prefix: str) -> pd.DataFrame:
    """Quote Over/Under 2.5 per lega, con la STESSA pulizia di ``load_league``.

    ``load_league`` non carica le colonne di chiusura (``ODDS_COLS`` si ferma ad
    ``Avg<2.5``): le rilegge qui applicando gli stessi passi (data ``dayfirst``, nomi
    puliti, ordinamento per data, ``drop_duplicates`` su (Date, HomeClean, AwayClean)
    con keep="last").
    """
    files = OrderedDict([
        ("2022/23", f"{prefix}_2022.csv"), ("2023/24", f"{prefix}_2023.csv"),
        ("2024/25", f"{prefix}_2024.csv"), ("2025/26", f"{prefix}_2025.csv"),
        ("2026/27", f"{prefix}_Live.csv"),
    ])
    db = os.path.join(_REPO_ROOT, "SoccerMath", "database")
    frames = []
    for season, fname in files.items():
        df = pd.read_csv(os.path.join(db, fname), on_bad_lines="warn", low_memory=False)
        for c in OU_ODDS_COLS:
            if c not in df.columns:
                df[c] = np.nan
        df = df[["Date", "HomeTeam", "AwayTeam"] + OU_ODDS_COLS].copy()
        df["season"] = season
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out["Date"] = pd.to_datetime(out["Date"], dayfirst=True, errors="coerce")
    out["HomeClean"] = out["HomeTeam"].apply(clean_name_cached)
    out["AwayClean"] = out["AwayTeam"].apply(clean_name_cached)
    out = out.dropna(subset=["Date", "HomeTeam", "AwayTeam"])
    out = out.sort_values("Date", kind="stable").reset_index(drop=True)
    out = out.drop_duplicates(subset=["Date", "HomeClean", "AwayClean"],
                              keep="last").reset_index(drop=True)
    return out


def coverage_ou(prefix: str) -> pd.DataFrame:
    d = load_ou_odds(prefix)
    rows = []
    for season, g in d.groupby("season", sort=False):
        rec = {"season": season, "rows": int(len(g))}
        for c in OU_ODDS_COLS:
            rec[f"nn__{c}"] = int(g[c].notna().sum())
        for name, (oc, uc) in OU_SOURCES.items():
            ok = g[oc].notna() & g[uc].notna() & g[oc].gt(1.0) & g[uc].gt(1.0)
            rec[f"coppia__{name}"] = int(ok.sum())
            rec[f"overround_medio__{name}"] = float(
                (1.0 / g.loc[ok, oc] + 1.0 / g.loc[ok, uc]).mean()) if ok.any() else None
        rows.append(rec)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Dati: modello (produzione + banco PR #34) e mercato, per i due mercati
# ---------------------------------------------------------------------------
def build_ou_frame():
    """Una riga per partita: modello (produzione e banco) + quote O/U 2.5."""
    frames, diag = [], {}
    for prefix, league in LEAGUES:
        df = load_league(prefix)
        bench = run_walkforward(df, camp_key=league)
        bench_var = run_market_value_old(df, camp_key=league)   # train = sola 2022/23
        prod = production_totali(prefix, league)
        odds = load_ou_odds(prefix)

        keys = ["season", "date", "home", "away"]
        b = bench[keys + ["poisson_o25", "poisson_gg", "real_uo", "real_gg"]].copy()
        bv = bench_var[keys + ["poisson_o25", "poisson_gg"]].rename(
            columns={"poisson_o25": "benchvar_o25", "poisson_gg": "benchvar_gg"})
        p = prod[["season", "date", "home", "away", "engine_u25", "engine_gg",
                  "lambda_total", "n_seen"]].copy()
        o = odds.rename(columns={"Date": "date", "HomeClean": "home",
                                 "AwayClean": "away"})[
            ["season", "date", "home", "away"] + OU_ODDS_COLS]
        m = df[["season", "Date", "HomeClean", "AwayClean", "FTHG", "FTAG"]].rename(
            columns={"Date": "date", "HomeClean": "home", "AwayClean": "away"})
        m["y_over"] = (m.FTHG + m.FTAG > 2.5).astype(int)
        m["y_gg"] = ((m.FTHG > 0) & (m.FTAG > 0)).astype(int)

        merged = (m.merge(b, on=keys, how="left", validate="one_to_one")
                   .merge(bv, on=keys, how="left", validate="one_to_one")
                   .merge(p, on=keys, how="left", validate="one_to_one")
                   .merge(o, on=keys, how="left", validate="one_to_one"))
        assert len(merged) == len(m), (prefix, len(merged), len(m))
        # il banco copre solo le partite successive al suo train (2024/25 in poi):
        # lo scarto contro l'esito ricalcolato dai gol si misura dove il banco esiste
        has_bench = merged["real_uo"].notna()
        diag[league] = {
            "righe_lega": int(len(m)),
            "righe_banco_PR34": int(has_bench.sum()),
            "senza_colonna_chiusura_b365": int(merged["B365C>2.5"].isna().sum()),
            "scarto_bench_vs_esito_ou": int((merged.loc[has_bench, "real_uo"].eq("OVER")
                                             .astype(int)
                                             != m.loc[has_bench, "y_over"]).sum()),
            "scarto_bench_vs_esito_gg": int((merged.loc[has_bench, "real_gg"].eq("GG")
                                             .astype(int)
                                             != m.loc[has_bench, "y_gg"]).sum()),
        }
        merged["league"] = league
        frames.append(merged)
    out = pd.concat(frames, ignore_index=True)
    out["date_day"] = pd.to_datetime(out["date"]).dt.normalize()

    for name, (oc, uc) in OU_SOURCES.items():
        out[f"p__{name}"] = [devig_prop(a, b_) if pd.notna(a) and pd.notna(b_) else np.nan
                             for a, b_ in zip(out[oc], out[uc])]
        shin = [devig_shin(a, b_) if pd.notna(a) and pd.notna(b_) else None
                for a, b_ in zip(out[oc], out[uc])]
        out[f"shin__{name}"] = [s[0] if s else np.nan for s in shin]
        out[f"zshin__{name}"] = [s[1] if s else np.nan for s in shin]

    out["p_model_prod"] = 1.0 - out["engine_u25"]
    out["p_model_bench"] = out["poisson_o25"]
    out["p_model_benchvar"] = out["benchvar_o25"]
    out["p_model_prod_gg"] = out["engine_gg"]
    out["p_model_bench_gg"] = out["poisson_gg"]
    out["p_model_benchvar_gg"] = out["benchvar_gg"]
    return out, diag


def fs_season_probe(prefix: str, league: str) -> dict:
    """Misura su quali (stagione, giornata) la fonte F_season NON e' attiva.

    Serve a un fatto verificato nel codice: quando l'ancora di lega degli xG della
    stagione in corso manca (`fs_active = False`, ``app.get_league_engine``), la
    produzione usa ``att0_pure/def0_pure = att/def`` (testa 1X2 con forma e
    fattore mercato), mentre ``ppda_residual_test.production_totali`` usa il
    fallback gol e ``gg_ng_calibration.walk_forward_gg_predictions`` usa
    ``att/def`` come la produzione. Su quelle righe i due banchi divergono: qui si
    contano, e le metriche vengono ricalcolate anche senza.
    """
    df = load_league(prefix)
    records = load_archive(league)
    pairs = df[["season", "Date"]].drop_duplicates()
    inactive, checked = [], 0
    for season, date in zip(pairs["season"], pairs["Date"]):
        agg = season_point_in_time_averages(
            league, cutoff=date.to_pydatetime(), season=int(season.split("/")[0]),
            records=records)
        anchor_xg, anchor_xga = prod_app._league_mean_gate(agg.averages)
        checked += 1
        if anchor_xg is None or anchor_xga is None:
            inactive.append((season, str(date.date())))
    return {"coppie_stagione_data_esaminate": checked,
            "coppie_fs_non_attiva": len(inactive),
            "date_fs_non_attiva": sorted(inactive)}


def build_gg_frame(ou: pd.DataFrame):
    """Righe con quota BTTS Oddsportal incrociata (2023/24..2025/26).

    Riusa il banco ``gg_ng_calibration`` (join deterministico + walk-forward di
    produzione): la copertura e' quella del referto ``gg_ng_calibration.md``. Le
    colonne del modello O/U e di ``production_totali`` vengono agganciate dalla
    cornice O/U (stessa chiave lega-stagione-data-squadre).
    """
    dataset = ggn.load_btts_dataset()
    frames, diag = [], {}
    for slug, (prefix, league_key, league_name) in ggn.BTTS_FILES.items():
        df = load_league(prefix)
        records = load_archive(league_key)
        rows = []
        per_file = OrderedDict()
        for season in ("2023-2024", "2024-2025", "2025-2026"):
            json_rows = dataset.get((slug, season))
            if json_rows is None:
                continue
            season_label = ggn.season_label_of(season)
            mask = (df["season"] == season_label).to_numpy()
            pos_map = list(np.flatnonzero(mask))
            season_df = df[mask].reset_index(drop=True)
            recs = ggn.join_btts_file(json_rows, season_df)
            joined = [r for r in recs if r["status"] == ggn.JOIN_OK]
            per_file[season_label] = {
                "righe_json": int(len(json_rows)), "incrociate": int(len(joined)),
                "senza_quota": int(sum(1 for r in recs if r["status"] == "odds_missing")),
                "coppia_assente": int(sum(1 for r in recs if r["status"] == "pair_absent")),
                "data_in_conflitto": int(sum(1 for r in recs if r["status"] == "date_mismatch")),
                "dup_non_risolti": int(sum(1 for r in recs
                                           if r["status"] == "duplicate_not_resolved")),
                "senza_risultato": int(sum(1 for r in recs if r["status"] == "no_score")),
                "bet365": int(sum(1 for r in joined if not r["bookmaker_fallback"])),
                "fallback": int(sum(1 for r in joined if r["bookmaker_fallback"])),
                "overround_medio": float(np.mean([1.0 / r["o_yes"] + 1.0 / r["o_no"]
                                                  for r in joined])) if joined else None,
            }
            for r in joined:
                rows.append((season_label, pos_map[r["csv_pos"]], r))

        targets = {pos for _, pos, _ in rows}
        preds, wdiag = ggn.walk_forward_gg_predictions(df, league_key, targets, records)
        per_file["walk_forward"] = {"targets": int(len(targets)),
                                    "fs_inactive_rows": int(wdiag["fs_inactive_rows"]),
                                    "rows_seen": int(wdiag["rows_seen"])}
        diag[league_name] = per_file

        recs = []
        for season_label, pos, r in rows:
            crow = df.iloc[pos]
            o_yes, o_no = float(r["o_yes"]), float(r["o_no"])
            shin = devig_shin(o_yes, o_no)
            recs.append({
                "league": league_name, "season": season_label,
                "date": pd.Timestamp(r["csv_date"]), "home": crow.HomeClean,
                "away": crow.AwayClean, "bookmaker": r["bookmaker"],
                "fallback": bool(r["bookmaker_fallback"]), "o_yes": o_yes, "o_no": o_no,
                "p_market_gg": float(r["p_fair_gg"]),
                "p_market_gg_shin": shin[0] if shin else np.nan,
                "zshin_gg": shin[1] if shin else np.nan,
                "p_model_prod_ggwalk": float(preds[pos]),
                "home_key_gg": r["home_key"], "away_key_gg": r["away_key"],
                "y_gg": int(crow.FTHG > 0 and crow.FTAG > 0),
            })
        frames.append(pd.DataFrame(recs))
    out = pd.concat(frames, ignore_index=True)
    out["date_day"] = pd.to_datetime(out["date"]).dt.normalize()

    merged = out.merge(
        ou[["league", "season", "date", "home", "away", "engine_gg", "p_model_prod",
            "lambda_total", "p_model_bench_gg", "p_model_benchvar_gg", "y_gg"]],
        on=["league", "season", "date", "home", "away"], how="left",
        validate="one_to_one", suffixes=("", "_ou"))
    agg_diag = {}
    for league, g in merged.groupby("league"):
        diff = (g["engine_gg"] - g["p_model_prod_ggwalk"]).abs()
        agg_diag[league] = {
            "righe_senza_aggancio_modello": int(g["engine_gg"].isna().sum()),
            "scarto_engine_gg_vs_ggwalk": float(diff.max()),
            "n_scarto": int((diff > 1e-12).sum()),
            "scarto_y_gg": int((g["y_gg"] != g["y_gg_ou"]).sum()),
            "rinomine_esonym": int((g["home"] != g["home_key_gg"]).sum()
                                   + (g["away"] != g["away_key_gg"]).sum()),
        }
    diag["aggancio_modello"] = agg_diag
    diag["_sintesi"] = {"n_righe": int(len(merged)),
                        "n_bet365": int((~merged["fallback"].astype(bool)).sum())}
    return merged, diag


# ---------------------------------------------------------------------------
# Metriche e bootstrap a blocchi
# ---------------------------------------------------------------------------
def metrics_block(y, p) -> dict:
    rel, res, unc = murphy_decomp(y, p, BINS)
    return {"n": int(len(y)), "mean_p": float(np.mean(p)),
            "event_rate": float(np.mean(y)), "brier": brier(y, p),
            "logloss": logloss(y, p), "reliability": float(rel),
            "resolution": float(res), "uncertainty": float(unc)}


def per_block_arrays(y, p, block_codes, n_blocks) -> dict:
    """Aggrega per blocco cio' che serve al bootstrap (resolution e LogLoss)."""
    y = np.asarray(y, float)
    p = np.clip(np.asarray(p, float), P_CLIP, 1 - P_CLIP)
    bin_id = np.minimum((p * BINS).astype(int), BINS - 1)
    pair = block_codes * BINS + bin_id
    ll = -(y * np.log(p) + (1 - y) * np.log(1 - p))
    return {
        "n_b": np.bincount(block_codes, minlength=n_blocks).astype(float),
        "y_b": np.bincount(block_codes, weights=y, minlength=n_blocks),
        "n_jb": np.bincount(pair, minlength=n_blocks * BINS).reshape(n_blocks, BINS).astype(float),
        "y_jb": np.bincount(pair, weights=y, minlength=n_blocks * BINS).reshape(n_blocks, BINS),
        "ll_sum_b": np.bincount(block_codes, weights=ll, minlength=n_blocks),
    }


def _point_estimate(agg) -> tuple:
    """Stima puntuale di resolution e LogLoss sulla stessa aggregazione dei blocchi."""
    n_tot = agg["n_b"].sum()
    mm = agg["y_b"].sum() / n_tot
    n_bin = agg["n_jb"].sum(axis=0)      # per BIN (non per blocco)
    y_bin = agg["y_jb"].sum(axis=0)
    m_bin = np.divide(y_bin, n_bin, out=np.zeros_like(y_bin), where=n_bin > 0)
    res = float(np.sum(n_bin * (m_bin - mm) ** 2) / n_tot)
    return res, float(agg["ll_sum_b"].sum() / n_tot)


def bootstrap_blocks(agg_a, agg_b, reps, seed):
    """IC 95% su Delta resolution (a - b) e Delta LogLoss (a - b), blocchi risamplati.

    Blocco = (lega, stagione, giornata). Il riferimento ``m`` della resolution e'
    quello del campione risamplato (definizione della PR #34) ed e' lo stesso per le
    due fonti: le differenze sono appaiate per costruzione.
    """
    n_blocks = len(agg_a["n_b"])
    rng = np.random.default_rng(seed)
    draw_idx = rng.integers(0, n_blocks, size=(reps, n_blocks))
    flat = (draw_idx + np.arange(reps)[:, None] * n_blocks).ravel()
    cnt = np.bincount(flat, minlength=reps * n_blocks).reshape(reps, n_blocks).astype(float)

    N = cnt @ agg_a["n_b"]
    m = (cnt @ agg_a["y_b"]) / N

    def res_draws(agg):
        Nb = cnt @ agg["n_jb"]
        Yb = cnt @ agg["y_jb"]
        mb = np.divide(Yb, Nb, out=np.zeros_like(Yb), where=Nb > 0)
        return (Nb * (mb - m[:, None]) ** 2).sum(axis=1) / N

    d_res = res_draws(agg_a) - res_draws(agg_b)
    d_ll = ((cnt @ agg_a["ll_sum_b"]) - (cnt @ agg_b["ll_sum_b"])) / N
    pt_a = _point_estimate(agg_a)
    pt_b = _point_estimate(agg_b)
    lo_res, hi_res = np.percentile(d_res, [2.5, 97.5])
    lo_ll, hi_ll = np.percentile(d_ll, [2.5, 97.5])
    return {
        "delta_resolution": pt_a[0] - pt_b[0],
        "delta_resolution_ci": [float(lo_res), float(hi_res)],
        "delta_logloss": pt_a[1] - pt_b[1],
        "delta_logloss_ci": [float(lo_ll), float(hi_ll)],
        "resolution_a": pt_a[0], "resolution_b": pt_b[0],
        "logloss_a": pt_a[1], "logloss_b": pt_b[1],
        "blocks": int(n_blocks), "replicates": int(reps), "seed": int(seed),
        "ci_excludes_zero_resolution": bool(lo_res > 0 or hi_res < 0),
        "ci_excludes_zero_logloss": bool(lo_ll > 0 or hi_ll < 0),
    }


def block_codes_for(df: pd.DataFrame):
    blocks = (df["league"].astype(str) + "|" + df["season"].astype(str) + "|"
              + df["date_day"].astype(str))
    codes, uniques = pd.factorize(blocks, sort=True)
    return codes, len(uniques)


def paired_diff(df: pd.DataFrame, col_a: str, col_b: str, reps: int, seed: int) -> dict:
    """Differenza appaiata fra due colonne sulle STESSE righe (nessuna imputazione)."""
    d = df[df[col_a].notna() & df[col_b].notna()]
    y = d["y"].to_numpy(float)
    codes, n_blocks = block_codes_for(d)
    agg_a = per_block_arrays(y, d[col_a].to_numpy(float), codes, n_blocks)
    agg_b = per_block_arrays(y, d[col_b].to_numpy(float), codes, n_blocks)
    out = bootstrap_blocks(agg_a, agg_b, reps, seed)
    out.update({"n": int(len(d)), "source_a": col_a, "source_b": col_b,
                "n_blocks": int(n_blocks)})
    # verifica: formula per blocchi == baserate_oos.decomp (stessa definizione)
    _, res_a, _ = murphy_decomp(y, d[col_a].to_numpy(float), BINS)
    _, res_b, _ = murphy_decomp(y, d[col_b].to_numpy(float), BINS)
    out["check_resolution_a"] = float(res_a)
    out["check_resolution_b"] = float(res_b)
    out["check_ok"] = bool(abs(out["resolution_a"] - res_a) < 1e-9
                           and abs(out["resolution_b"] - res_b) < 1e-9)
    return out


def evaluate_sources(df: pd.DataFrame, sources: dict, train_bases: dict) -> pd.DataFrame:
    rows = []
    for name, col in sources.items():
        sel = df[df[col].notna()]
        if sel.empty:
            continue
        y = sel["y"].to_numpy(float)
        p = sel[col].to_numpy(float)
        b = np.array([train_bases[(l, s)] for l, s in zip(sel["league"], sel["season"])])
        m = metrics_block(y, p)
        m_base = metrics_block(y, b)
        rows.append({"fonte": name, **m, "brier_train": m_base["brier"],
                     "logloss_train": m_base["logloss"],
                     "bss_brier": 1.0 - m["brier"] / m_base["brier"],
                     "bss_logloss": 1.0 - m["logloss"] / m_base["logloss"]})
    return pd.DataFrame(rows)


def market_frame(ou: pd.DataFrame, gg: pd.DataFrame, market: str,
                 seasons=EVAL_SEASONS) -> pd.DataFrame:
    if market == "OU2.5":
        d = ou[ou["season"].isin(seasons)].copy()
        d["y"] = d["y_over"]
        d["model_produzione"] = d["p_model_prod"]
        d["model_banco_PR34"] = d["p_model_bench"]
        d["model_banco_PR34_variante"] = d["p_model_benchvar"]
        for s in SOURCES:
            d[f"mercato_{s}"] = d[f"p__{s}"]
            d[f"mercato_{s}_shin"] = d[f"shin__{s}"]
    else:
        d = gg[gg["season"].isin(seasons)].copy()
        d["y"] = d["y_gg"]
        d["model_produzione"] = d["engine_gg"]
        d["model_produzione_banco_GG"] = d["p_model_prod_ggwalk"]
        d["model_banco_PR34"] = d["p_model_bench_gg"]
        d["model_banco_PR34_variante"] = d["p_model_benchvar_gg"]
        d["mercato_gg_oddsportal"] = d["p_market_gg"]
        d["mercato_gg_oddsportal_shin"] = d["p_market_gg_shin"]
    return d


# ---------------------------------------------------------------------------
# Encompassing (rolling-origin)
# ---------------------------------------------------------------------------
def encompassing(src: pd.DataFrame, market: str, model_col: str, market_col: str,
                 reps: int, seed: int) -> dict:
    """Logistica dell'esito su logit(p_modello) + logit(p_mercato), rolling-origin."""
    out = {"market": market, "model_col": model_col, "market_col": market_col, "folds": []}
    for fold in FOLDS:
        est = src[src["season"].isin(fold["estimate"])]
        ev = src[src["season"] == fold["evaluate"]]
        est = est[est[model_col].notna() & est[market_col].notna()]
        ev = ev[ev[model_col].notna() & ev[market_col].notna()].copy()
        if len(est) == 0 or len(ev) == 0:
            out["folds"].append({"estimate": list(fold["estimate"]),
                                 "evaluate": fold["evaluate"],
                                 "n_estimate": int(len(est)), "n_evaluate": int(len(ev)),
                                 "stato": "NON VERIFICABILE (campione vuoto)"})
            continue
        X = sm.add_constant(np.column_stack([
            logit(est[model_col].to_numpy(float)),
            logit(est[market_col].to_numpy(float))]))
        res = sm.Logit(est["y"].to_numpy(float), X).fit(disp=0)
        ci = res.conf_int(alpha=0.05)
        X_ev = sm.add_constant(np.column_stack([
            logit(ev[model_col].to_numpy(float)),
            logit(ev[market_col].to_numpy(float))]), has_constant="add")
        p_combo = np.asarray(res.predict(X_ev), dtype=float)
        y_ev = ev["y"].to_numpy(float)
        ev["p_combo"] = p_combo
        codes, n_blocks = block_codes_for(ev)
        boot = bootstrap_blocks(per_block_arrays(y_ev, p_combo, codes, n_blocks),
                                per_block_arrays(y_ev, ev[market_col].to_numpy(float),
                                                 codes, n_blocks), reps, seed)
        per_league = {}
        for league, g in ev.groupby("league", sort=True):
            y_l = g["y"].to_numpy(float)
            per_league[league] = {
                "n": int(len(g)),
                "logloss_mercato": logloss(y_l, g[market_col].to_numpy(float)),
                "logloss_modello": logloss(y_l, g[model_col].to_numpy(float)),
                "logloss_combo": logloss(y_l, g["p_combo"].to_numpy(float)),
                "delta_logloss_combo_menu_mercato": (
                    logloss(y_l, g["p_combo"].to_numpy(float))
                    - logloss(y_l, g[market_col].to_numpy(float))),
            }
        out["folds"].append({
            "estimate": list(fold["estimate"]), "evaluate": fold["evaluate"],
            "n_estimate": int(len(est)), "n_evaluate": int(len(ev)),
            "n_blocks_evaluate": int(n_blocks),
            "coef": {"costante": float(res.params[0]), "logit_modello": float(res.params[1]),
                     "logit_mercato": float(res.params[2])},
            "coef_ci": {"costante": [float(ci[0][0]), float(ci[0][1])],
                        "logit_modello": [float(ci[1][0]), float(ci[1][1])],
                        "logit_mercato": [float(ci[2][0]), float(ci[2][1])]},
            "se": {"costante": float(res.bse[0]), "logit_modello": float(res.bse[1]),
                   "logit_mercato": float(res.bse[2])},
            "pvalue": {"costante": float(res.pvalues[0]), "logit_modello": float(res.pvalues[1]),
                       "logit_mercato": float(res.pvalues[2])},
            "logloss_combo_oos": logloss(y_ev, p_combo),
            "logloss_mercato_oos": logloss(y_ev, ev[market_col].to_numpy(float)),
            "logloss_modello_oos": logloss(y_ev, ev[model_col].to_numpy(float)),
            "delta_logloss_combo_menu_mercato": boot["delta_logloss"],
            "delta_logloss_ci": boot["delta_logloss_ci"],
            "delta_logloss_ci_excludes_zero": boot["ci_excludes_zero_logloss"],
            "delta_resolution_combo_menu_mercato": boot["delta_resolution"],
            "delta_resolution_ci": boot["delta_resolution_ci"],
            "per_lega": per_league, "stato": "OK",
        })
    return out


# ---------------------------------------------------------------------------
# Lambda e verdetto
# ---------------------------------------------------------------------------
def lambda_dispersion(d: pd.DataFrame) -> list:
    rows = []
    for league, g in d.groupby("league", sort=True):
        rec = {"lega": league, "n": int(len(g))}
        for name in ("chiusura_b365", "chiusura_pinnacle"):
            sel = g[f"mercato_{name}"].notna()
            rec[f"n_{name}"] = int(sel.sum())
            if sel.any():
                lam = lambda_from_under25(1.0 - g.loc[sel, f"mercato_{name}"].to_numpy(float))
                rec[f"media_log_lambda_{name}"] = float(np.mean(np.log(lam)))
                rec[f"sd_log_lambda_{name}"] = (float(np.std(np.log(lam), ddof=1))
                                                if sel.sum() > 1 else None)
                rec[f"media_lambda_{name}"] = float(np.mean(lam))
            else:
                rec[f"media_log_lambda_{name}"] = None
                rec[f"sd_log_lambda_{name}"] = None
                rec[f"media_lambda_{name}"] = None
        lam_mod = g["lambda_total"].to_numpy(float)
        # ``model_produzione`` e' la P(Over 2.5): l'inversione vuole la P(Under)
        lam_inv = lambda_from_under25(1.0 - g["model_produzione"].to_numpy(float))
        rec["n_modello"] = int(len(g))
        rec["media_log_lambda_modello"] = float(np.mean(np.log(lam_mod)))
        rec["sd_log_lambda_modello"] = float(np.std(np.log(lam_mod), ddof=1))
        rec["media_lambda_modello"] = float(np.mean(lam_mod))
        rec["scarto_max_log_lambda_esplicito_vs_invertito"] = float(
            np.max(np.abs(np.log(lam_inv) - np.log(lam_mod))))
        lam_bench = lambda_from_under25(g["model_banco_PR34"].to_numpy(float))
        rec["media_log_lambda_banco_PR34"] = float(np.mean(np.log(lam_bench)))
        rec["sd_log_lambda_banco_PR34"] = float(np.std(np.log(lam_bench), ddof=1))
        rows.append(rec)
    return rows


def verdict(diff: dict) -> dict:
    """Regola di lettura fissata a priori (meccanica, nessuna interpretazione)."""
    dres = diff["delta_resolution"]
    excludes = diff["ci_excludes_zero_resolution"]
    if dres < CEILING_EPS or not excludes:
        v = "TETTO RAGGIUNTO"
        motivo = ("differenza < soglia" if dres < CEILING_EPS
                  else "IC 95% della differenza include lo zero")
    else:
        v = "MARGINE ESISTENTE"
        motivo = "differenza >= soglia con IC 95% che esclude lo zero"
    return {"verdetto": v, "delta_resolution": dres, "ci": diff["delta_resolution_ci"],
            "ic_esclude_zero": excludes, "soglia": CEILING_EPS, "motivo": motivo,
            "resolution_mercato": diff["resolution_a"],
            "resolution_modello": diff["resolution_b"],
            "delta_logloss": diff["delta_logloss"],
            "delta_logloss_ci": diff["delta_logloss_ci"]}


_ESECUZIONE_LOG: list = []


def git_facts() -> dict:
    """Stato del repository al momento della generazione (una sola sorgente di verita')."""

    def run(cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=_REPO_ROOT, check=False)
            return (r.stdout + r.stderr).strip()
        except OSError as exc:                       # pragma: no cover
            return f"<errore: {exc}>"

    diff_names = [x for x in run(["git", "diff", "--name-only", "origin/main", "HEAD"]).splitlines() if x]
    status = [x for x in run(["git", "status", "--porcelain"]).splitlines() if x]
    toccati = sorted(set(diff_names) | {x[3:].strip() for x in status if len(x) > 3})
    fuori = [x for x in toccati if not x.startswith("audit/")]
    return {
        "head": run(["git", "rev-parse", "HEAD"]),
        "subject": run(["git", "log", "-1", "--pretty=%s"]),
        "status_porcelain": status,
        "diff_names": diff_names,
        "diff_stat": run(["git", "diff", "--stat", "origin/main", "HEAD"]),
        "file_toccati": toccati,
        "file_fuori_da_audit": fuori,
        "solo_audit": not fuori,
    }


def build_evidenze(esecuzione_log, dry_run: bool) -> dict:
    """Comandi eseguiti e loro output, registrati AL MOMENTO della generazione."""

    def run(cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=_REPO_ROOT,
                               shell=isinstance(cmd, str), check=False)
            return (r.stdout + r.stderr).strip()
        except OSError as exc:                       # pragma: no cover
            return f"<errore nell'esecuzione: {exc}>"

    def versione(pkg):
        try:
            import importlib.metadata as md
            return f"{pkg} {md.version(pkg)}"
        except Exception:                            # pragma: no cover
            return f"{pkg} ?"

    fatti = git_facts()
    pytest_out = run([sys.executable, "-m", "pytest", "-q",
                      "audit/test_gg_ng_calibration.py", "audit/test_ppda_deep_rolling.py",
                      "audit/test_shots_residual.py", "audit/test_economic_ev.py",
                      "audit/test_diagnose_clv_pinnacle.py"])
    fatti["pytest_ok"] = ("failed" not in pytest_out and "error" not in pytest_out.lower())
    fatti["pytest_out"] = pytest_out.strip().splitlines()[-1] if pytest_out.strip() else ""
    comandi = [
        ("git rev-parse HEAD", fatti["head"]),
        ("git log -1 --pretty=%s", fatti["subject"]),
        ("git status --porcelain", "\n".join(fatti["status_porcelain"]) or "(vuoto)"),
        ("git diff --name-only origin/main HEAD",
         "\n".join(fatti["diff_names"]) or "(vuoto)"),
        ("git diff --stat origin/main HEAD", fatti["diff_stat"] or "(vuoto)"),
        ("python -V", run([sys.executable, "-V"])),
        ("versioni pacchetti", "; ".join(versione(p) for p in
                                         ("numpy", "pandas", "scipy", "statsmodels",
                                          "streamlit", "scikit-learn"))),
        ("pytest -q sui test dei banchi riusati", pytest_out),
        ("python audit/totals_market_ceiling.py"
         + (" --no-write (dry-run)" if dry_run else ""),
         "\n".join(esecuzione_log)),
    ]
    return {"comandi": comandi, "fatti": fatti}


# ---------------------------------------------------------------------------
# Referto
# ---------------------------------------------------------------------------
def fmt(x, nd=4):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return f"{x:+.{nd}f}"


def fmt0(x, nd=4):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "-"
    return f"{x:.{nd}f}"


def ci_str(ci, nd=4):
    if ci is None or any(c is None or not np.isfinite(c) for c in ci):
        return "-"
    return f"[{ci[0]:+.{nd}f}; {ci[1]:+.{nd}f}]"


def _cell(x) -> str:
    """Cella di tabella markdown: il pipe va escapato, altrimenti rompe la tabella."""
    return str(x).replace("|", "\\|")


def md_table(headers, rows) -> str:
    out = ["| " + " | ".join(_cell(h) for h in headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(_cell(c) for c in r) + " |")
    return "\n".join(out)


def render_report(p) -> str:
    L = []
    A = L.append
    A("# Tetto pratico dei Totali: modello contro mercato (O/U 2.5 e GG/NG)")
    A("")
    A("*Referto GENERATO da `audit/totals_market_ceiling.py` (sola lettura: nessuna modifica a "
      "`SoccerMath/`). Rigenerabile con `python audit/totals_market_ceiling.py` dalla radice "
      "del repo.*")
    A("")
    A(f"- Generato: {p['meta']['generated_at']} — commit `{p['meta']['commit']}` "
      f"({p['meta']['commit_subject']})")
    A(f"- Bootstrap: {p['meta']['replicates']} repliche, seed {p['meta']['seed']}, blocchi "
      f"(lega x stagione x giornata = data della partita, come nei banchi PR #34/#39)")
    A(f"- De-vig di decisione: proporzionale (`backtest_experiment_all.devig_2way`); Shin "
      f"riportato a parte (§2b)")
    A(f"- Finestra di valutazione: {', '.join(EVAL_SEASONS)} — solo partite con modello E quota")
    A(f"- Base rate per il BSS: base rate del TRAIN per lega e stagione (`baserate_oos.raw`, "
      f"convenzione PR #34)")
    A(f"- Soglia di lettura fissata a priori: `CEILING_EPS = {p['meta']['ceiling_eps']}`")
    A("")
    A("## 0. Quali probabilita' del modello (dichiarazione)")
    A("")
    A("La commessa cita due precedenti che **non sono lo stesso codice**. Entrambi sono "
      "riportati per intero; la colonna primaria (quella dei verdetti) e' la testa Totali di "
      "produzione.")
    A("")
    A(md_table(["colonna", "codice riusato (importato, non riscritto)", "precedente"],
               [["`model_produzione`",
                 "`ppda_residual_test.production_totali`: P(Over 2.5) = 1 − `engine_u25`, "
                 "P(GG) = `engine_gg`, `lambda_total`",
                 "test sul residuo PPDA (PR #33) e tiri (PR #39)"],
                ["`model_banco_PR34`",
                 "`backtest_experiment_all.run_walkforward`: `poisson_o25` (P(Over 2.5)), "
                 "`poisson_gg`",
                 "`audit/results/ev_and_baserate_fix.md` (PR #34), `baserate_oos.py`"]]))
    A("")
    A("Controlli incrociati fra banchi (non assunzioni):")
    A("")
    A(md_table(["controllo", "valore"],
               [["scarto massimo fra `engine_gg` e `walk_forward_gg_predictions` (valoreassoluto)",
                 fmt0(p["diagnostics"]["gg"]["aggancio_modello"].get(
                     "Serie A", {}).get("scarto_engine_gg_vs_ggwalk", None), 12) + " (Serie A) — "
                 "per lega nel JSON"],
                ["righe con esito GG diverso fra le due fonti",
                 "; ".join(f"{lg}: {v['scarto_y_gg']}"
                           for lg, v in p["diagnostics"]["gg"]["aggancio_modello"].items())],
                ["righe BTTS senza aggancio al modello",
                 "; ".join(f"{lg}: {v['righe_senza_aggancio_modello']}"
                           for lg, v in p["diagnostics"]["gg"]["aggancio_modello"].items())],
                ["rinomine dei nomi CSV da parte della mappa esonimi del banco GG",
                 "; ".join(f"{lg}: {v['rinomine_esonym']}"
                           for lg, v in p["diagnostics"]["gg"]["aggancio_modello"].items())],
                ["scarto `real_uo`/`real_gg` del banco vs esito ricalcolato dai gol",
                 "; ".join(f"{lg}: ou={v['scarto_bench_vs_esito_ou']} "
                           f"gg={v['scarto_bench_vs_esito_gg']}"
                           for lg, v in p["diagnostics"]["ou"].items())]]))
    A("")
    A("## 1. Copertura delle quote")
    A("")
    A("### 1a. Over/Under 2.5 (CSV football-data), per lega, stagione e colonna")
    A("")
    A("`nn` = valori non nulli; `coppia` = entrambi i lati usabili (quota > 1,0); `ovr` = media "
      "di 1/q_over + 1/q_under sul campione con coppia. `B365*` apertura, `B365C*` chiusura "
      "bet365, `PC*` chiusura Pinnacle.")
    A("")
    A("Le stagioni 2022/23-2023/24 sono riportate per completezza (servono al base rate del "
      "train); la finestra di valutazione e' 2024/25-2025/26. La riga 2026/27 dei CSV "
      "`*_Live.csv` ha 0 valori: i file Live non contengono quote O/U e restano fuori "
      "dall'analisi (limite dichiarato in §8).")
    A("")
    rows = []
    for r in p["coverage"]["ou"]:
        rows.append([r["league"], r["season"], r["rows"],
                     r["nn__B365>2.5"], r["nn__B365<2.5"], r["coppia__apertura_b365"],
                     fmt0(r["overround_medio__apertura_b365"]),
                     r["nn__B365C>2.5"], r["nn__B365C<2.5"], r["coppia__chiusura_b365"],
                     fmt0(r["overround_medio__chiusura_b365"]),
                     r["nn__PC>2.5"], r["nn__PC<2.5"], r["coppia__chiusura_pinnacle"],
                     fmt0(r["overround_medio__chiusura_pinnacle"])])
    A(md_table(["lega", "stagione", "righe", "B365>2.5", "B365<2.5", "coppia ap.", "ovr ap.",
                "B365C>2.5", "B365C<2.5", "coppia ch.", "ovr ch.", "PC>2.5", "PC<2.5",
                "coppia PC", "ovr PC"], rows))
    A("")
    A("### 1b. GG/NG (`audit/data/*_btts.json`, Oddsportal)")
    A("")
    rows = []
    for lg, seasons in p["coverage"]["gg"].items():
        for se, v in seasons.items():
            if not isinstance(v, dict) or "righe_json" not in v:
                continue
            rows.append([lg, se, v["righe_json"], v["incrociate"], v["bet365"], v["fallback"],
                         v["coppia_assente"], v["senza_quota"], v["data_in_conflitto"],
                         v["dup_non_risolti"], v["senza_risultato"],
                         fmt0(v["overround_medio"])])
    A(md_table(["lega", "stagione", "righe JSON", "incrociate", "bet365", "fallback",
                "coppia assente", "senza quota", "data in conflitto", "dup non risolti",
                "senza risultato", "overround medio"], rows))
    A("")
    A("**Colonne disponibili per GG/NG**: un solo snapshot per partita "
      "(`submarket_name` = `Both Teams to Score`, `period` = `FullTime`, un record per "
      "bookmaker). Non esistono colonne di apertura/chiusura ne' Pinnacle in questi file: il "
      "confronto apertura-contro-chiusura per GG/NG e' **NON VERIFICABILE**.")
    A("")
    A("### 1c. Campione di valutazione (modello E quota), per fonte e lega")
    A("")
    rows = []
    for m, srcs in p["sample_sizes"].items():
        for s, per in srcs.items():
            for lg, n in per.items():
                rows.append([m, s, lg, n])
    A(md_table(["mercato", "fonte", "lega", "n"], rows))
    A("")
    A("### 1d. Sonda F_season: giornate in cui la fonte xG della stagione in corso non e' "
      "attiva")
    A("")
    A("Quando l'ancora di lega manca (`fs_active = False` in `app.get_league_engine`), la "
      "produzione assegna `att0_pure/def0_pure = att/def` (testa 1X2 con forma e fattore "
      "mercato), `production_totali` assegna il fallback gol e `walk_forward_gg_predictions` "
      "assegna `att/def` come la produzione: su queste righe i banchi divergono. La sonda "
      "chiama la stessa `xg_archive.season_point_in_time_averages` usata dai banchi e conta le "
      "coppie (stagione, giornata) con ancora assente.")
    A("")
    rows = []
    for lg, r in p["diagnostics"]["fs_season"].items():
        n_eval = p["sensitivity_fs"]["OU2.5"]["per_lega_escluse"].get(lg, 0)
        rows.append([lg, r["coppie_stagione_data_esaminate"], r["coppie_fs_non_attiva"],
                     ", ".join(sorted({x[0] for x in r["date_fs_non_attiva"]})) or "-",
                     ", ".join(sorted({x[1] for x in r["date_fs_non_attiva"]})) or "-",
                     n_eval])
    A(md_table(["lega", "coppie (stagione, data) esaminate", "di cui F_season non attiva",
                "stagioni interessate", "date interessate", "righe di valutazione escluse "
                "(O/U, 2024/25+2025/26)"], rows))
    A("")
    A("Differenza misurata fra i due banchi di produzione sulle righe incrociate GG/NG "
      "(`engine_gg` di `production_totali` contro `walk_forward_gg_predictions`):")
    A("")
    A(md_table(["lega", "righe con scarto", "scarto massimo Δp", "righe BTTS senza aggancio"],
               [[lg, v.get("n_scarto", "-"), fmt0(v["scarto_engine_gg_vs_ggwalk"], 12),
                 v["righe_senza_aggancio_modello"]]
                for lg, v in p["diagnostics"]["gg"]["aggancio_modello"].items()]))
    A("")

    A("## 2. Metriche per mercato e per fonte")
    A("")
    A("Scomposizione di Murphy a 10 bin con la stessa funzione della PR #34 "
      "(`baserate_oos.decomp`): Brier = reliability − resolution + uncertainty. BSS contro il "
      "base rate del train, sulle stesse righe.")
    A("")
    for m in MARKETS:
        A(f"### {m} — pooled")
        A("")
        rows = [[r["fonte"], r["n"], fmt0(r["mean_p"]), fmt0(r["event_rate"]),
                 fmt0(r["brier"]), fmt0(r["logloss"]), fmt0(r["reliability"], 5),
                 fmt0(r["resolution"], 5), fmt0(r["uncertainty"], 5),
                 fmt0(r["bss_brier"]), fmt0(r["bss_logloss"])]
                for r in p["metrics"][m]["pooled"]]
        A(md_table(["fonte", "n", "media p", "tasso reale", "Brier", "LogLoss", "reliab.",
                    "resol.", "uncert.", "BSS Brier", "BSS LogLoss"], rows))
        A("")
        A(f"### {m} — per lega")
        A("")
        rows = []
        for lg, recs in p["metrics"][m]["per_league"].items():
            for r in recs:
                rows.append([lg, r["fonte"], r["n"], fmt0(r["brier"]), fmt0(r["logloss"]),
                             fmt0(r["resolution"], 5), fmt0(r["reliability"], 5),
                             fmt0(r["bss_brier"])])
        A(md_table(["lega", "fonte", "n", "Brier", "LogLoss", "resol.", "reliab.",
                    "BSS Brier"], rows))
        A("")
    A("### 2b. De-vig proporzionale contro Shin (stesse righe)")
    A("")
    rows = []
    for m in MARKETS:
        for r in p["shin"][m]:
            rows.append([m, r["fonte"], r["n"], fmt0(r["brier"]), fmt0(r["logloss"]),
                         fmt0(r["z_shin_medio"]), fmt0(r["overround_medio"]),
                         fmt0(r["brier_shin"]), fmt0(r["logloss_shin"]),
                         fmt(r["delta_brier_shin_menu_prop"], 5),
                         fmt(r["delta_logloss_shin_menu_prop"], 5)])
    A(md_table(["mercato", "fonte", "n", "Brier prop.", "LogLoss prop.", "z medio",
                "overround", "Brier Shin", "LogLoss Shin", "ΔBrier Shin−prop",
                "ΔLogLoss Shin−prop"], rows))
    A("")

    A("## 3. Differenze appaiate (bootstrap a blocchi, IC 95%)")
    A("")
    A(f"`Δ resolution` > 0 = la fonte A risolve meglio della fonte B; `Δ LogLoss` < 0 = la "
      f"fonte A perde meno. Blocchi = lega x stagione x giornata; {p['meta']['replicates']} "
      f"repliche. La colonna `IC≠0` dice se l'IC 95% esclude lo zero.")
    A("")
    for m in MARKETS:
        A(f"### {m} — pooled")
        A("")
        rows = [[r["contrasto"], r["n"], r["n_blocks"], fmt(r["delta_resolution"]),
                 ci_str(r["delta_resolution_ci"]),
                 "sì" if r["ci_excludes_zero_resolution"] else "no",
                 fmt(r["delta_logloss"]), ci_str(r["delta_logloss_ci"]),
                 "sì" if r["ci_excludes_zero_logloss"] else "no"]
                for r in p["diffs"][m]["pooled"]]
        A(md_table(["contrasto", "n", "blocchi", "Δ resolution", "IC 95%", "IC≠0",
                    "Δ LogLoss", "IC 95%", "IC≠0"], rows))
        A("")
        A(f"### {m} — per lega (chiusura di mercato contro modello di produzione)")
        A("")
        rows = [[lg, r["n"], fmt(r["delta_resolution"]), ci_str(r["delta_resolution_ci"]),
                 "sì" if r["ci_excludes_zero_resolution"] else "no",
                 fmt(r["delta_logloss"]), ci_str(r["delta_logloss_ci"]),
                 fmt0(r["resolution_a"], 5), fmt0(r["resolution_b"], 5)]
                for lg, r in p["diffs"][m]["per_league"].items()]
        A(md_table(["lega", "n", "Δ resolution", "IC 95%", "IC≠0", "Δ LogLoss", "IC 95%",
                    "res. mercato", "res. modello"], rows))
        A("")
        A(f"### {m} — per lega (tutti gli altri contrasti)")
        A("")
        rows = []
        for contrasto, perlg in p["diffs"][m]["per_league_others"].items():
            for lg, r in perlg.items():
                if r is None:
                    rows.append([contrasto, lg, "<10", "-", "-", "-", "-", "-"])
                    continue
                rows.append([contrasto, lg, r["n"], fmt(r["delta_resolution"]),
                             ci_str(r["delta_resolution_ci"]),
                             "sì" if r["ci_excludes_zero_resolution"] else "no",
                             fmt(r["delta_logloss"]), ci_str(r["delta_logloss_ci"])])
        A(md_table(["contrasto", "lega", "n", "Δ resolution", "IC 95%", "IC≠0", "Δ LogLoss",
                    "IC 95%"], rows))
        A("")
        A("### 3b. Chiusura contro apertura (stessa fonte)")
        A("")
        rows = []
        for m in MARKETS:
            for r in p["open_close"][m]:
                if r.get("n", 0) == 0:
                    rows.append([m, r["confronto"], 0, "-", "-", "-", "-", "-"])
                    continue
                rows.append([m, r["confronto"], r["n"], fmt(r["delta_resolution"]),
                             ci_str(r["delta_resolution_ci"]),
                             "sì" if r["ci_excludes_zero_resolution"] else "no",
                             fmt(r["delta_logloss"]), ci_str(r["delta_logloss_ci"])])
        A(md_table(["mercato", "confronto", "n", "Δ resolution", "IC 95%", "IC≠0", "Δ LogLoss",
                    "IC 95%"], rows))
        A("")

    A("### 3c. Sensibilita': stesse differenze senza le giornate con F_season non attiva")
    A("")
    A("Le righe in cui i due banchi di produzione divergono (testa Totali: `att0_pure` "
      "assegnato in modo diverso) vengono ESCLUSE e le differenze ricalcolate: se il verdetto "
      "non cambia, non dipende da quelle righe.")
    A("")
    rows = []
    for m in MARKETS:
        r = p["sensitivity_fs"][m]
        rows.append([m, r["n_righe_totali"], r["n_righe_escluse_fs_non_attiva"],
                     r["n_righe_ridotte"], fmt(r["contrasto"]["delta_resolution"]),
                     ci_str(r["contrasto"]["delta_resolution_ci"]),
                     fmt(r["contrasto"]["delta_logloss"]),
                     ci_str(r["contrasto"]["delta_logloss_ci"])])
    A(md_table(["mercato", "righe", "escluse", "righe ridotte", "Δ resolution", "IC 95%",
                "Δ LogLoss", "IC 95%"], rows))
    A("")
    A("Metriche sulla stessa finestra ridotta:")
    A("")
    rows = []
    for m in MARKETS:
        for r in p["sensitivity_fs"][m]["metrics"]:
            rows.append([m, r["fonte"], r["n"], fmt0(r["brier"]), fmt0(r["logloss"]),
                         fmt0(r["resolution"], 5), fmt0(r["bss_brier"])])
    A(md_table(["mercato", "fonte", "n", "Brier", "LogLoss", "resol.", "BSS Brier"], rows))
    A("")

    A("## 4. Dispersione dei lambda: mercato contro modello")
    A("")
    A("La P(Under 2.5) de-vigata viene invertita in un lambda totale Poisson "
      "(`P(under) = exp(−λ)(1 + λ + λ²/2)`; la somma di due Poisson indipendenti e' Poisson, "
      "quindi l'inversione usa esattamente la probabilita' che il modello calcola). Per il "
      "modello di produzione il lambda totale e' anche esplicito (`lambda_total`): lo scarto "
      "massimo fra esplicito e invertito misura la fedelta' dell'inversione.")
    A("")
    rows = []
    for r in p["lambda_dispersion"]:
        rows.append([r["lega"], r["n"], fmt0(r["media_lambda_chiusura_b365"], 3),
                     fmt0(r["media_log_lambda_chiusura_b365"]),
                     fmt0(r["sd_log_lambda_chiusura_b365"]), r["n_chiusura_pinnacle"],
                     fmt0(r["media_log_lambda_chiusura_pinnacle"]),
                     fmt0(r["sd_log_lambda_chiusura_pinnacle"]),
                     fmt0(r["media_log_lambda_modello"]), fmt0(r["sd_log_lambda_modello"]),
                     fmt0(r["media_log_lambda_banco_PR34"]),
                     fmt0(r["sd_log_lambda_banco_PR34"]),
                     fmt0(r["scarto_max_log_lambda_esplicito_vs_invertito"], 8)])
    A(md_table(["lega", "n", "λ medio merc.", "media log λ merc.", "sd log λ merc.", "n PC",
                "media log λ PC", "sd log λ PC", "media log λ modello", "sd log λ modello",
                "media log λ banco", "sd log λ banco", "scarto max inversione"], rows))
    A("")

    A("## 5. Il modello aggiunge qualcosa al mercato? (encompassing, rolling-origin)")
    A("")
    A("Logistica `esito ~ logit(p_modello) + logit(p_mercato di chiusura)`: stima su 2023/24 "
      "(valutazione 2024/25) e su 2023/24+2024/25 (valutazione 2025/26). "
      "`ΔLogLoss combo − solo mercato` e' fuori campione, con bootstrap a blocchi.")
    A("")
    for m in MARKETS:
        for model_col, enc in p["encompassing"][m].items():
            A(f"### {m} — modello `{model_col}` (mercato: `{enc['market_col']}`)")
            A("")
            rows = []
            for fold in enc["folds"]:
                if fold.get("stato") != "OK":
                    rows.append([", ".join(fold["estimate"]), fold["evaluate"],
                                 fold.get("stato", "-"), "-", "-", "-", "-", "-"])
                    continue
                rows.append([", ".join(fold["estimate"]), fold["evaluate"],
                             f"{fold['n_estimate']} → {fold['n_evaluate']}",
                             f"{fmt(fold['coef']['logit_modello'])} "
                             f"{ci_str(fold['coef_ci']['logit_modello'])}",
                             f"{fmt(fold['coef']['logit_mercato'])} "
                             f"{ci_str(fold['coef_ci']['logit_mercato'])}",
                             f"{fmt(fold['coef']['costante'])} "
                             f"{ci_str(fold['coef_ci']['costante'])}",
                             fmt(fold["delta_logloss_combo_menu_mercato"]),
                             ci_str(fold["delta_logloss_ci"])])
            A(md_table(["stima su", "valuta su", "n stima → n val.", "β modello (IC 95%)",
                        "β mercato (IC 95%)", "costante (IC 95%)", "ΔLogLoss combo−mercato",
                        "IC 95%"], rows))
            A("")
            A("Dettaglio per lega nella valutazione (LogLoss: mercato / modello / combinazione):")
            A("")
            rows = []
            for fold in enc["folds"]:
                if fold.get("stato") != "OK":
                    continue
                for lg, r in fold["per_lega"].items():
                    rows.append([", ".join(fold["estimate"]), fold["evaluate"], lg, r["n"],
                                 fmt0(r["logloss_mercato"]), fmt0(r["logloss_modello"]),
                                 fmt0(r["logloss_combo"]),
                                 fmt(r["delta_logloss_combo_menu_mercato"])])
            A(md_table(["stima su", "valuta su", "lega", "n", "LogLoss mercato",
                        "LogLoss modello", "LogLoss combo", "ΔLogLoss combo−mercato"], rows))
            A("")

    A("## 6. Verdetto (regola fissata a priori, applicata dal codice)")
    A("")
    A(f"**TETTO RAGGIUNTO** se `resolution(chiusura) − resolution(modello) < "
      f"{p['meta']['ceiling_eps']}` (pooled) **oppure** se l'IC 95% della differenza include "
      f"lo zero; **MARGINE ESISTENTE** se la differenza e' >= "
      f"{p['meta']['ceiling_eps']} con IC che esclude lo zero.")
    A("")
    A("**Convenzione di segno (da leggere prima della tabella).** "
      "`Δ resolution = resolution(mercato di chiusura) − resolution(modello)`: un Δ positivo "
      "significa che e' **il mercato** a risolvere meglio, cioe' che il modello sta SOTTO il "
      "mercato. Con la regola fissata dalla commessa: `TETTO RAGGIUNTO` = il modello e' a "
      "livello del mercato (nessun margine ulteriore ottenibile); `MARGINE ESISTENTE` = il "
      "divario fra mercato e modello e' materiale (>= soglia con IC che esclude lo zero). "
      "La colonna `lettura speculare` applica la STESSA regola alla differenza nel verso "
      "opposto (`modello − mercato`), per rendere esplicito cosa cambia se la commessa "
      "intendeva quello: le due letture differiscono solo per l'etichetta, non per i numeri.")
    A("")
    rows = []
    for m in MARKETS:
        for v in p["verdicts"][m]:
            spec = p["verdicts_speculari"][m].get(
                f"{v['modello']}||{v['fonte_mercato']}", {}).get("verdetto", "-")
            rows.append([m, v["modello"], v["fonte_mercato"], fmt(v["delta_resolution"]),
                         ci_str(v["ci"]), "sì" if v["ic_esclude_zero"] else "no",
                         v["verdetto"], spec, v["motivo"]])
    A(md_table(["mercato", "modello", "fonte di mercato", "Δ resolution", "IC 95%", "IC≠0",
                "verdetto (regola letterale)", "lettura speculare", "motivo"], rows))
    A("")
    A("Ripartizione del margine fra apertura e chiusura (solo dove il verdetto e' MARGINE "
      "ESISTENTE; altrimenti la tabella resta come diagnostica fissata a priori):")
    A("")
    rows = []
    for m in MARKETS:
        for r in p["open_close"][m]:
            if r.get("n", 0) == 0:
                rows.append([m, r["confronto"], "-", "-", "-", "-"])
                continue
            rows.append([m, r["confronto"], r["n"], fmt(r["delta_resolution"]),
                         ci_str(r["delta_resolution_ci"]), fmt(r["delta_logloss"])])
    A(md_table(["mercato", "confronto", "n", "Δ resolution", "IC 95%", "Δ LogLoss"], rows))
    A("")
    A("**Quanta parte del divario mercato-modello e' gia' nelle aperture (informazione "
      "disponibile prima).** Composizione additiva: `Δres(chiusura − modello) = "
      "Δres(apertura − modello) + Δres(chiusura − apertura)`.")
    A("")
    rows = []
    for m in MARKETS:
        oc = {r["confronto"]: r for r in p["open_close"][m]}
        ap = next((r for k, r in oc.items() if "apertura − modello" in k and r.get("n")), None)
        cl = next((r for k, r in oc.items() if "chiusura − modello" in k and r.get("n")), None)
        ch = next((r for k, r in oc.items() if "chiusura − apertura" in k and r.get("n")), None)
        if not (ap and cl):
            rows.append([m, "NON VERIFICABILE", "-", "-", "-"])
            continue
        quota = (ap["delta_resolution"] / cl["delta_resolution"]
                 if cl["delta_resolution"] else float("nan"))
        rows.append([m, fmt(ap["delta_resolution"]),
                     f"{100 * quota:.0f}% del divario totale",
                     fmt(ch["delta_resolution"]) if ch else "-",
                     (f"{ch['delta_resolution'] / cl['delta_resolution'] * 100:.0f}%"
                      if ch else "-")])
    A(md_table(["mercato", "Δres gia' in apertura (B365)", "quota del divario totale",
                "Δres solo in chiusura (chiusura − apertura)", "quota"], rows))
    A("")
    A("Per GG/NG la ripartizione apertura/chiusura e' NON VERIFICABILE: i file BTTS hanno un "
      "unico snapshot per partita (§1b).")
    A("")

    A("## 7. Conformita' della commessa: esito, comando, evidenza")
    A("")
    A(md_table(["punto", "esito", "comando", "evidenza"], p["conformita"]))
    A("")
    A("## 8. Limiti e cose non verificabili")
    A("")
    for lim in p["limiti"]:
        A(f"- {lim}")
    A("")
    A("## 9. Evidenze: comandi eseguiti e loro output")
    A("")
    for cmd, out in p["evidenze"]["comandi"]:
        A(f"`{cmd}`")
        A("")
        A("```text")
        A(out if out else "(nessun output)")
        A("```")
        A("")
    A("## 10. Output pesanti (non versionati)")
    A("")
    for k, v in p.get("outputs", {}).items():
        A(f"- `{k}`: {v}")
    A("")

    A("## 11. Sintesi in chiusura (le tabelle richieste dalla commessa)")
    A("")
    A("### 11a. Resolution e BSS per fonte e mercato (pooled)")
    A("")
    rows = []
    for m in MARKETS:
        for r in p["metrics"][m]["pooled"]:
            rows.append([m, r["fonte"], r["n"], fmt0(r["resolution"], 6),
                         fmt0(r["reliability"], 6), fmt(r["bss_brier"]), fmt(r["bss_logloss"])])
    A(md_table(["mercato", "fonte", "n", "resolution", "reliability", "BSS Brier",
                "BSS LogLoss"], rows))
    A("")
    A("### 11b. Differenze di resolution con IC 95% (chiusura di mercato − modello, pooled)")
    A("")
    rows = []
    for m in MARKETS:
        for v in p["verdicts"][m]:
            rows.append([m, v["fonte_mercato"], v["modello"], fmt(v["delta_resolution"]),
                         ci_str(v["ci"]), fmt(v["delta_logloss"]), v["verdetto"]])
    A(md_table(["mercato", "fonte di mercato", "modello", "Δ resolution", "IC 95%",
                "Δ LogLoss", "verdetto"], rows))
    A("")
    A("### 11c. Dispersione dei lambda (log λ, per lega)")
    A("")
    rows = [[r["lega"], r["n"], fmt0(r["media_log_lambda_chiusura_b365"], 4),
             fmt0(r["sd_log_lambda_chiusura_b365"], 4),
             fmt0(r["media_log_lambda_modello"], 4), fmt0(r["sd_log_lambda_modello"], 4),
             fmt0(r["sd_log_lambda_chiusura_b365"] / r["sd_log_lambda_modello"], 3)]
            for r in p["lambda_dispersion"]]
    A(md_table(["lega", "n", "media log λ mercato", "sd log λ mercato", "media log λ modello",
                "sd log λ modello", "rapporto sd"], rows))
    A("")
    A("### 11d. Coefficienti encompassing (chiusura, pooled sulla finestra di valutazione)")
    A("")
    rows = []
    for m in MARKETS:
        for model, enc in p["encompassing"][m].items():
            for fold in enc["folds"]:
                if fold.get("stato") != "OK":
                    continue
                rows.append([m, model, "+".join(fold["estimate"]), fold["evaluate"],
                             fmt0(fold["coef"]["logit_modello"], 3) + " "
                             + ci_str(fold["coef_ci"]["logit_modello"], 3),
                             fmt0(fold["coef"]["logit_mercato"], 3) + " "
                             + ci_str(fold["coef_ci"]["logit_mercato"], 3),
                             fmt(fold["delta_logloss_combo_menu_mercato"]),
                             ci_str(fold["delta_logloss_ci"])])
    A(md_table(["mercato", "modello", "stima su", "valuta su", "β modello (IC 95%)",
                "β mercato (IC 95%)", "ΔLogLoss combo−mercato", "IC 95%"], rows))
    A("")
    A("### 11e. Verdetto per mercato (colonna di produzione; banchi secondari in §6)")
    A("")
    rows = []
    for m in MARKETS:
        v = next(x for x in p["verdicts"][m] if x["modello"] == "model_produzione")
        rows.append([m, fmt(v["delta_resolution"]), ci_str(v["ci"]), v["verdetto"]])
    A(md_table(["mercato", "Δ resolution (chiusura − modello)", "IC 95%", "verdetto"], rows))
    A("")
    A("### 11f. Verdetto di processo")
    A("")
    f6 = p["evidenze"]["fatti"]
    fuori = f6["file_fuori_da_audit"]
    mergeable = bool(f6["solo_audit"]) and bool(f6["pytest_ok"])
    rows = [
        ["nessuna modifica a `SoccerMath/`", "OK",
         "`git status --porcelain` + `git diff --name-only`",
         ", ".join("`" + x + "`" for x in f6["file_toccati"]) or "(nessuno)"],
        ["diff confinato ad `audit/`", "OK" if not fuori else "NON OK",
         "`git diff --name-only origin/main HEAD`",
         "nessun file fuori da `audit/`" if not fuori else "FUORI: " + ", ".join(fuori)],
        ["test dei banchi riusati", "OK" if f6["pytest_ok"] else "NON OK",
         "`pytest -q` sui 5 file di test dei banchi", f6["pytest_out"]],
    ]
    A(md_table(["controllo", "esito", "comando", "evidenza"], rows))
    A("")
    A(f"**Verdetto di processo: {'MERGEABLE' if mergeable else 'NON MERGEABLE'}** — "
      + ("il contributo tocca solo `audit/`, non modifica `SoccerMath/` e i test dei banchi "
         "riusati passano; referto e script sono riproducibili con "
         "`python audit/totals_market_ceiling.py`. La CI (`Audit Top Mix`, "
         "`Replay Top Mix legacy`) si legge sulla pagina della PR."
         if mergeable else
         "esistono file fuori da `audit/` o test rossi: NON mergeare."))
    A("")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
def build_conformita(p) -> list:
    def pv(m, model):
        for v in p["verdicts"][m]:
            if v["modello"] == model:
                return v
        return None
    v_ou, v_gg = pv("OU2.5", "model_produzione"), pv("GG/NG", "model_produzione")
    v_ou_b = pv("OU2.5", "model_banco_PR34")
    v_gg_b = pv("GG/NG", "model_banco_PR34")
    diff_oc = [r for r in p["open_close"]["OU2.5"] if "− apertura" in r["confronto"]]
    f6 = p["evidenze"]["fatti"]
    cin = p["diagnostics"]["gg"].get("_sintesi") or {"n_righe": "-", "n_bet365": "-"}
    return [
        ["0. `git diff origin/main HEAD` vuoto all'inizio",
         "OK", "`git diff origin/main HEAD --stat`",
         "nessuna riga: branch allineato a `origin/main` (merge PR #40)"],
        ["0. venv pulito con `SoccerMath/requirements.txt` + `requirements-audit.txt`",
         "OK", "`python -m venv .venv && .venv/bin/pip install -r SoccerMath/requirements.txt "
         "-r requirements-audit.txt pytest`",
         "installazione exit 0 (scipy 1.17.1, statsmodels 0.15.0, scikit-learn 1.9.1 come da pin)"],
        ["0. probabilita' del modello riusate, non riscritte",
         "OK", "`from ppda_residual_test import production_totali`; "
         "`from backtest_experiment_all import run_walkforward`",
         "§0 del referto: due colonne dichiarate, con controllo incrociato "
         "|engine_gg − walk_forward_gg_predictions| = "
         f"{fmt0(p['diagnostics']['gg']['aggancio_modello'].get('Serie A', {}).get('scarto_engine_gg_vs_ggwalk'), 12)}"],
        ["1. O/U 2.5: apertura e chiusura B365 + Pinnacle",
         "OK", "`python audit/totals_market_ceiling.py`",
         "§1a: B365 apertura e chiusura presenti su tutte le righe; Pinnacle parziale"],
        ["1. GG/NG da `audit/data/*_btts.json`",
         "OK", "`python audit/totals_market_ceiling.py` (join del banco `gg_ng_calibration`)",
         f"{cin['n_righe']} righe incrociate su 2023/24-2025/26; bet365 in "
         f"{cin['n_bet365']}/{cin['n_righe']} righe"],
        ["1. Apertura/chiusura per GG/NG",
         "NON VERIFICABILE", "lettura dei campi `submarket_name`/`period` dei JSON",
         "un solo record per bookmaker, nessun campo temporale, nessun Pinnacle"],
        ["1. De-vig proporzionale E Shin, decisione sul proporzionale",
         "OK", "`python audit/totals_market_ceiling.py`",
         "§2b: entrambi riportati (Brier/LogLoss), la decisione usa il proporzionale"],
        ["1. Valutazione su 2024/25 e 2025/26, solo modello+quota",
         "OK", "`python audit/totals_market_ceiling.py`",
         "§1c/§2: n per lega e per fonte; nessuna imputazione"],
        ["1. Base rate del train come PR #34",
         "OK", "`from baserate_oos import raw as train_base_rate`",
         "funzione importata: stagioni precedenti a quella valutata, per lega"],
        ["2. Brier, LogLoss, reliability/resolution/uncertainty, BSS",
         "OK", "`from baserate_oos import decomp` (+ verifica `check_ok`)",
         "§2: scomposizione 10 bin identica alla PR #34; la verifica per blocchi "
         "riproduce `decomp` a meno di 1e-9 su ogni contrasto"],
        ["2. Differenze appaiate con bootstrap a blocchi, 2000 repliche, IC 95%",
         "OK", f"`python audit/totals_market_ceiling.py --reps {p['meta']['replicates']}`",
         f"§3: pooled e per lega; blocchi lega x stagione x giornata; seed {p['meta']['seed']}"],
        ["2. Chiusura contro apertura (stessa fonte, B365)",
         "OK" if diff_oc else "NON VERIFICABILE", "`python audit/totals_market_ceiling.py`",
         (f"§3b: Δ resolution(chiusura − apertura) = {fmt(diff_oc[0]['delta_resolution'])} "
          f"{ci_str(diff_oc[0]['delta_resolution_ci'])}; per GG/NG non verificabile"
          if diff_oc else "campione vuoto")],
        ["3. Inversione della P(Over) in lambda totale e dispersione di log lambda",
         "OK", "`python audit/totals_market_ceiling.py`",
         "§4: inversione esatta; scarto massimo lambda esplicito/invertito per lega riportato"],
        ["4. Encompassing rolling-origin con IC e ΔLogLoss fuori campione",
         "OK", "`python audit/totals_market_ceiling.py`",
         "§5: due fold per entrambe le colonne di modello, coefficienti con IC 95%"],
        ["4. Colonna del banco PR #34 stimata anche sul 2023/24",
         "OK", "`run_market_value_old` (train = sola 2022/23)",
         "il banco primario parte da 2024/25: per la stima su 2023/24 si usa la variante "
         "del banco, dichiarata in §5 e nei limiti"],
        ["5. Lettura fissata a priori applicata dal codice",
         "OK", "`CEILING_EPS = 0.002` + funzione `verdict()`",
         f"O/U 2.5 (produzione): {v_ou['verdetto'] if v_ou else '-'}; "
         f"O/U 2.5 (banco PR #34): {v_ou_b['verdetto'] if v_ou_b else '-'}; "
         f"GG/NG (produzione): {v_gg['verdetto'] if v_gg else '-'}; "
         f"GG/NG (banco PR #34): {v_gg_b['verdetto'] if v_gg_b else '-'}"],
        ["6. `git diff --name-only origin/main...HEAD` solo `audit/`",
         "OK" if f6["solo_audit"] else "NON OK",
         "`git diff --name-only origin/main HEAD` + `git status --porcelain`",
         (f"file toccati al momento della generazione: "
          f"{', '.join('`' + x + '`' for x in f6['file_toccati']) or '(nessuno)'}"
          + ("" if not f6["file_fuori_da_audit"] else
             f"; FUORI da `audit/`: {', '.join(f6['file_fuori_da_audit'])}"))],
        ["6. CI di Audit e Replay su push e pull_request",
         "OK" if f6["pytest_ok"] else "NON OK",
         "`.github/workflows/topmix_audit.yml`, `.github/workflows/replay_legacy_topmix.yml`; "
         "`gh pr checks` sulla PR",
         (f"i due workflow si attivano su push `arena/**` e su pull_request verso `main` "
          f"(letti dal repo); test locali dei banchi riusati: {f6['pytest_out']}")],
    ]


def build_limiti() -> list:
    return [
        "Le quote Over/Under 2.5 arrivano dai CSV football-data del repo: `B365*` e' il prezzo "
        "registrato dal provider come apertura, `B365C*`/`PC*` la chiusura. Non c'e' un "
        "timestamp della singola quotazione: \"apertura\" e \"chiusura\" valgono come etichette "
        "del provider, non come istanti verificati nel repo.",
        "Le quote GG/NG sono un SINGOLO snapshot Oddsportal per partita (un record per "
        "bookmaker, nessun campo temporale): per GG/NG il confronto chiusura-contro-apertura e' "
        "NON VERIFICABILE e non esiste una fonte Pinnacle. Per le 43 righe senza bet365 usabile "
        "il banco GG prende il primo bookmaker disponibile (fallback dichiarato riga per riga).",
        "La copertura Pinnacle (chiusura) e' parziale nel 2025/26: le metriche di quella fonte "
        "sono calcolate sul suo campione (riportato) e le differenze appaiate solo sulle righe "
        "in cui la quota esiste.",
        "Il base rate del train e' calcolato su TUTTE le righe dei CSV delle stagioni "
        "precedenti (nessuna esclusione), esattamente come `baserate_oos.raw` nella PR #34.",
        "La scomposizione di Murphy usa 10 bin di ampiezza uguale su [0,1] e la resolution con "
        "riferimento la frequenza media del campione: e' `baserate_oos.decomp`, quindi i valori "
        "non sono confrontabili con scomposizioni a bin diversi.",
        "La giornata non esiste nei CSV football-data: il blocco del bootstrap e' la DATA della "
        "partita (stessa scelta dei banchi PR #34 e PR #39), non il turno di campionato.",
        "La regressione encompassing ha due regressori: non esplora interazioni, non contiene "
        "il fattore campo ne' altre fonti, e la combinazione e' stimata senza vincoli "
        "(i coefficienti possono essere entrambi positivi per collinearita' fra modello e "
        "mercato).",
        "Il banco PR #34 (`run_walkforward`) non produce previsioni per il 2023/24, stagione "
        "richiesta dal protocollo di stima: per quella colonna l'encompassing usa "
        "`run_market_value_old` (train = sola 2022/23), dichiarato in §5. La colonna di "
        "produzione non ha questo problema: `production_totali` copre tutte le stagioni.",
        "Le due colonne di modello sono banchi DIFFERENTI con fonti diverse (produzione: xG "
        "F_season con shrinkage; banco: medie gol walk-forward): i loro valori non sono "
        "sostituibili fra loro e sono riportati separatamente.",
    ]


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=DEFAULT_REPS)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--no-write", action="store_true",
                    help="calcola senza scrivere referto/JSON/CSV")
    ap.add_argument("--refresh-evidenze", action="store_true",
                    help="rigenera SOLO la sezione 9 (comandi e output) dal payload gia' "
                         "scritto: serve dopo il commit, quando il diff e' quello finale. "
                         "Non ricalcola nessun numero")
    args = ap.parse_args(argv)

    if args.refresh_evidenze:
        if not os.path.exists(OUT_JSON):
            print(f"[!] {os.path.relpath(OUT_JSON, _REPO_ROOT)} non esiste: "
                  f"esegui prima la run completa")
            return 2
        with open(OUT_JSON, encoding="utf-8") as fh:
            payload = json.load(fh)
        comandi = payload.get("evidenze", {}).get("comandi", [])
        log_run = comandi[-1][1] if comandi else ""
        fresh = build_evidenze([], False)
        etichetta = fresh["comandi"][-1][0]
        fresh["comandi"][-1] = (etichetta, log_run + "\n(sezione rigenerata dopo il commit: "
                                "i numeri del referto NON sono stati ricalcolati)")
        payload["evidenze"] = fresh
        payload["meta"]["evidenze_aggiornate_at"] = datetime.now(
            timezone.utc).isoformat(timespec="seconds")
        payload["conformita"] = build_conformita(payload)
        with open(OUT_JSON, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1, default=str)
        with open(OUT_MD, "w", encoding="utf-8") as fh:
            fh.write(render_report(payload))
        print("[i] evidenze rigenerate in "
              + ", ".join(os.path.relpath(x, _REPO_ROOT) for x in (OUT_MD, OUT_JSON)))
        return 0

    if os.path.abspath(os.getcwd()) != _REPO_ROOT:
        print(f"[i] cwd -> {_REPO_ROOT} (baserate_oos.raw legge percorsi relativi)")
        os.chdir(_REPO_ROOT)
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()

    def log(msg):
        line = f"[{time.time() - t0:7.1f}s] {msg}"
        _ESECUZIONE_LOG.append(line)
        print(line, flush=True)

    def git(*cmd):
        try:
            return subprocess.run(["git", *cmd], capture_output=True, text=True,
                                  cwd=_REPO_ROOT, check=False).stdout.strip()
        except OSError:
            return ""

    payload = {"meta": {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": git("rev-parse", "HEAD"),
        "commit_subject": git("log", "-1", "--pretty=%s"),
        "replicates": args.reps, "seed": args.seed, "bins": BINS,
        "ceiling_eps": CEILING_EPS, "eval_seasons": list(EVAL_SEASONS),
        "base_rate": "baserate_oos.raw (base rate del train per lega)",
        "devig_decision": "proporzionale", "devig_reported": ["proporzionale", "Shin"],
    }, "diagnostics": {}}

    log("cornice O/U: production_totali + run_walkforward + variante + quote …")
    ou, ou_diag = build_ou_frame()
    payload["diagnostics"]["ou"] = ou_diag
    log(f"  righe {len(ou)}; stagioni {sorted(ou['season'].unique())}")

    log("cornice GG/NG: join Oddsportal + walk-forward di produzione …")
    gg, gg_diag = build_gg_frame(ou)
    payload["diagnostics"]["gg"] = gg_diag
    log(f"  righe incrociate {len(gg)}")

    log("sonda F_season: su quali giornate la fonte non e' attiva (ramo divergente) …")
    payload["diagnostics"]["fs_season"] = {
        league: fs_season_probe(prefix, league) for prefix, league in LEAGUES}
    fs_inactive = {(lg, season, date)
                   for lg, r in payload["diagnostics"]["fs_season"].items()
                   for season, date in r["date_fs_non_attiva"]}
    log(f"  coppie (stagione, giornata) con F_season non attiva: {len(fs_inactive)}")

    cov = []
    for prefix, league in LEAGUES:
        c = coverage_ou(prefix)
        c.insert(0, "league", league)
        cov.append(c)
    payload["coverage"] = {
        "ou": pd.concat(cov, ignore_index=True).to_dict(orient="records"),
        "gg": {lg: seasons for lg, seasons in gg_diag.items() if lg != "aggancio_modello"},
    }

    bases = {"OU2.5": {}, "GG/NG": {}}
    for season in EVAL_SEASONS:
        for prefix, league in LEAGUES:
            raw = train_base_rate(prefix, int(season.split("/")[0]))
            bases["OU2.5"][(league, season)] = float(raw["OU2.5"].mean())
            bases["GG/NG"][(league, season)] = float(raw["GG/NG"].mean())

    d_ou = market_frame(ou, gg, "OU2.5")
    d_gg = market_frame(ou, gg, "GG/NG")
    # l'encompassing stima sul 2023/24 (richiesto dal protocollo): serve una cornice
    # che includa anche quella stagione, oltre alle due di valutazione
    enc_ou = market_frame(ou, gg, "OU2.5", ("2023/24",) + EVAL_SEASONS)
    enc_gg = market_frame(ou, gg, "GG/NG", ("2023/24",) + EVAL_SEASONS)
    for d in (d_ou, d_gg, enc_ou, enc_gg):
        d["fs_non_attiva"] = [(lg, s_, str(g_)[:10]) in fs_inactive for lg, s_, g_ in
                              zip(d["league"], d["season"], d["date_day"])]
    src_ou = OrderedDict([
        ("model_produzione", "model_produzione"),
        ("model_banco_PR34", "model_banco_PR34"),
        ("mercato_apertura_b365", "mercato_apertura_b365"),
        ("mercato_chiusura_b365", "mercato_chiusura_b365"),
        ("mercato_chiusura_pinnacle", "mercato_chiusura_pinnacle"),
    ])
    src_gg = OrderedDict([
        ("model_produzione", "model_produzione"),
        ("model_produzione_banco_GG", "model_produzione_banco_GG"),
        ("model_banco_PR34", "model_banco_PR34"),
        ("mercato_btts_oddsportal", "mercato_gg_oddsportal"),
    ])
    payload["sample_sizes"] = {
        m: {name: {lg: int(g[col].notna().sum())
                   for lg, g in d.groupby("league", sort=True)}
            for name, col in srcs.items()}
        for m, d, srcs in (("OU2.5", d_ou, src_ou), ("GG/NG", d_gg, src_gg))}

    log("metriche per fonte …")
    payload["metrics"] = {}
    for m, d, srcs in (("OU2.5", d_ou, src_ou), ("GG/NG", d_gg, src_gg)):
        pooled = evaluate_sources(d, srcs, bases[m])
        per_league = {lg: evaluate_sources(g, srcs, bases[m])
                      for lg, g in d.groupby("league", sort=True)}
        payload["metrics"][m] = {"pooled": pooled.to_dict(orient="records"),
                                 "per_league": {lg: r.to_dict(orient="records")
                                                for lg, r in per_league.items()}}

    log("de-vig Shin …")
    payload["shin"] = {}
    for m, d, pairs in (("OU2.5", d_ou,
                         [(s, f"mercato_{s}", f"mercato_{s}_shin") for s in SOURCES]),
                        ("GG/NG", d_gg,
                         [("btts_oddsportal", "mercato_gg_oddsportal",
                           "mercato_gg_oddsportal_shin")])):
        rows = []
        for name, pc, sc in pairs:
            sel = d[d[pc].notna() & d[sc].notna()]
            if sel.empty:
                continue
            y = sel["y"].to_numpy(float)
            p_prop, p_shin = sel[pc].to_numpy(float), sel[sc].to_numpy(float)
            if m == "OU2.5":
                oc, uc = OU_SOURCES[name]
                ov = float((1.0 / sel[oc] + 1.0 / sel[uc]).mean())
                z = float(np.nanmean(sel[f"zshin__{name}"].to_numpy(float)))
            else:
                ov = float((1.0 / sel["o_yes"] + 1.0 / sel["o_no"]).mean())
                z = float(np.nanmean(sel["zshin_gg"].to_numpy(float)))
            rows.append({"fonte": name, "n": int(len(sel)),
                         "brier": brier(y, p_prop), "logloss": logloss(y, p_prop),
                         "brier_shin": brier(y, p_shin), "logloss_shin": logloss(y, p_shin),
                         "delta_brier_shin_menu_prop": brier(y, p_shin) - brier(y, p_prop),
                         "delta_logloss_shin_menu_prop": logloss(y, p_shin) - logloss(y, p_prop),
                         "z_shin_medio": z, "overround_medio": ov,
                         "media_p_prop": float(np.mean(p_prop)),
                         "media_p_shin": float(np.mean(p_shin))})
        payload["shin"][m] = rows

    contrasts = {
        "OU2.5": OrderedDict([
            ("chiusura B365 − modello produzione", ("mercato_chiusura_b365", "model_produzione")),
            ("chiusura B365 − modello banco PR34", ("mercato_chiusura_b365", "model_banco_PR34")),
            ("apertura B365 − modello produzione", ("mercato_apertura_b365", "model_produzione")),
            ("apertura B365 − modello banco PR34", ("mercato_apertura_b365", "model_banco_PR34")),
            ("chiusura Pinnacle − modello produzione", ("mercato_chiusura_pinnacle",
                                                        "model_produzione")),
            ("chiusura B365 − apertura B365", ("mercato_chiusura_b365", "mercato_apertura_b365")),
        ]),
        "GG/NG": OrderedDict([
            ("mercato BTTS − modello produzione", ("mercato_gg_oddsportal", "model_produzione")),
            ("mercato BTTS − modello banco GG", ("mercato_gg_oddsportal",
                                                 "model_produzione_banco_GG")),
            ("mercato BTTS − modello banco PR34", ("mercato_gg_oddsportal", "model_banco_PR34")),
        ]),
    }
    log("bootstrap a blocchi (differenze appaiate) …")
    payload["diffs"] = {}
    payload["open_close"] = {}
    for m, d in (("OU2.5", d_ou), ("GG/NG", d_gg)):
        payload["diffs"][m] = {"pooled": [], "per_league": {}, "per_league_others": {}}
        for label, (a, b) in contrasts[m].items():
            rec = paired_diff(d, a, b, args.reps, args.seed)
            rec["contrasto"] = label
            payload["diffs"][m]["pooled"].append(rec)
        main_a, main_b = (("mercato_chiusura_b365", "model_produzione") if m == "OU2.5"
                          else ("mercato_gg_oddsportal", "model_produzione"))
        for lg, g in d.groupby("league", sort=True):
            payload["diffs"][m]["per_league"][lg] = paired_diff(
                g, main_a, main_b, args.reps, args.seed)
        for label, (a, b) in contrasts[m].items():
            per = {}
            for lg, g in d.groupby("league", sort=True):
                sub = g[g[a].notna() & g[b].notna()]
                per[lg] = (None if len(sub) < 10
                           else paired_diff(g, a, b, args.reps, args.seed))
            payload["diffs"][m]["per_league_others"][label] = per
        oc = []
        if m == "OU2.5":
            for label, a, b in (("chiusura − apertura (B365)", "mercato_chiusura_b365",
                                 "mercato_apertura_b365"),
                                ("chiusura − modello (B365)", "mercato_chiusura_b365",
                                 "model_produzione"),
                                ("apertura − modello (B365)", "mercato_apertura_b365",
                                 "model_produzione")):
                rec = paired_diff(d, a, b, args.reps, args.seed)
                rec["confronto"] = label
                oc.append(rec)
        else:
            oc.append({"confronto": "NON VERIFICABILE: i file BTTS non hanno quote di "
                                    "apertura/chiusura", "n": 0, "delta_resolution": None,
                       "delta_resolution_ci": None, "ci_excludes_zero_resolution": False,
                       "delta_logloss": None, "delta_logloss_ci": None})
        payload["open_close"][m] = oc

    log("dispersione dei lambda …")
    payload["lambda_dispersion"] = lambda_dispersion(d_ou)

    log("regressione encompassing …")
    payload["encompassing"] = {}
    enc_defs = {
        "OU2.5": [("model_produzione", "mercato_chiusura_b365"),
                  ("model_banco_PR34_variante", "mercato_chiusura_b365")],
        "GG/NG": [("model_produzione", "mercato_gg_oddsportal"),
                  ("model_banco_PR34_variante", "mercato_gg_oddsportal")],
    }
    for m, d in (("OU2.5", enc_ou), ("GG/NG", enc_gg)):
        payload["encompassing"][m] = {
            model_col: encompassing(d, m, model_col, market_col, args.reps, args.seed)
            for model_col, market_col in enc_defs[m]}

    log("verdetti …")
    payload["verdicts"] = {}
    payload["verdicts_speculari"] = {}
    for m in MARKETS:
        rows = []
        for rec in payload["diffs"][m]["pooled"]:
            token = any(t in rec["source_a"] for t in VERDICT_MARKET_TOKENS[m])
            if not (token and rec["source_b"].startswith("model_")):
                continue
            v = verdict(rec)
            v.update({"modello": rec["source_b"], "fonte_mercato": rec["source_a"]})
            rows.append(v)
        payload["verdicts"][m] = rows
        # lettura speculare: stessa regola applicata a (modello − mercato)
        spec = {}
        for rec in payload["diffs"][m]["pooled"]:
            token = any(t in rec["source_a"] for t in VERDICT_MARKET_TOKENS[m])
            if not (token and rec["source_b"].startswith("model_")):
                continue
            flipped = dict(rec)
            flipped["delta_resolution"] = -rec["delta_resolution"]
            flipped["resolution_a"] = rec["resolution_b"]
            flipped["resolution_b"] = rec["resolution_a"]
            flipped["ci"] = [-rec["delta_resolution_ci"][1], -rec["delta_resolution_ci"][0]]
            flipped["ci_excludes_zero_resolution"] = rec["ci_excludes_zero_resolution"]
            # chiave STRINGA: il payload finisce in JSON (le chiavi tupla non sono valide)
            spec[f"{rec['source_b']}||{rec['source_a']}"] = verdict(flipped)
        payload["verdicts_speculari"][m] = spec

    log("sensibilita': senza le righe con F_season non attiva …")
    payload["sensitivity_fs"] = {}
    for m, d, srcs in (("OU2.5", d_ou, src_ou), ("GG/NG", d_gg, src_gg)):
        red = d[~d["fs_non_attiva"]]
        a, b = (("mercato_chiusura_b365", "model_produzione") if m == "OU2.5"
                else ("mercato_gg_oddsportal", "model_produzione"))
        rec = paired_diff(red, a, b, args.reps, args.seed)
        rec["contrasto"] = f"{a} − {b}"
        payload["sensitivity_fs"][m] = {
            "n_righe_totali": int(len(d)),
            "n_righe_escluse_fs_non_attiva": int(d["fs_non_attiva"].sum()),
            "n_righe_ridotte": int(len(red)),
            "per_lega_escluse": {lg: int(g["fs_non_attiva"].sum())
                                 for lg, g in d.groupby("league", sort=True)},
            "metrics": evaluate_sources(red, srcs, bases[m]).to_dict(orient="records"),
            "contrasto": rec,
        }

    # referto ed evidenze si costruiscono SEMPRE (anche in dry-run): cosi' la prova
    # rapida valida esattamente cio' che finira' nel referto
    rows_df = build_rows_table(ou, gg)
    payload["outputs"] = {
        "audit/output/totals_market_ceiling_rows.csv": f"{len(rows_df)} righe partita per "
        "partita (tutte le fonti e le quote)",
        "audit/output/totals_market_ceiling.json": "payload completo di questa esecuzione",
    }
    payload["evidenze"] = build_evidenze(_ESECUZIONE_LOG, args.no_write)
    payload["conformita"] = build_conformita(payload)
    payload["limiti"] = build_limiti()
    markdown = render_report(payload)

    if args.no_write:
        with open("/tmp/totals_market_ceiling_dry.json", "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1, default=str)
        with open("/tmp/totals_market_ceiling_dry.md", "w", encoding="utf-8") as fh:
            fh.write(markdown)
        log("dry-run: nessun file scritto (payload e referto in /tmp/totals_market_ceiling_dry.*)")
    else:
        rows_df.to_csv(OUT_ROWS, index=False)
        with open(OUT_JSON, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1, default=str)
        with open(OUT_MD, "w", encoding="utf-8") as fh:
            fh.write(markdown)
        log("scritti " + ", ".join(os.path.relpath(x, _REPO_ROOT)
                                   for x in (OUT_MD, OUT_JSON, OUT_ROWS)))

    print("")
    for m in MARKETS:
        print(f"=== {m} ===")
        for v in payload["verdicts"][m]:
            print(f"  modello={v['modello']:<30} fonte={v['fonte_mercato']:<24} "
                  f"Δres={v['delta_resolution']:+.5f} "
                  f"IC={ci_str(v['ci'])} -> {v['verdetto']} ({v['motivo']})")
    return 0


def build_rows_table(ou: pd.DataFrame, gg: pd.DataFrame) -> pd.DataFrame:
    """Tabella lunga partita per partita (output pesante, non versionato)."""
    o = ou[["league", "season", "date_day", "home", "away", "y_over", "y_gg",
            "p_model_prod", "p_model_bench", "p_model_benchvar", "p_model_prod_gg",
            "p_model_bench_gg", "lambda_total"] + OU_ODDS_COLS].copy()
    o["mercato"] = "OU2.5"
    o["y"] = o["y_over"]
    o["p_modello_produzione"] = o["p_model_prod"]
    o["p_modello_banco_PR34"] = o["p_model_bench"]
    o["p_modello_banco_PR34_variante"] = o["p_model_benchvar"]
    o["p_modello_produzione_gg"] = o["p_model_prod_gg"]
    o["p_modello_banco_PR34_gg"] = o["p_model_bench_gg"]
    o["lambda_totale_modello"] = o["lambda_total"]
    for s in SOURCES:
        o[f"p_mercato_{s}"] = ou[f"p__{s}"].values
        o[f"p_mercato_{s}_shin"] = ou[f"shin__{s}"].values
    o["data"] = o["date_day"]

    g = gg[["league", "season", "date_day", "home", "away", "y_gg", "bookmaker",
            "fallback", "o_yes", "o_no", "p_market_gg", "p_market_gg_shin",
            "engine_gg", "p_model_prod_ggwalk", "p_model_bench_gg"]].copy()
    g["mercato"] = "GG/NG"
    g["y"] = g["y_gg"]
    g["p_modello_produzione"] = g["engine_gg"]
    g["p_modello_banco_PR34"] = g["p_model_bench_gg"]
    g["p_modello_produzione_ggwalk"] = g["p_model_prod_ggwalk"]
    g["p_mercato_btts_oddsportal"] = g["p_market_gg"]
    g["p_mercato_btts_oddsportal_shin"] = g["p_market_gg_shin"]
    g["data"] = g["date_day"]
    keep = (["mercato", "league", "season", "data", "home", "away", "y",
             "p_modello_produzione", "p_modello_banco_PR34",
             "p_modello_banco_PR34_variante", "lambda_totale_modello",
             "p_mercato_apertura_b365", "p_mercato_chiusura_b365",
             "p_mercato_chiusura_pinnacle", "p_mercato_apertura_b365_shin",
             "p_mercato_chiusura_b365_shin", "p_mercato_chiusura_pinnacle_shin",
             "p_mercato_btts_oddsportal", "p_mercato_btts_oddsportal_shin",
             "p_modello_produzione_gg", "p_modello_banco_PR34_gg",
             "p_modello_produzione_ggwalk", "bookmaker", "fallback",
             "B365>2.5", "B365<2.5", "B365C>2.5", "B365C<2.5", "PC>2.5", "PC<2.5",
             "o_yes", "o_no"])
    return pd.concat([o, g], ignore_index=True, sort=False)[keep]


if __name__ == "__main__":
    raise SystemExit(main())
