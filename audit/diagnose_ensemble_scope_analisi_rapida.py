"""
diagnose_ensemble_scope_analisi_rapida.py — Analisi di SCOPO dell'ensemble
Poisson+Elo (w=0.6) sulla selezione a 7 mercati di analisi_rapida_giornata().

Domanda: l'audit diagnose_elo_ensemble.py ha validato l'ensemble sulla
probabilita' 1X2 in se' (Brier 0.5893 -> 0.5830). Ma da d21f5c3 l'1X2 blendato
entra anche nell'ARGMAX a 7 mercati di analisi_rapida_giornata() e delle card
giornata (prima il blend esisteva solo nella confidence del Top Mix). Quanto
spesso cambia il mercato selezionato? E il cambio migliora o peggiora?

REGOLE (audit in sola lettura):
  - NESSUNA modifica a SoccerMath/: il protocollo legge app.py e i modelli,
    non scrive nulla.
  - Regime A (PRE d21f5c3): selezione argmax sui mercati Poisson PURO
    (il blend esisteva solo nella confidence del Top Mix, non nelle
    probabilita' di Analisi Rapida/card).
  - Regime B (POST d21f5c3): selezione argmax sui mercati con 1X2 blendato
    (0.6*Poisson + 0.4*Elo), Totali invariati.
  - Entrambi i regimi usano la STESSA logica di selezione di produzione:
    argmax su {Vittoria casa, Pareggio, Vittoria trasferta, Over 2.5,
    Under 2.5, GG, NG} (stesso ordine del dizionario in app.py, stessi
    tie-break).

PARTI:
  1. Campione live (lo stesso >=30 partite di
     SoccerMath/test_elo_ensemble_1x2.py::TestEnsembleSuCampioneReale,
     funzioni di produzione app.get_full_poisson_two_heads e
     app.blend_elo_into_1x2): % di best_mkt cambiate + esito reale.
  2. Walk-forward storico (STESSO harness di diagnose_elo_ensemble.py:
     VALIDATION 2024/25 + TEST 2025/26, 5 leghe, no-leakage): Brier di
     selezione e ROI a quota fissa (B365) dei due regimi; il ROI copre solo
     i mercati con quota nel CSV (1X2 e O/U 2.5; GG/NG non hanno quota nei
     database football-data).
  3. Cross-check: le colonne 1X2/Elo del walk-forward esteso devono essere
     BIT-IDENTICHE a diagnose_elo_ensemble.run_models (stesso identico
     percorso di calcolo).

Output: audit/results/ensemble_scope_analisi_rapida.md
Uso:    python audit/diagnose_ensemble_scope_analisi_rapida.py
"""
from __future__ import annotations

import math
import os
import sys
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")

import diagnose_elo_ensemble as dee  # noqa: E402  (import sicuro: main guardata)
from backtest_experiment_all import LEAGUES, MARKET_VALUES, load_league  # noqa: E402
from config import LEAGUES_CONFIG  # noqa: E402

OUT_PATH = os.path.join(_AUDIT_DIR, "results",
                        "ensemble_scope_analisi_rapida.md")

# Nome breve dei 7 mercati (indipendente dai nomi delle squadre)
BASE_KEYS = ("1", "X", "2", "O", "U", "GG", "NG")
# colonna CSV della quota per mercato base (None = quota non presente nei DB)
ODDS_COL = {"1": "B365H", "X": "B365D", "2": "B365A",
            "O": "B365>2.5", "U": "B365<2.5", "GG": None, "NG": None}
SEASON_LABEL = {"2024/25": "VALIDATION 2024/25", "2025/26": "TEST 2025/26"}


