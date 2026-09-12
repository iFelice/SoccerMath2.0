"""Test di ``audit/gg_ng_calibration.py``.

Deterministici e offline: nessun accesso di rete; il test di integrazione sul
join usa solo i file gia' presenti nel repo (audit/data + SoccerMath/database)
in sola lettura. Nessuna scrittura fuori da una tmpdir.

Copertura (punto 5 del protocollo):
  * normalizzazione nomi su campione noto (clean_name + esonimi audit);
  * join deterministico (stesso input -> stesso output);
  * gestione coppie duplicate: mai assegnate a caso, segnalate
    ``duplicate_not_resolved`` / ``csv_duplicate``;
  * de-vig: nessuna quota negativa/<=1 accettata, probabilita' sempre in (0,1);
  * selezione bookmaker: priorita' bet365, fallback primo usabile, salti di
    esiti bloccati e quote non valide;
  * walk-forward no-leakage: modificare una partita FUTURA non cambia le
    probabilita' gia' emesse; modificarne una PASSATA si'.

Eseguibili con pytest o direttamente:
    python -m pytest audit/test_gg_ng_calibration.py -q
    python audit/test_gg_ng_calibration.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
import unittest
import warnings
from datetime import datetime, timezone

import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
for p in (_AUDIT_DIR, os.path.join(_REPO_ROOT, "SoccerMath")):
    if p not in sys.path:
        sys.path.insert(0, p)

# import di app (attraverso gg_ng_calibration) e' rumoroso in bare mode
logging.disable(logging.CRITICAL)
warnings.filterwarnings("ignore")

import gg_ng_calibration as M  # noqa: E402


def _season_df(rows):
    """Mini df stagione con lo schema di load_league (gia' pulito)."""
    return pd.DataFrame(rows, columns=["Date", "season", "HomeClean", "AwayClean",
                                       "FTHG", "FTAG"])


def _csv_row(date, season, home, away, fthg, ftag):
    return (pd.Timestamp(date), season, home, away, fthg, ftag)


def _json_row(home, away, date=None, hs="1", as_= "1", market=None):
    return {
        "home_team": home, "away_team": away,
        "match_date": date, "home_score": hs, "away_score": as_,
        "btts_market": market if market is not None else [
            {"btts_yes": "1.80", "btts_no": "2.00", "bookmaker_name": "bet365.it"},
        ],
    }


# =====================================================================
# 1. Normalizzazione
# =====================================================================
class TestNormalizzazione(unittest.TestCase):

    def test_campione_noto(self):
        casi = {
            # esonimi italiani Oddsportal -> canonici dei CSV football-data
            "Marsiglia": "Marseille",
            "Lione": "Lyon",
            "Lilla": "Lille",
            "Nizza": "Nice",
            "Tolosa": "Toulouse",
            "Strasburgo": "Strasbourg",
            "St. Etienne": "St Etienne",
            "Manchester Utd": "Man United",
            "Sheffield Utd": "Sheffield United",
            "Ath. Bilbao": "Ath Bilbao",
            "Atl. Madrid": "Ath Madrid",
            "Barcellona": "Barcelona",
            "Cadice": "Cadiz",
            "Celta Vigo": "Celta",
            "Maiorca": "Mallorca",
            "Siviglia": "Sevilla",
            "Amburgo": "Hamburg",
            "Augusta": "Augsburg",
            "Brema": "Werder Bremen",
            "Colonia": "Koln",
            "Francoforte": "Ein Frankfurt",
            "Friburgo": "Freiburg",
            "Kiel": "Holstein Kiel",
            "Magonza": "Mainz",
            "Monchengladbach": "M'gladbach",
            "RB Lipsia": "Leipzig",
            "St. Pauli": "St Pauli",
            "Stoccarda": "Stuttgart",
            "Union Berlino": "Union Berlin",
            # clean_name puro (nessun esonimo necessario)
            "Nottingham": "Nott'm Forest",
            "Espanyol": "Espanol",
            "Paris SG": "PSG",
            "PSG": "PSG",
            "Bayern": "Bayern",
            "Wolves": "Wolves",
            "Inter": "Inter",
            "Arsenal": "Arsenal",
            "Monaco": "Monaco",
        }
        for raw, expected in casi.items():
            self.assertEqual(M.normalize_name(raw), expected, msg=raw)

    def test_valori_esonimi_sono_canonici(self):
        """Invariante di team_aliases: ogni canonical e' punto fisso di clean_name."""
        for exonym, canonical in M.EXONYM_TO_CANONICAL.items():
            self.assertEqual(M.clean_name(canonical), canonical,
                             msg=f"canonical non canonico: {canonical} (da {exonym})")

    def test_nome_vuoto(self):
        self.assertEqual(M.normalize_name(""), "")
        self.assertEqual(M.normalize_name(None), "")


# =====================================================================
# 2. De-vig e quote
# =====================================================================
class TestDevig(unittest.TestCase):

    def test_proporzionale_standard(self):
        # 1/2.0 = 0.5, 1/1.75 = 0.571428..., overround 1.0714...
        p_yes, p_no = M.devig_two_way(2.0, 1.75)
        self.assertAlmostEqual(p_yes, 0.4666666, places=6)
        self.assertAlmostEqual(p_yes + p_no, 1.0, places=12)
        self.assertTrue(0.0 < p_yes < 1.0 and 0.0 < p_no < 1.0)

    def test_simmetrico(self):
        p_yes, p_no = M.devig_two_way(2.0, 2.0)
        self.assertAlmostEqual(p_yes, 0.5, places=12)
        self.assertAlmostEqual(p_no, 0.5, places=12)

    def test_rifiuta_quote_non_valide(self):
        for oy, on in [(1.0, 2.0), (2.0, 1.0), (-2.0, 2.0), (0.5, 2.0),
                       (None, 2.0), (2.0, None),
                       (float("nan"), 2.0), (2.0, float("inf"))]:
            self.assertIsNone(M.devig_two_way(oy, on), msg=f"{oy}/{on}")

    def test_pick_prefers_bet365(self):
        market = [
            {"btts_yes": "1.90", "btts_no": "1.95", "bookmaker_name": "888sport"},
            {"btts_yes": "1.80", "btts_no": "2.00", "bookmaker_name": "bet365.it"},
        ]
        info = M.pick_btts_entry(market)
        self.assertFalse(info["fallback"])
        self.assertIn("bet365", info["bookmaker"].lower())
        self.assertEqual(info["o_yes"], 1.80)

    def test_pick_fallback_primo_usabile(self):
        market = [
            {"btts_yes": "1.90", "btts_no": "1.95", "bookmaker_name": "888sport"},
            {"btts_yes": "1.80", "btts_no": "2.00", "bookmaker_name": "bwin.it"},
        ]
        info = M.pick_btts_entry(market)
        self.assertTrue(info["fallback"])
        self.assertEqual(info["bookmaker"], "888sport")
        self.assertEqual(info["index"], 0)

    def test_pick_salta_bloccati_e_quote_non_valide(self):
        market = [
            {"btts_yes": None, "btts_no": "2.00", "bookmaker_name": "A"},
            {"btts_yes": "1.50", "btts_no": "0.90", "bookmaker_name": "B"},   # <=1
            {"btts_yes": "1.70", "btts_no": "2.10",
             "bookmaker_name": "bet365.it", "blocked_outcomes": ["btts_yes"]},
            {"btts_yes": "1.60", "btts_no": "2.20", "bookmaker_name": "C"},
        ]
        info = M.pick_btts_entry(market)
        self.assertEqual(info["bookmaker"], "C")
        self.assertTrue(info["fallback"])
        # se il bet365 non e' bloccato vince lui
        market[2].pop("blocked_outcomes")
        info = M.pick_btts_entry(market)
        self.assertIn("bet365", info["bookmaker"].lower())
        self.assertFalse(info["fallback"])

    def test_pick_nessun_usabile(self):
        self.assertIsNone(M.pick_btts_entry([]))
        self.assertIsNone(M.pick_btts_entry(None))
        self.assertIsNone(M.pick_btts_entry([{"btts_yes": "x", "btts_no": "y",
                                              "bookmaker_name": "A"}]))


# =====================================================================
# 3. Parsing
# =====================================================================
class TestParsing(unittest.TestCase):

    def test_date(self):
        d = M.parse_utc_date("2023-03-05 11:30:00 UTC")
        self.assertEqual(d, datetime(2023, 3, 5, 11, 30, tzinfo=timezone.utc))
        self.assertIsNone(M.parse_utc_date(None))
        self.assertIsNone(M.parse_utc_date(""))
        self.assertIsNone(M.parse_utc_date("not a date"))

    def test_stagioni(self):
        self.assertEqual(M.season_start_year("2022-2023"), 2022)
        self.assertEqual(M.season_start_year("2025-2026"), 2025)
        self.assertEqual(M.season_label_of("2022-2023"), "2022/23")
        self.assertEqual(M.season_label_of("2025-2026"), "2025/26")

    def test_punteggi_mancanti(self):
        self.assertIsNone(M.parse_int(None))
        self.assertIsNone(M.parse_int(""))
        self.assertIsNone(M.parse_int("n/d"))
        self.assertEqual(M.parse_int("0"), 0)      # 0 e' valorizzato
        self.assertEqual(M.parse_int("5"), 5)


# =====================================================================
# 4. Join deterministico e coppie duplicate
# =====================================================================
class TestJoin(unittest.TestCase):

    def _season(self):
        # girone a 4 squadre, 2022/23: ogni coppia orientata compare una volta
        return _season_df([
            _csv_row("2022-08-20", "2022/23", "Alpha", "Beta", 1, 0),
            _csv_row("2022-08-20", "2022/23", "Gamma", "Delta", 2, 2),
            _csv_row("2022-08-27", "2022/23", "Alpha", "Gamma", 0, 0),
            _csv_row("2022-08-27", "2022/23", "Beta", "Delta", 3, 1),
        ])

    def test_deterministico(self):
        rows = [
            _json_row("Alpha", "Beta", date="2022-08-20 18:30:00 UTC"),
            _json_row("Gamma", "Delta"),                       # senza data
            _json_row("Beta", "Delta", date="2022-08-28 14:00:00 UTC"),  # +1 gg tollerato
        ]
        sdf = self._season()
        r1 = M.join_btts_file(rows, sdf)
        r2 = M.join_btts_file(rows, sdf)
        self.assertEqual(json.dumps(r1, sort_keys=True, default=str),
                         json.dumps(r2, sort_keys=True, default=str))
        self.assertEqual([r["status"] for r in r1],
                         ["ok", "ok", "ok"])

    def test_coppia_duplicata_senza_date_non_risolta(self):
        rows = [
            _json_row("Alpha", "Beta", hs="2", as_="0"),
            _json_row("Alpha", "Beta", hs="1", as_="0"),
        ]
        recs = M.join_btts_file(rows, self._season())
        self.assertTrue(all(r["status"] == "duplicate_not_resolved" for r in recs))
        self.assertTrue(all(r.get("csv_pos") is not None for r in recs))
        # nessuna assegnata: nessun record con quota
        self.assertTrue(all("o_yes" not in r for r in recs))

    def test_coppia_duplicata_disambiguata_per_data(self):
        rows = [
            _json_row("Alpha", "Beta", hs="4", as_="2"),                        # copia coppa, senza data
            _json_row("Alpha", "Beta", date="2022-08-20 18:30:00 UTC"),         # esemplare campionato
        ]
        recs = M.join_btts_file(rows, self._season())
        by_status = {r["status"] for r in recs}
        self.assertEqual(by_status, {"ok", "duplicate_not_resolved"})
        kept = [r for r in recs if r["status"] == "ok"]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["fthg"], 1)          # riga CSV, non il punteggio coppa
        dropped = [r for r in recs if r["status"] == "duplicate_not_resolved"]
        self.assertEqual(dropped[0]["home_score"], 4)

    def test_coppia_duplicata_con_due_date_coerenti_non_risolta(self):
        rows = [
            _json_row("Alpha", "Beta", date="2022-08-20 15:00:00 UTC"),
            _json_row("Alpha", "Beta", date="2022-08-20 20:45:00 UTC"),
        ]
        recs = M.join_btts_file(rows, self._season())
        self.assertTrue(all(r["status"] == "duplicate_not_resolved" for r in recs))

    def test_duplicato_lato_csv_mai_assegnato(self):
        # stessa coppia orientata due volte nel CSV: ambiguita' dichiarata
        sdf = _season_df([
            _csv_row("2022-08-20", "2022/23", "Alpha", "Beta", 1, 0),
            _csv_row("2022-11-20", "2022/23", "Alpha", "Beta", 2, 2),
        ])
        rows = [_json_row("Alpha", "Beta", date="2022-08-20 18:30:00 UTC")]
        recs = M.join_btts_file(rows, sdf)
        self.assertEqual([r["status"] for r in recs], ["csv_duplicate"])
        self.assertTrue(all("o_yes" not in r for r in recs))

    def test_date_mismatch_scartata(self):
        rows = [
            _json_row("Alpha", "Beta", date="2022-09-20 18:30:00 UTC"),  # copia coppa
            _json_row("Alpha", "Gamma", date="2022-08-28 12:00:00 UTC"), # +1 gg: ok
        ]
        recs = M.join_btts_file(rows, self._season())
        self.assertEqual(recs[0]["status"], "date_mismatch")
        self.assertEqual(recs[1]["status"], "ok")

    def test_risultato_mancante_escluso(self):
        rows = [
            _json_row("Alpha", "Beta", hs=None, as_=None),
            _json_row("Gamma", "Delta", hs="2", as_=None),
            _json_row("Alpha", "Gamma"),
        ]
        recs = M.join_btts_file(rows, self._season())
        self.assertEqual([r["status"] for r in recs[:2]], ["no_score", "no_score"])
        self.assertEqual(recs[2]["status"], "ok")

    def test_squadra_sconosciuta_pair_absent(self):
        rows = [_json_row("Alpha", "Zeta")]
        recs = M.join_btts_file(rows, self._season())
        self.assertEqual(recs[0]["status"], "pair_absent")

    def test_quota_mancante(self):
        rows = [_json_row("Alpha", "Beta", market=[])]
        recs = M.join_btts_file(rows, self._season())
        self.assertEqual(recs[0]["status"], "odds_missing")

    def test_accordo_punteggi(self):
        rows = [_json_row("Alpha", "Beta", hs="1", as_="0")]
        recs = M.join_btts_file(rows, self._season())
        self.assertTrue(recs[0]["scores_agree"])
        self.assertEqual(recs[0]["fthg"], 1)
        self.assertEqual(recs[0]["ftag"], 0)
        # l'esito reale GG/NG e' derivato dai gol CSV a valle (payload):
        # 1-0 non e' GG
        self.assertFalse(recs[0]["fthg"] > 0 and recs[0]["ftag"] > 0)


