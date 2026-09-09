"""Guardia sul tracciamento Top Mix: ispezione AST del codice di produzione.

Prima di ``audit/margini_migliorabili_topmix.md`` §7 questo file **fotografava i
difetti** (dedup per solo match_id, ``tipo`` derivato dal testo, PUT senza
verifica, campi assenti). Ora fotografia l'opposto: sono regression guard, e
falliscono se qualcuno re-introduce uno di quei percorsi.

Non importa ``app`` (niente Streamlit/numpy), non chiama JSONBin, non scrive il
registro: legge solo sorgenti. Esegue quindi anche in un ambiente minimale, a
differenza dei test che importano ``app``.
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
import unittest

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
_SOCCER = os.path.join(_REPO_ROOT, "SoccerMath")
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, _SOCCER)

from inspect_topmix_registry import (  # noqa: E402
    APP_PATH,
    REGISTRY_PATH,
    inspect_app,
    inspect_registry_module,
    tracking_verdict,
)

import prediction_registry as R  # noqa: E402  (solo stdlib)


def _src(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _fn(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(name)


class TestTracciamentoCorretto(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.facts = inspect_app()
        cls.verdict = tracking_verdict(cls.facts)

    def test_produzione_funzioni_presenti(self):
        found = self.facts["functions_found"]
        for name in (
            "save_prediction_entry", "save_predictions", "load_predictions",
            "fetch_and_calc_top_mix", "seleziona_riga_top_mix",
            "analisi_rapida_giornata", "show_details",
        ):
            self.assertTrue(found[name], name)

    def test_dedup_non_perde_piu_il_top_mix(self):
        d = self.facts["dedup_by_match_id"]
        self.assertFalse(d["present"], "il vecchio `if any(match_id...): return` e' tornato")
        self.assertFalse(d["early_return"])
        self.assertTrue(d["chiave_completa"], "save_prediction_entry non usa upsert_prediction_entry")
        self.assertTrue(d["passa_origine"])

    def test_origine_esplicita_da_ogni_percorso(self):
        tipo = self.facts["tipo_classification"]
        self.assertIsNone(tipo["rule"], "il tipo torna a essere un IfExp sul pronostico")
        self.assertTrue(tipo["usato_resolve_origin"])
        self.assertTrue(all(tipo["origini_esplicite"].values()), tipo["origini_esplicite"])

    def test_schema_completo(self):
        self.assertEqual(self.facts["missing_from_save"], [],
                         "campi richiesti per misurare il selettore tornati assenti")
        for field in ("origin", "selector_version", "rank", "kickoff_utc",
                      "data_snapshot_sha", "calculation_id", "poisson", "elo",
                      "elo_disponibile"):
            self.assertIn(field, self.facts["new_entry_fields_in_save"], field)

    def test_verdetto_positivo(self):
        self.assertTrue(self.verdict["can_measure_top_mix_in_isolation"],
                        self.verdict["problems"])
        self.assertEqual(self.verdict["problems"], [])


class TestIgieneTopMix(unittest.TestCase):
    """I percorsi di degrado non devono piu' essere silenziosi (§4 dell'audit)."""

    @classmethod
    def setUpClass(cls):
        cls.igiene = inspect_app()["degrado_igiene"]

    def test_get_ha_timeout(self):
        self.assertGreater(self.igiene["requests_get_total"], 0)
        self.assertEqual(self.igiene["requests_get_con_timeout"], self.igiene["requests_get_total"])

    def test_nessun_except_nudo_nel_top_mix(self):
        self.assertEqual(self.igiene["bare_excepts"], 0)

    def test_fallback_elo_marcato_e_soglia_corretta(self):
        self.assertTrue(self.igiene["elo_flag_disponibilita"])
        self.assertTrue(self.igiene["soglia_totali_se_elo_manca"])

    def test_rank_sulla_riga_e_sleep_tra_le_leghe(self):
        self.assertTrue(self.igiene["rank_sulla_riga"])
        self.assertTrue(self.igiene["sleep_guardato_da_indice"])


class TestCoerenzaDialoghetto(unittest.TestCase):
    def test_argmax_sui_sette_mercati(self):
        d = inspect_app()["dialogo_coerente"]
        self.assertEqual(d["argmax_su_n_mercati"], 7, d["mercati_puri_chiavi"])
        self.assertTrue(d["argmax_su_7_mercati"])

    def test_testa_totali_su_lambda_pure(self):
        d = inspect_app()["dialogo_coerente"]
        self.assertEqual(d["due_teste_chiamate"], 1)
        self.assertTrue(d["due_teste_con_pure"],
                        "_two_heads_from_lambdas chiamato senza base_pure_*: i totali "
                        "del dialogo tornano a usare la forma (peggiore, audit §4.4)")


class TestGradingUnico(unittest.TestCase):
    def test_entrata_unica_in_entrambi_i_rami(self):
        g = inspect_app()["grading"]
        self.assertGreaterEqual(g["esito_mercato_chiamato"], 2)
        self.assertEqual(g["catene_elif_superate"], 0, "una catena di elif e' stata re-incollata")
        self.assertEqual(g["bare_excepts_in_aggiorna"], 0)

    def test_tabella_di_grading_allinea_i_due_rami_storici(self):
        """Il ramo per match_id graduava 14 mercati, l'altro 7."""
        vecchi_loop = {"UNDER_2.5", "OVER_2.5", "GG", "NG", "X", "1", "2"}
        self.assertTrue(vecchi_loop <= set(R.MERCATI_GRADABILI))
        for extra in ("UNDER_1.5", "OVER_1.5", "UNDER_3.5", "OVER_3.5", "1X", "X2", "12"):
            self.assertIn(extra, R.MERCATI_GRADABILI)
            self.assertIsNotNone(R.esito_mercato(extra, 2, 1))


