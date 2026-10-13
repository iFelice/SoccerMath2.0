"""Parser puro dei comunicati del Giudice Sportivo Serie A.

Non effettua richieste. Le squalifiche sono lette esclusivamente dalla sezione
ufficiale delle squalifiche; gli ammoniti servono solo al calcolo dei diffidati,
mai a ricostruire assenze/squalifiche.
"""
from __future__ import annotations

import re
from typing import Any

from .core import normalize_text, strip_markup_line

ITALIAN_NUMBERS = {
    "una": 1,
    "un": 1,
    "uno": 1,
    "due": 2,
    "tre": 3,
    "quattro": 4,
    "cinque": 5,
    "sei": 6,
    "sette": 7,
    "otto": 8,
    "nove": 9,
    "dieci": 10,
    "undici": 11,
    "dodici": 12,
}
PROGRESSIVE = {
    "prima": 1,
    "seconda": 2,
    "terza": 3,
    "quarta": 4,
    "quinta": 5,
    "sesta": 6,
    "settima": 7,
    "ottava": 8,
    "nona": 9,
    "decima": 10,
    "undicesima": 11,
    "dodicesima": 12,
    "tredicesima": 13,
    "quattordicesima": 14,
    "quindicesima": 15,
    "sedicesima": 16,
    "diciassettesima": 17,
    "diciottesima": 18,
    "diciannovesima": 19,
    "ventesima": 20,
}

# Le soglie del Giudice Sportivo (art. 19, c. 9, CGS) sono 5, 9, 13, 16,
# 18 e ogni ammonizione dalla 19ª in poi.
SUSPENSION_THRESHOLDS = (5, 9, 13, 16, 18)


def triggers_suspension_on_next_yellow(current_yellows: int) -> bool:
    """True se la prossima ammonizione raggiunge una soglia Serie A."""
    if current_yellows < 0:
        return False
    next_yellows = current_yellows + 1
    return next_yellows in SUSPENSION_THRESHOLDS or next_yellows >= 19


