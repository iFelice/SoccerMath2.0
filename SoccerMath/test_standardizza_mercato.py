"""Regressione su standardizza_mercato e persistenza di mercato_standard.

I test sugli alias sono generati da TUTTE le chiavi di TEAM_NAME_MAP:
``Vittoria {alias} - Top Mix`` non deve mai restituire ALTRO.
"""
from __future__ import annotations

import ast
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))

from team_aliases import TEAM_NAME_MAP
from app import (
    codice_mercato_selezionato,
    save_prediction_entry,
    standardizza_mercato,
)
from prediction_registry import (
    ORIGIN_TOP_MIX,
    SELECTOR_VERSION_CURRENT,
)

_OTHER = "__NoSuchTeam__"


class TestReproducedAltroBug(unittest.TestCase):
    def test_stade_rennais_away_is_2_not_altro(self):
        got = standardizza_mercato(
            "Vittoria Stade Rennais - Top Mix", "Angers SCO", "Stade Rennais"
        )
        self.assertEqual(got, "2")

    def test_barca_away_is_2_not_altro(self):
        got = standardizza_mercato(
            "Vittoria Barça - Top Mix", "Getafe", "Barça"
        )
        self.assertEqual(got, "2")

    def test_stade_rennais_home_is_1(self):
        got = standardizza_mercato(
            "Vittoria Stade Rennais - Top Mix", "Stade Rennais", "Angers SCO"
        )
        self.assertEqual(got, "1")

    def test_canonical_rennes_still_works(self):
        self.assertEqual(
            standardizza_mercato("Vittoria Rennes - Top Mix", "Angers", "Rennes"),
            "2",
        )


class TestTeamNameMapNeverAltro(unittest.TestCase):
    """Un caso per OGNI alias di TEAM_NAME_MAP, non una selezione a mano."""

    def test_vittoria_alias_as_home_is_1(self):
        failures = []
        for alias in TEAM_NAME_MAP:
            testo = f"Vittoria {alias} - Top Mix"
            got = standardizza_mercato(testo, alias, _OTHER)
            if got != "1":
                failures.append((alias, got, testo))
        self.assertEqual(
            failures, [],
            "alias TEAM_NAME_MAP che non mappano a 1 come casa: "
            + repr(failures[:10]),
        )

    def test_vittoria_alias_as_away_is_2(self):
        failures = []
        for alias in TEAM_NAME_MAP:
            testo = f"Vittoria {alias} - Top Mix"
            got = standardizza_mercato(testo, _OTHER, alias)
            if got != "2":
                failures.append((alias, got, testo))
        self.assertEqual(
            failures, [],
            "alias TEAM_NAME_MAP che non mappano a 2 come ospite: "
            + repr(failures[:10]),
        )

    def test_map_is_not_empty(self):
        self.assertGreaterEqual(len(TEAM_NAME_MAP), 50)


class TestSevenMarketsUnchanged(unittest.TestCase):
    def test_over_under_gg_ng_x(self):
        self.assertEqual(standardizza_mercato("Over 2.5 - Top Mix"), "OVER_2.5")
        self.assertEqual(standardizza_mercato("Under 2.5 - Top Mix"), "UNDER_2.5")
        self.assertEqual(standardizza_mercato("GG - Top Mix"), "GG")
        self.assertEqual(standardizza_mercato("NG - Top Mix"), "NG")
        self.assertEqual(standardizza_mercato("Pareggio - Top Mix"), "X")


