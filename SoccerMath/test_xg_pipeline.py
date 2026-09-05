"""
test_xg_pipeline.py - Test della pipeline xG consolidata.

Copre:
  * aggregazione casa/trasferta e conteggio ``matches``;
  * selezione della stagione corretta (nessuna mescolanza);
  * zero valido, valori mancanti/negativi/non finiti;
  * duplicati e conflitti sulla stessa partita;
  * alias, collisioni e nomi canonici (dati reali delle 5 leghe);
  * squadre senza partite valide;
  * cutoff temporale (nessuna partita futura; giorno intero escluso quando
    l'archivio non ha l'orario);
  * fallimento dell'acquisizione senza sovrascrittura dei dati validi.

Esecuzione:
    python -m pytest SoccerMath/test_xg_pipeline.py -v
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _REPO_ROOT)

import pandas as pd  # noqa: E402

import update_all_xg_db  # noqa: E402  (script di acquisizione, root del repo)
import update_xg  # noqa: E402
from config import LEAGUES_CONFIG, clean_name  # noqa: E402
from team_names import (  # noqa: E402
    NAME_MAP, canonical_team_name, resolve_team_name,
)
from xg_archive import (  # noqa: E402
    ARCHIVE_FILES, LEAGUES, aggregate_season, load_archive, parse_kickoff,
    parse_season, parse_xg, season_averages, validate_archive,
)

DB_DIR = os.path.join(_HERE, "database")
LEAGUE_PREFIX = {
    "Serie A": "SerieA", "Premier League": "Premier", "La Liga": "LaLiga",
    "Bundesliga": "Bundesliga", "Ligue 1": "Ligue1",
}
UTC = timezone.utc


def match(season=2026, mid=1, date="2026-08-20 18:00:00", home="Inter",
          away="Torino", home_xg=2.0, away_xg=1.0, is_result=True,
          home_goals=1, away_goals=0):
    return {
        "season": season, "id": mid, "date": date,
        "home_team": home, "away_team": away,
        "home_goals": home_goals, "away_goals": away_goals,
        "home_xg": home_xg, "away_xg": away_xg, "is_result": is_result,
    }


# ---------------------------------------------------------------------------
# 1. Aggregazione casa/trasferta e conteggio matches
# ---------------------------------------------------------------------------
class TestHomeAwayAggregation(unittest.TestCase):
    def test_home_and_away_perspective(self):
        agg = aggregate_season([match(mid=1, home="Inter", away="Torino",
                                      home_xg=2.0, away_xg=0.5)], 2026)
        self.assertEqual(agg.averages["Inter"],
                         {"xG_avg": 2.0, "xGA_avg": 0.5, "matches": 1})
        self.assertEqual(agg.averages["Torino"],
                         {"xG_avg": 0.5, "xGA_avg": 2.0, "matches": 1})

    def test_average_over_multiple_matches(self):
        records = [
            match(mid=1, home="Inter", away="Torino", home_xg=2.0, away_xg=0.5),
            match(mid=2, home="Milan", away="Inter", home_xg=1.0, away_xg=3.0),
        ]
        agg = aggregate_season(records, 2026)
        # Inter: xG (2.0 in casa + 3.0 fuori)/2, xGA (0.5 + 1.0)/2
        self.assertEqual(agg.averages["Inter"],
                         {"xG_avg": 2.5, "xGA_avg": 0.75, "matches": 2})
        self.assertEqual(agg.averages["Milan"]["matches"], 1)
        self.assertEqual(agg.matches_used, 2)

    def test_matches_counts_only_valid_matches(self):
        records = [
            match(mid=1, home="Inter", away="Torino"),
            match(mid=2, home="Inter", away="Milan", home_xg=None, away_xg=1.0),
            match(mid=3, home="Inter", away="Roma", is_result=False,
                  home_xg=None, away_xg=None),
        ]
        agg = aggregate_season(records, 2026)
        self.assertEqual(agg.averages["Inter"]["matches"], 1)
        self.assertEqual(agg.matches_used, 1)
        self.assertEqual(agg.matches_in_season, 3)
        self.assertEqual(agg.skipped.get("xg_mancante_o_non_valido"), 1)
        self.assertEqual(agg.skipped.get("non_giocata"), 1)

    def test_no_shrinkage_applied_here(self):
        """L'aggregazione restituisce la media grezza: lo shrinkage vive
        soltanto in app.get_league_engine (PRIOR_MATCHES)."""
        agg = aggregate_season([match(home_xg=0.4, away_xg=0.2)], 2026)
        self.assertEqual(agg.averages["Inter"]["xG_avg"], 0.4)
        self.assertEqual(agg.averages["Inter"]["xGA_avg"], 0.2)


# ---------------------------------------------------------------------------
# 2. Stagione corretta
# ---------------------------------------------------------------------------
class TestSeasonSelection(unittest.TestCase):
    def test_other_seasons_excluded(self):
        records = [
            match(season=2025, mid=1, home_xg=3.0, away_xg=3.0),
            match(season=2026, mid=2, home_xg=1.0, away_xg=0.0),
        ]
        agg = aggregate_season(records, 2026)
        self.assertEqual(agg.averages["Inter"],
                         {"xG_avg": 1.0, "xGA_avg": 0.0, "matches": 1})
        self.assertEqual(agg.skipped.get("altra_stagione"), 1)
        self.assertEqual(agg.matches_in_season, 1)

    def test_season_formats(self):
        self.assertEqual(parse_season(2026), 2026)
        self.assertEqual(parse_season("2026"), 2026)
        self.assertEqual(parse_season("2627"), 2026)
        self.assertEqual(parse_season("2026/2027"), 2026)
        self.assertEqual(parse_season("2026-27"), 2026)
        self.assertIsNone(parse_season("stagione"))
        self.assertIsNone(parse_season(None))

    def test_string_season_matches_int_request(self):
        agg = aggregate_season([match(season="2627")], 2026)
        self.assertEqual(agg.averages["Inter"]["matches"], 1)

    def test_unreadable_season_is_skipped(self):
        agg = aggregate_season([match(season="boh")], 2026)
        self.assertEqual(agg.averages, {})
        self.assertEqual(agg.skipped.get("stagione_illeggibile"), 1)


# ---------------------------------------------------------------------------
# 3. Zero valido, mancanti, negativi, non finiti
# ---------------------------------------------------------------------------
class TestValueValidation(unittest.TestCase):
    def test_zero_is_valid(self):
        agg = aggregate_season([match(home_xg=0.0, away_xg=1.5)], 2026)
        self.assertEqual(agg.averages["Inter"]["xG_avg"], 0.0)
        self.assertEqual(agg.averages["Inter"]["matches"], 1)
        self.assertEqual(agg.averages["Torino"]["xGA_avg"], 0.0)

    def test_missing_never_becomes_zero(self):
        records = [
            match(mid=1, home_xg=None, away_xg=1.0),
            match(mid=2, home="Inter", away="Milan", home_xg=2.0, away_xg=1.0),
        ]
        agg = aggregate_season(records, 2026)
        self.assertEqual(agg.averages["Inter"],
                         {"xG_avg": 2.0, "xGA_avg": 1.0, "matches": 1})
        self.assertNotIn("Torino", agg.averages)

    def test_negative_and_non_finite_rejected(self):
        for bad in (-0.1, float("nan"), float("inf"), float("-inf"), "n/d", True, None):
            with self.subTest(bad=bad):
                agg = aggregate_season([match(home_xg=bad, away_xg=1.0)], 2026)
                self.assertEqual(agg.averages, {})
                self.assertEqual(agg.skipped.get("xg_mancante_o_non_valido"), 1)

    def test_numeric_strings_accepted(self):
        agg = aggregate_season([match(home_xg="1.25", away_xg="0")], 2026)
        self.assertEqual(agg.averages["Inter"]["xG_avg"], 1.25)
        self.assertEqual(agg.averages["Inter"]["xGA_avg"], 0.0)

    def test_parse_xg_helper(self):
        self.assertEqual(parse_xg(0), 0.0)
        self.assertEqual(parse_xg("2.5"), 2.5)
        self.assertIsNone(parse_xg(True))
        self.assertIsNone(parse_xg(-1))
        self.assertIsNone(parse_xg(float("nan")))
        self.assertIsNone(parse_xg(pd.NA))

    def test_unplayed_match_with_xg_is_ignored(self):
        agg = aggregate_season([match(is_result=False, home_xg=1.0, away_xg=1.0)], 2026)
        self.assertEqual(agg.averages, {})
        self.assertEqual(agg.skipped.get("non_giocata"), 1)


# ---------------------------------------------------------------------------
# 4. Duplicati e conflitti
# ---------------------------------------------------------------------------
class TestDuplicatesAndConflicts(unittest.TestCase):
    def test_identical_duplicate_counted_once(self):
        rec = match(mid=7, home_xg=1.5, away_xg=0.5)
        agg = aggregate_season([rec, dict(rec)], 2026)
        self.assertEqual(agg.averages["Inter"]["matches"], 1)
        self.assertEqual(len(agg.duplicates), 1)
        self.assertEqual(agg.conflicts, [])

    def test_conflicting_duplicate_reported_and_not_averaged(self):
        agg = aggregate_season([
            match(mid=7, home_xg=1.5, away_xg=0.5),
            match(mid=7, home_xg=2.5, away_xg=0.5),
        ], 2026)
        self.assertEqual(agg.averages["Inter"], {"xG_avg": 1.5, "xGA_avg": 0.5,
                                                 "matches": 1})
        self.assertEqual(len(agg.conflicts), 1)
        self.assertEqual(agg.skipped.get("conflitto"), 1)

    def test_duplicate_without_id_uses_date_and_teams(self):
        rec = match(mid=None, home_xg=1.0, away_xg=1.0)
        agg = aggregate_season([rec, dict(rec)], 2026)
        self.assertEqual(agg.averages["Inter"]["matches"], 1)
        self.assertEqual(len(agg.duplicates), 1)

    def test_same_teams_different_matches_both_counted(self):
        agg = aggregate_season([
            match(mid=1, date="2026-08-20 18:00:00", home_xg=1.0, away_xg=1.0),
            match(mid=2, date="2027-01-20 18:00:00", home_xg=3.0, away_xg=1.0),
        ], 2026)
        self.assertEqual(agg.averages["Inter"]["matches"], 2)
        self.assertEqual(agg.averages["Inter"]["xG_avg"], 2.0)


# ---------------------------------------------------------------------------
# 5. Alias e collisioni
# ---------------------------------------------------------------------------
class TestNameNormalization(unittest.TestCase):
    def test_requested_explicit_checks(self):
        expected = {
            "Bayer Leverkusen": "Leverkusen",
            "Bayer 04 Leverkusen": "Leverkusen",
            "Leverkusen": "Leverkusen",
            "Borussia Dortmund": "Dortmund",
            "Dortmund": "Dortmund",
            "Borussia M.Gladbach": "M'gladbach",
            "M'gladbach": "M'gladbach",
            "Borussia Mönchengladbach": "M'gladbach",
            "FC Cologne": "Koln",
            "Köln": "Koln",
            "FC Koln": "Koln",
            "RasenBallsport Leipzig": "Leipzig",
            "RB Leipzig": "Leipzig",
            "Leipzig": "Leipzig",
            "VfB Stuttgart": "Stuttgart",
            "Stuttgart": "Stuttgart",
            "Athletic Club": "Ath Bilbao",
            "Athletic Bilbao": "Ath Bilbao",
            "Ath Bilbao": "Ath Bilbao",
            "Hull": "Hull City",
            "Hull City": "Hull City",
            "Coventry": "Coventry City",
            "Coventry City": "Coventry City",
            "St. Pauli": "St Pauli",
            "Saint-Etienne": "St Etienne",
            "Paris Saint Germain": "PSG",
            "Paris FC": "Paris",
        }
        for raw, canonical in expected.items():
            with self.subTest(raw=raw):
                self.assertEqual(canonical_team_name(raw), canonical)

    def test_paris_clubs_do_not_collide(self):
        self.assertNotEqual(canonical_team_name("Paris FC"),
                            canonical_team_name("Paris Saint Germain"))

    def test_canonical_names_are_clean_name_idempotent(self):
        """clean_name(canonico) == canonico: altrimenti il lookup dell'engine,
        che applica clean_name ai nomi CSV, fallirebbe."""
        for raw, canonical in NAME_MAP.items():
            with self.subTest(raw=raw):
                self.assertEqual(clean_name(canonical), canonical)

    def test_unknown_name_is_flagged_not_guessed(self):
        res = resolve_team_name("Squadra Inventata")
        self.assertFalse(res.mapped)
        self.assertEqual(res.canonical, "Squadra Inventata")

    def test_empty_name(self):
        res = resolve_team_name(None)
        self.assertEqual(res.canonical, "")
        self.assertFalse(res.mapped)

    def test_aliases_merge_into_one_team(self):
        """Due alias della stessa squadra non devono creare due voci."""
        agg = aggregate_season([
            match(mid=1, home="Bayer Leverkusen", away="Borussia Dortmund",
                  home_xg=2.0, away_xg=1.0),
            match(mid=2, home="Borussia Dortmund", away="Bayer 04 Leverkusen",
                  home_xg=1.0, away_xg=2.0),
        ], 2026)
        self.assertEqual(sorted(agg.averages), ["Dortmund", "Leverkusen"])
        self.assertEqual(agg.averages["Leverkusen"]["matches"], 2)
        self.assertEqual(agg.averages["Leverkusen"]["xG_avg"], 2.0)

    def test_unmapped_names_reported(self):
        agg = aggregate_season([match(home="Squadra Ignota", away="Torino")], 2026)
        self.assertIn("Squadra Ignota", agg.unmapped_names)

    def test_no_collisions_in_shared_map(self):
        """Nessun nome canonico deve essere raggiunto da due club diversi."""
        distinct_clubs = {
            "PSG": {"Paris Saint Germain", "Paris Saint-Germain", "Paris SG"},
            "Paris": {"Paris FC"},
        }
        for canonical, sources in distinct_clubs.items():
            for src in sources:
                self.assertEqual(canonical_team_name(src), canonical)

    def test_update_xg_reexports_name_map(self):
        """Retrocompatibilita': audit/test_ng_regression.py usa update_xg.NAME_MAP."""
        self.assertIs(update_xg.NAME_MAP, NAME_MAP)
        self.assertEqual(update_xg.NAME_MAP["Coventry"], "Coventry City")
        self.assertEqual(update_xg.NAME_MAP["Hull"], "Hull City")


