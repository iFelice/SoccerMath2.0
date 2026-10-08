"""Test della regola di rientro dei Totali (audit/topmix_ombra_rientro.py).

La regola e' fissata a priori: questi test verificano che le costanti non scivolino, che
il campione sia quello giusto, che i due criteri (a) e (b) funzionino nei casi di confine,
e che una sorgente irraggiungibile venga riportata come NON VERIFICABILE, mai come zero.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(HERE), str(ROOT / "SoccerMath")):
    if p not in sys.path:
        sys.path.insert(0, p)

import topmix_ombra_rientro as RI  # noqa: E402


def _riga(i, esito="✅", conf=0.66, mkt="OVER_2.5", stagione="2026/2027", lega="Serie A",
          giornata=None, ammessa=True, ombra=True, origin="top_mix_ombra"):
    return {"match_id": 1000 + i, "campionato": lega, "giornata": giornata if giornata is not None else i // 10,
            "stagione": stagione, "mercato_standard": mkt, "ombra_confidence": conf,
            "ombra_ammessa": ammessa, "ombra": ombra, "origin": origin, "esito": esito}


def _campione(n, hit, conf, base_mkt="OVER_2.5", **kw):
    """n scelte giudicate con hit rate ~``hit`` e confidenza ``conf``.

    Gli esiti sono distribuiti in modo uniforme fra le giornate (permutazione
    deterministica), cosi' il bootstrap a blocchi non e' dominato da un'unica giornata.
    """
    soglia = hit * 1000
    return [_riga(i, esito="\u2705" if (i * 7919) % 1000 < soglia else "\u274c",
                  conf=conf, mkt=base_mkt, **kw) for i in range(n)]


class TestCostanti(unittest.TestCase):

    def test_costanti_fissate_a_priori(self):
        self.assertEqual(("OVER_2.5", "UNDER_2.5"), RI.RIENTRO_MERCATI_OU)
        self.assertEqual(300, RI.RIENTRO_N_MIN)
        self.assertEqual(2026, RI.RIENTRO_STAGIONE_MIN_ANNO)
        self.assertAlmostEqual(-0.02, RI.RIENTRO_MARGINE_CALIBRAZIONE)
        self.assertAlmostEqual(0.05, RI.RIENTRO_MARGINE_BASE_RATE)
        self.assertEqual(0.95, RI.RIENTRO_LIVELLO_IC)
        self.assertEqual("fuori_definitivamente", RI.RIENTRO_GG_NG)

    def test_gg_ng_non_possono_rientrare(self):
        self.assertNotIn("GG", RI.RIENTRO_MERCATI_OU)
        self.assertNotIn("NG", RI.RIENTRO_MERCATI_OU)


class TestCampione(unittest.TestCase):

    def test_gg_ng_visibili_e_altre_origini_escluse(self):
        righe = [_riga(1), _riga(2, mkt="GG"), _riga(3, mkt="NG"),
                 _riga(4, ombra=False), _riga(5, origin="top_mix"), _riga(6, origin="analisi_rapida")]
        c = RI.scelte_ou_ammesse(righe)
        self.assertEqual([1001], [r["match_id"] for r in c["righe"]])
        self.assertEqual(2, c["conteggi"]["non_ou"])        # GG e NG: mai nel campione di rientro
        self.assertEqual(3, c["conteggi"]["non_ombra"])     # visibile, origine top_mix, origine AR

    def test_scelte_non_ammesse_escluse(self):
        c = RI.scelte_ou_ammesse([_riga(1, ammessa=False), _riga(2)])
        self.assertEqual([1002], [r["match_id"] for r in c["righe"]])

    def test_stagioni_precedenti_fuori_dal_campione(self):
        c = RI.scelte_ou_ammesse([_riga(1, stagione="2025/2026"), _riga(2, stagione="2026/2027"),
                                  _riga(3, stagione="stagione-sconosciuta")])
        self.assertEqual([1002], [r["match_id"] for r in c["righe"]])
        self.assertEqual(1, c["conteggi"]["dentro_campione_precedente"])
        self.assertEqual(1, c["conteggi"]["senza_stagione"])


class TestDecisione(unittest.TestCase):
    """Base rate reale del riferimento simulato a 0,50 (Over) per isolare i due criteri."""

    BASE = {"Serie A": {"n": 1000, "over": 500, "rate": 0.50}}

    def _valuta(self, righe):
        return RI.valuta(righe, self.BASE)

    def test_sotto_300_non_rientra_anche_con_stime_ottime(self):
        v = self._valuta(_campione(299, hit=0.80, conf=0.60))
        self.assertFalse(v["N_sufficiente"])
        self.assertTrue(RI.decisione(v).startswith("NON RIENTRA: N insufficiente"))

    def test_rientro_ammesso_con_stime_buone(self):
        v = self._valuta(_campione(400, hit=0.70, conf=0.66))
        self.assertTrue(v["N_sufficiente"])
        self.assertTrue(v["criterio_a_ok"], v)
        self.assertTrue(v["criterio_b_ok"], v)
        self.assertEqual("RIENTRO AMMESSO (solo O/U 2.5; GG/NG restano fuori)", RI.decisione(v))

    def test_criterio_a_fallisce_se_la_confidenza_e_sovrastimata(self):
        v = self._valuta(_campione(400, hit=0.60, conf=0.80))   # a = -20 pp
        self.assertFalse(v["criterio_a_ok"])
        self.assertTrue(v["criterio_b_ok"])
        self.assertIn("(a)", RI.decisione(v))

    def test_criterio_b_fallisce_senza_valore_sul_base_rate(self):
        v = self._valuta(_campione(400, hit=0.52, conf=0.51))   # b = +2 pp < +5 pp
        self.assertFalse(v["criterio_b_ok"])
        self.assertIn("(b)", RI.decisione(v))
        self.assertNotIn("RIENTRO AMMESSO", RI.decisione(v))

    def test_under_usa_il_complemento_del_base_rate(self):
        """Under 2.5 con base 0,50 -> base 0,50; un hit di 0,56 e' +6 pp: passa (b)."""
        v = self._valuta(_campione(400, hit=0.56, conf=0.56, base_mkt="UNDER_2.5"))
        self.assertAlmostEqual(0.06, v["b_stima"], places=2)
        self.assertTrue(v["criterio_b_ok"])

    def test_bootstrap_deterministico_e_ic_che_contiene_la_stima(self):
        righe = _campione(400, hit=0.70, conf=0.66)
        b1 = RI.bootstrap(righe, self.BASE)
        b2 = RI.bootstrap(righe, self.BASE)
        self.assertEqual(b1, b2)
        lo, hi = b1["a_ic"]
        self.assertTrue(lo <= 0.70 - 0.66 <= hi, (lo, hi))

    def test_nessuna_scelta_giudicata_non_crea_stime(self):
        v = self._valuta([_riga(1, esito="⏳")])
        self.assertEqual(0, v["giudicate_N"])
        self.assertEqual(1, v["in_attesa"])
        self.assertIsNone(v.get("a_stima"))


