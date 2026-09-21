"""Campo ``model_variant`` del Registro (Top Mix a due motori): solo stdlib.

Contratto:

* il campo MANCA in tutte le righe scritte prima e l'assenza vale ``current``:
  nessun lettore esistente cambia risultato su un registro senza il campo;
* ``dedup_key`` include la variante: la riga legacy di una partita non
  sostituisce MAI la riga current (nemmeno quando e' ancora in attesa) e
  l'upsert di una legacy lascia la lista esistente byte-identica;
* ``build_calculation_id`` non cambia per le righe current (id storici
  stabili) e cambia per le legacy;
* le statistiche del "modello attuale" NON contano le righe legacy, che hanno
  il loro blocco (``stats_legacy_variant``); ``stats_all`` conta tutto.
"""
from __future__ import annotations

import copy
import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import prediction_registry as R  # noqa: E402


def _riga(mid=501, variant=None, esito="⏳", prob=64.0, **extra):
    e = {
        "match_id": mid, "home": "Casa", "away": "Trasferta", "campionato": "Serie A",
        "giornata": 5, "data": "19/09/2026 18:00", "pronostico_sicuro": "Vittoria Casa - Top Mix",
        "mercato_standard": "1", "top3": [], "prob_sicuro": prob, "risultati_attesi": "",
        "risultato_reale": None, "esito": esito, "tipo": "Top Mix", "stagione": "2026/2027",
        # Salvataggio DOPO il merge di PR#24: una riga senza campo scritta
        # dopo e' del modello attuale. (Le righe nate prima si leggono legacy:
        # c'e' un test apposta che lo pina.)
        "salvato_il": "19/09/2026 09:00", "origin": R.ORIGIN_TOP_MIX,
        "selector_version": R.SELECTOR_VERSION_CURRENT, "rank": 1,
        "kickoff_utc": "2026-09-19T18:00:00Z", "data_snapshot_sha": "abc123abc123",
        "calculation_id": "x", "poisson": 60.0, "elo": 66.0, "elo_disponibile": True,
        R.MODEL_VERSION_FIELD: R.MODEL_VERSION_CURRENT,
        R.EXCLUDED_FROM_CURRENT_STATS_FIELD: False,
    }
    if variant is not None:
        e[R.MODEL_VARIANT_FIELD] = variant
    e.update(extra)
    return e