# ---------------------------------------------------------------------------
# 6. Squadre senza partite valide
# ---------------------------------------------------------------------------
class TestTeamsWithoutData(unittest.TestCase):
    def test_team_seen_but_without_valid_matches_is_reported_not_invented(self):
        records = [
            match(mid=1, home="Inter", away="Torino", home_xg=1.0, away_xg=1.0),
            match(mid=2, home="Pisa", away="Milan", is_result=False,
                  home_xg=None, away_xg=None),
        ]
        agg = aggregate_season(records, 2026)
        self.assertNotIn("Pisa", agg.averages)
        self.assertNotIn("Milan", agg.averages)
        self.assertIn("Pisa", agg.teams_without_valid_matches)
        self.assertIn("Milan", agg.teams_without_valid_matches)

    def test_missing_team_never_gets_zero_stats(self):
        agg = aggregate_season([match(mid=1, home="Pisa", away="Milan",
                                      home_xg=None, away_xg=None)], 2026)
        self.assertEqual(agg.averages, {})


# ---------------------------------------------------------------------------
# 7. Cutoff temporale (base per audit point-in-time)
# ---------------------------------------------------------------------------
class TestTemporalCutoff(unittest.TestCase):
    def test_future_matches_excluded(self):
        records = [
            match(mid=1, date="2026-08-20 18:00:00", home_xg=1.0, away_xg=1.0),
            match(mid=2, date="2026-09-20 18:00:00", home="Inter", away="Milan",
                  home_xg=3.0, away_xg=0.0),
        ]
        agg = aggregate_season(records, 2026, cutoff="2026-09-01T00:00:00+00:00")
        self.assertEqual(agg.averages["Inter"]["matches"], 1)
        self.assertEqual(agg.averages["Inter"]["xG_avg"], 1.0)
        self.assertEqual(agg.skipped.get("dopo_cutoff"), 1)

    def test_match_exactly_at_cutoff_excluded(self):
        agg = aggregate_season(
            [match(date="2026-09-01 12:00:00")], 2026,
            cutoff=datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
        self.assertEqual(agg.averages, {})
        self.assertEqual(agg.skipped.get("dopo_cutoff"), 1)

    def test_earlier_same_day_kickoff_included_when_time_known(self):
        agg = aggregate_season(
            [match(date="2026-09-01 12:00:00")], 2026,
            cutoff=datetime(2026, 9, 1, 18, 0, tzinfo=UTC))
        self.assertEqual(agg.averages["Inter"]["matches"], 1)

    def test_date_only_excludes_whole_day(self):
        """Senza orario affidabile si esclude conservativamente tutto il giorno
        della previsione."""
        agg = aggregate_season(
            [match(date="2026-09-01")], 2026,
            cutoff=datetime(2026, 9, 1, 23, 59, tzinfo=UTC))
        self.assertEqual(agg.averages, {})
        self.assertEqual(agg.skipped.get("stesso_giorno_o_dopo_cutoff"), 1)

    def test_date_only_previous_day_included(self):
        agg = aggregate_season(
            [match(date="2026-08-31")], 2026,
            cutoff=datetime(2026, 9, 1, 0, 1, tzinfo=UTC))
        self.assertEqual(agg.averages["Inter"]["matches"], 1)

    def test_midnight_timestamp_treated_as_day_only(self):
        agg = aggregate_season(
            [match(date="2026-09-01 00:00:00")], 2026,
            cutoff=datetime(2026, 9, 1, 20, 0, tzinfo=UTC))
        self.assertEqual(agg.averages, {})

    def test_naive_cutoff_uses_archive_timezone(self):
        aware = aggregate_season([match(date="2026-09-01 12:00:00")], 2026,
                                 cutoff=datetime(2026, 9, 1, 18, 0, tzinfo=UTC))
        naive = aggregate_season([match(date="2026-09-01 12:00:00")], 2026,
                                 cutoff=datetime(2026, 9, 1, 18, 0))
        self.assertEqual(aware.averages, naive.averages)

    def test_cutoff_respects_explicit_offset(self):
        """Kickoff 12:00 UTC con cutoff 13:00+02:00 (= 11:00 UTC): esclusa."""
        agg = aggregate_season([match(date="2026-09-01 12:00:00")], 2026,
                               cutoff="2026-09-01T13:00:00+02:00")
        self.assertEqual(agg.averages, {})

    def test_unreadable_date_excluded_when_cutoff_set(self):
        agg = aggregate_season([match(date="data rotta")], 2026,
                               cutoff="2026-09-01T00:00:00+00:00")
        self.assertEqual(agg.averages, {})
        self.assertEqual(agg.skipped.get("data_illeggibile_con_cutoff"), 1)

    def test_unreadable_date_allowed_without_cutoff(self):
        agg = aggregate_season([match(date="data rotta")], 2026)
        self.assertEqual(agg.averages["Inter"]["matches"], 1)

    def test_parse_kickoff_has_time_flag(self):
        self.assertEqual(parse_kickoff("2026-09-01")[1], False)
        self.assertEqual(parse_kickoff("2026-09-01 00:00:00")[1], False)
        self.assertEqual(parse_kickoff("2026-09-01 18:30:00")[1], True)
        self.assertEqual(parse_kickoff("2026-09-01T18:30:00Z")[1], True)
        self.assertEqual(parse_kickoff(None), (None, False))

    def test_cutoff_never_uses_end_of_season_totals(self):
        """Il cutoff ricalcola le medie sulle sole partite passate: non e' un
        filtro applicato al totale di fine stagione."""
        records = [match(mid=i, date=f"2026-09-{i:02d} 18:00:00",
                         home="Inter", away="Torino", home_xg=float(i), away_xg=1.0)
                   for i in range(1, 6)]
        full = aggregate_season(records, 2026)
        partial = aggregate_season(records, 2026, cutoff="2026-09-03T00:00:00+00:00")
        self.assertEqual(full.averages["Inter"]["matches"], 5)
        self.assertEqual(partial.averages["Inter"]["matches"], 2)
        self.assertEqual(partial.averages["Inter"]["xG_avg"], 1.5)  # (1+2)/2


# ---------------------------------------------------------------------------
# 8. Acquisizione: fallimento senza sovrascrittura
# ---------------------------------------------------------------------------
class TestAcquisitionSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="xg-acq-")
        self.path = os.path.join(self.tmp, ARCHIVE_FILES["Serie A"])
        self.valid = [match(mid=i, date=f"2026-08-{(i % 28) + 1:02d} 18:00:00")
                      for i in range(200)]
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.valid, f)
        self.before = open(self.path, encoding="utf-8").read()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, fetcher):
        return update_all_xg_db.update_league(
            "Serie A", ["2627"], self.tmp, fetcher=fetcher)

    def test_download_error_keeps_previous_archive(self):
        def boom(*_a, **_k):
            raise RuntimeError("understat irraggiungibile")
        res = self._run(boom)
        self.assertFalse(res["written"])
        self.assertTrue(res["errors"])
        self.assertEqual(open(self.path, encoding="utf-8").read(), self.before)

    def test_empty_download_keeps_previous_archive(self):
        res = self._run(lambda *_a, **_k: [])
        self.assertFalse(res["written"])
        self.assertEqual(open(self.path, encoding="utf-8").read(), self.before)

    def test_partial_download_rejected(self):
        partial = self.valid[:150]  # -25% di partite
        res = self._run(lambda *_a, **_k: partial)
        self.assertFalse(res["written"])
        self.assertTrue(any("scrape parziale" in e for e in res["errors"]))
        self.assertEqual(open(self.path, encoding="utf-8").read(), self.before)

    def test_invalid_records_rejected(self):
        broken = [dict(m) for m in self.valid]
        broken[0].pop("home_xg")
        res = self._run(lambda *_a, **_k: broken)
        self.assertFalse(res["written"])
        self.assertEqual(open(self.path, encoding="utf-8").read(), self.before)

    def test_valid_download_is_written_atomically(self):
        new = self.valid + [match(mid=999, date="2026-09-01 18:00:00")]
        res = self._run(lambda *_a, **_k: new)
        self.assertTrue(res["written"])
        self.assertEqual(len(json.load(open(self.path, encoding="utf-8"))), len(new))
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_main_returns_nonzero_on_failure(self):
        def boom(*_a, **_k):
            raise RuntimeError("ko")
        original = update_all_xg_db.fetch_league
        update_all_xg_db.fetch_league = boom
        try:
            rc = update_all_xg_db.main(
                ["--league", "Serie A", "--output-dir", self.tmp])
        finally:
            update_all_xg_db.fetch_league = original
        self.assertEqual(rc, 1)
        self.assertEqual(open(self.path, encoding="utf-8").read(), self.before)

    def test_records_from_schedule_maps_soccerdata_columns(self):
        """Formato verificato su soccerdata 1.9.1: colonne di read_schedule()
        e tipi pandas nullable -> JSON nativo (NA -> null, non 0)."""
        df = pd.DataFrame([
            {"league": "ITA-Serie A", "season": "2627", "season_id": 2026,
             "game_id": 1, "date": "2026-08-20 18:00:00", "home_team": "Inter",
             "away_team": "Torino", "home_goals": 2, "away_goals": 1,
             "home_xg": 1.8, "away_xg": 0.9, "is_result": True},
            {"league": "ITA-Serie A", "season": "2627", "season_id": 2026,
             "game_id": 2, "date": "2027-05-20 18:00:00", "home_team": "Milan",
             "away_team": "Roma", "home_goals": None, "away_goals": None,
             "home_xg": None, "away_xg": None, "is_result": False},
        ]).convert_dtypes()
        records = update_all_xg_db.records_from_schedule(df)
        self.assertEqual(records[0]["season"], 2026)
        self.assertEqual(records[0]["home_xg"], 1.8)
        self.assertIs(records[0]["is_result"], True)
        self.assertIsNone(records[1]["home_xg"])  # NA non diventa 0
        self.assertIsNone(records[1]["home_goals"])
        json.dumps(records)  # deve essere serializzabile

    def test_records_from_schedule_missing_columns(self):
        df = pd.DataFrame([{"game_id": 1}])
        with self.assertRaises(ValueError):
            update_all_xg_db.records_from_schedule(df)


