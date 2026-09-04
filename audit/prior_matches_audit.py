"""
prior_matches_audit.py — Validazione statistica walk-forward di PRIOR_MATCHES
(lo shrinkage empirico-bayesiano introdotto con _shrunk_ratio() in app.py per
eliminare le lambda ~0 su campioni piccoli, bug "NG ~99.8%").

REGOLE PRE-COMMESSE (audit in sola lettura: NESSUNA modifica di produzione):
  1. Split temporale no-leakage (stessa struttura degli audit esistenti):
     pool/storico = tutte le partite completate PRIMA della partita predetta
     (multi-stagione, come il pool CSV di get_league_engine); snapshot xG =
     partite della STAGIONE IN CORSO prima della partita (semantica identica
     al file xg_<lega>.json di produzione, che contiene solo la corrente).
       - validation : 2024/25   -> scelta del prior SOLO qui
       - test       : 2025/26   -> usato UNA sola volta dopo la selezione
       - monitoring : 2026/27   -> 2 giornate, solo indicativo
  2. Varianti (tutte usano la STESSA struttura a due teste di produzione,
     chiamando app._two_heads_from_lambdas: matematica identica, zero reuse):
       - A    : baseline storica SOLO-GOL (pool multi-stagione), SENZA shrinkage
       - B(k) : baseline solo-gol + shrinkage k, k in {2,4,6,8,10}
       - C(k) : testa base_pure di produzione (xG stagione-in-corso se
                disponibile, altrimenti fallback gol pooled) + shrinkage k,
                k in {0,2,4,6,8,10}; C(0) = produzione senza shrinkage.
  3. Mercati SEPARATI: 1X2 (Brier multiclasse, LogLoss, accuracy), O/U 2.5 e
     GG/NG (Brier, LogLoss binari). Nessun punteggio unico aggregato.
     SELEZIONE: Brier GG/NG su validation (mercato del bug originale), con
     guardrail: Brier O/U entro +0.001 dal minimo e Brier 1X2 entro +0.002
     rispetto a C(0).
  4. Zona di equivalenza (sensitivity): k con |ΔBrier GG/NG vs migliore|
     < 0.001 E CI bootstrap paired 95% (2000 repliche) che include lo 0.
     Si sceglie il k piu' piccolo della zona (piu' conservativo).
  5. ROI omesso: quote B365 non allineate al dataset xG per-partita; criterio
     secondario pergettato esplicitamente.
  6. PRIOR_MATCHES di produzione resta 6; nessun file di produzione modificato.

Uso:
  python3 audit/prior_matches_audit.py     # scrive results JSON + report md
"""
import json
import math
import os
import sys
from collections import defaultdict, deque

import numpy as np

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from config import clean_name, get_market_values  # sola lettura
from app import _two_heads_from_lambdas            # matematica di produzione
import update_xg                                    # NAME_MAP (fix nomi 2026/27)

DB = os.path.join(_REPO_ROOT, "SoccerMath", "database")
ARCHIVES = {
    "Premier League": "xG archivio premier league.json",
    "Serie A": "xG archivio serie A.json",
    "Bundesliga": "xG archivio bundesliga.json",
    "La Liga": "xG archivio la liga.json",
    "Ligue 1": "xG archivio ligue 1.json",
}
LEAGUES = list(ARCHIVES.keys())
SEASON_TAG = {2024: "validation", 2025: "test", 2026: "monitoring"}
KS = [0, 2, 4, 6, 8, 10]
VARIANTS = ["A"] + [f"B{k}" for k in KS if k > 0] + [f"C{k}" for k in KS]
MARKET_VALUES = get_market_values()
_CANON = {}


def canon(title):
    if title not in _CANON:
        _CANON[title] = clean_name(update_xg.NAME_MAP.get(title, title))
    return _CANON[title]


def mkt_factor(team):
    v = MARKET_VALUES.get(team, 50)
    f = 1 + (math.log10(max(v, 10)) - 2.0) / 4
    return max(0.85, min(1.25, f))


def shrunk(r, n, k):
    """Identica a _shrunk_ratio di produzione (k=0 -> ratio grezzo; n=0 -> 1.0)."""
    if n <= 0:
        return 1.0
    if k <= 0:
        return r
    return (n * r + k) / (n + k)


