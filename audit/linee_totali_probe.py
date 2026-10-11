#!/usr/bin/env python3
"""linee_totali_probe.py — punto 4: verifica su dati reali del fit generalizzato.

Confronta la griglia ricavata dagli stessi 1X2 con DUE linee totals diverse, sugli
eventi della sonda (file grezzi gia' nel repository). Nessuna chiamata di rete,
nessuna chiave, nessuna nuova richiesta a The Odds API.

Fonti (entrambe gia' nel repository):
  * linee e quote totals: ``audit/data/totals_probe/2026-10-10_1703/*.json`` (82 eventi,
    mercato ``totals``, regione eu);
  * terna 1X2: la COPIA VERSIONATA fissata per questa analisi (#44),
    ``audit/data/totals_probe/2026-10-10_1703/_live_odds_1x2_2026-10-10T090852Z.json`` —
    h2h, libro **Pinnacle**, snapshot 2026-10-10T09:08:52Z, identica al blob
    ``078beef:SoccerMath/database/live_odds.json`` della storia git (provenienza in
    ``audit/data/totals_probe/2026-10-10_1703/_live_odds_pin.json``). La sonda totals
    NON contiene l'1X2 (la richiesta era ``markets=totals``) e senza 1X2 il fit non
    esiste: e' l'unica fonte reale sugli stessi eventi gia' presente nel repository.
    Eventi agganciati per ``id``. Il disallineamento temporale (circa 8 ore) e' un
    limite dichiarato. Il file vivo ``SoccerMath/database/live_odds.json`` NON e'
    piu' ammissibile: lo riscrive il workflow live_odds.yml ogni giorno e
    dall'aggiornamento del 2026-10-11T14:56Z (gli eventi gia' giocati escono dal
    file) i confrontabili scendono da 42 a 35 — questo conteggio non e' piu'
    riproducibile leggendo il file vivo.

REGOLE DICHIARATE (identiche a §0.2 del referto; scritte prima dei numeri):

  P4.1 Eventi confrontabili: Pinnacle con una linea totals **diversa da 2,5** e
       **almeno 3 ALTRI bookmaker** (Pinnacle escluso) con la linea 2,5.
  P4.2 Due griglie per evento, con la STESSA terna 1X2 Pinnacle de-vigata:
       A = 1X2 + linea di Pinnacle (≠ 2,5), fittata col fit generalizzato;
       B = 1X2 + linea 2,5 degli altri libri (consenso).
       Confronto su P(Over 2,5), P(Gol), P(Over 1,5): differenza in valore assoluto.
  P4.3 Consenso 2,5 = **mediana** delle P(Over 2,5) de-vigate dei libri (Pinnacle
       escluso) che espongono la linea 2,5. De-vig **proporzionale** su tutte le
       fonti (1X2 e totals), per isolare l'effetto della linea e non del metodo.
  P4.4 REGOLA DI UTILIZZABILITA': il fit generalizzato e' utilizzabile se la
       differenza **mediana** su P(Over 2,5) tra A e B e' **<= 1,5 punti** e la
       **massima** e' **<= 4 punti**, con **almeno 10 eventi confrontabili**.
       Con meno di 10 eventi: «non decidibile su questo snapshot».
  P4.5 Conteggio finale: quanti dei 82 eventi — e quanti di quelli con kickoff entro
       7 giorni dalla chiamata — avrebbero una **linea utilizzabile**: almeno una
       linea totals di un tipo gestito dal fit (mezza, intera o a quarti) da almeno
       un bookmaker, PIU' la terna 1X2 Pinnacle per lo stesso evento. Solo conteggio.

Output: audit/results/punto4_fit_linea_generalizzata.md, audit/output/punto4_linee.json.
Uso: python audit/linee_totali_probe.py
"""

from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter, OrderedDict
from datetime import datetime, timezone

import numpy as np

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)

from griglia_core import (  # noqa: E402
    _GG, dc_matrix, devig_prop, fit_implicit_line, grid_line_prob,
)

PROBE_ROOT = os.path.join(_AUDIT_DIR, "data", "totals_probe")
PROBE_DIR = os.path.join(PROBE_ROOT, "2026-10-10_1703")
# Terna 1X2 FISSATA (#44) su una copia versionata accanto alla sonda: il file vivo
# SoccerMath/database/live_odds.json (riscritto ogni giorno dal workflow
# live_odds.yml) NON e' un default ammissibile per un'analisi su snapshot storico.
LIVE_ODDS_PINNED = os.path.join(PROBE_DIR, "_live_odds_1x2_2026-10-10T090852Z.json")
REPORT = os.path.join(_AUDIT_DIR, "results", "punto4_fit_linea_generalizzata.md")
JSON_OUT = os.path.join(_AUDIT_DIR, "output", "punto4_linee.json")

