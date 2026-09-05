"""
team_aliases.py - Dati grezzi della normalizzazione dei nomi squadra.

UNICO posto in cui si scrivono gli alias. Il modulo non importa nulla del
progetto (niente `config`, niente `team_names`): e' la foglia della catena e
non puo' creare import circolari.

Tre livelli, con un solo significato di "nome canonico":

    canonico = clean_name(nome dei CSV football-data)

cioe' la chiave con cui `app.get_league_engine`, `models/elo_engine.py` e
`config.MARKET_VALUES` indicizzano le squadre.

  * ``TEAM_NAME_MAP``      alias delle API live / varianti dei CSV
                           (usata da ``clean_name``, ri-esportata da config);
  * ``UNDERSTAT_NAME_MAP`` titoli Understat presenti negli archivi per-partita
                           (verificati stagione per stagione dai dati reali);
  * ``ALL_ALIASES``        unione delle due + i nomi canonici che mappano su
                           se' stessi, usata da ``team_names.resolve_team_name``.

Invarianti verificate dai test (`SoccerMath/test_xg_pipeline.py`):
  * le due tabelle non si contraddicono mai sulla stessa chiave;
  * ogni valore e' gia' canonico: ``clean_name(valore) == valore``;
  * nessun fuzzy matching: i nomi fuori tabella non vengono indovinati.

Interfacce storiche conservate: ``config.TEAM_NAME_MAP``,
``config.NAME_CLEAN_REPLACEMENTS`` e ``config.clean_name`` restano importabili
da `config` (ri-esportazione), ``update_xg.NAME_MAP`` da `update_xg`.
"""

from __future__ import annotations

from typing import Dict, List


# ==========================================
# 1. Alias delle API live e varianti dei CSV
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
    "Brighton Hove": "Brighton",
    "Leeds United": "Leeds",
    "Nottingham": "Nott'm Forest",

    # La Liga
    "Athletic Bilbao": "Ath Bilbao",
    "Deportivo Alaves": "Alaves",
    "Real Betis": "Betis",
    "Alavés": "Alaves",
    "Athletic": "Ath Bilbao",
    "Atleti": "Ath Madrid",
    "Barça": "Barcelona",
    "Espanyol": "Espanol",
    "Rayo Vallecano": "Vallecano",
    "Real Sociedad": "Sociedad",

    # Bundesliga
    "Bayern Munich": "Bayern",
    "Bayer 04 Leverkusen": "Leverkusen",
    "Borussia Dortmund": "Dortmund",
    "RB Leipzig": "Leipzig",
    "VfB Stuttgart": "Stuttgart",
    # I CSV football-data (e quindi le chiavi di get_league_engine/elo_engine)
    # usano "Ein Frankfurt": mappare su "Frankfurt" faceva fallire il lookup
    # perche' clean_name e' a passata singola e non riapplicava "Frankfurt" ->
    # "Ein Frankfurt".
    "Eintracht Frankfurt": "Ein Frankfurt",
    "SC Freiburg": "Freiburg",
    "TSG Hoffenheim": "Hoffenheim",
    "VfL Wolfsburg": "Wolfsburg",
    "1. FSV Mainz 05": "Mainz",
    "SV Werder Bremen": "Werder Bremen",
    "FC Augsburg": "Augsburg",
    "1. FC Heidenheim 1846": "Heidenheim",
    "VfL Bochum": "Bochum",
    # il CSV Bundesliga scrive "St Pauli" (senza punto)
    "FC St. Pauli": "St Pauli",
    # idem: il nome canonico dei CSV e' "M'gladbach", non "Monchengladbach".
    "Borussia Mönchengladbach": "M'gladbach",
    "Bremen": "Werder Bremen",
    "Frankfurt": "Ein Frankfurt",
    "HSV": "Hamburg",
    "Köln": "Koln",
    "Schalke": "Schalke 04",

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
    # il CSV Ligue 1 scrive "St Etienne"
    "AS Saint-Étienne": "St Etienne",
    "Angers SCO": "Angers",
    "Le Havre AC": "Le Havre",
    "Olympique Lyon": "Lyon",
    "Stade Rennais": "Rennes",
}


