"""Le righe del Registro che il replay di OGGI non ritrova, una per una (SOLA LETTURA).

Domanda a cui risponde: la tabella Legacy della stagione in corso ha piu' righe
di quella del Drago a 2 Teste. Quante di quelle righe il replay di oggi **non le
propone affatto**, e **di che periodo sono**?

Il conto si fa con un confronto esatto, non a occhio:

* le righe del Registro si leggono con lo stesso strato del resto del programma
  (``registry_coverage_check.load_registry_readonly``: mai descrivere JSONBin
  quando il backend attivo e' Upstash);
* le righe che il replay propone sono nel suo referto JSON
  (``replay_legacy_topmix.json``, scritto dallo stesso run: ``entries_current`` +
  ``entries_legacy``, piu' le ``non_scritte``);
* la chiave di confronto e' ``dedup_key`` (match_id, origine, versione del
  selettore, variante): nient'altro.

Per ogni riga non ritrovata si stampa **data della partita, partita, quando e'
stata scritta, variante letta e stagione**, cosi' si vede subito se il motivo e'
"partita giocata prima della finestra ricostruibile" o qualcos'altro (una riga
scritta **dopo** l'inizio della finestra che il replay non riproduce piu' e' un
caso diverso, e va visto, non nascosto).

Nessuna scrittura, in nessun caso: questo strumento legge e riferisce.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from prediction_registry import (  # noqa: E402
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_LABELS,
    MODEL_VARIANT_LEGACY,
    dedup_key,
    entry_instant,
    model_variant_read,
    origin_of,
)
from registry_coverage_check import load_registry_readonly  # noqa: E402
from replay_legacy_topmix import PR24_MERGE_INSTANT, REPLAY_START_INSTANT  # noqa: E402
from season_calendar import season_label, season_start_year_of  # noqa: E402

VARIANTI = (MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY)


def _istante(riga: Dict[str, Any]) -> Optional[datetime]:
    return entry_instant(riga)[0]


def _kickoff(riga: Dict[str, Any]) -> Optional[datetime]:
    """Data della partita (per il confronto con la finestra). ``None`` se non si legge."""
    from prediction_registry import parse_datetime, parse_kickoff, KICKOFF_UTC_FIELD
    ko = parse_kickoff(riga.get(KICKOFF_UTC_FIELD))
    if ko is not None:
        return ko
    return parse_datetime(riga.get("data"))


def _stagione(riga: Dict[str, Any]) -> str:
    """Stagione della riga: il campo se c'e', altrimenti dalla data (mai vuota).

    Stesso calendario del resto del progetto (``season_calendar``). Una riga senza
    ne' campo ne' data leggibile finisce in ``Sconosciuta`` e lo dichiara: non si
    inventa una stagione, ma nemmeno si perde la riga dal conto.
    """
    campo = str(riga.get("stagione") or "").strip()
    if campo:
        return campo
    istante, _fonte = entry_instant(riga)
    if istante is None:
        return "Sconosciuta"
    return season_label(season_start_year_of(istante.date()))


def periodo(riga: Dict[str, Any]) -> str:
    """In che periodo sta la riga: partita E scrittura, rispetto ai due confini.

    I confini sono quelli veri del progetto: l'inizio della finestra ricostruibile
    (``REPLAY_START_INSTANT``, 30/08/2026 11:27 UTC) e il merge di PR#24
    (``PR24_MERGE_INSTANT``, 04/09/2026 16:50 UTC).
    """
    k = _kickoff(riga)
    n = _istante(riga)
    parte_partita = ("partita prima della finestra" if k is not None and k < REPLAY_START_INSTANT
                     else ("partita dentro la finestra" if k is not None else "partita non leggibile"))
    if n is None:
        parte_scrittura = "scrittura non leggibile"
    elif n < REPLAY_START_INSTANT:
        parte_scrittura = "scritta prima della finestra"
    elif n < PR24_MERGE_INSTANT:
        parte_scrittura = "scritta nella finestra, prima del merge"
    else:
        parte_scrittura = "scritta DOPO il merge"
    return f"{parte_partita} · {parte_scrittura}"


def confronta(righe: List[Dict[str, Any]], proposte: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Registro vs righe proposte dal replay: chi c'e' e chi non e' stato ritrovato."""
    chiavi = {tuple(dedup_key(p)) for p in proposte}
    top_mix = [r for r in righe if str(origin_of(r) or "").strip().lower() == "top_mix"]
    non_ritrovate: List[Dict[str, Any]] = []
    for r in top_mix:
        if tuple(dedup_key(r)) in chiavi:
            continue
        non_ritrovate.append({
            "match_id": r.get("match_id"),
            "home": r.get("home"), "away": r.get("away"),
            "data_partita": r.get("data"), "campionato": r.get("campionato"),
            # Sempre TESTO e sempre una stagione vera: nel Registro ci sono righe
            # senza campo ``stagione`` (valore assente) e ordinare chiavi miste
            # testo/None fa esplodere il referto (successo sul Registro vero). Il
            # campo mancante si ricava dalla DATA, con lo stesso calendario del
            # resto del progetto (``season_calendar``), cosi' i numeri di questo
            # referto e quelli della composizione parlano la stessa lingua.
            "stagione": _stagione(r),
            "salvato_il": r.get("salvato_il"),
            "variante": model_variant_read(r),
            "periodo": periodo(r),
        })
    # Solo le righe della STAGIONE IN CORSO sono la domanda: le altre sono catalogo.
    stagioni = Counter(x["stagione"] for x in non_ritrovate)
    return {
        "righe_registro": len(righe),
        "righe_top_mix": len(top_mix),
        "proposte_dal_replay": len(chiavi),
        "non_ritrovate": non_ritrovate,
        "non_ritrovate_per_stagione": dict(stagioni),
        "non_ritrovate_per_periodo": dict(Counter(x["periodo"] for x in non_ritrovate)),
        "non_ritrovate_per_variante": dict(Counter(x["variante"] for x in non_ritrovate)),
    }


