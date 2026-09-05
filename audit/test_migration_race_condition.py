#!/usr/bin/env python3
"""
audit/test_migration_race_condition.py

Test della protezione anti race-condition nella migrazione del Registro
Predizioni (audit/tag_pre_shrinkage_predictions.py).

Scenario difeso
---------------
1. viene letto il registro remoto A;
2. la migrazione viene calcolata su A;
3. prima della PUT serve un backup;
4. nel frattempo l'app aggiunge/modifica una predizione -> il remoto diventa B;
5. una PUT ingenua sovrascriverebbe B con dati derivati da A, perdendo la
   scrittura concorrente.

Difesa implementata e verificata qui:
  - la PRIMA GET produce uno snapshot IMMUTABILE con fingerprint SHA-256
    della serializzazione canonica;
  - il backup e' prodotto ESATTAMENTE da quello snapshot (nessuna seconda GET);
  - subito prima della PUT si rilegge il bin e si confronta il CONTENUTO
    COMPLETO canonicalizzato (mai il solo conteggio dei record);
  - qualsiasi differenza -> RemoteChangedError, nessuna PUT, backup conservato.

Esecuzione:
    python -m unittest audit.test_migration_race_condition -v
    python audit/test_migration_race_condition.py

NESSUN test contatta davvero JSONBin: la rete e' sostituita da un doppio di
test (FakeBin) che registra ogni richiesta effettuata.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_AUDIT_DIR = _REPO_ROOT / "audit"
_SOCCERMATH_DIR = _REPO_ROOT / "SoccerMath"
for _p in (str(_SOCCERMATH_DIR), str(_AUDIT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tag_pre_shrinkage_predictions as mig  # noqa: E402


# ---------------------------------------------------------------------------
# Dati di test
# ---------------------------------------------------------------------------
def _entry(home, away, salvato_il, prob=70.0, esito="\u23f3", **extra):
    """Record di registro minimale ma realistico."""
    e = {
        "home": home,
        "away": away,
        "campionato": "Premier League",
        "giornata": 3,
        "data": "05/09/2026 16:00",
        "pronostico_sicuro": f"NG - {prob}% - Top Mix Automatico",
        "mercato_standard": "NG",
        "prob_sicuro": prob,
        "risultato_reale": "",
        "esito": esito,
        "tipo": "Top Mix",
        "stagione": "2026/2027",
        "salvato_il": salvato_il,
    }
    e.update(extra)
    return e


# Salvate PRIMA del commit di fix (2026-09-04 15:40:10 UTC = 17:40:10 Rome).
PRE_FIX_A = _entry("Man City", "Coventry City", "04/09/2026 17:35", prob=99.8)
PRE_FIX_B = _entry("Hull City", "Aston Villa", "04/09/2026 17:35", prob=99.8)
# Stagione precedente -> legacy.
LEGACY = _entry("Old", "Season", "14/03/2026 09:00", prob=61.0,
                data="15/03/2026 20:45", stagione="2025/2026", esito="\u2705")

BASE_REGISTRY = [PRE_FIX_A, PRE_FIX_B, LEGACY]


class FakeBin:
    """Doppio di test di JSONBin che registra ogni richiesta.

    ``state`` e' il contenuto corrente del bin. ``mutate_after_reads`` permette
    di simulare una scrittura concorrente dell'app: dopo N letture lo stato
    cambia, riproducendo esattamente la finestra di race.
    """

    def __init__(self, records, mutate_after_reads=None, mutation=None):
        self.state = json.loads(json.dumps(records))  # deep copy
        self.requests = []            # ("GET"|"PUT", payload)
        self._reads = 0
        self._mutate_after_reads = mutate_after_reads
        self._mutation = mutation

    # -- lato lettura -------------------------------------------------------
    def read(self):
        self.requests.append(("GET", None))
        self._reads += 1
        snapshot = json.loads(json.dumps(self.state))
        if (self._mutate_after_reads is not None
                and self._reads == self._mutate_after_reads
                and self._mutation is not None):
            # La mutazione avviene DOPO aver servito questa lettura: la GET
            # successiva vedra' lo stato nuovo.
            self.state = self._mutation(json.loads(json.dumps(self.state)))
        return snapshot

    # -- lato scrittura -----------------------------------------------------
    def write(self, payload):
        self.requests.append(("PUT", payload))
        self.state = json.loads(json.dumps(payload))

    # -- helper -------------------------------------------------------------
    @property
    def puts(self):
        return [r for r in self.requests if r[0] == "PUT"]

    @property
    def gets(self):
        return [r for r in self.requests if r[0] == "GET"]


class _FakeResponse:
    status_code = 200
    text = "OK"


class RaceConditionTestCase(unittest.TestCase):
    """Base con patching di rete e filesystem temporaneo."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmp.name)
        self._orig_fetch = mig._fetch_remote_records
        self._orig_require = mig._require_remote_config
        self._orig_bin_id = mig.JSONBIN_BIN_ID
        self._orig_key = mig.JSONBIN_API_KEY
        # Credenziali fittizie: nessuna rete reale viene mai toccata.
        mig.JSONBIN_BIN_ID = "fake-bin"
        mig.JSONBIN_API_KEY = "fake-key"
        mig._require_remote_config = lambda: None

    def tearDown(self):
        mig._fetch_remote_records = self._orig_fetch
        mig._require_remote_config = self._orig_require
        mig.JSONBIN_BIN_ID = self._orig_bin_id
        mig.JSONBIN_API_KEY = self._orig_key
        self.tmp.cleanup()

    def wire(self, fake: FakeBin):
        """Collega FakeBin alle funzioni di rete del modulo."""
        mig._fetch_remote_records = lambda timeout=15: (fake.read(), "FakeBin (test)")

        class _FakeRequests:
            @staticmethod
            def put(url, json=None, headers=None, timeout=None):
                fake.write(json)
                return _FakeResponse()

        # _apply importa 'requests' localmente: lo intercetto in sys.modules.
        self._orig_requests = sys.modules.get("requests")
        sys.modules["requests"] = _FakeRequests
        self.addCleanup(self._restore_requests)

    def _restore_requests(self):
        if self._orig_requests is not None:
            sys.modules["requests"] = self._orig_requests
        else:
            sys.modules.pop("requests", None)

    def paths(self):
        return (self.tmpdir / "predictions.json",
                self.tmpdir / "backup.json.bak")


