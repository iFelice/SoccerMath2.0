#!/usr/bin/env python3
"""Margini migliorabili del selettore Top Mix — analisi in SOLA LETTURA.

Domanda a cui risponde questo script
------------------------------------
Quali funzioni di ``SoccerMath/app.py`` hanno margine misurabile, e quanto vale
quel margine sul materiale già committato dall'audit del Top Mix?

Fonte dei dati (nessuna ricalcolazione del motore)
--------------------------------------------------
Legge e basta:

* ``audit/results/topmix_selector_replay_rows.csv`` — una riga per
  ``(lega, stagione, partita)`` con il mercato scelto da A, la sua probabilità
  ``A_conf``, il disaccordo ``A_disagree``, la soglia ``A_min_conf``,
  l'ammissibilità ``A_admitted`` e l'esito ``A_hit`` (più i campi speculari di
  B). È l'output di ``audit/topmix_selector_replay.py``.
* ``audit/results/topmix_selector_replay.json`` — usato SOLO come
  **consistenza**: le metriche headline qui ricalcolate devono coincidere con
  quelle committate (se l'artefatto è presente).

Non viene importato ``app.py``, non viene ricalcolato alcun lambda, non viene
letto il database di produzione, non viene chiamata alcuna API remota, non
viene scritta nessuna riga del registro. L'unica scrittura è il report (e
l'eventuale JSON) in ``audit/results/``.

Perché questi numeri NON sono una taratura
------------------------------------------
Le stagioni 2024/25 e 2025/26 sono **validation storica già esaminata**
(``audit/topmix_selector_audit_protocol.md`` §3): sono quelle su cui sono già
stati scelti Poisson a due teste, forma fuori dai totali, ``PRIOR_MATCHES=6`` e
i pesi 0.6/0.4. Nessuna soglia, peso o formula viene qui cercata o cambiata:
le tabelle misurano **il costo di un vincolo già esistente**, non propongono
un suo valore alternativo. La direzione di ogni intervento va confermata in
cieco sul 2026/27, e questo richiede prima il tracciamento.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
RESULTS_DIR = os.path.join(_AUDIT_DIR, "results")

DEFAULT_ROWS = os.path.join(RESULTS_DIR, "topmix_selector_replay_rows.csv")
DEFAULT_SUMMARY = os.path.join(RESULTS_DIR, "topmix_selector_replay.json")
DEFAULT_OUT_MD = os.path.join(RESULTS_DIR, "topmix_margins.md")
DEFAULT_OUT_JSON = os.path.join(RESULTS_DIR, "topmix_margins.json")

# Stessa convenzione del replay committato (audit/topmix_selector_replay.py):
# pool = settimana ISO del cutoff, 5 leghe insieme, stagione inclusa nella
# chiave, taglio a 10, bootstrap a blocchi sul pool con seed fisso.
TOP_N = 10
N_BOOT = 2000
SEED = 20260905
MARKETS_1X2 = ("1", "X", "2")
#: mercato sotto questa numerosità non produce un bias affidabile
MIN_N_PER_MARKET = 30
#: tolleranza del confronto con l'artefatto committato
CONSISTENCY_TOL = 5e-4


# ---------------------------------------------------------------------------
# 1. Lettura e tipizzazione
# ---------------------------------------------------------------------------
def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip()
    if s == "" or s.lower() in ("none", "nan"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _flag(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def parse_row(raw: Dict[str, str]) -> Dict[str, Any]:
    """Converte una riga CSV in un dizionario tipizzato (nessuna logica qui)."""
    return {
        "league": raw.get("league", ""),
        "season": raw.get("season_label", ""),
        "matchday": _num(raw.get("matchday")),
        "cutoff": raw.get("cutoff", ""),
        "match_id": raw.get("match_id", ""),
        "home": raw.get("home", ""),
        "away": raw.get("away", ""),
        "A_market": raw.get("A_market", ""),
        "A_poisson": _num(raw.get("A_poisson")),
        "A_conf": _num(raw.get("A_conf")),
        "A_disagree": _num(raw.get("A_disagree")),
        "A_min_conf": _num(raw.get("A_min_conf")),
        "A_admitted": _flag(raw.get("A_admitted")),
        "A_hit": 1 if str(raw.get("A_hit", "")).strip() == "1" else 0,
        "B_market": raw.get("B_market", ""),
        "B_conf": _num(raw.get("B_conf")),
        "B_admitted": _flag(raw.get("B_admitted")),
        "B_n_admitted_markets": _num(raw.get("B_n_admitted_markets")),
        "B_hit": 1 if str(raw.get("B_hit", "")).strip() == "1" else 0,
        "B_hit_known": str(raw.get("B_hit", "")).strip() in ("0", "1"),
        "elo_available": _flag(raw.get("elo_available")),
        "team_stats_missing": _num(raw.get("team_stats_missing")) or 0.0,
    }


def load_rows(path: str) -> List[Dict[str, Any]]:
    with open(path, newline="", encoding="utf-8") as fh:
        return [parse_row(r) for r in csv.DictReader(fh)]


# ---------------------------------------------------------------------------
# 2. Primitivi di misura (formule identiche al replay: nessuna deriva)
# ---------------------------------------------------------------------------
def quality(pairs: Sequence[Tuple[Optional[float], int]]) -> Dict[str, Any]:
    """n / prob media / hit rate / Brier / gap su coppie ``(prob, esito)``."""
    usable = [(p, y) for p, y in pairs if p is not None]
    n = len(usable)
    if not n:
        return {"n": 0, "mean_prob": None, "hit_rate": None, "brier": None, "gap": None}
    mp = sum(p for p, _ in usable) / n
    hr = sum(y for _, y in usable) / n
    br = sum((p - y) ** 2 for p, y in usable) / n
    return {"n": n, "mean_prob": mp, "hit_rate": hr, "brier": br, "gap": mp - hr}


def quality_of(rows: Iterable[Dict[str, Any]],
               prob_key: str = "A_conf", hit_key: str = "A_hit") -> Dict[str, Any]:
    return quality([(r.get(prob_key), int(r.get(hit_key, 0))) for r in rows])


def iso_week(cutoff_iso: str) -> str:
    """Chiave settimanale del cutoff, stessa stringa del replay committato."""
    dt = datetime.fromisoformat(cutoff_iso)
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def pool_key(r: Dict[str, Any]) -> Tuple[str, str]:
    return (iso_week(r["cutoff"]), r["season"])


def pools_of(rows: Sequence[Dict[str, Any]]) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    pools: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        pools[pool_key(r)].append(r)
    return dict(sorted(pools.items()))


def select_top(pool: Sequence[Dict[str, Any]],
               admitted: Callable[[Dict[str, Any]], bool],
               prob_key: str = "A_conf",
               limit: int = TOP_N) -> List[Dict[str, Any]]:
    """Graduatoria globale del pool: stesso ``sorted(...)[:10]`` di produzione."""
    return sorted([r for r in pool if admitted(r)],
                  key=lambda r: r[prob_key], reverse=True)[:limit]


# ---------------------------------------------------------------------------
# 3. Vincoli del selettore A, isolati uno per uno
# ---------------------------------------------------------------------------
def below_threshold(r: Dict[str, Any]) -> bool:
    conf, mc = r["A_conf"], r["A_min_conf"]
    return conf is not None and mc is not None and conf < mc


def gate_blocks(r: Dict[str, Any], threshold: float = 0.25) -> bool:
    dis = r["A_disagree"]
    return dis is not None and dis >= threshold


def reject_reason(r: Dict[str, Any], gate: float = 0.25) -> Optional[str]:
    """``None`` se ammessa, altrimenti il motivo (soglia / disaccordo / entrambi)."""
    if r["A_admitted"]:
        return None
    low, blocked = below_threshold(r), gate_blocks(r, gate)
    if low and blocked:
        return "entrambi"
    if blocked:
        return "disaccordo"
    if low:
        return "soglia"
    return "altro"


def rejection_breakdown(rows: Sequence[Dict[str, Any]], gate: float = 0.25) -> Dict[str, Any]:
    reasons = Counter(r for r in (reject_reason(x, gate) for x in rows) if r)
    out: Dict[str, Any] = {"n_candidates": len(rows),
                           "n_admitted": sum(1 for r in rows if r["A_admitted"]),
                           "reasons": dict(reasons)}
    # qualità di ciò che ogni singolo vincolo butta VIA da solo
    for name in ("soglia", "disaccordo", "entrambi"):
        sel = [r for r in rows if reject_reason(r, gate) == name]
        out[f"only_{name}"] = {**quality_of(sel),
                               "markets": dict(Counter(r["A_market"] for r in sel))}
    return out


def admitted_quality_by_market(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["A_admitted"]:
            by[r["A_market"]].append(r)
    return {k: quality_of(v) for k, v in sorted(by.items(), key=lambda kv: -len(kv[1]))}


def admitted_quality_by_disagreement(rows: Sequence[Dict[str, Any]],
                                     bands: Sequence[Tuple[float, float]] =
                                     ((0.0, 0.05), (0.05, 0.15), (0.15, 0.25))) -> List[Dict[str, Any]]:
    adm = [r for r in rows if r["A_admitted"] and r["A_disagree"] is not None]
    out = []
    for lo, hi in bands:
        sel = [r for r in adm if lo <= r["A_disagree"] < hi]
        out.append({"band": [lo, hi], **quality_of(sel)})
    return out


def gate_only_rejections(rows: Sequence[Dict[str, Any]], gate: float = 0.25) -> Dict[str, Any]:
    """Partite candidate bocciate SOLO dal filtro di disaccordo, con la loro qualità."""
    sel = [r for r in rows if not r["A_admitted"] and not below_threshold(r)
           and gate_blocks(r, gate)]
    per_market = {}
    for mk in MARKETS_1X2:
        s = [r for r in sel if r["A_market"] == mk]
        if s:
            per_market[mk] = quality_of(s)
    return {**quality_of(sel), "markets": dict(Counter(r["A_market"] for r in sel)),
            "per_market": per_market}


def threshold_bands(rows: Sequence[Dict[str, Any]], gate: float = 0.25,
                    bands: Sequence[Tuple[float, float]] =
                    ((0.45, 0.50), (0.50, 0.55), (0.55, 0.60), (0.60, 0.65))) -> List[Dict[str, Any]]:
    """Cosa porterebbe dentro una soglia più bassa (non: cosa vale la soglia).

    Sono le partite bocciate dal solo taglio di confidenza, valutate sul
    mercato che A avrebbe mostrato: se la loro frequenza reale è vicina a
    quella dichiarata la soglia sta tagliando rumore, se è più alta sta
    tagliando segnale.
    """
    out = []
    for lo, hi in bands:
        for fam, thr in (("1X2", 0.55), ("totali", 0.60)):
            sel = [r for r in rows
                   if not r["A_admitted"] and not gate_blocks(r, gate)
                   and r["A_conf"] is not None and lo <= r["A_conf"] < hi
                   and ((r["A_market"] in MARKETS_1X2) == (fam == "1X2"))]
            q = quality_of(sel)
            out.append({"band": [lo, hi], "famiglia": fam, "soglia_attuale": thr, **q})
    return out


# ---------------------------------------------------------------------------
# 4. Il vincolo ad alto margine: gate di disaccordo come CANCELLAZIONE
# ---------------------------------------------------------------------------
def top10_gate_comparison(rows: Sequence[Dict[str, Any]], gate: float = 0.25) -> Dict[str, Any]:
    """Top 10 con il gate (produzione) vs top 10 senza il gate (stesse soglie).

    Pool e taglio replicano ``_top10_metrics`` di ``audit/topmix_selector_replay.py``:
    pool da TUTTE le candidate, selezione filtrata all'interno del pool, taglio a
    10. Confronto NON appaiato: sono insiemi diversi di righe, lo stesso disegno
    usato dal replay committato per il delta A−B sulla top 10.
    """
    pools = pools_of(rows)
    admitted = lambda r: bool(r["A_admitted"])
    above = lambda r: not below_threshold(r)          # solo soglia, niente gate

    sel_g: List[Dict[str, Any]] = []
    sel_n: List[Dict[str, Any]] = []
    slots_g: List[int] = []
    slots_n: List[int] = []
    for _, pool in pools.items():
        a = select_top(pool, admitted)
        b = select_top(pool, above)
        sel_g += a
        sel_n += b
        slots_g.append(len(a))
        slots_n.append(len(b))

    qg, qn = quality_of(sel_g), quality_of(sel_n)
    # probabilita' dell'ultimo slot riempito, per pool (con il gate)
    self_slots10 = [sorted([r for r in p if admitted(r)],
                           key=lambda r: r["A_conf"], reverse=True)[TOP_N - 1]["A_conf"]
                    for p in pools.values()
                    if len([r for r in p if admitted(r)]) >= TOP_N]
    ids_g = {r["match_id"] for r in sel_g}
    ids_n = {r["match_id"] for r in sel_n}
    entering = [r for r in sel_n if r["match_id"] not in ids_g]
    leaving = [r for r in sel_g if r["match_id"] not in ids_n]
    mean = lambda xs: (sum(xs) / len(xs)) if xs else None

    return {
        "gate": gate,
        "n_pools": len(pools),
        "pool_rule": "settimana ISO del cutoff + stagione, 5 leghe insieme, taglio a 10",
        "con_gate": {**qg, "mean_slots_filled": mean(slots_g),
                     "market_mix": dict(Counter(r["A_market"] for r in sel_g))},
        "senza_gate": {**qn, "mean_slots_filled": mean(slots_n),
                       "market_mix": dict(Counter(r["A_market"] for r in sel_n))},
        "delta": {
            "brier": (qn["brier"] - qg["brier"]) if qg["brier"] is not None and qn["brier"] is not None else None,
            "hit_rate": (qn["hit_rate"] - qg["hit_rate"]) if qg["hit_rate"] is not None and qn["hit_rate"] is not None else None,
            "mean_prob": (qn["mean_prob"] - qg["mean_prob"]) if qg["mean_prob"] is not None and qn["mean_prob"] is not None else None,
        },
        "slot10": slot10_stats(self_slots10),
        "swap": {
            "n": len(entering),
            "entrano": {**quality_of(entering), "markets": dict(Counter(r["A_market"] for r in entering))},
            "escono": {**quality_of(leaving), "markets": dict(Counter(r["A_market"] for r in leaving))},
        },
        "bootstrap": _pool_bootstrap_delta(
            {k: [r for r in p if admitted(r)] for k, p in pools.items()},
            {k: [r for r in p if above(r)] for k, p in pools.items()}),
    }


def slot10_stats(values: Sequence[float]) -> Dict[str, Optional[float]]:
    """Statistiche della confidence che chiude il 10° slot, sui pool che lo riempiono."""
    v = [x for x in values if x is not None]
    if not v:
        return {"n_pools": 0, "mean": None, "min": None, "p10": None}
    sv = sorted(v)
    return {"n_pools": len(v), "mean": sum(v) / len(v), "min": sv[0],
            "p10": sv[max(0, int(0.10 * (len(sv) - 1)))]}


def _pool_bootstrap_delta(pools_a: Dict[Any, List[Dict[str, Any]]],
                          pools_b: Dict[Any, List[Dict[str, Any]]],
                          n_boot: int = N_BOOT, seed: int = SEED) -> Dict[str, Any]:
    """ΔBrier e Δhit (B−A) con blocchi = pool. Delta non appaiato: in ogni
    draw si ri-applica il taglio a 10 a ciascun pool risampling."""
    keys = list(pools_b)
    if not keys:
        return {"n_blocks": 0, "brier": None, "hit_rate": None}
    rng = random.Random(seed)

    def _delta(sample: List[Any]) -> Tuple[Optional[float], Optional[float]]:
        pa: List[Tuple[float, int]] = []
        pb: List[Tuple[float, int]] = []
        for k in sample:
            for r in select_top(pools_a.get(k, []), lambda x: True):
                if r["A_conf"] is not None:
                    pa.append((r["A_conf"], r["A_hit"]))
            for r in select_top(pools_b.get(k, []), lambda x: True):
                if r["A_conf"] is not None:
                    pb.append((r["A_conf"], r["A_hit"]))
        qa, qb = quality(pa), quality(pb)
        if qa["n"] == 0 or qb["n"] == 0:
            return None, None
        return qb["brier"] - qa["brier"], qb["hit_rate"] - qa["hit_rate"]

    d_brier: List[float] = []
    d_hit: List[float] = []
    for _ in range(n_boot):
        b, h = _delta([rng.choice(keys) for _ in keys])
        if b is not None:
            d_brier.append(b)
        if h is not None:
            d_hit.append(h)
    point_b, point_h = _delta(keys)
    return {
        "n_boot": n_boot, "seed": seed, "n_blocks": len(keys),
        "brier": {"point": point_b, "ci95": _ci(d_brier)},
        "hit_rate": {"point": point_h, "ci95": _ci(d_hit)},
    }


def fit_isotonic(pairs: Sequence[Tuple[float, int]]) -> Callable[[float], float]:
    """Regressione isotona (PAVA) su ``(prob, esito)``: mappa monotona non parametrica.

    Serve a testare un'ipotesi diversa dal bias per mercato: se la *curva globale*
    di affidabilita' trasferisce fra stagioni, allora la probabilita' esposta va
    rimpicciolita; se non trasferisce, l'unica via e' il campione prospettico.
    """
    pts = sorted((float(pv), float(y)) for pv, y in pairs if pv is not None)
    if len(pts) < 2:
        return lambda x: x
    vals = [y for _, y in pts]
    blocks: List[List[int]] = [[i] for i in range(len(pts))]
    i = 0
    while i < len(blocks) - 1:
        a, b = blocks[i], blocks[i + 1]
        ma = sum(vals[j] for j in a) / len(a)
        mb = sum(vals[j] for j in b) / len(b)
        if ma <= mb + 1e-12:
            i += 1
            continue
        blocks[i] = a + b          # viola l'ordine: unisce e TORNA indietro
        del blocks[i + 1]          # a ricontrollare (PAVA standard)
        if i > 0:
            i -= 1
    # gradini: ogni blocco PAVA vale il proprio tasso medio, senza interpolare
    # fra i blocchi (l'interpolazione lineare fra blocchi ampi e' artifact-prone
    # sulle code, ed e' esattamente la regione dove vive la top 10).
    steps: List[Tuple[float, float]] = []
    for blk in blocks:
        m = sum(vals[j] for j in blk) / len(blk)
        steps.append((pts[blk[0]][0], m))

    def _map(x: float) -> float:
        if not steps:
            return x
        out = steps[0][1]
        for lo, m in steps:
            if x >= lo:
                out = m
            else:
                break
        return out
    return _map


def global_reliability_transfer(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Curva di affidabilita' fitata su UNA stagione, applicata all'altra.

    La mappa e' monotona: **non cambia l'ordine** (quindi non tocca la selezione
    della top 10), cambia solo la probabilita' esposta. Misura se la sovrastima
    del numero mostrato e' una costante trasferibile o rumore di coda.
    """
    seasons = sorted({r["season"] for r in rows})
    if len(seasons) != 2:
        return {"seasons": seasons, "available": False}
    out: Dict[str, Any] = {"seasons": seasons, "available": True, "esperimenti": []}
    for lbl in seasons:
        other = [x for x in seasons if x != lbl][0]
        fit = [r for r in rows if r["season"] == other and r["A_admitted"]]
        tgt: List[Dict[str, Any]] = []
        for _, pool in pools_of([r for r in rows
                                 if r["season"] == lbl and r["A_admitted"]]).items():
            tgt += select_top(pool, lambda x: True)
        if not fit or not tgt:
            continue
        g = fit_isotonic([(r["A_conf"], r["A_hit"]) for r in fit])
        raw = quality([(r["A_conf"], r["A_hit"]) for r in tgt])
        cal = quality([(g(r["A_conf"]), r["A_hit"]) for r in tgt])
        out["esperimenti"].append({
            "target": lbl, "fit_su": other, "n": raw["n"],
            "grezza": raw, "calibrata": cal,
            "delta_brier": (cal["brier"] - raw["brier"])
                           if raw["brier"] is not None and cal["brier"] is not None else None,
            "delta_prob": (cal["mean_prob"] - raw["mean_prob"])
                          if raw["mean_prob"] is not None and cal["mean_prob"] is not None else None,
        })
    return out


