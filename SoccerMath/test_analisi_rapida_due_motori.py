"""Analisi Rapida a due motori: due righe per partita, una per motore Elo.

Richiesta: "se faro' l'analisi rapida verra' fatta direttamente sui due motori a
confronto come avviene col top mix". Qui si prova:

* due righe per partita, con variante ``current`` (Elo post-fix PR#24) e
  ``legacy`` (Elo pre-fix), entrambe con origine ``analisi_rapida``;
* la riga del motore **attuale** e' quella di sempre: la SCELTA resta l'argmax
  sui mercati Poisson puri (l'Elo non la sposta);
* il gemello legacy usa l'Elo legacy per la probabilita' 1X2, e sui Totali
  (dove l'Elo non entra) le due righe hanno la stessa probabilita';
* Elo legacy assente -> la riga legacy si scrive col Poisson puro (degradazione
  dichiarata), senza far cadere la riga attuale;
* le due righe hanno la stessa struttura: nessun campo in piu' da una parte
  (a parte ``model_variant``, che le distingue).
"""
from __future__ import annotations

import logging
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

logging.getLogger("streamlit").setLevel(logging.ERROR)

import app  # noqa: E402
from prediction_registry import (  # noqa: E402
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_FIELD,
    MODEL_VARIANT_LEGACY,
    ORIGIN_ANALISI_RAPIDA,
)

MATCH = {"homeTeam": {"name": "TeamH"}, "awayTeam": {"name": "TeamA"},
         "id": 12345, "utcDate": "2026-09-10T15:00:00Z"}
STATS = {"TeamH": {"att": 1.0, "def": 1.0}, "TeamA": {"att": 1.0, "def": 1.0}}


def _gira(m_pure, elo_current, elo_legacy, *, legacy_ko=False):
    salvate = []

    def _cattura(*a, **k):
        salvate.append((a, k))
        return {"azione": "aggiunta"}

    patch_legacy = (mock.patch.object(app, "predict_elo_probs_legacy",
                                      side_effect=Exception("Elo legacy ko"))
                    if legacy_ko else
                    mock.patch.object(app, "predict_elo_probs_legacy",
                                      return_value=dict(elo_legacy)))
    with mock.patch.object(app, "get_full_poisson_two_heads", return_value=dict(m_pure)), \
         mock.patch.object(app, "predict_elo_probs", return_value=dict(elo_current)), \
         patch_legacy, \
         mock.patch.object(app, "save_prediction_entry", side_effect=_cattura):
        n = app.analisi_rapida_giornata([MATCH], STATS, 1.35, 1.15, "Serie A", {}, 5)
    righe = {k.get(MODEL_VARIANT_FIELD): (a, k) for a, k in salvate}
    return n, righe


class TestDueMotori(unittest.TestCase):
    M_1X2 = {"1": 0.70, "X": 0.18, "2": 0.12,
             "u15": 0.35, "u25": 0.55, "u35": 0.75, "gg": 0.60}
    M_TOTALI = {"1": 0.45, "X": 0.27, "2": 0.28,
                "u15": 0.30, "u25": 0.40, "u35": 0.22, "gg": 0.55}
    ELO_CUR = {"1": 0.50, "X": 0.28, "2": 0.22}
    ELO_LEG = {"1": 0.30, "X": 0.30, "2": 0.40}

    def test_due_righe_una_per_motore(self):
        n, righe = _gira(self.M_1X2, self.ELO_CUR, self.ELO_LEG)
        self.assertEqual(2, n, "due righe scritte per una partita")
        self.assertEqual({MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY}, set(righe))
        for _a, k in righe.values():
            self.assertEqual(ORIGIN_ANALISI_RAPIDA, k.get("origin"))

    def test_la_scelta_non_cambia_con_il_motore(self):
        _n, righe = _gira(self.M_TOTALI, {"1": 0.9, "X": 0.05, "2": 0.05},
                          {"1": 0.05, "X": 0.05, "2": 0.9})
        pron_current = righe[MODEL_VARIANT_CURRENT][0][6]
        pron_legacy = righe[MODEL_VARIANT_LEGACY][0][6]
        self.assertTrue(pron_current.startswith("Over 2.5"), pron_current)
        self.assertEqual(pron_current.split(" - ")[0], pron_legacy.split(" - ")[0],
                         "il mercato scelto e' lo stesso: l'argmax e' Poisson puro")

    def test_1x2_ogni_motore_usa_il_suo_elo(self):
        _n, righe = _gira(self.M_1X2, self.ELO_CUR, self.ELO_LEG)
        w = app.ELO_ENSEMBLE_W
        p_cur = righe[MODEL_VARIANT_CURRENT][0][8]
        p_leg = righe[MODEL_VARIANT_LEGACY][0][8]
        self.assertAlmostEqual(round((w * 0.70 + (1 - w) * 0.50) * 100, 1), p_cur, places=6)
        self.assertAlmostEqual(round((w * 0.70 + (1 - w) * 0.30) * 100, 1), p_leg, places=6)
        self.assertNotAlmostEqual(p_cur, p_leg, places=1,
                                  msg="i due motori hanno Elo diversi: la probabilita' 1X2 deve differire")

    def test_totali_dove_elo_non_entra_le_due_righe_coincidono(self):
        _n, righe = _gira(self.M_TOTALI, self.ELO_CUR, self.ELO_LEG)
        self.assertEqual(righe[MODEL_VARIANT_CURRENT][0][8], righe[MODEL_VARIANT_LEGACY][0][8],
                         "sui Totali l'Elo non viene letto: le due righe hanno la stessa probabilita'")

    def test_struttura_identica_a_parte_la_variante(self):
        _n, righe = _gira(self.M_1X2, self.ELO_CUR, self.ELO_LEG)
        campi = [{k for k in kw if k != MODEL_VARIANT_FIELD} for _a, kw in righe.values()]
        self.assertEqual(2, len(campi), "due righe")
        self.assertEqual(campi[0], campi[1],
                         "le due righe hanno gli stessi campi: cambia solo la variante")
        self.assertEqual({MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY}, set(righe))

    def test_elo_legacy_assente_non_fa_cadere_la_riga_attuale(self):
        n, righe = _gira(self.M_1X2, self.ELO_CUR, None, legacy_ko=True)
        self.assertEqual(2, n, "anche col legacy ko si scrivono le due righe")
        w = app.ELO_ENSEMBLE_W
        self.assertAlmostEqual(round((w * 0.70 + (1 - w) * 0.50) * 100, 1),
                               righe[MODEL_VARIANT_CURRENT][0][8], places=6)
        self.assertAlmostEqual(70.0, righe[MODEL_VARIANT_LEGACY][0][8], places=6,
                               msg="senza Elo legacy la riga legacy e' Poisson pura")


if __name__ == "__main__":
    unittest.main()
