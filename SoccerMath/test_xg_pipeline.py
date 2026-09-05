"""
test_xg_pipeline.py - Test della pipeline xG consolidata.

Copre:
  * aggregazione casa/trasferta e conteggio ``matches``;
  * selezione della stagione corretta (nessuna mescolanza);
  * zero valido, valori mancanti/negativi/non finiti;
  * duplicati e conflitti sulla stessa partita;
  * alias, collisioni e nomi canonici (dati reali delle 5 leghe);
  * squadre senza partite valide;
  * cutoff point-in-time (partite in corso escluse, giorno del cutoff escluso,
    fusi orari dichiarati, criterio kickoff_unsafe solo su richiesta);
  * confronto fra snapshot dell'archivio: risultati spariti o regrediti
    bloccano, fixture/correzioni legittime no;
  * validazione bloccante dei nomi PRIMA di pubblicare le medie;
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
from datetime import datetime, timedelta, timezone

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
    ARCHIVE_FILES, LEAGUES, aggregate_season, compare_snapshots, load_archive,
    match_key, parse_kickoff, parse_season, parse_xg, season_averages,
    validate_archive,
)

DB_DIR = os.path.join(_HERE, "database")
LEAGUE_PREFIX = {
    "Serie A": "SerieA", "Premier League": "Premier", "La Liga": "LaLiga",
    "Bundesliga": "Bundesliga", "Ligue 1": "Ligue1",
}
UTC = timezone.utc

# 20 nomi canonici reali di Serie A (chiavi usate da get_league_engine):
# i test di pubblicazione devono passare la validazione bloccante dei nomi.
SERIE_A_TEAMS = [
    "Inter", "Milan", "Juventus", "Napoli", "Roma", "Lazio", "Atalanta",
    "Fiorentina", "Bologna", "Torino", "Udinese", "Genoa", "Cagliari",
    "Verona", "Lecce", "Parma", "Como", "Sassuolo", "Pisa", "Cremonese",
]


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
    """Cutoff point-in-time.

    Criterio predefinito ``previous_day``: entrano solo le partite dei giorni
    STRETTAMENTE precedenti a quello del cutoff, nel fuso dichiarato. Il
    kickoff anteriore al cutoff non dimostra che la partita fosse finita (ne'
    che gli xG fossero pubblicati), e l'archivio non contiene la durata.
    """

    def test_match_in_progress_at_cutoff_excluded(self):
        """Kickoff 18:00, cutoff 18:30: la partita poteva essere IN CORSO."""
        agg = aggregate_season(
            [match(date="2026-09-05 18:00:00")], 2026,
            cutoff="2026-09-05T18:30:00+00:00")
        self.assertEqual(agg.averages, {})
        self.assertEqual(agg.skipped.get("giorno_del_cutoff_o_dopo"), 1)

    def test_same_day_earlier_kickoff_excluded_by_default(self):
        agg = aggregate_season(
            [match(date="2026-09-01 12:00:00")], 2026,
            cutoff=datetime(2026, 9, 1, 23, 59, tzinfo=UTC))
        self.assertEqual(agg.averages, {})
        self.assertEqual(agg.skipped.get("giorno_del_cutoff_o_dopo"), 1)

    def test_previous_day_included(self):
        agg = aggregate_season(
            [match(date="2026-08-31 20:45:00")], 2026,
            cutoff=datetime(2026, 9, 1, 0, 1, tzinfo=UTC))
        self.assertEqual(agg.averages["Inter"]["matches"], 1)

    def test_future_matches_excluded(self):
        records = [
            match(mid=1, date="2026-08-20 18:00:00", home_xg=1.0, away_xg=1.0),
            match(mid=2, date="2026-09-20 18:00:00", home="Inter", away="Milan",
                  home_xg=3.0, away_xg=0.0),
        ]
        agg = aggregate_season(records, 2026, cutoff="2026-09-01T00:00:00+00:00")
        self.assertEqual(agg.averages["Inter"]["matches"], 1)
        self.assertEqual(agg.averages["Inter"]["xG_avg"], 1.0)
        self.assertEqual(agg.skipped.get("giorno_del_cutoff_o_dopo"), 1)

    def test_match_exactly_at_cutoff_excluded(self):
        agg = aggregate_season(
            [match(date="2026-09-01 12:00:00")], 2026,
            cutoff=datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
        self.assertEqual(agg.averages, {})

    def test_day_timezone_boundary_rome_vs_utc(self):
        """Kickoff 31/08 22:00 UTC = 01/09 00:00 a Roma.

        Con i giorni contati in UTC la partita e' del giorno precedente ed
        entra; contandoli a Roma cade nel giorno del cutoff e resta fuori.
        Il fuso e' una scelta DICHIARATA, non un dato dell'archivio.
        """
        records = [match(date="2026-08-31 22:00:00")]
        cutoff = "2026-09-01T00:30:00+00:00"
        utc_agg = aggregate_season(records, 2026, cutoff=cutoff, day_timezone="UTC")
        rome_agg = aggregate_season(records, 2026, cutoff=cutoff,
                                    day_timezone="Europe/Rome")
        self.assertEqual(utc_agg.matches_used, 1)
        self.assertEqual(rome_agg.matches_used, 0)
        self.assertEqual(rome_agg.day_timezone, "Europe/Rome")

    def test_day_timezone_accepts_offset_and_tzinfo(self):
        records = [match(date="2026-08-31 22:00:00")]
        cutoff = "2026-09-01T00:30:00+00:00"
        for tz in ("+02:00", timezone(timedelta(hours=2))):
            with self.subTest(tz=tz):
                agg = aggregate_season(records, 2026, cutoff=cutoff, day_timezone=tz)
                self.assertEqual(agg.matches_used, 0)

    def test_kickoff_unsafe_policy_is_opt_in(self):
        records = [match(date="2026-09-05 12:00:00")]
        cutoff = "2026-09-05T18:30:00+00:00"
        self.assertEqual(aggregate_season(records, 2026, cutoff=cutoff).matches_used, 0)
        unsafe = aggregate_season(records, 2026, cutoff=cutoff,
                                  cutoff_policy="kickoff_unsafe")
        self.assertEqual(unsafe.matches_used, 1)
        self.assertEqual(unsafe.cutoff_policy, "kickoff_unsafe")

    def test_kickoff_unsafe_still_excludes_later_kickoff(self):
        agg = aggregate_season([match(date="2026-09-05 19:00:00")], 2026,
                               cutoff="2026-09-05T18:30:00+00:00",
                               cutoff_policy="kickoff_unsafe")
        self.assertEqual(agg.matches_used, 0)
        self.assertEqual(agg.skipped.get("dopo_cutoff"), 1)

    def test_kickoff_unsafe_falls_back_to_day_rule_without_time(self):
        agg = aggregate_season([match(date="2026-09-05")], 2026,
                               cutoff="2026-09-05T23:59:00+00:00",
                               cutoff_policy="kickoff_unsafe")
        self.assertEqual(agg.matches_used, 0)

    def test_unknown_policy_rejected(self):
        with self.assertRaises(ValueError):
            aggregate_season([match()], 2026, cutoff="2026-09-05",
                             cutoff_policy="qualunque")

    def test_default_policy_declared_in_result(self):
        agg = aggregate_season([match()], 2026, cutoff="2026-09-05")
        self.assertEqual(agg.cutoff_policy, "previous_day")
        self.assertEqual(agg.to_dict()["day_timezone"], "UTC")

    def test_date_only_excludes_whole_day(self):
        agg = aggregate_season(
            [match(date="2026-09-01")], 2026,
            cutoff=datetime(2026, 9, 1, 23, 59, tzinfo=UTC))
        self.assertEqual(agg.averages, {})
        self.assertEqual(agg.skipped.get("giorno_del_cutoff_o_dopo"), 1)

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
        aware = aggregate_season([match(date="2026-08-31 12:00:00")], 2026,
                                 cutoff=datetime(2026, 9, 1, 18, 0, tzinfo=UTC))
        naive = aggregate_season([match(date="2026-08-31 12:00:00")], 2026,
                                 cutoff=datetime(2026, 9, 1, 18, 0))
        self.assertEqual(aware.averages, naive.averages)
        self.assertEqual(aware.averages["Inter"]["matches"], 1)

    def test_cutoff_respects_explicit_offset(self):
        """Cutoff 00:30+02:00 = 31/08 22:30 UTC: il giorno del cutoff e' il 31."""
        agg = aggregate_season([match(date="2026-08-31 12:00:00")], 2026,
                               cutoff="2026-09-01T00:30:00+02:00")
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
        partial = self.valid[:150]  # -25% di partite gia' concluse
        res = self._run(lambda *_a, **_k: partial)
        self.assertFalse(res["written"])
        self.assertTrue(any("CONCLUSE" in e for e in res["errors"]), res["errors"])
        self.assertEqual(open(self.path, encoding="utf-8").read(), self.before)

    def test_single_missing_finished_match_rejected(self):
        """UNA partita conclusa persa su 200 (-0.5%): sotto MAX_SHRINK_RATIO,
        ma e' un risultato storico sparito: si blocca."""
        missing_one = [m for m in self.valid if m["id"] != 42]
        res = self._run(lambda *_a, **_k: missing_one)
        self.assertFalse(res["written"])
        self.assertEqual(len(res["diff"]["missing_finished"]), 1)
        self.assertTrue(any("CONCLUSE" in e for e in res["errors"]))
        self.assertEqual(open(self.path, encoding="utf-8").read(), self.before)

    def test_same_total_with_swapped_id_rejected(self):
        """Stesso NUMERO di partite ma un id sostituito: il controllo sul
        totale non se ne accorgerebbe, il confronto per id si'."""
        swapped = [dict(m) for m in self.valid]
        swapped[7] = match(mid=9999, date="2026-08-08 18:00:00")
        res = self._run(lambda *_a, **_k: swapped)
        self.assertFalse(res["written"])
        self.assertEqual(len(swapped), len(self.valid))
        self.assertEqual(len(res["diff"]["missing_finished"]), 1)
        self.assertEqual(open(self.path, encoding="utf-8").read(), self.before)

    def test_finished_match_regressed_to_not_played_rejected(self):
        regressed = [dict(m) for m in self.valid]
        regressed[3] = dict(regressed[3], is_result=False,
                            home_xg=None, away_xg=None)
        res = self._run(lambda *_a, **_k: regressed)
        self.assertFalse(res["written"])
        self.assertTrue(any("regredite" in e for e in res["errors"]), res["errors"])
        self.assertEqual(open(self.path, encoding="utf-8").read(), self.before)

    def test_new_matches_and_xg_corrections_accepted(self):
        """Variazioni legittime: partite nuove, xG rivisti sulla stessa
        partita, fixture non giocata tolta dal calendario."""
        updated = [dict(m) for m in self.valid]
        updated[0] = dict(updated[0], home_xg=2.35)          # correzione xG
        updated.append(match(mid=500, date="2026-09-02 18:00:00"))  # nuova
        unplayed = match(mid=600, date="2027-05-01 18:00:00",
                         is_result=False, home_xg=None, away_xg=None)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.valid + [unplayed], f)            # fixture poi tolta
        res = self._run(lambda *_a, **_k: updated)
        self.assertTrue(res["written"], res["errors"])
        self.assertEqual(res["diff"]["xg_corrections"], 1)
        self.assertEqual(res["diff"]["new_matches"], 1)
        self.assertEqual(res["diff"]["dropped_unplayed"], 1)

    def test_dropping_a_season_requires_explicit_flag(self):
        older = [match(mid=1000 + i, season=2025,
                       date=f"2025-08-{(i % 28) + 1:02d} 18:00:00")
                 for i in range(50)]
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.valid + older, f)

        blocked = self._run(lambda *_a, **_k: self.valid)
        self.assertFalse(blocked["written"])
        self.assertIn(2025, blocked["diff"]["dropped_seasons"])

        allowed = update_all_xg_db.update_league(
            "Serie A", ["2627"], self.tmp, fetcher=lambda *_a, **_k: self.valid,
            allow_dropping_seasons=True)
        self.assertTrue(allowed["written"], allowed["errors"])

    def test_baseline_dir_compares_against_real_data_while_writing_elsewhere(self):
        """Modalita' verifica: output in cartella temporanea, confronto contro
        l'archivio vero."""
        out_dir = tempfile.mkdtemp(prefix="xg-verify-")
        try:
            res = update_all_xg_db.update_league(
                "Serie A", ["2627"], out_dir, baseline_dir=self.tmp,
                fetcher=lambda *_a, **_k: self.valid[:150])
            self.assertFalse(res["written"])
            self.assertTrue(res["errors"])
            self.assertFalse(os.path.exists(
                os.path.join(out_dir, ARCHIVE_FILES["Serie A"])))
            self.assertEqual(open(self.path, encoding="utf-8").read(), self.before)
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)

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
        teams = list(SERIE_A_TEAMS)
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
        teams = list(SERIE_A_TEAMS)
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