class TestRegistroUI(unittest.TestCase):
    def test_brier_e_origine_esposti(self):
        r = inspect_app()["registro_ui"]
        self.assertTrue(r["brier_in_registro"])
        self.assertTrue(r["win_rate_e_brier_insieme"])
        self.assertTrue(r["colonna_origine"])
        self.assertTrue(r["filtro_origine"])

    def test_toast_condizionato(self):
        t = inspect_app()["top_mix_success_toast"]
        self.assertTrue(t["present_in_module"])
        self.assertTrue(t["gated_on_remote_ok"], "il messaggio torna a non leggere l'esito remoto")
        self.assertFalse(t["vecchio_message_incondizionato"])

    def test_save_predictions_legge_la_risposta(self):
        jb = inspect_app()["jsonbin_write"]
        self.assertTrue(jb["put_present"])
        self.assertTrue(jb["status_code_checked"])
        self.assertTrue(jb["ritorna_esito"])
        self.assertTrue(jb["response_assigned"])
        self.assertFalse(jb["bare_excepts"])
        self.assertFalse(jb["except_pass"])


class TestCacheNonCongelaIlTempo(unittest.TestCase):
    def test_rifiltro_all_uso(self):
        c = inspect_app()["top_mix_cache"]
        self.assertEqual(c["ttl_seconds"], 1800, "il TTL non doveva cambiare")
        self.assertTrue(c["no_arguments"], "un argomento per minuto = 5 chiamate API/min")
        self.assertTrue(c["rifiltrata_all_uso"],
                        "manca righe_non_iniziate(): il risultato cached puo' di nuovo "
                        "contenere partite gia' iniziate")


