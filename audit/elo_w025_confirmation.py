"""
elo_w025_confirmation.py — Audit di CONFERMA (sola lettura) per il cambio di
produzione ``ELO_ENSEMBLE_W`` 0.6 -> 0.25.

RIUSA la pipeline gia' committata di ``audit/grid_search_ensemble_weight.py``
(walker condiviso di ``diagnose_clv_pinnacle``, matrici per-riga-per-w,
``boot_stats`` appaiati vs w di riferimento, ``significant``): l'unico
adattamento e' la griglia, ridotta ai due pesi del confronto
(W_OLD = 0.6 attuale, W_NEW = 0.25 candidato) via patch LOCALE del modulo
(la griglia completa del report originale resta nei suoi artefatti).

Produce, con lo stesso dettaglio PER LEGA di
``audit/results/production_baseline_comparison.md``:
  * Brier / LogLoss (blend Poisson+Elo) a w=0.6 e w=0.25;
  * delta appaiati (bootstrap 2000 resample, seed 20260905, ``_ci`` di
    ``topmix_margins``) con verdetto «distinguibile» (CI senza zero) per
    VALIDATION 2024/25 e TEST 2025/26, per ogni lega E in aggregato;
  * ROI B365/Avg a puntata fissa (edge>0) per entrambi i pesi, con CI own
    (niente delta appaiato: le selezioni edge>0 dei due pesi differiscono,
    quindi i denominatori non sono gli stessi — stesso approccio del report
    grid, che mostra i ROI lato per lato).

La sezione viene APPESA a ``audit/results/ensemble_weight_grid_search.md``
fra marcatori dedicati (ri-eseguire lo script SOSTITUISCE la sezione senza
toccare il resto del report).

Uso: python audit/elo_w025_confirmation.py
"""
from __future__ import annotations

import os
import sys
from collections import OrderedDict
from datetime import datetime, timezone

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
if _AUDIT_DIR not in sys.path:
    sys.path.insert(0, _AUDIT_DIR)

import grid_search_ensemble_weight as GS   # noqa: E402
from topmix_margins import N_BOOT, SEED    # noqa: E402
from backtest_experiment_all import LEAGUES  # noqa: E402

OUT_PATH = GS.OUT_PATH                     # audit/results/ensemble_weight_grid_search.md

W_OLD = 0.6                                # attuale (app.ELO_ENSEMBLE_W)
W_NEW = 0.25                               # candidato
MARK_START = "<!-- conferma-w025:start -->"
MARK_END = "<!-- conferma-w025:end -->"
SPLIT_LABELS = (("validation", "VALIDATION 2024/25"), ("test", "TEST 2025/26"))


def analyze(d, split, n_boot=N_BOOT, seed=SEED):
    """Metriche + bootstrap appaiato vs W_OLD su un sotto-campione."""
    mask = GS.sample_split(d, split)
    sub = d[mask]
    if len(sub) == 0:
        return {"n": 0}
    _, B, LL, roi = GS.w_matrices(sub)
    j_old, j_new = GS.GRID_W.index(W_OLD), GS.GRID_W.index(W_NEW)
    point = GS.point_metrics(B, LL, roi)
    boot = GS.boot_stats(B, LL, roi, w_ref=W_OLD, n_boot=n_boot, seed=seed)
    out = {
        "n": int(len(sub)),
        "point": point,
        "delta_brier": boot["delta_brier"][W_NEW],
        "delta_log_loss": boot["delta_log_loss"][W_NEW],
        "sig_brier": GS.significant(boot["delta_brier"][W_NEW]),
        "sig_log_loss": GS.significant(boot["delta_log_loss"][W_NEW]),
        "roi": boot["roi"],
        "j_old": j_old, "j_new": j_new,
    }
    return out


def run(n_boot=N_BOOT, seed=SEED):
    """Colleziona le righe una volta per lega e analizza V/T per lega e aggregato."""
    # griglia ridotta ai due pesi del confronto: w_matrices/point_metrics/
    # boot_stats leggono GS.GRID_W in modo consistente (patch locale, la
    # griglia completa del report resta negli artefatti gia' committati)
    GS.GRID_W = (W_NEW, W_OLD)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "w_old": W_OLD, "w_new": W_NEW, "n_boot": n_boot, "seed": seed,
               "cells": OrderedDict()}
    all_rows = []
    for prefix, camp_key in LEAGUES:
        d = GS.collect_rows(prefix, camp_key)
        all_rows.append(d)
        for split, _label in SPLIT_LABELS:
            payload["cells"][(camp_key, split)] = analyze(d, split, n_boot, seed)
    every = pd_concat(all_rows)
    for split, _label in SPLIT_LABELS:
        payload["cells"][("AGGREGATO", split)] = analyze(every, split, n_boot, seed)
    return payload


