"""Test dello stato dei backend: deve essere SOLA LETTURA e dire la verita'.

Il comando piu' pericoloso della migrazione e' quello che sembra innocuo: se
"stato dei backend" scrivesse qualcosa, la fase B (verifica prima della copia)
non sarebbe piu' una verifica. Qui si controlla che:

1. non venga inviato NESSUN comando di scrittura (SET/HSET/PUT) — si guardano le
   chiamate di rete, non il codice;
2. le differenze fra i due Registri siano contate per chiave di campo;
3. un backend illeggibile faccia uscire 1 e lo dica, con l'errore vero.
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

import registry_backend_status as status  # noqa: E402


def _riga(match_id=1, variante="current", prob=60.0):
    return {"match_id": match_id, "origin": "top_mix", "model_variant": variante,
            "home": "Inter", "away": "Milan", "campionato": "Serie A", "data": "10/09/2026 20:00",
            "mercato_standard": "1", "prob_sicuro": prob, "salvato_il": "10/09/2026 18:00"}


class _PostRegistrato:
    def __init__(self, hgetall=None, null=False):
        self.hgetall = hgetall if hgetall is not None else {}
        self.null = null
        self.comandi = []

    def __call__(self, url, json=None, headers=None, timeout=None):  # noqa: A002
        self.comandi.append(json)
        nome = str(json[0]).upper()
        corpo = {"result": None}
        if nome == "HGETALL":
            corpo = {"result": None if self.null else self.hgetall}
        elif nome == "DBSIZE":
            corpo = {"result": len(self.hgetall)}
        elif nome == "KEYS":
            corpo = {"result": "\n".join(self.hgetall)}

        class _R:
            status_code = 200
            text = ""

            def __init__(self, p):
                self._p = p

            def json(self):
                return self._p
        return _R(corpo)


class TestStatoSolaLettura(unittest.TestCase):
    """Percorso VERO: si intercetta la rete e si guarda cosa e' partito."""

    def _esegui_con_rete(self, post, righe_jsonbin):
        env = {"REGISTRY_BACKEND": "upstash", "UPSTASH_REDIS_REST_URL": "https://db.upstash.io",
               "UPSTASH_REDIS_REST_TOKEN": "tok", "JSONBIN_API_KEY": "k", "JSONBIN_BIN_ID": "b"}
        with mock.patch.dict(os.environ, env), \
             mock.patch("requests.post", post), \
             mock.patch.object(status, "leggi_jsonbin", return_value=(righe_jsonbin, "ok")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = status.main(["--mostra", "2"])
        return rc, out.getvalue()

    def test_nessun_comando_di_scrittura(self):
        post = _PostRegistrato({"1|top_mix||current": json.dumps(_riga())})
        rc, testo = self._esegui_con_rete(post, [_riga()])
        self.assertEqual(0, rc)
        comandi = [str(c[0]).upper() for c in post.comandi]
        self.assertEqual(["HGETALL", "DBSIZE", "KEYS"], comandi,
                         "lo stato del backend e' sola lettura: HGETALL, DBSIZE, KEYS")
        self.assertIn("i due Registri coincidono", testo)

    def test_chiave_inesistente_non_rompe_e_mostra_zero_righe(self):
        post = _PostRegistrato(null=True)
        rc, testo = self._esegui_con_rete(post, [_riga(1), _riga(2)])
        self.assertEqual(0, rc)
        self.assertIn("Upstash: **0 righe**", testo)
        self.assertIn("database nuovo", testo)
        self.assertEqual(["HGETALL", "DBSIZE", "KEYS"], [str(c[0]).upper() for c in post.comandi])
        self.assertIn("chiavi nel database (**0**)", testo)


class TestUscita(unittest.TestCase):
    def _esegui(self, righe_jb, errore_jb, righe_us, errore_us, argv=None):
        with mock.patch.object(status, "leggi_jsonbin", return_value=(righe_jb, errore_jb)), \
             mock.patch.object(status, "leggi_upstash", return_value=(righe_us, errore_us)):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = status.main(argv or [])
        return rc, out.getvalue()

    def test_conta_le_differenze_per_campo(self):
        rc, testo = self._esegui([_riga(1), _riga(2, prob=70.0)], "ok", [_riga(2)], "ok")
        self.assertEqual(0, rc)
        self.assertIn("solo su JSONBin **1**", testo)
        self.assertIn("solo su Upstash **0**", testo)

    def test_identici_lo_dice(self):
        rc, testo = self._esegui([_riga(1)], "ok", [_riga(1)], "ok")
        self.assertEqual(0, rc)
        self.assertIn("i due Registri coincidono", testo)

    def test_upstash_vuoto_e_atteso_prima_della_copia(self):
        rc, testo = self._esegui([_riga(1), _riga(2)], "ok", [], "ok")
        self.assertEqual(0, rc)
        self.assertIn("database nuovo", testo)

    def test_backend_illeggibile_esce_1_e_lo_dice(self):
        rc, testo = self._esegui([_riga(1)], "ok", None, "RegistryStoreError: HTTP 401")
        self.assertEqual(1, rc)
        self.assertIn("NON leggibile", testo)
        self.assertIn("HTTP 401", testo)

    def test_errore_di_jsonbin_non_impedisce_di_vedere_upstash(self):
        rc, testo = self._esegui(None, "HTTP 403", [_riga(1)], "ok")
        self.assertEqual(1, rc)
        self.assertIn("JSONBin: NON leggibile", testo)
        self.assertIn("Upstash: **1 righe**", testo)
