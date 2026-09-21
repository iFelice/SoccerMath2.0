"""Registro a due tabelle: una per motore, con blocchi e etichette coerenti.

Cosa viene provato (richieste utente):

* "due tabelle, una per ogni modello in modo da essere tabelle piu' pulite":
  guardie sul tab5 (due chiamate a ``_mostra_registro_modello``, il filtro
  "Modello" rimosso, nessun tetto di righe) e sulla funzione di tabella (un
  motore per tabella, ordine per data, nessuna colonna variante);
* i due blocchi statistici in cima sono gli STESSI insiemi delle due tabelle:
  una riga letta "attuale" ha sempre la scheda attuale, quindi il blocco non
  puo' mescolare i due motori; la fetta "scheda vecchia" e' dichiarata come
  dettaglio dentro il blocco legacy e non e' un terzo modello;
* la colonna del vecchio "Modello" si chiama "Scheda del record" e nessuna delle
  sue etichette contiene la parola "Modello" (dentro una tabella intitolata a un
  motore si leggeva come una contraddizione: erano due assi diversi);
* il caso vivo: una riga SENZA campo ``model_variant`` nata prima del merge di
  PR#24 (es. Sunderland-Fulham 30/08) finisce nella tabella LEGACY.
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
    MODEL_LABEL_CURRENT,
    MODEL_LABEL_LEGACY,
    MODEL_LABEL_PRE_FIX,
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_FIELD,
    MODEL_VARIANT_LEGACY,
    model_variant_read,
)

APP_PATH = os.path.join(HERE, "app.py")

# Righe di prova: due nate prima del merge senza campo variante (lette legacy),
# una per motore con il campo esplicito.
RIGHE = [
    {"home": "Sunderland", "away": "Fulham", "quando": "30/08/2026 15:00"},
    {"home": "Everton", "away": "Wolves", "quando": "05/09/2026 16:00"},
    {"home": "Inter", "away": "Roma", "quando": "19/09/2026 20:45",
     "variante": MODEL_VARIANT_CURRENT},
    {"home": "Napoli", "away": "Lazio", "quando": "20/09/2026 18:00",
     "variante": MODEL_VARIANT_LEGACY},
]


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
        "modello": MODEL_LABEL_PRE_FIX,
    }
    if variante is not None:
        r[MODEL_VARIANT_FIELD] = variante
    r["variante_codice"] = model_variant_read(r)
    return r


def _df(righe):
    df = pd.DataFrame(righe).fillna({"esito": "⏳", "risultato_reale": "-"})
    df["data"] = pd.to_datetime(df["data"], format="%d/%m/%Y %H:%M", errors="coerce")
    return df


def _righe_fixture():
    return [_riga(**r) for r in RIGHE]


class TestGuardieTab5(unittest.TestCase):
    """Il tab5 del Registro non ha piu' UNA tabella che mescola i due motori."""

    @classmethod
    def setUpClass(cls):
        cls.src = open(APP_PATH, encoding="utf-8").read()
        cls.tab5 = cls.src[cls.src.index("with tab5:"):]

    def test_due_tabelle_etichettate_attuale_sopra_legacy_sotto(self):
        # I nomi dei due modelli in pagina: "Drago a 2 Teste" (attuale) sopra,
        # "Legacy" sotto. Stanno in ``NOMI_MODELLI``, un posto solo.
        self.assertIn('NOMI_MODELLI = {MODEL_VARIANT_CURRENT: "Drago a 2 Teste", '
                      'MODEL_VARIANT_LEGACY: "Legacy"}', self.src)
        self.assertIn('f"🟢 {NOMI_MODELLI[MODEL_VARIANT_CURRENT]}"', self.tab5)
        self.assertIn('f"🟠 {NOMI_MODELLI[MODEL_VARIANT_LEGACY]}"', self.tab5)
        self.assertLess(self.tab5.index('f"🟢 {NOMI_MODELLI[MODEL_VARIANT_CURRENT]}"'),
                        self.tab5.index('f"🟠 {NOMI_MODELLI[MODEL_VARIANT_LEGACY]}"'))
        self.assertNotIn("MODELLO ATTUALE", self.tab5)
        self.assertNotIn("MODELLO LEGACY", self.tab5)
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


