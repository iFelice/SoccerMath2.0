"""Quote 1X2 dal vivo: de-vig, riserva sulla media, partite senza quote, versione.

Cosa viene provato (punti 2, 3, 7 e 9 della commessa "quote live nel Top Mix"):

* **de-vig proporzionale**: la somma delle tre probabilita' e' 1 (a precisione
  macchina), una quota <= 1 o mancante NON produce probabilita' inventate;
* **riserva sulla media**: se Pinnacle manca, la probabilita' e' la media delle
  probabilita' de-vigate dei libri disponibili e la fonte e' dichiarata
  (``media_libri``, con il numero di libri) riga per riga;
* **partite senza quote**: nessuna terna valida -> ``probs is None`` e fonte
  ``nessuna_quota``; la partita e' esclusa dal Top Mix e segnalata, mai riempita
  con un valore di default;
* **versione del selettore**: ``topmix_mercato_v3`` e' la versione in prova e
  ``SELECTOR_VERSION_CURRENT`` la espone (il test di fingerprint
  ``test_versione_selettore.py`` ne impone l'impronta);
* **l'app non chiama la fonte**: nessun codice di ``SoccerMath/app.py`` e
  ``market_odds.py`` fa richieste HTTP verso The Odds API (solo
  ``update_live_odds.py``, eseguito dal workflow, puo' farlo).
"""
from __future__ import annotations

import ast
import logging
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

logging.getLogger("streamlit").setLevel(logging.ERROR)

import market_odds as mo  # noqa: E402
import prediction_registry as R  # noqa: E402

APP_PATH = os.path.join(HERE, "app.py")
MARKET_PATH = os.path.join(HERE, "market_odds.py")
WRITER_PATH = os.path.join(HERE, "update_live_odds.py")


def libri(*terne, chiavi=None):
    """Lista di libri con le terne (home, draw, away) date."""
    out = []
    for i, t in enumerate(terne):
        chiave = (chiavi[i] if chiavi else f"book{i}")
        out.append({"key": chiave, "title": chiave,
                    "h2h": {"home": t[0], "draw": t[1], "away": t[2]}})
    return out


class TestDevigProporzionale(unittest.TestCase):
    def test_somma_delle_probabilita_e_uno(self):
        for terna in [(2.0, 3.5, 4.0), (1.5, 4.2, 6.8), (1.02, 21.0, 41.0),
                      (3.34, 3.23, 2.36), (10.0, 10.0, 10.0)]:
            p = mo.devig_proporzionale(terna)
            self.assertIsNotNone(p, terna)
            self.assertAlmostEqual(1.0, sum(p), places=12, msg=str(terna))
            for x in p:
                self.assertGreater(x, 0.0)
                self.assertLess(x, 1.0)

    def test_formula_proporzionale_esatta(self):
        # 1/2, 1/4, 1/4 -> somma 1.0 -> probabilita' 0.5, 0.25, 0.25
        self.assertEqual((0.5, 0.25, 0.25), mo.devig_proporzionale((2.0, 4.0, 4.0)))

    def test_quote_uguali_danno_probabilita_uguali(self):
        p = mo.devig_proporzionale((3.0, 3.0, 3.0))
        self.assertAlmostEqual(1 / 3, p[0], places=12)
        self.assertAlmostEqual(p[0], p[1], places=12)
        self.assertAlmostEqual(p[1], p[2], places=12)

    def test_quote_non_valide_non_producono_probabilita(self):
        for terna in [(1.0, 3.5, 4.0), (0.9, 3.5, 4.0), (2.0, None, 4.0),
                      (2.0, 3.5, float("nan")), (2.0, 3.5, float("inf")),
                      (2.0, 3.5), (2.0, 3.5, 4.0, 5.0), None,
                      (2.0, 3.5, "4.0"), (True, 3.5, 4.0)]:
            self.assertIsNone(mo.devig_proporzionale(terna), str(terna))

    def test_piu_alta_la_quota_piu_bassa_la_probabilita(self):
        p = mo.devig_proporzionale((1.5, 3.5, 8.0))
        self.assertGreater(p[0], p[1])
        self.assertGreater(p[1], p[2])

    def test_coincide_con_la_formula_della_pr49(self):
        """Stessa formula di ``backtest_experiment_all.devig_1x2`` (PR #49)."""
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "audit"))
        from backtest_experiment_all import devig_1x2  # noqa: E402
        for terna in [(2.1, 3.4, 3.6), (1.72, 3.9, 4.75), (1.35, 5.0, 9.5)]:
            atteso = devig_1x2(*terna)
            ottenuto = mo.devig_proporzionale(terna)
            for a, o in zip(atteso, ottenuto):
                self.assertAlmostEqual(a, o, places=12, msg=str(terna))


