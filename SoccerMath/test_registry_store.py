"""Test di ``registry_store``: i due backend e il perche' della scelta.

Cosa deve restare vero (sono le proprieta' su cui si regge la migrazione):

1. **Con JSONBin il comportamento e' quello di prima**: un PUT del bin intero,
   con lo stesso payload e lo stesso trattamento degli errori.
2. **Con Upstash la scrittura tocca solo le righe nuove o cambiate**: un
   salvataggio che non cambia nulla non scrive (idempotenza), e due scrittori
   che aggiungono righe diverse non si sovrascrivono perche' usano campi
   diversi dello stesso hash. E' il difetto che il documento unico aveva.
3. **La chiave di campo e' ``dedup_key``**: righe della stessa partita ma di
   varianti diverse sono campi diversi (mai una che cancella l'altra).
4. **Un errore di rete non diventa mai una copia locale silenziosa** quando
   stiamo per scrivere (``strict=True``).
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import registry_store as rs  # noqa: E402
from prediction_registry import MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY  # noqa: E402


def _riga(match_id=1, variante=MODEL_VARIANT_CURRENT, **extra):
    riga = {"match_id": match_id, "origin": "top_mix", "model_variant": variante,
            "home": "Inter", "away": "Milan", "mercato_standard": "1", "prob_sicuro": 61.5}
    riga.update(extra)
    return riga


class _Risposta:
    """Risposta HTTP minima, come la vedrebbe il codice di produzione."""

    def __init__(self, status_code, payload, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class _PostFinto:
    """Registra i comandi inviati e risponde come Upstash."""

    def __init__(self, hgetall=None, hset_ok=True, status=200, null=False):
        # Riferimento, non copia: due "scrittori" che condividono lo stesso hash
        # devono vedersi a vicenda (e' il caso che il test deve riprodurre).
        self.hgetall = hgetall if hgetall is not None else {}
        self.hset_ok = hset_ok
        self.status = status
        self.null = null
        self.comandi = []

    def __call__(self, url, json=None, headers=None, timeout=None):  # noqa: A002 - nome dell'API
        self.comandi.append(json)
        nome = str(json[0]).upper()
        if nome == "HGETALL":
            # Redis risponde null (non {}) quando la chiave non esiste.
            return _Risposta(self.status, {"result": None if self.null else self.hgetall},
                             "" if self.status == 200 else "errore")
        if nome == "SET":
            return _Risposta(self.status, {"result": "OK"})
        if nome == "HSET":
            if not self.hset_ok:
                return _Risposta(500, {"error": "errore di scrittura"}, "errore")
            for i in range(2, len(json), 2):
                self.hgetall[json[i]] = json[i + 1]
            return _Risposta(200, {"result": (len(json) - 2) // 2})
        return _Risposta(400, {"error": f"comando non previsto: {nome}"}, "errore")


class TestCampo(unittest.TestCase):
    def test_campo_da_dedup_key_e_stabile(self):
        riga = _riga()
        campo = rs.field_of(riga)
        self.assertEqual(campo, rs.field_of(dict(riga)), "stessa riga, stesso campo")
        self.assertIn("top_mix", campo)

    def test_varianti_diverse_sono_campi_diversi(self):
        self.assertNotEqual(rs.field_of(_riga(variante=MODEL_VARIANT_LEGACY)),
                            rs.field_of(_riga(variante=MODEL_VARIANT_CURRENT)))

    def test_partite_diverse_sono_campi_diversi(self):
        self.assertNotEqual(rs.field_of(_riga(match_id=1)), rs.field_of(_riga(match_id=2)))


class TestBackendScelto(unittest.TestCase):
    def test_default_jsonbin(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REGISTRY_BACKEND", None)
            self.assertEqual(rs.BACKEND_JSONBIN, rs.backend())

    def test_upstash(self):
        with mock.patch.dict(os.environ, {"REGISTRY_BACKEND": "upstash"}):
            self.assertEqual(rs.BACKEND_UPSTASH, rs.backend())

    def test_valore_ignoto_ferma_tutto(self):
        with mock.patch.dict(os.environ, {"REGISTRY_BACKEND": "redis-casalingo"}):
            with self.assertRaises(rs.RegistryStoreError):
                rs.backend()


class TestUpstash(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"UPSTASH_REDIS_REST_URL": "https://db.upstash.io",
                                               "UPSTASH_REDIS_REST_TOKEN": "tok"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_leggi_hgetall(self):
        post = _PostFinto({"1|top_mix||current": json.dumps(_riga())})
        righe = rs.upstash_rows(post=post)
        self.assertEqual(1, len(righe))
        self.assertEqual("Inter", righe[0]["home"])
        self.assertEqual(["HGETALL", rs.hash_key()], post.comandi[0], "una HGETALL, niente altro")

    def test_chiave_inesistente_e_registro_vuoto(self):
        self.assertEqual([], rs.upstash_rows(post=_PostFinto(null=True)))

    def test_valori_illeggibili_ignorati_non_inventati(self):
        post = _PostFinto({"1|top_mix||current": "non json", "2|top_mix||current": json.dumps(_riga(2))})
        righe = rs.upstash_rows(post=post)
        self.assertEqual([2], [r["match_id"] for r in righe])

    def test_scrittura_solo_dei_campioni_nuovi_o_cambiati(self):
        esistente = _riga(match_id=1)
        cambiata = dict(esistente, prob_sicuro=70.0)
        nuova = _riga(match_id=2)
        post = _PostFinto({rs.field_of(esistente): json.dumps(esistente, ensure_ascii=False, sort_keys=True)})
        esito = rs.upstash_save([esistente, dict(cambiata, match_id=1), nuova], post=post)
        self.assertEqual(2, esito["righe_scritte"], "la riga identica va saltata")
        self.assertEqual(1, esito["righe_saltate"])
        hset = [c for c in post.comandi if c[0].upper() == "HSET"]
        self.assertEqual(1, len(hset), "un solo HSET, non uno per riga")
        self.assertIn(rs.field_of(nuova), hset[0])
        self.assertIn(rs.field_of(esistente), hset[0])

    def test_rilanciare_non_scrive_nulla(self):
        riga = _riga()
        post = _PostFinto({rs.field_of(riga): json.dumps(riga, ensure_ascii=False, sort_keys=True)})
        esito = rs.upstash_save([riga], post=post)
        self.assertEqual(0, esito["righe_scritte"])
        self.assertEqual([["HGETALL", rs.hash_key()]], post.comandi, "solo la lettura")
        self.assertEqual(1, esito["comandi"])

    def test_due_scrittori_con_righe_diverse_non_si_sovrascrivono(self):
        """Il cuore del problema risolto: la seconda scrittura non riscrive il
        Registro intero, quindi non puo' cancellare cio' che il primo ha
        aggiunto nel frattempo."""
        prima = _riga(match_id=1)
        dopo = _riga(match_id=2)
        hash_condiviso: dict = {}
        post_a = _PostFinto(hash_condiviso)
        rs.upstash_save([prima], post=post_a)
        post_b = _PostFinto(hash_condiviso)             # stesso hash, secondo scrittore
        rs.upstash_save([prima, dopo], post=post_b)
        self.assertIn(rs.field_of(prima), hash_condiviso)
        self.assertIn(rs.field_of(dopo), hash_condiviso)
        hset_b = [c for c in post_b.comandi if c[0].upper() == "HSET"][0]
        self.assertNotIn(rs.field_of(prima), hset_b, "la riga gia' presente non viene riscritta")

    def test_errore_upstash_non_e_silenzioso(self):
        with self.assertRaises(rs.RegistryStoreError):
            rs.upstash_rows(post=_PostFinto({}, status=401))

    def test_istantanea_giornaliera(self):
        post = _PostFinto()
        esito = rs.upstash_snapshot("2026-09-20", [_riga()], post=post)
        self.assertEqual("sm:registro:snapshot:2026-09-20", esito["chiave"])
        self.assertEqual("SET", post.comandi[0][0].upper())

    def test_senza_credenziali_errore_chiaro(self):
        with mock.patch.dict(os.environ, {"UPSTASH_REDIS_REST_URL": "", "UPSTASH_REDIS_REST_TOKEN": ""}):
            with self.assertRaises(rs.RegistryStoreError) as ctx:
                rs.upstash_rows(post=_PostFinto())
            self.assertIn("Upstash non configurato", str(ctx.exception))


class TestJsonbinInvariato(unittest.TestCase):
    """Le credenziali si prendono da ``config``, come prima della migrazione.

    I test le impostano sul modulo (non sull'ambiente): ``config`` viene
    importato una volta sola all'avvio del processo, quindi un ``os.environ``
    patchato a meta' esecuzione non cambierebbe piu' cio' che ``jsonbin_save``
    legge — ed e' esattamente il comportamento voluto in produzione.
    """
    def _credenziali(self, **kw):
        import config
        return mock.patch.multiple(config, JSONBIN_API_KEY="k", JSONBIN_BIN_ID="b", **kw)

    def _put(self, status=200, testo=""):
        chiamate = []

        class _R:
            status_code = status
            text = testo

        def finto(url, json=None, headers=None, timeout=None):  # noqa: A002
            chiamate.append((url, json, headers))
            return _R()
        return finto, chiamate

    def test_put_del_bin_intero_come_prima(self):
        righe = [_riga(), _riga(match_id=2, variante=MODEL_VARIANT_LEGACY)]
        put, chiamate = self._put()
        with self._credenziali():
            esito = rs.jsonbin_save(righe, put=put)
        self.assertEqual("ok", esito["remoto"])
        self.assertEqual(1, len(chiamate))
        self.assertEqual({"data": righe}, chiamate[0][1], "payload identico a prima")
        self.assertGreater(esito["byte"], 0)

    def test_403_riportato_con_il_messaggio_del_servizio(self):
        put, _ = self._put(status=403, testo='{"message":"Free users cannot update a record over 100kb"}')
        with self._credenziali():
            esito = rs.jsonbin_save([_riga()], put=put)
        self.assertEqual("errore", esito["remoto"])
        self.assertIn("100kb", esito["remoto_dettaglio"])


class TestFacciata(unittest.TestCase):
    def test_load_rows_dispatch(self):
        with mock.patch.dict(os.environ, {"REGISTRY_BACKEND": "upstash",
                                          "UPSTASH_REDIS_REST_URL": "u", "UPSTASH_REDIS_REST_TOKEN": "t"}):
            righe, fonte = rs.load_rows(post=_PostFinto({"1|top_mix||current": json.dumps(_riga())}))
        self.assertEqual(rs.BACKEND_UPSTASH, fonte)
        self.assertEqual(1, len(righe))

    def test_errore_non_strict_ricade_sul_file(self):
        with mock.patch.dict(os.environ, {"REGISTRY_BACKEND": "upstash",
                                          "UPSTASH_REDIS_REST_URL": "u", "UPSTASH_REDIS_REST_TOKEN": "t"}):
            righe, fonte = rs.load_rows(strict=False, post=_PostFinto({}, status=500))
        self.assertIsNone(righe)
        self.assertEqual("nessuno", fonte)

    def test_errore_strict_alza(self):
        with mock.patch.dict(os.environ, {"REGISTRY_BACKEND": "upstash",
                                          "UPSTASH_REDIS_REST_URL": "u", "UPSTASH_REDIS_REST_TOKEN": "t"}):
            with self.assertRaises(rs.RegistryStoreError):
                rs.load_rows(strict=True, post=_PostFinto({}, status=500))


class TestConfronto(unittest.TestCase):
    def test_identici(self):
        a = [_riga(1), _riga(2, variante=MODEL_VARIANT_LEGACY)]
        esito = rs.confronto(a, list(reversed(a)))
        self.assertTrue(esito["identici"])

    def test_differenze_elencate(self):
        a = [_riga(1), _riga(2)]
        b = [_riga(1, prob_sicuro=99.0)]
        esito = rs.confronto(a, b)
        self.assertEqual(1, len(esito["diverse"]))
        self.assertEqual([rs.field_of(_riga(2))], esito["solo_a"])
        self.assertEqual([], esito["solo_b"])
        self.assertFalse(esito["identici"])


class TestEsitoNormalizzato(unittest.TestCase):
    def test_porta_solo_i_campi_utili(self):
        esito = rs.esito_scrittura({"remoto": "ok", "backend": "upstash", "comandi": 2,
                                    "righe_scritte": 3, "righe_saltate": 1, "byte": 10,
                                    "altro": "ignorato"})
        self.assertEqual({"backend": "upstash", "remoto": "ok", "comandi": 2,
                          "righe_scritte": 3, "righe_saltate": 1, "byte": 10}, esito)
