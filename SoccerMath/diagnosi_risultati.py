"""Diagnosi (SOLA LETTURA) delle giocate 1X2 rimaste in attesa nel Registro.

Perche' esiste. Dal 23/10/2026 le righe 1X2 del Registro restano ``⏳`` anche a
partita finita («Nessun nuovo risultato»), mentre le giocate gol si aggiornano.
Il codice dei risultati (``app._applica_esiti``) non cambia dalla PR 81, quindi
la diagnosi non tocca l'app: osserva i DATI e la risposta dell'API replicando,
senza eseguire il grading, l'UNICA chiamata che quel ramo fa.

Che cosa fa, in ordine:

1. legge il Registro vivo (e, per il conteggio del giro, quello ombra) da
   Upstash con il SOLO comando ``HGETALL`` — nessuna scrittura, da nessuna
   parte: niente ``HSET``/``HDEL``/``SET``, niente file, niente salvataggi;
2. calcola un'impronta sha256 del contenuto grezzo dell'hash PRIMA delle
   chiamate football-data e la ricalcola DOPO: le due impronte devono essere
   identiche, ed e' la prova (stampata nel referto) che la diagnosi non ha
   toccato il Registro;
3. seleziona le righe 1X2 in attesa instradate dal ramo «per giornata» di
   ``_applica_esiti`` (``giornata`` presente e ``match_id`` numerico, vedi
   ``app._applica_esiti``) il cui calcio d'inizio e' passato da piu' di 3 ore;
4. per ognuna stampa partita, campionato, mercato, giornata SALVATA,
   ``match_id`` e il suo TIPO Python (numero/testo); poi, una sola volta per
   ogni (campionato, giornata) — come fa la cache di ``_applica_esiti`` —
   ripete la chiamata per giornata di produzione
   (``GET /v4/competitions/{comp}/matches?matchday={giornata}&status=FINISHED``)
   e stampa: codice HTTP, intestazione ``X-Requests-Available-Minute`` se
   presente, numero di partite nella risposta, e se l'id della riga e'
   presente nella risposta COME NUMERO, COME TESTO, e con la ricerca ESATTA
   di produzione (``match_id in {m["id"]: m}``, dove le chiavi sono gli id
   JSON dell'API). E' quest'ultimo confronto a decidere se la riga resta
   ``⏳``: ``app.py`` costruisce ``{m["id"]: m}`` e cerca ``p["match_id"]``
   senza conversioni, quindi un id salvato come testo non trova MAI la
   chiave numerica, anche se la partita e' nella risposta;
5. fra una chiamata e l'altra aspetta 7 secondi (``time.sleep`` DENTRO lo
   script): ~8,5 chiamate/minuto al massimo, sotto il limite free di
   football-data (10/minuto), cosi' la diagnosi non puo' farsi tagliare
   fuori da un 429 e non ne provoca per l'app;
6. conta quante chiamate farebbe UN GIRO INTERO di
   ``app.aggiorna_risultati_reali`` sui dati di oggi (Registro vivo + ombra,
   cache condivisa come in produzione): gruppi per giornata, gruppi
   (lega, giorno) del ramo senza giornata, chiamate dirette per match_id
   delle righe a giornata 0. Solo conteggio, dai dati gia' letti: per
   questo numero non parte nessuna chiamata in piu'.

Uso (in CI, dal workflow ``diagnosi_risultati.yml``):

    python SoccerMath/diagnosi_risultati.py

Variabili d'ambiente: ``UPSTASH_REDIS_REST_URL``/``UPSTASH_REDIS_REST_TOKEN``
(sola lettura), ``FOOTBALL_DATA_API_KEY``, ``REGISTRY_BACKEND=upstash``.
Nessuna chiave viene mai stampata.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import registry_store as rs  # noqa: E402
from config import LEAGUE_CODE_MAP  # noqa: E402
from prediction_registry import (  # noqa: E402
    DATA_FIELD,
    KICKOFF_UTC_FIELD,
    parse_datetime,
    parse_kickoff,
    selector_version_of,
)
from team_names import resolve_team_name  # noqa: E402

UTC = timezone.utc
ORE_MINIME = 3
PAUSA_CHIAMATE = 7.0  # secondi FRA una chiamata football-data e l'altra
API_PER_GIORNATA = "https://api.football-data.org/v4/competitions/{comp}/matches"

# Mercati della famiglia 1X2 (codici ``mercato_standard``, gli stessi di
# ``prediction_registry._GRADING`` per il ramo a esito secco/doppia chance).
# La selezione primaria pero' e' quella del RAMO di ``_applica_esiti``
# (giornata + match_id numerico): il mercato viene stampato, non filtrato,
# cosi' il referto mostra anche eventuali codici inattesi.
MERCATI_1X2 = ("1", "X", "2", "1X", "X2", "12")


def tipo(valore: Any) -> str:
    """Tipo del valore come lo vede il confronto di produzione: numero o testo."""
    if isinstance(valore, bool):
        return "booleano"
    if isinstance(valore, (int, float)):
        return "numero"
    if isinstance(valore, str):
        return "testo"
    if valore is None:
        return "assente"
    return type(valore).__name__


def match_id_numerico(valore: Any) -> bool:
    """Copia di ``app._match_id_numerico`` (l'app non si importa: tira Streamlit).

    True se ``valore`` e' un id football-data (intero o stringa di cifre).
    Nota: una stringa di cifre e' «numerica» per questa funzione e la riga va
    nel ramo per giornata, ma la ricerca ``m_id in {m["id"]: m}`` di quel
    ramo confronta testo con chiavi numeriche e fallisce sempre.
    """
    if valore is None or isinstance(valore, bool):
        return False
    if isinstance(valore, int):
        return True
    return isinstance(valore, str) and valore.strip().isdigit()


def kickoff_riga(riga: Dict[str, Any]) -> Optional[datetime]:
    """Istante della partita: ``kickoff_utc`` (autorevole) o ``data`` italiana."""
    ko = parse_kickoff(riga.get(KICKOFF_UTC_FIELD))
    if ko is not None:
        return ko
    return parse_datetime(riga.get(DATA_FIELD))


def impronta_hash(campi: Dict[str, Any]) -> str:
    """sha256 del contenuto GREZZO dell'hash (campo -> valore, ordinato).

    Due letture con la stessa impronta = contenuto identico byte per byte:
    e' il confronto prima/dopo che dichiara «nessuna scrittura».
    """
    h = hashlib.sha256()
    for campo in sorted(campi):
        valore = campi[campo]
        testo = valore if isinstance(valore, str) else json.dumps(
            valore, ensure_ascii=False, sort_keys=True, default=str)
        h.update(campo.encode("utf-8"))
        h.update(b"\n")
        h.update(testo.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def leggi_hash_grezzo(chiave: str) -> Dict[str, Any]:
    """SOLO ``HGETALL``: l'unico comando Upstash di tutta la diagnosi."""
    risultato = rs.upstash_raw(["HGETALL", chiave]).get("result")
    return rs.hash_da_risposta(risultato, dove="HGETALL diagnosi")


def in_attesa(righe: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Righe in attesa come in ``_applica_esiti``: esito None/``⏳``, con campionato."""
    return [p for p in righe
            if p.get("esito") in (None, "⏳") and p.get("campionato") is not None]


def instradamento(riga: Dict[str, Any]) -> str:
    """In quale ramo di ``_applica_esiti`` finisce la riga (stessa condizione)."""
    if riga.get("giornata") is not None and match_id_numerico(riga.get("match_id")):
        return "per_giornata"
    return "senza_giornata"


def seleziona_1x2(righe: Sequence[Dict[str, Any]], *, adesso: datetime,
                  ore_minime: int = ORE_MINIME) -> List[Dict[str, Any]]:
    """Righe 1X2 (ramo per giornata) in attesa, calcio d'inizio > ``ore_minime`` fa."""
    soglia = adesso - timedelta(hours=ore_minime)
    fuori: List[Dict[str, Any]] = []
    for r in in_attesa(righe):
        if instradamento(r) != "per_giornata":
            continue
        ko = kickoff_riga(r)
        if ko is None or ko > soglia:
            continue
        fuori.append(r)
    return sorted(fuori, key=lambda r: (kickoff_riga(r) or datetime.min.replace(tzinfo=UTC),
                                        str(r.get("campionato") or ""),
                                        str(r.get("home") or "")))


def coppia_canonica(home: Any, away: Any) -> Optional[Tuple[str, str]]:
    """Copia del criterio di ``app._coppia_canonica`` (resolver di produzione)."""
    h = resolve_team_name(home)
    a = resolve_team_name(away)
    if not (h.mapped and a.mapped):
        return None
    return (h.canonical, a.canonical)


def conta_chiamate_giro(registro_vivo: Sequence[Dict[str, Any]],
                        registro_ombra: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Quante GET farebbe UN giro di ``aggiorna_risultati_reali`` su questi dati.

    Rispecchia ``_applica_esiti`` chiamato due volte (vivo, poi ombra) con la
    STESSA cache, come in produzione:

    * ramo per giornata (giornata != 0): 1 GET per (competizione, giornata)
      distinta nell'intero giro, chiavi ``("giornata", comp, giornata)``;
    * righe a giornata 0: 1 GET diretta per match_id, PER RIGA (nessuna cache);
    * ramo senza giornata: 1 GET per (competizione, giorno del kickoff)
      distinta, chiavi ``("ou_giorno", comp, giorno)``, e solo per le righe
      con campionato riconosciuto, giorno leggibile e coppia risolta (le
      altre non fanno partire nessuna chiamata nemmeno in produzione).

    Nessuna chiamata parte davvero: il conteggio usa solo le righe gia' lette.
    """
    cache_giornata: set = set()
    cache_ou: set = set()
    dirette_match_id = 0
    dettaglio: Dict[str, Dict[str, Any]] = {}
    for nome, righe in (("vivo", registro_vivo), ("ombra", registro_ombra)):
        attese = in_attesa(righe)
        per_g, senza_g = 0, 0
        for r in attese:
            if instradamento(r) == "senza_giornata":
                senza_g += 1
                comp = LEAGUE_CODE_MAP.get(r.get("campionato"))
                ko = kickoff_riga(r)
                giorno = None if ko is None else ko.strftime("%Y-%m-%d")
                coppia = coppia_canonica(r.get("home"), r.get("away"))
                if not comp or giorno is None or coppia is None:
                    continue  # in produzione: log e resta ⏳, nessuna chiamata
                cache_ou.add(("ou_giorno", comp, giorno))
                continue
            per_g += 1
            giornata = r.get("giornata")
            if giornata == 0:
                if r.get("match_id"):
                    dirette_match_id += 1
                continue
            comp = LEAGUE_CODE_MAP.get(r.get("campionato"))
            if not comp:
                continue
            cache_giornata.add(("giornata", comp, giornata))
        dettaglio[nome] = {"in_attesa": len(attese), "per_giornata": per_g,
                           "senza_giornata": senza_g}
    totale = len(cache_giornata) + len(cache_ou) + dirette_match_id
    return {"per_registro": dettaglio,
            "chiamate_per_giornata": len(cache_giornata),
            "gruppi_per_giornata": sorted(f"{c}/{g}" for _k, c, g in cache_giornata),
            "chiamate_senza_giornata": len(cache_ou),
            "gruppi_senza_giornata": sorted(f"{c}/{g}" for _k, c, g in cache_ou),
            "chiamate_dirette_match_id": dirette_match_id,
            "totale": totale}


def chiamata_per_giornata(comp: str, giornata: Any, api_key: str) -> Dict[str, Any]:
    """La GET per giornata ESATTA di ``_applica_esiti`` (stessi params/headers).

    Ritorna codice HTTP, header di rate-limit e gli id delle partite, tenuti
    sia come numeri (il tipo JSON dell'API) sia come testo: e' il confronto
    che la riga in attesa non supera se il suo ``match_id`` e' salvato come
    stringa.
    """
    import requests
    esito: Dict[str, Any] = {"http": None, "x_requests_available_minute": None,
                             "errore": "", "ids_numero": [], "ids_testo": [],
                             "n_partite": 0}
    try:
        r = requests.get(API_PER_GIORNATA.format(comp=comp),
                         headers={"X-Auth-Token": api_key},
                         params={"matchday": giornata, "status": "FINISHED"},
                         timeout=15)
    except Exception as e:  # rete: dichiarato, mai interpretato come "assente"
        esito["errore"] = f"{type(e).__name__}: {e}"
        return esito
    esito["http"] = r.status_code
    esito["x_requests_available_minute"] = r.headers.get("X-Requests-Available-Minute")
    if r.status_code != 200:
        return esito
    try:
        partite = r.json().get("matches", []) or []
    except Exception as e:
        esito["errore"] = f"risposta non JSON: {e}"
        return esito
    esito["n_partite"] = len(partite)
    esito["ids_numero"] = [m.get("id") for m in partite]
    esito["ids_testo"] = [str(m.get("id")) for m in partite]
    return esito


def main() -> int:
    adesso = datetime.now(UTC)
    api_key = os.getenv("FOOTBALL_DATA_API_KEY", "").strip()
    print(f"DIAGNOSI| inizio {adesso.isoformat()} | sola lettura: unico comando "
          f"Upstash HGETALL, nessuna scrittura da nessuna parte")
    if not api_key:
        print("::error title=diagnosi::FOOTBALL_DATA_API_KEY assente: la chiamata "
              "per giornata non si puo' ripetere")
        return 2

    # 1) Lettura grezza (impronta PRIMA) e righe, Registro vivo e ombra.
    chiave_vivo = rs.hash_key()
    chiave_ombra = rs.shadow_hash_key()
    grezzo_prima = leggi_hash_grezzo(chiave_vivo)
    impronta_prima = impronta_hash(grezzo_prima)
    vivo = rs.upstash_rows(chiave=chiave_vivo)
    ombra = rs.upstash_rows(chiave=chiave_ombra)
    print(f"REGISTRO| chiave {chiave_vivo} | campi grezzi {len(grezzo_prima)} | "
          f"righe lette {len(vivo)} | righe ombra lette {len(ombra)}")
    print(f"IMPRONTA-PRIMA| sha256 {impronta_prima}")

    attese_vivo = in_attesa(vivo)
    ramo = {"per_giornata": 0, "senza_giornata": 0}
    for r in attese_vivo:
        ramo[instradamento(r)] += 1
    mercati_attesa = sorted({str(r.get("mercato_standard")) for r in attese_vivo})
    print(f"IN-ATTESA| vivo {len(attese_vivo)} (per_giornata {ramo['per_giornata']}, "
          f"senza_giornata {ramo['senza_giornata']}) | ombra {len(in_attesa(ombra))} | "
          f"mercati in attesa: {', '.join(mercati_attesa)}")

    # 2) Selezione richiesta: 1X2 in attesa, calcio d'inizio passato da >3 ore.
    selezionate = seleziona_1x2(vivo, adesso=adesso)
    fuori_mercato = [r for r in selezionate
                     if str(r.get("mercato_standard") or "").strip().upper() not in MERCATI_1X2]
    print(f"SELEZIONE| righe 1X2 (ramo per giornata) in attesa con calcio d'inizio "
          f"passato da piu' di {ORE_MINIME} ore: {len(selezionate)}"
          + (f" | di cui con mercato fuori dalla famiglia 1X2 {MERCATI_1X2}: "
             f"{len(fuori_mercato)}" if fuori_mercato else ""))

    # 3) Una chiamata per (campionato, giornata), come la cache di produzione,
    #    con 7 secondi FRA una chiamata e l'altra (dentro lo script).
    gruppi: Dict[Tuple[Any, Any], List[Dict[str, Any]]] = {}
    for r in selezionate:
        gruppi.setdefault((r.get("campionato"), r.get("giornata")), []).append(r)
    print(f"CHIAMATE| gruppi (campionato, giornata) distinti: {len(gruppi)} | "
          f"pausa fra le chiamate: {PAUSA_CHIAMATE:.0f}s (~{60.0 / (PAUSA_CHIAMATE + 1):.1f}/min "
          f"con ~1s di chiamata, sotto il limite di 10/min)")

    esiti_chiamate: Dict[Tuple[Any, Any], Dict[str, Any]] = {}
    for i, (camp, giornata) in enumerate(sorted(gruppi, key=lambda x: (str(x[0]), str(x[1])))):
        if i > 0:
            time.sleep(PAUSA_CHIAMATE)
        comp = LEAGUE_CODE_MAP.get(camp)
        if not comp:
            esiti_chiamate[(camp, giornata)] = {
                "http": None, "x_requests_available_minute": None,
                "errore": f"campionato {camp!r} non in LEAGUE_CODE_MAP "
                          f"(in produzione: nessuna chiamata, riga resta in attesa)",
                "ids_numero": [], "ids_testo": [], "n_partite": 0}
            continue
        esiti_chiamate[(camp, giornata)] = chiamata_per_giornata(comp, giornata, api_key)

    for (camp, giornata), esito_c in esiti_chiamate.items():
        comp = LEAGUE_CODE_MAP.get(camp)
        print(f"CHIAMATA| campionato {camp} (codice {comp}) | giornata salvata "
              f"{giornata!r} ({tipo(giornata)}) | GET competitions/{comp}/matches"
              f"?matchday={giornata}&status=FINISHED | HTTP {esito_c['http']} | "
              f"X-Requests-Available-Minute: "
              f"{esito_c['x_requests_available_minute'] if esito_c['x_requests_available_minute'] is not None else 'assente'} | "
              f"partite nella risposta: {esito_c['n_partite']}"
              + (f" | errore: {esito_c['errore']}" if esito_c["errore"] else ""))

    # 4) Referto riga per riga.
    trovate_produzione = 0
    for r in selezionate:
        m_id = r.get("match_id")
        esito_c = esiti_chiamate[(r.get("campionato"), r.get("giornata"))]
        come_numero = False
        if isinstance(m_id, str) and m_id.strip().isdigit():
            come_numero = int(m_id.strip()) in esito_c["ids_numero"]
        elif isinstance(m_id, int) and not isinstance(m_id, bool):
            come_numero = m_id in esito_c["ids_numero"]
        # La ricerca ESATTA di app.py: chiavi = id JSON (numeri), nessun cast.
        come_testo = str(m_id) in esito_c["ids_testo"]
        lookup = m_id in {i: None for i in esito_c["ids_numero"]}
        if lookup:
            trovate_produzione += 1
        ko = kickoff_riga(r)
        print(f"RIGA| {r.get('home')} - {r.get('away')} | campionato {r.get('campionato')} | "
              f"mercato {r.get('mercato_standard')} | calcio d'inizio "
              f"{ko.isoformat() if ko else 'illeggibile'} | giornata salvata "
              f"{r.get('giornata')!r} ({tipo(r.get('giornata'))}) | match_id {m_id!r} "
              f"({tipo(m_id)}) | selettore {selector_version_of(r)} | "
              f"HTTP {esito_c['http']} | X-Requests-Available-Minute: "
              f"{esito_c['x_requests_available_minute'] if esito_c['x_requests_available_minute'] is not None else 'assente'} | "
              f"id presente come numero: {'SI' if come_numero else 'NO'} | "
              f"come testo: {'SI' if come_testo else 'NO'} | "
              f"ricerca di _applica_esiti (match_id originale in dict a chiavi numeriche): "
              f"{'SI' if lookup else 'NO -> resta in attesa'}")

    # 5) Quante chiamate fa UN GIRO INTERO di aggiorna_risultati_reali (oggi).
    giro = conta_chiamate_giro(vivo, ombra)
    print(f"GIRO-INTERO| un giro di aggiorna_risultati_reali sui dati di oggi farebbe "
          f"{giro['totale']} chiamate: {giro['chiamate_per_giornata']} per giornata "
          f"(gruppi: {', '.join(giro['gruppi_per_giornata']) or 'nessuno'}), "
          f"{giro['chiamate_senza_giornata']} per (lega, giorno) del ramo senza giornata "
          f"(gruppi: {', '.join(giro['gruppi_senza_giornata']) or 'nessuno'}), "
          f"{giro['chiamate_dirette_match_id']} dirette per match_id (giornata 0) | "
          f"dettaglio per registro: {giro['per_registro']} | cache condivisa vivo+ombra "
          f"come in produzione")

    # 6) Impronta DOPO: deve essere identica alla PRIMA (nessuna scrittura).
    grezzo_dopo = leggi_hash_grezzo(chiave_vivo)
    impronta_dopo = impronta_hash(grezzo_dopo)
    print(f"IMPRONTA-DOPO| sha256 {impronta_dopo}")
    identica = impronta_dopo == impronta_prima and len(grezzo_dopo) == len(grezzo_prima)
    print(f"VERIFICA| impronta prima == dopo: {'SI' if identica else 'NO'} | "
          f"righe selezionate {len(selezionate)} | trovate dalla ricerca di produzione: "
          f"{trovate_produzione} | nessuna scrittura effettuata (solo HGETALL e GET)")
    if not identica:
        print("::error title=diagnosi::impronta del Registro cambiata durante la "
              "diagnosi: qualcuno/qualcosa ha scritto mentre leggevamo")
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
