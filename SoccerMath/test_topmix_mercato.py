"""Top Mix di mercato (``topmix_mercato_v3``): selettore, tabella unica, multipla.

Cosa viene provato (punti 3, 4, 5, 6 e 9 della commessa "quote live nel Top Mix"):

* **selettore di mercato** (``app.seleziona_riga_top_mix_mercato``, funzione
  pura): esito = argmax delle probabilita' di mercato, ammissione a 0,55,
  probabilita' e quota della STESSA fonte, probabilita' del modello (Drago) per
  lo stesso esito, segnale "d'accordo" (entrambi >= 0,55 e stesso esito, come
  nella PR #49 §4d). NESSUN filtro sulle quote basse: una quota 1,10 resta;
* **tabella unica**: le colonne richieste, e l'assenza di una tabella Legacy o
  Drago separata nel tab2 (guardia sul sorgente);
* **calcolatore di multipla**: 1 riga e 5 righe (casi richiesti), oltre le 5
  rifiutato, quota equa = 1/probabilita', edge = quota offerta/equa - 1, avviso
  sull'indipendenza sempre presente. Dalla rifinitura dopo la PR #53 la UI non
  mostra piu' quell'edge (e' il margine composto della fonte delle quote, sempre
  negativo e identico per tutto il giro) e offre il campo OPZIONALE
  ``quota_bookmaker``, da cui viene ``margine = quota * probabilita' - 1``: i
  due numeri restano nel dizionario di ritorno perche' ``multipla`` e' usata
  anche altrove, e il margine non calcolato resta ``None``. Vedi
  ``test_rifiniture_registro.py``;
* **registro**: le righe di mercato vanno nel Registro visibile con
  ``topmix_mercato_v3``; Drago e Legacy vanno nel registro ombra con
  ``topmix_ombra_1x2_v1`` e due chiavi di dedup distinte (stesse regole
  anti-doppione di prima).
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

import market_odds as mo  # noqa: E402
import prediction_registry as R  # noqa: E402
import app  # noqa: E402
from prediction_registry import (  # noqa: E402
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_LEGACY,
    dedup_key,
)

APP_PATH = os.path.join(HERE, "app.py")


def _match(mid, home, away, md=5, utc="2026-10-10T13:00:00Z"):
    return {"id": mid, "matchday": md, "utcDate": utc,
            "homeTeam": {"shortName": home}, "awayTeam": {"shortName": away}}


def _engine(stats):
    return (stats, 1.5, 1.2, {})


def _payload_quote(coppie, libro_pinnacle=("pinnacle",), commence="2026-10-10T13:00:00Z"):
    """Payload ``live_odds`` minimo: ``coppie`` = [(home, away, terna), ...]."""
    eventi = []
    for i, (h, a, terna) in enumerate(coppie):
        libri = [{"key": k, "title": k, "h2h": {"home": terna[0], "draw": terna[1], "away": terna[2]}}
                 for k in libro_pinnacle]
        eventi.append({"id": f"ev{i}", "commence_time": commence,
                       "home_team": h, "away_team": a, "libri": libri})
    return {"leghe": {"Serie A": {"eventi": eventi}}, "generato_il": "2026-10-09T08:17:00Z"}


class TestSelettoreDiMercato(unittest.TestCase):
    def test_l_esito_e_l_argmax_del_mercato(self):
        for probs, esito in [({"1": 0.60, "X": 0.25, "2": 0.15}, "1"),
                             ({"1": 0.20, "X": 0.60, "2": 0.20}, "X"),
                             ({"1": 0.20, "X": 0.20, "2": 0.60}, "2")]:
            riga = app.seleziona_riga_top_mix_mercato(probs, home="Inter", away="Roma")
            self.assertEqual(esito, riga["esito"], str(probs))
            self.assertEqual(esito, riga["mercato_standard"])

    def test_spareggio_sul_primo_massimo(self):
        """Due esiti uguali: vince il primo nell'ordine 1, X, 2 (come np.argmax)."""
        riga = app.seleziona_riga_top_mix_mercato({"1": 0.55, "X": 0.55, "2": 0.0})
        self.assertEqual("1", riga["esito"])
        riga2 = app.seleziona_riga_top_mix_mercato({"1": 0.20, "X": 0.55, "2": 0.55})
        self.assertEqual("X", riga2["esito"])

    def test_soglia_055(self):
        self.assertIsNotNone(app.seleziona_riga_top_mix_mercato(
            {"1": 0.55, "X": 0.25, "2": 0.20}, home="Inter", away="Roma"))
        self.assertIsNone(app.seleziona_riga_top_mix_mercato(
            {"1": 0.5499, "X": 0.25, "2": 0.20}, home="Inter", away="Roma"))

    def test_etichette_dell_esito(self):
        riga = app.seleziona_riga_top_mix_mercato({"1": 0.7, "X": 0.2, "2": 0.1},
                                                  home="Inter", away="Roma")
        self.assertEqual("Vittoria Inter", riga["market"])
        riga = app.seleziona_riga_top_mix_mercato({"1": 0.1, "X": 0.7, "2": 0.2},
                                                  home="Inter", away="Roma")
        self.assertEqual("Pareggio", riga["market"])
        riga = app.seleziona_riga_top_mix_mercato({"1": 0.1, "X": 0.2, "2": 0.7},
                                                  home="Inter", away="Roma")
        self.assertEqual("Vittoria Roma", riga["market"])

    def test_probabilita_e_quota_della_stessa_fonte(self):
        riga = app.seleziona_riga_top_mix_mercato(
            {"1": 0.6, "X": 0.25, "2": 0.15}, {"1": 1.62, "X": 4.1, "2": 6.5},
            fonte=mo.FONTE_PINNACLE, n_libri=3, home="Inter", away="Roma")
        self.assertAlmostEqual(0.6, riga["prob"])
        self.assertEqual(60.0, riga["prob_val"])
        self.assertEqual(1.62, riga["quota"], "la quota mostrata e' quella dell'esito scelto")
        self.assertEqual(mo.FONTE_PINNACLE, riga["fonte"])
        self.assertEqual(3, riga["n_libri"])

    def test_nessun_filtro_sulle_quote_basse(self):
        """Vincolo della commessa: una quota 1,10 NON viene scartata dall'app."""
        riga = app.seleziona_riga_top_mix_mercato(
            {"1": 0.90, "X": 0.06, "2": 0.04}, {"1": 1.10, "X": 15.0, "2": 21.0},
            home="Inter", away="Roma")
        self.assertIsNotNone(riga)
        self.assertEqual(1.10, riga["quota"])
        self.assertEqual("1", riga["esito"])


