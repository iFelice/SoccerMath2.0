"""
scraper_xg.py
Legge le medie xG stagionali dai file JSON locali.

I file ``database/xg_<lega>.json`` sono PRODOTTI DERIVATI dell'archivio
per-partita (`SoccerMath/update_xg.py`, alimentato dall'unica acquisizione
Understat `update_all_xg_db.py`): qui non si scarica nulla.

Interfaccia invariata:
    get_understat_xg(league_name) -> {nome: {xG_avg, xGA_avg, matches}}
"""

import json
import os
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

from config import LEAGUE_FILE_MAP as _CONFIG_FILE_MAP

# Percorsi assoluti risolti in config (DATABASE_DIR): funzionano da qualunque
# working directory. Restano i percorsi relativi storici come fallback.
LEAGUE_FILE_MAP = dict(_CONFIG_FILE_MAP)

_LEGACY_RELATIVE_MAP = {
    "Serie A":        "database/xg_serie_a.json",
    "Premier League": "database/xg_premier_league.json",
    "La Liga":        "database/xg_la_liga.json",
    "Bundesliga":     "database/xg_bundesliga.json",
    "Ligue 1":        "database/xg_ligue_1.json",
}


def get_understat_xg(league_name):
    candidates = [LEAGUE_FILE_MAP.get(league_name),
                  _LEGACY_RELATIVE_MAP.get(league_name)]
    file_path = next((p for p in candidates if p and os.path.exists(p)), None)
    if not file_path:
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
