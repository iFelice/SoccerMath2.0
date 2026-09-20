"""Test di NON-leakage del replay walk-forward del Top Mix legacy.

Non ci si fida della logica: si costruisce un repository git SINTETICO con una
storia avvelenata e si dimostra che il replay, per la partita bersaglio
Inter-Roma del 12/09/2026 18:45Z, legge SOLO il commit anteriore al kickoff.

Storia del repo di prova (date = committer date, UTC):

    A  10/09 12:00  storia MD1-MD8 (+ archivio xG con la partita bersaglio
                    ancora "da giocare")
    B  12/09 10:00  risultati dell'11/09 (leciti: prima del kickoff) + una
                    riga POST-DATATA 20/10/2026 gia' con risultato (anomalia
                    reale vista nei CSV live)
    S  12/09 15:00  [branch side] il risultato della partita bersaglio, scritto
                    PRIMA del kickoff ma mergiato in main solo il 13/09: una
                    ``git log --until`` senza ``--first-parent`` lo sceglierebbe
    C  12/09 20:45  [avvelenato] risultato della partita bersaglio + xG di
                    Inter gonfiato + archivio xG con ``is_result: True``
    D  13/09 20:00  risultati del 13/09
    M  13/09 22:00  merge di S in main (HEAD)

Il click simulato all'istante T = kickoff - 1 s deve usare B, e le prove sono
esplicite: commit < T, risultato bersaglio assente dal CSV e dall'archivio xG
dello snapshot, riga post-datata scartata, cutoff xG = T. Il controllo positivo
(click un giorno dopo) DEVE invece vedere il risultato e far fallire il leak
check: una guardia che non puo' scattare non e' una guardia.

Poi la forma delle righe: identiche a quelle live (stesse chiavi, stesso
ordine) con la sola differenza ``model_variant`` (e quindi ``calculation_id``),
nessuna etichetta "ricostruita"; la fusione nel registro non tocca nessuna riga
esistente ed e' idempotente; la scrittura rifiuta un registro remoto illeggibile
o vuoto.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

logging.getLogger("streamlit").setLevel(logging.ERROR)

import db_snapshot  # noqa: E402
import replay_legacy_topmix as replay  # noqa: E402
from prediction_registry import (  # noqa: E402
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_FIELD,
    MODEL_VARIANT_LEGACY,
    dedup_key,
)

UTC = timezone.utc
LEAGUE = "Serie A"
TEAMS = ["Inter", "Milan", "Juventus", "Napoli", "Roma", "Lazio"]
TARGET_KICKOFF = datetime(2026, 9, 12, 18, 45, tzinfo=UTC)
T = TARGET_KICKOFF - timedelta(seconds=1)

CSV_HEADER = "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,Matchday\n"


def _ftr(h: int, a: int) -> str:
    return "H" if h > a else ("A" if a > h else "D")


def _row(giorno: str, home: str, away: str, h: int, a: int, md: int) -> str:
    return f"I1,{giorno},,{home},{away},{h},{a},{_ftr(h, a)},{md}\n"


# --- Storia sintetica: Inter vince sempre largo, Roma perde sempre -------------
def _history_rows():
    """MD1..MD8 (22/08 -> 10/09): tre partite per giornata, tutte concluse."""
    rows = []
    calendario = [
        ("22/08/2026", 1), ("25/08/2026", 2), ("29/08/2026", 3), ("01/09/2026", 4),
        ("04/09/2026", 5), ("06/09/2026", 6), ("08/09/2026", 7), ("10/09/2026", 8),
    ]
    coppie = [
        [("Inter", "Milan"), ("Juventus", "Roma"), ("Napoli", "Lazio")],
        [("Roma", "Inter"), ("Lazio", "Juventus"), ("Milan", "Napoli")],
        [("Inter", "Juventus"), ("Roma", "Lazio"), ("Napoli", "Milan")],
        [("Lazio", "Inter"), ("Milan", "Roma"), ("Juventus", "Napoli")],
        [("Inter", "Napoli"), ("Roma", "Milan"), ("Lazio", "Juventus")],
        [("Juventus", "Inter"), ("Lazio", "Roma"), ("Milan", "Napoli")],
        [("Inter", "Lazio"), ("Napoli", "Roma"), ("Juventus", "Milan")],
        [("Milan", "Inter"), ("Roma", "Napoli"), ("Lazio", "Juventus")],
    ]
    for (giorno, md), partite in zip(calendario, coppie):
        for home, away in partite:
            if home == "Inter":
                h, a = 4, 0
            elif away == "Inter":
                h, a = 0, 3
            elif home == "Roma":
                h, a = 0, 2
            elif away == "Roma":
                h, a = 3, 0
            else:
                h, a = 1, 1
            rows.append(_row(giorno, home, away, h, a, md))
    return rows


ROWS_A = _history_rows()
ROWS_B_EXTRA = [
    _row("11/09/2026", "Napoli", "Juventus", 0, 0, 9),     # lecita: prima del kickoff
    _row("20/10/2026", "Lazio", "Napoli", 1, 0, 15),       # POST-DATATA con risultato (anomalia)
]
ROW_TARGET = _row("12/09/2026", "Inter", "Roma", 3, 0, 9)  # la partita bersaglio (kickoff 18:45Z)
ROWS_D_EXTRA = [_row("13/09/2026", "Milan", "Lazio", 1, 1, 9)]

MD9 = [("2026-09-11 18:45:00", "Napoli", "Juventus"), ("2026-09-12 18:45:00", "Inter", "Roma"),
       ("2026-09-13 16:00:00", "Milan", "Lazio")]
MD10 = [("2026-09-19 18:45:00", "Roma", "Inter"), ("2026-09-19 18:45:00", "Juventus", "Milan"),
        ("2026-09-19 18:45:00", "Lazio", "Napoli")]


def _archive(results: dict) -> list:
    """Archivio Understat sintetico: MD9 + MD10; ``results`` = {(home, away): (h, a)}."""
    out, uid = [], 90000
    for dt, home, away in MD9 + MD10:
        uid += 1
        res = results.get((home, away))
        out.append({"season": 2026, "id": uid, "date": dt, "home_team": home, "away_team": away,
                    "home_goals": res[0] if res else None, "away_goals": res[1] if res else None,
                    "home_xg": 1.5 if res else None, "away_xg": 0.7 if res else None,
                    "is_result": bool(res)})
    return out


def _xg_json(inter_xg: float) -> dict:
    base = {t: {"xG_avg": 1.3, "xGA_avg": 1.3, "matches": 8} for t in TEAMS}
    base["Inter"] = {"xG_avg": inter_xg, "xGA_avg": 0.6, "matches": 8}
    base["Roma"] = {"xG_avg": 0.7, "xGA_avg": 2.0, "matches": 8}
    return base


def _git(repo: str, *args: str, when: str | None = None) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.com",
               GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.com")
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    r = subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout.strip()


def _write_db(db: str, rows: list, archive_results: dict, inter_xg: float) -> None:
    os.makedirs(db, exist_ok=True)
    with open(os.path.join(db, "SerieA_Live.csv"), "w", encoding="utf-8") as f:
        f.write(CSV_HEADER + "".join(rows))
    with open(os.path.join(db, "xg_serie_a.json"), "w", encoding="utf-8") as f:
        json.dump(_xg_json(inter_xg), f)
    with open(os.path.join(db, "xG archivio serie A.json"), "w", encoding="utf-8") as f:
        json.dump(_archive(archive_results), f)


def build_poisoned_repo(root: str) -> dict:
    """Costruisce il repo di prova e ritorna gli sha dei commit."""
    db = os.path.join(root, "SoccerMath", "database")
    _git(root, "init", "-q", "-b", "main")
    sha = {}
    _write_db(db, ROWS_A, {}, 1.9)
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "A storia", when="2026-09-10T12:00:00Z")
    sha["A"] = _git(root, "rev-parse", "HEAD")

    _write_db(db, ROWS_A + ROWS_B_EXTRA, {("Napoli", "Juventus"): (0, 0)}, 1.9)
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "B live 12/09 01:50", when="2026-09-12T10:00:00Z")
    sha["B"] = _git(root, "rev-parse", "HEAD")

    # branch side da A: risultato bersaglio con data anteriore al kickoff, merge dopo
    _git(root, "checkout", "-q", "-b", "side", sha["A"])
    _write_db(db, ROWS_A + [ROW_TARGET], {("Inter", "Roma"): (3, 0)}, 1.9)
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "S side leak", when="2026-09-12T15:00:00Z")
    sha["S"] = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-q", "main")

    _write_db(db, ROWS_A + ROWS_B_EXTRA + [ROW_TARGET],
              {("Napoli", "Juventus"): (0, 0), ("Inter", "Roma"): (3, 0)}, 3.5)   # xG Inter gonfiato
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "C avvelenato", when="2026-09-12T20:45:00Z")
    sha["C"] = _git(root, "rev-parse", "HEAD")

    _write_db(db, ROWS_A + ROWS_B_EXTRA + [ROW_TARGET] + ROWS_D_EXTRA,
              {("Napoli", "Juventus"): (0, 0), ("Inter", "Roma"): (3, 0), ("Milan", "Lazio"): (1, 1)}, 3.5)
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "D live 13/09", when="2026-09-13T20:00:00Z")
    sha["D"] = _git(root, "rev-parse", "HEAD")

    _git(root, "merge", "-q", "--no-ff", "-m", "M merge side", "-X", "ours", "side", when="2026-09-13T22:00:00Z")
    sha["M"] = _git(root, "rev-parse", "HEAD")
    return sha


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="sm_replay_leak_")
        cls.sha = build_poisoned_repo(cls.root)
        cls.head_db = os.path.join(cls.root, "SoccerMath", "database")
        cls.fixtures = replay.fixtures_from_csv_and_archive([LEAGUE], db_dir=cls.head_db)
        cls.target = next(f for f in cls.fixtures[LEAGUE]
                          if f.home == "Inter" and f.away == "Roma" and f.utc == TARGET_KICKOFF)
        cls.click = replay.simulate_click(T, cls.fixtures, targets=[cls.target], leagues=[LEAGUE],
                                          ref="HEAD", repo_root=cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)


class TestSnapshotPointInTime(_Base):
    def test_target_fixture_comes_from_head_with_result_and_exact_kickoff(self):
        self.assertTrue(self.target.finished)
        self.assertEqual((3, 0), (self.target.gh, self.target.ga))
        self.assertEqual("understat", self.target.kickoff_source)
        self.assertEqual(9, self.target.matchday)

    def test_snapshot_is_last_main_commit_before_kickoff(self):
        c = self.click.commit
        self.assertEqual(self.sha["B"], c.sha, "lo snapshot deve essere B (ultimo commit di main < T)")
        self.assertLess(c.committer_time, T)
        self.assertNotIn(c.sha, (self.sha["C"], self.sha["D"], self.sha["M"]))

    def test_first_parent_ignores_side_branch_merged_later(self):
        """La trappola e' reale: senza --first-parent git sceglierebbe S (15:00 < T)."""
        senza = _git(self.root, "log", "HEAD", f"--until={T.isoformat()}", "-1", "--format=%H")
        self.assertEqual(self.sha["S"], senza, "precondizione: la storia di prova deve rendere S il candidato ingenuo")
        self.assertNotEqual(self.sha["S"], self.click.commit.sha)
        self.assertEqual(self.sha["B"], db_snapshot.main_head_at(T, "HEAD", self.root).sha)

    def test_snapshot_database_does_not_contain_target_or_future_rows(self):
        with db_snapshot.database_at_instant(T, ref="HEAD", repo_root=self.root) as snap:
            with open(os.path.join(snap.db_dir, "SerieA_Live.csv"), encoding="utf-8") as f:
                csv = f.read()
            self.assertNotIn("Inter,Roma,3,0", csv)
            self.assertNotIn("20/10/2026", csv, "la riga post-datata deve essere stata scartata")
            self.assertIn("11/09/2026,,Napoli,Juventus", csv, "i dati leciti (pre-kickoff) restano")
            self.assertEqual({"SerieA_Live.csv": 1}, snap.future_rows_dropped)
            with open(os.path.join(snap.db_dir, "xG archivio serie A.json"), encoding="utf-8") as f:
                arch = json.load(f)
            bersaglio = [r for r in arch if r["home_team"] == "Inter" and r["away_team"] == "Roma"]
            self.assertEqual(1, len(bersaglio))
            self.assertFalse(bersaglio[0]["is_result"])
            with open(os.path.join(snap.db_dir, "xg_serie_a.json"), encoding="utf-8") as f:
                self.assertEqual(1.9, json.load(f)["Inter"]["xG_avg"], "xG di B, non quello gonfiato di C")

    def test_leak_checks_all_pass_for_the_honest_click(self):
        lk = self.click.leak
        self.assertTrue(lk.commit_before_instant)
        self.assertTrue(lk.targets_absent_from_live_csv)
        self.assertTrue(lk.targets_absent_from_xg_archive)
        self.assertTrue(lk.xg_cutoff_is_instant)
        self.assertEqual({"SerieA_Live.csv": 1}, lk.future_rows_dropped)
        self.assertTrue(lk.ok, lk.dettagli)

    def test_pool_contains_only_matches_after_instant(self):
        self.assertEqual(self.click.pool_sizes[LEAGUE],
                         sum(1 for f in self.fixtures[LEAGUE] if f.utc > T))
        self.assertGreaterEqual(self.click.selected[LEAGUE], 1)
        for variante in (MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY):
            for r in self.click.rows[variante]:
                self.assertGreater(datetime.fromisoformat(r["utcDate"].replace("Z", "+00:00")), T)

    def test_config_paths_restored_after_snapshot(self):
        import config
        from models import elo_engine, elo_engine_legacy
        self.assertTrue(str(config.DATABASE_DIR).endswith(os.path.join("SoccerMath", "database")))
        self.assertNotIn("sm_pit_db_", str(config.DATABASE_DIR))
        self.assertNotIn("sm_pit_db_", str(elo_engine.DATABASE_DIR))
        self.assertNotIn("sm_pit_db_", str(elo_engine_legacy.DATABASE_DIR))
        self.assertNotIn("sm_pit_db_", str(config.LEAGUES_CONFIG[LEAGUE]["live_csv"]))


