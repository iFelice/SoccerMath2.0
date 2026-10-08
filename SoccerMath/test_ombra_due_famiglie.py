"""Registro ombra con DUE scelte per partita candidata (round 2 della PR Totali).

Ogni partita candidata produce due righe distinte nel registro ombra:

* ``famiglia = "ou25"``: la migliore fra Over 2.5 e Under 2.5, versione
  ``topmix_ombra_ou25_v1``;
* ``famiglia = "ggng"``: la migliore fra GG e NG, versione ``topmix_ombra_ggng_v1``.

Ciascuna ha la sua confidence e il suo flag ``ammessa`` (soglia 0,60, bordo incluso).
Le due righe hanno chiavi di dedup diverse, quindi l'aggiunta di una non tocca mai
l'altra, e nessuna delle due entra nelle statistiche visibili.
"""
from __future__ import annotations

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
import prediction_registry as R  # noqa: E402


def _m(p1=0.20, pX=0.15, p2=0.10, over=0.40, gg=0.50):
    """Vettore Poisson come ``get_full_poisson_two_heads``: Over = 1 - u25, GG = gg."""
    return {"1": p1, "X": pX, "2": p2, "u25": 1.0 - over, "gg": gg}


def _partita(mid, home="Casa", away="Trasferta", utc="2026-10-17T18:45:00Z", md=7):
    return {"id": mid, "matchday": md, "utcDate": utc,
            "homeTeam": {"name": home}, "awayTeam": {"name": away}, "status": "TIMED"}


def _scelte(m, home="Casa", away="Trasferta"):
    return {r["famiglia"]: r for r in app.righe_ombra_totali(m, home, away)}


def _con_partita(riga, mid=42):
    """Aggiunge i campi che ``calcola_righe_top_mix`` mette sulla riga ombra."""
    return dict(riga, match_id=mid, league="Serie A", giornata=7, home="Casa", away="Trasferta",
                utcDate="2026-10-17T18:45:00Z")


class TestDueSceltePerCandidata(unittest.TestCase):

    def test_famiglie_e_versioni_separate(self):
        s = _scelte(_m(over=0.70, gg=0.80))
        self.assertEqual({R.OMBRA_FAMIGLIA_OU25, R.OMBRA_FAMIGLIA_GGNG}, set(s))
        self.assertEqual("Over 2.5", s[R.OMBRA_FAMIGLIA_OU25]["market"])
        self.assertEqual("GG", s[R.OMBRA_FAMIGLIA_GGNG]["market"])
        self.assertAlmostEqual(0.70, s[R.OMBRA_FAMIGLIA_OU25]["confidence"], places=12)
        self.assertAlmostEqual(0.80, s[R.OMBRA_FAMIGLIA_GGNG]["confidence"], places=12)

    def test_ammessa_si_valuta_per_famiglia(self):
        s = _scelte(_m(over=0.62, gg=0.55))
        self.assertTrue(s[R.OMBRA_FAMIGLIA_OU25]["ammessa"])
        self.assertFalse(s[R.OMBRA_FAMIGLIA_GGNG]["ammessa"])

    def test_record_ombra_di_ciascuna_famiglia_ha_versione_e_chiave_proprie(self):
        s = _scelte(_m(over=0.70, gg=0.80))
        ou = app.build_ombra_entry(_con_partita(s[R.OMBRA_FAMIGLIA_OU25]), salvato_il="08/10/2026 19:00", snapshot_sha="sha")
        gg = app.build_ombra_entry(_con_partita(s[R.OMBRA_FAMIGLIA_GGNG]), salvato_il="08/10/2026 19:00", snapshot_sha="sha")
        self.assertEqual(R.SELECTOR_VERSION_OMBRA_OU25, ou["selector_version"])
        self.assertEqual(R.SELECTOR_VERSION_OMBRA_GGNG, gg["selector_version"])
        self.assertEqual(R.OMBRA_FAMIGLIA_OU25, ou[R.OMBRA_FAMIGLIA_FIELD])
        self.assertEqual(R.OMBRA_FAMIGLIA_GGNG, gg[R.OMBRA_FAMIGLIA_FIELD])
        self.assertNotEqual(R.dedup_key(ou), R.dedup_key(gg))
        self.assertEqual("OVER_2.5", ou["mercato_standard"])
        self.assertEqual("GG", gg["mercato_standard"])

    def test_aggiunta_delle_due_righe_della_stessa_partita_non_si_sovrascrivono(self):
        s = _scelte(_m(over=0.70, gg=0.80))
        ou = app.build_ombra_entry(_con_partita(s[R.OMBRA_FAMIGLIA_OU25]), salvato_il="08/10/2026 19:00", snapshot_sha="sha")
        gg = app.build_ombra_entry(_con_partita(s[R.OMBRA_FAMIGLIA_GGNG]), salvato_il="08/10/2026 19:00", snapshot_sha="sha")
        lista, azioni = R.upsert_prediction_entries([], [ou, gg])
        self.assertEqual({"aggiunta": 2}, azioni)
        self.assertEqual([R.OMBRA_FAMIGLIA_OU25, R.OMBRA_FAMIGLIA_GGNG],
                         [r[R.OMBRA_FAMIGLIA_FIELD] for r in lista])


