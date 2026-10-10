"""Workflow delle quote live: conversione della risposta reale, errori, quota.

Cosa viene provato (punti 2 e 9 della commessa "quote live nel Top Mix", piu'
la riparazione del guasto del 2026-10-09):

* **conversione della risposta GREZZA** (``bookmakers[].markets[].outcomes[]``,
  la forma che manda The Odds API): ogni bookmaker diventa un libro, con i
  motivi di scarto contati uno per uno;
* **dry-run con risposte REALI** (``--fixture``): non piu' eventi scritti a
  mano, ma le risposte della sonda del 2026-10-08 rimesse nella forma grezza da
  ``audit/live_odds_raw_fixtures.py``, piu' gli snapshot compattati committati
  in ``audit/data/live_odds_probe/`` (le due forme devono dare lo stesso file);
* **da capo a fondo**: risposte reali -> writer -> file in tmp ->
  ``carica_quote_live`` -> ``indice_partite`` -> ``cerca_quote`` -> de-vig;
* **eventi senza quote**: una lega con eventi e zero libri fa FALLIRE il giro
  (exit 4) e il file precedente resta intatto;
* **risposta API simulata via HTTP finto**: crediti dagli header, una chiamata
  per lega, regioni ``eu`` e mercato ``h2h``;
* **quota crediti esaurita** (HTTP 429) e **chiave rifiutata** (401): il file
  precedente NON viene sovrascritto;
* **nessun evento**: idem, il file precedente resta;
* **successo parziale**: si scrive, con gli errori elencati e le leghe perse
  rispetto al giro precedente dichiarate;
* **diagnostica nel file**: conteggi grezzi pre-conversione (eventi, bookmaker
  distinti, mercati) e conteggi di conversione, senza dati sensibili;
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
from datetime import datetime, timedelta, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
AUDIT_DIR = os.path.join(REPO_ROOT, "audit")
if HERE not in sys.path:
    sys.path.insert(0, HERE)
if AUDIT_DIR not in sys.path:
    sys.path.insert(0, AUDIT_DIR)

logging.getLogger("streamlit").setLevel(logging.ERROR)

import market_odds as mo  # noqa: E402
import update_live_odds as U  # noqa: E402
# Risposte REALI della sonda (PR #50) rimesse nella forma grezza dell'API: e'
# la forma che arriva dalla rete, quella su cui il writer e' andato a sbattere
# il 2026-10-09. Vedi il docstring di live_odds_raw_fixtures.
import live_odds_raw_fixtures as GREZZE  # noqa: E402

PROBE_DIR = os.path.join(REPO_ROOT, "audit", "data", "live_odds_probe")
CHIAVE_FINTA = "chiave-di-prova-0123456789abcdef"


def _snapshot(sport_key):
    """Snapshot COMPATTATO della sonda (quello committato)."""
    return GREZZE.carica_snapshot(sport_key)


def _corpo_grezzo(sport_key, n_eventi=None, senza_bookmakers=False):
    """Corpo GREZZO della risposta ``/odds`` per una lega (dati reali della sonda).

    I ``commence_time`` sono portati a +6h dall'ora reale (come in
    ``test_freschezza_quote``): i kickoff della sonda del 2026-10-08 sono
    "gia' iniziati" il giorno dopo e il filtro SOLO PRE-PARTITA del writer li
    escluderebbe — giustamente, ma qui si prova la conversione e il percorso
    di rete, non il filtro (che ha i test propri in
    ``test_quote_solo_pre_partita.py``).
    """
    corpo = GREZZE.risposta_grezza(_snapshot(sport_key), sport_key,
                                   senza_bookmakers=senza_bookmakers)
    if n_eventi is not None:
        corpo = corpo[:n_eventi]
    kickoff = (datetime.now(timezone.utc) + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [{**e, "commence_time": kickoff} for e in corpo]


def _dir_grezza(dest, senza_bookmakers=False):
    """Scrive in ``dest`` le 5 risposte grezze reali (cartella da passare a --fixture)."""
    GREZZE.scrivi_fixture(dest, senza_bookmakers=senza_bookmakers)
    return dest


def _risposta(eventi, status=200, headers=None, testo="[]"):
    return mock.Mock(status_code=status, headers=headers or {}, json=lambda: eventi, text=testo)


def _risposte_reali(n_eventi=1, headers=None):
    """Una risposta grezza REALE per ciascuna delle 5 leghe."""
    return {sk: _risposta(_corpo_grezzo(sk, n_eventi), headers=headers)
            for sk in U.LEGA_SPORT_KEY.values()}


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
        risposte = _risposte_reali(n_eventi=1,
                                   headers={"x-requests-used": "10",
                                            "x-requests-remaining": "490",
                                            "x-requests-last": "1"})
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
        risposte = _risposte_reali(n_eventi=1)
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
        risposte = {leghe[0]: _risposta(_corpo_grezzo(leghe[0], 2))}
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
        risposte = {leghe[0]: _risposta(_corpo_grezzo(leghe[0], 1))}
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
            return _risposta(_corpo_grezzo(sport, 1))

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


class TestConversioneRispostaGrezza(unittest.TestCase):
    """La forma che manda davvero The Odds API: ``markets`` -> ``outcomes``.

    E' il guasto del 2026-10-09: il writer leggeva solo ``{"h2h": {...}}`` e
    buttava ogni bookmaker annidato, con HTTP 200 e 5 crediti spesi.
    """

    EVENTO_GREZZO = {
        "id": "ev1", "commence_time": "2026-10-10T13:00:00Z",
        "home_team": "Genoa", "away_team": "Fiorentina",
        "bookmakers": [{
            "key": "pinnacle", "title": "Pinnacle", "last_update": "2026-10-08T23:30:15Z",
            "markets": [{"key": "h2h", "outcomes": [
                {"name": "Genoa", "price": 3.34},
                {"name": "Fiorentina", "price": 2.36},
                {"name": "Draw", "price": 3.23}]}],
        }],
    }

    def test_bookmaker_annidato_diventa_un_libro(self):
        libri = U.libri_dell_evento(self.EVENTO_GREZZO)
        self.assertEqual(1, len(libri))
        self.assertEqual("pinnacle", libri[0]["key"])
        self.assertEqual({"home": 3.34, "draw": 3.23, "away": 2.36}, libri[0]["h2h"])
        self.assertEqual("2026-10-08T23:30:15Z", libri[0]["last_update"])

    def test_forma_compattata_della_sonda_ancora_accettata(self):
        evento = {"home_team": "Genoa", "away_team": "Fiorentina",
                  "bookmakers": [{"key": "pinnacle",
                                  "h2h": {"home": 3.34, "draw": 3.23, "away": 2.36}}]}
        libri = U.libri_dell_evento(evento)
        self.assertEqual({"home": 3.34, "draw": 3.23, "away": 2.36}, libri[0]["h2h"])

    def test_le_due_forme_danno_lo_stesso_libro(self):
        compatto = {"home_team": "Genoa", "away_team": "Fiorentina", "bookmakers": [
            {"key": "pinnacle", "title": "Pinnacle", "last_update": "2026-10-08T23:30:15Z",
             "h2h": {"home": 3.34, "draw": 3.23, "away": 2.36}}]}
        self.assertEqual(U.libri_dell_evento(compatto),
                         U.libri_dell_evento(self.EVENTO_GREZZO))

    def test_pareggio_riconosciuto_senza_badare_a_maiuscole_e_spazi(self):
        evento = json.loads(json.dumps(self.EVENTO_GREZZO))
        evento["bookmakers"][0]["markets"][0]["outcomes"][2]["name"] = "  DRAW "
        self.assertEqual(3.23, U.libri_dell_evento(evento)[0]["h2h"]["draw"])

    def test_prezzi_interi_e_stringhe_sono_quote_valide(self):
        evento = json.loads(json.dumps(self.EVENTO_GREZZO))
        evento["bookmakers"][0]["markets"][0]["outcomes"][0]["price"] = 3
        evento["bookmakers"][0]["markets"][0]["outcomes"][1]["price"] = "2.36"
        h2h = U.libri_dell_evento(evento)[0]["h2h"]
        self.assertEqual(3.0, h2h["home"])
        self.assertEqual(2.36, h2h["away"])

    def test_altri_mercati_non_disturbano_h2h(self):
        evento = json.loads(json.dumps(self.EVENTO_GREZZO))
        evento["bookmakers"][0]["markets"].insert(
            0, {"key": "totals", "outcomes": [{"name": "Over", "price": 1.9, "point": 2.5}]})
        self.assertEqual({"home": 3.34, "draw": 3.23, "away": 2.36},
                         U.libri_dell_evento(evento)[0]["h2h"])

    def test_i_motivi_di_scarto_sono_contati_uno_per_uno(self):
        evento = {
            "home_team": "Genoa", "away_team": "Fiorentina",
            "bookmakers": [
                {"key": "a", "markets": [{"key": "totals", "outcomes": []}]},
                {"key": "b", "markets": [{"key": "h2h", "outcomes": [
                    {"name": "Squadra ignota", "price": 2.0}]}]},
                {"key": "c", "markets": [{"key": "h2h", "outcomes": [
                    {"name": "Genoa", "price": None}]}]},
                {"key": "d"},
                "non un dizionario",
            ],
        }
        scarti = {}
        self.assertEqual([], U.libri_dell_evento(evento, scarti))
        self.assertEqual({U.SCARTO_MERCATO_H2H_ASSENTE: 1,
                          U.SCARTO_ESITI_NON_ABBINATI: 1,
                          U.SCARTO_PREZZO_NON_NUMERICO: 1,
                          U.SCARTO_SENZA_MERCATI: 1,
                          U.SCARTO_NON_DICT: 1}, scarti)

    def test_quota_non_numerica_non_diventa_zero(self):
        self.assertIsNone(U._prezzo("abc"))
        self.assertIsNone(U._prezzo(True))
        self.assertIsNone(U._prezzo(None))
        self.assertIsNone(U._prezzo(float("inf")))

    def test_le_risposte_reali_della_sonda_danno_libri_su_ogni_evento(self):
        """Dati reali: ogni evento della sonda con bookmaker deve avere libri."""
        for sport_key in U.LEGA_SPORT_KEY.values():
            snap = _snapshot(sport_key)
            grezza = _corpo_grezzo(sport_key)
            attesi = {e["id"]: len(e.get("bookmakers") or []) for e in snap["events"]}
            attesi_pinnacle = {e["id"] for e in snap["events"]
                               if any(b.get("key") == "pinnacle" for b in e["bookmakers"])}
            self.assertTrue(attesi, sport_key)
            for evento in grezza:
                libri = U.libri_dell_evento(evento)
                with self.subTest(lega=sport_key, evento=evento["id"]):
                    self.assertEqual(attesi[evento["id"]], len(libri),
                                     "ogni bookmaker della sonda deve diventare un libro")
                    self.assertGreater(len(libri), 0)
                    trovato_pinnacle = any(l["key"] == "pinnacle" for l in libri)
                    self.assertEqual(evento["id"] in attesi_pinnacle, trovato_pinnacle,
                                     "Pinnacle dev'essere trovato dove lo trovava la sonda")


class TestDiagnosticaNelFile(unittest.TestCase):
    """Conteggi grezzi (pre-conversione) e di conversione, senza dati sensibili."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.grezze = _dir_grezza(os.path.join(cls.tmp.name, "grezze"))
        out = os.path.join(cls.tmp.name, "live_odds.json")
        with redirect_stdout(io.StringIO()):
            codice, riepilogo = U.esegui(chiave="", fixture=cls.grezze, out=out, dry_run=False)
        assert codice == U.ESITO_OK, codice
        with open(out, encoding="utf-8") as fh:
            cls.payload = json.load(fh)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_i_conteggi_grezzi_contano_i_bookmaker_prima_della_conversione(self):
        for lega, blocco in self.payload["leghe"].items():
            snap = _snapshot(blocco["sport_key"])
            coppie = sum(len(e["bookmakers"]) for e in snap["events"])
            distinti = len(snap["bookmakers"])
            grezzo = blocco["grezzo"]
            with self.subTest(lega=lega):
                self.assertEqual(len(snap["events"]), grezzo["n_eventi"])
                self.assertEqual(coppie, grezzo["n_coppie_evento_bookmaker"])
                self.assertEqual(distinti, grezzo["n_bookmaker_distinti"])
                self.assertEqual(sorted(snap["bookmakers"]),
                                 sorted(grezzo["bookmaker_per_chiave"]))
                self.assertEqual({"h2h": coppie}, grezzo["mercati_presenti"])
                self.assertEqual(coppie, grezzo["forma_bookmaker"]["annidata"])
                self.assertEqual(0, grezzo["forma_bookmaker"]["sconosciuta"])

    def test_i_conteggi_di_conversione_dicono_quanto_e_sopravvissuto(self):
        for lega, blocco in self.payload["leghe"].items():
            conv = blocco["conversione"]
            with self.subTest(lega=lega):
                self.assertEqual(blocco["n_eventi"], conv["n_eventi"])
                self.assertEqual(blocco["n_eventi"], conv["n_eventi_con_libri"])
                self.assertEqual(0, conv["n_eventi_senza_libri"])
                self.assertEqual(blocco["grezzo"]["n_coppie_evento_bookmaker"],
                                 conv["n_libri_totale"])
                self.assertEqual({}, conv["bookmaker_scartati"])
                self.assertGreater(conv["n_eventi_con_pinnacle"], 0)

    def test_i_totali_del_file_tornano_con_le_leghe(self):
        leghe = self.payload["leghe"].values()
        self.assertEqual(sum(l["conversione"]["n_libri_totale"] for l in leghe),
                         self.payload["n_libri_totale"])
        self.assertEqual(sum(l["conversione"]["n_eventi_con_libri"] for l in leghe),
                         self.payload["n_eventi_con_libri"])
        self.assertEqual(sum(l["conversione"]["n_eventi_con_pinnacle"] for l in leghe),
                         self.payload["n_eventi_con_pinnacle"])
        self.assertEqual([], self.payload["leghe_con_eventi_senza_libri"])
        self.assertEqual(5, self.payload["n_leghe_con_quote"])

    def test_la_diagnostica_non_contiene_dati_sensibili(self):
        for blocco in self.payload["leghe"].values():
            testo = json.dumps({"grezzo": blocco["grezzo"],
                                "conversione": blocco["conversione"]}, ensure_ascii=False)
            self.assertNotIn("apiKey", testo)
            self.assertNotIn("http", testo)
            self.assertNotIn(CHIAVE_FINTA, testo)

    def test_le_due_forme_della_stessa_risposta_danno_gli_stessi_eventi(self):
        """Snapshot compattato e corpo grezzo devono produrre lo stesso file."""
        out = os.path.join(self.tmp.name, "da_compattato.json")
        with redirect_stdout(io.StringIO()):
            codice, _r = U.esegui(chiave="", fixture=PROBE_DIR, out=out, dry_run=False)
        self.assertEqual(U.ESITO_OK, codice)
        compattato = json.load(open(out, encoding="utf-8"))
        for lega, blocco in self.payload["leghe"].items():
            self.assertEqual(compattato["leghe"][lega]["eventi"], blocco["eventi"], lega)


