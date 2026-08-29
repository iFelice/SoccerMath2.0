"""
config.py - Configurazione centralizzata per M4-analist
Gestione di segreti, campionati, stagioni, valori di mercato e mappature squadre.
"""

import os
from pathlib import Path

# Tentativo di caricamento .env con python-dotenv; fallback se non installato
try:
    from dotenv import load_dotenv
    # Carica il file .env se presente nella root del progetto
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=env_path)
except ImportError:
    # Fallback semplice per caricare un eventuale file .env se dotenv non è installato
    env_file = Path(__file__).resolve().parent / ".env"
    if env_file.exists():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip('"').strip("'")
                        if k and k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass


def _get_secret(key: str, default: str = "") -> str:
    """
    Recupera una chiave di configurazione cercando prima nelle variabili d'ambiente,
    poi nei secrets di Streamlit (se disponibile), con fallback su default.
    """
    val = os.getenv(key)
    if val:
        return val

    # Controllo Streamlit secrets se in ambiente Streamlit
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass

    return default


# ==========================================
# 1. API KEYS E CREDENZIALI
# ==========================================
FOOTBALL_DATA_API_KEY = _get_secret("FOOTBALL_DATA_API_KEY")
API_KEY_DATA = FOOTBALL_DATA_API_KEY  # Alias per retrocompatibilità

ODDS_API_KEY = _get_secret("ODDS_API_KEY", _get_secret("API_KEY_ODDS", ""))
API_KEY_ODDS = ODDS_API_KEY  # Alias per retrocompatibilità

GROQ_API_KEY = _get_secret("GROQ_API_KEY", "")
JSONBIN_API_KEY = _get_secret("JSONBIN_API_KEY", "")
JSONBIN_BIN_ID = _get_secret("JSONBIN_BIN_ID", "")


# ==========================================
# 2. GESTIONE STAGIONI
# ==========================================
# Stagione corrente di default: 2026/2027 (anno inizio: 2026)
CURRENT_SEASON = os.getenv("M4_CURRENT_SEASON", "2026/2027")
CURRENT_SEASON_START_YEAR = int(os.getenv("M4_CURRENT_SEASON_START_YEAR", "2026"))

# Stagioni storiche supportate
HISTORICAL_SEASONS = ["2025/2026", "2024/2025", "2023/2024", "2022/2023"]
ALL_SEASONS = [CURRENT_SEASON] + [s for s in HISTORICAL_SEASONS if s != CURRENT_SEASON]


# ==========================================
# 3. PERCORSI DIRECTORY E FILE
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
DATABASE_DIR = BASE_DIR / "database"
PREDICTIONS_FILE = str(DATABASE_DIR / "predictions.json")

