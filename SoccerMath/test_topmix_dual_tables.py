"""Top Mix a due modelli: due tabelle, nessun tetto, stesso meccanismo di registro.

Cosa viene provato (Commessa "Top Mix a due modelli", FASE 3/4):

* ``calcola_righe_top_mix`` produce DUE liste (current / legacy) dallo stesso
  Poisson: sui mercati 1X2 le righe differiscono quando i due Elo
  differiscono, sui Totali (Elo non letto) coincidono numero per numero, e le
  due tabelle possono contenere partite diverse (nessuna coincidenza forzata);
* ``classifica_top_mix`` non tronca: N righe sopra soglia -> N righe con rank
  1..N (il vecchio tetto di 10 e' sparito per ENTRAMBE le tabelle), soglie
  invariate (0,55 1X2 / 0,60 Totali);
* ``argomenti_registro_top_mix`` e' l'unico punto che trasforma una riga in
  record: i suoi argomenti sono esattamente quelli accettati da
  ``save_prediction_entry``/``build_prediction_entry``, e la variante passa
  nel record senza altre differenze;
* guardie sul sorgente del tab2: due tabelle etichettate, Attuale sopra e
  Legacy sotto, entrambe salvate con lo STESSO ``save_prediction_entry``.
"""
from __future__ import annotations

import ast
import inspect
import logging
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

logging.getLogger("streamlit").setLevel(logging.ERROR)

import app  # noqa: E402
from prediction_registry import (  # noqa: E402
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_FIELD,
    MODEL_VARIANT_LEGACY,
    dedup_key,
    model_variant_of,
)

APP_PATH = os.path.join(HERE, "app.py")


def _match(mid, home, away, md=5, utc="2026-10-03T18:45:00Z"):
    return {"id": mid, "matchday": md, "utcDate": utc,
            "homeTeam": {"shortName": home}, "awayTeam": {"shortName": away}}


def _engine(stats):
    """(team_stats, avg_h, avg_a, extra) come get_league_engine."""
    return (stats, 1.5, 1.2, {})


class TestDueMotoriStessoSelettore(unittest.TestCase):
    """Le due tabelle nascono dallo stesso Poisson e dallo stesso selettore."""

    def setUp(self):
        self.stats = {
            "Inter": {"att": 1.15, "def": 0.85}, "Roma": {"att": 0.85, "def": 1.15},
            "Milan": {"att": 1.0, "def": 1.0}, "Lazio": {"att": 1.0, "def": 1.0},
            "Napoli": {"att": 0.85, "def": 0.85}, "Torino": {"att": 0.85, "def": 0.85},
        }
        self.matches = [_match(1, "Inter", "Roma"), _match(2, "Milan", "Lazio"), _match(3, "Napoli", "Torino")]

    def _righe(self, elo_current, elo_legacy):
        with mock.patch.object(app, "predict_elo_probs", side_effect=elo_current), \
             mock.patch.object(app, "predict_elo_probs_legacy", side_effect=elo_legacy):
            return app.calcola_righe_top_mix("Serie A", self.matches, _engine(self.stats))

    def test_due_liste_e_poisson_identico_per_partita(self):
        cur_elo = lambda h, a, l: {"1": 0.70, "X": 0.18, "2": 0.12}
        leg_elo = lambda h, a, l: {"1": 0.55, "X": 0.25, "2": 0.20}
        righe = self._righe(cur_elo, leg_elo)
        self.assertEqual({MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY}, set(righe))
        cur = {r["match_id"]: r for r in righe[MODEL_VARIANT_CURRENT]}
        leg = {r["match_id"]: r for r in righe[MODEL_VARIANT_LEGACY]}
        self.assertIn(1, cur, "Inter-Roma deve passare la soglia 1X2 col blend Elo attuale")
        self.assertIn(1, leg)
        # stesso Poisson, Elo diverso -> confidence 1X2 diversa
        self.assertEqual(cur[1]["poisson"], leg[1]["poisson"])
        self.assertNotEqual(cur[1]["elo"], leg[1]["elo"])
        self.assertNotEqual(cur[1]["prob"], leg[1]["prob"])
        self.assertGreater(cur[1]["prob"], leg[1]["prob"])
        for r in list(cur.values()) + list(leg.values()):
            self.assertIsNone(r["rank"], "il rank lo assegna classifica_top_mix")
            self.assertEqual(sorted(r), sorted(["league", "giornata", "home", "away", "match_id", "utcDate",
                                                "market", "mercato_standard", "prob", "prob_val", "poisson",
                                                "elo", "elo_disponibile", "rank"]))

    def test_tabelle_possono_contenere_partite_diverse(self):
        """Con l'Elo legacy in disaccordo (veto |P-E| >= 0.25) Inter-Roma sparisce
        SOLO dalla tabella legacy: nessuna coincidenza forzata fra le due."""
        cur_elo = lambda h, a, l: {"1": 0.70, "X": 0.18, "2": 0.12}
        leg_elo = lambda h, a, l: {"1": 0.20, "X": 0.30, "2": 0.50}
        righe = self._righe(cur_elo, leg_elo)
        cur_ids = {r["match_id"] for r in righe[MODEL_VARIANT_CURRENT]}
        leg_ids = {r["match_id"] for r in righe[MODEL_VARIANT_LEGACY]}
        self.assertIn(1, cur_ids)
        self.assertNotIn(1, leg_ids)

    def test_legacy_sotto_soglia_e_solo_current_ha_la_riga(self):
        """Il Poisson scelto e' 1X2 con confidence attuale 0.63: col legacy 0.53
        (< 0.55) la riga NON esiste per il legacy. E' la spiegazione misurata
        delle partite coperte solo dal modello attuale (vedi
        audit/results/replay_sym_offline/diagnosi_differenze.md)."""
        cur_elo = lambda h, a, l: {"1": 0.70, "X": 0.18, "2": 0.12}
        leg_elo = lambda h, a, l: {"1": 0.48, "X": 0.28, "2": 0.24}
        righe = self._righe(cur_elo, leg_elo)
        cur = {r["match_id"] for r in righe[MODEL_VARIANT_CURRENT]}
        leg = {r["match_id"] for r in righe[MODEL_VARIANT_LEGACY]}
        self.assertIn(1, cur)
        self.assertNotIn(1, leg)

    def test_totali_identici_e_legacy_in_errore_isolato(self):
        """Elo legacy che solleva: la riga legacy resta Poisson puro (soglia 0,60),
        quella current non ne risente; sui Totali le due righe coincidono."""
        cur_elo = lambda h, a, l: {"1": 0.70, "X": 0.18, "2": 0.12}

        def leg_elo(h, a, l):
            raise RuntimeError("legacy rotto")

        righe = self._righe(cur_elo, leg_elo)
        cur = {r["match_id"]: r for r in righe[MODEL_VARIANT_CURRENT]}
        leg = {r["match_id"]: r for r in righe[MODEL_VARIANT_LEGACY]}
        self.assertTrue(cur[1]["elo_disponibile"])
        for r in leg.values():
            self.assertFalse(r["elo_disponibile"])
            self.assertAlmostEqual(r["prob"], r["poisson"] / 100.0, places=3)   # poisson e' arrotondato a 1 decimale
        for mid in set(cur) & set(leg):
            if not cur[mid]["market"].startswith(("Vittoria", "Pareggio")):
                self.assertEqual(cur[mid]["prob"], leg[mid]["prob"])


