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
        # Regola della produzione 1X2: commence_time <= istante della chiamata
        # e' una partita GIA' INIZIATA e viene esclusa (anche a parita' di istante).
        fetched = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
        def ev(hours):
            return {"fetched_at": fetched, "commence_time": fetched + timedelta(hours=hours)}
        self.assertFalse(tps.in_window(ev(0)))
        self.assertTrue(tps.in_window(ev(1)))
        self.assertTrue(tps.in_window(ev(168)))
        self.assertFalse(tps.in_window(ev(-1)))
        self.assertFalse(tps.in_window(ev(169)))

    def test_eventi_iniziati_classifica_solo_kickoff_non_successivo(self):
        fetched = datetime(2026, 10, 10, 17, 3, 43, tzinfo=timezone.utc)
        avviato = {"commence_time": fetched - timedelta(seconds=1), "fetched_at": fetched}
        in_corso_esatto = {"commence_time": fetched, "fetched_at": fetched}
        futuro = {"commence_time": fetched + timedelta(minutes=1), "fetched_at": fetched}
        senza_ora = {"commence_time": None, "fetched_at": fetched}
        lista = [avviato, in_corso_esatto, futuro, senza_ora]
        iniziati = tps.eventi_iniziati(lista)
        self.assertEqual(iniziati, [avviato, in_corso_esatto])
        # commence_time assente/corrotto: come in produzione NON viene classificato
        self.assertNotIn(senza_ora, iniziati)

    def test_regressione_risposta_reale_10_10_con_evento_iniziato(self):
        # Risposta GREZZA reale del 10/10: audit/data/totals_probe/2026-10-10_1703/
        # contiene Manchester United - Tottenham Hotspur con kickoff 16:30Z,
        # precedente alla chiamata delle 17:03:43Z (contaminazione segnalata nella
        # PR #61). L'evento deve risultare iniziato, fuori finestra, escluso.
        snapshot = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                                "totals_probe", "2026-10-10_1703")
        self.assertTrue(os.path.isdir(snapshot), "snapshot reale 10/10 assente")
        events, _call = tps.load_snapshot(snapshot)
        epl = [e for e in events if e.get("league") == "Premier League"]
        self.assertTrue(epl, "risposta soccer_epl.json non caricata")
        united = [e for e in epl if e.get("home") == "Manchester United"
                  and e.get("away") == "Tottenham Hotspur"]
        self.assertEqual(len(united), 1)
        ev = united[0]
        self.assertEqual(ev["commence_time"],
                         datetime(2026, 10, 10, 16, 30, tzinfo=timezone.utc))
        self.assertEqual(ev["fetched_at"],
                         datetime(2026, 10, 10, 17, 3, 43, tzinfo=timezone.utc))
        # 1) classificato come iniziato dalla regola di produzione
        self.assertIn(ev, tps.eventi_iniziati(epl))
        self.assertEqual(len(tps.eventi_iniziati(epl)), 1)
        # 2) fuori dalla finestra della regola (a)(b)(c): non entra negli eligible
        self.assertFalse(tps.in_window(ev))
        eligible = [e for e in events if tps.in_window(e)]
        self.assertNotIn(ev, eligible)
        self.assertTrue(all(not (e.get("league") == "Premier League"
                                 and e.get("home") == "Manchester United")
                            for e in eligible))
        # 3) il referto riporta quanti eventi sono stati esclusi per questo motivo
        stats = tps.decision(eligible, [])
        stats["n_iniziati_esclusi"] = len(tps.eventi_iniziati(events))
        report = tps.build_report(snapshot, None, None, stats, [], 0)
        self.assertIn("Eventi già iniziati alla chiamata", report)
        self.assertIn(f"**{len(tps.eventi_iniziati(events))}**", report)

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
