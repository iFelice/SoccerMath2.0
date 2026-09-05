"""
test_ng_regression.py — Test di regressione per il bug del Top Mix "NG ~ 99.8%".
Bug osservato: Premier League 2026/27, pronostici NG (No Goal) ~ 99.8%.

CAUSA (diagnosi completa in audit/repro_ng_anomaly.py):
  1. Le neopromosse Coventry City e Hull City sono ASSENTI dal file xG
     (xg_premier_league.json, residuo di uno scrape parziale 2025/26) e,
     anche con file fresco, la chiave Understat ("Coventry", "Hull") non
     coincideva con clean_name("Coventry City")/clean_name("Hull City")
     -> lookup xG fallito -> fallback sui gol del database CSV.
  2. Il fallback calcolava il rapporto attacco/difesa sulla media gol di
     1-2 partite senza alcun prior: Coventry 0 gol segnati in 2 partite
     -> att = 0.0 ESATTO; Hull 0 gol subiti -> def = 0.0 ESATTO.
  3. att0_pure/def0_pure = 0 -> base_pure_h/a = 0 -> _clip_lambda(0) =
     exp(-6) = 0.002479 -> P(0 gol) ~ 0.9975 -> GG ~ 0.2% -> NG ~ 99.8%.

FIX (nessun cap artificiale alle probabilita'):
  a) get_league_engine: shrinkage empirico-bayesiano verso la media di lega
     (_shrunk_ratio, PRIOR_MATCHES=6) su ENTRAMBI i percorsi (xG e fallback
     gol) + sanitizzazione (nessun ratio non-finito o <=0);
  b) _clip_lambda: input non finiti -> lambda neutra 1.0 (prima NaN ->
     20.0855, il clip SUPERIORE, per i confronti float di Python);
  c) update_xg.py: campo "matches" nel JSON xG + mappature nomi Understat
     2026/27 allineate ai nomi CSV/Football-Data.

Esecuzione:  python -m pytest audit/test_ng_regression.py -v
             python audit/test_ng_regression.py
"""
import json
import math
import os
import sys
import unittest
from unittest import mock

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

import app  # noqa: E402
from app import (  # noqa: E402
    _clip_lambda, _poisson_market, _shrunk_ratio, PRIOR_MATCHES,
    get_full_poisson_two_heads, get_league_engine,
)
from config import clean_name  # noqa: E402
import update_xg  # noqa: E402

import pandas as pd  # noqa: E402

LEAGUES = ["Serie A", "Premier League", "La Liga", "Bundesliga", "Ligue 1"]
DB_DIR = os.path.join(_REPO_ROOT, "SoccerMath", "database")
XG_FILES = {
    "Serie A": "xg_serie_a.json", "Premier League": "xg_premier_league.json",
    "La Liga": "xg_la_liga.json", "Bundesliga": "xg_bundesliga.json",
    "Ligue 1": "xg_ligue_1.json",
}
ARCH_FILES = {
    "Serie A": "xG archivio serie A.json",
    "Premier League": "xG archivio premier league.json",
    "La Liga": "xG archivio la liga.json",
    "Bundesliga": "xG archivio bundesliga.json",
    "Ligue 1": "xG archivio ligue 1.json",
}
LEAGUE_PREFIX = {"Serie A": "SerieA", "Premier League": "Premier",
                 "La Liga": "LaLiga", "Bundesliga": "Bundesliga", "Ligue 1": "Ligue1"}


def _engine(league):
    """get_league_engine senza cache (i test alterano le fonti xG)."""
    try:
        app.get_league_engine.clear()
    except Exception:
        pass
    return get_league_engine(league)