# ==========================================
# 2. Prefissi/suffissi rimossi da clean_name
# ==========================================
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


# ==========================================
# 3. Titoli Understat (archivi per-partita)
# ==========================================
UNDERSTAT_NAME_MAP = {
    # --- Serie A -----------------------------------------------------------
    "AC Milan": "Milan",
    "Atalanta": "Atalanta",
    "Bologna": "Bologna",
    "Cagliari": "Cagliari",
    "Como": "Como",
    "Cremonese": "Cremonese",
    "Empoli": "Empoli",
    "Fiorentina": "Fiorentina",
    "Frosinone": "Frosinone",
    "Genoa": "Genoa",
    "Inter": "Inter",
    "Juventus": "Juventus",
    "Lazio": "Lazio",
    "Lecce": "Lecce",
    "Monza": "Monza",
    "Napoli": "Napoli",
    "Parma Calcio 1913": "Parma",
    "Pisa": "Pisa",
    "Roma": "Roma",
    "Salernitana": "Salernitana",
    "Sampdoria": "Sampdoria",
    "Sassuolo": "Sassuolo",
    "Spezia": "Spezia",
    "Torino": "Torino",
    "Udinese": "Udinese",
    "Venezia": "Venezia",
    "Verona": "Verona",

    # --- Premier League ----------------------------------------------------
    "Arsenal": "Arsenal",
    "Aston Villa": "Aston Villa",
    "Bournemouth": "Bournemouth",
    "Brentford": "Brentford",
    "Brighton": "Brighton",
    "Burnley": "Burnley",
    "Chelsea": "Chelsea",
    # neopromosse 2026/27: il CSV usa il nome lungo, Understat quello corto
    "Coventry": "Coventry City",
    "Crystal Palace": "Crystal Palace",
    "Everton": "Everton",
    "Fulham": "Fulham",
    "Hull": "Hull City",
    "Ipswich": "Ipswich",
    "Leeds": "Leeds",
    "Leicester": "Leicester",
    "Liverpool": "Liverpool",
    "Luton": "Luton",
    "Manchester City": "Man City",
    "Manchester United": "Man United",
    "Newcastle United": "Newcastle",
    "Nottingham Forest": "Nott'm Forest",
    "Sheffield United": "Sheffield United",
    "Southampton": "Southampton",
    "Sunderland": "Sunderland",
    "Tottenham": "Tottenham",
    "West Ham": "West Ham",
    "Wolverhampton Wanderers": "Wolves",

    # --- La Liga -----------------------------------------------------------
    "Alaves": "Alaves",
    "Almeria": "Almeria",
    # I CSV football-data usano le abbreviazioni "Ath Bilbao"/"Ath Madrid":
    # NON "Athletic Club"/"Atletico Madrid" (mapping storico sbagliato).
    "Athletic Club": "Ath Bilbao",
    "Atletico Madrid": "Ath Madrid",
    "Barcelona": "Barcelona",
    "Cadiz": "Cadiz",
    "Celta Vigo": "Celta",
    "Deportivo La Coruna": "Deportivo",
    "Elche": "Elche",
    "Espanyol": "Espanol",
    "Getafe": "Getafe",
    "Girona": "Girona",
    "Granada": "Granada",
    "Las Palmas": "Las Palmas",
    "Leganes": "Leganes",
    "Levante": "Levante",
    "Malaga": "Málaga",
    "Mallorca": "Mallorca",
    "Osasuna": "Osasuna",
    "Racing Santander": "Santander",
    "Rayo Vallecano": "Vallecano",
    "Real Betis": "Betis",
    "Real Madrid": "Real Madrid",
    "Real Oviedo": "Oviedo",
    "Real Sociedad": "Sociedad",
    "Real Valladolid": "Valladolid",
    "Sevilla": "Sevilla",
    "Valencia": "Valencia",
    "Villarreal": "Villarreal",

    # --- Bundesliga --------------------------------------------------------
    "Augsburg": "Augsburg",
    "Bayer Leverkusen": "Leverkusen",
    "Bayern Munich": "Bayern",
    "Bochum": "Bochum",
    "Borussia Dortmund": "Dortmund",
    "Borussia M.Gladbach": "M'gladbach",
    "Darmstadt": "Darmstadt",
    "Eintracht Frankfurt": "Ein Frankfurt",
    "Elversberg": "Elversberg",
    "FC Cologne": "Koln",
    "FC Heidenheim": "Heidenheim",
    "Freiburg": "Freiburg",
    "Hamburger SV": "Hamburg",
    "Hertha Berlin": "Hertha",
    "Hoffenheim": "Hoffenheim",
    "Holstein Kiel": "Holstein Kiel",
    "Mainz 05": "Mainz",
    "Paderborn": "SC Paderborn",
    "RasenBallsport Leipzig": "Leipzig",
    "Schalke 04": "Schalke 04",
    # il CSV scrive "St Pauli" (senza punto): il vecchio mapping produceva
    # "St. Pauli" e falliva il lookup.
    "St. Pauli": "St Pauli",
    "Union Berlin": "Union Berlin",
    "VfB Stuttgart": "Stuttgart",
    "Werder Bremen": "Werder Bremen",
    "Wolfsburg": "Wolfsburg",

    # --- Ligue 1 -----------------------------------------------------------
    "Ajaccio": "Ajaccio",
    "Angers": "Angers",
    "Auxerre": "Auxerre",
    "Brest": "Brest",
    "Clermont Foot": "Clermont",
    "Le Havre": "Le Havre",
    "Le Mans": "Le Mans",
    "Lens": "Lens",
    "Lille": "Lille",
    "Lorient": "Lorient",
    "Lyon": "Lyon",
    "Marseille": "Marseille",
    "Metz": "Metz",
    "Monaco": "Monaco",
    "Montpellier": "Montpellier",
    "Nantes": "Nantes",
    "Nice": "Nice",
    # due club parigini distinti: Paris FC != Paris Saint Germain
    "Paris FC": "Paris",
    "Paris Saint Germain": "PSG",
    "Reims": "Reims",
    "Rennes": "Rennes",
    # il CSV 2024/25 scrive "St Etienne": il vecchio mapping produceva
    # "Saint-Etienne" e falliva il lookup.
    "Saint-Etienne": "St Etienne",
    "Strasbourg": "Strasbourg",
    "Toulouse": "Toulouse",
    "Troyes": "Troyes",
}



