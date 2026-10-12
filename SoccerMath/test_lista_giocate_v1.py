"""test_lista_giocate_v1.py — Test per la sezione Lista giocate (versione lista_giocate_v1).

Copre i requisiti della commessa:
1. Parità bit-a-bit delle probabilità di mercato con topmix_mercato_v3 su snapshot reale git.
2. Esclusione e conteggio partite già iniziate e senza quote valide.
3. 6 giocate per partita: 1, X, 2, 1X, X2, 12 con p(DC) = sum(p).
4. Stima quota bet365 1X2 (parity test con fit 2024/25 e test OOS 2025/26 errore mediano 1,36%).
5. Doppia chance: 1 / (1/qa + 1/qb) marcata 'stima non verificata'.
6. Ricerca esaustiva verificata contro forza bruta indipendente su insieme ridotto.
7. Casi limite: senza quote, una sola partita, nessuna combinazione in fascia.
8. Nessuna data fissa scritta a mano.
9. Registro ombra: famiglia multipla_proposta_v1, prima registrazione per settimana mai sovrascritta.
"""
from __future__ import annotations

import copy
import itertools
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import lista_giocate as lg
import market_odds as mo
import prediction_registry as pr


def _genera_evento_finto(match_id="m1", home="Casa", away="Trasferta", lega="Serie A",
                         commence_offset_hours=2.0, terna=(2.0, 3.2, 3.8)):
    now = datetime.now(timezone.utc)
    commence_dt = now + timedelta(hours=commence_offset_hours)
    return {
        "id": match_id,
        "home_team": home,
        "away_team": away,
        "lega": lega,
        "commence_time": commence_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "libri": [
            {
                "key": "pinnacle",
                "h2h": {"home": terna[0], "draw": terna[1], "away": terna[2]}
            }
        ]
    }


def _genera_payload_finto(eventi, generato_offset_hours=1.0):
    now = datetime.now(timezone.utc)
    gen_dt = now - timedelta(hours=generato_offset_hours)
    return {
        "schema": "soccermath_live_odds_v1",
        "generato_il": gen_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fonte": "the-odds-api",
        "regioni": "eu",
        "n_eventi": len(eventi),
        "leghe": {
            "Serie A": {"sport_key": "soccer_italy_serie_a", "eventi": eventi}
        }
    }


class TestParitaProbabilitaMercato(unittest.TestCase):
    """Verifica bit-per-bit delle probabilità di mercato (p1, pX, p2) rispetto a v3."""

    def test_parita_bit_per_bit_su_snapshot_reale_git(self):
        # Carica uno snapshot reale di live_odds.json dalla storia git (commit fc1b45e)
        try:
            raw = subprocess.check_output(
                ["git", "show", "fc1b45e:SoccerMath/database/live_odds.json"],
                stderr=subprocess.DEVNULL
            ).decode("utf-8")
            snapshot = json.loads(raw)
        except Exception as e:
            self.skipTest(f"Impossibile leggere snapshot da git: {e}")

        # Data dinamica prima della generazione dello snapshot per ammettere tutti gli eventi
        gen_dt = datetime.fromisoformat(snapshot["generato_il"].replace("Z", "+00:00"))
        t_ref = gen_dt - timedelta(hours=1.0)

        res = lg.calcola_lista_giocate(snapshot, adesso_utc=t_ref)
        self.assertGreater(res["n_partite_ammesse"], 0)

        # Mappa per partita delle giocate 1X2
        giocate_per_partita = {}
        for g in res["giocate"]:
            giocate_per_partita.setdefault(g["partita"], {})[g["giocata"]] = g["probabilita"]

        # Confronto con probabilita_mercato di market_odds (la stessa funzione usata da v3)
        for ev in mo.eventi_quote(snapshot):
            home = ev.get("home_team")
            away = ev.get("away_team")
            p_str = f"{home} vs {away}"
            if p_str not in giocate_per_partita:
                continue
            
            mkt = mo.probabilita_mercato(ev.get("libri") or [])
            v3_probs = mkt["probs"]
            self.assertIsNotNone(v3_probs)
            
            # Controllo bit-per-bit (uguaglianza float esatta)
            self.assertEqual(v3_probs["1"], giocate_per_partita[p_str]["1"])
            self.assertEqual(v3_probs["X"], giocate_per_partita[p_str]["X"])
            self.assertEqual(v3_probs["2"], giocate_per_partita[p_str]["2"])

    def test_somma_doppia_chance(self):
        ev = _genera_evento_finto(terna=(2.1, 3.4, 3.5))
        payload = _genera_payload_finto([ev])
        now = datetime.now(timezone.utc)
        res = lg.calcola_lista_giocate(payload, adesso_utc=now)
        self.assertEqual(6, len(res["giocate"]))
        
        m = {g["giocata"]: g["probabilita"] for g in res["giocate"]}
        self.assertAlmostEqual(m["1"] + m["X"], m["1X"], places=12)
        self.assertAlmostEqual(m["X"] + m["2"], m["X2"], places=12)
        self.assertAlmostEqual(m["1"] + m["2"], m["12"], places=12)


