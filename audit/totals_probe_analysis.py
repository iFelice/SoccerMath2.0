#!/usr/bin/env python3
"""totals_probe_analysis.py — analisi OFFLINE della sonda totals (audit).

Legge gli snapshot grezzi di ``audit/data/totals_probe/`` (scritti da
``audit/totals_probe.py``) e produce ``audit/results/totals_probe_analysis.md``.
Solo stdlib: nessuna rete, nessuna chiave, nessuna dipendenza di produzione.

Riporta:
  1. crediti spesi (header ``x-requests-last`` per chiamata; ``x-requests-used``
     e ``x-requests-remaining`` dell'ultima risposta);
  2. eventi per lega e quanti hanno Pinnacle (bookmaker key ``pinnacle``) sul mercato totals;
  3. distribuzione delle linee (2,5 / 2,25 / 2,75 / altre) per bookmaker, a livello
     evento (una linea per libro e per evento: la linea di quel libro);
  4. eventi con una linea 2,5 da almeno un bookmaker (e da Pinnacle);
  5. trattamento delle linee asiatiche (2,25 / 2,75): decisione dichiarata qui sotto.

TRATTAMENTO DELLE LINEE ASIATICHE (decisione dichiarata prima dei dati):
  * ESCLUSIONE nel confronto principale. Una linea 2,25 o 2,75 non e' un'estrazione
    di un Over 2,5: e' una combinazione di mezze puntate su due linee vicine (2,0 e
    2,5 per la 2,25; 2,5 e 3,0 per la 2,75) con rimborso parziale. Convertirla in
    P(Over 2,5) richiede di assumere come il libro prezza le due meta': e' un modello
    di prezzo non osservato, non un dato.
  * Il confronto 2,5 usa solo le partite con una linea 2,5 (da almeno un libro).
  * Sensibilita' (solo informativa, non implementata qui): conversione della
    linea 2,25/2,75 con la formula standard delle linee asiatiche, da confrontare
    con il sottoinsieme 2,5. Il numero di eventi che servirebbe questa conversione
    e' riportato in §4 come candidati.
"""

from __future__ import annotations

import glob
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_AUDIT_DIR, "data", "totals_probe")
REPORT = os.path.join(_AUDIT_DIR, "results", "totals_probe_analysis.md")
PINNACLE = "pinnacle"
BUCKETS = ("2,5", "2,25", "2,75", "altre")


def bucket_of(point) -> str:
    """Classe la linea totals. 2.5 esatto, 2.25 / 2.75 (linee asiatiche), altre."""
    try:
        x = float(point)
    except (TypeError, ValueError):
        return "altre"
    if abs(x - 2.5) < 1e-9:
        return "2,5"
    if abs(x - 2.25) < 1e-9:
        return "2,25"
    if abs(x - 2.75) < 1e-9:
        return "2,75"
    return "altre"


def event_lines(event: dict) -> dict:
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
                out[bk.get("key")] = sorted(points)[0]   # linee multiple nello stesso libro: ne tengo una
    return out


def load_snapshots(data_dir: str):
    snaps = []
    for path in sorted(glob.glob(os.path.join(data_dir, "*.json"))):
        if os.path.basename(path).startswith("_"):
            continue
        with open(path, encoding="utf-8") as fh:
            snaps.append((os.path.basename(path), json.load(fh)))
    return snaps


def analyse(snaps):
    res = {"leghe": [], "crediti": {}, "per_bookmaker": defaultdict(Counter),
           "eventi_totali": 0, "eventi_con_pinnacle": 0, "eventi_con_2_5": 0,
           "eventi_con_2_5_pinnacle": 0, "eventi_solo_asiatiche": 0,
           "eventi_asiatiche_candidati": 0, "libri": Counter()}
    last_headers = {}
    for name, env in snaps:
        body = env.get("body") or []
        headers = env.get("headers") or {}
        last_headers = headers or last_headers
        res["crediti"][env.get("sport_key")] = headers.get("x-requests-last")
        n_ev = len(body) if isinstance(body, list) else 0
        res["leghe"].append({"lega": env.get("lega"), "file": name, "status": env.get("status"),
                             "ok": env.get("ok"), "eventi": n_ev, "errore": env.get("error")})
        if not isinstance(body, list):
            continue
        for ev in body:
            res["eventi_totali"] += 1
            lines = event_lines(ev)
            for bk, pt in lines.items():
                res["per_bookmaker"][bk][bucket_of(pt)] += 1
                res["libri"][bk] += 1
            if PINNACLE in lines:
                res["eventi_con_pinnacle"] += 1
            if any(bucket_of(p) == "2,5" for p in lines.values()):
                res["eventi_con_2_5"] += 1
            if lines.get(PINNACLE) is not None and bucket_of(lines[PINNACLE]) == "2,5":
                res["eventi_con_2_5_pinnacle"] += 1
            kinds = {bucket_of(p) for p in lines.values()}
            if lines and "2,5" not in kinds and kinds & {"2,25", "2,75"}:
                res["eventi_solo_asiatiche"] += 1
            if kinds & {"2,25", "2,75"}:
                res["eventi_asiatiche_candidati"] += 1
    res["ultimi_header"] = {k: last_headers.get(k) for k in
                            ("x-requests-used", "x-requests-remaining", "x-requests-last")}
    return res


