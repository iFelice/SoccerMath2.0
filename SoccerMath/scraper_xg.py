"""
scraper_xg.py
Legge gli xG da file JSON locali aggiornati da GitHub Actions (update_xg.py).
Interfaccia invariata: get_understat_xg(league_name) → {nome: {xG_avg, xGA_avg}}
"""

import json
import os
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

LEAGUE_FILE_MAP = {
    "Serie A":        "database/xg_serie_a.json",
    "Premier League": "database/xg_premier_league.json",
    "La Liga":        "database/xg_la_liga.json",
    "Bundesliga":     "database/xg_bundesliga.json",
    "Ligue 1":        "database/xg_ligue_1.json",
}


def get_understat_xg(league_name):
    file_path = LEAGUE_FILE_MAP.get(league_name)
    if not file_path:
        return None
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data and len(data) >= 10:
            return data
        return None
    except Exception as e:
        logging.error(f"Errore lettura xG da file {file_path}: {e}")
        return None


def get_market_values():
    return {
        "Inter": 600, "Milan": 550, "Juventus": 500, "Napoli": 450, "Atalanta": 400,
        "Roma": 350, "Lazio": 300, "Fiorentina": 250, "Bologna": 200, "Torino": 180,
        "Monza": 120, "Genoa": 110, "Lecce": 80, "Verona": 75, "Udinese": 90,
        "Cagliari": 70, "Empoli": 65, "Parma": 60, "Como": 55, "Venezia": 50,
        "Cremonese": 45,
        "Man City": 900, "Arsenal": 850, "Liverpool": 900, "Chelsea": 750,
        "Man United": 600, "Tottenham": 500, "Newcastle": 450, "Aston Villa": 400,
        "West Ham": 300, "Brighton": 280,
        "Real Madrid": 1100, "Barcelona": 1000, "Atletico Madrid": 700,
        "Athletic Club": 350, "Villarreal": 300,
        "Bayern": 900, "Leverkusen": 600, "Dortmund": 550, "Leipzig": 450,
        "Frankfurt": 300,
    }
