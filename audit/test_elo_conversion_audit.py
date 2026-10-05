"""
test_elo_conversion_audit.py — controlli di correttezza delle implementazioni
usate dall'audit della conversione Elo -> 1X2 (punto 3 della roadmap).

Non verifica le CONCLUSIONI dell'audit (quelle sono misure, non invarianti):
verifica che le varianti siano quello che il referto dichiara.

  T1  A0 prodotta dall'audit == elo_probs_from_ratings di PRODUZIONE,
      bit per bit, su una griglia fitta di d.
  T2  Abeta con beta = 1 == A0, bit per bit.
  T3  _A_raw (trascrizione vettoriale senza arrotondamento) arrotondata ==
      A0 di produzione, bit per bit. Serve perche' l'ottimizzatore lavora su
      _A_raw: se divergesse, i parametri sarebbero stimati su un'altra mappa.
  T4  B preserva il punteggio atteso Elo: P(1) + P(X)/2 == e_H.
      E A0 NON lo preserva (controllo negativo).
  T5  B: terna valida (componenti >= 0) e il troncamento si attiva solo dove
      p_draw > 2*min(e_H, 1-e_H).
  T6  C: terna valida, somma 1, monotonia corretta in d con beta > 0
      (P(1) cresce, P(2) decresce) e ordine dichiarato 2 < X < 1.
  T7  C: scipy MLE e statsmodels OrderedModel danno la stessa stima su dati
      sintetici generati dal modello.
  T8  il blend usato dall'audit e' la funzione di produzione e a w = 1
      restituisce il Poisson, a w = 0 l'Elo.
  T9  bootstrap a blocchi: deterministico a parita' di seed e con IC che
      contiene la media campionaria.

Esecuzione:
    python -m pytest audit/test_elo_conversion_audit.py -v
"""
from __future__ import annotations

import os
import sys
import unittest

import numpy as np

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from models.elo_engine import elo_probs_from_ratings           # noqa: E402
import elo_conversion_audit as A                               # noqa: E402

#: griglia di d: copre il pavimento di p_draw (|d| ~ 481.6), la zona in cui
#: il vincolo di B morde (|d| ~ 604) e l'estremo osservato nei dati (~623).
D_GRID = np.concatenate([
    np.linspace(-900.0, 900.0, 4001),
    np.array([0.0, 1e-9, -1e-9, 481.6, -481.6, 604.0, -604.0, 622.7]),
])


class T1_A0_identica_alla_produzione(unittest.TestCase):
    def test_bit_exact(self):
        got = A.variante_A0(D_GRID)
        for i, dd in enumerate(D_GRID):
            p = elo_probs_from_ratings(float(dd), 0.0, 0.0)
            for j, k in enumerate(("1", "X", "2")):
                self.assertEqual(repr(float(got[i, j])), repr(float(p[k])),
                                 f"d={dd} chiave {k}")

    def test_dr_coincide_con_d(self):
        """elo_probs_from_ratings(d, 0, 0) ha dr = d + 0 - 0 = d."""
        for dd in (-321.5, 0.0, 77.25, 500.0):
            p = elo_probs_from_ratings(dd, 0.0, 0.0)
            self.assertEqual(p["elo_diff"], round(dd, 1))


class T2_Abeta_beta1_e_A0(unittest.TestCase):
    def test_bit_exact(self):
        a0 = A.variante_A0(D_GRID)
        ab = A.variante_Abeta(D_GRID, {"beta": 1.0})
        self.assertTrue((a0 == ab).all(),
                        f"max scarto {np.abs(a0 - ab).max()}")

    def test_beta_scala_anche_p_draw(self):
        """beta deve scalare l'INTERA mappa: a beta != 1 cambia anche la X."""
        x1 = A.variante_Abeta(np.array([300.0]), {"beta": 1.0})[0, 1]
        x2 = A.variante_Abeta(np.array([300.0]), {"beta": 1.5})[0, 1]
        self.assertNotEqual(x1, x2)
        # p_draw e' funzione pari e decrescente in |d|: beta>1 la riduce
        self.assertLess(x2, x1)


class T3_A_raw_coincide_con_la_produzione(unittest.TestCase):
    def test_round_di_A_raw_e_A0(self):
        raw = A._A_raw(D_GRID)
        r = np.stack(A._finalize(raw[:, 0], raw[:, 1], raw[:, 2]), axis=1)
        a0 = A.variante_A0(D_GRID)
        self.assertTrue((r == a0).all(), f"max scarto {np.abs(r - a0).max()}")


class T4_B_preserva_il_punteggio_atteso(unittest.TestCase):
    def test_B_preserva(self):
        d = D_GRID[np.abs(D_GRID) <= 480.0]        # fuori dal troncamento
        p = A.variante_B(d, raw=True)
        e_h = 1.0 / (1.0 + np.power(10.0, -d / 400.0))
        att = p[:, 0] + p[:, 1] / 2.0
        self.assertLess(float(np.abs(att - e_h).max()), 1e-12)

    def test_A0_non_preserva(self):
        d = np.array([-300.0, -100.0, 100.0, 300.0])
        p = A._A_raw(d)
        e_h = 1.0 / (1.0 + np.power(10.0, -d / 400.0))
        att = p[:, 0] + p[:, 1] / 2.0
        self.assertGreater(float(np.abs(att - e_h).max()), 1e-3)

    def test_A0_preserva_solo_in_equilibrio(self):
        p = A._A_raw(np.array([0.0]))
        self.assertAlmostEqual(p[0, 0] + p[0, 1] / 2.0, 0.5, places=12)


