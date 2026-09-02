"""
diagnose_rho_bootstrap.py — Robustezza dell'effetto del rho di Dixon-Coles via
bootstrap non parametrico sul Brier Score, partita per partita.

Domanda: la differenza di Brier Score tra la Poisson pura (RHO_ZERO, rho=0) e la
correzione Dixon-Coles con rho globale gia' stimato (RHO_GLOBALE, rho=-0.0470) e'
un segnale statisticamente robusto in questo campione, o e' indistinguibile dal
rumore campionario?

NON tocca SoccerMath/app.py, config.py, models/. Importa in sola lettura
load_league/LEAGUES da backtest_experiment_all.py e RIUSA la stessa logica
walk-forward no-leakage gia' scritta in diagnose_dixon_coles_rho.py
(run_walkforward_lambda, build_matrix, market_probs_from_matrix): nessuna
duplicazione, nessuna modifica a quei file.

Metodo:
  1. Per ciascuna lega genera le predizioni walk-forward su VALIDATION 2024/25 +
     TEST 2025/26. Per ogni partita calcola le probabilita' con rho=0 (RHO_ZERO) e
     con rho=-0.0470 (RHO_GLOBALE), e il Brier Score PER PARTITA su:
       - 1X2   (3 classi: 1/X/2)
       - GG/NG (2 classi)
     (i due mercati dove diagnose_dixon_coles_rho.py ha mostrato un effetto del rho)
     La differenza per-partita e' d_i = Brier(RHO_ZERO)_i - Brier(RHO_GLOBALE)_i:
     d_i > 0 => in quella partita il rho ha ridotto il Brier (miglioramento).
  2. Bootstrap non parametrico: B=2000 resample con reinserimento sul campione di
     partite di ciascuna lega (stessa dimensione campionaria originale). Per ogni
     resample si ricalcola la differenza MEDIA di Brier. CI 95% = percentili
     2.5-97.5 delle B medie. Idem per un campione AGGREGATO (pooling di tutte le
     partite delle 5 leghe).
  3. Per ciascuna lega/mercato: il CI include lo zero (=> non distinguibile dal
     rumore) oppure no (=> segnale robusto in questo campione)?
  4. Output: audit/results/rho_bootstrap_ci.md

Convenzione segno: differenza media > 0 = RHO_GLOBALE MEGLIO di RHO_ZERO
(Brier piu' basso col rho). CI interamente > 0 => il rho aiuta in modo robusto;
CI interamente < 0 => il rho peggiora in modo robusto; CI che include 0 => rumore.
"""
import os
import sys
import numpy as np

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

# Import in SOLA LETTURA. load_league/LEAGUES dal backtest; la logica walk-forward
# e la costruzione della matrice sono riusate da diagnose_dixon_coles_rho.py.
from backtest_experiment_all import load_league, LEAGUES  # noqa: E402
from diagnose_dixon_coles_rho import (  # noqa: E402
    run_walkforward_lambda,
    build_matrix,
    market_probs_from_matrix,
    SEASONS,          # ["2024/25", "2025/26"]  (validation + test)
)

RHO_ZERO = 0.0
RHO_GLOBALE = -0.0470     # rho globale gia' stimato (pooled 5 leghe) su training
N_BOOT = 2000
CI_LOW, CI_HIGH = 2.5, 97.5
SEED = 12345
MARKETS = ["1X2", "GG/NG"]

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "rho_bootstrap_ci.md")


def match_brier(probs, y_idx):
    """Brier score di una singola partita: sum_k (onehot_k - p_k)^2."""
    oh = np.zeros(len(probs))
    oh[y_idx] = 1.0
    return float(np.sum((np.asarray(probs) - oh) ** 2))


def per_match_brier_diffs(eval_df):
    """Per ogni partita del campione (val+test) di una lega, calcola la differenza
    di Brier Score (RHO_ZERO - RHO_GLOBALE) su 1X2 e GG/NG.

    Ritorna dict market -> np.array(diffs) con la convenzione:
        d_i = Brier(rho=0)_i - Brier(rho=-0.0470)_i
    quindi d_i > 0 => il rho ha migliorato (ridotto il Brier) su quella partita.
    """
    diffs = {m: [] for m in MARKETS}
    for _, r in eval_df.iterrows():
        M0 = build_matrix(r["lambda_h"], r["lambda_a"], RHO_ZERO)
        Mg = build_matrix(r["lambda_h"], r["lambda_a"], RHO_GLOBALE)
        m0 = market_probs_from_matrix(M0)
        mg = market_probs_from_matrix(Mg)

        # 1X2 (3 classi: 1/X/2)
        y_1x2 = {"1": 0, "X": 1, "2": 2}[r["real_1x2"]]
        b0 = match_brier([m0["1"], m0["X"], m0["2"]], y_1x2)
        bg = match_brier([mg["1"], mg["X"], mg["2"]], y_1x2)
        diffs["1X2"].append(b0 - bg)

        # GG/NG (2 classi: GG/NG)
        y_gg = 0 if r["real_gg"] == "GG" else 1
        b0 = match_brier([m0["gg"], 1 - m0["gg"]], y_gg)
        bg = match_brier([mg["gg"], 1 - mg["gg"]], y_gg)
        diffs["GG/NG"].append(b0 - bg)

    return {m: np.asarray(v, dtype=float) for m, v in diffs.items()}