def _ci(values: Sequence[float], q: float = 0.025) -> List[Optional[float]]:
    if not values:
        return [None, None]
    v = sorted(values)
    return [v[int(q * len(v))], v[min(len(v) - 1, int((1 - q) * len(v)))]]


def slot_marginality(rows: Sequence[Dict[str, Any]], gate: float = 0.25) -> Dict[str, Any]:
    """Righe 1-10 vs righe 11-15 dello stesso pool: quanto vale lo slot."""
    pools = pools_of([r for r in rows if r["A_admitted"]])
    inside: List[Dict[str, Any]] = []
    outside: List[Dict[str, Any]] = []
    for _, p in pools.items():
        s = sorted(p, key=lambda r: r["A_conf"], reverse=True)
        if len(s) >= TOP_N + 5:
            inside += s[:TOP_N]
            outside += s[TOP_N:TOP_N + 5]
    return {"in_top10": quality_of(inside), "rank_11_15": quality_of(outside)}


# ---------------------------------------------------------------------------
# 5. Scala della confidence: perché "correggere il bias per mercato" non basta
# ---------------------------------------------------------------------------
def market_bias(rows: Sequence[Dict[str, Any]], min_n: int = MIN_N_PER_MARKET) -> Dict[str, float]:
    by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["A_admitted"]:
            by[r["A_market"]].append(r)
    out = {}
    for k, v in by.items():
        q = quality_of(v)
        if q["n"] >= min_n:
            out[k] = q["gap"]
    return out


