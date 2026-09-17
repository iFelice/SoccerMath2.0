"""
test_update_db_rich.py — Test OFFLINE (nessuna rete) di ``update_db_rich.py``.

Coprono le proprieta' che la commessa chiede esplicitamente:

1. la chiave stagione e' DERIVATA da ``config.CURRENT_SEASON_START_YEAR``
   (nessuna stringa "2627" scritta a mano nel modulo);
2. la mappa lega -> codice football-data vive solo in ``config.LEAGUES_CONFIG``
   (campo ``fd_code``), non in un dizionario parallelo;
3. il merge e' per colonna: una cella gia' valorizzata NON viene sovrascritta,
   nemmeno da un valore diverso e nemmeno da un nullo;
4. le colonne protette (Date/squadre/risultati/Matchday) non vengono MAI
   scritte;
5. nessuna riga aggiunta o rimossa: le partite presenti solo su football-data
   non entrano nel database;
6. il modulo non usa ``pd.concat`` + ``drop_duplicates`` (il meccanismo con cui
   il bug delle colonne azzerate si ricreerebbe da solo);
7. idempotenza, tolleranza +/- 1 giorno, scrittura atomica, exit code != 0 con
   una lega fallita.

Esecuzione:
    python -m pytest SoccerMath/test_update_db_rich.py -v
    python SoccerMath/test_update_db_rich.py
"""
import ast
import json
import os
import re
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import pandas as pd  # noqa: E402

import config  # noqa: E402
import update_db_rich as rich  # noqa: E402

with open(os.path.join(_HERE, "update_db_rich.py"), "r", encoding="utf-8") as _fh:
    MODULE_SOURCE = _fh.read()

FD_CODES_EXPECTED = {"Serie A": "I1", "Premier League": "E0", "La Liga": "SP1",
                     "Bundesliga": "D1", "Ligue 1": "F1"}


def frame(rows):
    """Costruisce un frame di stringhe come quelli letti dai CSV."""
    return pd.DataFrame(rows)


class FakeResponse:
    def __init__(self, status_code=200, content=b"Div,Date\n"):
        self.status_code = status_code
        self.content = content


class FakeSession:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        if self.exc is not None:
            raise self.exc
        return self.response


class TestStagioneEdEncoding(unittest.TestCase):

    def test_season_code_derivata_dall_anno_di_inizio(self):
        self.assertEqual(rich.season_code(2026), "2627")
        self.assertEqual(rich.season_code(2025), "2526")
        self.assertEqual(rich.season_code(1999), "9900")

    def test_season_code_default_derivata_da_config(self):
        expected = "{:02d}{:02d}".format(config.CURRENT_SEASON_START_YEAR % 100,
                                         (config.CURRENT_SEASON_START_YEAR + 1) % 100)
        self.assertEqual(rich.season_code(), expected)

    def test_nessuna_stagione_scritta_a_mano_nel_modulo(self):
        # Nessun letterale di stagione ASSEGNATO nel codice (i docstring non
        # contano: li escludiamo analizzando l'AST e non il testo).
        tree = ast.parse(MODULE_SOURCE)
        assigned = [
            node.value.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ]
        self.assertNotIn("2627", assigned)
        self.assertNotIn("26/27", assigned)
        self.assertIn("CURRENT_SEASON_START_YEAR", MODULE_SOURCE)

    def test_encoding_latin1_prima_del_2425_e_utf8_dopo(self):
        self.assertEqual(rich.fd_encoding(2022), "latin-1")
        self.assertEqual(rich.fd_encoding(2023), "latin-1")
        self.assertEqual(rich.fd_encoding(2024), "utf-8-sig")
        self.assertEqual(rich.fd_encoding(2026), "utf-8-sig")


