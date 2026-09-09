"""
test_elo_ensemble_1x2.py — Test di regressione PERMANENTE dell'ensemble
Poisson+Elo sulla testa 1X2 (leva validata in audit/diagnose_elo_ensemble.py:
Brier 1X2 0.5893 -> 0.5830 con w=0.6, walk-forward no-leakage 5 leghe
VALIDATION 2024/25 + TEST 2025/26).

SCOPO DELL'ENSEMBLE (fissato dopo audit/results/ensemble_scope_analisi_rapida.md):
il blend 0.6*Poisson + 0.4*Elo CALIBRA MEGLIO le probabilita' 1X2 mostrate,
ma NON deve entrare nell'argmax di selezione dei mercati: usato dentro
l'argmax sposta sistematicamente le scelte verso Over/NG e peggiora
hit rate/ROI. Percio' in produzione:
  - analisi_rapida_giornata(): SELEZIONE sui mercati Poisson puro; la
    probabilita' salvata e' blendata SOLO se il mercato scelto e' 1X2;
  - card giornata (tab1) e Top Mix: restano come da commit d21f5c3
    (blend mostrato; il Top Mix selezionava gia' su Poisson puro).

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

4. analisi_rapida_giornata(): il mercato scelto e' l'argmax dei mercati
   POISSON PURO (indipendente dall'Elo); la probabilita' salvata e'
   blendata se e solo se il mercato scelto e' 1X2; i Totali salvati sono
   Poisson puro. Guardia di cablaggio anche su tab1 e Top Mix.

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


class TestAnalisiRapidaSelezionePuraProbabilitaBlendata(unittest.TestCase):
    """Opzione (b): in analisi_rapida_giornata() la SELEZIONE avviene sui
    mercati Poisson puro (l'Elo non puo' cambiare il mercato scelto), mentre
    la probabilita' salvata e' blendata SOLO se il mercato scelto e' 1X2."""

    def _run(self, m_pure, elo):
        match = {"homeTeam": {"name": "TeamH"},
                 "awayTeam": {"name": "TeamA"},
                 "id": 12345, "utcDate": "2026-09-10T15:00:00Z"}
        stats = {"TeamH": {"att": 1.0, "def": 1.0},
                 "TeamA": {"att": 1.0, "def": 1.0}}
        saved = []
        with mock.patch.object(prod_app, "get_full_poisson_two_heads",
                               return_value=dict(m_pure)), \
             mock.patch.object(prod_app, "predict_elo_probs",
                               return_value=dict(elo)), \
             mock.patch.object(prod_app, "save_prediction_entry",
                               side_effect=lambda *a, **k: saved.append((a, k))):
            n = prod_app.analisi_rapida_giornata([match], stats, 1.35, 1.15,
                                                 "Serie A", {}, 5)
        self.assertEqual(n, 1)
        self.assertEqual(len(saved), 1)
        args, kwargs = saved[0]
        # save_prediction_entry(m_id, h, a, camp, giornata, date, pron, top3, prob%, ...)
        return args[6], args[8]  # pron, prob_percentuale

    def test_mercato_1x2_scelto_salva_probabilita_blendata(self):
        # Poisson puro: vince "Vittoria TeamH" (0.70, sopra ogni totale)
        m_pure = {"1": 0.70, "X": 0.18, "2": 0.12,
                  "u15": 0.35, "u25": 0.55, "u35": 0.75, "gg": 0.60}
        elo = {"1": 0.50, "X": 0.28, "2": 0.22}
        pron, prob = self._run(m_pure, elo)
        w = prod_app.ELO_ENSEMBLE_W
        attesa = w * 0.70 + (1 - w) * 0.50
        self.assertTrue(pron.startswith("Vittoria TeamH"),
                        f"la selezione deve restare sull'argmax Poisson: {pron}")
        self.assertAlmostEqual(prob, round(attesa * 100, 1), places=6)
        self.assertNotAlmostEqual(prob, 70.0, places=1,
                                  msg="salvata la probabilita' pura, non blendata")

    def test_selezione_indipendente_dall_elo(self):
        # Elo estremo a favore della trasferta: la scelta NON deve cambiare
        # (l'argmax legge solo il Poisson puro)
        m_pure = {"1": 0.70, "X": 0.18, "2": 0.12,
                  "u15": 0.35, "u25": 0.55, "u35": 0.75, "gg": 0.60}
        elo = {"1": 0.05, "X": 0.05, "2": 0.90}
        pron, _ = self._run(m_pure, elo)
        self.assertTrue(pron.startswith("Vittoria TeamH"),
                        f"l'Elo ha cambiato la selezione: {pron}")

    def test_mercato_totale_scelto_salva_poisson_puro(self):
        # Poisson puro: vince "Over 2.5" (1-0.40=0.60, sopra l'1X2)
        m_pure = {"1": 0.45, "X": 0.27, "2": 0.28,
                  "u15": 0.30, "u25": 0.40, "u35": 0.22, "gg": 0.55}
        elo = {"1": 0.90, "X": 0.05, "2": 0.05}  # Elo irrilevante sui Totali
        pron, prob = self._run(m_pure, elo)
        self.assertTrue(pron.startswith("Over 2.5"),
                        f"atteso Over 2.5 dall'argmax Poisson: {pron}")
        self.assertAlmostEqual(prob, 60.0, places=6)

    def test_elo_indisponibile_probabilita_pura(self):
        m_pure = {"1": 0.70, "X": 0.18, "2": 0.12,
                  "u15": 0.35, "u25": 0.55, "u35": 0.75, "gg": 0.60}
        match = {"homeTeam": {"name": "TeamH"},
                 "awayTeam": {"name": "TeamA"},
                 "id": 1, "utcDate": "2026-09-10T15:00:00Z"}
        stats = {"TeamH": {"att": 1.0, "def": 1.0},
                 "TeamA": {"att": 1.0, "def": 1.0}}
        saved = []
        with mock.patch.object(prod_app, "get_full_poisson_two_heads",
                               return_value=dict(m_pure)), \
             mock.patch.object(prod_app, "predict_elo_probs",
                               side_effect=Exception("Elo ko")), \
             mock.patch.object(prod_app, "save_prediction_entry",
                               side_effect=lambda *a, **k: saved.append((a, k))):
            prod_app.analisi_rapida_giornata([match], stats, 1.35, 1.15,
                                             "Serie A", {}, 5)
        self.assertAlmostEqual(saved[0][0][8], 70.0, places=6,
                               msg="con Elo ko la probabilita' salvata deve "
                                   "essere il Poisson puro")


