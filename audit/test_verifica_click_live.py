"""Test della verifica "il replay rifa' i click veri?".

Tenere fermi questi punti, sono quelli che decidono se la verifica dice la verita':

1. l'istante del salvataggio si legge da ``salvato_il``, in ORA ITALIANA (il campo
   lo scrive l'app con ``ITALY_TZ``): leggerlo come UTC sposterebbe il click di due
   ore e cambierebbe lo snapshot scelto;
2. il motore "di allora" si decide dal SALVATAGGIO e non dalla partita: una riga
   salvata prima del merge di PR#24 (18/09/2026) e' un'uscita del motore legacy,
   anche se la partita si gioca dopo;
3. il campione contiene SOLO righe della versione del selettore in prova: 0 righe
   della versione in prova = "verifica rimandata, 0 righe v2", exit 0; righe
   presenti e nessuna coincide = fallimento; le altre versioni sono contate come
   NON VERIFICABILI.
"""
from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SOCCER = os.path.join(os.path.dirname(HERE), "SoccerMath")
for p in (SOCCER, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import verifica_click_live as v  # noqa: E402
import registry_coverage_check as check  # noqa: E402
import replay_legacy_topmix as replay  # noqa: E402
from prediction_registry import (  # noqa: E402
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_LEGACY,
    SELECTOR_VERSION_CURRENT,
)

VERSIONE_PRE_1X2 = "topmix_gate025_ens06_v1"


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
    def test_salvata_prima_del_merge_su_partita_dopo_e_legacy(self):
        # Caso reale (Milan-Lecce): salvata il 15/09, partita il 20/09. Il motore che
        # l'ha prodotta e' il vecchio (legacy), non l'Attuale.
        riga = {"match_id": 1, "salvato_il": "15/09/2026 17:18", "kickoff_utc": "2026-09-20T18:45:00Z"}
        self.assertEqual(MODEL_VARIANT_LEGACY, v.variante_da_confrontare(riga))

    def test_salvata_dopo_il_merge_senza_campo_e_current(self):
        riga = {"match_id": 2, "salvato_il": "19/09/2026 10:00", "kickoff_utc": "2026-09-20T18:45:00Z"}
        self.assertEqual(MODEL_VARIANT_CURRENT, v.variante_da_confrontare(riga))

    def test_campo_esplicito_vince_sulla_data(self):
        riga = {"match_id": 3, "salvato_il": "15/09/2026 17:18", "model_variant": MODEL_VARIANT_CURRENT}
        self.assertEqual(MODEL_VARIANT_CURRENT, v.variante_da_confrontare(riga))

    def test_senza_salvato_il_ripiega_sul_kickoff(self):
        self.assertEqual(MODEL_VARIANT_LEGACY,
                         v.variante_da_confrontare({"match_id": 4, "kickoff_utc": "2026-09-10T18:00:00Z"}))
        self.assertEqual(MODEL_VARIANT_CURRENT,
                         v.variante_da_confrontare({"match_id": 5, "kickoff_utc": "2026-09-19T18:00:00Z"}))

    def test_ordine_cronologico_non_lessicografico(self):
        righe = [{"salvato_il": "10/09/2026 20:00"}, {"salvato_il": "09/10/2026 08:00"}]
        ordinate = sorted(righe, key=v._chiave_cronologica)
        self.assertEqual("10/09/2026 20:00", ordinate[0]["salvato_il"])


class _EsecuzioneFinta:
    """Registro finto + ricostruzione finta: nessun dato reale, nessuna rete."""

    def __init__(self, righe, *, rows_ricostruite=None, fixtures_chiamate=None):
        self.righe = righe
        self.rows_ricostruite = rows_ricostruite or {}
        self.click_chiamati = []
        self.fixtures_chiamate = fixtures_chiamate if fixtures_chiamate is not None else []

    def _registro(self):
        return list(self.righe), "finto"

    def _click(self, istante, fixtures, targets, leagues, snapshot_cache=None):
        self.click_chiamati.append(str(targets[0].match_id))
        return types.SimpleNamespace(rows=self.rows_ricostruite, snapshot_sha="abc123")

    def _fixtures(self, leghe):
        self.fixtures_chiamate.append(list(leghe))
        return {"Serie A": [types.SimpleNamespace(match_id=7, home="Milan", away="Lecce")]}

    def esegui(self, *args):
        from unittest import mock
        out = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        out.close()
        with mock.patch.object(check, "load_registry_readonly", self._registro), \
                mock.patch.object(replay, "simulate_click", self._click), \
                mock.patch.object(replay, "fixtures_from_csv_and_archive", self._fixtures):
            try:
                rc = v.main(["--from", "2026-08-30", "--to", "2026-12-31", "--fixtures", "csv",
                             "--out", out.name] + list(args))
            finally:
                testo = open(out.name, encoding="utf-8").read()
                os.unlink(out.name)
        return rc, testo


def _riga(match_id, versione, mercato, prob, salvato_il="15/09/2026 17:18", kickoff="2026-09-20T18:45:00Z"):
    return {"match_id": match_id, "home": "Milan", "away": "Lecce", "campionato": "Serie A",
            "origin": "top_mix", "kickoff_utc": kickoff, "salvato_il": salvato_il,
            "mercato_standard": mercato, "prob_sicuro": prob, "esito": "⏳",
            "selector_version": versione}


class TestEsitoVerifica(unittest.TestCase):
    def test_zero_righe_v2_rimandata_senza_fallire_e_senza_fixture(self):
        """Solo righe v1: nessun campione, nessuna fixture scaricata, exit 0, esito dichiarato."""
        righe = [_riga(1, VERSIONE_PRE_1X2, "1", 64.5), _riga(2, VERSIONE_PRE_1X2, "2", 61.0)]
        fx = []
        rc, testo = _EsecuzioneFinta(righe, fixtures_chiamate=fx).esegui()
        self.assertEqual(0, rc)
        self.assertEqual([], fx, "con zero righe v2 non si deve chiedere nessuna fixture")
        self.assertIn("[verifica] esito: verifica rimandata, 0 righe v2", testo)
        self.assertIn("NON VERIFICABILI", testo)
        self.assertIn(f"`{VERSIONE_PRE_1X2}`: 2 righe", testo)

    def test_zero_righe_nel_periodo_rimandata(self):
        rc, testo = _EsecuzioneFinta([]).esegui()
        self.assertEqual(0, rc)
        self.assertIn("verifica rimandata, 0 righe v2", testo)

    def test_righe_v2_coincidenti_ok(self):
        riga = _riga(7, SELECTOR_VERSION_CURRENT, "1", 64.5)
        ricostruite = {MODEL_VARIANT_LEGACY: [{"match_id": 7, "mercato_standard": "1", "prob_val": 64.5}],
                       MODEL_VARIANT_CURRENT: []}
        rc, testo = _EsecuzioneFinta([riga], rows_ricostruite=ricostruite).esegui()
        self.assertEqual(0, rc)
        self.assertIn("[verifica] esito: ok (1/1 righe v2 coincidono)", testo)

    def test_righe_v2_non_coincidenti_fallisce(self):
        riga = _riga(7, SELECTOR_VERSION_CURRENT, "1", 64.5)
        ricostruite = {MODEL_VARIANT_LEGACY: [{"match_id": 7, "mercato_standard": "1", "prob_val": 71.6}],
                       MODEL_VARIANT_CURRENT: []}
        rc, testo = _EsecuzioneFinta([riga], rows_ricostruite=ricostruite).esegui()
        self.assertEqual(1, rc)
        self.assertIn("[verifica] esito: fallita", testo)
        self.assertIn("| match_id |", testo)
        self.assertIn("| 7 | Milan - Lecce", testo)
        self.assertIn("mercato_standard", testo)
        self.assertIn("prob_sicuro", testo)
        self.assertIn("prob_val", testo)
        self.assertIn("1 / 64.5%", testo)
        self.assertIn("1 / 71.6%", testo)

    def test_il_campione_contiene_solo_la_versione_in_prova(self):
        """La riga v1, anche se e' la piu' vecchia, non entra nel campione."""
        vecchia_v1 = _riga(5, VERSIONE_PRE_1X2, "1", 64.5, salvato_il="01/09/2026 10:00")
        nuova_v2 = _riga(7, SELECTOR_VERSION_CURRENT, "1", 64.5, salvato_il="20/10/2026 10:00")
        # salvata dopo il merge di PR#24 e senza campo variante: il motore e' l'Attuale
        ricostruite = {MODEL_VARIANT_CURRENT: [{"match_id": 7, "mercato_standard": "1", "prob_val": 64.5}],
                       MODEL_VARIANT_LEGACY: []}
        esecuzione = _EsecuzioneFinta([vecchia_v1, nuova_v2], rows_ricostruite=ricostruite)
        rc, testo = esecuzione.esegui()
        self.assertEqual(["7"], esecuzione.click_chiamati)
        self.assertEqual(0, rc)
        self.assertIn(f"`{VERSIONE_PRE_1X2}`: 1 righe", testo)


if __name__ == "__main__":
    unittest.main()