class TestPositiveControl(_Base):
    """Le guardie devono SCATTARE quando il dato futuro c'e'."""

    def test_click_one_day_later_sees_the_result_and_fails_the_check(self):
        dopo = replay.simulate_click(T + timedelta(days=1), self.fixtures, targets=[self.target],
                                     leagues=[LEAGUE], ref="HEAD", repo_root=self.root)
        self.assertEqual(self.sha["C"], dopo.commit.sha)
        self.assertFalse(dopo.leak.targets_absent_from_live_csv)
        self.assertFalse(dopo.leak.targets_absent_from_xg_archive)
        self.assertFalse(dopo.leak.ok)
        self.assertTrue(any("LEAK" in d for d in dopo.leak.dettagli), dopo.leak.dettagli)

    def test_side_branch_ref_would_leak_and_is_flagged(self):
        """Replay su ref=side: S ha il risultato -> il referto dice FALLITO."""
        rep, clicks = replay.run_replay(self.fixtures, date(2026, 9, 12), date(2026, 9, 12),
                                        sorgente="csv", ref="side", repo_root=self.root,
                                        leagues=[LEAGUE], log=lambda s: None)
        self.assertEqual(1, len(clicks))
        self.assertEqual(self.sha["S"], clicks[0].commit.sha)
        self.assertFalse(rep.leak_ok)
        self.assertIn("FALLITO", replay.render_markdown(rep))

    def test_legacy_elo_numbers_differ_between_honest_and_poisoned_snapshot(self):
        from models.legacy_elo import predict_elo_probs_legacy
        with db_snapshot.database_at_instant(T, ref="HEAD", repo_root=self.root):
            onesto = predict_elo_probs_legacy("Inter", "Roma", LEAGUE)
        with db_snapshot.database_at_instant(T + timedelta(days=1), ref="HEAD", repo_root=self.root):
            avvelenato = predict_elo_probs_legacy("Inter", "Roma", LEAGUE)
        self.assertNotEqual(onesto["1"], avvelenato["1"],
                            "il risultato bersaglio e lo xG gonfiato devono cambiare l'Elo legacy: "
                            "se non lo fanno, il test non sta misurando nulla")


