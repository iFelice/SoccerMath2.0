"""test_multiple_pronostico_partita.py — «🎯 Multiple»: che cosa dice la partita.

I riquadri propongono la COMBINAZIONE piu' probabile per arrivare a quota 2-3,
non la somma dei pronostici delle partite: per starci dentro a volte si gioca
una doppia chance (1X, X2, 12) o un esito che non e' quello che la partita
dice. Prima la scheda lo lasciava intuire («1X» e buonanotte) e chi leggeva
poteva credere che il pronostico di quella partita fosse proprio quello.

Due aggiunte, di TESTO e basta (la logica dei riquadri non cambia):

1. sotto il titolo, una riga che dice cosa sono i riquadri
   (``app.FRASE_RIQUADRI_MULTIPLA``);
2. accanto alla sigla giocata, quando e' un'altra cosa, il pronostico della
   partita: «X2 (pronostico: 1)», «12 (pronostico: —)». Se la sigla e' gia' il
   pronostico non si aggiunge niente (``app.sigla_giocata_con_pronostico``).
   Lo stesso numero sta nella colonna «Pronostico partita» di «Le più
   probabili» (``app.COLONNA_PRONOSTICO_PARTITA``).

Il pronostico della partita e' SEMPRE lo stesso della scheda «🏟️ Partite»:
``market_odds.esito_ammesso`` (l'esito piu' probabile solo se arriva a
``SOGLIA_TOPMIX_MERCATO``, altrimenti il trattino), letto una volta per tutte
dal file delle quote con ``app.pronostici_dalle_quote``. Nessuna delle due
viste se lo ricalcola per conto suo.

COSA VERIFICA

* (a) la sigla: «1» e pronostico «1» resta «1»; «X2» con pronostico «1»
  diventa «X2 (pronostico: 1)»; con pronostico «—» diventa «X2 (pronostico:
  —)»; senza pronostico (partita senza quote) non si aggiunge niente;
* (b) ``pronostici_dalle_quote``: «1» a una partita da 70%, il trattino a una
  piatta (40/30/30), stringa vuota a una senza quote;
* (c) UN RIQUADRO CON UN ESITO UGUALE E UNO DIVERSO (la prova della commessa):
  «Roma - Lecce 1» (uguale) e «Genoa - Fiorentina 12 (pronostico: 1)»
  (diverso), fianco a fianco nello stesso riquadro;
* (d) la colonna «Pronostico partita» di «Le più probabili»: subito dopo
  «Pronostico», con il valore giusto riga per riga; senza la mappa dei
  pronostichi la colonna non nasce;
* (e) la scheda VERA (AppTest su ``app.py``): la riga sotto il titolo, le
  sigle dei riquadri una per una, la colonna e nessuna parola vietata.

Nessuna rete: le quote sono un payload finto (test unitari) o la fixture degli
altri AppTest. Nessun file del repository toccato.

Esecuzione:
    python -m pytest SoccerMath/test_multiple_pronostico_partita.py -v
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from datetime import timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.dirname(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import market_odds as mo  # noqa: E402

import app as prod_app  # noqa: E402
import lista_giocate as lg  # noqa: E402

# La fixture degli AppTest (database in tmp, rete finta, registro in memoria) e
# i lettori del testo reso: una sola definizione per tutti.
from test_apptest_scheda_pronostici import (  # noqa: E402
    SCHEDA_PRONOSTICI,
    FixtureQuoteFinte,
    _BaseQuoteFinte,
)
from test_apptest_topmix_presentazione import (  # noqa: E402
    PAROLE_VIETATE,
    SCHEDA_MULTIPLE,
    _elementi_della_tab,
    _testi_della_tab,
)

# ---------------------------------------------------------------------------
# (a)(b): le parole, e il pronostico letto dal file delle quote
# ---------------------------------------------------------------------------
class TestLaSiglaColPronostico(unittest.TestCase):
    """(a): «1» resta «1», «X2» diventa «X2 (pronostico: 1)»."""

    def test_esito_uguale_non_si_aggiunge_niente(self):
        for sigla, pronostico in (("1", "1"), ("X", "X"), ("2", "2"), ("1X", "1X")):
            with self.subTest(sigla=sigla):
                self.assertEqual(sigla,
                                 prod_app.sigla_giocata_con_pronostico(sigla, pronostico))

    def test_esito_diverso_porta_il_pronostico_fra_parentesi(self):
        self.assertEqual("X2 (pronostico: 1)",
                         prod_app.sigla_giocata_con_pronostico("X2", "1"))
        self.assertEqual("1X (pronostico: 1)",
                         prod_app.sigla_giocata_con_pronostico("1X", "1"))
        self.assertEqual("12 (pronostico: 2)",
                         prod_app.sigla_giocata_con_pronostico("12", "2"))
        # Il trattino e' un pronostico (nessun esito abbastanza probabile): si dice.
        self.assertEqual(f"X2 (pronostico: {mo.TRATTINO_PRONOSTICO})",
                         prod_app.sigla_giocata_con_pronostico("X2",
                                                               mo.TRATTINO_PRONOSTICO))

    def test_senza_pronostico_nessuna_parentesi_vuota(self):
        """Partita senza quote: non c'e' un pronostico da dire, e non si
        scrive «pronostico: » seguito da niente."""
        for pronostico in ("", None):
            with self.subTest(pronostico=pronostico):
                self.assertEqual("12",
                                 prod_app.sigla_giocata_con_pronostico("12", pronostico))
        self.assertEqual("", prod_app.sigla_giocata_con_pronostico(None, None))

    def test_le_etichette_sono_quelle_promesse(self):
        self.assertEqual("pronostico: ", prod_app.ETICHETTA_PRONOSTICO_PARTITA)
        self.assertEqual("Pronostico partita", prod_app.COLONNA_PRONOSTICO_PARTITA)
        self.assertEqual("La combinazione più probabile per arrivare a quota 2-3. "
                         "Per arrivarci a volte si gioca un esito diverso dal "
                         "pronostico della partita.",
                         prod_app.FRASE_RIQUADRI_MULTIPLA)


class TestPronosticiDalFileDelleQuote(unittest.TestCase):
    """(b): un dizionario {match_id: pronostico}, dalla stessa regola di Partite."""

    def _payload(self, adesso):
        from test_apptest_scheda_pronostici import _iso
        eventi = [
            {"id": 501, "home_team": "Inter", "away_team": "Roma",
             "commence_time": _iso(adesso + timedelta(hours=8)),
             "libri": [FixtureQuoteFinte._libro(0.70, 0.18, 0.12, adesso)]},
            # terna piatta: l'esito piu' alto (40%) non arriva al 57% -> trattino
            {"id": 502, "home_team": "Genoa", "away_team": "Como",
             "commence_time": _iso(adesso + timedelta(hours=10)),
             "libri": [FixtureQuoteFinte._libro(0.40, 0.30, 0.30, adesso)]},
            # nessun libro: la fonte non copre la partita
            {"id": 503, "home_team": "Bologna", "away_team": "Monza",
             "commence_time": _iso(adesso + timedelta(hours=12)), "libri": []},
        ]
        return {"schema": "soccermath_live_odds_v1",
                "generato_il": _iso(adesso),
                "leghe": {"Serie A": {"eventi": eventi}}}

    def test_un_pronostico_per_partita(self):
        from datetime import datetime, timezone
        adesso = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
        pronostici = prod_app.pronostici_dalle_quote(self._payload(adesso))
        self.assertEqual({"501": "1", "502": mo.TRATTINO_PRONOSTICO, "503": ""},
                         pronostici)
        # La stessa regola della scheda Partite: non un'altra.
        self.assertEqual(prod_app.pronostico_dalle_quote({"1": 0.70, "X": 0.18,
                                                          "2": 0.12}),
                         pronostici["501"])
        self.assertEqual(mo.SOGLIA_TOPMIX_MERCATO, 0.57)

    def test_senza_file_niente_pronostici(self):
        for payload in ({}, None, "non un payload", {"leghe": {}}):
            with self.subTest(payload=payload):
                self.assertEqual({}, prod_app.pronostici_dalle_quote(payload))


# ---------------------------------------------------------------------------
# (c)(d): i riquadri e la tabella, con un esito uguale e uno diverso
# ---------------------------------------------------------------------------
def _giocata(mid, casa, trasferta, esito, prob, adesso, quota=2.0):
    """Una gamba di una proposta, come la scrive ``lista_giocate``."""
    return {"match_id": str(mid), "home": casa, "away": trasferta,
            "partita": f"{casa} vs {trasferta}", "giocata": esito, "esito": esito,
            "probabilita": prob, "quota_b365_stimata": quota,
            "quota_stimata_effettiva": quota,
            "commence_time": adesso.strftime("%Y-%m-%dT%H:%M:%SZ")}


class TestUnRiquadroConUnEsitoUgualeEUnoDiverso(unittest.TestCase):
    """(c): la prova della commessa, su un riquadro di due partite."""

    def setUp(self):
        from datetime import datetime, timezone
        self.ADESSO = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)

    def _prop(self):
        return {"per_k": {2: {
            "k": 2, "probabilita": 0.44, "quota_totale": 2.06,
            "giocate": [
                _giocata(501, "Genoa", "Fiorentina", "12", 0.91, self.ADESSO),
                _giocata(502, "Roma", "Lecce", "1", 0.66, self.ADESSO),
            ]}}}

    def test_nello_stesso_riquadro_una_sigla_cambia_e_una_no(self):
        pronostici = {"501": "1", "502": "1"}
        riquadri = prod_app.riquadri_multiple(self._prop(), self.ADESSO,
                                              pronostici=pronostici)
        self.assertEqual(1, len(riquadri))
        partite = riquadri[0]["partite"]
        # Letto per intero: «sigla · giorno abbreviato ora», con la parentesi
        # solo sulla riga il cui esito NON e' il pronostico della partita.
        self.assertEqual("Genoa - Fiorentina", partite[0][0])
        self.assertTrue(partite[0][1].startswith("12 (pronostico: 1) · "),
                        partite[0][1])
        self.assertEqual("Roma - Lecce", partite[1][0])
        self.assertTrue(partite[1][1].startswith("1 · "), partite[1][1])
        self.assertNotIn("pronostico", partite[1][1],
                         "se coincide con il pronostico non si aggiunge niente")

    def test_il_trattino_si_dice_in_parentesi(self):
        """Partita piatta: nessun esito arriva al 57% e la scheda lo scrive."""
        pronostici = {"501": mo.TRATTINO_PRONOSTICO, "502": mo.TRATTINO_PRONOSTICO}
        riquadri = prod_app.riquadri_multiple(self._prop(), self.ADESSO,
                                              pronostici=pronostici)
        self.assertTrue(riquadri[0]["partite"][0][1].startswith(
            f"12 (pronostico: {mo.TRATTINO_PRONOSTICO}) · "))
        self.assertTrue(riquadri[0]["partite"][1][1].startswith(
            f"1 (pronostico: {mo.TRATTINO_PRONOSTICO}) · "),
            "il trattino e' diverso da «1»: si dice")

    def test_senza_la_mappa_nessuna_parentesi(self):
        """Senza pronostichi la scheda resta com'era: nessun numero inventato."""
        riquadri = prod_app.riquadri_multiple(self._prop(), self.ADESSO)
        for _nome, sotto in riquadri[0]["partite"]:
            self.assertNotIn("pronostico", sotto)
        self.assertTrue(riquadri[0]["partite"][0][1].startswith("12 · "))
        self.assertTrue(riquadri[0]["partite"][1][1].startswith("1 · "))


