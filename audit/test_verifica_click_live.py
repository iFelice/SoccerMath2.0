"""Test della verifica "il replay rifa' i click veri?".

Due cose vanno tenute ferme, e sono quelle che decidono se la verifica dice la
verita' o solo numeri plausibili:

1. l'istante del salvataggio si legge da ``salvato_il``, che e' in ORA ITALIANA
   (il campo lo scrive l'app con ``ITALY_TZ``): leggerlo come UTC sposterebbe il
   click di due ore e cambierebbe lo snapshot scelto;
2. quale riga ricostruita si confronta: prima di PR#24 il motore live era il
   VECCHIO, quindi la riga storica (senza campo variante, che per i record
   vecchi vale "current") va confrontata con la ricostruzione LEGACY; dopo
   PR#24 con la variante dichiarata.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SOCCER = os.path.join(os.path.dirname(HERE), "SoccerMath")
for p in (SOCCER, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import verifica_click_live as v  # noqa: E402
from prediction_registry import MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY  # noqa: E402


class TestIstanteDelSalvataggio(unittest.TestCase):
    def setUp(self):
        import app
        v.ITALY = app.ITALY_TZ

    def test_ora_italiana_convertita_in_utc(self):
        # 10/09/2026 20:00 in Italia (CEST, UTC+2) = 18:00 UTC
        self.assertEqual(datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc),
                         v.istante_del_salvataggio({"salvato_il": "10/09/2026 20:00"}))

    def test_ora_solare_convertita_in_utc(self):
        # 10/01/2026 20:00 in Italia (CET, UTC+1) = 19:00 UTC
        self.assertEqual(datetime(2026, 1, 10, 19, 0, tzinfo=timezone.utc),
                         v.istante_del_salvataggio({"salvato_il": "10/01/2026 20:00"}))

    def test_senza_istante_non_si_inventa(self):
        self.assertIsNone(v.istante_del_salvataggio({"salvato_il": ""}))
        self.assertIsNone(v.istante_del_salvataggio({"salvato_il": "non una data"}))


class TestVarianteDaConfrontare(unittest.TestCase):
    def test_riga_prima_di_pr24_confrontata_col_legacy_anche_senza_campo(self):
        riga = {"match_id": 1, "kickoff_utc": "2026-09-10T18:00:00Z"}
        self.assertEqual(MODEL_VARIANT_LEGACY, v.variante_da_confrontare(riga))

    def test_riga_dopo_pr24_confrontata_con_la_sua_variante(self):
        riga = {"match_id": 2, "kickoff_utc": "2026-09-19T18:00:00Z"}
        self.assertEqual(MODEL_VARIANT_CURRENT, v.variante_da_confrontare(riga))
        riga_legacy = dict(riga, model_variant=MODEL_VARIANT_LEGACY)
        self.assertEqual(MODEL_VARIANT_LEGACY, v.variante_da_confrontare(riga_legacy))


class TestEsecuzioneEndToEnd(unittest.TestCase):
    """Un bug vero: il filtro del periodo usava una funzione inesistente e la
    verifica moriva senza stampare nulla, con la CI verde (pipe senza pipefail).
    Qui si esegue ``main`` su un registro finto: il percorso che filtra le righe
    deve restare vivo."""

    def test_main_su_registro_finto_senza_click(self):
        import json
        import tempfile
        from datetime import date
        import registry_coverage_check as check
        import verifica_click_live as v

        righe = [
            {"match_id": 1, "home": "A", "away": "B", "campionato": "Serie A", "origin": "top_mix",
             "kickoff_utc": "2026-09-10T18:00:00Z", "salvato_il": "10/09/2026 20:00",
             "mercato_standard": "1", "prob_sicuro": 60.0, "esito": "⏳"},
        ]
        originale = check.load_registry_readonly
        check.load_registry_readonly = lambda: (righe, "finto")
        out = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        out.close()
        self.addCleanup(os.unlink, out.name)
        try:
            rc = v.main(["--from", "2026-08-30", "--to", "2026-09-20", "--per-variante", "0",
                         "--fixtures", "csv", "--out", out.name])
        finally:
            check.load_registry_readonly = originale
        self.assertEqual(0, rc)
        testo = open(out.name, encoding="utf-8").read()
        self.assertIn("campione verificato: 0", testo)
        self.assertIn("coincidono", testo)

    def test_senza_campione_non_serve_la_sorgente_fixture(self):
        """Con zero righe da verificare non si deve nemmeno provare a scaricare
        le fixture (e senza chiave API non si deve rompere)."""
        import tempfile
        import registry_coverage_check as check
        import verifica_click_live as v

        originale = check.load_registry_readonly
        check.load_registry_readonly = lambda: ([], "vuoto")
        out = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        out.close()
        self.addCleanup(os.unlink, out.name)
        try:
            rc = v.main(["--from", "2026-08-30", "--to", "2026-09-20", "--per-variante", "2",
                         "--fixtures", "api", "--out", out.name])
        finally:
            check.load_registry_readonly = originale
        self.assertEqual(0, rc)
