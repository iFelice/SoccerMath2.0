"""Test offline del filtro di concordanza (`audit/filtro_concordanza_scarto.py`).

Tutti i test sono sintetici o sulle sole costanti/regole: nessuna costruzione
del frame della PR #49, nessuna rete, nessuna scrittura.
"""

from __future__ import annotations

import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import filtro_concordanza_scarto as F  # noqa: E402


class TestSoglieFisse(unittest.TestCase):
    def test_soglie_del_filtro_non_si_muovono(self):
        # Il prompt fissa le soglie: 0,75 e 0,05. Se qualcuno le cambia dopo aver
        # visto i dati, questo test cade.
        self.assertEqual(F.SOGLIA_ALTA, 0.75)
        self.assertEqual(F.TOLLERANZA_SCARTO, 0.05)
        self.assertEqual(F.FASCE_PM, ((0.55, 0.60), (0.60, 0.65), (0.65, 0.75)))
        self.assertEqual(F.DEFAULT_REPS, 2000)

    def test_regola_dichiarata_contiene_condizioni_a_b_e_divieto_ricerca(self):
        self.assertIn("(a)", F.RULE_TEXT)
        self.assertIn("(b)", F.RULE_TEXT)
        self.assertIn("Soglie fisse: nessuna ricerca di soglie alternative", F.RULE_TEXT)
        self.assertIn("In ogni altro caso il filtro non si adotta", F.RULE_TEXT)
        # il limite richiesto dal prompt deve stare nel referto (LIMITI)
        self.assertTrue(any("non sono vergini" in l for l in F.LIMITI))
        self.assertTrue(any("2024/25 e 2025/26" in l for l in F.LIMITI))


class TestGruppi(unittest.TestCase):
    def _frame(self, p_m, scarto):
        p_m = np.asarray(p_m, float)
        scarto = np.asarray(scarto, float)
        return pd.DataFrame({
            "p_m": p_m, "scarto": scarto,
            "passa_scarto": np.abs(scarto) <= F.TOLLERANZA_SCARTO,
            "alta": p_m >= F.SOGLIA_ALTA,
            "esclusa": ~((p_m >= F.SOGLIA_ALTA) | (np.abs(scarto) <= F.TOLLERANZA_SCARTO)),
        })

    def test_bordo_soglie(self):
        d = self._frame([0.75, 0.7499, 0.60, 0.60, 0.60, 0.60],
                        [0.50, 0.05, 0.05, -0.05, 0.0500001, -0.0500001])
        self.assertTrue(bool(d["alta"][0]))          # p_m = 0,75 passa per definizione
        self.assertFalse(bool(d["alta"][1]))
        self.assertTrue(bool(d["passa_scarto"][2]))  # |scarto| = 0,05 passa
        self.assertTrue(bool(d["passa_scarto"][3]))
        self.assertTrue(bool(d["esclusa"][4]))       # scarto > +0,05 -> esclusa
        self.assertTrue(bool(d["esclusa"][5]))       # scarto < -0,05 -> esclusa
        g = F.gruppi_tabelle(d)
        self.assertEqual(list(g["passa (|scarto| ≤ 0,05)"]), [False, True, True, True, False, False])
        self.assertEqual(list(g["esclusa (|scarto| > 0,05)"]), [False, False, False, False, True, True])
        self.assertEqual(list(g["esclusa — modello più alto (scarto > +0,05)"]),
                         [False, False, False, False, True, False])
        self.assertEqual(list(g["esclusa — modello più basso (scarto < −0,05)"]),
                         [False, False, False, False, False, True])

    def test_esclusa_e_unione_disgiunta_alta_bassa(self):
        rng = np.random.default_rng(0)
        d = self._frame(rng.uniform(0.55, 0.95, 500), rng.uniform(-0.2, 0.2, 500))
        g = F.gruppi_tabelle(d)
        unione = g["esclusa — modello più alto (scarto > +0,05)"] | \
            g["esclusa — modello più basso (scarto < −0,05)"]
        self.assertTrue(np.array_equal(unione, g["esclusa (|scarto| > 0,05)"]))
        self.assertFalse(np.any(g["esclusa — modello più alto (scarto > +0,05)"] &
                                g["esclusa — modello più basso (scarto < −0,05)"]))
        self.assertFalse(np.any(g["passa (|scarto| ≤ 0,05)"] & g["esclusa (|scarto| > 0,05)"]))


