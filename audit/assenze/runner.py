"""Adattatori di I/O per i lettori ufficiali; i parser restano funzioni pure."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from .core import (
    HTTPResponse,
    attach_response,
    decode_html,
    empty_snapshot,
    extract_pdf_text,
    fetch_url,
)
from .laliga import parse_laliga_text
from .ligue1 import parse_ligue1_text
from .policy import SOURCE_LABELS
from .serie_a import diffidati_from_progressives, parse_serie_a_text, triggers_suspension_on_next_yellow
from .team_mapping import decorate_records, load_live_teams


def _failure(snapshot: dict[str, Any], reason: str, *, document_found: bool | None = None) -> dict[str, Any]:
    snapshot["status"] = "not_read"
    snapshot["reason"] = reason
    if document_found is not None:
        snapshot["document_found"] = document_found
    snapshot["rows_extracted"] = 0
    return snapshot


def _fetch_pdf(source: str, url: str, snapshot: dict[str, Any]) -> tuple[str | None, str | None, HTTPResponse]:
    response = fetch_url(source, url)
    attach_response(snapshot, response)
    if response.status_code != 200:
        return None, f"HTTP {response.status_code if response.status_code is not None else 'senza risposta'}: {response.error or 'documento non restituito'}", response
    if response.error:
        return None, response.error, response
    if not response.body:
        return None, "risposta HTTP 200 con zero byte", response
    text, error = extract_pdf_text(response.body)
    if error:
        return None, error, response
    snapshot["document_found"] = True
    return text, None, response


def _fetch_html(source: str, url: str, snapshot: dict[str, Any]) -> tuple[str | None, str | None, HTTPResponse]:
    response = fetch_url(source, url)
    attach_response(snapshot, response)
    if response.status_code != 200:
        return None, f"HTTP {response.status_code if response.status_code is not None else 'senza risposta'}: {response.error or 'pagina non restituita'}", response
    if response.error:
        return None, response.error, response
    text, error = decode_html(response.body)
    if error:
        return None, error, response
    snapshot["document_found"] = True
    return text, None, response


def _not_authorized(source: str, report_window: str) -> dict[str, Any]:
    snapshot = empty_snapshot(source, SOURCE_LABELS[source], report_window)
    snapshot["reason"] = "permesso scritto non confermato nell'input workflow_dispatch; nessuna richiesta HTTP eseguita"
    return snapshot


def _unmatched(records: list[dict[str, Any]]) -> list[str]:
    return sorted({
        str(record.get("team_source") or "(squadra vuota)")
        for record in records
        if record.get("team_match") != "matched"
    }, key=str.casefold)


def _normalize_identity(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    bare = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", bare).strip()


def _aggregate_progressives(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ultimo progressivo ufficiale per giocatore/squadra in ordine giornata."""
    state: dict[tuple[str, str], dict[str, Any]] = {}
    for document in sorted(documents, key=lambda item: int(item.get("matchday") or 0)):
        day = int(document.get("matchday") or 0)
        for row in document.get("cautions", []):
            count = row.get("progressive_count")
            if not isinstance(count, int):
                continue
            key = (_normalize_identity(str(row.get("player_name", ""))), _normalize_identity(str(row.get("team_source", ""))))
            if not key[0]:
                continue
            previous = state.get(key)
            if previous is None or day > int(previous.get("last_seen_matchday", 0)):
                state[key] = {
                    "player_name": row.get("player_name"),
                    "team_source": row.get("team_source"),
                    "progressive_count": count,
                    "last_seen_matchday": day,
                }
            elif day == int(previous.get("last_seen_matchday", 0)):
                previous["progressive_count"] = max(int(previous["progressive_count"]), count)
    return sorted(state.values(), key=lambda row: (str(row.get("team_source", "")).casefold(), str(row.get("player_name", "")).casefold()))


def _diffidati_from_state(progressives: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {**row, "basis": "ultimo progressivo ufficiale nella cronologia comunicati"}
        for row in progressives
        if triggers_suspension_on_next_yellow(int(row["progressive_count"]))
    ]


