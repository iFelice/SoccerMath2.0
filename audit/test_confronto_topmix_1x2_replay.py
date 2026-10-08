"""Test dello script di confronto PRIMA/DOPO del Top Mix (audit/confronto_topmix_1x2_replay.py).

Dati sintetici con una riga per ogni categoria: il referto deve contarle come previsto.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import confronto_topmix_1x2_replay as C  # noqa: E402


def _r(mid, mk, esito="\u2705", rank=1, prob=60.0, sel="v"):
    return {"match_id": mid, "mercato_standard": mk, "esito": esito, "rank": rank,
            "prob_sicuro": prob, "selector_version": sel, "calculation_id": f"id-{sel}-{mid}",
            "pronostico_sicuro": f"{mk} - Top Mix", "origin": "top_mix", "model_variant": "current"}


MAIN = [
    _r(1, "OVER_2.5", "\u2705", sel="v1"),   # totale: rivalutato su 1X2 nel branch
    _r(2, "1", "\u2705", rank=2, sel="v1"),  # 1X2: identico nel branch (cambia solo il rank)
    _r(3, "UNDER_2.5", "\u274c", sel="v1"),  # totale: sparito (nessun 1X2 ammesso)
    _r(4, "2", "\u274c", sel="v1"),          # 1X2: diverso nel branch (prob diversa)
    _r(5, "GG", "\u2705", sel="v1"),         # totale: sparito
]
BRANCH = [
    _r(1, "1", "\u274c", rank=1, sel="v2", prob=58.0),       # rivalutata
    _r(2, "1", "\u2705", rank=1, sel="v2"),                  # identica salvo rank e versione
    _r(4, "2", "\u274c", sel="v2", prob=57.0),               # diversa
    _r(6, "X", "\u2705", rank=3, sel="v2", prob=56.0),       # entra nuova
]


class TestConfrontoVariante(unittest.TestCase):

    def setUp(self):
        self.r = C.confronta(MAIN, BRANCH)

    def test_totali_del_main_per_mercato(self):
        self.assertEqual({"OVER_2.5": 1, "UNDER_2.5": 1, "GG": 1}, self.r["totali_main_per_mercato"])

    def test_totali_sparite_e_rivalutate(self):
        self.assertEqual({"UNDER_2.5": 1, "GG": 1}, self.r["totali_sparite_senza_1x2_per_mercato"])
        self.assertEqual({"OVER_2.5": 1}, self.r["totali_rivalutate_su_1x2_per_mercato"])
        self.assertEqual(["3", "5"], self.r["totali_sparite_mid"])   # id come stringa, come nelle chiavi JSON

    def test_partite_che_entrano_con_1x2(self):
        self.assertEqual(1, self.r["entrano_1x2_nuove"])          # mid 6
        self.assertEqual(1, self.r["entrano_1x2_rivalutate"])     # mid 1
        self.assertEqual(2, self.r["entrano_1x2_hit"]["giudicate"])
        self.assertEqual(1, self.r["entrano_1x2_nuove_hit"]["vinte"])
        self.assertEqual(0.0, self.r["entrano_1x2_rivalutate_hit"]["hit_rate"])

    def test_1x2_gia_presenti_identiche_diverse_perse(self):
        self.assertEqual(2, self.r["1x2_gia_presenti"])           # mid 2 e 4
        self.assertEqual(1, self.r["1x2_identiche"])              # mid 2: solo rank e versione cambiano
        self.assertEqual(["4"], self.r["1x2_diverse_mid"])
        self.assertEqual(0, self.r["1x2_perse"])

    def test_nessun_totale_nel_branch_e_nessuna_anomalia(self):
        self.assertEqual(0, self.r["anomalie"]["branch_con_totale"])
        self.assertEqual(0, self.r["anomalie"]["main_1x2_branch_totale"])

    def test_hit_rate_prima_e_dopo(self):
        self.assertEqual(3, self.r["hit_prima"]["vinte"])         # main: mid 1, 2, 5 vinte; 3, 4 perse
        self.assertEqual(5, self.r["hit_prima"]["giudicate"])
        self.assertEqual(2, self.r["hit_dopo"]["vinte"])          # branch: 1 persa, 2 vinta, 4 persa, 6 vinta
        self.assertEqual(4, self.r["hit_dopo"]["giudicate"])

    def test_1x2_persa_se_il_branch_non_lo_ha(self):
        """Un 1X2 gia' presente nel main che nel branch sparisce conta come PERSO (deve essere 0 in produzione)."""
        branch_senza_2 = [b for b in BRANCH if b["match_id"] != 2]
        self.assertEqual(1, C.confronta(MAIN, branch_senza_2)["1x2_perse"])


class TestSommaEReferto(unittest.TestCase):

    def test_esegui_e_referto_su_file_temporanei(self):
        with tempfile.TemporaryDirectory() as d:
            pm, pb = Path(d) / "main.json", Path(d) / "branch.json"
            base = {"ref": "c06818e", "finestra": ["2026-08-30", "2026-10-08"], "clicks": [{}],
                    "leak_ok": True, "entries_legacy": []}
            pm.write_text(json.dumps({**base, "entries_current": MAIN}), encoding="utf-8")
            pb.write_text(json.dumps({**base, "entries_current": BRANCH}), encoding="utf-8")
            C.main(["--main", str(pm), "--branch", str(pb),
                    "--out-json", str(Path(d) / "r.json"), "--out-md", str(Path(d) / "r.md")])
            r = json.loads((Path(d) / "r.json").read_text(encoding="utf-8"))
            md = (Path(d) / "r.md").read_text(encoding="utf-8")
        self.assertEqual(1, r["risultati"]["current"]["entrano_1x2_nuove"])
        self.assertEqual(0, r["risultati"]["legacy"]["entrano_1x2_nuove"])
        self.assertEqual(1, r["risultati"]["totale"]["entrano_1x2_nuove"])
        self.assertIn("| UNDER_2.5 | 1 | 1 | 0 |", md)


if __name__ == "__main__":
    unittest.main()
