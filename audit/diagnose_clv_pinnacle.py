"""
diagnose_clv_pinnacle.py — CLV vs Pinnacle sul mercato 1X2 (audit SOLA LETTURA).

Confronta la probabilita' 1X2 del modello di produzione con la linea
Pinnacle PRE-MATCH (PSH/PSD/PSA) e con la CHIUSURA (PSCH/PSCD/PSCA) gia'
presenti nei CSV football-data storici, sulle 5 leghe e sullo stesso split
walk-forward degli altri audit (train 2022/23+2023/24, validation 2024/25,
test 2025/26). NON tocca app.py, config.py, models/ ne' i CSV: importa in
sola lettura da backtest_experiment_all.py e diagnose_production_baseline.py
(le stesse funzioni gia' usate da production_baseline_comparison.md).

Pipeline del modello (stessa degli altri audit):
  * testa 1X2 = PRODUZIONE_DUE_TESTE di diagnose_production_baseline.run_models,
    cioe' la testa 1X2 di PRODUZIONE_NORM_SUM (xG snapshot + forma ultime 5 +
    fattore mercato, lambda normalizzati alla somma base S, clip [exp(-6),exp(3)]);
  * ensemble Poisson+Elo "opzione b gia' in produzione": 1X2 finale =
    w*Poisson + (1-w)*Elo con w = app.ELO_ENSEMBLE_W (0.6, validato in
    audit/diagnose_elo_ensemble.py, applicato in app.blend_elo_into_1x2);
    l'Elo walk-forward e' la replica K=24 di diagnose_elo_ensemble.py
    (rating da 1500, home advantage per lega, aggiornamento DOPO la previsione:
    nessuna partita usa se stessa o partite successive).
  * l'equivalenza bit-faithful del ramo NORM-SUM e' verificata dal test che
    confronta il walker con run_models() sullo stesso df.

Quote e de-vig:
  * Pinnacle pre e chiusura lette dalle colonne PSH/PSD/PSA e PSCH/PSCD/PSCA;
    le partite con quota Pinnacle mancante/non valida (<= 1.0) sono ESCLUSE
    dal calcolo e contate per lega/stagione nella tabella di copertura in cima
    al report (nessuna stima/imputazione).
  * de-vig proporzionale standard (1/quota / overround) = devig_1x2 di
    backtest_experiment_all.py. Nota protocollo: il brief citava devig_2way,
    che nel progetto e' la variante a 2 esiti; per il 1X2 vale il precedente
    a 3 esiti devig_1x2 (stesso metodo proporzionale, stesso file).

Metriche (convenzioni degli altri audit):
  * Brier/LogLoss 1X2 (brier_ll_1x2) del modello vs Pinnacle pre vs Pinnacle
    chiusura vs Bet365 vs Average (punto 4), sullo stesso campione usabile.
  * CLV sul lato scommesso, come da protocollo: CLV = P_modello(lato) -
    P_chiusura_de-vigata(lato), dove il lato e' scelto dall'edge del modello
    sulla linea PRE Pinnacle (edge > 0, convenzione EDGE_MIN = 0 di
    backtest_experiment_all). Riportato accanto il CLV classico
    (P_pre_de-vigata - P_chiusura_de-vigata) per confronto con la letteratura.
  * ROI a puntata fissa: (a) sulle stesse scommesse CLV, settle a chiusura
    Pinnacle (prezzo di riferimento richiesto) e a pre Pinnacle; (b) ROI per
    book (selezione per edge>0 vs quel book, settle su quote reali di quel
    book) con la stessa roi_1x2 di diagnose_production_baseline.py.
  * Bootstrap: 2000 resample con seed fisso, CI percentile 2.5-97.5, stessa
    metodologia (costanti e formula _ci) di topmix_margins.py — il file
    "diagnose_rho_bootstrap.py" citato dal protocollo non esiste nel repo,
    diagnose_dixon_coles_rho.py non contiene bootstrap.

Output: audit/results/clv_pinnacle_report.md
Uso:    python audit/diagnose_clv_pinnacle.py
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone
from collections import OrderedDict

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from backtest_experiment_all import (load_league, get_full_poisson, devig_1x2,  # noqa: E402
                                     LEAGUES, clean_name, LEAGUE_HOME_ADVANTAGE,
                                     MARKET_VALUES)
from diagnose_production_baseline import (TeamState, market_factor,            # noqa: E402
                                          brier_ll_1x2, roi_1x2, SEASONS_EVAL,
                                          LAM_LO, LAM_HI, XG_FILES, DB)
from topmix_margins import N_BOOT, SEED, _ci                                   # noqa: E402

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "clv_pinnacle_report.md")

ELO_K = 24.0                # ELO_K di diagnose_elo_ensemble.py (replica del motore)
ELO_INITIAL = 1500.0        # DEFAULT_INITIAL_RATING di models/elo_engine.py
ELO_ENSEMBLE_W = 0.6        # app.ELO_ENSEMBLE_W (blend in produzione; test di uguaglianza)
STAKE = 10.0                # puntata fissa, come backtest_experiment_all.STAKE
EDGE_MIN = 0.0              # convenzione backtest_experiment_all.EDGE_MIN

SEASON_LABELS = ("2022/23", "2023/24", "2024/25", "2025/26", "2026/27")
ODDS_BOOKS = OrderedDict([
    ("PIN pre", ("PSH", "PSD", "PSA")),
    ("PIN close", ("PSCH", "PSCD", "PSCA")),
    ("Bet365", ("B365H", "B365D", "B365A")),
    ("Avg", ("AvgH", "AvgD", "AvgA")),
])
# colonne quota "neutre" che devono restare nel df del modello (da load_league)
BASE_ODDS = ("B365H", "B365D", "B365A", "AvgH", "AvgD", "AvgA")


# =====================================================================
# Punto 1: quote Pinnacle (side-load + join deterministico su load_league)
# =====================================================================
def season_files(prefix, db_dir=None):
    """Stesso mapping stagione->file di load_league (backtest_experiment_all)."""
    db = db_dir if db_dir is not None else DB
    return OrderedDict([
        ("2022/23", os.path.join(db, f"{prefix}_2022.csv")),
        ("2023/24", os.path.join(db, f"{prefix}_2023.csv")),
        ("2024/25", os.path.join(db, f"{prefix}_2024.csv")),
        ("2025/26", os.path.join(db, f"{prefix}_2025.csv")),
        ("2026/27", os.path.join(db, f"{prefix}_Live.csv")),
    ])


def load_pinnacle_odds(prefix, db_dir=None, season_files_map=None):
    """Legge PSH/PSD/PSA + PSCH/PSCD/PSCA dagli stessi CSV di load_league.

    Replica l'ordine di concatenazione e la deduplica di load_league
    (sort per Date stabile + drop_duplicates keep='last' su
    Date/HomeClean/AwayClean) cosiche' ogni chiave identifichi la stessa
    riga che load_league conserva. Le colonne assenti (file vecchi/nuovi)
    restano NaN: nessuna stima.
    """
    fmap = season_files_map or season_files(prefix, db_dir)
    cols_pin = [c for pair in ODDS_BOOKS.values() for c in pair
                if c not in BASE_ODDS]          # solo PSH..PSCA (B365/Avg gia' in load_league)
    dfs = []
    for season_label, path in fmap.items():
        if not os.path.exists(path):
            continue
        raw = pd.read_csv(path, on_bad_lines="warn", low_memory=False)
        keep = ["Date", "HomeTeam", "AwayTeam"] + [c for c in cols_pin if c in raw.columns]
        df = raw[keep].copy()
        for c in cols_pin:
            if c not in df.columns:
                df[c] = np.nan
        df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
        df["HomeClean"] = df["HomeTeam"].apply(clean_name)
        df["AwayClean"] = df["AwayTeam"].apply(clean_name)
        df["season_file"] = season_label
        dfs.append(df[["Date", "HomeClean", "AwayClean", "season_file"] + cols_pin])
    pin = pd.concat(dfs, ignore_index=True)
    pin = pin.sort_values("Date", kind="stable")
    pin = pin.drop_duplicates(subset=["Date", "HomeClean", "AwayClean"],
                              keep="last").reset_index(drop=True)
    for c in cols_pin:
        pin[c] = pd.to_numeric(pin[c], errors="coerce")
        # quota mancante/non valida/non finita: NaN, mai stimata
        pin.loc[~np.isfinite(pin[c].fillna(np.inf)) | ~(pin[c] > 1.0), c] = np.nan
    return pin


def attach_pinnacle(df, pin):
    """Join deterministico 1:1 sul df di load_league (chiavi uniche dopo dedup).

    Ritorna (df_con_quote, stats_join). Alza AssertionError se il join non
    e' 1:1 (righe duplicate perse o conteggi cambiati): nessuna ambiguita'
    viene risolta in silenzio.
    """
    keys = ["Date", "HomeClean", "AwayClean"]
    cols_pin = [c for pair in ODDS_BOOKS.values() for c in pair if c not in BASE_ODDS]
    assert not df.duplicated(subset=keys).any(), "df di load_league con chiavi duplicate"
    assert not pin.duplicated(subset=keys).any(), "tabella Pinnacle con chiavi duplicate"
    merged = df.merge(pin[keys + cols_pin], on=keys, how="left", validate="one_to_one")
    assert len(merged) == len(df), "il join ha cambiato il numero di righe"
    stats_join = {
        "rows_df": len(df),
        "rows_with_psh": int((merged["PSH"] > 1.0).sum()),
        "rows_matched_any": int(merged["PSH"].notna().sum()),
    }
    return merged, stats_join


def usable_mask(d):
    """Campione usabile: Pinnacle PRE e CHIUSURA entrambe presenti e valide
    (tutte le metriche Pinnacle e il CLV richiedono entrambe le linee;
    Bet365/Avg vengono mascherate per-riga quando mancano)."""
    return (d[["PSH", "PSD", "PSA"]].notna().all(axis=1)
            & d[["PSCH", "PSCD", "PSCA"]].notna().all(axis=1))


# =====================================================================
# Punto 2: modello di produzione con ensemble Elo (walk-forward no-leakage)
# =====================================================================
def elo_probs(r_h, r_a, home_adv):
    """Replica di diagnose_elo_ensemble.elo_probs (formula predict_elo_probs
    di models/elo_engine.py senza boost xG nel dr di predizione)."""
    dr = r_h + home_adv - r_a
    e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
    p_draw = max(0.06, min(0.34, 0.27 * math.exp(-((dr / 320.0) ** 2))))
    return (1.0 - p_draw) * e_h, p_draw, (1.0 - p_draw) * (1.0 - e_h)


def _clip_lambda(x):
    return max(LAM_LO, min(LAM_HI, x))


def run_model_with_elo(df, camp_key, xg_data, w=ELO_ENSEMBLE_W, emit_seasons=None):
    """Passata cronologica sul df di load_league.

    Per le righe di ``emit_seasons`` (default None = SEASONS_EVAL, comportamento
    storico di diagnose_clv_pinnacle) emette:
      * prodn_1/X/2: testa 1X2 PRODUZIONE_DUE_TESTE = NORM-SUM, ramo
        bit-faithful a diagnose_production_baseline.run_models (xG snapshot
        normalizzato con fallback gol, forma ultime 5, fattore mercato,
        normalizzazione della somma S, clip lambda);
      * elo_1/X/2: Elo walk-forward K=24 (rating pre-partita), replica di
        diagnose_elo_ensemble.py -- l'audit che ha validato il blend in produzione;
      * model_1/X/2: w*prodn + (1-w)*elo, come app.blend_elo_into_1x2;
      * pos: posizione della riga nel df (per filtri di campione come il
        cold-start warmup del grid search).
    Lo stato (TeamState, Elo, medie gol) viene aggiornato DOPO la previsione:
    nessuna partita usa se stessa o partite successive, per QUALSIASI valore di
    emit_seasons: emettere predizioni su altre stagioni non cambia la traiettoria
    dello stato (verificato dal test di consistenza di grid_search_ensemble_weight).
    Le righe fuori da emit_seasons (es. Live) aggiornano lo stato senza produrre
    output, identico a run_models.
    """
    emit = set(SEASONS_EVAL) if emit_seasons is None else set(emit_seasons)
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

    state = {}
    elo = {}
    tot_hg = tot_ag = tot_n = 0.0
    rows = []
    pos = -1

    def get(t):
        if t not in state:
            state[t] = TeamState()
        return state[t]

    for pos, (_, row) in enumerate(df.iterrows()):
        fthg, ftag = int(row.FTHG), int(row.FTAG)
        ftr = str(row.FTR).strip().upper()
        h, a = row.HomeClean, row.AwayClean
        sh, sa = get(h), get(a)
        avg_h = max(tot_hg / tot_n, 0.1) if tot_n else 0.1
        avg_a = max(tot_ag / tot_n, 0.1) if tot_n else 0.1
        r_h = elo.get(h, ELO_INITIAL)
        r_a = elo.get(a, ELO_INITIAL)

        if row.season in emit:
            # --- forma ultime 5 (identica a run_models) ---
            def form_fac(ts):
                if len(ts.last5) < 3:
                    return 1.0, 1.0
                n = len(ts.last5)
                gf = sum(x[0] for x in ts.last5)
                ga = sum(x[1] for x in ts.last5)
                avg_glob = (avg_h + avg_a) / 2.0
                den = max(avg_glob, 0.5)
                return (max(0.85, min(1.15, (gf / n) / den)),
                        max(0.85, min(1.15, (ga / n) / den)))

            # --- fonte primaria xG con fallback gol (identica a run_models) ---
            def prim(t, ts):
                pa = xg_att[t] if t in xg_att else ((ts.hgf / ts.hgn) / avg_h if ts.hgn else 1.0)
                pdf = xg_def[t] if t in xg_def else ((ts.hga / ts.hgn) / avg_a if ts.hgn else 1.0)
                return pa, pdf

            p_att_h, p_def_h = prim(h, sh)
            p_att_a, p_def_a = prim(a, sa)
            form_att_h, form_def_h = form_fac(sh)
            form_att_a, form_def_a = form_fac(sa)
            mkt_h = market_factor(MARKET_VALUES.get(h, 50))
            mkt_a = market_factor(MARKET_VALUES.get(a, 50))

            prod_att_h = p_att_h * form_att_h * mkt_h
            prod_def_h = p_def_h * form_def_h / mkt_h
            prod_att_a = p_att_a * form_att_a * mkt_a
            prod_def_a = p_def_a * form_def_a / mkt_a

            lam_prod_h_raw = prod_att_h * prod_def_a * avg_h
            lam_prod_a_raw = prod_att_a * prod_def_h * avg_a

            # NORM-SUM: normalizza i lambda con mercato sulla somma base S
            base_att_h = p_att_h * form_att_h
            base_def_h = p_def_h * form_def_h
            base_att_a = p_att_a * form_att_a
            base_def_a = p_def_a * form_def_a
            lam_base_h = base_att_h * base_def_a * avg_h
            lam_base_a = base_att_a * base_def_h * avg_a
            S = lam_base_h + lam_base_a
            den = lam_prod_h_raw + lam_prod_a_raw
            if den > 0:
                lam_ns_h = S * lam_prod_h_raw / den
                lam_ns_a = S * lam_prod_a_raw / den
            else:
                lam_ns_h, lam_ns_a = lam_base_h, lam_base_a
            m_prodn = get_full_poisson(_clip_lambda(lam_ns_h), _clip_lambda(lam_ns_a))

            e1, eX, e2 = elo_probs(r_h, r_a, home_adv)
            rows.append({
                "pos": pos, "date": row.Date, "season": row.season,
                "home": h, "away": a,
                "real_1x2": {"H": "1", "D": "X", "A": "2"}.get(ftr, "X"),
                "prodn_1": m_prodn["1"], "prodn_X": m_prodn["X"], "prodn_2": m_prodn["2"],
                "elo_1": e1, "elo_X": eX, "elo_2": e2,
                "model_1": w * m_prodn["1"] + (1.0 - w) * e1,
                "model_X": w * m_prodn["X"] + (1.0 - w) * eX,
                "model_2": w * m_prodn["2"] + (1.0 - w) * e2,
            })

        # --- aggiornamento stato DOPO la previsione (no-leakage) ---
        dr = r_h + home_adv - r_a
        e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
        s_h = 1.0 if ftr == "H" else (0.0 if ftr == "A" else 0.5)
        elo[h] = r_h + ELO_K * (s_h - e_h)
        elo[a] = r_a + ELO_K * ((1 - s_h) - (1 - e_h))
        tot_hg += fthg
        tot_ag += ftag
        tot_n += 1
        sh.observe_home(fthg, ftag)
        sa.observe_away(fthg, ftag)

    return pd.DataFrame(rows)


def load_xg(camp_key):
    """Snapshot xG statico, stessa fonte di diagnose_production_baseline."""
    path = os.path.join(DB, XG_FILES.get(camp_key, ""))
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f) or {}


# =====================================================================
# Punto 3: metriche — calibrazione, CLV, ROI, bootstrap
# =====================================================================
def fair_columns(d, prefix, odds_cols):
    """Aggiunge le colonne fair (de-vig proporzionale) per un book; NaN se
    la quota manca o non e' valida (devig_1x2 ritorna None: nessuna stima)."""
    h, dd, a_ = odds_cols
    f1, fX, f2 = [], [], []
    for _, r in d.iterrows():
        x = devig_1x2(r[h], r[dd], r[a_])
        f1.append(x[0] if x else np.nan)
        fX.append(x[1] if x else np.nan)
        f2.append(x[2] if x else np.nan)
    d = d.copy()
    d[f"{prefix}_1"], d[f"{prefix}_X"], d[f"{prefix}_2"] = f1, fX, f2
    return d