# ---------------------------------------------------------------------------
# 1. Remoto invariato -> scrittura consentita
# ---------------------------------------------------------------------------
class TestRemoteUnchangedAllowsWrite(RaceConditionTestCase):

    def test_unchanged_remote_allows_put(self):
        fake = FakeBin(BASE_REGISTRY)
        self.wire(fake)
        out, bak = self.paths()

        snapshot = mig.fetch_remote_snapshot()
        changed, kept, _, remote_backup = mig._apply(
            snapshot, out, push_remote=True, remote_backup=bak)

        self.assertEqual(len(fake.puts), 1, "deve esserci esattamente una PUT")
        self.assertEqual(changed, 2, "le due entry pre-fix vanno taggate")
        self.assertEqual(kept, 1, "la entry legacy resta invariata")
        self.assertEqual(remote_backup, bak)

        written = fake.puts[0][1]["data"]
        self.assertEqual(len(written), 3, "nessuna entry persa")
        tagged = [e for e in written
                  if e.get("model_version") == mig_pre_fix_version()]
        self.assertEqual(len(tagged), 2)

    def test_put_payload_preserves_untouched_fields(self):
        fake = FakeBin(BASE_REGISTRY)
        self.wire(fake)
        out, bak = self.paths()

        snapshot = mig.fetch_remote_snapshot()
        mig._apply(snapshot, out, push_remote=True, remote_backup=bak)

        written = fake.puts[0][1]["data"]
        for original, result in zip(BASE_REGISTRY, written):
            for field in ("prob_sicuro", "esito", "risultato_reale",
                          "pronostico_sicuro", "data", "salvato_il"):
                self.assertEqual(original[field], result[field],
                                 f"campo '{field}' non deve cambiare")


def mig_pre_fix_version():
    from prediction_registry import MODEL_VERSION_PRE_FIX
    return MODEL_VERSION_PRE_FIX