# ---------------------------------------------------------------------------
# 9. Derivazione delle medie: scrittura sicura
# ---------------------------------------------------------------------------
class TestDeriveAverages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="xg-der-")
        self.arch = os.path.join(self.tmp, ARCHIVE_FILES["Serie A"])
        self.out = os.path.join(self.tmp, "xg_serie_a.json")
        with open(self.out, "w", encoding="utf-8") as f:
            json.dump({"Inter": {"xG_avg": 1.0, "xGA_avg": 1.0, "matches": 10}}, f)
        self.before = open(self.out, encoding="utf-8").read()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_archive(self, records):
        with open(self.arch, "w", encoding="utf-8") as f:
            json.dump(records, f)

    def test_missing_archive_keeps_previous_averages(self):
        res = update_xg.derive_league("Serie A", 2026, database_dir=self.tmp)
        self.assertFalse(res["written"])
        self.assertTrue(res["errors"])
        self.assertEqual(open(self.out, encoding="utf-8").read(), self.before)

    def test_too_few_teams_keeps_previous_averages(self):
        self._write_archive([match(mid=1)])
        res = update_xg.derive_league("Serie A", 2026, database_dir=self.tmp)
        self.assertFalse(res["written"])
        self.assertEqual(open(self.out, encoding="utf-8").read(), self.before)

    def test_writes_when_enough_teams(self):
        teams = [f"Team{i}" for i in range(20)]
        records = [match(mid=i, home=teams[i], away=teams[i + 1],
                         date=f"2026-08-{i + 1:02d} 18:00:00")
                   for i in range(0, 19, 2)]
        self._write_archive(records)
        res = update_xg.derive_league("Serie A", 2026, database_dir=self.tmp)
        self.assertTrue(res["written"], res["errors"])
        data = json.load(open(self.out, encoding="utf-8"))
        self.assertEqual(len(data), 20)
        self.assertTrue(all({"xG_avg", "xGA_avg", "matches"} <= set(v)
                            for v in data.values()))

    def test_dry_run_writes_nothing(self):
        teams = [f"Team{i}" for i in range(20)]
        records = [match(mid=i, home=teams[i], away=teams[i + 1],
                         date=f"2026-08-{i + 1:02d} 18:00:00")
                   for i in range(0, 19, 2)]
        self._write_archive(records)
        res = update_xg.derive_league("Serie A", 2026, database_dir=self.tmp,
                                      dry_run=True)
        self.assertFalse(res["written"])
        self.assertEqual(open(self.out, encoding="utf-8").read(), self.before)


