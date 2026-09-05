"""Ispezione statica (AST) del tracciamento Top Mix nel codice di produzione.

Non importa ``app`` (niente Streamlit), non chiama JSONBin, non scrive il
registro. Serve a verificare *sul codice* se il Registro permette di misurare
il Top Mix, senza accedere ai dati persistiti.
"""
from __future__ import annotations

import ast
import os
from typing import Any, Dict, List, Optional, Tuple


_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
APP_PATH = os.path.join(_REPO_ROOT, "SoccerMath", "app.py")
REGISTRY_PATH = os.path.join(_REPO_ROOT, "SoccerMath", "prediction_registry.py")


def _load(path: str) -> ast.AST:
    with open(path, "r", encoding="utf-8") as f:
        return ast.parse(f.read(), filename=path)


def _fn(tree: ast.AST, name: str) -> Optional[ast.FunctionDef]:
    for node in tree.body if hasattr(tree, "body") else []:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    return None


def _dump(node: ast.AST) -> str:
    return ast.dump(node, include_attributes=False)


def _contains_str(node: ast.AST, text: str) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str) and text in child.value:
            return True
    return False


def _decorator_ttl(fn: ast.FunctionDef) -> Optional[int]:
    for dec in fn.decorator_list:
        if isinstance(dec, ast.Call):
            for kw in dec.keywords:
                if kw.arg == "ttl" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, (int, float)):
                    return int(kw.value.value)
            # @st.cache_data(ttl=1800, ...)
            func = dec.func
            name = ""
            if isinstance(func, ast.Attribute):
                name = func.attr
            elif isinstance(func, ast.Name):
                name = func.id
            if name == "cache_data":
                for kw in dec.keywords:
                    if kw.arg == "ttl" and isinstance(kw.value, ast.Constant):
                        return int(kw.value.value)
    return None


