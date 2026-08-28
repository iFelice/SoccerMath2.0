"""
update_xg.py - Scarica gli xG da Understat automaticamente
Stagione corrente: 2025/2026 (ID Understat = 2025)
"""

import requests
import json
import re
import base64
import codecs
import os
import time

# Configurazione campionati su Understat
# ID Lega: Serie A=11, Premier=9, La Liga=12, Bundesliga=20
# Season: Anno di inizio della stagione (2025 per il 2025/2026)
LEAGUES = {
    "serie_a": {"id": 11, "season": 2025},
    "premier_league": {"id": 9, "season": 2025},
    "la_liga": {"id": 12, "season": 2025},
    "bundesliga": {"id": 20, "season": 2025},
    "ligue_1": {"id": 13, "season": 2025},
}

# Mappatura nomi Understat -> Nomi usati dalla tua App
NAME_MAP = {
    # Serie A
    "Inter Milan": "Inter", "AC Milan": "Milan", "AS Roma": "Roma", "Juventus": "Juventus",
    "SS Lazio": "Lazio", "Atalanta": "Atalanta", "SSC Napoli": "Napoli", "ACF Fiorentina": "Fiorentina",
    "Bologna": "Bologna", "Torino": "Torino", "Udinese": "Udinese", "Genoa": "Genoa",
    "Cagliari": "Cagliari", "Empoli": "Empoli", "Hellas Verona": "Verona", "Lecce": "Lecce",
    "Parma Calcio 1913": "Parma", "Monza": "Monza", "Como": "Como", "Venezia": "Venezia",
    "Cremonese": "Cremonese", "Sassuolo": "Sassuolo", "Pisa": "Pisa",
    # Premier League
    "Manchester City": "Man City", "Manchester United": "Man United", "Tottenham Hotspur": "Tottenham",
    "Newcastle United": "Newcastle", "Aston Villa": "Aston Villa", "West Ham United": "West Ham",
    "Brighton and Hove Albion": "Brighton", "Wolverhampton Wanderers": "Wolves",
    "Crystal Palace": "Crystal Palace", "Nottingham Forest": "Nott'm Forest",
    "AFC Bournemouth": "Bournemouth", "Fulham": "Fulham", "Brentford": "Brentford",
    "Everton": "Everton", "Ipswich Town": "Ipswich", "Leicester City": "Leicester",
    "Southampton": "Southampton",
    # La Liga
    "Atletico Madrid": "Atletico Madrid", "Athletic Bilbao": "Athletic Club",
    "Real Sociedad": "Real Sociedad", "Celta Vigo": "Celta Vigo", "Rayo Vallecano": "Rayo Vallecano",
    "Deportivo Alaves": "Alaves", "Girona": "Girona", "Las Palmas": "Las Palmas",
    "Sevilla": "Sevilla", "Real Betis": "Betis", "Mallorca": "Mallorca", "Osasuna": "Osasuna",
    "Getafe": "Getafe", "Espanyol": "Espanyol", "Valladolid": "Valladolid", "Leganes": "Leganes",
    # Bundesliga
    "Bayern Munich": "Bayern", "Bayer 04 Leverkusen": "Leverkusen", "Borussia Dortmund": "Dortmund",
    "RB Leipzig": "Leipzig", "VfB Stuttgart": "Stuttgart", "Eintracht Frankfurt": "Frankfurt",
    "SC Freiburg": "Freiburg", "TSG Hoffenheim": "Hoffenheim", "VfL Wolfsburg": "Wolfsburg",
    "Union Berlin": "Union Berlin", "Borussia Mönchengladbach": "Monchengladbach",
    "1. FSV Mainz 05": "Mainz", "SV Werder Bremen": "Werder Bremen", "FC Augsburg": "Augsburg",
    "1. FC Heidenheim 1846": "Heidenheim", "VfL Bochum": "Bochum", "FC St. Pauli": "St. Pauli",
    "Holstein Kiel": "Holstein Kiel",

    # Ligue 1
    "Paris Saint-Germain": "PSG", "AS Monaco": "Monaco", "Monaco": "Monaco",
    "Olympique de Marseille": "Marseille", "Olympique Lyonnais": "Lyon",
    "Lille OSC": "Lille", "Lille": "Lille", "Stade Rennais FC": "Rennes",
    "OGC Nice": "Nice", "RC Lens": "Lens", "RC Strasbourg Alsace": "Strasbourg",
    "Stade de Reims": "Reims", "Stade Brestois 29": "Brest", "Toulouse FC": "Toulouse",
    "Montpellier HSC": "Montpellier", "FC Nantes": "Nantes", "AJ Auxerre": "Auxerre",
    "AS Saint-Étienne": "Saint-Etienne", "Angers SCO": "Angers", "Le Havre AC": "Le Havre"
}

def fetch_xg_understat(league_key, league_id, season):
    url = f"https://understat.com/league/{league_id}/{season}"
    print(f"Fetching {url}...")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=20)
        
        if resp.status_code == 404:
            print(f"  Stagione {season} non ancora disponibile su Understat per questa lega.")
            return None
        if resp.status_code != 200:
            print(f"  Errore HTTP: {resp.status_code}")
            return None

        match = re.search(r'var teamsData = JSON.parse\(\'(.*?)\'\);', resp.text)
        if not match:
            print("  Struttura pagina Understat cambiata o dati non trovati.")
            return None

        encoded_data = match.group(1)
        decoded_bytes = base64.b64decode(encoded_data)
        decoded_str = codecs.escape_decode(decoded_bytes)[0].decode('utf-8')
        
        teams_data = json.loads(decoded_str)
        
        result = {}
        for team_id, team_info in teams_data.items():
            understat_name = team_info.get("title", "")
            clean_name = NAME_MAP.get(understat_name, understat_name)
            
            history = team_info.get("history", [])
            if not history:
                continue
            
            total_xg = sum(float(m.get("xG", 0)) for m in history)
            total_xga = sum(float(m.get("xGA", 0)) for m in history)
            matches_played = len(history)
            
            result[clean_name] = {
                "xG_avg": round(total_xg / matches_played, 3) if matches_played > 0 else 0,
                "xGA_avg": round(total_xga / matches_played, 3) if matches_played > 0 else 0
            }
            
        return result
        
    except Exception as e:
        print(f"  Errore scraping Understat: {e}")
        return None

def main():
    os.makedirs("database", exist_ok=True)
    successi = 0

    for league_key, info in LEAGUES.items():
        data = fetch_xg_understat(league_key, info["id"], info["season"])
        if data and len(data) >= 10:
            path = f"database/xg_{league_key}.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"  Salvato: {path} ({len(data)} squadre)")
            successi += 1
        else:
            print(f"  SKIP {league_key} - Dati insufficienti o non disponibili")
        
        time.sleep(3)

    print(f"\nCompletato: {successi}/{len(LEAGUES)} campionati aggiornati")

if __name__ == "__main__":
    main()
