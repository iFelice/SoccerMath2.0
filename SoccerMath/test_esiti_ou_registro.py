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
* (d) su un registro misto, le righe 1X2 e quelle ombra si graduano ESATTAMENTE
  come prima della modifica (confronto riga per riga con il ramo per giornata
  com'era, e nessuna chiamata per data).

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
from datetime import datetime, timezone
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

    def __init__(self, per_giornata=None, per_data=None):
        self.per_giornata = per_giornata or {}
        self.per_data = per_data or {}
        self.chiamate = []

    def get(self, url, headers=None, params=None, timeout=None):
        params = dict(params or {})
        self.chiamate.append((url, params))
        competizione = url.rstrip("/").split("/")[-2]
        if "matchday" in params:
            return _Resp({"matches": self.per_giornata.get((competizione, params["matchday"]), [])})
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


class TestInvarianti1X2eOmbra(unittest.TestCase):
    """(d) su un registro misto, 1X2 e ombra si graduano come prima."""

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
        # Stesse GET, stesso ordine: nessuna chiamata per (lega, giorno) in piu'.
        self.assertEqual(rete_prima.chiamate, rete_oggi.chiamate)
        self.assertEqual(1, len(rete_oggi.chiamate))
        self.assertNotIn("dateFrom", rete_oggi.chiamate[0][1])
        # Il campo nuovo NON compare sulle righe graduate per giornata.
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