class TestLaColonnaPronosticoPartita(unittest.TestCase):
    """(d): «Le più probabili» guadagna una colonna, subito dopo «Pronostico»."""

    def setUp(self):
        from datetime import datetime, timezone
        self.ADESSO = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)

    def _giocate(self):
        return [
            _giocata(501, "Genoa", "Fiorentina", "12", 0.91, self.ADESSO, 1.09),
            _giocata(502, "Roma", "Lecce", "1", 0.66, self.ADESSO, 1.45),
            _giocata(503, "Bologna", "Monza", "1X", 0.70, self.ADESSO, 1.30),
        ]

    def test_la_colonna_va_dopo_pronostico_con_il_valore_giusto(self):
        pronostici = {"501": "1", "502": "1", "503": ""}
        righe = prod_app.tabella_piu_probabili(self._giocate(), 1.0, self.ADESSO,
                                               pronostici=pronostici)
        df, ordinate = prod_app.tabella_pronostici_visibile(righe)
        self.assertEqual(["Quando", "Partita", "Pronostico", "Pronostico partita",
                          "Quote %", "Quota"], list(df.columns))
        self.assertNotIn("Modello %", df.columns,
                         "«Modello %» sta nella scheda partita e nei Dettagli")
        per_partita = dict(zip(df["Partita"], df["Pronostico partita"]))
        self.assertEqual({"Genoa - Fiorentina": "1", "Roma - Lecce": "1",
                          "Bologna - Monza": ""}, per_partita)
        # «Pronostico» resta la sigla GIOCATA: le due colonne non si scambiano.
        per_partita_giocata = dict(zip(df["Partita"], df["Pronostico"]))
        self.assertEqual({"Genoa - Fiorentina": "12", "Roma - Lecce": "1",
                          "Bologna - Monza": "1X"}, per_partita_giocata)
        self.assertEqual(len(df), len(ordinate))
        for riga, ordinata in zip(df.to_dict("records"), ordinate):
            self.assertEqual(riga["Pronostico partita"],
                             ordinata["Pronostico partita"])

    def test_il_trattino_arriva_in_colonna(self):
        pronostici = {"501": mo.TRATTINO_PRONOSTICO, "502": "1", "503": ""}
        righe = prod_app.tabella_piu_probabili(self._giocate(), 1.0, self.ADESSO,
                                               pronostici=pronostici)
        df, _ = prod_app.tabella_pronostici_visibile(righe)
        self.assertEqual(mo.TRATTINO_PRONOSTICO,
                         df[df["Partita"] == "Genoa - Fiorentina"]
                         .iloc[0]["Pronostico partita"])

    def test_senza_pronostici_la_colonna_non_nasce(self):
        """Le altre tabelle (Pronostici, Pareggi) restano di cinque colonne."""
        righe = prod_app.tabella_piu_probabili(self._giocate(), 1.0, self.ADESSO)
        df, _ = prod_app.tabella_pronostici_visibile(righe)
        self.assertEqual(prod_app.COLONNE_PRONOSTICI, list(df.columns))
        self.assertNotIn(prod_app.COLONNA_PRONOSTICO_PARTITA, df.columns)