# ---------------------------------------------------------------------------
# 10. Dati reali del repository (5 leghe)
# ---------------------------------------------------------------------------
class TestRealArchives(unittest.TestCase):
    def test_every_archive_name_resolves_to_a_csv_team(self):
        """Ogni titolo Understat presente negli archivi deve risolversi in un
        nome usato dai CSV della stessa stagione (nomi del motore live)."""
        for league in LEAGUES:
            records = load_archive(league)
            by_season = {}
            for rec in records:
                season = parse_season(rec.get("season"))
                for key in ("home_team", "away_team"):
                    if rec.get(key):
                        by_season.setdefault(season, set()).add(str(rec[key]))
            for season, titles in sorted(by_season.items()):
                prefix = LEAGUE_PREFIX[league]
                name = f"{prefix}_Live.csv" if season >= 2026 else f"{prefix}_{season}.csv"
                path = os.path.join(DB_DIR, name)
                if not os.path.exists(path):
                    continue
                df = pd.read_csv(path, low_memory=False)
                csv_teams = {clean_name(t) for t in df["HomeTeam"].dropna()} | \
                            {clean_name(t) for t in df["AwayTeam"].dropna()}
                unresolved = sorted(t for t in titles
                                    if canonical_team_name(t) not in csv_teams)
                self.assertEqual(unresolved, [],
                                 f"{league} {season}: nomi non risolti {unresolved}")

    def test_no_name_collisions_per_season(self):
        for league in LEAGUES:
            by_season = {}
            for rec in load_archive(league):
                season = parse_season(rec.get("season"))
                for key in ("home_team", "away_team"):
                    if rec.get(key):
                        by_season.setdefault(season, set()).add(str(rec[key]))
            for season, titles in by_season.items():
                seen = {}
                for title in titles:
                    canonical = canonical_team_name(title)
                    self.assertNotIn(
                        canonical, seen,
                        f"{league} {season}: collisione {title} / {seen.get(canonical)}"
                        f" -> {canonical}")
                    seen[canonical] = title

    def test_real_archives_pass_validation(self):
        for league in LEAGUES:
            problems = validate_archive(load_archive(league), league=league,
                                        min_matches=100)
            self.assertEqual(problems, [], f"{league}: {problems}")

    def test_derived_averages_cover_current_season_teams(self):
        from config import CURRENT_SEASON_START_YEAR
        for league in LEAGUES:
            agg = season_averages(league, CURRENT_SEASON_START_YEAR)
            self.assertGreaterEqual(len(agg.averages), 10, league)
            for team, rec in agg.averages.items():
                self.assertGreater(rec["matches"], 0, f"{league}/{team}")
                self.assertTrue(0 <= rec["xG_avg"] < 10, f"{league}/{team}")
                self.assertTrue(0 <= rec["xGA_avg"] < 10, f"{league}/{team}")
            self.assertEqual(agg.unmapped_names, {}, league)
            self.assertEqual(agg.conflicts, [], league)

    def test_cutoff_on_real_archive_is_monotone(self):
        """Con cutoff crescente il numero di partite incluse non diminuisce e
        non supera mai il totale di fine stagione."""
        league = "Premier League"
        records = load_archive(league)
        full = aggregate_season(records, 2025, league=league)
        early = aggregate_season(records, 2025, league=league,
                                 cutoff="2025-10-01T00:00:00+00:00")
        late = aggregate_season(records, 2025, league=league,
                                cutoff="2026-03-01T00:00:00+00:00")
        self.assertLess(early.matches_used, late.matches_used)
        self.assertLess(late.matches_used, full.matches_used)
        for team, rec in early.averages.items():
            self.assertLessEqual(rec["matches"], full.averages[team]["matches"])


