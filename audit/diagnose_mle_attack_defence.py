"""
diagnose_mle_attack_defence.py — Stima congiunta MLE Dixon-Coles di attacco/difesa
vs l'euristica attuale team_attr() (medie di rapporti gol semplici).

CONTESTO. L'attuale team_attr() (usato in produzione e in tutti gli script di audit)
stima attacco/difesa come medie di rapporti gol per squadra, non una vera MLE
congiunta. Qui si implementa la stima Dixon-Coles standard e la si confronta con
l'euristica, ISOLANDO il solo effetto della stima attack/defence: entrambe le
varianti usano rho = 0 (nessuna correzione tau sulle celle basse).

Modello MLE (per squadra i: attack_i, defence_i; un home_adv globale):
    log(lambda_home) = home_adv + attack_home - defence_away
    log(lambda_away) =           attack_away - defence_home
Vincolo di identificabilita': media(attack_i) = 0 (imposta ricentrando gli attacchi
dentro la funzione obiettivo, il che rimuove l'unica ridondanza del modello:
lo shift simultaneo di tutti gli attack e defence).

Stima: massimizzazione della log-verosimiglianza Poisson congiunta su tutte le
partite di training disponibili fino alla data di refit, via
scipy.optimize.minimize (L-BFGS-B).

Walk-forward NO-leakage con refit mensile (per costo computazionale): a ogni
inizio-mese si rifittano i parametri usando SOLO le partite con Date < inizio mese,
poi quei parametri fissi predicono tutte le partite di quel mese. La finestra di
training e' espansiva (tutto il passato disponibile), mai dati futuri rispetto al
refit. Il primo refit utile parte dalle prime partite disponibili (2022/23).

Confronto (entrambe rho = 0):
  - BASELINE: euristica team_attr() attuale (identica a run_walkforward_lambda di
    diagnose_dixon_coles_rho.py — importata in sola lettura, non modificata).
  - MLE:      stima congiunta descritta sopra, con refit mensile.

Valutazione: VALIDATION 2024/25 + TEST 2025/26, tutte le 5 leghe.
Metriche: Brier Score e Log Loss su 1X2, Over/Under 2.5, GG/NG. Stessa costruzione
delle celle (build_matrix rho=0, market_probs_from_matrix) usata negli script
precedenti.

NON tocca SoccerMath/app.py, config.py, models/. Importa in sola lettura
load_league/LEAGUES da backtest_experiment_all.py.

Output: audit/results/mle_attack_defence_diagnosis.md (tabelle BASELINE vs MLE per
lega/mercato/metrica + costo computazionale: tempo totale e numero di refit MLE).
"""
import os
import sys
import time
import numpy as np
import pandas as pd
from scipy.optimize import minimize

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

# Import in SOLA LETTURA. load_league/LEAGUES dal backtest; la costruzione delle
# celle, la valutazione e l'euristica BASELINE sono riusate da
# diagnose_dixon_coles_rho.py senza modifiche.
from backtest_experiment_all import load_league, LEAGUES  # noqa: E402
from diagnose_dixon_coles_rho import (  # noqa: E402
    run_walkforward_lambda,       # euristica team_attr() -> lambda per partita
    build_matrix,                 # matrice congiunta Poisson (+tau; qui rho=0)
    market_probs_from_matrix,     # 1/X/2, o25, gg dalla matrice
    brier_logloss,                # (brier, logloss) da probs + indici
    SEASONS,                      # ["2024/25", "2025/26"] validation + test
)

RHO = 0.0                    # entrambe le varianti: nessuna correzione DC celle basse
MARKETS = ["1X2", "O/U2.5", "GG/NG"]

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "mle_attack_defence_diagnosis.md")


