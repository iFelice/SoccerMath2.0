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
            if comando[0] == "SET":
                return {"result": "OK"}
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

    def test_attesi_righe_diverso_ferma_tutto(self):
        # 2 campi selezionati, ma sono 2 nomi della STESSA riga logica: chiedere
        # 26 righe logiche deve fermare tutto prima di scrivere.
        self.assertEqual(3, RP.main(["--origini", "analisi_rapida", "--scrivi", "--conferma",
                                     "--attesi-righe", "26"]))
        self.assertEqual([], self.comandi)

    def test_un_solo_hdel_con_i_campi_giusti(self):
        rc = RP.main(["--origini", "analisi_rapida", "--scrivi", "--conferma", "--attesi", "2"])
        self.assertEqual(0, rc)
        hdel = [c for c in self.comandi if c[0] == "HDEL"]
        self.assertEqual(1, len(hdel), "un solo HDEL: niente mezze pulizie")
        comando = hdel[0]
        self.assertEqual("HDEL", comando[0])
        self.assertEqual(rs.hash_key(), comando[1])
        self.assertEqual(["3|analisi_rapida||current", "4|analisi_rapida||current"],
                         comando[2:])
        self.assertNotIn("1|top_mix||current", comando[2:])

    def test_istantanea_esatta_dei_campi_prima_della_cancellazione(self):
        """Oltre all'istantanea delle righe logiche serve quella dei CAMPI scritti:
        e' l'unica che permette di rimettere anche i nomi vecchi."""
        RP.main(["--origini", "analisi_rapida", "--scrivi", "--conferma"])
        hdel_idx = [i for i, c in enumerate(self.comandi) if c[0] == "HDEL"][0]
        set_campi = [c for c in self.comandi[:hdel_idx] if c[0] == "SET"]
        self.assertEqual(1, len(set_campi), "una sola istantanea esatta, prima dell'HDEL")
        self.assertTrue(str(set_campi[0][1]).endswith("-pre-pulizia-campi"))
        import json as _json
        salvati = _json.loads(set_campi[0][2])
        self.assertIn("3|analisi_rapida||current", salvati)

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


class TestCampiEspliciti(unittest.TestCase):
    """Una riga non attribuibile a nessuna origine: si cancella solo se la si
    indica a mano, e il Top Mix resta comunque intoccabile."""

    def setUp(self):
        self.riga_ignota = _riga(558625, "")
        self.riga_ignota.pop("origin")
        self.campi = {
            "558625|unknown||current": ("t", self.riga_ignota),
            "558625|unknown||legacy": ("t", dict(self.riga_ignota)),
            "1|top_mix||current": ("t", _riga(1, "top_mix")),
        }

    def test_seleziona_solo_i_campi_indicati(self):
        da_cancellare, problemi = RP.seleziona_campi_espliciti(
            self.campi, ["558625|unknown||current", "558625|unknown||legacy"])
        self.assertEqual([], problemi)
        self.assertEqual(["558625|unknown||current", "558625|unknown||legacy"], da_cancellare)

    def test_campo_inesistente_ferma_tutto(self):
        da_cancellare, problemi = RP.seleziona_campi_espliciti(self.campi, ["non|esiste"])
        self.assertEqual([], da_cancellare)
        self.assertTrue(problemi)

    def test_campo_top_mix_non_si_cancella_nemmeno_a_mano(self):
        da_cancellare, problemi = RP.seleziona_campi_espliciti(self.campi, ["1|top_mix||current"])
        self.assertEqual([], da_cancellare)
        self.assertIn("Top Mix", problemi[0])

    def test_la_selezione_per_origine_non_pesca_mai_gli_unknown(self):
        da_cancellare, problemi, non_attribuibili = RP.seleziona(self.campi, ("analisi_rapida",))
        self.assertEqual([], da_cancellare)
        self.assertEqual([], problemi)
        self.assertEqual(["558625|unknown||current", "558625|unknown||legacy"], non_attribuibili)


