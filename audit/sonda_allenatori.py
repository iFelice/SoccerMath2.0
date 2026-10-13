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

Uso::

    python audit/sonda_allenatori.py [--stagione 2026] [--leagues ...]
                                     [--out-dir DIR] [--results-dir DIR]
                                     [--casi FILE] [--max-calls-per-minute 10]
                                     [--fixture FILE] [--keep-going]

``--fixture`` gira SENZA RETE su risposte finte (test e prove): il referto lo
dichiara in testa ("RUN DI PROVA").

Code di uscita: 0 = sonda riuscita su tutte le leghe chieste; 1 = almeno una
lega fallita (con ``--keep-going`` le altre vengono comunque salvate); 3 =
chiave assente (e nessuna fixture).
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
# Chiave e rete (solo questi due punti toccano l'esterno)
# ---------------------------------------------------------------------------
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


def http_get(url: str, chiave: str, parametri=None, session=None, timeout=20) -> dict:
    """GET con la chiave nell'header. Nessun URL con la chiave, nessun log suo."""
    import requests

    sessione = session or requests
    risposta = sessione.get(url, headers={"X-Auth-Token": chiave},
                            params=parametri or {}, timeout=timeout)
    if risposta.status_code in STATUS_INTERROMPI:
        raise RuntimeError(f"HTTP {risposta.status_code} da football-data.org: "
                           "chiave non valida o quota esaurita (nessun dettaglio "
                           "stampato per non esporre la chiave)")
    risposta.raise_for_status()
    return risposta.json()


class FinestraChiamate:
    """Finestra mobile: al massimo ``max_chiamate`` chiamate ogni ``secondi``.

    ``orologio`` e ``dormi`` sono iniettabili: i test verificano l'attesa senza
    aspettare davvero.
    """

    def __init__(self, max_chiamate: int = MAX_CHIAMATE_AL_MINUTO,
                 secondi: float = 60.0, orologio=time.monotonic, dormi=time.sleep):
        # almeno 1: con 0 la finestra non si libererebbe mai (attesa infinita)
        self.max_chiamate = max(1, int(max_chiamate))
        self.secondi = float(secondi)
        self._orologio = orologio
        self._dormi = dormi
        self._istanti: list = []
        self.attese = 0
        self.chiamate = 0

    def attendi(self) -> float:
        """Blocca finche' c'e' posto nella finestra; ritorna i secondi attesi."""
        while True:
            adesso = self._orologio()
            self._istanti = [t for t in self._istanti if adesso - t < self.secondi]
            if len(self._istanti) < self.max_chiamate:
                self._istanti.append(adesso)
                self.chiamate += 1
                return 0.0
            pausa = self.secondi - (adesso - self._istanti[0]) + 0.01
            self.attese += 1
            self._dormi(max(pausa, 0.0))


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


def tutte_aggiornate(casi: list) -> bool:
    """True solo se ci sono casi E nessuno e' ``non aggiornato``/``senza nome``."""
    if not casi:
        return False
    return all(c.get("esito") == ESITO_AGGIORNATO for c in casi)


def giudizio(cop: dict, casi: list) -> dict:
    """Applica la regola dichiarata e spiega la decisione."""
    copertura_ok = cop["frazione"] >= SOGLIA_COPERTURA
    casi_ok = tutte_aggiornate(casi)
    motivi = []
    if not copertura_ok:
        motivi.append(f"copertura {cop['frazione']:.1%} < {SOGLIA_COPERTURA:.0%}")
    if not casi_ok:
        mancanti = [c for c in casi if c.get("esito") != ESITO_AGGIORNATO]
        if not casi:
            motivi.append("nessun caso verificabile")
        else:
            motivi.append(f"{len(mancanti)} casi su {len(casi)} non aggiornati")
    return {"copertura_ok": copertura_ok, "casi_ok": casi_ok,
            "affidabile": bool(copertura_ok and casi_ok), "motivi": motivi}