# ---------------------------------------------------------------------------
# (e): la scheda vera, disegnata da app.py
# ---------------------------------------------------------------------------
class TestNellaSchedaVera(_BaseQuoteFinte):
    """(e): la riga sotto il titolo, le sigle, la colonna. Tutto in vista."""

    @classmethod
    def _df_probabili(cls, at):
        """Il DataFrame di «Le più probabili» (quello con la chiave giusta)."""
        chiave = prod_app.chiave_tabella_corrente(
            prod_app.CHIAVE_TABELLA_PIU_PROBABILI, at.session_state)
        for el in _elementi_della_tab(at, SCHEDA_MULTIPLE, "dataframe"):
            if str(getattr(el, "key", "") or "") == chiave:
                val = getattr(el, "value", None)
                return val.data if val is not None and hasattr(val, "data") else val
        raise AssertionError("tabella «Le più probabili» non trovata")

    def test_01_la_riga_sotto_il_titolo_dice_cosa_sono_i_riquadri(self):
        testo = self._testo(self.at, SCHEDA_MULTIPLE)
        self.assertIn(prod_app.FRASE_RIQUADRI_MULTIPLA, testo,
                      "sotto il titolo la riga sulla combinazione quota 2-3")

    def test_02_un_riquadro_con_un_esito_uguale_e_uno_diverso(self):
        """Ogni gamba si legge come la regola dice: «sigla · quando», con la
        parentesi solo quando l'esito giocato NON e' il pronostico."""
        pronostici = prod_app.pronostici_dalle_quote(self.payload)
        res = lg.calcola_lista_giocate(self.payload, adesso_utc=self.ADESSO)
        in_periodo = lg.giocate_nel_periodo(res["giocate"], self.ADESSO,
                                            lg.PERIODO_GIORNATA)
        prop = lg.cerca_proposta_multipla(in_periodo)
        riquadri = prod_app.riquadri_multiple(prop, self.ADESSO,
                                              pronostici=pronostici)
        self.assertTrue(riquadri, "il fixture ha almeno una proposta")
        testo = self._testo(self.at, SCHEDA_MULTIPLE)
        uguali, diversi = 0, 0
        for r in riquadri:
            for nome, sotto in r["partite"]:
                with self.subTest(riquadro=r["k"], partita=nome):
                    self.assertIn(nome, testo)
                    self.assertIn(sotto, testo,
                                  f"la riga di {nome} si legge come la regola")
                if "(pronostico:" in sotto:
                    diversi += 1
                else:
                    uguali += 1
        # La commessa: almeno una gamba uguale e almeno una diversa, e la
        # «Doppia» del fixture le ha una di fianco all'altra.
        self.assertGreaterEqual(uguali, 1, "nessuna gamba uguale al pronostico")
        self.assertGreaterEqual(diversi, 1, "nessuna gamba diversa dal pronostico")

    def test_03_le_piu_probabili_hanno_la_colonna_pronostico_partita(self):
        pronostici = prod_app.pronostici_dalle_quote(self.payload)
        df = self._df_probabili(self.at)
        self.assertEqual(["Quando", "Partita", "Pronostico", "Pronostico partita",
                          "Quote %", "Quota"], list(df.columns))
        self.assertTrue(len(df), "la tabella ha le sue righe")
        for _i, riga in df.iterrows():
            with self.subTest(partita=riga["Partita"]):
                atteso = pronostici.get(str(self._match_id(riga["Partita"])), "")
                self.assertEqual(atteso, str(riga["Pronostico partita"]),
                                 f"{riga['Partita']}: il pronostico della partita")
        # E almeno una riga in cui giocato e pronostico NON coincidono: e'
        # esattamente il caso per cui la colonna serve.
        self.assertTrue(any(str(r["Pronostico"]) != str(r["Pronostico partita"])
                            for _i, r in df.iterrows()),
                        "nessuna riga con esito diverso dal pronostico")

    def _match_id(self, partita):
        """Il match_id del fixture dalla stringa «Casa - Trasferta»."""
        for mid, casa, trasferta, _probs, _kickoff in FixtureQuoteFinte.pianifica(
                self.ADESSO):
            if f"{casa} - {trasferta}" == str(partita):
                return str(mid)
        raise AssertionError(f"partita sconosciuta: {partita!r}")

    def test_04_in_vista_niente_gergo(self):
        testo = self._testo(self.at, SCHEDA_MULTIPLE).lower()
        for parola in PAROLE_VIETATE:
            with self.subTest(parola=parola):
                self.assertIsNone(re.search(parola, testo, re.IGNORECASE),
                                  f"parola vietata nella scheda Multiple: {parola!r}")

    def test_05_le_altre_schede_restano_di_cinque_colonne(self):
        """La colonna nuova sta solo in «Le più probabili»: Pronostici e
        Pareggi non cambiano (il confronto con «⚽ Pronostici» dopo il click)."""
        self._premi_click(self.at, "Calcola i pronostici della giornata")
        pron = self._df(self.at, SCHEDA_PRONOSTICI)
        self.assertEqual(prod_app.COLONNE_PRONOSTICI,
                         [c for c in pron.columns
                          if c not in ("Gol", "Insieme %")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
