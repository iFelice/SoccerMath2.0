"""`scheda_grafica.html_tabella_partite`: la tabella della giornata in HTML.

La scheda «🏟️ Partite» non disegna piu' un ``st.dataframe``: la tabella e' una
stringa HTML costruita da una funzione PURA, con le stesse classi ``sg`` e le
stesse due palette (chiara e scura) della scheda partita. Qui si prova la
funzione sui dati che riceve davvero (le righe di ``app.riga_tabella_partita``)
e si tengono gli aiuti che gli AppTest usano per rileggere la tabella resa:

* ``righe_da_html`` / ``dataframe_da_html``: il testo delle celle, con una
  piccola macchina a stati (``html.parser``, nessuna dipendenza in piu');
* ``tabella_giornata``: la tabella resa nella scheda «🏟️ Partite» di un
  AppTest, gia' come DataFrame con le sette colonne.

Cosa si verifica
----------------
* le sette colonne nell'ordine della commessa (Quando, Partita, 1, X, 2,
  Pronostico, Risultato);
* i nomi che arrivano dai dati passano da ``html.escape``: un nome con ``<``,
  ``>`` o ``&`` si legge come testo e non diventa mai un tag;
* la larghezza delle barre: la percentuale a una cifra decimale (virgola
  italiana nel testo, punto nel CSS), i colori 1 blu / X grigio / 2 arancione,
  e l'uscita dai limiti (sotto 0 o sopra 100) riportata nell'intervallo;
* il trattino grigio quando nessun esito arriva alla soglia, la pastiglia del
  colore dell'esito quando c'e', la cella vuota quando la quota manca;
* le partite gia' giocate: risultato al posto delle probabilita', come prima;
* il tema: chiaro e scuro cambiano i colori della palette, un tema
  sconosciuto ricade sul chiaro.

Esecuzione:
    python -m pytest SoccerMath/test_html_tabella_partite.py -v
"""
from __future__ import annotations

