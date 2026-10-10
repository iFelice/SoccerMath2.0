"""Rifiniture dopo la PR #53: rinfresco sotto soglia, statistiche per registrazione, margine multipla.

Tre blocchi, uno per punto della commessa (i numeri di ogni asserzione sono gli
stessi dell'enunciato, cosi' il test si legge accanto alla richiesta):

1. ``aggiorna_righe_mercato_in_attesa``: una riga registrata a 0,58 che al
   calcolo successivo e' a 0,52 deve dire 0,52 (con ``sotto_soglia_ora = True``),
   tenere 0,58 nei campi ``*_prima`` e NON far nascere nessuna riga nuova.
2. ``compute_calibration_per_registrazione``: hit rate, Brier e gap letti alla
   PRIMA e all'ULTIMA registrazione, con le righe scritte prima dei campi
   ``*_prima`` contate e dichiarate (``senza_prima_registrazione``).
3. ``market_odds.multipla`` con la quota del bookmaker: margine mostrato solo
   se la quota e' stata inserita, nessun margine inventato quando il campo e'
   vuoto.

Nessuna chiamata API e nessun file del database toccato: qui si provano le
funzioni pure. Il giro completo (pulsante, HTTP finto, scrittura unica) e' in
``test_apptest_top_mix.py``.
"""

import math
import ast
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import market_odds as mo
import prediction_registry as pr


# ---------------------------------------------------------------------------
# fixture
# ---------------------------------------------------------------------------
ISTANTE = "2026-10-08T08:00:00Z"      # stesso istante delle righe fixture


def _lettura(prob_sicuro, prob_mercato, quota_mercato, prob_modello=None,
             accordo=False, sotto_soglia=False):
    """Una lettura per esito, nel formato di ``market_odds.letture_registrazione``."""
    return {"prob_sicuro": prob_sicuro, "prob_mercato": prob_mercato,
            "quota_mercato": quota_mercato, "prob_modello": prob_modello,
            "accordo_modello": accordo, "sotto_soglia_ora": sotto_soglia}


def _lettura_partita(match_id, per_esito, *, fonte="pinnacle", n_libri=22,
                     istante="2026-10-09T08:00:00Z", utcDate="2026-10-11T18:30:00Z"):
    """Il payload che ``calcola_righe_top_mix`` mette in ``righe["letture"]``."""
    return {"match_id": match_id, "per_esito": per_esito, "league": "Serie A",
            "home": "Torino", "away": "Como", "utcDate": utcDate,
            "mercato_fonte": fonte, "mercato_n_libri": n_libri,
            "quote_live_istante": istante}


def _riga_registrata(match_id=112, prob_val=58.0, prob_mercato=0.58, quota=1.72,
                     *, esito="⏳", mercato_standard="1", con_prima=True,
                     accordo=True, prob_modello=53.0,
                     istante="2026-10-08T08:00:00Z",
                     selector_version=pr.SELECTOR_VERSION_CURRENT):
    """Riga di mercato gia' nel Registro, nella forma che scrive ``app.py``.

    ``con_prima=False`` simula una riga scritta PRIMA che la regola dei campi
    ``*_prima`` esistesse: e' il caso che le statistiche devono dichiarare.
    """
    entry = {
        "match_id": match_id, "home": "Torino", "away": "Como",
        "campionato": "Serie A", "giornata": 7, "data": "11/10/2026 18:30",
        "pronostico_sicuro": "1 - Top Mix", "mercato_standard": mercato_standard,
        "top3": [], "prob_sicuro": prob_val, "risultati_attesi": "",
        "risultato_reale": None, "esito": esito, "tipo": "Top Mix",
        "stagione": "2026", "salvato_il": "08/10/2026 09:00", "origin": "top_mix",
        "selector_version": selector_version,
        "model_variant": pr.MODEL_VARIANT_CURRENT, "rank": 2,
        "kickoff_utc": "2026-10-11T18:30:00Z", "data_snapshot_sha": "sha",
        "calculation_id": "cid", "poisson": None, "elo": None,
        "elo_disponibile": False, "model_version": pr.MODEL_VERSION_CURRENT,
        "excluded_from_current_stats": False,
        pr.PROB_MERCATO_FIELD: prob_mercato, pr.QUOTA_MERCATO_FIELD: quota,
        pr.MERCATO_FONTE_FIELD: "pinnacle", pr.MERCATO_N_LIBRI_FIELD: 22,
        pr.ACCORDO_MODELLO_FIELD: accordo, pr.PROB_MODELLO_FIELD: prob_modello,
        pr.QUOTE_LIVE_ISTANTE_FIELD: istante,
    }
    if con_prima:
        entry[pr.PROB_MERCATO_PRIMA_FIELD] = prob_mercato
        entry[pr.QUOTA_MERCATO_PRIMA_FIELD] = quota
        entry[pr.PROB_MODELLO_PRIMA_FIELD] = prob_modello
        entry[pr.ACCORDO_MODELLO_PRIMA_FIELD] = accordo
        entry[pr.QUOTE_LIVE_ISTANTE_PRIMA_FIELD] = istante
    return entry


def _app():
    try:
        import app
    except Exception as e:                                  # pragma: no cover
        raise unittest.SkipTest(f"app.py non importabile ({e})")
    return app


