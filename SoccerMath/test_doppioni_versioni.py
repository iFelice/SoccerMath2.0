"""Doppioni fra versioni del selettore Top Mix (round 2, punto 3).

Una stessa partita, con lo stesso mercato e la stessa tabella/modello, puo' avere una
riga scritta dalla versione precedente del selettore (v1) e una riga della versione in
prova (v2). Regole fissate qui:

* VISTA (statistiche e tabella): una sola riga per (tabella/modello, match_id, mercato),
  la piu' recente per ``salvato_il`` (non per posizione nella lista). Nessuna riga del
  Registro viene cancellata o riscritta: la deduplica filtra solo la vista.
* SCRITTURA (click e replay --write): una riga Top Mix NUOVA non si aggiunge se esiste
  gia' una riga della stessa (tabella/modello, match_id, mercato) di QUALUNQUE versione.
* Analisi Rapida e Billy non entrano in nessuna delle due regole; l'ombra ha il suo registro.
"""
from __future__ import annotations

import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import prediction_registry as pr  # noqa: E402
from prediction_registry import (  # noqa: E402
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_LEGACY,
    ORIGIN_ANALISI_RAPIDA,
    ORIGIN_TOP_MIX,
    ORIGIN_TOP_MIX_OMBRA,
    SELECTOR_VERSION_MODELLO_1X2,
    SELECTOR_VERSION_PRE_1X2,
    chiave_tabella_mercato,
    compute_calibration_stats,
    compute_stats,
    dedup_key,
    righe_visibili,
    upsert_prediction_entries,
    upsert_prediction_entry,
)

V1 = SELECTOR_VERSION_PRE_1X2         # "topmix_gate025_ens06_v1"
# La regola dei doppioni fra versioni vale DENTRO la stessa famiglia di
# selettore: v1 e v2 sono due versioni del selettore del MODELLO. v3 e' un
# selettore DIVERSO (quello del mercato): la sua coesistenza con le righe del
# modello e' verificata in test_topmix_mercato.py.
V2 = SELECTOR_VERSION_MODELLO_1X2     # "topmix_1x2_gate025_ens06_v2"


def riga(match_id=1, versione=V1, variante=MODEL_VARIANT_CURRENT, mercato="1", prob=64.5,
         salvato_il="15/09/2026 17:18", origin=ORIGIN_TOP_MIX, esito=None, **extra):
    e = {"match_id": match_id, "origin": origin, "selector_version": versione,
         "model_variant": variante, "mercato_standard": mercato, "prob_sicuro": prob,
         "salvato_il": salvato_il, "campionato": "Serie A", "home": "Milan", "away": "Lecce",
         "kickoff_utc": "2026-09-20T18:45:00Z", "data": "20/09/2026"}
    if esito is not None:
        e["esito"] = esito
    e.update(extra)
    return e


