"""Pulizia mirata del Registro: seleziona SOLO le origini richieste, e mai il Top Mix.

Nessuna rete: si prova ``seleziona()`` e ``campi_grezzi()`` con un finto HGETALL,
piu' le guardie del percorso di scrittura (``--scrivi`` senza ``--conferma``,
numero atteso diverso, backend JSONBin) eseguendo ``main()`` con le letture
sostituite. La scrittura vera e' provata con un finto ``upstash_raw`` che
registra i comandi: si verifica che sia **un solo HDEL** e che contenga
esattamente i campi giusti.
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

import registry_pulizia as RP  # noqa: E402
import registry_store as rs  # noqa: E402


def _riga(mid, origine, *, data="05/09/2026 18:00", variante=None):
    r = {"match_id": mid, "home": "Casa", "away": "Ospite", "campionato": "Serie A",
         "giornata": 1, "data": data, "pronostico_sicuro": "1 - x", "mercato_standard": "1",
         "prob_sicuro": 60.0, "esito": "⏳", "origin": origine,
         "model_version": "post_shrinkage_v1", "salvato_il": data}
    if variante:
        r["model_variant"] = variante
    return r


class TestSelezione(unittest.TestCase):
    def setUp(self):
        self.campi = {
            "1|top_mix||current": ("t", _riga(1, "top_mix", variante="current")),
            "2|top_mix||legacy": ("t", _riga(2, "top_mix", variante="legacy")),
            "3|analisi_rapida||current": ("t", _riga(3, "analisi_rapida")),
            "4|analisi_rapida||current": ("t", _riga(4, "analisi_rapida", data="24/08/2026 20:45")),
            "5|billy||current": ("t", _riga(5, "billy")),
        }

    def test_seleziona_solo_l_origine_richiesta(self):
        da_cancellare, problemi, _non = RP.seleziona(self.campi, ("analisi_rapida",))
        self.assertEqual([], problemi)
        self.assertEqual(["3|analisi_rapida||current", "4|analisi_rapida||current"], da_cancellare)

    def test_non_tocca_mai_le_righe_top_mix(self):
        da_cancellare, _p, _n = RP.seleziona(self.campi, ("top_mix", "analisi_rapida"))
        self.assertNotIn("1|top_mix||current", da_cancellare)

    def test_origine_top_mix_richiesta_e_un_problema_non_una_cancellazione(self):
        _da_cancellare, problemi, _n = RP.seleziona(self.campi, ("top_mix",))
        self.assertTrue(problemi)
        self.assertIn("top_mix", problemi[0])

    def test_origine_non_leggibile_non_si_cancella_e_si_dichiara(self):
        riga = _riga(9, "")
        riga.pop("origin")
        campi = {"9|||current": ("t", riga)}
        da_cancellare, _p, non_attribuibili = RP.seleziona(campi, ("analisi_rapida",))
        self.assertEqual([], da_cancellare)
        self.assertEqual(["9|||current"], non_attribuibili,
                         "una riga non attribuibile non si cancella in silenzio")

    def test_billy_non_viene_toccato_da_una_pulizia_di_analisi_rapida(self):
        da_cancellare, _p, _n = RP.seleziona(self.campi, ("analisi_rapida",))
        self.assertNotIn("5|billy||current", da_cancellare)


class TestPercorsoDiScrittura(unittest.TestCase):
    """main() con letture finte: la scrittura e' UN solo HDEL, e solo se confermata."""

    def setUp(self):
        self.campi = {
            "3|analisi_rapida||current": ("t", _riga(3, "analisi_rapida")),
            "4|analisi_rapida||current": ("t", _riga(4, "analisi_rapida", data="24/08/2026 20:45")),
            "1|top_mix||current": ("t", _riga(1, "top_mix")),
        }
        self.comandi = []

        def _finto_raw(comando, *, post=None):
            self.comandi.append(comando)
            if comando[0] == "HDEL":
                # il finto hash si aggiorna come quello vero: i campi spariscono
                for campo in comando[2:]:
                    self.campi.pop(campo, None)
                return {"result": len(comando) - 2}
            raise AssertionError(f"comando inatteso: {comando[0]}")

        self.patches = [
            mock.patch.object(RP, "campi_grezzi", side_effect=lambda **kw: dict(self.campi)),
            mock.patch.object(rs, "upstash_rows", return_value=[r for _t, r in self.campi.values()]),
            mock.patch.object(rs, "backend", return_value=rs.BACKEND_UPSTASH),
            mock.patch.object(rs, "upstash_snapshot",
                              return_value={"chiave": "sm:registro:snapshot:giorno-pre-pulizia",
                                            "righe": 3, "byte": 100}),
            mock.patch.object(rs, "upstash_raw", side_effect=_finto_raw),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def test_prova_non_scrive_nulla(self):
        self.assertEqual(0, RP.main(["--origini", "analisi_rapida"]))
        self.assertEqual([], self.comandi)

    def test_scrivi_senza_conferma_non_scrive(self):
        self.assertEqual(3, RP.main(["--origini", "analisi_rapida", "--scrivi"]))
        self.assertEqual([], self.comandi)

    def test_attesi_diverso_ferma_tutto(self):
        self.assertEqual(3, RP.main(["--origini", "analisi_rapida", "--scrivi", "--conferma",
                                     "--attesi", "26"]))
        self.assertEqual([], self.comandi)

    def test_un_solo_hdel_con_i_campi_giusti(self):
        rc = RP.main(["--origini", "analisi_rapida", "--scrivi", "--conferma", "--attesi", "2"])
        self.assertEqual(0, rc)
        self.assertEqual(1, len(self.comandi), "un solo comando: niente mezze pulizie")
        comando = self.comandi[0]
        self.assertEqual("HDEL", comando[0])
        self.assertEqual(rs.hash_key(), comando[1])
        self.assertEqual(["3|analisi_rapida||current", "4|analisi_rapida||current"],
                         comando[2:])
        self.assertNotIn("1|top_mix||current", comando[2:])

    def test_istantanea_prima_della_cancellazione(self):
        with mock.patch.object(rs, "upstash_snapshot") as snap:
            snap.return_value = {"chiave": "k", "righe": 3, "byte": 1}
            RP.main(["--origini", "analisi_rapida", "--scrivi", "--conferma"])
        snap.assert_called_once()
        self.assertTrue(str(snap.call_args[0][0]).endswith("-pre-pulizia"))


class TestRigaTecnica(unittest.TestCase):
    """Il nome scritto e il nome ricalcolato: se non coincidono, la stessa riga
    vive nell'hash sotto DUE nomi e cancellarne uno lascerebbe l'altra."""

    def test_nome_vecchio_dichiarato(self):
        riga = _riga(540706, "analisi_rapida", data="16/05/2026 15:30", variante="current")
        riga.pop("origin")   # riga scritta prima del campo origin
        riga["model_version"] = ""
        testo = RP.riga_tecnica("540706|analisi_rapida||current", "t", riga)
        self.assertIn("origine scritta: assente", testo)
        self.assertIn("origine letta: unknown", testo)
        self.assertIn("testo del pronostico: '1 - x'", testo)

    def test_nome_allineato_dichiarato(self):
        riga = _riga(1, "top_mix", variante="current")
        campo = "|".join("" if p is None else str(p) for p in RP.dedup_key(riga))
        testo = RP.riga_tecnica(campo, "t", riga)
        self.assertIn("allineato a", testo)
        self.assertIn("si |", testo)
        self.assertNotIn("NO (nome vecchio)", testo)


class TestGuardie(unittest.TestCase):
    def test_backend_jsonbin_non_si_pulisce(self):
        with mock.patch.object(rs, "backend", return_value=rs.BACKEND_JSONBIN):
            self.assertEqual(2, RP.main(["--origini", "analisi_rapida", "--scrivi", "--conferma"]))

    def test_origini_vuote(self):
        with mock.patch.object(rs, "backend", return_value=rs.BACKEND_UPSTASH):
            self.assertEqual(2, RP.main(["--origini", " , "]))


if __name__ == "__main__":
    unittest.main()
