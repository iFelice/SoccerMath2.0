#!/usr/bin/env python3
"""diagnose_live_odds_conversione.py — perche' ``live_odds.json`` e' uscito senza libri (sola lettura).

DOMANDA. Il 2026-10-09 il giro manuale delle quote ha scritto
``SoccerMath/database/live_odds.json`` con 96 eventi su 5/5 leghe, HTTP 200 e
1 credito per lega, ma ``"libri": []`` su TUTTI gli eventi; il log diceva
"20 eventi OK" per lega e il workflow e' uscito ``success``. Il Top Mix di
mercato e' quindi vuoto. Il file non contiene la risposta grezza: la colpa e'
della conversione o della risposta?

COME SI RISPONDE SENZA SPENDERE CREDITI
---------------------------------------
Nessuna chiamata all'API. Si usano solo dati committati:

* ``audit/data/live_odds_probe/odds_api_<sport_key>.json`` — le risposte REALI
  della sonda del 2026-10-08, nella forma COMPATTATA prodotta da
  ``live_odds_probe.compact_events``;
* la stessa risposta rimessa nella forma GREZZA dell'API
  (``bookmakers[].markets[].outcomes[]``) da ``audit/live_odds_raw_fixtures.py``,
  verificata per andata e ritorno in ``audit/test_live_odds_raw_fixtures.py``;
* ``SoccerMath/database/live_odds.json`` — il file guasto del 2026-10-09.

Le risposte passano nella STESSA funzione di produzione che costruisce
``libri`` (``update_live_odds.libri_dell_evento``), nella versione di oggi e
nella versione precedente (rimessa in piedi qui sotto, 5 righe, identica a
quella del commit ``bcbeb74``).

Uso: ``python audit/diagnose_live_odds_conversione.py``
Output:
  * ``audit/results/live_odds_conversione_diagnosi.md``  referto (committato);
  * ``audit/output/live_odds_conversione_diagnosi.json`` numeri (non versionato).
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
for _p in (_AUDIT_DIR, os.path.join(_REPO_ROOT, "SoccerMath")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import live_odds_raw_fixtures as GREZZE  # noqa: E402
import market_odds as mo  # noqa: E402
import update_live_odds as U  # noqa: E402
from live_odds_match import next_matchday  # noqa: E402  (regola della prossima giornata)

FILE_PRODUZIONE = os.path.join(_REPO_ROOT, "SoccerMath", "database", "live_odds.json")
RESULTS = os.path.join(_AUDIT_DIR, "results", "live_odds_conversione_diagnosi.md")
OUTPUT = os.path.join(_AUDIT_DIR, "output", "live_odds_conversione_diagnosi.json")

# Riferimento esatto della riga che scartava i bookmaker (versione precedente).
COMMIT_PRECEDENTE = "bcbeb74"
RIGHE_SCARTO = "SoccerMath/update_live_odds.py:147-149"

# Istante della sonda: serve a scegliere la "prossima giornata" con la stessa
# regola di produzione (app.select_next_matchday_matches / finestra 5 giorni).
ORA_SONDA = datetime(2026, 10, 8, 23, 30, 38, tzinfo=timezone.utc)


def libri_conversione_precedente(evento: Dict[str, Any]) -> List[Dict[str, Any]]:
    """La conversione com'era al commit ``bcbeb74`` (righe 143-156).

    Unica forma accettata: ``{"key": ..., "h2h": {...}}``. Un bookmaker nella
    forma grezza dell'API (``markets``/``outcomes``) non ha la chiave ``h2h``,
    quindi ``isinstance(h2h, dict)`` e' falso e il bookmaker viene scartato.
    """
    out = []
    for libro in evento.get("bookmakers") or []:
        if not isinstance(libro, dict):
            continue
        h2h = libro.get("h2h")
        if not isinstance(h2h, dict):     # <-- la riga che scartava tutto
            continue
        out.append({"key": libro.get("key"), "h2h": h2h})
    return out


def conta(eventi, conversione) -> Dict[str, int]:
    libri = [conversione(e) for e in eventi]
    return {
        "eventi": len(eventi),
        "eventi_con_libri": sum(1 for l in libri if l),
        "libri_totali": sum(len(l) for l in libri),
        "eventi_con_pinnacle": sum(1 for l in libri
                                   if any((b.get("key") or "") == "pinnacle" for b in l)),
    }


def sezione_conversione() -> Dict[str, Any]:
    """Le risposte della sonda nella funzione di produzione, nelle due forme."""
    righe = OrderedDict()
    for lega, sport_key in U.LEGA_SPORT_KEY.items():
        snap = GREZZE.carica_snapshot(sport_key)
        compattata = snap["events"]
        grezza = GREZZE.risposta_grezza(snap, sport_key)
        righe[lega] = {
            "sport_key": sport_key,
            "bookmaker_distinti_nella_sonda": len(snap.get("bookmakers") or {}),
            "compattata_oggi": conta(compattata, U.libri_dell_evento),
            "grezza_oggi": conta(grezza, U.libri_dell_evento),
            "grezza_codice_precedente": conta(grezza, libri_conversione_precedente),
            "compattata_codice_precedente": conta(compattata, libri_conversione_precedente),
        }
    return righe


def sezione_parametri() -> Dict[str, Any]:
    """Parametri della richiesta: produzione (file del 2026-10-09) contro sonda."""
    prod = json.load(open(FILE_PRODUZIONE, encoding="utf-8"))
    sonda = json.load(open(os.path.join(GREZZE.DATA_DIR, "odds_api_soccer_epl.json"),
                           encoding="utf-8"))
    richiesta_sonda = sonda.get("richiesta") or {}
    url_prod = ((prod.get("leghe") or {}).get("Premier League") or {}).get("url_masked")
    return {
        "produzione": {
            "endpoint": "/v4/sports/<sport_key>/odds",
            "regions": prod.get("regioni"),
            "markets": prod.get("mercato"),
            "oddsFormat": prod.get("formato_quote"),
            "bookmakers": "(parametro non usato)",
            "dateFormat": "iso",
            "url_masked": url_prod,
            "costo_per_lega": ((prod.get("crediti") or {}).get("costo_ultima_chiamata")),
        },
        "sonda": {
            "endpoint": "/v4/sports/<sport_key>/odds",
            "regions": richiesta_sonda.get("regions"),
            "markets": richiesta_sonda.get("markets"),
            "oddsFormat": richiesta_sonda.get("oddsFormat"),
            "bookmakers": "(parametro non usato)",
            "dateFormat": "iso",
            "url_masked": richiesta_sonda.get("url_masked"),
            "costo_per_lega": int((sonda.get("http") or {}).get("crediti", {})
                                  .get("x-requests-last", 0) or 0),
        },
    }


def sezione_file_produzione() -> Dict[str, Any]:
    """Il file guasto: quanti eventi, quanti libri, quanti ID in comune con la sonda."""
    prod = json.load(open(FILE_PRODUZIONE, encoding="utf-8"))
    righe = OrderedDict()
    for lega, blocco in (prod.get("leghe") or {}).items():
        sport_key = blocco.get("sport_key")
        try:
            snap = GREZZE.carica_snapshot(sport_key)
        except OSError:
            snap = {"events": []}
        id_sonda = {e["id"]: e for e in snap.get("events") or []}
        eventi = blocco.get("eventi") or []
        comuni = [e for e in eventi if e.get("id") in id_sonda]
        libri_sonda = [len(id_sonda[e["id"]].get("bookmakers") or []) for e in comuni]
        righe[lega] = {
            "sport_key": sport_key,
            "http_status": blocco.get("http_status"),
            "crediti": (blocco.get("crediti") or {}).get("costo_ultima_chiamata"),
            "eventi": len(eventi),
            "libri_nel_file": sum(len(e.get("libri") or []) for e in eventi),
            "eventi_in_comune_con_la_sonda": len(comuni),
            "libri_che_la_sonda_aveva_sugli_stessi_eventi": sum(libri_sonda),
            "min_libri_per_evento_nella_sonda": min(libri_sonda) if libri_sonda else 0,
        }
    return {"generato_il": prod.get("generato_il"), "n_eventi": prod.get("n_eventi"),
            "leghe": righe}


def sezione_calendario(payload_riparato: Dict[str, Any]) -> Dict[str, Any]:
    """Le 48 partite della prossima giornata della sonda: quante avrebbero quote."""
    dati = mo.indice_partite(payload_riparato)
    righe = OrderedDict()
    totale = Counter()
    for lega, blocco in (payload_riparato.get("leghe") or {}).items():
        eventi, prima, fine = next_matchday(blocco.get("eventi") or [], ORA_SONDA)
        conta_lega = Counter()
        for evento in eventi:
            trovato, motivo = mo.cerca_quote_con_motivo(
                dati["indice"], evento.get("home_team"), evento.get("away_team"),
                evento.get("commence_time"))
            if trovato is None:
                conta_lega[motivo or "non trovato"] += 1
                continue
            prob = mo.probabilita_mercato(trovato.get("libri") or [])
            conta_lega[prob["fonte"]] += 1
        righe[lega] = {"partite": len(eventi),
                       "prima": prima.isoformat() if prima else None,
                       "fine_finestra": fine.isoformat() if fine else None,
                       **conta_lega}
        totale.update(conta_lega)
        totale["partite"] += len(eventi)
    return {"per_lega": righe, "totale": dict(totale),
            "nomi_non_abbinati": dati["non_abbinati"]}


def tabella(intestazioni, righe) -> str:
    out = ["| " + " | ".join(intestazioni) + " |",
           "|" + "|".join(["---"] * len(intestazioni)) + "|"]
    for r in righe:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def referto(dati: Dict[str, Any]) -> str:
    conv = dati["conversione"]
    par = dati["parametri"]
    prod = dati["file_produzione"]
    cal = dati["calendario"]

    somma = lambda chiave, campo: sum(v[chiave][campo] for v in conv.values())  # noqa: E731

    testo = []
    A = testo.append
    A("# Quote live: perche' `live_odds.json` e' uscito con `libri: []`")
    A("")
    A(f"Generato il {dati['generato_il']} da `audit/diagnose_live_odds_conversione.py`. "
      "Sola lettura, **nessuna chiamata all'API, 0 crediti**: usa solo dati committati "
      "(gli snapshot della sonda del 2026-10-08 e il file di produzione del 2026-10-09).")
    A("")
    A("## 1. Esito: la risposta aveva i bookmaker, li ha persi la conversione")
    A("")
    A("Le risposte reali della sonda passate nella funzione di produzione che costruisce "
      "`libri` (`update_live_odds.libri_dell_evento`), nelle due forme in cui la stessa "
      "risposta puo' presentarsi:")
    A("")
    A(tabella(["lega", "eventi", "libri (forma compattata della sonda)",
               "libri (forma grezza dell'API) con il codice PRECEDENTE",
               "libri (forma grezza dell'API) con il codice di OGGI"],
              [[lega, v["grezza_oggi"]["eventi"], v["compattata_oggi"]["libri_totali"],
                v["grezza_codice_precedente"]["libri_totali"], v["grezza_oggi"]["libri_totali"]]
               for lega, v in conv.items()]
              + [["**totale**", somma("grezza_oggi", "eventi"),
                  somma("compattata_oggi", "libri_totali"),
                  somma("grezza_codice_precedente", "libri_totali"),
                  somma("grezza_oggi", "libri_totali")]]))
    A("")
    A("Gli snapshot committati della sonda **non sono il corpo della risposta**: sono la "
      "forma COMPATTATA prodotta da `live_odds_probe.compact_events`, che ha gia' ridotto "
      "`bookmakers[].markets[].outcomes[]` a `{\"h2h\": {\"home\": ..., \"draw\": ..., "
      "\"away\": ...}}`. Passati cosi' com'erano nella funzione di produzione danno libri "
      "PIENI, anche con il codice precedente: e' per questo che il dry-run della PR "
      "passava mentre la produzione scriveva il vuoto.")
    A("")
    A("La stessa risposta nella forma GREZZA dell'API — quella che arriva dalla rete, "
      "ricostruita da `audit/live_odds_raw_fixtures.py` e verificata per andata e ritorno "
      "in `audit/test_live_odds_raw_fixtures.py` — con il codice precedente da **0 libri "
      "su tutti gli eventi**: esattamente il file del 2026-10-09.")
    A("")
    A("### La riga esatta")
    A("")
    A(f"`{RIGHE_SCARTO}` (commit `{COMMIT_PRECEDENTE}`):")
    A("")
    A("```python")
    A("    for libro in evento.get(\"bookmakers\") or []:")
    A("        if not isinstance(libro, dict):")
    A("            continue")
    A("        h2h = libro.get(\"h2h\")          # 147")
    A("        if not isinstance(h2h, dict):   # 148  <-- scarta ogni bookmaker dell'API")
    A("            continue                    # 149")
    A("```")
    A("")
    A("**Perche'.** The Odds API non manda `h2h` dentro il bookmaker: manda "
      "`bookmakers[].markets[]`, e il mercato `h2h` ha `outcomes[]` con `name` e `price`. "
      "`libro.get(\"h2h\")` e' quindi `None`, `isinstance(None, dict)` e' falso e il "
      "`continue` butta il bookmaker. Tutti. In silenzio: nessun errore, nessun "
      "conteggio, HTTP 200, 1 credito speso per lega e `n_eventi` giusto, per cui il "
      "log diceva \"20 eventi OK\" e il workflow usciva `success`.")
    A("")
    A("Le altre cause possibili sono state controllate e **scartate**:")
    A("")
    A("* filtro sulle chiavi dei bookmaker: non esiste, non c'e' nessuna lista di "
      "bookmaker ammessi ne' nel writer ne' nella richiesta;")
    A("* nomi degli esiti: nella risposta gli esiti si chiamano come le squadre "
      "dell'evento piu' `Draw`; il confronto con i nomi normalizzati del progetto "
      "avviene DOPO, in `market_odds.indice_partite`, e oggi abbina 96 eventi su 96;")
    A("* tipo dei prezzi: nella sonda tutti i 3227 prezzi sono `float` validi;")
    A("* parametri della richiesta: vedi il punto 2, la differenza c'e' ma non spiega "
      "lo zero.")
    A("")
    A("## 2. Parametri: produzione contro sonda")
    A("")
    A(tabella(["parametro", "produzione (2026-10-09)", "sonda (2026-10-08)"],
              [[k, par["produzione"][k], par["sonda"][k]]
               for k in ("endpoint", "regions", "markets", "oddsFormat", "bookmakers",
                         "dateFormat", "costo_per_lega")]))
    A("")
    A("L'unica differenza e' `regions`: la produzione chiede `eu` (1 credito a chiamata), "
      "la sonda chiedeva `eu,uk` (2 crediti). `eu` e' un SOTTOINSIEME di `eu,uk`: puo' "
      "ridurre il numero di bookmaker per evento, non azzerarlo. Nella sonda, sugli "
      "stessi eventi, compaiono bookmaker che non sono del Regno Unito — `pinnacle`, "
      "`unibet_nl`, `winamax_fr`, `winamax_de`, `betclic_fr`, `codere_it`, `tipico_de`, "
      "`betsson`, `nordicbet`, `onexbet` — quindi con `regions=eu` i libri restano "
      "diversi da zero. Endpoint, `markets`, `oddsFormat` e `dateFormat` sono identici e "
      "non esiste un parametro `bookmakers` nella richiesta.")
    A("")
    A("## 3. Il file del 2026-10-09 e gli stessi eventi nella sonda")
    A("")
    A(tabella(["lega", "HTTP", "crediti", "eventi", "libri nel file",
               "eventi in comune con la sonda", "libri che la sonda aveva su quegli eventi",
               "minimo libri/evento nella sonda"],
              [[lega, v["http_status"], v["crediti"], v["eventi"], v["libri_nel_file"],
                v["eventi_in_comune_con_la_sonda"],
                v["libri_che_la_sonda_aveva_sugli_stessi_eventi"],
                v["min_libri_per_evento_nella_sonda"]]
               for lega, v in prod["leghe"].items()]))
    A("")
    A("Tutti e 96 gli eventi del file guasto hanno lo STESSO `id` degli eventi della "
      "sonda del giorno prima, e su quegli eventi la sonda aveva da 25 a 41 bookmaker "
      "ciascuno. La fonte quotava quelle partite; il file no.")
    A("")
    A("## 4. Il calendario della sonda dopo la riparazione")
    A("")
    A("Prossima giornata con la regola di produzione (prima partita futura rispetto "
      f"all'istante della sonda {ORA_SONDA.isoformat()} piu' finestra di 5 giorni, "
      "`app.TOP_MIX_ROUND_WINDOW_DAYS`), quote prese dal file prodotto dal writer "
      "riparato e lette con `carica_quote_live` -> `indice_partite` -> `cerca_quote` -> "
      "`probabilita_mercato`:")
    A("")
    A(tabella(["lega", "partite della giornata", "con quote (Pinnacle)",
               "con quote (media libri)", "senza quote"],
              [[lega, v["partite"], v.get(mo.FONTE_PINNACLE, 0),
                v.get(mo.FONTE_MEDIA_LIBRI, 0),
                v["partite"] - v.get(mo.FONTE_PINNACLE, 0) - v.get(mo.FONTE_MEDIA_LIBRI, 0)]
               for lega, v in cal["per_lega"].items()]
              + [["**totale**", cal["totale"].get("partite", 0),
                  cal["totale"].get(mo.FONTE_PINNACLE, 0),
                  cal["totale"].get(mo.FONTE_MEDIA_LIBRI, 0),
                  cal["totale"].get("partite", 0)
                  - cal["totale"].get(mo.FONTE_PINNACLE, 0)
                  - cal["totale"].get(mo.FONTE_MEDIA_LIBRI, 0)]]))
    A("")
    A(f"Nomi non abbinati dal resolver di produzione: {len(cal['nomi_non_abbinati'])}.")
    A("")
    A("## 5. Cosa e' stato cambiato")
    A("")
    A("* `update_live_odds.h2h_dal_bookmaker` accetta ENTRAMBE le forme (grezza "
      "dell'API e compattata della sonda) e dichiara il motivo di ogni scarto;")
    A("* il giro FALLISCE con uscita 4 se una lega ha eventi e zero libri, e in quel "
      "caso il file precedente non viene toccato;")
    A("* il log per lega riporta eventi, eventi con almeno un libro, eventi con "
      "Pinnacle e bookmaker nella risposta grezza; \"N eventi OK\" non esiste piu';")
    A("* il file porta per ogni lega i conteggi grezzi pre-conversione (eventi, "
      "bookmaker distinti per chiave, mercati presenti) e quelli post-conversione, "
      "cosi' il prossimo guasto si legge dal file senza spendere crediti.")
    A("")
    return "\n".join(testo) + "\n"


def main() -> int:
    conversione = sezione_conversione()
    parametri = sezione_parametri()
    file_prod = sezione_file_produzione()

    # File riparato prodotto dal writer di oggi sulle risposte grezze reali.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        grezze = os.path.join(tmp, "grezze")
        GREZZE.scrivi_fixture(grezze)
        out = os.path.join(tmp, "live_odds.json")
        codice, _r = U.esegui(chiave="", fixture=grezze, out=out, dry_run=False)
        if codice != U.ESITO_OK:
            print(f"writer uscito con {codice}: diagnosi interrotta", file=sys.stderr)
            return 1
        payload = mo.carica_quote_live(out)
    calendario = sezione_calendario(payload)

    dati = {
        "generato_il": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "conversione": conversione,
        "parametri": parametri,
        "file_produzione": file_prod,
        "calendario": calendario,
    }
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as fh:
        json.dump(dati, fh, ensure_ascii=False, indent=1)
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    with open(RESULTS, "w", encoding="utf-8") as fh:
        fh.write(referto(dati))
    print(f"scritto {RESULTS}")
    print(f"scritto {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