# =====================================================================
# 5. Walk-forward no-leakage
# =====================================================================
class TestWalkForward(unittest.TestCase):

    def _league_df(self):
        dates = pd.date_range("2022-08-20", periods=10, freq="7D")
        pairs = [("Alpha", "Beta"), ("Gamma", "Delta"), ("Alpha", "Gamma"),
                 ("Beta", "Delta"), ("Delta", "Alpha"), ("Beta", "Gamma"),
                 ("Gamma", "Alpha"), ("Delta", "Beta"), ("Alpha", "Delta"),
                 ("Gamma", "Beta")]
        return pd.DataFrame([{"Date": d, "season": "2022/23", "HomeClean": h,
                              "AwayClean": a, "FTHG": 1, "FTAG": 0}
                             for d, (h, a) in zip(dates, pairs)])

    def _run(self, df, targets, fs_records=()):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            preds, diag = M.walk_forward_gg_predictions(
                df, "Serie A", targets, list(fs_records))
        return preds, diag

    def test_predizioni_emesse_solo_per_target(self):
        df = self._league_df()
        preds, _ = self._run(df, {3, 7})
        self.assertEqual(sorted(preds), [3, 7])
        for p in preds.values():
            self.assertTrue(0.0 <= p <= 1.0)

    def test_no_leakage_avanti(self):
        """Modificare una partita FUTURA non cambia le P gia' emesse."""
        df = self._league_df()
        df2 = df.copy()
        df2.loc[9, "FTHG"], df2.loc[9, "FTAG"] = 5, 4   # ultima partita: 1-0 -> 5-4
        targets = {3, 5}
        p1, _ = self._run(df, targets)
        p2, _ = self._run(df2, targets)
        self.assertEqual(p1, p2)

    def test_lo_stato_usa_il_passato(self):
        """Modificare una partita PASSATA cambia le P delle successive
        (il walk-forward non e' una funzione costante)."""
        df = self._league_df()
        df2 = df.copy()
        df2.loc[0, "FTHG"], df2.loc[0, "FTAG"] = 5, 5   # prima partita: 1-0 -> 5-5
        targets = {3, 5}
        p1, _ = self._run(df, targets)
        p2, _ = self._run(df2, targets)
        self.assertNotEqual(p1, p2)

    def test_fallback_gol_branco_zero(self):
        """Prima giornata: F_season vuoto -> fallback gol shrinkato verso 1.0,
        identico al ramo a campione zero di produzione (P verso la media)."""
        df = self._league_df()
        preds, diag = self._run(df, {0})
        self.assertEqual(diag["fs_inactive_rows"], 1)
        # con stato vuoto lambda pure = avg * shrink(1.0) -> P(GG) < 1 e > 0
        self.assertTrue(0.0 < preds[0] < 1.0)


