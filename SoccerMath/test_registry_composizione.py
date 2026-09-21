"""Composizione del Registro: conteggi per origine, variante letta e stagione.

Nessuna rete: si prova ``analizza()`` su righe sintetiche che riproducono i casi
veri (click Top Mix senza campo nate prima del merge, righe di Analisi Rapida mai
prodotte dal Top Mix, righe del replay con la variante esplicita, righe senza
data). Il senso e' che il numero della tabella legacy NON e' il campione del
modello legacy: qui si dichiara di che specie sono le righe in piu'.
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import registry_composizione as RC  # noqa: E402


def _riga(origine, quando, *, variante=None, match_id=1, scheda=True, campionato="Serie A"):
    """Riga del Registro: ``quando`` e' la data italiana della partita."""
    r = {"match_id": match_id, "home": "Casa", "away": "Ospite", "campionato": campionato,
         "giornata": 1, "data": quando, "pronostico_sicuro": "1 - Top Mix",
         "mercato_standard": "1", "prob_sicuro": 60.0, "esito": "⏳",
         "origin": origine, "model_variant": variante} if variante else {
         "match_id": match_id, "home": "Casa", "away": "Ospite", "campionato": campionato,
         "giornata": 1, "data": quando, "pronostico_sicuro": "1 - Top Mix",
         "mercato_standard": "1", "prob_sicuro": 60.0, "esito": "⏳", "origin": origine}
    if scheda:
        r["model_version"] = "post_shrinkage_v1"
    return r


class TestComposizione(unittest.TestCase):
    RIGHE = [
        # 2 click Top Mix veri, senza campo, nati prima del merge -> letti legacy
        _riga("top_mix", "05/09/2026 18:00", match_id=1, scheda=False),
        _riga("top_mix", "07/09/2026 18:00", match_id=2, scheda=False),
        # 1 riga di Analisi Rapida, mai prodotta dal Top Mix -> legacy per data
        _riga("analisi_rapida", "24/08/2026 20:45", match_id=3, scheda=False),
        # 1 riga Billy
        _riga("billy", "23/08/2026 20:45", match_id=4, scheda=False),
        # righe del replay con la variante esplicita, in finestra
        _riga("top_mix", "19/09/2026 20:45", variante="current", match_id=5),
        _riga("top_mix", "20/09/2026 18:00", variante="legacy", match_id=6),
    ]

    def setUp(self):
        self.d = RC.analizza(self.RIGHE)

    def test_totale_e_varianti_lette(self):
        self.assertEqual(6, self.d["righe"])
        self.assertEqual({"current": 1, "legacy": 5}, self.d["per_variante"])

    def test_per_origine_dichiara_chi_non_e_top_mix(self):
        self.assertEqual({"Top Mix": 4, "Analisi Rapida": 1, "Billy": 1},
                         self.d["per_origine"])

    def test_incrocio_origine_per_variante(self):
        inc = self.d["origine_per_variante"]
        # Top Mix: 2 click veri senza campo (legacy) + 1 riga del replay legacy + 1 current
        self.assertEqual({"legacy": 3, "current": 1}, inc["Top Mix"])
        self.assertEqual({"legacy": 1}, inc["Analisi Rapida"])
        self.assertEqual({"legacy": 1}, inc["Billy"])

    def test_scheda_vecchia_conta_le_righe_senza_model_version(self):
        self.assertEqual({"Top Mix": 2, "Analisi Rapida": 1, "Billy": 1},
                         self.d["scheda_vecchia_per_origine"])

    def test_finestra_ricostruibile(self):
        # Solo le righe di settembre stanno dentro la finestra (dal 30/08).
        self.assertEqual(4, self.d["finestra"]["dentro la finestra ricostruibile"])
        self.assertEqual(2, self.d["finestra"]["fuori finestra (prima del 30/08/2026)"])

    def test_stagione_dal_campo_o_dalla_data(self):
        # Nessuna riga ha il campo 'stagione': si deriva dalla data (1 luglio).
        self.assertEqual({"2026/2027": 6}, self.d["per_stagione"])

    def test_riga_senza_data_non_inventa_una_stagione(self):
        d = RC.analizza([{"match_id": 9, "home": "A", "away": "B", "origin": "top_mix",
                          "pronostico_sicuro": "1", "mercato_standard": "1"}])
        self.assertEqual({"Sconosciuta": 1}, d["per_stagione"])
        self.assertEqual(1, d["istante_ignoto"])
        self.assertEqual(1, d["finestra"]["istante non leggibile"])

    def test_righe_senza_campo_variante(self):
        self.assertEqual(4, self.d["senza_campo_variante"])

    def test_elenco_delle_righe_non_top_mix(self):
        elenco = self.d["elenco"]
        # Il default esclude il Top Mix: resta cio' che non e' Top Mix.
        self.assertEqual({"Analisi Rapida", "Billy"}, set(elenco))
        self.assertEqual(1, len(elenco["Analisi Rapida"]))
        voce = elenco["Analisi Rapida"][0]
        self.assertIn("Casa - Ospite", voce)
        self.assertIn("origine `analisi_rapida`", voce)
        self.assertIn("match_id 3", voce)

    def test_incrocio_origine_per_stagione(self):
        self.assertEqual({"2026/2027": 4}, self.d["origine_per_stagione"]["Top Mix"])
        self.assertEqual({"2026/2027": 1}, self.d["origine_per_stagione"]["Billy"])

    def test_il_testo_riassume_senza_nascondere(self):
        testo = "\n".join(RC._righe_testo(self.d))
        self.assertIn("righe totali: **6**", testo)
        self.assertIn("Analisi Rapida", testo)
        self.assertIn("Billy", testo)
        self.assertIn("| origine | righe | lette attuale | lette legacy | senza `model_version` | stagioni |", testo)
        self.assertIn("### Elenco righe — origine Analisi Rapida (1)", testo)


if __name__ == "__main__":
    unittest.main()
