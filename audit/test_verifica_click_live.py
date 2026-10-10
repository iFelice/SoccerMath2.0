"""Test offline del verificatore Top Mix mercato.

Copre i contratti del replay approvati per il punto 8: snapshot live odds legati
all'esatto ``generato_il``, confronti numerici esatti, stato modello point-in-time,
righe ricostruite/non verificabili e warning verde quando non c'e' materiale v3.
Nessun test chiama API esterne.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOCCER = os.path.join(ROOT, "SoccerMath")
for path in (SOCCER, HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

import market_odds  # noqa: E402
import verifica_click_live as v  # noqa: E402
import registry_coverage_check as check  # noqa: E402
import replay_legacy_topmix as replay  # noqa: E402
from prediction_registry import (  # noqa: E402
    MODEL_VARIANT_CURRENT,
    SELECTOR_VERSION_CURRENT,
)

TS_PRIMA = "2026-10-09T08:17:00Z"
TS_ULTIMA = "2026-10-09T19:41:54Z"
KICKOFF = "2026-10-12T18:00:00Z"


def _payload(timestamp, odds, *, home="Milan", away="Lecce", kickoff=KICKOFF):
    return {
        "schema": "soccermath_live_odds_v1",
        "generato_il": timestamp,
        "leghe": {
            "Serie A": {
                "eventi": [{
                    "id": f"event-{timestamp}",
                    "commence_time": kickoff,
                    "home_team": home,
                    "away_team": away,
                    "libri": [{
                        "key": "pinnacle",
                        "title": "Pinnacle",
                        "h2h": {"home": odds[0], "draw": odds[1], "away": odds[2]},
                    }],
                }],
            },
        },
    }


def _market_values(payload, outcome="1"):
    evento = payload["leghe"]["Serie A"]["eventi"][0]
    calcolo = market_odds.probabilita_mercato(evento["libri"])
    p = calcolo["probs"][outcome]
    stored_p = round(round(p * 100.0, 1) / 100.0, 6)
    return stored_p, calcolo["odds"][outcome]


def _riga_v3(*, match_id=7, outcome="1", first_payload=None, latest_payload=None,
              first_reconstructed=False, model_first=None, model_latest=None):
    first_payload = first_payload or _payload(TS_PRIMA, (1.72, 3.8, 5.0))
    latest_payload = latest_payload or _payload(TS_ULTIMA, (3.6, 3.25, 2.05))
    p_first, q_first = _market_values(first_payload, "1")
    p_latest, q_latest = _market_values(latest_payload, outcome)
    row = {
        "match_id": match_id,
        "home": "Milan",
        "away": "Lecce",
        "campionato": "Serie A",
        "origin": "top_mix",
        "selector_version": SELECTOR_VERSION_CURRENT,
        "model_variant": MODEL_VARIANT_CURRENT,
        "kickoff_utc": KICKOFF,
        "salvato_il_originario": "09/10/2026 10:20",
        "salvato_il": "09/10/2026 22:00",
        "mercato_standard": outcome,
        "prob_mercato_prima": p_first,
        "quota_mercato_prima": q_first,
        "prob_mercato": p_latest,
        "quota_mercato": q_latest,
        "quote_live_istante_prima": first_payload["generato_il"],
        "quote_live_istante": latest_payload["generato_il"],
        "prob_modello_prima": model_first,
        "prob_modello": model_latest,
        "prob_sicuro": round(p_latest * 100, 1),
        "esito": "⏳",
    }
    if first_reconstructed:
        for key in ("prob_mercato_prima", "quota_mercato_prima", "quote_live_istante_prima"):
            row.pop(key, None)
    return row


def _fixture_loader(leagues):
    return {"Serie A": [types.SimpleNamespace(match_id=7, home="Milan", away="Lecce")]}


def _esegui_main(righe, snapshots, *, sim_prob=None):
    """Avvia il main con dipendenze in-memory; nessun accesso a rete o registro."""
    report = {
        "snapshot_necessari": 0,
        "snapshot_trovati": len(snapshots),
        "commit_scansionati": len(snapshots),
        "errore_git": None,
    }

    def fake_snapshot_loader(timestamps, repo_root=None):
        report["snapshot_necessari"] = len(set(timestamps))
        return snapshots, report

    valori = {}
    if sim_prob is not None:
        valori = sim_prob

    def fake_click(instant, fixtures, *, targets=None, leagues=None, snapshot_cache=None):
        if not targets:
            raise AssertionError("simulate_click deve ricevere le partite bersaglio")
        mid = str(targets[0].match_id)
        value = valori.get(instant, 60.0)
        return types.SimpleNamespace(
            rows={MODEL_VARIANT_CURRENT: [{"match_id": mid, "mercato_standard": "1",
                                           "prob_val": value}]},
            snapshot_sha="model-snapshot-test",
        )

    output = io.StringIO()
    with mock.patch.object(check, "load_registry_readonly", lambda: (list(righe), "finto")), \
            mock.patch.object(v, "carica_snapshot_live_odds_da_git", fake_snapshot_loader), \
            mock.patch.object(replay, "fixtures_from_csv_and_archive", _fixture_loader), \
            mock.patch.object(replay, "simulate_click", fake_click), \
            redirect_stdout(output):
        rc = v.main(["--from", "2026-08-30", "--to", "2026-12-31", "--fixtures", "csv"])
    return rc, output.getvalue()


class TestIstantiRegistrazione(unittest.TestCase):
    def setUp(self):
        import app
        v.ITALY = app.ITALY_TZ

    def test_salvato_il_italiano_convertito_in_utc(self):
        # 10/09/2026 20:00 in Italia (CEST, UTC+2) = 18:00 UTC.
        self.assertEqual(datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc),
                         v.istante_del_salvataggio({"salvato_il": "10/09/2026 20:00"}))

    def test_prima_usa_salvato_originario_e_ultima_salvato_il(self):
        row = {"salvato_il_originario": "09/10/2026 10:20", "salvato_il": "09/10/2026 22:00"}
        self.assertEqual(datetime(2026, 10, 9, 8, 20, tzinfo=timezone.utc),
                         v.istante_registrazione(row, "prima"))
        self.assertEqual(datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc),
                         v.istante_registrazione(row, "ultima"))


class TestConfrontoMercato(unittest.TestCase):
    def test_prima_e_ultima_coerenti_con_due_snapshot(self):
        prima = _payload(TS_PRIMA, (1.72, 3.8, 5.0))
        # Nel secondo snapshot il favorito e' diventato 2. L'ultima registrazione
        # continua pero' a verificare l'esito registrato 1, come fa il refresh.
        ultima = _payload(TS_ULTIMA, (3.6, 3.25, 2.05))
        row = _riga_v3(first_payload=prima, latest_payload=ultima, outcome="1")

        first = v.confronta_mercato_registrazione(
            row, "prima", prima, timestamp_richiesto=TS_PRIMA, commit_snapshot="abc1")
        last = v.confronta_mercato_registrazione(
            row, "ultima", ultima, timestamp_richiesto=TS_ULTIMA, commit_snapshot="abc2")

        self.assertEqual("corrisponde", first["esito"])
        self.assertEqual("1", first["mercato"], "esito iniziale ricostruito dall'argmax dello snapshot")
        self.assertEqual("corrisponde", last["esito"])
        self.assertEqual("1", last["mercato"], "ultima probabilita' sul pronostico registrato, non sul nuovo favorito")
        self.assertEqual({"corrisponde"}, {c["esito"] for c in first["campi"] + last["campi"]})

    def test_probabilita_alterata_di_un_decimo_di_punto_differisce_esattamente(self):
        snapshot = _payload(TS_ULTIMA, (1.72, 3.8, 5.0))
        row = _riga_v3(first_payload=snapshot, latest_payload=snapshot)
        row["prob_mercato"] += 0.001  # +0,1 punti percentuali, senza tolleranza
        result = v.confronta_mercato_registrazione(
            row, "ultima", snapshot, timestamp_richiesto=TS_ULTIMA)
        self.assertEqual("differisce", result["esito"])
        self.assertEqual("differisce", result["campi"][0]["esito"])
        self.assertEqual("prob_mercato", result["campi"][0]["campo"])
        self.assertEqual(7, row["match_id"])

    def test_snapshot_mancante_e_non_verificabile_non_ok(self):
        row = _riga_v3()
        result = v.confronta_mercato_registrazione(
            row, "ultima", None, timestamp_richiesto=TS_ULTIMA)
        self.assertEqual("non verificabile", result["esito"])
        self.assertIn("non trovato", result["motivo"])
        self.assertEqual([], result["campi"])

    def test_prima_ricostruita_viene_saltata_e_dichiarata(self):
        row = _riga_v3(first_reconstructed=True)
        rc, testo = _esegui_main([row], {TS_ULTIMA: {
            "payload": _payload(TS_ULTIMA, (3.6, 3.25, 2.05)), "commit": "abc2"}})
        self.assertEqual(0, rc)
        self.assertIn("prima registrazione ricostruita", testo)
        self.assertIn("verificata solo l'ultima", testo)
        self.assertIn("a_mercato_righe=1, registrazioni=1", testo)

    def test_main_fallisce_con_match_id_e_campo_se_prob_mercato_diverge(self):
        first = _payload(TS_PRIMA, (1.72, 3.8, 5.0))
        last = _payload(TS_ULTIMA, (1.72, 3.8, 5.0))
        row = _riga_v3(first_payload=first, latest_payload=last)
        row["prob_mercato"] += 0.001
        snapshots = {
            TS_PRIMA: {"payload": first, "commit": "abc1"},
            TS_ULTIMA: {"payload": last, "commit": "abc2"},
        }
        rc, testo = _esegui_main([row], snapshots)
        self.assertEqual(1, rc)
        self.assertIn("match_id 7", testo)
        self.assertIn("`prob_mercato`", testo)
        self.assertIn("differisce", testo)
        self.assertIn("[verifica] esito: fallita", testo)

    def test_snapshot_storico_mancante_non_conta_come_ok(self):
        first = _payload(TS_PRIMA, (1.72, 3.8, 5.0))
        row = _riga_v3(first_payload=first, latest_payload=_payload(TS_ULTIMA, (1.72, 3.8, 5.0)))
        snapshots = {TS_PRIMA: {"payload": first, "commit": "abc1"}}
        rc, testo = _esegui_main([row], snapshots)
        self.assertEqual(0, rc, "il confronto prima esatto resta valido, il timestamp mancante non e' una corrispondenza")
        self.assertIn("snapshot con generato_il=2026-10-09T19:41:54Z non trovato", testo)
        self.assertIn("| a) mercato | 7 | Milan - Lecce | ultima |", testo)
        self.assertIn("snapshot_necessari=2, snapshot_trovati=1", testo)


class TestConfrontoModello(unittest.TestCase):
    def test_simulate_click_stesso_match_id_ed_esito_e_istante(self):
        prima = _payload(TS_PRIMA, (1.72, 3.8, 5.0))
        ultima = _payload(TS_ULTIMA, (1.72, 3.8, 5.0))
        row = _riga_v3(first_payload=prima, latest_payload=ultima,
                       model_first=60.0, model_latest=54.0)
        snapshots = {
            TS_PRIMA: {"payload": prima, "commit": "abc1"},
            TS_ULTIMA: {"payload": ultima, "commit": "abc2"},
        }
        # I due salvato_il diventano 08:20 e 20:00 UTC con Europe/Rome.
        sim = {
            datetime(2026, 10, 9, 8, 20, tzinfo=timezone.utc): 60.0,
            datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc): 54.0,
        }
        rc, testo = _esegui_main([row], snapshots, sim_prob=sim)
        self.assertEqual(0, rc)
        self.assertIn("## b) Modello contro modello", testo)
        self.assertIn("08:20:00 UTC", testo)
        self.assertIn("20:00:00 UTC", testo)
        self.assertIn("prob_val (simulate_click)", testo)
        self.assertIn("b_modello_righe=1, registrazioni=2", testo)

    def test_prob_modello_divergente_fa_fallire_il_gate_esatto(self):
        first = _payload(TS_PRIMA, (1.72, 3.8, 5.0))
        last = _payload(TS_ULTIMA, (1.72, 3.8, 5.0))
        row = _riga_v3(first_payload=first, latest_payload=last,
                       model_first=60.0, model_latest=54.0)
        snapshots = {
            TS_PRIMA: {"payload": first, "commit": "abc1"},
            TS_ULTIMA: {"payload": last, "commit": "abc2"},
        }
        sim = {
            datetime(2026, 10, 9, 8, 20, tzinfo=timezone.utc): 60.0,
            datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc): 55.0,
        }
        rc, testo = _esegui_main([row], snapshots, sim_prob=sim)
        self.assertEqual(1, rc)
        self.assertIn("match_id 7", testo)
        self.assertIn("`prob_modello`", testo)
        self.assertIn("| 54 | 55 |", testo)
        self.assertIn("differisce", testo)
        self.assertIn("[verifica] esito: fallita", testo)

    def test_esito_model_differente_non_viene_confrontato_come_se_uguale(self):
        first = _payload(TS_PRIMA, (1.72, 3.8, 5.0))
        last = _payload(TS_ULTIMA, (1.72, 3.8, 5.0))
        row = _riga_v3(first_payload=first, latest_payload=last,
                       model_first=60.0, model_latest=54.0)
        snapshots = {
            TS_PRIMA: {"payload": first, "commit": "abc1"},
            TS_ULTIMA: {"payload": last, "commit": "abc2"},
        }

        def fake_click(instant, fixtures, *, targets=None, leagues=None, snapshot_cache=None):
            return types.SimpleNamespace(
                rows={MODEL_VARIANT_CURRENT: [{"match_id": "7", "mercato_standard": "2",
                                               "prob_val": 99.0}]},
                snapshot_sha="model-sha",
            )

        out = io.StringIO()
        with mock.patch.object(check, "load_registry_readonly", lambda: ([row], "finto")), \
                mock.patch.object(v, "carica_snapshot_live_odds_da_git",
                                  lambda timestamps, repo_root=None: (snapshots, {
                                      "snapshot_necessari": 2, "snapshot_trovati": 2,
                                      "commit_scansionati": 2, "errore_git": None})), \
                mock.patch.object(replay, "fixtures_from_csv_and_archive", _fixture_loader), \
                mock.patch.object(replay, "simulate_click", fake_click), \
                redirect_stdout(out):
            rc = v.main(["--from", "2026-08-30", "--to", "2026-12-31", "--fixtures", "csv"])
        self.assertEqual(0, rc, "le non-corrispondenze di esito sono non verificabili, non un confronto falsato")
        self.assertIn("simulate_click non ha ricostruito", out.getvalue())
        self.assertIn("| b) modello | 7 | Milan - Lecce | prima |", out.getvalue())


class TestSnapshotDaGit(unittest.TestCase):
    def test_ricerca_storica_per_generato_il_esatto_e_conteggio(self):
        with tempfile.TemporaryDirectory() as repo:
            subprocess.run(["git", "init", "-q", repo], check=True)
            db = os.path.join(repo, "SoccerMath", "database")
            os.makedirs(db)
            path = os.path.join(db, "live_odds.json")
            for timestamp in (TS_PRIMA, TS_ULTIMA):
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(_payload(timestamp, (1.72, 3.8, 5.0)), fh)
                subprocess.run(["git", "-C", repo, "add", "SoccerMath/database/live_odds.json"], check=True)
                subprocess.run([
                    "git", "-C", repo, "-c", "user.name=Audit Test", "-c",
                    "user.email=audit-test@example.invalid", "commit", "-q", "-m", timestamp,
                ], check=True)

            trovati, report = v.carica_snapshot_live_odds_da_git(
                [TS_PRIMA, TS_ULTIMA, "2026-10-10T00:00:00Z"], repo_root=repo)
        self.assertEqual(3, report["snapshot_necessari"])
        self.assertEqual(2, report["snapshot_trovati"])
        self.assertEqual({TS_PRIMA, TS_ULTIMA}, set(trovati))
        self.assertEqual(TS_PRIMA, trovati[TS_PRIMA]["payload"]["generato_il"])


class TestZeroRighe(unittest.TestCase):
    def test_zero_righe_v3_verde_con_annotazione_warning(self):
        output = io.StringIO()
        with mock.patch.object(check, "load_registry_readonly", lambda: ([], "finto")), \
                redirect_stdout(output):
            rc = v.main(["--from", "2026-08-30", "--to", "2026-12-31", "--fixtures", "csv"])
        self.assertEqual(0, rc)
        self.assertIn("::warning::verifica rimandata: 0 righe topmix_mercato_v3", output.getvalue())
        self.assertIn("a_mercato_righe=0, registrazioni=0", output.getvalue())
        self.assertIn("b_modello_righe=0, registrazioni=0", output.getvalue())
        self.assertIn("[verifica] esito: verifica rimandata: 0 righe topmix_mercato_v3", output.getvalue())

    def test_zero_confronti_esatti_con_riga_presente_fallisce(self):
        first = _payload(TS_PRIMA, (1.72, 3.8, 5.0))
        last = _payload(TS_ULTIMA, (1.72, 3.8, 5.0))
        row = _riga_v3(first_payload=first, latest_payload=last)
        row["prob_mercato_prima"] += 0.001
        row["prob_mercato"] += 0.001
        row["quota_mercato_prima"] += 0.01
        row["quota_mercato"] += 0.01
        snapshots = {
            TS_PRIMA: {"payload": first, "commit": "abc1"},
            TS_ULTIMA: {"payload": last, "commit": "abc2"},
        }
        rc, testo = _esegui_main([row], snapshots)
        self.assertEqual(1, rc)
        self.assertIn("zero corrispondenze esatte", testo)
        self.assertIn("match_id 7", testo)


if __name__ == "__main__":
    unittest.main()
