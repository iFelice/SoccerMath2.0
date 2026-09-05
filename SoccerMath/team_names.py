"""
team_names.py - Unica fonte di normalizzazione dei nomi squadra.

Perche' esiste questo modulo
----------------------------
Prima di questo intervento la stessa traduzione "nome Understat -> nome usato
dall'app" era duplicata (e divergente) in almeno tre punti:

  * ``SoccerMath/update_xg.py``           -> ``NAME_MAP`` (scraper Understat)
  * ``SoccerMath/config.py``              -> ``TEAM_NAME_MAP`` + ``clean_name``
  * ``audit/xg_rolling_walkforward.py``   -> ``NAME_TRANSLATE``

Il nome CANONICO e' quello con cui i consumatori reali indicizzano le squadre,
cioe' ``clean_name(<nome del CSV football-data>)``:

  * ``app.get_league_engine`` costruisce ``stats`` con chiave
    ``clean_name(df['HomeTeam'])`` e cerca gli xG con ``xg_data.get(t)``;
  * ``models/elo_engine.py`` fa lo stesso su ``HomeClean``/``AwayClean``;
  * ``config.MARKET_VALUES`` e' indicizzato sugli stessi nomi.

Quindi la regola e': *canonico = clean_name(nome CSV)*, e ogni titolo Understat
deve essere tradotto esplicitamente in quel nome. Nessun fuzzy matching:
``UNDERSTAT_NAME_MAP`` contiene una voce esplicita per ogni titolo presente
negli archivi per-partita delle cinque leghe (stagioni 2022-2026), verificata
contro i CSV storici stagione per stagione da ``audit/xg_pipeline_audit.py``.

I nomi non presenti nella tabella NON vengono indovinati: passano per
``clean_name`` e vengono segnalati come "non mappati" da ``resolve_team_name``,
cosi' l'audit puo' distinguere un alias mancante da una squadra semplicemente
assente in quella stagione.
"""

from __future__ import annotations

from typing import Dict, NamedTuple

from config import clean_name

# ---------------------------------------------------------------------------
# Titoli Understat osservati negli archivi per-partita (5 leghe, 2022-2026).
# Valore = clean_name(nome CSV football-data) della stessa squadra.
# Generato dai dati e verificato stagione per stagione (nessun fuzzy matching).
# ---------------------------------------------------------------------------
UNDERSTAT_NAME_MAP: Dict[str, str] = {
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

# ---------------------------------------------------------------------------
# Varianti storiche / di altre fonti (Football-Data API, vecchi scrape, titoli
# accentati). Non compaiono negli archivi attuali ma restano accettate: se un
# giorno Understat cambia titolo, il lookup non si rompe in silenzio.
# ---------------------------------------------------------------------------
LEGACY_ALIASES: Dict[str, str] = {
    # Serie A
    "Inter Milan": "Inter",
    "AS Roma": "Roma",
    "SS Lazio": "Lazio",
    "SSC Napoli": "Napoli",
    "ACF Fiorentina": "Fiorentina",
    "Hellas Verona": "Verona",
    # Premier League
    "Brighton and Hove Albion": "Brighton",
    "Tottenham Hotspur": "Tottenham",
    "West Ham United": "West Ham",
    "AFC Bournemouth": "Bournemouth",
    "Ipswich Town": "Ipswich",
    "Leicester City": "Leicester",
    "Leeds United": "Leeds",
    "Coventry City": "Coventry City",
    "Hull City": "Hull City",
    # La Liga
    "Athletic Bilbao": "Ath Bilbao",
    "Deportivo Alaves": "Alaves",
    "Deportivo La Coruña": "Deportivo",
    "Espanol": "Espanol",
    "Málaga": "Málaga",
    "Valladolid": "Valladolid",
    "Oviedo": "Oviedo",
    # Bundesliga
    "Bayer 04 Leverkusen": "Leverkusen",
    "Leverkusen": "Leverkusen",
    "RB Leipzig": "Leipzig",
    "Borussia Mönchengladbach": "M'gladbach",
    "M'gladbach": "M'gladbach",
    "1. FSV Mainz 05": "Mainz",
    "1. FC Heidenheim 1846": "Heidenheim",
    "SV Werder Bremen": "Werder Bremen",
    "FC Augsburg": "Augsburg",
    "SC Freiburg": "Freiburg",
    "TSG Hoffenheim": "Hoffenheim",
    "VfL Wolfsburg": "Wolfsburg",
    "VfL Bochum": "Bochum",
    "FC St. Pauli": "St Pauli",
    "St Pauli": "St Pauli",
    "Köln": "Koln",
    "FC Koln": "Koln",
    "Hamburger": "Hamburg",
    "HSV": "Hamburg",
    "SC Paderborn": "SC Paderborn",
    "Schalke": "Schalke 04",
    # Ligue 1
    "Paris Saint-Germain": "PSG",
    "Paris SG": "PSG",
    "AS Monaco": "Monaco",
    "Olympique de Marseille": "Marseille",
    "Olympique Lyonnais": "Lyon",
    "Olympique Lyon": "Lyon",
    "Lille OSC": "Lille",
    "Stade Rennais FC": "Rennes",
    "Stade Rennais": "Rennes",
    "OGC Nice": "Nice",
    "RC Lens": "Lens",
    "RC Strasbourg Alsace": "Strasbourg",
    "Stade de Reims": "Reims",
    "Stade Brestois 29": "Brest",
    "Toulouse FC": "Toulouse",
    "Montpellier HSC": "Montpellier",
    "FC Nantes": "Nantes",
    "AJ Auxerre": "Auxerre",
    "AS Saint-Étienne": "St Etienne",
    "Saint-Étienne": "St Etienne",
    "Angers SCO": "Angers",
    "Le Havre AC": "Le Havre",
    "Clermont": "Clermont",
}

# Tabella completa usata dal resolver. Le voci verificate sugli archivi hanno
# la precedenza sugli alias storici.
NAME_MAP: Dict[str, str] = {**LEGACY_ALIASES, **UNDERSTAT_NAME_MAP}


class NameResolution(NamedTuple):
    """Esito della normalizzazione di un nome squadra."""

    raw: str
    canonical: str
    mapped: bool  # True se il nome grezzo era nella tabella esplicita


def resolve_team_name(name) -> NameResolution:
    """Normalizza ``name`` verso il nome canonico usato dall'app.

    ``mapped`` dice se il nome grezzo era presente nella tabella esplicita:
    in caso contrario si applica soltanto ``clean_name`` (nessuna euristica,
    nessun fuzzy matching) e il chiamante puo' segnalarlo come alias mancante.
    """
    raw = "" if name is None else str(name).strip()
    if not raw:
        return NameResolution(raw="", canonical="", mapped=False)
    mapped_name = NAME_MAP.get(raw)
    if mapped_name is None:
        return NameResolution(raw=raw, canonical=clean_name(raw), mapped=False)
    # clean_name resta idempotente sui valori canonici (test_xg_pipeline)
    return NameResolution(raw=raw, canonical=clean_name(mapped_name), mapped=True)


def canonical_team_name(name) -> str:
    """Nome canonico (chiave usata da get_league_engine / elo_engine)."""
    return resolve_team_name(name).canonical


def canonical_names() -> set:
    """Insieme dei nomi canonici conosciuti."""
    return {clean_name(v) for v in NAME_MAP.values()}


def aliases_for(canonical: str) -> list:
    """Tutti i nomi grezzi che si risolvono in ``canonical`` (ordinati)."""
    target = clean_name(canonical)
    return sorted(k for k, v in NAME_MAP.items() if clean_name(v) == target)
