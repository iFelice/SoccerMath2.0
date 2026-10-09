"""Test AppTest standalone del calcolatore di multipla (Top Mix -> multipla).

Obiettivo: verificare che, dopo la selezione di 2 righe nel multiselect, tabella
e calcolatore restino visibili, che i valori siano quelli giusti e che il margine
compaia SOLO se la quota del bookmaker e' stata inserita (punto 3 delle
rifiniture dopo la PR #53: prima il confronto era con il prodotto delle quote
della fonte, sempre negativo per costruzione, e non diceva niente).

Perche' uno script a parte, ora che esiste ``test_apptest_top_mix.py``: quel file
e' la prova sul VERO ``app.py`` (pulsante, HTTP finto, scrittura del Registro una
volta sola). Questo resta il giro veloce del solo calcolatore, e vale come
documentazione del contratto ``multipla`` + campo opzionale anche per chi legge
senza streamlit: ``AppTest.from_file('app.py')`` re-esegue 3900 righe a ogni
``at.run()`` e le funzioni ``@st.cache_data`` vengono ridefinite dal decoratore,
quindi i mock del pulsante non sopravvivono (e un run costa ~70 s).

Lo script qui sotto replica il flusso tab2 chiamando le funzioni REALI
(``market_odds.multipla``) con righe finte: nessuna rete, nessun file scritto.
"""

import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _riga_finta(match_id, home, away, prob_val, quota, rank=1):
    """Riga come la produce il percorso di scrittura del Top Mix di mercato."""
    return {
        "match_id": match_id, "home": home, "away": away,
        "league": "Serie A", "giornata": 8,
        "utcDate": "2026-10-11T18:00:00Z",
        "market": "1", "esito": "1",
        "prob_val": prob_val, "prob": prob_val / 100.0,
        "quota": quota, "rank": rank,
        "prob_modello_val": prob_val - 5, "accordo": True,
        "fonte": "pinnacle", "n_libri": 1,
        "poisson": (prob_val - 7) / 100.0, "elo": (prob_val - 1) / 100.0,
        "elo_disponibile": True, "mercato_standard": "1",
        "quote_live_istante": "2026-10-09T08:00:00Z",
    }


TEST_SCRIPT = '''import streamlit as st
import pandas as pd
import sys, os
sys.path.insert(0, os.environ.get("TEST_DIR", "SoccerMath"))
from market_odds import multipla, MASSIMO_RIGHE_MULTIPLA, AVVISO_INDIPENDENZA


def etichetta(p):
    return ("#%(rank)s %(home)s vs %(away)s - %(esito)s"
            " (%(prob_val)s%% @ %(quota)s)") % p


righe = st.session_state.get("topmix_mercato", [])

if righe:
    st.markdown("##### Top Mix tabella")
    df = pd.DataFrame([{
        "Partita": r["home"] + " vs " + r["away"],
        "Esito": r["esito"],
        "P mercato %": r["prob_val"],
        "Quota mercato": r["quota"],
    } for r in righe])
    st.dataframe(df, width="stretch", hide_index=True)

    st.markdown("##### Calcolatore di multipla")
    etichette = [etichetta(p) for p in righe]
    scelte = st.multiselect(
        "Seleziona fino a 5 righe", etichette,
        max_selections=MASSIMO_RIGHE_MULTIPLA,
        key="multipla_selezione",
    )
    st.caption(AVVISO_INDIPENDENZA)
    if scelte:
        per_e = {etichetta(p): p for p in righe}
        sel = [per_e[e] for e in scelte if e in per_e]
        quota_bookmaker = st.number_input(
            "Quota offerta dal tuo bookmaker (opzionale)",
            min_value=0.0, step=0.01, format="%.2f", value=None,
            key="multipla_quota_bookmaker")
        esito = multipla([{"partita": p["home"] + " vs " + p["away"],
                           "esito": p["esito"], "prob": p["prob"],
                           "quota": p["quota"]} for p in sel],
                         quota_bookmaker=quota_bookmaker)
        if esito.get("ok"):
            c1, c2, c3 = st.columns(3)
            c1.metric("Prob combinata",
                      "%.2f%%" % (esito["probabilita_combinata"] * 100))
            c2.metric("Quota equa", "%.2f" % esito["quota_equa"])
            if esito.get("margine") is None:
                c3.caption("Margine: non calcolato (nessuna quota inserita).")
            else:
                c3.metric("Margine sulla tua quota",
                          "%+.2f%%" % (esito["margine"] * 100))
            if esito.get("errore_quota_bookmaker"):
                st.warning(esito["errore_quota_bookmaker"])
            st.dataframe(pd.DataFrame(esito["righe"]).rename(columns={
                "n": "#", "partita": "Partita", "esito": "Esito",
                "prob": "Prob", "quota": "Quota (fonte)",
            }), width="stretch", hide_index=True)
'''