class TestSegnaleAccordo(unittest.TestCase):
    PROBS_MKT = {"1": 0.60, "X": 0.25, "2": 0.15}

    def test_accordo_se_stesso_esito_ed_entrambi_sopra_soglia(self):
        riga = app.seleziona_riga_top_mix_mercato(
            self.PROBS_MKT, prob_modello={"1": 0.58, "X": 0.25, "2": 0.17},
            home="Inter", away="Roma")
        self.assertTrue(riga["accordo"])
        self.assertAlmostEqual(0.58, riga["prob_modello"])
        self.assertEqual(58.0, riga["prob_modello_val"])

    def test_nessun_accordo_se_il_modello_e_sotto_soglia(self):
        riga = app.seleziona_riga_top_mix_mercato(
            self.PROBS_MKT, prob_modello={"1": 0.50, "X": 0.30, "2": 0.20},
            home="Inter", away="Roma")
        self.assertFalse(riga["accordo"])

    def test_nessun_accordo_se_il_modello_indica_un_altro_esito(self):
        riga = app.seleziona_riga_top_mix_mercato(
            self.PROBS_MKT, prob_modello={"1": 0.30, "X": 0.20, "2": 0.50},
            home="Inter", away="Roma")
        self.assertFalse(riga["accordo"])

    def test_modello_assente_non_e_un_accordo(self):
        riga = app.seleziona_riga_top_mix_mercato(self.PROBS_MKT, home="Inter", away="Roma")
        self.assertFalse(riga["accordo"])
        self.assertIsNone(riga["prob_modello"])
        self.assertIsNone(riga["prob_modello_val"])

    def test_accordo_ripete_la_regola_della_pr49(self):
        """PR #49 §4d: consenso = stesso argmax ed entrambi >= 0,55."""
        casi = [
            ({"1": 0.60, "X": 0.25, "2": 0.15}, {"1": 0.56, "X": 0.24, "2": 0.20}, True),
            ({"1": 0.60, "X": 0.25, "2": 0.15}, {"1": 0.54, "X": 0.26, "2": 0.20}, False),
            ({"2": 0.62, "X": 0.24, "1": 0.14}, {"2": 0.60, "X": 0.22, "1": 0.18}, True),
            ({"X": 0.58, "1": 0.24, "2": 0.18}, {"1": 0.60, "X": 0.22, "2": 0.18}, False),
        ]
        for mkt, mod, atteso in casi:
            riga = app.seleziona_riga_top_mix_mercato(mkt, prob_modello=mod,
                                                      home="Inter", away="Roma")
            self.assertEqual(atteso, riga["accordo"], f"{mkt} vs {mod}")


