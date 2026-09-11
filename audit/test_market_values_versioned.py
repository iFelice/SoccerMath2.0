"""Test di ``audit/market_values_versioned.py``.

Deterministici e offline: girano su un CSV sintetico in una tmpdir e su
mini-df allo schema di load_league. Coprono il punto 6 del protocollo:
  * normalizzazione nomi (clean_name + esonimi audit);
  * join corretto per stagione: NESSUNA rilevazione futura o di altra
    stagione viene mai usata (partite di ottobre -> Post-Estivo, di marzo ->
    Post-Invernale, stessa stagione; stagione mancante -> fallback, non
    valore vicino);
  * mkt_factor bit-fedele alla formula di produzione (market_factor di
    diagnose_production_baseline / app.get_league_engine);
  * variante STATIC del walker bit-faithful alla pipeline condivisa;
  * parse del CSV (nomi colonna flessibili, formato euro, righe scartate
    dichiarate, mai indovinate).

Eseguibili con pytest o direttamente:
    python -m pytest audit/test_market_values_versioned.py -q
    python audit/test_market_values_versioned.py
"""
from __future__ import annotations

import logging
import math
import os
import sys
import tempfile
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

import market_values_versioned as M      # noqa: E402
import diagnose_clv_pinnacle as CLV      # noqa: E402
from diagnose_production_baseline import market_factor  # noqa: E402


CSV_MINIMO = """Lega;Stagione;Squadra;Rilevazione;Valore
Serie A;2022/23;Napoli;Post-Estivo;550
Serie A;2022/23;Napoli;Post-Invernale;600
Serie A;2022/23;Milan;Post-Estivo;500
Ligue 1;2022/23;Marsiglia;Post-Estivo;150
Premier League;2022-23;Manchester Utd;Post-Estivo;750
La Liga;2022/23;Barcellona;Post-Estivo;€800m
Bundesliga;2022/23;Bayern Monaco;Post-Estivo;€1.000.000.000
"""


class TestParsing(unittest.TestCase):

    def _tmp_csv(self, text):
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.addCleanup(os.unlink, path)
        return path

    def test_csv_minimo(self):
        lookup, meta = M.parse_market_csv(self._tmp_csv(CSV_MINIMO))
        self.assertEqual(meta["rows"], 7)
        # tutte le 7 righe valide: il parser non indovina squadre, ma qui sono tutte riconoscibili
        self.assertEqual(sum(meta["by_survey"].values()), 7)
        self.assertEqual(len(meta["unmatched"]), 0)
        # lookup per (camp_key, anno, rilevazione, squadra canonica)
        self.assertEqual(lookup[("Serie A", 2022, "Post-Estivo", "Napoli")], 550.0)
        self.assertEqual(lookup[("Serie A", 2022, "Post-Invernale", "Napoli")], 600.0)
        self.assertEqual(lookup[("Serie A", 2022, "Post-Estivo", "Milan")], 500.0)
        # esonimi: Manchester Utd -> Man United
        self.assertEqual(lookup[("Premier League", 2022, "Post-Estivo", "Man United")], 750.0)
        # Barcellona -> Barcelona
        self.assertEqual(lookup[("La Liga", 2022, "Post-Estivo", "Barcelona")], 800.0)
        # euro assoluti con migliaia puntate -> ricondotti a milioni
        self.assertEqual(lookup[("Bundesliga", 2022, "Post-Estivo", "Bayern Monaco")], 1000.0)
        # Ligue 1 riconosciuta dal nome italiano
        self.assertEqual(lookup[("Ligue 1", 2022, "Post-Estivo", "Marseille")], 150.0)

    def test_colonne_flessibili(self):
        alt = "League;Season;Club;Survey;Value\nPremier;2023/24;Arsenal;Post-Estivo;600\n"
        lookup, meta = M.parse_market_csv(self._tmp_csv(alt))
        self.assertEqual(lookup[("Premier League", 2023, "Post-Estivo", "Arsenal")], 600.0)
        self.assertEqual(meta["rows"], 1)

    def test_righe_illeggibili_scartate_dichiarate(self):
        brutto = ("Lega;Stagione;Squadra;Rilevazione;Valore\n"
                  "Serie A;2022/23;Napoli;Post-Estivo;n/d\n"
                  "Serie A;2022/23;Juventus;Mystery;500\n"
                  "Campionato X;2022/23;Roma;Post-Estivo;300\n")
        lookup, meta = M.parse_market_csv(self._tmp_csv(brutto))
        self.assertNotIn(("Serie A", 2022, "Post-Estivo", "Napoli"), lookup)
        reasons = [u[3] for u in meta["unmatched"]]
        self.assertIn("valore illeggibile", reasons)
        self.assertIn("stagione/rilevazione illeggibile", reasons)
        self.assertIn("lega non riconosciuta", reasons)


