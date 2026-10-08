"""Totali fuori dal Top Mix visibile, registrati in OMBRA (PR "Totali fuori dal Top Mix").

Motivazione misurata (non opinione): ``audit/results/totals_market_ceiling.md`` §11a
(BSS Over/Under 2.5 del modello +0,0084 contro +0,0337 della chiusura B365; GG/NG sotto
il base rate), ``audit/results/ev_and_baserate_fix.md`` (PR #34), e i Totali = 39,7%
delle righe ammesse in ``audit/results/topmix_selector_replay.md``.

Cosa viene provato:

* ``righe_ombra_totali``: DUE scelte per candidata, la migliore O/U 2.5 e la migliore
  GG/NG, ciascuna con la sua confidence (Poisson, nessun Elo), l'ammissione a 0,60
  (bordo incluso), e ``vincente_globale`` = il selettore a sette mercati l'avrebbe
  davvero mostrato;
* ``calcola_righe_top_mix(..., ombra=...)``: DUE righe ombra per partita candidata,
  nessun Totale nelle due tabelle visibili, e la firma senza ``ombra`` invariata;
* ``build_ombra_entry``: stessa forma del registro + marcatori ``ombra_*``, origine e
  versione dedicate, chiave di dedup DIVERSA da quella della riga visibile;
* ``upsert_prediction_entries``: stessa semantica di ``upsert_prediction_entry`` in
  sequenza; mai sovrascritta una riga visibile o gia' giudicata;
* statistiche e calibrazione: l'ombra non entra mai nei numeri visibili;
* ``registry_store``: hash separato, letture visibili che non toccano l'ombra,
  guardia contro la collisione con il Registro vivo, nessuna scrittura su JSONBin;
* ``salva_registro_ombra`` e grading: scrittura diff, lettura strict, stessa logica
  di grading del Registro visibile con una sola serie di chiamate HTTP;
* versioni: Top Mix visibile = v2 (solo 1X2); Analisi Rapida e Billy = v1, invariate.
"""
from __future__ import annotations

import ast
import contextlib
import copy
import json
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
import registry_store as rs  # noqa: E402
import prediction_registry as R  # noqa: E402

APP_PATH = os.path.join(HERE, "app.py")


# ----------------------------------------------------------------- fabbriche
def _m(p1=0.20, pX=0.15, p2=0.10, over=0.40, gg=0.50):
    """Vettore Poisson come ``get_full_poisson_two_heads``: Over = 1 - u25, GG = gg."""
    return {"1": p1, "X": pX, "2": p2, "u25": 1.0 - over, "gg": gg}


def _partita(mid, home="Casa", away="Trasferta", utc="2026-10-17T18:45:00Z", md=7):
    return {"id": mid, "matchday": md, "utcDate": utc,
            "homeTeam": {"shortName": home}, "awayTeam": {"shortName": away}}


def _visibile(mid, origin=R.ORIGIN_TOP_MIX, sel=R.SELECTOR_VERSION_CURRENT, market="Vittoria Casa",
              mkt="1", prob=61.0, esito="⏳"):
    """Riga visibile costruita dal codice vero (stessa forma del registro)."""
    e = app.build_prediction_entry(
        mid, "Casa", "Trasferta", "Serie A", 7, "17/10/2026 20:45", f"{market} - Top Mix", [],
        prob, "", mercato_standard=mkt, origin=origin, rank=1, kickoff_utc="2026-10-17T18:45:00Z",
        prob_poisson=58.0, prob_elo=62.0, elo_disponibile=True, snapshot_sha="sha-test",
        salvato_il="08/10/2026 19:00", selector_version=sel)
    e["esito"] = esito
    return e


def _riga_ombra(mid, market="Over 2.5", conf=0.66, ammessa=True, vincente=True, dati=False):
    famiglia = R.OMBRA_FAMIGLIA_GGNG if market in ("GG", "NG") else R.OMBRA_FAMIGLIA_OU25
    return {"league": "Serie A", "giornata": 7, "home": "Casa", "away": "Trasferta",
            "match_id": mid, "utcDate": "2026-10-17T18:45:00Z", "market": market,
            "mercato_standard": app.codice_mercato_selezionato(market, "Casa", "Trasferta"),
            "confidence": conf, "poisson": conf, "ammessa": ammessa,
            "vincente_globale": vincente, "famiglia": famiglia, "dati_mancanti": dati}


def _scelta(m, famiglia, home="Casa", away="Trasferta"):
    """La riga ombra di una famiglia ("ou25" | "ggng") calcolata dal codice vero."""
    return next(r for r in app.righe_ombra_totali(m, home, away) if r["famiglia"] == famiglia)


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p


