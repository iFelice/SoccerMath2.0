"""Valutazione delle multiple del registro ombra (famiglia multipla_proposta_v1).

Diagnosi 30/10, secondo passo: le righe multipla_proposta_v1 non venivano mai
valutate. Ogni gamba finiva nel ramo senza giornata di ``_applica_esiti`` e
produceva solo un "Grading O/U senza estremi" nel log, senza esito e senza
risultato. Da qui:

* ``valuta_riga_multipla`` (funzione pura): la multipla e' ✅ solo se TUTTE le
  gambe sono ✅, e' ❌ appena UNA gamba e' ❌, resta ⏳ finche' anche una sola
  gamba manca. Su ogni gamba ``esito_gamba`` e ``risultato_gamba`` (cosi' si
  vede quale gamba l'ha fatta cadere); sulla riga ``esito`` e
  ``risultato_reale`` vuoto: una multipla non ha un punteggio suo.
* Fonte del risultato di ogni gamba, in ordine:
  1. la stessa partita gia' graduata (registro ombra o Registro vivo), per
     ``match_id`` se la gamba lo ha, altrimenti per coppia di nomi canonici e
     stessa lega con calcio d'inizio entro 14 giorni da ``salvato_il`` della
     multipla, solo se l'abbinamento e' unico; l'esito della gamba si calcola
     con ``esito_mercato`` dalla ``giocata`` e dal ``risultato_reale``;
  2. solo se la gamba ha ``kickoff_utc`` passato da piu' di
     ``ORE_MINIME_CONTROLLO_RISULTATI`` ore e la fonte 1 non trova niente, le
     partite finite per (lega, giorno) con la stessa cache e la stessa chiave
     ``("ou_giorno", comp, giorno)`` del ramo senza giornata.
* ``aggiorna_esiti_ombra`` valuta le multiple DOPO che le altre righe ombra
  sono state graduate nello stesso giro e scrive con la stessa
  ``save_ombra_rows``: niente piu' "Grading O/U senza estremi" per le multiple.

Nessuna rete e nessuna chiave: football-data e' simulato da un oggetto che
risponde alle GET di ``app.requests``. Nessuna scrittura nel registro di
produzione: lo storage ombra e' finto, in memoria.
"""
from __future__ import annotations

import logging
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
if os.path.dirname(HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(HERE))

logging.getLogger("streamlit").setLevel(logging.ERROR)

import app  # noqa: E402
import lista_giocate as lg  # noqa: E402
import prediction_registry as R  # noqa: E402

CHIAVE = "chiave-di-prova"          # mai una chiave vera: nessuna rete
SHA = "sha-di-prova"
SALVATO_IL = "11/10/2026 15:00"

#: Multipla salvata l'11/10 (caso Alavés-Málaga, giocata il 23/10: 12 giorni).
SALVATO_MULTIPLA = datetime(2026, 10, 11, 16, 0, tzinfo=timezone.utc)
#: Orologio congelato dopo le partite del 24-25/10.
ADESSO = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------- football-data
class _Resp:
    """Risposta HTTP minimale (solo ``status_code`` e ``json``, come in produzione)."""

    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p


class Rete:
    """football-data simulato: risponde alle ricerche per data (le multiple non usano la giornata)."""

    def __init__(self, per_data=None):
        self.per_data = per_data or {}
        self.chiamate = []

    def get(self, url, headers=None, params=None, timeout=None):
        params = dict(params or {})
        self.chiamate.append((url, params))
        competizione = url.rstrip("/").split("/")[-2]
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


class RipristinaLogging:
    """Riabilita i log per la durata del test (stessa guardia di test_esiti_ou_registro)."""

    def setUp(self):
        self._disable_precedente = logging.root.manager.disable
        logging.disable(logging.NOTSET)
        if hasattr(super(), "setUp"):
            super().setUp()

    def tearDown(self):
        logging.disable(self._disable_precedente)