class TestStimaBet365(unittest.TestCase):
    """Test modulo stima bet365 e parità con PR #58 punto D."""

    def test_parametri_file_esistono_e_hanno_data_fit(self):
        params = lg.carica_parametri_stima()
        self.assertIn("fit_data", params)
        self.assertIn("fit_stagione", params)
        self.assertEqual("2024/25", params["fit_stagione"])
        self.assertIn("R_loc", params)
        self.assertIn("R_tipo", params)
        self.assertIn("R_glob", params)
        self.assertIn("R_fixed", params)

    def test_parita_numerica_errore_mediano_test_2025_26(self):
        # Riproduce esattamente il calcolo del test OOS 2025/26 da audit/griglia_implicita.py.
        # Fallisce se i moduli di audit non sono importabili dalla radice del repo e non salta mai in CI.
        try:
            import pandas as pd
            import numpy as np
            from audit.backtest_experiment_all import LEAGUES
            from audit.griglia_implicita import load_quotes, bet365_pairs, odd_band
        except ImportError as e:
            if os.environ.get("GITHUB_ACTIONS"):
                self.fail(f"I moduli di audit devono essere importabili in CI: {e}")
            self.skipTest(f"Moduli di audit (pandas/numpy) non disponibili in ambiente locale privo di dipendenze: {e}")

        quotes = pd.concat([load_quotes(pfx, lg_name) for pfx, lg_name in LEAGUES], ignore_index=True)
        pairs = bet365_pairs(quotes)
        pre = pairs[pairs.mercato.isin(["1X2 ant.", "O/U 2,5 ant."])].copy()
        pre["tipo"] = np.where(pre.mercato == "1X2 ant.", "1X2", "O/U 2,5")
        pre["fascia"] = odd_band(1.0 / pre["p_fair_pin"].to_numpy())
        te = pre[pre.stagione == "2025/26"]

        params = lg.carica_parametri_stima()
        preds = []
        for r in te.itertuples():
            q_est = lg.stima_quota_b365(r.p_fair_pin, r.lega, tipo=r.tipo, params=params)
            preds.append(q_est)
            
        b = te["quota_b365"].to_numpy(float)
        preds = np.array(preds)
        err_pct = np.abs(preds / b - 1.0)
        med_err = np.median(err_pct) * 100.0
        # Errore assoluto mediano atteso: 1,36%
        self.assertAlmostEqual(1.3578, med_err, delta=0.01)

    def test_doppia_chance_formula_e_marcatore(self):
        # q_dc = 1 / (1/qa + 1/qb)
        qa = 2.0
        qb = 3.0
        q_dc = lg.stima_quota_b365_dc(qa, qb)
        self.assertAlmostEqual(1.0 / (1.0/2.0 + 1.0/3.0), q_dc, places=6)
        
        # Test marcatura
        ev = _genera_evento_finto(terna=(2.0, 3.2, 3.8))
        payload = _genera_payload_finto([ev])
        res = lg.calcola_lista_giocate(payload, adesso_utc=datetime.now(timezone.utc))
        for g in res["giocate"]:
            if g["is_dc"]:
                self.assertEqual("stima non verificata", g["nota_stima"])


