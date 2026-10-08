#!/usr/bin/env python3
"""live_odds_probe.py — PROVA DI FATTIBILITA' di una fonte di quote 1X2 dal vivo (audit, SOLA LETTURA).

DOMANDA. Le 5 leghe del progetto (Serie A, Premier League, La Liga, Bundesliga,
Ligue 1) possono ricevere quote 1X2 dal vivo (pre-partita) da una fonte
sostenibile con il piano gratuito? E la fonte e' abbinabile ai nomi canonici
del progetto senza scrivere nuovo codice di normalizzazione?

Lo script tocca SOLO la rete in uscita (GET) e scrive file di prova. Non
modifica nulla in ``SoccerMath/``, non legge ne' scrive il Registro.

FONTI PROVATE
  1. The Odds API (api.the-odds-api.com, v4):
       - GET /v4/sports            (non consuma crediti: endpoint gratuito)
       - GET /v4/sports/{key}/odds  regions=eu,uk  markets=h2h  decimal
     Per ogni chiamata vengono registrati gli header di risposta
     ``x-requests-used``, ``x-requests-remaining``, ``x-requests-last``:
     sono l'EVIDENZA del costo in crediti, non una stima dalla documentazione.
  2. football-data.co.uk: GET https://www.football-data.co.uk/fixtures.csv
     (file delle partite in programma con quote; nessuna chiave).

SICUREZZA. La chiave API non viene MAI scritta su file ne' stampata: gli URL
vengono registrati con il parametro ``apiKey`` mascherato (``apiKey=***``).

USO (richiede rete; nella sandbox di sviluppo la rete e' bloccata, quindi lo
script gira da un workflow GitHub temporaneo, vedi il referto)::

    ODDS_API_KEY=... python audit/live_odds_probe.py --out <dir>

Output in ``<dir>``:
  * ``odds_api_sports.json``        elenco sport e chiavi delle 5 leghe;
  * ``odds_api_<lega>.json``        payload compattato (eventi + bookmaker + header);
  * ``raw_<lega>.json``             payload grezzo (solo artifact, non versionato);
  * ``football_data_fixtures.csv``  file CSV scaricato;
  * ``probe_summary.json``          riassunto di tutte le prove (nessun segreto).

Senza rete lo script termina con esito NON VERIFICABILE su tutte le voci e
scrive comunque il riassunto con l'errore di connessione.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
from datetime import datetime, timezone

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)

# 5 leghe del progetto -> sport key di The Odds API (documentate, vedi referto)
LEAGUES = [
    ("Serie A", "soccer_italy_serie_a"),
    ("Premier League", "soccer_epl"),
    ("La Liga", "soccer_spain_la_liga"),
    ("Bundesliga", "soccer_germany_bundesliga"),
    ("Ligue 1", "soccer_france_ligue_one"),
]

# cartella degli snapshot committati (usata dal workflow e riletta dagli script
# di abbinamento e dal referto: e' la prova che resta nel repository)
DATA_DIR = os.path.join(_AUDIT_DIR, "data", "live_odds_probe")

ODDS_HOST = "https://api.the-odds-api.com"
SPORTS_URL = f"{ODDS_HOST}/v4/sports/"
FD_FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
FD_NEW_FIXTURES_URL = "https://www.football-data.co.uk/new_league_fixtures.csv"
# Codici Div di football-data.co.uk per le 5 leghe del progetto
DIV_TARGET = {"E0": "Premier League", "I1": "Serie A", "D1": "Bundesliga",
              "SP1": "La Liga", "F1": "Ligue 1"}
REGIONS = "eu,uk"
MARKETS = "h2h"
CREDIT_HEADERS = ("x-requests-used", "x-requests-remaining", "x-requests-last")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mask(url: str, key: str) -> str:
    return url.replace(key, "***") if key else url


def _http():
    try:
        import requests  # dipendenza di produzione (SoccerMath/requirements.txt)
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(f"requests non disponibile: {exc}")
    return requests


def get_json(url, key, session, timeout=30):
    """GET JSON: ritorna (payload, headers_filtrati, errore, stato)."""
    out = {"url_masked": _mask(url, key), "fetched_at_utc": _now()}
    try:
        resp = session.get(url, timeout=timeout)
    except Exception as exc:
        out.update(ok=False, status=None, error=f"{type(exc).__name__}: {exc}")
        return None, out
    out["status"] = resp.status_code
    out["headers"] = {h: resp.headers.get(h) for h in CREDIT_HEADERS}
    out["ok"] = resp.status_code == 200
    if resp.status_code != 200:
        out["error"] = f"HTTP {resp.status_code}: {resp.text[:400]}"
        return None, out
    try:
        payload = resp.json()
    except Exception as exc:
        out["ok"] = False
        out["error"] = f"JSON non valido: {type(exc).__name__}: {exc}"
        return None, out
    return payload, out


def compact_events(payload, sport_key):
    """Payload compattato: eventi con quote h2h per bookmaker (niente campi vuoti)."""
    events = []
    for ev in payload or []:
        row = {
            "id": ev.get("id"),
            "sport_key": ev.get("sport_key", sport_key),
            "commence_time": ev.get("commence_time"),
            "home_team": ev.get("home_team"),
            "away_team": ev.get("away_team"),
            "bookmakers": [],
        }
        for bm in ev.get("bookmakers") or []:
            prices = {}
            for mk in bm.get("markets") or []:
                if mk.get("key") != "h2h":
                    continue
                for oc in mk.get("outcomes") or []:
                    name = oc.get("name")
                    if name == ev.get("home_team"):
                        prices["home"] = oc.get("price")
                    elif name == ev.get("away_team"):
                        prices["away"] = oc.get("price")
                    elif str(name).strip().lower() == "draw":
                        prices["draw"] = oc.get("price")
            row["bookmakers"].append({
                "key": bm.get("key"),
                "title": bm.get("title"),
                "last_update": bm.get("last_update"),
                "h2h": prices,
            })
        events.append(row)
    return events


def bookmaker_coverage(events):
    """Per ogni bookmaker: quanti eventi copre e ultimo aggiornamento (min/max)."""
    cov = {}
    for ev in events:
        for bm in ev["bookmakers"]:
            c = cov.setdefault(bm["key"], {"title": bm["title"], "n_events": 0,
                                           "last_update_min": None, "last_update_max": None,
                                           "h2h_completo": 0})
            c["n_events"] += 1
            if len([v for v in bm["h2h"].values() if v]) == 3:
                c["h2h_completo"] += 1
            lu = bm["last_update"]
            if lu:
                c["last_update_min"] = lu if c["last_update_min"] is None else min(c["last_update_min"], lu)
                c["last_update_max"] = lu if c["last_update_max"] is None else max(c["last_update_max"], lu)
    return cov


def probe_odds_api(session, key, out_dir, summary):
    """Chiamate reali a The Odds API: una per lega, piu' l'elenco sport (gratuito)."""
    sports_payload, sports_meta = get_json(SPORTS_URL + f"?apiKey={key}", key, session)
    sports_meta["endpoint"] = "/v4/sports (non consuma crediti secondo la documentazione)"
    summary["calls"].append({"label": "sports", **sports_meta})
    if sports_payload is None:
        summary["odds_api"]["sports_ok"] = False
        for league, skey in LEAGUES:
            summary["odds_api"]["leagues"][league] = {
                "sport_key": skey, "ok": False, "errore": "elenco sport non disponibile"}
        return
    with open(os.path.join(out_dir, "odds_api_sports.json"), "w", encoding="utf-8") as fh:
        json.dump(sports_payload, fh, ensure_ascii=False, indent=1)

    lookup = {s["key"]: s for s in sports_payload}
    for league, skey in LEAGUES:
        entry = {"sport_key": skey,
                 "presente_in_sports": skey in lookup,
                 "title": (lookup.get(skey) or {}).get("title"),
                 "active": (lookup.get(skey) or {}).get("active"),
                 "has_outrights": (lookup.get(skey) or {}).get("has_outrights")}
        url = (f"{ODDS_HOST}/v4/sports/{skey}/odds/?apiKey={key}&regions={REGIONS}"
               f"&markets={MARKETS}&oddsFormat=decimal&dateFormat=iso")
        payload, meta = get_json(url, key, session)
        meta["endpoint"] = f"/v4/sports/{skey}/odds"
        meta["league"] = league
        summary["calls"].append({"label": f"odds:{skey}", **meta})
        entry["chiamata"] = {k: meta[k] for k in ("url_masked", "status", "ok", "headers",
                                                  "fetched_at_utc", "error") if k in meta}
        if payload is None:
            entry["ok"] = False
            summary["odds_api"]["leagues"][league] = entry
            continue
        with open(os.path.join(out_dir, f"raw_{skey}.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        events = compact_events(payload, skey)
        cov = bookmaker_coverage(events)
        times = sorted(e["commence_time"] for e in events if e.get("commence_time"))
        compact = {
            "sport_key": skey,
            "lega_progetto": league,
            "richiesta": {"regions": REGIONS, "markets": MARKETS, "oddsFormat": "decimal",
                          "url_masked": meta["url_masked"]},
            "http": {"status": meta["status"],
                     "crediti": {h: meta["headers"].get(h) for h in CREDIT_HEADERS}},
            "scaricato_il": meta["fetched_at_utc"],
            "n_eventi": len(events),
            "prima_partita_utc": times[0] if times else None,
            "ultima_partita_utc": times[-1] if times else None,
            "bookmakers": cov,
            "events": events,
        }
        with open(os.path.join(out_dir, f"odds_api_{skey}.json"), "w", encoding="utf-8") as fh:
            json.dump(compact, fh, ensure_ascii=False, indent=1)
        entry["ok"] = True
        entry["n_eventi"] = len(events)
        entry["n_bookmaker"] = len(cov)
        entry["bookmakers"] = sorted(cov)
        entry["bet365_presente"] = any("bet365" in k.lower() for k in cov)
        entry["pinnacle_presente"] = any("pinnacle" in k.lower() for k in cov)
        entry["crediti_header"] = {h: meta["headers"].get(h) for h in CREDIT_HEADERS}
        entry["prima_partita_utc"] = times[0] if times else None
        entry["ultima_partita_utc"] = times[-1] if times else None
        entry["aggiornamento_libro_min"] = min(
            (v["last_update_min"] for v in cov.values() if v["last_update_min"]), default=None)
        entry["aggiornamento_libro_max"] = max(
            (v["last_update_max"] for v in cov.values() if v["last_update_max"]), default=None)
        summary["odds_api"]["leagues"][league] = entry
        time.sleep(1.0)  # nessuna raffica: la prova non deve sembrare un abuso
    summary["odds_api"]["sports_ok"] = True


def probe_bet365_check(session, key, out_dir, summary):
    """CONTROLLO: si chiede ESPLICITAMENTE bet365 (parametro ``bookmakers``).

    Serve a distinguere 'bet365 non e' nel piano' da 'bet365 non ha ancora
    pubblicato queste partite'. Costa 1 credito (fino a 10 bookmaker = 1 regione).
    """
    skey = "soccer_italy_serie_a"
    url = (f"{ODDS_HOST}/v4/sports/{skey}/odds/?apiKey={key}&bookmakers=bet365"
           f"&markets={MARKETS}&oddsFormat=decimal&dateFormat=iso")
    payload, meta = get_json(url, key, session)
    entry = {"endpoint": f"/v4/sports/{skey}/odds (bookmakers=bet365)",
             "url_masked": meta["url_masked"], "status": meta.get("status"),
             "crediti": meta.get("headers"), "ok": meta.get("ok", False),
             "errore": meta.get("error")}
    if payload is not None:
        keys = sorted({bm.get("key") for ev in payload or [] for bm in ev.get("bookmakers") or []})
        entry["n_eventi"] = len(payload or [])
        entry["bookmakers_restituiti"] = keys
        entry["bet365_presente"] = any("365" in (k or "").lower() for k in keys)
    summary["controllo_bet365"] = entry


def probe_region_cost(session, key, out_dir, summary):
    """CONTROLLO BUDGET: quanto costa la stessa chiamata con UNA sola regione.

    La documentazione dice ``costo = mercati x regioni``; qui si misura una
    chiamata con ``regions=eu`` (1 credito atteso) per verificare che il
    bookmaker scelto (Pinnacle) sia comunque restituito.
    """
    skey = "soccer_italy_serie_a"
    url = (f"{ODDS_HOST}/v4/sports/{skey}/odds/?apiKey={key}&regions=eu"
           f"&markets={MARKETS}&oddsFormat=decimal&dateFormat=iso")
    payload, meta = get_json(url, key, session)
    entry = {"endpoint": f"/v4/sports/{skey}/odds (regions=eu)",
             "url_masked": meta["url_masked"], "status": meta.get("status"),
             "crediti": meta.get("headers"), "ok": meta.get("ok", False),
             "errore": meta.get("error")}
    if payload is not None:
        keys = sorted({bm.get("key") for ev in payload or [] for bm in ev.get("bookmakers") or []})
        entry["n_eventi"] = len(payload or [])
        entry["n_bookmaker"] = len(keys)
        entry["pinnacle_presente"] = "pinnacle" in keys
        entry["bookmakers"] = keys
    summary["controllo_una_regione"] = entry


def probe_football_data(session, out_dir, summary):
    """File delle partite in programma di football-data.co.uk (nessuna chiave)."""
    for label, url, fname in (("fixtures_main", FD_FIXTURES_URL, "football_data_fixtures.csv"),
                              ("fixtures_extra", FD_NEW_FIXTURES_URL, "football_data_new_league_fixtures.csv")):
        entry = {"url": url, "scaricato_il": _now(), "richiede_chiave": False}
        try:
            resp = session.get(url, timeout=30)
        except Exception as exc:
            entry.update(ok=False, errore=f"{type(exc).__name__}: {exc}")
            summary["football_data"][label] = entry
            continue
        entry["status"] = resp.status_code
        entry["headers"] = {k: resp.headers.get(k) for k in
                            ("last-modified", "content-length", "content-type", "date")}
        if resp.status_code != 200:
            entry.update(ok=False, errore=f"HTTP {resp.status_code}")
            summary["football_data"][label] = entry
            continue
        # content-type 'text/csv' senza charset: requests usa ISO-8859-1 e il BOM
        # diventa 'ï»¿'. Si decodifica esplicitamente come UTF-8 con BOM.
        text = resp.content.decode("utf-8-sig", errors="replace")
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as fh:
            fh.write(text)
        reader = csv.reader(io.StringIO(text))
        rows = [r for r in reader if any(c.strip() for c in r)]
        header = rows[0] if rows else []
        body = rows[1:]
        entry["ok"] = True
        entry["n_colonne"] = len(header)
        entry["colonne"] = header
        entry["n_righe"] = len(body)
        entry["prime_3_righe"] = body[:3]
        if header and str(header[0]).strip().lower().startswith("div"):
            counts = {}
            for r in body:
                counts[str(r[0]).strip()] = counts.get(str(r[0]).strip(), 0) + 1
            entry["righe_per_div"] = counts
            entry["righe_5_leghe"] = {d: counts.get(d, 0) for d in DIV_TARGET}
            entry["n_righe_5_lelhe"] = sum(counts.get(d, 0) for d in DIV_TARGET)
            entry["colonne_quote_1x2"] = [c for c in header if c.endswith(("H", "D", "A"))
                                          and len(c) > 2]
        summary["football_data"][label] = entry


def main(argv=None):
    ap = argparse.ArgumentParser(description="Prova di fattibilita' quote 1X2 dal vivo")
    ap.add_argument("--out", default=os.path.join(_AUDIT_DIR, "output", "live_odds_probe"),
                    help="cartella di output (default: audit/output/live_odds_probe)")
    ap.add_argument("--skip-odds-api", action="store_true", help="non chiamare The Odds API")
    ap.add_argument("--skip-football-data", action="store_true", help="non scaricare fixtures.csv")
    ap.add_argument("--skip-bet365-check", action="store_true",
                    help="non fare la chiamata di controllo bookmakers=bet365 (1 credito)")
    args = ap.parse_args(argv)

    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)
    key = os.environ.get("ODDS_API_KEY", "").strip()

    summary = {
        "generato_il": _now(),
        "chiave_presente_nell_ambiente": bool(key),
        "chiave_presente_nel_repository": os.environ.get("SECRET_PRESENT", "n/d"),
        "host": ODDS_HOST,
        "regioni_richieste": REGIONS,
        "mercato_richiesto": MARKETS,
        "leggende": {
            "x-requests-used": "crediti usati dall'ultimo reset della quota",
            "x-requests-remaining": "crediti rimasti prima del reset",
            "x-requests-last": "costo in crediti dell'ultima chiamata",
        },
        "calls": [],
        "odds_api": {"sports_ok": False, "leagues": {}},
        "football_data": {},
        "controllo_bet365": None,
        "controllo_una_regione": None,
    }

    session = _http()
    if not args.skip_odds_api:
        if key:
            probe_odds_api(session, key, out_dir, summary)
            if not args.skip_bet365_check:
                probe_bet365_check(session, key, out_dir, summary)
                probe_region_cost(session, key, out_dir, summary)
        else:
            summary["odds_api"]["errore"] = "ODDS_API_KEY assente nell'ambiente"
            for league, skey in LEAGUES:
                summary["odds_api"]["leagues"][league] = {
                    "sport_key": skey, "ok": False, "errore": "chiave assente"}
    if not args.skip_football_data:
        probe_football_data(session, out_dir, summary)

    path = os.path.join(out_dir, "probe_summary.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
    ok = [k for k, v in summary["odds_api"]["leagues"].items() if v.get("ok")]
    print(f"riassunto: {path}")
    print(f"leghe con quote The Odds API: {len(ok)}/5 -> {ok}")
    for label, entry in summary["football_data"].items():
        print(f"football-data {label}: {'ok' if entry.get('ok') else 'NON OK'} "
              f"righe={entry.get('n_righe')} righe_5_leghe={entry.get('n_righe_5_lelhe')} "
              f"last-modified={entry.get('headers', {}).get('last-modified')}")
    if summary["controllo_bet365"]:
        print("controllo bet365:", summary["controllo_bet365"])
        print("controllo una regione:", {k: v for k, v in (summary["controllo_una_regione"] or {}).items()
                                        if k in ("status", "crediti", "n_eventi", "n_bookmaker",
                                                 "pinnacle_presente")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
