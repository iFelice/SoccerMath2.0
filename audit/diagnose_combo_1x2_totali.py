"""
diagnose_combo_1x2_totali.py — Quanto pesa la correlazione tra testa 1X2 e testa
Totali quando le due probabilita' vengono moltiplicate per formare una combo?

Domanda operativa: il Top Mix mostra P(1) (testa 1X2, con ensemble Poisson+Elo)
e P(Over 2.5)/P(Under 2.5) (testa Totali, lambda puri) come due numeri INDIPENDENTI.
Se qualcuno costruisce una combo "1 + Over 2.5" moltiplicandoli, sta assumendo
un'indipendenza che le due teste NON hanno: una partita da 3+ gol e una vittoria
della casa condividono gli stessi lambda, quindi sono correlate POSITIVAMENTE,
e il pareggio lo e' NEGATIVAMENTE. Qui si misura l'errore di quella assunzione
usando la matrice bivariata che il motore gia' costruisce e butta via.

VERSIONI A CONFRONTO per ogni combo (stessa partita, stesso stato no-leakage):
  a) GRID_1X2   : griglia Poisson congiunta sui lambda della testa 1X2 (att/def,
                  con fattore mercato, NORM-SUM sulla base con forma att0/def0),
                  somma sulle celle (h,a) che soddisfano esito 1X2 E totale;
  b) GRID_TOT   : stessa griglia congiunta ma sui lambda della testa Totali
                  (att0_pure/def0_pure: xG/gol di lungo periodo, M=1, senza forma);
  c) NAIVE      : prodotto delle due probabilita' GIA' MOSTRATE dal Top Mix:
                  P(1) blendata ELO_ENSEMBLE_W*Poisson+(1-w)*Elo per la testa 1X2,
                  P(Over/Under 2.5) dalla testa Totali. Nessuna correzione di
                  correlazione (e' la definizione di indipendenza).
  c0) NAIVE_PURO: controllo aggiunto per separare gli effetti: prodotto delle
                  marginali PURE (P(1) dalla griglia 1X2 senza Elo x P(totale)
                  dalla testa Totali). c0 -> a isola la SOLA correlazione;
                  c -> c0 isola il SOLO contributo dell'Elo.

DISCIPLINA (la stessa di grid_search_ensemble_weight.py):
  * TRAIN 2022/23+2023/24 usata solo per leggere la direzione e per qualsiasi
    scelta; VALIDATION 2024/25 conferma; TEST 2025/26 e' SOLA LETTURA, mai
    usata per scegliere o ritarare nulla;
  * le prime TRAIN_WARMUP=60 partite/lega restano nello STATO ma sono escluse
    dal campione TRAIN (cold start: DB vuoto, medie gol/forma/Elo non informativi);
  * una differenza che cade dentro l'IC bootstrap e' rumore, non miglioramento
    (N_BOOT resample di righe, seed e _ci di topmix_margins.py).

WALK-FORWARD: nessuna riscrittura del motore. La testa 1X2 e' la stessa di
diagnose_elo_ensemble.run_models e la testa Totali pura e' la stessa di
diagnose_form_totali.run_models (modello B): questo script ne importa i moduli,
estende l'emissione alle stagioni di train e aggiunge le somme sulle celle della
matrice; la conformita' e' VERIFICATA bit-a-bit in cross_check() e l'invarianza
dello stato all'estensione delle stagioni emesse in check_state_invariance().

NON tocca SoccerMath/app.py, config.py, models/ (sola lettura).
Output: audit/results/combo_1x2_totali_diagnosis.md
Uso:    python audit/diagnose_combo_1x2_totali.py
"""
from __future__ import annotations

import math
import os
import sys
from collections import OrderedDict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from scipy.stats import poisson                                   # noqa: E402
from backtest_experiment_all import LEAGUES, MARKET_VALUES, load_league  # noqa: E402
from config import LEAGUE_HOME_ADVANTAGE                           # noqa: E402
from topmix_margins import N_BOOT, SEED, _ci                       # noqa: E402
import diagnose_elo_ensemble as dee                                # noqa: E402
import diagnose_form_totali as dft                                 # noqa: E402
import diagnose_clv_pinnacle as CLV                                # noqa: E402

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "combo_1x2_totali_diagnosis.md")

TRAIN_SEASONS = ("2022/23", "2023/24")
SEASONS_EVAL = dee.SEASONS_EVAL                    # ("2024/25", "2025/26")
ALL_SEASONS = TRAIN_SEASONS + SEASONS_EVAL
SPLIT_OF_SEASON = {**{s: "train" for s in TRAIN_SEASONS},
                   SEASONS_EVAL[0]: "validation", SEASONS_EVAL[1]: "test"}
SPLITS = ("train", "validation", "test")
TRAIN_WARMUP = 60            # identico a grid_search_ensemble_weight.TRAIN_WARMUP
MAX_GOALS = 15               # supporto della matrice, identico a app._poisson_market
OVER_LINE = 2.5
ELO_ENSEMBLE_W = CLV.ELO_ENSEMBLE_W     # app.ELO_ENSEMBLE_W (oggi 0.25)
VERSIONS = ("a_grid_1x2", "b_grid_totali", "c_naive_blend", "c0_naive_puro")
VERSION_LABEL = {
    "a_grid_1x2": "(a) griglia congiunta lambda 1X2 (att/def + mercato)",
    "b_grid_totali": "(b) griglia congiunta lambda Totali (att0_pure/def0_pure)",
    "c_naive_blend": "(c) prodotto naive P(1) blendato x P(totale) testa Totali",
    "c0_naive_puro": "(c0) prodotto naive P(1) Poisson puro x P(totale) [controllo]",
}


# ---------------------------------------------------------------------------
# Definizioni delle combo
# ---------------------------------------------------------------------------
def _cell_masks(pick, total):
    """Maschera booleana MAX_GOALS x MAX_GOALS sulle celle (h,a) della combo."""
    idx = np.arange(MAX_GOALS)
    hh = idx[:, None]
    aa = idx[None, :]
    if pick == "1":
        pm = hh > aa
    elif pick == "X":
        pm = hh == aa
    elif pick == "2":
        pm = hh < aa
    else:
        raise ValueError(pick)
    tot = hh + aa
    tm = (tot > OVER_LINE) if total == "OVER" else (tot <= OVER_LINE)
    return pm & tm


COMBOS = (
    {"key": "1_over", "label": "1 + Over 2.5", "pick": "1", "total": "OVER",
     "role": "primaria (quella chiesta)",
     "note": "vittoria casa E >=3 gol totali: le due componenti condividono i "
             "lambda della stessa squadra forte in casa, correlazione attesa > 0"},
    {"key": "2_under", "label": "2 + Under 2.5", "pick": "2", "total": "UNDER",
     "role": "controllo",
     "note": "vittoria trasferta E <=2 gol totali: combo 'di partita chiusa', "
             "stesso tipo di assunzione di indipendenza nella direzione opposta"},
    {"key": "x_over", "label": "X + Over 2.5", "pick": "X", "total": "OVER",
     "role": "controllo (correlazione negativa)",
     "note": "pareggio E >=3 gol: qui l'indipendenza sbaglia di segno (1-1 e "
             "2-2 convivono male con un pari a reti inviolate), test robusto"},
)
MASKS = {c["key"]: _cell_masks(c["pick"], c["total"]) for c in COMBOS}


def observed(pick, total, fthg, ftag, ftr):
    """Esito reale binario della combo (1 se la combo si e' verificata)."""
    won = {"1": ftr == "H", "X": ftr == "D", "2": ftr == "A"}[pick]
    tot = fthg + ftag
    hit_total = (tot > OVER_LINE) if total == "OVER" else (tot <= OVER_LINE)
    return int(bool(won) and hit_total)