class TestIngressiNonValidi(unittest.TestCase):
    def test_probabilita_mancanti_o_malformate(self):
        for probs in (None, {}, {"1": 0.6, "X": 0.4},
                      {"1": 0.6, "X": 0.25, "2": None},
                      {"1": 0.6, "X": 0.25, "2": "0.15"},
                      {"1": 0.6, "X": 0.25, "2": float("nan")}):
            self.assertIsNone(app.seleziona_riga_top_mix_mercato(probs, home="A", away="B"),
                              str(probs))

    def test_quota_non_valida_non_inventa_un_numero(self):
        for odds in (None, {"1": 1.0, "X": 4.0, "2": 6.0}, {"1": None}, {"1": "1.6"}):
            riga = app.seleziona_riga_top_mix_mercato(
                {"1": 0.6, "X": 0.25, "2": 0.15}, odds, home="A", away="B")
            self.assertIsNone(riga["quota"], str(odds))




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


class TestCalcoloPerPartita(RipristinaLogging, unittest.TestCase):
    """``calcola_righe_top_mix(..., quote=...)`` produce le righe di mercato."""

    STATS = {"Inter": {"att": 1.25, "def": 0.85}, "Roma": {"att": 1.05, "def": 0.95},
             "Milan": {"att": 1.15, "def": 0.9}, "Napoli": {"att": 1.2, "def": 0.9}}

    def _calcola(self, quote, matches=None, elo=None):
        matches = matches or [_match(1, "Inter", "Roma"), _match(2, "Milan", "Napoli")]
        elo = elo or (lambda h, a, l, season=None: {"1": 0.58, "X": 0.24, "2": 0.18})
        with mock.patch.object(app, "predict_elo_probs", side_effect=elo), \
             mock.patch.object(app, "predict_elo_probs_legacy", side_effect=elo), \
             mock.patch.object(app, "_roster_stagione", return_value=None):
            return app.calcola_righe_top_mix("Serie A", matches, _engine(self.STATS), quote=quote)

    def test_righe_di_mercato_con_pinnacle(self):
        quote = mo.indice_partite(_payload_quote([
            ("Inter", "Roma", (1.62, 4.1, 6.0)),
            ("Milan", "Napoli", (4.5, 4.0, 1.7)),
        ]))
        quote["generato_il"] = "2026-10-09T08:17:00Z"
        righe = self._calcola(quote)
        self.assertEqual(2, len(righe["mercato"]))
        per_id = {r["match_id"]: r for r in righe["mercato"]}
        self.assertEqual("1", per_id[1]["esito"])
        self.assertEqual("2", per_id[2]["esito"])
        for r in righe["mercato"]:
            self.assertEqual(mo.FONTE_PINNACLE, r["fonte"])
            self.assertGreaterEqual(r["prob"], mo.SOGLIA_TOPMIX_MERCATO)
            self.assertEqual("2026-10-09T08:17:00Z", r["quote_live_istante"])
            self.assertIn("prob_modello", r)
            self.assertIn("accordo", r)

    def test_sotto_soglia_non_entra(self):
        quote = mo.indice_partite(_payload_quote([
            ("Inter", "Roma", (2.4, 3.2, 3.0)),      # max de-vig ~0,41
            ("Milan", "Napoli", (1.5, 4.5, 7.0)),     # max de-vig ~0,60
        ]))
        righe = self._calcola(quote)
        self.assertEqual(1, len(righe["mercato"]))
        self.assertEqual(2, righe["mercato"][0]["match_id"])
        self.assertEqual([], righe["senza_quote"])

    def test_partita_senza_quote_e_segnalata_per_nome(self):
        quote = mo.indice_partite(_payload_quote([("Inter", "Roma", (1.62, 4.1, 6.0))]))
        with self.assertLogs(level="WARNING") as cat:
            righe = self._calcola(quote)
        self.assertEqual(1, len(righe["mercato"]))
        self.assertEqual(1, len(righe["senza_quote"]))
        sq = righe["senza_quote"][0]
        self.assertEqual("Milan", sq["home"])
        self.assertEqual("Napoli", sq["away"])
        self.assertIn("partita assente dalla fonte quote", sq["motivo"])
        self.assertIn("Milan", "\n".join(cat.output))

    def test_evento_senza_libri_validi_e_segnalato(self):
        payload = _payload_quote([("Inter", "Roma", (1.62, 4.1, 6.0))])
        payload["leghe"]["Serie A"]["eventi"].append({
            "id": "ev9", "commence_time": "2026-10-10T13:00:00Z",
            "home_team": "Milan", "away_team": "Napoli", "libri": []})
        with self.assertLogs(level="WARNING") as cat:
            righe = self._calcola(mo.indice_partite(payload))
        self.assertEqual(1, len(righe["senza_quote"]))
        self.assertIn("nessuna terna h2h valida", righe["senza_quote"][0]["motivo"])
        self.assertIn("Napoli", "\n".join(cat.output))

    def test_senza_quote_non_vengono_passate_le_liste_restanto_vuote(self):
        """Il replay walk-forward non passa le quote: nessuna riga di mercato."""
        righe = self._calcola(None)
        self.assertEqual([], righe["mercato"])
        self.assertEqual([], righe["senza_quote"])
        self.assertIn(MODEL_VARIANT_CURRENT, righe)
        self.assertIn(MODEL_VARIANT_LEGACY, righe)

    def test_riserva_sulla_media_e_dichiarata_sulla_riga(self):
        payload = {"leghe": {"Serie A": {"eventi": [
            {"id": "ev0", "commence_time": "2026-10-10T13:00:00Z",
             "home_team": "Inter", "away_team": "Roma",
             "libri": [{"key": "unibet_nl", "h2h": {"home": 1.65, "draw": 4.0, "away": 5.8}},
                       {"key": "betclic_fr", "h2h": {"home": 1.6, "draw": 4.2, "away": 6.1}}]}]}}}
        righe = self._calcola(mo.indice_partite(payload),
                              matches=[_match(1, "Inter", "Roma")])
        self.assertEqual(1, len(righe["mercato"]))
        self.assertEqual(mo.FONTE_MEDIA_LIBRI, righe["mercato"][0]["fonte"])
        self.assertEqual(2, righe["mercato"][0]["n_libri"])