# ---------------------------------------------------------------------------
# 1. Test matematico diretto della formula GG/NG
# ---------------------------------------------------------------------------
class TestGGNGFormula(unittest.TestCase):
    """GG = (1 - P_home(0)) * (1 - P_away(0)); NG = 1 - GG."""

    def test_gg_formula_direct(self):
        for lh, la in [(1.5, 1.2), (0.3, 2.8), (2.5, 2.5), (0.9, 0.4), (1.62, 1.33)]:
            m = _poisson_market(lh, la)
            expected = (1.0 - math.exp(-lh)) * (1.0 - math.exp(-la))
            self.assertAlmostEqual(m["gg"], expected, places=10,
                                   msg=f"gg({lh},{la})")

    def test_ng_is_complement(self):
        for lh, la in [(1.5, 1.2), (0.05, 3.0), (2.0, 0.9)]:
            m = _poisson_market(lh, la)
            self.assertAlmostEqual((1 - m["gg"]) + m["gg"], 1.0, places=12)
            self.assertTrue(0.0 <= m["gg"] <= 1.0)

    def test_two_heads_gg_uses_pure_lambdas(self):
        """La testa Totali usa i lambda PURI (senza forma/mercato)."""
        hs = {"att": 1.4, "def": 0.8, "att0": 1.2, "def0": 0.9,
              "att0_pure": 1.1, "def0_pure": 0.95}
        as_ = {"att": 0.9, "def": 1.3, "att0": 1.0, "def0": 1.1,
               "att0_pure": 0.85, "def0_pure": 1.05}
        avg_h, avg_a = 1.6, 1.3
        m = get_full_poisson_two_heads(hs, as_, avg_h, avg_a)
        pure_h = _clip_lambda(1.1 * 1.05 * avg_h)
        pure_a = _clip_lambda(0.85 * 0.95 * avg_a)
        self.assertAlmostEqual(m["gg"], (1 - math.exp(-pure_h)) * (1 - math.exp(-pure_a)),
                               places=10)

    def test_lambda_zero_still_extreme_at_math_level(self):
        """Con lambda 0 CLIPPATA la matematica DEVE restituire NG estremo:
        il fix e' a monte (dati), non un cap sulle probabilita'."""
        m = _poisson_market(_clip_lambda(0.0), 1.2)
        self.assertGreater(1 - m["gg"], 0.99)  # matematica invariata


# ---------------------------------------------------------------------------
# 2. _shrunk_ratio: prior verso la media di lega (il cuore del fix)
# ---------------------------------------------------------------------------
class TestShrunkRatio(unittest.TestCase):
    def test_zero_goals_few_matches_not_zero(self):
        # Coventry: 0 gol in 2 partite -> (2*0 + 6)/(2+6) = 0.75, NON 0.0
        self.assertAlmostEqual(_shrunk_ratio(0.0, 2.9, 2), 0.75, places=12)

    def test_no_matches_league_average(self):
        self.assertEqual(_shrunk_ratio(0.0, 2.9, 0), 1.0)
        self.assertEqual(_shrunk_ratio(5.0, 2.9, None), 1.0)

    def test_zero_expected_league_average(self):
        self.assertEqual(_shrunk_ratio(3.0, 0.0, 10), 1.0)

    def test_nan_inf_inputs_league_average(self):
        self.assertEqual(_shrunk_ratio(float("nan"), 2.9, 5), 1.0)
        self.assertEqual(_shrunk_ratio(3.0, float("inf"), 5), 1.0)
        self.assertEqual(_shrunk_ratio(float("inf"), 2.9, 5), 1.0)
        self.assertEqual(_shrunk_ratio("rotta", 2.9, 5), 1.0)

    def test_large_sample_close_to_raw(self):
        # 38 partite con ratio reale 0.5 -> (38*0.5+6)/44 = 0.568: il prior
        # pesa ma non annulla l'evidenza
        self.assertAlmostEqual(_shrunk_ratio(0.5, 1.0, 38), (38 * 0.5 + 6) / 44,
                               places=12)

    def test_ratio_one_stays_one(self):
        self.assertAlmostEqual(_shrunk_ratio(2.9, 2.9, 7), 1.0, places=12)


# ---------------------------------------------------------------------------
# 3. NaN/inf non devono raggiungere _poisson_market()
# ---------------------------------------------------------------------------
class TestNaNInfSafety(unittest.TestCase):
    def test_clip_lambda_non_finite_neutral(self):
        # Prima del fix: max(0.002479, min(20.0855, nan)) -> 20.0855 (clip ALTO!)
        self.assertEqual(_clip_lambda(float("nan")), 1.0)
        self.assertEqual(_clip_lambda(float("inf")), 1.0)
        self.assertEqual(_clip_lambda(float("-inf")), 1.0)

    def test_clip_lambda_bounds_unchanged(self):
        self.assertAlmostEqual(_clip_lambda(1.5), 1.5, places=12)
        # costante storica documentata: exp(-6) ~ 0.002479 (arrotondato nel codice)
        self.assertAlmostEqual(_clip_lambda(0.0), 0.002479, places=12)
        self.assertAlmostEqual(_clip_lambda(1e9), 20.0855, places=12)

    def test_engine_stats_never_nonfinite_or_zero(self):
        for league in LEAGUES:
            engine = _engine(league)
            if not engine:
                continue
            stats, avg_h, avg_a, _ = engine
            for team, s in stats.items():
                for key in ("att", "def", "att0", "def0", "att0_pure", "def0_pure"):
                    v = s[key]
                    self.assertTrue(math.isfinite(v) and v > 0,
                                    f"{league}/{team}/{key}={v}: non finito o <= 0")

    def test_poisson_market_output_finite_with_garbage_input(self):
        m = _poisson_market(float("nan"), 1.1)
        for k, v in m.items():
            self.assertTrue(math.isfinite(v) and 0.0 <= v <= 1.0, f"{k}={v}")


