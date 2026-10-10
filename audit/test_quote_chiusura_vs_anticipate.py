"""Test offline e deterministici per audit/quote_chiusura_vs_anticipate.py.

Nessun dato esterno: tutto su valori sintetici o con risultato noto a mano.
Eseguibile con pytest o direttamente: python audit/test_quote_chiusura_vs_anticipate.py
"""
import os
import sys
import unittest

import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import quote_chiusura_vs_anticipate as T  # noqa: E402


def _df(odds_rows, cols):
    """DataFrame sintetico con le colonne di quote date (tutte le altre NaN)."""
    data = {c: np.full(len(odds_rows), np.nan) for c in T.ALL_ODDS_COLS}
    for j, c in enumerate(cols):
        data[c] = [row[j] for row in odds_rows]
    return pd.DataFrame(data)


class DevigTests(unittest.TestCase):
    def test_prop_sums_to_one_and_is_proportional(self):
        p = T.devig_prop(np.array([2.0, 4.0, 4.0]))  # 1/o = 0.5, 0.25, 0.25
        self.assertTrue(np.allclose(p, [0.5, 0.25, 0.25], atol=1e-12))
        o2 = np.array([1.90, 3.40, 4.20])  # con overround
        p2 = T.devig_prop(o2)
        self.assertAlmostEqual(float(p2.sum()), 1.0, places=12)
        self.assertTrue(np.allclose(p2, (1 / o2) / (1 / o2).sum(), atol=1e-12))

    def test_invalid_odds_return_none(self):
        self.assertIsNone(T.devig_prop(np.array([1.0, 3.0, 4.0])))
        self.assertIsNone(T.devig_prop(np.array([np.nan, 3.0, 4.0])))
        self.assertIsNone(T.devig_prop(np.array([2.0, -1.0, 4.0])))

    def test_probs_from_tern_marks_invalid_rows_nan(self):
        df = _df([[2.0, 4.0, 4.0], [1.0, 3.0, 4.0], [2.0, np.nan, 4.0]],
                 ("B365H", "B365D", "B365A"))
        P = T.probs_from_tern(df, T.PRE_B365)
        self.assertTrue(np.all(np.isfinite(P[0])))
        self.assertTrue(np.all(np.isnan(P[1])))
        self.assertTrue(np.all(np.isnan(P[2])))


class MetricTests(unittest.TestCase):
    def test_brier_hand_case(self):
        P = np.array([[0.5, 0.25, 0.25]])
        y = np.array([0])
        self.assertAlmostEqual(float(T.brier_1x2(P, y)[0]), 0.25 + 0.0625 + 0.0625, places=12)

    def test_brier_perfect_is_zero(self):
        P = np.eye(3)[[0, 1, 2]]
        self.assertTrue(np.allclose(T.brier_1x2(P, np.array([0, 1, 2])), 0.0))

    def test_logloss_hand_case_and_clip(self):
        P = np.array([[0.5, 0.25, 0.25]])
        self.assertAlmostEqual(float(T.logloss_each(P, np.array([0]))[0]), -np.log(0.5), places=12)
        # p = 0 sull'esito: clip a 1e-9, valore finito
        P0 = np.array([[0.0, 0.5, 0.5]])
        self.assertAlmostEqual(float(T.logloss_each(P0, np.array([0]))[0]), -np.log(1e-9), places=9)


class DecideTests(unittest.TestCase):
    def test_ic_favore_chiusura(self):
        self.assertEqual(T.decide((-0.003, -0.0005)), "piu_informativa")

    def test_ic_che_contiene_zero(self):
        self.assertEqual(T.decide((-0.003, 0.0004)), "nessuna_differenza_dimostrata")

    def test_ic_favore_anticipata(self):
        # regola dichiarata: 'piu informativa' solo se a favore della chiusura
        self.assertEqual(T.decide((0.0005, 0.003)), "nessuna_differenza_dimostrata")