class TestBaseRate(unittest.TestCase):

    def _csv(self, dirp, nome, righe):
        with open(Path(dirp) / nome, "w", encoding="latin-1", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"])
            for fthg, ftag in righe:
                w.writerow(["I1", "01/01/2026", "A", "B", fthg, ftag, "H"])

    def test_solo_stagioni_di_riferimento_mai_la_stagione_in_corso(self):
        with tempfile.TemporaryDirectory() as d:
            self._csv(d, "SerieA_2025.csv", [(3, 0), (1, 0)])          # 1 Over su 2
            self._csv(d, "SerieA_Live.csv", [(5, 5), (4, 4), (3, 1)])  # stagione in corso: escluso
            self._csv(d, "SerieA_2026.csv", [(9, 9)])                  # anno fuori riferimento: escluso
            base = RI.base_rate_over25(Path(d))
        self.assertEqual({"n": 2, "over": 1, "rate": 0.5}, base["Serie A"])


class TestSorgente(unittest.TestCase):

    def test_sorgente_non_raggiungibile_e_non_verificabile_e_mai_zero(self):
        with tempfile.TemporaryDirectory() as d:
            out_j, out_m = Path(d) / "r.json", Path(d) / "r.md"
            with mock.patch.object(RI, "carica_registro_ombra", return_value=(None, "upstash non raggiungibile: test")):
                r = RI.esegui("upstash", None, RI.DB_DIR, out_j, out_m)
            self.assertTrue(r["esito"].startswith("NON VERIFICABILE"), r["esito"])
            self.assertIsNone(r["valutazione"])
            self.assertIsNone(r["campione"])
            self.assertEqual("NON VERIFICABILE", json.loads(out_j.read_text(encoding="utf-8"))["stato_lettura"])
            self.assertIn("NON VERIFICABILE", out_m.read_text(encoding="utf-8"))

    def test_file_vuoto_da_n_zero_e_non_rientra(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "vuoto.json"
            f.write_text("[]", encoding="utf-8")
            r = RI.esegui("file", str(f), RI.DB_DIR, Path(d) / "r.json", Path(d) / "r.md")
            self.assertEqual(0, r["valutazione"]["giudicate_N"])
            self.assertTrue(r["esito"].startswith("NON RIENTRA: N insufficiente (0 su 300"), r["esito"])

    def test_markdown_riporta_le_costanti(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "export.json"
            f.write_text(json.dumps(_campione(400, hit=0.70, conf=0.66)), encoding="utf-8")
            r = RI.esegui("file", str(f), RI.DB_DIR, Path(d) / "r.json", Path(d) / "r.md")
            testo = (Path(d) / "r.md").read_text(encoding="utf-8")
        self.assertIn("| N minimo (scelte O/U ammesse giudicate) | 300 |", testo)
        self.assertIn("OVER_2.5, UNDER_2.5", testo)
        self.assertIn(r["esito"], testo)


class TestSolaLettura(unittest.TestCase):

    def test_lo_script_non_scrive_nel_registro(self):
        src = (HERE / "topmix_ombra_rientro.py").read_text(encoding="utf-8")
        for vietato in ("save_rows(", "save_predictions(", "save_ombra_rows(", "HSET", "upstash_save("):
            self.assertNotIn(vietato, src, vietato)


if __name__ == "__main__":
    unittest.main()