# ---------------------------------------------------------------------------
# Logica di selezione: replica ESATTA di analisi_rapida_giornata (app.py)
# ---------------------------------------------------------------------------
def mercati_7(p1, pX, p2, u25, gg, home, away):
    """Stesso dizionario, stesso ordine di inserimento di
    analisi_rapida_giornata(): i tie-break di max(..., key=dict.get) sono
    deterministici a parita' di ordine."""
    return {
        f"Vittoria {home}": p1, "Pareggio": pX, f"Vittoria {away}": p2,
        "Over 2.5": 1 - u25, "Under 2.5": u25, "GG": gg, "NG": 1 - gg,
    }


def base_key(market, home, away):
    if market == f"Vittoria {home}":
        return "1"
    if market == f"Vittoria {away}":
        return "2"
    return {"Pareggio": "X", "Over 2.5": "O", "Under 2.5": "U",
            "GG": "GG", "NG": "NG"}[market]


def esiti_reali(fthg, ftag, ftr):
    """Esito binario reale per ognuno dei 7 mercati base."""
    ftr = str(ftr).strip().upper()
    gg = (fthg > 0) and (ftag > 0)
    return {
        "1": ftr == "H", "X": ftr == "D", "2": ftr == "A",
        "O": (fthg + ftag) > 2.5, "U": (fthg + ftag) <= 2.5,
        "GG": gg, "NG": not gg,
    }


def scegli(mercati):
    """Argmax di produzione: max(mercati, key=mercati.get)."""
    return max(mercati, key=mercati.get)


# ---------------------------------------------------------------------------
# PARTE 1 — campione live (stesso campionamento del test permanente)
# ---------------------------------------------------------------------------
SAMPLES_PER_LEAGUE = 12


