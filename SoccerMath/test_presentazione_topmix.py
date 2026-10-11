"""Test delle funzioni PURE di presentazione della scheda TOP MIX (punti 1, 2, 3, 8, 9).

Copre, senza AppTest e senza rete:
3. Le sei traduzioni in parole della giocata, con la sigla in piccolo fra parentesi.
1. Il riquadro "Per raddoppiare": numeri identici a cerca_proposta_multipla sullo
   stesso snapshot reale; al massimo 4 righe; ritorno arrotondato all'euro.
2. "Le più probabili": al massimo una riga per partita, nessuna sotto "Paga almeno".
8. Periodo di gioco fino al lunedì: nessuna giocata proposta oltre lunedì 23:59
   (Europe/Rome) con istante venerdì 18:00 e sabato 15:00; il posticipo del lunedì
   20:45 incluso; confine del cambio ora (DST) di ottobre sul lunedì.
9. Settimana di gioco del registro tecnico: martedì-giovedì nessuna scrittura,
   venerdì scrive, un secondo calcolo nello stesso weekend non sovrascrive, il
   martedì successivo apre una settimana nuova (chiave = data del lunedì di
   chiusura). Le vecchie righe con chiave ISO restano intatte e leggibili.

I numeri non sono riscritti a mano: tutti i confronti ricavano i valori attesi
dalle funzioni esistenti (cerca_proposta_multipla, calcola_lista_giocate).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
for _p in (HERE, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lista_giocate as lg
import market_odds as mo
import snap_test

ROMA = ZoneInfo("Europe/Rome")


def _snapshot_o_skip(t):
    snap = snap_test.snapshot_reale()
    if snap is None:
        raise unittest.SkipTest("Blob dello snapshot non raggiungibile (clone shallow?)")
    return snap


class TestGiocataInParole(unittest.TestCase):
    """Punto 3: le sei giocate tradotte esattamente come da specifica."""

    def test_tutte_le_sei_giocate(self):
        casi = [
            ("1", "Vince Genoa"),
            ("X", "Pareggio"),
            ("2", "Vince Fiorentina"),
            ("1X", "Genoa non perde"),
            ("X2", "Fiorentina non perde"),
            ("12", "Non finisce in pareggio"),
        ]
        for sigla, atteso in casi:
            self.assertEqual(atteso, lg.giocata_in_parole(sigla, "Genoa", "Fiorentina"), sigla)

    def test_sigla_in_piccolo_fra_parentesi(self):
        self.assertEqual("Vince Genoa (1)",
                         lg.giocata_in_parole_con_sigla("1", "Genoa", "Fiorentina"))
        self.assertEqual("Non finisce in pareggio (12)",
                         lg.giocata_in_parole_con_sigla("12", "Genoa", "Fiorentina"))


class TestQuandoEdEtichette(unittest.TestCase):
    def test_quando_giorno_data_ora_italiana(self):
        self.assertEqual("lunedì 19/10, ore 20:45",
                         lg.quando_italiano("2026-10-19T18:45:00Z"))

    def test_riesce_e_paga_e_ritorno(self):
        self.assertEqual("47 volte su 100", lg.riesce_circa(0.4731))
        self.assertEqual("2,00 volte la puntata", lg.paga_circa(2.0))
        self.assertEqual(95, lg.ritorno_su_100(0.4731, 2.0))   # 0.4731*2*100 = 94.62 -> 95

    def test_aggiornamento_quote_parole(self):
        ven = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)  # venerdì 18:00 CEST
        self.assertEqual("Quote aggiornate oggi alle 16:56",
                         lg.aggiornamento_quote_parole("2026-10-16T14:56:54Z", ven))
        self.assertIn("non aggiornate oggi",
                      lg.aggiornamento_quote_parole("2026-10-11T14:56:54Z", ven))
        self.assertIn("ieri", lg.aggiornamento_quote_parole("2026-10-15T14:56:54Z", ven))


class TestPeriodoDiGioco(unittest.TestCase):
    """Punto 8: il confine del periodo e' lunedì 23:59:59 (Europe/Rome)."""

    # Istanti della specifica.
    VENERDI = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)   # ven 18:00 CEST
    SABATO = datetime(2026, 10, 17, 13, 0, tzinfo=timezone.utc)    # sab 15:00 CEST
    LUNEDI = datetime(2026, 10, 19, 22, 0, tzinfo=timezone.utc)    # lun 00:00 CEST+1 settimana? no: 18/10? -> vedi sotto

    def test_confine_lunedi_2359(self):
        fine = lg.lunedi_gioco(self.VENERDI)
        fine_roma = fine.astimezone(ROMA)
        self.assertEqual((2026, 10, 19, 23, 59), (fine_roma.year, fine_roma.month,
                                                  fine_roma.day, fine_roma.hour, fine_roma.minute))
        self.assertEqual(0, fine_roma.weekday())  # lunedì

    def test_nessuna_giocata_oltre_il_confine(self):
        for nome, istante in (("venerdì 18:00", self.VENERDI), ("sabato 15:00", self.SABATO)):
            with self.subTest(istante=nome):
                snap = _snapshot_o_skip(self)
                res = lg.calcola_lista_giocate(snap, adesso_utc=istante)
                in_periodo = lg.giocate_nel_periodo(res["giocate"], istante, "giornata")
                fine = lg.lunedi_gioco(istante)
                for g in in_periodo:
                    kick = lg.parse_commence_time(g["commence_time"])
                    self.assertLessEqual(kick, fine, f"{g['partita']} oltre lunedì 23:59")
                # la proposta della multipla riceve SOLO giocate del periodo (testato sopra)
                prop = lg.cerca_proposta_multipla(in_periodo)
                for item in prop["per_k"].values():
                    for g in (item or {}).get("giocate", []):
                        self.assertLessEqual(lg.parse_commence_time(g["commence_time"]), fine)

    def test_posticipo_lunedi_2045_incluso_ad_entrambi_gli_istanti(self):
        # Parma vs Torino parte lunedì 19/10 alle 20:45 italiane: dentro il confine.
        for nome, istante in (("venerdì 18:00", self.VENERDI), ("sabato 15:00", self.SABATO)):
            with self.subTest(istante=nome):
                snap = _snapshot_o_skip(self)
                res = lg.calcola_lista_giocate(snap, adesso_utc=istante)
                in_periodo = lg.giocate_nel_periodo(res["giocate"], istante, "giornata")
                posticipi = {g["partita"] for g in in_periodo
                             if lg.parse_commence_time(g["commence_time"]).astimezone(ROMA).weekday() == 0
                             and lg.parse_commence_time(g["commence_time"]).astimezone(ROMA).hour >= 20}
                self.assertTrue(posticipi, "atteso almeno un posticipo del lunedì sera")

    def test_cambio_ora_ottobre_sul_lunedi(self):
        # Il 26/10/2026 l'Italia e' tornata a CET (UTC+1): lunedì 23:59:59 romano
        # e' 22:59:59Z, non 21:59:59Z. Il confine segue l'ora itdiana, non UTC.
        ven = datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc)   # ven 23/10 18:00 CEST
        fine = lg.lunedi_gioco(ven).astimezone(timezone.utc)
        self.assertEqual(datetime(2026, 10, 26, 22, 59, 59, 999999, tzinfo=timezone.utc), fine)
        # E anche a primavera: lunedì 30/03/2026 23:59:59 CEST = 21:59:59Z.
        sab = datetime(2026, 3, 28, 14, 0, tzinfo=timezone.utc)    # sab 28/03 15:00 CET
        fine2 = lg.lunedi_gioco(sab).astimezone(timezone.utc)
        self.assertEqual(datetime(2026, 3, 30, 21, 59, 59, 999999, tzinfo=timezone.utc), fine2)

    def test_prossima_partita_quando_il_periodo_e_vuoto(self):
        # Palinsesto sottile (sosta nazionali): fra oggi e lunedì non c'e'
        # niente, ma la prossima partita in programma esiste e il messaggio la
        # cita al posto di una tabella vuota.
        mer = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
        snap = {
            "generato_il": "2026-10-21T08:00:00Z",
            "leghe": {"Serie A": {"sport_key": "soccer_italy_serie_a", "eventi": [
                {"id": "x1", "home_team": "A", "away_team": "B",
                 "commence_time": "2026-10-28T18:30:00Z",
                 "libri": [{"key": "pinnacle",
                            "h2h": {"home": 2.0, "draw": 3.3, "away": 3.9}}]},
            ]}},
        }
        res = lg.calcola_lista_giocate(snap, adesso_utc=mer)
        in_periodo = lg.giocate_nel_periodo(res["giocate"], mer, "giornata")
        self.assertEqual([], in_periodo)
        prossima = lg.prossima_partita(res["giocate"], mer)
        self.assertIsNotNone(prossima)
        self.assertEqual(datetime(2026, 10, 28, 18, 30, tzinfo=timezone.utc), prossima)
        self.assertIn("28/10", lg.quando_italiano(prossima))

    def test_provvisoria_oltre_tre_giorni(self):
        # Venerdì 18:00: le partite del lunedì 18:30+ sono oltre le 72 ore.
        g = {"commence_time": "2026-10-19T16:30:00Z"}
        self.assertTrue(lg.e_partita_provvisoria(g, self.VENERDI))
        # Sabato 15:00: la stessa partita e' DENTRO i 3 giorni — niente marca.
        self.assertFalse(lg.e_partita_provvisoria(g, self.SABATO))
        self.assertIn("quote provvisorie: possono cambiare",
                      lg.suffisso_provvisoria(g, self.VENERDI))


