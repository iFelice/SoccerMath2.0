"""Esiti dei pronostici O/U: il grading delle voci SENZA giornata.

Problema (produzione, 16-18/10/2026): nessuna voce O/U del registro riceveva
mai un esito. ``entry_registro_totals`` salva ``giornata=None`` e, come
``match_id``, l'id dell'evento The Odds API (stringa esadecimale);
``_applica_esiti`` considerava solo le righe CON giornata e cercava il
risultato per ``match_id`` football-data: dieci voci restavano a ⏳ per sempre
(es. Frosinone-Sassuolo, finita 4-2).

Il ramo nuovo di ``_applica_esiti`` cerca la partita su football-data con
``GET /v4/competitions/{codice}/matches?dateFrom=…&dateTo=…&status=FINISHED``
nella finestra [giorno del kickoff, giorno dopo] e la abbina per coppia di nomi
canonici (``resolve_team_name``, ``mapped`` su entrambi) e stessa data:

* (a) le voci O/U dello snapshot del 16/10, costruite dal codice vero
  (``entry_registro_totals``), ricevono esito, risultato e ``fd_match_id``,
  con il ``match_id`` di sempre (chiave anti-doppioni) intatto;
* (b) una voce in stile PR #76 (origin ``top_mix``, ``giornata=None``) si
  giudica allo stesso modo;
* (c) partita non trovata o partita doppia: la voce resta ⏳ e il motivo finisce
  nel log (nessun abbinamento inventato);
* (d) su un registro misto, le righe 1X2 e quelle ombra trovate per giornata si
  graduano ESATTAMENTE come prima (nessuna chiamata per data sulle righe gia'
  trovate);
* (e) diagnosi del 25/10/2026: la ricerca per giornata con ``status=FINISHED``
  puo' restare indietro di ore rispetto a quella per data. Una riga del ramo
  per giornata assente nella risposta della giornata (o la cui chiamata per
  giornata non ha dato 200), solo se il suo calcio d'inizio e' passato da piu'
  di ``ORE_MINIME_CONTROLLO_RISULTATI`` ore (``righe_in_attesa_scadute``),
  viene cercata anche con ``_partite_finite`` sulla stessa cache
  ``("ou_giorno", comp, giorno)``, abbinata prima per id football-data (come
  numero) e poi per coppia di nomi canonici e stessa data, senza aggiungere
  campi nuovi e loggando ogni chiamata fallita e ogni riga scaduta non trovata;
  le righe non ancora scadute restano in attesa senza chiamate per data ne'
  righe nel log.

Nessuna rete e nessuna chiave: football-data e' simulato da un oggetto che
risponde alle GET di ``app.requests``. Nessuna attesa, nessun replay, nessuna
scrittura nel registro di produzione.
"""
from __future__ import annotations

import copy
import logging
import os
import sys
import unittest
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
if os.path.dirname(HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(HERE))

logging.getLogger("streamlit").setLevel(logging.ERROR)

import app  # noqa: E402
import prediction_registry as R  # noqa: E402
from audit.totals_snapshot_fixture import payload_snapshot  # noqa: E402

#: Orologio congelato prima di tutti i kickoff dello snapshot del 16/10.
ADESSO = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
CHIAVE = "chiave-di-prova"          # mai una chiave vera: nessuna rete
SHA = "sha-snapshot-16-10"
SALVATO_IL = "16/10/2026 15:17"


# --------------------------------------------------------------- football-data
class _Resp:
    """Risposta HTTP minimale (solo ``status_code`` e ``json``, come in produzione)."""

    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p


class Rete:
    """football-data simulato: risposte per (competizione, giornata) e per (competizione, finestra)."""

    def __init__(self, per_giornata=None, per_data=None, stato_giornata=None):
        self.per_giornata = per_giornata or {}
        self.per_data = per_data or {}
        self.stato_giornata = stato_giornata or {}
        self.chiamate = []

    def get(self, url, headers=None, params=None, timeout=None):
        params = dict(params or {})
        self.chiamate.append((url, params))
        competizione = url.rstrip("/").split("/")[-2]
        if "matchday" in params:
            chiave_g = (competizione, params["matchday"])
            stato = self.stato_giornata.get(chiave_g, 200)
            if stato != 200:
                return _Resp({"message": f"HTTP {stato}"}, status=stato)
            return _Resp({"matches": self.per_giornata.get(chiave_g, [])})
        if "dateFrom" in params:
            chiave = (competizione, params["dateFrom"], params["dateTo"])
            return _Resp({"matches": self.per_data.get(chiave, [])})
        return _Resp({}, status=404)          # nessun altro endpoint e' atteso


def _partita(mid, casa, trasferta, giorno, ora="18:45", gh=0, ga=0):
    """Una partita FINISHED come la restituisce football-data."""
    return {"id": mid, "status": "FINISHED", "utcDate": f"{giorno}T{ora}:00Z",
            "homeTeam": {"shortName": casa, "name": casa},
            "awayTeam": {"shortName": trasferta, "name": trasferta},
            "score": {"fullTime": {"home": gh, "away": ga}}}


# ------------------------------------------------------------------ fixtures
#: Soglia di ammissione O/U della FIXTURE (non del selettore: il modulo non si
#: tocca, si abbassa solo in questa costruzione). Serve a far nascere dagli
#: eventi reali dello snapshot del 16/10 le tre voci del test (a), Frosinone-
#: Sassuolo compreso (Over a 0,6688, un soffio sotto 0,67): le probabilita',
#: i nomi, le quote e i kickoff restano quelli dello snapshot.
SOGLIA_FIXTURE = 0.60


def righe_snapshot():
    """Le righe dello snapshot del 16/10 costruite dal codice vero (nessuna rete)."""
    import totals_mercato as T
    with mock.patch.object(T, "SOGLIA_OU", SOGLIA_FIXTURE):
        righe, _info = app.righe_pronostici_dalle_quote(payload_snapshot(), adesso=ADESSO)
    return righe