def md_table(headers, rows):
    head = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join(["---"] * len(headers)) + "|"
    return "\n".join([head, sep] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def build_md(res: dict, generato_il: str, snaps_n: int) -> str:
    T = []
    A = T.append
    A("# Sonda The Odds API — mercato totals (audit, offline)\n")
    A(f"Generato da `audit/totals_probe_analysis.py` il {generato_il} a partire da {snaps_n} snapshot "
      "in `audit/data/totals_probe/`. Nessuna chiamata di rete, nessuna chiave.\n")
    A("## 1. Crediti spesi\n")
    crediti_tot = 0.0
    all_known = True
    rows = []
    for sk, v in res["crediti"].items():
        rows.append([sk, v if v is not None else "n/d"])
        try:
            crediti_tot += float(v)
        except (TypeError, ValueError):
            all_known = False
    A(md_table(["lega (sport_key)", "x-requests-last (crediti della chiamata)"], rows))
    A("")
    A(f"**Crediti spesi: {crediti_tot:g}{'' if all_known else ' (parziale: alcuni header assenti)'}.** "
      f"Ultimo stato del conto: used={res['ultimi_header'].get('x-requests-used')}, "
      f"remaining={res['ultimi_header'].get('x-requests-remaining')}.\n")
    A("## 2. Eventi e Pinnacle\n")
    A(md_table(["lega", "file", "status", "eventi"],
               [[x["lega"], x["file"], x["status"], x["eventi"]] for x in res["leghe"]]))
    A("")
    ev = res["eventi_totali"]
    A(f"- Eventi totali: **{ev}**.")
    A(f"- Eventi con **Pinnacle** sul mercato totals: **{res['eventi_con_pinnacle']}**"
      + (f" ({res['eventi_con_pinnacle'] / ev * 100:.1f} %)." if ev else "."))
    A("")
    A("## 3. Linee per bookmaker (una linea per libro e per evento)\n")
    rows = []
    for bk, cnt in sorted(res["per_bookmaker"].items(), key=lambda kv: -sum(kv[1].values())):
        tot = sum(cnt.values())
        rows.append([bk, tot] + [cnt.get(b, 0) for b in BUCKETS])
    A(md_table(["bookmaker", "eventi con totals"] + [f"linea {b}" for b in BUCKETS], rows) if rows
      else "Nessuna linea totals nei file.")
    A("")
    A("## 4. Eventi con linea 2,5 e linee asiatiche\n")
    A(md_table(["misura", "eventi"], [
        ["con una linea 2,5 da almeno un bookmaker", res["eventi_con_2_5"]],
        ["con una linea 2,5 da Pinnacle", res["eventi_con_2_5_pinnacle"]],
        ["con SOLO linee asiatiche (2,25 / 2,75), nessuna 2,5", res["eventi_solo_asiatiche"]],
        ["con almeno una linea asiatica (candidati alla sensibilita')", res["eventi_asiatiche_candidati"]],
    ]))
    A("")
    A("## 5. Trattamento delle linee asiatiche\n")
    A("Decisione dichiarata in `audit/totals_probe_analysis.py` (prima dei dati): **esclusione** nel "
      "confronto principale; la conversione e' solo sensibilita', non implementata. Motivo: una linea "
      "2,25/2,75 e' una combinazione di mezze puntate su linee vicine con rimborso parziale. Per "
      "convertirla in P(Over 2,5) bisogna assumere come il libro prezza le due meta': non e' un dato "
      "osservato.\n")
    if res["eventi_totali"] == 0:
        A("**Esito: sonda NON ESEGUITA o senza eventi.** Il workflow `totals_probe.yml` non ha ancora "
          "prodotto snapshot con eventi. Nessun numero di questo referto e' un risultato.\n")
    A("## 6. Limiti\n")
    A("- Una linea per libro e per evento: se un libro offre piu' linee nello stesso evento se ne tiene la piu' bassa.")
    A("- La sonda misura la DISPONIBILITA' delle linee, non le quote Over/Under: le quote sono nel corpo grezzo e "
      "non vengono usate qui.")
    A("- L'ora della rilevazione e' quella della chiamata (`fetched_at_utc`), non l'ora di chiusura del mercato.")
    return "\n".join(T) + "\n"


def main(argv=None) -> int:
    snaps = load_snapshots(DATA_DIR)
    generato = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = analyse(snaps)
    text = build_md(res, generato, len(snaps))
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"referto: {REPORT} (snapshot: {len(snaps)}, eventi: {res['eventi_totali']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