class TestTernariaH2h(unittest.TestCase):
    def test_forma_del_writer(self):
        self.assertEqual((2.0, 3.0, 4.0), mo.ternaria_h2h(
            {"key": "x", "h2h": {"home": 2.0, "draw": 3.0, "away": 4.0}}))

    def test_forma_piatta_degli_snapshot(self):
        self.assertEqual((2.0, 3.0, 4.0),
                         mo.ternaria_h2h({"key": "x", "home": 2.0, "draw": 3.0, "away": 4.0}))

    def test_ternaria_incompleta(self):
        self.assertIsNone(mo.ternaria_h2h({"key": "x", "h2h": {"home": 2.0, "draw": 3.0}}))
        self.assertIsNone(mo.ternaria_h2h({"key": "x"}))
        self.assertIsNone(mo.ternaria_h2h(None))


class TestFonteDellaProbabilita(unittest.TestCase):
    PINNACLE = {"key": "pinnacle", "title": "Pinnacle",
                "h2h": {"home": 3.34, "draw": 3.23, "away": 2.36}}
    ALTRO = {"key": "unibet_nl", "title": "Unibet", "h2h": {"home": 3.3, "draw": 3.4, "away": 2.33}}
    TERZO = {"key": "betclic_fr", "title": "Betclic", "h2h": {"home": 3.12, "draw": 3.2, "away": 2.23}}

    def test_pinnacle_presente_e_la_fonte(self):
        out = mo.probabilita_mercato([self.ALTRO, self.PINNACLE, self.TERZO])
        self.assertEqual(mo.FONTE_PINNACLE, out["fonte"])
        self.assertEqual(["pinnacle"], out["libri_usati"])
        self.assertEqual(3, out["n_libri"])
        self.assertTrue(out["primario_presente"])
        atteso = mo.devig_proporzionale((3.34, 3.23, 2.36))
        for k, esito in enumerate(mo.ESITI):
            self.assertAlmostEqual(atteso[k], out["probs"][esito], places=12)
        self.assertAlmostEqual(1.0, sum(out["probs"].values()), places=12)
        # la quota mostrata e' quella di Pinnacle, la stessa fonte della probabilita'
        self.assertEqual(2.36, out["odds"]["2"])

    def test_senza_pinnacle_riserva_sulla_media_dei_libri(self):
        out = mo.probabilita_mercato([self.ALTRO, self.TERZO])
        self.assertEqual(mo.FONTE_MEDIA_LIBRI, out["fonte"])
        self.assertFalse(out["primario_presente"])
        self.assertEqual(2, out["n_libri"])
        self.assertEqual({"unibet_nl", "betclic_fr"}, set(out["libri_usati"]))
        p1 = mo.devig_proporzionale((3.3, 3.4, 2.33))
        p2 = mo.devig_proporzionale((3.12, 3.2, 2.23))
        for k, esito in enumerate(mo.ESITI):
            self.assertAlmostEqual((p1[k] + p2[k]) / 2, out["probs"][esito], places=12)
        # la media di due distribuzioni di probabilita' somma ancora a 1
        self.assertAlmostEqual(1.0, sum(out["probs"].values()), places=12)
        # la quota di riserva e' la media delle quote degli stessi libri
        self.assertAlmostEqual((2.33 + 2.23) / 2, out["odds"]["2"], places=12)

    def test_pinnacle_senza_terna_valida_fa_scattare_la_riserva(self):
        pin_rotto = {"key": "pinnacle", "h2h": {"home": 3.34, "draw": None, "away": 2.36}}
        out = mo.probabilita_mercato([pin_rotto, self.ALTRO])
        self.assertEqual(mo.FONTE_MEDIA_LIBRI, out["fonte"])
        self.assertTrue(out["primario_presente"], "Pinnacle c'e', ma senza terna valida")
        self.assertEqual(["unibet_nl"], out["libri_usati"])

    def test_un_solo_libro_senza_pinnacle(self):
        out = mo.probabilita_mercato([self.ALTRO])
        self.assertEqual(mo.FONTE_MEDIA_LIBRI, out["fonte"])
        self.assertEqual(1, out["n_libri"])
        atteso = mo.devig_proporzionale((3.3, 3.4, 2.33))
        for k, esito in enumerate(mo.ESITI):
            self.assertAlmostEqual(atteso[k], out["probs"][esito], places=12)

    def test_nessuna_quota(self):
        for libri_ in ([], None, [{"key": "x"}],
                       [{"key": "x", "h2h": {"home": 1.0, "draw": 3.0, "away": 4.0}}],
                       [{"key": "x", "h2h": {"home": None, "draw": 3.0, "away": 4.0}}]):
            out = mo.probabilita_mercato(libri_)
            self.assertIsNone(out["probs"], str(libri_))
            self.assertIsNone(out["odds"], str(libri_))
            self.assertEqual(mo.FONTE_ASSENTE, out["fonte"], str(libri_))
            self.assertEqual(0, out["n_libri"], str(libri_))