class TestNessunTetto(unittest.TestCase):
    def test_classifica_non_tronca_e_ordina(self):
        righe = [{"prob": 0.55 + i * 0.001, "match_id": i} for i in range(25)]
        out = app.classifica_top_mix(list(righe))
        self.assertEqual(25, len(out))
        self.assertEqual(list(range(1, 26)), [r["rank"] for r in out])
        probs = [r["prob"] for r in out]
        self.assertEqual(probs, sorted(probs, reverse=True))

    def test_fetch_ritorna_due_tabelle_senza_tetto(self):
        """40 partite sopra soglia in una lega -> 40 righe in ENTRAMBE le tabelle."""
        stats = {f"H{i}": {"att": 1.15, "def": 0.85} for i in range(40)}
        stats.update({f"A{i}": {"att": 0.85, "def": 1.15} for i in range(40)})
        matches = [_match(100 + i, f"H{i}", f"A{i}") for i in range(40)]

        class _Resp:
            status_code = 200

            def json(self):
                return {"matches": matches}

        elo = lambda h, a, l: {"1": 0.70, "X": 0.18, "2": 0.12}
        with mock.patch.object(app.requests, "get", return_value=_Resp()), \
             mock.patch.object(app, "get_league_engine", return_value=_engine(stats)), \
             mock.patch.object(app, "predict_elo_probs", side_effect=elo), \
             mock.patch.object(app, "predict_elo_probs_legacy", side_effect=elo), \
             mock.patch.object(app, "select_next_matchday_matches", side_effect=lambda m, now=None: m), \
             mock.patch.object(app.time, "sleep", lambda s: None):
            app.fetch_and_calc_top_mix.clear()
            top_current, top_legacy, missing = app.fetch_and_calc_top_mix()
        n_leghe = len(app.LEAGUES_CONFIG)
        self.assertEqual([], missing)
        self.assertEqual(40 * n_leghe, len(top_current))
        self.assertEqual(40 * n_leghe, len(top_legacy))
        self.assertEqual(list(range(1, 40 * n_leghe + 1)), [r["rank"] for r in top_current])
        self.assertEqual(list(range(1, 40 * n_leghe + 1)), [r["rank"] for r in top_legacy])

    def test_soglie_invariate_nel_selettore(self):
        src = open(APP_PATH, encoding="utf-8").read()
        tree = ast.parse(src)
        sel = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "seleziona_riga_top_mix")
        testo = ast.unparse(sel)
        self.assertIn("min_conf = 0.55", testo)
        self.assertTrue("min_conf = 0.6" in testo or "min_conf = 0.60" in testo)
        for nome in ("fetch_and_calc_top_mix", "calcola_righe_top_mix", "classifica_top_mix", "_riga_top_mix"):
            fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == nome)
            self.assertNotIn("[:10]", ast.unparse(fn), nome)