class TestTabellaUnica(unittest.TestCase):
    RIGHE = [
        {"home": "Inter", "away": "Roma", "league": "Serie A",
         "utcDate": "2026-10-10T13:00:00Z", "esito": "1", "prob_val": 61.7,
         "quota": 1.62, "prob_modello_val": 58.0, "accordo": True,
         "fonte": mo.FONTE_PINNACLE, "n_libri": 40, "rank": 1},
        {"home": "Milan", "away": "Napoli", "league": "Serie A",
         "utcDate": "2026-10-11T18:00:00Z", "esito": "2", "prob_val": 55.4,
         "quota": None, "prob_modello_val": None, "accordo": False,
         "fonte": mo.FONTE_MEDIA_LIBRI, "n_libri": 12, "rank": 2},
    ]

    def test_colonne_richieste_dalla_commessa(self):
        df = app.tabella_top_mix_mercato(self.RIGHE)
        for col in ("Partita", "Esito", "P mercato %", "Quota mercato",
                    "P modello Drago %", "D'accordo", "Fonte"):
            self.assertIn(col, df.columns, col)
        self.assertEqual(2, len(df))
        self.assertEqual(["1", "2"], list(df["Esito"]))
        self.assertEqual(["sì", "no"], list(df["D'accordo"]))
        self.assertEqual(["Pinnacle", "media di 12 libri"], list(df["Fonte"]))

    def test_tabella_vuota_ha_le_stesse_colonne(self):
        df = app.tabella_top_mix_mercato([])
        self.assertTrue(df.empty)
        self.assertIn("Partita", df.columns)

    def test_il_tab2_non_ha_piu_due_tabelle_di_modello(self):
        src = open(APP_PATH, encoding="utf-8").read()
        tab2 = src[src.index("with tab2:"):src.index("with tab3:")]
        # nessuna tabella Legacy / Drago separata nel Top Mix
        self.assertNotIn("MODEL_VARIANT_LEGACY, top_legacy,", tab2)
        self.assertNotIn("MODEL_VARIANT_CURRENT, top_current,", tab2)
        self.assertNotIn("_mostra_tabella_top_mix(", tab2)
        # una sola tabella di scelte, quella del mercato
        self.assertEqual(1, tab2.count("_mostra_tabella_top_mix_mercato("))
        self.assertIn("calcolatore_multipla(top_mercato)", tab2)
        # UN SOLO punto di scrittura nel Registro visibile per click (rifinitura
        # dopo la PR #53): le righe di mercato passano da `build_prediction_entry`
        # e il blocco si chiude con UNA `save_predictions`. `save_prediction_entry`
        # (che scrive a ogni chiamata) non deve piu' comparire nel tab2: prima
        # girava una volta per riga, cioe' ~40 scritture + ~40 backup + ~40 PUT.
        self.assertEqual(0, tab2.count("save_prediction_entry("),
                         "il tab2 deve scrivere il Registro una volta sola")
        self.assertEqual(1, tab2.count("save_predictions("))
        self.assertEqual(1, tab2.count("build_prediction_entry("))
        self.assertIn("argomenti_registro_top_mix_mercato(p)", tab2)
        # e le righe gia' registrate vengono riallineate anche sotto soglia
        self.assertIn("aggiorna_righe_mercato_in_attesa(", tab2)
        # Drago e Legacy finiscono nel registro ombra
        self.assertIn("salva_registro_ombra(", tab2)
        self.assertIn("righe_modello=", tab2)
        # le partite senza quote sono segnalate
        self.assertIn("senza_quote", tab2)

    def test_la_funzione_delle_due_tabelle_non_esiste_piu(self):
        self.assertFalse(hasattr(app, "_mostra_tabella_top_mix"),
                         "_mostra_tabella_top_mix (due tabelle) doveva sparire col Top Mix unico")
        self.assertTrue(hasattr(app, "_mostra_tabella_top_mix_mercato"))


