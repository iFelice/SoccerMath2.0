"""REGOLA (presentazione dopo la PR #65, dopo la rimozione degli spoiler e dopo
l'uscita della colonna «Modello %»): nelle tabelle IN VISTA delle schede
Pronostici/Pareggi e della scheda Multiple, e nella tabella Mercato del Registro

* la giocata e' la SOLA sigla (1, X, 2, 1X, X2, 12): niente «Vince <squadra>»,
  «<squadra> non perde», «Non finisce in pareggio», niente sigla fra parentesi;
* al posto di «Riesce circa» c'e' «Quote %» (probabilita' dalle quote), e
  NIENT'ALTRO: le tabelle del periodo (Pronostici, Pareggi, «Le più
  probabili») non hanno piu' la colonna «Modello %». La probabilita' del
  modello Drago resta nella scheda partita e nei Dettagli tecnici, e le sue
  funzioni (``numero_modello_percento``, ``prob_modello_esito``) restano
  provate qui sotto: e' la REGOLA che non si e' persa, non la colonna;
* «Quote %» e' SEMPRE NUMERICA nel DataFrame e diventa una
  ``st.column_config.ProgressColumn`` (0-100, passo 0,1, ``format="localized"``):
  l'ordinamento al clic e' numerico e la barra si legge a colpo d'occhio. Dove
  il numero non c'e' (righe solo gol) il valore e' ``NaN`` — la cella vuota,
  non una stringa vuota e non un ripiego su TextColumn (verificato su
  Streamlit 1.66);
* la colonna «Il nostro modello è d'accordo» esce dalla vista: il campo resta
  nei dati, nel Registro e nei Dettagli (nessuna logica cambia);
* l'ordine predefinito e' «Quote %» DECRESCENTE, con le righe solo gol in fondo.

Nessuna asserzione numerica dei test precedenti cambia: qui si provano le
funzioni di presentazione (pure), i numeri passano intatti.
"""
from __future__ import annotations

import ast
import inspect
import os
import sys
import unittest
from datetime import datetime

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import app  # noqa: E402
import lista_giocate as lg  # noqa: E402
import prediction_registry as pr  # noqa: E402


def _riga_mercato(prob=0.675, esito="1", home="Inter", away="Roma",
                  prob_modello_val=60.0, lega="Serie A",
                  utc="2026-10-17T18:45:00Z"):
    """Riga come la produce ``seleziona_riga_top_mix_mercato`` (stessi campi)."""
    return {
        "league": lega, "giornata": 8, "home": home, "away": away,
        "match_id": f"{home}-{away}", "utcDate": utc, "kickoff_utc": utc,
        "market": f"Vittoria {home}" if esito == "1" else "Pareggio" if esito == "X" else f"Vittoria {away}",
        "mercato_standard": esito, "esito": esito,
        "prob": prob, "prob_val": round(prob * 100.0, 1),
        "quota": 1.65, "prob_modello": prob_modello_val / 100.0,
        "prob_modello_val": prob_modello_val, "accordo": False,
        "fonte": "pinnacle", "n_libri": 1, "rank": None,
    }


def _riga_solo_gol(home="Hamburger SV", away="Bayern Munich"):
    """Una riga che esiste SOLO per i gol (nessuna scelta 1X2): «Quote %» manca.

    E' la riga che prima faceva diventare di testo tutta la colonna: adesso il
    suo «Quote %» e' ``None`` nella riga e ``NaN`` nel DataFrame.
    """
    riga = _riga_mercato(prob=0.62, esito="", home=home, away=away)
    riga.update({"solo_ou": True, "esito": "", "mercato_standard": "",
                 "totals": {"pronostico": "Over", "p_over": 0.62, "p_under": 0.38}})
    return riga


def _terna_snapshot():
    """La terna 1X2 del modello per UNA partita, come dal giro del modello.

    Shape identica alle ``letture`` di ``fetch_and_calc_top_mix``: per ogni
    esito la probabilita' del Drago (percentuale, arrotondata come nel
    Registro). Le due probabilita' della doppia chance sommate dal test
    appartengono a QUESTO stesso snapshot.
    """
    return [{
        "home": "Inter", "away": "Roma",
        "per_esito": {
            "1": {"prob_modello": 41.2},
            "X": {"prob_modello": 27.5},
            "2": {"prob_modello": 31.3},
        },
    }]


