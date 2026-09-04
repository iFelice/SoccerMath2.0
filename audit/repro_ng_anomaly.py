"""
Riproduzione anomalia Top Mix: NG ~ 99.8% (Premier League).

Percorso identico alla produzione:
  get_league_engine() -> get_full_poisson_two_heads() -> _two_heads_from_lambdas()
  -> _poisson_market() -> GG/NG
Senza API key: si scansionano TUTTE le coppie casa/trasferta delle squadre
presenti nel database (equivalenti a qualsiasi fixture della prossima giornata).
"""

import sys, os, math, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "SoccerMath"))

from config import clean_name
from app import get_league_engine, get_full_poisson_two_heads, _clip_lambda

LEAGUE = sys.argv[1] if len(sys.argv) > 1 else "Premier League"

print(f"=== Analisi anomalia NG su: {LEAGUE} ===\n")
team_stats, avg_h, avg_a, df = get_league_engine(LEAGUE)
print(f"avg_h={avg_h:.4f}  avg_a={avg_a:.4f}  squadre={len(team_stats)}\n")

# --- 1. Squadre con att0_pure / def0_pure anomali (vicino a zero) ---
print("--- Squadre con att0_pure/def0_pure < 0.30 ---")
for t, s in sorted(team_stats.items(), key=lambda kv: min(kv[1]["att0_pure"], kv[1]["def0_pure"])):
    if min(s["att0_pure"], s["def0_pure"]) < 0.30:
        print(f"  {t:22s} att0_pure={s['att0_pure']:.4f} def0_pure={s['def0_pure']:.4f} "
              f"att={s['att']:.3f} def={s['def']:.3f} val={s['val']}")
print()

# --- 2. valori intermedi e lambda effettive per le squadre anomale ---
xg_file = {
    "Premier League": "xg_premier_league.json", "Serie A": "xg_serie_a.json",
    "La Liga": "xg_la_liga.json", "Bundesliga": "xg_bundesliga.json", "Ligue 1": "xg_ligue_1.json",
}[LEAGUE]
xg_path = os.path.join(os.path.dirname(__file__), "..", "SoccerMath", "database", xg_file)
xg_data = json.load(open(xg_path)) if os.path.exists(xg_path) else {}

anomalie = []
print("--- Scansione tutte le coppie (NG > 95%) ---")
teams = sorted(team_stats.keys())
for h in teams:
    for a in teams:
        if h == a:
            continue
        hs, as_ = team_stats[h], team_stats[a]
        attp_h = hs.get("att0_pure"); defp_h = hs.get("def0_pure")
        attp_a = as_.get("att0_pure"); defp_a = as_.get("def0_pure")
        base_pure_h = attp_h * defp_a * avg_h
        base_pure_a = attp_a * defp_h * avg_a
        lam_h = _clip_lambda(base_pure_h)
        lam_a = _clip_lambda(base_pure_a)
        m = get_full_poisson_two_heads(hs, as_, avg_h, avg_a)
        ng = 1 - m["gg"]
        if ng > 0.95:
            clip_h = " (CLIPPED!)" if base_pure_h < 0.002479 else ""
            clip_a = " (CLIPPED!)" if base_pure_a < 0.002479 else ""
            anomalie.append((h, a, lam_h, lam_a, m["gg"], ng))
            if len(anomalie) <= 12:
                print(f"\n  {h} vs {a}")
                print(f"    lambda_pure_h={base_pure_h:.6f}{clip_h} -> effettiva {lam_h:.6f}")
                print(f"    lambda_pure_a={base_pure_a:.6f}{clip_a} -> effettiva {lam_a:.6f}")
                print(f"    GG={m['gg']*100:.2f}%  NG={ng*100:.2f}%  U2.5={m['u25']*100:.1f}%")
                print(f"    [xG JSON] home in file: {h in xg_data}  away in file: {a in xg_data}")
                print(f"    [intermedi] att0_pure_h={attp_h:.4f} def0_pure_h={defp_h:.4f} "
                      f"att0_pure_a={attp_a:.4f} def0_pure_a={defp_a:.4f}")

print(f"\nTotale coppie con NG>95%: {len(anomalie)} su {len(teams)*(len(teams)-1)}")
if anomalie:
    squadre_coinvolte = sorted({x[0] for x in anomalie} | {x[1] for x in anomalie})
    print("Squadre coinvolte:", squadre_coinvolte)
