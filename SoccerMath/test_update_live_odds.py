"""Workflow delle quote live: dry-run con risposta API simulata, errori, quota.

Cosa viene provato (punti 2 e 9 della commessa "quote live nel Top Mix"):

* **dry-run con risposta API simulata** (``--fixture`` sugli snapshot committati
  in ``audit/data/live_odds_probe/``): lo STESSO writer del workflow, nessuna
  rete, nessun credito, nessuna scrittura;
* **risposta API simulata via HTTP finto**: crediti dagli header, una chiamata
  per lega, regioni ``eu`` e mercato ``h2h``;
* **quota crediti esaurita** (HTTP 429) e **chiave rifiutata** (401): il file
  precedente NON viene sovrascritto;
* **nessun evento**: idem, il file precedente resta;
* **successo parziale**: si scrive, con gli errori elencati e le leghe perse
  rispetto al giro precedente dichiarate;
* **la chiave non finisce mai nel file ne' nei log**.
"""
from __future__ import annotations

import io
import json
import logging
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

logging.getLogger("streamlit").setLevel(logging.ERROR)

import market_odds as mo  # noqa: E402
import update_live_odds as U  # noqa: E402

PROBE_DIR = os.path.join(REPO_ROOT, "audit", "data", "live_odds_probe")
CHIAVE_FINTA = "chiave-di-prova-0123456789abcdef"


def _evento(i, home, away, pinnacle=(1.6, 4.0, 6.0), extra=()):
    libri = [{"key": "pinnacle", "title": "Pinnacle", "last_update": "2026-10-09T08:16:00Z",
              "h2h": {"home": pinnacle[0], "draw": pinnacle[1], "away": pinnacle[2]}}]
    for k, t in extra:
        libri.append({"key": k, "title": k, "h2h": {"home": t[0], "draw": t[1], "away": t[2]}})
    return {"id": f"id{i}", "commence_time": "2026-10-10T13:00:00Z",
            "home_team": home, "away_team": away, "bookmakers": libri}


def _risposta(eventi, status=200, headers=None, testo="[]"):
    return mock.Mock(status_code=status, headers=headers or {}, json=lambda: eventi, text=testo)


