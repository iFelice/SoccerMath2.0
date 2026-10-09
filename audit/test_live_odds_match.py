#!/usr/bin/env python3
"""test_live_odds_match.py — Test offline di audit/live_odds_match.py.

Legge solo gli snapshot committati in audit/data/live_odds_probe/ e i CSV in
SoccerMath/database: nessuna rete e nessuna scrittura.

I valori attesi sono quelli dello snapshot del 2026-10-08: se il probe viene
rifatto (partite diverse, squadre diverse) i contatori vanno aggiornati.

AGGIORNAMENTO (PR delle quote live nel Top Mix). I sei alias aggiunti in
``SoccerMath/team_aliases.py`` portano l'abbinamento del RESOLVER DI PRODUZIONE
(``team_names.resolve_team_name``, quello che usa ``market_odds``) a
**48/48 = 100%** sullo stesso snapshot, contro 42/48 = 87,5% di prima. La
colonna ``n_abbinate`` (43/48) resta sotto il 100% perche' conta il solo
``clean_name`` senza tabella alias: e' il confronto storico della PR #50, tenuto
qui apposta per mostrare che il resolver aggiunge cinque nomi che la pulizia del
testo da sola non risolve (Bayer Leverkusen, Hamburger SV, Celta Vigo,
Deportivo La Coruña, Paris Saint Germain). In produzione non si usa
``clean_name`` da solo, quindi la copertura reale e' quella del resolver.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timezone

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

import live_odds_match as LOM  # noqa: E402
from team_aliases import clean_name  # noqa: E402

SNAPSHOT = "2026-10-08"   # data dello snapshot committato (vedi test_snapshot_presente)
# valori misurati sullo snapshot committato, DOPO i sei alias della PR delle
# quote live. Terzina: (partite della prossima giornata, abbinate con il solo
# clean_name, abbinate col resolver di produzione).
ATTESO = {
    "Serie A": (10, 10, 10),
    "Premier League": (10, 10, 10),
    "La Liga": (10, 8, 10),
    "Bundesliga": (9, 7, 9),
    "Ligue 1": (9, 8, 9),
}
# I sei alias aggiunti da questa PR: prima erano i NOMI NON CENSITI del probe.
NOMI_NUOVI_ALIAS = [
    "Atlético Madrid", "Borussia Monchengladbach", "CA Osasuna", "Elche CF",
    "FSV Mainz 05", "Real Racing Club de Santander",
]
# Nomi che il solo clean_name non risolve (nessun alias serve: sono gia' in
# tabella) e che il resolver risolve. Servono a spiegare il divario 43/48.
NOMI_SOLO_RESOLVER = [
    "Bayer Leverkusen", "Hamburger SV", "Celta Vigo", "Deportivo La Coruña",
    "Paris Saint Germain",
]


class TestInsiemeCanonico(unittest.TestCase):
    def test_canonici_non_vuoti_per_tutte_le_leghe(self):
        for prefix, (lega, _key) in LOM.LEAGUES.items():
            nomi = LOM.canonical_names(prefix, [LOM.CURRENT_SUFFIX])
            self.assertGreater(len(nomi), 0, lega)

    def test_clean_name_e_idempotente_sui_canonici(self):
        nomi = LOM.canonical_names("SerieA", [LOM.CURRENT_SUFFIX])
        for n in nomi:
            self.assertEqual(clean_name(n), n, n)

    def test_linsieme_con_la_stagione_precedente_non_stringe(self):
        solo = LOM.canonical_names("LaLiga", [LOM.CURRENT_SUFFIX])
        entrambi = LOM.canonical_names("LaLiga", [LOM.CURRENT_SUFFIX, LOM.PREV_SUFFIX])
        self.assertTrue(solo <= entrambi)


class TestAbbinamento(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = LOM.build_payload()

    def test_snapshot_presente(self):
        # l'istante di riferimento deve essere quello dello snapshot committato,
        # non l'ora corrente: il risultato dello script non dipende da quando gira
        self.assertTrue(self.payload["istante_di_riferimento"].startswith(SNAPSHOT),
                        self.payload["istante_di_riferimento"])
        with open(os.path.join(LOM.DATA_DIR, "probe_summary.json"), encoding="utf-8") as fh:
            summary = json.load(fh)
        self.assertEqual(self.payload["istante_di_riferimento"][:10],
                         str(summary["generato_il"])[:10])
        self.assertEqual(self.payload["snapshot_odds_api"], summary["generato_il"])
        for lega, v in self.payload["per_lega"].items():
            self.assertTrue(v["disponibile"], lega)

    def test_partite_e_abbinamenti_per_lega(self):
        for lega, (n, ok, ok_res) in ATTESO.items():
            v = self.payload["per_lega"][lega]
            self.assertEqual(v["n_prossima_giornata"], n, lega)
            self.assertEqual(v["n_abbinate"], ok, lega)
            self.assertEqual(v["n_abbinate_resolver"], ok_res, lega)

    def test_totali(self):
        t = self.payload["totale"]
        self.assertEqual(t["n_prossima_giornata"], 48)
        self.assertEqual(t["n_abbinate"], 43)
        self.assertEqual(t["n_abbinate_resolver"], 48)
        self.assertAlmostEqual(t["pct_abbinate"], 43 / 48, places=12)
        self.assertAlmostEqual(t["pct_abbinate_resolver"], 1.0, places=12)

    def test_copertura_completa_col_resolver_di_produzione(self):
        """Punto 1 della commessa: TUTTE le partite del calendario corrente.

        Il resolver e' quello che usa ``market_odds.indice_partite`` in
        produzione: se qui c'e' un buco, nel Top Mix c'e' una partita senza
        quote (e viene segnalata, non inventata).
        """
        for lega, v in self.payload["per_lega"].items():
            self.assertEqual(v["n_prossima_giornata"], v["n_abbinate_resolver"],
                             f"{lega}: {v['n_abbinate_resolver']}/"
                             f"{v['n_prossima_giornata']} partite abbinate")
            for r in v["righe"]:
                self.assertTrue(r["match_ok_resolver"],
                                f"{lega}: {r['home_raw']} vs {r['away_raw']} non abbinata")

    def test_il_divario_e_solo_nei_nomi_gia_in_tabella_alias(self):
        """Il clean_name da solo perde esattamente i nomi che il resolver conosce."""
        non_puliti = [u["raw"] for u in self.payload["nomi_non_abbinati"]]
        self.assertEqual(sorted(NOMI_SOLO_RESOLVER), sorted(non_puliti))
        for u in self.payload["nomi_non_abbinati"]:
            self.assertTrue(u["risolto_dal_resolver"], u["raw"])

    def test_il_resolver_non_puoi_essere_peggiore_di_clean_name(self):
        for lega, v in self.payload["per_lega"].items():
            self.assertGreaterEqual(v["n_abbinate_resolver"], v["n_abbinate"], lega)

    def test_nessun_fuzzy_matching(self):
        """Un nome fuori tabella resta fuori: nessuna somiglianza viene usata."""
        for u in self.payload["nomi_non_abbinati"]:
            self.assertNotEqual(u["raw"], "")
            self.assertIsNotNone(u["clean"])
        for u in self.payload["nomi_non_abbinati"]:
            if u["resolver_source"] == "unknown":
                self.assertFalse(u["risolto_dal_resolver"])

    def test_i_sei_alias_nuovi_non_sono_piu_nomi_non_censiti(self):
        """Nessun nome dello snapshot resta irrisolto: la lista e' vuota."""
        mancanti = [u["raw"] for u in self.payload["nomi_non_abbinati"]
                    if not u["risolto_dal_resolver"]]
        self.assertEqual([], mancanti,
                         "nomi dello snapshot ancora senza alias: aggiungerli in "
                         "SoccerMath/team_aliases.py")
        # e i sei nomi di questa PR compaiono nello snapshot (non sono fuori tema)
        dallo_snapshot = set()
        for v in self.payload["per_lega"].values():
            for r in v["righe"]:
                dallo_snapshot.update((r["home_raw"], r["away_raw"]))
        for nome in NOMI_NUOVI_ALIAS:
            self.assertIn(nome, dallo_snapshot,
                          f"{nome!r} non e' nello snapshot del 2026-10-08: "
                          f"l'alias va comunque verificato su un calendario reale")

    def test_nomi_unici(self):
        chiavi = [(u["lega"], u["raw"]) for u in self.payload["nomi_non_abbinati"]]
        self.assertEqual(len(chiavi), len(set(chiavi)))

    def test_prossima_giornata_dentro_la_finestra_di_produzione(self):
        for lega, v in self.payload["per_lega"].items():
            self.assertIsNotNone(v["primo_kickoff"])
            self.assertLessEqual(v["primo_kickoff"][:10], v["fine_finestra"][:10])
            self.assertEqual(v["n_prossima_giornata"] > 0, True)

    def test_determinismo(self):
        secondo = LOM.build_payload()
        self.assertEqual(secondo["totale"], self.payload["totale"])

    def test_json_serializzabile(self):
        import json
        json.dumps(self.payload, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