# ---------------------------------------------------------------------------
# 1. Righe in attesa sotto soglia
# ---------------------------------------------------------------------------
class TestRinfrescoRigheInAttesa(unittest.TestCase):
    def test_caso_della_commessa_058_diventa_052(self):
        """Riga registrata a 0,58, calcolo successivo a 0,52: ultima = 0,52."""
        preds = [_riga_registrata()]
        letture = [_lettura_partita(112, {
            "1": _lettura(52.0, 0.52, 1.92, 51.0, sotto_soglia=True),
            "X": _lettura(28.0, 0.28, 3.60, sotto_soglia=True),
            "2": _lettura(20.0, 0.20, 5.00, sotto_soglia=True)})]
        aggiornate, azioni = pr.aggiorna_righe_mercato_in_attesa(
            preds, letture, salvato_il="10/10/2026 08:00")
        self.assertEqual(1, len(aggiornate), "nessuna riga nuova per una partita sotto soglia")
        riga = aggiornate[0]
        self.assertEqual(52.0, riga["prob_sicuro"], "l'ultima registrazione scende a 0,52")
        self.assertAlmostEqual(0.52, riga[pr.PROB_MERCATO_FIELD])
        self.assertEqual(1.92, riga[pr.QUOTA_MERCATO_FIELD])
        self.assertEqual(51.0, riga[pr.PROB_MODELLO_FIELD])
        self.assertTrue(riga[pr.SOTTO_SOGLIA_ORA_FIELD],
                        "il flag dice che oggi la partita NON sarebbe in tabella")
        # La PRIMA registrazione resta il fatto storico di quando e' entrata
        self.assertAlmostEqual(0.58, riga[pr.PROB_MERCATO_PRIMA_FIELD])
        self.assertEqual(1.72, riga[pr.QUOTA_MERCATO_PRIMA_FIELD])
        # Il timestamp segue la stessa regola dell'upsert
        self.assertEqual("10/10/2026 08:00", riga["salvato_il"])
        self.assertEqual("08/10/2026 09:00", riga["salvato_il_originario"])
        self.assertEqual({"aggiornata": 1, "sotto_soglia": 1}, azioni)
        # La scelta registrata non viene sostituita dall'argmax del momento
        self.assertEqual("1", riga["mercato_standard"])
        self.assertEqual("1 - Top Mix", riga["pronostico_sicuro"])
        self.assertEqual(2, riga["rank"])

    def test_il_contenuto_del_record_prima_di_tutto(self):
        """Solo i campi dichiarati cambiano: le altre chiavi restano identiche."""
        prima = _riga_registrata()
        letture = [_lettura_partita(112, {"1": _lettura(52.0, 0.52, 1.92, 53.0,
                                                        accordo=True, sotto_soglia=True)},
                                   istante=ISTANTE)]
        aggiornate, _ = pr.aggiorna_righe_mercato_in_attesa([prima], letture,
                                                            salvato_il="10/10/2026 08:00")
        dopo = aggiornate[0]
        self.assertEqual(set(prima), set(dopo) - {pr.SOTTO_SOGLIA_ORA_FIELD,
                                                 "salvato_il_originario"})
        toccati = {k for k in dopo if dopo.get(k) != prima.get(k)}
        self.assertEqual({"prob_sicuro", pr.PROB_MERCATO_FIELD, pr.QUOTA_MERCATO_FIELD,
                          "salvato_il", pr.SOTTO_SOGLIA_ORA_FIELD, "salvato_il_originario"},
                         toccati, "nessun campo reale viene toccato per sbaglio")

    def test_il_flag_compare_anche_senza_movimento(self):
        """Valori gia' allineati: il flag si scrive lo stesso (perche' e' nuovo).

        Una riga scritta prima che il flag esistesse non ce l'ha: se la lettura
        del turno e' sotto soglia ``sotto_soglia_ora`` deve comparire anche se
        probabilita' e quota non sono cambiate. Senza questa regola il flag
        arriverebbe solo alle righe che si muovono, e la conta sarebbe falsa.
        """
        sotto = _lettura(52.0, 0.52, 1.72, 53.0, accordo=True, sotto_soglia=True)
        preds = [_riga_registrata(prob_val=52.0, prob_mercato=0.52, quota=1.72)]
        aggiornate, azioni = pr.aggiorna_righe_mercato_in_attesa(
            preds, [_lettura_partita(112, {"1": sotto}, istante=ISTANTE)],
            salvato_il="10/10/2026 08:00")
        self.assertTrue(aggiornate[0][pr.SOTTO_SOGLIA_ORA_FIELD])
        self.assertEqual({"aggiornata": 1, "sotto_soglia": 1}, azioni)

    def test_gia_allineata_non_si_riscrive(self):
        """Doppio click a quote invariate: nessun tocco, nemmeno il timestamp."""
        preds = [_riga_registrata()]
        preds[0][pr.SOTTO_SOGLIA_ORA_FIELD] = False
        letture = [_lettura_partita(112, {"1": _lettura(58.0, 0.58, 1.72, 53.0, accordo=True)},
                                   istante=ISTANTE)]
        aggiornate, azioni = pr.aggiorna_righe_mercato_in_attesa(preds, letture,
                                                                 salvato_il="10/10/2026 08:00")
        self.assertEqual(preds[0], aggiornate[0], "nessun campo cambiato: nessuna riscrittura")
        self.assertEqual({"gia_allineata": 1}, azioni)

    def test_i_campi_comuni_della_lettura_seguono_il_turno(self):
        """Fonte, numero di libri e istante vengono riallineati alla lettura.

        Sono le chiavi che dicono QUANTO vale la probabilita' scritta: una riga
        aggiornata con la media di 12 libri che dichiara ancora "pinnacle" sarebbe
        una riga non piu' interpretabile.
        """
        preds = [_riga_registrata(prob_val=52.0, prob_mercato=0.52, quota=1.92)]
        letture = [_lettura_partita(112, {"1": _lettura(52.0, 0.52, 1.92, sotto_soglia=True)},
                                   fonte="media di 12 libri", n_libri=12,
                                   istante="2026-10-09T19:41:54Z")]
        aggiornate, azioni = pr.aggiorna_righe_mercato_in_attesa(preds, letture,
                                                                salvato_il="10/10/2026 08:00")
        riga = aggiornate[0]
        self.assertEqual("media di 12 libri", riga[pr.MERCATO_FONTE_FIELD])
        self.assertEqual(12, riga[pr.MERCATO_N_LIBRI_FIELD])
        self.assertEqual("2026-10-09T19:41:54Z", riga[pr.QUOTE_LIVE_ISTANTE_FIELD])
        self.assertEqual({"aggiornata": 1, "sotto_soglia": 1}, azioni)

    def test_sotto_soglia_si_dice_anche_se_gia_allineata(self):
        """Il conteggio del flag non dipende dalla scrittura avvenuta."""
        preds = [_riga_registrata(prob_val=52.0, prob_mercato=0.52, quota=1.92)]
        preds[0][pr.SOTTO_SOGLIA_ORA_FIELD] = True
        preds[0]["salvato_il"] = "09/10/2026 08:00"
        letture = [_lettura_partita(112, {"1": _lettura(52.0, 0.52, 1.92, 53.0, accordo=True,
                                                        sotto_soglia=True)}, istante=ISTANTE)]
        aggiornate, azioni = pr.aggiorna_righe_mercato_in_attesa(preds, letture,
                                                                salvato_il="10/10/2026 08:00")
        self.assertEqual({"gia_allineata": 1, "sotto_soglia": 1}, azioni)
        self.assertEqual("09/10/2026 08:00", aggiornate[0]["salvato_il"],
                         "una riga gia' allineata non viene ridata nemmeno nel timestamp")

    def test_sopra_soglia_si_aggiorna_come_prima(self):
        """Le partite che SALGONO restano aggiornate: non e' un canale solo per sotto soglia."""
        preds = [_riga_registrata()]
        preds[0][pr.SOTTO_SOGLIA_ORA_FIELD] = False
        letture = [_lettura_partita(112, {"1": _lettura(61.0, 0.61, 1.64, 58.0)})]
        aggiornate, azioni = pr.aggiorna_righe_mercato_in_attesa(preds, letture,
                                                                 salvato_il="10/10/2026 08:00")
        self.assertEqual(61.0, aggiornate[0]["prob_sicuro"])
        self.assertFalse(aggiornate[0][pr.SOTTO_SOGLIA_ORA_FIELD])
        self.assertEqual({"aggiornata": 1}, azioni)

    def test_si_legge_l_esito_registrato_non_l_argmax_del_momento(self):
        """La riga porta "X": si usa la lettura di "X", non quella dell'1."""
        preds = [_riga_registrata(mercato_standard="X", prob_val=30.0,
                                  prob_mercato=0.30, quota=3.30)]
        letture = [_lettura_partita(112, {"1": _lettura(52.0, 0.52, 1.92, sotto_soglia=True),
                                         "X": _lettura(31.0, 0.31, 3.20, sotto_soglia=True)})]
        aggiornate, azioni = pr.aggiorna_righe_mercato_in_attesa(preds, letture,
                                                                salvato_il="10/10/2026 08:00")
        self.assertEqual(31.0, aggiornate[0]["prob_sicuro"])
        self.assertAlmostEqual(0.31, aggiornate[0][pr.PROB_MERCATO_FIELD])
        self.assertEqual(3.20, aggiornate[0][pr.QUOTA_MERCATO_FIELD])
        self.assertEqual({"aggiornata": 1, "sotto_soglia": 1}, azioni)

    def test_righe_giudicate_non_toccate(self):
        """✅/❌ sono intoccabili: il rinfresco le conta e le lascia stare."""
        for esito in ("✅", "❌"):
            with self.subTest(esito=esito):
                preds = [_riga_registrata(esito=esito)]
                aggiornate, azioni = pr.aggiorna_righe_mercato_in_attesa(
                    preds, [_lettura_partita(112, {"1": _lettura(52.0, 0.52, 1.92)})],
                    salvato_il="10/10/2026 08:00")
                self.assertEqual(preds, aggiornate)
                self.assertEqual({"gia_graduata": 1, "senza_riga": 1}, azioni,
                                 "la lettura c'e' ma nessuna riga in attesa la usa")

    def test_partita_in_registro_senza_quote_in_questo_turno(self):
        """Nessuna lettura per la partita: la riga resta com'era (``senza_lettura``)."""
        preds = [_riga_registrata()]
        aggiornate, azioni = pr.aggiorna_righe_mercato_in_attesa(preds, [], salvato_il="x")
        self.assertEqual(preds, aggiornate)
        self.assertEqual({"senza_lettura": 1}, azioni)

    def test_lettura_senza_riga_non_crea_niente(self):
        """Partita con quote ma fuori dal Registro: NON entra, nessuna riga nuova.

        E' il vincolo della commessa: sotto soglia non si ammette niente, quindi
        il rinfresco puo' solo allineare righe che esistono gia'. ``senza_riga``
        serve a dire che il giro ha guardato anche queste partite.
        """
        letture = [_lettura_partita(999, {"1": _lettura(52.0, 0.52, 1.92, sotto_soglia=True)})]
        aggiornate, azioni = pr.aggiorna_righe_mercato_in_attesa([], letture, salvato_il="x")
        self.assertEqual([], aggiornate, "nessuna riga creata da una lettura sotto soglia")
        self.assertEqual({"senza_riga": 1}, azioni)

    def test_legge_solo_le_righe_di_mercato_visibili(self):
        """Ombra, Analisi Rapida, Billy e il modello storico restano fuori."""
        casi = {
            "ombra": {pr.OMBRA_FIELD: True, "origin": pr.ORIGIN_TOP_MIX_OMBRA,
                      "selector_version": pr.SELECTOR_VERSION_OMBRA_BY_FAMIGLIA[pr.OMBRA_FAMIGLIA_1X2]},
            "analisi_rapida": {"origin": pr.ORIGIN_ANALISI_RAPIDA,
                               "selector_version": pr.SELECTOR_VERSION_PRE_1X2},
            "billy": {"origin": pr.ORIGIN_BILLY,
                      "selector_version": pr.SELECTOR_VERSION_PRE_1X2},
            "modello_storico": {"selector_version": pr.SELECTOR_VERSION_PRE_1X2},
            "motore_legacy": {"model_variant": pr.MODEL_VARIANT_LEGACY},
        }
        for nome, extra in casi.items():
            with self.subTest(caso=nome):
                base = _riga_registrata()
                base.update(extra)
                aggiornate, azioni = pr.aggiorna_righe_mercato_in_attesa(
                    [base], [_lettura_partita(112, {"1": _lettura(52.0, 0.52, 1.92)})],
                    salvato_il="x")
                self.assertEqual([base], aggiornate, f"{nome}: non si tocca")
                self.assertNotIn("aggiornata", azioni)

    def test_parita_con_il_percorso_di_scrittura(self):
        """``letture_registrazione`` e il selettore scrivono gli STESSI numeri.

        E' la parita' che rende onesto il rinfresco: per l'esito che il selettore
        ammette, i campi del percorso di scrittura
        (``argomenti_registro_top_mix_mercato``) e quelli del rinfresco devono
        coincidere; altrimenti "cosa ho registrato" e "cosa dice il mercato
        adesso" sarebbero due misure diverse per costruzione, e la riga sopra
        soglia verrebbe riscritta a ogni click con un numero diverso.
        """
        app = _app()
        prob_mkt = {"1": 0.6123, "X": 0.2211, "2": 0.1666}
        odds = {"1": 1.62, "X": 4.5, "2": 6.1}
        modello = {"1": 0.58, "X": 0.24, "2": 0.18}
        scelta = app.seleziona_riga_top_mix_mercato(prob_mkt, odds, modello, fonte="pinnacle",
                                                    n_libri=22, home="Torino", away="Como")
        letture = mo.letture_registrazione(prob_mkt, odds, modello)
        self.assertIsNotNone(scelta)
        agg = letture[scelta["esito"]]
        self.assertEqual(scelta["prob_val"], agg["prob_sicuro"])
        self.assertAlmostEqual(round(scelta["prob_val"] / 100.0, 6), agg["prob_mercato"])
        self.assertEqual(scelta["quota"], agg["quota_mercato"])
        self.assertEqual(scelta["prob_modello_val"], agg["prob_modello"])
        self.assertEqual(scelta["accordo"], agg["accordo_modello"])
        self.assertFalse(agg["sotto_soglia_ora"], "il selettore ammette solo sopra soglia")
        # e la riga costruita dal payload del selettore porta gli stessi valori
        riga = dict(scelta, match_id=1, league="Serie A", giornata=7,
                    utcDate="2026-10-11T18:30:00Z", home="Torino", away="Como", rank=1)
        _args, kwargs = app.argomenti_registro_top_mix_mercato(riga)
        self.assertEqual(kwargs["prob_mercato"], agg[pr.PROB_MERCATO_FIELD])
        self.assertEqual(kwargs["quota_mercato"], agg[pr.QUOTA_MERCATO_FIELD])
        self.assertEqual(kwargs["prob_modello"], agg[pr.PROB_MODELLO_FIELD])
        self.assertEqual(bool(kwargs["accordo_modello"]), agg[pr.ACCORDO_MODELLO_FIELD])
        self.assertEqual(kwargs["prob_val"] if "prob_val" in kwargs else scelta["prob_val"],
                         agg["prob_sicuro"])
        self.assertFalse(kwargs[pr.SOTTO_SOGLIA_ORA_FIELD],
                         "la riga ammessa dal selettore non e' sotto soglia")

    def test_soglia_del_flag_e_quella_di_ammissione(self):
        """``sotto_soglia_ora`` usa la soglia del selettore, non un numero a parte."""
        sotto = mo.letture_registrazione({"1": 0.5499, "X": 0.30, "2": 0.15})
        sopra = mo.letture_registrazione({"1": 0.55, "X": 0.30, "2": 0.15})
        self.assertTrue(sotto["1"]["sotto_soglia_ora"])
        self.assertFalse(sopra["1"]["sotto_soglia_ora"])
        self.assertEqual(0.55, mo.SOGLIA_TOPMIX_MERCATO)

    def test_accordo_modello_stessa_regola_del_selettore(self):
        """Modello e mercato entrambi >= 0,55 sullo STESSO esito (soglia di accordo)."""
        lettura = mo.letture_registrazione({"1": 0.60, "X": 0.25, "2": 0.15},
                                          {"1": 1.66, "X": 4.0, "2": 6.6},
                                          {"1": 0.56, "X": 0.24, "2": 0.20})
        self.assertTrue(lettura["1"]["accordo_modello"])
        self.assertFalse(lettura["X"]["accordo_modello"], "non e' l'esito scelto dal modello")
        # mercato d'accordo sul numero ma il modello non arriva a 0,55: niente accordo
        lettura2 = mo.letture_registrazione({"1": 0.60, "X": 0.25, "2": 0.15},
                                           {"1": 1.66}, {"1": 0.50, "X": 0.30, "2": 0.20})
        self.assertFalse(lettura2["1"]["accordo_modello"])
        # e senza modello l'accordo non puo' essere vero: nessun segnale inventato
        lettura3 = mo.letture_registrazione({"1": 0.60, "X": 0.25, "2": 0.15}, {"1": 1.66})
        self.assertFalse(lettura3["1"]["accordo_modello"])
        self.assertIsNone(lettura3["1"]["prob_modello"])

    def test_esiti_senza_numero_non_compaiono(self):
        """Una probabilita' mancante non diventa 0 e non viene inventata."""
        letture = mo.letture_registrazione({"1": 0.6, "X": None, "2": float("nan")},
                                          {"1": None, "X": None, "2": 0.0})
        self.assertEqual(["1"], list(letture))
        self.assertIsNone(letture["1"]["quota_mercato"], "quota assente: None, non 0")
        self.assertIsNone(letture["1"]["prob_modello"], "modello assente: None, non 0")
        self.assertEqual({}, mo.letture_registrazione(None))
        self.assertEqual({}, mo.letture_registrazione({}))

    def test_payload_spuri_non_fanno_cadere_il_giro(self):
        """Payload malformati: si scartano con un conteggio, nessuna eccezione."""
        preds = [_riga_registrata()]
        letture = [None, "roba", {}, {"match_id": None}, {"match_id": 112},
                   _lettura_partita(112, {"1": _lettura(52.0, 0.52, 1.92, sotto_soglia=True)})]
        aggiornate, azioni = pr.aggiorna_righe_mercato_in_attesa(preds, letture, salvato_il="x")
        self.assertEqual(52.0, aggiornate[0]["prob_sicuro"], "l'unica lettura buona vince")
        self.assertEqual(4, azioni.get("senza_chiave"), "quattro payload senza match_id")
        self.assertEqual(1, azioni.get("aggiornata"))

    def test_esito_non_letto_si_dice(self):
        """Riga con esito "2" e lettura che ha solo "1": ``esito_non_letto``."""
        preds = [_riga_registrata(mercato_standard="2")]
        aggiornate, azioni = pr.aggiorna_righe_mercato_in_attesa(
            preds, [_lettura_partita(112, {"1": _lettura(52.0, 0.52, 1.92)})],
            salvato_il="x")
        self.assertEqual(preds, aggiornate)
        self.assertEqual({"esito_non_letto": 1}, azioni)

    def test_lista_di_partite_un_giro_solo(self):
        """Tre partite, tre sorte diverse: aggiornata / gia_allineata / senza_lettura."""
        preds = [_riga_registrata(match_id=1),
                 _riga_registrata(match_id=2, prob_val=61.0, prob_mercato=0.61, quota=1.64),
                 _riga_registrata(match_id=3)]
        preds[1][pr.SOTTO_SOGLIA_ORA_FIELD] = False
        letture = [_lettura_partita(1, {"1": _lettura(52.0, 0.52, 1.92, sotto_soglia=True)}),
                   _lettura_partita(2, {"1": _lettura(61.0, 0.61, 1.64, 53.0, accordo=True)},
                                   istante=ISTANTE)]
        aggiornate, azioni = pr.aggiorna_righe_mercato_in_attesa(preds, letture,
                                                                 salvato_il="10/10/2026 08:00")
        self.assertEqual({"aggiornata": 1, "gia_allineata": 1, "sotto_soglia": 1,
                          "senza_lettura": 1}, azioni)
        self.assertEqual(52.0, aggiornate[0]["prob_sicuro"])
        self.assertEqual(61.0, aggiornate[1]["prob_sicuro"])
        self.assertEqual(58.0, aggiornate[2]["prob_sicuro"], "la terza non era nelle letture")
        self.assertNotIn(pr.SOTTO_SOGLIA_ORA_FIELD, aggiornate[2],
                        "una riga mai letta non guadagna il flag")


