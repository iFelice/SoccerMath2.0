#!/usr/bin/env python3
"""test_bookmaker_source_test.py — Test offline di audit/bookmaker_source_test.py.

Nessuna rete, nessuna scrittura fuori da audit/: i test leggono i CSV gia'
presenti in SoccerMath/database e gli snapshot committati in audit/data.

Eseguiti dalla "Suite test completa" (workflow test_suite.yml) insieme a tutti
gli altri test tracciati.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

import numpy as np  # noqa: E402

import bookmaker_source_test as BST  # noqa: E402
from backtest_experiment_all import devig_1x2  # noqa: E402
from onex2_market_test import devig_shin3  # noqa: E402

REPS = 30
SEED = 20261008


class TestDevig(unittest.TestCase):
    """Il de-vig e' quello di produzione (PR #49), non una reimplementazione."""

    def test_proporzionale_somma_a_uno(self):
        for triple in ((2.0, 3.0, 4.0), (1.2, 9.0, 15.0), (1.5, 4.0, 6.0)):
            p = devig_1x2(*triple)
            self.assertIsNotNone(p[0])
            self.assertAlmostEqual(sum(p), 1.0, places=12)

    def test_proporzionale_rifiuta_quote_non_valide(self):
        self.assertIsNone(devig_1x2(0.9, 3.0, 4.0)[0])
        self.assertIsNone(devig_1x2(float("nan"), 3.0, 4.0)[0])

    def test_shin_somma_a_uno(self):
        p = devig_shin3(np.array([2.0, 3.0, 4.0]))
        self.assertIsNotNone(p)
        self.assertAlmostEqual(float(p.sum()), 1.0, places=9)

    def test_devig_rows_allinea_le_righe(self):
        d = BST.load_odds("SerieA", "Serie A")
        P = BST.devig_rows(d, BST.BOOKS["B365"][1])
        self.assertEqual(P.shape, (len(d), 3))
        self.assertTrue(np.isfinite(P).all())

    def test_consenso_richiede_almeno_tre_libri(self):
        d = BST.load_odds("SerieA", "Serie A")
        P, V = BST.consensus_rows(d, list(BST.BOOKS))
        validi = int(np.isfinite(P).all(axis=1).sum())
        self.assertGreater(validi, 0)
        self.assertTrue((V[np.isfinite(P).all(axis=1)] >= 3).all())


class TestCopertura(unittest.TestCase):
    """Copertura delle colonne: la commessa chiede B365, Avg, Max e Pinnacle."""

    @classmethod
    def setUpClass(cls):
        cls.d = BST.build_frame()

    def test_righe_totali_delle_due_stagioni(self):
        self.assertEqual(len(self.d), 3504)

    def test_cinque_leghe(self):
        self.assertEqual(sorted(set(self.d["league"])),
                         ["Bundesliga", "La Liga", "Ligue 1", "Premier League", "Serie A"])

    def test_b365_avg_max_coprono_tutto(self):
        d = self.d
        for k in ("B365", "Avg", "Max"):
            self.assertEqual(int(BST.valid_mask(d, k).sum()), len(d), k)

    def test_pinnacle_copre_meno_di_b365(self):
        d = self.d
        n_b365 = int(BST.valid_mask(d, "B365").sum())
        n_ps = int(BST.valid_mask(d, "PS").sum())
        self.assertLess(n_ps, n_b365)
        self.assertGreater(n_ps, 0)

    def test_base_rate_del_train_somma_a_uno(self):
        base = np.asarray([np.asarray(b, float) for b in self.d["base"]], float)
        self.assertTrue(np.isfinite(base).all())
        for riga in base:
            self.assertAlmostEqual(float(riga.sum()), 1.0, places=9)


