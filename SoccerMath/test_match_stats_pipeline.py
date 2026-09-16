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
    load_ppda,
    name_resolution_report,
    parse_minutes,
    parse_ppda,
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
                 fail_team_stats=False, fail_players=False, broken_ids=()):
        self.schedule = schedule
        self.team_stats = team_stats
        self.player_stats = player_stats
        self.fail_team_stats = fail_team_stats
        self.fail_players = fail_players
        # partite il cui payload rompe soccerdata (errore NON ConnectionError):
        # la chiamata intera fallisce, come nell'esecuzione reale
        self.broken_ids = set(broken_ids)
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
        if wanted & self.broken_ids:
            raise AttributeError("'list' object has no attribute 'values'")
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
            min_rows_per_match=1, max_thin_matches_ratio=1.0, max_duplicate_rows_ratio=1.0,
            max_structural_na_ratio=1.0)
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
            max_thin_matches_ratio=1.0, max_duplicate_rows_ratio=1.0,
            max_structural_na_ratio=1.0)
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
            max_thin_matches_ratio=1.0, max_duplicate_rows_ratio=1.0,
            max_structural_na_ratio=1.0)
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
            max_thin_matches_ratio=1.0, max_duplicate_rows_ratio=1.0,
            max_structural_na_ratio=1.0)
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
            max_thin_matches_ratio=0.5, max_duplicate_rows_ratio=1.0,
            max_structural_na_ratio=1.0)
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
            max_thin_matches_ratio=1.0, max_duplicate_rows_ratio=1.0,
            max_structural_na_ratio=1.0)
        ppda = outcome["datasets"][PPDA_KIND]
        self.assertTrue(ppda["baseline_found"])
        self.assertFalse(ppda["written"])
        self.assertTrue(any("CONCLUSE" in err for err in ppda["errors"]))