class TestRiquadroPerRaddoppiare(unittest.TestCase):
    """Punto 1: i numeri del riquadro sono IDENTICI a cerca_proposta_multipla."""

    def _righe_e_prop(self, istante):
        snap = _snapshot_o_skip(self)
        res = lg.calcola_lista_giocate(snap, adesso_utc=istante)
        in_periodo = lg.giocate_nel_periodo(res["giocate"], istante, "giornata")
        prop = lg.cerca_proposta_multipla(in_periodo)
        return prop, lg.righe_riquadro_raddoppio(prop["per_k"], istante)

    def test_numeri_identici_alla_ricerca(self):
        prop, righe = self._righe_e_prop(TestPeriodoDiGioco.VENERDI)
        self.assertLessEqual(len(righe), 4)
        self.assertEqual(sorted(k for k, v in prop["per_k"].items() if v),
                         [r["k"] for r in righe])
        for r in righe:
            item = prop["per_k"][r["k"]]
            self.assertEqual(f"{item['probabilita'] * 100:.0f} volte su 100", r["riesce"])
            self.assertEqual(f"{item['quota_totale']:.2f}".replace(".", ",") + " volte la puntata",
                             r["paga"])
            self.assertEqual(round(item["probabilita"] * item["quota_totale"] * 100),
                             r["ritorno_100"])
            self.assertEqual(len(item["giocate"]), len(r["partite"]))
        # esattamente una riga marcata come quella piu' probabile
        self.assertEqual(1, sum(1 for r in righe if r["migliore"]))
        k_max = max(prop["per_k"], key=lambda kk: prop["per_k"][kk]["probabilita"])
        self.assertTrue(next(r for r in righe if r["k"] == k_max)["migliore"])

    def test_anch_esso_identico_sabato(self):
        prop, righe = self._righe_e_prop(TestPeriodoDiGioco.SABATO)
        self.assertEqual(sorted(k for k, v in prop["per_k"].items() if v),
                         [r["k"] for r in righe])
        for r in righe:
            self.assertEqual(round(prop["per_k"][r["k"]]["probabilita"]
                                   * prop["per_k"][r["k"]]["quota_totale"] * 100),
                             r["ritorno_100"])

    def test_nessuna_riga_quando_non_esiste_proposta(self):
        self.assertEqual([], lg.righe_riquadro_raddoppio({}, None))


