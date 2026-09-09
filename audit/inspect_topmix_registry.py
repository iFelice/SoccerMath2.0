"""Ispezione statica (AST) del tracciamento Top Mix nel codice di produzione.

Non importa ``app`` (niente Streamlit), non chiama JSONBin, non scrive il
registro. Serve a verificare *sul codice* se il Registro permette di misurare
il Top Mix, senza accedere ai dati persistiti.
"""
from __future__ import annotations

import ast
import os
import re
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


def _calls_function(fn: Optional[ast.AST], name: str) -> bool:
    if fn is None:
        return False
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id == name:
                return True
            if isinstance(f, ast.Attribute) and f.attr == name:
                return True
    return False


def _assigns_call_to(fn: Optional[ast.AST], attr: str) -> bool:
    """True se il risultato della chiamata ``.<attr>(...)`` viene assegnato."""
    if fn is None:
        return False
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            f = node.value.func
            if isinstance(f, ast.Attribute) and f.attr == attr:
                return True
    return False


def _toast_uses(text: str, mod: ast.AST, calls: Tuple[str, ...] = ("success", "warning", "error", "info")) -> bool:
    """True se una chiamata st.<calls...> CONTIENE `text` (f-string inclusive)."""
    for node in ast.walk(mod):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in calls and text in ast.unparse(node):
                return True
    return False


def _bare_excepts(fn: Optional[ast.AST]) -> int:
    """Numero di ``except:`` nudi (senza tipo) dentro ``fn``."""
    if fn is None:
        return 0
    n = 0
    for node in ast.walk(fn):
        if isinstance(node, ast.Try):
            for h in node.handlers:
                if h.type is None:
                    n += 1
    return n


def _if_gates_call(module_tree: ast.AST, test_token: str, ok_call: str,
                   ko_call: str) -> bool:
    """True se esiste un ``if`` il cui test contiene ``test_token`` e che ha un
    ramo con ``ok_call`` e un ``else`` con ``ko_call`` (o viceversa).

    Usato per verificare che il messaggio "salvato" sia CONDITIONATO
    all'esito reale della scrittura, non stampato a prescindere.
    """
    for node in ast.walk(module_tree):
        if not isinstance(node, ast.If):
            continue
        if test_token not in ast.unparse(node.test):
            continue
        corpo = ast.unparse(ast.Module(body=list(node.body), type_ignores=[]))
        orelse = ast.unparse(ast.Module(body=list(node.orelse), type_ignores=[])) if node.orelse else ""
        if (ok_call in corpo and ko_call in orelse) or (ko_call in corpo and ok_call in orelse):
            return True
    return False


