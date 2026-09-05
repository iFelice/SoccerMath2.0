"""Test del replay A vs B del selettore Top Mix (audit/topmix_selector_replay.py).

Test veloci e deterministici: nessun accesso di rete, nessuna scrittura nel
database di produzione, nessuna soglia ridefinita. Verificano le sole parti
NUOVE del replay (ricostruzione giornata, esiti dei mercati, metriche,
dominanza di B su A), non il motore di produzione che resta invariato.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
if _AUDIT_DIR not in sys.path:
    sys.path.insert(0, _AUDIT_DIR)

import topmix_selector_replay as SR  # noqa: E402
import reconstruct_topmix_match as R  # noqa: E402


def _fixture(idx, md, iso, home, away, fthg=0, ftag=0):
    kick = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return {
        "id": f"T|{idx}", "matchday": md, "utcDate": iso,
        "homeTeam": {"shortName": home}, "awayTeam": {"shortName": away},
        "_kick": kick, "_fthg": fthg, "_ftag": ftag,
    }


class TestMatchdayDerivation(unittest.TestCase):
    def test_regular_calendar(self):
        """Calendario regolare a 4 squadre: due giornate da due partite."""
        base = datetime(2024, 8, 17, 14, 0, tzinfo=timezone.utc)
        kicks = [base, base, base + timedelta(days=7), base + timedelta(days=7)]
        homes = ["A", "C", "B", "D"]
        aways = ["B", "D", "A", "C"]
        self.assertEqual(SR.derive_matchdays(kicks, homes, aways), [1, 1, 2, 2])

    def test_postponed_match_takes_later_matchday(self):
        """Un recupero prende la giornata in cui viene giocato (approssimazione dichiarata)."""
        base = datetime(2024, 8, 17, 14, 0, tzinfo=timezone.utc)
        kicks = [base, base + timedelta(days=7), base + timedelta(days=30)]
        homes = ["A", "A", "A"]
        aways = ["B", "C", "D"]
        self.assertEqual(SR.derive_matchdays(kicks, homes, aways), [1, 2, 3])

    def test_order_is_chronological_not_file_order(self):
        base = datetime(2024, 8, 17, 14, 0, tzinfo=timezone.utc)
        kicks = [base + timedelta(days=7), base]
        homes, aways = ["A", "A"], ["B", "C"]
        self.assertEqual(SR.derive_matchdays(kicks, homes, aways), [2, 1])


class TestReplayUnits(unittest.TestCase):
    def test_uses_production_selector_and_cutoff(self):
        fx = [
            _fixture(0, 1, "2024-08-17T14:00:00Z", "A", "B"),
            _fixture(1, 1, "2024-08-17T16:30:00Z", "C", "D"),
            _fixture(2, 2, "2024-08-24T14:00:00Z", "B", "C"),
            _fixture(3, 2, "2024-08-24T16:30:00Z", "D", "A"),
        ]
        units = SR.replay_units(fx)
        self.assertEqual([u["matchday"] for u in units], [1, 2])
        self.assertEqual(units[0]["cutoff"],
                         datetime(2024, 8, 17, 14, 0, tzinfo=timezone.utc))
        self.assertEqual(len(units[0]["matches"]), 2)
        self.assertEqual(len(units[1]["matches"]), 2)

    def test_round_window_excludes_far_match(self):
        """Recupero della stessa giornata oltre TOP_MIX_ROUND_WINDOW_DAYS: fuori."""
        far = "2024-09-30T18:00:00Z"
        fx = [
            _fixture(0, 1, "2024-08-17T14:00:00Z", "A", "B"),
            _fixture(1, 1, far, "C", "D"),
        ]
        units = SR.replay_units(fx)
        self.assertEqual(len(units[0]["matches"]), 1)
        self.assertEqual(units[0]["n_excluded_window"], 1)

    def test_empty_input(self):
        self.assertEqual(SR.replay_units([]), [])


class TestMarketOutcome(unittest.TestCase):
    def test_codes(self):
        self.assertEqual(SR.market_code("Vittoria Inter", "Inter", "Roma"), "1")
        self.assertEqual(SR.market_code("Vittoria Roma", "Inter", "Roma"), "2")
        self.assertEqual(SR.market_code("Pareggio", "Inter", "Roma"), "X")
        self.assertEqual(SR.market_code("Over 2.5", "Inter", "Roma"), "O2.5")
        self.assertEqual(SR.market_code("NG", "Inter", "Roma"), "NG")

    def test_outcomes_2_1(self):
        got = {c: SR.market_outcome(c, 2, 1)
               for c in ("1", "X", "2", "O2.5", "U2.5", "GG", "NG")}
        self.assertEqual(got, {"1": 1, "X": 0, "2": 0, "O2.5": 1, "U2.5": 0,
                               "GG": 1, "NG": 0})

    def test_outcomes_0_0(self):
        got = {c: SR.market_outcome(c, 0, 0)
               for c in ("1", "X", "2", "O2.5", "U2.5", "GG", "NG")}
        self.assertEqual(got, {"1": 0, "X": 1, "2": 0, "O2.5": 0, "U2.5": 1,
                               "GG": 0, "NG": 1})

    def test_outcomes_1_2(self):
        got = {c: SR.market_outcome(c, 1, 2)
               for c in ("1", "X", "2", "O2.5", "U2.5", "GG", "NG")}
        self.assertEqual(got, {"1": 0, "X": 0, "2": 1, "O2.5": 1, "U2.5": 0,
                               "GG": 1, "NG": 0})

    def test_unknown_market_raises(self):
        with self.assertRaises(ValueError):
            SR.market_outcome("Over 1.5", 1, 1)


class TestSelectorDominance(unittest.TestCase):
    """B non puo' perdere una partita che A ammette: stessa formula, stesso mercato."""

    def _markets(self, p1, px, p2, o25, gg):
        return {"Vittoria Inter": p1, "Pareggio": px, "Vittoria Roma": p2,
                "Over 2.5": o25, "Under 2.5": 1 - o25, "GG": gg, "NG": 1 - gg}

    def test_b_admits_whenever_a_admits(self):
        import random
        rng = random.Random(7)
        checked = 0
        for _ in range(500):
            raw = [rng.random() for _ in range(3)]
            s = sum(raw)
            p1, px, p2 = (x / s for x in raw)
            o25 = rng.random()
            gg = rng.random()
            mercati = self._markets(p1, px, p2, o25, gg)
            e_raw = [rng.random() for _ in range(3)]
            es = sum(e_raw)
            elo = {"1": e_raw[0] / es, "X": e_raw[1] / es, "2": e_raw[2] / es}
            a = R.apply_selector_A(mercati, "Inter", "Roma", elo)
            b = R.apply_selector_B(mercati, "Inter", "Roma", elo)
            if a["admitted"]:
                checked += 1
                self.assertTrue(b["admitted"])
                self.assertGreaterEqual(b["confidence"] + 1e-12, a["confidence"])
        self.assertGreater(checked, 0)