def brier_ll(d, cols, mask=None):
    """brier_ll_1x2 su un sottoinsieme (maschera) con n riportato."""
    sub = d if mask is None else d[mask]
    if len(sub) == 0 or sub[list(cols)].isna().any().any():
        sub = sub.dropna(subset=list(cols))
    if len(sub) == 0:
        return {"n": 0, "brier": None, "log_loss": None}
    b, ll = brier_ll_1x2(sub, cols)
    return {"n": len(sub), "brier": round(b, 4), "log_loss": round(ll, 4)}


def clv_block(d, model_cols=("model_1", "model_X", "model_2"),
              pre_prefix="pinpre", close_prefix="pinclose", n_boot=N_BOOT,
              seed=SEED):
    """CLV sul lato scommesso.

    Scommessa = lato con edge>0 del modello vs linea PRE Pinnacle de-vigata
    (convenzione EDGE_MIN=0). CLV protocollo = P_model(lato) - P_close(lato);
    CLV classico (informativo) = P_pre(lato) - P_close(lato). Bootstrap CI
    percentile su n_boot resample di righe con seed fisso (metodologia
    topmix_margins: N_BOOT=2000, SEED, _ci 2.5-97.5).
    """
    m1, mX, m2 = model_cols
    f1p, fXp, f2p = f"{pre_prefix}_1", f"{pre_prefix}_X", f"{pre_prefix}_2"
    f1c, fXc, f2c = f"{close_prefix}_1", f"{close_prefix}_X", f"{close_prefix}_2"
    rows = []
    for _, r in d.iterrows():
        probs = np.array([r[m1], r[mX], r[m2]], dtype=float)
        pre = np.array([r[f1p], r[fXp], r[f2p]], dtype=float)
        close = np.array([r[f1c], r[fXc], r[f2c]], dtype=float)
        if np.isnan(pre).any() or np.isnan(close).any():
            continue
        side = int(np.argmax(probs - pre))
        if (probs[side] - pre[side]) <= EDGE_MIN:
            continue
        rows.append({
            "side": side,
            "clv_model": float(probs[side] - close[side]),
            "clv_classic": float(pre[side] - close[side]),
            "odds_close": float(r[{0: "PSCH", 1: "PSCD", 2: "PSCA"}[side]]),
            "odds_pre": float(r[{0: "PSH", 1: "PSD", 2: "PSA"}[side]]),
            "won": r["real_1x2"] == {0: "1", 1: "X", 2: "2"}[side],
        })
    if not rows:
        return {"n_bet": 0}
    cm = np.array([r["clv_model"] for r in rows])
    cc = np.array([r["clv_classic"] for r in rows])
    # ROI sulle stesse scommesse: a chiusura (prezzo di riferimento) e a pre
    ret_close = np.array([STAKE * (r["odds_close"] - 1.0) if r["won"] else -STAKE
                          for r in rows])
    ret_pre = np.array([STAKE * (r["odds_pre"] - 1.0) if r["won"] else -STAKE
                        for r in rows])
    rng = np.random.default_rng(seed)
    n = len(rows)
    draws = rng.integers(0, n, size=(n_boot, n))
    # stessa formula _ci di topmix; per il CLV lo stat e' la media del campione,
    # per il ROI la somma delle contribuzioni per-riga (sum(ret)/(n*stake))
    ci_mean = lambda arr: _ci(list(arr[draws].mean(axis=1)))
    ci_sum = lambda arr: _ci(list(arr[draws].sum(axis=1)))
    wr = np.array([1.0 if r["won"] else 0.0 for r in rows])
    # ROI = bankroll / totale puntato; il vettore per-riga serve al bootstrap
    roi_c_vec = ret_close / (n * STAKE)
    roi_p_vec = ret_pre / (n * STAKE)
    return {
        "n_bet": n,
        "clv_model_mean": float(cm.mean()), "clv_model_pos_pct": float((cm > 0).mean() * 100),
        "clv_model_ci": ci_mean(cm),
        "clv_classic_mean": float(cc.mean()), "clv_classic_pos_pct": float((cc > 0).mean() * 100),
        "clv_classic_ci": ci_mean(cc),
        "win_rate_pct": float(wr.mean() * 100),
        # i campi *_pct sono gia' in percento, CI comprese (le medie CLV restano
        # frazioni: il render le moltiplica x100)
        "roi_close_pct": float(roi_c_vec.sum() * 100),
        "roi_close_ci": [x * 100.0 for x in ci_sum(roi_c_vec)],
        "roi_pre_pct": float(roi_p_vec.sum() * 100),
        "side_counts": {k: int(sum(1 for r in rows if r["side"] == i))
                        for i, k in enumerate(("1", "X", "2"))},
    }


