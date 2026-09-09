"""
diagnose_pt19_round_discrepancy.py — Problema B: perche' il round precedente
riportava "PT-19 full" O/U2.5 Brier = 0.2523 su Premier League TEST 2025/26
e l'audit corrente riporta PT19 (no cap) = 0.2563 (stessa lega/stagione/
mercato, stesso metodo dichiarato: finestra trailing 19, nessun tetto)?

Metodo: un SOLO walk-forward (identico a pt19_age_cap_audit.py: stesso
ordine partite, stesse medie gol avg_h/avg_a progressive, stessa forma/mkt,
stesso primary 1X2, stesso fallback gol) in cui per ogni partita si calcola
il ratio puro Totali con CIASCUNA variante di implementazione PT-19. Ogni
variante differisce per UN solo aspetto; quella che riproduce 0.2523
identifica la differenza di implementazione col round precedente.

Varianti (tutte finestra trailing 19, nessun tetto di eta', se non indicato):
  A_current      PT-19 no-cap + ancora = media di lega STATIC della stagione
                 in corso al cutoff + shrinkage PRIOR_MATCHES=6 + min 5
                 (l'implementazione corrente dell'audit)
  B_self_anchor  come A ma ancora = media delle squadre presenti nel lookup
                 PT stesso (includendo squadre non piu' in lega)
  C_no_shrink    come A ma ratio GREZZO pt_xg/ancora, senza shrinkage
  D_min0         come A ma min_matches=0 (nessun "dato insufficiente")
  E_round_none   come A ma medie PT non arrotondate a 3 decimali
  F_season       "PT" = medie della SOLA stagione in corso al cutoff
                 (season_averages, la fonte STATIC dell'audit)
  G_policy       come A ma cutoff_policy="kickoff_unsafe" (con cutoff a
                 mezzanotte e' equivalente: verifica)
  H_incl_day     come A ma cutoff = giorno partita +1 (include le partite
                 del giorno della previsione)
  I_inseason_w19 finestra trailing 19 limitata alle SOLE partite della
                 stagione 2025/26 (record pre-filtrati per stagione)
  STATIC         colonna di riferimento dell'audit (attesa 0.2523)

Solo lettura su SoccerMath/. Output su stdout.
"""
from __future__ import annotations

import math
import os
import sys
from collections import deque

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from backtest_experiment_all import load_league, MARKET_VALUES  # noqa: E402
import app as prod_app  # noqa: E402
from xg_archive import (  # noqa: E402
    load_archive, point_in_time_averages, season_averages, parse_season,
)
from pt19_age_cap_audit import (  # noqa: E402
    PRIOR, PT_WINDOW, PT_MIN_MATCHES, TeamState, shrunk_ratio, league_anchor,
)

LEAGUE = "Premier League"
SEASON = "2025/26"


