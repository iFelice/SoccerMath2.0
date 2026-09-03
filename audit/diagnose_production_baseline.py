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
  5. PROD_DC / PROD_NORM_DC (Alternativa 2: Dixon-Coles): gli stessi lambda di
     PRODUZIONE ATTUALE / PRODUZIONE_NORM_SUM passano in build_matrix() che applica la
     correzione bivariata tau(x,y,lambda_h,lambda_a,rho) di Dixon-Coles (1997) alle 4
     celle basse (0-0,1-0,0-1,1-1) e rinormalizza la matrice a somma 1. rho e' stimato
     con MLE (stessa funzione di diagnose_dixon_coles_rho.py) SOLO sul training
     2022/23+2023/24, per ogni lega, usando i lambda della PRODUZIONE ATTUALE.
  6. PRODUZIONE_DUE_TESTE (Alternativa 3: architettura a due teste): le probabilita'
     1X2 vengono prese dal modello PRODUZIONE_NORM_SUM (xG + forma + mercato
     normalizzato); le probabilita' Over/Under 2.5 e GG/NG vengono prese da una matrice
     costruita con i lambda BASE senza fattore mercato (M=1, solo xG/gol storici +
     forma/medie di lega).
  7. PRODUZIONE_DUE_TESTE_DC: come DUE_TESTE, ma sulla sola testa Totali viene applicata
     la correzione Dixon-Coles (rho MLE per lega) prima di ricavare O/U2.5 e GG/NG.

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
from diagnose_dixon_coles_rho import (build_matrix, market_probs_from_matrix,
                                      estimate_rho)