class TestArgomentiRegistro(unittest.TestCase):
    RIGA = {"league": "Serie A", "giornata": 5, "home": "Inter", "away": "Roma", "match_id": 4242,
            "utcDate": "2026-10-03T18:45:00Z", "market": "Vittoria Inter", "mercato_standard": "1",
            "prob": 0.6123, "prob_val": 61.2, "poisson": 58.0, "elo": 62.3, "elo_disponibile": True, "rank": 3}

    def test_argomenti_accettati_da_save_e_build(self):
        for variante in (MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY):
            args, kwargs = app.argomenti_registro_top_mix(self.RIGA, model_variant=variante)
            for fn in (app.save_prediction_entry, app.build_prediction_entry):
                inspect.signature(fn).bind(*args, **kwargs)     # TypeError se non combaciano
            self.assertEqual(variante, kwargs["model_variant"])
            self.assertEqual((4242, "Inter", "Roma", "Serie A", 5), args[:5])
            self.assertEqual("Vittoria Inter - Top Mix", args[6])
            self.assertEqual(61.2, args[8])
            self.assertEqual("1", kwargs["mercato_standard"])
            self.assertEqual(3, kwargs["rank"])
            self.assertEqual("2026-10-03T18:45:00Z", kwargs["kickoff_utc"])
            self.assertEqual((58.0, 62.3, True), (kwargs["prob_poisson"], kwargs["prob_elo"], kwargs["elo_disponibile"]))

    def test_record_differisce_solo_per_variante(self):
        a_cur, k_cur = app.argomenti_registro_top_mix(self.RIGA, model_variant=MODEL_VARIANT_CURRENT)
        a_leg, k_leg = app.argomenti_registro_top_mix(self.RIGA, model_variant=MODEL_VARIANT_LEGACY)
        cur = app.build_prediction_entry(*a_cur, **k_cur, snapshot_sha="abc123", salvato_il="03/10/2026 18:00")
        leg = app.build_prediction_entry(*a_leg, **k_leg, snapshot_sha="abc123", salvato_il="03/10/2026 18:00")
        self.assertEqual(list(cur), list(leg))
        self.assertEqual({MODEL_VARIANT_FIELD, "calculation_id"}, {k for k in cur if cur[k] != leg[k]})
        self.assertEqual(MODEL_VARIANT_CURRENT, model_variant_of(cur))
        self.assertEqual(MODEL_VARIANT_LEGACY, model_variant_of(leg))
        self.assertNotEqual(dedup_key(cur), dedup_key(leg), "chiavi distinte: la legacy non sostituisce la current")

    def test_riga_senza_variante_esplicita_e_current(self):
        args, kwargs = app.argomenti_registro_top_mix(self.RIGA)
        self.assertEqual(MODEL_VARIANT_CURRENT, kwargs["model_variant"])


class TestGuardieTab2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = open(APP_PATH, encoding="utf-8").read()
        i = cls.src.index("with tab2:")
        j = cls.src.index("with tab3:")
        cls.tab2 = cls.src[i:j]

    def test_due_tabelle_etichettate_attuale_sopra_legacy_sotto(self):
        self.assertIn("MODELLO ATTUALE", self.tab2)
        self.assertIn("MODELLO LEGACY", self.tab2)
        self.assertLess(self.tab2.index("MODELLO ATTUALE"), self.tab2.index("MODELLO LEGACY"))
        self.assertIn("(MODEL_VARIANT_CURRENT, top_current,", self.tab2)
        self.assertIn("(MODEL_VARIANT_LEGACY, top_legacy,", self.tab2)
        self.assertIn("_mostra_tabella_top_mix(righe_tab, titolo, sottotitolo, css)", self.tab2)

    def test_entrambe_salvano_con_lo_stesso_meccanismo(self):
        self.assertIn("args_reg, kwargs_reg = argomenti_registro_top_mix(p, model_variant=variante)", self.tab2)
        self.assertIn("save_prediction_entry(*args_reg, **kwargs_reg)", self.tab2)
        self.assertEqual(1, self.tab2.count("save_prediction_entry("), "un solo punto di scrittura per le due tabelle")
        self.assertNotIn("[:10]", self.tab2)
        self.assertNotIn("ricostru", self.tab2.lower())

    def test_filtro_rigo_iniziato_su_entrambe(self):
        self.assertIn("righe_non_iniziate(top_current)", self.tab2)
        self.assertIn("righe_non_iniziate(top_legacy)", self.tab2)


if __name__ == "__main__":
    unittest.main()
