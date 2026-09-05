"""Test sul tracciamento Top Mix: solo ispezione del codice, nessuna scrittura registro.

Non importa ``app`` (niente Streamlit/JSONBin). Verifica i problemi di
misurabilita' del Top Mix sul sorgente di produzione.
"""
from __future__ import annotations

import ast
import os
import sys
import unittest

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)

from inspect_topmix_registry import (  # noqa: E402
    APP_PATH,
    inspect_app,
    inspect_registry_module,
    tracking_verdict,
)


class TestTrackingInspection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.facts = inspect_app()
        cls.verdict = tracking_verdict(cls.facts)

    def test_production_functions_found(self):
        found = self.facts["functions_found"]
        for name in (
            "save_prediction_entry", "save_predictions", "fetch_and_calc_top_mix",
            "analisi_rapida_giornata", "show_details",
        ):
            self.assertTrue(found[name], name)

    def test_dedup_early_return_on_match_id(self):
        d = self.facts["dedup_by_match_id"]
        self.assertTrue(d["present"])
        self.assertTrue(d["early_return"])
        self.assertIn("match_id", d["source"])

    def test_tipo_collapses_billy_into_analisi(self):
        tipo = self.facts["tipo_classification"]
        self.assertIn("Top Mix", tipo["rule"])
        self.assertIn("Analisi", tipo["rule"])
        self.assertFalse(tipo["billy_tipo_esplicito"])

    def test_cache_is_30_minutes_and_nullary(self):
        cache = self.facts["top_mix_cache"]
        self.assertEqual(cache["ttl_seconds"], 1800)
        self.assertTrue(cache["no_arguments"])

    def test_jsonbin_put_unchecked(self):
        jb = self.facts["jsonbin_write"]
        self.assertTrue(jb["put_present"])
        self.assertFalse(jb["status_code_checked"])
        self.assertTrue(jb["except_pass"])

    def test_success_toast_not_gated(self):
        toast = self.facts["top_mix_success_toast"]
        self.assertTrue(toast["present_in_module"])
        self.assertFalse(toast["gated_on_remote_ok"])

    def test_seven_markets_and_selector_order(self):
        s = self.facts["top_mix_selector"]
        self.assertTrue(s["has_1"] and s["has_X"] and s["has_2"])
        self.assertTrue(s["has_over"] and s["has_under"])
        self.assertTrue(s["has_gg"] and s["has_ng"])
        self.assertFalse(s["has_over_15"])
        self.assertFalse(s["has_over_35"])
        self.assertTrue(s["max_then_filter"])
        self.assertTrue(s["elo_mix_1x2"])
        self.assertTrue(s["min_conf_ou_gg"])
        self.assertTrue(s["min_conf_1x2"])
        self.assertTrue(s["disagree"])
        self.assertTrue(s["global_top10"])

    def test_cannot_measure_top_mix_in_isolation(self):
        self.assertFalse(self.verdict["can_measure_top_mix_in_isolation"])
        ids = {p["id"] for p in self.verdict["problems"]}
        self.assertIn("dedup_match_id", ids)
        self.assertIn("origin_collapsed", ids)
        self.assertIn("cache_30min", ids)
        self.assertIn("jsonbin_unchecked", ids)
        self.assertIn("schema_gaps", ids)

    def test_schema_gaps_include_rank_origin_calculation_id(self):
        missing = set(self.facts["missing_from_save"])
        for field in ("calculation_id", "origin", "selector_version", "rank"):
            self.assertIn(field, missing)

    def test_registry_module_has_model_version_not_origin(self):
        reg = inspect_registry_module()
        self.assertTrue(reg["model_version_current"])
        self.assertTrue(reg["new_prediction_metadata"])
        self.assertFalse(reg["has_calculation_id"])
        self.assertFalse(reg["has_selector_version"])


class TestReadOnlyWorkflow(unittest.TestCase):
    def test_github_action_is_read_only(self):
        path = os.path.join(_REPO_ROOT, ".github", "workflows", "topmix_audit.yml")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("contents: read", src)
        self.assertNotIn("contents: write", src)
        self.assertIn("upload-artifact", src)
        self.assertIn("--fetch-api", src)
        # GET JSONBin consentita; PUT / --apply / --push-remote vietati.
        self.assertNotIn("--apply", src)
        self.assertNotIn("--push-remote", src)
        self.assertNotIn("requests.put", src)
        self.assertNotIn("method: PUT", src)
        self.assertIn("--jsonbin-get", src)


class TestSourceDoesNotWriteRemoteOnImport(unittest.TestCase):
    def test_no_jsonbin_call_at_module_level(self):
        """Il modulo app.py non chiama JSONBin all'import: solo dentro funzioni."""
        with open(APP_PATH, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        # Chiamate requests.get/put a livello modulo (non dentro FunctionDef).
        func_nodes = {id(n) for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

        def _inside_function(node):
            # heuristica: walk parents non disponibile; controlliamo che ogni
            # Call requests.* stia dentro una FunctionDef visitando le funzioni.
            return True

        calls_in_functions = set()
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in ("get", "put", "post", "patch"):
                        calls_in_functions.add(id(node))
        module_level_jsonbin = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in ("get", "put", "post", "patch"):
                continue
            func = node.func
            if isinstance(func.value, ast.Name) and func.value.id == "requests":
                dumped = ast.unparse(node)
                if "jsonbin" in dumped.lower() and id(node) not in calls_in_functions:
                    module_level_jsonbin.append(dumped[:80])
        self.assertEqual(module_level_jsonbin, [])


if __name__ == "__main__":
    unittest.main()
