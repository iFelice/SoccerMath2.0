"""
models/elo_engine.py - Motore di Calcolo Elo Rating Dinamico per M4-analist
"""

import math
import time
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from config import (
    DATABASE_DIR,
    DEFAULT_MARKET_VALUE,
    LEAGUES_CONFIG,
    LEAGUE_PREFIX_MAP,
    LEAGUE_HOME_ADVANTAGE,
    clean_name,
    get_league_db_files,
    get_market_values,
    season_start_year_of,
)

DEFAULT_INITIAL_RATING = 1500.0
HOME_ADVANTAGE = 65.0
BASE_K_FACTOR = 24.0

#: Distacco applicato al seeding delle squadre che ENTRANO in una lega.
#:
#: La PR #35 (audit ``audit/elo_drift_triage.py``, variante ``S3``) ha
#: misurato la deriva dei rating di ingresso: la produzione partiva da 1500
#: per le neopromosse mai viste e riprendeva il rating stantio per quelle di
#: ritorno, restando cosi' ~100 punti sopra la media delle squadre attive al
#: momento del loro esordio in lega. Il seeding S3 e' la media dei rating
#: delle squadre ATTIVE in quel momento (cioe' di quelle che hanno gia'
#: disputato almeno una partita in lega, nell'ordine di produzione) piu'
#: questo offset; il triage lo ha validato su 55 ingressi in 5 leghe
#: (DeltaLogLoss -0.018010 sulle prime 10 partite delle neopromosse).
#:
#: Non e' un parametro stimato: e' la costante dichiarata dalla variante S3
#: dell'audit, replicata qui senza modificarla. Nessun altro pezzo del motore
#: e' stato toccato: K, home advantage, moltiplicatore di scarto, draw e pesi
#: del blend restano quelli di prima.
PROMOTED_SEED_OFFSET = -100.0


def season_rosters_from_matches(df: pd.DataFrame) -> Dict[int, set]:
    """R(lega, stagione) = le squadre che compongono la lega in quella stagione.

    FONTE: il calendario della stagione, cioe' l'insieme delle squadre che
    compaiono nelle partite di quell'anno nei CSV di questa lega. Non e' un
    risultato: promozioni e retrocessioni sono decise e pubblicate prima del
    via, e il calendario della stagione e' pubblicato prima del via. Per la
    stagione in corso la stessa fonte e' il file ``*_Live.csv``, che l'app usa
    anche per le partite in programma.

    ``season_rosters`` puo' essere passato al costruttore quando il database
    non contiene il calendario completo (per esempio un backtest su CSV
    troncati): il caller passa allora il roster della stagione integrale,
    cosi' il riferimento del seed non dipende da quanto DB e' stato tagliato.
    """
    out: Dict[int, set] = {}
    stagioni = df["Date_Parsed"].map(season_start_year_of)
    for season, blocco in df.groupby(stagioni.to_numpy()):
        squadre = set(blocco["HomeClean"].unique()).union(
            set(blocco["AwayClean"].unique()))
        out[int(season)] = {str(t) for t in squadre}
    return out


def calculate_goal_margin_multiplier(goal_diff: int) -> float:
    diff = abs(goal_diff)
    if diff <= 1:
        return 1.0
    elif diff == 2:
        return 1.5
    elif diff == 3:
        return 1.75
    else:
        return 1.75 + (diff - 3) / 8.0


