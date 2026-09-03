"""
diagnose_production_baseline.py — Misura la VERA baseline di produzione e la
confronta con la baseline audit "solo-gol", walk-forward no-leakage sulle 5 leghe
(validation 2024/25 + test 2025/26).

NON tocca SoccerMath/app.py, config.py, models/: importa in sola lettura
load_league/get_full_poisson/devig_1x2/devig_2way/LEAGUES e MARKET_VALUES da
backtest_experiment_all.py (a sua volta sola lettura), leggendo in sola lettura
anche i CSV e i JSON xG.

Modelli confrontati:
  1. BASELINE AUDIT (solo-gol): la euristica team_attr di backtest_experiment_all.py
     (media cumulativa home/away goals for/against / medie di lega), nessun mercato,
     nessuna forma, nessun xG, nessun clip lambda.
  2. BASELINE AUDIT + CLIP: idem, ma lambda clippato in [exp(-6), exp(3)] prima di
     get_full_poisson().
  3. BASELINE PRODUZIONE REALE: replica no-leakage della logica di get_league_engine()
     in app.py:
       - xG stagionale (xG_avg/xGA_avg da xg_<lega>.json) come fonte primaria del
         rapporto attacco/difesa relativo; fallback sui gol se il team manca dall'xG.
       - forma ultime 5 partite (clip [0.85, 1.15]).
       - fattore valore di mercato logaritmico (MARKET_VALUES, clip [0.85, 1.25]).
       - clip lambda [exp(-6), exp(3)] in ingresso a get_full_poisson().
  4. PRODUZIONE_NORM_SUM (Alternativa 1: normalizzazione della somma gol): stessi input
     della PRODUZIONE, ma dopo il calcolo i lambda con mercato lambda_H^mkt/lambda_A^mkt
     vengono riassegnati in proporzione su una somma attesa target
     S = lambda_H^base + lambda_A^base (con M=1, forma/xG invariati):
       lambda_H* = S * lambda_H^mkt / (lambda_H^mkt + lambda_A^mkt)
       lambda_A* = S * lambda_A^mkt / (lambda_H^mkt + lambda_A^mkt)
     Poi clip lambda [exp(-6), exp(3)] in ingresso a get_full_poisson(). Rimuove il
     gonfiaggio sistematico della somma attesa negli scontri di fascia (1/M su attacco
     e M su difesa), senza alterare la frazione 1X2 del modello.

Metriche (per modello, per lega e aggregato): Brier/LogLoss su 1X2, Over/Under 2.5,
GG/NG; ROI e Win Rate su quota reale pre-match (Bet365 e Average) con edge > 0%.
Output: audit/results/production_baseline_comparison.md
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

from backtest_experiment_all import (load_league, get_full_poisson, devig_1x2,
                                     devig_2way, LEAGUES, MARKET_VALUES)

XG_FILES = {
    "Serie A": "xg_serie_a.json",
    "Premier League": "xg_premier_league.json",
    "La Liga": "xg_la_liga.json",
    "Bundesliga": "xg_bundesliga.json",
    "Ligue 1": "xg_ligue_1.json",
}
DB = os.path.join(_REPO_ROOT, "SoccerMath", "database")
SEASONS_EVAL = ("2024/25", "2025/26")
LAM_LO = math.exp(-6.0)   # 0.00247875
LAM_HI = math.exp(3.0)    # 20.08554

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "production_baseline_comparison.md")


class TeamState:
    """Aggregati per-team no-leakage: cumulative home/away + ultime 5."""
    __slots__ = ("hgf", "hga", "hgn", "agf", "aga", "agn", "last5")

    def __init__(self):
        self.hgf = 0.0   # gol fatti giocando in casa (somma FTHG)
        self.hga = 0.0   # gol subiti giocando in casa (somma FTAG)
        self.hgn = 0     # partite in casa
        self.agf = 0.0   # gol fatti in trasferta (somma FTAG)
        self.aga = 0.0   # gol subiti in trasferta (somma FTHG)
        self.agn = 0     # partite in trasferta
        self.last5 = deque(maxlen=5)  # (goals_for, goals_against) dalla prospettiva squadra

    def observe_home(self, fthg, ftag):
        self.hgf += fthg; self.hga += ftag; self.hgn += 1
        self.last5.append((fthg, ftag))

    def observe_away(self, fthg, ftag):
        self.agf += ftag; self.aga += fthg; self.agn += 1
        self.last5.append((ftag, fthg))


def market_factor(val):
    mkt = 1.0 + (math.log10(max(val, 10)) - 2.0) / 4.0
    return max(0.85, min(1.25, mkt))


def run_models(df, league, xg_data):
    """Walk-forward no-leakage a passata singola. Ritorna DataFrame con prob. dei 3
    modelli + real outcome + quote raw per le stagioni di eval."""
    use_xg_league = False
    xg_att = {}
    xg_def = {}
    if xg_data and len(xg_data) >= 10:
        vals = list(xg_data.values())
        league_xg = float(np.mean([v["xG_avg"] for v in vals]))
        league_xga = float(np.mean([v["xGA_avg"] for v in vals]))
        if league_xg and league_xga:
            use_xg_league = True
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
        ftr = str(row.FTR).strip().upper()

        avg_h = max(tot_hg / tot_n, 0.1) if tot_n else 0.1
        avg_a = max(tot_ag / tot_n, 0.1) if tot_n else 0.1

        if row.season in SEASONS_EVAL:
            h, a = row.HomeClean, row.AwayClean
            sh = get(h); sa = get(a)

            # --- rapporti combinati solo-gol (baseline audit, come run_walkforward) ---
            att_h_r = (sh.hgf / sh.hgn) / avg_h if sh.hgn else 1.0
            def_h_r = (sh.hga / sh.hgn) / avg_a if sh.hgn else 1.0
            att_a_r = (sh.agf / sh.agn) / avg_a if sh.agn else 1.0
            def_a_r = (sh.aga / sh.agn) / avg_h if sh.agn else 1.0
            att2_h_r = (sa.hgf / sa.hgn) / avg_h if sa.hgn else 1.0
            def2_h_r = (sa.hga / sa.hgn) / avg_a if sa.hgn else 1.0
            att2_a_r = (sa.agf / sa.agn) / avg_a if sa.agn else 1.0
            def2_a_r = (sa.aga / sa.agn) / avg_h if sa.agn else 1.0

            aud_att_h = (att_h_r + att_a_r) / 2.0
            aud_def_h = (def_h_r + def_a_r) / 2.0
            aud_att_a = (att2_h_r + att2_a_r) / 2.0
            aud_def_a = (def2_h_r + def2_a_r) / 2.0

            # --- forma ultime 5 ---
            def form_fac(tstate):
                if len(tstate.last5) < 3:
                    return 1.0, 1.0
                n = len(tstate.last5)
                gf = sum(x[0] for x in tstate.last5)
                ga = sum(x[1] for x in tstate.last5)
                avg_glob = (avg_h + avg_a) / 2.0
                den = max(avg_glob, 0.5)
                return max(0.85, min(1.15, (gf / n) / den)), \
                       max(0.85, min(1.15, (ga / n) / den))

            form_att_h, form_def_h = form_fac(sh)
            form_att_a, form_def_a = form_fac(sa)
            mkt_h = market_factor(MARKET_VALUES.get(h, 50))
            mkt_a = market_factor(MARKET_VALUES.get(a, 50))

            # --- fonte primaria: xG stagionale, fallback gol (lato casa) ---
            def prim_att(t, tstate):
                if use_xg_league and t in xg_att:
                    return xg_att[t]
                return (tstate.hgf / tstate.hgn) / avg_h if tstate.hgn else 1.0

            def prim_def(t, tstate):
                if use_xg_league and t in xg_def:
                    return xg_def[t]
                return (tstate.hga / tstate.hgn) / avg_a if tstate.hgn else 1.0

            p_att_h = prim_att(h, sh); p_def_h = prim_def(h, sh)
            p_att_a = prim_att(a, sa); p_def_a = prim_def(a, sa)

            prod_att_h = p_att_h * form_att_h * mkt_h
            prod_def_h = p_def_h * form_def_h / mkt_h
            prod_att_a = p_att_a * form_att_a * mkt_a
            prod_def_a = p_def_a * form_def_a / mkt_a

            def clip(x):
                return max(LAM_LO, min(LAM_HI, x))

            # baseline solo-gol (AUDIT) e con clip lambda
            lam_aud_h = aud_att_h * aud_def_a * avg_h
            lam_aud_a = aud_att_a * aud_def_h * avg_a
            lam_audc_h = clip(lam_aud_h); lam_audc_a = clip(lam_aud_a)

            # lambda mercato applicato (non clippati) -> PRODUZIONE
            lam_prod_h_raw = prod_att_h * prod_def_a * avg_h
            lam_prod_a_raw = prod_att_a * prod_def_h * avg_a
            lam_prod_h = clip(lam_prod_h_raw)
            lam_prod_a = clip(lam_prod_a_raw)

            # ---- PRODUZIONE_NORM_SUM (Alternativa 1: normalizzazione somma gol) ----
            # lambda base SENZA fattore mercato (M=1), forma e xG invariati:
            base_att_h = p_att_h * form_att_h          # senza * mkt_h
            base_def_h = p_def_h * form_def_h          # senza / mkt_h
            base_att_a = p_att_a * form_att_a
            base_def_a = p_def_a * form_def_a
            lam_base_h = base_att_h * base_def_a * avg_h
            lam_base_a = base_att_a * base_def_h * avg_a
            S = lam_base_h + lam_base_a                # somma attesa target
            den = lam_prod_h_raw + lam_prod_a_raw
            if den > 0:
                lam_ns_h = S * lam_prod_h_raw / den    # riassegna la proporzione
                lam_ns_a = S * lam_prod_a_raw / den
            else:
                lam_ns_h, lam_ns_a = lam_base_h, lam_base_a
            lam_ns_h = clip(lam_ns_h); lam_ns_a = clip(lam_ns_a)

            m_aud = get_full_poisson(lam_aud_h, lam_aud_a)
            m_audc = get_full_poisson(lam_audc_h, lam_audc_a)
            m_prod = get_full_poisson(lam_prod_h, lam_prod_a)
            m_prodn = get_full_poisson(lam_ns_h, lam_ns_a)

            real_1x2 = {"H": "1", "D": "X", "A": "2"}.get(ftr, "X")
            real_uo = "OVER" if (fthg + ftag) > 2.5 else "UNDER"
            real_gg = "GG" if fthg > 0 and ftag > 0 else "NG"

            rows.append({
                "season": row.season,
                "real_1x2": real_1x2, "real_uo": real_uo, "real_gg": real_gg,
                "aud_1": m_aud["1"], "aud_X": m_aud["X"], "aud_2": m_aud["2"],
                "aud_po": 1 - m_aud["u25"], "aud_gg": m_aud["gg"],
                "audc_1": m_audc["1"], "audc_X": m_audc["X"], "audc_2": m_audc["2"],
                "audc_po": 1 - m_audc["u25"], "audc_gg": m_audc["gg"],
                "prod_1": m_prod["1"], "prod_X": m_prod["X"], "prod_2": m_prod["2"],
                "prod_po": 1 - m_prod["u25"], "prod_gg": m_prod["gg"],
                "prodn_1": m_prodn["1"], "prodn_X": m_prodn["X"], "prodn_2": m_prodn["2"],
                "prodn_po": 1 - m_prodn["u25"], "prodn_gg": m_prodn["gg"],
                "B365H": row.B365H, "B365D": row.B365D, "B365A": row.B365A,
                "AvgH": row.AvgH, "AvgD": row.AvgD, "AvgA": row.AvgA,
                "B365o": row["B365>2.5"], "B365u": row["B365<2.5"],
                "Avgo": row["Avg>2.5"], "Avgu": row["Avg<2.5"],
            })

        # aggiornamento stato dopo la previsione (no-leakage)
        tot_hg += fthg; tot_ag += ftag; tot_n += 1
        h, a = row.HomeClean, row.AwayClean
        get(h).observe_home(fthg, ftag)
        get(a).observe_away(fthg, ftag)

    return pd.DataFrame(rows)


# ---------------- metriche ----------------
def brier_ll_1x2(df, cols):
    p = df[list(cols)].to_numpy(dtype=float)
    m = {"1": 0, "X": 1, "2": 2}
    y = np.array([m[v] for v in df["real_1x2"]])
    n = len(y)
    onehot = np.zeros_like(p); onehot[np.arange(n), y] = 1
    brier = float(np.mean(np.sum((onehot - p) ** 2, axis=1)))
    pc = np.clip(p[np.arange(n), y], 1e-12, 1.0)
    ll = float(-np.mean(np.log(pc)))
    return brier, ll


def brier_ll_bin(df, pcol, real_col, target):
    p = df[pcol].to_numpy(dtype=float)
    y = (df[real_col] == target).astype(int).to_numpy()
    brier = float(np.mean((y - p) ** 2))
    pc = np.clip(p, 1e-12, 1.0)
    ll = float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc)))
    return brier, ll


def roi_1x2(df, cols, fair_odds, odd_odds, stake=10.0):
    p1c, pXc, p2c = cols
    f1c, fXc, f2c = fair_odds
    o1c, oXc, o2c = odd_odds
    outcomes = ["1", "X", "2"]
    bankroll = 0.0; n_bet = 0; wins = 0
    for _, r in df.iterrows():
        probs = {"1": r[p1c], "X": r[pXc], "2": r[p2c]}
        fair = {"1": r[f1c], "X": r[fXc], "2": r[f2c]}
        odds = {"1": r[o1c], "X": r[oXc], "2": r[o2c]}
        if any(pd.isna(v) for v in fair.values()) or any(pd.isna(v) for v in probs.values()):
            continue
        edge = {o: probs[o] - fair[o] for o in outcomes}
        best = max(edge, key=edge.get)
        if edge[best] <= 0.0:
            continue
        n_bet += 1
        won = r["real_1x2"] == best
        profit = stake * (odds[best] - 1) if won else -stake
        wins += won
        bankroll += profit
    roi = (bankroll / (n_bet * stake) * 100) if n_bet else 0.0
    wr = (wins / n_bet * 100) if n_bet else 0.0
    return n_bet, wr, roi


def roi_ou(df, pcol, fair_o, fair_u, odd_o, odd_u, stake=10.0):
    bankroll = 0.0; n_bet = 0; wins = 0
    for _, r in df.iterrows():
        po = r[pcol]
        fo = r[fair_o]; fu = r[fair_u]
        oo = r[odd_o]; ou_ = r[odd_u]
        if any(pd.isna(v) for v in (fo, fu, oo, ou_)):
            continue
        edge_over = po - fo
        if abs(edge_over) <= 0:
            continue
        if edge_over > 0:
            side, odd = "OVER", oo
        else:
            side, odd = "UNDER", ou_
        n_bet += 1
        won = (side == "OVER" and r["real_uo"] == "OVER") or \
              (side == "UNDER" and r["real_uo"] == "UNDER")
        profit = stake * (odd - 1) if won else -stake
        wins += won
        bankroll += profit
    roi = (bankroll / (n_bet * stake) * 100) if n_bet else 0.0
    wr = (wins / n_bet * 100) if n_bet else 0.0
    return n_bet, wr, roi


def add_fair(rl):
    d = rl.copy()
    fb1 = []; fbX = []; fb2 = []; fa1 = []; faX = []; fa2 = []
    fo_o = []; fo_u = []; fg_o = []; fg_u = []
    for _, r in d.iterrows():
        x = devig_1x2(r["B365H"], r["B365D"], r["B365A"])
        fb1.append(x[0] if x else np.nan); fbX.append(x[1] if x else np.nan); fb2.append(x[2] if x else np.nan)
        y = devig_1x2(r["AvgH"], r["AvgD"], r["AvgA"])
        fa1.append(y[0] if y else np.nan); faX.append(y[1] if y else np.nan); fa2.append(y[2] if y else np.nan)
        u = devig_2way(r["B365o"], r["B365u"])
        fo_o.append(u[0] if u else np.nan); fo_u.append(u[1] if u else np.nan)
        v = devig_2way(r["Avgo"], r["Avgu"])
        fg_o.append(v[0] if v else np.nan); fg_u.append(v[1] if v else np.nan)
    d["fair_b365_1"], d["fair_b365_X"], d["fair_b365_2"] = fb1, fbX, fb2
    d["fair_avg_1"], d["fair_avg_X"], d["fair_avg_2"] = fa1, faX, fa2
    d["fair_b365_o"], d["fair_b365_u"] = fo_o, fo_u
    d["fair_avg_o"], d["fair_avg_u"] = fg_o, fg_u
    return d


def build_section(name, rl):
    d = add_fair(rl)
    models = [("AUDIT solo-gol", "aud"), ("AUDIT + CLIP", "audc"),
              ("PRODUZIONE ATTUALE", "prod"), ("PRODUZIONE_NORM_SUM", "prodn")]
    cal = []
    roi = []
    for mname, mp in models:
        for mkt, spec in [("1X2", "1x2"), ("O/U2.5", "ou"), ("GG/NG", "gg")]:
            vals = {}
            for s in SEASONS_EVAL:
                sub = d[d["season"] == s]
                if spec == "1x2":
                    b, ll = brier_ll_1x2(sub, (f"{mp}_1", f"{mp}_X", f"{mp}_2"))
                elif spec == "ou":
                    b, ll = brier_ll_bin(sub, f"{mp}_po", "real_uo", "OVER")
                else:
                    b, ll = brier_ll_bin(sub, f"{mp}_gg", "real_gg", "GG")
                vals[s] = (b, ll)
            cal.append(f"| {mname} | {mkt} | {vals['2024/25'][0]:.4f} | "
                       f"{vals['2024/25'][1]:.4f} | {vals['2025/26'][0]:.4f} | "
                       f"{vals['2025/26'][1]:.4f} |")
        # ROI 1X2
        for src, fair_odds, odd_odds in [
            ("B365", ("fair_b365_1", "fair_b365_X", "fair_b365_2"), ("B365H", "B365D", "B365A")),
            ("Avg", ("fair_avg_1", "fair_avg_X", "fair_avg_2"), ("AvgH", "AvgD", "AvgA")),
        ]:
            out = {}
            for s in SEASONS_EVAL:
                sub = d[d["season"] == s]
                n, wr, rv = roi_1x2(sub, (f"{mp}_1", f"{mp}_X", f"{mp}_2"), fair_odds, odd_odds)
                out[s] = (n, wr, rv)
            roi.append(f"| {mname} | 1X2 | {src} | {out['2024/25'][0]} | "
                       f"{out['2024/25'][1]:.1f} | {out['2024/25'][2]:.2f} | "
                       f"{out['2025/26'][0]} | {out['2025/26'][1]:.1f} | "
                       f"{out['2025/26'][2]:.2f} |")
        # ROI O/U
        for src, fo, fu, oo, ou_ in [
            ("B365", "fair_b365_o", "fair_b365_u", "B365o", "B365u"),
            ("Avg", "fair_avg_o", "fair_avg_u", "Avgo", "Avgu"),
        ]:
            out = {}
            for s in SEASONS_EVAL:
                sub = d[d["season"] == s]
                n, wr, rv = roi_ou(sub, f"{mp}_po", fo, fu, oo, ou_)
                out[s] = (n, wr, rv)
            roi.append(f"| {mname} | O/U2.5 | {src} | {out['2024/25'][0]} | "
                       f"{out['2024/25'][1]:.1f} | {out['2024/25'][2]:.2f} | "
                       f"{out['2025/26'][0]} | {out['2025/26'][1]:.1f} | "
                       f"{out['2025/26'][2]:.2f} |")
    return cal, roi


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    league_results = {}
    for prefix, camp_key in LEAGUES:
        df = load_league(prefix)
        xg_path = os.path.join(DB, XG_FILES[camp_key])
        xg_data = {}
        if os.path.exists(xg_path):
            with open(xg_path, "r", encoding="utf-8") as f:
                xg_data = json.load(f) or {}
        rl = run_models(df, camp_key, xg_data)
        league_results[camp_key] = rl

    agg_all = pd.concat([league_results[camp_key] for _prefix, camp_key in LEAGUES],
                        ignore_index=True)

    lines = []
    lines.append("# Baseline di Produzione vs Baseline Audit (solo-gol)")
    lines.append("")
    lines.append("Walk-forward no-leakage (ogni partita usa solo i dati precedenti). "
                 "Season: VALIDATION 2024/25 e TEST 2025/26. Modelli: "
                 "AUDIT solo-gol | AUDIT+CLIP (lambda clip [exp(-6),exp(3)]) | "
                 "PRODUZIONE ATTUALE (xG stagionale primario + forma ult.5 [0.85,1.15] + "
                 "valore di mercato [0.85,1.25] + clip lambda) | "
                 "PRODUZIONE_NORM_SUM (stessi input di PRODUZIONE ma somma attesa "
                 "normalizzata: S = somma lambda senza mercato, riassegnata in "
                 "proporzione ai lambda con mercato, poi clip lambda).")
    lines.append("")
    lines.append("xG di produzione: snapshot stagionale statico da xg_<lega>.json "
                 "(stesso file letto da get_league_engine); applicato costante alle "
                 "partite, come fa il motore di produzione a un dato istante.")
    lines.append("")
    lines.append("Nota metodologica: lo snapshot xG disponibile riflette la squadra ATTUALE. "
                 "Applicandolo costante alle partite 2024/25 e 2025/26 si introduce "
                 "un'informazione sui punti di forza delle rose odierne applicata a "
                 "stagioni passate: i numeri di PRODUZIONE su queste stagioni vanno quindi "
                 "letti come fedeli alla *struttura* del motore, ma l'eventuale edge/ROI "
                 "in validation non va interpretato come edge out-of-sample reale.")
    lines.append("")

    for prefix, camp_key in LEAGUES:
        rl = league_results[camp_key]
        nV = len(rl[rl["season"] == "2024/25"])
        nT = len(rl[rl["season"] == "2025/26"])
        cal, roi = build_section(camp_key, rl)
        lines.append(f"\n## {camp_key.upper()}  (VAL {nV} + TEST {nT} partite)")
        lines.append("")
        lines.append("### Brier / LogLoss  (V=2024/25, T=2025/26)")
        lines.append("")
        lines.append("| Modello | Mercato | Brier V | LogLoss V | Brier T | LogLoss T |")
        lines.append("|---|---|---|---|---|---|")
        lines.extend(cal)
        lines.append("")
        lines.append("### ROI % / Win rate % (edge>0)  (V=2024/25, T=2025/26)")
        lines.append("")
        lines.append("| Modello | Mercato | Quota | N V | WR V | ROI V | N T | WR T | ROI T |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        lines.extend(roi)
        lines.append("")

    nV = len(agg_all[agg_all["season"] == "2024/25"])
    nT = len(agg_all[agg_all["season"] == "2025/26"])
    calA, roiA = build_section("AGGREGATO 5 LEGHE", agg_all)
    lines.append(f"\n## AGGREGATO — 5 LEGHE  (VAL {nV} + TEST {nT} partite)")
    lines.append("")
    lines.append("### Brier / LogLoss  (V=2024/25, T=2025/26)")
    lines.append("")
    lines.append("| Modello | Mercato | Brier V | LogLoss V | Brier T | LogLoss T |")
    lines.append("|---|---|---|---|---|---|")
    lines.extend(calA)
    lines.append("")
    lines.append("### ROI % / Win rate % (edge>0)  (V=2024/25, T=2025/26)")
    lines.append("")
    lines.append("| Modello | Mercato | Quota | N V | WR V | ROI V | N T | WR T | ROI T |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    lines.extend(roiA)
    lines.append("")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Scritto: {OUT_PATH}")


if __name__ == "__main__":
    main()
