"""Fixture offline del 16/10: unisce per id h2h pinnato e totals grezzi.

Nessuna rete; produce anche risposte miste in forma API per il dry-run CI.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

SNAPSHOT = Path(__file__).parent / "data/totals_probe/2026-10-16_1320"


def payload_snapshot():
    payload = json.loads((SNAPSHOT / "_live_odds_pinnato.json").read_text())
    payload["schema"] = "soccermath_live_odds_v2"
    for lega, blocco in payload["leghe"].items():
        raw = json.loads((SNAPSHOT / (blocco["sport_key"] + ".json")).read_text())
        events = {e["id"]: e for e in raw["body"]}
        for ev in blocco["eventi"]:
            books = {b["key"]: b for b in ev["libri"]}
            for book in events.get(ev["id"], {}).get("bookmakers", []):
                b = books.setdefault(book["key"], {"key": book["key"], "h2h": {}})
                totals = b.setdefault("totals", {})
                for m in book.get("markets", []):
                    if m["key"] == "totals":
                        for o in m["outcomes"]:
                            totals.setdefault(str(float(o["point"])), {})[o["name"]] = o["price"]
            ev["libri"] = list(books.values())
    return payload


def write_raw(out, senza_bookmakers=False):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    payload = payload_snapshot()
    for lega, block in payload["leghe"].items():
        events = []
        for ev in block["eventi"]:
            raw = {k: copy.deepcopy(v) for k, v in ev.items() if k != "libri"}
            raw["bookmakers"] = []
            for b in ([] if senza_bookmakers else ev["libri"]):
                outcomes = [{"name": name, "price": b["h2h"][key]}
                            for key, name in (("home", ev["home_team"]), ("draw", "Draw"),
                                              ("away", ev["away_team"])) if b.get("h2h", {}).get(key)]
                totals = [{"name": side, "price": q, "point": float(line)}
                          for line, quotes in b.get("totals", {}).items() for side, q in quotes.items()]
                raw["bookmakers"].append({"key": b["key"], "markets": [
                    {"key": "h2h", "outcomes": outcomes}, {"key": "totals", "outcomes": totals}]})
            events.append(raw)
        wrapper = {"lega": lega, "sport_key": block["sport_key"], "events": events,
                   "scaricato_il": payload["generato_il"], "ok": True, "status": 200}
        (out / ("odds_api_" + block["sport_key"] + ".json")).write_text(json.dumps(wrapper))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--senza-bookmakers", action="store_true")
    args = parser.parse_args()
    write_raw(args.out, args.senza_bookmakers)
