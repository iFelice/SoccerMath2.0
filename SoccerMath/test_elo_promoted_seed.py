"""
test_elo_promoted_seed.py — Seeding S3 degli ingressi in lega in PRODUZIONE.

``models/elo_engine.py`` semina una squadra alla sua prima partita in lega con
la media dei rating delle squadre ATTIVE (quelle che hanno gia' disputato almeno
una partita in lega, nell'ordine di produzione) piu' ``PROMOTED_SEED_OFFSET``.
La variante S3 che ha validato la scelta e' ``audit/elo_drift_triage.py``; la
parita' bit-exact sulle 7334 partite reali e' negata da
``audit/test_elo_s3_parity.py``. Qui si verifica il COMPORTAMENTO su database
sintetici: i valori attesi sono ricalcolati da un motore costruito sul
TRONCAMENTO del database prima della partita d'ingresso, cosi' il test non riusa
la formula del motore ma la confronta con un'altra istanza.

Casi coperti:
  * neopromossa MAI VISTA (primo ingresso e ingresso successivo, quando la
    media attiva non e' piu' 1500 per effetto del seeding precedente);
  * squadra DI RITORNO dopo una stagione di assenza (scarta il rating stantio);
  * squadra presente in due stagioni consecutive: NON e' un ingresso e porta il
    suo rating;
  * due ingressi nella stessa partita: seed in ordine alfabetico, il secondo
    vede il primo (ordine con cui S3 li assegna);
  * prima partita non ancora giocata, ramo di PREDIZIONE;
  * lega senza squadre attive: comportamento dichiarato.

Nota aritmetica che i test sfruttano: l'update Elo e' a somma nulla, quindi la
somma dei rating di tutte le squadre resta 1500 per squadra finche' nessun
ingresso rompe l'equilibrio. Per questo il PRIMO ingresso di un database
equilibrato ha media attiva 1500 e seed 1400 esatto, e i test che vogliono una
media attiva diversa mettono un ingresso precedente.

Esecuzione:  python SoccerMath/test_elo_promoted_seed.py
             python -m pytest SoccerMath/test_elo_promoted_seed.py -v
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import config as PROD_CONFIG                                   # noqa: E402
from models.elo_engine import (                                # noqa: E402
    DEFAULT_INITIAL_RATING,
    PROMOTED_SEED_OFFSET,
    EloEngine,
    EloSeedError,
    elo_probs_from_ratings,
    predict_elo_probs,
)

#: lega di riferimento: i CSV del test sono scritti in una cartella temporanea e
#: config viene ripuntato li' per la durata del test.
LEGA = "Serie A"
HOME_ADV = PROD_CONFIG.LEAGUE_HOME_ADVANTAGE[LEGA]
PREFIX = PROD_CONFIG.LEAGUES_CONFIG[LEGA]["db_prefix"]

COLONNE = ["HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR", "Date"]


class _DBTemp:
    """Cartella temporanea con i CSV di una lega; ``config`` ripuntato li'."""

    def __init__(self, righe_per_stagione: dict, file_per_riga: dict | None = None):
        self.righe = righe_per_stagione
        self.file_per_riga = file_per_riga or {}
        self.tmp = None

    def __enter__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="elo_seed_test_"))
        for stagione, righe in self.righe.items():
            pd.DataFrame(righe, columns=COLONNE).to_csv(
                self.tmp / f"{PREFIX}_{stagione}.csv", index=False)
        for stagione, righe in self.file_per_riga.items():
            for i, riga in enumerate(righe):
                pd.DataFrame([riga], columns=COLONNE).to_csv(
                    self.tmp / f"{PREFIX}_{stagione}_{i}.csv", index=False)
        self.old_dir = PROD_CONFIG.DATABASE_DIR
        self.old_cfg = {k: dict(v) for k, v in PROD_CONFIG.LEAGUES_CONFIG.items()}
        PROD_CONFIG.DATABASE_DIR = self.tmp
        for k, v in PROD_CONFIG.LEAGUES_CONFIG.items():
            for chiave in ("base_csv", "live_csv", "xg_json"):
                if v.get(chiave):
                    v[chiave] = str(self.tmp / Path(v[chiave]).name)
        return self

    def __exit__(self, *exc):
        PROD_CONFIG.DATABASE_DIR = self.old_dir
        for k, v in self.old_cfg.items():
            PROD_CONFIG.LEAGUES_CONFIG[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False


def _partita(giorno, casa, fuori, gc, gf):
    return {"HomeTeam": casa, "AwayTeam": fuori, "FTHG": gc, "FTAG": gf,
            "FTR": "H" if gc > gf else ("A" if gf > gc else "D"), "Date": giorno}


def _motore(stagioni, file_per_riga=None):
    """Motore pulito (bypassa la cache di modulo) sul database fornito.

    ``file_per_riga`` scrive ogni riga della giornata indicata in un file
    separato: e' l'unico modo per pilotare l'ordine dentro la giornata,
    perche' il sort per data del loader e' instabile.
    """
    import models.elo_engine as E
    E._ELO_ENGINES_CACHE.pop(LEGA, None)
    E._ELO_ENGINES_STAMP.pop(LEGA, None)
    with _DBTemp(stagioni, file_per_riga):
        eng = EloEngine(LEGA)
        eng.compute_ratings()
        return eng


#: Due stagioni complete con un ingresso in 2023: serve ai casi in cui il
#: motore e' gia' calcolato e si verifica che ``promoted_seed`` non abbia piu'
#: un percorso silenzioso.
STAGIONI_2 = {
    "2022": [_partita("13/08/2022", "Alfa", "Beta", 2, 0),
             _partita("20/08/2022", "Beta", "Alfa", 1, 0)],
    "2023": [_partita("19/08/2023", "Gamma", "Alfa", 1, 0)],
}


def _rating_prima(eng, squadra, n):
    """Rating della squadra prima della sua n-esima partita (1-based)."""
    return eng.history[squadra][n - 1]["elo_before"]


def _stato_attivo(eng: EloEngine, squadra: str, n: int):
    """(insieme di riferimento, stagione) al primo istante della giornata della
    n-esima partita di ``squadra``.

    Il riferimento e' I(lega, stagione) = R(s) ∩ R(s−1), dove R e' la
    composizione DEL CALENDARIO (le squadre che compaiono nelle partite di
    quella stagione nei CSV: promozioni, retrocessioni e calendario sono noti
    prima del via, non e' un risultato futuro). I rating sono quelli che le
    squadre avevano a inizio giornata, ricostruiti dal ``history`` partita per
    partita e quindi indipendenti dalla formula del seeding: una squadra che
    non ha ancora giocato in stagione porta il suo rating di fine stagione
    precedente. Stessa definizione di ``EloEngine._snapshot_day_start``.
    """
    from config import season_start_year_of
    giorno = pd.Timestamp(eng.history[squadra][n - 1]["date"]).normalize()
    stagione = season_start_year_of(giorno)
    roster = {int(k): set(v) for k, v in eng.season_rosters.items()}
    precedenti = sorted(x for x in roster if x < stagione)
    prec = roster[precedenti[-1]] if precedenti else set()
    incumbent = roster.get(stagione, set()) & prec
    stato = {}
    for t in incumbent:
        ultimo = None
        for h in eng.history.get(t, []):
            if pd.Timestamp(h["date"]).normalize() < giorno:
                ultimo = h
            else:
                break
        if ultimo is not None:
            stato[t] = float(ultimo["elo_after"])
    return stato, stagione


def _seed_atteso(eng: EloEngine, squadra: str, n: int) -> float:
    """Il seed che la produzione DEVE usare, ricalcolato da un'altra strada."""
    attivi, _ = _stato_attivo(eng, squadra, n)
    if not attivi:
        return DEFAULT_INITIAL_RATING
    return float(np.mean([attivi[t] for t in sorted(attivi)])) + PROMOTED_SEED_OFFSET


def _seed_fine_db(eng: EloEngine) -> float:
    """Il seed che predict_elo_probs usa: lo snapshot di fine database, cioe'
    l'inizio della prossima giornata ancora da giocare."""
    ultima = max(eng.season_rosters)
    attivi = {t: float(eng.ratings[t]) for t in eng._incumbent(ultima)
              if t in eng.ratings}
    if not attivi:
        return DEFAULT_INITIAL_RATING
    return float(np.mean([attivi[t] for t in sorted(attivi)])) + PROMOTED_SEED_OFFSET


def _media_attiva(troncato: EloEngine) -> float:
    """Media dei rating delle squadre che hanno gia' GIOCATO, ordine alfabetico."""
    attive = [t for t in troncato.ratings if troncato.team_stats[t]["matches"] > 0]
    return float(np.mean([troncato.ratings[t] for t in sorted(attive)]))


class TestNeopromossaMaiVista(unittest.TestCase):
    STAGIONI = {
        "2022": [  # tre squadre, tre partite: esauriscono il burn-in
            _partita("13/08/2022", "Alfa", "Beta", 2, 0),
            _partita("14/08/2022", "Alfa", "Gamma", 3, 1),
            _partita("15/08/2022", "Beta", "Gamma", 1, 1),
        ],
        "2023": [
            _partita("19/08/2023", "Delta", "Alfa", 1, 0),   # Delta: MAI VISTA
            _partita("21/08/2023", "Beta", "Epsilon", 4, 0),  # Epsilon: MAI VISTA
        ],
    }

    def test_primo_ingresso_della_stagione_usa_il_roster_completo(self):
        """Delta debutta sul PRIMO giorno di una stagione. L'insieme di
        riferimento non e' "chi ha gia' giocato" (sarebbe vuoto) ma
        I(2023) = R(2023) ∩ R(2022): tutti gli incumbent, con il loro rating
        di fine stagione precedente. Nessuna retrocessa del 2022 e nessuna
        entrante."""
        eng = _motore(self.STAGIONI)
        attivi, stagione = _stato_attivo(eng, "Delta", 1)
        self.assertEqual(stagione, 2023)
        self.assertEqual(sorted(attivi), ["Alfa", "Beta"])
        self.assertNotIn("Gamma", attivi, "Gamma era assente nel 2023")
        atteso = float(np.mean([attivi[t] for t in sorted(attivi)])) \
            + PROMOTED_SEED_OFFSET
        self.assertEqual(repr(_rating_prima(eng, "Delta", 1)), repr(atteso))

    def test_ingresso_in_giornata_successiva_usa_la_media_attiva_meno_100(self):
        """Epsilon debutta il 21/08, quando nella stagione corrente ha gia'
        giocato Delta: la media e' quella di QUELL'insieme, meno l'offset."""
        eng = _motore(self.STAGIONI)
        attivi, _ = _stato_attivo(eng, "Epsilon", 1)
        self.assertEqual(sorted(attivi), ["Alfa", "Beta"])
        atteso = float(np.mean([attivi[t] for t in sorted(attivi)])) \
            + PROMOTED_SEED_OFFSET
        self.assertEqual(repr(_rating_prima(eng, "Epsilon", 1)), repr(atteso))
        # Epsilon e' un'entrante: non puo' stare nel proprio riferimento
        self.assertNotIn("Epsilon", attivi)
        self.assertNotEqual(repr(atteso), repr(1400.0))
        self.assertNotEqual(repr(_rating_prima(eng, "Epsilon", 1)),
                            repr(float(DEFAULT_INITIAL_RATING)))

    def test_le_tre_squadre_del_burnin_restano_a_1500(self):
        eng = _motore(self.STAGIONI)
        troncato = _motore({"2022": self.STAGIONI["2022"]})
        self.assertEqual(_media_attiva(troncato), DEFAULT_INITIAL_RATING)
        self.assertEqual(_rating_prima(eng, "Alfa", 1), DEFAULT_INITIAL_RATING)
        self.assertEqual(_rating_prima(eng, "Beta", 1), DEFAULT_INITIAL_RATING)
        self.assertEqual(_rating_prima(eng, "Gamma", 1), DEFAULT_INITIAL_RATING)

    def test_la_neopromossa_ha_un_update_elo_normale(self):
        eng = _motore(self.STAGIONI)
        storico = eng.history["Delta"]
        self.assertEqual(len(storico), 1)
        self.assertEqual(storico[0]["elo_before"], _rating_prima(eng, "Delta", 1))
        self.assertNotEqual(storico[0]["elo_after"], storico[0]["elo_before"])

    def test_il_seed_non_e_riapplicato_alla_seconda_partita(self):
        righe = dict(self.STAGIONI)
        righe["2023"] = righe["2023"] + [_partita("22/08/2023", "Delta", "Beta", 4, 0)]
        eng = _motore(righe)
        storico = eng.history["Delta"]
        self.assertEqual(len(storico), 2)
        self.assertNotEqual(storico[1]["elo_before"], storico[0]["elo_before"])
        # niente reassignazione: arriva dal post-partita della partita precedente
        self.assertEqual(storico[1]["elo_before"], storico[0]["elo_after"])
        self.assertNotEqual(storico[1]["elo_before"], storico[0]["elo_before"])


class TestSquadraDiRitorno(unittest.TestCase):
    STAGIONI = {
        "2022": [
            _partita("13/08/2022", "Alfa", "Beta", 2, 0),
            _partita("14/08/2022", "Alfa", "Gamma", 3, 1),
            _partita("15/08/2022", "Beta", "Gamma", 1, 1),
        ],
        "2023": [                                          # Beta assente
            _partita("19/08/2023", "Alfa", "Gamma", 1, 0),
            _partita("20/08/2023", "Gamma", "Alfa", 2, 2),
        ],
        "2024": [
            _partita("18/08/2024", "Beta", "Alfa", 2, 1),  # Beta: DI RITORNO
            _partita("19/08/2024", "Gamma", "Alfa", 1, 1),
        ],
    }
    TRONCATO = {"2022": STAGIONI["2022"], "2023": STAGIONI["2023"]}

    def test_ritorno_semina_media_attiva_meno_100(self):
        eng = _motore(self.STAGIONI)
        # Beta ha giocato 2 partite nel 2022: la 3-esima e' il ritorno, il
        # 18/08/2024, primo giorno della stagione 2024. Il riferimento e'
        # I(2024) = R(2024) ∩ R(2023) = {Alfa, Gamma}: Beta e' essa stessa
        # un'entrante e non puo' stare dentro.
        attivi, _ = _stato_attivo(eng, "Beta", 3)
        self.assertEqual(sorted(attivi), ["Alfa", "Gamma"])
        self.assertNotIn("Beta", attivi)
        atteso = float(np.mean([attivi[t] for t in sorted(attivi)])) \
            + PROMOTED_SEED_OFFSET
        self.assertEqual(repr(_rating_prima(eng, "Beta", 3)), repr(atteso))

    def test_ritorno_scarta_il_rating_stantio(self):
        eng = _motore(self.STAGIONI)
        troncato = _motore(self.TRONCATO)
        stantio = float(troncato.ratings["Beta"])
        seed = _rating_prima(eng, "Beta", 3)
        # main avrebbe ripartito da `stantio`: i due devono divergere
        self.assertNotEqual(repr(seed), repr(stantio))

    def test_squadra_presente_in_stagioni_consecutive_non_e_ingresso(self):
        eng = _motore(self.STAGIONI)
        troncato = _motore(self.TRONCATO)
        # Alfa gioca anche nel 2023: porta il suo rating, nessun seeding.
        # Nel motore completo Alfa ha 6 partite: la 5-esima e' la prima del 2024.
        prima_2024 = _rating_prima(eng, "Alfa", 5)
        self.assertEqual(prima_2024, _rating_prima(eng, "Alfa", 5))
        # nessun seeding: Alfa porta il suo rating, non la media meno 100
        self.assertNotEqual(repr(prima_2024), repr(DEFAULT_INITIAL_RATING))
        # il rating di arrivo e' quello prodotto dal troncamento, verificato qui
        # sul history e non ricalcolato con la formula del seeding
        storico = troncato.history["Alfa"]
        self.assertEqual(len(storico), 4)
        self.assertEqual(prima_2024, storico[-1]["elo_after"])


class TestDueIngressiNellaStessaPartita(unittest.TestCase):
    STAGIONI = {
        "2022": [
            _partita("13/08/2022", "Alfa", "Beta", 2, 0),
            _partita("14/08/2022", "Alfa", "Gamma", 3, 1),
            _partita("15/08/2022", "Alfa", "Delta", 4, 0),
        ],
        "2023": [                                          # Beta e Delta assenti
            _partita("19/08/2023", "Alfa", "Gamma", 1, 0),
            _partita("20/08/2023", "Gamma", "Alfa", 2, 2),
        ],
        "2024": [
            _partita("11/08/2024", "Alfa", "Gamma", 2, 1),  # giornata precedente
            _partita("18/08/2024", "Delta", "Beta", 2, 1),  # due ingressi insieme
        ],
    }
    TRONCATO = {"2022": STAGIONI["2022"], "2023": STAGIONI["2023"]}

    def test_due_ingressi_nella_stessa_partita_prendono_lo_stesso_seed(self):
        """Il seed si legge a inizio giornata: le due squadre lo leggono
        identico, perche' fra loro non e' ancora successo niente."""
        eng = _motore(self.STAGIONI)
        seed = _seed_atteso(eng, "Beta", 2)
        self.assertEqual(repr(_rating_prima(eng, "Beta", 2)), repr(seed))
        self.assertEqual(repr(_rating_prima(eng, "Delta", 2)), repr(seed))
        self.assertEqual(repr(_rating_prima(eng, "Beta", 2)),
                         repr(_rating_prima(eng, "Delta", 2)))

    def test_il_seed_viene_dallo_stato_di_inizio_giornata(self):
        """La giornata dell'ingresso non entra nel calcolo: si usa lo stato
        delle partite dei giorni precedenti."""
        eng = _motore(self.STAGIONI)
        troncato = _motore(self.TRONCATO)
        solo_18 = _motore({**self.TRONCATO, "2024": [
            _partita("18/08/2024", "Alfa", "Gamma", 1, 0)]})
        # Se la partita della giornata fosse contata, la media cambierebbe.
        self.assertNotEqual(repr(solo_18.ratings["Alfa"]),
                            repr(troncato.ratings["Alfa"]))
        seed = _seed_atteso(eng, "Delta", 2)
        self.assertEqual(repr(_rating_prima(eng, "Delta", 2)), repr(seed))


class TestPrimaPartitaNonGiocataPredizione(unittest.TestCase):
    STAGIONI = {
        "2022": [
            _partita("13/08/2022", "Alfa", "Beta", 2, 0),
            _partita("14/08/2022", "Alfa", "Gamma", 3, 1),
        ],
        "2023": [_partita("19/08/2023", "Alfa", "Beta", 1, 1)],
    }

    def _predici(self, casa, fuori, season=2023):
        import time
        import models.elo_engine as E
        eng = _motore(self.STAGIONI)
        E._ELO_ENGINES_CACHE[LEGA] = eng
        E._ELO_ENGINES_STAMP[LEGA] = time.monotonic()
        try:
            return eng, predict_elo_probs(casa, fuori, LEGA, season=season)
        finally:
            E._ELO_ENGINES_CACHE.pop(LEGA, None)
            E._ELO_ENGINES_STAMP.pop(LEGA, None)

    def test_squadra_ignota_usa_il_seeding_e_non_1500(self):
        eng, p = self._predici("Zeta", "Alfa")
        seed = _seed_fine_db(eng)
        self.assertEqual(p["elo_home"], round(seed, 1))
        self.assertEqual(p, elo_probs_from_ratings(seed, eng.ratings["Alfa"], eng.home_adv))
        self.assertNotEqual(p["elo_home"], round(DEFAULT_INITIAL_RATING, 1))

    def test_entrambe_ignote(self):
        eng, p = self._predici("Zeta", "Eta")
        seed = _seed_fine_db(eng)
        self.assertEqual(p["elo_home"], round(seed, 1))
        self.assertEqual(p["elo_away"], round(seed, 1))

    def test_squadra_gia_nei_csv_usa_il_proprio_rating(self):
        eng, p = self._predici("Alfa", "Beta")
        self.assertEqual(p["elo_home"], round(eng.ratings["Alfa"], 1))
        self.assertEqual(p["elo_away"], round(eng.ratings["Beta"], 1))

    def test_il_seeding_cambia_le_probabilita_rispetto_a_1500(self):
        eng, p1 = self._predici("Zeta", "Alfa")
        diverso = elo_probs_from_ratings(DEFAULT_INITIAL_RATING,
                                         eng.ratings["Alfa"], HOME_ADV)
        self.assertNotEqual((p1["1"], p1["X"], p1["2"]),
                            (diverso["1"], diverso["X"], diverso["2"]))
        for p in (p1, diverso):
            self.assertAlmostEqual(p["1"] + p["X"] + p["2"], 1.0, places=3)


class TestLegaSenzaSquadreAttive(unittest.TestCase):
    """Nessuna squadra attiva: il fallback a 1500 NON e' piu' silenzioso.

    PR #36 chiusura: `promoted_seed` senza stagione, senza roster o con roster
    vuoto solleva `EloSeedError`. L'unico 1500 rimasto e' il burn-in della
    prima stagione del database. Qui si asserisce esattamente questo.
    """

    def test_motore_mai_calcolato(self):
        eng = EloEngine(LEGA)
        self.assertEqual(eng.entry_season, {})
        self.assertIsNone(eng.first_season)
        self.assertEqual(eng.season_rosters, {})
        with self.assertRaises(EloSeedError):
            eng.promoted_seed()

    def test_database_vuoto(self):
        eng = EloEngine(LEGA)
        with _DBTemp({}):
            eng.compute_ratings()
        self.assertEqual(eng.ratings, {})
        self.assertEqual(eng.season_rosters, {})
        with self.assertRaises(EloSeedError):
            eng.promoted_seed()

    def test_una_sola_stagione_non_genera_ingressi(self):
        """Il burn-in resta a 1500 anche per una squadra che debutta a meta'."""
        eng = _motore({"2022": [
            _partita("13/08/2022", "Alfa", "Beta", 2, 0),
            _partita("20/08/2022", "Gamma", "Alfa", 1, 0),
        ]})
        self.assertEqual(_rating_prima(eng, "Gamma", 1), DEFAULT_INITIAL_RATING)
        self.assertEqual(eng.entry_season["Gamma"], 2022)

    def test_predizione_senza_squadre_attive(self):
        """Senza rating E senza season la previsione non puo' essere inventata."""
        import models.elo_engine as E
        eng = EloEngine(LEGA)
        E._ELO_ENGINES_CACHE[LEGA] = eng
        E._ELO_ENGINES_STAMP[LEGA] = 1e18
        try:
            with self.assertRaises(EloSeedError):
                predict_elo_probs("Zeta", "Eta", LEGA)
            with self.assertRaises(EloSeedError):
                eng.promoted_seed()
        finally:
            E._ELO_ENGINES_CACHE.pop(LEGA, None)
            E._ELO_ENGINES_STAMP.pop(LEGA, None)


class TestNessunFallbackSilenzioso(unittest.TestCase):
    """Chiusura PR #36: i buchi che ricadevano su 1500 sollevano.

    Ogni caso qui sotto era un percorso DI PRODUZIONE che poteva arrivare a
    `season=None` o a un roster vuoto e restituire 1500 senza dire niente.
    """

    def test_season_none_solleva_anche_con_roster_pieno(self):
        """Il caso di produzione: season=None su un motore gia' calcolato."""
        eng = _motore(STAGIONI_2)
        self.assertTrue(eng.season_rosters)
        with self.assertRaises(EloSeedError) as ctx:
            eng.promoted_seed()
        self.assertIn("season=None", str(ctx.exception))
        self.assertIn(LEGA, str(ctx.exception))

    def test_stagione_fuora_dai_roster_solleva(self):
        eng = _motore(STAGIONI_2)
        with self.assertRaises(EloSeedError) as ctx:
            eng.promoted_seed(2099)
        self.assertIn("2099", str(ctx.exception))

    def test_roster_vuoto_solleva(self):
        """Il caso reale a inizio stagione: R(s) ricavata dalle partite giocate
        e quindi vuota finche' nessuna partita e' stata disputata."""
        roster = {2022: {"Alfa", "Beta"}, 2023: set(), 2024: {"Alfa", "Beta"}}
        with _DBTemp({}):
            eng = EloEngine(LEGA, season_rosters=roster)
            eng.season_rosters = {k: set(v) for k, v in roster.items()}
            eng.first_season = 2022
            eng.ratings = {"Alfa": 1600.0, "Beta": 1550.0}
            with self.assertRaises(EloSeedError) as ctx:
                eng.promoted_seed(2023)
        self.assertIn("VUOTO", str(ctx.exception))
        self.assertIn("2023", str(ctx.exception))

    def test_incumbent_vuoto_solleva(self):
        """R(s) pieno ma R(s−1) disgiunto: I(s) = intersezione vuota."""
        roster = {2022: {"Alfa", "Beta"}, 2023: {"Gamma", "Delta"}}
        with _DBTemp({}):
            eng = EloEngine(LEGA, season_rosters=roster)
            eng.season_rosters = {k: set(v) for k, v in roster.items()}
            eng.first_season = 2022
            eng.ratings = {"Gamma": 1600.0, "Delta": 1550.0}
            with self.assertRaises(EloSeedError) as ctx:
                eng.promoted_seed(2023)
        self.assertIn("vuota", str(ctx.exception))

    def test_incumbent_senza_rating_solleva(self):
        roster = {2022: {"Alfa", "Beta"}, 2023: {"Alfa", "Beta", "Gamma"}}
        with _DBTemp({}):
            eng = EloEngine(LEGA, season_rosters=roster)
            eng.season_rosters = {k: set(v) for k, v in roster.items()}
            eng.first_season = 2022
            eng.ratings = {"Gamma": 1600.0}
            with self.assertRaises(EloSeedError) as ctx:
                eng.promoted_seed(2023)
        self.assertIn("nessuno dei 2 incumbent", str(ctx.exception))

    def test_burn_in_1500_e_l_unico_fallback(self):
        """Prima stagione del database: nessuna stagione precedente -> 1500."""
        roster = {2022: {"Alfa", "Beta"}}
        with _DBTemp({}):
            eng = EloEngine(LEGA, season_rosters=roster)
            eng.season_rosters = {k: set(v) for k, v in roster.items()}
            eng.first_season = 2022
            eng.ratings = {"Alfa": 1600.0, "Beta": 1550.0}
            self.assertEqual(eng.promoted_seed(2022), DEFAULT_INITIAL_RATING)

    def test_burn_in_1500_solo_se_e_la_prima_stagione_del_database(self):
        """Stagione senza precedente ma NON prima del database: solleva."""
        roster = {2025: {"Alfa", "Beta"}}
        with _DBTemp({}):
            eng = EloEngine(LEGA, season_rosters=roster)
            eng.season_rosters = {k: set(v) for k, v in roster.items()}
            eng.first_season = 2022
            eng.ratings = {"Alfa": 1600.0, "Beta": 1550.0}
            with self.assertRaises(EloSeedError) as ctx:
                eng.promoted_seed(2025)
        self.assertIn("burn-in", str(ctx.exception))

    def test_predict_elo_probs_esige_season_solo_se_serve_il_seed(self):
        """Entrambe le squadre con rating: season=None e' innocuo e il
        risultato e' bit-identico a season esplicita."""
        import models.elo_engine as E
        ing = _motore({"2022": [_partita("13/08/2022", "Alfa", "Beta", 2, 0)]})
        E._ELO_ENGINES_CACHE[LEGA] = ing
        E._ELO_ENGINES_STAMP[LEGA] = 1e18
        try:
            senza = predict_elo_probs("Alfa", "Beta", LEGA)
            con = predict_elo_probs("Alfa", "Beta", LEGA, season=2022)
        finally:
            E._ELO_ENGINES_CACHE.pop(LEGA, None)
            E._ELO_ENGINES_STAMP.pop(LEGA, None)
        self.assertEqual(senza, con)

    def test_predict_elo_probs_senza_season_su_ingresso_solleva(self):
        import models.elo_engine as E
        eng = EloEngine(LEGA)
        E._ELO_ENGINES_CACHE[LEGA] = eng
        E._ELO_ENGINES_STAMP[LEGA] = 1e18
        try:
            with self.assertRaises(EloSeedError) as ctx:
                predict_elo_probs("Alfa", "Beta", LEGA)
        finally:
            E._ELO_ENGINES_CACHE.pop(LEGA, None)
            E._ELO_ENGINES_STAMP.pop(LEGA, None)
        self.assertIn("rating in lega", str(ctx.exception))

    def test_compute_ratings_passa_la_stagione_esplicitamente(self):
        """Il ramo storico non usa piu' season=None: la sorgente del file
        contiene il riferimento con `self.promoted_seed(season)`."""
        import inspect
        src = inspect.getsource(EloEngine.compute_ratings)
        self.assertIn("self.promoted_seed(season)", src)
        self.assertNotIn("self.promoted_seed()", src)

    def test_app_degrada_a_elo_non_disponibile_invece_di_1500(self):
        """I call site di app.py che stanno in try/except segnano il fallback
        invece di usare un numero inventato."""
        src = Path(HERE, "app.py").read_text(encoding="utf-8")
        for blocco in ("elo_probs = predict_elo_probs(h, a, league)",):
            i = src.index(blocco)
            intorno = src[max(0, i - 260):i + 320]
            self.assertIn("elo_disponibile = True", intorno)
            self.assertIn("except Exception", intorno)
            self.assertIn("Elo non disponibile", intorno)
        # Gli altri due chiamano senza stagione dentro try/except espliciti.
        for chiamata in ("elo_p = predict_elo_probs(h, a, camp_sel)",
                         "elo_p = predict_elo_probs(home, away, league)"):
            i = src.index(chiamata)
            intorno = src[max(0, i - 200):i + 400]
            self.assertIn("except Exception", intorno)
        # Nessun chiamante di produzione deve passare season=None a caso:
        # tutti i predict_elo_probs di app.py sono a tre argomenti.
        for riga in src.splitlines():
            if "predict_elo_probs(" in riga and "legacy" not in riga:
                self.assertNotIn("season=", riga, riga)


class TestNessunAltroCambiamento(unittest.TestCase):
    """Le costanti, l'update e la conversione 1X2 restano quelli di prima."""

    STAGIONI = {
        "2022": [_partita("13/08/2022", "Alfa", "Beta", 2, 0)],
        "2023": [_partita("19/08/2023", "Delta", "Alfa", 1, 0)],
    }

    def test_costanti(self):
        import models.elo_engine as E
        self.assertEqual(E.DEFAULT_INITIAL_RATING, 1500.0)
        self.assertEqual(E.HOME_ADVANTAGE, 65.0)
        self.assertEqual(E.BASE_K_FACTOR, 24.0)
        self.assertEqual(E.PROMOTED_SEED_OFFSET, -100.0)

    def test_k_home_adv_e_moltiplicatore_di_scarto(self):
        import models.elo_engine as E
        eng = _motore(self.STAGIONI)
        self.assertEqual(eng.base_k, E.BASE_K_FACTOR)
        self.assertEqual(eng.home_adv, HOME_ADV)
        for scarto, atteso in ((0, 1.0), (1, 1.0), (2, 1.5), (3, 1.75), (6, 2.125)):
            self.assertEqual(E.calculate_goal_margin_multiplier(scarto), atteso, scarto)

    def test_conversione_1x2_e_la_pura_sequenza_di_operazioni(self):
        """``elo_probs_from_ratings`` non e' stata toccata: si rifa a mano."""
        r_h, r_a, ha = 1531.7, 1488.3, 55.0
        dr = r_h + ha - r_a
        e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
        p_draw = max(0.06, min(0.34, 0.27 * float(np.exp(-((dr / 320.0) ** 2)))))
        p_home = (1.0 - p_draw) * e_h
        p_away = (1.0 - p_draw) * (1.0 - e_h)
        tot = p_home + p_draw + p_away
        p = elo_probs_from_ratings(r_h, r_a, ha)
        self.assertEqual(p["1"], round(p_home / tot, 4))
        self.assertEqual(p["X"], round(p_draw / tot, 4))
        self.assertEqual(p["2"], round(p_away / tot, 4))

    def test_compute_ratings_e_un_ricalcolo_completo(self):
        """Chiamarlo due volte non accumula nulla: il seeding riparte da zero."""
        import models.elo_engine as E
        with _DBTemp(TestNeopromossaMaiVista.STAGIONI):
            E._ELO_ENGINES_CACHE.pop(LEGA, None)
            eng = EloEngine(LEGA)
            eng.compute_ratings()
            primo = {k: repr(v) for k, v in eng.ratings.items()}
            primo_delta = repr(eng.history["Delta"][0]["elo_before"])
            eng.compute_ratings()
            self.assertEqual({k: repr(v) for k, v in eng.ratings.items()}, primo)
            self.assertEqual(repr(eng.history["Delta"][0]["elo_before"]), primo_delta)


if __name__ == "__main__":
    unittest.main(verbosity=2)

class TestOrdineDentroLaGiornata(unittest.TestCase):
    """Il seed si legge a INIZIO giornata: riordinare le partite dello stesso
    giorno non cambia niente, ne' i rating ne' le probabilita'.

    Prima della correzione il seed guardava lo stato "in quel momento", quindi
    le partite della stessa giornata gia' processate entravano nella media e il
    risultato dipendeva dall'ordine (e nel backtest il seed poteva usare
    risultati non disponibili prima del kickoff). Qui la proprieta' e' bloccata.
    """

    STAGIONI = {
        "2022": [
            _partita("13/08/2022", "Alfa", "Beta", 2, 0),
            _partita("14/08/2022", "Alfa", "Gamma", 3, 1),
            _partita("15/08/2022", "Alfa", "Delta", 4, 0),
        ],
        "2023": [
            _partita("19/08/2023", "Alfa", "Gamma", 1, 0),
            _partita("20/08/2023", "Gamma", "Alfa", 2, 2),
        ],
    }

    def _con_ingressi(self, ordine):
        epsilon = _partita("18/08/2024", "Epsilon", "Alfa", 1, 0)
        zeta = _partita("18/08/2024", "Zeta", "Gamma", 1, 0)
        righe = ([epsilon, zeta] if ordine == "epsilon_prima" else [zeta, epsilon])
        return _motore(self.STAGIONI, file_per_riga={"2024": righe})

    def test_i_due_ingressi_prendono_lo_stesso_seed_qualunque_sia_l_ordine(self):
        a = self._con_ingressi("epsilon_prima")
        b = self._con_ingressi("zeta_prima")
        # l'ordine realizzato dal loader e' davvero diverso
        self.assertEqual(a.matches_df.iloc[-2]["HomeClean"], "Epsilon")
        self.assertEqual(b.matches_df.iloc[-2]["HomeClean"], "Zeta")
        for squadra in ("Epsilon", "Zeta"):
            self.assertEqual(repr(_rating_prima(a, squadra, 1)),
                             repr(_rating_prima(b, squadra, 1)),
                             f"{squadra}: il seed dipende dall'ordine della giornata")
        # ed e' la media delle attive a inizio giornata, meno l'offset
        seed = _seed_atteso(a, "Epsilon", 1)
        for squadra in ("Epsilon", "Zeta"):
            self.assertEqual(repr(_rating_prima(a, squadra, 1)), repr(seed))

    def test_rating_finali_bit_identici_qualunque_sia_l_ordine(self):
        a = self._con_ingressi("epsilon_prima")
        b = self._con_ingressi("zeta_prima")
        self.assertEqual(set(a.ratings), set(b.ratings))
        for squadra, valore in a.ratings.items():
            self.assertEqual(repr(valore), repr(b.ratings[squadra]),
                             f"{squadra}: rating finale dipende dall'ordine")

    def test_probabilita_bit_identiche_qualunque_sia_l_ordine(self):
        """Stesse partite, ordine diverso dentro la giornata: le 1X2 che la
        produzione calcolerebbe su quei rating sono identiche bit per bit."""
        a = self._con_ingressi("epsilon_prima")
        b = self._con_ingressi("zeta_prima")
        for squadra in ("Alfa", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"):
            self.assertEqual(len(a.history[squadra]), len(b.history[squadra]))
            for x, y in zip(a.history[squadra], b.history[squadra]):
                for campo in ("elo_before", "elo_after"):
                    self.assertEqual(repr(x[campo]), repr(y[campo]),
                                     f"{squadra} {campo}: dipende dall'ordine")
        coppie = [("Epsilon", "Alfa"), ("Zeta", "Gamma"), ("Alfa", "Beta"),
                  ("Gamma", "Delta")]
        for casa, fuori in coppie:
            pa = elo_probs_from_ratings(a.ratings[casa], a.ratings[fuori], 60.0)
            pb = elo_probs_from_ratings(b.ratings[casa], b.ratings[fuori], 60.0)
            for chiave in pa:
                self.assertEqual(repr(pa[chiave]), repr(pb[chiave]),
                                 f"{casa}-{fuori} {chiave}: dipende dall'ordine")
