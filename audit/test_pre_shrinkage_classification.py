#!/usr/bin/env python3
"""
audit/test_pre_shrinkage_classification.py

Test della logica di classificazione/migrazione delle predizioni pre-shrinkage.

Il cutoff di produzione e' il merge commit del fix NG/shrinkage in main:
  dc192d5eaa36968380f8bde823ca1abe9792e65d  2026-09-04T16:50:17+00:00

NOT il timestamp del commit del fix sul branch. Solo dal merge il modello
corretto era disponibile all'app di produzione.

Esecuzione:
    python -m unittest audit.test_pre_shrinkage_classification -v
    python audit/test_pre_shrinkage_classification.py
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SOCCERMATH_DIR = _REPO_ROOT / "SoccerMath"
_AUDIT_DIR = _REPO_ROOT / "audit"
for _p in (str(_SOCCERMATH_DIR), str(_AUDIT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from prediction_registry import (  # noqa: E402
    CUTOFF_MERGE_TIME,
    CUTOFF_COMMIT_TIME,
    EXCLUDED_FROM_CURRENT_STATS_FIELD,
    MODEL_VERSION_AMBIGUOUS,
    MODEL_VERSION_CURRENT,
    MODEL_VERSION_FIELD,
    MODEL_VERSION_LEGACY,
    MODEL_VERSION_PRE_FIX,
    TARGET_SEASON,
    TZ_ITALY,
    classify_entry,
    entry_era_by_time,
    entry_generation_time,
    normalize_season,
    parse_datetime,
    season_from_entry,
    should_tag_pre_fix,
    tag_pre_fix,
)
import tag_pre_shrinkage_predictions as mig  # noqa: E402


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _entry(home="A", away="B", salvato_il=None, prob=70.0,
           stagione="2026/2027", data="05/09/2026 16:00",
           model_version=None, esito="⏳", campionato="Premier League",
           **extra) -> Dict[str, Any]:
    """Crea un record di registro minimale."""
    e: Dict[str, Any] = {
        "home": home,
        "away": away,
        "campionato": campionato,
        "giornata": 3,
        "data": data,
        "pronostico_sicuro": f"NG - {prob}% - Top Mix Automatico",
        "mercato_standard": "NG",
        "prob_sicuro": prob,
        "risultato_reale": "",
        "esito": esito,
        "tipo": "Top Mix",
        "salvato_il": salvato_il,
    }
    if stagione is not None:
        e["stagione"] = stagione
    if model_version is not None:
        e[MODEL_VERSION_FIELD] = model_version
    e.update(extra)
    return e


# Merge in main: 2026-09-04 16:50:17 UTC = 2026-09-04 18:50:17 CEST (UTC+2)
MERGE_UTC = CUTOFF_MERGE_TIME  # datetime(2026, 9, 4, 16, 50, 17, tzinfo=timezone.utc)


# ===========================================================================
# TEST 1: record 04/09/2026 15:25 Europe/Rome -> pre_shrinkage
# ===========================================================================
class Test01_FifteenTwentyFive_Rome(unittest.TestCase):
    """04/09/2026 15:25 Europe/Rome = 13:25 UTC < 16:50:17 UTC merge -> pre_shrinkage."""

    def test_pre_shrinkage(self):
        entry = _entry(home="Team1", away="Team2",
                       salvato_il="04/09/2026 15:25")
        dt, field = entry_generation_time(entry)
        self.assertIsNotNone(dt)
        # 15:25 CEST = 13:25 UTC
        expected_utc = datetime(2026, 9, 4, 13, 25, 0, tzinfo=timezone.utc)
        self.assertEqual(dt, expected_utc)
        self.assertTrue(dt < MERGE_UTC)
        self.assertEqual(entry_era_by_time(entry), "pre")
        self.assertTrue(should_tag_pre_fix(entry))
        info = classify_entry(entry)
        self.assertEqual(info["status"], "to_tag_pre_shrinkage")
        tagged = tag_pre_fix(entry)
        self.assertEqual(tagged[MODEL_VERSION_FIELD], MODEL_VERSION_PRE_FIX)
        self.assertTrue(tagged[EXCLUDED_FROM_CURRENT_STATS_FIELD])


# ===========================================================================
# TEST 2: record 04/09/2026 16:40 Europe/Rome -> pre_shrinkage
# ===========================================================================
class Test02_SixteenForty_Rome(unittest.TestCase):
    """04/09/2026 16:40 Europe/Rome = 14:40 UTC < 16:50:17 UTC merge -> pre_shrinkage.

    Questi sono i 9 record citati nel requirements che DEVONO risultare
    pre_shrinkage perche' creati prima che il fix entrasse in main.
    """

    def test_pre_shrinkage(self):
        entry = _entry(home="Team3", away="Team4",
                       salvato_il="04/09/2026 16:40")
        dt, _ = entry_generation_time(entry)
        expected_utc = datetime(2026, 9, 4, 14, 40, 0, tzinfo=timezone.utc)
        self.assertEqual(dt, expected_utc)
        self.assertTrue(dt < MERGE_UTC)
        self.assertEqual(entry_era_by_time(entry), "pre")
        self.assertTrue(should_tag_pre_fix(entry))
        info = classify_entry(entry)
        self.assertEqual(info["status"], "to_tag_pre_shrinkage")

    def test_nine_records_at_1640_all_pre(self):
        """Simula i 9 record del JSONBin reale con salvato_il 04/09/2026 16:40."""
        records = []
        for i in range(9):
            records.append(_entry(home=f"Home{i}", away=f"Away{i}",
                                  salvato_il="04/09/2026 16:40",
                                  prob=60.0 + i))
        migrated, changed, kept = mig.build_migration(records)
        self.assertEqual(changed, 9, "tutti e 9 i record devono essere taggati")
        self.assertEqual(kept, 0)
        for m in migrated:
            self.assertEqual(m[MODEL_VERSION_FIELD], MODEL_VERSION_PRE_FIX)
            self.assertTrue(m[EXCLUDED_FROM_CURRENT_STATS_FIELD])


# ===========================================================================
# TEST 3: record immediatamente dopo il merge -> ambiguous
# ===========================================================================
class Test03_ImmediatelyAfterMerge(unittest.TestCase):
    """Record salvato subito dopo il merge in main senza model_version -> ambiguous."""

    def test_ambiguous_after_merge(self):
        # 04/09/2026 19:00 CEST = 17:00 UTC > 16:50:17 UTC merge
        entry = _entry(home="Post", away="Merge",
                       salvato_il="04/09/2026 19:00")
        dt, _ = entry_generation_time(entry)
        expected_utc = datetime(2026, 9, 4, 17, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(dt, expected_utc)
        self.assertTrue(dt >= MERGE_UTC)
        self.assertEqual(entry_era_by_time(entry), "post")
        self.assertFalse(should_tag_pre_fix(entry))
        info = classify_entry(entry)
        self.assertEqual(info["status"], "ambiguous")

    def test_exactly_at_merge_boundary(self):
        """Esattamente al merge (>=) -> post -> ambiguous."""
        # 2026-09-04 18:50:17 CEST = 16:50:17 UTC = exactly CUTOFF_MERGE_TIME
        entry = _entry(home="Boundary", away="Test",
                       salvato_il="04/09/2026 18:50:17")
        dt, _ = entry_generation_time(entry)
        expected_utc = datetime(2026, 9, 4, 16, 50, 17, tzinfo=timezone.utc)
        self.assertEqual(dt, expected_utc)
        self.assertTrue(dt >= MERGE_UTC)
        self.assertEqual(entry_era_by_time(entry), "post")
        info = classify_entry(entry)
        self.assertEqual(info["status"], "ambiguous")

    def test_one_second_before_merge_is_pre(self):
        """Un secondo prima del merge -> ancora pre -> pre_shrinkage."""
        # 04/09/2026 18:50:16 CEST = 16:50:16 UTC < 16:50:17 UTC
        entry = _entry(home="JustBefore", away="Merge",
                       salvato_il="04/09/2026 18:50:16")
        dt, _ = entry_generation_time(entry)
        self.assertTrue(dt < MERGE_UTC)
        self.assertEqual(entry_era_by_time(entry), "pre")
        self.assertTrue(should_tag_pre_fix(entry))


# ===========================================================================
# TEST 4: record maggio 2026 -> legacy
# ===========================================================================
class Test04_May2026Legacy(unittest.TestCase):
    """Record di maggio 2026 (stagione 2025/26) -> legacy."""

    def test_may_2026_legacy(self):
        # Maggio 2026: la partita e' di maggio 2026 -> stagione 2025/26
        entry = _entry(home="Old1", away="Old2",
                       salvato_il="15/05/2026 20:00",
                       data="16/05/2026 18:00",
                       stagione="2025/2026",
                       esito="✅")
        self.assertEqual(season_from_entry(entry), "2025/2026")
        self.assertEqual(normalize_season(season_from_entry(entry)), "2025/2026")
        self.assertNotEqual(normalize_season(season_from_entry(entry)), TARGET_SEASON)
        self.assertFalse(should_tag_pre_fix(entry))
        info = classify_entry(entry)
        self.assertEqual(info["status"], "legacy")

    def test_may_2026_without_stagione_field(self):
        """Maggio 2026 senza campo stagione: inferito dalla data -> 2025/26 -> legacy."""
        entry = _entry(home="Old3", away="Old4",
                       salvato_il="23/05/2026 08:19",
                       data="23/05/2026 21:00",
                       stagione=None)
        # La data della partita e' 23/05/2026 -> mese 5 < 8 -> stagione 2025/2026
        season = season_from_entry(entry)
        self.assertEqual(normalize_season(season), "2025/2026")
        info = classify_entry(entry)
        self.assertEqual(info["status"], "legacy")


# ===========================================================================
# TEST 5: record agosto 2026 senza campo stagione -> riconosciuto come 2026/27
# ===========================================================================
class Test05_August2026NoSeasonField(unittest.TestCase):
    """Record di agosto 2026 senza campo stagione: inferito come 2026/27."""

    def test_august_2026_inferred_season(self):
        entry = _entry(home="Aug1", away="Aug2",
                       salvato_il="26/08/2026 11:00",
                       data="29/08/2026 20:45",
                       stagione=None)
        season = season_from_entry(entry)
        self.assertEqual(normalize_season(season), "2026/2027")
        self.assertEqual(normalize_season(season), TARGET_SEASON)

    def test_august_2026_no_season_tagged_as_pre(self):
        """Agosto 2026, senza campo stagione, prima del merge -> pre_shrinkage."""
        entry = _entry(home="Aug3", away="Aug4",
                       salvato_il="26/08/2026 11:00",
                       data="29/08/2026 20:45",
                       stagione=None)
        self.assertTrue(should_tag_pre_fix(entry))
        info = classify_entry(entry)
        self.assertEqual(info["status"], "to_tag_pre_shrinkage")

    def test_september_2026_no_season_inferred(self):
        """Settembre 2026 senza campo stagione -> mese 9 >= 8 -> 2026/27."""
        entry = _entry(home="Sep1", away="Sep2",
                       salvato_il="02/09/2026 10:00",
                       data="04/09/2026 20:45",
                       stagione=None)
        season = season_from_entry(entry)
        self.assertEqual(normalize_season(season), "2026/2027")
        self.assertTrue(should_tag_pre_fix(entry))

    def test_no_season_not_classified_as_legacy(self):
        """Un record senza campo stagione MA con data in 2026/27 NON deve essere
        classificato legacy solo perche' manca il campo."""
        entry = _entry(home="NoS", away="Field",
                       salvato_il="04/09/2026 16:40",
                       data="05/09/2026 16:00",
                       stagione=None)
        info = classify_entry(entry)
        self.assertNotEqual(info["status"], "legacy")
        self.assertEqual(info["status"], "to_tag_pre_shrinkage")