import html.parser
import os
import sys
import unittest

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.dirname(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import scheda_grafica as sgr  # noqa: E402

#: Le colonne promesse, nell'ordine in cui si leggono.
COLONNE = ["Quando", "Partita", "1", "X", "2", "Pronostico", "Risultato"]


def _riga(partita="Genoa - Fiorentina", uno=33.4, x=32.1, due=34.5,
          pronostico="2", risultato="", quando="sab 17/10, 18:00"):
    """Una riga come la lascia ``app.riga_tabella_partita``."""
    return {"Quando": quando, "Partita": partita, "1": uno, "X": x, "2": due,
            "Pronostico": pronostico, "Risultato": risultato}


class _LettoreTabella(html.parser.HTMLParser):
    """Legge una ``<table>``: l'intestazione e una lista di celle per riga.

    Le celle si leggono come TESTO (``convert_charrefs``): ``&amp;`` torna
    ``&``, e quello che si confronta nei test e' cio' che l'utente legge.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.intestazione = []
        self.righe = []
        self._cella = None
        self._riga = None
        self._in_testa = False

    def handle_starttag(self, tag, attrs):
        if tag == "thead":
            self._in_testa = True
        elif tag == "tr":
            self._riga = []
        elif tag in ("th", "td"):
            self._cella = []

    def handle_data(self, data):
        if self._cella is not None:
            self._cella.append(data)

    def handle_endtag(self, tag):
        if tag in ("th", "td") and self._cella is not None:
            testo = "".join(self._cella).strip()
            if self._in_testa:
                self.intestazione.append(testo)
            elif self._riga is not None:
                self._riga.append(testo)
            self._cella = None
        elif tag == "tr" and self._riga is not None:
            if not self._in_testa and self._riga:
                self.righe.append(self._riga)
            self._riga = None
        elif tag == "thead":
            self._in_testa = False


def corpo(html: str) -> str:
    """Il corpo della pagina, senza il blocco ``<style>``.

    Il CSS contiene i nomi delle classi e delle proprieta' (``.sg-pastiglia``,
    ``width:``): chi controlla che una cella NON ci sia deve guardare solo il
    corpo, altrimenti trova la regola di stile e si sbaglia.
    """
    testo = html or ""
    fine = testo.find("</style>")
    return testo[fine + len("</style>"):] if fine >= 0 else testo


def righe_da_html(html: str) -> list:
    """Le righe della tabella come dizionari ``{colonna: testo}``.

    Le celle vuote restano stringhe vuote (mai ``None``: la tabella non scrive
    «None» da nessuna parte). Il primo elemento dell'intestazione e' la prima
    colonna, cosi' i test leggono per nome e non per posizione.
    """
    lettore = _LettoreTabella()
    lettore.feed(html or "")
    lettore.close()
    colonne = lettore.intestazione
    return [dict(zip(colonne, celle)) for celle in lettore.righe]


def dataframe_da_html(html: str) -> pd.DataFrame:
    """La tabella HTML come DataFrame a sette colonne (celle vuote = "")."""
    righe = righe_da_html(html)
    if not righe:
        return pd.DataFrame(columns=sgr.COLONNE_TABELLA_PARTITE)
    return pd.DataFrame(righe, columns=list(sgr.COLONNE_TABELLA_PARTITE))


def selettore_scheda(at):
    """Il selectbox «Apri la scheda» della scheda Partite di un AppTest."""
    import app as app_mod
    trovati = [sb for sb in at.selectbox
               if (sb.key or "") == app_mod.CHIAVE_SCEGLI_PARTITA]
    if len(trovati) != 1:
        raise AssertionError(
            f"un solo selettore «Apri la scheda», trovati {len(trovati)}")
    return trovati[0]


def pulsante_apri(at):
    """Il pulsante «Apri» della scheda Partite di un AppTest."""
    import app as app_mod
    trovati = [b for b in at.button
               if (b.key or "") == app_mod.CHIAVE_APRI_PARTITA]
    if len(trovati) != 1:
        raise AssertionError(f"un solo pulsante «Apri», trovati {len(trovati)}")
    return trovati[0]


def apri_scheda(at, etichetta=None):
    """Sceglie la partita nel selettore, preme «Apri» e ridisegna la pagina.

    E' il gesto che ha preso il posto del clic sulla riga: la tabella e' HTML
    (non un widget selezionabile), quindi la scheda si apre da qui. Con
    ``etichetta`` assente si apre la partita gia' scelta nel selettore. Torna
    l'etichetta aperta, cosi' chi chiama sa che titolo aspettarsi.
    """
    selettore = selettore_scheda(at)
    if etichetta is None:
        etichetta = selettore.value
    if etichetta not in list(selettore.options):
        raise AssertionError(f"la partita {etichetta!r} non e' nel selettore: "
                             f"{list(selettore.options)}")
    selettore.set_value(etichetta)
    pulsante_apri(at).click()
    at.run(timeout=900)
    return etichetta


def tabella_giornata(at, scheda="🏟️ Partite") -> pd.DataFrame:
    """La tabella della giornata resa in un AppTest (DataFrame vuoto se non c'e').

    Cerca fra i blocchi della scheda quello che contiene la tabella: e' il
    ``st.markdown`` con l'HTML prodotto da ``html_tabella_partite``. Con il
    calendario non disponibile la scheda non disegna nessuna tabella, e qui
    torna un DataFrame vuoto con le sette colonne.
    """
    from test_apptest_topmix_presentazione import _testi_della_tab

    fuori, _dentro = _testi_della_tab(at, scheda)
    for pezzo in fuori:
        if 'class="sg-tabella"' in pezzo:
            return dataframe_da_html(pezzo)
    return pd.DataFrame(columns=sgr.COLONNE_TABELLA_PARTITE)


class TestColonneEEscape(unittest.TestCase):
    """Le sette colonne, e i nomi che non devono mai diventare tag."""

    def test_sette_colonne_nell_ordine_promesso(self):
        righe = righe_da_html(sgr.html_tabella_partite([_riga()]))
        self.assertEqual(1, len(righe))
        self.assertEqual(COLONNE, list(righe[0]))
        self.assertEqual(COLONNE, list(sgr.COLONNE_TABELLA_PARTITE))
        self.assertEqual(COLONNE, list(dataframe_da_html(
            sgr.html_tabella_partite([_riga()])).columns))

    def test_i_nomi_dei_dati_sono_escapati(self):
        """Un nome con ``<``, ``>`` e ``&`` si legge come testo, mai come tag."""
        nome = '<img src=x onerror="alert(1)"> - A & B'
        html = sgr.html_tabella_partite([_riga(partita=nome)])
        self.assertNotIn("<img", corpo(html), "nessun tag che arriva dai dati")
        self.assertIn("&lt;img", html)
        self.assertIn("&amp;", html)
        # ...e il testo che l'utente legge e' quello originale, carattere per
        # carattere (l'escape e' solo nella pagina, non nei dati).
        self.assertEqual(nome, righe_da_html(html)[0]["Partita"])
        # Anche la cella «Risultato» e «Quando», che pure arrivano dai dati.
        sporca = sgr.html_tabella_partite(
            [_riga(quando="<script>alert(1)</script>", risultato="<b>2-1</b>")])
        self.assertNotIn("<script", sporca)
        self.assertNotIn("<b>", sporca)
        self.assertEqual("<b>2-1</b>", righe_da_html(sporca)[0]["Risultato"])

    def test_niente_partite_lo_dice_una_volta(self):
        html = sgr.html_tabella_partite([])
        self.assertIn(sgr.FRASE_NESSUNA_PARTITA, html)
        self.assertNotIn("<table", html, "senza righe non si disegna la tabella")
        self.assertEqual([], righe_da_html(html))
        self.assertTrue(dataframe_da_html(html).empty)


class TestBarre(unittest.TestCase):
    """Le barre 1/X/2: larghezza, colore, percentuale a una cifra con la virgola."""

    def test_larghezza_e_percentuale_della_barra(self):
        html = sgr.html_tabella_partite([_riga(uno=33.4, x=32.1, due=34.5)])
        self.assertIn('style="width:33.4%;background:#2563eb"', html)
        self.assertIn('style="width:32.1%;background:#8a8f98"', html)
        self.assertIn('style="width:34.5%;background:#e07b1f"', html)
        # Una cifra decimale e la virgola italiana nel testo, in tutte e tre.
        celle = righe_da_html(html)[0]
        self.assertEqual("33,4%", celle["1"])
        self.assertEqual("32,1%", celle["X"])
        self.assertEqual("34,5%", celle["2"])
        for esito in ("1", "X", "2"):
            self.assertRegex(celle[esito], r"^\d{1,3},\d%$")

    def test_i_colori_sono_quelli_della_scheda_partita(self):
        self.assertEqual({"1": "#2563eb", "X": "#8a8f98", "2": "#e07b1f"},
                         dict(sgr.COLORI_ESITI))
        html = sgr.html_tabella_partite([_riga()])
        for esito in ("1", "X", "2"):
            with self.subTest(esito=esito):
                self.assertIn(f"background:{sgr.COLORI_ESITI[esito]}", html)

    def test_percentuale_fuori_dai_limiti_rientra(self):
        html = sgr.html_tabella_partite([_riga(uno=120.0, x=-5.0, due=0.04)])
        self.assertIn("width:100.0%;background:#2563eb", html)
        self.assertIn("width:0.0%;background:#8a8f98", html)
        self.assertIn("width:0.0%;background:#e07b1f", html)

    def test_percentuale_arrotondata_a_una_cifra(self):
        html = sgr.html_tabella_partite([_riga(uno=33.44, x=33.45, due=33.96)])
        self.assertIn("width:33.4%", html)
        self.assertIn("width:33.5%", html)
        self.assertIn("width:34.0%", html)

    def test_cella_senza_numero_resta_vuota(self):
        """Nessuna barra a zero e nessuna scritta: la cella e' semplicemente vuota."""
        html = sgr.html_tabella_partite([_riga(uno=None, x=None, due=None)])
        self.assertIn('<span class="sg-cella-vuota"></span>', html)
        self.assertNotIn("width:", corpo(html),
                         "senza numero non c'e' nessuna barra")
        celle = righe_da_html(html)[0]
        self.assertEqual(("", "", ""), (celle["1"], celle["X"], celle["2"]))
        self.assertNotIn("n/d", html)
        self.assertNotIn("None", html)

    def test_legge_anche_il_testo_gia_formattato(self):
        """La forma testuale della vecchia tabella (``33,4%``) vale come il numero."""
        html = sgr.html_tabella_partite([_riga(uno="33,4%", x="", due="34,5")])
        self.assertIn('style="width:33.4%;background:#2563eb"', html)
        self.assertIn("width:34.5%;background:#e07b1f", html)
        self.assertIn('<span class="sg-cella-vuota"></span>', html)
        celle = righe_da_html(html)[0]
        self.assertEqual(("33,4%", "", "34,5%"), (celle["1"], celle["X"], celle["2"]))