# =====================================================================
# 6. Metriche e ROI
# =====================================================================
class TestMetricheRoi(unittest.TestCase):

    def test_roi_nota_fissa(self):
        rows = [
            # edge GG +0.10 -> gioca GG a 2.20 e vince: +12 su 10
            {"p_model": 0.60, "p_fair_gg": 0.50, "o_yes": 2.20, "o_no": 1.70, "real_gg": True},
            # edge NG (p_fair_gg - p_model = 0.15) -> gioca NG a 1.90 e perde: -10
            {"p_model": 0.35, "p_fair_gg": 0.50, "o_yes": 2.00, "o_no": 1.90, "real_gg": True},
            # edge +0.30 -> gioca GG a 1.80 e vince: +8
            {"p_model": 0.80, "p_fair_gg": 0.50, "o_yes": 1.80, "o_no": 2.10, "real_gg": True},
        ]
        roi = M.simulate_roi(rows, threshold=0.0, stake=10.0)
        self.assertEqual(roi["n_bet"], 3)
        self.assertAlmostEqual(roi["roi_pct"], (12 - 10 + 8) / 30 * 100, places=6)
        self.assertAlmostEqual(roi["win_rate_pct"], 2 / 3 * 100, places=6)

    def test_roi_soglia(self):
        # edge esattamente nullo: nessuna scommessa a soglia 0 (0 > 0 falso)
        zero = [{"p_model": 0.5, "p_fair_gg": 0.5, "o_yes": 2.0, "o_no": 2.0,
                 "real_gg": True}]
        self.assertEqual(M.simulate_roi(zero, 0.0)["n_bet"], 0)
        # edge netto 0.03: gioca a soglia 0 e 2%, non a 5%
        rows = [{"p_model": 0.53, "p_fair_gg": 0.50, "o_yes": 2.0, "o_no": 2.0,
                 "real_gg": True}]
        self.assertEqual(M.simulate_roi(rows, 0.0)["n_bet"], 1)
        self.assertEqual(M.simulate_roi(rows, 0.02)["n_bet"], 1)
        self.assertEqual(M.simulate_roi(rows, 0.05)["n_bet"], 0)
        self.assertEqual(M.simulate_roi([], 0.0)["n_bet"], 0)
        self.assertIsNone(M.simulate_roi([], 0.0)["roi_pct"])

    def test_metrics_block_bounds(self):
        rows = [
            {"p_model": 0.7, "p_fair_gg": 0.6, "real_gg": True},
            {"p_model": 0.3, "p_fair_gg": 0.4, "real_gg": False},
        ]
        mk = M.metrics_block(rows)
        self.assertEqual(mk["n"], 2)
        for side in ("model", "market"):
            self.assertTrue(0 <= mk[side]["brier"] <= 1)
            self.assertTrue(0 <= mk[side]["hit_rate_pct"] <= 100)
        self.assertEqual(M.metrics_block([])["n"], 0)
        self.assertIsNone(M.metrics_block([])["model"]["brier"])

    def test_hit_rate(self):
        self.assertEqual(M.hit_rate([0.7, 0.4], [1, 1]), 0.5)   # solo la prima al cutoff 0.5
        self.assertIsNone(M.hit_rate([], []))

    def test_calibration_table_bins(self):
        tab = M.calibration_table([0.2, 0.5, 0.9], [0, 1, 1])
        self.assertEqual([b["bucket"] for b in tab],
                         ["0-40%", "40-45%", "45-50%", "50-55%", "55-60%", "60-101%"])
        self.assertEqual(tab[0]["n"], 1)
        self.assertEqual(tab[5]["n"], 1)
        self.assertIsNone(tab[1]["prob_media"])   # bucket vuoto