def _tabella_periodo(righe, adesso=None, stato_confronto=None, mappa_modello_1x2=None):
    """Le righe del selettore passano dalla normalizzazione della scheda Pronostici.

    E' il percorso reale: ``riga_pronostico_da_mercato`` + ``tabella_pronostici_visibile``.
    """
    normalizzate = [app.riga_pronostico_da_mercato(r, adesso, stato_confronto,
                                                  mappa_modello_1x2)
                    for r in righe]
    df, _ordinate = app.tabella_pronostici_visibile(normalizzate)
    return df


class TestTabellaScelteSecondoLeQuote(unittest.TestCase):
    """«Le scelte più sicure secondo le quote»: la tabella della scheda Pronostici.

    Le colonne del punto 2 della commessa schede, senza «Modello %»: Quando,
    Partita, Pronostico, Quote %, Quota. «Campionato» esce dalla vista (la lega
    non e' una colonna, e dentro «Partita» non c'e' altra scritta che le due
    squadre), la sigla si chiama «Pronostico» e la quota bet365 stimata torna in
    tabella. I numeri restano quelli di prima: qui cambia come si leggono, non
    cosa si calcola.
    """

    def test_colonne_sigla_e_niente_accordo(self):
        righe = [_riga_mercato(prob=0.66, esito="1"), _riga_mercato(prob=0.58, esito="X",
                                                                    home="Milan", away="Lazio")]
        df = _tabella_periodo(righe, stato_confronto="pronto", mappa_modello_1x2={})
        self.assertEqual(["Quando", "Partita", "Pronostico", "Quote %",
                          "Quota", "Gol", "Insieme %"], list(df.columns))
        self.assertNotIn("Modello %", df.columns,
                         "la probabilita' del modello sta nella scheda partita e "
                         "nei Dettagli tecnici, non in questa tabella")
        self.assertNotIn("Riesce circa", df.columns)
        self.assertNotIn("Campionato", df.columns,
                         "il campionato non e' una colonna: la vista e' asciutta")
        self.assertFalse(any("d'accordo" in str(c) for c in df.columns),
                         "la colonna del segnale d'accordo esce dalla vista")
        for valore in df["Pronostico"]:
            self.assertIn(valore, {"1", "X", "2", "1X", "X2", "12"},
                          f"il pronostico in vista e' la sola sigla, non {valore!r}")
        for vietato in ("Vince", "non perde", "Non finisce in pareggio", "("):
            for valore in df["Pronostico"]:
                self.assertNotIn(vietato, valore)
        self.assertEqual(["Inter - Roma", "Milan - Lazio"], df["Partita"].tolist(),
                         "«Partita» e' casa - trasferta e nient'altro")

    def test_nessuna_scritta_dentro_partita(self):
        """Il marcatore delle quote provvisorie sta in «Quando», non in «Partita»."""
        lontana = _riga_mercato(prob=0.66, esito="1",
                                utc="2026-12-19T18:45:00Z")   # oltre 3 giorni dal fixture
        df = _tabella_periodo([lontana], adesso=datetime(2026, 10, 16, 16, 0))
        self.assertEqual("Inter - Roma", df["Partita"].iloc[0])
        self.assertIn("⏳", df["Quando"].iloc[0])
        prossimo = _riga_mercato(prob=0.66, esito="1", utc="2026-10-17T18:45:00Z")
        df2 = _tabella_periodo([prossimo], adesso=datetime(2026, 10, 16, 16, 0))
        self.assertNotIn("⏳", df2["Quando"].iloc[0],
                         "a due giorni dal fischio le quote non sono piu' provvisorie")

    def test_quando_giorno_breve_data_e_ora_italiana(self):
        self.assertEqual("sab 17/10, 20:45",
                         app._quando_breve("2026-10-17T18:45:00Z"),
                         "giorno in tre lettere, data corta, ora Europe/Rome")
        self.assertEqual("dom 18/10, 20:45 ⏳",
                         app._quando_breve("2026-10-18T18:45:00Z", lontana=True))
        self.assertEqual("", app._quando_breve(None))
        self.assertEqual("⏳", app._quando_breve("non una data", lontana=True),
                         "data non letta: niente da inventare, resta il marcatore")

    def test_quote_percento_numerica_e_ordine_decrescente(self):
        righe = [_riga_mercato(prob=0.58, home="A", away="B"),
                 _riga_mercato(prob=0.71, home="C", away="D"),
                 _riga_mercato(prob=0.649, home="E", away="F")]
        df = _tabella_periodo(righe)
        self.assertTrue(pd.api.types.is_numeric_dtype(df["Quote %"]),
                        "«Quote %» resta numerica: il clic sull'intestazione ordina per valore")
        valori = df["Quote %"].tolist()
        self.assertEqual(valori, sorted(valori, reverse=True),
                         "l'ordine predefinito e' «Quote %» decrescente")
        self.assertEqual([71.0, 64.9, 58.0], valori, "una cifra decimale")

    def test_nessuna_colonna_modello_nella_vista(self):
        """«Modello %» esce dalla tabella, anche col giro del modello PRONTO.

        La probabilita' del modello resta nella scheda partita e nei Dettagli
        tecnici: qui non c'e' la colonna, in nessuno stato del confronto.
        """
        mappa = app.prob_modello_1x2_per_partita(_terna_snapshot())
        righe = [_riga_mercato(esito="1")]
        for stato, m in ((None, None), ("in_calcolo", None),
                         ("non_disponibile", None), ("pronto", {}),
                         ("pronto", mappa)):
            with self.subTest(stato=stato):
                df = _tabella_periodo(righe, stato_confronto=stato, mappa_modello_1x2=m)
                self.assertNotIn("Modello %", df.columns)
                self.assertEqual(list(app.COLONNE_PRONOSTICI)[:5], list(df.columns)[:5])

    def test_quote_percento_numerica_anche_con_una_riga_senza_numero(self):
        """La riga solo gol non fa diventare la colonna di testo: e' ``NaN``.

        E' la richiesta della ProgressColumn: la colonna resta numerica (barra,
        ordinamento per valore) e la cella senza numero e' un valore mancante,
        non una stringa vuota e non una TextColumn di ripiego.
        """
        righe = [_riga_mercato(prob=0.66, esito="1", home="Inter", away="Roma"),
                 _riga_solo_gol(home="Hamburger SV", away="Bayern Munich")]
        df = _tabella_periodo(righe)
        self.assertTrue(pd.api.types.is_numeric_dtype(df["Quote %"]),
                        "«Quote %» resta numerica anche con una riga solo gol")
        self.assertEqual([66.0], [v for v in df["Quote %"] if not pd.isna(v)],
                         "la riga con 1X2 tiene il suo numero, una cifra decimale")
        self.assertEqual("Hamburger SV - Bayern Munich", df["Partita"].tolist()[-1],
                         "la riga solo gol va in fondo (NaN in coda)")
        self.assertTrue(pd.isna(df["Quote %"].iloc[-1]),
                        "riga solo gol: NaN, non una stringa vuota")
        # e nessuna cella di testo rende un non-numero scritto: in «Quote %» il
        # NaN e' il valore mancante voluto (la ProgressColumn lo disegna come
        # cella vuota), non una scritta.
        for colonna in df.columns:
            for cella in df[colonna]:
                if pd.isna(cella):
                    self.assertEqual("Quote %", colonna,
                                     f"{colonna}: un valore mancante qui sarebbe «None»")
                    continue
                self.assertNotIn(str(cella).strip().lower(), ("nan", "none", "nat"),
                                 f"{colonna}: nessuna cella rende un non-numero")

    def test_config_quote_percento_e_una_progress_column(self):
        """La colonna in vista e' una barra 0-100, non un numero o un testo."""
        config = app._config_colonne_pronostici()
        self.assertNotIn("Modello %", config,
                         "«Modello %» non e' piu' una colonna di queste tabelle")
        quote = config["Quote %"]
        self.assertEqual("progress", quote["type_config"]["type"])
        self.assertEqual(0, quote["type_config"]["min_value"])
        self.assertEqual(100, quote["type_config"]["max_value"])
        self.assertEqual(0.1, quote["type_config"]["step"])
        self.assertEqual("localized", quote["type_config"]["format"])
        # «Quota» resta testo gia' formattato (due decimali con la virgola).
        self.assertEqual("text", config["Quota"]["type_config"]["type"])

    def test_mostra_tabella_periodo_non_ripiega_su_textcolumn(self):
        """``_mostra_tabella_periodo`` passa la config cosi' com'e'.

        Il vecchio ripiego (colonna non numerica -> TextColumn) e' uscito: il
        DataFrame e' numerico per costruzione e la barra resta una barra.
        """
        from unittest import mock
        righe = app.tabella_piu_probabili(
            [{"match_id": "1", "partita": "Inter vs Roma", "home": "Inter",
              "away": "Roma", "lega": "Serie A", "giocata": "1", "esito": "1",
              "probabilita": 0.66, "quota_b365_stimata": 1.45,
              "commence_time": "2026-10-17T18:45:00Z"}], 1.0)
        finto_st = mock.MagicMock()
        # ``column_config`` VERO: la configurazione disegnata deve essere quella
        # di Streamlit, non un doppio che accetta qualunque attributo.
        finto_st.column_config = app.st.column_config
        with mock.patch.object(app, "st", finto_st):
            app._mostra_tabella_periodo(righe, "chiave_finta")
        config = finto_st.dataframe.call_args.kwargs["column_config"]
        self.assertEqual("progress", config["Quote %"]["type_config"]["type"])
        df = finto_st.dataframe.call_args.args[0]
        self.assertTrue(pd.api.types.is_numeric_dtype(df["Quote %"]))

    def test_quota_colonna_testo_con_due_decimali(self):
        """«Quota» e' la stima bet365 della probabilita' di mercato, non il prezzo
        del bookmaker: due decimali con la virgola, vuota se il numero non c'e'."""
        df = _tabella_periodo([_riga_mercato(prob=0.675, esito="1")])
        quota = df["Quota"].iloc[0]
        self.assertFalse(pd.api.types.is_numeric_dtype(df["Quota"]),
                         "anche «Quota» e' testo: nessuna cella rende NaN")
        self.assertRegex(str(quota), r"^\d+,\d{2}$")
        self.assertAlmostEqual(app.quota_b365_stimata(0.675, "Serie A"), float(quota.replace(",", ".")),
                               msg="la colonna legge la stima del progetto, non un prezzo altrui")
        # e la cella di una riga senza quota e' vuota, non "None"
        df2 = _tabella_periodo([_riga_mercato(prob=1.0, esito="1")])
        self.assertEqual([""], df2["Quota"].tolist())

    def test_quota_mancante_cella_vuota(self):
        self.assertIsNone(app.quota_b365_stimata(None, "Serie A"))
        self.assertIsNone(app.quota_b365_stimata(0.0, "Serie A"))
        self.assertIsNone(app.quota_b365_stimata(1.0, "Serie A"))
        self.assertIsNone(app.quota_b365_stimata("x", "Serie A"))
        self.assertIsNone(app.quota_b365_stimata(True, "Serie A"))
        # la stessa stima, data come percentuale: non e' una quota da 1,4 a zero
        self.assertEqual(app.quota_b365_stimata(0.675, "Serie A"),
                         app.quota_b365_stimata(67.5, "Serie A"))

    def test_righe_ordinate_seguono_il_dataframe(self):
        """Il clic sulla riga N deve leggere la partita della riga N: la lista
        normalizzata e il DataFrame hanno lo STESSO ordine."""
        righe = [_riga_mercato(prob=0.58, home="A", away="B"),
                 _riga_mercato(prob=0.71, home="C", away="D"),
                 _riga_mercato(prob=0.649, home="E", away="F")]
        normalizzate = [app.riga_pronostico_da_mercato(r) for r in righe]
        df, ordinate = app.tabella_pronostici_visibile(normalizzate)
        self.assertEqual(len(df), len(ordinate))
        self.assertEqual(df["Partita"].tolist(), [r["Partita"] for r in ordinate])
        self.assertEqual(["C - D", "E - F", "A - B"], [r["Partita"] for r in ordinate])
        self.assertEqual("C - D", ordinate[0]["scheda"]["nome"])
        self.assertEqual("C", ordinate[0]["scheda"]["casa"],
                         "la richiesta di scheda viaggia con la sua riga")

    def test_tabella_vuota_non_inventa_righe(self):
        for righe in ([], None, ["non un dict", 3]):
            df, ordinate = app.tabella_pronostici_visibile(righe)
            self.assertEqual([], list(ordinate))
            self.assertEqual(app.COLONNE_PRONOSTICI, list(df.columns))
            self.assertTrue(df.empty)


