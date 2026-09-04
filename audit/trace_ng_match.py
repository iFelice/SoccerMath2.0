"""
Trace completo dei valori intermedi per le partite anomale (Premier League).
Stampa: avg_h/avg_a, xG/xGA, att0_pure/def0_pure, base_pure_*, lambda passate
a _poisson_market(), P(GG), P(NG).
"""
import sys, os, math, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "SoccerMath"))

from config import clean_name
from app import get_league_engine, get_full_poisson_two_heads, _clip_lambda

team_stats, avg_h, avg_a, df = get_league_engine("Premier League")
xg_data = json.load(open(os.path.join(os.path.dirname(__file__), "..", "SoccerMath",
                                      "database", "xg_premier_league.json")))

FIXTURES = [("Man City", "Coventry City"), ("Hull City", "Aston Villa")]

print(f"avg_h={avg_h:.4f}  avg_a={avg_a:.4f}")
print(f"xG JSON (stagione 2025/26, parziale): {len(xg_data)} chiavi\n")

for h_name, a_name in FIXTURES:
    hc, ac = clean_name(h_name), clean_name(a_name)
    hs, as_ = team_stats[hc], team_stats[ac]
    attp_h, defp_h = hs["att0_pure"], hs["def0_pure"]
    attp_a, defp_a = as_["att0_pure"], as_["def0_pure"]
    base_pure_h = attp_h * defp_a * avg_h
    base_pure_a = attp_a * defp_h * avg_a
    lam_h, lam_a = _clip_lambda(base_pure_h), _clip_lambda(base_pure_a)
    m = get_full_poisson_two_heads(hs, as_, avg_h, avg_a)
    gg, ng = m["gg"], 1 - m["gg"]
    print(f"=== {h_name} vs {a_name} ===")
    print(f"  casa {h_name}:  xG/xGA nel JSON: {xg_data.get(hc, 'ASSENTE')}")
    print(f"       att0_pure={attp_h:.6f}  def0_pure={defp_h:.6f}")
    print(f"  trasferta {a_name}:  xG/xGA nel JSON: {xg_data.get(ac, 'ASSENTE')}")
    print(f"       att0_pure={attp_a:.6f}  def0_pure={defp_a:.6f}")
    print(f"  base_pure_h = {attp_h:.6f} * {defp_a:.6f} * {avg_h:.4f} = {base_pure_h:.8f}"
          f"   -> lambda a _poisson_market: {lam_h:.6f}"
          f"{'  (CLIPPATA da ~0 a exp(-6))' if base_pure_h < 0.002479 else ''}")
    print(f"  base_pure_a = {attp_a:.6f} * {defp_h:.6f} * {avg_a:.4f} = {base_pure_a:.8f}"
          f"   -> lambda a _poisson_market: {lam_a:.6f}"
          f"{'  (CLIPPATA da ~0 a exp(-6))' if base_pure_a < 0.002479 else ''}")
    print(f"  P(GG) = (1-e^(-{lam_h:.5f}))*(1-e^(-{lam_a:.5f})) = {gg*100:.2f}%")
    print(f"  P(NG) = {ng*100:.2f}%   U2.5={m['u25']*100:.1f}%  1={m['1']*100:.1f}%  X={m['X']*100:.1f}%  2={m['2']*100:.1f}%\n")

# Quante partite ha ciascuna squadra nel DB e gol F/T (dump esplicativo)
for t in ["Hull City", "Coventry City"]:
    h = df[df['HomeClean'] == t]; a = df[df['AwayClean'] == t]
    gf = (h['FTHG'].sum() + a['FTAG'].sum()); ga = (h['FTAG'].sum() + a['FTHG'].sum())
    print(f"DB {t}: partite={len(h)+len(a)} (home {len(h)}, away {len(a)}), "
          f"GF={gf}, GA={ga}  -> att_raw={(0 if len(h)==0 else h['FTHG'].mean()/avg_h)/2 + (0 if len(a)==0 else a['FTAG'].mean()/avg_a)/2:.4f} "
          f"def_raw={(0 if len(h)==0 else h['FTAG'].mean()/avg_a)/2 + (0 if len(a)==0 else a['FTHG'].mean()/avg_h)/2:.4f}")
