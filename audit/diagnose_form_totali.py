"""
diagnose_form_totali.py — La forma (ultime 5 gare) aiuta o danneggia la testa
Totali (O/U2.5 e GG/NG) dell'architettura a Due Teste?

Walk-forward no-leakage sulle 5 leghe, VALIDATION 2024/25 + TEST 2025/26.
Replica in sola lettura la logica di get_league_engine() (app.py) per la testa
Totali (lambda BASE, M=1): xG stagionale come fonte primaria (fallback gol),
clip lambda [exp(-6), exp(3)], Poisson indipendente.

Modelli confrontati (solo testa Totali, la testa 1X2 non e' toccata):
  A. TOTALI_CON_FORMA : att0/def0 = xG/gol * forma ult.5 (clip [0.85, 1.15])
  B. TOTALI_SENZA_FORMA: att0/def0 = xG/gol puri (baseline lungo periodo)

Metriche: Brier e LogLoss su O/U2.5 e GG/NG, per lega e per stagione
(5 leghe x 2 stagioni x 2 mercati x 2 metriche = 40 confronti) + aggregato.

NON tocca SoccerMath/app.py, config.py, models/.
Output: audit/results/form_totali_diagnosis.md
"""
import os
import sys
import math
import json
from collections import deque
import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from backtest_experiment_all import load_league, get_full_poisson, LEAGUES  # sola lettura

XG_FILES = {
    "Serie A": "xg_serie_a.json",
    "Premier League": "xg_premier_league.json",
    "La Liga": "xg_la_liga.json",
    "Bundesliga": "xg_bundesliga.json",
    "Ligue 1": "xg_ligue_1.json",
}
DB = os.path.join(_REPO_ROOT, "SoccerMath", "database")
SEASONS_EVAL = ("2024/25", "2025/26")
LAM_LO = math.exp(-6.0)
LAM_HI = math.exp(3.0)

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "form_totali_diagnosis.md")


class TeamState:
    __slots__ = ("hgf", "hga", "hgn", "agf", "aga", "agn", "last5")

    def __init__(self):
        self.hgf = self.hga = 0.0; self.hgn = 0
        self.agf = self.aga = 0.0; self.agn = 0
        self.last5 = deque(maxlen=5)

    def observe_home(self, fthg, ftag):
        self.hgf += fthg; self.hga += ftag; self.hgn += 1
        self.last5.append((fthg, ftag))

    def observe_away(self, fthg, ftag):
        self.agf += ftag; self.aga += fthg; self.agn += 1
        self.last5.append((ftag, fthg))


def clip(x):
    return max(LAM_LO, min(LAM_HI, x))


def load_xg(camp_key):
    path = os.path.join(DB, XG_FILES[camp_key])
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f) or {}


def run_models(df, xg_data):
    xg_att, xg_def = {}, {}
    if xg_data and len(xg_data) >= 10:
        vals = list(xg_data.values())
        league_xg = float(np.mean([v["xG_avg"] for v in vals]))
        league_xga = float(np.mean([v["xGA_avg"] for v in vals]))
        if league_xg and league_xga:
            for t, v in xg_data.items():
                xg_att[t] = v["xG_avg"] / league_xg
                xg_def[t] = v["xGA_avg"] / league_xga

    state = {}
    tot_hg = tot_ag = tot_n = 0.0
    rows = []

    def get(t):
        if t not in state:
            state[t] = TeamState()
        return state[t]

    for _, row in df.iterrows():
        fthg = int(row.FTHG); ftag = int(row.FTAG)
        h, a = row.HomeClean, row.AwayClean
        sh, sa = get(h), get(a)
        avg_h = max(tot_hg / tot_n, 0.1) if tot_n else 0.1
        avg_a = max(tot_ag / tot_n, 0.1) if tot_n else 0.1

        def form_fac(ts):
            if len(ts.last5) < 3:
                return 1.0, 1.0
            n = len(ts.last5)
            gf = sum(x[0] for x in ts.last5); ga = sum(x[1] for x in ts.last5)
            den = max((avg_h + avg_a) / 2.0, 0.5)
            return (max(0.85, min(1.15, (gf / n) / den)),
                    max(0.85, min(1.15, (ga / n) / den)))

        def prim_att(t, ts):
            if t in xg_att:
                return xg_att[t]
            return (ts.hgf / ts.hgn) / avg_h if ts.hgn else 1.0

        def prim_def(t, ts):
            if t in xg_def:
                return xg_def[t]
            return (ts.hga / ts.hgn) / avg_a if ts.hgn else 1.0

        if row.season in SEASONS_EVAL:
            p_att_h, p_def_h = prim_att(h, sh), prim_def(h, sh)
            p_att_a, p_def_a = prim_att(a, sa), prim_def(a, sa)
            f_att_h, f_def_h = form_fac(sh)
            f_att_a, f_def_a = form_fac(sa)

            # A: con forma
            lam_f_h = clip(p_att_h * f_att_h * p_def_a * f_def_a * avg_h)
            lam_f_a = clip(p_att_a * f_att_a * p_def_h * f_def_h * avg_a)
            # B: senza forma (baseline pura)
            lam_p_h = clip(p_att_h * p_def_a * avg_h)
            lam_p_a = clip(p_att_a * p_def_h * avg_a)

            m_f = get_full_poisson(lam_f_h, lam_f_a)
            m_p = get_full_poisson(lam_p_h, lam_p_a)
            rows.append({
                "season": row.season,
                "real_over": int(fthg + ftag > 2.5),
                "real_gg": int(fthg > 0 and ftag > 0),
                "form_po": 1 - m_f["u25"], "form_gg": m_f["gg"],
                "pure_po": 1 - m_p["u25"], "pure_gg": m_p["gg"],
                "form_lam_tot": lam_f_h + lam_f_a,
                "pure_lam_tot": lam_p_h + lam_p_a,
                "real_tot": fthg + ftag,
            })

        tot_hg += fthg; tot_ag += ftag; tot_n += 1
        sh.observe_home(fthg, ftag); sa.observe_away(fthg, ftag)

    return pd.DataFrame(rows)


