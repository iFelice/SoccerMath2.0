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


def _riga(mid, *, variante=None, ko="2026-09-10T18:00:00Z", mercato="1", prob=70.0,
          data=None, salvato_il=None):
    """Una riga del Registro. ``ko`` di default e' PRIMA del merge di PR#24:
    una riga senza campo scritta allora appartiene al motore che girava allora
    (il legacy), e la convenzione di lettura deve dirlo."""
    r = {"match_id": mid, "origin": "top_mix", "home": f"H{mid}", "away": f"A{mid}",
         "campionato": "Serie A", "data": data or "10/09/2026 20:00", "kickoff_utc": ko,
         "mercato_standard": mercato, "prob_sicuro": prob, "esito": "✅"}
    if salvato_il is not None:
        r["salvato_il"] = salvato_il
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

    def test_riga_senza_etichetta_si_legge_dalla_data(self):
        """La correzione chiesta: una riga senza campo nata PRIMA del merge di
        PR#24 e' del motore che girava allora, cioe' ``legacy`` — non ``current``
        per definizione. Qui la riga senza campo finisce nello stesso insieme
        della riga legacy esplicita: e' la stessa partita, stesso modello."""
        righe = [_riga(1, variante=None), _riga(2, variante=MODEL_VARIANT_LEGACY)]
        esito = chk.verifica(righe)
        self.assertEqual(1, esito["intero"]["righe_senza_variante"])
        self.assertEqual(1, esito["intero"]["righe_con_variante_esplicita"])
        self.assertEqual(0, esito["intero"]["partite"][MODEL_VARIANT_CURRENT],
                         "nessuna riga di questa epoca e' del modello attuale")
        self.assertEqual(2, esito["intero"]["partite"][MODEL_VARIANT_LEGACY])
        se = esito["intero"]["senza_etichetta"]
        self.assertEqual(1, se["prima_della_fusione"])
        self.assertEqual(0, se["dopo_la_fusione"])
        self.assertEqual(0, se["istante_ignoto"])
        self.assertEqual({"kickoff_utc": 1}, se["fonti"])

    def test_riga_senza_etichetta_dopo_la_fusione_e_attuale(self):
        dopo = _riga(1, variante=None, ko="2026-09-19T18:00:00Z")
        esito = chk.verifica([dopo])
        self.assertEqual(1, esito["intero"]["partite"][MODEL_VARIANT_CURRENT])
        se = esito["intero"]["senza_etichetta"]
        self.assertEqual(0, se["prima_della_fusione"])
        self.assertEqual(1, se["dopo_la_fusione"])

    def test_salvato_il_vince_sulla_data_della_partita(self):
        """L'istante che conta e' quando la riga e' nata: ``salvato_il`` batte la
        data della partita (una partita del 10/09 salvata il 19/09 e' del motore
        nuovo, anche se il campo variante non c'e')."""
        r = _riga(1, variante=None, data="10/09/2026 20:00", salvato_il="19/09/2026 09:00")
        esito = chk.verifica([r])
        self.assertEqual(1, esito["intero"]["partite"][MODEL_VARIANT_CURRENT])
        self.assertEqual({"salvato_il": 1}, esito["intero"]["senza_etichetta"]["fonti"])

    def test_riga_senza_kickoff_si_legge_dalla_data_italiana(self):
        """Le righe storiche non hanno ``kickoff_utc``: l'istante (e quindi la
        variante) si legge dalla ``data`` italiana, e la fonte va dichiarata."""
        r = _riga(1, variante=None, ko=None, data="10/09/2026 20:00")
        esito = chk.verifica([r])
        self.assertEqual(1, esito["intero"]["partite"][MODEL_VARIANT_LEGACY])
        se = esito["intero"]["senza_etichetta"]
        self.assertEqual(1, se["prima_della_fusione"])
        self.assertEqual({"data_partita": 1}, se["fonti"])
        self.assertEqual(0, se["istante_ignoto"])

    def test_differenze_distinguono_replay_e_click_veri(self):
        """Una riga senza variante e' un click vero dell'epoca, non una riga del
        replay: i conteggi devono poterlo dire, e dire anche da dove viene la
        variante (campo esplicito o istante)."""
        storica = _riga(1, variante=None)                        # click vero, prima del merge
        del_replay = _riga(2, variante=MODEL_VARIANT_CURRENT)    # scritta dal replay
        dopo = _riga(3, variante=None, ko="2026-09-19T18:00:00Z")  # click vero, dopo il merge
        esito = chk.verifica([storica, del_replay, dopo])
        per_id = {v["match_id"]: v for v in esito["intero"]["solo"][MODEL_VARIANT_CURRENT]}
        self.assertEqual({2, 3}, set(per_id))
        self.assertFalse(per_id[3]["riga_del_replay"])
        self.assertTrue(per_id[3]["riga_storica"])
        self.assertEqual("kickoff_utc", per_id[3]["variante_da"])
        self.assertTrue(per_id[2]["riga_del_replay"])
        self.assertEqual("esplicita", per_id[2]["variante_da"])
        per_id_legacy = {v["match_id"]: v for v in esito["intero"]["solo"][MODEL_VARIANT_LEGACY]}
        self.assertEqual({1}, set(per_id_legacy))
        self.assertEqual("kickoff_utc", per_id_legacy[1]["variante_da"])

    def test_partita_con_entrambe_le_specie_di_riga(self):
        """Click vero E riga del replay sulla stessa partita e stessa variante:
        due righe, e la voce deve dire che ci sono tutte e due."""
        righe = [_riga(1, variante=None), _riga(1, variante=MODEL_VARIANT_LEGACY)]
        esito = chk.verifica(righe)
        voce = esito["intero"]["solo"][MODEL_VARIANT_LEGACY][0]
        self.assertEqual(2, voce["righe"])
        self.assertTrue(voce["riga_del_replay"] and voce["riga_storica"])

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
        self.assertIn("senza la riga del modello LEGACY", testo)
        self.assertIn("non si scrivono", testo, "le righe legacy mancanti non si inventano")

    def test_allow_mismatch_esce_0(self):
        righe = [_riga(1, variante=MODEL_VARIANT_CURRENT)]
        rc, _ = self._esegui(righe, ["--allow-mismatch"])
        self.assertEqual(chk.ESITO_PAREGGIO, rc)

    def test_righe_attuale_mancanti_dichiarate_da_scrivere(self):
        righe = [_riga(1, variante=MODEL_VARIANT_LEGACY)]
        rc, testo = self._esegui(righe, ["--allow-mismatch"])
        self.assertEqual(chk.ESITO_PAREGGIO, rc)
        self.assertIn("senza la riga del modello ATTUALE", testo)
        self.assertIn("**1**", testo)
        self.assertIn("la diagnosi ne spiega ognuna", testo,
                      "una riga attuale mancante non spiegata deve poter rendere rossa la run")

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
