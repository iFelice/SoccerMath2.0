"""Guardia di freschezza (6 ore) e allarme quote vecchie (26 ore).

Robustezza del giro quote (secondo tentativo di cron, 2026-10-10): GitHub
ritarda e a volte salta i cron, quindi il writer ha una guardia prima di
qualunque chiamata e update_database.yml ha un allarme separato.

Cosa viene provato (orologio CONGELATO su ``update_live_odds.orologio_utc``):

* **file con 2 ore** -> nessuna chiamata (``requests.get`` non toccato),
  uscita 0, log che contiene "quote fresche, nessuna chiamata", file intatto,
  nessuna chiave nel log;
* **file con 7 ore** -> chiamata (le 5 leghe), giro completo, file riscritto;
* **file assente** -> chiamata;
* **forza** -> chiamata anche con file fresco (input booleano di
  workflow_dispatch, default false);
* **fixture** -> la guardia non si applica: con ``--fixture`` non ci sono
  chiamate (e crediti) da risparmiare, e i dry-run della PR non devono mai
  essere bloccati;
* **allarme**: 25 ore -> ok (exit 0), 27 ore -> ``::error::`` con l'eta' in
  ore (exit 1), file assente -> ``::error::`` (exit 1);
* **cablaggi dei workflow**: due cron su live_odds.yml, input ``forza``,
  gruppo dedicato ``soccermath-quote``, job allarme senza ``needs`` su
  update_database.yml.

Vincoli della commessa rispettati dai test: NESSUNA chiamata reale all'API
(``requests.get`` e' sempre mockato, di default con un errore che fa fallire il
test se toccato), la chiave finta non compare mai in log, nessuno scrittura
fuori dalle cartelle temporanee.
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
WORKFLOWS_DIR = os.path.join(REPO_ROOT, ".github", "workflows")
if HERE not in sys.path:
    sys.path.insert(0, HERE)
if AUDIT_DIR not in sys.path:
    sys.path.insert(0, AUDIT_DIR)

logging.getLogger("streamlit").setLevel(logging.ERROR)

import update_live_odds as U  # noqa: E402
# Risposte REALI della sonda (PR #50) rimesse nella forma grezza dell'API:
# servono a simulare un giro completo SENZA rete (0 crediti, chiave finta).
import live_odds_raw_fixtures as GREZZE  # noqa: E402

PROBE_DIR = os.path.join(REPO_ROOT, "audit", "data", "live_odds_probe")
CHIAVE_FINTA = "chiave-di-prova-0123456789abcdef"

# ORARIO FISSO: tutti i calcoli di eta' (e i timestamp scritti nei test)
# passano da questo istante congelato.
OROLOGIO = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)


class RipristinaLogging:
    """Riabilita i log per la durata del test (stessa guardia di test_quote_live).

    Sei file di test dell'audit chiamano ``logging.disable(CRITICAL)`` a livello
    di modulo e non lo ripristiono: qui i log fanno parte del contratto in
    prova ("quote fresche, nessuna chiamata" deve essere leggibile), quindi il
    setUp li riabilita e il tearDown rimette ESATTAMENTE lo stato trovato.
    """

    def setUp(self):
        self._disable_precedente = logging.root.manager.disable
        logging.disable(logging.NOTSET)
        if hasattr(super(), "setUp"):
            super().setUp()

    def tearDown(self):
        logging.disable(self._disable_precedente)


def _ora(ore_fa: float) -> str:
    """Timestamp ``generato_il`` ``ore_fa`` ore prima dell'orologio congelato."""
    return (OROLOGIO - timedelta(hours=ore_fa)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _risposta(eventi, status=200, headers=None, testo="[]"):
    return mock.Mock(status_code=status, headers=headers or {}, json=lambda: eventi,
                     text=testo)


def _corpo_grezzo(sport_key, n_eventi=1):
    """Corpo GREZZO della risposta ``/odds`` per una lega (dati reali della sonda).

    I ``commence_time`` sono SPOSTATI a 6h dopo l'orologio congelato: con il
    filtro solo pre-partita i kickoff della sonda (09/10 e 10/10) sarebbero
    esclusi — giustamente, ma qui si prova la guardia di freschezza, non il
    filtro, e il contenuto dell'evento non entra nella prova.
    """
    snapshot = GREZZE.carica_snapshot(sport_key)
    corpo = GREZZE.risposta_grezza(snapshot, sport_key)[:n_eventi]
    kickoff = (OROLOGIO + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [{**e, "commence_time": kickoff} for e in corpo]


class _ReteFinta:
    """``requests.get`` finto: registra le chiamate e risponde con dati reali.

    Nessuna chiamata esce dal processo: il getter e' l'UNICA via d'uscita verso
    la rete nei test, e qui resta dentro la memoria.
    """

    def __init__(self, n_eventi=1, headers=None):
        self.chiamate = []
        self.headers = headers or {}
        self.n_eventi = n_eventi

    def get(self, url, params=None, timeout=None):
        self.chiamate.append((url, dict(params or {})))
        sport = url.rstrip("/").split("/")[-2]
        return _risposta(_corpo_grezzo(sport, self.n_eventi),
                         headers=dict(self.headers))

    def mai(self, *_args, **_kwargs):
        raise AssertionError("nessuna chiamata attesa: la guardia deve uscire prima")


def _leggi(percorso):
    with open(percorso, encoding="utf-8") as fh:
        return fh.read()


class TestGuardiaDiFreschezza(RipristinaLogging, unittest.TestCase):
    """Prima di QUALSIASI chiamata: file recente -> 0 crediti, uscita 0."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "live_odds.json")
        self.oriologio = mock.patch.object(U, "orologio_utc", return_value=OROLOGIO)
        self.oriologio.start()
        self.addCleanup(self.oriologio.stop)

    def _file(self, ore_fa, extra=None):
        dati = {"generato_il": _ora(ore_fa), "schema": "soccermath_live_odds_v1"}
        if extra:
            dati.update(extra)
        with open(self.out, "w", encoding="utf-8") as fh:
            json.dump(dati, fh)
        return _leggi(self.out)

    def test_file_di_2_ore_nessuna_chiamata_uscita_0(self):
        prima = self._file(2.0)
        rete = _ReteFinta()
        with mock.patch("requests.get", side_effect=rete.mai):
            with self.assertLogs("update_live_odds", level="INFO") as log:
                codice, riepilogo = U.esegui(chiave=CHIAVE_FINTA, fixture=None,
                                             out=self.out, dry_run=False)
        testo_log = "\n".join(log.output)
        self.assertEqual(U.ESITO_OK, codice, "file fresco -> uscita 0")
        self.assertEqual("quote fresche", riepilogo["motivo"])
        self.assertTrue(riepilogo["fresco"])
        self.assertAlmostEqual(2.0, riepilogo["eta_ore"], places=6)
        self.assertIn("quote fresche, nessuna chiamata", testo_log)
        self.assertNotIn(CHIAVE_FINTA, testo_log, "la chiave non compare nel log")
        self.assertEqual(prima, _leggi(self.out), "il file fresco NON viene toccato")
        self.assertEqual([], rete.chiamate, "0 chiamate: 0 crediti")

    def test_file_di_7_ore_chiama(self):
        self._file(7.0)
        rete = _ReteFinta()
        with mock.patch("requests.get", side_effect=rete.get):
            with redirect_stdout(io.StringIO()):
                codice, riepilogo = U.esegui(chiave=CHIAVE_FINTA, fixture=None,
                                             out=self.out, dry_run=False)
        self.assertEqual(U.ESITO_OK, codice)
        self.assertEqual(len(U.LEGA_SPORT_KEY), len(rete.chiamate),
                         "file vecchio: il giro chiama tutte le leghe")
        self.assertTrue(riepilogo["scritto"], "il file viene riscritto")
        self.assertEqual(OROLOGIO.strftime("%Y-%m-%dT%H:%M:%SZ"),
                         json.load(open(self.out, encoding="utf-8"))["generato_il"],
                         "nuovo timestamp dell'orologio congelato")

    def test_file_assente_chiama(self):
        rete = _ReteFinta()
        with mock.patch("requests.get", side_effect=rete.get):
            with redirect_stdout(io.StringIO()):
                codice, riepilogo = U.esegui(chiave=CHIAVE_FINTA, fixture=None,
                                             out=self.out, dry_run=False)
        self.assertEqual(U.ESITO_OK, codice)
        self.assertEqual(len(U.LEGA_SPORT_KEY), len(rete.chiamate))
        self.assertTrue(os.path.exists(self.out), "nessun file -> il giro lo scrive")

    def test_forza_scarica_con_file_fresco(self):
        prima = self._file(2.0)
        rete = _ReteFinta()
        with mock.patch("requests.get", side_effect=rete.get):
            with redirect_stdout(io.StringIO()):
                codice, riepilogo = U.esegui(chiave=CHIAVE_FINTA, fixture=None,
                                             out=self.out, dry_run=False,
                                             forza=True)
        self.assertEqual(U.ESITO_OK, codice)
        self.assertEqual(len(U.LEGA_SPORT_KEY), len(rete.chiamate),
                         "forza=true salta la guardia e chiama")
        self.assertTrue(riepilogo["scritto"])
        self.assertNotEqual(prima, _leggi(self.out))

    def test_file_alle_6_ore_esatte_non_e_piu_fresco(self):
        """La soglia e' aperta a destra: meno di 6 ore -> fresco; 6 -> si chiama."""
        self._file(6.0)
        rete = _ReteFinta()
        with mock.patch("requests.get", side_effect=rete.get):
            with redirect_stdout(io.StringIO()):
                codice, _r = U.esegui(chiave=CHIAVE_FINTA, fixture=None,
                                      out=self.out, dry_run=False)
        self.assertEqual(U.ESITO_OK, codice)
        self.assertEqual(len(U.LEGA_SPORT_KEY), len(rete.chiamate))

    def test_file_corrotto_non_blocca_la_chiamata(self):
        """generato_il illeggibile = freschezza non dimostrabile -> si chiama."""
        with open(self.out, "w", encoding="utf-8") as fh:
            fh.write('{"generato_il": "ieri-tempi-misti"}')
        rete = _ReteFinta()
        with mock.patch("requests.get", side_effect=rete.get):
            with redirect_stdout(io.StringIO()):
                codice, _r = U.esegui(chiave=CHIAVE_FINTA, fixture=None,
                                      out=self.out, dry_run=False)
        self.assertEqual(U.ESITO_OK, codice)
        self.assertEqual(len(U.LEGA_SPORT_KEY), len(rete.chiamate))

    def test_la_guardia_non_si_applica_alle_fixture(self):
        """I dry-run su fixture (0 crediti) non devono mai essere bloccati."""
        self._file(2.0)
        with mock.patch("requests.get", side_effect=AssertionError("fixture: nessuna rete")):
            with redirect_stdout(io.StringIO()):
                codice, riepilogo = U.esegui(chiave="", fixture=PROBE_DIR,
                                             out=self.out, dry_run=False)
        self.assertEqual(U.ESITO_OK, codice)
        self.assertTrue(riepilogo["scritto"], "con --fixture il giro prosegue e scrive")
        self.assertNotEqual("quote fresche", riepilogo.get("motivo"))

    def test_nessuna_chiamata_anche_senza_chiave_se_il_file_e_fresco(self):
        """La guardia e' prima di tutto: 0 crediti anche senza secret."""
        self._file(1.0)
        with mock.patch("requests.get", side_effect=AssertionError("nessuna chiamata attesa")):
            with self.assertLogs("update_live_odds", level="INFO"):
                codice, riepilogo = U.esegui(chiave=None, fixture=None,
                                             out=self.out, dry_run=False)
        self.assertEqual(U.ESITO_OK, codice)
        self.assertEqual("quote fresche", riepilogo["motivo"])


class TestAllarmeQuoteVecchie(RipristinaLogging, unittest.TestCase):
    """Job separato di update_database.yml: 25 ore ok, 27 ore e assente ::error::."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "live_odds.json")
        self.oriologio = mock.patch.object(U, "orologio_utc", return_value=OROLOGIO)
        self.oriologio.start()
        self.addCleanup(self.oriologio.stop)

    def _file(self, ore_fa, raw=None):
        if raw is not None:
            with open(self.out, "w", encoding="utf-8") as fh:
                fh.write(raw)
            return
        with open(self.out, "w", encoding="utf-8") as fh:
            json.dump({"generato_il": _ora(ore_fa)}, fh)

    def _cli(self):
        """Il comando esatto del workflow, con stdout catturato e rete bloccata."""
        buf = io.StringIO()
        with mock.patch("requests.get",
                        side_effect=AssertionError("l'allarme non chiama l'API")):
            with redirect_stdout(buf):
                rc = U.main(["--allarme-vecchie", "--out", self.out])
        return rc, buf.getvalue()

    def test_25_ore_ok(self):
        self._file(25.0)
        rc, out = self._cli()
        self.assertEqual(U.ESITO_OK, rc, out)
        self.assertIn("OK:", out)
        self.assertNotIn("::error::", out)
        self.assertIn("25.0 ore", out, "l'eta' dichiarata in ore")

    def test_27_ore_errore_con_eta_in_ore(self):
        self._file(27.0)
        rc, out = self._cli()
        self.assertEqual(U.ESITO_NULLA_SCRITTO, rc, "exit 1 -> workflow fallito")
        self.assertIn("::error::", out)
        self.assertIn("27.0 ore", out, "l'eta' in ore va nel messaggio")
        self.assertIn("soglia 26 ore", out)

    def test_file_assente_errore(self):
        rc, out = self._cli()
        self.assertEqual(U.ESITO_NULLA_SCRITTO, rc, "nessun file -> workflow fallito")
        self.assertIn("::error::", out)
        self.assertIn("assente", out)

    def test_26_ore_esatte_ok(self):
        """La soglia e' "piu' vecchio di 26 ore": a 26 ore exacte l'allarme tace."""
        self._file(26.0)
        rc, out = self._cli()
        self.assertEqual(U.ESITO_OK, rc, out)
        self.assertNotIn("::error::", out)

    def test_generato_il_assente_errore(self):
        self._file(0, raw='{"qualcosaltro": 1}')
        rc, out = self._cli()
        self.assertEqual(U.ESITO_NULLA_SCRITTO, rc)
        self.assertIn("::error::", out)
        self.assertIn("generato_il assente", out)

    def test_file_corrotto_errore(self):
        self._file(0, raw="non json")
        rc, out = self._cli()
        self.assertEqual(U.ESITO_NULLA_SCRITTO, rc)
        self.assertIn("::error::", out)

    def test_uscita_0_non_stampa_error(self):
        self._file(1.0)
        rc, out = self._cli()
        self.assertEqual(U.ESITO_OK, rc, out)
        self.assertIn("fresco", out)


class TestSoglieECablaggi(unittest.TestCase):
    """Soglie dichiarate e cablaggi dei tre workflow (testo, nessuna dipendenza)."""

    def _yml(self, nome):
        with open(os.path.join(WORKFLOWS_DIR, nome), encoding="utf-8") as fh:
            return fh.read()

    def test_le_soglie_sono_6_e_26_ore(self):
        self.assertEqual(6.0, U.SOGGIA_FRESCHEZZA_ORE)
        self.assertEqual(26.0, U.SOGGIA_ALLARME_ORE)

    def test_live_odds_ha_i_due_cron(self):
        src = self._yml("live_odds.yml")
        self.assertIn("cron: '17 8 * * *'", src)
        self.assertIn("cron: '47 10 * * *'", src, "secondo tentativo mancante")

    def test_live_odds_ha_l_input_forza_booleano_default_false(self):
        src = self._yml("live_odds.yml")
        self.assertIn("forza:", src)
        self.assertIn("type: boolean", src)
        self.assertIn("default: false", src)
        self.assertIn('--forza', src, "il workflow passa forza al writer")

    def test_live_odds_ha_il_gruppo_dedicato(self):
        src = self._yml("live_odds.yml")
        self.assertIn("group: soccermath-quote", src)
        self.assertIn("cancel-in-progress: false", src)
        self.assertNotIn("group: soccermath-data", src,
                         "le quote non stanno piu' nel gruppo condiviso")

    def test_gli_altri_due_condividono_soccermath_data(self):
        for nome in ("update_database.yml", "update_xg.yml"):
            src = self._yml(nome)
            self.assertIn("group: soccermath-data", src, nome)
            self.assertIn("cancel-in-progress: false", src, nome)

    def test_l_allarme_e_un_job_separato_senza_needs(self):
        src = self._yml("update_database.yml")
        self.assertIn("allarme-quote-vecchie:", src)
        self.assertIn("--allarme-vecchie", src)
        # Nessun `needs` nel file: l'allarme gira in parallelo e non puo'
        # bloccare ne' ritardare il commit dei dati.
        self.assertNotIn("needs:", src)

    def test_l_allarme_non_tocca_secret_e_non_pusha(self):
        src = self._yml("update_database.yml")
        blocco_allarme = src.split("allarme-quote-vecchie:", 1)[1]
        self.assertNotIn("ODDS_API_KEY", blocco_allarme)
        self.assertNotIn("FOOTBALL_DATA_API_KEY", blocco_allarme)
        self.assertNotIn("git push", blocco_allarme)


if __name__ == "__main__":
    unittest.main()