def main():
    df = load_league("Premier")
    records = load_archive(LEAGUE)
    state = {}
    tot_hg = tot_ag = tot_n = 0.0
    rows = []
    cache = {}

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

        in_eval = (row.season == SEASON)
        dk = row.Date
        if in_eval and dk not in cache:
            static = season_averages(LEAGUE, 2025, cutoff=dk,
                                     records=records).averages
            lxg, lxga = league_anchor(static)

            def pt_lookup(cutoff, **kw):
                return point_in_time_averages(
                    LEAGUE, cutoff=cutoff, records=records,
                    window=PT_WINDOW, max_age_days=None,
                    min_matches=kw.get("min_matches", PT_MIN_MATCHES),
                    cutoff_policy=kw.get("cutoff_policy", "previous_day"),
                    round_digits=kw.get("round_digits", 3))

            cache[dk] = {
                "static": static, "lxg": lxg, "lxga": lxga,
                "A": pt_lookup(dk),
                "D": pt_lookup(dk, min_matches=0),
                "E": pt_lookup(dk, round_digits=12),
                "G": pt_lookup(dk, cutoff_policy="kickoff_unsafe"),
                "H": pt_lookup(dk + pd.Timedelta(days=1)),
                "F": static,  # la fonte stagionale stessa
                "I": point_in_time_averages(
                    LEAGUE, cutoff=dk,
                    records=[m for m in records
                             if parse_season(m.get("season")) == 2025],
                    window=PT_WINDOW, max_age_days=None,
                    min_matches=PT_MIN_MATCHES),
            }

        def primary(t, ts):
            if not in_eval:
                return ts.goal_fallback(avg_h, avg_a)
            static = cache[dk]["static"]
            lxg, lxga = cache[dk]["lxg"], cache[dk]["lxga"]
            rec = static.get(t) if static else None
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
                                shrunk_ratio(xa, lxga, float(n)))
                    return xv / lxg, xa / lxga
            return ts.goal_fallback(avg_h, avg_a)

        p_att_h, p_def_h = primary(h, sh)
        p_att_a, p_def_a = primary(a, sa)
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

        def pure_from(pt, lxg, lxga, shrink=True):
            """Ratio puro per h/a da un lookup PT con ancora (lxg,lxga)."""
            averages = pt.averages if hasattr(pt, "averages") else pt
            out = {}
            fb_h = sh.goal_fallback(avg_h, avg_a)
            fb_a = sa.goal_fallback(avg_h, avg_a)
            for t, fb in ((h, fb_h), (a, fb_a)):
                rec = averages.get(t)
                if rec is not None and lxg and lxga:
                    if shrink:
                        out[t] = (shrunk_ratio(rec["xG_avg"], lxg, rec["matches"]),
                                  shrunk_ratio(rec["xGA_avg"], lxga, rec["matches"]))
                    else:
                        out[t] = (rec["xG_avg"] / lxg, rec["xGA_avg"] / lxga)
                else:
                    out[t] = fb
            return out

        if in_eval:
            c = cache[dk]
            lxg, lxga = c["lxg"], c["lxga"]
            # ancora "self": media delle squadre nel lookup PT stesso
            vals = list(c["A"].averages.values())
            slxg = float(np.mean([v["xG_avg"] for v in vals])) if vals else None
            slxga = float(np.mean([v["xGA_avg"] for v in vals])) if vals else None

            variants = {
                "STATIC": predict((p_att_h, p_def_h), (p_att_a, p_def_a)),
            }
            pn = pure_from(c["A"], lxg, lxga)
            variants["A_current"] = predict(pn[h], pn[a])
            pnb = pure_from(c["A"], slxg, slxga)
            variants["B_self_anchor"] = predict(pnb[h], pnb[a])
            pnc = pure_from(c["A"], lxg, lxga, shrink=False)
            variants["C_no_shrink"] = predict(pnc[h], pnc[a])
            pnd = pure_from(c["D"], lxg, lxga)
            variants["D_min0"] = predict(pnd[h], pnd[a])
            pne = pure_from(c["E"], lxg, lxga)
            variants["E_round_none"] = predict(pne[h], pne[a])
            pnf = pure_from(c["F"], lxg, lxga)
            variants["F_season"] = predict(pnf[h], pnf[a])
            png = pure_from(c["G"], lxg, lxga)
            variants["G_policy"] = predict(png[h], png[a])
            pnh = pure_from(c["H"], lxg, lxga)
            variants["H_incl_day"] = predict(pnh[h], pnh[a])
            pni = pure_from(c["I"], lxg, lxga)
            variants["I_inseason_w19"] = predict(pni[h], pni[a])

            r = {"date": row.Date, "home": h, "away": a,
                 "real_uo": "OVER" if (fthg + ftag) > 2.5 else "UNDER",
                 "real_gg": "GG" if fthg > 0 and ftag > 0 else "NG"}
            for tag, m in variants.items():
                r[tag + "_po"] = 1 - m["u25"]
                r[tag + "_gg"] = m["gg"]
            rows.append(r)

        tot_hg += fthg
        tot_ag += ftag
        tot_n += 1
        sh.observe_home(fthg, ftag)
        sa.observe_away(fthg, ftag)

    res = pd.DataFrame(rows)

    def brier(pcol, target_col, target):
        p = res[pcol].to_numpy(dtype=float)
        y = (res[target_col] == target).astype(int).to_numpy()
        return float(np.mean((y - p) ** 2))

    def logloss(pcol, target_col, target):
        p = np.clip(res[pcol].to_numpy(dtype=float), 1e-12, 1 - 1e-12)
        y = (res[target_col] == target).astype(int).to_numpy()
        return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))

    print(f"Premier League TEST {SEASON} — {len(res)} partite\n")
    print(f"{'variante':<16} {'OU2.5 Brier':>12} {'OU2.5 LL':>10} "
          f"{'GG Brier':>10} {'GG LL':>9}   {'diff vs A':>10}")
    base = None
    for tag in ["STATIC", "A_current", "B_self_anchor", "C_no_shrink",
                "D_min0", "E_round_none", "F_season", "G_policy",
                "H_incl_day", "I_inseason_w19"]:
        b = brier(tag + "_po", "real_uo", "OVER")
        ll = logloss(tag + "_po", "real_uo", "OVER")
        bg = brier(tag + "_gg", "real_gg", "GG")
        lg = logloss(tag + "_gg", "real_gg", "GG")
        if tag == "A_current":
            base = b
        d = "" if base is None else f"{b - base:+.6f}"
        print(f"{tag:<16} {b:>12.6f} {ll:>10.6f} {bg:>10.6f} {lg:>9.6f}   {d:>10}")

    print("\nRiferimento: round precedente 'PT-19 full' = 0.2523; "
          "audit corrente PT19 (no cap) = 0.2563; STATIC audit = 0.2523.")
    # quante previsioni differiscono tra A e ciascuna variante
    print("\nPartite con previsione O/U diversa da A_current:")
    for tag in ["STATIC", "B_self_anchor", "C_no_shrink", "D_min0",
                "E_round_none", "F_season", "G_policy", "H_incl_day",
                "I_inseason_w19"]:
        n = int(((res["A_current_po"] - res[tag + "_po"]).abs() > 1e-12).sum())
        print(f"  {tag:<16} {n}/{len(res)}")


if __name__ == "__main__":
    main()