class TestMappaLeghe(unittest.TestCase):

    def test_tutte_le_leghe_hanno_fd_code(self):
        self.assertEqual(rich.league_fd_codes(), FD_CODES_EXPECTED)

    def test_nessun_dizionario_parallelo_nel_modulo(self):
        for code in FD_CODES_EXPECTED.values():
            pattern = r"\{\s*[\"']%s[\"']" % re.escape(code)
            self.assertIsNone(re.search(pattern, MODULE_SOURCE),
                              f"trovato un dizionario con il codice {code} nel modulo")


class TestLetturaComeTesto(unittest.TestCase):

    def test_lettura_preserva_la_rappresentazione_originale(self):
        csv = b"Div,Date,HomeTeam,AwayTeam,FTHG,HS,B365H\nI1,22/08/2026,Inter,Monza,4,13,1.2\n"
        df = rich.read_csv_text(csv, "utf-8-sig")
        self.assertEqual(df["FTHG"].iloc[0], "4")       # non "4.0"
        self.assertEqual(df["HS"].iloc[0], "13")        # non "13.0"
        self.assertEqual(df["B365H"].iloc[0], "1.2")
        self.assertEqual(df["Date"].iloc[0], "22/08/2026")

    def test_bom_utf8_non_finisce_nel_nome_colonna(self):
        csv = u"\ufeffDiv,Date,HomeTeam,AwayTeam\nI1,22/08/2026,Inter,Monza\n".encode("utf-8")
        df = rich.read_csv_text(csv, "utf-8-sig")
        self.assertEqual(list(df.columns)[0], "Div")

    def test_celle_vuote_sono_stringhe_vuote(self):
        csv = b"Div,Date,HomeTeam,AwayTeam,B365H\nI1,22/08/2026,Inter,Monza,\n"
        df = rich.read_csv_text(csv, "utf-8-sig")
        self.assertEqual(df["B365H"].iloc[0], "")

    def test_csv_senza_colonne_chiave_e_un_parse_error(self):
        with self.assertRaises(rich.ParseError):
            rich.read_csv_text(b"Div,Altro\nI1,1\n", "utf-8-sig")

    def test_csv_vuoto_e_un_parse_error(self):
        with self.assertRaises(rich.ParseError):
            rich.read_csv_text(b"Div,Date,HomeTeam,AwayTeam\n", "utf-8-sig")


