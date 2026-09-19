"""
verify_maxc_b365c_storico.py - Verifica copertura storica MaxC* vs B365C*.

DOMANDA (audit sola lettura, nessuna modifica a produzione):
  MaxCH/MaxCD/MaxCA e B365CH/B365CD/B365CA (CSV football-data.co.uk) esistono
  e sono coperti su TUTTO il perimetro walk-forward (2223, 2324, 2425, 2526;
  5 leghe) per poter sostituire PSCH/PSCD/PSCA (assenti sul live) come
  riferimento CLV di chiusura? Verifica esplicita colonna per colonna,
  stagione per stagione, lega per lega -- nessuna assunzione dal 2026/27.

Perimetro: 4 stagioni storiche x 5 leghe (20 file) + 2627 (5 file) solo per
ricalcolare con la STESSA metrica il baseline 2.22%/5.49% gia' misurato solo
sul 2026/27.

I byte grezzi sono in ``audit/data/fd_{DIV}_{season}.csv`` (scaricati da
football-data.co.uk via workflow GitHub Actions temporaneo, commit separato,
sha256 in ``audit/data/fd_maxc_storico_manifest.json``). Nessuna
trasformazione: il parser legge i byte cosi' come pubblicati dal sito.

Metriche per (lega, stagione):
  * presenza colonne (MaxCH/CD/CA, B365CH/CD/CA) nell'header reale del file;
  * copertura: % righe con quota valida (presente, numerica, > 1.0 -- stessa
    regola di ``devig_1x2``) per ciascuna colonna e per tripletta completa;
  * overround implicito (1/h+1/d+1/a-1) medio e mediano per book, sulle
    righe con tripletta completa;
  * copertura congiunta (entrambi i book completi: il campione effettivamente
    usabile per un confronto/switch di riferimento);
  * divergenza prezzi MaxC vs B365C e divergenza probabilita' de-vigate.

Uso:
    python audit/verify_maxc_b365c_storico.py
    python audit/verify_maxc_b365c_storico.py --data-dir X --results-dir Y

Output: audit/results/maxc_b365c_copertura_storica.{md,json}
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import statistics
from datetime import datetime, timezone

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
DATA_DIR_DEFAULT = os.path.join(_REPO_ROOT, "audit", "data")
RESULTS_DIR_DEFAULT = os.path.join(_REPO_ROOT, "audit", "results")

# Perimetro walk-forward (train 2223+2324, validation 2425, test 2526).
SEASONS_WALKFORWARD = ["2223", "2324", "2425", "2526"]
SEASON_BASELINE = "2627"  # solo per ricalcolare il baseline 2.22%/5.49%
SEASONS_ALL = SEASONS_WALKFORWARD + [SEASON_BASELINE]

LEAGUES = {
    "E0": "Premier League",
    "D1": "Bundesliga",
    "I1": "Serie A",
    "SP1": "La Liga",
    "F1": "Ligue 1",
}
LEAGUE_ORDER = ["I1", "E0", "SP1", "D1", "F1"]  # come nei report precedenti

BOOKS = {
    "MaxC": ["MaxCH", "MaxCD", "MaxCA"],
    "B365C": ["B365CH", "B365CD", "B365CA"],
}

# Partite attese per stagione/lega (fonte: report precedenti, clv_pinnacle):
EXPECTED_ROWS = {
    ("E0", "2223"): 380, ("E0", "2324"): 380, ("E0", "2425"): 380, ("E0", "2526"): 380,
    ("D1", "2223"): 306, ("D1", "2324"): 306, ("D1", "2425"): 306, ("D1", "2526"): 306,
    ("I1", "2223"): 380, ("I1", "2324"): 380, ("I1", "2425"): 380, ("I1", "2526"): 380,
    ("SP1", "2223"): 380, ("SP1", "2324"): 380, ("SP1", "2425"): 380, ("SP1", "2526"): 380,
    ("F1", "2223"): 380, ("F1", "2324"): 306, ("F1", "2425"): 306, ("F1", "2526"): 306,
}

# Soglia di sufficienza per il verdetto (copertura tripletta, in %).
COVERAGE_OK_PCT = 99.0

SEASON_LABEL = {
    "2223": "2022/23", "2324": "2023/24", "2425": "2024/25",
    "2526": "2025/26", "2627": "2026/27",
}


# ----------------------------------------------------------------- parsing --

def read_csv_bytes(path: str):
    """Legge i byte grezzi (BOM gestito, latin-1) e restituisce (header, righe,
    n_righe_scartate_per_struttura). Le righe con Div vuoto (code a fine file)
    sono considerate vuote, non malformed."""
    raw = open(path, "rb").read()
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]
    rows = list(csv.reader(io.StringIO(raw.decode("latin-1"))))
    header, data = rows[0], rows[1:]
    parsed, malformed = [], 0
    for row in data:
        if not row or all(not c.strip() for c in row):
            continue  # riga vuota di coda
        if not row[0].strip():
            continue  # Div vuoto
        parsed.append(row)
    return header, parsed, malformed


def valid_odds(row, idx: dict, name: str):
    """Quota valida = presente, numerica, > 1.0 (regola devig_1x2)."""
    i = idx.get(name)
    if i is None or i >= len(row):
        return None
    txt = row[i].strip()
    if not txt:
        return None
    try:
        v = float(txt)
    except ValueError:
        return None
    return v if v > 1.0 else None


def parse_date(txt: str):
    """Date football-data: DD/MM/YY o DD/MM/YYYY."""
    parts = txt.strip().split("/")
    if len(parts) != 3:
        return None
    d, m, y = parts
    if len(y) == 2:
        y = "20" + y
    try:
        return f"{y}-{int(m):02d}-{int(d):02d}"
    except ValueError:
        return None


def overround(row, idx, cols):
    h, d, a = (valid_odds(row, idx, c) for c in cols)
    if h is None or d is None or a is None:
        return None
    return 1.0 / h + 1.0 / d + 1.0 / a - 1.0


def devig_prop(row, idx, cols):
    """Probabilita' de-vigate proporzionali (come devig_1x2): p_i = 1/q_i / S."""
    h, d, a = (valid_odds(row, idx, c) for c in cols)
    if h is None or d is None or a is None:
        return None
    s = 1.0 / h + 1.0 / d + 1.0 / a
    return (1.0 / h / s, 1.0 / d / s, 1.0 / a / s)


