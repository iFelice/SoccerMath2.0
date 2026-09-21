"""Percentuale di successo dei due motori senza le righe di transizione: i conti e i confini.

I casi provati qui sono quelli che decidono la risposta:

* le righe di TRANSIZIONE (partita dentro la finestra ricostruibile, ma il replay
  di oggi non la rifa') NON entrano nel confronto;
* le righe di una partita giocata PRIMA della finestra restano nel Legacy pulito
  (non sono transizione: sono il vecchio motore su dati che oggi non si
  ricostruiscono) e sono dichiarate a parte;
* le due controprove appaiate (click veri e ricostruzioni) contano le coppie
  discordanti e il loro p-value;
* il verdetto dice a parole quando il campione non basta, invece di lasciar
  credere a una differenza che l'intervallo non sostiene.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import confronto_modelli as CM  # noqa: E402


def _riga(match_id, *, esito="✅", mercato="1", prob=60.0, variante="legacy",
          data="22/08/2026 18:30", salvato="17/08/2026 16:28", stagione="2026/2027",
          origine="top_mix", casa=None, ospite=None):
    return {"match_id": match_id, "home": casa or f"Casa{match_id}", "away": ospite or "Ospite",
            "campionato": "Serie A", "giornata": 1, "data": data,
            "mercato_standard": mercato, "prob_sicuro": prob, "esito": esito,
            "origin": origine, "model_variant": variante, "salvato_il": salvato,
            "stagione": stagione, "model_version": "post_shrinkage_v1"}


def _proposta(match_id, variante="legacy", mercato="1"):
    return {"match_id": match_id, "origin": "top_mix", "model_variant": variante,
            "mercato_standard": mercato, "esito": "✅"}


class TestStatisticaDiBase(unittest.TestCase):
    """Gli stimatori usati per dire 'dentro o fuori dal margine'."""

    def test_wilson_su_casi_noti(self):
        lo, hi = CM.wilson(0, 10)
        self.assertAlmostEqual(0.0, lo, places=4)
        self.assertAlmostEqual(0.2775, hi, places=3)
        lo, hi = CM.wilson(5, 10)
        self.assertAlmostEqual(0.2366, lo, places=3)
        self.assertAlmostEqual(0.7634, hi, places=3)

    def test_wilson_senza_decise_non_inventa_nulla(self):
        self.assertEqual((0.0, 1.0), CM.wilson(0, 0))

    def test_fisher_esatto_su_tabelle_note(self):
        self.assertAlmostEqual(0.4857, CM.fisher_esatto(3, 1, 1, 3), places=3)
        self.assertAlmostEqual(0.00794, CM.fisher_esatto(5, 0, 0, 5), places=5)
        self.assertEqual(1.0, CM.fisher_esatto(0, 0, 0, 0))

    def test_mcnemar_esatto_su_casi_noti(self):
        self.assertAlmostEqual(0.21875, CM.mcnemar_esatto(1, 5), places=5)
        self.assertEqual(1.0, CM.mcnemar_esatto(0, 0))

    def test_piu_righe_abbassano_la_differenza_rilevabile(self):
        piccolo = CM.mde(0.60, 30, 30)
        grande = CM.mde(0.60, 200, 200)
        self.assertLess(grande, piccolo, "con piu' righe si vede una differenza piu' piccola")

    def test_righe_necessarie_per_una_differenza(self):
        self.assertIsNotNone(CM.n_per_gruppo(0.60, 0.20))
        self.assertLess(CM.n_per_gruppo(0.60, 0.20), CM.n_per_gruppo(0.60, 0.10),
                        "+20 punti si vede con meno righe di +10 punti")
        self.assertIsNone(CM.n_per_gruppo(0.60, 0.0))

    def test_intervallo_della_differenza_nel_caso_incerto(self):
        """28 su 50 contro 22 su 50: differenza visibile (+12 punti) ma non solida."""
        lo, hi = CM.newcombe_diff(28, 50, 22, 50)
        self.assertLess(lo, 0.0)
        self.assertGreater(hi, 0.0)
        self.assertGreater(CM.fisher_esatto(28, 22, 22, 28), 0.05)

    def test_intervallo_della_differenza_nettezza(self):
        """30 su 50 contro 20 su 50: 20 punti, e l'intervallo non tocca lo zero."""
        lo, hi = CM.newcombe_diff(30, 50, 20, 50)
        self.assertGreater(lo, 0.0)
        self.assertGreater(hi, lo)