class TestLegaConEventiSenzaLibri(RipristinaLogging, unittest.TestCase):
    """Eventi presenti e zero libri: il giro FALLISCE e non sovrascrive nulla.

    E' il caso del 2026-10-09 (96 eventi, 5/5 leghe, HTTP 200, ``"libri": []``
    su tutti gli eventi, workflow uscito ``success``).
    """

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "live_odds.json")
        # giro precedente valido, da NON perdere
        self.precedente = {"schema": mo.SCHEMA_LIVE_ODDS, "generato_il": "2026-10-08T08:17:00Z",
                           "leghe": {"Serie A": {"n_eventi": 3, "eventi": [1, 2, 3]}}}
        with open(self.out, "w", encoding="utf-8") as fh:
            json.dump(self.precedente, fh)
        self.prima = open(self.out, encoding="utf-8").read()

    def test_fixture_con_bookmakers_vuoti_fallisce_e_non_sovrascrive(self):
        vuote = _dir_grezza(os.path.join(self.tmp.name, "vuote"), senza_bookmakers=True)
        with redirect_stdout(io.StringIO()):
            codice, riepilogo = U.esegui(chiave="", fixture=vuote, out=self.out, dry_run=False)
        self.assertEqual(U.ESITO_CONVERSIONE_VUOTA, codice)
        self.assertFalse(riepilogo["scritto"])
        self.assertEqual(list(U.LEGA_SPORT_KEY), riepilogo["leghe_senza_libri"])
        self.assertEqual(self.prima, open(self.out, encoding="utf-8").read(),
                         "il file precedente deve restare identico")

    def test_anche_il_dry_run_fallisce(self):
        vuote = _dir_grezza(os.path.join(self.tmp.name, "vuote"), senza_bookmakers=True)
        with redirect_stdout(io.StringIO()):
            codice, _r = U.esegui(chiave="", fixture=vuote, out=self.out, dry_run=True)
        self.assertEqual(U.ESITO_CONVERSIONE_VUOTA, codice)

    def test_una_sola_lega_senza_libri_basta_a_fallire(self):
        """Quattro leghe con quote e una senza: non si scrive comunque."""
        leghe = list(U.LEGA_SPORT_KEY.values())
        risposte = {sk: _risposta(_corpo_grezzo(sk, 2)) for sk in leghe}
        risposte[leghe[2]] = _risposta(_corpo_grezzo(leghe[2], 2, senza_bookmakers=True))
        with mock.patch("requests.get", side_effect=self._get(risposte)):
            with redirect_stdout(io.StringIO()):
                codice, riepilogo = U.esegui(chiave=CHIAVE_FINTA, fixture=None,
                                             out=self.out, dry_run=False)
        self.assertEqual(U.ESITO_CONVERSIONE_VUOTA, codice)
        self.assertEqual(["La Liga"], riepilogo["leghe_senza_libri"])
        self.assertEqual(self.prima, open(self.out, encoding="utf-8").read())

    def test_la_regressione_del_2026_10_09_fa_fallire_il_giro(self):
        """Risposta reale, conversione che perde i bookmaker: exit 4, non 0.

        La vecchia conversione accettava solo ``{"h2h": {...}}``: qui viene
        rimessa in piedi per un attimo per provare che oggi il giro FALLISCE
        invece di scrivere 96 eventi senza quote.
        """
        def conversione_vecchia(libro, home_team, away_team):
            if isinstance(libro, dict) and isinstance(libro.get("h2h"), dict):
                return dict(libro["h2h"]), None
            return None, U.SCARTO_SENZA_MERCATI

        grezze = _dir_grezza(os.path.join(self.tmp.name, "grezze"))
        with mock.patch.object(U, "h2h_dal_bookmaker", side_effect=conversione_vecchia):
            with redirect_stdout(io.StringIO()):
                codice, riepilogo = U.esegui(chiave="", fixture=grezze, out=self.out,
                                             dry_run=False)
        self.assertEqual(U.ESITO_CONVERSIONE_VUOTA, codice)
        self.assertEqual(96, riepilogo["payload"]["n_eventi"])
        self.assertEqual(0, riepilogo["payload"]["n_libri_totale"])
        self.assertEqual(self.prima, open(self.out, encoding="utf-8").read())

    def test_il_log_non_dice_piu_eventi_ok_senza_quote(self):
        blocco = {"sport_key": "soccer_epl", "n_eventi": 20, "errore": None,
                  "grezzo": U.conteggi_grezzi([]), "conversione": U.conteggi_conversione([])}
        blocco["conversione"]["n_eventi"] = 20
        blocco["conversione"]["n_eventi_senza_libri"] = 20
        with self.assertLogs("update_live_odds", level="ERROR") as cat:
            riga = U.registra_log_lega("soccer_epl", blocco)
        self.assertIn("eventi=20", riga)
        self.assertIn("eventi con almeno un libro=0", riga)
        self.assertIn("eventi con Pinnacle=0", riga)
        self.assertIn("bookmaker nella risposta grezza=0", riga)
        self.assertIn("SENZA QUOTE", riga)
        self.assertNotIn("20 eventi OK", "\n".join(cat.output))

    def test_il_log_di_una_lega_sana_riporta_i_quattro_numeri(self):
        grezza = _corpo_grezzo("soccer_epl", 3)
        eventi, grezzo, conv = U.normalizza_eventi(grezza)
        blocco = {"sport_key": "soccer_epl", "n_eventi": len(eventi), "errore": None,
                  "grezzo": grezzo, "conversione": conv}
        with self.assertLogs("update_live_odds", level="INFO"):
            riga = U.registra_log_lega("soccer_epl", blocco)
        self.assertIn("eventi=3", riga)
        self.assertIn("eventi con almeno un libro=3", riga)
        self.assertIn(f"eventi con Pinnacle={conv['n_eventi_con_pinnacle']}", riga)
        self.assertIn(f"bookmaker nella risposta grezza={grezzo['n_coppie_evento_bookmaker']}",
                      riga)
        self.assertIn("- OK", riga)

    def _get(self, risposte_per_sport):
        def get(url, params=None, timeout=None):
            sport = url.rstrip("/").split("/")[-2]
            return risposte_per_sport.get(sport, _risposta([]))
        return get