# ---------------------------------------------------------------------------
# 2. Statistiche per registrazione
# ---------------------------------------------------------------------------
class TestStatistichePerRegistrazione(unittest.TestCase):
    def _due_righe_giudicate(self):
        """Due righe: una scesa sotto soglia, una rimasta ferma."""
        mossa = _riga_registrata(match_id=1, prob_val=58.0, prob_mercato=0.58, quota=1.72)
        mossa["esito"] = "✅"
        mossa["risultato_reale"] = "1-0"
        mossa[pr.PROB_MERCATO_FIELD] = 0.52
        mossa[pr.PROB_MODELLO_FIELD] = 51.0
        mossa[pr.SOTTO_SOGLIA_ORA_FIELD] = True
        ferma = _riga_registrata(match_id=2, prob_val=60.0, prob_mercato=0.60, quota=1.66)
        ferma["esito"] = "❌"
        ferma["risultato_reale"] = "0-1"
        return [mossa, ferma]

    def test_prima_e_ultima_usano_numeri_diversi(self):
        righe = self._due_righe_giudicate()
        prima = pr.compute_calibration_per_registrazione(righe, pr.REGISTRAZIONE_PRIMA)
        ultima = pr.compute_calibration_per_registrazione(righe, pr.REGISTRAZIONE_ULTIMA)
        self.assertEqual(2, prima["total"])
        self.assertEqual(2, prima["decise"])
        self.assertEqual(2, prima["con_probabilita"])
        # Hit rate identico per costruzione: la registrazione non cambia la scelta
        self.assertEqual(prima["hit_rate"], ultima["hit_rate"])
        self.assertAlmostEqual(50.0, prima["hit_rate"])
        # Brier e gap no: la probabilita' sotto i numeri e' un'altra
        self.assertAlmostEqual((0.42 ** 2 + 0.60 ** 2) / 2.0, prima["brier"], places=6)
        self.assertAlmostEqual((0.48 ** 2 + 0.60 ** 2) / 2.0, ultima["brier"], places=6)
        self.assertAlmostEqual(9.0, prima["gap"], places=1)
        self.assertAlmostEqual(6.0, ultima["gap"], places=1)
        self.assertEqual(1, ultima["sotto_soglia_ora"])
        self.assertEqual(0, ultima["ricostruite"])
        self.assertEqual("prima", prima["registrazione"])
        self.assertEqual(pr.FAMIGLIA_SELETTORE_MERCATO, prima["famiglia"])

    def test_righe_senza_campi_prima_vengono_contate_e_dichiarate(self):
        """Riga scritta prima dei campi ``*_prima``: si ricostruisce e si dichiara."""
        vecchia = _riga_registrata(match_id=3, prob_val=52.0, con_prima=False)
        vecchia["esito"] = "✅"
        vecchia["risultato_reale"] = "2-1"
        vecchia[pr.PROB_MERCATO_FIELD] = 0.52
        vecchia[pr.SOTTO_SOGLIA_ORA_FIELD] = True
        s = pr.compute_calibration_per_registrazione([vecchia], pr.REGISTRAZIONE_PRIMA)
        self.assertEqual(1, s["senza_prima_registrazione"],
                         "il numero che la UI deve dichiarare")
        self.assertEqual(1, s["ricostruite"], "ed entra nei tre numeri come ricostruzione")
        self.assertAlmostEqual(52.0, s["prob_media"], places=1)
        # per quella riga la misura "prima" COINCIDE con l'ultima: va detto
        u = pr.compute_calibration_per_registrazione([vecchia], pr.REGISTRAZIONE_ULTIMA)
        self.assertEqual(s["brier"], u["brier"])
        self.assertEqual(0, u["ricostruite"], "nell'ultima il fallback non e' una ricostruzione")
        self.assertEqual(1, u["senza_prima_registrazione"])

    def test_ha_prima_registrazione(self):
        con_scrittura = _riga_registrata()
        self.assertTrue(pr.ha_prima_registrazione(con_scrittura))
        ricostruita = _riga_registrata(con_prima=False)
        self.assertFalse(pr.ha_prima_registrazione(ricostruita))
        vecchia_vuota = _riga_registrata()
        vecchia_vuota[pr.PROB_MERCATO_PRIMA_FIELD] = None
        self.assertFalse(pr.ha_prima_registrazione(vecchia_vuota))
        self.assertFalse(pr.ha_prima_registrazione("roba"))

    def test_non_si_inventano_probabilita(self):
        """Riga giudicata senza nessun numero: fuori da Brier e gap, ma contata."""
        rotta = _riga_registrata(match_id=4)
        rotta["esito"] = "✅"
        rotta[pr.PROB_MERCATO_FIELD] = None
        rotta["prob_sicuro"] = None
        rotta[pr.PROB_MERCATO_PRIMA_FIELD] = None
        s = pr.compute_calibration_per_registrazione([rotta], pr.REGISTRAZIONE_PRIMA)
        self.assertEqual(1, s["decise"])
        self.assertEqual(0, s["con_probabilita"])
        self.assertIsNone(s["brier"])
        self.assertIsNone(s["hit_rate"])
        self.assertEqual(1, s["senza_probabilita"])
        self.assertEqual(0, s["ricostruite"],
                         "una riga senza nessun numero non e' una ricostruzione: non entra")

    def test_pandas_nan_non_diventa_un_numero(self):
        """La tabella passa i campi mancanti come NaN: nessun numero si inventa."""
        riga = _riga_registrata(match_id=5, con_prima=False)
        riga["esito"] = "✅"
        riga[pr.PROB_MERCATO_FIELD] = float("nan")
        riga["prob_sicuro"] = float("nan")
        self.assertTrue(math.isnan(riga["prob_sicuro"]))
        s = pr.compute_calibration_per_registrazione([riga], pr.REGISTRAZIONE_ULTIMA)
        self.assertEqual(0, s["con_probabilita"])
        self.assertIsNone(s["brier"])
        self.assertEqual(1, s["senza_prima_registrazione"], "NaN non e' una prima registrazione")

    def test_ombra_e_modello_storico_restanto_fuori(self):
        """Il filtro di famiglia e' dentro la funzione: niente ombra, niente modello."""
        ombra = _riga_registrata(match_id=6)
        ombra[pr.OMBRA_FIELD] = True
        ombra["esito"] = "✅"
        modello = _riga_registrata(match_id=7, con_prima=False)
        modello["selector_version"] = pr.SELECTOR_VERSION_PRE_1X2
        modello["esito"] = "❌"
        s = pr.compute_calibration_per_registrazione([ombra, modello], pr.REGISTRAZIONE_PRIMA)
        self.assertEqual(0, s["total"], "nessuna riga della famiglia mercato")
        self.assertIsNone(s["hit_rate"])
        # senza filtro di famiglia le due famiglie si sommano (e il Brier mescola)
        tutto = pr.compute_calibration_per_registrazione([ombra, modello],
                                                        pr.REGISTRAZIONE_PRIMA, famiglia=None)
        self.assertEqual(1, tutto["total"], "resta solo la riga non ombra")

    def test_il_filtro_di_famiglia_sta_nei_numeri_non_nella_data(self):
        """La famiglia viene dal ``selector_version``, non dalla data del record."""
        src = open(os.path.join(HERE, "prediction_registry.py"), encoding="utf-8").read()
        blocco = src[src.index("def compute_calibration_per_registrazione("):
                     src.index("def calibration_by_mercato(")]
        self.assertIn("_filtra_per_famiglia", blocco)
        self.assertNotIn("data", blocco)
        self.assertNotIn("CONFINE_FAMIGLIA", blocco)


