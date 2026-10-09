#!/usr/bin/env python3
"""
update_live_odds.py — scarica le quote 1X2 dal vivo e scrive ``live_odds.json``.

CHI LO ESEGUE
-------------
SOLO il workflow ``.github/workflows/live_odds.yml`` (cron ``17 8 * * *`` UTC
piu' avvio manuale) o un operatore a mano. L'app non chiama MAI The Odds API:
legge il file scritto qui (``market_odds.carica_quote_live``).

COSTO
-----
Una chiamata per lega, ``regions=eu``, ``markets=h2h``: 1 credito a chiamata
(misurato in PR #50, ``audit/results/live_odds_feasibility.md`` §4), quindi
5 crediti per giro. Il piano gratuito ne da' 500 al mese: il giro quotidiano
alle 08:17 UTC sta nel budget (mese peggiore ~127 crediti con due regioni;
con una sola regione ~54).

SICUREZZA DELLA CHIAVE
----------------------
``ODDS_API_KEY`` sta SOLO nel secret GitHub. Questo script:
  * la legge dall'ambiente e non la stampa MAI;
  * maschera ogni URL prima di scriverlo nel file o nei log (``url_masked``);
  * passa ogni messaggio di errore da ``redigi``, che sostituisce la chiave con
    ``***`` anche se arriva dentro un'eccezione o un corpo di risposta;
  * prima di scrivere verifica che la chiave NON compaia nel JSON prodotto, e
    se compare NON scrive (exit 3).

ROBUSTEZZA (mai sovrascrivere con dati vuoti)
---------------------------------------------
  * se NESSUNA lega torna eventi il file precedente resta intatto (exit 1);
  * se la quota crediti e' esaurita (HTTP 429 / 402, o corpo che parla di
    quota) il file precedente resta intatto (exit 2);
  * se SOLO ALCUNE leghe tornano eventi si scrive, con gli errori elencati nel
    file e nel log, e con ``leghe_mancanti_rispetto_a_prima``: perdere una lega
    non deve far perdere le altre quattro;
  * la scrittura e' atomica (tmp + ``os.replace``), come gli altri writer del
    progetto.

Uso
---
    python update_live_odds.py                 # chiamata reale, scrive
    python update_live_odds.py --dry-run       # chiamata reale, NON scrive
    python update_live_odds.py --fixture DIR   # risposte simulate da DIR (0 crediti)
    python update_live_odds.py --out PATH      # percorso di destinazione
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from market_odds import SCHEMA_LIVE_ODDS  # noqa: E402  (foglia: nessuna dipendenza da streamlit)

LOG = logging.getLogger("update_live_odds")

HOST = "https://api.the-odds-api.com"
NOME_ENV_CHIAVE = "ODDS_API_KEY"
REGIONI = "eu"            # 1 credito a chiamata (PR #50 §4)
MERCATO = "h2h"
FORMATO_QUOTE = "decimal"
QUOTA_MENSILE = 500

# Le 5 leghe del progetto -> sport key di The Odds API (verificate in PR #50 §2).
LEGA_SPORT_KEY: "OrderedDict[str, str]" = OrderedDict([
    ("Serie A", "soccer_italy_serie_a"),
    ("Premier League", "soccer_epl"),
    ("La Liga", "soccer_spain_la_liga"),
    ("Bundesliga", "soccer_germany_bundesliga"),
    ("Ligue 1", "soccer_france_ligue_one"),
])

# Codici HTTP che significano "quota finita / chiave non accettata": non si
# scrive nulla, il file precedente resta.
HTTP_QUOTA = (402, 429)
HTTP_CHIAVE = (401, 403)

ESITO_OK = 0
ESITO_NULLA_SCRITTO = 1
ESITO_QUOTA_ESAURITA = 2
ESITO_CHIAVE = 3


# ---------------------------------------------------------------------------
# Chiave: mai stampata, mai scritta
# ---------------------------------------------------------------------------
def redigi(testo: Any, chiave: Optional[str]) -> str:
    """Sostituisce la chiave con ``***`` in qualunque testo (anche None)."""
    out = "" if testo is None else str(testo)
    if chiave:
        out = out.replace(chiave, "***")
    return out


def url_masked(sport_key: str, chiave_presente: bool) -> str:
    """URL della chiamata SENZA la chiave (quella che finisce nel file)."""
    qs = (f"apiKey={'***' if chiave_presente else '(assente)'}&regions={REGIONI}"
          f"&markets={MERCATO}&oddsFormat={FORMATO_QUOTE}&dateFormat=iso")
    return f"{HOST}/v4/sports/{sport_key}/odds/?{qs}"


def crediti_da_header(headers: Dict[str, str]) -> Dict[str, Optional[int]]:
    """Crediti dagli header di risposta (documentazione The Odds API).

    ``x-requests-used`` crediti usati dall'ultimo reset, ``x-requests-remaining``
    residui PRIMA del reset, ``x-requests-last`` costo dell'ultima chiamata.
    Header assente o non numerico -> None (non 0: un numero inventato sarebbe
    peggio di un numero mancante).
    """
    def num(nome: str) -> Optional[int]:
        v = (headers or {}).get(nome)
        if v is None:
            return None
        try:
            return int(str(v).strip())
        except ValueError:
            return None
    return {"usati_dall_ultimo_reset": num("x-requests-used"),
            "residui": num("x-requests-remaining"),
            "costo_ultima_chiamata": num("x-requests-last")}


# ---------------------------------------------------------------------------
# Normalizzazione della risposta (stessa forma per rete e fixture)
# ---------------------------------------------------------------------------
def libri_dell_evento(evento: Dict[str, Any]) -> List[Dict[str, Any]]:
    """I bookmaker di un evento, con SOLO i campi che servono (quote grezze).

    ``h2h`` resta grezzo (home/draw/away come li da' la fonte): nessuna
    rielaborazione, il de-vig lo fa ``market_odds.probabilita_mercato``.
    Accetta anche la forma piatta degli snapshot di prova.
    """
    out: List[Dict[str, Any]] = []
    for libro in evento.get("bookmakers") or []:
        if not isinstance(libro, dict):
            continue
        h2h = libro.get("h2h")
        if not isinstance(h2h, dict):
            continue
        out.append({
            "key": libro.get("key"),
            "title": libro.get("title"),
            "last_update": libro.get("last_update"),
            "h2h": {"home": h2h.get("home"), "draw": h2h.get("draw"), "away": h2h.get("away")},
        })
    return out


def evento_norm(evento: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": evento.get("id"),
        "commence_time": evento.get("commence_time"),
        "home_team": evento.get("home_team"),
        "away_team": evento.get("away_team"),
        "libri": libri_dell_evento(evento),
    }


def payload_fixture(percorso: str) -> Optional[Dict[str, Any]]:
    """Legge una risposta simulata (formato degli snapshot ``audit/data/live_odds_probe``)."""
    try:
        with open(percorso, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        LOG.error("Fixture %s non leggibile: %s: %s", percorso, type(e).__name__, e)
        return None


# ---------------------------------------------------------------------------
# Una lega
# ---------------------------------------------------------------------------
def scarica_lega_rete(sport_key: str, chiave: str, timeout: int = 30) -> Dict[str, Any]:
    """UNA chiamata /odds. Ritorna un blocco lega (mai solleva eccezioni).

    La chiave viaggia nei PARAMS di ``requests`` (mai nell'URL scritto) e ogni
    testo che esce da qui passa da ``redigi``.
    """
    import requests  # import tardivo: il percorso --fixture non richiede rete

    params = {"apiKey": chiave, "regions": REGIONI, "markets": MERCATO,
              "oddsFormat": FORMATO_QUOTE, "dateFormat": "iso"}
    url = f"{HOST}/v4/sports/{sport_key}/odds/"
    blocco: Dict[str, Any] = {"sport_key": sport_key, "scaricato_il": ora_utc(),
                              "url_masked": url_masked(sport_key, bool(chiave)),
                              "http_status": None, "crediti": {}, "eventi": [],
                              "n_eventi": 0, "errore": None}
    try:
        r = requests.get(url, params=params, timeout=timeout)
    except Exception as e:                                    # noqa: BLE001  (rete: mai su)
        blocco["errore"] = redigi(f"{type(e).__name__}: {e}", chiave)[:300]
        return blocco
    blocco["http_status"] = r.status_code
    blocco["crediti"] = crediti_da_header(dict(r.headers or {}))
    if r.status_code != 200:
        corpo = redigi((r.text or "")[:300], chiave)
        blocco["errore"] = f"HTTP {r.status_code}: {corpo}"
        if r.status_code in HTTP_QUOTA:
            blocco["quota_esaurita"] = True
        if r.status_code in HTTP_CHIAVE:
            blocco["chiave_rifiutata"] = True
        return blocco
    try:
        eventi = r.json()
    except ValueError as e:
        blocco["errore"] = redigi(f"risposta non JSON: {e}", chiave)[:300]
        return blocco
    if isinstance(eventi, dict):                              # errore nel corpo con HTTP 200
        blocco["errore"] = redigi(json.dumps(eventi, ensure_ascii=False)[:300], chiave)
        return blocco
    blocco["eventi"] = [evento_norm(e) for e in eventi if isinstance(e, dict)]
    blocco["n_eventi"] = len(blocco["eventi"])
    return blocco


def scarica_lega_fixture(sport_key: str, fixture_dir: str) -> Dict[str, Any]:
    """Stessa forma di ``scarica_lega_rete``, ma da una risposta salvata su disco."""
    blocco: Dict[str, Any] = {"sport_key": sport_key, "scaricato_il": ora_utc(),
                              "url_masked": f"fixture:{fixture_dir}/{sport_key}",
                              "http_status": 200, "crediti": {}, "eventi": [],
                              "n_eventi": 0, "errore": None}
    path = os.path.join(fixture_dir, f"odds_api_{sport_key}.json")
    snap = payload_fixture(path)
    if snap is None:
        blocco["http_status"] = None
        blocco["errore"] = f"fixture mancante o non leggibile: {path}"
        return blocco
    http = snap.get("http") if isinstance(snap.get("http"), dict) else {}
    blocco["http_status"] = http.get("status", 200)
    blocco["crediti"] = crediti_da_header({k: v for k, v in (http.get("crediti") or {}).items()
                                           if v is not None}) or {}
    if not blocco["crediti"]:
        blocco["crediti"] = http.get("crediti") or {}
    blocco["scaricato_il"] = snap.get("scaricato_il") or blocco["scaricato_il"]
    blocco["eventi"] = [evento_norm(e) for e in (snap.get("events") or snap.get("eventi") or [])
                        if isinstance(e, dict)]
    blocco["n_eventi"] = len(blocco["eventi"])
    return blocco


# ---------------------------------------------------------------------------
# Payload complessivo
# ---------------------------------------------------------------------------
def ora_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def riepilogo_crediti(blocchi: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Crediti dell'ULTIMA chiamata riuscita (gli header sono cumulativi)."""
    ultimo: Dict[str, Any] = {}
    for b in blocchi:
        if b.get("crediti"):
            ultimo = b["crediti"]
    costo = sum(int(b["crediti"].get("costo_ultima_chiamata") or 0)
                for b in blocchi if b.get("crediti"))
    out = {"quota_mensile": QUOTA_MENSILE,
           "usati_dall_ultimo_reset": ultimo.get("usati_dall_ultimo_reset"),
           "residui": ultimo.get("residui"),
           "costo_ultima_chiamata": ultimo.get("costo_ultima_chiamata"),
           "costo_giro_completo": costo or None,
           "fonte": "header x-requests-* dell'ultima chiamata"}
    return out


def costruisci_payload(blocchi: Sequence[Dict[str, Any]], *, fixture: Optional[str],
                       chiave_presente: bool, precedente: Optional[Dict[str, Any]] = None
                       ) -> Dict[str, Any]:
    leghe: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    errori: List[Dict[str, Any]] = []
    for lega, sport_key in LEGA_SPORT_KEY.items():
        blocco = next((b for b in blocchi if b.get("sport_key") == sport_key), None)
        if blocco is None:
            errori.append({"lega": lega, "sport_key": sport_key, "errore": "nessuna chiamata"})
            leghe[lega] = {"sport_key": sport_key, "scaricato_il": None, "http_status": None,
                           "n_eventi": 0, "eventi": [], "errore": "nessuna chiamata"}
            continue
        if blocco.get("errore"):
            errori.append({"lega": lega, "sport_key": sport_key, "errore": blocco["errore"]})
        leghe[lega] = {
            "sport_key": sport_key,
            "scaricato_il": blocco.get("scaricato_il"),
            "http_status": blocco.get("http_status"),
            "crediti": blocco.get("crediti") or {},
            "n_eventi": blocco.get("n_eventi", 0),
            "eventi": blocco.get("eventi") or [],
            "errore": blocco.get("errore"),
        }
    n_eventi = sum(v["n_eventi"] for v in leghe.values())
    payload: Dict[str, Any] = {
        "schema": SCHEMA_LIVE_ODDS,
        "generato_il": ora_utc(),
        "fonte": "the-odds-api",
        "piano": "starter (500 crediti/mese)",
        "regioni": REGIONI,
        "mercato": MERCATO,
        "formato_quote": FORMATO_QUOTE,
        "modalita": "fixture" if fixture else "rete",
        "crediti": riepilogo_crediti(blocchi),
        "n_leghe_ok": sum(1 for v in leghe.values() if v["n_eventi"] > 0),
        "n_leghe_richieste": len(LEGA_SPORT_KEY),
        "n_eventi": n_eventi,
        "leghe": leghe,
        "errori": errori,
        "leghe_mancanti_rispetto_a_prima": leghe_mancanti(precedente, leghe),
    }
    return payload


def leghe_mancanti(precedente: Optional[Dict[str, Any]],
                   nuove: Dict[str, Dict[str, Any]]) -> List[str]:
    """Leghe con eventi nel file precedente e senza eventi adesso."""
    if not isinstance(precedente, dict):
        return []
    vecchie = precedente.get("leghe") or {}
    if not isinstance(vecchie, dict):
        return []
    return sorted(lega for lega, blocco in vecchie.items()
                  if isinstance(blocco, dict) and (blocco.get("n_eventi") or blocco.get("eventi"))
                  and not (nuove.get(lega) or {}).get("n_eventi"))


# ---------------------------------------------------------------------------
# Scrittura atomica
# ---------------------------------------------------------------------------
def scrivi_atomico(payload: Dict[str, Any], percorso: str) -> None:
    cartella = os.path.dirname(os.path.abspath(percorso)) or "."
    os.makedirs(cartella, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".live_odds.", suffix=".tmp", dir=cartella)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1, sort_keys=False)
            fh.write("\n")
        os.replace(tmp, percorso)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def esegui(*, chiave: Optional[str], fixture: Optional[str], out: str, dry_run: bool,
           timeout: int = 30) -> Tuple[int, Dict[str, Any]]:
    """Un giro completo. Ritorna ``(codice_uscita, riepilogo)``; non solleva."""
    chiave = chiave or ""
    if not fixture and not chiave:
        LOG.error("%s assente: nessuna chiamata possibile (il file precedente non viene toccato).",
                  NOME_ENV_CHIAVE)
        return ESITO_CHIAVE, {"scritto": False, "motivo": f"{NOME_ENV_CHIAVE} assente"}

    precedente = None
    if os.path.exists(out):
        try:
            with open(out, encoding="utf-8") as fh:
                precedente = json.load(fh)
        except (OSError, ValueError) as e:
            LOG.warning("File precedente %s non leggibile (%s): si procede senza confronto.",
                        out, type(e).__name__)

    blocchi: List[Dict[str, Any]] = []
    for sport_key in LEGA_SPORT_KEY.values():
        blocco = (scarica_lega_fixture(sport_key, fixture) if fixture
                  else scarica_lega_rete(sport_key, chiave, timeout=timeout))
        blocchi.append(blocco)
        stato = "OK" if blocco.get("n_eventi") else f"ERRORE ({blocco.get('errore')})"
        LOG.info("%s: %s eventi %s", sport_key, blocco.get("n_eventi"), stato)
        if blocco.get("quota_esaurita"):
            LOG.error("Quota crediti esaurita su %s (HTTP %s): il file precedente NON viene "
                      "sovrascritto.", sport_key, blocco.get("http_status"))
            return ESITO_QUOTA_ESAURITA, {"scritto": False, "motivo": "quota crediti esaurita",
                                          "blocchi": blocchi}
        if blocco.get("chiave_rifiutata"):
            LOG.error("Chiave rifiutata su %s (HTTP %s): il file precedente NON viene "
                      "sovrascritto.", sport_key, blocco.get("http_status"))
            return ESITO_CHIAVE, {"scritto": False, "motivo": "chiave rifiutata",
                                  "blocchi": blocchi}

    payload = costruisci_payload(blocchi, fixture=fixture, chiave_presente=bool(chiave),
                                 precedente=precedente)

    # Guardia sulla chiave: se per qualunque ragione fosse finita nel JSON, non
    # si scrive. Nessun messaggio di errore la contiene (redigi su ogni testo).
    testo = json.dumps(payload, ensure_ascii=False)
    if chiave and chiave in testo:
        LOG.error("La chiave compare nel payload: scrittura BLOCCATA.")
        return ESITO_CHIAVE, {"scritto": False, "motivo": "chiave nel payload"}

    crediti = payload["crediti"]
    LOG.info("Giro completo: %s/%s leghe con eventi, %s eventi totali.",
             payload["n_leghe_ok"], payload["n_leghe_richieste"], payload["n_eventi"])
    LOG.info("Crediti: usati %s, residui %s, costo ultima chiamata %s (quota %s/mese).",
             crediti.get("usati_dall_ultimo_reset"), crediti.get("residui"),
             crediti.get("costo_ultima_chiamata"), crediti.get("quota_mensile"))
    if payload["errori"]:
        for err in payload["errori"]:
            LOG.warning("Lega %s: %s", err["lega"], err["errore"])
    if payload["leghe_mancanti_rispetto_a_prima"]:
        LOG.warning("Leghe con eventi prima e senza adesso: %s",
                    ", ".join(payload["leghe_mancanti_rispetto_a_prima"]))

    if payload["n_eventi"] == 0:
        LOG.error("Nessun evento da nessuna lega: il file precedente (%s) NON viene "
                  "sovrascritto con dati vuoti.", out)
        return ESITO_NULLA_SCRITTO, {"scritto": False, "motivo": "nessun evento",
                                     "payload": payload}

    if dry_run:
        LOG.info("dry-run: %s NON scritto (%s eventi sarebbero stati scritti).",
                 out, payload["n_eventi"])
        return ESITO_OK, {"scritto": False, "dry_run": True, "payload": payload}

    try:
        scrivi_atomico(payload, out)
    except OSError as e:
        LOG.error("Scrittura di %s fallita (%s: %s): il file precedente resta.",
                  out, type(e).__name__, e)
        return ESITO_NULLA_SCRITTO, {"scritto": False, "motivo": f"scrittura fallita: {e}",
                                     "payload": payload}
    LOG.info("Scritto %s (%s eventi, %s/%s leghe).", out, payload["n_eventi"],
             payload["n_leghe_ok"], payload["n_leghe_richieste"])
    return ESITO_OK, {"scritto": True, "percorso": out, "payload": payload}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixture", help="cartella con risposte simulate odds_api_<sport_key>.json "
                                      "(nessuna chiamata di rete, 0 crediti)")
    ap.add_argument("--out", default=os.path.join(HERE, "database", "live_odds.json"),
                    help="percorso di live_odds.json")
    ap.add_argument("--dry-run", action="store_true", help="non scrivere il file")
    ap.add_argument("--timeout", type=int, default=30, help="timeout HTTP per lega (secondi)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s", stream=sys.stdout)
    codice, _riepilogo = esegui(chiave=os.environ.get(NOME_ENV_CHIAVE), fixture=args.fixture,
                                out=args.out, dry_run=args.dry_run, timeout=args.timeout)
    return codice


if __name__ == "__main__":
    raise SystemExit(main())
