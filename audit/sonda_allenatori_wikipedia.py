#!/usr/bin/env python3
"""sonda_allenatori_wikipedia.py — cambi di allenatore da Wikipedia (SOLA LETTURA).

FONTE ALTERNATIVA alla sonda football-data (``audit/sonda_allenatori.py``).
Per le 5 leghe legge con l'API MediaWiki la pagina della stagione 2026–27 e ne
estrae la tabella «Managerial changes» (squadra, allenatore uscente, modalita'
di uscita, data del cambio, allenatore entrante, data della nomina).

LINGUA DICHIARATA: **inglese** (``en.wikipedia.org``). Motivo: e' l'edizione in
cui le pagine delle stagioni di tutte e 5 le leghe hanno la stessa tabella
standard. it/de/es/fr NON sono letti da questa versione.

NESSUNA CHIAVE. User-Agent identificativo (regole di Wikipedia): nome del
progetto, versione, repository di riferimento. Una richiesta alla volta, con una
pausa di 1 s fra due richieste, ``maxlag`` dichiarato, al massimo 3 nuovi
tentativi su 429/5xx (attesa 5, 10, 20 s).

REGOLA DICHIARATA (scritta PRIMA dei numeri nel referto):
la regola si valuta solo se **tutte e 5 le leghe** sono state lette per intero
(la tabella trovata e ogni riga letta). Altrimenti «non valutabile: leghe
mancanti <elenco>». Con le 5 leghe lette, la regola passa solo se **tutti** i
casi pubblici di ``casi_pubblici_2026_27.json`` (almeno 3 casi valutabili) sono
presenti nella tabella di Wikipedia **con l'allenatore entrante giusto**.
La data NON e' parte della regola: le differenze di data sono riportate a parte.
Dopo, nel referto, i cambi trovati su Wikipedia che NON sono nel file dei casi.

Quello che NON fa: non usa la chiave, non tocca l'app, non scrive in
``SoccerMath/``. Scrive lo snapshot in ``audit/data/allenatori_wikipedia/`` e il
referto in ``audit/results/sonda_allenatori_wikipedia.md``.

Uso::

    python audit/sonda_allenatori_wikipedia.py [--leagues ...] [--casi FILE]
                                              [--out-dir DIR] [--results-dir DIR]
                                              [--fixture FILE] [--referto-non-eseguito]

``--fixture`` gira SENZA RETE su pagine finte (HTML salvato): i file portano il
prefisso ``fixture_`` e, senza cartelle esplicite, stanno in ``audit/output/``.

Code di uscita: 0 = eseguita (con qualunque esito); 2 = nessuna lega letta (niente
file scritti); 1 = errore di uso.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT_DIR = os.path.join(REPO_ROOT, "audit")
for _p in (AUDIT_DIR, os.path.join(REPO_ROOT, "SoccerMath")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sonda_allenatori as sa  # noqa: E402  (stessa logica di confronto dei nomi)

API_WIKI = "https://en.wikipedia.org/w/api.php"
LINGUA = "en"
STAGIONE = "2026–27"                       # trattino di Wikipedia (en dash)
STAGIONE_TRATTINO = "2026-27"              # variante di titolo, provata di seguito
USER_AGENT = ("SoccerMath2.0-audit/1.0 (https://github.com/iFelice/SoccerMath2.0; "
              "sonda di sola lettura dei cambi di allenatore; nessuna chiave)")
PAUSA_SECONDI = 1.0
TENTATIVI_RETE = 3                         # nuovi tentativi su 429/5xx
ATTESE_RETE = (5, 10, 20)

LEGHE = ("Serie A", "Premier League", "La Liga", "Bundesliga", "Ligue 1")
#: Nome di lega in Wikipedia (inglese) per il titolo «2026–27 <nome>».
NOME_WIKI = {
    "Serie A": "Serie A",
    "Premier League": "Premier League",
    "La Liga": "La Liga",
    "Bundesliga": "Bundesliga",
    "Ligue 1": "Ligue 1",
}
DEFAULT_OUT_DIR = os.path.join(REPO_ROOT, "audit", "data", "allenatori_wikipedia")
DEFAULT_RESULTS_DIR = os.path.join(REPO_ROOT, "audit", "results")
DEFAULT_OUT_DIR_FIXTURE = os.path.join(REPO_ROOT, "audit", "output", "sonda_allenatori_wikipedia")
PREFISSO_FIXTURE = "fixture_"
DEFAULT_CASI = os.path.join(REPO_ROOT, "audit", "data", "allenatori", "casi_pubblici_2026_27.json")
MIN_CASI_PUBBLICI = sa.MIN_CASI_PUBBLICI

ESITO_PRESENTE = "presente, entrante giusto"
ESITO_ENTRANTE_DIVERSO = "presente, entrante diverso"
ESITO_NON_TROVATO = "non trovato su Wikipedia"
ESITO_LEGA_NON_LETTA = "lega non letta"

#: Titolo di sezione delle tabelle dei cambi (inglese, con varianti dichiarate).
RE_SEZIONE_CAMBI = re.compile(
    r"(?i)^\s*(managerial changes|manager changes|changes of manager|"
    r"coach(?:ing)? changes|head coach changes)\s*$")

MESI = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}


# ---------------------------------------------------------------------------
# Rete (solo qui): User-Agent, pausa, nuovi tentativi
# ---------------------------------------------------------------------------
def richiedi_api(parametri: dict, session=None, sleep=time.sleep) -> dict:
    """Una richiesta all'API MediaWiki con i tentativi dichiarati."""
    import requests

    sessione = session or requests
    base = {"format": "json", "formatversion": "2", "maxlag": "5"}
    base.update(parametri)
    ultimo = None
    for tentativo in range(TENTATIVI_RETE + 1):
        try:
            risposta = sessione.get(API_WIKI, params=base,
                                    headers={"User-Agent": USER_AGENT}, timeout=30)
        except Exception as errore:  # rete: si riprova
            ultimo = errore
        else:
            if risposta.status_code in (429, 500, 502, 503, 504):
                ultimo = RuntimeError(f"HTTP {risposta.status_code} da Wikipedia")
            else:
                risposta.raise_for_status()
                dati = risposta.json()
                codice = ((dati or {}).get("error") or {}).get("code")
                if codice != "maxlag":           # server sotto carico: si riprova
                    return dati
                ultimo = RuntimeError("Wikipedia: maxlag (server sotto carico)")
        if tentativo < TENTATIVI_RETE:
            sleep(ATTESE_RETE[tentativo])
    raise RuntimeError(f"Wikipedia non risponde dopo {TENTATIVI_RETE} nuovi tentativi: {ultimo}")