class TestSemanticaCampo(unittest.TestCase):
    def test_assente_vale_current(self):
        self.assertEqual(R.model_variant_of(_riga()), R.MODEL_VARIANT_CURRENT)
        self.assertEqual(R.model_variant_of({}), R.MODEL_VARIANT_CURRENT)
        self.assertEqual(R.model_variant_of(None), R.MODEL_VARIANT_CURRENT)
        self.assertEqual(R.model_variant_of(_riga(variant="")), R.MODEL_VARIANT_CURRENT)
        self.assertFalse(R.is_legacy_variant(_riga()))

    def test_valori_assenti_di_pandas_non_diventano_una_variante(self):
        """Bug visto in UI il 21/09/2026: su un DataFrame di pandas il campo
        assente diventa ``NaN`` e ``str(nan)`` e' ``"nan"``, cioe' una terza
        variante fantasma che faceva sparire la riga dal blocco legacy."""
        nan = float("nan")
        # NaN = campo assente: decide la DATA, come per una riga senza chiave.
        prima = _riga(variant=nan, salvato_il="10/09/2026 12:00")
        dopo = _riga(variant=nan)                      # salvato il 19/09 (post-merge)
        self.assertEqual(R.model_variant_read(prima), R.MODEL_VARIANT_LEGACY)
        self.assertEqual(R.model_variant_read(dopo), R.MODEL_VARIANT_CURRENT)
        self.assertEqual(R.MODEL_VARIANT_SOURCE_SAVED, R.model_variant_read_source(prima),
                         "la fonte e' l'istante di salvataggio: il campo NaN non e' un valore esplicito")
        self.assertEqual(R.model_variant_of(_riga(variant=nan)), R.MODEL_VARIANT_CURRENT)
        # Stessa cosa per le altre forme di "assente" e per la stringa "nan".
        for valore in (None, "", "  ", "nan", "NaN", "NA"):
            self.assertEqual(R.model_variant_read(_riga(variant=valore, salvato_il="10/09/2026 12:00")),
                             R.MODEL_VARIANT_LEGACY, f"valore {valore!r} trattato come assente")

    def test_legacy_esplicita(self):
        self.assertEqual(R.model_variant_of(_riga(variant="legacy")), R.MODEL_VARIANT_LEGACY)
        self.assertEqual(R.model_variant_of(_riga(variant=" LEGACY ")), R.MODEL_VARIANT_LEGACY)
        self.assertTrue(R.is_legacy_variant(_riga(variant=R.MODEL_VARIANT_LEGACY)))

    def test_etichette(self):
        self.assertEqual(R.model_variant_label(_riga()), "Attuale")
        self.assertEqual(R.model_variant_label(_riga(variant="legacy")), "Legacy")
        self.assertEqual(R.model_variant_label(_riga(variant="boh")), "boh")

    def test_lettura_per_data_prima_e_dopo_la_fusione(self):
        """Correzione chiesta: il campo mancante non vale "current" per ogni
        epoca. Una riga nata PRIMA del merge di PR#24 e' del motore che girava
        allora (legacy); una nata dopo e' del motore nuovo (current)."""
        prima = _riga(salvato_il="10/09/2026 10:00")
        dopo = _riga(salvato_il="19/09/2026 10:00")
        self.assertEqual(R.MODEL_VARIANT_LEGACY, R.model_variant_read(prima))
        self.assertEqual(R.MODEL_VARIANT_CURRENT, R.model_variant_read(dopo))
        self.assertEqual(R.MODEL_VARIANT_SOURCE_SAVED, R.model_variant_read_source(prima))
        # il percorso di scrittura NON cambia: la chiave di dedup resta stabile
        self.assertEqual(R.MODEL_VARIANT_CURRENT, R.model_variant_of(prima))

    def test_confine_della_fusione_half_open(self):
        """Un istante esattamente sul confine e' del modello nuovo: la stessa
        convenzione half-open usata dalle due commesse di replay."""
        # senza istante di salvataggio decide l'istante della partita
        self.assertEqual(R.MODEL_VARIANT_LEGACY,
                         R.model_variant_read(_riga(salvato_il=None, kickoff_utc="2026-09-18T21:51:57Z")))
        self.assertEqual(R.MODEL_VARIANT_CURRENT,
                         R.model_variant_read(_riga(salvato_il=None, kickoff_utc="2026-09-18T21:51:58Z")))
        # il confine e' lo stesso delle due commesse di replay
        import replay_legacy_topmix as replay
        self.assertEqual(replay.PR24_MERGE_INSTANT, R.TWO_MODELS_MERGE_INSTANT)

    def test_campo_esplicito_vince_sulla_data(self):
        esplicita = _riga(variant=R.MODEL_VARIANT_CURRENT, salvato_il="10/09/2026 10:00")
        self.assertEqual(R.MODEL_VARIANT_CURRENT, R.model_variant_read(esplicita))
        self.assertEqual(R.MODEL_VARIANT_SOURCE_EXPLICIT, R.model_variant_read_source(esplicita))

    def test_istante_illeggibile_resta_current_ma_dichiarato(self):
        """Senza nessuna data non si inventa l'epoca: resta ``current`` per
        convenzione, ma la fonte dice che l'istante e' ignoto, cosi' chi legge
        lo puo' contare invece di scambiarlo per una riga del modello nuovo."""
        senza_date = _riga()
        for campo in (R.SALVATO_IL_FIELD, R.KICKOFF_UTC_FIELD, R.DATA_FIELD):
            senza_date.pop(campo, None)
        self.assertEqual(R.MODEL_VARIANT_CURRENT, R.model_variant_read(senza_date))
        self.assertEqual(R.MODEL_VARIANT_SOURCE_UNKNOWN, R.model_variant_read_source(senza_date))

    def test_non_confonde_model_version(self):
        # model_version "legacy" (era pre-shrinkage) NON e' la variante legacy.
        vecchia = _riga(**{R.MODEL_VERSION_FIELD: R.MODEL_VERSION_LEGACY})
        self.assertEqual(R.model_variant_of(vecchia), R.MODEL_VARIANT_CURRENT)
        self.assertEqual(R.get_model_version(vecchia), R.MODEL_VERSION_LEGACY)


