"""Le risposte grezze ricostruite sono davvero le risposte della sonda.

La prova e' un ANDATA E RITORNO: la ricostruzione passa per
``live_odds_probe.compact_events`` (la funzione che ha prodotto gli snapshot
committati) e deve restituire ESATTAMENTE gli snapshot committati. Se la
ricostruzione inventasse qualcosa — un nome di esito, una quota, un bookmaker —
il giro non tornerebbe.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
for p in (HERE, os.path.join(REPO_ROOT, "SoccerMath")):
    if p not in sys.path:
        sys.path.insert(0, p)

import live_odds_probe as SONDA  # noqa: E402
import live_odds_raw_fixtures as GREZZE  # noqa: E402
import update_live_odds as U  # noqa: E402


class TestAndataERitorno(unittest.TestCase):
    def test_compact_events_della_ricostruzione_ridai_lo_snapshot(self):
        for sport_key in GREZZE.SPORT_KEYS:
            snap = GREZZE.carica_snapshot(sport_key)
            grezza = GREZZE.risposta_grezza(snap, sport_key)
            rifatto = SONDA.compact_events(grezza, sport_key)
            with self.subTest(lega=sport_key):
                self.assertEqual(len(snap["events"]), len(rifatto))
                for atteso, ottenuto in zip(snap["events"], rifatto):
                    self.assertEqual(atteso["id"], ottenuto["id"])
                    self.assertEqual(atteso["home_team"], ottenuto["home_team"])
                    self.assertEqual(atteso["away_team"], ottenuto["away_team"])
                    self.assertEqual(atteso["commence_time"], ottenuto["commence_time"])
                    self.assertEqual(atteso["bookmakers"], ottenuto["bookmakers"])

    def test_la_forma_e_quella_annidata_dell_api(self):
        grezza = GREZZE.risposta_grezza(GREZZE.carica_snapshot("soccer_epl"), "soccer_epl")
        self.assertIsInstance(grezza, list)
        evento = grezza[0]
        self.assertEqual({"h2h"}, {m["key"] for b in evento["bookmakers"] for m in b["markets"]})
        for libro in evento["bookmakers"]:
            self.assertNotIn("h2h", libro, "la forma grezza non ha la scorciatoia compattata")
            nomi = {o["name"] for o in libro["markets"][0]["outcomes"]}
            self.assertEqual({evento["home_team"], evento["away_team"], "Draw"}, nomi)
            for esito in libro["markets"][0]["outcomes"]:
                self.assertIsInstance(esito["price"], float)

    def test_variante_senza_bookmakers_tiene_gli_eventi(self):
        snap = GREZZE.carica_snapshot("soccer_epl")
        vuota = GREZZE.risposta_grezza(snap, "soccer_epl", senza_bookmakers=True)
        self.assertEqual(len(snap["events"]), len(vuota))
        self.assertTrue(all(e["bookmakers"] == [] for e in vuota))
        self.assertTrue(all(e["home_team"] for e in vuota))


class TestScritturaSuDisco(unittest.TestCase):
    def test_i_file_hanno_il_nome_che_il_writer_si_aspetta(self):
        with tempfile.TemporaryDirectory() as d:
            scritti = GREZZE.scrivi_fixture(d)
            self.assertEqual(len(GREZZE.SPORT_KEYS), len(scritti))
            for sport_key in GREZZE.SPORT_KEYS:
                path = os.path.join(d, f"odds_api_{sport_key}.json")
                self.assertTrue(os.path.exists(path), path)
                blocco = U.scarica_lega_fixture(sport_key, d)
                self.assertEqual(200, blocco["http_status"])
                self.assertGreater(blocco["n_eventi"], 0)
                self.assertGreater(blocco["conversione"]["n_libri_totale"], 0)

    def test_nessuna_chiave_nei_file_prodotti(self):
        with tempfile.TemporaryDirectory() as d:
            for path in GREZZE.scrivi_fixture(d):
                testo = open(path, encoding="utf-8").read()
                self.assertNotIn("apiKey", testo)
                self.assertNotIn("api_key", testo)
                json.loads(testo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