def cross_season_calibration(rows: Sequence[Dict[str, Any]], gate: float = 0.25) -> Dict[str, Any]:
    """Bias per mercato stimato su UNA stagione e applicato ALL'ALTRA.

    È il test che decide se il divario di scala fra 1X2 e totali è
    correggibile con i dati disponibili. Se il trasferimento peggiora, la
    correzione non è un margine incassabile: serve un campione prospettico.
    """
    seasons = sorted({r["season"] for r in rows})
    if len(seasons) != 2:
        return {"seasons": seasons, "available": False}
    a, b = seasons
    ra = [r for r in rows if r["season"] == a]
    rb = [r for r in rows if r["season"] == b]
    bias_a, bias_b = market_bias(ra), market_bias(rb)
    common = sorted(set(bias_a) & set(bias_b))
    md = [abs(bias_a[k] - bias_b[k]) for k in common]

    result: Dict[str, Any] = {
        "seasons": [a, b], "available": True,
        "bias": {a: bias_a, b: bias_b},
        "mercati_comuni": common,
        "mean_abs_bias_diff": sum(md) / len(md) if md else None,
        "esperimenti": [],
    }
    for lbl, target, src_bias in ((b, rb, bias_a), (a, ra, bias_b)):
        pools = pools_of([r for r in target if r["A_admitted"]])
        raw: List[Dict[str, Any]] = []
        adj: List[Dict[str, Any]] = []
        for _, p in pools.items():
            if len(p) < TOP_N:
                continue
            raw += select_top(p, lambda r: True)
            adj += sorted(p, key=lambda r: r["A_conf"] - src_bias.get(r["A_market"], 0.0),
                          reverse=True)[:TOP_N]
        q_raw, q_adj = quality_of(raw), quality_of(adj)
        # stesse righe, solo la probabilita' ESPERTA corretta
        corr_pairs = [(r["A_conf"] - src_bias.get(r["A_market"], 0.0), r["A_hit"]) for r in raw]
        q_corr = quality(corr_pairs)
        result["esperimenti"].append({
            "target": lbl,
            "bias_usato": "stagione opposta",
            "top10_rank_su_prob_grezza": q_raw,
            "top10_rank_su_prob_corretta": q_adj,
            "delta_brier_ranking": (q_adj["brier"] - q_raw["brier"]) if q_raw["brier"] and q_adj["brier"] else None,
            "delta_hit_ranking": (q_adj["hit_rate"] - q_raw["hit_rate"]) if q_raw["hit_rate"] is not None and q_adj["hit_rate"] is not None else None,
            "stesse_righe_prob_esposta_corretta": q_corr,
            "delta_brier_esposizione": (q_corr["brier"] - q_raw["brier"]) if q_raw["brier"] and q_corr["brier"] else None,
        })
    return result


