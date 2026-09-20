"""Test della copia JSONBin -> Upstash (fase C): deve copiare TUTTO e MAI
sovrascrivere, e non deve scrivere se prima non ha letto.

I casi che contano davvero:
- prova a vuoto: nessuna scrittura parte;
- copia: una HGETALL + UN HSET, poi rilettura e verifica di uguaglianza;
- conflitto: un campo diverso sull'hash ferma tutto PRIMA di scrivere;
- JSONBin illeggibile: zero comandi in uscita;
- idempotenza: se c'e' gia' tutto identico, non parte nessun HSET;
- verifica: se dopo la scrittura l'hash non coincide, l'operazione fallisce
  anche se la HSET ha risposto ok.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import contextlib
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import registry_migrate as mig  # noqa: E402
import registry_store as rs  # noqa: E402


def _riga(match_id=1, variante="current", prob=60.0):
    return {"match_id": match_id, "origin": "top_mix", "model_variant": variante,
            "home": "Inter", "away": "Milan", "campionato": "Serie A", "data": "10/09/2026 20:00",
            "mercato_standard": "1", "prob_sicuro": prob, "salvato_il": "10/09/2026 18:00"}


class _PostFinto:
    """Modella l'hash di Upstash: il dict e' CONDIVISO, non copiato."""

    def __init__(self, hash_iniziale=None, ignora_hset=False):
        self.hash = hash_iniziale if hash_iniziale is not None else {}
        self.ignora_hset = ignora_hset
        self.comandi = []

    def __call__(self, url, json=None, headers=None, timeout=None):  # noqa: A002
        self.comandi.append(list(json))
        nome = str(json[0]).upper()
        risultato = None
        if nome == "HGETALL":
            risultato = dict(self.hash)
        elif nome == "HSET" and not self.ignora_hset:
            campi = json[2:]
            for i in range(0, len(campi), 2):
                self.hash[campi[i]] = campi[i + 1]
            risultato = len(campi) // 2
        elif nome == "HSET":
            risultato = len(json[2:]) // 2

        class _R:
            status_code = 200
            text = ""

            def json(self):
                return {"result": risultato}
        return _R()


def _campo(riga):
    return rs.field_of(riga)


class TestPiano(unittest.TestCase):
    def _esegui(self, argv, righe_jsonbin, post, righe_jsonbin_errore=None):
        env = {"REGISTRY_BACKEND": "upstash", "UPSTASH_REDIS_REST_URL": "https://db.upstash.io",
               "UPSTASH_REDIS_REST_TOKEN": "tok", "JSONBIN_API_KEY": "k", "JSONBIN_BIN_ID": "b"}
        effetto = (mock.Mock(side_effect=righe_jsonbin_errore) if righe_jsonbin_errore
                   else mock.Mock(return_value=righe_jsonbin))
        with mock.patch.dict(os.environ, env), \
             mock.patch("requests.post", post), \
             mock.patch.object(rs, "jsonbin_rows", effetto):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = mig.main(argv)
        return rc, out.getvalue()

    def test_prova_a_vuoto_non_manda_scritture(self):
        post = _PostFinto()
        rc, testo = self._esegui([], [_riga(1), _riga(2)], post)
        self.assertEqual(mig.ESITO_OK, rc)
        self.assertEqual(["HGETALL"], [c[0] for c in post.comandi])
        self.assertIn("prova a vuoto", testo)
        self.assertEqual({}, post.hash)

    def test_esegui_copia_con_un_solo_hset_e_verifica(self):
        post = _PostFinto()
        rc, testo = self._esegui(["--esegui"], [_riga(1), _riga(2)], post)
        self.assertEqual(mig.ESITO_OK, rc)
        # piano (1 HGETALL) + copia (1 HGETALL + 1 HSET) + verifica (1 HGETALL)
        self.assertEqual(["HGETALL", "HGETALL", "HSET", "HGETALL"], [c[0] for c in post.comandi])
        self.assertEqual(2, len(post.hash))
        self.assertIn("comandi inviati: **2**", testo)
        self.assertIn(_campo(_riga(1)), post.hash)
        self.assertIn("i due Registri coincidono", testo)

    def test_conflitto_ferma_tutto_prima_di_scrivere(self):
        riga = _riga(1, prob=60.0)
        post = _PostFinto({_campo(riga): json.dumps(dict(riga, prob_sicuro=99.9))})
        rc, testo = self._esegui(["--esegui"], [riga], post)
        self.assertEqual(mig.ESITO_FERMATO, rc)
        self.assertEqual(["HGETALL"], [c[0] for c in post.comandi])
        self.assertIn("conflitt", testo)
        self.assertEqual(99.9, json.loads(post.hash[_campo(riga)])["prob_sicuro"],
                         "la riga esistente NON deve essere toccata")

    def test_jsonbin_illeggibile_non_tocca_upstash(self):
        post = _PostFinto()
        rc, testo = self._esegui(["--esegui"], None, post,
                                 righe_jsonbin_errore=rs.RegistryStoreError("JSONBin HTTP 500"))
        self.assertEqual(mig.ESITO_ERRORE, rc)
        self.assertEqual([], post.comandi, "prima si legge, poi si scrive")
        self.assertIn("NESSUNA scrittura inviata", testo)

    def test_idempotente_se_gia_presenti(self):
        righe = [_riga(1), _riga(2)]
        post = _PostFinto({_campo(r): json.dumps(r, ensure_ascii=False, sort_keys=True, default=str)
                           for r in righe})
        rc, testo = self._esegui(["--esegui"], righe, post)
        self.assertEqual(mig.ESITO_OK, rc)
        # con tutto gia' identico la copia non manda nessun HSET
        self.assertEqual(["HGETALL"] * 3, [c[0] for c in post.comandi])
        self.assertIn("gia' presenti identiche: 2", testo)

    def test_verifica_fallita_esce_1(self):
        post = _PostFinto(ignora_hset=True)
        rc, testo = self._esegui(["--esegui", "--json", self._tmp()], [_riga(1)], post)
        self.assertEqual(mig.ESITO_ERRORE, rc)
        self.assertIn("NON coincidono", testo)

    def _tmp(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_il_json_riporta_eseguito_e_esito(self):
        post = _PostFinto()
        percorso = self._tmp()
        rc, _ = self._esegui(["--esegui", "--json", percorso], [_riga(1)], post)
        self.assertEqual(mig.ESITO_OK, rc)
        with open(percorso, encoding="utf-8") as f:
            dati = json.load(f)
        self.assertTrue(dati["eseguito"])
        self.assertTrue(dati["coincidono"])
        self.assertEqual(2, dati["esito_copia"]["comandi"])
        self.assertEqual(1, dati["da_copiare"])