class TestCaptionScelteSecondoLeQuote(unittest.TestCase):
    """La caption della sezione sono DUE fatti e basta: quante partite sono in
    tabella e quante ne restano fuori perche' giocano dopo il lunedì. Niente
    stato del modello (la colonna vuota lo dice da sola), niente indicazioni su
    dove sta l'interruttore (sta sopra le schede), nessun conteggio del segnale
    "d'accordo" — quello resta nei Dettagli."""

    def test_caption_solo_le_partite(self):
        # Una frase sola, col punto, e null'altro: lo stato del modello non c'e'.
        for n in (18, 5, 1):
            self.assertEqual(f"{n} partite in tabella.",
                             app.caption_scelte_secondo_le_quote(n), n)

    def test_caption_nei_prossimi_giorni(self):
        self.assertEqual("11 partite in tabella. Altre 7 nei prossimi giorni.",
                         app.caption_scelte_secondo_le_quote(11, nascoste=7))

    def test_caption_non_rimanda_ad_altre_schede(self):
        frase = app.caption_scelte_secondo_le_quote(11, nascoste=7)
        for vietato in ("Multiple", "scheda", "Accendi", app.ETICHETTA_PROSSIMI_GIORNI):
            self.assertNotIn(vietato, frase, f"{vietato!r}: l'interruttore sta sopra le schede")

    def test_caption_non_parla_del_modello(self):
        for n, nascoste in ((18, 0), (9, 2)):
            frase = app.caption_scelte_secondo_le_quote(n, nascoste=nascoste)
            self.assertNotIn("Modello", frase,
                             "lo stato della colonna non si dichiara in caption")
            self.assertNotIn("d'accordo", frase)
            self.assertNotIn("senza confronto", frase)


