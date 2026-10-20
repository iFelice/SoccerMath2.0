"""Test del modulo puro ``scheda_grafica`` (la scheda partita in HTML).

Cosa verificano, in parole povere:

* l'HTML di Napoli-Roma costruita dai risultati ARCHIVIATI di Serie A
  (classifica vera: Napoli 9ª, Roma 3ª) con un evento quote fissato nel
  test — un solo libro, cosi' le percentuali non ballano con l'aggiornamento
  quotidiano di ``live_odds.json`` — contiene le tre percentuali delle
  barre (34,6 27,8 37,6), i loro colori (blu, grigio, arancione), la riga
  del modello, il pronostico-trattino con la sua nota e l'etichetta gol;
* nel riquadro di classifica Napoli ha la posizione 9 con la freccia verso
  il basso e «era 8», Roma la 3 con il segno uguale; ci sono punti,
  giocate, giornate rimaste, distanze e frasi obiettivo, e la griglia CSS
  (auto-fit/minmax, uno sotto l'altro sotto i 640 pixel);
* nell'HTML non compare mai ``None``, ``nan`` o ``NaN``, in nessuna delle
  due palette (chiara e scura, scelte col parametro ``tema``);
* un nome di squadra con ``<`` e ``>`` viene escapato: nell'HTML si legge
  ``&lt;``/``&gt;``, mai il tag scritto nel nome.
"""
from __future__ import annotations

