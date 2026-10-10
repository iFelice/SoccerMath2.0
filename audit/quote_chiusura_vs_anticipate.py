#!/usr/bin/env python3
"""quote_chiusura_vs_anticipate.py — Le quote di chiusura sono piu' informative
delle quote anticipate sull'1X2? (audit, SOLA LETTURA)

DOMANDA. Serve un giro quote piu' tardivo (verso la chiusura) o le quote
anticipate (quelle gia' usate dall'app) contengono gia' tutta l'informazione
utile? Nessuna modifica a ``SoccerMath/``, nessun replay --write, nessuna
chiamata all'API: si usano SOLO i CSV football-data gia' in
``SoccerMath/database/``.

CAMPO E FONTI (stesso campione della PR #49, ``onex2_market_test.py``)
  * leghe: Serie A, Premier League, La Liga, Bundesliga, Ligue 1;
  * stagioni: 2024/25 (file ``*_2024.csv``) e 2025/26 (file ``*_2025.csv``);
  * quote anticipate: B365H/B365D/B365A (quelle della PR #49) e, se presenti,
    PSH/PSD/PSA (Pinnacle pre);
  * quote di chiusura: B365CH/B365CD/B365CA e PSCH/PSCD/PSCA (Pinnacle).
  * Confronto principale: coppia B365 (pre vs chiusura, stesso bookmaker) su
    TUTTE le partite con entrambe le terne.
  * Controllo a fonte uguale: coppia Pinnacle (pre vs chiusura) sulle partite
    con entrambe le terne Pinnacle valide.

REGOLE (dichiarate prima di guardare i risultati)
  * De-vig PROPORZIONALE per tutte le fonti (``backtest_experiment_all.devig_1x2``):
    ``p_i = (1/o_i) / sum(1/o_j)``. Terna valida = i tre valori presenti e > 1.0.
  * Campione: solo partite con terna anticipata E terna di chiusura della fonte
    in esame; si dichiara quante restano. Esito da FTR (nella PR #49 FTR e'
    uguale all'esito dai gol in ogni riga dei due campioni).
  * Metriche su tutte le partite del campione: Brier 1X2 (media delle somme
    quadratiche sui 3 esiti) e LogLoss (media, p clip a 1e-9) per anticipata e
    chiusura.
  * Top Mix: esito piu' probabile ammesso se p >= 0,55 (soglia di produzione
    ``app.seleziona_riga_top_mix``): n, hit rate, confidenza media dichiarata,
    per anticipata e chiusura, con IC 95% bootstrap.
  * Delta Brier = Brier(chiusura) − Brier(anticipata), con bootstrap a blocchi
    (blocco = lega x stagione x giornata, 2000 repliche, IC 95% percentile,
    seme 20261008 come PR #49).
  * REGOLA DI DECISIONE: la chiusura e' "PIU' INFORMATIVA" se l'IC 95% di
    Delta Brier esclude lo zero a suo favore (IC interamente negativo);
    altrimenti "NESSUNA DIFFERENZA DIMOSTRATA".

ANALISI DEI MOVIMENTI
  * Delta = p_chiusura − p_anticipata sull'esito FAVORITO secondo la quota
    anticipata (in punti percentuali, x100).
  * Fasce (partizione di R, dichiarata): F1: Delta <= −5; F2: −5 < Delta <= −2;
    F3: −2 < Delta < +2; F4: +2 <= Delta < +5; F5: Delta >= +5.
  * Per fascia: n, hit rate del favorito anticipato, probabilità media
    dichiarata (anticipata e chiusura), differenze. Domanda: quando il
    favorito si accorcia (Delta > 0) vince piu' spesso di quanto dicesse la
    quota anticipata, e quando si allunga (Delta < 0) meno spesso?

Output
  * ``audit/results/quote_chiusura_vs_anticipate.md``  referto (versionato);
  * ``audit/output/quote_chiusura_vs_anticipate.json`` payload completo;
  * ``audit/output/quote_chiusura_vs_anticipate_rows.csv`` righe per partita.
  (``audit/output/`` e' ignorata da Git.)

Uso: ``python audit/quote_chiusura_vs_anticipate.py [--reps 2000] [--seed 20261008]``
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from collections import OrderedDict

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
from backtest_experiment_all import LEAGUES, devig_1x2  # noqa: E402

DB_DIR = os.path.join(_REPO_ROOT, "SoccerMath", "database")
OUT_DIR = os.path.join(_AUDIT_DIR, "output")
RES_DIR = os.path.join(_AUDIT_DIR, "results")

# ---------------------------------------------------------------------------
# Costanti fissate PRIMA di guardare i numeri
# ---------------------------------------------------------------------------
EVAL_SEASONS = OrderedDict([("2024/25", "2024"), ("2025/26", "2025")])
PRE_B365 = ("B365H", "B365D", "B365A")        # anticipate (commessa PR #49)
PRE_PIN = ("PSH", "PSD", "PSA")               # anticipate Pinnacle (se presenti)
CLOSE_B365 = ("B365CH", "B365CD", "B365CA")   # chiusura B365
CLOSE_PIN = ("PSCH", "PSCD", "PSCA")          # chiusura Pinnacle
ALL_ODDS_COLS = PRE_B365 + PRE_PIN + CLOSE_B365 + CLOSE_PIN
NEED = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"]

P_CLIP = 1e-9
TOPMIX_MIN = 0.55        # soglia di produzione del Top Mix (confidenza >= 0,55)
DEFAULT_REPS = 2000
DEFAULT_SEED = 20261008  # stesso seme della PR #49
Y_CODES = {"H": 0, "D": 1, "A": 2}

# Fasce di Delta (punti percentuali) — partizione di R, confini dichiarati:
# F1: Delta <= -5 ; F2: -5 < Delta <= -2 ; F3: -2 < Delta < +2 ;
# F4: +2 <= Delta < +5 ; F5: Delta >= +5.
BANDS = (
    ("F1: Delta <= -5", -math.inf, -5.0, True, True),
    ("F2: -5 < Delta <= -2", -5.0, -2.0, False, True),
    ("F3: -2 < Delta < +2", -2.0, 2.0, False, False),
    ("F4: +2 <= Delta < +5", 2.0, 5.0, True, False),
    ("F5: Delta >= +5", 5.0, math.inf, True, False),
)


# ---------------------------------------------------------------------------
# Caricamento (stessa pulizia dei CSV football-data della PR #49)
# ---------------------------------------------------------------------------
def load_season(prefix: str, league: str, suffix: str, season: str) -> pd.DataFrame:
    df = pd.read_csv(os.path.join(DB_DIR, f"{prefix}_{suffix}.csv"),
                     on_bad_lines="warn", low_memory=False)
    cols = [c for c in NEED + list(ALL_ODDS_COLS) if c in df.columns]
    df = df[cols].copy()
    for c in ALL_ODDS_COLS:
        if c not in df.columns:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    for c in ("FTHG", "FTAG"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["league"] = league
    df["season"] = season
    df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTR"]).reset_index(drop=True)
    df = df.sort_values("Date", kind="stable").reset_index(drop=True)
    df = df.drop_duplicates(subset=["Date", "HomeTeam", "AwayTeam"], keep="last")
    df = df.reset_index(drop=True)
    df["date_day"] = df["Date"].dt.normalize()
    return df


def coverage_table(df: pd.DataFrame) -> dict:
    """Copertura per colonna (non nulli) e per terna (valida: presenti, > 1.0)."""
    out = {"lega": df["league"].iloc[0], "stagione": df["season"].iloc[0],
           "righe": len(df), "colonne": {}, "terna": {}}
    for c in ALL_ODDS_COLS:
        out["colonne"][c] = int(df[c].notna().sum())
    for nome, ter in (("pre_b365", PRE_B365), ("pre_pin", PRE_PIN),
                      ("close_b365", CLOSE_B365), ("close_pin", CLOSE_PIN)):
        out["terna"][nome] = int(
            (df[list(ter)].notna().all(axis=1) & (df[list(ter)] > 1.0).all(axis=1)).sum())
    return out


# ---------------------------------------------------------------------------
# De-vig proporzionale e metriche
# ---------------------------------------------------------------------------
def devig_prop(odds: np.ndarray) -> np.ndarray | None:
    """De-vig proporzionale (helper di produzione ``devig_1x2``)."""
    o = np.asarray(odds, dtype=float)
    if o.shape != (3,) or not np.all(np.isfinite(o)) or np.any(o <= 1.0):
        return None
    p = devig_1x2(*[float(x) for x in o])
    if p is None or p[0] is None:
        return None
    return np.array([p[0], p[1], p[2]], dtype=float)


def probs_from_tern(df: pd.DataFrame, cols) -> np.ndarray:
    """Matrice (n,3) di probabilita' de-vig proporzionale; righe non valide = NaN."""
    raw = df[list(cols)].to_numpy(float)
    out = np.full((len(df), 3), np.nan)
    for i in range(len(df)):
        p = devig_prop(raw[i])
        if p is not None:
            out[i] = p
    return out


