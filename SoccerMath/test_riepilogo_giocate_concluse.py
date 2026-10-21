"""`app.riepilogo_giocate_concluse`: i quattro numeri dei riquadri del Registro.

I riquadri numerici di «Com'è andata» (concluse, riuscite, percentuale di
riuscite, attese) non devono avere una regola propria: sono le STESSE righe e
gli STESSI filtri delle due sintesi in parole, che fino a oggi contavano da sole
(``_sintesi_registro_mercato`` per la famiglia mercato, ``sintesi_gol_mercato``
per la famiglia gol). Qui si prova la funzione pura che li conta, e si verifica
che le due sintesi dicano gli stessi numeri.

Formato di ``prob_sicuro`` nel Registro: PERCENTUALE (es. 70.0), come la scrive
``market_odds`` (``round(p * 100, 1)``) e come confermano le righe dello
snapshot ``audit/results/replay_sym_offline/registro_offline_fuso.json``.
Le «attese» leggono pero' ``prob_di_registrazione(..., REGISTRAZIONE_PRIMA)``,
cioe' ``prob_mercato_prima`` e — dove il campo manca, come in quello snapshot —
il ripiego dichiarato su ``prob_sicuro``: la stessa strada delle due sintesi.

Caso a mano richiesto: 3 giocate concluse, 2 riuscite, probabilita' 0,60 0,70
0,80 -> riuscite 67%, attese 70%, scarto -3 punti.

Esecuzione:
    python -m pytest SoccerMath/test_riepilogo_giocate_concluse.py -v
"""
from __future__ import annotations

