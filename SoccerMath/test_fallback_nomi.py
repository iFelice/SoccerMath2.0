"""Nomi squadra senza fallback silenziosi: errore, esclusione, marcatore.

Cosa viene provato (commessa "eliminare i fallback silenziosi sui nomi squadra"):

* caso (a) NOME SCONOSCIUTO (il nome pulito non e' in R(lega, stagione)):
  ``predict_elo_probs`` solleva ``EloSeedError`` col nome GREZZO e quello
  PULITO; nel Top Mix la partita e' ESCLUSA da entrambe le tabelle; in Analisi
  Rapida non si scrive nessuna riga e compare un avviso esplicito; nella
  scheda PARTITE la card non si costruisce (avviso esplicito in scheda).
  Nessuno di questi percorsi usa le statistiche di default;
* caso (b) ROSTER SENZA STATISTICHE (la squadra e' nel calendario della
  stagione ma il motore non ha ancora dati, per es. una neopromossa prima del
  debutto): il comportamento numerico e' INVARIATO (default att=1.0 def=1.0),
  ma non e' piu' silenzioso: WARNING nel log col nome grezzo e pulito,
  marcatore ``dati_mancanti`` sulla riga del Top Mix e marcatore nella card
  della scheda PARTITE;
* nome NOTO: le righe hanno ESATTAMENTE lo schema di prima, chiave per chiave
  (la chiave ``dati_mancanti`` compare solo quando serve);
* roster NON disponibile: il chiamante resta permissivo (solo il caso b e'
  valutabile) e nulla viene escluso per un limite di dati.
"""
from __future__ import annotations

import logging
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

logging.getLogger("streamlit").setLevel(logging.ERROR)

import app  # noqa: E402
from models.elo_engine import EloSeedError  # noqa: E402
from prediction_registry import (  # noqa: E402
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_LEGACY,
)

MATCH_UTC = "2026-10-17T14:30:00Z"          # stagione 2026
STATS_BASE = {"att": 1.2, "def": 0.9, "att0": 1.2, "def0": 0.9,
              "att0_pure": 1.2, "def0_pure": 0.9}
POISSON = {"1": 0.70, "X": 0.18, "2": 0.12, "u15": 0.35, "u25": 0.55,
           "u35": 0.75, "gg": 0.60}
ELO = {"1": 0.60, "X": 0.20, "2": 0.20}


class RipristinaLogging:
    """Alcuni file di test del repo chiamano ``logging.disable(CRITICAL)`` e non
    lo ripristinano: lo stato globale dipende dall'ordine dei file. I WARNING
    sono qui parte del contratto in prova, quindi il setUp li riabilita e il
    tearDown rimette ESATTAMENTE lo stato trovato."""

    def setUp(self):
        self._disable_precedente = logging.root.manager.disable
        logging.disable(logging.NOTSET)

    def tearDown(self):
        logging.disable(self._disable_precedente)


def _match(mid, h, a, utc=MATCH_UTC):
    return {"id": mid, "matchday": 8, "utcDate": utc,
            "homeTeam": {"shortName": h}, "awayTeam": {"shortName": a}}


def _engine(stats):
    return (stats, 1.5, 1.2, {})


ROSTER_BUNDES_2026 = {"Bayern", "Koln", "Stuttgart", "Elversberg"}


class _CatturaLog:
    """Raccoglie i record WARNING+ del root logger (tollera lo zero).

    ``assertLogs`` fallisce se nessun record arriva: qui l'ASSSENZA di avvisi
    e' essa stessa un esito da verificare, quindi la cattura non puo' esigere
    almeno un record.
    """

    def __init__(self):
        self.output = []

    def __enter__(self):
        self._handler = logging.Handler()
        self._handler.emit = lambda record: self.output.append(
            f"{record.levelname}:{record.name}:{record.getMessage()}")
        self._root = logging.getLogger()
        self._root.addHandler(self._handler)
        return self

    def __exit__(self, *exc):
        self._root.removeHandler(self._handler)
        return False

    def testo(self):
        return "\n".join(self.output)


def _gira_top_mix(tc, matches, stats, roster=ROSTER_BUNDES_2026):
    """calcola_righe_top_mix con roster e Poisson/Elo controllati.

    Ritorna (righe, _CatturaLog): il Poisson e' stubbato perche' il contratto
    in prova e' la classificazione dei nomi, non la matematica del selettore.
    """
    with mock.patch.object(app, "get_full_poisson_two_heads", return_value=dict(POISSON)), \
         mock.patch.object(app, "predict_elo_probs", return_value=dict(ELO)), \
         mock.patch.object(app, "predict_elo_probs_legacy", return_value=dict(ELO)), \
         mock.patch.object(app, "_roster_stagione",
                           return_value=set(roster) if roster is not None else None), \
         _CatturaLog() as cattura:
        righe = app.calcola_righe_top_mix("Bundesliga", matches, _engine(stats))
    return righe, cattura