def voce_ou(righe, casa, trasferta):
    """La voce di registro che ``entry_registro_totals`` produce per quella partita.

    Nulla viene inventato: la riga e' quella dello snapshot (nomi, quote, fit,
    probabilita', kickoff) e il lato della scelta e' quello che il selettore
    le ha dato.
    """
    riga = copy.deepcopy(next(r for r in righe
                              if r["home"] == casa and r["away"] == trasferta))
    return app.entry_registro_totals(riga, SHA, SALVATO_IL)


def istantanea(voci):
    """(partita, match_id, esito, risultato_reale, fd_match_id) prima/dopo il grading."""
    return [{"partita": f'{v["home"]}-{v["away"]}', "match_id": v.get("match_id"),
             "esito": v.get("esito"), "risultato_reale": v.get("risultato_reale"),
             "fd_match_id": v.get(R.FD_MATCH_ID_FIELD)} for v in voci]


def stampa(titolo, prima, dopo):
    print(f"\n{titolo}")
    print(f'{"partita":32} {"esito prima":>12} {"esito dopo":>12} {"risultato":>10} {"fd_match_id":>12}')
    for p, d in zip(prima, dopo):
        print(f'{d["partita"][:32]:32} {str(p["esito"]):>12} {str(d["esito"]):>12} '
              f'{str(d["risultato_reale"]):>10} {str(d["fd_match_id"]):>12}')
    print(f"match_id invariati: {[p['match_id'] for p in prima] == [d['match_id'] for d in dopo]}")


# ------------------------------------------------- riferimento: com'era prima
def _applica_esiti_prima(preds, api_key, cache=None):
    """Il grading per giornata COM'ERA prima di questa modifica (copia di HEAD).

    Serve solo al test (d): stessa identica logica del ramo "loop per giornata"
    di ``_applica_esiti`` prima del ramo O/U, per confrontare riga per riga
    l'esito delle righe 1X2 e di quelle ombra.
    """
    if cache is None:
        cache = {}
    aggiornate = 0
    pending = [p for p in preds if p.get("esito") in [None, "⏳"]
               and p.get("campionato") is not None and p.get("giornata") is not None]
    if not pending:
        return 0, 0
    grouped = defaultdict(list)
    for p in pending:
        grouped[(p["campionato"], p["giornata"])].append(p)
    for (camp, giornata), camp_pending in grouped.items():
        comp = app.LEAGUE_CODE_MAP.get(camp)
        if not comp:
            continue
        chiave_cache = ("giornata", comp, giornata)
        if chiave_cache in cache:
            risultati_api = cache[chiave_cache]
        else:
            try:
                r = app.requests.get(
                    f"https://api.football-data.org/v4/competitions/{comp}/matches",
                    headers={"X-Auth-Token": api_key},
                    params={"matchday": giornata, "status": "FINISHED"},
                    timeout=15)
                if r.status_code != 200:
                    cache[chiave_cache] = None
                    continue
                risultati_api = {m["id"]: m for m in r.json().get("matches", [])}
                cache[chiave_cache] = risultati_api
            except Exception as e:
                logging.warning(f"Aggiornamento risultati {camp} giornata {giornata} fallito: {e}")
                cache[chiave_cache] = None
                continue
        if risultati_api is None:
            continue
        for p in camp_pending:
            m_id = p.get("match_id")
            if not m_id or m_id not in risultati_api:
                p["esito"] = "⏳"
                continue
            match = risultati_api[m_id]
            gh = match["score"]["fullTime"]["home"]
            ga = match["score"]["fullTime"]["away"]
            if gh is None:
                continue
            p["risultato_reale"] = f"{gh}-{ga}"
            p["esito"] = app.esito_mercato(p.get("mercato_standard", ""), gh, ga) or "⏳"
            aggiornate += 1
    return aggiornate, len(pending)


class RipristinaLogging:
    """Riabilita i log per la durata del test.

    Sei file di test dell'audit chiamano ``logging.disable(CRITICAL)`` a livello
    di modulo e non lo ripristinano: pytest importa tutti i file prima di
    eseguire qualunque test, quindi nella suite completa lo stato globale dei
    log dipende dall'ordine dei file. I WARNING qui sono parte del contratto in
    prova (una voce non abbinata DEVE essere loggata col suo motivo), quindi il
    setUp li riabilita e il tearDown rimette ESATTAMENTE lo stato trovato. E' la
    stessa guardia gia' usata in ``test_fallback_nomi.py``,
    ``test_quote_live.py`` e ``test_topmix_ombra_totali.py``.
    """

    def setUp(self):
        self._disable_precedente = logging.root.manager.disable
        logging.disable(logging.NOTSET)
        if hasattr(super(), "setUp"):
            super().setUp()

    def tearDown(self):
        logging.disable(self._disable_precedente)


