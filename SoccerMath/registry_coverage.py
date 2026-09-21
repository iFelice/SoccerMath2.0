"""Copertura per modello nel Registro: chi ha una riga e chi no.

La commessa "Top Mix a due modelli" chiede che, PER OGNI partita del periodo
coperto dal replay, il Registro abbia sia la scelta del modello attuale sia
quella del modello legacy: "stesso campione, stessa lunghezza, per entrambi".
Questo modulo misura esattamente quello, senza fidarsi della logica che scrive
le righe:

* una "partita coperta" da un modello = una riga Top Mix di quel modello nel
  Registro, identificata da ``match_id`` (o, quando manca, dalla terna
  casa/trasferta/kickoff);
* il confronto fra i due insiemi da': quante partite hanno ENTRAMBI i modelli,
  quante solo l'uno, quante solo l'altro;
* il motivo della differenza e' quasi sempre lo stesso: la partita non supera
  le soglie del selettore (0,55 1X2 / 0,60 Totali) per quel modello, oppure il
  veto di disaccordo |P-E| >= 0,25 la scarta. E' una differenza legittima, non
  un buco: il selettore non inventa una scelta per far tornare i conti.

E' usato sia dal replay (per dire in anticipo cosa scrivera') sia dal
controllo in sola lettura del Registro live (``registry_coverage_check.py``).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prediction_registry import (
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_LABELS,
    MODEL_VARIANT_LEGACY,
    MODEL_VARIANT_SOURCE_UNKNOWN,
    ORIGIN_TOP_MIX,
    TWO_MODELS_MERGE_INSTANT,
    entry_instant,
    model_variant_read,
    model_variant_read_source,
    origin_of,
)

VARIANTI = (MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY)


def _parse_data_italiana(valore: Any) -> Optional[date]:
    """Le righe del Registro hanno 'data' = 'gg/mm/aaaa HH:MM' (o ISO per i vecchi)."""
    if not isinstance(valore, str) or not valore.strip():
        return None
    testo = valore.strip()
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(testo, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(testo.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def row_day(row: Dict[str, Any]) -> Optional[date]:
    """Giorno della partita: dal kickoff UTC se c'e' (autorevole), altrimenti da 'data'."""
    ko = row.get("kickoff_utc")
    if isinstance(ko, str) and ko.strip():
        try:
            dt = datetime.fromisoformat(ko.strip().replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).date()
        except ValueError:
            pass
    return _parse_data_italiana(row.get("data"))


def match_key(row: Dict[str, Any]) -> Tuple[Any, ...]:
    """Identita' della PARTITA (non della riga): match_id, o la terna casa/trasferta/ora."""
    mid = row.get("match_id")
    if mid not in (None, "", 0):
        return ("id", str(mid))
    return ("nomi", str(row.get("home") or "").strip().lower(),
            str(row.get("away") or "").strip().lower(),
            str(row.get("kickoff_utc") or row.get("data") or ""))


def _nel_periodo(row: Dict[str, Any], day_from: Optional[date], day_to: Optional[date]) -> bool:
    giorno = row_day(row)
    if giorno is None:
        return day_from is None and day_to is None
    if day_from and giorno < day_from:
        return False
    if day_to and giorno > day_to:
        return False
    return True


def top_mix_rows(rows: Iterable[Dict[str, Any]], day_from: Optional[date] = None,
                 day_to: Optional[date] = None) -> List[Dict[str, Any]]:
    """Righe Top Mix (qualunque variante) del periodo indicato."""
    return [r for r in rows if isinstance(r, dict)
            and origin_of(r) == ORIGIN_TOP_MIX and _nel_periodo(r, day_from, day_to)]