class TestCalcolatoreMultipla(unittest.TestCase):
    def test_una_riga_sola(self):
        out = mo.multipla([{"partita": "Inter vs Roma", "esito": "1", "prob": 0.6, "quota": 1.70}])
        self.assertTrue(out["ok"])
        self.assertEqual(1, out["n_righe"])
        self.assertAlmostEqual(0.6, out["probabilita_combinata"])
        self.assertAlmostEqual(1 / 0.6, out["quota_equa"])
        self.assertAlmostEqual(1.70, out["quota_offerta"])
        self.assertAlmostEqual(1.70 * 0.6 - 1, out["edge"])
        self.assertIn("INDIPENDENTI", out["avviso"])

    def test_cinque_righe(self):
        righe = [{"partita": f"P{i}", "esito": "1", "prob": 0.6, "quota": 1.7} for i in range(5)]
        out = mo.multipla(righe)
        self.assertTrue(out["ok"])
        self.assertEqual(5, out["n_righe"])
        self.assertAlmostEqual(0.6 ** 5, out["probabilita_combinata"], places=12)
        self.assertAlmostEqual(1 / 0.6 ** 5, out["quota_equa"], places=9)
        self.assertAlmostEqual(1.7 ** 5, out["quota_offerta"], places=9)
        self.assertAlmostEqual(1.7 ** 5 * 0.6 ** 5 - 1, out["edge"], places=9)
        self.assertEqual(5, len(out["righe"]))

    def test_sei_righe_vengono_rifiutate(self):
        righe = [{"partita": f"P{i}", "esito": "1", "prob": 0.6, "quota": 1.7} for i in range(6)]
        out = mo.multipla(righe)
        self.assertFalse(out["ok"])
        self.assertIn("5", out["errore"])
        self.assertEqual(mo.MASSIMO_RIGHE_MULTIPLA, 5)

    def test_zero_righe(self):
        self.assertFalse(mo.multipla([])["ok"])
        self.assertFalse(mo.multipla(None)["ok"])

    def test_righe_non_valide(self):
        for righe in ([{"prob": 0.0, "quota": 1.7}], [{"prob": 1.0, "quota": 1.7}],
                      [{"prob": 0.6, "quota": 1.0}], [{"prob": 0.6, "quota": None}],
                      [{"prob": "0.6", "quota": 1.7}], [{"prob": 0.6}], ["x"]):
            out = mo.multipla(righe)
            self.assertFalse(out["ok"], str(righe))

    def test_edge_negativo_e_positivo(self):
        sotto = mo.multipla([{"prob": 0.6, "quota": 1.60}])
        self.assertLess(sotto["edge"], 0)
        sopra = mo.multipla([{"prob": 0.6, "quota": 1.75}])
        self.assertGreater(sopra["edge"], 0)
        # quota equa = 1/probabilita': con quota offerta = quota equa l'edge e' 0
        pari = mo.multipla([{"prob": 0.5, "quota": 2.0}])
        self.assertAlmostEqual(0.0, pari["edge"], places=12)

    def test_le_probabilita_sono_indipendenti_per_ipotesi_e_si_dice(self):
        out = mo.multipla([{"prob": 0.6, "quota": 1.7}, {"prob": 0.6, "quota": 1.7}])
        self.assertAlmostEqual(0.36, out["probabilita_combinata"], places=12)
        self.assertIn("INDIPENDENTI", out["avviso"])
        self.assertIn("non lo sono", out["avviso"].lower())

    def test_selezione_per_etichetta(self):
        righe = [{"home": "Inter", "away": "Roma", "esito": "1", "prob_val": 60.0,
                  "quota": 1.7, "prob": 0.6, "rank": 1},
                 {"home": "Milan", "away": "Napoli", "esito": "2", "prob_val": 55.0,
                  "quota": 2.1, "prob": 0.55, "rank": 2}]
        etichette = [app.etichetta_riga_multipla(p) for p in righe]
        self.assertEqual(len(etichette), len(set(etichette)), "etichette non univoche")
        scelte = app.righe_multipla(righe, [etichette[1]])
        self.assertEqual(1, len(scelte))
        self.assertEqual("Milan", scelte[0]["home"])
        # un'etichetta che non c'e' non inventa una riga
        self.assertEqual([], app.righe_multipla(righe, ["inesistente"]))