class TestPronostico(unittest.TestCase):
    """La pastiglia del colore dell'esito, il trattino grigio, la cella vuota."""

    def test_pastiglia_del_colore_dell_esito(self):
        for esito in ("1", "X", "2"):
            with self.subTest(esito=esito):
                html = sgr.html_tabella_partite([_riga(pronostico=esito)])
                self.assertIn(f'<span class="sg-pastiglia" '
                              f'style="background:{sgr.COLORI_ESITI[esito]}">'
                              f'{esito}</span>', html)
                self.assertEqual(esito, righe_da_html(html)[0]["Pronostico"])

    def test_trattino_grigio_sotto_la_soglia(self):
        html = sgr.html_tabella_partite([_riga(pronostico="—")])
        self.assertIn('<span class="sg-pastiglia sg-pastiglia-vuota">—</span>', html)
        self.assertNotIn("background:#2563eb\">—", html, "il trattino non e' un esito")
        self.assertEqual("—", righe_da_html(html)[0]["Pronostico"])
        self.assertEqual("—", sgr.TRATTINO_PRONOSTICO)

    def test_senza_quote_nessuna_pastiglia(self):
        for vuoto in ("", None, "   "):
            with self.subTest(valore=vuoto):
                html = sgr.html_tabella_partite([_riga(pronostico=vuoto)])
                self.assertNotIn("sg-pastiglia", corpo(html))
                self.assertEqual("", righe_da_html(html)[0]["Pronostico"])