class TestPartiteSenzaQuote(unittest.TestCase):
    def test_la_partita_senza_quote_e_elencata_non_riempita(self):
        """``indice_partite`` + ``probabilita_mercato``: nessun valore di default."""
        payload = {"leghe": {"Serie A": {"eventi": [
            {"id": "1", "commence_time": "2026-10-10T13:00:00Z",
             "home_team": "Inter", "away_team": "Roma", "libri": []},
        ]}}}
        dati = mo.indice_partite(payload)
        evento = mo.cerca_quote(dati["indice"], "Inter", "Roma")
        self.assertIsNotNone(evento, "la partita c'e', ma senza libri")
        out = mo.probabilita_mercato(evento["libri"])
        self.assertIsNone(out["probs"])
        self.assertEqual(mo.FONTE_ASSENTE, out["fonte"])

    def test_partita_assente_dalla_fonte(self):
        dati = mo.indice_partite({"leghe": {"Serie A": {"eventi": []}}})
        self.assertIsNone(mo.cerca_quote(dati["indice"], "Inter", "Roma"))


class TestVersioneSelettore(unittest.TestCase):
    def test_la_versione_in_prova_e_topmix_mercato_v3(self):
        self.assertEqual("topmix_mercato_v3", R.SELECTOR_VERSION_MERCATO_V3)
        self.assertEqual("topmix_mercato_v3", R.SELECTOR_VERSION_CURRENT)

    def test_le_versioni_precedenti_restanto_leggibili(self):
        self.assertEqual("topmix_gate025_ens06_v1", R.SELECTOR_VERSION_PRE_1X2)
        self.assertEqual("topmix_1x2_gate025_ens06_v2", R.SELECTOR_VERSION_MODELLO_1X2)
        self.assertNotEqual(R.SELECTOR_VERSION_CURRENT, R.SELECTOR_VERSION_MODELLO_1X2)

    def test_il_fingerprint_ha_l_impronta_della_versione_in_prova(self):
        import test_versione_selettore as T
        self.assertIn(R.SELECTOR_VERSION_CURRENT, T.IMPRONTE,
                      "SELECTOR_VERSION_CURRENT senza impronta in test_versione_selettore.IMPRONTE")
        self.assertEqual(T.IMPRONTE[R.SELECTOR_VERSION_CURRENT], T.impronta_attuale(),
                         "l'impronta non corrisponde al codice: alza la versione o aggiorna IMPRONTE")

    def test_l_ombra_dei_modelli_ha_la_sua_versione(self):
        self.assertEqual("topmix_ombra_1x2_v1", R.SELECTOR_VERSION_OMBRA_1X2)
        self.assertEqual(R.SELECTOR_VERSION_OMBRA_1X2,
                         R.SELECTOR_VERSION_OMBRA_BY_FAMIGLIA[R.OMBRA_FAMIGLIA_1X2])
        # tre famiglie di ombra, tre versioni distinte: nessuna sovrascrittura
        versioni = list(R.SELECTOR_VERSION_OMBRA_BY_FAMIGLIA.values())
        self.assertEqual(len(versioni), len(set(versioni)))