def righe_testo(d: Dict[str, Any], *, stagione: Optional[str] = None) -> List[str]:
    L = ["## Righe del Registro che il replay di oggi NON ritrova (sola lettura)", ""]
    L.append(f"- righe del Registro: **{d['righe_registro']}** · Top Mix: **{d['righe_top_mix']}** · "
             f"righe proposte dal replay: **{d['proposte_dal_replay']}**")
    L.append("- non ritrovate per stagione: "
             + (", ".join(f"**{k}** {v}" for k, v in sorted(d["non_ritrovate_per_stagione"].items()))
                or "nessuna"))
    L.append("- non ritrovate per variante letta: "
             + (", ".join(f"{MODEL_VARIANT_LABELS.get(k, k)} {v}"
                          for k, v in sorted(d["non_ritrovate_per_variante"].items())) or "nessuna"))
    L.append("")
    L.append("| periodo | righe |")
    L.append("|---|---|")
    for periodo, n in sorted(d["non_ritrovate_per_periodo"].items(), key=lambda kv: -kv[1]):
        L.append(f"| {periodo} | {n} |")
    selezione = [x for x in d["non_ritrovate"]
                 if stagione is None or str(x.get("stagione") or "") == stagione]
    L.append("")
    L.append(f"### Elenco ({len(selezione)} righe"
             + (f", stagione {stagione}" if stagione else "") + ")")
    for x in sorted(selezione, key=lambda x: (str(x.get("data_partita") or ""), str(x.get("home") or ""))):
        L.append(f"- {x['data_partita']} · {x['home']} - {x['away']} · {x['campionato']} · "
                 f"scritta {x['salvato_il']} · {MODEL_VARIANT_LABELS.get(x['variante'], x['variante'])} · "
                 f"match_id {x['match_id']} · {x['periodo']}")
    return L


def righe_compatti(d: Dict[str, Any], *, stagione: Optional[str] = None) -> List[str]:
    """Righe brevi per i referti con tetto di caratteri (annotazioni di CI)."""
    out = ["NONRITROVATE| " + " | ".join([
        f"Top Mix {d['righe_top_mix']}",
        f"proposte dal replay {d['proposte_dal_replay']}",
        "non ritrovate: " + ", ".join(f"{k} {v}" for k, v in sorted(d["non_ritrovate_per_stagione"].items())),
    ])]
    for periodo, n in sorted(d["non_ritrovate_per_periodo"].items(), key=lambda kv: -kv[1]):
        out.append(f"PERIODO| {n} righe · {periodo}")
    for x in sorted(d["non_ritrovate"],
                    key=lambda x: (str(x.get("data_partita") or ""), str(x.get("home") or ""))):
        if stagione is not None and str(x.get("stagione") or "") != stagione:
            continue
        out.append(f"RIGA| {x['data_partita']} | {x['home']} - {x['away']} | {x['campionato']} | "
                   f"scritta {x['salvato_il']} | {x['variante']} | id {x['match_id']} | {x['periodo']}")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--replay-json", default=None,
                    help="referto JSON del replay (entries_current/entries_legacy)")
    ap.add_argument("--stagione", default=None, help="limita l'elenco a una stagione (es. 2026/2027)")
    ap.add_argument("--compatto", action="store_true", help="righe brevi prefissate per le annotazioni")
    ap.add_argument("--json", dest="json_out", default=None, help="scrive il dettaglio in JSON")
    args = ap.parse_args(argv)

    righe, fonte = load_registry_readonly()
    if righe is None:
        print("::error title=non-ritrovate::Registro non leggibile (ne' remoto ne' locale)")
        return 2
    proposte: List[Dict[str, Any]] = []
    if args.replay_json and os.path.exists(args.replay_json):
        with open(args.replay_json, encoding="utf-8") as f:
            report = json.load(f)
        for campo in ("entries_current", "entries_legacy",
                      "entries_current_non_scritte", "entries_legacy_non_scritte"):
            proposte.extend(report.get(campo) or [])
    else:
        print(f"::error title=non-ritrovate::referto del replay non trovato ({args.replay_json}): "
              "senza le righe proposte il confronto non si puo' fare")
        return 2

    d = confronta(righe, proposte)
    d["fonte"] = fonte
    d["replay_json"] = args.replay_json
    testo = ("\n".join(righe_compatti(d, stagione=args.stagione)) if args.compatto
             else "\n".join(righe_testo(d, stagione=args.stagione)))
    print(testo)
    if fonte not in ("upstash", "jsonbin"):
        print(f"::warning title=non-ritrovate::sto leggendo la copia '{fonte}', NON il Registro vivo")
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