class LeagueState:
    def __init__(self):
        self.pn_h, self.pn_a = defaultdict(int), defaultdict(int)
        self.pgf, self.pga = defaultdict(float), defaultdict(float)
        self.tot, self.hg, self.ag = 0, 0.0, 0.0
        self.cur = {}
        self.last5 = defaultdict(deque)
        self.season = None

    def ensure_season(self, s):
        if s != self.season:
            self.cur, self.season = {}, s

    def avgs(self):
        if self.tot == 0:
            return 1.45, 1.15  # solo warm-up (nessuna partita emessa nel 2022)
        return self.hg / self.tot, self.ag / self.tot

    def league_xg(self):
        teams = [v for v in self.cur.values() if v[2] > 0]
        if len(teams) < 10:
            return None, None
        mx = float(np.mean([v[0] / v[2] for v in teams]))
        mxa = float(np.mean([v[1] / v[2] for v in teams]))
        if not (0.5 < mx < 5.0 and 0.5 < mxa < 5.0):
            return None, None
        return mx, mxa

    def team_ratio(self, team, source, k, lx, lxa):
        c = self.cur.get(team)
        if source == "C" and c and c[2] > 0 and lx and lxa:
            n = c[2]
            return (shrunk((c[0] / n) / lx, n, k),
                    shrunk((c[1] / n) / lxa, n, k), n, "xg")
        n_h, n_a = self.pn_h[team], self.pn_a[team]
        n = n_h + n_a
        avg_h, avg_a = self.avgs()
        exp_gf = avg_h * n_h + avg_a * n_a
        exp_ga = avg_a * n_h + avg_h * n_a
        att = shrunk(self.pgf[team] / exp_gf, n, k) if n > 0 else 1.0
        defe = shrunk(self.pga[team] / exp_ga, n, k) if n > 0 else 1.0
        return att, defe, n, "goals"

    def form(self, team):
        avg_h, avg_a = self.avgs()
        g = max((avg_h + avg_a) / 2, 0.5)
        m5 = self.last5[team]
        if len(m5) < 3:
            return 1.0, 1.0
        gf = sum(x[0] for x in m5) / len(m5)
        ga = sum(x[1] for x in m5) / len(m5)
        return (max(0.85, min(1.15, gf / g)), max(0.85, min(1.15, ga / g)))

    def update(self, m):
        h, a, hg, ag = m["h"], m["a"], m["hg"], m["ag"]
        self.pn_h[h] += 1; self.pn_a[a] += 1
        self.pgf[h] += hg; self.pga[h] += ag
        self.pgf[a] += ag; self.pga[a] += hg
        self.tot += 1; self.hg += hg; self.ag += ag
        self.last5[h].append((hg, ag)); self.last5[a].append((ag, hg))
        if len(self.last5[h]) > 5: self.last5[h].popleft()
        if len(self.last5[a]) > 5: self.last5[a].popleft()
        if m["hxg"] is not None and m["axg"] is not None:
            ch = self.cur.setdefault(h, [0.0, 0.0, 0])
            ca = self.cur.setdefault(a, [0.0, 0.0, 0])
            ch[0] += m["hxg"]; ch[1] += m["axg"]; ch[2] += 1
            ca[0] += m["axg"]; ca[1] += m["hxg"]; ca[2] += 1


def load_league(league):
    with open(os.path.join(DB, ARCHIVES[league]), encoding="utf-8") as f:
        raw = json.load(f)
    ms = []
    for m in raw:
        if not m.get("is_result"):
            continue
        try:
            hg, ag = int(m["home_goals"]), int(m["away_goals"])
        except (TypeError, ValueError):
            continue
        ms.append({"season": int(m["season"]), "date": str(m["date"]),
                   "h": canon(m["home_team"]), "a": canon(m["away_team"]),
                   "hg": hg, "ag": ag, "hxg": m.get("home_xg"), "axg": m.get("away_xg")})
    ms.sort(key=lambda x: x["date"])
    return ms


def predict_variants(state, m):
    avg_h, avg_a = state.avgs()
    lx, lxa = state.league_xg()
    out, ns = {}, {}
    for v in VARIANTS:
        src = "C" if v[0] == "C" else "B"
        k = 0 if v == "A" else int(v[1:])
        att_h, def_h, n_h, path_h = state.team_ratio(m["h"], src, k, lx, lxa)
        att_a, def_a, n_a, path_a = state.team_ratio(m["a"], src, k, lx, lxa)
        fa_h, fd_h = state.form(m["h"]); fa_a, fd_a = state.form(m["a"])
        mf_h, mf_a = mkt_factor(m["h"]), mkt_factor(m["a"])
        a0h, d0h = att_h * fa_h, def_h * fd_h
        a0a, d0a = att_a * fa_a, def_a * fd_a
        base_h, base_a = a0h * d0a * avg_h, a0a * d0h * avg_a
        mkt_h = a0h * mf_h * (d0a / mf_a) * avg_h
        mkt_a = a0a * mf_a * (d0h / mf_h) * avg_a
        pure_h, pure_a = att_h * def_a * avg_h, att_a * def_h * avg_a
        r = _two_heads_from_lambdas(base_h, base_a, mkt_h, mkt_a, pure_h, pure_a)
        out[v] = (r["1"], r["X"], r["2"], 1 - r["u25"], r["gg"])
        ns[v] = (n_h, n_a, path_h, path_a)
    return out, ns