class TestAuditReport(unittest.TestCase):
    """Il referto di fattibilita' si compila anche con dati parziali.

    Regressione: il report di acquisizione ha la forma scritta da
    ``update_all_ppda_player_db.main()`` (``leagues`` = LISTA di blocchi per
    lega) e l'audit deve leggerla senza sollevare eccezioni, dichiarando per
    ogni dataset assente il motivo.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ppda-audit-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db = os.path.join(self.tmp, "database")
        self.xg = os.path.join(self.tmp, "xg")
        self.out = os.path.join(self.tmp, "out")
        for folder in (self.db, self.xg, self.out):
            os.makedirs(folder)

    def _xg_archive(self):
        """Archivio xG sintetico: 3 concluse con xG + 1 senza xG."""
        records = []
        for index, (home, away, home_xg, away_xg) in enumerate([
                ("Inter", "Torino", 1.4, 0.9),
                ("Roma", "Lazio", 1.1, 1.2),
                ("Juventus", "Milan", 0.8, 1.0),
                ("Napoli", "Atalanta", None, None)]):
            records.append({
                "season": 2026, "id": 100 + index,
                "date": f"2026-09-{10 + index:02d} 18:45:00",
                "home_team": home, "away_team": away,
                "home_goals": 1 if home_xg else None,
                "away_goals": 1 if home_xg else None,
                "home_xg": home_xg, "away_xg": away_xg,
                "is_result": home_xg is not None,
            })
        # scritto a mano (non con write_atomic: il modulo NUOVO rifiuta di
        # scrivere dentro l'archivio xG, ed e' proprio la protezione che si
        # vuole verificare altrove)
        path = os.path.join(self.xg, ARCHIVE_FILES["Serie A"])
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, indent=2)

    def _archives(self):
        write_atomic(os.path.join(self.db, archive_files(PPDA_KIND)["Serie A"]), [
            acquisition.normalize_ppda_record({
                "season": 2026, "id": 100, "date": "2026-09-10 18:45:00",
                "home_team": "Inter", "away_team": "Torino", "is_result": True,
                "home_ppda": 8.5, "away_ppda": 12.0,
                "home_deep_completions": 14, "away_deep_completions": 6}),
            acquisition.normalize_ppda_record({
                "season": 2026, "id": 101, "date": "2026-09-11 18:45:00",
                "home_team": "Roma", "away_team": "Lazio", "is_result": True,
                "home_ppda": 9.1, "away_ppda": 10.4,
                "home_deep_completions": 9, "away_deep_completions": 11}),
            # terza partita presente ma con PPDA non calcolabile su un lato
            acquisition.normalize_ppda_record({
                "season": 2026, "id": 102, "date": "2026-09-12 18:45:00",
                "home_team": "Juventus", "away_team": "Milan", "is_result": True,
                "home_ppda": None, "away_ppda": 11.2,
                "home_deep_completions": 7, "away_deep_completions": 8}),
        ])
        rows = []
        for index, (home, away) in enumerate([
                ("Inter", "Torino"), ("Roma", "Lazio")]):
            for slot, minutes in enumerate((90, 90, 0)):
                rows.append(acquisition.normalize_player_record({
                    "season": 2026, "id": 100 + index,
                    "date": f"2026-09-{10 + index:02d}",
                    "team": home, "opponent": away, "venue": "home",
                    "player_id": 500 + slot, "player": f"Titolare {slot}",
                    "position": "FW", "minutes": minutes, "goals": 0,
                    "own_goals": 0, "shots": 1, "xg": 0.2, "xg_chain": 0.3,
                    "xg_buildup": 0.1, "assists": 0, "xa": 0.05,
                    "key_passes": 0, "yellow_cards": 0, "red_cards": 0}))
        write_atomic(os.path.join(self.db, archive_files(PLAYER_KIND)["Serie A"]),
                     rows)

    def _acquisition_report(self):
        path = os.path.join(self.tmp, "acquisizione.json")
        payload = {
            "generated_at": "2026-09-15T09:00:00+00:00",
            "soccerdata_version": "1.9.1", "required_soccerdata_version": "1.9.1",
            "seasons": ["2627"], "player_seasons": ["2627"],
            "leagues_requested": ["Serie A", "Premier League"],
            "failures": 1, "missing_tolerance_ratio": 0.0, "retries": 2,
            "frontier_days": 1.0, "parallel_leagues": 2,
            "sample_matches_per_league": None, "dry_run": False,
            "leagues": [
                {"league": "Serie A", "seconds": 42.0, "errors": [], "datasets": {
                    PPDA_KIND: {"written": True, "matches": 3, "errors": [],
                                "retry_rounds": 0, "requested_matches": 3,
                                "coverage": {"reference_matches": 3,
                                             "missing_total": 0,
                                             "missing_frontier": 0,
                                             "missing_old": 0, "missing_undated": 0,
                                             "complete": 2}},
                    PLAYER_KIND: {"written": True, "rows": 6, "errors": [],
                                  "retry_rounds": 1, "requested_matches": 3,
                                  "returned_matches": 2,
                                  "missing_matches_sample": ["2026-09-12 (id 102)"],
                                  "coverage": {"reference_matches": 3,
                                               "missing_total": 1,
                                               "missing_frontier": 1,
                                               "missing_old": 0,
                                               "missing_undated": 0}}},
                 "schedule": {"scheduled_matches": 4, "played_with_xg": 3,
                              "last_played_date": "2026-09-12 18:45:00"}},
                # lega in cui soccerdata NON espone i campi: motivo dichiarato
                {"league": "Premier League", "seconds": 3.0, "datasets": {},
                 "errors": ["read_team_match_stats(): campo home_ppda assente "
                            "nella versione installata"]},
            ],
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def test_report_renders_from_list_shaped_acquisition_report(self):
        sys.path.insert(0, os.path.join(_REPO_ROOT, "audit"))
        import ppda_deep_player_audit as audit  # noqa: E402

        self._xg_archive()
        self._archives()
        report_path = self._acquisition_report()
        exit_code = audit.main([
            "--database-dir", self.db, "--xg-dir", self.xg,
            "--acquisition-report", report_path, "--results-dir", self.out,
            "--run-url", "https://example.invalid/run/1", "--run-id", "1"])
        self.assertEqual(exit_code, 0)

        markdown_path = os.path.join(self.out, "ppda_deep_player_feasibility.md")
        json_path = os.path.join(self.out, "ppda_deep_player_feasibility.json")
        self.assertTrue(os.path.exists(markdown_path))
        with open(markdown_path, encoding="utf-8") as fh:
            markdown = fh.read()
        for section in ("## 1. Sintesi", "## 2. Copertura per lega e stagione",
                        "## 3. Point-in-time", "## 4. Minuti giocati per partita",
                        "## 5. Nomi delle squadre", "## 6. Cosa espone",
                        "## 7. Costo dell'acquisizione", "## 8. Limiti dichiarati"):
            self.assertIn(section, markdown)
        self.assertIn(archive_files(PPDA_KIND)["Serie A"], markdown)
        self.assertIn(archive_files(PLAYER_KIND)["Serie A"], markdown)
        # il motivo del dataset assente e' dichiarato, non taciuto
        self.assertIn("home_ppda assente", markdown)
        self.assertIn("0.55", markdown)  # nessuna modifica al motore, dichiarato

        with open(json_path, encoding="utf-8") as fh:
            analysis = json.load(fh)
        serie_a = analysis["leagues"]["Serie A"]["coverage"]
        totals = serie_a[PPDA_KIND]["totals"]
        self.assertEqual(totals["reference_matches"], 3)
        self.assertEqual(totals["complete"], 2)
        # PPDA nullo con deep presente su entrambi i lati = caso strutturale:
        # NON e' una partita mancante e non entra in "partial"
        self.assertEqual(totals["structural_ppda_na"], 1)
        self.assertEqual(totals["partial"], 0)
        self.assertEqual(totals["missing_matches"], 0)
        self.assertEqual(totals["with_home_ppda"], 2)
        player_totals = serie_a[PLAYER_KIND]["totals"]
        self.assertEqual(player_totals["present_matches"], 2)
        self.assertEqual(player_totals["rows"], 6)
        minutes = analysis["leagues"]["Serie A"]["minutes"]
        self.assertEqual(minutes["rows"], 6)
        self.assertEqual(minutes["zero_minutes_rows"], 2)
        self.assertEqual(minutes["used_rows"], 4)
        self.assertEqual(minutes["players_per_match"]["p50"], 3.0)
        self.assertEqual(analysis["acquisition"]["failures"], 1)


class TestSourceDefects(unittest.TestCase):
    """Difetti reali della fonte osservati sull'acquisizione vera (2026-09-15).

    1. il payload di lega puo' elencare due volte la stessa partita: soccerdata
       la percorre due volte e le righe giocatore escono doppie (La Liga);
    2. PPDA nullo su un lato con deep completions presente: e' il caso
       strutturale (denominatore difensivo 0 -> ``pd.NA`` in soccerdata), non un
       campo perduto (Bundesliga);
    3. un payload con una forma diversa fa fallire l'INTERA chiamata
       per-partita di soccerdata (Bundesliga): le partite buone non devono
       andare perse e quella rotta va dichiarata.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="match-stats-defects-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.out)
        original_match = acquisition.MIN_MATCHES_PER_SEASON
        original_rows = acquisition.MIN_ROWS_PER_SEASON
        acquisition.MIN_MATCHES_PER_SEASON = 1
        acquisition.MIN_ROWS_PER_SEASON = 1
        self.addCleanup(setattr, acquisition, "MIN_MATCHES_PER_SEASON", original_match)
        self.addCleanup(setattr, acquisition, "MIN_ROWS_PER_SEASON", original_rows)

    def _schedule(self, duplicate_match_id=None):
        rows = [
            schedule_row(2022, 1, "2022-08-13 18:45:00", "Inter", "Torino", 2.4, 0.7),
            schedule_row(2022, 2, "2022-08-20 18:45:00", "Roma", "Milan", 1.2, 1.1),
            schedule_row(2022, 3, "2022-08-27 18:45:00", "Napoli", "Inter", 0.9, 1.4),
        ]
        if duplicate_match_id is not None:
            rows.append(dict(rows[duplicate_match_id - 1]))
        return rows

    def _acquire(self, reader, datasets, **kwargs):
        original = acquisition._make_reader
        acquisition._make_reader = lambda *args, **kw: reader
        self.addCleanup(setattr, acquisition, "_make_reader", original)
        params = dict(dry_run=False, allow_dropping_seasons=False, retries=0,
                      frontier_days=1.0, missing_tolerance_ratio=0.0,
                      sample_matches=None, min_played_field_coverage=0.5,
                      min_rows_per_match=1, max_thin_matches_ratio=1.0,
                      max_duplicate_rows_ratio=0.02,
                      max_structural_na_ratio=0.01)
        params.update(kwargs)
        return acquisition.acquire_league(
            "Serie A", ["2223"], ["2223"], output_dir=self.out, baseline_dir=None,
            cache_dir=self.tmp, datasets=datasets, **params)

    def test_duplicated_schedule_row_does_not_duplicate_rows(self):
        # la partita 2 e' elencata due volte nel payload di lega: il dedup la
        # tiene una volta, le righe giocatore non raddoppiano e il conteggio
        # finisce nel report
        schedule = schedule_frame(self._schedule(duplicate_match_id=2))
        rows = [
            player_stats_row(2022, 1, "2022-08-13 18:45:00", "Inter", "Lautaro", 1,
                             minutes=90, home="Inter", away="Torino"),
            player_stats_row(2022, 1, "2022-08-13 18:45:00", "Torino", "Sanabria", 2,
                             minutes=0, home="Inter", away="Torino"),
            player_stats_row(2022, 2, "2022-08-20 18:45:00", "Roma", "Dybala", 3,
                             minutes=80, home="Roma", away="Milan"),
            player_stats_row(2022, 2, "2022-08-20 18:45:00", "Milan", "Leao", 4,
                             minutes=90, home="Roma", away="Milan"),
            player_stats_row(2022, 3, "2022-08-27 18:45:00", "Napoli", "Osimhen", 5,
                             minutes=90, home="Napoli", away="Inter"),
            player_stats_row(2022, 3, "2022-08-27 18:45:00", "Inter", "Barella", 6,
                             minutes=90, home="Napoli", away="Inter"),
        ]
        players = player_stats_frame(rows)
        # il lettore, come soccerdata, restituisce la partita 2 due volte perche'
        # la riga doppia e' nel calendario
        doubled = pd.concat([players.reset_index(), players.reset_index().loc[2:3]])
        doubled = doubled.set_index(
            ["league", "season", "game", "team", "player"]).sort_index()
        reader = FakeReader(schedule=schedule, player_stats=doubled)
        outcome = self._acquire(reader, [PLAYER_KIND])
        self.assertEqual(outcome["schedule_duplicates"]["duplicate_rows"], 1)
        player = outcome["datasets"][PLAYER_KIND]
        self.assertEqual(player["duplicates"]["duplicate_rows"], 2)
        self.assertEqual(player["duplicates"]["duplicate_matches"], 1)
        self.assertEqual(player["duplicates"]["sample_matches"],
                         [{"season": 2022, "id": 2, "rows": 2}])
        # 2 righe doppie su 8 = 25%: sopra la soglia dichiarata la lega non
        # pubblica (il dedup non e' mai silenzioso)
        self.assertFalse(player["written"])
        self.assertTrue(any("doppie sulla chiave" in err for err in player["errors"]))

        # con una soglia dichiarata piu' alta la lega pubblica e il difetto
        # resta nel report
        published = self._acquire(reader, [PLAYER_KIND], max_duplicate_rows_ratio=0.5)
        entry = published["datasets"][PLAYER_KIND]
        self.assertTrue(entry["written"])
        self.assertEqual(entry["rows"], 6)
        self.assertEqual(entry["duplicates"]["duplicate_rows"], 2)

    def test_structural_ppda_na_is_declared_and_does_not_block(self):
        # partita 3: deep presente su entrambi i lati, PPDA nullo sul lato casa
        # (denominatore difensivo 0). Non e' un campo perduto: la lega pubblica
        # e il caso e' contato a parte.
        team_stats = team_stats_frame([
            team_stats_row(2022, 1, "2022-08-13 18:45:00", "Inter", "Torino",
                           8.0, 9.0, 5, 6),
            team_stats_row(2022, 2, "2022-08-20 18:45:00", "Roma", "Milan",
                           7.5, 10.5, 4, 3),
            team_stats_row(2022, 3, "2022-08-27 18:45:00", "Napoli", "Inter",
                           None, 8.2, 6, 7),
        ])
        reader = FakeReader(schedule=schedule_frame(self._schedule()),
                            team_stats=team_stats)
        outcome = self._acquire(reader, [PPDA_KIND], max_structural_na_ratio=1.0)
        ppda = outcome["datasets"][PPDA_KIND]
        self.assertEqual(ppda["coverage"]["structural_ppda_na"], 1)
        self.assertEqual(ppda["coverage"]["missing_total"], 0)
        self.assertEqual(ppda["coverage"]["ppda_missing_but_deep_present"], 1)
        self.assertFalse(ppda["errors"])
        self.assertTrue(ppda["written"])

        # stessa istantanea ma con una soglia stretta sui casi strutturali: la
        # lega NON viene pubblicata (la soglia e' dichiarata, non silenziosa)
        second = self._acquire(reader, [PPDA_KIND], max_structural_na_ratio=0.01)
        strict = second["datasets"][PPDA_KIND]
        self.assertTrue(strict["errors"])
        self.assertIn("non calcolabile", strict["errors"][0])
        self.assertFalse(strict["written"])

    def test_broken_match_is_isolated_and_declared(self):
        # la partita 2 fa fallire la chiamata per-partita di soccerdata: le
        # partite 1 e 3 devono restare, la 2 va dichiarata illeggibile
        players = player_stats_frame([
            player_stats_row(2022, 1, "2022-08-13 18:45:00", "Inter", "Lautaro", 1,
                             minutes=90, home="Inter", away="Torino"),
            player_stats_row(2022, 2, "2022-08-20 18:45:00", "Roma", "Dybala", 3,
                             minutes=80, home="Roma", away="Milan"),
            player_stats_row(2022, 3, "2022-08-27 18:45:00", "Napoli", "Osimhen", 4,
                             minutes=90, home="Napoli", away="Inter"),
        ])
        reader = FakeReader(schedule=schedule_frame(self._schedule()),
                            player_stats=players, broken_ids=[2])
        outcome = self._acquire(reader, [PLAYER_KIND], missing_tolerance_ratio=0.0)
        player = outcome["datasets"][PLAYER_KIND]
        self.assertEqual(player["unreadable_matches"], 1)
        self.assertEqual(player["unreadable_sample"][0]["id"], 2)
        self.assertIn("no attribute 'values'", player["unreadable_sample"][0]["error"])
        # le altre due partite non sono andate perse
        self.assertEqual(player["coverage"]["returned_matches"], 2)
        # la partita rotta resta MANCANTE: senza tolleranza dichiarata la lega
        # non pubblica
        self.assertFalse(player["written"])
        self.assertTrue(any("senza righe giocatore" in err for err in player["errors"]))

        # con una tolleranza dichiarata la lega pubblica, dichiarando il difetto
        published = self._acquire(reader, [PLAYER_KIND], missing_tolerance_ratio=1.0)
        entry = published["datasets"][PLAYER_KIND]
        self.assertTrue(entry["written"])
        self.assertEqual(entry["unreadable_matches"], 1)
        self.assertEqual(entry["rows"], 2)


if __name__ == "__main__":
    unittest.main()
