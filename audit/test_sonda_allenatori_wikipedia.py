"""Test offline della sonda Wikipedia (``audit/sonda_allenatori_wikipedia.py``).

Nessuna rete: le pagine sono HTML finto con la STRUTTURA della tabella «Managerial
changes» di en.wikipedia (intestazioni Team / Outgoing manager / Manner of
departure / Date of vacancy / Position in table / Replaced by / Date of
appointment, celle con rowspan, note a pie' di pagina, cella vuota). Verificano:

* la tabella giusta viene trovata e le righe si leggono senza indovinare;
* una riga con celle mancanti NON viene riempita: la lega non e' letta per intero;
* la regola: 5 leghe lette per intero, poi tutti i casi presenti con l'entrante giusto;
* il User-Agent dichiarato, nessuna chiave, nuovi tentativi su 429 e maxlag;
* il titolo di riserva (trattino) se quello con en dash non esiste.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
for _p in (str(HERE), str(REPO_ROOT), str(REPO_ROOT / "SoccerMath")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sonda_allenatori as sa  # noqa: E402
import sonda_allenatori_wikipedia as wk  # noqa: E402

CASI = HERE / "data" / "allenatori" / "casi_pubblici_2026_27.json"


def _pagina_html(righe_html: str, titolo: str = "Managerial changes") -> str:
    """Una pagina con la sezione e la tabella nella forma delle pagine di en.wikipedia."""
    return f"""