# ===========================================================================
# TEST 6: model_version gia' presente -> non modificato
# ===========================================================================
class Test06_ExistingModelVersion(unittest.TestCase):
    """Record con model_version gia' presente non devono essere riclassificati."""

    def test_post_shrinkage_v1_not_modified(self):
        entry = _entry(home="Current", away="Model",
                       salvato_il="05/09/2026 10:00",
                       model_version=MODEL_VERSION_CURRENT)
        self.assertFalse(should_tag_pre_fix(entry))
        info = classify_entry(entry)
        self.assertEqual(info["status"], "already_post_shrinkage_v1")

    def test_explicit_post_version_wins_over_pre_merge_timestamp(self):
        """Comportamento ATTUALE, non un fix: model_version esplicito vince sul tempo.

        Se Schalke–Bayern e' taggato post_shrinkage_v1 con salvato_il precedente
        al merge, classify_entry NON lo ribalta a pre_fix. Non e' un bug del
        parser di data: e' la regola 'versione esplicita non sovrascritta'.
        Un eventuale correttivo andrebbe proposto, non applicato qui.
        """
        entry = _entry(home="Schalke", away="Bayern",
                       salvato_il="04/09/2026 15:25",
                       model_version=MODEL_VERSION_CURRENT,
                       prob=92.1)
        self.assertEqual(entry_era_by_time(entry), "pre")
        info = classify_entry(entry)
        self.assertEqual(info["status"], "already_post_shrinkage_v1")
        self.assertFalse(should_tag_pre_fix(entry))

    def test_pre_shrinkage_already_tagged_not_modified(self):
        entry = _entry(home="Pre", away="Already",
                       salvato_il="04/09/2026 16:00",
                       model_version=MODEL_VERSION_PRE_FIX,
                       excluded_from_current_model_stats=True)
        self.assertFalse(should_tag_pre_fix(entry))
        info = classify_entry(entry)
        self.assertEqual(info["status"], "already_pre_shrinkage")

    def test_ambiguous_explicit_not_overridden(self):
        """Un record con model_version='ambiguous' esplicito non viene cambiato
        anche se il timestamp lo porterebbe a pre_shrinkage."""
        entry = _entry(home="Amb", away="Explicit",
                       salvato_il="04/09/2026 15:00",
                       model_version=MODEL_VERSION_AMBIGUOUS)
        self.assertFalse(should_tag_pre_fix(entry))
        info = classify_entry(entry)
        self.assertEqual(info["status"], "ambiguous")

    def test_legacy_explicit_not_overridden(self):
        """Un record con model_version='legacy' esplicito resta legacy."""
        entry = _entry(home="Leg", away="Explicit",
                       salvato_il="04/09/2026 15:00",
                       model_version=MODEL_VERSION_LEGACY)
        # legacy esplicito e' trattato come "non ha versione" per should_tag
        self.assertTrue(should_tag_pre_fix(entry))
        info = classify_entry(entry)
        self.assertEqual(info["status"], "to_tag_pre_shrinkage")

    def test_build_migration_preserves_existing_version(self):
        records = [
            _entry(home="A", away="B", salvato_il="05/09/2026 10:00",
                   model_version=MODEL_VERSION_CURRENT),
            _entry(home="C", away="D", salvato_il="04/09/2026 16:00",
                   model_version=MODEL_VERSION_PRE_FIX),
        ]
        migrated, changed, kept = mig.build_migration(records)
        self.assertEqual(changed, 0, "nessun record con model_version deve essere toccato")
        self.assertEqual(kept, 2)
        self.assertEqual(migrated[0][MODEL_VERSION_FIELD], MODEL_VERSION_CURRENT)
        self.assertEqual(migrated[1][MODEL_VERSION_FIELD], MODEL_VERSION_PRE_FIX)