def coverage_by_variant(rows: Iterable[Dict[str, Any]], day_from: Optional[date] = None,
                        day_to: Optional[date] = None) -> Dict[str, Any]:
    """Copertura per variante sul periodo: insiemi, conteggi e differenze.

    Ritorna un dizionario serializzabile (niente set: liste ordinate), pronto
    per il referto e per il JSON.
    """
    per_variante: Dict[str, Dict[Tuple[Any, ...], Dict[str, Any]]] = {v: {} for v in VARIANTI}
    # La variante si LEGGE con la data quando il campo manca (una riga nata
    # prima del merge di PR#24 e' del motore di allora, cioe' il legacy): e'
    # ``model_variant_read``, non ``model_variant_of``, che resta la convenzione
    # del percorso di scrittura.
    for r in top_mix_rows(rows, day_from, day_to):
        per_variante[model_variant_read(r)].setdefault(match_key(r), r)

    insiemi = {v: set(per_variante[v]) for v in VARIANTI}
    comuni = insiemi[MODEL_VARIANT_CURRENT] & insiemi[MODEL_VARIANT_LEGACY]

    def _riga(variante: str, chiave: Tuple[Any, ...]) -> Dict[str, Any]:
        r = per_variante[variante][chiave]
        return {
            "partita": f"{r.get('home')} - {r.get('away')}",
            "campionato": r.get("campionato"),
            "data": r.get("data"),
            "kickoff_utc": r.get("kickoff_utc"),
            "mercato": r.get("mercato_standard"),
            "prob": r.get("prob_sicuro"),
            "esito": r.get("esito"),
            "match_id": r.get("match_id"),
            # Da dove viene la variante (campo esplicito o istante della riga):
            # senza questo, una riga senza campo sembra una riga del replay.
            "variante_da": model_variant_read_source(r),
        }

    solo_c = sorted(insiemi[MODEL_VARIANT_CURRENT] - insiemi[MODEL_VARIANT_LEGACY], key=str)
    solo_l = sorted(insiemi[MODEL_VARIANT_LEGACY] - insiemi[MODEL_VARIANT_CURRENT], key=str)
    return {
        "finestra": [day_from.isoformat() if day_from else None, day_to.isoformat() if day_to else None],
        "partite": {v: len(insiemi[v]) for v in VARIANTI},
        "comuni": len(comuni),
        "solo": {MODEL_VARIANT_CURRENT: [_riga(MODEL_VARIANT_CURRENT, k) for k in solo_c],
                 MODEL_VARIANT_LEGACY: [_riga(MODEL_VARIANT_LEGACY, k) for k in solo_l]},
        "righe_totali": {v: sum(1 for r in top_mix_rows(rows, day_from, day_to)
                                if model_variant_read(r) == v) for v in VARIANTI},
        "pareggio": len(solo_c) == 0 and len(solo_l) == 0,
    }


def render_coverage(cov: Dict[str, Any]) -> str:
    """Referto testuale del confronto di copertura (per log, summary e PR)."""
    L: List[str] = []
    f = cov.get("finestra") or [None, None]
    L.append(f"Copertura Top Mix nel periodo {f[0]} → {f[1]}:")
    for v in VARIANTI:
        etichetta = MODEL_VARIANT_LABELS.get(v, v)
        L.append(f"- modello {etichetta}: {cov['partite'][v]} partite "
                 f"({cov['righe_totali'][v]} righe)")
    L.append(f"- partite con ENTRAMBI i modelli: {cov['comuni']}")
    for v in VARIANTI:
        etichetta = MODEL_VARIANT_LABELS.get(v, v)
        sole = cov["solo"][v]
        if sole:
            L.append(f"- solo modello {etichetta}: {len(sole)} partite")
            for r in sole[:20]:
                L.append(f"    · {r['partita']} ({r['campionato']}, {r['data']}) {r['mercato']} {r['prob']}% {r['esito']}")
            if len(sole) > 20:
                L.append(f"    · … e altre {len(sole) - 20}")
    L.append("- i due campioni COINCIDONO" if cov["pareggio"]
             else "- i due campioni NON coincidono: le partite mancanti sono quelle sotto le soglie "
                  "del selettore (0,55 1X2 / 0,60 Totali) o scartate dal veto di disaccordo per QUEL modello")
    return "\n".join(L)
