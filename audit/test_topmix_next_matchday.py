"""
test_topmix_next_matchday.py — Test di regressione per il bug del Top Mix.

Bug: fetch_and_calc_top_mix() selezionava le partite future usando il
min(matchday) restituito dall'API Football-Data. Questo non garantisce che
sia la prossima giornata realmente futura: partite GIA' PASSATE ma ancora
TIMED/SCHEDULED, recuperi lontani nel calendario o dati anomali potevano
far risultare selezionata una giornata sbagliata e far entrare nel Top Mix
del giorno partite molto piu' avanti (es. fine ottobre).

Correzione verificata qui (solo selezione temporale, matematica invariata):
  1. le partite TIMED/SCHEDULED vengono lette dall'API;
  2. 'utcDate' viene convertito in datetime timezone-aware;
  3. le partite con data/ora <= now vengono scartate (restano solo le future);
  4. la prossima giornata e' quella della prima partita futura per data;
  5. solo le partite di quella giornata (stessa finestra di round) entrano
     nel calcolo; nessuna partita di giornate successive puo' entrare.

Esecuzione:  python -m pytest audit/test_topmix_next_matchday.py -v
             python audit/test_topmix_next_matchday.py
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

import app  # noqa: E402  (importa anche config e modelli, come test_basic.py)
from config import clean_name  # noqa: E402

NOW = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)


# ----------------------------------------------------------------------------
# Fixture: risposta API simulata
# ----------------------------------------------------------------------------
def _match(mid, matchday, dt, home, away):
    return {
        "id": mid,
        "status": "TIMED",
        "matchday": matchday,
        "utcDate": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "homeTeam": {"name": home, "shortName": home},
        "awayTeam": {"name": away, "shortName": away},
    }


def _fine_ottobre(now):
    """Primo 31 ottobre strettamente oltre now + 30 giorni (round di ottobre)."""
    anno = now.year if datetime(now.year, 10, 31, tzinfo=timezone.utc) > now + timedelta(days=30) else now.year + 1
    return datetime(anno, 10, 31, 20, 45, tzinfo=timezone.utc)


def _payload(now):
    """Risposta API con: prossima giornata, giornata di ottobre, partite passate.

    - matchday 4 (PASSATE, ancora TIMED): con il vecchio min(matchday) sarebbe
      stata proprio questa giornata ad essere selezionata;
    - matchday 5 (prossima giornata realmente futura, now + 2 giorni): le
      UNICHE che devono risultare selezionate (entro la finestra di round);
    - matchday 9 a fine ottobre e matchday 12 a +75 giorni: future ma di
      giornate successive, NON devono mai entrare nel Top Mix;
    - id 2004: recupero isolato della STESSA giornata 5 ma a +45 giorni
      (fuori finestra): non deve entrare;
    - id 9001/9002: dati anomali (senza utcDate / senza matchday).
    """
    prossima = now + timedelta(days=2)
    return {
        "matches": [
            # partite gia' passate ma ancora TIMED (matchday minimo: il bug)
            _match(1001, 4, now - timedelta(days=3), "Lazio", "Genoa"),
            _match(1002, 4, now - timedelta(days=3, hours=2), "Cagliari", "Verona"),
            # prossima giornata realmente futura (matchday 5)
            _match(2001, 5, prossima, "Napoli", "Monza"),
            _match(2002, 5, prossima + timedelta(hours=2), "Inter", "Torino"),
            _match(2003, 5, prossima + timedelta(hours=3), "Juventus", "Udinese"),
            # giornate future successive (non contigue): es. fine ottobre
            _match(3001, 9, _fine_ottobre(now), "Real Madrid", "Almeria"),
            _match(3002, 9, _fine_ottobre(now) + timedelta(hours=2), "Barcelona", "Cadiz"),
            _match(3003, 12, now + timedelta(days=75), "Atalanta", "Empoli"),
            # anomalia: recupero isolato della stessa giornata 5, ma a +45 giorni
            _match(2004, 5, now + timedelta(days=45), "Fiorentina", "Bologna"),
            # anomalie: campi mancanti
            {"id": 9001, "status": "TIMED", "matchday": 5,
             "homeTeam": {"name": "Roma"}, "awayTeam": {"name": "Lecce"}},
            {"id": 9002, "status": "TIMED",
             "utcDate": (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "homeTeam": {"name": "Sassuolo"}, "awayTeam": {"name": "Frosinone"}},
        ]
    }


NEXT_ROUND_IDS = {2001, 2002, 2003}


# ----------------------------------------------------------------------------
# 1) Test unitari sulla selezione pura (select_next_matchday_matches)
# ----------------------------------------------------------------------------
class TestSelectNextMatchday(unittest.TestCase):
    def test_solo_prima_giornata_futura(self):
        """Dato un insieme di partite future su piu' giornate (piu' passate e
        anomalie), la selezione restituisce TUTTE e SOLE le partite della
        prima giornata futura realmente giocabile."""
        selected = app.select_next_matchday_matches(_payload(NOW)["matches"], now=NOW)
        self.assertEqual({m["id"] for m in selected}, NEXT_ROUND_IDS)

    def test_nessuna_partita_successiva_o_passata(self):
        selected = app.select_next_matchday_matches(_payload(NOW)["matches"], now=NOW)
        ids = {m["id"] for m in selected}
        # partite di ottobre / +75 giorni e recupero isolato esclusi
        self.assertNotIn(3001, ids)
        self.assertNotIn(3002, ids)
        self.assertNotIn(3003, ids)
        self.assertNotIn(2004, ids)
        # partite passate (matchday minimo, il vecchio criterio) escluse
        self.assertNotIn(1001, ids)
        self.assertNotIn(1002, ids)
        # ogni partita selezionata e' strettamente futura e della giornata 5
        for m in selected:
            self.assertEqual(m["matchday"], 5)
            self.assertGreater(app._parse_utc_date(m["utcDate"]), NOW)

    def test_soglia_now_esclusa(self):
        """Una partita con kickoff esattamente == now è già passata (<= now),
        non futura: deve essere scartata insieme alle precedenti."""
        payload = _payload(NOW)["matches"] + [_match(4001, 5, NOW, "Como", "Parma")]
        selected = app.select_next_matchday_matches(payload, now=NOW)
        ids = {m["id"] for m in selected}
        self.assertNotIn(4001, ids)
        self.assertTrue(all(app._parse_utc_date(m["utcDate"]) > NOW for m in selected))

    def test_confronto_timezone_aware(self):
        """utcDate con offset diversi (Z, +02:00, +00:00) non generano TypeError
        naive-vs-aware e vengono ordinati correttamente per istante assoluto."""
        dt1 = NOW + timedelta(days=2)
        dt2 = NOW + timedelta(days=2, hours=1)
        dt3 = NOW + timedelta(days=2, hours=2)
        matches = [
            _match(1, 7, dt1, "A", "B"),                                   # suffisso Z
            {**_match(2, 7, dt2, "C", "D"),
             "utcDate": dt2.astimezone(ZoneInfo("Europe/Rome")).isoformat()},  # +02:00
            {**_match(3, 7, dt3, "E", "F"),
             "utcDate": dt3.isoformat()},                                  # +00:00 esplicito
        ]
        selected = app.select_next_matchday_matches(matches, now=NOW)  # non deve raise
        self.assertEqual([m["id"] for m in selected], [1, 2, 3])

    def test_now_naive_non_solleva_typeerror(self):
        """Protezione difensiva: un now naive viene coercito a UTC invece di
        far crashare il confronto con datetime aware."""
        now_naive = NOW.replace(tzinfo=None)
        selected = app.select_next_matchday_matches(_payload(NOW)["matches"], now=now_naive)
        self.assertEqual({m["id"] for m in selected}, NEXT_ROUND_IDS)

    def test_now_in_altra_timezone_stessa_selezione(self):
        """now espresso in Europe/Rome (+02:00) da' la stessa selezione di now UTC:
        il confronto e' tra consapevoli dello stesso istante."""
        now_rome = NOW.astimezone(ZoneInfo("Europe/Rome"))
        self.assertEqual(now_rome.utcoffset(), timedelta(hours=2))
        selected = app.select_next_matchday_matches(_payload(NOW)["matches"], now=now_rome)
        self.assertEqual({m["id"] for m in selected}, NEXT_ROUND_IDS)

    def test_dati_anomali_e_vuoti(self):
        # nessuna partita futura -> lista vuota, nessuna eccezione
        self.assertEqual(app.select_next_matchday_matches([], now=NOW), [])
        solo_passate = [_match(1, 3, NOW - timedelta(days=1), "A", "B")]
        self.assertEqual(app.select_next_matchday_matches(solo_passate, now=NOW), [])
        self.assertEqual(app.select_next_matchday_matches(None, now=NOW), [])


