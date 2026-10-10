#!/usr/bin/env python3
"""totals_probe_diagnosi.py — punto 3: diagnosi della sonda totals (audit, offline).

Legge SOLO lo snapshot storico `2026-10-10_1703` in
``audit/data/totals_probe/`` (5 risposte, mercato totals, 82 eventi). Nessuna
chiamata di rete, nessuna chiave, solo stdlib.

Riporta:
  1. classificazione per CAUSA dei 26 eventi che non superano la regola dell'85 %,
     con tabella per lega;
  2. distribuzione dei giorni mancanti al calcio d'inizio al momento della chiamata
     (tutti gli 82 eventi) e la stessa classificazione separata fra eventi entro
     7 giorni e oltre 7 giorni;
  3. costo reale della sonda in crediti dagli header di ogni chiamata
     (``x-requests-last``, ``x-requests-used``, ``x-requests-remaining``), con la
     correzione dello stato finale.

REGOLE DICHIARATE (scritte prima dei numeri; identiche a §0.3 del referto):

  D1. Regola della sonda (come PR #59): un evento la soddisfa se **Pinnacle ha la
      linea 2,5** OPPURE **almeno 3 bookmaker hanno la linea 2,5** (linea 2,5 esatta
      sul mercato totals; un libro = una linea per evento, la piu' bassa se ne
      offre piu' d'una, come ``totals_probe_analysis.py``).
  D2. Classificazione per causa: si assegna a ogni evento che NON supera la regola
      la PRIMA causa applicabile in questo ordine:
        C1 Pinnacle assente sul mercato totals dell'evento;
        C2 Pinnacle presente con linea ≠ 2,5 (la linea e' specificata:
           1,5 / 3,5 / altra mezza / intera / a quarti);
        C3 Pinnacle con la 2,5 ma meno di 3 libri con la 2,5;
        C4 altro (nessuna linea totals nell'evento, o causa non riconducibile).
      Poiche' la regola e' un OR, ogni evento che non la supera soddisfa ANCHE la
      condizione «meno di 3 bookmaker con la 2,5»: la priorita' evita i doppi
      conteggi e il numero di libri con la 2,5 (0 / 1 / 2) e' riportato a parte.
  D3. Giorni mancanti = (``commence_time`` − ``fetched_at_utc``) in giorni, in
      virgola mobile (negativo = partita gia' iniziata al momento della chiamata).
      Fasce dichiarate: < 0 (gia' iniziata), [0-1), [1-2), [2-7), [7-14), ≥ 14.
      «Entro 7 giorni» = giorni mancanti ≤ 7 (inclusi i valori negativi);
      «oltre 7 giorni» = giorni mancanti > 7.
  D4. Stato finale dei crediti = quello dell'ULTIMA CHIAMATA IN ORDINE DI TEMPO,
      non dell'ultima lega in ordine alfabetico. Ordine ricostruito dalla chiave
      (``fetched_at_utc``, ``x-requests-used``): il contatore usati e' monotono
      crescente, quindi e' il tie-break naturale a parita' di secondo (i timestamp
      hanno risoluzione di 1 secondo).

Output: audit/results/punto3_diagnosi_sonda_totals.md, audit/output/punto3_diagnosi.json.
Uso: python audit/totals_probe_diagnosi.py
"""

from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter, OrderedDict
from datetime import datetime, timezone

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.path.join(_AUDIT_DIR, "data", "totals_probe")
DATA_DIR = os.path.join(DATA_ROOT, "2026-10-10_1703")
REPORT = os.path.join(_AUDIT_DIR, "results", "punto3_diagnosi_sonda_totals.md")
JSON_OUT = os.path.join(_AUDIT_DIR, "output", "punto3_diagnosi.json")

PINNACLE = "pinnacle"
SOGLIA_LIBRI = 3
SOGLIA_GIORNI = 7.0
FASCE_GIORNI = [("< 0 (già iniziata)", float("-inf"), 0.0), ("[0-1)", 0.0, 1.0),
                ("[1-2)", 1.0, 2.0), ("[2-7)", 2.0, 7.0), ("[7-14)", 7.0, 14.0),
                ("≥ 14", 14.0, float("inf"))]