<div class="mw-parser-output">
<p>Intro della stagione.</p>
<div class="mw-heading mw-heading3"><h3 id="{titolo.replace(' ', '_')}">{titolo}</h3>
<span class="mw-editsection"><a>[edit]</a></span></div>
<table class="wikitable sortable">
<tbody>
<tr><th>Team</th><th>Outgoing manager</th><th>Manner of departure</th><th>Date of vacancy</th>
<th>Position in table</th><th>Replaced by</th><th>Date of appointment</th></tr>
{righe_html}
</tbody></table>
<div class="mw-heading mw-heading2"><h2 id="League_table">League table</h2></div>
<table class="wikitable"><tr><th>Pos</th><th>Team</th></tr></table>
</div>"""


RIGHE_SERIE_A = """
<tr><td rowspan="2"><a>Fiorentina</a></td><td><img alt="Italy"> <a>Paolo Vanoli</a></td>
<td>End of contract</td><td>5 June 2026</td><td></td>
<td><a>Fabio Grosso</a></td><td>8 June 2026</td></tr>
<tr><td><img alt="Italy"> <a>Fabio Grosso</a></td><td>Sacked</td>
<td>6 September 2026<sup class="reference">[23]</sup></td><td>20th</td>
<td><a>Paolo Vanoli</a></td><td>7 September 2026</td></tr>
<tr><td><a>Bologna</a></td><td><a>Domenico Tedesco</a></td><td></td>
<td>16 September 2026</td><td>16th</td><td><a>Raffaele Palladino</a></td>
<td>16 September 2026</td></tr>
<tr><td><a>Parma</a></td><td><a>Carlos Cuesta</a></td><td>Mutual consent</td>
<td>27 September 2026</td><td>15th</td><td><a>Alberto Gilardino</a></td>
<td>29 September 2026</td></tr>
"""

RIGHE_LIGUE1 = """
<tr><td><a>Lens</a></td><td><a>Dino Toppmöller</a></td><td>Sacked</td>
<td>15 September 2026</td><td>10th</td><td><a>Yannick Cahuzac</a></td>
<td>17 September 2026</td></tr>
"""


def _leghe_complete(letta_extra=None):
    """Le 5 pagine: Serie A e Ligue 1 con dati, le altre con una riga qualunque."""
    pagine = {
        "Serie A": {"titolo": "2026–27 Serie A", "revid": 1,
                    "url": "https://en.wikipedia.org/wiki/2026–27_Serie_A",
                    "html": _pagina_html(RIGHE_SERIE_A)},
        "Ligue 1": {"titolo": "2026–27 Ligue 1", "revid": 2, "url": "u",
                    "html": _pagina_html(RIGHE_LIGUE1)},
    }
    altre = ("Premier League", "La Liga", "Bundesliga")
    for lega in altre:
        pagine[lega] = {"titolo": f"2026–27 {lega}", "revid": 3, "url": "u",
                        "html": _pagina_html("<tr><td><a>Squadra Finta</a></td>"
                                             "<td><a>Mister Finto</a></td><td>Sacked</td>"
                                             "<td>1 October 2026</td><td>1st</td>"
                                             "<td><a>Altro Finto</a></td>"
                                             "<td>2 October 2026</td></tr>")}
    return pagine


class TestTabellaCambi(unittest.TestCase):
    def test_trova_la_tabella_e_legge_le_righe(self):
        lettura = wk.leggi_lega("Serie A", _leghe_complete()["Serie A"])
        self.assertTrue(lettura["letta"], lettura.get("nota"))
        self.assertEqual("Managerial changes", lettura["sezione"])
        righe = {r["squadra"]: r for r in lettura["righe"] if r["squadra"] != "Fiorentina"}
        self.assertEqual("Carlos Cuesta", righe["Parma"]["uscente"])
        self.assertEqual("Alberto Gilardino", righe["Parma"]["entrante"])
        self.assertEqual("2026-09-27", righe["Parma"]["data_cambio"])
        self.assertEqual("2026-09-29", righe["Parma"]["data_nomina"])
        self.assertEqual("Mutual consent", righe["Parma"]["uscita"])

    def test_rowspan_ripete_la_squadra_e_le_note_non_entrano(self):
        lettura = wk.leggi_lega("Serie A", _leghe_complete()["Serie A"])
        fiorentina = [r for r in lettura["righe"] if r["squadra"] == "Fiorentina"]
        self.assertEqual(2, len(fiorentina), "la squadra del rowspan compare nella riga 2")
        self.assertEqual(["Paolo Vanoli", "Fabio Grosso"], [r["uscente"] for r in fiorentina])
        self.assertEqual(["Fabio Grosso", "Paolo Vanoli"], [r["entrante"] for r in fiorentina])
        self.assertEqual(["2026-06-05", "2026-09-06"], [r["data_cambio"] for r in fiorentina])
        self.assertEqual("Sacked", fiorentina[1]["uscita"])
        self.assertNotIn("[23]", fiorentina[1]["data_cambio_testo"], "la nota non entra")

    def test_cella_vuota_resta_vuota_non_scivola(self):
        """Bologna: «Manner of departure» vuota: la data NON finisce nella colonna sbagliata."""
        lettura = wk.leggi_lega("Serie A", _leghe_complete()["Serie A"])
        bologna = [r for r in lettura["righe"] if r["squadra"] == "Bologna"][0]
        self.assertIsNone(bologna["uscita"])
        self.assertEqual("2026-09-16", bologna["data_cambio"])
        self.assertEqual("Raffaele Palladino", bologna["entrante"])

    def test_riga_con_celle_mancanti_non_si_indovina(self):
        """Una riga piu' corta dell'intestazione va dichiarata, e la lega NON e' letta."""
        html = _pagina_html(RIGHE_LIGUE1 +
                            "<tr><td><a>Torino</a></td><td><a>Roberto D'Aversa</a></td>"
                            "<td>12 June 2026</td><td><a>Ignazio Abate</a></td></tr>")
        lettura = wk.leggi_lega("Ligue 1", {"titolo": "t", "revid": 9, "html": html})
        self.assertFalse(lettura["letta"], "con una riga illeggibile la lega non e' letta")
        self.assertEqual(1, len(lettura["illeggibili"]))
        self.assertEqual(1, len(lettura["righe"]), "le righe buone restano lette")
        self.assertIn("non lette per intero", lettura["nota"])

    def test_colonne_non_riconosciute_non_e_letta(self):
        html = ('<div class="mw-heading"><h3>Managerial changes</h3></div>'
                '<table class="wikitable"><tr><th>Team</th><th>Outgoing manager</th>'
                '<th>Foo</th></tr><tr><td>A</td><td>B</td><td>C</td></tr></table>')
        lettura = wk.leggi_lega("Serie A", {"titolo": "t", "revid": 1, "html": html})
        self.assertFalse(lettura["letta"])
        self.assertIn("colonne non riconosciute", lettura["nota"])

    def test_sezione_assente(self):
        lettura = wk.leggi_lega("Serie A", {"titolo": "t", "revid": 1,
                                            "html": "<h2>Teams</h2><p>nulla</p>"})
        self.assertFalse(lettura["letta"])
        self.assertIn("non trovata", lettura["nota"])

    def test_data_leggibile(self):
        self.assertEqual("2026-09-13", wk.data_iso("13 September 2026"))
        self.assertEqual("2026-09-13", wk.data_iso("2026-09-13"))
        self.assertEqual("2026-06-05", wk.data_iso("5 June 2026[12]"))
        self.assertIsNone(wk.data_iso("Pre-season"))
        self.assertIsNone(wk.data_iso(""))


