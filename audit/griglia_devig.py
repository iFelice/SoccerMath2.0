#!/usr/bin/env python3
"""griglia_devig.py — punto 2: calibrazione dei derivati con TRE de-vig degli input.

Audit di SOLA LETTURA: nessuna modifica a SoccerMath/ (app.py incluso), nessun
--write, nessuna rete, nessuna chiave.

Ripete la tabella del punto 4 della PR #59 (variante A, stesse fasce, stessa
regola di ingresso) cambiando solo il de-vig degli input: proporzionale, potenza,
Shin.

REGOLE DICHIARATE (identiche a §0.3 del referto; nessuna soglia nuova):

  R2.1 Campione: le 3.504 partite di PR #59 (B365 1X2 + B365 O/U 2,5 completi,
       stagioni 2024/25 e 2025/26, 5 leghe), stesso caricamento e stessa dedup di
       ``griglia_varianti.load_quotes`` (importato, non ricopiato).
  R2.2 Variante: **A** di PR #59 = Dixon-Coles con rho per partita, fittata su
       1X2 + Over 2,5 con LO STESSO de-vig applicato a entrambi gli input.
  R2.3 Fasce: [0,55-0,65), [0,65-0,75), >= 0,75, come PR #59. Esito valutato:
       quello con p piu' alta nella coppia evento/complemento (p >= 0,5).
  R2.4 Regola di ingresso: R4 di PR #59, identica — un mercato entra se in OGNI
       fascia con n >= 100 l'IC 95% di f - p contiene lo zero OPPURE |f - p| <= 0,03;
       se nessuna fascia ha n >= 100 il mercato e' «non valutabile».
  R2.5 IC: bootstrap a blocchi (lega x stagione x data), 2000 repliche, seme
       20261011 (lo stesso di PR #59), stessa implementazione di PR #59.
  R2.6 Si riporta f - p CON IL SEGNO per ogni mercato, fascia e metodo. Per X2,
       1+Over 1,5 e 1X+Over 1,5 si dice esplicitamente se lo scarto cambia col
       metodo di de-vig (confronto dei tre valori a parita' di fascia).
  R2.7 Doppia chance (1X, X2, 12): accanto al valore della griglia si calcola il
       valore DIRETTO dalla somma delle probabilita' 1X2 de-vigate (senza griglia)
       e si riporta la differenza massima (e la mediana) rispetto alla griglia.
  R2.8 Controllo di parita': con il de-vig proporzionale i numeri DEVONO riprodurre
       la tabella del punto 4 di PR #59 (`audit/results/griglia_varianti.md`), che
       e' ricalcolata qui con lo stesso codice e gli stessi semi.

Output: audit/results/punto2_calibrazione_devig.md, audit/output/punto2_devig.json,
        audit/output/punto2_fits.pkl (non versionato).
Uso: python audit/griglia_devig.py [--no-cache]
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AUDIT_DIR)

import griglia_varianti as gv  # noqa: E402  (PR #59: maschere, loader, fasce, R4)
from griglia_core import DEVIG, dc_matrix, fit_implicit  # noqa: E402

OUT_DIR = gv.OUT_DIR
REPORT = os.path.join(_AUDIT_DIR, "results", "punto2_calibrazione_devig.md")
JSON_OUT = os.path.join(OUT_DIR, "punto2_devig.json")
CACHE = os.path.join(OUT_DIR, "punto2_fits.pkl")

B365 = ["B365H", "B365D", "B365A"]
B365_OU = ["B365>2.5", "B365<2.5"]
SEED_R4 = gv.SEED_R4          # 20261011, come PR #59
REPS = gv.REPS                # 2000
TOL_PT = gv.TOL_PT            # 0,03
CAL_BANDS = gv.CAL_BANDS
DC = OrderedDict([("1X", ("1", "X")), ("X2", ("X", "2")), ("12", ("1", "2"))])
MERCATI_CHIAVE = ("X2", "1+Over 1.5", "1X+Over 1.5")


# ---------------------------------------------------------------------------
# Campione e fit
# ---------------------------------------------------------------------------
def build_main_devig(q: pd.DataFrame, methods):
    """Come gv.build_main ma con un de-vig per metodo (stessi filtri)."""
    ok = (q[B365].notna().all(axis=1) & q[B365_OU].notna().all(axis=1))
    m = q[ok].reset_index(drop=True)
    out, keep = {}, None
    for name, fn in methods.items():
        trip = [fn([a, b, c]) for a, b, c in zip(m[B365[0]], m[B365[1]], m[B365[2]])]
        ou = [fn([a, b]) for a, b in zip(m[B365_OU[0]], m[B365_OU[1]])]
        v = np.array([t is not None and o is not None for t, o in zip(trip, ou)])
        keep = v if keep is None else (keep & v)
        out[name] = (np.array([t for t, x in zip(trip, v) if x]),
                     np.array([o[0] for o, x in zip(ou, v) if x]))
    m = m[keep].reset_index(drop=True)
    return m, {k: (v[0][keep], v[1][keep]) for k, v in out.items()}


def fit_variante_A(P3: np.ndarray, PO: np.ndarray) -> dict:
    """Variante A di PR #59: Dixon-Coles con rho per partita (fit esatto)."""
    n = len(PO)
    P = np.zeros((n, len(gv.EV_NAMES)))
    lam = np.zeros(n)
    mu = np.zeros(n)
    rho = np.zeros(n)
    res = np.zeros(n)
    for i in range(n):
        f = fit_implicit(P3[i, 0], P3[i, 1], P3[i, 2], PO[i], rho_free=True)
        lam[i], mu[i], rho[i], res[i] = f["lam"], f["mu"], f["rho"], f["max_abs_resid"]
        P[i] = gv.event_probs(dc_matrix(f["lam"], f["mu"], f["rho"]))
    return {"P": P, "lam": lam, "mu": mu, "rho": rho, "residuo": res,
            "residuo_max": float(res.max())}


