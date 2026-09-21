"""Test dell'istante di kickoff usato dalla diagnosi.

Il caso vero, trovato in CI: le righe STORICHE del Registro non hanno
``kickoff_utc`` (il campo non esisteva) e la diagnosi si fermava su ognuna.
Ora l'istante si deduce dalla data italiana e lo si DICHIARA nel referto; se non
c'e' neppure la data, la riga si ferma con un errore parlante.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "SoccerMath"))

_spec = importlib.util.spec_from_file_location(
    "diagnose_scarti_model_variant", os.path.join(HERE, "diagnose_scarti_model_variant.py"))
diag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diag)


class TestKickoff(unittest.TestCase):
    def test_kickoff_utc_e_la_fonte_autorevole(self):
        ko = diag._kickoff({"kickoff_utc": "2026-09-10T18:00:00Z", "data": "10/09/2026 23:59"})
        self.assertEqual(datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc), ko)

    def test_riga_storica_dedotta_dalla_data_italiana(self):
        ko = diag._kickoff({"data": "18/09/2026 20:45"})
        self.assertEqual(datetime(2026, 9, 18, 18, 45, tzinfo=timezone.utc), ko,
                         "20:45 a Roma = 18:45 UTC (ora legale)")

    def test_riga_senza_ne_kickoff_ne_data(self):
        with self.assertRaises(SystemExit):
            diag._kickoff({"data": ""})


if __name__ == "__main__":
    unittest.main()