import logging
import os
import sys
import unittest

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.dirname(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

logging.getLogger("streamlit").setLevel(logging.ERROR)

import app  # noqa: E402
import prediction_registry as pr  # noqa: E402


def _giocata(esito, probabilita, prob_mercato_prima="assente"):
    """Una riga del Registro: esito ✅/❌/⏳, ``prob_sicuro`` in PERCENTUALE.

    ``prob_mercato_prima`` sta a ``"assente"`` quando la riga non ha il campo
    (il caso dello snapshot nel repo): le attese ripiegano allora su
    ``prob_sicuro``.
    """
    riga = {"esito": esito,
            "mercato_standard": "1",
            "prob_sicuro": probabilita * 100.0,
            "selector_version": pr.SELECTOR_VERSION_CURRENT}
    if prob_mercato_prima != "assente":
        riga[pr.PROB_MERCATO_PRIMA_FIELD] = prob_mercato_prima
    return riga


class TestCasoAMano(unittest.TestCase):
    """3 concluse, 2 riuscite, prob 0,60 0,70 0,80."""

    def setUp(self):
        self.righe = [_giocata("✅", 0.60), _giocata("✅", 0.70), _giocata("❌", 0.80)]
        self.riepilogo = app.riepilogo_giocate_concluse(self.righe)

    def test_conteggi(self):
        self.assertEqual(3, self.riepilogo["concluse"])
        self.assertEqual(2, self.riepilogo["riuscite"])

    def test_percentuale_riuscite_67(self):
        # 2/3 = 66,67% -> 67, la stessa percentuale intera delle sintesi.
        self.assertEqual(67, self.riepilogo["percentuale_riuscite"])

    def test_attese_70(self):
        # media di 0,60 0,70 0,80 = 0,70 -> 70%.
        self.assertEqual(70, self.riepilogo["attese"])

    def test_scarto_meno_tre_punti(self):
        self.assertEqual(-3, self.riepilogo["scarto"])
        self.assertEqual(self.riepilogo["percentuale_riuscite"] - self.riepilogo["attese"],
                         self.riepilogo["scarto"],
                         "scarto = riuscite - attese, in punti percentuali")

    def test_nessuna_riga_fuori_dalla_media(self):
        self.assertEqual(0, self.riepilogo["senza_probabilita"])


class TestStessiFiltriDelleSintesi(unittest.TestCase):
    """Le righe che non sono concluse non entrano in nessun numero."""

    def test_le_righe_in_attesa_restano_fuori(self):
        righe = [_giocata("✅", 0.60), _giocata("✅", 0.70), _giocata("❌", 0.80),
                 _giocata("⏳", 0.90), _giocata("", 0.99), {"esito": None}]
        riepilogo = app.riepilogo_giocate_concluse(righe)
        self.assertEqual(3, riepilogo["concluse"],
                         "solo ✅/❌ sono concluse: ⏳ e le righe vuote restano fuori")
        self.assertEqual(70, riepilogo["attese"],
                         "la riga in attesa al 90% non sposta la media")

    def test_prob_mercato_prima_vince_su_prob_sicuro(self):
        # Con la PRIMA registrazione scritta, le attese leggono quella (0,55),
        # non il valore attuale (0,80): e' la regola di prob_di_registrazione.
        riga = _giocata("✅", 0.80, prob_mercato_prima=0.55)
        riepilogo = app.riepilogo_giocate_concluse([riga])
        self.assertEqual(55, riepilogo["attese"])

    def test_riga_senza_probabilita_fuori_dalla_media_ma_conteggiata(self):
        righe = [_giocata("✅", 0.60), _giocata("✅", 0.70),
                 {"esito": "❌", "prob_sicuro": None}]
        riepilogo = app.riepilogo_giocate_concluse(righe)
        self.assertEqual(3, riepilogo["concluse"],
                         "una riga giudicata resta una giocata conclusa")
        self.assertEqual(67, riepilogo["percentuale_riuscite"])
        self.assertEqual(65, riepilogo["attese"], "media solo delle leggibili: 60 e 70")
        self.assertEqual(1, riepilogo["senza_probabilita"])
        self.assertEqual(2, riepilogo["scarto"])

    def test_nessuna_probabilita_leggibile_attese_none(self):
        riepilogo = app.riepilogo_giocate_concluse([{"esito": "✅", "prob_sicuro": None},
                                                    {"esito": "❌"}])
        self.assertEqual(2, riepilogo["concluse"])
        self.assertIsNone(riepilogo["attese"], "nessun numero inventato")
        self.assertIsNone(riepilogo["scarto"])
        self.assertEqual(2, riepilogo["senza_probabilita"])

    def test_nessuna_conclusa_zero_e_none(self):
        for vuoto in ([], None, [_giocata("⏳", 0.7)]):
            with self.subTest(vuoto=vuoto):
                riepilogo = app.riepilogo_giocate_concluse(vuoto)
                self.assertEqual({"concluse": 0, "riuscite": 0,
                                  "percentuale_riuscite": None, "attese": None,
                                  "scarto": None, "senza_probabilita": 0}, riepilogo)

    def test_accetta_anche_il_dataframe(self):
        df = pd.DataFrame([_giocata("✅", 0.60), _giocata("✅", 0.70),
                           _giocata("❌", 0.80), _giocata("⏳", 0.90)])
        riepilogo = app.riepilogo_giocate_concluse(df)
        self.assertEqual(3, riepilogo["concluse"])
        self.assertEqual(67, riepilogo["percentuale_riuscite"])
        self.assertEqual(70, riepilogo["attese"])


class TestLeDueSintesiDiconoGliStessiNumeri(unittest.TestCase):
    """Nessuna regola nuova: le sintesi in parole leggono la stessa funzione."""

    def test_sintesi_gol_mercato(self):
        righe = [_giocata("✅", 0.60), _giocata("✅", 0.70), _giocata("❌", 0.80)]
        frase = app.sintesi_gol_mercato(righe)
        self.assertEqual("Gol: finora 3 giocate concluse, 2 riuscite (67%). Quote: 70%.",
                         frase)

    def test_sintesi_gol_mercato_senza_concluse(self):
        self.assertEqual("Gol: nessuna giocata conclusa finora.",
                         app.sintesi_gol_mercato([_giocata("⏳", 0.7)]))

    def test_sintesi_registro_mercato_riga1(self):
        df = pd.DataFrame([_giocata("✅", 0.60), _giocata("✅", 0.70),
                           _giocata("❌", 0.80)])
        riga1, _riga2 = app._sintesi_registro_mercato(df)
        self.assertEqual("Finora 3 giocate concluse, 2 riuscite (67%). "
                         "Quote: 70%. Modello: n/d.", riga1)
        riepilogo = app.riepilogo_giocate_concluse(df)
        self.assertIn(f"({riepilogo['percentuale_riuscite']}%)", riga1)
        self.assertIn(f"Quote: {riepilogo['attese']}%", riga1)

    def test_sintesi_registro_mercato_senza_concluse(self):
        df = pd.DataFrame([_giocata("⏳", 0.7)])
        self.assertEqual((None, None), app._sintesi_registro_mercato(df))

    def test_stessa_media_sulle_due_famiglie(self):
        """Le stesse righe, contate dalle due sintesi: numeri identici."""
        righe = [_giocata("✅", 0.62), _giocata("❌", 0.71), _giocata("✅", 0.58),
                 _giocata("❌", 0.66)]
        riepilogo = app.riepilogo_giocate_concluse(righe)
        riga1, _ = app._sintesi_registro_mercato(pd.DataFrame(righe))
        frase = app.sintesi_gol_mercato(righe)
        atteso = (f"{riepilogo['concluse']} giocate concluse, "
                  f"{riepilogo['riuscite']} riuscite "
                  f"({riepilogo['percentuale_riuscite']}%)")
        self.assertIn(atteso, riga1)
        self.assertIn(atteso, frase)
        self.assertIn(f"Quote: {riepilogo['attese']}%", riga1)
        self.assertIn(f"Quote: {riepilogo['attese']}%", frase)



# ---------------------------------------------------------------------------
# I riquadri a schermo: le etichette, i valori, il delta e il suggerimento
# ---------------------------------------------------------------------------

def _riga_pronostico(esito="1", solo_ou=False, gol="Over", prob=0.66):
    """Una riga della tabella dei Pronostici, come la lascia il selettore.

    ``solo_ou`` marca le partite senza 1X2 (in tabella «Pronostico» porta «—»);
    ``gol`` e' la scelta dei ``totals`` (``None`` quando la partita non ne ha
    una) — la stessa che ``celle_totals`` scrive nella colonna «Gol».
    """
    riga = {"esito": esito, "solo_ou": solo_ou, "prob": prob, "prob_val": prob * 100}
    if gol is not None:
        riga["totals"] = {"pronostico": gol, "p_over": 0.66, "p_under": 0.34}
    else:
        riga["totals"] = {"pronostico": "", "p_over": 0.55, "p_under": 0.45}
    return riga


class TestContaPronostici(unittest.TestCase):
    """Quante righe della tabella hanno un 1X2 e quante un gol."""

    def test_riga_con_entrambi_i_pronostici(self):
        self.assertEqual({"1x2": 1, "gol": 1},
                         app.conta_pronostici([_riga_pronostico()]))

    def test_riga_solo_gol_non_conta_come_1x2(self):
        conteggi = app.conta_pronostici([_riga_pronostico(esito="—", solo_ou=True)])
        self.assertEqual(0, conteggi["1x2"], "una riga solo gol non ha un 1X2")
        self.assertEqual(1, conteggi["gol"])

    def test_riga_senza_pronostico_gol(self):
        riga = _riga_pronostico(gol=None)
        self.assertEqual({"1x2": 1, "gol": 0}, app.conta_pronostici([riga]))

    def test_esito_non_leggibile_non_conta(self):
        conteggi = app.conta_pronostici([_riga_pronostico(esito=""), _riga_pronostico(esito=None)])
        self.assertEqual(0, conteggi["1x2"])

    def test_lista_vuota_e_dataframe(self):
        self.assertEqual({"1x2": 0, "gol": 0}, app.conta_pronostici([]))
        self.assertEqual({"1x2": 0, "gol": 0}, app.conta_pronostici(None))
        df = pd.DataFrame([_riga_pronostico(), _riga_pronostico(esito="X")])
        self.assertEqual({"1x2": 2, "gol": 2}, app.conta_pronostici(df))

    def test_una_riga_non_dizionario_non_rompe(self):
        self.assertEqual({"1x2": 1, "gol": 0},
                         app.conta_pronostici([None, _riga_pronostico(gol=None)]))


class TestRiquadroDelRegistro(unittest.TestCase):
    """Valore, delta e suggerimento di un riquadro del Registro."""

    def test_caso_a_mano(self):
        riquadro = app.riquadro_registro(app.riepilogo_giocate_concluse(
            [_giocata("✅", 0.60), _giocata("✅", 0.70), _giocata("❌", 0.80)]))
        self.assertEqual("67%", riquadro["value"])
        self.assertEqual("-3 punti sulle attese", riquadro["delta"],
                         "sotto le attese il segno e' meno")
        self.assertIn("2 riuscite su 3 concluse", riquadro["help"])
        self.assertIn("media delle probabilità di mercato della prima registrazione",
                      riquadro["help"])

    def test_delta_con_il_segno_quando_si_va_meglio(self):
        riquadro = app.riquadro_registro(app.riepilogo_giocate_concluse(
            [_giocata("✅", 0.60), _giocata("✅", 0.80)]))
        self.assertEqual("100%", riquadro["value"])
        self.assertEqual("+30 punti sulle attese", riquadro["delta"])

    def test_zero_concluse_nessun_numero_e_nessun_delta(self):
        riquadro = app.riquadro_registro(app.riepilogo_giocate_concluse(
            [_giocata("⏳", 0.70)]))
        self.assertEqual("n/d", riquadro["value"])
        self.assertIsNone(riquadro["delta"])
        self.assertIn("Nessuna giocata conclusa finora", riquadro["help"])

    def test_senza_probabilita_leggibile_niente_scarto(self):
        riga = {"esito": "✅", "mercato_standard": "1",
                "selector_version": pr.SELECTOR_VERSION_CURRENT}
        riquadro = app.riquadro_registro(app.riepilogo_giocate_concluse([riga]))
        self.assertEqual("100%", riquadro["value"])
        self.assertIsNone(riquadro["delta"], "senza attese non c'e' uno scarto")
        self.assertIn("non c'è uno scarto da mostrare", riquadro["help"])

    def test_le_concluse_fuori_dalla_media_si_dichiarano(self):
        senza = {"esito": "❌", "mercato_standard": "1",
                 "selector_version": pr.SELECTOR_VERSION_CURRENT}
        riquadro = app.riquadro_registro(app.riepilogo_giocate_concluse(
            [_giocata("✅", 0.60), senza]))
        self.assertEqual("50%", riquadro["value"])
        self.assertEqual("-10 punti sulle attese", riquadro["delta"])
        self.assertIn("1 concluse senza probabilità leggibile", riquadro["help"])

    def test_nessun_numero_ripetuto_per_estensione(self):
        """Il valore e il delta non ripetono il conteggio del suggerimento."""
        riquadro = app.riquadro_registro(app.riepilogo_giocate_concluse(
            [_giocata("✅", 0.60), _giocata("❌", 0.80)]))
        self.assertNotIn("2", riquadro["value"])
        self.assertNotIn("concluse", riquadro["delta"])
        self.assertIn("1 riuscite su 2 concluse", riquadro["help"])


class TestRiquadriGiocate(unittest.TestCase):
    """L'ordine e le etichette dei quattro riquadri sono UNO solo."""

    def test_ordine_ed_etichette_con_la_tabella(self):
        riquadri = app.riquadri_giocate([_riga_pronostico()],
                                        [_giocata("✅", 0.60)], [])
        self.assertEqual(["Pronostici 1X2", "Pronostici gol",
                          "Registro 1X2", "Registro gol"],
                         [r["label"] for r in riquadri])
        self.assertEqual(app.ETICHETTE_RIQUADRI_GIOCATE,
                         tuple(r["label"] for r in riquadri))
        self.assertEqual("1", riquadri[0]["value"])
        self.assertEqual("1", riquadri[1]["value"])
        self.assertEqual("100%", riquadri[2]["value"])
        self.assertEqual("n/d", riquadri[3]["value"])

    def test_senza_la_tabella_restano_i_due_del_registro(self):
        riquadri = app.riquadri_giocate(None, [_giocata("✅", 0.60)], [])
        self.assertEqual(["Registro 1X2", "Registro gol"],
                         [r["label"] for r in riquadri])

    def test_tabella_vuota_mostra_zero_non_sparisce(self):
        riquadri = app.riquadri_giocate([], [], [])
        self.assertEqual(4, len(riquadri))
        self.assertEqual("0", riquadri[0]["value"])
        self.assertEqual("0", riquadri[1]["value"])
        self.assertEqual("n/d", riquadri[2]["value"])

    def test_i_riquadri_del_registro_leggono_la_funzione_pura(self):
        righe = [_giocata("✅", 0.50), _giocata("❌", 0.70)]
        riepilogo = app.riepilogo_giocate_concluse(righe)
        riquadri = app.riquadri_giocate(None, righe, righe)
        for riquadro in riquadri:
            self.assertEqual(f"{riepilogo['percentuale_riuscite']}%", riquadro["value"])
            self.assertEqual(f"{riepilogo['scarto']:+d} punti sulle attese",
                             riquadro["delta"])


class TestRighePerFamiglia(unittest.TestCase):
    """Le due famiglie del Registro, divise con la funzione della vista."""

    def test_mercato_e_gol_e_il_modello_fuori(self):
        mercato = _giocata("✅", 0.60)
        gol = dict(_giocata("❌", 0.70), selector_version="totals_mercato_v1")
        modello = {"esito": "✅", "prob_sicuro": 50.0}   # nessuna versione: modello
        fuori_mercato, fuori_gol = app.righe_per_famiglia([mercato, gol, modello])
        self.assertEqual([mercato], fuori_mercato)
        self.assertEqual([gol], fuori_gol)

    def test_lista_vuota(self):
        self.assertEqual(([], []), app.righe_per_famiglia([]))
        self.assertEqual(([], []), app.righe_per_famiglia(None))



# ---------------------------------------------------------------------------
# La stagione del Registro: UN calcolo solo per il filtro e per i riquadri
# ---------------------------------------------------------------------------

class TestStagioneDelRegistro(unittest.TestCase):
    """La stagione si ricava dalla DATA, come fa il filtro «Stagione»."""

    def test_stagione_dalla_data_italiana(self):
        self.assertEqual("2026/2027",
                         app.stagione_di_registro({"data": "15/10/2026 20:45"}))
        self.assertEqual("2025/2026",
                         app.stagione_di_registro({"data": "15/10/2025 20:45"}))
        # La stagione comincia il 1° luglio (season_calendar): giugno e' ancora
        # quella di prima.
        self.assertEqual("2025/2026",
                         app.stagione_di_registro({"data": "30/06/2026 20:45"}))
        self.assertEqual("2026/2027",
                         app.stagione_di_registro({"data": "01/07/2026 20:45"}))

    def test_stagione_dalla_data_gia_datetime(self):
        """La colonna «data» della tabella e' un datetime: stesso risultato."""
        from datetime import datetime
        self.assertEqual("2026/2027",
                         app.stagione_di_registro({"data": datetime(2026, 10, 15, 20, 45)}))

    def test_data_mancante_e_sconosciuta(self):
        for riga in ({"data": ""}, {}, None, {"data": "Data N/D"}):
            with self.subTest(riga=riga):
                self.assertEqual("Sconosciuta", app.stagione_di_registro(riga))

    def test_stagioni_registro_dalla_piu_recente(self):
        righe = [{"data": "15/10/2025 20:45"}, {"data": "15/10/2026 20:45"},
                 {"data": "16/10/2026 18:00"}]
        self.assertEqual(["2026/2027", "2025/2026"], app.stagioni_registro(righe))
        self.assertEqual(["2026/2027", "2025/2026"], app.stagioni_registro(pd.DataFrame(righe)))

    def test_stagione_predefinita_e_la_piu_recente(self):
        righe = [{"data": "15/10/2025 20:45"}, {"data": "15/10/2026 20:45"}]
        self.assertEqual("2026/2027", app.stagione_predefinita_registro(righe))
        self.assertIsNone(app.stagione_predefinita_registro([]),
                          "senza righe non c'e' nessuna stagione da scegliere")

    def test_righe_stagione_in_corso(self):
        vecchia = {"data": "15/10/2025 20:45", "esito": "❌"}
        nuove = [{"data": "15/10/2026 20:45", "esito": "✅"},
                 {"data": "16/10/2026 18:00", "esito": "⏳"}]
        tenute, stagione = app.righe_stagione_in_corso(nuove + [vecchia])
        self.assertEqual("2026/2027", stagione)
        self.assertEqual(nuove, tenute, "la stagione passata resta fuori")
        self.assertEqual(([], None), app.righe_stagione_in_corso([]))

    def test_etichetta_stagione(self):
        for grezza, attesa in (("2026/2027", "2026-27"), ("2026/27", "2026-27"),
                               ("26/27", "2026-27"), ("", ""), (None, "")):
            with self.subTest(stagione=grezza):
                self.assertEqual(attesa, app.etichetta_stagione(grezza))

    def test_il_riquadro_scrive_la_stagione_nell_aiuto(self):
        riepilogo = app.riepilogo_giocate_concluse([_giocata("✅", 0.60)])
        self.assertIn("Stagione 2026-27.",
                       app.riquadro_registro(riepilogo, "2026/2027")["help"])
        self.assertNotIn("Stagione", app.riquadro_registro(riepilogo)["help"],
                         "senza stagione (filtro Tutti) l'aiuto non la nomina")
        # Anche quando non c'e' nessun numero la stagione si dice: «n/d» di
        # quale stagione, altrimenti, non si saprebbe.
        vuoto = app.riepilogo_giocate_concluse([])
        self.assertIn("Stagione 2025-26.",
                      app.riquadro_registro(vuoto, "2025/2026")["help"])


class TestMediaDelModello(unittest.TestCase):
    """«Modello: N%.» nei Dettagli: lo stesso testo che era nella frase."""

    def _riga(self, esito, modello):
        riga = {"esito": esito, "mercato_standard": "1",
                "selector_version": pr.SELECTOR_VERSION_CURRENT}
        if modello is not None:
            riga[pr.PROB_MODELLO_PRIMA_FIELD] = modello
        return riga

    def test_media_delle_concluse(self):
        concluse = [self._riga("✅", 63.0), self._riga("❌", 51.0)]
        self.assertEqual("Modello: 57%", app.media_modello_concluse(concluse))

    def test_nessuna_lettura_del_modello(self):
        self.assertEqual("Modello: n/d",
                         app.media_modello_concluse([self._riga("✅", None)]))

    def test_frazione_e_percentuale_danno_la_stessa_media(self):
        self.assertEqual("Modello: 60%",
                         app.media_modello_concluse([self._riga("✅", 0.6),
                                                     self._riga("❌", 60.0)]))

    def test_la_riga_nei_dettagli(self):
        righe = [self._riga("✅", 63.0), self._riga("❌", 51.0),
                 self._riga("⏳", 90.0)]
        self.assertEqual("Modello: 57%.", app.testo_modello_registro(righe),
                         "solo le concluse entrano nella media")
        self.assertEqual("Modello: 57%.", app.testo_modello_registro(pd.DataFrame(righe)))

    def test_niente_riga_senza_concluse(self):
        self.assertIsNone(app.testo_modello_registro([self._riga("⏳", 90.0)]))
        self.assertIsNone(app.testo_modello_registro([]))

    def test_la_sintesi_dice_lo_stesso_numero(self):
        righe = [self._riga("✅", 63.0), self._riga("❌", 51.0)]
        riga1, _ = app._sintesi_registro_mercato(pd.DataFrame(righe))
        self.assertIn(app.media_modello_concluse(righe) + ".", riga1)
        self.assertIn("Modello: 57%.", riga1)


if __name__ == "__main__":
    unittest.main()
