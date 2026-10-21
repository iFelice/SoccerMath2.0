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


if __name__ == "__main__":
    unittest.main()
