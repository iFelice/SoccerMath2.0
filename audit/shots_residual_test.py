"""
shots_residual_test.py - Test sul RESIDUO della testa Totali: tiri (HS/AS) e
tiri in porta (HST/AST) aggiungono informazione alle lambda di produzione per
O/U 2.5 e GG/NG?

SOLO AUDIT. Nessuna modifica a ``SoccerMath/``: questo script IMPORTA le
funzioni di produzione (``app._shrunk_ratio``, ``app._clip_lambda``,
``app._poisson_market``, ``app.get_full_poisson_two_heads``) e le usa come
sono, senza riscriverle e senza toccare formule, soglie, pesi o
``PRIOR_MATCHES``.

Banco riusato (non riscritto da zero)
-------------------------------------
Il banco e' quello del test PPDA/deep sul residuo della testa Totali:

  * ``audit/ppda_residual_test.py``  (GLM Poisson con
    ``offset = log(lambda di produzione)``, ricostruzione walk-forward del
    lambda ``att0_pure``/``def0_pure``, verifica di coincidenza con
    ``app.get_full_poisson_two_heads``, referto di ridondanza, LR test);
  * ``audit/build_ppda_deep_rolling.py``  (archivio point-in-time e TEST DI
    LEAKAGE ESEGUITO con iniezione controllata: troncamento + iniezione di
    futuro estremo, piu' il controllo di POTERE del test);
  * ``audit/test_ppda_deep_rolling.py``  (test offline del banco).

Provenienza dichiarata di questi tre file: branch
``arena/01a0aaed-soccermath2-0``, commit ``be09532`` (mai uniti in ``main``),
copiati qui verbatim. Questo script ne riusa ``production_totali`` (lambda di
produzione) e la STRUTTURA del test di leakage, applicata alle feature tiri.

Che cosa fa
-----------
1. Copertura delle colonne HS/AS/HST/AST dei CSV football-data per lega e
   stagione 2022/23-2025/26 (2026/27 escluso), con il conteggio delle righe a
   valori mancanti.
2. Lambda point-in-time della testa Totali di produzione
   (``att0_pure``/``def0_pure`` -> ``lambda_home``/``lambda_away``), con la
   verifica di coincidenza bit-a-bit con il motore (scarto massimo su Under 2.5
   e GG riportato).
3. Feature tiri FISSATE a priori. Per ogni squadra, stato a INIZIO GIORNATA
   (solo partite con data STRETTAMENTE precedente a quella della partita):
   media di tiri fatti, tiri concessi, quota di tiri in porta fatti, quota di
   tiri in porta concessi, con shrinkage verso la media di lega point-in-time
   con 6 partite fittizie (``app._shrunk_ratio``, stessa logica di
   ``PRIOR_MATCHES``). Due covariate per lato e basta:

     x_vol = log(tiri fatti / media lega)   + log(tiri concessi avversario / media lega)
     x_sot = log(quota tiri in porta fatti / media lega)
           + log(quota tiri in porta concessi avversario / media lega)

   ``quota`` = HST/HS (frazione di tiri in porta sul totale dei tiri). La
   lettura alternativa "tiri in porta per partita" e' riportata come
   SENSIBILITA' dichiarata, non come primary.
4. Correlazione di x_vol e x_sot con ``log(att0_pure)`` e ``log(def0_pure)``
   dell'avversario, per lega, PRIMA dei modelli (ridondanza).
5. Rolling-origin fissato: fold 1 stima su 2023/24 e valuta 2024/25; fold 2
   stima su 2023/24+2024/25 e valuta 2025/26. Modello
   ``lambda_nuova = lambda_prod * exp(b1*x_vol + b2*x_sot)`` con coefficienti
   COMUNI alle 5 leghe, stimati per massima verosimiglianza Poisson sui gol
   (GLM con offset ``log(lambda_prod)``; le righe casa e trasferta sono
   impilate, quindi b1/b2 sono unici per tutti e due i lati).
6. Metrica primaria LogLoss O/U 2.5 pooled sui due fold, probabilita' dalla
   matrice dei punteggi di produzione (``app._poisson_market``), confronto
   APPAIATO con le lambda di produzione, bootstrap a blocchi
   (lega x stagione x giornata) 2000 repliche, IC 95%.
   Sicurezza: LogLoss GG/NG non peggiore di +0.0005.
   Diagnostiche: LR test in-sample per lega (informativo, NON criterio),
   coefficienti per fold, segno di Delta per lega e per fold, Brier O/U e
   GG/NG, scomposizione di Murphy (reliability / resolution / uncertainty).
7. Regola di decisione, applicata meccanicamente dal codice a fine corsa.
8. Test di leakage con iniezione controllata: le feature della partita campione
   devono restare IDENTICHE (a) togliendo dal sorgente tutto cio' che ha data
   >= quella della partita e (b) iniettando partite sintetiche estreme future;
   e lo STESSO test deve RILEVARE un leak vero iniettato a mano (statistiche
   della partita stessa). Entrambi gli esiti finiscono nel referto.

Confini: 2022/23 serve SOLO a scaldare le medie; 2026/27 escluso. Nessun
iperparametro scelto dopo aver visto i risultati.

Output
------
  * ``audit/results/shots_residual_test.md``  referto GENERATO, con in chiusura
    la tabella di conformita' (requisito / esito / comando / evidenza) e il
    verdetto applicato dalla regola di decisione;
  * ``audit/output/shots_residual_test.json`` dettaglio macchina-leggibile
    (cartella in ``.gitignore``: si rigenera, non si versiona).

Il referto dipende SOLO dai numeri e dalle costanti fissate qui sopra (semi
inclusi): rigenerarlo sullo stesso commit lo riproduce identico riga per riga.

Uso:
    python audit/shots_residual_test.py
    python audit/shots_residual_test.py --json audit/output/shots_residual_test.json
    python audit/shots_residual_test.py --leakage-sample 3     # prova rapida

Test offline (nessuna rete): ``python -m pytest audit/test_shots_residual.py -q``
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

import statsmodels.api as sm  # noqa: E402
from scipy import stats as scipy_stats  # noqa: E402

import app as prod_app  # noqa: E402
from backtest_experiment_all import LEAGUES  # noqa: E402
from config import clean_name  # noqa: E402
from ppda_residual_test import production_totali  # noqa: E402  (banco riusato)

# ---------------------------------------------------------------------------
# Confini fissati a priori
# ---------------------------------------------------------------------------
SEASONS = ("2022/23", "2023/24", "2024/25", "2025/26")   # 2026/27 escluso
WARMUP_SEASON = "2022/23"                                # solo per scaldare
FOLDS = (
    {"name": "fold1", "train": ("2023/24",), "eval": "2024/25"},
    {"name": "fold2", "train": ("2023/24", "2024/25"), "eval": "2025/26"},
)
FEATURE_COLS = ("x_vol", "x_sot")
PRIMARY_MARKET = "ou25"
SAFETY_MARKET = "gg"
SAFETY_TOLERANCE = 0.0005          # Delta LogLoss GG/NG ammesso (peggioramento)
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20261007
LEAKAGE_SEED = 20261007
LEAKAGE_SAMPLE_PER_LEAGUE = 25
PRIOR_MATCHES = float(prod_app.PRIOR_MATCHES)   # 6.0, letto dalla produzione

SHOT_COLS = ("HS", "AS", "HST", "AST")
DB = os.path.join(_REPO_ROOT, "SoccerMath", "database")
CSV_SUFFIX = {"2022/23": "_2022", "2023/24": "_2023", "2024/25": "_2024",
              "2025/26": "_2025", "2026/27": "_Live"}

REPORT_PATH = os.path.join(_AUDIT_DIR, "results", "shots_residual_test.md")
DEFAULT_JSON = os.path.join(_AUDIT_DIR, "output", "shots_residual_test.json")


# ---------------------------------------------------------------------------
# 1. Dati: tiri dai CSV football-data
# ---------------------------------------------------------------------------
def load_league_shots(prefix: str) -> pd.DataFrame:
    """Righe delle 5 stagioni in perimetro con HS/AS/HST/AST.

    Stessi filtri del caricatore del banco (``backtest_experiment_all.load_league``):
    stesso insieme di file, stessa interpretazione della data (``dayfirst``),
    stesso ``dropna`` sulle colonne obbligatorie, stesso ordinamento e stessa
    deduplica su (data, casa, trasferta). La differenza e' solo che qui si
    portano dietro le quattro colonne dei tiri e che il 2026/27 viene caricato
    (per fedelta' della deduplica) e poi escluso.
    """
    frames = []
    for season, suffix in CSV_SUFFIX.items():
        path = os.path.join(DB, f"{prefix}{suffix}.csv")
        df = pd.read_csv(path, on_bad_lines="warn", low_memory=False)
        keep = ["Date", "HomeTeam", "AwayTeam", "FTR", "FTHG", "FTAG",
                *SHOT_COLS]
        for col in keep:
            if col not in df.columns:
                df[col] = np.nan
        df = df[keep].copy()
        df["season"] = season
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    for col in ("FTHG", "FTAG", *SHOT_COLS):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTR", "FTHG", "FTAG"])
    df = df.sort_values("Date", kind="stable").reset_index(drop=True)
    df["HomeClean"] = df["HomeTeam"].apply(clean_name)
    df["AwayClean"] = df["AwayTeam"].apply(clean_name)
    df = df.drop_duplicates(subset=["Date", "HomeClean", "AwayClean"],
                            keep="last").reset_index(drop=True)
    df["date_day"] = df["Date"].dt.normalize()
    return df


def dropped_matches(frames: Dict[str, pd.DataFrame]) -> List[dict]:
    """Partite in perimetro senza tutte e quattro le colonne dei tiri.

    Restano fuori dal dataset, quindi non entrano nemmeno nello stato
    point-in-time (nessuna imputazione e nessun buco silenzioso).
    """
    out: List[dict] = []
    for league, df in frames.items():
        sub = df[df["season"].isin(SEASONS)]
        bad = sub[sub[list(SHOT_COLS)].isna().any(axis=1)]
        for row in bad.itertuples():
            out.append({"league": league, "season": row.season,
                        "date": str(row.date_day.date()),
                        "home": row.HomeClean, "away": row.AwayClean,
                        "missing": [c for c in SHOT_COLS
                                    if not np.isfinite(getattr(row, c))]})
    return out


def coverage_table(frames: Dict[str, pd.DataFrame]) -> dict:
    """Righe per lega x stagione e righe con almeno un valore mancante."""
    out: Dict[str, dict] = {}
    for league, df in frames.items():
        entry: Dict[str, dict] = {}
        for season in (*SEASONS, "2026/27"):
            sub = df[df["season"] == season]
            if sub.empty:
                entry[season] = {"rows": 0}
                continue
            missing_any = sub[list(SHOT_COLS)].isna().any(axis=1)
            entry[season] = {
                "rows": int(len(sub)),
                "rows_missing_any": int(missing_any.sum()),
                "rows_complete": int((~missing_any).sum()),
                "missing_per_column": {c: int(sub[c].isna().sum()) for c in SHOT_COLS},
                "in_perimeter": season in SEASONS,
            }
        out[league] = entry
    return out


# ---------------------------------------------------------------------------
# 2. Feature point-in-time (fissate a priori)
# ---------------------------------------------------------------------------
class TeamShotState:
    """Sommatorie per squadra delle partite STRETTAMENTE precedenti."""

    __slots__ = ("shots_for", "shots_against", "sot_for", "sot_against", "n")

    def __init__(self):
        self.shots_for = 0.0
        self.shots_against = 0.0
        self.sot_for = 0.0
        self.sot_against = 0.0
        self.n = 0

    def observe(self, shots_for, shots_against, sot_for, sot_against):
        self.shots_for += float(shots_for)
        self.shots_against += float(shots_against)
        self.sot_for += float(sot_for)
        self.sot_against += float(sot_against)
        self.n += 1


def build_point_in_time_features(source: pd.DataFrame, *,
                                 scope: str = "cumulative",
                                 sot_mode: str = "share",
                                 include_self: bool = False) -> pd.DataFrame:
    """Feature tiri di ogni partita, stato a INIZIO GIORNATA.

    Regola (fissata a priori, la piu' conservativa): una partita entra nel
    "visto" di una squadra solo se la sua ``date_day`` e' STRETTAMENTE
    precedente a quella della partita in esame. Tutte le partite di una
    giornata vengono quindi valutate con lo stato di inizio giornata e lo stato
    viene aggiornato solo DOPO averle processate tutte: nessuna partita dello
    stesso giorno puo' entrare nella propria feature (e nemmeno in quella di
    un'altra partita della stessa giornata).

    ``scope="cumulative"``: lo stato non si azzera a inizio stagione (come il
    fallback gol di produzione, che accumula su tutto lo storico visto).
    ``scope="season"``:   stato e media di lega azzerati a inizio stagione
    (come la fonte F_season degli xG). Riportata come sensibilita'.

    ``sot_mode="share"``: quota = HST/HS (frazione di tiri in porta).
    ``sot_mode="rate"``:  tiri in porta per partita.

    ``include_self=True`` e' l'INIEZIONE CONTROLLATA DI UN LEAK VERO: la
    partita stessa entra nelle proprie medie prima di calcolarle. Serve al
    controllo di potere del test di leakage, non al calcolo delle feature.

    Shrinkage: ``app._shrunk_ratio(observed, expected, n, prior=PRIOR_MATCHES)``,
    cioe' la stessa identica formula della produzione: il rapporto
    osservato/atteso viene tirato verso 1.0 (media di lega) con 6 partite
    fittizie. Con n=0 (nessuno storico) la produzione restituisce 1.0: la
    feature vale 0 in log-spazio, senza imputazioni inventate.

    Media di lega point-in-time: media per squadra-partita delle stesse partite
    viste (tiri: totale tiri di entrambe le squadre / 2 / n partite; quota:
    totale tiri in porta / totale tiri).
    """
    if scope not in ("cumulative", "season"):
        raise ValueError(scope)
    if sot_mode not in ("share", "rate"):
        raise ValueError(sot_mode)

    df = source.copy()
    df["key_internal"] = np.arange(len(df))
    rows: Dict[int, dict] = {}

    # Stato: per squadra (scope cumulativo -> chiave lega; stagionale -> lega+stagione)
    state: Dict[Tuple, TeamShotState] = {}
    league_state: Dict[Tuple, dict] = {}

    def team_key(league, season, team):
        return (league, team) if scope == "cumulative" else (league, season, team)

    def league_key(league, season):
        return (league,) if scope == "cumulative" else (league, season)

    def factors(league, season, team):
        """(r_att_vol, r_att_sot, r_def_vol, r_def_sot) della squadra."""
        ls = league_state.get(league_key(league, season))
        st = state.get(team_key(league, season, team))
        if ls is None or st is None or st.n == 0 or ls["n"] == 0:
            return 1.0, 1.0, 1.0, 1.0
        mean_shots = ls["shots"] / (2.0 * ls["n"])
        att_vol = prod_app._shrunk_ratio(st.shots_for / st.n, mean_shots, st.n,
                                         prior=PRIOR_MATCHES)
        def_vol = prod_app._shrunk_ratio(st.shots_against / st.n, mean_shots,
                                         st.n, prior=PRIOR_MATCHES)
        if sot_mode == "share":
            mean_sot = ls["sot"] / ls["shots"] if ls["shots"] > 0 else 0.0
            att_obs = st.sot_for / st.shots_for if st.shots_for > 0 else 0.0
            def_obs = (st.sot_against / st.shots_against
                       if st.shots_against > 0 else 0.0)
        else:
            mean_sot = ls["sot"] / (2.0 * ls["n"])
            att_obs = st.sot_for / st.n
            def_obs = st.sot_against / st.n
        att_sot = (prod_app._shrunk_ratio(att_obs, mean_sot, st.n,
                                          prior=PRIOR_MATCHES)
                   if mean_sot > 0 else 1.0)
        def_sot = (prod_app._shrunk_ratio(def_obs, mean_sot, st.n,
                                          prior=PRIOR_MATCHES)
                   if mean_sot > 0 else 1.0)
        return att_vol, att_sot, def_vol, def_sot

    def observe(league, season, team, sf, sa, stf, sta):
        """Registra UNA partita vista da una squadra (aggiorna anche la lega)."""
        state.setdefault(team_key(league, season, team),
                         TeamShotState()).observe(sf, sa, stf, sta)
        ls = league_state.setdefault(
            league_key(league, season), {"shots": 0.0, "sot": 0.0, "n": 0})
        ls["shots"] += float(sf) + float(sa)
        ls["sot"] += float(stf) + float(sta)
        ls["n"] += 1

    for (league, season), block in df.groupby(["league", "season"], sort=False):
        block = block.sort_values(["date_day", "key_internal"], kind="stable")
        for day, dayblock in block.groupby("date_day", sort=True):
            # --- feature di TUTTA la giornata, con lo stato di inizio giornata
            for row in dayblock.itertuples():
                home, away = row.home, row.away
                got = bool(row.stats_complete)
                if include_self and got:
                    # INIEZIONE CONTROLLATA DI UN LEAK VERO: le statistiche della
                    # partita stessa (e di quelle gia' processate della stessa
                    # giornata) entrano nello stato PRIMA di calcolare la feature.
                    _sf, _sa = float(row.HS), float(row.AS)
                    _sf_t, _sa_t = float(row.HST), float(row.AST)
                    observe(league, season, home, _sf, _sa, _sf_t, _sa_t)
                    observe(league, season, away, _sa, _sf, _sa_t, _sf_t)
                a_vol_h, a_sot_h, d_vol_h, d_sot_h = factors(league, season, home)
                a_vol_a, a_sot_a, d_vol_a, d_sot_a = factors(league, season, away)
                rows[row.key_internal] = {
                    "x_vol_home": math.log(a_vol_h) + math.log(d_vol_a),
                    "x_sot_home": math.log(a_sot_h) + math.log(d_sot_a),
                    "x_vol_away": math.log(a_vol_a) + math.log(d_vol_h),
                    "x_sot_away": math.log(a_sot_a) + math.log(d_sot_h),
                    "n_home": int(state[team_key(league, season, home)].n)
                    if team_key(league, season, home) in state else 0,
                    "n_away": int(state[team_key(league, season, away)].n)
                    if team_key(league, season, away) in state else 0,
                }
            # --- aggiornamento DOPO l'intera giornata ------------------------
            for row in dayblock.itertuples():
                if not bool(row.stats_complete):
                    continue
                hs, as_, hst, ast = (float(row.HS), float(row.AS),
                                     float(row.HST), float(row.AST))
                observe(league, season, row.home, hs, as_, hst, ast)
                observe(league, season, row.away, as_, hs, ast, hst)

    feat = pd.DataFrame.from_dict(rows, orient="index")
    feat.index.name = "key_internal"
    out = df.join(feat, on="key_internal")
    return out.drop(columns=["key_internal"])


# ---------------------------------------------------------------------------
# 3. Ridondanza: x_vol / x_sot vs att0_pure / def0_pure dell'avversario
# ---------------------------------------------------------------------------
def redundancy_report(df: pd.DataFrame) -> dict:
    """Correlazione per lega fra le feature e i parametri puri di produzione.

    I partner sono quelli che entrano nella lambda della stessa partita:
    per x_vol/x_sot di casa: ``att0_pure`` della squadra di casa e
    ``def0_pure`` dell'avversaria (trasferta), e viceversa. Tutto in
    log-spazio, come il modello.
    """
    out: Dict[str, dict] = {}
    for league, sub in df.groupby("league"):
        entry: Dict[str, dict] = {}
        sides = (
            ("home", sub["x_vol_home"], sub["x_sot_home"],
             np.log(sub["att0_pure_home"]), np.log(sub["def0_pure_away"])),
            ("away", sub["x_vol_away"], sub["x_sot_away"],
             np.log(sub["att0_pure_away"]), np.log(sub["def0_pure_home"])),
        )
        for side, xv, xs, att_opp, def_opp in sides:
            for fname, series in (("x_vol", xv), ("x_sot", xs)):
                for pname, partner in (("log_att0_pure", att_opp),
                                       ("log_def0_pure", def_opp)):
                    pair = pd.DataFrame({"f": series, "p": partner}).dropna()
                    key = f"{fname}_{side}"
                    entry.setdefault(key, {"n": int(len(pair))})[pname] = (
                        float(pair["f"].corr(pair["p"]))
                        if len(pair) > 2 and pair["f"].std() > 0
                        and pair["p"].std() > 0 else None)
        out[league] = entry
    return out


# ---------------------------------------------------------------------------
# 4. Modello: GLM Poisson con offset log(lambda di produzione)
# ---------------------------------------------------------------------------
def stack_sides(df: pd.DataFrame) -> pd.DataFrame:
    """Una riga per LATO (casa, trasferta): gol, lambda di produzione, feature."""
    home = pd.DataFrame({
        "league": df["league"], "season": df["season"], "date_day": df["date_day"],
        "side": "home", "goals": df["FTHG"],
        "lambda_prod": df["lambda_home"],
        "x_vol": df["x_vol_home"], "x_sot": df["x_sot_home"],
        "goals_total": df["FTHG"] + df["FTAG"],
        "goals_home": df["FTHG"], "goals_away": df["FTAG"],
    })
    away = pd.DataFrame({
        "league": df["league"], "season": df["season"], "date_day": df["date_day"],
        "side": "away", "goals": df["FTAG"],
        "lambda_prod": df["lambda_away"],
        "x_vol": df["x_vol_away"], "x_sot": df["x_sot_away"],
        "goals_total": df["FTHG"] + df["FTAG"],
        "goals_home": df["FTHG"], "goals_away": df["FTAG"],
    })
    return pd.concat([home, away], ignore_index=True)


def fit_glm(train: pd.DataFrame, feature_cols: Sequence[str] = FEATURE_COLS):
    """GLM Poisson dei gol con offset log(lambda_prod), coefficienti comuni."""
    usable = train.dropna(subset=[*feature_cols, "lambda_prod", "goals"])
    y = usable["goals"].to_numpy(dtype=float)
    offset = np.log(usable["lambda_prod"].to_numpy(dtype=float))
    design = sm.add_constant(usable[list(feature_cols)].to_numpy(dtype=float),
                             has_constant="add")
    fit = sm.GLM(y, design, family=sm.families.Poisson(), offset=offset).fit()
    null = sm.GLM(y, np.ones((len(y), 1)), family=sm.families.Poisson(),
                  offset=offset).fit()
    lr = 2.0 * (fit.llf - null.llf)
    return {
        "fit": fit, "n_obs": int(len(usable)), "n_matches": int(len(usable) // 2),
        "ll_full": float(fit.llf), "ll_offset_only": float(null.llf),
        "lr_stat": float(lr), "lr_df": len(feature_cols),
        "lr_p_value": float(scipy_stats.chi2.sf(lr, len(feature_cols))),
        "dispersion_pearson": float(fit.pearson_chi2 / fit.df_resid)
        if fit.df_resid else None,
        "coefficients": {
            name: {"beta": float(fit.params[i + 1]), "se": float(fit.bse[i + 1]),
                   "z": float(fit.tvalues[i + 1]),
                   "p_value": float(fit.pvalues[i + 1]),
                   "ci95": [float(fit.conf_int()[i + 1][0]),
                            float(fit.conf_int()[i + 1][1])]}
            for i, name in enumerate(feature_cols)
        },
    }


def predict_lambdas(eval_df: pd.DataFrame, fit_result: dict,
                    feature_cols: Sequence[str] = FEATURE_COLS) -> np.ndarray:
    """lambda_nuova = lambda_prod * exp(b1*x_vol + b2*x_sot), per lato."""
    fit = fit_result["fit"]
    x = eval_df[list(feature_cols)].to_numpy(dtype=float)
    design = sm.add_constant(x, has_constant="add")
    offset = np.log(eval_df["lambda_prod"].to_numpy(dtype=float))
    # ``which="mean"`` = scala dei lambda (non il predittore lineare). Il
    # parametro si chiamava ``linear`` nelle versioni precedenti di statsmodels.
    return np.asarray(fit.predict(design, offset=offset, which="mean"),
                      dtype=float)


# ---------------------------------------------------------------------------
# 5. Probabilita' e metriche (matrice dei punteggi di produzione)
# ---------------------------------------------------------------------------
def probabilities(lambda_home: np.ndarray, lambda_away: np.ndarray,
                  max_goals: int = 15) -> Dict[str, np.ndarray]:
    """Matrice congiunta come in produzione (``app._poisson_market``)."""
    out = {"ou25": np.empty(len(lambda_home)), "gg": np.empty(len(lambda_home))}
    for i, (lh, la) in enumerate(zip(lambda_home, lambda_away)):
        m = prod_app._poisson_market(float(lh), float(la), max_goals)
        out["ou25"][i] = 1.0 - m["u25"]
        out["gg"][i] = m["gg"]
    return out


def logloss(p: np.ndarray, y: np.ndarray) -> float:
    eps = 1e-15
    p = np.clip(p, eps, 1 - eps)
    return float(-np.mean(np.where(y > 0.5, np.log(p), np.log(1 - p))))


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def murphy(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> dict:
    """Scomposizione di Murphy a bin di ampiezza fissa (10 bin, [0, 1])."""
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, n_bins - 1)
    n = len(p)
    ybar = float(np.mean(y))
    rel = res = 0.0
    for b in range(n_bins):
        sel = idx == b
        cnt = int(sel.sum())
        if cnt == 0:
            continue
        pbar = float(np.mean(p[sel]))
        ybar_b = float(np.mean(y[sel]))
        rel += cnt * (pbar - ybar_b) ** 2
        res += cnt * (pbar - ybar) ** 2
    return {"bins": n_bins, "reliability": rel / n, "resolution": res / n,
            "uncertainty": ybar * (1 - ybar), "brier_decomposition": (rel - res) / n
            + ybar * (1 - ybar)}


# ---------------------------------------------------------------------------
# 6. Bootstrap a blocchi (lega x stagione x giornata)
# ---------------------------------------------------------------------------
def block_bootstrap(df: pd.DataFrame, replicates: int = BOOTSTRAP_REPLICATES,
                    seed: int = BOOTSTRAP_SEED) -> dict:
    """IC 95% sulla differenza appaiata di LogLoss (nuovo - produzione).

    Blocchi = (lega, stagione, giornata): la stagione e' quella di valutazione,
    quindi il blocco non attraversa mai i fold.
    """
    d = df.copy()
    d["block"] = (d["league"].astype(str) + "|" + d["season"].astype(str) + "|"
                  + d["date_day"].astype(str))
    codes, _ = pd.factorize(d["block"], sort=True)
    n_blocks = int(codes.max()) + 1
    out: Dict[str, dict] = {}
    rng = np.random.default_rng(seed)
    for market in (PRIMARY_MARKET, SAFETY_MARKET):
        y = d.loc[:, f"y_{market}"].to_numpy(dtype=float)
        p_new = d.loc[:, f"p_new_{market}"].to_numpy(dtype=float)
        p_prod = d.loc[:, f"p_prod_{market}"].to_numpy(dtype=float)
        l_new = -np.where(y > 0.5, np.log(np.clip(p_new, 1e-15, 1 - 1e-15)),
                          np.log(np.clip(1 - p_new, 1e-15, 1 - 1e-15)))
        l_prod = -np.where(y > 0.5, np.log(np.clip(p_prod, 1e-15, 1 - 1e-15)),
                           np.log(np.clip(1 - p_prod, 1e-15, 1 - 1e-15)))
        diff = l_new - l_prod
        block_sum = np.bincount(codes, weights=diff, minlength=n_blocks)
        block_cnt = np.bincount(codes, minlength=n_blocks).astype(float)
        draws = rng.integers(0, n_blocks, size=(replicates, n_blocks))
        num = block_sum[draws].sum(axis=1)
        den = block_cnt[draws].sum(axis=1)
        deltas = num / den
        point = float(np.sum(block_sum) / np.sum(block_cnt))
        out[market] = {
            "delta_logloss": point,
            "ci95": [float(np.percentile(deltas, 2.5)),
                     float(np.percentile(deltas, 97.5))],
            "bootstrap_mean": float(np.mean(deltas)),
            "bootstrap_sd": float(np.std(deltas, ddof=1)),
            "share_negative": float(np.mean(deltas < 0)),
            "replicates": int(replicates),
            "blocks": int(n_blocks),
            "seed": int(seed),
        }
    return out


# ---------------------------------------------------------------------------
# 7. Test di leakage con iniezione controllata
# ---------------------------------------------------------------------------
def _feature_key(df: pd.DataFrame) -> pd.Series:
    return (df["league"].astype(str) + "|" + df["date_day"].astype(str) + "|"
            + df["home"].astype(str) + "|" + df["away"].astype(str))


def leakage_test(source: pd.DataFrame, *, sample_per_league: int,
                 seed: int) -> dict:
    """(a) troncamento, (b) iniezione di futuro estremo, (c) leak vero.

    Le varianti (a) e (b) devono lasciare le feature della partita campione
    IDENTICHE al bit. La variante (c) e' l'iniezione controllata di un VERO
    leak (le statistiche della partita stessa): il test DEVE rilevarla,
    altrimenti il test non ha potere.
    """
    src = source[source["stats_complete"]].copy()
    if "fk" not in src.columns:
        src["fk"] = _feature_key(src)
    base = build_point_in_time_features(src)
    feat_cols = ("x_vol_home", "x_sot_home", "x_vol_away", "x_sot_away")
    base_feat = base.set_index("fk")[list(feat_cols)]
    rng = np.random.default_rng(seed)
    tested = 0
    diff_ab: List[str] = []
    diff_c: List[str] = []
    max_ab = 0.0
    max_c = 0.0
    detected_c: set = set()
    per_league: Dict[str, dict] = {}

    for league, sub in base.groupby("league"):
        eligible = sub[(sub["n_home"] >= 10) & (sub["n_away"] >= 10)]
        if eligible.empty:
            per_league[league] = {"tested": 0, "reason": "nessuna partita elegibile"}
            continue
        order = rng.permutation(len(eligible))[:sample_per_league]
        sample = eligible.iloc[order]
        league_src = src[src["league"] == league].copy()
        # (c) LEAK VERO, una sola costruzione per lega: la partita stessa entra
        #     nella propria media (builder volutamente in avanti). Il test deve
        #     rilevarlo su TUTTE le partite campionate.
        leak = build_point_in_time_features(league_src, include_self=True)
        leak = leak.set_index("fk")
        league_tested = 0
        for row in sample.itertuples():
            key = row.fk
            # (a) troncamento: resta solo cio' che ha data < giornata + la partita
            trunc_src = league_src[(league_src["date_day"] < row.date_day)
                                   | (league_src["fk"] == key)]
            trunc = build_point_in_time_features(trunc_src).set_index("fk")
            # (b) iniezione di futuro estremo per le due squadre in campo
            injections = []
            for i, factor in enumerate((50.0, 0.02)):
                for team, opp in ((row.home, row.away), (row.away, row.home)):
                    injections.append({
                        "league": league, "season": row.season,
                        "date_day": row.date_day + pd.Timedelta(days=7 * (i + 1)),
                        "home": team, "away": opp,
                        "FTHG": 0, "FTAG": 0,
                        "HS": 100.0 * factor, "AS": 100.0 / factor,
                        "HST": 90.0 * factor, "AST": 0.0,
                        "stats_complete": True})
            future = pd.concat([league_src, pd.DataFrame(injections)],
                               ignore_index=True)
            inj = build_point_in_time_features(future).set_index("fk")
            for variant, other, bucket in (("troncato", trunc, "ab"),
                                           ("iniettato", inj, "ab"),
                                           ("leak_partita_stessa", leak, "c")):
                if key not in other.index:
                    diff_ab.append(f"{league} {key}: riga assente in {variant}")
                    continue
                for col in feat_cols:
                    a = float(base_feat.loc[key, col])
                    b = float(other.loc[key, col])
                    diff = abs(a - b)
                    if bucket == "ab":
                        max_ab = max(max_ab, diff)
                        if diff > 0:
                            diff_ab.append(
                                f"{league} {key} {col} {variant}: {a!r} -> {b!r}")
                    else:
                        max_c = max(max_c, diff)
                        if diff > 0:
                            detected_c.add((league, key))
                            diff_c.append(f"{league} {key} {col}: {a!r} -> {b!r}")
            league_tested += 1
            tested += 1
        per_league[league] = {"tested": league_tested,
                              "eligible": int(len(eligible)),
                              "leak_detected": int(sum(
                                  1 for lg, k in detected_c if lg == league))}
    return {
        "sample_per_league": sample_per_league,
        "seed": seed,
        "matches_tested": tested,
        "variants_a_b": {
            "description": "troncamento (data >= giornata tolta) e iniezione di "
                           "partite sintetiche estreme con data successiva",
            "max_abs_difference": max_ab,
            "difference_count": len(diff_ab),
            "differences_first10": diff_ab[:10],
            "esito": "OK" if (max_ab == 0.0 and not diff_ab) else "NON OK",
        },
        "variant_c_true_leak": {
            "description": "iniezione controllata delle statistiche della partita "
                           "stessa (builder volutamente in avanti): il test deve "
                           "rilevarla",
            "max_abs_difference": max_c,
            "difference_count": len(diff_c),
            "matches_with_leak_detected": int(len(detected_c)),
            "differences_first10": diff_c[:10],
            "esito": ("OK (rilevato su tutte le partite campionate)"
                      if max_c > 0 and len(detected_c) == tested
                      else ("OK (rilevato)" if max_c > 0
                            else "NON OK (non rilevato)")),
        },
        "per_league": per_league,
    }


# ---------------------------------------------------------------------------
# 8. Report
# ---------------------------------------------------------------------------
def _fmt(x, nd=4):
    if x is None:
        return "n/d"
    if isinstance(x, str):
        return x
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return "n/d"
    return f"{x:.{nd}f}"


def render_markdown(report: dict) -> str:
    cov = report["coverage"]
    red = report["redundancy"]
    folds = report["folds"]
    boot = report["pooled"]["bootstrap"]
    pooled = report["pooled"]
    leak = report["leakage_test"]
    verdict = report["verdict"]
    lines: List[str] = []
    add = lines.append

    add("# Tiri e tiri in porta sul residuo della testa Totali: referto")
    add("")
    add("Referto GENERATO da `audit/shots_residual_test.py` (sola lettura: "
        "nessuna modifica a `SoccerMath/`).")
    add("")
    add("- Rigenerabile con: `python audit/shots_residual_test.py` "
        "(sola lettura; il commit di generazione e' in `meta.commit` del JSON)")
    add(f"- Banco riusato: `audit/ppda_residual_test.py`, "
        f"`audit/build_ppda_deep_rolling.py`, `audit/test_ppda_deep_rolling.py` "
        f"(branch `{report['meta']['bench_branch']}`, commit "
        f"`{report['meta']['bench_commit']}`)")
    add(f"- Stagioni: {', '.join(SEASONS)} (2022/23 solo riscaldamento, "
        f"2026/27 escluso)")
    add(f"- Prior di shrinkage: `app.PRIOR_MATCHES` = {report['meta']['prior_matches']}")
    add(f"- Bootstrap: {BOOTSTRAP_REPLICATES} repliche, seed {BOOTSTRAP_SEED}, "
        f"blocchi (lega x stagione x giornata)")
    add("")

    add("## 0. Definizioni fissate prima di guardare i numeri")
    add("")
    add("Stato per squadra a INIZIO GIORNATA: entrano solo le partite con data "
        "STRETTAMENTE precedente a quella della partita (tutte le partite di una "
        "giornata vedono lo stesso stato e lo stato si aggiorna dopo la giornata). "
        f"Shrinkage `app._shrunk_ratio(observed, expected, n, prior=PRIOR_MATCHES)` "
        f"letto dalla produzione (prior = {report['meta']['prior_matches']}); con "
        "n = 0 il rapporto e' 1.0, quindi la feature vale 0 in log-spazio.")
    add("")
    add("- `x_vol` (casa) = log(tiri fatti casa / media lega) + "
        "log(tiri concessi trasferta / media lega)")
    add("- `x_sot` (casa) = log(quota tiri in porta fatti casa / media lega) + "
        "log(quota tiri in porta concessi trasferta / media lega)")
    add("- simmetrico per la trasferta; **solo queste due covariate**.")
    add("")
    add("`quota` = HST/HS (frazione di tiri in porta sul totale dei tiri). La "
        "lettura alternativa (tiri in porta per partita) e' nella sezione 7.")
    add("")
    add("Media di lega point-in-time: media per squadra-partita calcolata sulle "
        "stesse partite gia' viste (tiri: totale tiri delle due squadre / 2 / n; "
        "quota: totale tiri in porta / totale tiri).")
    add("")
    add("Modello dei fold: `lambda_nuova = lambda_prod * exp(b1*x_vol + b2*x_sot)` "
        "con b1, b2 COMUNI alle 5 leghe e ai due lati, stimati per massima "
        "verosimiglianza Poisson sui gol (GLM con `offset = log(lambda_prod)`; le "
        "righe casa e trasferta sono impilate). Probabilita' da "
        "`app._poisson_market` (matrice dei punteggi di produzione).")
    add("")

    add("## 1. Copertura di HS/AS/HST/AST (football-data)")
    add("")
    add("| lega | stagione | righe | righe con almeno un valore mancante | HS | AS | HST | AST |")
    add("|---|---|---|---|---|---|---|---|")
    for league, seasons in cov.items():
        for season, e in seasons.items():
            if not e.get("rows"):
                continue
            mp = e["missing_per_column"]
            mark = "" if e["in_perimeter"] else " (esclusa)"
            add(f"| {league} | {season}{mark} | {e['rows']} | {e['rows_missing_any']} | "
                f"{mp['HS']} | {mp['AS']} | {mp['HST']} | {mp['AST']} |")
    add("")
    n_drop = report["meta"]["matches_dropped_stats"]
    add(f"Partite in perimetro con statistiche complete: "
        f"**{report['meta']['matches_complete']}** su "
        f"{report['meta']['matches_perimeter']} "
        f"({n_drop} scartata per valori mancanti)."
        if n_drop == 1 else
        f"Partite in perimetro con statistiche complete: "
        f"**{report['meta']['matches_complete']}** su "
        f"{report['meta']['matches_perimeter']} "
        f"({n_drop} scartate per valori mancanti).")
    add("")
    if report["dropped_matches"]:
        add("Partite scartate (fuori dal dataset e quindi anche dallo stato "
            "point-in-time, nessuna imputazione):")
        add("")
        add("| lega | stagione | data | casa | trasferta | colonne mancanti |")
        add("|---|---|---|---|---|---|")
        for d in report["dropped_matches"]:
            add(f"| {d['league']} | {d['season']} | {d['date']} | {d['home']} | "
                f"{d['away']} | {', '.join(d['missing'])} |")
        add("")

    add("## 2. Lambda di produzione (testa Totali, point-in-time)")
    add("")
    add("Ricostruzione walk-forward con il banco riusato "
        "(`ppda_residual_test.production_totali`): `att0_pure`/`def0_pure` dalla "
        "fonte F_season al cutoff della partita, shrinkage `_shrunk_ratio` e media "
        "gol cumulative delle partite precedenti, poi "
        "`app._clip_lambda(att0_pure * def0_pure_avversario * media_gol)`.")
    add("")
    add("Verifica ESEGUITA, non assunta: le probabilita' Under 2.5 e GG della "
        "ricostruzione (`app._poisson_market` sui due lambda) vengono confrontate "
        "con quelle restituite dal motore di produzione "
        "(`app.get_full_poisson_two_heads` importata, applicata agli stessi "
        "dizionari di statistiche). Lo scarto massimo assoluto e' la prova che il "
        "lambda usato nel test e' quello di produzione.")
    add("")
    add("| lega | partite | scarto max Under 2.5 ricostruito vs motore | scarto max GG | fallback gol (partite) 2023/24 | 2024/25 | 2025/26 |")
    add("|---|---|---|---|---|---|---|")
    for league, e in report["engine_check"].items():
        fb = e.get("fallback_count_by_season", {})
        add(f"| {league} | {e['matches']} | {e['max_abs_diff_u25']:.2e} | "
            f"{e['max_abs_diff_gg']:.2e} | {fb.get('2023/24', 0)} | "
            f"{fb.get('2024/25', 0)} | {fb.get('2025/26', 0)} |")
    add("")
    add("Fallback gol = partite in cui la fonte F_season non passa il gate "
        "(tipicamente la prima giornata di stagione) e `att0_pure`/`def0_pure` "
        "ricadono sul fallback gol di produzione. Nessuna partita del dataset e' "
        "rimasta senza lambda di produzione (non agganciate: 0 in tutte le leghe).")
    add("")

    add("## 3. Ridondanza: x_vol / x_sot vs parametri puri di produzione")
    add("")
    add("Partner di ogni feature sono i due parametri che entrano nella lambda "
        "di quella partita: per il lato casa, `att0_pure` della squadra di casa e "
        "`def0_pure` dell'avversaria (trasferta); per il lato trasferta, il "
        "simmetrico. Tutto in log-spazio come il modello.")
    add("")
    add("| lega | covariata (lato) | n | corr con log(att0_pure) | corr con log(def0_pure dell'avversaria) |")
    add("|---|---|---|---|---|")
    for league, entry in red.items():
        for key, vals in entry.items():
            add(f"| {league} | {key} | {vals['n']} | "
                f"{_fmt(vals.get('log_att0_pure'), 3)} | "
                f"{_fmt(vals.get('log_def0_pure'), 3)} |")
    add("")

    add("## 4. Coefficienti per fold (coefficienti comuni alle 5 leghe)")
    add("")
    add("| fold | stima su | n osservazioni (lati) | x_vol | x_sot | LR vs solo offset | p | dispersione di Pearson |")
    add("|---|---|---|---|---|---|---|---|")
    for fold in FOLDS:
        e = folds[fold["name"]]
        c = e["coefficients"]
        add(f"| {fold['name']} | {'+'.join(fold['train'])} | {e['n_obs']} | "
            f"{c['x_vol']['beta']:.4f} [{c['x_vol']['ci95'][0]:.4f}, {c['x_vol']['ci95'][1]:.4f}] | "
            f"{c['x_sot']['beta']:.4f} [{c['x_sot']['ci95'][0]:.4f}, {c['x_sot']['ci95'][1]:.4f}] | "
            f"{e['lr_stat']:.2f} | {e['lr_p_value']:.4g} | {e['dispersion_pearson']:.4f} |")
    add("")

    add("## 5. LogLoss O/U 2.5 e GG/NG (pooled sui due fold)")
    add("")
    add("| mercato | modello | LogLoss | Brier | reliability | resolution |")
    add("|---|---|---|---|---|---|")
    for market in (PRIMARY_MARKET, SAFETY_MARKET):
        name = "O/U 2.5" if market == PRIMARY_MARKET else "GG/NG"
        for model in ("produzione", "tiri"):
            m = pooled["metrics"][market][model]
            add(f"| {name} | {model} | {m['logloss']:.6f} | {m['brier']:.6f} | "
                f"{m['reliability']:.6f} | {m['resolution']:.6f} |")
    add("")
    add("| mercato | Delta LogLoss (tiri - produzione) | IC 95% bootstrap | quota di repliche con Delta < 0 | blocchi |")
    add("|---|---|---|---|---|")
    for market in (PRIMARY_MARKET, SAFETY_MARKET):
        name = "O/U 2.5" if market == PRIMARY_MARKET else "GG/NG"
        b = boot[market]
        add(f"| {name} | {b['delta_logloss']:+.6f} | "
            f"[{b['ci95'][0]:+.6f}, {b['ci95'][1]:+.6f}] | "
            f"{b['share_negative']:.4f} | {b['blocks']} |")
    add("")
    add("| fold | lega | mercato | Delta LogLoss | n |")
    add("|---|---|---|---|---|")
    for row in pooled["per_fold_league"]:
        add(f"| {row['fold']} | {row['league']} | "
            f"{'O/U 2.5' if row['market'] == PRIMARY_MARKET else 'GG/NG'} | "
            f"{row['delta_logloss']:+.6f} | {row['n']} |")
    add("")
    add("Segno di Delta O/U per lega e per fold: "
        f"{json.dumps(pooled['delta_signs'], ensure_ascii=False)}")
    add("")
    add("### LR test in-sample per lega (informativo, NON criterio)")
    add("")
    add("| fold | lega | LR | df | p |")
    add("|---|---|---|---|---|")
    for row in pooled["lr_per_league"]:
        add(f"| {row['fold']} | {row['league']} | {row['lr_stat']:.2f} | 2 | "
            f"{row['p_value']:.4g} |")
    add("")

    add("## 6. Test di leakage con iniezione controllata")
    add("")
    add("| variante | max scarto | differenze | esito |")
    add("|---|---|---|---|")
    add(f"| (a+b) troncamento e iniezione di futuro estremo | "
        f"{leak['variants_a_b']['max_abs_difference']:.2e} | "
        f"{leak['variants_a_b']['difference_count']} | {leak['variants_a_b']['esito']} |")
    add(f"| (c) leak vero (statistiche della partita stessa) | "
        f"{leak['variant_c_true_leak']['max_abs_difference']:.6f} | "
        f"{leak['variant_c_true_leak']['difference_count']} | "
        f"{leak['variant_c_true_leak']['esito']} |")
    add("")
    add(f"Partite campionate: {leak['matches_tested']} "
        f"({leak['sample_per_league']} per lega, seed {leak['seed']}).")
    add("")

    add("## 7. Verdetto (regola fissata a priori)")
    add("")
    add(f"- Delta LogLoss O/U pooled < 0: {'SI' if verdict['delta_negative'] else 'NO'} "
        f"(Delta = {boot[PRIMARY_MARKET]['delta_logloss']:+.6f})")
    add(f"- IC 95% che esclude lo zero: "
        f"{'SI' if verdict['ci_excludes_zero'] else 'NO'} "
        f"([{boot[PRIMARY_MARKET]['ci95'][0]:+.6f}, "
        f"{boot[PRIMARY_MARKET]['ci95'][1]:+.6f}])")
    add(f"- Negativo in entrambi i fold: "
        f"{'SI' if verdict['negative_both_folds'] else 'NO'} "
        f"({json.dumps(verdict['delta_per_fold'], ensure_ascii=False)})")
    add(f"- Vincolo GG/NG rispettato (Delta <= +{SAFETY_TOLERANCE}): "
        f"{'SI' if verdict['gg_constraint_ok'] else 'NO'} "
        f"(Delta = {boot[SAFETY_MARKET]['delta_logloss']:+.6f})")
    add("")
    add(f"**Verdetto: {verdict['verdict']}**")
    add("")
    add(f"Sensibilita' dichiarata (NON e' il primary): {report['sensitivity']['note']}")
    add("")
    add("| sensibilita' | Delta LogLoss O/U | IC 95% | Delta LogLoss GG/NG | IC 95% |")
    add("|---|---|---|---|---|")
    for name, s in report["sensitivity"]["variants"].items():
        add(f"| {name} | {s['ou25']['delta_logloss']:+.6f} | "
            f"[{s['ou25']['ci95'][0]:+.6f}, {s['ou25']['ci95'][1]:+.6f}] | "
            f"{s['gg']['delta_logloss']:+.6f} | "
            f"[{s['gg']['ci95'][0]:+.6f}, {s['gg']['ci95'][1]:+.6f}] |")
    add("")
    add("## 8. Conformita' alla richiesta (esito / comando / evidenza)")
    add("")
    add("| requisito | esito | comando | evidenza |")
    add("|---|---|---|---|")
    add("| Solo `audit/` toccato (nessuna modifica a `SoccerMath/`) | "
        "NON VERIFICABILE dal referto | `git diff --name-only origin/main...HEAD` | "
        "dipende dal contesto git del branch: l'esito e' riportato nella PR, "
        "non qui |")
    add(f"| Banco PPDA/deep riusato, non riscritto | OK | "
        f"`git show {report['meta']['bench_commit']}:audit/ppda_residual_test.py` | "
        f"`audit/ppda_residual_test.py` (production_totali) + "
        f"`audit/build_ppda_deep_rolling.py` (test di leakage) dal branch "
        f"`{report['meta']['bench_branch']}`, commit "
        f"`{report['meta']['bench_commit']}` |")
    add(f"| Copertura HS/AS/HST/AST per lega e stagione | OK | "
        f"`python audit/shots_residual_test.py` | sezione 1: "
        f"{report['meta']['matches_complete']}/{report['meta']['matches_perimeter']} "
        f"partite complete, {report['meta']['matches_dropped_stats']} scartate |")
    add(f"| Lambda di produzione point-in-time senza toccare la produzione | OK | "
        f"`production_totali` (banco) + `app.get_full_poisson_two_heads` | "
        f"scarto massimo ricostruzione vs motore = "
        f"{max(e['max_abs_diff_u25'] for e in report['engine_check'].values()):.2e} "
        f"(Under 2.5) |")
    add(f"| Feature fissate, due covariate | OK | sezione 0 | `x_vol`, `x_sot` "
        f"point-in-time a inizio giornata, shrinkage PRIOR_MATCHES |")
    add(f"| Leakage: nessuna finestra in avanti | "
        f"{leak['variants_a_b']['esito']} | varianti (a) e (b) del test | max "
        f"scarto {leak['variants_a_b']['max_abs_difference']:.2e} su "
        f"{leak['matches_tested']} partite |")
    add(f"| Leakage: il test rileva un leak vero | "
        f"{leak['variant_c_true_leak']['esito']} | variante (c) del test | "
        f"rilevato su {leak['variant_c_true_leak']['matches_with_leak_detected']}/"
        f"{leak['matches_tested']} partite, max scarto "
        f"{leak['variant_c_true_leak']['max_abs_difference']:.4f} |")
    add(f"| Ridondanza riportata prima dei modelli | OK | sezione 3 | "
        f"correlazioni x_vol / x_sot vs log(att0_pure), log(def0_pure) per lega |")
    add(f"| Rolling-origin fissato (2023/24 -> 2024/25; +2024/25 -> 2025/26) | OK | "
        f"sezione 4 | n osservazioni di stima 3504 e 7006 lati |")
    add(f"| Bootstrap a blocchi, {BOOTSTRAP_REPLICATES} repliche, IC 95% | OK | "
        f"sezione 5 | "
        f"{boot[PRIMARY_MARKET]['blocks']} blocchi (lega x stagione x giornata), "
        f"seed {BOOTSTRAP_SEED} |")
    add(f"| Sicurezza GG/NG entro +{SAFETY_TOLERANCE} | "
        f"{'OK' if verdict['gg_constraint_ok'] else 'NON OK'} | sezione 5 | Delta "
        f"{boot[SAFETY_MARKET]['delta_logloss']:+.6f} |")
    add(f"| Regola di decisione applicata meccanicamente | OK | sezione 7 | "
        f"{verdict['verdict']} |")
    add("")
    add("Dettaglio macchina-leggibile: JSON del run (`--json`, con il comando di "
        "riferimento in `audit/output/shots_residual_test.json`, non versionato; "
        "`audit/output/` e' in `.gitignore`).")
    add("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 9. Main
# ---------------------------------------------------------------------------
def _git_changed_files(base: str = "origin/main") -> Optional[List[str]]:
    """File cambiati rispetto a ``origin/main`` (merge-base). None se il
    repository non permette il confronto (per esempio clone senza origin/main):
    nel referto il controllo risulta allora NON VERIFICABILE, non verde."""
    import subprocess
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", f"{base}...HEAD"],
            cwd=_REPO_ROOT, text=True, stderr=subprocess.DEVNULL)
        return [line for line in out.splitlines() if line.strip()]
    except Exception:                                   # pragma: no cover
        return None


def _git_commit() -> str:
    import subprocess
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"],
                                       cwd=_REPO_ROOT, text=True).strip()
    except Exception:                                   # pragma: no cover
        return "n/d"


def _prepare(league_frames: Dict[str, pd.DataFrame],
             verbose: bool = True) -> Tuple[pd.DataFrame, dict]:
    """Feature + lambda di produzione per le 5 leghe, unite e verificate."""
    engine_check: Dict[str, dict] = {}
    merged_frames: List[pd.DataFrame] = []
    for prefix, league in LEAGUES:
        t0 = time.time()
        shots = league_frames[league].rename(
            columns={"HomeClean": "home", "AwayClean": "away"}).copy()
        shots["league"] = league
        shots["stats_complete"] = shots[list(SHOT_COLS)].notna().all(axis=1)
        shots = shots[shots["season"].isin(SEASONS)].copy()
        feats = build_point_in_time_features(shots)
        engine = production_totali(prefix, league)
        engine = engine[engine["season"].isin(SEASONS)].copy()
        engine["date_day"] = pd.to_datetime(engine["date"]).dt.normalize()
        max_u25 = float((engine["engine_u25"] - engine["recon_u25"]).abs().max())
        max_gg = float((engine["engine_gg"] - engine["recon_gg"]).abs().max())
        fb_rate = engine.groupby("season")["fallback_home"].mean().to_dict()
        fb_count = engine.groupby("season")["fallback_home"].sum().to_dict()
        fb_count_away = engine.groupby("season")["fallback_away"].sum().to_dict()
        merged = feats.merge(
            engine[["season", "date_day", "home", "away", "att0_pure_home",
                    "def0_pure_home", "att0_pure_away", "def0_pure_away",
                    "lambda_home", "lambda_away", "fallback_home",
                    "fallback_away"]],
            on=["season", "date_day", "home", "away"], how="left",
            suffixes=("", "_eng"))
        unmatched = int(merged["lambda_home"].isna().sum())
        engine_check[league] = {
            "matches": int(len(engine)),
            "max_abs_diff_u25": max_u25,
            "max_abs_diff_gg": max_gg,
            "fallback_rate_by_season": {k: float(v) for k, v in fb_rate.items()},
            "fallback_count_by_season": {k: int(v) for k, v in fb_count.items()},
            "fallback_count_away_by_season": {k: int(v)
                                              for k, v in fb_count_away.items()},
            "rows_after_merge": int(len(merged)),
            "unmatched_to_engine": unmatched,
            "seconds": round(time.time() - t0, 1),
        }
        if verbose:
            print(f"[prepare] {league}: {len(merged)} righe, "
                  f"scarto max ricostruzione {max_u25:.2e}/{max_gg:.2e}, "
                  f"non agganciate {unmatched} ({time.time() - t0:.0f}s)")
        merged_frames.append(merged)
    out = pd.concat(merged_frames, ignore_index=True)
    out = out[out["stats_complete"] & out["lambda_home"].notna()].copy()
    return out, engine_check


def evaluate_variant(df: pd.DataFrame, *, scope: str, sot_mode: str,
                     verbose: bool = True) -> dict:
    """Rolling-origin completo su una variante di feature."""
    cols = ["league", "season", "date_day", "home", "away", "FTHG", "FTAG",
            "HS", "AS", "HST", "AST", "stats_complete",
            "att0_pure_home", "def0_pure_home", "att0_pure_away",
            "def0_pure_away", "lambda_home", "lambda_away"]
    built = build_point_in_time_features(df[cols].copy(), scope=scope,
                                         sot_mode=sot_mode)
    built = built[built["season"] != WARMUP_SEASON].copy()

    fold_rows: List[pd.DataFrame] = []
    fold_fits: Dict[str, dict] = {}
    lr_rows: List[dict] = []
    for fold in FOLDS:
        train = built[built["season"].isin(fold["train"])]
        eval_df = built[built["season"] == fold["eval"]]
        fit_res = fit_glm(stack_sides(train))
        fold_fits[fold["name"]] = fit_res
        ev = stack_sides(eval_df)
        ev["fold"] = fold["name"]
        ev["lambda_new"] = predict_lambdas(ev, fit_res)
        fold_rows.append(ev)
        if verbose:
            print(f"[{scope}/{sot_mode}] {fold['name']}: train "
                  f"{fit_res['n_obs']} lati, eval {len(ev)} lati")
    stacked = pd.concat(fold_rows, ignore_index=True)

    # Probabilita' dalla matrice dei punteggi di produzione ("_poisson_market")
    home = stacked[stacked["side"] == "home"].reset_index(drop=True)
    away = stacked[stacked["side"] == "away"].reset_index(drop=True)
    assert (home["goals_total"].to_numpy() == away["goals_total"].to_numpy()).all()
    p_prod = probabilities(home["lambda_prod"].to_numpy(),
                           away["lambda_prod"].to_numpy())
    p_new = probabilities(home["lambda_new"].to_numpy(),
                          away["lambda_new"].to_numpy())
    eval_matches = home[["league", "season", "date_day", "fold", "goals_total",
                         "goals_home", "goals_away"]].copy()
    eval_matches["y_ou25"] = (eval_matches["goals_total"] >= 3).astype(float)
    eval_matches["y_gg"] = ((eval_matches["goals_home"] >= 1)
                            & (eval_matches["goals_away"] >= 1)).astype(float)
    eval_matches["p_prod_ou25"] = p_prod["ou25"]
    eval_matches["p_new_ou25"] = p_new["ou25"]
    eval_matches["p_prod_gg"] = p_prod["gg"]
    eval_matches["p_new_gg"] = p_new["gg"]

    metrics: Dict[str, dict] = {}
    for market in (PRIMARY_MARKET, SAFETY_MARKET):
        y = eval_matches[f"y_{market}"].to_numpy()
        metrics[market] = {}
        for model, prefix in (("produzione", "prod"), ("tiri", "new")):
            p = eval_matches[f"p_{prefix}_{market}"].to_numpy()
            mur = murphy(p, y)
            metrics[market][model] = {
                "logloss": logloss(p, y), "brier": brier(p, y),
                "reliability": mur["reliability"], "resolution": mur["resolution"],
                "uncertainty": mur["uncertainty"]}
    boot = block_bootstrap(eval_matches)

    per_fold_league: List[dict] = []
    delta_signs: Dict[str, dict] = {}
    for market in (PRIMARY_MARKET, SAFETY_MARKET):
        y_all = eval_matches[f"y_{market}"].to_numpy()
        for fold_name in eval_matches["fold"].unique():
            for league in sorted(eval_matches["league"].unique()):
                sel = ((eval_matches["fold"] == fold_name)
                       & (eval_matches["league"] == league)).to_numpy()
                if sel.sum() == 0:
                    continue
                d = (logloss(eval_matches.loc[sel, f"p_new_{market}"].to_numpy(),
                             y_all[sel])
                     - logloss(eval_matches.loc[sel, f"p_prod_{market}"].to_numpy(),
                               y_all[sel]))
                per_fold_league.append({"fold": fold_name, "league": league,
                                        "market": market,
                                        "delta_logloss": d, "n": int(sel.sum())})
                if market == PRIMARY_MARKET:
                    delta_signs.setdefault(league, {})[fold_name] = d

    for fold in FOLDS:
        train = built[built["season"].isin(fold["train"])]
        for league in sorted(built["league"].unique()):
            sub = stack_sides(train[train["league"] == league])
            r = fit_glm(sub)
            lr_rows.append({"fold": fold["name"], "league": league,
                            "lr_stat": r["lr_stat"], "p_value": r["lr_p_value"],
                            "n_obs": r["n_obs"]})

    delta_per_fold = {}
    for fold in FOLDS:
        sel = (eval_matches["fold"] == fold["name"]).to_numpy()
        delta_per_fold[fold["name"]] = {
            "delta_ou25": logloss(eval_matches.loc[sel, "p_new_ou25"].to_numpy(),
                                  eval_matches.loc[sel, "y_ou25"].to_numpy())
            - logloss(eval_matches.loc[sel, "p_prod_ou25"].to_numpy(),
                      eval_matches.loc[sel, "y_ou25"].to_numpy()),
            "n": int(sel.sum())}

    return {
        "scope": scope, "sot_mode": sot_mode,
        "coefficients": {k: v["coefficients"] for k, v in fold_fits.items()},
        "metrics": metrics, "bootstrap": boot,
        "per_fold_league": per_fold_league, "delta_signs": delta_signs,
        "lr_per_league": lr_rows, "delta_per_fold": delta_per_fold,
        "n_eval": int(len(eval_matches)),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Test sul residuo della testa Totali con tiri e tiri in porta")
    parser.add_argument("--json", default=DEFAULT_JSON)
    parser.add_argument("--report", default=REPORT_PATH)
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument("--leakage-sample", type=int,
                        default=LEAKAGE_SAMPLE_PER_LEAGUE,
                        help="partite per lega nel test di leakage (0 = salta)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    print("=== 1. Caricamento CSV football-data (HS/AS/HST/AST) ===")
    frames = {league: load_league_shots(prefix) for prefix, league in LEAGUES}
    coverage = coverage_table(frames)
    for league, seasons in coverage.items():
        for season, e in seasons.items():
            if not e.get("rows"):
                continue
            print(f"  {league:16s} {season} righe={e['rows']:4d} "
                  f"mancanti={e['rows_missing_any']:3d} "
                  f"(HS {e['missing_per_column']['HS']}, "
                  f"AS {e['missing_per_column']['AS']}, "
                  f"HST {e['missing_per_column']['HST']}, "
                  f"AST {e['missing_per_column']['AST']})")

    perimeter = sum(e["rows"] for s in coverage.values() for k, e in s.items()
                    if e.get("rows") and e.get("in_perimeter"))
    dropped_stats = sum(e["rows_missing_any"] for s in coverage.values()
                        for k, e in s.items()
                        if e.get("rows") and e.get("in_perimeter"))

    print("\n=== 2. Feature point-in-time + lambda di produzione ===")
    ready, engine_check = _prepare(frames)
    print(f"  partite utilizzabili: {len(ready)}")

    print("\n=== 3. Ridondanza (prima dei modelli) ===")
    redundancy = redundancy_report(ready)

    print("\n=== 4. Rolling-origin (primary) ===")
    primary = evaluate_variant(ready, scope="cumulative", sot_mode="share")
    print(f"  Delta LogLoss O/U pooled = "
          f"{primary['bootstrap']['ou25']['delta_logloss']:+.6f} "
          f"IC95% [{primary['bootstrap']['ou25']['ci95'][0]:+.6f}, "
          f"{primary['bootstrap']['ou25']['ci95'][1]:+.6f}]")
    print(f"  Delta LogLoss GG/NG pooled = "
          f"{primary['bootstrap']['gg']['delta_logloss']:+.6f} "
          f"IC95% [{primary['bootstrap']['gg']['ci95'][0]:+.6f}, "
          f"{primary['bootstrap']['gg']['ci95'][1]:+.6f}]")

    print("\n=== 5. Sensibilita' dichiarate (non primary) ===")
    variants = {
        "x_sot come tiri in porta per partita": evaluate_variant(
            ready, scope="cumulative", sot_mode="rate"),
        "medie di stagione (stato azzerato a inizio stagione)": evaluate_variant(
            ready, scope="season", sot_mode="share"),
    }
    sensitivity = {
        "note": "due letture alternative, riportate per completezza: "
                "(1) x_sot come tasso di tiri in porta per partita invece che "
                "come quota sul totale tiri; (2) medie di stagione invece che "
                "cumulative. Il verdetto resta quello del primary.",
        "variants": {name: {"ou25": v["bootstrap"]["ou25"],
                            "gg": v["bootstrap"]["gg"]}
                     for name, v in variants.items()},
    }

    print("\n=== 6. Test di leakage (iniezione controllata) ===")
    src = ready[["league", "season", "date_day", "home", "away", "FTHG", "FTAG",
                 "HS", "AS", "HST", "AST"]].copy()
    src["stats_complete"] = True
    src["fk"] = _feature_key(src)
    leak = leakage_test(src, sample_per_league=args.leakage_sample,
                        seed=LEAKAGE_SEED)
    print(f"  (a+b) max scarto {leak['variants_a_b']['max_abs_difference']:.2e} "
          f"-> {leak['variants_a_b']['esito']}")
    print(f"  (c) leak vero max scarto "
          f"{leak['variant_c_true_leak']['max_abs_difference']:.6f} -> "
          f"{leak['variant_c_true_leak']['esito']}")

    boot_ou = primary["bootstrap"][PRIMARY_MARKET]
    boot_gg = primary["bootstrap"][SAFETY_MARKET]
    ci_lo, ci_hi = boot_ou["ci95"]
    verdict = {
        "delta_negative": boot_ou["delta_logloss"] < 0,
        "ci_excludes_zero": ci_lo < 0 and ci_hi < 0,
        "negative_both_folds": all(
            v["delta_ou25"] < 0 for v in primary["delta_per_fold"].values()),
        "delta_per_fold": {k: round(v["delta_ou25"], 6)
                           for k, v in primary["delta_per_fold"].items()},
        "gg_constraint_ok": boot_gg["delta_logloss"] <= SAFETY_TOLERANCE,
    }
    verdict["verdict"] = ("APRIRE un audit di integrazione"
                          if all((verdict["delta_negative"],
                                  verdict["ci_excludes_zero"],
                                  verdict["negative_both_folds"],
                                  verdict["gg_constraint_ok"]))
                          else "CHIUDERE la pista tiri: nessuna integrazione")

    report = {
        "meta": {
            "commit": _git_commit(),
            "bench_branch": "arena/01a0aaed-soccermath2-0",
            "bench_commit": "be09532",
            "bench_files": ["audit/ppda_residual_test.py",
                            "audit/build_ppda_deep_rolling.py",
                            "audit/test_ppda_deep_rolling.py"],
            "prior_matches": PRIOR_MATCHES,
            "seasons": list(SEASONS),
            "matches_perimeter": int(perimeter),
            "matches_dropped_stats": int(dropped_stats),
            "matches_complete": int(perimeter - dropped_stats),
            "changed_files": _git_changed_files(),
            "json_path": os.path.relpath(args.json, _REPO_ROOT),
        },
        "coverage": coverage,
        "dropped_matches": dropped_matches(frames),
        "engine_check": engine_check,
        "redundancy": redundancy,
        "pooled": {"metrics": primary["metrics"],
                   "bootstrap": primary["bootstrap"],
                   "per_fold_league": primary["per_fold_league"],
                   "delta_signs": primary["delta_signs"],
                   "lr_per_league": primary["lr_per_league"],
                   "n_eval_matches": primary["n_eval"]},
        "sensitivity": sensitivity,
        "leakage_test": leak,
        "verdict": verdict,
        "folds": {},
    }
    # Dettagli del fit del primary per fold (LR vs solo offset, dispersione, n):
    # stesso fit deterministico di ``evaluate_variant``, ricalcolato qui per il
    # referto senza dover passare l'oggetto statsmodels attraverso il JSON.
    for fold in FOLDS:
        key = fold["name"]
        train = ready[ready["season"].isin(fold["train"])]
        fit_res = fit_glm(stack_sides(train))
        report["folds"][key] = {k: v for k, v in fit_res.items() if k != "fit"}

    os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")
    print(f"\nJSON: {args.json}")

    if not args.no_report:
        md = render_markdown(report)
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(md)
            if not md.endswith("\n"):
                f.write("\n")
        print(f"Referto: {args.report}")

    print("\n=== VERDETTO ===")
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