# ---------------------------------------------------------------------------
# 3. Calcolatore di multipla: margine sulla quota del bookmaker
# ---------------------------------------------------------------------------
DUE = [{"partita": "A vs B", "esito": "1", "prob": 0.60, "quota": 1.70},
       {"partita": "C vs D", "esito": "2", "prob": 0.50, "quota": 1.90}]


class TestMargineMultipla(unittest.TestCase):
    def test_margine_quando_la_quota_c_e(self):
        out = mo.multipla(DUE, quota_bookmaker=2.85)
        self.assertAlmostEqual(0.30, out["probabilita_combinata"], places=6)
        self.assertAlmostEqual(2.85 * 0.30 - 1.0, out["margine"], places=10)
        self.assertEqual(2.85, out["quota_bookmaker"])
        self.assertNotIn("errore_quota_bookmaker", out)
        self.assertAlmostEqual(1.0 / 0.30, out["quota_equa"], places=6)

    def test_nessun_margine_se_il_campo_e_vuoto(self):
        out = mo.multipla(DUE)
        self.assertTrue(out["ok"])
        self.assertIsNone(out["margine"], "campo vuoto: nessun margine, nessun numero falso")
        self.assertIsNone(out["quota_bookmaker"])
        self.assertNotIn("errore_quota_bookmaker", out)
        # la quota equa resta: e' l'unica cosa che si puo' dire senza prezzo altrui
        self.assertAlmostEqual(1.0 / 0.30, out["quota_equa"], places=6)

    def test_quota_non_valida_si_dice_e_non_inventa(self):
        for q in (0, 0.0, -1.0, 1.0, "due", float("nan"),
                  float("inf"), True):
            with self.subTest(quota=q):
                out = mo.multipla(DUE, quota_bookmaker=q)
                self.assertTrue(out["ok"], "la multipla resta valida")
                self.assertIsNone(out["margine"], "il margine no")
                self.assertIn("errore_quota_bookmaker", out)

    def test_prodotto_delle_quote_del_file_non_e_piu_il_confronto(self):
        """``edge`` esiste ancora per chi lo usa, ma NON e' il margine dell'offerta.

        E' il punto della commessa: ``edge`` e' il margine composto della fonte
        delle quote, sempre negativo, e non dice niente su cio' che offre chi
        ospiera' la giocata.
        """
        senza = mo.multipla(DUE)
        con_quota = mo.multipla(DUE, quota_bookmaker=3.30)
        self.assertAlmostEqual(1.70 * 1.90, senza["quota_offerta"], places=6)
        self.assertLess(senza["edge"], 0.0, "il vecchio confronto: negativo per costruzione")
        self.assertAlmostEqual(3.30 * 0.30 - 1.0, con_quota["margine"], places=10)
        self.assertNotAlmostEqual(con_quota["margine"], senza["edge"], places=3)

    def test_la_selezione_invalida_non_cambia(self):
        self.assertFalse(mo.multipla([])["ok"])
        self.assertFalse(mo.multipla([], quota_bookmaker=2.0)["ok"])
        self.assertTrue(mo.multipla(DUE[:1], quota_bookmaker=2.0)["ok"],
                        "una riga sola basta: MASSIMO 5, MINIMO 1")
        self.assertFalse(mo.multipla(DUE * 3, quota_bookmaker=2.0)["ok"])

    def test_margine_quota_formula_separata(self):
        self.assertAlmostEqual(2.85 * 0.30 - 1.0, mo.margine_quota(2.85, 0.30), places=10)
        self.assertAlmostEqual(-0.145, mo.margine_quota(2.85, 0.30), places=3)
        self.assertEqual(0.0, mo.margine_quota(10.0, 0.10))
        for q, p in ((None, 0.3), (2.85, None), (1.0, 0.3), (2.85, 1.5),
                     ("2,85", 0.3), (2.85, float("nan")), (float("inf"), 0.3),
                     (True, 0.3)):
            with self.subTest(quota=q, prob=p):
                self.assertIsNone(mo.margine_quota(q, p))