class TestMetrics(unittest.TestCase):
    def _row(self, **kw):
        base = {
            "league": "Serie A", "season": 2024, "season_label": "2024/25",
            "matchday": 1, "cutoff": "2024-08-17T14:00:00+00:00",
            "match_id": "m1", "home": "Inter", "away": "Roma",
            "kickoff": "2024-08-17T14:00:00Z", "fthg": 2, "ftag": 1,
            "team_stats_missing": 0, "elo_available": True,
            "A_market": "1", "A_poisson": 0.7, "A_conf": 0.7, "A_disagree": 0.05,
            "A_min_conf": 0.55, "A_admitted": True, "A_hit": 1,
            "B_market": "1", "B_conf": 0.7, "B_admitted": True,
            "B_n_admitted_markets": 1, "B_hit": 1,
            "per_market": {c: {"poisson": 0.5, "conf": 0.5, "admitted": False,
                               "hit": SR.market_outcome(c, 2, 1)}
                           for c in ("1", "X", "2", "O2.5", "U2.5", "GG", "NG")},
        }
        base.update(kw)
        return base

    def test_dedup_by_match_id(self):
        rows = [self._row(), self._row(), self._row(match_id="m2")]
        out, dups = SR.dedup_rows(rows)
        self.assertEqual(len(out), 2)
        self.assertEqual(dups, 1)

    def test_disagreement_and_rescue_counts(self):
        rows = [
            self._row(match_id="m1"),  # accordo
            self._row(match_id="m2", A_market="O2.5", A_hit=1, B_market="1",
                      B_conf=0.71, B_hit=1),  # disaccordo, entrambi ammessi
            self._row(match_id="m3", A_admitted=False, A_conf=0.50,
                      A_market="X", A_hit=0, B_market="O2.5", B_conf=0.66,
                      B_hit=1),  # A scarta, B recupera
        ]
        m = SR.compute_metrics(rows, [])
        agg = m["aggregate"]
        self.assertEqual(agg["n_candidates"], 3)
        self.assertEqual(agg["n_A_admitted"], 2)
        self.assertEqual(agg["n_B_admitted"], 3)
        self.assertEqual(agg["disagreement"]["n_diff_market_both_admitted"], 1)
        self.assertAlmostEqual(agg["disagreement"]["freq_diff_given_both"], 0.5)
        self.assertEqual(agg["disagreement"]["n_diff_market_any_B"], 2)
        self.assertEqual(agg["rescued_by_B"]["n"], 1)
        self.assertEqual(agg["n_A_only"], 0)
        self.assertEqual(
            agg["rescued_by_B"]["reasons"]["A: confidence sotto soglia"], 1)

    def test_brier_and_hit_rate_on_disagreement(self):
        rows = [
            self._row(match_id="m1", A_market="O2.5", A_conf=0.70, A_hit=1,
                      B_market="1", B_conf=0.80, B_hit=0),
            self._row(match_id="m2", A_market="O2.5", A_conf=0.60, A_hit=0,
                      B_market="1", B_conf=0.90, B_hit=1),
        ]
        m = SR.compute_metrics(rows, [])
        a = m["aggregate"]["on_disagreement"]["A"]
        b = m["aggregate"]["on_disagreement"]["B"]
        self.assertEqual(a["n"], 2)
        self.assertAlmostEqual(a["hit_rate"], 0.5)
        self.assertAlmostEqual(a["brier"], ((0.7 - 1) ** 2 + (0.6 - 0) ** 2) / 2)
        self.assertAlmostEqual(b["brier"], ((0.8 - 0) ** 2 + (0.9 - 1) ** 2) / 2)

    def test_thresholds_are_the_production_ones(self):
        """Il replay non introduce soglie proprie: usa quelle importate."""
        self.assertEqual(R.MIN_CONF_1X2, 0.55)
        self.assertEqual(R.MIN_CONF_OU_GG, 0.60)
        self.assertEqual(R.ELO_DISAGREE_MAX, 0.25)
        self.assertEqual(R.POISSON_WEIGHT, 0.6)
        self.assertEqual(R.ELO_WEIGHT, 0.4)
        src = open(os.path.join(_AUDIT_DIR, "topmix_selector_replay.py"),
                   encoding="utf-8").read()
        for forbidden in ("0.55", "0.60", "0.25", "= 0.6", "= 0.4"):
            self.assertNotIn(f"MIN_CONF_1X2 = {forbidden}", src)
        for name in R._FORBIDDEN_CALLS:
            self.assertNotIn(f"{name}(", src)


class TestNoProductionWrites(unittest.TestCase):
    def test_point_in_time_db_restores_paths(self):
        import config
        before = str(config.DATABASE_DIR)
        pit = SR.PointInTimeDB()
        try:
            self.assertNotEqual(str(config.DATABASE_DIR), before)
        finally:
            pit.close()
        self.assertEqual(str(config.DATABASE_DIR), before)
        self.assertFalse(os.path.exists(pit.tmp))


if __name__ == "__main__":
    unittest.main(verbosity=2)