# ------------------------------------------------------------------ fixtures
def _gamba(mid, casa, trasferta, lega, giocata, commence=None, prob=0.55, quota=1.90):
    """Una gamba come quella che ``calcola_lista_giocate`` mette nella proposta.

    ``mid``/``commence`` a ``None`` riproducono una gamba VECCHIA (senza
    match_id e senza kickoff), come le righe salvate prima del primo passo.
    """
    g = {"partita": f"{casa} vs {trasferta}", "lega": lega, "giocata": giocata,
         "probabilita": prob, "quota_b365_stimata": quota}
    if mid is not None:
        g["match_id"] = mid
    if commence is not None:
        g["commence_time"] = commence
    return g


def _riga_multipla(gambe, istante=SALVATO_MULTIPLA, k=None):
    """Riga multipla_proposta_v1 costruita dal codice vero (build_ombra_multipla_entry)."""
    proposta = {"probabilita": 0.40, "quota_totale": 2.15, "ev": -0.14, "giocate": gambe}
    return lg.build_ombra_multipla_entry(proposta, istante_utc=istante, k=k or len(gambe))


def _riga_graduata(mid, casa, trasferta, lega, kickoff, risultato, giornata=7):
    """Una riga gia' graduata del registro (vivo o ombra): costruita dal codice vero."""
    riga = app.build_prediction_entry(
        mid, casa, trasferta, lega, giornata,
        f"{kickoff[8:10]}/{kickoff[5:7]}/{kickoff[:4]} {kickoff[11:16]}",
        "Scelta 1X2 - Top Mix", [], 61.0, "",
        mercato_standard="1", origin=R.ORIGIN_TOP_MIX, rank=1,
        kickoff_utc=kickoff, snapshot_sha=SHA, salvato_il=SALVATO_IL)
    riga["risultato_reale"] = risultato
    riga["esito"] = "✅"
    return riga


class Fonte2Spy:
    """Cercatore di partite finite che registra le chiamate (mai una rete vera)."""

    def __init__(self, partite=None):
        self.partite = partite or []
        self.chiamate = []

    def __call__(self, comp, giorno):
        self.chiamate.append((comp, giorno))
        return self.partite