# ===========================================================================
# TEST 7: probabilita' 99.8 e probabilita' 52 con stesso timestamp -> stessa classificazione
# ===========================================================================
class Test07_ProbabilityIrrelevant(unittest.TestCase):
    """La probabilita' NON entra nel criterio di classificazione."""

    def test_998_and_52_same_classification(self):
        entry_998 = _entry(home="High", away="Prob",
                           salvato_il="04/09/2026 16:40", prob=99.8)
        entry_52 = _entry(home="Low", away="Prob",
                          salvato_il="04/09/2026 16:40", prob=52.0)
        info_998 = classify_entry(entry_998)
        info_52 = classify_entry(entry_52)
        self.assertEqual(info_998["status"], info_52["status"])
        self.assertEqual(info_998["status"], "to_tag_pre_shrinkage")
        self.assertTrue(should_tag_pre_fix(entry_998))
        self.assertTrue(should_tag_pre_fix(entry_52))

    def test_hull_city_and_man_city_998(self):
        """Hull City-Aston Villa e Man City-Coventry City, NG 99.8%:
        devono essere classificati per timestamp, non per probabilita'."""
        hull = _entry(home="Hull City", away="Aston Villa",
                      salvato_il="04/09/2026 16:40", prob=99.8,
                      pronostico_sicuro="NG - 99.8% - Top Mix Automatico")
        man_city = _entry(home="Man City", away="Coventry City",
                          salvato_il="04/09/2026 16:40", prob=99.8,
                          pronostico_sicuro="NG - 99.8% - Top Mix Automatico")
        self.assertTrue(should_tag_pre_fix(hull))
        self.assertTrue(should_tag_pre_fix(man_city))

    def test_probability_sweep_same_timestamp(self):
        for prob in (0.1, 25.0, 50.0, 52.0, 75.0, 99.8, 100.0):
            entry = _entry(home="Sweep", away=f"P{prob}",
                           salvato_il="04/09/2026 16:40", prob=prob)
            info = classify_entry(entry)
            self.assertEqual(info["status"], "to_tag_pre_shrinkage",
                             f"prob={prob} deve essere pre_shrinkage")