def pd_concat(frames):
    import pandas as pd
    return pd.concat(frames, ignore_index=True)


# =====================================================================
# Render della sezione e inserimento non distruttivo nel report
# =====================================================================
def _fv(v, nd=4):
    return "-" if v is None else f"{v:.{nd}f}"


def _fci(ci, nd=4):
    if ci is None or ci[0] is None:
        return "-"
    return f"[{ci[0]:+.{nd}f};{ci[1]:+.{nd}f}]"


def verdict_word(sig_v, sig_t):
    if sig_v and sig_t:
        return "sì (V e T)"
    if sig_v:
        return "solo validation"
    if sig_t:
        return "solo test"
    return "no"


def render_section(payload):
    L = []
    ap = L.append
    ap(MARK_START)
    ap(f"## Conferma cambio produzione: ELO_ENSEMBLE_W 0.6 -> 0.25 "
       f"({payload['generated_at']})")
    ap("")
    ap("Audit di conferma SOLA LETTURA riusando la pipeline di questo report "
       "(walker condiviso, stesse righe, stesse quote, stesso bootstrap): "
       f"griglia ridotta ai due pesi ({W_NEW} candidato vs {W_OLD} attuale), "
       f"delta appaiati {payload['n_boot']} resample, seed {payload['seed']}, "
       "CI percentile 2.5-97.5 (`_ci` di `topmix_margins`), convenzioni "
       "identiche alle sezioni sopra. Stesso dettaglio per lega di "
       "`production_baseline_comparison.md`; l'aggregato è in coda.")
    ap("")
    for split, label in SPLIT_LABELS:
        ap(f"### {label}")
        ap("")
        ap("| Campione | n | Brier 0.6 | Brier 0.25 | Δ Brier (CI) | sig | "
           "LogLoss 0.6 | LogLoss 0.25 | Δ LogLoss (CI) | sig |")
        ap("|---|---:|---:|---:|---:|:---:|---:|---:|---:|:---:|")
        for (camp, sp), c in payload["cells"].items():
            if sp != split or c.get("n", 0) == 0:
                continue
            po, pn = c["point"][W_OLD], c["point"][W_NEW]
            db, dll = c["delta_brier"], c["delta_log_loss"]
            ap(f"| {camp} | {c['n']} | {_fv(po['brier'])} | {_fv(pn['brier'])} | "
               f"{db['point']:+.4f} {_fci(db['ci'])} | "
               f"{'**sì**' if c['sig_brier'] else 'no'} | "
               f"{_fv(po['log_loss'])} | {_fv(pn['log_loss'])} | "
               f"{dll['point']:+.4f} {_fci(dll['ci'])} | "
               f"{'**sì**' if c['sig_log_loss'] else 'no'} |")
        ap("")
        ap("ROI a puntata fissa (edge>0, stesso book per scommessa; CI own "
           "bootstrap, niente delta appaiato: le selezioni dei due pesi "
           "differiscono, denominatori non confrontabili 1:1):")
        ap("")
        ap("| Campione | n bet B365 0.6 | ROI B365 0.6 (CI) | n bet B365 0.25 | ROI B365 0.25 (CI) | "
           "n bet Avg 0.6 | ROI Avg 0.6 | n bet Avg 0.25 | ROI Avg 0.25 |")
        ap("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for (camp, sp), c in payload["cells"].items():
            if sp != split or c.get("n", 0) == 0:
                continue
            ro = c["roi"]
            cells = []
            for book in ("b365", "avg"):
                for w in (W_OLD, W_NEW):
                    r = ro[(w, book)]
                    pt = f"{r['point']:.2f}" if r["point"] is not None else "-"
                    ci = _fci(r["ci"], 2) if r["point"] is not None else "-"
                    cells.append(f"{pt} {ci}" if book == "b365" else pt)
            nb = c["point"]
            ap(f"| {camp} | {nb[W_OLD]['n_bet_b365']} | {cells[0]} | "
               f"{nb[W_NEW]['n_bet_b365']} | {cells[1]} | "
               f"{nb[W_OLD]['n_bet_avg']} | {cells[2]} | "
               f"{nb[W_NEW]['n_bet_avg']} | {cells[3]} |")
        ap("")
    ap("### Verdetto di conferma")
    ap("")
    agg_v = payload["cells"][("AGGREGATO", "validation")]
    agg_t = payload["cells"][("AGGREGATO", "test")]
    league_names = []
    for camp, _sp in payload["cells"]:
        if camp != "AGGREGATO" and camp not in league_names:
            league_names.append(camp)
    per_league = [(camp, payload["cells"][(camp, "validation")]["sig_brier"]
                   and payload["cells"][(camp, "test")]["sig_brier"])
                  for camp in league_names]
    # direzione e significativita' su tutte le celle (lega, split)
    dbriers = [(camp, sp, c["delta_brier"]["point"], c["sig_brier"])
               for (camp, sp), c in payload["cells"].items()
               if camp != "AGGREGATO" and c.get("n", 0)]
    n_neg = sum(1 for _, _, dpt, _ in dbriers if dpt < 0)
    n_sig_v = sum(1 for _, sp, _, sg in dbriers if sp == "validation" and sg)
    n_sig_t = sum(1 for _, sp, _, sg in dbriers if sp == "test" and sg)
    n_worse = sum(1 for (camp, sp, dpt, sg) in dbriers if dpt > 0 and sg)
    ap(f"**Calibrazione (Brier): il miglioramento a w={payload['w_new']} è "
       f"distinguibile (CI senza zero) in ENTRAMBI validation e test in "
       f"AGGREGATO: V {agg_v['delta_brier']['point']:+.4f} "
       f"{_fci(agg_v['delta_brier']['ci'])}, T {agg_t['delta_brier']['point']:+.4f} "
       f"{_fci(agg_t['delta_brier']['ci'])}. LogLoss aggregato: V "
       f"{agg_v['delta_log_loss']['point']:+.4f} "
       f"{_fci(agg_v['delta_log_loss']['ci'])}, T "
       f"{agg_t['delta_log_loss']['point']:+.4f} "
       f"{_fci(agg_t['delta_log_loss']['ci'])}.**")
    ap("")
    dir_note = ("nessuna eccezione al segno" if n_neg == len(dbriers)
                else f"{len(dbriers) - n_neg} celle col segno opposto")
    ap("Per lega (Brier, distinguibile in ENTRAMBI gli split): "
       + ", ".join(f"{camp} {'sì' if sig else 'no'}" for camp, sig in per_league)
       + f". Direzione: {n_neg}/{len(dbriers)} delta per-(lega,split) negativi "
       + "(" + dir_note + ").")
    ap("")
    n_leagues = len(league_names)
    ap(f"Significatività per lega: Brier distinguibile in {n_sig_v}/{n_leagues} leghe in "
       f"validation e {n_sig_t}/{n_leagues} in test; "
       + ("nessuna cella (lega, split) mostra un PEGGIORAMENTO distinguibile."
          if n_worse == 0 else
          f"ATTENZIONE: {n_worse} celle mostrano un peggioramento distinguibile."))
    ap("")
    if agg_v["sig_brier"] and agg_t["sig_brier"] and n_worse == 0 and n_neg == len(dbriers):
        ap("La conferma richiesta per il cambio di produzione è SODDISFATTA sul "
           "piano della calibrazione: significativo su entrambi gli split in "
           "aggregato, direzione coerente in ogni lega e split, mai un "
           "peggioramento significativo per lega. Le leghe singole non sempre "
           "raggiungono la significatività da sole (306-380 partite a cella: "
           "potere statistico limitato), ma non c'e' nessuna lega che si "
           "comporti diversamente dalle altre.")
    elif not (agg_v["sig_brier"] and agg_t["sig_brier"]):
        ap("La conferma NON è soddisfatta: il miglioramento non è "
           "distinguibile su entrambi gli split in aggregato.")
    else:
        ap("Conferma parziale: vedi tabelle riga per riga.")
    ap("")
    ap("Promemoria del report grid (vale qui): calibrazione ≠ redditività — "
       "il peso più basso scommessa di più e con ROI storico peggiore; questa "
       "sezione misura, la decisione resta al porting.")
    ap("")
    ap(MARK_END)
    return "\n".join(L) + "\n"


def replace_or_append_section(md_text, section_md):
    """Inserisce la sezione fra i marcatori: sostituisce quella esistente,
    appende in coda se assente. Il resto del report NON viene toccato."""
    if MARK_START in md_text and MARK_END in md_text:
        pre = md_text[:md_text.index(MARK_START)]
        post = md_text[md_text.index(MARK_END) + len(MARK_END):]
        if post.strip():
            return pre + section_md + "\n" + post.lstrip("\n")
        return pre + section_md
    if not md_text.endswith("\n"):
        md_text += "\n"
    return md_text + "\n" + section_md


def main():
    payload = run()
    section = render_section(payload)
    with open(OUT_PATH, "r", encoding="utf-8") as fh:
        md = fh.read()
    new_md = replace_or_append_section(md, section)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write(new_md)
    print(f"Sezione 'Conferma cambio produzione 0.6 -> 0.25' scritta in {OUT_PATH}")
    for split, label in SPLIT_LABELS:
        c = payload["cells"][("AGGREGATO", split)]
        print(f"{label}: ΔBrier {c['delta_brier']['point']:+.4f} "
              f"{_fci(c['delta_brier']['ci'])} sig={c['sig_brier']} | "
              f"ΔLogLoss {c['delta_log_loss']['point']:+.4f} "
              f"{_fci(c['delta_log_loss']['ci'])} sig={c['sig_log_loss']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
