"""registry_store.py - Dove vive il Registro delle previsioni, con due backend.

Il problema che questo modulo risolve: il Registro era **un unico documento**
riscritto per intero a ogni salvataggio. Con JSONBin significa (a) sbattere
contro il tetto del piano free (100 kB per record: misurato, il replay lo
supera) e (b) rischiare che un click dell'app fallisca per colpa di righe
scritte giorni prima, e in piu' il tempo di scrittura cresce con lo storico.

Qui la lettura e la scrittura remote passano da un solo punto, con due backend:

* ``jsonbin`` (attuale, default): GET/PUT del bin intero;
* ``upstash`` (nuovo): hash Redis via REST, **una riga = un campo**, quindi la
  scrittura tocca solo le righe nuove o cambiate (``HSET``), non tutto il
  Registro.

La scelta e' una variabile d'ambiente/segreto ``REGISTRY_BACKEND``: con
``jsonbin`` (o assente) il comportamento e' **identico a prima**, byte per byte.
Nessun percorso di questo modulo scrive senza che il chiamante lo chieda.

Nota sul perche' non si perde nulla: la chiave di campo e' ``dedup_key``
(``match_id``, origine, versione del selettore, variante), la stessa che usa la
fusione delle righe. Due scrittori che aggiungono righe DIVERSE non possono
sovrascriversi, perche' scrivono campi diversi dello stesso hash: e' il
controprogetto del "riscrivi tutto", non una sua ottimizzazione.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

BACKEND_JSONBIN = "jsonbin"
BACKEND_UPSTASH = "upstash"
BACKENDS = (BACKEND_JSONBIN, BACKEND_UPSTASH)

HASH_KEY_DEFAULT = "sm:registro"
SNAPSHOT_PREFIX = "sm:registro:snapshot:"
TIMEOUT = 20


class RegistryStoreError(RuntimeError):
    """Errore di lettura/scrittura del Registro (mai silenzioso)."""


def backend() -> str:
    """Backend attivo: ``REGISTRY_BACKEND``, default ``jsonbin`` (= come prima)."""
    scelto = (os.getenv("REGISTRY_BACKEND") or BACKEND_JSONBIN).strip().lower()
    if scelto not in BACKENDS:
        raise RegistryStoreError(f"REGISTRY_BACKEND sconosciuto: {scelto!r} (attesi {BACKENDS})")
    return scelto


def _upstash_config() -> Tuple[str, str]:
    url = (os.getenv("UPSTASH_REDIS_REST_URL") or "").strip().rstrip("/")
    token = (os.getenv("UPSTASH_REDIS_REST_TOKEN") or "").strip()
    return url, token


def hash_key() -> str:
    return (os.getenv("REGISTRY_HASH_KEY") or HASH_KEY_DEFAULT).strip() or HASH_KEY_DEFAULT


def field_of(row: Dict[str, Any]) -> str:
    """Chiave di campo dell'hash = ``dedup_key`` della riga, in forma stabile.

    Gli elementi di ``dedup_key`` sono codici (id numerico, origine, versione
    del selettore, variante) e non contengono il separatore; il campo resta
    quindi leggibile a occhio quando si guarda l'hash in console.
    """
    from prediction_registry import dedup_key
    return "|".join("" if p is None else str(p) for p in dedup_key(row))


def _row_from_value(valore: Any) -> Optional[Dict[str, Any]]:
    if isinstance(valore, dict):
        return valore
    if not isinstance(valore, str) or not valore.strip():
        return None
    try:
        riga = json.loads(valore)
    except json.JSONDecodeError:
        return None
    return riga if isinstance(riga, dict) else None


def hash_da_risposta(risultato: Any, *, dove: str = "HGETALL") -> Dict[str, Any]:
    """Normalizza la risposta di ``HGETALL``: oggetto JSON **oppure** array piatto.

    L'API REST di Upstash risponde con un array piatto (``["campo", "valore", ...]``,
    forma RESP2) se il client non negozia la forma oggetto: i dati ci sono, ma
    leggerli come se fossero un oggetto significherebbe vedere un Registro vuoto.
    E' esattamente quello che e' successo nella prima copia: 108 righe scritte e
    "0 righe" in rilettura. Qui si accettano entrambe le forme e una risposta
    inattesa **alza** invece di essere interpretata come "vuoto" (su un percorso
    di scrittura, "vuoto" vuol dire riscrivere tutto).
    """
    if risultato is None:
        return {}
    if isinstance(risultato, dict):
        return risultato
    if isinstance(risultato, list):
        if len(risultato) % 2 != 0:
            raise RegistryStoreError(f"Upstash: {dove} ha risposto con un array di "
                                     f"lunghezza dispari ({len(risultato)})")
        coppie: Dict[str, Any] = {}
        for i in range(0, len(risultato), 2):
            campo = risultato[i]
            if not isinstance(campo, str):
                raise RegistryStoreError(f"Upstash: {dove} ha risposto con un campo "
                                         f"non testuale ({type(campo).__name__})")
            coppie[campo] = risultato[i + 1]
        return coppie
    raise RegistryStoreError(f"Upstash: {dove} ha risposto in forma inattesa "
                             f"({type(risultato).__name__})")


def chiavi_da_risposta(risultato: Any) -> List[str]:
    """Normalizza la risposta di ``KEYS``: array, stringa separata da spazi o nulla."""
    if risultato is None:
        return []
    if isinstance(risultato, list):
        return [str(k) for k in risultato]
    if isinstance(risultato, str):
        return [k for k in risultato.split("\n") if k.strip()]
    return [str(risultato)]


def _righe_ordinate(righe: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ordine deterministico: per campo (stessa chiave dell'hash)."""
    return sorted(righe, key=field_of)