class TestBlocchiAllineatiAlleTabelle(unittest.TestCase):
    """Due blocchi, uno per motore: stesse righe delle due tabelle.

    Il terzo riquadro ("Storico / pre-fix") non e' un modello: e' la sotto-fetta
    del blocco legacy scritta prima del versionamento dei record, e ora e'
    dichiarata come riga di dettaglio.
    """

    @classmethod
    def setUpClass(cls):
        cls.src = open(APP_PATH, encoding="utf-8").read()
        cls.tab5 = cls.src[cls.src.index("with tab5:"):]

    def test_due_blocchi_e_nessun_terzo_modello(self):
        self.assertEqual(2, self.tab5.count("_mostra_blocco_modello("),
                         "due blocchi: uno per motore, come le tabelle")
        self.assertNotIn("##### 📊 Modello attuale", self.tab5)
        self.assertNotIn("##### 📜 Storico / pre-fix (audit)", self.tab5)
        self.assertNotIn("historical_stats", self.tab5)

    def test_blocchi_presi_dalle_stesse_maschere_delle_tabelle(self):
        # Blocchi, tabelle e affidabilita' partono dalle stesse due maschere
        # sulla stessa colonna: nessun secondo modo di contare.
        self.assertIn('maschera_attuale = df_display["variante_codice"] == MODEL_VARIANT_CURRENT', self.tab5)
        self.assertIn('maschera_legacy = df_display["variante_codice"] == MODEL_VARIANT_LEGACY', self.tab5)
        self.assertIn('attuale_records = df_display[maschera_attuale].to_dict("records")', self.tab5)
        self.assertIn('legacy_records = df_display[maschera_legacy].to_dict("records")', self.tab5)
        self.assertNotIn("split_by_variant", self.tab5,
                         "le parti si prendono dalle maschere: su un DataFrame la variante assente diventa NaN")

    def test_dettaglio_scheda_vecchia_dichiarato_non_nascosto(self):
        self.assertIn("schede_vecchie = [r for r in legacy_records if not is_current_model(r)]", self.tab5)
        self.assertIn("con la **scheda vecchia**", self.tab5)

    def test_blocco_mostra_i_quattro_numeri_delle_sue_righe(self):
        righe = [_riga("Inter", "Roma", "19/09/2026 20:45", variante=MODEL_VARIANT_CURRENT),
                 _riga("Napoli", "Lazio", "20/09/2026 18:00", variante=MODEL_VARIANT_CURRENT)]
        finto = mock.MagicMock()
        colonne = [mock.MagicMock() for _ in range(4)]
        finto.columns.return_value = colonne
        with mock.patch.object(app, "st", finto):
            app._mostra_blocco_modello(righe, "🟢 Drago a 2 Teste", "sotto")
        intestazione = finto.markdown.call_args[0][0]
        self.assertIn("— 2 righe", intestazione)
        etichette = [c.metric.call_args[0][0] for c in colonne]
        self.assertEqual(["Totale", "✅ Vinte", "❌ Perse", "⏳ Attesa"], etichette)
        self.assertEqual(2, colonne[0].metric.call_args[0][1])

    def test_blocchi_e_tabelle_contano_le_stesse_righe(self):
        df = _df(_righe_fixture())
        maschera_attuale = df["variante_codice"] == MODEL_VARIANT_CURRENT
        maschera_legacy = df["variante_codice"] == MODEL_VARIANT_LEGACY
        # Le stesse espressioni del tab5, sulle stesse righe.
        attuale_records = df[maschera_attuale].to_dict("records")
        legacy_records = df[maschera_legacy].to_dict("records")
        self.assertEqual(int(maschera_attuale.sum()), len(attuale_records))
        self.assertEqual(int(maschera_legacy.sum()), len(legacy_records))
        self.assertEqual(len(df), len(attuale_records) + len(legacy_records))
        self.assertEqual(["Inter"], [r["home"] for r in attuale_records])
        self.assertIn("Sunderland", [r["home"] for r in legacy_records],
                      "la riga senza campo nata prima del merge e' nel blocco legacy, non in un terzo gruppo")

    def test_variante_assente_non_diventa_nan(self):
        """Il bug visto in UI il 21/09/2026: su un DataFrame la variante assente
        diventa NaN e `str(nan)` e' "nan" (una terza variante fantasma)."""
        df = _df(_righe_fixture())
        record = df.to_dict("records")
        self.assertNotIn("nan", {model_variant_read(r) for r in record})
        self.assertNotIn("nan", set(df["variante_codice"]))
        self.assertEqual({"current", "legacy"}, set(df["variante_codice"]))


class TestEtichetteScheda(unittest.TestCase):
    """La colonna parla della SCHEDA del record, non del motore Elo."""

    def test_nessuna_etichetta_contiene_la_parola_modello(self):
        for etichetta in (MODEL_LABEL_CURRENT, MODEL_LABEL_PRE_FIX, MODEL_LABEL_LEGACY):
            self.assertNotIn("Modello", etichetta,
                             "dentro la tabella di un motore 'Modello' si confonde col motore")

    def test_colonna_e_didascalia_esplicite(self):
        src = open(APP_PATH, encoding="utf-8").read()
        self.assertIn('"Scheda del record"', src)
        self.assertNotIn('"Versione record"', src)
        self.assertIn("Il **motore** (i due modelli: Drago a 2 Teste / Legacy) e' l'intestazione "
                      "delle due tabelle", src)


class TestTabellaRegistroPerMotore(unittest.TestCase):
    """La funzione di tabella mostra un motore solo, ordinato, senza tetto."""

    def _mostra(self, variante, df=None):
        df = _df(_righe_fixture()) if df is None else df
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
        df = _df(_righe_fixture())
        attuale = df["variante_codice"] == MODEL_VARIANT_CURRENT
        legacy = df["variante_codice"] == MODEL_VARIANT_LEGACY
        self.assertFalse((attuale & legacy).any(), "nessuna riga in due tabelle")
        self.assertEqual(len(df), int((attuale | legacy).sum()),
                         "nessuna riga fuori dalle due tabelle")
        self.assertEqual({MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY},
                         set(df["variante_codice"]))


if __name__ == "__main__":
    unittest.main()