class TestPropostaMultiplaERicercaEsaustiva(unittest.TestCase):
    """Verifica della ricerca combinatoria esaustiva contro forza bruta indipendente."""

    def test_forza_bruta_indipendente_su_insieme_ridotto(self):
        # Insieme ridotto di prova generato senza campi derivati del modulo
        giocate = [
            {"partita": "P1", "match_id": "1", "giocata": "1", "probabilita": 0.70, "quota_b365_stimata": 1.35},
            {"partita": "P1", "match_id": "1", "giocata": "X", "probabilita": 0.20, "quota_b365_stimata": 4.50},
            {"partita": "P2", "match_id": "2", "giocata": "1", "probabilita": 0.65, "quota_b365_stimata": 1.45},
            {"partita": "P2", "match_id": "2", "giocata": "2", "probabilita": 0.25, "quota_b365_stimata": 3.80},
            {"partita": "P3", "match_id": "3", "giocata": "1X", "probabilita": 0.80, "quota_b365_stimata": 1.20},
            {"partita": "P3", "match_id": "3", "giocata": "2", "probabilita": 0.20, "quota_b365_stimata": 4.80},
        ]
        
        # Forza bruta di riferimento completamente indipendente:
        # enumera TUTTE le giocate dell'insieme ridotto senza pre-selezione candidati né campi derivati
        all_combos = []
        # Singole
        for g in giocate:
            q = g["quota_b365_stimata"]
            if 2.0 <= q <= 3.0:
                all_combos.append((g["probabilita"], q, [g]))
        # 2 e 3 eventi (max 1 per partita)
        for k in (2, 3):
            for c in itertools.combinations(giocate, k):
                partiti = [x["partita"] for x in c]
                if len(set(partiti)) < len(partiti):
                    continue
                q_tot = 1.0
                p_tot = 1.0
                for x in c:
                    q_tot *= x["quota_b365_stimata"]
                    p_tot *= x["probabilita"]
                if 2.0 <= q_tot <= 3.0:
                    all_combos.append((p_tot, q_tot, list(c)))

        ref_best = max(all_combos, key=lambda x: x[0]) if all_combos else None
        
        # Esecuzione della funzione sotto test
        res = lg.cerca_proposta_multipla(giocate, fascia_min=2.0, fascia_max=3.0, top_k=10)
        migliore = res["migliore_assoluta"]
        
        if ref_best is None:
            self.assertIsNone(migliore)
        else:
            self.assertIsNotNone(migliore)
            self.assertAlmostEqual(ref_best[0], migliore["probabilita"], places=8)
            self.assertAlmostEqual(ref_best[1], migliore["quota_totale"], places=8)
            self.assertEqual(len(ref_best[2]), len(migliore["giocate"]))

    def test_percorso_reale_singola_in_fascia(self):
        # Output di calcola_lista_giocate su snapshot reale passato senza modifiche a cerca_proposta_multipla.
        # Adattamento di interfaccia (nessuna asserzione numerica cambiata): lo snapshot NON e'
        # piu' letto dal file su disco, che il workflow live_odds.yml rigenera ogni giorno e su
        # cui i valori attesi qui sotto non valgono piu'; si legge il blob storico 078beef (93
        # eventi, generato 2026-10-10T09:08Z) — quello su cui le asserzioni sono nate, con lo
        # stesso meccanismo `git show` del test di parita' (fc1b45e).
        try:
            raw = subprocess.check_output(
                ["git", "show", "078beef:SoccerMath/database/live_odds.json"],
                stderr=subprocess.DEVNULL
            ).decode("utf-8")
            snap = json.loads(raw)
        except Exception as e:
            self.skipTest(f"Impossibile leggere snapshot da git: {e}")
        now = datetime.fromisoformat("2026-10-11T13:00:00Z")
        res_lg = lg.calcola_lista_giocate(snap, adesso_utc=now)
        giocate = res_lg["giocate"]
        
        prop = lg.cerca_proposta_multipla(giocate, fascia_min=2.00, fascia_max=3.00)
        k1 = prop["per_k"][1]
        self.assertIsNotNone(k1, "k=1 non deve essere None quando esiste una singola in fascia [2,00; 3,00]")
        self.assertEqual("Celta Vigo vs Alavés", k1["giocate"][0]["partita"])
        self.assertEqual("1", k1["giocate"][0]["giocata"])
        self.assertAlmostEqual(0.4732, k1["probabilita"], delta=0.001)
        self.assertAlmostEqual(2.00, k1["quota_totale"], delta=0.01)

    def test_ev_anche_se_negativo(self):
        giocate = [
            {"partita": "P1", "match_id": "1", "giocata": "1", "probabilita": 0.40, "quota_stimata_effettiva": 2.20},
        ]
        res = lg.cerca_proposta_multipla(giocate, fascia_min=2.0, fascia_max=3.0)
        migliore = res["migliore_assoluta"]
        self.assertIsNotNone(migliore)
        # EV = 0.40 * 2.20 - 1 = -0.12 (-12%)
        self.assertAlmostEqual(-0.12, migliore["ev"], places=6)


