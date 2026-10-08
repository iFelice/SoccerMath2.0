#!/usr/bin/env python3
"""test_live_odds_feasibility.py — Test offline del referto di fattibilita'.

Verifica la parte di CALCOLO (turni infrasettimanali, budget in crediti, quadro
di sintesi) e che il referto committato contenga le sezioni richieste. Nessuna
rete: legge gli snapshot in audit/data/live_odds_probe/ e i CSV del repository.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)

import live_odds_feasibility as LOF  # noqa: E402
import live_odds_match as LOM  # noqa: E402


class TestTurniInfrasettimanali(unittest.TestCase):
    def test_2024_25(self):
        starts, per_month, n_mesi = LOF.midweek_rounds("2024")
        self.assertEqual(len(starts), 22)
        self.assertEqual(n_mesi, 10)
        self.assertEqual(max(per_month.values()), 4)

    def test_2025_26(self):
        starts, per_month, n_mesi = LOF.midweek_rounds("2025")
        self.assertEqual(len(starts), 17)
        self.assertEqual(max(per_month.values()), 3)

    def test_solo_date_di_martedi_mercoledi_giovedi(self):
        starts, _pm, _m = LOF.midweek_rounds("2025")
        for d in starts:
            self.assertIn(d.weekday(), (1, 2, 3), str(d))


class TestBudget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(LOF.DATA_DIR, "probe_summary.json"), encoding="utf-8") as fh:
            probe = json.load(fh)
        cls.probe = probe
        cls.budget, _stagioni = LOF.build_budget(probe)

    def test_due_scenari(self):
        self.assertEqual([s["regioni"] for s in self.budget["scenari"]], ["eu,uk", "eu"])

    def test_costo_misurato_per_chiamata(self):
        self.assertEqual([s["costo_chiamata"] for s in self.budget["scenari"]], [2, 1])

    def test_crediti_per_giro(self):
        for s in self.budget["scenari"]:
            self.assertEqual(s["crediti_per_giro_5_leghe"], s["costo_chiamata"] * 5)

    def test_aritmetica_del_mese_tipo(self):
        base = LOF.UPDATES_PER_WEEK * LOF.WEEKS_PER_MONTH
        for s in self.budget["scenari"]:
            self.assertAlmostEqual(s["crediti_mese_base"], base * s["crediti_per_giro_5_leghe"],
                                   places=6)
            self.assertGreater(s["crediti_mese_medio"], s["crediti_mese_base"])
            self.assertGreaterEqual(s["crediti_mese_peggiore"], s["crediti_mese_medio"])

    def test_sta_nel_piano_gratuito(self):
        for s in self.budget["scenari"]:
            self.assertTrue(s["sta_nei_500"], s["regioni"])
            self.assertLessEqual(s["crediti_mese_peggiore"], 500)

    def test_crediti_consumati_dalle_prove(self):
        self.assertEqual(self.budget["crediti_consumati_dalle_prove"], 12)
        self.assertEqual(self.budget["crediti_usati_dopo_le_prove"], 43)
        self.assertGreater(int(self.budget["crediti_residui_alla_prova"]), 0)


class TestQuadroDiSintesi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(LOF.DATA_DIR, "probe_summary.json"), encoding="utf-8") as fh:
            probe = json.load(fh)
        match = LOM.build_payload()
        budget, stagioni = LOF.build_budget(probe)
        # il confronto fra book non serve al quadro di sintesi: payload minimo
        bst = {"reps": 0, "seed": 0, "campioni": {}, "etichette": {},
               "comune": {"quality": [], "topmix": [], "diffs": {}}, "verdetti": {},
               "motivi": [], "live_availability": {"disponibile": False}}
        cls.stato = LOF.repo_state()
        cls.ci = {"suite": "success", "audit": "success", "replay": "skipped"}
        cls.checks = LOF.build_checks(probe, bst, match, budget, cls.stato, cls.ci)

    def test_tredici_voci(self):
        self.assertEqual(len(self.checks["sintesi"]), 13)

    def test_esiti_attesi(self):
        esiti = {r[0]: r[2] for r in self.checks["sintesi"]}
        self.assertEqual(esiti["2"], "OK")                  # copertura 5 leghe
        self.assertEqual(esiti["3"], "NON OK")              # Bet365 assente
        self.assertEqual(esiti["4"], "OK")                  # Pinnacle presente
        self.assertEqual(esiti["8"], "NON OK")              # fixtures: 0 partite
        self.assertEqual(esiti["9"], "NON VERIFICABILE")    # terza fonte
        self.assertEqual(esiti["10"], "NON OK")             # abbinamento parziale
        self.assertEqual(esiti["11"], "OK")                 # budget

    def test_ogni_voce_ha_comando_e_evidenza(self):
        for riga in self.checks["sintesi"]:
            self.assertEqual(len(riga), 5)
            for campo in riga:
                self.assertNotEqual(str(campo).strip(), "")

    def test_raccomandazione_non_vuota(self):
        self.assertGreaterEqual(len(self.checks["raccomandazione"]), 4)
        self.assertTrue(any("The Odds API" in p for p in self.checks["raccomandazione"]))

    def test_verdetto_con_criteri_soddisfatti(self):
        verdetto, criteri = LOF.mergeability(
            {"solo_audit": True, "tocca_soccermath": False, "tocca_workflow": False,
             "dirs": ["audit"], "n_file": 10, "file": []},
            {"suite": "success", "audit": "success", "replay": "skipped"})
        self.assertEqual(verdetto, "MERGEABLE")
        self.assertTrue(all(c[1] for c in criteri))

    def test_verdetto_negativo_se_il_diff_esce_da_audit(self):
        verdetto, criteri = LOF.mergeability(
            {"solo_audit": False, "tocca_soccermath": True, "tocca_workflow": False,
             "dirs": ["audit", "SoccerMath"], "n_file": 2, "file": []},
            {"suite": "success", "audit": "success", "replay": "skipped"})
        self.assertEqual(verdetto, "NON MERGEABLE")
        self.assertFalse(criteri[1][1])

    def test_verdetto_negativo_se_la_ci_non_e_verde(self):
        verdetto, _c = LOF.mergeability(
            {"solo_audit": True, "tocca_soccermath": False, "tocca_workflow": False,
             "dirs": ["audit"], "n_file": 1, "file": []},
            {"suite": "failure", "audit": "success", "replay": "skipped"})
        self.assertEqual(verdetto, "NON MERGEABLE")

    def test_limiti_dichiarati(self):
        self.assertGreaterEqual(len(self.checks["limiti"]), 5)


class TestReferto(unittest.TestCase):
    def test_file_presente_e_completo(self):
        self.assertTrue(os.path.exists(LOF.REPORT_PATH))
        testo = open(LOF.REPORT_PATH, encoding="utf-8").read()
        for sezione in ("## 0.", "## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6.", "## 7."):
            self.assertIn(sezione, testo)
        for parola in ("MERGEABLE",):
            self.assertIn(parola, testo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