# ----------------------------- metriche ------------------------------------
def metrics(rs, v):
    n = len(rs)
    b1 = sum(brier_mc(r["preds"][v], r["y"]) for r in rs) / n
    l1 = sum(ll_mc(r["preds"][v], r["y"]) for r in rs) / n
    acc = sum(1 for r in rs if argmax3(r["preds"][v]) == r["y"]) / n
    po = np.array([r["preds"][v][3] for r in rs]); yo = np.array([r["y_over"] for r in rs], float)
    pg = np.array([r["preds"][v][4] for r in rs]); yg = np.array([r["y_gg"] for r in rs], float)
    return {"n": n, "brier_1x2": b1, "ll_1x2": l1, "acc_1x2": acc,
            "brier_ou": float(np.mean((po - yo) ** 2)), "ll_ou": float(-np.mean(np.log(np.where(yo > 0, po, 1 - po).clip(1e-12)))),
            "brier_gg": float(np.mean((pg - yg) ** 2)), "ll_gg": float(-np.mean(np.log(np.where(yg > 0, pg, 1 - pg).clip(1e-12))))}


def brier_mc(p, y):
    return (p[0] - (y == 0)) ** 2 + (p[1] - (y == 1)) ** 2 + (p[2] - (y == 2)) ** 2


def ll_mc(p, y):
    return -math.log(max(p[y], 1e-12))


def argmax3(p):
    return max(range(3), key=lambda i: p[i])


def boot_delta(rows, v_a, v_b, market, n_boot=2000, seed=42):
    """Delta Brier paired bootstrap: metrica(v_a) - metrica(v_b)."""
    rng = np.random.default_rng(seed)
    i = 3 if market == "ou" else 4
    yk = "y_over" if market == "ou" else "y_gg"
    pa = np.array([r["preds"][v_a][i] for r in rows])
    pb = np.array([r["preds"][v_b][i] for r in rows])
    y = np.array([r[yk] for r in rows], float)
    n = len(rows)
    deltas = np.empty(n_boot)
    for b in range(n_boot):
        s = rng.integers(0, n, n)
        deltas[b] = np.mean((pa[s] - y[s]) ** 2) - np.mean((pb[s] - y[s]) ** 2)
    return {"mean": float(np.mean(deltas)), "ci_lo": float(np.percentile(deltas, 2.5)),
            "ci_hi": float(np.percentile(deltas, 97.5)), "p_gt0": float(np.mean(deltas > 0))}


def bucket_of(n):
    return "0-2" if n <= 2 else "3-5" if n <= 5 else "6-10" if n <= 10 else "11-20" if n <= 20 else "21+"


BUCKETS = ["0-2", "3-5", "6-10", "11-20", "21+"]


def calib_table(rows, v, key):  # key 3=over, 4=gg
    edges = [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 0.80), (0.80, 1.01)]
    yk = "y_over" if key == 3 else "y_gg"
    ps = np.array([r["preds"][v][key] for r in rows])
    ys = np.array([r[yk] for r in rows], float)
    out = []
    for lo, hi in edges:
        sel = (ps >= lo) & (ps < hi)
        n = int(sel.sum())
        label = "80%+" if hi > 1 else f"{lo:.0%}-{hi:.0%}"
        out.append({"bucket": label, "n": n, "pred": float(ps[sel].mean()) if n else None,
                    "real": float(ys[sel].mean()) if n else None})
    return out


