#!/usr/bin/env python3
"""sonda_allenatori.py — allenatori dalle API football-data.org v4 (SOLA LETTURA).

DOMANDA. Si puo' mettere l'allenatore nella scheda partita? Prima bisogna sapere
se la fonte lo sa, e QUANTO e' aggiornata. Questa sonda misura due cose, per le
5 leghe del progetto:

1. **copertura**: quante squadre hanno un allenatore con nome nella risposta
   dell'API (`GET /v4/competitions/{codice}/teams` per l'elenco, poi
   `GET /v4/teams/{id}` per ogni squadra: e' li' che stanno `coach.name`,
   `coach.contract.start` e `coach.contract.until`);
2. **aggiornamento**: per i cambi di allenatore 2026/27 verificati su fonti
   pubbliche (file ``audit/data/allenatori/casi_pubblici_2026_27.json``), l'API
   riporta gia' l'allenatore entrante o quello uscente?

REGOLA DICHIARATA (scritta PRIMA dei numeri nel referto, come i referti PR #64):
l'allenatore entra nella scheda partita **solo se** la copertura e' almeno
``SOGLIA_COPERTURA`` (95%) e **tutti** i casi verificati risultano aggiornati.
Altrimenti la scheda non mostra l'allenatore e lo dichiara ("dato non
affidabile"), indicando le fonti alternative.

CHIAVE E LIMITI
* la chiave arriva dall'ambiente (``FOOTBALL_DATA_API_KEY``/``API_KEY_DATA`` o
  dal secret di Streamlit usato da ``config``): viaggia nell'header
  ``X-Auth-Token``, **mai** nell'URL, mai stampata, e ``scrivi_json`` rifiuta di
  scrivere un file che contenga la chiave;
* piano gratuito football-data.org: **10 chiamate al minuto**. Il contatore
  ``FinestraChiamate`` aspetta da solo quando serve (orologio e ``sleep``
  iniettabili, cosi' i test girano in 0 secondi);
* **nessuna scrittura** dentro ``SoccerMath/`` e nessuna modifica all'app: i
  file finiscono in ``audit/data/allenatori/`` (snapshot) e
  ``audit/results/`` (referto).

QUALE FILE DOVE (importante)
* un run di **rete** scrive ``audit/data/allenatori/<giorno>.json`` **solo se
  almeno una lega e' arrivata in fondo** (almeno una chiamata riuscita): se
  tutte le chiamate falliscono lo script esce con errore e NON scrive nulla
  (ne' snapshot ne' referto), cosi' non resta in giro un file con la data che
  sembra un risultato;
* un run ``--fixture`` (risposte finte, prove e test) scrive SEMPRE con il
  prefisso ``fixture_`` (``fixture_<giorno>.json``, ``fixture_sonda_allenatori.md``)
  e, senza ``--out-dir``/``--results-dir`` espliciti, dentro ``audit/output/``
  (cartella NON versionata): una risposta finta non puo' mai finire in
  ``audit/data/allenatori/<giorno>.json`` e passare per uno snapshot reale;
* ``--referto-non-eseguito`` scrive il referto nello stato "sonda non
  eseguita" (regola dichiarata, casi pubblici con la fonte, colonna
  "Allenatore nelle API" = "da misurare"): serve a tenere il referto della PR
  senza inventare numeri, e non fa nessuna chiamata.

Uso::

    python audit/sonda_allenatori.py [--stagione 2026] [--leagues ...]
                                     [--out-dir DIR] [--results-dir DIR]
                                     [--casi FILE] [--max-calls-per-minute 10]
                                     [--fixture FILE] [--keep-going]
                                     [--referto-non-eseguito]

``--fixture`` gira SENZA RETE su risposte finte (test e prove): il referto lo
dichiara in testa ("RUN DI PROVA") e i file portano il prefisso ``fixture_``.

Code di uscita: 0 = sonda riuscita su tutte le leghe chieste; 1 = almeno una
lega fallita (con ``--keep-going`` le altre vengono comunque salvate); 2 =
nessuna chiamata riuscita (niente file scritti); 3 = chiave assente (e nessuna
fixture).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOCCERMATH_DIR = os.path.join(REPO_ROOT, "SoccerMath")
if SOCCERMATH_DIR not in sys.path:
    sys.path.insert(0, SOCCERMATH_DIR)

API_BASE = "https://api.football-data.org/v4"
MAX_CHIAMATE_AL_MINUTO = 10          # limite dichiarato del piano gratuito
SOGLIA_COPERTURA = 0.95              # regola della scheda partita
STATUS_INTERROMPI = {401, 403, 429}  # chiave non valida / limite di quota

DEFAULT_OUT_DIR = os.path.join(REPO_ROOT, "audit", "data", "allenatori")
DEFAULT_RESULTS_DIR = os.path.join(REPO_ROOT, "audit", "results")
DEFAULT_CASI = os.path.join(DEFAULT_OUT_DIR, "casi_pubblici_2026_27.json")

#: Dove scrive un run ``--fixture`` senza ``--out-dir``: cartella NON versionata
#: (``audit/output/`` e' in ``.gitignore``), cosi' una risposta finta non puo'
#: finire nell'albero dei file versionati.
DEFAULT_OUT_DIR_FIXTURE = os.path.join(REPO_ROOT, "audit", "output", "sonda_allenatori")
#: Prefisso OBBLIGATORIO dei file di un run ``--fixture``: ``fixture_<giorno>.json``
#: e ``fixture_sonda_allenatori.md``. Il nome senza prefisso resta del solo run
#: di rete.
PREFISSO_FIXTURE = "fixture_"

#: Le 5 leghe del progetto: nome di vista -> codice competizione football-data.
LEGHE = {
    "Serie A": "SA",
    "Premier League": "PL",
    "La Liga": "PD",
    "Bundesliga": "BL1",
    "Ligue 1": "FL1",
}

ESITO_AGGIORNATO = "aggiornato"
ESITO_NON_AGGIORNATO = "non aggiornato"
ESITO_SQUADRA_ASSENTE = "squadra non nel run"
ESITO_SENZA_ALLENATORE = "api senza allenatore"
MIN_CASI_PUBBLICI = 3               # sotto questa soglia la verifica non dice nulla


# ---------------------------------------------------------------------------
# Chiave e rete (solo questi punti toccano l'esterno)
# ---------------------------------------------------------------------------
#: Tentativi DOPO il primo, per una stessa chiamata, quando la risposta e' 429.
#: Totale massimo per chiamata: 1 + 3 = 4 richieste (dichiarato nel referto).
MAX_NUOVI_TENTATIVI_429 = 3
#: Attesa su 429 se l'header X-RequestCounter-Reset non c'e' o non e' valido.
ATTESA_429_DEFAULT = 60.0


class Limite429(RuntimeError):
    """HTTP 429 da football-data.org: si puo' riprovare, con l'attesa dell'header."""

    def __init__(self, headers: dict):
        super().__init__("HTTP 429 da football-data.org (limite di richieste al "
                         "minuto raggiunto)")
        self.headers = headers


def leggi_chiave(env=None) -> str:
    """La chiave dall'ambiente, senza mai stamparla.

    Ordine: ``FOOTBALL_DATA_API_KEY``, ``API_KEY_DATA``, poi ``config`` (che
    legge la stessa variabile o i secret di Streamlit). Stringa vuota = assente.
    """
    env = os.environ if env is None else env
    for nome in ("FOOTBALL_DATA_API_KEY", "API_KEY_DATA"):
        valore = (env.get(nome) or "").strip()
        if valore:
            return valore
    try:
        import config  # import locale: la sonda gira anche senza Streamlit
        return str(getattr(config, "API_KEY_DATA", "") or "").strip()
    except Exception:
        return ""