class _FakeUpstash:
    """Sostituto di ``requests.post`` verso Upstash: registra i comandi, risponde ``result``."""

    def __init__(self, hash_values=None):
        self.comandi = []
        self.hash_values = hash_values or []   # lista piatta [campo, valore, ...] (forma RESP2)

    def __call__(self, url, json=None, headers=None, timeout=None):
        comando = json
        self.comandi.append(comando)
        if comando[0] == "HGETALL":
            return _Resp({"result": list(self.hash_values)})
        if comando[0] == "HSET":
            return _Resp({"result": (len(comando) - 2) // 2})
        return _Resp({"result": None})


_ENV_UPSTASH = {"UPSTASH_REDIS_REST_URL": "https://example.upstash.io",
                "UPSTASH_REDIS_REST_TOKEN": "token-di-test",
                "REGISTRY_BACKEND": "upstash"}


class RipristinaLogging:
    """Alcuni moduli di test dell'audit chiamano ``logging.disable(CRITICAL)`` a import
    time, e l'import avviene prima di tutti i test: nella suite completa i WARNING sono
    spenti. Qui il contratto in prova E' il WARNING, quindi il setUp lo riabilita e il
    tearDown rimette ESATTAMENTE lo stato trovato (stesso schema di test_fallback_nomi.py)."""

    def setUp(self):
        self._disable_precedente = logging.root.manager.disable
        logging.disable(logging.NOTSET)

    def tearDown(self):
        logging.disable(self._disable_precedente)


# ============================================================ 1. scelta ombra
class TestRigaOmbraTotali(unittest.TestCase):
    """Due scelte per candidata: la migliore O/U 2.5 e la migliore GG/NG (round 2)."""

    def test_restituisce_sempre_due_righe_una_per_famiglia(self):
        righe = app.righe_ombra_totali(_m(over=0.70, gg=0.45), "Casa", "Trasferta")
        self.assertEqual(2, len(righe))
        self.assertEqual({R.OMBRA_FAMIGLIA_OU25, R.OMBRA_FAMIGLIA_GGNG}, {r["famiglia"] for r in righe})

    def test_ou25_sceglie_over_o_under_piu_probabile(self):
        r = _scelta(_m(over=0.70, gg=0.45), R.OMBRA_FAMIGLIA_OU25)
        self.assertEqual("Over 2.5", r["market"])
        self.assertAlmostEqual(0.70, r["confidence"], places=12)
        self.assertEqual("OVER_2.5", r["mercato_standard"])
        r_under = _scelta(_m(over=0.30, gg=0.45), R.OMBRA_FAMIGLIA_OU25)
        self.assertEqual("Under 2.5", r_under["market"])
        self.assertAlmostEqual(0.70, r_under["confidence"], places=12)

    def test_ggng_sceglie_gg_o_ng_piu_probabile(self):
        self.assertEqual("GG", _scelta(_m(gg=0.80), R.OMBRA_FAMIGLIA_GGNG)["mercato_standard"])
        r = _scelta(_m(gg=0.20), R.OMBRA_FAMIGLIA_GGNG)
        self.assertEqual("NG", r["market"])
        self.assertEqual("NG", r["mercato_standard"])
        self.assertAlmostEqual(0.80, r["confidence"], places=12)

    def test_soglia_0_60_bordo_incluso_per_ciascuna_famiglia(self):
        self.assertTrue(_scelta(_m(over=0.60), R.OMBRA_FAMIGLIA_OU25)["ammessa"])
        self.assertFalse(_scelta(_m(over=0.5999), R.OMBRA_FAMIGLIA_OU25)["ammessa"])
        self.assertTrue(_scelta(_m(gg=0.60), R.OMBRA_FAMIGLIA_GGNG)["ammessa"])
        self.assertFalse(_scelta(_m(gg=0.5999), R.OMBRA_FAMIGLIA_GGNG)["ammessa"])

    def test_ammissione_di_una_famiglia_non_dipende_dall_altra(self):
        r = {x["famiglia"]: x for x in app.righe_ombra_totali(_m(over=0.62, gg=0.50), "Casa", "Trasferta")}
        self.assertTrue(r[R.OMBRA_FAMIGLIA_OU25]["ammessa"])
        self.assertFalse(r[R.OMBRA_FAMIGLIA_GGNG]["ammessa"])

    def test_soglia_della_riga_e_quella_del_selettore_dei_totali(self):
        self.assertEqual(0.60, R.OMBRA_SOGLIA_TOTALI)

    def test_vincente_globale_vero_se_il_totale_batte_tutti_i_1x2(self):
        r = _scelta(_m(p1=0.20, pX=0.15, p2=0.10, over=0.62), R.OMBRA_FAMIGLIA_OU25)
        self.assertTrue(r["ammessa"])
        self.assertTrue(r["vincente_globale"])

    def test_vincente_globale_falso_se_un_1x2_e_piu_probabile(self):
        """Over 0,62 ma il 1X2 casa 0,65: il vecchio selettore avrebbe mostrato il 1X2, non l'Over."""
        r = _scelta(_m(p1=0.65, pX=0.15, p2=0.10, over=0.62), R.OMBRA_FAMIGLIA_OU25)
        self.assertEqual("Over 2.5", r["market"])
        self.assertTrue(r["ammessa"])
        self.assertFalse(r["vincente_globale"])

    def test_vincente_globale_falso_se_non_ammessa(self):
        r = _scelta(_m(p1=0.20, pX=0.15, p2=0.10, over=0.59), R.OMBRA_FAMIGLIA_OU25)
        self.assertFalse(r["ammessa"])
        self.assertFalse(r["vincente_globale"])

    def test_non_scarta_mai_e_non_legge_l_elo(self):
        firma = list(ast.parse(open(APP_PATH, encoding="utf-8").read()).body)
        fn = next(n for n in firma if isinstance(n, ast.FunctionDef) and n.name == "righe_ombra_totali")
        self.assertEqual(["m", "home", "away"], [a.arg for a in fn.args.args])
        self.assertIsInstance(app.righe_ombra_totali(_m(over=0.1), "Casa", "Trasferta"), list)


# ============================================ 2. calcolo per partita (tabelle)
class TestCalcolaConOmbra(unittest.TestCase):
    """Stesso codice di produzione, con Poisson ed Elo fissati per partita."""

    def _esegui(self, partite, poisson_per_id, elo_per_id, ombra=True):
        def poisson(h_s, a_s, avg_h, avg_a):
            return dict(poisson_per_id[h_s["mid"]])

        def elo(h, a, league, season=None):
            v = elo_per_id[h]
            if isinstance(v, Exception):
                raise v
            return v

        stats = {}
        for mid, (home, away) in partite.items():
            stats[app.clean_name(home)] = {"att": 1.0, "def": 1.0, "mid": mid}
            stats[app.clean_name(away)] = {"att": 1.0, "def": 1.0, "mid": mid}
        matches = [_partita(mid, home, away) for mid, (home, away) in partite.items()]
        lista = [] if ombra else None
        with mock.patch.object(app, "get_full_poisson_two_heads", side_effect=poisson), \
             mock.patch.object(app, "predict_elo_probs", side_effect=elo), \
             mock.patch.object(app, "predict_elo_probs_legacy", side_effect=elo), \
             mock.patch.object(app, "_roster_stagione", return_value=None):
            righe = app.calcola_righe_top_mix("Serie A", matches, (stats, 1.5, 1.2, {}), ombra=lista)
        return righe, lista

    def test_una_riga_ombra_per_ogni_candidata_e_nessun_totale_visibile(self):
        partite = {1: ("Casa1", "Trasferta1"), 2: ("Casa2", "Trasferta2"), 3: ("Casa3", "Trasferta3")}
        poisson = {1: _m(p1=0.20, pX=0.15, p2=0.10, over=0.70),   # Totale forte, nessun 1X2 ammesso
                   2: _m(p1=0.58, pX=0.22, p2=0.20, over=0.80),   # Totale forte, 1X2 ammesso: rivalutata
                   3: _m(p1=0.60, pX=0.20, p2=0.20, over=0.30, gg=0.40)}  # 1X2 argmax
        elo = {"Casa1": {"1": 0.20, "X": 0.15, "2": 0.10},
               "Casa2": {"1": 0.58, "X": 0.22, "2": 0.20},
               "Casa3": {"1": 0.60, "X": 0.20, "2": 0.20}}
        righe, ombra = self._esegui(partite, poisson, elo)
        # DUE scelte ombra per partita candidata (O/U 2.5 e GG/NG), anche quando la visibile non c'e'
        self.assertEqual([1, 1, 2, 2, 3, 3], sorted(r["match_id"] for r in ombra))
        self.assertEqual({(mid, f) for mid in (1, 2, 3) for f in (R.OMBRA_FAMIGLIA_OU25, R.OMBRA_FAMIGLIA_GGNG)},
                         {(r["match_id"], r["famiglia"]) for r in ombra})
        visibili = {r["market"] for r in righe[R.MODEL_VARIANT_CURRENT]}
        for totale in ("Over 2.5", "Under 2.5", "GG", "NG"):
            self.assertNotIn(totale, visibili)
        self.assertEqual({2, 3}, {r["match_id"] for r in righe[R.MODEL_VARIANT_CURRENT]})

    def test_partita_rivalutata_ha_visibile_1x2_e_ombra_che_avrebbe_mostrato_il_totale(self):
        partite = {2: ("Casa2", "Trasferta2")}
        poisson = {2: _m(p1=0.58, pX=0.22, p2=0.20, over=0.80)}
        elo = {"Casa2": {"1": 0.58, "X": 0.22, "2": 0.20}}
        righe, ombra = self._esegui(partite, poisson, elo)
        self.assertEqual(["Vittoria Casa2"], [r["market"] for r in righe[R.MODEL_VARIANT_CURRENT]])
        self.assertEqual(2, len(ombra))
        ou = next(r for r in ombra if r["famiglia"] == R.OMBRA_FAMIGLIA_OU25)
        self.assertEqual("Over 2.5", ou["market"])
        self.assertTrue(ou["ammessa"])
        self.assertTrue(ou["vincente_globale"])           # il vecchio selettore lo avrebbe mostrato

    def test_firma_senza_ombra_invariata(self):
        partite = {5: ("Casa5", "Trasferta5")}
        poisson = {5: _m(p1=0.60, pX=0.20, p2=0.20, over=0.30)}
        elo = {"Casa5": {"1": 0.60, "X": 0.20, "2": 0.20}}
        con, _ = self._esegui(partite, poisson, elo, ombra=True)
        senza, _ = self._esegui(partite, poisson, elo, ombra=False)
        self.assertEqual(con, senza)

    def test_elo_legacy_rotto_non_cambia_la_riga_ombra(self):
        partite = {7: ("Casa7", "Trasferta7")}
        poisson = {7: _m(p1=0.20, pX=0.15, p2=0.10, over=0.70)}
        elo = {"Casa7": RuntimeError("elo rotto")}
        _righe, ombra = self._esegui(partite, poisson, elo)
        ou = next(r for r in ombra if r["famiglia"] == R.OMBRA_FAMIGLIA_OU25)
        self.assertEqual("Over 2.5", ou["market"])
        self.assertAlmostEqual(0.70, ou["confidence"], places=12)


# ====================================================== 3. forma del record
class TestBuildOmbraEntry(unittest.TestCase):

    def setUp(self):
        self.riga = _riga_ombra(42, dati=True)
        self.entry = app.build_ombra_entry(self.riga, salvato_il="08/10/2026 19:00", snapshot_sha="sha-test")

    def test_stessa_forma_della_riga_visibile_piu_i_marcatori_ombra(self):
        visibile = _visibile(42)
        extra = set(self.entry) - set(visibile)
        self.assertEqual({R.OMBRA_FIELD, R.OMBRA_FAMIGLIA_FIELD, R.OMBRA_MERCATO_FIELD, R.OMBRA_CONFIDENCE_FIELD,
                          R.OMBRA_AMMESSA_FIELD, R.OMBRA_SOGLIA_FIELD,
                          R.OMBRA_VINCENTE_GLOBALE_FIELD, R.OMBRA_DATI_MANCANTI_FIELD}, extra)
        self.assertEqual(set(visibile), set(self.entry) - extra)

    def test_marcatori_e_origine_dedicata(self):
        self.assertIs(True, self.entry[R.OMBRA_FIELD])
        self.assertEqual("top_mix_ombra", self.entry["origin"])
        self.assertEqual("Top Mix ombra", self.entry["tipo"])
        self.assertEqual(R.SELECTOR_VERSION_OMBRA_OU25, self.entry["selector_version"])
        self.assertEqual(R.OMBRA_FAMIGLIA_OU25, self.entry[R.OMBRA_FAMIGLIA_FIELD])
        self.assertEqual("Over 2.5", self.entry[R.OMBRA_MERCATO_FIELD])
        self.assertEqual("OVER_2.5", self.entry["mercato_standard"])
        self.assertAlmostEqual(0.66, self.entry[R.OMBRA_CONFIDENCE_FIELD], places=6)
        self.assertIs(True, self.entry[R.OMBRA_AMMESSA_FIELD])
        self.assertEqual(0.60, self.entry[R.OMBRA_SOGLIA_FIELD])
        self.assertIs(True, self.entry[R.OMBRA_VINCENTE_GLOBALE_FIELD])
        self.assertIs(True, self.entry[R.OMBRA_DATI_MANCANTI_FIELD])
        self.assertIsNone(self.entry["rank"])
        self.assertEqual("⏳", self.entry["esito"])

    def test_chiave_di_dedup_diversa_dalla_riga_visibile_della_stessa_partita(self):
        visibile = _visibile(42)
        self.assertNotEqual(R.dedup_key(self.entry), R.dedup_key(visibile))
        self.assertEqual("42", R.dedup_key(self.entry)[0])

    def test_una_riga_visibile_resta_identica_dopo_l_aggiunta_dell_ombra(self):
        visibile = _visibile(42)
        lista, azione = R.upsert_prediction_entry([copy.deepcopy(visibile)], self.entry)
        self.assertEqual("aggiunta", azione)
        self.assertEqual(visibile, lista[0])
        self.assertIs(True, lista[1][R.OMBRA_FIELD])


# ================================================ 4. upsert in blocco
class TestUpsertInBlocco(unittest.TestCase):

    def _sequenziale(self, preds, entries):
        lista = list(preds)
        azioni = []
        for e in entries:
            lista, a = R.upsert_prediction_entry(lista, e)
            azioni.append(a)
        return lista, azioni

    def test_stesso_esito_della_sequenza_su_casi_misti(self):
        esistenti = [_visibile(1), _visibile(2, esito="✅"),
                     app.build_ombra_entry(_riga_ombra(3), snapshot_sha="s"),
                     app.build_ombra_entry(_riga_ombra(4), snapshot_sha="s")]
        esistenti[3]["esito"] = "❌"
        entries = [app.build_ombra_entry(_riga_ombra(5), snapshot_sha="s"),       # nuova
                   app.build_ombra_entry(_riga_ombra(3, conf=0.71), snapshot_sha="s"),  # aggiornata
                   app.build_ombra_entry(_riga_ombra(4, conf=0.72), snapshot_sha="s"),  # gia' giudicata
                   app.build_ombra_entry(_riga_ombra(5, conf=0.73), snapshot_sha="s"),  # stessa chiave nel blocco
                   _visibile(2, mkt="2", market="Vittoria Trasferta")]               # visibile gia' giudicata
        lista_b, azioni_b = R.upsert_prediction_entries(copy.deepcopy(esistenti), copy.deepcopy(entries))
        lista_s, azioni_s = self._sequenziale(copy.deepcopy(esistenti), copy.deepcopy(entries))
        self.assertEqual(lista_s, lista_b)
        self.assertEqual(["aggiunta", "aggiornata", "gia_graduata", "aggiornata", "gia_graduata"],
                         azioni_s)
        self.assertEqual({"aggiunta": 1, "aggiornata": 2, "gia_graduata": 2}, azioni_b)

    def test_una_riga_visibile_non_viene_mai_toccata_dal_blocco_ombra(self):
        visibile = _visibile(10)
        lista, _ = R.upsert_prediction_entries([copy.deepcopy(visibile)],
                                               [app.build_ombra_entry(_riga_ombra(10), snapshot_sha="s")])
        self.assertEqual(visibile, lista[0])
        self.assertEqual(2, len(lista))

    def test_aggiornamento_conserva_il_salvato_il_originario(self):
        vecchia = app.build_ombra_entry(_riga_ombra(11), salvato_il="08/10/2026 18:00", snapshot_sha="s")
        nuova = app.build_ombra_entry(_riga_ombra(11, conf=0.64), salvato_il="08/10/2026 19:30", snapshot_sha="s")
        lista, azioni = R.upsert_prediction_entries([vecchia], [nuova])
        self.assertEqual({"aggiornata": 1}, azioni)
        self.assertEqual("08/10/2026 18:00", lista[0]["salvato_il_originario"])
        self.assertAlmostEqual(0.64, lista[0][R.OMBRA_CONFIDENCE_FIELD], places=6)


# ============================================ 5. statistiche senza ombra
class TestStatisticheSenzaOmbra(unittest.TestCase):

    def _misto(self):
        visibili = [_visibile(1, esito="✅"), _visibile(2, esito="❌")]
        ombre = [app.build_ombra_entry(_riga_ombra(3), snapshot_sha="s"),
                 app.build_ombra_entry(_riga_ombra(4), snapshot_sha="s")]
        ombre[0]["esito"] = "✅"
        ombre[1]["esito"] = "✅"
        return visibili + ombre

    def test_is_ombra_per_marcatore_e_per_origine(self):
        misto = self._misto()
        self.assertEqual([False, False, True, True], [R.is_ombra(e) for e in misto])
        solo_origine = {"match_id": 9, "origin": "top_mix_ombra", "esito": "✅"}
        self.assertTrue(R.is_ombra(solo_origine))
        self.assertFalse(R.is_ombra({"match_id": 9, "origin": "top_mix"}))

    def test_statistiche_e_calibrazione_escludono_l_ombra(self):
        misto = self._misto()
        self.assertEqual(2, R.compute_stats(misto)["total"])
        self.assertEqual(1, R.compute_stats(misto)["losses"])
        self.assertEqual(2, R.stats_all(misto)["total"])
        self.assertEqual(2, R.compute_calibration_stats(misto)["total"])
        self.assertEqual(2, R.compute_calibration_stats(misto)["decise"])
        self.assertEqual([], [r for r in R.calibration_by_mercato(misto, min_decise=1)
                              if r["origine"] == "top_mix_ombra"])
        self.assertEqual([1, 2], [e["match_id"] for e in R.righe_visibili(misto)])

    def test_stats_correnti_non_contano_l_ombra(self):
        misto = self._misto()
        self.assertEqual(2, R.stats_current_model(misto)["total"])


# ============================================ 6. storage: hash separato
class TestStoreOmbra(unittest.TestCase):

    def test_hash_ombra_di_default_separato_dal_vivo(self):
        with mock.patch.dict(os.environ, {"REGISTRY_SHADOW_HASH_KEY": "", "REGISTRY_HASH_KEY": ""}):
            self.assertEqual("sm:registro:ombra", rs.shadow_hash_key())
            self.assertNotEqual(rs.hash_key(), rs.shadow_hash_key())

    def test_collisione_con_il_vivo_o_con_gli_snapshot_si_rifiuta(self):
        for valore in ("sm:registro", "sm:registro:snapshot:2026-10-08"):
            with mock.patch.dict(os.environ, {"REGISTRY_SHADOW_HASH_KEY": valore}):
                with self.assertRaises(rs.RegistryStoreError):
                    rs.shadow_hash_key()

    def test_letture_visibili_non_toccano_la_chiave_ombra(self):
        fake = _FakeUpstash()
        with mock.patch.dict(os.environ, _ENV_UPSTASH):
            rs.load_rows(strict=True, post=fake)
        self.assertEqual([["HGETALL", "sm:registro"]], fake.comandi)

    def test_lettura_e_scrittura_ombra_usano_solo_la_chiave_ombra(self):
        fake = _FakeUpstash()
        riga = app.build_ombra_entry(_riga_ombra(77), snapshot_sha="s")
        with mock.patch.dict(os.environ, _ENV_UPSTASH):
            rs.load_ombra_rows(strict=True, post=fake)
            rs.save_ombra_rows([riga], post=fake)
        chiavi = {c[1] for c in fake.comandi}
        self.assertEqual({"sm:registro:ombra"}, chiavi)
        # lettura: una HGETALL; scrittura: una HGETALL per il diff + una HSET (solo le righe nuove)
        self.assertEqual(["HGETALL", "HGETALL", "HSET"], [c[0] for c in fake.comandi])

    def test_scrittura_ombra_solo_delle_righe_nuove_o_cambiate(self):
        riga = app.build_ombra_entry(_riga_ombra(78), snapshot_sha="s")
        valore = json.dumps(riga, ensure_ascii=False, sort_keys=True, default=str)
        fake = _FakeUpstash(hash_values=[rs.field_of(riga), valore])
        with mock.patch.dict(os.environ, _ENV_UPSTASH):
            esito = rs.save_ombra_rows([riga], post=fake)
        self.assertEqual(1, esito["righe_saltate"])
        self.assertEqual(["HGETALL"], [c[0] for c in fake.comandi])

    def test_con_jsonbin_il_registro_ombra_non_esiste(self):
        with mock.patch.dict(os.environ, {"REGISTRY_BACKEND": "jsonbin"}):
            with self.assertRaises(rs.RegistryStoreError):
                rs.load_ombra_rows(strict=True)
            self.assertEqual({"remoto": "non_supportato", "backend": "jsonbin", "righe_scritte": 0},
                             rs.save_ombra_rows([{"match_id": 1}]))

    def test_chiave_di_campo_ombra_diversa_dalla_visibile(self):
        ombra = app.build_ombra_entry(_riga_ombra(79), snapshot_sha="s")
        self.assertNotEqual(rs.field_of(_visibile(79)), rs.field_of(ombra))


# ======================================== 7. scrittura e grading dell'ombra
class TestSalvaRegistroOmbra(RipristinaLogging, unittest.TestCase):

    def _store(self, esistenti, load_raise=None):
        """(load_mock, save_mock, patch_contextmanager): lo store finto del registro ombra."""
        salvate = []

        def load(strict=True, post=None):
            if load_raise:
                raise load_raise
            return copy.deepcopy(esistenti), "upstash"

        def save(righe, post=None):
            salvate.append(copy.deepcopy(righe))
            return {"remoto": "ok", "backend": "upstash", "righe_scritte": len(righe)}

        load_m, save_m = mock.Mock(side_effect=load), mock.Mock(side_effect=save)
        patch = contextlib.ExitStack()
        patch.enter_context(mock.patch.object(rs, "load_ombra_rows", load_m))
        patch.enter_context(mock.patch.object(rs, "save_ombra_rows", save_m))
        patch.enter_context(mock.patch.object(app, "snapshot_fingerprint", return_value="sha"))
        return load_m, save_m, salvate, patch

    def test_nessuna_candidata_non_legge_nemmeno(self):
        load_m, save_m, _salvate, patch = self._store([])
        with patch:
            esito = app.salva_registro_ombra([])
        self.assertEqual("nessuna_riga", esito["remoto"])
        load_m.assert_not_called()
        save_m.assert_not_called()

    def test_prima_scrive_le_nuove_poi_il_secondo_click_aggiorna_senza_duplicare(self):
        candidate = [_riga_ombra(20), _riga_ombra(21, market="Under 2.5", conf=0.63)]
        _l, _s, salvate, patch = self._store([])
        with patch:
            primo = app.salva_registro_ombra(candidate)
        self.assertEqual("ok", primo["remoto"])
        self.assertEqual({"aggiunta": 2}, primo["azioni"])
        self.assertEqual(1, len(salvate))
        self.assertEqual({True}, {r[R.OMBRA_FIELD] for r in salvate[0]})
        # secondo click: lo store contiene gia' le due righe. Come per il Registro
        # visibile la riga non giudicata viene aggiornata (cambia salvato_il), mai duplicata.
        _l2, _s2, salvate2, patch2 = self._store(salvate[0])
        with patch2:
            secondo = app.salva_registro_ombra(candidate)
        self.assertEqual({"aggiornata": 2}, secondo["azioni"])
        self.assertEqual(1, len(salvate2))
        self.assertEqual(2, len(salvate2[0]))

    def test_errore_nella_costruzione_non_fa_fallire_il_click(self):
        """Il Top Mix visibile e' gia' salvato: un guasto dell'ombra resta dell'ombra."""
        _l, save_m, _salvate, patch = self._store([])
        with patch, mock.patch.object(app, "build_ombra_entry", side_effect=ValueError("riga rotta")), \
             self.assertLogs(level="WARNING"):
            esito = app.salva_registro_ombra([_riga_ombra(31)])
        self.assertEqual("errore", esito["remoto"])
        self.assertIn("riga rotta", esito["remoto_dettaglio"])
        save_m.assert_not_called()

    def test_lettura_fallita_non_scrive_niente(self):
        _l, save_m, _salvate, patch = self._store([], load_raise=rs.RegistryStoreError("Upstash giu'"))
        with patch:
            esito = app.salva_registro_ombra([_riga_ombra(30)])
        self.assertEqual("errore", esito["remoto"])
        save_m.assert_not_called()

    def test_riga_ombra_gia_giudicata_non_si_tocca(self):
        giudicata = app.build_ombra_entry(_riga_ombra(40), snapshot_sha="s")
        giudicata["esito"] = "✅"
        giudicata[R.OMBRA_CONFIDENCE_FIELD] = 0.61
        _l, save_m, _salvate, patch = self._store([giudicata])
        with patch:
            esito = app.salva_registro_ombra([_riga_ombra(40, conf=0.75)])
        self.assertEqual({"gia_graduata": 1}, esito["azioni"])
        save_m.assert_not_called()


class TestGradingOmbra(RipristinaLogging, unittest.TestCase):
    """Stesso grading del Registro visibile, con UNA sola serie di chiamate HTTP."""

    def _risposte(self, mapping):
        chiamate = []

        def get(url, headers=None, params=None, timeout=None):
            chiamate.append((url, params))
            return _Resp({"matches": mapping.get((url, json.dumps(params, sort_keys=True)), [])})

        return chiamate, get

    def test_stesso_esito_per_visibile_e_ombra_con_una_sola_chiamata_per_giornata(self):
        visibile = _visibile(50, market="Over 2.5", mkt="OVER_2.5", prob=60.0)
        ombra = app.build_ombra_entry(_riga_ombra(51, market="Over 2.5"), snapshot_sha="s")
        partita = {"id": 50, "score": {"fullTime": {"home": 2, "away": 1}}}
        partita_ombra = {"id": 51, "score": {"fullTime": {"home": 0, "away": 0}}}
        url = f"https://api.football-data.org/v4/competitions/{app.LEAGUE_CODE_MAP['Serie A']}/matches"
        chiamate, get = self._risposte({(url, json.dumps({"matchday": 7, "status": "FINISHED"}, sort_keys=True)):
                                        [partita, partita_ombra]})
        cache = {}
        with mock.patch.object(app.requests, "get", side_effect=get):
            ag1, pe1 = app._applica_esiti([visibile], "KEY", cache)
            ag2, pe2 = app._applica_esiti([ombra], "KEY", cache)
        self.assertEqual((1, 1), (ag1, pe1))
        self.assertEqual("✅", visibile["esito"])          # 3 gol > 2
        self.assertEqual("❌", ombra["esito"])             # 0 gol
        self.assertEqual(1, len(chiamate), "la seconda passata non deve rifare la GET")

    def test_aggiorna_risultati_visibili_invariato_e_ombra_nello_stesso_giro(self):
        visibile = _visibile(60, market="Vittoria Casa", mkt="1", prob=60.0)
        ombra = app.build_ombra_entry(_riga_ombra(61, market="Under 2.5"), snapshot_sha="s")
        url = f"https://api.football-data.org/v4/competitions/{app.LEAGUE_CODE_MAP['Serie A']}/matches"
        chiamate, get = self._risposte({(url, json.dumps({"matchday": 7, "status": "FINISHED"}, sort_keys=True)): [
            {"id": 60, "score": {"fullTime": {"home": 2, "away": 0}}},
            {"id": 61, "score": {"fullTime": {"home": 1, "away": 1}}}]})
        salvate_vis, salvate_omb = [], []
        with mock.patch.object(app, "load_predictions", return_value=[visibile]), \
             mock.patch.object(app, "save_predictions", side_effect=lambda p: salvate_vis.append(p)), \
             mock.patch.object(app.requests, "get", side_effect=get), \
             mock.patch.object(rs, "load_ombra_rows", return_value=([ombra], "upstash")), \
             mock.patch.object(rs, "save_ombra_rows",
                               side_effect=lambda righe, post=None: (salvate_omb.append(righe)
                                                                    or {"remoto": "ok"})):
            agg, pend = app.aggiorna_risultati_reali("KEY")
        self.assertEqual((1, 1), (agg, pend))
        self.assertEqual("✅", salvate_vis[0][0]["esito"])
        self.assertEqual("✅", ombra["esito"])            # Under 2.5 con 2 gol
        self.assertEqual(1, len(salvate_omb))
        self.assertEqual(1, len(chiamate))

    def test_guasto_dell_ombra_non_ferma_il_grading_visibile(self):
        visibile = _visibile(70, market="Vittoria Casa", mkt="1", prob=60.0)
        url = f"https://api.football-data.org/v4/competitions/{app.LEAGUE_CODE_MAP['Serie A']}/matches"
        _chiamate, get = self._risposte({(url, json.dumps({"matchday": 7, "status": "FINISHED"}, sort_keys=True)): [
            {"id": 70, "score": {"fullTime": {"home": 1, "away": 0}}}]})
        with mock.patch.object(app, "load_predictions", return_value=[visibile]), \
             mock.patch.object(app, "save_predictions", return_value={"remoto": "ok"}), \
             mock.patch.object(app.requests, "get", side_effect=get), \
             mock.patch.object(rs, "load_ombra_rows", side_effect=rs.RegistryStoreError("giu'")), \
             self.assertLogs(level="WARNING") as log:
            agg, pend = app.aggiorna_risultati_reali("KEY")
        self.assertEqual((1, 1), (agg, pend))
        self.assertTrue(any("registro ombra" in m for m in log.output), log.output)


# ============================================================ 8. versioni
class TestVersioni(unittest.TestCase):

    def test_costanti_di_versione(self):
        self.assertEqual("topmix_gate025_ens06_v1", R.SELECTOR_VERSION_PRE_1X2)
        self.assertEqual("topmix_1x2_gate025_ens06_v2", R.SELECTOR_VERSION_CURRENT)
        self.assertEqual("topmix_ombra_ou25_v1", R.SELECTOR_VERSION_OMBRA_OU25)
        self.assertEqual("topmix_ombra_ggng_v1", R.SELECTOR_VERSION_OMBRA_GGNG)
        self.assertEqual({R.OMBRA_FAMIGLIA_OU25: R.SELECTOR_VERSION_OMBRA_OU25,
                          R.OMBRA_FAMIGLIA_GGNG: R.SELECTOR_VERSION_OMBRA_GGNG},
                         R.SELECTOR_VERSION_OMBRA_BY_FAMIGLIA)
        self.assertEqual(4, len({R.SELECTOR_VERSION_PRE_1X2, R.SELECTOR_VERSION_CURRENT,
                                 R.SELECTOR_VERSION_OMBRA_OU25, R.SELECTOR_VERSION_OMBRA_GGNG}))

    def test_analisi_rapida_e_billy_restano_sulla_versione_storica(self):
        for origin in (R.ORIGIN_ANALISI_RAPIDA, R.ORIGIN_BILLY):
            e = app.build_prediction_entry(1, "A", "B", "Serie A", 1, "17/10/2026 20:45", "x", [], 60.0, "",
                                           origin=origin, snapshot_sha="s", salvato_il="08/10/2026 19:00")
            self.assertEqual(R.SELECTOR_VERSION_PRE_1X2, e["selector_version"], origin)
            self.assertEqual(R.build_calculation_id(1, origin, R.SELECTOR_VERSION_PRE_1X2, None, "s", None),
                             e["calculation_id"], origin)

    def test_top_mix_scritto_dal_percorso_di_salvataggio_usa_la_versione_nuova(self):
        e = app.build_prediction_entry(1, "A", "B", "Serie A", 1, "17/10/2026 20:45", "x", [], 60.0, "",
                                       origin=R.ORIGIN_TOP_MIX, snapshot_sha="s", salvato_il="08/10/2026 19:00")
        self.assertEqual(R.SELECTOR_VERSION_CURRENT, e["selector_version"])

    def test_argomenti_del_top_mix_portano_la_versione_corrente(self):
        riga = {"league": "Serie A", "giornata": 5, "home": "Inter", "away": "Roma", "match_id": 4242,
                "utcDate": "2026-10-03T18:45:00Z", "market": "Vittoria Inter", "mercato_standard": "1",
                "prob": 0.6123, "prob_val": 61.2, "poisson": 58.0, "elo": 62.3,
                "elo_disponibile": True, "rank": 3}
        _args, kwargs = app.argomenti_registro_top_mix(riga)
        self.assertEqual(R.SELECTOR_VERSION_CURRENT, kwargs["selector_version"])


# ============================================ 9. guardie sull'interfaccia
class TestGuardieInterfaccia(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.src = open(APP_PATH, encoding="utf-8").read()
        cls.tree = ast.parse(cls.src)

    def _tab(self, nome):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.With):
                for it in node.items:
                    if isinstance(it.context_expr, ast.Name) and it.context_expr.id == nome:
                        return node
        self.fail(f"blocco {nome} non trovato")

    def test_tab_registro_legge_solo_le_righe_visibili(self):
        self.assertIn("preds = righe_visibili(load_predictions())", self.src)

    def test_l_ombra_non_arriva_mai_alle_tabelle_ne_a_st(self):
        """Nel tab2 la variabile ``ombra`` puo' solo essere assegnata, filtrata o passata al salvataggio."""
        tab2 = self._tab("tab2")
        usi_ok = {"righe_non_iniziate", "salva_registro_ombra"}
        for node in ast.walk(tab2):
            if isinstance(node, ast.Call):
                nome = node.func.id if isinstance(node.func, ast.Name) else (
                    node.func.attr if isinstance(node.func, ast.Attribute) else "")
                passa_ombra = any(isinstance(a, ast.Name) and a.id == "ombra" for a in node.args)
                if passa_ombra:
                    self.assertIn(nome, usi_ok, f"`ombra` passata a {nome}(): potrebbe finire in UI")
                if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "st"):
                    self.assertFalse(passa_ombra, "`ombra` passata a st.*")

    def test_tab2_chiama_il_salvataggio_ombra_dopo_le_tabelle(self):
        tab2 = self._tab("tab2")
        chiamate = [n for n in ast.walk(tab2) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == "salva_registro_ombra"]
        self.assertEqual(1, len(chiamate))

    def test_calcola_richiamato_con_il_canale_ombra_una_sola_volta(self):
        self.assertEqual(1, self.src.count("calcola_righe_top_mix(league, matches, engine, ombra=ombra)"))


if __name__ == "__main__":
    unittest.main()