class TestModelloDoppiaChanceSomma(unittest.TestCase):
    """«Modello %» di una doppia chance = somma delle due probabilita' 1X2
    del modello SULLO STESSO SNAPSHOT (le letture dello stesso giro)."""

    def test_somma_delle_due_probabilita_1x2(self):
        terna = {"1": 41.2, "X": 27.5, "2": 31.3}
        self.assertEqual(68.7, app.prob_modello_esito("1X", terna))
        self.assertEqual(58.8, app.prob_modello_esito("X2", terna))
        self.assertEqual(72.5, app.prob_modello_esito("12", terna))
        # singole: lettura diretta, nessun ricalcolo
        self.assertEqual(41.2, app.prob_modello_esito("1", terna))
        self.assertEqual(27.5, app.prob_modello_esito("X", terna))
        self.assertEqual(31.3, app.prob_modello_esito("2", terna))

    def test_numero_mancante_non_inventato(self):
        terna = {"1": 41.2, "X": 27.5}          # il modello non copre l'esito 2
        self.assertEqual(68.7, app.prob_modello_esito("1X", terna))
        self.assertIsNone(app.prob_modello_esito("X2", terna))
        self.assertIsNone(app.prob_modello_esito("12", terna))
        self.assertIsNone(app.prob_modello_esito("2", terna))
        self.assertIsNone(app.prob_modello_esito("1X", {}))
        self.assertIsNone(app.prob_modello_esito("1X", None))
        self.assertIsNone(app.prob_modello_esito("", {"1": 1.0}))

    def test_dal_giro_del_modello_alla_colonna_stesso_snapshot(self):
        mappa = app.prob_modello_1x2_per_partita(_terna_snapshot())
        self.assertEqual({("Inter", "Roma")}, set(mappa))
        terna = mappa[("Inter", "Roma")]
        # le due probabilita' sommate sono le STESSE due voci 1X2 dello snapshot
        self.assertEqual({"1", "X", "2"}, set(terna))
        self.assertEqual((41.2, 27.5, 31.3), (terna["1"], terna["X"], terna["2"]))
        self.assertEqual(41.2 + 27.5, app.prob_modello_esito("1X", terna))
        riga = _riga_mercato(esito="1X", prob=0.687)
        self.assertEqual(68.7, app.numero_modello_percento(riga, "pronto", mappa),
                         "la somma delle due probabilita' 1X2, come numero")