# ----------------------------------------------------------------------------
# Stima MLE congiunta attacco/difesa (Poisson, home_adv globale)
# ----------------------------------------------------------------------------
def fit_mle(train_df):
    """MLE Dixon-Coles (Poisson) su train_df (partite con Date < refit).

    Ritorna (attack, defence, home_adv, team_index) con attack ricentrato a media 0.
    attack/defence sono np.array indicizzati da team_index (dict nome->idx).
    """
    teams = pd.unique(pd.concat([train_df["HomeClean"], train_df["AwayClean"]]))
    team_index = {t: i for i, t in enumerate(teams)}
    n = len(teams)

    hi = train_df["HomeClean"].map(team_index).to_numpy()
    ai = train_df["AwayClean"].map(team_index).to_numpy()
    yh = train_df["FTHG"].to_numpy(dtype=float)
    ya = train_df["FTAG"].to_numpy(dtype=float)

    # init: home_adv ~ log(media gol casa / media gol trasferta), att/def a 0
    mean_h = max(yh.mean(), 0.05)
    mean_a = max(ya.mean(), 0.05)
    ha0 = float(np.log(mean_h / mean_a)) if mean_a > 0 else 0.25
    x0 = np.zeros(2 * n + 1)
    x0[2 * n] = ha0

    def neg_ll(params):
        raw_att = params[:n]
        att = raw_att - raw_att.mean()          # vincolo: media(attack) = 0
        deff = params[n:2 * n]
        ha = params[2 * n]
        log_lh = ha + att[hi] - deff[ai]
        log_la = att[ai] - deff[hi]
        # clip per stabilita' numerica di exp
        log_lh = np.clip(log_lh, -6.0, 3.0)
        log_la = np.clip(log_la, -6.0, 3.0)
        lh = np.exp(log_lh)
        la = np.exp(log_la)
        # NLL Poisson (i termini log(y!) sono costanti, omessi)
        nll = np.sum(lh - yh * log_lh) + np.sum(la - ya * log_la)
        return nll

    # bounds larghi ma finiti: stabilizzano L-BFGS-B ed evitano derive
    bounds = [(-3.0, 3.0)] * (2 * n) + [(-1.0, 1.5)]
    res = minimize(neg_ll, x0, method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": 500, "ftol": 1e-9})

    params = res.x
    raw_att = params[:n]
    attack = raw_att - raw_att.mean()
    defence = params[n:2 * n]
    home_adv = float(params[2 * n])
    return attack, defence, home_adv, team_index


def mle_lambdas(home, away, attack, defence, home_adv, team_index):
    """lambda_home/lambda_away per una partita dai parametri MLE.
    Squadra non vista in training -> attack/defence = 0 (media di lega)."""
    ih = team_index.get(home)
    ia = team_index.get(away)
    att_h = attack[ih] if ih is not None else 0.0
    def_h = defence[ih] if ih is not None else 0.0
    att_a = attack[ia] if ia is not None else 0.0
    def_a = defence[ia] if ia is not None else 0.0
    lam_h = float(np.exp(np.clip(home_adv + att_h - def_a, -6.0, 3.0)))
    lam_a = float(np.exp(np.clip(att_a - def_h, -6.0, 3.0)))
    return lam_h, lam_a


# ----------------------------------------------------------------------------
# Valutazione mercati da (lambda_h, lambda_a) + realizzazioni
# ----------------------------------------------------------------------------
def eval_from_lambdas(records):
    """records: lista di dict con lambda_h, lambda_a, real_1x2, real_uo, real_gg.
    Ritorna {market: (brier, logloss)} con celle build_matrix(rho=0)."""
    p1x2 = []; y1x2 = []
    p_uo = []; y_uo = []
    p_gg = []; y_gg = []
    for r in records:
        M = build_matrix(r["lambda_h"], r["lambda_a"], RHO)
        m = market_probs_from_matrix(M)
        p1x2.append([m["1"], m["X"], m["2"]])
        y1x2.append({"1": 0, "X": 1, "2": 2}[r["real_1x2"]])
        p_uo.append([m["o25"], 1 - m["o25"]])
        y_uo.append(0 if r["real_uo"] == "OVER" else 1)
        p_gg.append([m["gg"], 1 - m["gg"]])
        y_gg.append(0 if r["real_gg"] == "GG" else 1)
    return {
        "1X2": brier_logloss(np.array(p1x2), np.array(y1x2)),
        "O/U2.5": brier_logloss(np.array(p_uo), np.array(y_uo)),
        "GG/NG": brier_logloss(np.array(p_gg), np.array(y_gg)),
    }


def real_outcomes(row):
    ftr = str(row.FTR).strip().upper()
    real_1x2 = {"H": "1", "D": "X", "A": "2"}.get(ftr, "X")
    tot = row.FTHG + row.FTAG
    real_uo = "OVER" if tot > 2.5 else "UNDER"
    real_gg = "GG" if row.FTHG > 0 and row.FTAG > 0 else "NG"
    return real_1x2, real_uo, real_gg


# ----------------------------------------------------------------------------
# Walk-forward MLE con refit mensile
# ----------------------------------------------------------------------------
def run_mle_walkforward(df):
    """Per le partite di VALIDATION+TEST predice i lambda con parametri MLE
    rifittati a inizio mese (finestra espansiva, no-leakage).
    Ritorna (records, n_refits)."""
    df = df.sort_values("Date", kind="stable").reset_index(drop=True)
    eval_df = df[df["season"].isin(SEASONS)].copy()
    eval_df["month"] = eval_df["Date"].dt.to_period("M")

    records = []
    n_refits = 0
    for period in sorted(eval_df["month"].unique()):
        month_start = period.to_timestamp()          # primo giorno del mese
        train = df[df["Date"] < month_start]
        if len(train) < 20:
            # troppo pochi dati: salta il refit, fallback su medie neutre (att/def=0)
            attack = np.zeros(1); defence = np.zeros(1); team_index = {}
            home_adv = 0.25
        else:
            attack, defence, home_adv, team_index = fit_mle(train)
            n_refits += 1

        month_matches = eval_df[eval_df["month"] == period]
        for _, row in month_matches.iterrows():
            lam_h, lam_a = mle_lambdas(row.HomeClean, row.AwayClean,
                                       attack, defence, home_adv, team_index)
            r1, ruo, rgg = real_outcomes(row)
            records.append({
                "lambda_h": lam_h, "lambda_a": lam_a,
                "real_1x2": r1, "real_uo": ruo, "real_gg": rgg,
            })
    return records, n_refits


def baseline_records(df):
    """BASELINE euristico: riusa run_walkforward_lambda (team_attr) e filtra
    VALIDATION+TEST. Ritorna lista di record compatibili con eval_from_lambdas."""
    rl = run_walkforward_lambda(df)
    ev = rl[rl["season"].isin(SEASONS)]
    records = []
    for _, r in ev.iterrows():
        records.append({
            "lambda_h": r["lambda_h"], "lambda_a": r["lambda_a"],
            "real_1x2": r["real_1x2"], "real_uo": r["real_uo"],
            "real_gg": r["real_gg"],
        })
    return records


# ----------------------------------------------------------------------------
def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t_start = time.perf_counter()

    per_league = {}      # camp_key -> {"BASELINE":{...}, "MLE":{...}, "N":int}
    total_refits = 0
    mle_time = 0.0
    base_time = 0.0
    pooled_base = []
    pooled_mle = []

    for prefix, camp_key in LEAGUES:
        df = load_league(prefix)

        t0 = time.perf_counter()
        base_rec = baseline_records(df)
        base_time += time.perf_counter() - t0

        t0 = time.perf_counter()
        mle_rec, n_refits = run_mle_walkforward(df)
        mle_time += time.perf_counter() - t0
        total_refits += n_refits

        res_base = eval_from_lambdas(base_rec)
        res_mle = eval_from_lambdas(mle_rec)
        per_league[camp_key] = {
            "BASELINE": res_base, "MLE": res_mle,
            "N": len(mle_rec), "N_base": len(base_rec), "refits": n_refits,
        }
        pooled_base.extend(base_rec)
        pooled_mle.extend(mle_rec)
        print(f"[{camp_key}] N_mle={len(mle_rec)} N_base={len(base_rec)} "
              f"refits={n_refits} | "
              f"1X2 Brier base={res_base['1X2'][0]:.4f} mle={res_mle['1X2'][0]:.4f}")

    agg_base = eval_from_lambdas(pooled_base)
    agg_mle = eval_from_lambdas(pooled_mle)

    total_time = time.perf_counter() - t_start
    write_report(per_league, agg_base, agg_mle, len(pooled_mle),
                 total_time, mle_time, base_time, total_refits)
    print(f"\nTempo totale: {total_time:.1f}s  refit MLE: {total_refits}")
    print(f"Scritto: {OUT_PATH}")


def _delta_tag(base, mle):
    """Ritorna stringa delta (base - mle); >0 = MLE migliore (metrica piu' bassa)."""
    d = base - mle
    if d > 0:
        return f"{d:+.4f} (MLE meglio)"
    elif d < 0:
        return f"{d:+.4f} (BASELINE meglio)"
    return "0.0000 (pari)"


def write_report(per_league, agg_base, agg_mle, n_pooled,
                 total_time, mle_time, base_time, total_refits):
    lines = []
    lines.append("# Diagnosi MLE attacco/difesa (Dixon-Coles) vs euristica team_attr()")
    lines.append("")
    lines.append("Confronto della stima dei parametri di forza squadra, isolando il "
                 "**solo** effetto della stima attack/defence: **entrambe** le varianti "
                 "usano rho = 0 (nessuna correzione tau di Dixon-Coles sulle celle basse).")
    lines.append("")
    lines.append("- **BASELINE** — euristica attuale `team_attr()` (medie di rapporti "
                 "gol semplici per squadra), la stessa di `diagnose_ou_gg.py` / "
                 "`diagnose_dixon_coles_rho.py` e della produzione. Riusa "
                 "`run_walkforward_lambda` (import in sola lettura).")
    lines.append("- **MLE** — stima congiunta di massima verosimiglianza Poisson: per "
                 "ogni squadra `attack_i`, `defence_i`; un `home_adv` globale.")
    lines.append("")
    lines.append("```")
    lines.append("log(lambda_home) = home_adv + attack_home - defence_away")
    lines.append("log(lambda_away) =            attack_away - defence_home")
    lines.append("```")
    lines.append("")
    lines.append("Vincolo di identificabilita': media(attack_i) = 0 (ricentraggio degli "
                 "attacchi nella funzione obiettivo). Ottimizzazione con "
                 "`scipy.optimize.minimize(method=\"L-BFGS-B\")`.")
    lines.append("")
    lines.append("**Walk-forward no-leakage con refit mensile.** A ogni inizio-mese i "
                 "parametri MLE vengono rifittati usando SOLO le partite con "
                 "`Date < inizio mese` (finestra di training espansiva, mai dati futuri "
                 "rispetto al refit); quei parametri fissi predicono poi tutte le "
                 "partite del mese. Il primo refit parte dalle prime partite disponibili "
                 "(2022/23).")
    lines.append("")
    lines.append(f"**Valutazione.** VALIDATION 2024/25 + TEST 2025/26, tutte le 5 leghe. "
                 f"Metriche Brier Score e Log Loss su 1X2, Over/Under 2.5, GG/NG. Stessa "
                 f"costruzione delle celle (`build_matrix` rho=0, "
                 f"`market_probs_from_matrix`) degli script precedenti.")
    lines.append("")
    lines.append("Delta = BASELINE - MLE: **positivo => MLE migliore** (Brier/LogLoss "
                 "piu' bassi).")
    lines.append("")

    # ---- costo computazionale ----
    lines.append("## Costo computazionale")
    lines.append("")
    lines.append("L'architettura MLE e' piu' pesante dell'euristica: rifitta decine di "
                 "parametri (2 per squadra + home_adv) a ogni inizio-mese.")
    lines.append("")
    lines.append("| Voce | Valore |")
    lines.append("|---|---|")
    lines.append(f"| Tempo totale esecuzione | {total_time:.1f} s |")
    lines.append(f"| Tempo speso nel walk-forward MLE (5 leghe) | {mle_time:.1f} s |")
    lines.append(f"| Tempo speso nella BASELINE euristica (5 leghe) | {base_time:.1f} s |")
    lines.append(f"| Numero totale di refit MLE eseguiti | {total_refits} |")
    lines.append(f"| Tempo medio per refit MLE | "
                 f"{(mle_time / total_refits if total_refits else 0):.3f} s |")
    lines.append("")

    # ---- tabella per lega ----
    for _, camp_key in [(p, c) for p, c in LEAGUES]:
        d = per_league[camp_key]
        lines.append(f"## {camp_key.upper()}  (N={d['N']} val+test, refit MLE={d['refits']})")
        lines.append("")
        lines.append("| Mercato | Metrica | BASELINE | MLE | Delta (base-MLE) |")
        lines.append("|---|---|---|---|---|")
        for market in MARKETS:
            bb, bl = d["BASELINE"][market]
            mb, ml = d["MLE"][market]
            lines.append(f"| {market} | Brier | {bb:.4f} | {mb:.4f} | "
                         f"{_delta_tag(bb, mb)} |")
            lines.append(f"| {market} | LogLoss | {bl:.4f} | {ml:.4f} | "
                         f"{_delta_tag(bl, ml)} |")
        lines.append("")

    # ---- aggregato ----
    lines.append(f"## AGGREGATO — 5 LEGHE  (N={n_pooled} val+test)")
    lines.append("")
    lines.append("| Mercato | Metrica | BASELINE | MLE | Delta (base-MLE) |")
    lines.append("|---|---|---|---|---|")
    for market in MARKETS:
        bb, bl = agg_base[market]
        mb, ml = agg_mle[market]
        lines.append(f"| {market} | Brier | {bb:.4f} | {mb:.4f} | {_delta_tag(bb, mb)} |")
        lines.append(f"| {market} | LogLoss | {bl:.4f} | {ml:.4f} | {_delta_tag(bl, ml)} |")
    lines.append("")

    # ---- sintesi ----
    n_metrics = 0
    mle_wins = 0
    for _, camp_key in LEAGUES:
        d = per_league[camp_key]
        for market in MARKETS:
            for i in (0, 1):  # Brier, LogLoss
                n_metrics += 1
                if d["BASELINE"][market][i] - d["MLE"][market][i] > 0:
                    mle_wins += 1
    lines.append("## Sintesi")
    lines.append("")
    lines.append(f"- Celle metrica per-lega confrontate: **{n_metrics}** "
                 f"(5 leghe x 3 mercati x 2 metriche).")
    lines.append(f"- Celle in cui la MLE batte la BASELINE: **{mle_wins}/{n_metrics}**.")
    agg_wins = sum(1 for market in MARKETS for i in (0, 1)
                   if agg_base[market][i] - agg_mle[market][i] > 0)
    lines.append(f"- Nell'aggregato la MLE vince su **{agg_wins}/6** celle "
                 f"(3 mercati x 2 metriche).")
    lines.append("")
    lines.append("**Lettura.** La MLE congiunta e' teoricamente piu' corretta "
                 "dell'euristica (stima i parametri massimizzando la verosimiglianza del "
                 "modello effettivamente usato per predire), ma e' molto piu' costosa "
                 "(refit di 2*n_squadre+1 parametri a ogni mese). Il confronto qui misura "
                 "se il guadagno predittivo out-of-sample giustifica il costo: delta "
                 "vicini a zero indicano che l'euristica, molto piu' leggera, e' gia' "
                 "competitiva; delta sistematicamente positivi indicano un vantaggio "
                 "reale della MLE.")
    lines.append("")
    lines.append("## Note")
    lines.append("")
    lines.append("- Entrambe le varianti: rho = 0 (nessuna correzione DC celle basse), "
                 "cosi' il delta isola solo l'effetto della stima attack/defence.")
    lines.append("- MLE: vincolo media(attack)=0 imposto per ricentraggio nella funzione "
                 "obiettivo (rimuove l'unica ridondanza del modello). Squadre neopromosse "
                 "non presenti nel training del mese: attack=defence=0 (forza media di "
                 "lega), home_adv comunque applicato.")
    lines.append("- Refit mensile a finestra espansiva: nessun dato con "
                 "`Date >= inizio mese` entra nel training di quel mese (no-leakage).")
    lines.append("- Import in sola lettura da `backtest_experiment_all.py` "
                 "(`load_league`, `LEAGUES`) e da `diagnose_dixon_coles_rho.py` "
                 "(`run_walkforward_lambda`, `build_matrix`, `market_probs_from_matrix`, "
                 "`brier_logloss`). Nessun file di SoccerMath/ modificato.")
    lines.append("")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
