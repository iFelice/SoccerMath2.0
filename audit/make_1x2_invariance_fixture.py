"""
make_1x2_invariance_fixture.py — Genera il fixture del test di regressione
``SoccerMath/test_1x2_invariance.py``.

Campiona partite REALI dal database attuale (5 leghe), calcola le probabilita'
con ``app.get_full_poisson_two_heads`` usando gli stats di
``app.get_league_engine`` e salva input (dizionari squadra + avg_h/avg_a) e
output (1/X/2 e totali) in ``SoccerMath/test_fixtures/1x2_invariance.json``.

Il fixture congela l'esito "PRIMA" di una modifica: il test permanente
ri-executa ``get_full_poisson_two_heads`` sugli input congelati e pretende
l'1X2 bit-identico (max abs diff 0.0), come fatto in audit.

Uso:
    python audit/make_1x2_invariance_fixture.py [--samples-per-league 12] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from config import LEAGUES_CONFIG  # noqa: E402
import app as prod_app  # noqa: E402

DEFAULT_OUT_PATH = os.path.join(_REPO_ROOT, "SoccerMath", "test_fixtures",
                                "1x2_invariance.json")

STAT_KEYS = ("att", "def", "att0", "def0", "att0_pure", "def0_pure", "val")


def sample_matches(df, stats, n):
    """Indici deterministici (passo uniforme) su partite con entrambe le
    squadre presenti negli stats del motore."""
    idxs = []
    total = len(df)
    if total == 0:
        return idxs
    step = max(1, total // n)
    i = 0
    while len(idxs) < n and i < total:
        h = df.at[i, "HomeClean"]
        a = df.at[i, "AwayClean"]
        if h in stats and a in stats:
            idxs.append(i)
        i += step
    return idxs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples-per-league", type=int, default=12)
    ap.add_argument("--out", default=DEFAULT_OUT_PATH)
    args = ap.parse_args()
    out_path = args.out

    entries = []
    for camp_key in LEAGUES_CONFIG:
        res = prod_app.get_league_engine(camp_key)
        if not res:
            raise SystemExit(f"get_league_engine({camp_key!r}) non ha prodotto dati")
        stats, avg_h, avg_a, df = res
        idxs = sample_matches(df, stats, args.samples_per_league)
        for i in idxs:
            row = df.iloc[i]
            hs = {k: float(stats[row.HomeClean][k]) for k in STAT_KEYS}
            as_ = {k: float(stats[row.AwayClean][k]) for k in STAT_KEYS}
            out = prod_app.get_full_poisson_two_heads(hs, as_, avg_h, avg_a)
            entries.append({
                "league": camp_key,
                "date": str(row.Date),
                "home": row.HomeClean,
                "away": row.AwayClean,
                "avg_h": float(avg_h),
                "avg_a": float(avg_a),
                "hs": hs,
                "as": as_,
                "expected": {k: float(v) for k, v in out.items()},
            })
        print(f"{camp_key}: {len(idxs)} partite campionate "
              f"(avg_h={avg_h:.4f}, avg_a={avg_a:.4f})")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "description": (
                "Fixture di regressione 1X2: input (stats squadra + medie gol) "
                "e output di app.get_full_poisson_two_heads su partite reali. "
                "Generato PRIMA del cambio point-in-time della testa Totali: "
                "l'1X2 deve restare bit-identico (max abs diff 0.0)."
            ),
            "generated_by": "audit/make_1x2_invariance_fixture.py",
            "entries": entries,
        }, f, ensure_ascii=False, indent=1)
    print(f"\nScritto {out_path} ({len(entries)} partite)")


if __name__ == "__main__":
    main()
