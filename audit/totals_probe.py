#!/usr/bin/env python3
"""totals_probe.py — sonda The Odds API, mercato TOTALS (Over/Under), audit.

Scarica, per le 5 leghe del progetto, GET /v4/sports/{key}/odds con
``markets=totals``, ``regions=eu``: UNA chiamata per lega. Ogni run riserva una
nuova sottocartella UTC ``audit/data/totals_probe/<AAAA-MM-GG_HHMM>/`` e salva
lì le risposte GREZZE (corpo JSON invariato + intestazioni dei crediti) e il
riepilogo. Se due run cadono nello stesso minuto, aggiunge un suffisso numerico
per evitare qualsiasi sovrascrittura.

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

Uso: ``ODDS_API_KEY=... python audit/totals_probe.py [--out-root audit/data/totals_probe]``
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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _now(when: datetime | None = None) -> str:
    return (when or _utc_now()).strftime("%Y-%m-%dT%H:%M:%SZ")


def reserve_run_dir(out_root: str, when: datetime | None = None) -> str:
    """Crea atomicamente una cartella nuova, senza mai riusare uno snapshot."""
    when = when or _utc_now()
    os.makedirs(out_root, exist_ok=True)
    base = when.astimezone(timezone.utc).strftime("%Y-%m-%d_%H%M")
    attempt = 0
    while True:
        name = base if attempt == 0 else f"{base}_{attempt + 1:02d}"
        candidate = os.path.join(out_root, name)
        try:
            os.mkdir(candidate)
            return candidate
        except FileExistsError:
            attempt += 1


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
    ap.add_argument("--out-root", "--out", dest="out_root", default=DEFAULT_OUT,
                    help="radice in cui creare una nuova cartella snapshot UTC")
    args = ap.parse_args(argv)

    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key:
        print("ERROR: ODDS_API_KEY assente nell'ambiente", file=sys.stderr)
        return 3

    run_started = _utc_now()
    run_dir = reserve_run_dir(args.out_root, run_started)
    session = _http().Session()
    summary = {"generato_il": _now(run_started), "snapshot_id": os.path.basename(run_dir),
               "mercato": MARKETS, "regioni": REGIONS,
               "chiamate_previste": len(LEAGUES), "leghe": []}
    exit_code = 0
    for league, sport in LEAGUES:
        url = build_url(sport, key)
        payload, meta = get_json(url, key, session)
        # payload None (errore) -> busta con body null: il file documenta l'errore
        env = envelope(sport, league, meta, payload)
        write_json(os.path.join(run_dir, f"{sport}.json"), env)
        n_ev = len(payload) if isinstance(payload, list) else None
        summary["leghe"].append({
            "lega": league, "sport_key": sport, "ok": bool(meta.get("ok")),
            "status": meta.get("status"), "eventi": n_ev,
            # serve a riconoscere l'ultima chiamata in ordine di TEMPO (vedi sotto)
            "fetched_at_utc": meta.get("fetched_at_utc", _now()),
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
    # STATO FINALE = ultima chiamata in ORDINE DI TEMPO, non ultima lega del ciclo.
    # Chiave (fetched_at_utc, x-requests-used): il contatore rompe i pareggi
    # quando i timestamp hanno la stessa risoluzione di un secondo.
    def _chiave(r):
        headers = r.get("headers") or {}
        try:
            usati = float(headers.get("x-requests-used"))
        except (TypeError, ValueError):
            usati = -1.0
        ts = r.get("fetched_at_utc")
        return (ts is None, "" if ts is None else str(ts), usati)

    ultima = max(summary["leghe"], key=_chiave) if summary["leghe"] else {}
    uh = ultima.get("headers") or {}
    summary["ultima_chiamata"] = {"sport_key": ultima.get("sport_key"),
                                  "fetched_at_utc": ultima.get("fetched_at_utc")}
    summary["x-requests-used_ultimo"] = uh.get("x-requests-used")
    summary["x-requests-remaining_ultimo"] = uh.get("x-requests-remaining")
    write_json(os.path.join(run_dir, "_summary.json"), summary)
    print(f"riepilogo: {os.path.join(run_dir, '_summary.json')}", flush=True)
    print(f"SNAPSHOT_DIR={run_dir}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
