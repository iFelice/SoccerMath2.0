"""Test offline del ricalcolo senza eventi iniziati (punto A del follow-up).

Lo snapshot `audit/data/totals_probe/2026-10-10_1703/` è reale e committato:
i test di regressione sui numeri lo usano così com'è, senza rete.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import totals_probe_senza_avviati as S  # noqa: E402


class TestAvviati(unittest.TestCase):
    def test_regola_kickoff_non_successivo_alla_chiamata(self):
        eventi = [
            {"id": "a", "giorni": -0.02},   # iniziato
            {"id": "b", "giorni": 0.0},     # kickoff == chiamata: iniziato
            {"id": "c", "giorni": 0.5},
            {"id": "d", "giorni": None},    # non classificabile: NON iniziato
        ]
        avv = S.avviati(eventi)
        self.assertEqual([e["id"] for e in avv], ["a", "b"])


class TestRicalcoloSuSnapshotReale(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dati = S.calcola()

    def test_snapshot_reale_con_5_eventi_iniziati(self):
        self.assertEqual(self.dati["n_eventi_totali"], 82)
        avv = self.dati["avviati"]
        self.assertEqual(len(avv), 5)
        nomi = {(e["home"], e["away"]) for e in avv}
        self.assertIn(("Manchester United", "Tottenham Hotspur"), nomi)

    def test_pr59_senza_avviati(self):
        t = self.dati["pr59"]["tutti"]
        s = self.dati["pr59"]["senza_avviati"]
        self.assertEqual((t["n"], t["superano"], t["non_superano"]), (82, 56, 26))
        self.assertEqual((s["n"], s["superano"], s["non_superano"]), (77, 55, 22))
        self.assertLess(s["quota_superano"], 0.85)   # esito dichiarato invariato

    def test_pr60_senza_avviati(self):
        t = self.dati["pr60"]["tutti"]
        s = self.dati["pr60"]["senza_avviati"]
        self.assertEqual((t["n"], t["mediana_pp"], t["massimo_pp"])[:1], (42,))
        self.assertAlmostEqual(t["mediana_pp"], 0.64, places=2)
        self.assertAlmostEqual(t["massimo_pp"], 4.54, places=2)
        self.assertEqual(s["n"], 41)
        self.assertAlmostEqual(s["mediana_pp"], 0.54, places=2)
        self.assertAlmostEqual(s["massimo_pp"], 3.38, places=2)
        # il massimo originale era l'evento iniziato Man Utd-Tottenham
        self.assertEqual(len(self.dati["pr60"]["confrontabili_avviati"]), 1)
        c = self.dati["pr60"]["confrontabili_avviati"][0]
        self.assertEqual((c["home"], c["away"]), ("Manchester United", "Tottenham Hotspur"))


class TestReferto(unittest.TestCase):
    def test_regola_prima_dei_numeri_e_contaminazione_annotata(self):
        dati = S.calcola()
        testo = S.scrivi_referto(dati)
        self.assertTrue(testo.startswith(S.RULE_TEXT.rstrip().split("\n")[0]))
        self.assertLess(testo.index("## Regola dichiarata"), testo.index("## 1."))
        self.assertIn("non cambiano", testo)
        self.assertIn("snapshot contaminato", testo.lower())
        self.assertIn("**SÌ**", testo)
        self.assertIn("esito invariato", testo)


if __name__ == "__main__":
    unittest.main()
