"""Presidio della cartella `audit/data/football_data_storico/` (punti B e C).

Regola dichiarata: un test che dipende dai 25 CSV storici (football-data, 5
stagioni × 5 leghe) deve FALLIRE con messaggio esplicito quando la cartella ne
contiene solo una parte, e SALTARE solo quando è vuota (nessuno dei 25 CSV).
Nessun numero di replica de-vig viene prodotto finché la cartella non è completa.
"""

from __future__ import annotations

import os
import unittest

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "football_data_storico")

# Percorsi attesi relativi a DATA_DIR (README della cartella): 5 stagioni × 5 leghe.
STAGIONI = (("1718", "2017/18"), ("1819", "2018/19"), ("1920", "2019/20"),
            ("2021", "2020/21"), ("2122", "2021/22"))
LEGHE = ("I1.csv", "E0.csv", "SP1.csv", "D1.csv", "F1.csv")


def csv_attesi() -> list[str]:
    return [os.path.join(d, f) for d, _s in STAGIONI for f in LEGHE]


def stato_cartella() -> tuple[list[str], list[str]]:
    """(presenti, mancanti) fra i 25 CSV attesi."""
    presenti, mancanti = [], []
    for rel in csv_attesi():
        (presenti if os.path.isfile(os.path.join(DATA_DIR, rel)) else mancanti).append(rel)
    return presenti, mancanti


class TestFootballDataStorico(unittest.TestCase):
    def test_25_csv_o_cartella_vuota_mai_stato_parziale(self):
        attesi = csv_attesi()
        self.assertEqual(len(attesi), 25)
        presenti, mancanti = stato_cartella()
        if not presenti:
            self.skipTest(
                "audit/data/football_data_storico/ non contiene nessuno dei 25 CSV "
                "storici (5 stagioni × 5 leghe): la replica de-vig del punto 1 "
                "(PR #61) non è eseguibile e nessun numero viene prodotto. "
                "La cartella va riempita con i 25 file originali di football-data.co.uk.")
        if mancanti:
            self.fail(
                f"audit/data/football_data_storico/ è PARZIALE: presenti "
                f"{len(presenti)}/25 CSV storici. Mancano: {', '.join(mancanti)}. "
                f"Completare la cartella con tutti i 25 file oppure svuotarla: "
                f"uno stato parziale non è accettabile (nessun numero di replica "
                f"viene prodotto da una cartella parziale).")
        # Cartella completa: i 25 file ci sono tutti (la replica resta una scelta
        # esplicita di un run dedicato, non di questo test).
        for rel in attesi:
            self.assertGreater(os.path.getsize(os.path.join(DATA_DIR, rel)), 0,
                               f"{rel} è vuoto")


if __name__ == "__main__":
    unittest.main()
