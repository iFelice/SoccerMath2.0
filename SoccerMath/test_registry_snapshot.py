"""Test dell'istantanea giornaliera: deve essere fedele o non esistere.

Un'istantanea che non si rilegge, o che non coincide con il Registro, e' peggio
di nessuna istantanea: sembra un punto di ripristino e non lo e'. Qui si blinda:
- si scrive solo dopo aver LETTO il Registro (remoto illeggibile -> nessun SET);
- un Registro vuoto non produce istantanea;
- l'istantanea viene riletta e confrontata riga per riga;
- se non coincide, l'esito e' 1;
- in prova non parte nessuna scrittura.
"""
from __future__ import annotations

import io
import json
import json as _json
import os
import sys
import tempfile
import unittest
import contextlib
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import registry_snapshot as snap  # noqa: E402
import registry_store as rs  # noqa: E402

REGISTRO = "sm:registro"


def _riga(match_id=1):
    return {"match_id": match_id, "origin": "top_mix", "model_variant": "current",
            "home": "Inter", "away": "Milan", "mercato_standard": "1", "prob_sicuro": 61.0}


class _RedisFinto:
    """Chiavi vere (Registro + istantanea), con dizionari CONDIVISI."""

    def __init__(self, registro=None, ignora_set=False, set_alterato=False):
        self.chiavi = {REGISTRO: registro} if registro is not None else {}
        self.ignora_set = ignora_set
        self.set_alterato = set_alterato
        self.comandi = []

    def __call__(self, url, json=None, headers=None, timeout=None):  # noqa: A002
        self.comandi.append(list(json))
        nome = str(json[0]).upper()
        chiave = json[1] if len(json) > 1 else None
        risultato = None
        if nome == "HGETALL":
            store = self.chiavi.get(chiave) or {}
            if store and not isinstance(next(iter(store.values())), str):
                piatto = []
                for k, v in store.items():
                    piatto += [k, v]
                risultato = piatto
            elif store:
                risultato = dict(store)
        elif nome == "SET":
            if not self.ignora_set:
                righe = _json.loads(json[2])
                if self.set_alterato and righe:
                    righe[0] = dict(righe[0], prob_sicuro=99.9)
                self.chiavi[chiave] = righe
            risultato = "OK"
        elif nome == "GET":
            righe = self.chiavi.get(chiave)
            risultato = _json.dumps(righe, ensure_ascii=False) if righe is not None else None

        class _R:
            status_code = 200
            text = ""

            def json(self):
                return {"result": risultato}
        return _R()


def _hash_di(righe):
    return {rs.field_of(r): _json.dumps(r, ensure_ascii=False, sort_keys=True, default=str) for r in righe}


class TestIstantanea(unittest.TestCase):
    def _esegui(self, post, argv=None):
        env = {"REGISTRY_BACKEND": "upstash", "UPSTASH_REDIS_REST_URL": "https://db.upstash.io",
               "UPSTASH_REDIS_REST_TOKEN": "tok"}
        with mock.patch.dict(os.environ, env), mock.patch("requests.post", post):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = snap.main(argv or ["--giorno", "2026-09-21"])
        return rc, out.getvalue()

    def test_scrive_e_verifica(self):
        post = _RedisFinto(_hash_di([_riga(1), _riga(2)]))
        rc, testo = self._esegui(post)
        self.assertEqual(snap.ESITO_OK, rc)
        self.assertIn("istantanea fedele", testo)
        self.assertEqual(["HGETALL", "SET", "GET"], [c[0] for c in post.comandi])
        self.assertEqual(2, len(post.chiavi[rs.snapshot_key("2026-09-21")]))

    def test_registro_illeggibile_non_scrive(self):
        def esplode(url, json=None, headers=None, timeout=None):  # noqa: A002
            raise RuntimeError("rete giu'")
        rc, testo = self._esegui(esplode, ["--giorno", "2026-09-21", "--json", self._tmp()])
        self.assertEqual(snap.ESITO_ERRORE, rc)
        self.assertIn("NESSUNA istantanea scritta", testo)
        self.assertIn("degradazione dichiarata", testo)

    def test_registro_vuoto_non_scrive(self):
        post = _RedisFinto(registro={})
        rc, testo = self._esegui(post)
        self.assertEqual(snap.ESITO_ERRORE, rc)
        self.assertIn("VUOTO", testo)
        self.assertNotIn("SET", [c[0] for c in post.comandi])

    def test_prova_non_scrive(self):
        post = _RedisFinto(_hash_di([_riga(1)]))
        rc, testo = self._esegui(post, ["--giorno", "2026-09-21", "--prova"])
        self.assertEqual(snap.ESITO_OK, rc)
        self.assertEqual(["HGETALL"], [c[0] for c in post.comandi])
        self.assertIn("prova", testo)

    def test_istantanea_non_rileggibile_esce_1(self):
        post = _RedisFinto(_hash_di([_riga(1)]), ignora_set=True)
        rc, testo = self._esegui(post)
        self.assertEqual(snap.ESITO_ERRORE, rc)
        self.assertIn("NON rileggibile", testo)

    def test_istantanea_diversa_esce_1(self):
        post = _RedisFinto(_hash_di([_riga(1)]), set_alterato=True)
        rc, testo = self._esegui(post)
        self.assertEqual(snap.ESITO_ERRORE, rc)
        self.assertIn("DIVERSA dal Registro", testo)

    def test_json_riporta_verifica(self):
        percorso = self._tmp()
        post = _RedisFinto(_hash_di([_riga(1)]))
        rc, _ = self._esegui(post, ["--giorno", "2026-09-21", "--json", percorso])
        self.assertEqual(snap.ESITO_OK, rc)
        with open(percorso, encoding="utf-8") as f:
            dati = json.load(f)
        self.assertTrue(dati["scritto"])
        self.assertTrue(dati["verificata"])
        self.assertEqual("sm:registro:snapshot:2026-09-21", dati["chiave"])

    def _tmp(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name