# ---------------------------------------------------------------------------
# 4. Scenari engine su dati reali (Premier League) con fonti xG manipolate
# ---------------------------------------------------------------------------
# Snapshot xG "vecchio" della Premier League usato dai test di regressione.
# I file xg_<lega>.json sono ora DERIVATI dall'archivio per-partita
# (SoccerMath/update_xg.py) e contengono anche le neopromosse, quindi lo
# scenario del bug ("squadra assente dal file xG") va costruito
# esplicitamente rimuovendo Coventry City e Hull City: e' quella assenza,
# non il contenuto del file committato, che i test qui sotto verificano.
_PL_XG_FILE = json.load(open(os.path.join(DB_DIR, "xg_premier_league.json")))
PL_STALE_XG = {k: v for k, v in _PL_XG_FILE.items()
               if k not in ("Coventry City", "Hull City")}


class TestEngineXGPaths(unittest.TestCase):
    """xG normali / mancanti / zero-anomali / NaN, sul database reale."""

    def _stats(self, patched_xg):
        with mock.patch.object(app, "get_understat_xg", return_value=patched_xg):
            engine = _engine("Premier League")
        return engine

    def test_normal_xg_used(self):
        """1) Squadra con xG normali: il ratio xG viene usato (con shrinkage
        se 'matches' e' noto, identico al passato altrimenti)."""
        xg = {k: dict(v) for k, v in PL_STALE_XG.items()}
        xg["Coventry City"] = {"xG_avg": 1.0, "xGA_avg": 1.5, "matches": 2}
        xg["Hull City"] = {"xG_avg": 1.1, "xGA_avg": 1.4, "matches": 2}
        stats, avg_h, avg_a, _ = self._stats(xg)
        league_xg = sum(v["xG_avg"] for v in xg.values()) / len(xg)
        self.assertAlmostEqual(stats["Coventry City"]["att0_pure"],
                               (2 * (1.0 / league_xg) + PRIOR_MATCHES) / (2 + PRIOR_MATCHES),
                               places=10)

    def test_legacy_xg_without_matches_backcompat(self):
        """File xG vecchio (senza 'matches'): ratio = xG/lega, nessun shrinkage."""
        xg = {k: {"xG_avg": v["xG_avg"], "xGA_avg": v["xGA_avg"]}
              for k, v in PL_STALE_XG.items()}
        stats, avg_h, avg_a, _ = self._stats(xg)
        league_xg = sum(v["xG_avg"] for v in xg.values()) / len(xg)
        self.assertAlmostEqual(stats["Arsenal"]["att0_pure"],
                               xg["Arsenal"]["xG_avg"] / league_xg, places=10)

    def test_missing_xg_fallback_shrunk_not_zero(self):
        """2) Squadra con xG MANCANTI (caso del bug): fallback gol con prior.
        L'atteso va derivato dal DB live corrente, non fissato a mano: con il
        rollover dei dati le neopromosse possono avere 2, 3, ... partite."""
        stats, avg_h, avg_a, df = self._stats(dict(PL_STALE_XG))
        cov = df[(df["HomeClean"] == "Coventry City") | (df["AwayClean"] == "Coventry City")]
        hull = df[(df["HomeClean"] == "Hull City") | (df["AwayClean"] == "Hull City")]
        expected_cov_att = PRIOR_MATCHES / (len(cov) + PRIOR_MATCHES)  # 0 gol segnati
        expected_hull_def = PRIOR_MATCHES / (len(hull) + PRIOR_MATCHES)  # 0 gol subiti
        self.assertAlmostEqual(stats["Coventry City"]["att0_pure"], expected_cov_att, places=6)
        self.assertAlmostEqual(stats["Hull City"]["def0_pure"], expected_hull_def, places=6)
        self.assertGreater(stats["Hull City"]["att0_pure"], 0.5)

    def test_missing_xg_no_extreme_ng(self):
        """Con il fallback corretto le partite delle neopromosse non danno
        NG ~ 99.8% (le due partite della giornata 5-6/09/2026)."""
        stats, avg_h, avg_a, _ = self._stats(dict(PL_STALE_XG))
        for h, a in [("Man City", "Coventry City"), ("Hull City", "Aston Villa")]:
            m = get_full_poisson_two_heads(stats[clean_name(h)], stats[clean_name(a)],
                                           avg_h, avg_a)
            self.assertLess(1 - m["gg"], 0.85, f"NG estremo per {h}-{a}")
            self.assertGreater(m["gg"], 0.15)

    def test_zero_xg_without_matches_falls_back(self):
        """3) xG_avg = 0 senza 'matches' (dato indistinguibile da rotto):
        si usa il fallback gol, NON lambda ~ 0."""
        xg = {k: dict(v) for k, v in PL_STALE_XG.items()}
        xg["Coventry City"] = {"xG_avg": 0.0, "xGA_avg": 1.5}
        stats, _, _, df = self._stats(xg)
        cov = df[(df["HomeClean"] == "Coventry City") | (df["AwayClean"] == "Coventry City")]
        expected_cov_att = PRIOR_MATCHES / (len(cov) + PRIOR_MATCHES)
        self.assertAlmostEqual(stats["Coventry City"]["att0_pure"], expected_cov_att, places=6)

    def test_zero_xg_with_matches_shrunk(self):
        """xG_avg = 0 autentico (0.00 xG in 2 partite, con 'matches'):
        shrinkage -> 0.75, mai 0.0."""
        xg = {k: dict(v) for k, v in PL_STALE_XG.items()}
        xg["Coventry City"] = {"xG_avg": 0.0, "xGA_avg": 1.5, "matches": 2}
        stats, _, _, _ = self._stats(xg)
        self.assertAlmostEqual(stats["Coventry City"]["att0_pure"], 0.75, places=6)

    def test_nan_xg_falls_back(self):
        xg = {k: dict(v) for k, v in PL_STALE_XG.items()}
        xg["Hull City"] = {"xG_avg": float("nan"), "xGA_avg": 1.4}
        stats, _, _, _ = self._stats(xg)
        self.assertTrue(math.isfinite(stats["Hull City"]["att0_pure"]))
        self.assertGreater(stats["Hull City"]["att0_pure"], 0.5)