class T5_B_terna_valida_e_troncamento(unittest.TestCase):
    def test_non_negativa(self):
        p = A.variante_B(D_GRID, raw=True)
        self.assertGreaterEqual(float(p.min()), 0.0)

    def test_maschera_coerente(self):
        m = A.B_attiva(D_GRID)
        e_h = 1.0 / (1.0 + np.power(10.0, -D_GRID / 400.0))
        pdr = np.clip(0.27 * np.exp(-((D_GRID / 320.0) ** 2)), 0.06, 0.34)
        atteso = pdr > 2.0 * np.minimum(e_h, 1.0 - e_h)
        self.assertTrue((m == atteso).all())
        # dove NON e' attiva, P(X) di B == p_draw di A0
        p = A.variante_B(D_GRID, raw=True)
        self.assertLess(float(np.abs(p[~m, 1] - pdr[~m]).max()), 1e-12)

    def test_si_attiva_solo_in_coda(self):
        m = A.B_attiva(D_GRID)
        if m.any():
            self.assertGreater(float(np.abs(D_GRID[m]).min()), 500.0)


class T6_C_ordered_logit(unittest.TestCase):
    PAR = {"tau0": -0.58, "tau1": 0.70, "beta": 0.0061}

    def test_terna_valida(self):
        p = A.variante_C(D_GRID, self.PAR, raw=True)
        self.assertGreater(float(p.min()), 0.0)
        self.assertLess(float(np.abs(p.sum(axis=1) - 1.0).max()), 1e-12)

    def test_monotonia(self):
        d = np.linspace(-600, 600, 1001)
        p = A.variante_C(d, self.PAR, raw=True)
        self.assertTrue((np.diff(p[:, 0]) > 0).all(), "P(1) deve crescere in d")
        self.assertTrue((np.diff(p[:, 2]) < 0).all(), "P(2) deve decrescere in d")

    def test_ordine_dichiarato(self):
        """P(Y<=k)=sigmoid(tau_k-beta*d) con 2<X<1: le cumulate devono essere
        crescenti in k, cioe' P(2) <= P(2)+P(X)."""
        p = A.variante_C(D_GRID, self.PAR, raw=True)
        self.assertTrue((p[:, 1] >= 0).all())


class T7_C_scipy_vs_statsmodels(unittest.TestCase):
    def test_coincidono_su_dati_sintetici(self):
        rng = np.random.default_rng(12345)
        n = 4000
        d = rng.normal(0, 180, n)
        par = {"tau0": -0.6, "tau1": 0.7, "beta": 0.006}
        p = A.variante_C(d, par, raw=True)
        u = rng.random(n)
        cum = np.cumsum(p[:, [2, 1, 0]], axis=1)     # ordine 2, X, 1
        k = (u[:, None] > cum).sum(axis=1)           # 0->"2", 1->"X", 2->"1"
        y = np.select([k == 0, k == 1, k == 2], [2, 1, 0])
        par_s, nll_s = A.stima_C_scipy(d, y)
        par_m, nll_m, err = A.stima_C_statsmodels(d, y)
        self.assertIsNone(err, f"statsmodels non utilizzabile: {err}")
        for key in ("tau0", "tau1", "beta"):
            self.assertAlmostEqual(par_s[key], par_m[key], places=5,
                                   msg=f"{key}: scipy={par_s[key]} sm={par_m[key]}")
        self.assertAlmostEqual(nll_s, nll_m, places=9)


class T8_blend_e_di_produzione(unittest.TestCase):
    def test_estremi(self):
        P = np.array([[0.5, 0.3, 0.2], [0.1, 0.2, 0.7]])
        E = np.array([[0.4, 0.25, 0.35], [0.2, 0.3, 0.5]])
        self.assertTrue(np.allclose(A.blend(P, E, 1.0), P))
        self.assertTrue(np.allclose(A.blend(P, E, 0.0), E))
        self.assertTrue(np.allclose(A.blend(P, E, 0.25), 0.25 * P + 0.75 * E))

    def test_usa_la_funzione_di_produzione(self):
        import app as PROD_APP
        self.assertIn("blend_elo_into_1x2", A.blend.__code__.co_names)
        self.assertIs(A.PROD_APP, PROD_APP)


class T9_bootstrap(unittest.TestCase):
    def test_deterministico_e_coerente(self):
        rng = np.random.default_rng(7)
        x = rng.normal(0.001, 0.05, 2000)
        b = np.repeat(np.arange(200), 10)
        a1 = A.boot_ic(x, b)
        a2 = A.boot_ic(x, b)
        self.assertEqual(a1, a2, "bootstrap non deterministico a parita' di seed")
        m, lo, hi, nb = a1
        self.assertEqual(nb, 200)
        self.assertAlmostEqual(m, float(x.mean()), places=12)
        self.assertLess(lo, m)
        self.assertGreater(hi, m)


class T10_perdite_e_rps(unittest.TestCase):
    def test_logloss_e_brier(self):
        p = np.array([[0.6, 0.25, 0.15]])
        y = np.array([0])
        ll, br = A.perdite(p, y)
        self.assertAlmostEqual(float(ll[0]), -np.log(0.6), places=12)
        self.assertAlmostEqual(float(br[0]), (1 - 0.6) ** 2 + 0.25 ** 2 + 0.15 ** 2,
                               places=12)

    def test_rps_perfetto_e_pessimo(self):
        self.assertAlmostEqual(float(A.rps(np.array([[1.0, 0, 0]]), np.array([0]))[0]), 0.0)
        self.assertAlmostEqual(float(A.rps(np.array([[0, 0, 1.0]]), np.array([0]))[0]), 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
