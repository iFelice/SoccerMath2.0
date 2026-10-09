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

CONVERSIONE DELLA RISPOSTA (il guasto del 2026-10-09)
------------------------------------------------------
The Odds API manda le quote ANNIDATE::

    [{"id": ..., "home_team": "Genoa", "away_team": "Fiorentina",
      "bookmakers": [{"key": "pinnacle", "title": "Pinnacle",
                      "last_update": "...",
                      "markets": [{"key": "h2h", "outcomes": [
                          {"name": "Genoa", "price": 3.34},
                          {"name": "Fiorentina", "price": 2.36},
                          {"name": "Draw", "price": 3.23}]}]}]}]

Gli esiti NON si chiamano 1/X/2: si riconoscono confrontando ``name`` con
``home_team``/``away_team`` dell'evento e con ``Draw``. Fino al 2026-10-09
questo writer leggeva solo la forma COMPATTATA degli snapshot della sonda
(``{"key": ..., "h2h": {"home":..., "draw":..., "away":...}}``) e scartava ogni
bookmaker annidato: 96 eventi, HTTP 200, 5 crediti e ``"libri": []`` dappertutto.
Adesso ``h2h_dal_bookmaker`` accetta entrambe le forme e il giro FALLISCE se una
lega ha eventi e zero libri (exit 4), invece di scrivere un file senza quote.

ROBUSTEZZA (mai sovrascrivere con dati vuoti)
---------------------------------------------
  * se NESSUNA lega torna eventi il file precedente resta intatto (exit 1);
  * se una lega ha eventi ma ZERO libri dopo la conversione il file precedente
    resta intatto (exit 4): meglio quote di ieri vere che un file di oggi vuoto;
  * se la quota crediti e' esaurita (HTTP 429 / 402, o corpo che parla di
    quota) il file precedente resta intatto (exit 2);
  * se SOLO ALCUNE leghe tornano eventi si scrive, con gli errori elencati nel
    file e nel log, e con ``leghe_mancanti_rispetto_a_prima``: perdere una lega
    non deve far perdere le altre quattro;
  * la scrittura e' atomica (tmp + ``os.replace``), come gli altri writer del
    progetto.

DIAGNOSTICA NEL FILE (0 crediti per il prossimo guasto)
--------------------------------------------------------
Ogni lega porta nel file due blocchi di SOLI CONTEGGI (nessuna quota grezza,
nessun URL, nessuna chiave):

  * ``grezzo``: eventi, eventi con bookmaker, coppie evento-bookmaker,
    bookmaker distinti per chiave, mercati presenti, forma dei bookmaker
    (annidata/piatta) - tutto misurato PRIMA della conversione;
  * ``conversione``: eventi con almeno un libro, eventi con Pinnacle, libri
    totali, terne complete/incomplete e i bookmaker scartati per MOTIVO.

Con questi numeri \"la fonte non aveva quote\" e \"le abbiamo perse noi\" si
distinguono leggendo il file, senza spendere una chiamata.

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
import math
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
# Eventi presenti ma NESSUN libro dopo la conversione: la risposta c'e' ma le
# quote non sono arrivate nel file. Il Top Mix di mercato sarebbe vuoto, quindi
# il giro FALLISCE e il file precedente resta (guasto del 2026-10-09).
ESITO_CONVERSIONE_VUOTA = 4

# Bookmaker primario: lo stesso di ``market_odds.BOOKMAKER_PRIMARIO``, qui solo
# per contarlo nel log e nella diagnostica (il writer non sceglie nulla).
BOOKMAKER_PRIMARIO = "pinnacle"

# Nomi dell'esito "pareggio" nella risposta grezza (The Odds API usa "Draw";
# il confronto e' case-insensitive). Nessun fuzzy matching: elenco dichiarato.
NOMI_PAREGGIO = ("draw", "tie", "pareggio")