def inspect_app(path: str = APP_PATH) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        raw_src = f.read()
    tree = ast.parse(raw_src, filename=path)
    module_src_raw = ast.unparse(tree)
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
        "chiave_completa": False,
        "passa_origine": False,
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
    if save_entry is not None:
        dedup["chiave_completa"] = ("origin" in src and "selector_version" in src
                                    and _calls_function(save_entry, "upsert_prediction_entry"))
        dedup["passa_origine"] = "resolve_origin(" in src
    else:
        dedup["chiave_completa"] = False
        dedup["passa_origine"] = False
    facts["dedup_by_match_id"] = dedup

    # --- tipo: Top Mix vs Analisi (Billy non ha un tipo proprio) ---
    tipo = {
        "field": "tipo",
        "top_mix_marker": "Top Mix" in (ast.unparse(save_entry) if save_entry else ""),
        "billy_tipo_esplicito": False,
        "fallback_label": "Analisi",
        "rule": None,
    }
    src_save = ast.unparse(save_entry) if save_entry is not None else ""
    module_blob = ast.unparse(tree)
    if save_entry is not None:
        for node in ast.walk(save_entry):
            if isinstance(node, ast.IfExp):
                text = ast.unparse(node)
                if "Top Mix" in text and "Analisi" in text:
                    tipo["rule"] = text
                    tipo["billy_tipo_esplicito"] = "Billy" in text
    tipo["origini_esplicite"] = {
        o: (f'origin={o},' in module_blob or f'origin={o})' in module_blob)
        for o in ("ORIGIN_TOP_MIX", "ORIGIN_ANALISI_RAPIDA", "ORIGIN_BILLY")
    }
    tipo["usato_resolve_origin"] = bool(save_entry is not None and "resolve_origin(" in src_save)
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
            "origin", "selector_version", "rank", "kickoff_utc",
            "data_snapshot_sha", "calculation_id", "poisson", "elo",
            "elo_disponibile",
        ):
            if f'"{field}"' in src or f"'{field}'" in src:
                facts["new_entry_fields_in_save"].append(field)
        # `position` (posizione di classifica) NON e' in lista: non serve a
        # misurare il selettore, e' un dato contestuale del solo dialogo Billy.
        facts["missing_from_save"] = [
            f for f in (
                "calculation_id", "origin", "selector_version", "rank",
                "kickoff_utc", "data_snapshot_sha", "poisson", "elo",
                "elo_disponibile",
            ) if f'"{f}"' not in src and f"'{f}'" not in src
        ]

    # --- JSONBin PUT ---
    jsonbin = {
        "put_present": False,
        "response_assigned": False,
        "status_code_checked": False,
        "except_pass": False,
        "bare_put_swallowed": False,
        "bare_excepts": 0,
        "ritorna_esito": False,
    }
    if save_preds is not None:
        src = ast.unparse(save_preds)
        jsonbin["put_present"] = "requests.put" in src
        jsonbin["status_code_checked"] = "status_code" in src
        jsonbin["except_pass"] = _put_is_bare_in_try_except_pass(save_preds)
        jsonbin["bare_put_swallowed"] = jsonbin["except_pass"]
        jsonbin["response_assigned"] = _assigns_call_to(save_preds, "put")
        jsonbin["bare_excepts"] = _bare_excepts(save_preds)
        # L'esito della scrittura deve TORNA.RE al chiamante, altrimenti il
        # messaggio all'utente non puo' essere condizionato a nulla.
        jsonbin["ritorna_esito"] = bool(
            [n for n in ast.walk(save_preds) if isinstance(n, ast.Return) and n.value is not None]
        )
    facts["jsonbin_write"] = jsonbin

    # --- cache Top Mix ---
    # Il difetto reale non e' il TTL in se': e' che il `now` calcolato DENTRO la
    # funzione cached resta congelato per tutta la TTL. La mitigazione corretta
    # non e' passare un argomento (farebbe 5 chiamate API al minuto contro il
    # limite free di 10) ma rifiltrare le righe al momento dell'uso.
    cache = {"ttl_seconds": None, "no_arguments": None,
             "rifiltrata_all_uso": False, "righe_iniziate_scartate": False}
    if top_mix is not None:
        cache["ttl_seconds"] = _decorator_ttl(top_mix)
        cache["no_arguments"] = len(top_mix.args.args) == 0
    cache["rifiltrata_all_uso"] = "righe_non_iniziate(" in module_src_raw
    cache["righe_iniziate_scartate"] = "righe_non_iniziate(" in module_src_raw
    facts["top_mix_cache"] = cache

    # --- success toast ---
    facts["top_mix_success_toast"] = {
        # Il messaggio, DOPO la correzione, dice cosa e' successo davvero (quante
        # righe, e se il remoto ha risposto) invece di "salvati!" a prescindere.
        "message": "✅ Top Mix nel registro: N nuove, M aggiornate, K gia' giudicate",
        # Si cercano le CHIAMATE di messaggio, non il testo ovunque: i
        # docstring dei due fix citano il vecchio toast e darebbero falsi positivi.
        "present_in_module": _toast_uses("Top Mix nel registro", tree),
        "vecchio_message_incondizionato": _toast_uses("Top Mix salvati!", tree),
        "gated_on_remote_ok": False,  # verificato sotto
        "gated_on_save_count": False,
    }
    # Il toast vive nel corpo modulo (tab2), non in una funzione.
    module_src = module_src_raw
    facts["top_mix_success_toast"]["gated_on_remote_ok"] = _if_gates_call(
        tree, "n_err_remoto", "st.warning", "st.success"
    )
    facts["top_mix_success_toast"]["gated_on_save_count"] = _if_gates_call(
        tree, "esiti_save", "st.info", "st.success"
    ) or facts["top_mix_success_toast"]["gated_on_remote_ok"]
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
            "elo_mix_1x2": "ELO_ENSEMBLE_W * poisson_prob + (1 - ELO_ENSEMBLE_W) * elo_prob" in src,
            # Il sorgente scrive 0.60; ast.unparse normalizza a 0.6.
            "min_conf_ou_gg": "min_conf = 0.60" in raw_src or "min_conf = 0.6" in src,
            "min_conf_1x2": "min_conf = 0.55" in src or "min_conf = 0.55" in raw_src,
            "disagree": "abs(poisson_prob - elo_prob) < 0.25" in src,
            "global_top10": "[:10]" in src,
        }
    facts["top_mix_selector"] = seven

    # --- igiene dei percorsi di degrado (audit §4 punti 1-3) ---
    igiene: Dict[str, Any] = {}
    if top_mix is not None:
        src_tm = ast.unparse(top_mix)
        getters = [n for n in ast.walk(top_mix)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "get" and isinstance(n.func.value, ast.Name)
                   and n.func.value.id == "requests"]
        igiene["requests_get_total"] = len(getters)
        igiene["requests_get_con_timeout"] = sum(
            1 for g in getters if any(kw.arg == "timeout" for kw in g.keywords))
        igiene["bare_excepts"] = _bare_excepts(top_mix)
        igiene["elo_flag_disponibilita"] = ("elo_disponibile" in src_tm
                                           and "elo_disponibile = False" in src_tm)
        # senza Elo la confidence e' Poisson puro: deve valere la soglia 0,60
        igiene["soglia_totali_se_elo_manca"] = "or not elo_disponibile:" in src_tm
        igiene["rank_sulla_riga"] = bool(re.search(r"\['rank'\]\s*=\s*i \+ 1", src_tm)
                                          or re.search(r'\["rank"\]\s*=\s*i \+ 1', src_tm))
        # la coda di rate-limit serve FRA le leghe, non dopo l'ultima
        igiene["sleep_guardato_da_indice"] = bool(re.search(r"if i_lega:\s*\n\s*time\.sleep", src_tm))
    facts["degrado_igiene"] = igiene

    # --- coerenza dialoghetto / card (audit §4 punto 4) ---
    dialogo: Dict[str, Any] = {}
    if show is not None:
        src_sh = ast.unparse(show)
        # Conteggio STRUTTURALE delle chiavi del dizionario usato per l'argmax
        # (ast.unparse normalizza le virgolette, quindi non si cerca testo).
        chiavi: list = []
        for node in ast.walk(show):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                for tgt in node.targets:
                    # chiavi = numero di mercati su cui viene fatto l'argmax;
                    # le chiavi f-string ("Vittoria {h}") non sono Costanti e
                    # contano solo nel totale.
                    if isinstance(tgt, ast.Name) and tgt.id == "mercati_puri":
                        chiavi = [k.value for k in node.value.keys
                                  if isinstance(k, ast.Constant)] + [None] * sum(
                            1 for k in node.value.keys if not isinstance(k, ast.Constant))
        dialogo["mercati_puri_chiavi"] = [c for c in chiavi if c]
        dialogo["argmax_su_n_mercati"] = len(chiavi)
        dialogo["argmax_su_7_mercati"] = len(chiavi) == 7 and {"GG", "NG"} <= set(chiavi)
        th = [n for n in ast.walk(show) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Name) and n.func.id == "_two_heads_from_lambdas"]
        dialogo["due_teste_chiamate"] = len(th)
        dialogo["due_teste_con_pure"] = bool(th) and all(
            len(c.args) >= 5 or any(kw.arg in ("base_pure_h", "base_pure_a") for kw in c.keywords)
            for c in th
        )
    facts["dialogo_coerente"] = dialogo

    # --- grading unico (audit §4 punto 6) e Brier nel registro (§7) ---
    grading: Dict[str, Any] = {"esito_mercato_chiamato": 0, "catene_elif_superate": 0,
                               "bare_excepts_in_aggiorna": 0}
    agg = _fn(tree, "aggiorna_risultati_reali")
    if agg is not None:
        src_agg = ast.unparse(agg)
        grading["esito_mercato_chiamato"] = src_agg.count("esito_mercato(")
        grading["catene_elif_superate"] = src_agg.count('elif m == "X2"')
        grading["bare_excepts_in_aggiorna"] = _bare_excepts(agg)
    facts["grading"] = grading
    facts["registro_ui"] = {
        "brier_in_registro": "calibration_by_mercato(" in module_src_raw,
        "win_rate_e_brier_insieme": "compute_calibration_stats(" in module_src_raw,
        "colonna_origine": ("df_preds['origine']" in module_src_raw
                            or 'df_preds["origine"]' in module_src_raw),
        "filtro_origine": "filter_origine" in module_src_raw,
    }
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
    """Sintesi: il Registro permette di misurare il Top Mix in isolamento?

    Prima di ``audit/margini_migliorabili_topmix.md`` §7 questa funzione
    restituiva `can_measure_top_mix_in_isolation: False` **perche' il codice non
    permetteva la misura** (dedup per solo match_id, tipo derivato dal testo,
    PUT non verificato, campi assenti). Ora i problemi sono derivati dal codice
    e la bandiera e' calcolata: se qualcuno re-introduce un `except: pass` o
    il vecchio `return` sul match_id, il verdetto torna `False` e i test
    dell'audit falliscono.
    """
    facts = app_facts or inspect_app()
    problems: List[Dict[str, str]] = []

    ded = facts.get("dedup_by_match_id") or {}
    if (ded.get("present") and ded.get("early_return")) or not ded.get("chiave_completa"):
        problems.append({
            "id": "dedup_match_id",
            "severity": "blocking",
            "summary": (
                "save_prediction_entry non usa la chiave (match_id, origin, "
                "selector_version): una riga Top Mix puo' di nuovo non essere "
                "registrata perche' Analisi Rapida o Billy hanno salvato prima."
            ),
        })

    tipo = facts.get("tipo_classification") or {}
    origini = tipo.get("origini_esplicite") or {}
    if not (tipo.get("usato_resolve_origin") and origini and all(origini.values())):
        problems.append({
            "id": "origin_collapsed",
            "severity": "blocking",
            "summary": (
                "L'origine della previsione non e' passata esplicitamente da "
                "tutti i percorsi (Top Mix / Analisi Rapida / Billy): il campo "
                "tipo torna a dipendere dal testo libero del pronostico."
            ),
        })

    cache = facts.get("top_mix_cache") or {}
    if cache.get("ttl_seconds") == 1800 and cache.get("no_arguments") and not cache.get("rifiltrata_all_uso"):
        problems.append({
            "id": "cache_30min",
            "severity": "high",
            "summary": (
                "fetch_and_calc_top_mix e' cache_data(ttl=1800) senza argomenti "
                "e il risultato non viene rifiltrato contro l'orologio reale al "
                "momento dell'uso: partite gia' iniziate possono restare in Top "
                "Mix ed essere salvate."
            ),
        })

    jb = facts.get("jsonbin_write") or {}
    if jb.get("put_present") and not (jb.get("status_code_checked") and jb.get("ritorna_esito")):
        problems.append({
            "id": "jsonbin_unchecked",
            "severity": "high",
            "summary": (
                "save_predictions non verifica status_code del PUT o non ne "
                "restituisce l'esito: un messaggio 'salvato' puo' di nuovo "
                "descrivere un record che non esiste nel remoto."
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

    ig = facts.get("degrado_igiene") or {}
    if ig:
        guasti = []
        if ig.get("bare_excepts"):
            guasti.append(f"{ig['bare_excepts']} except: nudi")
        if ig.get("requests_get_con_timeout", 0) < ig.get("requests_get_total", 0):
            guasti.append("richieste senza timeout")
        if not ig.get("elo_flag_disponibilita"):
            guasti.append("fallback Elo non marcato")
        if not ig.get("soglia_totali_se_elo_manca"):
            guasti.append("soglia 1X2 non rialzata quando l'Elo manca")
        if not ig.get("rank_sulla_riga"):
            guasti.append("rank non persistito sulla riga")
        if not ig.get("sleep_guardato_da_indice"):
            guasti.append("rate-limit sleep non condizionato alla lega in coda")
        if guasti:
            problems.append({
                "id": "topmix_degrado_silenzioso",
                "severity": "high",
                "summary": "Percorsi di degrado del Top Mix: " + "; ".join(guasti),
            })

    dl = facts.get("dialogo_coerente") or {}
    if dl and (not dl.get("argmax_su_7_mercati") or not dl.get("due_teste_con_pure")):
        problems.append({
            "id": "dialogo_divergente",
            "severity": "medium",
            "summary": (
                "show_details non coincide con la card/Top Mix: "
                + ("argmax non sui 7 mercati. " if not dl.get("argmax_su_7_mercati") else "")
                + ("_two_heads_from_lambdas chiamato senza lambda pure."
                   if not dl.get("due_teste_con_pure") else "")
            ),
        })

    gr = facts.get("grading") or {}
    if gr and (gr.get("esito_mercato_chiamato", 0) < 2 or gr.get("catene_elif_superate", 0) > 0
               or gr.get("bare_excepts_in_aggiorna", 0) > 0):
        problems.append({
            "id": "grading_duplicato",
            "severity": "medium",
            "summary": (
                "aggiorna_risultati_reali non usa la tabella unica "
                "prediction_registry.esito_mercato in entrambi i rami: alcuni "
                "mercati possono tornare a restare \u23f3 per sempre."
            ),
        })

    reg = facts.get("registro_ui") or {}
    if reg and not (reg.get("brier_in_registro") and reg.get("colonna_origine")):
        problems.append({
            "id": "registro_solo_win_rate",
            "severity": "medium",
            "summary": (
                "Il registro non espone il Brier/calibrazione per mercato e per "
                "origine, anche se prob_sicuro e' persistito: la misura live di "
                "affidabilita' non e' visibile."
            ),
        })

    return {
        "can_measure_top_mix_in_isolation": not problems,
        "problems": problems,
        "facts": facts,
    }


if __name__ == "__main__":
    import json
    v = tracking_verdict()
    print(json.dumps({k: v[k] for k in ("can_measure_top_mix_in_isolation", "problems")},
                     ensure_ascii=False, indent=2))