class TestBootstrap(unittest.TestCase):
    def _dati(self, n=400, seed=7):
        rng = np.random.default_rng(seed)
        d = pd.DataFrame({
            "league": rng.choice(["A", "B"], n),
            "season": rng.choice(["2024/25", "2025/26"], n),
            "date": pd.to_datetime(rng.choice(pd.date_range("2024-08-01", "2026-05-01"), n)),
        })
        y = rng.integers(0, 2, n).astype(float)
        pm = rng.uniform(0.55, 0.9, n)
        return d, y, pm

    def test_punto_ed_ic_del_gruppo(self):
        d, y, pm = self._dati()
        mask = pm < 0.75
        boot = F.BootstrapBlocchi(d, reps=500, seed=11)
        info = boot.delta_gruppo(y, pm, mask)
        self.assertAlmostEqual(info["punto"], float(y[mask].mean() - pm[mask].mean()), places=12)
        self.assertAlmostEqual(info["f"], float(y[mask].mean()), places=12)
        self.assertAlmostEqual(info["p_m"], float(pm[mask].mean()), places=12)
        self.assertEqual(info["draws"].shape, (500,))
        lo, hi = info["ic"]
        self.assertTrue(np.isfinite(lo) and np.isfinite(hi) and lo < hi)

    def test_stesso_seme_stessi_draw(self):
        d, y, pm = self._dati()
        mask = pm < 0.75
        a = F.BootstrapBlocchi(d, reps=100, seed=3).delta_gruppo(y, pm, mask)
        b = F.BootstrapBlocchi(d, reps=100, seed=3).delta_gruppo(y, pm, mask)
        self.assertTrue(np.array_equal(a["draws"], b["draws"]))
        c = F.BootstrapBlocchi(d, reps=100, seed=4).delta_gruppo(y, pm, mask)
        self.assertFalse(np.array_equal(a["draws"], c["draws"]))

    def test_diff_gruppi_appaiata(self):
        d, y, pm = self._dati()
        m1 = pm < 0.70
        m2 = pm >= 0.70
        boot = F.BootstrapBlocchi(d, reps=200, seed=5)
        i1 = boot.delta_gruppo(y, pm, m1)
        i2 = boot.delta_gruppo(y, pm, m2)
        diff = boot.diff_gruppi(i1, i2)
        self.assertAlmostEqual(diff["punto"], i1["punto"] - i2["punto"], places=12)
        self.assertTrue(np.allclose(diff["draws"], i1["draws"] - i2["draws"], equal_nan=True))

    def test_moltiplicita_dei_blocchi(self):
        # Un blocco estratto m volte porta tutte le sue righe m volte.
        d, y, pm = self._dati(n=50)
        boot = F.BootstrapBlocchi(d, reps=5, seed=2)
        ix = boot.righe_indices(0)
        conteggi = np.bincount(boot.codes[ix], minlength=boot.nb)
        attesi = boot.cnt[0] * np.array([len(r) for r in boot.rows_by_block])
        self.assertTrue(np.array_equal(conteggi, attesi))
        self.assertEqual(int(boot.cnt[0].sum()), boot.nb)  # nb estrazioni con reimmissione


class TestLogit(unittest.TestCase):
    def test_logit_fit_coincide_con_statsmodels(self):
        try:
            import statsmodels.api as sm
        except ImportError:  # pragma: no cover
            self.skipTest("statsmodels non disponibile")
        rng = np.random.default_rng(21)
        n = 600
        x1 = rng.normal(size=n)
        x2 = rng.uniform(-0.2, 0.2, n)
        eta = -0.3 + 1.2 * x1 + 2.5 * x2
        y = (rng.uniform(size=n) < 1 / (1 + np.exp(-eta))).astype(float)
        X = np.column_stack([np.ones(n), x1, x2])
        beta = F.logit_fit(X, y)
        ref = sm.Logit(y, X).fit(disp=0)
        self.assertTrue(np.allclose(beta, np.asarray(ref.params), atol=1e-8))

    def test_bootstrap_coeff_riporta_ic_e_repliche(self):
        rng = np.random.default_rng(3)
        n = 300
        d = pd.DataFrame({
            "league": rng.choice(["A", "B"], n),
            "season": ["2024/25"] * n,
            "date": pd.to_datetime(rng.choice(pd.date_range("2024-08-01", "2025-05-01"), n)),
        })
        boot = F.BootstrapBlocchi(d, reps=50, seed=1)
        x = rng.normal(size=n)
        y = (rng.uniform(size=n) < 1 / (1 + np.exp(-(0.5 + 0.8 * x)))).astype(float)
        X = np.column_stack([np.ones(n), x])
        punto, ic, n_ok = F.bootstrap_coeff(boot, X, y, reps=50)
        self.assertEqual(punto.shape, (2,))
        self.assertEqual(len(ic), 2)
        self.assertGreater(n_ok, 0)
        for lo, hi in ic:
            self.assertTrue(np.isfinite(lo) and np.isfinite(hi))


