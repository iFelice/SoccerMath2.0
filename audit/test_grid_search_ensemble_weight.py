"""Test di ``audit/grid_search_ensemble_weight.py``.

Deterministici e offline. Verificano:
  * il blend a peso w e la formula delle metriche (uguaglianza con
    brier_ll_1x2 / roi_1x2 di riferimento);
  * la disciplina split: train/validation/test disgiunti, warmup applicato
    solo al campione train, selezione impossibile fuori dal train;
  * emettere predizioni su train+validation+test non cambia la traiettoria
    dello stato (le predizioni di validation sono identiche al run storico);
  * no-leakage cross-stagione: mutare il test non cambia il train;
  * bootstrap deterministico, punto dentro la CI;
  * logica significant().

Eseguibili con pytest o direttamente:
    python -m pytest audit/test_grid_search_ensemble_weight.py -q
    python audit/test_grid_search_ensemble_weight.py
"""
from __future__ import annotations

import logging
import os
import sys
import unittest
import warnings

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
for p in (_AUDIT_DIR, os.path.join(_REPO_ROOT, "SoccerMath")):
    if p not in sys.path:
        sys.path.insert(0, p)

logging.disable(logging.CRITICAL)
warnings.filterwarnings("ignore")

import grid_search_ensemble_weight as G    # noqa: E402
import diagnose_clv_pinnacle as CLV        # noqa: E402
from diagnose_production_baseline import roi_1x2  # noqa: E402


