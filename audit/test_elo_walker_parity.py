"""
test_elo_walker_parity.py — Punto A.3: parita' BIT-EXACT fra il walker Elo
fedele (audit/elo_walker_core.py) e il codice di produzione, su fixture
congelata.

Fixture: audit/fixtures/elo_walker_parity.json
Generata da: audit/make_elo_parity_fixture.py (solo codice di produzione)
Il commit di generazione e' dentro la fixture (campo repo_head_commit) e viene
ri-asserito qui contro il merge-base di main.

Tre controlli:
  P1  stato finale: il rating ``elo_after`` dell'ultima partita di ogni
      squadra nel walker == ``EloEngine.ratings`` di produzione (repr esatto).
  P2  conversione: le probabilita' del walker, calcolate sullo stato finale,
      == ``predict_elo_probs`` di produzione sulle stesse coppie (bit-exact).
  P3  walk-forward: per ogni cutoff della fixture, le probabilita' del walker
      per la PRIMA partita della data di cutoff == quelle di un motore di
      PRODUZIONE costruito su CSV troncati a ``Date < cutoff`` (bit-exact),
      inclusi i rating pre-partita.

Esecuzione:
    python audit/test_elo_walker_parity.py
    python -m pytest audit/test_elo_walker_parity.py -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest

import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

import models.elo_engine as PROD_ELO                       # noqa: E402
from models.elo_engine import EloEngine, predict_elo_probs  # noqa: E402
import elo_walker_core as W                                 # noqa: E402

FIXTURE_PATH = os.path.join(_AUDIT_DIR, "fixtures", "elo_walker_parity.json")
MAIN_MERGE_BASE = "3f9f04278096aba2bc96fc5335a45ccd0d219094"

with open(FIXTURE_PATH, encoding="utf-8") as _f:
    FIX = json.load(_f)


class TestProvenienzaFixture(unittest.TestCase):
    def test_fixture_generata_da_produzione_di_main(self):
        self.assertEqual(FIX["main_merge_base_commit"], MAIN_MERGE_BASE)
        diff = subprocess.check_output(
            ["git", "diff", "--stat", MAIN_MERGE_BASE, "--", "SoccerMath/"],
            cwd=_REPO_ROOT).decode().strip()
        self.assertEqual(diff, "", "la produzione e' stata modificata: "
                                   "la fixture non e' piu' quella di main")


class TestParitaWalker(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.engines = {}
        cls.tables = {}
        for lg in W.LEAGUES:
            PROD_ELO._ELO_ENGINES_CACHE.pop(lg, None)
            PROD_ELO._ELO_ENGINES_STAMP.pop(lg, None)
            e = EloEngine(lg)
            e.compute_ratings()
            cls.engines[lg] = e
            cls.tables[lg] = W.build_walker_table(lg, engine=e)

    # ---- P1 -------------------------------------------------------------
    def test_p1_stato_finale_identico(self):
        for lg in W.LEAGUES:
            eng = self.engines[lg]
            atteso = FIX["leagues"][lg]["final_ratings"]
            ottenuto = {t: repr(float(r)) for t, r in eng.ratings.items()}
            self.assertEqual(ottenuto, atteso, f"{lg}: rating finali != fixture")
            # il walker ricostruisce lo stesso stato finale dagli elo_after
            d = self.tables[lg]
            last = {}
            for _, r in d.iterrows():
                last[r["home"]] = r["elo_home_pre"]
                last[r["away"]] = r["elo_away_pre"]
            # elo_after dell'ultima partita per squadra, ripreso da history
            post = {}
            for team, hist in eng.history.items():
                if hist:
                    post[team] = repr(float(hist[-1]["elo_after"]))
            self.assertEqual(post, atteso, f"{lg}: elo_after finali != fixture")

    # ---- P2 -------------------------------------------------------------
    def test_p2_conversione_identica(self):
        for lg in W.LEAGUES:
            eng = self.engines[lg]
            PROD_ELO._ELO_ENGINES_CACHE[lg] = eng
            PROD_ELO._ELO_ENGINES_STAMP[lg] = time.monotonic()
            for case in FIX["leagues"][lg]["now_fixtures"]:
                got = predict_elo_probs(case["home_raw"], case["away_raw"], lg)
                for k, v in case["probs"].items():
                    self.assertEqual(repr(got[k]), repr(v),
                                     f"{lg} {case['home_raw']}-{case['away_raw']} chiave {k}")
            PROD_ELO._ELO_ENGINES_CACHE.pop(lg, None)
            PROD_ELO._ELO_ENGINES_STAMP.pop(lg, None)

    # ---- P3 -------------------------------------------------------------
    def test_p3_walk_forward_vs_produzione_troncata(self):
        diffs = []
        for lg in W.LEAGUES:
            d = self.tables[lg]
            for case in FIX["leagues"][lg]["cutoff_cases"]:
                pos = case["prod_pos_nel_db_completo"]
                row = d.iloc[pos]
                self.assertEqual(row["home"], case["home"])
                self.assertEqual(row["away"], case["away"])
                self.assertEqual(str(pd.Timestamp(row["date"]).date()), case["cutoff"])
                att = case["probs"]
                for col, key in (("elo_1", "1"), ("elo_X", "X"), ("elo_2", "2"),
                                 ("d", "elo_diff"), ("e_H", "expected_score_home")):
                    if repr(float(row[col])) != repr(float(att[key])):
                        diffs.append((lg, case["cutoff"], col,
                                      float(row[col]), float(att[key])))
                for team, rr in case["ratings_troncati"].items():
                    col = "elo_home_pre" if team == case["home"] else "elo_away_pre"
                    if repr(float(row[col])) != rr:
                        diffs.append((lg, case["cutoff"], col,
                                      float(row[col]), float(rr)))
        if diffs:
            msg = "\n".join(f"  {a} cutoff={b} {c}: walker={e!r} produzione={f!r} "
                            f"delta={e - f:+.10g}" for a, b, c, e, f in diffs)
            self.fail(f"P3 NON OK, {len(diffs)} differenze:\n{msg}")


class TestNoLeakage(unittest.TestCase):
    """P4: test di causalita'. Si altera il RISULTATO di una partita nei CSV
    (copia temporanea del DB, originale intatto) e si verifica che le
    probabilita' Elo del walker PER QUELLA partita non cambino di un bit,
    mentre quelle delle partite successive delle stesse squadre cambino.
    Se il walker guardasse il risultato della partita che prevede, la prima
    verifica fallirebbe."""

    LEAGUE = "Premier League"

    def test_p4_alterare_il_risultato_non_cambia_la_previsione(self):
        import shutil
        import tempfile
        import config as PROD_CONFIG
        from make_elo_parity_fixture import _RepointDB

        base = W.build_walker_table(self.LEAGUE)
        target = 1000                       # riga di prova, in mezzo alla serie
        row = base.iloc[target]

        tmp = tempfile.mkdtemp(prefix="elo_leak_db_")
        try:
            src = str(PROD_CONFIG.DATABASE_DIR)
            for f in os.listdir(src):
                shutil.copy(os.path.join(src, f), os.path.join(tmp, f))
            # inverte il risultato della partita bersaglio in tutti i CSV
            cambiate = 0
            for f in os.listdir(tmp):
                if not f.endswith(".csv"):
                    continue
                p = os.path.join(tmp, f)
                df = pd.read_csv(p, on_bad_lines="warn", low_memory=False)
                if not {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"}.issubset(df.columns):
                    continue
                dt = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
                m = ((dt == pd.Timestamp(row["date"]))
                     & (df["HomeTeam"] == row["home_raw"])
                     & (df["AwayTeam"] == row["away_raw"]))
                if m.any():
                    df.loc[m, "FTHG"] = 9
                    df.loc[m, "FTAG"] = 0
                    df.loc[m, "FTR"] = "H"
                    df.to_csv(p, index=False)
                    cambiate += int(m.sum())
            self.assertGreater(cambiate, 0, "partita bersaglio non trovata nei CSV")

            with _RepointDB(tmp):
                PROD_ELO._ELO_ENGINES_CACHE.pop(self.LEAGUE, None)
                alt = W.build_walker_table(self.LEAGUE)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            PROD_ELO._ELO_ENGINES_CACHE.pop(self.LEAGUE, None)

        self.assertEqual(len(alt), len(base))
        for col in ("elo_1", "elo_X", "elo_2", "elo_home_pre", "elo_away_pre"):
            self.assertEqual(repr(float(alt.iloc[target][col])),
                             repr(float(base.iloc[target][col])),
                             f"LEAKAGE: {col} della partita bersaglio e' cambiato")
        # le righe precedenti sono identiche
        pre_eq = (alt.iloc[:target][["elo_1", "elo_X", "elo_2"]].to_numpy()
                  == base.iloc[:target][["elo_1", "elo_X", "elo_2"]].to_numpy()).all()
        self.assertTrue(pre_eq, "il passato e' cambiato: ordinamento non deterministico")
        # almeno una riga successiva deve essere cambiata (l'update ha effetto)
        post_diff = (alt.iloc[target + 1:][["elo_1", "elo_X", "elo_2"]].to_numpy()
                     != base.iloc[target + 1:][["elo_1", "elo_X", "elo_2"]].to_numpy()).any()
        self.assertTrue(post_diff, "l'aggiornamento non ha avuto alcun effetto a valle")
        n_post = int((alt.iloc[target + 1:][["elo_1", "elo_X", "elo_2"]].to_numpy()
                      != base.iloc[target + 1:][["elo_1", "elo_X", "elo_2"]].to_numpy())
                     .any(axis=1).sum())
        print(f"\n  P4: righe successive modificate = {n_post} / {len(base) - target - 1}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