class TestRegolaAB(unittest.TestCase):
    def test_entrambe_le_condizioni(self):
        self.assertEqual(F.valuta_regola((-0.10, -0.02), (0.01, 0.09)), (True, True))

    def test_a_sotto_zero_deve_essere_tutto_l_ic(self):
        self.assertEqual(F.valuta_regola((-0.10, 0.00), (0.01, 0.09)), (False, True))
        self.assertEqual(F.valuta_regola((-0.10, -0.001), (0.01, 0.09)), (True, True))

    def test_b_sopra_zero_deve_essere_tutto_l_ic(self):
        # (a) superata: il limite e' solo (b), il cui IC tocca lo zero.
        self.assertEqual(F.valuta_regola((-0.10, -0.02), (0.0, 0.09)), (True, False))
        self.assertEqual(F.valuta_regola((-0.10, -0.02), (0.001, 0.09)), (True, True))

    def test_nan_non_supera(self):
        self.assertEqual(F.valuta_regola((float("nan"), float("nan")),
                                         (float("nan"), float("nan"))), (False, False))


class TestReferto(unittest.TestCase):
    def _payload_minimo(self):
        rig = lambda n, p, f, d, ic: {"gruppo": n, "n": 1, "p_m": p, "f": f,
                                      "delta": d, "ic": ic}  # noqa: E731
        return {
            "generato_il": "2026-10-10T00:00:00Z",
            "git": {"commit": "abc1234", "branch": "test"},
            "reps": 2000, "seed": 1, "parita_replay": True,
            "meta": {"righe_campione": 3504, "scelte": 1302, "max_scarto_devig": 0.0,
                     "n_accordo": 0},
            "tabella1": [rig("passa (|scarto| ≤ 0,05)", 0.63, 0.65, 0.02, (-0.01, 0.05)),
                         rig("esclusa (|scarto| > 0,05)", 0.63, 0.64, 0.01, (-0.02, 0.05)),
                         rig("esclusa — modello più alto", 0.64, 0.63, -0.01, (-0.05, 0.04)),
                         rig("esclusa — modello più basso", 0.62, 0.66, 0.04, (-0.03, 0.11))],
            "alta_definizione": rig("p_m ≥ 0,75", 0.80, 0.84, 0.04, (-0.01, 0.10)),
            "tabella2": [{"fascia": "[0,55-0,60)", "righe": [rig("passa", 0.57, 0.56, -0.01, (-0.08, 0.06))]}],
            "tabella3": [{"modello": "A", "repliche_valide": 2000,
                          "coefficienti": [{"nome": "b2 scarto", "stima": -1.4,
                                            "ic": (-3.4, 0.2)}]}],
            "tabella4": [rig("escluse già senza accordo", 0.59, 0.63, 0.04, (-0.05, 0.13))],
            "tabella4_nota": "nota.",
            "tabella5": [{"insieme": "insieme completo (scelte di mercato)", "n": 1302,
                          "vinte": 879, "hit": 0.6751}],
            "scelte_perse": 555, "hit_perse": 0.645,
            "esito_regola": {
                "righe": [{"condizione": "(a) ...", "misura": "f − p_m = 1,22 pt",
                           "ic": "[-2,51 pt; 5,02 pt]", "esito": "NON SUPERATA"},
                          {"condizione": "(b) ...", "misura": "differenza = 0,36 pt",
                           "ic": "[-5,20 pt; 6,11 pt]", "esito": "NON SUPERATA"}],
                "verdetto": "IL FILTRO NON SI ADOTTA",
                "frase": "non valgono (a) e (b): lo scarto resta un'informazione di contesto.",
                "a_ok": False, "b_ok": False,
                "sensibilita": {"punto": 0.011, "ic": (-0.03, 0.06), "b_ok": False}},
            "limiti": ["limite di test"],
        }

    def test_regola_prima_dei_numeri(self):
        testo = F.scrivi_referto(self._payload_minimo())
        self.assertTrue(testo.startswith(F.RULE_TEXT.rstrip().split("\n")[0]))
        i_regola = testo.index("## Regola dichiarata")
        i_numeri = testo.index("## 1. Gruppi passa / esclusa")
        self.assertLess(i_regola, i_numeri)
        # nessuna cifra prima della regola dichiarata
        prima = testo[:i_regola]
        self.assertNotRegex(prima, r"\d,\d")

    def test_referto_riporta_verdetto_e_limiti(self):
        testo = F.scrivi_referto(self._payload_minimo())
        self.assertIn("IL FILTRO NON SI ADOTTA", testo)
        self.assertIn("limite di test", testo)
        self.assertIn("Scelte perse dal filtro: **555**", testo)


if __name__ == "__main__":
    unittest.main()