# ---------------------------------------------------------------------------
# Griglia Poisson congiunta: stessa costruzione di app._poisson_market
# ---------------------------------------------------------------------------
def grid(lh, la):
    """Matrice congiunta 15x15 di Poisson indipendenti, clip [exp(-6), exp(3)]
    in ingresso (identica a _poisson_market di app.py, che NON rinormalizza il
    troncamento a 15 reti: le marginali e le somme sulle celle stanno quindi
    sullo stesso supporto troncato)."""
    lh = dee.clip(lh)
    la = dee.clip(la)
    h_p = np.array([poisson.pmf(i, lh) for i in range(MAX_GOALS)])
    a_p = np.array([poisson.pmf(i, la) for i in range(MAX_GOALS)])
    return np.outer(h_p, a_p)


def marginali(mat):
    p1 = float(np.sum(np.tril(mat, -1)))
    pX = float(np.sum(np.diag(mat)))
    p2 = float(np.sum(np.triu(mat, 1)))
    u25 = float(sum(mat[i, j] for i in range(MAX_GOALS) for j in range(MAX_GOALS)
                   if i + j < OVER_LINE))
    return {"1": p1, "X": pX, "2": p2, "u25": u25}


def joint_prob(mat, mask):
    return float(mat[mask].sum())


def implied_rho(p_joint, p_pick, p_total):
    """Correlazione point-biserial tra i due eventi binari implicita nel modello."""
    den = math.sqrt(max(p_pick * (1 - p_pick) * p_total * (1 - p_total), 1e-12))
    return (p_joint - p_pick * p_total) / den


# ---------------------------------------------------------------------------
# Walk-forward: due teste di produzione + somme sulle celle della matrice
# ---------------------------------------------------------------------------
def run_combo_model(df, camp_key, xg_data, emit_seasons=ALL_SEASONS,
                    w=ELO_ENSEMBLE_W):
    """Passata cronologica singola. Identica a diagnose_elo_ensemble.run_models
    per i lambda della testa 1X2 e a diagnose_form_totali.run_models (modello B,
    SENZA forma) per i lambda della testa Totali; in piu' costruisce le due
    matrici congiunte e ne ricava le probabilita' di combo.

    Lo stato (TeamState, Elo, medie gol) e' aggiornato DOPO la previsione, per
    ogni riga: nessuna previsione vede se stessa o il futuro, per QUALSIASI
    insieme di stagioni emesse (verificato da check_state_invariance).
    Ritorna un DataFrame con una riga per partita emessa."""
    emit = set(ALL_SEASONS if emit_seasons is None else emit_seasons)
    home_adv = LEAGUE_HOME_ADVANTAGE.get(camp_key, 60.0)
    xg_att, xg_def = {}, {}
    if xg_data and len(xg_data) >= 10:
        vals = list(xg_data.values())
        lx = float(np.mean([v["xG_avg"] for v in vals]))
        lxa = float(np.mean([v["xGA_avg"] for v in vals]))
        if lx and lxa:
            for t, v in xg_data.items():
                xg_att[t] = v["xG_avg"] / lx
                xg_def[t] = v["xGA_avg"] / lxa

    state, elo = {}, {}
    tot_hg = tot_ag = tot_n = 0.0
    rows = []

    def get(t):
        if t not in state:
            state[t] = dee.TeamState()
        return state[t]

    for pos, (_, row) in enumerate(df.iterrows()):
        fthg, ftag = int(row.FTHG), int(row.FTAG)
        ftr = str(row.FTR).strip().upper()
        h, a = row.HomeClean, row.AwayClean
        sh, sa = get(h), get(a)
        avg_h = max(tot_hg / tot_n, 0.1) if tot_n else 0.1
        avg_a = max(tot_ag / tot_n, 0.1) if tot_n else 0.1
        r_h, r_a = elo.get(h, 1500.0), elo.get(a, 1500.0)

        if row.season in emit:
            def form_fac(ts):
                if len(ts.last5) < 3:
                    return 1.0, 1.0
                n = len(ts.last5)
                gf = sum(x[0] for x in ts.last5)
                ga = sum(x[1] for x in ts.last5)
                den = max((avg_h + avg_a) / 2.0, 0.5)
                return (max(0.85, min(1.15, (gf / n) / den)),
                        max(0.85, min(1.15, (ga / n) / den)))

            def prim(t, ts):
                pa = xg_att[t] if t in xg_att else (
                    (ts.hgf / ts.hgn) / avg_h if ts.hgn else 1.0)
                pdf = xg_def[t] if t in xg_def else (
                    (ts.hga / ts.hgn) / avg_a if ts.hgn else 1.0)
                return pa, pdf

            pa_h, pd_h = prim(h, sh)
            pa_a, pd_a = prim(a, sa)
            fa_h, fd_h = form_fac(sh)
            fa_a, fd_a = form_fac(sa)
            m_h = dee.market_factor(MARKET_VALUES.get(h, 50))
            m_a = dee.market_factor(MARKET_VALUES.get(a, 50))

            # --- testa 1X2 di produzione: NORM-SUM (identica a dee.run_models) ---
            lam_base_h = pa_h * fa_h * pd_a * fd_a * avg_h
            lam_base_a = pa_a * fa_a * pd_h * fd_h * avg_a
            lam_m_h = (pa_h * fa_h * m_h) * (pd_a * fd_a / m_a) * avg_h
            lam_m_a = (pa_a * fa_a * m_a) * (pd_h * fd_h / m_h) * avg_a
            S = lam_base_h + lam_base_a
            den = lam_m_h + lam_m_a
            lh = dee.clip(S * lam_m_h / den) if den > 0 else dee.clip(lam_base_h)
            la = dee.clip(S * lam_m_a / den) if den > 0 else dee.clip(lam_base_a)

            # --- testa Totali di produzione: lambda puri, senza forma ne' mercato
            #     (identica a dft.run_models, modello B) ---
            lp_h = dee.clip(pa_h * pd_a * avg_h)
            lp_a = dee.clip(pa_a * pd_h * avg_a)

            mat1 = grid(lh, la)                   # griglia 1X2 (con mercato)
            m1 = marginali(mat1)
            mat0 = grid(lp_h, lp_a)               # griglia Totali (pura)
            m0 = marginali(mat0)

            e1, eX, e2 = dee.elo_probs(r_h, r_a, home_adv)
            b1 = w * m1["1"] + (1.0 - w) * e1
            bX = w * m1["X"] + (1.0 - w) * eX
            b2 = w * m1["2"] + (1.0 - w) * e2
            p_tot_1x2 = 1.0 - m1["u25"]            # over della griglia 1X2
            p_tot_alta = 1.0 - m0["u25"]           # over della testa Totali

            rec = {"pos": pos, "date": row.Date, "season": row.season,
                   "league": camp_key, "home": h, "away": a,
                   "fthg": fthg, "ftag": ftag, "real_1x2":
                   {"H": "1", "D": "X", "A": "2"}.get(ftr, "X"),
                   "real_over": int(fthg + ftag > OVER_LINE),
                   "real_under": int(fthg + ftag <= OVER_LINE),
                   # lambda e marginali (per la sezione correlazione)
                   "lam1_h": lh, "lam1_a": la, "lam0_h": lp_h, "lam0_a": lp_a,
                   "p1_head1x2": m1["1"], "p1_headtot": m0["1"],
                   "p1_blend": b1, "p1_elo": e1,
                   "pO_head1x2": p_tot_1x2, "pO_headtot": p_tot_alta,
                   "lam_sum_1x2": lh + la, "lam_sum_tot": lp_h + lp_a}
            for c in COMBOS:
                mask = MASKS[c["key"]]
                p_pick_1 = m1[c["pick"]]
                p_pick_0 = m0[c["pick"]]
                p_tot = p_tot_alta if c["total"] == "OVER" else m0["u25"]
                p_tot_1 = p_tot_1x2 if c["total"] == "OVER" else m1["u25"]
                blended_pick = {"1": b1, "X": bX, "2": b2}[c["pick"]]
                rec[f"{c['key']}_y"] = observed(c["pick"], c["total"], fthg, ftag, ftr)
                rec[f"{c['key']}_a"] = joint_prob(mat1, mask)
                rec[f"{c['key']}_b"] = joint_prob(mat0, mask)
                rec[f"{c['key']}_c"] = blended_pick * p_tot
                rec[f"{c['key']}_c0"] = p_pick_1 * p_tot
                # prodotto delle marginali DELLA STESSA griglia: stesso identico
                # P(pick) e P(totale) usati dalla somma sulle celle, quindi il
                # distacco (griglia - prodotto) E' esattamente e soltanto il
                # termine di correlazione (rho posto a zero per costruzione)
                p_tot_0 = p_tot_alta if c["total"] == "OVER" else m0["u25"]
                rec[f"{c['key']}_ref1"] = p_pick_1 * p_tot_1
                rec[f"{c['key']}_ref0"] = p_pick_0 * p_tot_0
                # correlazione implicita nelle due griglie
                rec[f"{c['key']}_rho_a"] = implied_rho(rec[f"{c['key']}_a"],
                                                        p_pick_1, p_tot_1)
                rec[f"{c['key']}_rho_b"] = implied_rho(rec[f"{c['key']}_b"],
                                                        p_pick_0, p_tot)
            rows.append(rec)

        # --- aggiornamento stato DOPO la previsione (no-leakage) ---
        dr = r_h + home_adv - r_a
        e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
        s_h = 1.0 if ftr == "H" else (0.0 if ftr == "A" else 0.5)
        elo[h] = r_h + dee.ELO_K * (s_h - e_h)
        elo[a] = r_a + dee.ELO_K * ((1 - s_h) - (1 - e_h))
        tot_hg += fthg
        tot_ag += ftag
        tot_n += 1
        sh.observe_home(fthg, ftag)
        sa.observe_away(fthg, ftag)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Verifiche di conformita' del protocollo