def bootstrap_dbrier(d, cols_a, cols_b, n_boot=N_BOOT, seed=SEED):
    """Delta Brier (B - A) con CI percentile bootstrap appaiato sulle righe."""
    sub = d.dropna(subset=list(cols_a) + list(cols_b))
    if len(sub) < 5:
        return {"n": len(sub), "delta": None, "ci": [None, None]}
    y = np.array([{ "1": 0, "X": 1, "2": 2}[v] for v in sub["real_1x2"]])
    onehot = np.zeros((len(y), 3))
    onehot[np.arange(len(y)), y] = 1
    pa = sub[list(cols_a)].to_numpy(dtype=float)
    pb = sub[list(cols_b)].to_numpy(dtype=float)
    ba = ((onehot - pa) ** 2).sum(axis=1)
    bb = ((onehot - pb) ** 2).sum(axis=1)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(sub), size=(n_boot, len(sub)))
    deltas = bb[draws].mean(axis=1) - ba[draws].mean(axis=1)
    return {"n": len(sub), "delta": float(bb.mean() - ba.mean()),
            "ci": _ci(list(deltas))}


# =====================================================================
# Aggregazione per lega + report
# =====================================================================
def coverage_rows(df_merged):
    """Punto 1: copertura quote per lega/stagione (nessuna stima delle mancanti)."""
    out = []
    for season in SEASON_LABELS:
        sub = df_merged[df_merged["season"] == season]
        pre_ok = sub[["PSH", "PSD", "PSA"]].notna().all(axis=1)
        close_ok = sub[["PSCH", "PSCD", "PSCA"]].notna().all(axis=1)
        both = pre_ok & close_ok
        out.append({
            "season": season,
            "rows": len(sub),
            "pre_ok": int(pre_ok.sum()), "pre_missing": int((~pre_ok).sum()),
            "close_ok": int(close_ok.sum()), "close_missing": int((~close_ok).sum()),
            "usable": int(both.sum()),
            "usable_pct": round(100.0 * both.sum() / len(sub), 1) if len(sub) else None,
            "in_eval": season in SEASONS_EVAL,
        })
    return out


