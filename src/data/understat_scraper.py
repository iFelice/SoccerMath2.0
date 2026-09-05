"""DEPRECATO - non fa parte della pipeline.

L'UNICA acquisizione Understat di SoccerMath e' ``update_all_xg_db.py`` (root
del repository), che produce ``SoccerMath/database/xG archivio <lega>.json``;
le medie stagionali si derivano da quell'archivio con
``python SoccerMath/update_xg.py``.

Questo file resta solo come traccia dello scraper esplorativo usato per la
Serie A: non e' importato da nessun modulo e non deve essere schedulato.
Eseguendolo serve ``--force``, per evitare che diventi una seconda fonte di
dati disallineata dall'archivio.
"""

import json
import os
import re
import sys
import time
import requests

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        ' (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': (
        'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
    ),
    'Accept-Language': 'en-US,en;q=0.5',
}

LEAGUE = 'Serie_A'
SEASONS = [2024, 2025]


def fetch_league_xg_matches(league_name, season):
  """Scarica ed estrae le partite giocate con i relativi xG per la Serie A."""
  url = f'https://understat.com/league/{league_name}/{season}'

  try:
    response = requests.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()

    # Cerca la variabile JavaScript 'datesData' nell'HTML
    match = re.search(
        r"var datesData\s*=\s*JSON\.parse\('([^']+)'\);", response.text
    )
    if not match:
      print(f'  ⚠️ Impossibile trovare datesData per {league_name} ({season})')
      return []

    raw_json = match.group(1).encode('utf-8').decode('unicode_escape')
    data = json.loads(raw_json)

    extracted_matches = []
    for item in data:
      if item.get('isResult'):  # Solo partite già giocate
        extracted_matches.append({
            'match_id': item['id'],
            'datetime': item['datetime'],
            'league': league_name,
            'season': season,
            'home_team': item['h']['title'],
            'away_team': item['a']['title'],
            'goals_home': int(item['goals']['h']),
            'goals_away': int(item['goals']['a']),
            'xg_home': float(item['xG']['h']),
            'xg_away': float(item['xG']['a']),
            'forecast_w': float(item['forecast']['w']),
            'forecast_d': float(item['forecast']['d']),
            'forecast_l': float(item['forecast']['l']),
        })

    print(f'  ✓ Serie A ({season}): recuperate {len(extracted_matches)} partite.')
    return extracted_matches

  except Exception as e:
    print(f'  ❌ Errore durante il fetch di Serie A ({season}): {e}')
    return []


def run_test():
  all_data = {}
  print('=== TEST ESTRAZIONE XG SERIE A (2024 - 2025) ===')

  for season in SEASONS:
    matches = fetch_league_xg_matches(LEAGUE, season)
    all_data[str(season)] = matches
    time.sleep(2)  # Pausa di sicurezza

  # Definizione del percorso esatto: SoccerMath/database/xG sorici serie A.json
  base_dir = os.path.abspath(
      os.path.join(os.path.dirname(__file__), '..', '..')
  )
  output_dir = os.path.join(base_dir, 'SoccerMath', 'database')
  os.makedirs(output_dir, exist_ok=True)

  output_path = os.path.join(output_dir, 'xG sorici serie A.json')

  with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(all_data, f, indent=4, ensure_ascii=False)

  print(f'\n✅ File storico salvato con successo in: {output_path}')


if __name__ == '__main__':
  if '--force' not in sys.argv:
    print('Script deprecato: usa update_all_xg_db.py (acquisizione) e '
          'SoccerMath/update_xg.py (medie derivate). Con --force lo esegui '
          'comunque, ma i suoi file non fanno parte della pipeline.')
    raise SystemExit(1)
  run_test()
