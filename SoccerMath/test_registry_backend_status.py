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
        # Due HGETALL: le righe, e i NOMI dei campi (diagnosi). Mai una scrittura.
        self.assertEqual(["HGETALL", "DBSIZE", "KEYS", "HGETALL"], comandi,
                         "lo stato del backend e' sola lettura: HGETALL, DBSIZE, KEYS")
        self.assertIn("i due Registri coincidono", testo)

    def test_chiave_inesistente_non_rompe_e_mostra_zero_righe(self):
        post = _PostRegistrato(null=True)
        rc, testo = self._esegui_con_rete(post, [_riga(1), _riga(2)])
        self.assertEqual(0, rc)
        self.assertIn("Upstash: **0 righe**", testo)
        self.assertIn("database nuovo", testo)
        self.assertEqual(["HGETALL", "DBSIZE", "KEYS", "HGETALL"],
                         [str(c[0]).upper() for c in post.comandi])
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


class TestCampiDellHash(unittest.TestCase):
    """Il campo dell'hash e' la chiave ricalcolata: se la convenzione cambia, il
    nome vecchio resta accanto a quello nuovo (una riga, due campi). La diagnosi
    deve VEDERLO — e' l'effetto collaterale da misurare, non da nascondere."""

    def _riga_senza_campo(self, match_id=5):
        riga = _riga(match_id)
        riga.pop("model_variant")
        riga["salvato_il"] = "05/09/2026 18:18"      # prima del merge di PR#24
        return riga

    def test_nome_vecchio_e_riga_doppia_vengono_contati(self):
        riga = self._riga_senza_campo()
        nuovo = status.rs.field_of(riga)
        vecchio = nuovo.rsplit("|", 1)[0] + "|current"
        self.assertNotEqual(vecchio, nuovo, "il nome vecchio e quello ricalcolato devono differire")
        post = _PostRegistrato({vecchio: json.dumps(riga), nuovo: json.dumps(riga)})
        with mock.patch.dict(os.environ, {"REGISTRY_BACKEND": "upstash",
                                          "UPSTASH_REDIS_REST_URL": "https://db.upstash.io",
                                          "UPSTASH_REDIS_REST_TOKEN": "tok"}), \
             mock.patch("requests.post", post), \
             mock.patch.object(status, "leggi_jsonbin", return_value=([riga], "ok")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = status.main(["--mostra", "2"])
        testo = out.getvalue()
        self.assertEqual(0, rc)
        self.assertIn("campi dell'hash: **2**", testo)
        self.assertIn("allineati alla chiave ricalcolata **1**", testo)
        self.assertIn("con nome vecchio **1**", testo)
        self.assertIn("righe distinte **1**", testo)
        self.assertIn("chiavi doppie **1**", testo)
        self.assertIn(f"`{vecchio}` -> ricalcolato `{nuovo}`", testo)

    def test_hash_allineato_non_segnala_nulla(self):
        riga = _riga(1)
        post = _PostRegistrato({status.rs.field_of(riga): json.dumps(riga)})
        with mock.patch.dict(os.environ, {"REGISTRY_BACKEND": "upstash",
                                          "UPSTASH_REDIS_REST_URL": "https://db.upstash.io",
                                          "UPSTASH_REDIS_REST_TOKEN": "tok"}), \
             mock.patch("requests.post", post), \
             mock.patch.object(status, "leggi_jsonbin", return_value=([riga], "ok")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                status.main(["--mostra", "2"])
        testo = out.getvalue()
        self.assertIn("campi dell'hash: **1**", testo)
        self.assertIn("con nome vecchio **0**", testo)
        self.assertIn("chiavi doppie **0**", testo)


class TestDoppioniDellHash(unittest.TestCase):
    """Due campi, stessa chiave: o e' la stessa riga scritta due volte (nome
    vecchio + nome nuovo) o sono due righe diverse che la chiave non distingue.
    Le due cose vanno contate SEPARATE: la prima e' solo disordine, la seconda
    puo' nascondere una riga non piu' raggiungibile."""

    def _riga_senza_campo(self, match_id=5):
        riga = _riga(match_id)
        riga.pop("model_variant")
        riga["salvato_il"] = "05/09/2026 18:18"
        return riga

    def _esegui(self, hash_campi):
        post = _PostRegistrato(hash_campi)
        righe = [json.loads(v) for v in hash_campi.values()]
        with mock.patch.dict(os.environ, {"REGISTRY_BACKEND": "upstash",
                                          "UPSTASH_REDIS_REST_URL": "https://db.upstash.io",
                                          "UPSTASH_REDIS_REST_TOKEN": "tok"}), \
             mock.patch("requests.post", post), \
             mock.patch.object(status, "leggi_jsonbin", return_value=(righe, "ok")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = status.main(["--mostra", "3"])
        return rc, out.getvalue()

    def test_doppione_identico_non_e_un_conflitto(self):
        riga = self._riga_senza_campo()
        nuovo = status.rs.field_of(riga)
        vecchio = nuovo.rsplit("|", 1)[0] + "|current"
        rc, testo = self._esegui({vecchio: json.dumps(riga), nuovo: json.dumps(riga)})
        self.assertEqual(0, rc)
        self.assertIn("doppioni: **1** righe scritte due volte", testo)
        self.assertIn("**0** chiavi con valori DIVERSI", testo)
        self.assertIn("righe senza campo variante **2**", testo)

    def test_due_righe_diverse_sulla_stessa_chiave_vengono_mostrate(self):
        riga = _riga(7)                    # campo esplicito: chiave stabile
        chiave = status.rs.field_of(riga)
        altra = dict(riga, prob_sicuro=71.5, salvato_il="20/09/2026 15:04")
        rc, testo = self._esegui({chiave: json.dumps(riga),
                                  chiave + "_bis": json.dumps(altra)})
        self.assertEqual(0, rc)
        self.assertIn("**1** chiavi con valori DIVERSI", testo)
        self.assertIn("STESSA CHIAVE", testo)
        self.assertIn("71.5%", testo)

    def test_variante_letta_per_data_e_contata(self):
        riga = self._riga_senza_campo()
        chiave = status.rs.field_of(riga)
        rc, testo = self._esegui({chiave: json.dumps(riga)})
        self.assertEqual(0, rc)
        self.assertIn("variante letta (campo esplicito o DATA): `legacy` **1**", testo)
