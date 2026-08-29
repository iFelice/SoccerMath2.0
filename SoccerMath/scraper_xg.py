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
    from config import get_market_values as _cfg_mkt
    return _cfg_mkt()