# ===========================================================================
# TEST 8: confronto corretto tra Europe/Rome e timestamp Git UTC
# ===========================================================================
class Test08_TimezoneComparison(unittest.TestCase):
    """Il confronto deve avvenire tra istanti timezone-aware reali."""

    def test_rome_time_correctly_converted_to_utc(self):
        """16:40 CEST (UTC+2) = 14:40 UTC < 16:50:17 UTC merge."""
        dt_rome = parse_datetime("04/09/2026 16:40")
        self.assertIsNotNone(dt_rome)
        # Deve essere un datetime aware in UTC
        self.assertIsNotNone(dt_rome.tzinfo)
        utc_equivalent = dt_rome.astimezone(timezone.utc)
        self.assertEqual(utc_equivalent.hour, 14)
        self.assertEqual(utc_equivalent.minute, 40)
        self.assertTrue(utc_equivalent < MERGE_UTC)

    def test_git_utc_timestamp_aware(self):
        """Il timestamp Git e' timezone-aware (UTC)."""
        self.assertIsNotNone(MERGE_UTC.tzinfo)
        self.assertEqual(MERGE_UTC.tzinfo, timezone.utc)

    def test_comparison_both_aware_no_error(self):
        """Confronto diretto tra datetime aware: nessun TypeError."""
        dt = parse_datetime("04/09/2026 16:40")
        # Questo non deve mai sollevare TypeError
        result = dt < MERGE_UTC
        self.assertIsInstance(result, bool)
        self.assertTrue(result)

    def test_rome_cest_offset_is_two_hours(self):
        """Verifica che a settembre 2026 siamo in CEST (UTC+2)."""
        dt = parse_datetime("04/09/2026 16:40")
        dt_utc = dt.astimezone(timezone.utc)
        # 16:40 CEST = 14:40 UTC -> differenza 2 ore
        diff_hours = (16 - dt_utc.hour) % 24
        self.assertEqual(diff_hours, 2)


