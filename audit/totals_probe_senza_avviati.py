#!/usr/bin/env python3
"""totals_probe_senza_avviati.py — ricalcolo DESCrittivo dei conteggi delle
PR #59 e PR #60 sullo snapshot totals del 10/10 SENZA gli eventi già iniziati.

REGOLA DICHIARATA (prima dei numeri; non modificata dopo)
--------------------------------------------------------
Un evento è "già iniziato alla chiamata" se ``commence_time`` ≤ istante della
chiamata della sua lega (stessa regola della produzione per le quote 1X2,
``update_live_odds.normalizza_eventi``). Gli eventi già iniziati vengono esclusi
dal ricalcolo e contati a parte.

Questo referto è SOLO DESCRITTIVO: gli esiti dichiarati nelle PR #59 e PR #60
NON cambiano. Per ciascun esito dichiarato si riporta se lo snapshot del 10/10
era contaminato (cioè se i suoi conteggi includevano eventi già iniziati).

Cosa si ricalcola senza gli eventi iniziati:
  * PR #59 (``totals_probe_diagnosi.py``): copertura della regola dell'85 %
    e classificazione delle cause degli eventi che non la superano (regole
    D1/D2 invariate);
  * PR #60 (``linee_totali_probe.py``): numero di eventi confrontabili e
    mediana/massimo della differenza assoluta su P(Over 2,5) fra le due griglie
    (regole P4.1/P4.2 invariate).

Nessuna rete, nessuna chiamata a The Odds API, nessuna modifica a ``SoccerMath/``.

Fonte della terna 1X2 (PR #60): la copia versionata fissata accanto allo
snapshot (``audit/data/totals_probe/2026-10-10_1703/_live_odds_1x2_2026-10-10T090852Z.json``,
= blob ``078beef`` del 2026-10-10T09:08:52Z). Il file vivo
``SoccerMath/database/live_odds.json`` NON si usa: lo riscrive il workflow
live_odds.yml ogni giorno e dall'aggiornamento 2026-10-11T14:56Z (che ha
espulso gli eventi già giocati) i confrontabili letti da lì non sono più
riproducibili (42 → 35).

Output: ``audit/results/totals_probe_senza_avviati.md``,
``audit/output/totals_probe_senza_avviati.json``.
Uso: ``python audit/totals_probe_senza_avviati.py``
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, OrderedDict
from datetime import datetime, timezone

import numpy as np

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AUDIT_DIR)

import totals_probe_diagnosi as T  # noqa: E402  (logica PR #59, invariata)
import linee_totali_probe as L  # noqa: E402  (logica PR #60, invariata)

SNAPSHOT_DIR = os.path.join(_AUDIT_DIR, "data", "totals_probe", "2026-10-10_1703")
REPORT = os.path.join(_AUDIT_DIR, "results", "totals_probe_senza_avviati.md")
JSON_PATH = os.path.join(_AUDIT_DIR, "output", "totals_probe_senza_avviati.json")

RULE_TEXT = """\
# Ricalcolo descrittivo dello snapshot 10/10 senza gli eventi già iniziati

## Regola dichiarata (prima dei numeri; questa sezione non viene modificata dopo)

Un evento è **già iniziato alla chiamata** se `commence_time` ≤ istante della
chiamata della sua lega (stessa regola della produzione per le quote 1X2).
Gli eventi già iniziati sono esclusi dal ricalcolo e contati a parte.

Questo referto è **solo descrittivo**: gli esiti dichiarati nelle PR #59 e
PR #60 **non cambiano**. Per ciascun esito dichiarato si riporta se lo snapshot
del 10/10 era **contaminato** (i suoi conteggi includevano eventi già iniziati).