class TestEsitiOU(RipristinaLogging, unittest.TestCase):
    """(a) voci O/U dallo snapshot, (b) voce in stile PR #76, (c) casi non abbinabili."""

    @classmethod
    def setUpClass(cls):
        cls.righe = righe_snapshot()

    def test_a_voci_ou_dallo_snapshot_del_16_10(self):
        """Frosinone-Sassuolo 4-2 -> Over ✅, un Over ❌ e un Under ✅."""
        voci = [voce_ou(self.righe, "Frosinone", "Sassuolo"),
                voce_ou(self.righe, "Bayern Munich", "RB Leipzig"),
                voce_ou(self.righe, "Getafe", "Rayo Vallecano")]
        self.assertEqual(["OVER_2.5", "OVER_2.5", "UNDER_2.5"],
                         [v["mercato_standard"] for v in voci])
        self.assertEqual([None, None, None], [v["giornata"] for v in voci])
        self.assertEqual("mercato_ou", voci[0]["origin"])
        prima = istantanea(voci)
        self.assertEqual(["⏳", "⏳", "⏳"], [p["esito"] for p in prima])
        self.assertEqual([None, None, None], [p["fd_match_id"] for p in prima])

        rete = Rete(per_data={
            ("SA", "2026-10-16", "2026-10-17"):
                [_partita(401, "Frosinone", "Sassuolo", "2026-10-16", "18:45", 4, 2)],
            ("BL1", "2026-10-17", "2026-10-18"):
                [_partita(402, "Bayern Munich", "RB Leipzig", "2026-10-17", "16:30", 0, 0)],
            ("PD", "2026-10-19", "2026-10-20"):
                [_partita(403, "Getafe", "Rayo Vallecano", "2026-10-19", "19:00", 1, 1)],
        })
        cache = {}
        with mock.patch.object(app.requests, "get", side_effect=rete.get):
            aggiornate, pending = app._applica_esiti(voci, CHIAVE, cache)
        self.assertEqual((3, 3), (aggiornate, pending))

        attesi = [("Frosinone-Sassuolo", "✅", "4-2", 401, "OVER_2.5"),
                  ("Bayern Munich-RB Leipzig", "❌", "0-0", 402, "OVER_2.5"),
                  ("Getafe-Rayo Vallecano", "✅", "1-1", 403, "UNDER_2.5")]
        for voce, (partita, esito, risultato, fid, mercato) in zip(voci, attesi):
            self.assertEqual(partita, f'{voce["home"]}-{voce["away"]}')
            self.assertEqual(esito, voce["esito"], partita)
            self.assertEqual(risultato, voce["risultato_reale"], partita)
            self.assertEqual(fid, voce[R.FD_MATCH_ID_FIELD], partita)
            self.assertEqual(mercato, voce["mercato_standard"], partita)
        dopo = istantanea(voci)
        # Il match_id NON cambia: e' la chiave anti-doppioni della riga.
        self.assertEqual([p["match_id"] for p in prima], [d["match_id"] for d in dopo])
        for p in prima:
            self.assertFalse(str(p["match_id"]).isdigit(), "il match_id e' quello The Odds API")
        # Una chiamata per (lega, giorno): tre giorni, tre leghe, tre GET.
        self.assertEqual(3, len(rete.chiamate))
        self.assertEqual([("dateFrom", "dateTo", "status")],
                         [tuple(sorted(c[1])) for c in rete.chiamate][:1])
        # Secondo giro con la stessa cache (Registro vivo + ombra): nessuna GET nuova.
        altre = [voce_ou(self.righe, "Frosinone", "Sassuolo"),
                 voce_ou(self.righe, "Bayern Munich", "RB Leipzig"),
                 voce_ou(self.righe, "Getafe", "Rayo Vallecano")]
        with mock.patch.object(app.requests, "get", side_effect=rete.get):
            app._applica_esiti(altre, CHIAVE, cache)
        self.assertEqual(3, len(rete.chiamate), "una sola chiamata per (lega, giorno)")
        stampa("(a) voci O/U dallo snapshot del 16/10", prima, dopo)

    def test_b_voce_in_stile_pr76_senza_giornata(self):
        """Origin ``top_mix`` e ``giornata=None``: stesso grading delle O/U."""
        riga = {"league": "Serie A", "giornata": None, "home": "Frosinone", "away": "Sassuolo",
                "match_id": "7d3160040958fe21778fd5ee485666c3",
                "utcDate": "2026-10-16T18:45:00Z",
                "market": "Over 2.5", "mercato_standard": "OVER_2.5", "esito": "Over 2.5",
                "prob": 0.6688, "prob_val": 66.88, "quota": 1.49,
                "fonte": "pinnacle", "n_libri": 1,
                "prob_modello": None, "prob_modello_val": None, "accordo": False,
                "quote_live_istante": "2026-10-16T13:17:55Z", "rank": 1}
        args, kwargs = app.argomenti_registro_top_mix_mercato(riga)
        voce = app.build_prediction_entry(*args, **kwargs, snapshot_sha=SHA, salvato_il=SALVATO_IL)
        self.assertIsNone(voce["giornata"])
        self.assertEqual(R.ORIGIN_TOP_MIX, voce["origin"])
        self.assertEqual("7d3160040958fe21778fd5ee485666c3", voce["match_id"])
        prima = istantanea([voce])

        rete = Rete(per_data={("SA", "2026-10-16", "2026-10-17"):
                              [_partita(401, "Frosinone", "Sassuolo", "2026-10-16", "18:45", 4, 2)]})
        with mock.patch.object(app.requests, "get", side_effect=rete.get):
            aggiornate, pending = app._applica_esiti([voce], CHIAVE, {})
        self.assertEqual((1, 1), (aggiornate, pending))
        self.assertEqual("✅", voce["esito"])
        self.assertEqual("4-2", voce["risultato_reale"])
        self.assertEqual(401, voce[R.FD_MATCH_ID_FIELD])
        self.assertEqual("7d3160040958fe21778fd5ee485666c3", voce["match_id"])
        self.assertIsNone(voce["giornata"])
        stampa("(b) voce in stile PR #76 (origin top_mix, giornata None)", prima, istantanea([voce]))

    def test_c_partita_non_trovata_e_partita_doppia(self):
        """Zero corrispondenze o piu' di una: la voce resta ⏳ e il motivo va nel log."""
        doppia = voce_ou(self.righe, "Frosinone", "Sassuolo")
        assente = voce_ou(self.righe, "Parma", "Torino")
        voci = [doppia, assente]
        prima = istantanea(voci)
        rete = Rete(per_data={
            # due partite con gli STESSI nomi nello stesso giorno: abbinamento ambiguo
            ("SA", "2026-10-16", "2026-10-17"):
                [_partita(401, "Frosinone", "Sassuolo", "2026-10-16", "18:45", 4, 2),
                 _partita(402, "Frosinone", "Sassuolo", "2026-10-16", "20:45", 0, 0)],
            # nella finestra del 19/10 c'e' un'altra partita, non Parma-Torino
            ("SA", "2026-10-19", "2026-10-20"):
                [_partita(403, "Monza", "Cagliari", "2026-10-19", "16:30", 1, 1)],
        })
        with self.assertLogs(level="WARNING") as log:
            with mock.patch.object(app.requests, "get", side_effect=rete.get):
                aggiornate, pending = app._applica_esiti(voci, CHIAVE, {})
        self.assertEqual((0, 2), (aggiornate, pending))
        for voce in voci:
            self.assertEqual("⏳", voce["esito"])
            self.assertIsNone(voce["risultato_reale"])
            self.assertNotIn(R.FD_MATCH_ID_FIELD, voce)
        testo = "\n".join(log.output)
        self.assertIn("2 partite corrispondenti", testo)
        self.assertIn("nessuna partita finita", testo)
        self.assertIn("Parma-Torino", testo)
        self.assertIn("Frosinone-Sassuolo", testo)
        stampa("(c) partita doppia e partita non trovata", prima, istantanea(voci))
        print("warning: " + " | ".join(riga.split("WARNING:")[-1].strip() for riga in log.output))

    def test_c2_riga_senza_kickoff_resta_in_attesa_con_un_motivo(self):
        """Senza kickoff non esiste la finestra di ricerca: ⏳ e warning, mai un esito."""
        voce = voce_ou(self.righe, "Frosinone", "Sassuolo")
        voce["kickoff_utc"] = ""
        rete = Rete(per_data={("SA", "2026-10-16", "2026-10-17"): [_partita(401, "Frosinone", "Sassuolo", "2026-10-16", "18:45", 4, 2)]})
        with self.assertLogs(level="WARNING") as log:
            with mock.patch.object(app.requests, "get", side_effect=rete.get):
                aggiornate, pending = app._applica_esiti([voce], CHIAVE, {})
        self.assertEqual((0, 1), (aggiornate, pending))
        self.assertEqual("⏳", voce["esito"])
        self.assertEqual([], rete.chiamate, "senza finestra non si chiama football-data")
        self.assertIn("senza estremi", "\n".join(log.output))