class TestCodiceMercatoAllaGenerazione(unittest.TestCase):
    def test_seven_keys_from_best_mkt(self):
        h, a = "Stade Rennais", "Angers SCO"
        self.assertEqual(codice_mercato_selezionato(f"Vittoria {h}", h, a), "1")
        self.assertEqual(codice_mercato_selezionato(f"Vittoria {a}", h, a), "2")
        self.assertEqual(codice_mercato_selezionato("Pareggio", h, a), "X")
        self.assertEqual(codice_mercato_selezionato("Over 2.5", h, a), "OVER_2.5")
        self.assertEqual(codice_mercato_selezionato("Under 2.5", h, a), "UNDER_2.5")
        self.assertEqual(codice_mercato_selezionato("GG", h, a), "GG")
        self.assertEqual(codice_mercato_selezionato("NG", h, a), "NG")

    def test_barca_display_name(self):
        self.assertEqual(
            codice_mercato_selezionato("Vittoria Barça", "Getafe", "Barça"),
            "2",
        )

    @patch("app.save_predictions")
    @patch("app.load_predictions", return_value=[])
    def test_save_uses_explicit_code_not_reparse(self, _load, save):
        # Anche se il testo sarebbe ALTRO col vecchio parser, il codice
        # passato alla generazione vince.
        save_prediction_entry(
            999001, "Angers SCO", "Stade Rennais", "Ligue 1", 4,
            "05/09/2026 18:00", "Vittoria Stade Rennais - Top Mix",
            [], 70.0, "", mercato_standard="2",
        )
        save.assert_called_once()
        entry = save.call_args[0][0][0]
        self.assertEqual(entry["mercato_standard"], "2")
        self.assertEqual(entry["match_id"], 999001)

    @patch("app.save_predictions")
    @patch("app.load_predictions", return_value=[])
    def test_save_fallback_standardizza_when_code_omitted(self, _load, save):
        save_prediction_entry(
            999002, "Angers SCO", "Stade Rennais", "Ligue 1", 4,
            "05/09/2026 18:00", "Vittoria Stade Rennais - Top Mix",
            [], 70.0, "",
        )
        entry = save.call_args[0][0][0]
        self.assertEqual(entry["mercato_standard"], "2")

    @patch("app.save_predictions")
    @patch("app.load_predictions", return_value=[{"match_id": 999003}])
    def test_il_top_mix_non_piu_bloccato_da_un_record_altr_origine(self, _load, save):
        """Chiave di dedup = (match_id, origin, selector_version).

        Il vecchio dedup per solo ``match_id`` faceva ``return`` e la riga Top
        Mix sparava se Analisi Rapida/Billy avevano salvato prima (problema
        ``dedup_match_id``, blocking, in results/topmix_registry_tracking.json).
        Il record qui sopra non ha ``origin``: e' "Analisi" legacy, quindi la
        riga Top Mix DEVE essere scritta.
        """
        esito = save_prediction_entry(
            999003, "H", "A", "Serie A", 1, "05/09/2026 18:00",
            "Over 2.5 - Top Mix", [], 61.0, "", mercato_standard="OVER_2.5",
        )
        save.assert_called_once()
        self.assertEqual(esito["azione"], "aggiunta")
        self.assertEqual(len(save.call_args[0][0]), 2)   # legacy + Top Mix

    @patch("app.save_predictions")
    @patch("app.load_predictions")
    def test_ricalcolo_della_stessa_origine_aggiorna_senza_duplicare(self, load, save):
        load.return_value = [{
            "match_id": 999004, "origin": "top_mix",
            "selector_version": SELECTOR_VERSION_CURRENT,
            "esito": "⏳", "prob_sicuro": 55.0,
        }]
        esito = save_prediction_entry(
            999004, "H", "A", "Serie A", 1, "05/09/2026 18:00",
            "Over 2.5 - Top Mix", [], 61.0, "", mercato_standard="OVER_2.5",
            origin=ORIGIN_TOP_MIX,
        )
        self.assertEqual(esito["azione"], "aggiornata")
        self.assertEqual(len(save.call_args[0][0]), 1)
        self.assertEqual(save.call_args[0][0][0]["prob_sicuro"], 61.0)

    @patch("app.save_predictions")
    @patch("app.load_predictions")
    def test_record_gia_giudicato_non_viene_sovrascritto(self, load, save):
        load.return_value = [{
            "match_id": 999005, "origin": "top_mix",
            "selector_version": SELECTOR_VERSION_CURRENT,
            "esito": "✅", "prob_sicuro": 61.0,
        }]
        esito = save_prediction_entry(
            999005, "H", "A", "Serie A", 1, "05/09/2026 18:00",
            "Over 2.5 - Top Mix", [], 90.0, "", mercato_standard="OVER_2.5",
            origin=ORIGIN_TOP_MIX,
        )
        self.assertEqual(esito["azione"], "gia_graduata")
        save.assert_not_called()

    @patch("app.save_predictions")
    @patch("app.load_predictions", return_value=[])
    def test_top_mix_salva_le_componenti_e_il_rank(self, _load, save):
        save_prediction_entry(
            999006, "H", "A", "Serie A", 1, "05/09/2026 18:00",
            "Vittoria H - Top Mix", [], 66.0, "", mercato_standard="1",
            origin=ORIGIN_TOP_MIX, rank=4, kickoff_utc="2026-09-12T18:00:00Z",
            prob_poisson=70.0, prob_elo=60.0, elo_disponibile=True,
            snapshot_sha="deadbeef",
        )
        e = save.call_args[0][0][0]
        self.assertEqual((e["origin"], e["tipo"]), ("top_mix", "Top Mix"))
        self.assertEqual((e["rank"], e["kickoff_utc"]), (4, "2026-09-12T18:00:00Z"))
        self.assertEqual((e["poisson"], e["elo"], e["elo_disponibile"]), (70.0, 60.0, True))
        self.assertEqual(e["data_snapshot_sha"], "deadbeef")
        self.assertEqual(e["selector_version"], SELECTOR_VERSION_CURRENT)
        self.assertEqual(len(e["calculation_id"]), 16)

    @patch("app.save_predictions")
    @patch("app.load_predictions", return_value=[])
    def test_elo_assente_e_marca_la_soglia_dei_totali(self, _load, save):
        save_prediction_entry(
            999007, "H", "A", "Serie A", 1, "05/09/2026 18:00",
            "Vittoria H - Top Mix", [], 66.0, "", mercato_standard="1",
            origin=ORIGIN_TOP_MIX, prob_elo=None, elo_disponibile=False,
        )
        e = save.call_args[0][0][0]
        self.assertFalse(e["elo_disponibile"])
        self.assertIsNone(e["elo"])


