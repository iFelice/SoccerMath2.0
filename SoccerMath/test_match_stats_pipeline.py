"""
test_match_stats_pipeline.py - Test offline della pipeline PPDA/deep + giocatore.

Copre, senza rete (i DataFrame di soccerdata sono ricostruiti a mano):
  * conversione calendario -> perimetro e dei due DataFrame in record JSON;
  * schema: campi mancanti, chiavi duplicate, valori non validi, soglie di
    copertura PPDA/deep e di roster "sottile";
  * confronto partita-per-partita con l'ultimo valido: partite concluse sparite
    e stagioni sparite bloccano, partite nuove/correzioni/frontiera no;
  * scrittura atomica e rifiuto di scrivere dentro l'archivio xG;
  * flusso completo di acquisizione con un lettore finto: file scritti solo se
    validi, nessuna sovrascrittura quando la lega fallisce, `--dry-run`;
  * resolver dei nomi condiviso (nessuna tabella nuova) e conteggi di copertura.

Esecuzione:
    python -m pytest SoccerMath/test_match_stats_pipeline.py -v
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _REPO_ROOT)

import pandas as pd  # noqa: E402

import update_all_ppda_player_db as acquisition  # noqa: E402
from match_stats_archive import (  # noqa: E402
    PLAYER_KIND,
    PPDA_KIND,
    archive_files,
    compare_player_snapshots,
    compare_ppda_snapshots,
    coverage_against_perimeter,
    load_player,
    load_ppda,
    name_resolution_report,
    parse_minutes,
    parse_ppda,
    player_summary,
    ppda_summary,
    record_completeness,
    validate_player,
    validate_ppda,
    write_atomic,
)
from xg_archive import ARCHIVE_FILES  # noqa: E402

UTC = timezone.utc


def schedule_frame(rows):
    """DataFrame con l'indice che soccerdata usa per read_schedule()."""
    frame = pd.DataFrame(rows)
    return frame.set_index(["league", "season", "game"])


def team_stats_frame(rows):
    frame = pd.DataFrame(rows)
    return frame.set_index(["league", "season", "game"])


def player_stats_frame(rows):
    frame = pd.DataFrame(rows)
    return frame.set_index(["league", "season", "game", "team", "player"])


def schedule_row(season_id, game_id, date, home, away, home_xg, away_xg,
                 is_result=True):
    return {
        "league": "ITA-Serie A", "season": f"{season_id}-{season_id + 1}",
        "game": f"{date[:10]} {home}-{away}", "season_id": season_id,
        "game_id": game_id, "date": pd.Timestamp(date),
        "home_team": home, "away_team": away,
        "home_xg": home_xg, "away_xg": away_xg, "is_result": is_result,
    }


def team_stats_row(season_id, game_id, date, home, away, home_ppda, away_ppda,
                   home_deep, away_deep):
    return {
        "league": "ITA-Serie A", "season": f"{season_id}-{season_id + 1}",
        "game": f"{date[:10]} {home}-{away}", "season_id": season_id,
        "game_id": game_id, "date": pd.Timestamp(date),
        "home_team": home, "away_team": away,
        "home_ppda": home_ppda, "away_ppda": away_ppda,
        "home_deep_completions": home_deep, "away_deep_completions": away_deep,
    }


def player_stats_row(season_id, game_id, date, team, player, player_id, *,
                     minutes=90, home="Inter", away="Torino"):
    return {
        "league": "ITA-Serie A", "season": f"{season_id}-{season_id + 1}",
        "game": f"{date[:10]} {home}-{away}", "season_id": season_id,
        "game_id": game_id, "team": team, "player": player, "player_id": player_id,
        "position": "FW", "minutes": minutes, "goals": 1, "own_goals": 0,
        "shots": 2, "xg": 0.45, "xg_chain": 0.7, "xg_buildup": 0.3,
        "assists": 0, "xa": 0.1, "key_passes": 1, "yellow_cards": 0, "red_cards": 0,
        "date": pd.Timestamp(date),
    }


