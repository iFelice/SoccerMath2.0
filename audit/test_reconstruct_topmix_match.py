"""Test della ricostruzione Top Mix: usa le funzioni di produzione, non scrive il registro."""
from __future__ import annotations

import ast
import os
import sys
import unittest

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
_SOCCER = os.path.join(_REPO_ROOT, "SoccerMath")
sys.path.insert(0, _SOCCER)
sys.path.insert(0, _AUDIT_DIR)

os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")

from reconstruct_topmix_match import (  # noqa: E402
    ELO_DISAGREE_MAX,
    ELO_WEIGHT,
    MIN_CONF_1X2,
    MIN_CONF_OU_GG,
    POISSON_WEIGHT,
    SEVEN_MARKET_KEYS,
    apply_selector_A,
    apply_selector_B,
    database_at_git_ref,
    git_commit_0695e9e_present,
    git_sha,
    main_head_at,
    reconstruct_match,
    seven_markets,
    _FORBIDDEN_CALLS,
)


APP_PATH = os.path.join(_SOCCER, "app.py")
RECON_PATH = os.path.join(_AUDIT_DIR, "reconstruct_topmix_match.py")


def _app_topmix_source() -> str:
    with open(APP_PATH, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "fetch_and_calc_top_mix":
            return ast.unparse(node)
    raise AssertionError("fetch_and_calc_top_mix non trovata")


class TestNoWriteSideEffects(unittest.TestCase):
    def test_reconstruction_module_never_calls_savers(self):
        with open(RECON_PATH, encoding="utf-8") as f:
            src = f.read()
        # Importati solo come guardia: non devono comparire come chiamate.
        tree = ast.parse(src)
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name in _FORBIDDEN_CALLS:
                    called.add(name)
        self.assertEqual(called, set())

    def test_forbidden_list_covers_registry_writers(self):
        for name in (
            "save_prediction_entry", "save_predictions",
            "load_predictions", "fetch_and_calc_top_mix",
        ):
            self.assertIn(name, _FORBIDDEN_CALLS)


class TestProductionConstants(unittest.TestCase):
    def test_weights_and_thresholds_match_fetch_and_calc_top_mix(self):
        src = _app_topmix_source()
        self.assertIn("0.6 * poisson_prob + 0.4 * elo_prob", src)
        # 0.60 nel file; ast.unparse lo rende 0.6
        self.assertTrue("min_conf = 0.60" in src or "min_conf = 0.6" in src)
        self.assertIn("min_conf = 0.55", src)
        self.assertIn("abs(poisson_prob - elo_prob) < 0.25", src)
        self.assertIn("[:10]", src)
        self.assertEqual(POISSON_WEIGHT, 0.6)
        self.assertEqual(ELO_WEIGHT, 0.4)
        self.assertEqual(MIN_CONF_OU_GG, 0.60)
        self.assertEqual(MIN_CONF_1X2, 0.55)
        self.assertEqual(ELO_DISAGREE_MAX, 0.25)

    def test_seven_markets_only(self):
        src = _app_topmix_source()
        self.assertIn("Over 2.5", src)
        self.assertIn("Under 2.5", src)
        self.assertIn("GG", src)
        self.assertIn("NG", src)
        self.assertNotIn("Over 1.5", src)
        self.assertNotIn("Over 3.5", src)
        self.assertEqual(len(SEVEN_MARKET_KEYS), 7)


class TestSelectorOrderEffect(unittest.TestCase):
    """A e B con le STESSE soglie possono scegliere mercati diversi: effetto ordine."""

    def test_b_can_pick_1x2_when_a_picks_over(self):
        home, away = "Home", "Away"
        mercati = {
            f"Vittoria {home}": 0.62,
            "Pareggio": 0.18,
            f"Vittoria {away}": 0.20,
            "Over 2.5": 0.70,
            "Under 2.5": 0.30,
            "GG": 0.55,
            "NG": 0.45,
        }
        elo = {"1": 0.85, "X": 0.10, "2": 0.05}
        a = apply_selector_A(mercati, home, away, elo)
        b = apply_selector_B(mercati, home, away, elo)
        self.assertEqual(a["best_market"], "Over 2.5")
        self.assertEqual(a["prob_val"], 70.0)
        self.assertTrue(a["admitted"])
        self.assertEqual(b["best_market"], f"Vittoria {home}")
        self.assertGreater(b["confidence"], a["confidence"])
        # soglie identiche
        self.assertEqual(a["filters"]["min_conf"], MIN_CONF_OU_GG)
        self.assertEqual(b["filters"]["min_conf_1x2"], MIN_CONF_1X2)

    def test_a_and_b_agree_when_max_poisson_is_already_the_final_max(self):
        home, away = "H", "A"
        mercati = {
            f"Vittoria {home}": 0.40,
            "Pareggio": 0.20,
            f"Vittoria {away}": 0.40,
            "Over 2.5": 0.81,
            "Under 2.5": 0.19,
            "GG": 0.60,
            "NG": 0.40,
        }
        elo = {"1": 0.40, "X": 0.20, "2": 0.40}
        a = apply_selector_A(mercati, home, away, elo)
        b = apply_selector_B(mercati, home, away, elo)
        self.assertEqual(a["best_market"], b["best_market"])
        self.assertEqual(a["best_market"], "Over 2.5")


class TestSchalkeBayernProduction(unittest.TestCase):
    """Integrazione: motore reale sullo snapshot committato. Nessun salvataggio."""

    @classmethod
    def setUpClass(cls):
        cls.rec = reconstruct_match("Schalke", "Bayern", "Bundesliga")

    def test_engine_ok(self):
        self.assertTrue(self.rec["ok"], self.rec.get("error"))

    def test_canonical_names(self):
        self.assertEqual(self.rec["canonical_names"]["home"], "Schalke 04")
        self.assertEqual(self.rec["canonical_names"]["away"], "Bayern")

    def test_mapped_not_default_fallback(self):
        self.assertFalse(self.rec["defaults_att_def_1"]["home"])
        self.assertFalse(self.rec["defaults_att_def_1"]["away"])
        self.assertTrue(self.rec["home"]["in_engine_stats"])
        self.assertTrue(self.rec["away"]["in_engine_stats"])

    def test_xg_keys_hit(self):
        self.assertTrue(self.rec["home"]["xg_key_hit"])
        self.assertTrue(self.rec["away"]["xg_key_hit"])

    def test_seven_poisson_markets(self):
        m = self.rec["seven_markets_poisson"]
        self.assertEqual(len(m), 7)
        self.assertIn("Vittoria Schalke", m)
        self.assertIn("Vittoria Bayern", m)
        self.assertIn("Pareggio", m)
        self.assertIn("Over 2.5", m)
        self.assertIn("Under 2.5", m)
        self.assertIn("GG", m)
        self.assertIn("NG", m)
        self.assertAlmostEqual(m["Over 2.5"] + m["Under 2.5"], 1.0, places=5)
        self.assertAlmostEqual(m["GG"] + m["NG"], 1.0, places=5)

    def test_poisson_crosscheck(self):
        self.assertTrue(all(self.rec["poisson_crosscheck_vs_lambdas"].values()))

    def test_trace_matches_engine_pure_ratios(self):
        self.assertTrue(self.rec["home"]["trace_matches_engine_att0_pure"])
        self.assertTrue(self.rec["away"]["trace_matches_engine_att0_pure"])

    def test_elo_probs_sum_to_one(self):
        elo = self.rec["elo_1x2"]
        self.assertIsNotNone(elo)
        self.assertAlmostEqual(elo["1"] + elo["X"] + elo["2"], 1.0, places=3)

    def test_does_not_force_92_1(self):
        """Se il 92,1% non esce, il campo reproduced e' False: non si forza."""
        tgt = self.rec["target_92_1"]
        self.assertIn("reproduced_by_selector_A", tgt)
        if tgt["reproduced_by_selector_A"]:
            self.assertAlmostEqual(tgt["selector_A_prob_val"], 92.1, places=1)
        else:
            self.assertNotAlmostEqual(float(tgt["selector_A_prob_val"]), 92.1, places=1)

    def test_missing_api_snapshot_declared(self):
        missing = " ".join(self.rec["missing_for_bit_exact_replay"])
        self.assertIn("snapshot API", missing)

    def test_seven_markets_helper_matches_production_keys(self):
        fake = {"1": 0.4, "X": 0.2, "2": 0.4, "u25": 0.45, "gg": 0.5, "u15": 0, "u35": 0}
        m = seven_markets("H", "A", fake)
        self.assertEqual(set(m), {
            "Vittoria H", "Pareggio", "Vittoria A",
            "Over 2.5", "Under 2.5", "GG", "NG",
        })


class TestHistoricalGitRef(unittest.TestCase):
    """Ricostruzione su commit storico senza cambiare HEAD del working tree."""

    def test_main_head_at_xg_commit(self):
        info = main_head_at("2026-09-05T16:14:56+00:00")
        if not info.get("sha"):
            self.skipTest(f"storia git non disponibile in questo clone: {info}")
        self.assertTrue(info.get("sha", "").startswith("0695e9e"), info)

    def test_database_at_ref_does_not_move_head(self):
        import config
        before = git_sha()
        old_db = str(config.DATABASE_DIR)
        try:
            with database_at_git_ref("0695e9e611e481d2a9f5648a3a9fcd4412f86070") as hist:
                self.assertTrue(os.path.isdir(hist.db))
                self.assertTrue(os.path.exists(os.path.join(hist.db, "xg_bundesliga.json")))
                self.assertNotEqual(str(config.DATABASE_DIR), old_db)
                rec = reconstruct_match("Schalke", "Bayern", "Bundesliga")
                self.assertTrue(rec["ok"], rec.get("error"))
                self.assertIsNotNone((rec.get("selector_A") or {}).get("prob_val"))
        except RuntimeError as exc:
            self.skipTest(f"ref storico non disponibile in questo clone: {exc}")
        self.assertEqual(git_sha(), before)
        self.assertEqual(str(config.DATABASE_DIR), old_db)

    def test_reconstruct_match_git_ref_kw(self):
        before = git_sha()
        try:
            rec = reconstruct_match(
                "Schalke", "Bayern", "Bundesliga",
                git_ref="0695e9e611e481d2a9f5648a3a9fcd4412f86070",
            )
        except RuntimeError as exc:
            self.skipTest(f"ref storico non disponibile in questo clone: {exc}")
        self.assertTrue(rec["ok"], rec.get("error"))
        self.assertTrue(str(rec.get("snapshot_commit") or "").startswith("0695e9e"))
        self.assertEqual(git_sha(), before)


if __name__ == "__main__":
    unittest.main()
