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


def _rating_prima(eng, squadra, n):
    """Rating della squadra prima della sua n-esima partita (1-based)."""
    return eng.history[squadra][n - 1]["elo_before"]


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

    def test_primo_ingresso_seed_media_attiva_meno_100(self):
        eng = _motore(self.STAGIONI)
        troncato = _motore({"2022": self.STAGIONI["2022"]})
        atteso = _media_attiva(troncato) + PROMOTED_SEED_OFFSET
        ottenuto = _rating_prima(eng, "Delta", 1)
        self.assertEqual(repr(ottenuto), repr(atteso))
        # con un database equilibrato e nessun ingresso precedente la somma dei
        # rating resta 1500 per squadra: il primo seed e' 1400 esatto, non 1500
        self.assertEqual(repr(atteso), repr(1400.0))
        self.assertNotEqual(repr(ottenuto), repr(float(DEFAULT_INITIAL_RATING)))

    def test_secondo_ingresso_usa_la_media_attiva_gia_spozzata(self):
        eng = _motore(self.STAGIONI)
        troncato = _motore({"2022": self.STAGIONI["2022"],
                            "2023": [self.STAGIONI["2023"][0]]})
        atteso = _media_attiva(troncato) + PROMOTED_SEED_OFFSET
        ottenuto = _rating_prima(eng, "Epsilon", 1)
        self.assertEqual(repr(ottenuto), repr(atteso))
        # il seeding precedente ha rotto la conservazione della somma: qui la
        # media attiva NON e' piu' 1500 e il seed non e' piu' 1400
        self.assertNotEqual(repr(atteso), repr(1400.0))
        self.assertNotEqual(repr(ottenuto), repr(float(DEFAULT_INITIAL_RATING)))

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
        troncato = _motore(self.TRONCATO)
        atteso = _media_attiva(troncato) + PROMOTED_SEED_OFFSET
        # Beta ha giocato 2 partite nel 2022: la 3-esima e' il ritorno
        self.assertEqual(repr(_rating_prima(eng, "Beta", 3)), repr(atteso))

    def test_ritorno_scarta_il_rating_stantio(self):
        eng = _motore(self.STAGIONI)
        troncato = _motore(self.TRONCATO)
        stantio = float(troncato.ratings["Beta"])
        seed = _rating_prima(eng, "Beta", 3)
        # main avrebbe ripartito da `stantio`: i due devono divergere
        self.assertNotEqual(repr(seed), repr(stantio))
        # e il seed sta sotto la media attiva, non sopra
        self.assertLess(seed, _media_attiva(troncato))

    def test_squadra_presente_in_stagioni_consecutive_non_e_ingresso(self):
        eng = _motore(self.STAGIONI)
        troncato = _motore(self.TRONCATO)
        # Alfa gioca anche nel 2023: porta il suo rating, nessun seeding.
        # Nel motore completo Alfa ha 6 partite: la 5-esima e' la prima del 2024.
        prima_2024 = _rating_prima(eng, "Alfa", 5)
        seed = _media_attiva(troncato) + PROMOTED_SEED_OFFSET
        self.assertNotEqual(repr(prima_2024), repr(seed))
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
            _partita("18/08/2024", "Delta", "Beta", 2, 1),  # due ingressi insieme
        ],
    }
    TRONCATO = {"2022": STAGIONI["2022"], "2023": STAGIONI["2023"]}

    def test_seed_in_ordine_alfabetico_il_secondo_vede_il_primo(self):
        eng = _motore(self.STAGIONI)
        troncato = _motore(self.TRONCATO)
        attivi = sorted(troncato.ratings)
        # "Beta" < "Delta": Beta e' seminata per PRIMA, con la media attiva
        # intera (tutte e quattro le squadre hanno gia' giocato).
        primo = float(np.mean([troncato.ratings[t] for t in attivi])) + PROMOTED_SEED_OFFSET
        # Delta e' seminata DOPO: la sua media attiva vede il rating di Beta
        # gia' sostituito dal seed. E' l'ordine con cui S3 assegna i seed.
        dopo = [primo if t == "Beta" else troncato.ratings[t] for t in attivi]
        secondo = float(np.mean(dopo)) + PROMOTED_SEED_OFFSET
        self.assertEqual(repr(_rating_prima(eng, "Beta", 2)), repr(primo))
        self.assertEqual(repr(_rating_prima(eng, "Delta", 2)), repr(secondo))
        self.assertNotEqual(repr(primo), repr(secondo))
        self.assertEqual(repr(_media_attiva(troncato) + PROMOTED_SEED_OFFSET), repr(primo))