class TestLePiuProbabili(unittest.TestCase):
    """Le righe di «Le più probabili»: sigla, una percentuale, ordine decrescente.

    Da questa PR la tabella e' quella delle schede Pronostici e Pareggi
    (``tabella_piu_probabili`` -> ``riga_pronostico_da_giocata`` ->
    ``tabella_pronostici_visibile``): cinque colonne (piu' «Pronostico partita»
    quando c'e'), «Pronostico» al posto di «Giocata», «Quota» al posto di «Paga
    circa». I NUMERI attesi sono gli stessi di prima: 71,2 e 67,5 in «Quote %»,
    numerica; nessuna colonna «Modello %».
    """

    def _tabella(self, **kw):
        # ``quota_min`` 1.0: tutte e due le giocate restano (1,52 e 1,41).
        return app.tabella_pronostici_visibile(
            app.tabella_piu_probabili(self._giocata(), 1.0, **kw))[0]

    def _giocata(self):
        return [
            {"match_id": "1", "partita": "Inter vs Roma", "home": "Inter", "away": "Roma",
             "lega": "Serie A", "giocata": "1X", "esito": "1X", "probabilita": 0.675,
             "quota_b365_stimata": 1.52, "commence_time": "2026-10-17T18:45:00Z"},
            {"match_id": "2", "partita": "Milan vs Lazio", "home": "Milan", "away": "Lazio",
             "lega": "Serie A", "giocata": "1", "esito": "1", "probabilita": 0.712,
             "quota_b365_stimata": 1.41, "commence_time": "2026-10-18T20:45:00Z"},
        ]

    def test_sigla_percentuali_e_ordine(self):
        mappa = app.prob_modello_1x2_per_partita(_terna_snapshot())
        df = self._tabella(adesso=None, stato_confronto="pronto", mappa_modello_1x2=mappa)
        self.assertEqual(app.COLONNE_PRONOSTICI, list(df.columns))
        self.assertNotIn("Modello %", df.columns)
        self.assertEqual(["1", "1X"], df["Pronostico"].tolist(),
                         "la sigla secca, anche per le doppie chance, in ordine decrescente")
        # «Partita» senza testo aggiunto, «Quota» con la virgola italiana.
        self.assertEqual(["Milan - Lazio", "Inter - Roma"], df["Partita"].tolist())
        self.assertEqual(["1,41", "1,52"], df["Quota"].tolist())
        self.assertTrue(pd.api.types.is_numeric_dtype(df["Quote %"]))
        self.assertEqual([71.2, 67.5], df["Quote %"].tolist(),
                         "ordine «Quote %» decrescente, una cifra decimale")

    def test_quote_percento_tutte_numeriche(self):
        """Una giocata 1X2 per riga: nessun valore mancante, colonna numerica.

        Le righe solo gol (con ``NaN`` in «Quote %») le porta la tabella della
        scheda Pronostici/Pareggi, provata sopra; qui si verifica che la stessa
        colonna resti numerica anche in «Le più probabili».
        """
        df = self._tabella()
        self.assertTrue(pd.api.types.is_numeric_dtype(df["Quote %"]))
        self.assertFalse(df["Quote %"].isna().any(),
                         "ogni giocata 1X2 ha la sua probabilita'")
        self.assertEqual([71.2, 67.5], df["Quote %"].tolist())

    def test_una_riga_per_partita_sopra_la_quota_minima(self):
        """«Paga almeno» filtra come prima (``lg.migliori_giocate_per_partita``):
        con 1,50 resta la sola giocata che paga almeno 1,50."""
        righe = app.tabella_piu_probabili(self._giocata(), 1.50)
        self.assertEqual(["Inter - Roma"], [r["Partita"] for r in righe])
        self.assertEqual([67.5], [r["Quote %"] for r in righe])


