"""
elo_walker_core.py — Walker Elo FEDELE ALLA PRODUZIONE (audit, SOLA LETTURA).

Punto 2 della roadmap Elo. Nessuna riga di produzione viene modificata: questo
modulo IMPORTA e RIUSA il codice di produzione, non lo replica.

Cosa viene importato (e NON riscritto)
--------------------------------------
* ``models.elo_engine.EloEngine``            -> aggiornamento dei rating
  (K base 24, moltiplicatore per scarto ``calculate_goal_margin_multiplier``,
  home advantage per lega da ``config.LEAGUE_HOME_ADVANTAGE``).
  L'aritmetica dell'update NON e' riscritta qui: si usa ``compute_ratings()``.
* ``models.elo_engine.predict_elo_probs``    -> conversione Elo -> 1X2
  (e_H logistica su dr/400, p_draw gaussiana 0.27*exp(-(dr/320)^2) clip
  [0.06,0.34], normalizzazione, arrotondamento a 4 decimali).
  La formula NON e' riscritta qui.
* ``app.blend_elo_into_1x2``                 -> blend w*Poisson + (1-w)*Elo.
  La formula NON e' riscritta qui.
* ``diagnose_clv_pinnacle.run_model_with_elo`` -> testa Poisson di produzione
  (PRODUZIONE_DUE_TESTE / NORM-SUM), gia' bit-faithful a
  ``diagnose_production_baseline.run_models`` per test esistente.
  Di questo walker si usano SOLO le colonne ``prodn_1/X/2`` (Poisson) e, per
  il confronto del punto A.4, le sue ``elo_1/X/2`` (= VECCHIA REPLICA Elo:
  K fisso 24, nessun moltiplicatore per scarto, pre PR #24).

Come si ottiene il walk-forward senza riscrivere nulla
------------------------------------------------------
``EloEngine.compute_ratings()`` e' gia' una passata cronologica che, per ogni
partita, registra in ``engine.history[team]`` il campo ``elo_before`` (rating
PRIMA della partita) e ``elo_after``. Il walker quindi:

  1. esegue UNA volta ``compute_ratings()`` di produzione;
  2. ricostruisce, scorrendo ``engine.matches_df`` nell'ordine di produzione,
     la coppia (elo_before casa, elo_before trasferta) per ogni partita
     leggendo le liste ``history`` in ordine di append (un cursore per
     squadra). Sono i rating di produzione, non ricalcolati;
  3. per ogni partita inietta quei due rating in ``engine.ratings`` e chiama
     ``predict_elo_probs(home, away, league)`` di produzione, che legge il
     motore dalla cache di modulo ``_ELO_ENGINES_CACHE``.

=> previsione PRIMA, aggiornamento DOPO per costruzione (``elo_before`` e' per
definizione lo stato precedente all'applicazione del delta di quella partita).
Il walker non puo' "vedere" il risultato della partita che sta prevedendo.

EFFETTO COLLATERALE DICHIARATO (necessario, confinato al processo di audit)
--------------------------------------------------------------------------
``predict_elo_probs`` non accetta rating in input: prende il motore da
``models.elo_engine._ELO_ENGINES_CACHE`` (cache globale di modulo, TTL 3600 s).
Per usarla punto-nel-tempo bisogna scrivere in quella cache e mutare
``engine.ratings`` prima di ogni chiamata. Vedi ``REFACTOR_MINIMO_PROPOSTO``
in fondo al file: NON e' applicato.

ORDINAMENTO A PARITA' DI DATA (documentato, NON corretto)
---------------------------------------------------------
``EloEngine.load_and_preprocess_matches`` fa, nell'ordine:
    concat(files in ordine get_league_db_files)
    -> dropna(HomeTeam/AwayTeam/FTR) -> clean_name -> to_datetime(dayfirst=True)
    -> dropna(Date_Parsed) -> drop_duplicates([Date_Parsed,HomeClean,AwayClean], keep='last')
    -> sort_values("Date_Parsed")            # kind di default = 'quicksort'
I CSV football-data hanno granularita' GIORNO (la colonna ``Time`` esiste ma
non viene letta dal motore): tutte le partite dello stesso giorno hanno la
stessa chiave di ordinamento. ``sort_values`` senza ``kind`` usa quicksort,
che NON e' stabile: l'ordine relativo delle partite in pari data e' quello
prodotto dall'algoritmo di pandas, non necessariamente l'ordine del file.
Conseguenza: fra due partite dello stesso giorno, l'una puo' entrare nello
stato Elo prima dell'altra in modo non controllato dall'utente. Il walker NON
corregge questo comportamento: usa esattamente l'ordine di produzione.
``ordering_report()`` misura quanto l'ordine effettivo si discosta
dall'ordine-file (mergesort stabile).

Uso:
    from elo_walker_core import build_walker_table
    df = build_walker_table("Premier League")
"""
from __future__ import annotations

import os
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
if _AUDIT_DIR not in sys.path:
    sys.path.insert(0, _AUDIT_DIR)
_SM = os.path.join(_REPO_ROOT, "SoccerMath")
if _SM not in sys.path:
    sys.path.insert(0, _SM)