class FakeReader:
    """Sostituto di ``soccerdata.Understat`` per i test offline."""

    def __init__(self, schedule=None, team_stats=None, player_stats=None,
                 fail_team_stats=False, fail_players=False):
        self.schedule = schedule
        self.team_stats = team_stats
        self.player_stats = player_stats
        self.fail_team_stats = fail_team_stats
        self.fail_players = fail_players
        self.calls = []

    def read_schedule(self, *args, **kwargs):
        self.calls.append("read_schedule")
        return self.schedule

    def read_team_match_stats(self, *args, **kwargs):
        self.calls.append("read_team_match_stats")
        if self.fail_team_stats:
            raise RuntimeError("download fallito (simulato)")
        return self.team_stats

    def read_player_match_stats(self, match_id=None):
        self.calls.append("read_player_match_stats")
        if self.fail_players:
            raise RuntimeError("download fallito (simulato)")
        if self.player_stats is None:
            return player_stats_frame([])
        if match_id is None:
            return self.player_stats
        wanted = {match_id} if isinstance(match_id, int) else set(match_id)
        frame = self.player_stats.reset_index()
        return frame[frame["game_id"].isin(wanted)].set_index(
            ["league", "season", "game", "team", "player"])


class TestConversions(unittest.TestCase):
    def test_perimeter_from_schedule(self):
        frame = schedule_frame([
            schedule_row(2022, 1, "2022-08-13 18:45:00", "Inter", "Torino", 2.4, 0.7),
            schedule_row(2022, 2, "2022-08-14 18:45:00", "Milan", "Roma", 1.1, 1.2),
            # non giocata: xG assenti -> fuori dal perimetro
            schedule_row(2022, 3, "2022-08-20 18:45:00", "Napoli", "Lazio", None, None,
                         is_result=False),
            # conclusa ma con un xG mancante -> fuori dal perimetro
            schedule_row(2022, 4, "2022-08-21 18:45:00", "Inter", "Milan", 1.0, None),
        ])
        records = acquisition.perimeter_from_schedule(frame)
        self.assertEqual(len(records), 4)
        perimeter = acquisition.played_perimeter(records)
        self.assertEqual([rec["id"] for rec in perimeter], [1, 2])
        self.assertEqual(records[0]["date"], "2022-08-13 18:45:00")
        self.assertTrue(records[0]["both_xg"])
        self.assertFalse(records[3]["both_xg"])

    def test_records_from_team_match_stats_join_and_one_sided(self):
        schedule = acquisition.perimeter_from_schedule(schedule_frame([
            schedule_row(2022, 1, "2022-08-13 18:45:00", "Inter", "Torino", 2.4, 0.7),
            schedule_row(2022, 2, "2022-08-14 18:45:00", "Milan", "Roma", 1.1, 1.2),
        ]))
        frame = team_stats_frame([
            team_stats_row(2022, 1, "2022-08-13 18:45:00", "Inter", "Torino",
                           8.13, 11.2, 12, 5),
            # storico presente solo per un lato (caso reale: una squadra non
            # ancora aggiornata) -> valori del lato ospite a None, non a 0
            team_stats_row(2022, 2, "2022-08-14 18:45:00", "Milan", "Roma",
                           9.5, None, 7, None),
        ])
        records = acquisition.records_from_team_match_stats(frame, schedule)
        self.assertEqual(len(records), 2)
        self.assertTrue(records[0]["is_result"])
        self.assertEqual(record_completeness(records[0]), "completo")
        self.assertEqual(record_completeness(records[1]), "parziale")
        self.assertIsNone(records[1]["away_ppda"])
        self.assertIsNone(records[1]["away_deep_completions"])

    def test_records_from_player_match_stats_dates_and_sides(self):
        schedule = acquisition.perimeter_from_schedule(schedule_frame([
            schedule_row(2022, 1, "2022-08-13 18:45:00", "Inter", "Torino", 2.4, 0.7),
        ]))
        frame = player_stats_frame([
            player_stats_row(2022, 1, "2022-08-13 18:45:00", "Inter", "Lautaro", 1,
                             minutes=90, home="Inter", away="Torino"),
            player_stats_row(2022, 1, "2022-08-13 18:45:00", "Torino", "Sanabria", 2,
                             minutes=0, home="Inter", away="Torino"),
        ])
        records = acquisition.records_from_player_match_stats(frame, schedule)
        self.assertEqual(len(records), 2)
        home = [rec for rec in records if rec["team"] == "Inter"][0]
        away = [rec for rec in records if rec["team"] == "Torino"][0]
        self.assertEqual(home["venue"], "home")
        self.assertEqual(home["opponent"], "Torino")
        self.assertEqual(away["venue"], "away")
        self.assertEqual(away["opponent"], "Inter")
        self.assertEqual(home["date"], "2022-08-13")
        self.assertFalse(home["date_mismatch"])
        self.assertEqual(away["minutes"], 0)

    def test_player_rows_without_schedule_reference_are_flagged(self):
        schedule = acquisition.perimeter_from_schedule(schedule_frame([
            schedule_row(2022, 1, "2022-08-13 18:45:00", "Inter", "Torino", 2.4, 0.7),
        ]))
        frame = player_stats_frame([
            player_stats_row(2022, 99, "2022-08-13 18:45:00", "Inter", "Lautaro", 1),
        ])
        records = acquisition.records_from_player_match_stats(
            frame, schedule, match_ids=[99])
        self.assertIsNone(records[0]["venue"])
        self.assertIsNone(records[0]["opponent"])
        problems = validate_player(records, league="Serie A", min_rows=1)
        self.assertTrue(any("venue" in problem for problem in problems))


