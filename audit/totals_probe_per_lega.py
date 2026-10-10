#!/usr/bin/env python3
"""totals_probe_per_lega.py — dettaglio PER LEGA della sonda totals (audit, offline).

Estende ``totals_probe_analysis.py`` con le misure richieste dalla regola di
ingresso in produzione (decisa PRIMA di vedere i dati):

  REGOLA: totals entra in produzione solo se almeno l'85 % degli eventi ha la
  linea 2,5 da Pinnacle OPPURE da almeno 3 bookmaker.

Per ogni lega riporta: crediti usati e residui, eventi, eventi con Pinnacle,
distribuzione della linea offerta da Pinnacle (2,5 / altre linee intere o mezze /
asiatiche quarti), eventi con 2,5 da almeno 1 e da almeno 3 bookmaker, quota di
eventi che soddisfa la regola.

Solo stdlib. Nessuna rete, nessuna chiave. Legge ``audit/data/totals_probe/``
e scrive ``audit/results/totals_probe_per_lega.md``.
"""

from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_AUDIT_DIR, "data", "totals_probe")
REPORT = os.path.join(_AUDIT_DIR, "results", "totals_probe_per_lega.md")
PINNACLE = "pinnacle"
SOGLIA_CONSENSO = 3          # bookmaker distinti con linea 2,5
SOGLIA_QUOTA = 0.85          # regola dichiarata


def classe_linea(point) -> str:
    """2,5 esatto / intere o mezze (non 2,5) / asiatiche (quarti x,25 o x,75)."""
    try:
        x = float(point)
    except (TypeError, ValueError):
        return "non valida"
    if abs(x - 2.5) < 1e-9:
        return "2,5"
    frac = round((x - int(x)) * 100) % 100
    if frac in (25, 75):
        return "asiatica (quarto)"
    if frac in (0, 50):
        return "intera o mezza (altra)"
    return "altra"


def linee_per_book(ev: dict) -> dict:
    """{book: set(point)} sul mercato totals (tutte le linee del libro)."""
    out: dict = defaultdict(set)
    for bk in ev.get("bookmakers") or []:
        for mk in bk.get("markets") or []:
            if mk.get("key") != "totals":
                continue
            for o in mk.get("outcomes") or []:
                if o.get("name") in ("Over", "Under") and o.get("point") is not None:
                    out[bk.get("key")].add(float(o["point"]))
    return out


