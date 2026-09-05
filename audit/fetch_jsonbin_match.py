#!/usr/bin/env python3
"""GET sola lettura di una riga del registro JSONBin.

Vincoli:
  * nessuna PUT, nessuno apply, nessuno push-remote;
  * se le credenziali mancano, esce 0 con un JSON di 'missing' (non fallisce CI);
  * stampa TUTTI i campi delle entry che matchano, incluso salvato_il esatto.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
_SOCCER = os.path.join(_REPO_ROOT, "SoccerMath")
if _SOCCER not in sys.path:
    sys.path.insert(0, _SOCCER)

from config import JSONBIN_API_KEY, JSONBIN_BIN_ID  # noqa: E402
from prediction_registry import (  # noqa: E402
    classify_entry,
    entry_era_by_time,
    parse_datetime,
)

JSONBIN_READ_URL = "https://api.jsonbin.io/v3/b/{bin_id}/latest"


def _json_safe(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    if isinstance(obj, float):
        return obj if obj == obj else None
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


def fetch_latest(api_key: Optional[str] = None, bin_id: Optional[str] = None,
                 timeout: int = 20) -> Dict[str, Any]:
    """GET /latest. Mai PUT."""
    key = api_key if api_key is not None else JSONBIN_API_KEY
    bid = bin_id if bin_id is not None else JSONBIN_BIN_ID
    out: Dict[str, Any] = {
        "attempted": bool(key and bid),
        "ok": False,
        "http_status": None,
        "reason": None,
        "n_records": 0,
        "records": None,
        "bin_id_present": bool(bid),
        "api_key_present": bool(key),
        "method": "GET",
        "url": JSONBIN_READ_URL.format(bin_id=bid or "<missing>"),
        "put_called": False,
    }
    if not key or not bid:
        out["reason"] = (
            "JSONBIN_API_KEY / JSONBIN_BIN_ID assenti "
            "(env, SoccerMath/.env o st.secrets). Nessuna GET eseguita."
        )
        return out
    try:
        import requests
    except ImportError as exc:
        out["reason"] = f"modulo requests assente: {exc}"
        return out
    url = JSONBIN_READ_URL.format(bin_id=bid)
    try:
        resp = requests.get(url, headers={"X-Master-Key": key}, timeout=timeout)
    except Exception as exc:
        out["reason"] = f"errore di rete: {type(exc).__name__}: {exc}"
        return out
    out["http_status"] = resp.status_code
    if resp.status_code != 200:
        out["reason"] = f"HTTP {resp.status_code} {resp.text[:200]}"
        return out
    rec = resp.json().get("record", {})
    if isinstance(rec, dict) and isinstance(rec.get("data"), list):
        records = rec["data"]
    elif isinstance(rec, list):
        records = rec
    else:
        out["reason"] = "formato JSONBin non riconosciuto"
        return out
    out["ok"] = True
    out["n_records"] = len(records)
    out["records"] = records
    return out


def _haystack(entry: Dict[str, Any]) -> str:
    parts = [
        str(entry.get("home") or ""),
        str(entry.get("away") or ""),
        str(entry.get("pronostico_sicuro") or ""),
        str(entry.get("match_id") or ""),
        str(entry.get("campionato") or ""),
    ]
    return " ".join(parts).lower()


def find_entries(records: List[Dict[str, Any]], needles: List[str],
                 match_id: Optional[Any] = None,
                 prob: Optional[float] = None) -> List[Dict[str, Any]]:
    hits = []
    needles_l = [n.lower() for n in needles if n]
    for entry in records or []:
        if not isinstance(entry, dict):
            continue
        if match_id is not None and str(entry.get("match_id")) != str(match_id):
            continue
        hay = _haystack(entry)
        if needles_l and not all(n in hay for n in needles_l):
            continue
        if prob is not None:
            try:
                p = float(entry.get("prob_sicuro"))
            except (TypeError, ValueError):
                continue
            if abs(p - prob) > 0.05:
                continue
        hits.append(entry)
    return hits


def annotate(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Tutti i campi originali + classificazione (nessuna mutazione persistita)."""
    info = classify_entry(entry)
    dt = parse_datetime(entry.get("salvato_il"))
    return {
        "fields": dict(entry),
        "field_names": sorted(entry.keys()),
        "salvato_il_raw": entry.get("salvato_il"),
        "salvato_il_utc": dt.astimezone(timezone.utc).isoformat() if dt else None,
        "classification": info,
        "era_by_time": entry_era_by_time(entry),
    }


def report_schalke_bayern(fetch: Dict[str, Any]) -> Dict[str, Any]:
    records = fetch.get("records") or []
    by_names = find_entries(records, ["schalke", "bayern"])
    by_prob = find_entries(records, ["schalke", "bayern"], prob=92.1)
    by_prob_only = find_entries(records, [], prob=92.1)
    return {
        "ok": fetch.get("ok"),
        "reason": fetch.get("reason"),
        "http_status": fetch.get("http_status"),
        "n_records": fetch.get("n_records"),
        "put_called": False,
        "method": "GET",
        "n_schalke_bayern": len(by_names),
        "n_schalke_bayern_92_1": len(by_prob),
        "n_any_92_1": len(by_prob_only),
        "schalke_bayern": [annotate(e) for e in by_names],
        "any_92_1_preview": [
            {
                "home": e.get("home"),
                "away": e.get("away"),
                "prob_sicuro": e.get("prob_sicuro"),
                "mercato_standard": e.get("mercato_standard"),
                "salvato_il": e.get("salvato_il"),
                "model_version": e.get("model_version"),
                "match_id": e.get("match_id"),
                "tipo": e.get("tipo"),
            }
            for e in by_prob_only[:20]
        ],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="GET JSONBin (sola lettura)")
    parser.add_argument("--needle", action="append", default=[],
                        help="Sottostringa da cercare in home/away/pronostico (ripetibile)")
    parser.add_argument("--match-id", default=None)
    parser.add_argument("--prob", type=float, default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--schalke-bayern", action="store_true",
                        help="Report dedicato Schalke–Bayern + 92.1")
    args = parser.parse_args(argv)

    fetch = fetch_latest()
    payload: Dict[str, Any]
    if args.schalke_bayern or (not args.needle and args.match_id is None and args.prob is None):
        payload = report_schalke_bayern(fetch)
        payload["credentials"] = {
            "api_key_present": fetch.get("api_key_present"),
            "bin_id_present": fetch.get("bin_id_present"),
        }
    else:
        records = fetch.get("records") or []
        hits = find_entries(records, args.needle, match_id=args.match_id, prob=args.prob)
        payload = {
            "ok": fetch.get("ok"),
            "reason": fetch.get("reason"),
            "n_records": fetch.get("n_records"),
            "n_hits": len(hits),
            "hits": [annotate(e) for e in hits],
            "put_called": False,
        }

    payload["fetched_at_utc"] = datetime.now(timezone.utc).isoformat()
    payload = _json_safe(payload)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"output: {args.output}")
    else:
        sys.stdout.write(text)
    if fetch.get("ok"):
        print(f"GET ok, {fetch.get('n_records')} record, put_called=False")
    else:
        print(f"GET non eseguita/fallita: {fetch.get('reason')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
