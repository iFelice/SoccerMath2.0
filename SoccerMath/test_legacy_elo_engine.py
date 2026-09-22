"""Provenienza e isolamento del motore Elo LEGACY (pre-PR#24).

Il Top Mix a due tabelle calcola il modello legacy con
``models/elo_engine_legacy.py``. Quel file deve essere il codice di produzione
di PRIMA del fix, non una ricostruzione: questi test lo dimostrano.

* ``TestProvenienzaVerbatim``: l'hash del blob git del file (ricalcolato in
  Python, senza git) e' ``784cecc9...``, cioe' l'oggetto che ``main`` aveva in
  ``SoccerMath/models/elo_engine.py`` fino ad ``a435436`` (ultimo commit
  prima del fix ``980e048``, merge PR#24 ``626cd0b``). Con un clone completo
  si chiede conferma anche a git.
* ``TestUnicaDifferenza``: il diff fra motore legacy e attuale e' SOLO il
  boost xG retroattivo di ``compute_ratings`` (import di ``get_understat_xg``,
  ``xg_data``, ``xg_adj``, ``xg_elo_boost`` in ``dr``); ``predict_elo_probs``
  e' identica riga per riga.
* ``TestConvivenza``: i due moduli hanno cache separate e danno probabilita'
  diverse sugli stessi dati (se le medie xG ci sono: senza, il boost e' 0 e i
  due motori coincidono per costruzione).
"""
from __future__ import annotations

import ast
import difflib
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from models import legacy_elo as L  # noqa: E402

LEGACY_PATH = L.LEGACY_ELO_ENGINE_FILE
CURRENT_PATH = os.path.join(HERE, "models", "elo_engine.py")


def _git(*args):
    try:
        r = subprocess.run(["git", "-C", REPO_ROOT, *args], capture_output=True,
                           text=True, timeout=30)
    except Exception:
        return None
    return r.stdout if r.returncode == 0 else None


class TestProvenienzaVerbatim(unittest.TestCase):
    def test_blob_sha_ricalcolato_in_python(self):
        self.assertEqual(L.git_blob_sha(LEGACY_PATH), L.LEGACY_ELO_BLOB_SHA)
        self.assertTrue(L.legacy_engine_is_verbatim())

    def test_git_conferma_che_e_il_file_pre_fix(self):
        atteso = _git("rev-parse", f"{L.LEGACY_ELO_SOURCE_COMMIT}:{L.LEGACY_ELO_SOURCE_PATH}")
        if not atteso:
            self.skipTest("clone senza l'oggetto git a435436 (shallow o senza git)")
        self.assertEqual(atteso.strip(), L.LEGACY_ELO_BLOB_SHA)
        contenuto = _git("cat-file", "-p", L.LEGACY_ELO_BLOB_SHA)
        with open(LEGACY_PATH, encoding="utf-8") as f:
            self.assertEqual(contenuto, f.read())

    def test_git_conferma_il_commit_che_lo_ha_sostituito(self):
        log = _git("log", "--format=%H %cI", "-1", L.LEGACY_ELO_REPLACED_BY_COMMIT)
        if not log:
            self.skipTest("commit 980e048 non presente nel clone")
        sha, quando = log.split()
        self.assertEqual(sha, L.LEGACY_ELO_REPLACED_BY_COMMIT)
        self.assertTrue(quando.startswith("2026-09-18T21:39:23"), quando)
        # Il blob del commit di fix e' gia' quello attuale, non piu' il legacy.
        dopo = _git("rev-parse", f"{L.LEGACY_ELO_REPLACED_BY_COMMIT}:{L.LEGACY_ELO_SOURCE_PATH}")
        self.assertIsNotNone(dopo)
        self.assertNotEqual(dopo.strip(), L.LEGACY_ELO_BLOB_SHA)
        # ... e il primo genitore della merge PR#24 e' proprio il commit sorgente.
        genitore = _git("rev-parse", f"{L.LEGACY_ELO_MERGE_COMMIT}^1")
        if genitore:
            self.assertEqual(genitore.strip(), L.LEGACY_ELO_SOURCE_COMMIT)


