"""registry_backend_status.py - Stato dei due backend del Registro (SOLA LETTURA).

Serve alla migrazione verso Upstash: dice, senza scrivere nulla, quante righe ha
il Registro su JSONBin, quante sull'hash Upstash, e **quali differenze** ci sono
fra i due (per chiave di campo, la stessa che usa la fusione delle righe).

Casi d'uso:

* **verifica dei secret**: se Upstash risponde, URL e token sono giusti;
* **prima della copia** (fase B): Upstash e' vuoto -> nessuna differenza
  inattesa, si sa esattamente quante righe verranno copiate;
* **dopo la copia** (fase C) e **dopo la commutazione** (fase D): i due insiemi
  devono risultare identici, e questo comando lo dice in una riga;
* **in esercizio**: se qualcuno scrive da una parte sola, si vede subito;
* **igiene dell'hash**: i NOMI dei campi sono la chiave ricalcolata dal
  contenuto (``field_of`` = ``dedup_key``). Se la convenzione di lettura
  cambia, una riga scritta prima del cambio resta sotto il nome vecchio:
  il comando conta campi, campi con nome vecchio e righe distinte.

Non scrive MAI: nessun SET/HSET/PUT, nessun file di registro toccato. Esce 1
solo se un backend non risponde o risponde male (non per una differenza: durante
la migrazione la differenza e' il dato che stiamo guardando).

Uso:
    python SoccerMath/registry_backend_status.py
    python SoccerMath/registry_backend_status.py --json out/stato.json --mostra 5
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


def _kb(righe: List[Dict[str, Any]]) -> float:
    return len(json.dumps({"data": righe}, ensure_ascii=False).encode("utf-8")) / 1024


def leggi_jsonbin() -> Tuple[Optional[List[Dict[str, Any]]], str]:
    try:
        return rs.jsonbin_rows(), "ok"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def leggi_upstash() -> Tuple[Optional[List[Dict[str, Any]]], str]:
    try:
        return rs.upstash_rows(), "ok"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def chiavi_upstash(quante: int = 10) -> Dict[str, Any]:
    """DBSIZE + prime chiavi del database: dice se una scrittura e' arrivata
    altrove (chiave diversa) o non e' arrivata affatto. Sola lettura."""
    try:
        dimensione = rs.upstash_raw(["DBSIZE"]).get("result")
        chiavi = sorted(rs.chiavi_da_risposta(rs.upstash_raw(["KEYS", "*"]).get("result")))[:quante]
        return {"dbsize": dimensione, "chiavi": chiavi, "errore": None}
    except Exception as e:
        return {"dbsize": None, "chiavi": [], "errore": f"{type(e).__name__}: {e}"}


def campi_upstash(esempi: int = 3, *, post=None) -> Dict[str, Any]:
    """HGETALL GREZZO: i NOMI dei campi contro la chiave ricalcolata dal contenuto.

    Il campo dell'hash e' ``field_of(riga)`` = ``dedup_key`` della riga, quindi
    dipende dalla convenzione con cui si legge la variante: se cambia (una riga
    senza campo letta per DATA invece che col default), una riga scritta prima
    del cambio resta sotto il nome VECCHIO. Il contenuto c'e' e si legge, ma il
    campo non e' piu' quello che la riga ricalcola: due campi, una sola riga.

    Qui si contano i campi totali, quelli allineati, quelli con nome vecchio,
    le righe DISTINTE per chiave ricalcolata (se i campi doppi sono righe
    doppie) e si mostrano un paio di esempi. Sola lettura: una ``HGETALL``.
    """
    try:
        grezzo = rs.upstash_raw(["HGETALL", rs.hash_key()], post=post).get("result")
        coppie = rs.hash_da_risposta(grezzo)
    except Exception as e:                                  # pragma: no cover - rete
        return {"errore": f"{type(e).__name__}: {e}"}
    allineati = vecchi = illeggibili = 0
    per_chiave: Dict[str, List[str]] = {}
    esempi_vecchi: List[Dict[str, str]] = []
    for campo, valore in coppie.items():
        riga = valore if isinstance(valore, dict) else None
        if riga is None:
            try:
                riga = json.loads(valore) if isinstance(valore, str) else None
            except Exception:
                riga = None
        if not isinstance(riga, dict):
            illeggibili += 1
            continue
        calcolato = rs.field_of(riga)
        if calcolato == campo:
            allineati += 1
        else:
            vecchi += 1
            if len(esempi_vecchi) < max(0, esempi):
                esempi_vecchi.append({"campo_scritto": campo, "campo_ricalcolato": calcolato})
        per_chiave.setdefault(calcolato, []).append(campo)
    doppie = sum(1 for campi in per_chiave.values() if len(campi) > 1)
    return {"campi": len(coppie), "allineati": allineati, "nome_vecchio": vecchi,
            "illeggibili": illeggibili, "righe_distinte": len(per_chiave),
            "chiavi_doppie": doppie, "esempi": esempi_vecchi}