# ---------------------------------------------------------------------------
def cross_check(df_mine, ck, df_dee, df_form):
    """Le marginali devono essere BIT-IDENTICHE alle due diagnosi di riferimento:
    1X2 -> diagnose_elo_ensemble.run_models, Totali -> diagnose_form_totali
    (modello B). E' la prova che qui non c'e' un terzo modello, ma lo STESSO
    walk-forward con in piu' le somme sulle celle della matrice.

    Ritorna i numeri della verifica (max scarto assoluto e n righe confrontate),
    riportati nel report; uno scarto != 0 ferma l'audit."""
    mine = df_mine[df_mine.season.isin(SEASONS_EVAL)].reset_index(drop=True)
    d1 = float(np.max(np.abs(mine["p1_head1x2"].to_numpy() - df_dee["p1"].to_numpy())))
    dO = float(np.max(np.abs(mine["pO_headtot"].to_numpy() - df_form["pure_po"].to_numpy())))
    ok_y1 = np.array_equal(mine["real_1x2"].map({"1": 0, "X": 1, "2": 2}).to_numpy(),
                           df_dee["y"].to_numpy())
    ok_yo = np.array_equal(mine["real_over"].to_numpy(), df_form["real_over"].to_numpy())
    if d1 != 0.0 or not ok_y1:
        raise SystemExit(f"CROSS-CHECK FALLITO {ck}: P(1) della testa 1X2 diverge da "
                         f"diagnose_elo_ensemble.run_models (max scarto {d1:.3e})")
    if dO != 0.0 or not ok_yo:
        raise SystemExit(f"CROSS-CHECK FALLITO {ck}: P(Over 2.5) della testa Totali "
                         f"diverge da diagnose_form_totali modello B (max scarto {dO:.3e})")
    return {"league": ck, "n": int(len(mine)), "max_abs_p1": d1, "max_abs_pO": dO,
            "outcomes_ok": bool(ok_y1 and ok_yo)}


def check_state_invariance(df_full, df_eval, ck):
    """Emettere anche le stagioni di train NON deve cambiare le predizioni di
    validation/test: lo stato evolve allo stesso modo perche' l'aggiornamento
    avviene dopo la previsione e non dipende da cosa viene emesso."""
    a = df_full[df_full.season.isin(SEASONS_EVAL)].reset_index(drop=True)
    cols = [f"{c['key']}_{s}" for c in COMBOS
            for s in ("a", "b", "c", "c0", "ref1", "ref0")] + \
           ["p1_blend", "p1_head1x2", "pO_headtot"]
    for col in cols:
        if not np.array_equal(a[col].to_numpy(), df_eval[col].to_numpy()):
            raise SystemExit(f"STATE-INVARIANCE FALLITA {ck} colonna {col}: "
                             "l'estensione alle stagioni di train ha alterato "
                             "le predizioni di validation/test (leakage)")


# ---------------------------------------------------------------------------
# Metriche
# ---------------------------------------------------------------------------
def brier_ll(p, y):
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=int)
    pc = np.clip(p, 1e-12, 1 - 1e-12)
    return (float(np.mean((y - p) ** 2)),
            float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc))))


def boot_delta_ci(B_a, B_b, n_boot=N_BOOT, seed=SEED):
    """IC percentile 2.5-97.5 del Delta appaiato mean(B_a - B_b) su resample di
    righe (stesse costanti e stessa convenzione di topmix_margins._ci)."""
    n = len(B_a)
    if n == 0:
        return [None, None]
    rng = np.random.default_rng(seed)
    d = np.asarray(B_a, dtype=float) - np.asarray(B_b, dtype=float)
    means = np.empty(n_boot)
    batch = 200                      # resample a blocchi: evita n_boot x n di indici
    done = 0
    while done < n_boot:
        k = min(batch, n_boot - done)
        idx = rng.integers(0, n, size=(k, n))
        means[done:done + k] = d[idx].mean(axis=1)
        done += k
    return _ci(list(means))


def sample_mask(d, split):
    if split == "train":
        return (d["season"].isin(TRAIN_SEASONS) & (d["pos"] >= TRAIN_WARMUP)).to_numpy()
    if split == "validation":
        return (d["season"] == SEASONS_EVAL[0]).to_numpy()
    if split == "test":
        return (d["season"] == SEASONS_EVAL[1]).to_numpy()
    raise ValueError(split)


def version_stats(sub, combo):
    """Brier/LogLoss/affidabilita' delle 4 versioni su un sottoinsieme, piu' gli
    IC bootstrap del Delta appaiato vs (c) e vs (c0)."""
    y = sub[f"{combo}_y"].to_numpy(dtype=float)
    out = OrderedDict()
    B = {}
    for v, col in zip(VERSIONS, ("a", "b", "c", "c0")):
        p = sub[f"{combo}_{col}"].to_numpy(dtype=float)
        B[v] = (p - y) ** 2
        b, ll = brier_ll(p, y)
        out[v] = {"brier": b, "logloss": ll, "mean_pred": float(p.mean()),
                  "freq_obs": float(y.mean()), "bias": float(p.mean() - y.mean())}
    for v in VERSIONS:
        out[v]["delta_c"] = out[v]["brier"] - out["c_naive_blend"]["brier"]
        out[v]["delta_c0"] = out[v]["brier"] - out["c0_naive_puro"]["brier"]
    ref = "c_naive_blend"
    for v, b in B.items():
        if v == ref:
            out[v]["ci_delta_c"] = [0.0, 0.0]
        else:
            out[v]["ci_delta_c"] = boot_delta_ci(b, B[ref])
    # riferimento: Brier del predittore costante (sempre la frequenza base del
    # campione). Serve a dare la scala dei delta: su combo con base rate ~0.2
    # un Brier di 0.16 vale poco se il costante sta a 0.157.
    f = float(y.mean())
    out["_ref"] = {"const": float(np.mean((y - f) ** 2))}
    for v in VERSIONS:
        out[v]["skill_vs_const"] = (100.0 * (1.0 - out[v]["brier"] / out["_ref"]["const"])
                                    if out["_ref"]["const"] > 0 else None)
    out["_n"] = len(y)
    out["_y"] = y
    return out