# ---------------------------------------------------------------------------
# 2. Nuova predizione aggiunta tra GET e PUT -> abort
# ---------------------------------------------------------------------------
class TestConcurrentInsertAborts(RaceConditionTestCase):

    def test_new_prediction_between_read_and_put_aborts(self):
        def add_entry(state):
            state.append(_entry("Nuova", "Partita", "05/09/2026 12:00", prob=55.0))
            return state

        # La mutazione scatta dopo la 1a lettura (lo snapshot): la GET di
        # verifica pre-PUT vedra' il registro gia' cambiato.
        fake = FakeBin(BASE_REGISTRY, mutate_after_reads=1, mutation=add_entry)
        self.wire(fake)
        out, bak = self.paths()

        snapshot = mig.fetch_remote_snapshot()
        self.assertEqual(snapshot.count, 3)

        with self.assertRaises(mig.RemoteChangedError) as ctx:
            mig._apply(snapshot, out, push_remote=True, remote_backup=bak)

        self.assertIn("Remote registry changed since read", str(ctx.exception))
        self.assertEqual(len(fake.puts), 0, "nessuna PUT deve essere eseguita")
        # La entry aggiunta dall'app e' ancora nel bin: non e' stata persa.
        self.assertEqual(len(fake.state), 4)


# ---------------------------------------------------------------------------
# 3. Modifica di una predizione esistente -> abort
# ---------------------------------------------------------------------------
class TestConcurrentUpdateAborts(RaceConditionTestCase):

    def test_modified_existing_prediction_aborts(self):
        def set_result(state):
            # L'app registra l'esito reale di una partita gia' presente.
            state[0]["risultato_reale"] = "2-0"
            state[0]["esito"] = "\u2705"
            return state

        fake = FakeBin(BASE_REGISTRY, mutate_after_reads=1, mutation=set_result)
        self.wire(fake)
        out, bak = self.paths()

        snapshot = mig.fetch_remote_snapshot()
        with self.assertRaises(mig.RemoteChangedError):
            mig._apply(snapshot, out, push_remote=True, remote_backup=bak)

        self.assertEqual(len(fake.puts), 0)
        # L'esito scritto dall'app sopravvive.
        self.assertEqual(fake.state[0]["risultato_reale"], "2-0")

    def test_single_field_change_is_detected(self):
        """Anche un solo campo modificato deve far abortire."""
        def tweak(state):
            state[1]["giornata"] = 4          # differenza minima
            return state

        fake = FakeBin(BASE_REGISTRY, mutate_after_reads=1, mutation=tweak)
        self.wire(fake)
        out, bak = self.paths()

        snapshot = mig.fetch_remote_snapshot()
        with self.assertRaises(mig.RemoteChangedError):
            mig._apply(snapshot, out, push_remote=True, remote_backup=bak)
        self.assertEqual(len(fake.puts), 0)


# ---------------------------------------------------------------------------
# 4. Stesso numero di record ma contenuto diverso -> abort
# ---------------------------------------------------------------------------
class TestSameCountDifferentContentAborts(RaceConditionTestCase):

    def test_same_length_different_content_aborts(self):
        def swap_entry(state):
            # Una entry rimossa e una aggiunta: la LUNGHEZZA resta 3.
            state[2] = _entry("Sostituita", "Entry", "05/09/2026 09:00", prob=48.0)
            return state

        fake = FakeBin(BASE_REGISTRY, mutate_after_reads=1, mutation=swap_entry)
        self.wire(fake)
        out, bak = self.paths()

        snapshot = mig.fetch_remote_snapshot()
        self.assertEqual(snapshot.count, 3)
        self.assertEqual(len(fake.state), 3, "il conteggio non cambia")

        with self.assertRaises(mig.RemoteChangedError) as ctx:
            mig._apply(snapshot, out, push_remote=True, remote_backup=bak)

        msg = str(ctx.exception)
        self.assertIn("Remote registry changed since read", msg)
        self.assertIn("stesso numero di entry", msg,
                      "il messaggio deve chiarire che il conteggio coincide")
        self.assertEqual(len(fake.puts), 0)

    def test_count_alone_is_not_the_criterion(self):
        """Il fingerprint distingue registri con identico numero di record."""
        a = [PRE_FIX_A, PRE_FIX_B, LEGACY]
        b = [PRE_FIX_A, PRE_FIX_B,
             _entry("Diversa", "Entry", "01/09/2026 09:00", prob=61.0)]
        self.assertEqual(len(a), len(b))
        self.assertNotEqual(mig.fingerprint(a), mig.fingerprint(b))

    def test_reordering_is_detected(self):
        """Un riordino e' una modifica reale del registro."""
        a = [PRE_FIX_A, PRE_FIX_B, LEGACY]
        b = [PRE_FIX_B, PRE_FIX_A, LEGACY]
        self.assertEqual(len(a), len(b))
        self.assertNotEqual(mig.fingerprint(a), mig.fingerprint(b))

    def test_key_order_does_not_cause_false_positive(self):
        """L'ordine delle chiavi in un dict non e' una modifica semantica."""
        original = dict(PRE_FIX_A)
        reordered = {k: original[k] for k in reversed(list(original.keys()))}
        self.assertEqual(mig.fingerprint([original]), mig.fingerprint([reordered]))


