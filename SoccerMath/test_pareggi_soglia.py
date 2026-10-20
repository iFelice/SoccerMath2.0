"""test_pareggi_soglia.py — la scheda «🟰 Pareggi» mostra solo i pareggi che contano.

Commessa (schedula «🟰 Pareggi»): la scheda elencava TUTTE le partite del
periodo il cui esito piu' probabile era l'X — anche quando l'X valeva il 20%,
cioe' un evento che non arriva a una volta su cinque. Una graduatoria cosi'
non dice niente: «il pareggio piu' probabile» di quella partita resta un fatto
tecnico, non un pareggio su cui vale la pena fermarsi.

Adesso la scheda mostra solo i pareggi con probabilita' almeno
``market_odds.SOGLIA_PAREGGI`` (0,30). La regola e' UNA e sta in
``app.pareggi_da_mostrare``: esito «X» della lista giocate e probabilita' >=
soglia. Se nel periodo non ne resta nessuno, la scheda lo DICE
(``app.FRASE_NESSUN_PAREGGIO_SOPRA_SOGLIA``) invece di tirarne fuori uno per
forza: «Nessun pareggio con almeno il 30% di probabilita' nel periodo scelto.»
La frase vecchia (nessun pareggio in programma) resta per il caso davvero
vuoto: un conto e' «non ci sono X», un altro e' «ci sono ma non arrivano».

COSA VERIFICA

* (a) una partita con l'X al 31% COMPARE, una con l'X al 20% NO;
* (b) il confine e' la soglia (29,99% fuori, 30% dentro) e la soglia e' un
  parametro, non un numero cucito nella funzione;
* (c) restano fuori gli esiti che non sono X e le giocate senza probabilita':
  nessun pareggio inventato;
* (d) lo stesso filtro sul percorso VERO (file delle quote -> de-vig ->
  ``lista_giocate`` -> ``pareggi_da_mostrare``);
* (e) se nessun pareggio arriva al 30%, la scheda mostra la frase che lo dice e
  NESSUNA tabella: provato nell'AppTest, sul VERO ``app.py``.

Nessuna rete: le quote sono un payload finto (test unitari) o la fixture degli
altri AppTest, con calendario e rete finti. Nessun file del repository toccato.

Esecuzione:
    python -m pytest SoccerMath/test_pareggi_soglia.py -v
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.dirname(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import market_odds as mo  # noqa: E402

import app as prod_app  # noqa: E402
import lista_giocate as lg  # noqa: E402

# La fixture degli altri AppTest (database in tmp, rete finta, registro in
# memoria) e i due lettori del testo reso: una sola definizione per tutti.
from test_apptest_scheda_pronostici import (  # noqa: E402
    SCHEDA_PAREGGI,
    FixtureQuoteFinte,
    _BaseQuoteFinte,
    _elementi_della_tab,
    _iso,
)
from test_apptest_topmix_presentazione import PAROLE_VIETATE  # noqa: E402

SOGLIA = mo.SOGLIA_PAREGGI


def _giocata(casa, trasferta, esito, prob):
    """Una giocata della lista, come la scrive ``lista_giocate``."""
    g = {"match_id": 900 + len(casa) + len(trasferta), "home": casa,
         "away": trasferta, "partita": f"{casa} - {trasferta}",
         "giocata": esito, "esito": esito}
    if prob is not None:
        g["probabilita"] = prob
        g["prob_percentuale"] = round(prob * 100.0, 2)
    return g


def _nomi(giocate):
    return [f"{g['home']} - {g['away']}" for g in giocate]


class TestIlFiltroSul30PerCento(unittest.TestCase):
    """(a)(b)(c): dentro sopra il 30%, fuori sotto, e la soglia e' un parametro."""

    def test_la_soglia_e_una_costante_e_vale_030(self):
        self.assertEqual(0.30, SOGLIA)
        self.assertEqual(SOGLIA, prod_app.SOGLIA_PAREGGI,
                         "l'app la importa, non la riscrive")

    def test_il_31_per_cento_entra_il_20_per_cento_no(self):
        """La prova della commessa, sulla stessa lista di giocate."""
        giocate = [
            _giocata("Genoa", "Fiorentina", "X", 0.31),
            _giocata("Roma", "Lecce", "X", 0.20),
        ]
        self.assertEqual(["Genoa - Fiorentina"],
                         _nomi(prod_app.pareggi_da_mostrare(giocate)))

    def test_il_confine_e_la_soglia(self):
        giocate = [
            _giocata("Sotto", "DiPoco", "X", 0.2999),
            _giocata("Pari", "Esatto", "X", 0.30),
            _giocata("Sopra", "DiTanto", "X", 0.3001),
        ]
        self.assertEqual(["Pari - Esatto", "Sopra - DiTanto"],
                         _nomi(prod_app.pareggi_da_mostrare(giocate)))

    def test_la_soglia_e_un_parametro_non_un_numero_cucito(self):
        giocate = [_giocata("Genoa", "Fiorentina", "X", 0.31),
                   _giocata("Roma", "Lecce", "X", 0.20)]
        self.assertEqual(["Genoa - Fiorentina", "Roma - Lecce"],
                         _nomi(prod_app.pareggi_da_mostrare(giocate, 0.20)),
                         "con la soglia a 0,20 entra anche il 20%")
        self.assertEqual([], _nomi(prod_app.pareggi_da_mostrare(giocate, 0.35)),
                         "con la soglia a 0,35 non entra nessuno")

    def test_esiti_che_non_sono_x_restano_fuori(self):
        """La scheda e' dei PAREGGI: un 1 al 57% non c'entra, ne' un Over 2.5."""
        giocate = [
            _giocata("Milan", "Juventus", "1", 0.57),
            _giocata("Inter", "Napoli", "2", 0.80),
            _giocata("Lazio", "Udinese", "Over 2.5", 0.62),
            _giocata("Torino", "Como", "X", 0.31),
            _giocata("Fiorentina", "Bologna", " X ", 0.33),
        ]
        self.assertEqual(["Torino - Como", "Fiorentina - Bologna"],
                         _nomi(prod_app.pareggi_da_mostrare(giocate)))

    def test_senza_probabilita_nessun_pareggio_inventato(self):
        giocate = [
            _giocata("Sassuolo", "Verona", "X", None),
            {"home": "Empoli", "away": "Cagliari", "giocata": "X"},
            {"home": "Lecce", "away": "Frosinone", "giocata": "X",
             "probabilita": "non un numero"},
            None,
            "non una giocata",
        ]
        self.assertEqual([], prod_app.pareggi_da_mostrare(giocate))
        self.assertEqual([], prod_app.pareggi_da_mostrare(None))
        self.assertEqual([], prod_app.pareggi_da_mostrare([]))

    def test_la_probabilita_si_legge_in_entrambi_i_campi(self):
        """La lista tiene il numero in frazione e in percentuale: qui la
        frazione, che il confronto non dipenda da chi ha riempito la riga."""
        self.assertEqual(0.31, prod_app.probabilita_giocata(
            {"probabilita": 0.31, "prob_percentuale": 31.0}))
        self.assertEqual(0.31, prod_app.probabilita_giocata(
            {"prob_percentuale": 31.0}))
        self.assertIsNone(prod_app.probabilita_giocata({"giocata": "X"}))
        self.assertIsNone(prod_app.probabilita_giocata(None))

    def test_il_filtro_non_riordina(self):
        """A ordinare ci pensa la tabella: qui si filtra e basta."""
        giocate = [_giocata("Prima", "Partita", "X", 0.31),
                   _giocata("Seconda", "Partita", "X", 0.40),
                   _giocata("Terza", "Partita", "X", 0.30)]
        self.assertEqual(["Prima - Partita", "Seconda - Partita",
                          "Terza - Partita"],
                         _nomi(prod_app.pareggi_da_mostrare(giocate)))