# ---------------------------------------------------------------------------
# 11. Fonte unica degli alias (team_aliases.py) e coerenza fra i livelli
# ---------------------------------------------------------------------------
class TestSharedAliasSource(unittest.TestCase):
    def test_config_reexports_the_shared_tables(self):
        """Le interfacce storiche restano valide (nessun import circolare)."""
        import config
        import team_aliases
        self.assertIs(config.TEAM_NAME_MAP, team_aliases.TEAM_NAME_MAP)
        self.assertIs(config.clean_name, team_aliases.clean_name)
        self.assertIs(config.NAME_CLEAN_REPLACEMENTS,
                      team_aliases.NAME_CLEAN_REPLACEMENTS)

    def test_no_layer_disagrees_on_a_shared_key(self):
        import team_aliases
        self.assertEqual(team_aliases.conflicting_aliases(), {})

    def test_every_mapped_value_is_canonical(self):
        """clean_name(valore) == valore: nessun alias porta a un nome che
        l'engine non userebbe mai (es. 'St. Pauli' invece di 'St Pauli')."""
        import team_aliases
        for table_name in ("TEAM_NAME_MAP", "UNDERSTAT_NAME_MAP"):
            table = getattr(team_aliases, table_name)
            for raw, value in table.items():
                with self.subTest(table=table_name, raw=raw):
                    self.assertEqual(team_aliases.clean_name(value), value)

    def test_team_names_has_no_private_alias_table(self):
        """team_names espone la tabella condivisa, non una copia parallela."""
        import team_aliases
        import team_names
        self.assertIs(team_names.NAME_MAP, team_aliases.ALL_ALIASES)
        self.assertFalse(hasattr(team_names, "LEGACY_ALIASES"))

    def test_resolution_sources(self):
        cases = {
            "Bayer Leverkusen": "alias",     # titolo Understat
            "Inter Milan": "alias",          # nome API live
            "Leverkusen": "canonical",       # gia' canonico
            "Dortmund": "canonical",
            "Squadra Mai Vista": "unknown",
            "": "empty",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(resolve_team_name(raw).source, expected)

    def test_canonical_names_are_accepted_without_alias_entry(self):
        """Nessun falso allarme: un nome gia' canonico non e' 'non mappato'."""
        for name in ("Inter", "Ath Bilbao", "M'gladbach", "Nott'm Forest", "PSG"):
            with self.subTest(name=name):
                res = resolve_team_name(name)
                self.assertTrue(res.mapped)
                self.assertEqual(res.canonical, name)

    def test_unknown_name_is_never_guessed(self):
        res = resolve_team_name("Real Sociedadd")   # refuso
        self.assertEqual(res.source, "unknown")
        self.assertNotEqual(res.canonical, "Sociedad")

    def test_csv_names_of_all_leagues_are_canonical(self):
        """Coerenza con i CSV reali: ogni nome dei CSV e' gia' canonico."""
        for league, prefix in LEAGUE_PREFIX.items():
            for fname in os.listdir(DB_DIR):
                if not fname.startswith(prefix + "_") or not fname.endswith(".csv"):
                    continue
                df = pd.read_csv(os.path.join(DB_DIR, fname), usecols=["HomeTeam"],
                                 encoding="latin-1", on_bad_lines="skip")
                for raw in df["HomeTeam"].dropna().unique():
                    with self.subTest(league=league, file=fname, team=raw):
                        self.assertEqual(canonical_team_name(raw), clean_name(raw))


# ---------------------------------------------------------------------------
# 12. Validazione bloccante dei nomi PRIMA della pubblicazione
# ---------------------------------------------------------------------------
class TestBlockingNameValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="xg-names-")
        self.arch = os.path.join(self.tmp, ARCHIVE_FILES["Serie A"])
        self.out = os.path.join(self.tmp, "xg_serie_a.json")
        with open(self.out, "w", encoding="utf-8") as f:
            json.dump({"Inter": {"xG_avg": 1.0, "xGA_avg": 1.0, "matches": 10}}, f)
        self.before = open(self.out, encoding="utf-8").read()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _archive(self, teams, extra=()):
        records = [match(mid=i, home=teams[i], away=teams[i + 1],
                         date=f"2026-08-{i + 1:02d} 18:00:00")
                   for i in range(0, len(teams) - 1, 2)]
        records.extend(extra)
        with open(self.arch, "w", encoding="utf-8") as f:
            json.dump(records, f)
        return records

    def test_unknown_name_blocks_publication(self):
        teams = list(SERIE_A_TEAMS)
        teams[4] = "Societa Sportiva Inventata"
        self._archive(teams)
        res = update_xg.derive_league("Serie A", 2026, database_dir=self.tmp)
        self.assertFalse(res["written"])
        self.assertTrue(any("non risolti" in e for e in res["errors"]), res["errors"])
        # il file precedente resta esattamente com'era
        self.assertEqual(open(self.out, encoding="utf-8").read(), self.before)

    def test_valid_alias_is_accepted(self):
        teams = list(SERIE_A_TEAMS)
        teams[0] = "Inter Milan"           # alias dichiarato -> Inter
        self._archive(teams)
        res = update_xg.derive_league("Serie A", 2026, database_dir=self.tmp)
        self.assertTrue(res["written"], res["errors"])
        data = json.load(open(self.out, encoding="utf-8"))
        self.assertIn("Inter", data)
        self.assertNotIn("Inter Milan", data)

    def test_canonical_names_pass_without_warnings(self):
        self._archive(list(SERIE_A_TEAMS))
        res = update_xg.derive_league("Serie A", 2026, database_dir=self.tmp)
        self.assertTrue(res["written"], res["errors"])
        self.assertEqual(res["unmapped_names"], {})
        self.assertEqual(res["name_collisions"], {})

    def test_undeclared_collision_blocks_publication(self):
        # nella STESSA stagione compaiono sia "Inter" sia "Inter Milan":
        # due grafie che collassano sullo stesso nome canonico
        collision = match(mid=99, home="Inter Milan", away="Torino",
                          date="2026-08-25 18:00:00")
        self._archive(list(SERIE_A_TEAMS), extra=[collision])
        res = update_xg.derive_league("Serie A", 2026, database_dir=self.tmp)
        self.assertFalse(res["written"])
        self.assertTrue(any("collisione" in e for e in res["errors"]), res["errors"])
        self.assertEqual(open(self.out, encoding="utf-8").read(), self.before)

    def test_declared_collision_is_allowed(self):
        collision = match(mid=99, home="Inter Milan", away="Torino",
                          date="2026-08-25 18:00:00")
        self._archive(list(SERIE_A_TEAMS), extra=[collision])
        original = dict(update_xg.ACCEPTED_COLLISIONS)
        update_xg.ACCEPTED_COLLISIONS["Inter"] = ["Inter", "Inter Milan"]
        try:
            res = update_xg.derive_league("Serie A", 2026, database_dir=self.tmp)
        finally:
            update_xg.ACCEPTED_COLLISIONS.clear()
            update_xg.ACCEPTED_COLLISIONS.update(original)
        self.assertTrue(res["written"], res["errors"])

    def test_validation_runs_before_writing(self):
        """Nessun file (nemmeno .tmp) viene creato quando la validazione fallisce."""
        teams = list(SERIE_A_TEAMS)
        teams[2] = "Nome Inesistente FC"
        self._archive(teams)
        out_only = os.path.join(self.tmp, "nuovo_xg.json")
        res = update_xg.derive_league("Serie A", 2026, database_dir=self.tmp)
        self.assertFalse(res["written"])
        self.assertFalse(os.path.exists(out_only))
        self.assertFalse(os.path.exists(self.out + ".tmp"))

    def test_opt_out_flag_downgrades_to_warning(self):
        teams = list(SERIE_A_TEAMS)
        teams[6] = "Nome Inesistente FC"
        self._archive(teams)
        res = update_xg.derive_league("Serie A", 2026, database_dir=self.tmp,
                                      allow_unmapped_names=True)
        self.assertTrue(res["written"], res["errors"])
        self.assertTrue(res["warnings"])

    def test_real_archives_pass_the_blocking_validation(self):
        """Sui dati reali delle 5 leghe la validazione non blocca nulla."""
        from config import CURRENT_SEASON_START_YEAR
        for league in LEAGUES:
            with self.subTest(league=league):
                agg = season_averages(league, CURRENT_SEASON_START_YEAR)
                self.assertEqual(update_xg.mapping_errors(agg, league=league), [])