class TestCasiLimite(unittest.TestCase):
    """Casi senza quote, con una sola partita, e senza combinazioni in fascia."""

    def test_caso_senza_quote(self):
        # Payload nullo o vuoto
        res = lg.calcola_lista_giocate(None)
        self.assertEqual([], res["giocate"])
        self.assertEqual(0, res["n_partite_ammesse"])
        
        prop = lg.cerca_proposta_multipla(res["giocate"])
        self.assertIsNone(prop["migliore_assoluta"])
        self.assertIn("Nessuna giocata disponibile", prop["messaggio"])

    def test_caso_una_sola_partita_senza_combinazioni_in_fascia(self):
        # Una partita con quota stimata bassa (es. 1.20)
        ev = _genera_evento_finto(match_id="m1", terna=(1.25, 6.0, 11.0))
        payload = _genera_payload_finto([ev])
        now = datetime.now(timezone.utc)
        res = lg.calcola_lista_giocate(payload, adesso_utc=now)
        self.assertEqual(1, res["n_partite_ammesse"])
        self.assertEqual(6, len(res["giocate"]))

        # Con fascia [2.50, 2.60], nessuna giocata della singola partita rientra
        prop = lg.cerca_proposta_multipla(res["giocate"], fascia_min=2.50, fascia_max=2.60)
        self.assertIsNone(prop["migliore_assoluta"])
        self.assertIsNotNone(prop["messaggio"])
        self.assertIn("Nessuna combinazione", prop["messaggio"])

    def test_conteggio_escluse_iniziate_e_senza_quote(self):
        now = datetime.now(timezone.utc)
        ev_iniziata = _genera_evento_finto(match_id="m_ini", commence_offset_hours=-1.0)
        ev_senza_quote = {
            "id": "m_no_odds",
            "home_team": "Team A",
            "away_team": "Team B",
            "lega": "Serie A",
            "commence_time": (now + timedelta(hours=2.0)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "libri": []
        }
        ev_ok = _genera_evento_finto(match_id="m_ok", commence_offset_hours=2.0)
        payload = _genera_payload_finto([ev_iniziata, ev_senza_quote, ev_ok])
        
        res = lg.calcola_lista_giocate(payload, adesso_utc=now)
        self.assertEqual(1, res["n_partite_ammesse"])
        self.assertEqual(1, res["n_escluse_iniziate"])
        self.assertEqual(1, res["n_escluse_senza_quote"])
        self.assertEqual(3, res["n_partite_totali"])


class TestRegistroOmbraMultipla(unittest.TestCase):
    """Test del registro ombra per multipla_proposta_v1: prima registrazione immutabile."""

    def test_prima_registrazione_settimana_mai_sovrascritta(self):
        # Adattamento di interfaccia (nessuna asserzione numerica cambiata): dal punto 9 la
        # prima registrazione avviene SOLO fra venerdì 00:00 e lunedì 23:59 (Europe/Rome),
        # quindi l'istante del calcolo va fissato a un venerdì — con `datetime.now()` il test
        # fallirebbe da martedì a giovedì ("fuori_finestra") senza che nulla sia rotto.
        # Venerdì 2026-10-16 18:00 ora italiana (16:00 UTC): finestra aperta.
        now = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)
        settimana = lg.settimana_gioco(now)
        
        proposta1 = {
            "probabilita": 0.45,
            "quota_totale": 2.20,
            "ev": -0.01,
            "giocate": [
                {"partita": "A vs B", "lega": "Serie A", "giocata": "1", "probabilita": 0.45, "quota_b365_stimata": 2.20}
            ]
        }
        proposta2 = {
            "probabilita": 0.50,
            "quota_totale": 2.10,
            "ev": 0.05,
            "giocate": [
                {"partita": "C vs D", "lega": "Serie A", "giocata": "1", "probabilita": 0.50, "quota_b365_stimata": 2.10}
            ]
        }
        
        # Simulazione storage ombra
        storage_ombra = []
        def fake_load(*args, **kwargs):
            return list(storage_ombra), "upstash"
        def fake_save(rows, *args, **kwargs):
            storage_ombra.clear()
            storage_ombra.extend(rows)
            return {"remoto": "ok", "backend": "upstash", "righe_scritte": len(rows)}

        with mock.patch("registry_store.load_ombra_rows", side_effect=fake_load), \
             mock.patch("registry_store.save_ombra_rows", side_effect=fake_save):
            
            # Primo salvataggio: aggiunge la riga
            esito1 = lg.salva_proposta_multipla_registro_ombra(proposta1, istante_utc=now, k=1)
            self.assertEqual("ok", esito1.get("remoto"))
            self.assertEqual(1, len(storage_ombra))
            entry_salvata = storage_ombra[0]
            self.assertEqual(lg.FAMIGLIA_OMBRA_MULTIPLA_PROPOSTA, entry_salvata["ombra_famiglia"])
            self.assertEqual(settimana, entry_salvata["settimana"])
            self.assertEqual(45.0, entry_salvata["prob_sicuro"])

            # Secondo salvataggio nella stessa settimana per stesso k: NON sovrascrive
            esito2 = lg.salva_proposta_multipla_registro_ombra(proposta2, istante_utc=now, k=1)
            self.assertEqual("gia_registrata_settimana", esito2.get("remoto"))
            self.assertEqual(1, len(storage_ombra))
            # Contenuto rimasto identico a proposta1
            self.assertEqual(45.0, storage_ombra[0]["prob_sicuro"])
            self.assertIn("A vs B", storage_ombra[0]["top3"][0])

            # Salvataggio di tutte le proposte k (1..4)
            best_by_k_mock = {
                1: proposta1,
                2: {
                    "k": 2, "probabilita": 0.40, "quota_totale": 2.15, "ev": -0.14,
                    "giocate": [
                        {"partita": "A vs B", "lega": "Serie A", "giocata": "1", "probabilita": 0.60, "quota_b365_stimata": 1.40},
                        {"partita": "C vs D", "lega": "Serie A", "giocata": "X", "probabilita": 0.66, "quota_b365_stimata": 1.53},
                    ]
                }
            }
            esito_k = lg.salva_tutte_proposte_k_registro_ombra(best_by_k_mock, istante_utc=now)
            # k=1 era già presente, quindi viene salvato solo k=2
            self.assertEqual("ok", esito_k.get("remoto"))
            self.assertIn(2, esito_k.get("salvate_k", []))
            self.assertIn(1, esito_k.get("gia_presenti_k", []))
            self.assertEqual(2, len(storage_ombra))