class TestConfrontoERegola(unittest.TestCase):
    def _letture(self, **override):
        pagine = _leghe_complete()
        letture = {l: wk.leggi_lega(l, pagine[l]) for l in wk.LEGHE}
        letture.update(override)
        return letture

    def test_casi_presenti_con_l_entrante_giusto(self):
        """Serie A e Ligue 1 hanno i dati nella fixture; Bundesliga e Liga no (finte)."""
        casi = sa.carica_casi(str(CASI))
        esiti = {e["squadra"]: e for e in wk.confronta_casi(casi, self._letture())}
        self.assertEqual(wk.ESITO_PRESENTE, esiti["Fiorentina"]["esito"])
        self.assertEqual("Paolo Vanoli", esiti["Fiorentina"]["entrante_wikipedia"])
        self.assertEqual(wk.ESITO_PRESENTE, esiti["Parma"]["esito"])
        self.assertEqual(wk.ESITO_PRESENTE, esiti["Lens"]["esito"])
        self.assertEqual(wk.ESITO_NON_TROVATO, esiti["Borussia Mönchengladbach"]["esito"])
        self.assertEqual(wk.ESITO_NON_TROVATO, esiti["Osasuna"]["esito"])

    def test_data_diversa_dal_file_e_segnalata_non_bloccata(self):
        casi = sa.carica_casi(str(CASI))
        bologna = [e for e in wk.confronta_casi(casi, self._letture()) if e["squadra"] == "Bologna"][0]
        self.assertEqual(wk.ESITO_PRESENTE, bologna["esito"], "l'entrante c'e': la data non e' regola")
        self.assertEqual("Raffaele Palladino", bologna["entrante_wikipedia"])
        self.assertFalse(bologna["data_coincide"], "file 27/09, Wikipedia 16/09: si dichiara")
        self.assertEqual("2026-09-16", bologna["data_wikipedia"])

    def test_entrante_diverso_e_squadra_assente(self):
        casi = [{"lega": "Serie A", "squadra": "Parma", "allenatore_atteso": "Pinco Pallino",
                 "allenatore_uscente": "Carlos Cuesta", "data_cambio": "2026-09-27"},
                {"lega": "Serie A", "squadra": "Napoli", "allenatore_atteso": "Massimiliano Allegri",
                 "allenatore_uscente": "Antonio Conte", "data_cambio": "2026-06-03"}]
        esiti = {e["squadra"]: e for e in wk.confronta_casi(casi, self._letture())}
        self.assertEqual(wk.ESITO_ENTRANTE_DIVERSO, esiti["Parma"]["esito"])
        self.assertEqual(wk.ESITO_NON_TROVATO, esiti["Napoli"]["esito"])

    def test_lega_non_letta_non_e_un_non_trovato(self):
        letture = self._letture()
        letture["Serie A"] = {"lega": "Serie A", "letta": False, "righe": []}
        casi = [{"lega": "Serie A", "squadra": "Parma", "allenatore_atteso": "Alberto Gilardino"}]
        self.assertEqual(wk.ESITO_LEGA_NON_LETTA, wk.confronta_casi(casi, letture)[0]["esito"])

    def test_regola_non_valutabile_senza_cinque_leghe(self):
        letture = self._letture()
        letture["Bundesliga"] = {"lega": "Bundesliga", "letta": False, "righe": []}
        letture["La Liga"] = {"lega": "La Liga", "letta": False, "righe": []}
        casi = sa.carica_casi(str(CASI))
        esito = wk.giudizio(letture, wk.confronta_casi(casi, letture))
        self.assertFalse(esito["valutabile"])
        self.assertFalse(esito["passa"])
        self.assertEqual(["non valutabile: leghe mancanti La Liga, Bundesliga"],
                         esito["motivi"])

    def test_regola_passa_solo_con_tutti_i_casi_presenti(self):
        letture = self._letture()
        casi = [{"lega": "Serie A", "squadra": "Fiorentina", "allenatore_atteso": "Paolo Vanoli"},
                {"lega": "Serie A", "squadra": "Parma", "allenatore_atteso": "Alberto Gilardino"},
                {"lega": "Ligue 1", "squadra": "Lens", "allenatore_atteso": "Yannick Cahuzac"}]
        esito = wk.giudizio(letture, wk.confronta_casi(casi, letture))
        self.assertTrue(esito["valutabile"])
        self.assertTrue(esito["passa"], esito["motivi"])
        casi.append({"lega": "Serie A", "squadra": "Parma", "allenatore_atteso": "Pinco Pallino"})
        esito2 = wk.giudizio(letture, wk.confronta_casi(casi, letture))
        self.assertFalse(esito2["passa"])
        self.assertIn("1 casi su 4 non presenti con l'entrante giusto", esito2["motivi"])

    def test_meno_di_tre_casi_non_passa(self):
        letture = self._letture()
        casi = [{"lega": "Serie A", "squadra": "Parma", "allenatore_atteso": "Alberto Gilardino"}]
        esito = wk.giudizio(letture, wk.confronta_casi(casi, letture))
        self.assertFalse(esito["passa"])
        self.assertIn("casi valutabili 1 (servono almeno 3)", esito["motivi"])

    def test_cambi_in_piu_sono_quelli_fuori_dal_file(self):
        casi = sa.carica_casi(str(CASI))
        fuori = wk.cambi_fuori_dal_file(self._letture(), casi)
        coppie = {(c["squadra"], c.get("entrante")) for c in fuori}
        self.assertNotIn(("Parma", "Alberto Gilardino"), coppie, "Parma e' nel file")
        self.assertNotIn(("Fiorentina", "Paolo Vanoli"), coppie, "il cambio del file c'e'")
        self.assertIn(("Fiorentina", "Fabio Grosso"), coppie,
                      "l'8 giugno non e' nel file: e' un cambio in piu'")
        self.assertIn(("Squadra Finta", "Altro Finto"), coppie,
                      "Premier, Liga, Bundesliga: cambi in piu'")