class TestPersistenzaAllaGenerazioneAST(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.path.join(os.path.dirname(__file__), "app.py")
        with open(path, encoding="utf-8") as f:
            cls.src = f.read()
        cls.tree = ast.parse(cls.src)

    def _fn(self, name):
        for node in self.tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        self.fail(name)

    def test_fetch_and_calc_stores_mercato_standard(self):
        # `mercato_standard` lo scrive l'orchestratore, `codice_mercato_selezionato`
        # lo chiama il selettore puro (referto §9 punto 2): la guardia legge il
        # percorso completo, cosi' nessuno dei due pezzi puo' sparire in silenzio.
        # `ast.unparse` normalizza gli apici a ', quindi anche il confronto
        # structurale si fa su testo normalizzato allo stesso modo.
        fetch = ast.unparse(self._fn("fetch_and_calc_top_mix")).replace("'", '"')
        src = fetch + ast.unparse(self._fn("seleziona_riga_top_mix")).replace("'", '"')
        self.assertIn("mercato_standard", fetch)
        self.assertIn('"mercato_standard": riga["mercato_standard"]', fetch)
        self.assertIn("codice_mercato_selezionato", src)

    def test_analisi_rapida_passes_code(self):
        src = ast.unparse(self._fn("analisi_rapida_giornata"))
        self.assertIn("mercato_standard", src)
        self.assertIn("codice_mercato_selezionato", src)

    def test_billy_fallback_passes_code(self):
        src = ast.unparse(self._fn("show_details"))
        self.assertIn("codice_mercato_selezionato", src)
        self.assertIn("mercato_standard=codice_top", src)

    def test_save_accepts_optional_code_and_keeps_dedup(self):
        fn = self._fn("save_prediction_entry")
        args = [a.arg for a in fn.args.args]
        self.assertIn("mercato_standard", args)
        src = ast.unparse(fn)
        self.assertIn("match_id", src)
        self.assertIn("return", src)


if __name__ == "__main__":
    unittest.main()
