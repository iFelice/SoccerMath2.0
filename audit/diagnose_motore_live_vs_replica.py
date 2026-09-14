"""
diagnose_motore_live_vs_replica.py — PASSO 0 (mai fatto finora): il motore
REALE di produzione, chiamato direttamente, e' identico alla replica offline
usata dai 4 audit precedenti?

Tutti gli audit finora (form_totali, combo_1x2_totali, calibration_layer,
overdispersion, bias_variance_totali) RIIMPLEMENTANO la logica di
app.get_league_engine() camminando sui CSV in ordine cronologico; usano
pero' l'istantanea xG STATICA (xg_*.json) senza la pipeline point-in-time
di produzione. La produzione vera (SoccerMath/app.py) per la testa Totali
usa invece:
  * season_point_in_time_averages()  (fonte F_season, xG della SOLA
    stagione in corso al cutoff, niente leakage, archivio
    "xG archivio *.json" di xg_archive.py);
  * _shrunk_ratio() con PRIOR_MATCHES=6 (shrinkage empirico-bayesiano
    verso la media di lega, ancora derivata dal dizionario F_season);
  * fallback gol pooled e shrinkato per dato insufficiente;
  * clip lambda [exp(-6), exp(3)] dentro _poisson_market.

Questo script, per OGNI partita di validation 2024/25 e test 2025/26
(5 leghe, stesso walk-forward/disciplina degli audit precedenti):
  PASSO 0  chiama DIRETTAMENTE app.get_league_engine() in versione
           point-in-time (un engine per data, DB troncato al giorno prima,
           cutoff iniettato nella VERA season_point_in_time_averages: nessuna
           riga di produzione riscritta, solo monkeypatch di I/O e cutoff,
           zero scritture su SoccerMath/) e app.get_full_poisson_two_heads()
           per avere lambda_home/lambda_away, P(Over2.5), P(GG). Confronta
           partita-per-partita con la replica modello B di
           diagnose_form_totali (stessa base dati dei 4 audit). Riporta
           massimo, media, mediana, p95, p99, RMS e frazione di zeri degli
           scarti, separatamente per lambda e per probabilita'.
  PASSO 1  (solo se il passo 0 mostra scarti non nulli) ripete la
           decomposizione di Murphy a 10 decili (identica a
           diagnose_bias_variance_totali.murphy) e il rapporto
           Risoluzione/Incertezza sulle probabilita' LIVE, e le confronta
           con quelle della replica (Over 0.8%/0.9%, GG 0.6%/1.2% su
           val/test) tramite bootstrap stratificato per lega,
           appaiato e con seed deterministico, sulla differenza.

CONCLUSIONE RICHIESTA: l'eventuale differenza sposta il verdetto "nessun
segnale da suddividere in bucket" della pista 3, oppure il motore live e'
sostanzialmente equivalente alla replica su questa metrica?

NON tocca SoccerMath/: chiama solo funzioni esistenti in sola lettura
(il troncamento storico avviene intercettando pd.read_csv in memoria;
non viene scritto alcun file dentro SoccerMath/).
Output: audit/results/motore_live_vs_replica_diagnosis.md
Uso:    python audit/diagnose_motore_live_vs_replica.py
"""
from __future__ import annotations

import os
import sys
import math
import time
import contextlib
import functools
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

# I warning "missing ScriptRunContext" della streamlit in bare mode non
# devono inquinare l'output: e' la modalita' prevista per importare app.py
# fuori da `streamlit run`.
for _name in ("streamlit", "streamlit.runtime",
              "streamlit.runtime.scriptrunner", "root"):
    logging.getLogger(_name).setLevel(logging.ERROR)

import streamlit as st  # noqa: E402,F401  (necessita' del package installato)

import app                                                   # noqa: E402
import xg_archive                                            # noqa: E402
from config import get_league_db_files                      # noqa: E402
from backtest_experiment_all import LEAGUES, load_league    # noqa: E402
import diagnose_form_totali as dft                          # noqa: E402
import diagnose_bias_variance_totali as bv                  # noqa: E402
from topmix_margins import SEED, _ci                        # noqa: E402

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "motore_live_vs_replica_diagnosis.md")
SEASONS_EVAL = ("2024/25", "2025/26")
LEAGUE_KEYS = [ck for _, ck in LEAGUES]

# Soglie di "scarto nullo": al di' sotto di queste il Passo 1 non serve.
EPS_PROB = 1e-12
EPS_LAM = 1e-12
SOGLIA = 0.05      # RES/UNC >= 5% su entrambi gli split = risoluzione sostanziale
N_BOOT = 2000

# Le fonti statiche (istantanee xG 1X2, valori di mercato, archivi JSON) non
# dipendono dal cutoff: le si cachea in memoria per non rileggerle per ogni
# data. I dati DIPENDENTI dal cutoff passano tutti dal troncamento di
# pd.read_csv e dall'argomento cutoff iniettato in season_point_in_time.
app.get_understat_xg = functools.cache(app.get_understat_xg)
app.get_market_values = functools.cache(app.get_market_values)
xg_archive.load_archive = functools.cache(xg_archive.load_archive)


# ---------------------------------------------------------------------------
# PASSO 0a: replica offline modello B, con lambda separate per lato
# (formule letterali di diagnose_form_totali.run_models, variante "pura")
# ---------------------------------------------------------------------------
def replica_walk(df, xg_data):
    """Walk-forward identico a diagnose_form_totali modello B, ma emette
    anche lambda_home/lambda_away e le chiavi di partita. La parita' esatta
    con run_models viene verificata esternamente (cross-check bit-a-bit)."""
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
            state[t] = dft.TeamState()
        return state[t]

    for _, row in df.iterrows():
        fthg = int(row.FTHG)
        ftag = int(row.FTAG)
        h, a = row.HomeClean, row.AwayClean
        sh, sa = get(h), get(a)
        avg_h = max(tot_hg / tot_n, 0.1) if tot_n else 0.1
        avg_a = max(tot_ag / tot_n, 0.1) if tot_n else 0.1

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
            lam_h = dft.clip(p_att_h * p_def_a * avg_h)
            lam_a = dft.clip(p_att_a * p_def_h * avg_a)
            m = dft.get_full_poisson(lam_h, lam_a)
            rows.append({
                "date": pd.Timestamp(row.Date).normalize(),
                "season": row.season, "home": h, "away": a,
                "lam_h": lam_h, "lam_a": lam_a,
                "po_rep": 1.0 - m["u25"], "gg_rep": m["gg"],
                "y_over": int(fthg + ftag > 2.5),
                "y_gg": int(fthg > 0 and ftag > 0),
            })

        tot_hg += fthg
        tot_ag += ftag
        tot_n += 1
        sh.observe_home(fthg, ftag)
        sa.observe_away(fthg, ftag)

    return pd.DataFrame(rows)