# ---------------------------------------------------------------------------
# 13. Confronto fra snapshot: unita'
# ---------------------------------------------------------------------------
class TestSnapshotDiff(unittest.TestCase):
    def test_match_key_prefers_id(self):
        self.assertEqual(match_key(match(mid=7)), (2026, "7"))
        no_id = match(mid=None)
        self.assertEqual(match_key(no_id), (2026, "Inter", "Torino"))

    def test_no_previous_snapshot_is_not_a_problem(self):
        diff = compare_snapshots(None, [match()])
        self.assertEqual(diff.blocking_problems, [])

    def test_identical_snapshots(self):
        recs = [match(mid=i) for i in range(5)]
        diff = compare_snapshots(recs, [dict(r) for r in recs])
        self.assertEqual(diff.blocking_problems, [])
        self.assertEqual(diff.new_matches, [])
        self.assertEqual(diff.xg_corrections, [])

    def test_unplayed_fixture_removed_is_allowed(self):
        played = match(mid=1)
        fixture = match(mid=2, is_result=False, home_xg=None, away_xg=None)
        diff = compare_snapshots([played, fixture], [dict(played)])
        self.assertEqual(diff.blocking_problems, [])
        self.assertEqual(len(diff.dropped_unplayed), 1)

    def test_xg_correction_is_reported_not_blocked(self):
        before = match(mid=1, home_xg=1.10)
        after = match(mid=1, home_xg=1.35)
        diff = compare_snapshots([before], [after])
        self.assertEqual(diff.blocking_problems, [])
        self.assertEqual(diff.xg_corrections[0]["before"], [1.10, 1.0])
        self.assertEqual(diff.xg_corrections[0]["after"], [1.35, 1.0])

    def test_finished_match_losing_xg_blocks(self):
        before = match(mid=1)
        after = match(mid=1, home_xg=None)
        diff = compare_snapshots([before], [after])
        self.assertEqual(len(diff.regressed), 1)
        self.assertTrue(diff.blocking_problems)

    def test_new_match_is_allowed(self):
        diff = compare_snapshots([match(mid=1)], [match(mid=1), match(mid=2)])
        self.assertEqual(diff.blocking_problems, [])
        self.assertEqual(len(diff.new_matches), 1)

    def test_declared_season_reduction(self):
        old = [match(mid=1, season=2025, date="2025-08-20 18:00:00"),
               match(mid=2, season=2026)]
        new = [match(mid=2, season=2026)]
        blocked = compare_snapshots(old, new, requested_seasons=[2026])
        self.assertEqual(blocked.dropped_seasons, [2025])
        self.assertTrue(blocked.blocking_problems)
        allowed = compare_snapshots(old, new, requested_seasons=[2026],
                                    allow_dropping_seasons=True)
        self.assertEqual(allowed.blocking_problems, [])

    def test_missing_match_of_a_requested_season_still_blocks(self):
        """La riduzione dichiarata delle stagioni non autorizza a perdere i
        risultati delle stagioni ANCORA richieste."""
        old = [match(mid=1, season=2025, date="2025-08-20 18:00:00"),
               match(mid=2, season=2026), match(mid=3, season=2026)]
        new = [match(mid=2, season=2026)]
        diff = compare_snapshots(old, new, requested_seasons=[2026],
                                 allow_dropping_seasons=True)
        self.assertEqual(len(diff.missing_finished), 1)
        self.assertTrue(diff.blocking_problems)


if __name__ == "__main__":
    unittest.main(verbosity=2)