class TestDryRunConRispostaSimulata(unittest.TestCase):
    """Il comando che gira sulla PR: writer reale, risposte simulate, 0 crediti."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "live_odds.json")
        self.addCleanup(self.tmp.cleanup)

    def test_dry_run_non_scrive_ma_fa_tutto_il_resto(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            codice, riepilogo = U.esegui(chiave="", fixture=PROBE_DIR, out=self.out, dry_run=True)
        self.assertEqual(U.ESITO_OK, codice)
        self.assertFalse(os.path.exists(self.out), "il dry-run non deve scrivere")
        self.assertTrue(riepilogo["dry_run"])
        payload = riepilogo["payload"]
        self.assertEqual(payload["n_leghe_richieste"], len(U.LEGA_SPORT_KEY))
        self.assertEqual(payload["n_leghe_ok"], 5)
        self.assertGreaterEqual(payload["n_eventi"], 90)
        self.assertEqual("fixture", payload["modalita"])

    def test_il_payload_ha_timestamp_bookmaker_e_quote_grezze(self):
        with redirect_stdout(io.StringIO()):
            _codice, riepilogo = U.esegui(chiave="", fixture=PROBE_DIR, out=self.out, dry_run=True)
        payload = riepilogo["payload"]
        self.assertTrue(payload["generato_il"].endswith("Z"))
        for lega, blocco in payload["leghe"].items():
            self.assertIn("sport_key", blocco, lega)
            self.assertTrue(blocco["scaricato_il"], lega)
            self.assertGreater(blocco["n_eventi"], 0, lega)
            for evento in blocco["eventi"]:
                self.assertTrue(evento["commence_time"])
                self.assertTrue(evento["home_team"] and evento["away_team"])
                self.assertGreater(len(evento["libri"]), 0)
                for libro in evento["libri"]:
                    self.assertTrue(libro["key"])
                    self.assertEqual({"home", "draw", "away"}, set(libro["h2h"]))
                    for v in libro["h2h"].values():
                        self.assertIsInstance(v, float, "quote grezze, non rielaborate")

    def test_il_payload_e_leggibile_da_market_odds(self):
        with redirect_stdout(io.StringIO()):
            codice, _r = U.esegui(chiave="", fixture=PROBE_DIR, out=self.out, dry_run=False)
        self.assertEqual(U.ESITO_OK, codice)
        payload = mo.carica_quote_live(self.out)
        self.assertIsNotNone(payload)
        dati = mo.indice_partite(payload)
        self.assertEqual(dati["n_eventi"], dati["n_indicizzati"])
        self.assertEqual([], dati["non_abbinati"])

    def test_i_crediti_sono_registrati(self):
        with redirect_stdout(io.StringIO()):
            _c, riepilogo = U.esegui(chiave="", fixture=PROBE_DIR, out=self.out, dry_run=True)
        crediti = riepilogo["payload"]["crediti"]
        self.assertEqual(500, crediti["quota_mensile"])
        self.assertIsNotNone(crediti["residui"])
        self.assertIsNotNone(crediti["usati_dall_ultimo_reset"])

    def test_la_chiave_non_compare_negli_output(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            U.esegui(chiave=CHIAVE_FINTA, fixture=PROBE_DIR, out=self.out, dry_run=False)
        self.assertNotIn(CHIAVE_FINTA, buf.getvalue())
        with open(self.out, encoding="utf-8") as fh:
            self.assertNotIn(CHIAVE_FINTA, fh.read())




class RipristinaLogging:
    """Riabilita i log per la durata del test.

    Sei file di test dell'audit chiamano ``logging.disable(CRITICAL)`` a livello
    di modulo e non lo ripristinano: pytest importa tutti i file prima di
    eseguire qualunque test, quindi nella suite completa lo stato globale dei log
    dipende dall'ordine dei file. I WARNING qui sono parte del contratto in prova
    (un nome non abbinato DEVE essere loggato), quindi il setUp li riabilita e il
    tearDown rimette ESATTAMENTE lo stato trovato. E' la stessa guardia gia' usata
    in ``test_fallback_nomi.py`` e ``test_topmix_ombra_totali.py``.
    """

    def setUp(self):
        self._disable_precedente = logging.root.manager.disable
        logging.disable(logging.NOTSET)
        if hasattr(super(), "setUp"):
            super().setUp()

    def tearDown(self):
        logging.disable(self._disable_precedente)


class TestChiamataRealeSimulata(RipristinaLogging, unittest.TestCase):
    """Una chiamata per lega, regions=eu, markets=h2h, crediti dagli header."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "live_odds.json")
        self.addCleanup(self.tmp.cleanup)
        self.chiamate = []

    def _get(self, risposte_per_sport):
        def get(url, params=None, timeout=None):
            self.chiamate.append((url, dict(params or {})))
            sport = url.rstrip("/").split("/")[-2]
            return risposte_per_sport.get(sport, _risposta([]))
        return get

    def test_una_chiamata_per_lega_con_eu_e_h2h(self):
        risposte = {sk: _risposta([_evento(i, "Inter", "Roma")],
                                  headers={"x-requests-used": "10", "x-requests-remaining": "490",
                                           "x-requests-last": "1"})
                    for i, sk in enumerate(U.LEGA_SPORT_KEY.values())}
        with mock.patch("requests.get", side_effect=self._get(risposte)):
            with redirect_stdout(io.StringIO()):
                codice, riepilogo = U.esegui(chiave=CHIAVE_FINTA, fixture=None,
                                             out=self.out, dry_run=False)
        self.assertEqual(U.ESITO_OK, codice)
        self.assertEqual(len(U.LEGA_SPORT_KEY), len(self.chiamate))
        for url, params in self.chiamate:
            self.assertEqual("eu", params["regions"])
            self.assertEqual("h2h", params["markets"])
            self.assertEqual("decimal", params["oddsFormat"])
            self.assertNotIn(CHIAVE_FINTA, url, "la chiave sta nei params, non nell'URL")
        self.assertEqual(5, riepilogo["payload"]["crediti"]["costo_giro_completo"])
        self.assertEqual(490, riepilogo["payload"]["crediti"]["residui"])
        self.assertTrue(os.path.exists(self.out))

    def test_la_chiave_non_finisce_nel_file(self):
        risposte = {sk: _risposta([_evento(0, "Inter", "Roma")]) for sk in U.LEGA_SPORT_KEY.values()}
        with mock.patch("requests.get", side_effect=self._get(risposte)):
            with redirect_stdout(io.StringIO()):
                U.esegui(chiave=CHIAVE_FINTA, fixture=None, out=self.out, dry_run=False)
        self.assertNotIn(CHIAVE_FINTA, open(self.out, encoding="utf-8").read())

    def test_quota_esaurita_non_sovrascrive(self):
        # giro precedente valido
        with open(self.out, "w", encoding="utf-8") as fh:
            json.dump({"leghe": {"Serie A": {"n_eventi": 3, "eventi": [1, 2, 3]}}}, fh)
        prima = open(self.out, encoding="utf-8").read()
        risposte = {sk: _risposta([], status=429, testo="quota exceeded")
                    for sk in U.LEGA_SPORT_KEY.values()}
        with mock.patch("requests.get", side_effect=self._get(risposte)):
            with redirect_stdout(io.StringIO()):
                codice, riepilogo = U.esegui(chiave=CHIAVE_FINTA, fixture=None,
                                             out=self.out, dry_run=False)
        self.assertEqual(U.ESITO_QUOTA_ESAURITA, codice)
        self.assertFalse(riepilogo["scritto"])
        self.assertEqual(prima, open(self.out, encoding="utf-8").read(),
                         "il file precedente deve restare identico")

    def test_chiave_rifiutata_non_sovrascrive(self):
        with open(self.out, "w", encoding="utf-8") as fh:
            json.dump({"leghe": {"Serie A": {"n_eventi": 3, "eventi": [1, 2, 3]}}}, fh)
        prima = open(self.out, encoding="utf-8").read()
        risposte = {sk: _risposta([], status=401, testo="invalid key")
                    for sk in U.LEGA_SPORT_KEY.values()}
        with mock.patch("requests.get", side_effect=self._get(risposte)):
            with redirect_stdout(io.StringIO()):
                codice, _r = U.esegui(chiave=CHIAVE_FINTA, fixture=None, out=self.out, dry_run=False)
        self.assertEqual(U.ESITO_CHIAVE, codice)
        self.assertEqual(prima, open(self.out, encoding="utf-8").read())

    def test_chiave_assente_nessuna_chiamata(self):
        with mock.patch("requests.get", side_effect=AssertionError("nessuna chiamata attesa")):
            with redirect_stdout(io.StringIO()):
                codice, riepilogo = U.esegui(chiave=None, fixture=None, out=self.out, dry_run=False)
        self.assertEqual(U.ESITO_CHIAVE, codice)
        self.assertEqual("ODDS_API_KEY assente", riepilogo["motivo"])

    def test_nessun_evento_non_sovrascrive(self):
        with open(self.out, "w", encoding="utf-8") as fh:
            json.dump({"leghe": {"Serie A": {"n_eventi": 3, "eventi": [1, 2, 3]}}}, fh)
        prima = open(self.out, encoding="utf-8").read()
        risposte = {sk: _risposta([]) for sk in U.LEGA_SPORT_KEY.values()}
        with mock.patch("requests.get", side_effect=self._get(risposte)):
            with redirect_stdout(io.StringIO()):
                codice, riepilogo = U.esegui(chiave=CHIAVE_FINTA, fixture=None,
                                             out=self.out, dry_run=False)
        self.assertEqual(U.ESITO_NULLA_SCRITTO, codice)
        self.assertEqual("nessun evento", riepilogo["motivo"])
        self.assertEqual(prima, open(self.out, encoding="utf-8").read())

    def test_errore_di_rete_su_tutte_le_leghe_non_sovrascrive(self):
        with open(self.out, "w", encoding="utf-8") as fh:
            json.dump({"leghe": {"Serie A": {"n_eventi": 3, "eventi": [1, 2, 3]}}}, fh)
        prima = open(self.out, encoding="utf-8").read()

        def boom(*a, **k):
            raise OSError("connessione rifiutata")

        with mock.patch("requests.get", side_effect=boom):
            with redirect_stdout(io.StringIO()):
                codice, _r = U.esegui(chiave=CHIAVE_FINTA, fixture=None, out=self.out, dry_run=False)
        self.assertEqual(U.ESITO_NULLA_SCRITTO, codice)
        self.assertEqual(prima, open(self.out, encoding="utf-8").read())

    def test_una_lega_sola_scrive_e_dichiara_le_altre(self):
        leghe = list(U.LEGA_SPORT_KEY.values())
        risposte = {leghe[0]: _risposta([_evento(0, "Inter", "Roma"), _evento(1, "Milan", "Napoli")])}
        for sk in leghe[1:]:
            risposte[sk] = _risposta([], status=500, testo="errore interno")
        with mock.patch("requests.get", side_effect=self._get(risposte)):
            with redirect_stdout(io.StringIO()):
                codice, riepilogo = U.esegui(chiave=CHIAVE_FINTA, fixture=None,
                                             out=self.out, dry_run=False)
        self.assertEqual(U.ESITO_OK, codice)
        payload = riepilogo["payload"]
        self.assertEqual(1, payload["n_leghe_ok"])
        self.assertEqual(len(leghe) - 1, len(payload["errori"]))
        self.assertTrue(os.path.exists(self.out))

    def test_leghe_perse_rispetto_al_giro_precedente(self):
        with open(self.out, "w", encoding="utf-8") as fh:
            json.dump({"leghe": {"Serie A": {"n_eventi": 3, "eventi": [1, 2, 3]},
                                "La Liga": {"n_eventi": 2, "eventi": [1, 2]}}}, fh)
        leghe = list(U.LEGA_SPORT_KEY.values())
        risposte = {leghe[0]: _risposta([_evento(0, "Inter", "Roma")])}
        for sk in leghe[1:]:
            risposte[sk] = _risposta([], status=500, testo="errore")
        with mock.patch("requests.get", side_effect=self._get(risposte)):
            with redirect_stdout(io.StringIO()):
                _c, riepilogo = U.esegui(chiave=CHIAVE_FINTA, fixture=None,
                                         out=self.out, dry_run=False)
        self.assertEqual(["La Liga"], riepilogo["payload"]["leghe_mancanti_rispetto_a_prima"])

    def test_risposta_non_json_e_errore_nel_corpo(self):
        leghe = list(U.LEGA_SPORT_KEY.values())

        def get(url, params=None, timeout=None):
            sport = url.rstrip("/").split("/")[-2]
            if sport == leghe[0]:
                r = mock.Mock(status_code=200, headers={}, text="non json")
                r.json.side_effect = ValueError("non json")
                return r
            if sport == leghe[1]:
                return mock.Mock(status_code=200, headers={},
                                 json=lambda: {"message": "nessun evento"}, text="{}")
            return _risposta([_evento(0, "Inter", "Roma")])

        with mock.patch("requests.get", side_effect=get):
            with redirect_stdout(io.StringIO()):
                codice, riepilogo = U.esegui(chiave=CHIAVE_FINTA, fixture=None,
                                             out=self.out, dry_run=False)
        self.assertEqual(U.ESITO_OK, codice)
        # 5 leghe: 2 in errore (non JSON, corpo d'errore) e 3 con eventi
        self.assertEqual(2, len(riepilogo["payload"]["errori"]))
        self.assertEqual(3, riepilogo["payload"]["n_leghe_ok"])

    def test_un_messaggio_di_errore_contenente_la_chiave_viene_redatto(self):
        def boom(*a, **k):
            raise OSError(f"url https://api.the-odds-api.com/?apiKey={CHIAVE_FINTA} fallito")

        with mock.patch("requests.get", side_effect=boom):
            with self.assertLogs("update_live_odds", level="WARNING") as cat:
                codice, _r = U.esegui(chiave=CHIAVE_FINTA, fixture=None,
                                      out=self.out, dry_run=False)
        self.assertEqual(U.ESITO_NULLA_SCRITTO, codice)
        testo = "\n".join(cat.output)
        self.assertNotIn(CHIAVE_FINTA, testo, "la chiave e' finita in un messaggio di log")
        self.assertIn("apiKey=***", testo)


