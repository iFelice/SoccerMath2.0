"""Nomi delle partite nei riquadri di «Multiple» e altezza della tabella del periodo.

Due difetti visti a schermo, due regole piccole e pure, ognuna col suo test:

1) **Il nome della partita nei riquadri di «Multiple».** «1. FC Koln - FC
   Schalke 04» e «1. FSV Mainz 05 - Bayern» iniziano con «numero.» e
   ``st.markdown`` li leggeva come prima voce di un elenco numerato. Adesso la
   trasformazione sta in ``app.nome_riquadro_multiple``: protegge il punto
   (``1\\.``) e lascia il testo mostrato IDENTICO; i nomi normali («Milan -
   Roma») tornano com'erano. Il test guarda anche cosa arriva davvero a
   ``st.markdown`` dentro ``app._mostra_riquadri_multiple``, cosi' la regola
   non resta una funzione mai chiamata.

2) **L'altezza della tabella del periodo.** ``app._mostra_tabella_periodo``
   disegnava sempre 420 px: con 5 partite restavano 6 righe vuote. La formula
   sta in ``app._altezza_tabella_periodo``: 35 px per riga (intestazione
   compresa) piu' 3 px per i bordi, cioe' ``n * 35 + 38``, con il tetto di 420.
   Con 1 riga 73 (non 70: senza i 3 px la tabella esce tagliata sotto,
   verificato su Streamlit 1.66), 5 righe 213, 11 e 20 righe 420. Il test
   controlla la formula E il valore che finisce in ``st.dataframe``.

Nessuna rete, nessun file del repository toccato: solo ``app`` importato in
memoria e Streamlit sostituito da un doppio.

Esecuzione:
    python -m pytest SoccerMath/test_nomi_riquadri_e_altezza_tabelle.py -v
"""
from __future__ import annotations

import logging
import os
import sys
import unittest
from unittest import mock

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.dirname(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

logging.getLogger("streamlit").setLevel(logging.ERROR)

import app  # noqa: E402

# I due nomi veri che finiscono nei riquadri (entrambi iniziano con «1.»).
NOMI_CON_NUMERO = (
    "1. FC Koln - FC Schalke 04",
    "1. FSV Mainz 05 - Bayern",
)
# Nomi che NON devono cambiare: nessun numero iniziale da proteggere.
NOMI_NORMALI = (
    "Milan - Roma",
    "Inter - Napoli",
    "Bayern Munich - Borussia Dortmund",
)


class TestNomeRiquadroMultiple(unittest.TestCase):
    """``app.nome_riquadro_multiple``: punto protetto, testo identico."""

    def test_numero_iniziale_protetto_e_testo_identico(self):
        for nome in NOMI_CON_NUMERO:
            with self.subTest(nome=nome):
                mostrato = app.nome_riquadro_multiple(nome)
                # Il punto dopo il numero porta la barra: non e' piu' una lista.
                self.assertEqual(mostrato, "1\\. " + nome[len("1. "):])
                self.assertNotRegex(mostrato, r"^\d+\.")
                # Tolta la sola barra aggiunta, il testo e' quello di partenza.
                self.assertEqual(mostrato.replace("\\", ""), nome)
                self.assertEqual(len(mostrato), len(nome) + 1)

    def test_nomi_normali_non_cambiano(self):
        for nome in NOMI_NORMALI:
            with self.subTest(nome=nome):
                self.assertEqual(app.nome_riquadro_multiple(nome), nome)

    def test_numero_non_iniziale_non_cambia(self):
        # Il numero in mezzo al nome non apre nessuna lista: resta com'e'.
        self.assertEqual(app.nome_riquadro_multiple("Milan 1. Roma"),
                         "Milan 1. Roma")

    def test_i_riquadri_mostrano_i_nomi_protetti(self):
        """La regola arriva davvero a ``st.markdown``: il riquadro la usa."""
        nome_normale = NOMI_NORMALI[0]
        riquadri = [{
            "k": "singola",
            "titolo": "Singola",
            "partite": [(n, "1 · ven 18:00") for n in NOMI_CON_NUMERO]
                        + [(nome_normale, "1 · ven 18:00")],
            "quota": "2,10",
            "riesce": "48%",
            "provvisoria": False,
            "item": {},
        }]
        finto_st = mock.MagicMock()
        # La scheda chiede prima 4 colonne (i riquadri), poi 2 (Quota/Riesce).
        finto_st.columns.side_effect = lambda n: [mock.MagicMock() for _ in range(n)]
        with mock.patch.object(app, "riquadri_multiple", return_value=riquadri), \
                mock.patch.object(app, "st", finto_st):
            app._mostra_riquadri_multiple({}, None)

        testi = [c.args[0] for c in finto_st.markdown.call_args_list]
        self.assertIn("##### Singola", testi)
        self.assertIn("1\\. FC Koln - FC Schalke 04", testi)
        self.assertIn("1\\. FSV Mainz 05 - Bayern", testi)
        self.assertIn(nome_normale, testi)
        # Il nome NON protetto non arriva piu' al markdown.
        self.assertNotIn("1. FC Koln - FC Schalke 04", testi)
        self.assertNotIn("1. FSV Mainz 05 - Bayern", testi)


class TestAltezzaTabellaPeriodo(unittest.TestCase):
    """``app._altezza_tabella_periodo``: 35 px a riga (intestazione compresa)
    piu' 3 px di bordi, massimo 420."""

    def test_altezze_richieste(self):
        attese = {1: 73, 5: 213, 11: 420, 20: 420}
        for n_righe, altezza in attese.items():
            with self.subTest(n_righe=n_righe):
                self.assertEqual(app._altezza_tabella_periodo(n_righe), altezza)

    def test_formula_righe_piu_intestazione_piu_bordi(self):
        # 38 = 35 dell'intestazione + 3 dei bordi, non 35.
        self.assertEqual(app._altezza_tabella_periodo(1), 1 * 35 + 38)
        self.assertEqual(app._altezza_tabella_periodo(5), 5 * 35 + 38)
        self.assertEqual(app._altezza_tabella_periodo(10), 10 * 35 + 38)
        # Il tetto si applica da 11 righe in poi (10 * 35 + 38 = 388).
        self.assertEqual(app._altezza_tabella_periodo(11), 420)
        self.assertEqual(app._altezza_tabella_periodo(100), 420)

    def _altezza_disegnata(self, n_righe):
        df = pd.DataFrame({"Quote %": [50.0] * n_righe})
        finto_st = mock.MagicMock()
        with mock.patch.object(app, "tabella_pronostici_visibile",
                               return_value=(df, [{}] * n_righe)), \
                mock.patch.object(app, "_config_colonne_pronostici",
                                  return_value={}), \
                mock.patch.object(app, "chiave_tabella_pulita",
                                  return_value="chiave_finta"), \
                mock.patch.object(app, "st", finto_st):
            app._mostra_tabella_periodo([], "chiave_finta")
        return finto_st.dataframe.call_args.kwargs["height"]

    def test_la_tabella_usa_l_altezza_calcolata(self):
        # Una riga: 73 px, non 70 (con 70 la tabella esce tagliata sotto).
        self.assertEqual(self._altezza_disegnata(1), 73)
        self.assertEqual(self._altezza_disegnata(5), 213)
        self.assertEqual(self._altezza_disegnata(20), 420)


if __name__ == "__main__":
    unittest.main()