# --- PRODUZIONE (import, non riscrittura) --------------------------------
import models.elo_engine as PROD_ELO                      # noqa: E402
from models.elo_engine import EloEngine, predict_elo_probs  # noqa: E402
from config import LEAGUE_HOME_ADVANTAGE, clean_name, get_league_db_files  # noqa: E402

LEAGUES = ("Serie A", "Premier League", "La Liga", "Bundesliga", "Ligue 1")

#: mappa lega -> prefisso dei CSV (come audit/backtest_experiment_all.LEAGUES)
LEAGUE_PREFIX = {
    "Serie A": "SerieA",
    "Premier League": "Premier",
    "La Liga": "LaLiga",
    "Bundesliga": "Bundesliga",
    "Ligue 1": "Ligue1",
}


# =====================================================================
# Walker
# =====================================================================
def _prematch_ratings(engine: EloEngine) -> pd.DataFrame:
    """Per ogni partita di ``engine.matches_df``, il rating PRIMA della
    partita di casa e trasferta, letto da ``engine.history`` di produzione.

    ``compute_ratings`` appende a ``history[team]`` una voce per partita
    nell'ordine di iterazione del df: un cursore per squadra ricostruisce
    l'accoppiamento riga <-> voce senza ricalcolare nulla.
    Ogni accoppiamento e' verificato su (data, avversario, is_home): se non
    torna, si alza AssertionError (nessuna riconciliazione silenziosa).
    """
    df = engine.matches_df
    cur = defaultdict(int)
    rows = []
    for idx, row in df.iterrows():
        h, a = row["HomeClean"], row["AwayClean"]
        eh = engine.history[h][cur[h]]
        ea = engine.history[a][cur[a]]
        assert eh["date"] == row["Date_Parsed"] and eh["opponent"] == a and eh["is_home"] is True, \
            f"history casa disallineata su riga {idx}: {eh}"
        assert ea["date"] == row["Date_Parsed"] and ea["opponent"] == h and ea["is_home"] is False, \
            f"history trasferta disallineata su riga {idx}: {ea}"
        cur[h] += 1
        cur[a] += 1
        rows.append((eh["elo_before"], ea["elo_before"], eh["elo_after"], ea["elo_after"]))
    out = pd.DataFrame(rows, columns=["elo_home_pre", "elo_away_pre",
                                      "elo_home_post", "elo_away_post"],
                       index=df.index)
    return out


class _CacheInjection:
    """Context manager: installa ``engine`` nella cache di modulo di
    produzione per ``league`` e la ripulisce all'uscita (nessuno stato
    residuo fra leghe). Vedi EFFETTO COLLATERALE DICHIARATO nel docstring."""

    def __init__(self, league: str, engine: EloEngine):
        self.league = league
        self.engine = engine
        self._prev_engine = None
        self._prev_stamp = None

    def __enter__(self):
        self._prev_engine = PROD_ELO._ELO_ENGINES_CACHE.get(self.league)
        self._prev_stamp = PROD_ELO._ELO_ENGINES_STAMP.get(self.league)
        PROD_ELO._ELO_ENGINES_CACHE[self.league] = self.engine
        PROD_ELO._ELO_ENGINES_STAMP[self.league] = time.monotonic()
        return self

    def refresh(self):
        PROD_ELO._ELO_ENGINES_STAMP[self.league] = time.monotonic()

    def __exit__(self, *exc):
        if self._prev_engine is None:
            PROD_ELO._ELO_ENGINES_CACHE.pop(self.league, None)
            PROD_ELO._ELO_ENGINES_STAMP.pop(self.league, None)
        else:
            PROD_ELO._ELO_ENGINES_CACHE[self.league] = self._prev_engine
            PROD_ELO._ELO_ENGINES_STAMP[self.league] = self._prev_stamp
        return False


def build_walker_table(league: str, engine: EloEngine = None) -> pd.DataFrame:
    """Tabella per-partita del walker Elo fedele.

    Colonne: league, date, home_raw, away_raw, home, away, FTHG, FTAG, FTR,
    elo_home_pre, elo_away_pre, d (= dr con home advantage), e_H, p_draw,
    elo_1, elo_X, elo_2, home_adv.

    ``d``/``e_H``/``elo_1/X/2`` vengono dall'OUTPUT di ``predict_elo_probs``
    (produzione), non da una formula riscritta qui.
    """
    if engine is None:
        engine = EloEngine(league)
        engine.compute_ratings()
    df = engine.matches_df
    pre = _prematch_ratings(engine)
    final_ratings = dict(engine.ratings)   # da ripristinare a fine walk

    out = []
    with _CacheInjection(league, engine) as inj:
        for i, (idx, row) in enumerate(df.iterrows()):
            if i % 200 == 0:
                inj.refresh()              # mai far scadere il TTL di 3600 s
            h_cl, a_cl = row["HomeClean"], row["AwayClean"]
            r_h = pre.at[idx, "elo_home_pre"]
            r_a = pre.at[idx, "elo_away_pre"]
            # stato PRE-partita visibile a predict_elo_probs
            engine.ratings = {h_cl: r_h, a_cl: r_a}
            p = predict_elo_probs(row["HomeTeam"], row["AwayTeam"], league)
            fthg = row.get("FTHG")
            ftag = row.get("FTAG")
            out.append({
                "league": league,
                "date": row["Date_Parsed"],
                "home_raw": row["HomeTeam"], "away_raw": row["AwayTeam"],
                "home": h_cl, "away": a_cl,
                "FTHG": fthg, "FTAG": ftag,
                "FTR": str(row["FTR"]).strip().upper(),
                "home_adv": p["home_adv"],
                "elo_home_pre": r_h, "elo_away_pre": r_a,
                "d": p["elo_diff"],
                "e_H": p["expected_score_home"],
                # p_draw = componente pareggio di predict_elo_probs: la terna
                # e' gia' normalizzata a 1 per costruzione, quindi elo_X e'
                # esattamente p_draw arrotondato a 4 decimali dalla produzione.
                "p_draw": p["X"],
                "elo_1": p["1"], "elo_X": p["X"], "elo_2": p["2"],
            })
        engine.ratings = final_ratings
    return pd.DataFrame(out)


