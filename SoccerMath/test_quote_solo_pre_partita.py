"""Quote SOLO pre-partita: una quota vale solo se l'acquisizione precede il kickoff.

Cosa viene provato (commessa "quote solo pre-partita"):

* **scrittore**: un evento con ``commence_time`` gia' passato ALL'ISTANTE della
  chiamata NON entra nel file (escluso e contato in
  ``grezzo.eventi_iniziati_esclusi`` per lega + ``n_eventi_iniziati_esclusi``
  nel payload, con WARNING); un evento a 10 minuti dal via ENTRA; un
  ``commence_time`` corrotto NON scarta (non si inventa uno stato);
* **fixture**: la lista grezza non viene filtrata (nessun istante credibile,
  il dry-run resta stabile per sempre) e lo snapshot compattato si filtra
  contro il suo ``scaricato_il`` — un secondo run sullo stesso snapshot da lo
  STESSO file (l'orologio reale non c'entra);
* **filtro applicazione** (``prediction_registry.righe_solo_pre_partita``,
  orologio CONGELATO su ``2026-10-10T12:00:00Z``): kickoff futuro -> tenuta;
  kickoff <= istante delle quote -> scartata (regola dell'acquisizione);
  kickoff <= ora del calcolo -> scartata (regola del calcolo); calendario
  stale (``utcDate`` futuro ma ``commence_time`` passato) -> scartata;
  kickoff assente -> tenuta;
* **al click del pulsante**: con calendario stale l'evento iniziato da 17
  minuti produce la riga ma NON entra (nessuna riga nuova, nessun aggiornamento
  dell'ultima registrazione), mentre 10 minuti prima del via entra; la PRIMA
  registrazione non viene mai toccata (il rinfresco con quote regolari
  aggiorna l'ultima e preserva la ``*_prima``); il cablaggi del sorgente
  (``righe_solo_pre_partita`` dopo le righe esistenti, che restano intatte).

Nessuna chiamata API: ``requests.get`` e' sempre mockato, gli orologi sono
congelati, i file stanno in tmp.
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
if HERE not in sys.path:
    sys.path.insert(0, HERE)

logging.getLogger("streamlit").setLevel(logging.ERROR)

import market_odds as mo  # noqa: E402
import prediction_registry as R  # noqa: E402
import update_live_odds as U  # noqa: E402
import app  # noqa: E402

OROLOGIO = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
CHIAVE_FINTA = "chiave-di-prova-0123456789abcdef"


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class RipristinaLogging:
    """Riabilita i log per la durata del test (stessa guardia dei file affini)."""

    def setUp(self):
        self._disable_precedente = logging.root.manager.disable
        logging.disable(logging.NOTSET)
        if hasattr(super(), "setUp"):
            super().setUp()

    def tearDown(self):
        logging.disable(self._disable_precedente)


# ---------------------------------------------------------------------------
# Scrittore
# ---------------------------------------------------------------------------
def _evento_anidato(id_, home, away, commence):
    """Corpo GREZZO dell'endpoint /odds: bookmakers annidati + una terna h2h."""
    return {"id": id_, "commence_time": commence,
            "home_team": home, "away_team": away,
            "bookmakers": [{"key": "pinnacle", "title": "Pinnacle", "last_update": commence,
                            "markets": [{"key": "h2h", "outcomes": [
                                {"name": home, "price": 1.62},
                                {"name": away, "price": 6.0},
                                {"name": "Draw", "price": 4.1}]}]}]}


def _risposta(eventi, status=200, headers=None, testo="[]"):
    return mock.Mock(status_code=status, headers=headers or {},
                     json=lambda: eventi, text=testo)


