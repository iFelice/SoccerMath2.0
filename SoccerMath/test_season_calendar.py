"""
test_season_calendar.py - UN SOLO confine di stagione in tutta la pipeline.

Prima dell'unificazione convivevano ``mese >= 7`` (config, season_rollover,
xg_archive) e ``mese >= 8`` (app.calcola_stagione_calcolo,
prediction_registry.season_from_entry). Questi test fissano la regola scelta
(1° luglio, verificata sul calendario reale delle 5 leghe: nessuna partita a
luglio in 8.834 partite 2022/23-2026/27) e la sua coerenza fra i moduli.
"""
import os
import sys
import unittest
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

import config  # noqa: E402
import season_calendar as sc  # noqa: E402
from season_rollover import _season_of  # noqa: E402
from prediction_registry import season_from_entry  # noqa: E402


class TestSeasonCalendar(unittest.TestCase):
    def test_confine_primo_luglio(self):
        self.assertEqual(sc.SEASON_START_MONTH, 7)
        self.assertEqual(sc.season_start_year(2027, 6), 2026)
        self.assertEqual(sc.season_start_year(2027, 7), 2027)
        self.assertEqual(sc.season_start_year(2027, 8), 2027)
        self.assertEqual(sc.season_start_year_of(date(2027, 6, 30)), 2026)
        self.assertEqual(sc.season_start_year_of(datetime(2027, 7, 1, 0, 0, tzinfo=timezone.utc)), 2027)

    def test_etichette_e_codici(self):
        self.assertEqual(sc.season_label(2026), "2026/2027")
        self.assertEqual(sc.season_label(2026, short=True), "2026/27")
        self.assertEqual(sc.soccerdata_season_code(2026), "2627")
        self.assertEqual(sc.soccerdata_season_code(2029), "2930")
        self.assertEqual(sc.season_window(2026), [2022, 2023, 2024, 2025, 2026])
        self.assertEqual(sc.season_window(2027, 3), [2025, 2026, 2027])
        for value, expected in (("2026/2027", 2026), ("2026/27", 2026), ("2627", 2026),
                                (2026, 2026), ("2026", 2026), ("", None), (None, None), ("xx", None)):
            self.assertEqual(sc.parse_season_start_year(value), expected, value)

    def test_mese_non_valido(self):
        with self.assertRaises(ValueError):
            sc.season_start_year(2027, 13)
        with self.assertRaises(ValueError):
            sc.season_window(2027, 0)

    def test_calendario_reale_nessuna_partita_a_luglio(self):
        """Sui CSV reali le due regole storiche (>=7 e >=8) coincidono al 100%:
        il confine di luglio cade nella zona morta fra due stagioni."""
        db = config.DATABASE_DIR
        files = [f for f in os.listdir(db) if f.endswith(".csv")]
        self.assertTrue(files)
        n = 0
        for name in files:
            df = pd.read_csv(os.path.join(db, name), usecols=["Date"], on_bad_lines="skip")
            dates = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce").dropna()
            n += len(dates)
            self.assertFalse((dates.dt.month == 7).any(), f"{name}: partite a luglio")
            with_7 = dates.dt.year - (dates.dt.month < 7).astype(int)
            with_8 = dates.dt.year - (dates.dt.month < 8).astype(int)
            self.assertTrue((with_7 == with_8).all(), f"{name}: le due regole divergono")
        self.assertGreater(n, 5000)


class TestCoerenzaFraModuli(unittest.TestCase):
    CASI = (
        ("30/06/2027", "2026/2027"),
        ("01/07/2027", "2027/2028"),   # prima: app/registro dicevano 2026/2027
        ("15/07/2027", "2027/2028"),
        ("01/08/2027", "2027/2028"),
        ("15/08/2026", "2026/2027"),
        ("24/05/2027", "2026/2027"),
    )

    def test_config_rollover_app_registro_identici(self):
        import app  # noqa: WPS433  (import pesante ma necessario: e' la funzione di produzione)
        for giorno, atteso in self.CASI:
            d = datetime.strptime(giorno, "%d/%m/%Y")
            self.assertEqual(config.get_current_season_start_year(d), int(atteso[:4]), giorno)
            self.assertEqual(app.calcola_stagione_calcolo(giorno + " 20:45"), atteso, giorno)
            self.assertEqual(app.calcola_stagione_calcolo(d.isoformat()), atteso, giorno)
            self.assertEqual(season_from_entry({"data": giorno + " 20:45"}), atteso, giorno)
            self.assertEqual(int(_season_of(pd.Series([pd.Timestamp(d)])).iloc[0]), int(atteso[:4]), giorno)

    def test_xg_archive_deriva_la_stagione_dal_cutoff_con_la_stessa_regola(self):
        from xg_archive import season_point_in_time_averages
        agg = season_point_in_time_averages("Serie A", cutoff=datetime(2027, 7, 15, tzinfo=timezone.utc),
                                            records=[])
        self.assertEqual(agg.season, 2027)
        agg = season_point_in_time_averages("Serie A", cutoff=datetime(2027, 6, 15, tzinfo=timezone.utc),
                                            records=[])
        self.assertEqual(agg.season, 2026)


class TestConfigDerivato(unittest.TestCase):
    def test_historical_seasons_non_scritte_a_mano(self):
        self.assertEqual(config.historical_seasons(2026),
                         ["2025/2026", "2024/2025", "2023/2024", "2022/2023"])
        self.assertEqual(config.historical_seasons(2027),
                         ["2026/2027", "2025/2026", "2024/2025", "2023/2024"])
        # la finestra corrente + storiche e' sempre di SEASON_WINDOW stagioni
        self.assertEqual(len(config.ALL_SEASONS), sc.SEASON_WINDOW)
        self.assertEqual(config.ALL_SEASONS[0], config.CURRENT_SEASON)
        self.assertEqual(config.CURRENT_SEASON, sc.season_label(config.CURRENT_SEASON_START_YEAR))

    def test_derive_seasons_soccerdata(self):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import update_all_xg_db
        self.assertEqual(update_all_xg_db.derive_seasons(2026), ["2223", "2324", "2425", "2526", "2627"])
        self.assertEqual(update_all_xg_db.derive_seasons(2027), ["2324", "2425", "2526", "2627", "2728"])
        # la lista di modulo e' derivata dalla stagione corrente di config
        self.assertEqual(update_all_xg_db.SEASONS,
                         update_all_xg_db.derive_seasons(config.CURRENT_SEASON_START_YEAR))


if __name__ == "__main__":
    unittest.main()