class TestPrimaPartitaNonGiocataPredizione(unittest.TestCase):
    STAGIONI = {
        "2022": [
            _partita("13/08/2022", "Alfa", "Beta", 2, 0),
            _partita("14/08/2022", "Alfa", "Gamma", 3, 1),
        ],
        "2023": [_partita("19/08/2023", "Alfa", "Beta", 1, 1)],
    }

    def _predici(self, casa, fuori):
        import time
        import models.elo_engine as E
        eng = _motore(self.STAGIONI)
        E._ELO_ENGINES_CACHE[LEGA] = eng
        E._ELO_ENGINES_STAMP[LEGA] = time.monotonic()
        try:
            return eng, predict_elo_probs(casa, fuori, LEGA)
        finally:
            E._ELO_ENGINES_CACHE.pop(LEGA, None)
            E._ELO_ENGINES_STAMP.pop(LEGA, None)

    def test_squadra_ignota_usa_il_seeding_e_non_1500(self):
        eng, p = self._predici("Zeta", "Alfa")
        seed = float(np.mean([eng.ratings[t] for t in sorted(eng.entry_season)])) \
            + PROMOTED_SEED_OFFSET
        self.assertEqual(p["elo_home"], round(seed, 1))
        self.assertEqual(p, elo_probs_from_ratings(seed, eng.ratings["Alfa"], eng.home_adv))
        self.assertNotEqual(p["elo_home"], round(DEFAULT_INITIAL_RATING, 1))

    def test_entrambe_ignote(self):
        eng, p = self._predici("Zeta", "Eta")
        seed = float(np.mean([eng.ratings[t] for t in sorted(eng.entry_season)])) \
            + PROMOTED_SEED_OFFSET
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
    """Caso limite dichiarato: nessuna squadra attiva -> DEFAULT_INITIAL_RATING."""

    def test_motore_mai_calcolato(self):
        eng = EloEngine(LEGA)
        self.assertEqual(eng.entry_season, {})
        self.assertIsNone(eng.first_season)
        self.assertEqual(eng.promoted_seed(), DEFAULT_INITIAL_RATING)

    def test_database_vuoto(self):
        eng = EloEngine(LEGA)
        with _DBTemp({}):
            eng.compute_ratings()
        self.assertEqual(eng.ratings, {})
        self.assertEqual(eng.promoted_seed(), DEFAULT_INITIAL_RATING)

    def test_una_sola_stagione_non_genera_ingressi(self):
        """Il burn-in resta a 1500 anche per una squadra che debutta a meta'."""
        eng = _motore({"2022": [
            _partita("13/08/2022", "Alfa", "Beta", 2, 0),
            _partita("20/08/2022", "Gamma", "Alfa", 1, 0),
        ]})
        self.assertEqual(_rating_prima(eng, "Gamma", 1), DEFAULT_INITIAL_RATING)
        self.assertEqual(eng.entry_season["Gamma"], 2022)

    def test_predizione_senza_squadre_attive(self):
        import models.elo_engine as E
        eng = EloEngine(LEGA)
        self.assertEqual(eng.promoted_seed(), DEFAULT_INITIAL_RATING)
        E._ELO_ENGINES_CACHE[LEGA] = eng
        E._ELO_ENGINES_STAMP[LEGA] = 1e18
        try:
            p = predict_elo_probs("Zeta", "Eta", LEGA)
        finally:
            E._ELO_ENGINES_CACHE.pop(LEGA, None)
            E._ELO_ENGINES_STAMP.pop(LEGA, None)
        self.assertEqual(p, elo_probs_from_ratings(DEFAULT_INITIAL_RATING,
                                                   DEFAULT_INITIAL_RATING, HOME_ADV))


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
    """Il seed conta le SQUADRE attive, e dentro la giornata puo' cambiare.

    Conseguenza diretta e voluta della definizione S3 dell'audit ("squadre
    che hanno gia' una partita precedente nel medesimo ordine di produzione,
    incluse le partite della nuova stagione gia' processate prima
    dell'ingresso"). Prima di questa modifica il motore non ne risentiva: il
    rating di una squadra dipendeva solo dalle sue partite e le partite di
    una stessa giornata sono disgiunte, quindi riordinarle non cambiava un
    bit. Con il seed attivo l'ordine dentro la giornata e' osservabile, ma
    solo dove un blocco-giornata contiene piu' di un ingresso: gli update Elo
    sono a somma zero, quindi la media delle squadre attive non cambia se la
    partita precedente e' fra due squadre gia' attive.

    Il test fissa la proprieta' perche' e' il motivo per cui il confronto
    walk-forward su DB troncato di audit/test_elo_walker_parity.py non puo'
    piu' essere bit-exact (vedi TOLLERANZA_* li').
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

    def _con_due_ingressi(self, ordine):
        """Stesse partite, stesso giorno, ordine di acquisizione diverso."""
        epsilon = _partita("18/08/2024", "Epsilon", "Alfa", 1, 0)
        zeta = _partita("18/08/2024", "Zeta", "Gamma", 1, 0)
        righe = [epsilon, zeta] if ordine == "epsilon_prima" else [zeta, epsilon]
        eng = _motore(self.STAGIONI, file_per_riga={"2024": righe})
        return eng, epsilon, zeta

    def test_il_secondo_ingresso_della_giornata_vede_il_seed_del_primo(self):
        eps_prima, eps, zeta = self._con_due_ingressi("epsilon_prima")
        zeta_prima, _, _ = self._con_due_ingressi("zeta_prima")
        # ordine realizzato dal loader (controllato, non casuale)
        self.assertEqual(eps_prima.matches_df.iloc[-2]["HomeClean"], "Epsilon")
        self.assertEqual(eps_prima.matches_df.iloc[-1]["HomeClean"], "Zeta")
        self.assertEqual(zeta_prima.matches_df.iloc[-2]["HomeClean"], "Zeta")
        self.assertEqual(zeta_prima.matches_df.iloc[-1]["HomeClean"], "Epsilon")

        media_iniziale = _media_attiva(_motore(self.STAGIONI))
        seed_primo = media_iniziale + PROMOTED_SEED_OFFSET
        # chi arriva per secondo ha nel gruppo attivo anche il seed del primo:
        # la media dei cinque non e' piu' quella iniziale.
        media_dopo = float(np.mean(
            [seed_primo] + [1500.0] * 4))          # 4 squadre del burn-in a 1500
        seed_secondo = media_dopo + PROMOTED_SEED_OFFSET

        self.assertEqual(repr(_rating_prima(eps_prima, "Epsilon", 1)), repr(seed_primo))
        self.assertEqual(repr(_rating_prima(eps_prima, "Zeta", 1)), repr(seed_secondo))
        # scambiando l'ordine di acquisizione i due seed si scambiano
        self.assertEqual(repr(_rating_prima(zeta_prima, "Zeta", 1)), repr(seed_primo))
        self.assertEqual(repr(_rating_prima(zeta_prima, "Epsilon", 1)), repr(seed_secondo))
        self.assertLess(seed_secondo, seed_primo)

    def test_senza_ingressi_l_ordine_dentro_la_giornata_non_conta(self):
        """Prima del seeding le partite di una giornata erano disgiunte:
        riordinarle non cambiava un bit, e il motore deve continuare a farlo."""
        a = _partita("19/08/2023", "Alfa", "Gamma", 1, 0)
        b = _partita("19/08/2023", "Beta", "Delta", 0, 2)
        ing = self.STAGIONI["2022"]
        uno = _motore({**self.STAGIONI, "2023": ing}, file_per_riga={"2023": [a, b]})
        due = _motore({**self.STAGIONI, "2023": ing}, file_per_riga={"2023": [b, a]})
        self.assertEqual(uno.matches_df.iloc[-2]["HomeClean"], "Alfa")
        self.assertEqual(due.matches_df.iloc[-2]["HomeClean"], "Beta")
        for squadra in ("Alfa", "Beta", "Gamma", "Delta"):
            self.assertEqual(repr(uno.ratings[squadra]), repr(due.ratings[squadra]),
                             f"{squadra}: l'ordine dentro la giornata ha cambiato "
                             f"il rating finale")
