"""Test di ``audit/diagnose_clv_pinnacle.py``.

Deterministici e offline. Coprono il punto 6 del protocollo:
  * de-vig corretto (proporzionale, rifiuta quote non valide);
  * join walk-forward senza leakage (mutare il futuro non cambia le predizioni,
    mutare il passato si');
  * esclusione corretta delle righe senza quota Pinnacle (nessuna stima);
  * join quote 1:1 sul df di load_league (dati reali, sola lettura);
  * equivalenza bit-faithful del ramo NORM-SUM con
    diagnose_production_baseline.run_models;
  * blend costante con app.ELO_ENSEMBLE_W (produzione);
  * CLV e bootstrap deterministici.

Eseguibili con pytest o direttamente:
    python -m pytest audit/test_diagnose_clv_pinnacle.py -q
    python audit/test_diagnose_clv_pinnacle.py
"""
from __future__ import annotations

import json
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

import diagnose_clv_pinnacle as M  # noqa: E402


def _league_df(n_rounds=3, teams=("Alpha", "Beta", "Gamma", "Delta")):
    """Mini df con lo schema di load_league: girone all'italiana sintetico."""
    dates = pd.date_range("2022-08-20", periods=len(teams) * 2 * n_rounds, freq="3D")
    rows = []
    t = list(teams)
    for r in range(n_rounds):
        for h, a in [(t[0], t[1]), (t[2], t[3]), (t[1], t[2]), (t[3], t[0]),
                     (t[0], t[2]), (t[1], t[3]), (t[2], t[0]), (t[3], t[1])]:
            rows.append((dates[len(rows) % len(dates)],))
    # costruzione semplice e deterministica: coppie cicliche
    pairs = []
    for i in range(len(dates)):
        h = teams[i % 4]
        a = teams[(i + 1) % 4] if (i // 4) % 2 == 0 else teams[(i + 2) % 4]
        pairs.append((h, a))
    return pd.DataFrame([{
        "Date": d, "season": "2024/25", "HomeClean": h, "AwayClean": a,
        "FTHG": (i * 7) % 4, "FTAG": (i * 3) % 3,
        "FTR": "H" if (i * 7) % 4 > (i * 3) % 3 else ("A" if (i * 7) % 4 < (i * 3) % 3 else "D"),
    } for i, (d, (h, a)) in enumerate(zip(dates, pairs))])


def _pin_table(df, pre=(2.1, 3.4, 3.2), close=(2.0, 3.5, 3.1), drop_pre=(),
               drop_close=()):
    """Tabella Pinnacle allineata al df (con buchi dove richiesto)."""
    rows = []
    for i, (_, r) in enumerate(df.iterrows()):
        row = {"Date": r["Date"], "HomeClean": r["HomeClean"], "AwayClean": r["AwayClean"],
               "PSH": pre[0], "PSD": pre[1], "PSA": pre[2],
               "PSCH": close[0], "PSCD": close[1], "PSCA": close[2]}
        if i in drop_pre:
            row["PSH"] = np.nan
        if i in drop_close:
            row["PSCH"] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)