def _parse(ts):
    if not ts:
        return None
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def _bucket(point):
    """Tipo di linea totals: '2,5' / '1,5' / '3,5' / 'altra mezza' / 'intera' / 'a quarti'."""
    try:
        x = float(point)
    except (TypeError, ValueError):
        return "non numerica", None
    if abs(x - 2.5) < 1e-9:
        return "2,5", x
    if abs(x - 1.5) < 1e-9:
        return "1,5", x
    if abs(x - 3.5) < 1e-9:
        return "3,5", x
    n4 = x * 4.0
    if abs(n4 - round(n4)) > 1e-9:
        return "non ammessa", x
    if round(n4) % 2 == 0 and round(n4) % 4 != 0:      # x,5 (diversa da 1,5 / 2,5 / 3,5)
        return "altra mezza", x
    if round(n4) % 4 == 0:                             # x,0
        return "intera", x
    return "a quarti", x                               # x,25 / x,75


def event_lines(event):
    """{bookmaker_key: point} per il mercato totals (una linea per libro)."""
    out = {}
    for bk in event.get("bookmakers") or []:
        for mk in bk.get("markets") or []:
            if mk.get("key") != "totals":
                continue
            points = {o.get("point") for o in mk.get("outcomes") or []
                      if o.get("name") in ("Over", "Under") and o.get("point") is not None}
            if len(points) == 1:
                out[bk.get("key")] = points.pop()
            elif len(points) > 1:
                out[bk.get("key")] = sorted(points)[0]
    return out


def load_snapshots():
    snaps = []
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "*.json"))):
        if os.path.basename(path).startswith("_"):
            continue
        with open(path, encoding="utf-8") as fh:
            snaps.append((os.path.basename(path), json.load(fh)))
    return snaps


def ordine_cronologico(snaps):
    """Snapshots ordinati per (fetched_at_utc, x-requests-used).

    Regola D4: lo stato finale e' quello dell'ultima chiamata in ordine di TEMPO.
    Con timestampa risoluzione di 1 secondo il tie-break e' il contatore
    ``x-requests-used`` (monotono crescente). Snapshot senza data vanno in fondo.
    """
    def chiave(item):
        _nome, env = item
        ts = _parse(env.get("fetched_at_utc"))
        used = env.get("headers", {}).get("x-requests-used")
        try:
            used = float(used)
        except (TypeError, ValueError):
            used = -1.0
        return (ts is None, ts or datetime.min.replace(tzinfo=timezone.utc), used)
    return sorted(snaps, key=chiave)


def analizza(snaps):
    eventi = []
    for _nome, env in snaps:
        lega = env.get("lega")
        fetched = _parse(env.get("fetched_at_utc"))
        for ev in env.get("body") or []:
            lines = event_lines(ev)
            n_25 = sum(1 for p in lines.values() if _bucket(p)[0] == "2,5")
            pin = lines.get(PINNACLE)
            pin_tipo, pin_val = _bucket(pin) if pin is not None else ("assente", None)
            regola = (pin is not None and pin_tipo == "2,5") or (n_25 >= SOGLIA_LIBRI)
            ct = _parse(ev.get("commence_time"))
            giorni = (ct - fetched).total_seconds() / 86400.0 if (ct and fetched) else None
            eventi.append({
                "id": ev.get("id"), "lega": lega, "home": ev.get("home_team"),
                "away": ev.get("away_team"), "commence_time": ev.get("commence_time"),
                "giorni": giorni, "n_libri": len(lines), "n_25": n_25,
                "pinnacle": pin, "pinnacle_tipo": pin_tipo, "pinnacle_val": pin_val,
                "regola": bool(regola), "libri_25": sorted(k for k, p in lines.items()
                                                           if _bucket(p)[0] == "2,5"),
            })
    return eventi


def causa(ev):
    """Regola D2: prima causa applicabile, in ordine C1 -> C4."""
    if ev["pinnacle"] is None:
        if ev["n_libri"] == 0:
            return "C4 altro (nessuna linea totals nell'evento)"
        return "C1 Pinnacle assente"
    if ev["pinnacle_tipo"] != "2,5":
        return "C2 Pinnacle con linea " + {
            "1,5": "1,5", "3,5": "3,5", "altra mezza": "altra mezza",
            "intera": "intera", "a quarti": "a quarti",
        }.get(ev["pinnacle_tipo"], ev["pinnacle_tipo"])
    if ev["n_25"] < SOGLIA_LIBRI:
        return "C3 Pinnacle 2,5 con meno di 3 libri a 2,5"
    return "C4 altro"