class TestInvarianti1X2eOmbra(RipristinaLogging, unittest.TestCase):
    """(d) su un registro misto, 1X2 e ombra trovate per giornata si graduano come prima."""

    @classmethod
    def setUpClass(cls):
        cls.righe = righe_snapshot()

    def _registro_misto(self):
        """Tre righe 1X2 visibili e due ombra: nessuna e' una voce O/U."""
        visibili = [
            app.build_prediction_entry(501, "Frosinone", "Sassuolo", "Serie A", 7,
                                       "16/10/2026 20:45", "Vittoria Casa - Top Mix", [],
                                       61.0, "", mercato_standard="1",
                                       origin=R.ORIGIN_TOP_MIX, rank=1,
                                       kickoff_utc="2026-10-16T18:45:00Z",
                                       snapshot_sha=SHA, salvato_il=SALVATO_IL),
            app.build_prediction_entry(502, "Bologna", "Inter Milan", "Serie A", 7,
                                       "17/10/2026 18:00", "Pareggio - Top Mix", [],
                                       33.0, "", mercato_standard="X",
                                       origin=R.ORIGIN_TOP_MIX, rank=2,
                                       kickoff_utc="2026-10-17T16:00:00Z",
                                       snapshot_sha=SHA, salvato_il=SALVATO_IL),
            # partita non (ancora) nei risultati: resta in attesa
            app.build_prediction_entry(599, "Juventus", "Lazio", "Serie A", 7,
                                       "18/10/2026 20:45", "Vittoria Casa - Top Mix", [],
                                       58.0, "", mercato_standard="1",
                                       origin=R.ORIGIN_TOP_MIX, rank=3,
                                       kickoff_utc="2026-10-18T18:45:00Z",
                                       snapshot_sha=SHA, salvato_il=SALVATO_IL),
        ]
        ombra = [app.build_ombra_entry(
            {"league": "Serie A", "giornata": 7, "home": casa, "away": trasferta,
             "match_id": mid, "utcDate": utc, "market": mercato, "mercato_standard": codice,
             "confidence": 0.66, "poisson": 0.66, "ammessa": True,
             "vincente_globale": True, "famiglia": famiglia, "dati_mancanti": False},
            snapshot_sha=SHA, salvato_il=SALVATO_IL)
            for (mid, casa, trasferta, utc, mercato, codice, famiglia) in (
                (503, "Frosinone", "Sassuolo", "2026-10-16T18:45:00Z",
                 "Over 2.5", "OVER_2.5", R.OMBRA_FAMIGLIA_OU25),
                (504, "Bologna", "Inter Milan", "2026-10-17T16:00:00Z",
                 "GG", "GG", R.OMBRA_FAMIGLIA_GGNG))]
        return visibili + ombra

    def test_d_1x2_e_ombra_come_prima(self):
        registro = self._registro_misto()
        self.assertEqual(5, len(registro))
        self.assertTrue(all(r["giornata"] == 7 for r in registro))
        self.assertTrue(all(str(r["match_id"]).isdigit() for r in registro))
        per_giornata = {("SA", 7): [
            _partita(501, "Frosinone", "Sassuolo", "2026-10-16", "18:45", 2, 0),
            _partita(502, "Bologna", "Inter Milan", "2026-10-17", "16:00", 1, 1),
            _partita(503, "Frosinone", "Sassuolo", "2026-10-16", "18:45", 4, 2),
            _partita(504, "Bologna", "Inter Milan", "2026-10-17", "16:00", 2, 0),
        ]}
        rete_oggi, rete_prima = Rete(per_giornata=per_giornata), Rete(per_giornata=per_giornata)
        riferimento = copy.deepcopy(registro)
        prima = istantanea(registro)
        with self.assertLogs(level="WARNING") as log:
            with mock.patch.object(app.requests, "get", side_effect=rete_oggi.get):
                agg_oggi, pend_oggi = app._applica_esiti(registro, CHIAVE, {})
        with mock.patch.object(app.requests, "get", side_effect=rete_prima.get):
            agg_prima, pend_prima = _applica_esiti_prima(riferimento, CHIAVE, {})
        self.assertEqual((agg_prima, pend_prima), (agg_oggi, pend_oggi))
        self.assertEqual((4, 5), (agg_oggi, pend_oggi))
        for dopo, prima_riga in zip(registro, riferimento):
            self.assertEqual(prima_riga["esito"], dopo["esito"], dopo["home"])
            self.assertEqual(prima_riga["risultato_reale"], dopo["risultato_reale"], dopo["home"])
            self.assertEqual(prima_riga["match_id"], dopo["match_id"])
        # Le 4 righe trovate per giornata (16/10 e 17/10) non generano nessuna GET per data;
        # solo la riga 599 (18/10), assente per giornata, viene cercata anche per data e loggata.
        self.assertEqual(rete_prima.chiamate, rete_oggi.chiamate[:1])
        self.assertEqual(2, len(rete_oggi.chiamate))
        self.assertNotIn("dateFrom", rete_oggi.chiamate[0][1])
        self.assertEqual({"dateFrom": "2026-10-18", "dateTo": "2026-10-19", "status": "FINISHED"},
                         rete_oggi.chiamate[1][1])
        self.assertIn("Juventus-Lazio", "\n".join(log.output))
        # Il campo nuovo NON compare sulle righe del ramo per giornata.
        for riga in registro:
            self.assertNotIn(R.FD_MATCH_ID_FIELD, riga)
        attesi = ["✅", "✅", "⏳", "✅", "❌"]     # 1 (2-0), X (1-1), assente, Over 4-2, GG 2-0
        self.assertEqual(attesi, [r["esito"] for r in registro])
        stampa("(d) registro misto: 1X2 e ombra", prima, istantanea(registro))

    def test_d2_le_ou_non_cambiano_il_grading_per_giornata(self):
        """Nello stesso giro: O/U per (lega, giorno) e 1X2 per giornata, senza interferenze."""
        ou = voce_ou(self.righe, "Frosinone", "Sassuolo")
        visibile = app.build_prediction_entry(501, "Frosinone", "Sassuolo", "Serie A", 7,
                                              "16/10/2026 20:45", "Vittoria Casa - Top Mix", [],
                                              61.0, "", mercato_standard="1",
                                              origin=R.ORIGIN_TOP_MIX, rank=1,
                                              kickoff_utc="2026-10-16T18:45:00Z",
                                              snapshot_sha=SHA, salvato_il=SALVATO_IL)
        registro = [visibile, ou]
        rete = Rete(per_giornata={("SA", 7): [_partita(501, "Frosinone", "Sassuolo", "2026-10-16", "18:45", 2, 0)]},
                    per_data={("SA", "2026-10-16", "2026-10-17"):
                              [_partita(501, "Frosinone", "Sassuolo", "2026-10-16", "18:45", 2, 0)]})
        prima = istantanea(registro)
        with mock.patch.object(app.requests, "get", side_effect=rete.get):
            aggiornate, pending = app._applica_esiti(registro, CHIAVE, {})
        self.assertEqual((2, 2), (aggiornate, pending))
        self.assertEqual("✅", visibile["esito"])       # 1 con 2-0
        self.assertEqual("❌", ou["esito"])             # Over 2.5 con 2 gol
        self.assertEqual("2-0", ou["risultato_reale"])
        self.assertEqual(501, ou[R.FD_MATCH_ID_FIELD])
        self.assertNotIn(R.FD_MATCH_ID_FIELD, visibile)
        self.assertEqual(2, len(rete.chiamate))
        stampa("(d) stesso giro: 1X2 per giornata + O/U per data", prima, istantanea(registro))


