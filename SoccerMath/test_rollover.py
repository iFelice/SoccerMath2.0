"""
Test per l'archiviazione automatica di fine stagione (season_rollover.py).
Esegui con: python -m pytest SoccerMath/test_rollover.py -v
Oppure semplicemente: python SoccerMath/test_rollover.py
"""
import sys
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd

from season_rollover import run_rollover, rollover_league

HEADER = "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,Matchday"


def _row(div, date, home, away, gh, ga, md):
    # 9 campi, coerenti con HEADER (Div,Date,Time,Home,Away,FTHG,FTAG,FTR,Matchday)
    ftr = "H" if gh > ga else ("A" if ga > gh else "D")
    return f"{div},{date},,{home},{away},{gh},{ga},{ftr},{md}"


def _write(path, lines):
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read(path):
    return pd.read_csv(path)


class TestRollover(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    # 1) Esempio del requisito: a luglio 2027 il Live 2026/27 diventa _2026.csv
    #    e il Live riparte da 0 (solo intestazione).
    def test_luglio_2027_archivia_2026_e_live_riparte_da_zero(self):
        live = self.db / "SerieA_Live.csv"
        _write(live, [
            HEADER,
            _row("I1", "22/08/2026", "Udinese", "Como", 1, 1, 1),
            _row("I1", "24/05/2027", "Inter", "Napoli", 2, 0, 38),
        ])
        n = run_rollover(db_dir=self.db, now=datetime(2027, 7, 15))
        self.assertEqual(n, 1)
        archivio = self.db / "SerieA_2026.csv"
        self.assertTrue(archivio.exists(), "l'archivio _2026 deve essere creato")
        df_arch = _read(archivio)
        self.assertEqual(len(df_arch), 2)  # entrambe le partite 2026/27
        df_live = _read(live)
        self.assertEqual(len(df_live), 0, "il Live deve ripartire da 0")
        self.assertEqual(list(df_live.columns), list(df_arch.columns), "intestazione del Live preservata")

    # 2) Live misto (fine stagione precedente + inizio nuova): solo le vecchie vanno in archivio
    def test_live_misto_solo_stagione_vecchia_in_archivio(self):
        live = self.db / "Premier_Live.csv"
        _write(live, [
            HEADER,
            _row("E0", "10/05/2026", "Arsenal", "Chelsea", 1, 0, 36),
            _row("E0", "15/08/2026", "Arsenal", "Coventry City", 3, 0, 1),  # nuova stagione
        ])
        run_rollover(db_dir=self.db, now=datetime(2026, 8, 30))
        df_arch = _read(self.db / "Premier_2025.csv")
        self.assertEqual(len(df_arch), 1)
        self.assertEqual(df_arch.iloc[0]["AwayTeam"], "Chelsea")
        df_live = _read(live)
        self.assertEqual(len(df_live), 1)
        self.assertEqual(df_live.iloc[0]["AwayTeam"], "Coventry City")

    # 3) Idempotente: eseguito due volte non duplica nulla
    def test_idempotente(self):
        live = self.db / "SerieA_Live.csv"
        _write(live, [
            HEADER,
            _row("I1", "20/09/2026", "Milan", "Juventus", 1, 1, 4),  # stagione corrente: no-op
        ])
        n1 = run_rollover(db_dir=self.db, now=datetime(2027, 1, 10))
        n2 = run_rollover(db_dir=self.db, now=datetime(2027, 1, 10))
        self.assertEqual((n1, n2), (0, 0))
        self.assertFalse((self.db / "SerieA_2026.csv").exists())

    # 4) Unione con archivio esistente + deduplica dello stesso match
    def test_unione_con_archivio_esistente_e_dedup(self):
        arch = self.db / "Bundesliga_2025.csv"
        _write(arch, [
            HEADER,
            _row("D1", "15/08/2025", "Bayern", "Stuttgart", 3, 1, 1),
            _row("D1", "22/08/2025", "Dortmund", "Lyon", 2, 2, 2),
        ])
        live = self.db / "Bundesliga_Live.csv"
        _write(live, [
            HEADER,
            _row("D1", "15/08/2025", "Bayern", "Stuttgart", 3, 1, 1),  # duplicato esatto
            _row("D1", "16/05/2026", "Lyon", "Bremen", 0, 2, 34),      # nuova da archiviare
        ])
        n = run_rollover(db_dir=self.db, now=datetime(2026, 8, 30))  # stagione 2025/26 conclusa
        self.assertEqual(n, 1)
        df_arch = _read(arch)
        self.assertEqual(len(df_arch), 3, "dedup: 2 vecchie + 1 nuova, il doppione va scartato")

    # 5) Live assente / vuoto / solo intestazione: nessun errore, nessuna azione
    def test_live_mancante_o_vuoto(self):
        n = run_rollover(db_dir=self.db, now=datetime(2027, 7, 15))
        self.assertEqual(n, 0)
        (self.db / "Ligue1_Live.csv").write_text("", encoding="utf-8")
        (self.db / "LaLiga_Live.csv").write_text(HEADER + "\n", encoding="utf-8")
        n = run_rollover(db_dir=self.db, now=datetime(2027, 7, 15))
        self.assertEqual(n, 0)
        self.assertFalse((self.db / "Ligue1_2026.csv").exists())

    # 6) La stagione deriva dalla data: agosto 2026 -> 2026 (giu 2026 -> 2025)
    def test_calcolo_stagione_corrente(self):
        from config import get_current_season_start_year
        self.assertEqual(get_current_season_start_year(datetime(2026, 8, 30)), 2026)
        self.assertEqual(get_current_season_start_year(datetime(2026, 6, 20)), 2025)
        self.assertEqual(get_current_season_start_year(datetime(2027, 7, 1)), 2027)
        self.assertEqual(get_current_season_start_year(datetime(2027, 1, 15)), 2026)

    # 7) Rollover su un solo campionato senza toccare gli altri
    def test_singolo_campionato(self):
        live = self.db / "LaLiga_Live.csv"
        _write(live, [HEADER, _row("SP1", "30/08/2026", "Alaves", "Getafe", 3, 0, 2)])
        report = rollover_league("LaLiga", live, current_season=2026)
        self.assertEqual(report["status"], "noop")


if __name__ == "__main__":
    unittest.main(verbosity=2)
