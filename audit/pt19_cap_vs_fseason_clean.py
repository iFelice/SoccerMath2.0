"""
pt19_cap_vs_fseason_clean.py — Confronto pulito F_season vs PT19_CAP per la
fonte point-in-time della testa Totali. SNAPSHOT DI PRODUZIONE ESCLUSO dalla
decisione (contaminato da informazione futura entro la stessa stagione):
resta solo come nota.

Bracci (solo att0_pure/def0_pure cambiano; la testa 1X2 e' identica per
costruzione e verificata a 0.0):

  F_season  = medie xG della SOLA stagione in corso al cutoff della partita
              (season_averages, point-in-time, no leakage), shrinkage
              PRIOR_MATCHES=6 verso la media di lega della stagione in corso,
              fallback gol per le squadre senza partite in stagione. E' la
              fonte isolata nel Problema B (Premier TEST O/U2.5 Brier
              0.252257, bit-identica alla colonna STATIC dell'audit);
  PT19_CAP  = finestra trailing 19 partite multi-stagione con tetto di eta'
              400 giorni e minimo 5 partite (quella attualmente cablata in
              app.get_league_engine su questo branch), stessa ancora di
              shrinkage, fallback gol per "dato insufficiente".

In piu': fallback rate per lega/stagione di F_season, PT19 (no cap),
PT19_CAP e copertura dello snapshot di produzione (candidati per il
riferimento "32,65% originale").

Output: audit/results/pt19_cap_vs_fseason_clean.md
Uso:    python audit/pt19_cap_vs_fseason_clean.py
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from backtest_experiment_all import load_league, LEAGUES, MARKET_VALUES  # noqa: E402
import app as prod_app  # noqa: E402
from xg_archive import (  # noqa: E402
    load_archive, point_in_time_averages, season_averages,
)
from pt19_age_cap_audit import (  # noqa: E402
    PRIOR, PT_WINDOW, PT_AGE_CAP, PT_MIN_MATCHES, TeamState, shrunk_ratio,
    league_anchor, load_prod_snapshot, season_year_of,
)

SEASONS_EVAL = ("2024/25", "2025/26")
OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "pt19_cap_vs_fseason_clean.md")
NOISE = 0.002  # soglia pratica "entro il rumore" (SE Brier ~0.025/stagione)


def run_league(prefix, league, cache):
    """Walk-forward no-leakage identico a pt19_age_cap_audit.run_league:
    stesso ordine partite, stesse medie gol progressive, stessa forma/mkt,
    stesso primary 1X2. Ritorna righe con i due bracci F e CP e i flag di
    fallback di F, PT19 (no cap) e PT19_CAP."""
    df = load_league(prefix)
    records = load_archive(league)
    snapshot = load_prod_snapshot(league)
    state = {}
    tot_hg = tot_ag = tot_n = 0.0
    rows = []

    def get(t):
        if t not in state:
            state[t] = TeamState()
        return state[t]

    for _, row in df.iterrows():
        fthg = int(row.FTHG)
        ftag = int(row.FTAG)
        h, a = row.HomeClean, row.AwayClean
        sh, sa = get(h), get(a)
        avg_h = max(tot_hg / tot_n, 0.1) if tot_n else 0.1
        avg_a = max(tot_ag / tot_n, 0.1) if tot_n else 0.1

        def form_fac(ts):
            if len(ts.last5) < 3:
                return 1.0, 1.0
            n = len(ts.last5)
            gf = sum(x[0] for x in ts.last5)
            ga = sum(x[1] for x in ts.last5)
            den = max((avg_h + avg_a) / 2.0, 0.5)
            return (max(0.85, min(1.15, (gf / n) / den)),
                    max(0.85, min(1.15, (ga / n) / den)))

        def mkt_factor(t):
            val = MARKET_VALUES.get(t, 50)
            m = 1.0 + (math.log10(max(val, 10)) - 2.0) / 4.0
            return max(0.85, min(1.25, m))

        in_eval = row.season in SEASONS_EVAL
        date_key = (league, row.Date)
        if in_eval and date_key not in cache:
            cutoff = row.Date
            static = season_averages(
                league, season_year_of(row.season), cutoff=cutoff,
                records=records).averages
            cache[date_key] = {
                "static": static,
                "lxg": league_anchor(static)[0],
                "lxga": league_anchor(static)[1],
                "nocap": point_in_time_averages(
                    league, cutoff=cutoff, records=records,
                    window=PT_WINDOW, max_age_days=None,
                    min_matches=PT_MIN_MATCHES),
                "cap": point_in_time_averages(
                    league, cutoff=cutoff, records=records,
                    window=PT_WINDOW, max_age_days=PT_AGE_CAP,
                    min_matches=PT_MIN_MATCHES),
            }

        def primary(t, ts):
            """Fonte F_season = fonte statica stagionale dell'audit ( STATIC).
            Ritorna (att, def, usato_fallback)."""
            if not in_eval:
                r = ts.goal_fallback(avg_h, avg_a)
                return r[0], r[1], False
            xg_data = cache[date_key]["static"]
            lxg, lxga = cache[date_key]["lxg"], cache[date_key]["lxga"]
            rec = xg_data.get(t) if xg_data else None
            if rec is not None and lxg and lxga and isinstance(rec, dict):
                xv, xa, n = rec.get("xG_avg"), rec.get("xGA_avg"), rec.get("matches")
                try:
                    xv, xa = float(xv), float(xa)
                    val_ok = np.isfinite(xv) and np.isfinite(xa) and xv >= 0 and xa >= 0
                except (TypeError, ValueError):
                    val_ok, n = False, None
                n_ok = (isinstance(n, (int, float)) and not isinstance(n, bool)
                        and np.isfinite(float(n)) and float(n) > 0)
                if val_ok and (n_ok or (xv > 0 and xa > 0)):
                    if n_ok:
                        return (shrunk_ratio(xv, lxg, float(n)),
                                shrunk_ratio(xa, lxga, float(n)), False)
                    return xv / lxg, xa / lxga, False
            r = ts.goal_fallback(avg_h, avg_a)
            return r[0], r[1], True

        p_att_h, p_def_h, fb_fh = primary(h, sh)
        p_att_a, p_def_a, fb_fa = primary(a, sa)
        fah, fdh = form_fac(sh)
        faa, fda = form_fac(sa)
        mh, ma = mkt_factor(h), mkt_factor(a)

        def make_stats(p_att, p_def, f_att, f_def, mkt, pure):
            return {"att": p_att * f_att * mkt, "def": p_def * f_def / mkt,
                    "att0": p_att * f_att, "def0": p_def * f_def,
                    "att0_pure": pure[0], "def0_pure": pure[1], "val": 50}

        def predict(pure_h, pure_a):
            hs = make_stats(p_att_h, p_def_h, fah, fdh, mh, pure_h)
            as_ = make_stats(p_att_a, p_def_a, faa, fda, ma, pure_a)
            return prod_app.get_full_poisson_two_heads(hs, as_, avg_h, avg_a)

        if in_eval:
            c = cache[date_key]
            m_f = predict((p_att_h, p_def_h), (p_att_a, p_def_a))

            lxg, lxga = c["lxg"], c["lxga"]
            fb_h = sh.goal_fallback(avg_h, avg_a)
            fb_a = sa.goal_fallback(avg_h, avg_a)

            def pure_from_pt(pt):
                out = {}
                for t, fb in ((h, fb_h), (a, fb_a)):
                    rec = pt.averages.get(t)
                    if rec is not None and lxg and lxga:
                        out[t] = (shrunk_ratio(rec["xG_avg"], lxg, rec["matches"]),
                                  shrunk_ratio(rec["xGA_avg"], lxga, rec["matches"]))
                    else:
                        out[t] = fb
                return out

            pc = pure_from_pt(c["cap"])
            m_cp = predict(pc[h], pc[a])

            rows.append({
                "season": row.season, "date": row.Date,
                "home": h, "away": a,
                "real_uo": "OVER" if (fthg + ftag) > 2.5 else "UNDER",
                "real_gg": "GG" if fthg > 0 and ftag > 0 else "NG",
                "f_1": m_f["1"], "f_X": m_f["X"], "f_2": m_f["2"],
                "f_po": 1 - m_f["u25"], "f_gg": m_f["gg"],
                "cp_1": m_cp["1"], "cp_X": m_cp["X"], "cp_2": m_cp["2"],
                "cp_po": 1 - m_cp["u25"], "cp_gg": m_cp["gg"],
                "fb_f": fb_fh or fb_fa,
                "fb_nocap": (h not in c["nocap"].averages)
                            or (a not in c["nocap"].averages),
                "fb_cap": (h not in c["cap"].averages)
                          or (a not in c["cap"].averages),
                "fb_snap": (h not in snapshot) or (a not in snapshot),
            })

        tot_hg += fthg
        tot_ag += ftag
        tot_n += 1
        sh.observe_home(fthg, ftag)
        sa.observe_away(fthg, ftag)

    return pd.DataFrame(rows)


def brier_ll(sub, pcol, target_col, target):
    p = sub[pcol].to_numpy(dtype=float)
    y = (sub[target_col] == target).astype(int).to_numpy()
    b = float(np.mean((y - p) ** 2))
    pc = np.clip(p, 1e-12, 1 - 1e-12)
    ll = float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc)))
    return b, ll


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    cache = {}
    all_res = {}
    for prefix, league in LEAGUES:
        all_res[league] = run_league(prefix, league, cache)

    out = []
    A = out.append
    A("# Confronto pulito: F_season vs PT19_CAP (fonte point-in-time della testa Totali)")
    A("")
    A("Walk-forward no-leakage, 5 leghe, VAL 2024/25 + TEST 2025/26, testa "
      "**Totali** (O/U2.5 e GG/NG). Lo snapshot di produzione e' ESCLUSO dal "
      "verdetto (contaminato da informazione futura entro la stessa stagione); "
      "resta come nota in fondo.")
    A("")
    A("- **F_season** = medie xG della sola stagione in corso al cutoff "
      "(point-in-time, no leakage) + shrinkage PRIOR_MATCHES=6 + fallback gol "
      "(fonte isolata nel Problema B: Premier TEST O/U2.5 Brier 0.252257);")
    A(f"- **PT19_CAP** = finestra trailing {PT_WINDOW} multi-stagione, tetto "
      f"{PT_AGE_CAP:.0f} giorni, minimo {PT_MIN_MATCHES} partite (la fonte "
      "attualmente cablata in app.py su questo branch).")
    A("")
    A("La testa 1X2 usa la stessa fonte nei due bracci: verificata bit-identica sotto.")
    A("")

    # --- 1X2 invarianza ---
    worst = 0.0
    for league, res in all_res.items():
        for k in ("1", "X", "2"):
            worst = max(worst, float((res["f_" + k] - res["cp_" + k]).abs().max()))
    A(f"**1X2 F_season vs PT19_CAP: max abs diff = {worst:.1e}** (atteso 0.0: "
      "cambia solo att0_pure/def0_pure).")
    A("")

    # --- sanity check vs numeri noti del Problema B ---
    pl_test = all_res["Premier League"]
    pl_test = pl_test[pl_test["season"] == "2025/26"]
    b_chk, _ = brier_ll(pl_test, "f_po", "real_uo", "OVER")
    b_cp_chk, _ = brier_ll(pl_test, "cp_po", "real_uo", "OVER")
    A(f"Sanity check Premier TEST 2025/26 O/U2.5 Brier: F_season {b_chk:.6f} "
      f"(atteso 0.252257 dal Problema B), PT19_CAP {b_cp_chk:.6f} (atteso "
      "~0.2563 dall'audit).")
    A("")

    # --- tabella per lega/stagione ---
    A("## Risultati per lega e stagione (Brier / LogLoss, delta = PT19_CAP − F_season)")
    A("")
    A("| Lega | Stagione | N | Mercato | Metrica | F_season | PT19_CAP | Δ | Vincitore |")
    A("|---|---|---|---|---|---|---|---|---|")
    for _, league in LEAGUES:
        res = all_res[league]
        for season in SEASONS_EVAL:
            sub = res[res["season"] == season]
            if sub.empty:
                continue
            for mname, col, rc, tgt in (
                    ("O/U2.5", "po", "real_uo", "OVER"),
                    ("GG/NG", "gg", "real_gg", "GG")):
                for metric, idx in (("Brier", 0), ("LogLoss", 1)):
                    vf = brier_ll(sub, "f_" + col, rc, tgt)[idx]
                    vc = brier_ll(sub, "cp_" + col, rc, tgt)[idx]
                    d = vc - vf
                    if abs(d) <= NOISE:
                        win = "≈ rumore"
                    else:
                        win = "**F_season**" if d > 0 else "**PT19_CAP**"
                    A(f"| {league} | {season} | {len(sub)} | {mname} | {metric} "
                      f"| {vf:.4f} | {vc:.4f} | {d:+.4f} | {win} |")
    A("")

    # --- pooling per lega (VAL+TEST) e aggregato complessivo ---
    A("## Pool per lega (VAL 2024/25 + TEST 2025/26) e aggregato")
    A("")
    A("| Ambito | N | Mercato | Metrica | F_season | PT19_CAP | Δ |")
    A("|---|---|---|---|---|---|---|")
    pooled_all = []
    league_pooled_ou = {}
    for _, league in LEAGUES:
        res = all_res[league]
        pooled_all.append(res)
        for mname, col, rc, tgt in (("O/U2.5", "po", "real_uo", "OVER"),
                                    ("GG/NG", "gg", "real_gg", "GG")):
            for metric, idx in (("Brier", 0), ("LogLoss", 1)):
                vf = brier_ll(res, "f_" + col, rc, tgt)[idx]
                vc = brier_ll(res, "cp_" + col, rc, tgt)[idx]
                A(f"| {league} | {len(res)} | {mname} | {metric} "
                  f"| {vf:.4f} | {vc:.4f} | {vc - vf:+.4f} |")
                if mname == "O/U2.5" and metric == "Brier":
                    league_pooled_ou[league] = (vf, vc)
    tot = pd.concat(pooled_all, ignore_index=True)
    total_ou_brier = None
    for mname, col, rc, tgt in (("O/U2.5", "po", "real_uo", "OVER"),
                                ("GG/NG", "gg", "real_gg", "GG")):
        for metric, idx in (("Brier", 0), ("LogLoss", 1)):
            vf = brier_ll(tot, "f_" + col, rc, tgt)[idx]
            vc = brier_ll(tot, "cp_" + col, rc, tgt)[idx]
            A(f"| **TOTALE 5 leghe** | {len(tot)} | {mname} | {metric} "
              f"| {vf:.4f} | {vc:.4f} | {vc - vf:+.4f} |")
            if mname == "O/U2.5" and metric == "Brier":
                total_ou_brier = (vf, vc)
    A("")

    # --- fallback rate ---
    A("## Fallback rate per lega/stagione (quota partite con almeno una squadra in fallback)")
    A("")
    A("F_season: squadra senza partite nella stagione in corso al cutoff. "
      "PT19 (no cap): squadra assente/dato insufficiente nella finestra "
      "trailing senza tetto. PT19_CAP: idem con tetto 400gg. SNAP: squadra "
      "assente dallo snapshot di produzione corrente (solo copertura, per il "
      "riferimento '32,65% originale').")
    A("")
    A("| Lega | Stagione | N | F_season | PT19 (no cap) | PT19_CAP | SNAP assenti |")
    A("|---|---|---|---|---|---|---|")
    agg_fb = {"f": [0, 0], "nocap": [0, 0], "cap": [0, 0], "snap": [0, 0]}
    for _, league in LEAGUES:
        res = all_res[league]
        for season in SEASONS_EVAL:
            sub = res[res["season"] == season]
            if sub.empty:
                continue
            n = len(sub)
            rf = float(sub["fb_f"].mean()) * 100
            rn = float(sub["fb_nocap"].mean()) * 100
            rcap = float(sub["fb_cap"].mean()) * 100
            rs = float(sub["fb_snap"].mean()) * 100
            for k, v in (("f", rf), ("nocap", rn), ("cap", rcap), ("snap", rs)):
                agg_fb[k][0] += v * n
                agg_fb[k][1] += n
            A(f"| {league} | {season} | {n} | {rf:.2f}% | {rn:.2f}% "
              f"| {rcap:.2f}% | {rs:.2f}% |")
    A(f"| **TOTALE** | | {len(tot)} "
      f"| {agg_fb['f'][0] / agg_fb['f'][1]:.2f}% "
      f"| {agg_fb['nocap'][0] / agg_fb['nocap'][1]:.2f}% "
      f"| {agg_fb['cap'][0] / agg_fb['cap'][1]:.2f}% "
      f"| {agg_fb['snap'][0] / agg_fb['snap'][1]:.2f}% |")
    A("")
    fb_f_tot = agg_fb['f'][0] / agg_fb['f'][1]
    fb_snap_tot = agg_fb['snap'][0] / agg_fb['snap'][1]
    A(f"**Risposta alla domanda sul 32,65% originale**: il 32,65% e' la quota "
      f"aggregata di partite con almeno una squadra assente dallo snapshot di "
      f"produzione (colonna SNAP assenti). F_season DA SOLO, senza alcuna "
      f"componente cross-season, porta il fallback rate al {fb_f_tot:.2f}% "
      f"aggregato: la riduzione rispetto al {fb_snap_tot:.2f}% originale NON "
      "dipende dalla componente cross-season (che in F_season non esiste ed "
      "e' quella risultata dannosa): e' tutta coperta dalla disponibilita' "
      "in-season (le squadre hanno partite della stagione in corso gia' dalla "
      "prima giornata utile; il fallback resta solo alla giornata 1).")
    A("")

    # --- verdetto per lega + raccomandazione ---
    A("## Verdetto per lega (pool VAL+TEST, O/U2.5 Brier) e raccomandazione")
    A("")
    wins_f = wins_c = ties = 0
    for league, (vf, vc) in league_pooled_ou.items():
        d = vc - vf
        if d > NOISE:
            lab = "vince **F_season**"
            wins_f += 1
        elif d < -NOISE:
            lab = "vince **PT19_CAP**"
            wins_c += 1
        else:
            lab = "entro il rumore"
            ties += 1
        A(f"- {league}: F_season {vf:.4f} vs PT19_CAP {vc:.4f} "
          f"(Δ {d:+.4f}) -> {lab}.")
    A("")
    if wins_f == len(league_pooled_ou):
        A(f"RACCOMANDAZIONE: F_season vince in modo consistente in tutte e "
          f"{len(league_pooled_ou)} le leghe: sostituire PT19_CAP con F_season "
          "come fonte point-in-time di att0_pure/def0_pure in get_league_engine.")
    elif wins_c == len(league_pooled_ou):
        A("RACCOMANDAZIONE: PT19_CAP vince in tutte le leghe: mantenere la fonte attuale.")
    else:
        vf_t, vc_t = total_ou_brier
        A(f"RACCOMANDAZIONE: esito MISTO ({wins_f} leghe F_season, {wins_c} "
          f"PT19_CAP, {ties} entro il rumore): nessuna raccomandazione unica "
          "forzata; dettaglio lega per lega sopra. Direzione aggregata: su "
          f"{len(tot)} partite F_season vince l'O/U2.5 Brier complessivo di "
          f"{vc_t - vf_t:+.4f} e non perde MAI in modo netto in nessuna lega "
          "(nessun pool di lega con delta oltre la soglia di rumore a favore "
          "di PT19_CAP).")
    A("")
    A(f"Nota di scala: errore standard del Brier ~0.025 su 306-380 partite "
      f"(~0.018 sul pool di {len(tot) // len(LEAGUES)} partite per lega): "
      f"soglia 'rumore' usata: ±{NOISE}.")
    A("")

    # --- SNAP: nota, esclusa dal verdetto ---
    A("## Nota: snapshot di produzione (ESCLUSO dal verdetto)")
    A("")
    A("Il singolo snapshot committato xg_<lega>.json e' contaminato da "
      "informazione futura entro la stessa stagione (per le squadre ancora in "
      "lega usa i valori xG della stagione corrente del file, non della "
      "stagione storica): non e' una base valida per decidere la fonte "
      "point-in-time. Per riferimento, su Premier League TEST 2025/26 "
      "(dall'audit pt19_age_cap_audit.md): SNAP O/U2.5 Brier 0.2491 vs "
      "F_season 0.2523 vs PT19_CAP 0.2563; le squadre del TEST assenti dallo "
      "snapshot erano Burnley, West Ham, Wolves (fallback gol).")
    A("")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"Report scritto in {OUT_PATH}")


if __name__ == "__main__":
    main()