def _voce_1x2(mid, casa, trasferta, lega, giornata, giorno, ora="15:00", mercato="1"):
    """Voce 1X2 del Registro costruita dal codice vero (con giornata e match_id numerico)."""
    return app.build_prediction_entry(
        mid, casa, trasferta, lega, giornata,
        f"{giorno[8:10]}/{giorno[5:7]}/{giorno[:4]} {ora}",
        "Scelta 1X2 - Top Mix", [], 61.0, "",
        mercato_standard=mercato, origin=R.ORIGIN_TOP_MIX, rank=1,
        kickoff_utc=f"{giorno}T{ora}:00Z",
        snapshot_sha=SHA, salvato_il=SALVATO_IL,
    )


def _voce_ombra(mid, casa, trasferta, lega, giornata, giorno, ora="15:00",
                mercato="Over 2.5", codice="OVER_2.5", famiglia=R.OMBRA_FAMIGLIA_OU25):
    """Voce ombra costruita dal codice vero (con giornata e match_id numerico)."""
    return app.build_ombra_entry(
        {"league": lega, "giornata": giornata, "home": casa, "away": trasferta,
         "match_id": mid, "utcDate": f"{giorno}T{ora}:00Z",
         "market": mercato, "mercato_standard": codice,
         "confidence": 0.66, "poisson": 0.66, "ammessa": True,
         "vincente_globale": True, "famiglia": famiglia, "dati_mancanti": False},
        snapshot_sha=SHA, salvato_il=SALVATO_IL,
    )


