import json
import os
import soccerdata as sd

LEAGUES_MAP = {
    'ITA-Serie A': 'xG archivio serie A.json',
    'ENG-Premier League': 'xG archivio premier league.json',
    'ESP-La Liga': 'xG archivio la liga.json',
    'GER-Bundesliga': 'xG archivio bundesliga.json',
    'FRA-Ligue 1': 'xG archivio ligue 1.json'
}

# Formattazione corretta delle stagioni per soccerdata (dalla 2022/23 alla 2026/27)
SEASONS = ['2223', '2324', '2425', '2526', '2627']

def update_all_databases():
    output_dir = os.path.join('SoccerMath', 'database')
    os.makedirs(output_dir, exist_ok=True)

    output_columns = {
        'season_id': 'season',
        'game_id': 'id',
        'date': 'date',
        'home_team': 'home_team',
        'away_team': 'away_team',
        'home_goals': 'home_goals',
        'away_goals': 'away_goals',
        'home_xg': 'home_xg',
        'away_xg': 'away_xg',
        'is_result': 'is_result'
    }

    for sd_league, filename in LEAGUES_MAP.items():
        print(f"📥 Scaricamento dati per: {sd_league} (Stagioni: {SEASONS})...")
        try:
            # no_cache=True per azzerare vecchie risposte salvate
            understat = sd.Understat(leagues=sd_league, seasons=SEASONS, no_cache=True)
            df = understat.read_schedule().reset_index()

            df_selected = df[list(output_columns.keys())].rename(columns=output_columns)
            df_selected['date'] = df_selected['date'].astype(str)

            data_json = df_selected.to_dict(orient='records')
            output_path = os.path.join(output_dir, filename)

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data_json, f, ensure_ascii=False, indent=2)

            print(f"✅ Salvate {len(data_json)} partite totali in: {output_path}\n")

        except Exception as e:
            print(f"❌ Errore durante lo scaricamento di {sd_league}: {e}\n")

if __name__ == "__main__":
    update_all_databases()
