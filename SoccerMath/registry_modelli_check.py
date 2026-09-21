"""registry_modelli_check.py - Sola lettura: i due modelli coprono lo stesso campione?

Risponde, sul Registro vero, alla domanda della commessa:

    per OGNI partita dell'intero periodo ricostruibile, il Registro ha sia la
    scelta del modello ATTUALE sia quella del LEGACY? stesso campione, stessa
    lunghezza per entrambi?

Non si fida di un numero a mano: legge il Registro dal **backend attivo**
(`registry_store`, quindi l'hash Upstash) e confronta gli insiemi di partite
coperte dai due modelli, separando i due lati della storia con lo STESSO confine
usato dalle due commesse (`replay_legacy_topmix.PR24_MERGE_INSTANT`, half-open) e
la stessa finestra dichiarata ricostruibile (`REPLAY_START_INSTANT`).

Dichiara anche tre cose che un conteggio secco nasconderebbe:

* quante righe hanno il campo variante **esplicito** (scritte dal replay) e
  quante non ce l'hanno (record storici: il campo non esisteva, il motore di
  allora era quello vecchio ma `model_variant_of` li legge come ``current``);
* quante partite ha ciascun modello **in più** dell'altro, con mercato e
  probabilita' del selettore che le ha scelte;
* se mancano righe del modello ATTUALE per partite che hanno solo il legacy:
  quelle si possono scrivere (rilanciando il replay, che aggiunge e non
  sovrascrive); il contrario NO, perche' vorrebbe dire scrivere righe sotto
  soglia o scartate dal veto — vietato dalla commessa.

NON scrive nulla: nessun PUT/HSET, nessun file di registro toccato.

Uso:
    python SoccerMath/registry_modelli_check.py
    python SoccerMath/registry_modelli_check.py --json out/modelli.json
    python SoccerMath/registry_modelli_check.py --allow-mismatch   # esce 0 anche se i campioni differiscono
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from registry_coverage import (  # noqa: E402
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_LABELS,
    MODEL_VARIANT_LEGACY,
    match_key,
    model_variant_of,
    row_day,
    top_mix_rows,
)

ESITO_PAREGGIO = 0
ESITO_DISPARI = 1
ESITO_ERRORE = 2


def _modulo_replay():
    import replay_legacy_topmix as replay
    return replay


def confini() -> Dict[str, Any]:
    """I confini della storia ricostruibile, presi dalla fonte unica (il replay)."""
    r = _modulo_replay()
    return {"inizio": r.REPLAY_START_INSTANT, "inizio_giorno": r.REPLAY_START_DAY,
            "merge_pr24": r.PR24_MERGE_INSTANT, "prima_di_pr24": r._prima_di_pr24}


def _ha_variante_esplicita(riga: Dict[str, Any]) -> bool:
    return bool(str(riga.get("model_variant") or "").strip())


def _conteggi(righe: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Conteggi per variante su un insieme di righe Top Mix (una partita = una voce)."""
    per_variante: Dict[str, Dict[Tuple[Any, ...], Dict[str, Any]]] = {
        MODEL_VARIANT_CURRENT: {}, MODEL_VARIANT_LEGACY: {}}
    for r in righe:
        per_variante[model_variant_of(r)].setdefault(match_key(r), r)
    insiemi = {v: set(per_variante[v]) for v in per_variante}
    comuni = insiemi[MODEL_VARIANT_CURRENT] & insiemi[MODEL_VARIANT_LEGACY]
    solo_c = sorted(insiemi[MODEL_VARIANT_CURRENT] - insiemi[MODEL_VARIANT_LEGACY], key=str)
    solo_l = sorted(insiemi[MODEL_VARIANT_LEGACY] - insiemi[MODEL_VARIANT_CURRENT], key=str)

    def _dettaglio(variante: str, chiavi: List[Tuple[Any, ...]]) -> List[Dict[str, Any]]:
        def _voce(k: Tuple[Any, ...]) -> Dict[str, Any]:
            r = per_variante[variante][k]
            return {"partita": f"{r.get('home')} - {r.get('away')}",
                    "data": r.get("data"),
                    "campionato": r.get("campionato"),
                    "mercato": r.get("mercato_standard"),
                    "prob": r.get("prob_sicuro"),
                    "match_id": r.get("match_id"),
                    # Una riga senza campo variante e' un click VERO dell'epoca
                    # (il campo non esisteva): la convenzione la legge come
                    # "current", ma non e' una riga scritta dal replay. Chi legge
                    # i conteggi deve poterlo distinguere.
                    "variante_esplicita": _ha_variante_esplicita(r)}
        return [_voce(k) for k in chiavi]

    return {
        "righe": len(righe),
        "righe_con_variante_esplicita": sum(1 for r in righe if _ha_variante_esplicita(r)),
        "righe_senza_variante": sum(1 for r in righe if not _ha_variante_esplicita(r)),
        "partite": {v: len(insiemi[v]) for v in insiemi},
        "righe_totali": {v: sum(1 for r in righe if model_variant_of(r) == v) for v in insiemi},
        "comuni": len(comuni),
        "solo": {MODEL_VARIANT_CURRENT: _dettaglio(MODEL_VARIANT_CURRENT, solo_c),
                 MODEL_VARIANT_LEGACY: _dettaglio(MODEL_VARIANT_LEGACY, solo_l)},
        "pareggio": not solo_c and not solo_l,
    }