class TestPiuProbabili(unittest.TestCase):
    """Punto 2: una riga sola per partita, nessuna sotto "Paga almeno"."""

    def test_una_riga_per_partita_e_sopra_la_soglia(self):
        snap = _snapshot_o_skip(self)
        ven = TestPeriodoDiGioco.VENERDI
        res = lg.calcola_lista_giocate(snap, adesso_utc=ven)
        in_periodo = lg.giocate_nel_periodo(res["giocate"], ven, "giornata")
        for quota_min in (1.10, 1.20, 1.50, 2.00):
            with self.subTest(quota_min=quota_min):
                migliori = lg.migliori_giocate_per_partita(in_periodo, quota_min)
                partite = [g["partita"] for g in migliori]
                self.assertEqual(len(partite), len(set(partite)), "piu' di una riga per partita")
                for g in migliori:
                    self.assertGreaterEqual(g["quota_b365_stimata"], quota_min - 1e-9, partite)
                # e la riga scelta e' davvero la piu' probabile fra quelle ammesse della partita
                per_partita = {}
                for g in in_periodo:
                    if g.get("quota_b365_stimata") and g["quota_b365_stimata"] >= quota_min - 1e-9:
                        per_partita.setdefault(g["partita"], []).append(g)
                for g in migliori:
                    ammesse = per_partita[g["partita"]]
                    self.assertEqual(max(x["probabilita"] for x in ammesse), g["probabilita"])

    def test_ordine_decrescente(self):
        snap = _snapshot_o_skip(self)
        ven = TestPeriodoDiGioco.VENERDI
        res = lg.calcola_lista_giocate(snap, adesso_utc=ven)
        migliori = lg.migliori_giocate_per_partita(
            lg.giocate_nel_periodo(res["giocate"], ven, "giornata"), 1.20)
        probs = [g["probabilita"] for g in migliori]
        self.assertEqual(sorted(probs, reverse=True), probs)