class TestRegistro(unittest.TestCase):
    RIGA_MERCATO = {
        "league": "Serie A", "giornata": 5, "home": "Inter", "away": "Roma", "match_id": 4242,
        "utcDate": "2026-10-10T13:00:00Z", "market": "Vittoria Inter", "mercato_standard": "1",
        "esito": "1", "prob": 0.617, "prob_val": 61.7, "quota": 1.62,
        "prob_modello": 0.58, "prob_modello_val": 58.0, "accordo": True,
        "fonte": mo.FONTE_PINNACLE, "n_libri": 40,
        "quote_live_istante": "2026-10-09T08:17:00Z", "rank": 1,
    }
    RIGA_MODELLO = {
        "league": "Serie A", "giornata": 5, "home": "Inter", "away": "Roma", "match_id": 4242,
        "utcDate": "2026-10-10T13:00:00Z", "market": "Vittoria Inter", "mercato_standard": "1",
        "prob": 0.6123, "prob_val": 61.2, "poisson": 58.0, "elo": 62.3,
        "elo_disponibile": True, "rank": 3,
    }

    def test_la_riga_di_mercato_usa_la_versione_nuova(self):
        args, kwargs = app.argomenti_registro_top_mix_mercato(self.RIGA_MERCATO)
        self.assertEqual(R.SELECTOR_VERSION_MERCATO_V3, kwargs["selector_version"])
        self.assertEqual(R.SELECTOR_VERSION_CURRENT, kwargs["selector_version"])
        self.assertEqual(R.ORIGIN_TOP_MIX, kwargs["origin"])
        self.assertEqual(1.62, kwargs["quota_mercato"])
        self.assertEqual(mo.FONTE_PINNACLE, kwargs["mercato_fonte"])
        self.assertEqual(40, kwargs["mercato_n_libri"])
        self.assertTrue(kwargs["accordo_modello"])
        self.assertEqual(58.0, kwargs["prob_modello"])
        self.assertAlmostEqual(0.617, kwargs["prob_mercato"])
        self.assertEqual("2026-10-09T08:17:00Z", kwargs["quote_live_istante"])
        for fn in (app.save_prediction_entry, app.build_prediction_entry):
            import inspect
            inspect.signature(fn).bind(*args, **kwargs)

    def test_il_record_porta_i_campi_di_mercato(self):
        args, kwargs = app.argomenti_registro_top_mix_mercato(self.RIGA_MERCATO)
        entry = app.build_prediction_entry(*args, **kwargs, snapshot_sha="abc")
        self.assertEqual(mo.FONTE_PINNACLE, entry[R.MERCATO_FONTE_FIELD])
        self.assertEqual(1.62, entry[R.QUOTA_MERCATO_FIELD])
        self.assertTrue(entry[R.ACCORDO_MODELLO_FIELD])
        self.assertEqual("1", entry["mercato_standard"])
        self.assertEqual(61.7, entry["prob_sicuro"])

    def test_le_righe_del_modello_vanno_nell_ombra_con_la_loro_versione(self):
        _args, kwargs = app.argomenti_registro_top_mix(self.RIGA_MODELLO,
                                                       model_variant=MODEL_VARIANT_CURRENT)
        self.assertEqual(R.SELECTOR_VERSION_OMBRA_1X2, kwargs["selector_version"])
        self.assertNotEqual(R.SELECTOR_VERSION_CURRENT, kwargs["selector_version"])

    def test_drago_e_legacy_hanno_chiavi_di_dedup_diverse(self):
        cur = app.build_ombra_modello_entry(self.RIGA_MODELLO, model_variant=MODEL_VARIANT_CURRENT,
                                            snapshot_sha="abc", salvato_il="10/10/2026 10:00")
        leg = app.build_ombra_modello_entry(self.RIGA_MODELLO, model_variant=MODEL_VARIANT_LEGACY,
                                            snapshot_sha="abc", salvato_il="10/10/2026 10:00")
        self.assertNotEqual(dedup_key(cur), dedup_key(leg),
                            "Drago e Legacy devono restare due righe distinte")
        for e in (cur, leg):
            self.assertTrue(e[R.OMBRA_FIELD])
            self.assertEqual(R.ORIGIN_TOP_MIX_OMBRA, e["origin"])
            self.assertEqual(R.OMBRA_FAMIGLIA_1X2, e[R.OMBRA_FAMIGLIA_FIELD])
            self.assertEqual(R.SELECTOR_VERSION_OMBRA_1X2, e["selector_version"])
            self.assertEqual(0.55, e[R.OMBRA_SOGLIA_FIELD])
            self.assertTrue(e[R.OMBRA_AMMESSA_FIELD])

    def test_l_ombra_1x2_non_collide_con_l_ombra_dei_totali(self):
        riga_ou = {**self.RIGA_MODELLO, "market": "Over 2.5", "mercato_standard": "OVER_2.5",
                   "confidence": 0.62, "ammessa": True, "vincente_globale": False,
                   "famiglia": R.OMBRA_FAMIGLIA_OU25}
        ou = app.build_ombra_entry(riga_ou, snapshot_sha="abc", salvato_il="10/10/2026 10:00")
        x1 = app.build_ombra_modello_entry(self.RIGA_MODELLO, snapshot_sha="abc",
                                           salvato_il="10/10/2026 10:00")
        self.assertNotEqual(dedup_key(ou), dedup_key(x1))

    def test_senza_elo_la_soglia_ombra_e_060(self):
        riga = {**self.RIGA_MODELLO, "elo_disponibile": False}
        e = app.build_ombra_modello_entry(riga, snapshot_sha="abc", salvato_il="10/10/2026 10:00")
        self.assertEqual(0.60, e[R.OMBRA_SOGLIA_FIELD])
        self.assertTrue(e[R.OMBRA_AMMESSA_FIELD])

    def test_le_regole_anti_doppione_sono_quelle_di_prima(self):
        """Upsert in blocco: stessa semantica di prima, una riga giudicata non si tocca."""
        base = app.build_ombra_modello_entry(self.RIGA_MODELLO, snapshot_sha="abc",
                                             salvato_il="10/10/2026 10:00")
        lista, azioni = R.upsert_prediction_entries([], [base])
        self.assertEqual(1, azioni["aggiunta"])
        # ricalcolo della stessa previsione -> sostituita, non duplicata
        lista2, azioni2 = R.upsert_prediction_entries(lista, [base])
        self.assertEqual(0, azioni2.get("aggiunta", 0))
        self.assertEqual(1, azioni2["aggiornata"])
        self.assertEqual(1, len(lista2))
        # gia' giudicata -> intoccata
        lista[0]["esito"] = R.ESITO_VINTO
        lista3, azioni3 = R.upsert_prediction_entries(lista, [base])
        self.assertEqual(1, azioni3.get("gia_graduata", 0))
        self.assertEqual(R.ESITO_VINTO, lista3[0]["esito"])
        self.assertEqual(1, len(lista3))

    def test_la_riga_di_mercato_non_e_bloccata_da_una_riga_del_modello(self):
        """Due selettori diversi sulla stessa partita: coesistono.

        La regola dei doppioni fra versioni vale dentro la STESSA famiglia di
        selettore: una riga v2 del modello gia' scritta non deve impedire la
        riga v3 del mercato (PR #49 §4d: le due scelte coincidono su 1144
        partite e divergono sulle altre).
        """
        vecchia = app.build_prediction_entry(
            *app.argomenti_registro_top_mix(self.RIGA_MODELLO,
                                            model_variant=MODEL_VARIANT_CURRENT)[0],
            **{**app.argomenti_registro_top_mix(self.RIGA_MODELLO,
                                                model_variant=MODEL_VARIANT_CURRENT)[1],
               "selector_version": R.SELECTOR_VERSION_MODELLO_1X2},
            snapshot_sha="abc", salvato_il="01/10/2026 10:00")
        args, kwargs = app.argomenti_registro_top_mix_mercato(self.RIGA_MERCATO)
        nuova = app.build_prediction_entry(*args, **kwargs, snapshot_sha="abc",
                                           salvato_il="09/10/2026 08:20")
        self.assertNotEqual(R.chiave_tabella_mercato(vecchia),
                            R.chiave_tabella_mercato(nuova))
        lista, azioni = R.upsert_prediction_entries([vecchia], [nuova])
        self.assertEqual(1, azioni.get("aggiunta", 0), azioni)
        self.assertEqual(2, len(lista))
        # due righe della STESSA famiglia (mercato v3 due volte) restano una
        lista2, azioni2 = R.upsert_prediction_entries(lista, [nuova])
        self.assertEqual(1, azioni2.get("aggiornata", 0), azioni2)
        self.assertEqual(2, len(lista2))