class TestChiaveDedupEUpsert(unittest.TestCase):
    def test_la_variante_e_nella_chiave(self):
        a = R.dedup_key(_riga())
        b = R.dedup_key(_riga(variant="legacy"))
        c = R.dedup_key(_riga(variant="current"))
        self.assertNotEqual(a, b)
        self.assertEqual(a, c, "current esplicito e campo assente (dopo il merge) sono la stessa riga")
        # La correzione: una riga senza campo nata PRIMA del merge e' del
        # motore di allora, quindi la sua chiave e' quella del legacy — non
        # occupa piu' il posto della riga del modello attuale.
        prima = R.dedup_key(_riga(salvato_il="10/09/2026 10:00"))
        self.assertEqual(prima, b, "riga pre-merge senza campo: chiave legacy")
        self.assertNotEqual(prima, a, "e NON occupa la chiave del modello attuale")
        self.assertEqual(len(a), 4)

    def test_legacy_non_sovrascrive_la_current_in_attesa(self):
        esistenti = [_riga(prob=64.0)]
        prima = copy.deepcopy(esistenti)
        out, azione = R.upsert_prediction_entry(esistenti, _riga(variant="legacy", prob=58.0))
        self.assertEqual(azione, "aggiunta")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0], prima[0], "la riga current e' stata alterata")
        self.assertEqual(esistenti, prima, "la lista in ingresso e' stata mutata")

    def test_legacy_non_sovrascrive_la_current_giudicata(self):
        esistenti = [_riga(esito=R.ESITO_VINTO)]
        prima = copy.deepcopy(esistenti)
        out, azione = R.upsert_prediction_entry(esistenti, _riga(variant="legacy"))
        self.assertEqual(azione, "aggiunta")
        self.assertEqual(out[0], prima[0])

    def test_ricalcolo_legacy_aggiorna_solo_la_legacy(self):
        esistenti = [_riga(prob=64.0), _riga(variant="legacy", prob=58.0)]
        prima = copy.deepcopy(esistenti)
        out, azione = R.upsert_prediction_entry(esistenti, _riga(variant="legacy", prob=59.5))
        self.assertEqual(azione, "aggiornata")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0], prima[0])
        self.assertEqual(out[1]["prob_sicuro"], 59.5)
        self.assertEqual(out[1]["salvato_il_originario"], "19/09/2026 09:00")

    def test_legacy_giudicata_non_si_tocca(self):
        esistenti = [_riga(variant="legacy", esito=R.ESITO_PERSO, prob=58.0)]
        out, azione = R.upsert_prediction_entry(esistenti, _riga(variant="legacy", prob=70.0))
        self.assertEqual(azione, "gia_graduata")
        self.assertEqual(out[0]["prob_sicuro"], 58.0)


class TestEtichettaEStatistichePerData(unittest.TestCase):
    """Cio' che l'utente vede: un pronostico vecchio e' "Legacy", non "Attuale".

    E' la correzione chiesta prima del merge: l'etichetta e i due blocchi di
    statistiche devono leggere la DATA quando il campo variante manca.
    """

    def test_etichetta_di_una_riga_pre_merge(self):
        vecchia = _riga(salvato_il="10/09/2026 10:00")
        self.assertEqual("Legacy", R.model_variant_label(vecchia))
        self.assertTrue(R.is_legacy_variant(vecchia))
        self.assertEqual({R.MODEL_VARIANT_LEGACY: 1}, {k: len(v) for k, v in
                                                         R.split_by_variant([vecchia]).items()})

    def test_etichetta_di_una_riga_dopo_il_merge(self):
        nuova = _riga(salvato_il="19/09/2026 10:00")
        self.assertEqual("Attuale", R.model_variant_label(nuova))
        self.assertFalse(R.is_legacy_variant(nuova))

    def test_i_due_blocchi_di_statistiche_con_una_riga_vecchia(self):
        vecchia = _riga(salvato_il="10/09/2026 10:00", esito=R.ESITO_VINTO)
        nuova = _riga(salvato_il="19/09/2026 10:00", esito=R.ESITO_PERSO)
        self.assertEqual(1, R.stats_current_model([vecchia, nuova])["total"])
        self.assertEqual(1, R.stats_current_model([vecchia, nuova])["losses"])
        self.assertEqual(1, R.stats_legacy_variant([vecchia, nuova])["total"])
        self.assertEqual(1, R.stats_legacy_variant([vecchia, nuova])["wins"])


class TestCalculationId(unittest.TestCase):
    def _vecchia_formula(self, *parti):
        return hashlib.sha1("|".join(str(p) for p in parti).encode("utf-8")).hexdigest()[:16]

    def test_current_o_assente_id_invariato(self):
        atteso = self._vecchia_formula(921, R.ORIGIN_TOP_MIX, "v1", "2026-09-06T18:00:00Z", "abc", 3)
        self.assertEqual(R.build_calculation_id(921, R.ORIGIN_TOP_MIX, "v1", "2026-09-06T18:00:00Z", "abc", 3),
                         atteso)
        self.assertEqual(R.build_calculation_id(921, R.ORIGIN_TOP_MIX, "v1", "2026-09-06T18:00:00Z", "abc", 3,
                                                model_variant=R.MODEL_VARIANT_CURRENT), atteso)
        self.assertEqual(R.build_calculation_id(921, R.ORIGIN_TOP_MIX, "v1", "2026-09-06T18:00:00Z", "abc", 3,
                                                model_variant=None), atteso)

    def test_legacy_id_diverso_e_deterministico(self):
        a = R.build_calculation_id(921, R.ORIGIN_TOP_MIX, "v1", "2026-09-06T18:00:00Z", "abc", 3,
                                   model_variant=R.MODEL_VARIANT_LEGACY)
        b = R.build_calculation_id(921, R.ORIGIN_TOP_MIX, "v1", "2026-09-06T18:00:00Z", "abc", 3,
                                   model_variant=R.MODEL_VARIANT_LEGACY)
        c = R.build_calculation_id(921, R.ORIGIN_TOP_MIX, "v1", "2026-09-06T18:00:00Z", "abc", 3)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(a, self._vecchia_formula(921, R.ORIGIN_TOP_MIX, "v1", "2026-09-06T18:00:00Z",
                                                  "abc", 3, "legacy"))


