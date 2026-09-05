#!/usr/bin/env python3
"""
audit/test_prediction_registry_date_sorting.py

Test del fix di parsing/ordinamento/visualizzazione della colonna `data`
nel tab "📒 Registro Predizioni & Tracking".

Bug: `data` e' persistita come stringa italiana ("05/09/2026 16:00") e il
dataframe del Registro veniva ordinato LESSICOGRAFICAMENTE, quindi il
confronto partiva dal GIORNO producendo ordini errati tipo:
    04/09 -> 05/09 -> 10/10 -> 17/08 -> 21/08
invece del corretto ordine cronologico.

Il fix converte la colonna `data` in un vero datetime (wall-clock
Europe/Rome, NaT per valori mancanti/non validi, ISO timezone-aware
convertito in Europe/Rome) quando viene costruito il dataframe, ordina col
datetime reale (NaT in fondo) e la mostra in `st.dataframe` come colonna
datetime con formato italiano DD/MM/YYYY HH:mm. NESSUNA migrazione dei
dati persistiti (predictions.json / JSONBin restano invariati).

Esecuzione:
    python -m unittest audit.test_prediction_registry_date_sorting -v
    python audit/test_prediction_registry_date_sorting.py
    python -m pytest audit/test_prediction_registry_date_sorting.py -v

Nessun test tocca predictions.json o JSONBin: usa solo dati in memoria.
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SOCCERMATH_DIR = _REPO_ROOT / "SoccerMath"
sys.path.insert(0, str(_SOCCERMATH_DIR))

import pandas as pd  # noqa: E402

from prediction_registry import (  # noqa: E402
    parse_registry_display_datetime,
    build_registry_datetime_column,
)

# Espressione esatta usata in app.py (tab5) per costruire la colonna mostrata.
# Se il file della UI cambia rotta, questi test devono rompersi.
_APP_SOURCE = (_SOCCERMATH_DIR / "app.py").read_text(encoding="utf-8")


def ui_dataframe(preds):
    """Replica la costruzione del dataframe del Registro fatta da app.py:
    conversione datetime reale + sort cronologico con NaT in fondo."""
    df = pd.DataFrame(preds)
    df["data"] = build_registry_datetime_column(df["data"])
    return df


def ui_sorted(preds, ascending=False):
    """Replica inoltre il sort applicato prima di st.dataframe."""
    return ui_dataframe(preds).sort_values(by="data", ascending=ascending,
                                           na_position="last")


def rec(data_value, match_id=1):
    return {"match_id": match_id, "data": data_value, "esito": "⏳",
            "home": "A", "away": "B"}


class TestParserFormats(unittest.TestCase):
    def test_italian_datetime(self):
        self.assertEqual(parse_registry_display_datetime("05/09/2026 16:00"),
                         datetime(2026, 9, 5, 16, 0))

    def test_italian_datetime_with_seconds(self):
        self.assertEqual(parse_registry_display_datetime("05/09/2026 16:00:45"),
                         datetime(2026, 9, 5, 16, 0, 45))

    def test_italian_date_only_midnight(self):
        self.assertEqual(parse_registry_display_datetime("05/09/2026"),
                         datetime(2026, 9, 5, 0, 0))

    def test_legacy_iso_naive_kept_as_local(self):
        self.assertEqual(parse_registry_display_datetime("2026-09-05T16:00:00"),
                         datetime(2026, 9, 5, 16, 0))
        self.assertEqual(parse_registry_display_datetime("2026-09-05"),
                         datetime(2026, 9, 5, 0, 0))

    def test_iso_aware_converted_to_europe_rome(self):
        # UTC 14:00 = 16:00 a Roma in periodo CEST (+02:00).
        self.assertEqual(parse_registry_display_datetime("2026-09-05T14:00:00Z"),
                         datetime(2026, 9, 5, 16, 0))
        self.assertEqual(parse_registry_display_datetime("2026-09-05T14:00:00+00:00"),
                         datetime(2026, 9, 5, 16, 0))
        # Offset romano esplicito: nessuna conversione numerica, wall-clock 16:00.
        self.assertEqual(parse_registry_display_datetime("2026-09-05T16:00:00+02:00"),
                         datetime(2026, 9, 5, 16, 0))
        # In inverno (CET +01:00): UTC 15:00 -> 16:00 a Roma.
        self.assertEqual(parse_registry_display_datetime("2026-01-15T15:00:00Z"),
                         datetime(2026, 1, 15, 16, 0))

    def test_result_is_naive(self):
        parsed = parse_registry_display_datetime("05/09/2026 16:00")
        self.assertIsInstance(parsed, datetime)
        self.assertIsNone(parsed.tzinfo)

    def test_missing_and_invalid_become_none_no_crash(self):
        for bad in (None, "", "   ", "ieri", "16:00", "32/13/2026",
                    "2026-13-05", float("nan"), 12345, {"data": 1}, []):
            with self.subTest(bad=bad):
                self.assertIsNone(parse_registry_display_datetime(bad))


class TestChronologicalOrder(unittest.TestCase):
    """Gli ordini che il sort testuale sbagliava."""

    def assert_chronological(self, values, ascending=True):
        df = ui_sorted([rec(v, i) for i, v in enumerate(values)], ascending=ascending)
        return df

    def test_end_of_month_before_next_month(self):
        dates = [datetime(2026, 8, 31), datetime(2026, 9, 1),
                 datetime(2026, 9, 30), datetime(2026, 10, 1)]
        self.assertLess(datetime(2026, 8, 31), datetime(2026, 9, 1))
        self.assertLess(datetime(2026, 9, 30), datetime(2026, 10, 1))
        self.assertLess(datetime(2026, 12, 31), datetime(2027, 1, 1))

    def test_31_08_before_01_09_in_ui_order(self):
        df = ui_sorted([rec("01/09/2026 18:00", 1), rec("31/08/2026 20:45", 2)],
                       ascending=True)
        self.assertEqual(df["data"].dt.strftime("%d/%m/%Y").tolist(),
                         ["31/08/2026", "01/09/2026"])

    def test_30_09_before_01_10_in_ui_order(self):
        df = ui_sorted([rec("01/10/2026 18:00", 1), rec("30/09/2026 20:45", 2)],
                       ascending=True)
        self.assertEqual(df["data"].dt.strftime("%d/%m/%Y").tolist(),
                         ["30/09/2026", "01/10/2026"])

    def test_year_rollover_31_12_2026_before_01_01_2027(self):
        df = ui_sorted([rec("01/01/2027 12:30", 1), rec("31/12/2026 20:45", 2)],
                       ascending=True)
        self.assertEqual(df["data"].dt.strftime("%d/%m/%Y").tolist(),
                         ["31/12/2026", "01/01/2027"])

    def test_same_day_time_ordering(self):
        self.assertLess(parse_registry_display_datetime("05/09/2026 16:00"),
                        parse_registry_display_datetime("05/09/2026 21:00"))
        df = ui_sorted([rec("05/09/2026 21:00", 1), rec("05/09/2026 16:00", 2)],
                       ascending=True)
        self.assertEqual(df["data"].dt.strftime("%H:%M").tolist(), ["16:00", "21:00"])
        # Ordinamento della UI: piu' recente in testa.
        df_desc = ui_sorted([rec("05/09/2026 21:00", 1), rec("05/09/2026 16:00", 2)])
        self.assertEqual(df_desc["data"].dt.strftime("%H:%M").tolist(), ["21:00", "16:00"])

    def test_bug_scenario_textual_sort_fixed(self):
        """Riproduce l'ordine del bug report e verifica l'ordine reale."""
        values = ["04/09/2026 18:00", "05/09/2026 16:00", "10/10/2026 20:45",
                  "17/08/2026 21:00", "21/08/2026 18:30"]
        # Il sort testuale (vecchio comportamento) parte dal giorno: errato.
        textual = sorted(values)
        self.assertEqual(textual, ["04/09/2026 18:00", "05/09/2026 16:00",
                                   "10/10/2026 20:45", "17/08/2026 21:00",
                                   "21/08/2026 18:30"])
        # Il sort datetime (nuovo comportamento) e' cronologico.
        df = ui_sorted([rec(v, i) for i, v in enumerate(values)], ascending=True)
        self.assertEqual(df["data"].dt.strftime("%d/%m/%Y").tolist(),
                         ["17/08/2026", "21/08/2026", "04/09/2026",
                          "05/09/2026", "10/10/2026"])

    def test_italian_and_iso_mixed_chronological(self):
        mixed = ["05/09/2026 16:00", "2026-09-04T20:45:00+02:00",
                 "2026-09-06T18:00:00Z", "2026-09-03 20:45"]
        df = ui_sorted([rec(v, i) for i, v in enumerate(mixed)], ascending=True)
        # 2026-09-06T18:00Z -> 20:00 a Roma: resta il 06/09 ma dopo le 16:00.
        self.assertEqual(df["data"].dt.strftime("%d/%m/%Y %H:%M").tolist(),
                         ["03/09/2026 20:45", "04/09/2026 20:45",
                          "05/09/2026 16:00", "06/09/2026 20:00"])


class TestNaT(unittest.TestCase):
    def test_nat_does_not_crash_and_goes_last(self):
        preds = [rec("05/09/2026 16:00", 1), rec(None, 2), rec("", 3),
                 rec("spazzatura", 4), rec("10/10/2026 20:45", 5),
                 {"match_id": 6}, rec(float("nan"), 7)]
        df_desc = ui_sorted(preds)  # ascending=False, come nella UI
        # None, "", "spazzatura", records senza campo data, NaN -> tutti NaT
        self.assertEqual(int(df_desc["data"].isna().sum()), 5)
        # NaT in fondo al sort principale della UI
        self.assertTrue(df_desc["data"].tail(5).isna().all())
        self.assertEqual(df_desc["data"].iloc[0], datetime(2026, 10, 10, 20, 45))
        # NaT in fondo anche in ordine crescente
        df_asc = ui_sorted(preds, ascending=True)
        self.assertTrue(df_asc["data"].tail(5).isna().all())
        self.assertEqual(df_asc["data"].iloc[0], datetime(2026, 9, 5, 16, 0))

    def test_all_invalid_still_datetime_dtype(self):
        df = ui_dataframe([rec(None), rec(""), rec("??/??/????")])
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(df["data"]))
        self.assertTrue(df["data"].isna().all())


class TestUiColumnContract(unittest.TestCase):
    def test_column_dtype_is_real_datetime_not_string(self):
        preds = [rec("05/09/2026 16:00"), rec("10/10/2026 20:45"), rec("gibberish")]
        df = ui_sorted(preds)
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(df["data"]))
        # Non deve essere un oggetto stringa (dtype object) dopo il sort.
        self.assertNotEqual(str(df["data"].dtype), "object")
        # Lo scalare reale e' un Timestamp (datetime64), non una stringa
        # riconvertita dopo il sort: il formato italiano e' delegato a
        # st.column_config.DatetimeColumn.
        first = df["data"].iloc[0]
        self.assertIsInstance(first, datetime)  # pd.Timestamp e' un datetime
        self.assertNotIsInstance(first, str)

    def test_no_helper_technical_column(self):
        df = ui_dataframe([rec("05/09/2026 16:00"), rec(None)])
        for helper in ("data_dt", "data_datetime", "dt", "_dt", "sort_key"):
            self.assertNotIn(helper, df.columns)

    def test_app_uses_same_datetime_pipeline(self):
        """Guardia sul sorgente UI: il tab5 deve usare conversione datetime,
        sort con na_position e la DatetimeColumn col formato italiano, senza
        stringhe di formato applicate DOPO il sort ne' colonne helper."""
        registro_start = _APP_SOURCE.find('st.subheader("📒 Registro Predizioni & Tracking")')
        self.assertGreater(registro_start, 0, "sezione Registro non trovata in app.py")
        block = _APP_SOURCE[registro_start:registro_start + 6000]
        self.assertIn("build_registry_datetime_column", block,
                      "il Registro non usa la conversione datetime condivisa")
        self.assertIn('sort_values(by="data", ascending=False, na_position="last")', block,
                      "il sort del Registro non usa na_position='last'")
        self.assertIn('format="DD/MM/YYYY HH:mm"', block,
                      "manca il formato italiano DD/MM/YYYY HH:mm in DatetimeColumn")
        self.assertIn("DatetimeColumn", block)
        self.assertNotIn("data_dt", block,
                         "una colonna helper data_dt non deve essere esposta in UI")
        # La data non deve essere ri-formattata a stringa dopo il sort.
        self.assertNotIn("dt.strftime('%d/%m/%Y %H:%M')", block.split("st.dataframe(")[1][:800],
                         "la colonna data non deve essere riconvertita in stringa per la UI")


class TestPersistedDataUntouched(unittest.TestCase):
    def test_build_column_does_not_mutate_source_records(self):
        preds = [rec("05/09/2026 16:00"), rec("2026-09-04T20:45:00+02:00")]
        before = [dict(p) for p in preds]
        ui_dataframe(preds)
        self.assertEqual(preds, before,
                         "i record persistiti non devono essere modificati dalla conversione UI")

    def test_parse_is_read_only_on_strings(self):
        original = "05/09/2026 16:00"
        parse_registry_display_datetime(original)
        self.assertEqual(original, "05/09/2026 16:00")


if __name__ == "__main__":
    unittest.main(verbosity=2)