class TestPerRaddoppiare(unittest.TestCase):
    """La tabella «Per raddoppiare» (nei Dettagli): ogni partita «<casa> - <trasferta>: <sigla>»,
    «Quote %» numerica al posto di «Riesce circa», niente «Modello %»."""

    def test_riga_partita_sigla(self):
        g = {"home": "Inter", "away": "Roma", "giocata": "1X"}
        self.assertEqual("Inter - Roma: 1X", app.riga_partita_sigla(g))
        self.assertEqual("? - Roma: 1", app.riga_partita_sigla({"away": "Roma", "giocata": "1"}))

    def test_tabella_riquadro(self):
        best_by_k = {
            2: {"giocate": [
                {"home": "Inter", "away": "Roma", "giocata": "1", "probabilita": 0.675},
                {"home": "Milan", "away": "Lazio", "giocata": "X2", "probabilita": 0.58},
            ], "probabilita": 0.675 * 0.58, "quota_totale": 2.35},
            1: {"giocate": [
                {"home": "Napoli", "away": "Torino", "giocata": "1", "probabilita": 0.71},
            ], "probabilita": 0.71, "quota_totale": 1.45},
        }
        righe = lg.righe_riquadro_raddoppio(best_by_k, istante=None)
        df = app.tabella_per_raddoppiare_visibile(righe, best_by_k)
        self.assertEqual(["★", "Partite", "Quote %", "Paga circa",
                          "Su 100 € giocati tornano in media"], list(df.columns))
        self.assertNotIn("Riesce circa", df.columns)
        self.assertNotIn("Modello %", df.columns,
                         "nel riquadro niente «Modello %»: la probabilita' e' combinata")
        self.assertTrue(pd.api.types.is_numeric_dtype(df["Quote %"]))
        self.assertEqual(df["Quote %"].tolist(), sorted(df["Quote %"].tolist(), reverse=True),
                         "ordine predefinito «Quote %» decrescente")
        partite_k1 = df[df["Partite"].str.contains("Napoli")]["Partite"].iloc[0]
        self.assertEqual("Napoli - Torino: 1", partite_k1)
        partite_k2 = df[df["Partite"].str.contains("Milan")]["Partite"].iloc[0]
        self.assertIn("Inter - Roma: 1", partite_k2)
        self.assertIn("Milan - Lazio: X2", partite_k2)
        # la stella segue la riga con la probabilita' piu' alta (k=1 qui)
        stella = df[df["★"] == "★"]["Partite"].iloc[0]
        self.assertIn("Napoli", stella)
        # «Paga circa» e il ritorno su 100 restano come erano
        self.assertTrue(df["Paga circa"].str.endswith("volte la puntata").all())