class TestSettimanaDiGiocoEFinestra(unittest.TestCase):
    """Punto 9: la chiave e' la data del lunedì di chiusura; la scrittura solo
    fra venerdì 00:00 e lunedì 23:59 (Europe/Rome)."""

    def test_chiave_data_del_lunedi_di_chiusura(self):
        ven = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)
        self.assertEqual("2026-10-19", lg.settimana_gioco(ven))
        lun = datetime(2026, 10, 19, 21, 30, tzinfo=timezone.utc)  # lun 19/10 23:30 CEST
        self.assertEqual("2026-10-19", lg.settimana_gioco(lun))
        mezzanotte = datetime(2026, 10, 19, 22, 0, tzinfo=timezone.utc)  # mar 20/10 00:00 CEST: settimana nuova
        self.assertEqual("2026-10-26", lg.settimana_gioco(mezzanotte))
        self.assertEqual("2026-10-26", lg.settimana_gioco(datetime(2026, 10, 26, 21, 0, tzinfo=timezone.utc)))

    def test_finestra_giorni(self):
        casi = [
            (datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc), False),  # giovedì
            (datetime(2026, 10, 16, 0, 0, tzinfo=timezone.utc), True),    # venerdì ore 02:00 CEST
            (datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc), True),   # sabato
            (datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc), True),   # domenica
            (datetime(2026, 10, 19, 21, 30, tzinfo=timezone.utc), True),  # lunedì 23:30 CEST
            (datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc), False),   # martedì
            (datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc), False),   # mercoledì
        ]
        for istante, atteso in casi:
            self.assertEqual(atteso, lg.in_finestra_registrazione_multipla(istante), istante)

    def _storage_finto(self):
        storage = []

        def fake_load(*args, **kwargs):
            return list(storage), "upstash"

        def fake_save(rows, *args, **kwargs):
            storage.clear()
            storage.extend(rows)
            return {"remoto": "ok", "backend": "upstash", "righe_scritte": len(rows)}

        return storage, fake_load, fake_save

    def _proposta_finta(self, partita="A vs B", p=0.45, q=2.20):
        return {
            "probabilita": p, "quota_totale": q, "ev": p * q - 1.0,
            "giocate": [{"partita": partita, "lega": "Serie A", "giocata": "1",
                         "probabilita": p, "quota_b365_stimata": q}],
        }

    def test_giovedi_non_scrive_venerdi_scrive_sabato_non_sovrascrive_martedi_nuova_settimana(self):
        storage, fake_load, fake_save = self._storage_finto()
        gio = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
        ven = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)
        sab = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)
        mar = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
        ven2 = datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc)

        with mock.patch("registry_store.load_ombra_rows", side_effect=fake_load), \
             mock.patch("registry_store.save_ombra_rows", side_effect=fake_save):
            # martedì e giovedì: nessuna scrittura
            es = lg.salva_proposta_multipla_registro_ombra(self._proposta_finta(),
                                                           istante_utc=gio, k=1)
            self.assertEqual("fuori_finestra", es.get("remoto"))
            self.assertEqual(0, len(storage))

            # venerdì: scrive con la chiave del lunedì di chiusura
            es = lg.salva_proposta_multipla_registro_ombra(self._proposta_finta(),
                                                           istante_utc=ven, k=1)
            self.assertEqual("ok", es.get("remoto"))
            self.assertEqual(1, len(storage))
            self.assertEqual("multipla_2026-10-19_k1", storage[0]["match_id"])
            self.assertEqual("2026-10-19", storage[0]["settimana"])
            self.assertEqual(45.0, storage[0]["prob_sicuro"])

            # sabato, proposta diversa, stesso weekend: NON sovrascrive
            es = lg.salva_proposta_multipla_registro_ombra(
                self._proposta_finta("C vs D", 0.50, 2.10), istante_utc=sab, k=1)
            self.assertEqual("gia_registrata_settimana", es.get("remoto"))
            self.assertEqual(1, len(storage))
            self.assertEqual(45.0, storage[0]["prob_sicuro"])

            # il martedì successivo: fuori finestra, niente scritture
            es = lg.salva_proposta_multipla_registro_ombra(
                self._proposta_finta("E vs F", 0.44, 2.30), istante_utc=mar, k=1)
            self.assertEqual("fuori_finestra", es.get("remoto"))
            self.assertEqual(1, len(storage))

            # il venerdì successivo: settimana nuova, chiave nuova
            es = lg.salva_proposta_multipla_registro_ombra(
                self._proposta_finta("E vs F", 0.44, 2.30), istante_utc=ven2, k=1)
            self.assertEqual("ok", es.get("remoto"))
            self.assertEqual(2, len(storage))
            chiavi = {r["match_id"] for r in storage}
            self.assertEqual({"multipla_2026-10-19_k1", "multipla_2026-10-26_k1"}, chiavi)

    def test_righe_iso_vecchie_restono_leggibili_e_non_bloccano(self):
        """Le righe scritte con la chiave ISO ("2026-W42") restano intatte: la
        chiave nuova non coincide MAI con quella esatta (formati diversi), quindi
        alla prima scrittura del nuovo formato le vecchie restano leggibili in
        coda e non vengono ne' scartate ne' sovrascritte."""
        storage, fake_load, fake_save = self._storage_finto()
        # Precarico una riga del vecchio formato ISO (stesso k), inalterabile.
        storage.append({
            "match_id": "multipla_2026-W42_k1", "ombra_famiglia": lg.FAMIGLIA_OMBRA_MULTIPLA_PROPOSTA,
            "settimana": "2026-W42", "k": 1, "prob_sicuro": 48.0, "top3": ["Vecchia (1)"],
        })
        n_iso_prima = sum(1 for r in storage if "-W" in str(r.get("settimana", "")))
        self.assertEqual(1, n_iso_prima)   # conteggio delle righe ISO esistenti (punto 9)
        ven = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)
        with mock.patch("registry_store.load_ombra_rows", side_effect=fake_load), \
             mock.patch("registry_store.save_ombra_rows", side_effect=fake_save):
            es = lg.salva_proposta_multipla_registro_ombra(self._proposta_finta(),
                                                           istante_utc=ven, k=1)
            # La riga ISO non conta come "gia' registrata": chiave diversa.
            self.assertEqual("ok", es.get("remoto"))
        self.assertEqual(2, len(storage))
        # Lettura post-cambio: entrambe le righe ci sono ancora, la ISO invariata.
        iso = [r for r in storage if r["settimana"] == "2026-W42"]
        self.assertEqual(1, len(iso))
        self.assertEqual(48.0, iso[0]["prob_sicuro"])
        self.assertEqual("multipla_2026-W42_k1", iso[0]["match_id"])

    def test_salva_tutte_fuori_finestra_non_scrive_nulla(self):
        storage, fake_load, fake_save = self._storage_finto()
        mer = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
        with mock.patch("registry_store.load_ombra_rows", side_effect=fake_load), \
             mock.patch("registry_store.save_ombra_rows", side_effect=fake_save):
            es = lg.salva_tutte_proposte_k_registro_ombra({1: self._proposta_finta()},
                                                          istante_utc=mer)
        self.assertEqual("fuori_finestra", es.get("remoto"))
        self.assertEqual(0, len(storage))


