"""Test offline della regola preregistrata per la seconda sonda totals."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import totals_probe_seconda_analisi as tps  # noqa: E402


class TestSecondaSondaTotals(unittest.TestCase):

    def test_senza_nuovo_snapshot_stampa_non_eseguita_e_non_scrive_numeri(self):
        with tempfile.TemporaryDirectory() as d:
            report = os.path.join(d, "seconda.md")
            output = io.StringIO()
            with mock.patch.object(tps, "discover_new_snapshot", return_value=None):
                with redirect_stdout(output):
                    self.assertEqual(tps.main(["--report", report]), 0)
            testo = output.getvalue()
            self.assertIn("seconda sonda non eseguita", testo)
            self.assertNotIn("## Risultati", testo)
            self.assertFalse(os.path.exists(report))
            self.assertTrue(testo.startswith(tps.RULE_TEXT.split("\n\n")[0]))

    def test_snapshot_del_10_10_escluso_dalla_scoperta(self):
        with tempfile.TemporaryDirectory() as d:
            baseline = os.path.join(d, tps.BASELINE_SNAPSHOT_NAME)
            os.makedirs(baseline)
            with open(os.path.join(baseline, "_summary.json"), "w", encoding="utf-8") as fh:
                json.dump({"generato_il": "2026-10-10T17:03:43Z"}, fh)
            self.assertIsNone(tps.discover_new_snapshot(d))

    def test_finestra_esclude_eventi_gia_iniziati_e_oltre_7_giorni(self):
        # Regola della produzione 1X2: commence_time <= istante della chiamata
        # e' una partita GIA' INIZIATA e viene esclusa (anche a parita' di istante).
        fetched = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
        def ev(hours):
            return {"fetched_at": fetched, "commence_time": fetched + timedelta(hours=hours)}
        self.assertFalse(tps.in_window(ev(0)))
        self.assertTrue(tps.in_window(ev(1)))
        self.assertTrue(tps.in_window(ev(168)))
        self.assertFalse(tps.in_window(ev(-1)))
        self.assertFalse(tps.in_window(ev(169)))

    def test_eventi_iniziati_classifica_solo_kickoff_non_successivo(self):
        fetched = datetime(2026, 10, 10, 17, 3, 43, tzinfo=timezone.utc)
        avviato = {"commence_time": fetched - timedelta(seconds=1), "fetched_at": fetched}
        in_corso_esatto = {"commence_time": fetched, "fetched_at": fetched}
        futuro = {"commence_time": fetched + timedelta(minutes=1), "fetched_at": fetched}
        senza_ora = {"commence_time": None, "fetched_at": fetched}
        lista = [avviato, in_corso_esatto, futuro, senza_ora]
        iniziati = tps.eventi_iniziati(lista)
        self.assertEqual(iniziati, [avviato, in_corso_esatto])
        # commence_time assente/corrotto: come in produzione NON viene classificato
        self.assertNotIn(senza_ora, iniziati)

    def test_regressione_risposta_reale_10_10_con_evento_iniziato(self):
        # Risposta GREZZA reale del 10/10: audit/data/totals_probe/2026-10-10_1703/
        # contiene Manchester United - Tottenham Hotspur con kickoff 16:30Z,
        # precedente alla chiamata delle 17:03:43Z (contaminazione segnalata nella
        # PR #61). L'evento deve risultare iniziato, fuori finestra, escluso.
        snapshot = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                                "totals_probe", "2026-10-10_1703")
        self.assertTrue(os.path.isdir(snapshot), "snapshot reale 10/10 assente")
        events, _call = tps.load_snapshot(snapshot)
        epl = [e for e in events if e.get("league") == "Premier League"]
        self.assertTrue(epl, "risposta soccer_epl.json non caricata")
        united = [e for e in epl if e.get("home") == "Manchester United"
                  and e.get("away") == "Tottenham Hotspur"]
        self.assertEqual(len(united), 1)
        ev = united[0]
        self.assertEqual(ev["commence_time"],
                         datetime(2026, 10, 10, 16, 30, tzinfo=timezone.utc))
        self.assertEqual(ev["fetched_at"],
                         datetime(2026, 10, 10, 17, 3, 43, tzinfo=timezone.utc))
        # 1) classificato come iniziato dalla regola di produzione
        self.assertIn(ev, tps.eventi_iniziati(epl))
        self.assertEqual(len(tps.eventi_iniziati(epl)), 1)
        # 2) fuori dalla finestra della regola (a)(b)(c): non entra negli eligible
        self.assertFalse(tps.in_window(ev))
        eligible = [e for e in events if tps.in_window(e)]
        self.assertNotIn(ev, eligible)
        self.assertTrue(all(not (e.get("league") == "Premier League"
                                 and e.get("home") == "Manchester United")
                            for e in eligible))
        # 3) il referto riporta quanti eventi sono stati esclusi per questo motivo
        stats = tps.decision(eligible, [])
        stats["n_iniziati_esclusi"] = len(tps.eventi_iniziati(events))
        report = tps.build_report(snapshot, None, None, stats, [], 0)
        self.assertIn("Eventi già iniziati alla chiamata", report)
        self.assertIn(f"**{len(tps.eventi_iniziati(events))}**", report)

    def test_quote_linea_deve_avere_due_quote_valide(self):
        event = {"bookmakers": [{"key": "pinnacle", "last_update": "2026-10-10T12:00:00Z",
                                 "markets": [{"key": "totals", "outcomes": [
                                     {"name": "Over", "point": 2.25, "price": 1.91},
                                     {"name": "Under", "point": 2.25, "price": 1.97},
                                     {"name": "Over", "point": 2.5, "price": 1.0},
                                     {"name": "Under", "point": 2.5, "price": 2.0}]}]}]}
        lines = tps.extract_book_lines(event)
        self.assertEqual(list(lines["pinnacle"]), [2.25])
        self.assertEqual(lines["pinnacle"][2.25]["last_update"], "2026-10-10T12:00:00Z")
        self.assertEqual(tps.selected_line(lines["pinnacle"])[0], 2.25)

    def test_regola_b_non_decidibile_con_meno_di_20_eventi(self):
        events = [{"book_lines": {"pinnacle": {2.25: {}}}} for _ in range(19)]
        comparisons = [{"diff_pp": 0.5} for _ in range(19)]
        result = tps.decision(events, comparisons)
        self.assertTrue(result["coverage_pass"])
        self.assertEqual(result["concordance_status"], "NON DECIDIBILE")
        self.assertFalse(result["production_proposable"])
        self.assertIsNone(result["median_diff_pp"])
        self.assertIsNone(result["p90_diff_pp"])

    def test_regole_a_b_e_c_passano_solo_con_soglie_e_n_rispettati(self):
        events = [{"book_lines": {"pinnacle": {2.25: {}}}} for _ in range(20)]
        comparisons = [{"diff_pp": 1.0} for _ in range(20)]
        result = tps.decision(events, comparisons)
        self.assertEqual(result["coverage"], 1.0)
        self.assertTrue(result["coverage_pass"])
        self.assertEqual(result["median_diff_pp"], 1.0)
        self.assertEqual(result["p90_diff_pp"], 1.0)
        self.assertTrue(result["concordance_pass"])
        self.assertTrue(result["production_proposable"])

        for comparison in comparisons[:3]:
            comparison["diff_pp"] = 4.0
        result = tps.decision(events, comparisons)
        self.assertFalse(result["concordance_pass"])
        self.assertFalse(result["production_proposable"])

    def test_referto_comincia_con_regola_preregistrata(self):
        stats = tps.decision([], [])
        report = tps.build_report("new_snapshot", None, None, stats, [], 0)
        self.assertTrue(report.startswith(tps.RULE_TEXT.rstrip()))
        self.assertIn("### (a) Copertura", report)
        self.assertIn("### (b) Concordanza", report)
        self.assertIn("### (c) Proponibilità", report)


def _evento_totals_id(eid, fetched, kickoff_offset_h=24):
    """Evento totals CONFRONTABILE: Pinnacle su linea ≠2,5 e 3 altri libri a 2,5."""
    def book(key, linea, over, under):
        return {"key": key, "last_update": fetched.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "markets": [{"key": "totals", "outcomes": [
                    {"name": "Over", "point": linea, "price": over},
                    {"name": "Under", "point": linea, "price": under}]}]}
    return {"id": eid, "home_team": f"Casa-{eid}", "away_team": f"Trasferta-{eid}",
            "commence_time": (fetched + timedelta(hours=kickoff_offset_h)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"),
            "bookmakers": [book("pinnacle", 2.75, 1.83, 2.01),
                           book("betfair", 2.5, 1.90, 1.90),
                           book("unibet", 2.5, 1.92, 1.88),
                           book("williamhill", 2.5, 1.88, 1.92)]}


def _live_payload(eventi, generato_il="2026-10-17T09:00:00Z"):
    """Mini live_odds.json con UNA sola lega e la terna Pinnacle data."""
    return {"schema": "soccermath_live_odds_v1", "generato_il": generato_il,
            "leghe": {"Serie A": {"sport_key": "soccer_italy_serie_a",
                                  "eventi": [{"id": eid, "home_team": "C", "away_team": "T",
                                              "commence_time": "2026-10-19T15:00:00Z",
                                              "libri": [{"key": "pinnacle",
                                                         "h2h": {"home": fh2, "draw": fd2,
                                                                 "away": fa2}}]}
                                            for eid, (fh2, fd2, fa2) in eventi]}}}


class TestPinQuote1x2(unittest.TestCase):
    """Il file vivo si legge UNA volta per snapshot: poi regna il pin.

    Regola: rieseguire l'analisi dopo un cambio di live_odds.json deve dare
    numeri identici — la terna riletta e' quella pinnata alla prima analisi.
    Il fixture usa due "pacchetti pinnati" (id evento con prefisso
    ``testpin-``): un cambiamento della fonte 1X2 che li lascia senza terna
    Pinnacle e' SEMPRE rilevabile dal conteggio dei pacchetti senza coppia
    (esattamente il quale-dei-due-file-cambio che deve rimanere invisibile
    alla riesecuzione).
    """

    FETCHED = datetime(2026, 10, 18, 17, 3, 43, tzinfo=timezone.utc)
    PACCHETTI = (f"{tps.MOCK_TEAM_NAME_PREFIX}alfa", f"{tps.MOCK_TEAM_NAME_PREFIX}beta")

    def _scrivi_snapshot(self, root):
        snapdir = os.path.join(root, "2026-10-18_1703")
        os.makedirs(snapdir)
        with open(os.path.join(snapdir, "_summary.json"), "w", encoding="utf-8") as fh:
            json.dump({"generato_il": "2026-10-18T17:03:43Z"}, fh)
        env = {"fetched_at_utc": "2026-10-18T17:03:43Z", "lega": "Serie A",
               "body": [_evento_totals_id(pid, self.FETCHED) for pid in self.PACCHETTI]}
        with open(os.path.join(snapdir, "soccer_italy_serie_a.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(env, fh)
        return snapdir

    def _scrivi_live(self, root, nome, ids_con_terna, generato_il="2026-10-17T09:00:00Z"):
        """Mini live_odds.json: terna Pinnacle solo per gli id indicati (gli altri
        pacchetti restano silenziosi dalle statistiche — e il nuovo conteggio li censisce)."""
        path = os.path.join(root, nome)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(_live_payload([(pid, (1.62, 4.10, 5.60)) for pid in ids_con_terna],
                                    generato_il=generato_il), fh)
        return path

    def _esegui(self, snapdir, live_path):
        with tempfile.TemporaryDirectory() as rep_dir:
            report = os.path.join(rep_dir, "report.md")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(tps.main(["--snapshot", snapdir,
                                           "--live-odds", live_path,
                                           "--report", report]), 0)
            with open(report, encoding="utf-8") as fh:
                testo = fh.read()
        return testo

    def test_rerun_identico_dopo_cambio_di_live_odds(self):
        with tempfile.TemporaryDirectory() as d:
            snapdir = self._scrivi_snapshot(d)
            live_completo = self._scrivi_live(d, "live_a.json", self.PACCHETTI)
            live_bucato = self._scrivi_live(d, "live_b.json", self.PACCHETTI[:1])

            primo = self._esegui(snapdir, live_completo)
            self.assertIn("senza terna 1X2 Pinnacle (esclusi dai confrontabili): **0**", primo)
            # il pin e' nato accanto allo snapshot, con la copia integrale del file
            pin_path = os.path.join(snapdir, tps.PIN_FILENAME)
            self.assertTrue(os.path.exists(pin_path))
            with open(pin_path, encoding="utf-8") as fh:
                pin = json.load(fh)
            self.assertEqual(pin["file_copia"], tps.PIN_COPY_FILENAME)
            self.assertTrue(os.path.exists(os.path.join(snapdir, tps.PIN_COPY_FILENAME)))
            # file NON tracciato dal repository: nessun commit fittizio, solo la copia
            self.assertIsNone(pin["commit_live_odds"])
            self.assertIn("prima analisi", primo)

            # ora il file vivo "cambia": a un pacchetto pinnato sparisce la terna.
            # Con il pin NON se ne accorge nessun numero della sezione risultati.
            secondo = self._esegui(snapdir, live_bucato)
            self.assertIn("copia pinnata", secondo)
            tail = lambda s: s[s.index("## Risultati"):]
            self.assertEqual(tail(primo), tail(secondo),
                             "la riesecuzione deve rileggere il pin, non il file cambiato")

    def test_senza_pin_i_numeri_seguono_davvero_il_file_vivo(self):
        # Controllo negativo: se il pin non c'e' piu', lo stesso cambiamento del
        # file vivo sposta il conteggio dei pacchetti scoperti (il test del pin
        # non e' cieco: il fixture distingue le due fonti).
        with tempfile.TemporaryDirectory() as d:
            snapdir = self._scrivi_snapshot(d)
            live_completo = self._scrivi_live(d, "live_a.json", self.PACCHETTI)
            live_bucato = self._scrivi_live(d, "live_b.json", self.PACCHETTI[:1])
            primo = self._esegui(snapdir, live_completo)
            os.remove(os.path.join(snapdir, tps.PIN_FILENAME))
            os.remove(os.path.join(snapdir, tps.PIN_COPY_FILENAME))
            altro = self._esegui(snapdir, live_bucato)
            self.assertIn("senza terna 1X2 Pinnacle (esclusi dai confrontabili): **1**", altro)
            tail = lambda s: s[s.index("## Risultati"):]
            self.assertNotEqual(tail(primo), tail(altro))

    def test_commit_registrato_solo_per_file_tracciato(self):
        # commit_live_odds_per_file e' None per file fuori dal repository e
        # registra il commit in vigore solo per il file tracciato.
        self.assertIsNone(tps.commit_live_odds_per_file("/tmp/live_finto.json"))


if __name__ == "__main__":
    unittest.main()
