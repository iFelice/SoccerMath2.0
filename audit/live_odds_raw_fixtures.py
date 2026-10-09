#!/usr/bin/env python3
"""live_odds_raw_fixtures.py — risposte GREZZE di The Odds API per le prove offline.

A COSA SERVE
------------
Gli snapshot committati in ``audit/data/live_odds_probe/odds_api_<sport_key>.json``
NON sono il corpo della risposta: sono la forma COMPATTATA prodotta dalla sonda
(``audit/live_odds_probe.compact_events``), con le quote gia' ridotte a
``{"h2h": {"home":..., "draw":..., "away":...}}``.

E' esattamente la differenza che ha nascosto il guasto del 2026-10-09:
``update_live_odds.py`` leggeva solo la forma compattata, il dry-run della PR
girava sulla forma compattata e passava, mentre la rete manda la forma
ANNIDATA (``bookmakers[].markets[].outcomes[]``) e ogni bookmaker veniva
scartato in silenzio.

Questo modulo RICOSTRUISCE il corpo grezzo a partire dagli snapshot
committati, invertendo ``compact_events``::

    compact_events:  outcomes[name == home_team].price  ->  h2h["home"]
                     outcomes[name == away_team].price  ->  h2h["away"]
                     outcomes[name == "Draw"].price     ->  h2h["draw"]

    questo modulo:   h2h["home"] -> {"name": home_team, "price": ...}
                     h2h["away"] -> {"name": away_team, "price": ...}
                     h2h["draw"] -> {"name": "Draw",    "price": ...}

COSA E' REALE E COSA NO (dichiarato, non nascosto)
---------------------------------------------------
REALI, presi dallo snapshot della sonda del 2026-10-08: id, orari di inizio,
nomi delle squadre, chiavi e titoli dei bookmaker, ``last_update``, QUOTE.
RICOSTRUITI: l'annidamento ``markets``/``outcomes``, il nome dell'esito di
pareggio (``"Draw"``, la stringa che la sonda cercava) e l'ordine degli esiti.
Un prezzo assente nello snapshot (bookmaker senza quel lato) resta assente:
l'esito non viene inventato.

I file prodotti NON sono committati: si rigenerano in un attimo da dati
committati (``python audit/live_odds_raw_fixtures.py --out <dir>``) e li usano
i test e il dry-run del workflow.

Uso::

    python audit/live_odds_raw_fixtures.py --out /tmp/odds_grezze
    python audit/live_odds_raw_fixtures.py --out /tmp/odds_vuote --senza-bookmakers
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional, Sequence

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)

# Snapshot committati della sonda (PR #50).
DATA_DIR = os.path.join(_AUDIT_DIR, "data", "live_odds_probe")

# Le 5 leghe del progetto, nello stesso ordine di ``update_live_odds.LEGA_SPORT_KEY``.
SPORT_KEYS: Sequence[str] = (
    "soccer_italy_serie_a",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
)

NOME_PAREGGIO = "Draw"


def percorso_snapshot(sport_key: str, data_dir: str = DATA_DIR) -> str:
    return os.path.join(data_dir, f"odds_api_{sport_key}.json")


def carica_snapshot(sport_key: str, data_dir: str = DATA_DIR) -> Dict[str, Any]:
    with open(percorso_snapshot(sport_key, data_dir), encoding="utf-8") as fh:
        return json.load(fh)


def bookmaker_grezzo(libro: Dict[str, Any], home_team: Any, away_team: Any) -> Dict[str, Any]:
    """Un bookmaker compattato -> la forma annidata della risposta di rete."""
    h2h = libro.get("h2h") or {}
    outcomes: List[Dict[str, Any]] = []
    # Ordine come lo manda The Odds API: casa, trasferta, pareggio.
    for nome, chiave in ((home_team, "home"), (away_team, "away"), (NOME_PAREGGIO, "draw")):
        prezzo = h2h.get(chiave)
        if prezzo is None:          # lato non quotato: nessun esito inventato
            continue
        outcomes.append({"name": nome, "price": prezzo})
    return {
        "key": libro.get("key"),
        "title": libro.get("title"),
        "last_update": libro.get("last_update"),
        "markets": [{"key": "h2h",
                     "last_update": libro.get("last_update"),
                     "outcomes": outcomes}],
    }


def evento_grezzo(evento: Dict[str, Any], sport_key: str,
                  senza_bookmakers: bool = False) -> Dict[str, Any]:
    home = evento.get("home_team")
    away = evento.get("away_team")
    return {
        "id": evento.get("id"),
        "sport_key": evento.get("sport_key", sport_key),
        "sport_title": evento.get("sport_title"),
        "commence_time": evento.get("commence_time"),
        "home_team": home,
        "away_team": away,
        "bookmakers": ([] if senza_bookmakers
                       else [bookmaker_grezzo(b, home, away)
                             for b in (evento.get("bookmakers") or [])]),
    }


def risposta_grezza(snapshot: Dict[str, Any], sport_key: str,
                    senza_bookmakers: bool = False) -> List[Dict[str, Any]]:
    """Il CORPO della risposta ``/v4/sports/<key>/odds``: una lista di eventi."""
    return [evento_grezzo(e, sport_key, senza_bookmakers)
            for e in (snapshot.get("events") or []) if isinstance(e, dict)]


def scrivi_fixture(out_dir: str, *, senza_bookmakers: bool = False,
                   sport_keys: Optional[Sequence[str]] = None,
                   data_dir: str = DATA_DIR) -> List[str]:
    """Scrive ``odds_api_<sport_key>.json`` (corpo grezzo) in ``out_dir``.

    Ritorna l'elenco dei file scritti. Il nome dei file e' quello che
    ``update_live_odds.scarica_lega_fixture`` si aspetta, cosi' la cartella si
    passa tale e quale a ``--fixture``.
    """
    os.makedirs(out_dir, exist_ok=True)
    scritti: List[str] = []
    for sport_key in (sport_keys or SPORT_KEYS):
        snapshot = carica_snapshot(sport_key, data_dir)
        corpo = risposta_grezza(snapshot, sport_key, senza_bookmakers)
        path = os.path.join(out_dir, f"odds_api_{sport_key}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(corpo, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        scritti.append(path)
    return scritti


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="cartella di destinazione")
    ap.add_argument("--senza-bookmakers", action="store_true",
                    help="stessi eventi, 'bookmakers': [] su tutti (prova del guasto)")
    args = ap.parse_args(argv)
    scritti = scrivi_fixture(args.out, senza_bookmakers=args.senza_bookmakers)
    for path in scritti:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
