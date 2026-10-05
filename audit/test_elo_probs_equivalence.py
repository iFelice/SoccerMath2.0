"""
test_elo_probs_equivalence.py — Confronto BIT-EXACT fra il codice corrente e
la fixture di equivalenza congelata, generata con il codice di MAIN PRIMA
dell'estrazione di ``elo_probs_from_ratings`` (PR #30).

Fixture
-------
``audit/fixtures/elo_probs_equivalence_main.jsonl.gz``
``audit/fixtures/elo_probs_equivalence_main.manifest.json``

Generata da ``audit/make_elo_probs_equivalence_fixture.py`` eseguito su un
worktree a ``3f9f04278096aba2bc96fc5335a45ccd0d219094`` (= ``origin/main``,
merge della PR #29) con ``git status --porcelain -- SoccerMath/`` vuoto.
Il commit di generazione e lo stato pulito della produzione sono registrati
dentro il manifest e ri-asseriti da questo test.

Contenuto (32539 casi):
  (a) 25205 casi di griglia: rating 1200..1900 passo 10 (71 x 71) per
      l'home advantage di ciascuna delle 5 leghe;
  (b) 7334 partite storiche di tutte le leghe, stato del motore
      point-in-time (rating pre-partita).

Il test rigenera entrambi i blocchi con il codice CORRENTE e confronta il
``repr(float)`` di OGNI chiave di OGNI caso. Nessun ``assertAlmostEqual``.

Esecuzione:
    python audit/test_elo_probs_equivalence.py
    python -m pytest audit/test_elo_probs_equivalence.py -v
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
import unittest

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

import make_elo_probs_equivalence_fixture as GEN  # noqa: E402

FIX_JSONL = os.path.join(_AUDIT_DIR, "fixtures", "elo_probs_equivalence_main.jsonl.gz")
FIX_MANIFEST = os.path.join(_AUDIT_DIR, "fixtures",
                            "elo_probs_equivalence_main.manifest.json")
MAIN_COMMIT = "3f9f04278096aba2bc96fc5335a45ccd0d219094"


def _carica_fixture():
    with gzip.open(FIX_JSONL, "rt", encoding="utf-8") as f:
        payload = f.read()
    righe = [json.loads(x) for x in payload.splitlines()]
    with open(FIX_MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    return payload, righe, manifest


def _rigenera():
    righe = []
    na = GEN.block_a(righe.append)
    nb = GEN.block_b(righe.append)
    payload = "\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False)
                        for r in righe) + "\n"
    return payload, righe, na, nb


class TestEquivalenzaBitExact(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.pay_fix, cls.righe_fix, cls.manifest = _carica_fixture()
        cls.pay_now, cls.righe_now, cls.na, cls.nb = _rigenera()

    def test_provenienza_fixture(self):
        self.assertEqual(self.manifest["repo_head_commit"], MAIN_COMMIT)
        self.assertEqual(self.manifest["produzione_sporca_rispetto_al_commit"],
                         "(pulita)")
        self.assertEqual(
            hashlib.sha256(self.pay_fix.encode("utf-8")).hexdigest(),
            self.manifest["sha256_payload_non_compresso"])

    def test_conteggi(self):
        self.assertEqual(self.na, self.manifest["n_grid"])
        self.assertEqual(self.nb, self.manifest["n_match"])
        self.assertEqual(len(self.righe_now), len(self.righe_fix))

    def test_tutte_le_chiavi_bit_exact(self):
        diffs = []
        for i, (a, b) in enumerate(zip(self.righe_fix, self.righe_now)):
            if a["meta"] != b["meta"] or a["kind"] != b["kind"]:
                diffs.append((i, "meta", a["meta"], b["meta"]))
                continue
            if set(a["probs_repr"]) != set(b["probs_repr"]):
                diffs.append((i, "chiavi", sorted(a["probs_repr"]),
                              sorted(b["probs_repr"])))
                continue
            for k in a["probs_repr"]:
                if a["probs_repr"][k] != b["probs_repr"][k]:
                    diffs.append((i, k, a["probs_repr"][k], b["probs_repr"][k]))
        if diffs:
            testa = "\n".join(f"  caso {i} chiave {k}: main={x} branch={y}"
                              for i, k, x, y in diffs[:20])
            self.fail(f"{len(diffs)} differenze (prime 20):\n{testa}")

    def test_sha256_payload_identico(self):
        self.assertEqual(hashlib.sha256(self.pay_now.encode("utf-8")).hexdigest(),
                         self.manifest["sha256_payload_non_compresso"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
