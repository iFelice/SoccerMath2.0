#!/usr/bin/env python3
"""totals_probe.py — sonda The Odds API, mercato TOTALS (Over/Under), audit.

Scarica, per le 5 leghe del progetto, GET /v4/sports/{key}/odds con
``markets=totals``, ``regions=eu``: UNA chiamata per lega. Salva la risposta
GREZZA (corpo JSON invariato + intestazioni dei crediti) in
``audit/data/totals_probe/<sport_key>.json`` e un riepilogo in
``audit/data/totals_probe/_summary.json``.

COSTO ATTESO: 1 credito per chiamata (1 mercato x 1 regione), 5 crediti in tutto.
Il costo EFFETTIVO e' quello che The Odds API riporta negli header
``x-requests-last`` / ``x-requests-used`` / ``x-requests-remaining``: lo script li
salva e non stima nulla.

SICUREZZA. La chiave viene letta da ``ODDS_API_KEY`` nell'ambiente e NON viene mai
scritta su file ne' stampata: gli URL salvati hanno ``apiKey=***``; i messaggi di
errore passano dal mascheramento. Nessun ``set -x`` nel workflow.

NON LANCIARLO in sviluppo: lo esegue il workflow manuale
``.github/workflows/totals_probe.yml`` (workflow_dispatch, nessun cron).

Uscite di codice: 0 = tutte le leghe scaricate; 1 = almeno una lega con errore
(le altre sono salvate); 3 = ODDS_API_KEY assente. Dopo un 401/403/429 lo script
si FERMA (non brucia altri crediti).

Uso: ``ODDS_API_KEY=... python audit/totals_probe.py [--out audit/data/totals_probe]``
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AUDIT_DIR)
DEFAULT_OUT = os.path.join(_AUDIT_DIR, "data", "totals_probe")

from live_odds_probe import (  # noqa: E402  (stessi helper della sonda 1X2: mascheramento, header)
    CREDIT_HEADERS, LEAGUES, ODDS_HOST, _http, get_json,
)

MARKETS = "totals"
REGIONS = "eu"
STOP_STATUS = {401, 403, 429}
FORBIDDEN_IN_FILES = ("apiKey=",)   # nessun URL con chiave deve finire nei file (ammesso solo apiKey=***)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_url(sport_key: str, key: str) -> str:
    return (f"{ODDS_HOST}/v4/sports/{sport_key}/odds/?apiKey={key}"
            f"&regions={REGIONS}&markets={MARKETS}&oddsFormat=decimal&dateFormat=iso")


def envelope(sport_key: str, league: str, meta: dict, payload) -> dict:
    """Busta grezza salvata su disco: corpo invariato + metadati senza chiave."""
    return {
        "lega": league,
        "sport_key": sport_key,
        "mercato": MARKETS,
        "regioni": REGIONS,
        "fetched_at_utc": meta.get("fetched_at_utc", _now()),
        "url_masked": meta.get("url_masked"),
        "status": meta.get("status"),
        "ok": bool(meta.get("ok")),
        "error": meta.get("error"),
        "headers": meta.get("headers", {}),
        "body": payload,
    }


def assert_no_key(text: str) -> None:
    """Rifiuta la scrittura se nel testo compare un parametro apiKey con valore reale."""
    stripped = text.replace("apiKey=***", "")
    if any(bad in stripped for bad in FORBIDDEN_IN_FILES):
        raise RuntimeError("chiave API trovata nel file da salvare: rifiuto di scrivere")


def write_json(path: str, obj) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    assert_no_key(text)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key:
        print("ERROR: ODDS_API_KEY assente nell'ambiente", file=sys.stderr)
        return 3

    session = _http().Session()
    summary = {"generato_il": _now(), "mercato": MARKETS, "regioni": REGIONS,
               "chiamate_previste": len(LEAGUES), "leghe": []}
    exit_code = 0
    for league, sport in LEAGUES:
        url = build_url(sport, key)
        payload, meta = get_json(url, key, session)
        # payload None (errore) -> busta con body null: il file documenta l'errore
        env = envelope(sport, league, meta, payload)
        write_json(os.path.join(args.out, f"{sport}.json"), env)
        n_ev = len(payload) if isinstance(payload, list) else None
        summary["leghe"].append({
            "lega": league, "sport_key": sport, "ok": bool(meta.get("ok")),
            "status": meta.get("status"), "eventi": n_ev,
            "headers": meta.get("headers", {}), "error": meta.get("error"),
        })
        print(f"{league}: status={meta.get('status')} eventi={n_ev} "
              f"crediti_ultima={meta.get('headers', {}).get('x-requests-last')}", flush=True)
        if not meta.get("ok"):
            exit_code = 1
            if meta.get("status") in STOP_STATUS:
                print(f"STOP: stato {meta.get('status')}, nessuna altra chiamata", flush=True)
                break
    summary["crediti_ultima_chiamata"] = {r["sport_key"]: r["headers"].get("x-requests-last")
                                         for r in summary["leghe"]}
    last = summary["leghe"][-1]["headers"] if summary["leghe"] else {}
    summary["x-requests-used_ultimo"] = last.get("x-requests-used")
    summary["x-requests-remaining_ultimo"] = last.get("x-requests-remaining")
    write_json(os.path.join(args.out, "_summary.json"), summary)
    print(f"riepilogo: {os.path.join(args.out, '_summary.json')}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
