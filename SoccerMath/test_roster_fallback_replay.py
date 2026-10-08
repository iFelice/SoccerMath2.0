"""Replay storico: roster della stagione dal checkout quando lo snapshot non lo ha.

Difetto chiuso (preesistente dalla PR #38): ``season_rosters.json`` non esiste nei
commit storici di settembre 2026. Senza roster il seed Elo non parte
(``EloSeedError``), il replay ricostruisce il solo Poisson e il 1X2 cambia soglia e
veto. ``assicura_roster_stagione`` copia il file del checkout SOLO quando lo snapshot
non ha la stagione del click; ``database_at_instant(roster_fallback=...)`` lo applica.

Il repository non viene toccato: gli snapshot sono cartelle temporanee e
``main_head_at`` / ``extract_database_at`` sono sostituiti da fixture locali.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

logging.getLogger("streamlit").setLevel(logging.ERROR)

import config  # noqa: E402
import db_snapshot as DS  # noqa: E402
from season_rosters import ROSTER_FILENAME, load_season_rosters  # noqa: E402

REAL_ROSTER = os.path.join(HERE, "database", ROSTER_FILENAME)
INSTANT = datetime(2026, 9, 15, 15, 18, tzinfo=timezone.utc)   # stagione 2026/27
LEGHE = list(config.LEAGUES_CONFIG.keys())


def _json_senza(stagione: str, dst: str, leghe_senza=None) -> None:
    """Copia del file reale con la stagione tolta (in tutte le leghe o solo in alcune)."""
    with open(REAL_ROSTER, encoding="utf-8") as f:
        dati = json.load(f)
    for lega in (leghe_senza if leghe_senza is not None else dati):
        dati[lega].pop(stagione, None)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False)


def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="test_roster_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db = os.path.join(self.tmp, "snapshot_db")
        self.checkout = os.path.join(self.tmp, "checkout_db")
        os.makedirs(self.db)
        os.makedirs(self.checkout)


class TestAssicuraRosterStagione(_Tmp):

    def test_snapshot_senza_file_copia_il_checkout(self):
        shutil.copyfile(REAL_ROSTER, os.path.join(self.checkout, ROSTER_FILENAME))
        esito = DS.assicura_roster_stagione(self.db, INSTANT, checkout_dir=self.checkout)
        self.assertEqual("checkout", esito["fonte"])
        self.assertEqual(2026, esito["stagione"])
        self.assertEqual(sorted(LEGHE), sorted(esito["integrate"]))
        self.assertEqual([], esito["ancora_mancanti"])
        roster = load_season_rosters(self.db)
        for lega in LEGHE:
            self.assertIn(2026, roster[lega])

    def test_snapshot_con_la_stagione_resta_com_e(self):
        dst = os.path.join(self.db, ROSTER_FILENAME)
        shutil.copyfile(REAL_ROSTER, dst)
        prima = _sha(dst)
        shutil.copyfile(REAL_ROSTER, os.path.join(self.checkout, ROSTER_FILENAME))
        esito = DS.assicura_roster_stagione(self.db, INSTANT, checkout_dir=self.checkout)
        self.assertEqual("snapshot", esito["fonte"])
        self.assertEqual([], esito["mancanti_snapshot"])
        self.assertEqual([], esito["integrate"])
        self.assertEqual(prima, _sha(dst))          # nessuna copia: il file dello snapshot non si tocca

    def test_snapshot_con_il_file_ma_senza_la_stagione_usa_il_checkout(self):
        _json_senza("2026", os.path.join(self.db, ROSTER_FILENAME))
        shutil.copyfile(REAL_ROSTER, os.path.join(self.checkout, ROSTER_FILENAME))
        esito = DS.assicura_roster_stagione(self.db, INSTANT, checkout_dir=self.checkout)
        self.assertEqual("checkout", esito["fonte"])
        self.assertEqual(sorted(LEGHE), sorted(esito["mancanti_snapshot"]))
        self.assertEqual(2026, max(load_season_rosters(self.db)["Serie A"]))

    def test_stagione_mancante_solo_in_una_lega_integra_il_file_intero(self):
        _json_senza("2026", os.path.join(self.db, ROSTER_FILENAME), leghe_senza=["La Liga"])
        shutil.copyfile(REAL_ROSTER, os.path.join(self.checkout, ROSTER_FILENAME))
        esito = DS.assicura_roster_stagione(self.db, INSTANT, checkout_dir=self.checkout)
        self.assertEqual("checkout", esito["fonte"])
        self.assertEqual(["La Liga"], esito["mancanti_snapshot"])
        self.assertEqual(["La Liga"], esito["integrate"])
        self.assertEqual([], esito["ancora_mancanti"])
        self.assertIn(2026, load_season_rosters(self.db)["La Liga"])

    def test_checkout_senza_la_stagione_resta_assente_e_non_copia(self):
        _json_senza("2026", os.path.join(self.checkout, ROSTER_FILENAME))
        esito = DS.assicura_roster_stagione(self.db, INSTANT, checkout_dir=self.checkout)
        self.assertEqual("assente", esito["fonte"])
        self.assertEqual(sorted(LEGHE), sorted(esito["ancora_mancanti"]))
        self.assertFalse(os.path.exists(os.path.join(self.db, ROSTER_FILENAME)))

    def test_checkout_senza_file_e_assente(self):
        esito = DS.assicura_roster_stagione(self.db, INSTANT, checkout_dir=self.checkout)
        self.assertEqual("assente", esito["fonte"])
        self.assertFalse(os.path.exists(os.path.join(self.db, ROSTER_FILENAME)))

    def test_il_checkout_di_default_e_quello_del_repository(self):
        self.assertEqual(os.path.join(HERE, "database"), DS.CHECKOUT_DATABASE_DIR)
        self.assertTrue(os.path.isfile(os.path.join(DS.CHECKOUT_DATABASE_DIR, ROSTER_FILENAME)))

    def test_la_regola_e_documentata_nel_codice(self):
        doc = DS.assicura_roster_stagione.__doc__ or ""
        for frase in ("LECITO", "CALENDARIO", "PR #38", "EloSeedError", "LA REGOLA"):
            self.assertIn(frase, doc)


class _Fake(_Tmp):
    """``database_at_instant`` con commit e estrazione finti: nessun git, nessuna rete."""

    def setUp(self):
        super().setUp()
        self.estratti = 0

        def head(instant, ref=None, repo_root=None):
            return DS.CommitInfo(sha="c" * 40, committer_time=INSTANT, subject="fixture", ref="fixture")

        def estrai(sha, dest, repo_root=None):
            self.estratti += 1
            dir_db = os.path.join(dest, "SoccerMath", "database")
            os.makedirs(dir_db, exist_ok=True)
            _json_senza("2026", os.path.join(dir_db, ROSTER_FILENAME))   # lo snapshot storico non ha la stagione
            return dir_db

        for nome, fn in (("main_head_at", head), ("extract_database_at", estrai)):
            p = mock.patch.object(DS, nome, side_effect=fn)
            p.start()
            self.addCleanup(p.stop)
        self.checkout_patch = mock.patch.object(DS, "CHECKOUT_DATABASE_DIR", self.checkout)
        self.checkout_patch.start()
        self.addCleanup(self.checkout_patch.stop)
        shutil.copyfile(REAL_ROSTER, os.path.join(self.checkout, ROSTER_FILENAME))


class TestDatabaseAtInstantRoster(_Fake):

    def test_roster_fallback_false_lascia_lo_snapshot_com_e(self):
        """Lo snapshot storico ha il file SENZA la stagione 2026: con fallback spento resta cosi'."""
        with DS.database_at_instant(INSTANT, drop_future_rows=False, roster_fallback=False) as snap:
            self.assertEqual({}, snap.roster)
            self.assertTrue(os.path.isfile(os.path.join(snap.db_dir, ROSTER_FILENAME)))
            for lega in LEGHE:
                self.assertNotIn(2026, load_season_rosters(snap.db_dir).get(lega, {}))

    def test_roster_fallback_true_integra_il_checkout(self):
        with DS.database_at_instant(INSTANT, drop_future_rows=False, roster_fallback=True) as snap:
            self.assertEqual("checkout", snap.roster["fonte"])
            self.assertEqual(sorted(LEGHE), sorted(snap.roster["integrate"]))
            self.assertEqual([], snap.roster["ancora_mancanti"])
            self.assertIn(2026, load_season_rosters(snap.db_dir)["Serie A"])

    def test_default_e_roster_fallback_attivo(self):
        with DS.database_at_instant(INSTANT, drop_future_rows=False) as snap:
            self.assertEqual("checkout", snap.roster["fonte"])

    def test_cache_senza_roster_poi_con_roster_applica_il_fallback(self):
        """La cartella in cache scritta con roster_fallback=False non resta senza roster."""
        cache = os.path.join(self.tmp, "cache")
        with DS.database_at_instant(INSTANT, drop_future_rows=False, roster_fallback=False,
                                    cache_dir=cache) as a:
            self.assertEqual({}, a.roster)
        with DS.database_at_instant(INSTANT, drop_future_rows=False, roster_fallback=True,
                                    cache_dir=cache) as b:
            self.assertTrue(b._cached)
            self.assertEqual("checkout", b.roster["fonte"])
            self.assertIn(2026, load_season_rosters(b.db_dir)["Serie A"])
        self.assertEqual(1, self.estratti)            # una sola estrazione: la cache e' stata riusata
        with DS.database_at_instant(INSTANT, drop_future_rows=False, roster_fallback=True,
                                    cache_dir=cache) as c:
            self.assertTrue(c._cached)
            self.assertEqual("checkout", c.roster["fonte"])   # esito ricordato dal marker
        self.assertEqual(1, self.estratti)

    def test_il_repository_non_viene_modificato(self):
        """Il file del checkout non cambia: il ripiego copia, non sposta ne' scrive nel repo."""
        reale = os.path.join(DS.CHECKOUT_DATABASE_DIR, ROSTER_FILENAME)
        prima = _sha(reale)
        with DS.database_at_instant(INSTANT, drop_future_rows=False, roster_fallback=True):
            pass
        self.assertEqual(prima, _sha(reale))


if __name__ == "__main__":
    unittest.main()
