#!/usr/bin/env python3
"""test_live_odds_match.py — Test offline di audit/live_odds_match.py.

Legge solo gli snapshot committati in audit/data/live_odds_probe/ e i CSV in
SoccerMath/database: nessuna rete e nessuna scrittura.

I valori attesi sono quelli dello snapshot del 2026-10-08: se il probe viene
rifatto (partite diverse, squadre diverse) i contatori vanno aggiornati.
"""
from __future__ import annotations

import os
import sys
import unittest

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

import live_odds_match as LOM  # noqa: E402
from team_aliases import clean_name  # noqa: E402

SNAPSHOT = "2026-10-08"
# valori misurati sullo snapshot committato
ATTESO = {
    "Serie A": (10, 10, 10),
    "Premier League": (10, 10, 10),
    "La Liga": (10, 5, 6),
    "Bundesliga": (9, 6, 7),
    "Ligue 1": (9, 8, 9),
}
NOMI_NON_CENSITI = [
    "Atlético Madrid", "Borussia Monchengladbach", "CA Osasuna", "Elche CF",
    "FSV Mainz 05", "Real Racing Club de Santander",
]


class TestInsiemeCanonico(unittest.TestCase):
    def test_canonici_non_vuoti_per_tutte_le_leghe(self):
        for prefix, (lega, _key) in LOM.LEAGUES.items():
            nomi = LOM.canonical_names(prefix, [LOM.CURRENT_SUFFIX])
            self.assertGreater(len(nomi), 0, lega)

    def test_clean_name_e_idempotente_sui_canonici(self):
        nomi = LOM.canonical_names("SerieA", [LOM.CURRENT_SUFFIX])
        for n in nomi:
            self.assertEqual(clean_name(n), n, n)

    def test_linsieme_con_la_stagione_precedente_non_stringe(self):
        solo = LOM.canonical_names("LaLiga", [LOM.CURRENT_SUFFIX])
        entrambi = LOM.canonical_names("LaLiga", [LOM.CURRENT_SUFFIX, LOM.PREV_SUFFIX])
        self.assertTrue(solo <= entrambi)


class TestAbbinamento(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = LOM.build_payload()

    def test_snapshot_presente(self):
        self.assertTrue(self.payload["istante_di_riferimento"].startswith(SNAPSHOT))
        for lega, v in self.payload["per_lega"].items():
            self.assertTrue(v["disponibile"], lega)

    def test_partite_e_abbinamenti_per_lega(self):
        for lega, (n, ok, ok_res) in ATTESO.items():
            v = self.payload["per_lega"][lega]
            self.assertEqual(v["n_prossima_giornata"], n, lega)
            self.assertEqual(v["n_abbinate"], ok, lega)
            self.assertEqual(v["n_abbinate_resolver"], ok_res, lega)

    def test_totali(self):
        t = self.payload["totale"]
        self.assertEqual(t["n_prossima_giornata"], 48)
        self.assertEqual(t["n_abbinate"], 39)
        self.assertEqual(t["n_abbinate_resolver"], 42)
        self.assertAlmostEqual(t["pct_abbinate"], 39 / 48, places=12)

    def test_il_resolver_non_puoi_essere_peggiore_di_clean_name(self):
        for lega, v in self.payload["per_lega"].items():
            self.assertGreaterEqual(v["n_abbinate_resolver"], v["n_abbinate"], lega)

    def test_nessun_fuzzy_matching(self):
        """Un nome fuori tabella resta fuori: nessuna somiglianza viene usata."""
        for u in self.payload["nomi_non_abbinati"]:
            self.assertNotEqual(u["raw"], "")
            self.assertIsNotNone(u["clean"])
        for u in self.payload["nomi_non_abbinati"]:
            if u["resolver_source"] == "unknown":
                self.assertFalse(u["risolto_dal_resolver"])

    def test_nomi_non_censiti_attesi(self):
        mancanti = [u["raw"] for u in self.payload["nomi_non_abbinati"]
                    if not u["risolto_dal_resolver"]]
        for nome in NOMI_NON_CENSITI:
            self.assertIn(nome, mancanti)

    def test_nomi_unici(self):
        chiavi = [(u["lega"], u["raw"]) for u in self.payload["nomi_non_abbinati"]]
        self.assertEqual(len(chiavi), len(set(chiavi)))

    def test_prossima_giornata_dentro_la_finestra_di_produzione(self):
        for lega, v in self.payload["per_lega"].items():
            self.assertIsNotNone(v["primo_kickoff"])
            self.assertLessEqual(v["primo_kickoff"][:10], v["fine_finestra"][:10])
            self.assertEqual(v["n_prossima_giornata"] > 0, True)

    def test_determinismo(self):
        secondo = LOM.build_payload()
        self.assertEqual(secondo["totale"], self.payload["totale"])

    def test_json_serializzabile(self):
        import json
        json.dumps(self.payload, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
