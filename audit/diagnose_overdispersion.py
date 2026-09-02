"""
diagnose_overdispersion.py — Overdispersion dei gol segnati (FTHG / FTAG) rispetto
a una Poisson pura, per ciascuna delle 5 leghe.

La domanda: la distribuzione dei gol segnati in casa (FTHG) e in trasferta (FTAG)
e' compatibile con una Poisson (dove varianza = media per definizione), oppure
mostra overdispersion (varianza > media) che una Negative Binomial cattura meglio?

Per ciascuna lega e per ciascuna delle due serie (FTHG, FTAG), su TUTTE le stagioni
disponibili 2022/23-2025/26 (la stagione Live 2026/27 e' esclusa: incompleta):

  1. Distribuzione empirica dei gol segnati in casa (FTHG) e in trasferta (FTAG),
     tenute SEPARATE (non il totale della partita).
  2. Fit via MLE di:
       - Poisson pura              (1 parametro: lambda = mu)
       - Negative Binomial NB2     (2 parametri: mu, alpha), parametrizzazione
         media-dispersione:  Var = mu + alpha * mu^2
     con AIC e BIC per entrambi i modelli.
  3. Indice di dispersione empirico = varianza / media (test diretto):
       > 1  -> overdispersion rispetto a Poisson pura
       ~ 1  -> Poisson adeguata
  4. Parametro di dispersione alpha stimato della NegBin (0 = Poisson).

Non tocca SoccerMath/app.py, config.py, models/. Importa in sola lettura
load_league / LEAGUES da backtest_experiment_all.py.

Produce audit/results/overdispersion_diagnosis.md con, per lega/serie:
  media, varianza, indice di dispersione, AIC Poisson, AIC NegBin,
  BIC Poisson, BIC NegBin, parametro di dispersione (alpha) della NegBin.
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd
from scipy.stats import poisson as scipy_poisson
from scipy.stats import nbinom as scipy_nbinom

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

# Import in SOLA LETTURA — nessuna modifica a SoccerMath/ o a backtest_experiment_all.
from backtest_experiment_all import load_league, LEAGUES  # noqa: E402

import statsmodels.api as sm  # noqa: E402
from statsmodels.discrete.discrete_model import (  # noqa: E402
    Poisson as SMPoisson,
    NegativeBinomial as SMNegativeBinomial,
)

# Stagioni complete: la Live (2026/27) e' esclusa perche' incompleta.
SEASONS = ["2022/23", "2023/24", "2024/25", "2025/26"]

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "overdispersion_diagnosis.md")


def poisson_mle(y):
    """MLE Poisson in forma chiusa: lambda_hat = media campionaria.
    Ritorna (lambda_hat, loglik, aic, bic). k = 1 parametro."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    lam = y.mean()
    ll = float(np.sum(scipy_poisson.logpmf(y, lam)))
    k = 1
    aic = 2 * k - 2 * ll
    bic = k * np.log(n) - 2 * ll
    return lam, ll, aic, bic


def negbin_mle(y):
    """MLE Negative Binomial NB2 (parametrizzazione media-dispersione).

    Modello con sola intercetta: Var = mu + alpha * mu^2.
    Usa statsmodels.discrete.NegativeBinomial (loglike = NB2) su una costante,
    che fitta congiuntamente mu (via intercetta) e alpha via MLE.
    Ritorna (mu_hat, alpha_hat, loglik, aic, bic, converged). k = 2 parametri.

    Fallback: se statsmodels non converge, MLE diretta sulla griglia di alpha
    con scipy.stats.nbinom (mu fissato alla media campionaria — MLE per NB2 con
    mu libero coincide con la media campionaria quando c'e' solo l'intercetta).
    """
    y = np.asarray(y, dtype=float)
    n = len(y)
    exog = np.ones((n, 1))
    k = 2

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            model = SMNegativeBinomial(y, exog, loglike_method="nb2")
            res = model.fit(disp=0, maxiter=200)
            mu = float(np.exp(res.params[0]))
            alpha = float(res.params[1])
            ll = float(res.llf)
            converged = bool(res.mle_retvals.get("converged", True))
            if converged and np.isfinite(ll) and alpha > 0:
                aic = 2 * k - 2 * ll
                bic = k * np.log(n) - 2 * ll
                return mu, alpha, ll, aic, bic, True
        except Exception:
            pass

    # Fallback MLE diretto: mu = media campionaria, alpha ottimizzato su griglia fine.
    mu = y.mean()

    def nb_loglik(alpha):
        # NB2: size r = 1/alpha, prob p = r / (r + mu)
        r = 1.0 / alpha
        p = r / (r + mu)
        return float(np.sum(scipy_nbinom.logpmf(y, r, p)))

    best_alpha, best_ll = None, -np.inf
    for alpha in np.concatenate([np.linspace(1e-4, 1.0, 2000),
                                 np.linspace(1.0, 5.0, 800)]):
        ll = nb_loglik(alpha)
        if ll > best_ll:
            best_ll, best_alpha = ll, alpha
    aic = 2 * k - 2 * best_ll
    bic = k * np.log(n) - 2 * best_ll
    return mu, float(best_alpha), float(best_ll), aic, bic, False


