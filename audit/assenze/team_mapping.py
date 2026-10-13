"""Crosswalk delle fonti ufficiali verso i nomi canonici dei CSV *_Live.csv.

La risoluzione usa prima ``SoccerMath.team_aliases.clean_name`` e poi alias
espliciti per i nomi lunghi delle fonti. Nessun fuzzy matching. I display name
sono usati esclusivamente nel referto, non come chiave di abbinamento.
"""
from __future__ import annotations

import csv
from pathlib import Path
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
SOCCERMATH_DIR = ROOT / "SoccerMath"
if str(SOCCERMATH_DIR) not in sys.path:
    sys.path.insert(0, str(SOCCERMATH_DIR))

from team_aliases import clean_name  # noqa: E402
from display_names import display_name  # noqa: E402

LIVE_CSV = {
    "serie_a": ROOT / "SoccerMath" / "database" / "SerieA_Live.csv",
    "laliga": ROOT / "SoccerMath" / "database" / "LaLiga_Live.csv",
    "ligue1": ROOT / "SoccerMath" / "database" / "Ligue1_Live.csv",
}

# Alias della denominazione ufficiale nel documento -> chiave del relativo CSV.
# Gli alias sono locali all'audit: non modificano il comportamento dell'app.
_SOURCE_ALIASES: dict[str, dict[str, str]] = {
    "serie_a": {},
    "laliga": {
        "deportivo alavés": "Alaves",
        "club atlético de madrid": "Ath Madrid",
        "club atlético osasuna": "Osasuna",
        "elche cf": "Elche",
        "real racing club de santander": "Santander",
        "rc celta de vigo": "Celta",
        "sevilla fc": "Sevilla",
        "real madrid cf": "Real Madrid",
        "real betis balompié": "Betis",
        "valencia cf": "Valencia",
        "athletic club": "Ath Bilbao",
        "rayo vallecano de madrid": "Vallecano",
        "rcd espanyol de barcelona": "Espanol",
        "rc deportivo": "Deportivo",
        "getafe cf": "Getafe",
        "málaga cf": "Málaga",
        "real sociedad de fútbol": "Sociedad",
        "levante ud": "Levante",
        "villarreal cf": "Villarreal",
        "fc barcelona": "Barcelona",
        # Varianti incontrate nei comunicati/archivi RFEF.
        "deportivo alaves": "Alaves",
        "club atletico de madrid": "Ath Madrid",
        "club atletico osasuna": "Osasuna",
        "real sociedad": "Sociedad",
        "real betis": "Betis",
        "athletic bilbao": "Ath Bilbao",
        "rayo vallecano": "Vallecano",
        "espanyol": "Espanol",
        "atletico madrid": "Ath Madrid",
        "celta": "Celta",
        "alavés": "Alaves",
        "alaves": "Alaves",
    },
    "ligue1": {
        "as monaco": "Monaco",
        "le mans fc": "Le Mans",
        "estac troyes": "Troyes",
        "troyes": "Troyes",
        "angers sco": "Angers",
        "havre ac": "Le Havre",
        "le havre ac": "Le Havre",
        "losc": "Lille",
        "losc lille": "Lille",
        "lille osc": "Lille",
        "fc lorient": "Lorient",
        "fc metz": "Metz",
        "paris fc": "Paris",
        "paris saint-germain": "PSG",
        "paris sg": "PSG",
        "psg": "PSG",
        "olympique de marseille": "Marseille",
        "olympique lyonnais": "Lyon",
        "olympique lyon": "Lyon",
        "stade rennais fc": "Rennes",
        "stade rennais": "Rennes",
        "ogc nice": "Nice",
        "rc lens": "Lens",
        "rc strasbourg alsace": "Strasbourg",
        "stade de reims": "Reims",
        "stade brestois 29": "Brest",
        "toulouse fc": "Toulouse",
        "montpellier hsc": "Montpellier",
        "fc nantes": "Nantes",
        "aj auxerre": "Auxerre",
        "as saint-étienne": "St Etienne",
        "as saint-etienne": "St Etienne",
        "saint-étienne": "St Etienne",
        "saint-etienne": "St Etienne",
        "clermont foot": "Clermont",
    },
}


def load_live_teams(league: str, *, root: Path = ROOT) -> set[str]:
    """Carica nomi Home/Away distinti dal CSV Live; errore se manca lo schema."""
    relative = LIVE_CSV.get(league)
    if relative is None:
        raise ValueError(f"lega non prevista per il mapping: {league}")
    path = root / relative.relative_to(ROOT)
    if not path.is_file():
        raise FileNotFoundError(f"CSV squadre live mancante: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        home_key = next((key for key in ("HomeTeam", "Home", "Home Team") if key in fields), None)
        away_key = next((key for key in ("AwayTeam", "Away", "Away Team") if key in fields), None)
        if not home_key or not away_key:
            raise ValueError(f"schema CSV squadre non riconosciuto: {path}")
        teams = {
            str(row[key]).strip()
            for row in reader
            for key in (home_key, away_key)
            if row.get(key) and str(row[key]).strip()
        }
    if not teams:
        raise ValueError(f"nessuna squadra nel CSV live: {path}")
    return teams


def canonical_team(source: str, source_name: str, live_teams: Iterable[str]) -> str | None:
    """Risoluzione dichiarata e deterministica; restituisce None se non abbinata."""
    raw = " ".join(str(source_name or "").split())
    if not raw:
        return None
    live = set(live_teams)

    # Primo tentativo: resolver condiviso dell'app, come richiesto.
    candidate = clean_name(raw)
    if candidate in live:
        return candidate

    # Secondo tentativo: crosswalk ufficiale specifico della fonte. Anche il
    # risultato passa per clean_name, così il valore resta una chiave canonica.
    override = _SOURCE_ALIASES.get(source, {}).get(raw.casefold())
    if override:
        candidate = clean_name(override)
        if candidate in live:
            return candidate
    return None


def decorate_team(record: dict[str, Any], source: str, live_teams: Iterable[str]) -> dict[str, Any]:
    """Copia un record e aggiunge canonico/display/status senza modificare l'input."""
    result = dict(record)
    raw = str(result.get("team_source") or "").strip()
    canonical = canonical_team(source, raw, live_teams)
    result["team_canonical"] = canonical
    result["team_display"] = display_name(canonical) if canonical else None
    result["team_match"] = "matched" if canonical else "unmatched"
    return result


def decorate_records(
    records: Iterable[dict[str, Any]], source: str, live_teams: Iterable[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    decorated = [decorate_team(record, source, live_teams) for record in records]
    unmatched = sorted({
        str(row.get("team_source") or "(squadra vuota)")
        for row in decorated
        if row["team_match"] != "matched"
    }, key=str.casefold)
    return decorated, unmatched