def bootstrap_ci(diffs, rng, n_boot=N_BOOT):
    """Bootstrap non parametrico della differenza MEDIA di Brier.

    diffs: array (n,) delle differenze per-partita. Estrae n_boot campioni con
    reinserimento di dimensione n, calcola la media di ciascuno, ritorna
    (mean_osservata, ci_low, ci_high, frac_positivi).
    """
    n = len(diffs)
    obs_mean = float(np.mean(diffs))
    idx = rng.integers(0, n, size=(n_boot, n))
    boot_means = diffs[idx].mean(axis=1)
    lo = float(np.percentile(boot_means, CI_LOW))
    hi = float(np.percentile(boot_means, CI_HIGH))
    frac_pos = float(np.mean(boot_means > 0))
    return obs_mean, lo, hi, frac_pos


def includes_zero(lo, hi):
    return lo <= 0.0 <= hi


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    rng = np.random.default_rng(SEED)

    # --- genera predizioni walk-forward per lega, raccogli le diff per-partita ---
    league_diffs = {}      # camp_key -> {market: array}
    pooled = {m: [] for m in MARKETS}
    league_n = {}

    for prefix, camp_key in LEAGUES:
        df = load_league(prefix)
        rl = run_walkforward_lambda(df)
        ev = rl[rl["season"].isin(SEASONS)].reset_index(drop=True)
        d = per_match_brier_diffs(ev)
        league_diffs[camp_key] = d
        league_n[camp_key] = len(ev)
        for m in MARKETS:
            pooled[m].append(d[m])
        print(f"[{camp_key}] N={len(ev)}  "
              + "  ".join(f"{m}: mean_d={np.mean(d[m]):+.5f}" for m in MARKETS))

    pooled = {m: np.concatenate(pooled[m]) for m in MARKETS}

    # --- bootstrap per lega/mercato ---
    results = {}   # (camp_key, market) -> (obs, lo, hi, frac_pos)
    for _, camp_key in LEAGUES:
        for m in MARKETS:
            results[(camp_key, m)] = bootstrap_ci(league_diffs[camp_key][m], rng)

    # --- bootstrap aggregato (pooling di tutte le partite delle 5 leghe) ---
    agg = {}
    for m in MARKETS:
        agg[m] = bootstrap_ci(pooled[m], rng)

    write_report(results, agg, league_n, pooled)
    print(f"\nScritto: {OUT_PATH}")


def _sig(lo, hi):
    if includes_zero(lo, hi):
        return "si", "rumore (CI include 0)"
    if lo > 0:
        return "no", "robusto: rho MEGLIO"
    return "no", "robusto: rho PEGGIO"


