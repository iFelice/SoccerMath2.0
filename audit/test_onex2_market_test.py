"""Test offline e deterministici per audit/onex2_market_test.py.

Nessun dato esterno: tutto su valori sintetici o su casi con risultato noto a mano.
Eseguibile con pytest o direttamente: python audit/test_onex2_market_test.py
"""
import os
import sys
import unittest

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import onex2_market_test as T  # noqa: E402


def _rows(fn, odds):
    """De-vig e' per singola terna (come in produzione: raw[i]); qui si applica riga per riga."""
    return np.array([fn(o) for o in odds])


class DevigTests(unittest.TestCase):
    def test_shin_sums_to_one_and_keeps_order(self):
        odds = np.array([[1.80, 3.60, 4.50], [2.50, 3.20, 2.90], [1.30, 5.50, 9.00]])
        p = _rows(T.devig_shin3, odds)
        self.assertTrue(np.allclose(p.sum(axis=1), 1.0, atol=1e-9))
        # il favorito resta favorito
        self.assertTrue(np.all(np.argmax(p, axis=1) == np.argmin(odds, axis=1)))

    def test_prop_sums_to_one_and_is_proportional(self):
        p = T.devig_prop3(np.array([2.0, 4.0, 4.0]))  # 1/o = 0.5, 0.25, 0.25 -> somma 1
        self.assertTrue(np.allclose(p, [0.5, 0.25, 0.25], atol=1e-12))
        o2 = np.array([1.90, 3.40, 4.20])  # con overround
        p2 = T.devig_prop3(o2)
        self.assertAlmostEqual(float(p2.sum()), 1.0, places=12)
        r = (1 / o2) / (1 / o2).sum()
        self.assertTrue(np.allclose(p2, r, atol=1e-12))

    def test_shin_equals_prop_without_overround(self):
        self.assertTrue(np.allclose(T.devig_shin3(np.array([2.0, 4.0, 4.0])), [0.5, 0.25, 0.25], atol=1e-7))

    def test_invalid_odds_return_none(self):
        self.assertIsNone(T.devig_shin3(np.array([1.0, 3.0, 4.0])))
        self.assertIsNone(T.devig_prop3(np.array([np.nan, 3.0, 4.0])))


class MetricTests(unittest.TestCase):
    def test_logloss_brier_rps_hand_case(self):
        P = np.array([[0.5, 0.25, 0.25]])
        y = np.array([0])  # esito 1 (casa); ordine 1 < X < 2
        ll, br, rps = T.row_losses(P, y)
        self.assertAlmostEqual(float(ll[0]), -np.log(0.5), places=12)
        self.assertAlmostEqual(float(br[0]), 0.25 + 0.0625 + 0.0625, places=12)
        # RPS = 1/2 * sum_k (F_k - O_k)^2 con F = (0.5, 0.75), O = (1, 1)
        self.assertAlmostEqual(float(rps[0]), 0.5 * (0.25 + 0.0625), places=12)

    def test_perfect_forecast_is_zero(self):
        P = np.eye(3)[[0, 1, 2]]
        ll, br, rps = T.row_losses(P, np.array([0, 1, 2]))
        self.assertTrue(np.allclose(ll, 0.0, atol=1e-6))
        self.assertTrue(np.allclose(br, 0.0, atol=1e-12))
        self.assertTrue(np.allclose(rps, 0.0, atol=1e-12))


class BootstrapTests(unittest.TestCase):
    def test_draw_counts_rows_sum_to_blocks(self):
        rng = np.random.default_rng(1)
        C = T.draw_counts(7, 50, rng)
        self.assertEqual(C.shape, (50, 7))
        self.assertTrue(np.all(C.sum(axis=1) == 7))

    def test_paired_identical_arrays_give_zero_difference(self):
        import pandas as pd
        d = pd.DataFrame({
            "league": ["A"] * 6 + ["B"] * 6,
            "season": ["2024/25"] * 12,
            "date_day": list(pd.to_datetime(["2024-08-10"] * 3 + ["2024-08-17"] * 3)) * 2,
        })
        rng = np.random.default_rng(2)
        S = T.Sample(d, 200, rng)
        x = np.linspace(0.1, 1.0, 12)
        pt, ci = S.mean_diff(x, x)
        self.assertAlmostEqual(pt, 0.0, places=12)
        self.assertTrue(ci[0] <= 0 <= ci[1])


def _sample_outcomes(P, rng):
    """Estrae un esito per riga da P (inversione della CDF), deterministico con rng."""
    u = rng.random(P.shape[0])
    return np.minimum((u[:, None] > np.cumsum(P, axis=1)).sum(axis=1), 2)


class ClogitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(20261008)
        n = 20000
        base = rng.dirichlet([4, 3, 4], size=n)
        M = rng.dirichlet([8, 5, 8], size=n) * 0.5 + base * 0.5
        M /= M.sum(axis=1, keepdims=True)
        cls.Q = base
        cls.M = M
        # verita' del processo: S = 0.5*log M + 1.0*log Q (intercette 0), esiti da softmax(S)
        S = 0.5 * np.log(M) + 1.0 * np.log(base)
        P = np.exp(S - S.max(axis=1, keepdims=True))
        P /= P.sum(axis=1, keepdims=True)
        cls.y = _sample_outcomes(P, rng)
        # per il test di alpha: esiti estratti dal solo mercato, oppure dal solo modello
        cls.y_mkt = _sample_outcomes(base, rng)
        cls.y_mod = _sample_outcomes(M, rng)

    def test_recovers_known_weights(self):
        th, _, _ = T.clogit_fit(np.log(self.M), np.log(self.Q), self.y, need_cov=False)
        # tolleranza ampia: il flag di convergenza di BFGS non e' asserito (precisione sul gradiente sommato)
        self.assertAlmostEqual(th[0], 0.5, delta=0.15)
        self.assertAlmostEqual(th[1], 1.0, delta=0.15)

    def test_mle_beats_true_parameter_in_nll(self):
        X1, X2 = np.log(self.M), np.log(self.Q)
        th, _, _ = T.clogit_fit(X1, X2, self.y, need_cov=False)

        def nll(t):
            S = t[0] * X1 + t[1] * X2 + np.array([t[2], 0.0, t[3]])[None, :]
            P = T._softmax_rows(S)
            return -np.mean(np.log(np.clip(P[np.arange(len(self.y)), self.y], 1e-12, 1)))
        self.assertLessEqual(nll(th), nll(np.array([0.5, 1.0, 0.0, 0.0])) + 1e-9)

    def test_probs_are_normalised(self):
        th = np.array([0.3, 0.8, -0.1, 0.05])
        P = T.clogit_probs(th, self.M[:100], self.Q[:100])
        self.assertTrue(np.allclose(P.sum(axis=1), 1.0, atol=1e-12))

    def test_pool_alpha_prefers_the_better_source(self):
        # esiti dal mercato: il peso del modello deve andare a ~0
        self.assertLess(T.pool_alpha(self.M, self.Q, self.y_mkt), 0.1)
        # esiti dal modello: il peso del modello deve andare a ~1
        self.assertGreater(T.pool_alpha(self.M, self.Q, self.y_mod), 0.9)


class TopMixTests(unittest.TestCase):
    def test_threshold_and_argmax(self):
        P = np.array([[0.55, 0.30, 0.15], [0.549, 0.30, 0.151], [0.20, 0.10, 0.70]])
        pick, conf, ok = T.topmix_pick(P)
        self.assertEqual(list(pick), [0, 0, 2])
        self.assertEqual(list(ok), [True, False, True])
        self.assertTrue(np.allclose(conf, [0.55, 0.549, 0.70]))


class DecisionTests(unittest.TestCase):
    """Regola di decisione (con precisazione del referto, §5)."""

    @staticmethod
    def _c(dll_pool, pool_ci, dA, dB, wA, wB):
        return {"dll_pool": dll_pool, "dll_pool_ci": pool_ci, "dll_A": dA, "dll_B": dB,
                "w_mod_ci_A": wA, "w_mod_ci_B": wB}

    def test_combinare_when_all_criteria_hold(self):
        c = self._c(-0.01, [-0.02, -0.001], -0.01, -0.005, [-0.1, 0.2], [-0.1, 0.2])
        self.assertEqual(T.decide(c), "COMBINARE")

    def test_mercato_when_weight_contains_zero_in_both_folds(self):
        c = self._c(-0.0003, [-0.004, 0.003], -0.002, 0.001, [-0.3, 0.1], [-0.2, 0.2])
        self.assertEqual(T.decide(c), "MERCATO")

    def test_mercato_when_weight_significantly_negative_in_both_folds(self):
        # caso osservato (precisazione del referto): peso negativo distinguibile da zero
        c = self._c(-0.0003, [-0.004, 0.003], -0.0026, 0.0019, [-0.63, -0.02], [-0.63, -0.19])
        self.assertEqual(T.decide(c), "MERCATO")
        self.assertFalse(any("significativamente positivo" in r for r in T.decide_reasons(c)))

    def test_no_mercato_when_weight_significantly_positive_in_one_fold(self):
        c = self._c(0.001, [0.0, 0.003], 0.001, 0.002, [0.1, 0.5], [-0.2, 0.2])
        self.assertEqual(T.decide(c), "NESSUN VERDETTO AUTOMATICO")
        self.assertTrue(any("significativamente positivo" in r for r in T.decide_reasons(c)))

    def test_alpha_on_boundary_counts_as_zero(self):
        c = self._c(3e-10, [8e-11, 6e-10], 0.0, 0.0, [4.5e-8, 4.5e-8], [4.5e-8, 4.5e-8])
        self.assertEqual(T.decide(c), "MERCATO")


if __name__ == "__main__":
    unittest.main()