class TestModuloRegistro(unittest.TestCase):
    def test_costanti_di_tracciamento_esistono(self):
        reg = inspect_registry_module()
        self.assertTrue(reg["model_version_current"])
        self.assertTrue(reg["new_prediction_metadata"])
        self.assertTrue(reg["has_origin_field"])
        self.assertTrue(reg["has_selector_version"])
        self.assertTrue(reg["has_calculation_id"])

    def test_la_versione_del_selettore_e_nel_dedup_key(self):
        tree = ast.parse(_src(REGISTRY_PATH))
        fn = _fn(tree, "dedup_key")
        self.assertIn("origin", ast.unparse(fn))
        self.assertIn("selector_version", ast.unparse(fn))

    def test_upsert_non_sovrascrive_le_righe_giudicate(self):
        preds = [{
            "match_id": 5, "origin": R.ORIGIN_TOP_MIX,
            "selector_version": R.SELECTOR_VERSION_CURRENT,
            "esito": R.ESITO_VINTO, "prob_sicuro": 66.0,
        }]
        out, azione = R.upsert_prediction_entry(preds, {
            "match_id": 5, "origin": R.ORIGIN_TOP_MIX,
            "selector_version": R.SELECTOR_VERSION_CURRENT, "prob_sicuro": 99.0,
        })
        self.assertEqual(azione, "gia_graduata")
        self.assertEqual(out[0]["prob_sicuro"], 66.0)


class TestSelettoreInvariato(unittest.TestCase):
    """Nessuna formula o soglia toccata: i costanti del selettore restano quelle."""

    def test_soglie_e_pesi_inalterati(self):
        s = inspect_app()["top_mix_selector"]
        self.assertTrue(s["max_then_filter"])
        self.assertTrue(s["elo_mix_1x2"])
        self.assertTrue(s["min_conf_ou_gg"])
        self.assertTrue(s["min_conf_1x2"])
        self.assertTrue(s["disagree"])
        self.assertTrue(s["global_top10"])
        self.assertFalse(s["has_over_15"])
        self.assertFalse(s["has_over_35"])
        self.assertEqual(R.SELECTOR_VERSION_CURRENT, "topmix_gate025_ens06_v1")

    def test_get_league_engine_usa_il_gate_condiviso(self):
        tree = ast.parse(_src(APP_PATH))
        src = ast.unparse(_fn(tree, "get_league_engine"))
        self.assertIn("_league_mean_gate(xg_data)", src)
        self.assertNotIn("_lx = [v['xG_avg']", src.replace('"', "'"),
                         "il gate di sanita' duplicato e' tornato dentro get_league_engine")