# ---------------------------------------------------------------------------
# «Prova la tua giocata»: hint, confronto, titoli, esito (punto 3, rifinitura)
# ---------------------------------------------------------------------------

def _gamba(match_id=1, giocata="1", prob=0.60, quota=1.70):
    """Una gamba come la produce ``calcola_lista_giocate``: la probabilita'
    vive nel campo ``probabilita`` (0..1), la stima in ``quota_b365_stimata``."""
    return {"match_id": match_id, "partita": "Inter vs Roma", "home": "Inter",
            "away": "Roma", "giocata": giocata, "probabilita": prob,
            "quota_b365_stimata": quota,
            "commence_time": "2026-10-17T18:00:00Z", "lega": "Serie A"}


class TestProvaLaTuaGiocataPure(unittest.TestCase):
    """Gli aiutanti puri del riquadro: nessun numero cambia, si decide solo
    da dove arriva la quota di ogni gamba e come lo si dice."""

    def test_e_doppia_chance(self):
        self.assertFalse(lg.e_doppia_chance("1"))
        self.assertFalse(lg.e_doppia_chance("2"))
        self.assertFalse(lg.e_doppia_chance("X"))
        for dc in ("1X", "X2", "12"):
            self.assertTrue(lg.e_doppia_chance(dc))

    def test_identificativo_giocata(self):
        self.assertEqual("1|1", lg.identificativo_giocata(_gamba(1, "1")))
        self.assertNotEqual(lg.identificativo_giocata(_gamba(1, "1")),
                            lg.identificativo_giocata(_gamba(1, "X")))
        self.assertNotEqual(lg.identificativo_giocata(_gamba(1, "1")),
                            lg.identificativo_giocata(_gamba(2, "1")))

    def test_quota_stimata_e_hint(self):
        g = _gamba(giocata="1", quota=2.00)
        self.assertAlmostEqual(2.00, lg.quota_stimata_giocata(g), places=12)
        self.assertEqual("L'app si aspetta circa 2,00", lg.hint_quota_stimata(g))
        # doppia chance: "stima meno precisa" (le doppie sul sito del
        # bookmaker possono arrotondare in modo diverso)
        self.assertEqual("L'app si aspetta circa 2,00 (stima meno precisa)",
                         lg.hint_quota_stimata(_gamba(giocata="1X", quota=2.00)))
        # quota mancante: niente numero inventato
        self.assertEqual("L'app non ha una stima per questa giocata.",
                         lg.hint_quota_stimata(_gamba(quota=None)))

    def test_confronto_quota_bet365(self):
        self.assertEqual("bet365 paga come previsto", lg.confronto_quota_bet365(2.00, 2.00))
        # tolleranza +-0,02
        self.assertEqual("bet365 paga come previsto", lg.confronto_quota_bet365(2.01, 2.00))
        self.assertEqual("bet365 paga come previsto", lg.confronto_quota_bet365(1.99, 2.00))
        self.assertEqual("bet365 paga più del previsto", lg.confronto_quota_bet365(2.03, 2.00))
        self.assertEqual("bet365 paga meno del previsto", lg.confronto_quota_bet365(1.97, 2.00))

    def test_titolo_nei_tre_casi(self):
        self.assertEqual("Con le quote previste dall'app",
                         lg.titolo_risultato_giocata(0, 3))
        self.assertEqual("Con le quote di bet365", lg.titolo_risultato_giocata(3, 3))
        self.assertEqual("Con 1 quote di bet365 e 2 previste dall'app",
                         lg.titolo_risultato_giocata(1, 3))

    def test_esito_tutte_vuote_usa_le_stime(self):
        gambe = [_gamba(1, "1", 0.60, 1.70), _gamba(2, "2", 0.55, 2.00)]
        es = lg.esito_prova_giocata(gambe, [None, None])
        self.assertEqual(0, es["n_compilate"])
        self.assertAlmostEqual(0.60 * 0.55, es["probabilita"], places=12)
        self.assertAlmostEqual(1.70 * 2.00, es["quota_totale"], places=12)
        self.assertEqual(round(100.0 * 0.60 * 0.55 * 1.70 * 2.00), es["ritorno_100"])
        self.assertEqual("Con le quote previste dall'app", es["titolo"])
        # la "trattenuta" del libro e' 100 - ritorno, solo se positiva
        self.assertEqual(max(0, 100 - es["ritorno_100"]), es["trattenuta_su_100"])

    def test_esito_riempire_una_casella_cambia_solo_quella_gamba(self):
        gambe = [_gamba(1, "1", 0.60, 1.70), _gamba(2, "2", 0.55, 2.00)]
        prima = lg.esito_prova_giocata(gambe, [None, None])
        dopo = lg.esito_prova_giocata(gambe, [1.90, None])
        # la probabilita' non si muove MAI: cambia solo quanto paga
        self.assertAlmostEqual(prima["probabilita"], dopo["probabilita"], places=12)
        self.assertAlmostEqual(1.90 * 2.00, dopo["quota_totale"], places=12)
        self.assertEqual(1, dopo["n_compilate"])
        self.assertEqual("Con 1 quote di bet365 e 1 previste dall'app", dopo["titolo"])
        # ritorno coerente con la nuova quota totale
        self.assertEqual(round(100.0 * 0.60 * 0.55 * 1.90 * 2.00), dopo["ritorno_100"])

    def test_esito_tutte_compilate(self):
        gambe = [_gamba(1, "1", 0.60, 1.70), _gamba(2, "2", 0.55, 2.00)]
        es = lg.esito_prova_giocata(gambe, [1.90, 2.10])
        self.assertEqual(2, es["n_compilate"])
        self.assertAlmostEqual(1.90 * 2.10, es["quota_totale"], places=12)
        self.assertEqual("Con le quote di bet365", es["titolo"])

    def test_esito_una_sola_gamba(self):
        es = lg.esito_prova_giocata([_gamba(1, "1", 0.62, 1.61)], [None])
        self.assertAlmostEqual(0.62, es["probabilita"], places=12)
        self.assertAlmostEqual(1.61, es["quota_totale"], places=12)

    def test_esito_quota_non_usabile_non_inventa(self):
        # casella compilata con un valore impossibile (<= 1.00): la stima
        # dell'app NON la sostituisce in silenzio, il totale resta n/d.
        es = lg.esito_prova_giocata([_gamba(1, "1", 0.60, None)], [0.50])
        self.assertEqual(0.0, es["quota_totale"])
        self.assertEqual("n/d", es["paga"])
        self.assertIsNone(es["trattenuta_su_100"])


