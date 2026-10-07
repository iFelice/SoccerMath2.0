"""
ppda_residual_test.py - Test sul RESIDUO della testa Totali: PPDA e deep
completions rolling aggiungono informazione al lambda che il motore usa OGGI?

Solo analisi. Nessuna modifica a ``app.py``, ``config.py``, ``models/``, a
formule, soglie, pesi o ``PRIOR_MATCHES``: questo script LEGGE il motore per
ricostruirne il lambda e non lo tocca.

Che cosa fa
-----------
1. Ricostruisce, per ogni partita, il lambda point-in-time della testa Totali
   esattamente come fa la produzione (``att0_pure``/``def0_pure`` = fonte
   F_season, shrinkage ``PRIOR_MATCHES``, lambda pura = att0_pure * def0_pure
   avversario * media gol, clip [exp(-6), exp(3)]). La ricostruzione e'
   verificata contro ``app.get_full_poisson_two_heads`` partita per partita:
   lo scarto massimo su Under 2.5 e GG finisce nel riepilogo, quindi non si
   assume che il lambda sia quello di produzione: si misura.
2. Unisce le feature rolling point-in-time di ``build_ppda_deep_rolling.py``
   (PPDA proprio / deep generati / PPDA subito / deep subiti, finestre N=5 e
   N=10, somma dei due lati per coerenza con un offset sui gol totali).
3. Fitta un GLM Poisson su TRAIN (2022/23 + 2023/24) con
   ``offset = log(lambda_casa + lambda_trasferta)`` e le 8 covariate rolling:
   la domanda e' se resta struttura nel residuo, non se il modello predice.
4. Riporta coefficienti, errori standard, p-value, test del rapporto di
   verosimiglianza contro il modello di solo offset, dispersione di Pearson,
   coefficienti standardizzati e matrice di correlazione fra le covariate.
5. Riporta la correlazione fra le feature rolling e ``att0_pure``/``def0_pure``
   a livello squadra-partita (ridondanza prima della significativita').
6. Ripete il fit SEPARATAMENTE per lega (5 fit indipendenti) piu' un fit
   aggregato di solo confronto, con il controllo di coerenza di segno fra leghe.

Confini: train 2022/23 + 2023/24, validation 2024/25, test 2025/26 (gli stessi
del resto del progetto). Qui si usa SOLO il train: validation e backtest vengono
dopo, e solo se questo referto dice che il segnale esiste.

Uso:
    python audit/ppda_residual_test.py
    python audit/ppda_residual_test.py --rolling audit/data/ppda_deep_rolling.csv
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

import statsmodels.api as sm  # noqa: E402
from scipy import stats as scipy_stats  # noqa: E402

import app as prod_app  # noqa: E402
from backtest_experiment_all import (  # noqa: E402
    LEAGUES, MARKET_VALUES, load_league,
)
from build_ppda_deep_rolling import MEASURES, WINDOWS  # noqa: E402
from pt19_age_cap_audit import TeamState, season_year_of  # noqa: E402
from xg_archive import load_archive, season_averages  # noqa: E402

TRAIN_SEASONS = ("2022/23", "2023/24")
VAL_SEASON = "2024/25"
TEST_SEASON = "2025/26"

# Le 8 covariate richieste: {attacco proprio, difesa subita} x {PPDA, deep} x
# {N=5, N=10}. "own" = della squadra, "faced" = quello che la squadra subisce.
COVARIATES: List[str] = [
    f"{measure}_{window}" for window in WINDOWS for measure in MEASURES
]


def _market_factor(team: str) -> float:
    val = MARKET_VALUES.get(team, 50)
    factor = 1.0 + (math.log10(max(val, 10)) - 2.0) / 4.0
    return max(0.85, min(1.25, factor))


def production_totali(prefix: str, league: str) -> pd.DataFrame:
    """Lambda point-in-time della testa Totali, ricostruito come in produzione.

    Walk-forward in ordine cronologico su TUTTO lo storico: le medie gol
    (``avg_h``/``avg_a``) e lo stato delle squadre usano solo le partite
    precedenti, la fonte xG e' F_season al cutoff della partita (la stessa
    fonte di ``app.get_league_engine``). Restituisce una riga per partita con
    ``att0_pure``/``def0_pure`` dei due lati, i lambda puri (prima e dopo il
    clip di produzione) e le probabilita' Under 2.5 / GG del motore, usate come
    prova che la ricostruzione coincide con la testa Totali di produzione.
    """
    df = load_league(prefix)
    records = load_archive(league)
    state: Dict[str, TeamState] = {}
    tot_hg = tot_ag = 0.0
    tot_n = 0
    rows: List[dict] = []

    for _, row in df.iterrows():
        home, away = row.HomeClean, row.AwayClean
        sh = state.setdefault(home, TeamState())
        sa = state.setdefault(away, TeamState())
        avg_h = max(tot_hg / tot_n, 0.1) if tot_n else 0.1
        avg_a = max(tot_ag / tot_n, 0.1) if tot_n else 0.1

        # --- fonte F_season (produzione): sola stagione in corso al cutoff ---
        static = season_averages(league, season_year_of(row.season),
                                 cutoff=row.Date, records=records).averages
        anchor_xg, anchor_xga = prod_app._league_mean_gate(static)

        def pure(team: str, ts: TeamState):
            """att0_pure/def0_pure di produzione, con il fallback gol."""
            fallback = ts.goal_fallback(avg_h, avg_a)
            rec = static.get(team) if static else None
            if rec is not None and anchor_xg and anchor_xga:
                xg_v, xga_v, n = (rec.get("xG_avg"), rec.get("xGA_avg"),
                                  rec.get("matches"))
                try:
                    xg_v, xga_v = float(xg_v), float(xga_v)
                    ok = (np.isfinite(xg_v) and np.isfinite(xga_v)
                          and xg_v >= 0 and xga_v >= 0)
                except (TypeError, ValueError):
                    ok, n = False, None
                n_ok = (isinstance(n, (int, float)) and not isinstance(n, bool)
                        and np.isfinite(float(n)) and float(n) > 0)
                if ok and n_ok:
                    return (prod_app._shrunk_ratio(xg_v, anchor_xg, n),
                            prod_app._shrunk_ratio(xga_v, anchor_xga, n), False)
            return fallback[0], fallback[1], True

        att_pure_h, def_pure_h, fb_h = pure(home, sh)
        att_pure_a, def_pure_a, fb_a = pure(away, sa)
        if not (np.isfinite(att_pure_h) and att_pure_h > 0):
            att_pure_h = 1.0
        if not (np.isfinite(def_pure_h) and def_pure_h > 0):
            def_pure_h = 1.0
        if not (np.isfinite(att_pure_a) and att_pure_a > 0):
            att_pure_a = 1.0
        if not (np.isfinite(def_pure_a) and def_pure_a > 0):
            def_pure_a = 1.0

        # lambda pura della testa Totali (get_full_poisson_two_heads)
        base_pure_h = att_pure_h * def_pure_a * avg_h
        base_pure_a = att_pure_a * def_pure_h * avg_a
        lambda_h = prod_app._clip_lambda(base_pure_h)
        lambda_a = prod_app._clip_lambda(base_pure_a)

        # --- prova: le probabilita' del motore su questi lambda ---
        def make_stats(att, defe, ts, pure_pair):
            last5 = list(ts.last5)
            if len(last5) >= 3:
                den = max((avg_h + avg_a) / 2.0, 0.5)
                f_att = max(0.85, min(1.15, (sum(x[0] for x in last5) / len(last5)) / den))
                f_def = max(0.85, min(1.15, (sum(x[1] for x in last5) / len(last5)) / den))
            else:
                f_att = f_def = 1.0
            mkt = _market_factor(home if ts is sh else away)
            return {"att": att * f_att * mkt, "def": defe * f_def / mkt,
                    "att0": att * f_att, "def0": defe * f_def,
                    "att0_pure": pure_pair[0], "def0_pure": pure_pair[1],
                    "val": 50}

        hs = make_stats(att_pure_h, def_pure_h, sh, (att_pure_h, def_pure_h))
        as_ = make_stats(att_pure_a, def_pure_a, sa, (att_pure_a, def_pure_a))
        engine = prod_app.get_full_poisson_two_heads(hs, as_, avg_h, avg_a)

        rows.append({
            "league": league, "season": row.season, "date": row.Date,
            "home": home, "away": away,
            "n_seen": int(tot_n),
            "fthg": float(row.FTHG), "ftag": float(row.FTAG),
            "goals_total": float(row.FTHG + row.FTAG),
            "avg_h": avg_h, "avg_a": avg_a,
            "att0_pure_home": att_pure_h, "def0_pure_home": def_pure_h,
            "att0_pure_away": att_pure_a, "def0_pure_away": def_pure_a,
            "fallback_home": bool(fb_h), "fallback_away": bool(fb_a),
            "lambda_raw_home": base_pure_h, "lambda_raw_away": base_pure_a,
            "lambda_home": lambda_h, "lambda_away": lambda_a,
            "lambda_total": lambda_h + lambda_a,
            "engine_u25": engine["u25"], "engine_gg": engine["gg"],
            "recon_u25": prod_app._poisson_market(lambda_h, lambda_a)["u25"],
            "recon_gg": prod_app._poisson_market(lambda_h, lambda_a)["gg"],
        })

        tot_hg += float(row.FTHG)
        tot_ag += float(row.FTAG)
        tot_n += 1
        sh.observe_home(float(row.FTHG), float(row.FTAG))
        sa.observe_away(float(row.FTHG), float(row.FTAG))

    out = pd.DataFrame(rows)
    out["date_day"] = pd.to_datetime(out["date"]).dt.normalize()
    return out


def load_rolling(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"archivio rolling assente: {path} (eseguire "
            f"audit/build_ppda_deep_rolling.py)")
    df = pd.read_csv(path)
    # Data LOCALE del calcio d'inizio (i primi 10 caratteri del kickoff), non la
    # data UTC: il Date dei CSV football-data e' la data locale della partita, e
    # convertire in UTC sposterebbe di un giorno i posticipi serali.
    df["date_day"] = pd.to_datetime(df["kickoff"].astype(str).str.slice(0, 10),
                                    format="%Y-%m-%d")
    return df


def join_rolling(engine: pd.DataFrame, rolling: pd.DataFrame) -> Dict:
    """Unisce lambda di produzione e feature rolling su (lega, giorno, squadre).

    Il tasso di aggancio viene MISURATO e riportato: un nome non risolto o una
    data non coincidente tolgono la partita dal fit, non la imputano. Le
    partite non agganciate vengono elencate TUTTE nel riepilogo (``unmatched_all``):
    la causa osservata e' il disaccordo di data fra Understat e football-data
    (partite rinviate e recuperate, o disallineamenti di un giorno), non un nome
    non riconosciuto. Nessuna tolleranza fuzzy sulla data: una partita non
    agganciata resta fuori ed e' dichiarata.
    """
    merged = engine.merge(
        rolling, how="left", on=["league", "date_day", "home", "away"],
        suffixes=("", "_roll"))
    matched = merged["home_r5_n"].notna()
    unmatched = merged[~matched]
    reasons = {
        "matches_all": int(len(merged)),
        "matched": int(matched.sum()),
        "unmatched_no_record": int(len(unmatched)),
        "unmatched_in_train": int(unmatched["season"].isin(TRAIN_SEASONS).sum()),
        # Elenco completo, non un campione: ogni mancata coincidenza va vista.
        "unmatched_all": [
            {"season": r.season, "date": str(r.date_day.date()),
             "home": r.home, "away": r.away}
            for r in unmatched.itertuples()
        ],
    }
    return {"merged": merged, "join": reasons}


def match_covariates(merged: pd.DataFrame) -> pd.DataFrame:
    """Covariate a livello partita = somma dei due lati.

    L'offset e' log(lambda_casa + lambda_trasferta), cioe' sui gol TOTALI: le
    covariate additive coerenti con quell'offset sono la somma delle feature
    delle due squadre (attacco proprio = somma dei due attacchi, difesa subita
    = somma di cio' che le due squadre subiscono).
    """
    out = merged.copy()
    for window in WINDOWS:
        for measure in MEASURES:
            name = f"{measure}_{window}"
            left = f"home_r{window}_{measure}"
            right = f"away_r{window}_{measure}"
            out[name] = out[left] + out[right]
    return out


def glm_report(df: pd.DataFrame, label: str, compact: bool = False,
               extra: Optional[pd.DataFrame] = None) -> Optional[dict]:
    """GLM Poisson con offset = log(lambda attuale), covariate rolling.

    ``extra`` sono regressori sempre presenti (per esempio le dummy di lega nel
    fit aggregato): entrano sia nel modello con le covariate sia in quello di
    solo offset, cosi' il test del rapporto di verosimiglianza misura solo il
    contributo delle feature rolling e non il disallineamento fra leghe.
    """
    usable = df[COVARIATES + ["lambda_total", "goals_total"]].dropna()
    dropped = int(len(df) - len(usable))
    if len(usable) < 50:
        return {"label": label, "error": f"troppo poche partite utilizzabili "
                                        f"({len(usable)})"}
    y = usable["goals_total"].to_numpy(dtype=float)
    offset_log = np.log(usable["lambda_total"].to_numpy(dtype=float))
    X = usable[COVARIATES].to_numpy(dtype=float)
    X_extra = extra.loc[usable.index].to_numpy(dtype=float) if extra is not None else None
    if X_extra is not None:
        design_full = sm.add_constant(np.hstack([X_extra, X]), has_constant="add")
        design_null = sm.add_constant(X_extra, has_constant="add")
        n_extra = X_extra.shape[1]
    else:
        design_full = sm.add_constant(X, has_constant="add")
        design_null = np.ones((len(y), 1))
        n_extra = 0
    fit = sm.GLM(y, design_full, family=sm.families.Poisson(),
                 offset=offset_log).fit()

    # Modello nullo: solo l'offset (nessuna covariata). Il confronto dice se le
    # 8 feature aggiungono qualcosa al lambda che il motore usa gia'.
    null = sm.GLM(y, design_null, family=sm.families.Poisson(),
                  offset=offset_log).fit()
    lr_stat = 2.0 * (fit.llf - null.llf)
    lr_p = float(scipy_stats.chi2.sf(lr_stat, len(COVARIATES))) if lr_stat > 0 else 1.0

    # Coefficienti standardizzati: stessa regressione su covariate z-score,
    # per confrontare l'ampiezza fra misure con scale diverse.
    mean = X.mean(axis=0)
    std = X.std(axis=0, ddof=1)
    std[std == 0] = 1.0
    X_std = (X - mean) / std
    if X_extra is not None:
        X_std = np.hstack([X_extra, X_std])
    fit_std = sm.GLM(y, sm.add_constant(X_std, has_constant="add"),
                     family=sm.families.Poisson(), offset=offset_log).fit()

    disp = float(fit.pearson_chi2 / fit.df_resid) if fit.df_resid else float("nan")
    if compact:
        return {
            "label": label,
            "n_matches": int(len(usable)),
            "n_dropped_missing_features": dropped,
            "dispersion_pearson": disp,
            "lr_stat_vs_offset_only": float(lr_stat),
            "lr_df": len(COVARIATES),
            "lr_p_value": lr_p,
        }
    corr = pd.DataFrame(X, columns=COVARIATES).corr().round(3)
    return {
        "label": label,
        "n_matches": int(len(usable)),
        "n_dropped_missing_features": dropped,
        "mean_goals": float(y.mean()),
        "mean_lambda_total": float(np.exp(offset_log).mean()),
        "dispersion_pearson": disp,
        "lr_stat_vs_offset_only": float(lr_stat),
        "lr_df": len(COVARIATES),
        "lr_p_value": lr_p,
        "log_likelihood": float(fit.llf),
        "log_likelihood_offset_only": float(null.llf),
        "coefficients": [
            {
                "covariate": name,
                "beta": float(fit.params[n_extra + i + 1]),
                "se": float(fit.bse[n_extra + i + 1]),
                "z": float(fit.tvalues[n_extra + i + 1]),
                "p_value": float(fit.pvalues[n_extra + i + 1]),
                "beta_standardized": float(fit_std.params[n_extra + i + 1]),
                "p_value_standardized": float(fit_std.pvalues[n_extra + i + 1]),
            }
            for i, name in enumerate(COVARIATES)
        ],
        "correlation_matrix": corr.to_dict(),
        "max_abs_correlation_offdiag": float(
            np.max(np.abs(np.triu(corr.to_numpy(), 1)))),
    }


def redundancy_report(df: pd.DataFrame) -> dict:
    """Correlazione fra feature rolling e att0_pure/def0_pure (squadra-partita)."""
    rows = []
    for side in ("home", "away"):
        block = pd.DataFrame({
            "att0_pure": df[f"att0_pure_{side}"],
            "def0_pure": df[f"def0_pure_{side}"],
        })
        for window in WINDOWS:
            for measure in MEASURES:
                block[f"{measure}_{window}"] = df[f"{side}_r{window}_{measure}"]
        rows.append(block)
    stacked = pd.concat(rows, ignore_index=True)
    out: Dict[str, dict] = {}
    for target in ("att0_pure", "def0_pure"):
        entry = {}
        for name in COVARIATES:
            pair = stacked[[target, name]].dropna()
            if len(pair) < 30 or pair[name].std() == 0:
                entry[name] = {"pearson": None, "spearman": None,
                               "n": int(len(pair))}
                continue
            entry[name] = {
                "pearson": float(pair[target].corr(pair[name], method="pearson")),
                "spearman": float(pair[target].corr(pair[name], method="spearman")),
                "n": int(len(pair)),
            }
        out[target] = entry
    return {"team_matches": int(len(stacked)), "correlations": out}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Test sul residuo della testa Totali con PPDA/deep rolling")
    parser.add_argument("--rolling",
                        default=os.path.join(_AUDIT_DIR, "data",
                                             "ppda_deep_rolling.csv"))
    parser.add_argument("--output",
                        default=os.path.join(_AUDIT_DIR, "data",
                                             "ppda_residual_test.json"))
    args = parser.parse_args(list(argv) if argv is not None else None)

    rolling = load_rolling(args.rolling)
    report: Dict = {
        "train_seasons": list(TRAIN_SEASONS),
        "covariates": COVARIATES,
        "offset": "log(lambda_casa + lambda_trasferta) della testa Totali di produzione",
        "leagues": {},
    }
    all_train: List[pd.DataFrame] = []

    for prefix, league in LEAGUES:
        engine = production_totali(prefix, league)
        max_u25 = float((engine["engine_u25"] - engine["recon_u25"]).abs().max())
        max_gg = float((engine["engine_gg"] - engine["recon_gg"]).abs().max())
        joined = join_rolling(engine, rolling)
        merged = match_covariates(joined["merged"])
        train = merged[merged["season"].isin(TRAIN_SEASONS)].copy()
        # La prima giornata del walk-forward non ha ancora una giornata completa
        # di storico: le medie gol provvisorie (0.1, poi 4.0 dopo una sola
        # partita) rendono quel lambda irriconoscibile. Le partite con meno di
        # una giornata completa vista sono ESCLUSE dal fit primario e contate;
        # il fit su tutto il train resta riportato come robustezza.
        threshold = int(merged.groupby("date_day")["home"].count().max())
        warm = train[train["n_seen"] >= threshold]
        warm_rows = warm.copy()
        warm_rows["league"] = league
        all_train.append(warm_rows)
        report["leagues"][league] = {
            "matches_all": int(len(merged)),
            "matches_train": int(len(train)),
            "join": joined["join"],
            "engine_reconstruction_check": {
                "max_abs_diff_u25": max_u25,
                "max_abs_diff_gg": max_gg,
                "matches": int(len(engine)),
            },
            "glm": glm_report(warm, f"{league} (train, senza la prima giornata "
                                    f"incompleta del walk-forward)"),
            "glm_all_train": glm_report(train, f"{league} (tutto il train)",
                                        compact=True),
            "fit_dropped_breakdown": {
                "dropped": int(warm[COVARIATES].isna().any(axis=1).sum()),
                "no_rolling_record": int(
                    warm[warm[COVARIATES].isna().any(axis=1)]["home_r5_n"].isna().sum()),
                "window_insufficient": int(
                    warm[warm[COVARIATES].isna().any(axis=1)]["home_r5_n"].notna().sum()),
            },
            "warmup_excluded": {
                "threshold_matches_seen": threshold,
                "excluded": int(len(train) - len(warm)),
                "kept": int(len(warm)),
            },
            "redundancy_vs_pure": redundancy_report(warm),
            "window_status_train": {
                f"{side}_r{window}": {
                    status: int((train[f"{side}_r{window}_status"] == status).sum())
                    for status in ("full", "partial", "insufficient")
                }
                for side in ("home", "away") for window in WINDOWS
            },
            "fallback_rate_train": {
                "home": float(train["fallback_home"].mean()),
                "away": float(train["fallback_away"].mean()),
            },
        }

    pooled = pd.concat(all_train, ignore_index=True)
    # Fit aggregato: senza e CON effetti fissi di lega. Serve a distinguere un
    # segnale reale dal disallineamento di calibrazione fra leghe (gol medi /
    # lambda medio va da 0.95 a 1.06): se la significativita' aggregata sparisce
    # con le dummy di lega, era quell'artefatto e non le feature rolling.
    league_dummies = pd.get_dummies(pooled["league"], prefix="lega",
                                    drop_first=True).astype(float)
    report["pooled"] = {
        "matches_train": int(len(pooled)),
        "glm": glm_report(pooled, "aggregato 5 leghe (solo confronto, non e' il "
                                  "verdetto: i 5 fit per lega lo sono)"),
        "glm_league_fixed_effects": glm_report(
            pooled, "aggregato 5 leghe con effetti fissi di lega",
            extra=league_dummies),
    }

    # Coerenza di segno fra leghe: un coefficiente significativo solo aggregato
    # ma con segno incoerente fra leghe non e' un segnale.
    sign_check = {}
    for name in COVARIATES:
        per_league = []
        for league, payload in report["leagues"].items():
            glm = payload.get("glm") or {}
            for coef in glm.get("coefficients", []):
                if coef["covariate"] == name:
                    per_league.append({"league": league,
                                       "beta": coef["beta"],
                                       "p_value": coef["p_value"]})
        signs = {("+" if c["beta"] > 0 else "-") for c in per_league}
        significant = [c for c in per_league if c["p_value"] < 0.05]
        sign_check[name] = {
            "leagues": per_league,
            "distinct_signs": sorted(signs),
            "consistent_sign": len(signs) == 1,
            "significant_at_5pct": significant,
            "significant_and_consistent": (len(signs) == 1
                                           and len(significant) == len(per_league)),
        }
    report["sign_consistency_across_leagues"] = sign_check

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