def titoli_candidati(lega: str) -> list:
    """Titoli di pagina provati, in ordine: trattino di Wikipedia, poi il trattino ``-``."""
    nome = NOME_WIKI[lega]
    return [f"{STAGIONE}_{nome}".replace(" ", "_"),
            f"{STAGIONE_TRATTINO}_{nome}".replace(" ", "_")]


def scarica_pagina(lega: str, session=None, sleep=time.sleep, contatore=None) -> dict:
    """HTML della pagina della stagione della lega (prima variante di titolo che esiste).

    ``contatore`` (lista) riceve una voce per ogni richiesta API fatta.
    """
    ultimo = None
    for titolo in titoli_candidati(lega):
        if contatore is not None:
            contatore.append(titolo)
        dati = richiedi_api({"action": "parse", "page": titolo, "prop": "text|revid",
                             "disablelimitreport": "1"}, session=session, sleep=sleep)
        if "error" in dati:
            ultimo = dati["error"].get("code")
            sleep(PAUSA_SECONDI)
            continue
        parse = dati.get("parse") or {}
        return {"titolo": parse.get("title") or titolo,
                "revid": parse.get("revid"),
                "url": "https://en.wikipedia.org/wiki/" + titolo,
                "html": (parse.get("text") or "")}
    raise RuntimeError(f"pagina non trovata per {lega} (ultimo errore: {ultimo})")


# ---------------------------------------------------------------------------
# Lettura della tabella (funzioni pure sull'HTML: nessuna rete)
# ---------------------------------------------------------------------------
def _soup(html: str):
    from bs4 import BeautifulSoup
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # lxml non installato: parser standard
        return BeautifulSoup(html, "html.parser")