class TestTabellaMercatoComEAndata(unittest.TestCase):
    """La tabella Mercato di «Com'è andata»: sigle, percentuali della PRIMA
    registrazione, niente colonna «d'accordo», ordini richiesti."""

    def _df(self):
        righe = [
            {"data": datetime(2026, 10, 12, 20, 45), "campionato": "Serie A",
             "home": "Inter", "away": "Roma", "mercato_standard": "1",
             "prob_sicuro": 62.5, pr.PROB_MERCATO_PRIMA_FIELD: 0.625,
             pr.PROB_MODELLO_PRIMA_FIELD: 63.0, "risultato_reale": "2-0", "esito": "✅"},
            {"data": datetime(2026, 10, 11, 15, 0), "campionato": "Liga",
             "home": "Como", "away": "Torino", "mercato_standard": "X2",
             "prob_sicuro": 58.0, pr.PROB_MERCATO_PRIMA_FIELD: 0.58,
             pr.PROB_MODELLO_PRIMA_FIELD: 51.0, "risultato_reale": "1-1", "esito": "❌"},
            {"data": datetime(2026, 10, 18, 20, 45), "campionato": "Serie A",
             "home": "Milan", "away": "Lazio", "mercato_standard": "1",
             "prob_sicuro": 64.0, pr.PROB_MERCATO_PRIMA_FIELD: None,
             pr.PROB_MODELLO_PRIMA_FIELD: None, "risultato_reale": None, "esito": ""},
        ]
        return pd.DataFrame(righe)

    def test_colonne_sigla_e_percentuali_prima_registrazione(self):
        df = app._tabella_registro_mercato_visibile(self._df())
        self.assertEqual(["Quando", "Campionato", "Partita", "Giocata", "Quote %",
                          "Modello %", "Risultato", "Esito"], list(df.columns))
        self.assertNotIn("Riesce circa", df.columns)
        self.assertFalse(any("d'accordo" in str(c) for c in df.columns))
        self.assertEqual(["1", "X2", "1"], df["Giocata"].tolist(),
                         "la sola sigla, anche per le doppie chance")
        # «Quote %» e «Modello %» = PRIMA registrazione (prob_mercato_prima e
        # prob_modello_prima della riga), non il valore attuale. La terza riga
        # senza *_prima ha la prima ricostruita dall'attuale (64,0, la cella
        # mostra quel numero); «Modello %» senza campo resta vuota.
        # «Quote %» e' TESTO (virgola italiana, simbolo %): la colonna puo'
        # avere una cella vuota e una NumberColumn la renderebbe «None».
        self.assertFalse(pd.api.types.is_numeric_dtype(df["Quote %"]))
        self.assertEqual(["62,5%", "58,0%", "64,0%"], df["Quote %"].tolist())
        self.assertEqual(["63,0", "51,0", ""], df["Modello %"].tolist(),
                         "virgola italiana come nelle altre tabelle; senza campo "
                         "*_prima la cella resta vuota, nessun numero inventato")
        self.assertEqual("", df["Risultato"].iloc[2],
                         'la riga da giocare non scrive "None" nel risultato')
        self.assertEqual("", df["Esito"].iloc[2])

    def test_prima_registrazione_ricostruita_dichiarata_dai_numeri(self):
        # Riga vecchia scritta PRIMA che i campi *_prima esistessero: il campo
        # manca del tutto, la prima e' ricostruita dall'attuale
        # (``prob_di_registrazione``) e la cella mostra quel numero.
        vecchia = {"data": datetime(2026, 10, 5, 20, 45), "campionato": "Liga",
                   "home": "Getafe", "away": "Osasuna", "mercato_standard": "12",
                   "prob_sicuro": 57.0, "risultato_reale": "0-0", "esito": "❌"}
        df = pd.DataFrame([vecchia])
        out = app._tabella_registro_mercato_visibile(df)
        self.assertEqual("57,0%", out["Quote %"].iloc[0])
        self.assertEqual("", out["Modello %"].iloc[0])

    def test_concluse_per_data_decrescente(self):
        df = self._df()
        concluse = df[df["esito"].isin(["✅", "❌"])]
        # ordine di arrivo invertito: l'ordinamento del render deve tenerlo
        concluse = concluse.iloc[::-1]
        ordinato = app.ordina_righe_mercato_concluse(concluse)
        date = ordinato["data"].tolist()
        self.assertEqual(date, sorted(date, reverse=True))

    def test_in_attesa_per_quote_percento_decrescente(self):
        records = [
            {"home": "A", "away": "B", "prob_sicuro": 58.0,
             pr.PROB_MERCATO_PRIMA_FIELD: 0.58, "esito": ""},
            {"home": "C", "away": "D", "prob_sicuro": 66.0,
             pr.PROB_MERCATO_PRIMA_FIELD: 0.66, "esito": ""},
            {"home": "E", "away": "F", "prob_sicuro": 61.0,
             pr.PROB_MERCATO_PRIMA_FIELD: None, "esito": ""},   # prima ricostruita
            {"home": "G", "away": "H", "prob_sicuro": None,
             pr.PROB_MERCATO_PRIMA_FIELD: None, "esito": ""},   # nessun numero
        ]
        ordinati = app.ordina_righe_mercato_in_attesa(list(reversed(records)))
        quote = [app.percento_prima_registrazione(r) for r in ordinati]
        numeri = [q for q in quote if q is not None]
        self.assertEqual(numeri, sorted(numeri, reverse=True),
                         "«Quote %» decrescente: prima le scelte piu' probabili")
        self.assertIsNone(quote[-1], "le righe senza probabilita' leggibile vanno in coda")
        self.assertEqual(["C", "E", "A", "G"], [r["home"] for r in ordinati])