class TestVistaUnaRigaPerTabellaPartitaMercato(unittest.TestCase):
    def test_v1_e_v2_stessa_scelta_mostrano_una_riga_la_piu_recente(self):
        entries = [riga(versione=V1, prob=64.5, salvato_il="10/09/2026 20:00"),
                   riga(versione=V2, prob=71.6, salvato_il="20/10/2026 10:00")]
        visibili = righe_visibili(entries)
        self.assertEqual(1, len(visibili))
        self.assertEqual(71.6, visibili[0]["prob_sicuro"])
        self.assertEqual(V2, visibili[0]["selector_version"])

    def test_la_piu_recente_vince_per_orario_non_per_posizione(self):
        """La riga piu' recente sta PRIMA nella lista: vince comunque lei."""
        entries = [riga(versione=V2, prob=71.6, salvato_il="20/10/2026 10:00"),
                   riga(versione=V1, prob=64.5, salvato_il="10/09/2026 20:00")]
        visibili = righe_visibili(entries)
        self.assertEqual([71.6], [e["prob_sicuro"] for e in visibili])

    def test_nessuna_riga_del_registro_viene_cancellata_ne_riscritta(self):
        entries = [riga(versione=V1, salvato_il="10/09/2026 20:00"),
                   riga(versione=V2, prob=71.6, salvato_il="20/10/2026 10:00")]
        prima = copy.deepcopy(entries)
        righe_visibili(entries)
        compute_stats(entries)
        compute_calibration_stats(entries)
        self.assertEqual(prima, entries)

    def test_mercati_diversi_restano_entrambi(self):
        entries = [riga(versione=V1, mercato="Over 2.5", prob=64.0),
                   riga(versione=V2, mercato="1", prob=71.6)]
        self.assertEqual(2, len(righe_visibili(entries)))

    def test_tabelle_diverse_restano_entrambe(self):
        entries = [riga(versione=V1, variante=MODEL_VARIANT_LEGACY, prob=64.5),
                   riga(versione=V2, variante=MODEL_VARIANT_CURRENT, prob=71.6)]
        self.assertEqual(2, len(righe_visibili(entries)))

    def test_analisi_rapida_non_si_tocca(self):
        """Due righe Analisi Rapida della stessa scelta restano entrambe: la tabella non cambia."""
        entries = [riga(origin=ORIGIN_ANALISI_RAPIDA, versione="analisi_v1", salvato_il="10/09/2026 20:00"),
                   riga(origin=ORIGIN_ANALISI_RAPIDA, versione="analisi_v1", salvato_il="20/10/2026 10:00")]
        self.assertEqual(2, len(righe_visibili(entries)))

    def test_ombra_resta_fuori_dalla_vista(self):
        entries = [riga(origin=ORIGIN_TOP_MIX_OMBRA, versione="topmix_ombra_ou25_v1", ombra=True,
                        ombra_mercato="Over 2.5")]
        self.assertEqual([], righe_visibili(entries))


class TestStatisticheSenzaDoppioni(unittest.TestCase):
    def test_compute_stats_conta_la_scelta_una_volta_sola(self):
        entries = [riga(versione=V1, prob=64.5, salvato_il="10/09/2026 20:00", esito="✅"),
                   riga(versione=V2, prob=71.6, salvato_il="20/10/2026 10:00", esito="❌")]
        st = compute_stats(entries)
        self.assertEqual(1, st["total"])
        self.assertEqual((0, 1), (st["wins"], st["losses"]))   # vince la v2 (la piu' recente)

    def test_calibrazione_non_conta_il_doppione(self):
        entries = [riga(versione=V1, prob=64.5, salvato_il="10/09/2026 20:00", esito="✅"),
                   riga(versione=V2, prob=71.6, salvato_il="20/10/2026 10:00", esito="✅")]
        self.assertEqual(1, compute_calibration_stats(entries)["total"])


