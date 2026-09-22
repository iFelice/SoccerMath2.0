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
  quante non ce l'hanno (record storici: il campo non esisteva). Quelle senza
  campo si leggono **con la data** (``model_variant_read``): una riga nata
  prima del merge di PR#24 e' del motore che girava allora, cioe' il ``legacy``;
  una nata dopo e' del ``current``. Il conteggio e' diviso fra le due epoche e
  dichiara la fonte dell'istante (``salvato_il``, ``kickoff_utc``, ``data``);
  un istante ignoto resta ``current`` ma viene contato a parte;
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
    MODEL_VARIANT_SOURCE_UNKNOWN,
    TWO_MODELS_MERGE_INSTANT,
    entry_instant,
    match_key,
    model_variant_read,
    model_variant_read_source,
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


def _nata_prima(riga: Dict[str, Any]) -> Optional[bool]:
    """La riga e' nata prima del merge di PR#24? ``None`` se l'istante non si legge."""
    dt, _ = entry_instant(riga)
    if dt is None:
        return None
    return dt < TWO_MODELS_MERGE_INSTANT


def _conteggi(righe: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Conteggi per variante su un insieme di righe Top Mix (una partita = una voce)."""
    per_variante: Dict[str, Dict[Tuple[Any, ...], Dict[str, Any]]] = {
        MODEL_VARIANT_CURRENT: {}, MODEL_VARIANT_LEGACY: {}}
    # Tutte le righe di ogni partita, per variante: una partita puo' averne piu'
    # d'una (un click vero dell'epoca senza campo + una riga del replay).
    righe_per_partita: Dict[str, Dict[Tuple[Any, ...], List[Dict[str, Any]]]] = {
        MODEL_VARIANT_CURRENT: {}, MODEL_VARIANT_LEGACY: {}}
    for r in righe:
        variante = model_variant_read(r)
        chiave = match_key(r)
        per_variante[variante].setdefault(chiave, r)
        righe_per_partita[variante].setdefault(chiave, []).append(r)
    insiemi = {v: set(per_variante[v]) for v in per_variante}
    comuni = insiemi[MODEL_VARIANT_CURRENT] & insiemi[MODEL_VARIANT_LEGACY]
    solo_c = sorted(insiemi[MODEL_VARIANT_CURRENT] - insiemi[MODEL_VARIANT_LEGACY], key=str)
    solo_l = sorted(insiemi[MODEL_VARIANT_LEGACY] - insiemi[MODEL_VARIANT_CURRENT], key=str)

    def _dettaglio(variante: str, chiavi: List[Tuple[Any, ...]]) -> List[Dict[str, Any]]:
        def _voce(k: Tuple[Any, ...]) -> Dict[str, Any]:
            r = per_variante[variante][k]
            gruppo = righe_per_partita[variante][k]
            # Due specie di righe per la stessa partita, e non si escludono:
            # quelle scritte dal REPLAY (campo variante esplicito) e i click
            # VERI dell'epoca, senza campo perche' non esisteva. La variante di
            # quei click e' decisa dall'ISTANTE (prima del merge di PR#24 -> il
            # motore di allora, cioe' legacy); qui si dichiara anche da dove
            # viene la decisione, cosi' nessuna riga sembra quello che non e'.
            return {"partita": f"{r.get('home')} - {r.get('away')}",
                    "data": r.get("data"),
                    "campionato": r.get("campionato"),
                    "mercato": r.get("mercato_standard"),
                    "prob": r.get("prob_sicuro"),
                    "match_id": r.get("match_id"),
                    "righe": len(gruppo),
                    "riga_del_replay": any(_ha_variante_esplicita(x) for x in gruppo),
                    "riga_storica": any(not _ha_variante_esplicita(x) for x in gruppo),
                    "variante_esplicita": _ha_variante_esplicita(r),
                    "variante_da": model_variant_read_source(r),
                    # Quando e' NATA la riga: e' l'istante che decide la
                    # variante quando il campo manca, quindi va dichiarato. Una
                    # riga nata prima del merge per una partita giocata dopo e'
                    # il caso che rende sbagliato leggerla come "attuale".
                    "salvato_il": r.get("salvato_il"),
                    "riga_nata_prima_della_fusione": _nata_prima(r)}
        return [_voce(k) for k in chiavi]

    senza = [r for r in righe if not _ha_variante_esplicita(r)]
    fonti: Dict[str, int] = {}
    for r in senza:
        fonte = model_variant_read_source(r)
        fonti[fonte] = fonti.get(fonte, 0) + 1
    return {
        "righe": len(righe),
        "righe_con_variante_esplicita": sum(1 for r in righe if _ha_variante_esplicita(r)),
        "righe_senza_variante": len(senza),
        # Le righe senza campo: quante nate prima del merge di PR#24 (lette
        # legacy) e quante dopo (lette current), con la fonte dell'istante.
        "senza_etichetta": {
            "prima_della_fusione": sum(1 for r in senza if model_variant_read(r) == MODEL_VARIANT_LEGACY),
            # Un istante che non si riesce a leggere non e' "dopo la fusione":
            # e' un'incognita, e si conta a parte invece di gonfiare il current.
            "dopo_la_fusione": sum(1 for r in senza if fonti.get(model_variant_read_source(r))
                                   and model_variant_read(r) == MODEL_VARIANT_CURRENT),
            "istante_ignoto": fonti.get(MODEL_VARIANT_SOURCE_UNKNOWN, 0),
            "fonti": fonti,
        },
        "partite": {v: len(insiemi[v]) for v in insiemi},
        "righe_totali": {v: sum(1 for r in righe if model_variant_read(r) == v) for v in insiemi},
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
    # Incrocio fra quando e' NATA la riga e quando si e' giocata la partita: e'
    # l'incrocio che dice quante righe senza etichetta sono state lette male
    # dalla convenzione a default fisso (nate prima del merge = del motore di
    # allora, anche se la partita si e' giocata dopo).
    senza = [r for r in nel_periodo if not _ha_variante_esplicita(r)]
    incrocio = {"nate_prima_partita_prima": 0, "nate_prima_partita_dopo": 0,
                "nate_dopo_partita_prima": 0, "nate_dopo_partita_dopo": 0, "istante_ignoto": 0}
    for r in senza:
        nata_prima = _nata_prima(r)
        if nata_prima is None:
            incrocio["istante_ignoto"] += 1
        elif nata_prima and c["prima_di_pr24"](r):
            incrocio["nate_prima_partita_prima"] += 1
        elif nata_prima:
            incrocio["nate_prima_partita_dopo"] += 1
        elif c["prima_di_pr24"](r):
            incrocio["nate_dopo_partita_prima"] += 1
        else:
            incrocio["nate_dopo_partita_dopo"] += 1
    return {
        "finestra": [c["inizio"].strftime("%Y-%m-%dT%H:%M:%SZ"), "adesso"],
        "confine_pr24": c["merge_pr24"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "incrocio_nascita_partita": incrocio,
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
    se = intero["senza_etichetta"]
    L.append(f"- righe SENZA etichetta ({intero['righe_senza_variante']}): **{se['prima_della_fusione']} nate "
             f"prima del merge di PR#24** (lette `legacy`: allora in produzione girava quel motore) · "
             f"**{se['dopo_la_fusione']} nate dopo** (lette `current`) · "
             f"**{se['istante_ignoto']} con istante illeggibile** (nessuna data: restano `current` per "
             f"convenzione e sono dichiarate) · fonti dell'istante: {se['fonti']}")
    inc = esito.get("incrocio_nascita_partita") or {}
    if inc:
        L.append(f"- righe senza etichetta per EPOCA: nate prima del merge e partite prima "
                 f"({inc['nate_prima_partita_prima']}) · **nate prima del merge e partite DOPO "
                 f"({inc['nate_prima_partita_dopo']})** (lette legacy: e' il motore che le ha "
                 f"prodotte, non la data della partita) · nate dopo e partite dopo "
                 f"({inc['nate_dopo_partita_dopo']}) · istante illeggibile ({inc['istante_ignoto']})")
    if intero["pareggio"]:
        L.append("- **i due campioni COINCIDONO**: ogni partita del periodo ha entrambi i modelli")
    else:
        n_c = intero["partite"][MODEL_VARIANT_CURRENT]
        n_l = intero["partite"][MODEL_VARIANT_LEGACY]
        solo_c = len(intero["solo"][MODEL_VARIANT_CURRENT])
        solo_l = len(intero["solo"][MODEL_VARIANT_LEGACY])
        L.append(f"- **i due campioni NON coincidono**: il modello attuale copre {n_c} partite, il legacy "
                 f"{n_l}; {solo_c + solo_l} partite le copre UN SOLO modello "
                 f"({solo_c} solo attuale, {solo_l} solo legacy). Dove manca l'ATTUALE la causa va "
                 f"MISURATA (diagnosi: sotto soglia, veto o buco del replay); dove manca il LEGACY vale "
                 f"lo stesso: sotto le soglie del selettore 0,55 1X2 / 0,60 Totali o scartata dal veto")
    for variante in (MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY):
        voci = intero["solo"][variante]
        if voci:
            etichetta = MODEL_VARIANT_LABELS.get(variante, variante)
            replay = sum(1 for v in voci if v.get("riga_del_replay"))
            storiche = sum(1 for v in voci if v.get("riga_storica"))
            L.append(f"- partite coperte SOLO dal modello {etichetta} ({len(voci)}): "
                     f"con una riga del REPLAY {replay}, con un CLICK VERO dell'epoca "
                     f"{storiche} (campo variante assente; le due condizioni possono "
                     f"valere per la stessa partita)")
            for v in voci[:8]:
                da = v.get("variante_da")
                L.append(f"    · {v['partita']} ({v['campionato']}, {v['data']}) "
                         f"{v['mercato']} {v['prob']}% · variante da: {da}")
            if len(voci) > 8:
                L.append(f"    · … e altre {len(voci) - 8}")
    # Il modello ATTUALE manca dove il Registro ha solo il legacy: quelle righe
    # il replay le puo' scrivere (aggiunge, non sovrascrive), ma solo se il
    # motore attuale esprime una scelta: la causa va MISURATA dalla diagnosi,
    # non dedotta qui. Il contrario (manca il LEGACY) non si scrive mai.
    mancanti_attuale = intero["solo"][MODEL_VARIANT_LEGACY]
    mancanti_legacy = intero["solo"][MODEL_VARIANT_CURRENT]
    L.append(f"- partite senza la riga del modello ATTUALE (il Registro ha solo il legacy): "
             f"**{len(mancanti_attuale)}** — se il motore attuale esprime una scelta si scrivono "
             f"rilanciando il replay (aggiunge, non sovrascrive); se non la esprime (sotto soglia o "
             f"veto) la riga NON va scritta: la diagnosi lo misura partita per partita")
    L.append(f"- partite senza la riga del modello LEGACY (il Registro ha solo l'attuale): "
             f"**{len(mancanti_legacy)}** — non si scrivono a tavolino: sarebbero righe sotto soglia o "
             f"scartate dal veto, cioe' un campione falsato (vietato dalla commessa)")
    L.append(f"- gate: le partite senza la riga ATTUALE sono {len(mancanti_attuale)}; la run resta "
             f"VERDE solo se la diagnosi ne spiega ognuna (sotto soglia o veto). Un solo motivo non "
             f"attribuito le rende ROSSE.")
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