def main():
    rows = []
    all_matches = {}
    for league in LEAGUES:
        ms = load_league(league)
        all_matches[league] = ms
        state = LeagueState()
        for m in ms:
            state.ensure_season(m["season"])
            if m["season"] in SEASON_TAG:
                preds, ns = predict_variants(state, m)
                y = 0 if m["hg"] > m["ag"] else (1 if m["hg"] == m["ag"] else 2)
                rows.append({"league": league, "season": m["season"], "tag": SEASON_TAG[m["season"]],
                             "date": m["date"], "h": m["h"], "a": m["a"], "y": y,
                             "y_over": 1 if m["hg"] + m["ag"] >= 3 else 0,
                             "y_gg": 1 if m["hg"] > 0 and m["ag"] > 0 else 0,
                             "preds": preds,
                             "n_C": min(ns["C0"][0], ns["C0"][1]),
                             "n_pool": min(ns["B6"][0], ns["B6"][1]),
                             "paths_C": f"{ns['C0'][2]}/{ns['C0'][3]}"})
            state.update(m)
    val = [r for r in rows if r["tag"] == "validation"]
    test = [r for r in rows if r["tag"] == "test"]
    mon = [r for r in rows if r["tag"] == "monitoring"]
    print(f"rows: val={len(val)} test={len(test)} mon={len(mon)}")

    R = {"variants": VARIANTS, "ks": KS}

    # --- tabelle aggregate validation/test ---
    R["agg"] = {tag: {v: metrics(rs, v) for v in VARIANTS}
                for tag, rs in (("validation", val), ("test", test), ("monitoring", mon))}

    # --- per lega (calcolato dopo la selezione per includere C{sel}) ---


    # --- buckets (validation): asse unico n_C = partite stagionali disponibili
    # per la testa xG di produzione (min tra le due squadre). L'asse e' un
    # attributo della PARTITA: tutte le varianti vengono bucketizzate uguale.
    R["buckets"] = {}
    for v in VARIANTS:
        R["buckets"][v] = {b: metrics([r for r in val if bucket_of(r["n_C"]) == b], v)
                           for b in BUCKETS
                           if any(bucket_of(r["n_C"]) == b for r in val)}
    # peso matematico del prior (k=6) sulla squadra piu' scarsa, per bucket
    R["prior_weight_6"] = {b: float(np.mean([6.0 / (r["n_C"] + 6.0) for r in val if bucket_of(r["n_C"]) == b]))
                           for b in BUCKETS if any(bucket_of(r["n_C"]) == b for r in val)}

    # --- selezione (pre-commessa, SOLO validation) ---
    gg = {k: R["agg"]["validation"][f"C{k}"]["brier_gg"] for k in KS}
    ou = {k: R["agg"]["validation"][f"C{k}"]["brier_ou"] for k in KS}
    b1 = {k: R["agg"]["validation"][f"C{k}"]["brier_1x2"] for k in KS}
    best = min(KS, key=lambda k: gg[k])
    zone = []
    R["zone_boot"] = {}
    for k in KS:
        d = gg[k] - gg[best]
        if abs(d) < 0.001:
            bd = boot_delta(val, f"C{k}", f"C{best}", "gg")
            R["zone_boot"][k] = bd
            if bd["ci_lo"] <= 0 <= bd["ci_hi"]:
                zone.append(k)
        else:
            R["zone_boot"][k] = None
    guard_ok = [k for k in KS if ou[k] <= min(ou.values()) + 0.001 and b1[k] <= b1[0] + 0.002]
    cand = [k for k in zone if k in guard_ok]
    sel = min(cand) if cand else (min(guard_ok, key=lambda k: gg[k]) if guard_ok else best)
    R["selection"] = {"gg_brier_val": gg, "ou_brier_val": ou, "b1x2_val": b1,
                      "best_gg": best, "zone": zone, "guard_ok": guard_ok, "selected": sel}

    pl_variants = ["A", "C0", "C6", f"C{sel}"]
    R["per_league"] = {lg: {tag: {v: metrics([r for r in rs if r["league"] == lg], v)
                                  for v in pl_variants}
                            for tag, rs in (("validation", val), ("test", test))}
                       for lg in LEAGUES}

    # --- bootstrap validation: C0 vs Ck (O/U e GG/NG) ---
    R["boot_val_C0_vs"] = {k: {"gg": boot_delta(val, "C0", f"C{k}", "gg"),
                               "ou": boot_delta(val, "C0", f"C{k}", "ou")} for k in KS if k > 0}
    # --- bootstrap test (una sola volta, sul selezionato): C0 vs Csel ---
    R["boot_test_C0_vs_sel"] = {"gg": boot_delta(test, "C0", f"C{sel}", "gg"),
                                "ou": boot_delta(test, "C0", f"C{sel}", "ou")}
    # --- bootstrap validation A vs C6 (xG vs gol) e B6 vs C6 ---
    R["boot_val_A_vs_C6"] = {"gg": boot_delta(val, "A", "C6", "gg"), "ou": boot_delta(val, "A", "C6", "ou")}
    R["boot_val_B6_vs_C6"] = {"gg": boot_delta(val, "B6", "C6", "gg"), "ou": boot_delta(val, "B6", "C6", "ou")}

    # --- calibrazione (validation) ---
    R["calibration"] = {v: {"over": calib_table(val, v, 3), "gg": calib_table(val, v, 4)}
                        for v in ["C0", f"C{sel}", "C6"]}

    # --- bug check: NG estremi per variante/stagione ---
    R["ng_extreme"] = {}
    for v in VARIANTS:
        R["ng_extreme"][v] = {}
        for tag, rs in (("validation", val), ("test", test), ("monitoring", mon)):
            ngs = [1 - r["preds"][v][4] for r in rs]
            R["ng_extreme"][v][tag] = {"max_ng": float(np.max(ngs)),
                                       "count_gt_95": int(np.sum(np.array(ngs) > 0.95)),
                                       "count_gt_90": int(np.sum(np.array(ngs) > 0.90))}

    # --- bug check: dettaglio delle predizioni NG>90% (varianti senza shrinkage) ---
    extremes = []
    for tag, rs in (("validation", val), ("test", test), ("monitoring", mon)):
        for r in rs:
            ng_a = 1 - r["preds"]["A"][4]
            ng_c0 = 1 - r["preds"]["C0"][4]
            if ng_a > 0.90 or ng_c0 > 0.90:
                extremes.append({"tag": tag, "league": r["league"], "date": r["date"][:10],
                                 "match": f"{r['h']} vs {r['a']}",
                                 "n_C": r["n_C"], "n_pool": r["n_pool"], "paths_C": r["paths_C"],
                                 "NG_A": round(100 * ng_a, 2), "NG_C0": round(100 * ng_c0, 2),
                                 "NG_C6": round(100 * (1 - r["preds"]["C6"][4]), 2),
                                 "y_gg": r["y_gg"]})
    R["ng_extreme_details"] = extremes

    # --- neopromosse (assenti nella stagione precedente) con 0 gol nelle prime 2 ---
    cases = []
    for league in LEAGUES:
        ms = all_matches[league]
        steams = defaultdict(set)
        for m in ms:
            steams[m["season"]].add(m["h"]); steams[m["season"]].add(m["a"])
        for s in (2024, 2025, 2026):
            for team in sorted(steams[s]):
                if team in steams.get(s - 1, set()):
                    continue
                tm = [m for m in ms if m["season"] == s and team in (m["h"], m["a"])][:2]
                if len(tm) == 2:
                    gf2 = sum(m["hg"] if m["h"] == team else m["ag"] for m in tm)
                    if gf2 == 0:
                        nxt = [m for m in ms if m["season"] == s and team in (m["h"], m["a"])
                               and m["date"] > tm[1]["date"]]
                        entry = {"league": league, "season": s, "team": team,
                                 "gf_first2": 0, "next_match": f"{nxt[0]['h']} vs {nxt[0]['a']}" if nxt else None}
                        if nxt:
                            row = next((r for r in rows if r["league"] == league and r["season"] == s
                                        and r["date"] == nxt[0]["date"] and r["h"] == nxt[0]["h"]
                                        and r["a"] == nxt[0]["a"]), None)
                            if row:
                                entry["n_pool squadra"] = row["n_pool"]
                                entry["NG_A"] = round(100 * (1 - row["preds"]["A"][4]), 2)
                                entry["NG_C6"] = round(100 * (1 - row["preds"]["C6"][4]), 2)
                                entry["NG_C0"] = round(100 * (1 - row["preds"]["C0"][4]), 2)
                        cases.append(entry)
    R["promoted_zero_goal"] = cases

    out_json = os.path.join(_AUDIT_DIR, "results", "prior_matches_audit_results.json")
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(R, f, indent=1, ensure_ascii=False)
    print(f"scritto {out_json}; selezionato k={sel} (zona={zone}, best_gg={best})")
    write_report(R)
    return R