def _adesso_fixture():
    """L'orologio del test: ADESSO, con la giornata abbastanza lunga.

    Come nella fixture degli AppTest: le date sono RELATIVE all'orologio vero,
    perche' il percorso scarta le partite il cui kickoff e' gia' passato. Se il
    giorno cade troppo vicino al lunedi' di gioco, si va avanti di tre giorni:
    cosi' «dentro la giornata» resta un insieme certo.
    """
    adesso = datetime.now(timezone.utc).replace(microsecond=0)
    if lg.lunedi_gioco(adesso) - adesso < timedelta(hours=26):
        adesso += timedelta(days=3)
    return adesso


class TestSulPercorsoVero(unittest.TestCase):
    """(d): dal file delle quote alla scheda, senza riscrivere niente."""

    def setUp(self):
        self.ADESSO = _adesso_fixture()

    def _payload(self):
        eventi = []
        # (casa, trasferta, (p1, pX, p2)): l'X e' 31%, 20% e 33%.
        for mid, (casa, trasferta, probs) in enumerate(
                [("Genoa", "Fiorentina", (0.37, 0.31, 0.32)),
                 ("Roma", "Lecce", (0.66, 0.20, 0.14)),
                 ("Torino", "Como", (0.34, 0.33, 0.33))], start=1):
            eventi.append({
                "id": 900 + mid,
                "commence_time": _iso(self.ADESSO + timedelta(hours=8 + mid)),
                "home_team": casa, "away_team": trasferta,
                "last_update": _iso(self.ADESSO),
                "libri": [FixtureQuoteFinte._libro(*probs, self.ADESSO)]})
        return {"schema": "soccermath_live_odds_v1",
                "generato_il": _iso(self.ADESSO),
                "leghe": {"Serie A": {"eventi": eventi}}}

    def test_tre_partite_due_sopra_e_una_sotto(self):
        payload = self._payload()
        res = lg.calcola_lista_giocate(payload, adesso_utc=self.ADESSO)
        in_periodo = lg.giocate_nel_periodo(res["giocate"], self.ADESSO,
                                            lg.PERIODO_GIORNATA)
        x_tutti = [g for g in in_periodo
                   if str(g.get("giocata") or "").strip() == "X"]
        self.assertEqual(3, len(x_tutti), "tre X nel periodo, prima del filtro")
        mostrati = prod_app.pareggi_da_mostrare(in_periodo)
        self.assertEqual(["Torino - Como", "Genoa - Fiorentina"], _nomi(mostrati),
                         "il 33% e il 31% si vedono, il 20% no")
        # Le righe della tabella portano la stessa probabilita' con cui si e'
        # deciso: nessun numero ricalcolato dopo il filtro.
        self.assertEqual([33.0, 31.0],
                         [round(prod_app.percento_decimale(g["probabilita"]), 1)
                          for g in mostrati])
        for g in mostrati:
            riga = prod_app.riga_pronostico_da_giocata(g, self.ADESSO)
            self.assertEqual("X", riga["Pronostico"])
            self.assertEqual(f"{g['home']} - {g['away']}", riga["Partita"])