def main(argv=None) -> int:
    per_lega = []
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "soccer_*.json"))):
        with open(path, encoding="utf-8") as fh:
            env = json.load(fh)
        hdr = env.get("headers") or {}
        body = env.get("body") or []
        r = {
            "lega": env.get("lega"), "sport_key": env.get("sport_key"),
            "crediti": hdr.get("x-requests-last"),
            "residui": hdr.get("x-requests-remaining"),
            "eventi": 0, "con_pinnacle": 0, "pin_linee": Counter(),
            "con_25_1": 0, "con_25_3": 0, "regola_ok": 0,
            "libri_con_linee_multiple": 0,
        }
        for ev in body:
            r["eventi"] += 1
            lines = linee_per_book(ev)
            if any(len(v) > 1 for v in lines.values()):
                r["libri_con_linee_multiple"] += 1
            pin = lines.get(PINNACLE)
            if pin:
                r["con_pinnacle"] += 1
                # linea principale di Pinnacle: la piu' vicina a 2,5 (per leggere la distribuzione)
                pt = min(pin, key=lambda p: abs(p - 2.5))
                r["pin_linee"][classe_linea(pt)] += 1
            n25 = sum(1 for v in lines.values() if any(abs(p - 2.5) < 1e-9 for p in v))
            pin25 = bool(pin) and any(abs(p - 2.5) < 1e-9 for p in pin)
            r["con_25_1"] += int(n25 >= 1)
            r["con_25_3"] += int(n25 >= SOGLIA_CONSENSO)
            r["regola_ok"] += int(pin25 or n25 >= SOGLIA_CONSENSO)
        per_lega.append(r)

    tot = {k: sum(r[k] for r in per_lega) for k in
           ("eventi", "con_pinnacle", "con_25_1", "con_25_3", "regola_ok")}
    pin_tot = Counter()
    for r in per_lega:
        pin_tot.update(r["pin_linee"])

    T = []
    A = T.append
    A("# Sonda The Odds API — dettaglio per lega (mercato totals, audit offline)\n")
    A(f"Generato da `audit/totals_probe_per_lega.py` il "
      f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} dagli snapshot di "
      "`audit/data/totals_probe/`. Nessuna chiamata di rete, nessuna chiave.\n")
    A("## Regola dichiarata (prima dei dati)\n")
    A(f"Totals entra in produzione solo se **almeno il {int(SOGLIA_QUOTA*100)} %** degli eventi "
      f"ha la linea **2,5 da Pinnacle** oppure **da almeno {SOGLIA_CONSENSO} bookmaker** "
      "(linea 2,5 esatta sul mercato totals).\n")
    A("## Crediti e residui\n")
    A("| lega | sport_key | crediti chiamata (x-requests-last) | residui (x-requests-remaining) |")
    A("|---|---|---|---|")
    for r in per_lega:
        A(f"| {r['lega']} | {r['sport_key']} | {r['crediti']} | {r['residui']} |")
    crediti = sum(float(r["crediti"] or 0) for r in per_lega)
    A(f"\nCrediti spesi nel run: **{crediti:g}** (una chiamata per lega, {len(per_lega)} chiamate).\n")
    A("## Eventi, Pinnacle e linee 2,5\n")
    A("| lega | eventi | con Pinnacle | Pinnacle: 2,5 | Pinnacle: altra intera/mezza | Pinnacle: asiatica | "
      "2,5 da ≥1 libro | 2,5 da ≥3 libri | regola soddisfatta | quota regola |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for r in per_lega:
        ev = r["eventi"] or 1
        pl = r["pin_linee"]
        A(f"| {r['lega']} | {r['eventi']} | {r['con_pinnacle']} | {pl['2,5']} | "
          f"{pl['intera o mezza (altra)'] + pl['altra']} | {pl['asiatica (quarto)']} | "
          f"{r['con_25_1']} | {r['con_25_3']} | {r['regola_ok']} | {r['regola_ok'] / ev * 100:.1f} % |")
    ev = tot["eventi"] or 1
    A(f"| **totale** | **{tot['eventi']}** | **{tot['con_pinnacle']}** | "
      f"**{pin_tot['2,5']}** | **{pin_tot['intera o mezza (altra)'] + pin_tot['altra']}** | "
      f"**{pin_tot['asiatica (quarto)']}** | **{tot['con_25_1']}** | **{tot['con_25_3']}** | "
      f"**{tot['regola_ok']}** | **{tot['regola_ok'] / ev * 100:.1f} %** |")
    A("")
    A("Pinnacle: la linea considerata è quella del libro più vicina a 2,5 (se ne offre più d'una). "
      "«Intera o mezza (altra)» = linee x,0 o x,5 diverse da 2,5; «asiatica» = quarti x,25 / x,75.\n")
    A("## Esito della regola\n")
    quota = tot["regola_ok"] / ev
    esito = "SUPERATA" if quota >= SOGLIA_QUOTA else "NON superata"
    A(f"Eventi che soddisfano la regola: **{tot['regola_ok']} / {tot['eventi']} = {quota * 100:.1f} %** "
      f"(soglia {SOGLIA_QUOTA * 100:.0f} %). Esito: **{esito}**. "
      "Per lega: vedi colonna «quota regola».\n")
    A("Eventi con linee multiple dello stesso libro nello stesso evento: "
      f"{sum(r['libri_con_linee_multiple'] for r in per_lega)} (contati a livello evento).\n")
    text = "\n".join(T) + "\n"
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