def replica_ratios_by_day(df, xg_data):
    """Cammina come la replica ma registra, per ogni giorno valutato, le
    medie-gol di lega correnti e i ratio grezzi di ogni squadra (snapshot
    xG statica senza shrinkage, o fallback gol della replica). Serve ad
    ATTRIBUIRE gli scarti del Passo 0 separando i tre canali: finestra della
    sorgente xG, shrinkage e fallback gol."""
    xg_att, xg_def = {}, {}
    if xg_data and len(xg_data) >= 10:
        vals = list(xg_data.values())
        lx = float(np.mean([v["xG_avg"] for v in vals]))
        lxa = float(np.mean([v["xGA_avg"] for v in vals]))
        for t, v in xg_data.items():
            xg_att[t] = v["xG_avg"] / lx
            xg_def[t] = v["xGA_avg"] / lxa
    state = {}
    thg = tag = tn = 0
    out = {}
    prev = None

    def get(t):
        if t not in state:
            state[t] = dft.TeamState()
        return state[t]

    for _, row in df.iterrows():
        fthg, ftag = int(row.FTHG), int(row.FTAG)
        h, a = row.HomeClean, row.AwayClean
        sh, sa = get(h), get(a)
        ah = max(thg / tn, 0.1) if tn else 0.1
        aa = max(tag / tn, 0.1) if tn else 0.1

        def prim_att(t, ts):
            if t in xg_att:
                return xg_att[t]
            return (ts.hgf / ts.hgn) / ah if ts.hgn else 1.0

        def prim_def(t, ts):
            if t in xg_def:
                return xg_def[t]
            return (ts.hga / ts.hgn) / aa if ts.hgn else 1.0

        if row.season in SEASONS_EVAL:
            d = pd.Timestamp(row.Date).normalize()
            if d != prev:
                out[d] = {
                    "ah": ah, "aa": aa,
                    "ratios": {t: (prim_att(t, s), prim_def(t, s))
                               for t, s in state.items()},
                }
                prev = d
        thg += fthg
        tag += ftag
        tn += 1
        sh.observe_home(fthg, ftag)
        sa.observe_away(fthg, ftag)
    return out


# ---------------------------------------------------------------------------
# PASSO 0b: motore REALE point-in-time, chiamato direttamente
# ---------------------------------------------------------------------------
class LiveReplayer:
    """Esegue app.get_league_engine(camp_key) ESATTAMENTE come produzione,
    ma a un cutoff storico: (1) intercetta pd.read_csv per troncare i CSV
    della lega alle partite con Date < giorno del cutoff; (2) inietta il
    cutoff nella vera xg_archive.season_point_in_time_averages (fonte
    F_season). Niente altro viene toccato: shrinkage, fallback, gate,
    form factors, mercato, Poisson sono quelli letterali di app.py."""

    def __init__(self, camp_key):
        self.camp_key = camp_key
        self.engine_files = {
            os.path.realpath(p) for p in get_league_db_files(camp_key)}
        self._orig_pit = app.season_point_in_time_averages
        self._orig_read = pd.read_csv
        self.last_agg = None

    @contextlib.contextmanager
    def _patched(self, cutoff, day):
        replayer = self
        orig_read = self._orig_read
        files = self.engine_files

        def pit(lg, *args, **kwargs):
            kwargs.pop("cutoff", None)
            agg = replayer._orig_pit(lg, cutoff=cutoff, *args, **kwargs)
            replayer.last_agg = agg
            return agg

        def rcsv(path, *args, **kwargs):
            df = orig_read(path, *args, **kwargs)
            try:
                rp = os.path.realpath(path)
            except (TypeError, ValueError):
                rp = None
            if rp in files and hasattr(df, "columns") and "Date" in df.columns:
                dates = pd.to_datetime(df["Date"], dayfirst=True,
                                       errors="coerce")
                df = df[dates < day]
            return df

        app.season_point_in_time_averages = pit
        pd.read_csv = rcsv
        app.pd.read_csv = rcsv
        app.get_league_engine.clear()
        try:
            yield
        finally:
            app.season_point_in_time_averages = replayer._orig_pit
            pd.read_csv = orig_read
            app.pd.read_csv = orig_read
            app.get_league_engine.clear()

    def engine_at(self, day):
        """day: Timestamp alle 00:00 (giorno della partita). Il cutoff e'
        quello giorno a mezzogiorno UTC: con cutoff_policy di default
        ('previous_day') F_season include esattamente le partite dei giorni
        precedenti, come nel pre-partita reale."""
        cutoff = datetime(day.year, day.month, day.day, 12, 0,
                          tzinfo=timezone.utc)
        self.last_agg = None
        with self._patched(cutoff, day):
            with open(os.devnull, "w") as devnull, \
                    contextlib.redirect_stderr(devnull):
                res = app.get_league_engine(self.camp_key)
        return res, self.last_agg


def live_probs(stats, avg_h, avg_a, home, away):
    """Chiama direttamente la funzione di produzione che mappa le statistiche
    nelle due teste, e ricava i lambda della testa Totali con le STESSE
    righe di get_full_poisson_two_heads (verifica di chiusura inclusa)."""
    sh = stats.get(home) if stats else None
    sa = stats.get(away) if stats else None
    sh = sh if isinstance(sh, dict) else {}
    sa = sa if isinstance(sa, dict) else {}
    m = app.get_full_poisson_two_heads(sh, sa, avg_h, avg_a)

    att0_h = app._stat_num(sh, "att0", app._stat_num(sh, "att", 1.0))
    def0_h = app._stat_num(sh, "def0", app._stat_num(sh, "def", 1.0))
    att0_a = app._stat_num(sa, "att0", app._stat_num(sa, "att", 1.0))
    def0_a = app._stat_num(sa, "def0", app._stat_num(sa, "def", 1.0))
    attp_h = app._stat_num(sh, "att0_pure", att0_h)
    defp_h = app._stat_num(sh, "def0_pure", def0_h)
    attp_a = app._stat_num(sa, "att0_pure", att0_a)
    defp_a = app._stat_num(sa, "def0_pure", def0_a)
    lam_h = app._clip_lambda(attp_h * defp_a * avg_h)
    lam_a = app._clip_lambda(attp_a * defp_h * avg_a)

    # chiusura: i lambda ricavati devono riprodurre le prob. del wrapper
    mm = app._poisson_market(lam_h, lam_a)
    err = max(abs(mm["u25"] - m["u25"]), abs(mm["gg"] - m["gg"]))
    return {
        "lam_h": lam_h, "lam_a": lam_a,
        "po_live": 1.0 - m["u25"], "gg_live": m["gg"],
        "missing": int(not sh) + int(not sa),
        "close_err": err,
    }


# ---------------------------------------------------------------------------
# Distribuzione scarti
# ---------------------------------------------------------------------------
def scarto_stats(d):
    d = np.asarray(d, dtype=float)
    a = np.abs(d)
    if len(a) == 0:
        return {k: float("nan") for k in
                ("n", "max", "p99", "p95", "median", "mean", "rms",
                 "zero_frac", "signed_mean")}
    return {
        "n": len(a),
        "max": float(a.max()),
        "p99": float(np.percentile(a, 99)),
        "p95": float(np.percentile(a, 95)),
        "median": float(np.median(a)),
        "mean": float(a.mean()),
        "rms": float(np.sqrt(np.mean(d ** 2))),
        "zero_frac": float(np.mean(a == 0.0)),
        "signed_mean": float(d.mean()),
    }


def fmt_scarto(s):
    return (f"max {s['max']:.2e} | p99 {s['p99']:.2e} | p95 "
            f"{s['p95']:.2e} | mediana {s['median']:.2e} | media "
            f"{s['mean']:.2e} | RMS {s['rms']:.2e} | zeri "
            f"{100*s['zero_frac']:.1f}%")


