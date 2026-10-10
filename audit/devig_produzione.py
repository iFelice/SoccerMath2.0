#!/usr/bin/env python3
"""devig_produzione.py — punto 1: quale de-vig per la produzione (Pinnacle 1X2).

Audit di SOLA LETTURA: nessuna modifica a SoccerMath/ (app.py incluso), nessun
replay con --write, nessuna chiamata di rete, nessuna chiave, nessuna scrittura
nel Registro. Legge solo i CSV football-data gia' nel repository.

REGOLE DICHIARATE (scritte PRIMA dei numeri, non modificate dopo; identiche a
§0.1 di audit/results/referto_audit_devig_linee_2026-10-10.md):

  R1.1 Dati. Terna 1X2. Sorgente PRINCIPALE: Pinnacle di PRE-CHIUSURA
       (PSH/PSD/PSA), perche' la produzione usa le quote del mattino.
       SENSIBILITA': Pinnacle di CHIUSURA (PSCH/PSCD/PSCA); non entra nella
       regola di decisione. L'Over/Under 2,5 Pinnacle (P>2.5/P<2.5 e
       PC>2.5/PC<2.5) serve solo al fit della griglia e alla verifica di
       riproduzione della terna, non alla metrica.
  R1.2 Campioni. 5 leghe (SerieA, Premier, LaLiga, Bundesliga, Ligue1).
       PRIMARIO = stagioni 2022/23 e 2023/24 (file _2022, _2023).
       CONFERMA = stagioni 2024/25 e 2025/26 (file _2024, _2025).
       Una partita entra se la terna 1X2 Pinnacle e' completa e valida (tre
       quote finite e > 1) e la coppia O/U 2,5 Pinnacle e' completa e valida.
       Dedup su lega x data x casa x trasferta (keep last), come PR #58/#59.
  R1.3 Metodi. Proporzionale (produzione), potenza, Shin. Riferimento:
       proporzionale. Tutte le differenze sono metodo - proporzionale.
  R1.4 Metrica. LogLoss = -log p(esito reale), con p limitata a [1e-12; 1].
       Brier multiclasse = somma sui tre esiti di (p_k - y_k)^2.
       Delta = metodo - proporzionale, appaiato per partita; negativo = meglio.
       La griglia Dixon-Coles fittata su 1X2 + O/U 2,5 ha 3 parametri e 3
       vincoli indipendenti (P1+PX+P2 = 1 piu' P(Over 2,5)): riproduce quindi
       ESATTAMENTE la terna in ingresso e la metrica e' calcolata direttamente
       sulle probabilita' de-vigate. L'equivalenza e' VERIFICATA sui dati su un
       sottocampione casuale (seme dichiarato), non assunta.
  R1.5 Bootstrap. Blocchi = lega x stagione x data. 2000 repliche, IC 95%
       percentile. Semi: 20261020 (metrica), 20261021 (calibrazione),
       20261022 (descrittivo topmix).
  R1.6 Calibrazione dell'esito piu' probabile (argmax, primo massimo in ordine
       1, X, 2). Fasce di p: [0,55-0,65), [0,65-0,75), >= 0,75. Per fascia:
       n, p media, frequenza f, f - p con segno e IC 95% a blocchi.
  R1.7 REGOLA DI DECISIONE (sulle quote di PRE-CHIUSURA, metrica LogLoss):
         (a) si propone la POTENZA per la produzione se sul campione PRIMARIO
             l'IC 95% di ΔLogLoss(potenza - proporzionale) e' interamente
             sotto zero E sul campione di CONFERMA la stima puntuale dello
             stesso Delta e' <= 0;
         (b) SHIN sostituisce la potenza SOLO se l'IC 95% di
             ΔLogLoss(Shin - potenza) e' interamente sotto zero sul campione
             PRIMARIO;
         (c) in ogni altro caso resta il PROPORZIONALE.
       Il Brier e' secondario e non decide. La chiusura e' sensibilita'.
  R1.8 Parte descrittiva sul campione delle 3.504 partite (B365, 2024/25 +
       2025/26, stesso campione di PR #59): per ciascun metodo si contano le
       scelte che superano la soglia p >= 0,55 del selettore
       topmix_mercato_v3 (argmax della terna de-vigata, primo massimo in
       ordine 1, X, 2; regola di app.seleziona_riga_top_mix_mercato), il loro
       hit rate, e quante scelte cambiano esito, entrano o escono dalla soglia
       rispetto al proporzionale. Sorgente: B365 (quella che definisce il
       campione); Pinnacle di pre-chiusura come sensibilita'. Nessuna
       regola di decisione: solo conteggi.

Output: audit/results/punto1_devig_produzione.md (versionato),
        audit/output/punto1_devig.json (non versionato).
Uso: python audit/devig_produzione.py
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

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO, "SoccerMath"))  # config.clean_name (sola lettura)

from config import clean_name  # noqa: E402
from griglia_core import (  # noqa: E402
    DEVIG, block_bootstrap_mean_diff, dc_matrix, fit_implicit, grid_1x2_ou,
)

DB_DIR = os.path.join(_REPO, "SoccerMath", "database")
OUT_DIR = os.path.join(_AUDIT_DIR, "output")
REPORT = os.path.join(_AUDIT_DIR, "results", "punto1_devig_produzione.md")
JSON_OUT = os.path.join(OUT_DIR, "punto1_devig.json")

LEAGUES = [("SerieA", "Serie A"), ("Premier", "Premier League"), ("LaLiga", "La Liga"),
           ("Bundesliga", "Bundesliga"), ("Ligue1", "Ligue 1")]

# nome stagione -> suffisso del file CSV
SEASON_FILE = OrderedDict([("2022/23", "2022"), ("2023/24", "2023"),
                           ("2024/25", "2024"), ("2025/26", "2025")])
PRIMARY_SEASONS = ("2022/23", "2023/24")
CONFIRM_SEASONS = ("2024/25", "2025/26")

PS = ["PSH", "PSD", "PSA"]                 # Pinnacle pre-chiusura 1X2
PS_OU = ["P>2.5", "P<2.5"]                 # Pinnacle pre-chiusura O/U 2,5
PSC = ["PSCH", "PSCD", "PSCA"]             # Pinnacle chiusura 1X2
PSC_OU = ["PC>2.5", "PC<2.5"]              # Pinnacle chiusura O/U 2,5
B365 = ["B365H", "B365D", "B365A"]
B365_OU = ["B365>2.5", "B365<2.5"]

QCOLS = (["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"]
         + PS + PS_OU + PSC + PSC_OU + B365 + B365_OU)

REPS = 2000
SEED_METRIC = 20261020
SEED_CALIB = 20261021
SEED_TOPMIX = 20261022
SEED_VERIFICA = 20261023
N_VERIFICA = 500            # partite del sottocampione di verifica griglia <-> de-vig
SOGLIA_TOPMIX = 0.55        # soglia di produzione del selettore topmix_mercato_v3
CAL_BANDS = OrderedDict([("0,55-0,65", (0.55, 0.65)), ("0,65-0,75", (0.65, 0.75)),
                         ("≥0,75", (0.75, 1.0000001))])
LOG_CLIP = 1e-12


# ---------------------------------------------------------------------------
# Caricamento
# ---------------------------------------------------------------------------
def load_quotes(prefix: str, league: str, seasons) -> pd.DataFrame:
    frames = []
    for season in seasons:
        raw = pd.read_csv(os.path.join(DB_DIR, f"{prefix}_{SEASON_FILE[season]}.csv"),
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


def load_all(seasons) -> pd.DataFrame:
    return pd.concat([load_quotes(p, l, seasons) for p, l in LEAGUES], ignore_index=True)


# ---------------------------------------------------------------------------
# Campioni
# ---------------------------------------------------------------------------
def devig_cols(df: pd.DataFrame, cols, fn):
    """De-vig riga per riga su `cols` (1 riga -> vettore) con il metodo `fn`."""
    out, valid = [], []
    for row in df[cols].to_numpy(dtype=float):
        p = fn(row)
        ok = p is not None and np.all(np.isfinite(p))
        valid.append(ok)
        out.append(p if ok else np.full(len(cols), np.nan))
    return np.array(out, dtype=float), np.array(valid)


def build_sample(df: pd.DataFrame, cols3, cols2, methods):
    """Filtra su quote complete e valide, poi de-viga con ogni metodo.

    Ritorna (m, dict metodo -> (P3, PO)) dove P3 e' (n x 3) e PO e' (n,) = P(Over 2,5).
    """
    ok = df[cols3 + cols2].notna().all(axis=1)
    m = df[ok].reset_index(drop=True)
    res = {}
    keep = None
    for name, fn in methods.items():
        P3, v3 = devig_cols(m, cols3, fn)
        PO, v2 = devig_cols(m, cols2, fn)
        v = v3 & v2
        keep = v if keep is None else (keep & v)
        res[name] = (P3, PO[:, 0], v)
    m = m[keep].reset_index(drop=True)
    out = {}
    for name, (P3, PO, v) in res.items():
        out[name] = (P3[keep], PO[keep])
    return m, out


def outcome_1x2(m: pd.DataFrame) -> np.ndarray:
    h = m["FTHG"].to_numpy(dtype=int)
    a = m["FTAG"].to_numpy(dtype=int)
    return np.stack([h > a, h == a, h < a], axis=1).astype(float)


def blocks_of(m: pd.DataFrame) -> np.ndarray:
    return (m["league"] + "|" + m["season"] + "|" + m["date_day"].dt.strftime("%Y-%m-%d")).to_numpy()


# ---------------------------------------------------------------------------
# Metriche
# ---------------------------------------------------------------------------
def logloss(P3: np.ndarray, Y: np.ndarray) -> np.ndarray:
    p = np.clip(np.sum(P3 * Y, axis=1), LOG_CLIP, 1.0)
    return -np.log(p)


def brier3(P3: np.ndarray, Y: np.ndarray) -> np.ndarray:
    return np.sum((P3 - Y) ** 2, axis=1)


def boot(d: np.ndarray, blocks: np.ndarray, seed: int):
    rng = np.random.default_rng(seed)
    return block_bootstrap_mean_diff(d, blocks, REPS, rng)


def boot_fp(num, den, blocks: np.ndarray, seed: int, reps: int = REPS):
    """IC 95% a blocchi di sum(num)/sum(den) (per f - p in una fascia)."""
    labels, inv = np.unique(blocks, return_inverse=True)
    nb = len(labels)
    rng = np.random.default_rng(seed)
    draws = rng.multinomial(nb, np.full(nb, 1.0 / nb), size=reps).astype(float)
    S_n = np.bincount(inv, weights=num, minlength=nb)
    S_d = np.bincount(inv, weights=den, minlength=nb)
    n_b, d_b = draws @ S_n, draws @ S_d
    stat = np.where(d_b > 0, n_b / np.maximum(d_b, 1e-12), np.nan)
    lo, hi = np.nanpercentile(stat, [2.5, 97.5])
    return float(lo), float(hi)


# ---------------------------------------------------------------------------
# Formattazione (virgola decimale, come gli altri referti)
# ---------------------------------------------------------------------------
def fmt(x, nd=4):
    if x is None or (isinstance(x, (float, np.floating)) and not np.isfinite(x)):
        return "n/d"
    return f"{float(x):.{nd}f}".replace(".", ",")


def pct(x, nd=2):
    return "n/d" if x is None else fmt(100.0 * float(x), nd) + " %"


def pts(x, nd=2):
    return "n/d" if x is None else fmt(100.0 * float(x), nd) + " pt"


def md_table(headers, rows):
    head = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join(["---"] * len(headers)) + "|"
    return "\n".join([head, sep] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


# ---------------------------------------------------------------------------
# Verifica: la griglia riproduce la terna de-vigata
# ---------------------------------------------------------------------------
def verifica_griglia(P3, PO, seed=SEED_VERIFICA, n=N_VERIFICA):
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(P3), size=min(n, len(P3)), replace=False)
    worst_1x2 = 0.0
    worst_all = 0.0
    for i in idx:
        f = fit_implicit(P3[i, 0], P3[i, 1], P3[i, 2], PO[i], rho_free=True)
        g = grid_1x2_ou(dc_matrix(f["lam"], f["mu"], f["rho"]))
        worst_1x2 = max(worst_1x2, float(np.max(np.abs(g[:3] - P3[i]))))
        worst_all = max(worst_all, f["max_abs_resid"])
    return {"n_verificati": int(len(idx)), "max_abs_1x2": worst_1x2, "max_residuo_4_vincoli": worst_all}


# ---------------------------------------------------------------------------
# Analisi di un campione
# ---------------------------------------------------------------------------
def analyse_sample(nome, m, P, Y):
    """P: dict metodo -> (P3, PO). Ritorna metriche, calibrazione e conteggi."""
    blocks = blocks_of(m)
    base = P["proporzionale"][0]
    ll0, br0 = logloss(base, Y), brier3(base, Y)
    out = {"nome": nome, "n": int(len(m)), "blocchi": int(len(np.unique(blocks))),
           "ll_prop": float(np.mean(ll0)), "brier_prop": float(np.mean(br0)),
           "delta": {}, "calibrazione": {}, "topmix": {}}
    for meth in ("potenza", "Shin"):
        P3 = P[meth][0]
        d_ll = logloss(P3, Y) - ll0
        d_br = brier3(P3, Y) - br0
        out["delta"][meth] = {
            "logloss": boot(d_ll, blocks, SEED_METRIC),
            "brier": boot(d_br, blocks, SEED_METRIC),
        }
    # ΔLogLoss(Shin - potenza): serve alla regola (b)
    d_sp = logloss(P["Shin"][0], Y) - logloss(P["potenza"][0], Y)
    out["delta"]["Shin-potenza"] = {"logloss": boot(d_sp, blocks, SEED_METRIC)}

    # calibrazione dell'esito piu' probabile
    for meth in ("proporzionale", "potenza", "Shin"):
        P3 = P[meth][0]
        k = np.argmax(P3, axis=1)
        p = P3[np.arange(len(P3)), k]
        y = Y[np.arange(len(Y)), k]
        rows = []
        for bname, (lo, hi) in CAL_BANDS.items():
            sel = (p >= lo) & (p < hi)
            n = int(sel.sum())
            if n == 0:
                rows.append({"fascia": bname, "n": 0, "p": None, "f": None, "fp": None,
                             "lo": None, "hi": None})
                continue
            fp = float(y[sel].mean() - p[sel].mean())
            lo_ci, hi_ci = boot_fp(np.where(sel, y - p, 0.0), sel.astype(float),
                                   blocks, SEED_CALIB)
            rows.append({"fascia": bname, "n": n, "p": float(p[sel].mean()),
                         "f": float(y[sel].mean()), "fp": fp, "lo": lo_ci, "hi": hi_ci})
        out["calibrazione"][meth] = rows

    # descrittivo topmix (soglia 0,55)
    for meth in ("proporzionale", "potenza", "Shin"):
        P3 = P[meth][0]
        k = np.argmax(P3, axis=1)
        p = P3[np.arange(len(P3)), k]
        y = Y[np.arange(len(Y)), k]
        sel = p >= SOGLIA_TOPMIX
        out["topmix"][meth] = {"scelte": int(sel.sum()), "hit": int(y[sel].sum()),
                               "hit_rate": float(y[sel].mean()) if sel.any() else None,
                               "esito": k, "p": p, "y": y, "sel": sel}
    return out, blocks


def topmix_transitions(res):
    """Conteggi di transizione rispetto al proporzionale (campione completo)."""
    base = res["topmix"]["proporzionale"]
    kb, pb, yb, sb = base["esito"], base["p"], base["y"], base["sel"]
    out = {}
    for meth in ("potenza", "Shin"):
        o = res["topmix"][meth]
        k, p, y, s = o["esito"], o["p"], o["y"], o["sel"]
        out[meth] = {
            "cambia_esito_tutte": int(np.sum(k != kb)),
            "cambia_esito_tra_scelte": int(np.sum((k != kb) & sb & s)),
            "entra": int(np.sum(~sb & s)),
            "esce": int(np.sum(sb & ~s)),
            "scelte_prop": int(sb.sum()),
            "scelte_metodo": int(s.sum()),
            "hit_rate_prop": float(yb[sb].mean()) if sb.any() else None,
            "hit_rate_metodo": float(y[s].mean()) if s.any() else None,
            # hit rate sulle sole scelte che ENTRANO (nuove rispetto al proporzionale)
            "hit_rate_entrate": float(y[~sb & s].mean()) if np.any(~sb & s) else None,
            "hit_rate_uscite": float(yb[sb & ~s].mean()) if np.any(sb & ~s) else None,
        }
    return out


def decide(primary, confirm):
    """Regola R1.7. primary/confirm: dict con ['delta']['potenza']['logloss'] ecc."""
    dp = primary["delta"]["potenza"]["logloss"]
    dc = confirm["delta"]["potenza"]["logloss"]
    cond_a1 = dp["hi"] < 0
    cond_a2 = dc["mean"] <= 0
    proposta = "potenza" if (cond_a1 and cond_a2) else "proporzionale"
    dsp = primary["delta"]["Shin-potenza"]["logloss"]
    cond_b = dsp["hi"] < 0
    if proposta == "potenza" and cond_b:
        proposta = "Shin"
    return {"proposta": proposta,
            "cond_a1_IC_primario_tutta_sotto_zero": bool(cond_a1),
            "cond_a2_puntuale_conferma_le_zero": bool(cond_a2),
            "cond_b_IC_shin_meno_potenza_sotto_zero": bool(cond_b),
            "delta_potenza_primario": dp, "delta_potenza_conferma": dc,
            "delta_shin_meno_potenza_primario": dsp}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def build_md(meta, prim, conf, sens_prim, sens_conf, ver, topmix_b365, topmix_ps, decisione) -> str:
    T = []
    A = T.append
    A("## 1. Punto 1 — metodo di de-vig per la produzione (terna 1X2 Pinnacle)\n")
    A(f"Generato da `audit/devig_produzione.py` il {meta['generato']} · campione primario "
      f"{prim['n']} partite (2022/23 + 2023/24) · conferma {conf['n']} (2024/25 + 2025/26) · "
      "nessuna modifica a `SoccerMath/`, nessun `--write`, nessuna rete, nessuna chiave.\n")

    A("### 1.1 Copertura per lega e stagione (prima dei risultati)\n")
    A(md_table(["lega", "stagione", "partite con risultato",
                "1X2 + O/U 2,5 Pinnacle pre-chiusura completi",
                "1X2 + O/U 2,5 Pinnacle chiusura completi", "senza Pinnacle pre-chiusura",
                "date coperte da Pinnacle pre-chiusura"],
               meta["copertura"]))
    A("")
    A(meta["nota_copertura"] + "\n")

    A("### 1.2 Verifica: la griglia riproduce la terna de-vigata\n")
    A(f"Su {ver['n_verificati']} partite estratte a caso dal campione primario (seme {SEED_VERIFICA}) "
      "il fit Dixon-Coles su 1X2 + Over 2,5 restituisce una griglia la cui terna 1X2 differisce dalla "
      f"terna de-vigata in ingresso per al piu' **{ver['max_abs_1x2']:.2e}** (residuo massimo sui 4 "
      f"vincoli: {ver['max_residuo_4_vincoli']:.2e}). Il sistema ha 3 parametri e 3 vincoli "
      "indipendenti, quindi la metrica del punto 1 puo' essere calcolata direttamente sulle "
      "probabilita' de-vigate: la griglia non aggiunge e non toglie nulla.\n")

    A("### 1.3 ΔLogLoss e ΔBrier appaiati rispetto al proporzionale\n")
    for res, tag in ((prim, "campione PRIMARIO (2022/23 + 2023/24)"),
                     (conf, "campione di CONFERMA (2024/25 + 2025/26)")):
        A(f"**{tag} — Pinnacle di pre-chiusura — n = {res['n']}** "
          f"(LogLoss proporzionale {fmt(res['ll_prop'], 5)}, Brier proporzionale {fmt(res['brier_prop'], 5)})\n")
        rows = []
        for meth in ("potenza", "Shin", "Shin-potenza"):
            d = res["delta"][meth]
            for metrica, key in (("ΔLogLoss", "logloss"), ("ΔBrier", "brier")):
                if key == "brier" and meth == "Shin-potenza":
                    continue
                v = d[key]
                rows.append([f"{meth}" if key == "logloss" else f"{meth} ({metrica})",
                             metrica, fmt(v["mean"], 6),
                             f"[{fmt(v['lo'], 6)}; {fmt(v['hi'], 6)}]",
                             "IC tutta < 0" if v["hi"] < 0 else
                             ("IC tutta > 0" if v["lo"] > 0 else "IC contiene 0")])
        A(md_table(["confronto (metodo − proporzionale)", "metrica", "media per partita",
                    "IC 95% a blocchi", "lettura"], rows))
        A("")
    A("Negativo = meglio del proporzionale. Blocchi = lega × stagione × data; 2000 repliche; "
      f"seme {SEED_METRIC}.\n")

    A("### 1.4 Sensibilità: Pinnacle di chiusura\n")
    rows = []
    for res, tag in ((sens_prim, "primario (2022/23 + 2023/24)"), (sens_conf, "conferma (2024/25 + 2025/26)")):
        for meth in ("potenza", "Shin"):
            v = res["delta"][meth]["logloss"]
            rows.append([tag, meth, res["n"], fmt(v["mean"], 6),
                         f"[{fmt(v['lo'], 6)}; {fmt(v['hi'], 6)}]",
                         "IC tutta < 0" if v["hi"] < 0 else
                         ("IC tutta > 0" if v["lo"] > 0 else "IC contiene 0")])
    A(md_table(["campione (chiusura)", "metodo", "n", "ΔLogLoss medio", "IC 95%", "lettura"], rows))
    A("")

    A("### 1.5 Calibrazione dell'esito più probabile (argmax)\n")
    for res, tag in ((prim, "PRIMARIO (2022/23 + 2023/24)"), (conf, "CONFERMA (2024/25 + 2025/26)")):
        A(f"**{tag} — n = {res['n']}**\n")
        rows = []
        for meth in ("proporzionale", "potenza", "Shin"):
            for r in res["calibrazione"][meth]:
                if r["n"] == 0:
                    rows.append([meth, r["fascia"], 0, "n/d", "n/d", "n/d"])
                else:
                    rows.append([meth, r["fascia"], r["n"], pct(r["p"]), pct(r["f"]),
                                 f"{pts(r['fp'])} [{pts(r['lo'])}; {pts(r['hi'])}]"])
        A(md_table(["de-vig", "fascia di p", "n", "p media", "frequenza f", "f − p [IC 95%]"], rows))
        A("")

    A("### 1.6 Esito della regola dichiarata (R1.7)\n")
    d = decisione
    A(md_table(["condizione", "esito"], [
        ["(a1) IC 95% di ΔLogLoss(potenza − proporzionale) tutta < 0 sul primario",
         f"{'SÌ' if d['cond_a1_IC_primario_tutta_sotto_zero'] else 'NO'} "
         f"(IC [{fmt(d['delta_potenza_primario']['lo'], 6)}; {fmt(d['delta_potenza_primario']['hi'], 6)}])"],
        ["(a2) stima puntuale di ΔLogLoss(potenza − proporzionale) ≤ 0 sulla conferma",
         f"{'SÌ' if d['cond_a2_puntuale_conferma_le_zero'] else 'NO'} "
         f"(puntuale {fmt(d['delta_potenza_conferma']['mean'], 6)})"],
        ["(b) IC 95% di ΔLogLoss(Shin − potenza) tutta < 0 sul primario",
         f"{'SÌ' if d['cond_b_IC_shin_meno_potenza_sotto_zero'] else 'NO'} "
         f"(IC [{fmt(d['delta_shin_meno_potenza_primario']['lo'], 6)}; {fmt(d['delta_shin_meno_potenza_primario']['hi'], 6)}])"],
    ]))
    A("")
    A(f"**Proposta: {d['proposta']}.** (Solo proposta: nessuna modifica al codice di produzione "
      "in questo audit.)\n")

    A("### 1.7 Descrittivo: soglia p ≥ 0,55 di topmix_mercato_v3 sulle 3.504 partite\n")
    A("Campione delle 3.504 partite di PR #59 (B365, 2024/25 + 2025/26). Scelta = argmax della terna "
      f"de-vigata (primo massimo in ordine 1, X, 2) con p ≥ {fmt(SOGLIA_TOPMIX, 2)}, come in "
      "`app.seleziona_riga_top_mix_mercato`. Nessuna regola di decisione.\n")
    A("#### 1.7.1 Sorgente B365 (definisce il campione)\n")
    A(md_table(["de-vig", "scelte (p ≥ 0,55)", "hit rate", "cambia esito (su 3504)",
                "cambia esito restando sopra soglia", "entra", "esce"],
               topmix_b365["righe"]))
    A("")
    A(topmix_b365["nota"] + "\n")
    A("#### 1.7.2 Sensibilità: Pinnacle di pre-chiusura (stesse partite, dove disponibile)\n")
    A(md_table(["de-vig", "scelte (p ≥ 0,55)", "hit rate", "cambia esito",
                "cambia esito restando sopra soglia", "entra", "esce"],
               topmix_ps["righe"]))
    A("")
    A(topmix_ps["nota"] + "\n")
    return "\n".join(T) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-cache", action="store_true", help="non usato: nessuna cache in questo script")
    args = ap.parse_args(argv)
    t0 = time.time()

    q_prim = load_all(PRIMARY_SEASONS)
    q_conf = load_all(CONFIRM_SEASONS)
    q_all = pd.concat([q_prim, q_conf], ignore_index=True)

    samples = {}
    for tag, q in (("prim", q_prim), ("conf", q_conf)):
        for src, cols3, cols2 in (("PS", PS, PS_OU), ("PSC", PSC, PSC_OU)):
            m, P = build_sample(q, cols3, cols2, DEVIG)
            samples[(tag, src)] = (m, P)

    # --- copertura (per lega x stagione, sui campioni completi) ---
    copertura = []
    for (lg, se), g in q_all.groupby(["league", "season"], sort=False):
        ps_ok = g[PS + PS_OU].notna().all(axis=1)
        psc_ok = g[PSC + PSC_OU].notna().all(axis=1)
        date_ok = g.loc[ps_ok, "date_day"]
        copertura.append([lg, se, int(len(g)), int(ps_ok.sum()), int(psc_ok.sum()),
                          int(len(g) - int(ps_ok.sum())),
                          (f"{date_ok.min():%d/%m/%Y} – {date_ok.max():%d/%m/%Y}"
                           if len(date_ok) else "—")])
    # nota automatica sulle stagioni a copertura parziale (soglia dichiarata: 95 %)
    righe_nota = []
    for (lg, se), g in q_all.groupby(["league", "season"], sort=False):
        ps_ok = g[PS + PS_OU].notna().all(axis=1)
        frac = float(ps_ok.mean()) if len(g) else 0.0
        if frac < 0.95:
            date_ok = g.loc[ps_ok, "date_day"]
            ultima = f"{date_ok.max():%d/%m/%Y}" if len(date_ok) else "—"
            righe_nota.append(f"{lg} {se}: {ps_ok.sum()}/{len(g)} ({pct(frac, 1)}), "
                              f"ultima data coperta {ultima}")
    nota = ("Conteggi dopo la deduplicazione su lega × data × casa × trasferta e dopo aver scartato "
            "le partite senza risultato. Le colonne Pinnacle (`PSH/PSD/PSA`, `P>2.5/P<2.5`, "
            "`PSCH/PSCD/PSCA`, `PC>2.5/PC<2.5`) sono presenti nell'intestazione di tutti i 20 CSV "
            "(2022-2025, 5 leghe): nessuna stagione e' stata esclusa per mancanza delle colonne. "
            "La copertura NON e' completa in tutte le celle: sotto il 95 % di righe compilate — "
            + ("; ".join(righe_nota) if righe_nota else "nessuna")
            + ". Dove Pinnacle manca la partita esce dal campione: e' una proprieta' del dato "
              "scaricato, non una scelta di questo audit.")
    # verifica griglia <-> de-vig sul campione primario (PS)
    m_p, P_p = samples[("prim", "PS")]
    Y_p = outcome_1x2(m_p)
    ver = verifica_griglia(P_p["proporzionale"][0], P_p["proporzionale"][1])

    res = {}
    for tag in ("prim", "conf"):
        for src in ("PS", "PSC"):
            m, P = samples[(tag, src)]
            res[(tag, src)] = analyse_sample(f"{tag}/{src}", m, P, outcome_1x2(m))

    prim = res[("prim", "PS")][0]
    conf = res[("conf", "PS")][0]
    sens_prim = res[("prim", "PSC")][0]
    sens_conf = res[("conf", "PSC")][0]
    decisione = decide(prim, conf)

    # --- descrittivo topmix sulle 3504 (B365) e sensibilita' Pinnacle pre-chiusura ---
    q_3504 = load_all(CONFIRM_SEASONS)
    m_b, P_b = build_sample(q_3504, B365, B365_OU, DEVIG)
    Y_b = outcome_1x2(m_b)
    r_b, _ = analyse_sample("b365", m_b, P_b, Y_b)
    tr_b = topmix_transitions(r_b)

    # Pinnacle pre-chiusura sulle stesse 3504 partite (chiavi lega|data|home|away)
    key_3504 = set(zip(m_b["league"], m_b["date_day"].dt.strftime("%Y-%m-%d"), m_b["home"], m_b["away"]))
    m_ps = q_3504.copy()
    m_ps["_k"] = list(zip(m_ps["league"], m_ps["date_day"].dt.strftime("%Y-%m-%d"),
                          m_ps["home"], m_ps["away"]))
    m_ps = m_ps[m_ps["_k"].isin(key_3504)].reset_index(drop=True)
    m_ps2, P_ps = build_sample(m_ps, PS, PS_OU, DEVIG)
    r_ps, _ = analyse_sample("ps", m_ps2, P_ps, outcome_1x2(m_ps2))
    tr_ps_own = topmix_transitions(r_ps)

    def righe_topmix(r, tr, n_tot):
        rows = []
        base = r["topmix"]["proporzionale"]
        rows.append(["proporzionale", base["scelte"], pct(base["hit_rate"]),
                     "—", "—", "—", "—"])
        for meth in ("potenza", "Shin"):
            o = r["topmix"][meth]
            t = tr[meth]
            rows.append([meth, o["scelte"], pct(o["hit_rate"]),
                         f"{t['cambia_esito_tutte']} / {n_tot}",
                         str(t["cambia_esito_tra_scelte"]),
                         f"{t['entra']} (hit {pct(t['hit_rate_entrate'])})",
                         f"{t['esce']} (hit {pct(t['hit_rate_uscite'])})"])
        return rows

    n_tot_ps = len(m_ps2)
    n_prop = int(r_b["topmix"]["proporzionale"]["scelte"])
    hit_prop = r_b["topmix"]["proporzionale"]["hit_rate"]
    parita = (n_prop == 1302 and abs(hit_prop - 0.675) < 0.005)
    topmix_b365 = {"righe": righe_topmix(r_b, tr_b, len(m_b)),
                   "nota": (f"Su {len(m_b)} partite (attese 3.504 di PR #59). «Cambia esito» e' "
                            "contato su tutte le partite del campione; «cambia esito restando sopra "
                            "soglia» solo fra le scelte ammesse da entrambi i metodi. Tra parentesi "
                            "l'hit rate delle scelte che entrano/escono.\n\n"
                            "**Perche' «cambia esito» e' 0 con ogni metodo:** proporzionale, potenza e "
                            "Shin sono trasformazioni *monotone crescenti* di π_i = 1/q_i (la potenza "
                            "con esponente k ≥ 1, Shin con z < 1), quindi l'argmax della terna e' lo "
                            "stesso per costruzione: nessuna scelta puo' cambiare esito. Puo' cambiare "
                            "solo il livello di p, e qui il livello sale (potenza e Shin tolgono meno "
                            "al favorito del proporzionale): entrano solo nuove scelte, nessuna esce.\n\n"
                            f"**Controllo di parita' con PR #49/PR #59:** con il de-vig proporzionale le "
                            f"scelte di mercato sono {n_prop} con hit rate {pct(hit_prop)}: "
                            + ("coincidono con i 1302 / 67,5 % del replay `topmix_mercato_v3`."
                               if parita else
                               "NON coincidono con i 1302 / 67,5 % del replay `topmix_mercato_v3`."))}
    topmix_ps = {"righe": righe_topmix(r_ps, tr_ps_own, n_tot_ps),
                 "nota": (f"Stesse partite, filtrate su quelle con terna Pinnacle di pre-chiusura e "
                          f"O/U 2,5 Pinnacle completi: {n_tot_ps} su {len(m_b)}. La colonna "
                          "«cambia esito» e' calcolata su questo sottoinsieme.")}

    meta = {"generato": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "copertura": copertura, "nota_copertura": nota,
            "secondi": time.time() - t0,
            "versioni": {"numpy": np.__version__, "pandas": pd.__version__}}

    md = build_md(meta, prim, conf, sens_prim, sens_conf, ver, topmix_b365, topmix_ps, decisione)
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write(md)
    os.makedirs(OUT_DIR, exist_ok=True)

    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items() if k not in ("esito", "p", "y", "sel")}
        if isinstance(o, (np.floating, np.integer)):
            return o.item()
        return o

    with open(JSON_OUT, "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "verifica_griglia": ver, "primario": clean(prim),
                   "conferma": clean(conf), "sens_primario": clean(sens_prim),
                   "sens_conferma": clean(sens_conf), "decisione": decisione,
                   "topmix_b365": {"righe": topmix_b365["righe"], "nota": topmix_b365["nota"],
                                   "dettagli": clean(tr_b)},
                   "topmix_pinnacle": {"righe": topmix_ps["righe"], "nota": topmix_ps["nota"],
                                       "dettagli": clean(tr_ps_own)}}, fh,
                  ensure_ascii=False, indent=1)
    print(md)
    print(f"[punto1] referto: {REPORT} · json: {JSON_OUT} · {time.time() - t0:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