class TestSenzaOrigine(unittest.TestCase):
    """La classe 'senza riferimento' si toglie solo con il flag E i conteggi."""

    def setUp(self):
        ignota = _riga(558625, "")
        ignota.pop("origin")
        self.campi = {
            "558625|unknown||current": ("t", ignota),
            "558625|unknown||legacy": ("t", dict(ignota)),
            "1|top_mix||current": ("t", _riga(1, "top_mix")),
            "3|analisi_rapida||legacy": ("t", _riga(3, "analisi_rapida")),
        }
        self.comandi = []

        def _finto_raw(comando, *, post=None):
            self.comandi.append(comando)
            if comando[0] == "SET":
                return {"result": "OK"}
            if comando[0] == "HDEL":
                for campo in comando[2:]:
                    self.campi.pop(campo, None)
                return {"result": len(comando) - 2}
            raise AssertionError(comando[0])

        self.patches = [
            mock.patch.object(RP, "campi_grezzi", side_effect=lambda **kw: dict(self.campi)),
            mock.patch.object(rs, "upstash_rows", return_value=[r for _t, r in self.campi.values()]),
            mock.patch.object(rs, "backend", return_value=rs.BACKEND_UPSTASH),
            mock.patch.object(rs, "upstash_snapshot",
                              return_value={"chiave": "sm:registro:snapshot:x-pre-pulizia",
                                            "righe": 4, "byte": 10}),
            mock.patch.object(rs, "upstash_raw", side_effect=_finto_raw),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def test_senza_il_flag_le_righe_senza_origine_non_si_toccano(self):
        RP.main(["--origini", "analisi_rapida", "--scrivi", "--conferma"])
        for comando in self.comandi:
            if comando[0] == "HDEL":
                self.assertNotIn("558625|unknown||current", comando[2:])

    def test_flag_senza_attesi_non_scrive(self):
        self.assertEqual(3, RP.main(["--senza-origine", "--scrivi", "--conferma"]))
        self.assertEqual([], [c for c in self.comandi if c[0] == "HDEL"])

    def test_flag_con_attesi_giusti_cancella_solo_quelle(self):
        rc = RP.main(["--senza-origine", "--scrivi", "--conferma",
                      "--attesi", "2", "--attesi-righe", "1"])
        self.assertEqual(0, rc)
        hdel = [c for c in self.comandi if c[0] == "HDEL"]
        self.assertEqual(1, len(hdel))
        self.assertEqual(["558625|unknown||current", "558625|unknown||legacy"], hdel[0][2:])

    def test_attesi_sbagliato_non_scrive(self):
        self.assertEqual(3, RP.main(["--senza-origine", "--scrivi", "--conferma", "--attesi", "26"]))
        self.assertEqual([], [c for c in self.comandi if c[0] == "HDEL"])


class TestRigaCompatta(unittest.TestCase):
    """Il referto corto deve restare corto: sta nelle annotazioni di CI."""

    def test_corta_e_leggibile(self):
        riga = _riga(558633, "analisi_rapida")
        riga.pop("origin")
        riga["pronostico_sicuro"] = "Vittoria Atalanta - 63% - analisi automatica Poisson"
        testo = RP.riga_compatta("558633|analisi_rapida||legacy", riga)
        self.assertLessEqual(len(testo), 170, "una riga = un campo, in un referto corto")
        self.assertIn("id 558633", testo)
        self.assertIn("Casa - Ospite", testo)
        self.assertIn("scritta: assente", testo)
        self.assertIn("letta: analisi_rapida", testo)
        self.assertIn("Vittoria Atalanta", testo)


class TestGuardie(unittest.TestCase):
    def test_backend_jsonbin_non_si_pulisce(self):
        with mock.patch.object(rs, "backend", return_value=rs.BACKEND_JSONBIN):
            self.assertEqual(2, RP.main(["--origini", "analisi_rapida", "--scrivi", "--conferma"]))

    def test_origini_vuote(self):
        with mock.patch.object(rs, "backend", return_value=rs.BACKEND_UPSTASH):
            self.assertEqual(2, RP.main(["--origini", " , "]))


if __name__ == "__main__":
    unittest.main()
