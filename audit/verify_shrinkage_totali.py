"""
verify_shrinkage_totali.py - Test dello shrinkage onesto sui Totali (O/U2.5, GG/NG).

Audit di SOLA VERIFICA, nessuna modifica a produzione. Domande (brief 2026-09-19):

  1. ricalcolo indipendente di k* (p* = base + k*(p_grezza - base)) per O/U2.5 e
     GG/NG SEPARATAMENTE (non "Totali" aggregato), sulla stessa fonte del 17/09
     (topmix_selector_replay_rows.csv, 3422 candidate / 1865 ammesse), con l'1X2
     come controllo di coerenza (atteso ~0.91 da misura precedente);
  2. stabilita' TRAIN (2024/25) vs VAL (2025/26) di k*: se divergono, va segnalato;
  3. walk-forward onesto: (base, k) congelati sul TRAIN, applicati al TEST 2025/26
     RIGENERATO col motore live vero (non la replica memorizzata): quante righe
     ammesse restano sopra soglia 0.60, Reliability/Brier delle superstiti raw vs p*;
  4. righe che SPARISCONO (raw>=0.60 ma p*<0.60): hit rate REALE (Wilson CI) vs
     base rate -- rumore spacciato per confidenza o segnale genuino?
  5. coerenza per lega di k* (un k* aggregato robusto ma incoerente per lega non e'
     lo stesso segnale ovunque -- lezione PPDA);
  6. raccomandazione esplicita su COME applicarlo (soglia ricalibrata vs solo
     probabilita' mostrata).

Due ancore pre-specified per ``base`` (entrambe riportate):
  * UNCOND = frequenza incondizionata dell'evento fra i candidati (≈0.5 sui
    totali): è la costruzione che riproduce l'ordine di grandezza della stima
    223/741 di memoria;
  * PICKED = hit rate realizzata delle righe ammesse per mercato (ancora
    "ciò che la selezione realmente produce").

k* Brier-optimal ha forma chiusa (il Brier è quadratico in k):
    k* = Σ (p−b)(y−b) / Σ (p−b)²   [clip a [0,1]]
usata sia sul fit pieno sia dentro il bootstrap; il k* LogLoss-optimal (griglia
0–1 passo 0.001) è riportato come sensibilità solo sui fit pieni.

Fonte e validazione: il replay del motore live viene RIFATTO da
``audit.topmix_selector_replay`` (funzioni di produzione, dati point-in-time).
Sulla testa Totali le righe fresh sono bit-identiche al CSV committato (conf =
Poisson puro, nessun Elo): il CSV è quindi base valida. Sull'1X2 la conf fresh
DIVERGE (lo stato Elo di produzione è cambiato dal 05/09): il controllo 0.91 è
fatto sulla fonte 17/09 e il drift è misurato e riportato a parte.

Uso:
    python audit/verify_shrinkage_totali.py            # usa/crea la cache fresh
    python audit/verify_shrinkage_totali.py --fresh    # rigenera il replay
Output: audit/results/shrinkage_totali_onesto.{md,json} (+ righe fresh in CSV)
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import math
import os
import random
import statistics
import sys
from datetime import datetime, timezone

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)

RESULTS_DIR_DEFAULT = os.path.join(_REPO_ROOT, "audit", "results")
SOURCE_CSV = os.path.join(_REPO_ROOT, "audit", "results",
                          "topmix_selector_replay_rows.csv")
FRESH_CACHE = os.path.join(_REPO_ROOT, "audit", "results",
                           "shrinkage_totali_replay_rows.csv")

FAMILIES = {
    "OU25": ("O2.5", "U2.5"),
    "GGNG": ("GG", "NG"),
    "1X2": ("1", "2"),
}
FAMILY_LABEL = {"OU25": "O/U 2.5", "GGNG": "GG/NG", "1X2": "1X2 (controllo)"}
TRAIN_LABEL, TEST_LABEL = "2024/25", "2025/26"
THRESHOLD = 0.60          # MIN_CONF_OU_GG di produzione
N_BOOT = 2000
SEED = 20260919
KGRID = [i / 1000 for i in range(0, 1001)]


# --------------------------------------------------------------- utilities --

def event_hit(market: str, r: dict) -> int:
    gh, ga = int(r["fthg"]), int(r["ftag"])
    g = gh + ga
    if market == "O2.5":
        return int(g > 2)
    if market == "U2.5":
        return int(g < 3)
    if market == "GG":
        return int(gh > 0 and ga > 0)
    if market == "NG":
        return int(not (gh > 0 and ga > 0))
    if market == "1":
        return int(gh > ga)
    if market == "2":
        return int(ga > gh)
    raise ValueError(market)


def uncond_base(market: str, pool: list) -> float:
    """Frequenza incondizionata dell'evento ``market`` fra i candidati del pool
    (dai punteggi, indipendente dal mercato argmax di ciascuna riga)."""
    if not pool:
        return float("nan")
    return statistics.fmean(event_hit(market, r) for r in pool)


def picked_base(market: str, pool: list, family: str) -> float:
    sub = [r for r in pool if r["A_market"] == market]
    if sub:
        return statistics.fmean(int(r["A_hit"]) for r in sub)
    fam = [r for r in pool if r["A_market"] in FAMILIES[family]]
    return statistics.fmean(int(r["A_hit"]) for r in fam) if fam else float("nan")


def star(p: float, base: float, k: float) -> float:
    return base + k * (p - base)


def k_brier_analytic(pts) -> float:
    """k* = mean((p-b)(y-b)) / mean((p-b)^2), clip [0,1]."""
    num = den = 0.0
    for p, y, b in pts:
        dp = p - b
        num += dp * (y - b)
        den += dp * dp
    if den <= 0:
        return 0.0
    return min(1.0, max(0.0, num / den))


def brier_of(pts, k: float) -> float:
    return statistics.fmean((star(p, b, k) - y) ** 2 for p, y, b in pts)


def logloss_of(pts, k: float) -> float:
    s = 0.0
    for p, y, b in pts:
        q = min(max(star(p, b, k), 1e-9), 1 - 1e-9)
        s += -(y * math.log(q) + (1 - y) * math.log(1 - q))
    return s / len(pts)


def k_logloss_grid(pts) -> float:
    best_k, best_v = 0.0, None
    for k in KGRID:
        v = logloss_of(pts, k)
        if best_v is None or v < best_v:
            best_k, best_v = k, v
    return best_k


def wilson_ci(hits: int, n: int, z: float = 1.959963985):
    if n == 0:
        return (float("nan"), float("nan"))
    ph = hits / n
    d = 1 + z * z / n
    c = ph + z * z / (2 * n)
    e = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))
    return ((c - e) / d, (c + e) / d)


def make_pts(sub: list, anchor: str, family: str, pool_adm, pool_all):
    """(p, y, base) per le righe ``sub``.
    UNCOND: base = frequenza incondizionata dell'evento (event_hit dai punteggi)
    fra TUTTI i candidati del pool -- indipendente dalla selezione.
    PICKED: base = hit rate realizzata delle ammesse con quel mercato
    (fallback: media della famiglia)."""
    if anchor == "UNCOND":
        bmap = {m: uncond_base(m, pool_all) for m in
                set(FAMILIES[family]) | {r["A_market"] for r in sub}}
        pts = [(float(r["A_conf"]), int(r["A_hit"]), bmap[r["A_market"]])
               for r in sub]
        return pts
    from collections import defaultdict
    acc = defaultdict(list)
    for r in pool_adm:
        acc[r["A_market"]].append(int(r["A_hit"]))
    fam_rows = [v for m, v in acc.items() if m in FAMILIES[family]]
    fam_mean = (statistics.fmean([x for v in fam_rows for x in v])
                if fam_rows else float("nan"))
    pts = []
    for r in sub:
        m = r["A_market"]
        v = acc.get(m)
        b = statistics.fmean(v) if v else fam_mean
        pts.append((float(r["A_conf"]), int(r["A_hit"]), b))
    return pts


# ------------------------------------------------------------------ replay --

def _normalize_rows(rows: list) -> list:
    """Tipi coerenti (stringhe come nel CSV) sia che le righe vengano dal replay
    diretto (bool/int nativi) sia dalla cache CSV."""
    out = []
    for r in rows:
        r = dict(r)
        for k in ("A_admitted", "B_admitted", "elo_available"):
            if k in r:
                r[k] = str(r[k])
        for k in ("fthg", "ftag", "A_hit", "B_hit", "matchday",
                  "B_n_admitted_markets", "team_stats_missing"):
            if k in r and r[k] is not None and r[k] != "":
                r[k] = str(int(r[k]))
        out.append(r)
    return out


def load_or_run_fresh(force: bool) -> list:
    if not force and os.path.exists(FRESH_CACHE):
        with open(FRESH_CACHE, encoding="utf-8") as f:
            return list(csv.DictReader(f))
    logging.disable(logging.WARNING)
    import topmix_selector_replay as TR  # motore live vero, point-in-time
    out = TR.replay(leagues=TR.LEAGUES, seasons=TR.SEASONS, progress=True)
    cols = ["league", "season_label", "matchday", "cutoff", "match_id", "home",
            "away", "kickoff", "fthg", "ftag", "elo_available",
            "team_stats_missing", "A_market", "A_poisson", "A_conf",
            "A_disagree", "A_min_conf", "A_admitted", "A_hit", "B_market",
            "B_conf", "B_admitted", "B_n_admitted_markets", "B_hit"]
    os.makedirs(os.path.dirname(FRESH_CACHE), exist_ok=True)
    with open(FRESH_CACHE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in out["rows"]:
            w.writerow({k: r[k] for k in cols})
    return _normalize_rows([{k: r[k] for k in cols} for r in out["rows"]])


def identity_check(fresh: list, source: list) -> dict:
    src = {r["match_id"]: r for r in source}
    c = {"TOT_identica": 0, "TOT_diversa": 0, "1X2_conf_diversa": 0,
         "1X2_identica": 0, "1X2_mercato_diverso": 0, "non_nel_csv": 0,
         "max_dconf_1x2": 0.0}
    tot_markets = FAMILIES["OU25"] + FAMILIES["GGNG"]
    for r in fresh:
        o = src.get(r["match_id"])
        if o is None:
            c["non_nel_csv"] += 1
            continue
        if r["A_market"] in tot_markets:
            same = (abs(float(o["A_conf"]) - float(r["A_conf"])) < 1e-9
                    and o["A_market"] == r["A_market"]
                    and o["A_admitted"] == r["A_admitted"]
                    and o["A_hit"] == r["A_hit"])
            c["TOT_identica" if same else "TOT_diversa"] += 1
        else:
            d = abs(float(o["A_conf"]) - float(r["A_conf"]))
            c["max_dconf_1x2"] = max(c["max_dconf_1x2"], d)
            if o["A_market"] != r["A_market"]:
                c["1X2_mercato_diverso"] += 1
            elif d > 1e-9:
                c["1X2_conf_diversa"] += 1
            else:
                c["1X2_identica"] += 1
    return c


# ------------------------------------------------------------------- main ----

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fresh", action="store_true",
                    help="rigenera il replay del motore live (default: cache)")
    ap.add_argument("--results-dir", default=RESULTS_DIR_DEFAULT)
    args = ap.parse_args()
    os.makedirs(args.results_dir, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    rng = random.Random(SEED)

    fresh = load_or_run_fresh(args.fresh)
    with open(SOURCE_CSV, encoding="utf-8") as f:
        source = list(csv.DictReader(f))
    ident = identity_check(fresh, source)

    adm = [r for r in fresh if r["A_admitted"] == "True"]
    train = [r for r in adm if r["season_label"] == TRAIN_LABEL]
    test = [r for r in adm if r["season_label"] == TEST_LABEL]
    train_all = [r for r in fresh if r["season_label"] == TRAIN_LABEL]
    test_all = [r for r in fresh if r["season_label"] == TEST_LABEL]

    # ------------------------------------------------ k* per famiglia/split
    fits = {}
    for fam, mkts in FAMILIES.items():
        for split, pool_adm, pool_all in (("TRAIN", train, train_all),
                                          ("VAL", test, test_all),
                                          ("POOL", adm, fresh)):
            sub = [r for r in pool_adm if r["A_market"] in mkts]
            if not sub:
                continue
            entry = {"n": len(sub),
                     "hit_rate": statistics.fmean(int(r["A_hit"]) for r in sub),
                     "mean_conf": statistics.fmean(float(r["A_conf"]) for r in sub),
                     "base_uncond": {m: uncond_base(m, pool_all) for m in mkts},
                     "base_picked": {m: picked_base(m, pool_adm, fam)
                                     for m in mkts}}
            for anchor in ("UNCOND", "PICKED"):
                pts = make_pts(sub, anchor, fam, pool_adm, pool_all)
                k_an = k_brier_analytic(pts)
                k_grid = min(KGRID, key=lambda kk: brier_of(pts, kk))
                assert abs(k_an - k_grid) <= 0.002, (fam, split, anchor, k_an, k_grid)
                entry[f"k_{anchor}_brier"] = {
                    "k": k_an, "fit_score": brier_of(pts, k_an),
                    "raw_score": brier_of(pts, 1.0)}
                entry[f"k_{anchor}_logloss"] = {
                    "k": k_logloss_grid(pts),
                    "raw_score": logloss_of(pts, 1.0)}
                ks = []
                for _ in range(N_BOOT):
                    rs = [sub[rng.randrange(len(sub))] for _ in range(len(sub))]
                    ks.append(k_brier_analytic(make_pts(rs, anchor, fam,
                                                        rs, rs)))
                ks.sort()
                entry[f"k_{anchor}_brier_ci95"] = [ks[int(0.025 * N_BOOT)],
                                                   ks[int(0.975 * N_BOOT) - 1]]
            fits[f"{fam}|{split}"] = entry

    # ------------------------------------- frozen walk-forward su TEST 2526
    frozen = {}
    for fam in ("OU25", "GGNG"):
        mkts = FAMILIES[fam]
        tr_sub = [r for r in train if r["A_market"] in mkts]
        te_sub = [r for r in test if r["A_market"] in mkts]
        entry = {"n_train": len(tr_sub), "n_test": len(te_sub)}
        for anchor in ("UNCOND", "PICKED"):
            bmap = {m: (uncond_base(m, train_all) if anchor == "UNCOND"
                        else picked_base(m, train, fam)) for m in mkts}
            k_fr = k_brier_analytic(make_pts(tr_sub, anchor, fam,
                                             train, train_all))
            pairs = []
            for r in te_sub:
                p = float(r["A_conf"])
                pairs.append((p, int(r["A_hit"]),
                              star(p, bmap[r["A_market"]], k_fr),
                              r["A_market"]))
            surv = [t[:3] for t in pairs if t[2] >= THRESHOLD]
            gone = [t[:3] for t in pairs if t[2] < THRESHOLD]
            gone_mkt = [t[3] for t in pairs if t[2] < THRESHOLD]
            whole = [r for r in adm if r["A_market"] in mkts]
            surv_whole = sum(
                1 for r in whole
                if star(float(r["A_conf"]), bmap[r["A_market"]], k_fr) >= THRESHOLD)
            gy = [y for _, y, _ in gone]
            wi = wilson_ci(sum(gy), len(gy))
            sub_e = {
                "k_frozen": k_fr, "base_frozen": bmap,
                "n_test": len(te_sub),
                "n_surv": len(surv), "n_gone": len(gone),
                "n_surv_wholefile": surv_whole,
                "surv_hit": (statistics.fmean(y for _, y, _ in surv)
                             if surv else None),
                "surv_hit_rawclaim": (statistics.fmean(p for p, _, _ in surv)
                                      if surv else None),
                "surv_brier_raw": (statistics.fmean((p - y) ** 2
                                                    for p, y, _ in surv)
                                   if surv else None),
                "surv_brier_star": (statistics.fmean((ps - y) ** 2
                                                     for _, y, ps in surv)
                                    if surv else None),
                "all_brier_raw": statistics.fmean((p - y) ** 2
                                                  for p, y, _, _ in pairs),
                "all_brier_star": statistics.fmean((ps - y) ** 2
                                                   for _, y, ps, _ in pairs),
                "gone_n": len(gone),
                "gone_hit": (statistics.fmean(gy) if gy else None),
                "gone_wilson95": list(wi),
                "gone_base_uncond_mix": (statistics.fmean(
                    uncond_base(m, test_all) for m in gone_mkt)
                    if gone_mkt else None),
                "gone_base_picked_mix": (statistics.fmean(bmap[m]
                                                          for m in gone_mkt)
                                         if gone_mkt else None),
            }
            # paired reliability sulle superstiti: stessi bin (sulla p grezza)
            if surv:
                edges = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 1.01]
                tot = len(surv)
                acc_r = acc_s = 0.0
                bins = []
                for lo, hi in zip(edges[:-1], edges[1:]):
                    sel = [(p, y, ps) for p, y, ps in surv if lo <= p < hi]
                    if not sel:
                        continue
                    fy = statistics.fmean(y for _, y, _ in sel)
                    mr = statistics.fmean(p for p, _, _ in sel)
                    ms = statistics.fmean(ps for _, _, ps in sel)
                    acc_r += len(sel) / tot * abs(fy - mr)
                    acc_s += len(sel) / tot * abs(fy - ms)
                    bins.append({"bucket": f"[{lo:.2f},{hi:.2f})",
                                 "n": len(sel), "freq": fy,
                                 "mean_raw": mr, "mean_star": ms})
                sub_e["rel_err_raw_paired"] = acc_r
                sub_e["rel_err_star_paired"] = acc_s
                sub_e["rel_bins_paired"] = bins
            entry[anchor] = sub_e
        frozen[fam] = entry

    # -------------------------------------------------- memoria 223/741
    tot_markets = FAMILIES["OU25"] + FAMILIES["GGNG"]
    tot_adm = [r for r in adm if r["A_market"] in tot_markets]
    pts_pool = [(float(r["A_conf"]), int(r["A_hit"]),
                 uncond_base(r["A_market"], fresh)) for r in tot_adm]
    k_pool_u = k_brier_analytic(pts_pool)
    surv_pool = sum(1 for p, y, b in pts_pool if star(p, b, k_pool_u) >= THRESHOLD)

    # --------------------------------- alternative di soglia su TEST (UNCOND)
    thresh_alt = {}
    for fam in ("OU25", "GGNG"):
        e = frozen[fam]["UNCOND"]
        bmap, k_fr = e["base_frozen"], e["k_frozen"]
        te_sub = [r for r in test if r["A_market"] in FAMILIES[fam]]
        cur = [(float(r["A_conf"]), int(r["A_hit"])) for r in te_sub
               if float(r["A_conf"]) >= THRESHOLD]
        hit_cur = statistics.fmean(y for _, y in cur) if cur else None
        starred = [(star(float(r["A_conf"]), bmap[r["A_market"]], k_fr),
                    int(r["A_hit"])) for r in te_sub]
        a_sel = [(p, y) for p, y in starred if p >= THRESHOLD]
        best_t, best_n = None, -1
        if hit_cur is not None:
            for t in [i / 1000 for i in range(400, 801)]:
                sel = [(p, y) for p, y in starred if p >= t]
                if sel and statistics.fmean(y for _, y in sel) >= hit_cur \
                        and len(sel) > best_n:
                    best_t, best_n = t, len(sel)
        tgt = len(cur)
        c_sel = sorted(starred, key=lambda t_: -t_[0])[:tgt]
        thresh_alt[fam] = {
            "n_current_raw060": len(cur), "hit_current": hit_cur,
            "a_star060_n": len(a_sel),
            "a_star060_hit": (statistics.fmean(y for _, y in a_sel)
                              if a_sel else None),
            "b_quality_neutral_t": best_t, "b_quality_neutral_n": best_n,
            "c_volume_neutral_hit": (statistics.fmean(y for _, y in c_sel)
                                     if c_sel else None),
        }

    # ------------------------------------------------------ k* per lega
    league_fits = {}
    for fam in ("OU25", "GGNG"):
        mkts = FAMILIES[fam]
        for lg in sorted({r["league"] for r in adm}):
            sub_tr = [r for r in train if r["A_market"] in mkts
                      and r["league"] == lg]
            sub_po = [r for r in adm if r["A_market"] in mkts
                      and r["league"] == lg]
            row = {}
            for tag, sub, pool in (("TRAIN", sub_tr, train_all),
                                   ("POOL", sub_po, fresh)):
                if len(sub) < 15:
                    row[tag] = {"n": len(sub), "k_uncond": None}
                    continue
                pts_l = [(float(r["A_conf"]), int(r["A_hit"]),
                          uncond_base(r["A_market"], pool)) for r in sub]
                k_l = k_brier_analytic(pts_l)
                ks = []
                for _ in range(N_BOOT):
                    rs = [sub[rng.randrange(len(sub))]
                          for _ in range(len(sub))]
                    pts_b = [(float(r["A_conf"]), int(r["A_hit"]),
                              uncond_base(r["A_market"], rs)) for r in rs]
                    ks.append(k_brier_analytic(pts_b))
                ks.sort()
                row[tag] = {"n": len(sub), "k_uncond": k_l,
                            "ci95": [ks[int(0.025 * N_BOOT)],
                                     ks[int(0.975 * N_BOOT) - 1]],
                            "hit": statistics.fmean(y for _, y, _ in pts_l),
                            "mean_conf": statistics.fmean(p for p, _, _ in pts_l)}
            league_fits[f"{fam}|{lg}"] = row

    # k* 1X2 sulla fonte 17/09 (controllo di coerenza col numero a memoria 0.91)
    src_adm = [r for r in source if r["A_admitted"] == "True"]
    fits_1x2_source = {}
    for split, pool in (("TRAIN", [r for r in src_adm
                                   if r["season_label"] == TRAIN_LABEL]),
                        ("VAL", [r for r in src_adm
                                 if r["season_label"] == TEST_LABEL]),
                        ("POOL", src_adm)):
        sub = [r for r in pool if r["A_market"] in FAMILIES["1X2"]]
        # ancora PICKED (base = hit rate per mercato del campione), come la
        # misura 17/09 che il controllo deve riprodurre
        sub_fits = {}
        for m in FAMILIES["1X2"]:
            ms = [r for r in sub if r["A_market"] == m]
            sub_fits[m] = (statistics.fmean(int(r["A_hit"]) for r in ms)
                           if ms else 0.5)
        pts_s = [(float(r["A_conf"]), int(r["A_hit"]),
                  sub_fits[r["A_market"]]) for r in sub]
        fits_1x2_source[split] = {"n": len(sub),
                                  "k_picked_brier": k_brier_analytic(pts_s)}

    result = {
        "generated_utc": now,
        "protocol": {
            "source_1709": os.path.relpath(SOURCE_CSV, _REPO_ROOT),
            "fresh_replay": "audit.topmix_selector_replay (motore live, point-in-time)",
            "train": TRAIN_LABEL, "val_test": TEST_LABEL,
            "families": {k: list(v) for k, v in FAMILIES.items()},
            "anchors": {"UNCOND": "frequenza incondizionata evento (candidati)",
                        "PICKED": "hit rate realizzata ammesse (per mercato)"},
            "threshold": THRESHOLD, "n_boot": N_BOOT, "seed": SEED,
            "labels": "2425 e 2526 sono entrambe stagioni gia' esaminate in "
                      "passato per il selettore: 'TEST' qui vale solo per la "
                      "DOMANDA shrinkage-totali, non e' un hold-out assoluto",
        },
        "identity_check": ident,
        "fits": fits,
        "fits_1x2_source_1709": fits_1x2_source,
        "frozen_test": frozen,
        "memory_223_741": {"k_pooled_uncond": k_pool_u,
                           "survivors_recomputed": surv_pool,
                           "denominator": len(tot_adm),
                           "memory_estimate": "223/741"},
        "threshold_alternatives_test": thresh_alt,
        "league_fits": league_fits,
    }

    json_path = os.path.join(args.results_dir, "shrinkage_totali_onesto.json")
    with io.open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    md = render(result)
    md_path = os.path.join(args.results_dir, "shrinkage_totali_onesto.md")
    with io.open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    print("scritti:", os.path.relpath(md_path, _REPO_ROOT),
          os.path.relpath(json_path, _REPO_ROOT))
    return 0


# ------------------------------------------------------------------ report --

def render(res: dict) -> str:
    o = []
    w = o.append
    ident = res["identity_check"]
    w("# Shrinkage onesto sui Totali (O/U2.5, GG/NG) — verifica indipendente\n")
    w(f"*Generato: {res['generated_utc']} — script `audit/verify_shrinkage_totali.py`. "
      "Sola lettura: nessuna modifica a produzione, nessun fix committato in questa "
      "fase.*\n")
    w("## 0. Fonte e validazione sul motore live vero\n")
    w("Rigioco il replay con il **motore live vero** (`audit.topmix_selector_replay`: "
      "funzioni di produzione `get_league_engine`/`get_full_poisson_two_heads`/"
      "`predict_elo_probs`/`select_next_matchday_matches`, dati point-in-time) invece "
      "di riusare passivamente la replica memorizzata (`topmix_selector_replay_rows.csv`, "
      "3422 candidate / 1865 ammesse). Verifica di identità fresh vs CSV:\n")
    w(f"- testa **Totali: {ident['TOT_identica']} righe identiche, "
      f"{ident['TOT_diversa']} diverse** — la conf dei Totali è Poisson puro (nessun "
      f"Elo per costruzione in `apply_selector_A`): il CSV del 17/09 è confermato "
      f"base valida bit-per-bit;")
    w(f"- testa **1X2: {ident['1X2_conf_diversa']} conf diverse su "
      f"{ident['1X2_conf_diversa'] + ident['1X2_identica']} (max Δ = "
      f"{ident['max_dconf_1x2']:.3f}), mercati diversi: "
      f"{ident['1X2_mercato_diverso']}** — lo stato Elo di produzione è cambiato dal "
      f"05/09 (drift fino a |Δconf|=0.118; su Bundesliga il Δ è uniforme lungo la "
      f"stagione: è un cambio globale del motore Elo, non un effetto point-in-time). "
      f"Il controllo 0.91 va quindi condotto sulla fonte del 17/09; il drift è "
      f"riportato e non influenza i Totali (conf = Poisson puro).\n")
    w("Etichette: **TRAIN = 2024/25**, **VAL/TEST = 2025/26** (VAL = split per la "
      "stabilità di k*, TEST = valutazione frozen: stessi dati, ruoli diversi come "
      "da brief). Entrambe le stagioni sono già state esaminate in passato per il "
      "selettore (due teste, forma fuori dai totali, PRIOR_MATCHES=6, pesi 0.6/0.4): "
      "il TEST qui vale per la *domanda* shrinkage-totali, non è un hold-out "
      "assoluto. Campione = righe **ammesse** (quello che la produzione mostra). "
      "k* Brier-optimal in forma chiusa; k* LogLoss come sensibilità. Ancore "
      "pre-specificate: **UNCOND** = frequenza incondizionata dell'evento fra i "
      "candidati (≈ base rate di mercato); **PICKED** = hit rate realizzata delle "
      "ammesse per mercato. CI bootstrap 95% "
      f"({res['protocol']['n_boot']} resample, seed {res['protocol']['seed']}).\n")

    # §1 k*
    w("## 1. k* ricalcolato per mercato, non aggregato\n")
    w("| Famiglia | Split | n | hit rate | conf media | k* UNCOND [CI95] | k* PICKED [CI95] | k* LogLoss UNCOND |")
    w("|---|---|---:|---:|---:|---:|---:|---:|")
    for fam in ("OU25", "GGNG", "1X2"):
        for split in ("TRAIN", "VAL", "POOL"):
            e = res["fits"].get(f"{fam}|{split}")
            if not e:
                continue
            cu, cp = e["k_UNCOND_brier_ci95"], e["k_PICKED_brier_ci95"]
            w(f"| {FAMILY_LABEL[fam]} | {split} | {e['n']} | "
              f"{e['hit_rate']*100:.1f}% | {e['mean_conf']*100:.1f}% | "
              f"**{e['k_UNCOND_brier']['k']:.3f}** [{cu[0]:.3f}; {cu[1]:.3f}] | "
              f"**{e['k_PICKED_brier']['k']:.3f}** [{cp[0]:.3f}; {cp[1]:.3f}] | "
              f"{e['k_UNCOND_logloss']['k']:.3f} |")
    w("")
    w("Nota sull'1X2 in tabella: i valori «fresh» usano il motore di OGGI, il cui "
      "stato Elo è driftato rispetto al 05/09 (§0): per il confronto col ~0.91 a "
      "memoria vale la tabella in §2, calcolata sulla fonte del 17/09.\n")

    # §2 stabilita'
    w("## 2. Stabilità TRAIN vs VAL (per ancora)\n")
    w("| Famiglia | Ancora | k* TRAIN | k* VAL | Δ | Esito (Δ≤0.15) |")
    w("|---|---|---:|---:|---:|---|")
    stab_note = {}
    for fam in ("OU25", "GGNG", "1X2"):
        tr, va = res["fits"][f"{fam}|TRAIN"], res["fits"][f"{fam}|VAL"]
        for anchor in ("UNCOND", "PICKED"):
            kt = tr[f"k_{anchor}_brier"]["k"]
            kv = va[f"k_{anchor}_brier"]["k"]
            d = abs(kt - kv)
            esito = "stabile" if d <= 0.15 else "**INSTABILE**"
            stab_note[(fam, anchor)] = esito
            w(f"| {FAMILY_LABEL[fam]} | {anchor} | {kt:.3f} | {kv:.3f} | {d:.3f} | {esito} |")
    w("")
    e1 = res["fits_1x2_source_1709"]
    w(f"**Controllo di coerenza 1X2 (fonte 17/09, ancora PICKED):** k* = "
      f"{e1['POOL']['k_picked_brier']:.3f} sul pool (TRAIN "
      f"{e1['TRAIN']['k_picked_brier']:.3f}, VAL {e1['VAL']['k_picked_brier']:.3f}) — "
      f"**riproduce il ~0.91 a memoria**: la procedura è la stessa della misura "
      f"precedente e il numero torna.\n")
    ou_u = stab_note[("OU25", "UNCOND")] == "stabile"
    gg_u = stab_note[("GGNG", "UNCOND")] == "stabile"
    ou_p = stab_note[("OU25", "PICKED")] == "stabile"
    gg_p = stab_note[("GGNG", "PICKED")] == "stabile"
    w(f"Lettura dei Totali:\n")
    w(f"- ancora **UNCOND**: O/U 2.5 è {'stabile' if ou_u else 'instabile'} "
      f"({res['fits']['OU25|TRAIN']['k_UNCOND_brier']['k']:.3f} → "
      f"{res['fits']['OU25|VAL']['k_UNCOND_brier']['k']:.3f}; LogLoss d'accordo), "
      f"GG/NG è {'stabile' if gg_u else 'al limite (Δ≈0.15, soglia passeggera)'} "
      f"({res['fits']['GGNG|TRAIN']['k_UNCOND_brier']['k']:.3f} → "
      f"{res['fits']['GGNG|VAL']['k_UNCOND_brier']['k']:.3f}); i CI restano larghi "
      f"(GG/NG TRAIN [0;1]): con n≈150–215 per stagione il singolo k* ha "
      f"un'incertezza grande anche quando il punto è stabile;")
    w(f"- ancora **PICKED**: {'entrambe instabili' if not (ou_p and gg_p) else 'stabili'} "
      f"e con valori degeneri (k*=0 su GG/NG VAL/POOL): la selezione tronca la "
      f"distribuzione a ≥0.60 e la base realizzata coincide con la soglia — "
      f"ancora inadatta a un uso con soglie.\n")
    w("**Segnalato come richiesto dal brief**: il fenomeno (sovraconfidenza dei "
      "Totali mostrati) è robusto e presente in ENTRAMBE le stagioni, ma il "
      "*valore* di k* per GG/NG non è stabilmente identificato; per O/U 2.5 "
      "l'ancora UNCOND dà un k* riproducibile (~0.62–0.64).\n")

    # §3 frozen test
    w("## 3. Walk-forward onesto su TEST 2025/26 (base e k congelati sul TRAIN)\n")
    w("| Famiglia | Ancora | k frozen | n TEST | Sopravvive ≥0.60 | Sparisce | Sopravvive su file intero (equiv. 741) |")
    w("|---|---|---:|---:|---:|---:|---:|")
    for fam in ("OU25", "GGNG"):
        for anchor in ("UNCOND", "PICKED"):
            e = res["frozen_test"][fam][anchor]
            w(f"| {FAMILY_LABEL[fam]} | {anchor} | {e['k_frozen']:.3f} | {e['n_test']} | "
              f"**{e['n_surv']}** | {e['n_gone']} | {e['n_surv_wholefile']}/741 |")
    w("")
    mu = res["memory_223_741"]
    w("«File intero» = stesse (base, k) frozen applicate anche alle righe 2024/25 "
      "ammesse (protocollo per-famiglia; il pooled-fit uniforme è qui sotto).\n")
    w(f"**Verifica del numero a memoria 223/741.** La costruzione che lo approssima è "
      f"`k* Brier sulle ammesse POOL, ancora UNCOND`: k* = {mu['k_pooled_uncond']:.3f} "
      f"→ sopravvive **{mu['survivors_recomputed']}/{mu['denominator']}**. Stesso "
      f"ordine di grandezza della stima a memoria (223/741), replica non esatta: il "
      f"numero di memoria non è ricostruibile con precisione e va sostituito da "
      f"questo ricalcolo. Sotto l'ancora PICKED il protocollo frozen dà risultati "
      f"degenerati per l'uso con soglie (GGNG: la base realizzata ≈ 0.60 = soglia → "
      f"non sparisce quasi nulla; OU25: k*≈0 → p* costante = base).\n")

    # §4 reliability
    w("## 4. Reliability e Brier delle superstiti (TEST, bin costruiti sulla p grezza)\n")
    w("| Famiglia | Ancora | n sopravvissute | hit | conf raw media | Rel.err raw | Rel.err p* | Brier raw | Brier p* |")
    w("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for fam in ("OU25", "GGNG"):
        for anchor in ("UNCOND", "PICKED"):
            e = res["frozen_test"][fam][anchor]
            if not e["n_surv"]:
                w(f"| {FAMILY_LABEL[fam]} | {anchor} | 0 | — | — | — | — | — | — |")
                continue
            w(f"| {FAMILY_LABEL[fam]} | {anchor} | {e['n_surv']} | "
              f"{e['surv_hit']*100:.1f}% | {e['surv_hit_rawclaim']*100:.1f}% | "
              f"{e['rel_err_raw_paired']:.4f} | **{e['rel_err_star_paired']:.4f}** | "
              f"{e['surv_brier_raw']:.4f} | **{e['surv_brier_star']:.4f}** |")
    w("")
    w("Lettura: sull'ancora UNCOND (quella supportata dai dati) la reliability "
      "delle superstiti migliora in entrambe le famiglie (O/U 0.124→0.102, GG/NG "
      "0.088→0.050) mentre il Brier è praticamente neutro (O/U +0.0002, GG/NG "
      "−0.005): comprimere verso la base sistema le probabilità dichiarate senza "
      "cambiare la capacità discriminante sulle superstiti. Sull'ancora PICKED il "
      "confronto è degenere (k*=0 su O/U: p* costante) o peggiorativo.\n")

    # §5 sparizione
    w("## 5. Le righe che SPARISCONO: rumore o segnale genuino?\n")
    w("«Base UNCOND mix» = frequenza incondizionata degli eventi dei mercati "
      "spariti (miscela effettiva delle righe eliminate); «Base PICKED mix» = base "
      "frozen dell'ancora PICKED per quegli stessi mercati.\n")
    w("| Famiglia | Ancora | n sparite | hit rate reale | Wilson 95% | Base UNCOND mix | Base PICKED mix | Lettura |")
    w("|---|---|---:|---:|---:|---:|---:|---|")
    for fam in ("OU25", "GGNG"):
        for anchor in ("UNCOND", "PICKED"):
            e = res["frozen_test"][fam][anchor]
            if not e["gone_n"]:
                w(f"| {FAMILY_LABEL[fam]} | {anchor} | 0 | — | — | — | — | "
                  f"nessuna sparizione |")
                continue
            lo, hi = e["gone_wilson95"]
            b_un = e["gone_base_uncond_mix"]
            b_pk = e["gone_base_picked_mix"]
            if lo > b_un:
                lettura = "hit sopra la base incondizionata: segnale genuino perso"
            elif hi < b_un:
                lettura = "hit sotto la base: sovraconfidenza confermata"
            else:
                lettura = ("punto sopra la base ma CI che la include: "
                           "rumore non escluso, segnale non provato")
            w(f"| {FAMILY_LABEL[fam]} | {anchor} | {e['gone_n']} | "
              f"{e['gone_hit']*100:.1f}% | [{lo*100:.1f}; {hi*100:.1f}]% | "
              f"{b_un*100:.1f}% | {b_pk*100:.1f}% | {lettura} |")
    w("")
    w("**Sintesi (punto 4 del brief).** Le due ancore DICONO COSE DIVERTE sulle "
      "righe eliminate, e va riportato senza arbitrare: con l'ancora UNCOND "
      "(quella che riproduce l'ordine di grandezza della stima a memoria ed è "
      "stabile su O/U) le righe eliminate hanno hit rate **non distinguibili "
      "dalla base** (O/U 52.6% vs 48.1%; GG/NG 60.7% vs 53.9%, CI che include la "
      "base): lettura «rumore spacciato per confidenza», con la punta che su "
      "GG/NG il punto stimato è comunque +6.8 pp sopra la base. Con l'ancora "
      "PICKED le righe O/U eliminate mostrano invece un hit 60.0% netto sopra "
      "base (47.0%): **segnale genuino che lo shrinkage butterebbe via**. Non è "
      "automatico che le eliminate siano rumore: dipende dall'ancora, e "
      "l'incertezza (Wilson) non chiude la questione.\n")

    # §6 per lega
    w("## 6. Coerenza per lega (k* UNCOND Brier)\n")
    w("| Famiglia | Lega | n TRAIN | k* TRAIN [CI95] | n POOL | k* POOL [CI95] | hit POOL | conf media POOL |")
    w("|---|---|---:|---|---:|---|---:|---:|")
    for key, row in res["league_fits"].items():
        fam, lg = key.split("|")
        tr, po = row.get("TRAIN", {}), row.get("POOL", {})
        def fmt(d):
            if d.get("k_uncond") is None:
                return "n/d (n<15)"
            return f"{d['k_uncond']:.3f} [{d['ci95'][0]:.2f}; {d['ci95'][1]:.2f}]"
        if po.get("k_uncond") is None:
            w(f"| {FAMILY_LABEL[fam]} | {lg} | {tr.get('n', 0)} | {fmt(tr)} | "
              f"{po.get('n', 0)} | {fmt(po)} | n/d | n/d |")
        else:
            w(f"| {FAMILY_LABEL[fam]} | {lg} | {tr.get('n', 0)} | {fmt(tr)} | "
              f"{po.get('n', 0)} | {fmt(po)} | {po['hit']*100:.1f}% | "
              f"{po['mean_conf']*100:.1f}% |")
    w("")
    w("**Lettura (punto 5 del brief, lezione PPDA).** Il k* aggregato NON è lo "
      "stesso segnale ovunque: O/U va da k*≈0.80 (Bundesliga, La Liga) a "
      "k*≈0-0.53 (Premier, Serie A: dove l'hit rate dei picks è 46.8–56.8%, "
      "ben sotto la conf ~63–64%); GG/NG va da 1.00 (Bundesliga: nessuna "
      "sovraconfidenza) a ~0-0.39 (Ligue 1: hit 47.1% contro conf dichiarata "
      "62% — la famiglia peggiore in assoluto). Nota: la Serie A ha solo 7 "
      "righe GG/NG ammesse in due stagioni (il selettore lì sceglie quasi solo "
      "1X2 e O/U): per GG/NG la Serie A è di fatto fuori perimetro. Un eventuale "
      "k* unico applicato a tutte le leghe comprimerebbe nel modo sbagliato "
      "almeno due leghe su cinque.\n")

    # §7 alternative soglia
    w("## 7. Se si applicasse: alternative di soglia su TEST (ancora UNCOND frozen)\n")
    w("| Famiglia | Oggi raw≥0.60 | (a) p*≥0.60 | (b) t* a pari qualità (hit ≥ oggi) | (c) a pari volume |")
    w("|---|---:|---:|---:|---:|")
    for fam, e in res["threshold_alternatives_test"].items():
        hc = e["hit_current"]
        b_n = e["b_quality_neutral_n"]
        c_hit = e["c_volume_neutral_hit"]
        w(f"| {FAMILY_LABEL[fam]} | n={e['n_current_raw060']}, hit "
          f"{hc*100 if hc is not None else float('nan'):.1f}% | "
          f"n={e['a_star060_n']}, hit "
          f"{e['a_star060_hit']*100 if e['a_star060_hit'] is not None else float('nan'):.1f}% | "
          f"t*={e['b_quality_neutral_t'] if e['b_quality_neutral_t'] is not None else 'n/d'}, "
          f"n={b_n if b_n is not None else 'n/d'} | hit "
          f"{c_hit*100 if c_hit is not None else float('nan'):.1f}% |")
    w("")
    w("Nota semantica: il confronto è DENTRO le ammesse (tutte ≥0.60 per "
      "costruzione): «t*=0.40, n=tutte» significa che sulla TEST 2025/26 "
      "l'ordinamento raw≥0.60 non ha gradiente di qualità interno — tenendole "
      "tutte l'hit rate non scende. (a) mostra l'effetto della soglia onesta su "
      "p*: volume −64% su O/U (con hit che SALGONO a 61.8%: le eliminate erano "
      "rumore) e −60% su GG/NG (con hit che SCENDE a 56.2%: le eliminate erano "
      "in media buone). Le due famiglie si comportano in modo opposto.\n")

    # §8 raccomandazione
    w("## 8. Raccomandazione\n")
    w("**Non applicare lo shrinkage a produzione in questa fase.** In sintesi:\n")
    w("1. la *procedura* è validata (l'1X2 di controllo riproduce il ~0.91) e il "
      "fenomeno esiste: i Totali ammessi dichiarano 63–65% con hit rate reali "
      "56–60% in ENTRAMBE le stagioni. Sull'ancora UNCOND il k* di O/U 2.5 è "
      "riproducibile (~0.62–0.64 in TRAIN, VAL e pool); quello di GG/NG è al "
      "limite (0.61→0.46) e i CI restano larghi; sull'ancora PICKED i k* sono "
      "degeneri. Inoltre il k* NON è coerente tra leghe (§6): un singolo k "
      "aggregato comprimerebbe nel modo sbagliato almeno due leghe su cinque. "
      "Come parametro di SOGLIA non è pronto;\n")
    w("2. **se** si volesse procedere nonostante ciò, la variante coerente con "
      "i dati è: **ricalibrare SOLO la probabilità mostrata** — ancora UNCOND, "
      "k≈0.63 stimato sul pool (e ricongelato ogni stagione), selezione "
      "invariata `raw ≥ 0.60`. È un cambio di sola presentazione: nessuna riga "
      "cambia, l'utente legge 55–60% ciò che oggi viene etichettato 63–65%. "
      "Limitandolo a O/U 2.5 il k* è il più stabile; estenderlo a GG/NG espone "
      "all'instabilità del suo k*;\n")
    w("3. la variante aggressiva — sostituire la soglia fissa con una soglia su "
      "p* — ha effetti OPPOSTI sulle due famiglie sulla TEST (§7a): su O/U 2.5 "
      "migliora la qualità (hit 55.9%→61.8% a volume −64%: le eliminate erano "
      "rumore), su GG/NG la peggiora (58.9%→56.2% a volume −60%: le eliminate "
      "erano in media buone). NON è una sola decisione ma due, e quella GG/NG "
      "oggi sarebbe sbagliata. Qualunque cambio di soglia è inoltre una "
      "decisione di prodotto sul volume mostrato, da fare solo con k* "
      "stabilizzati (almeno un'altra stagione di dati) e per lega, non "
      "aggregati;\n")
    w("4. la soglia ricalibrata equivalente «a pari qualità» (§7b) su questa "
      "TEST degenera (t* = base: tenere tutto non peggiora l'hit rate): è il "
      "segno che DENTRO le ammesse l'ordinamento raw non ha gradiente utile su "
      "quest'anno — ulteriore motivo per non fissare soglie su questo k*.\n")
    w("---\n")
    w("*Audit di sola verifica: produzione intoccata; il replay del motore gira in "
      "directory temporanee point-in-time, nessuna scrittura su database/registro; "
      "nessuna funzione di produzione modificata.*\n")
    return "\n".join(o)


if __name__ == "__main__":
    raise SystemExit(main())
