#!/usr/bin/env python3
"""test_live_odds_probe.py — Test offline dello script di probe e degli snapshot committati.

Lo script `audit/live_odds_probe.py` ha bisogno della rete (bloccata nella
sandbox) e della chiave: qui si verifica che (a) la logica locale sia corretta
(mascheramento della chiave, compattamento del payload, conteggio dei bookmaker)
e (b) gli snapshot committati in `audit/data/live_odds_probe/` abbiano la forma
attesa e NON contengano la chiave API.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)

import live_odds_probe as LOP  # noqa: E402

DATA_DIR = LOP.DATA_DIR
SPORT_KEYS = [k for _l, k in LOP.LEAGUES]


def _carica(nome):
    with open(os.path.join(DATA_DIR, nome), encoding="utf-8") as fh:
        return json.load(fh)


class TestSicurezza(unittest.TestCase):
    """La chiave non deve mai finire nei file committati ne' negli URL registrati."""

    def test_maschera_la_chiave(self):
        url = "https://api.the-odds-api.com/v4/sports/?apiKey=SEGRETO123"
        self.assertNotIn("SEGRETO123", LOP._mask(url, "SEGRETO123"))
        self.assertIn("apiKey=***", LOP._mask(url, "SEGRETO123"))

    def test_nessuna_chiave_negli_snapshot(self):
        for nome in sorted(os.listdir(DATA_DIR)):
            if not nome.endswith(".json"):
                continue
            testo = open(os.path.join(DATA_DIR, nome), encoding="utf-8").read()
            self.assertNotIn("apiKey=", testo.replace("apiKey=***", ""), nome)

    def test_url_registrati_sono_tutti_mascherati(self):
        s = _carica("probe_summary.json")
        for c in s["calls"]:
            self.assertIn("apiKey=***", c["url_masked"])
        for k in ("controllo_bet365", "controllo_una_regione"):
            if s.get(k):
                self.assertIn("apiKey=***", s[k]["url_masked"])


class TestCompattamento(unittest.TestCase):
    def test_compact_events_estrae_h2h(self):
        payload = [{
            "id": "x1", "sport_key": "soccer_epl",
            "commence_time": "2026-10-10T11:30:00Z",
            "home_team": "Arsenal", "away_team": "Leeds",
            "bookmakers": [{"key": "pinnacle", "title": "Pinnacle",
                            "last_update": "2026-10-08T23:00:00Z",
                            "markets": [{"key": "h2h", "outcomes": [
                                {"name": "Arsenal", "price": 1.5},
                                {"name": "Draw", "price": 4.0},
                                {"name": "Leeds", "price": 7.0}]}]}],
        }]
        ev = LOP.compact_events(payload, "soccer_epl")
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["bookmakers"][0]["h2h"],
                         {"home": 1.5, "draw": 4.0, "away": 7.0})

    def test_bookmaker_coverage_conta(self):
        eventi = [{"bookmakers": [
            {"key": "pinnacle", "title": "Pinnacle", "last_update": "2026-10-08T23:00:00Z",
             "h2h": {"home": 1.5, "draw": 4.0, "away": 7.0}},
            {"key": "betway", "title": "Betway", "last_update": "2026-10-08T22:00:00Z",
             "h2h": {"home": 1.4, "draw": None, "away": 6.0}}]},
            {"bookmakers": [
                {"key": "pinnacle", "title": "Pinnacle", "last_update": "2026-10-08T23:10:00Z",
                 "h2h": {"home": 2.0, "draw": 3.0, "away": 4.0}}]}]
        cov = LOP.bookmaker_coverage(eventi)
        self.assertEqual(cov["pinnacle"]["n_events"], 2)
        self.assertEqual(cov["pinnacle"]["h2h_completo"], 2)
        self.assertEqual(cov["betway"]["h2h_completo"], 0)
        self.assertEqual(cov["pinnacle"]["last_update_min"], "2026-10-08T23:00:00Z")
        self.assertEqual(cov["pinnacle"]["last_update_max"], "2026-10-08T23:10:00Z")


class TestSnapshot(unittest.TestCase):
    """Gli snapshot committati: forma e contenuto minimo atteso."""

    @classmethod
    def setUpClass(cls):
        cls.s = _carica("probe_summary.json")

    def test_chiave_dichiarata_presente(self):
        self.assertEqual(self.s["chiave_presente_nel_repository"], "true")

    def test_cinque_leghe_tutte_ok(self):
        leghe = self.s["odds_api"]["leagues"]
        self.assertEqual(len(leghe), 5)
        for lega, v in leghe.items():
            self.assertTrue(v["ok"], lega)
            self.assertTrue(v["presente_in_sports"], lega)
            self.assertEqual(v["status"] if "status" in v else 200, 200)
            self.assertGreater(v["n_eventi"], 0, lega)
            self.assertGreater(v["n_bookmaker"], 0, lega)
            self.assertEqual(v["crediti_header"]["x-requests-last"], "2", lega)

    def test_bet365_assente_pinnacle_presente(self):
        for lega, v in self.s["odds_api"]["leagues"].items():
            self.assertFalse(v["bet365_presente"], lega)
            self.assertTrue(v["pinnacle_presente"], lega)

    def test_controllo_bet365_esplicito(self):
        c = self.s["controllo_bet365"]
        self.assertEqual(c["status"], 200)
        self.assertEqual(c["bookmakers_restituiti"], [])
        self.assertFalse(c["bet365_presente"])
        self.assertEqual(c["crediti"]["x-requests-last"], "1")

    def test_controllo_una_regione_costa_un_credito(self):
        c = self.s["controllo_una_regione"]
        self.assertEqual(c["status"], 200)
        self.assertEqual(c["crediti"]["x-requests-last"], "1")
        self.assertTrue(c["pinnacle_presente"])

    def test_payload_per_lega(self):
        for key in SPORT_KEYS:
            d = _carica(f"odds_api_{key}.json")
            self.assertEqual(d["sport_key"], key)
            self.assertGreater(d["n_eventi"], 0)
            self.assertTrue(d["bookmakers"])
            for ev in d["events"]:
                self.assertIn("home_team", ev)
                self.assertIn("away_team", ev)
                self.assertIn("commence_time", ev)
                self.assertTrue(ev["bookmakers"])

    def test_football_data_fixtures(self):
        fd = self.s["football_data"]["fixtures_main"]
        self.assertTrue(fd["ok"])
        self.assertEqual(fd["status"], 200)
        self.assertIn("B365H", fd["colonne"])
        self.assertIn("B365CH", fd["colonne"])
        self.assertEqual(fd["righe_5_leghe"], {d: 0 for d in ("E0", "I1", "D1", "SP1", "F1")})
        self.assertEqual(fd["n_righe_5_lelhe"], 0)

    def test_file_csv_committato(self):
        path = os.path.join(DATA_DIR, "football_data_fixtures.csv")
        self.assertTrue(os.path.exists(path))
        testo = open(path, encoding="utf-8").read()
        self.assertIn("HomeTeam", testo.splitlines()[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