def testo_cella(cella) -> str:
    """Testo visibile di una cella: senza note a pie' di pagina e senza spazi doppi."""
    copia = _soup(str(cella))
    for nota in copia.find_all("sup"):
        nota.decompose()
    for stile in copia.find_all(["style", "script"]):
        stile.decompose()
    testo = copia.get_text(" ", strip=True)
    testo = re.sub(r"\[\s*\d+\s*\]", "", testo)          # resti di [12]
    testo = re.sub(r"\s+", " ", testo).strip()
    return testo


def _e_titolo_sezione(elemento) -> bool:
    if elemento.name in ("h2", "h3", "h4"):
        return True
    classi = " ".join(elemento.get("class") or [])
    return "mw-heading" in classi


def trova_tabella_cambi(html: str):
    """La tabella dei cambi di allenatore nella pagina: ``(titolo_sezione, tabella)``.

    Cerca il titolo di sezione (variante in inglese, ``RE_SEZIONE_CAMBI``); nella
    sezione, fra i fratelli successivi e prima del titolo successivo, prende la
    prima tabella con le intestazioni dei cambi (``_e_tabella_cambi``). Nessuna
    tabella «simile» al posto di quella giusta: ``(None, None)``.
    """
    soup = _soup(html)
    for intestazione in soup.find_all(["h2", "h3", "h4", "div"]):
        if intestazione.name == "div":
            if "mw-heading" not in " ".join(intestazione.get("class") or []):
                continue
            ancora = intestazione
        else:
            ancora = intestazione.find_parent("div", class_="mw-heading") or intestazione
        testo = re.sub(r"\[edit\]|\[modifica\]", "", ancora.get_text(" ", strip=True)).strip()
        if not RE_SEZIONE_CAMBI.match(testo):
            continue
        for fratello in ancora.find_next_siblings():
            if _e_titolo_sezione(fratello):
                break
            candidate = [fratello] if fratello.name == "table" else fratello.find_all("table")
            for tabella in candidate:
                if _e_tabella_cambi(tabella):
                    return testo, tabella
    return None, None


def _e_tabella_cambi(tabella) -> bool:
    primo = tabella.find("tr")
    testo = testo_cella(primo).lower() if primo is not None else ""
    return ("outgoing" in testo or "replaced" in testo) and "team" in testo


def griglia(tabella) -> list:
    """Le righe della tabella come liste di testi, con rowspan e colspan espansi.

    Una cella con rowspan=2 compare anche nella riga successiva: cosi' il nome
    della squadra dei cambi multipli non si perde. Nessuna riga viene riempita
    «a occhio»: una riga con un numero di celle diverso dall'intestazione resta
    tale, e il lettore la scarta dichiarandolo.
    """
    righe = []
    occupate: dict = {}          # colonna -> [testo, righe_ancora_da_coprire]
    for tr in tabella.find_all("tr"):
        riga = []
        colonna = 0
        celle = tr.find_all(["td", "th"], recursive=False)
        indice = 0
        while True:
            while colonna in occupate:
                valore = occupate[colonna][0]
                riga.append(valore)
                occupate[colonna][1] -= 1
                if occupate[colonna][1] <= 0:
                    del occupate[colonna]
                colonna += 1
            if indice >= len(celle):
                break
            cella = celle[indice]
            indice += 1
            testo = testo_cella(cella)
            rowspan = _intero(cella.get("rowspan"), 1)
            colspan = _intero(cella.get("colspan"), 1)
            for k in range(colspan):
                riga.append(testo)
                if rowspan > 1:
                    occupate[colonna + k] = [testo, rowspan - 1]
            colonna += colspan
        righe.append(riga)
    return righe


def _intero(valore, predefinito: int) -> int:
    try:
        return max(1, int(str(valore).strip()))
    except (TypeError, ValueError):
        return predefinito