class TestRichiesteEMissioni(unittest.TestCase):
    def test_user_agent_dichiarato_e_nessuna_chiave(self):
        visti = []

        class Risposta:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"parse": {"title": "x", "revid": 1, "text": ""}}

        class Sessione:
            def get(self, url, params=None, headers=None, timeout=None):
                visti.append((url, dict(params or {}), dict(headers or {})))
                return Risposta()

        wk.scarica_pagina("Serie A", session=Sessione(), sleep=lambda s: None)
        url, parametri, intestazioni = visti[0]
        self.assertIn("SoccerMath2.0-audit", intestazioni["User-Agent"])
        self.assertIn("github.com/iFelice/SoccerMath2.0", intestazioni["User-Agent"])
        self.assertEqual("5", parametri["maxlag"])
        self.assertNotIn("key", " ".join(parametri).lower())
        self.assertNotIn("token", " ".join(parametri).lower())
        self.assertNotIn("auth", " ".join(intestazioni).lower())

    def test_429_ritenta_con_attesa(self):
        attese = []
        risposte = [mock.Mock(status_code=429), mock.Mock(status_code=200)]
        for r in risposte[1:]:
            r.raise_for_status.return_value = None
            r.json.return_value = {"parse": {"title": "x", "revid": 1, "text": ""}}

        class Sessione:
            def get(self, url, params=None, headers=None, timeout=None):
                return risposte.pop(0)

        dati = wk.richiedi_api({"action": "parse"}, session=Sessione(),
                               sleep=attese.append)
        self.assertIn("parse", dati)
        self.assertEqual([wk.ATTESE_RETE[0]], attese)

    def test_titolo_di_riserva_con_trattino(self):
        provati = []

        def fake(parametri, session=None, sleep=None):
            provati.append(parametri["page"])
            if "–" in parametri["page"]:
                return {"error": {"code": "missingtitle"}}
            return {"parse": {"title": parametri["page"], "revid": 7, "text": "<p/>"}}

        with mock.patch.object(wk, "richiedi_api", side_effect=fake):
            pagina = wk.scarica_pagina("Serie A", sleep=lambda s: None)
        self.assertEqual(["2026–27_Serie_A", "2026-27_Serie_A"], provati)
        self.assertEqual(7, pagina["revid"])

    def test_lega_in_errore_non_ferma_le_altre(self):
        def fake(parametri, session=None, sleep=None):
            if "Serie_A" in parametri["page"]:
                raise RuntimeError("rete giu'")
            return {"parse": {"title": parametri["page"], "revid": 2, "text": ""}}

        with mock.patch.object(wk, "richiedi_api", side_effect=fake):
            letture, chiamate, note = wk.misura_pagine(list(wk.LEGHE), sleep=lambda s: None)
        self.assertFalse(letture["Serie A"]["letta"])
        self.assertTrue(note and "Serie A" in note[0])
        self.assertEqual(5, chiamate, "una richiesta per lega, anche in errore")
        self.assertEqual(set(wk.LEGHE), set(letture))