def brier_ll(p, y):
    p = np.asarray(p, dtype=float); y = np.asarray(y, dtype=int)
    pc = np.clip(p, 1e-12, 1 - 1e-12)
    return (float(np.mean((y - p) ** 2)),
            float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc))))


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    per_league = {}
    for prefix, camp_key in LEAGUES:
        per_league[camp_key] = run_models(load_league(prefix), load_xg(camp_key))
    agg = pd.concat(per_league.values(), ignore_index=True)

    wins = 0; total = 0
    lines = ["# Forma (ult. 5) nella testa Totali: CON vs SENZA", "",
             "Walk-forward no-leakage, 5 leghe, VALIDATION 2024/25 + TEST 2025/26. "
             "Testa Totali (lambda BASE, M=1) con xG stagionale primario e clip lambda "
             "[exp(-6), exp(3)]. A = xG/gol * forma ult.5 (clip [0.85,1.15]); "
             "B = xG/gol puri (baseline di lungo periodo). Delta = B - A "
             "(negativo = rimuovere la forma migliora).", ""]

    def section(name, d):
        nonlocal wins, total
        out = [f"\n## {name.upper()}  (VAL {len(d[d.season=='2024/25'])} + TEST {len(d[d.season=='2025/26'])} partite)", "",
               "| Stagione | Mercato | Metrica | A CON forma | B SENZA forma | Delta | Migliore |",
               "|---|---|---|---|---|---|---|"]
        for s in SEASONS_EVAL:
            sub = d[d.season == s]
            for mkt, pf, pp, yc in [("O/U2.5", "form_po", "pure_po", "real_over"),
                                    ("GG/NG", "form_gg", "pure_gg", "real_gg")]:
                bf, lf = brier_ll(sub[pf], sub[yc]); bp, lp = brier_ll(sub[pp], sub[yc])
                for metric, va, vb in [("Brier", bf, bp), ("LogLoss", lf, lp)]:
                    better = "SENZA" if vb < va else ("CON" if va < vb else "=")
                    if name != "AGGREGATO":
                        total += 1; wins += int(vb < va)
                    out.append(f"| {s} | {mkt} | {metric} | {va:.4f} | {vb:.4f} | {vb-va:+.4f} | {better} |")
        sd_f = d["form_lam_tot"].std(); sd_p = d["pure_lam_tot"].std(); sd_r = d["real_tot"].std()
        out += ["", f"Std lambda totale: CON forma {sd_f:.3f} | SENZA forma {sd_p:.3f} | "
                    f"gol reali {sd_r:.3f}. Media lambda totale: CON {d['form_lam_tot'].mean():.3f} | "
                    f"SENZA {d['pure_lam_tot'].mean():.3f} | reale {d['real_tot'].mean():.3f}."]
        return out

    for camp_key in per_league:
        lines += section(camp_key, per_league[camp_key])
    lines += section("AGGREGATO", agg)

    bo_f, _ = brier_ll(agg["form_po"], agg["real_over"]); bo_p, _ = brier_ll(agg["pure_po"], agg["real_over"])
    bg_f, _ = brier_ll(agg["form_gg"], agg["real_gg"]); bg_p, _ = brier_ll(agg["pure_gg"], agg["real_gg"])
    lines += ["", "## Sintesi", "",
              f"- Confronti (lega x stagione x mercato x metrica) in cui SENZA forma batte CON forma: **{wins}/{total}**.",
              f"- Brier O/U2.5 aggregato (V+T, 5 leghe): {bo_f:.4f} -> {bo_p:.4f}.",
              f"- Brier GG/NG aggregato (V+T, 5 leghe): {bg_f:.4f} -> {bg_p:.4f}.",
              "", "### Raccomandazione", "",
              "Rimuovere `form_att`/`form_def` dal calcolo di `att0`/`def0` in "
              "`get_league_engine()` (app.py): la testa Totali deve usare la baseline "
              "pura di lungo periodo. La forma resta nella testa 1X2 (`att`/`def`)."]
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[-8:]))
    print(f"\nReport: {OUT_PATH}")


if __name__ == "__main__":
    main()