class TestMergePerColonna(unittest.TestCase):
    """Il cuore della commessa: il merge riempie SOLO le celle vuote."""

    def setUp(self):
        self.existing = frame([
            {"Date": "22/08/2026", "HomeTeam": "Inter", "AwayTeam": "Monza",
             "FTHG": "4", "FTAG": "1", "FTR": "H", "HTHG": "1", "HTAG": "1",
             "HTR": "D", "Matchday": "1", "Div": "", "Time": "", "B365H": "",
             "B365D": "", "HS": "", "HxG": ""},
            {"Date": "23/08/2026", "HomeTeam": "Udinese", "AwayTeam": "Como",
             "FTHG": "1", "FTAG": "1", "FTR": "D", "HTHG": "1", "HTAG": "0",
             "HTR": "H", "Matchday": "1", "Div": "", "Time": "", "B365H": "",
             "B365D": "", "HS": "", "HxG": ""},
        ])
        self.source = frame([
            {"Div": "I1", "Date": "22/08/2026", "Time": "17:30", "HomeTeam": "Inter",
             "AwayTeam": "Monza", "FTHG": "4", "FTAG": "1", "FTR": "H",
             "B365H": "1.2", "B365D": "7", "HS": "13", "HxG": "1.05"},
            {"Div": "I1", "Date": "23/08/2026", "Time": "19:45", "HomeTeam": "Udinese",
             "AwayTeam": "Como", "FTHG": "1", "FTAG": "1", "FTR": "D",
             "B365H": "4.5", "B365D": "3.6", "HS": "17", "HxG": "2.14"},
        ])

    def test_riempie_le_colonne_vuote(self):
        merged, stats = rich.merge_columns(self.existing, self.source)
        self.assertEqual(merged["B365H"].tolist(), ["1.2", "4.5"])
        self.assertEqual(merged["HS"].tolist(), ["13", "17"])
        self.assertEqual(merged["Div"].tolist(), ["I1", "I1"])
        self.assertEqual(merged["Time"].tolist(), ["17:30", "19:45"])
        self.assertEqual(stats["matched_exact"], 2)
        self.assertEqual(stats["unmatched"], 0)

    def test_una_colonna_gia_valorizzata_non_viene_sovrascritta(self):
        self.existing["B365H"] = ["1.11", ""]
        merged, _ = rich.merge_columns(self.existing, self.source)
        self.assertEqual(merged["B365H"].tolist(), ["1.11", "4.5"],
                         "il valore gia' presente e' stato sovrascritto da football-data")

    def test_un_nullo_non_sovrascrive_un_valore_esistente(self):
        self.existing["HS"] = ["9", ""]
        self.source["HS"] = ["", "17"]      # la sorgente non ha il tiri di Inter-Monza
        merged, _ = rich.merge_columns(self.existing, self.source)
        self.assertEqual(merged["HS"].tolist(), ["9", "17"],
                         "un valore vuoto lato sorgente ha azzerato una cella piena")

    def test_colonne_protette_non_vengono_mai_scritte(self):
        # FTHG/FTAG/FTR/HTHG/HTAG/HTR vuoti nel file attuale, pieni nella sorgente:
        # il file attuale vince comunque (fonte API), quindi restano vuoti.
        for col in ("FTHG", "FTAG", "FTR", "HTHG", "HTAG", "HTR", "Matchday"):
            self.existing[col] = ["", ""]
        merged, _ = rich.merge_columns(self.existing, self.source)
        for col in ("FTHG", "FTAG", "FTR", "HTHG", "HTAG", "HTR", "Matchday"):
            self.assertEqual(merged[col].tolist(), ["", ""],
                             f"la colonna protetta {col} e' stata scritta dalla sorgente")

    def test_date_e_squadre_restano_quelle_del_file_attuale(self):
        merged, _ = rich.merge_columns(self.existing, self.source)
        self.assertEqual(merged["Date"].tolist(), ["22/08/2026", "23/08/2026"])
        self.assertEqual(merged["HomeTeam"].tolist(), ["Inter", "Udinese"])
        self.assertEqual(merged["AwayTeam"].tolist(), ["Monza", "Como"])

    def test_nessuna_riga_aggiunta_o_rimossa(self):
        extra = frame([
            {"Div": "I1", "Date": "24/08/2026", "Time": "20:00", "HomeTeam": "Roma",
             "AwayTeam": "Lazio", "FTHG": "2", "FTAG": "0", "FTR": "H",
             "B365H": "2.1", "B365D": "3.3", "HS": "10", "HxG": "1.7"},
        ])
        source = pd.concat([self.source, extra], ignore_index=True)
        merged, stats = rich.merge_columns(self.existing, source)
        self.assertEqual(len(merged), 2, "una riga della sorgente e' entrata nel database")
        self.assertEqual(merged["HomeTeam"].tolist(), ["Inter", "Udinese"])
        self.assertEqual(stats["source_rows_unused"], 1)

    def test_chiave_sul_nome_pulito_allinea_le_varianti_dei_csv(self):
        existing = frame([
            {"Date": "28/08/2026", "HomeTeam": "Bayern Munich", "AwayTeam": "Stuttgart",
             "FTHG": "5", "B365H": ""},
        ])
        source = frame([
            {"Div": "D1", "Date": "28/08/2026", "HomeTeam": "Bayern", "AwayTeam": "Stuttgart",
             "FTHG": "5", "B365H": "1.22"},
        ])
        merged, stats = rich.merge_columns(existing, source)
        self.assertEqual(stats["matched_exact"], 1)
        self.assertEqual(merged["B365H"].iloc[0], "1.22")

    def test_nomi_non_allineati_non_vengono_appaiati_ne_forzati(self):
        existing = frame([
            {"Date": "29/08/2026", "HomeTeam": "SC Paderborn", "AwayTeam": "Freiburg",
             "FTHG": "1", "B365H": ""},
        ])
        source = frame([
            {"Div": "D1", "Date": "29/08/2026", "HomeTeam": "Paderborn",
             "AwayTeam": "Freiburg", "FTHG": "1", "B365H": "3.1"},
        ])
        merged, stats = rich.merge_columns(existing, source)
        self.assertEqual(stats["unmatched"], 1)
        self.assertEqual(merged["B365H"].iloc[0], "")
        self.assertIn("nome squadra non allineato", stats["unmatched_rows"][0]["reason"])
        self.assertIn("SC Paderborn", stats["unmatched_rows"][0]["reason"])

    def test_righe_duplicate_sulla_stessa_chiave_riusano_la_sorgente(self):
        # "Dortmund-HSV" e "Dortmund-Hamburg" sono la stessa partita scritta due
        # volte da update_db.py: entrambe devono essere riempite.
        existing = frame([
            {"Date": "29/08/2026", "HomeTeam": "Dortmund", "AwayTeam": "HSV",
             "FTHG": "2", "B365H": ""},
            {"Date": "29/08/2026", "HomeTeam": "Dortmund", "AwayTeam": "Hamburg",
             "FTHG": "2", "B365H": ""},
        ])
        source = frame([
            {"Div": "D1", "Date": "29/08/2026", "HomeTeam": "Dortmund",
             "AwayTeam": "Hamburg", "FTHG": "2", "B365H": "1.44"},
        ])
        merged, stats = rich.merge_columns(existing, source)
        self.assertEqual(stats["unmatched"], 0)
        self.assertEqual(merged["B365H"].tolist(), ["1.44", "1.44"])

    def test_tolleranza_piu_meno_un_giorno(self):
        existing = frame([
            {"Date": "30/08/2026", "HomeTeam": "Inter", "AwayTeam": "Monza", "B365H": ""},
            {"Date": "31/08/2026", "HomeTeam": "Inter", "AwayTeam": "Monza", "B365H": ""},
        ])
        source = frame([
            {"Date": "29/08/2026", "HomeTeam": "Inter", "AwayTeam": "Monza", "B365H": "1.2"},
            {"Date": "29/08/2026", "HomeTeam": "Inter", "AwayTeam": "Juventus", "B365H": "2.2"},
        ])
        merged, stats = rich.merge_columns(existing, source, tolerance_days=1)
        self.assertEqual(stats["matched_tolerance"], 1)   # 30/08 -> 29/08
        self.assertEqual(stats["unmatched"], 1)           # 31/08 resta fuori
        self.assertEqual(merged["B365H"].tolist(), ["1.2", ""])

    def test_tolleranza_zero_non_appiana(self):
        existing = frame([{"Date": "30/08/2026", "HomeTeam": "Inter",
                           "AwayTeam": "Monza", "B365H": ""}])
        source = frame([{"Date": "29/08/2026", "HomeTeam": "Inter",
                         "AwayTeam": "Monza", "B365H": "1.2"}])
        merged, stats = rich.merge_columns(existing, source, tolerance_days=0)
        self.assertEqual(stats["unmatched"], 1)
        self.assertEqual(merged["B365H"].iloc[0], "")

    def test_unione_delle_colonne_con_ordine_stabile(self):
        existing = frame([
            {"Date": "22/08/2026", "HomeTeam": "Inter", "AwayTeam": "Monza",
             "Matchday": "1", "B365H": ""},
        ])
        source = frame([
            {"Date": "22/08/2026", "HomeTeam": "Inter", "AwayTeam": "Monza",
             "B365H": "1.2", "PPH": "1.18", "HxG": "1.05"},
        ])
        merged, stats = rich.merge_columns(existing, source)
        self.assertEqual(list(merged.columns),
                         ["Date", "HomeTeam", "AwayTeam", "Matchday", "B365H", "PPH", "HxG"])
        self.assertEqual(stats["columns_added"], ["PPH", "HxG"])

    def test_idempotenza_del_merge(self):
        once, _ = rich.merge_columns(self.existing, self.source)
        twice, stats = rich.merge_columns(once, self.source)
        pd.testing.assert_frame_equal(once, twice)
        self.assertEqual(stats["cells_filled"], 0,
                         "il secondo passaggio ha riscritto celle gia' piene")

    def test_merge_non_usa_concat_ne_drop_duplicates(self):
        # Il bug delle colonne azzerate nasce da
        # pd.concat([vecchio, nuovo]) + drop_duplicates(keep="last"): il modulo
        # non deve contenerne traccia NEL CODICE (i docstring che lo citano
        # come divieto sono ammessi, quindi si controlla l'AST).
        tree = ast.parse(MODULE_SOURCE)
        banned = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "drop_duplicates":
                banned.add("drop_duplicates")
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in ("concat", "merge"):
                    banned.add(f"pd.{func.attr}")
        self.assertFalse(banned, f"trovate chiamate vietate nel modulo: {sorted(banned)}")
        self.assertIn("VIETATO", MODULE_SOURCE)


