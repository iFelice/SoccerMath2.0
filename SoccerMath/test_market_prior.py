"""
test_market_prior.py - proprieta' del prior xG (modulo di AUDIT, non collegato
all'app: valutato e non adottato, vedi audit/results/market_prior_xg_report.md).

Fissa cio' che rende l'audit credibile: point-in-time rigoroso, regola
dichiarata per le promosse, fattore nello stesso intervallo del fattore
mercato, neutralita' in assenza totale di informazione.
"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from market_prior import XgPriorIndex, XgPriorParams, factor_from_quality  # noqa: E402


def _m(season, mid, day, home, away, hx, ax, played=True):
    return {"season": season, "id": mid, "date": f"{day} 18:00:00",
            "home_team": home, "away_team": away,
            "home_goals": 1 if played else None, "away_goals": 0 if played else None,
            "home_xg": hx if played else None, "away_xg": ax if played else None,
            "is_result": played}


class TestMarketPrior(unittest.TestCase):
    def setUp(self):
        # 2025: A forte (+1.0/partita), B debole (-1.0), C retrocessa (-0.5)
        self.records = [
            _m(2025, 1, "2025-09-01", "Inter", "Lecce", 2.0, 1.0),
            _m(2025, 2, "2025-09-08", "Lecce", "Inter", 0.5, 1.5),
            _m(2025, 3, "2025-09-15", "Inter", "Venezia", 1.5, 1.0),
            _m(2025, 4, "2025-09-22", "Venezia", "Lecce", 1.0, 1.0),
            # 2026: Venezia sparisce, arriva Pisa (promossa); una giornata giocata
            _m(2026, 5, "2026-08-22", "Pisa", "Inter", 0.4, 2.4),
            _m(2026, 6, "2026-08-22", "Lecce", "Pisa", 1.0, 1.0, played=False),  # fixture futura
        ]
        self.idx = XgPriorIndex(self.records, resolver=lambda n: n)

    def test_point_in_time_nessuna_partita_del_giorno_o_futura(self):
        # prima del 22/08/2026: nessuna partita 2026 usata
        info = self.idx.quality("Inter", 2026, datetime(2026, 8, 22))
        self.assertEqual(info["n_cur"], 0)
        # il giorno dopo la partita e' inclusa
        info = self.idx.quality("Inter", 2026, datetime(2026, 8, 23))
        self.assertEqual(info["n_cur"], 1)
        self.assertAlmostEqual(info["q_cur"], 2.0)

    def test_prior_stagione_precedente_regredito(self):
        p = XgPriorParams(persistence=0.5, prior_matches=10, slope=0.25)
        info = self.idx.quality("Inter", 2026, datetime(2026, 8, 1), p)
        # Inter 2025: (+1.0 +1.0 +0.5)/3 = 0.8333 -> prior 0.4167
        self.assertAlmostEqual(info["q_prev"], 0.8333, places=3)
        self.assertAlmostEqual(info["prior"], 0.4167, places=3)
        self.assertEqual(info["source"], "previous_season")
        self.assertAlmostEqual(self.idx.factor("Inter", 2026, datetime(2026, 8, 1), p),
                               1 + 0.25 * 0.4167, places=3)

    def test_promossa_eredita_la_media_delle_retrocesse(self):
        info = self.idx.quality("Pisa", 2026, datetime(2026, 8, 1))
        self.assertEqual(info["source"], "promoted")
        # Venezia 2025: (-0.5 + 0.0)/2 = -0.25
        self.assertAlmostEqual(info["q_prev"], -0.25, places=6)

    def test_aggiornamento_con_la_stagione_corrente(self):
        p = XgPriorParams(persistence=1.0, prior_matches=1, slope=0.25)
        info = self.idx.quality("Inter", 2026, datetime(2026, 8, 23), p)
        # q = (1*0.8333 + 1*2.0)/2
        self.assertAlmostEqual(info["q"], (0.8333 + 2.0) / 2, places=3)

    def test_neutro_senza_alcuna_informazione(self):
        self.assertEqual(self.idx.factor("Inter", 2025, datetime(2025, 8, 1)), 1.0)  # nessuna 2024
        self.assertEqual(factor_from_quality(float("nan")), 1.0)
        # una squadra assente dalla stagione precedente e' per definizione
        # "promossa": prior delle retrocesse, non neutro (regola dichiarata)
        info = self.idx.quality("Sconosciuta", 2026, datetime(2026, 8, 1))
        self.assertEqual(info["source"], "promoted")

    def test_clip_stesso_intervallo_del_fattore_mercato(self):
        self.assertEqual(factor_from_quality(10.0), 1.25)
        self.assertEqual(factor_from_quality(-10.0), 0.85)


if __name__ == "__main__":
    unittest.main()