# ==========================================
# 4b. HOME ADVANTAGE ELO PER CAMPIONATO
# ==========================================
LEAGUE_HOME_ADVANTAGE = {
    "Serie A": 55.0,
    "Premier League": 60.0,
    "La Liga": 58.0,
    "Bundesliga": 70.0,
    "Ligue 1": 56.0,
}
# ==========================================
# 4. CONFIGURAZIONE CAMPIONATI
# ==========================================
# Supporto a 5 campionati: Serie A, Premier League, La Liga, Bundesliga, Ligue 1
LEAGUES_CONFIG = {
    "Serie A": {
        "code": "SA",
        "name": "Serie A",
        "short_name": "SerieA",
        "understat_id": 11,
        "understat_slug": "serie_a",
        "db_prefix": "SerieA",
        "base_csv": str(DATABASE_DIR / "SerieA.csv"),
        "live_csv": str(DATABASE_DIR / "SerieA_Live.csv"),
        "xg_json": str(DATABASE_DIR / "xg_serie_a.json"),
    },
    "Premier League": {
        "code": "PL",
        "name": "Premier League",
        "short_name": "Premier",
        "understat_id": 9,
        "understat_slug": "premier_league",
        "db_prefix": "Premier",
        "base_csv": str(DATABASE_DIR / "PremierLeague.csv"),
        "live_csv": str(DATABASE_DIR / "Premier_Live.csv"),
        "xg_json": str(DATABASE_DIR / "xg_premier_league.json"),
    },
    "La Liga": {
        "code": "PD",
        "name": "La Liga",
        "short_name": "LaLiga",
        "understat_id": 12,
        "understat_slug": "la_liga",
        "db_prefix": "LaLiga",
        "base_csv": str(DATABASE_DIR / "LaLiga.csv"),
        "live_csv": str(DATABASE_DIR / "LaLiga_Live.csv"),
        "xg_json": str(DATABASE_DIR / "xg_la_liga.json"),
    },
    "Bundesliga": {
        "code": "BL1",
        "name": "Bundesliga",
        "short_name": "Bundesliga",
        "understat_id": 20,
        "understat_slug": "bundesliga",
        "db_prefix": "Bundesliga",
        "base_csv": str(DATABASE_DIR / "Bundesliga.csv"),
        "live_csv": str(DATABASE_DIR / "Bundesliga_Live.csv"),
        "xg_json": str(DATABASE_DIR / "xg_bundesliga.json"),
    },
    "Ligue 1": {
        "code": "FL1",
        "name": "Ligue 1",
        "short_name": "Ligue1",
        "understat_id": 13,
        "understat_slug": "ligue_1",
        "db_prefix": "Ligue1",
        "base_csv": str(DATABASE_DIR / "Ligue1.csv"),
        "live_csv": str(DATABASE_DIR / "Ligue1_Live.csv"),
        "xg_json": str(DATABASE_DIR / "xg_ligue_1.json"),
    },
}

# Mapping di compatibilità per scraper_xg
LEAGUE_FILE_MAP = {
    name: info["xg_json"] for name, info in LEAGUES_CONFIG.items()
}

# Mapping per update_db.py (indicizzato per short_name o name)
CAMPIONATI_UPDATE_DB = {
    info["short_name"]: {
        "id": info["code"],
        "name": name,
        "live_path": info["live_csv"],
        "cols_home": "HomeTeam",
        "cols_away": "AwayTeam",
    }
    for name, info in LEAGUES_CONFIG.items()
}

# Mapping per update_xg.py
LEAGUES_UNDERSTAT = {
    info["understat_slug"]: {
        "id": info["understat_id"],
        "season": CURRENT_SEASON_START_YEAR,
        "name": name,
        "json_path": info["xg_json"],
    }
    for name, info in LEAGUES_CONFIG.items()
}

# Mapping rapido nome -> codice Football-Data (es. "Serie A" -> "SA")
LEAGUE_CODE_MAP = {name: info["code"] for name, info in LEAGUES_CONFIG.items()}
# Aggiunta alias (es. "Premier" -> "PL")
LEAGUE_CODE_MAP.update({info["short_name"]: info["code"] for info in LEAGUES_CONFIG.values()})

# Mapping rapido nome -> prefisso file (es. "Premier League" -> "Premier")
LEAGUE_PREFIX_MAP = {name: info["db_prefix"] for name, info in LEAGUES_CONFIG.items()}
LEAGUE_PREFIX_MAP.update({info["short_name"]: info["db_prefix"] for info in LEAGUES_CONFIG.values()})


# ==========================================
# 4c. FILE DATABASE DI UN CAMPIONATO
# ==========================================
def get_league_config(camp_key: str) -> dict:
    """Ritrova la config di un campionato da nome esteso, short_name o db_prefix."""
    if camp_key in LEAGUES_CONFIG:
        return LEAGUES_CONFIG[camp_key]
    for info in LEAGUES_CONFIG.values():
        if camp_key in (info.get("short_name"), info.get("db_prefix"), info.get("name")):
            return info
    return {}