class TestGuardiaValoreAtteso(unittest.TestCase):
    """Verifica che una combinazione con sole quote stimate non possa avere EV positivo in silenzio."""

    def test_guardia_ev_positivo_stima_incoerente(self):
        # Se una quota stimata anomala produce EV > 0 (ad es. p=0.60, q=2.20 -> p*q = 1.32 > 1.0),
        # la logica di calcolo segnala stima_incoerente=True indicando la giocata responsabile.
        giocata_anomala = {
            "match_id": "m1",
            "partita": "Squadra A vs Squadra B",
            "lega": "Serie A",
            "giocata": "1",
            "probabilita": 0.60,
            "quota_b365_stimata": 2.20,
            "quota_stimata_effettiva": 2.20,
            "is_dc": False,
        }
        res = lg.cerca_proposta_multipla([giocata_anomala], fascia_min=2.0, fascia_max=3.0)
        migliore = res["migliore_assoluta"]
        self.assertIsNotNone(migliore)
        self.assertGreater(migliore["ev"], 0.0)
        self.assertTrue(migliore.get("stima_incoerente"))
        self.assertEqual("m1", migliore.get("giocata_responsabile", {}).get("match_id"))


class TestInvarianteMargineImplicito(unittest.TestCase):
    """Invariante sullo stimatore di produzione su snapshot reale di live_odds.json.

    Per ogni giocata candidata:
    1. Quota stimata < Quota equa (1/p)
    2. Margine implicito (p * quota - 1) compreso fra -12% e -1% (anche per doppia chance)
    """

    def test_invariante_margine_implicito_snapshot_reale(self):
        snap = mo.carica_quote_live()
        self.assertIsNotNone(snap)
        res = lg.calcola_lista_giocate(snap)
        giocate = res["giocate"]
        self.assertGreater(len(giocate), 0)

        for g in giocate:
            p = g["probabilita"]
            q = g["quota_b365_stimata"]
            q_equa = 1.0 / p
            self.assertLess(q, q_equa, f"Quota {q} >= quota equa {q_equa} per {g['partita']} {g['giocata']}")
            margine = p * q - 1.0
            self.assertGreaterEqual(margine, -0.12, f"Margine {margine} < -12% per {g['partita']} {g['giocata']}")
            self.assertLessEqual(margine, -0.01, f"Margine {margine} > -1% per {g['partita']} {g['giocata']}")