# Varianti storiche/accentate viste da altre fonti (vecchi scrape, API):
# non compaiono negli archivi attuali ma restano accettate, cosi' un cambio di
# titolo a monte non fa fallire il lookup in silenzio.
UNDERSTAT_NAME_MAP.update({
    "AS Monaco": "Monaco",
    "Deportivo La Coruña": "Deportivo",
    "FC Koln": "Koln",
    "Hamburger": "Hamburg",
    "Lille OSC": "Lille",
    "Saint-Étienne": "St Etienne",
})

# ==========================================
# 4. Tabella unica usata dal resolver
# ==========================================
def _merged_aliases() -> Dict[str, str]:
    """Unione delle tabelle + i nomi canonici che mappano su se' stessi.

    I nomi gia' canonici devono essere accettati ESPLICITAMENTE: senza questa
    riga ``resolve_team_name("Dortmund")`` risulterebbe "non mappato" e la
    validazione bloccante darebbe un falso allarme.
    """
    merged: Dict[str, str] = {}
    for table in (TEAM_NAME_MAP, UNDERSTAT_NAME_MAP):
        for raw, canonical in table.items():
            merged[raw] = canonical
    for canonical in list(merged.values()):
        merged.setdefault(clean_name(canonical), canonical)
    return merged


ALL_ALIASES: Dict[str, str] = _merged_aliases()

# Insieme dei nomi canonici dichiarati.
CANONICAL_NAMES = frozenset(clean_name(v) for v in ALL_ALIASES.values())


def conflicting_aliases() -> Dict[str, List[str]]:
    """Chiavi presenti in entrambe le tabelle con valori diversi (deve essere vuoto)."""
    conflicts: Dict[str, List[str]] = {}
    for raw, canonical in TEAM_NAME_MAP.items():
        other = UNDERSTAT_NAME_MAP.get(raw)
        if other is not None and other != canonical:
            conflicts[raw] = [canonical, other]
    return conflicts
