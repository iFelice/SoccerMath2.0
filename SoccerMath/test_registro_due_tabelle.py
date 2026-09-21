"""Registro a due tabelle: una per motore (Attuale sopra, Legacy sotto).

Cosa viene provato (richiesta utente: "due tabelle, una per ogni modello in
modo da essere tabelle piu' pulite" — una tabella sola che mescola i due motori
non va bene):

* guardie sul sorgente del tab5: due chiamate a ``_mostra_registro_modello``,
  la prima per ``MODEL_VARIANT_CURRENT`` e la seconda per
  ``MODEL_VARIANT_LEGACY``; il vecchio filtro "Modello" non c'e' piu' (le
  tabelle sono gia' una per motore) e non c'e' nessun tetto di righe;
* ``_mostra_registro_modello`` disegna SOLO le righe che riceve, ordinate per
  data decrescente, senza la colonna della variante (dentro una tabella di un
  solo motore sarebbe la stessa parola ripetuta su ogni riga);
* le due maschere partizionano il registro: nessuna riga sparisce, e quelle
  con variante non riconosciuta finiscono in una tabella a parte;
* il caso vivo: una riga SENZA campo ``model_variant`` nata prima del merge di
  PR#24 (es. Sunderland-Fulham 30/08) finisce nella tabella LEGACY, non in
  quella attuale.
"""
from __future__ import annotations

import logging
import os
import sys
import unittest
from unittest import mock

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

logging.getLogger("streamlit").setLevel(logging.ERROR)

import app  # noqa: E402
from prediction_registry import (  # noqa: E402
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_FIELD,
    MODEL_VARIANT_LEGACY,
    model_variant_read,
)

APP_PATH = os.path.join(HERE, "app.py")


def _riga(home, away, quando, *, variante=None, campionato="Premier League", mercato="UNDER_2.5"):
    """Una riga del Registro come la costruisce la UI (data italiana + variante)."""
    r = {
        "data": quando,
        "stagione": "2026/2027",
        "campionato": campionato,
        "home": home,
        "away": away,
        "mercato_standard": mercato,
        "prob_sicuro": 80.3,
        "risultato_reale": "-",
        "esito": "⏳",
        "origine": "Top Mix",
        "modello": "⚠️ Pre-fix",
    }
    if variante is not None:
        r[MODEL_VARIANT_FIELD] = variante
    r["variante_codice"] = model_variant_read(r)
    return r


def _df(righe):
    df = pd.DataFrame(righe).fillna({"esito": "⏳", "risultato_reale": "-"})
    df["data"] = pd.to_datetime(df["data"], format="%d/%m/%Y %H:%M", errors="coerce")
    return df


class TestGuardieTab5(unittest.TestCase):
    """Il tab5 del Registro non ha piu' UNA tabella che mescola i due motori."""

    @classmethod
    def setUpClass(cls):
        cls.src = open(APP_PATH, encoding="utf-8").read()
        cls.tab5 = cls.src[cls.src.index("with tab5:"):]

    def test_due_tabelle_etichettate_attuale_sopra_legacy_sotto(self):
        self.assertIn("MODELLO ATTUALE", self.tab5)
        self.assertIn("MODELLO LEGACY", self.tab5)
        self.assertLess(self.tab5.index("MODELLO ATTUALE"), self.tab5.index("MODELLO LEGACY"))
        self.assertEqual(2, self.tab5.count("_mostra_registro_modello("),
                         "una chiamata per motore: due tabelle, non una mista")
        # L'ordine si legge sulle DUE CHIAMATE (prima l'attuale, poi il legacy):
        # i due nomi compaiono anche nei blocchi statistiche piu' sopra.
        prima = self.tab5.index("_mostra_registro_modello(")
        seconda = self.tab5.index("_mostra_registro_modello(", prima + 1)
        self.assertIn("maschera_attuale", self.tab5[prima:seconda])
        self.assertIn("maschera_legacy", self.tab5[seconda:])
        self.assertEqual('maschera_attuale = df_display["variante_codice"] == MODEL_VARIANT_CURRENT',
                         [riga.strip() for riga in self.tab5.splitlines()
                          if "maschera_attuale =" in riga][0])
        self.assertEqual('maschera_legacy = df_display["variante_codice"] == MODEL_VARIANT_LEGACY',
                         [riga.strip() for riga in self.tab5.splitlines()
                          if "maschera_legacy =" in riga][0])

    def test_filtro_modello_rimosso(self):
        # Il filtro "Modello" serviva a separare i due motori DENTRO una tabella
        # sola: con due tabelle non serve piu' e potrebbe svuotarne una.
        self.assertNotIn("filter_variante", self.tab5)

    def test_nessun_tetto_di_righe_nel_registro(self):
        self.assertNotIn("[:10]", self.tab5)