def get_fits(use_cache, P_by_method):
    if use_cache and os.path.exists(CACHE):
        with open(CACHE, "rb") as fh:
            cache = pickle.load(fh)
        if set(cache) == set(P_by_method):
            return cache
    fits = {}
    for name, (P3, PO) in P_by_method.items():
        t0 = time.time()
        fits[name] = fit_variante_A(P3, PO)
        fits[name]["secondi"] = time.time() - t0
        print(f"[punto2] fit {name}: {fits[name]['secondi']:.0f}s", flush=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(CACHE, "wb") as fh:
        pickle.dump(fits, fh)
    return fits


# ---------------------------------------------------------------------------
# Calibrazione
# ---------------------------------------------------------------------------
def calibra(P: np.ndarray, Y: np.ndarray, blocks: np.ndarray, inv, nb, draws):
    """Tabella R4 per gli 11 eventi (come PR #59 §4)."""
    righe = {}
    for j, name in enumerate(gv.EV_NAMES):
        p_ev, y_ev = P[:, j], Y[:, j]
        lato = p_ev >= 0.5
        p = np.where(lato, p_ev, 1 - p_ev)
        y = np.where(lato, y_ev, 1 - y_ev)
        bande = []
        ok_tutte, n_val = True, 0
        for bname, (lo, hi) in CAL_BANDS.items():
            sel = (p >= lo) & (p < hi)
            n = int(sel.sum())
            if n == 0:
                bande.append({"fascia": bname, "n": 0, "p": None, "f": None,
                              "fp": None, "lo": None, "hi": None, "conta": False})
                continue
            fp = float(y[sel].mean() - p[sel].mean())
            lo_ci, hi_ci = gv.boot_fp(np.where(sel, y - p, 0.0), sel.astype(float), inv, nb, draws)
            bande.append({"fascia": bname, "n": n, "p": float(p[sel].mean()),
                          "f": float(y[sel].mean()), "fp": fp, "lo": lo_ci, "hi": hi_ci,
                          "conta": n >= 100})
            if n >= 100:
                n_val += 1
                if not ((lo_ci <= 0 <= hi_ci) or abs(fp) <= TOL_PT):
                    ok_tutte = False
        if n_val == 0:
            esito = "non valutabile (nessuna fascia n ≥ 100)"
        elif ok_tutte:
            esito = "CALIBRATO: entra nella lista"
        else:
            esito = "non calibrato: resta fuori"
        righe[name] = {"bande": bande, "esito": esito}
    return righe


def doppia_chance_diretta(P3: np.ndarray, P: np.ndarray):
    """1X / X2 / 12 dalla somma delle 1X2 de-vigate (senza griglia) vs griglia."""
    idx = gv.EV_IDX
    somme = {"1X": P3[:, 0] + P3[:, 1], "X2": P3[:, 1] + P3[:, 2], "12": P3[:, 0] + P3[:, 2]}
    out = {}
    for nome, diretta in somme.items():
        griglia = P[:, idx[nome]]
        d = np.abs(diretta - griglia)
        out[nome] = {"max": float(d.max()), "mediana": float(np.median(d)),
                     "media": float(d.mean()),
                     "argmax_partita": int(np.argmax(d)),
                     "p95": float(np.percentile(d, 95))}
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def build_md(meta, cal, dc_diff, parita) -> str:
    fmt, pct, pts, md_table = gv.fmt, gv.pct, gv.pts, gv.md_table
    T = []
    A = T.append
    A("## 2. Punto 2 — calibrazione dei derivati rifatta con tre de-vig degli input\n")
    A(f"Generato da `audit/griglia_devig.py` il {meta['generato']} · campione {meta['n']} partite "
      "(B365, 2024/25 + 2025/26) · variante **A** (Dixon-Coles con ρ per partita) · stesse fasce e "
      "stessa regola di ingresso R4 di PR #59 · nessuna modifica a `SoccerMath/`, nessun "
      "`--write`, nessuna rete, nessuna chiave.\n")
    A("### 2.1 Campione e riproduzione del fit\n")
    A(md_table(["metodo di de-vig", "partite", "residuo massimo sui 4 vincoli",
                "ρ mediano", "λ mediano", "μ mediano"],
               [[k, meta["n"], f"{v['residuo_max']:.1e}",
                 fmt(float(np.median(meta["fits"][k]["rho"])), 4),
                 fmt(float(np.median(meta["fits"][k]["lam"])), 3),
                 fmt(float(np.median(meta["fits"][k]["mu"])), 3)]
                for k, v in meta["fits"].items()]))
    A("")
    A(parita["nota"] + "\n")

    A("### 2.2 f − p con segno, per mercato, fascia e metodo\n")
    A("Esito valutato: quello con p più alta nella coppia evento/complemento (p ≥ 0,5). "
      "f − p in punti percentuali con IC 95% a blocchi (lega × stagione × data, 2000 repliche, "
      f"seme {SEED_R4}).\n")
    for name in gv.EV_NAMES:
        A(f"#### {name}" + (" (extra)" if name in gv.EXTRA else "") +
          f" — esiti: {gv.EVENTS[name][1]} / {name}\n")
        rows = []
        for meth in ("proporzionale", "potenza", "Shin"):
            r = cal[meth][name]
            for b in r["bande"]:
                if b["n"] == 0:
                    rows.append([meth, b["fascia"], 0, "n/d", "n/d", "n/d", "no"])
                else:
                    rows.append([meth, b["fascia"], b["n"], pct(b["p"]), pct(b["f"]),
                                 f"{pts(b['fp'])} [{pts(b['lo'])}; {pts(b['hi'])}]",
                                 "sì" if b["conta"] else "no"])
        A(md_table(["de-vig", "fascia di p", "n", "p media", "frequenza f", "f − p [IC 95%]",
                    "conta (n ≥ 100)"], rows))
        A("")
        A(md_table(["de-vig", "esito R4"],
                   [[m, cal[m][name]["esito"]] for m in ("proporzionale", "potenza", "Shin")]))
        A("")

    A("### 2.3 Sintesi: lo scarto cambia col metodo di de-vig?\n")
    rows = []
    for name in gv.EV_NAMES:
        riga = [name + (" (extra)" if name in gv.EXTRA else "")]
        for meth in ("proporzionale", "potenza", "Shin"):
            b = cal[meth][name]["bande"]
            valide = [x for x in b if x["conta"]]
            if not valide:
                riga.append("n/d")
            else:
                riga.append("; ".join(f"{x['fascia']}: {pts(x['fp'])}" for x in valide))
        esiti = {cal[m][name]["esito"].split(":")[0] for m in ("proporzionale", "potenza", "Shin")}
        riga.append("sì" if len(esiti) > 1 else "no")
        rows.append(riga)
    A(md_table(["mercato", "f − p proporzionale (fasce con n ≥ 100)",
                "f − p potenza", "f − p Shin", "l'esito R4 cambia col metodo"], rows))
    A("")
    A("#### 2.3.1 I tre mercati fuori lista: lo scarto cambia col metodo?\n")
    for name in MERCATI_CHIAVE:
        A(f"**{name}.**")
        for meth in ("proporzionale", "potenza", "Shin"):
            valide = [x for x in cal[meth][name]["bande"] if x["conta"]]
            dettaglio = ", ".join(f"{x['fascia']}: {pts(x['fp'])} "
                                  f"[{pts(x['lo'])}; {pts(x['hi'])}]" for x in valide) or "nessuna fascia con n ≥ 100"
            A(f" {meth}: {dettaglio}. Esito R4: {cal[meth][name]['esito']}.")
        fps = []
        for b in cal["proporzionale"][name]["bande"]:
            if not b["conta"]:
                continue
            valori = [cal[m][name]["bande"][i]["fp"] for m in ("proporzionale", "potenza", "Shin")
                      for i, x in enumerate(cal[m][name]["bande"]) if x["fascia"] == b["fascia"]]
            fps.append((b["fascia"], valori))
        for fascia, valori in fps:
            v = [x for x in valori if x is not None]
            if len(v) == 3:
                A(f"  - fascia {fascia}: lo scarto passa da {pts(v[0])} (proporzionale) a "
                  f"{pts(v[1])} (potenza) e {pts(v[2])} (Shin): "
                  + ("**cambia segno**" if min(v) < 0 < max(v) else
                     ("resta dello stesso segno, ampiezza massima "
                      f"{pts(max(v) - min(v))}")) + ".")
        A("")

    A("### 2.4 Doppia chance: somma diretta delle 1X2 (senza griglia) contro la griglia\n")
    rows = []
    for meth in ("proporzionale", "potenza", "Shin"):
        for nome, d in dc_diff[meth].items():
            rows.append([meth, nome, f"{d['mediana']:.1e}", f"{d['media']:.1e}",
                         f"{d['p95']:.1e}", f"**{d['max']:.1e}**"])
    A(md_table(["de-vig", "doppia chance", "|Δ| mediana", "|Δ| media", "p95",
                "differenza MASSIMA |Δ|"], rows))
    A("")
    A("Δ = (p₁ + pX dalla terna de-vigata) − P(doppia chance) dalla griglia, in frazione di "
      "probabilità (1e-16 = una unità di macchina). La somma diretta è calcolata SENZA griglia: "
      "P(1X) = p₁ + pX, P(X2) = pX + p₂, P(12) = p₁ + p₂.\n")
    A("**Le due vie coincidono al livello di macchina, con ogni de-vig.** Non è un caso: il fit "
      "vincola la griglia a riprodurre ESATTAMENTE la terna 1X2 (3 parametri, 3 vincoli "
      "indipendenti, residuo massimo ~1e-12) e 1X, X2 e 12 sono unioni di celle 1X2 "
      "(1X = «1» ∪ «X», X2 = «X» ∪ «2», 12 = «1» ∪ «2»), quindi la loro probabilità è la somma "
      "delle tre di partenza qualunque cosa faccia il modello dentro le celle: la differenza "
      "massima è solo l'errore di arrotondamento in virgola mobile. La conseguenza pratica è che "
      "sulla doppia chance la griglia NON aggiunge nulla al de-vig: al contrario di Over 1,5, "
      "Over 3,5, Gol e delle combinazioni (1+Over 1,5, 1X+Over 1,5, 1X+Under 3,5), dove il "
      "valore dipende da come la massa è distribuita dentro la griglia.\n")

    A("### 2.5 Limiti\n")
    A("- Campione unico (3.504 partite B365, due stagioni): i conti per fascia non sono "
      "indipendenti fra mercati derivati dalla stessa griglia.")
    A("- Il de-vig e' applicato sia alla terna 1X2 sia all'Over/Under 2,5: i due effetti non sono "
      "separati in questa tabella.")
    A("- R4 non e' una misura di valore economico: dice solo se la frequenza osservata e' "
      "compatibile con la probabilita' dichiarata.")
    A("- «Non valutabile» (nessuna fascia con n ≥ 100) e' una lettura conservativa: il mercato "
      "resta fuori (regola di PR #59, non modificata).\n")
    return "\n".join(T) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args(argv)
    t0 = time.time()

    q = gv.load_all()
    m, P_by_method = build_main_devig(q, DEVIG)
    n = len(m)
    if n != 3504:
        raise SystemExit(f"campione {n} != 3504 (PR #59)")
    print(f"[punto2] campione {n}", flush=True)

    fits = get_fits(not args.no_cache, P_by_method)
    blocks = gv.blocks_of(m)
    inv, nb, draws = gv.block_setup(blocks, REPS, SEED_R4)
    Yev, _O = gv.outcome_indicators(m["FTHG"].to_numpy().astype(int),
                                    m["FTAG"].to_numpy().astype(int))

    cal = {meth: calibra(fits[meth]["P"], Yev, blocks, inv, nb, draws)
           for meth in ("proporzionale", "potenza", "Shin")}
    dc_diff = {meth: doppia_chance_diretta(P_by_method[meth][0], fits[meth]["P"])
               for meth in ("proporzionale", "potenza", "Shin")}

    # controllo di parita' con la tabella del punto 4 di PR #59 (proporzionale)
    attesi = {  # (mercato, fascia) -> (n, f-p in punti) dal referto PR #59
        ("Gol", "0,55-0,65"): (1661, -0.0), ("Gol", "0,65-0,75"): (126, -3.9),
        ("X2", "0,65-0,75"): (916, 3.2), ("X2", "≥0,75"): (727, 4.0),
        ("1+Over 1.5", "0,65-0,75"): (1027, 3.0), ("1+Over 1.5", "≥0,75"): (1068, 2.7),
        ("1X+Over 1.5", "≥0,75"): (368, 4.5), ("Over 3.5", "≥0,75"): (894, 1.9),
        ("1X", "≥0,75"): (1443, 1.1), ("12", "0,65-0,75"): (2039, -0.9),
        ("2+Over 1.5", "0,65-0,75"): (669, -1.1), ("1X+Under 3.5", "0,55-0,65"): (1633, 1.8),
        ("Over 1.5", "≥0,75"): (2222, 0.2), ("X2+Under 3.5", "0,65-0,75"): (666, 3.1),
    }
    scostamenti = []
    for (mercato, fascia), (n_att, fp_att) in sorted(attesi.items()):
        b = [x for x in cal["proporzionale"][mercato]["bande"] if x["fascia"] == fascia][0]
        scostamenti.append((mercato, fascia, b["n"], n_att, 100 * (b["fp"] or 0.0), fp_att))
        assert b["n"] == n_att, (mercato, fascia, b["n"], n_att)
    massimo = max(abs(fp - fp_att) for _m, _f, _n, _na, fp, fp_att in scostamenti)
    parita = {"massimo": massimo,
              "nota": ("**Controllo di parità con PR #59 (de-vig proporzionale).** Confrontate "
                       f"{len(scostamenti)} celle (mercato, fascia) con la tabella del punto 4 di "
                       "`audit/results/griglia_varianti.md`: tutti i conteggi n coincidono "
                       "esattamente e il massimo scarto su f − p è "
                       f"**{massimo:.2f} punti** (dovuto all'arrotondamento a un decimale del "
                       "referto PR #59). Le colonne potenza e Shin sono calcolate con lo stesso "
                       "codice e gli stessi semi: l'unica differenza è il de-vig degli input.")
                      if massimo <= 0.06 else
                       ("**Controllo di parità FALLITO** con la tabella del punto 4 di PR #59: "
                        f"scarto massimo su f − p {massimo:.2f} punti.")}

    meta = {"generato": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "n": n,
            "fits": {k: {"residuo_max": v["residuo_max"], "rho": v["rho"], "lam": v["lam"],
                         "mu": v["mu"]} for k, v in fits.items()},
            "secondi": time.time() - t0}
    md = build_md(meta, cal, dc_diff, parita)
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write(md)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(JSON_OUT, "w", encoding="utf-8") as fh:
        json.dump({"meta": {k: (v if k != "fits" else
                                {m: {"residuo_max": d["residuo_max"]} for m, d in v.items()})
                            for k, v in meta.items()},
                   "calibrazione": cal, "doppia_chance": dc_diff,
                   "parita_pr59": {"scarto_massimo_punti": massimo,
                                   "celle_confrontate": len(scostamenti)}},
                  fh, ensure_ascii=False, indent=1)
    print(md)
    print(f"[punto2] referto: {REPORT} · json: {JSON_OUT} · {time.time() - t0:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
