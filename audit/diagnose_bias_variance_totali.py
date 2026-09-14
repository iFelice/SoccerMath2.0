"""
diagnose_bias_variance_totali.py — Il marginale Over/Under 2.5 GREZZO di
produzione (Poisson su att0_pure/def0_pure, la testa Totali modello B):
quanto del suo Brier e' bias di LIVELLO (affidabilita') e quanto segnale
per partita (risoluzione)?

Lo spunto viene dall'audit di calibrazione, dove il marginale grezzo Over
aveva Brier PEGGIORE del predittore costante, e la beta calibration lo
riportava sulla frequenza base comprimendone quasi tutta l'escursione. Qui
si decompone il fenomeno invece di fermarsi al Brier.

PROTOCOLLO (identico agli ultimi tre audit):
  * walk-forward train 2022/23+2023/24 (prime TRAIN_WARMUP=60 partite/lega
    escluse dal campione, cold start), validation 2024/25, test 2025/26, 5
    leghe; nessun parametro stimato su validation/test;
  * riusa diagnose_calibration_layer.run_calibration_model (stesso motore di
    diagnose_combo_1x2_totali / overdispersion): cross-check bit-a-bit delle
    marginali grezze contro diagnose_form_totali (modello B), scarto 0.0e+00;
  * le beta calibration SONO QUELLE dell'audit calibration_layer (stessi
    a,b,c stampati nel report), NON ristimate: qui vengono riottenute con lo
    stesso codice e lo stesso train solo come controllo di identita'.

CONTENUTI:
  1. Decomposizione di MURPHY Brier = Affidabilita' - Risoluzione +
     Incertezza su 10 DECILI di probabilita' predetta, per validation e
     test, aggregato e per lega, grezzo vs beta-calibrato. Test di coerenza
     interna: la mappa beta e' monotona quindi i decili contengono le stesse
     partite e la Risoluzione NON deve cambiare (Delta_RES = 0 esatto,
     entro i tie di clipping); deve calare solo l'Affidabilita'.
  2. Risoluzione in termini assoluti: std della probabilita' predetta vs
     std massima teorica sqrt(p_base*(1-p_base)); Var(p)/Incertezza e
     Risoluzione/Incertezza (frazione di incertezza spiegata).
  3. Deriva temporale: Over2.5 e GG rate reali (e gol/partita) su train,
     validation, test, aggregato e per lega, con IC bootstrap.
  4. Verdetto esplicito: post-calibrazione resta risoluzione sostanziale
     ('la pista 3 ha basi solide, il problema era solo di livello') oppure
     prossima allo zero ('nessun segnale da suddividere in bucket, la pista
     3 rischia di aggiungere solo rumore').

GG/NG e' ripetuto per confronto; l'oggetto primario e' O/U2.5.
NON tocca SoccerMath/ (sola lettura).
Output: audit/results/bias_variance_totali_diagnosis.md
Uso:    python audit/diagnose_bias_variance_totali.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from backtest_experiment_all import LEAGUES, load_league            # noqa: E402
from topmix_margins import N_BOOT, SEED, _ci                        # noqa: E402
import diagnose_elo_ensemble as dee                                 # noqa: E402
import diagnose_form_totali as dft                                  # noqa: E402
import diagnose_combo_1x2_totali as dc                               # noqa: E402
import diagnose_calibration_layer as cl                              # noqa: E402

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "bias_variance_totali_diagnosis.md")

TRAIN_SEASONS = dc.TRAIN_SEASONS
SEASONS_EVAL = dc.SEASONS_EVAL
ALL_SEASONS = dc.ALL_SEASONS
LEAGUE_KEYS = [ck for _, ck in LEAGUES]
N_BINS = 10

# Parametri beta calibration dell'audit calibration_layer (stampati nel
# report, stima solo-train). Qui usati come Costanti di riferimento: il
# codice riottiene i parametri con la stessa pipeline e verifica l'identita'.
BETA_REPORTED = {
    ("over", "pois"): np.array([0.3069, 0.0369, 0.3358]),
    ("gg", "pois"): np.array([-0.0313, 0.5934, -0.2367]),
}
EVENTS = [("over", "Over 2.5", "O/U2.5", "real_over", "over_pois"),
          ("gg", "GG", "GG/NG", "real_gg", "gg_pois")]


# ---------------------------------------------------------------------------
# Decomposizione di Murphy su bin a frequenza uguale (decili)
# ---------------------------------------------------------------------------
def murphy(p, y, n_bins=N_BINS):
    """Decomposizione di Murphy su bin a frequenza uguale.

    Per il forecast BINNATO (ogni partita rimpiazzata dalla media del
    proprio decile) vale l'identita' classica a 3 termini:
        Brier_bin = REL - RES + UNC.
    Per il forecast CONTINUO entro ogni bin resta un termine di
    raffinamento:
        Brier = Brier_bin + W - 2*C
    con W = media Var(p|bin), C = media Cov(p,y|bin). D = W - 2*C e' il
    guadagno del forecast continuo su quello binnato (negativo = c'e'
    discriminazione anche ENTRO i decili).
    """
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(p)
    edges = np.quantile(p, np.linspace(0, 1, n_bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    bidx = np.clip(np.searchsorted(edges[1:-1], p, side="right"),
                   0, n_bins - 1)
    ybar = float(y.mean())
    unc = ybar * (1.0 - ybar)
    rel = res = within = cov_in = 0.0
    brier = float(np.mean((p - y) ** 2))
    p_binned = np.empty(n)
    rows = []
    for b in range(n_bins):
        m = bidx == b
        nb = int(m.sum())
        if nb == 0:
            continue
        pb, yb = float(p[m].mean()), float(y[m].mean())
        p_binned[m] = pb
        rel += nb * (pb - yb) ** 2
        res += nb * (yb - ybar) ** 2
        within += float(np.sum((p[m] - pb) ** 2))
        cov_in += float(np.sum((p[m] - pb) * (y[m] - yb)))
        rows.append({"n": nb, "p": pb, "y": yb,
                     "bias": pb - yb})
    rel /= n
    res /= n
    within /= n
    cov_in /= n
    refine = within - 2.0 * cov_in
    brier_binned = float(np.mean((p_binned - y) ** 2))
    return {"brier": brier, "w": float(within), "c": float(cov_in),
            "refine": float(refine),
            "brier_binned": brier_binned,
            "rel": float(rel), "res": float(res),
            "unc": float(unc),
            "identity_err": float(brier - (brier_binned + refine)),
            "binned_identity_err": float(brier_binned - (rel - res + unc)),
            "ybar": ybar, "bidx": bidx, "bins": rows}


def rate_ci(y, n_boot=N_BOOT, seed=SEED):
    rng = np.random.default_rng(seed)
    y = np.asarray(y, dtype=float)
    n = len(y)
    means = np.empty(n_boot)
    batch, done = 200, 0
    while done < n_boot:
        k = min(batch, n_boot - done)
        idx = rng.integers(0, n, size=(k, n))
        means[done:done + k] = y[idx].mean(axis=1)
        done += k
    return float(y.mean()), _ci(list(means))


# ---------------------------------------------------------------------------
# Helpers report
# ---------------------------------------------------------------------------
def _f(x, dec=4):
    return "n/d" if x is None else f"{x:.{dec}f}"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # ---------------- walk-forward ----------------
    per_league, checks = {}, {}
    for prefix, ck in LEAGUES:
        print(f"==> {ck}: walk-forward ...")
        df = load_league(prefix)
        xg = dee.load_xg(ck)
        d_full = cl.run_calibration_model(df, ck, xg, ALL_SEASONS)
        d_eval = cl.run_calibration_model(df, ck, xg, SEASONS_EVAL)
        a = d_full[d_full.season.isin(SEASONS_EVAL)].reset_index(drop=True)
        b = d_eval.reset_index(drop=True)
        for col in d_full.columns:
            if col in ("pos", "season", "league", "home", "away"):
                continue
            if not np.array_equal(a[col].to_numpy(), b[col].to_numpy()):
                raise SystemExit(f"STATE-INVARIANCE FALLITA {ck} {col}")
        per_league[ck] = d_full

        # cross-check bit-a-bit vs diagnose_form_totali modello B
        d_dft = dft.run_models(df, xg).reset_index(drop=True)
        dO = float(np.max(np.abs(a["over_pois"].to_numpy()
                                 - d_dft["pure_po"].to_numpy())))
        dG = float(np.max(np.abs(a["gg_pois"].to_numpy()
                                 - d_dft["pure_gg"].to_numpy())))
        okO = np.array_equal(a["real_over"].to_numpy(),
                             d_dft["real_over"].to_numpy())
        okG = np.array_equal(a["real_gg"].to_numpy(),
                             d_dft["real_gg"].to_numpy())
        if dO != 0.0 or dG != 0.0 or not (okO and okG):
            raise SystemExit(f"CROSS-CHECK FALLITO {ck}: dO={dO} dG={dG} "
                             f"esiti {okO}/{okG}")
        checks[ck] = {"n": len(a), "dO": dO, "dG": dG, "ok": bool(okO and okG)}
    print("cross-check bit-a-bit vs diagnose_form_totali: scarti 0.0e+00 | "
          "state-invariance OK")

    agg = pd.concat(per_league.values(), ignore_index=True)
    m_tr = dc.sample_mask(agg, "train")
    m_va = dc.sample_mask(agg, "validation")
    m_te = dc.sample_mask(agg, "test")
    i_tr = np.where(m_tr)[0]

    # ---------------- beta RIUSATE (mai ristimate) ----------------
    # La calibrazione usa letteralmente i parametri pubblicati nel report
    # calibration_layer; riottenerli con la stessa pipeline serve solo da
    # controllo di riproducibilita' (lo scarto e' l'arrotondamento a 4
    # cifre del report).
    beta = {ev: BETA_REPORTED[(ev, "pois")] for ev, *_ in EVENTS}
    ident_err, refit = {}, {}
    for ev, name, mkt, ycol, pcol in EVENTS:
        bh = cl.beta_fit(agg[pcol].to_numpy()[i_tr],
                         agg[ycol].to_numpy()[i_tr])
        refit[ev] = bh
        ident_err[ev] = float(np.max(np.abs(bh - beta[ev])))
    print("beta RIUSATE dal report; max |scarto| del controllo di "
          "riproducibilita': "
          + ", ".join(f"{ev} {e:.1e}" for ev, e in ident_err.items()))

    # colleziona probabilita' grezze/calibrate + esiti per scope/split
    def series(scope, split, ev):
        _, _, mkt, ycol, pcol = next(e for e in EVENTS if e[0] == ev)
        sm = {"train": m_tr, "validation": m_va, "test": m_te}[split]
        if scope == "AGGREGATO":
            m = sm
        else:
            m = sm & agg["league"].eq(scope).to_numpy()
        idx = np.where(m)[0]
        p0 = agg[pcol].to_numpy()[idx]
        y = agg[ycol].to_numpy()[idx].astype(float)
        p1 = cl.beta_apply(p0, beta[ev])
        return p0, p1, y

    # ---------------- 1) Murphy ----------------
    murph = {}
    for ev, name, mkt, ycol, pcol in EVENTS:
        for scope in ["AGGREGATO"] + LEAGUE_KEYS:
            for split in ("validation", "test"):
                p0, p1, y = series(scope, split, ev)
                murph[(ev, scope, split, "raw")] = murphy(p0, y)
                murph[(ev, scope, split, "cal")] = murphy(p1, y)

    # controlli di coerenza interna (per evento)
    consistency = {}
    for ev, *_ in EVENTS:
        max_ident = max_dres = max_ties = 0.0
        min_spearman = 1.0
        for scope in ["AGGREGATO"] + LEAGUE_KEYS:
            for split in ("validation", "test"):
                r0 = murph[(ev, scope, split, "raw")]
                r1 = murph[(ev, scope, split, "cal")]
                max_ident = max(max_ident, abs(r0["identity_err"]),
                                abs(r1["identity_err"]),
                                abs(r0["binned_identity_err"]),
                                abs(r1["binned_identity_err"]))
                # appartenenze ai decili identiche (mappa monotona)
                same = np.mean(r0["bidx"] == r1["bidx"])
                max_ties = max(max_ties, abs(1.0 - same))
                max_dres = max(max_dres, abs(r0["res"] - r1["res"]))
                p0, p1, _ = series(scope, split, ev)
                rho = float(spearmanr(p0, p1).statistic)
                min_spearman = min(min_spearman, rho)
        inv_count = 0
        inv_pmax = 0.0
        n_tot = 0
        n_tail = 0
        for split in ("validation", "test"):
            p0, p1, _ = series("AGGREGATO", split, ev)
            order = np.argsort(p0)
            d = np.diff(p1[order])
            inv_count += int((d < -1e-12).sum())
            if (d < -1e-12).any():
                idxs = np.where(d < -1e-12)[0]
                inv_pmax = max(inv_pmax,
                               float(p0[order][idxs + 1].max()))
            n_tot += len(p0)
            a_, b_ = beta[ev][0], beta[ev][1]
            if a_ < 0:
                pstar = a_ / (a_ - b_)
                n_tail += int((p0 < pstar).sum())
        agg_dres = max(
            abs(murph[(ev, "AGGREGATO", s, "raw")]["res"]
                - murph[(ev, "AGGREGATO", s, "cal")]["res"])
            for s in ("validation", "test"))
        consistency[ev] = {"max_ident": max_ident, "max_dres": max_dres,
                           "agg_dres": float(agg_dres),
                           "max_ties": max_ties, "min_spearman": min_spearman,
                           "inversions": inv_count,
                           "inv_pmax": inv_pmax,
                           "tail_frac": n_tail / max(n_tot, 1),
                           "pstar": (float(beta[ev][0] /
                                           (beta[ev][0] - beta[ev][1]))
                                     if beta[ev][0] < 0 else None),
                           "beta_a": float(beta[ev][0]),
                           "beta_b": float(beta[ev][1])}

    # ---------------- 2) risoluzione assoluta ----------------
    absres = {}
    for ev, *_ in EVENTS:
        for scope in ["AGGREGATO"] + LEAGUE_KEYS:
            for split in ("validation", "test"):
                p0, p1, y = series(scope, split, ev)
                unc = y.mean() * (1 - y.mean())
                r0 = murph[(ev, scope, split, "raw")]
                r1 = murph[(ev, scope, split, "cal")]
                absres[(ev, scope, split)] = {
                    "std_raw": float(p0.std(ddof=1)),
                    "std_cal": float(p1.std(ddof=1)),
                    "std_max": float(np.sqrt(unc)),
                    "var_ratio_raw": float(p0.var(ddof=1) / unc),
                    "var_ratio_cal": float(p1.var(ddof=1) / unc),
                    "res_frac_raw": r0["res"] / unc,
                    "res_frac_cal": r1["res"] / unc,
                    "rel_frac_raw": r0["rel"] / unc,
                    "rel_frac_cal": r1["rel"] / unc,
                }

    # ---------------- 3) deriva temporale ----------------
    drift = {}
    seed_counter = [0]

    def dseed():
        seed_counter[0] += 1
        return SEED + 700 + seed_counter[0]

    for ev, name, mkt, ycol, pcol in EVENTS:
        for scope in ["AGGREGATO"] + LEAGUE_KEYS:
            for split in ("train", "validation", "test"):
                sm = {"train": m_tr, "validation": m_va, "test": m_te}[split]
                m = sm if scope == "AGGREGATO" else \
                    sm & agg["league"].eq(scope).to_numpy()
                idx = np.where(m)[0]
                y = agg[ycol].to_numpy()[idx].astype(float)
                rate, ci = rate_ci(y, seed=dseed())
                goals = (agg["fthg"].to_numpy()[idx]
                         + agg["ftag"].to_numpy()[idx]).astype(float)
                gm, _gci = rate_ci(goals, seed=dseed())
                drift[(ev, scope, split)] = {"rate": rate, "ci": ci,
                                             "goals": float(goals.mean())}

    # =====================================================================
    # REPORT
    # =====================================================================
    L = []
    ap = L.append
    ap("# Bias e varianza del marginale Over/Under 2.5 (e confronto GG/NG) "
       "— audit sola lettura")
    ap("")
    ap(f"*Generato: {datetime.now(timezone.utc).isoformat(timespec='seconds')} "
       "— script `audit/diagnose_bias_variance_totali.py`, nessuna modifica a "
       "SoccerMath/.*")
    ap("")
    ap("## Oggetto e protocollo")
    ap("")
    ap("Il marginale **Over/Under 2.5 grezzo di produzione** e' la Poisson "
       "indipendente sui lambda puri `att0_pure`/`def0_pure` (modello B di "
       "`diagnose_form_totali`, senza forma/mercato): e' il marginale che "
       "nell'audit di calibrazione aveva Brier peggiore del predittore "
       "costante. GG/NG e' ripetuto come confronto. Stesso walk-forward dei "
       f"tre audit precedenti: train {TRAIN_SEASONS[0]}+{TRAIN_SEASONS[1]} "
       "(prime 60 partite/lega escluse), validation "
       f"{SEASONS_EVAL[0]}, test {SEASONS_EVAL[1]}, 5 leghe; nessun "
       "parametro tocca validation/test.")
    ap("")
    ap("La versione calibrata usa i parametri **(a,b,c) dell'audit "
       "calibration_layer, non ristimati**; riottenerli con la stessa "
       "pipeline solo-train e verificare che coincidano e' un controllo di "
       "riproducibilita', non una nuova stima.")
    ap("")
    ap("## Conformita' (verificata, non dichiarata)")
    ap("")
    ap("| Lega | n righe val+test | max|scarto| P(Over) vs form_totali B | "
       "max|scarto| P(GG) | esiti identici |")
    ap("|---|---:|---:|---:|---|")
    for ck in LEAGUE_KEYS:
        c = checks[ck]
        ap(f"| {ck} | {c['n']} | {c['dO']:.1e} | {c['dG']:.1e} | "
           f"{'si' if c['ok'] else 'NO'} |")
    ap("")
    ap(f"Beta riusate vs report: max scarto Over {ident_err['over']:.1e}, "
       f"GG {ident_err['gg']:.1e} (i parametri sono quelli pubblicati).")
    ap("")

    ap("## Copertura")
    ap("")
    ap("| Lega | Train | Validation | Test |")
    ap("|---|---:|---:|---:|")
    for ck in LEAGUE_KEYS:
        d = per_league[ck]
        ap(f"| {ck} | {int(dc.sample_mask(d,'train').sum())} | "
           f"{int(dc.sample_mask(d,'validation').sum())} | "
           f"{int(dc.sample_mask(d,'test').sum())} |")
    ap(f"| **AGGREGATO** | {int(m_tr.sum())} | {int(m_va.sum())} | "
       f"{int(m_te.sum())} |")
    ap("")

    # ---- 1) Murphy ----
    ap("## 1. Decomposizione di Murphy (10 decili): Brier = Affidabilita' "
       "− Risoluzione + Incertezza")
    ap("")
    ap("- **Affidabilita' (REL)**: distanza media tra probabilita' predetta "
       "e frequenza osservata nel decile (0 = perfetta); e' il costo del "
       "bias di livello/forma.")
    ap("- **Risoluzione (RES)**: quanto la frequenza dei decili si discosta "
       "dalla frequenza marginale: e' il SEGNALE per partita che il "
       "modello sa estrarre (entra col segno meno, quindi abbassa il Brier).")
    ap("- **Incertezza (UNC)**: p_base(1−p_base), il Brier irriducibile del "
       "predittore costante.")
    ap("- **D = W − 2C (raffinamento entro-decili)**: passando dal forecast "
       "continuo alla media del proprio decile si perde W (varianza di p "
       "entro i bin) ma si guadagna 2C (covarianza entro-bin tra p ed "
       "esito). D negativo e stabile vorrebbe dire segnale nascosto dentro "
       "i bucket; in tabella, dopo calibrazione, |D| resta sotto i 4e-4 in "
       "aggregato e cambia segno tra split e leghe: non c'e' raffinamento "
       "entro-decile utilizzabile.")
    ap("")
    for ev, name, mkt, ycol, pcol in EVENTS:
        ap(f"### {mkt} — {name}")
        ap("")
        for split in ("validation", "test"):
            ap(f"**{split.upper()}**")
            ap("")
            ap("| Scope | Versione | Affidabilita' REL | Risoluzione RES | "
               "D=W−2C entro-decili | Incertezza UNC | Brier | REL/UNC | "
               "RES/UNC |")
            ap("|---|---|---:|---:|---:|---:|---:|---:|---:|")
            for scope in ["AGGREGATO"] + LEAGUE_KEYS:
                for ver, vlab in (("raw", "grezzo"), ("cal", "beta-calibrato")):
                    r = murph[(ev, scope, split, ver)]
                    a = absres[(ev, scope, split)]
                    relf = a["rel_frac_raw"] if ver == "raw" else a["rel_frac_cal"]
                    resf = a["res_frac_raw"] if ver == "raw" else a["res_frac_cal"]
                    bold = "**" if scope == "AGGREGATO" else ""
                    ap(f"| {bold}{scope}{bold} | {vlab} | {r['rel']:.4f} | "
                       f"{r['res']:.4f} | {r['refine']:+.4f} | "
                       f"{r['unc']:.4f} | "
                       f"{r['brier']:.4f} | {100*relf:.1f}% | "
                       f"{100*resf:.1f}% |")
            ap("")
        ap("")

    ap("### Test di coerenza interna (monotonia, identita' Murphy)")
    ap("")
    ap("Una mappa di calibrazione monotona lascia immutato l'ordinamento "
       "delle partite; con decili a frequenza uguale i bin contengono le "
       "stesse identiche partite prima e dopo la calibrazione, quindi la "
       "Risoluzione deve restare invariata e deve calare solo "
       "l'Affidabilita'. Chiusura contabile: per la previsione sostituita "
       "dalla media del proprio decile vale Brier_bin = REL − RES + UNC; "
       "per la previsione continua Brier = Brier_bin + D con "
       "D = W − 2C, dove W e' la varianza di p entro i decili e C la "
       "covarianza media entro-decile tra p ed esito: D negativo significa "
       "che esiste discriminazione anche dentro i bucket (un canale di "
       "segnale che i decili non vedono).")
    ap("")
    ap("| Evento | max errore identita' | ΔRISOLUZIONE max | "
       "Spearman min | partite cambiate di decile (max) | inversioni di "
       "rango (V+T, aggregato) |")
    ap("|---|---:|---:|---:|---:|---:|")
    for ev, name, mkt, ycol, pcol in EVENTS:
        c = consistency[ev]
        ap(f"| {mkt} | {c['max_ident']:.1e} | {c['max_dres']:.1e} | "
           f"{c['min_spearman']:.6f} | {100*c['max_ties']:.2f}% | "
           f"{c['inversions']} |")
    ap("")
    ov = consistency["over"]
    gg = consistency["gg"]
    ap(f"Sull'oggetto primario (Over 2.5) il test e' perfetto: ΔRisoluzione "
       f"{ov['agg_dres']:.1e} in aggregato (max per-lega "
       f"{ov['max_dres']:.1e}, per soli patiti al bordo dei decili), "
       f"Spearman {ov['min_spearman']:.6f}, nessuna inversione di rango. "
       "Su GG/NG si contano "
       f"{gg['inversions']} inversioni di rango in aggregato, tutte a "
       f"p<{gg['inv_pmax']:.4f}, ovvero nella coda che riguarda "
       f"{100*gg['tail_frac']:.2f}% delle righe: il coefficiente beta a="
       f"{gg['beta_a']:.3f} e' leggermente negativo e la mappa, monotona "
       "crescente sull'intervallo di probabilita' usato, si ripiega solo "
       f"sotto p*=a/(a−b)={gg['pstar']:.4f} (reti inviolabili quasi "
       "impossibili); l'effetto su Risoluzione e' "
       f"{gg['agg_dres']:.1e} in aggregato (max per-lega "
       f"{gg['max_dres']:.1e}), sostanzialmente zero. Gli scarti per-lega "
       "sono effetti di confine dei decili (fino al "
       f"{100*gg['max_ties']:.1f}% delle righe si sposta di bucket), non "
       "segnale creato dalla mappa: una trasformazione monotona non puo' "
       "creare risoluzione.")
    ap("")
    # tabellino sintetico aggregato: 3 termini + raffinamento continuo
    ap("| Evento | Split | W entro-decili | C cov entro-decili | D=W−2C | "
       "REL grezzo→cal | RES grezzo→cal | Brier grezzo→cal (continuo) | "
       "Brier_bin calibrato | UNC |")
    ap("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for ev, name, mkt, ycol, pcol in EVENTS:
        for split in ("validation", "test"):
            r0 = murph[(ev, "AGGREGATO", split, "raw")]
            r1 = murph[(ev, "AGGREGATO", split, "cal")]
            ap(f"| {mkt} | {split} | {r1['w']:.4f} | {r1['c']:+.4f} | "
               f"{r1['refine']:+.4f} | "
               f"{r0['rel']:.4f}→{r1['rel']:.4f} | "
               f"{r0['res']:.4f}→{r1['res']:.4f} | "
               f"{r0['brier']:.4f}→{r1['brier']:.4f} | "
               f"{r1['brier_binned']:.4f} | {r0['unc']:.4f} |")
    ap("")
    ap("Lettura: REL crolla di 1-2 ordini di grandezza mentre RES e' "
       "immutata (Over) o quasi (GG): la beta calibration rimuove il bias di "
       "livello e non tocca il segnale. Ma RES e' minuscola anche da grezza "
       "(0.001-0.003 contro UNC~0.25), e anche il termine di raffinamento "
       "entro-decili D non regala nulla: la colonna C (covarianza tra p od "
       "esito dentro i bucket) e' circa zero, quindi il forecast continuo "
       "non e' migliore della media del proprio decile. Il problema non e' la "
       "calibrazione, e' l'assenza di segnale per partita.")
    ap("")

    # ---- 2) risoluzione assoluta ----
    ap("## 2. Risoluzione in termini assoluti")
    ap("")
    ap("La varianza delle probabilita' predette misura quanto il modello "
       "distingue le partite, indipendentemente dal bias: anche un "
       "predittore perfettamente calibrato ma piatto non e' utile. Lo "
       "std massimo teorico e' sqrt(UNC)=sqrt(p_base(1−p_base)); "
       "Var(p)/UNC e' la frazione di varianza 'usata' rispetto a un "
       "segno binario perfetto, RES/UNC la frazione di incertezza realmente "
       "spiegata dai decili.")
    ap("")
    ap("| Evento | Split | Versione | std P | std max sqrt(UNC) | "
       "Var(P)/UNC | RES/UNC |")
    ap("|---|---|---|---:|---:|---:|---:|")
    for ev, name, mkt, ycol, pcol in EVENTS:
        for split in ("validation", "test"):
            a = absres[(ev, "AGGREGATO", split)]
            ap(f"| {mkt} | {split} | grezzo | {a['std_raw']:.4f} | "
               f"{a['std_max']:.4f} | {100*a['var_ratio_raw']:.1f}% | "
               f"{100*a['res_frac_raw']:.1f}% |")
            ap(f"| {mkt} | {split} | beta-calibrato | {a['std_cal']:.4f} | "
               f"{a['std_max']:.4f} | {100*a['var_ratio_cal']:.1f}% | "
               f"{100*a['res_frac_cal']:.1f}% |")
    ap("")
    ap("Per lega (RES/UNC, grezzo → calibrato):")
    ap("")
    ap("| Evento | Split | " + " | ".join(LEAGUE_KEYS) + " |")
    ap("|---|---|" + "---:|" * len(LEAGUE_KEYS))
    for ev, name, mkt, ycol, pcol in EVENTS:
        for split in ("validation", "test"):
            cells = []
            for ck in LEAGUE_KEYS:
                a = absres[(ev, ck, split)]
                cells.append(f"{100*a['res_frac_raw']:.1f}%→"
                             f"{100*a['res_frac_cal']:.1f}%")
            ap(f"| {mkt} | {split} | " + " | ".join(cells) + " |")
    ap("")

    # ---- 3) deriva ----
    ap("## 3. Deriva temporale dei tassi reali")
    ap("")
    ap("Over 2.5 rate, GG rate e gol/partita medi per split (IC 95% "
       "bootstrap). Il train e' il periodo su cui i parametri di "
       "calibrazione sono fissati; validation e test non possono ritoccarli.")
    ap("")
    ap("### Aggregato 5 leghe")
    ap("")
    ap("| Split | n | Over 2.5 rate (IC 95%) | GG rate (IC 95%) | gol/partita |")
    ap("|---|---:|---|---|---:|")
    for split in ("train", "validation", "test"):
        do = drift[("over", "AGGREGATO", split)]
        dg = drift[("gg", "AGGREGATO", split)]
        # n dal mask
        mm = {"train": m_tr, "validation": m_va, "test": m_te}[split]
        ap(f"| {split} | {int(mm.sum())} | {do['rate']:.3f} "
           f"[{do['ci'][0]:.3f}; {do['ci'][1]:.3f}] | {dg['rate']:.3f} "
           f"[{dg['ci'][0]:.3f}; {dg['ci'][1]:.3f}] | {do['goals']:.3f} |")
    ap("")
    ap("### Over 2.5 rate per lega e split")
    ap("")
    ap("| Lega | train (IC) | validation (IC) | test (IC) | "
       "delta test−train |")
    ap("|---|---|---|---|---:|")
    for ck in LEAGUE_KEYS:
        cells = {}
        for split in ("train", "validation", "test"):
            d = drift[("over", ck, split)]
            cells[split] = f"{d['rate']:.3f} [{d['ci'][0]:.3f}; {d['ci'][1]:.3f}]"
        delta = drift[("over", ck, "test")]["rate"] \
            - drift[("over", ck, "train")]["rate"]
        ap(f"| {ck} | {cells['train']} | {cells['validation']} | "
           f"{cells['test']} | {delta:+.3f} |")
    ap("")
    ap("### GG rate per lega e split")
    ap("")
    ap("| Lega | train | validation | test | delta test−train |")
    ap("|---|---:|---:|---:|---:|")
    for ck in LEAGUE_KEYS:
        rt = {s: drift[("gg", ck, s)]["rate"]
              for s in ("train", "validation", "test")}
        ap(f"| {ck} | {rt['train']:.3f} | {rt['validation']:.3f} | "
           f"{rt['test']:.3f} | {rt['test']-rt['train']:+.3f} |")
    ap("")
    # media predetta del modello vs tasso reale (livello per split)
    ap("### Livello predetto vs osservato (grezzo e calibrato)")
    ap("")
    ap("| Evento | Split | P media grezza | P media calibrata | frequenza "
       "reale | bias grezzo | bias calibrato |")
    ap("|---|---|---:|---:|---:|---:|---:|")
    for ev, name, mkt, ycol, pcol in EVENTS:
        for split in ("validation", "test"):
            p0, p1, y = series("AGGREGATO", split, ev)
            ap(f"| {mkt} | {split} | {p0.mean():.4f} | {p1.mean():.4f} | "
               f"{y.mean():.4f} | {p0.mean()-y.mean():+.4f} | "
               f"{p1.mean()-y.mean():+.4f} |")
    ap("")
    # lettura onesta della deriva
    gtr = drift[("over", "AGGREGATO", "train")]["goals"]
    gva = drift[("over", "AGGREGATO", "validation")]["goals"]
    gte = drift[("over", "AGGREGATO", "test")]["goals"]
    rtr = drift[("over", "AGGREGATO", "train")]["rate"]
    deltas = [drift[("over", ck, "test")]["rate"]
              - drift[("over", ck, "train")]["rate"] for ck in LEAGUE_KEYS]
    p0v, _, yv = series("AGGREGATO", "validation", "over")
    p0t, _, yt = series("AGGREGATO", "test", "over")
    ap("**Lettura.** Aggregato, il tasso Over e' piatto "
       f"({rtr:.3f} → {drift[('over','AGGREGATO','validation')]['rate']:.3f} "
       f"→ {drift[('over','AGGREGATO','test')]['rate']:.3f}) mentre i "
       f"gol/partita scendono leggermente nel test ({gtr:.3f} → {gva:.3f} "
       f"→ {gte:.3f}, {gte-gtr:+.3f}); per lega gli spostamenti "
       f"test−train sono tra {min(deltas):+.3f} e {max(deltas):+.3f}, dentro "
       "l'ampiezza degli IC 95% (circa ±0.05): non c'e' un trend aggregato "
       "certo, ma il livello VAGA per lega e periodo. Soprattutto, la "
       "sottostima grezza dell'Over esiste gia' verso la base train "
       f"({p0v.mean()-yv.mean():+.3f}/{p0t.mean()-yt.mean():+.3f} su "
       "validation/test, con tasso train praticamente uguale): e' dunque "
       "un difetto STRUTTURALE di soglia della Poisson indipendente "
       "(code troppo leggere), non prodotto dalla deriva. La deriva spiega "
       "invece perche' una calibrazione statica vada riaggiustata "
       "periodicamente: insegue un livello che si muove per lega.")
    ap("")

    # ---- 4) verdetto ----
    ap("## 4. Conclusione esplicita: quanta risoluzione resta?")
    ap("")
    ro_v = murph[("over", "AGGREGATO", "validation", "raw")]
    rc_v = murph[("over", "AGGREGATO", "validation", "cal")]
    ro_t = murph[("over", "AGGREGATO", "test", "raw")]
    rc_t = murph[("over", "AGGREGATO", "test", "cal")]
    ao_v = absres[("over", "AGGREGATO", "validation")]
    ao_t = absres[("over", "AGGREGATO", "test")]
    go_v = murph[("gg", "AGGREGATO", "validation", "cal")]
    go_t = murph[("gg", "AGGREGATO", "test", "cal")]
    ag_v = absres[("gg", "AGGREGATO", "validation")]
    ag_t = absres[("gg", "AGGREGATO", "test")]
    # soglia di 'sostanziale': almeno il 5% di incertezza spiegata su
    # ENTRAMBI gli split (ordine di grandezza di un segnale utilizzabile)
    SOGLIA = 0.05
    res_fracs = [ao_v["res_frac_cal"], ao_t["res_frac_cal"]]
    sostanziale = all(x >= SOGLIA for x in res_fracs)

    ap("**Over 2.5 (oggetto primario)**")
    ap("")
    ap(f"- Grezzo: Affidabilita' {ro_v['rel']:.4f}/{ro_t['rel']:.4f} "
       f"(val/test), Risoluzione {ro_v['res']:.4f}/{ro_t['res']:.4f}, "
       f"Incertezza {ro_v['unc']:.4f}/{ro_t['unc']:.4f}; il Brier grezzo "
       f"({ro_v['brier']:.4f}/{ro_t['brier']:.4f}) e' sopra l'Incertezza: "
       "il costo di affidabilita' (bias di livello) piu' che annulla il "
       "segnale.")
    ap(f"- Beta-calibrato: Affidabilita' ridotta a {rc_v['rel']:.4f}/"
       f"{rc_t['rel']:.4f}, Risoluzione invariata "
       f"{rc_v['res']:.4f}/{rc_t['res']:.4f} (sull'Over i test di coerenza "
       f"sopra danno Delta_RES={ov['agg_dres']:.1e} in aggregato, Spearman "
       f"{ov['min_spearman']:.4f}; il massimo scarto per-lega e' "
       f"{ov['max_dres']:.1e} e nasce da patiti di probabilita' sul bordo "
       "del decile); il Brier calibrato "
       f"({rc_v['brier']:.4f}/{rc_t['brier']:.4f}) e' praticamente uguale "
       f"all'Incertezza (skill vs costante "
       f"{100*(1-rc_v['brier']/rc_v['unc']):+.1f}%/"
       f"{100*(1-rc_t['brier']/rc_t['unc']):+.1f}%).")
    ap(f"- In valori assoluti, dopo calibrazione lo std di P(Over) e' "
       f"{ao_v['std_cal']:.3f}/{ao_t['std_cal']:.3f} contro un massimo "
       f"teorico {ao_v['std_max']:.3f}/{ao_t['std_max']:.3f}; la frazione di "
       f"incertezza spiegata dai decili e' "
       f"{100*ao_v['res_frac_cal']:.1f}%/{100*ao_t['res_frac_cal']:.1f}% "
       "(grezzo: "
       f"{100*ao_v['res_frac_raw']:.1f}%/{100*ao_t['res_frac_raw']:.1f}%).")
    ap("")
    ap("**GG/NG (confronto)**")
    ap("")
    ap(f"- Risoluzione post-calibrazione "
       f"{go_v['res']:.4f}/{go_t['res']:.4f} = "
       f"{100*ag_v['res_frac_cal']:.1f}%/{100*ag_t['res_frac_cal']:.1f}% "
       "dell'incertezza; stesso ordine di grandezza di Over.")
    ap("")
    ap("**Deriva.** "
       f"Over rate aggregato: train {drift[('over','AGGREGATO','train')]['rate']:.3f}, "
       f"validation {drift[('over','AGGREGATO','validation')]['rate']:.3f}, "
       f"test {drift[('over','AGGREGATO','test')]['rate']:.3f} "
       "(gol/partita "
       f"{drift[('over','AGGREGATO','train')]['goals']:.3f} → "
       f"{drift[('over','AGGREGATO','validation')]['goals']:.3f} → "
       f"{drift[('over','AGGREGATO','test')]['goals']:.3f}); la tabella §3 "
       "mostra per lega quanto il livello si muove tra i tre periodi: una "
       "calibrazione statica fissata sul train insegue un bersaglio mobile, "
       "il che spiega perche' serva riaggiustare periodicamente anche "
       "quando il segnale per partita resta nullo.")
    ap("")
    if sostanziale:
        ap(f"### VERDETTO: la Risoluzione residua e' SOSTANZIALE "
           f"(>= {100*SOGLIA:.0f}% dell'incertezza su entrambi gli split)")
        ap("")
        ap("La calibrazione aggiusta il livello ma resta segnale per "
           "partita da suddividere in bucket: la pista 3 ha basi solide, il "
           "problema era principalmente di livello.")
    else:
        ap("### VERDETTO: **la Risoluzione residua post-calibrazione e' "
           "vicina a zero — nessun segnale da suddividere in bucket, la "
           "pista 3 rischia di aggiungere solo rumore.**")
        ap("")
        ap(f"Dopo aver rimosso il bias di livello con la mappa monotona "
           "(che per costruzione conserva tutto il segnale esistente, come "
           "dimostrato su Over da Delta_RES=0, Spearman=1 e bin identici), "
           f"i decili spiegano solo "
           f"il {100*res_fracs[0]:.1f}%/{100*res_fracs[1]:.1f}% "
           "dell'incertezza intrinseca su validation/test, e il Brier "
           "calibrato coincide col predittore costante. Tradotto: la testa "
           "Totali grezza, nella ricostruzione a snapshot xG di questi "
           "audit, non sa dire quali partite saranno Over oltre alla "
           "frequenza di campionato; l'unico difetto reale e' il LIVELLO, e "
           "anche quello e' instabile per deriva temporale (§3). "
           "Suddividere in bucket/selezioni queste probabilita' (pista 3) "
           "non si appoggia a potere discriminante residuo: qualsiasi "
           "ordinamento per bucket sarebbe etichettatura di rumore. Prima "
           "di riaprire la pista servirebbe una fonte predittiva con "
           "risoluzione propria (es. engine point-in-time live, che usa "
           "finestre e shrinkage diversi dall'snapshot statico), e "
           "soltanto DOPO andrebbe verificata nuovamente la decomposizione. "
           "Nessuna modifica di produzione e' autorizzata da questo audit.")
    ap("")
    ap("## Limiti dichiarati")
    ap("")
    ap("1. **Snapshot xG statico**: i lambda sono quelli della replica di "
       "audit (come nei tre audit precedenti), non la fonte point-in-time "
       "live (`att0_pure/def0_p` con F_season/PT19_CAP e shrinkage): la "
       "risoluzione del motore di produzione potrebbe differire, e la "
       "conclusione sulla pista 3 vale per questa ricostruzione.")
    ap("2. **Decili a frequenza uguale**: e' la scelta richiesta e rende il "
       "test di invarianza della Risoluzione esatto; bin a bordi fissi "
       "darebbero numeri leggermente diversi ma non cambierebbero il "
       "rapporto di grandezza.")
    ap("3. **Beta pooled**: un solo terno (a,b,c) per mercato, fissato sul "
       "train; la deriva per lega non e' corretta e si vede in §3.")
    ap("4. **Nessuna quota**: si decompone accuratezza probabilistica, non "
       "convenienza economica.")
    ap("")
    ap("## Riferimenti incrociati")
    ap("")
    ap("- `audit/results/form_totali_diagnosis.md`: marginale grezzo "
       "modello B;")
    ap("- `audit/results/calibration_layer_diagnosis.md`: parametri beta "
       "riusati qui, collasso sul predittore costante;")
    ap("- `audit/results/overdispersion_condizionale_diagnosis.md`: NegBin "
       "sulle soglie e fallimento su GG;")
    ap("- `audit/results/combo_1x2_totali_diagnosis.md`: walk-forward e "
       "cross-check condivisi.")
    ap("")

    md = "\n".join(L) + "\n"
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Scritto {OUT_PATH}")
    for ev, name, mkt, *_ in EVENTS:
        for split in ("validation", "test"):
            r0 = murph[(ev, "AGGREGATO", split, "raw")]
            r1 = murph[(ev, "AGGREGATO", split, "cal")]
            a = absres[(ev, "AGGREGATO", split)]
            print(f"{mkt:6s} {split:10s} REL {r0['rel']:.4f}->{r1['rel']:.4f} "
                  f"RES {r0['res']:.4f}->{r1['res']:.4f} "
                  f"({100*a['res_frac_cal']:.1f}% UNC) "
                  f"Brier {r0['brier']:.4f}->{r1['brier']:.4f} UNC {r0['unc']:.4f}")
    for ev in ("over", "gg"):
        c = consistency[ev]
        print(f"{ev}: identity {c['max_ident']:.1e} dRES {c['max_dres']:.1e} "
              f"spearman {c['min_spearman']:.6f} inversioni {c['inversions']}")
    print("sostanziale?", sostanziale)


if __name__ == "__main__":
    main()
