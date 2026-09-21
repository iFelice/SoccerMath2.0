"""Composizione del Registro vivo: che specie di righe contiene (SOLA LETTURA).

Risponde a una domanda precisa, nata da una verifica in UI: "perche' la tabella
del modello legacy ha 127 righe e quella del modello attuale 77?". I due numeri
**non** sono due campioni dello stesso esperimento:

* la tabella legacy contiene TUTTE le righe lette ``legacy``, e fra queste ci
  sono righe che il Top Mix non ha mai prodotto (Analisi Rapida, Billy) e righe
  di partite che il modello attuale non avrebbe selezionato (sotto soglia o
  veto: la causa la misura ``diagnose_scarti_model_variant``);
* la tabella attuale contiene solo le righe del motore Elo post-fix PR#24.

Qui si contano le righe per **origine**, **variante letta** e **stagione**, e si
dichiara quante stanno dentro la finestra ricostruibile del replay (le sole che
si possono rigiocare onestamente). Nessuna scrittura: il Registro si legge e
basta (``registry_coverage_check.load_registry_readonly``, lo stesso strato del
resto del programma: mai descrivere JSONBin quando il backend attivo e' Upstash).

Uso:

    python SoccerMath/registry_composizione.py                 # testo
    python SoccerMath/registry_composizione.py --json out.json # anche JSON
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from prediction_registry import (  # noqa: E402
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_LABELS,
    MODEL_VARIANT_LEGACY,
    MODEL_VERSION_FIELD,
    entry_instant,
    is_current_model,
    model_variant_read,
    origin_of,
)
from registry_coverage_check import load_registry_readonly  # noqa: E402
from replay_legacy_topmix import REPLAY_START_INSTANT  # noqa: E402
from season_calendar import season_label, season_start_year_of  # noqa: E402

# Origini etichettate come le mostra la UI (``prediction_registry.tipo_for_origin``).
ORIGINI_NOTE = {
    "top_mix": "Top Mix",
    "analisi_rapida": "Analisi Rapida",
    "billy": "Billy",
}


def _etichetta_origine(origine: Any) -> str:
    testo = str(origine or "").strip().lower()
    if not testo:
        return "senza campo origine"
    return ORIGINI_NOTE.get(testo, f"altra origine ({testo})")


def _stagione(riga: Dict[str, Any]) -> str:
    """Stagione della riga: il campo se c'e', altrimenti dalla data.

    Il confine e' quello unico della pipeline (``season_calendar``, 1 luglio).
    Una riga senza data leggibile non si inventa: finisce in "Sconosciuta", e
    il conteggio lo dice (e' la stessa etichetta che mette la UI).
    """
    campo = str(riga.get("stagione") or "").strip()
    if campo:
        return campo
    istante, _fonte = entry_instant(riga)
    if istante is None:
        return "Sconosciuta"
    return season_label(season_start_year_of(istante.date()))


def _in_finestra(riga: Dict[str, Any]) -> Optional[bool]:
    """La riga sta nella finestra ricostruibile del replay? ``None`` se non si sa."""
    istante, _fonte = entry_instant(riga)
    if istante is None:
        return None
    return istante >= REPLAY_START_INSTANT


def dettaglio_riga(riga: Dict[str, Any]) -> str:
    """Una riga in una riga di testo: partita, data, origine, variante, scheda."""
    istante, fonte = entry_instant(riga)
    return (f"{riga.get('home')} - {riga.get('away')} · {riga.get('data') or 'data n/d'} · "
            f"origine `{riga.get('origin') or 'assente'}` · letto "
            f"{MODEL_VARIANT_LABELS.get(model_variant_read(riga), model_variant_read(riga))} · "
            f"nato {istante.strftime('%d/%m/%Y %H:%M') if istante else 'istante n/d'} "
            f"({fonte}) · `model_version` {riga.get(MODEL_VERSION_FIELD) or 'assente'} · "
            f"match_id {riga.get('match_id')}")


def analizza(righe: List[Dict[str, Any]], *, origini_escluse: Tuple[str, ...] = ("top_mix",)) -> Dict[str, Any]:
    """Conteggi della composizione: nessuna scrittura, nessuna finestra nascosta.

    ``origini_escluse`` sono le origini che NON si vogliono elencare riga per
    riga (default: ``top_mix``, che e' la grande maggioranza): nel risultato
    finisce l'**elenco** di tutte le altre, per rispondere a "quali partite sono
    quelle righe?", non solo a "quante sono".
    """
    per_origine: Counter = Counter()
    per_variante: Counter = Counter()
    per_stagione: Counter = Counter()
    incrocio = defaultdict(Counter)          # origine -> variante
    stagione_per_origine = defaultdict(Counter)   # origine -> stagione
    scheda_vecchia = Counter()               # origine -> righe senza model_version
    per_finestra = Counter()
    elenco: Dict[str, List[str]] = defaultdict(list)
    senza_campo_variante = 0
    istante_ignoto = 0
    for riga in righe:
        grezza = str(origin_of(riga) or "").strip().lower()
        origine = _etichetta_origine(origin_of(riga))
        variante = model_variant_read(riga)
        per_origine[origine] += 1
        per_variante[variante] += 1
        stagione = _stagione(riga)
        per_stagione[stagione] += 1
        incrocio[origine][variante] += 1
        stagione_per_origine[origine][stagione] += 1
        if grezza not in origini_escluse:
            elenco[origine].append(dettaglio_riga(riga))
        if not str(riga.get(MODEL_VERSION_FIELD) or "").strip():
            scheda_vecchia[origine] += 1
        dentro = _in_finestra(riga)
        per_finestra["dentro la finestra ricostruibile" if dentro else
                     ("fuori finestra (prima del 30/08/2026)" if dentro is False else
                      "istante non leggibile")] += 1
        if not str(riga.get("model_variant") or "").strip():
            senza_campo_variante += 1
        if entry_instant(riga)[0] is None:
            istante_ignoto += 1
    return {
        "righe": len(righe),
        "per_origine": dict(per_origine),
        "per_variante": dict(per_variante),
        "per_stagione": dict(per_stagione),
        "origine_per_variante": {k: dict(v) for k, v in incrocio.items()},
        "origine_per_stagione": {k: dict(v) for k, v in stagione_per_origine.items()},
        "senza_campo_variante": senza_campo_variante,
        "istante_ignoto": istante_ignoto,
        "scheda_vecchia_per_origine": dict(scheda_vecchia),
        "finestra": dict(per_finestra),
        "elenco": {k: sorted(v) for k, v in elenco.items()},
        "confine_finestra": REPLAY_START_INSTANT.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _righe_testo(d: Dict[str, Any]) -> List[str]:
    L: List[str] = ["## Composizione del Registro (sola lettura)", ""]
    L.append(f"- righe totali: **{d['righe']}** · finestra ricostruibile dal {d['confine_finestra']}")
    L.append("- per origine: " + ", ".join(f"**{k}** {v}" for k, v in sorted(d["per_origine"].items())))
    L.append("- per variante LETTA (campo o DATA): "
             + ", ".join(f"`{MODEL_VARIANT_LABELS.get(k, k)}` **{v}**"
                         for k, v in sorted(d["per_variante"].items())))
    L.append("- per stagione: " + ", ".join(f"**{k}** {v}" for k, v in sorted(d["per_stagione"].items())))
    L.append("- " + " · ".join(f"{k}: **{v}**" for k, v in sorted(d["finestra"].items())))
    L.append(f"- righe senza campo `model_variant`: **{d['senza_campo_variante']}** · "
             f"senza istante leggibile: **{d['istante_ignoto']}**")
    L.append("")
    L.append("| origine | righe | lette attuale | lette legacy | senza `model_version` | stagioni |")
    L.append("|---|---|---|---|---|---|")
    for origine, conteggi in sorted(d["origine_per_variante"].items(),
                                    key=lambda kv: -sum(kv[1].values())):
        stagioni = " · ".join(f"{s} {n}" for s, n in
                              sorted(d["origine_per_stagione"].get(origine, {}).items(), reverse=True))
        L.append(f"| {origine} | {sum(conteggi.values())} | "
                 f"{conteggi.get(MODEL_VARIANT_CURRENT, 0)} | "
                 f"{conteggi.get(MODEL_VARIANT_LEGACY, 0)} | "
                 f"{d['scheda_vecchia_per_origine'].get(origine, 0)} | {stagioni} |")
    for origine, voci in sorted(d["elenco"].items()):
        L.append("")
        L.append(f"### Elenco righe — origine {origine} ({len(voci)})")
        for voce in voci:
            L.append(f"- {voce}")
    return L


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", dest="json_out", default=None, help="scrive il dettaglio in JSON")
    ap.add_argument("--escludi", default="top_mix",
                    help="origini di cui NON elencare le righe una per una (default: top_mix, "
                         "cioe' si elencano tutte le righe che NON sono Top Mix)")
    args = ap.parse_args(argv)

    righe, fonte = load_registry_readonly()
    if righe is None:
        print("::error title=composizione::Registro non leggibile (ne' remoto ne' locale)")
        return 2
    d = analizza(righe, origini_escluse=tuple(
        o.strip().lower() for o in args.escludi.split(",") if o.strip()))
    d["fonte"] = fonte
    testo = "\n".join(_righe_testo(d)) + "\n"
    print(testo)
    if d["fonte"] not in ("upstash", "jsonbin"):
        print(f"::warning title=composizione::sto leggendo la copia '{d['fonte']}', "
              "NON il Registro vivo")
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        print(f"[composizione] json: {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
