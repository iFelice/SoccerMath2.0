"""Il GET JSONBin di audit non deve contenere PUT / --apply / --push-remote."""
from __future__ import annotations

import ast
import os
import unittest

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
FETCH_PATH = os.path.join(_AUDIT_DIR, "fetch_jsonbin_match.py")


class TestJsonbinGetIsReadOnly(unittest.TestCase):
    def test_no_put_apply_or_push(self):
        with open(FETCH_PATH, encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        puts = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("put", "post", "patch", "delete"):
                    puts.append(ast.unparse(node)[:80])
        self.assertEqual(puts, [])
        self.assertNotIn('"--apply"', src)
        self.assertNotIn("'--apply'", src)
        self.assertNotIn('"--push-remote"', src)
        self.assertNotIn("'--push-remote'", src)
        self.assertIn("requests.get", src)
        self.assertIn("/latest", src)
