#!/usr/bin/env python3
"""Gate shadow: il veto |P-E| < 0.25 come penalita' continua, in SOLA LETTURA.

Modalita' ombra (referto ``audit/margini_migliorabili_topmix.md`` §9 punto 4,
§11quater): il gate non scarta piu' la partita ma scala la confidence col
fattore continuo ``0.25/(0.25 + d)`` (``prediction_registry.
gate_shadow_confidence``); l'ammissione ombra e' il solo confronto
``conf_shadow >= min_conf``.

Questo harness risponde a: sulle 3 422 candidate storiche gia' committate,
cosa avrebbe fatto la variante ombra?

* sulle righe AMMESSE dal selettore reale: quante sarebbero comunque ammesse
  dall'ombra (``conf_shadow`` sopra soglia, "robuste") e quante no ("fragili"),
  con hit/Brier per gruppo. E' il confronto che il campo shadow del registro
  rende misurabile in prospettiva sulle righe giocate;
* sulle righe che il gate blocca (194, le uniche dove la differenza conta):
  la ``conf_shadow`` che verrebbe loro assegnata. NOTA algebrica: con
  ``d >= 0.25`` il fattore e' <= 1/2, quindi ``conf_shadow <= conf/2 <= 0.5 <
  0.55``: la variante ombra NON riammette mai una riga bloccata dal veto. Il
  suo contributo e' il valore continuo ``conf_shadow`` (e l'esito reale,
  valutabile a posteriori), non una riammissione.

Fonte dei dati (nessun ricalcolo del motore): ``audit/results/
topmix_selector_replay_rows.csv`` — stessa fonte di ``audit/topmix_margins.py``.
Consistenza: i conteggi di riga (candidate/ammesse/motivi di scarto) e le
headline delle ammesse devono coincidere con ``audit/results/topmix_margins.json``
committato (stesso controllo di §0 del referto, per la parte che serve qui).

Non importa ``app.py``, non tocca il registro, non chiama API. Unica scrittura:
i report ``audit/results/topmix_shadow_gate.{md,json}``.

NOTA sul metodo: 2024/25 e 2025/26 sono validation storica gia' esaminata
(protocollo §3). Queste tabelle NON tarano nulla: misurano la direzione di un
cambiamento predittivo che va confermato in cieco sul 2026/27 — che e' il
motivo per cui i campi shadow vengono persistiti nel registro live.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
RESULTS_DIR = os.path.join(_AUDIT_DIR, "results")
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from topmix_margins import load_rows  # noqa: E402  (riusa il parser del replay)
import prediction_registry as R       # noqa: E402  (formula ombra: unica fonte)

DEFAULT_ROWS = os.path.join(RESULTS_DIR, "topmix_selector_replay_rows.csv")
DEFAULT_MARGINS = os.path.join(RESULTS_DIR, "topmix_margins.json")
DEFAULT_OUT_MD = os.path.join(RESULTS_DIR, "topmix_shadow_gate.md")
DEFAULT_OUT_JSON = os.path.join(RESULTS_DIR, "topmix_shadow_gate.json")

TOL = 1e-6


def _brier(rows: list) -> float:
    coppie = [(r["A_conf"], r["A_hit"]) for r in rows]
    return statistics.mean((p - y) ** 2 for p, y in coppie)


def _gruppo(rows: list) -> dict:
    n = len(rows)
    hit = sum(r["A_hit"] for r in rows)
    return {
        "n": n,
        "mean_prob": statistics.mean(r["A_conf"] for r in rows) if n else None,
        "mean_conf_shadow": statistics.mean(r["conf_shadow"] for r in rows) if n else None,
        "mean_disagree": statistics.mean(r["A_disagree"] for r in rows) if n else None,
        "hit_rate": hit / n if n else None,
        "brier": _brier(rows) if n else None,
    }


def analizza(rows_path: str, margins_path: str) -> dict:
    rows = load_rows(rows_path)
    margini = json.load(open(margins_path, encoding="utf-8"))["payload"]
    cons = margini["consistency"]

    # --- split reale (stesse categorie di margini §2) + variante ombra ---
    ammesse, gate_solo = [], []
    for r in rows:
        conf, d, mc = r["A_conf"], r["A_disagree"], r["A_min_conf"]
        if conf is None or d is None or mc is None:
            continue
        r["conf_shadow"] = R.gate_shadow_confidence(conf, d)
        r["ammessa_shadow"] = bool(r["conf_shadow"] is not None and r["conf_shadow"] >= mc)
        r["conf_off"] = R.gate_off_confidence(conf, d)
        r["ammessa_off"] = bool(r["conf_off"] is not None and r["conf_off"] >= mc)
        if r["A_admitted"]:
            ammesse.append(r)
        elif conf >= mc and d >= 0.25:
            gate_solo.append(r)

    robuste = [r for r in ammesse if r["ammessa_shadow"]]
    fragili = [r for r in ammesse if not r["ammessa_shadow"]]
    gate_solo_ammesse = [r for r in gate_solo if r["ammessa_shadow"]]
    # Secondo segnale (gate assente): per costruzione le 194 hanno conf >= min_conf,
    # quindi tutte rientrano. E' il controllo di coerenza col numero di §2.
    gate_solo_ammesse_off = [r for r in gate_solo if r["ammessa_off"]]

    # --- consistenza con l'artefatto committato (margini) ---
    atteso = {c["nome"]: c["atteso"] for c in cons}
    attesi_rejection = margini["rejection"]
    attesi_ammesse = margini["admitted"]["overall"]
    controlli = [
        ("candidate", float(len(rows)), atteso.get("candidate"), "conteggio"),
        ("A ammesse", float(len(ammesse)), atteso.get("A ammesse"), "conteggio"),
        ("scartate: solo soglia", float(attesi_rejection["reasons"]["soglia"]),
         attesi_rejection["reasons"]["soglia"], "conteggio (margini.json)"),
        ("scartate: solo disaccordo (gate)", float(len(gate_solo)),
         attesi_rejection["reasons"]["disaccordo"], "conteggio (margini.json)"),
        ("ammesse: hit rate", _gruppo(ammesse)["hit_rate"], attesi_ammesse["hit_rate"],
         "tol 1e-6 (margini.json)"),
        ("ammesse: brier", _gruppo(ammesse)["brier"], attesi_ammesse["brier"],
         "tol 1e-6 (margini.json)"),
        ("gate_off riammette le 194", float(len(gate_solo_ammesse_off)),
         attesi_rejection["reasons"]["disaccordo"],
         "per costruzione: A_conf >= min_conf (margini.json)"),
    ]
    consistency = []
    for nome, ricalcolato, att, nota in controlli:
        ok = att is not None and abs(float(ricalcolato) - float(att)) <= TOL
        consistency.append({"nome": nome, "ricalcolato": ricalcolato,
                            "atteso": att, "ok": ok, "nota": nota})

    payload = {
        "n_candidates": len(rows),
        "consistency": consistency,
        "shadow_admitted": {
            "overall": _gruppo(ammesse),
            "robuste": _gruppo(robuste),
            "fragili": _gruppo(fragili),
            "n_robuste": len(robuste),
            "n_fragili": len(fragili),
            "quote": {"robuste": len(robuste) / len(ammesse) if ammesse else None,
                      "fragili": len(fragili) / len(ammesse) if ammesse else None},
        },
        "gate_only": {
            **_gruppo(gate_solo),
            "n": len(gate_solo),
            "max_conf_shadow": max((r["conf_shadow"] for r in gate_solo), default=None),
            "n_ammesse_shadow": len(gate_solo_ammesse),
            # Per riferimento: hit/Brier "se giocate" sono gia' in margini §2
            # (gate_only). Qui interessa solo la scala conf_shadow.
            "n_ammesse_off": len(gate_solo_ammesse_off),
            "mean_conf_off": (statistics.mean(r["conf_off"] for r in gate_solo)
                               if gate_solo else None),
        },
        "nota": (
            "Nessuna riga bloccata dal gate puo' essere riammessa dalla "
            "variante ombra: d >= 0.25 implica fattore <= 1/2, quindi "
            "conf_shadow <= conf/2 <= 0.5 < 0.55 (soglia 1X2)."
        ),
        "nota_gate_off": (
            "Il secondo segnale (gate assente) riammette per costruzione tutte "
            "le 194: hanno A_conf >= min_conf e il veto e' l'unico motivo di "
            "scarto. Zero parametri liberi; conf_off == A_conf."
        ),
    }
    return {"meta": {"n_rows": len(rows), "rows_file": os.path.basename(rows_path),
                     "shadow_formula": "conf * 0.25 / (0.25 + |P-E|)",
                     "sorgente": "prediction_registry.gate_shadow_confidence",
                     "gate_off_formula": "conf (identita', nessuno sconto)",
                     "sorgente_gate_off": "prediction_registry.gate_off_confidence"},
            "payload": payload}


def _fmt_pct(x, nd=1):
    return "n/d" if x is None else f"{x * 100:.{nd}f}%"


def render_md(res: dict) -> str:
    p = res["payload"]
    ad = p["shadow_admitted"]
    g = p["gate_only"]
    righe = []
    righe.append("# Gate shadow: il veto |P-E| < 0.25 come penalita' continua\n")
    righe.append("**Definizione (referto `margini_migliorabili_topmix.md` §11quater):** "
                 "`conf_shadow = conf * 0.25 / (0.25 + d)`, ammissione ombra = "
                 "`conf_shadow >= min_conf`. Formula implementata in "
                 "`prediction_registry.gate_shadow_confidence`.\n")
    righe.append(f"Fonte: `{res['meta']['rows_file']}` ({res['meta']['n_rows']} candidate). "
                 "Sola lettura: nessuna riga del registro toccata.\n")
    ok = all(c["ok"] for c in p["consistency"])
    righe.append(f"**Consistenza con l'artefatto committato: {'OK' if ok else 'FALLITA'}**\n")
    if not ok:
        for c in p["consistency"]:
            if not c["ok"]:
                righe.append(f"- {c['nome']}: ricalcolato {c['ricalcolato']} vs atteso {c['atteso']}")
    righe.append("| grandezza | valore |")
    righe.append("|---|---|")
    righe.append(f"| righe ammesse dal selettore reale | {ad['overall']['n']} |")
    righe.append(f"| ...che l'ombra ammetterebbe ancora (**robuste**) | "
                 f"{ad['n_robuste']} ({_fmt_pct(ad['quote']['robuste'], 0)}) |")
    righe.append(f"| ...che l'ombra NON ammetterebbe (**fragili**) | "
                 f"{ad['n_fragili']} ({_fmt_pct(ad['quote']['fragili'], 0)}) |")
    righe.append(f"| righe bloccate dal gate (d >= 0.25) | {g['n']} |")
    righe.append(f"| ...riammesse dall'ombra | {g['n_ammesse_shadow']} |")
    righe.append(f"| ...riammesse dal secondo segnale (gate assente) | {g['n_ammesse_off']} |")
    righe.append("")
    righe.append("### Ammesse: robuste vs fragili\n")
    righe.append("| gruppo | n | prob media | conf_shadow media | d medio | hit | Brier |")
    righe.append("|---|---:|---:|---:|---:|---:|---:|")
    for nome, gr in (("tutte le ammesse", ad["overall"]), ("robuste", ad["robuste"]),
                     ("fragili", ad["fragili"])):
        d = f"{gr['mean_disagree']:.3f}" if gr["mean_disagree"] is not None else "n/d"
        b = f"{gr['brier']:.4f}" if gr["brier"] is not None else "n/d"
        righe.append(f"| {nome} | {gr['n']} | {_fmt_pct(gr['mean_prob'])} | "
                     f"{_fmt_pct(gr['mean_conf_shadow'])} | {d} | "
                     f"{_fmt_pct(gr['hit_rate'])} | {b} |")
    righe.append("")
    righe.append("### Bloccate dal gate: la scala conf_shadow (nessuna riammissione)\n")
    righe.append("| n | prob media | d medio | conf_shadow media | max conf_shadow | "
                 "riammesse dall'ombra |")
    righe.append("|---|---:|---:|---:|---:|---:|")
    righe.append(f"| {g['n']} | {_fmt_pct(g['mean_prob'])} | {g['mean_disagree']:.3f} | "
                 f"{_fmt_pct(g['mean_conf_shadow'])} | {_fmt_pct(g['max_conf_shadow'])} | "
                 f"{g['n_ammesse_shadow']} |")
    righe.append("")
    righe.append(f"Nota: {p['nota']}\n")
    righe.append("Lettura: su validation storica gia' esaminata robuste e fragili "
                 "hanno hit/Brier vicini (le tabelle NON tarano nulla e non provano "
                 "nessun margine: il confronto va fatto in cieco sul 2026/27). "
                 "Il valore operativo e' la misura APPAIATA che i campi "
                 "`gate_shadow_confidence`/`gate_shadow_ammessa` del registro "
                 "renderanno possibile sulle righe giocate: Brier della "
                 "conf_shadow vs Brier della conf reale, per gruppo. Le 194 "
                 "bloccate restano misurabili solo ex-post/harness: la "
                 "produzione non le mostra ne' le gioca (referto §11quater).\n")
    return "\n".join(righe)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rows", default=DEFAULT_ROWS)
    ap.add_argument("--margins", default=DEFAULT_MARGINS)
    ap.add_argument("--out-md", default=DEFAULT_OUT_MD)
    ap.add_argument("--out-json", default=DEFAULT_OUT_JSON)
    args = ap.parse_args(argv)
    res = analizza(args.rows, args.margins)
    if not all(c["ok"] for c in res["payload"]["consistency"]):
        print("CONSISTENZA FALLITA: l'input non coincide con margini.json", file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(args.out_md), exist_ok=True)
    with open(args.out_md, "w", encoding="utf-8") as f:
        f.write(render_md(res))
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("ok:", args.out_md, "|", args.out_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