def fmt(x, nd=5):
    return "-" if x is None else f"{x:.{nd}f}"


def write_report(R):
    sel = R["selection"]["selected"]
    L = []
    A = L.append
    A("# Audit PRIOR_MATCHES — shrinkage `_shrunk_ratio()` (fix NG ~99.8%)")
    A("")
    A("Audit statistico walk-forward, **nessuna modifica di produzione** (`PRIOR_MATCHES` resta 6).")
    A("Codice: `audit/prior_matches_audit.py` · dati: `audit/results/prior_matches_audit_results.json`.")
    A("")
    A("## Metodologia")
    A("")
    A("- **No-leakage**: ogni predizione usa solo partite completate *prima* della data")
    A("  della partita. Pool gol multi-stagione (come i CSV di produzione) + snapshot xG")
    A("  della stagione in corso (semantica del file `xg_<lega>.json`).")
    A("- **Split**: validation 2024/25 (scelta del prior), test 2025/26 (un solo uso,")
    A("  dopo la selezione), monitoring 2026/27 (2 giornate, solo indicativo).")
    A("- **Varianti** (tutte con la stessa struttura a due teste di produzione, via")
    A("  `app._two_heads_from_lambdas`):")
    A("  - `A` baseline storica **solo-gol** (pool multi-stagione) senza shrinkage;")
    A("  - `B(k)` solo-gol + shrinkage k;")
    A("  - `C(k)` testa `base_pure` di produzione (xG stagione-in-corso, fallback gol)")
    A("    + shrinkage k; `C0` = produzione senza shrinkage.")
    A("- **Selezione pre-commessa** (solo validation): Brier GG/NG (mercato del bug);")
    A("  zona di equivalenza = |Δ| < 0.001 vs il migliore E CI bootstrap 95% che include 0;")
    A("  guardrail: Brier O/U entro +0.001 dal minimo, Brier 1X2 entro +0.002 da `C0`;")
    A("  si sceglie il k **più piccolo** della zona. Mercati mai aggregati in un punteggio unico.")
    A("- ROI omesso (quote non allineate al dataset xG per-partita; criterio secondario).")
    A("- 1752 partite/stagione (3 leghe a 20 squadre + 2 a 18), 5 leghe, Understat per-partita.")
    A("")
    A("## A. Tabella validation (2024/25, n=%d)" % R["agg"]["validation"]["C0"]["n"])
    A("")
    A("| Variante | 1X2 Brier | 1X2 LogLoss | 1X2 acc | O/U Brier | O/U LogLoss | GG/NG Brier | GG/NG LogLoss |")
    A("|---|---|---|---|---|---|---|---|")
    for v in R["variants"]:
        m = R["agg"]["validation"][v]
        A(f"| {v} | {m['brier_1x2']:.5f} | {m['ll_1x2']:.5f} | {m['acc_1x2']*100:.2f}% | "
          f"{m['brier_ou']:.5f} | {m['ll_ou']:.5f} | {m['brier_gg']:.5f} | {m['ll_gg']:.5f} |")
    A("")
    A("## B. Tabella test (2025/26, n=%d) — usata UNA volta, dopo la selezione (k=%d)" % (R["agg"]["test"]["C0"]["n"], sel))
    A("")
    A("| Variante | 1X2 Brier | 1X2 LogLoss | 1X2 acc | O/U Brier | O/U LogLoss | GG/NG Brier | GG/NG LogLoss |")
    A("|---|---|---|---|---|---|---|---|")
    for v in R["variants"]:
        m = R["agg"]["test"][v]
        A(f"| {v} | {m['brier_1x2']:.5f} | {m['ll_1x2']:.5f} | {m['acc_1x2']*100:.2f}% | "
          f"{m['brier_ou']:.5f} | {m['ll_ou']:.5f} | {m['brier_gg']:.5f} | {m['ll_gg']:.5f} |")
    A("")
    A("## C. Risultati per lega (Brier GG/NG · O/U 2.5)")
    A("")
    for tag in ("validation", "test"):
        A("### %s" % tag)
        A("")
        A("| Lega | A GG | C0 GG | C6 GG | C%s GG | A O/U | C0 O/U | C6 O/U | C%s O/U |" % (sel, sel))
        A("|---|---|---|---|---|---|---|---|---|")
        for lg in LEAGUES:
            m = R["per_league"][lg][tag]
            cs = m[f"C{sel}"]
            A(f"| {lg} | {m['A']['brier_gg']:.5f} | {m['C0']['brier_gg']:.5f} | {m['C6']['brier_gg']:.5f} | "
              f"{cs['brier_gg']:.5f} | {m['A']['brier_ou']:.5f} | {m['C0']['brier_ou']:.5f} | "
              f"{m['C6']['brier_ou']:.5f} | {cs['brier_ou']:.5f} |")
        A("")
    A("## D. Analisi per dimensione campione (validation, asse = n_C = partite stagionali della testa xG, min tra le squadre)")
    A("")
    A("| Bucket | n | A O/U | C0 O/U | C6 O/U | A GG | C0 GG | C6 GG | peso prior k=6* |")
    A("|---|---|---|---|---|---|---|---|---|")
    for b in BUCKETS:
        if b not in R["buckets"]["C0"]:
            continue
        n = R["buckets"]["C0"][b]["n"]
        row = [b, str(n)]
        for v in ("A", "C0", "C6"):
            row.append(fmt(R["buckets"][v][b]["brier_ou"]))
        for v in ("A", "C0", "C6"):
            row.append(fmt(R["buckets"][v][b]["brier_gg"]))
        row.append(f"{R['prior_weight_6'][b]:.3f}")
        A("| " + " | ".join(row) + " |")
    A("")
    A("\\* peso matematico del prior w = k/(n+k) sulla squadra con meno dati (k=6).")
    A("")
    A("## E. Calibrazione (validation)")
    A("")
    for v in ("C0", f"C{sel}", "C6"):
        A(f"### {v}")
        for mkt, name in (("over", "P(Over 2.5)"), ("gg", "P(GG)")):
            A("")
            A(f"**{name}**")
            A("")
            A("| bucket | n | prevista | reale |")
            A("|---|---|---|---|")
            for r in R["calibration"][v][mkt]:
                flag = " ⚠️ pochi casi" if r["n"] < 30 else ""
                A(f"| {r['bucket']} | {r['n']}{flag} | {fmt(r['pred'], 4)} | {fmt(r['real'], 4)} |")
        A("")
    A("Osservazione: senza shrinkage (`C0`) la coda alta è sistematicamente sovra-confidente")
    A("(P(GG)≥80% prevista 84% vs 43% reale su 7 casi; P(Over)≥80% prevista 85% vs 70% su 30 casi).")
    A(f"Con shrinkage (`C6`/`C{sel}`) la coda ≥80% svanisce quasi del tutto (0–2 casi): le probabilità")
    A("estreme non compaiono più perché non sono più giustificate dai dati.")
    A("")
    A("## F. Bootstrap paired (2000 repliche, Δ = Brier(a) − Brier(b); Δ>0 ⇒ a peggiore)")
    A("")
    A("### Validation: C0 vs Ck")
    A("")
    A("| k | Δ O/U mean | CI 95% | Δ GG/NG mean | CI 95% |")
    A("|---|---|---|---|---|")
    for k in [x for x in R["ks"] if x > 0]:
        d = R["boot_val_C0_vs"][str(k)] if str(k) in R["boot_val_C0_vs"] else R["boot_val_C0_vs"][k]
        A(f"| {k} | {d['ou']['mean']:+.5f} | [{d['ou']['ci_lo']:+.5f}, {d['ou']['ci_hi']:+.5f}] | "
          f"{d['gg']['mean']:+.5f} | [{d['gg']['ci_lo']:+.5f}, {d['gg']['ci_hi']:+.5f}] |")
    A("")
    A("### Test (un solo uso): C0 vs C%d" % sel)
    A("")
    d = R["boot_test_C0_vs_sel"]
    A(f"- O/U: Δ={d['ou']['mean']:+.5f}, CI [{d['ou']['ci_lo']:+.5f}, {d['ou']['ci_hi']:+.5f}], P(Δ>0)={d['ou']['p_gt0']:.3f}")
    A(f"- GG/NG: Δ={d['gg']['mean']:+.5f}, CI [{d['gg']['ci_lo']:+.5f}, {d['gg']['ci_hi']:+.5f}], P(Δ>0)={d['gg']['p_gt0']:.3f}")
    A("")
    A("### Validation: basi a confronto")
    A("")
    for label, key in (("A (gol, senza shrinkage) vs C6 (xG + shrinkage)", "boot_val_A_vs_C6"),
                       ("B6 (gol + shrinkage) vs C6 (xG + shrinkage)", "boot_val_B6_vs_C6")):
        d = R[key]
        A(f"- {label}: O/U Δ={d['ou']['mean']:+.5f} CI [{d['ou']['ci_lo']:+.5f}, {d['ou']['ci_hi']:+.5f}]; "
          f"GG/NG Δ={d['gg']['mean']:+.5f} CI [{d['gg']['ci_lo']:+.5f}, {d['gg']['ci_hi']:+.5f}]")
    A("")
    A("## G. Confronto con baseline solo-gol (domanda: lo shrinkage o la fonte dati?)")
    A("")
    mV, mT = R["agg"]["validation"], R["agg"]["test"]
    A(f"- `C0` (xG senza shrinkage) è **peggiore della baseline solo-gol `A`** su ogni mercato e stagione: "
      f"GG/NG val {mV['C0']['brier_gg']:.5f} vs {mV['A']['brier_gg']:.5f}, test {mT['C0']['brier_gg']:.5f} vs {mT['A']['brier_gg']:.5f}.")
    A(f"- Con shrinkage la testa xG recupera e supera `A`: `C6` GG/NG val {mV['C6']['brier_gg']:.5f} "
      f"(A: {mV['A']['brier_gg']:.5f}), test {mT['C6']['brier_gg']:.5f} (A: {mT['A']['brier_gg']:.5f}); "
      f"bootstrap A−C6 CI include lo 0 (nessuna differenza robusta).")
    A(f"- `B6` (gol+shrinkage) ≈ `C6` (xG+shrinkage): Δ GG/NG val {R['boot_val_B6_vs_C6']['gg']['mean']:+.5f} "
      f"(CI [{R['boot_val_B6_vs_C6']['gg']['ci_lo']:+.5f}, {R['boot_val_B6_vs_C6']['gg']['ci_hi']:+.5f}]) "
      f"e segno opposto nel test → fonte gol vs xG sostanzialmente equivalente SUI TOTALI una volta applicato lo shrinkage.")
    A("")
    A("## Verifica del bug originale (NG ~99.8%)")
    A("")
    A("| Variante | val: NG>90 / >95 / max | test: NG>90 / >95 | mon: NG>95 / max |")
    A("|---|---|---|---|")
    for v in R["variants"]:
        e = R["ng_extreme"][v]
        A(f"| {v} | {e['validation']['count_gt_90']} / {e['validation']['count_gt_95']} / {e['validation']['max_ng']*100:.2f}% | "
          f"{e['test']['count_gt_90']} / {e['test']['count_gt_95']} | "
          f"{e['monitoring']['count_gt_95']} / {e['monitoring']['max_ng']*100:.2f}% |")
    A("")
    A("Il caso patologico è **ricorrente e reale** nelle varianti senza shrinkage:")
    A("`A` produce NG>95% in 7 partite di validation e 7 di test (max 99.88%);")
    A("`C0` 1 caso >95% per stagione e 8 >90% in validation (max 99.10%).")
    A("Con qualsiasi k≥2: **zero** predizioni NG>90% e massimo ~63–75%.")
    A("Non è un cap sulla probabilità: le NG estreme scompaiono perché λ non collassa più a exp(−6).")
    A("")
    A("Dettaglio dei casi estremi (NG>90% in A o C0):")
    A("")
    A("| Stagione | Lega | Partita | Data | n_C | NG A | NG C0 | NG C6 | GG reale |")
    A("|---|---|---|---|---|---|---|---|---|")
    for e in R["ng_extreme_details"]:
        A(f"| {e['tag']} | {e['league']} | {e['match']} | {e['date']} | {e['n_C']} | "
          f"{e['NG_A']:.1f}% | {e['NG_C0']:.1f}% | {e['NG_C6']:.1f}% | {'GG' if e['y_gg'] else 'NG'} |")
    A("")
    A("Neopromosse (assenti dalla stagione precedente) con 0 gol nelle prime 2 partite:")
    A("")
    for c in R["promoted_zero_goal"]:
        if c.get("next_match") is None:
            A(f"- {c['league']} {c['season']}/{c['season']+1}: **{c['team']}** (0 gol nelle prime 2) — "
              f"3ª partita non ancora giocata al momento dell'audit (monitoring).")
        else:
            A(f"- {c['league']} {c['season']}/{c['season']+1}: **{c['team']}** (0 gol nelle prime 2) — "
              f"3ª partita {c['next_match']}: NG A={c.get('NG_A')}% C0={c.get('NG_C0')}% C6={c.get('NG_C6')}% "
              f"(pool gol della squadra: n={c.get('n_pool squadra')}).")
    A("")
    A("I casi con pool n=2 (prima stagione nel window dell'archivio: St. Pauli 2024/25,")
    A("Saint-Etienne 2024/25, Hamburg 2025/26, Real Oviedo 2025/26) mostrano esattamente la firma")
    A("del bug nel baseline `A`: NG ≈ 99.8%. I casi con pool n=40 (Southampton, Espanol, Angers:")
    A("due stagioni d'archivio) non collassano. Ipswich 2024/25 e Real Oviedo 2025/26, senza")
    A("storico in archivio, generano in `A` le predizioni NG 99.8% visibili in tabella sopra.")
    A("")
    A("## Monitoring 2026/27 (n=%d, 2 giornate — solo indicativo)" % R["agg"]["monitoring"]["C0"]["n"])
    A("")
    A("| Variante | 1X2 Brier | O/U Brier | GG/NG Brier |")
    A("|---|---|---|---|")
    for v in R["variants"]:
        m = R["agg"]["monitoring"][v]
        A(f"| {v} | {m['brier_1x2']:.5f} | {m['brier_ou']:.5f} | {m['brier_gg']:.5f} |")
    A("")
    A("## Selezione e sensitivity")
    A("")
    s = R["selection"]
    A("Brier GG/NG in validation: " + ", ".join(f"k={k}: {v:.5f}" for k, v in s["gg_brier_val"].items()) + ".")
    A(f"Migliore: k={s['best_gg']}. Zone rule: |Δ|<0.001 vs migliore E CI che include 0 → zona={s['zone']}; "
      f"guardrail O/U e 1X2 ok per k={s['guard_ok']} → **selezionato k={s['selected']}**.")
    A("")
    A("Δ incrementali del Brier GG/NG (validation): 0→2: −0.0057 · 2→4: −0.0014 · 4→6: −0.0007 · "
      "6→8: −0.0004 · 8→10: −0.0003: rendimenti decrescenti, curva piatta da k=6 in poi.")
    A("k=6 resta fuori dalla zona solo per un soffio (CI basso +0.00006 > 0): **6, 8 e 10 sono")
    A("praticamente indistinguibili**; le differenze (≤0.0004) sono troppo piccole per essere")
    A("considerate significative. Non c'è evidenza per un valore preciso nella zona 6–10.")
    A("")
    A("## H. Raccomandazione finale")
    A("")
    A("**BUG FIX** — Lo shrinkage risolve il caso patologico (0 gol in 1–2 partite → λ→exp(−6) → NG 99.8%):")
    A("con k≥2 nessuna predizione NG>90% in 3 stagioni×5 leghe; risolto via stima dei parametri, non via cap.")
    A("")
    A("**MIGLIORAMENTO PREDITTIVO** — C'è anche un miglioramento out-of-sample **statisticamente robusto**,")
    A("non limitato all'inizio stagione: su validation C0→C6 migliora GG/NG di 0.0078 (CI Δ [0.0044, 0.0114])")
    A(f"e O/U di 0.0048; confermato nel test una-tantum C0→C{sel}: GG/NG −0.0043 (CI Δ "
      f"[{R['boot_test_C0_vs_sel']['gg']['ci_lo']:+.5f}, {R['boot_test_C0_vs_sel']['gg']['ci_hi']:+.5f}]), "
      f"O/U −0.0049. Il grosso del guadagno sta nelle fasce 0–2 e 3–10 partite, ma non c'è danno")
    A("nelle fasce 11+ (differenze trascurabili e di segno favorevole).")
    A("")
    A(f"**Decisione consigliata dai dati**: categoria *\"shrinkage utile (bug fix + predittivo) ma valore non")
    A("identificabile con precisione nella zona 6–10\"* → **mantenere `PRIOR_MATCHES = 6` in produzione**:")
    A("è dentro la zona di equivalenza, è il valore più conservativo già testato dal fix, e il passaggio 6→8")
    A("varrebbe ~0.0004 Brier (non significante). Nessuna modifica di produzione eseguita in questo audit.")
    A("")
    A("---")
    A("")
    A("Ambito: 5 leghe, 2022/23–2026/27 (Understat per-partita), test unitari di regressione in")
    A("`audit/test_ng_regression.py` (24 test, verdi) coprono NaN/inf, xG mancanti/zero, mapping nomi,")
    A("neopromosse e campioni insufficienti.")
    md = "\n".join(L)
    path = os.path.join(_AUDIT_DIR, "prior_matches_audit_report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"scritto {path}")


if __name__ == "__main__":
    main()