PINNACLE = "pinnacle"
MIN_LIBRI_25 = 3            # P4.1: almeno 3 ALTRI bookmaker con la 2,5
SOGLIA_GIORNI = 7.0         # P4.5: "entro 7 giorni"
MEDIANA_MAX = 1.5           # P4.4: punti percentuali
MASSIMO_MAX = 4.0
MIN_EVENTI = 10


def _maschere():
    from griglia_core import I, J
    tot = I + J
    return {"Over 2.5": (tot > 2.5).astype(float),
            "Gol": _GG.astype(float),
            "Over 1.5": (tot > 1.5).astype(float)}


MASCHERE = None  # inizializzata in main (serve I, J importati da griglia_core)


# ---------------------------------------------------------------------------
# Lettura
# ---------------------------------------------------------------------------
def _parse(ts):
    if not ts:
        return None
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def tipo_linea(point):
    """'mezza' / 'intera' / 'a quarti' / None (linea non gestita)."""
    try:
        x = float(point)
    except (TypeError, ValueError):
        return None
    n4 = x * 4.0
    if abs(n4 - round(n4)) > 1e-9 or round(n4) <= 0:
        return None
    r = int(round(n4)) % 4
    return "intera" if r == 0 else ("mezza" if r == 2 else "a quarti")


def load_probe():
    """Eventi della sonda: id -> {lega, giorni, lines{bk: (point, o_over, o_under)}, fetched}."""
    eventi = OrderedDict()
    for path in sorted(glob.glob(os.path.join(PROBE_DIR, "*.json"))):
        if os.path.basename(path).startswith("_"):
            continue
        with open(path, encoding="utf-8") as fh:
            env = json.load(fh)
        fetched = _parse(env.get("fetched_at_utc"))
        for ev in env.get("body") or []:
            lines = {}
            for bk in ev.get("bookmakers") or []:
                for mk in bk.get("markets") or []:
                    if mk.get("key") != "totals":
                        continue
                    prezzi = {}
                    for o in mk.get("outcomes") or []:
                        if o.get("name") in ("Over", "Under") and o.get("point") is not None:
                            prezzi[(o["name"], o["point"])] = o.get("price")
                    if not prezzi:
                        continue
                    # una linea per libro: la piu' bassa (come totals_probe_analysis.py)
                    point = sorted({p for (_n, p) in prezzi})[0]
                    lines[bk.get("key")] = (point, prezzi.get(("Over", point)),
                                            prezzi.get(("Under", point)))
            ct = _parse(ev.get("commence_time"))
            eventi[ev.get("id")] = {
                "id": ev.get("id"), "lega": env.get("lega"),
                "home": ev.get("home_team"), "away": ev.get("away_team"),
                "commence_time": ev.get("commence_time"),
                "giorni": (ct - fetched).total_seconds() / 86400.0 if (ct and fetched) else None,
                "lines": lines,
            }
    return eventi


def load_1x2(live_odds_path=LIVE_ODDS_PINNED):
    """id evento -> (o_home, o_draw, o_away) di Pinnacle dal file indicato.

    ``live_odds_path`` e' la copia versionata fissata per la sonda
    (``_live_odds_1x2_2026-10-10T090852Z.json``): ne e' parametro esplicito e
    NON ha un default che punti al file vivo, che il workflow riscrive ogni giorno.
    """
    with open(live_odds_path, encoding="utf-8") as fh:
        d = json.load(fh)
    out = {}
    generato = d.get("generato_il")
    for lega in (d.get("leghe") or {}).values():
        for ev in lega.get("eventi") or []:
            for libro in ev.get("libri") or []:
                if libro.get("key") != PINNACLE:
                    continue
                h2h = libro.get("h2h") or {}
                if all(isinstance(h2h.get(k), (int, float)) for k in ("home", "draw", "away")):
                    out[ev.get("id")] = (float(h2h["home"]), float(h2h["draw"]), float(h2h["away"]))
    return out, generato


# ---------------------------------------------------------------------------
# Fit e confronto
# ---------------------------------------------------------------------------
def prob_mercati(m):
    flat = m.ravel()
    return {nome: float(flat @ mask.ravel()) for nome, mask in MASCHERE.items()}


def fit_griglia(P3, target, line, side="over"):
    f = fit_implicit_line(P3[0], P3[1], P3[2], target, line=line, side=side, rho_free=True)
    m = dc_matrix(f["lam"], f["mu"], f["rho"])
    return m, f