def verifica(righe: List[Dict[str, Any]], *, oggi: Optional[date] = None) -> Dict[str, Any]:
    """Copertura dei due modelli: intero periodo + i due lati del confine PR#24."""
    c = confini()
    oggi = oggi or datetime.now(timezone.utc).date()
    nel_periodo = [r for r in top_mix_rows(righe, c["inizio_giorno"], oggi)
                   if (row_day(r) or c["inizio_giorno"]) >= c["inizio_giorno"]]
    prima = [r for r in nel_periodo if c["prima_di_pr24"](r)]
    dopo = [r for r in nel_periodo if not c["prima_di_pr24"](r)]
    return {
        "finestra": [c["inizio"].strftime("%Y-%m-%dT%H:%M:%SZ"), "adesso"],
        "confine_pr24": c["merge_pr24"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "vecchio": _conteggi(prima),
        "nuovo": _conteggi(dopo),
        "intero": _conteggi(nel_periodo),
    }


def _righe_referto(esito: Dict[str, Any]) -> List[str]:
    L: List[str] = ["## I due modelli nel Registro: stesso campione? (sola lettura)", ""]
    L.append(f"- finestra ricostruibile: **{esito['finestra'][0]} → adesso** · "
             f"confine PR#24: `{esito['confine_pr24']}` (half-open)")
    for nome, chiave in (("VECCHIO (prima di PR#24)", "vecchio"), ("NUOVO (da PR#24 in poi)", "nuovo"),
                         ("INTERO PERIODO", "intero")):
        c = esito[chiave]
        L.append(f"- **{nome}**: {c['righe']} righe ({c['righe_con_variante_esplicita']} con variante "
                 f"esplicita, {c['righe_senza_variante']} storiche senza) · partite: "
                 f"attuale **{c['partite'][MODEL_VARIANT_CURRENT]}**, legacy "
                 f"**{c['partite'][MODEL_VARIANT_LEGACY]}**, entrambi **{c['comuni']}**, "
                 f"solo attuale **{len(c['solo'][MODEL_VARIANT_CURRENT])}**, "
                 f"solo legacy **{len(c['solo'][MODEL_VARIANT_LEGACY])}**")
    intero = esito["intero"]
    mancanti_attuale = intero["solo"][MODEL_VARIANT_LEGACY]
    if intero["pareggio"]:
        L.append("- **i due campioni COINCIDONO**: ogni partita del periodo ha entrambi i modelli")
    else:
        delta = intero["partite"][MODEL_VARIANT_CURRENT] - intero["partite"][MODEL_VARIANT_LEGACY]
        L.append(f"- **i due campioni NON coincidono**: il modello attuale copre {delta} partite in piu'. "
                 f"Le partite mancanti sono quelle in cui il LEGACY non esprime una scelta (sotto le "
                 f"soglie del selettore 0,55 1X2 / 0,60 Totali, o scartate dal veto di disaccordo)")
    for variante in (MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY):
        voci = intero["solo"][variante]
        if voci:
            etichetta = MODEL_VARIANT_LABELS.get(variante, variante)
            esplicite = sum(1 for v in voci if v.get("variante_esplicita"))
            L.append(f"- partite coperte SOLO dal modello {etichetta} ({len(voci)}): "
                     f"{esplicite} righe del replay (variante esplicita), "
                     f"{len(voci) - esplicite} click veri dell'epoca (campo variante assente, "
                     f"letto come {etichetta} per convenzione)")
            for v in voci[:8]:
                L.append(f"    · {v['partita']} ({v['campionato']}, {v['data']}) "
                         f"{v['mercato']} {v['prob']}%")
            if len(voci) > 8:
                L.append(f"    · … e altre {len(voci) - 8}")
    come = ("nessuna: tutte le partite coperte dal legacy hanno anche l'attuale" if not mancanti_attuale
            else "si scrivono rilanciando il replay: aggiunge, non sovrascrive")
    L.append(f"- righe del modello ATTUALE da scrivere: **{len(mancanti_attuale)}** ({come})")
    L.append("- le righe mancanti del modello LEGACY non si scrivono: sarebbero righe sotto soglia o "
             "scartate dal veto, cioe' un campione falsato (vietato dalla commessa)" if
             intero["solo"][MODEL_VARIANT_CURRENT] else
             "- nessuna partita in cui il legacy manca: nulla da dichiarare")
    return L


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--registry", dest="registry_file", default=None, metavar="FILE",
                    help="misura su un FILE (copia fusa/archivio) invece che sul Registro vivo")
    ap.add_argument("--json", dest="json_out", default=None, help="scrive il dettaglio in JSON")
    ap.add_argument("--allow-mismatch", action="store_true",
                    help="esce 0 anche se i due campioni differiscono (default: esce 1)")
    args = ap.parse_args(argv)

    try:
        if args.registry_file:
            from registry_coverage_check import load_registry_file
            righe, fonte = load_registry_file(args.registry_file)
        else:
            from registry_coverage_check import load_registry_readonly
            righe, fonte = load_registry_readonly()
    except Exception as e:
        print(f"## I due modelli nel Registro: stesso campione? (sola lettura)\n\n"
              f"- **Registro non leggibile, nessuna verifica possibile** — {type(e).__name__}: {e}\n")
        if args.json_out:
            _scrivi_json(args.json_out, {"errore": f"{type(e).__name__}: {e}", "fonte": None})
        return ESITO_ERRORE

    esito = verifica(righe)
    esito["fonte"] = fonte
    esito["righe_totali"] = len(righe)
    esito["generato_il"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    L = [f"Registro ({fonte}): {len(righe)} righe totali"] + _righe_referto(esito)
    print("\n".join(L) + "\n")
    if args.json_out:
        _scrivi_json(args.json_out, esito)
    if not esito["intero"]["pareggio"] and not args.allow_mismatch:
        return ESITO_DISPARI
    return ESITO_PAREGGIO


def _scrivi_json(path: str, dati: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=2)
    print(f"[modelli] json: {path}")


if __name__ == "__main__":
    sys.exit(main())