class TestWiringNeiPuntiDiEmissione(unittest.TestCase):
    """Guardia permanente: l'ensemble resta cablato dove previsto (rimozioni
    accidentali farebbero fallire questo test)."""

    def test_blend_chiamata_nei_percorsi_di_emissione(self):
        src = inspect.getsource(prod_app)
        n_calls = src.count("blend_elo_into_1x2(")
        # 1 definizione + tab1 + analisi_rapida
        self.assertGreaterEqual(
            n_calls, 3,
            "blend_elo_into_1x2 non risulta cablata nei punti di emissione")
        self.assertIn("confidence = ELO_ENSEMBLE_W * poisson_prob", src,
                      "la confidence 1X2 del Top Mix deve usare lo stesso "
                      "peso dell'ensemble")

    def test_tab1_mostra_il_blend_invariato(self):
        src = inspect.getsource(prod_app)
        tab1 = src[src.index("with tab1:"):src.index("with tab2:")]
        self.assertIn("blend_elo_into_1x2(", tab1,
                      "il loop card giornata (tab1) deve restare come da "
                      "d21f5c3: 1X2 mostrato blendato")

    def test_analisi_rapida_seleziona_su_poisson_puro(self):
        src_ar = inspect.getsource(prod_app.analisi_rapida_giornata)
        # il blend deve avvenire DOPO la costruzione del dizionario mercati
        # usato dall'argmax: la selezione legge solo il Poisson puro
        i_mercati = src_ar.index("mercati = {")
        i_blend = src_ar.index("blend_elo_into_1x2(")
        self.assertLess(i_mercati, i_blend,
                        "analisi_rapida: il blend deve restare FUORI "
                        "dall'argmax di selezione (mercati Poisson puro)")
        self.assertIn("max(mercati, key=mercati.get)", src_ar)


if __name__ == "__main__":
    unittest.main(verbosity=2)