class TopMixTests(unittest.TestCase):
    def test_hand_case(self):
        P = np.array([[0.60, 0.20, 0.20],
                      [0.54, 0.30, 0.16],   # sotto soglia 0.55: non ammessa
                      [0.55, 0.25, 0.20],
                      [0.30, 0.56, 0.14]])
        y = np.array([0, 1, 2, 1])
        st = T.topmix_stats(P, y)
        self.assertEqual(st["n"], 4)
        self.assertEqual(st["ammesse"], 3)  # 2a riga esclusa
        # favorite ammesse: riga 0 (H, vinta), riga 2 (X? no: argmax=H, persa), riga 3 (X, vinta)
        self.assertAlmostEqual(st["hit_rate"], 2 / 3, places=12)
        self.assertAlmostEqual(st["confidenza_media"], (0.60 + 0.55 + 0.56) / 3, places=12)

    def test_no_admitted(self):
        P = np.array([[0.54, 0.30, 0.16]])
        st = T.topmix_stats(P, np.array([0]))
        self.assertEqual(st["ammesse"], 0)
        self.assertIsNone(st["hit_rate"])
        self.assertIsNone(st["confidenza_media"])

    def test_topmix_ic_degenerate_confidence(self):
        P = np.array([[0.60, 0.20, 0.20], [0.60, 0.20, 0.20], [0.60, 0.20, 0.20]])
        y = np.array([0, 1, 0])
        blocks = np.array(["a", "a", "b"])
        ic = T.topmix_ic(P, y, blocks, reps=50, seed=1)
        self.assertAlmostEqual(ic["confidenza_ic95"][0], 0.6, places=9)
        self.assertAlmostEqual(ic["confidenza_ic95"][1], 0.6, places=9)
        self.assertLessEqual(ic["hit_rate_ic95"][0], 2 / 3)
        self.assertGreaterEqual(ic["hit_rate_ic95"][1], 2 / 3)
        self.assertIsNotNone(ic)

    def test_topmix_ic_none_when_empty(self):
        P = np.array([[0.54, 0.30, 0.16]])
        self.assertIsNone(T.topmix_ic(P, np.array([0]), np.array(["a"]), reps=10, seed=1))


class BandTests(unittest.TestCase):
    def _band_of(self, delta):
        for label, lo, hi, lo_inc, hi_inc in T.BANDS:
            if ((delta > lo) | (lo_inc & (delta == lo))) and ((delta < hi) | (hi_inc & (delta == hi))):
                return label.split(":")[0]
        return None

    def test_band_membership_at_boundaries(self):
        cases = {
            -6.0: "F1", -5.0: "F1", -5.01: "F1", -2.5: "F2", -2.0: "F2",
            -1.999: "F3", 0.0: "F3", 1.999: "F3", 2.0: "F4", 4.999: "F4",
            5.0: "F5", 6.0: "F5",
        }
        for d, want in cases.items():
            self.assertEqual(self._band_of(d), want, f"delta={d}")

    def test_bands_partition_all_reals(self):
        ds = np.linspace(-15, 15, 10001)
        counts = np.zeros(len(T.BANDS))
        for d in ds:
            for i, (label, lo, hi, lo_inc, hi_inc) in enumerate(T.BANDS):
                if ((d > lo) | (lo_inc & (d == lo))) and ((d < hi) | (hi_inc & (d == hi))):
                    counts[i] += 1
                    break
        self.assertEqual(counts.sum(), len(ds))


class MovementTests(unittest.TestCase):
    def test_hand_case(self):
        Pa = np.array([[0.60, 0.20, 0.20], [0.55, 0.25, 0.20]])
        Pb = np.array([[0.65, 0.20, 0.15], [0.50, 0.30, 0.20]])
        y = np.array([0, 1])
        m = T.movement(Pa, Pb, y)
        self.assertAlmostEqual(m["distribuzione"]["media"], 0.0, places=12)  # +5 e -5
        self.assertEqual(m["distribuzione"]["share_ge5"], 1.0)
        self.assertAlmostEqual(m["hit_favorito_totale"], 0.5, places=12)
        f1, f5 = m["fasce"]["F1: Delta <= -5"], m["fasce"]["F5: Delta >= +5"]
        self.assertEqual(f1["n"], 1)
        self.assertEqual(f5["n"], 1)
        self.assertAlmostEqual(f1["hit_rate"], 0.0, places=12)
        self.assertAlmostEqual(f1["prob_media_anticipata"], 0.55, places=12)
        self.assertAlmostEqual(f1["prob_media_chiusura"], 0.50, places=12)
        self.assertAlmostEqual(f5["hit_rate"], 1.0, places=12)
        self.assertAlmostEqual(f5["hit_minus_anticipata"], 0.40, places=12)
        acc = m["aggregati"]["accorcia_ge+2"]
        allu = m["aggregati"]["allunga_le-2"]
        self.assertEqual(acc["n"], 1)
        self.assertEqual(allu["n"], 1)
        self.assertAlmostEqual(acc["hit_rate"], 1.0, places=12)
        self.assertAlmostEqual(allu["prob_media_chiusura"], 0.50, places=12)


