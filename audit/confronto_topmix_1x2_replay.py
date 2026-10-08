"""Confronto del Top Mix PRIMA (main) e DOPO (branch) sul replay storico point-in-time.

Legge i due report JSON prodotti da ``SoccerMath/replay_legacy_topmix.py`` (stesso
``--fixtures csv``, stesso ``--ref``: cambia solo il codice del selettore) e misura:

* (i)   le righe Totali del vecchio Top Mix che NON ci sono piu', per mercato, e che
        cosa e' successo alla partita (sparita del tutto, o rivalutata su un 1X2);
* (ii)  le partite che ENTRANO con una scelta 1X2 (nuove, o rivalutate da un Totale):
        conteggio e hit rate sulle scelte giudicate;
* (iii) le righe 1X2 gia' presenti nel vecchio Top Mix: devono restare IDENTICHE
        (cambia al piu' il rank, che e' la posizione nella lista);
* l'hit rate complessivo del Top Mix visibile, prima e dopo, per variante.

Sola lettura: non tocca il registro, non scrive nel repo. Il referto va in ``--out``.
Non e' una verifica di produzione: e' un replay offline sulle partite gia' giocate
presenti nei CSV, con le stesse regole point-in-time del replay (vedi il suo docstring).

Uso:
    python audit/confronto_topmix_1x2_replay.py --main main.json --branch branch.json --out-md x.md --out-json x.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TOTALI = ("OVER_2.5", "UNDER_2.5", "GG", "NG")
UNO_ICS = ("1", "X", "2")
ESITI_GIUDICATI = ("\u2705", "\u274c")
CHIAVI_IGNORATE_NEL_CONFRONTO = ("rank", "selector_version", "calculation_id")
VARIANTI = (("current", "entries_current"), ("legacy", "entries_legacy"))


def carica(percorso: str) -> Dict[str, Any]:
    with open(percorso, encoding="utf-8") as f:
        dati = json.load(f)
    for _nome, chiave in VARIANTI:
        if not isinstance(dati.get(chiave), list):
            raise ValueError(f"{percorso}: manca la lista `{chiave}`")
    return dati


def indice(entries: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], int]:
    """Una riga per partita (per match_id). Ritorna ``(mappa, duplicati)``."""
    mappa: Dict[str, Dict[str, Any]] = {}
    duplicati = 0
    for e in entries:
        mid = str(e.get("match_id"))
        if mid in mappa:
            duplicati += 1
            continue
        mappa[mid] = e
    return mappa, duplicati


def hit(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    giudicate = [e for e in entries if e.get("esito") in ESITI_GIUDICATI]
    vinte = sum(1 for e in giudicate if e.get("esito") == "\u2705")
    return {"righe": len(entries), "giudicate": len(giudicate), "vinte": vinte,
            "hit_rate": (vinte / len(giudicate)) if giudicate else None}


def _canon(e: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in e.items() if k not in CHIAVI_IGNORATE_NEL_CONFRONTO}


def confronta(main: List[Dict[str, Any]], branch: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Confronto di UNA variante (current o legacy)."""
    m, dup_m = indice(main)
    b, dup_b = indice(branch)

    totali_main: Dict[str, int] = {}
    sparite: Dict[str, List[str]] = {}
    rivalutate: Dict[str, List[str]] = {}
    for mid, e in m.items():
        mk = e.get("mercato_standard")
        if mk not in TOTALI:
            continue
        totali_main[mk] = totali_main.get(mk, 0) + 1
        nuova = b.get(mid)
        if nuova is None:
            sparite.setdefault(mk, []).append(mid)
        elif nuova.get("mercato_standard") in UNO_ICS:
            rivalutate.setdefault(mk, []).append(mid)

    entrano_nuove = [mid for mid, e in b.items()
                     if e.get("mercato_standard") in UNO_ICS and mid not in m]
    entrano_rivalutate = [mid for mid in b if b[mid].get("mercato_standard") in UNO_ICS
                          and m.get(mid, {}).get("mercato_standard") in TOTALI]
    entrano = [b[mid] for mid in entrano_nuove + entrano_rivalutate]

    uno_x_due_main = [mid for mid, e in m.items() if e.get("mercato_standard") in UNO_ICS]
    identiche, diverse, perse = 0, [], []
    for mid in uno_x_due_main:
        if mid not in b:
            perse.append(mid)
            continue
        if _canon(m[mid]) == _canon(b[mid]):
            identiche += 1
        else:
            diverse.append(mid)

    anomalie = {
        "branch_con_totale": sum(1 for e in b.values() if e.get("mercato_standard") in TOTALI),
        "main_1x2_branch_totale": sum(1 for mid in uno_x_due_main
                                      if b.get(mid, {}).get("mercato_standard") in TOTALI),
        "duplicati_main": dup_m, "duplicati_branch": dup_b,
    }
    return {
        "totali_main_per_mercato": totali_main,
        "totali_sparite_senza_1x2_per_mercato": {k: len(v) for k, v in sorted(sparite.items())},
        "totali_rivalutate_su_1x2_per_mercato": {k: len(v) for k, v in sorted(rivalutate.items())},
        "totali_sparite_mid": sorted(mid for v in sparite.values() for mid in v),
        "entrano_1x2_nuove": len(entrano_nuove),
        "entrano_1x2_rivalutate": len(entrano_rivalutate),
        "entrano_1x2_hit": hit(entrano),
        "entrano_1x2_nuove_hit": hit([b[mid] for mid in entrano_nuove]),
        "entrano_1x2_rivalutate_hit": hit([b[mid] for mid in entrano_rivalutate]),
        "1x2_gia_presenti": len(uno_x_due_main),
        "1x2_identiche": identiche,
        "1x2_diverse": len(diverse),
        "1x2_diverse_mid": sorted(diverse),
        "1x2_perse": len(perse),
        "anomalie": anomalie,
        "hit_prima": hit(list(m.values())),
        "hit_dopo": hit(list(b.values())),
    }