class TestTopMixNomeSconosciuto(RipristinaLogging, unittest.TestCase):
    STATS = {"Bayern": dict(STATS_BASE), "Stuttgart": dict(STATS_BASE)}

    def test_partita_esclusa_da_entrambe_le_tabelle(self):
        matches = [_match(1, "FC Colonia Inventata", "Bayern"),
                   _match(2, "Koln", "Stuttgart")]
        righe, cattura = _gira_top_mix(self, matches, self.STATS)
        log = cattura.testo()
        for variante in (MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY):
            self.assertEqual([2], [r["match_id"] for r in righe[variante]],
                             "solo la partita con nomi noti entra in tabella")
        self.assertIn("FC Colonia Inventata", log)
        self.assertIn("'Colonia Inventata'", log)
        self.assertIn("SCONOSCIUTO", log)

    def test_nessuna_statistica_di_default_al_sconosciuto(self):
        """Il fallimento e' LOUD: se la partita entrasse in tabella col default,
        questa guardia non la vedrebbe sparire. La riga del conosciuto resta."""
        righe, cattura = _gira_top_mix(
            self, [_match(1, "Squadra Che Non Esiste", "Bayern")], self.STATS)
        self.assertEqual(1, len(cattura.output), "illogico: lo sconosciuto deve lasciare il warning")
        self.assertEqual([], righe[MODEL_VARIANT_CURRENT])
        self.assertEqual([], righe[MODEL_VARIANT_LEGACY])

    def test_roster_non_disponibile_non_esclude_nessuno(self):
        """Roster None = non valutabile: il chiamante resta permissivo e il
        comportamento e' quello di sempre (nessuna esclusione per limite dati)."""
        matches = [_match(1, "Squadra Fuori Ogni Mappa", "Bayern")]
        righe, cattura = _gira_top_mix(self, matches, self.STATS, roster=None)
        log = cattura.testo()
        self.assertEqual([1], [r["match_id"] for r in righe[MODEL_VARIANT_CURRENT]])
        self.assertNotIn("SCONOSCIUTO", log)


class TestTopMixRosterSenzaStats(RipristinaLogging, unittest.TestCase):
    STATS = {"Bayern": dict(STATS_BASE)}          # Koln NON ha statistiche

    def test_riga_invariata_più_marcatore_e_warning(self):
        righe, cattura = _gira_top_mix(self, [_match(1, "Köln", "Bayern")], self.STATS)
        log = cattura.testo()
        attese = [MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY]
        self.assertEqual(attese, sorted(righe))
        for r in righe[MODEL_VARIANT_CURRENT]:
            self.assertEqual(["Koln"], r["dati_mancanti"],
                             "marcatore sul lato senza statistiche (nome pulito)")
        self.assertIn("Köln", log)
        self.assertIn("'Koln'", log)
        self.assertIn("att=1.0 def=1.0", log)

    def test_riga_senza_dati_mancanti_ha_lo_schema_di_prima(self):
        """Nome noto con statistiche: ESATTAMENTE le chiavi di sempre."""
        stats = {"Bayern": dict(STATS_BASE), "Koln": dict(STATS_BASE)}
        righe, cattura = _gira_top_mix(self, [_match(1, "Köln", "Bayern")], stats)
        log = cattura.testo()
        self.assertEqual([], cattura.output, "nome noto con statistiche: NESSUN avviso")
        self.assertEqual(
            sorted(["league", "giornata", "home", "away", "match_id", "utcDate",
                    "market", "mercato_standard", "prob", "prob_val", "poisson",
                    "elo", "elo_disponibile", "rank"]),
            sorted(righe[MODEL_VARIANT_CURRENT][0]),
            "nessuna chiave nuova per le righe normali")
        self.assertNotIn("att=1.0", log)