def _riga_testo(r: Dict[str, Any]) -> str:
    return (f"{r.get('home')} - {r.get('away')} ({r.get('campionato')}, {r.get('data')}) "
            f"{r.get('mercato_standard')} {r.get('prob_sicuro')}% "
            f"[{r.get('model_variant') or 'current'}] {r.get('salvato_il')}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", dest="json_out", default=None, help="scrive il dettaglio in JSON")
    ap.add_argument("--mostra", type=int, default=3, help="quante righe di esempio per lato")
    args = ap.parse_args(argv)

    righe_jb, errore_jb = leggi_jsonbin()
    righe_us, errore_us = leggi_upstash()
    esito: Dict[str, Any] = {
        "generato_il": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "backend_attivo": rs.backend(),
        "hash_key": rs.hash_key(),
        "jsonbin": {"righe": None if righe_jb is None else len(righe_jb),
                    "kb": None if righe_jb is None else round(_kb(righe_jb), 1),
                    "errore": None if errore_jb == "ok" else errore_jb},
        "upstash": {"righe": None if righe_us is None else len(righe_us),
                    "kb": None if righe_us is None else round(_kb(righe_us), 1),
                    "errore": None if errore_us == "ok" else errore_us},
    }

    L: List[str] = ["## Registro: stato dei due backend (sola lettura)", ""]
    L.append(f"- backend attivo: `{esito['backend_attivo']}` · chiave hash: `{esito['hash_key']}`")
    if righe_jb is None:
        L.append(f"- **JSONBin: NON leggibile** — {errore_jb}")
    else:
        L.append(f"- JSONBin: **{len(righe_jb)} righe** · {esito['jsonbin']['kb']} kB "
                 f"(tetto piano free: 100 kB)")
    if righe_us is None:
        L.append(f"- **Upstash: NON leggibile** — {errore_us}")
    else:
        L.append(f"- Upstash: **{len(righe_us)} righe** · {esito['upstash']['kb']} kB "
                 f"(tetto piano free: 256 MB)")
        chiavi = chiavi_upstash()
        esito["upstash"]["dbsize"] = chiavi["dbsize"]
        esito["upstash"]["chiavi"] = chiavi["chiavi"]
        if chiavi["errore"]:
            L.append(f"- **chiavi del database: non leggibili** — {chiavi['errore']}")
        else:
            L.append(f"- chiavi nel database (**{chiavi['dbsize']}**): "
                     + (", ".join(f"`{k}`" for k in chiavi["chiavi"]) or "nessuna"))
        campi = campi_upstash(args.mostra)
        esito["upstash"]["campi"] = campi
        if campi.get("errore"):
            L.append(f"- **campi dell'hash: non leggibili** — {campi['errore']}")
        else:
            L.append(f"- campi dell'hash: **{campi['campi']}** · allineati alla chiave ricalcolata "
                     f"**{campi['allineati']}** · con nome vecchio **{campi['nome_vecchio']}** · "
                     f"righe distinte **{campi['righe_distinte']}** · chiavi doppie "
                     f"**{campi['chiavi_doppie']}**"
                     + (f" · valori illeggibili {campi['illeggibili']}" if campi["illeggibili"] else ""))
            for esempio in campi["esempi"]:
                L.append(f"    · nome vecchio: `{esempio['campo_scritto']}` -> ricalcolato "
                         f"`{esempio['campo_ricalcolato']}`")

    if righe_jb is not None and righe_us is not None:
        diff = rs.confronto(righe_jb, righe_us)
        esito["confronto"] = diff
        L.append(f"- confronto per chiave di campo: solo su JSONBin **{len(diff['solo_a'])}**, "
                 f"solo su Upstash **{len(diff['solo_b'])}**, contenuto diverso **{len(diff['diverse'])}**")
        if diff["identici"]:
            L.append("- **i due Registri coincidono**: la migrazione e' allineata")
        elif not righe_us:
            L.append("- Upstash e' vuoto: database nuovo, la copia e' la fase C "
                     "(nessuna scrittura fatta da questo comando)")
        else:
            L.append("- i due Registri NON coincidono: durante la migrazione e' atteso, "
                     "in esercizio no (vedi gli esempi sotto)")
        mappa_jb = {rs.field_of(r): r for r in righe_jb}
        mappa_us = {rs.field_of(r): r for r in righe_us}
        for titolo, campi, mappa in (("solo su JSONBin", diff["solo_a"], mappa_jb),
                                     ("solo su Upstash", diff["solo_b"], mappa_us)):
            for campo in campi[:max(0, args.mostra)]:
                L.append(f"    · {titolo}: {_riga_testo(mappa[campo])}")
        for campo in diff["diverse"][:max(0, args.mostra)]:
            L.append(f"    · contenuto diverso:\n        JSONBin: {_riga_testo(mappa_jb[campo])}\n"
                     f"        Upstash: {_riga_testo(mappa_us[campo])}")

    testo = "\n".join(L) + "\n"
    print(testo)
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(esito, f, ensure_ascii=False, indent=2)
        print(f"[stato] json: {args.json_out}")
    if righe_jb is None or righe_us is None:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