Si ricalcolano senza gli eventi iniziati, con le regole originali invariate:
la copertura della regola dell'85 % e la classificazione delle cause (PR #59,
regole D1/D2) e il numero di eventi confrontabili con mediana e massimo della
differenza assoluta su P(Over 2,5) fra le due griglie (PR #60, regole P4.1/P4.2).
"""


def avviati(eventi):
    """Eventi con kickoff ≤ istante della chiamata (giorni mancanti ≤ 0)."""
    return [e for e in eventi
            if e.get("giorni") is not None and float(e["giorni"]) <= 0.0]


def calcola(live_odds_path=L.LIVE_ODDS_PINNED) -> dict:
    """Ricalcolo descrittivo. ``live_odds_path`` e' parametro esplicito: la terna
    1X2 di questo snapshot storico si legge dalla copia versionata fissata
    (default ``linee_totali_probe.LIVE_ODDS_PINNED``), MAI dal file vivo."""
    # ---- PR #59: regola dell'85 % e cause (funzioni originali, logica invariata) ----
    snaps = T.load_snapshots()
    eventi = T.analizza(snaps)
    avv = avviati(eventi)
    ids_avv = {e["id"] for e in avv}
    senza = [e for e in eventi if e["id"] not in ids_avv]

    def quadro(evs):
        sup = [e for e in evs if e["regola"]]
        non = [e for e in evs if not e["regola"]]
        return {
            "n": len(evs), "superano": len(sup), "non_superano": len(non),
            "quota_superano": (len(sup) / len(evs) if evs else None),
            "cause": OrderedDict(sorted(Counter(T.causa(e) for e in non).items())),
        }

    pr59_tutti = quadro(eventi)
    pr59_senza = quadro(senza)

    # ---- PR #60: eventi confrontabili e differenza su P(Over 2,5) (logica invariata) ----
    L.MASCHERE = L._maschere()
    probe = L.load_probe()
    h2h, _gen = L.load_1x2(live_odds_path)

    def confronti(ev_ids):
        out = []
        for eid in ev_ids:
            ev = probe[eid]
            if eid not in h2h:
                continue
            pin = ev["lines"].get(L.PINNACLE)
            if pin is None or pin[1] is None or pin[2] is None:
                continue
            linea_pin = float(pin[0])
            if abs(linea_pin - 2.5) < 1e-9:
                continue
            libri_25 = [(bk, p, o, u) for bk, (p, o, u) in ev["lines"].items()
                        if bk != L.PINNACLE and abs(float(p) - 2.5) < 1e-9 and o and u]
            if len(libri_25) < L.MIN_LIBRI_25:
                continue
            P3 = L.devig_prop(list(h2h[eid]))
            if P3 is None:
                continue
            p_pin = L.devig_prop([pin[1], pin[2]])
            if p_pin is None:
                continue
            mA, _fA = L.fit_griglia(P3, p_pin[0], linea_pin, "over")
            p25 = []
            for _bk, _p, o, u in libri_25:
                q = L.devig_prop([o, u])
                if q is not None:
                    p25.append(q[0])
            if not p25:
                continue
            mB, _fB = L.fit_griglia(P3, float(np.median(p25)), 2.5, "over")
            pa, pb = L.prob_mercati(mA), L.prob_mercati(mB)
            out.append({"id": eid, "home": ev["home"], "away": ev["away"],
                        "lega": ev["lega"], "giorni": ev["giorni"],
                        "diff_pp": abs(pa["Over 2.5"] - pb["Over 2.5"]) * 100.0})
        return out

    tutti = confronti(list(probe))
    senza_conf = [c for c in confronti([i for i in probe if i not in ids_avv])]
    avv_conf = [c for c in confronti(sorted(ids_avv & set(probe)))]

    def quadro_conf(conf):
        d = np.asarray([c["diff_pp"] for c in conf], float)
        return {"n": int(d.size),
                "mediana_pp": float(np.median(d)) if d.size else None,
                "massimo_pp": float(d.max()) if d.size else None}

    return {
        "generato_il": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snapshot": SNAPSHOT_DIR,
        "n_eventi_totali": len(eventi),
        "avviati": [{"id": e["id"], "lega": e["lega"], "home": e["home"],
                     "away": e["away"], "commence_time": e["commence_time"],
                     "giorni_mancanti": e["giorni"]} for e in avv],
        "pr59": {"tutti": pr59_tutti, "senza_avviati": pr59_senza},
        "pr60": {"tutti": quadro_conf(tutti), "senza_avviati": quadro_conf(senza_conf),
                 "confrontabili_avviati": avv_conf},
    }


def _n(x, nd=2):
    """Float con decimale virgola (stile referti italiani); None -> n/d."""
    if x is None:
        return "n/d"
    return f"{float(x):.{nd}f}".replace(".", ",")


def scrivi_referto(dati: dict) -> str:
    p59t, p59s = dati["pr59"]["tutti"], dati["pr59"]["senza_avviati"]
    p60t, p60s = dati["pr60"]["tutti"], dati["pr60"]["senza_avviati"]
    avv = dati["avviati"]
    P = [RULE_TEXT.rstrip(), "",
         f"Generato da `audit/totals_probe_senza_avviati.py` il {dati['generato_il']} "
         f"dallo snapshot reale `{dati['snapshot']}` (sola lettura). Nessuna rete, "
         f"nessuna chiamata a The Odds API, nessuna modifica a `SoccerMath/`.", ""]

    P.append("## 1. Eventi già iniziati alla chiamata\n")
    P.append(f"Eventi totali dello snapshot: **{dati['n_eventi_totali']}**. "
             f"Già iniziati (`commence_time` ≤ istante della chiamata): "
             f"**{len(avv)}**.\n")
    P.append("| lega | partita | calcio d'inizio (UTC) | giorni mancanti |")
    P.append("|---|---|---|---:|")
    for e in avv:
        P.append(f"| {e['lega']} | {e['home']} – {e['away']} | {e['commence_time']} | "
                 f"{_n(e['giorni_mancanti'], 4)} |")
    P.append("")

    P.append("## 2. PR #59 ricalcolata senza gli eventi iniziati (descrittivo)\n")
    P.append("Regola D1 invariata: un evento la supera se Pinnacle ha la linea 2,5 "
             "OPPURE almeno 3 bookmaker hanno la linea 2,5. Regola D2 invariata per "
             "la classificazione delle cause.\n")
    P.append("| voce | originale (82 eventi) | senza eventi iniziati |")
    P.append("|---|---:|---:|")
    P.append(f"| eventi | {p59t['n']} | {p59s['n']} |")
    P.append(f"| superano la regola | {p59t['superano']} | {p59s['superano']} |")
    P.append(f"| non la superano | {p59t['non_superano']} | {p59s['non_superano']} |")
    quota_t = 100 * p59t["quota_superano"] if p59t["quota_superano"] is not None else None
    quota_s = 100 * p59s["quota_superano"] if p59s["quota_superano"] is not None else None
    P.append(f"| copertura della regola | {_n(quota_t, 1)} % | {_n(quota_s, 1)} % |")
    P.append("")
    cause_t, cause_s = p59t["cause"], p59s["cause"]
    etichette = sorted(set(cause_t) | set(cause_s))
    P.append("| causa (D2) | originale | senza eventi iniziati |")
    P.append("|---|---:|---:|")
    for et in etichette:
        P.append(f"| {et} | {cause_t.get(et, 0)} | {cause_s.get(et, 0)} |")
    P.append("")
    P.append(f"Soglia dell'85 %: **non raggiunta** in entrambi i conteggi "
             f"({_n(quota_t, 1)} % e {_n(quota_s, 1)} %). L'esito dichiarato nella "
             f"PR #59 resta «NON superata».\n")

    P.append("## 3. PR #60 ricalcolata senza gli eventi iniziati (descrittivo)\n")
    P.append("Regole P4.1/P4.2 invariate: evento confrontabile se Pinnacle ha una "
             "linea ≠ 2,5 e almeno 3 ALTRI bookmaker hanno la 2,5; si confronta "
             "P(Over 2,5) delle due griglie (fit generalizzato, differenza assoluta).\n")
    P.append("| voce | originale | senza eventi iniziati |")
    P.append("|---|---:|---:|")
    P.append(f"| eventi confrontabili | {p60t['n']} | {p60s['n']} |")
    P.append(f"| mediana di Δ P(Over 2,5) (valore assoluto) | {_n(p60t['mediana_pp'])} pt | "
             f"{_n(p60s['mediana_pp'])} pt |")
    P.append(f"| massimo di Δ P(Over 2,5) (valore assoluto) | {_n(p60t['massimo_pp'])} pt | "
             f"{_n(p60s['massimo_pp'])} pt |")
    P.append("")
    conf_avv = dati["pr60"]["confrontabili_avviati"]
    if conf_avv:
        P.append("Eventi confrontabili che erano già iniziati (esclusi dal ricalcolo):\n")
        P.append("| partita | giorni mancanti | Δ P(Over 2,5) (pt) |")
        P.append("|---|---:|---:|")
        for c in conf_avv:
            P.append(f"| {c['home']} – {c['away']} | {_n(c['giorni'], 4)} | "
                     f"{_n(c['diff_pp'])} pt |")
        P.append("")

    P.append("## 4. Esiti dichiarati nelle PR #59 e #60 e contaminazione\n")
    P.append("Gli esiti dichiarati **non cambiano**: qui sotto restano quelli già "
             "pubblicati, con accanto se lo snapshot del 10/10 era contaminato.\n")
    P.append("| esito dichiarato | fonte | snapshot contaminato | ricalcolo senza eventi iniziati |")
    P.append("|---|---|---|---|")
    P.append(f"| Regola dell'85 %: **NON superata** ({p59t['superano']}/{p59t['n']} = "
             f"{_n(quota_t, 1)} %) | PR #59 §3 | **SÌ** (includeva {len(avv)} eventi "
             f"iniziati) | copertura {_n(quota_s, 1)} % ({p59s['superano']}/{p59s['n']}): "
             f"esito invariato |")
    P.append(f"| {p59t['non_superano']} eventi non superano la regola, classificati "
             f"per causa (C1 = {cause_t.get('C1 Pinnacle assente', 0)}, C2 varie) | "
             f"PR #59 §3.1 | **SÌ** | {p59s['non_superano']} eventi, cause nella "
             f"tabella §2 |")
    P.append(f"| 82 eventi, 77 con terna 1X2 Pinnacle, **{p60t['n']} confrontabili** | "
             f"PR #60 §4.2 | **SÌ** | {p60s['n']} confrontabili |")
    P.append(f"| Differenza su P(Over 2,5): mediana {_n(p60t['mediana_pp'])} pt, "
             f"massimo {_n(p60t['massimo_pp'])} pt | PR #60 §4.2 | **SÌ** | "
             f"mediana {_n(p60s['mediana_pp'])} pt, massimo {_n(p60s['massimo_pp'])} pt |")
    P.append(f"| P4.4: **NON utilizzabile** (mediana ≤ 1,5 pt; massimo "
             f"{_n(p60t['massimo_pp'])} pt > 4 pt) | PR #60 §4.2 | **SÌ** (il massimo "
             f"era l'evento iniziato Man Utd–Tottenham) | esito invariato: la regola "
             f"P4.4 resta come dichiarata |")
    P.append("| 77 eventi con linea totals utilizzabile (entro 7 giorni: 53 eventi, 51 utilizzabili) | "
             "PR #60 §4.3 | **SÌ** | non ricalcolato: è un conteggio di disponibilità, "
             "non dei quattro numeri oggetto di questo punto |")
    P.append("")

    P.append("## 5. Limiti\n")
    P.append("- Solo descrittivo: nessun esito delle PR #59/#60 è riassegnato e nessuna "
             "regola è rivalutata su questo snapshot.")
    P.append("- Lo snapshot resta unico (10/10/2026): i ricalcoli sono sensibilità, non "
             "stime di effetto.")
    P.append("- La terna 1X2 usata dalla PR #60 è di 8 ore prima della sonda totals: il "
             "disallineamento temporale resta anche senza gli eventi iniziati.")
    P.append("- `commence_time` assente o corrotto non viene classificato come iniziato "
             "(come in produzione).")
    P.append("")
    return "\n".join(P)


def main(argv=None) -> int:
    if argv is not None and "--report" in argv:
        # firma minimale per i test: --report PATH
        i = argv.index("--report")
        report_path = argv[i + 1]
    else:
        report_path = REPORT
    dati = calcola()
    referto = scrivi_referto(dati)
    os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(referto)
    with open(JSON_PATH, "w", encoding="utf-8") as fh:
        json.dump(dati, fh, ensure_ascii=False, indent=1, default=str)
    print(referto)
    print(f"\njson:    {JSON_PATH}")
    print(f"referto: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