class TestFamigliaRetrocompatibile(unittest.TestCase):

    def test_riga_senza_campo_famiglia_si_deduce_dal_mercato(self):
        self.assertEqual(R.OMBRA_FAMIGLIA_OU25, R.famiglia_ombra({R.OMBRA_FIELD: True, "mercato_standard": "OVER_2.5"}))
        self.assertEqual(R.OMBRA_FAMIGLIA_OU25, R.famiglia_ombra({R.OMBRA_FIELD: True, "mercato_standard": "UNDER_2.5"}))
        self.assertEqual(R.OMBRA_FAMIGLIA_GGNG, R.famiglia_ombra({R.OMBRA_FIELD: True, "mercato_standard": "GG"}))
        self.assertEqual(R.OMBRA_FAMIGLIA_GGNG, R.famiglia_ombra({R.OMBRA_FIELD: True, "mercato_standard": "NG"}))

    def test_campo_famiglia_esplicito_vince_sul_mercato(self):
        riga = {R.OMBRA_FIELD: True, R.OMBRA_FAMIGLIA_FIELD: R.OMBRA_FAMIGLIA_GGNG, "mercato_standard": "OVER_2.5"}
        self.assertEqual(R.OMBRA_FAMIGLIA_GGNG, R.famiglia_ombra(riga))

    def test_riga_visibile_non_ha_famiglia(self):
        self.assertEqual("", R.famiglia_ombra({"mercato_standard": "1"}))

    def test_costanti_ombra_per_famiglia_coerenti(self):
        self.assertEqual({R.OMBRA_FAMIGLIA_OU25: R.SELECTOR_VERSION_OMBRA_OU25,
                          R.OMBRA_FAMIGLIA_GGNG: R.SELECTOR_VERSION_OMBRA_GGNG},
                         R.SELECTOR_VERSION_OMBRA_BY_FAMIGLIA)
        self.assertNotIn(R.SELECTOR_VERSION_CURRENT, R.SELECTOR_VERSION_OMBRA_BY_FAMIGLIA.values())
        self.assertFalse(hasattr(R, "SELECTOR_VERSION_OMBRA"))


class TestCalcoloDueRighePerCandidata(unittest.TestCase):
    """``calcola_righe_top_mix`` produce due ombra per candidata e nessuna Totale visibile."""

    def _esegui(self, partite, poisson_per_id):
        def poisson(h_s, a_s, avg_h, avg_a):
            return dict(poisson_per_id[h_s["mid"]])

        def elo(h, a, league, season=None):
            return {"1": 0.20, "X": 0.15, "2": 0.10}

        stats = {}
        for mid, (home, away) in partite.items():
            stats[app.clean_name(home)] = {"att": 1.0, "def": 1.0, "mid": mid}
            stats[app.clean_name(away)] = {"att": 1.0, "def": 1.0, "mid": mid}
        matches = [_partita(mid, home, away) for mid, (home, away) in partite.items()]
        lista = []
        with mock.patch.object(app, "get_full_poisson_two_heads", side_effect=poisson), \
             mock.patch.object(app, "predict_elo_probs", side_effect=elo), \
             mock.patch.object(app, "predict_elo_probs_legacy", side_effect=elo), \
             mock.patch.object(app, "_roster_stagione", return_value=None):
            righe = app.calcola_righe_top_mix("Serie A", matches, (stats, 1.5, 1.2, {}), ombra=lista)
        return righe, lista

    def test_due_righe_ombra_per_ogni_partita_candidata(self):
        partite = {1: ("Casa1", "Trasferta1"), 2: ("Casa2", "Trasferta2")}
        poisson = {1: _m(p1=0.20, pX=0.15, p2=0.10, over=0.70, gg=0.40),
                   2: _m(p1=0.58, pX=0.22, p2=0.20, over=0.30, gg=0.66)}
        righe, ombra = self._esegui(partite, poisson)
        self.assertEqual({(1, R.OMBRA_FAMIGLIA_OU25), (1, R.OMBRA_FAMIGLIA_GGNG),
                          (2, R.OMBRA_FAMIGLIA_OU25), (2, R.OMBRA_FAMIGLIA_GGNG)},
                         {(r["match_id"], r["famiglia"]) for r in ombra})
        self.assertEqual(4, len(ombra))
        visibili = {r["market"] for r in righe[R.MODEL_VARIANT_CURRENT]}
        for totale in ("Over 2.5", "Under 2.5", "GG", "NG"):
            self.assertNotIn(totale, visibili)


if __name__ == "__main__":
    unittest.main()
