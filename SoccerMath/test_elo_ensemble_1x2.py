"""
test_elo_ensemble_1x2.py — Test di regressione PERMANENTE dell'ensemble
Poisson+Elo sulla testa 1X2 (leva validata in audit/diagnose_elo_ensemble.py:
Brier 1X2 0.5893 -> 0.5830 con w=0.6, walk-forward no-leakage 5 leghe
VALIDATION 2024/25 + TEST 2025/26).

Contratti fissati da questo test (per sempre):

1. ``app.blend_elo_into_1x2`` applica ESATTAMENTE ``w*Poisson + (1-w)*Elo``
   con ``w = app.ELO_ENSEMBLE_W = 0.6`` alla terna 1X2, non tocca i Totali
   (u15/u25/u35/gg) e non muta il dizionario di input; se l'Elo non e'
   disponibile (errore o valori non validi) degrada al Poisson puro
   bit-identico (comportamento pre-modifica).

2. La funzione ``get_full_poisson_two_heads`` resta bit-identica al
   fixture ``test_fixtures/1x2_pre_elo_ensemble.json`` (60 partite reali
   catturate PRIMA dell'introduzione dell'ensemble): l'ensemble e' uno
   strato a valle, non deve mai contaminare il calcolo Poisson ne' gli
   stats del motore.

3. Su un campione live >= 30 partite reali dal database attuale:
   l'1X2 blendato e' la combinazione lineare esatta di Poisson ed Elo di
   produzione, i Totali restano bit-identici al Poisson puro e tutti i
   ratio restano finiti e positivi.

4. I due punti di emissione delle previsioni (card giornata e Analisi
   Rapida) chiamano ``blend_elo_into_1x2`` (guardia contro rimozioni
   accidentali dello strato ensemble).

Esecuzione:
    python -m pytest SoccerMath/test_elo_ensemble_1x2.py -v
    python SoccerMath/test_elo_ensemble_1x2.py
"""

import inspect
import json
import os
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, _REPO_ROOT)

import app as prod_app  # noqa: E402

FIXTURE_PATH = os.path.join(_HERE, "test_fixtures", "1x2_pre_elo_ensemble.json")
KEYS_1X2 = ("1", "X", "2")
KEYS_TOTALI = ("u15", "u25", "u35", "gg")
LEAGUES_UNDER_TEST = ("Serie A", "Premier League", "La Liga",
                      "Bundesliga", "Ligue 1")
SAMPLES_PER_LEAGUE = 12

POISSON_SAMPLE = {
    "1": 0.4820, "X": 0.2530, "2": 0.2650,
    "u15": 0.4100, "u25": 0.5200, "u35": 0.2800, "gg": 0.5600,
}
ELO_SAMPLE = {"1": 0.5431, "X": 0.2387, "2": 0.2182}


class TestBlendEloInto1x2Formula(unittest.TestCase):
    """Contratto matematico dell'ensemble, Elo controllato via mock."""

    def test_blend_esatto_w_0_6(self):
        with mock.patch.object(prod_app, "predict_elo_probs",
                               return_value=dict(ELO_SAMPLE)):
            out = prod_app.blend_elo_into_1x2(dict(POISSON_SAMPLE),
                                              "Home", "Away", "Serie A")
        w = prod_app.ELO_ENSEMBLE_W
        self.assertEqual(w, 0.6,
                         "il peso dell'ensemble deve restare 0.6 (audit)")
        for k in KEYS_1X2:
            self.assertAlmostEqual(
                out[k], w * POISSON_SAMPLE[k] + (1 - w) * ELO_SAMPLE[k],
                places=14)
        # somma 1X2 conservata (Poisson ed Elo normalizzati)
        self.assertAlmostEqual(sum(out[k] for k in KEYS_1X2),
                               w * sum(POISSON_SAMPLE[k] for k in KEYS_1X2)
                               + (1 - w) * sum(ELO_SAMPLE[k] for k in KEYS_1X2),
                               places=14)

    def test_totali_e_input_invariati(self):
        m_in = dict(POISSON_SAMPLE)
        with mock.patch.object(prod_app, "predict_elo_probs",
                               return_value=dict(ELO_SAMPLE)):
            out = prod_app.blend_elo_into_1x2(m_in, "Home", "Away", "Serie A")
        for k in KEYS_TOTALI:
            self.assertEqual(out[k], POISSON_SAMPLE[k],
                             f"il totale {k} non deve cambiare con l'ensemble")
        self.assertEqual(m_in, POISSON_SAMPLE,
                         "il dizionario di input non deve essere mutato")
        self.assertIsNot(out, m_in)

    def test_elo_indisponibile_poisson_bit_identico(self):
        with mock.patch.object(prod_app, "predict_elo_probs",
                               side_effect=Exception("motore Elo assente")):
            out = prod_app.blend_elo_into_1x2(dict(POISSON_SAMPLE),
                                              "Home", "Away", "Serie A")
        for k in list(POISSON_SAMPLE):
            self.assertEqual(out[k], POISSON_SAMPLE[k],
                             f"fallback non bit-identico su {k}")

    def test_elo_non_valido_poisson_bit_identico(self):
        for bad in ({"1": float("nan"), "X": 0.2, "2": 0.2},
                    {"1": -0.1, "X": 0.5, "2": 0.6},
                    {"X": 0.5, "2": 0.5}):  # manca la chiave "1"
            with self.subTest(bad=bad):
                with mock.patch.object(prod_app, "predict_elo_probs",
                                       return_value=bad):
                    out = prod_app.blend_elo_into_1x2(dict(POISSON_SAMPLE),
                                                      "H", "A", "Serie A")
                for k in list(POISSON_SAMPLE):
                    self.assertEqual(out[k], POISSON_SAMPLE[k])