class TestRedazione(unittest.TestCase):
    def test_redigi(self):
        self.assertEqual("a *** b", U.redigi(f"a {CHIAVE_FINTA} b", CHIAVE_FINTA))
        self.assertEqual("nessuna chiave", U.redigi("nessuna chiave", CHIAVE_FINTA))
        self.assertEqual("", U.redigi(None, CHIAVE_FINTA))

    def test_url_masked_non_contiene_la_chiave(self):
        url = U.url_masked("soccer_epl", True)
        self.assertIn("apiKey=***", url)
        self.assertNotIn(CHIAVE_FINTA, url)

    def test_crediti_da_header(self):
        c = U.crediti_da_header({"x-requests-used": "12", "x-requests-remaining": "488",
                                 "x-requests-last": "1"})
        self.assertEqual({"usati_dall_ultimo_reset": 12, "residui": 488,
                          "costo_ultima_chiamata": 1}, c)
        self.assertEqual({"usati_dall_ultimo_reset": None, "residui": None,
                          "costo_ultima_chiamata": None}, U.crediti_da_header({}))
        self.assertIsNone(U.crediti_da_header({"x-requests-remaining": "n/d"})["residui"])


class TestSchemaEAtomicita(unittest.TestCase):
    def test_la_scrittura_e_atomica(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "live_odds.json")
            U.scrivi_atomico({"a": 1}, out)
            self.assertEqual({"a": 1}, json.load(open(out, encoding="utf-8")))
            self.assertEqual([], [f for f in os.listdir(d) if f.endswith(".tmp")])

    def test_lo_schema_e_dichiarato(self):
        payload = U.costruisci_payload([], fixture=None, chiave_presente=False)
        self.assertEqual(mo.SCHEMA_LIVE_ODDS, payload["schema"])
        self.assertEqual("eu", payload["regioni"])
        self.assertEqual("h2h", payload["mercato"])

    def test_le_cinque_leghe_del_progetto(self):
        self.assertEqual(["Serie A", "Premier League", "La Liga", "Bundesliga", "Ligue 1"],
                         list(U.LEGA_SPORT_KEY))

    def test_cli_dry_run_su_fixture(self):
        """Il comando esatto del passo PR del workflow."""
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "live_odds.json")
            buf = io.StringIO()
            with redirect_stdout(buf):
                codice = U.main(["--fixture", PROBE_DIR, "--out", out, "--dry-run"])
            self.assertEqual(0, codice)
            self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    unittest.main(verbosity=2)
