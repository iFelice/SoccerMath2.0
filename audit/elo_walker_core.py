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
* ``models.elo_engine.elo_probs_from_ratings`` -> conversione Elo -> 1X2
  (e_H logistica su dr/400, p_draw gaussiana 0.27*exp(-(dr/320)^2) clip
  [0.06,0.34], normalizzazione, arrotondamento a 4 decimali).
  La formula NON e' riscritta qui. E' la funzione PURA estratta da
  ``predict_elo_probs`` dalla PR #30 (bit-exact): prende i rating in input,
  non legge nessuno stato globale.
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
  3. per ogni partita passa quei due rating e l'home advantage della lega a
     ``elo_probs_from_ratings(r_h, r_a, home_adv)`` di produzione.

=> previsione PRIMA, aggiornamento DOPO per costruzione (``elo_before`` e' per
definizione lo stato precedente all'applicazione del delta di quella partita).
Il walker non puo' "vedere" il risultato della partita che sta prevedendo.

NESSUN EFFETTO COLLATERALE (dalla PR #30 in poi)
------------------------------------------------
La versione precedente di questo walker doveva scrivere in
``models.elo_engine._ELO_ENGINES_CACHE`` (cache globale di modulo, TTL 3600 s)
e mutare ``engine.ratings`` prima di ogni chiamata, perche' l'unico punto di
ingresso alla conversione era ``predict_elo_probs``, che i rating se li va a
prendere da solo dallo stato globale.

La PR #30 ha estratto ``elo_probs_from_ratings(r_h, r_a, home_adv)``: funzione
pura, i rating sono argomenti. Il walker ora chiama quella. Conseguenze
verificabili:

  * ``build_walker_table`` NON legge e NON scrive ``_ELO_ENGINES_CACHE`` /
    ``_ELO_ENGINES_STAMP`` (il test di parita' lo asserisce confrontando lo
    snapshot delle due dict prima e dopo la chiamata);
  * ``engine.ratings`` non viene piu' sovrascritto a ogni riga, quindi il
    motore passato dal chiamante esce dalla funzione integro;
  * non serve piu' il "refresh" periodico per non far scadere il TTL;
  * due walker su leghe diverse non possono piu' interferire fra loro.

L'aritmetica non cambia di un bit: ``predict_elo_probs`` e'
``elo_probs_from_ratings`` preceduta dalla sola risoluzione dei rating
(``engine.ratings.get(clean_name(team), DEFAULT_INITIAL_RATING)``), che qui
viene fatta dal walker a partire dalla ``history`` di produzione.

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
import models.elo_engine as PROD_ELO                      # noqa: E402  (solo per il test di non-interferenza)
from models.elo_engine import EloEngine, elo_probs_from_ratings  # noqa: E402
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


def build_walker_table(league: str, engine: EloEngine = None) -> pd.DataFrame:
    """Tabella per-partita del walker Elo fedele.

    Colonne: league, date, home_raw, away_raw, home, away, FTHG, FTAG, FTR,
    elo_home_pre, elo_away_pre, d (= dr con home advantage), e_H, p_draw,
    elo_1, elo_X, elo_2, home_adv.

    ``d``/``e_H``/``elo_1/X/2`` vengono dall'OUTPUT di
    ``elo_probs_from_ratings`` (produzione, funzione pura), non da una formula
    riscritta qui.

    NON tocca ``_ELO_ENGINES_CACHE``/``_ELO_ENGINES_STAMP`` e NON muta
    ``engine.ratings``: vedi "NESSUN EFFETTO COLLATERALE" nel docstring del
    modulo.
    """
    if engine is None:
        engine = EloEngine(league)
        engine.compute_ratings()
    df = engine.matches_df
    pre = _prematch_ratings(engine)
    home_adv = engine.home_adv       # stesso valore che predict_elo_probs passerebbe

    out = []
    for idx, row in df.iterrows():
        h_cl, a_cl = row["HomeClean"], row["AwayClean"]
        r_h = pre.at[idx, "elo_home_pre"]
        r_a = pre.at[idx, "elo_away_pre"]
        # funzione PURA di produzione: i rating pre-partita sono argomenti,
        # nessuno stato globale letto o scritto.
        p = elo_probs_from_ratings(r_h, r_a, home_adv)
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
            # p_draw = componente pareggio di elo_probs_from_ratings: la terna
            # e' gia' normalizzata a 1 per costruzione, quindi elo_X e'
            # esattamente p_draw arrotondato a 4 decimali dalla produzione.
            "p_draw": p["X"],
            "elo_1": p["1"], "elo_X": p["X"], "elo_2": p["2"],
        })
    return pd.DataFrame(out)


def cache_snapshot() -> tuple:
    """Fotografia delle due dict globali di ``models.elo_engine``.

    Serve al test di non-interferenza: ``build_walker_table`` deve lasciarle
    identiche a prima della chiamata.
    """
    return (
        {k: id(v) for k, v in PROD_ELO._ELO_ENGINES_CACHE.items()},
        dict(PROD_ELO._ELO_ENGINES_STAMP),
    )


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
# REFACTOR_MINIMO_PROPOSTO — stato aggiornato
# =====================================================================
REFACTOR_MINIMO_PROPOSTO = """
[1] APPLICATO IN PRODUZIONE dalla PR #30 (merge in main 4f07713).

    models/elo_engine.py espone ora la funzione pura

        elo_probs_from_ratings(r_h, r_a, home_adv) -> dict

    e predict_elo_probs la chiama dopo aver risolto i rating dal motore.
    Questo walker la usa direttamente: non scrive piu' in
    _ELO_ENGINES_CACHE, non muta engine.ratings.

[2] NON APPLICATO (resta una proposta, fuori dal perimetro di questo audit):

        EloEngine.compute_ratings(as_of=None)

    per limitare il df a Date_Parsed < as_of senza passare dalla riscrittura
    dei CSV in una cartella temporanea. Oggi il troncamento punto-nel-tempo
    (usato dal generatore della fixture, cutoff_cases) si ottiene ripuntando
    config.DATABASE_DIR su una copia filtrata.
"""