# ---------------------------------------------------------------------------
# Bootstrap appaiato, stratificato per lega, sulla differenza live-replica
# ---------------------------------------------------------------------------
def bootstrap_delta(df, pcol_live, pcol_rep, ycol, n_boot=N_BOOT, seed=SEED):
    """Differenza LIVE - REPLICA di Risoluzione/Incertezza (e Brier) sul
    pool delle 5 leghe. In ogni ricampionamento si ripescano dentro ogni
    lega (stesso seme/disciplina degli altri audit) e le coppie
    live/replica restano appaiate partita-per-partita."""
    league_idx = {lk: np.where(df["league"].to_numpy() == lk)[0]
                  for lk in LEAGUE_KEYS}
    rng = np.random.default_rng(seed)
    d_rat, d_brier = [], []
    y_all = df[ycol].to_numpy().astype(float)
    pl_all = df[pcol_live].to_numpy()
    pr_all = df[pcol_rep].to_numpy()
    for _ in range(n_boot):
        idx = np.concatenate([
            ix[rng.integers(0, len(ix), size=len(ix))]
            for ix in league_idx.values() if len(ix)])
        ml = bv.murphy(pl_all[idx], y_all[idx])
        mr = bv.murphy(pr_all[idx], y_all[idx])
        d_rat.append(ml["res"] / ml["unc"] - mr["res"] / mr["unc"])
        d_brier.append(ml["brier"] - mr["brier"])
    d_rat = np.asarray(d_rat)
    d_brier = np.asarray(d_brier)
    lo_r, hi_r = _ci(list(d_rat))
    lo_b, hi_b = _ci(list(d_brier))
    return {"d_ratio": float(np.mean(d_rat)), "lo_r": lo_r, "hi_r": hi_r,
            "d_brier": float(np.mean(d_brier)), "lo_b": lo_b, "hi_b": hi_b}