class TestGruppiDelConfronto(unittest.TestCase):
    """Chi entra nel confronto e chi no."""

    RIGHE = [
        _riga(101, variante="current", salvato="20/09/2026 12:00", data="21/09/2026 18:00"),
        _riga(102, variante="legacy", salvato="10/09/2026 12:00", data="11/09/2026 18:00"),  # rifatta
        _riga(103, variante="legacy", salvato="15/09/2026 12:00", data="16/09/2026 18:00"),  # NON rifatta, dentro
        _riga(104, variante="legacy", salvato="17/08/2026 16:28", data="22/08/2026 18:30"),  # prima finestra
        _riga(105, variante="legacy", salvato="23/05/2026 07:18", data="20/05/2026 18:00",
              stagione="2025/2026"),
        _riga(106, origine="analisi_rapida"),  # fuori dal conto: non e' Top Mix
    ]
    PROPOSTE = [_proposta(101, "current"), _proposta(102, "legacy")]

    def test_la_riga_di_transizione_resta_fuori_dal_legacy(self):
        d = CM.classifica(self.RIGHE, self.PROPOSTE)
        g = d["gruppi"]
        self.assertEqual([103], [r["match_id"] for r in g["transizione"]])
        self.assertEqual({102, 104, 105}, {r["match_id"] for r in g["legacy_pulito"]})
        self.assertEqual([101], [r["match_id"] for r in g["drago"]])

    def test_la_riga_prima_della_finestra_resta_nel_legacy_pulito(self):
        d = CM.classifica(self.RIGHE, self.PROPOSTE)
        g = d["gruppi"]
        self.assertIn(104, [r["match_id"] for r in g["legacy_fuori_finestra"]])
        self.assertNotIn(104, [r["match_id"] for r in g["transizione"]])

    def test_le_righe_rifatte_dal_replay_sono_dichiarate(self):
        d = CM.classifica(self.RIGHE, self.PROPOSTE)
        self.assertEqual([102], [r["match_id"] for r in d["gruppi"]["legacy_riprodotto"]])

    def test_solo_le_top_mix_entrano_nel_conto(self):
        d = CM.classifica(self.RIGHE, self.PROPOSTE)
        self.assertEqual(5, d["righe_top_mix"])
        self.assertEqual(0, len(d["gruppi"]["altro"]))

    def test_una_riga_current_non_rifatta_e_dichiarata_come_anomalia(self):
        righe = self.RIGHE + [_riga(107, variante="current", salvato="20/09/2026 12:00")]
        d = CM.classifica(righe, self.PROPOSTE)
        self.assertEqual(1, d["anomalie"]["drago_non_riproposto"])
        # resta comunque nella tabella Drago: non si nasconde
        self.assertIn(107, [r["match_id"] for r in d["gruppi"]["drago"]])


class TestConfrontoEVerdetto(unittest.TestCase):
    """I numeri del confronto e la frase che li accompagna."""

    @staticmethod
    def _d(gruppo_drago, gruppo_legacy, proposte=()):
        righe = [dict(r, model_variant="current") for r in gruppo_drago] + \
                [dict(r, model_variant="legacy") for r in gruppo_legacy]
        return CM.costruisci(righe, list(proposte), fonte="upstash")

    def test_campione_piccolo_il_verdetto_lo_dice(self):
        drago = [_riga(i, esito="✅", variante="current", salvato="20/09/2026 12:00") for i in (1, 2)]
        legacy = [_riga(10 + i, esito="✅", salvato="10/09/2026 12:00") for i in (1, 2)] + \
                 [_riga(20 + i, esito="❌", salvato="10/09/2026 12:00") for i in (1, 2)]
        d = self._d(drago, legacy)
        self.assertIn("COMPRENDE lo zero", d["verdetto"])
        self.assertIn("NON basta", d["verdetto"])
        self.assertFalse(d["confronto"]["significativo"])

    def test_differenza_grande_fuori_dal_margine(self):
        drago = [_riga(i, esito="❌", variante="current", salvato="20/09/2026 12:00") for i in range(30)]
        legacy = [_riga(100 + i, esito="✅", salvato="10/09/2026 12:00") for i in range(30)]
        d = self._d(drago, legacy)
        self.assertTrue(d["confronto"]["significativo"])
        self.assertIn("zero escluso", d["verdetto"])
        self.assertLess(d["confronto"]["fisher_p"], 0.05)

    def test_le_righe_in_attesa_non_entrano_nel_denominatore(self):
        drago = [_riga(1, esito="✅", variante="current", salvato="20/09/2026 12:00"),
                 _riga(2, esito="⏳", variante="current", salvato="20/09/2026 12:00")]
        legacy = [_riga(3, esito="✅"), _riga(4, esito="⏳")]
        d = self._d(drago, legacy)
        st = d["statistiche"]["drago"]
        self.assertEqual(2, st["righe"])
        self.assertEqual(1, st["decise"])
        self.assertEqual(1, st["attesa"])
        self.assertEqual(1.0, st["successo"])

    def test_robustezza_al_netto_della_stagione_precedente(self):
        drago = [_riga(1, esito="✅", variante="current", salvato="20/09/2026 12:00")]
        legacy = [_riga(2, esito="❌"),
                  _riga(3, esito="✅", stagione="2025/2026", salvato="23/05/2026 07:18")]
        d = self._d(drago, legacy)
        self.assertEqual(2, d["statistiche"]["legacy_pulito"]["righe"])
        self.assertEqual(1, d["statistiche"]["legacy_solo_stagione"]["righe"])
        self.assertIn("legacy_solo_stagione", d["confronti_robustezza"])


