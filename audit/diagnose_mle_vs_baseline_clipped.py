"""
diagnose_mle_vs_baseline_clipped.py — Come diagnose_mle_attack_defence.py, ma
verifica se applicare lo STESSO clip della MLE anche ai lambda dell'euristica
baseline chiude il divario di LogLoss osservato nello script precedente.

Copia la logica di audit/diagnose_mle_attack_defence.py (stesso walk-forward MLE
con refit mensile, stesso rho=0 per tutte le varianti, stessa valutazione
VALIDATION 2024/25 + TEST 2025/26, stesse 5 leghe, stessa costruzione delle
celle) importando in sola lettura le sue funzioni.

UNICA MODIFICA rispetto allo script precedente: si aggiunge una variante della
baseline in cui i lambda euristici vengono clippati con gli STESSI bound usati in
mle_lambdas() PRIMA di costruire la matrice:
    lam_h = clip(lam_h, exp(-6), exp(3))
    lam_a = clip(lam_a, exp(-6), exp(3))
Nient'altro della logica baseline cambia (team_attr, avg_h/avg_a identici): il clip
e' applicato ai lambda gia' prodotti da run_walkforward_lambda.

Tre varianti confrontate:
  1. BASELINE_NOCLIP  — euristica originale, senza clip (riferimento).
  2. BASELINE_CLIPPED — stessa euristica, con clip [exp(-6), exp(3)] sui lambda.
  3. MLE              — identica allo script precedente.

Per ciascuna: Brier Score e Log Loss su 1X2, O/U2.5, GG/NG, per lega e aggregato.
In piu': conteggio delle partite (per lega, su BASELINE_NOCLIP) in cui il lambda
pre-clip usciva dal range [exp(-6), exp(3)], per quantificare quanto il clip
interviene davvero.

NON tocca SoccerMath/app.py, config.py, models/. Importa in sola lettura
load_league/LEAGUES da backtest_experiment_all.py.

Output: audit/results/mle_vs_baseline_clipped_diagnosis.md
"""
import os
import sys
import time
import numpy as np

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

# Import in SOLA LETTURA. load_league/LEAGUES dal backtest; tutta la logica MLE e di
# valutazione e' riusata da diagnose_mle_attack_defence.py senza modifiche.
from backtest_experiment_all import load_league, LEAGUES  # noqa: E402
from diagnose_dixon_coles_rho import run_walkforward_lambda, SEASONS  # noqa: E402
from diagnose_mle_attack_defence import (  # noqa: E402
    RHO,                      # 0.0 — stesso rho per tutte le varianti
    MARKETS,                  # ["1X2", "O/U2.5", "GG/NG"]
    eval_from_lambdas,        # {market: (brier, logloss)} da record, celle build_matrix rho=0
    run_mle_walkforward,      # walk-forward MLE con refit mensile
)

# Stessi bound in log-spazio usati in mle_lambdas() dello script precedente.
LOG_LO, LOG_HI = -6.0, 3.0
CLIP_LO, CLIP_HI = float(np.exp(LOG_LO)), float(np.exp(LOG_HI))

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "mle_vs_baseline_clipped_diagnosis.md")


def baseline_records(df, apply_clip):
    """BASELINE euristico: riusa run_walkforward_lambda (team_attr, avg_h/avg_a
    identici) e filtra VALIDATION+TEST.

    Se apply_clip=True, i lambda vengono clippati a [exp(-6), exp(3)] PRIMA di
    costruire la matrice (unica modifica rispetto allo script precedente).

    Ritorna (records, n_clipped) dove n_clipped = numero di partite in cui almeno
    uno tra lam_h/lam_a era fuori range [exp(-6), exp(3)] (conteggio sui lambda
    pre-clip, indipendente da apply_clip).
    """
    rl = run_walkforward_lambda(df)
    ev = rl[rl["season"].isin(SEASONS)]
    records = []
    n_clipped = 0
    for _, r in ev.iterrows():
        lam_h = float(r["lambda_h"])
        lam_a = float(r["lambda_a"])
        if lam_h < CLIP_LO or lam_h > CLIP_HI or lam_a < CLIP_LO or lam_a > CLIP_HI:
            n_clipped += 1
        if apply_clip:
            lam_h = min(max(lam_h, CLIP_LO), CLIP_HI)
            lam_a = min(max(lam_a, CLIP_LO), CLIP_HI)
        records.append({
            "lambda_h": lam_h, "lambda_a": lam_a,
            "real_1x2": r["real_1x2"], "real_uo": r["real_uo"],
            "real_gg": r["real_gg"],
        })
    return records, n_clipped


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t_start = time.perf_counter()

    per_league = {}
    total_refits = 0
    pooled = {"BASELINE_NOCLIP": [], "BASELINE_CLIPPED": [], "MLE": []}
    total_clipped = 0

    for prefix, camp_key in LEAGUES:
        df = load_league(prefix)

        base_noclip, n_clipped = baseline_records(df, apply_clip=False)
        base_clipped, _ = baseline_records(df, apply_clip=True)
        mle_rec, n_refits = run_mle_walkforward(df)
        total_refits += n_refits
        total_clipped += n_clipped

        res = {
            "BASELINE_NOCLIP": eval_from_lambdas(base_noclip),
            "BASELINE_CLIPPED": eval_from_lambdas(base_clipped),
            "MLE": eval_from_lambdas(mle_rec),
        }
        per_league[camp_key] = {
            "res": res, "N": len(mle_rec), "N_base": len(base_noclip),
            "refits": n_refits, "n_clipped": n_clipped,
        }
        pooled["BASELINE_NOCLIP"].extend(base_noclip)
        pooled["BASELINE_CLIPPED"].extend(base_clipped)
        pooled["MLE"].extend(mle_rec)
        print(f"[{camp_key}] N={len(mle_rec)} refits={n_refits} "
              f"clip_attivati={n_clipped}/{len(base_noclip)} | "
              f"1X2 LogLoss noclip={res['BASELINE_NOCLIP']['1X2'][1]:.4f} "
              f"clipped={res['BASELINE_CLIPPED']['1X2'][1]:.4f} "
              f"mle={res['MLE']['1X2'][1]:.4f}")

    agg = {k: eval_from_lambdas(v) for k, v in pooled.items()}
    total_time = time.perf_counter() - t_start

    write_report(per_league, agg, len(pooled["MLE"]), total_time,
                 total_refits, total_clipped)
    print(f"\nTempo totale: {total_time:.1f}s  refit MLE: {total_refits}  "
          f"clip attivati (tutte le leghe): {total_clipped}")
    print(f"Scritto: {OUT_PATH}")