class TestAnalisiRapidaNomi(RipristinaLogging, unittest.TestCase):
    MATCHES = [_match(1, "FC Colonia Inventata", "Bayern"),
               _match(2, "Köln", "Bayern")]
    STATS = {"Bayern": dict(STATS_BASE)}          # Koln senza statistiche

    def _gira(self, matches, stats, roster=ROSTER_BUNDES_2026):
        salvate = []
        with mock.patch.object(app, "get_full_poisson_two_heads", return_value=dict(POISSON)), \
             mock.patch.object(app, "predict_elo_probs", return_value=dict(ELO)), \
             mock.patch.object(app, "predict_elo_probs_legacy", return_value=dict(ELO)), \
             mock.patch.object(app, "save_prediction_entry",
                               side_effect=lambda *a, **k: salvate.append((a, k)) or {"azione": "aggiunta"}), \
             mock.patch.object(app, "_roster_stagione",
                               return_value=set(roster) if roster is not None else None), \
             mock.patch.object(app.st, "warning") as warn, \
             mock.patch.object(app.st, "info") as info, \
             _CatturaLog() as cattura:
            n = app.analisi_rapida_giornata(matches, stats, 1.5, 1.2,
                                            "Bundesliga", {}, 8)
        return n, salvate, cattura, warn, info

    def test_sconosciuto_nessuna_riga_e_avviso_esplicito(self):
        n, salvate, cattura, warn, _info = self._gira([self.MATCHES[0]], self.STATS)
        log = cattura.testo()
        self.assertEqual(1, len(cattura.output), "un warning nel log per lo sconosciuto")
        self.assertEqual(0, n, "nome sconosciuto: nessuna riga scritta")
        self.assertEqual([], salvate)
        self.assertIn("FC Colonia Inventata", log)
        self.assertIn("'Colonia Inventata'", log)
        self.assertEqual(1, warn.call_count, "avviso esplicito in UI")
        self.assertIn("FC Colonia Inventata", str(warn.call_args))

    def test_entrante_senza_stats_comportamento_invariato(self):
        """Köln nel roster senza statistiche: righe scritte come sempre col
        default, IDENTICHE a quelle con stats {att:1.0, def:1.0} date, piu'
        l'avviso nel log e in UI che lo dichiara."""
        _n, con_default, cattura, _warn, info = self._gira([self.MATCHES[1]], self.STATS)
        log = cattura.testo()
        stats_dato = {"Bayern": dict(STATS_BASE), "Koln": {"att": 1.0, "def": 1.0}}
        _n2, con_dato, _cattura2, _warn2, _info2 = self._gira([self.MATCHES[1]], stats_dato)
        self.assertEqual(len(con_dato), len(con_default))
        self.assertEqual(2, len(con_default), "due righe (current + legacy)")
        self.assertEqual([a for a, _k in con_default], [a for a, _k in con_dato],
                         "stessi argomenti posizionali: default = dati dati")
        self.assertEqual([k for _a, k in con_default], [k for _a, k in con_dato],
                         "stessi kwargs: il comportamento numerico non cambia")
        self.assertIn("Köln", log)
        self.assertIn("'Koln'", log)
        self.assertTrue(any("att=1.0 def=1.0" in str(c) for c in info.call_args_list),
                        "in UI si dice quali squadre hanno usato il default")

    def test_nomi_noti_nessun_avviso(self):
        stats = {"Bayern": dict(STATS_BASE), "Koln": dict(STATS_BASE)}
        _n, salvate, cattura, warn, info = self._gira([self.MATCHES[1]], stats)
        log = cattura.testo()
        self.assertEqual(2, len(salvate))
        self.assertEqual([], [w for w in warn.call_args_list])
        self.assertEqual([], [c for c in info.call_args_list])
        self.assertEqual([], cattura.output, "nome noto con statistiche: NESSUN avviso")
        self.assertNotIn("SCONOSCIUTO", log)
        self.assertNotIn("att=1.0 def=1.0", log)