class FixturePareggiBassi:
    """Lo stesso pianeta del fixture, con TUTTI gli X al 20%.

    Serve a provare la frase: di pareggi ce ne sono (quattro in periodo, uno
    fuori), ma nessuno arriva al 30%. Le probabilita' di 1 restano quelle del
    fixture, cosi' le altre schede non cambiano.
    """

    @staticmethod
    def pianifica(adesso):
        return [(mid, casa, trasferta, (0.60, 0.20, 0.20), kickoff)
                for mid, casa, trasferta, _probs, kickoff
                in FixtureQuoteFinte.pianifica(adesso)]

    @classmethod
    def payload_quote(cls, adesso):
        from test_apptest_scheda_pronostici import _iso as iso_fixture
        eventi = []
        for mid, casa, trasferta, probs, kickoff in cls.pianifica(adesso):
            eventi.append({
                "id": mid, "commence_time": iso_fixture(kickoff),
                "home_team": casa, "away_team": trasferta,
                "last_update": iso_fixture(adesso),
                "libri": [FixtureQuoteFinte._libro(*probs, adesso)]})
        payload = FixtureQuoteFinte.payload_quote(adesso)
        payload["leghe"]["Serie A"]["eventi"] = eventi
        return payload

    @staticmethod
    def calendario(adesso):
        return FixtureQuoteFinte.calendario(adesso)


class TestLaSchedaLoDice(_BaseQuoteFinte):
    """(e): nessun pareggio sopra il 30% -> la frase, e nessuna tabella.

    Gira sul VERO ``app.py`` con la fixture degli altri AppTest (database in
    tmp, rete finta, registro in memoria): il testo che si legge qui e' quello
    che si leggerebbe aprendo la pagina.
    """

    FIXTURE = FixturePareggiBassi

    def test_nessun_pareggio_sopra_il_30_per_cento_si_dice_e_basta(self):
        self.assertEqual("Nessun pareggio con almeno il 30% di probabilit\u00e0 "
                         "nel periodo scelto.",
                         prod_app.FRASE_NESSUN_PAREGGIO_SOPRA_SOGLIA)
        testo = self._testo(self.at, SCHEDA_PAREGGI)
        self.assertIn(prod_app.FRASE_NESSUN_PAREGGIO_SOPRA_SOGLIA, testo,
                      "la scheda dice che nessun pareggio arriva al 30%")
        # Non e' il caso «nessun pareggio in programma»: di X ce ne sono, sono
        # solo troppo bassi, e la frase vecchia direbbe una cosa falsa.
        self.assertNotIn(prod_app.FRASE_NESSUN_PAREGGIO_NEL_PERIODO, testo)
        self.assertEqual([], _elementi_della_tab(self.at, SCHEDA_PAREGGI,
                                                 "dataframe"),
                         "nessuna tabella vuota: si legge la frase")
        # Il filtro, sulla stessa fixture: quattro X in periodo, nessuno dentro.
        res = lg.calcola_lista_giocate(self.payload, adesso_utc=self.ADESSO)
        in_periodo = lg.giocate_nel_periodo(res["giocate"], self.ADESSO,
                                            lg.PERIODO_GIORNATA)
        self.assertEqual(4, len([g for g in in_periodo
                                 if str(g.get("giocata") or "").strip() == "X"]))
        self.assertEqual([], prod_app.pareggi_da_mostrare(in_periodo))
        self.assertEqual([], self.scritture, "la scheda Pareggi non scrive niente")
        self.assertEqual([], self.registro.scritture)

    def test_in_vista_niente_gergo(self):
        """La frase sta IN VISTA: niente «soglia» e niente delle altre parole
        vietate dell'elenco unico della PR #64."""
        testo = self._testo(self.at, SCHEDA_PAREGGI).lower()
        self.assertTrue(testo, "la scheda Pareggi e' bianca")
        for parola in PAROLE_VIETATE:
            with self.subTest(parola=parola):
                self.assertIsNone(re.search(parola, testo, re.IGNORECASE),
                                  f"parola vietata nella scheda Pareggi: {parola!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