def main(argv=None) -> int:
    global MASCHERE
    MASCHERE = _maschere()

    probe = load_probe()
    h2h, generato_1x2 = load_1x2(LIVE_ODDS_PINNED)
    ora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ---- conteggio delle linee utilizzabili (P4.5) ----
    conteggi = Counter()
    righe_evento = []
    for eid, ev in probe.items():
        tipi_presenti = {tipo_linea(p) for p, _o, _u in ev["lines"].values()}
        tipi_presenti.discard(None)
        n_25_altri = sum(1 for bk, (p, _o, _u) in ev["lines"].items()
                         if bk != PINNACLE and abs(float(p) - 2.5) < 1e-9)
        ha_1x2 = eid in h2h
        linee_ok = bool(tipi_presenti)
        utilizzabile = linee_ok and ha_1x2
        conteggi["eventi"] += 1
        conteggi["con_linea_totals_gestita"] += int(linee_ok)
        conteggi["con_1x2_pinnacle"] += int(ha_1x2)
        conteggi["utilizzabili"] += int(utilizzabile)
        if ev["giorni"] is not None and ev["giorni"] <= SOGLIA_GIORNI:
            conteggi["entro_7_eventi"] += 1
            conteggi["entro_7_utilizzabili"] += int(utilizzabile)
        righe_evento.append({"id": eid, "lega": ev["lega"], "home": ev["home"],
                             "away": ev["away"], "giorni": ev["giorni"],
                             "n_libri_totals": len(ev["lines"]),
                             "linea_pinnacle": ev["lines"].get(PINNACLE, (None, None, None))[0],
                             "n_25_altri": n_25_altri, "ha_1x2": ha_1x2,
                             "utilizzabile": utilizzabile})

    # ---- eventi confrontabili (P4.1) e confronto A vs B (P4.2) ----
    confronti = []
    for eid, ev in probe.items():
        if eid not in h2h:
            continue
        pin = ev["lines"].get(PINNACLE)
        if pin is None or pin[1] is None or pin[2] is None:
            continue
        linea_pin = pin[0]
        if abs(float(linea_pin) - 2.5) < 1e-9:
            continue                                   # P4.1: Pinnacle deve avere un'altra linea
        libri_25 = [(bk, p, o, u) for bk, (p, o, u) in ev["lines"].items()
                    if bk != PINNACLE and abs(float(p) - 2.5) < 1e-9 and o and u]
        if len(libri_25) < MIN_LIBRI_25:
            continue
        P3 = devig_prop(list(h2h[eid]))
        if P3 is None:
            continue
        # --- griglia A: linea di Pinnacle
        p_pin = devig_prop([pin[1], pin[2]])
        if p_pin is None:
            continue
        mA, fA = fit_griglia(P3, p_pin[0], float(linea_pin), "over")
        # --- griglia B: la 2,5 degli altri libri (mediana delle P(Over 2,5) de-vigate)
        p25 = []
        for _bk, _p, o, u in libri_25:
            q = devig_prop([o, u])
            if q is not None:
                p25.append(q[0])
        if not p25:
            continue
        target_b = float(np.median(p25))
        mB, fB = fit_griglia(P3, target_b, 2.5, "over")
        pa, pb = prob_mercati(mA), prob_mercati(mB)
        confronti.append({
            "id": eid, "lega": ev["lega"], "home": ev["home"], "away": ev["away"],
            "giorni": ev["giorni"], "linea_pinnacle": float(linea_pin),
            "tipo_linea": tipo_linea(linea_pin), "n_libri_25": len(libri_25),
            "p_over_pin": float(p_pin[0]), "p_over_25_mediana": target_b,
            "lam_A": fA["lam"], "mu_A": fA["mu"], "rho_A": fA["rho"],
            "residuo_A": fA["max_abs_resid"],
            "lam_B": fB["lam"], "mu_B": fB["mu"], "rho_B": fB["rho"],
            "residuo_B": fB["max_abs_resid"],
            **{f"A_{k}": v for k, v in pa.items()},
            **{f"B_{k}": v for k, v in pb.items()},
            **{f"d_{k}": abs(pa[k] - pb[k]) for k in pa},
        })

    # ---- regola P4.4 ----
    n_conf = len(confronti)
    d25 = [c["d_Over 2.5"] for c in confronti]
    dgg = [c["d_Gol"] for c in confronti]
    d15 = [c["d_Over 1.5"] for c in confronti]

    def mediana(v):
        return float(np.median(v)) if v else None

    def massimo(v):
        return float(np.max(v)) if v else None

    if n_conf < MIN_EVENTI:
        esito = "non decidibile su questo snapshot"
        motivazione = f"solo {n_conf} eventi confrontabili, sotto i {MIN_EVENTI} richiesti"
    else:
        med25, max25 = mediana(d25), massimo(d25)
        ok = (med25 * 100 <= MEDIANA_MAX) and (max25 * 100 <= MASSIMO_MAX)
        esito = "UTILIZZABILE" if ok else "NON utilizzabile"
        motivazione = (f"mediana {med25 * 100:.2f} pt (soglia ≤ {MEDIANA_MAX:g}) e massimo "
                       f"{max25 * 100:.2f} pt (soglia ≤ {MASSIMO_MAX:g}) su {n_conf} eventi")

    T = []
    A = T.append
    A("## 4. Punto 4 — fit della griglia su una linea totals qualunque\n")
    A(f"Generato da `audit/linee_totali_probe.py` il {ora} · linee e quote totals dalla sonda in "
      f"`audit/data/totals_probe/` (2026-10-10T17:03Z) · terna 1X2 Pinnacle dalla copia versionata "
      f"`audit/data/totals_probe/2026-10-10_1703/_live_odds_1x2_2026-10-10T090852Z.json` "
      f"({generato_1x2}; = blob `078beef` del file vivo, fissato dopo che il workflow "
      f"live_odds.yml del 2026-10-11T14:56Z lo ha riscritto) · nessuna nuova chiamata a The "
      "Odds API, nessuna chiave, nessuna modifica a `SoccerMath/`.\n")
    A("### 4.1 Estensione del fit (audit/griglia_core.py)\n")
    A("Il terzo vincolo del fit non è più la sola P(Over 2,5) ma la **probabilità giusta** di una "
      "linea qualsiasi, calcolata con le regole di pagamento del mercato:\n")
    A("| tipo di linea | regola | probabilità giusta usata nel fit |")
    A("|---|---|---|")
    A("| mezza (1,5 / 2,5 / 3,5) | vinta sopra la linea, persa sotto | P(gol totali > linea) |")
    A("| intera (2 / 3) | rimborso se i gol totali sono uguali alla linea | P(sopra) / (1 − P(uguale)) |")
    A("| a quarti (2,25 / 2,75) | mezza puntata su ciascuna delle due linee adiacenti | quota equa "
      "da EV nullo: p = W / (W + Lp) |")
    A("")
    A("`W` = frazione di puntata che vince, `Lp` = frazione che perde, il resto è rimborsato. Con "
      "questa definizione p(sopra) + p(sotto) = 1 per ogni tipo di linea, quindi il de-vig a due "
      "vie è applicabile senza correzioni. Test di andata e ritorno su parametri noti per ogni "
      "tipo di linea: `audit/test_griglia_core_linee.py` (96 test con "
      "`audit/test_griglia_core.py` e `audit/test_griglia_varianti.py`), residuo richiesto "
      "< 1e-9.\n")

    A("### 4.2 Verifica su dati reali\n")
    A(f"Eventi della sonda: **{len(probe)}**. Eventi con la terna 1X2 Pinnacle disponibile: "
      f"**{conteggi['con_1x2_pinnacle']}** (aggancio per `id`). Eventi **confrontabili** "
      f"(Pinnacle con linea ≠ 2,5 e almeno {MIN_LIBRI_25} altri libri con la 2,5): "
      f"**{n_conf}**.\n")
    if confronti:
        A(md_tabella_confronti(confronti))
        A("")
        A("Differenze fra la griglia A (linea Pinnacle, fit generalizzato) e la griglia B (linea "
          "2,5 degli altri libri), in valore assoluto:\n")
        A(md_table(["mercato", "n", "mediana", "massimo"],
                   [[k, n_conf, f"{mediana(v) * 100:.2f} pt" if v else "n/d",
                     f"{massimo(v) * 100:.2f} pt" if v else "n/d"]
                    for k, v in (("P(Over 2,5)", d25), ("P(Gol)", dgg), ("P(Over 1,5)", d15))]))
        A("")
    else:
        A("Nessun evento confrontabile: nessuna differenza calcolabile.\n")
    A(f"**Esito della regola dichiarata (P4.4): {esito}.** {motivazione.capitalize()}.\n")
    A("")

    A("### 4.3 Conteggio: quanti eventi avrebbero una linea utilizzabile\n")
    A("Linea utilizzabile = almeno una linea totals di un tipo gestito dal fit (mezza, intera o a "
      "quarti) da almeno un bookmaker, **e** la terna 1X2 Pinnacle per lo stesso evento (senza "
      "1X2 il fit non esiste). Solo conteggio: l'ingresso di totals in produzione si decide su "
      "una sonda nuova.\n")
    A(md_table(["misura", "tutti gli eventi", "entro 7 giorni"],
               [["eventi della sonda", conteggi["eventi"], conteggi["entro_7_eventi"]],
                ["con almeno una linea totals di tipo gestito",
                 conteggi["con_linea_totals_gestita"], "—"],
                ["con la terna 1X2 Pinnacle", conteggi["con_1x2_pinnacle"], "—"],
                ["**con una linea UTILIZZABILE (entrambi)**",
                 f"**{conteggi['utilizzabili']}**", f"**{conteggi['entro_7_utilizzabili']}**"]]))
    A("")
    tipi_pin = Counter(r["linea_pinnacle"] for r in righe_evento if r["linea_pinnacle"] is not None)
    A("Linee esposte da Pinnacle sugli 82 eventi (valori grezzi): "
      + ", ".join(f"**{k}** × {v}" for k, v in sorted(tipi_pin.items(), key=lambda kv: float(kv[0])))
      + f"; Pinnacle assente: {sum(1 for r in righe_evento if r['linea_pinnacle'] is None)}.\n")
    A("")

    A("### 4.4 Limiti\n")
    A("- La terna 1X2 viene da uno snapshot **8 ore prima** della sonda totals "
      f"(`live_odds.json` {generato_1x2} contro 2026-10-10T17:03Z): le quote 1X2 nel frattempo "
      "hanno potuto muoversi. La differenza misurata fra A e B include questo disallineamento, "
      "che agisce però nella stessa direzione sulle due griglie (la terna è identica).")
    A(f"- Snapshot unico: {n_conf} eventi confrontabili su {len(probe)}. Con meno di {MIN_EVENTI} "
      "eventi la regola dichiara «non decidibile», che è l'esito atteso su una sola giornata tipo.")
    A("- Il consenso 2,5 e' la mediana delle P(Over 2,5) de-vigate dei libri: libri con margini "
      "molto diversi pesano tutti allo stesso modo.")
    A("- De-vig proporzionale su tutte le fonti (P4.3): la scelta del de-vig non è oggetto di "
      "questo punto (lo è del punto 1).")
    A("- Nessuna conseguenza sulla produzione: totals non entra in produzione con questo audit e "
      "la regola dell'85% della PR #59 resta non superata.\n")

    testo = "\n".join(T) + "\n"
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write(testo)
    os.makedirs(os.path.dirname(JSON_OUT), exist_ok=True)
    with open(JSON_OUT, "w", encoding="utf-8") as fh:
        json.dump({"generato": ora, "n_eventi_sonda": len(probe), "conteggi": dict(conteggi),
                   "n_confrontabili": n_conf, "esito": esito, "motivazione": motivazione,
                   "differenze": {"Over 2.5": {"mediana": mediana(d25), "massimo": massimo(d25)},
                                  "Gol": {"mediana": mediana(dgg), "massimo": massimo(dgg)},
                                  "Over 1.5": {"mediana": mediana(d15), "massimo": massimo(d15)}},
                   "confronti": confronti, "eventi": righe_evento}, fh,
                  ensure_ascii=False, indent=1)
    print(testo)
    print(f"[punto4] referto: {REPORT} · json: {JSON_OUT}", file=sys.stderr)
    return 0


def md_table(headers, rows):
    head = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join(["---"] * len(headers)) + "|"
    return "\n".join([head, sep] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def md_tabella_confronti(confronti):
    rows = []
    for c in sorted(confronti, key=lambda x: -(x["d_Over 2.5"])):
        rows.append([f"{c['home']} – {c['away']}", c["lega"], f"{c['linea_pinnacle']:g}",
                     c["tipo_linea"], c["n_libri_25"],
                     f"{c['A_Over 2.5'] * 100:.2f} / {c['B_Over 2.5'] * 100:.2f}",
                     f"{c['d_Over 2.5'] * 100:.2f}", f"{c['d_Gol'] * 100:.2f}",
                     f"{c['d_Over 1.5'] * 100:.2f}",
                     f"{c['residuo_A']:.0e}"])
    return md_table(["partita", "lega", "linea Pinnacle", "tipo", "libri a 2,5",
                     "P(Over 2,5) A / B (%)", "Δ Over 2,5 (pt)", "Δ Gol (pt)",
                     "Δ Over 1,5 (pt)", "residuo A"], rows)


if __name__ == "__main__":
    raise SystemExit(main())
