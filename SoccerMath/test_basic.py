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
from app import get_full_poisson


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


if __name__ == "__main__":
    unittest.main()