class TestRegolaDiDecisione(unittest.TestCase):
    """La regola C1-C2-C3 e' applicata dal codice, non a mano."""

    def _payload(self, ci_ll, ci_hit, ci_gap):
        return {
            "topmix": [{"fonte": "B365", "gap_ci": [0.0, 0.0]},
                       {"fonte": "A", "gap_ci": list(ci_gap), "gap": ci_gap[0]}],
            "diffs": {"A": {"delta_logloss": ci_ll[0], "ci_logloss": list(ci_ll),
                            "delta_brier": 0.0, "ci_brier": [0.0, 0.0],
                            "delta_rps": 0.0, "ci_rps": [0.0, 0.0],
                            "hit_appaiato": {"delta": ci_hit[0], "ci": list(ci_hit),
                                             "n_intersezione": 100},
                            "resolution": {}}},
        }

    def test_tutti_e_tre_soddisfatti(self):
        v = BST.verdicts(self._payload((-0.001, 0.001), (-0.01, 0.01), (-0.02, 0.02)))
        self.assertEqual(v["A"]["esito"], "EQUIVALENTE")
        self.assertTrue(all((v["A"]["c1"], v["A"]["c2"], v["A"]["c3"])))

    def test_c1_non_soddisfatto_se_significativamente_peggiore(self):
        v = BST.verdicts(self._payload((0.002, 0.005), (-0.01, 0.01), (-0.02, 0.02)))
        self.assertEqual(v["A"]["esito"], "NON EQUIVALENTE")
        self.assertFalse(v["A"]["c1"])
        self.assertTrue(any("C1" in m for m in v["A"]["motivi"]))

    def test_c2_non_soddisfatto_se_hit_rate_peggiore(self):
        v = BST.verdicts(self._payload((-0.001, 0.001), (-0.05, -0.01), (-0.02, 0.02)))
        self.assertEqual(v["A"]["esito"], "NON EQUIVALENTE")
        self.assertFalse(v["A"]["c2"])

    def test_c3_non_soddisfatto_se_calibrazione_storta(self):
        v = BST.verdicts(self._payload((-0.001, 0.001), (-0.01, 0.01), (-0.06, -0.01)))
        self.assertEqual(v["A"]["esito"], "NON EQUIVALENTE")
        self.assertFalse(v["A"]["c3"])

    def test_motivi_generati_dal_codice(self):
        v = BST.verdicts(self._payload((0.002, 0.005), (-0.05, -0.01), (-0.06, -0.01)))
        self.assertEqual(len(v["A"]["motivi"]), 3)


class TestValutazioneCompleta(unittest.TestCase):
    """Un giro completo con poche repliche: struttura e ordini di grandezza."""

    @classmethod
    def setUpClass(cls):
        cls.payload = BST.build_payload(reps=REPS, seed=SEED)

    def test_campioni(self):
        self.assertEqual(self.payload["campioni"]["comune (B365+Avg+Max validi)"], 3504)
        self.assertEqual(self.payload["campioni"]["righe totali delle due stagioni"], 3504)
        self.assertGreater(self.payload["campioni"]["di cui con Pinnacle pre valido"], 0)

    def test_fonti_valutate(self):
        fonti = {q["fonte"] for q in self.payload["comune"]["quality"]}
        for k in ("B365", "Avg", "Max", "PS", "CONS"):
            self.assertIn(k, fonti)

    def test_logloss_nell_intorno_atteso(self):
        ll = {q["fonte"]: q["logloss"] for q in self.payload["comune"]["quality"]}
        for k, v in ll.items():
            self.assertGreater(v, 0.90, k)
            self.assertLess(v, 1.02, k)

    def test_delta_logloss_vs_b365_ridotto(self):
        for k, d in self.payload["comune"]["diffs"].items():
            self.assertLess(abs(d["delta_logloss"]), 0.01, k)

    def test_differenza_hit_rate_appaiata_su_intersezione_non_vuota(self):
        for k, d in self.payload["comune"]["diffs"].items():
            self.assertGreater(d["hit_appaiato"]["n_intersezione"], 0, k)

    def test_verdetti_presenti_per_tutte_le_fonti_alternative(self):
        self.assertIn("Avg", self.payload["verdetti"])
        self.assertIn("PS", self.payload["verdetti"])
        self.assertEqual(self.payload["verdetti"]["Avg"]["esito"], "EQUIVALENTE")
        self.assertEqual(self.payload["verdetti"]["PS"]["esito"], "EQUIVALENTE")

    def test_report_generato(self):
        md = BST.build_report(self.payload)
        self.assertIn("Quale bookmaker basta?", md)
        self.assertIn("EQUIVALENTE", md)
        for sezione in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6.", "## 7."):
            self.assertIn(sezione, md)

    def test_json_serializzabile(self):
        json.dumps(self.payload, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