# Motivi per cui un bookmaker della risposta NON diventa un libro del file.
# Finiscono nei conteggi del file: un guasto si diagnostica dal file, non da
# una nuova chiamata all'API.
SCARTO_NON_DICT = "bookmaker_non_dizionario"
SCARTO_SENZA_MERCATI = "senza_markets_ne_h2h"
SCARTO_MERCATO_H2H_ASSENTE = "mercato_h2h_assente"
SCARTO_ESITI_NON_ABBINATI = "esiti_non_abbinati_ai_nomi_evento"
SCARTO_PREZZO_NON_NUMERICO = "prezzo_non_numerico"
SCARTO_TERNA_VUOTA = "terna_vuota"


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
def _prezzo(valore: Any) -> Optional[float]:
    """Quota come ``float``, o ``None`` se non e' un numero finito.

    Accetta int e float (quello che manda The Odds API con
    ``oddsFormat=decimal``) e, per prudenza, anche la stringa numerica: una
    quota arrivata come ``"2.15"`` e' un dato valido, non un motivo per buttare
    un bookmaker. ``bool`` NON e' un numero (``True`` non e' la quota 1.0).
    """
    if isinstance(valore, bool):
        return None
    if isinstance(valore, (int, float)):
        v = float(valore)
        return v if math.isfinite(v) else None
    if isinstance(valore, str):
        try:
            v = float(valore.strip().replace(",", "."))
        except (ValueError, AttributeError):
            return None
        return v if math.isfinite(v) else None
    return None


def _nome_norm(valore: Any) -> str:
    """Nome di un esito/squadra normalizzato per il CONFRONTO (non per l'output).

    Solo spazi collassati e maiuscole/minuscole ignorate: nessun fuzzy matching,
    nessun alias. L'abbinamento ai nomi del progetto resta compito di
    ``team_names.resolve_team_name`` a valle.
    """
    return " ".join(str(valore or "").split()).casefold()


def h2h_dal_bookmaker(libro: Any, home_team: Any, away_team: Any
                      ) -> Tuple[Optional[Dict[str, Optional[float]]], Optional[str]]:
    """Terna ``{"home","draw","away"}`` di UN bookmaker, o ``(None, motivo)``.

    Due forme accettate, perche' sono due cose diverse e nel progetto esistono
    entrambe:

    1. forma GREZZA di The Odds API (quella che arriva dalla rete)::

         {"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [
             {"name": "<home_team>", "price": 3.34},
             {"name": "<away_team>", "price": 2.36},
             {"name": "Draw",        "price": 3.23}]}]}

       gli esiti NON hanno 1/X/2: si riconoscono confrontando ``name`` con
       ``home_team``/``away_team`` dell'evento e con ``Draw``;

    2. forma COMPATTATA degli snapshot della sonda
       (``audit/data/live_odds_probe``, prodotta da
       ``audit/live_odds_probe.compact_events``)::

         {"key": "pinnacle", "h2h": {"home": 3.34, "draw": 3.23, "away": 2.36}}

    Il motivo dello scarto viene RESTITUITO (non ingoiato): e' quello che
    finisce nei conteggi del file, cosi' il prossimo guasto si legge dal file.
    """
    if not isinstance(libro, dict):
        return None, SCARTO_NON_DICT

    piatto = libro.get("h2h")
    if isinstance(piatto, dict):
        h2h = {"home": _prezzo(piatto.get("home")),
               "draw": _prezzo(piatto.get("draw")),
               "away": _prezzo(piatto.get("away"))}
        if all(v is None for v in h2h.values()):
            vuoto = all(piatto.get(k) is None for k in ("home", "draw", "away"))
            return None, SCARTO_TERNA_VUOTA if vuoto else SCARTO_PREZZO_NON_NUMERICO
        return h2h, None

    mercati = libro.get("markets")
    if not isinstance(mercati, list):
        return None, SCARTO_SENZA_MERCATI
    mercato = next((m for m in mercati
                    if isinstance(m, dict) and str(m.get("key") or "").strip().lower() == MERCATO),
                   None)
    if mercato is None:
        return None, SCARTO_MERCATO_H2H_ASSENTE

    h2h: Dict[str, Optional[float]] = {"home": None, "draw": None, "away": None}
    n_non_abbinati = 0
    n_prezzi_non_numerici = 0
    casa = _nome_norm(home_team)
    ospite = _nome_norm(away_team)
    for esito in mercato.get("outcomes") or []:
        if not isinstance(esito, dict):
            n_non_abbinati += 1
            continue
        nome = _nome_norm(esito.get("name"))
        if nome and nome == casa:
            ruolo = "home"
        elif nome and nome == ospite:
            ruolo = "away"
        elif nome in NOMI_PAREGGIO:
            ruolo = "draw"
        else:
            n_non_abbinati += 1
            continue
        prezzo = _prezzo(esito.get("price"))
        if prezzo is None:
            n_prezzi_non_numerici += 1
            continue
        h2h[ruolo] = prezzo

    if all(v is None for v in h2h.values()):
        if n_prezzi_non_numerici:
            return None, SCARTO_PREZZO_NON_NUMERICO
        if n_non_abbinati:
            return None, SCARTO_ESITI_NON_ABBINATI
        return None, SCARTO_TERNA_VUOTA
    return h2h, None