class TestQuoteNonGiocabili(unittest.TestCase):
    """Test su snapshot reale con conteggio delle giocate escluse (quota stimata arrotondata <= 1.01)."""

    def test_conteggio_giocate_non_giocabili_snapshot_reale(self):
        # Adattamento di interfaccia (nessuna asserzione numerica cambiata): anche qui lo
        # snapshot si legge dal blob storico 078beef — le 93 partite / 558 giocate sono QUELLE,
        # non quelle del file su disco che il workflow rigenera ogni giorno.
        try:
            raw = subprocess.check_output(
                ["git", "show", "078beef:SoccerMath/database/live_odds.json"],
                stderr=subprocess.DEVNULL
            ).decode("utf-8")
            snap = json.loads(raw)
        except Exception as e:
            self.skipTest(f"Impossibile leggere snapshot da git: {e}")
        # Istante 2020-01-01 per includere tutte le 93 partite dello snapshot
        res = lg.calcola_lista_giocate(snap, adesso_utc=datetime(2020, 1, 1, tzinfo=timezone.utc))
        giocate = res["giocate"]
        self.assertEqual(558, len(giocate))  # 93 partite * 6 esiti

        non_giocabili = [g for g in giocate if not g.get("giocabile")]
        # Sullo snapshot del 10/10 ci sono esattamente 3 giocate con quota stimata arrotondata <= 1.01:
        # 1. Barcelona vs Getafe (1X): quota 0.99
        # 2. Paris Saint Germain vs Le Mans FC (1X): quota 1.00
        # 3. Inter Milan vs Parma (1X): quota 1.01
        self.assertEqual(3, len(non_giocabili))
        for g in non_giocabili:
            self.assertLessEqual(g["quota_b365_stimata"], 1.01)
            self.assertEqual("non giocabile", g["stato_quota"])

        # Verifica che restino in tabella (presenti in giocate) ma non entrino nei candidati della multipla
        prop = lg.cerca_proposta_multipla(giocate)
        candidati_ids = [
            (cg.get("partita"), cg.get("giocata"))
            for cg in (prop.get("migliore_assoluta", {}).get("giocate", []) if prop.get("migliore_assoluta") else [])
        ]
        for ng in non_giocabili:
            self.assertNotIn((ng["partita"], ng["giocata"]), candidati_ids)


if __name__ == "__main__":
    unittest.main()