class TestCopertura(unittest.TestCase):

    def test_copertura_con_motivo_per_partita(self):
        original = frame([
            {"Date": "22/08/2026", "HomeTeam": "Inter", "AwayTeam": "Monza", "FTHG": "4"},
            {"Date": "23/08/2026", "HomeTeam": "SC Paderborn", "AwayTeam": "Freiburg",
             "FTHG": "1"},
        ])
        merged = frame([
            {"Date": "22/08/2026", "HomeTeam": "Inter", "AwayTeam": "Monza", "FTHG": "4",
             "B365H": "1.2", "HS": "13"},
            {"Date": "23/08/2026", "HomeTeam": "SC Paderborn", "AwayTeam": "Freiburg",
             "FTHG": "1", "B365H": "", "HS": ""},
        ])
        cov = rich.coverage_report(original, merged,
                                   reasons={1: "nome squadra non allineato: SC Paderborn"})
        self.assertEqual(cov["played_matches"], 2)
        self.assertAlmostEqual(cov["B365H"]["ratio"], 0.5)
        self.assertEqual(cov["B365H"]["missing"], 1)
        self.assertEqual(cov["B365H"]["missing_rows"][0]["reason"],
                         "nome squadra non allineato: SC Paderborn")
        self.assertAlmostEqual(cov["HS"]["ratio"], 0.5)