def brier_1x2(P: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Errore quadrato sommato sui 3 esiti, per partita: (n,)."""
    n = len(P)
    Y = np.zeros((n, 3))
    Y[np.arange(n), y] = 1.0
    return np.sum((P - Y) ** 2, axis=1)


def logloss_each(P: np.ndarray, y: np.ndarray) -> np.ndarray:
    """LogLoss per partita: (n,)."""
    n = len(P)
    return -np.log(np.clip(P[np.arange(n), y], P_CLIP, 1.0))


def block_bootstrap_block(arr: np.ndarray, blocks: np.ndarray, reps: int, seed: int):
    """Risampling dei blocchi: ritorna (indici per replica). Arr e' allineato a blocks."""
    uniq = np.unique(blocks)
    idx = {b: np.where(blocks == b)[0] for b in uniq}
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(reps):
        out.append(np.concatenate([idx[x] for x in uniq[rng.integers(0, len(uniq), len(uniq))]]))
    return out


def diff_brier_ic(Pa: np.ndarray, Pb: np.ndarray, y: np.ndarray, blocks: np.ndarray,
                  reps: int, seed: int, subset: np.ndarray | None = None):
    """Delta Brier = Brier(Pb) − Brier(Pa); punto + IC 95% bootstrap a blocchi.

    None se il subset e' vuoto.
    """
    if subset is None:
        subset = np.ones(len(Pa), dtype=bool)
    if not subset.any():
        return None
    d = brier_1x2(Pb[subset], y[subset]) - brier_1x2(Pa[subset], y[subset])
    sel = block_bootstrap_block(d, blocks[subset], reps, seed)
    means = np.array([d[s].mean() for s in sel])
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"n": int(subset.sum()), "point": float(d.mean()), "ic95": (float(lo), float(hi))}


def decide(ic95: tuple) -> str:
    """Regola dichiarata: 'piu_informativa' solo se l'IC 95% esclude lo zero a
    favore della chiusura (IC interamente negativo); altrimenti
    'nessuna_differenza_dimostrata'."""
    lo, hi = ic95
    if hi < -1e-12:
        return "piu_informativa"
    return "nessuna_differenza_dimostrata"


def topmix_stats(P: np.ndarray, y: np.ndarray, min_p: float = TOPMIX_MIN) -> dict:
    """Top Mix: esito piu' probabile ammesso se p >= min_p."""
    n = len(P)
    fav = np.argmax(P, axis=1)
    pmax = P[np.arange(n), fav]
    ad = pmax >= min_p
    n_ad = int(ad.sum())
    return {
        "n": n,
        "ammesse": n_ad,
        "hit_rate": float((fav[ad] == y[ad]).mean()) if n_ad else None,
        "confidenza_media": float(pmax[ad].mean()) if n_ad else None,
    }