# =====================================================================
# Diagnostica sull'ordinamento a parita' di data (documentare, non correggere)
# =====================================================================
def ordering_report(league: str) -> dict:
    """Quanto l'ordine di produzione (quicksort, non stabile) differisce
    dall'ordine-file a parita' di data (mergesort stabile)."""
    engine = EloEngine(league)
    df = engine.load_and_preprocess_matches()          # ordine di PRODUZIONE
    # stessa pipeline fino al sort, poi sort STABILE: ordine-file sui pari-data
    files = get_league_db_files(league)
    dfs = []
    for f in files:
        t = pd.read_csv(f, on_bad_lines="warn", low_memory=False)
        if not t.empty and {"HomeTeam", "AwayTeam", "FTR", "Date"}.issubset(t.columns):
            dfs.append(t)
    raw = pd.concat(dfs, ignore_index=True).copy()
    raw = raw.dropna(subset=["HomeTeam", "AwayTeam", "FTR"])
    raw["HomeClean"] = raw["HomeTeam"].apply(clean_name)
    raw["AwayClean"] = raw["AwayTeam"].apply(clean_name)
    raw["Date_Parsed"] = pd.to_datetime(raw["Date"], dayfirst=True, errors="coerce")
    raw = raw.dropna(subset=["Date_Parsed"])
    raw = raw.drop_duplicates(subset=["Date_Parsed", "HomeClean", "AwayClean"], keep="last")
    stable = raw.sort_values("Date_Parsed", kind="mergesort").reset_index(drop=True)

    key_prod = list(zip(df["Date_Parsed"], df["HomeClean"], df["AwayClean"]))
    key_stab = list(zip(stable["Date_Parsed"], stable["HomeClean"], stable["AwayClean"]))
    sizes = df.groupby("Date_Parsed").size()
    return {
        "league": league,
        "n_matches": len(df),
        "n_date_con_piu_partite": int((sizes > 1).sum()),
        "n_partite_in_date_condivise": int(sizes[sizes > 1].sum()),
        "max_partite_stessa_data": int(sizes.max()) if len(sizes) else 0,
        "ordine_prod_uguale_ordine_file": key_prod == key_stab,
        "n_posizioni_diverse": int(sum(1 for a, b in zip(key_prod, key_stab) if a != b)),
    }


# =====================================================================
# REFACTOR_MINIMO_PROPOSTO (NON APPLICATO)
# =====================================================================
REFACTOR_MINIMO_PROPOSTO = """
models/elo_engine.py — estrarre la conversione Elo->1X2 in una funzione pura,
e far chiamare quella a predict_elo_probs (zero cambi numerici):

    def elo_probs_from_ratings(r_h: float, r_a: float, home_adv: float) -> dict:
        dr = r_h + home_adv - r_a
        e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
        e_a = 1.0 - e_h
        p_draw = 0.27 * math.exp(-((dr / 320.0) ** 2))
        p_draw = max(0.06, min(0.34, p_draw))
        p_home = (1.0 - p_draw) * e_h
        p_away = (1.0 - p_draw) * e_a
        total = p_home + p_draw + p_away
        return {...}   # corpo attuale di predict_elo_probs, invariato

    def predict_elo_probs(home_team, away_team, league_name) -> dict:
        engine = get_elo_engine(league_name)
        r_h = engine.ratings.get(clean_name(home_team), DEFAULT_INITIAL_RATING)
        r_a = engine.ratings.get(clean_name(away_team), DEFAULT_INITIAL_RATING)
        return elo_probs_from_ratings(r_h, r_a, engine.home_adv)

Motivo: senza questo, un backtest point-in-time non puo' chiedere le
probabilita' per rating arbitrari senza scrivere nella cache globale
_ELO_ENGINES_CACHE (effetto collaterale). Secondo (opzionale) hook utile:
EloEngine.compute_ratings(as_of=None) per limitare il df a Date_Parsed < as_of.
Nessuna delle due modifiche e' applicata in questo audit.
"""
