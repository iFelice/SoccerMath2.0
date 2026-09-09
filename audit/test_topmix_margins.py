"""Test di ``audit/topmix_margins.py``.

Deterministici e offline: nessun accesso di rete, nessuna lettura del database
di produzione, nessuna scrittura fuori da una tmpdir. Verificano le parti NUOVE
dell'harness (attribuzione degli scarti, pool e taglio a 10, bootstrap,
trasferimento cross-stagione, sola lettura) e — quando l'artefatto è presente —
che le metriche ricalcate coincidano con ``topmix_selector_replay.json``.

Eseguibili con pytest o direttamente:
    python -m pytest audit/test_topmix_margins.py -q
    python audit/test_topmix_margins.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
if _AUDIT_DIR not in sys.path:
    sys.path.insert(0, _AUDIT_DIR)

import topmix_margins as M  # noqa: E402

RESULTS = os.path.join(_AUDIT_DIR, "results")
ROWS_CSV = os.path.join(RESULTS, "topmix_selector_replay_rows.csv")
SUMMARY_JSON = os.path.join(RESULTS, "topmix_selector_replay.json")


def _row(market="1", conf=0.70, poisson=None, disagree=0.05, min_conf=0.55,
         admitted=None, hit=1, league="Serie A", season="2024/25",
         match_id="X|0", cutoff="2024-08-17T17:30:00+00:00", matchday=1,
         elo_available=True, team_stats_missing=0):
    """Riga già tipizzata, con le chiavi prodotte da ``parse_row``."""
    admitted = (conf >= min_conf and disagree < 0.25) if admitted is None else admitted
    return {
        "league": league, "season": season, "matchday": matchday, "cutoff": cutoff,
        "match_id": match_id, "home": "A", "away": "B",
        "A_market": market,
        "A_poisson": conf if poisson is None else poisson,
        "A_conf": conf, "A_disagree": disagree, "A_min_conf": min_conf,
        "A_admitted": bool(admitted), "A_hit": hit,
        "B_market": market, "B_conf": conf, "B_admitted": bool(admitted),
        "B_n_admitted_markets": 1 if admitted else 0, "B_hit": hit,
        "B_hit_known": True, "elo_available": elo_available,
        "team_stats_missing": team_stats_missing,
    }


class TestPrimitivi(unittest.TestCase):
    def test_quality_formula_a_mano(self):
        q = M.quality([(0.5, 1), (0.5, 0)])
        self.assertEqual(q["n"], 2)
        self.assertAlmostEqual(q["mean_prob"], 0.5)
        self.assertAlmostEqual(q["hit_rate"], 0.5)
        self.assertAlmostEqual(q["brier"], 0.25)
        self.assertAlmostEqual(q["gap"], 0.0)

    def test_quality_segnale_del_gap(self):
        # prob > frequenza reale => gap positivo (sovrastima)
        self.assertGreater(M.quality([(0.8, 0), (0.8, 0)])["gap"], 0)
        self.assertLess(M.quality([(0.4, 1), (0.4, 1)])["gap"], 0)

    def test_quality_vuoto_e_probabilita_mancanti(self):
        self.assertEqual(M.quality([]), {"n": 0, "mean_prob": None, "hit_rate": None,
                                         "brier": None, "gap": None})
        self.assertEqual(M.quality([(None, 1)])["n"], 0)

    def test_parse_row_tipizza_tutto(self):
        r = M.parse_row({"league": "Serie A", "season_label": "2024/25", "matchday": "3",
                         "cutoff": "2024-08-17T17:30:00+00:00", "match_id": "S|1",
                         "A_market": "O2.5", "A_poisson": "0.61", "A_conf": "0.61",
                         "A_disagree": "0.0", "A_min_conf": "0.6", "A_admitted": "True",
                         "A_hit": "1", "B_conf": "", "B_admitted": "False",
                         "B_n_admitted_markets": "", "B_hit": "", "elo_available": "True",
                         "team_stats_missing": ""})
        self.assertEqual(r["A_conf"], 0.61)
        self.assertTrue(r["A_admitted"])
        self.assertEqual(r["A_hit"], 1)
        self.assertIsNone(r["B_conf"])
        self.assertFalse(r["B_hit_known"])
        self.assertEqual(r["team_stats_missing"], 0.0)


class TestPoolETaglio(unittest.TestCase):
    def test_iso_week_usa_la_settimana_del_cutoff(self):
        self.assertEqual(M.iso_week("2024-08-17T17:30:00+00:00"), "2024-W33")

    def test_pool_chiaveInclude_la_stagione(self):
        a = _row(cutoff="2025-01-04T18:00:00+00:00", season="2024/25")
        b = _row(cutoff="2025-01-04T18:00:00+00:00", season="2025/26")
        self.assertNotEqual(M.pool_key(a), M.pool_key(b))
        self.assertEqual(M.pool_key(a)[0], "2025-W01")

    def test_select_top_ordina_e_taglia(self):
        pool = [_row(conf=c / 100, match_id=f"m{i}") for i, c in enumerate(
            [70, 65, 80, 75, 90, 60, 85, 55, 78, 72, 71, 69])]
        sel = M.select_top(pool, lambda r: True)
        self.assertEqual(len(sel), 10)
        self.assertEqual(sel[0]["A_conf"], 0.90)
        self.assertEqual([r["A_conf"] for r in sel[:3]], [0.90, 0.85, 0.80])

    def test_select_top_rispetta_il_filtro(self):
        pool = [_row(conf=0.9, admitted=False), _row(conf=0.8, admitted=True)]
        self.assertEqual(len(M.select_top(pool, lambda r: r["A_admitted"])), 1)
        self.assertEqual(len(M.select_top(pool, lambda r: True)), 2)


class TestVincoli(unittest.TestCase):
    def test_soglia_e_sono_ammesse(self):
        self.assertFalse(M.below_threshold(_row(conf=0.55, min_conf=0.55)))
        self.assertTrue(M.below_threshold(_row(conf=0.5499, min_conf=0.55)))

    def test_gate_e_al_blocca(self):
        self.assertFalse(M.gate_blocks(_row(disagree=0.2499)))
        self.assertTrue(M.gate_blocks(_row(disagree=0.25)))

    def test_reject_reason_quattro_casi(self):
        self.assertIsNone(M.reject_reason(_row(conf=0.7, disagree=0.1, admitted=True)))
        self.assertEqual(M.reject_reason(_row(conf=0.50, disagree=0.0, admitted=False)), "soglia")
        self.assertEqual(M.reject_reason(_row(conf=0.70, disagree=0.3, admitted=False)), "disaccordo")
        self.assertEqual(M.reject_reason(_row(conf=0.50, disagree=0.3, admitted=False)), "entrambi")

    def test_rejection_breakdown_e_esauritivo(self):
        rows = [_row(conf=0.7, admitted=True), _row(conf=0.5, admitted=False),
                _row(conf=0.7, disagree=0.4, admitted=False),
                _row(conf=0.5, disagree=0.4, admitted=False)]
        rb = M.rejection_breakdown(rows)
        self.assertEqual(rb["n_admitted"] + sum(rb["reasons"].values()), rb["n_candidates"])
        self.assertEqual(rb["reasons"], {"soglia": 1, "disaccordo": 1, "entrambi": 1})

    def test_gate_only_esclude_chi_e_gia_sotto_soglia(self):
        rows = [_row(conf=0.70, disagree=0.40, admitted=False),
                _row(conf=0.50, disagree=0.40, admitted=False)]
        g = M.gate_only_rejections(rows)
        self.assertEqual(g["n"], 1)
        self.assertEqual(g["markets"], {"1": 1})

    def test_market_bias_rispetta_la_numerosita_minima(self):
        rows = [_row(market="1", conf=0.7, hit=1, match_id="a"),
                _row(market="1", conf=0.7, hit=0, match_id="b")]
        self.assertEqual(M.market_bias(rows, min_n=30), {})
        self.assertAlmostEqual(M.market_bias(rows, min_n=2)["1"], 0.20)


class TestGateSullaTop10(unittest.TestCase):
    def _pool(self):
        # 12 partite nello stesso pool: 4 sono bloccate SOLO dal gate e hanno
        # confidence piu' alta di alcune ammesse -> devono cambiare gli slot
        rows = []
        for i, (conf, dis) in enumerate([(0.80, 0.30), (0.79, 0.30), (0.78, 0.05),
                                         (0.77, 0.05), (0.76, 0.05), (0.75, 0.05),
                                         (0.74, 0.05), (0.73, 0.05), (0.72, 0.05),
                                         (0.71, 0.05), (0.70, 0.05), (0.69, 0.05)]):
            rows.append(_row(conf=conf, disagree=dis, min_conf=0.55,
                             admitted=(dis < 0.25), hit=1 if i % 2 == 0 else 0,
                             match_id=f"p|{i}"))
        return rows

    def test_con_gate_riempie_dieci_slot(self):
        t = M.top10_gate_comparison(self._pool())
        self.assertEqual(t["con_gate"]["n"], 10)
        self.assertEqual(t["senza_gate"]["n"], 10)

    def test_senza_gate_entrano_le_bloccate(self):
        t = M.top10_gate_comparison(self._pool())
        self.assertEqual(t["swap"]["n"], 2)          # le due con |Δ| >= 0,25
        self.assertEqual(t["swap"]["entrano"]["n"], 2)
        self.assertEqual(t["swap"]["escono"]["n"], 2)
        self.assertEqual(t["swap"]["entrano"]["markets"], {"1": 2})
        self.assertEqual(t["swap"]["escono"]["markets"], {"1": 2})
        self.assertAlmostEqual(t["swap"]["entrano"]["mean_prob"], 0.795, places=6)
        self.assertAlmostEqual(t["swap"]["escono"]["mean_prob"], 0.695, places=6)

    def test_soglia_del_decimo_slot(self):
        t = M.top10_gate_comparison(self._pool())
        self.assertEqual(t["slot10"]["n_pools"], 1)
        self.assertAlmostEqual(t["slot10"]["mean"], 0.69)
        self.assertAlmostEqual(t["slot10"]["min"], 0.69)

    def test_bootstrap_e_deterministico(self):
        rows = self._pool()
        a = M.top10_gate_comparison(rows)["bootstrap"]
        b = M.top10_gate_comparison(rows)["bootstrap"]
        self.assertEqual(a, b)
        self.assertEqual(a["seed"], M.SEED)
        self.assertEqual(a["n_blocks"], 1)
        self.assertEqual(a["brier"]["ci95"][0], a["brier"]["ci95"][1])

    def test_slot_marginality_esige_quindici_righe(self):
        # 12 candidate di cui 10 ammesse: non ci sono 15 righe ammesse -> vuoto
        self.assertEqual(M.slot_marginality(self._pool())["in_top10"]["n"], 0)
        rows = self._pool() + [_row(conf=0.68, match_id=f"e{i}") for i in range(5)]
        sm = M.slot_marginality(rows)
        self.assertEqual(sm["in_top10"]["n"], 10)
        self.assertEqual(sm["rank_11_15"]["n"], 5)


class TestScalaDeiMercati(unittest.TestCase):
    def test_cross_season_fuori_target(self):
        self.assertFalse(M.cross_season_calibration([_row(season="2024/25")])["available"])

    def test_cross_season_calcola_discordanza(self):
        rows = []
        for i in range(M.MIN_N_PER_MARKET):
            # 2024/25: '1' sempre giusto -> bias 0.7-1.0; 2025/26: '1' meta' -> bias 0.7-0.5
            rows.append(_row(market="1", conf=0.7, hit=1, season="2024/25", match_id=f"a{i}"))
            rows.append(_row(market="1", conf=0.7, hit=1 if i % 2 else 0,
                             season="2025/26", match_id=f"b{i}"))
        out = M.cross_season_calibration(rows)
        self.assertTrue(out["available"])
        self.assertAlmostEqual(out["bias"]["2024/25"]["1"], -0.30, places=6)
        self.assertAlmostEqual(out["bias"]["2025/26"]["1"], 0.20, places=6)
        self.assertAlmostEqual(out["mean_abs_bias_diff"], 0.50, places=6)
        self.assertEqual(len(out["esperimenti"]), 2)
        for e in out["esperimenti"]:
            self.assertIn("delta_brier_ranking", e)
            self.assertIn("stesse_righe_prob_esposta_corretta", e)


class TestQualitaDati(unittest.TestCase):
    def test_data_quality_conta_duplicati_e_fallback(self):
        rows = [_row(match_id="d|1"), _row(match_id="d|1"),
                _row(match_id="d|2", elo_available=False, team_stats_missing=1)]
        dq = M.data_quality(rows)
        self.assertEqual(dq["n"], 3)
        self.assertEqual(dq["match_id_distinti"], 2)
        self.assertEqual(dq["match_id_duplicati"], 1)
        self.assertEqual(dq["elo_non_disponibile"], 1)
        self.assertEqual(dq["team_stats_mancanti"], 1)

    def test_units_fallback_legge_anche_senza_artefatto(self):
        self.assertIsNone(M.replay_units_fallback(None))
        self.assertIsNone(M.replay_units_fallback({"units": []}))
        u = {"units": [{"league": "Serie A", "season": 2024, "matchday": 1, "xg_teams": 0},
                        {"league": "Serie A", "season": 2024, "matchday": 2, "xg_teams": 20}]}
        f = M.replay_units_fallback(u)
        self.assertEqual(f["n_units"], 2)
        self.assertEqual(f["n_senza_xg"], 1)
        self.assertTrue(f["solo_prima_giornata"])


class TestSolaLettura(unittest.TestCase):
    """Nessun import di produzione, nessuna scrittura di registro, nessuna rete."""

    SRC = open(os.path.join(_AUDIT_DIR, "topmix_margins.py"), encoding="utf-8").read()

    def test_nessun_import_di_produzione(self):
        for forbidden in ("import app", "from app", "import pandas", "import numpy",
                          "import requests", "from requests", "JSONBin", "jsonbin",
                          "save_prediction_entry", "save_predictions(", "load_predictions("):
            self.assertNotIn(forbidden, self.SRC, f"non ammesso in un audit in sola lettura: {forbidden}")

    def test_scrittura_solo_nella_tmpdir(self):
        with tempfile.TemporaryDirectory() as td:
            out_md = os.path.join(td, "m.md")
            out_json = os.path.join(td, "m.json")
            rc = M.main(["--rows", ROWS_CSV if os.path.exists(ROWS_CSV) else os.path.join(td, "x"),
                         "--summary", "", "--out", out_md, "--json", out_json]) \
                if os.path.exists(ROWS_CSV) else None
            if rc is None:
                self.skipTest("artefatto del replay non presente")
            self.assertEqual(rc, 0)
            for p in (out_md, out_json):
                self.assertTrue(os.path.exists(p))

    def test_render_produce_le_sezioni_attese(self):
        rows = [_row(conf=0.7, hit=1, match_id=f"r{i}") for i in range(12)] + \
               [_row(market="O2.5", conf=0.62, min_conf=0.60, hit=0, match_id=f"o{i}") for i in range(12)] + \
               [_row(season="2025/26", conf=0.7, hit=1, match_id=f"s{i}") for i in range(12)]
        payload = M.compute(rows, None)
        text = M.render_markdown(payload, {"generated_at": "x", "git_sha": "y", "n_rows": len(rows),
                                           "rows_file": "z", "season_status": "test"})
        for h in ("## 0. Consistenza", "## 1. Dove finisce", "## 2. Qualità", "## 4. Top 10",
                  "## 5. Scala dei mercati", "## 8. Cosa questi numeri NON dimostrano",
                  "## 9. Riproduzione"):
            self.assertIn(h, text)


@unittest.skipUnless(os.path.exists(ROWS_CSV) and os.path.exists(SUMMARY_JSON),
                     "artefatti del replay non presenti")
class TestConsistenzaConIlReplayCommittato(unittest.TestCase):
    """Le metriche ricalcate devono coincidere con l'artefatto pubblicato."""

    @classmethod
    def setUpClass(cls):
        cls.rows = M.load_rows(ROWS_CSV)
        import json
        with open(SUMMARY_JSON, encoding="utf-8") as fh:
            cls.summary = json.load(fh)

    def test_perimetro_atteso(self):
        self.assertEqual(len(self.rows), 3422)
        self.assertEqual(sum(1 for r in self.rows if r["A_admitted"]), 1865)

    def test_tutte_le_grandezze_coincidono(self):
        checks = M.consistency_checks(self.rows, self.summary)
        self.assertGreater(len(checks), 10)
        bad = [c for c in checks if not c["ok"]]
        self.assertEqual([], bad, "deriva dalle selezioni committate: " + str(bad))

    def test_headline_del_report(self):
        qa = M.quality_of([r for r in self.rows if r["A_admitted"]])
        self.assertAlmostEqual(qa["brier"], 0.2312, places=4)
        self.assertAlmostEqual(qa["hit_rate"], 0.6198, places=4)
        t = M.top10_gate_comparison(self.rows)
        self.assertAlmostEqual(t["con_gate"]["brier"], 0.2013, places=4)
        self.assertEqual(t["n_pools"], 74)
        # il gate rimosso migliora il punto stimato, senza essere significativo
        self.assertLess(t["delta"]["brier"], 0)
        self.assertGreater(t["bootstrap"]["brier"]["ci95"][1], 0)