# ---------------------------------------------------------------------------
# 5. Backup identico allo snapshot iniziale
# ---------------------------------------------------------------------------
class TestBackupMatchesSnapshot(RaceConditionTestCase):

    def test_backup_equals_initial_snapshot(self):
        fake = FakeBin(BASE_REGISTRY)
        self.wire(fake)
        out, bak = self.paths()

        snapshot = mig.fetch_remote_snapshot()
        mig._apply(snapshot, out, push_remote=True, remote_backup=bak)

        saved = json.loads(bak.read_text(encoding="utf-8"))["data"]
        self.assertEqual(saved, BASE_REGISTRY,
                         "il backup deve contenere il registro PRE-migrazione")
        self.assertEqual(mig.fingerprint(saved), snapshot.fingerprint)

    def test_backup_comes_from_snapshot_not_from_a_new_get(self):
        """Se il remoto cambia dopo lo snapshot, il backup resta lo snapshot.

        E' il cuore della correzione: prima il backup veniva da una GET
        separata e poteva quindi contenere dati diversi da quelli migrati.
        """
        def add_entry(state):
            state.append(_entry("Concorrente", "Scrittura", "05/09/2026 12:00"))
            return state

        fake = FakeBin(BASE_REGISTRY, mutate_after_reads=1, mutation=add_entry)
        self.wire(fake)
        out, bak = self.paths()

        snapshot = mig.fetch_remote_snapshot()
        with self.assertRaises(mig.RemoteChangedError):
            mig._apply(snapshot, out, push_remote=True, remote_backup=bak)

        saved = json.loads(bak.read_text(encoding="utf-8"))["data"]
        self.assertEqual(len(saved), 3, "il backup e' lo snapshot, non lo stato mutato")
        self.assertEqual(mig.fingerprint(saved), snapshot.fingerprint)

    def test_backup_sidecar_hash_matches(self):
        fake = FakeBin(BASE_REGISTRY)
        self.wire(fake)
        out, bak = self.paths()

        snapshot = mig.fetch_remote_snapshot()
        mig._apply(snapshot, out, push_remote=True, remote_backup=bak)

        sidecar = bak.with_suffix(bak.suffix + ".sha256")
        self.assertTrue(sidecar.exists(), "deve esistere il file .sha256")
        self.assertIn(snapshot.fingerprint, sidecar.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 6. In caso di abort nessuna PUT eseguita (+ backup conservato)
# ---------------------------------------------------------------------------
class TestAbortPerformsNoPut(RaceConditionTestCase):

    def _run_abort(self, mutation):
        fake = FakeBin(BASE_REGISTRY, mutate_after_reads=1, mutation=mutation)
        self.wire(fake)
        out, bak = self.paths()
        snapshot = mig.fetch_remote_snapshot()
        with self.assertRaises(mig.RemoteChangedError):
            mig._apply(snapshot, out, push_remote=True, remote_backup=bak)
        return fake, bak, snapshot

    def test_no_put_on_insert(self):
        fake, bak, _ = self._run_abort(
            lambda s: s + [_entry("X", "Y", "05/09/2026 12:00")])
        self.assertEqual(len(fake.puts), 0)
        self.assertEqual([m for m, _ in fake.requests], ["GET", "GET"],
                         "solo letture: snapshot + verifica pre-PUT")

    def test_no_put_on_update(self):
        def mod(s):
            s[0]["prob_sicuro"] = 12.3
            return s
        fake, bak, _ = self._run_abort(mod)
        self.assertEqual(len(fake.puts), 0)

    def test_backup_is_kept_after_abort(self):
        fake, bak, snapshot = self._run_abort(
            lambda s: s + [_entry("X", "Y", "05/09/2026 12:00")])
        self.assertTrue(bak.exists(), "il backup deve sopravvivere all'abort")
        saved = json.loads(bak.read_text(encoding="utf-8"))["data"]
        self.assertEqual(mig.fingerprint(saved), snapshot.fingerprint)

    def test_remote_state_untouched_after_abort(self):
        fake, _, _ = self._run_abort(
            lambda s: s + [_entry("X", "Y", "05/09/2026 12:00")])
        # Il bin contiene ancora la scrittura concorrente, non i dati migrati.
        self.assertEqual(len(fake.state), 4)
        self.assertFalse(any("model_version" in e for e in fake.state),
                         "nessun tag deve essere stato scritto sul remoto")

    def test_cli_returns_exit_code_3_on_abort(self):
        def add_entry(state):
            state.append(_entry("Concorrente", "Scrittura", "05/09/2026 12:00"))
            return state

        fake = FakeBin(BASE_REGISTRY, mutate_after_reads=1, mutation=add_entry)
        self.wire(fake)
        out, bak = self.paths()
        rc = mig.main(["--remote", "--apply", "--push-remote",
                       "--output", str(out), "--backup-path", str(bak)])
        self.assertEqual(rc, 3, "l'abort deve avere exit code dedicato")
        self.assertEqual(len(fake.puts), 0)


# ---------------------------------------------------------------------------
# Snapshot immutabile
# ---------------------------------------------------------------------------
class TestSnapshotImmutability(RaceConditionTestCase):

    def test_mutating_returned_records_does_not_affect_snapshot(self):
        snap = mig.RemoteSnapshot(BASE_REGISTRY, "test")
        fp_before = snap.fingerprint
        got = snap.records
        got.append({"injected": True})
        got[0]["prob_sicuro"] = 0.1
        self.assertEqual(snap.count, 3)
        self.assertEqual(snap.fingerprint, fp_before)
        self.assertNotIn("injected", json.dumps(snap.records))

    def test_mutating_source_list_does_not_affect_snapshot(self):
        source = [dict(PRE_FIX_A)]
        snap = mig.RemoteSnapshot(source, "test")
        fp_before = snap.fingerprint
        source[0]["prob_sicuro"] = 1.0
        source.append(dict(LEGACY))
        self.assertEqual(snap.fingerprint, fp_before)
        self.assertEqual(snap.count, 1)

    def test_matches_is_content_based(self):
        snap = mig.RemoteSnapshot(BASE_REGISTRY, "test")
        self.assertTrue(snap.matches(json.loads(json.dumps(BASE_REGISTRY))))
        changed = json.loads(json.dumps(BASE_REGISTRY))
        changed[0]["esito"] = "\u274c"
        self.assertFalse(snap.matches(changed))


# ---------------------------------------------------------------------------
# Canonicalizzazione numerica del fingerprint
# ---------------------------------------------------------------------------
class TestNumericCanonicalization(unittest.TestCase):
    """JSON non distingue 1 da 1.0: non devono generare abort spuri.

    Il confronto avviene sempre sulla struttura parsata, mai sul body HTTP
    grezzo, quindi spaziatura e forma testuale dei numeri sono irrilevanti.
    """

    def assertSameFingerprint(self, a, b, msg=""):
        self.assertEqual(mig.fingerprint(a), mig.fingerprint(b), msg)

    def assertDifferentFingerprint(self, a, b, msg=""):
        self.assertNotEqual(mig.fingerprint(a), mig.fingerprint(b), msg)

    # -- equivalenze numeriche ---------------------------------------------
    def test_int_and_float_are_equivalent(self):
        self.assertSameFingerprint([{"giornata": 1}], [{"giornata": 1.0}],
                                   "1 e 1.0 sono lo stesso valore JSON")

    def test_trailing_zeros_are_equivalent(self):
        """``1.00`` parsato da JSON deve coincidere con ``1``."""
        parsed = json.loads('[{"giornata": 1.00}]')
        self.assertSameFingerprint([{"giornata": 1}], parsed)

    def test_exponent_notation_is_equivalent(self):
        parsed = json.loads('[{"v": 1e2}]')
        self.assertSameFingerprint([{"v": 100}], parsed)

    def test_probability_trailing_zero_is_equivalent(self):
        """Caso realistico: prob_sicuro 99.8 riscritto come 99.80."""
        parsed = json.loads('[{"prob_sicuro": 99.80}]')
        self.assertSameFingerprint([{"prob_sicuro": 99.8}], parsed)

    def test_negative_zero_equals_zero(self):
        self.assertSameFingerprint([{"v": -0.0}], [{"v": 0}])

    def test_nested_numbers_are_normalized(self):
        self.assertSameFingerprint([{"top3": {"odds": [1, 2]}}],
                                   [{"top3": {"odds": [1.0, 2.0]}}])

    def test_whole_registry_reserialization_is_stable(self):
        """Un round-trip JSON del registro non cambia il fingerprint."""
        reparsed = json.loads(json.dumps(BASE_REGISTRY))
        self.assertSameFingerprint(BASE_REGISTRY, reparsed)

    # -- distinzioni che devono restare -------------------------------------
    def test_true_is_not_one(self):
        self.assertDifferentFingerprint([{"v": True}], [{"v": 1}],
                                        "true non e' 1")

    def test_false_is_not_zero(self):
        self.assertDifferentFingerprint([{"v": False}], [{"v": 0}],
                                        "false non e' 0")

    def test_true_is_not_one_point_zero(self):
        self.assertDifferentFingerprint([{"v": True}], [{"v": 1.0}])

    def test_bool_field_realistic(self):
        """excluded_from_current_model_stats: False non deve valere 0."""
        self.assertDifferentFingerprint(
            [{"excluded_from_current_model_stats": False}],
            [{"excluded_from_current_model_stats": 0}])

    def test_real_numeric_change_is_detected(self):
        self.assertDifferentFingerprint([{"v": 1.0}], [{"v": 1.01}],
                                        "1.0 e 1.01 sono valori diversi")

    def test_string_number_is_not_number(self):
        self.assertDifferentFingerprint([{"v": "1"}], [{"v": 1}])

    def test_none_is_not_zero(self):
        self.assertDifferentFingerprint([{"v": None}], [{"v": 0}])

    def test_key_order_is_irrelevant(self):
        self.assertSameFingerprint([{"a": 1, "b": 2}], [{"b": 2, "a": 1}])

    def test_entry_order_is_relevant(self):
        self.assertDifferentFingerprint([{"a": 1}, {"b": 2}],
                                        [{"b": 2}, {"a": 1}])

    # -- integrazione: nessun abort spurio ----------------------------------
    def test_int_float_rewrite_does_not_abort(self):
        """Se il bin riscrive 1 come 1.0, la PUT deve restare consentita."""
        original = [_entry("A", "B", "04/09/2026 17:35", prob=70)]
        snap = mig.RemoteSnapshot(original, "test")
        rewritten = json.loads(json.dumps(original).replace('"giornata": 3',
                                                            '"giornata": 3.0'))
        self.assertTrue(snap.matches(rewritten),
                        "una riscrittura numerica equivalente non deve abortire")


class TestNumericCanonicalizationNoSpuriousAbort(RaceConditionTestCase):

    def test_put_allowed_when_remote_reserializes_numbers(self):
        """Il remoto restituisce gli stessi dati con int al posto di float."""
        original = [
            _entry("Man City", "Coventry City", "04/09/2026 17:35", prob=99.8,
                   giornata=3),
        ]

        def reserialize(state):
            # Stesso valore logico, forma diversa: 3 -> 3.0
            for e in state:
                e["giornata"] = float(e["giornata"])
            return state

        fake = FakeBin(original, mutate_after_reads=1, mutation=reserialize)
        self.wire(fake)
        out, bak = self.paths()

        snapshot = mig.fetch_remote_snapshot()
        changed, kept, _, _ = mig._apply(snapshot, out, push_remote=True,
                                         remote_backup=bak)
        self.assertEqual(len(fake.puts), 1,
                         "nessun abort spurio per 3 vs 3.0")
        self.assertEqual(changed, 1)


# ---------------------------------------------------------------------------
# Nessun file locale stale dopo un abort remoto
# ---------------------------------------------------------------------------
class TestNoStaleLocalFileOnAbort(RaceConditionTestCase):
    """Se la PUT viene abortita, il registro locale non deve restare
    derivato dallo snapshot stale: l'app lo userebbe come fallback."""

    def _abort_run(self, out: Path, bak: Path):
        fake = FakeBin(
            BASE_REGISTRY, mutate_after_reads=1,
            mutation=lambda s: s + [_entry("Concorrente", "Scrittura",
                                           "05/09/2026 12:00")])
        self.wire(fake)
        snapshot = mig.fetch_remote_snapshot()
        with self.assertRaises(mig.RemoteChangedError):
            mig._apply(snapshot, out, push_remote=True, remote_backup=bak)
        return fake, snapshot

    def test_no_local_file_created_when_none_existed(self):
        out, bak = self.paths()
        self.assertFalse(out.exists())
        fake, _ = self._abort_run(out, bak)
        self.assertEqual(len(fake.puts), 0)
        self.assertFalse(out.exists(),
                         "non deve essere creato un predictions.json stale")

    def test_existing_local_file_is_byte_identical(self):
        out, bak = self.paths()
        original = json.dumps(
            {"data": [{"home": "PRE", "away": "ESISTENTE",
                       "salvato_il": "01/01/2026 10:00"}]},
            ensure_ascii=False, indent=2)
        out.write_text(original, encoding="utf-8")
        before = out.read_bytes()

        fake, _ = self._abort_run(out, bak)

        self.assertEqual(len(fake.puts), 0)
        self.assertEqual(out.read_bytes(), before,
                         "il file locale preesistente deve restare identico")

    def test_no_local_backup_side_effect_on_abort(self):
        """L'abort non deve nemmeno lasciare backup locali .bak spuri."""
        out, bak = self.paths()
        out.write_text(json.dumps({"data": []}), encoding="utf-8")
        self._abort_run(out, bak)
        strays = [p for p in out.parent.glob("predictions*.json.bak")]
        self.assertEqual(strays, [], f"backup locali inattesi: {strays}")

    def test_no_temp_files_left_behind(self):
        out, bak = self.paths()
        self._abort_run(out, bak)
        leftovers = [p.name for p in out.parent.glob(".*tmp*")]
        self.assertEqual(leftovers, [], f"file temporanei residui: {leftovers}")

    def test_remote_backup_is_kept_on_abort(self):
        out, bak = self.paths()
        _, snapshot = self._abort_run(out, bak)
        self.assertTrue(bak.exists(), "il backup remoto va conservato")
        saved = json.loads(bak.read_text(encoding="utf-8"))["data"]
        self.assertEqual(mig.fingerprint(saved), snapshot.fingerprint)

    def test_remote_state_unchanged_on_abort(self):
        out, bak = self.paths()
        fake, _ = self._abort_run(out, bak)
        self.assertEqual(len(fake.state), 4, "la entry concorrente resta")
        self.assertFalse(any("model_version" in e for e in fake.state))

    def test_local_file_written_when_remote_unchanged(self):
        """Controprova: senza collisione il file locale DEVE essere scritto."""
        fake = FakeBin(BASE_REGISTRY)
        self.wire(fake)
        out, bak = self.paths()
        snapshot = mig.fetch_remote_snapshot()
        mig._apply(snapshot, out, push_remote=True, remote_backup=bak)

        self.assertEqual(len(fake.puts), 1)
        self.assertTrue(out.exists(), "a PUT riuscita il locale va aggiornato")
        data = json.loads(out.read_text(encoding="utf-8"))["data"]
        self.assertEqual(len(data), 3)

    def test_local_write_still_happens_without_push_remote(self):
        """Senza --push-remote la scrittura locale resta l'unico effetto."""
        fake = FakeBin(BASE_REGISTRY)
        self.wire(fake)
        out, bak = self.paths()
        snapshot = mig.fetch_remote_snapshot()
        mig._apply(snapshot, out, push_remote=False)

        self.assertEqual(len(fake.puts), 0)
        self.assertTrue(out.exists())
        self.assertEqual(len(json.loads(out.read_text())["data"]), 3)

    def test_cli_abort_leaves_no_stale_local_file(self):
        fake = FakeBin(
            BASE_REGISTRY, mutate_after_reads=1,
            mutation=lambda s: s + [_entry("X", "Y", "05/09/2026 12:00")])
        self.wire(fake)
        out, bak = self.paths()
        rc = mig.main(["--remote", "--apply", "--push-remote",
                       "--output", str(out), "--backup-path", str(bak)])
        self.assertEqual(rc, 3)
        self.assertEqual(len(fake.puts), 0)
        self.assertFalse(out.exists(),
                         "la CLI non deve lasciare un registro locale stale")
        self.assertTrue(bak.exists())


class TestAtomicLocalWrite(RaceConditionTestCase):

    def test_atomic_write_replaces_content(self):
        out, _ = self.paths()
        mig.write_predictions_file_atomic(out, [{"a": 1}])
        self.assertEqual(json.loads(out.read_text())["data"], [{"a": 1}])
        mig.write_predictions_file_atomic(out, [{"b": 2}])
        self.assertEqual(json.loads(out.read_text())["data"], [{"b": 2}])

    def test_failed_write_leaves_original_intact(self):
        """Se la serializzazione fallisce, il file originale non cambia."""
        out, _ = self.paths()
        mig.write_predictions_file_atomic(out, [{"ok": 1}])
        before = out.read_bytes()

        class Unserializable:
            pass

        with self.assertRaises(TypeError):
            mig.write_predictions_file_atomic(out, [{"bad": Unserializable()}])

        self.assertEqual(out.read_bytes(), before)
        self.assertEqual([p.name for p in out.parent.glob(".*tmp*")], [],
                         "nessun temporaneo deve restare")


# ---------------------------------------------------------------------------
# Il tagging non dipende da probabilita'/esito
# ---------------------------------------------------------------------------
class TestTaggingIgnoresProbabilityAndOutcome(unittest.TestCase):

    def test_high_probability_after_cutoff_is_not_tagged(self):
        after = _entry("Dopo", "Fix", "05/09/2026 10:00", prob=99.8)
        migrated, changed, _ = mig.build_migration([after])
        self.assertEqual(changed, 0)
        self.assertNotIn("model_version", migrated[0])

    def test_low_probability_before_cutoff_is_tagged(self):
        before = _entry("Prima", "Fix", "29/08/2026 11:00", prob=52.0)
        migrated, changed, _ = mig.build_migration([before])
        self.assertEqual(changed, 1)
        self.assertEqual(migrated[0]["model_version"], mig_pre_fix_version())

    def test_outcome_does_not_change_decision(self):
        """Stesso timestamp, esiti diversi -> stessa decisione di tagging."""
        for esito in ("\u2705", "\u274c", "\u23f3"):
            e = _entry("A", "B", "04/09/2026 17:35", prob=70.0, esito=esito)
            _, changed, _ = mig.build_migration([e])
            self.assertEqual(changed, 1, f"esito {esito} non deve influire")

    def test_probability_sweep_does_not_change_decision(self):
        for prob in (0.1, 25.0, 50.0, 75.0, 99.8, 100.0):
            pre = _entry("A", "B", "04/09/2026 17:35", prob=prob)
            _, changed_pre, _ = mig.build_migration([pre])
            self.assertEqual(changed_pre, 1, f"prob {prob} pre-cutoff -> tag")

            post = _entry("A", "B", "05/09/2026 10:00", prob=prob)
            _, changed_post, _ = mig.build_migration([post])
            self.assertEqual(changed_post, 0, f"prob {prob} post-cutoff -> no tag")


# ---------------------------------------------------------------------------
# Il dry-run non scrive mai
# ---------------------------------------------------------------------------
class TestDryRunPerformsNoWrite(RaceConditionTestCase):

    def test_dry_run_only_reads(self):
        fake = FakeBin(BASE_REGISTRY)
        self.wire(fake)
        rc = mig.main(["--remote"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(fake.puts), 0, "il dry-run non deve mai scrivere")
        self.assertEqual(len(fake.gets), 1, "una sola GET in dry-run")


if __name__ == "__main__":
    unittest.main(verbosity=2)