# ---------------------------------------------------------------------------
# Scrittura (snapshot + referto)
# ---------------------------------------------------------------------------
def percorso_del_giorno(out_dir: str, giorno: str, suffisso: str = "") -> str:
    return os.path.join(out_dir, f"{giorno}{suffisso}.json")


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
                    chiavi_da_escludere=()) -> str:
    """Salva lo snapshot del giorno senza MAI sovrascrivere un file esistente.

    Il primo nome e' ``<giorno>.json``; se esiste si passa a ``<giorno>_02.json``
    e cosi' via: un secondo run nello stesso giorno non cancella il primo.
    """
    candidati = [percorso_del_giorno(out_dir, giorno)]
    candidati += [percorso_del_giorno(out_dir, giorno, f"_{i:02d}")
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
                     "Il run vero lo esegue il workflow manuale `audit_allenatori.yml`.")
        righe.append("")
    righe.append(f"Run: **{misure['quando']}** · stagione dal run: "
                 f"**{misure['stagione'] or 'predefinita'}** · chiamate fatte: "
                 f"**{misure['chiamate']}**.")
    righe.append("")
    righe.append("## Regola dichiarata (prima dei numeri)")
    righe.append("")
    righe.append("L'allenatore entra nella scheda partita **solo se**:")
    righe.append("")
    righe.append(f"1. la copertura delle squadre con allenatore e' almeno "
                 f"**{SOGLIA_COPERTURA:.0%}**"
                 + (f" ({misure['copertura']:.1%} in questo run);"
                    if misure.get("copertura") is not None else ";"));
    righe.append("2. **tutti** i casi di cambio allenatore verificati su fonti "
                 "pubbliche risultano aggiornati nelle API (nessun caso «non "
                 "aggiornato», nessun caso «da verificare»).")
    righe.append("")
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
    righe.append("| Lega | Squadre | Con allenatore | Senza |")
    righe.append("|---|---|---|---|")
    for lega, numeri in (misure.get("copertura_per_lega") or {}).items():
        righe.append(f"| {lega} | {numeri['squadre']} | {numeri['con_allenatore']} | "
                     f"{len(numeri['senza'])} |")
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
    righe.append(f"Casi verificabili in questo run: **{len(casi)}** "
                 f"(servono almeno {misure.get('min_casi_pubblici') or 3} casi e che "
                 f"TUTTI risultino aggiornati).")
    righe.append("")
    if not casi:
        righe.append("_Nessun caso pubblico disponibile._")
    else:
        righe.append("| Lega | Squadra | Uscente | Entrante | Data | Allenatore "
                     "nelle API | Esito | Fonte |")
        righe.append("|---|---|---|---|---|---|---|---|")
        for c in casi:
            righe.append(f"| {c.get('lega')} | {c.get('squadra')} | "
                         f"{c.get('allenatore_uscente') or '—'} | "
                         f"{c.get('allenatore_entrante') or c.get('allenatore_atteso') or '—'} | "
                         f"{c.get('data') or c.get('data_cambio') or '—'} | "
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
    righe.append(f"* chiave nell'header `X-Auth-Token`, **mai** nell'URL, mai "
                 f"stampata; massimo **{misure.get('max_per_minuto')} chiamate al "
                 f"minuto** (limite del piano gratuito), con finestra mobile;")
    righe.append("* sola lettura: nessuna scrittura in `SoccerMath/`, nessuna "
                 "modifica all'app, nessuna chiamata fatta dall'app;")
    if misure.get("attese"):
        righe.append(f"* questo run ha aspettato la finestra {misure['attese']} volte "
                     f"(durata prevista: {misure.get('durata_prevista')});")
    if note:
        righe.append("")
        righe.append("## Note del run")
        righe.append("")
        for n in note:
            righe.append(f"* {n}")
    return "\n".join(righe) + "\n"


# ---------------------------------------------------------------------------
# Giro completo
# ---------------------------------------------------------------------------
def scarica_lega(codice: str, stagione, chiave: str, finestra: FinestraChiamate,
                 session=None) -> list:
    """Elenco squadre + una chiamata per squadra. Ritorna le voci salvate."""
    quando = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parametri = {"season": stagione} if stagione else None
    finestra.attendi()
    elenco = http_get(f"{API_BASE}/competitions/{codice}/teams", chiave,
                      parametri, session=session)
    voci = []
    for squadra in allenatore_da_teams(elenco, quando):
        finestra.attendi()
        payload = http_get(f"{API_BASE}/teams/{squadra['id']}", chiave,
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
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--results-dir", default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--casi", default=DEFAULT_CASI)
    parser.add_argument("--max-calls-per-minute", type=int, default=MAX_CHIAMATE_AL_MINUTO)
    parser.add_argument("--fixture", default=None,
                        help="risposte finte in JSON: gira senza rete (prove e test)")
    parser.add_argument("--keep-going", action="store_true",
                        help="se una lega fallisce, continua con le altre")
    args = parser.parse_args(argv)

    quando = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    giorno = quando[:10]
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

    cop = copertura(squadre_per_lega)
    casi = carica_casi(args.casi)
    casi_confrontati = confronta_casi(casi, squadre_per_lega, quando)
    esito = giudizio(cop, casi_confrontati)

    misure = {
        "versione": "sonda_allenatori_v1",
        "quando": quando,
        "stagione": args.stagione,
        "modalita": modalita,
        "leghe": leghe,
        "chiamate": finestra.chiamate,
        "attese": finestra.attese,
        "max_per_minuto": args.max_calls_per_minute,
        "durata_prevista": (f"circa {max(len(finestra._istanti), 1) / args.max_calls_per_minute:.1f} minuti "
                            f"a {args.max_calls_per_minute} chiamate/minuto"),
        "copertura": cop["frazione"],
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

    percorso_snapshot = scrivi_snapshot(
        args.out_dir, giorno,
        # nel file: le stesse misure del referto, ma con la copertura COMPLETA
        # (per lega e con l'elenco di chi non ha allenatore), non solo la frazione
        {**misure, "versione": "allenatori_snapshot_v1",
         "squadre_per_lega": squadre_per_lega, "copertura": cop},
        quando, chiavi_da_escludere=(chiave,))
    referto = os.path.join(args.results_dir, "sonda_allenatori.md")
    os.makedirs(args.results_dir, exist_ok=True)
    with open(referto, "w", encoding="utf-8") as fh:
        fh.write(testo_referto(misure, casi_confrontati, esito, note))

    print(f"SQUADRE={cop['squadre']} CON_ALLENATORE={cop['con_allenatore']} "
          f"COPERTURA={cop['frazione']:.1%} CHIAMATE={misure['chiamate']}")
    print(f"CASI={len(casi_confrontati)} NON_AGGIORNATI="
          f"{sum(1 for c in casi_confrontati if c.get('esito') != ESITO_AGGIORNATO)}")
    print(f"FILE={percorso_snapshot}")
    print(f"REFERTO={referto}")
    return 1 if falliti else 0


if __name__ == "__main__":
    sys.exit(main())