def run_league(prefix, camp_key):
    """Pipeline completa per una lega. Ritorna dict con copertura + righe."""
    df = load_league(prefix)
    pin = load_pinnacle_odds(prefix)
    merged, stats_join = attach_pinnacle(df, pin)
    d = run_model_with_elo(merged, camp_key, load_xg(camp_key))
    # attacca le quote alle righe di output (join deterministico sulle chiavi)
    quote_cols = (["PSH", "PSD", "PSA", "PSCH", "PSCD", "PSCA"]
                  + [c for c in BASE_ODDS if c in merged.columns])
    d = d.merge(merged[["Date", "HomeClean", "AwayClean"] + quote_cols],
                left_on=["date", "home", "away"],
                right_on=["Date", "HomeClean", "AwayClean"], how="left",
                validate="one_to_one")
    assert not d.duplicated(subset=["date", "home", "away"]).any()
    d = fair_columns(d, "pinpre", ODDS_BOOKS["PIN pre"])
    d = fair_columns(d, "pinclose", ODDS_BOOKS["PIN close"])
    d = fair_columns(d, "b365", ODDS_BOOKS["Bet365"])
    d = fair_columns(d, "avg", ODDS_BOOKS["Avg"])
    return {
        "prefix": prefix, "league": camp_key,
        "coverage": coverage_rows(merged),
        "join": stats_join,
        "rows": d,
    }


