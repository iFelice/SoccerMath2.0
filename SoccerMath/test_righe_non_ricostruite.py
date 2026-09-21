"""Le righe non ritrovate dal replay: elenco con data e partita, mai una scrittura.

Si prova ``confronta()`` e ``periodo()`` su righe sintetiche che riproducono i casi
veri: la riga di agosto scritta live prima della finestra, la riga scritta dentro la
finestra che il replay di oggi non riproduce (motivo diverso, va vista), la riga
della stagione precedente (catalogo) e la riga che il replay ritrova (che NON deve
finire nell'elenco).
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import righe_non_ricostruite as RN  # noqa: E402


def _riga(match_id, *, data="22/08/2026 18:30", salvato="17/08/2026 16:28",
          variante="legacy", stagione="2026/2027", origine="top_mix"):
    r = {"match_id": match_id, "home": f"Casa{match_id}", "away": "Ospite",
         "campionato": "Serie A", "giornata": 1, "data": data,
         "pronostico_sicuro": "1 - Top Mix", "mercato_standard": "1", "prob_sicuro": 60.0,
         "esito": "⏳", "origin": origine, "model_variant": variante,
         "salvato_il": salvato, "stagione": stagione, "model_version": "post_shrinkage_v1"}
    return r


class TestConfronto(unittest.TestCase):
    """Solo le righe che il replay non propone, e solo Top Mix."""

    RIGHE = [
        _riga(1),                                                     # non proposta: periodo 15-29/08
        _riga(2, data="05/09/2026 18:00", salvato="05/09/2026 17:00"),  # non proposta: dentro finestra
        _riga(3, data="20/05/2026 18:00", salvato="23/05/2026 07:18", stagione="2025/2026"),
        _riga(4, data="19/09/2026 20:45", salvato="19/09/2026 19:00"),  # proposta -> non in elenco
        _riga(5, origine="analisi_rapida"),                           # non Top Mix -> fuori dal conto
    ]
    # La chiave e' ``dedup_key``: match_id + origine + versione del selettore +
    # variante. La proposta qui sotto ha la stessa chiave della riga 4.
    PROPOSTE = [{"match_id": 4, "origin": "top_mix", "model_variant": "legacy"}]

    def test_conta_solo_le_top_mix(self):
        d = RN.confronta(self.RIGHE, self.PROPOSTE)
        self.assertEqual(4, d["righe_top_mix"], "la riga di Analisi Rapida non entra nel conto")

    def test_la_riga_del_replay_non_e_fra_le_non_ritrovate(self):
        d = RN.confronta(self.RIGHE, self.PROPOSTE)
        self.assertNotIn(4, [x["match_id"] for x in d["non_ritrovate"]])

    def test_elenco_con_data_partita_e_periodo(self):
        d = RN.confronta(self.RIGHE, self.PROPOSTE)
        per_id = {x["match_id"]: x for x in d["non_ritrovate"]}
        self.assertEqual({"1", "2", "3"}, {str(k) for k in per_id})
        self.assertEqual("22/08/2026 18:30", per_id[1]["data_partita"])
        self.assertIn("partita prima della finestra", per_id[1]["periodo"])
        self.assertIn("scritta prima della finestra", per_id[1]["periodo"])
        self.assertIn("partita dentro la finestra", per_id[2]["periodo"],
                      "una riga dentro la finestra che il replay non riproduce e' un caso DA VEDERE")
        self.assertEqual("2025/2026", per_id[3]["stagione"])

    def test_periodo_dopo_il_merge_dichiarato(self):
        riga = _riga(9, data="19/09/2026 20:45", salvato="19/09/2026 19:00")
        self.assertIn("scritta DOPO il merge", RN.periodo(riga))

    def test_il_referto_compatto_ha_una_riga_per_partita(self):
        d = RN.confronta(self.RIGHE, self.PROPOSTE)
        compatte = RN.righe_compatti(d, stagione="2026/2027")
        righe = [r for r in compatte if r.startswith("RIGA|")]
        self.assertEqual(2, len(righe), "la stagione 2025/2026 si esclude con --stagione")
        self.assertTrue(any("PERIODO|" in r for r in compatte))

    def test_senza_referto_del_replay_non_si_inventa(self):
        # main() con un referto inesistente deve uscire 2, non ``0`` con un elenco vuoto.
        from unittest import mock as _mock
        righe_finte = ([], "upstash")
        with _mock.patch.object(RN, "load_registry_readonly", return_value=righe_finte):
            self.assertEqual(2, RN.main(["--replay-json", "/tmp/non-esiste-mai.json"]))


if __name__ == "__main__":
    unittest.main()