# ===========================================================================
# TEST 9: cambio DST/timezone non deve produrre confronti naive
# ===========================================================================
class Test09_DSTSafety(unittest.TestCase):
    """Il confronto non deve mai avvenire tra datetime naive."""

    def test_parsed_datetime_is_always_aware(self):
        """parse_datetime() restituisce sempre datetime aware (UTC)."""
        for fmt in ("04/09/2026 16:40", "04/09/2026 16:40:00",
                    "2026-09-04T14:40:00+00:00", "2026-09-04T16:40:00",
                    "2026-09-04T14:40:00Z"):
            dt = parse_datetime(fmt)
            self.assertIsNotNone(dt, f"parse failed for {fmt}")
            self.assertIsNotNone(dt.tzinfo,
                                 f"parse_datetime('{fmt}') returned naive datetime")

    def test_no_naive_comparison_in_era(self):
        """entry_era_by_time non deve mai confrontare datetime naive."""
        # Anche con un salvato_il in formato ISO senza tz, deve essere
        # reso aware prima del confronto.
        entry = _entry(home="Naive", away="Test",
                       salvato_il="2026-09-04T14:40:00")
        era = entry_era_by_time(entry)
        self.assertIn(era, ("pre", "post", "unknown"))

    def test_winter_time_cet_vs_summer_cest(self):
        """In inverno (CET, UTC+1) lo shift e' diverso dall'estate (CEST, UTC+2).
        La logica deve funzionare correttamente in entrambi i casi."""
        # Gennaio 2027: CET (UTC+1)
        winter_entry = _entry(home="Winter", away="Test",
                              salvato_il="15/01/2027 20:00",
                              data="16/01/2027 18:00",
                              stagione="2026/2027")
        dt = parse_datetime("15/01/2027 20:00")
        dt_utc = dt.astimezone(timezone.utc)
        # 20:00 CET = 19:00 UTC
        self.assertEqual(dt_utc.hour, 19)

        # Settembre 2026: CEST (UTC+2)
        summer_entry = _entry(home="Summer", away="Test",
                              salvato_il="04/09/2026 20:00",
                              data="05/09/2026 18:00",
                              stagione="2026/2027")
        dt2 = parse_datetime("04/09/2026 20:00")
        dt2_utc = dt2.astimezone(timezone.utc)
        # 20:00 CEST = 18:00 UTC
        self.assertEqual(dt2_utc.hour, 18)

    def test_all_comparisons_are_aware(self):
        """Verifica che TUTTI i path di confronto nel codice usino aware datetime."""
        from prediction_registry import _as_aware
        # _as_aware deve sempre produrre datetime aware
        naive = datetime(2026, 9, 4, 16, 40, 0)
        aware = _as_aware(naive)
        self.assertIsNotNone(aware.tzinfo)
        # Confronto diretto con MERGE_UTC non deve mai fallire
        _ = aware < MERGE_UTC