class TestDaCapoAFondoSuDatiReali(unittest.TestCase):
    """Sonda -> writer -> file in tmp -> carica_quote_live -> indice -> cerca_quote."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        grezze = _dir_grezza(os.path.join(cls.tmp.name, "grezze"))
        cls.out = os.path.join(cls.tmp.name, "database", "live_odds.json")
        with redirect_stdout(io.StringIO()):
            codice, _r = U.esegui(chiave="", fixture=grezze, out=cls.out, dry_run=False)
        assert codice == U.ESITO_OK, codice
        cls.payload = mo.carica_quote_live(cls.out)
        cls.dati = mo.indice_partite(cls.payload)
        cls.attesi = {}
        for sport_key in U.LEGA_SPORT_KEY.values():
            for evento in _snapshot(sport_key)["events"]:
                cls.attesi[evento["id"]] = evento

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_il_file_si_legge_e_tutti_i_nomi_si_abbinano(self):
        self.assertIsNotNone(self.payload)
        self.assertEqual(96, self.dati["n_eventi"])
        self.assertEqual(self.dati["n_eventi"], self.dati["n_indicizzati"])
        self.assertEqual([], self.dati["non_abbinati"])

    def test_ogni_evento_della_sonda_con_bookmaker_ha_almeno_un_libro(self):
        visti = 0
        for evento in mo.eventi_quote(self.payload):
            atteso = self.attesi[evento["id"]]
            if not atteso["bookmakers"]:
                continue
            visti += 1
            with self.subTest(evento=evento["id"]):
                self.assertGreaterEqual(len(evento["libri"]), 1)
                self.assertEqual(len(atteso["bookmakers"]), len(evento["libri"]))
        self.assertEqual(96, visti)

    def test_cerca_quote_ritrova_ogni_partita_con_le_sue_quote(self):
        for evento in mo.eventi_quote(self.payload):
            trovato = mo.cerca_quote(self.dati["indice"], evento["home_team"],
                                     evento["away_team"], evento["commence_time"])
            with self.subTest(evento=evento["id"]):
                self.assertIsNotNone(trovato)
                self.assertEqual(evento["id"], trovato["id"])
                self.assertGreater(len(trovato["libri"]), 0)

    def test_pinnacle_e_trovato_dove_lo_trovava_la_sonda(self):
        attesi_pinnacle = {i for i, e in self.attesi.items()
                           if any(b.get("key") == "pinnacle" for b in e["bookmakers"])}
        trovati = set()
        for evento in mo.eventi_quote(self.payload):
            prob = mo.probabilita_mercato(evento["libri"])
            if prob["fonte"] == mo.FONTE_PINNACLE:
                trovati.add(evento["id"])
            with self.subTest(evento=evento["id"]):
                self.assertEqual(evento["id"] in attesi_pinnacle, prob["primario_presente"])
        self.assertEqual(attesi_pinnacle, trovati)
        self.assertEqual(93, len(trovati), "93 dei 96 eventi della sonda hanno Pinnacle")

    def test_le_terne_de_vig_sommano_a_uno(self):
        fonti = {}
        for evento in mo.eventi_quote(self.payload):
            prob = mo.probabilita_mercato(evento["libri"])
            fonti[prob["fonte"]] = fonti.get(prob["fonte"], 0) + 1
            with self.subTest(evento=evento["id"]):
                self.assertIsNotNone(prob["probs"])
                somma = sum(prob["probs"][e] for e in mo.ESITI)
                self.assertAlmostEqual(1.0, somma, places=12)
                for esito in mo.ESITI:
                    self.assertGreater(prob["probs"][esito], 0.0)
                    self.assertGreater(prob["odds"][esito], 1.0)
        self.assertEqual(0, fonti.get(mo.FONTE_ASSENTE, 0))
        self.assertEqual({mo.FONTE_PINNACLE: 93, mo.FONTE_MEDIA_LIBRI: 3}, fonti)

    def test_le_quote_sono_quelle_della_sonda(self):
        """Nessuna rielaborazione: la quota nel file e' quella della fonte."""
        for evento in mo.eventi_quote(self.payload):
            atteso = {b["key"]: b["h2h"] for b in self.attesi[evento["id"]]["bookmakers"]}
            for libro in evento["libri"]:
                with self.subTest(evento=evento["id"], libro=libro["key"]):
                    self.assertEqual(atteso[libro["key"]], libro["h2h"])


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