class TestValidation(unittest.TestCase):
    def setUp(self):
        self.records = [
            acquisition.normalize_ppda_record({
                "season": 2022, "id": 1, "date": "2022-08-13 18:45:00",
                "home_team": "Inter", "away_team": "Torino", "is_result": True,
                "home_ppda": 8.13, "away_ppda": 11.2,
                "home_deep_completions": 12, "away_deep_completions": 5}),
        ]

    def test_valid_record_passes(self):
        self.assertEqual(validate_ppda(self.records, league="Serie A", min_matches=1),
                         [])

    def test_missing_field_and_duplicates_block(self):
        broken = [dict(self.records[0])]
        broken[0].pop("away_ppda")
        problems = validate_ppda(broken, league="Serie A", min_matches=1)
        self.assertTrue(any("campi richiesti" in problem for problem in problems))
        duplicated = self.records + self.records
        problems = validate_ppda(duplicated, league="Serie A", min_matches=1)
        self.assertTrue(any("duplicate" in problem for problem in problems))

    def test_negative_and_non_finite_values_block(self):
        bad = [dict(self.records[0])]
        bad[0]["home_ppda"] = -1.0
        bad[0]["away_deep_completions"] = float("nan")
        problems = validate_ppda(bad, league="Serie A", min_matches=1)
        self.assertTrue(any("non validi" in problem for problem in problems))

    def test_played_field_coverage_blocks_below_threshold(self):
        records = [dict(self.records[0])]
        empty = dict(self.records[0])
        empty.update({"id": 2, "home_ppda": None, "away_ppda": None,
                      "home_deep_completions": None, "away_deep_completions": None})
        records.append(empty)
        forced = [dict(record) for record in records]
        for record in forced:
            record.pop("home_ppda")
            record.pop("away_ppda")
            record.pop("home_deep_completions")
            record.pop("away_deep_completions")
            record.update({"home_ppda": None, "away_ppda": None,
                           "home_deep_completions": None,
                           "away_deep_completions": None})
        problems = validate_ppda(records, league="Serie A", min_matches=1,
                                 min_played_field_coverage=0.95)
        self.assertTrue(any("copertura PPDA/deep" in problem for problem in problems))
        # con una soglia realistica il file parziale ma sotto soglia passa
        self.assertEqual(validate_ppda(records, league="Serie A", min_matches=1,
                                       min_played_field_coverage=0.5), [])

    def test_expected_seasons_block(self):
        problems = validate_ppda(self.records, league="Serie A", min_matches=1,
                                 expected_seasons=[2022, 2023])
        self.assertTrue(any("stagioni assenti" in problem for problem in problems))

    def test_player_validation_thin_rosters_and_minutes(self):
        rows = [acquisition.normalize_player_record({
            "season": 2022, "id": 1, "date": "2022-08-13", "team": "Inter",
            "opponent": "Torino", "venue": "home", "player_id": 10,
            "player": "Lautaro", "position": "FW", "minutes": 90,
        })]
        self.assertEqual(validate_player(rows, league="Serie A", min_rows=1,
                                         max_thin_matches_ratio=1.0), [])
        thin = rows + [acquisition.normalize_player_record({
            "season": 2022, "id": 2, "date": "2022-08-14", "team": "Inter",
            "opponent": "Torino", "venue": "home", "player_id": 11,
            "player": "Barella", "position": "MF", "minutes": 45,
        })]
        problems = validate_player(thin, league="Serie A", min_rows=1,
                                   max_thin_matches_ratio=0.0)
        self.assertTrue(any("righe giocatore" in problem for problem in problems))

    def test_minutes_and_ppda_parsers(self):
        self.assertEqual(parse_minutes(0), 0)
        self.assertIsNone(parse_minutes(None))
        self.assertIsNone(parse_minutes(-1))
        self.assertIsNone(parse_minutes(500))
        self.assertEqual(parse_ppda(0.0), 0.0)
        self.assertIsNone(parse_ppda(float("inf")))
        self.assertIsNone(parse_ppda(1001))

    def test_summaries_count_seasons(self):
        summary = ppda_summary(self.records)
        self.assertEqual(summary["matches"], 1)
        self.assertEqual(summary["seasons"]["2022"]["complete"], 1)