# ---------------------------------------------------------------------------
# 5. Mapping nomi Understat <-> CSV/Football-Data
# ---------------------------------------------------------------------------
class TestNameMapping(unittest.TestCase):
    def test_current_season_teams_covered(self):
        """4) Ogni squadra della stagione in corso (Live CSV) deve essere
        raggiungibile dal file xG: la chiave prodotta da update_xg (titolo
        Understat -> NAME_MAP) deve coincidere con clean_name(nome CSV)."""
        for league in LEAGUES:
            with open(os.path.join(DB_DIR, ARCH_FILES[league]), encoding="utf-8") as f:
                arch = json.load(f)
            titles_2026 = {m["home_team"] for m in arch if m.get("season") == 2026}
            canonical = {update_xg.NAME_MAP.get(t, t) for t in titles_2026}
            live = pd.read_csv(os.path.join(DB_DIR, f"{LEAGUE_PREFIX[league]}_Live.csv"),
                               low_memory=False)
            live_teams = {clean_name(t) for t in live["HomeTeam"]} | \
                         {clean_name(t) for t in live["AwayTeam"]}
            missing = {t for t in live_teams if t not in canonical}
            self.assertEqual(missing, set(),
                             f"{league}: squadre non mappabili su xG: {missing}")

    def test_premier_specific_aliases(self):
        self.assertEqual(update_xg.NAME_MAP["Coventry"], "Coventry City")
        self.assertEqual(update_xg.NAME_MAP["Hull"], "Hull City")
        self.assertEqual(clean_name("Coventry City"), "Coventry City")
        self.assertEqual(clean_name("Hull City"), "Hull City")


# ---------------------------------------------------------------------------
# 6. Regressione end-to-end sul database reale
# ---------------------------------------------------------------------------
class TestNoExtremeNGRegression(unittest.TestCase):
    def test_all_leagues_no_extreme_ng(self):
        """Nessuna coppia di squadre reali di alcun campionato puo' produrre
        NG > 95% (prima del fix: 102/702 coppie Premier League > 95%).
        Le probabilita' estreme restano possibili SOLO con lambda estreme
        realmente giustificate dai dati (che nessuna squadra reale ha)."""
        for league in LEAGUES:
            engine = _engine(league)
            if not engine:
                continue
            stats, avg_h, avg_a, _ = engine
            teams = sorted(stats.keys())
            worst = ("", "", 0.0)
            for h in teams:
                for a in teams:
                    if h == a:
                        continue
                    ng = 1 - get_full_poisson_two_heads(stats[h], stats[a],
                                                        avg_h, avg_a)["gg"]
                    if ng > worst[2]:
                        worst = (h, a, ng)
            self.assertLess(worst[2], 0.95,
                            f"{league}: NG={worst[2]:.4f} per {worst[0]}-{worst[1]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