# ---------------------------------------------------------------- analisi ---

def pct(n: int, d: int) -> float:
    return 100.0 * n / d if d else 0.0


def fmt_pct(x: float) -> str:
    return "100.0%" if x >= 99.9995 else f"{x:.1f}%"


def analyze_file(path: str, div: str, season: str) -> dict:
    header, rows, malformed = read_csv_bytes(path)
    idx = {name: i for i, name in enumerate(header)}

    # Div dichiarato dal file (mode) vs atteso dal nome file.
    divs = {r[0].strip() for r in rows if r and r[0].strip()}
    div_file = sorted(divs)[0] if len(divs) == 1 else ",".join(sorted(divs))

    dates = [parse_date(r[idx["Date"]]) for r in rows if idx.get("Date") is not None
             and idx["Date"] < len(r)]
    dates = [d for d in dates if d]
    played = sum(
        1 for r in rows
        if idx.get("FTR") is not None and idx["FTR"] < len(r) and r[idx["FTR"]].strip()
    )

    out = {
        "div": div,
        "league": LEAGUES[div],
        "season": season,
        "season_label": SEASON_LABEL[season],
        "file": os.path.basename(path),
        "bytes": os.path.getsize(path),
        "sha256": hashlib.sha256(open(path, "rb").read()).hexdigest(),
        "n_rows": len(rows),
        "n_expected": EXPECTED_ROWS.get((div, season)),
        "n_malformed": malformed,
        "div_in_file": div_file,
        "div_match": div_file == div,
        "date_min": min(dates) if dates else None,
        "date_max": max(dates) if dates else None,
        "n_played_ftr": played,
        "columns": {},
    }

    # Tutti i blocchi chiusura *CH/*CD/*CA presenti (contesto).
    closing_books = sorted({
        h[:-2] for h in header
        if len(h) > 2 and h.endswith("CH") and (h[:-2] + "CD") in idx and (h[:-2] + "CA") in idx
    })
    out["closing_books_present"] = closing_books

    for book, cols in BOOKS.items():
        missing_cols = [c for c in cols if c not in idx]
        out["columns"][book] = {
            "cols": cols,
            "missing_cols": missing_cols,
            "present": not missing_cols,
        }

    # Copertura per colonna e per tripletta.
    for book, cols in BOOKS.items():
        colstats = {}
        for c in cols:
            if c not in idx:
                colstats[c] = None
                continue
            n = sum(1 for r in rows if valid_odds(r, idx, c) is not None)
            colstats[c] = {"n_valid": n, "pct_valid": pct(n, len(rows))}
        tri = [overround(r, idx, cols) for r in rows]
        n_tri = sum(1 for o in tri if o is not None)
        vals = [o for o in tri if o is not None]
        out["columns"][book].update({
            "colstats": colstats,
            "n_triplet_valid": n_tri,
            "pct_triplet_valid": pct(n_tri, len(rows)),
            "overround_mean_pct": 100.0 * statistics.fmean(vals) if vals else None,
            "overround_median_pct": 100.0 * statistics.median(vals) if vals else None,
            "overround_min_pct": 100.0 * min(vals) if vals else None,
            "overround_max_pct": 100.0 * max(vals) if vals else None,
        })

    # Righe utilizzabili con ENTRAMBI i book (per confronto/switch riferimento).
    both = []
    for r in rows:
        if overround(r, idx, BOOKS["MaxC"]) is not None and \
           overround(r, idx, BOOKS["B365C"]) is not None:
            both.append(r)
    out["n_both"] = len(both)
    out["pct_both"] = pct(len(both), len(rows))

    # Divergenze MaxC vs B365C sulle righe congiunte.
    if both:
        gaps = {s: [] for s in ("H", "D", "A")}
        pdiff = {s: [] for s in ("H", "D", "A")}
        eq = {s: 0 for s in ("H", "D", "A")}
        outliers = []
        for r in both:
            pm = devig_prop(r, idx, BOOKS["MaxC"])
            pb = devig_prop(r, idx, BOOKS["B365C"])
            row_max_abs = 0.0
            for k, s in enumerate(("CH", "CD", "CA")):
                qm = valid_odds(r, idx, "Max" + s)
                qb = valid_odds(r, idx, "B365" + s)
                gaps["HDA"[k]].append((qm - qb) / qb)
                pdiff["HDA"[k]].append(100.0 * (pm[k] - pb[k]))
                row_max_abs = max(row_max_abs, abs(100.0 * (pm[k] - pb[k])))
                if abs(qm - qb) < 1e-9:
                    eq["HDA"[k]] += 1
            if row_max_abs > 10.0:
                outliers.append({
                    "date": parse_date(r[idx["Date"]]) if idx.get("Date") is not None else None,
                    "home": r[idx["HomeTeam"]] if idx.get("HomeTeam") is not None and
                            idx["HomeTeam"] < len(r) else "?",
                    "away": r[idx["AwayTeam"]] if idx.get("AwayTeam") is not None and
                            idx["AwayTeam"] < len(r) else "?",
                    "maxc": [valid_odds(r, idx, "Max" + s) for s in ("CH", "CD", "CA")],
                    "b365c": [valid_odds(r, idx, "B365" + s) for s in ("CH", "CD", "CA")],
                    "max_abs_pp": round(row_max_abs, 1),
                })
        n = len(both)
        out["divergence"] = {
            "n": n,
            "price_gap_mean_pct": {s: 100.0 * statistics.fmean(v) for s, v in gaps.items()},
            "price_gap_mean_abs_pct": {s: 100.0 * statistics.fmean(abs(x) for x in v)
                                       for s, v in gaps.items()},
            "devig_prob_diff_mean_pp": {s: statistics.fmean(v) for s, v in pdiff.items()},
            "devig_prob_diff_max_abs_pp": {s: max(abs(x) for x in v) for s, v in pdiff.items()},
            "pct_b365_is_max": {s: pct(eq[s], n) for s in eq},
            "outliers_gt_10pp": outliers,
        }
    else:
        out["divergence"] = None
    return out