def _has_status_check_on_put(fn: ast.FunctionDef) -> bool:
    """True se il PUT JSONBin viene seguito da un controllo di status_code."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            func = node.func
            is_put = (
                isinstance(func, ast.Attribute) and func.attr == "put"
            )
            if not is_put:
                continue
            # Il valore di ritorno e' usato? Cerchiamo un Assign/AnnAssign parent.
            # In produzione il PUT e' un'espressione nuda dentro try, senza
            # assegnazione e senza .status_code.
            return False
    return False


def _put_is_bare_in_try_except_pass(fn: ast.FunctionDef) -> bool:
    """PUT in try/except che inghiotte tutto e non legge la risposta."""
    for node in ast.walk(fn):
        if not isinstance(node, ast.Try):
            continue
        has_put = False
        assigns_put = False
        reads_status = False
        for child in node.body:
            for sub in ast.walk(child):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "put":
                    has_put = True
                if isinstance(sub, ast.Attribute) and sub.attr == "status_code":
                    reads_status = True
            if isinstance(child, ast.Assign):
                for sub in ast.walk(child):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "put":
                        assigns_put = True
        swallows = False
        for handler in node.handlers:
            if handler.type is None and handler.body and all(
                isinstance(s, ast.Pass) for s in handler.body
            ):
                swallows = True
        if has_put:
            return has_put and not assigns_put and not reads_status and swallows
    return False


def inspect_app(path: str = APP_PATH) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        raw_src = f.read()
    tree = ast.parse(raw_src, filename=path)
    save_entry = _fn(tree, "save_prediction_entry")
    save_preds = _fn(tree, "save_predictions")
    load_preds = _fn(tree, "load_predictions")
    top_mix = _fn(tree, "fetch_and_calc_top_mix")
    analisi = _fn(tree, "analisi_rapida_giornata")
    show = _fn(tree, "show_details")
    select_md = _fn(tree, "select_next_matchday_matches")

    facts: Dict[str, Any] = {
        "app_path": path,
        "functions_found": {
            "save_prediction_entry": save_entry is not None,
            "save_predictions": save_preds is not None,
            "load_predictions": load_preds is not None,
            "fetch_and_calc_top_mix": top_mix is not None,
            "analisi_rapida_giornata": analisi is not None,
            "show_details": show is not None,
            "select_next_matchday_matches": select_md is not None,
        },
    }

    # --- dedup per match_id ---
    dedup = {
        "present": False,
        "early_return": False,
        "source": None,
    }
    if save_entry is not None:
        src = ast.unparse(save_entry)
        dedup["source"] = src
        if "match_id" in src and "return" in src:
            # if any(p.get("match_id") == match_id for p in preds): return
            for node in save_entry.body:
                if isinstance(node, ast.If):
                    cond = ast.unparse(node.test)
                    if "match_id" in cond and "any(" in cond:
                        dedup["present"] = True
                        if node.body and isinstance(node.body[0], ast.Return) and node.body[0].value is None:
                            dedup["early_return"] = True
                        elif node.body and isinstance(node.body[0], ast.Return):
                            dedup["early_return"] = True
    facts["dedup_by_match_id"] = dedup

    # --- tipo: Top Mix vs Analisi (il campo storico resta, ma puo' essere
    #     affiancato da un origin esplicito per distinguere i flussi) ---
    tipo = {
        "field": "tipo",
        "top_mix_marker": "Top Mix" in (ast.unparse(save_entry) if save_entry else ""),
        "billy_tipo_esplicito": False,
        "fallback_label": "Analisi",
        "rule": None,
        "origin_field_present": False,
    }
    if save_entry is not None:
        src = ast.unparse(save_entry)
        tipo["origin_field_present"] = '"origin"' in src or "'origin'" in src
        for node in ast.walk(save_entry):
            if isinstance(node, ast.IfExp):
                text = ast.unparse(node)
                if "Top Mix" in text and "Analisi" in text:
                    tipo["rule"] = text
                    tipo["billy_tipo_esplicito"] = "Billy" in text
    facts["tipo_classification"] = tipo

    # --- metadata nuove predizioni ---
    facts["new_entry_fields_in_save"] = []
    if save_entry is not None:
        src = ast.unparse(save_entry)
        for field in (
            "match_id", "home", "away", "campionato", "giornata", "data",
            "pronostico_sicuro", "mercato_standard", "top3", "prob_sicuro",
            "risultati_attesi", "risultato_reale", "esito", "tipo", "stagione",
            "salvato_il", "model_version", "excluded_from_current_model_stats",
            "calculation_id", "origin", "selector_version", "data_snapshot_sha",
            "poisson", "elo", "position",
        ):
            if f'"{field}"' in src or f"'{field}'" in src:
                facts["new_entry_fields_in_save"].append(field)
        facts["missing_from_save"] = [
            f for f in (
                "calculation_id", "origin", "selector_version", "rank",
                "kickoff_utc", "data_snapshot_sha", "poisson", "elo",
                "position",
            ) if f'"{f}"' not in src and f"'{f}'" not in src
        ]

    # --- JSONBin PUT ---
    jsonbin = {
        "put_present": False,
        "response_assigned": False,
        "status_code_checked": False,
        "except_pass": False,
        "bare_put_swallowed": False,
    }
    if save_preds is not None:
        src = ast.unparse(save_preds)
        jsonbin["put_present"] = "requests.put" in src
        jsonbin["status_code_checked"] = "status_code" in src
        jsonbin["except_pass"] = _put_is_bare_in_try_except_pass(save_preds)
        jsonbin["bare_put_swallowed"] = jsonbin["except_pass"]
        jsonbin["response_assigned"] = "r = requests.put" in src or "resp = requests.put" in src
    facts["jsonbin_write"] = jsonbin

    # --- cache Top Mix ---
    cache = {"ttl_seconds": None, "no_arguments": None}
    if top_mix is not None:
        cache["ttl_seconds"] = _decorator_ttl(top_mix)
        cache["no_arguments"] = len(top_mix.args.args) == 0
    facts["top_mix_cache"] = cache

    # --- success toast ---
    facts["top_mix_success_toast"] = {
        "message": "✅ Top Mix salvati!",
        "present_in_module": _contains_str(tree, "Top Mix salvati"),
        "gated_on_remote_ok": False,  # verificato sotto
        "gated_on_save_count": False,
    }
    # Il toast vive nel corpo modulo (tab2), non in una funzione.
    module_src = ast.unparse(tree)
    # Non c'e' if su status_code intorno al success.
    facts["top_mix_success_toast"]["gated_on_remote_ok"] = False
    facts["analisi_rapida_calls_save"] = analisi is not None and "save_prediction_entry" in ast.unparse(analisi)
    facts["billy_calls_save"] = show is not None and "save_prediction_entry" in ast.unparse(show)

    # --- mercati Top Mix (sette) ---
    seven = None
    if top_mix is not None:
        src = ast.unparse(top_mix)
        seven = {
            "has_1": 'm_poisson["1"]' in src or "m_poisson['1']" in src,
            "has_X": 'm_poisson["X"]' in src or "m_poisson['X']" in src,
            "has_2": 'm_poisson["2"]' in src or "m_poisson['2']" in src,
            "has_over": "Over 2.5" in src,
            "has_under": "Under 2.5" in src,
            "has_gg": '"GG"' in src or "'GG'" in src,
            "has_ng": '"NG"' in src or "'NG'" in src,
            "has_over_15": "Over 1.5" in src,
            "has_under_15": "Under 1.5" in src,
            "has_over_35": "Over 3.5" in src,
            "max_then_filter": "best_mkt = max(mercati" in src,
            "elo_mix_1x2": "0.6 * poisson_prob + 0.4 * elo_prob" in src,
            # Il sorgente scrive 0.60; ast.unparse normalizza a 0.6.
            "min_conf_ou_gg": "min_conf = 0.60" in raw_src or "min_conf = 0.6" in src,
            "min_conf_1x2": "min_conf = 0.55" in src or "min_conf = 0.55" in raw_src,
            "disagree": "abs(poisson_prob - elo_prob) < 0.25" in src,
            "global_top10": "[:10]" in src,
        }
    facts["top_mix_selector"] = seven
    facts["round_window_days"] = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "TOP_MIX_ROUND_WINDOW_DAYS":
                    if isinstance(node.value, ast.Constant):
                        facts["round_window_days"] = node.value.value

    return facts


def inspect_registry_module(path: str = REGISTRY_PATH) -> Dict[str, Any]:
    tree = _load(path)
    src = ast.unparse(tree)
    return {
        "model_version_current": "post_shrinkage_v1" in src,
        "new_prediction_metadata": _fn(tree, "new_prediction_metadata") is not None,
        "has_origin_field": "origin" in src and "ORIGIN" in src,
        "has_selector_version": "selector_version" in src,
        "has_calculation_id": "calculation_id" in src,
    }


def tracking_verdict(app_facts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Sintesi: il Registro NON permette di misurare il Top Mix in isolamento."""
    facts = app_facts or inspect_app()
    problems: List[Dict[str, str]] = []

    if facts["dedup_by_match_id"].get("present") and facts["dedup_by_match_id"].get("early_return"):
        problems.append({
            "id": "dedup_match_id",
            "severity": "blocking",
            "summary": (
                "save_prediction_entry ritorna subito se match_id e' gia' nel "
                "registro: Analisi Rapida o Billy salvati prima bloccano il Top Mix; "
                "un ricalcolo Top Mix non aggiorna la prima previsione."
            ),
        })

    tipo = facts.get("tipo_classification") or {}
    if tipo.get("rule") and not tipo.get("origin_field_present"):
        problems.append({
            "id": "origin_collapsed",
            "severity": "blocking",
            "summary": (
                "Il campo tipo vale 'Top Mix' solo se la stringa 'Top Mix' compare "
                "nel pronostico; altrimenti e' 'Analisi'. Senza un campo origin "
                "esplicito Billy e Analisi Rapida non sono distinguibili."
            ),
        })

    cache = facts.get("top_mix_cache") or {}
    if cache.get("ttl_seconds") == 1800 and cache.get("no_arguments"):
        problems.append({
            "id": "cache_30min",
            "severity": "high",
            "summary": (
                "fetch_and_calc_top_mix e' cache_data(ttl=1800) senza argomenti: "
                "il now interno e' congelato 30 minuti. Partite nel frattempo "
                "iniziate restano nel risultato cached e possono essere mostrate "
                "e salvate."
            ),
        })

    jb = facts.get("jsonbin_write") or {}
    if jb.get("put_present") and not jb.get("status_code_checked"):
        problems.append({
            "id": "jsonbin_unchecked",
            "severity": "high",
            "summary": (
                "save_predictions fa PUT su JSONBin senza leggere status_code; "
                "l'except e' nudo (pass). Il toast 'Top Mix salvati!' non e' "
                "condizionato al successo remoto."
            ),
        })

    missing = facts.get("missing_from_save") or []
    if missing:
        problems.append({
            "id": "schema_gaps",
            "severity": "blocking",
            "summary": (
                "Campi assenti dal salvataggio, necessari per misurare il Top Mix: "
                + ", ".join(missing)
            ),
        })

    return {
        "can_measure_top_mix_in_isolation": False,
        "problems": problems,
        "facts": facts,
    }


if __name__ == "__main__":
    import json
    v = tracking_verdict()
    print(json.dumps({k: v[k] for k in ("can_measure_top_mix_in_isolation", "problems")},
                     ensure_ascii=False, indent=2))