def libri_dell_evento(evento: Dict[str, Any],
                      scarti: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """I bookmaker di un evento, con SOLO i campi che servono (quote grezze).

    ``h2h`` resta grezzo (home/draw/away come li da' la fonte): nessuna
    rielaborazione, il de-vig lo fa ``market_odds.probabilita_mercato``.
    Accetta la forma grezza di The Odds API (``markets``/``outcomes``) e quella
    compattata degli snapshot della sonda: vedi ``h2h_dal_bookmaker``.

    ``scarti`` (se passato) viene incrementato con il MOTIVO di ogni bookmaker
    che non produce un libro: e' la diagnostica che finisce nel file.
    """
    out: List[Dict[str, Any]] = []
    home_team = evento.get("home_team")
    away_team = evento.get("away_team")
    for libro in evento.get("bookmakers") or []:
        h2h, motivo = h2h_dal_bookmaker(libro, home_team, away_team)
        if h2h is None:
            if scarti is not None and motivo:
                scarti[motivo] = scarti.get(motivo, 0) + 1
            continue
        out.append({
            "key": libro.get("key"),
            "title": libro.get("title"),
            "last_update": libro.get("last_update"),
            "h2h": h2h,
        })
    return out


def evento_norm(evento: Dict[str, Any],
                scarti: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    return {
        "id": evento.get("id"),
        "commence_time": evento.get("commence_time"),
        "home_team": evento.get("home_team"),
        "away_team": evento.get("away_team"),
        "libri": libri_dell_evento(evento, scarti),
    }


# ---------------------------------------------------------------------------
# Diagnostica: conteggi PRIMA e DOPO la conversione (senza dati sensibili)
# ---------------------------------------------------------------------------
def conteggi_grezzi(eventi: Sequence[Any]) -> Dict[str, Any]:
    """Conteggi sulla risposta GREZZA, prima di qualunque conversione.

    Niente quote, niente URL, niente chiavi: solo numeri e nomi pubblici di
    bookmaker e mercati. Servono a rispondere dal FILE (0 crediti) alla domanda
    \"la fonte aveva i bookmaker e li abbiamo persi noi, oppure non li aveva?\",
    che senza questi conteggi e' costata una sonda a pagamento.
    """
    per_chiave: Dict[str, int] = {}
    mercati: Dict[str, int] = {}
    forma = {"annidata": 0, "piatta": 0, "sconosciuta": 0}
    n_eventi = 0
    n_con_bookmaker = 0
    n_coppie = 0
    for evento in eventi or []:
        if not isinstance(evento, dict):
            continue
        n_eventi += 1
        libri = evento.get("bookmakers")
        libri = libri if isinstance(libri, list) else []
        if libri:
            n_con_bookmaker += 1
        for libro in libri:
            n_coppie += 1
            if not isinstance(libro, dict):
                forma["sconosciuta"] += 1
                continue
            chiave = str(libro.get("key") or "").strip() or "(senza chiave)"
            per_chiave[chiave] = per_chiave.get(chiave, 0) + 1
            if isinstance(libro.get("markets"), list):
                forma["annidata"] += 1
                for mercato in libro["markets"]:
                    if isinstance(mercato, dict):
                        nome = str(mercato.get("key") or "").strip() or "(senza chiave)"
                        mercati[nome] = mercati.get(nome, 0) + 1
            elif isinstance(libro.get("h2h"), dict):
                forma["piatta"] += 1
                mercati["h2h"] = mercati.get("h2h", 0) + 1
            else:
                forma["sconosciuta"] += 1
    ordina = lambda d: dict(sorted(d.items(), key=lambda kv: (-kv[1], kv[0])))  # noqa: E731
    return {
        "n_eventi": n_eventi,
        "n_eventi_con_bookmaker": n_con_bookmaker,
        "n_eventi_senza_bookmaker": n_eventi - n_con_bookmaker,
        "n_coppie_evento_bookmaker": n_coppie,
        "n_bookmaker_distinti": len(per_chiave),
        "bookmaker_per_chiave": ordina(per_chiave),
        "mercati_presenti": ordina(mercati),
        "forma_bookmaker": forma,
    }


def conteggi_conversione(eventi: Sequence[Dict[str, Any]],
                         scarti: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """Conteggi DOPO la conversione: quanto e' sopravvissuto, e cosa si e' perso."""
    n_libri = 0
    n_con_libri = 0
    n_con_primario = 0
    n_terne_complete = 0
    n_terne_incomplete = 0
    for evento in eventi or []:
        libri = evento.get("libri") or []
        n_libri += len(libri)
        if libri:
            n_con_libri += 1
        if any(str((l or {}).get("key") or "").strip().lower() == BOOKMAKER_PRIMARIO
               for l in libri):
            n_con_primario += 1
        for libro in libri:
            h2h = (libro or {}).get("h2h") or {}
            if all(h2h.get(k) is not None for k in ("home", "draw", "away")):
                n_terne_complete += 1
            else:
                n_terne_incomplete += 1
    n_eventi = len(eventi or [])
    return {
        "n_eventi": n_eventi,
        "n_eventi_con_libri": n_con_libri,
        "n_eventi_senza_libri": n_eventi - n_con_libri,
        "n_eventi_con_pinnacle": n_con_primario,
        "n_libri_totale": n_libri,
        "n_terne_complete": n_terne_complete,
        "n_terne_incomplete": n_terne_incomplete,
        "bookmaker_scartati": dict(sorted((scarti or {}).items(),
                                          key=lambda kv: (-kv[1], kv[0]))),
    }


def normalizza_eventi(eventi: Sequence[Any]) -> Tuple[List[Dict[str, Any]],
                                                      Dict[str, Any], Dict[str, Any]]:
    """Risposta grezza -> ``(eventi normalizzati, conteggi grezzi, conteggi conversione)``.

    UNICO punto in cui una risposta (di rete o da fixture) diventa eventi del
    file: rete e fixture passano di qui, quindi una prova su fixture prova
    davvero il percorso di produzione.
    """
    grezzo = conteggi_grezzi(eventi)
    scarti: Dict[str, int] = {}
    norm = [evento_norm(e, scarti) for e in (eventi or []) if isinstance(e, dict)]
    return norm, grezzo, conteggi_conversione(norm, scarti)


def payload_fixture(percorso: str) -> Optional[Any]:
    """Legge una risposta simulata.

    Due formati, entrambi reali:
      * LISTA: il corpo GREZZO di ``/v4/sports/<key>/odds`` come arriva dalla
        rete (quello che il writer deve saper convertire);
      * DIZIONARIO: lo snapshot compattato della sonda
        (``audit/data/live_odds_probe/odds_api_<key>.json``), con ``events``,
        ``http`` e i crediti.
    """
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
                              "n_eventi": 0, "errore": None,
                              "grezzo": conteggi_grezzi([]),
                              "conversione": conteggi_conversione([])}
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
    blocco["eventi"], blocco["grezzo"], blocco["conversione"] = normalizza_eventi(eventi)
    blocco["n_eventi"] = len(blocco["eventi"])
    return blocco


def scarica_lega_fixture(sport_key: str, fixture_dir: str) -> Dict[str, Any]:
    """Stessa forma di ``scarica_lega_rete``, ma da una risposta salvata su disco."""
    blocco: Dict[str, Any] = {"sport_key": sport_key, "scaricato_il": ora_utc(),
                              "url_masked": f"fixture:{fixture_dir}/{sport_key}",
                              "http_status": 200, "crediti": {}, "eventi": [],
                              "n_eventi": 0, "errore": None,
                              "grezzo": conteggi_grezzi([]),
                              "conversione": conteggi_conversione([])}
    path = os.path.join(fixture_dir, f"odds_api_{sport_key}.json")
    snap = payload_fixture(path)
    if snap is None:
        blocco["http_status"] = None
        blocco["errore"] = f"fixture mancante o non leggibile: {path}"
        return blocco
    if isinstance(snap, list):          # corpo GREZZO dell'endpoint /odds
        eventi_grezzi: Sequence[Any] = snap
    elif isinstance(snap, dict):        # snapshot compattato della sonda
        http = snap.get("http") if isinstance(snap.get("http"), dict) else {}
        blocco["http_status"] = http.get("status", 200)
        blocco["crediti"] = crediti_da_header({k: v for k, v in (http.get("crediti") or {}).items()
                                               if v is not None}) or {}
        if not blocco["crediti"]:
            blocco["crediti"] = http.get("crediti") or {}
        blocco["scaricato_il"] = snap.get("scaricato_il") or blocco["scaricato_il"]
        eventi_grezzi = snap.get("events") or snap.get("eventi") or []
    else:
        blocco["http_status"] = None
        blocco["errore"] = f"fixture con forma inattesa ({type(snap).__name__}): {path}"
        return blocco
    blocco["eventi"], blocco["grezzo"], blocco["conversione"] = normalizza_eventi(eventi_grezzi)
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
                           "n_eventi": 0, "eventi": [], "errore": "nessuna chiamata",
                           "grezzo": conteggi_grezzi([]), "conversione": conteggi_conversione([])}
            continue
        if blocco.get("errore"):
            errori.append({"lega": lega, "sport_key": sport_key, "errore": blocco["errore"]})
        leghe[lega] = {
            "sport_key": sport_key,
            "scaricato_il": blocco.get("scaricato_il"),
            "http_status": blocco.get("http_status"),
            "crediti": blocco.get("crediti") or {},
            "n_eventi": blocco.get("n_eventi", 0),
            # DIAGNOSTICA (nessun dato sensibile: solo conteggi e nomi pubblici
            # di bookmaker/mercati). La risposta grezza NON viene salvata, ma
            # questi numeri dicono se i bookmaker c'erano prima della conversione.
            "grezzo": blocco.get("grezzo") or conteggi_grezzi([]),
            "conversione": blocco.get("conversione") or conteggi_conversione([]),
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
        "n_leghe_con_quote": sum(1 for v in leghe.values()
                                 if (v["conversione"] or {}).get("n_eventi_con_libri")),
        "n_leghe_richieste": len(LEGA_SPORT_KEY),
        "n_eventi": n_eventi,
        "n_eventi_con_libri": sum((v["conversione"] or {}).get("n_eventi_con_libri", 0)
                                  for v in leghe.values()),
        "n_eventi_con_pinnacle": sum((v["conversione"] or {}).get("n_eventi_con_pinnacle", 0)
                                     for v in leghe.values()),
        "n_libri_totale": sum((v["conversione"] or {}).get("n_libri_totale", 0)
                              for v in leghe.values()),
        "leghe_con_eventi_senza_libri": leghe_con_eventi_senza_libri(leghe),
        "leghe": leghe,
        "errori": errori,
        "leghe_mancanti_rispetto_a_prima": leghe_mancanti(precedente, leghe),
    }
    return payload


def leghe_con_eventi_senza_libri(leghe: Dict[str, Dict[str, Any]]) -> List[str]:
    """Leghe con eventi e ZERO libri dopo la conversione.

    E' il guasto del 2026-10-09: 96 eventi su 5 leghe, HTTP 200, 1 credito per
    lega e ``"libri": []`` su tutti gli eventi. Una lega che ha eventi ma
    nessun libro non e' \"quasi a posto\": per il Top Mix di mercato vale zero,
    quindi il giro deve FALLIRE e il file precedente deve restare.
    """
    fuori: List[str] = []
    for lega, blocco in (leghe or {}).items():
        if not isinstance(blocco, dict):
            continue
        if (blocco.get("n_eventi") or 0) > 0 and \
                not ((blocco.get("conversione") or {}).get("n_libri_totale") or 0):
            fuori.append(lega)
    return fuori


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
# Log di una lega
# ---------------------------------------------------------------------------
def registra_log_lega(sport_key: str, blocco: Dict[str, Any]) -> str:
    """Una riga di log per lega, con i numeri che servono a capire un guasto.

    Riporta SEMPRE: eventi, eventi con almeno un libro, eventi con Pinnacle,
    bookmaker nella risposta GREZZA prima della conversione (totale e distinti)
    e i mercati visti.

    \"N eventi OK\" non esiste piu': il 2026-10-09 il log diceva \"20 eventi OK\"
    per lega mentre il file usciva con ``"libri": []`` su tutti gli eventi.
    Una lega e' ``OK`` solo se TUTTI i suoi eventi hanno almeno un libro,
    ``PARZIALE`` se solo alcuni, ``SENZA QUOTE`` se nessuno.
    """
    grezzo = blocco.get("grezzo") or {}
    conv = blocco.get("conversione") or {}
    n_eventi = int(blocco.get("n_eventi") or 0)
    con_libri = int(conv.get("n_eventi_con_libri") or 0)
    con_pinnacle = int(conv.get("n_eventi_con_pinnacle") or 0)
    bm_grezzi = int(grezzo.get("n_coppie_evento_bookmaker") or 0)
    bm_distinti = int(grezzo.get("n_bookmaker_distinti") or 0)
    mercati = ", ".join(f"{k}={v}" for k, v in (grezzo.get("mercati_presenti") or {}).items()) \
        or "nessuno"
    scartati = conv.get("bookmaker_scartati") or {}
    coda = ("; bookmaker scartati nella conversione: "
            + ", ".join(f"{k}={v}" for k, v in scartati.items())) if scartati else ""

    if blocco.get("errore"):
        stato = f"ERRORE ({blocco['errore']})"
    elif n_eventi == 0:
        stato = "NESSUN EVENTO"
    elif con_libri == 0:
        stato = "SENZA QUOTE (eventi presenti, zero libri dopo la conversione)"
    elif con_libri < n_eventi:
        stato = "PARZIALE"
    else:
        stato = "OK"

    messaggio = ("%s: eventi=%d, eventi con almeno un libro=%d, eventi con Pinnacle=%d, "
                 "bookmaker nella risposta grezza=%d (distinti=%d), mercati grezzi: %s - %s%s")
    argomenti = (sport_key, n_eventi, con_libri, con_pinnacle, bm_grezzi, bm_distinti,
                 mercati, stato, coda)
    if blocco.get("errore") or (n_eventi > 0 and con_libri == 0):
        LOG.error(messaggio, *argomenti)
    elif n_eventi == 0 or con_libri < n_eventi:
        LOG.warning(messaggio, *argomenti)
    else:
        LOG.info(messaggio, *argomenti)
    return messaggio % argomenti


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
        registra_log_lega(sport_key, blocco)
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
    LOG.info("Giro completo: %s/%s leghe con eventi, %s/%s leghe con quote, %s eventi totali, "
             "%s eventi con almeno un libro, %s con Pinnacle, %s libri in tutto.",
             payload["n_leghe_ok"], payload["n_leghe_richieste"], payload["n_leghe_con_quote"],
             payload["n_leghe_richieste"], payload["n_eventi"], payload["n_eventi_con_libri"],
             payload["n_eventi_con_pinnacle"], payload["n_libri_totale"])
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

    # Eventi senza NESSUN libro: la risposta c'era, le quote no. Il Top Mix di
    # mercato sarebbe vuoto e il file precedente (quote vecchie ma vere) e'
    # meglio di un file nuovo senza quote: si fallisce e non si scrive.
    senza_libri = payload["leghe_con_eventi_senza_libri"]
    if senza_libri:
        for lega in senza_libri:
            blocco = payload["leghe"][lega]
            LOG.error("Lega %s (%s): %s eventi e ZERO libri dopo la conversione "
                      "(bookmaker nella risposta grezza: %s, distinti: %s, mercati: %s, "
                      "scarti: %s).",
                      lega, blocco.get("sport_key"), blocco.get("n_eventi"),
                      (blocco.get("grezzo") or {}).get("n_coppie_evento_bookmaker"),
                      (blocco.get("grezzo") or {}).get("n_bookmaker_distinti"),
                      (blocco.get("grezzo") or {}).get("mercati_presenti") or {},
                      (blocco.get("conversione") or {}).get("bookmaker_scartati") or {})
        LOG.error("Leghe con eventi e zero libri: %s. Il file precedente (%s) NON viene "
                  "sovrascritto: senza quote il Top Mix di mercato sarebbe vuoto.",
                  ", ".join(senza_libri), out)
        return ESITO_CONVERSIONE_VUOTA, {"scritto": False,
                                         "motivo": "lega con eventi e zero libri",
                                         "leghe_senza_libri": senza_libri,
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
    LOG.info("Scritto %s (%s eventi, %s con almeno un libro, %s con Pinnacle, %s/%s leghe).",
             out, payload["n_eventi"], payload["n_eventi_con_libri"],
             payload["n_eventi_con_pinnacle"], payload["n_leghe_ok"],
             payload["n_leghe_richieste"])
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