class TestAppTestMultipla(unittest.TestCase):
    """AppTest standalone: seleziona 2 righe -> verifica multipla e margine."""

    @classmethod
    def setUpClass(cls):
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:                                      # pragma: no cover
            raise unittest.SkipTest("streamlit.testing.v1 non disponibile")
        cls.tmpdir = tempfile.mkdtemp(prefix="sm_multipla_")
        cls.script = os.path.join(cls.tmpdir, "test_tab2.py")
        with open(cls.script, "w", encoding="utf-8") as f:
            f.write(TEST_SCRIPT)
        os.environ["TEST_DIR"] = HERE
        r1 = _riga_finta(12345, "Juventus", "Milan", 72.0, 1.39, rank=1)
        r2 = _riga_finta(12346, "Inter", "Roma", 65.0, 1.54, rank=2)
        cls.righe = [r1, r2]
        cls.prob = r1["prob"] * r2["prob"]
        cls._AppTest = AppTest

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("TEST_DIR", None)
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def setUp(self):
        # Un AppTest NUOVO per test: la sessione mantiene i widget fra un run e
        # l'altro, e una prova che scrive 1,85 nel campo della quota lascerebbe
        # il margine gia' compilato nella prova che vuole il campo VUOTO.
        self.at = self._AppTest.from_file(self.script, default_timeout=120)
        self.at.session_state["topmix_mercato"] = self.righe
        self.at.run()

    def metriche(self):
        return {m.label: m.value for m in self.at.metric}

    def _seleziona_due_righe(self):
        """Seleziona le due righe e fa girare di nuovo (il rerun del multiselect)."""
        ms = self.at.multiselect[0]
        ms.set_value(list(ms.options))
        self.at.run()
        self.assertEqual([], [str(e.value) for e in self.at.exception])

    def test_prima_della_selezione_solo_la_tabella(self):
        dfs = [e for e in self.at if type(e).__name__ == "Dataframe"]
        self.assertEqual(1, len(dfs), "la tabella del Top Mix c'e', la multipla no")
        ms = self.at.multiselect[0]
        self.assertEqual("multipla_selezione", ms.key)
        self.assertEqual(2, len(ms.options))
        self.assertEqual([], list(self.at.number_input),
                         "il campo della quota non si mostra senza selezione")
        self.assertNotIn("Prob combinata", self.metriche())

    def test_selezione_senza_quota_del_bookmaker(self):
        """Due righe selezionate e campo VUOTO: valori giusti, nessun margine."""
        self._seleziona_due_righe()

        # tabella e calcolatore restano visibili (era il bug del rerun)
        dfs = [e for e in self.at if type(e).__name__ == "Dataframe"]
        self.assertGreaterEqual(len(dfs), 2, "tabella Top Mix + tabella multipla")
        self.assertEqual(1, len(self.at.multiselect), "il multiselect non e' sparito")
        self.assertEqual(2, len(self.at.multiselect[0].value))

        m = self.metriche()
        self.assertIn("Prob combinata", m, list(m))
        self.assertIn("Quota equa", m, list(m))
        self.assertAlmostEqual(self.prob * 100,
                               float(m["Prob combinata"].replace("%", "")), places=1)
        self.assertAlmostEqual(1.0 / self.prob, float(m["Quota equa"]), places=2)
        self.assertNotIn("Margine sulla tua quota", m,
                         "senza quota inserita il margine non si mostra")
        self.assertNotIn("Edge", m, "il vecchio confronto con le quote della fonte e' sparito")
        self.assertNotIn("Quota offerta", m, "e non si mostra piu' il prodotto delle quote del file")

        ni = [n for n in self.at.number_input if n.key == "multipla_quota_bookmaker"]
        self.assertEqual(1, len(ni), "il campo opzionale c'e' ed e' vuoto")
        self.assertIsNone(ni[0].value, "nessun valore di default: nessuna quota inventata")
        # e il testo che lo dichiara sta nella pagina
        testi = " ".join(getattr(e, "value", "") or "" for e in self.at.caption)
        self.assertIn("non calcolato", testi)

    def test_selezione_con_quota_del_bookmaker(self):
        """Quota inserita: margine = quota * probabilita' combinata - 1."""
        self._seleziona_due_righe()
        quota = 1.85
        ni = [n for n in self.at.number_input if n.key == "multipla_quota_bookmaker"][0]
        ni.set_value(quota)
        self.at.run()
        self.assertEqual([], [str(e.value) for e in self.at.exception])
        m = self.metriche()
        self.assertIn("Margine sulla tua quota", m, list(m))
        atteso = quota * self.prob - 1.0
        mostrato = float(m["Margine sulla tua quota"].replace("%", "").replace("+", ""))
        self.assertAlmostEqual(atteso * 100, mostrato, places=2)
        self.assertLess(atteso, 0.0, "il fixture e' fatto per dare margine negativo")
        # i due numeri che restano validi anche con la quota piena
        self.assertAlmostEqual(1.0 / self.prob, float(m["Quota equa"]), places=2)
        self.assertEqual(1, len([n for n in self.at.number_input
                                if n.key == "multipla_quota_bookmaker"]))
        self.assertEqual(quota, self.at.session_state["multipla_quota_bookmaker"],
                         "il campo sopravvive al rerun (persistenza, problema 1)")

    def test_quota_impossibile_si_dice_e_non_inventa(self):
        """Quota 1,00 (non e' una quota decimale): avviso, nessun margine."""
        self._seleziona_due_righe()
        ni = [n for n in self.at.number_input if n.key == "multipla_quota_bookmaker"][0]
        # ``min_value=0.0`` lascia scrivere 1,00: la validita' la giudica multipla
        ni.set_value(1.0)
        self.at.run()
        self.assertEqual([], [str(e.value) for e in self.at.exception])
        m = self.metriche()
        self.assertNotIn("Margine sulla tua quota", m, list(m))
        avvisi = [str(w.value) for w in self.at.warning]
        self.assertTrue(any("bookmaker" in a for a in avvisi), avvisi)


if __name__ == "__main__":
    unittest.main(verbosity=2)
