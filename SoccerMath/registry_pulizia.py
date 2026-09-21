"""Pulizia mirata del Registro: toglie le righe di una o piu' ORIGINI (sola lettura
finche' non si passa ``--scrivi`` insieme a ``--conferma``).

Perche' esiste. Il confronto fra i due motori Elo si fa sulle righe **Top Mix**
(le uniche che entrambi i motori producono). Le righe di *Analisi Rapida* sono
un'altra cosa: una sola riga, motore attuale, nessun gemello legacy. Se restano
dentro l'hash, ogni volta che si guarda "quante righe ha il Registro" si sommano
mele e pere.

Cosa fa, in ordine, quando scrive:

1. legge l'hash GREZZO (``HGETALL``) e seleziona i campi il cui **contenuto** dice
   ``origin`` richiesta — non si fida del nome del campo;
2. crea PRIMA un'istantanea completa del Registro su una chiave dedicata
   (``sm:registro:snapshot:<giorno>-pre-pulizia``): e' il punto di ripristino;
3. ``HDEL`` di tutti i campi selezionati in UN SOLO comando (niente mezze
   pulizie), e poi rilegge per verificare: righe prima/dopo, nessuna riga
   dell'origine rimasta, insieme dei campi delle altre origini **identico**;
4. scrive il JSON delle righe rimosse in ``--rimosse`` (leggibile per ripristino
   riga per riga anche senza l'istantanea).

Garanzie (le stesse della scrittura normale):

* non tocca MAI le righe Top Mix: se un campo selezionato ha origine ``top_mix``
  lo strumento si ferma (errore) invece di procedere;
* nessuna scrittura senza ``--scrivi`` **e** ``--conferma``;
* il numero di righe selezionate deve combaciare con ``--attesi`` quando dato:
  un numero diverso ferma tutto (una pulizia "quasi giusta" e' un guasto);
* il backend deve essere Upstash: su JSONBin questa pulizia non si fa.

Uso:

    python SoccerMath/registry_pulizia.py                       # prova (nessuna scrittura)
    python SoccerMath/registry_pulizia.py --scrivi --conferma --attesi 26 \\
        --rimosse /tmp/rimosse.json
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
from prediction_registry import (  # noqa: E402
    MODEL_VARIANT_LABELS,
    dedup_key,
    model_variant_read,
    origin_of,
    origin_from_text,
)
from registry_composizione import dettaglio_riga  # noqa: E402

ORIGINI_DEFAULT = ("analisi_rapida",)


def riga_tecnica(campo: str, testo: str, riga: Dict[str, Any]) -> str:
    """Perche' un campo e' quello che e': nome scritto, origine scritta, origine letta.

    Serve quando il nome del campo e la lettura NON coincidono (convenzione
    cambiata): il nome vecchio e quello ricalcolato restano nell'hash come due
    campi con lo stesso contenuto, e cancellarne uno solo lascerebbe la riga
    dentro per l'altro nome.
    """
    grezza = str(riga.get("origin") or "").strip()
    letta = str(origin_of(riga) or "").strip()
    ricalcolato = "|".join("" if p is None else str(p) for p in dedup_key(riga))
    return (f"RIGA| `{campo}` | allineato a `{ricalcolato}`: "
            f"{'si' if campo == ricalcolato else 'NO (nome vecchio)'} | "
            f"origine scritta: {grezza or 'assente'} | origine letta: {letta} | "
            f"testo del pronostico: {str(riga.get('pronostico_sicuro') or 'assente')[:40]!r} | "
            f"letto {MODEL_VARIANT_LABELS.get(model_variant_read(riga), model_variant_read(riga))} | "
            f"{dettaglio_riga(riga)}")


def _giorno_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def campi_grezzi(*, post=None) -> Dict[str, Tuple[str, Dict[str, Any]]]:
    """Ogni campo dell'hash cosi' com'e' scritto: ``{campo: (testo, riga)}``.

    Si legge GREZZO di proposito: la pulizia deve cancellare i **nomi dei campi
    che esistono davvero**, non un nome ricalcolato (che dopo un cambio di
    convenzione puo' non essere piu' quello scritto).
    """
    risultato = rs._upstash_cmd(["HGETALL", rs.hash_key()], post=post)
    valori = rs.hash_da_risposta(risultato)
    fuori: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for campo, valore in valori.items():
        riga = rs._row_from_value(valore)
        if riga is None:
            continue
        fuori[campo] = (json.dumps(riga, ensure_ascii=False, sort_keys=True, default=str), riga)
    return fuori


def seleziona(campi: Dict[str, Tuple[str, Dict[str, Any]]],
              origini: Tuple[str, ...]) -> Tuple[List[str], List[str], List[str]]:
    """Campi da cancellare, problemi e righe NON attribuibili (nessuna scrittura).

    * un campo la cui origine e' ``top_mix`` NON si tocca **mai**: chiederla e'
      un problema da dichiarare, non da risolvere cancellando;
    * un campo la cui origine non si legge (``unknown``: nessun campo e testo non
      riconoscibile) non si seleziona e finisce nell'elenco dei **non
      attribuibili**, cosi' non sparisce dal discorso: se e' una riga che si
      vuole togliere, quella si indica a parte e con una decisione esplicita.
    """
    da_cancellare: List[str] = []
    problemi: List[str] = []
    non_attribuibili: List[str] = []
    for campo, (_testo, riga) in sorted(campi.items()):
        origine = str(origin_of(riga) or "").strip().lower()
        if origine == "top_mix":
            if origine in origini:
                problemi.append(f"`{campo}`: origine top_mix fra quelle richieste ({origine})")
            continue
        if origine in origini:
            da_cancellare.append(campo)
            continue
        if origine in ("", "unknown"):
            non_attribuibili.append(campo)
    return da_cancellare, problemi, non_attribuibili


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--origini", default=",".join(ORIGINI_DEFAULT),
                    help="origini da togliere dal Registro (separate da virgola)")
    ap.add_argument("--attesi", type=int, default=None,
                    help="numero di righe atteso: se non combacia lo strumento si ferma")
    ap.add_argument("--rimosse", default=None, help="scrive qui il JSON delle righe rimosse")
    ap.add_argument("--dettaglio", action="store_true",
                    help="stampa per ogni campo il nome scritto, quello ricalcolato e le origini")
    ap.add_argument("--scrivi", action="store_true", help="esegue davvero la pulizia")
    ap.add_argument("--conferma", action="store_true",
                    help="seconda chiave: senza questa, --scrivi non scrive")
    ap.add_argument("--giorno", default=None, help="giorno dell'istantanea (default: oggi UTC)")
    args = ap.parse_args(argv)

    origini = tuple(o.strip().lower() for o in args.origini.split(",") if o.strip())
    if not origini:
        print("::error title=pulizia::nessuna origine indicata")
        return 2
    if rs.backend() != rs.BACKEND_UPSTASH:
        print(f"::error title=pulizia::backend attivo `{rs.backend()}`: questa pulizia si fa solo su Upstash")
        return 2

    campi = campi_grezzi()
    totale_prima = len(campi)
    righe_prima = len(rs.upstash_rows())
    da_cancellare, problemi, non_attribuibili = seleziona(campi, origini)
    if problemi:
        print("::error title=pulizia::problemi trovati, nessuna scrittura:")
        for p in problemi:
            print(f"  - {p}")
        return 3
    if args.attesi is not None and len(da_cancellare) != args.attesi:
        print(f"::error title=pulizia::attese {args.attesi} righe, trovate {len(da_cancellare)}: "
              "niente scrittura (una pulizia 'quasi giusta' e' un guasto)")
        return 3

    print(f"## Pulizia del Registro — origini {', '.join(f'`{o}`' for o in origini)}")
    print(f"- campi nell'hash prima: **{totale_prima}** · righe (una per chiave): **{righe_prima}**")
    print(f"- campi selezionati: **{len(da_cancellare)}**")
    for campo in da_cancellare:
        _testo, riga = campi[campo]
        print(f"  - `{campo}` · {dettaglio_riga(riga)}")
    if non_attribuibili:
        print(f"- righe NON attribuibili a nessuna origine (restano, non si toccano): "
              f"**{len(non_attribuibili)}**")
        for campo in non_attribuibili:
            print(f"  - `{campo}` · {dettaglio_riga(campi[campo][1])}")
    if args.dettaglio:
        # Un blocco per OGNI campo selezionato: nome scritto, nome ricalcolato,
        # origine scritta e origine letta. E' il blocco che dice se cancellare
        # il campo basta, o se la stessa riga vive sotto un secondo nome.
        print("")
        print("### Dettaglio tecnico dei campi selezionati")
        for campo in da_cancellare:
            testo, riga = campi[campo]
            print(riga_tecnica(campo, testo, riga))
        chiavi_logiche = {}
        for campo in da_cancellare:
            chiavi_logiche.setdefault(rs.field_of(campi[campo][1]), []).append(campo)
        print(f"\n- campi selezionati: **{len(da_cancellare)}** · righe logiche distinte: "
              f"**{len(chiavi_logiche)}**")
        sdoppiate = {k: v for k, v in chiavi_logiche.items() if len(v) > 1}
        print(f"- righe presenti sotto PIU' nomi di campo: **{len(sdoppiate)}**")
        for chiave, campi_uguali in sorted(sdoppiate.items()):
            print(f"  - riga logica `{chiave}` → campi: {', '.join('`' + c + '`' for c in sorted(campi_uguali))}")
        for chiave, campi_uguali in sorted(chiavi_logiche.items()):
            if len(campi_uguali) == 1 and campi_uguali[0] != chiave:
                print(f"  - riga logica `{chiave}` → un solo campo, con nome vecchio: "
                      f"`{campi_uguali[0]}`")
    if not args.scrivi:
        print("\n**PROVA**: nessuna scrittura. Per eseguire servono `--scrivi --conferma`.")
        return 0
    if not args.conferma:
        print("\n::error title=pulizia::`--scrivi` senza `--conferma`: nessuna scrittura.")
        return 3
    if not da_cancellare:
        print("\nNiente da cancellare: l'origine richiesta non e' piu' nel Registro. "
              "Nessuna scrittura (idempotente).")
        return 0

    # 1) Istantanea PRIMA di toccare: e' il punto di ripristino.
    giorno = args.giorno or f"{_giorno_utc()}-pre-pulizia"
    righe = [riga for _campo, (_testo, riga) in campi.items()]
    # una riga per chiave logica, come nel Registro vero
    chiavi_viste = set()
    righe_logiche = []
    for riga in righe:
        chiave = rs.field_of(riga)
        if chiave in chiavi_viste:
            continue
        chiavi_viste.add(chiave)
        righe_logiche.append(riga)
    snap = rs.upstash_snapshot(giorno, righe_logiche)
    print(f"\n- istantanea creata: `{snap['chiave']}` · {snap['righe']} righe · {snap['byte']} byte")

    # 2) HDEL in UN SOLO comando (niente mezze pulizie).
    risposta = rs.upstash_raw(["HDEL", rs.hash_key()] + da_cancellare)
    cancellati = risposta.get("result")
    print(f"- HDEL: `result` = **{cancellati}** (campi chiesti: {len(da_cancellare)})")

    # 3) Rilettura e verifica.
    campi_dopo = campi_grezzi()
    righe_dopo = len(rs.upstash_rows())
    chiavi_altre_prima = {c for c, (_t, r) in campi.items() if str(origin_of(r) or "").lower() not in origini}
    chiavi_altre_dopo = set(campi_dopo) - set(da_cancellare)
    rimaste = [c for c, (_t, r) in campi_dopo.items() if str(origin_of(r) or "").strip().lower() in origini]
    print(f"- campi dopo: **{len(campi_dopo)}** · righe dopo: **{righe_dopo}** "
          f"(prima {totale_prima} / {righe_prima})")
    print(f"- righe dell'origine rimaste: **{len(rimaste)}**")
    print(f"- campi delle ALTRE origini: prima {len(chiavi_altre_prima)} · dopo {len(chiavi_altre_dopo)} · "
          f"{'IDENTICI' if chiavi_altre_prima == chiavi_altre_dopo else 'DIVERSI (guasto!)'}")

    if args.rimosse:
        os.makedirs(os.path.dirname(os.path.abspath(args.rimosse)), exist_ok=True)
        with open(args.rimosse, "w", encoding="utf-8") as f:
            json.dump({"campo_e_riga": [{"campo": c, "riga": campi[c][1]} for c in da_cancellare],
                       "istantanea": snap["chiave"], "origini": list(origini)},
                      f, ensure_ascii=False, indent=2)
        print(f"- righe rimosse scritte in `{args.rimosse}`")

    esito_ok = (not rimaste) and (chiavi_altre_prima == chiavi_altre_dopo) and \
               (cancellati == len(da_cancellare))
    if not esito_ok:
        print("::error title=pulizia::verifica NON superata: guarda i numeri sopra "
              "(l'istantanea e' comunque al sicuro)")
        return 4
    print("\n**Pulizia eseguita e verificata**: solo le righe delle origini richieste, "
          "le altre intatte, istantanea disponibile per il ripristino.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
