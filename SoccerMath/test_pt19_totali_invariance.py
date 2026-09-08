"""
test_pt19_totali_invariance.py — Test di regressione PERMANENTE: l'1X2 di
``get_full_poisson_two_heads`` deve restare bit-identico alla modifica che ha
spostato la fonte della testa Totali (att0_pure/def0_pure) dal file xG
stagionale al lookup point-in-time PT-19 con tetto di eta' 400 giorni
(``xg_archive.point_in_time_averages``).

Vincolo non negoziabile di questa modifica: la testa Totali (O/U2.5 e GG/NG)
cambia fonte; la testa 1X2 (att/def/att0/def0) resta ESATTAMENTE quella di
prima. Questo test lo rende permanente in due modi:

1. ``test_1x2_bit_identico_campione_reale`` (il controllo fatto in audit):
   per un campione di partite REALI del database attuale, l'1X2 calcolato con
   gli stats prodotti dal motore deve essere bit-identico (max abs diff 0.0)
   anche sostituendo att0_pure/def0_pure con la baseline precedente (att0/def0)
   o con valori arbitrari: la testa 1X2 non legge quei campi, e chiunque in
   futuro li collegasse all'1X2 farebbe fallire questo test.

2. ``test_1x2_bit_identico_fixture_pre_modifica``: il fixture committato
   (``test_fixtures/1x2_invariance.json``) congela input (dizionari squadra +
   avg_h/avg_a) ed esiti 1X2 calcolati PRIMA della modifica su partite reali;
   ri-eseguendo ``get_full_poisson_two_heads`` sugli stessi input l'1X2 deve
   riprodursi bit-identico (max abs diff 0.0), come verificato in audit.

Esecuzione:
    python -m pytest SoccerMath/test_pt19_totali_invariance.py -v
    python SoccerMath/test_pt19_totali_invariance.py
"""
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _REPO_ROOT)

import app as prod_app  # noqa: E402

FIXTURE_PATH = os.path.join(_HERE, "test_fixtures", "1x2_invariance.json")
LEAGUES_UNDER_TEST = ("Serie A", "Premier League", "La Liga",
                      "Bundesliga", "Ligue 1")
SAMPLES_PER_LEAGUE = 12
KEYS_1X2 = ("1", "X", "2")


def max_diff_1x2(a, b):
    return max(abs(a[k] - b[k]) for k in KEYS_1X2)


class Test1X2InvarianzaPT19(unittest.TestCase):

    def test_1x2_bit_identico_campione_reale(self):
        """Campione di partite reali dal database attuale: l'1X2 non deve
        muoversi di un bit qualunque cosa ci sia in att0_pure/def0_pure."""
        total_checked = 0
        for camp_key in LEAGUES_UNDER_TEST:
            res = prod_app.get_league_engine(camp_key)
            self.assertIsNotNone(res, f"nessun dato per {camp_key}")
            stats, avg_h, avg_a, df = res
            n = len(df)
            step = max(1, n // SAMPLES_PER_LEAGUE)
            i = 0
            while i < n:
                row = df.iloc[i]
                h, a = row.HomeClean, row.AwayClean
                i += step
                if h not in stats or a not in stats:
                    continue
                hs, as_ = stats[h], stats[a]
                base = prod_app.get_full_poisson_two_heads(hs, as_, avg_h, avg_a)

                # variante A: att0_pure/def0_pure = baseline pre-modifica
                # (att0/def0: i valori che la testa Totali leggeva prima)
                hs_old = dict(hs)
                as_old = dict(as_)
                hs_old["att0_pure"] = hs["att0"]
                hs_old["def0_pure"] = hs["def0"]
                as_old["att0_pure"] = as_["att0"]
                as_old["def0_pure"] = as_["def0"]
                old = prod_app.get_full_poisson_two_heads(hs_old, as_old,
                                                          avg_h, avg_a)

                # variante B: valori arbitrari (nessun legame col motore)
                hs_garbage = dict(hs)
                as_garbage = dict(as_)
                hs_garbage["att0_pure"] = 0.123
                hs_garbage["def0_pure"] = 3.456
                as_garbage["att0_pure"] = 9.999
                as_garbage["def0_pure"] = 0.001
                garbage = prod_app.get_full_poisson_two_heads(hs_garbage,
                                                              as_garbage,
                                                              avg_h, avg_a)

                self.assertEqual(
                    max_diff_1x2(base, old), 0.0,
                    f"{camp_key} {h}-{a}: l'1X2 cambia sostituendo la fonte "
                    "della testa Totali con la baseline precedente")
                self.assertEqual(
                    max_diff_1x2(base, garbage), 0.0,
                    f"{camp_key} {h}-{a}: l'1X2 dipende da att0_pure/def0_pure")
                total_checked += 1
        self.assertGreaterEqual(total_checked, 30,
                                "campione reale troppo piccolo")

    def test_1x2_bit_identico_fixture_pre_modifica(self):
        """Fixture generato PRIMA della modifica: stessi input -> stesso 1X2,
        bit per bit (max abs diff 0.0, come in audit)."""
        self.assertTrue(os.path.exists(FIXTURE_PATH),
                        f"fixture mancante: {FIXTURE_PATH}")
        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            fixture = json.load(f)
        entries = fixture["entries"]
        self.assertGreaterEqual(len(entries), 50)
        max_diff = 0.0
        for e in entries:
            out = prod_app.get_full_poisson_two_heads(
                e["hs"], e["as"], e["avg_h"], e["avg_a"])
            for k in KEYS_1X2:
                max_diff = max(max_diff, abs(out[k] - e["expected"][k]))
        self.assertEqual(
            max_diff, 0.0,
            "l'1X2 sul fixture pre-modifica non e' piu' bit-identico "
            f"(max abs diff {max_diff})")


if __name__ == "__main__":
    unittest.main(verbosity=2)