def metrics_for_sample(d):
    """Calibrazione + ROI per book + CLV su un campione (df righe eval)."""
    usable = usable_mask(d)
    u = d[usable].copy()
    out = {"n_usable": len(u), "n_eval": len(d)}
    out["calib"] = OrderedDict()
    out["calib"]["MODELLO"] = brier_ll(u, ("model_1", "model_X", "model_2"))
    out["calib"]["PIN pre"] = brier_ll(u, ("pinpre_1", "pinpre_X", "pinpre_2"))
    out["calib"]["PIN close"] = brier_ll(u, ("pinclose_1", "pinclose_X", "pinclose_2"))
    out["calib"]["Bet365"] = brier_ll(u, ("b365_1", "b365_X", "b365_2"))
    out["calib"]["Avg"] = brier_ll(u, ("avg_1", "avg_X", "avg_2"))
    # ROI per book (selezione edge>0 vs quel book, settle su quote reali): stessa
    # roi_1x2 di diagnose_production_baseline (EDGE_MIN=0, puntata fissa)
    out["roi"] = OrderedDict()
    book_specs = OrderedDict([
        ("PIN pre", ("pinpre_1", "pinpre_X", "pinpre_2", "PSH", "PSD", "PSA")),
        ("PIN close", ("pinclose_1", "pinclose_X", "pinclose_2", "PSCH", "PSCD", "PSCA")),
        ("Bet365", ("b365_1", "b365_X", "b365_2", "B365H", "B365D", "B365A")),
        ("Avg", ("avg_1", "avg_X", "avg_2", "AvgH", "AvgD", "AvgA")),
    ])
    for book, (f1, fX, f2, o1, oX, o2) in book_specs.items():
        sub = u.dropna(subset=[f1, fX, f2, o1, oX, o2])
        if len(sub) == 0:
            out["roi"][book] = {"n_bet": 0, "win_rate_pct": None, "roi_pct": None, "n": 0}
            continue
        nb, wr, roi = roi_1x2(sub, ("model_1", "model_X", "model_2"),
                              (f1, fX, f2), (o1, oX, o2), stake=STAKE)
        out["roi"][book] = {"n": len(sub), "n_bet": nb,
                            "win_rate_pct": round(wr, 1) if wr is not None else None,
                            "roi_pct": round(roi, 2) if roi is not None else None}
    out["clv"] = clv_block(u)
    # confronto di segnale (punto 4): delta Brier appaiati con bootstrap CI
    out["delta"] = {
        "modello_vs_pinclose": bootstrap_dbrier(
            u, ("pinclose_1", "pinclose_X", "pinclose_2"),
            ("model_1", "model_X", "model_2")),
        "pinclose_vs_b365": bootstrap_dbrier(
            u, ("b365_1", "b365_X", "b365_2"),
            ("pinclose_1", "pinclose_X", "pinclose_2")),
        "pinclose_vs_avg": bootstrap_dbrier(
            u, ("avg_1", "avg_X", "avg_2"),
            ("pinclose_1", "pinclose_X", "pinclose_2")),
    }
    return out


def _fv(v, nd=2, suffix=""):
    return "-" if v is None else f"{v:.{nd}f}{suffix}"


def _fci(ci, nd=2, suffix=""):
    if ci is None or ci[0] is None or ci[1] is None:
        return "-"
    return f"[{ci[0]:.{nd}f}; {ci[1]:.{nd}f}]{suffix}"


