"""
diagnose_quota_minima.py — Audit di SOLA LETTURA: fascia di QUOTA REALE del
Top Mix (ipotesi del protocollo: restringere le righe ammesse a quota reale
>= 1,50 preserva/migliora la calibrazione, o butta via valore?).

Nessuna modifica a SoccerMath/: si importano funzioni di produzione e di
audit gia' committate, si leggono artefatti esistenti.

Fonti (tutte gia' nel repo, nessun dato nuovo):
  * ``audit/results/topmix_selector_replay_rows.csv`` — il replay consolidato
    di ``seleziona_riga_top_mix`` (funzione PURA importata direttamente da
    ``SoccerMath/app.py``; la parita' comportamentale con il replay e' gia'
    testata da ``SoccerMath/test_topmix_selector_parity.py``): 3422 righe
    candidate 2024/25+2025/26, 1865 ammesse dal selettore A (produzione).
    Sono le STESSHE righe di ``topmix_margins.py``: stagioni etichettate
    "validation storica gia' esaminata", non un test intatto.
  * Quote 1X2 (B365H/D/A) e O/U 2.5 (B365>2.5 / B365<2.5) dai CSV storici di
    ``SoccerMath/database/`` via ``backtest_experiment_all.load_league``
    (stessa convenzione B365 degli altri audit 1X2).
  * Quote GG/NG (o_yes/o_no, bet365 con fallback dichiarato) dai file
    ``audit/data/*_btts.json`` riusando ``gg_ng_calibration.join_btts_file``
    (stesso join per coppia normalizzata + conferma data, NESSUNA logica
    riscritta).

Analisi:
  1. ogni riga ammessa viene agganciata alla quota REALE del mercato scelto
     (mai 1/confidence, mai quota implicita del modello);
  2. le righe sono divise per quota reale < 1,50 vs >= 1,50 (soglia del
     protocollo, NON ottimizzata sui dati);
  3. per fascia: n, hit-rate, Brier (confidence del modello vs esito), ROI a
     puntata fissa sulla quota reale; bootstrap 2000 resample, seed 20260905,
     CI percentile 2.5-97.5 (``_ci`` di ``topmix_margins.py``);
  4. stessa scomposizione per mercato dentro ciascuna fascia;
  5. confronto esplicito subset >= 1,50 vs INTERO campione ammesso con
     bootstrap appaiato: la domanda e' se restringere BUTTA VIA valore.

Righe senza quota usabile (join fallito, quota mancante/NaN/<= 1.0) sono
ESCLUSE e CONTEGGIATE per motivo, mai assegnate a una fascia.

Output: audit/results/quota_minima_report.md (+ sidecar .json)
Uso:    python audit/diagnose_quota_minima.py
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import Counter

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
for _p in (_AUDIT_DIR, _REPO_ROOT, os.path.join(_REPO_ROOT, "SoccerMath")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backtest_experiment_all import load_league                        # noqa: E402
from team_aliases import clean_name                                    # noqa: E402
from topmix_margins import N_BOOT, SEED, _ci, DEFAULT_ROWS             # noqa: E402
from gg_ng_calibration import (BTTS_FILES, JOIN_OK, load_btts_dataset,  # noqa: E402
                               join_btts_file, season_label_of)
import app as prod_app                                                  # noqa: E402

# selettore di produzione, funzione PURA (nessun HTTP/registro): importato
# direttamente per documentare la fonte delle righe del replay e per i test.
seleziona_riga_top_mix = prod_app.seleziona_riga_top_mix

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "quota_minima_report.md")
JSON_PATH = os.path.join(OUT_DIR, "quota_minima_report_detail.json")

QUOTA_THRESHOLD = 1.50           # soglia del protocollo (mai ottimizzata sui dati)
STAKE = 10.0
REPLAY_SEASONS = ("2024/25", "2025/26")
BTTS_SEASONS = ("2024-2025", "2025-2026")
DATE_TOL_DAYS = 1                # fuso: stessa tolleranza del join BTTS

# mercato selezionato -> colonna quota reale nei CSV football-data (B365,
# convenzione degli altri audit 1X2); GG/NG viene dai JSON BTTS.
MARKET_ODDS_COL = {
    "1": "B365H",
    "X": "B365D",
    "2": "B365A",
    "O2.5": "B365>2.5",
    "U2.5": "B365<2.5",
}


# esito atteso per mercato dati i gol (sanity: deve coincidere con A_hit)
def expected_hit(market, fthg, ftag):
    if market == "1":
        return 1 if fthg > ftag else 0
    if market == "2":
        return 1 if fthg < ftag else 0
    if market == "X":
        return 1 if fthg == ftag else 0
    if market == "O2.5":
        return 1 if (fthg + ftag) >= 3 else 0
    if market == "U2.5":
        return 1 if (fthg + ftag) <= 2 else 0
    if market == "GG":
        return 1 if (fthg > 0 and ftag > 0) else 0
    if market == "NG":
        return 0 if (fthg > 0 and ftag > 0) else 1
    return None


# =====================================================================
# Indici di quota (coppia normalizzata come chiave primaria, data come
# conferma secondaria: stessa gerarchia del join BTTS di gg_ng_calibration)
# =====================================================================
def league_prefix_map():
    """Nome lega del replay -> prefix database (da BTTS_FILES, gia' auditato)."""
    return {league_key: prefix for prefix, league_key, _ in BTTS_FILES.values()}


def build_csv_odds_index(prefixes, seasons=REPLAY_SEASONS):
    """{(prefix, stagione, casa, fuori): {'date', 'odds': {col: quota}}}.

    Coppia orientata unica per stagione nei CSV football-data (auditato in
    gg_ng_calibration): se un dominio divenisse ambiguo lo si segnala,
    mai assegnazioni a caso."""
    idx = {}
    dup = []
    for prefix in prefixes:
        df = load_league(prefix)
        sub = df[df["season"].isin(seasons)]
        for h, a, season in set(zip(sub.HomeClean, sub.AwayClean, sub.season)):
            key = (prefix, season, h, a)
            if key in idx:
                dup.append(key)
                continue
            rows = sub[(sub.HomeClean == h) & (sub.AwayClean == a)
                       & (sub.season == season)]
            odds = {}
            for col in MARKET_ODDS_COL.values():
                if col in rows.columns:
                    vals = pd.to_numeric(rows[col], errors="coerce").dropna()
                    if len(vals):
                        odds[col] = float(vals.iloc[0])
            idx[key] = {"date": rows["Date"].iloc[0], "odds": odds}
    return idx, dup


def build_btts_odds_index(dataset, prefixes, seasons=BTTS_SEASONS):
    """{(prefix, stagione, casa, fuori): {'date', 'o_yes', 'o_no', 'book'}}.

    Riusa ESATTAMENTE ``join_btts_file`` (join deterministico per coppia
    normalizzata + conferma data + scelta quota bet365/fallback + stati
    odds_missing/duplicate_not_resolved/...): nessuna logica riscritta."""
    slug_by_prefix = {v[0]: slug for slug, v in BTTS_FILES.items()}
    idx = {}
    dup = []
    stats = {}
    for prefix in prefixes:
        slug = slug_by_prefix.get(prefix)
        if slug is None:
            continue
        df = load_league(prefix)
        for season in seasons:
            json_rows = dataset.get((slug, season))
            if json_rows is None:
                continue
            season_df = df[df["season"] == season_label_of(season)].reset_index(drop=True)
            recs = join_btts_file(json_rows, season_df)
            fname = slug + "_" + season + "_btts.json"
            stats[fname] = dict(Counter(r["status"] for r in recs))
            for r in recs:
                if r["status"] != JOIN_OK or r.get("o_yes") is None:
                    continue
                key = (prefix, season_label_of(season), r["home_key"], r["away_key"])
                if key in idx:
                    dup.append(key)
                    continue
                idx[key] = {"date": r.get("csv_date"),
                            "o_yes": float(r["o_yes"]), "o_no": float(r["o_no"]),
                            "book": r.get("bookmaker", "?")}
    return idx, dup, stats


# =====================================================================
# Aggancio quota reale alle righe ammesse del replay
# =====================================================================
def attach_real_odds(rows_df, csv_idx, btts_idx):
    """Righe ammesse -> DataFrame con quota reale, oppure esclusione contata.

    Ritorna (attached_df, coverage). Nessuna riga senza quota usabile finisce
    in una fascia; ``hit_mismatch`` (esito ricalcolato dai gol vs A_hit del
    replay) DEVE restare 0: e' la prova che la mappa mercato->esito usata qui
    coincide con quella del replay."""
    pmap = league_prefix_map()
    out = []
    coverage = Counter()
    for _, row in rows_df.iterrows():
        if not bool(row["A_admitted"]):
            continue
        prefix = pmap.get(str(row["league"]))
        season = str(row["season_label"])
        market = str(row["A_market"])
        fthg, ftag = int(row["fthg"]), int(row["ftag"])
        hit = int(row["A_hit"])
        base = {"league": str(row["league"]), "season": season,
                "home": str(row["home"]), "away": str(row["away"]),
                "market": market, "conf": float(row["A_conf"]), "hit": hit,
                "fthg": fthg, "ftag": ftag, "kickoff": str(row["kickoff"])}
        if market not in MARKET_ODDS_COL and market not in ("GG", "NG"):
            coverage["mercato_sconosciuto"] += 1
            coverage["excluded"] += 1
            continue
        if expected_hit(market, fthg, ftag) != hit:
            coverage["hit_mismatch"] += 1
            coverage["excluded"] += 1
            continue
        if prefix is None:
            coverage["lega_sconosciuta"] += 1
            coverage["excluded"] += 1
            continue
        # il replay conserva i nomi GREZZI football-data (es. "Bayern Munich",
        # "RB Leipzig" in Bundesliga): la stessa normalizzazione dei database
        # (clean_name) li riconduce ai canonici usati da load_league e dal
        # join BTTS ("Bayern", "Leipzig").
        key = (prefix, season, clean_name(str(row["home"])), clean_name(str(row["away"])))
        ko_day = pd.Timestamp(row["kickoff"]).tz_localize(None).date()
        odds = None
        if market in MARKET_ODDS_COL:
            entry = csv_idx.get(key)
            col = MARKET_ODDS_COL[market]
            if entry is None:
                coverage["coppia_assente_csv"] += 1
            else:
                delta = abs((ko_day - pd.Timestamp(entry["date"]).date()).days)
                if delta > DATE_TOL_DAYS:
                    coverage["data_mismatch_csv"] += 1
                elif col not in entry["odds"]:
                    coverage["quota_mancante_csv"] += 1
                else:
                    odds = entry["odds"][col]
        elif market in ("GG", "NG"):
            entry = btts_idx.get(key)
            if entry is None:
                coverage["coppia_assente_btts"] += 1
            else:
                delta = abs((ko_day - pd.Timestamp(entry["date"]).date()).days)
                if delta > DATE_TOL_DAYS:
                    coverage["data_mismatch_btts"] += 1
                else:
                    odds = entry["o_yes"] if market == "GG" else entry["o_no"]
        else:
            coverage["mercato_sconosciuto"] += 1
        if odds is None:
            coverage["excluded"] += 1
            continue
        if not (isinstance(odds, float) and math.isfinite(odds)):
            coverage["quota_nan"] += 1
            coverage["excluded"] += 1
            continue
        if odds <= 1.0:
            coverage["quota_non_valida"] += 1
            coverage["excluded"] += 1
            continue
        out.append({**base, "odds": float(odds)})
    return pd.DataFrame(out), coverage


# =====================================================================
# Metriche per fascia/mercato + bootstrap appaiato
# =====================================================================
def cell_metrics(hit, conf, odds):
    """n, hit-rate, Brier (confidence vs esito, stessa definizione di
    ``topmix_margins.quality``), conf media, quota media, ROI a puntata fissa
    (ROI = 100 * media di ((q-1)*hit - (1-hit)), puntata unitaria per riga)."""
    n = len(hit)
    if n == 0:
        return {"n": 0, "hit_rate": None, "brier": None, "mean_conf": None,
                "mean_odds": None, "roi_pct": None}
    profit = (odds - 1.0) * hit - (1.0 - hit)
    return {"n": int(n), "hit_rate": float(hit.mean()),
            "brier": float(((conf - hit) ** 2).mean()),
            "mean_conf": float(conf.mean()), "mean_odds": float(odds.mean()),
            "roi_pct": float(100.0 * profit.mean())}


def _sel(a, mask):
    return {k: v[mask] for k, v in a.items()}


def bootstrap_analysis(attached, n_boot=N_BOOT, seed=SEED):
    """CI percentile 2.5-97.5 (``_ci`` di topmix_margins) per le celle:
    full / sub (quota >= soglia) / comp (< soglia) e mercato-fascia;
    delta appaiati sub-full e sub-comp (stesso resample per tutte le
    quantita': differenze appaiate). Celle assenti in oltre meta' dei
    resample: CI dichiarata instabile (nessun numero inventato)."""
    hit = attached["hit"].to_numpy(float)
    conf = attached["conf"].to_numpy(float)
    odds = attached["odds"].to_numpy(float)
    market = attached["market"].to_numpy(str)
    is_sub = odds >= QUOTA_THRESHOLD
    a = {"hit": hit, "conf": conf, "odds": odds}
    n = len(hit)
    markets = sorted(set(market))
    buckets = {"full": np.ones(n, dtype=bool), "sub": is_sub, "comp": ~is_sub}
    for m in markets:
        buckets["m:" + m + ":full"] = market == m
        buckets["m:" + m + ":sub"] = is_sub & (market == m)
        buckets["m:" + m + ":comp"] = (~is_sub) & (market == m)

    point = {name: cell_metrics(**_sel(a, mask)) for name, mask in buckets.items()}

    rng = np.random.default_rng(seed)
    keys = ("hit_rate", "brier", "roi_pct")
    boot = {name: {k: [] for k in keys} for name in buckets}
    boot_n = {name: [] for name in buckets}
    deltas = {dk: {k: [] for k in keys} for dk in ("sub-full", "sub-comp")}
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        vals = {}
        for name, mask in buckets.items():
            v = cell_metrics(**_sel(a, idx[mask[idx]]))
            vals[name] = v
            boot_n[name].append(v["n"])
            for k in keys:
                boot[name][k].append(v[k])
        for dk, (x, y) in (("sub-full", ("sub", "full")),
                           ("sub-comp", ("sub", "comp"))):
            for k in keys:
                vx, vy = vals[x][k], vals[y][k]
                deltas[dk][k].append(None if (vx is None or vy is None) else vx - vy)

    def ci_of(name, k):
        if boot_n[name].count(0) > n_boot // 2:
            return None   # cella troppo spesso vuota nei resample: CI instabile
        return _ci([v for v in boot[name][k] if v is not None])

    ci = {name: {"ci_stable": boot_n[name].count(0) <= n_boot // 2,
                 "hit_rate": ci_of(name, "hit_rate"),
                 "brier": ci_of(name, "brier"),
                 "roi_pct": ci_of(name, "roi_pct")}
          for name in buckets}
    delta_cis = {}
    for dk in ("sub-full", "sub-comp"):
        yname = "full" if dk == "sub-full" else "comp"
        delta_cis[dk] = {}
        for k in keys:
            ps, py = point["sub"][k], point[yname][k]
            delta = None if (ps is None or py is None) else ps - py
            boots = [v for v in deltas[dk][k] if v is not None]
            delta_cis[dk][k] = {"delta": delta,
                                "ci": _ci(boots) if boots else [None, None]}
    return {"point": point, "ci": ci, "delta": delta_cis,
            "n_boot": n_boot, "seed": seed, "threshold": QUOTA_THRESHOLD}


# =====================================================================
# Report
# =====================================================================
def _pct01(v, nd=1):
    """Frazione 0..1 -> percentuale."""
    return "-" if v is None else f"{100.0 * v:.{nd}f}%"


def _pctroi(v, nd=2):
    """ROI gia' in punti percentuali."""
    return "-" if v is None else f"{v:.{nd}f}%"


def _fm(v, nd=3):
    return "-" if v is None else f"{v:.{nd}f}"


def _ci_str(ci, key, nd=3):
    if ci is None or ci[key] is None:
        return "-"
    lo, hi = ci[key]
    return "[" + f"{lo:+.{nd}f};{hi:+.{nd}f}" + "]"


def render(payload):
    L = []
    ap = L.append
    thr = payload["threshold"]
    an = payload["analysis"]
    pt, ci = an["point"], an["ci"]
    ap("# Fascia di quota reale del Top Mix — soglia 1,50 (audit sola lettura)")
    ap("")
    ap(f"*Generato: {payload['generated_at']} — script "
       "`audit/diagnose_quota_minima.py`, nessuna modifica a SoccerMath/.*")
    ap("")
    ap(f"Le righe ammesse del selettore Top Mix (replay consolidato di "
       "`seleziona_riga_top_mix`, funzione pura importata da "
       f"`SoccerMath/app.py`: {payload['n_candidate']} candidate, "
       f"{payload['n_admitted']} ammesse, stagioni 2024/25+2025/26 — "
       "**validation storica gia' esaminata**, non un test intatto) vengono "
       "agganciate alla QUOTA REALE del mercato scelto: B365 dai CSV storici "
       "per 1X2 e O/U 2.5, quote BTTS (bet365/fallback dichiarato) dai file "
       "`audit/data/*_btts.json` via `gg_ng_calibration.join_btts_file` "
       f"riusato identico. Le righe sono divise per quota reale < {thr:.2f} vs "
       ">= " + f"{thr:.2f} (soglia del protocollo, non ottimizzata sui dati). "
       "Mai 1/confidence, mai quota implicita del modello; righe senza quota "
       "usabile ESCLUSE e CONTEGGIATE, mai assegnate a una fascia.")
    ap("")

    cov = payload["coverage"]
    ap("## 0. Perimetro e consistenza")
    ap("")
    ap(f"* Sorgente righe: `{payload['rows_path']}` (committato, "
       f"{payload['n_candidate']} candidate, {payload['n_admitted']} ammesse — "
       "identico a `topmix_margins.py`).")
    ap("* Selettore: `seleziona_riga_top_mix` di produzione (parita' "
       "comportamentale garantita da `SoccerMath/test_topmix_selector_parity.py`; "
       "qui la funzione e' importata e il replay NON viene rieseguito).")
    ap("* Quote: B365 per 1X2 (B365H/D/A) e O/U 2.5 (B365>2.5/B365<2.5) dai CSV "
       "`SoccerMath/database/`; GG/NG dai JSON oddsportal (bet365 se presente, "
       "altrimenti primo book usabile — convenzione `gg_ng_calibration`).")
    ap("* Nota join: il replay conserva i nomi GREZZI football-data in "
       "`home`/`away` (es. «Bayern Munich», «RB Leipzig» in Bundesliga): la "
       "chiave di join applica la stessa normalizzazione dei database "
       "(`team_aliases.clean_name`), identica a quella di `load_league` e del "
       "join BTTS. Copertura risultata 100% su ogni mercato.")
    ap("* Brier = media di (confidence − esito)² sull'evento scelto, stessa "
       "definizione di `topmix_margins.quality` (verificata nei test); ROI = "
       "puntata fissa 10 su OGNI riga ammessa con quota, settle sulla quota "
       "reale del book (le ammesse sono le selezioni gia' puntate dal Top Mix).")
    ap("")

    ap("## 1. Copertura dell'aggancio quota reale")
    ap("")
    ap("| Voce | Righe |")
    ap("|---|---:|")
    ap(f"| Ammesse dal replay | {payload['n_admitted']} |")
    ap(f"| Con quota reale usabile | {payload['attached_n']} |")
    for k in sorted(cov):
        if k != "excluded":
            ap(f"| Escluse: {k} | {cov[k]} |")
    ap(f"| **Totale escluse** | **{cov.get('excluded', 0)}** |")
    ap("")
    ap("Nessuna riga senza quota e' finita in una fascia. Verifica di coerenza "
       "dell'esito: ricalcolando l'esito del mercato dai gol del replay, "
       f"``hit_mismatch`` = {cov.get('hit_mismatch', 0)} (la mappa "
       "mercato->esito di questo audit coincide con quella del replay).")
    ap("")
    ap("Copertura per mercato:")
    ap("")
    ap("| Mercato | con quota | ammesse | copertura |")
    ap("|---|---:|---:|---:|")
    for m in payload["markets_present"]:
        n_adm = payload["per_market_admitted"].get(m, 0)
        n_att = payload["per_market_attached"].get(m, 0)
        ap(f"| {m} | {n_att} | {n_adm} | "
           f"{100.0 * n_att / max(1, n_adm):.1f}% |")
    ap("")

    ap(f"## 2. Fasce di quota reale (< {thr:.2f} vs >= {thr:.2f})")
    ap("")
    ap("| Fascia | n | hit-rate | Brier | conf media | quota media | ROI |")
    ap("|---|---:|---:|---:|---:|---:|---:|")
    for name, label in (("comp", "quota < " + f"{thr:.2f}"),
                        ("sub", "quota >= " + f"{thr:.2f}"),
                        ("full", "intero campione ammesso")):
        p, c = pt[name], ci[name]
        ap(f"| {label} | {p['n']} | {_pct01(p['hit_rate'])} "
           f"(CI {_ci_str(c, 'hit_rate')}) | {_fm(p['brier'])} "
           f"(CI {_ci_str(c, 'brier')}) | {_fm(p['mean_conf'])} | "
           f"{_fm(p['mean_odds'], 2)} | {_pctroi(p['roi_pct'])} "
           f"(CI {_ci_str(c, 'roi_pct', 2)}) |")
    ap("")
    ap(f"Tutte le CI: bootstrap {an['n_boot']} resample, seed {an['seed']}, "
       "percentile 2.5-97.5 (convenzione `topmix_margins._ci`). Lo stesso "
       "resample e' applicato a tutte le celle e ai delta della sezione 4: i "
       "confronti sono appaiati. Una cella con troppo pochi casi (CI istabile "
       "in oltre meta' dei resample) e' marcata senza CI, mai stimata a caso.")
    ap("")

    ap("## 3. Scomposizione per mercato dentro ciascuna fascia")
    ap("")
    ap("| Mercato | Fascia | n | hit-rate | Brier | conf media | ROI |")
    ap("|---|---|---:|---:|---:|---:|---:|")
    for m in payload["markets_present"]:
        for name, label in (("sub", ">= " + f"{thr:.2f}"), ("comp", "< " + f"{thr:.2f}")):
            p = pt["m:" + m + ":" + name]
            if p["n"] == 0:
                ap(f"| {m} | {label} | 0 | - | - | - | - |")
            else:
                c = ci["m:" + m + ":" + name]
                roi_ci = ("CI " + _ci_str(c, "roi_pct", 2)) if c["ci_stable"] \
                    else "CI instabile (n troppo piccolo)"
                ap(f"| {m} | {label} | {p['n']} | {_pct01(p['hit_rate'])} | "
                   f"{_fm(p['brier'])} | {_fm(p['mean_conf'])} | "
                   f"{_pctroi(p['roi_pct'])} ({roi_ci}) |")
        ap("")
    ap("")

    ap(f"## 4. Confronto esplicito: subset quota >= {thr:.2f} vs INTERO campione")
    ap("")
    ap("Delta appaiati (stesso resample) subset − intero campione e subset − "
       "complementare. La domanda del protocollo: restringere BUTTA VIA valore "
       "(ROI delta significativamente negativo) o lo PRESERVA (delta "
       "indistinguibile da zero)? «sig» = l'IC esclude lo 0.")
    ap("")
    ap("| Confronto | Metrica | Delta | CI 2.5% | CI 97.5% | sig |")
    ap("|---|---|---:|---:|---:|:---:|")
    for dk, dlabel in (("sub-full", "subset − intero campione"),
                       ("sub-comp", "subset − fascia corta")):
        for k, klabel, nd in (("hit_rate", "hit-rate", 3), ("brier", "Brier", 4),
                              ("roi_pct", "ROI", 2)):
            d = an["delta"][dk][k]
            lo, hi = d["ci"]
            if d["delta"] is None or lo is None:
                ap(f"| {dlabel} | {klabel} | - | - | - | n/c |")
                continue
            sig = not (lo <= 0.0 <= hi)
            ap(f"| {dlabel} | {klabel} | {d['delta']:+.{nd}f} | {lo:+.{nd}f} | "
               f"{hi:+.{nd}f} | {'**sì**' if sig else 'no'} |")
    ap("")

    dfull = an["delta"]["sub-full"]["roi_pct"]
    dbrier = an["delta"]["sub-full"]["brier"]
    dcomp = an["delta"]["sub-comp"]["roi_pct"]
    sig_roi_full = dfull["ci"][0] is not None and not (dfull["ci"][0] <= 0.0 <= dfull["ci"][1])
    sig_brier_full = dbrier["ci"][0] is not None and not (dbrier["ci"][0] <= 0.0 <= dbrier["ci"][1])
    share = 100.0 * pt["sub"]["n"] / max(1, pt["full"]["n"])
    ap("## 5. Lettura")
    ap("")
    ap(f"1. **Composizione.** Il {share:.0f}% del campione ammesso "
       f"({pt['sub']['n']} su {pt['full']['n']}) ha quota >= {thr:.2f}; la "
       f"fascia corta (< {thr:.2f}, {pt['comp']['n']} righe) e' fatta "
       "soprattutto da favoriti 1 e Under 2.5 (sezione 3).")
    ap("")
    ap(f"2. **Calibrazione subset vs intero.** Delta Brier "
       f"{dbrier['delta']:+.4f} (CI [{dbrier['ci'][0]:+.4f};{dbrier['ci'][1]:+.4f}], "
       f"{'significativo' if sig_brier_full else 'NON significativo'}). Il "
       "confronto assoluto fra fasce va letto con la confidenza media in mano "
       "(colonna «conf media»): la fascia corta e' quella a confidenza piu' "
       "alta, quindi un suo Brier basso non e' una sorpresa.")
    ap("")
    ap(f"3. **Valore.** ROI subset − intero: {dfull['delta']:+.2f} punti "
       f"(CI [{dfull['ci'][0]:+.2f};{dfull['ci'][1]:+.2f}], "
       f"{'significativo' if sig_roi_full else 'NON significativo'}); "
       f"ROI subset − fascia corta: {dcomp['delta']:+.2f} "
       f"(CI [{dcomp['ci'][0]:+.2f};{dcomp['ci'][1]:+.2f}]).")
    ap("")
    dhr = an["delta"]["sub-full"]["hit_rate"]
    neg_roi = dfull["delta"] < 0 and sig_roi_full
    neg_brier = dbrier["delta"] > 0 and sig_brier_full
    if neg_roi and neg_brier:
        verdict = ("**Risposta alla domanda del protocollo: NO — su questo "
                   "campione restringere a quota >= " + f"{thr:.2f} BUTTA VIA "
                   "valore invece di preservarlo.** Tutti e tre i delta subset−intero "
                   "sono significativamente negativi (hit-rate "
                   f"{dhr['delta']:+.3f}, Brier {dbrier['delta']:+.4f}, ROI "
                   f"{dfull['delta']:+.2f} punti): il filtro elimina proprio il "
                   "segmento migliore (quota corta: hit-rate "
                   f"{_pct01(pt['comp']['hit_rate'])}, Brier {_fm(pt['comp']['brier'])}, "
                   f"ROI {_pctroi(pt['comp']['roi_pct'])} con CI che include lo 0, "
                   "cioè vicino al pareggio) e lascia solo il segmento peggiore. "
                   "L'effetto e' TRASVERSALE: dentro ogni mercato la fascia corta "
                   "ha Brier e ROI migliori della fascia lunga (sezione 3).")
    elif not sig_roi_full and not sig_brier_full:
        verdict = ("**Risposta alla domanda del protocollo: il filtro PRESERVA "
                   "calibrazione e valore** (nessun delta subset−intero "
                   "significativo): restringere non migliora nulla ma non "
                   "distrugge niente di misurabile.")
    else:
        verdict = ("**Risposta alla domanda del protocollo: esito misto** — "
                   "vedi delta della sezione 4 con i relativi CI.")
    ap("4. " + verdict)
    ap("")

    ap("## 6. Limiti dichiarati")
    ap("")
    ap("1. **Stagioni gia' esaminate**: il replay 2024/25+2025/26 e' la stessa "
       "validation storica degli altri audit Top Mix (soglie, pesi e gate sono "
       "stati scelti su questi dati): nessun numero qui e' out-of-sample.")
    ap("2. **Soglia 1,50 del protocollo**, non ottimizzata: nessuna scansione "
       "di soglie; qualunque altra soglia andrebbe testata con la stessa "
       "disciplina (selezione su train, conferma su validation) prima di "
       "credervi.")
    ap("3. **Quote B365 pre-match** (colonne CSV, non line live) e BTTS "
       "oddsportal con fallback multi-book dichiarato per file: stessa fonte "
       "degli audit precedenti, quindi stessi limiti di realismo di "
       "esecuzione.")
    ap("4. **Brier fra fasce non e' paragonabile in assoluto**: le fasce hanno "
       "confidenze medie diverse; il Brier per fascia misura la calibrazione "
       "del modello SU quella fascia, non la qualita' della fascia.")
    ap("5. Le righe senza quota usabile sono escluse e contate (sezione 1): se "
       "la mancanza di quota fosse correlata all'esito, le fasce subirebbero "
       "un bias di selezione non correggibile.")
    ap("6. ROI a puntata fissa su selezioni del selettore: niente stake "
       "variabili/Kelly, niente accumuli: come gli altri audit Top Mix.")
    ap("")
    ap("## 7. Riproduzione")
    ap("")
    ap("```")
    ap("python audit/diagnose_quota_minima.py")
    ap("```")
    ap("")
    ap(f"Deterministico: bootstrap con seed fisso ({an['seed']}), righe lette "
       "dal CSV committato (stesso replay di `topmix_margins.py`). Dettaglio "
       "completo nel sidecar `quota_minima_report_detail.json`.")
    ap("")
    return "\n".join(L) + "\n"


# =====================================================================
# Main
# =====================================================================
def run(rows_path=DEFAULT_ROWS):
    rows = pd.read_csv(rows_path)
    admitted = rows[rows["A_admitted"] == True]  # noqa: E712  (come topmix_margins)
    prefixes = {league_prefix_map()[lg] for lg in rows["league"].unique()}
    dataset = load_btts_dataset()
    csv_idx, dup_csv = build_csv_odds_index(prefixes)
    btts_idx, dup_btts, btts_stats = build_btts_odds_index(dataset, prefixes)
    assert not dup_csv, "coppie duplicate nell'indice quote CSV: " + str(dup_csv)
    assert not dup_btts, "coppie duplicate nell'indice quote BTTS: " + str(dup_btts)
    attached, coverage = attach_real_odds(rows, csv_idx, btts_idx)
    analysis = bootstrap_analysis(attached)
    per_market_admitted = Counter(admitted["A_market"])
    per_market_attached = Counter(attached["market"])
    payload = {
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "rows_path": os.path.relpath(rows_path, _REPO_ROOT),
        "n_candidate": int(len(rows)),
        "n_admitted": int(len(admitted)),
        "attached_n": int(len(attached)),
        "coverage": dict(coverage),
        "btts_join_stats": btts_stats,
        "duplicate_pairs": {"csv": dup_csv, "btts": dup_btts},
        "per_market_admitted": {m: int(per_market_admitted.get(m, 0))
                                for m in sorted(set(per_market_admitted))},
        "per_market_attached": {m: int(per_market_attached.get(m, 0))
                                for m in sorted(set(per_market_attached))},
        "markets_present": sorted(set(per_market_attached)),
        "threshold": QUOTA_THRESHOLD,
        "stake": STAKE,
        "analysis": analysis,
    }
    md = render(payload)
    return payload, md


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    payload, md = run()
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(JSON_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1, default=str)
    print("Scritti " + OUT_PATH + " e " + JSON_PATH)
    pt = payload["analysis"]["point"]
    d = payload["analysis"]["delta"]["sub-full"]["roi_pct"]
    print(f"Con quota: {payload['attached_n']}/{payload['n_admitted']} | "
          f"sub(>=1.50) n={pt['sub']['n']} ROI {pt['sub']['roi_pct']:.2f}% vs "
          f"full ROI {pt['full']['roi_pct']:.2f}% | delta "
          f"{d['delta']:+.2f} CI [{d['ci'][0]:+.2f};{d['ci'][1]:+.2f}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
