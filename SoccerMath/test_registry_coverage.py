"""Copertura per modello nel Registro: conteggi, differenze e referto.

Prova la misura richiesta dalla commessa ("per ogni partita del periodo il
Registro deve avere ENTRAMBI i modelli: stesso campione, stessa lunghezza"):
una riga per modello=1 partita coperta, due modelli sulla stessa partita=1
partita con entrambi, e le partite coperte da un solo modello devono comparire
con il loro mercato (non sparire in un totale).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import registry_coverage_check as check  # noqa: E402
from registry_coverage import (  # noqa: E402
    coverage_by_variant,
    match_key,
    render_coverage,
    row_day,
    top_mix_rows,
)
from prediction_registry import (  # noqa: E402
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_FIELD,
    MODEL_VARIANT_LEGACY,
    ORIGIN_TOP_MIX,
)


def _riga(mid, home, away, variante, giorno="19/09/2026 18:00", kickoff="2026-09-19T16:00:00Z",
          mercato="1", prob=61.0, campionato="Serie A", esito="✅", origin=ORIGIN_TOP_MIX):
    return {"match_id": mid, "home": home, "away": away, "campionato": campionato,
            "data": giorno, "kickoff_utc": kickoff, "mercato_standard": mercato,
            "prob_sicuro": prob, "esito": esito, "origin": origin,
            MODEL_VARIANT_FIELD: variante}


class TestCopertura(unittest.TestCase):
    def test_stesso_campione_e_differenze_esplicite(self):
        righe = [
            _riga(1, "Inter", "Roma", MODEL_VARIANT_CURRENT),
            _riga(1, "Inter", "Roma", MODEL_VARIANT_LEGACY, mercato="GG", prob=58.0),
            _riga(2, "Milan", "Lazio", MODEL_VARIANT_CURRENT, mercato="2", prob=64.0),
            _riga(3, "Napoli", "Torino", MODEL_VARIANT_LEGACY, mercato="UNDER_2.5", prob=60.5),
            # righe di ALTRE origini e con variante mancante (storica = attuale)
            _riga(9, "X", "Y", MODEL_VARIANT_CURRENT, origin="analisi_rapida"),
            {"match_id": 10, "home": "A", "away": "B", "campionato": "Serie A",
             "data": "19/09/2026 15:00", "mercato_standard": "1", "origin": ORIGIN_TOP_MIX, "esito": "⏳"},
        ]
        cov = coverage_by_variant(righe)
        self.assertEqual(3, cov["partite"][MODEL_VARIANT_CURRENT])   # 1, 2, 10
        self.assertEqual(2, cov["partite"][MODEL_VARIANT_LEGACY])    # 1, 3
        self.assertEqual(1, cov["comuni"])
        self.assertEqual(3, cov["righe_totali"][MODEL_VARIANT_CURRENT])   # 1, 2 e la riga senza campo variante
        self.assertEqual(2, cov["righe_totali"][MODEL_VARIANT_LEGACY])
        self.assertFalse(cov["pareggio"])
        solo_c = {r["partita"] for r in cov["solo"][MODEL_VARIANT_CURRENT]}
        solo_l = {r["partita"] for r in cov["solo"][MODEL_VARIANT_LEGACY]}
        self.assertEqual({"Milan - Lazio", "A - B"}, solo_c)
        self.assertEqual({"Napoli - Torino"}, solo_l)
        self.assertEqual({"UNDER_2.5"}, {r["mercato"] for r in cov["solo"][MODEL_VARIANT_LEGACY]})
        testo = render_coverage(cov)
        self.assertIn("NON coincidono", testo)
        self.assertIn("Napoli - Torino", testo)

    def test_campioni_identici(self):
        righe = []
        for i, (h, a) in enumerate([("Inter", "Roma"), ("Milan", "Lazio")], start=1):
            righe.append(_riga(i, h, a, MODEL_VARIANT_CURRENT, mercato="GG"))
            righe.append(_riga(i, h, a, MODEL_VARIANT_LEGACY, mercato="1"))
        cov = coverage_by_variant(righe)
        self.assertTrue(cov["pareggio"])
        self.assertEqual(2, cov["partite"][MODEL_VARIANT_CURRENT])
        self.assertEqual(2, cov["partite"][MODEL_VARIANT_LEGACY])
        self.assertIn("COINCIDONO", render_coverage(cov))

    def test_filtro_periodo_usa_il_kickoff(self):
        righe = [
            _riga(1, "Inter", "Roma", MODEL_VARIANT_CURRENT, kickoff="2026-08-29T18:00:00Z"),
            _riga(2, "Milan", "Lazio", MODEL_VARIANT_CURRENT, kickoff="2026-09-19T16:00:00Z"),
        ]
        self.assertEqual(1, len(top_mix_rows(righe, date(2026, 9, 1), None)))
        self.assertEqual(1, len(top_mix_rows(righe, None, date(2026, 8, 31))))
        self.assertEqual(2, len(top_mix_rows(righe)))
        self.assertEqual(date(2026, 8, 29), row_day(righe[0]))

    def test_chiave_partita_senza_match_id(self):
        a = {"home": "Inter", "away": "Roma", "kickoff_utc": "2026-09-19T16:00:00Z"}
        b = dict(a)
        self.assertEqual(match_key(a), match_key(b))
        self.assertNotEqual(match_key(a), match_key({**b, "away": "Lazio"}))
        self.assertEqual(("id", "42"), match_key({"match_id": 42}))
        # match_id 0/None non identifica nulla: si ricade sui nomi
        self.assertEqual(match_key(a)["0"] if False else match_key(a)[0], "nomi")

    def test_check_readonly_non_scrive(self):
        """Il controllo deve solo leggere: nessun PUT, nessun file toccato."""
        src = open(os.path.join(HERE, "registry_coverage_check.py"), encoding="utf-8").read()
        self.assertNotIn("requests.put", src)
        self.assertNotIn("save_predictions", src)
        self.assertNotIn("open(PREDICTIONS_FILE, \"w\"", src)
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "cov.json")
            rc = check.main(["--from", "2026-09-01", "--to", "2026-09-20", "--json", out,
                             "--allow-mismatch"])
            self.assertIn(rc, (0, 1))
            self.assertTrue(os.path.exists(out))
            dati = json.load(open(out, encoding="utf-8"))
            self.assertIn("partite", dati)
            self.assertIn("fonte", dati)


if __name__ == "__main__":
    unittest.main()


class TestRegistroDaFile(unittest.TestCase):
    """La misura su file serve a verificare i dati ricostruiti quando il
    Registro live non e' raggiungibile: deve leggere sia una lista sia
    {"data": [...]} e dichiarare la fonte, senza toccare nulla."""

    def _file(self, contenuto):
        import json
        import tempfile
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(contenuto, f)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_legge_la_forma_del_registro(self):
        from registry_coverage_check import load_registry_file
        righe, fonte = load_registry_file(self._file({"data": [{"match_id": 1}]}))
        self.assertEqual([{"match_id": 1}], righe)
        self.assertTrue(fonte.startswith("file "))

    def test_legge_anche_una_lista_nuda(self):
        from registry_coverage_check import load_registry_file
        righe, _ = load_registry_file(self._file([{"match_id": 1}, {"match_id": 2}]))
        self.assertEqual(2, len(righe))

    def test_forma_sbagliata_ferma_tutto(self):
        from registry_coverage_check import load_registry_file
        with self.assertRaises(SystemExit):
            load_registry_file(self._file({"record": {"data": []}}))
