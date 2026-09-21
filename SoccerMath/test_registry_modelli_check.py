"""Test della verifica dei due modelli: deve contare, non raccontare.

Casi che contano:
- campioni uguali -> esito 0 e lo dice;
- campioni diversi -> esito 1 e Dice QUALE modello ha di piu';
- il confine PR#24 separa la storia all'ISTANTE (half-open), non al giorno;
- le righe storiche senza campo variante sono contate a parte (il campo non
  esisteva: leggerle come "attuale" senza dirlo sarebbe un numero ingannevole);
- righe del modello attuale mancanti -> "da scrivere"; righe legacy mancanti ->
  dichiarate non scrivibili (sotto soglia / veto);
- Registro illeggibile -> esito 2, nessuna verifica inventata.
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
import contextlib
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import registry_modelli_check as chk  # noqa: E402
from prediction_registry import MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY  # noqa: E402


def _riga(mid, *, variante=None, ko="2026-09-10T18:00:00Z", mercato="1", prob=70.0):
    r = {"match_id": mid, "origin": "top_mix", "home": f"H{mid}", "away": f"A{mid}",
         "campionato": "Serie A", "data": "10/09/2026 20:00", "kickoff_utc": ko,
         "mercato_standard": mercato, "prob_sicuro": prob, "esito": "✅"}
    if variante is not None:
        r["model_variant"] = variante
    return r


class TestConteggi(unittest.TestCase):
    def test_campioni_uguali(self):
        righe = [_riga(1, variante=MODEL_VARIANT_CURRENT), _riga(1, variante=MODEL_VARIANT_LEGACY)]
        esito = chk.verifica(righe)
        self.assertTrue(esito["intero"]["pareggio"])
        self.assertEqual(1, esito["intero"]["comuni"])
        self.assertEqual(1, esito["intero"]["partite"][MODEL_VARIANT_CURRENT])

    def test_modello_attuale_in_piu(self):
        righe = [_riga(1, variante=MODEL_VARIANT_CURRENT), _riga(1, variante=MODEL_VARIANT_LEGACY),
                 _riga(2, variante=MODEL_VARIANT_CURRENT)]
        esito = chk.verifica(righe)
        self.assertFalse(esito["intero"]["pareggio"])
        self.assertEqual(1, len(esito["intero"]["solo"][MODEL_VARIANT_CURRENT]))
        self.assertEqual(0, len(esito["intero"]["solo"][MODEL_VARIANT_LEGACY]))

    def test_confine_a_istante_non_a_giorno(self):
        """Due partite lo stesso giorno, una prima e una dopo il merge."""
        prima = _riga(1, variante=MODEL_VARIANT_LEGACY, ko="2026-09-18T20:00:00Z")
        dopo = _riga(2, variante=MODEL_VARIANT_LEGACY, ko="2026-09-18T23:00:00Z")
        esito = chk.verifica([prima, dopo])
        self.assertEqual(1, esito["vecchio"]["righe"])
        self.assertEqual(1, esito["nuovo"]["righe"])

    def test_righe_storiche_senza_variante_contate_a_parte(self):
        righe = [_riga(1, variante=None), _riga(1, variante=MODEL_VARIANT_LEGACY)]
        esito = chk.verifica(righe)
        self.assertEqual(1, esito["intero"]["righe_senza_variante"])
        self.assertEqual(1, esito["intero"]["righe_con_variante_esplicita"])
        self.assertTrue(esito["intero"]["pareggio"],
                        "la riga senza campo vale current: la partita ha entrambi i modelli")

    def test_differenze_distinguono_replay_e_click_veri(self):
        """Una riga senza variante e' un click vero dell'epoca, non una riga del
        replay: i conteggi devono poterlo dire (l'utente lo chiede esplicitamente)."""
        storica = _riga(1, variante=None)                       # click vero, campo assente
        del_replay = _riga(2, variante=MODEL_VARIANT_CURRENT)   # scritta dal replay
        esito = chk.verifica([storica, del_replay])
        voci = esito["intero"]["solo"][MODEL_VARIANT_CURRENT]
        self.assertEqual(2, len(voci))
        self.assertEqual(1, sum(1 for v in voci if v["variante_esplicita"]))
        self.assertEqual({1, 2}, {v["match_id"] for v in voci})

    def test_fuori_finestra_ignorate(self):
        vecchia = _riga(9, variante=MODEL_VARIANT_CURRENT, ko="2026-05-01T18:00:00Z")
        esito = chk.verifica([vecchia])
        self.assertEqual(0, esito["intero"]["righe"], "prima del 2026-08-30 non e' ricostruibile")


class TestRefertoEUscta(unittest.TestCase):
    def _esegui(self, righe, argv=None):
        with mock.patch("registry_coverage_check.load_registry_readonly", return_value=(righe, "finto")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = chk.main(argv or [])
        return rc, out.getvalue()

    def test_pareggio_esce_0(self):
        righe = [_riga(1, variante=MODEL_VARIANT_CURRENT), _riga(1, variante=MODEL_VARIANT_LEGACY)]
        rc, testo = self._esegui(righe)
        self.assertEqual(chk.ESITO_PAREGGIO, rc)
        self.assertIn("i due campioni COINCIDONO", testo)

    def test_disparita_esce_1_e_dice_quale(self):
        righe = [_riga(1, variante=MODEL_VARIANT_CURRENT)]
        rc, testo = self._esegui(righe)
        self.assertEqual(chk.ESITO_DISPARI, rc)
        self.assertIn("NON coincidono", testo)
        self.assertIn("attuale copre 1 partite in piu'", testo)
        self.assertIn("non si scrivono", testo, "le righe legacy mancanti non si inventano")

    def test_allow_mismatch_esce_0(self):
        righe = [_riga(1, variante=MODEL_VARIANT_CURRENT)]
        rc, _ = self._esegui(righe, ["--allow-mismatch"])
        self.assertEqual(chk.ESITO_PAREGGIO, rc)

    def test_righe_attuale_mancanti_dichiarate_da_scrivere(self):
        righe = [_riga(1, variante=MODEL_VARIANT_LEGACY)]
        rc, testo = self._esegui(righe, ["--allow-mismatch"])
        self.assertEqual(chk.ESITO_PAREGGIO, rc)
        self.assertIn("da scrivere: **1**", testo)

    def test_registro_illeggibile_esce_2(self):
        def esplode():
            raise RuntimeError("backend giu'")
        with mock.patch("registry_coverage_check.load_registry_readonly", esplode):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = chk.main([])
        self.assertEqual(chk.ESITO_ERRORE, rc)
        self.assertIn("nessuna verifica possibile", out.getvalue())

    def test_json_riporta_i_tre_livelli(self):
        import tempfile
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        f.close()
        self.addCleanup(os.unlink, f.name)
        righe = [_riga(1, variante=MODEL_VARIANT_CURRENT), _riga(1, variante=MODEL_VARIANT_LEGACY)]
        self._esegui(righe, ["--json", f.name])
        with open(f.name, encoding="utf-8") as fh:
            dati = json.load(fh)
        self.assertEqual(["vecchio", "nuovo", "intero"], [k for k in ("vecchio", "nuovo", "intero") if k in dati])
        self.assertEqual("finto", dati["fonte"])
        self.assertTrue(dati["intero"]["pareggio"])