class TestSelettorePuro(unittest.TestCase):
    """L'estrazione deve restare un'estrazione, non un travestimento.

    Il perche' (referto §9 punto 2): la selezione di riga era l'unica parte del
    Top Mix senza test di comportamento, perche' era incastrata fra HTTP e cache
    di Streamlit. Ora ha ``SoccerMath/test_topmix_selector_parity.py``; questa
    classe impedisce che il beneficio si dissipi: I/O reintrodotto dentro la
    funzione (e la parita' verrebbe misurata sugli stub, non sulla realta'), o
    - peggio - il corpo copiato sia nel chiamante sia nella funzione pura, cioe'
    due fonti di verita' che possono divergere in silenzio.
    """

    def test_il_selettore_e_isolato_e_non_duplicato(self):
        f = inspect_app()
        puro = f["selettore_puro"]
        self.assertTrue(puro["presente"],
                        "seleziona_riga_top_mix rimossa: il test di parita' non puo' piu' girare")
        self.assertTrue(puro["pura_davvero"], puro)
        self.assertEqual(["m", "elo_probs", "elo_disponibile", "home", "away"], puro["firma"],
                         "la firma e' il contratto del test di parita': cambiarla rompe il confronto")
        self.assertEqual([], puro["chiamate_io"])
        self.assertEqual([], puro["chiamate_scrittrici"])
        self.assertTrue(puro["ritorna_dett_o_none"])
        self.assertTrue(f["top_mix_selector"]["selezione_in_un_solo_punto"],
                        "i 7 mercati vengono costruiti in due punti")
        self.assertTrue(f["top_mix_selector"]["codice_mercato_chiamato"])

    def test_le_guardie_scattano_su_un_sorgente_mutato(self):
        """Una guardia che non puo' fallire non e' una guardia: qui si prova il fuoco."""
        src = _src(APP_PATH)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "app.py")

            def ispeziona(mutato: str) -> dict:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(mutato)
                return inspect_app(p)

            # (a) I/O reintrodotto nella funzione pura
            con_sleep = src.replace(
                "    best_mkt = max(mercati, key=mercati.get)",
                "    time.sleep(0.1)\n    best_mkt = max(mercati, key=mercati.get)", 1)
            self.assertNotEqual(con_sleep, src, "la mutazione (a) non e' stata applicata")
            f2 = ispeziona(con_sleep)
            self.assertFalse(f2["selettore_puro"]["pura_davvero"], f2["selettore_puro"])
            self.assertEqual(["time"], f2["selettore_puro"]["chiamate_io"])
            self.assertIn("selettore_non_piu_puro",
                          [x["id"] for x in tracking_verdict(f2)["problems"]])

            # (b) corpo duplicato nel chiamante: due copie della selezione
            duplicato = src.replace(
                "    all_preds, missing = [], []",
                '    mercati = {"GG": 0.5}  # duplicato mutato\n'
                "    all_preds, missing = [], []", 1)
            self.assertNotEqual(duplicato, src, "la mutazione (b) non e' stata applicata")
            f3 = ispeziona(duplicato)
            self.assertFalse(f3["top_mix_selector"]["selezione_in_un_solo_punto"],
                             f3["top_mix_selector"])
            self.assertIn("selezione_duplicata",
                          [x["id"] for x in tracking_verdict(f3)["problems"]])

            # (c) il codice vero non deve avere nessuno di questi problemi
            self.assertEqual([], tracking_verdict(ispeziona(src))["problems"])


class TestReadOnlyWorkflow(unittest.TestCase):
    def test_github_action_is_read_only(self):
        path = os.path.join(_REPO_ROOT, ".github", "workflows", "topmix_audit.yml")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("contents: read", src)
        self.assertNotIn("contents: write", src)
        self.assertIn("upload-artifact", src)
        self.assertIn("--fetch-api", src)
        # GET JSONBin consentita; PUT / --apply / --push-remote vietati.
        self.assertNotIn("--apply", src)
        self.assertNotIn("--push-remote", src)
        self.assertNotIn("requests.put", src)
        self.assertNotIn("method: PUT", src)
        self.assertIn("--jsonbin-get", src)

    def test_i_test_del_selettore_girano_in_ci(self):
        """L'unico test che ESEGUIVA fetch_and_calc_top_mix non era in lista."""
        with open(os.path.join(_REPO_ROOT, ".github", "workflows", "topmix_audit.yml"),
                  encoding="utf-8") as f:
            src = f.read()
        for richiesto in ("audit/test_topmix_next_matchday.py",
                          "SoccerMath/test_registry_tracking.py",
                          "SoccerMath/test_topmix_selector_parity.py",
                          "audit/test_topmix_margins.py"):
            self.assertIn(richiesto, src, f"{richiesto} non eseguito in CI")


class TestSourceDoesNotWriteRemoteOnImport(unittest.TestCase):
    def test_no_jsonbin_call_at_module_level(self):
        """Il modulo app.py non chiama JSONBin all'import: solo dentro funzioni."""
        with open(APP_PATH, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        calls_in_functions = set()
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in ("get", "put", "post", "patch"):
                        calls_in_functions.add(id(node))
        module_level_jsonbin = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in ("get", "put", "post", "patch"):
                continue
            func = node.func
            if isinstance(func.value, ast.Name) and func.value.id == "requests":
                dumped = ast.unparse(node)
                if "jsonbin" in dumped.lower() and id(node) not in calls_in_functions:
                    module_level_jsonbin.append(dumped[:80])
        self.assertEqual(module_level_jsonbin, [])


if __name__ == "__main__":
    unittest.main()