class TestUnicaDifferenza(unittest.TestCase):
    RIMOSSE_ATTESE = [
        "from scraper_xg import get_understat_xg",
        "xg_data = get_understat_xg(self.league_name) or {}",
        "xg_adj = 0.0",
        "if xg_data and h_team in xg_data and a_team in xg_data:",
        'h_xg = xg_data[h_team].get("xG_avg", 1.3)',
        'h_xga = xg_data[h_team].get("xGA_avg", 1.3)',
        'a_xg = xg_data[a_team].get("xG_avg", 1.3)',
        'a_xga = xg_data[a_team].get("xGA_avg", 1.3)',
        "xg_adj = ((h_xg - h_xga) - (a_xg - a_xga)) * 0.15",
        "",
        "xg_elo_boost = max(-100, min(100, xg_adj * 400))",
        "dr = r_h + self.home_adv - r_a + xg_elo_boost",
    ]
    AGGIUNTE_ATTESE = ["dr = r_h + self.home_adv - r_a"]

    @classmethod
    def setUpClass(cls):
        with open(LEGACY_PATH, encoding="utf-8") as f:
            cls.legacy = f.read()
        with open(CURRENT_PATH, encoding="utf-8") as f:
            cls.current = f.read()

    def test_il_diff_e_solo_il_boost_xg(self):
        diff = list(difflib.unified_diff(self.legacy.splitlines(), self.current.splitlines(),
                                         lineterm="", n=0))
        rimosse = [l[1:].strip() for l in diff if l.startswith("-") and not l.startswith("---")]
        aggiunte = [l[1:].strip() for l in diff if l.startswith("+") and not l.startswith("+++")]
        self.assertEqual(rimosse, self.RIMOSSE_ATTESE)
        self.assertEqual(aggiunte, self.AGGIUNTE_ATTESE)

    def _fn(self, src, nome):
        for node in ast.parse(src).body:
            if isinstance(node, ast.FunctionDef) and node.name == nome:
                return ast.unparse(node)
        raise AssertionError(nome)

    def test_predict_elo_probs_identica_nei_due_motori(self):
        self.assertEqual(self._fn(self.legacy, "predict_elo_probs"),
                         self._fn(self.current, "predict_elo_probs"))
        self.assertEqual(self._fn(self.legacy, "get_elo_engine"),
                         self._fn(self.current, "get_elo_engine"))

    def test_costanti_identiche(self):
        for nome in ("DEFAULT_INITIAL_RATING", "HOME_ADVANTAGE", "BASE_K_FACTOR",
                     "ELO_ENGINE_TTL_SECONDS"):
            self.assertIn(nome, self.legacy)
            riga_l = next(l for l in self.legacy.splitlines() if l.startswith(nome))
            riga_c = next(l for l in self.current.splitlines() if l.startswith(nome))
            self.assertEqual(riga_l, riga_c)


class TestConvivenza(unittest.TestCase):
    def test_moduli_e_cache_distinti(self):
        import models.elo_engine as attuale
        import models.elo_engine_legacy as legacy
        self.assertIsNot(attuale, legacy)
        self.assertIsNot(attuale._ELO_ENGINES_CACHE, legacy._ELO_ENGINES_CACHE)
        self.assertIs(L.predict_elo_probs_legacy, legacy.predict_elo_probs)
        self.assertIs(L.get_elo_engine_legacy, legacy.get_elo_engine)

    def test_stessi_dati_probabilita_diverse_se_ci_sono_le_medie_xg(self):
        from scraper_xg import get_understat_xg
        from models.elo_engine import predict_elo_probs
        if not get_understat_xg("Serie A"):
            self.skipTest("medie xG assenti: senza boost i due motori coincidono per costruzione")
        L.clear_legacy_elo_cache()
        a = predict_elo_probs("Inter", "Milan", "Serie A")
        b = L.predict_elo_probs_legacy("Inter", "Milan", "Serie A")
        self.assertEqual(set(a), set(b))
        self.assertNotEqual((a["elo_home"], a["elo_away"]), (b["elo_home"], b["elo_away"]))
        # entrambe distribuzioni valide
        for p in (a, b):
            self.assertAlmostEqual(p["1"] + p["X"] + p["2"], 1.0, places=3)
            self.assertEqual(p["home_adv"], a["home_adv"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