class TestVersionedLookup(unittest.TestCase):

    def setUp(self):
        self.lookup, _ = M.parse_market_csv(self._tmp())

    def _tmp(self):
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(CSV_MINIMO)
        self.addCleanup(os.unlink, path)
        return path

    def test_ottobre_usa_post_estivo_stagione(self):
        v, kind = M.versioned_value(self.lookup, "Serie A",
                                    pd.Timestamp("2022-10-16"), "2022/23", "Napoli")
        self.assertEqual((v, kind), (550.0, "Post-Estivo"))

    def test_marzo_usa_post_invernale_stessa_stagione(self):
        v, kind = M.versioned_value(self.lookup, "Serie A",
                                    pd.Timestamp("2023-03-05"), "2022/23", "Napoli")
        self.assertEqual((v, kind), (600.0, "Post-Invernale"))

    def test_soglia_15_febbraio(self):
        v, kind = M.versioned_value(self.lookup, "Serie A",
                                    pd.Timestamp("2023-02-15"), "2022/23", "Napoli")
        self.assertEqual(kind, "Post-Invernale")          # dal 15/2 incluso
        v, kind = M.versioned_value(self.lookup, "Serie A",
                                    pd.Timestamp("2023-02-14"), "2022/23", "Napoli")
        self.assertEqual(kind, "Post-Estivo")

    def test_mai_altre_stagioni(self):
        # una partita 2023/23-24 non vede i valori 2022/23: fallback None
        v, kind = M.versioned_value(self.lookup, "Serie A",
                                    pd.Timestamp("2023-10-20"), "2023/24", "Napoli")
        self.assertIsNone(v)
        # stagione 2021/22 (passata): stessa cosa
        v, _ = M.versioned_value(self.lookup, "Serie A",
                                 pd.Timestamp("2021-10-20"), "2021/22", "Napoli")
        self.assertIsNone(v)
        # squadra senza rilevazione: None, non un vicino
        v, _ = M.versioned_value(self.lookup, "Serie A",
                                 pd.Timestamp("2022-10-20"), "2022/23", "Sassuolo")
        self.assertIsNone(v)

    def test_anno_di_fine_stagione(self):
        # 15/2/2023 e' nel 2023 = anno di FINE di 2022/23
        _, kind = M.versioned_value(self.lookup, "Serie A",
                                    pd.Timestamp("2023-02-15"), "2022/23", "Milan")
        self.assertEqual(kind, "Post-Invernale")


class TestMktFactorBitFedele(unittest.TestCase):

    def test_uguale_a_produzione(self):
        for v in (10, 50, 300, 545, 1200, 1.0, 15.0):
            self.assertEqual(M.market_factor(v), market_factor(v), msg=v)

    def test_clip_formula(self):
        # 10 -> 1+(1-2)/4 = 0.75, clippato a 0.85 DENTRO market_factor (produzione)
        self.assertEqual(market_factor(10), 0.85)
        self.assertEqual(market_factor(10), max(0.85, min(1.25, 1.0 + (math.log10(10) - 2.0) / 4)))
        self.assertEqual(market_factor(20000), 1.25)                 # clip superiore
        self.assertEqual(market_factor(50), 1.0 + (math.log10(50) - 2.0) / 4)