def _read_history(
    urls: list[str],
    snapshot: dict[str, Any],
    *,
    current_url: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    documents: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_urls = {current_url.strip()}
    if len(urls) > 20:
        return documents, diagnostics, ["massimo 20 PDF storici per esecuzione; nessuna richiesta storica eseguita"]
    for index, url in enumerate(urls, start=1):
        cleaned_url = url.strip()
        if not cleaned_url:
            continue
        if cleaned_url in seen_urls:
            errors.append(f"URL storico duplicato o coincidente con il PDF corrente: {cleaned_url}")
            diagnostics.append({"url": cleaned_url, "status": "not_read", "reason": "URL duplicato"})
            continue
        seen_urls.add(cleaned_url)
        text, error, response = _fetch_pdf("serie_a", cleaned_url, snapshot)
        if error or text is None:
            reason = error or "PDF storico non leggibile"
            errors.append(f"storico {index}: {reason}")
            diagnostics.append({
                "url": cleaned_url,
                "status": "not_read",
                "matchday": None,
                "rows_extracted": 0,
                "reason": reason,
                "http_status": response.status_code,
                "response_bytes": response.response_bytes,
            })
            continue
        parsed = parse_serie_a_text(text)
        if not parsed.get("recognized") or int(parsed.get("rows_extracted", 0)) == 0:
            reason = str(parsed.get("reason") or "schema/righe del PDF storico non riconosciute")
            errors.append(f"storico {index}: {reason}")
            diagnostics.append({
                "url": cleaned_url,
                "status": "not_read",
                "matchday": parsed.get("matchday"),
                "rows_extracted": int(parsed.get("rows_extracted", 0)),
                "reason": reason,
                "http_status": response.status_code,
                "response_bytes": response.response_bytes,
            })
            continue
        documents.append(parsed)
        diagnostics.append({
            "url": cleaned_url,
            "status": "read",
            "matchday": parsed.get("matchday"),
            "rows_extracted": int(parsed.get("rows_extracted", 0)),
            "reason": None,
            "http_status": response.status_code,
            "response_bytes": response.response_bytes,
        })
    return documents, diagnostics, errors


def read_serie_a(
    url: str,
    *,
    authorized: bool,
    report_window: str = "",
    history_urls: list[str] | None = None,
    history_complete_confirmed: bool = False,
) -> dict[str, Any]:
    source = "serie_a"
    if not authorized:
        return _not_authorized(source, report_window)
    snapshot = empty_snapshot(source, SOURCE_LABELS[source], report_window)
    snapshot["source_url"] = url.strip() or None
    if not url.strip():
        return _failure(snapshot, "URL del PDF ufficiale corrente non fornito; nessuna richiesta HTTP eseguita")

    text, error, _ = _fetch_pdf(source, url, snapshot)
    if error or text is None:
        return _failure(snapshot, error or "PDF ufficiale non leggibile", document_found=False)
    parsed = parse_serie_a_text(text)
    if not parsed.get("recognized"):
        return _failure(snapshot, str(parsed.get("reason") or "schema del comunicato non riconosciuto"), document_found=True)
    current_rows = int(parsed.get("rows_extracted", 0))
    if current_rows == 0:
        return _failure(snapshot, str(parsed.get("reason") or "zero righe estratte"), document_found=True)

    try:
        live_teams = load_live_teams(source)
    except (OSError, ValueError) as exc:
        return _failure(snapshot, f"mapping squadre Live non leggibile: {exc}", document_found=True)

    players, unmatched_players = decorate_records(parsed["suspended_players"], source, live_teams)
    coaches, unmatched_coaches = decorate_records(parsed["suspended_coaches"], source, live_teams)
    cautions, unmatched_cautions = decorate_records(parsed["cautions"], source, live_teams)
    observed, unmatched_observed = decorate_records(parsed.get("diffidati_observed", []), source, live_teams)

    snapshot.update({
        "status": "read",
        "reason": None,
        "document_found": True,
        "rows_extracted": current_rows,
        "matchday": parsed.get("matchday"),
        "suspended_players": players,
        "suspended_coaches": coaches,
        "cautions": cautions,
        "diffidati_observed": observed,
        "diffidati": None,
        "diffidati_complete": False,
        "diffidati_rule": "ammonizioni a 5, 9, 13, 16, 18; ogni ammonizione dalla 19ª",
    })

    historical_urls = history_urls or []
    history_documents, history_diagnostics, history_errors = _read_history(
        historical_urls,
        snapshot,
        current_url=url,
    )
    current_for_history = {
        "matchday": parsed.get("matchday"),
        "cautions": parsed.get("cautions", []),
    }
    valid_documents = [*history_documents, current_for_history]
    progressives = _aggregate_progressives(valid_documents)
    rounds_seen = sorted({int(doc["matchday"]) for doc in valid_documents if doc.get("matchday") is not None})
    current_matchday = parsed.get("matchday")
    expected_rounds = list(range(1, int(current_matchday) + 1)) if isinstance(current_matchday, int) else []
    missing_rounds = sorted(set(expected_rounds) - set(rounds_seen))
    coverage_ok = bool(
        history_complete_confirmed
        and not history_errors
        and not missing_rounds
        and expected_rounds
    )
    snapshot["history"] = {
        "complete_confirmed_by_operator": bool(history_complete_confirmed),
        "complete": coverage_ok,
        "rounds_seen": rounds_seen,
        "rounds_expected": expected_rounds,
        "missing_rounds": missing_rounds,
        "documents": history_diagnostics,
        "errors": history_errors,
        "progressives_known": len(progressives),
    }
    snapshot["history_rows_extracted"] = sum(int(doc.get("rows_extracted", 0)) for doc in history_documents)
    if coverage_ok:
        full_diffidati, unmatched_full = decorate_records(_diffidati_from_state(progressives), source, live_teams)
        snapshot["diffidati"] = full_diffidati
        snapshot["diffidati_complete"] = True
        snapshot["unmatched_teams"] = sorted(set(unmatched_players + unmatched_coaches + unmatched_cautions + unmatched_observed + unmatched_full), key=str.casefold)
    else:
        snapshot["unmatched_teams"] = sorted(set(unmatched_players + unmatched_coaches + unmatched_cautions + unmatched_observed), key=str.casefold)
    return snapshot


def read_laliga(url: str, *, authorized: bool, report_window: str = "") -> dict[str, Any]:
    source = "laliga"
    if not authorized:
        return _not_authorized(source, report_window)
    snapshot = empty_snapshot(source, SOURCE_LABELS[source], report_window)
    snapshot["source_url"] = url.strip() or None
    if not url.strip():
        return _failure(snapshot, "URL del PDF ufficiale RFEF non fornito; nessuna richiesta HTTP eseguita")
    text, error, _ = _fetch_pdf(source, url, snapshot)
    if error or text is None:
        return _failure(snapshot, error or "PDF RFEF non leggibile", document_found=False)
    parsed = parse_laliga_text(text)
    if not parsed.get("recognized"):
        return _failure(snapshot, str(parsed.get("reason") or "schema RFEF non riconosciuto"), document_found=True)
    if int(parsed.get("rows_extracted", 0)) == 0:
        return _failure(snapshot, str(parsed.get("reason") or "zero righe squalifica estratte"), document_found=True)
    try:
        live_teams = load_live_teams(source)
    except (OSError, ValueError) as exc:
        return _failure(snapshot, f"mapping squadre Live non leggibile: {exc}", document_found=True)
    players, unmatched = decorate_records(parsed["suspended_players"], source, live_teams)
    snapshot.update({
        "status": "read",
        "reason": None,
        "document_found": True,
        "matchday": parsed.get("matchday"),
        "rows_extracted": len(players),
        "suspended_players": players,
        "unmatched_teams": unmatched,
    })
    return snapshot


def read_ligue1(url: str, *, authorized: bool, report_window: str = "") -> dict[str, Any]:
    source = "ligue1"
    if not authorized:
        return _not_authorized(source, report_window)
    snapshot = empty_snapshot(source, SOURCE_LABELS[source], report_window)
    snapshot["source_url"] = url.strip() or None
    if not url.strip():
        return _failure(snapshot, "URL dell'articolo ufficiale LFP non fornito; nessuna richiesta HTTP eseguita")
    text, error, _ = _fetch_html(source, url, snapshot)
    if error or text is None:
        return _failure(snapshot, error or "pagina LFP non leggibile", document_found=False)
    parsed = parse_ligue1_text(text)
    if not parsed.get("recognized"):
        return _failure(snapshot, str(parsed.get("reason") or "schema LFP non riconosciuto"), document_found=True)
    if int(parsed.get("rows_extracted", 0)) == 0:
        return _failure(snapshot, str(parsed.get("reason") or "zero righe squalifica estratte"), document_found=True)
    try:
        live_teams = load_live_teams(source)
    except (OSError, ValueError) as exc:
        return _failure(snapshot, f"mapping squadre Live non leggibile: {exc}", document_found=True)
    players, unmatched = decorate_records(parsed["suspended_players"], source, live_teams)
    snapshot.update({
        "status": "read",
        "reason": None,
        "document_found": True,
        "rows_extracted": len(players),
        "suspended_players": players,
        "unmatched_teams": unmatched,
    })
    return snapshot


def run_source(
    source: str,
    *,
    url: str = "",
    authorized: bool = False,
    report_window: str = "",
    history_urls_text: str = "",
    history_complete_confirmed: bool = False,
) -> dict[str, Any]:
    if source == "serie_a":
        history_urls = [line.strip() for line in history_urls_text.splitlines() if line.strip()]
        return read_serie_a(
            url,
            authorized=authorized,
            report_window=report_window,
            history_urls=history_urls,
            history_complete_confirmed=history_complete_confirmed,
        )
    if source == "laliga":
        return read_laliga(url, authorized=authorized, report_window=report_window)
    if source == "ligue1":
        return read_ligue1(url, authorized=authorized, report_window=report_window)
    raise ValueError(f"lettore non previsto: {source}")
