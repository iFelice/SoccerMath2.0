#!/usr/bin/env python3
"""
audit/test_prediction_registry.py

Test autonomi del versionamento del Registro Predizioni & Tracking e della
separazione pre-fix / post-fix (shrinkage/lambda-zero).

Esecuzione:
    python -m unittest audit.test_prediction_registry -v
    python audit/test_prediction_registry.py
    python -m pytest audit/test_prediction_registry.py -v   (se pytest disponibile)

Nessun test tocca predictions.json o JSONBin: usa solo dati in memoria/temp.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SOCCERMATH_DIR = _REPO_ROOT / "SoccerMath"
sys.path.insert(0, str(_SOCCERMATH_DIR))

from prediction_registry import (  # noqa: E402
    MODEL_VERSION_AMBIGUOUS,
    MODEL_VERSION_CURRENT,
    MODEL_VERSION_FIELD,
    MODEL_VERSION_LEGACY,
    MODEL_VERSION_PRE_FIX,
    EXCLUDED_FROM_CURRENT_STATS_FIELD,
    get_model_version,
    is_current_model,
    is_excluded_from_stats,
    load_predictions_file,
    new_prediction_metadata,
    should_tag_pre_fix,
    tag_pre_fix,
    stats_current_model,
    stats_historical,
    season_from_entry,
    classify_entry,
)

PRE_2026 = {
    "match_id": 1,
    "home": "Casa", "away": "Ospite", "campionato": "Serie A", "giornata": 3,
    "data": "29/08/2026 20:45", "pronostico_sicuro": "Under 2.5",
    "mercato_standard": "UNDER_2.5", "top3": [], "prob_sicuro": 59.9,
    "risultati_attesi": "", "risultato_reale": "1-1", "esito": "✅",
    "tipo": "Top Mix", "stagione": "2026/2027", "salvato_il": "26/08/2026 11:00",
}

POST_CURRENT_2026 = {
    "match_id": 2,
    "home": "Casa2", "away": "Ospite2", "campionato": "Serie A", "giornata": 4,
    "data": "05/09/2026 18:00", "pronostico_sicuro": "Over 2.5",
    "mercato_standard": "OVER_2.5", "top3": [], "prob_sicuro": 72.0,
    "risultati_attesi": "", "risultato_reale": "3-1", "esito": "✅",
    "tipo": "Top Mix", "stagione": "2026/2027", "salvato_il": "05/09/2026 12:00",
    MODEL_VERSION_FIELD: MODEL_VERSION_CURRENT,
    EXCLUDED_FROM_CURRENT_STATS_FIELD: False,
}

LEGACY_2025 = {
    "match_id": 3,
    "home": "Vecchia", "away": "Storica", "campionato": "La Liga", "giornata": 38,
    "data": "23/05/2026 21:00", "pronostico_sicuro": "1",
    "mercato_standard": "1", "top3": [], "prob_sicuro": 66.0,
    "risultati_attesi": "", "risultato_reale": "2-0", "esito": "❌",
    "tipo": "Top Mix", "stagione": "2025/2026", "salvato_il": "23/05/2026 08:19",
}

POST_UNVERSIONED_2026 = {
    "match_id": 4,
    "home": "Casa3", "away": "Ospite3", "campionato": "Premier League", "giornata": 5,
    "data": "06/09/2026 15:00", "pronostico_sicuro": "Vittoria Casa3",
    "mercato_standard": "1", "top3": [], "prob_sicuro": 61.5,
    "risultati_attesi": "", "risultato_reale": None, "esito": "⏳",
    "tipo": "Top Mix", "stagione": "2026/2027", "salvato_il": "06/09/2026 09:00",
}

AMBIGUOUS_2026 = {
    "match_id": 5,
    "home": "Amb", "away": "Igua", "campionato": "Bundesliga", "giornata": 4,
    "data": "05/09/2026 18:30", "pronostico_sicuro": "GG",
    "mercato_standard": "GG", "top3": [], "prob_sicuro": 64.0,
    "risultati_attesi": "", "risultato_reale": None, "esito": "⏳",
    "tipo": "Top Mix", "stagione": "2026/2027", "salvato_il": "04/09/2026 18:00",
}


def migrate(records):
    """Equivalente semplificato della migrazione: nessuna cancellazione."""
    return [tag_pre_fix(e) if should_tag_pre_fix(e) else e for e in records]


class TestNoDataLoss(unittest.TestCase):
    def test_no_entry_deleted(self):
        records = [PRE_2026, POST_CURRENT_2026, LEGACY_2025]
        migrated = migrate(records)
        self.assertEqual(len(records), len(migrated))
        self.assertEqual({x["match_id"] for x in records}, {x["match_id"] for x in migrated})

    def test_immutable_fields_remain_identical(self):
        migrated = migrate([PRE_2026])[0]
        for field in ["pronostico_sicuro", "prob_sicuro", "risultato_reale",
                      "esito", "salvato_il", "top3", "mercato_standard",
                      "data", "home", "away", "campionato", "giornata"]:
            self.assertEqual(PRE_2026[field], migrated[field], field)

    def test_tagging_adds_only_metadata(self):
        migrated = migrate([PRE_2026])[0]
        self.assertEqual(migrated[MODEL_VERSION_FIELD], MODEL_VERSION_PRE_FIX)
        self.assertIs(migrated[EXCLUDED_FROM_CURRENT_STATS_FIELD], True)


class TestClassification(unittest.TestCase):
    def test_pre_fix_tagged(self):
        self.assertTrue(should_tag_pre_fix(PRE_2026))

    def test_post_current_not_tagged(self):
        self.assertFalse(should_tag_pre_fix(POST_CURRENT_2026))

    def test_post_unversioned_not_tagged_as_pre(self):
        self.assertFalse(should_tag_pre_fix(POST_UNVERSIONED_2026))
        # Non viene promosso automaticamente a post_shrinkage_v1.
        self.assertEqual(get_model_version(POST_UNVERSIONED_2026), MODEL_VERSION_LEGACY)

    def test_legacy_old_season_not_tagged(self):
        self.assertFalse(should_tag_pre_fix(LEGACY_2025))
        self.assertEqual(get_model_version(LEGACY_2025), MODEL_VERSION_LEGACY)

    def test_ambiguous_window_not_tagged(self):
        # Salvata tra il commit di fix e il merge in main: non classificare.
        self.assertFalse(should_tag_pre_fix(AMBIGUOUS_2026))
        info = classify_entry(AMBIGUOUS_2026)
        self.assertEqual(info["status"], "ambiguous")

    def test_explicit_ambiguous_not_tagged_even_if_pre_window(self):
        explicit = dict(AMBIGUOUS_2026)
        explicit[MODEL_VERSION_FIELD] = MODEL_VERSION_AMBIGUOUS
        self.assertFalse(should_tag_pre_fix(explicit))
        self.assertEqual(classify_entry(explicit)["status"], "ambiguous")


class TestStats(unittest.TestCase):
    def test_current_stats_exclude_pre_fix(self):
        stats = stats_current_model([PRE_2026, POST_CURRENT_2026])
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["wins"], 1)
        self.assertEqual(stats["win_rate"], 100.0)

    def test_historical_stats_include_pre_and_legacy(self):
        stats = stats_historical([PRE_2026, POST_CURRENT_2026, LEGACY_2025])
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["wins"], 1)
        self.assertEqual(stats["losses"], 1)
        self.assertEqual(stats["win_rate"], 50.0)

    def test_excluded_flag_removes_from_current_even_if_versioned(self):
        weird = dict(POST_CURRENT_2026)
        weird[EXCLUDED_FROM_CURRENT_STATS_FIELD] = True
        stats = stats_current_model([weird])
        self.assertEqual(stats["total"], 0)
        self.assertTrue(is_excluded_from_stats(weird))


class TestNewPredictionsAndLegacyLoad(unittest.TestCase):
    def test_new_prediction_metadata_has_current_version(self):
        md = new_prediction_metadata()
        self.assertEqual(md[MODEL_VERSION_FIELD], MODEL_VERSION_CURRENT)
        self.assertIs(md[EXCLUDED_FROM_CURRENT_STATS_FIELD], False)

    def test_loading_old_json_without_version_still_works(self):
        old = {
            "match_id": 99,
            "home": "A", "away": "B", "campionato": "Serie A", "giornata": 1,
            "data": "29/08/2026 20:45", "pronostico_sicuro": "Under 2.5",
            "mercato_standard": "UNDER_2.5", "top3": [], "prob_sicuro": 58.0,
            "risultati_attesi": "", "risultato_reale": None, "esito": "⏳",
            "tipo": "Top Mix", "stagione": "2026/2027", "salvato_il": "26/08/2026 11:00",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "predictions.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"data": [old]}, f, ensure_ascii=False)
            loaded = load_predictions_file(path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["match_id"], 99)
            # Nessuna promozione automatica a post_shrinkage_v1.
            self.assertEqual(get_model_version(loaded[0]), MODEL_VERSION_LEGACY)
            self.assertFalse(is_current_model(loaded[0]))


class TestSeasonParsing(unittest.TestCase):
    def test_season_derived_from_explicit_or_date(self):
        self.assertEqual(season_from_entry(PRE_2026), "2026/2027")
        self.assertEqual(season_from_entry(LEGACY_2025), "2025/2026")

    def test_unknown_season_is_empty(self):
        self.assertEqual(season_from_entry({}), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