def headers_minuscoli(risposta) -> dict:
    """Gli header della risposta con i nomi in minuscolo (confronto senza maiuscole)."""
    grezzi = getattr(risposta, "headers", None) or {}
    try:
        return {str(k).lower(): v for k, v in dict(grezzi).items()}
    except Exception:
        return {}


def secondi_da_header(valore, default: float = ATTESA_429_DEFAULT) -> float:
    """Un header di attesa in secondi (``X-RequestCounter-Reset``), o il default."""
    try:
        secondi = float(str(valore).strip())
    except (TypeError, ValueError):
        return default
    return secondi if secondi > 0 else default


def http_get_risposta(url: str, chiave: str, parametri=None, session=None,
                      timeout=20):
    """Una richiesta GET. Ritorna ``(payload, header)``.

    Con 429 solleva ``Limite429`` (la chiamata si puo' ripetere); con 401/403
    solleva ``RuntimeError`` senza tentativi (chiave non valida). Nessun URL con
    la chiave, nessun log suo.
    """
    import requests

    sessione = session or requests
    risposta = sessione.get(url, headers={"X-Auth-Token": chiave},
                            params=parametri or {}, timeout=timeout)
    intestazioni = headers_minuscoli(risposta)
    if risposta.status_code == 429:
        raise Limite429(intestazioni)
    if risposta.status_code in (401, 403):
        raise RuntimeError(f"HTTP {risposta.status_code} da football-data.org: "
                           "chiave non valida (nessun dettaglio stampato per non "
                           "esporre la chiave)")
    risposta.raise_for_status()
    return risposta.json(), intestazioni


def http_get(url: str, chiave: str, parametri=None, session=None, timeout=20) -> dict:
    """GET senza ripetizioni (compatibilita'): ritorna solo il payload."""
    try:
        payload, _ = http_get_risposta(url, chiave, parametri, session, timeout)
    except Limite429 as errore:
        raise RuntimeError(f"{errore} (chiave non valida o quota esaurita; "
                           "nessun dettaglio stampato per non esporre la chiave)")
    return payload


class FinestraChiamate:
    """Al massimo ``max_chiamate`` richieste in OGNI finestra di ``secondi``.

    La finestra e' chiusa: una richiesta a distanza esattamente di 60 s dalla
    precedente conta ancora nella stessa finestra. Cosi' in qualunque intervallo
    di 60 s ci sono al massimo ``max_chiamate`` richieste (non 11).

    Tutte le richieste passano di qui, anche l'elenco squadre e i tentativi
    ripetuti dopo un 429. ``orologio`` e ``dormi`` sono iniettabili: i test
    verificano l'attesa senza aspettare davvero.
    """

    def __init__(self, max_chiamate: int = MAX_CHIAMATE_AL_MINUTO,
                 secondi: float = 60.0, orologio=time.monotonic, dormi=time.sleep):
        # almeno 1: con 0 la finestra non si libererebbe mai (attesa infinita)
        self.max_chiamate = max(1, int(max_chiamate))
        self.secondi = float(secondi)
        self._orologio = orologio
        self._dormi = dormi
        self._istanti: list = []
        self.attese = 0          # quante volte si e' aspettato per far posto nella finestra
        self.attese_429 = 0      # quante volte si e' aspettato dopo un 429
        self.attese_header = 0   # quante volte perche' X-Requests-Available-Minute era 0
        self.chiamate = 0        # richieste effettive (anche quelle ripetute dopo un 429)
        self.riprovate = 0       # richieste ripetute dopo un 429

    def attendi(self) -> float:
        """Blocca finche' c'e' posto nella finestra; ritorna i secondi attesi."""
        attesa = 0.0
        while True:
            adesso = self._orologio()
            self._istanti = [t for t in self._istanti if adesso - t <= self.secondi]
            if len(self._istanti) < self.max_chiamate:
                self._istanti.append(adesso)
                self.chiamate += 1
                return attesa
            pausa = self.secondi - (adesso - self._istanti[0]) + 0.01
            self.attese += 1
            attesa += max(pausa, 0.0)
            self._dormi(max(pausa, 0.0))

    def riposa(self, secondi: float, motivo: str = "429") -> None:
        """Attesa imposta dal server (429 o header di quota esaurita)."""
        if motivo == "429":
            self.attese_429 += 1
        else:
            self.attese_header += 1
        self._dormi(max(float(secondi), 0.0))


def durata_minima_secondi(chiamate: int, max_per_minuto: int, secondi: float = 60.0) -> float:
    """Durata MINIMA, in secondi, per fare ``chiamate`` richieste col tetto dato.

    Le prime ``max_per_minuto`` partono subito; ogni altra deve aspettare che si
    liberi un posto nella finestra: (n - L) intervalli da ``secondi / L``.
    Esempio: 100 chiamate a 10 al minuto -> 90 * 6 s = 540 s = 9 minuti.
    Non include le attese dei 429 (quelle si sommano e si contano a parte).
    """
    limite = max(1, int(max_per_minuto))
    n = max(0, int(chiamate))
    if n <= limite:
        return 0.0
    return (n - limite) * float(secondi) / limite


def chiama(url: str, chiave: str, finestra: FinestraChiamate, parametri=None,
           session=None, max_nuovi_tentativi: int = MAX_NUOVI_TENTATIVI_429):
    """Una chiamata REALE, col limite di finestra e i nuovi tentativi su 429.

    Ogni tentativo passa dalla finestra (conta come richiesta). Su 429: attesa
    del tempo di ``X-RequestCounter-Reset`` (o 60 s), poi un nuovo tentativo; al
    massimo ``max_nuovi_tentativi`` per chiamata. Dopo l'ultimo 429 la chiamata
    fallisce con RuntimeError. Se ``X-Requests-Available-Minute`` e' 0 in una
    risposta riuscita, si aspetta il reset PRIMA della richiesta successiva.
    """
    tentativi_ripetuti = 0
    while True:
        finestra.attendi()
        try:
            payload, intestazioni = http_get_risposta(url, chiave, parametri,
                                                      session=session)
        except Limite429 as errore:
            if tentativi_ripetuti >= max_nuovi_tentativi:
                raise RuntimeError(f"HTTP 429 da football-data.org dopo "
                                   f"{tentativi_ripetuti} nuovi tentativi: "
                                   "chiamata saltata (limite di richieste al minuto)")
            tentativi_ripetuti += 1
            finestra.riprovate += 1
            finestra.riposa(secondi_da_header(
                errore.headers.get("x-requestcounter-reset")), motivo="429")
            continue
        disponibili = intestazioni.get("x-requests-available-minute")
        if disponibili is not None:
            try:
                if int(str(disponibili).strip()) <= 0:
                    finestra.riposa(secondi_da_header(
                        intestazioni.get("x-requestcounter-reset")), motivo="header")
            except ValueError:
                pass
        return payload