class TestPartiteGiaGiocate(unittest.TestCase):
    """Le partite concluse stanno come prima: il risultato al posto delle quote."""

    def test_risultato_senza_probabilita(self):
        html = sgr.html_tabella_partite(
            [_riga(uno=None, x=None, due=None, pronostico="", risultato="2-1")])
        celle = righe_da_html(html)[0]
        self.assertEqual("2-1", celle["Risultato"])
        self.assertEqual(("", "", ""), (celle["1"], celle["X"], celle["2"]))
        self.assertEqual("", celle["Pronostico"])
        self.assertIn('<span class="sg-risultato">2-1</span>', html)

    def test_partita_da_giocare_senza_risultato(self):
        celle = righe_da_html(sgr.html_tabella_partite([_riga(risultato="")]))[0]
        self.assertEqual("", celle["Risultato"])


class TestTema(unittest.TestCase):
    """Stessa palette della scheda partita: chiaro e scuro, con la ricaduta."""

    def test_chiaro_e_scuro_cambiano_i_colori(self):
        chiaro = sgr.html_tabella_partite([_riga()], tema="chiaro")
        scuro = sgr.html_tabella_partite([_riga()], tema="scuro")
        self.assertIn(f"--sg-sfondo: {sgr.PALETTE['chiaro']['sfondo']}", chiaro)
        self.assertIn(f"--sg-sfondo: {sgr.PALETTE['scuro']['sfondo']}", scuro)
        self.assertNotEqual(chiaro, scuro)
        # I colori degli esiti non cambiano col tema: sono fissi per esito.
        for html in (chiaro, scuro):
            for colore in sgr.COLORI_ESITI.values():
                self.assertIn(f"background:{colore}", html)

    def test_tema_sconosciuto_ricade_sul_chiaro(self):
        self.assertEqual(sgr.html_tabella_partite([_riga()], tema="chiaro"),
                         sgr.html_tabella_partite([_riga()], tema="fucsia"))

    def test_le_classi_sono_quelle_della_scheda(self):
        html = sgr.html_tabella_partite([_riga()])
        for classe in ('class="sg sg-tabella-partite"', 'class="sg-tabella"',
                       'class="sg-th', 'class="sg-td', 'class="sg-riempimento"',
                       'class="sg-traccia sg-traccia-cella"'):
            with self.subTest(classe=classe):
                self.assertIn(classe, html)


