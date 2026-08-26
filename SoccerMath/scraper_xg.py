"""
scraper_xg.py
Legge gli xG da file JSON locali aggiornati da GitHub Actions (update_xg.py).
Interfaccia invariata: get_understat_xg(league_name) → {nome: {xG_avg, xGA_avg}}
"""

import json
import os
from config import LEAGUE_FILE_MAP, MARKET_VALUES, get_market_values


def get_understat_xg(league_name):
    """
    Legge i dati xG salvati per il campionato specificato.
    """
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
        print(f"Errore lettura xG da file: {e}")
        return None