class TestLeFunzioniInParoleRestano(unittest.TestCase):
    """``giocata_in_parole`` / ``giocata_in_parole_con_sigla`` restano nel
    modulo (test e altri usi), ma non sono piu' chiamate dalle tabelle."""

    def test_le_funzioni_esistono_e_non_cambiano(self):
        self.assertEqual("Vince Inter", lg.giocata_in_parole("1", "Inter", "Roma"))
        self.assertEqual("Inter non perde", lg.giocata_in_parole("1X", "Inter", "Roma"))
        self.assertEqual("Vince Inter (1)",
                         lg.giocata_in_parole_con_sigla("1", "Inter", "Roma"))

    def test_le_tabelle_non_chiamano_giu_le_parole(self):
        """Codice (docstring esclusi) delle quattro tabelle: nessuna traduzione
        in parole, nessun «Riesce circa», nessuna colonna del segnale."""
        import ast
        for nome in ("tabella_pronostici_visibile", "riga_pronostico_da_mercato",
                     "riga_pronostico_da_giocata", "tabella_piu_probabili",
                     "riquadri_multiple",
                     "tabella_per_raddoppiare_visibile", "_tabella_registro_mercato_visibile"):
            fn = getattr(app, nome)
            albero = ast.parse(inspect.getsource(fn))
            nodi = [n for n in ast.walk(albero)
                    if isinstance(n, (ast.Name, ast.Attribute, ast.Constant))
                    and not (isinstance(n, ast.Constant) and not isinstance(n.value, str))]
            testo = " ".join(
                (n.id if isinstance(n, ast.Name) else
                 n.attr if isinstance(n, ast.Attribute) else n.value)
                for n in nodi)
            for vietato in ("giocata_in_parole", "riesce_circa", "Riesce circa",
                            "Il nostro modello è d'accordo"):
                self.assertNotIn(vietato, testo,
                                 f"{nome}: la presentazione in parole e' uscita dalla vista")


class TestDicitureProvaLaTuaGiocata(unittest.TestCase):
    """«Prova la tua giocata»: la giocata compare come sigla secca."""

    def test_descrivi_leg_con_sigla(self):
        g = {"home": "Frosinone", "away": "Sassuolo", "giocata": "1X",
             "partita": "Frosinone vs Sassuolo",
             "commence_time": "2026-10-16T18:45:00Z"}
        etichetta = lg.descrivi_leg(g)
        self.assertIn("Frosinone - Sassuolo: 1X", etichetta)
        for vietato in ("Vince", "non perde", "Non finisce in pareggio", "(1X)"):
            self.assertNotIn(vietato, etichetta)
        self.assertTrue(etichetta.startswith("venerdì 16/10, ore 20:45"),
                        "data e ora italiane restano nell'etichetta della gamba")


if __name__ == "__main__":
    unittest.main()