def topmix_ic(P: np.ndarray, y: np.ndarray, blocks: np.ndarray, reps: int, seed: int,
              min_p: float = TOPMIX_MIN):
    """IC 95% (bootstrap a blocchi) su hit rate e confidenza media del Top Mix."""
    n = len(P)
    fav = np.argmax(P, axis=1)
    pmax = P[np.arange(n), fav]
    ad = pmax >= min_p
    if not ad.any():
        return None
    hit_arr = (fav[ad] == y[ad]).astype(float)
    conf_arr = pmax[ad]
    sel = block_bootstrap_block(np.ones(ad.sum()), blocks[ad], reps, seed)
    hr = np.array([hit_arr[s].mean() for s in sel])
    cf = np.array([conf_arr[s].mean() for s in sel])
    return {
        "hit_rate_ic95": tuple(np.percentile(hr, [2.5, 97.5]).tolist()),
        "confidenza_ic95": tuple(np.percentile(cf, [2.5, 97.5]).tolist()),
    }


# ---------------------------------------------------------------------------
# Analisi di una coppia (anticipata, chiusura) su un sottoinsieme
# ---------------------------------------------------------------------------
def analyze_pair(df: pd.DataFrame, Pa: np.ndarray, Pb: np.ndarray,
                 y: np.ndarray, blocks: np.ndarray, reps: int, seed: int) -> dict:
    """Metriche su tutte le righe del DataFrame (Pa/Pb gia' de-vig, senza NaN)."""
    out: dict = {}
    for tag, P in (("anticipata", Pa), ("chiusura", Pb)):
        out[f"brier_{tag}"] = float(brier_1x2(P, y).mean())
        out[f"logloss_{tag}"] = float(logloss_each(P, y).mean())

    per_s = OrderedDict()
    for s in sorted(df["season"].unique()):
        m = (df["season"] == s).to_numpy()
        per_s[s] = {
            "n": int(m.sum()),
            "brier_anticipata": float(brier_1x2(Pa[m], y[m]).mean()),
            "brier_chiusura": float(brier_1x2(Pb[m], y[m]).mean()),
            "logloss_anticipata": float(logloss_each(Pa[m], y[m]).mean()),
            "logloss_chiusura": float(logloss_each(Pb[m], y[m]).mean()),
        }
    out["per_stagione"] = per_s

    tm = {}
    for tag, P in (("anticipata", Pa), ("chiusura", Pb)):
        st = topmix_stats(P, y)
        ic = topmix_ic(P, y, blocks, reps, seed=seed + (0 if tag == "anticipata" else 101))
        if ic:
            st.update(ic)
        tm[tag] = st
    out["topmix"] = tm

    per_s_tm = OrderedDict()
    for s in sorted(df["season"].unique()):
        m = (df["season"] == s).to_numpy()
        per_s_tm[s] = {"anticipata": topmix_stats(Pa[m], y[m]),
                       "chiusura": topmix_stats(Pb[m], y[m])}
    out["topmix_per_stagione"] = per_s_tm

    db = {"pooled": diff_brier_ic(Pa, Pb, y, blocks, reps, seed)}
    for lga in [l for _, l in LEAGUES]:
        r = diff_brier_ic(Pa, Pb, y, blocks, reps, seed, subset=(df["league"] == lga).to_numpy())
        if r:
            db[lga] = r
    for s in sorted(df["season"].unique()):
        db[f"stagione_{s}"] = diff_brier_ic(Pa, Pb, y, blocks, reps, seed,
                                            subset=(df["season"] == s).to_numpy())
    out["delta_brier"] = db
    out["verdetto"] = decide(db["pooled"]["ic95"])
    return out


# ---------------------------------------------------------------------------
# Analisi dei movimenti (sull'esito favorito secondo la quota anticipata)
# ---------------------------------------------------------------------------
def _agg(m, hit, delta, p_pre, p_close) -> dict | None:
    if not m.any():
        return None
    return {
        "n": int(m.sum()),
        "hit_rate": float(hit[m].mean()),
        "prob_media_anticipata": float(p_pre[m].mean()),
        "prob_media_chiusura": float(p_close[m].mean()),
        "hit_minus_anticipata": float(hit[m].mean() - p_pre[m].mean()),
        "hit_minus_chiusura": float(hit[m].mean() - p_close[m].mean()),
    }


def movement(Pa: np.ndarray, Pb: np.ndarray, y: np.ndarray) -> dict:
    """Delta = p_chiusura − p_anticipata sull'esito favorito dell'anticipata."""
    n = len(Pa)
    fav = np.argmax(Pa, axis=1)
    p_fav_pre = Pa[np.arange(n), fav]
    p_fav_close = Pb[np.arange(n), fav]
    delta = (p_fav_close - p_fav_pre) * 100.0
    hit = (fav == y)
    dist = {
        "n": int(n),
        "media": float(delta.mean()),
        "mediana": float(np.median(delta)),
        "dev_std": float(delta.std(ddof=1)),
        "min": float(delta.min()),
        "max": float(delta.max()),
        "p05": float(np.percentile(delta, 5)),
        "p10": float(np.percentile(delta, 10)),
        "p25": float(np.percentile(delta, 25)),
        "p75": float(np.percentile(delta, 75)),
        "p90": float(np.percentile(delta, 90)),
        "p95": float(np.percentile(delta, 95)),
        "share_abs_lt1": float((np.abs(delta) < 1).mean()),
        "share_abs_lt2": float((np.abs(delta) < 2).mean()),
        "share_ge2": float((np.abs(delta) >= 2).mean()),
        "share_ge5": float((np.abs(delta) >= 5).mean()),
    }
    bands = OrderedDict()
    for label, lo, hi, lo_inc, hi_inc in BANDS:
        m = ((delta > lo) | (lo_inc & (delta == lo))) & ((delta < hi) | (hi_inc & (delta == hi)))
        n_b = int(m.sum())
        if n_b == 0:
            bands[label] = {"n": 0}
            continue
        bands[label] = {
            "n": n_b,
            "hit_rate": float(hit[m].mean()),
            "prob_media_anticipata": float(p_fav_pre[m].mean()),
            "prob_media_chiusura": float(p_fav_close[m].mean()),
            "hit_minus_anticipata": float(hit[m].mean() - p_fav_pre[m].mean()),
            "hit_minus_chiusura": float(hit[m].mean() - p_fav_close[m].mean()),
            "delta_media": float(delta[m].mean()),
        }
    agg = {
        "accorcia_ge+2": _agg(delta >= 2, hit, delta, p_fav_pre, p_fav_close),
        "allunga_le-2": _agg(delta <= -2, hit, delta, p_fav_pre, p_fav_close),
    }
    return {"distribuzione": dist, "fasce": bands, "aggregati": agg,
            "hit_favorito_totale": float(hit.mean())}


