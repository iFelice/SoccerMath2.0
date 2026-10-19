"""test_pronostico_partite.py — la colonna «Pronostico» di Partite e della scheda partita.

Commessa (schedula «🏟️ Partite» + scheda della singola partita): la colonna
«Pronostico» deve mostrare LO STESSO pronostico del Top Mix — l'esito secco
1, X o 2 piu' probabile, ma SOLO se la sua probabilita' arriva a
``market_odds.SOGLIA_TOPMIX_MERCATO`` (0,57). Sotto soglia si legge un
trattino: un 39,9% non e' un pronostico, e prima la colonna lo mostrava
(comodo, ma falso: era solo l'esito piu' alto di una terna piatta).

La regola e' UNA e sta in ``market_odds.esito_ammesso``: la chiamano la
scheda Partite (``app.riga_tabella_partita``) e la scheda della singola
partita (``scheda_partita.costruisci_scheda`` / ``righe_partite_giornata``),
ed e' la stessa regola di ``app.seleziona_riga_top_mix_mercato`` (argmax con
spareggio sul primo massimo, ammissione sopra soglia). Nessuna delle due la
riscrive: due copie della stessa soglia divergono, prima o poi.

COSA VERIFICA

* (a) una partita con il 2 al 39,9% mostra il TRATTINO, non «2»;
* (b) una partita con l'1 al 64% mostra «1»;
* (c) il confine e' la soglia del Top Mix (0,5699 trattino, 0,57 «1») e senza
  i tre numeri la cella resta VUOTA (nessun pronostico inventato);
* (d) il pronostico di «Partite» coincide con quello della scheda
  «Pronostici» sulle STESSE partite (Top Mix: ammessa = stessa sigla, non
  ammessa = trattino);
* (e) la scheda della singola partita dice lo stesso, in chiaro nel blocco
  «Probabilità».

Nessuna rete: le quote sono un payload finto e il calendario e' una lista.
Nessun file del repository viene toccato.

Esecuzione:
    python -m pytest SoccerMath/test_pronostico_partite.py -v
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.dirname(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import market_odds as mo  # noqa: E402
import scheda_partita as sp  # noqa: E402

import app as prod_app  # noqa: E402

ADESSO = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
FRA = "2026-10-25T18:45:00Z"

#: (casa, trasferta, terna 1/X/2) del payload finto. La terna e' quella che la
#: de-vig restituisce: ``_libro`` la ricostruisce con il margine 1,06.
PARTITE = [
    # il 2 e' l'esito piu' alto ma NON arriva alla soglia: trattino.
    ("Genoa", "Fiorentina", (0.301, 0.30, 0.399)),
    # l'1 al 64%: pronostico «1».
    ("Inter", "Roma", (0.64, 0.20, 0.16)),
    # il 2 al 58%: sopra la soglia di poco, pronostico «2».
    ("Napoli", "Lazio", (0.20, 0.22, 0.58)),
]
#: Nessun libro: la fonte non copre la partita (celle vuote, nessun pronostico).
SENZA_QUOTE = ("Bologna", "Monza")

TRATTINO = mo.TRATTINO_PRONOSTICO


def _libro(p1, pX, p2, k=1.06):
    """Un solo libro (Pinnacle) con il 6% di margine, come la fonte vera."""
    return {"key": "pinnacle", "title": "Pinnacle",
            "last_update": ADESSO.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "h2h": {"home": round(k / p1, 4), "draw": round(k / pX, 4),
                    "away": round(k / p2, 4)}}


def _payload():
    """Il file delle quote finto: tre partite con quote e una senza."""
    eventi = [{"id": 900 + i, "commence_time": FRA, "home_team": c,
               "away_team": t, "last_update": ADESSO.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "libri": [_libro(*terna)]}
              for i, (c, t, terna) in enumerate(PARTITE)]
    eventi.append({"id": 999, "commence_time": FRA, "home_team": SENZA_QUOTE[0],
                   "away_team": SENZA_QUOTE[1], "libri": []})
    return {"schema": "soccermath_live_odds_v1",
            "generato_il": ADESSO.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "leghe": {"Serie A": {"eventi": eventi}}}


def _calendario():
    """Le stesse partite nel formato di football-data (SCHEDULED)."""
    out = []
    for i, (c, t, _terna) in enumerate(PARTITE + [(SENZA_QUOTE[0], SENZA_QUOTE[1], None)]):
        out.append({"id": 900 + i, "matchday": 8, "utcDate": FRA, "status": "SCHEDULED",
                    "homeTeam": {"name": c, "shortName": c},
                    "awayTeam": {"name": t, "shortName": t},
                    "score": {"fullTime": {"home": None, "away": None}}})
    return out


def _pronostici_partite():
    """La colonna «Pronostico» della scheda Partite: {partita: sigla}."""
    payload = _payload()
    matches = _calendario()
    righe = sp.righe_partite_giornata(
        [{"lega": "Serie A", "casa": (m["homeTeam"] or {}).get("name"),
          "trasferta": (m["awayTeam"] or {}).get("name"),
          "utcDate": m.get("utcDate")} for m in matches],
        payload, ADESSO)
    return {str(r["casa_nome"]): prod_app.riga_tabella_partita(
        r, m, ADESSO)["Pronostico"] for r, m in zip(righe, matches)}


def _pronostici_top_mix():
    """La colonna «Pronostico» della scheda Pronostici: {partita: sigla}."""
    righe, _info = prod_app.righe_mercato_dalle_quote(_payload(), ADESSO)
    return {str(r["home"]): prod_app.riga_pronostico_da_mercato(
        r, ADESSO)["Pronostico"] for r in righe}


class TestIlTrattinoSottoSoglia(unittest.TestCase):
    """(a)(b)(c): 39,9% trattino, 64% «1», confine = soglia del Top Mix."""

    def test_il_2_al_399_per_cento_mostra_il_trattino(self):
        terna = {"1": 0.301, "X": 0.30, "2": 0.399}
        self.assertEqual(TRATTINO, mo.esito_ammesso(terna),
                         "il 39,9% NON e' un pronostico: trattino, non «2»")
        self.assertIsNone(prod_app.seleziona_riga_top_mix_mercato(terna),
                          "il Top Mix la stessa partita non la sceglie")
        self.assertEqual(TRATTINO, prod_app.pronostico_dalle_quote(terna))

    def test_l_1_al_64_per_cento_mostra_1(self):
        terna = {"1": 0.64, "X": 0.20, "2": 0.16}
        self.assertEqual("1", mo.esito_ammesso(terna))
        riga = prod_app.seleziona_riga_top_mix_mercato(terna)
        self.assertIsNotNone(riga)
        self.assertEqual("1", riga["esito"])
        self.assertEqual("1", prod_app.pronostico_dalle_quote(terna))

    def test_il_confine_e_la_soglia_del_top_mix(self):
        self.assertEqual(0.57, mo.SOGLIA_TOPMIX_MERCATO)
        self.assertEqual(TRATTINO, mo.esito_ammesso({"1": 0.5699, "X": 0.25, "2": 0.1801}))
        self.assertEqual("1", mo.esito_ammesso({"1": 0.57, "X": 0.25, "2": 0.18}))
        # spareggio sul PRIMO massimo, come il selettore: 1 prima di X e di 2
        self.assertEqual("1", mo.esito_ammesso({"1": 0.60, "X": 0.60, "2": 0.0}))
        self.assertEqual("X", mo.esito_ammesso({"1": 0.20, "X": 0.60, "2": 0.60}))

    def test_senza_i_tre_numeri_la_cella_resta_vuota(self):
        """Un dato che non c'e' non e' un pronostico: stringa vuota, non trattino."""
        for quote in (None, {}, {"1": 0.60, "X": 0.40}, {"1": None, "X": 0.4, "2": 0.6},
                      {"1": "0,6", "X": 0.2, "2": 0.2}, {"1": float("nan"), "X": 0.2, "2": 0.2}):
            with self.subTest(quote=quote):
                self.assertEqual("", mo.esito_ammesso(quote))
                self.assertEqual("", prod_app.pronostico_dalle_quote(quote))

    def test_la_soglia_e_un_parametro_non_un_numero_cucito(self):
        """La regola e' parametrizzata: con la soglia di v3 (0,55) il 56% entra."""
        self.assertEqual("1", mo.esito_ammesso({"1": 0.56, "X": 0.25, "2": 0.19}, 0.55))
        self.assertEqual(TRATTINO, mo.esito_ammesso({"1": 0.56, "X": 0.25, "2": 0.19}))