def mappa_colonne(intestazioni: list) -> dict:
    """Indice delle colonne che ci servono, dalle intestazioni (in inglese)."""
    def trova(*parole):
        for i, testo in enumerate(intestazioni):
            t = testo.lower()
            if any(p in t for p in parole):
                return i
        return None

    mappa = {
        "squadra": trova("team", "club"),
        "uscente": trova("outgoing"),
        "uscita": trova("manner"),
        "data_cambio": trova("vacancy", "date of departure"),
        "entrante": trova("replaced by", "incoming", "successor", "appointed"),
        "data_nomina": trova("date of appointment", "appointment"),
    }
    mancanti = [k for k in ("squadra", "uscente", "entrante", "data_cambio")
                if mappa[k] is None]
    return {"mappa": mappa, "mancanti": mancanti}


MESE_RE = "|".join(MESI)
RE_DATA_TESTO = re.compile(rf"(\d{{1,2}})\s+({MESE_RE})\s+(\d{{4}})", re.IGNORECASE)
RE_DATA_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def data_iso(testo: str) -> Optional[str]:
    """``13 September 2026`` o ``2026-09-13`` -> ``2026-09-13``; altrimenti None."""
    if not testo:
        return None
    m = RE_DATA_TESTO.search(testo)
    if m:
        giorno, mese, anno = int(m.group(1)), MESI[m.group(2).lower()], int(m.group(3))
        return f"{anno:04d}-{mese:02d}-{giorno:02d}"
    m = RE_DATA_ISO.search(testo)
    if m:
        return m.group(0)
    return None


def _campo(riga, mappa, chiave):
    """Valore della colonna `chiave` nella riga, o stringa vuota se manca."""
    i = mappa.get(chiave)
    return riga[i] if i is not None and i < len(riga) else ""


def leggi_tabella(tabella) -> dict:
    """Le righe dei cambi: ``{"righe": [...], "illeggibili": [...], "errore": str|None}``."""
    griglia_righe = griglia(tabella)
    if not griglia_righe:
        return {"righe": [], "illeggibili": [], "errore": "tabella vuota"}
    intestazioni = griglia_righe[0]
    info = mappa_colonne(intestazioni)
    if info["mancanti"]:
        return {"righe": [], "illeggibili": [],
                "errore": "colonne non riconosciute: " + ", ".join(info["mancanti"])}
    mappa = info["mappa"]
    righe, illeggibili = [], []
    for riga in griglia_righe[1:]:
        if not any(riga):
            continue
        if len(riga) != len(intestazioni):
            illeggibili.append(riga)         # non si indovina: si dichiara
            continue

        squadra = _campo(riga, mappa, "squadra")
        uscente = _campo(riga, mappa, "uscente")
        entrante = _campo(riga, mappa, "entrante")
        if not squadra or not uscente:
            illeggibili.append(riga)
            continue
        righe.append({
            "squadra": squadra,
            "uscente": uscente,
            "uscita": _campo(riga, mappa, "uscita") or None,
            "data_cambio": data_iso(_campo(riga, mappa, "data_cambio")),
            "data_cambio_testo": _campo(riga, mappa, "data_cambio") or None,
            "entrante": entrante or None,
            "data_nomina": data_iso(_campo(riga, mappa, "data_nomina")),
        })
    return {"righe": righe, "illeggibili": illeggibili, "errore": None}


def leggi_lega(lega: str, pagina: dict) -> dict:
    """Una lega dalla sua pagina: letta per intero solo con tabella e righe lette."""
    titolo_sezione, tabella = trova_tabella_cambi(pagina.get("html") or "")
    base = {"lega": lega, "titolo": pagina.get("titolo"), "revid": pagina.get("revid"),
            "url": pagina.get("url"), "sezione": titolo_sezione}
    if tabella is None:
        return {**base, "letta": False, "righe": [], "illeggibili": [],
                "nota": "sezione «Managerial changes» o tabella non trovata"}
    lettura = leggi_tabella(tabella)
    if lettura["errore"]:
        return {**base, "letta": False, "righe": [], "illeggibili": lettura["illeggibili"],
                "nota": lettura["errore"]}
    letta = bool(lettura["righe"]) and not lettura["illeggibili"]
    nota = None
    if not lettura["righe"]:
        nota = "tabella senza righe leggibili"
    elif lettura["illeggibili"]:
        nota = f"{len(lettura['illeggibili'])} righe non leggibili: non lette per intero"
    return {**base, "letta": letta, "righe": lettura["righe"],
            "illeggibili": lettura["illeggibili"], "nota": nota}