class TestScrittoreSoloPrePartita(RipristinaLogging, unittest.TestCase):
    """Il file NON puo' contenere quote prese dopo il fischio d'inizio."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "live_odds.json")
        # orologio CONGELATO: nessun test dipende da quando gira
        self._orologio = mock.patch.object(U, "orologio_utc",
                                           return_value=OROLOGIO)
        self._orologio.start()
        self.addCleanup(self._orologio.stop)

    def _esegui_corpo(self, eventi_per_leaga):
        """eventi_per_leaga: lista degli eventi che OGNI lega restituisce."""

        def get(url, params=None, timeout=None):
            return _risposta(eventi_per_leaga)

        with mock.patch("requests.get", side_effect=get):
            with redirect_stdout(io.StringIO()):
                codice, riepilogo = U.esegui(chiave=CHIAVE_FINTA, fixture=None,
                                             out=self.out, dry_run=False)
        return codice, riepilogo

    def test_iniziato_da_17_minuti_non_entra_nel_file(self):
        iniziato = _evento_anidato("in-1", "Inter", "Roma",
                                   _iso(OROLOGIO - timedelta(minutes=17)))
        futuro = _evento_anidato("fu-1", "Milan", "Napoli",
                                 _iso(OROLOGIO + timedelta(minutes=10)))
        with self.assertLogs("update_live_odds", level="WARNING") as log:
            codice, riepilogo = self._esegui_corpo([iniziato, futuro])
        self.assertEqual(U.ESITO_OK, codice, riepilogo.get("motivo"))
        self.assertTrue(riepilogo["scritto"])
        self.assertIn("gia' iniziati", "\n".join(log.output))
        payload = json.load(open(self.out, encoding="utf-8"))
        ids = [e["id"] for lega in payload["leghe"].values() for e in lega["eventi"]]
        self.assertNotIn("in-1", ids, "l'evento iniziato NON deve entrare nel file")
        self.assertEqual(len(U.LEGA_SPORT_KEY), ids.count("fu-1"))
        self.assertEqual(len(U.LEGA_SPORT_KEY), payload["n_eventi_iniziati_esclusi"])
        for blocco in payload["leghe"].values():
            self.assertEqual(1, blocco["grezzo"]["eventi_iniziati_esclusi"])
            # i conteggi GREZZI della risposta arrivata restano intatti:
            # 2 eventi arrivati, 1 escluso, 1 scritto
            self.assertEqual(2, blocco["grezzo"]["n_eventi"])
            self.assertEqual(1, blocco["n_eventi"])
            for e in blocco["eventi"]:
                self.assertGreater(e["commence_time"], payload["generato_il"],
                                   "nel file solo kickoff futuri rispetto all'acquisizione")

    def test_a_10_minuti_dal_via_entra_nel_file(self):
        vicino = _evento_anidato("vicino-1", "Inter", "Roma",
                                 _iso(OROLOGIO + timedelta(minutes=10)))
        codice, riepilogo = self._esegui_corpo([vicino])
        self.assertEqual(U.ESITO_OK, codice, riepilogo.get("motivo"))
        payload = json.load(open(self.out, encoding="utf-8"))
        ids = [e["id"] for lega in payload["leghe"].values() for e in lega["eventi"]]
        self.assertEqual(len(U.LEGA_SPORT_KEY), ids.count("vicino-1"))
        self.assertEqual(0, payload["n_eventi_iniziati_esclusi"])

    def test_kickoff_malformato_non_scarta(self):
        """Lo stato di partita NON si inventa: kickoff illeggibile -> resta."""
        strano = _evento_anidato("strano-1", "Inter", "Roma", "non-una-data")
        codice, riepilogo = self._esegui_corpo([strano])
        self.assertEqual(U.ESITO_OK, codice, riepilogo.get("motivo"))
        payload = json.load(open(self.out, encoding="utf-8"))
        ids = [e["id"] for lega in payload["leghe"].values() for e in lega["eventi"]]
        self.assertEqual(len(U.LEGA_SPORT_KEY), ids.count("strano-1"))
        self.assertEqual(0, payload["n_eventi_iniziati_esclusi"])


class TestFixtureSoloPrePartita(RipristinaLogging, unittest.TestCase):
    """Due forme di fixture: lista grezza (non filtrare) e snapshot (filtrare)."""

    SCARICATO = "2026-10-08T23:30:00Z"

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "snap")
        os.makedirs(self.dir)

    def _snapshot(self, eventi):
        return {"scaricato_il": self.SCARICATO,
                "http": {"status": 200, "crediti": {"residui": 400}},
                "events": eventi}

    def _scrivi(self, nome, contenuto):
        path = os.path.join(self.dir, f"odds_api_{nome}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(contenuto, fh)
        return path

    def test_snapshot_filtrata_su_scaricato_il_e_deterministica(self):
        eventi = [
            _evento_anidato("passato", "Inter", "Roma", "2026-10-08T20:00:00Z"),
            _evento_anidato("futuro", "Milan", "Napoli", "2026-10-12T18:00:00Z"),
        ]
        for sk in U.LEGA_SPORT_KEY.values():
            self._scrivi(sk, self._snapshot(eventi))
        primo = U.scarica_lega_fixture(list(U.LEGA_SPORT_KEY.values())[0], self.dir)
        self.assertEqual(1, primo["n_eventi"], "solo l'evento futuro entra")
        self.assertEqual(["futuro"], [e["id"] for e in primo["eventi"]])
        self.assertEqual(1, primo["grezzo"]["eventi_iniziati_esclusi"])
        self.assertEqual(2, primo["grezzo"]["n_eventi"], "il grezzo conta la risposta")
        # secondo run: STESSO risultato, perche' l'istante e' lo snapshot e
        # non l'orologio reale (il dry-run non invecchia mai)
        secondo = U.scarica_lega_fixture(list(U.LEGA_SPORT_KEY.values())[0], self.dir)
        self.assertEqual(primo, secondo)

    def test_lista_grezza_non_vi_filtrata(self):
        """Il corpo grezzo salvato non ha istante: il filtro resta disattivato."""
        eventi = [
            _evento_anidato("passato", "Inter", "Roma", "2026-10-08T20:00:00Z"),
            _evento_anidato("futuro", "Milan", "Napoli", "2026-10-12T18:00:00Z"),
        ]
        for sk in U.LEGA_SPORT_KEY.values():
            self._scrivi(sk, eventi)
        blocco = U.scarica_lega_fixture(list(U.LEGA_SPORT_KEY.values())[0], self.dir)
        self.assertEqual(2, blocco["n_eventi"])
        self.assertIsNone(blocco["grezzo"].get("eventi_iniziati_esclusi"))


# ---------------------------------------------------------------------------
# Filtro dell'applicazione (funzione pura)
# ---------------------------------------------------------------------------
class TestRigheSoloPrePartita(unittest.TestCase):
    """Le due regole, isolate, con orologio congelato."""

    KICKOFF = _iso(OROLOGIO - timedelta(minutes=17))    # iniziato 17 minuti fa
    FUTURO = _iso(OROLOGIO + timedelta(minutes=10))     # a 10 minuti dal via
    PRIMA = _iso(OROLOGIO - timedelta(hours=1))         # file acquisito 1h fa

    def _riga(self, **extra):
        base = {"match_id": 1, "home": "Inter", "away": "Roma",
                "utcDate": self.FUTURO, "quote_live_istante": self.PRIMA}
        base.update(extra)
        return base

    def test_kickoff_futuro_e_ante_kickoff_e_usata(self):
        riga = self._riga(commence_time=self.FUTURO)
        tenute, scartate = R.righe_solo_pre_partita([riga], ora=_iso(OROLOGIO))
        self.assertEqual([riga], tenute)
        self.assertEqual(0, scartate)

    def test_regola_del_calcolo_kickoff_gia_passato(self):
        """Kickoff passato all'ora del calcolo (anche col file pre-match)."""
        riga = self._riga(commence_time=self.KICKOFF, utcDate=self.FUTURO)
        tenute, scartate = R.righe_solo_pre_partita([riga], ora=_iso(OROLOGIO))
        self.assertEqual([], tenute)
        self.assertEqual(1, scartate)

    def test_regola_dell_acquisizione_kickoff_non_precede_l_istante(self):
        """Istante delle quote DOPO il kickoff -> quota non pre-partita.

        Isolata dalla regola 2: l'ora del calcolo e' PRIMA del kickoff, resta
        solo il confronto kickoff <= istante delle quote.
        """
        riga = self._riga(commence_time=self.FUTURO,
                          quote_live_istante=_iso(OROLOGIO + timedelta(minutes=15)))
        tenute, scartate = R.righe_solo_pre_partita([riga], ora=_iso(OROLOGIO))
        self.assertEqual([], tenute)
        self.assertEqual(1, scartate)

    def test_calendario_stale_commence_passato_utcdate_futuro(self):
        """Il buco che ``righe_non_iniziate`` (solo utcDate) NON vede."""
        riga = self._riga(commence_time=self.KICKOFF, utcDate=self.FUTURO)
        tenute_ni, _ = R.righe_non_iniziate([riga], ora=_iso(OROLOGIO))
        self.assertEqual([riga], tenute_ni, "senza il filtro nuovo la riga passa")
        tenute, scartate = R.righe_solo_pre_partita(tenute_ni, ora=_iso(OROLOGIO))
        self.assertEqual([], tenute)
        self.assertEqual(1, scartate)

    def test_kickoff_mancante_o_illeggibile_resta(self):
        riga1 = self._riga(commence_time=None, utcDate="non-una-data")
        riga2 = self._riga()   # nessun campo kickoff
        tenute, scartate = R.righe_solo_pre_partita([riga1, riga2], ora=_iso(OROLOGIO))
        self.assertEqual([riga1, riga2], tenute)
        self.assertEqual(0, scartate)

    def test_preferisce_commence_time_a_utcdate(self):
        """E' il kickoff della FONTE a contare, non il calendario."""
        riga = self._riga(commence_time=self.KICKOFF,   # passato
                          utcDate="2027-01-01T18:00:00Z")  # calendario stale
        tenute, scartate = R.righe_solo_pre_partita([riga], ora=_iso(OROLOGIO))
        self.assertEqual([], tenute)
        self.assertEqual(1, scartate)