def _best_tag(vals):
    """vals: dict variante->valore. Ritorna nome della variante col valore minimo."""
    return min(vals, key=vals.get)


def write_report(per_league, agg, n_pooled, total_time, total_refits, total_clipped):
    VARIANTS = ["BASELINE_NOCLIP", "BASELINE_CLIPPED", "MLE"]
    lines = []
    lines.append("# MLE vs baseline euristica — effetto del clip sui lambda")
    lines.append("")
    lines.append("Stessa architettura di `diagnose_mle_attack_defence.py` "
                 "(walk-forward MLE con refit mensile, rho = 0 per tutte le varianti, "
                 "valutazione VALIDATION 2024/25 + TEST 2025/26, 5 leghe, stessa "
                 "costruzione delle celle). Funzioni MLE/valutazione importate in sola "
                 "lettura da quello script.")
    lines.append("")
    lines.append("**Unica modifica:** una variante della baseline applica ai lambda "
                 "euristici lo STESSO clip usato in `mle_lambdas()` PRIMA di costruire la "
                 f"matrice: `lam = clip(lam, exp(-6), exp(3))` = "
                 f"`clip(lam, {CLIP_LO:.6f}, {CLIP_HI:.4f})`. Tutto il resto della logica "
                 "baseline (team_attr, avg_h/avg_a) e' identico.")
    lines.append("")
    lines.append("Tre varianti:")
    lines.append("")
    lines.append("1. **BASELINE_NOCLIP** — euristica originale, senza clip (riferimento).")
    lines.append("2. **BASELINE_CLIPPED** — stessa euristica, con clip "
                 "`[exp(-6), exp(3)]` sui lambda.")
    lines.append("3. **MLE** — stima congiunta attacco/difesa, identica allo script "
                 "precedente.")
    lines.append("")
    lines.append("Metriche: Brier Score e Log Loss su 1X2, O/U2.5, GG/NG. Valori piu' "
                 "bassi = migliore.")
    lines.append("")

    # ---- conteggio clip attivati ----
    lines.append("## Clip attivati (BASELINE_NOCLIP)")
    lines.append("")
    lines.append("Numero di partite di validation+test in cui almeno uno tra "
                 "`lambda_home`/`lambda_away` prodotto dall'euristica usciva dal range "
                 f"`[exp(-6), exp(3)]` = `[{CLIP_LO:.6f}, {CLIP_HI:.4f}]` (cioe' dove il "
                 "clip interviene davvero).")
    lines.append("")
    lines.append("| Lega | N partite | Clip attivati | % |")
    lines.append("|---|---:|---:|---:|")
    for _, camp_key in LEAGUES:
        d = per_league[camp_key]
        pct = 100.0 * d["n_clipped"] / d["N_base"] if d["N_base"] else 0.0
        lines.append(f"| {camp_key} | {d['N_base']} | {d['n_clipped']} | {pct:.2f}% |")
    pct_tot = 100.0 * total_clipped / n_pooled if n_pooled else 0.0
    lines.append(f"| **TOTALE 5 leghe** | {n_pooled} | {total_clipped} | {pct_tot:.2f}% |")
    lines.append("")

    # ---- costo computazionale ----
    lines.append("## Costo computazionale")
    lines.append("")
    lines.append("| Voce | Valore |")
    lines.append("|---|---|")
    lines.append(f"| Tempo totale esecuzione | {total_time:.1f} s |")
    lines.append(f"| Numero totale di refit MLE eseguiti | {total_refits} |")
    lines.append("")

    # ---- tabelle per lega ----
    for _, camp_key in LEAGUES:
        d = per_league[camp_key]
        res = d["res"]
        lines.append(f"## {camp_key.upper()}  (N={d['N']} val+test, refit MLE={d['refits']}, "
                     f"clip attivati={d['n_clipped']})")
        lines.append("")
        lines.append("| Mercato | Metrica | BASELINE_NOCLIP | BASELINE_CLIPPED | MLE | "
                     "Migliore |")
        lines.append("|---|---|---|---|---|---|")
        for market in MARKETS:
            for mi, mname in ((0, "Brier"), (1, "LogLoss")):
                vals = {v: res[v][market][mi] for v in VARIANTS}
                best = _best_tag(vals)
                lines.append(
                    f"| {market} | {mname} | {vals['BASELINE_NOCLIP']:.4f} | "
                    f"{vals['BASELINE_CLIPPED']:.4f} | {vals['MLE']:.4f} | {best} |"
                )
        lines.append("")

    # ---- aggregato ----
    lines.append(f"## AGGREGATO — 5 LEGHE  (N={n_pooled} val+test)")
    lines.append("")
    lines.append("| Mercato | Metrica | BASELINE_NOCLIP | BASELINE_CLIPPED | MLE | "
                 "Migliore |")
    lines.append("|---|---|---|---|---|---|")
    for market in MARKETS:
        for mi, mname in ((0, "Brier"), (1, "LogLoss")):
            vals = {v: agg[v][market][mi] for v in VARIANTS}
            best = _best_tag(vals)
            lines.append(
                f"| {market} | {mname} | {vals['BASELINE_NOCLIP']:.4f} | "
                f"{vals['BASELINE_CLIPPED']:.4f} | {vals['MLE']:.4f} | {best} |"
            )
    lines.append("")

    # ---- sintesi ----
    # confronto NOCLIP vs CLIPPED e ruolo residuo della MLE
    clip_helps = 0
    clip_changes = 0
    n_cells = 0
    for _, camp_key in LEAGUES:
        res = per_league[camp_key]["res"]
        for market in MARKETS:
            for mi in (0, 1):
                n_cells += 1
                nc = res["BASELINE_NOCLIP"][market][mi]
                cl = res["BASELINE_CLIPPED"][market][mi]
                if abs(nc - cl) > 1e-9:
                    clip_changes += 1
                    if cl < nc:
                        clip_helps += 1
    mle_best_cells = 0
    for _, camp_key in LEAGUES:
        res = per_league[camp_key]["res"]
        for market in MARKETS:
            for mi in (0, 1):
                vals = {v: res[v][market][mi] for v in VARIANTS}
                if _best_tag(vals) == "MLE":
                    mle_best_cells += 1

    lines.append("## Sintesi")
    lines.append("")
    lines.append(f"- Clip attivati in totale: **{total_clipped}/{n_pooled}** partite "
                 f"({pct_tot:.2f}%).")
    lines.append(f"- Celle metrica per-lega: **{n_cells}** (5 leghe x 3 mercati x 2 "
                 f"metriche).")
    lines.append(f"- Celle in cui il clip cambia il risultato (NOCLIP != CLIPPED): "
                 f"**{clip_changes}/{n_cells}**; di queste, il clip **migliora** in "
                 f"**{clip_helps}**.")
    lines.append(f"- Celle in cui la MLE resta la migliore delle tre: "
                 f"**{mle_best_cells}/{n_cells}**.")
    lines.append("")
    lines.append("**Lettura.** Se BASELINE_CLIPPED recupera gran parte del divario di "
                 "LogLoss verso la MLE, allora il vantaggio della MLE osservato nello "
                 "script precedente era in buona parte dovuto ai lambda estremi mal "
                 "calibrati dell'euristica (che il clip taglia), non a una stima "
                 "attack/defence intrinsecamente migliore. Il numero di clip attivati "
                 "quantifica quanto spesso il fenomeno si presenta.")
    lines.append("")
    lines.append("## Note")
    lines.append("")
    lines.append("- rho = 0 per tutte e tre le varianti (nessuna correzione DC celle "
                 "basse): il confronto isola stima dei lambda + clip.")
    lines.append(f"- Bound del clip identici a `mle_lambdas()`: log-spazio "
                 f"[{LOG_LO}, {LOG_HI}] => lineare [{CLIP_LO:.6f}, {CLIP_HI:.4f}].")
    lines.append("- Il conteggio dei clip e' calcolato sui lambda pre-clip "
                 "dell'euristica (BASELINE_NOCLIP), indipendentemente dalla variante.")
    lines.append("- Import in sola lettura da `backtest_experiment_all.py`, "
                 "`diagnose_dixon_coles_rho.py` e `diagnose_mle_attack_defence.py`. "
                 "Nessun file di SoccerMath/ modificato.")
    lines.append("")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