class TestIsotona(unittest.TestCase):
    def test_pava_e_monotona(self):
        import random as _r
        rnd = _r.Random(7)
        pairs = []
        for _ in range(4000):
            p = rnd.uniform(0.5, 0.95)
            y = 1 if rnd.random() < (p - 0.06) else 0      # sovrastima di 6 pp
            pairs.append((p, y))
        g = M.fit_isotonic(pairs)
        xs = [x / 100 for x in range(50, 96)]
        ys = [g(x) for x in xs]
        self.assertTrue(all(b >= a - 1e-9 for a, b in zip(ys, ys[1:])), "la mappa deve essere non decrescente")
        # e recupera la sovrastima: sopra la prob. media reale c'e' circa 6 pp
        self.assertLess(g(0.75), 0.75)
        self.assertGreater(g(0.75), 0.60)

    def test_pava_degenera(self):
        g = M.fit_isotonic([(0.5, 1)])
        self.assertEqual(g(0.5), 0.5)          # sotto le 2 coppie: identita'

    def test_transfer_globale_fuori_target(self):
        self.assertFalse(M.global_reliability_transfer([_row(season="2024/25")])["available"])

    def test_transfer_globale_gira_entrambe_le_stagioni(self):
        rows = []
        for j, seas in enumerate(("2024/25", "2025/26")):
            for i in range(40):
                rows.append(_row(conf=0.70 + (i % 5) / 100, hit=1 if (i + j) % 2 else 0,
                                 season=seas, match_id=f"{j}|{i}"))
        out = M.global_reliability_transfer(rows)
        self.assertTrue(out["available"])
        self.assertEqual({e["target"] for e in out["esperimenti"]}, {"2024/25", "2025/26"})
        for e in out["esperimenti"]:
            self.assertIn("delta_brier", e)


if __name__ == "__main__":
    unittest.main(verbosity=2)