# ---------------------------------------------------------------------------
# Upstash (Redis via REST)
# ---------------------------------------------------------------------------
def upstash_raw(comando: List[Any], *, post=None) -> Dict[str, Any]:
    """Esegue UN comando e ritorna la risposta GREZZA (per diagnosi e referti).

    La diagnosi serve quando una scrittura "riesce" ma non si ritrova: sapere
    cosa ha risposto davvero il servizio (``result`` o ``error``) e' l'unico modo
    di distinguere un problema di permessi da uno di replica o di chiave.
    """
    import requests
    url, token = _upstash_config()
    if not url or not token:
        raise RegistryStoreError("Upstash non configurato: mancano UPSTASH_REDIS_REST_URL/TOKEN")
    invia = post or requests.post
    r = invia(url, json=comando, headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
    corpo: Any
    try:
        corpo = r.json()
    except Exception:
        corpo = {"_non_json": str(getattr(r, "text", "") or "")[:300]}
    if not isinstance(corpo, dict):
        corpo = {"result": corpo}
    if getattr(r, "status_code", None) != 200:
        raise RegistryStoreError(f"Upstash HTTP {getattr(r, 'status_code', '?')}: "
                                 f"{str(corpo)[:300]}")
    if corpo.get("error"):
        raise RegistryStoreError(f"Upstash: {corpo['error']}")
    return corpo


def _upstash_cmd(comando: List[Any], *, post=None) -> Any:
    """Esegue UN comando Redis via REST. Ritorna il campo ``result``."""
    return upstash_raw(comando, post=post).get("result")


def upstash_rows(*, post=None) -> List[Dict[str, Any]]:
    """Tutte le righe dell'hash (1 comando: ``HGETALL``)."""
    risultato = _upstash_cmd(["HGETALL", hash_key()], post=post)
    valori = hash_da_risposta(risultato)
    righe = [r for r in (_row_from_value(v) for v in valori.values()) if r is not None]
    return _righe_ordinate(righe)


def upstash_save(righe: Iterable[Dict[str, Any]], *, post=None) -> Dict[str, Any]:
    """Scrive SOLO i campi nuovi o cambiati: ``HGETALL`` + un ``HSET``.

    Una riga gia' presente e identica viene saltata: rilanciare un salvataggio
    non produce nessuna scrittura (idempotenza, la stessa garanzia della fusione
    con ``dedup_key``).
    """
    attuale = hash_da_risposta(_upstash_cmd(["HGETALL", hash_key()], post=post))
    coppie: List[str] = []
    scritte = saltate = 0
    risposta: Any = None
    for riga in righe:
        campo = field_of(riga)
        valore = json.dumps(riga, ensure_ascii=False, sort_keys=True, default=str)
        if campo in attuale and attuale[campo] == valore:
            saltate += 1
            continue
        coppie.extend([campo, valore])
        scritte += 1
    comandi = 1                                     # la HGETALL
    if coppie:
        # La risposta del servizio viene riportata: se l'hash poi non contiene
        # quello che abbiamo scritto, il "perche'" sta in quel valore.
        risposta = _upstash_cmd(["HSET", hash_key()] + coppie, post=post)
        comandi += 1
    return {"remoto": "ok", "backend": BACKEND_UPSTASH, "comandi": comandi,
            "righe_scritte": scritte, "righe_saltate": saltate,
            "righe_hash": len(attuale) + scritte,
            "risposta_scrittura": risposta,
            "byte": sum(len(c.encode("utf-8")) for c in coppie)}


def snapshot_key(giorno: str) -> str:
    return f"{SNAPSHOT_PREFIX}{giorno}"


def upstash_snapshot(giorno: str, righe: Iterable[Dict[str, Any]], *, post=None) -> Dict[str, Any]:
    """Istantanea giornaliera (1 comando ``SET``): punto di ripristino, e termine
    di confronto "prima/dopo". Non e' lo storico completo: e' UNA fotografia al
    giorno, e la chiave del giorno viene riscritta se il comando viene rilanciato.
    """
    lista = list(righe)
    chiave = snapshot_key(giorno)
    corpo = json.dumps(lista, ensure_ascii=False)
    risposta = _upstash_cmd(["SET", chiave, corpo], post=post)
    return {"chiave": chiave, "righe": len(lista), "byte": len(corpo.encode("utf-8")),
            "risposta": risposta}


def upstash_snapshot_read(giorno: str, *, post=None) -> Optional[List[Dict[str, Any]]]:
    """Rilegge l'istantanea di un giorno (1 comando ``GET``). ``None`` se assente."""
    corpo = _upstash_cmd(["GET", snapshot_key(giorno)], post=post)
    if corpo is None:
        return None
    try:
        dati = json.loads(corpo)
    except (TypeError, json.JSONDecodeError) as e:
        raise RegistryStoreError(f"istantanea {giorno} illeggibile: {e}") from e
    if not isinstance(dati, list):
        raise RegistryStoreError(f"istantanea {giorno}: attesa una lista, trovato {type(dati).__name__}")
    return dati


# ---------------------------------------------------------------------------
# JSONBin (comportamento attuale, invariato)
# ---------------------------------------------------------------------------
def jsonbin_rows(*, get=None, timeout: int = TIMEOUT) -> List[Dict[str, Any]]:
    import requests
    from config import JSONBIN_API_KEY, JSONBIN_BIN_ID
    if not (JSONBIN_API_KEY and JSONBIN_BIN_ID):
        raise RegistryStoreError("JSONBin non configurato: mancano JSONBIN_API_KEY/JSONBIN_BIN_ID")
    leggi = get or requests.get
    r = leggi(f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest",
              headers={"X-Master-Key": JSONBIN_API_KEY}, timeout=timeout)
    if getattr(r, "status_code", None) != 200:
        raise RegistryStoreError(f"JSONBin HTTP {getattr(r, 'status_code', '?')}")
    record = r.json().get("record", {})
    if isinstance(record, dict) and isinstance(record.get("data"), list):
        return record["data"]
    if isinstance(record, list):
        return record
    raise RegistryStoreError("JSONBin: registro in forma inattesa")


def jsonbin_save(righe: List[Dict[str, Any]], *, put=None) -> Dict[str, Any]:
    import requests
    from config import JSONBIN_API_KEY, JSONBIN_BIN_ID
    if not (JSONBIN_API_KEY and JSONBIN_BIN_ID):
        return {"remoto": "disattivato", "backend": BACKEND_JSONBIN}
    scrivi = put or requests.put
    payload = {"data": righe}
    byte = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    r = scrivi(f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}", json=payload,
               headers={"X-Master-Key": JSONBIN_API_KEY, "Content-Type": "application/json"},
               timeout=TIMEOUT)
    esito = {"backend": BACKEND_JSONBIN, "byte": byte, "remoto": "ok"}
    if getattr(r, "status_code", None) != 200:
        esito["remoto"] = "errore"
        esito["remoto_dettaglio"] = f"HTTP {getattr(r, 'status_code', '?')}: " \
                                    f"{str(getattr(r, 'text', '') or '')[:300]}"
    return esito


