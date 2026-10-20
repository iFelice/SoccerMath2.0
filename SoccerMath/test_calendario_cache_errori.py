"""test_calendario_cache_errori.py — la cache del calendario tiene SOLO le risposte riuscite.

Commessa (schedula «🏟️ Partite»): ``calendario_campionato`` ha
``@st.cache_data(ttl=900)`` e prima il ttl valeva ANCHE per gli errori: la
funzione restituiva ``([], "🟠 Errore 429...")`` e Streamlit memorizzava pure
questo esito, quindi un 429 o un timeout restavano scritti in scheda per 15
minuti anche se la fonte tornava viva dopo un minuto.

Adesso il download sta in ``_scarica_calendario_campionato`` (senza cache) e la
funzione in cache, ``_calendario_in_cache``, restituisce le partite SOLO se il
download riesce: se fallisce solleva ``_ErroreCalendario`` e Streamlit non
mette in cache le eccezioni. Il rerun successivo riparte dalla rete.

COSA VERIFICA (``calendario_campionato`` chiamata a mano, rete finta):

* (a) prima chiamata con 429 simulato: nessuna partita e messaggio con «429»;
* (b) seconda chiamata, STESSA lega e STESSA cache (non si svuota niente in
  mezzo): la fonte risponde 200 e la funzione restituisce le partite, con
  errore vuoto;
* (c) la seconda chiamata ha davvero rifatto la richiesta (2 GET, non 1): e'
  la prova che l'errore NON era rimasto in cache;
* (d) la risposta RIUSCITA resta in cache: una terza chiamata non aggiunge GET;
* (e) lo stesso percorso con un timeout simulato al posto del 429 (la commessa
  cita 429 e timeout).

Nessuna rete: ``requests.get`` e' finto e ``st.cache_data`` viene svuotato
prima e dopo, cosi' il test non lascia niente agli altri file di test che
girano nello stesso processo. Nessun file del repository viene toccato.

Esecuzione:
    python -m pytest SoccerMath/test_calendario_cache_errori.py -v
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.dirname(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import requests  # noqa: E402
import streamlit as st  # noqa: E402

import app as prod_app  # noqa: E402

LEGA = "Serie A"
#: Il calendario finto della risposta riuscita: due partite, come football-data.
PARTITE = [
    {"id": 4101, "matchday": 7, "utcDate": "2026-10-24T18:45:00Z",
     "status": "TIMED", "homeTeam": {"name": "Genoa", "shortName": "Genoa"},
     "awayTeam": {"name": "Fiorentina", "shortName": "Fiorentina"},
     "score": {"fullTime": {"home": None, "away": None}}},
    {"id": 4102, "matchday": 7, "utcDate": "2026-10-25T20:45:00Z",
     "status": "TIMED", "homeTeam": {"name": "Atalanta", "shortName": "Atalanta"},
     "awayTeam": {"name": "Lazio", "shortName": "Lazio"},
     "score": {"fullTime": {"home": None, "away": None}}},
]


class _Risposta:
    """Una risposta di ``requests``: solo quello che legge l'app.

    ``json()`` solleva ``ValueError`` (come ``requests``) se il corpo non e'
    JSON: il test della risposta non valida passa di qui.
    """

    def __init__(self, payload, code=200, testo=None):
        self.status_code = code
        self._payload = payload
        self.text = testo if testo is not None else repr(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("corpo non JSON")
        return self._payload


class TestCalendarioErroriNonInCache(unittest.TestCase):
    """(a)(b)(c)(d)(e): un errore non resta in cache, un successo si'."""

    def setUp(self):
        # La cache di ``@st.cache_data`` e' di PROCESSO: si parte vuoti e si
        # lascia vuota, o il calendario finto di questo test finirebbe in un
        # altro file di test (e viceversa).
        st.cache_data.clear()
        self.chiamate: list[str] = []
        self.risposte: list[_Risposta | Exception] = []
        self._patch = [
            mock.patch.object(prod_app, "API_KEY_DATA", "chiave-finta-fixture"),
            mock.patch.object(prod_app.requests, "get", self._get_finto),
        ]
        for p in self._patch:
            p.start()

    def tearDown(self):
        for p in reversed(self._patch):
            p.stop()
        st.cache_data.clear()

    # ------------------------------------------------------------------ aiuti
    def _get_finto(self, url, **kw):
        """La rete finta: una risposta (o un'eccezione) per chiamata, in ordine."""
        self.chiamate.append(str(url))
        if not self.risposte:
            raise AssertionError(f"chiamata di rete non attesa dal test: {url}")
        prossima = self.risposte.pop(0)
        if isinstance(prossima, Exception):
            raise prossima
        return prossima

    def _errore_429(self):
        return _Risposta({"message": "API rate limit exceeded"}, code=429,
                         testo='{"message":"API rate limit exceeded"}')

    def _ok(self):
        return _Risposta({"matches": [dict(m) for m in PARTITE]})

    # ------------------------------------------------------------------ test
    def test_01_dopo_il_429_la_seconda_chiamata_rende_le_partite(self):
        """(a)(b)(c)(d) 429, poi 200: la seconda chiamata torna con le partite."""
        self.risposte = [self._errore_429(), self._ok()]

        # (a) la prima chiamata vede il 429: nessuna partita, messaggio leggibile.
        partite, errore = prod_app.calendario_campionato(LEGA)
        self.assertEqual([], partite, "con il 429 nessuna partita")
        self.assertIn("429", errore, f"il messaggio dice l'errore: {errore!r}")
        self.assertEqual(1, len(self.chiamate), "una sola richiesta per la prima chiamata")

        # (b) la seconda chiamata: la fonte e' tornata viva, le partite arrivano.
        #     Nessuno svuota la cache in mezzo: e' esattamente il «rerun
        #     successivo» della commessa.
        partite, errore = prod_app.calendario_campionato(LEGA)
        self.assertEqual("", errore, f"senza errori l'errore e' vuoto: {errore!r}")
        self.assertEqual([m["id"] for m in PARTITE], [m["id"] for m in partite],
                         "la seconda chiamata restituisce le partite della fonte")

        # (c) la seconda chiamata ha rifatto la richiesta: l'errore NON era in
        #     cache (con il vecchio comportamento le GET sarebbero 1).
        self.assertEqual(2, len(self.chiamate),
                         "l'errore non va in cache: la seconda chiamata ritenta")

        # (d) la risposta RIUSCITA resta in cache: la terza chiamata non aggiunge
        #     richieste (non si martella la fonte a ogni rerun).
        partite, errore = prod_app.calendario_campionato(LEGA)
        self.assertEqual("", errore)
        self.assertEqual([m["id"] for m in PARTITE], [m["id"] for m in partite])
        self.assertEqual(2, len(self.chiamate),
                         "un calendario riuscito resta in cache (ttl 15 minuti)")

    def test_02_dopo_il_timeout_la_seconda_chiamata_rende_le_partite(self):
        """(e) timeout, poi 200: la seconda chiamata torna con le partite."""
        self.risposte = [requests.exceptions.Timeout("timeout simulato"),
                         self._ok()]

        partite, errore = prod_app.calendario_campionato(LEGA)
        self.assertEqual([], partite, "con il timeout nessuna partita")
        self.assertIn("Timeout", errore, f"il messaggio dice l'errore: {errore!r}")

        partite, errore = prod_app.calendario_campionato(LEGA)
        self.assertEqual("", errore, f"senza errori l'errore e' vuoto: {errore!r}")
        self.assertEqual([m["id"] for m in PARTITE], [m["id"] for m in partite],
                         "dopo il timeout la seconda chiamata restituisce le partite")
        self.assertEqual(2, len(self.chiamate),
                         "anche il timeout non va in cache: si ritenta")

    def test_03_senza_chiave_nessuna_chiamata_e_nessuna_cache(self):
        """Senza chiave non parte nessuna richiesta: il messaggio non e' un dato."""
        with mock.patch.object(prod_app, "API_KEY_DATA", ""):
            partite, errore = prod_app.calendario_campionato(LEGA)
        self.assertEqual([], partite)
        self.assertIn("Chiave", errore, f"il messaggio dice perche': {errore!r}")
        self.assertEqual([], self.chiamate, "senza chiave non si chiama la fonte")

    def test_04_chiave_sbagliata_non_avvelena_le_lega_buone(self):
        """Un errore su una lega non blocca le altre: la cache e' per lega."""
        self.risposte = [self._errore_429(), self._ok()]
        partite_ko, errore_ko = prod_app.calendario_campionato(LEGA)
        self.assertIn("429", errore_ko)
        self.assertEqual([], partite_ko)
        partite_ok, errore_ok = prod_app.calendario_campionato("Bundesliga")
        self.assertEqual("", errore_ok)
        self.assertEqual([m["id"] for m in PARTITE], [m["id"] for m in partite_ok])


if __name__ == "__main__":
    unittest.main(verbosity=2)
