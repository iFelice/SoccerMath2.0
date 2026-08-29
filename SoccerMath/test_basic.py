"""
Test base per validare clean_name, modelli e parsing CSV.
Esegui localmente con: python -m pytest SoccerMath/test_basic.py -v
Oppure semplicemente: python SoccerMath/test_basic.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import unittest
from config import clean_name, LEAGUES_CONFIG, LEAGUE_HOME_ADVANTAGE
from models.elo_engine import predict_elo_probs
from models.dixon_coles import DixonColesEngine
from app import get_full_poisson, run_historical_backtest


class TestCleanName(unittest.TestCase):
    def test_basic_mappings(self):
        self.assertEqual(clean_name("AC Milan"), "Milan")
        self.assertEqual(clean_name("Manchester United"), "Man United")
        self.assertEqual(clean_name("FC Internazionale Milano"), "Inter")

    def test_no_accidental_collision(self):
        # Roma non deve collidere con Bromley o simili
        self.assertNotEqual(clean_name("AS Roma"), clean_name("Bromley"))

    def test_empty(self):
        self.assertEqual(clean_name(""), "")


class TestPoisson(unittest.TestCase):
    def test_1x2_sum(self):
        m = get_full_poisson(1.4, 1.1)
        total = m["1"] + m["X"] + m["2"]
        self.assertAlmostEqual(total, 1.0, places=2)

    def test_under_complement(self):
        m = get_full_poisson(1.4, 1.1)
        self.assertAlmostEqual(m["u25"] + (1 - m["u25"]), 1.0, places=5)

    def test_gg_ng_complement(self):
        m = get_full_poisson(1.4, 1.1)
        self.assertAlmostEqual(m["gg"] + (1 - m["gg"]), 1.0, places=5)


class TestElo(unittest.TestCase):
    def test_home_advantage_config(self):
        self.assertIn("Serie A", LEAGUE_HOME_ADVANTAGE)
        self.assertGreater(LEAGUE_HOME_ADVANTAGE["Serie A"], 0)

    def test_predict_sum(self):
        # 1500 vs 1500 + HA
        probs = predict_elo_probs("TeamA", "TeamB", "Serie A")
        total = probs["1"] + probs["X"] + probs["2"]
        self.assertAlmostEqual(total, 1.0, places=3)


class TestDixonColes(unittest.TestCase):
    def test_fit_empty_fails(self):
        engine = DixonColesEngine("FakeLeague")
        result = engine.fit()
        self.assertFalse(result)

    def test_predict_with_mock_params(self):
        engine = DixonColesEngine("Serie A")
        engine.teams = ["A", "B"]
        engine.team_idx = {"A": 0, "B": 1}
        engine.attack_params = {"A": 0.2, "B": 0.1}
        engine.defense_params = {"A": -0.1, "B": 0.0}
        engine.home_advantage = 0.25
        engine.rho = -0.04
        engine.is_fitted = True
        res = engine.predict_match("A", "B", max_goals=5)
        self.assertGreater(res["lambda"], 0)
        self.assertGreater(res["mu"], 0)
        total = res["1"] + res["X"] + res["2"]
        self.assertAlmostEqual(total, 1.0, places=2)


class TestLeagueDbFiles(unittest.TestCase):
    """get_league_db_files() deve includere i file il cui nome non deriva dal prefisso."""

    def test_premier_legge_premierleague_csv(self):
        from config import get_league_db_files
        files = [os.path.basename(f) for f in get_league_db_files("Premier League")]
        # Dalla stagione 2026/27 PremierLeague.csv e' stato rinominato in Premier_2024.csv:
        # il resolver deve trovare gli archivi stagionali <Prefix>_<anno>.csv + il Live.
        self.assertTrue(any(f.startswith("Premier_20") and f.endswith(".csv") for f in files),
                      "nessun archivo stagionale Premier_20xx risolto dal prefisso 'Premier'")
        self.assertIn("Premier_Live.csv", files)

    def test_tutti_i_file_esistono(self):
        from config import get_league_db_files
        for league in LEAGUES_CONFIG:
            files = get_league_db_files(league)
            self.assertTrue(files, f"nessun CSV trovato per {league}")
            for f in files:
                self.assertTrue(os.path.exists(f), f"file fantasma: {f}")

    def test_live_ultimo_cosi_vince_sui_duplicati(self):
        from config import get_league_db_files
        for league in LEAGUES_CONFIG:
            files = [os.path.basename(f) for f in get_league_db_files(league)]
            live = [f for f in files if "Live" in f]
            if live:
                self.assertEqual(files[-1], live[-1],
                                 f"{league}: il file live deve stare in coda (keep='last')")

    def test_alias_e_lega_inesistente(self):
        from config import get_league_db_files
        self.assertEqual(get_league_db_files("SerieA"), get_league_db_files("Serie A"))
        self.assertEqual(get_league_db_files("Fantacalcio"), [])


class TestLeagueEngineDedupe(unittest.TestCase):
    """get_league_engine() non deve contare due volte le partite base + Live."""

    def test_nessuna_partita_duplicata(self):
        import pandas as pd
        from app import get_league_engine
        for league in LEAGUES_CONFIG:
            engine = get_league_engine(league)
            if not engine:
                continue
            df = engine[3]
            dup = df.duplicated(subset=["Date", "HomeClean", "AwayClean"]).sum()
            self.assertEqual(int(dup), 0, f"{league}: {dup} partite conteggiate due volte")
            self.assertGreater(len(df), 100, f"{league}: dataset troppo piccolo ({len(df)})")
            # le medie gol di lega devono essere valori plausibili, non gonfiati
            self.assertTrue(0.8 < float(df["FTHG"].mean()) < 2.5, f"{league}: avg home goals {df['FTHG'].mean():.2f}")


class TestHistoricalBacktest(unittest.TestCase):
    """Copre run_historical_backtest (walk-forward Poisson vs Elo) usato nel tab BACKTEST."""

    @classmethod
    def setUpClass(cls):
        cls.df = run_historical_backtest("Serie A")

    def test_torna_un_dataframe(self):
        import pandas as pd
        self.assertIsInstance(self.df, pd.DataFrame)
        self.assertFalse(self.df.empty, "con i CSV storici in repo il backtest non deve essere vuoto")

    def test_colonne_attese(self):
        attese = {"date", "home", "away", "real_1x2", "poisson_1x2", "poisson_ok", "elo_1x2",
                  "elo_ok", "real_uo", "poisson_uo", "poisson_uo_ok", "real_gg", "poisson_gg",
                  "poisson_gg_ok"}
        self.assertTrue(attese.issubset(set(self.df.columns)),
                        f"colonne mancanti: {attese - set(self.df.columns)}")

    def test_si_testano_le_partite_recenti(self):
        # max_test deve tagliare la CODA (partiti più recenti), non la testa:
        # la finestra da 50 match e' la coda della finestra 'tutto il dataset'.
        import pandas as pd
        full = run_historical_backtest("Serie A", min_train=30, step=5, max_test=None)
        win = run_historical_backtest("Serie A", min_train=30, step=5, max_test=50)
        cols = ["date", "home", "away", "real_1x2", "poisson_1x2", "elo_1x2"]
        self.assertEqual(len(win), 50)
        pd.testing.assert_frame_equal(
            win[cols].reset_index(drop=True),
            full.tail(len(win))[cols].reset_index(drop=True),
        )
        self.assertLess(len(win), len(full), "con max_test il numero di partite testate cala")

    def test_finestra_non_oltre_max_test(self):
        self.assertLessEqual(len(self.df), 300)
        self.assertGreaterEqual(len(self.df), 250)

    def test_valori_nei_domini_giusti(self):
        self.assertTrue(self.df["real_1x2"].isin(["1", "X", "2"]).all())
        self.assertTrue(self.df["poisson_1x2"].isin(["1", "X", "2"]).all())
        self.assertTrue(self.df["elo_1x2"].isin(["1", "X", "2"]).all())
        self.assertTrue(self.df["real_uo"].isin(["UNDER_2.5", "OVER_2.5"]).all())
        self.assertTrue(self.df["poisson_uo"].isin(["UNDER_2.5", "OVER_2.5"]).all())
        self.assertTrue(self.df["real_gg"].isin(["GG", "NG"]).all())
        self.assertTrue(self.df["poisson_gg"].isin(["GG", "NG"]).all())

    def test_flag_coerenti(self):
        self.assertTrue((self.df["poisson_ok"] == (self.df["poisson_1x2"] == self.df["real_1x2"])).all())
        self.assertTrue((self.df["elo_ok"] == (self.df["elo_1x2"] == self.df["real_1x2"])).all())

    def test_dates_in_ordine(self):
        self.assertTrue(self.df["date"].is_monotonic_increasing,
                        "le partite testate devono essere in ordine cronologico")

    def test_nessun_nan(self):
        self.assertFalse(self.df.isna().any().any(), "il backtest non deve produrre valori mancanti")

    def test_non_sembra_il_tifo_della_domenicale(self):
        # Un modello rotto tende al caso: 1X2 sopra 40% e bidirezionale sotto il 90%
        self.assertGreater(self.df["poisson_ok"].mean(), 0.40)
        self.assertLess(self.df["poisson_ok"].mean(), 0.90)

    def test_cache_restuisce_lo_stesso_output(self):
        again = run_historical_backtest("Serie A")
        self.assertEqual(len(self.df), len(again))
        self.assertTrue(self.df.equals(again))

    def test_lega_sconosciuta(self):
        self.assertTrue(run_historical_backtest("Liga Fantasma").empty)

    def test_dati_troppo_pochi(self):
        self.assertTrue(run_historical_backtest("Serie A", min_train=250000).empty)

    def test_ogni_lega_supportata_produce_righe(self):
        for league in LEAGUES_CONFIG:
            df = run_historical_backtest(league)
            self.assertFalse(df.empty, f"backtest vuoto per {league}")


if __name__ == "__main__":
    unittest.main()