class TestTabellaRegistroPerMotore(unittest.TestCase):
    """La funzione di tabella mostra un motore solo, ordinato, senza tetto."""

    RIGHE = [
        _riga("Sunderland", "Fulham", "30/08/2026 15:00"),                      # senza campo -> legacy
        _riga("Everton", "Wolves", "05/09/2026 16:00"),                          # senza campo -> legacy
        _riga("Inter", "Roma", "19/09/2026 20:45", variante=MODEL_VARIANT_CURRENT),
        _riga("Napoli", "Lazio", "20/09/2026 18:00", variante=MODEL_VARIANT_LEGACY),
    ]

    def _mostra(self, variante, df=None):
        df = _df(self.RIGHE) if df is None else df
        with mock.patch.object(app, "st", mock.MagicMock()) as finto:
            app._mostra_registro_modello(
                df[df["variante_codice"] == variante], f"TITOLO {variante}", "sotto", "css")
        return finto

    def test_legacy_contiene_le_righe_senza_campo_nate_prima_del_merge(self):
        finto = self._mostra(MODEL_VARIANT_LEGACY)
        mostrate = finto.dataframe.call_args[0][0]
        self.assertIn("Sunderland", list(mostrate["home"]),
                      "Sunderland-Fulham 30/08 e' legacy: riga senza campo nata prima di PR#24")
        self.assertNotIn("Inter", list(mostrate["home"]))
        self.assertEqual(3, len(mostrate))

    def test_attuale_contiene_solo_il_motore_attuale(self):
        finto = self._mostra(MODEL_VARIANT_CURRENT)
        mostrate = finto.dataframe.call_args[0][0]
        self.assertEqual(["Inter"], list(mostrate["home"]))

    def test_una_sola_colonna_modello_e_colonne_condivise(self):
        for variante in (MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY):
            finto = self._mostra(variante)
            mostrate = finto.dataframe.call_args[0][0]
            self.assertEqual(app.REGISTRO_COLONNE, list(mostrate.columns))
            self.assertNotIn("variante", mostrate.columns,
                             "dentro una tabella di un solo motore la variante e' costante")
            testata = finto.markdown.call_args[0][0]
            self.assertIn(f"{len(mostrate)} righe", testata)

    def test_ordine_per_data_decrescente(self):
        finto = self._mostra(MODEL_VARIANT_LEGACY)
        mostrate = finto.dataframe.call_args[0][0]
        date = list(mostrate["data"])
        self.assertEqual(date, sorted(date, reverse=True))

    def test_nessun_tetto_di_righe(self):
        righe = [_riga(f"Casa{i}", f"Ospite{i}", "05/09/2026 16:00",
                       variante=MODEL_VARIANT_LEGACY) for i in range(60)]
        finto = self._mostra(MODEL_VARIANT_LEGACY, df=_df(righe))
        mostrate = finto.dataframe.call_args[0][0]
        self.assertEqual(60, len(mostrate), "nessun tetto di 10 righe nel Registro")

    def test_motore_senza_righe_non_disegna_una_tabella_vuota(self):
        finto = self._mostra("inesistente")
        self.assertFalse(finto.dataframe.called)
        self.assertTrue(finto.info.called)

    def test_maschere_partizionano_il_registro(self):
        df = _df(self.RIGHE)
        attuale = df["variante_codice"] == MODEL_VARIANT_CURRENT
        legacy = df["variante_codice"] == MODEL_VARIANT_LEGACY
        self.assertFalse((attuale & legacy).any(), "nessuna riga in due tabelle")
        self.assertEqual(len(df), int((attuale | legacy).sum()),
                         "nessuna riga fuori dalle due tabelle")
        self.assertEqual({MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY},
                         set(df["variante_codice"]))


if __name__ == "__main__":
    unittest.main()