class TestGiroCompletoConFixture(unittest.TestCase):
    """Il giro intero in modalita' fixture: nessuna rete, prefisso fixture_."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="sonda_wiki_"))
        fixture = cls.tmp / "fixture.json"
        fixture.write_text(json.dumps({"leghe": _leghe_complete()}), encoding="utf-8")
        cls.rc = wk.main(["--fixture", str(fixture), "--casi", str(CASI),
                          "--out-dir", str(cls.tmp / "data"),
                          "--results-dir", str(cls.tmp / "results")])
        cls.referti = list((cls.tmp / "results").glob("*.md"))
        cls.snapshot = list((cls.tmp / "data").glob("*.json"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_rc_file_e_prefisso(self):
        self.assertEqual(0, self.rc)
        self.assertEqual(1, len(self.snapshot))
        self.assertTrue(self.snapshot[0].name.startswith("fixture_"))
        self.assertEqual(["fixture_sonda_allenatori_wikipedia.md"],
                         [p.name for p in self.referti])

    def test_referto_dichiara_regola_prima_dei_numeri_e_fixture(self):
        testo = self.referti[0].read_text(encoding="utf-8")
        self.assertIn("RUN DI PROVA", testo.upper())
        self.assertLess(testo.index("Regola dichiarata"), testo.index("## Leghe lette"))
        self.assertLess(testo.index("## Leghe lette"), testo.index("## Casi pubblici su Wikipedia"))
        self.assertIn("lingua: **en**", testo)
        self.assertIn("NON PASSA", testo, "Premier/Liga/Bundesliga sono fixture finte: non passa")

    def test_snapshot_senza_chiavi(self):
        testo = self.snapshot[0].read_text(encoding="utf-8")
        self.assertIn("allenatori_wikipedia_v1", testo)
        self.assertNotIn("FOOTBALL_DATA_API_KEY", testo)
        self.assertNotIn("X-Auth-Token", testo)

    def test_referto_non_eseguito_non_fa_richieste(self):
        tmp = Path(tempfile.mkdtemp(prefix="sonda_wiki_non_"))
        try:
            with mock.patch.object(wk, "richiedi_api", side_effect=AssertionError("rete!")):
                rc = wk.main(["--referto-non-eseguito", "--casi", str(CASI),
                              "--results-dir", str(tmp)])
            self.assertEqual(0, rc)
            testo = (tmp / "sonda_allenatori_wikipedia.md").read_text(encoding="utf-8")
            self.assertIn("da misurare", testo)
            self.assertIn("Sonda non eseguita", testo)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