def reliability(sub, combo, col, n_bins=5):
    """Tabella di affidabilita' di una versione: quintili della propria previsione."""
    p = sub[f"{combo}_{col}"].to_numpy(dtype=float)
    y = sub[f"{combo}_y"].to_numpy(dtype=float)
    if len(p) < n_bins * 20:
        return []
    edges = np.quantile(p, np.linspace(0, 1, n_bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    idx = np.clip(np.searchsorted(edges[1:-1], p, side="right"), 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        m = idx == b
        if m.sum() == 0:
            continue
        rows.append({"n": int(m.sum()), "pred": float(p[m].mean()),
                     "obs": float(y[m].mean()), "bias": float(p[m].mean() - y[m].mean())})
    return rows


def k_factor_table(agg):
    """k stimato sul TRAIN (rapporto frequenza osservata / probabilita' media del
    prodotto naive) e applicato out-of-sample su validation e test.

    Ritorna (righe per il report, payload per la sezione Lettura)."""
    tr = agg[sample_mask(agg, "train")]
    rows, payload = [], {}
    for c in COMBOS:
        for col, label in (("c", "naive mostrata (P(1) con Elo)"),
                           ("c0", "naive pura (P(1) senza Elo)")):
            p_tr = tr[f"{c['key']}_{col}"].to_numpy(dtype=float)
            y_tr = tr[f"{c['key']}_y"].to_numpy(dtype=float)
            k = float(y_tr.mean() / p_tr.mean()) if p_tr.mean() > 0 else float("nan")
            cells = [c["label"], label, f"{k:.4f}"]
            per_split = {}
            for split in ("validation", "test"):
                sub = agg[sample_mask(agg, split)]
                p = sub[f"{c['key']}_{col}"].to_numpy(dtype=float)
                y = sub[f"{c['key']}_y"].to_numpy(dtype=float)
                pc = np.clip(k * p, 0.0, 1.0)
                b0 = float(np.mean((p - y) ** 2))
                b1 = float(np.mean((pc - y) ** 2))
                rel0 = float((p.mean() - y.mean()) / y.mean())
                rel1 = float((pc.mean() - y.mean()) / y.mean())
                ci = boot_delta_ci((pc - y) ** 2, (p - y) ** 2)
                cells += [f"{100 * rel0:+.1f}% → {100 * rel1:+.1f}%",
                          f"{_f(b0)} → {_f(b1)}",
                          f"{b1 - b0:+.4f} ({_fci(ci)})"]
                per_split[split] = {"k": k, "brier_base": b0, "brier_corr": b1,
                                    "delta": b1 - b0, "ci": ci,
                                    "bias_rel_base": rel0, "bias_rel_corr": rel1}
            payload[(c["key"], col)] = {"k": k, **per_split}
            rows.append(cells)
    return rows, payload


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def _f(x, dec=4):
    return "n/d" if x is None else f"{x:.{dec}f}"


def _fci(ci, dec=4):
    if ci is None or ci[0] is None:
        return "n/d"
    return f"[{ci[0]:.{dec}f}; {ci[1]:.{dec}f}]"


def verdict(delta, ci):
    if ci is None or ci[0] is None:
        return "n/d"
    if delta < 0 and ci[1] < 0:
        return "MIGLIORE (IC senza zero)"
    if delta > 0 and ci[0] > 0:
        return "PEGGIORE (IC senza zero)"
    return "entro l'IC: rumore"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    per_league, per_league_dee, per_league_form, checks = {}, {}, {}, []
    for prefix, ck in LEAGUES:
        print(f"==> {ck}: walk-forward due teste + griglie congiunte ...")
        df = load_league(prefix)
        xg = dee.load_xg(ck)
        d_full = run_combo_model(df, ck, xg, emit_seasons=ALL_SEASONS)
        d_eval = run_combo_model(df, ck, xg, emit_seasons=SEASONS_EVAL)
        per_league[ck] = d_full
        check_state_invariance(d_full, d_eval, ck)
        # conformita' ai due audit di riferimento (soli split di eval)
        per_league_dee[ck] = dee.run_models(df, ck, xg)
        per_league_form[ck] = dft.run_models(df, xg)
        checks.append(cross_check(d_full, ck, per_league_dee[ck], per_league_form[ck]))
    print("cross-check: marginali 1X2 e Totali bit-identiche a "
          "diagnose_elo_ensemble / diagnose_form_totali | state-invariance: OK")

    agg = pd.concat(per_league.values(), ignore_index=True)
    L = []
    ap = L.append
    ap("# Combo 1X2 + Totali: griglia congiunta vs prodotto naive (audit sola lettura)")
    ap("")
    ap(f"*Generato: {datetime.now(timezone.utc).isoformat(timespec='seconds')} — "
       "script `audit/diagnose_combo_1x2_totali.py`, nessuna modifica a "
       "SoccerMath/.* Brier = mean((p - y)^2) sull'indicatore binario della combo; "
       "piu' basso = meglio.*")
    ap("")
    ap(f"Walk-forward no-leakage, 5 leghe, TRAIN {TRAIN_SEASONS[0]}+{TRAIN_SEASONS[1]} "
       f"(le prime {TRAIN_WARMUP} partite/lega restano nello stato ma sono escluse dal "
       f"campione: cold start), VALIDATION {SEASONS_EVAL[0]} (conferma), TEST "
       f"{SEASONS_EVAL[1]} (sola lettura, mai usata per scegliere). Testa 1X2 = "
       "NORM-SUM di `diagnose_elo_ensemble.run_models` (xG snapshot + forma ult.5 + "
       "fattore mercato, somma normalizzata alla base con forma); testa Totali = "
       "lambda puri senza forma ne' mercato di `diagnose_form_totali` (modello B); "
       f"Elo sequenziale K={dee.ELO_K:.0f} e blend w={ELO_ENSEMBLE_W} "
       "(`app.ELO_ENSEMBLE_W`). Griglia congiunta = matrice 15x15 di `app._poisson_market` "
       "con somma sulle celle (h,a) della combo, supporto troncato e non rinormalizzato "
       "come in produzione. Conformita' verificata bit-a-bit (vedi sotto).")
    ap("")
    ap("Versioni a confronto (stessa partita, stesso stato):")
    ap("")
    for v in VERSIONS:
        ap(f"- **{VERSION_LABEL[v]}**")
    ap("")
    ap("La (c) e' esattamente cio' che si otterrebbe oggi moltiplicando i due numeri "
       "che il Top Mix mette in scheda; la (c0) e' lo stesso prodotto senza Elo, "
       "serve a separare 'manca la correlazione' da 'dentro c'e' anche l'Elo'.")
    ap("")
    ap("Attenzione a un particolare non casuale: (a) e (b) usano le marginali IMPLICITE "
       "della propria griglia (il P(1) di (a) non contiene l'Elo, e l'Over di (a) e' "
       "quello della testa 1X2 non quello mostrato in scheda), quindi il confronto "
       "raw (a) vs (c) mescola tre effetti: correlazione, scelta della testa per il "
       "totale, contributo dell'Elo. Per separarli sono disponibili due controlli: "
       "(c0) = prodotto delle marginali cosi' come le mostriamo oggi ma senza Elo, e "
       "il `naive stessa griglia` (ref) = prodotto delle marginali DELLA STESSA "
       "matrice usata per la somma sulle celle. Lì le marginali sono identiche per "
       "costruzione, quindi (griglia − ref) E' il termine di correlazione e niente "
       "altro: e' la cifra da leggere per rispondere alla domanda dell'audit.")
    ap("")

    # ---- conformita' del protocollo ----
    ap("## Conformita' del protocollo (verificata, non dichiarata)")
    ap("")
    ap("Le marginali di questo walk-forward sono state confrontate riga per riga "
       "con le due diagnosi da cui ereditano il modello, su validation+test:")
    ap("")
    ap("| Lega | n righe confrontate | max \|scarto\| P(1) vs diagnose_elo_ensemble | "
       "max \|scarto\| P(Over) vs diagnose_form_totali | esiti reali identici |")
    ap("|---|---:|---:|---:|---|")
    for ck_row in checks:
        ap(f"| {ck_row['league']} | {ck_row['n']} | {ck_row['max_abs_p1']:.1e} | "
           f"{ck_row['max_abs_pO']:.1e} | {'si' if ck_row['outcomes_ok'] else 'NO'} |")
    ap("")
    ap("Scarto zero = le tre colonne della testa 1X2 e la testa Totali di questo "
       "audit sono lo STESSO numero che producono gli audit di riferimento: qui ci "
       "sono solo in piu' le somme sulle celle della matrice. In piu', "
       "`check_state_invariance` verifica che emettere anche le stagioni di train "
       "non sposti di un bit le predizioni di validation/test (nessuna leakage "
       "dall'estensione del campione).")
    ap("")

    # ---- copertura ----
    ap("## Copertura campioni")
    ap("")
    ap("| Lega | Train (n) | Train escluse cold-start | Validation (n) | Test (n) |")
    ap("|---|---:|---:|---:|---:|")
    for ck, d in per_league.items():
        n_tr = int(sample_mask(d, "train").sum())
        n_all_tr = int(d["season"].isin(TRAIN_SEASONS).sum())
        ap(f"| {ck} | {n_tr} | {n_all_tr - n_tr} | "
           f"{int(sample_mask(d, 'validation').sum())} | "
           f"{int(sample_mask(d, 'test').sum())} |")
    tot = [int(sample_mask(agg, s).sum()) for s in SPLITS]
    ap(f"| **AGGREGATO** | {tot[0]} | {int(agg['season'].isin(TRAIN_SEASONS).sum()) - tot[0]} "
       f"| {tot[1]} | {tot[2]} |")
    ap("")

    # ---- tabelle per combo / split / versione ----
    stats = {}
    for c in COMBOS:
        for split in SPLITS:
            for scope, d in [("AGGREGATO", agg)] + [(ck, dd) for ck, dd in per_league.items()]:
                sub = d[sample_mask(d, split)]
                if len(sub) == 0:
                    continue
                stats[(c["key"], split, scope)] = version_stats(sub, c["key"])

    for c in COMBOS:
        ap(f"## Combo {c['label']} — {c['role']}")
        ap("")
        ap(c["note"] + ".")
        ap("")
        for split in SPLITS:
            tag = {"train": "TRAIN 2022/23+2023/24 (direzione, nessuna ritaratura)",
                   "validation": f"VALIDATION {SEASONS_EVAL[0]} (conferma)",
                   "test": f"TEST {SEASONS_EVAL[1]} (sola lettura)"}[split]
            st = stats.get((c["key"], split, "AGGREGATO"))
            if not st:
                continue
            ap(f"### {c['label']} — {tag} (aggregato 5 leghe, n={st['_n']})")
            ap("")
            ap("| Versione | Brier | LogLoss | Segnale vs costante | Pred. media | "
               "Frequ. osservata | Bias | Δ Brier vs (c) | IC 95% Δ | Δ vs (c0) |")
            ap("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
            for v in VERSIONS:
                s = st[v]
                ap(f"| {v} | {_f(s['brier'])} | {_f(s['logloss'])} | "
                   f"{_f(s['skill_vs_const'], 1)}% | {_f(s['mean_pred'])} | "
                   f"{_f(s['freq_obs'])} | {s['bias']:+.4f} | {s['delta_c']:+.4f} | "
                   f"{_fci(s['ci_delta_c'])} | {s['delta_c0']:+.4f} |")
            ap("")
            ap(f"Predittore costante (frequenza base del campione): Brier "
               f"{_f(st['_ref']['const'])}. `Segnale vs costante` = 100*(1 - "
               f"Brier/Brier costante): quanto la versione sa davvero distinguere "
               f"le combo vinte da quelle perse. Il riferimento usa la frequenza del "
               f"campione stesso (in-sample): e' una scala per leggere i delta, "
               f"non una strategia reperibile sul mercato.")
            ap("")
            ap("Lettura Δ Brier vs (c): " + "; ".join(
                f"{v} {verdict(st[v]['delta_c'], st[v]['ci_delta_c'])}"
                for v in VERSIONS if v != "c_naive_blend") + ".")
            ap("")
        ap(f"### {c['label']} — Brier per singola lega")
        ap("")
        ap("| Lega | Split | " + " | ".join(VERSIONS) + " |")
        ap("|---|---|" + "---:|" * len(VERSIONS))
        for ck in per_league:
            for split in SPLITS:
                st = stats.get((c["key"], split, ck))
                if not st:
                    continue
                ap(f"| {ck} | {split} | " +
                   " | ".join(_f(st[v]["brier"]) for v in VERSIONS) + " |")
        ap("")
        # per-lega: migliore versione (frequenza vittorie su split x lega)
        ap(f"### {c['label']} — quante volte ogni versione vince il Brier "
           f"(lega x split, {len(SPLITS) * len(per_league)} casi)")
        ap("")
        wins = {v: 0 for v in VERSIONS}
        ncase = 0
        for ck in per_league:
            for split in SPLITS:
                st = stats.get((c["key"], split, ck))
                if not st:
                    continue
                ncase += 1
                wins[min(VERSIONS, key=lambda v: st[v]["brier"])] += 1
        ap(" | ".join(f"{v}: {wins[v]}/{ncase}" for v in VERSIONS))
        ap("")

    # ---- sezione correlazione ----
    ap("## Quanto pesa la correlazione 1X2 x Totali in pratica")
    ap("")
    ap("Tre punti di vista sullo stesso fenomeno: (i) la correlazione che le "
       "griglie congiunte implicano e che il prodotto naive pone a zero, (ii) la "
       "correlazione EMPIRICA tra i due eventi realised, (iii) il danno in Brier "
       "di chi la ignora.")
    ap("")
    ap("| Combo | Split | ρ implicita griglia 1X2 | ρ implicita griglia Totali | "
       "ρ empirica (gol reali) | Δ Brier (a-c) | Δ Brier (b-c) |")
    ap("|---|---|---:|---:|---:|---:|---:|")
    corr_rows = {}
    for c in COMBOS:
        for split in SPLITS:
            sub = agg[sample_mask(agg, split)]
            if len(sub) == 0:
                continue
            ra = float(sub[f"{c['key']}_rho_a"].mean())
            rb = float(sub[f"{c['key']}_rho_b"].mean())
            re = float(np.corrcoef(sub["real_1x2"].eq(c["pick"]).to_numpy(dtype=float),
                                   sub["real_over"].to_numpy(dtype=float)
                                   if c["total"] == "OVER" else
                                   sub["real_under"].to_numpy(dtype=float))[0, 1])
            st = stats[(c["key"], split, "AGGREGATO")]
            corr_rows[(c["key"], split)] = (ra, rb, re)
            ap(f"| {c['label']} | {split} | {ra:+.4f} | {rb:+.4f} | {re:+.4f} | "
               f"{st['a_grid_1x2']['delta_c']:+.4f} | "
               f"{st['b_grid_totali']['delta_c']:+.4f} |")
    ap("")
    ap("`ρ implicita` = correlazione point-biserial tra i due eventi che emerge "
       "dalla matrice congiunta, mediata sulle partite: il prodotto naive ha "
       "ρ = 0 per definizione. `ρ empirica` = correlazione di Pearson tra i due "
       "indicatori osservati sullo stesso campione.")
    ap("")

    ap("### Il solo termine di correlazione (marginali identiche per costruzione)")
    ap("")
    ap("Stesso P(testa) e stesso P(totale), unica differenza: somma sulle celle "
       "della matrice congiunta oppure prodotto delle due marginali. La "
       "differenza di Brier qui sotto E' il peso della correlazione 1X2 x Totali, "
       "liberata da altri effetti; Δ negativo = la griglia congiunta batte il "
       "prodotto, cioe' ignorare la correlazione costa.")
    ap("")
    ap("| Combo | Split | Testa usata | Brier griglia | Brier prodotto stessa griglia | "
       "Δ (correlazione pura) | IC 95% Δ | Verdetto |")
    ap("|---|---|---|---:|---:|---:|---:|---|")
    corr_pure = {}
    for c in COMBOS:
        for split in SPLITS:
            sub = agg[sample_mask(agg, split)]
            if len(sub) == 0:
                continue
            y = sub[f"{c['key']}_y"].to_numpy(dtype=float)
            for head, gv, rv in (("1X2 (con mercato)", "a", "ref1"),
                                 ("Totali (pura)", "b", "ref0")):
                pg = sub[f"{c['key']}_{gv}"].to_numpy(dtype=float)
                pr = sub[f"{c['key']}_{rv}"].to_numpy(dtype=float)
                bg = float(np.mean((pg - y) ** 2))
                br = float(np.mean((pr - y) ** 2))
                ci = boot_delta_ci((pg - y) ** 2, (pr - y) ** 2)
                delta = bg - br
                corr_pure[(c["key"], split, gv)] = (bg, br, delta, ci)
                ap(f"| {c['label']} | {split} | {head} | {_f(bg)} | {_f(br)} | "
                   f"{delta:+.4f} | {_fci(ci)} | {verdict(delta, ci)} |")
    ap("")

    ap("### Fattore di correlazione k: stimato SUL TRAIN, letto fuori campione")
    ap("")
    ap("Se il difetto del prodotto naive e' il LIVELLO (il termine di correlazione "
       "omesso), un solo moltiplicatore per tipo di combo dovrebbe riassumerlo. k "
       "e' stimato SOLO sul TRAIN come `frequenza osservata / probabilita' media` "
       "e applicato a validation e test senza nessun ricalibramento "
       "(p_corr = clip(k*p, 0, 1)). E' il modo piu' economico di misurare quanto "
       "vale davvero la correlazione, senza toccare il motore.")
    ap("")
    ktab, kpayload = k_factor_table(agg)
    ap("| Combo | Base | k (train) | VAL: bias rel. base → corretto | VAL: Brier base → corretto | Δ (IC 95%) | TEST: bias rel. base → corretto | TEST: Brier base → corretto | Δ (IC 95%) |")
    ap("|---|---|---:|---|---|---|---|---|---|")
    for row in ktab:
        ap("| " + " | ".join(row) + " |")
    ap("")
    ap("`Δ` = Brier corretto − Brier base: negativo = il moltiplicatore miglio"
       "ra. L'ultima coppia di colonne e' sul TEST, dove nulla e' stato tarato.")
    ap("")

    ap("### Bias sistematico del prodotto naive (aggregato 5 leghe)")
    ap("")
    ap("Se il prodotto naive sottostima sistematicamente la frequenza reale, il "
       "suo errore NON e' solo rumore di correlazione ma anche livello: qui si "
       "separano le due cose.")
    ap("")
    ap("| Combo | Split | Versione | Pred. media | Frequ. osservata | Bias | Bias relativo |")
    ap("|---|---|---|---:|---:|---:|---:|")
    for c in COMBOS:
        for split in SPLITS:
            st = stats.get((c["key"], split, "AGGREGATO"))
            if not st:
                continue
            for v in VERSIONS:
                s = st[v]
                rel = (s["bias"] / s["freq_obs"]) if s["freq_obs"] else None
                ap(f"| {c['label']} | {split} | {v} | {_f(s['mean_pred'])} | "
                   f"{_f(s['freq_obs'])} | {s['bias']:+.4f} | "
                   f"{'n/d' if rel is None else f'{100 * rel:+.1f}%'} |")
    ap("")

    ap("### Affidabilita' per quintili (combo primaria, validation e test separate)")
    ap("")
    for split in ("validation", "test"):
        ap(f"**{split.upper()}** — quintili della previsione di ciascuna versione "
           "(bin diversi per versione per costruzione: confrontare il *bias*, non "
           "la riga).")
        ap("")
        ap("| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |")
        ap("|---|---|---:|---:|---:|---:|")
        sub = agg[sample_mask(agg, split)]
        for v, col in zip(VERSIONS, ("a", "b", "c", "c0")):
            for i, r in enumerate(reliability(sub, COMBOS[0]["key"], col), 1):
                ap(f"| {v} | Q{i} | {r['n']} | {_f(r['pred'])} | {_f(r['obs'])} | "
                   f"{r['bias']:+.4f} |")
        ap("")

    # ---- selezione e lettura ----
    ap("## Selezione (su TRAIN) e conferma (su VALIDATION); TEST sola lettura")
    ap("")
    prim = COMBOS[0]["key"]
    sel = min(VERSIONS, key=lambda v: stats[(prim, "train", "AGGREGATO")][v]["brier"])
    ap(f"- Combo primaria {COMBOS[0]['label']}: Brier minimo su TRAIN = **{sel}** "
       f"({_f(stats[(prim, 'train', 'AGGREGATO')][sel]['brier'])}); su VALIDATION "
       f"la stessa versione vale "
       f"{_f(stats[(prim, 'validation', 'AGGREGATO')][sel]['brier'])} e su TEST "
       f"{_f(stats[(prim, 'test', 'AGGREGATO')][sel]['brier'])}.")
    for split in SPLITS:
        st = stats[(prim, split, "AGGREGATO")]
        ranked = sorted(VERSIONS, key=lambda v: st[v]["brier"])
        ap(f"- {split}: ordine dal migliore al peggiore — " +
           " < ".join(f"{v} ({_f(st[v]['brier'])})" for v in ranked))
    ap("")

    ap("## Lettura")
    ap("")
    kc = kpayload[(prim, "c")]
    kc0 = kpayload[(prim, "c0")]

    # 1) la correlazione esiste, e il modello la vede grande quanto i dati
    rho_bits = []
    for c in COMBOS:
        ra, rb, re = corr_rows[(c["key"], "validation")]
        rho_bits.append(f"{c['label']}: modello {ra:+.3f} (griglia 1X2) / "
                        f"{rb:+.3f} (griglia Totali), dati {re:+.3f}")
    ap("1. **La dipendenza tra le due teste esiste ed e' quella che il modello "
       "disegna, non un artefatto** (validation, media sulle partite): " + "; ".join(rho_bits) +
       ". Il segno torna anche sul test e sul train; per X + Over 2.5 la "
       "correlazione e' forte e NEGATIVA (il pareggio vive di 0-0 e 1-1), per "
       "1 + Over 2.5 e' media e POSITIVA. Chi moltiplica le due probabilita' "
       "sta imponendo rho = 0 a un blocco di eventi che rho lo ha, e lo sbaglio "
       "ha direzione diversa a seconda della combo.")

    # 2) ma sul Brier della primaria non si vede
    d_a = [corr_pure[(prim, s, "a")] for s in SPLITS]
    d_b = [corr_pure[(prim, s, "b")] for s in SPLITS]
    ap("2. **Sul Brier della combo primaria, pero', il termine di correlazione non "
       "emerge**: griglia − prodotto a marginali identiche vale " +
       ", ".join(f"{d[2]:+.4f} ({s})" for s, d in zip(SPLITS, d_a)) +
       " sulla testa 1X2 e " +
       ", ".join(f"{d[2]:+.4f} ({s})" for s, d in zip(SPLITS, d_b)) +
       " sulla testa Totali. L'unica casella fuori dall'IC bootstrap e' "
       f"{d_b[0][2]:+.4f} (train, testa Totali) e va nella direzione opposta: "
       "li' la griglia congiunta risulta PEGGIORE del prodotto. Detto in modo "
       "sgradevole ma esatto: su questa "
       "combo la scelta tra (a), (b) e (c) NON e' distinguibile con il Brier, "
       "quindi il Brier da solo non autorizza nessuna delle tre.")

    # 3) dove si vede: il livello, cioe' il prezzo
    lvl, grid_wins, sign_flips = [], 0, 0
    for c in COMBOS:
        bs = [stats[(c["key"], sp, "AGGREGATO")] for sp in SPLITS]
        rel_c = [100 * st["c_naive_blend"]["bias"] / st["c_naive_blend"]["freq_obs"]
                 for st in bs]
        rel_a = [100 * st["a_grid_1x2"]["bias"] / st["a_grid_1x2"]["freq_obs"]
                 for st in bs]
        grid_wins += sum(1 for rc, ra in zip(rel_c, rel_a) if abs(ra) < abs(rc))
        sign_flips += int(any(rc * ra < 0 for rc, ra in zip(rel_c, rel_a)))
        lvl.append(f"{c['label']}: prodotto naive {rel_c[0]:+.1f}% (train) "
                   f"{rel_c[1]:+.1f}% (validation) {rel_c[2]:+.1f}% (test); "
                   f"griglia congiunta {rel_a[0]:+.1f}% {rel_a[1]:+.1f}% "
                   f"{rel_a[2]:+.1f}%")
    ap("3. **Dove la correlazione pesa davvero e' il LIVELLO, cioe' il prezzo**: " +
       "; ".join(lvl) + ". Il prodotto naive sbaglia sempre dello stesso segno nei "
       f"tre split (sottostima la 1 + Over di un sesto-quinto, sovrastima la "
       f"X + Over di meta'), mentre la griglia congiunta riduce l'errore assoluto "
       f"di livello in {grid_wins} casi su {len(COMBOS) * len(SPLITS)} (combo x "
       f"split) e ne inverte il segno su {sign_flips} combo su {len(COMBOS)}: incorpora la dipendenza, ma non e' "
       "un correttivo neutro — dove le marginali Poisson sono gia' troppo sicure, "
       "la somma sulle celle le rende ancora piu' estreme. Per una combo il numero "
       "che conta e' questa distanza tra probabilita' mostrata e frequenza reale, "
       "e li' la correlazione costa un ordine di grandezza piu' di quanto il Brier "
       "faccia vedere.")

    # 4) perche' il Brier premia chi sbaglia in modo opposto
    sub_va = agg[sample_mask(agg, "validation")]
    rel_a = reliability(sub_va, prim, "a")
    rel_c = reliability(sub_va, prim, "c")
    top_a = rel_a[-1] if rel_a else None
    top_c = rel_c[-1] if rel_c else None
    txt_a = (f"promette {top_a['pred']:.3f}, se ne vedono {top_a['obs']:.3f} "
             f"(bias {top_a['bias']:+.3f})" if top_a else "n/d")
    txt_c = (f"promette {top_c['pred']:.3f}, se ne vedono {top_c['obs']:.3f} "
             f"(bias {top_c['bias']:+.3f})" if top_c else "n/d")
    ap("4. **Perche' il prodotto naive vince la classifica Brier (e non perche' "
       "l'indipendenza sia vera)**: le marginali della testa 1X2 sono "
       "over-disperse in coda e la correlazione le amplifica. Nell'ultimo quintile "
       f"della (a) su validation si {txt_a}; nella (c), stessa coda di partite, si "
       f"{txt_c}. Moltiplicare due probabilita' minori di uno comprime la "
       "dispersione, la somma sulle celle della matrice la espande: sul Brier la "
       "compensazione accidentale del prodotto batte la joint coerente della "
       "griglia. E' un risultato giusto per la ragione sbagliata — leggerlo come "
       "'la correlazione non serve' sarebbe un errore di lettura, non un risultato "
       "dell'audit.")

    # 5) la prova del nove: k sul train
    def _delta_s(v):
        return (f"{v['delta']:+.4f} (IC {_fci(v['ci'])}, "
                + ("fuori zero" if (v['delta'] < 0 and v['ci'][1] < 0)
                   or (v['delta'] > 0 and v['ci'][0] > 0) else "dentro zero") + ")")
    ap("5. **Quanto vale il solo termine omesso**: k "
       f"stimato sul TRAIN vale {kc['k']:.4f} sul prodotto mostrato e "
       f"{kc0['k']:.4f} su quello puro. Applicato out-of-sample riporta "
       f"vicino allo zero l'errore di livello della primaria (bias relativo validation "
       f"{100 * kc['validation']['bias_rel_base']:+.1f}% → "
       f"{100 * kc['validation']['bias_rel_corr']:+.1f}%, test "
       f"{100 * kc['test']['bias_rel_base']:+.1f}% → "
       f"{100 * kc['test']['bias_rel_corr']:+.1f}%) MA il Brier della primaria "
       f"peggiora: Δ {_delta_s(kc['validation'])} su validation e "
       f"{_delta_s(kc['test'])} su test. Sulle due combo di controllo, invece, la "
       f"stessa correzione MIGLIORA il Brier in modo distinguibile: "
       f"{COMBOS[1]['label']} Δ {_delta_s(kpayload[(COMBOS[1]['key'], 'c')]['validation'])} e "
       f"{COMBOS[2]['label']} Δ {_delta_s(kpayload[(COMBOS[2]['key'], 'c')]['validation'])} su "
       "validation. k non e' unico: " +
       ", ".join(f"{c['label']} {kpayload[(c['key'], 'c')]['k']:.3f}" for c in COMBOS) +
       " — chi correggesse la correlazione con un fattore globale sbaglierebbe "
       "meta' delle combo per costruzione.")
    ap("")
    ap("   E' il punto piu' scomodo dell'audit e va letto senza scorciatoie: sulla "
       "combo primaria le due cose si tirano in direzioni opposte (livello giusto, "
       "Brier peggiore), perche' il prodotto naive compensava con il suo difetto "
       "l'over-dispersione delle marginali. Ne segue che **il Brier non e' il "
       "criterio giusto per scegliere come costruire una probabilita' di combo**: "
       "premia lo shrinkage sulle code e su eventi rari perdona chi sottostima in "
       "modo uniforme. Il criterio da usare, se un giorno le combo si esporranno, "
       "e' il bias di calibrazione (e la coda), con il Brier come secondo parere.")

    # 6) controllo sulle altre combo
    ctrl = []
    for c in COMBOS[1:]:
        d_va2 = corr_pure[(c["key"], "validation", "a")]
        ctrl.append(f"{c['label']}: Δ (griglia − prodotto, stesse marginali) "
                    f"{d_va2[2]:+.4f} su validation, IC {_fci(d_va2[3])} "
                    f"→ {verdict(d_va2[2], d_va2[3])}")
    sub_va2 = agg[sample_mask(agg, "validation")]
    c2 = COMBOS[1]["key"]
    mj = float(sub_va2[f"{c2}_a"].mean())
    mp_ = float(sub_va2[f"{c2}_ref1"].mean())
    mo = float(sub_va2[f"{c2}_y"].mean())
    ap("6. **Le combo di controllo**: " + " | ".join(ctrl) +
       f" — su 2 + Under 2.5 la griglia congiunta batte il prodotto in modo "
       "distinguibile anche a marginali identiche; su X + Over 2.5 e sulla primaria "
       "resta dentro il rumore. Il meccanismo che separa i casi sta nelle colonne "
       "Bias: la correzione di correlazione conviene quando migliora il livello "
       f"SENZA pagare in dispersione (2 + Under 2.5 su validation: joint {mj:.4f} "
       f"contro prodotto-stessa-griglia {mp_:.4f}, reale {mo:.4f}); non conviene quando recupera "
       "il livello ma allarga la coda oltre il vero (combo primaria, ultimo "
       f"quintile {top_a['pred']:.3f} promesso contro {top_a['obs']:.3f} "
       "osservato).")

    ap("")
    def _rel(ckey, ver, split):
        st = stats[(ckey, split, "AGGREGATO")]
        return 100.0 * st[ver]["bias"] / st[ver]["freq_obs"]
    prim_l, ctrl_l, xt_l = (COMBOS[0]["key"], COMBOS[1]["key"], COMBOS[2]["key"])
    ap("**In sintesi, per chi dovesse mai esporre una probabilita' di combo**: "
       "nessuna delle tre versioni e' giusta su tutte le combo, e va detto senza "
       f"scontorni. Sulla primaria la griglia congiunta riporta il livello verso la "
       f"verita' (bias relativo validation {_rel(prim_l, 'c_naive_blend', 'validation'):+.1f}% "
       f"del prodotto contro {_rel(prim_l, 'a_grid_1x2', 'validation'):+.1f}% della griglia) e "
       f"anche la 2 + Under 2.5 migliora ({_rel(ctrl_l, 'c_naive_blend', 'validation'):+.1f}% → "
       f"{_rel(ctrl_l, 'a_grid_1x2', 'validation'):+.1f}%), ma su X + Over 2.5 la griglia "
       f"sbaglia nella direzione opposta e con modulo maggiore "
       f"({_rel(xt_l, 'a_grid_1x2', 'validation'):+.1f}% della griglia contro "
       f"{_rel(xt_l, 'c_naive_blend', 'validation'):+.1f}% del prodotto): li' la "
       "frequenza vera sta IN MEZZO alle due stime, e la matrice indipendente "
       "esagera la dipendenza negativa tra pareggio e gol. Il quadro onesto e': "
       "il prodotto naive ha un "
       "errore di livello sistematico e direzionalmente coerente (sottostima le "
       "combo vittoria+over, sovrastima pareggio+over e trasferta+under); la "
       "griglia congiunta e' l'unica che incorpora la dipendenza, ma eredita "
       "l'over-dispersione delle marginali Poisson e su quel tipo di stima la "
       "amplifica. Se un giorno le combo entreranno in scheda, la scelta va fatta "
       "su bias di livello e comportamento della coda (con la k per tipo di combo "
       "come pavimento economico di confronto), non sulla classifica Brier, che "
       "qui premia la cancellazione accidentale. Nessuna modifica di produzione e' "
       "suggerita da questo script: qui si misura, non si decide.")
    ap("")

    ap("## Limiti dichiarati")
    ap("")
    ap("1. **Marginali da snapshot xG statico, non la fonte point-in-time di "
       "produzione.** La testa Totali live legge `att0_pure`/`def0_pure` dalla "
       "finestra point-in-time di `get_league_engine` (F_season/PT19_CAP con "
       "shrinkage); qui si usano i lambda puri da snapshot xG come in "
       "`diagnose_form_totali`, per restare bit-identici a un audit gia' "
       "validato. Cio' sposta il LIVELLO delle marginali, non il confronto "
       "griglia-vs-prodotto: (a)/(b)/(c0) usano le stesse identiche marginali e "
       "differiscono solo per il termine di correlazione.")
    ap("2. **Elo di replica** (K fisso, home advantage da config, niente boost "
       "xG), come in `diagnose_elo_ensemble`: la (c) usa il P(1) blendato con "
       "quell'Elo, non il rating live dell'app. Stesso limite di "
       "`clv_pinnacle_report.md` §Limiti.")
    ap("3. **Matrice troncata a 15 reti e non rinormalizzata** (comportamento di "
       "produzione): le probabilita' di combo somma su quel supporto, quindi "
       "risultano coerenti con le marginali mostrate ma leggermente sotto la "
       "loro somma teorica.")
    ap("4. **Cold start del TRAIN**: 2022/23 parte da DB vuoto; il warmup "
       f"esclude le prime {TRAIN_WARMUP} partite/lega dal campione ma lo stato "
       "conserva il rumore residuo (stessa convenzione del grid search).")
    ap("5. **Nessuna quota per le combo**: i database del repo non hanno quote "
       "1X2+Totale, quindi qui si misura solo la CALIBRAZIONE della probabilita' "
       "di combo, non la sua convenienza. Un Brier migliore su una combo non "
       "implica un ROI positivo: per quello servirebbe il prezzo della combo, "
       "che non c'e'.")
    ap("7. **Il Brier come unico criterio e' fuorviante su eventi rari**: per una "
       "combo con base rate 0.07-0.28 il termine E[p^2] domina la differenza tra "
       "due versioni, e un modello che sottostima in modo uniforme puo' risultare "
       "migliore anche se la sua frequenza media e' sbagliata del 17%. Per questo "
       "nel report le tabelle di bias/affidabilita' non sono un optional: senza, la "
       "classifica Brier porterebbe alla conclusione sbagliata ('la correlazione "
       "non serve').")
    ap("6. **Un solo punto di osservazione temporale**: snapshot 2026-09; le "
       "conclusioni vanno lette come direzione, non come coefficiente di "
       "correlazione da cablare (stessa lezione dell'audit rho Dixon-Coles).")
    ap("")

    ap("## Riferimenti incrociati")
    ap("")
    ap("- `audit/results/elo_ensemble_diagnosis.md` e "
       "`audit/results/ensemble_weight_grid_search.md`: da cui vengono la testa "
       "1X2 NORM-SUM e il peso d'insieme w;")
    ap("- `audit/results/form_totali_diagnosis.md`: da cui viene la testa Totali "
       "a lambda puri;")
    ap("- `audit/results/ensemble_scope_analisi_rapida.md`: mostra che l'1X2 "
       "blendato entra gia' nell'argmax a 7 mercati di `analisi_rapida_giornata`; "
       "questo audit aggiunge il pezzo mancante: cosa succede se 1X2 e Totali "
       "vengono combinati in un'unica scommessa.")
    ap("")
    return L, stats, agg


def run():
    L, stats, agg = main()
    md = "\n".join(L) + "\n"
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Scritto {OUT_PATH}")
    prim = COMBOS[0]["key"]
    for split in SPLITS:
        st = stats[(prim, split, "AGGREGATO")]
        print(f"{split:10s} Brier combo {COMBOS[0]['label']}: " + " | ".join(
            f"{v.split('_')[0]} {st[v]['brier']:.4f}" for v in VERSIONS))
    return stats


if __name__ == "__main__":
    run()