class TestStatistichePerVariante(unittest.TestCase):
    RIGHE = [
        _riga(mid=1, esito=R.ESITO_VINTO),
        _riga(mid=2, esito=R.ESITO_PERSO),
        _riga(mid=3),
        _riga(mid=1, variant="legacy", esito=R.ESITO_PERSO),
        _riga(mid=4, variant="legacy", esito=R.ESITO_VINTO),
        _riga(mid=5, variant="legacy"),
        _riga(mid=6, esito=R.ESITO_VINTO, **{R.MODEL_VERSION_FIELD: R.MODEL_VERSION_PRE_FIX,
                                            R.EXCLUDED_FROM_CURRENT_STATS_FIELD: True}),
    ]

    def test_modello_attuale_esclude_le_legacy(self):
        s = R.stats_current_model(self.RIGHE)
        self.assertEqual((s["total"], s["wins"], s["losses"], s["pending"]), (3, 1, 1, 1))

    def test_blocco_legacy_conta_solo_le_legacy(self):
        s = R.stats_legacy_variant(self.RIGHE)
        self.assertEqual((s["total"], s["wins"], s["losses"], s["pending"]), (3, 1, 1, 1))

    def test_storico_e_totale_invariati(self):
        self.assertEqual(R.stats_historical(self.RIGHE)["total"], 1)
        self.assertEqual(R.stats_all(self.RIGHE)["total"], 7)

    def test_registro_senza_il_campo_numeri_identici_a_prima(self):
        # Un registro "vecchio" (nessuna riga col campo) da' esattamente i
        # numeri della formula precedente: current & non escluse.
        vecchie = [r for r in self.RIGHE if R.MODEL_VARIANT_FIELD not in r]
        s = R.stats_current_model(vecchie)
        atteso = R.compute_stats([e for e in vecchie if R.is_current_model(e)
                                  and not R.is_excluded_from_stats(e)])
        self.assertEqual({k: v for k, v in s.items() if k != "entries"},
                         {k: v for k, v in atteso.items() if k != "entries"})
        self.assertEqual(R.stats_legacy_variant(vecchie)["total"], 0)

    def test_split_by_variant(self):
        parti = R.split_by_variant(self.RIGHE)
        self.assertEqual(sorted(parti), ["current", "legacy"])
        self.assertEqual(len(parti["current"]), 4)
        self.assertEqual(len(parti["legacy"]), 3)


class TestLettoriEsistentiNonCambiano(unittest.TestCase):
    """Le funzioni che la dashboard gia' usa accettano righe legacy senza errori
    e, sulle righe senza campo, rispondono come prima."""

    def test_helper_di_lettura(self):
        for r in (_riga(), _riga(variant="legacy")):
            self.assertEqual(R.origin_of(r), R.ORIGIN_TOP_MIX)
            self.assertEqual(R.model_label(r), R.MODEL_LABEL_CURRENT)
            self.assertEqual(R.classify_entry(r)[R.MODEL_VERSION_FIELD], R.MODEL_VERSION_CURRENT)
            self.assertEqual(R.prob_of_entry(r), 0.64)
            self.assertEqual(R.esito_mercato(r["mercato_standard"], 2, 1), R.ESITO_VINTO)
            tenute, scartate = R.righe_non_iniziate([r], ora="2026-09-19T17:00:00Z",
                                                    campo_kickoff="kickoff_utc")
            self.assertEqual((len(tenute), scartate), (1, 0))

    def test_calibrazione_su_misto(self):
        righe = [_riga(mid=1, esito=R.ESITO_VINTO), _riga(mid=1, variant="legacy", esito=R.ESITO_PERSO)]
        stat = R.compute_calibration_stats(righe)
        self.assertEqual(stat["decise"], 2)
        for parte, attese in R.split_by_variant(righe).items():
            self.assertEqual(R.compute_calibration_stats(attese)["decise"], 1, parte)


if __name__ == "__main__":
    unittest.main(verbosity=2)