XG_FILES = {
    "Serie A": "xg_serie_a.json",
    "Premier League": "xg_premier_league.json",
    "La Liga": "xg_la_liga.json",
    "Bundesliga": "xg_bundesliga.json",
    "Ligue 1": "xg_ligue_1.json",
}
DB = os.path.join(_REPO_ROOT, "SoccerMath", "database")
SEASONS_EVAL = ("2024/25", "2025/26")
TRAIN_SEASONS = ("2022/23", "2023/24")
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
    """Walk-forward no-leakage a passata singola. Ritorna DataFrame con prob. dei
    modelli (audit, audit+clip, produzione, produzione_norm_sum, prod_dc,
    prod_norm_dc) + real outcome + quote raw per le stagioni di eval.

    rho Dixon-Coles viene stimato con MLE SOLO sulle stagioni di training
    (2022/23+2023/24) precedenti alla validation, usando i lambda di
    PRODUZIONE ATTUALE (stessa generazione no-leakage dell'eval), poi applicato
    costante alle correzioni DC su validation+test."""
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
    # campione di training per MLE di rho (lambda produzione, no-leakage)
    train_lh, train_la, train_x, train_y = [], [], [], []
    rho = 0.0

    def get(t):
        if t not in state:
            state[t] = TeamState()
        return state[t]

    def clip(x):
        return max(LAM_LO, min(LAM_HI, x))

    for _, row in df.iterrows():
        fthg = int(row.FTHG); ftag = int(row.FTAG)
        ftr = str(row.FTR).strip().upper()
        h, a = row.HomeClean, row.AwayClean
        sh = get(h); sa = get(a)

        avg_h = max(tot_hg / tot_n, 0.1) if tot_n else 0.1
        avg_a = max(tot_ag / tot_n, 0.1) if tot_n else 0.1

        # --- rapporti combinati solo-gol (baseline audit) ---
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

        if row.season in TRAIN_SEASONS:
            # training per MLE rho (lambda produzione attuale, clippati)
            train_lh.append(lam_prod_h); train_la.append(lam_prod_a)
            train_x.append(fthg); train_y.append(ftag)
        elif row.season in SEASONS_EVAL:
            # stima rho una sola volta: tutto il training (pre-eval) e'' gia'' visto
            if train_lh:
                tr = pd.DataFrame({"lambda_h": train_lh, "lambda_a": train_la,
                                   "FTHG": train_x, "FTAG": train_y})
                rho = estimate_rho(tr)
                train_lh = []   # non ri-stimare alle righe eval successive

            m_aud = get_full_poisson(lam_aud_h, lam_aud_a)
            m_audc = get_full_poisson(lam_audc_h, lam_audc_a)
            m_prod = get_full_poisson(lam_prod_h, lam_prod_a)
            m_prodn = get_full_poisson(lam_ns_h, lam_ns_a)

            # --- Dixon-Coles: matrice + tau su 4 celle basse, rinorm, con rho ---
            mp_dc = market_probs_from_matrix(build_matrix(lam_prod_h, lam_prod_a, rho))
            mp_dcn = market_probs_from_matrix(build_matrix(lam_ns_h, lam_ns_a, rho))

            # --- Testa Totali (O/U2.5 e GG/NG): lambda BASE senza fattore mercato
            # (M=1, solo xG/gol + forma), clippati per la matrice ---
            cb_h = clip(lam_base_h); cb_a = clip(lam_base_a)
            m_base = get_full_poisson(cb_h, cb_a)
            mp_bdc = market_probs_from_matrix(build_matrix(cb_h, cb_a, rho))

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
                "proddc_1": mp_dc["1"], "proddc_X": mp_dc["X"], "proddc_2": mp_dc["2"],
                "proddc_po": mp_dc["o25"], "proddc_gg": mp_dc["gg"],
                "prodndc_1": mp_dcn["1"], "prodndc_X": mp_dcn["X"],
                "prodndc_2": mp_dcn["2"], "prodndc_po": mp_dcn["o25"],
                "prodndc_gg": mp_dcn["gg"],
                # Due teste: 1X2 da NORM_SUM; O/U e GG/NG dalla testa BASE (M=1)
                "duet_1": m_prodn["1"], "duet_X": m_prodn["X"], "duet_2": m_prodn["2"],
                "duet_po": 1 - m_base["u25"], "duet_gg": m_base["gg"],
                # Due teste + DC sulla sola testa Totali
                "duetdc_1": m_prodn["1"], "duetdc_X": m_prodn["X"],
                "duetdc_2": m_prodn["2"], "duetdc_po": mp_bdc["o25"],
                "duetdc_gg": mp_bdc["gg"],
                "B365H": row.B365H, "B365D": row.B365D, "B365A": row.B365A,
                "AvgH": row.AvgH, "AvgD": row.AvgD, "AvgA": row.AvgA,
                "B365o": row["B365>2.5"], "B365u": row["B365<2.5"],
                "Avgo": row["Avg>2.5"], "Avgu": row["Avg<2.5"],
            })

        # aggiornamento stato dopo la previsione (no-leakage)
        tot_hg += fthg; tot_ag += ftag; tot_n += 1
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
              ("PRODUZIONE ATTUALE", "prod"), ("PRODUZIONE_NORM_SUM", "prodn"),
              ("PROD_DC", "proddc"), ("PROD_NORM_DC", "prodndc"),
              ("PRODUZIONE_DUE_TESTE", "duet"),
              ("PRODUZIONE_DUE_TESTE_DC", "duetdc")]
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


