"""Test di ``audit/elo_w025_confirmation.py`` (helper puri, offline).

Il meccanismo numerico riutilizzato (walker, matrici per-w, boot_stats,
significant) e' gia' coperto dai 9 test di
``test_grid_search_ensemble_weight.py``: qui si testano i pezzi NUOVI:
  * patch della griglia a (0.25, 0.6) coerente con boot_stats (delta vs 0.6);
  * inserimento NON distruttivo della sezione nel report (idempotente,
    il resto del markdown resta intatto);
  * verdetto: conteggi di segno/significativita' sulle celle.
"""
from __future__ import annotations

import logging
import os
import sys
import unittest
import warnings

import numpy as np

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
if _AUDIT_DIR not in sys.path:
    sys.path.insert(0, _AUDIT_DIR)

logging.disable(logging.CRITICAL)
warnings.filterwarnings("ignore")

import grid_search_ensemble_weight as GS   # noqa: E402
import elo_w025_confirmation as W          # noqa: E402


class TestPatchGriglia(unittest.TestCase):
    def setUp(self):
        self._grid = GS.GRID_W
        GS.GRID_W = (W.W_NEW, W.W_OLD)

    def tearDown(self):
        GS.GRID_W = self._grid

    def test_boot_stats_delta_vs_060_con_griglia_ridotta(self):
        rng = np.random.default_rng(3)
        n = 150
        p = rng.dirichlet([2, 2, 2], size=n)
        y = rng.integers(0, 3, size=n)
        oh = np.zeros((n, 3))
        oh[np.arange(n), y] = 1
        # colonna 0.25 IDENTICA a 0.6 -> delta esattamente 0, CI [0, 0]
        B = np.stack([((oh - p) ** 2).sum(axis=1)] * 2, axis=1)
        LL = np.stack([-np.log(np.clip(p[np.arange(n), y], 1e-12, 1.0))] * 2, axis=1)
        roi = {"b365": {"profit": np.zeros((n, 2)),
                        "selected": np.zeros((n, 2), dtype=bool)},
               "avg": {"profit": np.zeros((n, 2)),
                       "selected": np.zeros((n, 2), dtype=bool)}}
        boot = GS.boot_stats(B, LL, roi, w_ref=W.W_OLD, n_boot=100, seed=1)
        d = boot["delta_brier"][W.W_NEW]
        self.assertEqual(d["point"], 0.0)
        self.assertEqual(d["ci"], [0.0, 0.0])
        self.assertFalse(GS.significant(d))
        # e con la colonna 0.25 sistematicamente migliore -> significativo
        B2 = B.copy()
        B2[:, 0] -= 0.01
        boot2 = GS.boot_stats(B2, LL, roi, w_ref=W.W_OLD, n_boot=100, seed=1)
        self.assertTrue(GS.significant(boot2["delta_brier"][W.W_NEW]))
        self.assertLess(boot2["delta_brier"][W.W_NEW]["point"], 0.0)


class TestReplaceSection(unittest.TestCase):
    BASE = ("# Titolo\n\n## Sezione A\ntesto A\n\n## Limiti\ntesto L\n")

    def test_append_e_poi_replace_idempotente(self):
        sec1 = W.MARK_START + "\n## Conferma cambio produzione: X\n\nA\n" + W.MARK_END + "\n"
        out1 = W.replace_or_append_section(self.BASE, sec1)
        self.assertIn("## Sezione A", out1)
        self.assertIn("## Limiti", out1)
        self.assertEqual(out1.count(W.MARK_START), 1)
        self.assertTrue(out1.index("## Conferma") > out1.index("## Limiti"))
        sec2 = (W.MARK_START + "\n## Conferma cambio produzione: X\n\nB\n"
                + W.MARK_END + "\n")
        out2 = W.replace_or_append_section(out1, sec2)
        self.assertEqual(out2.count(W.MARK_START), 1)
        self.assertIn("\nB\n", out2)
        self.assertNotIn("\nA\n", out2)
        self.assertIn("## Sezione A", out2)          # resto intatto
        self.assertIn("testo L", out2)
        # terzo giro: stabile
        out3 = W.replace_or_append_section(out2, sec2)
        self.assertEqual(out3, out2)

    def test_append_con_file_senza_newline_finale(self):
        out = W.replace_or_append_section("# x\nnessun newline", "SEC")
        self.assertTrue(out.startswith("# x\nnessun newline\n\nSEC"))


class TestVerdetto(unittest.TestCase):
    @staticmethod
    def _cell(delta_brier, sig, n=100):
        po = {"w": 0.6, "brier": 0.60, "log_loss": 1.00, "n_bet_b365": n,
              "roi_b365": -2.0, "n_bet_avg": n, "roi_avg": -2.0}
        pn = {"w": 0.25, "brier": 0.60 + delta_brier, "log_loss": 1.00,
              "n_bet_b365": n, "roi_b365": -3.0, "n_bet_avg": n, "roi_avg": -3.0}
        roi = {(0.6, "b365"): {"point": -2.0, "ci": [-10.0, 10.0]},
               (0.25, "b365"): {"point": -3.0, "ci": [-10.0, 10.0]},
               (0.6, "avg"): {"point": -2.0, "ci": None},
               (0.25, "avg"): {"point": -3.0, "ci": None}}
        return {"n": n, "point": {0.6: po, 0.25: pn},
                "delta_brier": {"point": delta_brier, "ci": [-1.0, 1.0]},
                "delta_log_loss": {"point": delta_brier, "ci": [-1.0, 1.0]},
                "sig_brier": sig, "sig_log_loss": sig, "roi": roi,
                "j_old": 1, "j_new": 0}

    def _payload(self, deltas_v, deltas_t, agg_sig=True):
        """deltas_*: lista di 5 delta Brier per lega (positivo=peggioramento)."""
        cells = {}
        for camp, dv, dt in zip(("L1", "L2", "L3", "L4", "L5"), deltas_v, deltas_t):
            for sp, dv_ in (("validation", dv), ("test", dt)):
                sig = abs(dv_) > 0.005
                cells[(camp, sp)] = self._cell(dv_, sig)
        cells[("AGGREGATO", "validation")] = self._cell(-0.01, agg_sig, n=500)
        cells[("AGGREGATO", "test")] = self._cell(-0.01, agg_sig, n=500)
        return {"cells": cells, "w_new": 0.25, "w_old": 0.6,
                "n_boot": 2000, "seed": 1, "generated_at": "x"}

    def test_verdetto_confermato(self):
        neg = [-0.02, -0.01, -0.015, -0.003, -0.012]   # la quarta non sig
        sec = W.render_section(self._payload(neg, neg))
        self.assertIn("SODDISFATTA", sec)
        self.assertIn("10/10 delta per-(lega,split) negativi", sec)
        self.assertIn("nessuna cella (lega, split) mostra un PEGGIORAMENTO", sec)

    def test_verdetto_non_soddisfatto_se_aggregato_non_sig(self):
        neg = [-0.02] * 5
        sec = W.render_section(self._payload(neg, neg, agg_sig=False))
        self.assertIn("NON è soddisfatta", sec)

    def test_verdetto_attenzione_se_celle_peggiorano(self):
        pos = [0.02] * 5
        sec = W.render_section(self._payload(pos, pos))
        self.assertIn("ATTENZIONE", sec)
        self.assertIn("Conferma parziale", sec)


if __name__ == "__main__":
    unittest.main(verbosity=2)