class TestLAppNonChiamaLaFonte(unittest.TestCase):
    """Vincolo della commessa: l'app legge il file, non chiama l'API."""

    def test_nessuna_chiamata_http_in_market_odds(self):
        src = open(MARKET_PATH, encoding="utf-8").read()
        self.assertNotIn("import requests", src)
        self.assertNotIn("the-odds-api.com", src.replace("The Odds API", ""))

    def test_nessuna_chiamata_http_alla_fonte_in_app(self):
        src = open(APP_PATH, encoding="utf-8").read()
        albero = ast.parse(src)
        # Nessun URL della fonte quote: l'host non compare in nessuna stringa.
        self.assertNotIn("api.the-odds-api.com", src)
        # E nessuna chiamata ``requests.*`` verso un host di quote: gli host
        # delle GET/POST dell'app sono football-data (calendario) e i backend
        # del Registro.
        host_chiamati = set()
        for nodo in ast.walk(albero):
            if not isinstance(nodo, ast.Call):
                continue
            fn = nodo.func
            if not (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                    and fn.value.id == "requests"):
                continue
            for arg in nodo.args[:1]:
                if isinstance(arg, ast.JoinedStr):
                    host_chiamati.update(
                        v.value for v in arg.values
                        if isinstance(v, ast.Constant) and isinstance(v.value, str))
                elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    host_chiamati.add(arg.value)
        self.assertTrue(host_chiamati, "fixture non valida: nessuna chiamata requests trovata")
        for url in host_chiamati:
            self.assertNotIn("the-odds-api", url, url)
        self.assertTrue(any("api.football-data.org" in u for u in host_chiamati),
                        "l'app continua a usare football-data per il calendario")

    def test_solo_il_writer_conosce_l_host(self):
        for path in (APP_PATH, MARKET_PATH):
            self.assertNotIn("api.the-odds-api.com", open(path, encoding="utf-8").read(), path)
        self.assertIn("api.the-odds-api.com", open(WRITER_PATH, encoding="utf-8").read())

    def test_il_writer_legge_la_chiave_solo_dall_ambiente(self):
        src = open(WRITER_PATH, encoding="utf-8").read()
        self.assertIn('os.environ.get(NOME_ENV_CHIAVE)', src)
        self.assertNotIn("ODDS_API_KEY=", src.replace("NOME_ENV_CHIAVE = \"ODDS_API_KEY\"", ""))




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


class TestLetturaDelFile(RipristinaLogging, unittest.TestCase):
    def setUp(self):
        super().setUp()
        # ``carica_quote_live`` avvisa una volta per processo quando il file non
        # c'e' (poi passa in DEBUG): qui si parte sempre dallo stato iniziale.
        mo._AVVISI_DATI.discard("file_assente")

    def test_file_assente_ritorna_none_con_log(self):
        with self.assertLogs("market_odds", level="WARNING") as cat:
            out = mo.carica_quote_live("/tmp/definitivamente_assente_live_odds.json")
        self.assertIsNone(out)
        self.assertIn("non presente", "\n".join(cat.output))

    def test_file_non_json_ritorna_none_con_log(self):
        path = "/tmp/live_odds_corrotto.json"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{non e' json")
        try:
            with self.assertLogs("market_odds", level="WARNING"):
                self.assertIsNone(mo.carica_quote_live(path))
        finally:
            os.unlink(path)

    def test_file_senza_leghe_ritorna_none(self):
        path = "/tmp/live_odds_senza_leghe.json"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"schema": "x"}')
        try:
            with self.assertLogs("market_odds", level="WARNING"):
                self.assertIsNone(mo.carica_quote_live(path))
        finally:
            os.unlink(path)

    def test_payload_valido(self):
        path = "/tmp/live_odds_ok.json"
        payload = {"leghe": {"Serie A": {"eventi": [
            {"id": "1", "commence_time": "2026-10-10T13:00:00Z",
             "home_team": "Inter", "away_team": "Roma",
             "libri": [{"key": "pinnacle", "h2h": {"home": 2.0, "draw": 3.4, "away": 4.0}}]}]}}}
        with open(path, "w", encoding="utf-8") as fh:
            import json
            json.dump(payload, fh)
        try:
            letto = mo.carica_quote_live(path)
            self.assertIsNotNone(letto)
            dati = mo.indice_partite(letto)
            self.assertEqual(1, dati["n_indicizzati"])
            out = mo.probabilita_mercato(
                mo.cerca_quote(dati["indice"], "Inter", "Roma")["libri"])
            self.assertEqual(mo.FONTE_PINNACLE, out["fonte"])
            self.assertAlmostEqual(1.0, sum(out["probs"].values()), places=12)
        finally:
            os.unlink(path)


class TestCostanti(unittest.TestCase):
    def test_soglie_e_limiti_della_commessa(self):
        self.assertEqual(0.55, mo.SOGLIA_TOPMIX_MERCATO)
        self.assertEqual(0.55, mo.SOGLIA_ACCORDO)
        self.assertEqual(5, mo.MASSIMO_RIGHE_MULTIPLA)
        self.assertEqual(1, mo.MINIMO_RIGHE_MULTIPLA)
        self.assertEqual("pinnacle", mo.BOOKMAKER_PRIMARIO)

    def test_le_soglie_coincidono_con_quelle_del_registro(self):
        """La soglia del mercato e' quella usata dalla PR #49 (0,55)."""
        self.assertTrue(math.isclose(0.55, mo.SOGLIA_TOPMIX_MERCATO))


if __name__ == "__main__":
    unittest.main(verbosity=2)