# =====================================================================
# 7. Integrazione sui dati reali (sola lettura, join only)
# =====================================================================
class TestIntegrazioneDatiReali(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(M.DATA_DIR):
            raise unittest.SkipTest("audit/data non presente")
        cls.dataset = M.load_btts_dataset()
        cls.league_cache = {}

    def _league(self, prefix):
        if prefix not in self.league_cache:
            self.league_cache[prefix] = M.load_league(prefix)
        return self.league_cache[prefix]

    def test_tutti_i_file_invariati_join(self):
        """Su tutti i 20 file: niente quote negative, P_fair sempre in (0,1),
        le coppie duplicate non vengono MAI assegnate, punteggi concordi."""
        for (slug, season), rows in self.dataset.items():
            prefix = M.BTTS_FILES[slug][0]
            df = self._league(prefix)
            sdf = df[df["season"] == M.season_label_of(season)].reset_index(drop=True)
            recs = M.join_btts_file(rows, sdf)
            joined = [r for r in recs if r["status"] == "ok"]
            for r in joined:
                self.assertGreater(r["o_yes"], 1.0, msg=f"{slug} {season}")
                self.assertGreater(r["o_no"], 1.0, msg=f"{slug} {season}")
                self.assertTrue(0.0 < r["p_fair_gg"] < 1.0, msg=f"{slug} {season}")
                self.assertTrue(r["scores_agree"], msg=f"{slug} {season} #{r['json_index']}")
            # le non risolte non hanno quota assegnata
            for r in recs:
                if r["status"] != "ok":
                    self.assertNotIn("o_yes", r,
                                     msg=f"{r['status']} con quota: {slug} {season}")

    def test_join_deterministico_su_file_reale(self):
        rows = self.dataset[("italy-serie-a", "2022-2023")]
        df = self._league("SerieA")
        sdf = df[df["season"] == "2022/23"].reset_index(drop=True)
        r1 = M.join_btts_file(rows, sdf)
        r2 = M.join_btts_file(rows, sdf)
        self.assertEqual(json.dumps(r1, sort_keys=True, default=str),
                         json.dumps(r2, sort_keys=True, default=str))
        # il caso noto: Spezia-Verona 2022/23 (coppa + campionato)
        dups = [r for r in r1 if r["status"] == "duplicate_not_resolved"]
        self.assertEqual(len(dups), 1)
        self.assertEqual((dups[0]["home_key"], dups[0]["away_key"]), ("Spezia", "Verona"))
        kept = [r for r in r1 if r["status"] == "ok"
                and (r["home_key"], r["away_key"]) == ("Spezia", "Verona")]
        self.assertEqual(len(kept), 1)
        self.assertEqual((kept[0]["fthg"], kept[0]["ftag"]), (0, 0))  # 0-0 del 05/03/2023


if __name__ == "__main__":
    unittest.main(verbosity=2)