def get_league_db_files(camp_key: str) -> list:
    """
    Elenca i CSV locali di un campionato in ordine di priorita crescente:
    il file piu' avanti nella lista vince sui duplicati (drop_duplicates keep='last'),
    quindi gli storici < base < live (il live e' quello aggiornato da GitHub Actions).

    Si cercano sia i pattern derivati dal prefisso (Premier_2024.csv, Premier_Live.csv,
    Premier.csv) sia i percorsi dichiarati in LEAGUES_CONFIG, perche' alcuni file
    hanno un nome non derivabile dal db_prefix: e' il caso di PremierLeague.csv,
    che con prefisso 'Premier' altrimenti non verrebbe mai letto.
    """
    info = get_league_config(camp_key)
    if not info:
        return []
    prefix = info.get("db_prefix") or info.get("short_name") or ""

    groups = [
        sorted(str(p) for p in DATABASE_DIR.glob(f"{prefix}_20*.csv")),   # stagioni storiche
        [str(DATABASE_DIR / f"{prefix}.csv")],                             # base (pattern)
        [str(info["base_csv"])] if info.get("base_csv") else [],           # base (config)
        [str(DATABASE_DIR / f"{prefix}_Live.csv")],                        # live (pattern)
        [str(info["live_csv"])] if info.get("live_csv") else [],           # live (config)
    ]

    files, seen = [], set()
    for group in groups:
        for f in group:
            if f not in seen and os.path.exists(f):
                seen.add(f)
                files.append(f)
    return files


# ==========================================
# 5. VALORI DI MERCATO DELLE SQUADRE
# ==========================================
MARKET_VALUES = {
    # Serie A
    "Inter": 600, "Milan": 550, "Juventus": 500, "Napoli": 450, "Atalanta": 400,
    "Roma": 350, "Lazio": 300, "Fiorentina": 250, "Bologna": 200, "Torino": 180,
    "Monza": 120, "Genoa": 110, "Lecce": 80, "Verona": 75, "Udinese": 90,
    "Cagliari": 70, "Empoli": 65, "Parma": 60, "Como": 55, "Venezia": 50,
    "Cremonese": 45, "Sassuolo": 70, "Pisa": 40,

    # Premier League
    "Man City": 900, "Arsenal": 850, "Liverpool": 900, "Chelsea": 750,
    "Man United": 600, "Tottenham": 500, "Newcastle": 450, "Aston Villa": 400,
    "West Ham": 300, "Brighton": 280, "Wolves": 250, "Crystal Palace": 240,
    "Nott'm Forest": 220, "Bournemouth": 200, "Fulham": 200, "Brentford": 190,
    "Everton": 180, "Ipswich": 120, "Leicester": 160, "Southampton": 140,

    # La Liga
    "Real Madrid": 1100, "Barcelona": 1000, "Atletico Madrid": 700,
    "Athletic Club": 350, "Villarreal": 300, "Real Sociedad": 320,
    "Betis": 250, "Sevilla": 220, "Girona": 200, "Celta Vigo": 150,
    "Mallorca": 120, "Osasuna": 110, "Rayo Vallecano": 100, "Alaves": 90,
    "Getafe": 85, "Las Palmas": 80, "Espanyol": 75, "Leganes": 60, "Valladolid": 55,

    # Bundesliga
    "Bayern": 900, "Leverkusen": 600, "Dortmund": 550, "Leipzig": 450,
    "Frankfurt": 300, "Stuttgart": 280, "Wolfsburg": 200, "Freiburg": 180,
    "Monchengladbach": 160, "Hoffenheim": 150, "Union Berlin": 130, "Mainz": 120,
    "Augsburg": 110, "Werder Bremen": 110, "Heidenheim": 80, "St. Pauli": 60,
    "Bochum": 55, "Holstein Kiel": 45,

    # Ligue 1
    "PSG": 1000, "Monaco": 350, "Marseille": 300, "Lyon": 250, "Lille": 250,
    "Rennes": 200, "Nice": 180, "Lens": 150, "Strasbourg": 110, "Reims": 100,
    "Brest": 100, "Toulouse": 80, "Montpellier": 70, "Nantes": 70, "Auxerre": 60,
    "Saint-Etienne": 60, "Angers": 45, "Le Havre": 45
}

DEFAULT_MARKET_VALUE = 50