# ---------------------------------------------------------------------------
# Confronto con i casi pubblici (stessa logica dei nomi della sonda football)
# ---------------------------------------------------------------------------
def confronta_casi(casi: list, leghe_lette: dict) -> list:
    """Per ogni caso: la tabella di Wikipedia ha la squadra con l'entrante giusto?"""
    esiti = []
    for caso in casi or []:
        lega = caso.get("lega")
        squadra_caso = caso.get("squadra")
        entrante = caso.get("allenatore_entrante") or caso.get("allenatore_atteso")
        riga = dict(caso)
        riga["data_file"] = caso.get("data_cambio") or caso.get("data")
        lettura = leghe_lette.get(lega)
        if not lettura or not lettura.get("letta"):
            riga.update({"esito": ESITO_LEGA_NON_LETTA, "entrante_wikipedia": None,
                         "data_wikipedia": None, "data_coincide": None})
            esiti.append(riga)
            continue
        candidate = [r for r in lettura["righe"]
                     if sa.stessa_squadra(r["squadra"], squadra_caso)]
        giusta = [r for r in candidate if r.get("entrante")
                  and sa.stessa_persona(r["entrante"], entrante)]
        if giusta:
            scelta = giusta[0]
            riga["esito"] = ESITO_PRESENTE
        elif candidate:
            scelta = candidate[0]
            riga["esito"] = ESITO_ENTRANTE_DIVERSO
        else:
            scelta = None
            riga["esito"] = ESITO_NON_TROVATO
        riga["entrante_wikipedia"] = scelta.get("entrante") if scelta else None
        riga["data_wikipedia"] = scelta.get("data_cambio") if scelta else None
        riga["data_coincide"] = (None if not scelta or not riga["data_file"]
                                 else riga["data_file"] == scelta.get("data_cambio"))
        esiti.append(riga)
    return esiti


def cambi_fuori_dal_file(leghe_lette: dict, casi: list) -> list:
    """I cambi letti su Wikipedia che NON corrispondono a nessun caso del file."""
    fuori = []
    for lega in LEGHE:
        lettura = leghe_lette.get(lega) or {}
        for riga in lettura.get("righe") or []:
            coperta = False
            for caso in casi or []:
                if caso.get("lega") != lega:
                    continue
                entrante = caso.get("allenatore_entrante") or caso.get("allenatore_atteso")
                if sa.stessa_squadra(riga["squadra"], caso.get("squadra")) and \
                        (not riga.get("entrante") or sa.stessa_persona(riga["entrante"], entrante)):
                    coperta = True
                    break
            if not coperta:
                fuori.append({"lega": lega, **riga})
    return fuori


def giudizio(leghe_lette: dict, esiti: list) -> dict:
    """La regola dichiarata: 5 leghe lette + tutti i casi presenti con l'entrante giusto."""
    mancanti = [l for l in LEGHE if not (leghe_lette.get(l) or {}).get("letta")]
    if mancanti:
        return {"valutabile": False, "passa": False,
                "motivi": ["non valutabile: leghe mancanti " + ", ".join(mancanti)]}
    valutabili = [e for e in esiti if e["esito"] != ESITO_LEGA_NON_LETTA]
    motivi = []
    if len(valutabili) < MIN_CASI_PUBBLICI:
        motivi.append(f"casi valutabili {len(valutabili)} (servono almeno {MIN_CASI_PUBBLICI})")
    non_ok = [e for e in valutabili if e["esito"] != ESITO_PRESENTE]
    if non_ok:
        motivi.append(f"{len(non_ok)} casi su {len(valutabili)} non presenti con l'entrante giusto")
    return {"valutabile": True, "passa": not motivi, "motivi": motivi}