def write_report(results, agg, league_n, pooled):
    lines = []
    lines.append("# Bootstrap CI 95% — effetto del rho Dixon-Coles sul Brier Score")
    lines.append("")
    lines.append(f"Campione: predizioni walk-forward no-leakage su **VALIDATION 2024/25 "
                 f"+ TEST 2025/26**, tutte le 5 leghe. Stessa logica di "
                 f"`diagnose_dixon_coles_rho.py` (import in sola lettura: "
                 f"`run_walkforward_lambda`, `build_matrix`, "
                 f"`market_probs_from_matrix`). Nessuna modifica a SoccerMath/.")
    lines.append("")
    lines.append(f"Confronto: **RHO_ZERO** (rho = 0, Poisson pura) vs "
                 f"**RHO_GLOBALE** (rho = {RHO_GLOBALE:+.4f}, gia' stimato su training "
                 f"pooled 5 leghe). Mercati analizzati: **1X2** e **GG/NG** (i due dove "
                 f"il rho ha mostrato un effetto nella diagnosi originale).")
    lines.append("")
    lines.append("**Metodo.** Per ogni partita si calcola la differenza di Brier Score "
                 "`d_i = Brier(RHO_ZERO)_i - Brier(RHO_GLOBALE)_i`. Bootstrap non "
                 f"parametrico: {N_BOOT} resample con reinserimento (stessa dimensione "
                 "campionaria della lega), media di `d` per ogni resample, CI 95% = "
                 f"percentili {CI_LOW}-{CI_HIGH}. Seed fisso = {SEED}.")
    lines.append("")
    lines.append("**Segno.** Differenza media `> 0` => RHO_GLOBALE **migliore** "
                 "(Brier piu' basso col rho); `< 0` => rho peggiore. Se il CI 95% "
                 "**include lo zero** l'effetto e' **indistinguibile dal rumore**; se il "
                 "CI e' interamente sopra (o sotto) lo zero l'effetto e' un **segnale "
                 "statisticamente robusto in questo campione**.")
    lines.append("")

    # --- tabella principale lega x mercato ---
    lines.append("## Tabella: lega x mercato")
    lines.append("")
    lines.append("| Lega | Mercato | N | Diff. media (Z-G) | CI95% basso | CI95% alto | "
                 "Include zero | Verdetto |")
    lines.append("|---|---|---|---:|---:|---:|:---:|---|")
    for _, camp_key in LEAGUES:
        for m in MARKETS:
            obs, lo, hi, _ = results[(camp_key, m)]
            inc, verdict = _sig(lo, hi)
            lines.append(
                f"| {camp_key} | {m} | {league_n[camp_key]} | {obs:+.6f} | "
                f"{lo:+.6f} | {hi:+.6f} | {inc} | {verdict} |"
            )
    lines.append("")

    # --- aggregato ---
    n_tot = len(pooled[MARKETS[0]])
    lines.append("## Aggregato — 5 leghe insieme (pooling dei resample)")
    lines.append("")
    lines.append(f"Resample con reinserimento sul campione poolato di tutte le partite "
                 f"delle 5 leghe (N = {n_tot}).")
    lines.append("")
    lines.append("| Campione | Mercato | N | Diff. media (Z-G) | CI95% basso | "
                 "CI95% alto | Include zero | Verdetto |")
    lines.append("|---|---|---|---:|---:|---:|:---:|---|")
    for m in MARKETS:
        obs, lo, hi, _ = agg[m]
        inc, verdict = _sig(lo, hi)
        lines.append(
            f"| POOLED 5 leghe | {m} | {n_tot} | {obs:+.6f} | {lo:+.6f} | "
            f"{hi:+.6f} | {inc} | {verdict} |"
        )
    lines.append("")

    # --- sintesi ---
    robust = [(lg, m) for (lg, m), (o, lo, hi, _) in results.items()
              if not includes_zero(lo, hi)]
    noise = [(lg, m) for (lg, m), (o, lo, hi, _) in results.items()
             if includes_zero(lo, hi)]
    lines.append("## Sintesi")
    lines.append("")
    lines.append(f"- Combinazioni lega x mercato analizzate: **{len(results)}** "
                 f"(5 leghe x 2 mercati).")
    lines.append(f"- CI 95% che **NON** include lo zero (segnale robusto in questo "
                 f"campione): **{len(robust)}/{len(results)}**"
                 + (": " + ", ".join(f"{lg}/{m}" for lg, m in robust) if robust else "")
                 + ".")
    lines.append(f"- CI 95% che include lo zero (indistinguibile dal rumore): "
                 f"**{len(noise)}/{len(results)}**.")
    for m in MARKETS:
        obs, lo, hi, _ = agg[m]
        inc, _v = _sig(lo, hi)
        state = "include lo zero" if inc == "si" else "non include lo zero"
        lines.append(f"- Aggregato {m}: diff. media {obs:+.6f}, "
                     f"CI95% [{lo:+.6f}, {hi:+.6f}] — {state}.")
    lines.append("")
    lines.append("**Lettura.** Le differenze di Brier in gioco sono minuscole "
                 "(ordine 1e-3 o inferiore per partita): il bootstrap serve proprio a "
                 "capire se, pur piccole, sono sistematiche o solo rumore di "
                 "campionamento. Dove il CI include lo zero, il segno osservato della "
                 "differenza media non e' affidabile e il rho e' di fatto ininfluente "
                 "su quel mercato/lega in questo campione. L'aggregato, avendo la N piu' "
                 "grande, e' il test piu' potente per un effetto sistematico.")
    lines.append("")
    lines.append("## Note")
    lines.append("")
    lines.append(f"- rho fisso = {RHO_GLOBALE:+.4f} (RHO_GLOBALE gia' stimato via MLE su "
                 "training 2022/23+2023/24 in `diagnose_dixon_coles_rho.py`; qui NON "
                 "viene ristimato).")
    lines.append("- Brier per-partita: 1X2 su 3 classi (1/X/2), GG/NG su 2 classi. "
                 "La differenza usa la stessa realizzazione e gli stessi lambda "
                 "walk-forward per entrambi i valori di rho, quindi e' un confronto "
                 "appaiato (paired) partita per partita.")
    lines.append(f"- Bootstrap: {N_BOOT} resample, seed {SEED} "
                 "(`numpy.random.default_rng`), percentili "
                 f"{CI_LOW}/{CI_HIGH}. Nessun file di SoccerMath/ modificato.")
    lines.append("")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
