"""Fonti ammesse/escluse e diagnostica senza rete per le fonti non automatizzabili."""
from __future__ import annotations

from typing import Any

from .core import empty_snapshot

SOURCE_LABELS = {
    "serie_a": "Giudice Sportivo — Serie A",
    "laliga": "RFEF — Primera División / La Liga",
    "ligue1": "LFP — Ligue 1",
    "rotowire": "RotoWire",
    "premier_injuries": "Premier Injuries",
    "fantacalcio": "Fantacalcio.it",
}

EXCLUDED_SOURCES = {
    "rotowire": (
        "Esclusa prima di qualsiasi richiesta: Article VI dei termini vieta accesso/estrazione automatizzati e scraping; Article VII limita l'uso dei contenuti con strumenti AI. Nessun endpoint o pagina dati interrogati.",
        "https://www.rotowire.com/termsandconditions.php",
    ),
    "premier_injuries": (
        "Esclusa dall'archiviazione GitHub: i termini consentono l'archivio elettronico personale solo su dispositivi non di rete/server; gli snapshot richiesti sarebbero conservati nel repository/Actions. Nessuna pagina dati interrogata.",
        "https://www.premierinjuries.com/terms",
    ),
    "fantacalcio": (
        "Esclusa prima di qualsiasi richiesta: NAVIGAZIONE §3 vieta software/meccanismi automatici o manuali per copiare/accedere alle pagine, incluso scraping, senza autorizzazione scritta ed espressa; vieta inoltre copia/elaborazione dei contenuti senza consenso.",
        "https://www.fantacalcio.it/termini-e-condizioni",
    ),
}


def excluded_snapshot(source: str, report_window: str = "") -> dict[str, Any]:
    if source not in EXCLUDED_SOURCES:
        raise ValueError(f"fonte non classificata come esclusa: {source}")
    reason, terms_url = EXCLUDED_SOURCES[source]
    snapshot = empty_snapshot(source, SOURCE_LABELS[source], report_window)
    snapshot.update({
        "status": "excluded_terms",
        "terms_url": terms_url,
        "source_url": None,
        "reason": reason,
        "document_found": False,
        "rows_extracted": 0,
        "requests": [],
        "http_status": None,
        "response_bytes": 0,
    })
    return snapshot