class TestSnapshots(unittest.TestCase):
    def _ppda(self, match_id, home_ppda=8.0, away_ppda=9.0, played=True,
              season=2022):
        return acquisition.normalize_ppda_record({
            "season": season, "id": match_id, "date": "2022-08-13 18:45:00",
            "home_team": "Inter", "away_team": "Torino", "is_result": played,
            "home_ppda": home_ppda, "away_ppda": away_ppda,
            "home_deep_completions": 5, "away_deep_completions": 6})

    def test_lost_played_match_blocks(self):
        diff = compare_ppda_snapshots([self._ppda(1)], [], league="Serie A")
        self.assertEqual(len(diff.missing_played), 1)
        self.assertTrue(diff.blocking_problems)

    def test_dropped_unplayed_is_reported_not_blocking(self):
        previous = [self._ppda(1, home_ppda=None, away_ppda=None, played=False)]
        diff = compare_ppda_snapshots(previous, [], league="Serie A")
        self.assertEqual(len(diff.dropped_unplayed), 1)
        self.assertEqual(diff.blocking_problems, [])

    def test_corrections_and_new_matches_are_allowed(self):
        previous = [self._ppda(1, home_ppda=8.0)]
        current = [self._ppda(1, home_ppda=8.5), self._ppda(2)]
        diff = compare_ppda_snapshots(previous, current, league="Serie A")
        self.assertEqual(len(diff.corrections), 1)
        self.assertEqual(len(diff.new_matches), 1)
        self.assertEqual(diff.blocking_problems, [])

    def test_season_disappearance_blocks_unless_declared(self):
        previous = [self._ppda(1, season=2022), self._ppda(2, season=2023)]
        current = [self._ppda(1, season=2022)]
        diff = compare_ppda_snapshots(previous, current, league="Serie A",
                                      requested_seasons=[2022])
        self.assertEqual(diff.dropped_seasons, [2023])
        declared = compare_ppda_snapshots(previous, current, league="Serie A",
                                          requested_seasons=[2022],
                                          allow_dropping_seasons=True)
        self.assertEqual(declared.dropped_seasons, [])
        self.assertEqual(declared.blocking_problems, [])

    def test_lost_side_blocks_and_partial_to_complete_is_allowed(self):
        previous = [self._ppda(1, away_ppda=None)]
        current = [self._ppda(1)]
        diff = compare_ppda_snapshots(previous, current, league="Serie A")
        self.assertEqual(len(diff.improved), 1)
        self.assertEqual(diff.blocking_problems, [])
        lost = compare_ppda_snapshots([self._ppda(1)], [self._ppda(1, away_ppda=None)],
                                     league="Serie A")
        self.assertEqual(len(lost.regressed), 1)
        self.assertIn("away_ppda", lost.regressed[0])
        self.assertTrue(lost.blocking_problems)

    def test_player_snapshot_frontier_and_collapse(self):
        now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
        old_match = "2022-08-13"
        recent = "2026-09-15"

        def rows(match_id, date, count, season=2022):
            return [acquisition.normalize_player_record({
                "season": season, "id": match_id, "date": date, "team": "Inter",
                "opponent": "Torino", "venue": "home", "player_id": 100 + index,
                "player": f"Giocatore {index}", "position": "FW", "minutes": 90})
                for index in range(count)]

        previous = rows(1, old_match, 12) + rows(2, recent, 12, season=2026)
        current = rows(1, old_match, 12) + rows(2, recent, 11, season=2026)
        diff = compare_player_snapshots(previous, current, league="Serie A",
                                        frontier_days=1.0, now=now)
        self.assertEqual(diff.missing_matches, [])
        self.assertEqual(len(diff.shrunk_matches), 1)
        self.assertEqual(diff.blocking_problems, [])

        # partita vecchia sparita: bloccante; partita di frontiera sparita: no
        missing_old = compare_player_snapshots(previous, rows(2, recent, 12, season=2026),
                                              league="Serie A", frontier_days=1.0,
                                              now=now)
        self.assertEqual(len(missing_old.missing_matches), 1)
        self.assertTrue(missing_old.blocking_problems)
        missing_frontier = compare_player_snapshots(previous, rows(1, old_match, 12),
                                                   league="Serie A", frontier_days=1.0,
                                                   now=now)
        self.assertEqual(len(missing_frontier.frontier_missing_matches), 1)
        self.assertEqual(missing_frontier.blocking_problems, [])

    def test_player_collapse_blocks(self):
        now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)

        def rows(count):
            return [acquisition.normalize_player_record({
                "season": 2022, "id": 1, "date": "2022-08-13", "team": "Inter",
                "opponent": "Torino", "venue": "home", "player_id": 100 + index,
                "player": f"Giocatore {index}", "position": "FW", "minutes": 90})
                for index in range(count)]

        diff = compare_player_snapshots(rows(20), rows(5), league="Serie A",
                                        frontier_days=1.0, now=now)
        self.assertEqual(len(diff.collapsed_matches), 1)
        self.assertTrue(diff.blocking_problems)


class TestArchiveSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="match-stats-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_write_atomic_refuses_xg_archive_names(self):
        for name in list(ARCHIVE_FILES.values()) + ["xg_serie_a.json"]:
            with self.assertRaises(ValueError):
                write_atomic(os.path.join(self.tmp, name), [])

    def test_write_atomic_and_load_roundtrip(self):
        records = [{"season": 2022, "id": 1}]
        path = os.path.join(self.tmp, "ppda_deep_serie_a.json")
        write_atomic(path, records)
        self.assertTrue(os.path.exists(path))
        self.assertFalse(os.path.exists(path + ".tmp"))
        self.assertEqual(load_ppda("Serie A", self.tmp), records)
        self.assertEqual(len(archive_files(PPDA_KIND)), 5)
        self.assertEqual(len(archive_files(PLAYER_KIND)), 5)
        self.assertEqual(os.path.basename(archive_files(PPDA_KIND)["Ligue 1"]),
                         "ppda_deep_ligue_1.json")

    def test_coverage_against_perimeter(self):
        perimeter = [{"season": 2022, "id": 1, "date": "2022-08-13"},
                     {"season": 2022, "id": 2, "date": "2022-08-14"}]
        records = [acquisition.normalize_ppda_record({
            "season": 2022, "id": 1, "date": "2022-08-13 18:45:00",
            "home_team": "Inter", "away_team": "Torino", "is_result": True,
            "home_ppda": 8.0, "away_ppda": 9.0,
            "home_deep_completions": 5, "away_deep_completions": 6})]
        coverage = coverage_against_perimeter(records, perimeter, kind=PPDA_KIND)
        self.assertEqual(coverage["reference_matches"], 2)
        self.assertEqual(coverage["present_matches"], 1)
        bucket = coverage["seasons"]["2022"]
        self.assertEqual(bucket["complete"], 1)
        self.assertEqual(bucket["missing_matches_total"], 1)
        self.assertEqual(bucket["missing_matches"][0]["id"], 2)

    def test_name_resolution_uses_shared_resolver(self):
        records = [acquisition.normalize_ppda_record({
            "season": 2022, "id": 1, "date": "2022-08-13 18:45:00",
            "home_team": "Inter", "away_team": "Torino", "is_result": True,
            "home_ppda": 8.0, "away_ppda": 9.0,
            "home_deep_completions": 5, "away_deep_completions": 6})]
        report = name_resolution_report(records, kind=PPDA_KIND)
        self.assertEqual(report["raw_names"], 2)
        self.assertEqual(report["unmapped"], {})
        unknown = [dict(records[0], home_team="Squadra Inesistente")]
        report = name_resolution_report(unknown, kind=PPDA_KIND)
        self.assertIn("Squadra Inesistente", report["unmapped"])