def get_market_values() -> dict:
    """Restituisce il dizionario completo dei valori di mercato."""
    return MARKET_VALUES.copy()


# ==========================================
# 6. NORMALIZZAZIONE NOMI SQUADRE
# ==========================================
TEAM_NAME_MAP = {
    # Serie A
    "Inter Milan": "Inter",
    "FC Internazionale Milano": "Inter",
    "AC Milan": "Milan",
    "AS Roma": "Roma",
    "Juventus FC": "Juventus",
    "SS Lazio": "Lazio",
    "Atalanta BC": "Atalanta",
    "SSC Napoli": "Napoli",
    "ACF Fiorentina": "Fiorentina",
    "Hellas Verona": "Verona",
    "Cagliari Calcio": "Cagliari",
    "Genoa CFC": "Genoa",
    "Udinese Calcio": "Udinese",
    "Parma Calcio 1913": "Parma",

    # Premier League
    "Manchester United": "Man United",
    "Manchester City": "Man City",
    "Tottenham Hotspur": "Tottenham",
    "Newcastle United": "Newcastle",
    "West Ham United": "West Ham",
    "Brighton and Hove Albion": "Brighton",
    "Wolverhampton Wanderers": "Wolves",
    "Nottingham Forest": "Nott'm Forest",
    "AFC Bournemouth": "Bournemouth",
    "Ipswich Town": "Ipswich",
    "Leicester City": "Leicester",

    # La Liga
    "Athletic Bilbao": "Athletic Club",
    "Deportivo Alaves": "Alaves",
    "Real Betis": "Betis",

    # Bundesliga
    "Bayern Munich": "Bayern",
    "Bayer 04 Leverkusen": "Leverkusen",
    "Borussia Dortmund": "Dortmund",
    "RB Leipzig": "Leipzig",
    "VfB Stuttgart": "Stuttgart",
    "Eintracht Frankfurt": "Frankfurt",
    "SC Freiburg": "Freiburg",
    "TSG Hoffenheim": "Hoffenheim",
    "VfL Wolfsburg": "Wolfsburg",
    "1. FSV Mainz 05": "Mainz",
    "SV Werder Bremen": "Werder Bremen",
    "FC Augsburg": "Augsburg",
    "1. FC Heidenheim 1846": "Heidenheim",
    "VfL Bochum": "Bochum",
    "FC St. Pauli": "St. Pauli",
    "Borussia Mönchengladbach": "Monchengladbach",

    # Ligue 1
    "Paris Saint-Germain": "PSG",
    "Paris SG": "PSG",
    "Olympique de Marseille": "Marseille",
    "Olympique Lyonnais": "Lyon",
    "Stade Rennais FC": "Rennes",
    "OGC Nice": "Nice",
    "RC Lens": "Lens",
    "RC Strasbourg Alsace": "Strasbourg",
    "Stade de Reims": "Reims",
    "Stade Brestois 29": "Brest",
    "Toulouse FC": "Toulouse",
    "Montpellier HSC": "Montpellier",
    "FC Nantes": "Nantes",
    "AJ Auxerre": "Auxerre",
    "AS Saint-Étienne": "Saint-Etienne",
    "Angers SCO": "Angers",
    "Le Havre AC": "Le Havre",
}

# Prefissi/suffissi comuni da rimuovere durante la pulizia del nome
NAME_CLEAN_REPLACEMENTS = [
    "FC", "BC", "AC ", "AS ", "SSC ", "SS ", "AFC ", "SV ",
    "1907", "Calcio", " CFC", "VfL ", "VfB ", "1. ", "OGC ", "RC ", "HSC"
]


def clean_name(name: str) -> str:
    """
    Pulisce e standardizza il nome di una squadra per garantire coerenza
    tra API esterne (Football-Data, Understat) e i database CSV locali.
    """
    if not name:
        return ""
    n = str(name).strip()
    n = TEAM_NAME_MAP.get(n, n)
    for r in NAME_CLEAN_REPLACEMENTS:
        n = n.replace(r, "")
    return n.strip()