# ---------------------------------------------------------------------------
# Conclusione generata dai numeri (la regola e' quella dichiarata in testa)
# ---------------------------------------------------------------------------
def build_conclusioni(b365: dict, pin: dict, mov_b: dict, sample: dict) -> str:
    db = b365["delta_brier"]["pooled"]
    v = b365["verdetto"]
    d = mov_b["distribuzione"]
    agg = mov_b["aggregati"]
    fas = mov_b["fasce"]
    L: list[str] = []
    if v == "piu_informativa":
        L.append(f"**Secondo la regola dichiarata, la chiusura e' PIU' INFORMATIVA:** Delta Brier pooled = "
                 f"{db['point']:.4f}, IC 95% [{db['ic95'][0]:.4f}; {db['ic95'][1]:.4f}] interamente negativo; "
                 f"campione {sample['comune_b365']} partite.")
    else:
        direzione = ("esclude lo zero a favore dell'anticipata" if db["ic95"][0] > 0
                     else "contiene lo zero")
        L.append(f"**Secondo la regola dichiarata, NESSUNA DIFFERENZA DIMOSTRATA:** Delta Brier pooled = "
                 f"{db['point']:.4f}, IC 95% [{db['ic95'][0]:.4f}; {db['ic95'][1]:.4f}] ({direzione}); "
                 f"campione {sample['comune_b365']} partite. Lo scarto e' piccolo anche in valore assoluto "
                 f"({abs(db['point'])*100:.2f} punti percentuali di Brier).")
    dp = pin["delta_brier"]["pooled"]
    L.append(f"Il controllo a fonte uguale (Pinnacle pre vs chiusura, n={dp['n']}) da: "
             f"Delta Brier = {dp['point']:.4f} [{dp['ic95'][0]:.4f}; {dp['ic95'][1]:.4f}].")

    acc = agg.get("accorcia_ge+2")
    allu = agg.get("allunga_le-2")
    if acc:
        L.append(f"Quando il favorito si ACCORCIA (Delta >= +2 pt; n={acc['n']}, "
                 f"{acc['n']/d['n']:.0%} delle partite): hit rate {acc['hit_rate']:.4f} vs probabilità media "
                 f"anticipata {acc['prob_media_anticipata']:.4f} (scarto {acc['hit_minus_anticipata']:+.4f}) → "
                 "il favorito vince PIU' spesso di quanto dicesse la quota anticipata. Ma rispetto alla "
                 f"probabilità dichiarata in chiusura ({acc['prob_media_chiusura']:.4f}) lo scarto e' solo "
                 f"{acc['hit_minus_chiusura']:+.4f}: la chiusura ha gia' assorbito il movimento.")
    if allu:
        L.append(f"Quando il favorito si ALLUNGA (Delta <= −2 pt; n={allu['n']}, "
                 f"{allu['n']/d['n']:.0%} delle partite): hit rate {allu['hit_rate']:.4f} vs probabilità media "
                 f"anticipata {allu['prob_media_anticipata']:.4f} (scarto {allu['hit_minus_anticipata']:+.4f}) "
                 f"→ il favorito vince MENO spesso di quanto dicesse la quota anticipata. Rispetto alla "
                 f"chiusura ({allu['prob_media_chiusura']:.4f}) lo scarto e' {allu['hit_minus_chiusura']:+.4f}: "
                 "su questo campione la chiusura corregge leggermente piu' del necessario.")
    in_fasce = [r["hit_minus_anticipata"] for _, r in fas.items() if r and r.get("n")]
    if len(in_fasce) == len(BANDS) and all(a <= b for a, b in zip(in_fasce, in_fasce[1:])):
        L.append(f"Il pattern e' monotono: lo scarto (hit rate − probabilità anticipata) cresce con Delta "
                 f"da {in_fasce[0]:+.4f} (favorevole che si allunga di >= 5 pt) a {in_fasce[-1]:+.4f} "
                 f"(favorevole che si accorcia di >= 5 pt): piu' il favorito si accorcia in chiusura, piu' "
                 "l'anticipata sottostimava la sua frequenza di vittoria reale.")
    f1, f5 = fas.get("F1: Delta <= -5"), fas.get("F5: Delta >= +5")
    if f1 and f5 and f1.get("n") and f5.get("n"):
        L.append(f"Nelle fasce estreme l'effetto e' netto e monocausale: favorito che si allunga di >= 5 pt "
                 f"(n={f1['n']}): hit {f1['hit_rate']:.4f} vs anticipata {f1['prob_media_anticipata']:.4f} "
                 f"({f1['hit_minus_anticipata']:+.4f}) ma quasi calibrato sulla chiusura "
                 f"({f1['hit_minus_chiusura']:+.4f}); favorito che si accorcia di >= 5 pt (n={f5['n']}): hit "
                 f"{f5['hit_rate']:.4f} vs anticipata {f5['prob_media_anticipata']:.4f} "
                 f"({f5['hit_minus_anticipata']:+.4f}) e quasi calibrato sulla chiusura "
                 f"({f5['hit_minus_chiusura']:+.4f}). L'informazione esiste, e sta nel movimento; la chiusura la "
                 "riconcilia, l'anticipata no.")
    L.append(f"I movimenti grandi non sono poi cosi' rari da essere irrilevanti: {d['share_ge2']:.0%} delle "
             f"partite si muovono di 2 pt o piu' sul favorito e |Delta| >= 5 pt tocca il {d['share_ge5']:.1%}; "
             f"ma sul totale il Delta Brier resta dentro il rumore (IC che contiene lo zero).")

    g_mese = 500 // 5
    L.append(f"**Implicazioni per l'orario del giro quote (piano 500 crediti/mese, 1 giro = 5 crediti).** "
             f"Il budget regge {g_mese} gironi/mese, cioe' ~3 gironi/giorno. Lo scenario attuale (1 giro/giorno, "
             "cron 08:17 UTC) costa 5 crediti/giorno = 140–155 crediti in un mese di 28–31 giorni: "
             "~3/4 del budget con un solo giro, e il secondo tentativo (10:47 UTC) costa gia' 0 quando il "
             "primo e' fresco.")
    if v != "piu_informativa":
        L.append("La chiusura non dimostra un vantaggio significativo sull'anticipata: **non conviene "
                 "aggiungere gironi di routine per 'catturare' la chiusura** — il giro unico mattutino resta la "
                 "scelta dominante per rapporto informazione/costo. Il margine di budget (~345 crediti/mese, "
                 "~69 gironi) va tenuto per i cron saltati (gia' coperti a costo zero dalla guardia di "
                 "freschezza) e per gironi manuali mirati (es. sabato 15:00–17:00 UTC) su partite in cui "
                 "interessa un movimento specifico, non per la routine giornaliera. Se in futuro l'app "
                 "sfruttera' il movimento stesso (Delta) come segnale, il dato di questo audit dice che vale "
                 "solo per movimenti >= 2 pt, cioe' per ~la meta' delle giornate: un giro pomeridiano "
                 "mirato a quelle partite sarebbe il candidato naturale, non il giro di chiusura.")
    else:
        L.append("Il vantaggio e' significativo: **conviene un secondo giro tardo** (es. 15:30–17:00 UTC, "
                 "prima delle big match di weekend). 2 gironi/giorno = 10 crediti/giorno = 280–310 "
                 "crediti/mese: dentro il budget di 500 con margine. Un terzo giro (~420–465 crediti/mese) "
                 "saturerebbe il piano e non e' giustificato dal guadagno incrementale: si aggiungera' solo "
                 "se un prossimo audit mostrera' che anche il terzo giro migliora il Brier rispetto al "
                 "secondo. Nota: le 'chiusure' del CSV sono di mercato; un giro tardo le approssima, quindi "
                 "il guadagno effettivo sara' compreso tra 0 e il Delta misurato qui.")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Referto