# ---------------------------------------------------------------------------
# Integrazione: calcola_righe_top_mix + sequenza del pulsante
# ---------------------------------------------------------------------------
class TestAlClickDelPulsante(unittest.TestCase):
    """La sequenza esatta del pulsante: non_iniziate -> solo_pre_partita."""

    STATS = {"Inter": {"att": 1.25, "def": 0.85}, "Roma": {"att": 1.05, "def": 0.95}}

    def _calcola(self, *, utc_date, commence, istante):
        payload = {"leghe": {"Serie A": {"eventi": [
            {"id": "ev1", "commence_time": commence,
             "home_team": "Inter", "away_team": "Roma",
             "libri": [{"key": "pinnacle", "title": "Pinnacle",
                        "h2h": {"home": 1.62, "draw": 4.1, "away": 6.0}}]}]}},
            "generato_il": istante}
        quote = mo.indice_partite(payload)
        quote["generato_il"] = istante
        match = {"id": 1, "matchday": 5, "utcDate": utc_date,
                 "homeTeam": {"shortName": "Inter"},
                 "awayTeam": {"shortName": "Roma"}}
        elo = lambda h, a, l, season=None: {"1": 0.58, "X": 0.24, "2": 0.18}  # noqa: E731
        with mock.patch.object(app, "predict_elo_probs", side_effect=elo), \
             mock.patch.object(app, "predict_elo_probs_legacy", side_effect=elo), \
             mock.patch.object(app, "_roster_stagione", return_value=None):
            return app.calcola_righe_top_mix("Serie A", [match],
                                             (self.STATS, 1.5, 1.2, {}), quote=quote)

    def _bottone(self, righe, ora=None):
        """La sequenza del pulsante su mercato + letture (in quell'ordine)."""
        ora = ora or _iso(OROLOGIO)
        top, _s1 = R.righe_non_iniziate(righe["mercato"], ora=ora)
        top, s2 = R.righe_solo_pre_partita(top, ora=ora)
        letture, _s3 = R.righe_non_iniziate(righe["letture"], ora=ora)
        letture, s4 = R.righe_solo_pre_partita(letture, ora=ora)
        return top, letture, s2, s4

    def test_iniziato_da_17_minuti_calendario_stale_nessuna_riga_ne_rinfresco(self):
        """Evento iniziato 17 minuti fa, utcDate ancora futuro: tutto escluso.

        La PRIMA registrazione non viene toccata (la riga non arriva neppure
        all'upsert), e l'ULTIMA della riga in attesa resta dov'e'.
        """
        righe = self._calcola(utc_date=_iso(OROLOGIO + timedelta(hours=2)),
                              commence=_iso(OROLOGIO - timedelta(minutes=17)),
                              istante=_iso(OROLOGIO - timedelta(hours=1)))
        self.assertEqual(1, len(righe["mercato"]), "la calcola produce la riga")
        self.assertEqual(1, len(righe["letture"]))
        top, letture, s2, s4 = self._bottone(righe)
        self.assertEqual([], top, "nessuna riga nuova nel Top Mix")
        self.assertEqual([], letture, "nessuna lettura per il rinfresco")
        self.assertEqual(1, s2)
        self.assertEqual(1, s4)
        # rinfresco con zero letture: la riga registrata resta INTATTA
        registrata = _riga_registrata_compatta()
        prima = json.dumps(registrata, sort_keys=True, default=str)
        aggiornate, azioni = R.aggiorna_righe_mercato_in_attesa(
            [registrata], letture, salvato_il="10/10/2026 12:00")
        self.assertEqual({"senza_lettura": 1}, azioni,
                         "riga registrata ma nessuna lettura ammessa: nessun aggiornamento")
        self.assertEqual(prima, json.dumps(aggiornate[0], sort_keys=True, default=str),
                         "ne' ultima ne' prima cambiano")

    def test_a_10_minuti_dal_via_entra_con_campo_kickoff(self):
        righe = self._calcola(utc_date=_iso(OROLOGIO + timedelta(minutes=10)),
                              commence=_iso(OROLOGIO + timedelta(minutes=10)),
                              istante=_iso(OROLOGIO - timedelta(hours=1)))
        top, letture, s2, s4 = self._bottone(righe)
        self.assertEqual(1, len(top))
        self.assertEqual(1, len(letture))
        self.assertEqual((0, 0), (s2, s4))
        # il metadata di kickoff C'E' su riga e lettura (costruito in calcola,
        # non dentro la funzione sotto impronta)
        self.assertEqual(_iso(OROLOGIO + timedelta(minutes=10)), top[0]["commence_time"])
        self.assertEqual(_iso(OROLOGIO + timedelta(minutes=10)),
                         letture[0]["commence_time"])
        self.assertEqual(_iso(OROLOGIO - timedelta(hours=1)),
                         top[0]["quote_live_istante"], "stesso istante del file")

    def test_rinfresco_regolare_preserva_la_prima_registrazione(self):
        """Quote pre-partita ammesse: l'ULTIMA si aggiorna, la PRIMA no."""
        lettura = {"match_id": 1, "home": "Inter", "away": "Roma",
                   "league": "Serie A",
                   "utcDate": _iso(OROLOGIO + timedelta(days=2)),
                   "commence_time": _iso(OROLOGIO + timedelta(days=2)),
                   "quote_live_istante": _iso(OROLOGIO - timedelta(hours=1)),
                   "per_esito": {"1": {"prob_sicuro": 52.0, "prob_mercato": 0.52,
                                       "quota_mercato": 1.92, "prob_modello": 58.0,
                                       "accordo_modello": True, "sotto_soglia_ora": True}}}
        tenute, scartate = R.righe_solo_pre_partita([lettura], ora=_iso(OROLOGIO))
        self.assertEqual([lettura], tenute)
        self.assertEqual(0, scartate)
        registrata = _riga_registrata_compatta()
        aggiornate, azioni = R.aggiorna_righe_mercato_in_attesa(
            [registrata], tenute, salvato_il="10/10/2026 12:00")
        self.assertEqual(1, azioni.get("aggiornata"), azioni)
        self.assertEqual(0.52, aggiornate[0][R.PROB_MERCATO_FIELD],
                         "l'ultima registrazione si aggiorna")
        self.assertEqual(0.58, aggiornate[0][R.PROB_MERCATO_PRIMA_FIELD],
                         "la PRIMA registrazione NON viene mai toccata")
        self.assertEqual(1.72, aggiornate[0][R.QUOTA_MERCATO_PRIMA_FIELD])

    def test_cablaggio_nel_sorgente_del_pulsante(self):
        """Il filtro e' dopo quelli esistenti, i quali restano IDENTICI."""
        src = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
        vecchio = "letture, _scartate_letture = righe_non_iniziate(letture)"
        self.assertIn(vecchio, src, "le righe di cablaggio esistenti non cambiano")
        self.assertIn("top_mercato, scartate_pre = righe_solo_pre_partita(top_mercato)", src)
        self.assertIn("letture, scartate_pre_letture = righe_solo_pre_partita(letture)", src)
        self.assertLess(src.index(vecchio),
                        src.index("top_mercato, scartate_pre = righe_solo_pre_partita"),
                        "prima i filtri gia' esistenti, poi quello pre-partita")
        # la funzione fingerprinted non tocca i campi: il metadata si aggiunge
        # in calcola_righe_top_mix (fuori dall'impronta)
        self.assertNotIn("commence_time", _corpo(app._riga_top_mix_mercato))


