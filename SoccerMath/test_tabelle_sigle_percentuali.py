"""REGOLA (presentazione dopo la PR #65): nelle tabelle IN VISTA della scheda
Giocate e della tabella Mercato di Com'è andata

* la giocata e' la SOLA sigla (1, X, 2, 1X, X2, 12): niente «Vince <squadra>»,
  «<squadra> non perde», «Non finisce in pareggio», niente sigla fra parentesi;
* al posto di «Riesce circa» ci sono DUE colonne percentuali con una cifra
  decimale: «Quote %» (probabilita' dalle quote, come prima) e «Modello %»
  (probabilita' del modello Drago per lo STESSO esito; per le doppie chance e'
  la SOMMA delle due probabilita' 1X2 del modello, sullo stesso snapshot del
  giro ``fetch_and_calc_top_mix``: «in calcolo» finche' il giro non e' pronto,
  «n/d» se fallisce o non copre la partita);
* la colonna «Il nostro modello è d'accordo» esce dalla vista: il campo resta
  nei dati, nel Registro e nei Dettagli (nessuna logica cambia);
* l'ordine predefinito e' «Quote %» DECRESCENTE e la colonna «Quote %» resta
  NUMERICA nel DataFrame (l'ordinamento al clic e' numerico, non alfabetico).

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


class TestTabellaScelteSecondoLeQuote(unittest.TestCase):
    """«Le scelte più sicure secondo le quote» (tabella in vista della scheda Giocate)."""

    def test_colonne_sigla_e_niente_accordo(self):
        righe = [_riga_mercato(prob=0.66, esito="1"), _riga_mercato(prob=0.58, esito="X",
                                                                    home="Milan", away="Lazio")]
        df = app.tabella_top_mix_mercato_visibile(righe, stato_confronto="pronto",
                                                  mappa_modello_1x2={})
        self.assertEqual(["Quando", "Campionato", "Partita", "Giocata",
                          "Quote %", "Modello %"], list(df.columns))
        self.assertNotIn("Riesce circa", df.columns)
        self.assertFalse(any("d'accordo" in str(c) for c in df.columns),
                         "la colonna del segnale d'accordo esce dalla vista")
        for valore in df["Giocata"]:
            self.assertIn(valore, {"1", "X", "2", "1X", "X2", "12"},
                          f"la Giocata in vista e' la sola sigla, non {valore!r}")
        for vietato in ("Vince", "non perde", "Non finisce in pareggio", "("):
            for valore in df["Giocata"]:
                self.assertNotIn(vietato, valore)

    def test_quote_percento_numerica_e_ordine_decrescente(self):
        righe = [_riga_mercato(prob=0.58, home="A", away="B"),
                 _riga_mercato(prob=0.71, home="C", away="D"),
                 _riga_mercato(prob=0.649, home="E", away="F")]
        df = app.tabella_top_mix_mercato_visibile(righe)
        self.assertTrue(pd.api.types.is_numeric_dtype(df["Quote %"]),
                        "«Quote %» resta numerica: il clic sull'intestazione ordina per valore")
        valori = df["Quote %"].tolist()
        self.assertEqual(valori, sorted(valori, reverse=True),
                         "l'ordine predefinito e' «Quote %» decrescente")
        self.assertEqual([71.0, 64.9, 58.0], valori, "una cifra decimale")

    def test_modello_percento_stati_in_calcolo_e_nd(self):
        righe = [_riga_mercato(esito="1")]
        # giro del modello non ancora finito -> "in calcolo"
        for stato in (None, "in_calcolo"):
            df = app.tabella_top_mix_mercato_visibile(righe, stato_confronto=stato)
            self.assertEqual(["in calcolo"], df["Modello %"].tolist())
        # giro fallito -> "n/d"
        df = app.tabella_top_mix_mercato_visibile(righe, stato_confronto="non_disponibile")
        self.assertEqual(["n/d"], df["Modello %"].tolist())
        # giro pronto ma partita non coperta -> "n/d" (nessun numero inventato)
        df = app.tabella_top_mix_mercato_visibile(righe, stato_confronto="pronto",
                                                  mappa_modello_1x2={})
        self.assertEqual(["n/d"], df["Modello %"].tolist())

    def test_modello_percento_pronto_il_numero_del_selettore(self):
        righe = [_riga_mercato(prob=0.675, esito="1", prob_modello_val=63.0)]
        mappa = app.prob_modello_1x2_per_partita(_terna_snapshot())
        df = app.tabella_top_mix_mercato_visibile(righe, stato_confronto="pronto",
                                                  mappa_modello_1x2=mappa)
        self.assertEqual(["41,2%"], df["Modello %"].tolist(),
                         "l'esito 1 della riga legge la STESSA terna dello snapshot, "
                         "con la virgola italiana")


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
        self.assertEqual("68,7%", app.testo_modello_percento(riga, "pronto", mappa),
                         "in colonna la somma si mostra con la virgola italiana")


class TestLePiuProbabili(unittest.TestCase):
    """Le righe di «Le più probabili»: sigla, due percentuali, ordine decrescente."""

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
        df = app.righe_piu_probabili_visibili(self._giocata(), adesso=None,
                                              stato_confronto="pronto", mappa_modello_1x2=mappa)
        self.assertEqual(["Quando", "Partita", "Giocata", "Quote %",
                          "Modello %", "Paga circa"], list(df.columns))
        self.assertEqual(["1", "1X"], df["Giocata"].tolist(),
                         "la sigla secca, anche per le doppie chance, in ordine decrescente")
        self.assertTrue(pd.api.types.is_numeric_dtype(df["Quote %"]))
        self.assertEqual([71.2, 67.5], df["Quote %"].tolist(),
                         "ordine «Quote %» decrescente, una cifra decimale")
        # la doppia chance 1X di Inter-Roma somma le due probabilita' 1X2
        # della STESSA terna snapshot: 41,2 + 27,5; Milan-Lazio non e' nel
        # giro del modello -> "n/d"
        self.assertEqual(["n/d", "68,7%"], df["Modello %"].tolist())

    def test_modello_in_calcolo_e_nd(self):
        g = self._giocata()
        df = app.righe_piu_probabili_visibili(g, stato_confronto=None)
        self.assertEqual(["in calcolo"] * 2, df["Modello %"].tolist())
        df = app.righe_piu_probabili_visibili(g, stato_confronto="non_disponibile")
        self.assertEqual(["n/d"] * 2, df["Modello %"].tolist())
        df = app.righe_piu_probabili_visibili(g, stato_confronto="pronto",
                                              mappa_modello_1x2={})
        self.assertEqual(["n/d"] * 2, df["Modello %"].tolist())


class TestPerRaddoppiare(unittest.TestCase):
    """Il riquadro «Per raddoppiare»: ogni partita «<casa> - <trasferta>: <sigla>»,
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
        self.assertTrue(pd.api.types.is_numeric_dtype(df["Quote %"]))
        self.assertEqual([62.5, 58.0, 64.0], df["Quote %"].tolist())
        self.assertEqual([63.0, 51.0], [v for v in df["Modello %"].tolist() if not pd.isna(v)])
        self.assertTrue(pd.isna(df["Modello %"].iloc[2]),
                        "senza campo *_prima la cella resta vuota, nessun numero inventato")

    def test_prima_registrazione_ricostruita_dichiarata_dai_numeri(self):
        # Riga vecchia scritta PRIMA che i campi *_prima esistessero: il campo
        # manca del tutto, la prima e' ricostruita dall'attuale
        # (``prob_di_registrazione``) e la cella mostra quel numero.
        vecchia = {"data": datetime(2026, 10, 5, 20, 45), "campionato": "Liga",
                   "home": "Getafe", "away": "Osasuna", "mercato_standard": "12",
                   "prob_sicuro": 57.0, "risultato_reale": "0-0", "esito": "❌"}
        df = pd.DataFrame([vecchia])
        out = app._tabella_registro_mercato_visibile(df)
        self.assertEqual(57.0, out["Quote %"].iloc[0])
        self.assertIsNone(out["Modello %"].iloc[0])

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
        for nome in ("tabella_top_mix_mercato_visibile", "righe_piu_probabili_visibili",
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