def md_table(headers, rows):
    head = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join(["---"] * len(headers)) + "|"
    return "\n".join([head, sep] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def fmt(x, nd=1):
    if x is None:
        return "n/d"
    return f"{float(x):.{nd}f}".replace(".", ",")


def pct(x, nd=1):
    return "n/d" if x is None else fmt(100.0 * float(x), nd) + " %"


def distribuzione(vals):
    v = sorted(vals)
    n = len(v)

    def q(f):
        if n == 0:
            return None
        i = min(n - 1, max(0, int(round(f * (n - 1)))))
        return v[i]
    return {"n": n, "min": v[0] if n else None, "p10": q(0.10), "p25": q(0.25),
            "mediana": q(0.50), "p75": q(0.75), "p90": q(0.90), "max": v[-1] if n else None,
            "media": sum(v) / n if n else None}


def main(argv=None) -> int:
    snaps = load_snapshots()
    ordinate = ordine_cronologico(snaps)
    eventi = analizza(snaps)
    ok = [e for e in eventi if e["regola"]]
    ko = [e for e in eventi if not e["regola"]]
    for e in ko:
        e["causa"] = causa(e)

    generato = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    T = []
    A = T.append
    A("## 3. Punto 3 — diagnosi della sonda totals (sui file grezzi, offline)\n")
    A(f"Generato da `audit/totals_probe_diagnosi.py` il {generato} dai 5 snapshot grezzi in "
      f"`audit/data/totals_probe/`. Nessuna chiamata di rete, nessuna chiave, nessuna nuova "
      f"richiesta a The Odds API.\n")
    A(f"Eventi totali: **{len(eventi)}** · superano la regola: **{len(ok)}** "
      f"({pct(len(ok) / len(eventi))}) · non la superano: **{len(ko)}** "
      f"({pct(len(ko) / len(eventi))}). Soglia dell'85 %: **NON superata** (come in PR #59). "
      "Solo descrittivo: nessuna conseguenza sul codice.\n")

    # ---- 3.1 classificazione per causa
    A("### 3.1 I 26 eventi che non superano la regola, per causa\n")
    A("Causa assegnata per priorità (D2): C1 Pinnacle assente → C2 Pinnacle con linea ≠ 2,5 → "
      "C3 Pinnacle 2,5 con meno di 3 libri → C4 altro. Poiché la regola è un OR, tutti i 26 "
      "hanno anche meno di 3 libri con la 2,5: il conteggio per numero di libri è sotto.\n")
    conteggi = Counter(e["causa"] for e in ko)
    A(md_table(["causa", "eventi"], [[c, n] for c, n in sorted(conteggi.items())]))
    A("")
    leghe = [e["lega"] for e in eventi]
    ordine_leghe = list(OrderedDict.fromkeys(leghe))
    intestazioni_causa = sorted(conteggi)
    rows = []
    for lg in ordine_leghe:
        ko_lg = [e for e in ko if e["lega"] == lg]
        n_ev = sum(1 for e in eventi if e["lega"] == lg)
        n_ok = sum(1 for e in ok if e["lega"] == lg)
        riga = [lg, n_ev, n_ok, len(ko_lg)] + [sum(1 for e in ko_lg if e["causa"] == c)
                                               for c in intestazioni_causa]
        rows.append(riga)
    rows.append(["**totale**", len(eventi), len(ok), len(ko)]
                + [conteggi[c] for c in intestazioni_causa])
    A(md_table(["lega", "eventi", "superano la regola", "non la superano"] + intestazioni_causa, rows))
    A("")

    # linee Pinnacle nei 26
    A("#### 3.1.1 Linea di Pinnacle nei 26 eventi (quando presente)\n")
    tipi = Counter(e["pinnacle_tipo"] for e in ko)
    A(md_table(["linea Pinnacle", "eventi"],
               [[f"{t}" + (f" (valore {fmt(e['pinnacle_val'], 2)})" if False else ""), n]
                for t, n in sorted(tipi.items())]))
    A("")
    dettaglio = Counter()
    for e in ko:
        if e["pinnacle"] is not None:
            dettaglio[f"{e['pinnacle_val']}"] += 1
    A("Valori esatti della linea Pinnacle nei 26 eventi: "
      + (", ".join(f"**{k}** × {v}" for k, v in sorted(dettaglio.items(), key=lambda kv: float(kv[0])))
         if dettaglio else "nessuno (Pinnacle sempre assente)")
      + ".\n")
    A("#### 3.1.2 Quanti libri offrono la 2,5 nei 26 eventi\n")
    c25 = Counter(min(e["n_25"], 2) for e in ko)
    A(md_table(["libri con la linea 2,5", "eventi"],
               [[("0" if k == 0 else ("1" if k == 1 else "2")), c25.get(k, 0)]
                for k in (0, 1, 2)]))
    A("")
    A("C3 è vuota **per costruzione**: se Pinnacle ha la 2,5 la regola è soddisfatta, quindi un "
      "evento che non la supera non può avere Pinnacle a 2,5.\n")

    # ---- 3.2 giorni mancanti
    A("### 3.2 Giorni mancanti al calcio d'inizio al momento della chiamata\n")
    giorni = [e["giorni"] for e in eventi if e["giorni"] is not None]
    d = distribuzione(giorni)
    A(md_table(["misura", "giorni"],
               [["n", d["n"]], ["minimo", fmt(d["min"], 2)], ["p10", fmt(d["p10"], 2)],
                ["p25", fmt(d["p25"], 2)], ["mediana", fmt(d["mediana"], 2)],
                ["p75", fmt(d["p75"], 2)], ["p90", fmt(d["p90"], 2)], ["massimo", fmt(d["max"], 2)],
                ["media", fmt(d["media"], 2)]]))
    A("")
    rows = []
    for nome, lo, hi in FASCE_GIORNI:
        if nome.startswith("<"):
            n = sum(1 for g in giorni if g < 0.0)
        else:
            n = sum(1 for g in giorni if lo <= g < hi)
        rows.append([nome, n, pct(n / len(giorni) if giorni else 0.0)])
    A(md_table(["fascia di giorni mancanti", "eventi", "quota"], rows))
    A("")
    rows = []
    for lg in ordine_leghe:
        gg = [e["giorni"] for e in eventi if e["lega"] == lg and e["giorni"] is not None]
        dd = distribuzione(gg)
        rows.append([lg, len(gg), fmt(dd["min"], 2), fmt(dd["mediana"], 2), fmt(dd["max"], 2)])
    A(md_table(["lega", "eventi", "minimo", "mediana", "massimo"], rows))
    A("")

    # ---- 3.3 entro / oltre 7 giorni
    A("### 3.3 Stessa classificazione separata: entro 7 giorni e oltre 7 giorni\n")
    entro = [e for e in eventi if e["giorni"] is not None and e["giorni"] <= SOGLIA_GIORNI]
    oltre = [e for e in eventi if e["giorni"] is not None and e["giorni"] > SOGLIA_GIORNI]
    rows = []
    for tag, grp in (("entro 7 giorni", entro), ("oltre 7 giorni", oltre)):
        n_ok_g = sum(1 for e in grp if e["regola"])
        n_ko_g = len(grp) - n_ok_g
        rows.append([tag, len(grp), n_ok_g, pct(n_ok_g / len(grp) if grp else 0.0), n_ko_g])
    rows.append(["**tutti**", len(eventi), len(ok), pct(len(ok) / len(eventi)), len(ko)])
    A(md_table(["gruppo", "eventi", "superano la regola", "quota", "non la superano"], rows))
    A("")
    A("Causa degli eventi che non superano la regola, nei due gruppi:\n")
    rows = []
    for tag, grp in (("entro 7 giorni", entro), ("oltre 7 giorni", oltre)):
        ko_g = [e for e in grp if not e["regola"]]
        for e in ko_g:
            if "causa" not in e:
                e["causa"] = causa(e)
        cg = Counter(e["causa"] for e in ko_g)
        rows.append([tag, len(ko_g)] + [cg.get(c, 0) for c in intestazioni_causa])
    A(md_table(["gruppo", "non superano"] + intestazioni_causa, rows))
    A("")
    A(f"«Entro 7 giorni» = giorni mancanti ≤ {fmt(SOGLIA_GIORNI, 0)} (comprese le partite gia' "
      "iniziate al momento della chiamata); «oltre 7 giorni» = giorni mancanti > 7. Lettura "
      "solo descrittiva: la quota dell'85 % non e' raggiunta in nessuno dei due gruppi.\n")

    # ---- 3.4 crediti
    A("### 3.4 Costo reale della sonda in crediti (dagli header)\n")
    rows = []
    tot_last = 0.0
    for i, (_nome, env) in enumerate(ordinate, start=1):
        h = env.get("headers") or {}
        last = h.get("x-requests-last")
        try:
            tot_last += float(last)
        except (TypeError, ValueError):
            pass
        rows.append([i, env.get("sport_key"), env.get("fetched_at_utc"), last,
                     h.get("x-requests-used"), h.get("x-requests-remaining"),
                     len(env.get("body") or [])])
    A(md_table(["# (ordine di tempo)", "sport_key", "fetched_at_utc", "x-requests-last (costo)",
                "x-requests-used", "x-requests-remaining", "eventi"], rows))
    A("")
    ultimo = ordinate[-1][1] if ordinate else {}
    uh = ultimo.get("headers") or {}
    primo = ordinate[0][1] if ordinate else {}
    ph = primo.get("headers") or {}
    A(f"**Crediti spesi nel run: {tot_last:g}** (una chiamata per lega, 5 chiamate). "
      f"Stato finale (ultima chiamata in ordine di tempo, `{ultimo.get('sport_key')}` alle "
      f"{ultimo.get('fetched_at_utc')}): **used = {uh.get('x-requests-used')}, "
      f"remaining = {uh.get('x-requests-remaining')}**. "
      f"Stato prima del run (prima chiamata, `{primo.get('sport_key')}`): used = "
      f"{ph.get('x-requests-used')}, remaining = {ph.get('x-requests-remaining')}.\n")
    A("**Correzione dello stato finale.** `audit/results/totals_probe_analysis.md` riporta "
      "«used=61, remaining=439»: è lo stato della chiamata `soccer_spain_la_liga`, l'ULTIMA LEGA "
      "IN ORDINE ALFABETICO, non l'ultima chiamata in ordine di tempo. Con la chiave "
      "(`fetched_at_utc`, `x-requests-used`) l'ultima chiamata è "
      f"`{ultimo.get('sport_key')}` (usati {uh.get('x-requests-used')}, residui "
      f"{uh.get('x-requests-remaining')}). La correzione è stata applicata in "
      "`audit/totals_probe_analysis.py` (funzione `ordine_cronologico` + scelta dello stato "
      "finale) e in `audit/totals_probe.py` (stato finale preso per max della stessa chiave, non "
      "dall'ultima lega del ciclo). Il numero di crediti spesi (5) non cambia: cambia lo stato "
      "del conto attribuito al run.\n")

    A("### 3.5 Limiti\n")
    A("- La sonda misura la DISPONIBILITÀ delle linee totals, non le quote Over/Under: le quote "
      "sono nel corpo grezzo e qui non sono state usate (solo nel punto 4, per il confronto fra "
      "griglie).")
    A("- Una linea per libro e per evento: se un libro offre più linee se ne tiene la più bassa, "
      "come in `totals_probe_analysis.py`.")
    A("- L'ora della chiamata è `fetched_at_utc` (risoluzione 1 secondo): i giorni mancanti hanno "
      "quindi un'incertezza dell'ordine del secondo, irrilevante sulle fasce usate.")
    A("- Lo snapshot è unico (2026-10-10): la relazione fra giorni mancanti e disponibilità della "
      "2,5 è misurata su 82 eventi di una sola giornata tipo ed è descrittiva, non una stampa "
      "di un effetto.\n")

    testo = "\n".join(T) + "\n"
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write(testo)
    os.makedirs(os.path.dirname(JSON_OUT), exist_ok=True)
    with open(JSON_OUT, "w", encoding="utf-8") as fh:
        json.dump({"generato": generato, "n_eventi": len(eventi), "n_ok": len(ok), "n_ko": len(ko),
                   "causa_ko": dict(conteggi), "giorni": {k: v for k, v in d.items()},
                   "crediti": {"spesi": tot_last,
                               "ultimo": {"sport_key": ultimo.get("sport_key"),
                                          "headers": uh},
                               "primo": {"sport_key": primo.get("sport_key"), "headers": ph}},
                   "entro_7": {"n": len(entro), "ok": sum(1 for e in entro if e["regola"])},
                   "oltre_7": {"n": len(oltre), "ok": sum(1 for e in oltre if e["regola"])},
                   "eventi_ko": [{k: v for k, v in e.items()} for e in ko]},
                  fh, ensure_ascii=False, indent=1)
    print(testo)
    print(f"[punto3] referto: {REPORT} · json: {JSON_OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