# ---------------------------------------------------------------------------
# Scrittura (snapshot e referto)
# ---------------------------------------------------------------------------
def _nome_libero(cartella: str, giorno: str, prefisso: str) -> str:
    candidati = [os.path.join(cartella, f"{prefisso}{giorno}.json")]
    candidati += [os.path.join(cartella, f"{prefisso}{giorno}_{i:02d}.json") for i in range(2, 100)]
    for percorso in candidati:
        if not os.path.exists(percorso):
            return percorso
    raise RuntimeError(f"{cartella}: troppi file per il giorno {giorno}")


def testo_casi_file(percorso_casi: str) -> tuple:
    """Versione e data dei casi, e i casi esclusi dichiarati nel file."""
    if not percorso_casi or not os.path.exists(percorso_casi):
        return None, None, []
    with open(percorso_casi, "r", encoding="utf-8") as fh:
        dati = json.load(fh)
    return dati.get("versione"), dati.get("raccolti_il"), dati.get("esclusi") or []


def testo_referto(misure: dict, esiti: list, fuori: list, esito: dict, note: list) -> str:
    """Il referto: REGOLA prima dei numeri, poi leghe, casi, cambi in più."""
    r = []
    r.append("# Sonda allenatori — fonte alternativa: Wikipedia (sola lettura)")
    r.append("")
    if misure.get("modalita") == "fixture":
        r.append("**Run di PROVA con pagine FINTE (`--fixture`)**: mostra che il giro "
                 "funziona, NON lo stato di Wikipedia. Nessun numero qui e' una misura.")
        r.append("")
    if misure.get("modalita") == "non eseguita":
        r.append("**Sonda non eseguita: nessuna richiesta a Wikipedia.** Questo referto "
                 "dichiara la regola e i casi pubblici; le colonne «su Wikipedia» sono "
                 "«da misurare». Lo misura il workflow `audit_allenatori.yml`, job "
                 "«Sonda allenatori Wikipedia».")
        r.append("")
    r.append(f"Run: **{misure.get('quando')}** · lingua: **{LINGUA}** "
             f"(en.wikipedia.org) · stagione: **{STAGIONE}** · richieste API: "
             f"**{misure.get('chiamate', 0)}**.")
    r.append("")
    r.append("## Regola dichiarata (prima dei numeri)")
    r.append("")
    r.append("La regola si valuta solo se **tutte e 5 le leghe** sono state lette per "
             "intero (tabella «Managerial changes» trovata e tutte le righe lette). "
             "Altrimenti: «non valutabile: leghe mancanti <elenco>», senza giudizio.")
    r.append("")
    r.append(f"Con le 5 leghe lette, la regola **passa** solo se **tutti** i casi pubblici "
             f"di `casi_pubblici_2026_27.json` (almeno {MIN_CASI_PUBBLICI} valutabili) "
             f"risultano presenti nella tabella di Wikipedia **con l'allenatore entrante "
             f"giusto**. La data non e' parte della regola: le differenze sono riportate "
             f"a parte. I cambi su Wikipedia che non sono nel file dei casi sono elencati "
             f"in fondo, senza giudizio.")
    r.append("")
    if not esito["valutabile"]:
        r.append("Esito di questo run: **NON VALUTABILE** — " + "; ".join(esito["motivi"]) + ".")
    elif esito["passa"]:
        r.append("Esito di questo run: **PASSA** — tutti i casi pubblici presenti con "
                 "l'entrante giusto.")
    else:
        r.append("Esito di questo run: **NON PASSA** — " + "; ".join(esito["motivi"]) + ".")
    r.append("")
    r.append("## Leghe lette")
    r.append("")
    r.append("| Lega | Letta per intero | Titolo pagina | Revisione | Righe lette | Non lette | Nota |")
    r.append("|---|---|---|---|---|---|---|")
    for lega in LEGHE:
        l = (misure.get("leghe_lette") or {}).get(lega) or {}
        if misure.get("modalita") == "non eseguita":
            r.append(f"| {lega} | da misurare | — | — | — | — | — |")
            continue
        r.append(f"| {lega} | {'sì' if l.get('letta') else '**no**'} | "
                 f"{l.get('titolo') or '—'} | {l.get('revid') or '—'} | "
                 f"{len(l.get('righe') or [])} | {len(l.get('illeggibili') or [])} | "
                 f"{l.get('nota') or '—'} |")
    r.append("")
    r.append("## Casi pubblici su Wikipedia")
    r.append("")
    if not esiti:
        r.append("_Nessun caso pubblico nel file._")
    else:
        r.append("| Lega | Squadra | Entrante (file) | Entrante (Wikipedia) | Data file | "
                 "Data Wikipedia | Data coincide | Esito |")
        r.append("|---|---|---|---|---|---|---|---|")
        for e in esiti:
            coincide = {True: "sì", False: "**no**", None: "—"}[e.get("data_coincide")]
            r.append(f"| {e.get('lega')} | {e.get('squadra')} | "
                     f"{e.get('allenatore_entrante') or e.get('allenatore_atteso') or '—'} | "
                     f"{e.get('entrante_wikipedia') or '—'} | {e.get('data_file') or '—'} | "
                     f"{e.get('data_wikipedia') or '—'} | {coincide} | **{e.get('esito')}** |")
    r.append("")
    r.append("## Cambi su Wikipedia che NON sono nel file dei casi")
    r.append("")
    if not fuori:
        r.append("_Nessuno (o leghe non lette)._")
    else:
        r.append("| Lega | Squadra | Uscente | Uscita | Data cambio | Entrante | Data nomina |")
        r.append("|---|---|---|---|---|---|---|")
        for c in fuori:
            r.append(f"| {c['lega']} | {c['squadra']} | {c['uscente']} | {c.get('uscita') or '—'} | "
                     f"{c.get('data_cambio') or c.get('data_cambio_testo') or '—'} | "
                     f"{c.get('entrante') or '—'} | {c.get('data_nomina') or '—'} |")
    r.append("")
    if note:
        r.append("## Note del run")
        r.append("")
        for n in note:
            r.append(f"* {n}")
        r.append("")
    r.append("## Come e' stata prodotta questa sonda")
    r.append("")
    r.append(f"* API MediaWiki (`action=parse`, `prop=text|revid`), una pagina per lega, "
             f"pagina `{STAGIONE}_<lega>` in inglese; titolo alternativo con trattino `-` "
             f"se il primo non esiste;")
    r.append(f"* User-Agent dichiarato: `{USER_AGENT}`; nessuna chiave; "
             f"una richiesta alla volta, pausa {PAUSA_SECONDI:.0f} s, `maxlag=5`, al massimo "
             f"{TENTATIVI_RETE} nuovi tentativi su 429/5xx;")
    r.append("* sola lettura: nessuna scrittura in `SoccerMath/`, nessuna modifica all'app.")
    return "\n".join(r) + "\n"