class TestPartiteEPronosticiDiconoLoStesso(unittest.TestCase):
    """(d): la scheda Partite e la scheda Pronostici, sulle stesse partite."""

    def test_le_partite_con_quote_hanno_un_pronostico_in_entrambe(self):
        partite = _pronostici_partite()
        top_mix = _pronostici_top_mix()
        # Solo le due partite sopra soglia entrano nel Top Mix (e quindi nella
        # scheda Pronostici): Genoa-Fiorentina (39,9%) NON c'e'.
        self.assertEqual({"Inter", "Napoli"}, set(top_mix))
        self.assertEqual("1", top_mix["Inter"])
        self.assertEqual("2", top_mix["Napoli"])

    def test_stessa_partita_stesso_pronostico(self):
        partite = _pronostici_partite()
        top_mix = _pronostici_top_mix()
        self.assertIn("Genoa", partite)
        for nome, atteso in (("Inter", "1"), ("Napoli", "2"), ("Genoa", TRATTINO)):
            with self.subTest(partita=nome):
                self.assertEqual(atteso, partite[nome],
                                 f"{nome}: la colonna di Partite")
                if nome in top_mix:
                    self.assertEqual(top_mix[nome], partite[nome],
                                     f"{nome}: Partite = Pronostici")
        # La partita fuori dal Top Mix: la scheda Pronostici non ha la riga, la
        # scheda Partite mostra il trattino (non «2», che sarebbe inventato).
        self.assertNotIn("Genoa", top_mix)
        self.assertEqual(TRATTINO, partite["Genoa"])
        self.assertNotEqual("2", partite["Genoa"])

    def test_senza_quote_nessun_pronostico_in_nessuna_delle_due(self):
        partite = _pronostici_partite()
        top_mix = _pronostici_top_mix()
        self.assertEqual("", partite[SENZA_QUOTE[0]],
                         "senza quote la cella resta vuota, non il trattino")
        self.assertNotIn(SENZA_QUOTE[0], top_mix)

    def test_parita_su_una_griglia_di_terne(self):
        """Su 500 terne: esito_ammesso = selettore del Top Mix, sempre."""
        import random
        rng = random.Random(20261019)
        for _ in range(500):
            a, b, c = (rng.uniform(0.05, 0.9) for _ in range(3))
            s = a + b + c
            # terna normalizzata: i tre numeri sommano 1 (ultimo per differenza)
            terna = {"1": round(a / s, 6), "X": round(b / s, 6)}
            terna["2"] = round(1.0 - terna["1"] - terna["X"], 6)
            sel = prod_app.seleziona_riga_top_mix_mercato(terna)
            atteso = sel["esito"] if sel is not None else TRATTINO
            self.assertEqual(atteso, mo.esito_ammesso(terna), str(terna))