# ---------------------------------------------------------------------------
# Lettura delle risposte (funzioni pure: nessuna rete)
# ---------------------------------------------------------------------------
def data_leggibile(valore):
    """Una data di contratto come arriva dalle API, normalizzata.

    football-data usa ``AAAA-MM-GG`` per ``contract.start`` e ``AAAA-MM`` per
    ``contract.until`` (verificato sulle risposte di prova): qui si tiene il
    valore grezzo e si dichiara la forma (``giorno``/``mese``), senza inventare
    giorni che la fonte non da'.
    """
    if valore is None:
        return None, None
    testo = str(valore).strip()
    if not testo:
        return None, None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", testo):
        return testo, "giorno"
    if re.fullmatch(r"\d{4}-\d{2}", testo):
        return testo, "mese"
    if re.fullmatch(r"\d{4}", testo):
        return testo, "anno"
    return testo, "altro"


def contratto(payload_contratto) -> dict:
    """``{"dal": ..., "fino": ..., "forme": {...}}`` dal blocco ``contract``."""
    blocco = payload_contratto if isinstance(payload_contratto, dict) else {}
    dal, forma_dal = data_leggibile(blocco.get("start"))
    fino, forma_fino = data_leggibile(blocco.get("until"))
    forme = []
    if forma_dal:
        forme.append(f"inizio: {forma_dal}")
    if forma_fino:
        forme.append(f"fine: {forma_fino}")
    return {"dal": dal, "fino": fino, "forme": forme}


def allenatore_da_teams(payload: dict, when: str) -> list:
    """Le squadre di ``/competitions/{cod}/teams`` (id e nome: nessun altro uso).

    Serve solo l'elenco: l'allenatore lo porta la chiamata per squadra.
    """
    squadre = []
    for voce in (payload or {}).get("teams") or []:
        if not isinstance(voce, dict) or voce.get("id") is None:
            continue
        squadre.append({"id": voce.get("id"), "nome": voce.get("name"),
                        "rilevato_il": when})
    return squadre


def allenatore_da_squadra(payload: dict, when: str) -> dict:
    """``coach`` di ``/teams/{id}`` -> voce salvata (tutto puo' essere None)."""
    allenatore = (payload or {}).get("coach")
    if not isinstance(allenatore, dict):
        return {"allenatore": None, "allenatore_id": None,
                "contratto_dal": None, "contratto_fino": None,
                "forme_date": [], "rilevato_il": when}
    cont = contratto(allenatore.get("contract"))
    return {
        "allenatore": (allenatore.get("name") or None),
        "allenatore_id": allenatore.get("id"),
        "contratto_dal": cont["dal"],
        "contratto_fino": cont["fino"],
        "forme_date": cont["forme"],
        "rilevato_il": when,
    }


def normalizza_nome(nome) -> str:
    """Nome confrontabile: senza accenti, spazi doppi, punti e trattini."""
    testo = str(nome or "")
    testo = "".join(c for c in unicodedata.normalize("NFKD", testo)
                    if not unicodedata.combining(c))
    testo = testo.replace("-", " ").replace(".", " ")
    return re.sub(r"\s+", " ", testo).strip().lower()


def parole_informative(nome) -> list:
    """Le parole di un nome con almeno 3 lettere (le iniziali non contano)."""
    return [p for p in normalizza_nome(nome).split() if len(p) >= 3]


def cognome(nome) -> str:
    """L'ultima parola informativa: il cognome, per come scrivono le fonti."""
    parole = parole_informative(nome)
    return parole[-1] if parole else ""


def stessa_persona(nome_api, nome_caso) -> bool:
    """True se i due nomi indicano la stessa PERSONA.

    Le API scrivono il nome per esteso ("Alexander Blessin"), le fonti spesso il
    solo cognome ("Blessin"): qui conta il cognome (ultima parola informativa).
    Nessuna somiglianza approssimata: "Paolo Vanoli Rossi" NON e' "Vanoli".
    """
    a, b = normalizza_nome(nome_api), normalizza_nome(nome_caso)
    if not a or not b:
        return False
    return a == b or (cognome(nome_api) == cognome(nome_caso))


def stessa_squadra(nome_api, nome_caso) -> bool:
    """True se i due nomi indicano la stessa SQUADRA.

    Le API aggiungono ragioni sociali e anni ("Bologna FC 1909", "ACF
    Fiorentina"): basta che le parole del nome piu' corto compaiano nell'altro
    ("Bologna" dentro "Bologna FC 1909"). Nessun confronto per somiglianza.
    """
    a, b = normalizza_nome(nome_api), normalizza_nome(nome_caso)
    if not a or not b:
        return False
    if a == b:
        return True
    pa, pb = parole_informative(nome_api), parole_informative(nome_caso)
    if not pa or not pb:
        return False
    corto, lungo = (pa, pb) if len(pa) <= len(pb) else (pb, pa)
    return all(p in lungo for p in corto)