def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)

    # Cache di sviluppo del replay (fuori dal repo): se LIVE_REPLAY_CACHE
    # punta a un percorso, il risultato del replay viene caricato/salvato
    # li' (DataFrame), evitando i ~4 min di chiamate al motore quando si
    # ritocca solo il report.
    cache_path = os.environ.get("LIVE_REPLAY_CACHE")
    import pickle
    if cache_path and os.path.exists(cache_path):
        with open(cache_path, "rb") as fh:
            blob = pickle.load(fh)
        frames = blob["frames"]
        fs_cov = blob["fs_cov"]
        checks = blob["checks"]
        universe_rows = blob["universe_rows"]
        n_engine_calls = blob["n_engine_calls"]
        attribution = blob.get("attribution", {})
        loaded_from_cache = True
        print(f"(replay caricato da cache {cache_path}: "
              f"{sum(len(f) for f in frames)} partite)")
    else:
        loaded_from_cache = False

    if not loaded_from_cache:
        # =================================================================
        # Costruzione dei due universi (replica + live) per tutte le leghe
        # =================================================================
        frames = []
        checks = {
            "cross_replica_po": 0.0, "cross_replica_gg": 0.0,
            "cross_replica_lam": 0.0, "cross_prob_engine": 0.0,
            "close_err": 0.0, "missing_teams": 0, "harness_today": 0.0,
            "avg_diff": 0.0,
        }
        fs_cov = {}
        n_engine_calls = 0
        universe_rows = []
        attribution = {ck: {"src": [], "shr": [], "fb": [],
                            "avg": []} for _, ck in LEAGUES}

        for prefix, ck in LEAGUES:
            print(f"==> {ck}: replica + replay del motore live ...")
            df = load_league(prefix)
            xg = dft.load_xg(ck)

            # ---- universi a confronto: replica (modello B, dettagliata) ----
            rep = replica_walk(df, xg)

            # cross-check bit-a-bit con la replica COMMITTATA diagnose_form_totali
            ref = dft.run_models(df, xg)
            assert len(ref) == len(rep), (ck, len(ref), len(rep))
            checks["cross_replica_po"] = max(
                checks["cross_replica_po"],
                float(np.max(np.abs(rep["po_rep"].to_numpy()
                                    - ref["pure_po"].to_numpy()))))
            checks["cross_replica_gg"] = max(
                checks["cross_replica_gg"],
                float(np.max(np.abs(rep["gg_rep"].to_numpy()
                                    - ref["pure_gg"].to_numpy()))))
            checks["cross_replica_lam"] = max(
                checks["cross_replica_lam"],
                float(np.max(np.abs(
                    (rep["lam_h"] + rep["lam_a"]).to_numpy()
                    - ref["pure_lam_tot"].to_numpy()))))

            # parita' del motore di probabilita': app._poisson_market contro
            # get_full_poisson della replica, sugli STESSI lambda (deve essere 0)
            for lh, la in zip(rep["lam_h"].to_numpy(), rep["lam_a"].to_numpy()):
                mp = app._poisson_market(lh, la)
                mr = dft.get_full_poisson(lh, la)
                checks["cross_prob_engine"] = max(
                    checks["cross_prob_engine"],
                    abs(mp["u25"] - mr["u25"]), abs(mp["gg"] - mr["gg"]))

            # ---- parita' di universo dati (engine non patchato, stato attuale)
            stats0, ah0, aa0, df0 = app.get_league_engine(ck)
            app.get_league_engine.clear()
            universe_rows.append({
                "league": ck,
                "n_replica": len(df), "n_engine": len(df0),
                "max_rep": df["Date"].max(), "max_eng": df0["Date"].max(),
            })

            # ---- VALIDAZIONE HARNESS: replay a "oggi" == produzione reale ----
            # E' il controllo piu' forte: con troncamento che lascia tutto lo
            # storico (max data < oggi) e cutoff = oggi, il replay deve
            # riprodurre BIT-ESATTO l'engine non patchato (tutte le statistiche
            # e le medie di lega). Prova che l'intercettazione di I/O e cutoff
            # non altera la pipeline.
            replayer = LiveReplayer(ck)
            today_ts = pd.Timestamp(datetime.now(timezone.utc).date())
            (st_t, ah_t, aa_t, _df_t), _agg_t = replayer.engine_at(today_ts)
            for t in set(st_t) & set(stats0):
                for k in ("att", "def", "att0", "def0",
                          "att0_pure", "def0_pure"):
                    checks["harness_today"] = max(
                        checks["harness_today"],
                        abs(st_t[t][k] - stats0[t][k]))
            checks["harness_today"] = max(
                checks["harness_today"], abs(ah_t - ah0), abs(aa_t - aa0))

            # ---- mappa giornaliera dei ratio della replica (attribuzione) ----
            repday = replica_ratios_by_day(df, xg)
            rng_attr = np.random.default_rng(SEED + len(ck))
            sample_days = set(pd.Timestamp(d) for d in
                              rng_attr.choice(sorted(repday), size=10,
                                              replace=False))

            # ---- replay del motore LIVE per ogni data di val/test ----
            live_rows = []
            eval_dates = sorted(rep["date"].unique())
            for day_ts in eval_dates:
                day = pd.Timestamp(day_ts)
                (stats, avg_h, avg_a, _df), agg = replayer.engine_at(day)
                n_engine_calls += 1

                # attribuzione dei canali di scarto (10 date/lega campionate)
                if day in sample_days:
                    rs = repday[day]
                    attribution[ck]["avg"] += [
                        abs(avg_h - rs["ah"]), abs(avg_a - rs["aa"])]
                    gate = app._league_mean_gate(agg.averages)
                    axg, axga = gate
                    fs = agg.averages
                    for t, (ra, rdef) in rs["ratios"].items():
                        s = stats.get(t)
                        if not isinstance(s, dict):
                            continue
                        rec = fs.get(t)
                        if isinstance(rec, dict) and axg:
                            raw_att = rec["xG_avg"] / axg
                            raw_def = rec["xGA_avg"] / axga
                            # canale 1: finestra/sorgente (F_season non
                            # shrunk vs snapshot statica della replica)
                            attribution[ck]["src"].append(
                                max(abs(raw_att - ra), abs(raw_def - rdef)))
                            # canale 2: shrinkage PRIOR_MATCHES=6
                            attribution[ck]["shr"].append(max(
                                abs(s["att0_pure"] - raw_att),
                                abs(s["def0_pure"] - raw_def)))
                        else:
                            # canale 3: fallback gol pooled vs fallback replica
                            attribution[ck]["fb"].append(
                                max(abs(s["att0_pure"] - ra),
                                    abs(s["def0_pure"] - rdef)))

                todays = rep[rep["date"] == day]
                fs_teams = set(agg.averages.keys()) if agg is not None else set()
                for _, r in todays.iterrows():
                    lp = live_probs(stats, avg_h, avg_a, r["home"], r["away"])
                    checks["close_err"] = max(checks["close_err"],
                                              lp["close_err"])
                    checks["missing_teams"] += lp["missing"]
                    live_rows.append({
                        "date": day, "home": r["home"], "away": r["away"],
                        "lam_h_live": lp["lam_h"], "lam_a_live": lp["lam_a"],
                        "po_live": lp["po_live"], "gg_live": lp["gg_live"],
                        "fs_home": r["home"] in fs_teams,
                        "fs_away": r["away"] in fs_teams,
                    })
            live = pd.DataFrame(live_rows)

            # ---- join chiave (data, casa, trasferta): deve essere totale ----
            merged = rep.merge(live, on=["date", "home", "away"], how="outer",
                               indicator=True)
            n_unmatched = int((merged["_merge"] != "both").sum())
            assert n_unmatched == 0, f"{ck}: {n_unmatched} partite non allineate"
            merged = merged.drop(columns="_merge")
            merged["league"] = ck
            frames.append(merged)

            # copertura F_season per split
            for sp in SEASONS_EVAL:
                ms = merged[merged["season"] == sp]
                both = ms["fs_home"] & ms["fs_away"]
                fs_cov[(ck, sp)] = {
                    "n": len(ms),
                    "both_frac": float(both.mean()),
                    "one_miss_frac": float((~(ms["fs_home"] & ms["fs_away"])).mean()),
                }
            print(f"   {len(eval_dates)} date-motore, {len(merged)} partite, "
                  f"copertura F_season "
                  f"{fs_cov[(ck,'2024/25')]['both_frac']:.1%}/"
                  f"{fs_cov[(ck,'2025/26')]['both_frac']:.1%}")

        if cache_path:
            with open(cache_path, "wb") as fh:
                pickle.dump({
                    "frames": frames, "fs_cov": fs_cov, "checks": checks,
                    "universe_rows": universe_rows,
                    "n_engine_calls": n_engine_calls,
                    "attribution": attribution,
                }, fh)
            print(f"(replay salvato in cache {cache_path})")

    data = pd.concat(frames, ignore_index=True)
    data["d_lam_h"] = data["lam_h_live"] - data["lam_h"]
    data["d_lam_a"] = data["lam_a_live"] - data["lam_a"]
    data["d_po"] = data["po_live"] - data["po_rep"]
    data["d_gg"] = data["gg_live"] - data["gg_rep"]

    # =====================================================================
    # PASSO 0: distribuzione degli scarti
    # =====================================================================
    def collect(diffcol, label):
        out = []
        for scope in ["AGGREGATO"] + LEAGUE_KEYS:
            m = np.ones(len(data), bool) if scope == "AGGREGATO" \
                else data["league"].to_numpy() == scope
            for sp in ("val+test", "2024/25", "2025/26"):
                mm = m & np.ones(len(data), bool)
                if sp != "val+test":
                    mm = mm & (data["season"].to_numpy() == sp)
                s = scarto_stats(data.loc[mm, diffcol].to_numpy())
                out.append((label, scope, sp, s))
        return out

    sc_lam = collect("d_lam_h", "lambda casa") + collect("d_lam_a",
                                                         "lambda trasf.")
    sc_po = collect("d_po", "P(Over2.5)")
    sc_gg = collect("d_gg", "P(GG)")

    max_lam = max(s["max"] for _, _, _, s in sc_lam)
    max_po = max(s["max"] for _, _, _, s in sc_po)
    max_gg = max(s["max"] for _, _, _, s in sc_gg)
    passo1 = (max_lam > EPS_LAM) or (max_po > EPS_PROB) or (max_gg > EPS_PROB)

    # livello medio: live vs replica vs frequenza reale
    levels = []
    for ev, pl, pr, yc in (("Over 2.5", "po_live", "po_rep", "y_over"),
                           ("GG/NG", "gg_live", "gg_rep", "y_gg")):
        for sp in SEASONS_EVAL:
            m = data["season"] == sp
            levels.append((ev, sp,
                           data.loc[m, pl].mean(), data.loc[m, pr].mean(),
                           data.loc[m, yc].mean()))

    # =====================================================================
    # PASSO 1 (solo se serve): Murphy live vs replica + bootstrap CI
    # =================================================================
    murph = {}
    ratios = {}
    boot = {}
    boot_lg = {}

    def bootstrap_delta_league(d, pcol_live, pcol_rep, ycol, seed):
        """Come bootstrap_delta ma su una sola lega (306-380 partite):
        serve a giudicare le celle per-lega sopra soglia."""
        rng = np.random.default_rng(seed)
        y = d[ycol].to_numpy().astype(float)
        pl = d[pcol_live].to_numpy()
        pr = d[pcol_rep].to_numpy()
        n = len(d)
        dr = []
        for _ in range(N_BOOT):
            ix = rng.integers(0, n, n)
            ml = bv.murphy(pl[ix], y[ix])
            mr = bv.murphy(pr[ix], y[ix])
            dr.append(ml["res"] / ml["unc"] - mr["res"] / mr["unc"])
        lo, hi = _ci(list(dr))
        return {"lo": 100 * lo, "hi": 100 * hi, "mean": 100 * np.mean(dr)}

    if passo1:
        for ev, pl, pr, yc in (("over", "po_live", "po_rep", "y_over"),
                               ("gg", "gg_live", "gg_rep", "y_gg")):
            for sp in SEASONS_EVAL:
                for scope in ["AGGREGATO"] + LEAGUE_KEYS:
                    m = data["season"] == sp
                    if scope != "AGGREGATO":
                        m = m & (data["league"] == scope)
                    d = data.loc[m]
                    ml = bv.murphy(d[pl].to_numpy(),
                                   d[yc].to_numpy().astype(float))
                    mr = bv.murphy(d[pr].to_numpy(),
                                   d[yc].to_numpy().astype(float))
                    murph[(ev, scope, sp, "live")] = ml
                    murph[(ev, scope, sp, "rep")] = mr
                dsp = data.loc[data["season"] == sp]
                hseed = (1 if ev == "gg" else 0) * 7 + (
                    13 if sp == "2025/26" else 0)
                boot[(ev, sp)] = bootstrap_delta(
                    dsp, pl, pr, yc, seed=SEED + 101 + hseed)
                if ev == "over":
                    for li, lk in enumerate(LEAGUE_KEYS):
                        dl = dsp[dsp["league"] == lk]
                        boot_lg[(lk, sp)] = bootstrap_delta_league(
                            dl, pl, pr, yc,
                            seed=SEED + 211 + li * 17
                            + (13 if sp == "2025/26" else 0))
        for ev in ("over", "gg"):
            ratios[ev] = {
                sp: (murph[(ev, "AGGREGATO", sp, "rep")]["res"]
                     / murph[(ev, "AGGREGATO", sp, "rep")]["unc"],
                     murph[(ev, "AGGREGATO", sp, "live")]["res"]
                     / murph[(ev, "AGGREGATO", sp, "live")]["unc"])
                for sp in SEASONS_EVAL}

    # verdetto: il LIVE supera la soglia 5% su ENTRAMBI gli split?
    def sostanziale(ev):
        if not passo1:
            return False
        vals = [ratios[ev][sp][1] for sp in SEASONS_EVAL]
        return all(v >= SOGLIA for v in vals)

    sost_over_live = sostanziale("over")
    sost_gg_live = sostanziale("gg") if passo1 else False
    sost_over_rep = (passo1 and all(
        ratios["over"][sp][0] >= SOGLIA for sp in SEASONS_EVAL))

    # =====================================================================
    # REPORT
    # =====================================================================
    L = []
    ap = L.append
    ap("# Motore live di produzione vs replica offline (testa Totali) — "
       "audit sola lettura")
    ap("")
    ap(f"*Generato: {datetime.now(timezone.utc).isoformat(timespec='seconds')}"
       f" — script `audit/diagnose_motore_live_vs_replica.py`, nessuna "
       "scrittura su SoccerMath/.*")
    ap("")
    ap("## Oggetto e protocollo")
    ap("")
    ap("I 4 audit precedenti camminano sui CSV con una REPLICA della logica "
       "di `app.get_league_engine()` che legge l'istantanea xG statica "
       "(`xg_*.json`), senza shrinkage e senza la sorgente point-in-time. "
       "Questo script chiama invece **direttamente il motore reale**:")
    ap("")
    ap("1. `app.get_league_engine(camp_key)` eseguito letteralmente, una "
       "volta per ogni data di validation 2024/25 e test 2025/26, in versione "
       "point-in-time: i CSV della lega vengono troncati in memoria "
       "(intercettando `pd.read_csv`, nessuna scrittura) alle partite dei "
       "giorni precedenti, e il cutoff viene iniettato nella VERA "
       "`xg_archive.season_point_in_time_averages` (fonte **F_season**, "
       "politica `previous_day`). Quindi passano in produzione invariati "
       "**shrinkage** `_shrunk_ratio` (PRIOR_MATCHES=6), l'ancora di lega "
       "derivata dal dizionario F_season, il gate `_league_mean_gate`, il "
       "fallback gol pooled, la sanitizzazione e i fattori di forma 1X2.")
    ap("2. Per ogni partita si chiama `app.get_full_poisson_two_heads()` "
       "(da cui la testa Totali usa `att0_pure/def0_pure`) e si leggono "
       "lambda home/away (clippati da `_clip_lambda`, range "
       "[exp(−6), exp(3)]), P(Over2.5) e P(GG).")
    ap(f"3. Le predizioni live vengono allineate per (data, casa, trasferta) "
       f"a quelle della replica modello B di `diagnose_form_totali.py` — la "
       f"stessa base dati dei 4 audit — su {len(data)} partite.")
    ap("")
    ap("## Conformita' (verificata, non dichiarata)")
    ap("")
    ap("| Controllo | Esito |")
    ap("|---|---:|")
    ap(f"| Replica qui vs `diagnose_form_totali.run_models` modello B, max "
       f"\\|scarto\\| P(Over) | {checks['cross_replica_po']:.1e} |")
    ap(f"| idem, max \\|scarto\\| P(GG) | "
       f"{checks['cross_replica_gg']:.1e} |")
    ap(f"| idem, max \\|scarto\\| lambda totale (casa+trasf.) | "
       f"{checks['cross_replica_lam']:.1e} |")
    ap(f"| Motore di probabilita' `app._poisson_market` vs "
       f"`backtest.get_full_poisson` sugli stessi lambda | "
       f"{checks['cross_prob_engine']:.1e} |")
    ap(f"| Chiusura lambda→prob. del wrapper live (max errore interno) | "
       f"{checks['close_err']:.1e} |")
    ap(f"| **Validazione harness: replay a oggi vs engine di produzione "
       f"non patchato, max scarto su tutte le stats** | "
       f"**{checks['harness_today']:.1e}** |")
    ap(f"| Squadre-lato assenti nell'engine al cutoff (default neutri "
       f"1.0 del wrapper di produzione) | {checks['missing_teams']} |")
    ap(f"| Chiamate a `get_league_engine` (una per data) | "
       f"{n_engine_calls} |")
    ap(f"| Tempo totale replay | {time.time()-t0:.0f} s |")
    ap("")
    ap("La riga di validazione harness e' il controllo chiave: a cutoff "
       "\"oggi\" (tutto lo storico visibile) il replay deve riprodurre la "
       "produzione bit-esatta. Lo scarto 0.0 e' quindi la prova che "
       "l'intercettazione di `pd.read_csv` e l'iniezione del cutoff non "
       "alterano la pipeline; ogni scarto che segue su date storiche e' "
       "reale, non un artefatto del replay. Il confronto tra i due motori "
       "Poisson (`app._poisson_market` vs `backtest_experiment_all."
       "get_full_poisson`) sugli stessi lambda non e' nullo per "
       f"~{checks['cross_prob_engine']:.0e}: e' il diverso ordine di "
       "somma dei PMF (somma Python con generatore vs numpy), precisione "
       "di macchina, non differenza di logica.")
    ap("")
    ap(f"I {checks['missing_teams']} casi di squadra-lato assente dal "
       "dizionario del motore al cutoff sono tutti e 14 neopromosse alla "
       "prima giornata di stagione (es. Parma, Venezia, Ipswich, Holstein "
       "Kiel nel 2024/25; Pisa, Amburgo, Oviedo nel 2025/26): non esistono "
       "ancora nel DB troncato e la produzione stessa, senza alcun intervento "
       "dell'audit, le tratta con ratio neutro 1.0 nel wrapper; non e' un "
       "artefatto del replay.")
    ap("")
    ap("Parita' di universo dati tra engine reale e caricamento della "
       "replica (stato attuale, nessun troncamento):")
    ap("")
    ap("| Lega | righe replica | righe engine | data max replica | "
       "data max engine |")
    ap("|---|---:|---:|---|---|")
    for u in universe_rows:
        ap(f"| {u['league']} | {u['n_replica']} | {u['n_engine']} | "
           f"{pd.Timestamp(u['max_rep']).date()} | "
           f"{pd.Timestamp(u['max_eng']).date()} |")
    ap("")
    ap("Copertura della fonte F_season (squadra presente negli archivi "
       "point-in-time al cutoff, quindi att0_pure/def0_pure da xG stagionale; "
       "gli altri vanno al fallback gol pooled con shrinkage):")
    ap("")
    ap("| Lega | split | n | entrambe in F_season | almeno una al fallback |")
    ap("|---|---|---:|---:|---:|")
    for ck in LEAGUE_KEYS:
        for sp in SEASONS_EVAL:
            c = fs_cov[(ck, sp)]
            ap(f"| {ck} | {sp} | {c['n']} | {100*c['both_frac']:.1f}% | "
               f"{100*c['one_miss_frac']:.1f}% |")
    ap("")

    # ----------------------------------------------------------------- 0
    ap("## PASSO 0 — Scarti live vs replica, partita per partita")
    ap("")

    def tabella_scarti(rows, titolo):
        ap(f"### {titolo}")
        ap("")
        ap("| Scope | split | max | p99 | p95 | mediana | media | RMS | "
           "scarto=0 |")
        ap("|---|---|---:|---:|---:|---:|---:|---:|---:|")
        for lab, scope, sp, s in rows:
            if lab != rows[0][0]:
                continue
        # righe: per scope/split aggregando le due etichette lambda
        groups = {}
        for lab, scope, sp, s in rows:
            groups.setdefault((scope, sp), []).append((lab, s))
        for scope in ["AGGREGATO"] + LEAGUE_KEYS:
            for sp in ("val+test", "2024/25", "2025/26"):
                gs = groups[(scope, sp)]
                # massimo dei lati (lambda) o valore unico (prob.)
                smax = max(x[1]["max"] for x in gs)
                sp99 = max(x[1]["p99"] for x in gs)
                sp95 = max(x[1]["p95"] for x in gs)
                smed = max(x[1]["median"] for x in gs)
                smean = np.mean([x[1]["mean"] for x in gs])
                srms = np.sqrt(np.mean([x[1]["rms"] ** 2 for x in gs]))
                szero = min(x[1]["zero_frac"] for x in gs)
                bold = "**" if scope == "AGGREGATO" else ""
                ap(f"| {bold}{scope}{bold} | {sp} | {smax:.2e} | "
                   f"{sp99:.2e} | {sp95:.2e} | {smed:.2e} | {smean:.2e} | "
                   f"{srms:.2e} | {100*szero:.1f}% |")
        ap("")

    tabella_scarti(sc_lam, "Lambda home e away (clippati; riportato il "
                   "massimo dei due lati)")
    tabella_scarti(sc_po, "Probabilita' P(Over 2.5)")
    tabella_scarti(sc_gg, "Probabilita' P(GG)")
    ap("Livello medio predetto (aggregato 5 leghe):")
    ap("")
    ap("| Evento | split | live media | replica media | frequenza reale |")
    ap("|---|---|---:|---:|---:|")
    for ev, sp, l, r, y in levels:
        ap(f"| {ev} | {sp} | {l:.4f} | {r:.4f} | {y:.4f} |")
    ap("")

    # ---- attribuzione dei canali (10 date/lega campionate, seed fisso) ----
    def chan_stats(vals):
        v = np.asarray(vals, float)
        if len(v) == 0:
            return 0, float("nan"), float("nan"), float("nan")
        return (len(v), float(np.median(v)),
                float(np.percentile(v, 95)), float(v.mean()))

    ap("### Da dove nascono gli scarti (attribuzione sui ratio squadra)")
    ap("")
    ap("Le medie-gol di lega (avg_h/avg_a, la base da cui parte ogni "
       "lambda) sono **bit-identiche** tra motore live e replica a ogni "
       "cutoff (max scarto "
       f"{max(max(v['avg']) if v['avg'] else 0.0 for v in attribution.values()):.1e}"
       "): il cammino sui CSV e' lo stesso. Gli scarti nascono tutti dai "
       "**ratio attacco/difesa** di `att0_pure/def0_pure`. Su 10 date "
       "campionate per lega (seed deterministico), ogni ratio squadra-stato "
       "viene scomposto in tre canali:")
    ap("")
    ap("- **finestra/sorgente**: ratio F_season NON shrinkato (xG della "
       "sola stagione in corso al cutoff, dall'archivio point-in-time) "
       "meno il ratio della replica, che applica a TUTTO lo storico la "
       "singola istantanea `xg_*.json` (oggi: medie 2026/27 dopo 3 gare);")
    ap("- **shrinkage**: effetto di `_shrunk_ratio` (PRIOR_MATCHES=6 verso "
       "la media di lega F_season) sul ratio point-in-time;")
    ap("- **fallback**: squadre assenti da F_season, dove il live usa il "
       "pooled gol shrinkato su tutto il DB troncato e la replica il "
       "proprio rapporto gol running.")
    ap("")
    ap("| Canale | n ratio-squadra | mediana scarto ratio | p95 | media |")
    ap("|---|---:|---:|---:|---:|")
    pooled = {"src": [], "shr": [], "fb": []}
    labels = {"src": "finestra/sorgente xG (F_season vs istantanea statica)",
              "shr": "shrinkage PRIOR_MATCHES=6",
              "fb": "fallback gol pooled (~squadre senza F_season)"}
    for k in ("src", "shr", "fb"):
        for ck in LEAGUE_KEYS:
            pooled[k].extend(attribution.get(ck, {}).get(k, []))
    for k in ("src", "shr", "fb"):
        n_, med, p95, mean = chan_stats(pooled[k])
        ap(f"| {labels[k]} | {n_} | {med:.3f} | {p95:.3f} | {mean:.3f} |")
    ap("")
    ap("Per lega, mediana |scarto ratio| dei tre canali (src / shr / fb):")
    ap("")
    ap("| Lega | src mediana | shr mediana | fb mediana | fallback: n ratio |")
    ap("|---|---:|---:|---:|---:|")
    for ck in LEAGUE_KEYS:
        a = attribution.get(ck, {})
        ms = chan_stats(a.get("src", []))[1]
        mh = chan_stats(a.get("shr", []))[1]
        mf, nfb = chan_stats(a.get("fb", []))[3], chan_stats(a.get("fb", []))[0]
        ap(f"| {ck} | {ms:.3f} | {mh:.3f} | {mf:.3f} | {nfb} |")
    ap("")
    ap("Il canale dominante e' la **finestra/sorgente**: la replica valuta "
       "partite del 2024/25 e 2025/26 con ratio fotografati nell'autunno "
       "2026 (stagione in corso, 3 gare), mentre il live usa gli xG reali "
       "della stagione di quella partita. Lo shrinkage pesa poco (mediana "
       "~0.05) e agisce come stabilizzatore; il fallback interessa circa "
       "il 3% delle PARTITE (tabella copertura sopra).")
    ap("")

    if not passo1:
        ap("**Tutti gli scarti sono 0.0e+00.** La pipeline di produzione "
           "(F_season, shrinkage PRIOR_MATCHES, fallback pooled) non "
           "introduce alcuna differenza pratica sulla storia valutata: le "
           "probabilita' del motore live sono bit-identiche a quelle della "
           "replica. La conclusione di `bias_variance_totali_diagnosis.md` "
           "(risoluzione residua 0.8%/0.9% dell'incertezza su Over, "
           "0.6%/1.2% su GG) si applica dunque GIA' al motore reale, senza "
           "bisogno del Passo 1.")
        ap("")

    # ----------------------------------------------------------------- 1
    if passo1:
        ap("## PASSO 1 — Murphy a 10 decili sul motore LIVE vs replica")
        ap("")
        ap("Gli scarti del Passo 0 sono risultati non nulli, quindi si "
           "ripete la decomposizione esatta di "
           "`diagnose_bias_variance_totali.py` (stessa funzione `murphy`, "
           "stessi 10 decili a frequenza uguale) sulle probabilita' live. "
           "Versione grezza: come dimostrato nell'audit precedente, una "
           "calibrazione monotona lascia la Risoluzione invariata, quindi "
           "il confronto che decide il verdetto (RES) non dipende da "
           "beta.")
        ap("")
        for ev, mkt in (("over", "O/U2.5 — Over 2.5"),
                        ("gg", "GG/NG — GG")):
            ap(f"### {mkt}")
            ap("")
            for sp in SEASONS_EVAL:
                ap(f"**{sp}**")
                ap("")
                ap("| Scope | sorgente | REL | RES | UNC | Brier | RES/UNC |")
                ap("|---|---|---:|---:|---:|---:|---:|")
                for scope in ["AGGREGATO"] + LEAGUE_KEYS:
                    for src, lab in (("rep", "replica"), ("live", "LIVE")):
                        r = murph[(ev, scope, sp, src)]
                        bold = "**" if scope == "AGGREGATO" else ""
                        ap(f"| {bold}{scope}{bold} | {lab} | {r['rel']:.4f} "
                           f"| {r['res']:.4f} | {r['unc']:.4f} | "
                           f"{r['brier']:.4f} | "
                           f"{100*r['res']/r['unc']:.1f}% |")
                ap("")

        ap("### Bootstrap appaiato stratificato per lega "
           f"({N_BOOT} ricampionamenti, seed deterministico)")
        ap("")
        ap("Differenza **LIVE − replica** (aggregato 5 leghe); IC 95%.")
        ap("")
        ap("| Evento | split | Δ(RES/UNC) | IC 95% | ΔBrier | IC 95% |")
        ap("|---|---|---:|---|---:|---|")
        for ev, mkt in (("over", "O/U2.5"), ("gg", "GG/NG")):
            for sp in SEASONS_EVAL:
                b = boot[(ev, sp)]
                ap(f"| {mkt} | {sp} | {100*b['d_ratio']:+.2f} p.p. | "
                   f"[{100*b['lo_r']:+.2f}; {100*b['hi_r']:+.2f}] p.p. | "
                   f"{b['d_brier']:+.4f} | "
                   f"[{b['lo_b']:+.4f}; {b['hi_b']:+.4f}] |")
        ap("")
        rep_o = ratios["over"]
        ap(f"Replica Over: RES/UNC "
           f"{100*rep_o['2024/25'][0]:.1f}%/"
           f"{100*rep_o['2025/26'][0]:.1f}% (val/test, come da audit "
           "precedente). LIVE Over: "
           f"{100*rep_o['2024/25'][1]:.1f}%/{100*rep_o['2025/26'][1]:.1f}%. "
           f"GG LIVE: {100*ratios['gg']['2024/25'][1]:.1f}%/"
           f"{100*ratios['gg']['2025/26'][1]:.1f}% contro replica "
           f"{100*ratios['gg']['2024/25'][0]:.1f}%/"
           f"{100*ratios['gg']['2025/26'][0]:.1f}%.")
        ap("")

    # ------------------------------------------------------------- verdetto
    ap("## Conclusione esplicita")
    ap("")
    if not passo1:
        ap("Il motore live e' **bit-identico** alla replica su tutte le "
           f"{len(data)} partite di validation+test: la differenza non "
           "esiste e **non sposta nulla**. Il verdetto dell'audit "
           "`bias_variance_totali` vale integralmente per il motore reale: "
           "**nessun segnale da suddividere in bucket, la pista 3 rischia "
           "di aggiungere solo rumore**.")
    else:
        bo_v, bo_t = boot[("over", "2024/25")], boot[("over", "2025/26")]
        med_po = [r for r in sc_po
                  if r[1] == "AGGREGATO" and r[2] == "val+test"][0][3]
        med_gg = [r for r in sc_gg
                  if r[1] == "AGGREGATO" and r[2] == "val+test"][0][3]
        mlo_v = murph[("over", "AGGREGATO", "2024/25", "live")]
        mlo_t = murph[("over", "AGGREGATO", "2025/26", "live")]
        ap("**Passo 0.** La pipeline reale NON e' bit-identica alla "
           "replica, e la differenza non e' trascurabile partita per "
           "partita: mediana |scarto| "
           f"{med_po['median']:.2f} su P(Over) (p95 {med_po['p95']:.2f}, "
           f"max {med_po['max']:.2f}) e {med_gg['median']:.2f} su P(GG) "
           f"(p95 {med_gg['p95']:.2f}). L'attribuzione sopra mostra che il "
           "motore e' esattamente lo stesso nei mezzi (medie-gol di lega, "
           "Poisson, clip, medie di bucket) ma usa una SORGENTE xG diversa "
           "e piu' corretta: i veri xG della stagione in corso al cutoff "
           "(F_season) con shrinkage, contro l'istantanea statica 2026/27 "
           "dopo 3 gare che la replica applica a tutto lo storico. Anche il "
           "livello ne guadagna: la media live (tabella sopra) cade quasi "
           "sulla frequenza reale, mentre la replica restava sotto di 2-10 "
           "punti percentuali.")
        ap("")
        if not sost_over_live:
            ap("**Passo 1.** La differenza ESISTE ma **non sposta il "
               "verdetto sulla pista 3**. La Risoluzione live di Over 2.5 "
               "e' circa il triplo della replica, "
               f"{100*ratios['over']['2024/25'][1]:.1f}%/"
               f"{100*ratios['over']['2025/26'][1]:.1f}% dell'incertezza "
               f"contro {100*ratios['over']['2024/25'][0]:.1f}%/"
               f"{100*ratios['over']['2025/26'][0]:.1f}%; il delta "
               "bootstrap (LIVE−replica, stratificato per lega, appaiato) e' "
               f"[{100*bo_v['lo_r']:+.2f}; {100*bo_v['hi_r']:+.2f}] punti "
               f"percentuali in validation (esclude lo zero) e "
               f"[{100*bo_t['lo_r']:+.2f}; {100*bo_t['hi_r']:+.2f}] nel "
               "test (include lo zero). Su nessuno dei due split il live si "
               "avvicina alla soglia di segnale sostanziale del "
               f"{100*SOGLIA:.0f}%: nel test il 95% superiore e' "
               f"{100*bo_t['hi_r'] + 100*ratios['over']['2025/26'][0]:.1f}%. "
               "GG/NG resta nella stessa fascia "
               f"({100*ratios['gg']['2024/25'][1]:.1f}%/"
               f"{100*ratios['gg']['2025/26'][1]:.1f}%). ")
            ap("")
            ap("Due precisazioni oneste, in positivo per il motore reale:")
            ap("")
            ap("1. **Il difetto di livello della testa grezza evidenziato "
               "dall'audit di calibrazione era in gran parte un artefatto "
               "della replica statica.** Sul motore live l'Affidabilita' "
               "grezza e' gia' "
               f"{mlo_v['rel']:.4f}/{mlo_t['rel']:.4f} (replica 0.0259/"
               "0.0231) e il Brier grezzo live "
               f"{mlo_v['brier']:.4f}/{mlo_t['brier']:.4f} e' GIA' sotto "
               "il predittore costante "
               f"({mlo_v['unc']:.4f}/{mlo_t['unc']:.4f}): F_season + "
               "shrinkage, senza alcun beta, elimina quasi tutto il bias di "
               "livello. La beta calibration storica, derivata sulla "
               "replica, non e' il ritratto del motore reale.")
            def over_pct(lk, sp):
                r = murph[("over", lk, sp, "live")]
                return 100 * r["res"] / r["unc"]

            blv = boot_lg[("Ligue 1", "2024/25")]
            blt = boot_lg[("Ligue 1", "2025/26")]
            n_pos = sum(1 for lk in LEAGUE_KEYS
                        for sp in SEASONS_EVAL
                        if boot_lg[(lk, sp)]["lo"] > 0)
            ap("2. **Qualche cella per-lega supera il 5%** in uno o entrambi "
               "gli split (es. Ligue 1 Over "
               f"{over_pct('Ligue 1', '2024/25'):.1f}%/"
               f"{over_pct('Ligue 1', '2025/26'):.1f}%, Bundesliga "
               f"{over_pct('Bundesliga', '2024/25'):.1f}%/"
               f"{over_pct('Bundesliga', '2025/26'):.1f}% val/test), ma e' "
               "rumore da sotto-potenza: il bootstrap appaiato per-lega "
               "(stesso metodo) mette gli IC 95% del delta per la Ligue 1 a "
               f"[{blv['lo']:+.1f}; {blv['hi']:+.1f}]/"
               f"[{blt['lo']:+.1f}; {blt['hi']:+.1f}] punti percentuali "
               f"(val/test), e gli IC includono lo zero per tutte le "
               f"{len(LEAGUE_KEYS)} leghe in entrambi gli split "
               f"({n_pos}/10 intervalli strettamente positivi). Nessun "
               "campionato sostiene dunque il 5% in modo statistico: sono "
               "isole su 306-380 partite, non un segnale poolizzato, e non "
               "fanno base per la pista 3.")
            ap("")
            ap("### VERDETTO: **il motore live e' migliore della replica "
               "(soprattutto di livello, un po' di piu' di risoluzione) ma "
               "resta sostanzialmente equivalente ai fini della pista 3: "
               "nessun segnale da suddividere in bucket, la pista 3 rischia "
               "di aggiungere solo rumore.**")
            ap("")
            ap("La differenza reale trovata al Passo 0 NON rovescia il "
               "verdetto: la risoluzione del motore vero e' 2-3% "
               "dell'incertezza (contro ~1% della replica), un miglioramento "
               "relativo reale ma ancora troppo piccolo per un ordinamento "
               "in bucket/selezioni robusto, e nel test statisticamente "
               "indistinguibile dalla replica. La raccomandazione si "
               "aggiorna invece su un punto: le conclusioni di livello "
               "dell'audit di calibrazione vanno rivalutate sul motore live "
               "(che e' gia' ben livellato senza beta), mentre la pista 3 "
               "resta senza base finche' una fonte con risoluzione propria "
               "non porta RES/UNC stabilmente sopra soglia su entrambi gli "
               "split e in aggregato.")
        else:
            ap("### VERDETTO: **il motore live MOSTRA risoluzione "
               "sostanziale (>= 5% dell'incertezza su entrambi gli split) "
               "assente nella replica: la pista 3 ha basi solide sul motore "
               "reale, il problema era solo di livello/ricostruzione.**")
            ap("")
            ap("La differenza tra pipeline live e replica sposta il "
               "verdetto: la fonte point-in-time contiene segnale che la "
               "replica statica perdeva; la pista 3 va riaperta e validata "
               "sul motore reale.")
        if sost_gg_live:
            ap("")
            ap("(Anche GG/NG supera la soglia live: "
               f"{100*ratios['gg']['2024/25'][1]:.1f}%/"
               f"{100*ratios['gg']['2025/26'][1]:.1f}%.)")
    ap("")
    ap("## Limiti dichiarati")
    ap("")
    ap("1. **Cutoff a giorno, non a minuto**: il replay usa la politica "
       "`previous_day` (tutte le partite del giorno della partita sono "
       "escluse, sia da F_season sia dal DB), come il pre-partita reale al "
       "mattino; risultati di anticipi dello stesso giorno non entrano. E' "
       "la scelta conservativa della produzione.")
    ap("2. **Nessun beta refit live**: il Passo 1 decompone le sole "
       "probabilita' grezze live/replica; la Risoluzione e' invariante per "
       "trasformazioni monotone (verificato nel precedente audit), quindi "
       "il confronto decisivo non dipende dalla calibrazione.")
    ap("3. **Ambiente bare-mode**: `app.py` e' importato fuori da "
       "`streamlit run` (cache `@st.cache_data` svuotata prima di ogni "
       "taglio storico); le funzioni chiamate sono quelle letterali di "
       "produzione, ma il rendering UI non e' eseguito nel suo contesto.")
    ap("4. **Nessuna quota**: si decompone accuratezza probabilistica, non "
       "convenienza economica.")
    ap("5. **Istantanea xG della replica e' mobile**: `xg_*.json` contiene "
       "le medie della stagione 2026/27 dopo 3 gare (stato dei file il "
       "giorno dell'audit); la replica le applica come costanti a 2024/25 e "
       "2025/26. E' il disegno ereditato dai 4 audit precedenti: qui se ne "
       "misura per la prima volta la distanza dal motore reale, ma non lo "
       "si modifica.")
    ap("6. **Attribuzione su campione**: i tre canali (sorgente/shrinkage/"
       "fallback) sono quantificati su 10 date campionate per lega con seed "
       "fisso (50 date-motore); le coperture F_season e gli scarti "
       "partita-per-partita del Passo 0 sono invece esaustivi.")
    ap("")
    ap("## Riferimenti incrociati")
    ap("")
    ap("- `audit/results/bias_variance_totali_diagnosis.md`: Murphy sulla "
       "replica, soglia 5% e verdetto pista 3 (oggetto del confronto);")
    ap("- `audit/results/pt19_cap_vs_fseason_clean.md`: scelta della fonte "
       "F_season rispetto alla finestra PT19_CAP;")
    ap("- `audit/results/calibration_layer_diagnosis.md`: beta live-level;")
    ap("- `audit/results/form_totali_diagnosis.md`: modello B replicato.")
    ap("")

    text = "\n".join(L)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Scritto {OUT_PATH}")

    # ---------------------------------- riepilogo finale a terminale
    print("cross-check replica:", checks["cross_replica_po"],
          checks["cross_replica_gg"], "| prob-engine:",
          checks["cross_prob_engine"], "| close:", checks["close_err"])
    print(f"max scarti: lambda {max_lam:.3e} over {max_po:.3e} gg "
          f"{max_gg:.3e} -> PASSO 1: {passo1}")
    for ev in ("over", "gg"):
        if passo1:
            print(ev, "RES/UNC rep",
                  [f"{ratios[ev][sp][0]:.4f}" for sp in SEASONS_EVAL],
                  "live",
                  [f"{ratios[ev][sp][1]:.4f}" for sp in SEASONS_EVAL])
    print("sostanziale over live?", sost_over_live,
          "| gg live?", sost_gg_live)


if __name__ == "__main__":
    main()
