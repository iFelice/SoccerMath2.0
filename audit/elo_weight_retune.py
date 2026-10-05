"""
elo_weight_retune.py — Punto 2 roadmap Elo: ritaratura del peso w del blend
1X2 ``w*Poisson + (1-w)*Elo`` con un walker Elo FEDELE ALLA PRODUZIONE.
AUDIT SOLA LETTURA: non modifica alcun file di produzione, non cambia
``app.POISSON_1X2_WEIGHT`` (0.25), non propone patch applicate.

Componenti importate dalla PRODUZIONE (non riscritte):
  * Elo:     audit/elo_walker_core.py -> models.elo_engine.EloEngine +
             models.elo_engine.predict_elo_probs
  * Blend:   app.blend_elo_into_1x2
  * Poisson: audit/diagnose_clv_pinnacle.run_model_with_elo (colonne prodn_*),
             ramo NORM-SUM bit-faithful a diagnose_production_baseline.run_models
  * Metriche: diagnose_production_baseline.brier_ll_1x2
  * Bootstrap: topmix_margins.N_BOOT / SEED / _ci

Dalla stessa ``run_model_with_elo`` si prendono anche le colonne ``elo_*``
della VECCHIA REPLICA (K fisso 24, nessun moltiplicatore per scarto) per
quantificare il mismatch rispetto al walker fedele (punto A.4).

Split (letto dal repo, non dedotto): diagnose_production_baseline.TRAIN_SEASONS
e SEASONS_EVAL. Burn-in: la prima stagione disponibile e' esclusa da OGNI
stima di parametro (resta nello stato Elo).

Uso:   python audit/elo_weight_retune.py
Out:   audit/output/elo_walker_per_match.parquet (+ .csv.gz)
       audit/results/elo_weight_retune.md
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

import elo_walker_core as W                                            # noqa: E402
import diagnose_clv_pinnacle as CLV                                    # noqa: E402
from diagnose_production_baseline import (brier_ll_1x2, TRAIN_SEASONS,  # noqa: E402
                                          SEASONS_EVAL)
from topmix_margins import N_BOOT, SEED, _ci                           # noqa: E402
import app as PROD_APP                                                 # noqa: E402

OUT_RES = os.path.join(_AUDIT_DIR, "results")
OUT_DAT = os.path.join(_AUDIT_DIR, "output")
REPORT = os.path.join(OUT_RES, "elo_weight_retune.md")
PARQUET = os.path.join(OUT_DAT, "elo_walker_per_match.parquet")
CSVGZ = os.path.join(OUT_DAT, "elo_walker_per_match.csv.gz")

W_PROD = PROD_APP.POISSON_1X2_WEIGHT                      # 0.25, SOLA LETTURA
GRID = tuple(sorted(set([round(0.05 * i, 4) for i in range(21)]) | {round(W_PROD, 4)}))
BRIER_TOL = 0.0005                                        # vincolo di sicurezza
ALL_SEASONS = tuple(TRAIN_SEASONS) + tuple(SEASONS_EVAL) + ("2026/27",)
BURN_IN_SEASON = TRAIN_SEASONS[0]                         # prima stagione disponibile
TRAIN_EFFECTIVE = tuple(s for s in TRAIN_SEASONS if s != BURN_IN_SEASON)
VALIDATION_SEASON = SEASONS_EVAL[0]
TEST_SEASON = SEASONS_EVAL[1]


# =====================================================================
# 1. Costruzione del campione
# =====================================================================
def _giornata(sub: pd.DataFrame) -> pd.Series:
    """Giornata DERIVATA (i CSV football-data non hanno colonna round/giornata):
    all'interno di (lega, stagione), in ordine di data di produzione,
    giornata = 1 + indice // (n_squadre // 2). Approssimazione: i recuperi
    finiscono nel blocco della data in cui si giocano, non in quello del
    turno originale. Serve SOLO come unita' di blocco per il bootstrap e
    come colonna descrittiva dell'artefatto."""
    teams = pd.unique(pd.concat([sub["home"], sub["away"]]))
    per_round = max(1, len(teams) // 2)
    return pd.Series(1 + (np.arange(len(sub)) // per_round), index=sub.index)


def _team_flags(d: pd.DataFrame) -> pd.DataFrame:
    """Per ogni riga: per la squadra di casa e di trasferta,
      * mai_vista: e' la prima partita in assoluto di quella squadra nel
        dataset (= promossa/neopromossa mai vista dal motore, rating 1500);
      * di_ritorno: la squadra aveva gia' giocato, ma non nella stagione
        precedente del suo campionato;
      * anni_assenza: numero di stagioni consecutive saltate prima di questa.
    Le stagioni sono quelle etichettate da load_league, ordinate."""
    seasons_order = {s: i for i, s in enumerate(ALL_SEASONS)}
    seen_seasons = {}       # (league, team) -> set(indice stagione)
    for _, r in d.iterrows():
        si = seasons_order[r["season"]]
        for t in (r["home"], r["away"]):
            seen_seasons.setdefault((r["league"], t), set()).add(si)

    first_seen = {}         # (league, team) -> indice stagione minima
    for k, v in seen_seasons.items():
        first_seen[k] = min(v)

    out = {c: [] for c in ("home_mai_vista", "away_mai_vista",
                           "home_di_ritorno", "away_di_ritorno",
                           "home_anni_assenza", "away_anni_assenza")}
    played_before = set()   # (league, team) gia' apparsa in una riga precedente
    for _, r in d.iterrows():
        si = seasons_order[r["season"]]
        for side, t in (("home", r["home"]), ("away", r["away"])):
            key = (r["league"], t)
            mai_vista = key not in played_before
            ss = sorted(x for x in seen_seasons[key] if x < si)
            if not ss:
                assenza = 0
                ritorno = False
            else:
                assenza = si - ss[-1] - 1
                ritorno = assenza > 0
            out[f"{side}_mai_vista"].append(bool(mai_vista))
            out[f"{side}_di_ritorno"].append(bool(ritorno))
            out[f"{side}_anni_assenza"].append(int(assenza))
            played_before.add(key)
    return pd.DataFrame(out, index=d.index)


def build_sample(verbose=True):
    """Tabella per-partita: Elo del walker fedele + Poisson di produzione +
    Elo della vecchia replica, con etichette di stagione/giornata/flag."""
    frames, join_stats = [], []
    for league, prefix in W.LEAGUE_PREFIX.items():
        walker = W.build_walker_table(league)
        df_ll = CLV.load_league(prefix)
        clv = CLV.run_model_with_elo(df_ll, league, CLV.load_xg(league),
                                     emit_seasons=ALL_SEASONS)
        clv = clv.rename(columns={"elo_1": "old_elo_1", "elo_X": "old_elo_X",
                                  "elo_2": "old_elo_2"})
        clv = clv.drop(columns=[c for c in ("model_1", "model_X", "model_2") if c in clv])
        # orario: unica fonte e' la colonna Time dei CSV, che il motore Elo
        # NON legge; qui serve solo come colonna descrittiva.
        times = df_ll[["Date", "HomeClean", "AwayClean"]].copy()
        if "Time" in df_ll.columns:
            times["Time"] = df_ll["Time"]
        else:
            times["Time"] = np.nan
        m = walker.merge(clv, left_on=["date", "home", "away"],
                         right_on=["date", "home", "away"],
                         how="inner", validate="one_to_one")
        m = m.merge(times, left_on=["date", "home", "away"],
                    right_on=["Date", "HomeClean", "AwayClean"], how="left",
                    validate="one_to_one").drop(columns=["Date", "HomeClean", "AwayClean"])
        join_stats.append({
            "league": league,
            "n_walker_elo": len(walker), "n_poisson_walker": len(clv),
            "n_join": len(m),
            "solo_walker": len(walker) - len(m), "solo_poisson": len(clv) - len(m),
        })
        frames.append(m)
        if verbose:
            print(f"  {league:16s} elo={len(walker):5d} poisson={len(clv):5d} join={len(m):5d}")
    d = pd.concat(frames, ignore_index=True)
    d = d.sort_values(["league", "date", "home"], kind="mergesort").reset_index(drop=True)
    g = []
    for (lg, se), sub in d.groupby(["league", "season"], sort=False):
        g.append(_giornata(sub))
    d["giornata"] = pd.concat(g).sort_index()
    d["burn_in"] = d["season"] == BURN_IN_SEASON
    d = pd.concat([d, _team_flags(d)], axis=1)
    return d, pd.DataFrame(join_stats)


# =====================================================================
# 2. Blend (funzione di PRODUZIONE) e metriche
# =====================================================================
def blend_matrix(d: pd.DataFrame, w: float) -> np.ndarray:
    """P(1X2) a peso w usando ``app.blend_elo_into_1x2`` riga per riga."""
    out = np.empty((len(d), 3))
    P = d[["prodn_1", "prodn_X", "prodn_2"]].to_numpy(float)
    E = d[["elo_1", "elo_X", "elo_2"]].to_numpy(float)
    for i in range(len(d)):
        m = {"1": P[i, 0], "X": P[i, 1], "2": P[i, 2],
             "u15": 0.0, "u25": 0.0, "u35": 0.0, "gg": 0.0}
        ep = {"1": E[i, 0], "X": E[i, 1], "2": E[i, 2]}
        b = PROD_APP.blend_elo_into_1x2(m, "H", "A", "Serie A", w=w, elo_probs=ep)
        out[i] = (b["1"], b["X"], b["2"])
    return out


def losses(p: np.ndarray, y: np.ndarray):
    """Perdite PER RIGA: logloss (-log p_osservato) e Brier (somma quadrati)."""
    n = len(y)
    oh = np.zeros_like(p)
    oh[np.arange(n), y] = 1.0
    brier = np.sum((oh - p) ** 2, axis=1)
    ll = -np.log(np.clip(p[np.arange(n), y], 1e-12, 1.0))
    return ll, brier


def y_index(d: pd.DataFrame) -> np.ndarray:
    return np.array([{"1": 0, "X": 1, "2": 2}[v] for v in d["real_1x2"]])


# =====================================================================
# 3. Bootstrap a blocchi (lega x stagione x giornata), appaiato
# =====================================================================
def block_bootstrap_delta(delta_rows: np.ndarray, blocks: np.ndarray,
                          n_boot=N_BOOT, seed=SEED):
    """IC percentile 2.5-97.5 della media di ``delta_rows`` ricampionando i
    BLOCCHI con reinserimento (stesso numero di blocchi dell'originale)."""
    codes, _ = pd.factorize(blocks)
    nb = codes.max() + 1
    sums = np.bincount(codes, weights=delta_rows, minlength=nb)
    cnts = np.bincount(codes, minlength=nb).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, nb, size=(n_boot, nb))
    means = sums[idx].sum(axis=1) / cnts[idx].sum(axis=1)
    lo, hi = _ci(list(means))
    return float(np.mean(delta_rows)), float(lo), float(hi), int(nb)


# =====================================================================
# 4. Pipeline
# =====================================================================
def evaluate(d_split: pd.DataFrame, label: str):
    """Per ogni w: Brier, LogLoss, delta appaiati vs W_PROD con IC a blocchi."""
    y = y_index(d_split)
    blocks = (d_split["league"] + "|" + d_split["season"] + "|"
              + d_split["giornata"].astype(str)).to_numpy()
    ll_by_w, br_by_w = {}, {}
    for w in GRID:
        p = blend_matrix(d_split, w)
        ll, br = losses(p, y)
        ll_by_w[w], br_by_w[w] = ll, br
    rows = []
    for w in GRID:
        dll = ll_by_w[w] - ll_by_w[W_PROD]
        dbr = br_by_w[w] - br_by_w[W_PROD]
        m_ll, lo_ll, hi_ll, nb = block_bootstrap_delta(dll, blocks)
        m_br, lo_br, hi_br, _ = block_bootstrap_delta(dbr, blocks)
        rows.append({
            "split": label, "w": w, "n": len(d_split), "n_blocchi": nb,
            "logloss": float(np.mean(ll_by_w[w])),
            "brier": float(np.mean(br_by_w[w])),
            "d_logloss_vs_025": m_ll, "d_ll_lo": lo_ll, "d_ll_hi": hi_ll,
            "d_brier_vs_025": m_br, "d_br_lo": lo_br, "d_br_hi": hi_br,
        })
    tab = pd.DataFrame(rows)
    # range di equivalenza: delta appaiato vs il MINIMO puntuale di LogLoss
    w_star = float(tab.loc[tab["logloss"].idxmin(), "w"])
    eq = []
    for w in GRID:
        dll = ll_by_w[w] - ll_by_w[w_star]
        m, lo, hi, _ = block_bootstrap_delta(dll, blocks)
        eq.append({"w": w, "d_logloss_vs_wstar": m, "lo": lo, "hi": hi,
                   "equivalente": bool(lo <= 0.0 <= hi)})
    eqtab = pd.DataFrame(eq)
    return tab, eqtab, w_star, ll_by_w, br_by_w, blocks


def per_league_sign(d_split: pd.DataFrame, w_alt: float):
    """Segno di Delta LogLoss (w_alt - W_PROD) per lega, con IC a blocchi."""
    out = []
    for lg, sub in d_split.groupby("league", sort=False):
        y = y_index(sub)
        blocks = (sub["season"] + "|" + sub["giornata"].astype(str)).to_numpy()
        ll_a, _ = losses(blend_matrix(sub, w_alt), y)
        ll_b, _ = losses(blend_matrix(sub, W_PROD), y)
        m, lo, hi, nb = block_bootstrap_delta(ll_a - ll_b, blocks)
        out.append({"league": lg, "n": len(sub), "n_blocchi": nb,
                    "d_logloss": m, "lo": lo, "hi": hi,
                    "segno": "-" if m < 0 else "+"})
    return pd.DataFrame(out)


def old_replica_mismatch(d: pd.DataFrame):
    """Punto A.4: |elo_* vecchia replica - elo_* walker fedele|."""
    rows = []
    for col_new, col_old, name in (("elo_1", "old_elo_1", "elo_1"),
                                   ("elo_X", "old_elo_X", "elo_X"),
                                   ("elo_2", "old_elo_2", "elo_2")):
        a = np.abs(d[col_old].to_numpy(float) - d[col_new].to_numpy(float))
        rows.append({
            "componente": name, "n": len(a), "media": float(a.mean()),
            "p50": float(np.percentile(a, 50)), "p90": float(np.percentile(a, 90)),
            "p95": float(np.percentile(a, 95)), "p99": float(np.percentile(a, 99)),
            "max": float(a.max()),
        })
    tot = np.abs(d[["old_elo_1", "old_elo_X", "old_elo_2"]].to_numpy(float)
                 - d[["elo_1", "elo_X", "elo_2"]].to_numpy(float)).sum(axis=1)
    rows.append({"componente": "L1 sulla terna", "n": len(tot),
                 "media": float(tot.mean()), "p50": float(np.percentile(tot, 50)),
                 "p90": float(np.percentile(tot, 90)), "p95": float(np.percentile(tot, 95)),
                 "p99": float(np.percentile(tot, 99)), "max": float(tot.max())})
    return pd.DataFrame(rows)


def main():
    os.makedirs(OUT_RES, exist_ok=True)
    os.makedirs(OUT_DAT, exist_ok=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                   cwd=_REPO_ROOT).decode().strip()

    print("[1/6] costruzione campione")
    d, join_stats = build_sample()
    print(f"  totale righe: {len(d)}")

    print("[2/6] artefatto per-partita")
    art = d[[
        "league", "season", "giornata", "date", "Time", "home_raw", "away_raw",
        "home", "away", "home_adv", "elo_home_pre", "elo_away_pre", "d", "e_H",
        "p_draw", "elo_1", "elo_X", "elo_2", "prodn_1", "prodn_X", "prodn_2",
        "old_elo_1", "old_elo_X", "old_elo_2", "FTHG", "FTAG", "FTR", "real_1x2",
        "home_mai_vista", "away_mai_vista", "home_di_ritorno", "away_di_ritorno",
        "home_anni_assenza", "away_anni_assenza", "burn_in",
    ]].copy()
    art = art.rename(columns={"Time": "ora", "date": "data", "d": "d_elo_diff"})
    try:
        art.to_parquet(PARQUET, index=False)
        parquet_ok = True
    except Exception as e:                                   # pragma: no cover
        parquet_ok = False
        print(f"  parquet non scritto: {e}")
    art.to_csv(CSVGZ, index=False, compression="gzip")
    print(f"  parquet={parquet_ok} righe={len(art)}")

    print("[3/6] mismatch vecchia replica")
    mism_all = old_replica_mismatch(d)
    mism_split = {}
    for lbl, sub in (("train effettivo", d[d["season"].isin(TRAIN_EFFECTIVE)]),
                     ("validation", d[d["season"] == VALIDATION_SEASON]),
                     ("test", d[d["season"] == TEST_SEASON])):
        mism_split[lbl] = old_replica_mismatch(sub)

    splits = {
        "train (post burn-in)": d[d["season"].isin(TRAIN_EFFECTIVE)].reset_index(drop=True),
        "validation 2024/25": d[d["season"] == VALIDATION_SEASON].reset_index(drop=True),
        "test 2025/26": d[d["season"] == TEST_SEASON].reset_index(drop=True),
        "burn-in 2022/23 (solo descrittivo)":
            d[d["season"] == BURN_IN_SEASON].reset_index(drop=True),
    }

    print("[4/6] griglia + bootstrap a blocchi")
    results, eqtabs, wstars = {}, {}, {}
    for lbl, sub in splits.items():
        print(f"  {lbl} n={len(sub)}")
        tab, eqtab, wstar, _, _, _ = evaluate(sub, lbl)
        results[lbl], eqtabs[lbl], wstars[lbl] = tab, eqtab, wstar

    print("[5/6] dettaglio per lega")
    w_star_train = wstars["train (post burn-in)"]
    per_lg = {
        "train (post burn-in)": per_league_sign(splits["train (post burn-in)"], w_star_train),
        "validation 2024/25": per_league_sign(splits["validation 2024/25"], w_star_train),
    }

    print("[6/6] report")
    write_report(head, d, join_stats, art, parquet_ok, mism_all, mism_split,
                 splits, results, eqtabs, wstars, per_lg, w_star_train)
    print(f"scritto {REPORT}")


def _md(df: pd.DataFrame, floatfmt="{:.6f}") -> str:
    def fmt(v):
        if isinstance(v, (float, np.floating)):
            return floatfmt.format(v)
        return str(v)
    head = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    body = ["| " + " | ".join(fmt(v) for v in row) + " |"
            for row in df.itertuples(index=False)]
    return "\n".join([head, sep] + body)


def write_report(head, d, join_stats, art, parquet_ok, mism_all, mism_split,
                 splits, results, eqtabs, wstars, per_lg, w_star_train):
    L = []
    ap = L.append
    ap("# Ritaratura del peso w del blend 1X2 — walker Elo fedele alla produzione")
    ap("")
    ap(f"Generato: {datetime.now(timezone.utc).isoformat(timespec='seconds')} UTC  ")
    ap(f"Commit: `{head}`  ")
    ap(f"`app.POISSON_1X2_WEIGHT` letto in sola lettura: **{W_PROD}** (non modificato)  ")
    ap(f"Griglia: {list(GRID)}  ")
    ap(f"Bootstrap: {N_BOOT} repliche, seed {SEED}, blocchi (lega x stagione x giornata), IC percentile 2.5-97.5")
    ap("")
    ap("## A. Walker e join")
    ap(_md(join_stats, "{:.0f}"))
    ap("")
    ap("### Ordinamento a parita' di data (documentato, non corretto)")
    rows = [W.ordering_report(lg) for lg in W.LEAGUES]
    ap(_md(pd.DataFrame(rows), "{:.0f}"))
    ap("")
    ap("### A.4 Mismatch vecchia replica (K fisso, senza moltiplicatore) vs walker fedele")
    ap("Tutte le partite in join:")
    ap(_md(mism_all))
    for lbl, t in mism_split.items():
        ap("")
        ap(f"Solo {lbl}:")
        ap(_md(t))
    ap("")
    ap("## B. Split e burn-in")
    ap(f"* `diagnose_production_baseline.TRAIN_SEASONS` = {TRAIN_SEASONS}")
    ap(f"* `diagnose_production_baseline.SEASONS_EVAL` = {SEASONS_EVAL}")
    ap(f"* burn-in = {BURN_IN_SEASON} (prima stagione disponibile) -> train effettivo = {TRAIN_EFFECTIVE}")
    cnt = d.groupby(["season"]).size().reset_index(name="n_partite")
    ap("")
    ap(_md(cnt, "{:.0f}"))
    ap("")
    ap("## C. Griglia di w")
    for lbl in results:
        ap("")
        ap(f"### {lbl} (n={len(splits[lbl])}, w* LogLoss = {wstars[lbl]})")
        ap(_md(results[lbl]))
        ap("")
        ap(f"Range di equivalenza rispetto a w*={wstars[lbl]}:")
        ap(_md(eqtabs[lbl]))
    ap("")
    ap("## C.bis Dettaglio per lega (Delta LogLoss w* train vs 0.25)")
    for lbl, t in per_lg.items():
        ap("")
        ap(f"### {lbl}")
        ap(_md(t))
    ap("")
    ap("## Verdetto (regola decisionale fissata PRIMA di guardare i numeri)")
    tr = results["train (post burn-in)"]
    eqt = eqtabs["train (post burn-in)"]
    r025 = eqt[np.isclose(eqt["w"], W_PROD)].iloc[0]
    eq_ws = [float(x) for x in eqt.loc[eqt["equivalente"], "w"]]
    ap(f"* w* puntuale su TRAIN (LogLoss minima) = **{w_star_train}**")
    ap(f"* range di equivalenza su TRAIN (IC 95% del Delta appaiato vs w* che include 0): "
       f"**{min(eq_ws)} – {max(eq_ws)}**")
    dentro = bool(r025["lo"] <= 0.0 <= r025["hi"])
    ap(f"* w=0.25 dentro il range di equivalenza del minimo sul train: **{dentro}** "
       f"(Delta LogLoss {r025['d_logloss_vs_wstar']:+.6f}, IC [{r025['lo']:+.6f}, {r025['hi']:+.6f}])")
    va = results["validation 2024/25"]
    cand = tr[(tr["d_logloss_vs_025"] < 0) & (tr["d_ll_hi"] < 0)
              & (tr["d_brier_vs_025"] <= BRIER_TOL)]["w"].tolist()
    cand_ok = []
    for w in cand:
        rv = va[np.isclose(va["w"], w)].iloc[0]
        if rv["d_logloss_vs_025"] < 0 and rv["d_ll_hi"] < 0 and rv["d_brier_vs_025"] <= BRIER_TOL:
            cand_ok.append(w)
    ap(f"* candidati che su TRAIN battono 0.25 con IC che esclude lo zero e Brier entro "
       f"+{BRIER_TOL}: {cand or 'nessuno'}")
    ap(f"* di questi, confermati anche su VALIDATION con IC che esclude lo zero: "
       f"{cand_ok or 'nessuno'}")
    if dentro and not cand_ok:
        ap("")
        ap("**VERDETTO: w=0.25 confermato.** Il picco puntuale non e' significativo.")
    else:
        ap("")
        ap(f"**VERDETTO: alternativa proposta: w={cand_ok}** (NON applicata: audit di sola lettura).")
    ap("")
    ap("## D. Artefatto per-partita")
    ap(f"* `audit/output/elo_walker_per_match.parquet` (scritto: {parquet_ok})")
    ap("* `audit/output/elo_walker_per_match.csv.gz`")
    ap(f"* righe: {len(art)}, colonne: {list(art.columns)}")
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