def giorni_tra(data_iniziale, quando) -> "int | None":
    """Giorni interi fra una data ``AAAA-MM-GG`` e l'istante del run (UTC).

    None se una delle due non si legge: nessun giorno inventato.
    """
    try:
        inizio = datetime.strptime(str(data_iniziale or "")[:10], "%Y-%m-%d").date()
        fine = datetime.strptime(str(quando or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (fine - inizio).days


def confronta_casi(casi: list, squadre_per_lega: dict, when: str) -> list:
    """Per ogni caso pubblico: che allenatore riporta l'API?

    ``squadre_per_lega`` = {lega: [voce squadra]}. Gli esiti sono quattro,
    dichiarati: aggiornato / non aggiornato / squadra non nel run / api senza
    allenatore. Nessun caso viene saltato in silenzio.
    """
    fuori = []
    for caso in casi or []:
        lega = caso.get("lega")
        squadra_caso = caso.get("squadra")
        voca = None
        for voce in squadre_per_lega.get(lega) or []:
            if stessa_squadra(voce.get("nome"), squadra_caso):
                voca = voce
                break
        riga = dict(caso)
        riga["rilevato_il"] = when
        # Eta' del caso: giorni fra la data del cambio e il run. Un «non
        # aggiornato» dopo 1 giorno e uno dopo 30 non dicono la stessa cosa.
        riga["eta_giorni"] = giorni_tra(caso.get("data_cambio") or caso.get("data"), when)
        if voca is None:
            riga.update({"esito": ESITO_SQUADRA_ASSENTE, "allenatore_api": None})
        elif not voca.get("allenatore"):
            riga.update({"esito": ESITO_SENZA_ALLENATORE, "allenatore_api": None})
        else:
            riga["allenatore_api"] = voca["allenatore"]
            # il file dei casi pubblici usa "allenatore_atteso": qui si
            # accettano entrambi i nomi, la sostanza non cambia
            entrante = caso.get("allenatore_entrante") or caso.get("allenatore_atteso")
            uscente = caso.get("allenatore_uscente")
            if stessa_persona(voca["allenatore"], entrante):
                riga["esito"] = ESITO_AGGIORNATO
                riga["dettaglio"] = f"l'API riporta l'entrante ({entrante})"
            elif uscente and stessa_persona(voca["allenatore"], uscente):
                riga["esito"] = ESITO_NON_AGGIORNATO
                riga["dettaglio"] = (f"l'API riporta ancora l'uscente ({uscente}); "
                                     f"atteso: {entrante}")
            else:
                riga["esito"] = ESITO_NON_AGGIORNATO
                riga["dettaglio"] = (f"l'API riporta un nome diverso da entrambi "
                                     f"(atteso: {entrante})")
        fuori.append(riga)
    return fuori


def copertura(squadre_per_lega: dict) -> dict:
    """Numeri dichiarati: per lega e globali, con l'elenco di chi non ha coach."""
    per_lega, totale, con_allenatore, senza = {}, 0, 0, []
    for lega, voci in (squadre_per_lega or {}).items():
        con = [v for v in voci if v.get("allenatore")]
        per_lega[lega] = {"squadre": len(voci), "con_allenatore": len(con),
                          "senza": [v.get("nome") for v in voci if not v.get("allenatore")]}
        totale += len(voci)
        con_allenatore += len(con)
        senza.extend(f"{lega}: {v.get('nome')}" for v in voci if not v.get("allenatore"))
    frazione = (con_allenatore / totale) if totale else 0.0
    return {"per_lega": per_lega, "squadre": totale, "con_allenatore": con_allenatore,
            "frazione": frazione, "percentuale": frazione, "soglia": SOGLIA_COPERTURA,
            "senza_allenatore": senza}


def forme_date(squadre_per_lega: dict) -> dict:
    """Le forme di data viste davvero, contate (per il referto)."""
    conteggio: dict = {}
    for voci in (squadre_per_lega or {}).values():
        for voce in voci:
            for forma in voce.get("forme_date") or []:
                conteggio[forma] = conteggio.get(forma, 0) + 1
    return dict(sorted(conteggio.items()))


ESITI_VALUTABILI = (ESITO_AGGIORNATO, ESITO_NON_AGGIORNATO, ESITO_SENZA_ALLENATORE)


def casi_valutabili(casi: list) -> list:
    """I casi che il confronto ha davvero potuto giudicare.

    «squadra non nel run» NON conta: non e' ne' aggiornato ne' non aggiornato
    (la squadra non e' nelle leghe lette: non si sa niente di lei). Un caso «api
    senza allenatore» invece conta come non aggiornato: l'API non riporta
    l'entrante.
    """
    return [c for c in (casi or []) if c.get("esito") in ESITI_VALUTABILI]


def tutte_aggiornate(casi: list) -> bool:
    """True solo se ci sono casi valutabili E tutti sono ``aggiornato``."""
    valutabili = casi_valutabili(casi)
    if not valutabili:
        return False
    return all(c.get("esito") == ESITO_AGGIORNATO for c in valutabili)


def leghe_mancanti(cop: dict) -> list:
    """Le leghe delle 5 del progetto NON lette per intero (ordine di LEGHE).

    Una lega e' «letta» solo se la sua risposta e' arrivata in fondo: squadre
    presenti nel conteggio di copertura. Lega fallita = mancante.
    """
    per_lega = (cop or {}).get("per_lega") or {}
    return [l for l in LEGHE if not (per_lega.get(l) or {}).get("squadre")]


def giudizio(cop: dict, casi: list) -> dict:
    """Applica la regola dichiarata e spiega la decisione.

    1. Se NON tutte e 5 le leghe sono state lette per intero, la regola NON si
       valuta: ``valutabile`` False, motivo «non valutabile: leghe mancanti
       <elenco>», e nessuna percentuale confrontata con la soglia.
    2. Altrimenti: copertura >= 95% E tutti i casi valutabili «aggiornato»
       (almeno ``MIN_CASI_PUBBLICI`` valutabili). Le «squadra non nel run» non
       contano in nessuno dei due sensi.
    """
    mancanti = leghe_mancanti(cop)
    if mancanti:
        return {"valutabile": False, "copertura_ok": None, "casi_ok": None,
                "affidabile": False,
                "motivi": ["non valutabile: leghe mancanti " + ", ".join(mancanti)]}
    copertura_ok = cop["frazione"] >= SOGLIA_COPERTURA
    valutabili = casi_valutabili(casi)
    casi_ok = tutte_aggiornate(casi) and len(valutabili) >= MIN_CASI_PUBBLICI
    motivi = []
    if not copertura_ok:
        motivi.append(f"copertura {cop['frazione']:.1%} < {SOGLIA_COPERTURA:.0%}")
    if not valutabili:
        motivi.append("nessun caso verificabile")
    elif len(valutabili) < MIN_CASI_PUBBLICI:
        motivi.append(f"casi valutabili {len(valutabili)} (servono almeno "
                      f"{MIN_CASI_PUBBLICI})")
    mancati = [c for c in valutabili if c.get("esito") != ESITO_AGGIORNATO]
    if mancati:
        motivi.append(f"{len(mancati)} casi su {len(valutabili)} non aggiornati")
    return {"valutabile": True, "copertura_ok": copertura_ok, "casi_ok": casi_ok,
            "affidabile": bool(copertura_ok and casi_ok), "motivi": motivi}


# ---------------------------------------------------------------------------
# Scrittura (snapshot + referto)
# ---------------------------------------------------------------------------
def percorso_del_giorno(out_dir: str, giorno: str, suffisso: str = "",
                        prefisso: str = "") -> str:
    """``<out_dir>/<prefisso><giorno><suffisso>.json`` (prefisso ``fixture_``
    per i run con risposte finte: il nome senza prefisso e' del solo run di
    rete)."""
    return os.path.join(out_dir, f"{prefisso}{giorno}{suffisso}.json")


def scrivi_json(percorso: str, dati, chiavi_da_escludere=()) -> str:
    """Scrive JSON compatto; rifiuta il file se contiene una chiave API.

    Il controllo e' sulle chiavi passate (di norma quella in uso): se per un
    errore finissero nel testo, la sonda fallisce invece di committare un
    segreto.
    """
    testo = json.dumps(dati, ensure_ascii=False, indent=2)
    for chiave in chiavi_da_escludere or ():
        if chiave and str(chiave) in testo:
            raise RuntimeError("la chiave API sarebbe finita nel file salvato: "
                               "scrittura annullata")
    os.makedirs(os.path.dirname(os.path.abspath(percorso)) or ".", exist_ok=True)
    with open(percorso, "w", encoding="utf-8") as fh:
        fh.write(testo + "\n")
    return percorso


def scrivi_snapshot(out_dir: str, giorno: str, dati: dict, quando: str,
                    chiavi_da_escludere=(), prefisso: str = "") -> str:
    """Salva lo snapshot del giorno senza MAI sovrascrivere un file esistente.

    Il primo nome e' ``<prefisso><giorno>.json``; se esiste si passa a
    ``<prefisso><giorno>_02.json`` e cosi' via: un secondo run nello stesso
    giorno non cancella il primo. Con ``prefisso="fixture_"`` il file non puo'
    confondersi con lo snapshot di un run di rete.
    """
    candidati = [percorso_del_giorno(out_dir, giorno, prefisso=prefisso)]
    candidati += [percorso_del_giorno(out_dir, giorno, f"_{i:02d}", prefisso)
                  for i in range(2, 100)]
    for percorso in candidati:
        if not os.path.exists(percorso):
            dati = {**dati, "scritto_il": quando}
            return scrivi_json(percorso, dati,
                               chiavi_da_escludere=chiavi_da_escludere)
    raise RuntimeError(f"{out_dir}: troppi file per il giorno {giorno}")


def testo_referto(misure: dict, casi: list, esito: dict, note: list) -> str:
    """Il referto: regola PRIMA dei numeri, poi copertura, date e casi."""
    righe = []
    righe.append("# Sonda allenatori (football-data.org v4, sola lettura)")
    righe.append("")
    if misure.get("modalita") == "fixture":
        righe.append("**Run di PROVA con risposte FINTA (`--fixture`)**: quello che "
                     "segue mostra che il giro funziona, NON lo stato delle API. "
                     "I file di questo run portano il prefisso `fixture_` e (senza "
                     "cartelle esplicite) stanno in `audit/output/`, la cartella NON "
                     "versionata: nessuno di questi numeri e' uno snapshot con la "
                     "data, e nessun file `audit/data/allenatori/<giorno>.json` "
                     "viene scritto. Il run vero lo esegue il workflow manuale "
                     "`audit_allenatori.yml`.")
        righe.append("")
    righe.append(f"Run: **{misure['quando']}** · stagione dal run: "
                 f"**{misure['stagione'] or 'predefinita'}** · chiamate fatte: "
                 f"**{misure['chiamate']}**.")
    righe.append("")
    righe.append("## Regola dichiarata (prima dei numeri)")
    righe.append("")
    righe.append("L'allenatore entra nella scheda partita **solo se**:")
    righe.append("")
    righe.append("0. **tutte e 5 le leghe** sono state lette per intero (ogni "
                 "squadra della lega ha la sua risposta). Se una lega manca, la "
                 "regola NON si valuta: nessuna percentuale viene confrontata con "
                 "la soglia;")
    righe.append(f"1. la copertura delle squadre con allenatore e' almeno "
                 f"**{SOGLIA_COPERTURA:.0%}**;")
    righe.append("2. **tutti** i casi di cambio allenatore verificati su fonti "
                 "pubbliche risultano aggiornati nelle API (nessun caso «non "
                 "aggiornato», nessun caso «da verificare»). Un caso «squadra non "
                 "nel run» NON conta né come aggiornato né come non aggiornato; "
                 "servono almeno "
                 f"{misure.get('min_casi_pubblici') or MIN_CASI_PUBBLICI} casi "
                 "valutabili.")
    righe.append("")
    if not esito.get("valutabile"):
        righe.append("Esito di questo run: **NON VALUTABILE** — "
                     + "; ".join(esito["motivi"]) + ". La scheda NON mostra "
                     "l'allenatore e lo dichiara, rimandando alle fonti alternative "
                     "(sito del club, comunicati ufficiali).")
    else:
        righe.append("Esito di questo run: **" + ("AFFIDABILE" if esito["affidabile"]
                     else "NON AFFIDABILE") + "**"
                     + ("" if esito["affidabile"] else
                        " — motivi: " + "; ".join(esito["motivi"]))
                     + ". Se non e' affidabile la scheda NON mostra l'allenatore e lo "
                       "dichiara, rimandando alle fonti alternative (sito del club, "
                       "comunicati ufficiali).")
    righe.append("")
    righe.append("## Copertura (squadre con un allenatore nella risposta)")
    righe.append("")
    righe.append("| Lega | Squadre | Con allenatore | Senza | Letta per intero |")
    righe.append("|---|---|---|---|---|")
    letture = misure.get("copertura_per_lega") or {}
    for lega in LEGHE:
        numeri = letture.get(lega)
        if numeri is None:
            righe.append(f"| {lega} | — | — | — | **no** |")
        else:
            righe.append(f"| {lega} | {numeri['squadre']} | {numeri['con_allenatore']} | "
                         f"{len(numeri['senza'])} | sì |")
    righe.append(f"| **totale** | **{misure.get('squadre', 0)}** | "
                 f"**{misure.get('con_allenatore', 0)}** | "
                 f"**{len(misure.get('senza_allenatore') or [])}** |")
    righe.append("")
    if misure.get("senza_allenatore"):
        righe.append("Squadre senza allenatore nella risposta: "
                     + ", ".join(misure["senza_allenatore"]) + ".")
        righe.append("")
    righe.append("## Formato delle date di contratto")
    righe.append("")
    if misure.get("forme_date"):
        for forma, quante in misure["forme_date"].items():
            righe.append(f"* {forma}: {quante} campi.")
    else:
        righe.append("_Nessuna data di contratto nella risposta._")
    righe.append("")
    righe.append("Le date sono salvate **come arrivano** (nessun giorno inventato): "
                 "`contract.start` e `contract.until` restano le stringhe della "
                 "fonte, la forma e' dichiarata campo per campo.")
    righe.append("")
    righe.append("## Casi pubblici 2026/27: le API sono aggiornate?")
    righe.append("")
    righe.append(f"I casi vengono da `audit/data/allenatori/casi_pubblici_2026_27.json` "
                 f"(versione {misure.get('casi_versione') or 'n/d'}, "
                 f"{misure.get('casi_raccolti_il') or 'data n/d'}; solo i casi "
                 f"«verificabili»: un esonero senza sostituto certo non e' un caso, "
                 f"e' una nota).")
    righe.append("")
    for escluso in misure.get("casi_esclusi") or []:
        nome = escluso.get("squadra") or escluso.get("lega") or "caso"
        righe.append(f"* **{nome}** non e' un caso: {escluso.get('motivo')}")
    if misure.get("casi_esclusi"):
        righe.append("")
    valutabili_n = len(casi_valutabili(casi))
    righe.append(f"Casi nel file: **{len(casi)}**; valutabili in questo run: "
                 f"**{valutabili_n}** (servono almeno "
                 f"{misure.get('min_casi_pubblici') or MIN_CASI_PUBBLICI} casi "
                 f"valutabili e che TUTTI risultino aggiornati). L'età è in giorni "
                 f"fra la data del cambio e il giorno del run.")
    righe.append("")
    if not casi:
        righe.append("_Nessun caso pubblico disponibile._")
    else:
        righe.append("| Lega | Squadra | Uscente | Entrante | Data | Età (giorni) | "
                     "Allenatore nelle API | Esito | Fonte |")
        righe.append("|---|---|---|---|---|---|---|---|---|")
        for c in casi:
            eta = c.get("eta_giorni")
            righe.append(f"| {c.get('lega')} | {c.get('squadra')} | "
                         f"{c.get('allenatore_uscente') or '—'} | "
                         f"{c.get('allenatore_entrante') or c.get('allenatore_atteso') or '—'} | "
                         f"{c.get('data') or c.get('data_cambio') or '—'} | "
                         f"{eta if eta is not None else '—'} | "
                         f"{c.get('allenatore_api') or '—'} | **{c.get('esito')}** | "
                         f"[fonte]({c.get('fonte')}) |")
        righe.append("")
        for c in casi:
            if c.get("dettaglio"):
                righe.append(f"* {c.get('squadra')}: {c['dettaglio']}.")
        righe.append("")
    righe.append("## Come e' stata prodotta questa sonda")
    righe.append("")
    righe.append("* `GET /v4/competitions/{codice}/teams` (una chiamata per lega) e "
                 "`GET /v4/teams/{id}` (una per squadra): e' da quest'ultima che "
                 "arrivano `coach.name`, `coach.contract.start` e "
                 "`coach.contract.until`;")
    righe.append("* chiave nell'header `X-Auth-Token`, **mai** nell'URL, mai stampata;")
    righe.append("* sola lettura: nessuna scrittura in `SoccerMath/`, nessuna "
                 "modifica all'app, nessuna chiamata fatta dall'app;")
    righe.append(f"* limite: al massimo **{misure.get('max_per_minuto')} richieste in "
                 f"qualunque finestra di 60 secondi**, contando anche l'elenco "
                 f"squadre; header `X-Requests-Available-Minute` e "
                 f"`X-RequestCounter-Reset` letti quando presenti;")
    righe.append(f"* su 429: attesa del tempo dell'header `X-RequestCounter-Reset` "
                 f"(o 60 s) e un nuovo tentativo, **al massimo "
                 f"{MAX_NUOVI_TENTATIVI_429} per chiamata**;")
    righe.append(f"* richieste fatte: **{misure.get('chiamate')}** (di cui ripetute dopo "
                 f"un 429: {misure.get('riprovate', 0)}); attese per il limite: "
                 f"{misure.get('attese', 0)}; attese dopo un 429: "
                 f"{misure.get('attese_429', 0)}; attese per header di quota: "
                 f"{misure.get('attese_header', 0)};")
    righe.append(f"* durata minima teorica di queste richieste senza 429: "
                 f"**{misure.get('durata_minima_teorica')}**; durata reale del run: "
                 f"**{misure.get('durata_reale')}**;")
    if note:
        righe.append("")
        righe.append("## Note del run")
        righe.append("")
        for n in note:
            righe.append(f"* {n}")
    return "\n".join(righe) + "\n"


def testo_referto_non_eseguito(quando: str, percorso_casi: str) -> str:
    """Il referto quando la sonda NON e' mai stata eseguita.

    Niente numeri: la REGOLA dichiarata prima di tutto, i casi pubblici 2026/27
    con la fonte e la colonna «Allenatore nelle API» con «da misurare», cosa si
    deve lanciare per misurare. Nessun esito, nessuna copertura, nessuna riga
    «non aggiornato»: quei dati esistono solo dopo un run reale.
    """
    casi = carica_casi(percorso_casi)
    descrizione = descrizione_casi(percorso_casi)
    righe = []
    righe.append("# Sonda allenatori (football-data.org v4, sola lettura)")
    righe.append("")
    righe.append("**Sonda non eseguita: nessuna chiamata reale a football-data.org.** "
                 "Questo referto dichiara la regola e i casi pubblici raccolti con la "
                 "fonte; la colonna «Allenatore nelle API» e' «da misurare» perche' "
                 "nessuno l'ha ancora letta. Nessun numero qui e' un risultato.")
    righe.append("")
    righe.append(f"Referto generato il **{quando}** in modalita' «non eseguita» "
                 f"(`--referto-non-eseguito`): nessuna chiave API usata, nessuna "
                 f"cartella di snapshot creata, nessun file "
                 f"`audit/data/allenatori/<giorno>.json` scritto.")
    righe.append("")
    righe.append("## Regola dichiarata (prima dei numeri)")
    righe.append("")
    righe.append("L'allenatore entra nella scheda partita **solo se**:")
    righe.append("")
    righe.append(f"1. la copertura delle squadre con allenatore e' almeno "
                 f"**{SOGLIA_COPERTURA:.0%}** (misurata su tutte e cinque le leghe);")
    righe.append("2. **tutti** i casi di cambio allenatore verificati su fonti "
                 "pubbliche risultano gia' aggiornati nelle API (nessun caso fuori "
                 "posto).")
    righe.append("")
    righe.append("Finche' non gira un run reale la regola **non e' soddisfatta**: la "
                 "scheda partita non mostra l'allenatore e lo dichiara, rimandando "
                 "alle fonti alternative (sito del club, comunicati ufficiali). Un "
                 "run `--fixture` (risposte finte) non cambia questa riga: i suoi "
                 "file portano il prefisso `fixture_` e non valgono come misura.")
    righe.append("")
    righe.append("## Casi pubblici 2026/27 (fonte per caso; stato da misurare)")
    righe.append("")
    if descrizione.get("versione") or descrizione.get("raccolti_il"):
        righe.append(f"I casi vengono da `audit/data/allenatori/"
                     f"casi_pubblici_2026_27.json` (versione "
                     f"{descrizione.get('versione') or 'n/d'}, "
                     f"{descrizione.get('raccolti_il') or 'data n/d'}).")
        righe.append("")
    for escluso in descrizione.get("esclusi") or []:
        nome = escluso.get("squadra") or escluso.get("lega") or "caso"
        righe.append(f"* **{nome}** non e' un caso: {escluso.get('motivo')}")
    if descrizione.get("esclusi"):
        righe.append("")
    if not casi:
        righe.append("_Nessun caso pubblico disponibile._")
    else:
        righe.append("| Lega | Squadra | Uscente | Entrante | Data | Allenatore "
                     "nelle API | Fonte |")
        righe.append("|---|---|---|---|---|---|---|")
        for c in casi:
            righe.append(f"| {c.get('lega')} | {c.get('squadra')} | "
                         f"{c.get('allenatore_uscente') or '—'} | "
                         f"{c.get('allenatore_entrante') or c.get('allenatore_atteso') or '—'} | "
                         f"{c.get('data') or c.get('data_cambio') or '—'} | "
                         f"da misurare | "
                         f"[fonte]({c.get('fonte')}) |")
        righe.append("")
        righe.append(f"Casi pubblici raccolti: **{len(casi)}** (la regola chiede "
                     f"almeno {MIN_CASI_PUBBLICI} casi e che TUTTI risultino "
                     f"aggiornati nel run reale).")
    righe.append("")
    righe.append("## Cosa manca per misurare")
    righe.append("")
    righe.append("**Il workflow manuale `audit_allenatori.yml`** (`workflow_dispatch`: "
                 "lo lancia Felice, non questo referto). Fa, in quest'ordine:")
    righe.append("")
    righe.append("1. i test offline della sonda (nessuna rete, nessuna chiave);")
    righe.append("2. ~5 chiamate per l'elenco squadre delle 5 leghe + 1 chiamata per "
                 "squadra (`GET /v4/competitions/{codice}/teams`, poi "
                 "`GET /v4/teams/{id}`): ~100 squadre, ~11 minuti a 10 chiamate al "
                 "minuto, il limite del piano gratuito;")
    righe.append("3. scrive `audit/data/allenatori/<giorno>.json` **solo** se almeno "
                 "una lega e' arrivata in fondo (almeno una chiamata riuscita) e "
                 "riscrive **questo** referto con copertura, forme delle date e "
                 "l'esito dei casi; se tutte le chiamate falliscono il workflow si "
                 "ferma con errore e non committa nulla;")
    righe.append("4. committa snapshot e referto con il token del bot.")
    righe.append("")
    righe.append("Dopo quel run questo referto conterra' i numeri veri: la copertura "
                 "per lega, la forma delle date di contratto cosi' come arrivano, "
                 "l'allenatore che le API riportano per ogni caso pubblico e l'esito "
                 "della regola. Solo allora si sapra' se l'allenatore puo' entrare "
                 "nella scheda partita.")
    righe.append("")
    righe.append("## Cosa NON fa questa sonda")
    righe.append("")
    righe.append("* non modifica l'app ne' `SoccerMath/`: la scheda partita non mostra "
                 "l'allenatore;")
    righe.append("* non stampa la chiave API (header `X-Auth-Token`, mai nell'URL) e "
                 "rifiuta di scrivere un file che la contenga;")
    righe.append("* non scrive snapshot senza chiamate riuscite: nessun file con la "
                 "data viene creato in modalita' «non eseguita».")
    return "\n".join(righe) + "\n"


# ---------------------------------------------------------------------------
# Giro completo
# ---------------------------------------------------------------------------
def scarica_lega(codice: str, stagione, chiave: str, finestra: FinestraChiamate,
                 session=None) -> list:
    """Elenco squadre + una chiamata per squadra. Ritorna le voci salvate."""
    quando = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parametri = {"season": stagione} if stagione else None
    # l'elenco squadre conta come le altre chiamate (stessa finestra, stessi 429)
    elenco = chiama(f"{API_BASE}/competitions/{codice}/teams", chiave, finestra,
                    parametri, session=session)
    voci = []
    for squadra in allenatore_da_teams(elenco, quando):
        payload = chiama(f"{API_BASE}/teams/{squadra['id']}", chiave, finestra,
                         session=session)
        voci.append({**squadra, **allenatore_da_squadra(payload, quando)})
    return voci


def blocco_fixture(fixture: dict, lega: str, codice: str) -> dict:
    """Il blocco di una lega dentro la fixture, con le due forme ammesse.

    Forma 1: ``{"leghe": {"SA": {...}}}`` (per codice). Forma 2: ``{"Serie A":
    {...}}`` (per nome). Le risposte per squadra stanno in ``per_squadra`` o
    ``teams_payload`` (le due chiavi usate finora), indicizzate per id in stringa.
    """
    fixture = fixture or {}
    if isinstance(fixture.get("leghe"), dict):
        return (fixture["leghe"].get(codice) or fixture["leghe"].get(lega) or {})
    return (fixture.get(lega) or fixture.get(codice) or {})


def scarica_da_fixture(fixture: dict, lega: str, codice: str) -> list:
    """Le stesse voci, da risposte finte: nessuna rete, nessuna chiave."""
    quando = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    blocco = blocco_fixture(fixture, lega, codice)
    per_squadra = blocco.get("per_squadra") or blocco.get("teams_payload") or {}
    voci = []
    for squadra in allenatore_da_teams(blocco, quando):
        payload = per_squadra.get(str(squadra["id"])) or {"coach": None}
        voci.append({**squadra, **allenatore_da_squadra(payload, quando)})
    return voci


def carica_casi(percorso: str) -> list:
    if not percorso or not os.path.exists(percorso):
        return []
    with open(percorso, "r", encoding="utf-8") as fh:
        dati = json.load(fh)
    casi = dati.get("casi") if isinstance(dati, dict) else dati
    return casi if isinstance(casi, list) else []


def descrizione_casi(percorso: str) -> dict:
    """Versione, data di raccolta e casi ESCLUSI (dichiarati, mai sottintesi)."""
    if not percorso or not os.path.exists(percorso):
        return {"versione": None, "raccolti_il": None, "esclusi": []}
    with open(percorso, "r", encoding="utf-8") as fh:
        dati = json.load(fh)
    if not isinstance(dati, dict):
        return {"versione": None, "raccolti_il": None, "esclusi": []}
    return {"versione": dati.get("versione"), "raccolti_il": dati.get("raccolti_il"),
            "esclusi": dati.get("esclusi") or []}


def rigenera_da_snapshot(percorso_snapshot: str, percorso_casi: str,
                         results_dir: str) -> int:
    """Ricalcola il referto con la regola di QUESTA versione, dallo snapshot.

    Nessuna chiamata di rete, nessuna chiave: si legge lo snapshot gia' salvato
    dal run (squadre per lega, leghe fallite, chiamate) e si riapplica il
    confronto e il giudizio. Lo snapshot NON viene toccato. Serve a correggere il
    referto di un run fatto con la versione precedente della sonda, che non
    riprovava i 429 e giudicava anche con leghe mancanti.
    """
    with open(percorso_snapshot, "r", encoding="utf-8") as fh:
        dati = json.load(fh)
    if dati.get("modalita") != "rete":
        print("ERRORE: si rigenera solo da uno snapshot di rete (non da una fixture)")
        return 1
    quando = dati.get("quando")
    squadre_per_lega = dati.get("squadre_per_lega") or {}
    cop = copertura(squadre_per_lega)
    casi = carica_casi(percorso_casi)
    descrizione = descrizione_casi(percorso_casi)
    confrontati = confronta_casi(casi, squadre_per_lega, quando)
    esito = giudizio(cop, confrontati)
    note = [
        f"Referto RIGENERATO dallo snapshot del run {quando} (nessuna chiamata nuova, "
        "nessuna chiave). Quel run e' stato fatto con la sonda v1, che non riprovava "
        "i 429 e giudicava anche con leghe mancanti: i numeri di chiamate e attese "
        "sono quelli del run; l'esito e' quello di questa versione.",
    ]
    for lega in dati.get("leghe_fallite") or []:
        note.append(f"{lega}: fallita nel run con «RuntimeError: HTTP 429 da "
                    "football-data.org» (il run v1 non riprovava: nessun tentativo "
                    "successivo).")
    misure = {
        **dati,
        "leghe": list(LEGHE),
        "riprovate": 0,
        "attese_429": 0,
        "attese_header": 0,
        "durata_minima_teorica": formato_durata(durata_minima_secondi(
            dati.get("chiamate") or 0, dati.get("max_per_minuto") or MAX_CHIAMATE_AL_MINUTO)),
        "durata_reale": "n/d (run v1: durata non registrata)",
        "copertura": cop["frazione"],
        "copertura_valutata": not leghe_mancanti(cop),
        "squadre": cop["squadre"],
        "con_allenatore": cop["con_allenatore"],
        "copertura_per_lega": cop["per_lega"],
        "senza_allenatore": cop["senza_allenatore"],
        "esito": esito,
        "casi": confrontati,
        "leghe_mancanti": leghe_mancanti(cop),
        "min_casi_pubblici": MIN_CASI_PUBBLICI,
        "casi_versione": descrizione.get("versione"),
        "casi_raccolti_il": descrizione.get("raccolti_il"),
        "casi_esclusi": descrizione.get("esclusi"),
    }
    os.makedirs(results_dir, exist_ok=True)
    referto = os.path.join(results_dir, "sonda_allenatori.md")
    with open(referto, "w", encoding="utf-8") as fh:
        fh.write(testo_referto(misure, confrontati, esito, note))
    print(f"RIGENERATO da {percorso_snapshot} (nessuna chiamata)")
    print(f"VALUTABILE={esito['valutabile']} LEGHE_MANCANTI={misure['leghe_mancanti']}")
    print(f"REFERTO={referto}")
    return 0


def formato_durata(secondi: float) -> str:
    """Durata leggibile: ``9 min 0 s`` (dichiarata, non stimata)."""
    totale = int(round(float(secondi)))
    return f"{totale // 60} min {totale % 60} s"


def stagione_da_testo(valore):
    """``--stagione``: intero, oppure ``None`` se vuoto (input del workflow)."""
    testo = str(valore or "").strip()
    return int(testo) if testo else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Sonda allenatori (sola lettura)")
    parser.add_argument("--stagione", type=stagione_da_testo, default=None,
                        help="anno di inizio stagione (es. 2026); vuoto = "
                             "predefinita delle API")
    parser.add_argument("--leagues", nargs="*", default=None,
                        help="nomi delle leghe (default: tutte e cinque)")
    parser.add_argument("--out-dir", default=None,
                        help="dove salvare lo snapshot (default: "
                             "audit/data/allenatori per un run di rete, "
                             "audit/output/sonda_allenatori con --fixture)")
    parser.add_argument("--results-dir", default=None,
                        help="dove scrivere il referto (stessa regola di --out-dir)")
    parser.add_argument("--casi", default=DEFAULT_CASI)
    parser.add_argument("--max-calls-per-minute", type=int, default=MAX_CHIAMATE_AL_MINUTO)
    parser.add_argument("--fixture", default=None,
                        help="risposte finte in JSON: gira senza rete (prove e test); "
                             "i file scritti portano il prefisso fixture_")
    parser.add_argument("--keep-going", action="store_true",
                        help="se una lega fallisce, continua con le altre")
    parser.add_argument("--rigenera-da", default=None,
                        help="ricalcola il referto con la regola di questa versione "
                             "dallo snapshot indicato: nessuna chiamata, lo snapshot "
                             "non viene toccato")
    parser.add_argument("--referto-non-eseguito", action="store_true",
                        help="scrive il referto nello stato «sonda non eseguita» "
                             "(regola, casi con fonte, colonna «da misurare»): "
                             "nessuna chiamata, nessuno snapshot")
    args = parser.parse_args(argv)

    if args.rigenera_da:
        return rigenera_da_snapshot(args.rigenera_da, args.casi,
                                    args.results_dir or DEFAULT_RESULTS_DIR)

    quando = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    giorno = quando[:10]
    inizio_run = time.monotonic()

    if args.referto_non_eseguito:
        results_dir = args.results_dir or DEFAULT_RESULTS_DIR
        referto = os.path.join(results_dir, "sonda_allenatori.md")
        os.makedirs(results_dir, exist_ok=True)
        with open(referto, "w", encoding="utf-8") as fh:
            fh.write(testo_referto_non_eseguito(quando, args.casi))
        print("MODALITA=non eseguita CHIAMATE=0")
        print(f"REFERTO={referto}")
        return 0

    leghe = args.leagues or list(LEGHE)
    sconosciute = [l for l in leghe if l not in LEGHE]
    if sconosciute:
        print(f"leghe non riconosciute: {sconosciute}; ammesse: {list(LEGHE)}")
        return 1

    chiave = ""
    fixture = None
    if args.fixture:
        with open(args.fixture, "r", encoding="utf-8") as fh:
            fixture = json.load(fh)
        modalita = "fixture"
    else:
        chiave = leggi_chiave()
        if not chiave:
            print("chiave API assente (FOOTBALL_DATA_API_KEY): nessuna chiamata fatta")
            return 3
        modalita = "rete"

    finestra = FinestraChiamate(args.max_calls_per_minute)
    squadre_per_lega, note, falliti = {}, [], []
    for lega in leghe:
        codice = LEGHE[lega]
        try:
            voci = (scarica_da_fixture(fixture, lega, codice) if modalita == "fixture"
                    else scarica_lega(codice, args.stagione, chiave, finestra))
        except Exception as errore:                      # una lega non ferma le altre
            falliti.append(lega)
            note.append(f"{lega}: errore nella lettura delle API "
                        f"({type(errore).__name__}: {errore}).")
            if not args.keep_going:
                print(f"ERRORE su {lega}: {type(errore).__name__}: {errore}")
                return 1
            continue
        squadre_per_lega[lega] = voci
        print(f"{lega}: {len(voci)} squadre, "
              f"{sum(1 for v in voci if v.get('allenatore'))} con allenatore")

    # Un run di RETE senza nemmeno una lega arrivata in fondo non e' una misura:
    # niente snapshot con la data e niente referto (altrimenti resterebbe in
    # giro un file che sembra un risultato). Un run --fixture invece e' una
    # prova: si scrive, ma solo con il prefisso fixture_.
    leghe_riuscite = [l for l in leghe if squadre_per_lega.get(l)]
    if modalita == "rete" and not leghe_riuscite:
        print("ERRORE: nessuna chiamata riuscita: nessuno snapshot e nessun "
              "referto scritti (la regola resta non verificata).")
        for n in note:
            print(f"  - {n}")
        return 2

    cop = copertura(squadre_per_lega)
    casi = carica_casi(args.casi)
    casi_confrontati = confronta_casi(casi, squadre_per_lega, quando)
    esito = giudizio(cop, casi_confrontati)

    durata_reale = time.monotonic() - inizio_run
    misure = {
        "versione": "sonda_allenatori_v1",
        "quando": quando,
        "stagione": args.stagione,
        "modalita": modalita,
        "leghe": leghe,
        "chiamate": finestra.chiamate,
        "riprovate": finestra.riprovate,
        "attese": finestra.attese,
        "attese_429": finestra.attese_429,
        "attese_header": finestra.attese_header,
        "max_per_minuto": args.max_calls_per_minute,
        "durata_minima_teorica": formato_durata(durata_minima_secondi(
            finestra.chiamate, args.max_calls_per_minute)),
        "durata_reale": formato_durata(durata_reale) if modalita == "rete" else "n/d (fixture)",
        "leghe_mancanti": leghe_mancanti(cop),
        "copertura": cop["frazione"],
        "copertura_valutata": bool(not leghe_mancanti(cop)),
        "squadre": cop["squadre"],
        "con_allenatore": cop["con_allenatore"],
        "copertura_per_lega": cop["per_lega"],
        "senza_allenatore": cop["senza_allenatore"],
        "forme_date": forme_date(squadre_per_lega),
        "esito": esito,
        "casi": casi_confrontati,
        "leghe_fallite": falliti,
        "min_casi_pubblici": MIN_CASI_PUBBLICI,
        "casi_versione": descrizione_casi(args.casi).get("versione"),
        "casi_raccolti_il": descrizione_casi(args.casi).get("raccolti_il"),
        "casi_esclusi": descrizione_casi(args.casi).get("esclusi"),
    }

    # Percorsi: con --fixture SEMPRE il prefisso fixture_ e, senza cartelle
    # esplicite, la cartella non versionata audit/output/.
    prefisso = PREFISSO_FIXTURE if modalita == "fixture" else ""
    out_dir = args.out_dir or (DEFAULT_OUT_DIR_FIXTURE if modalita == "fixture"
                               else DEFAULT_OUT_DIR)
    results_dir = args.results_dir or (DEFAULT_OUT_DIR_FIXTURE if modalita == "fixture"
                                      else DEFAULT_RESULTS_DIR)
    percorso_snapshot = scrivi_snapshot(
        out_dir, giorno,
        # nel file: le stesse misure del referto, ma con la copertura COMPLETA
        # (per lega e con l'elenco di chi non ha allenatore), non solo la frazione
        {**misure, "versione": "allenatori_snapshot_v1",
         "squadre_per_lega": squadre_per_lega, "copertura": cop},
        quando, chiavi_da_escludere=(chiave,), prefisso=prefisso)
    referto = os.path.join(results_dir, f"{prefisso}sonda_allenatori.md")
    os.makedirs(results_dir, exist_ok=True)
    with open(referto, "w", encoding="utf-8") as fh:
        fh.write(testo_referto(misure, casi_confrontati, esito, note))

    print(f"SQUADRE={cop['squadre']} CON_ALLENATORE={cop['con_allenatore']} "
          f"CHIAMATE={misure['chiamate']}")
    print(f"VALUTABILE={esito['valutabile']} LEGHE_MANCANTI={misure['leghe_mancanti']}")
    print(f"CASI={len(casi_confrontati)} VALUTABILI={len(casi_valutabili(casi_confrontati))} "
          f"NON_AGGIORNATI={sum(1 for c in casi_valutabili(casi_confrontati) if c.get('esito') != ESITO_AGGIORNATO)}")
    print(f"RIPROVATE={finestra.riprovate} ATTESE_429={finestra.attese_429} "
          f"ATTESE_LIMITE={finestra.attese}")
    print(f"FILE={percorso_snapshot}")
    print(f"REFERTO={referto}")
    return 1 if falliti else 0


if __name__ == "__main__":
    sys.exit(main())