class TestRigheMercatoNelPeriodo(unittest.TestCase):
    """Punto 5a: la tabella in parole del mercato segue lo stesso «Periodo»."""

    LUN = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)  # venerdì

    def _riga(self, kickoff):
        return {"home": "A", "away": "B", "kickoff_utc": kickoff,
                "utcDate": kickoff, "prob": 0.6}

    def test_dentro_la_giornata(self):
        righe = [self._riga("2026-10-17T18:00:00Z"),
                 self._riga("2026-10-19T21:00:00Z")]  # entro lunedì 23:59
        in_p = lg.righe_mercato_nel_periodo(righe, self.LUN, "giornata")
        self.assertEqual(2, len(in_p))

    def test_oltre_il_lunedi_fuori(self):
        righe = [self._riga("2026-10-20T21:00:00Z")]  # martedì
        self.assertEqual([], lg.righe_mercato_nel_periodo(righe, self.LUN, "giornata"))
        self.assertEqual(1, len(lg.righe_mercato_nel_periodo(righe, self.LUN, "tutte")))

    def test_gia_iniziata_fuori_sempre(self):
        righe = [self._riga("2026-10-16T10:00:00Z")]  # prima dell'istante
        self.assertEqual([], lg.righe_mercato_nel_periodo(righe, self.LUN, "giornata"))
        self.assertEqual([], lg.righe_mercato_nel_periodo(righe, self.LUN, "tutte"))

    def test_senza_kickoff_fuori_sempre(self):
        righe = [{"home": "A", "away": "B"}]
        self.assertEqual([], lg.righe_mercato_nel_periodo(righe, self.LUN, "giornata"))


if __name__ == "__main__":
    unittest.main()