class TestAcquisitionFlow(unittest.TestCase):
    """Flusso completo con un lettore finto: nessuna rete, nessuna sorpresa."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="match-stats-flow-")
        self.out = os.path.join(self.tmp, "out")
        self.baseline = os.path.join(self.tmp, "baseline")
        os.makedirs(self.out)
        os.makedirs(self.baseline)
        # 3 partite concluse + 1 non giocata
        self.schedule_rows = [
            schedule_row(2022, 1, "2022-08-13 18:45:00", "Inter", "Torino", 2.4, 0.7),
            schedule_row(2022, 2, "2022-08-20 18:45:00", "Roma", "Milan", 1.2, 1.1),
            schedule_row(2022, 3, "2022-08-27 18:45:00", "Napoli", "Inter", 0.9, 1.4),
            schedule_row(2022, 4, "2022-09-03 18:45:00", "Torino", "Roma", None, None,
                         is_result=False),
        ]
        self.team_stats_rows = [
            team_stats_row(2022, 1, "2022-08-13 18:45:00", "Inter", "Torino", 8.0, 9.0, 5, 6),
            team_stats_row(2022, 2, "2022-08-20 18:45:00", "Roma", "Milan", 7.5, 10.5, 4, 3),
            team_stats_row(2022, 3, "2022-08-27 18:45:00", "Napoli", "Inter", 11.0, 8.2, 6, 7),
        ]
        self.player_rows = [
            player_stats_row(2022, 1, "2022-08-13 18:45:00", "Inter", "Lautaro", 1,
                             minutes=90, home="Inter", away="Torino"),
            player_stats_row(2022, 1, "2022-08-13 18:45:00", "Torino", "Sanabria", 2,
                             minutes=0, home="Inter", away="Torino"),
            player_stats_row(2022, 2, "2022-08-20 18:45:00", "Roma", "Dybala", 3,
                             minutes=80, home="Roma", away="Milan"),
            player_stats_row(2022, 3, "2022-08-27 18:45:00", "Napoli", "Osimhen", 4,
                             minutes=90, home="Napoli", away="Inter"),
        ]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _patch_thresholds(self):
        original_match = acquisition.MIN_MATCHES_PER_SEASON
        original_rows = acquisition.MIN_ROWS_PER_SEASON
        acquisition.MIN_MATCHES_PER_SEASON = 1
        acquisition.MIN_ROWS_PER_SEASON = 1
        self.addCleanup(setattr, acquisition, "MIN_MATCHES_PER_SEASON", original_match)
        self.addCleanup(setattr, acquisition, "MIN_ROWS_PER_SEASON", original_rows)

    def _patch_reader(self, **kwargs):
        reader = FakeReader(
            schedule=schedule_frame(self.schedule_rows),
            team_stats=team_stats_frame(self.team_stats_rows),
            player_stats=player_stats_frame(self.player_rows), **kwargs)
        original = acquisition._make_reader
        acquisition._make_reader = lambda *args, **kwargs2: reader
        self.addCleanup(setattr, acquisition, "_make_reader", original)
        return reader

    def test_full_acquisition_writes_both_files(self):
        self._patch_thresholds()
        self._patch_reader()
        outcome = acquisition.acquire_league(
            "Serie A", ["2223"], ["2223"], output_dir=self.out,
            baseline_dir=None, cache_dir=self.tmp, datasets=[PPDA_KIND, PLAYER_KIND],
            dry_run=False, allow_dropping_seasons=False, retries=0,
            frontier_days=1.0, missing_tolerance_ratio=0.0,
            sample_matches=None, min_played_field_coverage=0.95,
            min_rows_per_match=1, max_thin_matches_ratio=1.0)
        self.assertEqual(outcome["errors"], [])
        ppda = outcome["datasets"][PPDA_KIND]
        self.assertTrue(ppda["written"])
        self.assertEqual(ppda["matches"], 3)
        self.assertEqual(ppda["coverage"]["complete"], 3)
        player = outcome["datasets"][PLAYER_KIND]
        self.assertTrue(player["written"])
        self.assertEqual(player["matches"], 3)
        self.assertEqual(player["rows"], 4)
        self.assertTrue(os.path.exists(
            os.path.join(self.out, archive_files(PPDA_KIND)["Serie A"])))
        self.assertTrue(os.path.exists(
            os.path.join(self.out, archive_files(PLAYER_KIND)["Serie A"])))
        # l'archivio xG non e' mai toccato
        for name in ARCHIVE_FILES.values():
            self.assertFalse(os.path.exists(os.path.join(self.out, name)))

    def test_dry_run_does_not_write(self):
        self._patch_thresholds()
        self._patch_reader()
        acquisition.acquire_league(
            "Serie A", ["2223"], ["2223"], output_dir=self.out,
            baseline_dir=None, cache_dir=self.tmp, datasets=[PPDA_KIND],
            dry_run=True, allow_dropping_seasons=False, retries=0,
            frontier_days=1.0, missing_tolerance_ratio=0.0, sample_matches=None,
            min_played_field_coverage=0.95, min_rows_per_match=1,
            max_thin_matches_ratio=1.0)
        self.assertEqual(os.listdir(self.out), [])

    def test_failed_league_keeps_previous_file(self):
        path = os.path.join(self.out, archive_files(PPDA_KIND)["Serie A"])
        previous = [acquisition.normalize_ppda_record({
            "season": 2022, "id": 1, "date": "2022-08-13 18:45:00",
            "home_team": "Inter", "away_team": "Torino", "is_result": True,
            "home_ppda": 8.0, "away_ppda": 9.0,
            "home_deep_completions": 5, "away_deep_completions": 6})]
        write_atomic(path, previous)
        snapshot = json.dumps(previous, sort_keys=True)
        self._patch_thresholds()
        self._patch_reader(fail_team_stats=True)
        outcome = acquisition.acquire_league(
            "Serie A", ["2223"], ["2223"], output_dir=self.out,
            baseline_dir=None, cache_dir=self.tmp, datasets=[PPDA_KIND],
            dry_run=False, allow_dropping_seasons=False, retries=0,
            frontier_days=1.0, missing_tolerance_ratio=0.0, sample_matches=None,
            min_played_field_coverage=0.95, min_rows_per_match=1,
            max_thin_matches_ratio=1.0)
        self.assertTrue(outcome["errors"])
        self.assertFalse(outcome["datasets"][PPDA_KIND]["written"])
        with open(path, "r", encoding="utf-8") as f:
            self.assertEqual(json.dumps(json.load(f), sort_keys=True), snapshot)

    def test_missing_matches_block_and_are_counted(self):
        # il lettore restituisce righe solo per la prima partita: le altre due
        # (vecchie) sono mancanti -> la lega fallisce e non scrive
        self._patch_thresholds()
        reader = FakeReader(
            schedule=schedule_frame(self.schedule_rows),
            team_stats=team_stats_frame(self.team_stats_rows),
            player_stats=player_stats_frame(self.player_rows[:2]))
        original = acquisition._make_reader
        acquisition._make_reader = lambda *args, **kwargs: reader
        self.addCleanup(setattr, acquisition, "_make_reader", original)
        outcome = acquisition.acquire_league(
            "Serie A", ["2223"], ["2223"], output_dir=self.out, baseline_dir=None,
            cache_dir=self.tmp, datasets=[PLAYER_KIND], dry_run=False,
            allow_dropping_seasons=False, retries=0, frontier_days=1.0,
            missing_tolerance_ratio=0.0, sample_matches=None,
            min_played_field_coverage=0.95, min_rows_per_match=1,
            max_thin_matches_ratio=1.0)
        player = outcome["datasets"][PLAYER_KIND]
        self.assertFalse(player["written"])
        self.assertEqual(player["coverage"]["missing_total"], 2)
        self.assertEqual(player["missing_matches"], 2)
        self.assertTrue(any("senza righe giocatore" in err for err in player["errors"]))

    def test_frontier_missing_is_tolerated_and_reported(self):
        self._patch_thresholds()
        today = datetime.now(timezone.utc)
        recent = (today - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
        schedule_rows = [
            schedule_row(2022, 1, "2022-08-13 18:45:00", "Inter", "Torino", 2.4, 0.7),
            schedule_row(2022, 2, recent, "Roma", "Milan", 1.2, 1.1),
        ]
        player_rows = [
            player_stats_row(2022, 1, "2022-08-13 18:45:00", "Inter", "Lautaro", 1),
        ]
        reader = FakeReader(schedule=schedule_frame(schedule_rows),
                            team_stats=team_stats_frame([
                                team_stats_row(2022, 1, "2022-08-13 18:45:00", "Inter",
                                               "Torino", 8.0, 9.0, 5, 6)]),
                            player_stats=player_stats_frame(player_rows))
        original = acquisition._make_reader
        acquisition._make_reader = lambda *args, **kwargs: reader
        self.addCleanup(setattr, acquisition, "_make_reader", original)
        outcome = acquisition.acquire_league(
            "Serie A", ["2223"], ["2223"], output_dir=self.out,
            baseline_dir=None, cache_dir=self.tmp, datasets=[PLAYER_KIND],
            dry_run=False, allow_dropping_seasons=False, retries=0,
            frontier_days=1.0, missing_tolerance_ratio=0.0, sample_matches=None,
            min_played_field_coverage=0.95, min_rows_per_match=1,
            max_thin_matches_ratio=0.5)
        player = outcome["datasets"][PLAYER_KIND]
        self.assertEqual(player["coverage"]["missing_frontier"], 1)
        self.assertEqual(player["coverage"]["missing_old"], 0)
        self.assertFalse(player["errors"])
        self.assertTrue(player["written"])

    def test_baseline_comparison_blocks_losses(self):
        baseline_path = os.path.join(self.baseline,
                                     archive_files(PPDA_KIND)["Serie A"])
        write_atomic(baseline_path, [
            acquisition.normalize_ppda_record({
                "season": 2022, "id": 99, "date": "2022-08-06 18:45:00",
                "home_team": "Inter", "away_team": "Roma", "is_result": True,
                "home_ppda": 8.0, "away_ppda": 9.0,
                "home_deep_completions": 5, "away_deep_completions": 6})])
        self._patch_thresholds()
        self._patch_reader()
        outcome = acquisition.acquire_league(
            "Serie A", ["2223"], ["2223"], output_dir=self.out,
            baseline_dir=self.baseline, cache_dir=self.tmp, datasets=[PPDA_KIND],
            dry_run=False, allow_dropping_seasons=False, retries=0,
            frontier_days=1.0, missing_tolerance_ratio=0.0, sample_matches=None,
            min_played_field_coverage=0.95, min_rows_per_match=1,
            max_thin_matches_ratio=1.0)
        ppda = outcome["datasets"][PPDA_KIND]
        self.assertTrue(ppda["baseline_found"])
        self.assertFalse(ppda["written"])
        self.assertTrue(any("CONCLUSE" in err for err in ppda["errors"]))


if __name__ == "__main__":
    unittest.main()