def diffidati_from_progressives(cautions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Calcola i diffidati osservabili dai progressivi presenti nel documento.

    Il risultato è deliberatamente limitato ai nomi con progressivo nel
    comunicato passato al parser. Per una lista completa occorre l'archivio
    ufficiale da inizio stagione, e il chiamante deve dichiarare la copertura.
    """
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in cautions:
        count = row.get("progressive_count")
        if not isinstance(count, int):
            continue
        key = (str(row.get("player_name", "")).casefold(), str(row.get("team_source", "")).casefold())
        if not key[0]:
            continue
        if key not in latest or count > int(latest[key].get("progressive_count", 0)):
            latest[key] = row
    result = []
    for row in latest.values():
        count = int(row["progressive_count"])
        if triggers_suspension_on_next_yellow(count):
            item = dict(row)
            item["basis"] = "progressivo ufficiale nel comunicato letto"
            result.append(item)
    return sorted(result, key=lambda row: (str(row.get("team_source", "")).casefold(), str(row.get("player_name", "")).casefold()))


def _plain_lines(text: str) -> list[str]:
    return [strip_markup_line(line) for line in normalize_text(text).splitlines()]


def _find_marker(lines: list[str], marker: str, *, start: int = 0) -> int | None:
    wanted = marker.casefold()
    for index in range(start, len(lines)):
        if lines[index].casefold().startswith(wanted):
            return index
    return None


def _find_player_and_coach_sections(lines: list[str]) -> tuple[list[str] | None, list[str] | None]:
    player_start = None
    coach_start = None
    for index, line in enumerate(lines):
        lower = line.casefold()
        if player_start is None and re.match(r"^b\s*\)?\s+calciatori\b", lower):
            player_start = index + 1
        elif player_start is None and re.fullmatch(r"b\s*\)?", lower) and index + 1 < len(lines):
            if "calciatori" in lines[index + 1].casefold():
                player_start = index + 2
        if coach_start is None and re.match(r"^c\s*\)?\s+allenatori\b", lower):
            coach_start = index
        elif coach_start is None and re.fullmatch(r"c\s*\)?", lower) and index + 1 < len(lines):
            if "allenatori" in lines[index + 1].casefold():
                coach_start = index
    if player_start is None or coach_start is None or coach_start <= player_start:
        return None, None
    player_lines = lines[player_start:coach_start]
    coach_lines = lines[coach_start + 1 :]
    for index, line in enumerate(coach_lines):
        if line.casefold().startswith("ammoniti"):
            coach_lines = coach_lines[:index]
            break
    return player_lines, coach_lines


def _count_from_word(word: str) -> int | None:
    cleaned = word.strip().casefold().rstrip("ª°a")
    if cleaned.isdigit():
        return int(cleaned)
    return ITALIAN_NUMBERS.get(cleaned)


def _suspension_heading(line: str) -> int | None:
    match = re.search(
        r"\bsqualifica\s+per\s+(una|un|uno|due|tre|quattro|cinque|sei|sette|otto|nove|dieci|undici|dodici|\d+)\s+giornat[ae]\b",
        line,
        flags=re.IGNORECASE,
    )
    return _count_from_word(match.group(1)) if match else None


def _progressive_from_line(line: str) -> int | None:
    match = re.search(
        r"\b(prima|seconda|terza|quarta|quinta|sesta|settima|ottava|nona|decima|undicesima|dodicesima|tredicesima|quattordicesima|quindicesima|sedicesima|diciassettesima|diciottesima|diciannovesima|ventesima|\d+(?:a|ª)?)\s+sanzione\b",
        line,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    word = match.group(1).casefold()
    numeric = re.fullmatch(r"(\d+)(?:a|ª)?", word)
    if numeric:
        return int(numeric.group(1))
    return PROGRESSIVE.get(word)


def _person_line(line: str) -> dict[str, str] | None:
    """Riconosce una riga ``NOME (squadra): motivazione`` del comunicato."""
    cleaned = strip_markup_line(line)
    if not cleaned or re.match(r"^(?:[a-c]\)|squalifica\b|ammonizione\b|per\b|calciatori\b|allenatori\b|espulsi\b|ammoniti\b)", cleaned, re.I):
        return None
    match = re.match(r"^(?P<name>.+?)\s*\((?P<team>[^()]+)\)\s*:?[ \t]*(?P<reason>.*)$", cleaned)
    if not match:
        return None
    name = match.group("name").strip(" .:*#")
    team = match.group("team").strip()
    if not name or not team:
        return None
    return {"player_name": name, "team_source": team, "reason_text": match.group("reason").strip(" :")}


def _parse_suspensions(lines: list[str], *, entity: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    active_games: int | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        heading_games = _suspension_heading(line)
        if heading_games is not None:
            active_games = heading_games
            index += 1
            continue
        if "squalifica" in line.casefold() and "giornat" not in line.casefold():
            active_games = None
        if line.upper().startswith(("PER ", "AMMONIZIONE", "AMMONITI", "ESPULSI")):
            active_games = None
        if active_games is not None:
            person = _person_line(line)
            if person:
                continuation: list[str] = [person.pop("reason_text", "")]
                next_index = index + 1
                while next_index < len(lines):
                    candidate = lines[next_index]
                    if not candidate:
                        break
                    if _suspension_heading(candidate) is not None or _person_line(candidate) is not None:
                        break
                    if re.match(r"^(?:[a-c]\)|per\b|ammonizione\b|squalifica\b|calciatori\b|allenatori\b)", candidate, re.I):
                        break
                    continuation.append(candidate)
                    next_index += 1
                reason = " ".join(part for part in continuation if part).strip()
                rows.append({
                    **person,
                    "entity": entity,
                    "games": active_games,
                    "reason": reason or "motivo non riportato nella riga estratta",
                    "source_section": "squalifiche ufficiali",
                })
                index = next_index
                continue
        index += 1
    return rows


def _parse_cautions(lines: list[str]) -> list[dict[str, Any]]:
    cautions: list[dict[str, Any]] = []
    in_caution_block = False
    current_progressive: int | None = None
    for line in lines:
        upper = line.upper()
        if "SQUALIFICA" in upper:
            in_caution_block = False
            current_progressive = None
            continue
        if upper.startswith("PER "):
            in_caution_block = False
            current_progressive = None
            continue
        if "AMMONIZIONE" in upper:
            in_caution_block = True
            current_progressive = _progressive_from_line(line) or current_progressive
            # L'intestazione può essere solo ``AMMONIZIONE``; la progressione
            # verrà impostata dalla riga successiva.
            continue
        progressive = _progressive_from_line(line)
        if progressive is not None:
            current_progressive = progressive
            in_caution_block = True
            continue
        if not in_caution_block or current_progressive is None:
            continue
        person = _person_line(line)
        if not person:
            continue
        cautions.append({
            "player_name": person["player_name"],
            "team_source": person["team_source"],
            "progressive_count": current_progressive,
            "reason": "ammonizione: progressivo ufficiale del comunicato",
        })
    # Evita duplicati letterali senza sommare due volte lo stesso progressivo.
    unique: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in cautions:
        key = (row["player_name"].casefold(), row["team_source"].casefold(), row["progressive_count"])
        unique[key] = row
    return list(unique.values())


def _extract_matchday(text: str) -> int | None:
    normalized = normalize_text(text)
    words = {
        "prima": 1, "seconda": 2, "terza": 3, "quarta": 4, "quinta": 5,
        "sesta": 6, "settima": 7, "ottava": 8, "nona": 9, "decima": 10,
        "undicesima": 11, "dodicesima": 12, "tredicesima": 13, "quattordicesima": 14,
        "quindicesima": 15, "sedicesima": 16, "diciassettesima": 17,
        "diciottesima": 18, "diciannovesima": 19, "ventesima": 20,
    }
    match = re.search(r"\b(\d{1,2})\s*(?:ª|a)?\s+giornata\b", normalized, re.I)
    if match:
        return int(match.group(1))
    match = re.search(
        r"\b(prima|seconda|terza|quarta|quinta|sesta|settima|ottava|nona|decima|undicesima|dodicesima|tredicesima|quattordicesima|quindicesima|sedicesima|diciassettesima|diciottesima|diciannovesima|ventesima)\s+giornata\b",
        normalized,
        re.I,
    )
    return words.get(match.group(1).casefold()) if match else None


def parse_serie_a_text(text: str) -> dict[str, Any]:
    """Interpreta il testo estratto dal PDF del Giudice Sportivo, senza I/O."""
    normalized = normalize_text(text)
    lines = _plain_lines(normalized)
    upper = "\n".join(lines).upper()
    if "COMUNICATO UFFICIALE" not in upper or "DECISIONI DEL GIUDICE SPORTIVO" not in upper:
        return {"recognized": False, "reason": "intestazione del comunicato Giudice Sportivo assente", "rows_extracted": 0}
    player_lines, coach_lines = _find_player_and_coach_sections(lines)
    if player_lines is None or coach_lines is None:
        return {"recognized": False, "reason": "sezioni CALCIATORI/ALLENATORI non riconosciute", "rows_extracted": 0}

    suspended_players = _parse_suspensions(player_lines, entity="player")
    suspended_coaches = _parse_suspensions(coach_lines, entity="coach")
    cautions = _parse_cautions(player_lines)
    rows_extracted = len(suspended_players) + len(suspended_coaches) + len(cautions)
    if rows_extracted == 0:
        return {
            "recognized": True,
            "reason": "nessuna riga disciplinare estratta: documento non dichiarato come assenza zero",
            "matchday": _extract_matchday(normalized),
            "suspended_players": [],
            "suspended_coaches": [],
            "cautions": [],
            "rows_extracted": 0,
        }
    return {
        "recognized": True,
        "reason": None,
        "matchday": _extract_matchday(normalized),
        "suspended_players": suspended_players,
        "suspended_coaches": suspended_coaches,
        "cautions": cautions,
        "diffidati_observed": diffidati_from_progressives(cautions),
        "rows_extracted": rows_extracted,
    }
