"""Test del tracciamento del Registro (origini, dedup, grading, Brier).

Solo stdlib: importa ``prediction_registry`` (che non dipende da Streamlit,
pandas o numpy) e NIENTE che apra rete o scriva il registro reale. Le
scritture usano una directory temporanea.

Copre il lavoro di ``audit/margini_migliorabili_topmix.md`` §7 (problemi
``dedup_match_id``, ``origin_collapsed``, ``schema_gaps``) e §4 punto 6
(grading unificato fra i due rami di ``aggiorna_risultati_reali``).
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import prediction_registry as R  # noqa: E402


def _entry(mid=101, origin=R.ORIGIN_TOP_MIX, version=R.SELECTOR_VERSION_CURRENT,
           esito="⏳", prob=66.0, mercato="1", **extra):
    e = {
        "match_id": mid, "origin": origin, "selector_version": version,
        "esito": esito, "prob_sicuro": prob, "mercato_standard": mercato,
        "pronostico_sicuro": "Vittoria X - Top Mix",
    }
    e.update(extra)
    return e


class TestOrigini(unittest.TestCase):
    def test_origin_dal_testo_e_un_fallback(self):
        self.assertEqual(R.origin_from_text("Over 2.5 - Top Mix"), R.ORIGIN_TOP_MIX)
        self.assertEqual(R.origin_from_text("GG - 61% - Poisson Auto"), R.ORIGIN_ANALISI_RAPIDA)
        self.assertEqual(R.origin_from_text("1 - Fallback"), R.ORIGIN_BILLY)
        self.assertEqual(R.origin_from_text(""), R.ORIGIN_UNKNOWN)

    def test_origin_esplicita_vince_sul_testo(self):
        # Un record Top Mix salvato con origine Analisi Rapida resta Analisi
        # Rapida: e' il chiamante che sa chi ha generato la previsione.
        self.assertEqual(R.resolve_origin(R.ORIGIN_ANALISI_RAPIDA, "Vittoria X - Top Mix"),
                         R.ORIGIN_ANALISI_RAPIDA)
        self.assertEqual(R.resolve_origin(None, "Vittoria X - Top Mix"), R.ORIGIN_TOP_MIX)
        self.assertEqual(R.resolve_origin("sbagliato", "Vittoria X - Top Mix"), R.ORIGIN_UNKNOWN)

    def test_etichetta_tipo(self):
        self.assertEqual(R.tipo_for_origin(R.ORIGIN_TOP_MIX), "Top Mix")
        self.assertEqual(R.tipo_for_origin(R.ORIGIN_BILLY), "Billy")
        self.assertEqual(R.tipo_for_origin(R.ORIGIN_UNKNOWN), "Analisi")
        self.assertEqual(R.tipo_for_origin(None), "Analisi")

    def test_origin_of_record_legacy(self):
        # Record scritti prima del campo origin: si risale dal tipo, poi dal testo.
        self.assertEqual(R.origin_of({"tipo": "Top Mix"}), R.ORIGIN_TOP_MIX)
        self.assertEqual(R.origin_of({"tipo": "Analisi", "pronostico_sicuro": "GG - 61% - Poisson Auto"}),
                         R.ORIGIN_ANALISI_RAPIDA)
        self.assertEqual(R.origin_of({"origin": R.ORIGIN_BILLY}), R.ORIGIN_BILLY)
        self.assertEqual(R.origin_of({}), R.ORIGIN_UNKNOWN)
        self.assertEqual(R.origin_of(None), R.ORIGIN_UNKNOWN)


class TestChiaveDedup(unittest.TestCase):
    def test_match_id_normalizzato(self):
        self.assertEqual(R.dedup_key({"match_id": 921}), R.dedup_key({"match_id": "921"}))

    def test_la_stessa_partita_ha_una_riga_per_origine(self):
        a = R.dedup_key(_entry(origin=R.ORIGIN_TOP_MIX))
        b = R.dedup_key(_entry(origin=R.ORIGIN_ANALISI_RAPIDA))
        self.assertNotEqual(a, b)

    def test_versioni_del_selettore_non_si_schiacciano(self):
        a = R.dedup_key(_entry(version="topmix_gate025_ens06_v1"))
        b = R.dedup_key(_entry(version="topmix_gate025_ens06_v2"))
        self.assertNotEqual(a, b)


class TestUpsert(unittest.TestCase):
    def test_origini_diverse_coesistono(self):
        preds = [_entry(origin=R.ORIGIN_ANALISI_RAPIDA)]
        out, azione = R.upsert_prediction_entry(preds, _entry(origin=R.ORIGIN_TOP_MIX))
        self.assertEqual(azione, "aggiunta")
        self.assertEqual(len(out), 2)

    def test_il_dedup_vecchio_perdeva_il_top_mix(self):
        """Ex novo: con la vecchia chiave (solo match_id) la riga non entrava."""
        preds = [_entry(origin=R.ORIGIN_ANALISI_RAPIDA)]
        stessa_chiave_vecchia = all(p.get("match_id") == 101 for p in preds)
        self.assertTrue(stessa_chiave_vecchia)          # l'old code faceva return
        self.assertEqual(len(R.upsert_prediction_entry(preds, _entry(origin=R.ORIGIN_TOP_MIX))[0]), 2)

    def test_ricalcolo_aggiorna_e_non_duplica(self):
        preds = [_entry(prob=66.0, salvato_il="01/09/2026 10:00")]
        out, azione = R.upsert_prediction_entry(preds, _entry(prob=71.0))
        self.assertEqual(azione, "aggiornata")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["prob_sicuro"], 71.0)
        # la prima scrittura resta leggibile: un ricalcolo non cancella la storia
        self.assertEqual(out[0]["salvato_il_originario"], "01/09/2026 10:00")

    def test_record_giudicato_non_si_tocca_mai(self):
        preds = [_entry(esito="✅", prob=66.0)]
        out, azione = R.upsert_prediction_entry(preds, _entry(prob=99.0))
        self.assertEqual(azione, "gia_graduata")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["prob_sicuro"], 66.0)
        self.assertEqual(out[0]["esito"], "✅")

    def test_lista_input_non_mutata(self):
        preds = [_entry()]
        R.upsert_prediction_entry(preds, _entry(prob=50.0))
        self.assertEqual(len(preds), 1)
        self.assertEqual(preds[0]["prob_sicuro"], 66.0)

    def test_senza_match_id_si_accoda(self):
        out, azione = R.upsert_prediction_entry([], _entry(mid=None))
        self.assertEqual(azione, "senza_chiave")
        self.assertEqual(len(out), 1)

    def test_upsert_vuoto_iniziale(self):
        out, azione = R.upsert_prediction_entry(None, _entry())
        self.assertEqual((len(out), azione), (1, "aggiunta"))


class TestGradingUnico(unittest.TestCase):
    CASI = [
        ("UNDER_1.5", 0, 0, "✅"), ("UNDER_1.5", 1, 1, "❌"),
        # OVER 1.5 perde con UN gol totale: la linea e' " piu' di 1".
        ("OVER_1.5", 1, 0, "❌"), ("OVER_1.5", 1, 1, "✅"), ("OVER_1.5", 0, 0, "❌"),
        ("UNDER_2.5", 1, 1, "✅"), ("UNDER_2.5", 2, 1, "❌"),
        ("OVER_2.5", 2, 1, "✅"), ("OVER_2.5", 1, 1, "❌"),
        ("UNDER_3.5", 2, 1, "✅"), ("UNDER_3.5", 2, 2, "❌"),
        ("OVER_3.5", 2, 2, "✅"), ("OVER_3.5", 2, 1, "❌"),
        ("1X", 1, 0, "✅"), ("1X", 1, 1, "✅"), ("1X", 0, 1, "❌"),
        ("X2", 0, 1, "✅"), ("X2", 1, 1, "✅"), ("X2", 1, 0, "❌"),
        ("12", 1, 0, "✅"), ("12", 0, 0, "❌"),
        ("GG", 1, 1, "✅"), ("GG", 1, 0, "❌"),
        ("NG", 1, 0, "✅"), ("NG", 0, 0, "✅"), ("NG", 1, 1, "❌"),
        ("X", 1, 1, "✅"), ("X", 1, 0, "❌"),
        ("1", 2, 0, "✅"), ("1", 0, 0, "❌"),
        ("2", 0, 2, "✅"), ("2", 1, 1, "❌"),
    ]

    def test_tabella_completa(self):
        for mkt, gh, ga, atteso in self.CASI:
            self.assertEqual(R.esito_mercato(mkt, gh, ga), atteso, (mkt, gh, ga))

    def test_entrambi_i_rami_ora_graduano_gli_stessi_mercati(self):
        """Il vecchio loop per giornata conosceva solo 7 mercati."""
        vecchi_7 = {"UNDER_2.5", "OVER_2.5", "GG", "NG", "X", "1", "2"}
        for mkt in R.MERCATI_GRADABILI:
            self.assertIsNotNone(R.esito_mercato(mkt, 2, 1), mkt)
            if mkt not in vecchi_7:
                self.assertIn(mkt, {"UNDER_1.5", "OVER_1.5", "UNDER_3.5", "OVER_3.5",
                                    "1X", "X2", "12"})

    def test_coperture_e_ambiguita(self):
        self.assertEqual(len(set(m for m, *_ in self.CASI)), len(R.MERCATI_GRADABILI))

    def test_mercato_sconosciuto_o_gol_dati_mali_non_si_graduano(self):
        for mkt in ("ALTRO", "", "GG/NG", None, "OVER_4.5"):
            self.assertIsNone(R.esito_mercato(mkt, 1, 0), mkt)
        for gol in (None, float("nan"), "1", True, -1, 1.5):
            self.assertIsNone(R.esito_mercato("1", gol, 0), ("1", gol))

    def test_float_interi_accettati(self):
        self.assertEqual(R.esito_mercato("1", 2.0, 0), "✅")


class TestIgieneRighe(unittest.TestCase):
    def test_parse_kickoff(self):
        self.assertEqual(R.parse_kickoff("2026-09-06T18:00:00Z").year, 2026)
        self.assertEqual(R.parse_kickoff("2026-09-06T18:00:00+00:00").hour, 18)
        self.assertIsNone(R.parse_kickoff("06/09/2026 18:00"))
        self.assertIsNone(R.parse_kickoff(None))
        # naive -> trattato come UTC (mai confrontare naive con aware)
        self.assertIsNotNone(R.parse_kickoff("2026-09-06T18:00:00").tzinfo)

    def test_scarta_gia_iniziate_e_non_perde_dati_sporchi(self):
        righe = [
            {"id": 1, "utcDate": "2026-09-05T18:00:00Z"},   # passata
            {"id": 2, "utcDate": "2099-01-01T18:00:00Z"},   # futura
            {"id": 3, "utcDate": "non una data"},           # data illeggibile
            {"id": 4},                                      # data assente
            "non un dict",
        ]
        tenute, scartate = R.righe_non_iniziate(righe, ora="2026-09-06T12:00:00Z")
        self.assertEqual(scartate, 1)
        self.assertEqual([r["id"] for r in tenute], [2, 3, 4])

    def test_il_kickoff_esatto_non_e_piu_giocabile(self):
        tenute, scartate = R.righe_non_iniziate(
            [{"utcDate": "2026-09-06T12:00:00Z"}], ora="2026-09-06T12:00:00Z")
        self.assertEqual((len(tenute), scartate), (0, 1))

    def test_svuotare_non_che_cancellare(self):
        tenute, scartate = R.righe_non_iniziate([], ora="2026-09-06T12:00:00Z")
        self.assertEqual((tenute, scartate), ([], 0))


class TestCalibrazioneRegistro(unittest.TestCase):
    def test_prob_percentuale_o_frazione(self):
        self.assertAlmostEqual(R.prob_of_entry({"prob_sicuro": 66.0}), 0.66)
        self.assertAlmostEqual(R.prob_of_entry({"prob_sicuro": 0.66}), 0.66)
        self.assertIsNone(R.prob_of_entry({"prob_sicuro": "66"}))
        self.assertIsNone(R.prob_of_entry({"prob_sicuro": 120.0}))
        self.assertIsNone(R.prob_of_entry({}))

    def test_brier_entry(self):
        self.assertAlmostEqual(R.brier_of_entry({"prob_sicuro": 70.0, "esito": "✅"}), 0.09)
        self.assertAlmostEqual(R.brier_of_entry({"prob_sicuro": 70.0, "esito": "❌"}), 0.49)
        self.assertIsNone(R.brier_of_entry({"prob_sicuro": 70.0, "esito": "⏳"}))

    def test_statistics_aggregate(self):
        entries = [
            {"prob_sicuro": 70.0, "esito": "✅"},
            {"prob_sicuro": 70.0, "esito": "❌"},
            {"prob_sicuro": 65.0, "esito": "⏳"},
        ]
        st = R.compute_calibration_stats(entries)
        self.assertEqual(st["total"], 3)
        self.assertEqual(st["decise"], 2)
        self.assertEqual(st["con_probabilita"], 2)
        self.assertAlmostEqual(st["hit_rate"], 50.0)
        self.assertAlmostEqual(st["prob_media"], 70.0)
        self.assertAlmostEqual(st["gap"], 20.0)
        self.assertAlmostEqual(st["brier"], 0.29)

    def test_senza_probabilita_nessuna_metrica_mista(self):
        """Hit/gap/Brier stanno sulla STESSA popolazione: nessuna delle due viene
        calcolata su un sottoinsieme diverso, nemmeno per errore."""
        st = R.compute_calibration_stats([{"esito": "✅"}, {"esito": "❌"}])
        self.assertEqual((st["decise"], st["con_probabilita"]), (2, 0))
        self.assertIsNone(st["brier"])
        self.assertIsNone(st["hit_rate"])
        self.assertIsNone(st["gap"])

    def test_per_mercato_e_per_origine(self):
        entries = [
            {"prob_sicuro": 70.0, "esito": "✅", "mercato_standard": "1", "origin": R.ORIGIN_TOP_MIX},
            {"prob_sicuro": 70.0, "esito": "❌", "mercato_standard": "1", "origin": R.ORIGIN_TOP_MIX},
            {"prob_sicuro": 70.0, "esito": "✅", "mercato_standard": "1", "origin": R.ORIGIN_ANALISI_RAPIDA},
        ]
        righe = R.calibration_by_mercato(entries, min_decise=1)
        self.assertEqual(len(righe), 2)                    # split per origine
        self.assertEqual(sum(r["decise"] for r in righe), 3)
        per_mercato = R.calibration_by_mercato(entries, min_decise=1, per_origine=False)
        self.assertEqual(len(per_mercato), 1)
        self.assertAlmostEqual(per_mercato[0]["hit_rate"], 200.0 / 3)

    def test_min_decise_filtra_i_tagli_rumore(self):
        entries = [{"prob_sicuro": 70.0, "esito": "✅", "mercato_standard": "NG"}]
        self.assertEqual(R.calibration_by_mercato(entries, min_decise=5), [])
        self.assertEqual(len(R.calibration_by_mercato(entries, min_decise=1)), 1)

    def test_avvertenza_campione_piccolo(self):
        self.assertIn("30 partite", R.overall_reliability_transfer_warning(
            {"brier": 0.2, "con_probabilita": 12}) or "")
        self.assertIsNone(R.overall_reliability_transfer_warning(
            {"brier": 0.2, "con_probabilita": 400}))
        self.assertIsNone(R.overall_reliability_transfer_warning({"brier": None}))


class TestIdentitaCalcolo(unittest.TestCase):
    def test_calculation_id_deterministico(self):
        a = R.build_calculation_id(921, R.ORIGIN_TOP_MIX, "v1", "2026-09-06T18:00:00Z", "abc", 3)
        b = R.build_calculation_id(921, R.ORIGIN_TOP_MIX, "v1", "2026-09-06T18:00:00Z", "abc", 3)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 16)
        for kwargs in ({"rank": 4}, {"snapshot_sha": "zzz"}, {"origin": R.ORIGIN_BILLY}):
            base = dict(match_id=921, origin=R.ORIGIN_TOP_MIX, selector_version="v1",
                        kickoff_utc="2026-09-06T18:00:00Z", snapshot_sha="abc", rank=3)
            base.update(kwargs)
            self.assertNotEqual(R.build_calculation_id(**base), a, kwargs)

    def test_il_registro_non_e_un_input_del_fingerprint(self):
        """`predictions.json` e' l'OUTPUT: includerlo renderebbe il
        ``data_snapshot_sha`` (e quindi il calculation_id) diverso a ogni
        scrittura della stessa previsione."""
        with tempfile.TemporaryDirectory() as td:
            open(os.path.join(td, "a.csv"), "w").write("1\n")
            open(os.path.join(td, "predictions.json"), "w").write('{"data":[]}')
            fp1 = R.snapshot_fingerprint(td)
            with open(os.path.join(td, "predictions.json"), "w") as f:
                json.dump({"data": [{"match_id": i} for i in range(50)]}, f)
            self.assertEqual(R.snapshot_fingerprint(td), fp1)

    def test_fingerprint_stabile_e_reattivo(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(R.snapshot_fingerprint(os.path.join(td, "nope")), "")
            open(os.path.join(td, "a.csv"), "w").write("1,2\n")
            open(os.path.join(td, "b.json"), "w").write("{}\n")
            open(os.path.join(td, "ignored.txt"), "w").write("x\n")
            fp1 = R.snapshot_fingerprint(td)
            self.assertEqual(len(fp1), 12)
            self.assertEqual(R.snapshot_fingerprint(td), fp1)      # deterministico
            open(os.path.join(td, "c.csv"), "w").write("3\n")     # un file in piu'
            self.assertNotEqual(R.snapshot_fingerprint(td), fp1)
            # la sottodirectory NON viene scavata (archivi partita = migliaia di
            # file): il costo deve restare pochi stat()
            os.makedirs(os.path.join(td, "archive"))
            open(os.path.join(td, "archive", "d.csv"), "w").write("4\n")
            self.assertEqual(len(R.snapshot_fingerprint(td)), 12)


class TestVersioneSelettore(unittest.TestCase):
    def test_la_version_e_nel_dedup_key(self):
        """Una cambio di selettore NON deve sovrascrivere le righe vecchie."""
        vecchi = [_entry(version="topmix_gate025_ens06_v1")]
        out, azione = R.upsert_prediction_entry(vecchi, _entry(version="senza_gate"))
        self.assertEqual(azione, "aggiunta")
        self.assertEqual(len(out), 2)

    def test_metadata_corrente_non_regressa(self):
        md = R.new_prediction_metadata()
        self.assertEqual(md[R.MODEL_VERSION_FIELD], R.MODEL_VERSION_CURRENT)
        self.assertFalse(md[R.EXCLUDED_FROM_CURRENT_STATS_FIELD])
        self.assertEqual(R.SELECTOR_VERSION_CURRENT, "topmix_gate025_ens06_v1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
