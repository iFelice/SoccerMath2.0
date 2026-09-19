"""
test_rollover_chain_2027.py - SIMULAZIONE ESPLICITA DEL ROLLOVER (punto 6).

Data di sistema portata a luglio e ad agosto 2027 e intera catena eseguita su
una COPIA temporanea del database reale, senza interventi manuali:

  1. config              : stagione corrente, HISTORICAL_SEASONS, finestra
                           soccerdata derivate dalla data (via env
                           M4_CURRENT_SEASON_START_YEAR in un sottoprocesso,
                           come farebbe il runner il 1° luglio);
  2. season_rollover     : il Live 2026/27 diventa _2026.csv, il Live riparte
                           vuoto, nessun doppione (grafie diverse unificate),
                           idempotente;
  3. update_all_xg_db    : finestra mobile 2324..2728; la 2223 esce
                           dall'archivio senza flag manuale, la 2728 e'
                           tollerata assente finche' Understat non la
                           pubblica (luglio) e diventa obbligatoria appena
                           compare (agosto);
  4. update_xg           : derivazione delle medie per la stagione nuova ->
                           pre-stagione = uscita 0 e file precedente intatto;
                           dopo la prima giornata -> file scritto;
  5. update_all_ppda_... : stesse tolleranze di finestra mobile;
  6. MARKET_VALUES/alias : nessun blocco; le neopromosse senza valore vengono
                           segnalate, i nomi canonici restano stabili.

Il test usa fetcher finti (nessuna rete) costruiti dall'archivio reale.
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _ROOT)

import pandas as pd  # noqa: E402

import config  # noqa: E402
import season_rollover  # noqa: E402
import update_xg  # noqa: E402
import update_all_xg_db  # noqa: E402
import update_all_ppda_player_db as ppda  # noqa: E402
from xg_archive import ARCHIVE_FILES, load_archive, parse_season  # noqa: E402
from team_aliases import clean_name  # noqa: E402

JULY_2027 = datetime(2027, 7, 15)
AUGUST_2027 = datetime(2027, 8, 25)


def _fake_2027_matchday(records, season=2027, day="2027-08-21"):
    """Una giornata intera della stagione nuova (>= 10 squadre) con xG validi,
    costruita dalle squadre della stagione precedente (tutte gia' canoniche)."""
    prev = max(parse_season(r["season"]) for r in records)
    teams = sorted({r["home_team"] for r in records if parse_season(r["season"]) == prev})
    out = []
    for i in range(0, len(teams) - 1, 2):
        out.append({"season": season, "id": 9_000_000 + i, "date": f"{day} 18:00:00",
                    "home_team": teams[i], "away_team": teams[i + 1],
                    "home_goals": 1, "away_goals": 0,
                    "home_xg": 1.2 + 0.01 * i, "away_xg": 0.8, "is_result": True})
    return out


class TestRolloverChain2027(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="rollover-2027-")
        cls.db = Path(cls._tmp.name) / "database"
        shutil.copytree(config.DATABASE_DIR, cls.db)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    # ------------------------------------------------------------------ 1
    def test_1_config_e_finestre_derivate_dalla_data(self):
        code = (
            "import config, update_all_xg_db, update_all_ppda_player_db as p, json;"
            "print(json.dumps({'cur': config.CURRENT_SEASON, 'y': config.CURRENT_SEASON_START_YEAR,"
            " 'hist': config.HISTORICAL_SEASONS, 'all': config.ALL_SEASONS,"
            " 'xg': update_all_xg_db.SEASONS, 'ppda': p.SEASONS}))"
        )
        env = dict(os.environ, M4_CURRENT_SEASON_START_YEAR="2027",
                   PYTHONPATH=os.pathsep.join([_HERE, _ROOT]))
        env.pop("M4_CURRENT_SEASON", None)
        out = subprocess.run([sys.executable, "-c", code], cwd=_ROOT, env=env,
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        got = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(got["cur"], "2027/2028")
        self.assertEqual(got["hist"], ["2026/2027", "2025/2026", "2024/2025", "2023/2024"])
        self.assertEqual(got["all"], ["2027/2028", "2026/2027", "2025/2026", "2024/2025", "2023/2024"])
        self.assertEqual(got["xg"], ["2324", "2425", "2526", "2627", "2728"])
        self.assertEqual(got["ppda"], got["xg"])
        # senza override: la data reale governa (oggi 2026/27, il 1/7/2027 scatta da sola)
        self.assertEqual(config.get_current_season_start_year(datetime(2027, 6, 30)), 2026)
        self.assertEqual(config.get_current_season_start_year(JULY_2027), 2027)

    # ------------------------------------------------------------------ 2
    def test_2_rollover_live_archivia_2026_senza_doppioni(self):
        n = season_rollover.run_rollover(db_dir=self.db, now=JULY_2027)
        self.assertEqual(n, len(config.LEAGUES_CONFIG), "tutti i campionati archiviati")
        for name, cfg in config.LEAGUES_CONFIG.items():
            prefix = cfg["db_prefix"]
            live = pd.read_csv(self.db / f"{prefix}_Live.csv")
            arch = pd.read_csv(self.db / f"{prefix}_2026.csv")
            self.assertEqual(len(live), 0, f"{name}: il Live deve ripartire vuoto")
            self.assertGreater(len(arch), 30, f"{name}: archivio 2026 troppo piccolo")
            key = arch["Date"] + "|" + arch["HomeTeam"].map(clean_name) + "|" + arch["AwayTeam"].map(clean_name)
            self.assertEqual(int(key.duplicated().sum()), 0, f"{name}: doppioni nell'archivio 2026")
            # tutte le date archiviate appartengono alla 2026/27 (confine 1° luglio)
            dates = pd.to_datetime(arch["Date"], dayfirst=True, errors="coerce").dropna()
            seasons = dates.dt.year - (dates.dt.month < 7).astype(int)
            self.assertTrue((seasons == 2026).all(), name)
        # idempotenza: la seconda esecuzione non cambia nulla
        before = {p.name: p.read_bytes() for p in self.db.glob("*.csv")}
        self.assertEqual(season_rollover.run_rollover(db_dir=self.db, now=JULY_2027), 0)
        after = {p.name: p.read_bytes() for p in self.db.glob("*.csv")}
        self.assertEqual(before, after)

    # ------------------------------------------------------------------ 3
    def test_3_acquisizione_xg_finestra_mobile_luglio_e_agosto(self):
        league = "Serie A"
        baseline = load_archive(league, self.db)
        seasons_2027 = update_all_xg_db.derive_seasons(2027)

        # LUGLIO: Understat espone solo le stagioni concluse (2223..2627): la
        # 2223 e' fuori finestra, la 2728 non esiste ancora.
        july = [r for r in baseline if parse_season(r["season"]) >= 2023]
        res = update_all_xg_db.update_league(
            league, seasons_2027, str(self.db), fetcher=lambda *_a, **_k: copy.deepcopy(july),
            rolling_window=True)
        self.assertEqual(res["errors"], [], res["errors"])
        self.assertTrue(res["written"])
        self.assertEqual(res["season_not_started"], 2027)
        self.assertEqual(res["seasons_aged_out"], [2022])
        written = load_archive(league, self.db)
        self.assertEqual(sorted({parse_season(r["season"]) for r in written}), [2023, 2024, 2025, 2026])

        # Stesso scenario con --seasons ESPLICITO: nessuna tolleranza automatica
        strict = update_all_xg_db.update_league(
            league, seasons_2027, str(self.db), fetcher=lambda *_a, **_k: copy.deepcopy(july))
        self.assertFalse(strict["written"])
        self.assertTrue(any("stagioni assenti" in e for e in strict["errors"]), strict["errors"])

        # AGOSTO: compare la 2728 con la prima giornata -> entra da sola
        august = july + _fake_2027_matchday(baseline)
        res = update_all_xg_db.update_league(
            league, seasons_2027, str(self.db), fetcher=lambda *_a, **_k: copy.deepcopy(august),
            rolling_window=True)
        self.assertEqual(res["errors"], [], res["errors"])
        self.assertTrue(res["written"])
        self.assertNotIn("season_not_started", res)

        # REGRESSIONE (deve ancora bloccare): la 2728 c'era nella baseline e sparisce
        regress = update_all_xg_db.update_league(
            league, seasons_2027, str(self.db), fetcher=lambda *_a, **_k: copy.deepcopy(july),
            rolling_window=True)
        self.assertFalse(regress["written"])
        self.assertTrue(regress["errors"])

        # main() senza --seasons usa la finestra derivata (oggi: 2223..2627)
        original = update_all_xg_db.fetch_league
        seen = {}

        def spy(sd_league, seasons, *a, **k):
            seen["seasons"] = list(seasons)
            raise RuntimeError("stop")
        update_all_xg_db.fetch_league = spy
        try:
            update_all_xg_db.main(["--league", "Serie A", "--output-dir", str(self.db), "--dry-run"])
        finally:
            update_all_xg_db.fetch_league = original
        self.assertEqual(seen["seasons"], update_all_xg_db.derive_seasons(config.CURRENT_SEASON_START_YEAR))

    # ------------------------------------------------------------------ 4
    def test_4_derivazione_medie_pre_stagione_non_fallisce(self):
        league = "Premier League"
        avg_path = update_xg.averages_path(league, self.db)
        before = Path(avg_path).read_bytes()
        # luglio 2027: la stagione 2027 non e' in archivio -> uscita 0, file intatto
        rc = update_xg.main(["--season", "2027", "--league", league, "--database-dir", str(self.db)])
        self.assertEqual(rc, 0)
        self.assertEqual(Path(avg_path).read_bytes(), before)
        res = update_xg.derive_league(league, 2027, database_dir=self.db)
        self.assertTrue(res["season_not_started"])
        self.assertFalse(res["written"])
        self.assertEqual(res["errors"], [])

        # fixture pubblicate ma nessuna giocata (1° agosto): ancora pre-stagione
        records = load_archive(league, self.db)
        fixtures = [dict(r, season=2027, id=8_000_000 + i, date="2027-08-14 19:00:00",
                         is_result=False, home_goals=None, away_goals=None, home_xg=None, away_xg=None)
                    for i, r in enumerate(records[:40])]
        with open(update_xg.archive_path(league, self.db), "w", encoding="utf-8") as f:
            json.dump(records + fixtures, f)
        res = update_xg.derive_league(league, 2027, database_dir=self.db)
        self.assertTrue(res["season_not_started"], res)
        self.assertEqual(res["errors"], [])

        # prima giornata giocata (>= 10 squadre): il file viene scritto
        with open(update_xg.archive_path(league, self.db), "w", encoding="utf-8") as f:
            json.dump(records + _fake_2027_matchday(records), f)
        rc = update_xg.main(["--season", "2027", "--league", league, "--database-dir", str(self.db)])
        self.assertEqual(rc, 0)
        data = json.loads(Path(avg_path).read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(data), 10)
        self.assertNotEqual(Path(avg_path).read_bytes(), before)

        # una sola partita giocata (venerdi' di apertura): tollerata, non e' un errore
        with open(update_xg.archive_path(league, self.db), "w", encoding="utf-8") as f:
            json.dump(records + _fake_2027_matchday(records)[:1], f)
        res = update_xg.derive_league(league, 2027, database_dir=self.db)
        self.assertTrue(res.get("season_starting"), res)
        self.assertEqual(res["errors"], [])

    # ------------------------------------------------------------------ 5
    def test_5_ppda_finestra_mobile(self):
        seasons = ppda.derive_seasons(2027)
        base = [{"season": y, "id": i, "date": f"{y}-09-01 18:00:00"} for y in range(2022, 2027) for i in range(3)]
        os.makedirs(self.db / "ppda", exist_ok=True)
        path = ppda.archive_path(ppda.PPDA_KIND, "Ligue 1", str(self.db / "ppda"))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(base, f)
        schedule = [{"season": y, "id": i} for y in range(2023, 2027) for i in range(3)]
        adj = ppda._rolling_window_adjustments("Ligue 1", seasons, seasons, schedule,
                                               [ppda.PPDA_KIND], str(self.db / "ppda"), None)
        self.assertEqual(adj["season_not_started"], 2027)
        self.assertEqual(adj["seasons"], ["2324", "2425", "2526", "2627"])
        self.assertTrue(adj["allow_dropping_seasons"])
        self.assertEqual(adj["seasons_aged_out"], [2022])
        # agosto: la 2027 compare nel calendario -> resta richiesta
        adj = ppda._rolling_window_adjustments("Ligue 1", seasons, seasons,
                                               schedule + [{"season": 2027, "id": 99}],
                                               [ppda.PPDA_KIND], str(self.db / "ppda"), None)
        self.assertIsNone(adj["season_not_started"])
        self.assertEqual(adj["seasons"], seasons)
        # --seasons esplicito: il parser non applica la finestra (default None)
        self.assertIsNone(ppda.build_parser().parse_args([]).seasons)

    # ------------------------------------------------------------------ 6
    def test_6_market_values_e_alias_non_bloccano(self):
        df = pd.DataFrame({
            "Date": ["21/08/2027", "22/08/2027"],
            "HomeTeam": ["Inter", "Neopromossa FC"],
            "AwayTeam": ["Bayern Munich", "Nott'm Forest"],
        })
        missing = season_rollover.teams_without_market_value(df)
        self.assertEqual(missing, ["Neopromossa"] if "Neopromossa" not in config.MARKET_VALUES else [])
        # alias: ogni voce della tabella e' raggiungibile dal nome canonico che
        # produce clean_name sui CSV (le 4 chiavi legacy non canoniche hanno il
        # gemello canonico allo stesso valore) e i canonici sono punti fissi.
        for name, value in config.MARKET_VALUES.items():
            canon = clean_name(name)
            self.assertIn(canon, config.MARKET_VALUES, name)
            self.assertEqual(config.MARKET_VALUES[canon], value, name)
            self.assertEqual(clean_name(canon), canon, name)
        # il fattore mercato di produzione resta definito per una squadra ignota (default 50)
        import math
        val = config.MARKET_VALUES.get("Neopromossa", 50)
        mkt = max(0.85, min(1.25, 1 + (math.log10(max(val, 10)) - 2) / 4))
        self.assertAlmostEqual(mkt, 0.925, places=3)


if __name__ == "__main__":
    unittest.main()