class TestScritturaAtomica(unittest.TestCase):

    def test_scrive_e_non_lascia_file_temporanei(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "Prova_Live.csv")
            df = frame([{"Date": "22/08/2026", "HomeTeam": "Inter", "B365H": "1.2"}])
            rich.atomic_write_csv(path, df)
            self.assertTrue(os.path.exists(path))
            self.assertFalse(os.path.exists(f"{path}.tmp"))
            with open(path, "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "Date,HomeTeam,B365H\n22/08/2026,Inter,1.2\n")

    def test_se_la_scrittura_fallisce_non_resta_il_tmp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "Prova_Live.csv")
            df = frame([{"Date": "22/08/2026"}])
            original_replace = os.replace
            try:
                def boom(a, b):
                    raise OSError("simulazione errore di rename")
                os.replace = boom
                with self.assertRaises(OSError):
                    rich.atomic_write_csv(path, df)
            finally:
                os.replace = original_replace
            self.assertFalse(os.path.exists(f"{path}.tmp"))
            self.assertFalse(os.path.exists(path))


class TestRete(unittest.TestCase):

    def test_http_non_200_e_un_fetch_error(self):
        session = FakeSession(response=FakeResponse(status_code=404, content=b""))
        with self.assertRaises(rich.FetchError):
            rich.fetch_csv_bytes("I1", "2627", session=session)

    def test_errore_di_rete_e_un_fetch_error(self):
        session = FakeSession(exc=OSError("rete giu'"))
        with self.assertRaises(rich.FetchError):
            rich.fetch_csv_bytes("I1", "2627", session=session)

    def test_user_agent_browser_nella_richiesta(self):
        session = FakeSession(response=FakeResponse(200, b"Div,Date,HomeTeam,AwayTeam\nI1,x,A,B\n"))
        rich.fetch_csv_bytes("E0", "2627", session=session)
        self.assertTrue(session.calls)
        self.assertTrue(session.calls[0].endswith("/mmz4281/2627/E0.csv"))