def misura_pagine(leghe: list, session=None, sleep=time.sleep,
                  pagine: Optional[dict] = None) -> tuple:
    """Legge le pagine (o usa quelle di prova) e ritorna ``(letture, chiamate, note)``.

    ``chiamate`` conta le richieste API reali (0 con le pagine di prova).
    """
    letture, note, richieste = {}, [], []
    for lega in leghe:
        try:
            if pagine is not None:
                pagina = pagine[lega]
            else:
                pagina = scarica_pagina(lega, session=session, sleep=sleep, contatore=richieste)
                sleep(PAUSA_SECONDI)
        except Exception as errore:          # una lega non ferma le altre
            letture[lega] = {"lega": lega, "letta": False, "righe": [], "illeggibili": [],
                             "nota": f"errore: {type(errore).__name__}: {errore}"}
            note.append(f"{lega}: errore nella lettura di Wikipedia "
                        f"({type(errore).__name__}: {errore}).")
            continue
        letture[lega] = leggi_lega(lega, pagina)
    return letture, len(richieste), note


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Sonda allenatori da Wikipedia (sola lettura)")
    parser.add_argument("--leagues", nargs="*", default=None)
    parser.add_argument("--casi", default=DEFAULT_CASI)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--results-dir", default=None)
    parser.add_argument("--fixture", default=None,
                        help="pagine finte in JSON: {\"leghe\": {\"Serie A\": {titolo, revid, "
                             "html}}}; nessuna rete, prefisso fixture_")
    parser.add_argument("--referto-non-eseguito", action="store_true",
                        help="scrive il referto «non eseguita» (regola, casi, «da misurare»)")
    args = parser.parse_args(argv)

    leghe = args.leagues or list(LEGHE)
    sconosciute = [l for l in leghe if l not in LEGHE]
    if sconosciute:
        print(f"leghe non riconosciute: {sconosciute}; ammesse: {list(LEGHE)}")
        return 1
    quando = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    giorno = quando[:10]
    casi = sa.carica_casi(args.casi)
    versione_casi, raccolti, esclusi = testo_casi_file(args.casi)
    results_dir = args.results_dir or DEFAULT_RESULTS_DIR

    if args.referto_non_eseguito:
        os.makedirs(results_dir, exist_ok=True)
        referto = os.path.join(results_dir, "sonda_allenatori_wikipedia.md")
        misure = {"quando": quando, "modalita": "non eseguita", "chiamate": 0,
                  "leghe_lette": {}}
        esiti = [dict(c, esito="da misurare", data_file=c.get("data_cambio"),
                      entrante_wikipedia=None, data_wikipedia=None, data_coincide=None)
                 for c in casi]
        esito = {"valutabile": False, "passa": False,
                 "motivi": ["sonda non eseguita"]}
        with open(referto, "w", encoding="utf-8") as fh:
            fh.write(testo_referto(misure, esiti, [], esito, []))
        print(f"MODALITA=non eseguita REFERTO={referto}")
        return 0

    if args.fixture:
        with open(args.fixture, "r", encoding="utf-8") as fh:
            fixture = json.load(fh)
        pagine = fixture.get("leghe") or {}
        modalita = "fixture"
        letture, chiamate, note = misura_pagine(leghe, pagine=pagine)
        prefisso = PREFISSO_FIXTURE
        out_dir = args.out_dir or DEFAULT_OUT_DIR_FIXTURE
        results_dir = args.results_dir or DEFAULT_OUT_DIR_FIXTURE
    else:
        modalita = "rete"
        letture, chiamate, note = misura_pagine(leghe)
        prefisso = ""
        out_dir = args.out_dir or DEFAULT_OUT_DIR

    lette = [l for l in leghe if letture.get(l, {}).get("letta")]
    if modalita == "rete" and not lette:
        print("ERRORE: nessuna lega letta da Wikipedia: nessuno snapshot, nessun referto.")
        for n in note:
            print(f"  - {n}")
        return 2

    esiti = confronta_casi(casi, letture)
    fuori = cambi_fuori_dal_file(letture, casi)
    esito = giudizio(letture, esiti)
    misure = {"quando": quando, "modalita": modalita, "chiamate": chiamate,
              "leghe_lette": letture}
    snapshot = {
        "versione": "allenatori_wikipedia_v1",
        "quando": quando,
        "lingua": LINGUA,
        "stagione": STAGIONE,
        "modalita": modalita,
        "user_agent": USER_AGENT,
        "chiamate": chiamate,
        "leghe": {l: {k: v for k, v in letture[l].items()} for l in letture},
        "esiti_casi": esiti,
        "cambi_fuori_dal_file": fuori,
        "esito": esito,
        "casi_versione": versione_casi,
        "casi_raccolti_il": raccolti,
        "casi_esclusi": esclusi,
    }
    testo_snap = json.dumps(snapshot, ensure_ascii=False, indent=2)
    os.makedirs(out_dir, exist_ok=True)
    percorso = _nome_libero(out_dir, giorno, prefisso)
    with open(percorso, "w", encoding="utf-8") as fh:
        fh.write(testo_snap + "\n")
    os.makedirs(results_dir, exist_ok=True)
    referto = os.path.join(results_dir, f"{prefisso}sonda_allenatori_wikipedia.md")
    with open(referto, "w", encoding="utf-8") as fh:
        fh.write(testo_referto(misure, esiti, fuori, esito, note))
    print(f"LETTE={len(lette)}/{len(leghe)} CHIAMATE={chiamate}")
    print(f"VALUTABILE={esito['valutabile']} PASSA={esito['passa']}")
    print(f"FILE={percorso}")
    print(f"REFERTO={referto}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