class TestPoissonLayerBitIdenticaAlFixture(unittest.TestCase):
    """Fixture generato PRIMA dell'ensemble (60 partite reali): la funzione
    get_full_poisson_two_heads e l'intero dizionario output devono restare
    bit-identici: l'ensemble e' uno strato a valle e non deve contaminare il
    calcolo Poisson."""

    def test_replay_fixture_pre_ensemble(self):
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
            for k, expected in e["expected"].items():
                max_diff = max(max_diff, abs(out[k] - expected))
        self.assertEqual(
            max_diff, 0.0,
            "get_full_poisson_two_heads non e' piu' bit-identica al "
            f"fixture pre-ensemble (max abs diff {max_diff})")


class TestEnsembleSuCampioneReale(unittest.TestCase):
    """Campione di partite reali dal database attuale: l'1X2 blendato e' la
    combinazione lineare esatta di Poisson ed Elo di produzione; i Totali
    restano bit-identici al Poisson puro; gli stats restano validi."""

    def test_blend_live(self):
        checked = 0
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
                for k in ("att", "def", "att0", "def0",
                          "att0_pure", "def0_pure"):
                    self.assertTrue(
                        hs[k] > 0 and as_[k] > 0,
                        f"{camp_key} {h}-{a}: ratio {k} non valido")
                m_raw = prod_app.get_full_poisson_two_heads(
                    hs, as_, avg_h, avg_a)
                m_blend = prod_app.blend_elo_into_1x2(m_raw, h, a, camp_key)
                elo_p = prod_app.predict_elo_probs(h, a, camp_key)
                w = prod_app.ELO_ENSEMBLE_W
                for k in KEYS_1X2:
                    self.assertEqual(
                        m_blend[k],
                        w * m_raw[k] + (1 - w) * elo_p[k],
                        f"{camp_key} {h}-{a}: ensemble {k} non esatto")
                for k in KEYS_TOTALI:
                    self.assertEqual(
                        m_blend[k], m_raw[k],
                        f"{camp_key} {h}-{a}: totale {k} alterato")
                checked += 1
        self.assertGreaterEqual(checked, 30, "campione reale troppo piccolo")


class TestWiringNeiPuntiDiEmissione(unittest.TestCase):
    """Guardia permanente: i punti di emissione delle previsioni applicano
    l'ensemble (rimozioni accidentali farebbero fallire questo test)."""

    def test_blend_chiamata_nei_percorsi_di_emissione(self):
        src = inspect.getsource(prod_app)
        n_calls = src.count("blend_elo_into_1x2(")
        # 1 definizione + almeno 2 punti di emissione (card giornata e
        # Analisi Rapida)
        self.assertGreaterEqual(
            n_calls, 3,
            "blend_elo_into_1x2 non risulta cablata nei punti di emissione")
        self.assertIn("confidence = ELO_ENSEMBLE_W * poisson_prob", src,
                      "la confidence 1X2 del Top Mix deve usare lo stesso "
                      "peso dell'ensemble")


if __name__ == "__main__":
    unittest.main(verbosity=2)
