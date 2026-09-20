"""registry_migrate.py - Copia del Registro da JSONBin all'hash Upstash (fase C).

Fa UNA cosa: travasare il Registro che vive nel bin JSONBin nell'hash Redis di
Upstash, **senza perdere e senza sovrascrivere niente**. Le regole sono quelle
della migrazione dichiarata in ``audit/results/proposta_shard_registro.md`` §9.5:

1. si legge PRIMA JSONBin, in modo stretto: se il Registro non risponde, non si
   scrive nulla (un remoto illeggibile non deve diventare una copia parziale);
2. se l'hash ha gia' un campo con contenuto DIVERSO, ci si ferma **prima** di
   scrivere: non si sovrascrive una riga esistente, mai (esito 2);
3. si copia con ``registry_store.upstash_save``: una ``HGETALL`` + UN ``HSET`` di
   tutti i campi nuovi, quindi 2 comandi in tutto e nessuna finestra in cui il
   Registro e' a meta';
4. si RILEGGE e si confronta per chiave di campo: se non coincide riga per riga,
   l'operazione e' fallita (esito 1), anche se la scrittura e' passata;
5. default: prova a vuoto. Senza ``--esegui`` non parte nessuna scrittura.

JSONBin resta intatto: questo comando non fa nessun PUT.

Uso:
    python SoccerMath/registry_migrate.py                  # prova a vuoto
    python SoccerMath/registry_migrate.py --esegui         # copia + verifica
    python SoccerMath/registry_migrate.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import registry_store as rs  # noqa: E402

ESITO_OK = 0
ESITO_ERRORE = 1
ESITO_FERMATO = 2


def _valore(riga: Dict[str, Any]) -> str:
    """La stessa serializzazione che usa ``upstash_save`` per decidere se saltare."""
    return json.dumps(riga, ensure_ascii=False, sort_keys=True, default=str)


def pianifica() -> Dict[str, Any]:
    """Legge i due backend e dice cosa farebbe la copia. Non scrive nulla."""
    righe_jsonbin = rs.jsonbin_rows()
    righe_upstash = rs.upstash_rows()
    mappa_us = {rs.field_of(r): r for r in righe_upstash}
    da_copiare: List[str] = []
    gia_presenti: List[str] = []
    conflitti: List[str] = []
    for riga in righe_jsonbin:
        campo = rs.field_of(riga)
        if campo not in mappa_us:
            da_copiare.append(campo)
        elif _valore(mappa_us[campo]) == _valore(riga):
            gia_presenti.append(campo)
        else:
            conflitti.append(campo)
    return {
        "righe_jsonbin": len(righe_jsonbin),
        "righe_upstash": len(righe_upstash),
        "da_copiare": da_copiare,
        "gia_presenti": gia_presenti,
        "conflitti": conflitti,
        "righe_jsonbin_dati": righe_jsonbin,
        "comandi_previsti": 2 if da_copiare else 0,
    }


CHIAVE_DIAG = "sm:registro:diagnostica"


def diagnostica(*, post=None) -> Tuple[List[str], bool]:
    """Prova di andata e ritorno: UN campo, poi riletto. Sola diagnosi.

    Serve quando una scrittura "riesce" ma non si ritrova: distingue un problema
    di chiave (il valore c'e' ma sotto un altro nome), di permessi (il servizio
    risponde con un errore) o di conservazione (il servizio accetta e non
    conserva). Lascia il database come l'ha trovato (la chiave di prova viene
    rimossa se la scrittura si rilegge).
    """
    L: List[str] = ["## Diagnosi della scrittura su Upstash (sola prova, 1 campo)", ""]
    ok = False
    try:
        prima = rs.upstash_raw(["DBSIZE"], post=post).get("result")
        L.append(f"- DBSIZE prima: **{prima}**")
        marca = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        risposta = rs.upstash_raw(["HSET", CHIAVE_DIAG, "prova", marca], post=post)
        L.append(f"- `HSET {CHIAVE_DIAG} prova {marca}` -> risposta grezza: "
                 f"`{json.dumps(risposta, ensure_ascii=False)}`")
        grezzo = rs.upstash_raw(["HGETALL", CHIAVE_DIAG], post=post).get("result")
        L.append(f"- `HGETALL {CHIAVE_DIAG}` -> `{json.dumps(grezzo, ensure_ascii=False)}`")
        # La forma puo' essere un oggetto o un array piatto: si accettano entrambe.
        letto = rs.hash_da_risposta(grezzo)
        ok = letto.get("prova") == marca
        L.append("- **la scrittura si rilegge**: il database accetta e conserva"
                 if ok else
                 "- **la scrittura NON si rilegge**: il comando viene accettato ma il "
                 "valore non c'e' (chiave diversa, oppure replica in ritardo)")
        if ok:
            rs.upstash_raw(["DEL", CHIAVE_DIAG], post=post)
            L.append("- chiave di prova rimossa (`DEL`): il database torna com'era")
        dopo = rs.upstash_raw(["DBSIZE"], post=post).get("result")
        L.append(f"- DBSIZE dopo: **{dopo}**")
    except Exception as e:
        L.append(f"- **errore**: {type(e).__name__}: {e}")
    return L, ok


def _report(piano: Dict[str, Any], esito: Optional[Dict[str, Any]], verifica: Optional[Dict[str, Any]],
            eseguito: bool) -> Tuple[List[str], bool]:
    L: List[str] = ["## Migrazione del Registro: JSONBin -> Upstash (fase C)", ""]
    L.append("### Piano (prima di scrivere)")
    L.append(f"- JSONBin: **{piano['righe_jsonbin']} righe** · Upstash: **{piano['righe_upstash']} righe**")
    L.append(f"- da copiare: **{len(piano['da_copiare'])}** · gia' presenti identiche: "
             f"{len(piano['gia_presenti'])} · in conflitto: **{len(piano['conflitti'])}**")
    if piano["conflitti"]:
        L.append("- **conflitti**: il campo esiste sull'hash con contenuto diverso. Non si "
                 "sovrascrive niente: la copia si ferma qui.")
        for campo in piano["conflitti"][:5]:
            L.append(f"    · {campo}")
    ok = not piano["conflitti"]

    if esito is not None:
        L.append("")
        L.append("### Copia")
        L.append(f"- comandi inviati: **{esito.get('comandi')}** · righe scritte: "
                 f"**{esito.get('righe_scritte')}** · righe identiche saltate: {esito.get('righe_saltate')} · "
                 f"byte: {esito.get('byte')}")
        L.append(f"- righe dell'hash dopo la scrittura: {esito.get('righe_hash')}")
    elif eseguito:
        L.append("")
        L.append("### Copia: NON eseguita (nessuna scrittura inviata)")

    if verifica is not None:
        L.append("")
        L.append("### Verifica (rilettura dei due Registri)")
        L.append(f"- solo su JSONBin: {len(verifica['solo_a'])} · solo su Upstash: "
                 f"{len(verifica['solo_b'])} · contenuto diverso: {len(verifica['diverse'])}")
        L.append("- **i due Registri coincidono**: la copia e' completa e fedele"
                 if verifica["identici"] else
                 "- **i due Registri NON coincidono**: la copia NON e' valida")
        ok = ok and verifica["identici"]

    L.append("")
    if not eseguito:
        L.append("- modalita' **prova a vuoto**: nessuna scrittura inviata a Upstash")
        L.append("- per eseguire: `--esegui` (oppure tag `migra-registro-esegui-*`)")
    return L, ok


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--esegui", action="store_true",
                    help="scrive davvero sull'hash (senza, si ferma al piano)")
    ap.add_argument("--json", dest="json_out", default=None, help="scrive il dettaglio in JSON")
    ap.add_argument("--diagnostica", action="store_true",
                    help="prova di andata e ritorno con UN campo (non tocca il Registro)")
    args = ap.parse_args(argv)

    if args.diagnostica:
        try:
            righe, ok = diagnostica()
        except Exception as e:  # pragma: no cover - la diagnosi non deve mai esplodere
            righe, ok = [f"- errore: {type(e).__name__}: {e}"], False
        print("\n".join(righe) + "\n")
        if args.json_out:
            _scrivi_json(args.json_out, {"diagnostica": righe, "scrittura_riletta": ok})
        return ESITO_OK if ok else ESITO_ERRORE

    try:
        piano = pianifica()
    except Exception as e:
        print(f"## Migrazione del Registro: JSONBin -> Upstash (fase C)\n\n"
              f"- **lettura fallita, NESSUNA scrittura inviata**: {type(e).__name__}: {e}\n")
        if args.json_out:
            _scrivi_json(args.json_out, {"errore": f"{type(e).__name__}: {e}", "eseguito": False})
        return ESITO_ERRORE

    if piano["conflitti"]:
        testo, _ = _report(piano, None, None, eseguito=False)
        print("\n".join(testo) + "\n")
        if args.json_out:
            _scrivi_json(args.json_out, {k: v for k, v in piano.items() if k != "righe_jsonbin_dati"})
        return ESITO_FERMATO

    esito: Optional[Dict[str, Any]] = None
    verifica: Optional[Dict[str, Any]] = None
    if args.esegui:
        try:
            esito = rs.upstash_save(piano["righe_jsonbin_dati"])
            # Rilettura: il Registro e' valido solo se TUTTE le righe ci sono e
            # sono identiche, non se la HSET ha risposto 200.
            verifica = rs.confronto(piano["righe_jsonbin_dati"], rs.upstash_rows())
        except Exception as e:
            print(f"## Migrazione del Registro: JSONBin -> Upstash (fase C)\n\n"
                  f"- **errore durante la copia**: {type(e).__name__}: {e}\n"
                  f"- righe lette da JSONBin: {piano['righe_jsonbin']} (il bin NON e' stato toccato)\n")
            if args.json_out:
                _scrivi_json(args.json_out, {"errore": f"{type(e).__name__}: {e}",
                                             "eseguito": False, "piano": len(piano["da_copiare"])})
            return ESITO_ERRORE

    testo, ok = _report(piano, esito, verifica, eseguito=args.esegui)
    print("\n".join(testo) + "\n")
    if args.json_out:
        _scrivi_json(args.json_out, {
            "generato_il": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "eseguito": args.esegui,
            "righe_jsonbin": piano["righe_jsonbin"],
            "righe_upstash_prima": piano["righe_upstash"],
            "da_copiare": len(piano["da_copiare"]),
            "gia_presenti": len(piano["gia_presenti"]),
            "conflitti": piano["conflitti"],
            "esito_copia": esito,
            "verifica": verifica,
            "coincidono": None if verifica is None else verifica["identici"],
        })
    return ESITO_OK if ok else ESITO_ERRORE


def _scrivi_json(path: str, dati: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=2)
    print(f"[migrazione] json: {path}")


if __name__ == "__main__":
    sys.exit(main())