class TestSchedaPartiteNomi(RipristinaLogging, unittest.TestCase):
    """Scheda PARTITE: stesso trattamento di Top Mix e Analisi Rapida.

    La logica della card vive in ``dati_card_partita`` (il tab Streamlit la
    chiama per ogni partita del giorno): qui si prova la funzione e, in coda,
    una guardia di cablaggio sul sorgente del tab.
    """

    def _gira(self, match, stats, roster=ROSTER_BUNDES_2026):
        chiamate = []

        def _poisson(h_s, a_s, avg_h, avg_a):
            chiamate.append((dict(h_s), dict(a_s), avg_h, avg_a))
            return dict(POISSON)

        with mock.patch.object(app, "get_full_poisson_two_heads", side_effect=_poisson), \
             mock.patch.object(app, "blend_elo_into_1x2",
                               side_effect=lambda m, h, a, camp, **kw: dict(m)), \
             mock.patch.object(app, "_roster_stagione",
                               return_value=set(roster) if roster is not None else None), \
             _CatturaLog() as cattura:
            esito = app.dati_card_partita(match, stats, 1.5, 1.2, "Bundesliga")
        return esito, chiamate, cattura

    def test_sconosciuto_niente_default_niente_card(self):
        stats = {"Bayern": dict(STATS_BASE)}
        match = _match(1, "Zeta FC", "Bayern")
        (h, a, m_poisson, m, sconosciuti, senza), chiamate, cattura = self._gira(match, stats)
        log = cattura.testo()
        self.assertIsNone(m_poisson, "nome sconosciuto: nessun Poisson calcolato")
        self.assertIsNone(m, "nome sconosciuto: nessuna card costruita")
        self.assertEqual([], chiamate, "NESSUNA statistica di default al sconosciuto")
        self.assertEqual([("Zeta FC", "Zeta")], sconosciuti)
        self.assertEqual([], senza)
        self.assertIn("PARTITE", log)
        self.assertIn("SCONOSCIUTO", log)
        self.assertIn("'Zeta FC'", log, "nome GREZZO nel log")
        self.assertIn("'Zeta'", log, "nome PULITO nel log")

    def test_entrante_senza_stats_invariato_e_marcato(self):
        stats = {"Bayern": dict(STATS_BASE)}          # Koln senza statistiche
        match = _match(2, "Köln", "Bayern")
        (h, a, m_poisson, m, sconosciuti, senza), chiamate, cattura = self._gira(match, stats)
        log = cattura.testo()
        self.assertEqual([], sconosciuti)
        self.assertEqual([("Köln", "Koln")], senza)
        self.assertEqual(dict(POISSON), m)
        self.assertEqual(1, len(chiamate))
        h_s, a_s, avg_h, avg_a = chiamate[0]
        self.assertEqual({"att": 1.0, "def": 1.0}, h_s,
                         "il Poisson riceve il default per l'entrante (invariato)")
        self.assertEqual(dict(STATS_BASE), a_s)
        self.assertEqual((1.5, 1.2), (avg_h, avg_a))
        self.assertIn("Köln", log)
        self.assertIn("'Koln'", log)
        self.assertIn("att=1.0 def=1.0", log)

    def test_nomi_noti_output_identico_zero_avvisi(self):
        stats = {"Bayern": dict(STATS_BASE), "Stuttgart": dict(STATS_BASE)}
        match = _match(3, "Bayern", "Stuttgart")
        (h, a, m_poisson, m, sconosciuti, senza), chiamate, cattura = self._gira(match, stats)
        self.assertEqual(("Bayern", "Stuttgart"), (h, a))
        self.assertEqual(dict(POISSON), m_poisson)
        self.assertEqual(dict(POISSON), m)
        self.assertEqual([], sconosciuti)
        self.assertEqual([], senza)
        self.assertEqual([(dict(STATS_BASE), dict(STATS_BASE), 1.5, 1.2)], chiamate)
        self.assertEqual([], cattura.output, "nome noto con statistiche: NESSUN avviso")

    def test_roster_non_disponibile_permissivo(self):
        stats = {"Bayern": dict(STATS_BASE)}          # Koln senza statistiche
        match = _match(4, "Köln", "Bayern")
        (h, a, m_poisson, m, sconosciuti, senza), chiamate, cattura = self._gira(
            match, stats, roster=None)
        self.assertEqual([], sconosciuti, "roster non noto: nessuno e' 'sconosciuto'")
        self.assertEqual([("Köln", "Koln")], senza)
        self.assertEqual(dict(POISSON), m, "comportamento invariato")
        self.assertEqual(1, len(chiamate))

    def test_cablaggio_scheda_partite(self):
        """Il tab PARTITE passa da ``dati_card_partita``: avviso caso (a) e
        marcatore caso (b) in scheda, niente default inline residui."""
        with open(os.path.join(HERE, "app.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("def dati_card_partita(match, team_stats, avg_h, avg_a, camp_sel):", src)
        chiamata = ("h_api, a_api, m_poisson, m, sconosciuti, senza_stats = "
                    "dati_card_partita(match, team_stats, avg_h, avg_a, camp_sel)")
        self.assertEqual(1, src.count(chiamata), "il tab chiama l'helper")
        self.assertIn('st.warning(f"⚠️ PARTITE:', src, "avviso esplicito in scheda (caso a)")
        self.assertIn("stats di default (nessun dato: ", src, "marcatore nella card (caso b)")
        inline_vecchio = 'h_s = team_stats.get(clean_name(h_api), {"att": 1.0, "def": 1.0})'
        self.assertEqual(1, src.count(inline_vecchio),
                         "il default inline resta SOLO dentro l'helper")


class TestRosterStagione(unittest.TestCase):
    def test_rostere_reale_della_stagione_corrente(self):
        roster = app._roster_stagione("Bundesliga", 2026)
        self.assertIsInstance(roster, set)
        self.assertIn("Koln", roster, "la forma pulita dell'API shortName 'Köln'")
        self.assertNotIn("Köln", roster, "le chiavi del roster sono gia' pulite")

    def test_stagione_senza_roster_restituisce_none(self):
        self.assertIsNone(app._roster_stagione("Bundesliga", 2099))

    def test_motore_non_disponibile_restituisce_none(self):
        with mock.patch.object(app, "get_elo_engine", side_effect=RuntimeError("ko")):
            self.assertIsNone(app._roster_stagione("Bundesliga", 2026))

    def test_stagione_none_restituisce_none(self):
        self.assertIsNone(app._roster_stagione("Bundesliga", None))


if __name__ == "__main__":
    unittest.main()
