"""Test della sonda totals (audit): nessuna chiamata di rete, nessuna chiave su disco."""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import totals_probe as tp  # noqa: E402
import totals_probe_analysis as tpa  # noqa: E402

SECRET = "SEGRETO123456789"


def _ev(eid, books):
    """books: lista (key, point) per il mercato totals."""
    bks = []
    for key, point in books:
        bks.append({"key": key, "markets": [{"key": "totals", "outcomes": [
            {"name": "Over", "price": 1.9, "point": point},
            {"name": "Under", "price": 1.9, "point": point}]}]})
    return {"id": eid, "bookmakers": bks}


class TestTotalsProbe(unittest.TestCase):

    def test_bucket_linee(self):
        self.assertEqual(tpa.bucket_of(2.5), "2,5")
        self.assertEqual(tpa.bucket_of(2.25), "2,25")
        self.assertEqual(tpa.bucket_of(2.75), "2,75")
        self.assertEqual(tpa.bucket_of(3.0), "altre")
        self.assertEqual(tpa.bucket_of(None), "altre")

    def test_event_lines_e_pinnacle(self):
        ev = _ev("a", [("pinnacle", 2.5), ("bet365", 2.25)])
        lines = tpa.event_lines(ev)
        self.assertEqual(lines, {"pinnacle": 2.5, "bet365": 2.25})

    def test_analisi_conteggi_su_snapshot_sintetici(self):
        snaps = [
            ("soccer_epl.json", {"lega": "Premier League", "sport_key": "soccer_epl", "status": 200,
                                 "ok": True, "error": None,
                                 "headers": {"x-requests-last": "1", "x-requests-used": "5",
                                             "x-requests-remaining": "495"},
                                 "body": [_ev("1", [("pinnacle", 2.5), ("bet365", 2.5)]),
                                          _ev("2", [("bet365", 2.25)]),
                                          _ev("3", [("pinnacle", 3.0)])]}),
        ]
        r = tpa.analyse(snaps)
        self.assertEqual(r["eventi_totali"], 3)
        self.assertEqual(r["eventi_con_pinnacle"], 2)
        self.assertEqual(r["eventi_con_2_5"], 1)
        self.assertEqual(r["eventi_con_2_5_pinnacle"], 1)
        self.assertEqual(r["eventi_solo_asiatiche"], 1)
        self.assertEqual(r["per_bookmaker"]["bet365"]["2,25"], 1)
        self.assertEqual(r["crediti"]["soccer_epl"], "1")
        md = tpa.build_md(r, "2026-10-10T00:00:00Z", 1)
        self.assertIn("Crediti spesi: 1", md)

    def test_il_referto_senza_snapshot_dichiara_non_eseguita(self):
        md = tpa.build_md(tpa.analyse([]), "x", 0)
        self.assertIn("NON ESEGUITA", md)

    def test_nessuna_chiave_nei_file_salvati(self):
        env = tp.envelope("soccer_epl", "Premier League",
                          {"url_masked": tp.build_url("soccer_epl", "***"), "status": 200,
                           "ok": True, "headers": {"x-requests-last": "1"}},
                          [_ev("1", [("pinnacle", 2.5)])])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "soccer_epl.json")
            tp.write_json(path, env)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn(SECRET, text)
            self.assertIn("apiKey=***", text)
            self.assertEqual(json.loads(text)["mercato"], "totals")

    def test_rifiuta_di_scrivere_una_chiave_reale(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):
                tp.write_json(os.path.join(d, "x.json"), {"u": f"https://x/?apiKey={SECRET}"})

    def test_senza_chiave_esce_3_senza_chiamare_la_rete(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ODDS_API_KEY", None)
            with mock.patch.object(tp, "_http") as h:
                self.assertEqual(tp.main(["--out", tempfile.mkdtemp()]), 3)
                h.assert_not_called()

    def test_url_contiene_markets_totals_e_regions_eu(self):
        u = tp.build_url("soccer_epl", "K")
        self.assertIn("markets=totals", u)
        self.assertIn("regions=eu", u)
        self.assertIn("soccer_epl/odds", u)


if __name__ == "__main__":
    unittest.main()