class TestRifinitureNelCodiceDellApp(unittest.TestCase):
    """Le guardie di testo sui punti 1 e 3: il contratto della UI non scivola via."""

    @classmethod
    def setUpClass(cls):
        cls.src = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
        cls.tab2 = cls.src[cls.src.index("with tab2:"):cls.src.index("with tab3:")]
        cls.calc = cls.src[cls.src.index("def calcolatore_multipla("):
                           cls.src.index("# Nomi dei due modelli")]

    def test_il_percorso_di_scrittura_dichiara_il_flag(self):
        """``argomenti_registro_top_mix_mercato`` passa il flag (False in ammissione)."""
        app = _app()
        riga = {"league": "Serie A", "giornata": 5, "home": "Inter", "away": "Roma",
                "match_id": 4242, "utcDate": "2026-10-10T13:00:00Z",
                "market": "Vittoria Inter", "mercato_standard": "1",
                "prob": 0.617, "prob_val": 61.7, "quota": 1.62,
                "prob_modello_val": 58.0, "accordo": True,
                "fonte": "pinnacle", "n_libri": 22,
                "quote_live_istante": "2026-10-09T08:17:00Z", "rank": 1}
        args, kwargs = app.argomenti_registro_top_mix_mercato(riga)
        self.assertFalse(kwargs[pr.SOTTO_SOGLIA_ORA_FIELD])
        entry = app.build_prediction_entry(*args, **kwargs, snapshot_sha="abc")
        self.assertFalse(entry[pr.SOTTO_SOGLIA_ORA_FIELD])
        import inspect
        for fn in (app.save_prediction_entry, app.build_prediction_entry):
            inspect.signature(fn).bind(*args, **kwargs)   # TypeError se non combaciano
        # una riga declassata che viene riscritta porta il flag True
        _a2, k2 = app.argomenti_registro_top_mix_mercato(dict(riga, sotto_soglia_ora=True))
        self.assertTrue(app.build_prediction_entry(*_a2, **k2, snapshot_sha="abc")[
            pr.SOTTO_SOGLIA_ORA_FIELD])

    def test_il_flag_non_compare_sulle_righe_del_modello(self):
        app = _app()
        riga = {"league": "Serie A", "giornata": 5, "home": "Inter", "away": "Roma",
                "match_id": 4242, "utcDate": "2026-10-10T13:00:00Z",
                "market": "Vittoria Inter", "prob": 0.6123, "prob_val": 61.2,
                "poisson": 58.0, "elo": 62.3, "elo_disponibile": True, "rank": 3}
        args, kwargs = app.argomenti_registro_top_mix(riga)
        entry = app.build_prediction_entry(*args, **kwargs, snapshot_sha="abc")
        self.assertNotIn(pr.SOTTO_SOGLIA_ORA_FIELD, entry,
                         "solo le righe di mercato possono portare il flag")

    def test_tab2_una_sola_scrittura_dopo_entrambe_le_passate(self):
        self.assertLess(self.tab2.index("upsert_prediction_entries("),
                        self.tab2.index("aggiorna_righe_mercato_in_attesa("),
                        "il rinfresco parte dal registro GIA' aggiornato dall'ammissione")
        self.assertLess(self.tab2.index("aggiorna_righe_mercato_in_attesa("),
                        self.tab2.index("save_predictions(preds)"),
                        "e la scrittura e' una sola, dopo entrambe le passate")
        self.assertEqual(1, self.tab2.count("save_predictions(preds)"))
        self.assertIn("letture, _scartate_letture = righe_non_iniziate(letture)", self.tab2)

    def test_il_calcolatore_espone_il_campo_opzionale(self):
        self.assertIn("Quota offerta dal tuo bookmaker", self.calc)
        self.assertIn("value=None", self.calc, "il campo deve poter restare vuoto")
        self.assertIn('key="multipla_quota_bookmaker"', self.calc)
        self.assertIn("quota_bookmaker=quota_bookmaker", self.calc)
        self.assertIn('metric("Margine sulla tua quota"', self.calc)
        # le due metriche che non dicevano niente sono sparite
        self.assertNotIn('metric("Edge"', self.calc)
        self.assertNotIn('metric("Quota offerta"', self.calc)

    def test_le_statistiche_per_registrazione_sono_in_pagina(self):
        blocco = self.src[self.src.index("def _mostra_statistiche_registrazione("):
                          self.src.index("def _mostra_registro_mercato(")]
        self.assertIn("misura principale", blocco)
        self.assertIn("REGISTRAZIONE_PRIMA", blocco)
        self.assertIn("REGISTRAZIONE_ULTIMA", blocco)
        self.assertIn("senza_prima_registrazione", blocco)
        self.assertIn("sotto_soglia_ora", blocco)
        self.assertIn("hit rate", blocco.lower())
        self.assertIn("_mostra_statistiche_registrazione(all_records)", self.src)