def _corpo(fn):
    """Sorgente di una funzione (test che il campo non e' dentro l'impronta)."""
    import inspect
    return inspect.getsource(fn)


def _riga_registrata_compatta():
    """Riga di mercato registrata, nella forma minima del rinfresco."""
    return {"match_id": 1, "home": "Inter", "away": "Roma",
            "campionato": "Serie A", "giornata": 5,
            "pronostico_sicuro": "Vittoria Inter - Top Mix",
            "mercato_standard": "1", "esito": "⏳", "origin": "top_mix",
            "selector_version": R.SELECTOR_VERSION_CURRENT,
            "model_variant": R.MODEL_VARIANT_CURRENT,
            "prob_sicuro": 58.0,
            R.PROB_MERCATO_FIELD: 0.58, R.QUOTA_MERCATO_FIELD: 1.72,
            R.PROB_MERCATO_PRIMA_FIELD: 0.58, R.QUOTA_MERCATO_PRIMA_FIELD: 1.72,
            R.PROB_MODELLO_FIELD: 53.0, R.ACCORDO_MODELLO_FIELD: True,
            R.QUOTE_LIVE_ISTANTE_FIELD: "2026-10-10T11:00:00Z",
            R.QUOTE_LIVE_ISTANTE_PRIMA_FIELD: "2026-10-10T11:00:00Z"}


if __name__ == "__main__":
    unittest.main()