# ---------------------------------------------------------------------------
# Faccia unica per il resto del programma
# ---------------------------------------------------------------------------
def load_rows(*, strict: bool = False, get=None, post=None) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """Righe del Registro dal backend attivo. Ritorna ``(righe, fonte)``.

    ``fonte`` e' ``"jsonbin"``, ``"upstash"`` oppure ``"nessuno"`` (niente
    backend configurato: il chiamante puo' ricadere sul file locale). Con
    ``strict=True`` un errore di rete alza ``RegistryStoreError`` invece di
    ricadere sul file: e' il comportamento che serve PRIMA di una scrittura,
    perche' un registro remoto illeggibile non deve diventare una copia locale.
    """
    scelto = backend()
    try:
        if scelto == BACKEND_UPSTASH:
            return upstash_rows(post=post), BACKEND_UPSTASH
        return jsonbin_rows(get=get), BACKEND_JSONBIN
    except RegistryStoreError:
        if strict:
            raise
        return None, "nessuno"


def save_rows(righe: List[Dict[str, Any]], *, put=None, post=None) -> Dict[str, Any]:
    """Scrive il Registro sul backend attivo (il chiamante decide SE farlo)."""
    if backend() == BACKEND_UPSTASH:
        return upstash_save(righe, post=post)
    return jsonbin_save(righe, put=put)