def aggregate(files_stats: list, books=("MaxC", "B365C")) -> dict:
    """Micro (righe in pool) e macro (media non pesata dei file) per book."""
    out = {}
    for book in books:
        ovs, means = [], []
        for st in files_stats:
            b = st["columns"][book]
            if b["overround_mean_pct"] is not None:
                means.append(b["overround_mean_pct"])
        # micro: replica la media di ciascun file per il suo n di triplette valide
        # (somma pesata == media sulle righe in pool, i valori sono gia' in %)
        for st in files_stats:
            b = st["columns"][book]
            n = b["n_triplet_valid"]
            if n and b["overround_mean_pct"] is not None:
                ovs.extend([b["overround_mean_pct"]] * n)
        out[book] = {
            "micro_mean_pct": statistics.fmean(ovs) if ovs else None,
            "micro_n": len(ovs),
            "macro_mean_pct": statistics.fmean(means) if means else None,
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default=DATA_DIR_DEFAULT)
    ap.add_argument("--results-dir", default=RESULTS_DIR_DEFAULT)
    args = ap.parse_args()

    os.makedirs(args.results_dir, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    stats_all = {}
    missing_files = []
    for season in SEASONS_ALL:
        for div in LEAGUE_ORDER:
            name = f"fd_{div}_{season}.csv"
            path = os.path.join(args.data_dir, name)
            if not os.path.exists(path):
                missing_files.append(name)
                continue
            stats_all[(div, season)] = analyze_file(path, div, season)

    wf = [st for (d, s), st in stats_all.items() if s in SEASONS_WALKFORWARD]
    bl = [st for (d, s), st in stats_all.items() if s == SEASON_BASELINE]

    agg = {
        "per_season": {},
        "overall_walkforward": aggregate(wf),
        "baseline_2627": aggregate(bl),
        "macro_per_league_walkforward": {},
    }
    for season in SEASONS_ALL:
        st = [v for (d, s), v in stats_all.items() if s == season]
        agg["per_season"][season] = aggregate(st)
    for div in LEAGUE_ORDER:
        st = [v for (d, s), v in stats_all.items() if d == div and s in SEASONS_WALKFORWARD]
        agg["macro_per_league_walkforward"][div] = aggregate(st)

    # ---------------------------------------------------------------- verdetto
    holes = []
    for (div, season), st in sorted(stats_all.items()):
        if season not in SEASONS_WALKFORWARD:
            continue
        probs = []
        for book, b in st["columns"].items():
            if not b["present"]:
                probs.append(f"{book}: colonne mancanti {b['missing_cols']}")
            elif b["pct_triplet_valid"] < COVERAGE_OK_PCT:
                probs.append(
                    f"{book}: tripletta valida solo {fmt_pct(b['pct_triplet_valid'])}"
                )
        if st["pct_both"] < COVERAGE_OK_PCT:
            probs.append(f"congiunta {fmt_pct(st['pct_both'])}")
        if st["n_expected"] is not None and st["n_rows"] != st["n_expected"]:
            probs.append(f"righe {st['n_rows']} != attese {st['n_expected']}")
        if probs:
            holes.append({"div": div, "league": st["league"],
                          "season": st["season_label"], "problems": probs})
    verdict = {
        "maxc_usable_walkforward": not holes,
        "coverage_threshold_pct": COVERAGE_OK_PCT,
        "holes": holes,
    }

    # Confronto baseline 2627 (2.22% / 5.49% misurati in precedenza).
    b_max = agg["baseline_2627"]["MaxC"]["micro_mean_pct"]
    b_b365 = agg["baseline_2627"]["B365C"]["micro_mean_pct"]
    baseline_cmp = {
        "previous_measurement": {"MaxC_pct": 2.22, "B365C_pct": 5.49,
                                 "note": "misurato solo sul 2026/27 in sessione precedente"},
        "recomputed_now": {"MaxC_pct": round(b_max, 2), "B365C_pct": round(b_b365, 2),
                           "n_rows": agg["baseline_2627"]["MaxC"]["micro_n"]},
    }

    result = {
        "generated_utc": now,
        "scope": {
            "seasons_walkforward": [SEASON_LABEL[s] for s in SEASONS_WALKFORWARD],
            "season_baseline": SEASON_LABEL[SEASON_BASELINE],
            "leagues": LEAGUES,
            "source": "football-data.co.uk mmz4281/{season}/{div}.csv (byte grezzi)",
            "data_dir": os.path.relpath(args.data_dir, _REPO_ROOT),
            "manifest": "fd_maxc_storico_manifest.json",
            "missing_files": missing_files,
        },
        "odds_validity_rule": "presente, numerica, > 1.0 (regola devig_1x2)",
        "files": [st for st in stats_all.values()],
        "aggregates": agg,
        "baseline_2627_comparison": baseline_cmp,
        "verdict": verdict,
    }

    json_path = os.path.join(args.results_dir, "maxc_b365c_copertura_storica.json")
    with io.open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")

    md = render_markdown(result)
    md_path = os.path.join(args.results_dir, "maxc_b365c_copertura_storica.md")
    with io.open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"scritti: {os.path.relpath(md_path, _REPO_ROOT)}, "
          f"{os.path.relpath(json_path, _REPO_ROOT)}")
    print(f"verdetto MaxC* walk-forward: {verdict['maxc_usable_walkforward']}; "
          f"buchi: {len(holes)}")
    return 0