def analyze_series(y):
    """Statistiche descrittive + fit Poisson e NegBin per una serie di conteggi."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    mean = float(y.mean())
    var = float(y.var(ddof=1))               # varianza campionaria (ddof=1)
    disp_index = var / mean if mean > 0 else float("nan")

    p_lam, p_ll, p_aic, p_bic = poisson_mle(y)
    nb_mu, nb_alpha, nb_ll, nb_aic, nb_bic, nb_conv = negbin_mle(y)

    return {
        "n": n,
        "mean": mean,
        "var": var,
        "disp_index": disp_index,
        "pois_lambda": p_lam,
        "pois_ll": p_ll,
        "pois_aic": p_aic,
        "pois_bic": p_bic,
        "nb_mu": nb_mu,
        "nb_alpha": nb_alpha,
        "nb_ll": nb_ll,
        "nb_aic": nb_aic,
        "nb_bic": nb_bic,
        "nb_converged": nb_conv,
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    rows = []           # righe della tabella riassuntiva
    per_league = {}     # dettaglio per stampa a console

    for prefix, league in LEAGUES:
        df = load_league(prefix)
        df = df[df["season"].isin(SEASONS)].copy()

        n_matches = len(df)
        for label, col in (("FTHG (gol casa)", "FTHG"),
                           ("FTAG (gol trasferta)", "FTAG")):
            y = df[col].to_numpy(dtype=float)
            stats = analyze_series(y)
            stats["league"] = league
            stats["series"] = label
            stats["n_matches"] = n_matches
            rows.append(stats)

        per_league[league] = n_matches
        print(f"[{league}] {n_matches} partite  "
              f"FTHG mean={rows[-2]['mean']:.3f} var={rows[-2]['var']:.3f} "
              f"disp={rows[-2]['disp_index']:.3f} | "
              f"FTAG mean={rows[-1]['mean']:.3f} var={rows[-1]['var']:.3f} "
              f"disp={rows[-1]['disp_index']:.3f}")

    write_report(rows, per_league)
    print(f"\nScritto: {OUT_PATH}")


def _fmt(x, nd=4):
    return f"{x:.{nd}f}"


def write_report(rows, per_league):
    lines = []
    lines.append("# Diagnosi overdispersion — gol segnati in casa (FTHG) e in trasferta (FTAG)")
    lines.append("")
    lines.append("Campione: TUTTE le stagioni complete disponibili "
                 "**2022/23, 2023/24, 2024/25, 2025/26** per le 5 leghe "
                 "(la stagione Live 2026/27 e' esclusa perche' incompleta).")
    lines.append("")
    lines.append("Le due serie di conteggio (FTHG = gol segnati dai padroni di casa, "
                 "FTAG = gol segnati dagli ospiti) sono trattate **separatamente**, "
                 "non come totale della partita.")
    lines.append("")
    lines.append("Metodo:")
    lines.append("")
    lines.append("- **Poisson pura** (MLE, 1 parametro: lambda = media). "
                 "Per definizione varianza = media.")
    lines.append("- **Negative Binomial NB2** (MLE, 2 parametri: mu, alpha), "
                 "parametrizzazione media-dispersione `Var = mu + alpha * mu^2`. "
                 "Fit con `statsmodels.discrete.NegativeBinomial` (loglike NB2) su "
                 "sola intercetta; alpha = **parametro di dispersione** (alpha = 0 "
                 "=> Poisson pura).")
    lines.append("- **AIC** = 2k - 2*logL, **BIC** = k*ln(n) - 2*logL "
                 "(k=1 Poisson, k=2 NegBin). Valori piu' bassi = modello preferito.")
    lines.append("- **Indice di dispersione** = varianza campionaria (ddof=1) / media. "
                 "`> 1` overdispersion rispetto a Poisson; `~ 1` Poisson adeguata.")
    lines.append("")

    # -------- Tabella principale richiesta --------
    lines.append("## Tabella riassuntiva per lega / serie")
    lines.append("")
    header = ("| Lega | Serie | n | Media | Varianza | Indice disp. "
              "(var/media) | AIC Poisson | AIC NegBin | BIC Poisson | "
              "BIC NegBin | alpha NegBin |")
    sep = "|---|---|---|---|---|---|---|---|---|---|---|"
    lines.append(header)
    lines.append(sep)
    for r in rows:
        lines.append(
            f"| {r['league']} | {r['series']} | {r['n']} | "
            f"{_fmt(r['mean'],3)} | {_fmt(r['var'],3)} | {_fmt(r['disp_index'],3)} | "
            f"{_fmt(r['pois_aic'],1)} | {_fmt(r['nb_aic'],1)} | "
            f"{_fmt(r['pois_bic'],1)} | {_fmt(r['nb_bic'],1)} | "
            f"{_fmt(r['nb_alpha'],4)} |"
        )
    lines.append("")

    # -------- Delta AIC/BIC e verdetto --------
    lines.append("## Confronto modelli: delta AIC/BIC (Poisson - NegBin) e verdetto")
    lines.append("")
    lines.append("delta positivo = la NegBin e' preferita (AIC/BIC piu' basso). "
                 "Regola pratica: |delta| < 2 differenza trascurabile, "
                 "2-6 debole, 6-10 forte, > 10 molto forte a favore del modello migliore.")
    lines.append("")
    lines.append("| Lega | Serie | dAIC (P-NB) | dBIC (P-NB) | Indice disp. | "
                 "Modello preferito |")
    lines.append("|---|---|---|---|---|---|")
    for r in rows:
        d_aic = r["pois_aic"] - r["nb_aic"]
        d_bic = r["pois_bic"] - r["nb_bic"]
        # verdetto basato su BIC (piu' conservativo) + coerenza indice dispersione
        if d_bic > 2:
            verdict = "NegBin"
        elif d_bic < -2:
            verdict = "Poisson"
        else:
            verdict = "equivalenti"
        lines.append(
            f"| {r['league']} | {r['series']} | {_fmt(d_aic,1)} | "
            f"{_fmt(d_bic,1)} | {_fmt(r['disp_index'],3)} | {verdict} |"
        )
    lines.append("")

    # -------- Sintesi --------
    over = [r for r in rows if r["disp_index"] > 1.05]
    under = [r for r in rows if r["disp_index"] < 0.95]
    nb_pref_bic = [r for r in rows if (r["pois_bic"] - r["nb_bic"]) > 2]
    nb_pref_aic = [r for r in rows if (r["pois_aic"] - r["nb_aic"]) > 2]

    lines.append("## Sintesi")
    lines.append("")
    lines.append(f"- Serie totali analizzate: **{len(rows)}** "
                 f"(2 serie x 5 leghe).")
    lines.append(f"- Serie con indice di dispersione > 1.05 (overdispersion "
                 f"apprezzabile): **{len(over)}/{len(rows)}**.")
    lines.append(f"- Serie con indice di dispersione < 0.95 (underdispersion): "
                 f"**{len(under)}/{len(rows)}**.")
    lines.append(f"- Serie in cui la NegBin batte la Poisson per **AIC** (delta > 2): "
                 f"**{len(nb_pref_aic)}/{len(rows)}**.")
    lines.append(f"- Serie in cui la NegBin batte la Poisson per **BIC** (delta > 2): "
                 f"**{len(nb_pref_bic)}/{len(rows)}**.")
    lines.append("")

    mean_disp = float(np.mean([r["disp_index"] for r in rows]))
    mean_alpha = float(np.mean([r["nb_alpha"] for r in rows]))
    lines.append(f"- Indice di dispersione medio su tutte le serie: "
                 f"**{mean_disp:.3f}**.")
    lines.append(f"- alpha NegBin medio su tutte le serie: **{mean_alpha:.4f}** "
                 f"(vicino a 0 => la Poisson e' gia' una buona approssimazione).")
    lines.append("")
    lines.append("**Lettura.** Un indice di dispersione vicino a 1 e un alpha vicino "
                 "a 0, con AIC/BIC che non preferiscono nettamente la NegBin, indicano "
                 "che la distribuzione dei gol segnati (per singola squadra, casa o "
                 "trasferta) e' ben descritta da una Poisson pura: l'eventuale "
                 "sovradispersione osservata nei gol *totali* di partita nasce dalla "
                 "somma/correlazione delle due marginali e dall'eterogeneita' tra "
                 "squadre, non dalla marginale di conteggio in se'. Dove invece l'indice "
                 "supera 1 e la NegBin e' preferita da BIC, c'e' overdispersion reale "
                 "nella marginale.")
    lines.append("")

    # -------- Note metodologiche --------
    lines.append("## Note")
    lines.append("")
    lines.append("- Dati caricati via `load_league` da `backtest_experiment_all.py` "
                 "(import in sola lettura): stessa pulizia/dedup usata dal backtest. "
                 "Nessun file di SoccerMath/ e' stato modificato.")
    lines.append("- Varianza campionaria con `ddof=1`. Con n grande (centinaia di "
                 "osservazioni per serie) la differenza rispetto a ddof=0 e' "
                 "trascurabile per l'indice di dispersione.")
    lines.append("- La NegBin e' fittata con la parametrizzazione media-dispersione "
                 "NB2; il parametro riportato e' alpha. Conversione a "
                 "`scipy.stats.nbinom`: size `r = 1/alpha`, prob `p = r/(r+mu)`.")
    conv_fail = [r for r in rows if not r["nb_converged"]]
    if conv_fail:
        names = ", ".join(f"{r['league']}/{r['series']}" for r in conv_fail)
        lines.append(f"- Fit NegBin via fallback (griglia su alpha, MLE diretta con "
                     f"scipy) per: {names}.")
    else:
        lines.append("- Tutti i fit NegBin (statsmodels) sono andati a convergenza.")
    lines.append("")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