# =====================================================================
# 1. De-vig
# =====================================================================
class TestDevig(unittest.TestCase):

    def test_proporzionale_1x2(self):
        oh, od, oa = 2.5, 3.4, 2.9
        got = M.devig_1x2(oh, od, oa)
        inv = [1 / oh, 1 / od, 1 / oa]
        tot = sum(inv)
        for g, e in zip(got, inv):
            self.assertAlmostEqual(g, e / tot, places=12)
        self.assertAlmostEqual(sum(got), 1.0, places=12)

    def test_rifiuta_quote_non_valide(self):
        # nota: devig_1x2 e' la funzione del repo (non modificata): rifiuta
        # quote assenti o <= 1.0; inf passerebbe (1/inf = 0) ma il loader
        # Pinnacle la esclude prima (test_validita_quota_nel_loader).
        for o in [(1.0, 3.0, 3.0), (2.0, 0.5, 3.0), (None, 3.0, 3.0),
                  (float("nan"), 3.0, 3.0)]:
            x = M.devig_1x2(*o)
            ok = x is None or all(v is None for v in x)
            self.assertTrue(ok, msg=f"{o} -> {x}")

    def test_validita_quota_nel_loader(self):
        """Il loader mette NaN su quote <= 1 o non numeriche: mai stimate."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "Test_2024.csv")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("Date,HomeTeam,AwayTeam,PSH,PSD,PSA,PSCH,PSCD,PSCA\n")
                fh.write("17/08/2024,Alpha,Beta,2.10,3.40,4.35,2.00,3.45,4.76\n")
                fh.write("18/08/2024,Gamma,Delta,1.00,3.40,4.35,2.00,3.45,4.76\n")
                fh.write("19/08/2024,Alpha,Gamma,2.10,n/d,4.35,2.00,-2.5,4.76\n")
            fmap = {"2024/25": path}
            pin = M.load_pinnacle_odds("Test", season_files_map=fmap)
            self.assertEqual(len(pin), 3)
            self.assertTrue(np.isnan(pin.loc[1, "PSH"]))       # <= 1 (riga 18/08)
            self.assertTrue(np.isnan(pin.loc[2, "PSD"]))       # illeggibile (19/08)
            self.assertTrue(np.isnan(pin.loc[2, "PSCD"]))      # negativa (19/08)
            self.assertAlmostEqual(pin.loc[0, "PSA"], 4.35)
            self.assertAlmostEqual(pin.loc[0, "PSCA"], 4.76)
            self.assertTrue((pin[["PSH", "PSD", "PSA"]].dropna() > 1.0).all().all())


# =====================================================================
# 2. Esclusione righe senza quota Pinnacle
# =====================================================================
class TestEsclusione(unittest.TestCase):

    def test_usable_mask(self):
        df = _league_df(n_rounds=1)
        pin = _pin_table(df, drop_pre={1}, drop_close={2})
        merged, stats = M.attach_pinnacle(df, pin)
        self.assertEqual(len(merged), len(df))
        self.assertEqual(stats["rows_df"], len(df))
        usable = M.usable_mask(merged)
        self.assertTrue(bool(usable.iloc[0]))    # completa
        self.assertFalse(bool(usable.iloc[1]))   # PSH mancante -> esclusa
        self.assertFalse(bool(usable.iloc[2]))   # PSCH mancante -> esclusa
        # le escluse restano NaN: nessuna stima
        self.assertTrue(np.isnan(merged.loc[1, "PSH"]))
        self.assertTrue(np.isnan(merged.loc[2, "PSCH"]))

    def test_attach_join_1a1_e_deterministico(self):
        df = _league_df(n_rounds=2)
        pin = _pin_table(df)
        m1, s1 = M.attach_pinnacle(df, pin)
        m2, s2 = M.attach_pinnacle(df, pin)
        self.assertEqual(json.dumps(s1, sort_keys=True), json.dumps(s2, sort_keys=True))
        pd.testing.assert_frame_equal(m1, m2)
        # chiave duplicata -> assertion, mai risolta in silenzio
        dup = pd.concat([pin, pin.iloc[[0]]], ignore_index=True)
        with self.assertRaises(AssertionError):
            M.attach_pinnacle(df, dup)


# =====================================================================
# 3. Walk-forward senza leakage + blend
# =====================================================================
class TestWalkForward(unittest.TestCase):

    def _run(self, df):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return M.run_model_with_elo(df, "Serie A", {})

    def test_emesse_solo_eval(self):
        df = _league_df(n_rounds=2)
        out = self._run(df)
        self.assertEqual(len(out), len(df))
        self.assertTrue((out["season"] == "2024/25").all())

    def test_no_leakage_avanti(self):
        df = _league_df(n_rounds=2)
        df2 = df.copy()
        df2.loc[df2.index[-1], "FTHG"] = 4   # ultima partita cambiata
        df2.loc[df2.index[-1], "FTAG"] = 4
        o1, o2 = self._run(df), self._run(df2)
        # le predizioni sulle partite precedenti sono identiche
        head = o1.index[o1.index < len(o1) - 1]
        pd.testing.assert_frame_equal(o1.loc[head, ["model_1", "model_X", "model_2"]],
                                      o2.loc[head, ["model_1", "model_X", "model_2"]])
        # lo stato aggiunto dall'ultima partita non puo' retro-agire: l'ultima
        # predizione (calcolata PRIMA dell'aggiornamento) usa i dati precedenti
        # ed e' identica per costruzione anche se la partita e' se stessa cambiata?
        # No: l'ultima predizione NON dipende dal proprio risultato -> identica.
        self.assertAlmostEqual(o1["model_1"].iloc[-1], o2["model_1"].iloc[-1])

    def test_lo_stato_usa_il_passato(self):
        df = _league_df(n_rounds=2)
        df2 = df.copy()
        df2.loc[df2.index[0], "FTHG"] += 3   # prima partita cambiata
        o1, o2 = self._run(df), self._run(df2)
        diffs = (o1["model_1"] - o2["model_1"]).abs()
        self.assertGreater(float(diffs.iloc[1:].max()), 1e-9)

    def test_blend_produzione(self):
        df = _league_df(n_rounds=2)
        out = self._run(df)
        w = M.ELO_ENSEMBLE_W
        rebuilt = w * out["prodn_1"] + (1 - w) * out["elo_1"]
        self.assertTrue(np.allclose(rebuilt, out["model_1"], atol=1e-12))

    def test_probs_in_range(self):
        df = _league_df(n_rounds=2)
        out = self._run(df)
        for c in ("prodn_1", "prodn_X", "prodn_2", "elo_1", "elo_X", "elo_2",
                  "model_1", "model_X", "model_2"):
            self.assertTrue(((out[c] >= 0) & (out[c] <= 1)).all(), msg=c)
        s = out[["model_1", "model_X", "model_2"]].sum(axis=1)
        self.assertTrue(np.allclose(s, 1.0, atol=1e-9))   # blend convesso di distribuzioni

    def test_elo_senso_delle_correnti(self):
        """Elo con rating favorevole in casa deve dare P(1) > P(2)."""
        e = M.elo_probs(1600.0, 1400.0, 65.0)
        self.assertGreater(e[0], e[2])
        e_sym = M.elo_probs(1500.0, 1500.0, 65.0)
        self.assertGreater(e_sym[0], e_sym[2])    # home advantage
        self.assertAlmostEqual(sum(e_sym), 1.0, places=12)


# =====================================================================
# 4. Equivalenza con la pipeline di riferimento (run_models)
# =====================================================================
class TestEquivalenzaRunModels(unittest.TestCase):

    def test_norm_sum_bit_faithful(self):
        from diagnose_production_baseline import run_models
        prefix, camp = "SerieA", "Serie A"
        df = M.load_league(prefix)
        df = df.iloc[:820]          # 2 stagioni di train + primi eval
        xg = M.load_xg(camp)
        mine = M.run_model_with_elo(df, camp, xg)
        ref = run_models(df, camp, xg)
        self.assertEqual(len(mine), len(ref))
        for c in ("prodn_1", "prodn_X", "prodn_2"):
            diff = float(np.abs(mine[c].to_numpy(dtype=float)
                                - ref[c].to_numpy(dtype=float)).max())
            self.assertLess(diff, 1e-12, msg=c)


# =====================================================================
# 5. Blend costante = produzione (app.ELO_ENSEMBLE_W)
# =====================================================================
class TestBlendProduzione(unittest.TestCase):

    def test_w_uguale_a_app(self):
        import app as prod_app   # import pesante (bare mode): solo qui
        self.assertEqual(M.ELO_ENSEMBLE_W, prod_app.ELO_ENSEMBLE_W)


# =====================================================================
# 6. CLV e bootstrap
# =====================================================================
class TestClvBootstrap(unittest.TestCase):

    def _d(self):
        return pd.DataFrame([
            # edge GG... qui 1X2: edge lato 1 = 0.60 - 0.4762 = +0.1238 -> bet 1
            {"model_1": 0.60, "model_X": 0.25, "model_2": 0.15,
             "pinpre_1": 0.4762, "pinpre_X": 0.2941, "pinpre_2": 0.2297,
             "pinclose_1": 0.50, "pinclose_X": 0.29, "pinclose_2": 0.21,
             "PSH": 2.10, "PSD": 3.40, "PSA": 4.35,
             "PSCH": 2.00, "PSCD": 3.45, "PSCA": 4.76, "real_1x2": "1"},
            # edge lato 2 = 0.40 - 0.24 = +0.16 -> bet 2
            {"model_1": 0.30, "model_X": 0.30, "model_2": 0.40,
             "pinpre_1": 0.45, "pinpre_X": 0.31, "pinpre_2": 0.24,
             "pinclose_1": 0.48, "pinclose_X": 0.30, "pinclose_2": 0.22,
             "PSH": 2.20, "PSD": 3.20, "PSA": 4.15,
             "PSCH": 2.05, "PSCD": 3.30, "PSCA": 4.55, "real_1x2": "2"},
            # nessun edge: fair pre == prob modello (nessun lato con edge > 0)
            {"model_1": 0.40, "model_X": 0.30, "model_2": 0.30,
             "pinpre_1": 0.40, "pinpre_X": 0.30, "pinpre_2": 0.30,
             "pinclose_1": 0.40, "pinclose_X": 0.30, "pinclose_2": 0.30,
             "PSH": 2.20, "PSD": 3.20, "PSA": 4.15,
             "PSCH": 2.20, "PSCD": 3.20, "PSA": 4.15, "real_1x2": "X"},
        ])

    def _d_big(self, n=60):
        """Campione sintetico ampio (serve al bootstrap: con n piccolo la
        distribuzione e' degenere)."""
        rng = np.random.default_rng(3)
        rows = []
        for _ in range(n):
            p = rng.dirichlet([2.0, 2.0, 2.0])
            pre_q = rng.dirichlet([3.0, 3.0, 3.0])
            close_q = rng.dirichlet([3.0, 3.0, 3.0])
            pre_o = 1.0 / (pre_q * 1.07)
            close_o = 1.0 / (close_q * 1.07)
            rows.append({
                "model_1": p[0], "model_X": p[1], "model_2": p[2],
                "pinpre_1": pre_q[0], "pinpre_X": pre_q[1], "pinpre_2": pre_q[2],
                "pinclose_1": close_q[0], "pinclose_X": close_q[1], "pinclose_2": close_q[2],
                "PSH": pre_o[0], "PSD": pre_o[1], "PSA": pre_o[2],
                "PSCH": close_o[0], "PSCD": close_o[1], "PSCA": close_o[2],
                "real_1x2": str(rng.choice(["1", "X", "2"], p=p)),
            })
        return pd.DataFrame(rows)

    def test_clv_notevole(self):
        d = self._d()
        c = M.clv_block(d, n_boot=200, seed=1)
        self.assertEqual(c["n_bet"], 2)                 # la terza non e' scommessa
        # scommessa 1: P_model 0.60 - close 0.50 = +0.10; classic: 0.4762 - 0.50 = -0.0238
        self.assertAlmostEqual(c["clv_model_mean"], (0.10 + (0.40 - 0.22)) / 2, places=9)
        self.assertAlmostEqual(c["clv_classic_mean"], ((0.4762 - 0.50) + (0.24 - 0.22)) / 2,
                               places=9)
        # lato 1 vince a 2.00 chiuse: +10; lato 2 vince a 4.55 chiuse: +35.5
        # ROI chiusura = (10 + 35.5) / 20 = 227.5%
        self.assertAlmostEqual(c["roi_close_pct"], (10 + 35.5) / 20 * 100, places=6)
        self.assertAlmostEqual(c["win_rate_pct"], 100.0, places=6)
        self.assertEqual(c["side_counts"], {"1": 1, "X": 0, "2": 1})

    def test_bootstrap_deterministico(self):
        d = self._d_big()
        c1 = M.clv_block(d, n_boot=300, seed=7)
        c2 = M.clv_block(d, n_boot=300, seed=7)
        self.assertEqual(c1["clv_model_ci"], c2["clv_model_ci"])
        self.assertEqual(c1["roi_close_ci"], c2["roi_close_ci"])
        c3 = M.clv_block(d, n_boot=300, seed=8)
        self.assertNotEqual(c1["clv_model_ci"], c3["clv_model_ci"])  # seed conta
        # il punto stimato sta dentro la propria CI (sanita' del resampling)
        for point, ci in ((c1["clv_model_mean"], c1["clv_model_ci"]),
                          (c1["roi_close_pct"] / 100.0, [x / 100.0 for x in c1["roi_close_ci"]])):
            self.assertLessEqual(ci[0], point + 1e-9)
            self.assertGreaterEqual(ci[1], point - 1e-9)

    def test_clv_nessuna_scommessa(self):
        d = self._d()
        d.loc[:, "model_1"] = 0.1
        d.loc[:, "model_X"] = 0.1
        d.loc[:, "model_2"] = 0.1
        c = M.clv_block(d)
        self.assertEqual(c, {"n_bet": 0})

    def test_bootstrap_dbrier(self):
        d = self._d_big()
        out = M.bootstrap_dbrier(d, ("pinpre_1", "pinpre_X", "pinpre_2"),
                                 ("pinclose_1", "pinclose_X", "pinclose_2"), n_boot=200)
        self.assertEqual(out["n"], 60)
        self.assertIsInstance(out["delta"], float)
        lo, hi = out["ci"]
        self.assertLessEqual(lo, hi)
        # deterministico
        out2 = M.bootstrap_dbrier(d, ("pinpre_1", "pinpre_X", "pinpre_2"),
                                  ("pinclose_1", "pinclose_X", "pinclose_2"), n_boot=200)
        self.assertEqual(out["ci"], out2["ci"])


# =====================================================================
# 7. Join quote su dati reali (sola lettura)
# =====================================================================
class TestJoinDatiReali(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(os.path.join(_REPO_ROOT, "SoccerMath", "database")):
            raise unittest.SkipTest("database non presente")
        cls.cases = [("SerieA", "Serie A"), ("Premier", "Premier League")]

    def test_join_1a1_e_copertura(self):
        for prefix, camp in self.cases:
            df = M.load_league(prefix)
            pin = M.load_pinnacle_odds(prefix)
            merged, stats = M.attach_pinnacle(df, pin)
            self.assertEqual(len(merged), len(df), msg=prefix)
            self.assertEqual(stats["rows_df"], len(df), msg=prefix)
            # conteggio indipendente: righe con PSH valido nel CSV grezzo della
            # stagione 2024/25 == righe merged con PSH valido per quella stagione
            raw = pd.read_csv(M.season_files(prefix)["2024/25"],
                              on_bad_lines="warn", low_memory=False)
            raw_psh_ok = int((pd.to_numeric(raw["PSH"], errors="coerce") > 1.0).sum())
            got = int(((merged["season"] == "2024/25") & (merged["PSH"] > 1.0)).sum())
            self.assertEqual(got, raw_psh_ok,
                             msg=f"{prefix}: merged {got} != raw {raw_psh_ok}")

    def test_coverage_report_rows(self):
        for prefix, camp in self.cases:
            df = M.load_league(prefix)
            pin = M.load_pinnacle_odds(prefix)
            merged, _ = M.attach_pinnacle(df, pin)
            cov = M.coverage_rows(merged)
            tot_usable = sum(c["usable"] for c in cov if c["in_eval"])
            self.assertGreater(tot_usable, 0, msg=prefix)
            for c in cov:
                self.assertLessEqual(c["usable"], c["rows"], msg=prefix)
                self.assertEqual(c["pre_ok"] + c["pre_missing"], c["rows"], msg=prefix)


if __name__ == "__main__":
    unittest.main(verbosity=2)