class TestLaSchedaDellaPartita(unittest.TestCase):
    """(e): la scheda della singola partita mostra lo stesso pronostico."""

    def _scheda(self, casa, trasferta):
        payload = _payload()
        return sp.costruisci_scheda("Serie A", casa, trasferta, kickoff_utc=FRA,
                                    payload_quote=payload)

    def test_il_pronostico_e_nella_scheda_e_in_parole(self):
        for casa, trasferta, atteso in (("Genoa", "Fiorentina", TRATTINO),
                                        ("Inter", "Roma", "1"),
                                        ("Napoli", "Lazio", "2"),
                                        ("Bologna", "Monza", "")):
            with self.subTest(partita=f"{casa}-{trasferta}"):
                scheda = self._scheda(casa, trasferta)
                self.assertEqual(atteso, scheda["pronostico"])
                if scheda["probabilita"]["disponibile"]:
                    blocco = dict(sp.blocchi_scheda(scheda))[
                        "Probabilità (dalle quote dei bookmaker)"]
                    self.assertIn("Pronostico: " + (atteso or TRATTINO), blocco,
                                  str(blocco))
                else:
                    self.assertEqual([], [r for r in dict(sp.blocchi_scheda(scheda))[
                        "Probabilità (dalle quote dei bookmaker)"]
                        if r.startswith("Pronostico")])

    def test_le_righe_della_giornata_portano_lo_stesso_pronostico(self):
        payload = _payload()
        matches = _calendario()
        righe = sp.righe_partite_giornata(
            [{"lega": "Serie A", "casa": (m["homeTeam"] or {}).get("name"),
              "trasferta": (m["awayTeam"] or {}).get("name"),
              "utcDate": m.get("utcDate")} for m in matches],
            payload, ADESSO)
        attesi = {"Genoa": TRATTINO, "Inter": "1", "Napoli": "2",
                  SENZA_QUOTE[0]: ""}
        visti = {str(r["casa_nome"]): r["pronostico"] for r in righe}
        for nome, atteso in attesi.items():
            with self.subTest(partita=nome):
                self.assertEqual(atteso, visti[nome])
        # E la colonna della tabella legge lo stesso numero: una sola regola.
        for r, m in zip(righe, matches):
            with self.subTest(partita=str(r["casa_nome"])):
                self.assertEqual(r["pronostico"],
                                 prod_app.riga_tabella_partita(r, m, ADESSO)["Pronostico"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
