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


class TestSorgenteFixture(unittest.TestCase):
    """Le righe del Registro vivo hanno i match_id dell'API.

    Con le fixture dei CSV (id sintetici) ogni partita risulta "non trovata" e la
    diagnosi non misura nulla: e' successo davvero in CI, con 19 righe tutte
    dichiarate non diagnosticabili per lo stesso motivo sbagliato.
    """

    def test_fixtures_api_chiama_lapi(self):
        import io
        import json
        import tempfile
        import contextlib
        from unittest import mock

        cov = {"solo": {"current": [{"partita": "Inter - Milan", "campionato": "Serie A",
                                     "kickoff_utc": "2026-09-10T18:00:00Z", "match_id": 123,
                                     "mercato": "1", "prob": 70.0}], "legacy": []}}
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(cov, f)
        f.close()
        self.addCleanup(os.unlink, f.name)

        chiamate = {}

        def finti_api(api_key, leghe, **kw):
            chiamate["api"] = (api_key, list(leghe))
            return {}

        def finti_csv(leghe, **kw):
            chiamate["csv"] = list(leghe)
            return {}

        with mock.patch.object(diag.replay, "fixtures_from_api", finti_api), \
             mock.patch.object(diag.replay, "fixtures_from_csv_and_archive", finti_csv):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                diag.main(["--dump", f.name, "--coverage", f.name, "--fixtures", "api"])
            self.assertIn("api", chiamate)
            self.assertNotIn("csv", chiamate)
            out2 = io.StringIO()
            with contextlib.redirect_stdout(out2):
                diag.main(["--dump", f.name, "--coverage", f.name])
            self.assertIn("csv", chiamate)
