"""
test_elo_probs_from_ratings.py — Contratto PERMANENTE della funzione pura
``models.elo_engine.elo_probs_from_ratings``, estratta da
``predict_elo_probs`` con un refactor puramente strutturale (PR #30).

Contratti fissati da questo test:

1. ``predict_elo_probs`` delega a ``elo_probs_from_ratings`` passando i
   rating letti dal motore in cache (default ``DEFAULT_INITIAL_RATING``
   = 1500.0 per le squadre sconosciute) e ``engine.home_adv``.
2. L'output di ``predict_elo_probs`` e' BIT-IDENTICO a quello di
   ``elo_probs_from_ratings`` sugli stessi rating, su tutte le chiavi
   (confronto su ``repr(float)``, non ``assertAlmostEqual``).
3. ``elo_probs_from_ratings`` e' PURA: non legge ne' scrive
   ``_ELO_ENGINES_CACHE`` e non ha bisogno di alcun motore.
4. Proprieta' numeriche della formula documentata nel docstring, su una
   griglia di rating: terna normalizzata a 1 entro l'arrotondamento,
   ``p_draw`` dentro [0.06, 0.34], simmetria ``dr -> -dr``, monotonia di
   ``expected_score_home`` in ``dr``.

Esecuzione:
    python -m pytest SoccerMath/test_elo_probs_from_ratings.py -v
    python SoccerMath/test_elo_probs_from_ratings.py
"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import models.elo_engine as EE  # noqa: E402
from models.elo_engine import (  # noqa: E402
    DEFAULT_INITIAL_RATING,
    elo_probs_from_ratings,
    predict_elo_probs,
)

KEYS = ("1", "X", "2", "elo_home", "elo_away", "elo_diff", "home_adv",
        "expected_score_home", "expected_score_away")
LEGA = "__TEST_LEAGUE__"


class _StubEngine:
    """Superficie minima letta da predict_elo_probs: ratings + home_adv."""

    def __init__(self, ratings, home_adv):
        self.ratings = dict(ratings)
        self.home_adv = home_adv


class _CacheStub:
    def __init__(self, engine):
        self.engine = engine

    def __enter__(self):
        import time
        EE._ELO_ENGINES_CACHE[LEGA] = self.engine
        EE._ELO_ENGINES_STAMP[LEGA] = time.monotonic()
        return self

    def __exit__(self, *exc):
        EE._ELO_ENGINES_CACHE.pop(LEGA, None)
        EE._ELO_ENGINES_STAMP.pop(LEGA, None)
        return False


class TestChiaviEPurezza(unittest.TestCase):

    def test_chiavi_invariate(self):
        out = elo_probs_from_ratings(1500.0, 1400.0, 60.0)
        self.assertEqual(tuple(out.keys()), KEYS)

    def test_funzione_pura_non_tocca_la_cache(self):
        prima = dict(EE._ELO_ENGINES_CACHE)
        elo_probs_from_ratings(1712.3, 1488.9, 55.0)
        self.assertEqual(dict(EE._ELO_ENGINES_CACHE), prima)

    def test_home_adv_restituito_non_arrotondato(self):
        out = elo_probs_from_ratings(1500.0, 1500.0, 57.3333)
        self.assertEqual(repr(out["home_adv"]), repr(57.3333))


class TestDelega(unittest.TestCase):
    """predict_elo_probs == elo_probs_from_ratings, bit per bit."""

    def test_delega_bit_exact_su_griglia(self):
        for home_adv in (55.0, 56.0, 58.0, 60.0, 70.0):
            for r_h in range(1200, 1901, 50):
                for r_a in range(1200, 1901, 50):
                    eng = _StubEngine({"CASA": float(r_h), "FUORI": float(r_a)},
                                      home_adv)
                    with _CacheStub(eng):
                        got = predict_elo_probs("CASA", "FUORI", LEGA)
                    want = elo_probs_from_ratings(float(r_h), float(r_a), home_adv)
                    for k in KEYS:
                        self.assertEqual(repr(got[k]), repr(want[k]),
                                         f"chiave {k} r_h={r_h} r_a={r_a} ha={home_adv}")

    def test_squadra_sconosciuta_usa_il_default_1500(self):
        eng = _StubEngine({"CASA": 1700.0}, 60.0)
        with _CacheStub(eng):
            got = predict_elo_probs("CASA", "MAI_VISTA", LEGA)
        want = elo_probs_from_ratings(1700.0, DEFAULT_INITIAL_RATING, 60.0)
        for k in KEYS:
            self.assertEqual(repr(got[k]), repr(want[k]), f"chiave {k}")
        self.assertEqual(repr(got["elo_away"]), repr(round(DEFAULT_INITIAL_RATING, 1)))

    def test_entrambe_sconosciute_usano_il_default(self):
        eng = _StubEngine({}, 65.0)
        with _CacheStub(eng):
            got = predict_elo_probs("A", "B", LEGA)
        want = elo_probs_from_ratings(DEFAULT_INITIAL_RATING,
                                      DEFAULT_INITIAL_RATING, 65.0)
        for k in KEYS:
            self.assertEqual(repr(got[k]), repr(want[k]), f"chiave {k}")


class TestProprietaFormula(unittest.TestCase):

    def test_terna_normalizzata_e_pdraw_nel_range(self):
        for home_adv in (55.0, 70.0):
            for r_h in range(1200, 1901, 25):
                for r_a in range(1200, 1901, 25):
                    o = elo_probs_from_ratings(float(r_h), float(r_a), home_adv)
                    self.assertAlmostEqual(o["1"] + o["X"] + o["2"], 1.0, places=3)
                    self.assertGreaterEqual(o["X"], 0.06 - 5e-5)
                    self.assertLessEqual(o["X"], 0.34 + 5e-5)

    def test_simmetria_scambio_dei_rating(self):
        """dr -> -dr scambia 1 e 2 e lascia X invariata."""
        for d in range(0, 501, 25):
            a = elo_probs_from_ratings(1500.0 + d, 1500.0, 0.0)
            b = elo_probs_from_ratings(1500.0, 1500.0 + d, 0.0)
            self.assertEqual(repr(a["1"]), repr(b["2"]))
            self.assertEqual(repr(a["2"]), repr(b["1"]))
            self.assertEqual(repr(a["X"]), repr(b["X"]))

    def test_expected_score_home_monotono_in_dr(self):
        prev = -1.0
        for r_h in range(1200, 1901, 10):
            cur = elo_probs_from_ratings(float(r_h), 1500.0, 60.0)["expected_score_home"]
            self.assertGreaterEqual(cur, prev)
            prev = cur


if __name__ == "__main__":
    unittest.main(verbosity=2)
