"""Test del tracciamento diagnostico additivo nel Registro.

Copre:
- nuovi campi persistiti da ``save_prediction_entry`` senza rompere quelli legacy;
- ``calculation_id`` condiviso nello stesso run e diverso tra run distinti;
- ``data_snapshot_sha`` letto da git tramite comando mockato (mai reale nei test).
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(__file__))

import app  # noqa: E402
from app import analisi_rapida_giornata, persist_top_mix_predictions, save_prediction_entry  # noqa: E402
from prediction_registry import build_registry_datetime_column, model_label, stats_all  # noqa: E402


FAKE_SHA = "1234567890abcdef1234567890abcdef12345678"


def _git_ok(sha=FAKE_SHA):
    return Mock(returncode=0, stdout=f"{sha}\n", stderr="")


class TestDiagnosticSaveFields(unittest.TestCase):
    @patch("app.subprocess.run", return_value=_git_ok())
    @patch("app.save_predictions")
    @patch("app.load_predictions", return_value=[])
    def test_save_prediction_entry_persists_new_fields_in_coda(self, _load, save, _git):
        save_prediction_entry(
            999101,
            "Napoli",
            "Monza",
            "Serie A",
            5,
            "06/09/2026 20:45",
            "Vittoria Napoli - Top Mix",
            [],
            75.9,
            "",
            mercato_standard="1",
            calculation_id="calc-top-001",
            origin="top_mix",
            selector_version="A",
            poisson=76.8,
            elo=74.6,
            position=1,
        )
        save.assert_called_once()
        entry = save.call_args[0][0][0]

        # Contratto storico invariato
        self.assertEqual(entry["pronostico_sicuro"], "Vittoria Napoli - Top Mix")
        self.assertEqual(entry["mercato_standard"], "1")
        self.assertEqual(entry["tipo"], "Top Mix")

        # Nuovi campi diagnostici
        self.assertEqual(entry["calculation_id"], "calc-top-001")
        self.assertEqual(entry["origin"], "top_mix")
        self.assertEqual(entry["selector_version"], "A")
        self.assertEqual(entry["poisson"], 76.8)
        self.assertEqual(entry["elo"], 74.6)
        self.assertEqual(entry["position"], 1)
        self.assertEqual(entry["data_snapshot_sha"], FAKE_SHA)

    @patch("app.save_predictions")
    @patch("app.load_predictions", return_value=[])
    @patch.object(app.requests, "get")
    def test_legacy_records_without_new_fields_remain_readable(self, fake_get, _load, save):
        legacy = {
            "match_id": 777001,
            "home": "Casa",
            "away": "Ospite",
            "campionato": "Serie A",
            "giornata": 0,
            "data": "05/09/2026 18:00",
            "pronostico_sicuro": "Over 2.5 - Top Mix",
            "mercato_standard": "OVER_2.5",
            "top3": [],
            "prob_sicuro": 61.0,
            "risultati_attesi": "",
            "risultato_reale": None,
            "esito": "⏳",
            "tipo": "Top Mix",
            "stagione": "2026/2027",
            "salvato_il": "05/09/2026 12:00",
        }
        fake_get.return_value = Mock(
            status_code=200,
            json=lambda: {"score": {"fullTime": {"home": 2, "away": 1}}},
        )

        with patch("app.load_predictions", return_value=[legacy]):
            aggiornate, pending = app.aggiorna_risultati_reali("fake-key")

        self.assertEqual((aggiornate, pending), (1, 1))
        self.assertEqual(legacy["risultato_reale"], "2-1")
        self.assertEqual(legacy["esito"], "✅")
        save.assert_called_once()

        # Anche le funzioni di lettura pure continuano a tollerare i record vecchi.
        self.assertEqual(model_label(legacy), "Legacy")
        self.assertEqual(int(stats_all([legacy])["total"]), 1)
        dt_col = build_registry_datetime_column([legacy["data"]])
        self.assertEqual(dt_col.dt.strftime("%d/%m/%Y %H:%M").iloc[0], legacy["data"])


class TestCalculationIdRuns(unittest.TestCase):
    @patch("app.subprocess.run", return_value=_git_ok())
    @patch("app.save_prediction_entry")
    def test_top_mix_shares_calculation_id_within_run_and_changes_across_runs(self, save_entry, _git):
        top_predictions = [
            {
                "match_id": 2001,
                "home": "Napoli",
                "away": "Monza",
                "league": "Serie A",
                "giornata": 5,
                "utcDate": "2026-09-06T18:45:00Z",
                "market": "Vittoria Napoli",
                "mercato_standard": "1",
                "prob_val": 75.9,
                "poisson": 76.8,
                "elo": 74.6,
            },
            {
                "match_id": 2002,
                "home": "Inter",
                "away": "Torino",
                "league": "Serie A",
                "giornata": 5,
                "utcDate": "2026-09-06T20:45:00Z",
                "market": "Vittoria Inter",
                "mercato_standard": "1",
                "prob_val": 71.2,
                "poisson": 72.0,
                "elo": 70.1,
            },
        ]

        saved = persist_top_mix_predictions(top_predictions)
        self.assertEqual(saved, 2)
        self.assertEqual(save_entry.call_count, 2)
        run_one_ids = [call.kwargs["calculation_id"] for call in save_entry.call_args_list]
        run_one_positions = [call.kwargs["position"] for call in save_entry.call_args_list]
        run_one_origins = [call.kwargs["origin"] for call in save_entry.call_args_list]
        run_one_shas = [call.kwargs["data_snapshot_sha"] for call in save_entry.call_args_list]

        self.assertEqual(len(set(run_one_ids)), 1)
        self.assertEqual(run_one_positions, [1, 2])
        self.assertEqual(run_one_origins, ["top_mix", "top_mix"])
        self.assertEqual(run_one_shas, [FAKE_SHA, FAKE_SHA])

        save_entry.reset_mock()
        persist_top_mix_predictions(top_predictions)
        run_two_ids = [call.kwargs["calculation_id"] for call in save_entry.call_args_list]
        self.assertEqual(len(set(run_two_ids)), 1)
        self.assertNotEqual(run_one_ids[0], run_two_ids[0])

    @patch("app.subprocess.run", return_value=_git_ok())
    @patch("app.save_prediction_entry")
    @patch("app.get_full_poisson_two_heads", return_value={"1": 0.62, "X": 0.20, "2": 0.18, "u25": 0.41, "gg": 0.57})
    def test_analisi_rapida_uses_one_calculation_id_per_click(self, _poisson, save_entry, _git):
        matches = [
            {
                "id": 3001,
                "matchday": 5,
                "utcDate": "2026-09-06T18:45:00Z",
                "homeTeam": {"shortName": "Napoli", "name": "Napoli"},
                "awayTeam": {"shortName": "Monza", "name": "Monza"},
            },
            {
                "id": 3002,
                "matchday": 5,
                "utcDate": "2026-09-06T20:45:00Z",
                "homeTeam": {"shortName": "Inter", "name": "Inter"},
                "awayTeam": {"shortName": "Torino", "name": "Torino"},
            },
        ]
        team_stats = {
            "Napoli": {"att": 1.0, "def": 1.0},
            "Monza": {"att": 1.0, "def": 1.0},
            "Inter": {"att": 1.0, "def": 1.0},
            "Torino": {"att": 1.0, "def": 1.0},
        }

        saved = analisi_rapida_giornata(matches, team_stats, 1.4, 1.1, "Serie A", {}, 5)
        self.assertEqual(saved, 2)
        self.assertEqual(save_entry.call_count, 2)
        calc_ids = [call.kwargs["calculation_id"] for call in save_entry.call_args_list]
        origins = [call.kwargs["origin"] for call in save_entry.call_args_list]
        positions = [call.kwargs["position"] for call in save_entry.call_args_list]

        self.assertEqual(len(set(calc_ids)), 1)
        self.assertEqual(origins, ["analisi_rapida", "analisi_rapida"])
        self.assertEqual(positions, [None, None])


if __name__ == "__main__":
    unittest.main(verbosity=2)
