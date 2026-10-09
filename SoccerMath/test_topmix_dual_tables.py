"""Top Mix a due modelli: due tabelle, nessun tetto, stesso meccanismo di registro.

Cosa viene provato (Commessa "Top Mix a due modelli", FASE 3/4):

* ``calcola_righe_top_mix`` produce DUE liste (current / legacy) dallo stesso
  Poisson: sui 1X2 le righe differiscono quando i due Elo differiscono, e le
  due tabelle possono contenere partite diverse (nessuna coincidenza forzata).
  Dal PR Totali nessuna delle due tabelle contiene un Over/Under o un GG/NG:
  quelle scelte vanno nel registro ombra (campo ``ombra`` di ``fetch``);
* ``classifica_top_mix`` non tronca: N righe sopra soglia -> N righe con rank
  1..N (il vecchio tetto di 10 e' sparito per ENTRAMBE le tabelle), soglie
  invariate (0,55 sui 1X2 con Elo, 0,60 senza Elo);
* ``argomenti_registro_top_mix`` e' l'unico punto che trasforma una riga in
  record: i suoi argomenti sono esattamente quelli accettati da
  ``save_prediction_entry``/``build_prediction_entry``, e la variante passa
  nel record senza altre differenze;
* guardie sul sorgente del tab2: dalla PR delle quote live il tab2 mostra UNA
  sola tabella, quella del MERCATO. Le due liste del modello non sono piu'
  mostrate: alimentano il registro ombra. Qui si verifica che (a) la tabella
  mostrata e salvata e' quella di mercato, (b) il Registro visibile e' scritto
  da un solo punto (``argomenti_registro_top_mix_mercato`` +
  ``save_prediction_entry``), (c) le righe del modello arrivano ancora a
  ``salva_registro_ombra``, (d) le partite senza quote sono segnalate.
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
import market_odds as mo  # noqa: E402
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
        # Roster non disponibile (= non valutabile): qui si prova il selettore e
        # le due tabelle, non la classificazione roster/stats (in
        # test_fallback_nomi.py). Senza il patch verrebbe caricato il motore
        # Elo reale di produzione solo per leggere il roster.
        with mock.patch.object(app, "predict_elo_probs", side_effect=elo_current), \
             mock.patch.object(app, "predict_elo_probs_legacy", side_effect=elo_legacy), \
             mock.patch.object(app, "_roster_stagione", return_value=None):
            return app.calcola_righe_top_mix("Serie A", self.matches, _engine(self.stats))

    def test_due_liste_e_poisson_identico_per_partita(self):
        cur_elo = lambda h, a, l, season=None: {"1": 0.70, "X": 0.18, "2": 0.12}
        leg_elo = lambda h, a, l, season=None: {"1": 0.55, "X": 0.25, "2": 0.20}
        righe = self._righe(cur_elo, leg_elo)
        self.assertEqual({MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY, "mercato",
                          "senza_quote"}, set(righe))
        # senza l'indice delle quote (quote=None, come nel replay walk-forward)
        # la tabella di mercato e' vuota e non viene segnalata nessuna partita:
        # non e' "senza quote", e' "quote non richieste".
        self.assertEqual([], righe["mercato"])
        self.assertEqual([], righe["senza_quote"])
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
        cur_elo = lambda h, a, l, season=None: {"1": 0.70, "X": 0.18, "2": 0.12}
        leg_elo = lambda h, a, l, season=None: {"1": 0.20, "X": 0.30, "2": 0.50}
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
        cur_elo = lambda h, a, l, season=None: {"1": 0.70, "X": 0.18, "2": 0.12}
        leg_elo = lambda h, a, l, season=None: {"1": 0.48, "X": 0.28, "2": 0.24}
        righe = self._righe(cur_elo, leg_elo)
        cur = {r["match_id"] for r in righe[MODEL_VARIANT_CURRENT]}
        leg = {r["match_id"] for r in righe[MODEL_VARIANT_LEGACY]}
        self.assertIn(1, cur)
        self.assertNotIn(1, leg)

    def test_totali_identici_e_legacy_in_errore_isolato(self):
        """Elo legacy che solleva: la riga legacy resta Poisson puro (soglia 0,60),
        quella current non ne risente. Nessuna delle due tabelle contiene un Totale."""
        cur_elo = lambda h, a, l, season=None: {"1": 0.70, "X": 0.18, "2": 0.12}

        def leg_elo(h, a, l):
            raise RuntimeError("legacy rotto")

        righe = self._righe(cur_elo, leg_elo)
        cur = {r["match_id"]: r for r in righe[MODEL_VARIANT_CURRENT]}
        leg = {r["match_id"]: r for r in righe[MODEL_VARIANT_LEGACY]}
        self.assertTrue(cur[1]["elo_disponibile"])
        for r in leg.values():
            self.assertFalse(r["elo_disponibile"])
            self.assertAlmostEqual(r["prob"], r["poisson"] / 100.0, places=3)   # poisson e' arrotondato a 1 decimale
        for riga in list(cur.values()) + list(leg.values()):
            self.assertTrue(riga["market"].startswith(("Vittoria", "Pareggio")), riga["market"])


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

        elo = lambda h, a, l, season=None: {"1": 0.70, "X": 0.18, "2": 0.12}
        with mock.patch.object(app.requests, "get", return_value=_Resp()), \
             mock.patch.object(app, "get_league_engine", return_value=_engine(stats)), \
             mock.patch.object(app, "predict_elo_probs", side_effect=elo), \
             mock.patch.object(app, "predict_elo_probs_legacy", side_effect=elo), \
             mock.patch.object(app, "select_next_matchday_matches", side_effect=lambda m, now=None: m), \
             mock.patch.object(app, "_roster_stagione", return_value=None), \
             mock.patch.object(app, "carica_indice_quote_live",
                               return_value={"stato": mo.STATO_ASSENTE,
                                             "indice": None}), \
             mock.patch.object(app.time, "sleep", lambda s: None):
            app.fetch_and_calc_top_mix.clear()
            (top_mercato, top_current, top_legacy, missing, ombra,
             senza_quote) = app.fetch_and_calc_top_mix()
        n_leghe = len(app.LEAGUES_CONFIG)
        # Questo test riguarda il TETTO delle tabelle, non le quote: il file
        # delle quote viene dichiarato assente (``carica_indice_quote_live``
        # intercettata), cosi' l'esito non dipende dal fatto che la macchina
        # abbia o no database/live_odds.json - che in CI ADESSO c'e', perche' il
        # workflow delle quote lo committa. Senza il file non ci sono righe di
        # mercato. "Quote non richieste" (file assente) NON e' lo stesso di
        # "partita senza quote": nel secondo caso la partita entra in
        # senza_quote ed e' segnalata per nome (verificato in
        # test_topmix_mercato.py con un file di quote simulato).
        self.assertEqual([], top_mercato)
        self.assertEqual([], senza_quote)
        self.assertEqual([], missing)
        # registro ombra: DUE scelte per ogni partita candidata (migliore O/U 2.5 e migliore
        # GG/NG, ciascuna con la sua confidence), anche se non mostrate
        self.assertEqual(2 * 40 * n_leghe, len(ombra))
        self.assertEqual({"ou25", "ggng"}, {r["famiglia"] for r in ombra})
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

    def test_una_sola_tabella_quella_di_mercato(self):
        """Commessa 'quote live', punto 4: NESSUNA tabella visibile dei modelli."""
        self.assertIn("_mostra_tabella_top_mix_mercato(top_mercato, stato_quote)", self.tab2)
        self.assertIn("calcolatore_multipla(top_mercato)", self.tab2)
        # la vecchia tabella dei modelli non esiste piu' (ne' la chiamata, ne' i
        # titoli etichettati per motore)
        self.assertNotIn("_mostra_tabella_top_mix(", self.tab2)
        self.assertNotIn('f"🟢 {NOMI_MODELLI[MODEL_VARIANT_CURRENT]}"', self.tab2)
        self.assertNotIn('f"🟠 {NOMI_MODELLI[MODEL_VARIANT_LEGACY]}"', self.tab2)

    def test_il_registro_visibile_prende_solo_le_scelte_di_mercato(self):
        self.assertIn("args_reg, kwargs_reg = argomenti_registro_top_mix_mercato(p)", self.tab2)
        self.assertIn("save_prediction_entry(*args_reg, **kwargs_reg)", self.tab2)
        self.assertEqual(1, self.tab2.count("save_prediction_entry("),
                         "un solo punto di scrittura per il Registro visibile")
        self.assertIn("for p in top_mercato:", self.tab2)
        self.assertNotIn("for variante, righe_tab in (", self.tab2)
        self.assertNotIn("[:10]", self.tab2)
        self.assertNotIn("ricostru", self.tab2.lower())

    def test_le_scelte_dei_due_modelli_vanno_ancora_nel_registro_ombra(self):
        """Punto 6: Drago e Legacy non spariscono, passano in ``sm:registro:ombra``."""
        self.assertIn("esito_ombra = salva_registro_ombra(", self.tab2)
        self.assertIn("righe_modello={MODEL_VARIANT_CURRENT: top_current,", self.tab2)
        self.assertIn("MODEL_VARIANT_LEGACY: top_legacy}", self.tab2)
        # le righe dei due motori NON entrano nel Registro visibile
        self.assertNotIn("save_prediction_entry(*args_reg, **kwargs_reg)\n        for p in top_current",
                         self.tab2)

    def test_partite_senza_quote_e_file_assente_sono_segnalate(self):
        """Punto 3: niente quote -> esclusione SEGNALATA, mai silenziosa."""
        self.assertIn("if senza_quote:", self.tab2)
        self.assertIn("partite SENZA quote di mercato", self.tab2)
        self.assertIn("{r['home']} vs {r['away']} ({r['league']}: {r['motivo']})", self.tab2)
        # Lo stato del file ha un messaggio per ogni caso (assente / non
        # leggibile / senza_leghe / ok): il testo sta in
        # _DETTAGLIO_STATO_QUOTE, qui si verifica che il tab2 lo usi e che
        # mostri anche i nomi della fonte non riconosciuti (avviso separato).
        self.assertIn('_avviso_stato_quote(stato_quote, "Top Mix")', self.tab2)
        self.assertIn('_mostra_non_abbinati_fonte(stato_quote, "Top Mix")', self.tab2)
        self.assertNotIn("Quote dal vivo ASSENTI", self.tab2,
                         "il testo unico 'non c'e\'' e' sostituito dai messaggi per stato")
        stati_guasti = (mo.STATO_ASSENTE, mo.STATO_NON_LEGGIBILE, mo.STATO_SENZA_LEGHE)
        self.assertEqual(3, len({app._DETTAGLIO_STATO_QUOTE[s] for s in stati_guasti}),
                         "tre stati, tre messaggi diversi")
        # solo lo stato "assente" dice che il file non esiste: gli altri due
        # devono dire che il file C'E' (nasconderlo farebbe cercare nel posto
        # sbagliato)
        self.assertIn("non esiste", app._DETTAGLIO_STATO_QUOTE[mo.STATO_ASSENTE])
        for stato in (mo.STATO_NON_LEGGIBILE, mo.STATO_SENZA_LEGHE):
            self.assertIn("ESISTE", app._DETTAGLIO_STATO_QUOTE[stato], stato)

    def test_filtro_riga_iniziata_su_tutte_le_liste(self):
        for nome in ("top_mercato", "top_current", "top_legacy", "ombra", "senza_quote"):
            self.assertIn(f"righe_non_iniziate({nome})", self.tab2, nome)


if __name__ == "__main__":
    unittest.main()