class BootstrapTests(unittest.TestCase):
    def _data(self):
        n = 12
        rng = np.random.default_rng(0)
        y = rng.integers(0, 3, n)
        Pa = np.tile(np.array([0.5, 0.25, 0.25]), (n, 1))
        Pb = np.full((n, 3), 0.225)  # probabilita' valide (somma 1),
        Pb[np.arange(n), y] = 0.55   # la chiusura e' SEMPRE migliore riga per riga
        blocks = np.array(["L1|s1|d%d" % (i % 4) for i in range(n)])  # 4 blocchi x 3 righe
        return Pa, Pb, y, blocks

    def test_identical_probs_give_zero_everywhere(self):
        Pa, _, y, blocks = self._data()
        r = T.diff_brier_ic(Pa, Pa, y, blocks, reps=200, seed=42)
        self.assertAlmostEqual(r["point"], 0.0, places=12)
        # d identicamente zero: IC degenere a zero
        self.assertAlmostEqual(r["ic95"][0], 0.0, places=12)
        self.assertAlmostEqual(r["ic95"][1], 0.0, places=12)

    def test_strictly_better_chiusura_gives_all_negative_ic(self):
        Pa, Pb, y, blocks = self._data()
        r = T.diff_brier_ic(Pa, Pb, y, blocks, reps=200, seed=42)
        self.assertLess(r["point"], 0.0)
        self.assertLess(r["ic95"][1], 0.0)
        self.assertEqual(T.decide(r["ic95"]), "piu_informativa")

    def test_determinism_with_same_seed(self):
        Pa, Pb, y, blocks = self._data()
        r1 = T.diff_brier_ic(Pa, Pb, y, blocks, reps=200, seed=7)
        r2 = T.diff_brier_ic(Pa, Pb, y, blocks, reps=200, seed=7)
        self.assertAlmostEqual(r1["point"], r2["point"], places=15)
        self.assertAlmostEqual(r1["ic95"][0], r2["ic95"][0], places=15)
        self.assertAlmostEqual(r1["ic95"][1], r2["ic95"][1], places=15)

    def test_subset_empty_returns_none(self):
        Pa, Pb, y, blocks = self._data()
        r = T.diff_brier_ic(Pa, Pb, y, blocks, reps=10, seed=1,
                            subset=np.zeros(len(Pa), dtype=bool))
        self.assertIsNone(r)

    def test_block_bootstrap_preserves_block_counts(self):
        n = 10
        blocks = np.array(["a"] * 4 + ["b"] * 3 + ["c"] * 3)
        arr = np.ones(n)
        sizes = {"a": 4, "b": 3, "c": 3}
        n_blocks = 3  # blocchi estratti con reimmissione (come nel bootstrap di PR #34/#49)
        sels = T.block_bootstrap_block(arr, blocks, reps=25, seed=3)
        self.assertEqual(len(sels), 25)
        for sel in sels:
            # la taglia del repliche varia: somma delle cardinalita' dei blocchi estratti
            self.assertGreaterEqual(len(sel), min(sizes.values()) * n_blocks)
            self.assertLessEqual(len(sel), max(sizes.values()) * n_blocks)
            # il conteggio di un blocco nel repliche = sua cardinalita' x volte estratto
            counts = pd.Series(blocks[sel]).value_counts()
            for b, cnt in counts.items():
                self.assertEqual(cnt % sizes[b], 0)
                self.assertLessEqual(cnt, sizes[b] * n_blocks)  # al massimo estratto n_blocks volte


if __name__ == "__main__":
    unittest.main(verbosity=2)