def live_sample():
    import app as prod_app  # import tardivo: porta con se' Streamlit
    results = []
    for camp_key in LEAGUES_CONFIG:
        res = prod_app.get_league_engine(camp_key)
        if not res:
            raise SystemExit(f"get_league_engine({camp_key!r}) senza dati")
        stats, avg_h, avg_a, df = res
        n = len(df)
        step = max(1, n // SAMPLES_PER_LEAGUE)
        i = 0
        while i < n:
            row = df.iloc[i]
            h, a = row.HomeClean, row.AwayClean
            i += step
            if h not in stats or a not in stats:
                continue
            hs, as_ = stats[h], stats[a]
            m_raw = prod_app.get_full_poisson_two_heads(hs, as_, avg_h, avg_a)
            m_blend = prod_app.blend_elo_into_1x2(m_raw, h, a, camp_key)
            # Totali bit-identici per costruzione: verifica di sicurezza
            assert m_blend["u25"] == m_raw["u25"] and m_blend["gg"] == m_raw["gg"]
            merc_a = mercati_7(m_raw["1"], m_raw["X"], m_raw["2"],
                                m_raw["u25"], m_raw["gg"], h, a)
            merc_b = mercati_7(m_blend["1"], m_blend["X"], m_blend["2"],
                               m_blend["u25"], m_blend["gg"], h, a)
            best_a, best_b = scegli(merc_a), scegli(merc_b)
            fthg = row.FTHG if pd.notna(row.FTHG) else None
            ftag = row.FTAG if pd.notna(row.FTAG) else None
            ftr = str(row.FTR).strip().upper() if pd.notna(row.FTR) else ""
            esito = esiti_reali(fthg, ftag, ftr) if fthg is not None else None
            results.append({
                "league": camp_key, "home": h, "away": a,
                "date": str(row.Date), "fthg": fthg, "ftag": ftag,
                "best_a": best_a, "conf_a": merc_a[best_a],
                "best_b": best_b, "conf_b": merc_b[best_b],
                "base_a": base_key(best_a, h, a),
                "base_b": base_key(best_b, h, a),
                "esito": esito,
            })
    return results


# ---------------------------------------------------------------------------
# PARTE 2 — walk-forward (stesso harness di diagnose_elo_ensemble, esteso)
# ---------------------------------------------------------------------------
def run_models_extended(df, camp_key, xg_data):
    """Copia CONFORME di diagnose_elo_ensemble.run_models (stesso ordine di
    operazioni, stessi clip, stesse formule) con campi aggiuntivi per riga:
    u25/gg del Poisson, quote B365 e gol reali. La conformita' e' verificata
    bit-a-bit contro l'originale in cross_check()."""
    home_adv = dee.LEAGUE_HOME_ADVANTAGE.get(camp_key, 60.0)
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

    for _, row in df.iterrows():
        fthg, ftag = int(row.FTHG), int(row.FTAG)
        ftr = str(row.FTR).strip().upper()
        h, a = row.HomeClean, row.AwayClean
        sh, sa = get(h), get(a)
        avg_h = max(tot_hg / tot_n, 0.1) if tot_n else 0.1
        avg_a = max(tot_ag / tot_n, 0.1) if tot_n else 0.1
        r_h, r_a = elo.get(h, 1500.0), elo.get(a, 1500.0)

        if row.season in dee.SEASONS_EVAL:
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
            lam_base_h = pa_h * fa_h * pd_a * fd_a * avg_h
            lam_base_a = pa_a * fa_a * pd_h * fd_h * avg_a
            lam_m_h = (pa_h * fa_h * m_h) * (pd_a * fd_a / m_a) * avg_h
            lam_m_a = (pa_a * fa_a * m_a) * (pd_h * fd_h / m_h) * avg_a
            S = lam_base_h + lam_base_a
            den = lam_m_h + lam_m_a
            lh = dee.clip(S * lam_m_h / den) if den > 0 else dee.clip(lam_base_h)
            la = dee.clip(S * lam_m_a / den) if den > 0 else dee.clip(lam_base_a)
            mp = dee.get_full_poisson(lh, la)
            e1, eX, e2 = dee.elo_probs(r_h, r_a, home_adv)
            rows.append({
                "season": row.season,
                "y": {"H": 0, "D": 1, "A": 2}.get(ftr, 1),
                "p1": mp["1"], "pX": mp["X"], "p2": mp["2"],
                "e1": e1, "eX": eX, "e2": e2,
                # campi estesi
                "u25": mp["u25"], "gg": mp["gg"],
                "fthg": fthg, "ftag": ftag, "ftr": ftr,
                "home": h, "away": a,
                "odds_H": row.get("B365H"), "odds_D": row.get("B365D"),
                "odds_A": row.get("B365A"),
                "odds_O": row.get("B365>2.5"), "odds_U": row.get("B365<2.5"),
            })

        # aggiornamento stato (dopo la predizione) — identico all'originale
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


def cross_check(per_league_df, per_league_xg):
    """Le colonne condivise devono essere BIT-IDENTICHE a
    diagnose_elo_ensemble.run_models: garantisce che il walk-forward e' lo
    stesso dell'audit originale."""
    for (prefix, ck), dfe in per_league_df.items():
        orig = dee.run_models(load_league(prefix), ck, per_league_xg[ck])
        for col in ("p1", "pX", "p2", "e1", "eX", "e2", "y", "season"):
            if not np.array_equal(orig[col].to_numpy(), dfe[col].to_numpy()):
                raise SystemExit(
                    f"CROSS-CHECK FALLITO {ck} colonna {col}: il walk-forward "
                    "esteso diverge da diagnose_elo_ensemble.run_models")
    print("cross-check walk-forward: OK (bit-identico a diagnose_elo_ensemble)")


# ---------------------------------------------------------------------------
# Metriche dei due regimi sul walk-forward
# ---------------------------------------------------------------------------
def regimi_riga(r, w=dee.WEIGHTS[1]):  # WEIGHTS[1] = 0.6
    """Ritorna (riga regime A, riga regime B) per una riga di walk-forward."""
    h, a = r["home"], r["away"]
    esito = esiti_reali(r["fthg"], r["ftag"], r["ftr"])
    merc_a = mercati_7(r["p1"], r["pX"], r["p2"], r["u25"], r["gg"], h, a)
    b1 = w * r["p1"] + (1 - w) * r["e1"]
    bX = w * r["pX"] + (1 - w) * r["eX"]
    b2 = w * r["p2"] + (1 - w) * r["e2"]
    merc_b = mercati_7(b1, bX, b2, r["u25"], r["gg"], h, a)
    out = []
    for regime, merc in (("A", merc_a), ("B", merc_b)):
        best = scegli(merc)
        bk = base_key(best, h, a)
        conf = merc[best]
        hit = 1.0 if esito[bk] else 0.0
        odds_col = {"1": "odds_H", "X": "odds_D", "2": "odds_A",
                    "O": "odds_O", "U": "odds_U"}.get(bk)
        odds = r.get(odds_col) if odds_col else None
        odds = float(odds) if odds is not None and pd.notna(odds) and odds > 1.0 else None
        out.append({"regime": regime, "season": r["season"], "best": best,
                    "base": bk, "conf": conf, "hit": hit, "odds": odds,
                    "home": h, "away": a})
    return out[0], out[1]


def metrics(rows):
    n = len(rows)
    if n == 0:
        return None
    confs = np.array([r["conf"] for r in rows])
    hits = np.array([r["hit"] for r in rows])
    brier = float(np.mean((confs - hits) ** 2))
    ll = float(-np.mean(np.log(np.clip(
        np.where(hits == 1, confs, 1 - confs), 1e-12, 1.0))))
    bets = [r for r in rows if r["odds"] is not None]
    roi = (float(np.mean([r["hit"] * r["odds"] - 1.0 for r in bets]))
           if bets else None)
    return {"n": n, "brier": brier, "logloss": ll, "hit_rate": float(hits.mean()),
            "conf_media": float(confs.mean()), "roi": roi, "n_bets": len(bets)}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def fmt(x, dec=4):
    return "n/d" if x is None else f"{x:.{dec}f}"


def main():
    # ---- preparazione walk-forward (dati e xG come diagnose_elo_ensemble) --
    per_league_df, per_league_xg = {}, {}
    for prefix, ck in LEAGUES:
        df = load_league(prefix)
        xg = dee.load_xg(ck)
        per_league_xg[ck] = xg
        per_league_df[(prefix, ck)] = run_models_extended(df, ck, xg)
    cross_check(per_league_df, per_league_xg)

    allrows = []
    for (prefix, ck), dfe in per_league_df.items():
        for _, r in dfe.iterrows():
            ra, rb = regimi_riga(r)
            ra["league"], rb["league"] = ck, ck
            allrows.append((ra, rb))

    # ---- PARTE 1: campione live -------------------------------------------
    live = live_sample()
    flips_live = [x for x in live if x["best_a"] != x["best_b"]]

    # ---- PARTE 2: metriche walk-forward ------------------------------------
    split = {}
    for label, flt in (
            ("VALIDATION 2024/25", lambda r: r["season"] == "2024/25"),
            ("TEST 2025/26", lambda r: r["season"] == "2025/26"),
            ("AGGREGATO V+T", lambda r: True)):
        ra = [x[0] for x in allrows if flt(x[0])]
        rb = [x[1] for x in allrows if flt(x[1])]
        flips = [(x[0], x[1]) for x in allrows
                 if flt(x[0]) and x[0]["best"] != x[1]["best"]]
        split[label] = (metrics(ra), metrics(rb), flips)

    # ---- scrittura report ---------------------------------------------------
    L = []
    L.append("# Ensemble Poisson+Elo: analisi di scopo sulla selezione a 7 mercati")
    L.append("")
    L.append("Audit in sola lettura (nessuna modifica a SoccerMath/). Domanda: da "
             "d21f5c3 l'1X2 blendato (w=0.6) entra nell'argmax a 7 mercati di "
             "analisi_rapida_giornata() e delle card giornata. Quanto cambia il "
             "mercato selezionato rispetto al comportamento pre-modifica (Poisson "
             "puro, blend presente solo nella confidence del Top Mix)? E il cambio "
             "migliora o peggiora la scelta?")
    L.append("")
    L.append("- **Regime A (PRE d21f5c3)**: argmax su mercati Poisson puro.")
    L.append("- **Regime B (POST d21f5c3)**: argmax su mercati con 1X2 = 0.6*Poisson + 0.4*Elo; Totali invariati.")
    L.append("- Stessa logica di selezione di produzione (stesso dizionario, stesso ordine).")
    L.append("- Brier di selezione = Brier binario (confidenza del mercato scelto vs esito reale del mercato scelto).")
    L.append("- ROI = puntata piatta 1 unita' alla quota B365 del mercato scelto; copre solo i mercati con quota nel CSV (1X2, O/U 2.5; GG/NG senza quota nei database football-data).")
    L.append("")

    # -- live
    L.append("## 1) Campione live (stesso campionamento del test permanente, funzioni di produzione)")
    L.append("")
    L.append(f"Partite campionate: {len(live)} (>= 30) | best_mkt cambiato: "
             f"**{len(flips_live)}/{len(live)} = {100*len(flips_live)/len(live):.1f}%**")
    L.append("")
    if flips_live:
        L.append("| Lega | Partita | Risultato | PRE (A) | conf A | POST (B) | conf B | scelto da A corretto? | scelto da B corretto? |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for x in flips_live:
            score = (f"{int(x['fthg'])}-{int(x['ftag'])}"
                     if x["fthg"] is not None else "n/d")
            ok_a = "—" if x["esito"] is None else ("si'" if x["esito"][x["base_a"]] else "no")
            ok_b = "—" if x["esito"] is None else ("si'" if x["esito"][x["base_b"]] else "no")
            L.append(f"| {x['league']} | {x['home']}-{x['away']} | {score} | "
                     f"{x['best_a']} | {x['conf_a']:.3f} | {x['best_b']} | "
                     f"{x['conf_b']:.3f} | {ok_a} | {ok_b} |")
        hit_a = sum(1 for x in flips_live if x["esito"] and x["esito"][x["base_a"]])
        hit_b = sum(1 for x in flips_live if x["esito"] and x["esito"][x["base_b"]])
        with_esito = sum(1 for x in flips_live if x["esito"] is not None)
        L.append("")
        L.append(f"Sui {with_esito} flip con esito disponibile: scelta PRE corretta "
                 f"{hit_a} volte, scelta POST corretta {hit_b} volte.")
    L.append("")

    # -- walk-forward
    L.append("## 2) Walk-forward storico (stesso harness di diagnose_elo_ensemble.py, cross-check bit-identico)")
    L.append("")
    L.append("| Split | Regime | n | Brier sel. | LogLoss sel. | hit rate | conf media | ROI (B365) | n scommesse |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for label, (ma, mb, _) in split.items():
        L.append(f"| {label} | A (Poisson puro) | {ma['n']} | {fmt(ma['brier'])} | "
                 f"{fmt(ma['logloss'])} | {fmt(ma['hit_rate'])} | {fmt(ma['conf_media'])} | "
                 f"{fmt(ma['roi'])} | {ma['n_bets']} |")
        L.append(f"| {label} | B (1X2 blendato) | {mb['n']} | {fmt(mb['brier'])} | "
                 f"{fmt(mb['logloss'])} | {fmt(mb['hit_rate'])} | {fmt(mb['conf_media'])} | "
                 f"{fmt(mb['roi'])} | {mb['n_bets']} |")
    L.append("")
    for label, (ma, mb, _) in split.items():
        L.append(f"Delta {label} (B - A): Brier {mb['brier']-ma['brier']:+.4f} | "
                 f"LogLoss {mb['logloss']-ma['logloss']:+.4f} | "
                 f"ROI {fmt(mb['roi']-ma['roi'], 4) if ma['roi'] is not None and mb['roi'] is not None else 'n/d'}")
    L.append("")

    # -- flip sul walk-forward
    agg_flips = split["AGGREGATO V+T"][2]
    n_agg = split["AGGREGATO V+T"][0]["n"]
    L.append("## 3) Cambio di mercato selezionato (walk-forward)")
    L.append("")
    L.append(f"Best_mkt cambiato in **{len(agg_flips)}/{n_agg} = "
             f"{100*len(agg_flips)/n_agg:.1f}%** delle partite (aggregato V+T).")
    L.append("")
    trans = Counter((x[0]["base"], x[1]["base"]) for x in agg_flips)
    L.append("Transizioni (base market PRE -> POST):")
    L.append("")
    for (ba, bb), c in sorted(trans.items(), key=lambda kv: -kv[1]):
        L.append(f"- {ba} -> {bb}: {c}")
    L.append("")
    hit_a = sum(1 for ra, _ in agg_flips if ra["hit"])
    hit_b = sum(1 for _, rb in agg_flips if rb["hit"])
    brier_fa = float(np.mean([(ra["conf"] - ra["hit"]) ** 2 for ra, _ in agg_flips]))
    brier_fb = float(np.mean([(rb["conf"] - rb["hit"]) ** 2 for ra, rb in agg_flips]))
    roi_fa = [ra["hit"] * ra["odds"] - 1 for ra, _ in agg_flips if ra["odds"]]
    roi_fb = [rb["hit"] * rb["odds"] - 1 for _, rb in agg_flips if rb["odds"]]
    L.append(f"Sui soli flip: scelta PRE corretta {hit_a}/{len(agg_flips)} "
             f"({100*hit_a/len(agg_flips):.1f}%), scelta POST corretta "
             f"{hit_b}/{len(agg_flips)} ({100*hit_b/len(agg_flips):.1f}%).")
    L.append("")
    L.append(f"Sui soli flip: Brier selezione PRE {brier_fa:.4f} vs POST {brier_fb:.4f} "
             f"(delta {brier_fb-brier_fa:+.4f}); ROI PRE {fmt(np.mean(roi_fa) if roi_fa else None)} "
             f"({len(roi_fa)} scommesse) vs POST {fmt(np.mean(roi_fb) if roi_fb else None)} "
             f"({len(roi_fb)} scommesse).")
    L.append("")

    # -- per lega
    L.append("## 4) Per lega (aggregato V+T)")
    L.append("")
    L.append("| Lega | n | Brier A | Brier B | Δ | flip % | ROI A | ROI B |")
    L.append("|---|---|---|---|---|---|---|---|")
    for _, ck in LEAGUES:
        ra = [x[0] for x in allrows if x[0]["league"] == ck]
        rb = [x[1] for x in allrows if x[1]["league"] == ck]
        ma, mb = metrics(ra), metrics(rb)
        nfl = sum(1 for x in allrows if x[0]["league"] == ck
                  and x[0]["best"] != x[1]["best"])
        L.append(f"| {ck} | {ma['n']} | {fmt(ma['brier'])} | {fmt(mb['brier'])} | "
                 f"{mb['brier']-ma['brier']:+.4f} | {100*nfl/ma['n']:.1f}% | "
                 f"{fmt(ma['roi'])} | {fmt(mb['roi'])} |")
    L.append("")
    L.append("## Nota metodologica")
    L.append("")
    L.append("- Il walk-forward e' lo STESSO di audit/results/elo_ensemble_diagnosis.md "
             "(verificato bit-a-bit su p1/pX/p2/e1/eX/e2/y per tutte le leghe).")
    L.append("- Il Brier di selezione misura insieme qualita' della scelta e "
             "calibrazione della confidenza sul mercato scelto; l'audit "
             "elo_ensemble misura la probabilita' 1X2 completa (3 esiti). I due "
             "numeri NON sono direttamente confrontabili in valore assoluto.")
    L.append("- Rumore: SE del Brier binario con n~3500 e' ~0.007; delta sotto "
             "questa soglia vanno letti come 'entro il rumore'.")
    L.append("")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"\nReport: {OUT_PATH}")


if __name__ == "__main__":
    main()