import copy
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
for _p in (HERE, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import scheda_grafica as sg  # noqa: E402
import scheda_partita as sp  # noqa: E402
import market_odds as mo  # noqa: E402

CAMP = "Serie A"

# L'evento quote del test: UN libro con terna 3.04/3.79/2.80, che de-vigata
# (la stessa devig_proporzionale di market_odds) da' 34,6/27,8/37,6. E'
# fissato qui, e non letto da live_odds.json, perche' quel file viene
# riscritto ogni giorno dal workflow: le posizioni in classifica invece
# vengono dai risultati archiviati letti con carica_risultati_stagione.
EVENTO_NAPOLI_ROMA = {
    "home_team": "Napoli", "away_team": "AS Roma",
    "commence_time": "2026-10-24T16:00:00Z",
    "libri": [{"key": "pinnacle", "title": "Pinnacle",
               "h2h": {"home": 3.04, "draw": 3.79, "away": 2.80},
               "totals": {"2.5": {"Over": 1.91, "Under": 1.98}}}],
}
MODELLO_NAPOLI_ROMA = {("Napoli", "Roma"): {"1": 31, "X": 27, "2": 42}}


def _scheda_napoli_roma() -> dict:
    risultati = sp.carica_risultati_stagione(CAMP)
    if risultati.empty:
        raise unittest.SkipTest("nessun risultato archiviato di Serie A")
    return sp.costruisci_scheda(
        CAMP, "Napoli", "Roma", evento_quote=EVENTO_NAPOLI_ROMA,
        modello_1x2=MODELLO_NAPOLI_ROMA, risultati=risultati, storico_elo={})


class TestProbabilitaGrafica(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.scheda = _scheda_napoli_roma()
        cls.html = sg.html_probabilita(cls.scheda)

    def test_le_tre_barre_con_percentuali_e_colori(self):
        for atteso in ("34,6", "27,8", "37,6"):
            with self.subTest(percentuale=atteso):
                self.assertIn(atteso, self.html)
        for esito in ("1", "X", "2"):
            with self.subTest(esito=esito):
                self.assertIn(sg.COLORI_ESITI[esito], self.html)
        # La larghezza della barra e' la percentuale (notazione CSS).
        for larghezza in ("width:34.6%", "width:27.8%", "width:37.6%"):
            with self.subTest(larghezza=larghezza):
                self.assertIn(larghezza, self.html)

    def test_riga_modello_piccola_e_grigia(self):
        self.assertIn("Modello: 1 31 X 27 2 42", self.html)
        self.assertIn("sg-modello", self.html)

    def test_modello_assente_nessuna_riga(self):
        scheda = sp.costruisci_scheda(
            CAMP, "Napoli", "Roma", evento_quote=EVENTO_NAPOLI_ROMA,
            risultati=sp.carica_risultati_stagione(CAMP), storico_elo={})
        self.assertNotIn("Modello:", sg.html_probabilita(scheda))

    def test_etichette_pronostico_e_gol(self):
        # Il massimo delle quote (37,6%) non arriva alla soglia: trattino e
        # nota costruita dalla costante, con il simbolo di percento.
        atteso = (f"nessun esito arriva al "
                  f"{int(round(mo.SOGLIA_TOPMIX_MERCATO * 100))}%")
        self.assertEqual(atteso, sg.NOTA_SOTTO_SOGLIA)
        self.assertIn("%", sg.NOTA_SOTTO_SOGLIA)
        self.assertIn("Pronostico:", self.html)
        self.assertIn(f"— ({sg.NOTA_SOTTO_SOGLIA})", self.html)
        self.assertIn("Gol:", self.html)
        self.assertIn("P(Over 2,5)", self.html)

    def test_pronostico_con_sigla(self):
        scheda = copy.deepcopy(self.scheda)
        scheda["pronostico"] = "2"
        html = sg.html_probabilita(scheda)
        self.assertIn("Pronostico:</strong> 2", html)
        self.assertNotIn("nessun esito arriva", html)


class TestClassificaGrafica(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.scheda = _scheda_napoli_roma()
        cls.html = sg.html_classifica(cls.scheda)

    def test_napoli_nona_freccia_giu_era_8(self):
        self.assertIn("Napoli", self.html)
        self.assertIn("9°", self.html)
        self.assertIn("▼ (era 8)", self.html)
        self.assertIn(sg.COLORI_FRECCIA["giu"], self.html)

    def test_roma_terza_segno_uguale(self):
        self.assertIn("Roma", self.html)
        self.assertIn("3°", self.html)
        self.assertIn("= (era 3)", self.html)
        self.assertIn(sg.COLORI_FRECCIA["ferma"], self.html)

    def test_freccia_su_se_migliorata(self):
        scheda = copy.deepcopy(self.scheda)
        scheda["classifica"]["casa"]["pos"] = 7  # era 8: migliorata di una
        html = sg.html_classifica(scheda)
        self.assertIn("▲ (era 8)", html)
        self.assertIn(sg.COLORI_FRECCIA["su"], html)

    def test_punti_giocate_rimaste_distanze_e_frase(self):
        for atteso in ("10 punti", "17 punti", "7 partite giocate",
                       "31 giornate rimaste", "dal primo posto",
                       "dal sesto posto", "sopra la zona retrocessione",
                       "In corsa per l'Europa: 3 punti dal sesto posto.",
                       "In corsa per il titolo: 2 punti dal primo posto.",
                       "sg-frase"):
            with self.subTest(atteso=atteso):
                self.assertIn(atteso, self.html)

    def test_griglia_auto_fit_e_sotto_i_640_pixel(self):
        self.assertIn("repeat(auto-fit, minmax(280px, 1fr))", self.html)
        self.assertIn("@media (max-width: 640px)", self.html)

    def test_senza_giornata_precedente_nessun_none(self):
        scheda = copy.deepcopy(self.scheda)
        scheda["classifica"]["casa"]["pos_prec"] = None
        html = sg.html_classifica(scheda)
        self.assertIn("nessuna giornata precedente", html)
        self.assertNotIn("None", html)


class TestFormaGrafica(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.scheda = _scheda_napoli_roma()
        cls.html = sg.html_forma(cls.scheda)

    def test_cerchi_da_44_pixel_colori_e_ordine(self):
        self.assertIn("width: 44px; height: 44px", self.html)
        # Cinque cerchi per squadra, due squadre.
        self.assertEqual(10, self.html.count('class="sg-cerchio"'))
        for colore in sg.COLORI_FORMA.values():
            with self.subTest(colore=colore):
                self.assertIn(colore, self.html)
        for lettera in (">V<", ">N<", ">P<"):
            with self.subTest(lettera=lettera):
                self.assertIn(lettera, self.html)
        # La successione dei cerchi e' quella delle partite della scheda
        # (dalla piu' vecchia a sinistra alla piu' recente a destra): le
        # lettere attese si contano sulle partite, non si riscrivono qui.
        forma = self.scheda["forma"]["casa"]
        attese = [sg.LETTERE_FORMA[p["esito"]] for p in forma["partite"]]
        trovate = re.findall(r'class="sg-cerchio"[^>]*>([VNP])<', self.html)
        self.assertEqual(attese, trovate[:5])

    def test_conteggio_elenco_e_legenda(self):
        forma = self.scheda["forma"]["trasferta"]
        ultima = forma["partite"][-1]
        for atteso in ("Legenda:", "V = vittoria", "N = pareggio", "P = sconfitta",
                       ultima["avversario_nome"], ultima["dove"],
                       ultima["risultato"]):
            with self.subTest(atteso=atteso):
                self.assertIn(atteso, self.html)


class TestGolGrafico(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.scheda = _scheda_napoli_roma()
        cls.html = sg.html_gol(cls.scheda)

    def test_casa_in_casa_trasferta_in_trasferta_scala_0_3(self):
        self.assertIn("Napoli — in casa", self.html)
        self.assertIn("Roma — in trasferta", self.html)
        self.assertIn("Gol fatti a partita", self.html)
        self.assertIn("Gol subiti a partita", self.html)
        self.assertIn("da 0 a 3 gol a partita", self.html)
        # La larghezza e' media/3: quella del blocco giusto della scheda.
        blocco = self.scheda["gol"]["casa"]["casa"]
        larghezza = blocco["media_fatti"] / sg.SCALA_GOL * 100.0
        self.assertIn(f"width:{larghezza:.1f}%", self.html)

    def test_riga_stagionale_con_percentuali(self):
        stag = self.scheda["gol"]["trasferta"]["stagione"]
        over = round(100.0 * stag["piu_di_2_gol"] / stag["partite"])
        btts = round(100.0 * stag["entrambe_a_segno"] / stag["partite"])
        self.assertIn(f"Over 2,5: {over}%", self.html)
        self.assertIn(f"Entrambe a segno: {btts}%", self.html)
        self.assertIn("In stagione:", self.html)


class TestPrecedentiGrafica(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.scheda = _scheda_napoli_roma()
        cls.html = sg.html_precedenti(cls.scheda)

    def test_precedenti_e_testo_piccolo(self):
        self.assertIn("Precedenti in stagione", self.html)
        precedenti = self.scheda["precedenti"]
        if precedenti:
            self.assertIn(precedenti[0]["casa_nome"], self.html)
            self.assertIn(precedenti[0]["risultato"], self.html)
        else:
            self.assertIn("non si sono ancora affrontate", self.html)
        self.assertIn("sg-piccolo", self.html)

    def test_dati_mancanti_solo_se_ci_sono(self):
        scheda = copy.deepcopy(self.scheda)
        scheda["note_dati"] = ["Nota <di> prova"]
        html = sg.html_precedenti(scheda)
        self.assertIn("Dati mancanti", html)
        self.assertIn("Nota &lt;di&gt; prova", html)
        scheda["note_dati"] = []
        self.assertNotIn("Dati mancanti", sg.html_precedenti(scheda))

    def test_cinque_sezioni_nella_scheda_intera(self):
        html = sg.html_scheda(self.scheda)
        self.assertEqual(5, html.count('class="sg sg-sezione"'))
        for titolo in ("Probabilità", "Classifica", "Forma: ultime 5",
                       "Gol", "Precedenti in stagione"):
            with self.subTest(titolo=titolo):
                self.assertIn(titolo, html)


class TestPaletteENomiEscapati(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.scheda = _scheda_napoli_roma()

    def test_due_palette_e_parametro_tema(self):
        self.assertEqual({"chiaro", "scuro"}, set(sg.PALETTE))
        chiaro = sg.html_scheda(self.scheda, tema="chiaro")
        scuro = sg.html_scheda(self.scheda, tema="scuro")
        self.assertIn(sg.PALETTE["chiaro"]["sfondo"], chiaro)
        self.assertIn(sg.PALETTE["scuro"]["sfondo"], scuro)
        self.assertNotEqual(chiaro, scuro)
        # La predefinita e' la chiara.
        self.assertEqual(chiaro, sg.html_scheda(self.scheda))

    def test_nessun_none_nan_in_html(self):
        for tema in ("chiaro", "scuro"):
            with self.subTest(tema=tema):
                html = sg.html_scheda(self.scheda, tema=tema)
                self.assertNotIn("None", html)
                self.assertIsNone(re.search(r"\bnan\b|\bNaN\b", html))

    def test_nome_con_minore_e_maggiore_viene_escapato(self):
        scheda = copy.deepcopy(self.scheda)
        nome = "Squadra <b>Speciale</b>"
        scheda["casa"]["nome"] = nome
        scheda["classifica"]["casa"]["nome"] = nome
        scheda["classifica"]["casa"]["frase"] = "Frase <con> tag"
        html = sg.html_classifica(scheda)
        self.assertIn("Squadra &lt;b&gt;Speciale&lt;/b&gt;", html)
        self.assertIn("Frase &lt;con&gt; tag", html)
        self.assertNotIn("<b>Speciale</b>", html)

    def test_le_due_sezioni_nella_scheda_intera(self):
        html = sg.html_scheda(self.scheda)
        self.assertIn("Probabilità", html)
        self.assertIn("Classifica", html)
        self.assertIn("34,6", html)
        self.assertIn("9°", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