# ---------------------------------------------------------------------------
# 11. Lettura live: get_league_engine riceve nomi, stagione e matches corretti
# ---------------------------------------------------------------------------
class TestLiveEngineIntegration(unittest.TestCase):
    def test_published_files_match_the_archive(self):
        """I file xg_<lega>.json committati devono essere esattamente il
        prodotto derivato dell'archivio per la stagione corrente."""
        from config import CURRENT_SEASON_START_YEAR
        for league in LEAGUES:
            path = os.path.join(DB_DIR, os.path.basename(
                str(LEAGUES_CONFIG[league]["xg_json"])))
            with open(path, encoding="utf-8") as f:
                published = json.load(f)
            derived = season_averages(league, CURRENT_SEASON_START_YEAR).averages
            self.assertEqual(published, derived, league)

    def test_engine_resolves_every_published_team(self):
        """Ogni squadra del file xG deve esistere fra le chiavi dell'engine
        (nomi canonici) e il record deve avere un 'matches' > 0."""
        import app
        from scraper_xg import get_understat_xg
        for league in LEAGUES:
            xg = get_understat_xg(league)
            self.assertIsNotNone(xg, league)
            try:
                app.get_league_engine.clear()
            except Exception:
                pass
            engine = app.get_league_engine(league)
            self.assertIsNotNone(engine, league)
            stats = engine[0]
            missing = sorted(t for t in xg if t not in stats)
            self.assertEqual(missing, [],
                             f"{league}: squadre del file xG assenti dall'engine: {missing}")
            for team, rec in xg.items():
                self.assertIsInstance(rec.get("matches"), int, f"{league}/{team}")
                self.assertGreater(rec["matches"], 0, f"{league}/{team}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