class TestLayoutArchivioModelloStorico(unittest.TestCase):
    """Punto 5 (layout): l'archivio del modello storico sta in un riquadro chiuso.

    Guardia sull'albero sintattico di ``app.py``, non su una fetta di testo:
    "dentro il riquadro" vuol dire che l'elemento sta nel corpo del
    ``with st.expander(...)``, quindi un reindent, un commento di troppo o una
    seconda chiamata non possono far credere il contrario. Il comportamento vivo
    (riquadro chiuso, niente tabelle vuote in pagina) e' provato da
    ``test_apptest_top_mix.py::test_b_archivio_modello_storico_in_riquadro``.
    """

    TITOLO = "Modello storico (archivio fino al"

    @classmethod
    def setUpClass(cls):
        cls.src = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
        cls.albero = ast.parse(cls.src)
        cls.tab5 = cls.src[cls.src.index("with tab5:"):]

    # ------------------------------------------------------------------ aiuti
    def _riquadro(self):
        for nodo in ast.walk(self.albero):
            if isinstance(nodo, ast.With) and nodo.items:
                testo = ast.get_source_segment(self.src, nodo.items[0].context_expr) or ""
                if self.TITOLO in testo:
                    return nodo
        return None

    @staticmethod
    def _conteggio(nodo, nome):
        n = 0
        for c in ast.walk(nodo):
            if not isinstance(c, ast.Call):
                continue
            f = c.func
            if (isinstance(f, ast.Name) and f.id == nome) or \
               (isinstance(f, ast.Attribute) and f.attr == nome):
                n += 1
        return n

    # ------------------------------------------------------------------- prova
    def test_il_riquadro_c_e_ed_e_chiuso_per_default(self):
        riq = self._riquadro()
        self.assertIsNotNone(riq, "l'archivio del modello storico deve stare in uno st.expander")
        chiamata = riq.items[0].context_expr
        testo = ast.get_source_segment(self.src, chiamata)
        self.assertIn(self.TITOLO, testo)
        self.assertIn("CONFINE_FAMIGLIA_MERCATO", testo,
                      "la data del titolo e' quella del confine delle famiglie, non una copia")
        self.assertEqual([], [k.arg for k in chiamata.keywords],
                          "nessun parametro di apertura: st.expander e' chiuso per default")
        # uno solo: due riquadri con lo stesso titolo vorrebbe dire tabelle duplicate
        titoli = [ast.get_source_segment(self.src, n.items[0].context_expr) or ""
                  for n in ast.walk(self.albero) if isinstance(n, ast.With) and n.items]
        self.assertEqual(1, sum(1 for t in titoli if self.TITOLO in t),
                         f"un solo riquadro per l'archivio, trovati: {titoli}")

    def test_dentro_il_riquadro_ci_sta_tutto_il_modello_storico(self):
        riq = self._riquadro()
        self.assertIsNotNone(riq)
        self.assertEqual(2, self._conteggio(riq, "_mostra_registro_modello"),
                         "le DUE tabelle dei motori stanno nel riquadro, non in pagina")
        self.assertEqual(2, self._conteggio(riq, "_mostra_blocco_modello"),
                         "e ci stanno anche i due blocchi di statistiche, che contano "
                         "le stesse righe delle tabelle")
        # due chiamate perche' due sono i rami: una per motore se i motori sono
        # piu' d'uno, un'unica affidabilita' di famiglia se nel filtro resta un
        # solo motore. In nessun caso si chiama fuori dal riquadro.
        self.assertEqual(2, self._conteggio(riq, "_mostra_affidabilita"))
        self.assertEqual(2, self.tab5.count("_mostra_affidabilita("),
                         "l'affidabilita' del modello si chiama solo nei due rami qui "
                         "dentro: nessun blocco di affidabilita' resta in apertura")
        self.assertEqual(1, self._conteggio(riq, "_metriche_famiglia_registro"),
                         "l'intestazione di famiglia con i cinque numeri e' del riquadro")
        self.assertIn("schede_vecchie", ast.get_source_segment(self.src, riq),
                      "il dettaglio 'scheda vecchia' resta dichiarato, dentro il riquadro")
        self.assertIn("FAMIGLIA_SELETTORE_MODELLO", ast.get_source_segment(self.src, riq))

    def test_fuori_dal_riquadro_restano_mercato_e_ombra(self):
        riq = self._riquadro()
        self.assertIsNotNone(riq)
        corpo = ast.get_source_segment(self.src, riq)
        fuori = self.tab5_fuori_riquadro()
        for nome in ("_mostra_registro_mercato", "_mostra_statistiche_registrazione",
                     "load_ombra_rows"):
            self.assertEqual(0, self._conteggio(riq, nome),
                             f"{nome} non deve finire nel riquadro chiuso")
            self.assertIn(nome + "(", fuori, f"{nome} deve restare in apertura")
        self.assertIn("FAMIGLIA_SELETTORE_MERCATO", fuori.split("st.expander", 1)[0],
                      "la famiglia mercato si renderizza PRIMA del riquadro: e' cio' che "
                      "si vede aprendo il tab")

    def test_le_tabelle_dei_motori_incrociano_la_famiglia(self):
        """Le due tabelle sono l'archivio: variante E famiglia di selettore.

        Le righe del mercato portano ``model_variant = current`` perche' le scrive
        lo stesso codice di scrittura: tagliare solo sulla variante le avrebbe
        messe nell'archivio del modello, smentendo il titolo del riquadro e
        sballando i totali rispetto all'intestazione di famiglia.
        """
        self.assertIn('maschera_attuale = maschera_attuale & maschera_modello', self.tab5)
        self.assertIn('maschera_legacy = maschera_legacy & maschera_modello', self.tab5)
        self.assertIn('resto_records = df_display[maschera_resto].to_dict("records")', self.tab5)
        self.assertIn('resto = df_display[maschera_resto]', self.tab5)
        # la terza tabella di controllo esiste solo se ha righe: non e' mai vuota
        i = self.tab5.index("resto = df_display[maschera_resto]")
        self.assertIn("if len(resto):", self.tab5[i:i + 200])
        # e la tabella di controllo sta FUORI dal riquadro: un'anomalia dei dati
        # nascosta in un box chiuso non la vede nessuno
        riq = self._riquadro()
        self.assertEqual(0, self._conteggio(riq, "dataframe") if riq else 0,
                         "nel riquadro non si costruisce nessuna tabella all'infuori "
                         "delle due dei motori (quella di controllo sta fuori)")

    def tab5_fuori_riquadro(self):
        """Il tab5 SENZA il corpo del riquadro: cio' che si vede in apertura."""
        corpo = ast.get_source_segment(self.src, self._riquadro())
        return self.tab5.replace(corpo, "", 1)

    def test_il_loop_misto_non_c_e_piu_e_la_didascalia_descrive_il_layout(self):
        for token in ("for _fam, _etichetta, _nota in (", "parti_variante_modello =",
                      "righe_famiglia_modello ="):
            self.assertFalse(token in self.src,
                             "e' tornato il vecchio giro misto sulle due famiglie: "
                             f"cerca {token!r} in app.py")
        # la didascalia che parlava di "due tabelle" descrive il layout attuale
        self.assertFalse("titolo delle due tabelle)" in self.src,
                         "la didascalia parla ancora del vecchio layout a due tabelle")
        i = self.src.index('"**Come sono state scritte le righe**')
        didascalia = self.src[i:self.src.index("        )\n", i)]
        self.assertIn("riquadro chiuso", didascalia)
        self.assertIn("archivio del modello storico", didascalia)
        for etichetta in ("MODEL_LABEL_CURRENT", "MODEL_LABEL_PRE_FIX", "MODEL_LABEL_LEGACY"):
            self.assertIn(etichetta, didascalia, "le tre etichette della scheda restano")

if __name__ == "__main__":
    unittest.main(verbosity=2)