def esito_scrittura(esito: Dict[str, Any]) -> Dict[str, Any]:
    """Normalizza l'esito per i chiamanti (app, replay, referti)."""
    out = {"backend": esito.get("backend", backend()), "remoto": esito.get("remoto", "errore")}
    for chiave in ("remoto_dettaglio", "byte", "comandi", "righe_scritte", "righe_saltate", "righe_hash"):
        if chiave in esito:
            out[chiave] = esito[chiave]
    return out


def confronto(a: List[Dict[str, Any]], b: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Differenza fra due Registri, per chiave di campo (sola lettura).

    Serve alla verifica di migrazione: ``solo_a``/``solo_b`` sono i campi
    presenti da una parte sola, ``diverse`` quelli presenti in entrambe con
    contenuto diverso.
    """
    mappa_a = {field_of(r): r for r in a}
    mappa_b = {field_of(r): r for r in b}
    solo_a = sorted(set(mappa_a) - set(mappa_b))
    solo_b = sorted(set(mappa_b) - set(mappa_a))
    diverse = []
    for campo in sorted(set(mappa_a) & set(mappa_b)):
        if json.dumps(mappa_a[campo], sort_keys=True, ensure_ascii=False, default=str) != \
           json.dumps(mappa_b[campo], sort_keys=True, ensure_ascii=False, default=str):
            diverse.append(campo)
    return {"righe_a": len(mappa_a), "righe_b": len(mappa_b), "solo_a": solo_a,
            "solo_b": solo_b, "diverse": diverse,
            "identici": not (solo_a or solo_b or diverse)}


def _secondi() -> float:                            # usato dai test per il backoff
    return time.time()