class TestScritturaClick(unittest.TestCase):
    """Percorso del click: ``upsert_prediction_entry`` (usato da ``save_prediction_entry``)."""

    def test_v2_non_si_aggiunge_accanto_alla_v1_della_stessa_scelta(self):
        esistenti = [riga(versione=V1, prob=64.5)]
        prima = copy.deepcopy(esistenti)
        lista, azione = upsert_prediction_entry(esistenti, riga(versione=V2, prob=71.6))
        self.assertEqual("gia_presente_altra_versione", azione)
        self.assertEqual(prima, lista)

    def test_v2_si_aggiunge_se_il_mercato_e_diverso(self):
        esistenti = [riga(versione=V1, mercato="Over 2.5", prob=64.0)]
        lista, azione = upsert_prediction_entry(esistenti, riga(versione=V2, mercato="1", prob=71.6))
        self.assertEqual("aggiunta", azione)
        self.assertEqual(2, len(lista))

    def test_v2_si_aggiunge_se_la_tabella_e_diversa(self):
        esistenti = [riga(versione=V1, variante=MODEL_VARIANT_LEGACY, prob=64.5)]
        lista, azione = upsert_prediction_entry(esistenti, riga(versione=V2, variante=MODEL_VARIANT_CURRENT,
                                                                prob=71.6))
        self.assertEqual("aggiunta", azione)

    def test_stessa_versione_stessa_chiave_resta_un_aggiornamento(self):
        """Il ricalcolo della STESSA riga (non giudicata) continua a sostituirla: non e' un'aggiunta."""
        esistenti = [riga(versione=V2, prob=70.0, salvato_il="19/10/2026 10:00")]
        lista, azione = upsert_prediction_entry(esistenti, riga(versione=V2, prob=71.6))
        self.assertEqual("aggiornata", azione)
        self.assertEqual(1, len(lista))
        self.assertEqual(71.6, lista[0]["prob_sicuro"])

    def test_riga_giudicata_della_v1_non_viene_toccata(self):
        esistenti = [riga(versione=V1, prob=64.5, esito="✅")]
        prima = copy.deepcopy(esistenti)
        lista, azione = upsert_prediction_entry(esistenti, riga(versione=V2, prob=71.6))
        self.assertEqual("gia_presente_altra_versione", azione)
        self.assertEqual(prima, lista)

    def test_analisi_rapida_non_blocca_la_top_mix(self):
        esistenti = [riga(origin=ORIGIN_ANALISI_RAPIDA, versione="analisi_v1", mercato="1")]
        lista, azione = upsert_prediction_entry(esistenti, riga(versione=V2, mercato="1"))
        self.assertEqual("aggiunta", azione)
        self.assertEqual(2, len(lista))

    def test_dedup_key_invariata(self):
        """La regola dei doppioni NON cambia l'identita' delle righe (chiavi e id stabili)."""
        self.assertNotEqual(dedup_key(riga(versione=V1)), dedup_key(riga(versione=V2)))
        self.assertEqual(chiave_tabella_mercato(riga(versione=V1)), chiave_tabella_mercato(riga(versione=V2)))


class TestScritturaBloccoOmbra(unittest.TestCase):
    """``upsert_prediction_entries`` (ombra): stessa regola, solo per la Top Mix."""

    def test_blocco_top_mix_salta_il_doppione_di_altra_versione(self):
        esistenti = [riga(versione=V1, prob=64.5)]
        lista, azioni = upsert_prediction_entries(esistenti, [riga(versione=V2, prob=71.6)])
        self.assertEqual({"gia_presente_altra_versione": 1}, azioni)
        self.assertEqual(esistenti, lista)

    def test_blocco_ombra_non_e_toccato_dalla_regola(self):
        ombra = riga(origin=ORIGIN_TOP_MIX_OMBRA, versione="topmix_ombra_ou25_v1", ombra=True,
                     ombra_mercato="Over 2.5", mercato="Over 2.5")
        esistenti = [riga(versione=V1, mercato="Over 2.5", prob=64.0)]
        lista, azioni = upsert_prediction_entries(esistenti, [ombra])
        self.assertEqual({"aggiunta": 1}, azioni)
        self.assertEqual(2, len(lista))


class TestReplayMerge(unittest.TestCase):
    """Percorso del replay --write: ``merge_entries`` (dry-run e scrittura usano la stessa fusione)."""

    def test_merge_non_aggiunge_v2_accanto_a_v1(self):
        import replay_legacy_topmix as replay
        esistenti = [riga(versione=V1, prob=64.5)]
        prima = copy.deepcopy(esistenti)
        merged, azioni = replay.merge_entries(esistenti, [riga(versione=V2, prob=71.6)])
        self.assertEqual(1, azioni["gia_presente_altra_versione"])
        self.assertEqual(0, azioni.get("aggiunta", 0))
        self.assertEqual(prima, merged)

    def test_merge_aggiunge_la_v2_se_la_scelta_e_nuova(self):
        import replay_legacy_topmix as replay
        esistenti = [riga(versione=V1, mercato="Over 2.5", prob=64.0)]
        merged, azioni = replay.merge_entries(esistenti, [riga(versione=V2, mercato="1", prob=71.6)])
        self.assertEqual(1, azioni["aggiunta"])
        self.assertEqual(2, len(merged))


if __name__ == "__main__":
    unittest.main()