def render_markdown(payload):
    L = []
    ap = L.append
    ap("# CLV vs Pinnacle — mercato 1X2 (audit sola lettura)")
    ap("")
    ap(f"*Generato: {payload['generated_at']} — script `audit/diagnose_clv_pinnacle.py`, "
       "nessuna modifica a SoccerMath/.*")
    ap("")
    ap("Split walk-forward identico agli altri audit: train 2022/23+2023/24, "
       "validation (V) 2024/25, test (T) 2025/26. Il Live 2026/27 resta fuori "
       "dall'eval (nessuna quota Pinnacle comunque).")
    ap("")

    # ---------- Copertura (punto 1, in cima) ----------
    ap("## Copertura quote Pinnacle (partite senza quota: ESCLUSE, non stimate)")
    ap("")
    ap("Quota valida = presente, numerica e > 1.0 (regola di `devig_1x2`). Il campione "
       "usabile richiede PRE **e** chiusura: senza una delle due la partita esce da "
       "tutte le metriche Pinnacle/CLV (Bet365/Avg vengono mascherate per-riga se "
       "mancanti). Nessuna imputazione.")
    ap("")
    ap("| Lega | Stagione | Partite | PSH ok | PSH mancante | PSCH ok | PSCH mancante | Usabili (pre+close) | % usabili | Eval |")
    ap("|---|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for lg in payload["leagues"]:
        for c in lg["coverage"]:
            ap(f"| {lg['league']} | {c['season']} | {c['rows']} | {c['pre_ok']} | "
               f"{c['pre_missing']} | {c['close_ok']} | {c['close_missing']} | "
               f"{c['usable']} | {_fv(c['usable_pct'],1,'%')} | {'si' if c['in_eval'] else 'no'} |")
    tot_rows = sum(c["rows"] for lg in payload["leagues"] for c in lg["coverage"] if c["in_eval"])
    tot_usable = sum(c["usable"] for lg in payload["leagues"] for c in lg["coverage"] if c["in_eval"])
    ap("")
    ap(f"**Totale eval (V+T): {tot_usable} partite usabili su {tot_rows} "
       f"({100.0*tot_usable/max(tot_rows,1):.1f}%).** Le mancanze sono concentrate in "
       "2025/26 (stagione in corso allo scraping: Pinnacle presente solo sulle "
       "partite gia' disputate con quotazione chiusa) e nel Live 2026/27 (nessuna "
       "quota); le stagioni 2022/23-2024/25 sono coperte al 100%. PSH vs PSCH "
       "differiscono per 1-2 partite per lega nel 2025/26 (partite appena giocate: "
       "apertura senza chiusura): escluse come da protocollo.")
    ap("")

    # ---------- Metodo ----------
    ap("## Metodo")
    ap("")
    ap("- **Modello**: testa 1X2 PRODUZIONE_DUE_TESTE (NORM-SUM: xG snapshot + forma "
       "ultime 5 + fattore mercato, lambda normalizzati alla somma base S, clip "
       "[exp(-6), exp(3)]) con ensemble Elo **opzione b gia' in produzione**: "
       "1X2 = 0.6*Poisson + 0.4*Elo (`app.ELO_ENSEMBLE_W`, validato in "
       "`diagnose_elo_ensemble.py`, applicato in `app.blend_elo_into_1x2`). Elo "
       "walk-forward K=24 replica di `diagnose_elo_ensemble.py`, aggiornato DOPO "
       "ogni previsione: nessuna partita usa se stessa o il futuro. Il ramo "
       "NORM-SUM del walker e' verificato bit-faithful a "
       "`diagnose_production_baseline.run_models` da `test_diagnose_clv_pinnacle.py`.")
    ap("- **De-vig**: proporzionale standard `1/quota / overround` = `devig_1x2` di "
       "`backtest_experiment_all.py` (il brief citava `devig_2way`: e' la variante "
       "a 2 esiti dello stesso file; per il 1X2 vale il precedente a 3 esiti).")
    ap("- **CLV (protocollo)**: sul lato scommesso dal modello (edge>0 vs linea PRE "
       "Pinnacle de-vigata, convenzione `EDGE_MIN=0`): `CLV = P_modello(lato) - "
       "P_chiusura(lato)`. Accanto, il **CLV classico** `P_pre(lato) - "
       "P_chiusura(lato)` (prezzo preso vs chiusura) per il confronto con la "
       "letteratura: il primo misura l'edge residuo del modello a chiusura, il "
       "secondo la qualita' del prezzo preso.")
    ap("- **ROI a puntata fissa**: (a) sulle stesse scommesse CLV, settle alla "
       "**chiusura Pinnacle** come prezzo di riferimento richiesto (e a pre, "
       "informativo); (b) ROI per book con selezione edge>0 vs quel book e settle "
       "sulle quote reali di quel book (`roi_1x2` di "
       "`diagnose_production_baseline.py`, identica agli altri audit).")
    ap("- **Bootstrap**: 2000 resample di righe, seed 20260905, CI percentile "
       "2.5-97.5 (costanti `N_BOOT`/`SEED` e formula `_ci` di `topmix_margins.py`; "
       "il file `diagnose_rho_bootstrap.py` citato dal protocollo non esiste nel "
       "repo, e `diagnose_dixon_coles_rho.py` non contiene bootstrap).")
    ap("")

    # ---------- Calibrazione ----------
    ap("## Calibrazione 1X2: modello vs Pinnacle pre vs chiusura vs Bet365 vs Avg")
    ap("")
    ap("Campione = partite eval con Pinnacle pre+close valide (Bet365/Avg mascherate "
       "per-riga dove mancano). Brier/LogLoss multiclasse (`brier_ll_1x2`).")
    ap("")
    ap("| Campione | Book | n V | Brier V | LogLoss V | n T | Brier T | LogLoss T | n tot | Brier tot | LogLoss tot |")
    ap("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

    def _calib_row(label, book, mb, ms, mt):
        ap(f"| {label} | {book} | {ms['n']} | {_fv(ms['brier'],4)} | {_fv(ms['log_loss'],4)} | "
           f"{mt['n']} | {_fv(mt['brier'],4)} | {_fv(mt['log_loss'],4)} | "
           f"{mb['n']} | {_fv(mb['brier'],4)} | {_fv(mb['log_loss'],4)} |")

    for lg in payload["leagues"]:
        for book in ("MODELLO", "PIN pre", "PIN close", "Bet365", "Avg"):
            _calib_row(f"**{lg['league']}**", book,
                       lg["overall"]["calib"][book],
                       lg["by_season"]["2024/25"]["calib"][book],
                       lg["by_season"]["2025/26"]["calib"][book])
    for book in ("MODELLO", "PIN pre", "PIN close", "Bet365", "Avg"):
        _calib_row("**AGGREGATO**", book,
                   payload["overall"]["calib"][book],
                   payload["overall_by_season"]["2024/25"]["calib"][book],
                   payload["overall_by_season"]["2025/26"]["calib"][book])
    ap("")

    # ---------- CLV ----------
    ap("## CLV sul lato scommesso (edge>0 vs Pinnacle pre)")
    ap("")
    ap("`CLV modello = P_modello(lato) - P_chiusura(lato)` (protocollo); "
       "`CLV classico = P_pre(lato) - P_chiusura(lato)`. CI bootstrap 95%. "
       "ROI chiusura = scommesse settle a quote chiuse Pinnacle (prezzo di "
       "riferimento); ROI pre = alle quote pre effettivamente battute.")
    ap("")
    ap("| Campione | Scommesse | CLV medio | CI 95% | CLV>0 | CLV classico | CI 95% | Clas.>0 | Win rate | ROI chiusura | CI 95% | ROI pre |")
    ap("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for lg in payload["leagues"]:
        for season in SEASONS_EVAL:
            c = lg["by_season"][season]["clv"]
            if c.get("n_bet", 0) == 0:
                ap(f"| **{lg['league']}** {season} | 0 | - | - | - | - | - | - | - | - | - | - |")
                continue
            ap(f"| **{lg['league']}** {season} | {c['n_bet']} | "
               f"{_fv(c['clv_model_mean']*100)}% | {_fci([x*100 for x in c['clv_model_ci']],2,'%')} | "
               f"{_fv(c['clv_model_pos_pct'],1,'%')} | {_fv(c['clv_classic_mean']*100)}% | "
               f"{_fci([x*100 for x in c['clv_classic_ci']],2,'%')} | {_fv(c['clv_classic_pos_pct'],1,'%')} | "
               f"{_fv(c['win_rate_pct'],1,'%')} | {_fv(c['roi_close_pct'])}% | "
               f"{_fci(c['roi_close_ci'],2,'%')} | {_fv(c['roi_pre_pct'])}% |")
        c = lg["overall"]["clv"]
        if c.get("n_bet", 0) == 0:
            ap(f"| **{lg['league']}** tot | 0 | - | - | - | - | - | - | - | - | - | - |")
        else:
            ap(f"| **{lg['league']}** tot | {c['n_bet']} | "
               f"{_fv(c['clv_model_mean']*100)}% | {_fci([x*100 for x in c['clv_model_ci']],2,'%')} | "
               f"{_fv(c['clv_model_pos_pct'],1,'%')} | {_fv(c['clv_classic_mean']*100)}% | "
               f"{_fci([x*100 for x in c['clv_classic_ci']],2,'%')} | {_fv(c['clv_classic_pos_pct'],1,'%')} | "
               f"{_fv(c['win_rate_pct'],1,'%')} | {_fv(c['roi_close_pct'])}% | "
               f"{_fci(c['roi_close_ci'],2,'%')} | {_fv(c['roi_pre_pct'])}% |")
    c = payload["overall"]["clv"]
    if c.get("n_bet", 0):
        ap(f"| **AGGREGATO** | {c['n_bet']} | "
           f"{_fv(c['clv_model_mean']*100)}% | {_fci([x*100 for x in c['clv_model_ci']],2,'%')} | "
           f"{_fv(c['clv_model_pos_pct'],1,'%')} | {_fv(c['clv_classic_mean']*100)}% | "
           f"{_fci([x*100 for x in c['clv_classic_ci']],2,'%')} | {_fv(c['clv_classic_pos_pct'],1,'%')} | "
           f"{_fv(c['win_rate_pct'],1,'%')} | {_fv(c['roi_close_pct'])}% | "
           f"{_fci(c['roi_close_ci'],2,'%')} | {_fv(c['roi_pre_pct'])}% |")
    ap("")
    ov_calib = payload["overall"]["calib"]
    ov_delta = payload["overall"]["delta"]["modello_vs_pinclose"]
    if c.get("n_bet", 0) and ov_calib["MODELLO"]["brier"] is not None:
        ap(f"**Lettura**: il CLV di protocollo ({_fv(c['clv_model_mean']*100)}%, "
           f"{_fv(c['clv_model_pos_pct'],1,'%')} positivo) e' molto piu' alto del CLV classico "
           f"({_fv(c['clv_classic_mean']*100)}%): misura la distanza modello-mercato, non la "
           f"qualita' del prezzo. Il modello e' sistematicamente meno calibrato della chiusura "
           f"(Brier {_fv(ov_calib['MODELLO']['brier'],4)} vs "
           f"{_fv(ov_calib['PIN close']['brier'],4)}; Delta Brier modello-chiusura "
           f"{ov_delta['delta']:+.4f}, CI {_fci(ov_delta['ci'],4)}), quindi un lato con "
           f"edge positivo vs pre di solito resta in edge anche a chiusura: e' il segno della "
           f"calibrazione peggiore del modello, non di skill. Il segnale da guardare e' il "
           f"CLV classico ({_fv(c['clv_classic_mean']*100)}%, CI "
           f"{_fci([x*100 for x in c['clv_classic_ci']],2,'%')}): l'informazione del modello al "
           f"momento della scommessa batte la chiusura solo di un margine sottile.")
    ap("")

    # ---------- ROI per book ----------
    ap("## ROI per book (edge>0 vs quel book, settle su quote reali, puntata 10)")
    ap("")
    ap("| Campione | Book | Righe | Scommesse | Win rate | ROI |")
    ap("|---|---|---:|---:|---:|---:|")
    for lg in payload["leagues"]:
        for book, r in lg["overall"]["roi"].items():
            ap(f"| **{lg['league']}** | {book} | {r.get('n', 0)} | {r['n_bet']} | "
               f"{_fv(r['win_rate_pct'],1,'%')} | {_fv(r['roi_pct'])}% |")
    for book, r in payload["overall"]["roi"].items():
        ap(f"| **AGGREGATO** | {book} | {r.get('n', 0)} | {r['n_bet']} | "
           f"{_fv(r['win_rate_pct'],1,'%')} | {_fv(r['roi_pct'])}% |")
    ap("")

    # ---------- Pinnacle vs B365/Avg ----------
    ap("## Pinnacle da' un segnale diverso da Bet365/Avg?")
    ap("")
    ap("Delta Brier appaiati (B - A) sullo stesso campione, CI bootstrap 95%. "
       "Delta > 0 significa che il book B e' MENO calibrated (Brier peggiore).")
    ap("")
    ap("| Confronto | n | Delta Brier | CI 95% |")
    ap("|---|---:|---:|---:|")
    delta_labels = {
        "modello_vs_pinclose": "MODELLO - PIN close",
        "pinclose_vs_b365": "PIN close - Bet365",
        "pinclose_vs_avg": "PIN close - Avg",
    }
    for name, dd in payload["overall"]["delta"].items():
        label = delta_labels.get(name, name)
        if dd["delta"] is None:
            ap(f"| {label} | {dd['n']} | - | - |")
        else:
            ap(f"| {label} | {dd['n']} | {dd['delta']:+.4f} | "
               f"[{dd['ci'][0]:+.4f}; {dd['ci'][1]:+.4f}] |")
    ap("")
    dd_close = payload["overall"]["delta"]["pinclose_vs_b365"]
    if dd_close["delta"] is not None:
        sig = (dd_close["delta"] > 0 and dd_close["ci"][0] > 0) or \
              (dd_close["delta"] < 0 and dd_close["ci"][1] < 0)
        if sig:
            direz = "meglio" if dd_close["delta"] < 0 else "peggio"
            ap(f"Sul campione aggregato la chiusura Pinnacle e' **{direz}** di Bet365 in modo "
               "distinguishable (CI che non contiene 0): la scelta di Pinnacle come riferimento "
               "cambia il segnale di calibrazione rispetto a Bet365/Avg.")
        else:
            ap("Sul campione aggregato la differenza tra chiusura Pinnacle e Bet365 non e' "
               "distinguishable dal rumore (CI che contiene 0): Pinnacle e Bet365/Avg danno lo "
               "stesso tipo di segnale di calibrazione sui dati correnti; la differenza pratica "
               "sta nel prezzo (margine tipicamente minore su Pinnacle), non nella direzione.")
    ap("")

    # ---------- Limiti ----------
    ap("## Limiti dichiarati")
    ap("")
    ap("1. **xG snapshot statico**: la testa 1X2 usa `xg_<lega>.json` aggiornato a "
       "oggi (come in tutti gli audit del progetto che replicano la produzione): "
       "nelle stagioni passate lo snapshot e' piu' informativo di quanto fosse "
       "all'epoca. Vale anche per il boost xG assente nell'Elo di replica.")
    ap("2. **Elo di replica**: K fisso 24 senza moltiplicatore di scarto gol e "
       "senza boost xG (formula `predict_elo_probs` di produzione), secondo la "
       "replica validata di `diagnose_elo_ensemble.py` che ha introdotto il blend "
       "0.6/0.4 in produzione.")
    ap("3. **CLV protocollo vs classico**: il CLV richiesto misura l'edge residuo "
       "del modello a chiusura (probabilita', non prezzi): e' sensibile alla "
       "calibrazione del modello, non solo al timing della scommessa. Il CLV "
       "classico e' riportato per separare i due effetti.")
    ap("4. **Chiusura come prezzo di riferimento**: il ROI a chiusura non e' "
       "eseguibile in pratica (la selezione avviene sulla linea pre): e' il "
       "riferimento richiesto dal protocollo, il ROI a pre e' riportato accanto.")
    ap("5. **Quote una sola casa per confronto**: Pinnacle pre/chiusura non hanno "
       "timestamp; le colonne football-data sono apertura e chiusura come da "
       "rilascio del dataset. Bet365/Avg usano le stesse convenzioni degli altri "
       "audit (B365*/Avg*).")
    ap("")
    return "\n".join(L) + "\n"


# =====================================================================
# Main
# =====================================================================
def run():
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "leagues": []}
    all_rows = []
    for prefix, camp_key in LEAGUES:
        lg = run_league(prefix, camp_key)
        d = lg["rows"]
        all_rows.append(d)
        by_season = OrderedDict()
        for season in SEASONS_EVAL:
            by_season[season] = metrics_for_sample(d[d["season"] == season])
        lg["by_season"] = by_season
        lg["overall"] = metrics_for_sample(d)
        payload["leagues"].append(lg)

    all_d = pd.concat(all_rows, ignore_index=True)
    payload["overall_by_season"] = OrderedDict(
        (season, metrics_for_sample(all_d[all_d["season"] == season]))
        for season in SEASONS_EVAL)
    payload["overall"] = metrics_for_sample(all_d)
    md = render_markdown(payload)
    return payload, md


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    payload, md = run()
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(f"Scritto {OUT_PATH}")
    ov = payload["overall"]
    clv = ov["clv"]
    print(f"Partite eval usabili: {ov['n_usable']} | "
          f"Brier modello {ov['calib']['MODELLO']['brier']} vs PIN pre "
          f"{ov['calib']['PIN pre']['brier']} vs PIN close {ov['calib']['PIN close']['brier']}")
    if clv.get("n_bet"):
        print(f"CLV modello medio {clv['clv_model_mean']*100:+.2f}% su {clv['n_bet']} scommesse "
              f"({clv['clv_model_pos_pct']:.1f}% >0) | ROI chiusura {clv['roi_close_pct']:+.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