# ===========================================================================
# Simulazione del registro reale (83 record: 29 legacy / 54 pre_shrinkage)
# ===========================================================================
class Test10_SimulationFullRegistry(unittest.TestCase):
    """Simulazione del registro JSONBin reale.

    Costruisce un fixture di 83 record che rispecchia la distribuzione attesa:
      - 29 record di stagioni precedenti (2025/26 e prima) -> legacy
      - 54 record della stagione 2026/27 salvati prima del merge -> pre_shrinkage
      - 0 ambiguous
      - 0 post_shrinkage_v1

    La simulazione usa build_migration() (funzione pura, nessun I/O) e verifica
    i conteggi esatti.
    """

    def _build_fixture(self) -> List[Dict[str, Any]]:
        """Costruisce il fixture di 83 record."""
        records: List[Dict[str, Any]] = []

        # --- 29 record legacy (stagione 2025/26 e prima) ---
        legacy_timestamps = [
            ("15/03/2026 09:00", "15/03/2026 20:45", "2025/2026"),
            ("22/03/2026 10:00", "22/03/2026 18:00", "2025/2026"),
            ("29/03/2026 11:00", "29/03/2026 20:45", "2025/2026"),
            ("05/04/2026 09:00", "05/04/2026 18:00", "2025/2026"),
            ("12/04/2026 10:00", "12/04/2026 20:45", "2025/2026"),
            ("19/04/2026 11:00", "19/04/2026 18:00", "2025/2026"),
            ("26/04/2026 09:00", "26/04/2026 20:45", "2025/2026"),
            ("03/05/2026 10:00", "03/05/2026 18:00", "2025/2026"),
            ("10/05/2026 11:00", "10/05/2026 20:45", "2025/2026"),
            ("17/05/2026 09:00", "17/05/2026 18:00", "2025/2026"),
            ("23/05/2026 08:19", "23/05/2026 21:00", "2025/2026"),
            ("16/08/2025 10:00", "16/08/2025 18:00", "2025/2026"),
            ("23/08/2025 11:00", "23/08/2025 20:45", "2025/2026"),
            ("30/08/2025 09:00", "30/08/2025 18:00", "2025/2026"),
            ("06/09/2025 10:00", "06/09/2025 20:45", "2025/2026"),
            ("13/09/2025 11:00", "13/09/2025 18:00", "2025/2026"),
            ("20/09/2025 09:00", "20/09/2025 20:45", "2025/2026"),
            ("27/09/2025 10:00", "27/09/2025 18:00", "2025/2026"),
            ("04/10/2025 11:00", "04/10/2025 20:45", "2025/2026"),
            ("11/10/2025 09:00", "11/10/2025 18:00", "2025/2026"),
            ("18/10/2025 10:00", "18/10/2025 20:45", "2025/2026"),
            ("25/10/2025 11:00", "25/10/2025 18:00", "2025/2026"),
            ("01/11/2025 09:00", "01/11/2025 20:45", "2025/2026"),
            ("08/11/2025 10:00", "08/11/2025 18:00", "2025/2026"),
            ("15/11/2025 11:00", "15/11/2025 20:45", "2025/2026"),
            ("22/11/2025 09:00", "22/11/2025 18:00", "2025/2026"),
            ("29/11/2025 10:00", "29/11/2025 20:45", "2025/2026"),
            ("06/12/2025 11:00", "06/12/2025 18:00", "2025/2026"),
            ("13/12/2025 09:00", "13/12/2025 20:45", "2025/2026"),
        ]
        for i, (salvato, data_match, stag) in enumerate(legacy_timestamps):
            records.append(_entry(
                home=f"Legacy{i}", away=f"Old{i}",
                salvato_il=salvato, data=data_match,
                stagione=stag, prob=55.0 + i,
                esito="✅" if i % 2 == 0 else "❌"))

        # --- 54 record pre_shrinkage (stagione 2026/27, prima del merge) ---
        # Timestamps prima di 2026-09-04 16:50:17 UTC (= 18:50:17 CEST)
        pre_timestamps = [
            # Record di agosto 2026 (alcuni senza campo stagione esplicito)
            ("17/08/2026 10:00", "17/08/2026 18:00", None),
            ("17/08/2026 14:00", "18/08/2026 20:45", "2026/2027"),
            ("21/08/2026 11:00", "21/08/2026 18:30", "2026/2027"),
            ("21/08/2026 15:00", "22/08/2026 20:45", None),
            ("24/08/2026 09:00", "24/08/2026 18:00", "2026/2027"),
            ("24/08/2026 12:00", "25/08/2026 20:45", "2026/2027"),
            ("26/08/2026 11:00", "29/08/2026 20:45", None),
            ("26/08/2026 14:00", "30/08/2026 18:00", "2026/2027"),
            ("28/08/2026 10:00", "30/08/2026 20:45", "2026/2027"),
            ("28/08/2026 16:00", "31/08/2026 18:00", None),
            ("30/08/2026 09:00", "31/08/2026 20:45", "2026/2027"),
            ("30/08/2026 12:00", "01/09/2026 18:00", "2026/2027"),
            # Record di settembre 2026 (prima del merge)
            ("01/09/2026 10:00", "02/09/2026 20:45", "2026/2027"),
            ("01/09/2026 14:00", "03/09/2026 18:00", None),
            ("02/09/2026 09:00", "03/09/2026 20:45", "2026/2027"),
            ("02/09/2026 11:00", "04/09/2026 18:00", "2026/2027"),
            ("02/09/2026 15:00", "05/09/2026 20:45", None),
            ("03/09/2026 08:00", "04/09/2026 18:00", "2026/2027"),
            ("03/09/2026 10:00", "05/09/2026 20:45", "2026/2027"),
            ("03/09/2026 14:00", "06/09/2026 18:00", "2026/2027"),
            ("03/09/2026 16:00", "06/09/2026 20:45", None),
            ("03/09/2026 18:00", "07/09/2026 18:00", "2026/2027"),
            ("04/09/2026 08:00", "05/09/2026 20:45", "2026/2027"),
            ("04/09/2026 09:00", "06/09/2026 18:00", "2026/2027"),
            ("04/09/2026 10:00", "06/09/2026 20:45", "2026/2027"),
            ("04/09/2026 11:00", "07/09/2026 18:00", None),
            ("04/09/2026 12:00", "07/09/2026 20:45", "2026/2027"),
            # Hull City - Aston Villa, NG 99.8%
            ("04/09/2026 17:35", "05/09/2026 16:00", "2026/2027"),
            # Man City - Coventry City, NG 99.8%
            ("04/09/2026 17:35", "05/09/2026 16:00", "2026/2027"),
            # 9 record a 04/09/2026 16:40
            ("04/09/2026 16:40", "05/09/2026 18:00", "2026/2027"),
            ("04/09/2026 16:40", "05/09/2026 18:30", "2026/2027"),
            ("04/09/2026 16:40", "06/09/2026 18:00", None),
            ("04/09/2026 16:40", "06/09/2026 20:45", "2026/2027"),
            ("04/09/2026 16:40", "07/09/2026 18:00", "2026/2027"),
            ("04/09/2026 16:40", "07/09/2026 20:45", None),
            ("04/09/2026 16:40", "08/09/2026 18:00", "2026/2027"),
            ("04/09/2026 16:40", "08/09/2026 20:45", "2026/2027"),
            ("04/09/2026 16:40", "09/09/2026 18:00", None),
            # 2 record a 04/09/2026 15:25
            ("04/09/2026 15:25", "05/09/2026 20:45", "2026/2027"),
            ("04/09/2026 15:25", "06/09/2026 18:00", "2026/2027"),
            # Altri record pre-merge
            ("01/09/2026 08:00", "02/09/2026 18:00", "2026/2027"),
            ("01/09/2026 16:00", "03/09/2026 20:45", None),
            ("02/09/2026 14:00", "04/09/2026 18:00", "2026/2027"),
            ("03/09/2026 12:00", "05/09/2026 18:00", "2026/2027"),
            ("03/09/2026 20:00", "06/09/2026 20:45", None),
            ("04/09/2026 07:00", "05/09/2026 18:00", "2026/2027"),
            ("04/09/2026 13:00", "06/09/2026 20:45", "2026/2027"),
            ("04/09/2026 14:00", "07/09/2026 18:00", None),
            ("04/09/2026 15:00", "07/09/2026 20:45", "2026/2027"),
            ("04/09/2026 16:00", "08/09/2026 18:00", "2026/2027"),
            # 4 record aggiuntivi per raggiungere 54
            ("20/08/2026 10:00", "23/08/2026 20:45", "2026/2027"),
            ("25/08/2026 11:00", "27/08/2026 18:00", None),
            ("02/09/2026 16:00", "04/09/2026 20:45", "2026/2027"),
            ("03/09/2026 07:00", "05/09/2026 20:45", "2026/2027"),
        ]
        # Costruisce i record con nomi squadra specifici per Hull/Man City
        special_names = {
            27: ("Hull City", "Aston Villa"),       # NG 99.8%
            28: ("Man City", "Coventry City"),       # NG 99.8%
        }
        for i, (salvato, data_match, stag) in enumerate(pre_timestamps):
            prob = 52.0 if i % 3 == 0 else (99.8 if i % 5 == 0 else 65.0 + i * 0.3)
            if i in special_names:
                home, away = special_names[i]
                prob = 99.8  # Hull City e Man City hanno prob 99.8
            else:
                home, away = f"Pre{i}", f"Shrink{i}"
            records.append(_entry(
                home=home, away=away,
                salvato_il=salvato, data=data_match,
                stagione=stag, prob=round(prob, 1)))

        return records

    def test_total_83_records(self):
        fixture = self._build_fixture()
        self.assertEqual(len(fixture), 83)

    def test_29_legacy(self):
        fixture = self._build_fixture()
        legacy_count = sum(1 for e in fixture if classify_entry(e)["status"] == "legacy")
        self.assertEqual(legacy_count, 29, f"attesi 29 legacy, trovati {legacy_count}")

    def test_54_pre_shrinkage(self):
        fixture = self._build_fixture()
        pre_count = sum(1 for e in fixture
                        if classify_entry(e)["status"] == "to_tag_pre_shrinkage")
        self.assertEqual(pre_count, 54, f"attesi 54 pre_shrinkage, trovati {pre_count}")

    def test_0_ambiguous(self):
        fixture = self._build_fixture()
        amb_count = sum(1 for e in fixture if classify_entry(e)["status"] == "ambiguous")
        self.assertEqual(amb_count, 0, f"attesi 0 ambiguous, trovati {amb_count}")

    def test_0_post_shrinkage_v1(self):
        fixture = self._build_fixture()
        post_count = sum(1 for e in fixture
                         if classify_entry(e)["status"] == "already_post_shrinkage_v1")
        self.assertEqual(post_count, 0, f"attesi 0 post_shrinkage_v1, trovati {post_count}")

    def test_build_migration_produces_correct_counts(self):
        """La migrazione tramite build_migration() produce esattamente:
        29 legacy (invariati) + 54 pre_shrinkage (taggati)."""
        fixture = self._build_fixture()
        migrated, changed, kept = mig.build_migration(fixture)
        self.assertEqual(changed, 54, "54 record devono essere taggati pre_shrinkage")
        self.assertEqual(kept, 29, "29 record legacy restano invariati")
        self.assertEqual(len(migrated), 83)
        # Verifica che nessun campo sia stato perso
        pre = [m for m in migrated if m.get(MODEL_VERSION_FIELD) == MODEL_VERSION_PRE_FIX]
        self.assertEqual(len(pre), 54)

    def test_hull_city_and_man_city_in_pre(self):
        """Hull City-Aston Villa e Man City-Coventry City sono tra i 54 pre_shrinkage."""
        fixture = self._build_fixture()
        hull = [e for e in fixture
                if "Hull" in str(e.get("home", "")) or "Hull" in str(e.get("away", ""))]
        man_city = [e for e in fixture
                    if "Man City" in str(e.get("home", "")) or "Man City" in str(e.get("away", ""))]
        self.assertTrue(len(hull) > 0, "Hull City deve essere presente")
        self.assertTrue(len(man_city) > 0, "Man City deve essere presente")
        for e in hull:
            self.assertEqual(classify_entry(e)["status"], "to_tag_pre_shrinkage")
        for e in man_city:
            self.assertEqual(classify_entry(e)["status"], "to_tag_pre_shrinkage")


if __name__ == "__main__":
    unittest.main(verbosity=2)
