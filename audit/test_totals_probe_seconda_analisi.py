"""Test offline della regola preregistrata per la seconda sonda totals."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import totals_probe_seconda_analisi as tps  # noqa: E402


class TestSecondaSondaTotals(unittest.TestCase):

    def test_senza_nuovo_snapshot_stampa_non_eseguita_e_non_scrive_numeri(self):
        with tempfile.TemporaryDirectory() as d:
            report = os.path.join(d, "seconda.md")
            output = io.StringIO()
            with mock.patch.object(tps, "discover_new_snapshot", return_value=None):
                with redirect_stdout(output):
                    self.assertEqual(tps.main(["--report", report]), 0)
            testo = output.getvalue()
            self.assertIn("seconda sonda non eseguita", testo)
            self.assertNotIn("## Risultati", testo)
            self.assertFalse(os.path.exists(report))
            self.assertTrue(testo.startswith(tps.RULE_TEXT.split("\n\n")[0]))

    def test_snapshot_del_10_10_escluso_dalla_scoperta(self):
        with tempfile.TemporaryDirectory() as d:
            baseline = os.path.join(d, tps.BASELINE_SNAPSHOT_NAME)
            os.makedirs(baseline)
            with open(os.path.join(baseline, "_summary.json"), "w", encoding="utf-8") as fh:
                json.dump({"generato_il": "2026-10-10T17:03:43Z"}, fh)
            self.assertIsNone(tps.discover_new_snapshot(d))

    def test_finestra_esclude_eventi_gia_iniziati_e_oltre_7_giorni(self):
        fetched = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
        def ev(hours):
            return {"fetched_at": fetched, "commence_time": fetched + timedelta(hours=hours)}
        self.assertTrue(tps.in_window(ev(0)))
        self.assertTrue(tps.in_window(ev(168)))
        self.assertFalse(tps.in_window(ev(-1)))
        self.assertFalse(tps.in_window(ev(169)))

    def test_quote_linea_deve_avere_due_quote_valide(self):
        event = {"bookmakers": [{"key": "pinnacle", "last_update": "2026-10-10T12:00:00Z",
                                 "markets": [{"key": "totals", "outcomes": [
                                     {"name": "Over", "point": 2.25, "price": 1.91},
                                     {"name": "Under", "point": 2.25, "price": 1.97},
                                     {"name": "Over", "point": 2.5, "price": 1.0},
                                     {"name": "Under", "point": 2.5, "price": 2.0}]}]}]}
        lines = tps.extract_book_lines(event)
        self.assertEqual(list(lines["pinnacle"]), [2.25])
        self.assertEqual(lines["pinnacle"][2.25]["last_update"], "2026-10-10T12:00:00Z")
        self.assertEqual(tps.selected_line(lines["pinnacle"])[0], 2.25)

    def test_regola_b_non_decidibile_con_meno_di_20_eventi(self):
        events = [{"book_lines": {"pinnacle": {2.25: {}}}} for _ in range(19)]
        comparisons = [{"diff_pp": 0.5} for _ in range(19)]
        result = tps.decision(events, comparisons)
        self.assertTrue(result["coverage_pass"])
        self.assertEqual(result["concordance_status"], "NON DECIDIBILE")
        self.assertFalse(result["production_proposable"])
        self.assertIsNone(result["median_diff_pp"])
        self.assertIsNone(result["p90_diff_pp"])

    def test_regole_a_b_e_c_passano_solo_con_soglie_e_n_rispettati(self):
        events = [{"book_lines": {"pinnacle": {2.25: {}}}} for _ in range(20)]
        comparisons = [{"diff_pp": 1.0} for _ in range(20)]
        result = tps.decision(events, comparisons)
        self.assertEqual(result["coverage"], 1.0)
        self.assertTrue(result["coverage_pass"])
        self.assertEqual(result["median_diff_pp"], 1.0)
        self.assertEqual(result["p90_diff_pp"], 1.0)
        self.assertTrue(result["concordance_pass"])
        self.assertTrue(result["production_proposable"])

        for comparison in comparisons[:3]:
            comparison["diff_pp"] = 4.0
        result = tps.decision(events, comparisons)
        self.assertFalse(result["concordance_pass"])
        self.assertFalse(result["production_proposable"])

    def test_referto_comincia_con_regola_preregistrata(self):
        stats = tps.decision([], [])
        report = tps.build_report("new_snapshot", None, None, stats, [], 0)
        self.assertTrue(report.startswith(tps.RULE_TEXT.rstrip()))
        self.assertIn("### (a) Copertura", report)
        self.assertIn("### (b) Concordanza", report)
        self.assertIn("### (c) Proponibilità", report)


if __name__ == "__main__":
    unittest.main()