def _league_df(n_days=40, season="2024/25", start="2024-08-17"):
    """Mini df con lo schema di load_league (girone a 4, coppie cicliche)."""
    teams = ("Alpha", "Beta", "Gamma", "Delta")
    dates = pd.date_range(start, periods=n_days, freq="3D")
    rows = []
    for i, d in enumerate(dates):
        h = teams[i % 4]
        a = teams[(i + 1) % 4] if (i // 4) % 2 == 0 else teams[(i + 2) % 4]
        rows.append({"Date": d, "season": season, "HomeClean": h, "AwayClean": a,
                     "FTHG": (i * 7) % 4, "FTAG": (i * 3) % 3,
                     "FTR": "H" if (i * 7) % 4 > (i * 3) % 3 else
                            ("A" if (i * 7) % 4 < (i * 3) % 3 else "D"),
                     "B365H": 2.0 + (i % 5) * 0.1, "B365D": 3.2, "B365A": 3.6,
                     "AvgH": 2.05, "AvgD": 3.25, "AvgA": 3.55})
    return pd.DataFrame(rows)


def _multi_season_df():
    """Tre stagioni attaccate, come load_league (train+val+test)."""
    return pd.concat([
        _league_df(30, "2022/23", "2022-08-20"),
        _league_df(30, "2023/24", "2023-08-20"),
        _league_df(30, "2024/25", "2024-08-20"),
        _league_df(30, "2025/26", "2025-08-20"),
    ], ignore_index=True)


class TestBlendEMetriche(unittest.TestCase):

    def _sample(self):
        d = _multi_season_df()
        rows = CLV.run_model_with_elo(d, "Serie A", {},
                                      emit_seasons=G.ALL_SEASONS)
        rows["B365H"], rows["B365D"], rows["B365A"] = d["B365H"].to_numpy(), \
            d["B365D"].to_numpy(), d["B365A"].to_numpy()
        rows["AvgH"], rows["AvgD"], rows["AvgA"] = d["AvgH"].to_numpy(), \
            d["AvgD"].to_numpy(), d["AvgA"].to_numpy()
        return rows.reset_index(drop=True)

    def test_blend_estremi(self):
        d = self._sample()
        w1 = G.w_probs(d, 1.0)
        w0 = G.w_probs(d, 0.0)
        np.testing.assert_allclose(w1, d[["prodn_1", "prodn_X", "prodn_2"]].to_numpy(float))
        np.testing.assert_allclose(w0, d[["elo_1", "elo_X", "elo_2"]].to_numpy(float))
        mix = G.w_probs(d, G.W_PROD)
        np.testing.assert_allclose(
            mix, d[["model_1", "model_X", "model_2"]].to_numpy(float), atol=1e-12)

    def test_brier_logloss_uguale_al_riferimento(self):
        d = self._sample()
        dd, B, LL, _ = G.w_matrices(d)
        j = G.GRID_W.index(0.4)
        p = G.w_probs(dd, 0.4)
        tmp = dd.copy()
        tmp["_1"], tmp["_X"], tmp["_2"] = p[:, 0], p[:, 1], p[:, 2]
        b_ref, ll_ref = __import__("diagnose_production_baseline",
                                   fromlist=["brier_ll_1x2"]).brier_ll_1x2(
            tmp, ("_1", "_X", "_2"))
        self.assertAlmostEqual(float(B[:, j].mean()), b_ref, places=10)
        self.assertAlmostEqual(float(LL[:, j].mean()), ll_ref, places=10)

    def test_roi_uguale_a_roi_1x2(self):
        d = self._sample()
        dd, _, _, roi = G.w_matrices(d)
        j = G.GRID_W.index(0.4)
        p = G.w_probs(dd, 0.4)
        tmp = dd.copy()
        tmp["_1"], tmp["_X"], tmp["_2"] = p[:, 0], p[:, 1], p[:, 2]
        nb_ref, wr_ref, roi_ref = roi_1x2(tmp, ("_1", "_X", "_2"),
                                          ("fair_b365_1", "fair_b365_X", "fair_b365_2"),
                                          ("B365H", "B365D", "B365A"), stake=G.STAKE)
        sel = roi["b365"]["selected"][:, j]
        prof = roi["b365"]["profit"][:, j]
        self.assertEqual(int(sel.sum()), nb_ref)
        if nb_ref:
            self.assertAlmostEqual(prof.sum() / (nb_ref * G.STAKE) * 100, roi_ref, places=6)


class TestSplitDisciplina(unittest.TestCase):

    def test_split_disgiunti_e_warmup(self):
        d = _multi_season_df()
        d = CLV.run_model_with_elo(d, "Serie A", {}, emit_seasons=G.ALL_SEASONS)
        tr = G.sample_split(d, "train")
        va = G.sample_split(d, "validation")
        te = G.sample_split(d, "test")
        self.assertFalse((tr & va).any())
        self.assertFalse((tr & te).any())
        self.assertFalse((va & te).any())
        # warmup: nessuna riga train con pos < TRAIN_WARMUP
        self.assertFalse((d.loc[tr, "pos"] < G.TRAIN_WARMUP).any())
        # le righe escluse dal campione train sono esattamente le prime pos
        excluded = d[(d["season"].isin(G.TRAIN_SEASONS)) & (d["pos"] < G.TRAIN_WARMUP)]
        self.assertEqual(len(excluded), min(G.TRAIN_WARMUP, len(d)))
        # validation = solo 2024/25, test = solo 2025/26
        self.assertTrue((d.loc[va, "season"] == "2024/25").all())
        self.assertTrue((d.loc[te, "season"] == "2025/26").all())

    def test_emissioni_extra_non_cambiano_lo_stato(self):
        """Le predizioni di validation sono identiche emettendo (o meno) anche
        train/test: lo stato non dipende da emit_seasons."""
        d = _multi_season_df()
        all_rows = CLV.run_model_with_elo(d, "Serie A", {}, emit_seasons=G.ALL_SEASONS)
        eval_rows = CLV.run_model_with_elo(d, "Serie A", {})
        a = all_rows[all_rows["season"] == "2024/25"].reset_index(drop=True)
        b = eval_rows[eval_rows["season"] == "2024/25"].reset_index(drop=True)
        self.assertEqual(len(a), len(b))
        for c in ("prodn_1", "prodn_X", "prodn_2", "elo_1", "elo_X", "elo_2"):
            np.testing.assert_allclose(a[c].to_numpy(float), b[c].to_numpy(float), atol=1e-15)

    def test_no_leakage_cross_stagione(self):
        """Mutare una partita del TEST non cambia le predizioni del TRAIN."""
        d1 = _multi_season_df()
        d2 = d1.copy()
        idx_test = d2.index[d2["season"] == "2025/26"][0]
        d2.loc[idx_test, "FTHG"] += 5
        r1 = CLV.run_model_with_elo(d1, "Serie A", {}, emit_seasons=G.ALL_SEASONS)
        r2 = CLV.run_model_with_elo(d2, "Serie A", {}, emit_seasons=G.ALL_SEASONS)
        tr1 = r1[r1["season"].isin(G.TRAIN_SEASONS)].reset_index(drop=True)
        tr2 = r2[r2["season"].isin(G.TRAIN_SEASONS)].reset_index(drop=True)
        for c in ("prodn_1", "elo_1", "model_1"):
            np.testing.assert_allclose(tr1[c].to_numpy(float), tr2[c].to_numpy(float),
                                       atol=1e-15)


class TestBootstrap(unittest.TestCase):

    def test_deterministico_e_punto_in_ci(self):
        d = _multi_season_df()
        rows = CLV.run_model_with_elo(d, "Serie A", {}, emit_seasons=G.ALL_SEASONS)
        rows["B365H"], rows["B365D"], rows["B365A"] = d["B365H"].to_numpy(), \
            d["B365D"].to_numpy(), d["B365A"].to_numpy()
        rows["AvgH"], rows["AvgD"], rows["AvgA"] = d["AvgH"].to_numpy(), \
            d["AvgD"].to_numpy(), d["AvgA"].to_numpy()
        _, B, LL, roi = G.w_matrices(rows.reset_index(drop=True))
        b1 = G.boot_stats(B, LL, roi, n_boot=200, seed=11)
        b2 = G.boot_stats(B, LL, roi, n_boot=200, seed=11)
        self.assertEqual(b1["brier"][0.6], b2["brier"][0.6])
        self.assertEqual(b1["delta_brier"][0.2], b2["delta_brier"][0.2])
        for w in G.GRID_W:
            pt, ci = b1["brier"][w]["point"], b1["brier"][w]["ci"]
            self.assertLessEqual(ci[0], pt + 1e-12)
            self.assertGreaterEqual(ci[1], pt - 1e-12)
        # delta di w_ref vs se stesso = 0 con CI degenere [0, 0]
        dz = b1["delta_brier"][G.W_PROD]
        self.assertAlmostEqual(dz["point"], 0.0, places=12)

    def test_significant(self):
        self.assertTrue(G.significant({"point": 0.5, "ci": [0.1, 0.9]}))
        self.assertTrue(G.significant({"point": -0.5, "ci": [-0.9, -0.1]}))
        self.assertFalse(G.significant({"point": 0.5, "ci": [-0.1, 0.9]}))
        self.assertFalse(G.significant({"point": 0.0, "ci": [0.0, 0.0]}))
        self.assertFalse(G.significant({"point": None, "ci": [None, None]}))


class TestSelezione(unittest.TestCase):

    def test_argmin_trova_il_w_giusto_su_giocattolo(self):
        """Elo perfetto, Poisson sbagliato -> argmin = 0.0 (tutto su Elo)."""
        n = 40
        rng = np.random.default_rng(0)
        y = rng.integers(0, 3, size=n)
        oh = np.zeros((n, 3))
        oh[np.arange(n), y] = 1
        elo = np.clip(oh + rng.normal(0, 0.02, (n, 3)), 0.01, 0.98)
        elo = elo / elo.sum(axis=1, keepdims=True)
        wrong = np.roll(np.eye(3), 1, axis=0)[y]          # prob 1 sull'esito sbagliato
        d = pd.DataFrame({
            "prodn_1": wrong[:, 0], "prodn_X": wrong[:, 1], "prodn_2": wrong[:, 2],
            "elo_1": elo[:, 0], "elo_X": elo[:, 1], "elo_2": elo[:, 2],
            "model_1": 0.6 * wrong[:, 0] + 0.4 * elo[:, 0],
            "model_X": 0.6 * wrong[:, 1] + 0.4 * elo[:, 1],
            "model_2": 0.6 * wrong[:, 2] + 0.4 * elo[:, 2],
            "real_1x2": [{"0": "1", "1": "X", "2": "2"}[str(v)] for v in y],
            "B365H": 2.5, "B365D": 3.2, "B365A": 2.5,
            "AvgH": 2.5, "AvgD": 3.2, "AvgA": 2.5,
        })
        _, B, LL, _ = G.w_matrices(d)
        w_star = G.GRID_W[int(B.mean(axis=0).argmin())]
        self.assertEqual(w_star, 0.0)
        # e il Brier a w=0 deve battere quello a w=1
        self.assertLess(float(B[:, 0].mean()), float(B[:, -1].mean()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