def somma(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Somma di due risultati di variante (per il totale del Top Mix visibile)."""
    out: Dict[str, Any] = {}
    for k in a:
        va, vb = a[k], b[k]
        if isinstance(va, dict) and "hit_rate" in va:
            giud = va["giudicate"] + vb["giudicate"]
            vin = va["vinte"] + vb["vinte"]
            out[k] = {"righe": va["righe"] + vb["righe"], "giudicate": giud, "vinte": vin,
                      "hit_rate": (vin / giud) if giud else None}
        elif isinstance(va, dict):
            out[k] = {kk: va.get(kk, 0) + vb.get(kk, 0) for kk in set(va) | set(vb)}
        elif isinstance(va, list):
            out[k] = va + vb
        elif isinstance(va, (int, float)):
            out[k] = va + vb
    return out


def esegui(main_path: str, branch_path: str) -> Dict[str, Any]:
    rm, rb = carica(main_path), carica(branch_path)
    risultati = {}
    for nome, chiave in VARIANTI:
        risultati[nome] = confronta(rm[chiave], rb[chiave])
    risultati["totale"] = somma(risultati["current"], risultati["legacy"])
    return {
        "main": {"file": Path(main_path).name, "ref": rm.get("ref"), "finestra": rm.get("finestra"),
                 "clicks": len(rm.get("clicks") or []), "leak_ok": rm.get("leak_ok")},
        "branch": {"file": Path(branch_path).name, "ref": rb.get("ref"), "finestra": rb.get("finestra"),
                   "clicks": len(rb.get("clicks") or []), "leak_ok": rb.get("leak_ok")},
        "risultati": risultati,
    }


def _pct(x: Optional[float]) -> str:
    return "n/d" if x is None else f"{x * 100:.1f}%"


def scrivi_md(r: Dict[str, Any], percorso: Path) -> None:
    res = r["risultati"]
    L = [
        "# Top Mix: PRIMA (main) contro DOPO (branch) sul replay storico point-in-time",
        "",
        f"- main: `{r['main']['file']}` - ref `{r['main']['ref']}` - click {r['main']['clicks']} - leak_ok {r['main']['leak_ok']}",
        f"- branch: `{r['branch']['file']}` - ref `{r['branch']['ref']}` - click {r['branch']['clicks']} - leak_ok {r['branch']['leak_ok']}",
        "- Stesse fixture (CSV), stessi istanti, stesso database point-in-time: cambia solo il selettore.",
        "",
    ]
    for nome in ("current", "legacy", "totale"):
        v = res[nome]
        L += [f"## Variante `{nome}`", ""]
        L += ["### (i) Totali del vecchio Top Mix", "",
              "| mercato | nel main | sparite (nessun 1X2) | rivalutate su 1X2 |",
              "|---|---:|---:|---:|"]
        for mk in TOTALI:
            L.append(f"| {mk} | {v['totali_main_per_mercato'].get(mk, 0)} | "
                     f"{v['totali_sparite_senza_1x2_per_mercato'].get(mk, 0)} | "
                     f"{v['totali_rivalutate_su_1x2_per_mercato'].get(mk, 0)} |")
        L += ["", "### (ii) Partite che entrano con un 1X2", "",
              f"- nuove (il main non aveva nulla): **{v['entrano_1x2_nuove']}**; "
              f"hit rate: {_pct(v['entrano_1x2_nuove_hit']['hit_rate'])} "
              f"({v['entrano_1x2_nuove_hit']['vinte']}/{v['entrano_1x2_nuove_hit']['giudicate']} giudicate)",
              f"- rivalutate (il main aveva un Totale): **{v['entrano_1x2_rivalutate']}**; "
              f"hit rate: {_pct(v['entrano_1x2_rivalutate_hit']['hit_rate'])} "
              f"({v['entrano_1x2_rivalutate_hit']['vinte']}/{v['entrano_1x2_rivalutate_hit']['giudicate']} giudicate)",
              "", "### (iii) Righe 1X2 gia' presenti", "",
              f"- nel main: {v['1x2_gia_presenti']}; identiche nel branch (salvo rank, selector_version, "
              f"calculation_id): **{v['1x2_identiche']}**; diverse: {v['1x2_diverse']}; perse: {v['1x2_perse']}",
              "", "### Hit rate complessivo del Top Mix visibile", "",
              f"- prima (main): {_pct(v['hit_prima']['hit_rate'])} su {v['hit_prima']['giudicate']} giudicate "
              f"({v['hit_prima']['righe']} righe)",
              f"- dopo (branch): {_pct(v['hit_dopo']['hit_rate'])} su {v['hit_dopo']['giudicate']} giudicate "
              f"({v['hit_dopo']['righe']} righe)",
              "", f"- controlli: branch con Totale = {v['anomalie']['branch_con_totale']}; "
              f"1X2 del main diventato Totale = {v['anomalie']['main_1x2_branch_totale']}; "
              f"duplicati main/branch = {v['anomalie']['duplicati_main']}/{v['anomalie']['duplicati_branch']}",
              ""]
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text("\n".join(L), encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--main", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--out-json", required=True)
    p.add_argument("--out-md", required=True)
    a = p.parse_args(argv)
    r = esegui(a.main, a.branch)
    Path(a.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out_json).write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scrivi_md(r, Path(a.out_md))
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if not isinstance(vv, list)}
                      for k, v in r["risultati"].items()}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