# ------------------------------------------------- la funzione pura: la regola
class TestValutaRigaMultipla(RipristinaLogging, unittest.TestCase):
    """La regola della multipla e le due fonti del risultato di ogni gamba."""

    def test_tutte_le_gambe_riuscite(self):
        """Due gambe ✅ per match_id: multipla ✅, zero chiamate alla fonte 2."""
        gambe = [_gamba("aaa1", "Roma", "Lazio", "Serie A", "1", "2026-10-24T18:00:00Z"),
                 _gamba("bbb2", "Como", "Parma", "Serie A", "12", "2026-10-24T15:00:00Z")]
        riga = _riga_multipla(gambe)
        graduate = [_riga_graduata("aaa1", "Roma", "Lazio", "Serie A",
                                   "2026-10-24T18:00:00Z", "2-0"),
                    _riga_graduata("bbb2", "Como", "Parma", "Serie A",
                                   "2026-10-24T15:00:00Z", "2-1")]
        spy = Fonte2Spy()
        info = app.valuta_riga_multipla(riga, graduate, partite_finite=spy, adesso=ADESSO)
        self.assertEqual({"gambe_valutate": 2, "motivi": []}, info)
        self.assertEqual("✅", riga["esito"])
        self.assertEqual("", riga["risultato_reale"])
        self.assertEqual([("✅", "2-0"), ("✅", "2-1")],
                         [(g["esito_gamba"], g["risultato_gamba"]) for g in riga["giocate"]])
        self.assertEqual([], spy.chiamate, "la fonte 1 basta: nessuna chiamata")

        # Secondo giro sugli stessi dati: niente da fare, nessuna gamba da scrivere.
        info2 = app.valuta_riga_multipla(riga, graduate, partite_finite=spy, adesso=ADESSO)
        self.assertEqual({"gambe_valutate": 0, "motivi": []}, info2)
        self.assertEqual([], spy.chiamate)

    def test_una_gamba_persa_con_le_altre_in_attesa(self):
        """Appena una gamba e' ❌ la multipla e' ❌, anche se le altre mancano ancora."""
        gambe = [_gamba("aaa1", "Roma", "Lazio", "Serie A", "1", "2026-10-24T18:00:00Z"),
                 _gamba("bbb2", "Como", "Parma", "Serie A", "12", "2026-10-26T20:00:00Z")]
        riga = _riga_multipla(gambe)
        graduate = [_riga_graduata("aaa1", "Roma", "Lazio", "Serie A",
                                   "2026-10-24T18:00:00Z", "0-1")]
        spy = Fonte2Spy()
        info = app.valuta_riga_multipla(riga, graduate, partite_finite=spy, adesso=ADESSO)
        self.assertEqual(1, info["gambe_valutate"])
        self.assertEqual([], info["motivi"], "la gamba futura resta in attesa in silenzio")
        self.assertEqual("❌", riga["esito"])
        self.assertEqual("", riga["risultato_reale"])
        self.assertEqual(("❌", "0-1"),
                         (riga["giocate"][0]["esito_gamba"], riga["giocate"][0]["risultato_gamba"]))
        self.assertNotIn("esito_gamba", riga["giocate"][1])
        self.assertEqual([], spy.chiamate, "la partita futura non si cerca")

    def test_una_gamba_in_attesa_con_le_altre_riuscite_resta_in_attesa(self):
        """Con una gamba ancora senza risultato la multipla resta ⏳."""
        gambe = [_gamba("aaa1", "Roma", "Lazio", "Serie A", "1", "2026-10-24T18:00:00Z"),
                 _gamba("bbb2", "Como", "Parma", "Serie A", "12", "2026-10-26T20:00:00Z")]
        riga = _riga_multipla(gambe)
        graduate = [_riga_graduata("aaa1", "Roma", "Lazio", "Serie A",
                                   "2026-10-24T18:00:00Z", "2-0")]
        spy = Fonte2Spy()
        info = app.valuta_riga_multipla(riga, graduate, partite_finite=spy, adesso=ADESSO)
        self.assertEqual(1, info["gambe_valutate"])
        self.assertEqual([], info["motivi"])
        self.assertEqual("⏳", riga["esito"])
        self.assertEqual(("✅", "2-0"),
                         (riga["giocate"][0]["esito_gamba"], riga["giocate"][0]["risultato_gamba"]))
        self.assertNotIn("esito_gamba", riga["giocate"][1])

    def test_abbinamento_per_nomi_entro_14_giorni(self):
        """Alavés-Málaga giocata il 23/10 per una multipla salvata l'11/10 (gamba senza match_id).

        La riga graduata porta i nomi della fonte ("Deportivo Alavés",
        "Málaga CF"): l'abbinamento e' per nomi canonici e stessa lega, entro 14
        giorni da salvato_il. Un'altra Alavés-Málaga fuori finestra (il
        26/09, prima del salvataggio) NON deve confondere l'abbinamento.
        """
        gambe = [_gamba(None, "Alavés", "Málaga", "La Liga", "1")]
        riga = _riga_multipla(gambe)
        graduate = [_riga_graduata(901, "Deportivo Alavés", "Málaga CF", "La Liga",
                                   "2026-10-23T18:30:00Z", "1-0", giornata=10),
                    _riga_graduata(902, "Deportivo Alavés", "Málaga CF", "La Liga",
                                   "2026-09-26T18:30:00Z", "0-2", giornata=8)]
        spy = Fonte2Spy()
        info = app.valuta_riga_multipla(riga, graduate, partite_finite=spy,
                                        adesso=datetime(2026, 10, 23, 22, 0, tzinfo=timezone.utc))
        self.assertEqual({"gambe_valutate": 1, "motivi": []}, info)
        self.assertEqual("✅", riga["esito"])
        gamba = riga["giocate"][0]
        self.assertEqual(("✅", "1-0"), (gamba["esito_gamba"], gamba["risultato_gamba"]))
        self.assertEqual([], spy.chiamate, "la fonte 1 basta: nessuna chiamata")

    def test_due_partite_con_gli_stessi_nomi_nella_finestra_restano_in_attesa(self):
        """Due partite graduate con gli stessi nomi entro 14 giorni: abbinamento non unico."""
        gambe = [_gamba(None, "Alavés", "Málaga", "La Liga", "1")]
        riga = _riga_multipla(gambe)
        graduate = [_riga_graduata(901, "Deportivo Alavés", "Málaga CF", "La Liga",
                                   "2026-10-17T18:30:00Z", "1-0", giornata=9),
                    _riga_graduata(902, "Alavés", "Málaga", "La Liga",
                                   "2026-10-23T18:30:00Z", "2-2", giornata=10)]
        spy = Fonte2Spy()
        info = app.valuta_riga_multipla(riga, graduate, partite_finite=spy,
                                        adesso=datetime(2026, 10, 23, 22, 0, tzinfo=timezone.utc))
        self.assertEqual(0, info["gambe_valutate"], "nessuna gamba si puo' valutare")
        self.assertEqual(1, len(info["motivi"]))
        motivo = info["motivi"][0]
        self.assertIn("2 partite graduate con gli stessi nomi", motivo)
        self.assertIn("14 giorni", motivo)
        self.assertIn("Alavés vs Málaga", motivo)
        self.assertEqual("⏳", riga["esito"])
        self.assertNotIn("esito_gamba", riga["giocate"][0])
        self.assertEqual([], spy.chiamate,
                         "abbinamento non unico: la fonte 2 non si cerca, la gamba resta in attesa")

    def test_partita_futura_senza_nessuna_chiamata(self):
        """Gamba con kickoff nel futuro: nessuna chiamata, nessun motivo nel log."""
        futuro = ADESSO + timedelta(days=2)
        gambe = [_gamba("zzz9", "Juventus", "Lazio", "Serie A", "1",
                        futuro.strftime("%Y-%m-%dT%H:%M:%SZ"))]
        riga = _riga_multipla(gambe)
        spy = Fonte2Spy()
        info = app.valuta_riga_multipla(riga, [], partite_finite=spy, adesso=ADESSO)
        self.assertEqual({"gambe_valutate": 0, "motivi": []}, info)
        self.assertEqual("⏳", riga["esito"])
        self.assertEqual("", riga["risultato_reale"])
        self.assertNotIn("esito_gamba", riga["giocate"][0])
        self.assertEqual([], spy.chiamate, "partita futura: nessuna chiamata")

    def test_multipla_gia_decisa_non_si_sovrascrive(self):
        """Una multipla gia' decisa (✅/❌) non si ricalcola: le gambe in attesa
        si riempiono, ma l'esito della riga resta quello di sempre."""
        # Gia' PERSA: una gamba decisa e una in attesa che ora si risolve.
        gambe = [_gamba("aaa1", "Roma", "Lazio", "Serie A", "1", "2026-10-24T18:00:00Z"),
                 _gamba("bbb2", "Como", "Parma", "Serie A", "12", "2026-10-24T15:00:00Z")]
        riga = _riga_multipla(gambe)
        riga["esito"] = "❌"
        riga["giocate"][0]["esito_gamba"] = "❌"
        riga["giocate"][0]["risultato_gamba"] = "0-1"
        graduate = [_riga_graduata("bbb2", "Como", "Parma", "Serie A",
                                   "2026-10-24T15:00:00Z", "2-1")]
        info = app.valuta_riga_multipla(riga, graduate, partite_finite=Fonte2Spy(), adesso=ADESSO)
        self.assertEqual({"gambe_valutate": 1, "motivi": []}, info)
        self.assertEqual("❌", riga["esito"], "una multipla persa resta persa")
        self.assertEqual(("✅", "2-1"),
                         (riga["giocate"][1]["esito_gamba"], riga["giocate"][1]["risultato_gamba"]))
        # Gia' VINTA, senza gambe (riga sintetica come i fixture di navigazione):
        # l'esito non si ricalcola verso il basso e non c'e' niente da scrivere.
        gia_vinta = {"match_id": "multipla_2026-10-12_k2", "esito": "✅", "k": 2,
                     R.OMBRA_FAMIGLIA_FIELD: lg.FAMIGLIA_OMBRA_MULTIPLA_PROPOSTA}
        info2 = app.valuta_riga_multipla(gia_vinta, [], partite_finite=Fonte2Spy(), adesso=ADESSO)
        self.assertEqual({"gambe_valutate": 0, "motivi": []}, info2)
        self.assertEqual("✅", gia_vinta["esito"])

    def test_fonte_2_partite_finite_per_lega_e_giorno(self):
        """Kickoff passato da piu' di ORE_MINIME_CONTROLLO_RISULTATI e fonte 1 vuota:
        la gamba si cerca fra le partite finite per (lega, giorno), per nomi e data."""
        kickoff = ADESSO - timedelta(hours=5)
        gambe = [_gamba("zzz9", "Inter Milan", "Torino", "Serie A", "12",
                        kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"))]
        riga = _riga_multipla(gambe)
        giorno = kickoff.strftime("%Y-%m-%d")
        spy = Fonte2Spy(partite=[_partita(602, "Inter Milan", "Torino", giorno,
                                          kickoff.strftime("%H:%M"), 3, 0)])
        info = app.valuta_riga_multipla(riga, [], partite_finite=spy, adesso=ADESSO)
        self.assertEqual({"gambe_valutate": 1, "motivi": []}, info)
        self.assertEqual([("SA", giorno)], spy.chiamate)
        self.assertEqual("✅", riga["esito"])
        self.assertEqual(("✅", "3-0"),
                         (riga["giocate"][0]["esito_gamba"], riga["giocate"][0]["risultato_gamba"]))

    def test_doppie_chance_valutate_dal_risultato(self):
        """1X, X2 e 12 si laureano con esito_mercato sul risultato della partita."""
        gambe = [_gamba("d1", "Roma", "Lazio", "Serie A", "1X", "2026-10-24T18:00:00Z"),
                 _gamba("d2", "Como", "Parma", "Serie A", "X2", "2026-10-24T15:00:00Z"),
                 _gamba("d3", "Cagliari", "Genoa", "Serie A", "12", "2026-10-24T20:00:00Z")]
        riga = _riga_multipla(gambe)
        graduate = [_riga_graduata("d1", "Roma", "Lazio", "Serie A",
                                   "2026-10-24T18:00:00Z", "1-1"),
                    _riga_graduata("d2", "Como", "Parma", "Serie A",
                                   "2026-10-24T15:00:00Z", "0-3"),
                    _riga_graduata("d3", "Cagliari", "Genoa", "Serie A",
                                   "2026-10-24T20:00:00Z", "2-2")]
        spy = Fonte2Spy()
        info = app.valuta_riga_multipla(riga, graduate, partite_finite=spy, adesso=ADESSO)
        self.assertEqual({"gambe_valutate": 3, "motivi": []}, info)
        # 1X con 1-1 -> ✅; X2 con 0-3 -> ✅; 12 con 2-2 (pareggio) -> ❌.
        self.assertEqual([("✅", "1-1"), ("✅", "0-3"), ("❌", "2-2")],
                         [(g["esito_gamba"], g["risultato_gamba"]) for g in riga["giocate"]])
        self.assertEqual("❌", riga["esito"])
        self.assertEqual("", riga["risultato_reale"])
        self.assertEqual([], spy.chiamate)


# ------------------------------- il giro completo: aggiorna_esiti_ombra
class TestAggiornaEsitiOmbraMultipla(RipristinaLogging, unittest.TestCase):
    """Le multiple non passano piu' da _applica_esiti e si valutano nello stesso giro."""

    def test_nessun_grading_ou_senza_estremi_per_le_multiple(self):
        """La multipla non finisce nel ramo O/U: niente "senza estremi" per lei."""
        import registry_store as rs
        kickoff = (datetime.now(timezone.utc) - timedelta(hours=5)).replace(
            second=0, microsecond=0)
        giorno = kickoff.strftime("%Y-%m-%d")
        multipla = _riga_multipla(
            [_gamba("zzz9", "Juventus", "Lazio", "Serie A", "1",
                    kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"))])
        # Una vera voce O/U senza kickoff: quella SI' logga "senza estremi".
        ou_senza_kickoff = {"match_id": "ead11223344556677889900aabbccdde",
                            "home": "Como", "away": "Parma", "campionato": "Serie A",
                            "giornata": None, "mercato_standard": "OVER_2.5",
                            "esito": "⏳", "risultato_reale": None,
                            "origin": R.ORIGIN_MERCATO_OU, R.KICKOFF_UTC_FIELD: ""}
        ombra = [multipla, ou_senza_kickoff]
        salvate = []
        rete = Rete()      # nessuna partita finita da nessuna parte
        with self.assertLogs(level="WARNING") as log:
            with mock.patch.object(rs, "load_ombra_rows", return_value=(ombra, "upstash")), \
                 mock.patch.object(rs, "save_ombra_rows",
                                   side_effect=lambda r, post=None: salvate.append(r)
                                   or {"remoto": "ok"}), \
                 mock.patch.object(app.requests, "get", side_effect=rete.get):
                aggiornate, pending = app.aggiorna_esiti_ombra(CHIAVE, righe_vive=[])
        testo = "\n".join(log.output)
        # La voce O/U senza kickoff logga "senza estremi" come sempre...
        self.assertIn("senza estremi", testo)
        # ...ma NESSUNA riga "senza estremi" riguarda la multipla.
        for riga_log in log.output:
            if "senza estremi" in riga_log:
                self.assertNotIn(multipla["match_id"], riga_log)
                self.assertNotIn("Multipla", riga_log)
        # La multipla ha il SUO motivo, da valutazione delle multiple.
        self.assertIn("Grading multipla", testo)
        self.assertIn(multipla["match_id"], testo)
        self.assertIn("nessuna partita finita", testo)
        # La multipla resta in attesa, senza punteggio e senza esito di gamba.
        self.assertEqual("⏳", multipla["esito"])
        self.assertEqual("", multipla["risultato_reale"])
        self.assertNotIn("esito_gamba", multipla["giocate"][0])
        self.assertEqual("⏳", ou_senza_kickoff["esito"])
        # Una sola GET: la fonte 2 della gamba (la O/U senza kickoff non chiama),
        # sulla finestra [giorno del kickoff, giorno dopo].
        self.assertEqual(1, len(rete.chiamate), rete.chiamate)
        self.assertEqual({"dateFrom": giorno,
                          "dateTo": (kickoff + timedelta(days=1)).strftime("%Y-%m-%d"),
                          "status": "FINISHED"}, rete.chiamate[0][1])
        # La multipla resta in attesa: niente da scrivere, NESSUNA save (lettura).
        self.assertEqual(0, aggiornate)
        self.assertEqual(2, pending)
        self.assertEqual([], salvate)

    def test_multipla_valutata_dopo_le_altre_righe_ombra_stessa_cache(self):
        """La gamba si abbinata alla riga O/U ombra graduata NELLO STESSO giro.

        La seconda gamba usa la fonte 2 sullo stesso (lega, giorno) della riga
        O/U: la risposta e' gia' in cache ("ou_giorno"), quindi nessuna GET in
        piu'. Il tutto si scrive con la stessa save_ombra_rows.
        """
        import registry_store as rs
        kickoff = (datetime.now(timezone.utc) - timedelta(hours=5)).replace(
            second=0, microsecond=0)
        giorno = kickoff.strftime("%Y-%m-%d")
        ora = kickoff.strftime("%H:%M")
        # Voce O/U ombra sullo stesso giorno della seconda gamba: si graduera'
        # nel ramo senza giornata di QUESTO giro, prima delle multiple.
        ou = {"match_id": "ead11223344556677889900aabbccdde", "home": "Como",
              "away": "Parma", "campionato": "Serie A", "giornata": None,
              "mercato_standard": "OVER_2.5", "esito": "⏳", "risultato_reale": None,
              "origin": R.ORIGIN_MERCATO_OU,
              R.KICKOFF_UTC_FIELD: kickoff.strftime("%Y-%m-%dT%H:%M:%SZ")}
        gambe = [_gamba("ead11223344556677889900aabbccdde", "Como", "Parma",
                        "Serie A", "1", kickoff.strftime("%Y-%m-%dT%H:%M:%SZ")),
                 _gamba("zzz9", "Inter Milan", "Torino", "Serie A", "12",
                        kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"))]
        multipla = _riga_multipla(gambe)
        ombra = [ou, multipla]
        salvate = []
        rete = Rete(per_data={
            ("SA", giorno, (kickoff + timedelta(days=1)).strftime("%Y-%m-%d")): [
                _partita(601, "Como 1907", "Parma", giorno, "15:00", 2, 1),
                _partita(602, "Inter Milan", "Torino", giorno, ora, 3, 0),
            ]})
        with mock.patch.object(rs, "load_ombra_rows", return_value=(ombra, "upstash")), \
             mock.patch.object(rs, "save_ombra_rows",
                               side_effect=lambda r, post=None: salvate.append(r)
                               or {"remoto": "ok"}), \
             mock.patch.object(app.requests, "get", side_effect=rete.get):
            aggiornate, pending = app.aggiorna_esiti_ombra(CHIAVE, righe_vive=[])
        # La voce O/U e' stata graduata nel giro (2-1 -> OVER_2.5 ✅)...
        self.assertEqual(("✅", "2-1", 601),
                         (ou["esito"], ou["risultato_reale"], ou[R.FD_MATCH_ID_FIELD]))
        # ...e la multipla si e' valutata DOPO, sulle righe appena graduate:
        # la prima gamba si abbinata per match_id alla voce O/U stessa.
        self.assertEqual("✅", multipla["esito"])
        self.assertEqual("", multipla["risultato_reale"])
        self.assertEqual([("✅", "2-1"), ("✅", "3-0")],
                         [(g["esito_gamba"], g["risultato_gamba"]) for g in multipla["giocate"]])
        # Una sola GET in tutto: la ricerca per (SA, giorno) della voce O/U,
        # riutilizzata dalla fonte 2 della seconda gamba.
        self.assertEqual(1, len(rete.chiamate), rete.chiamate)
        self.assertEqual((2, 1), (aggiornate, pending))
        self.assertEqual(1, len(salvate))
        self.assertEqual([ou, multipla], salvate[0])
        self.assertIs(multipla, salvate[0][1])

    def test_gamba_dal_registro_vivo_con_load_predictions(self):
        """Senza righe_vive il Registro vivo si rilegge: la gamba si abbinata per match_id."""
        import registry_store as rs
        kickoff = (datetime.now(timezone.utc) - timedelta(hours=5)).replace(
            second=0, microsecond=0)
        vivo = _riga_graduata("vv1", "Napoli", "Bologna", "Serie A",
                              kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"), "0-2")
        gambe = [_gamba("vv1", "Napoli", "Bologna", "Serie A", "2",
                        kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"))]
        multipla = _riga_multipla(gambe)
        ombra = [multipla]
        salvate = []
        rete = Rete()
        with mock.patch.object(rs, "load_ombra_rows", return_value=(ombra, "upstash")), \
             mock.patch.object(rs, "save_ombra_rows",
                               side_effect=lambda r, post=None: salvate.append(r)
                               or {"remoto": "ok"}), \
             mock.patch.object(app, "load_predictions", return_value=[vivo]), \
             mock.patch.object(app.requests, "get", side_effect=rete.get):
            aggiornate, pending = app.aggiorna_esiti_ombra(CHIAVE)
        self.assertEqual("✅", multipla["esito"])
        self.assertEqual("", multipla["risultato_reale"])
        self.assertEqual(("✅", "0-2"),
                         (multipla["giocate"][0]["esito_gamba"],
                          multipla["giocate"][0]["risultato_gamba"]))
        self.assertEqual([], rete.chiamate, "la fonte 1 basta: nessuna chiamata")
        self.assertEqual((1, 0), (aggiornate, pending))
        self.assertEqual([multipla], salvate[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
