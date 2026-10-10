"""Test di audit per il punto 3: diagnosi della sonda totals e correzione dello
stato finale dei crediti.

Due cose sotto test:
  1. lo stato finale del conto e' quello dell'ULTIMA CHIAMATA IN ORDINE DI TEMPO
     (non dell'ultima lega in ordine alfabetico): e' il bug trovato nel referto
     della PR #59 (61/439 invece di 63/437);
  2. la classificazione per causa degli eventi che non superano la regola
     (priorita' C1 -> C4) e la distribuzione dei giorni mancanti.

Nessuna rete, nessuna chiave: i test usano snapshot sintetici.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import totals_probe as tp  # noqa: E402
import totals_probe_analysis as tpa  # noqa: E402
import totals_probe_diagnosi as tpd  # noqa: E402


def _env(sport_key, usati, secondi="17:03:43", eventi=1):
    return {
        "lega": sport_key, "sport_key": sport_key, "mercato": "totals", "regioni": "eu",
        "fetched_at_utc": f"2026-10-10T{secondi}Z",
        "url_masked": "https://api.the-odds-api.com/v4/sports/x/odds/?apiKey=***",
        "status": 200, "ok": True, "error": None,
        "headers": {"x-requests-used": str(usati), "x-requests-remaining": str(500 - usati),
                    "x-requests-last": "1"},
        "body": [{"id": f"{sport_key}-{i}", "bookmakers": []} for i in range(eventi)],
    }


class TestOrdineCronologico(unittest.TestCase):

    def test_a_parita_di_secondo_decide_il_contatore_usati(self):
        snaps = [("b.json", _env("soccer_b", 61)), ("a.json", _env("soccer_a", 63))]
        ordine = [n for n, _e in tpa.ordine_cronologico(snaps)]
        self.assertEqual(ordine, ["b.json", "a.json"])     # non alfabetico: per usati

    def test_ordina_prima_per_timestamp_poi_per_contatore(self):
        snaps = [("t2.json", _env("soccer_t2", 70, "17:03:44")),
                 ("t1.json", _env("soccer_t1", 71, "17:03:43")),
                 ("t0.json", _env("soccer_t0", 69, "17:03:43"))]
        ordine = [n for n, _e in tpa.ordine_cronologico(snaps)]
        self.assertEqual(ordine, ["t0.json", "t1.json", "t2.json"])

    def test_analisi_prende_lo_stato_dell_ultima_chiamata_in_ordine_di_tempo(self):
        # l'ultima in ordine ALFABETICO (spain) NON e' l'ultima in ordine di tempo
        snaps = [("soccer_epl.json", _env("soccer_epl", 60)),
                 ("soccer_spain_la_liga.json", _env("soccer_spain_la_liga", 61)),
                 ("soccer_france_ligue_one.json", _env("soccer_france_ligue_one", 63,
                                                       "17:03:44"))]
        r = tpa.analyse(snaps)
        self.assertEqual(r["ultimi_header"]["x-requests-used"], "63")
        self.assertEqual(r["ultimi_header"]["x-requests-remaining"], "437")
        self.assertEqual(r["ultima_chiamata"]["sport_key"], "soccer_france_ligue_one")
        md = tpa.build_md(r, "2026-10-10T00:00:00Z", 3)
        self.assertIn("used=63", md)
        self.assertIn("remaining=437", md)

    def test_il_referto_dichiara_la_regola_e_non_solo_il_numero(self):
        r = tpa.analyse([("a.json", _env("soccer_epl", 60))])
        md = tpa.build_md(r, "x", 1)
        self.assertIn("ultima chiamata in ordine di tempo", md)


class TestStatoFinaleDellaSonda(unittest.TestCase):
    """totals_probe.py: lo stato finale non puo' dipendere dall'ordine del ciclo."""

    def test_riassunto_prende_il_massimo_della_chiave_cronologica(self):
        stato = {}

        def fake_get_json(url, key, session):
            # risposte in un ordine di tempo DIVERSO dall'ordine del ciclo LEAGUES
            sport = url.split("/sports/")[1].split("/odds")[0]
            usati, sec = {"soccer_italy_serie_a": (59, "17:03:43"),
                          "soccer_epl": (60, "17:03:43"),
                          "soccer_spain_la_liga": (61, "17:03:43"),
                          "soccer_germany_bundesliga": (62, "17:03:44"),
                          "soccer_france_ligue_one": (63, "17:03:44")}[sport]
            meta = {"url_masked": "https://x/?apiKey=***", "fetched_at_utc":
                    f"2026-10-10T{sec}Z", "status": 200, "ok": True, "error": None,
                    "headers": {"x-requests-used": str(usati),
                                "x-requests-remaining": str(500 - usati),
                                "x-requests-last": "1"}}
            return [{"id": sport, "bookmakers": []}], meta

        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"ODDS_API_KEY": "chiave-finta"}):
                with mock.patch.object(tp, "get_json", side_effect=fake_get_json):
                    self.assertEqual(tp.main(["--out", d]), 0)
            with open(os.path.join(d, "_summary.json"), encoding="utf-8") as fh:
                stato = json.load(fh)
        self.assertEqual(stato["x-requests-used_ultimo"], "63")
        self.assertEqual(stato["x-requests-remaining_ultimo"], "437")
        self.assertEqual(stato["ultima_chiamata"]["sport_key"], "soccer_france_ligue_one")
        self.assertNotIn("chiave-finta", json.dumps(stato))


class TestClassificazioneCause(unittest.TestCase):

    def _ev(self, giorni=1.0, lines=None, regola=None):
        e = {"id": "x", "lega": "Serie A", "giorni": giorni, "n_libri": len(lines or {}),
             "n_25": sum(1 for p in (lines or {}).values() if p == 2.5),
             "pinnacle": (lines or {}).get("pinnacle"),
             "pinnacle_val": (lines or {}).get("pinnacle")}
        tipo, val = tpd._bucket(e["pinnacle"]) if e["pinnacle"] is not None else ("assente", None)
        e["pinnacle_tipo"] = tipo
        e["pinnacle_val"] = val
        if regola is None:
            regola = (e["pinnacle"] == 2.5) or (e["n_25"] >= 3)
        e["regola"] = regola
        return e

    def test_priorita_c1_pinnacle_assente(self):
        e = self._ev(lines={"a": 2.5, "b": 2.5})          # 2 libri a 2,5, nessun Pinnacle
        self.assertFalse(e["regola"])
        self.assertTrue(tpd.causa(e).startswith("C1"))

    def test_priorita_c2_linea_diversa(self):
        for punto, atteso in ((1.5, "1,5"), (3.0, "intera"), (3.25, "a quarti"),
                              (3.5, "3,5"), (4.5, "altra mezza")):
            e = self._ev(lines={"pinnacle": punto, "a": 2.5, "b": 2.5})
            self.assertFalse(e["regola"])
            self.assertIn(atteso, tpd.causa(e)), (punto, tpd.causa(e))

    def test_c3_vuota_per_costruzione(self):
        # Pinnacle a 2,5 => regola soddisfatta: C3 non puo' presentarsi
        e = self._ev(lines={"pinnacle": 2.5})
        self.assertTrue(e["regola"])
        e2 = self._ev(lines={"pinnacle": 2.5}, regola=False)   # forzato solo per il test
        self.assertTrue(tpd.causa(e2).startswith("C3"))

    def test_c4_senza_linee(self):
        e = self._ev(lines={})
        self.assertFalse(e["regola"])
        self.assertTrue(tpd.causa(e).startswith("C4"))

    def test_distribuzione_giorni(self):
        d = tpd.distribuzione([3.0, 1.0, 2.0])
        self.assertEqual(d["n"], 3)
        self.assertEqual(d["min"], 1.0)
        self.assertEqual(d["mediana"], 2.0)
        self.assertEqual(d["max"], 3.0)


class TestSugliSnapshotReali(unittest.TestCase):
    """Se gli snapshot della sonda sono nel repo, i conteggi devono tornare."""

    def setUp(self):
        self.snaps = tpd.load_snapshots()
        if not self.snaps:
            self.skipTest("nessuno snapshot in audit/data/totals_probe/")

    def test_82_eventi_e_26_fuori_regola(self):
        eventi = tpd.analizza(self.snaps)
        self.assertEqual(len(eventi), 82)
        ko = [e for e in eventi if not e["regola"]]
        self.assertEqual(len(ko), 26)
        self.assertEqual(sum(1 for e in eventi if e["regola"]), 56)

    def test_ogni_evento_fuori_regola_ha_meno_di_tre_libri_a_2_5(self):
        eventi = tpd.analizza(self.snaps)
        for e in eventi:
            if not e["regola"]:
                self.assertLess(e["n_25"], 3)
                self.assertNotEqual(e["pinnacle"], 2.5)

    def test_stato_finale_63_437(self):
        ultimo = tpd.ordine_cronologico(self.snaps)[-1][1]
        self.assertEqual(ultimo["headers"]["x-requests-used"], "63")
        self.assertEqual(ultimo["headers"]["x-requests-remaining"], "437")


if __name__ == "__main__":
    unittest.main()