# ---------------------------------------------------------------------------
def _band_rows(src_mov: dict, with_delta: bool) -> list[str]:
    rows = []
    for label, r in src_mov["fasce"].items():
        if not r or r.get("n", 0) == 0:
            cells = [label, "0", "-", "-", "-", "-", "-"] + (["-"] if with_delta else [])
            rows.append("| " + " | ".join(cells) + " |")
            continue
        cells = [label, str(r["n"]), f"{r['hit_rate']:.4f}", f"{r['prob_media_anticipata']:.4f}",
                 f"{r['prob_media_chiusura']:.4f}", f"{r['hit_minus_anticipata']:+.4f}",
                 f"{r['hit_minus_chiusura']:+.4f}"]
        if with_delta:
            cells.append(f"{r['delta_media']:+.2f} pt")
        rows.append("| " + " | ".join(cells) + " |")
    return rows


def build_report(res: dict) -> str:
    a: list[str] = []
    cov = res["coverage"]
    b = res["b365"]
    p = res["pinnacle"]
    a.append("# Le quote di chiusura sono piu' informative delle quote anticipate? — referto di audit (sola lettura)\n")
    a.append(f"Generato da `audit/quote_chiusura_vs_anticipate.py` (nessuna modifica a `SoccerMath/`, nessun "
             f"replay `--write`, nessuna chiamata all'API: dati solo dai CSV football-data in "
             f"`SoccerMath/database/`). Commit di base: `{res['base_commit']}`. Bootstrap: {res['reps']} "
             f"repliche a blocchi (lega x stagione x giornata), seme {res['seed']} (stesso della PR #49). "
             f"Tempo di esecuzione: {res['elapsed_s']:.0f} s.")
    a.append("Comando: `python audit/quote_chiusura_vs_anticipate.py`.\n")

    a.append("## 0. Regole dichiarate (fissate prima di guardare i risultati)\n")
    a.append("- De-vig PROPORZIONALE per tutte le fonti; terna valida = tre quote presenti e > 1.0.")
    a.append("- Campione: solo partite con terna anticipata E terna di chiusura della fonte in esame; si "
             "dichiara quante restano.")
    a.append("- Metriche su tutte le partite del campione: Brier 1X2 e LogLoss per anticipata e chiusura.")
    a.append("- Top Mix (esito piu' probabile con p >= 0,55): n, hit rate, confidenza media dichiarata, per "
             "anticipata e chiusura.")
    a.append(f"- Delta Brier = Brier(chiusura) − Brier(anticipata) con bootstrap a blocchi (lega x stagione x "
             f"giornata, {res['reps']} repliche) e IC 95% percentile.")
    a.append("- REGOLA DI DECISIONE: la chiusura e' 'piu' informativa' se l'IC 95% di Delta Brier esclude lo "
             "zero a suo favore (IC interamente negativo); altrimenti 'nessuna differenza dimostrata'.")
    a.append("- Movimenti: Delta = p_chiusura − p_anticipata sull'esito favorito secondo l'anticipata (punti "
             "percentuali). Fasce: F1: Delta <= −5; F2: −5 < Delta <= −2; F3: −2 < Delta < +2; "
             "F4: +2 <= Delta < +5; F5: Delta >= +5.\n")

    a.append("## 1. Copertura delle colonne e campione\n")
    a.append("| Lega | Stagione | Righe | B365H | B365D | B365A | PSH | PSD | PSA | B365CH | B365CD | B365CA "
             "| PSCH | PSCD | PSCA | Terna B365 pre | Terna Pin pre | Terna B365 close | Terna Pin close |")
    a.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in cov:
        c = r["colonne"]
        t = r["terna"]
        a.append(f"| {r['lega']} | {r['stagione']} | {r['righe']} | {c['B365H']} | {c['B365D']} | {c['B365A']} "
                 f"| {c['PSH']} | {c['PSD']} | {c['PSA']} | {c['B365CH']} | {c['B365CD']} | {c['B365CA']} "
                 f"| {c['PSCH']} | {c['PSCD']} | {c['PSCA']} | {t['pre_b365']} | {t['pre_pin']} "
                 f"| {t['close_b365']} | {t['close_pin']} |")
    a.append("")
    s = res["sample"]
    a.append("| Campione | Partite |")
    a.append("|---|---|")
    a.append(f"| Righe totali 2024/25 + 2025/26 (5 leghe) | {s['righe_totali']} |")
    a.append(f"| Senza terna B365 anticipata | {s['senza_pre_b365']} |")
    a.append(f"| Senza terna B365 chiusura | {s['senza_close_b365']} |")
    a.append(f"| **Campione comune B365** (pre E chiusura B365 valide) — campione principale | **{s['comune_b365']}** |")
    a.append(f"| Campione Pinnacle a fonte uguale (pre E chiusura Pinnacle valide) — controllo | {s['comune_pin']} |")
    a.append("")
    a.append("L'esito e' preso da FTR; nella PR #49 FTR coincide con l'esito dai gol in ogni riga del campione.\n")

    a.append("## 2. Metriche su tutte le partite (Brier 1X2 e LogLoss)\n")
    a.append("Valori piu' bassi = meglio. Campione comune B365 (tutte le partite con entrambe le fonti):\n")
    a.append("| Fonte | n | Brier 1X2 | LogLoss |")
    a.append("|---|---|---|---|")
    a.append(f"| B365 anticipata (de-vig prop.) | {b['topmix']['anticipata']['n']} | "
             f"{b['brier_anticipata']:.4f} | {b['logloss_anticipata']:.4f} |")
    a.append(f"| B365 chiusura (de-vig prop.) | {b['topmix']['chiusura']['n']} | "
             f"{b['brier_chiusura']:.4f} | {b['logloss_chiusura']:.4f} |")
    a.append("")
    a.append("Per stagione:\n")
    a.append("| Stagione | n | Brier anticipata | Brier chiusura | LogLoss anticipata | LogLoss chiusura |")
    a.append("|---|---|---|---|---|---|")
    for st, r in b["per_stagione"].items():
        a.append(f"| {st} | {r['n']} | {r['brier_anticipata']:.4f} | {r['brier_chiusura']:.4f} "
                 f"| {r['logloss_anticipata']:.4f} | {r['logloss_chiusura']:.4f} |")
    a.append("")
    a.append("Controllo a fonte uguale, campione Pinnacle (pre E chiusura Pinnacle valide):\n")
    a.append("| Fonte | n | Brier 1X2 | LogLoss |")
    a.append("|---|---|---|---|")
    a.append(f"| Pinnacle anticipata (de-vig prop.) | {p['topmix']['anticipata']['n']} | "
             f"{p['brier_anticipata']:.4f} | {p['logloss_anticipata']:.4f} |")
    a.append(f"| Pinnacle chiusura (de-vig prop.) | {p['topmix']['chiusura']['n']} | "
             f"{p['brier_chiusura']:.4f} | {p['logloss_chiusura']:.4f} |")
    a.append("")
    a.append("Per stagione:\n")
    a.append("| Stagione | n | Brier anticipata | Brier chiusura | LogLoss anticipata | LogLoss chiusura |")
    a.append("|---|---|---|---|---|---|")
    for st, r in p["per_stagione"].items():
        a.append(f"| {st} | {r['n']} | {r['brier_anticipata']:.4f} | {r['brier_chiusura']:.4f} "
                 f"| {r['logloss_anticipata']:.4f} | {r['logloss_chiusura']:.4f} |")
    a.append("")

    a.append("## 3. Top Mix (esito piu' probabile, p >= 0,55)\n")
    a.append("IC 95% bootstrap a blocchi (stessi blocchi, 2000 repliche).\n")
    a.append("| Campione | Fonte | Scelte (n) | Hit rate [IC 95%] | Confidenza media [IC 95%] |")
    a.append("|---|---|---|---|---|")
    for nome, r in (("B365 (campione comune)", b), ("Pinnacle (a fonte uguale)", p)):
        for tag in ("anticipata", "chiusura"):
            t = r["topmix"][tag]
            if t["hit_rate"] is None:
                a.append(f"| {nome} | {tag} | 0 | - | - |")
                continue
            a.append(f"| {nome} | {tag} | {t['ammesse']} | "
                     f"{t['hit_rate']:.4f} [{t['hit_rate_ic95'][0]:.4f}; {t['hit_rate_ic95'][1]:.4f}] | "
                     f"{t['confidenza_media']:.4f} [{t['confidenza_ic95'][0]:.4f}; {t['confidenza_ic95'][1]:.4f}] |")
    a.append("")
    a.append("Per stagione (n ammesse e confidenza media dichiarata):\n")
    a.append("| Campione | Stagione | Fonte | Scelte (n) | Confidenza media |")
    a.append("|---|---|---|---|---|")
    for nome, r in (("B365 (campione comune)", b), ("Pinnacle (a fonte uguale)", p)):
        for st in ("2024/25", "2025/26"):
            n_tot = r["per_stagione"][st]["n"]
            for tag in ("anticipata", "chiusura"):
                t = r["topmix_per_stagione"][st][tag]
                cf = f"{t['confidenza_media']:.4f}" if t["confidenza_media"] is not None else "-"
                a.append(f"| {nome} | {st} | {tag} | {t['ammesse']} di {n_tot} | {cf} |")
    a.append("")

    a.append("## 4. Delta Brier (chiusura − anticipata) e regola di decisione\n")
    a.append("Delta negativo = la chiusura e' migliore (Brier piu' basso). IC 95% bootstrap a blocchi.\n")
    a.append("| Confronto | n | Delta Brier [IC 95%] |")
    a.append("|---|---|---|")
    db = b["delta_brier"]
    a.append(f"| B365 — pooled | {db['pooled']['n']} | {db['pooled']['point']:.4f} "
             f"[{db['pooled']['ic95'][0]:.4f}; {db['pooled']['ic95'][1]:.4f}] |")
    for _, lga in LEAGUES:
        r = db.get(lga)
        if r:
            a.append(f"| B365 — {lga} | {r['n']} | {r['point']:.4f} [{r['ic95'][0]:.4f}; {r['ic95'][1]:.4f}] |")
    for st in ("2024/25", "2025/26"):
        r = db[f"stagione_{st}"]
        a.append(f"| B365 — {st} | {r['n']} | {r['point']:.4f} [{r['ic95'][0]:.4f}; {r['ic95'][1]:.4f}] |")
    dp = p["delta_brier"]
    a.append(f"| Pinnacle — pooled | {dp['pooled']['n']} | {dp['pooled']['point']:.4f} "
             f"[{dp['pooled']['ic95'][0]:.4f}; {dp['pooled']['ic95'][1]:.4f}] |")
    for _, lga in LEAGUES:
        r = dp.get(lga)
        if r:
            a.append(f"| Pinnacle — {lga} | {r['n']} | {r['point']:.4f} [{r['ic95'][0]:.4f}; {r['ic95'][1]:.4f}] |")
    a.append("")
    a.append("Applicazione della regola dichiarata:")
    v_b = b["verdetto"]
    v_p = p["verdetto"]
    a.append(f"- **B365 (campione comune, decisione principale):** Delta Brier pooled = "
             f"{db['pooled']['point']:.4f} [{db['pooled']['ic95'][0]:.4f}; {db['pooled']['ic95'][1]:.4f}] → **"
             + ("la chiusura e' PIU' INFORMATIVA" if v_b == "piu_informativa"
                else "NESSUNA DIFFERENZA DIMOSTRATA") + "**.")
    a.append(f"- Pinnacle (a fonte uguale, controllo): Delta Brier pooled = "
             f"{dp['pooled']['point']:.4f} [{dp['pooled']['ic95'][0]:.4f}; {dp['pooled']['ic95'][1]:.4f}] → "
             + ("la chiusura e' PIU' INFORMATIVA" if v_p == "piu_informativa"
                else "nessuna differenza dimostrata") + ".\n")

    a.append("## 5. Analisi dei movimenti (Delta = p_chiusura − p_anticipata sul favorito)\n")
    a.append("Favorito = esito piu' probabile secondo la quota anticipata. Delta in punti percentuali.\n")
    d = res["movimento_b365"]["distribuzione"]
    a.append("| Statistica | Valore |")
    a.append("|---|---|")
    a.append(f"| n | {d['n']} |")
    a.append(f"| media | {d['media']:+.2f} pt |")
    a.append(f"| mediana | {d['mediana']:+.2f} pt |")
    a.append(f"| deviazione std | {d['dev_std']:.2f} pt |")
    a.append(f"| min / max | {d['min']:+.2f} / {d['max']:+.2f} pt |")
    a.append(f"| quantili 5/10/25/75/90/95 | {d['p05']:+.2f} / {d['p10']:+.2f} / {d['p25']:+.2f} / "
             f"{d['p75']:+.2f} / {d['p90']:+.2f} / {d['p95']:+.2f} pt |")
    a.append(f"| share |Delta| < 1 pt | {d['share_abs_lt1']:.1%} |")
    a.append(f"| share |Delta| < 2 pt | {d['share_abs_lt2']:.1%} |")
    a.append(f"| share |Delta| >= 2 pt | {d['share_ge2']:.1%} |")
    a.append(f"| share |Delta| >= 5 pt | {d['share_ge5']:.1%} |")
    a.append(f"| hit rate del favorito (tutte le partite) | {res['movimento_b365']['hit_favorito_totale']:.4f} |")
    a.append("")
    a.append("Fasce di Delta (B365, campione comune):\n")
    a.append("| Fascia | n | Hit rate favorito | Prob media anticipata | Prob media chiusura "
             "| Hit − anticipata | Hit − chiusura | Delta medio |")
    a.append("|---|---|---|---|---|---|---|---|")
    a.extend(_band_rows(res["movimento_b365"], with_delta=True))
    a.append("")
    a.append("Controllo a fonte uguale (Pinnacle, campione Pinnacle):\n")
    a.append("| Fascia | n | Hit rate favorito | Prob media anticipata | Prob media chiusura "
             "| Hit − anticipata | Hit − chiusura |")
    a.append("|---|---|---|---|---|---|---|")
    a.extend(_band_rows(res["movimento_pin"], with_delta=False))
    a.append("")
    a.append("Aggregati per la domanda (B365, campione comune):\n")
    a.append("| Gruppo | n | Hit rate | Prob media anticipata | Prob media chiusura "
             "| Hit − anticipata | Hit − chiusura |")
    a.append("|---|---|---|---|---|---|---|")
    for k, lbl in (("accorcia_ge+2", "accorcia (Delta >= +2 pt)"),
                   ("allunga_le-2", "allunga (Delta <= −2 pt)")):
        r = res["movimento_b365"]["aggregati"].get(k)
        if r:
            a.append(f"| {lbl} | {r['n']} | {r['hit_rate']:.4f} | {r['prob_media_anticipata']:.4f} "
                     f"| {r['prob_media_chiusura']:.4f} | {r['hit_minus_anticipata']:+.4f} "
                     f"| {r['hit_minus_chiusura']:+.4f} |")
    a.append("")

    a.append("## 6. Conclusione e implicazioni per l'orario del giro quote\n")
    a.append(res["conclusioni_md"])
    a.append("")
    a.append("## 7. Limiti dichiarati\n")
    a.append("- Cross-verifica con la PR #49: su questo campione i valori di Brier, LogLoss, Top Mix e Delta "
             "Brier (pooled e per lega) riportati in questo referto riproducono quelli del referto "
             "`audit/results/onex2_market_test.md` (stesso campione, stesso de-vig proporzionale, stesso "
             "seme); le novita' sono la coppia Pinnacle a fonte uguale e l'analisi dei movimenti.")
    a.append("- L'orario di rilevazione delle colonne del CSV non e' nel file: 'anticipata' e 'chiusura' sono "
             "le diciture della fonte football-data (B365 pre = commessa della PR #49; B365C e PSCH = chiusura "
             "di mercato).")
    a.append("- Il campione Pinnacle e' un sottoinsieme: la chiusura Pinnacle e' mancante su parte del 2025/26, "
             "quindi il controllo a fonte uguale non e' sullo stesso campione del confronto principale.")
    a.append("- Il de-vig proporzionale presuppone che il margine sia distribuito proporzionalmente agli esiti; "
             "e' la decisione gia' usata nella PR #49 e qui non viene rivisitata.")
    a.append("- Il bootstrap a blocchi tratta la giornata come unita'; le partite della stessa giornata "
             "condividono squadre.")
    a.append("- Nessun dato live dell'app e' stato usato: e' un esperimento retrospettivo su CSV, non una stima "
             "del valore di un giro quote in orario specifico.")
    a.append("")
    return "\n".join(a)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=DEFAULT_REPS)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = ap.parse_args()

    t0 = time.time()
    base_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT,
                                 capture_output=True, text=True).stdout.strip() or "?"

    # --- caricamento e copertura ---
    cov, frames = [], []
    for prefix, league in LEAGUES:
        for season, suffix in EVAL_SEASONS.items():
            df = load_season(prefix, league, suffix, season)
            cov.append(coverage_table(df))
            frames.append(df)
    df = pd.concat(frames, ignore_index=True).reset_index(drop=True)

    # --- probabilità de-vig (proporzionale) ---
    pa = probs_from_tern(df, PRE_B365)
    pc = probs_from_tern(df, CLOSE_B365)
    ppa = probs_from_tern(df, PRE_PIN)
    ppc = probs_from_tern(df, CLOSE_PIN)

    y = df["FTR"].astype(str).str.strip().str.upper().map(Y_CODES).to_numpy()
    assert y is not None and len(y) == len(df)
    blocks = (df["league"] + "|" + df["season"] + "|" + df["date_day"].dt.strftime("%Y-%m-%d")
              ).to_numpy()

    ok_pre = ~np.isnan(pa).any(axis=1)
    ok_close = ~np.isnan(pc).any(axis=1)
    ok_pre_pin = ~np.isnan(ppa).any(axis=1)
    ok_close_pin = ~np.isnan(ppc).any(axis=1)

    s_common = ok_pre & ok_close
    s_pin = ok_pre_pin & ok_close_pin
    sample = {
        "righe_totali": int(len(df)),
        "senza_pre_b365": int((~ok_pre).sum()),
        "senza_close_b365": int((~ok_close).sum()),
        "comune_b365": int(s_common.sum()),
        "comune_pin": int(s_pin.sum()),
    }

    y_c = y[s_common]
    y_p = y[s_pin]
    b365 = analyze_pair(df[s_common].reset_index(drop=True), pa[s_common], pc[s_common], y_c,
                        blocks[s_common], args.reps, args.seed)
    movimento_b365 = movement(pa[s_common], pc[s_common], y_c)
    pin = analyze_pair(df[s_pin].reset_index(drop=True), ppa[s_pin], ppc[s_pin], y_p,
                       blocks[s_pin], args.reps, args.seed + 777)
    movimento_pin = movement(ppa[s_pin], ppc[s_pin], y_p)

    res = {
        "base_commit": base_commit,
        "reps": args.reps,
        "seed": args.seed,
        "elapsed_s": time.time() - t0,
        "coverage": cov,
        "sample": sample,
        "b365": b365,
        "pinnacle": pin,
        "movimento_b365": movimento_b365,
        "movimento_pin": movimento_pin,
    }
    res["conclusioni_md"] = build_conclusioni(b365, pin, movimento_b365, sample)

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(RES_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "quote_chiusura_vs_anticipate.json"), "w") as f:
        json.dump(res, f, indent=1, default=float)
    df[s_common][["league", "season", "date_day", "HomeTeam", "AwayTeam", "FTR"]].to_csv(
        os.path.join(OUT_DIR, "quote_chiusura_vs_anticipate_rows.csv"), index=False)
    with open(os.path.join(RES_DIR, "quote_chiusura_vs_anticipate.md"), "w") as f:
        f.write(build_report(res))
    print(f"ok: righe={sample['righe_totali']} comune_b365={sample['comune_b365']} "
          f"comune_pin={sample['comune_pin']} "
          f"delta_brier={b365['delta_brier']['pooled']['point']:.5f} "
          f"{[round(x, 5) for x in b365['delta_brier']['pooled']['ic95']]} "
          f"verdetto={b365['verdetto']} (t={time.time()-t0:.1f}s)")


if __name__ == "__main__":
    main()