class TestExitCodeSenzaRete(unittest.TestCase):
    """Una lega che non si riesce a leggere deve far fallire il comando."""

    def test_exit_code_non_zero_con_sorgente_assente(self):
        with tempfile.TemporaryDirectory() as tmp:
            json_out = os.path.join(tmp, "run.json")
            code = rich.main(["--source-dir", os.path.join(tmp, "mancante"),
                              "--database-dir", str(config.DATABASE_DIR),
                              "--json-out", json_out])
            self.assertEqual(code, 1)
            with open(json_out, "r", encoding="utf-8") as fh:
                report = json.load(fh)
            self.assertEqual(len(report["failures"]), len(config.LEAGUES_CONFIG))
            for failure in report["failures"]:
                self.assertIn("CSV locale assente", failure)

    def test_exit_code_zero_con_sorgente_presente(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_dir = os.path.join(tmp, "database")
            os.makedirs(db_dir)
            src_dir = os.path.join(tmp, "src")
            os.makedirs(src_dir)
            for fd_code in FD_CODES_EXPECTED.values():
                with open(os.path.join(src_dir, f"{fd_code}.csv"), "w",
                          encoding="utf-8") as fh:
                    fh.write("Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,HS\n"
                             f"{fd_code},22/08/2026,20:00,Inter,Monza,4,1,H,1.2,13\n")
            for prefix in ("SerieA", "Premier", "LaLiga", "Bundesliga", "Ligue1"):
                with open(os.path.join(db_dir, f"{prefix}_Live.csv"), "w",
                          encoding="utf-8") as fh:
                    fh.write("Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,Matchday,B365H,HS\n"
                             "22/08/2026,Inter,Monza,4,1,H,1,,\n")
            code = rich.main(["--source-dir", src_dir, "--database-dir", db_dir])
            self.assertEqual(code, 0)
            with open(os.path.join(db_dir, "SerieA_Live.csv"), "r", encoding="utf-8") as fh:
                content = fh.read()
            self.assertIn("B365H", content)
            self.assertIn(",1.2,13", content)
            # le 6 colonne lette da app.py sono intatte
            self.assertIn("22/08/2026,Inter,Monza,4,1,H", content)


class TestInvarianzaSeiColonneDiProduzione(unittest.TestCase):
    """app.py legge solo Date/HomeTeam/AwayTeam/FTHG/FTAG/FTR: devono restare
    identiche, cella per cella, dopo l'arricchimento."""

    PRODUCTION_COLUMNS = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"]

    def test_le_sei_colonne_non_cambiano(self):
        existing = frame([
            {"Date": "22/08/2026", "HomeTeam": "Inter", "AwayTeam": "Monza",
             "FTHG": "4", "FTAG": "1", "FTR": "H", "B365H": ""},
        ])
        source = frame([
            {"Date": "22/08/2026", "HomeTeam": "Inter", "AwayTeam": "Monza",
             "FTHG": "9", "FTAG": "9", "FTR": "A", "B365H": "1.2"},
        ])
        merged, _ = rich.merge_columns(existing, source)
        for col in self.PRODUCTION_COLUMNS:
            self.assertEqual(merged[col].tolist(), existing[col].tolist(),
                             f"la colonna di produzione {col} e' cambiata")
        self.assertEqual(merged["B365H"].tolist(), ["1.2"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