class TestEndToEndConQuoteSimulate(unittest.TestCase):
    """``fetch_and_calc_top_mix`` con HTTP ed Elo simulati e quote dal file."""

    # nomi REALI: l'abbinamento delle quote passa dal resolver di produzione,
    # che non indovina i nomi (nessun fuzzy matching).
    SQUADRE = [("Inter", "Roma"), ("Milan", "Napoli"), ("Juventus", "Lazio")]
    STATS = {h: {"att": 1.25, "def": 0.85} for h, _a in SQUADRE}
    STATS.update({a: {"att": 0.85, "def": 1.15} for _h, a in SQUADRE})

    def test_ritorna_sei_valori_e_la_tabella_di_mercato(self):
        matches = [_match(100 + i, h, a) for i, (h, a) in enumerate(self.SQUADRE)]
        payload = {"leghe": {"Serie A": {"eventi": [
            {"id": f"e{i}", "commence_time": "2026-10-10T13:00:00Z",
             "home_team": h, "away_team": a,
             "libri": [{"key": "pinnacle", "h2h": {"home": 1.55, "draw": 4.2, "away": 6.5}}]}
            for i, (h, a) in enumerate(self.SQUADRE[:2])]}},
            "generato_il": "2026-10-09T08:17:00Z"}
        indice = mo.indice_partite(payload)
        indice["generato_il"] = "2026-10-09T08:17:00Z"
        indice["crediti"] = {"residui": 495, "quota_mensile": 500}
        indice["fonte"] = "the-odds-api"
        indice["regioni"] = "eu"
        indice["n_leghe_ok"] = 5
        indice["n_leghe_richieste"] = 5

        class _Resp:
            status_code = 200

            def json(self):
                return {"matches": matches}

        elo = lambda h, a, l, season=None: {"1": 0.62, "X": 0.22, "2": 0.16}
        with mock.patch.object(app.requests, "get", return_value=_Resp()), \
             mock.patch.object(app, "get_league_engine", return_value=_engine(self.STATS)), \
             mock.patch.object(app, "predict_elo_probs", side_effect=elo), \
             mock.patch.object(app, "predict_elo_probs_legacy", side_effect=elo), \
             mock.patch.object(app, "select_next_matchday_matches", side_effect=lambda m, now=None: m), \
             mock.patch.object(app, "_roster_stagione", return_value=None), \
             mock.patch.object(app, "carica_indice_quote_live",
                               return_value=dict(indice, stato=mo.STATO_OK)), \
             mock.patch.object(app.time, "sleep", lambda s: None):
            app.fetch_and_calc_top_mix.clear()
            out = app.fetch_and_calc_top_mix()
        self.assertEqual(7, len(out))
        (top_mercato, top_current, top_legacy, missing, ombra, senza_quote,
         letture) = out
        n_leghe = len(app.LEAGUES_CONFIG)
        # 2 partite con quote per lega, entrambe sopra soglia -> 2 * n_leghe
        self.assertEqual(2 * n_leghe, len(top_mercato))
        self.assertEqual(1 * n_leghe, len(senza_quote))
        self.assertEqual([], missing)
        # le scelte del modello coprono TUTTE e 3 le partite per lega
        self.assertEqual(3 * n_leghe, len(top_current))
        self.assertEqual(3 * n_leghe, len(top_legacy))
        self.assertEqual(2 * 3 * n_leghe, len(ombra))
        self.assertEqual(list(range(1, 2 * n_leghe + 1)), [r["rank"] for r in top_mercato])
        for r in top_mercato:
            self.assertEqual("1", r["esito"])
            self.assertEqual(mo.FONTE_PINNACLE, r["fonte"])
            self.assertGreaterEqual(r["prob"], mo.SOGLIA_TOPMIX_MERCATO)

    def test_senza_file_delle_quote_il_top_mix_e_vuoto_ma_i_modelli_no(self):
        matches = [_match(100, *self.SQUADRE[0])]

        class _Resp:
            status_code = 200

            def json(self):
                return {"matches": matches}

        elo = lambda h, a, l, season=None: {"1": 0.62, "X": 0.22, "2": 0.16}
        with mock.patch.object(app.requests, "get", return_value=_Resp()), \
             mock.patch.object(app, "get_league_engine", return_value=_engine(self.STATS)), \
             mock.patch.object(app, "predict_elo_probs", side_effect=elo), \
             mock.patch.object(app, "predict_elo_probs_legacy", side_effect=elo), \
             mock.patch.object(app, "select_next_matchday_matches", side_effect=lambda m, now=None: m), \
             mock.patch.object(app, "_roster_stagione", return_value=None), \
             mock.patch.object(app, "carica_indice_quote_live",
                               return_value={"stato": mo.STATO_ASSENTE, "indice": None}), \
             mock.patch.object(app.time, "sleep", lambda s: None):
            app.fetch_and_calc_top_mix.clear()
            (top_mercato, top_current, top_legacy, missing, ombra, senza_quote,
             letture) = app.fetch_and_calc_top_mix()
        self.assertEqual([], top_mercato)
        self.assertEqual([], senza_quote)
        self.assertEqual([], letture, "senza file delle quote non c'e' nessuna lettura")
        self.assertEqual(len(app.LEAGUES_CONFIG), len(top_current))


if __name__ == "__main__":
    unittest.main(verbosity=2)