class TestControproveAppaiate(unittest.TestCase):
    """Le coppie: stessa partita, due motori."""

    def test_coppie_del_registro_contano_le_discordanti(self):
        drago = [_riga(1, esito="❌", variante="current", mercato="OVER_2.5"),
                 _riga(2, esito="✅", variante="current", mercato="1"),
                 _riga(3, esito="✅", variante="current")]
        legacy = [_riga(1, esito="✅", mercato="GG"),
                  _riga(2, esito="✅", mercato="1")]
        r = CM.coppie_registro(drago, legacy)
        self.assertEqual(2, r["partite_con_entrambi"])
        self.assertEqual(1, r["b_legacy_vince_drago_perde"])
        self.assertEqual(0, r["c_drago_vince_legacy_perde"])
        self.assertAlmostEqual(1.0, r["mcnemar_p"], places=6)
        self.assertEqual(1, r["mercati_diversi"])
        self.assertEqual(1, r["stessi_mercati"])

    def test_coppie_del_replay_sullo_stesso_istante(self):
        proposte = [
            _proposta(1, "current", mercato="1"), _proposta(1, "legacy", mercato="1"),
            _proposta(2, "current", mercato="GG"), _proposta(2, "legacy", mercato="OVER_2.5"),
            _proposta(3, "legacy", mercato="1"),          # senza il gemello: non e' una coppia
        ]
        r = CM.coppie_replay(proposte)
        self.assertEqual(2, r["partite_con_entrambi"])
        self.assertEqual(1, r["mercati_diversi"])

    def test_una_coppia_in_attesa_non_entra_nel_test(self):
        proposte = [
            dict(_proposta(1, "current"), esito="✅"), dict(_proposta(1, "legacy"), esito="⏳"),
        ]
        r = CM.coppie_replay(proposte)
        self.assertEqual(1, r["partite_con_entrambi"])
        self.assertEqual(0, r["b_legacy_vince_drago_perde"])
        self.assertEqual(1.0, r["mcnemar_p"])


class TestRefertoEIngressi(unittest.TestCase):
    """Il referto esce, e senza Registro non si inventa niente."""

    @staticmethod
    def _fixture():
        righe = [
            _riga(1, esito="✅", variante="current", salvato="20/09/2026 12:00", data="21/09/2026 18:00"),
            _riga(2, esito="❌", variante="current", salvato="20/09/2026 12:00", data="21/09/2026 18:00"),
            _riga(3, esito="✅", salvato="10/09/2026 12:00", data="11/09/2026 18:00"),
            _riga(4, esito="❌", salvato="15/09/2026 12:00", data="16/09/2026 18:00"),
        ]
        return righe, [_proposta(1, "current"), _proposta(3, "legacy")]

    def test_referto_compatto_ha_tutte_le_sezioni(self):
        righe, proposte = self._fixture()
        d = CM.costruisci(righe, proposte, fonte="upstash")
        testo = "\n".join(CM.righe_compatti(d))
        for prefisso in ("CAMPIONE|", "GRUPPO|", "CONFRONTO|", "COPPIE|", "VERDETTO|"):
            self.assertIn(prefisso, testo)
        self.assertIn("transizione escluse 1", testo)

    def test_referto_esteso_ha_la_tabella_e_il_verdetto(self):
        righe, proposte = self._fixture()
        d = CM.costruisci(righe, proposte, fonte="upstash")
        testo = "\n".join(CM.righe_testo(d))
        self.assertIn("| gruppo | righe | decise |", testo)
        self.assertIn("**Verdetto**", testo)

    def test_senza_registro_esce_due(self):
        with mock.patch.object(CM, "load_registry_readonly", return_value=(None, "nessuno")):
            self.assertEqual(2, CM.main(["--replay-json", "qualunque.json"]))

    def test_senza_referto_del_replay_esce_due(self):
        with mock.patch.object(CM, "load_registry_readonly", return_value=([], "upstash")):
            self.assertEqual(2, CM.main(["--replay-json", "non-esiste.json"]))

    def test_da_riga_di_comando_scrive_il_json(self):
        righe, proposte = self._fixture()
        with tempfile.TemporaryDirectory() as tmp:
            replay = os.path.join(tmp, "replay.json")
            with open(replay, "w", encoding="utf-8") as f:
                json.dump({"entries_current": [proposte[0]], "entries_legacy": [proposte[1]]}, f)
            uscita = os.path.join(tmp, "out.json")
            with mock.patch.object(CM, "load_registry_readonly", return_value=(righe, "upstash")):
                rc = CM.main(["--replay-json", replay, "--compatto", "--json", uscita])
            self.assertEqual(0, rc)
            with open(uscita, encoding="utf-8") as f:
                d = json.load(f)
            self.assertEqual(2, d["statistiche"]["drago"]["righe"])
            self.assertIn("verdetto", d)


if __name__ == "__main__":
    unittest.main()