class TestWalkerVariants(unittest.TestCase):

    def _mini_df(self, n=30, season="2024/25"):
        teams = ("Alpha", "Beta", "Gamma", "Delta")
        dates = pd.date_range("2024-08-17", periods=n, freq="3D")
        rows = []
        for i, d in enumerate(dates):
            h = teams[i % 4]
            a = teams[(i + 1) % 4]
            rows.append({"Date": d, "season": season, "HomeClean": h, "AwayClean": a,
                         "FTHG": (i * 7) % 4, "FTAG": (i * 3) % 3,
                         "FTR": "H" if (i * 7) % 4 > (i * 3) % 3 else
                                ("A" if (i * 7) % 4 < (i * 3) % 3 else "D")})
        return pd.DataFrame(rows)

    def test_static_variante_bit_faithful_al_walker_condiviso(self):
        df = self._mini_df()
        lookup, _ = M.parse_market_csv(self._mini_csv())
        mine, usage = M.run_market_variants(df, "Serie A", {}, lookup)
        ref = CLV.run_model_with_elo(df, "Serie A", {})
        self.assertEqual(len(mine), len(ref))
        for c in ("static_1", "static_X", "static_2"):
            np.testing.assert_allclose(mine[c].to_numpy(float),
                                       ref[f"prodn_{c.split('_')[1]}"].to_numpy(float),
                                       atol=1e-12)

    def _mini_csv(self):
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("Lega;Stagione;Squadra;Rilevazione;Valore (mln)\n"
                     "Serie A;2024/25;Alpha;Post-Estivo;400\n"
                     "Serie A;2024/25;Beta;Post-Estivo;100\n"
                     "Serie A;2024/25;Gamma;Post-Estivo;80\n"
                     "Serie A;2024/25;Delta;Post-Estivo;30\n"
                     "Serie A;2024/25;Alpha;Post-Invernale;420\n"
                     "Serie A;2024/25;Beta;Post-Invernale;90\n"
                     "Serie A;2024/25;Gamma;Post-Invernale;85\n"
                     "Serie A;2024/25;Delta;Post-Invernale;25\n")
        self.addCleanup(os.unlink, path)
        return path

    def test_versionato_cambia_le_probabilita_e_usa_point_in_time(self):
        df = self._mini_df()
        lookup, _ = M.parse_market_csv(self._mini_csv())
        mine, usage = M.run_market_variants(df, "Serie A", {}, lookup)
        diff = (mine["ver_1"] - mine["static_1"]).abs().max()
        self.assertGreater(float(diff), 1e-9)     # il versionato NON e' lo statico
        self.assertEqual(usage["fallback_missing"], 0)
        self.assertEqual(usage["Post-Estivo"], 2 * len(mine))
        self.assertEqual(usage["Post-Invernale"], 0)
        # le probabilita' restano distribuzioni
        s = mine[["ver_1", "ver_X", "ver_2"]].sum(axis=1)
        np.testing.assert_allclose(s, 1.0, atol=1e-9)

    def test_fallback_senza_valori(self):
        df = self._mini_df()
        mine, usage = M.run_market_variants(df, "Serie A", {}, {})   # lookup vuoto
        self.assertEqual(usage["fallback_missing"], 2 * len(mine))
        # con fattore 1 la variante versionata coincide con NO_MKT
        np.testing.assert_allclose(mine["ver_1"].to_numpy(float),
                                   mine["none_1"].to_numpy(float), atol=1e-12)

    def _mini_df_teams(self, teams):
        teams_all = teams + ("Gamma", "Delta")
        df = self._mini_df(n=10)
        out = df.copy()
        for i in range(len(out)):
            out.loc[i, "HomeClean"] = teams_all[i % len(teams_all)]
            out.loc[i, "AwayClean"] = teams_all[(i + 1) % len(teams_all)]
        return out

    def test_stesso_fattore_si_cancella_nella_normalizzazione(self):
        """Due squadre con lo STESSO fattore mercato: m/m si cancella in
        NORM-SUM -> static == none (proprieta' matematica del modello)."""
        df = self._mini_df(n=10)   # Alpha/Beta fuori da MARKET_VALUES: fattore(50) uguale
        mine, _ = M.run_market_variants(df, "Serie A", {}, {})
        self.assertTrue(M.market_factor(M.MARKET_VALUES.get("Alpha", 50))
                        == M.market_factor(M.MARKET_VALUES.get("Beta", 50)))
        np.testing.assert_allclose(mine["static_1"].to_numpy(float),
                                   mine["none_1"].to_numpy(float), atol=1e-12)

    def test_fattori_diversi_danno_static_diverso_da_none(self):
        """Squadre reali con valori MARKET_VALUES molto diversi (Inter vs Lecce):
        il fattore NON si cancella e static != none."""
        hi = max(M.MARKET_VALUES, key=lambda k: M.MARKET_VALUES[k])
        lo = min(M.MARKET_VALUES, key=lambda k: M.MARKET_VALUES[k])
        df = self._mini_df_teams((hi, lo))
        mine, _ = M.run_market_variants(df, "Serie A", {}, {})
        self.assertGreater(M.market_factor(M.MARKET_VALUES[hi]),
                           M.market_factor(M.MARKET_VALUES[lo]))
        self.assertGreater(float((mine["static_1"] - mine["none_1"]).abs().max()), 1e-9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