def build_ranking(d):
    """Sintesi comparativa AGGREGATA (tutte le alternative) ordinata per Brier 1X2 V.
    Ritorna (righe_markdown, raccomandazione). d deve avere gia' le colonne fair+modelli."""
    models = [("AUDIT solo-gol", "aud"), ("AUDIT + CLIP", "audc"),
              ("PRODUZIONE ATTUALE", "prod"), ("PRODUZIONE_NORM_SUM", "prodn"),
              ("PROD_DC", "proddc"), ("PROD_NORM_DC", "prodndc"),
              ("PRODUZIONE_DUE_TESTE", "duet"),
              ("PRODUZIONE_DUE_TESTE_DC", "duetdc")]
    rows = []
    for name, mp in models:
        dV = d[d["season"] == "2024/25"]
        dT = d[d["season"] == "2025/26"]
        b1V, _ = brier_ll_1x2(dV, (f"{mp}_1", f"{mp}_X", f"{mp}_2"))
        b1T, _ = brier_ll_1x2(dT, (f"{mp}_1", f"{mp}_X", f"{mp}_2"))
        bOV, _ = brier_ll_bin(dV, f"{mp}_po", "real_uo", "OVER")
        bOT, _ = brier_ll_bin(dT, f"{mp}_po", "real_uo", "OVER")
        bGV, _ = brier_ll_bin(dV, f"{mp}_gg", "real_gg", "GG")
        bGT, _ = brier_ll_bin(dT, f"{mp}_gg", "real_gg", "GG")
        r1V = roi_1x2(dV, (f"{mp}_1", f"{mp}_X", f"{mp}_2"),
                      ("fair_b365_1", "fair_b365_X", "fair_b365_2"),
                      ("B365H", "B365D", "B365A"))[2]
        r1T = roi_1x2(dT, (f"{mp}_1", f"{mp}_X", f"{mp}_2"),
                      ("fair_b365_1", "fair_b365_X", "fair_b365_2"),
                      ("B365H", "B365D", "B365A"))[2]
        rows.append([name, b1V, b1T, bOV, bOT, bGV, bGT, r1V, r1T])
    rows.sort(key=lambda r: r[1])  # per Brier 1X2 V
    lines = []
    lines.append("| Modello | Brier 1X2 V | Brier 1X2 T | Brier O/U V | Brier O/U T | "
                 "Brier GG V | Brier GG T | ROI 1X2 V% | ROI 1X2 T% |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        lines.append(f"| {r[0]} | {r[1]:.4f} | {r[2]:.4f} | {r[3]:.4f} | {r[4]:.4f} | "
                     f"{r[5]:.4f} | {r[6]:.4f} | {r[7]:.2f} | {r[8]:.2f} |")

    # raccomandazione ingegneristica basata sui numeri dell'AGGREGATO
    best1 = min(rows, key=lambda r: (r[1], r[7]))            # 1X2: Brier V poi ROI V
    bestou = min(rows, key=lambda r: (r[3], r[5]))           # O/U: Brier V
    bestgg = min(rows, key=lambda r: (r[5], r[3]))           # GG: Brier V
    rec = (f"Su AGGREGATO (3.504 partite): miglior 1X2 = {best1[0]} "
           f"(Brier V {best1[1]:.4f}, ROI 1X2 V {best1[7]:+.2f}%); "
           f"miglior O/U2.5 = {bestou[0]} (Brier V {bestou[3]:.4f}); "
           f"miglior GG/NG = {bestgg[0]} (Brier V {bestgg[5]:.4f}). "
           f"Se un unico modello domina su 1X2, O/U e GG si puo' implementare in "
           f"SoccerMath/app.py; altrimenti adottare l'architettura a due teste "
           f"(1X2 da NORM_SUM, Totali da base senza mercato).")
    return lines, rec


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
                 "PRODUZIONE_NORM_SUM (somma attesa normalizzata senza mercato) | "
                 "PROD_DC / PROD_NORM_DC (come i due precedenti ma con correzione "
                 "Dixon-Coles tau(x,y,rho) sulle 4 celle basse e rinormalizzazione; "
                 "rho stimato via MLE solo su training 2022/23+2023/24 per lega) | "
                 "PRODUZIONE_DUE_TESTE (1X2 da NORM_SUM, O/U2.5 e GG/NG da lambda base "
                 "senza mercato M=1) e PRODUZIONE_DUE_TESTE_DC (idem + Dixon-Coles solo "
                 "sulla testa Totali).")
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

    dA = add_fair(agg_all)
    rank_lines, rec = build_ranking(dA)
    lines.append("\n## SINTESI — CLASSIFICA COMPARATIVA (AGGREGATO 5 LEGHE)")
    lines.append("")
    lines.append("Ranking delle alternative per Brier 1X2 Validation; per ogni modello "
                 "sono riportati anche O/U2.5, GG/NG e ROI 1X2 (Bet365).")
    lines.append("")
    lines.extend(rank_lines)
    lines.append("")
    lines.append("### Raccomandazione ingegneristica per SoccerMath/app.py")
    lines.append("")
    lines.append(rec)
    lines.append("")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Scritto: {OUT_PATH}")


if __name__ == "__main__":
    main()
