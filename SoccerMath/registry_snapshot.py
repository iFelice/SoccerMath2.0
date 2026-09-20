"""registry_snapshot.py - Istantanea giornaliera del Registro (fase E).

Perche' esiste: l'hash Redis e' il Registro vivo, e un Registro vivo ha bisogno
di un punto di ripristino che non dipenda dallo stato di un momento. Una chiave
al giorno (``sm:registro:snapshot:<AAAA-MM-GG>``) e' 1 comando: costa quanto una
lettura e vale come termine di confronto ("com'era ieri") e come copia da cui
ripartire se un giorno qualcosa va storto.

Regole:

* si legge PRIMA il Registro dal backend attivo, in modo stretto: se non si
  legge, NON si scrive nessuna istantanea (un'istantanea vuota non e' un punto
  di ripristino, e' una trappola);
* si scrive una chiave al giorno, con la data nel nome: nessuna storia da
  gestire, nessuna potatura da fare (256 MB free = decine di migliaia di giorni);
* si RILEGGE e si confronta riga per riga: se l'istantanea non coincide con il
  Registro, l'operazione e' fallita, anche se il ``SET`` ha risposto ok;
* degradazione dichiarata: se Upstash non risponde, l'uscita e' 1 e il referto
  lo dice a chiare lettere (il bin JSONBin resta l'archivio dichiarato, il file
  locale resta la copia dell'app).

Uso:
    python SoccerMath/registry_snapshot.py                 # scrive e verifica
    python SoccerMath/registry_snapshot.py --prova         # non scrive
    python SoccerMath/registry_snapshot.py --giorno 2026-09-21 --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import registry_store as rs  # noqa: E402

ESITO_OK = 0
ESITO_ERRORE = 1


def oggi_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--giorno", default=None, help="giorno dell'istantanea (default: oggi UTC)")
    ap.add_argument("--prova", action="store_true", help="non scrive: dice cosa farebbe")
    ap.add_argument("--json", dest="json_out", default=None, help="scrive il dettaglio in JSON")
    args = ap.parse_args(argv)
    giorno = args.giorno or oggi_utc()
    chiave = rs.snapshot_key(giorno)

    L: List[str] = ["## Istantanea del Registro (fase E)", ""]
    esito: Dict[str, Any] = {"giorno": giorno, "chiave": chiave, "scritto": False,
                             "prova": args.prova, "generato_il": oggi_utc()}
    try:
        righe, fonte = rs.load_rows(strict=True)
    except Exception as e:
        L.append(f"- **Registro non leggibile: NESSUNA istantanea scritta** — "
                 f"{type(e).__name__}: {e}")
        L.append("- degradazione dichiarata: il Registro resta sul bin JSONBin "
                 "(archivio) e sul file locale dell'app; l'istantanea di oggi "
                 "manca e va rifatta quando il backend risponde.")
        print("\n".join(L) + "\n")
        if args.json_out:
            _scrivi_json(args.json_out, dict(esito, errore=f"{type(e).__name__}: {e}"))
        return ESITO_ERRORE

    L.append(f"- Registro letto da **{fonte}**: {len(righe)} righe")
    if not righe:
        L.append("- **Registro remoto VUOTO: nessuna istantanea scritta** (una fotografia "
                 "del nulla non e' un punto di ripristino)")
        print("\n".join(L) + "\n")
        if args.json_out:
            _scrivi_json(args.json_out, dict(esito, errore="registro vuoto"))
        return ESITO_ERRORE

    esito["righe"] = len(righe)
    esito["fonte"] = fonte
    if args.prova:
        L.append(f"- modalita' **prova**: avrei scritto `{chiave}` ({len(righe)} righe), niente comandi di scrittura")
        print("\n".join(L) + "\n")
        if args.json_out:
            _scrivi_json(args.json_out, esito)
        return ESITO_OK

    try:
        scritto = rs.upstash_snapshot(giorno, righe)
        riletto = rs.upstash_snapshot_read(giorno)
    except Exception as e:
        L.append(f"- **scrittura dell'istantanea fallita** — {type(e).__name__}: {e}")
        print("\n".join(L) + "\n")
        if args.json_out:
            _scrivi_json(args.json_out, dict(esito, errore=f"{type(e).__name__}: {e}"))
        return ESITO_ERRORE

    esito["scritto"] = True
    esito["snapshot"] = scritto
    L.append(f"- scritta `{scritto['chiave']}`: {scritto['righe']} righe · {scritto['byte']} byte")
    if riletto is None:
        esito["verificata"] = False
        L.append("- **istantanea NON rileggibile**: la fotografia non e' un punto di ripristino")
        print("\n".join(L) + "\n")
        if args.json_out:
            _scrivi_json(args.json_out, esito)
        return ESITO_ERRORE
    diff = rs.confronto(righe, riletto)
    esito["verificata"] = diff["identici"]
    esito["verifica"] = {k: v for k, v in diff.items() if k != "identici"}
    L.append(f"- verifica: solo su Registro {len(diff['solo_a'])} · solo sull'istantanea "
             f"{len(diff['solo_b'])} · contenuto diverso {len(diff['diverse'])}")
    L.append("- **istantanea fedele**: rileggibile e uguale al Registro"
             if diff["identici"] else "- **istantanea DIVERSA dal Registro**: non vale come punto di ripristino")
    print("\n".join(L) + "\n")
    if args.json_out:
        _scrivi_json(args.json_out, esito)
    return ESITO_OK if diff["identici"] else ESITO_ERRORE


def _scrivi_json(path: str, dati: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=2)
    print(f"[istantanea] json: {path}")


if __name__ == "__main__":
    sys.exit(main())