class TestSelettoreDellaScheda(unittest.TestCase):
    """Le due funzioni pure del selettore: le voci e la riga scelta.

    Il selettore prende le voci dalla STESSA lista di righe che disegna la
    tabella (ordine compreso), e il pulsante «Apri» ritrova la riga dal nome:
    qui si prova che il giro nome -> riga non perda niente e non inventi.
    """

    def test_le_voci_sono_le_partite_nell_ordine_della_tabella(self):
        import app as app_mod
        righe = [_riga(partita="Inter - Roma", quando="sab 10/10, 20:45"),
                 _riga(partita="Atalanta - Lazio", quando="dom 11/10, 15:00")]
        self.assertEqual(["Inter - Roma", "Atalanta - Lazio"],
                         app_mod.opzioni_scheda_partita(righe))
        self.assertEqual(["Inter - Roma", "Atalanta - Lazio"],
                         [r["Partita"] for r in righe_da_html(
                             sgr.html_tabella_partite(righe))])
        self.assertEqual([], app_mod.opzioni_scheda_partita([]))
        self.assertEqual([], app_mod.opzioni_scheda_partita(None))

    def test_una_riga_senza_nome_non_diventa_una_voce(self):
        import app as app_mod
        righe = [_riga(partita="  "), _riga(partita=None, quando="x"),
                 _riga(partita="Inter - Roma")]
        self.assertEqual(["Inter - Roma"], app_mod.opzioni_scheda_partita(righe))

    def test_la_riga_scelta_si_ritrova_dal_nome(self):
        import app as app_mod
        prima = _riga(partita="Inter - Roma")
        seconda = _riga(partita="Atalanta - Lazio")
        righe = [prima, seconda]
        self.assertIs(seconda, app_mod.riga_scelta_partita(righe, "Atalanta - Lazio"))
        self.assertIs(prima, app_mod.riga_scelta_partita(righe, "Inter - Roma"))
        self.assertIsNone(app_mod.riga_scelta_partita(righe, "Milan - Napoli"))
        self.assertIsNone(app_mod.riga_scelta_partita(righe, None))
        self.assertIsNone(app_mod.riga_scelta_partita([], "Inter - Roma"))

    def test_la_riga_scelta_porta_con_se_la_richiesta_della_scheda(self):
        """Il pulsante apre la partita della riga: lega, casa, trasferta, quando."""
        import app as app_mod
        riga = _riga(partita="Inter - Roma")
        riga["scheda"] = {"lega": "Serie A", "casa": "Inter", "trasferta": "Roma",
                          "kickoff_utc": "2026-10-10T18:45:00Z", "giornata": 8}
        scelta = app_mod.riga_scelta_partita([riga], "Inter - Roma")
        self.assertEqual({"lega": "Serie A", "casa": "Inter",
                          "trasferta": "Roma",
                          "kickoff_utc": "2026-10-10T18:45:00Z",
                          "giornata": 8}, scelta["scheda"])
        # Una riga senza la chiave non fa esplodere il pulsante.
        self.assertEqual({}, (_riga().get("scheda") or {}))


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