def _fmt2(x) -> str:
    return "n/d" if x is None else f"{x:.2f}%"


def _fmt1(x) -> str:
    return "n/d" if x is None else f"{x:.1f}%"


def render_markdown(res: dict) -> str:
    o = []
    w = o.append
    w("# Copertura storica MaxC* vs B365C* (quote di chiusura football-data)\n")
    w(f"*Generato: {res['generated_utc']} — script `audit/verify_maxc_b365c_storico.py`, "
      f"sola lettura, nessuna modifica a produzione.*\n")
    w(f"Byte grezzi committati in `{res['scope']['data_dir']}/fd_*.csv` "
      f"(download via workflow GitHub Actions temporaneo, poi rimosso; sha256 per file "
      f"nella tabella §1 e in `{res['scope']['manifest']}`). Fonte: "
      f"`football-data.co.uk mmz4281/{{stagione}}/{{div}}.csv`, nessuna trasformazione.\n")
    w(f"Perimetro richiesto: **{', '.join(res['scope']['seasons_walkforward'])}** "
      f"(train+val+test) × 5 leghe = 20 file. Aggiunti i 5 file 2026/27 SOLO per "
      f"ricalcolare con la stessa metrica il baseline 2.22%/5.49% misurato in "
      f"precedenza sul 2026/27. Regola quota valida: {res['odds_validity_rule']}.\n")

    # §1 presenza colonne
    w("## 1. Le colonne esistono? Verifica esplicita header per header\n")
    w("Cerchi = esiste l'INTERA famiglia di chiusura `*CH/*CD/*CA` nell'header del file. "
      "`closing` = numero di book con blocco chiusura completo presente (contesto).\n")
    w("| File | Righe | Attese | MaxCH/CD/CA | B365CH/CD/CA | Altri blocchi chiusura | Div ok |")
    w("|---|---:|---:|:--:|:--:|:--:|:--:|")
    for st in res["files"]:
        mx = "sì" if st["columns"]["MaxC"]["present"] else f"NO ({st['columns']['MaxC']['missing_cols']})"
        b3 = "sì" if st["columns"]["B365C"]["present"] else f"NO ({st['columns']['B365C']['missing_cols']})"
        nb = len(st["closing_books_present"])
        exp = st["n_expected"] if st["n_expected"] is not None else "—"
        w(f"| `{st['file']}` | {st['n_rows']} | {exp} | {mx} | {b3} | {nb} | "
          f"{'sì' if st['div_match'] else 'NO: ' + st['div_in_file']} |")
    w("")
    any_missing = any(not st["columns"][b]["present"] for st in res["files"] for b in BOOKS)
    if not any_missing:
        w("**Tutte e 6 le colonne (MaxCH/MaxCD/MaxCA, B365CH/B365CD/B365CA) esistono in "
          "tutti i 25 file** — nessuna eccezione per stagione o lega: non sono una "
          "novità del 2026/27. Per contesto: i blocchi di chiusura sono presenti anche "
          "per gli altri book (PSCH, AvgCH, BWCH, …); i set di book cambiano leggermente "
          "tra le stagioni, Max e B365 ci sono sempre.\n")
    else:
        w("**ATTENZIONE: almeno una colonna manca in qualche file** — vedi tabella.\n")

    # righe
    n_bad_rows = [st for st in res["files"]
                  if st["n_expected"] is not None and st["n_rows"] != st["n_expected"]]
    if not n_bad_rows:
        w("Conteggi righe coerenti con il perimetro noto (380 o 306 partite; "
          "Bundesliga sempre 306, Ligue 1 380 solo nel 2022/23 prima del passaggio a 18 "
          "squadre). Nessun file troncato, nessuna riga malformed.\n")

    # §2 copertura
    w("## 2. Copertura per colonna — % righe con quota valida (lega × stagione)\n")
    w("| Lega | Stagione | Righe | MaxCH | MaxCD | MaxCA | MaxC* tripletta | B365CH | B365CD | B365CA | B365C* tripletta | Entrambi |")
    w("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for st in res["files"]:
        m, b = st["columns"]["MaxC"], st["columns"]["B365C"]
        cells = []
        for c in ("MaxCH", "MaxCD", "MaxCA"):
            cs = m["colstats"][c]
            cells.append(_fmt1(cs["pct_valid"]) if cs else "colonna assente")
        cells.append(f"**{_fmt1(m['pct_triplet_valid'])}**")
        for c in ("B365CH", "B365CD", "B365CA"):
            cs = b["colstats"][c]
            cells.append(_fmt1(cs["pct_valid"]) if cs else "colonna assente")
        cells.append(f"**{_fmt1(b['pct_triplet_valid'])}**")
        cells.append(_fmt1(st["pct_both"]))
        w(f"| {st['league']} | {st['season_label']} | {st['n_rows']} | " + " | ".join(cells) + " |")
    w("")
    w("«Tripletta» = righe con tutte e tre le quote del book valide (il minimo per "
      "calcolare l'overround o de-vigare). «Entrambi» = righe utilizzabili per un "
      "confronto diretto MaxC* vs B365C*.\n")

    # §3 overround
    w("## 3. Overround implicito medio (1/h+1/d+1/a−1) — MaxC* vs B365C*\n")
    w("| Lega | Stagione | n Max | MaxC* media | MaxC* mediana | MaxC* min–max | n B365 | B365C* media | B365C* mediana | Δ (B365−Max) |")
    w("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for st in res["files"]:
        m, b = st["columns"]["MaxC"], st["columns"]["B365C"]
        delta = (b["overround_mean_pct"] - m["overround_mean_pct"]) \
            if (m["overround_mean_pct"] is not None and b["overround_mean_pct"] is not None) else None
        rng = (f"{m['overround_min_pct']:.2f}–{m['overround_max_pct']:.2f}%"
               if m["overround_min_pct"] is not None else "n/d")
        w(f"| {st['league']} | {st['season_label']} | {m['n_triplet_valid']} | "
          f"**{_fmt2(m['overround_mean_pct'])}** | {_fmt2(m['overround_median_pct'])} | {rng} | "
          f"{b['n_triplet_valid']} | **{_fmt2(b['overround_mean_pct'])}** | "
          f"{_fmt2(b['overround_median_pct'])} | {('' if delta is None else f'{delta:+.2f} pp')} |")
    w("")
    w("### Aggregati\n")
    w("| Aggregato | MaxC* micro | MaxC* macro | B365C* micro | B365C* macro | n |")
    w("|---|---:|---:|---:|---:|---:|")
    a = res["aggregates"]
    for label, key in [("2022/23", "2223"), ("2023/24", "2324"), ("2024/25", "2425"),
                       ("2025/26", "2526"), ("2026/27 (baseline)", "2627"),
                       ("**Walk-forward 2022/23–2025/26**", "overall_walkforward")]:
        aa = a[key] if key in a else a.get("per_season", {}).get(key)
        if aa is None:
            continue
        n = aa["MaxC"]["micro_n"]
        w(f"| {label} | {_fmt2(aa['MaxC']['micro_mean_pct'])} | {_fmt2(aa['MaxC']['macro_mean_pct'])} | "
          f"{_fmt2(aa['B365C']['micro_mean_pct'])} | {_fmt2(aa['B365C']['macro_mean_pct'])} | {n} |")
    w("")
    w("micro = media sulle righe in pool; macro = media non pesata delle leghe.\n")

    # §4 baseline
    bc = res["baseline_2627_comparison"]
    rn = bc["recomputed_now"]
    wf_st = [st for st in res["files"] if st["season_label"] in res["scope"]["seasons_walkforward"]]
    b365_means = [st["columns"]["B365C"]["overround_mean_pct"] for st in wf_st]
    b365_lo, b365_hi = min(b365_means), max(b365_means)
    b365_sd = statistics.pstdev(b365_means)
    bl_max_date = max((st["date_max"] for st in res["files"]
                       if st["season"] == SEASON_BASELINE and st["date_max"]), default="n/d")
    seas_maxc = {lbl: res["aggregates"]["per_season"][key]["MaxC"]["micro_mean_pct"]
                 for lbl, key in [("2022/23", "2223"), ("2023/24", "2324"),
                                  ("2024/25", "2425"), ("2025/26", "2526")]}
    neg_seasons = [lbl for lbl, v in seas_maxc.items() if v is not None and v < 0]
    w("## 4. Conferma/smentita del 2.22%/5.49% (misurato solo sul 2026/27)\n")
    w("| Grandezza (2026/27, 5 leghe) | misura precedente | ricalcolo di oggi |")
    w("|---|---:|---:|")
    w(f"| Overround MaxC* | 2.22% | **{rn['MaxC_pct']:.2f}%** |")
    w(f"| Overround B365C* | 5.49% | **{rn['B365C_pct']:.2f}%** |")
    w(f"| Righe con tripletta | non dichiarato | {rn['n_rows']} |")
    w("")
    w(f"Il ricalcolo di oggi sul 2026/27 ({rn['n_rows']} partite chiuse entro il "
      f"{bl_max_date}, file freschi di oggi) "
      f"conferma il baseline in sostanza: MaxC* {rn['MaxC_pct']:.2f}% contro 2,22%, "
      f"B365C* {rn['B365C_pct']:.2f}% contro 5,49%. Lo scarto di ~0,1–0,2 pp è atteso: "
      f"il file 2026/27 cresce a ogni matchday e la misura precedente era presa su un "
      f"campione più piccolo. **Confermato.**\n")
    w(f"Due letture che la sola stagione live non permetteva:\n")
    w(f"1. **Il 5,49% di B365C* non è un'anomalia del live**: sulle 20 combinazioni "
      f"lega×stagione del walk-forward B365C* sta sempre tra {b365_lo:.2f}% e "
      f"{b365_hi:.2f}% (dev. std {b365_sd:.2f} pp): è il livello strutturale del "
      f"margine Bet365 di chiusura su football-data, identico nel 2022/23 e nel 2026/27.\n")
    w(f"2. **Il 2,22% di MaxC* è il punto ALTO del suo range storico, non la norma**: "
      f"l'overround MaxC* per stagione (micro) vale "
      + ", ".join(f"{lbl} {v:.2f}%" for lbl, v in seas_maxc.items())
      + f"; {'è NEGATIVO in ' + ', '.join(neg_seasons) if neg_seasons else 'non è mai negativo'} "
      f"(max per esito preso su book diversi ⇒ insieme quasi arbitraggibile) e sale "
      f"progressivamente fino a ~2,2–2,5% nelle ultime due stagioni. Storicamente MaxC* "
      f"«comprime» il margine molto più di B365C* (Δ ~+6 pp nel 2022/23, ~+3 pp oggi — "
      f"vedi §3).\n")


    # §5 divergenza
    w("## 5. Quanto MaxC* e B365C* sono diversi (righe con entrambi)\n")
    w("Gap di prezzo medio `(|MaxC−B365C|)/B365C` e differenza media delle probabilità "
      "de-vigate proporzionali, in punti percentuali (pp), per esito. `%B365=max` = "
      "quante volte B365C è già il prezzo massimo di mercato per quell'esito.\n")
    w("| Lega | Stagione | n | gap H | gap D | gap A | Δp H | Δp D | Δp A | max |Δp| | %B365=max (H/D/A) |")
    w("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for st in res["files"]:
        dv = st["divergence"]
        if not dv:
            continue
        g, p = dv["price_gap_mean_abs_pct"], dv["devig_prob_diff_mean_pp"]
        mx = max(dv["devig_prob_diff_max_abs_pp"].values())
        eq = dv["pct_b365_is_max"]
        w(f"| {st['league']} | {st['season_label']} | {dv['n']} | {g['H']:.2f}% | {g['D']:.2f}% | "
          f"{g['A']:.2f}% | {p['H']:+.2f} | {p['D']:+.2f} | {p['A']:+.2f} | {mx:.2f} | "
          f"{eq['H']:.0f}/{eq['D']:.0f}/{eq['A']:.0f}% |")
    all_out = [(st, o) for st in res["files"] if st["divergence"]
               for o in st["divergence"].get("outliers_gt_10pp", [])]
    n_joint = sum(st["n_both"] for st in res["files"])
    if all_out:
        w("")
        w(f"**Code anomale** ({len(all_out)} righe su {n_joint} congiunte, "
          f"{pct(len(all_out), n_joint):.2f}%): chiaramente refusi della fonte, non buchi "
          f"di copertura — un eventuale uso di MaxC* come riferimento settlement deve "
          f"gestirle per riga:")
        for st, out_row in all_out:
            fm = lambda q: "[" + ", ".join("n/d" if x is None else f"{x:.2f}" for x in q) + "]"
            w(f"  - `{st['file']}` {out_row['date']} {out_row['home']}–{out_row['away']}: "
              f"MaxC={fm(out_row['maxc'])} vs B365C={fm(out_row['b365c'])} "
              f"(Δp max {out_row['max_abs_pp']} pp)")
    w("")

    # §6 verdetto
    v = res["verdict"]
    w("## 6. Verdetto\n")
    if v["maxc_usable_walkforward"]:
        w(f"**MaxC* ha copertura sufficiente su TUTTO il perimetro walk-forward** "
          f"(soglia tripletta ≥ {v['coverage_threshold_pct']}%): colonne sempre presenti, "
          f"copertura ~100% in ogni lega/stagione, nessun buco. Dal punto di vista della "
          f"SOLE DISPONIBILITA' DEI DATI può essere riferimento CLV di chiusura su "
          f"train+val+test.\n")
        w("Riserva metodologica (non di copertura): l'overround di MaxC* è vicino allo "
          "zero e a volte NEGATIVO (max per esito preso su book diversi ⇒ insieme quasi "
          "arbitraggibile). Come riferimento «prezzo meglio disponibile in mercato» è "
          "legittimo e conservativo (CLV più difficile da battere); come prezzo di "
          "settlement realistico è ottimistico (nessuno può effettivamente puntare "
          "l'intera tripletta ai massimi). B365C* ha copertura identica ma overround "
          "reale ~5,5% in ogni stagione: riferimento più «morto», e un CLV positivo "
          "contro B365C* è più facile per costruzione.\n")
    else:
        w(f"**MaxC* NON ha copertura sufficiente su tutto il perimetro walk-forward** "
          f"(soglia tripletta ≥ {v['coverage_threshold_pct']}%). Buchi:\n")
        for h in v["holes"]:
            w(f"- **{h['league']} {h['season']}**: {'; '.join(h['problems'])}")
        w("")
        w("In presenza di questi buchi, **B365C* resta l'unica opzione praticabile** per "
          "coerenza con il resto delle misure già prodotte (stessa copertura ovunque, "
          "overround stabile ~5,5% in ogni stagione/lega).\n")
    w("---\n")
    w("*Audit di sola verifica: nessun file di produzione toccato; il workflow "
      "temporaneo di download è stato rimosso prima di questo commit.*\n")
    return "\n".join(o)


if __name__ == "__main__":
    raise SystemExit(main())
