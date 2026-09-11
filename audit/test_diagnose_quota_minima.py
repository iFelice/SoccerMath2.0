"""Test di ``audit/diagnose_quota_minima.py``.

Deterministici e offline. Coprono il punto 7 del protocollo:
  * join corretto per CIASCUNA fonte di quota (CSV B365 per 1X2/O-U,
    JSON BTTS per GG/NG riusando join_btts_file);
  * nessuna quota negativa/NaN/mancante finita silenziosamente in un bucket;
  * soglia: bordo 1,50 incluso nel gruppo >= 1,50;
  * bootstrap deterministico, punto dentro la CI, delta appaiati;
  * Brier identico a topmix_margins.quality (stessa definizione);
  * import pura di seleziona_riga_top_mix da SoccerMath/app.py;
  * integrazione col replay reale (se il CSV committato esiste).

Eseguibili con pytest o direttamente:
    python -m pytest audit/test_diagnose_quota_minima.py -q
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
for _p in (_AUDIT_DIR, _REPO_ROOT, os.path.join(_REPO_ROOT, "SoccerMath")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

logging.disable(logging.CRITICAL)
warnings.filterwarnings("ignore")

import diagnose_quota_minima as Q                        # noqa: E402
from topmix_margins import quality                       # noqa: E402


# =====================================================================
# Fixture compatte
# =====================================================================
def _admitted_row(**kw):
    base = {"league": "Serie A", "season_label": "2024/25", "matchday": 1,
            "home": "Alpha", "away": "Beta", "kickoff": "2024-08-18T17:30:00Z",
            "fthg": 2, "ftag": 1, "A_market": "1", "A_conf": 0.65,
            "A_admitted": True, "A_hit": 1}
    base.update(kw)
    return base


def _rows_df(*rows):
    return pd.DataFrame(list(rows))


class TestExpectedHit(unittest.TestCase):
    def test_mappa_mercato_esito(self):
        self.assertEqual(Q.expected_hit("1", 2, 1), 1)
        self.assertEqual(Q.expected_hit("1", 1, 1), 0)
        self.assertEqual(Q.expected_hit("2", 0, 1), 1)
        self.assertEqual(Q.expected_hit("X", 1, 1), 1)
        self.assertEqual(Q.expected_hit("O2.5", 2, 1), 1)
        self.assertEqual(Q.expected_hit("O2.5", 1, 1), 0)
        self.assertEqual(Q.expected_hit("U2.5", 1, 1), 1)
        self.assertEqual(Q.expected_hit("U2.5", 2, 1), 0)
        self.assertEqual(Q.expected_hit("GG", 1, 1), 1)
        self.assertEqual(Q.expected_hit("GG", 1, 0), 0)
        self.assertEqual(Q.expected_hit("NG", 1, 0), 1)
        self.assertEqual(Q.expected_hit("NG", 1, 1), 0)
        self.assertIsNone(Q.expected_hit("BOH", 1, 1))


class TestAttachRealOdds(unittest.TestCase):
    """Join per ciascuna fonte su indici costruiti a mano (il test del build
    vero dagli artefatti reali e' in TestIntegrazioneReplay)."""

    CSV_IDX = {("SerieA", "2024/25", "Alpha", "Beta"):
               {"date": pd.Timestamp("2024-08-18"),
                "odds": {"B365H": 1.80, "B365D": 3.4, "B365A": 4.2,
                         "B365>2.5": 1.90, "B365<2.5": 1.95}}}
    BTTS_IDX = {("SerieA", "2024/25", "Alpha", "Beta"):
                {"date": pd.Timestamp("2024-08-18"),
                 "o_yes": 1.85, "o_no": 2.05, "book": "bet365"}}

    def test_quote_per_mercato_da_indici(self):
        rows = _rows_df(
            _admitted_row(A_market="1", A_hit=1, fthg=2, ftag=1),
            _admitted_row(A_market="2", A_hit=0, fthg=2, ftag=1),
            _admitted_row(A_market="O2.5", A_hit=1, fthg=2, ftag=1),
            _admitted_row(A_market="U2.5", A_hit=0, fthg=2, ftag=1),
            _admitted_row(A_market="GG", A_hit=1, fthg=2, ftag=1),
            _admitted_row(A_market="NG", A_hit=0, fthg=2, ftag=1),
        )
        attached, cov = Q.attach_real_odds(rows, self.CSV_IDX, self.BTTS_IDX)
        self.assertEqual(len(attached), 6)
        self.assertEqual(cov.get("excluded", 0), 0)
        odds = dict(zip(attached["market"], attached["odds"]))
        self.assertEqual(odds["1"], 1.80)      # B365H
        self.assertEqual(odds["2"], 4.20)      # B365A
        self.assertEqual(odds["O2.5"], 1.90)   # B365>2.5
        self.assertEqual(odds["U2.5"], 1.95)   # B365<2.5
        self.assertEqual(odds["GG"], 1.85)     # o_yes BTTS
        self.assertEqual(odds["NG"], 2.05)     # o_no BTTS

    def test_esclusioni_contate_mai_in_bucket(self):
        csv_bad = {("SerieA", "2024/25", "Alpha", "Beta"):
                   {"date": pd.Timestamp("2024-08-18"),
                    "odds": {"B365H": np.nan, "B365A": 0.5,
                             "B365>2.5": 1.90, "B365<2.5": 1.95}}}
        rows = _rows_df(
            _admitted_row(A_market="1", A_hit=1, fthg=2, ftag=1),           # NaN
            _admitted_row(A_market="2", A_hit=0, fthg=2, ftag=1),           # <=1.0
            _admitted_row(A_market="X", A_hit=1, fthg=1, ftag=1),           # assente
            _admitted_row(home="Gamma", away="Delta", A_market="1",
                          A_hit=1, fthg=2, ftag=1),                          # coppia assente
            _admitted_row(A_market="DC", A_hit=0, fthg=2, ftag=1),          # mercato ignoto
        )
        attached, cov = Q.attach_real_odds(rows, csv_bad, self.BTTS_IDX)
        self.assertEqual(len(attached), 0)
        self.assertEqual(cov["quota_nan"], 1)
        self.assertEqual(cov["quota_non_valida"], 1)
        self.assertEqual(cov["quota_mancante_csv"], 1)
        self.assertEqual(cov["coppia_assente_csv"], 1)
        self.assertEqual(cov["mercato_sconosciuto"], 1)
        self.assertEqual(cov["excluded"], 5)

    def test_hit_mismatch_esclude_e_conta(self):
        rows = _rows_df(_admitted_row(A_market="1", A_hit=0, fthg=2, ftag=1))
        attached, cov = Q.attach_real_odds(rows, self.CSV_IDX, self.BTTS_IDX)
        self.assertEqual(len(attached), 0)
        self.assertEqual(cov["hit_mismatch"], 1)

    def test_soglia_150_bordo_nel_gruppo_giusto(self):
        rows = _rows_df(
            _admitted_row(A_market="1", A_hit=1, fthg=2, ftag=1),   # 1.80 >= 1.50
        )
        attached, _ = Q.attach_real_odds(rows, self.CSV_IDX, self.BTTS_IDX)
        attached["odds"] = [1.50]                    # bordo esatto
        an = Q.bootstrap_analysis(attached, n_boot=50)
        self.assertEqual(an["point"]["sub"]["n"], 1)
        self.assertEqual(an["point"]["comp"]["n"], 0)
        # e 1.49 va nell'altro gruppo
        attached["odds"] = [1.49]
        an = Q.bootstrap_analysis(attached, n_boot=50)
        self.assertEqual(an["point"]["sub"]["n"], 0)
        self.assertEqual(an["point"]["comp"]["n"], 1)

    def test_data_incompatibile_esclusa(self):
        csv_lontano = {("SerieA", "2024/25", "Alpha", "Beta"):
                       {"date": pd.Timestamp("2024-08-30"),
                        "odds": {"B365H": 1.80}}}
        rows = _rows_df(_admitted_row(A_market="1", A_hit=1, fthg=2, ftag=1))
        attached, cov = Q.attach_real_odds(rows, csv_lontano, self.BTTS_IDX)
        self.assertEqual(len(attached), 0)
        self.assertEqual(cov["data_mismatch_csv"], 1)


class TestMetricheEBootstrap(unittest.TestCase):
    def _attached(self, n=120, seed=11):
        rng = np.random.default_rng(seed)
        odds = rng.uniform(1.30, 2.60, size=n)
        conf = rng.uniform(0.55, 0.85, size=n)
        hit = (rng.uniform(0, 1, size=n) < conf).astype(int)
        market = rng.choice(["1", "2", "GG", "U2.5"], size=n)
        return pd.DataFrame({"league": "Serie A", "season": "2024/25",
                             "home": "A", "away": "B", "market": market,
                             "conf": conf, "hit": hit, "odds": odds,
                             "fthg": 1, "ftag": 0, "kickoff": "x"})

    def test_brier_identico_a_quality(self):
        d = self._attached()
        m = Q.cell_metrics(d["hit"].to_numpy(float), d["conf"].to_numpy(float),
                           d["odds"].to_numpy(float))
        q = quality(list(zip(d["conf"].tolist(), d["hit"].tolist())))
        self.assertAlmostEqual(m["brier"], q["brier"], places=12)
        self.assertAlmostEqual(m["hit_rate"], q["hit_rate"], places=12)

    def test_bootstrap_deterministico_punto_in_ci_delta(self):
        d = self._attached()
        a1 = Q.bootstrap_analysis(d, n_boot=200)
        a2 = Q.bootstrap_analysis(d, n_boot=200)
        self.assertEqual(a1, a2)   # stesso seed -> identico
        for cell in ("full", "sub", "comp"):
            for k in ("hit_rate", "brier", "roi_pct"):
                lo, hi = a1["ci"][cell][k]
                self.assertLessEqual(lo - 1e-9, a1["point"][cell][k])
                self.assertLessEqual(a1["point"][cell][k] - 1e-9, hi)
        # delta appaiato = differenza dei punti (identita' al variare del campione)
        dk = a1["delta"]["sub-full"]["roi_pct"]
        self.assertAlmostEqual(dk["delta"],
                               a1["point"]["sub"]["roi_pct"] - a1["point"]["full"]["roi_pct"],
                               places=12)

    def test_cella_vuota_senza_ci_inventata(self):
        d = self._attached(n=40)
        d.loc[d.index, "market"] = "GG"
        d.loc[d.index, "odds"] = 1.35          # tutti sotto soglia: sub vuota
        an = Q.bootstrap_analysis(d, n_boot=50)
        self.assertEqual(an["point"]["sub"]["n"], 0)
        self.assertIsNone(an["point"]["sub"]["brier"])
        self.assertIsNone(an["ci"]["sub"]["brier"])       # niente CI inventata
        self.assertFalse(an["ci"]["sub"]["ci_stable"])
        self.assertGreater(an["point"]["comp"]["n"], 0)


class TestSelettorePuroImport(unittest.TestCase):
    def test_seleziona_riga_top_mix_importata_da_app(self):
        m = {"1": 0.62, "X": 0.22, "2": 0.16, "u25": 0.58, "gg": 0.50}
        riga = Q.seleziona_riga_top_mix(m, elo_probs=None,
                                                 elo_disponibile=True,
                                                 home="Alpha", away="Beta")
        self.assertIsNotNone(riga)
        self.assertIn(riga["market"], ("Vittoria Alpha", "Pareggio", "Vittoria Beta",
                                       "Over 2.5", "Under 2.5", "GG", "NG"))
        # nessuna side-effect sul dict di input (pura)
        self.assertEqual(m, {"1": 0.62, "X": 0.22, "2": 0.16, "u25": 0.58, "gg": 0.50})


@unittest.skipUnless(os.path.exists(Q.DEFAULT_ROWS),
                     "replay CSV non presente")
class TestIntegrazioneReplay(unittest.TestCase):
    """Test d'integrazione sugli artefatti reali committati (lettura)."""

    @classmethod
    def setUpClass(cls):
        cls.payload, cls.md = Q.run()

    def test_perimetro_identico_al_replay(self):
        self.assertEqual(self.payload["n_candidate"], 3422)
        self.assertEqual(self.payload["n_admitted"], 1865)
        self.assertEqual(self.payload["coverage"].get("hit_mismatch", 0), 0)

    def test_tutte_le_quote_usabili_positive(self):
        rows = pd.read_csv(Q.DEFAULT_ROWS)
        admitted = rows[rows["A_admitted"] == True]  # noqa: E712
        csv_idx, dup_csv = Q.build_csv_odds_index(Q.league_prefix_map().values())
        btts_idx, dup_btts, _ = Q.build_btts_odds_index(Q.load_btts_dataset(),
                                                        Q.league_prefix_map().values())
        self.assertEqual(dup_csv, [])
        self.assertEqual(dup_btts, [])
        attached, cov = Q.attach_real_odds(rows, csv_idx, btts_idx)
        self.assertTrue((attached["odds"] > 1.0).all())
        self.assertTrue(np.isfinite(attached["odds"].to_numpy(float)).all())
        # ammesse = con quota + escluse, nessuna doppia
        self.assertEqual(len(attached) + cov.get("excluded", 0), len(admitted))
        # ogni mercato dell'attached e' un mercato noto del mapping
        self.assertTrue(set(attached["market"]) <= set(Q.MARKET_ODDS_COL) | {"GG", "NG"})

    def test_gg_ng_da_btts_1x2_da_csv(self):
        csv_idx, _ = Q.build_csv_odds_index(Q.league_prefix_map().values())
        btts_idx, _, _ = Q.build_btts_odds_index(Q.load_btts_dataset(),
                                                 Q.league_prefix_map().values())
        # le chiavi BTTS coprono le partite del campionato (380 x stagione per lega)
        serie_btts = sum(1 for k in btts_idx if k[0] == "SerieA")
        self.assertGreaterEqual(serie_btts, 700)   # 2 stagioni, piu' coppie
        # il CSV index ha le colonne 1X2 per le stesse coppie
        key0 = next(iter(csv_idx))
        self.assertIn("B365H", csv_idx[key0]["odds"])

    def test_bootstrap_punto_in_ci_report_contenuto(self):
        an = self.payload["analysis"]
        self.assertEqual(an["n_boot"], 2000)
        self.assertEqual(an["seed"], 20260905)
        for cell in ("full", "sub", "comp"):
            for k in ("hit_rate", "brier", "roi_pct"):
                if an["ci"][cell][k] is not None:
                    lo, hi = an["ci"][cell][k]
                    self.assertLessEqual(lo - 1e-9, an["point"][cell][k])
                    self.assertLessEqual(an["point"][cell][k] - 1e-9, hi)
        self.assertIn("# Fascia di quota reale del Top Mix", self.md)
        self.assertIn("## 4. Confronto esplicito", self.md)
        self.assertIn("validation storica gia' esaminata", self.md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
