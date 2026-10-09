"""Test AppTest: Calcola Top Mix -> Multipla.

Obiettivo: verificare che, dopo la selezione di 2 righe nel multiselect,
tabella e calcolatore restino visibili e i valori siano corretti.

Ostacolo con AppTest.from_file('app.py'):
  AppTest.from_file re-esegue l'intero file (3700+ righe) ad ogni at.run().
  Le funzioni definite con @st.cache_data vengono ridefinite dal decoratore,
  sovrascrivendo i mock applicati con mock.patch.object. Il pulsante attiva
  il blocco if st.button() che invoca fetch_and_calc_top_mix() (HTTP reale),
  e il mock non sopravvive alla re-esecuzione.

Soluzione: script di test standalone che replica il flusso tab2 usando le
funzioni REALI (multipla da market_odds) con dati finti, senza ri-eseguire
i 3700+ righe di app.py.
"""

import os
import sys
import tempfile
import shutil
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _riga_finta(match_id, home, away, prob_val, quota, rank=1):
    """Riga come la produce argomenti_registro_top_mix_mercato."""
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


TEST_SCRIPT = '''\
import streamlit as st
import pandas as pd
import sys, os
sys.path.insert(0, os.environ.get("TEST_DIR", "SoccerMath"))
from market_odds import multipla, MASSIMO_RIGHE_MULTIPLA, AVVISO_INDIPENDENZA

def etichetta(p):
    return ("#%(rank)s %(home)s vs %(away)s — %(esito)s"
            " (%(prob_val)s%% @ %(quota)s)") % p

righe = st.session_state.get("topmix_mercato", [])

if righe:
    st.markdown("##### Top Mix tabella")
    df = pd.DataFrame([{
        "Partita": r["home"] + " vs " + r["away"],
        "Esito": r["esito"],
        "P mercato %%": r["prob_val"],
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
        esito = multipla([{"partita": p["home"] + " vs " + p["away"],
                           "esito": p["esito"], "prob": p["prob"],
                           "quota": p["quota"]} for p in sel])
        if esito.get("ok"):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Prob combinata",
                      "%.2f%%" % (esito["probabilita_combinata"] * 100))
            c2.metric("Quota equa",
                      "%.2f" % esito["quota_equa"])
            c3.metric("Quota offerta",
                      "%.2f" % esito["quota_offerta"])
            c4.metric("Edge",
                      "%+.2f%%" % (esito["edge"] * 100))
            st.dataframe(pd.DataFrame(esito["righe"]).rename(columns={
                "n": "#", "partita": "Partita", "esito": "Esito",
                "prob": "Prob", "quota": "Quota",
            }), width="stretch", hide_index=True)
'''


class TestAppTestMultipla(unittest.TestCase):
    """AppTest: Calcola Top Mix -> seleziona 2 righe -> verifica multipla."""

    def test_flusso_completo_multipla(self):
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:
            self.skipTest("streamlit.testing.v1 non disponibile")

        os.environ["TEST_DIR"] = HERE
        tmpdir = tempfile.mkdtemp()
        script_path = os.path.join(tmpdir, "test_tab2.py")
        with open(script_path, "w") as f:
            f.write(TEST_SCRIPT)

        try:
            at = AppTest.from_file(script_path)

            # --- Step 1: Run iniziale, niente ---
            at.run(timeout=30)
            dfs0 = [e for e in at if type(e).__name__ == "Dataframe"]
            ms0 = [e for e in at if type(e).__name__ == "Multiselect"]
            self.assertEqual(len(dfs0), 0, "DF prima dei dati")
            self.assertEqual(len(ms0), 0, "MS prima dei dati")

            # --- Step 2: Pre-popola session_state ---
            r1 = _riga_finta(12345, "Juventus", "Milan", 72.0, 1.39, rank=1)
            r2 = _riga_finta(12346, "Inter", "Roma", 65.0, 1.54, rank=2)
            at.session_state["topmix_mercato"] = [r1, r2]
            at.run(timeout=30)

            # --- Step 3: Tabella visibile ---
            dfs = [e for e in at if type(e).__name__ == "Dataframe"]
            self.assertGreater(len(dfs), 0, "Tabella non visibile")

            # --- Step 4: Multiselect visibile ---
            mss = [e for e in at if type(e).__name__ == "Multiselect"]
            self.assertGreater(len(mss), 0, "Multiselect non visibile")
            ms = mss[0]
            self.assertEqual(ms.key, "multipla_selezione")
            self.assertEqual(len(ms.options), 2)

            # --- Step 5: Seleziona 2 righe -> RERUN ---
            ms.set_value([ms.options[0], ms.options[1]])
            at.run(timeout=30)

            dfs2 = [e for e in at if type(e).__name__ == "Dataframe"]
            ms2 = [e for e in at if type(e).__name__ == "Multiselect"]
            self.assertGreater(len(dfs2), 0, "Tabella scomparsa!")
            self.assertGreater(len(ms2), 0, "Multiselect scomparso!")

            # --- Step 6: Valori del calcolatore ---
            metrics = {}
            for m in at.metric:
                metrics[m.label] = m.value

            p1, p2 = 0.72, 0.65
            q1, q2 = 1.39, 1.54
            ep = p1 * p2
            ee = 1.0 / ep
            eq = q1 * q2
            ed = eq / ee - 1.0

            self.assertIn("Prob combinata", metrics,
                          "metrics: %s" % list(metrics.keys()))
            self.assertIn("Quota equa", metrics)
            self.assertIn("Quota offerta", metrics)
            self.assertIn("Edge", metrics)

            pv = float(metrics["Prob combinata"].replace("%", ""))
            self.assertAlmostEqual(pv, ep * 100, places=1)
            ev = float(metrics["Quota equa"])
            self.assertAlmostEqual(ev, ee, places=1)
            ov = float(metrics["Quota offerta"])
            self.assertAlmostEqual(ov, eq, places=1)
            dv = float(metrics["Edge"].replace("%", "").replace("+", ""))
            self.assertAlmostEqual(dv, ed * 100, places=1)

            # 2 DF = tabella Top Mix + tabella multipla
            self.assertGreaterEqual(len(dfs2), 2,
                                    "DF multipla mancante: solo %d" % len(dfs2))

            print("\n✅ TUTTI I CHECK APPTEST PASSATI")
            print("   DF=%d, MS key=multipla_selezione opts=%d" % (
                len(dfs2), len(ms2[0].options)))
            print("   Prob=%.2f%% (%.2f), Equa=%.2f (%.2f), "
                  "Offerta=%.2f (%.2f), Edge=%+.2f%% (%+.2f%%)" % (
                      pv, ep * 100, ev, ee, ov, eq, dv, ed * 100))

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
            del os.environ["TEST_DIR"]

if __name__ == "__main__":
    unittest.main()