class EloEngine:

    def __init__(self, league_name: str, home_adv: float = None,
                 base_k: float = BASE_K_FACTOR,
                 season_rosters: Dict[int, set] | None = None):
        self.league_name = league_name
        self.home_adv = home_adv if home_adv is not None else LEAGUE_HOME_ADVANTAGE.get(league_name, HOME_ADVANTAGE)
        self.base_k = base_k
        self.ratings: Dict[str, float] = {}
        self.history: Dict[str, List[dict]] = {}
        self.team_stats: Dict[str, dict] = {}
        self.is_computed = False
        self.matches_df = pd.DataFrame()
        # Seeding degli ingressi in lega (PR #35): stagione dell'ultima partita
        # disputata da ciascuna squadra e stagione della prima partita del
        # database, che resta il burn-in e non genera ingressi.
        self.entry_season: Dict[str, int] = {}
        self.first_season: Optional[int] = None
        #: Stato dei rating degli INCUMBENT al BEGINNING of the day being
        #: processed, taken before any match of that day. The seed of an entry
        #: reads this and nothing else, so it cannot depend on the order of the
        #: matches of the same date nor on results not yet available at kickoff.
        #: Season the snapshot belongs to, and the rule that defines the set.
        self._day_start_state: Dict[str, float] = {}
        self._day_start_season: Optional[int] = None
        #: R(lega, stagione): composizione del campionato, dal calendario.
        #: Se non passata viene ricavata dal database caricato.
        self.season_rosters: Dict[int, set] = {}
        #: Roster passato esplicitamente dal chiamante (backtest su DB
        #: troncati): se None si ricava dal database caricato.
        self._season_rosters_input = season_rosters
        #: I(lega, stagione): le squadre di R che hanno giocato in questa lega
        #: anche nella stagione precedente. E' l'insieme di riferimento del
        #: seed ed e' FISSO per tutta la stagione.
        self.incumbents: Dict[int, tuple] = {}

    def _get_league_files(self) -> List[str]:
        # Risoluzione centralizzata in config: include anche i file il cui nome non
        # deriva dal db_prefix (es. PremierLeague.csv con prefisso 'Premier').
        return get_league_db_files(self.league_name)

    def _is_entry(self, team: str, season: int) -> bool:
        """La squadra ``team`` sta giocando la sua prima partita in lega?

        Ingresso = MAI VISTA (nessuna partita precedente in questa lega) oppure
        DI RITORNO dopo una o piu' stagioni di assenza: nell'ordine di
        produzione, ``season_start_year_of`` della partita corrente meno la
        stagione della sua ultima partita supera 1.

        La prima stagione del database non genera ingressi: e' il burn-in,
        l'unica condizione iniziale che il motore ha sempre avuto, e resta a
        ``DEFAULT_INITIAL_RATING`` come prima della PR #35.
        """
        ultima = self.entry_season.get(team)
        if ultima is None:
            return season > self.first_season
        return season - ultima > 1

    def _incumbent(self, season: int) -> tuple:
        """I(lega, stagione): R(s) ∩ R(s−1), in ordine alfabetico.

        Vuota per la prima stagione del database (nessuna stagione
        precedente): e' il burn-in, che resta a DEFAULT_INITIAL_RATING.
        """
        if season not in self.incumbents:
            roster = self.season_rosters.get(season, set())
            stagioni = sorted(self.season_rosters)
            precedente = [s for s in stagioni if s < season]
            prima = set(self.season_rosters[precedente[-1]]) if precedente else set()
            self.incumbents[season] = tuple(sorted(roster & prima))
        return self.incumbents[season]

    def _snapshot_day_start(self, season: Optional[int] = None) -> None:
        """Fotografa lo stato delle squadre attive PRIMA della giornata.

        ``season`` e' la stagione della giornata che sta per essere processata.
        Il riferimento del seed e' I(lega, stagione) = R(s) ∩ R(s−1): le
        squadre che compongono il campionato in quella stagione e c'erano gia'
        nella stagione precedente. Sono una COMPOSIZIONE DEL CALENDARIO, nota
        prima del via, non un risultato: vedi ``season_rosters_from_matches``.
        Una retrocessa non e' in R(s) e una neo-promossa non e' in R(s−1), per
        costruzione nessuna delle due entra nel riferimento. L'insieme e'
        fisso per tutta la stagione, i rating dentro cambiano giorno per
        giorno: e' per questo che il seed resta indipendente dall'ordine delle
        partite della stessa data.
        """
        if season is None:
            season = self._day_start_season
        self._day_start_season = season
        # Solo gli INCUMBENT della stagione: sono le squadre che fanno parte
        # del campionato e c'erano gia' nella stagione precedente. Una
        # neo-promossa o una retrocessa non ci sono per costruzione, e una
        # squadra che non ha ancora giocato in stagione porta qui il suo
        # rating di fine stagione precedente, senza dover aspettare la sua
        # prima partita. L'insieme e' fisso per tutta la stagione: cambia solo
        # il rating che in esso si legge.
        self._day_start_state = {
            t: self.ratings[t]
            for t in self._incumbent(season)
            if t in self.ratings
        } if season is not None else {}

    def promoted_seed(self, season: Optional[int] = None) -> float:
        """Rating iniziale di una squadra che entra in lega (PR #35).

        ``season`` e' la stagione della partita da prevedere. E' informazione
        di CALENDARIO, nota prima del via, quindi non e' look-ahead: serve
        perche' a fine database l'ultimo giorno processato puo' essere
        l'ultimo della stagione o un giorno qualunque in mezzo, e in questi
        due casi la partita successiva appartiene a una stagione diversa. Se
        None si usa lo snapshot di fine database (inizio della prossima
        giornata ancora da giocare nella stagione appena processata).

        Media dei rating delle squadre INCUMBENT al **inizio della data della
        partita** — cioe' di quelle che compongono il campionato nella stagione
        corrente e c'erano gia' nella stagione precedente, con i rating che
        avevano in quel momento (per chi non ha ancora giocato in stagione
        quello di fine stagione precedente) — piu' ``PROMOTED_SEED_OFFSET``.

        Lo snapshot e' preso una volta per giornata, prima di qualunque
        partita di quella giornata: per questo il seed non dipende dall'ordine
        delle partite della stessa data e non usa risultati che al kickoff non
        erano ancora disponibili. In predizione lo snapshot e' quello di fine
        database, cioe' l'inizio della prossima giornata ancora da giocare:
        stessa regola, stesso codice.

        Se I e' vuota il fallback dichiarato e' ``DEFAULT_INITIAL_RATING``.
        Questo accade solo per la prima stagione del database, che non ha
        stagione precedente: e' il burn-in.
        """
        if season is None:
            stato = self._day_start_state
        else:
            # Le partite ancora da giocare non hanno cambiato nessun rating:
            # `ratings` E' gia' lo stato di inizio della prossima giornata.
            stato = {t: self.ratings[t] for t in self._incumbent(season)
                     if t in self.ratings}
        if not stato:
            return DEFAULT_INITIAL_RATING
        return float(np.mean([stato[t] for t in sorted(stato)])) + PROMOTED_SEED_OFFSET

    def load_and_preprocess_matches(self) -> pd.DataFrame:
        files = self._get_league_files()
        if not files:
            return pd.DataFrame()
        dfs = []
        for f in files:
            try:
                df_tmp = pd.read_csv(f, on_bad_lines="warn", low_memory=False)
                # servono tutte e 4 le colonne usate sotto: un CSV parziale farebbe
                # KeyError su df["Date"]/df["FTR"] a valle
                needed = {"HomeTeam", "AwayTeam", "FTR", "Date"}
                if not df_tmp.empty and needed.issubset(df_tmp.columns):
                    dfs.append(df_tmp)
            except Exception:
                continue
        if not dfs:
            return pd.DataFrame()
        df = pd.concat(dfs, ignore_index=True).copy()
        df = df.dropna(subset=["HomeTeam", "AwayTeam", "FTR"])
        df["HomeClean"] = df["HomeTeam"].apply(clean_name)
        df["AwayClean"] = df["AwayTeam"].apply(clean_name)
        df["Date_Parsed"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
        df = df.dropna(subset=["Date_Parsed"])
        df = df.drop_duplicates(subset=["Date_Parsed", "HomeClean", "AwayClean"], keep="last")
        df = df.sort_values("Date_Parsed").reset_index(drop=True).copy()
        self.matches_df = df
        return df

    def compute_ratings(self) -> Dict[str, float]:
        df = self.load_and_preprocess_matches()
        if df.empty:
            self.is_computed = True
            return self.ratings
        all_teams = set(df["HomeClean"].unique()).union(set(df["AwayClean"].unique()))
        # compute_ratings e' un ricalcolo completo: lo stato degli ingressi
        # riparte da zero come i rating.
        self.entry_season = {}
        self._day_start_state = {}
        self._day_start_season = None
        self.incumbents = {}
        roster = self._season_rosters_input
        if roster:
            self.season_rosters = {int(k): {str(t) for t in v}
                                   for k, v in roster.items()}
        else:
            self.season_rosters = season_rosters_from_matches(df)
        self.first_season = season_start_year_of(df["Date_Parsed"].iloc[0])
        for team in all_teams:
            self.ratings[team] = DEFAULT_INITIAL_RATING
            self.history[team] = []
            self.team_stats[team] = {
                "matches": 0, "wins": 0, "draws": 0, "losses": 0,
                "goals_for": 0, "goals_against": 0,
                "peak_elo": DEFAULT_INITIAL_RATING, "min_elo": DEFAULT_INITIAL_RATING,
            }
        giorno_corrente = None
        for idx, row in df.iterrows():
            h_team = row["HomeClean"]
            a_team = row["AwayClean"]
            ftr = str(row["FTR"]).strip().upper()
            season = season_start_year_of(row["Date_Parsed"])
            # UN solo snapshot per giornata, preso PRIMA di qualunque sua
            # partita: e' lo stato che il seed deve vedere. Le righe sono
            # ordinate per data, quindi il cambio di data e' il momento esatto
            # in cui congelarlo; dentro la giornata non si tocca piu'.
            if pd.Timestamp(row["Date_Parsed"]).normalize() != giorno_corrente:
                giorno_corrente = pd.Timestamp(row["Date_Parsed"]).normalize()
                self._snapshot_day_start(season)
            # Seeding d'ingresso (PR #35). Se due squadre esordiscono nella
            # stessa partita i seed sono applicati in sequenza, in ordine
            # alfabetico di nome: e' l'ordine con cui _entry_records elenca gli
            # ingressi e con cui la variante S3 dell'audit li assegna. Lo
            # snapshot letto e' quello di inizio giornata e non cambia fra le
            # due squadre, quindi l'ordine serve solo a rendere deterministico
            # il risultato float, non a scegliere chi vede chi.
            for team in sorted((h_team, a_team)):
                if self._is_entry(team, season):
                    self.ratings[team] = self.promoted_seed()
            for team in (h_team, a_team):
                self.entry_season[team] = season
            fthg = row.get("FTHG")
            ftag = row.get("FTAG")
            try:
                fthg = int(fthg) if pd.notna(fthg) else 0
                ftag = int(ftag) if pd.notna(ftag) else 0
            except Exception:
                fthg, ftag = 0, 0

            r_h = self.ratings.get(h_team, DEFAULT_INITIAL_RATING)
            r_a = self.ratings.get(a_team, DEFAULT_INITIAL_RATING)

            if ftr == "H" or fthg > ftag:
                s_h, s_a = 1.0, 0.0
            elif ftr == "A" or ftag > fthg:
                s_h, s_a = 0.0, 1.0
            else:
                s_h, s_a = 0.5, 0.5

            margin = abs(fthg - ftag)
            margin_mult = calculate_goal_margin_multiplier(margin)

            dr = r_h + self.home_adv - r_a
            expected_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
            expected_a = 1.0 - expected_h

            k_eff = self.base_k * margin_mult
            delta_h = k_eff * (s_h - expected_h)
            delta_a = k_eff * (s_a - expected_a)
            new_r_h = r_h + delta_h
            new_r_a = r_a + delta_a
            self.ratings[h_team] = new_r_h
            self.ratings[a_team] = new_r_a

            st_h = self.team_stats[h_team]
            st_a = self.team_stats[a_team]
            st_h["matches"] += 1
            st_a["matches"] += 1
            st_h["goals_for"] += fthg
            st_h["goals_against"] += ftag
            st_a["goals_for"] += ftag
            st_a["goals_against"] += fthg
            if s_h == 1.0:
                st_h["wins"] += 1
                st_a["losses"] += 1
            elif s_h == 0.0:
                st_h["losses"] += 1
                st_a["wins"] += 1
            else:
                st_h["draws"] += 1
                st_a["draws"] += 1
            st_h["peak_elo"] = max(st_h["peak_elo"], new_r_h)
            st_h["min_elo"] = min(st_h["min_elo"], new_r_h)
            st_a["peak_elo"] = max(st_a["peak_elo"], new_r_a)
            st_a["min_elo"] = min(st_a["min_elo"], new_r_a)

            date_val = row["Date_Parsed"]
            self.history[h_team].append({
                "date": date_val, "opponent": a_team, "is_home": True,
                "score": f"{fthg}-{ftag}",
                "result": "V" if s_h == 1.0 else ("P" if s_h == 0.0 else "X"),
                "elo_before": r_h, "elo_after": new_r_h, "delta": delta_h
            })
            self.history[a_team].append({
                "date": date_val, "opponent": h_team, "is_home": False,
                "score": f"{ftag}-{fthg}",
                "result": "V" if s_a == 1.0 else ("P" if s_a == 0.0 else "X"),
                "elo_before": r_a, "elo_after": new_r_a, "delta": delta_a
            })
        # Fine database: lo snapshot diventa lo stato di inizio della PROSSIMA
        # giornata, cioe' quello che predict_elo_probs usa per una squadra che
        # non ha ancora rating in lega. Stessa definizione del ramo storico.
        self._snapshot_day_start()
        self.is_computed = True
        return self.ratings

    def get_leaderboard(self) -> pd.DataFrame:
        if not self.is_computed:
            self.compute_ratings()
        rows = []
        for team, rating in self.ratings.items():
            stats = self.team_stats.get(team, {})
            hist = self.history.get(team, [])
            last_5 = hist[-5:] if hist else []
            last_5_delta = sum(m["delta"] for m in last_5) if last_5 else 0.0
            last_5_form = "".join([m["result"] for m in last_5]) if last_5 else "—"
            rows.append({
                "Squadra": team, "Elo Rating": round(rating, 1),
                "PG": stats.get("matches", 0), "V": stats.get("wins", 0),
                "N": stats.get("draws", 0), "P": stats.get("losses", 0),
                "GF": stats.get("goals_for", 0), "GS": stats.get("goals_against", 0),
                "DR": stats.get("goals_for", 0) - stats.get("goals_against", 0),
                "Delta 5G": round(last_5_delta, 1), "Forma 5G": last_5_form,
                "Peak Elo": round(stats.get("peak_elo", rating), 1),
            })
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("Elo Rating", ascending=False).reset_index(drop=True)
            df.index = df.index + 1
            df.index.name = "Rank"
        return df


_ELO_ENGINES_CACHE: Dict[str, EloEngine] = {}
# Etá (monotonic) di costruzione per lega: la cache senza scadenza faceva
# girare, in una sessione lunga, il veto di disaccordo del Top Mix su un Elo
# vecchio contro un Poisson rinfrescato ogni 3600 s (get_league_engine).
# allineare le due finestre (audit/margini_migliorabili_topmix.md  §6.1).
_ELO_ENGINES_STAMP: Dict[str, float] = {}
ELO_ENGINE_TTL_SECONDS = 3600


def get_elo_engine(league_name: str, ttl_seconds: float = ELO_ENGINE_TTL_SECONDS) -> EloEngine:
    engine = _ELO_ENGINES_CACHE.get(league_name)
    if engine is not None:
        eta = time.monotonic() - _ELO_ENGINES_STAMP.get(league_name, 0.0)
        if eta < ttl_seconds:
            return engine
    engine = EloEngine(league_name)
    engine.compute_ratings()
    _ELO_ENGINES_CACHE[league_name] = engine
    _ELO_ENGINES_STAMP[league_name] = time.monotonic()
    return engine


def get_current_elo(league_name: str) -> Dict[str, float]:
    engine = get_elo_engine(league_name)
    return {team: round(score, 1) for team, score in engine.ratings.items()}


def get_elo_leaderboard(league_name: str) -> pd.DataFrame:
    engine = get_elo_engine(league_name)
    return engine.get_leaderboard()


def elo_probs_from_ratings(r_h: float, r_a: float, home_adv: float) -> dict:
    """Conversione Elo -> 1X2: funzione PURA, nessuno stato, nessuna cache.

    Estratta dal corpo di ``predict_elo_probs`` senza alcun cambio numerico:
    stesse operazioni, stesso ordine, stessi arrotondamenti, stesse chiavi.

    Formula, nell'ordine esatto in cui viene calcolata:

    1. differenza di rating, home advantage incluso::

           dr = r_h + home_adv - r_a

    2. punteggio atteso della squadra di casa (logistica Elo in base 10 con
       scala 400) e, per complemento, quello della squadra ospite::

           e_h = 1 / (1 + 10 ** (-dr / 400))
           e_a = 1 - e_h

    3. probabilita' di pareggio: campana gaussiana centrata sull'equilibrio
       (dr = 0), ampiezza 0.27, scala 320, troncata nell'intervallo
       [0.06, 0.34]::

           p_draw = 0.27 * exp(-((dr / 320) ** 2))
           p_draw = max(0.06, min(0.34, p_draw))

    4. la massa residua ``1 - p_draw`` viene ripartita fra casa e trasferta
       in proporzione ai punteggi attesi::

           p_home = (1 - p_draw) * e_h
           p_away = (1 - p_draw) * e_a

    5. normalizzazione sulla somma dei tre esiti e arrotondamento::

           total = p_home + p_draw + p_away
           "1" = round(p_home / total, 4)
           "X" = round(p_draw / total, 4)
           "2" = round(p_away / total, 4)

       (``total`` vale 1 per costruzione, perche' ``e_h + e_a = 1``; la
       divisione resta nel codice per non alterare l'aritmetica in virgola
       mobile preesistente.)

    Chiavi del dict restituito: ``"1"``, ``"X"``, ``"2"`` (terna 1X2
    arrotondata a 4 decimali), ``elo_home`` / ``elo_away`` (rating in
    ingresso, 1 decimale), ``elo_diff`` (``dr``, 1 decimale), ``home_adv``
    (il valore ricevuto, non arrotondato), ``expected_score_home`` /
    ``expected_score_away`` (``e_h`` / ``e_a``, 4 decimali).

    :param r_h: rating Elo della squadra di casa.
    :param r_a: rating Elo della squadra in trasferta.
    :param home_adv: vantaggio casalingo in punti Elo (per lega in
        ``config.LEAGUE_HOME_ADVANTAGE``, default ``HOME_ADVANTAGE``).
    """
    dr = r_h + home_adv - r_a
    e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
    e_a = 1.0 - e_h
    p_draw = 0.27 * math.exp(-((dr / 320.0) ** 2))
    p_draw = max(0.06, min(0.34, p_draw))
    p_home = (1.0 - p_draw) * e_h
    p_away = (1.0 - p_draw) * e_a
    total = p_home + p_draw + p_away
    return {
        "1": round(p_home / total, 4),
        "X": round(p_draw / total, 4),
        "2": round(p_away / total, 4),
        "elo_home": round(r_h, 1), "elo_away": round(r_a, 1),
        "elo_diff": round(dr, 1), "home_adv": home_adv,
        "expected_score_home": round(e_h, 4), "expected_score_away": round(e_a, 4),
    }


def predict_elo_probs(home_team: str, away_team: str, league_name: str,
                      season: Optional[int] = None) -> dict:
    engine = get_elo_engine(league_name)
    h_cl = clean_name(home_team)
    a_cl = clean_name(away_team)
    r_h = engine.ratings.get(h_cl)
    r_a = engine.ratings.get(a_cl)
    # Squadra senza rating in questa lega = neopromossa alla prima partita e non
    # ancora presente nei CSV: si applica lo stesso seeding di compute_ratings
    # (media degli incumbent - 100), non DEFAULT_INITIAL_RATING. `season` e' la
    # stagione della partita da prevedere (dato di calendario, noto prima del
    # via): senza di lei l'ultimo giorno del database non direbbe a quale
    # stagione appartiene la partita successiva.
    if r_h is None:
        r_h = engine.promoted_seed(season)
    if r_a is None:
        r_a = engine.promoted_seed(season)
    return elo_probs_from_ratings(r_h, r_a, engine.home_adv)


def get_team_elo_history(team_name: str, league_name: str) -> pd.DataFrame:
    engine = get_elo_engine(league_name)
    t_cl = clean_name(team_name)
    hist = engine.history.get(t_cl, [])
    if not hist:
        return pd.DataFrame()
    return pd.DataFrame(hist)
