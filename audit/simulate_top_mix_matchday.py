"""
Simulazione Top Mix Premier League — prossima giornata (matchday 3, 5-6/09/2026).
Replica ESATTAMENTE il calcolo per-partita di fetch_and_calc_top_mix():
stesse formule, stessi filtri (confidence, soglia disaccordo Elo), stesso ordinamento.
Le fixture sono quelle reali del calendario (fonte: archivio Understat 2026/27,
nomi convertiti in stile Football-Data).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "SoccerMath"))

from datetime import datetime, timezone
from config import clean_name
from app import (get_league_engine, get_full_poisson_two_heads,
                 select_next_matchday_matches)
from models.elo_engine import predict_elo_probs

FIXTURES_MD3 = [  # (utcDate, home football-data style, away)
    ("2026-09-04T19:00:00Z", "Ipswich", "Liverpool"),
    ("2026-09-05T11:30:00Z", "Newcastle", "Bournemouth"),
    ("2026-09-05T14:00:00Z", "Brentford", "Sunderland"),
    ("2026-09-05T14:00:00Z", "Brighton", "Leeds United"),
    ("2026-09-05T14:00:00Z", "Fulham", "Crystal Palace"),
    ("2026-09-05T14:00:00Z", "Man City", "Coventry City"),
    ("2026-09-05T14:00:00Z", "Nott'm Forest", "Tottenham"),
    ("2026-09-05T16:30:00Z", "Hull City", "Aston Villa"),
    ("2026-09-06T13:00:00Z", "Everton", "Man United"),
    ("2026-09-06T15:30:00Z", "Arsenal", "Chelsea"),
]

NOW = datetime(2026, 9, 4, 15, 0, 0, tzinfo=timezone.utc)

matches = [{"utcDate": d, "homeTeam": {"shortName": h}, "awayTeam": {"shortName": a},
            "matchday": 3, "id": i} for i, (d, h, a) in enumerate(FIXTURES_MD3, 1)]
selected = select_next_matchday_matches(matches, now=NOW)
print(f"Selezionate {len(selected)} partite (prossima giornata)\n")

team_stats, avg_h, avg_a, _ = get_league_engine("Premier League")
all_preds = []
for m in selected:
    h = m['homeTeam'].get('shortName') or m['homeTeam'].get('name', '?')
    a = m['awayTeam'].get('shortName') or m['awayTeam'].get('name', '?')
    h_s = team_stats.get(clean_name(h), {"att": 1.0, "def": 1.0})
    a_s = team_stats.get(clean_name(a), {"att": 1.0, "def": 1.0})
    m_poisson = get_full_poisson_two_heads(h_s, a_s, avg_h, avg_a)
    mercati = {
        f"Vittoria {h}": m_poisson["1"], "Pareggio": m_poisson["X"], f"Vittoria {a}": m_poisson["2"],
        "Over 2.5": 1 - m_poisson["u25"], "Under 2.5": m_poisson["u25"],
        "GG": m_poisson["gg"], "NG": 1 - m_poisson["gg"]
    }
    best_mkt = max(mercati, key=mercati.get)
    poisson_prob = mercati[best_mkt]
    elo_prob = poisson_prob
    try:
        elo_p = predict_elo_probs(h, a, "Premier League")
        if best_mkt == f"Vittoria {h}":
            elo_prob = elo_p["1"]
        elif best_mkt == f"Vittoria {a}":
            elo_prob = elo_p["2"]
        elif best_mkt == "Pareggio":
            elo_prob = elo_p["X"]
    except Exception:
        pass
    if best_mkt in ["Over 2.5", "Under 2.5", "GG", "NG"]:
        confidence = poisson_prob
        min_conf = 0.60
    else:
        confidence = 0.6 * poisson_prob + 0.4 * elo_prob
        min_conf = 0.55
    if confidence >= min_conf and abs(poisson_prob - elo_prob) < 0.25:
        all_preds.append({"home": h, "away": a, "market": best_mkt,
                          "prob": round(confidence * 100, 1),
                          "poisson": round(poisson_prob * 100, 1)})

print(f"{'#':>2} {'partita':38s} {'mercato':18s} {'conf%':>6} {'poisson%':>9}")
for i, p in enumerate(sorted(all_preds, key=lambda x: x['prob'], reverse=True)[:10], 1):
    print(f"{i:>2} {p['home']+' - '+p['away']:38s} {p['market']:18s} {p['prob']:>6} {p['poisson']:>9}")
