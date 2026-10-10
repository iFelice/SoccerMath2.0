"""Test unitari di audit/griglia_core.py (griglia implicita, audit di sola lettura)."""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import griglia_core as gc  # noqa: E402


class TestGrigliaCore(unittest.TestCase):

    def test_devig_proporzionale_somma_uno(self):
        p = gc.devig_prop([2.0, 3.5, 4.0])
        self.assertAlmostEqual(float(p.sum()), 1.0, places=12)
        self.assertIsNone(gc.devig_prop([1.0, 3.0, 3.0]))   # quota non valida
        self.assertIsNone(gc.devig_prop([np.nan, 3.0, 3.0]))

    def test_dc_normalizzata_e_convenzione_di_produzione(self):
        from scipy.stats import poisson
        lam, mu, rho = 1.5, 1.2, -0.1
        m = gc.dc_matrix(lam, mu, rho)
        self.assertAlmostEqual(float(m.sum()), 1.0, places=12)
        raw = np.outer(poisson.pmf(gc.GOALS, lam), poisson.pmf(gc.GOALS, mu))
        # convenzione DC/produzione: (0,1) *= 1 + lam*rho ; (1,0) *= 1 + mu*rho
        ref = raw.copy()
        ref[0, 0] *= 1 - lam * mu * rho
        ref[0, 1] *= 1 + lam * rho
        ref[1, 0] *= 1 + mu * rho
        ref[1, 1] *= 1 - rho
        ref /= ref.sum()
        np.testing.assert_allclose(m, ref, rtol=0, atol=1e-15)

    def test_fit_recupera_parametri_noti(self):
        g = gc.dc_matrix(1.7, 0.9, -0.08)
        p = gc.grid_1x2_ou(g)
        f = gc.fit_implicit(*p, rho_free=True)
        self.assertLess(f["max_abs_resid"], 1e-9)
        self.assertAlmostEqual(f["lam"], 1.7, places=5)
        self.assertAlmostEqual(f["mu"], 0.9, places=5)
        self.assertAlmostEqual(f["rho"], -0.08, places=5)

    def test_mercati_complementari_hanno_stesso_valore(self):
        g = gc.dc_matrix(1.4, 1.1, -0.05)
        pm = gc.grid_markets(g)
        idx = {n: i for i, n in enumerate(gc.MARKET_NAMES)}
        self.assertAlmostEqual(pm[idx["1X"]] + pm[idx["2"]], 1.0, places=12)
        self.assertAlmostEqual(pm[idx["Over 2.5"]] + pm[idx["Under 2.5"]], 1.0, places=12)
        self.assertAlmostEqual(pm[idx["Gol"]] + pm[idx["No Gol"]], 1.0, places=12)
        self.assertLessEqual(pm[idx["1+Gol"]], pm[idx["1"]] + 1e-15)   # combinazione <= evento base

    def test_esiti_reali(self):
        Y = gc.outcome_matrix(np.array([2]), np.array([1]))   # 2-1
        idx = {n: i for i, n in enumerate(gc.MARKET_NAMES)}
        self.assertEqual(Y[0, idx["1"]], 1)
        self.assertEqual(Y[0, idx["1X"]], 1)
        self.assertEqual(Y[0, idx["Over 2.5"]], 1)
        self.assertEqual(Y[0, idx["Gol"]], 1)
        self.assertEqual(Y[0, idx["1+Gol"]], 1)
        self.assertEqual(Y[0, idx["X"]], 0)
        self.assertEqual(Y[0, idx["No Gol"]], 0)

    def test_regola_di_decisione(self):
        self.assertEqual(gc.decide_replace(0.001, 0.02), "SOSTITUISCE (griglia implicita)")
        self.assertEqual(gc.decide_replace(-0.01, 0.02), "nessuna differenza dimostrata")
        self.assertEqual(gc.decide_replace(-0.03, -0.001), "NO: modello migliore (dimostrato)")

    def test_bootstrap_ic_contiene_la_media(self):
        rng = np.random.default_rng(1)
        d = rng.normal(0.01, 0.05, size=600)
        blocks = np.repeat(np.arange(60), 10)
        r = gc.block_bootstrap_mean_diff(d, blocks, 500, rng)
        self.assertLessEqual(r["lo"], r["mean"])
        self.assertGreaterEqual(r["hi"], r["mean"])
        self.assertEqual(r["n_blocchi"], 60)

    def test_calibrazione_fasce(self):
        p = np.array([0.55, 0.65, 0.95, 0.95])
        y = np.array([1, 0, 1, 1])
        rows = gc.calibration_rows(p, y, gc.BANDS)
        counts = {r["fascia"]: r["n"] for r in rows}
        self.assertEqual(counts["0,50-0,60"], 1)
        self.assertEqual(counts["0,60-0,70"], 1)
        self.assertEqual(counts["≥0,90"], 2)
        top = [r for r in rows if r["fascia"] == "≥0,90"][0]
        self.assertAlmostEqual(top["freq_osservata"], 1.0)


if __name__ == "__main__":
    unittest.main()