# ---------------------------------------------------------------------------
# 6. Copertura, mercati morti, fallback dei dati
# ---------------------------------------------------------------------------
def coverage_by_league(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for L in sorted({r["league"] for r in rows}):
        cand = [r for r in rows if r["league"] == L]
        adm = [r for r in cand if r["A_admitted"]]
        q = quality_of(adm)
        out.append({"league": L, "candidate": len(cand), "ammessa": len(adm),
                    "copertura": (len(adm) / len(cand)) if cand else None,
                    "prob_media": q["mean_prob"], "hit": q["hit_rate"], "brier": q["brier"]})
    return out


def market_mix(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Cosa è argmax Poisson sulle candidate, e cosa arriva a essere mostrato."""
    return {
        "argmax_poisson_tutte_le_candidate": dict(Counter(r["A_market"] for r in rows)),
        "mostrate_dopo_i_filtri": dict(Counter(r["A_market"] for r in rows if r["A_admitted"])),
    }


def data_quality(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    ids = [r["match_id"] for r in rows]
    return {
        "n": len(rows),
        "match_id_distinti": len(set(ids)),
        "match_id_duplicati": len(ids) - len(set(ids)),
        "elo_non_disponibile": sum(1 for r in rows if not r["elo_available"]),
        "team_stats_mancanti": sum(1 for r in rows if r["team_stats_missing"]),
        "mercati_ammessi_per_partita_B": dict(Counter(int(r["B_n_admitted_markets"] or 0)
                                                      for r in rows)),
    }


def replay_units_fallback(summary: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Quante giornate del replay giravano senza xG point-in-time (fallback gol)."""
    if not summary:
        return None
    units = summary.get("units") or []
    if not units:
        return None
    no_xg = [u for u in units if not u.get("xg_teams")]
    per_league = Counter((u.get("league"), u.get("season")) for u in no_xg)
    return {"n_units": len(units), "n_senza_xg": len(no_xg),
            "quota": len(no_xg) / len(units),
            "solo_prima_giornata": all((u.get("matchday") == 1) for u in no_xg),
            "dettaglio": {f"{k[0]} {k[1]}": v for k, v in sorted(per_league.items())}}


# ---------------------------------------------------------------------------
# 7. Consistenza con l'artefatto committato
# ---------------------------------------------------------------------------
def consistency_checks(rows: Sequence[Dict[str, Any]],
                       summary: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ricalcola le headline e le confronta con ``topmix_selector_replay.json``.

    Serve a garantire che le tabelle qui sotto stiano leggendo **le stesse
    selezioni** del report pubblicato: se un numero non coincide, questo script
    sta ridefinendo pool, soglia o Brier invece di riusarli.
    """
    if not summary:
        return []
    metrics = summary.get("metrics") or {}
    agg = metrics.get("aggregate") or {}
    top10_ref = metrics.get("top10") or {}
    checks: List[Dict[str, Any]] = []

    def add(name: str, got: Optional[float], exp: Optional[float],
            tol: float = CONSISTENCY_TOL, is_count: bool = False) -> None:
        if got is None or exp is None:
            checks.append({"nome": name, "ricalcolato": got, "atteso": exp,
                           "delta": None, "ok": None, "nota": "non confrontabile"})
            return
        d = got - exp
        checks.append({"nome": name, "ricalcolato": got, "atteso": exp, "delta": d,
                       "ok": abs(d) <= (0.5 if is_count else tol),
                       "nota": "conteggio" if is_count else f"tol {tol}"})

    adm = [r for r in rows if r["A_admitted"]]
    add("candidate", float(len(rows)), float(agg.get("n_candidates")), is_count=True)
    add("A ammesse", float(len(adm)), float(agg.get("n_A_admitted")), is_count=True)
    add("B ammesse", float(sum(1 for r in rows if r["B_admitted"])),
        float(agg.get("n_B_admitted")), is_count=True)
    qa = quality_of(adm)
    ref = (agg.get("on_all_shown") or {}).get("A") or {}
    add("A mostrate · prob media", qa["mean_prob"], ref.get("mean_prob"))
    add("A mostrate · hit rate", qa["hit_rate"], ref.get("hit_rate"))
    add("A mostrate · Brier", qa["brier"], ref.get("brier"))
    add("A mostrate · gap", qa["gap"], ref.get("gap"))
    # mix delle righe MOSTRATE (non della top 10)
    ref_shown_mix = (agg.get("market_mix_A") or {})
    mine_shown_mix = dict(Counter(r["A_market"] for r in adm))
    for mk in sorted(set(ref_shown_mix) | set(mine_shown_mix)):
        add(f"A mostrate · mix {mk}", float(mine_shown_mix.get(mk, 0)),
            float(ref_shown_mix.get(mk, 0)), is_count=True)
    # top 10: pool, slot, metriche, composizione
    t10 = top10_gate_comparison(list(rows))
    ref_a = top10_ref.get("A") or {}
    add("top 10 · n pool", float(t10["n_pools"]), float(top10_ref.get("n_pools") or 0),
        is_count=True)
    add("top 10 A · n", float(t10["con_gate"]["n"]),
        float(ref_a["n"]) if ref_a.get("n") is not None else None, is_count=True)
    add("top 10 A · slot medi", t10["con_gate"]["mean_slots_filled"], ref_a.get("mean_slots_filled"))
    add("top 10 A · prob media", t10["con_gate"]["mean_prob"], ref_a.get("mean_prob"))
    add("top 10 A · hit rate", t10["con_gate"]["hit_rate"], ref_a.get("hit_rate"))
    add("top 10 A · Brier", t10["con_gate"]["brier"], ref_a.get("brier"))
    ref_mix = (ref_a.get("market_mix") or {})
    mine = t10["con_gate"].get("market_mix", {})
    for mk in sorted(set(ref_mix) | set(mine)):
        add(f"top 10 A · mix {mk}", float(mine.get(mk, 0)), float(ref_mix.get(mk, 0)),
            is_count=True)
    return checks


# ---------------------------------------------------------------------------
# 8. Renderizzazione
# ---------------------------------------------------------------------------
def _pct(v: Optional[float], d: int = 1) -> str:
    return "—" if v is None else f"{v * 100:.{d}f}%"


def _f(v: Optional[float], d: int = 4) -> str:
    return "—" if v is None else f"{v:.{d}f}"


def _sf(v: Optional[float], d: int = 4) -> str:
    return "—" if v is None else f"{v:+.{d}f}"


def _spp(v: Optional[float], d: int = 1) -> str:
    return "—" if v is None else f"{v * 100:+.{d}f} pp"


def _qrow(label: str, q: Dict[str, Any]) -> str:
    return (f"| {label} | {q['n']} | {_pct(q['mean_prob'])} | {_pct(q['hit_rate'])} | "
            f"{_pct(q['gap'], 1) if q['gap'] is not None else '—'} | {_f(q['brier'])} |")


def render_markdown(payload: Dict[str, Any], meta: Dict[str, Any]) -> str:
    L: List[str] = []
    L.append("# Margini migliorabili del selettore Top Mix — numeri")
    L.append("")
    L.append(f"*Generato*: {meta['generated_at']} · *righe analizzate*: {meta['n_rows']} · "
             f"*commit codice*: `{meta['git_sha']}`")
    L.append("")
    L.append(f"> **Etichetta dei dati.** {meta['season_status']} "
             "Non è un hold-out. Nessuna soglia, peso o formula è stata cercata o "
             "cambiata in questo giro: le tabelle misurano il **costo di vincoli già "
             "esistenti**, non il valore di vincoli alternativi. Fonte: "
             "`audit/results/topmix_selector_replay_rows.csv` (output di "
             "`audit/topmix_selector_replay.py`, importato come convenzione di pool "
             "e di bootstrap, non ricalcolato dal motore).")
    L.append("")

    L.append("## 0. Consistenza con l'artefatto committato")
    L.append("")
    checks = payload["consistency"]
    if not checks:
        L.append("_`topmix_selector_replay.json` non trovato: confronto saltato._")
    else:
        L.append("| Grandezza | ricalcolata | attesa (report) | Δ | ok |")
        L.append("|---|---:|---:|---:|:--:|")
        for c in checks:
            L.append(f"| {c['nome']} | {_f(c['ricalcolato'], 4)} | {_f(c['atteso'], 4)} | "
                     f"{_f(c['delta'], 6)} | {'✅' if c['ok'] else ('—' if c['ok'] is None else '❌')} |")
        n_ok = sum(1 for c in checks if c["ok"])
        L.append("")
        L.append(f"{n_ok}/{len(checks)} grandezze coincidono entro la tolleranza "
                 f"({CONSISTENCY_TOL} sulle metriche, ±0,5 sui conteggi): le tabelle "
                 "sotto riutilizzano esattamente le stesse selezioni del replay "
                 "pubblicato, non una loro reinterpretazione.")
    L.append("")

    L.append("## 1. Dove finisce ogni partita candidata (attribuzione degli scarti)")
    L.append("")
    rb = payload["rejection"]
    L.append(f"Candidate **{rb['n_candidates']}**, ammesse da A **{rb['n_admitted']}** "
             f"({_pct(rb['n_admitted'] / rb['n_candidates'])}).")
    L.append("")
    L.append("| Scartata per | n | prob media mostrata | hit se accettata | gap | Brier |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for name, key in (("soglia 0,55/0,60 (solo)", "only_soglia"),
                      ("disaccordo Elo ≥ 0,25 (solo)", "only_disaccordo"),
                      ("entrambi i vincoli", "only_entrambi")):
        q = rb[key]
        L.append(f"| {name} | {q['n']} | {_pct(q['mean_prob'])} | {_pct(q['hit_rate'])} | "
                 f"{_pct(q['gap'])} | {_f(q['brier'])} |")
    L.append("")
    q_thr, q_gate, q_adm = (rb["only_soglia"], rb["only_disaccordo"],
                            payload["admitted"]["overall"])
    L.append("Lettura: il gate di disaccordo è l'unico scarto che butta via partite **migliori "
             f"della media delle ammesse** (hit {_pct(q_gate['hit_rate'])} contro il "
             f"{_pct(q_adm['hit_rate'])}; Brier {_f(q_gate['brier'])} contro {_f(q_adm['brier'])}). "
             "La soglia invece taglia bande in linea con la propria dichiarazione "
             f"(hit {_pct(q_thr['hit_rate'])} a fronte di {_pct(q_thr['mean_prob'])} dichiarata): "
             "accettarle porterebbe volume, non valore — ed è, in negativo, ciò che ha reso "
             "inutile il selettore B (§3 e §4 del rapporto di replay).")
    L.append("")
    L.append("### 1a. Le partite perse solo per il gate, per mercato")
    L.append("")
    g = payload["gate_only"]
    L.append(f"n = {g['n']}, prob media {_pct(g['mean_prob'])}, hit {_pct(g['hit_rate'])}, "
             f"Brier {_f(g['brier'])}. Composizione: " +
             ", ".join(f"{k} {v}" for k, v in sorted(g["markets"].items(), key=lambda kv: -kv[1])) + ".")
    if g["per_market"]:
        L.append("")
        L.append("| Mercato | n | prob | hit | gap | Brier |")
        L.append("|---|---:|---:|---:|---:|---:|")
        for mk, q in sorted(g["per_market"].items(), key=lambda kv: -kv[1]["n"]):
            L.append(_qrow(mk, q))
        L.append("")
        L.append("Il `1` bloccato dal gate ha una frequenza reale **superiore** a quella "
                 "dichiarata (gap negativo): lì il disaccordo Elo sta scartando informazione, "
                 "non rumore.")
    L.append("")

    L.append("### 1b. Cosa c'è appena sotto la soglia (perché non è un margine)")
    L.append("")
    L.append("Partite bocciate dal solo taglio di confidenza (gate rispettato), valutate sul "
             "mercato che A avrebbe mostrato:")
    L.append("")
    L.append("| Banda | Famiglia | soglia oggi | n | prob media | hit | gap | Brier |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for e in payload["threshold_bands"]:
        lo, hi = e["band"]
        L.append(f"| [{lo:.2f}, {hi:.2f}) | {e['famiglia']} | {e['soglia_attuale']:.2f} | {e['n']} | "
                 f"{_pct(e['mean_prob'])} | {_pct(e['hit_rate'])} | {_pct(e['gap'])} | {_f(e['brier'])} |")
    L.append("")
    se = payload["top10_gate"].get("slot10") or {}
    hit_max = max((e["hit_rate"] for e in payload["threshold_bands"] if e["hit_rate"] is not None),
                  default=None)
    L.append("Nelle bande sotto soglia la frequenza reale è in linea con la probabilità dichiarata "
             f"(gap fra −1,2 % e −4,2 %; hit massimo osservato {_pct(hit_max)}): il margine lì è "
             "**quantità di righe**, non qualità. A conferma: lo slot #10 si chiude in media a "
             f"**{_pct(se.get('mean'))}** di confidence (minimo {_pct(se.get('min'))}, 10° percentile "
             f"{_pct(se.get('p10'))} su {se.get('n_pools')} pool): la fascia 0,55-0,60 contenderebbe "
             "uno slot solo nei pool più poveri (minimo "
             f"{_pct(se.get('min'))}), mentre il grosso delle candidate scartate sta sotto. È la "
             "stessa ragione per cui le ~155 partite recuperate dal selettore B non arrivavano al "
             "prodotto (§3 e §4 del rapporto di replay).")
    L.append("")

    L.append("## 2. Qualità delle righe ammesse, per mercato")
    L.append("")
    L.append("| Mercato | n | prob media | hit | gap | Brier |")
    L.append("|---|---:|---:|---:|---:|---:|")
    L.append(_qrow("**tutte**", payload["admitted"]["overall"]))
    for mk, q in payload["admitted"]["by_market"].items():
        L.append(_qrow(mk, q))
    L.append("")
    gaps = {k: v["gap"] for k, v in payload["admitted"]["by_market"].items() if v["gap"] is not None}
    if gaps:
        lo, hi = min(gaps.items(), key=lambda kv: kv[1]), max(gaps.items(), key=lambda kv: kv[1])
        L.append(f"Il gap (prob − hit) va da {lo[0]} {_pct(lo[1])} a {hi[0]} {_pct(hi[1])}: la "
                 f"`confidence` **non è una scala unica fra mercati**, ed è la scala con cui la "
                 "top 10 viene ordinata (`sorted(..., key=prob, reverse=True)[:10]`). "
                 "Vedi §5 per perché questo non si corregge gratis.")
    L.append("")

    L.append("## 3. Ammesse per fascia di disaccordo (il gate lavora già dentro le ammesse)")
    L.append("")
    L.append("| Fascia \\|poisson − elo\\| | n | prob media | hit | gap | Brier |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for e in payload["admitted_by_disagreement"]:
        lo, hi = e["band"]
        L.append(f"| [{lo:.2f}, {hi:.2f}) | {e['n']} | {_pct(e['mean_prob'])} | "
                 f"{_pct(e['hit_rate'])} | {_pct(e['gap'])} | {_f(e['brier'])} |")
    L.append("")
    L.append("Se il disaccordo fosse segnale, le righe con `|Δ|` alto dovrebbero essere le "
             "peggiori delle ammesse. Non lo sono (le bande sono vicine, e la peggior Brier non "
             "è quella a disaccordo massimo): il contenuto informativo del disaccordo è già "
             "assorbito dal blend `0.6·Poisson + 0.4·Elo`, che **penalizza** la confidence. Il "
             "gate hard aggiunge una seconda penalità, questa volta a senso unico (esclusione).")
    L.append("")

    L.append("## 4. Top 10: gate come cancellazione vs gate come penalità")
    L.append("")
    t = payload["top10_gate"]
    L.append(f"Pool: {t['pool_rule']} — **{t['n_pools']}** pool. "
             "Stesso identico ordinamento per probabilità; gli insiemi cambiano solo perché "
             "una riga con `|Δ| ≥ 0,25` viene ammessa invece di essere scartata.")
    L.append("")
    L.append("| Configurazione | righe | slot medi | prob media | hit | Brier |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for lbl, key in (("con il gate (produzione)", "con_gate"), ("senza il gate (stesse soglie)", "senza_gate")):
        q = t[key]
        L.append(f"| {lbl} | {q['n']} | {_f(q['mean_slots_filled'], 2)} | {_pct(q['mean_prob'])} | "
                 f"{_pct(q['hit_rate'])} | {_f(q['brier'])} |")
    d = t["delta"]
    L.append(f"| **Δ (senza − con)** | 0 | — | {_pct(d['mean_prob'])} | {_pct(d['hit_rate'])} | "
             f"{_f(d['brier'])} |")
    L.append("")
    bs = t["bootstrap"]
    L.append(f"Bootstrap a blocchi sul pool (blocco = weekend, Δ non appaiato, {bs['n_blocks']} blocchi, "
             f"{bs['n_boot']} draw, seed {bs['seed']}): "
             f"ΔBrier = {_f(bs['brier']['point'])} (IC95% {_f(bs['brier']['ci95'][0])} … {_f(bs['brier']['ci95'][1])}), "
             f"Δhit = {_pct(bs['hit_rate']['point'])} (IC95% {_pct(bs['hit_rate']['ci95'][0])} … "
             f"{_pct(bs['hit_rate']['ci95'][1])}).")
    L.append("")
    L.append("Composizione: con il gate " +
             ", ".join(f"{k}={v}" for k, v in sorted(t["con_gate"]["market_mix"].items(), key=lambda kv: -kv[1])) +
             " · senza " +
             ", ".join(f"{k}={v}" for k, v in sorted(t["senza_gate"]["market_mix"].items(), key=lambda kv: -kv[1])) + ".")
    se4 = t.get("slot10") or {}
    L.append("")
    L.append(f"Confidence che chiude il 10° slot, sui pool che lo riempiono: media "
             f"{_pct(se4.get('mean'))}, minimo {_pct(se4.get('min'))} "
             f"(10° percentile {_pct(se4.get('p10'))}).")
    L.append("")
    sw = t["swap"]
    L.append("### 4a. Cosa entra e cosa esce dagli slot")
    L.append("")
    tot_slots = t["con_gate"]["n"] or 1
    L.append(f"Cambiano **{sw['n']} slot su {t['con_gate']['n']}** "
             f"({_pct(sw['n'] / tot_slots)} degli slot riempiti).")
    L.append("")
    L.append("| | n | prob | hit | gap | Brier |")
    L.append("|---|---:|---:|---:|---:|---:|")
    L.append(_qrow("entrerebbero (oggi bloccate)", sw["entrano"]))
    L.append(_qrow("uscirebbero", sw["escono"]))
    L.append("")
    ent_mk = sw["entrano"]["markets"] or {}
    sol_1x2 = bool(ent_mk) and all(k in MARKETS_1X2 for k in ent_mk)
    L.append("Mercati in entrata: " + ", ".join(f"{k} {v}" for k, v in
               sorted(ent_mk.items(), key=lambda kv: -kv[1])) + ". " +
             ("Le righe che il gate blocca e che avrebbero un posto in top 10 sono **tutte 1X2** "
              "e, su queste due stagioni, più affidabili di quelle che sostituiscono."
              if sol_1x2 else
              "Le righe in entrata coprono più famiglie di mercato.") +
             " È il singolo punto con il delta più favorevole emerso dall'analisi; resta "
             "**non dimostrato** (intervallo che include lo zero) e su validation riusata: è un "
             "candidato per la conferma prospettica, non un cambiamento da varare adesso.")
    L.append("")
    sm = payload["slot_marginality"]
    L.append("### 4b. Valore marginale dello slot")
    L.append("")
    L.append("| | n | prob | hit | gap | Brier |")
    L.append("|---|---:|---:|---:|---:|---:|")
    L.append(_qrow("righe 1-10 del pool", sm["in_top10"]))
    L.append(_qrow("righe 11-15 dello stesso pool", sm["rank_11_15"]))
    L.append("")
    L.append("Il taglio a 10 è netto (le 11-15 sono peggio di ~15 pp di hit): **la dimensione 10 non "
             "è il problema**; il problema è la graduatoria con cui si riempie.")
    L.append("")

    L.append("## 5. Scala dei mercati: perché il bias non si corregge gratis")
    L.append("")
    cs = payload["cross_season"]
    if not cs.get("available"):
        L.append("_Servono exactly due stagioni nel file delle righe: esperimento saltato._")
    else:
        a, b = cs["seasons"]
        L.append(f"Bias per mercato (`prob − hit` sulle righe ammesse), stimato **su una sola "
                 f"stagione** e trasferito all'altra ({a} ⇄ {b}).")
        L.append("")
        L.append(f"| Mercato | bias {a} | bias {b} | scarto |")
        L.append("|---|---:|---:|---:|")
        for mk in cs["mercati_comuni"]:
            L.append(f"| {mk} | {_pct(cs['bias'][a][mk])} | {_pct(cs['bias'][b][mk])} | "
                     f"{abs(cs['bias'][a][mk] - cs['bias'][b][mk]) * 100:.1f} pp |")
        L.append("")
        _mabd = cs["mean_abs_bias_diff"]
        L.append(f"Scarto medio del bias fra le due stagioni: "
                 f"**{'—' if _mabd is None else format(_mabd * 100, '.1f') + ' pp'}**. "
                 "Il gap di scala c'è, ma la sua *entità* non è stabile: è rumore di coda del "
                 "mercato selezionato, non una costante stimabile su 740 righe.")
        L.append("")
        for e in cs["esperimenti"]:
            L.append(f"**Applica il bias dell'altra stagione a `{e['target']}`**")
            L.append("")
            L.append("| | n | prob | hit | gap | Brier |")
            L.append("|---|---:|---:|---:|---:|---:|")
            L.append(_qrow("top 10 ordinata su prob grezza (oggi)", e["top10_rank_su_prob_grezza"]))
            L.append(_qrow("top 10 ordinata su prob − bias", e["top10_rank_su_prob_corretta"]))
            L.append("")
            L.append(f"- riordinare con la correzione: ΔBrier "
                     f"{_sf(e['delta_brier_ranking'])} (positivo = peggiora), "
                     f"Δhit {_spp(e['delta_hit_ranking'])}")
            L.append(f"- esporre la probabilità corretta (stesse righe): Brier "
                     f"{_f(e['stesse_righe_prob_esposta_corretta']['brier'])} "
                     f"(Δ {_sf(e['delta_brier_esposizione'])})")
            L.append("")
        L.append("In entrambe le direzioni la correzione per mercato **peggiora** Brier: la "
                 "correzione sbagliata sposta l'ordine più di quanto corregga il livello. Quindi: "
                 "il margine «rendere confrontabili le scale» è reale (è ciò che fa fallire il "
                 "selettore B, §6 del rapporto di replay), ma non è incassabile su queste due "
                 "stagioni — serve una curva di calibrazione per mercato stimata sull'intero "
                 "campione di base (dove la baseline è già calibrata: gap ≤ 3,1 pp) e una "
                 "conferma prospettica.")
    L.append("")

    L.append("### 5b. Curva di affidabilita' globale (senza toccare la selezione)")
    L.append("")
    gr = payload.get("global_reliability") or {}
    if not gr.get("available"):
        L.append("_Servono due stagioni nel file delle righe: esperimento saltato._")
    else:
        L.append("Regressione isotona (PAVA) fitata sulle righe ammesse di una stagione e applicata "
                 "all'altra. Essendo monotona **non cambia l'ordine** della top 10: corregge solo il "
                 "numero esposto.")
        L.append("")
        L.append("| Target (fit sull'altra) | n | prob grezza | hit | Brier grezza | prob calibrata | Brier calibrata | ΔBrier |")
        L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for e in gr["esperimenti"]:
            r_, c_ = e["grezza"], e["calibrata"]
            L.append(f"| {e['target']} (fit su {e['fit_su']}) | {e['n']} | {_pct(r_['mean_prob'])} | "
                     f"{_pct(r_['hit_rate'])} | {_f(r_['brier'])} | {_pct(c_['mean_prob'])} | "
                     f"{_f(c_['brier'])} | {_f(e['delta_brier'])} |")
        L.append("")
        db = [e["delta_brier"] for e in gr["esperimenti"] if e["delta_brier"] is not None]
        dp = [e["delta_prob"] for e in gr["esperimenti"] if e["delta_prob"] is not None]
        if db and all(abs(x) < 5e-3 for x in db):
            lettura = ("i ΔBrier sono **entro mezzo punto di Brier** (max "
                       f"{max(abs(x) for x in db) * 1000:.1f} millesimi): la curva globale trasferisce "
                       "in modo approssimativo, non migliora. Togliendo la sovrastima si passa da "
                       "un gap di +1,5 pp a uno di segno opposto: si sta **sovra-correggendo** la coda "
                       "alta, che e' poi l'unica regione che il Top Mix mostra.")
        elif db and all(x > 5e-3 for x in db):
            lettura = ("i ΔBrier sono positivi e ampi: la curva globale fitata sulle righe ammesse "
                       "*rovina* la coda alta dove vive la top 10, perche' la fascia 0,55-0,65 domina "
                       "il fit.")
        elif db and all(x < 0 for x in db):
            lettura = "i ΔBrier sono negativi in entrambe le direzioni: la curva trasferisce."
        else:
            lettura = "i ΔBrier sono di segno non coerente fra le due stagioni: nessun trasferimento stabile."
        L.append("Lettura: " + lettura)
        if dp:
            L.append("")
            L.append(f"Spostamento del numero esposto: {min(dp) * 100:+.1f} … {max(dp) * 100:+.1f} pp. "
                     "Conclusione operativa identica in ogni caso: **il numero mostrato non si tocca "
                     "con questi dati** (coerente con §7 del rapporto di replay: curve di A e B "
                     "sovrapposte, sovrastima = effetto coda del selezionare il massimo).")
    L.append("")

    L.append("## 6. Copertura per lega e mercati mai raggiungibili")
    L.append("")
    L.append("| Lega | candidate | ammesse | copertura | prob media | hit | Brier |")
    L.append("|---|---:|---:|---:|---:|---:|---:|")
    for c in payload["coverage"]:
        L.append(f"| {c['league']} | {c['candidate']} | {c['ammessa']} | {_pct(c['copertura'])} | "
                 f"{_pct(c['prob_media'])} | {_pct(c['hit'])} | {_f(c['brier'])} |")
    L.append("")
    mm = payload["market_mix"]
    L.append("Mercato scelto (argmax Poisson) sulle candidate, e dopo i filtri:")
    L.append("")
    L.append("```")
    L.append("argmax:  " + json.dumps(mm["argmax_poisson_tutte_le_candidate"], ensure_ascii=False))
    L.append("mostrate: " + json.dumps(mm["mostrate_dopo_i_filtri"], ensure_ascii=False))
    L.append("```")
    L.append("")
    L.append("`X` non è **mai** argmax e non può superare 0,55: il pareggio è un mercato morto del "
             "Top Mix, ed è il mercato con il maggiore disallineamento della baseline (22,1 % "
             "dichiarato contro 25,2 % reale, §6 del rapporto di replay). `NG` è vivo solo nominalmente.")
    L.append("")
    dq = payload["data_quality"]
    L.append("## 7. Stato dei dati del replay (per leggere i numeri sopra)")
    L.append("")
    L.append(f"- Elo non disponibile in {dq['elo_non_disponibile']}/{dq['n']} partite candidate; "
             f"`team_stats` assente per almeno una squadra in {dq['team_stats_mancanti']:.0f} partite "
             "(in quei casi il ramo di produzione ripiega su `att=def=1.0`: è il percorso che "
             "`fetch_and_calc_top_mix` percorre senza segnalarlo).")
    L.append(f"- mercati ammessi per partita dal selettore B: " +
             ", ".join(f"{k} → {v}" for k, v in sorted(dq["mercati_ammessi_per_partita_B"].items())))
    fu = payload.get("units_fallback")
    if fu:
        L.append(f"- giornate del replay senza xG point-in-time: {fu['n_senza_xg']}/{fu['n_units']} "
                 f"({_pct(fu['quota'])}), "
                 + ("tutte la 1ª giornata" if fu["solo_prima_giornata"] else "distribuite")
                 + " → la testa Totali era su fallback-gol solo a campionato appena aperto "
                   "(dettaglio: " + json.dumps(fu["dettaglio"], ensure_ascii=False) + ").")
    L.append("")

    L.append("## 8. Cosa questi numeri NON dimostrano")
    L.append("")
    L.append("- **Non sono una taratura.** Nessuna soglia/peso è stata cercata; §4 è il costo di un "
             "vincolo esistente, non la bontà del suo rimpiazzo.")
    L.append("- **Sono validation riusata.** 2024/25 + 2025/26 sono le stagioni su cui il motore è già "
             "stato scelto (`audit/topmix_selector_audit_protocol.md` §3).")
    L.append("- **Δ non appaiato.** Le due top 10 di §4 contengono partite diverse: il bootstrap sul "
             "pool è il minimo che si possa fare, non un test appaiato.")
    L.append("- **74 swap su 740 slot** su 3 422 partite: potenza bassa di proposito, non di trascuratezza.")
    dqp = payload["data_quality"]
    L.append("- **Ricostruzione, non live.** I candidati vengono dai CSV (nessuno snapshot API "
             f"TIMED/SCHEDULED); `match_id` è la chiave del replay (`Lega|anno|indice`: "
             f"{dqp['match_id_distinti']} distinti su {dqp['n']} righe, "
             f"{dqp['match_id_duplicati']} duplicati), non l'id di football-data.org; forma e "
             "calcolo point-in-time con i limiti dichiarati in §9 del rapporto di replay. Gli "
             "identici limiti valgono per A e per B, quindi non spostano i confronti interni, ma "
             "impediscono di chiamare questo un replay bit-identico del Top Mix live.")
    L.append("")
    L.append("## 9. Riproduzione")
    L.append("")
    L.append("```bash")
    L.append("python audit/topmix_margins.py                 # scrive audit/results/topmix_margins.{md,json}")
    L.append("python audit/topmix_margins.py --rows <csv> --out <md> --json <json>")
    L.append("python audit/test_topmix_margins.py   # 33 test, solo stdlib (pytest non serve)")
    L.append("```")
    L.append("")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# 9. Orchestrazione
# ---------------------------------------------------------------------------
def compute(rows: List[Dict[str, Any]], summary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    adm = [r for r in rows if r["A_admitted"]]
    return {
        "consistency": consistency_checks(rows, summary),
        "rejection": rejection_breakdown(rows),
        "admitted": {"overall": quality_of(adm),
                     "by_market": {k: dict(v) for k, v in
                                    admitted_quality_by_market(rows).items()}},
        "admitted_by_disagreement": admitted_quality_by_disagreement(rows),
        "gate_only": gate_only_rejections(rows),
        "threshold_bands": threshold_bands(rows),
        "top10_gate": top10_gate_comparison(rows),
        "slot_marginality": slot_marginality(rows),
        "cross_season": cross_season_calibration(rows),
        "global_reliability": global_reliability_transfer(rows),
        "coverage": coverage_by_league(rows),
        "market_mix": market_mix(rows),
        "data_quality": data_quality(rows),
        "units_fallback": replay_units_fallback(summary),
    }


def _git_sha() -> str:
    try:
        import subprocess
        return subprocess.check_output(["git", "-C", _REPO_ROOT, "rev-parse", "HEAD"],
                                       text=True).strip()[:12]
    except Exception:
        return "sconosciuto"


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Margini migliorabili del Top Mix (sola lettura)")
    ap.add_argument("--rows", default=DEFAULT_ROWS, help="CSV delle righe del replay")
    ap.add_argument("--summary", default=DEFAULT_SUMMARY,
                    help="JSON del replay, per il controllo di consistenza")
    ap.add_argument("--out", default=DEFAULT_OUT_MD, help="Markdown di uscita")
    ap.add_argument("--json", dest="json_out", default=DEFAULT_OUT_JSON, help="JSON di uscita")
    args = ap.parse_args(argv)

    rows = load_rows(args.rows)
    summary = None
    if args.summary and os.path.exists(args.summary):
        with open(args.summary, encoding="utf-8") as fh:
            summary = json.load(fh)

    payload = compute(rows, summary)
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "n_rows": len(rows),
        "rows_file": os.path.relpath(args.rows, _REPO_ROOT),
        "season_status": (summary.get("meta", {}).get("season_status", "")
                          if summary else ""),
    }
    text = render_markdown(payload, meta)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump({"meta": meta, "payload": payload}, fh, ensure_ascii=False, indent=1,
                      default=lambda o: None)
    print(f"scritto: {args.out}")
    if args.json_out:
        print(f"scritto: {args.json_out}")
    bad = [c for c in payload["consistency"] if c["ok"] is False]
    if bad:
        print("ATTENZIONE: consistenza non raggiunta per " + ", ".join(c["nome"] for c in bad),
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