# ----------------------------------------------------------------------------
# 2) Test end-to-end su fetch_and_calc_top_mix (HTTP/engine/Elo mockati)
#    Verifica che NESSUNA partita di giornate successive entri nel Top Mix e
#    che il Top Mix globale resti ordinato per probabilita'.
# ----------------------------------------------------------------------------
class TestFetchAndCalcTopMix(unittest.TestCase):
    def _team_stats(self):
        # statistiche fittizie per TUTTE le squadre del payload: le squadre di
        # ottobre sono favoritissimi, cosi' - se il bug esistesse - sarebbero
        # proprio le loro partite a dominare il Top Mix.
        raw = {
            # prossima giornata (matchday 5)
            "Napoli": {"att": 1.35, "def": 0.80}, "Monza": {"att": 0.85, "def": 1.40},
            "Inter": {"att": 1.30, "def": 0.85}, "Torino": {"att": 0.90, "def": 1.30},
            "Juventus": {"att": 1.28, "def": 0.85}, "Udinese": {"att": 0.90, "def": 1.35},
            # giornata di fine ottobre (matchday 9): squilibrate di proposito
            "Real Madrid": {"att": 2.00, "def": 0.40}, "Almeria": {"att": 0.60, "def": 2.00},
            "Barcelona": {"att": 1.95, "def": 0.45}, "Cadiz": {"att": 0.65, "def": 1.90},
            # matchday 12 e recupero isolato
            "Atalanta": {"att": 1.90, "def": 0.80}, "Empoli": {"att": 0.70, "def": 2.00},
            "Fiorentina": {"att": 1.50, "def": 1.00}, "Bologna": {"att": 1.20, "def": 1.10},
        }
        return {clean_name(nome): s for nome, s in raw.items()}

    def test_top_mix_solo_prima_giornata_futura(self):
        now = datetime.now(timezone.utc)
        payload_sa = _payload(now)

        def fake_get(url, **kwargs):
            self.assertIn("status", kwargs.get("params", {}))
            code = url.rstrip("/").split("/")[-2]  # .../competitions/{code}/matches
            body = payload_sa if code == "SA" else {"matches": []}
            return mock.Mock(status_code=200, json=lambda: body)

        fake_elo = lambda h, a, league: {"1": 0.62, "X": 0.22, "2": 0.16, "elo_diff": 80}
        engine = (self._team_stats(), 1.45, 1.15, None)

        with mock.patch.object(app.requests, "get", side_effect=fake_get), \
             mock.patch.object(app, "get_league_engine", return_value=engine), \
             mock.patch.object(app, "predict_elo_probs", side_effect=fake_elo), \
             mock.patch.object(app.time, "sleep", lambda s: None):
            app.fetch_and_calc_top_mix.clear()  # azzera la cache st.cache_data
            top_10, missing = app.fetch_and_calc_top_mix()

        # il Top Mix globale resta non vuoto, ordinato per probabilita' decrescente
        self.assertGreaterEqual(len(top_10), 1)
        self.assertLessEqual(len(top_10), 10)
        probs = [p["prob"] for p in top_10]
        self.assertEqual(probs, sorted(probs, reverse=True))
        self.assertEqual(missing, [])

        # SOLO partite della prima giornata futura realmente giocabile
        for p in top_10:
            self.assertEqual(p["giornata"], 5)
            self.assertIn(p["match_id"], NEXT_ROUND_IDS)
            self.assertGreater(app._parse_utc_date(p["utcDate"]), now)

        # NESSUNA partita di giornate successive (es. ottobre) o passata puo'
        # essere entrata nel Top Mix, nemmeno da lega diversa
        ids = {p["match_id"] for p in top_10}
        self.assertEqual(ids, ids & NEXT_ROUND_IDS)
        self.assertFalse(ids & {3001, 3002, 3003, 2004, 1001, 1002, 9001, 9002})


if __name__ == "__main__":
    unittest.main(verbosity=2)