class TestRowShape(_Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.legacy = replay.entries_for_targets(cls.click, MODEL_VARIANT_LEGACY)
        cls.current = replay.entries_for_targets(cls.click, MODEL_VARIANT_CURRENT)

    def test_target_is_above_threshold_in_both_variants(self):
        self.assertEqual(1, len(self.legacy), [r["home"] + "-" + r["away"] for r in self.click.rows[MODEL_VARIANT_LEGACY]])
        self.assertEqual(1, len(self.current))
        self.assertEqual(("Inter", "Roma"), (self.legacy[0]["home"], self.legacy[0]["away"]))

    def test_row_identical_to_live_row_except_model_variant(self):
        import app
        leg, cur = self.legacy[0], self.current[0]
        self.assertEqual(list(leg.keys()), list(cur.keys()), "stesse chiavi, stesso ordine")
        diverse = {k for k in leg if leg[k] != cur[k]}
        self.assertEqual({MODEL_VARIANT_FIELD, "calculation_id"}, diverse)
        self.assertEqual(MODEL_VARIANT_LEGACY, leg[MODEL_VARIANT_FIELD])
        # forma di produzione: le chiavi sono quelle di build_prediction_entry
        riga = next(r for r in self.click.rows[MODEL_VARIANT_LEGACY] if str(r["match_id"]) == str(self.target.match_id))
        args, kwargs = app.argomenti_registro_top_mix(riga, model_variant=MODEL_VARIANT_LEGACY)
        live = app.build_prediction_entry(*args, **kwargs)
        self.assertEqual(list(live.keys()), list(leg.keys()))

    def test_no_reconstruction_label_anywhere(self):
        testo = json.dumps(self.legacy[0], ensure_ascii=False).lower()
        for parola in ("ricostr", "replay", "walk", "reconstruct", "backfill"):
            self.assertNotIn(parola, testo)

    def test_graded_with_final_score_and_stamped_with_snapshot(self):
        import app
        leg = self.legacy[0]
        self.assertEqual("3-0", leg["risultato_reale"])
        self.assertIn(leg["esito"], ("✅", "❌"))
        self.assertEqual(self.click.commit.short, leg["data_snapshot_sha"])
        self.assertEqual(T.astimezone(app.ITALY_TZ).strftime("%d/%m/%Y %H:%M"), leg["salvato_il"])
        self.assertEqual(TARGET_KICKOFF.strftime("%Y-%m-%dT%H:%M:%SZ"), leg["kickoff_utc"])
        self.assertEqual("top_mix", leg["origin"])
        self.assertEqual(9, leg["giornata"])


class TestRegistryMerge(_Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.legacy = replay.entries_for_targets(cls.click, MODEL_VARIANT_LEGACY)
        cls.current = replay.entries_for_targets(cls.click, MODEL_VARIANT_CURRENT)

    def _existing(self):
        graduata = dict(self.current[0]); graduata["esito"] = "❌"; graduata["risultato_reale"] = "0-0"
        pendente = dict(self.current[0]); pendente["match_id"] = 777; pendente["esito"] = "⏳"; pendente["risultato_reale"] = None
        rapida = dict(self.current[0]); rapida["origin"] = "analisi_rapida"; rapida["tipo"] = "Analisi Rapida"
        vecchia = {"match_id": 555, "home": "X", "away": "Y", "esito": "✅", "pronostico_sicuro": "GG - Top Mix"}
        return [graduata, pendente, rapida, vecchia]

    def test_existing_rows_untouched_and_only_legacy_added(self):
        existing = self._existing()
        before = json.dumps(existing, sort_keys=True, ensure_ascii=False)
        merged, azioni = replay.merge_entries(existing, self.legacy)
        self.assertEqual(before, json.dumps(existing, sort_keys=True, ensure_ascii=False), "input non mutato")
        self.assertEqual(len(existing) + 1, len(merged))
        self.assertEqual(existing, merged[:len(existing)])
        self.assertEqual({"aggiunta": 1}, dict(azioni))
        self.assertEqual(MODEL_VARIANT_LEGACY, merged[-1][MODEL_VARIANT_FIELD])
        # la riga current graduata della STESSA partita resta com'era
        stessa = [p for p in merged if str(p.get("match_id")) == str(self.target.match_id)
                  and p.get("origin") == "top_mix"]
        self.assertEqual(2, len(stessa))
        self.assertEqual({MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY}, {p[MODEL_VARIANT_FIELD] for p in stessa})
        self.assertNotEqual(dedup_key(stessa[0]), dedup_key(stessa[1]))

    def test_rerun_is_idempotent(self):
        merged, _ = replay.merge_entries(self._existing(), self.legacy)
        again, azioni = replay.merge_entries(merged, self.legacy)
        self.assertEqual(merged, again)
        self.assertEqual({"gia_presente": 1}, dict(azioni))

    def test_current_rows_are_refused(self):
        with self.assertRaises(replay.ReplayError):
            replay.merge_entries(self._existing(), self.current)

    def test_write_refuses_unreadable_or_empty_remote(self):
        import config

        class _Resp:
            def __init__(self, status, payload=None):
                self.status_code = status
                self._payload = payload

            def json(self):
                return self._payload

        with mock.patch.object(config, "JSONBIN_API_KEY", "k"), \
             mock.patch.object(config, "JSONBIN_BIN_ID", "b"), \
             mock.patch.object(replay, "database_at_instant"):
            import requests
            with mock.patch.object(requests, "get", return_value=_Resp(500)):
                with self.assertRaises(replay.ReplayError):
                    replay.write_to_registry(self.legacy, dry_run=True)
            with mock.patch.object(requests, "get", return_value=_Resp(200, {"record": {"data": []}})):
                with self.assertRaises(replay.ReplayError):
                    replay.write_to_registry(self.legacy, dry_run=True)
            with mock.patch.object(requests, "get", return_value=_Resp(200, {"record": {"data": self._existing()}})), \
                 mock.patch.object(requests, "put") as put:
                esito = replay.write_to_registry(self.legacy, dry_run=True)
                self.assertFalse(esito["scritto"])
                self.assertEqual({"aggiunta": 1}, esito["azioni"])
                put.assert_not_called()


class TestReportEndToEnd(_Base):
    def test_run_replay_offline_report(self):
        rep, clicks = replay.run_replay(self.fixtures, date(2026, 9, 12), date(2026, 9, 12),
                                        sorgente="csv", ref="HEAD", repo_root=self.root,
                                        leagues=[LEAGUE], log=lambda s: None)
        self.assertTrue(rep.leak_ok)
        self.assertEqual(1, len(clicks))
        self.assertEqual(self.sha["B"], clicks[0].commit.sha)
        self.assertEqual(1, len(rep.entries_legacy))
        md = replay.render_markdown(rep)
        self.assertIn("Leak check complessivo: OK", md)
        self.assertIn(self.sha["B"][:12], md)
        self.assertIn("Inter-Roma", md)
        self.assertNotIn("FALLITO", md)


if __name__ == "__main__":
    unittest.main()