class TestFallbackGiornataPerData(RipristinaLogging, unittest.TestCase):
    """Fallback per data sulle righe con giornata quando football-data per giornata resta indietro."""

    def test_1_assente_per_giornata_ma_presente_per_data_graduata(self):
        """Riga scaduta assente nella risposta della giornata ma finita per data: graduata senza campi nuovi."""
        # SA giornata 8 restituisce 1 sola partita finita (600), mentre Como e
        # Lazio (gia' giocate oltre 3 ore fa) sono FINISHED nella ricerca per data.
        como = _voce_1x2(601, "Como", "Parma", "Serie A", 8, "2026-10-24", "15:00", "1")
        # 602 con id diverso nella risposta per data: verifica anche il secondo passo (nomi canonici + data)
        lazio = _voce_1x2(602, "Lazio", "Genoa", "Serie A", 8, "2026-10-24", "18:00", "1")
        voci = [como, lazio]
        chiavi_prima = [set(v.keys()) for v in voci]
        prima = istantanea(voci)

        rete = Rete(
            per_giornata={("SA", 8): [_partita(600, "Inter Milan", "Torino", "2026-10-24", "12:30", 2, 0)]},
            per_data={("SA", "2026-10-24", "2026-10-25"): [
                _partita(600, "Inter Milan", "Torino", "2026-10-24", "12:30", 2, 0),
                _partita(601, "Como 1907", "Parma", "2026-10-24", "15:00", 2, 1),
                _partita(9602, "SS Lazio", "Genoa CFC", "2026-10-24", "18:00", 0, 1),
            ]},
        )
        with mock.patch.object(app.requests, "get", side_effect=rete.get):
            aggiornate, pending = app._applica_esiti(voci, CHIAVE, {})

        self.assertEqual((2, 2), (aggiornate, pending))
        self.assertEqual(("✅", "2-1", 601), (como["esito"], como["risultato_reale"], como["match_id"]))
        self.assertEqual(("❌", "0-1", 602), (lazio["esito"], lazio["risultato_reale"], lazio["match_id"]))
        # Nessun campo nuovo aggiunto alle righe 1X2 (niente fd_match_id).
        for voce, k_prima in zip(voci, chiavi_prima):
            self.assertEqual(k_prima, set(voce.keys()))
            self.assertNotIn(R.FD_MATCH_ID_FIELD, voce)
        self.assertEqual(2, len(rete.chiamate))     # 1 per giornata + 1 per (SA, 2026-10-24)
        stampa("(1) assente per giornata ma presente per data", prima, istantanea(voci))

    def test_2_abbinamento_per_id_prima_dei_nomi(self):
        """Prima id football-data (confrontato come numero), poi coppia di nomi canonici e stessa data."""
        # match_id come stringa di cifre ("701") confrontato con id intero 701:
        # nella risposta per data 701 ha nomi diversi (2-0 -> ✅), mentre 799 ha
        # gli stessi nomi della riga (0-3 -> ❌). Deve vincere 701 per id.
        per_id = _voce_1x2("701", "RB Leipzig", "Freiburg", "Bundesliga", 7, "2026-10-24", "14:30", "1")
        # 888 non compare per id: cade sul secondo passo (nomi canonici + stessa data -> 799, 0-3 -> ❌).
        per_nomi = _voce_1x2(888, "RB Leipzig", "Freiburg", "Bundesliga", 7, "2026-10-24", "14:30", "1")
        voci = [per_id, per_nomi]
        chiavi_prima = [set(v.keys()) for v in voci]

        rete = Rete(
            per_giornata={("BL1", 7): []},
            per_data={("BL1", "2026-10-24", "2026-10-25"): [
                _partita(701, "Borussia Dortmund", "Augsburg", "2026-10-24", "14:30", 2, 0),
                _partita(799, "RB Leipzig", "SC Freiburg", "2026-10-24", "14:30", 0, 3),
            ]},
        )
        with mock.patch.object(app.requests, "get", side_effect=rete.get):
            aggiornate, pending = app._applica_esiti(voci, CHIAVE, {})

        self.assertEqual((2, 2), (aggiornate, pending))
        self.assertEqual(("✅", "2-0", "701"), (per_id["esito"], per_id["risultato_reale"], per_id["match_id"]))
        self.assertEqual(("❌", "0-3", 888), (per_nomi["esito"], per_nomi["risultato_reale"], per_nomi["match_id"]))
        for voce, k_prima in zip(voci, chiavi_prima):
            self.assertEqual(k_prima, set(voce.keys()))
            self.assertNotIn(R.FD_MATCH_ID_FIELD, voce)

    def test_3_due_partite_corrispondenti_resta_in_attesa_con_riga_nel_log(self):
        """Con due partite corrispondenti (o zero) la riga resta ⏳ e il motivo finisce nel log."""
        doppia = _voce_1x2(901, "Como", "Parma", "Serie A", 8, "2026-10-24", "15:00", "1")
        assente = _voce_1x2(902, "Lazio", "Genoa", "Serie A", 8, "2026-10-24", "18:00", "1")
        voci = [doppia, assente]
        chiavi_prima = [set(v.keys()) for v in voci]

        rete = Rete(
            per_giornata={("SA", 8): []},
            per_data={("SA", "2026-10-24", "2026-10-25"): [
                _partita(401, "Como", "Parma", "2026-10-24", "15:00", 2, 0),
                _partita(402, "Como 1907", "Parma", "2026-10-24", "20:45", 0, 1),
            ]},
        )
        with self.assertLogs(level="WARNING") as log:
            with mock.patch.object(app.requests, "get", side_effect=rete.get):
                aggiornate, pending = app._applica_esiti(voci, CHIAVE, {})

        self.assertEqual((0, 2), (aggiornate, pending))
        for voce, k_prima in zip(voci, chiavi_prima):
            self.assertEqual("⏳", voce["esito"])
            self.assertIsNone(voce["risultato_reale"])
            self.assertEqual(k_prima, set(voce.keys()))
            self.assertNotIn(R.FD_MATCH_ID_FIELD, voce)
        testo = "\n".join(log.output)
        self.assertIn("2 partite corrispondenti", testo)
        self.assertIn("Como-Parma", testo)
        self.assertIn("nessuna partita finita", testo)
        self.assertIn("Lazio-Genoa", testo)

    def test_4_chiamata_per_giornata_con_429_riga_cercata_per_data(self):
        """Se la GET per giornata risponde 429, scrive nel log il motivo e cerca comunque per data."""
        dortmund = _voce_1x2(710, "Borussia Dortmund", "Augsburg", "Bundesliga", 7, "2026-10-24", "14:30", "1")
        chiavi_prima = set(dortmund.keys())

        rete = Rete(
            stato_giornata={("BL1", 7): 429},
            per_data={("BL1", "2026-10-24", "2026-10-25"): [
                _partita(710, "Borussia Dortmund", "Augsburg", "2026-10-24", "14:30", 3, 1),
            ]},
        )
        with self.assertLogs(level="WARNING") as log:
            with mock.patch.object(app.requests, "get", side_effect=rete.get):
                aggiornate, pending = app._applica_esiti([dortmund], CHIAVE, {})

        self.assertEqual((1, 1), (aggiornate, pending))
        self.assertEqual(("✅", "3-1", 710),
                         (dortmund["esito"], dortmund["risultato_reale"], dortmund["match_id"]))
        self.assertEqual(chiavi_prima, set(dortmund.keys()))
        self.assertNotIn(R.FD_MATCH_ID_FIELD, dortmund)
        self.assertEqual(2, len(rete.chiamate))
        self.assertEqual({"matchday": 7, "status": "FINISHED"}, rete.chiamate[0][1])
        self.assertEqual({"dateFrom": "2026-10-24", "dateTo": "2026-10-25", "status": "FINISHED"},
                         rete.chiamate[1][1])
        self.assertIn("429", "\n".join(log.output))

    def test_5_riga_trovata_per_giornata_nessuna_chiamata_in_piu(self):
        """Riga gia' presente nella risposta per giornata: gestita come oggi, zero chiamate per data."""
        lipsia = _voce_1x2(720, "RB Leipzig", "Freiburg", "Bundesliga", 7, "2026-10-24", "14:30", "1")
        dortmund = _voce_1x2(721, "Borussia Dortmund", "Augsburg", "Bundesliga", 7, "2026-10-24", "16:30", "2")
        voci = [lipsia, dortmund]
        chiavi_prima = [set(v.keys()) for v in voci]

        rete = Rete(per_giornata={("BL1", 7): [
            _partita(720, "RB Leipzig", "Freiburg", "2026-10-24", "14:30", 3, 1),
            _partita(721, "Borussia Dortmund", "Augsburg", "2026-10-24", "16:30", 2, 0),
        ]})
        with mock.patch.object(app.requests, "get", side_effect=rete.get):
            aggiornate, pending = app._applica_esiti(voci, CHIAVE, {})

        self.assertEqual((2, 2), (aggiornate, pending))
        self.assertEqual(("✅", "3-1"), (lipsia["esito"], lipsia["risultato_reale"]))
        self.assertEqual(("❌", "2-0"), (dortmund["esito"], dortmund["risultato_reale"]))
        self.assertEqual(1, len(rete.chiamate))
        self.assertNotIn("dateFrom", rete.chiamate[0][1])
        for voce, k_prima in zip(voci, chiavi_prima):
            self.assertEqual(k_prima, set(voce.keys()))
            self.assertNotIn(R.FD_MATCH_ID_FIELD, voce)

    def test_6_stessa_cache_fra_registro_vivo_e_ombra_conta_le_chiamate(self):
        """Stessa cache fra gol, 1X2 vivo e ombra; le righe future non aggiungono chiamate."""
        import registry_store as rs
        adesso = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        fut_vivo = adesso + timedelta(days=2)
        fut_ombra = adesso + timedelta(days=3)
        # Nel Registro vivo:
        # - una voce O/U su (SA, 2026-10-24) -> popola ('ou_giorno', 'SA', '2026-10-24');
        # - una 1X2 trovata per giornata (600, SA giornata 8);
        # - una 1X2 assente per giornata (601, SA giornata 8, stesso giorno 2026-10-24) -> riusa la cache O/U;
        # - una 1X2 con giornata 429 (710, BL1 giornata 7, 2026-10-24) -> chiama ('ou_giorno', 'BL1', '2026-10-24');
        # - una 1X2 futura (699, SA giornata 8, tra 2 giorni) -> resta in attesa senza chiamate per data.
        ou_sa = {"match_id": "ead11223344556677889900aabbccdde", "home": "Como", "away": "Parma",
                 "campionato": "Serie A", "giornata": None, "mercato_standard": "OVER_2.5",
                 "esito": "⏳", "risultato_reale": None, "origin": R.ORIGIN_MERCATO_OU,
                 R.KICKOFF_UTC_FIELD: "2026-10-24T15:00:00Z"}
        vivo_trovata = _voce_1x2(600, "Inter Milan", "Torino", "Serie A", 8, "2026-10-24", "12:30", "1")
        vivo_assente = _voce_1x2(601, "Como", "Parma", "Serie A", 8, "2026-10-24", "15:00", "1")
        vivo_429 = _voce_1x2(710, "Borussia Dortmund", "Augsburg", "Bundesliga", 7, "2026-10-24", "14:30", "1")
        vivo_futura = _voce_1x2(699, "Juventus", "Lazio", "Serie A", 8,
                                fut_vivo.strftime("%Y-%m-%d"), fut_vivo.strftime("%H:%M"), "1")
        vivo = [ou_sa, vivo_trovata, vivo_assente, vivo_429, vivo_futura]

        # Nel Registro ombra: stesse due giornate e stesso giorno + una riga futura (tra 3 giorni) -> zero GET aggiuntive.
        omb_trovata = _voce_ombra(600, "Inter Milan", "Torino", "Serie A", 8, "2026-10-24", "12:30",
                                  mercato="Over 2.5", codice="OVER_2.5", famiglia=R.OMBRA_FAMIGLIA_OU25)
        omb_assente = _voce_ombra(601, "Como", "Parma", "Serie A", 8, "2026-10-24", "15:00",
                                  mercato="GG", codice="GG", famiglia=R.OMBRA_FAMIGLIA_GGNG)
        omb_429 = _voce_ombra(710, "Borussia Dortmund", "Augsburg", "Bundesliga", 7, "2026-10-24", "14:30",
                              mercato="Under 2.5", codice="UNDER_2.5", famiglia=R.OMBRA_FAMIGLIA_OU25)
        omb_futura = _voce_ombra(799, "RB Leipzig", "Freiburg", "Bundesliga", 7,
                                 fut_ombra.strftime("%Y-%m-%d"), fut_ombra.strftime("%H:%M"),
                                 mercato="Over 2.5", codice="OVER_2.5", famiglia=R.OMBRA_FAMIGLIA_OU25)
        ombra = [omb_trovata, omb_assente, omb_429, omb_futura]

        rete = Rete(
            per_giornata={("SA", 8): [_partita(600, "Inter Milan", "Torino", "2026-10-24", "12:30", 2, 0)]},
            stato_giornata={("BL1", 7): 429},
            per_data={
                ("SA", "2026-10-24", "2026-10-25"): [
                    _partita(600, "Inter Milan", "Torino", "2026-10-24", "12:30", 2, 0),
                    _partita(601, "Como", "Parma", "2026-10-24", "15:00", 2, 1),
                ],
                ("BL1", "2026-10-24", "2026-10-25"): [
                    _partita(710, "Borussia Dortmund", "Augsburg", "2026-10-24", "14:30", 3, 1),
                ],
            },
        )
        salvate_vivo, salvate_ombra = [], []
        with mock.patch.object(app, "load_predictions", return_value=vivo), \
             mock.patch.object(app, "save_predictions", side_effect=lambda p: salvate_vivo.append(p)), \
             mock.patch.object(rs, "load_ombra_rows", return_value=(ombra, "upstash")), \
             mock.patch.object(rs, "save_ombra_rows",
                               side_effect=lambda r, post=None: salvate_ombra.append(r) or {"remoto": "ok"}), \
             mock.patch.object(app.requests, "get", side_effect=rete.get):
            agg, pend = app.aggiorna_risultati_reali(CHIAVE)

        self.assertEqual((4, 5), (agg, pend))
        self.assertEqual(["✅", "✅", "✅", "✅", "⏳"], [r["esito"] for r in vivo])
        self.assertEqual(["❌", "✅", "❌", "⏳"], [r["esito"] for r in ombra])   # Over 2-0, GG 2-1, Under 3-1, futura ⏳
        self.assertIsNone(vivo_futura["risultato_reale"])
        self.assertIsNone(omb_futura["risultato_reale"])
        self.assertEqual(601, ou_sa[R.FD_MATCH_ID_FIELD])
        for riga in [vivo_trovata, vivo_assente, vivo_429, vivo_futura] + ombra:
            self.assertNotIn(R.FD_MATCH_ID_FIELD, riga)
        # Esattamente 4 GET in tutto (vivo + ombra insieme, comprese le 2 righe future):
        # 1) SA per data (O/U, riusata da vivo_assente e da omb_assente)
        # 2) SA giornata 8 (riusata da omb_trovata; vivo_futura non genera chiamate per data)
        # 3) BL1 giornata 7 -> 429 (in cache come None, non ripetuta nell'ombra; omb_futura non genera chiamate per data)
        # 4) BL1 per data (vivo_429, riusata da omb_429)
        self.assertEqual(4, len(rete.chiamate), rete.chiamate)
        self.assertEqual(1, sum(1 for u, p in rete.chiamate if "/SA/" in u and "dateFrom" in p))
        self.assertEqual(1, sum(1 for u, p in rete.chiamate if "/SA/" in u and "matchday" in p))
        self.assertEqual(1, sum(1 for u, p in rete.chiamate if "/BL1/" in u and "matchday" in p))
        self.assertEqual(1, sum(1 for u, p in rete.chiamate if "/BL1/" in u and "dateFrom" in p))

    def test_7_partita_futura_assente_per_giornata_zero_chiamate_per_data_e_niente_nel_log(self):
        """Riga di partita futura assente nella risposta per giornata: ⏳, zero GET per data e niente nel log."""
        futuro = (datetime.now(timezone.utc) + timedelta(days=2)).replace(second=0, microsecond=0)
        voce_futura = _voce_1x2(
            801, "Juventus", "Lazio", "Serie A", 8,
            futuro.strftime("%Y-%m-%d"), futuro.strftime("%H:%M"), "1",
        )
        chiavi_prima = set(voce_futura.keys())

        rete = Rete(per_giornata={("SA", 8): [
            _partita(600, "Inter Milan", "Torino", "2026-10-24", "12:30", 2, 0),
        ]})
        with self.assertNoLogs(level="DEBUG"):
            with mock.patch.object(app.requests, "get", side_effect=rete.get):
                aggiornate, pending = app._applica_esiti([voce_futura], CHIAVE, {})

        self.assertEqual((0, 1), (aggiornate, pending))
        self.assertEqual("⏳", voce_futura["esito"])
        self.assertIsNone(voce_futura["risultato_reale"])
        self.assertEqual(chiavi_prima, set(voce_futura.keys()))
        self.assertNotIn(R.FD_MATCH_ID_FIELD, voce_futura)
        self.assertEqual(1, len(rete.chiamate), rete.chiamate)
        self.assertEqual({"matchday": 8, "status": "FINISHED"}, rete.chiamate[0][1])
        self.assertEqual(0, sum(1 for _, p in rete.chiamate if "dateFrom" in p))

    def test_8_riga_iniziata_da_4_ore_assente_per_giornata_cercata_per_data(self):
        """Riga iniziata da 4 ore (> ORE_MINIME_CONTROLLO_RISULTATI) assente per giornata: cercata per data."""
        inizio_4h = (datetime.now(timezone.utc) - timedelta(hours=4)).replace(second=0, microsecond=0)
        giorno_4h = inizio_4h.strftime("%Y-%m-%d")
        giorno_4h_dopo = (inizio_4h + timedelta(days=1)).strftime("%Y-%m-%d")
        ora_4h = inizio_4h.strftime("%H:%M")

        voce_4h = _voce_1x2(802, "Como", "Parma", "Serie A", 8, giorno_4h, ora_4h, "1")
        chiavi_prima = set(voce_4h.keys())

        rete = Rete(
            per_giornata={("SA", 8): []},
            per_data={("SA", giorno_4h, giorno_4h_dopo): [
                _partita(802, "Como 1907", "Parma", giorno_4h, ora_4h, 2, 1),
            ]},
        )
        with mock.patch.object(app.requests, "get", side_effect=rete.get):
            aggiornate, pending = app._applica_esiti([voce_4h], CHIAVE, {})

        self.assertEqual((1, 1), (aggiornate, pending))
        self.assertEqual(("✅", "2-1", 802),
                         (voce_4h["esito"], voce_4h["risultato_reale"], voce_4h["match_id"]))
        self.assertEqual(chiavi_prima, set(voce_4h.keys()))
        self.assertNotIn(R.FD_MATCH_ID_FIELD, voce_4h)
        self.assertEqual(2, len(rete.chiamate), rete.chiamate)
        self.assertEqual({"matchday": 8, "status": "FINISHED"}, rete.chiamate[0][1])
        self.assertEqual({"dateFrom": giorno_4h, "dateTo": giorno_4h_dopo, "status": "FINISHED"},
                         rete.chiamate[1][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
