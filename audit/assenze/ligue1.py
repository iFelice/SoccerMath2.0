"""Parser puro delle decisioni disciplinari ufficiali LFP/Ligue 1."""
from __future__ import annotations

import re
from typing import Any

from .core import normalize_text, strip_markup_line

FRENCH_NUMBERS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4,
    "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9,
    "dix": 10, "onze": 11, "douze": 12,
}
MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
    "decembre": 12,
}

HEADING_RE = re.compile(
    r"\b(?P<count>un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|\d+)\s+"
    r"matchs?\s+(?P<tail>[^\n.]*?suspension[^\n.]*)",
    re.IGNORECASE,
)
PLAYER_RE = re.compile(
    r"(?P<name>(?:[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿĀ-ž'’.-]+|[A-ZÀ-ÖØ-Þ]{2,})"
    r"(?:\s+(?:[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿĀ-ž'’.-]+|[A-ZÀ-ÖØ-Þ]{2,})){1,5})"
    r"\s*\((?P<team>[^()]+)\)",
)
MATCHDAY_RE = re.compile(r"(?im)^\s*\d{1,2}(?:er|e)\s+journée\s+de\s+Ligue\s+1\b[^\n]*")
DATE_RE = re.compile(
    r"\b(?P<day>\d{1,2})\s+(?P<month>janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)\s+(?P<year>20\d{2})\b",
    re.IGNORECASE,
)


def _plain_text(text: str) -> str:
    return "\n".join(strip_markup_line(line) for line in normalize_text(text).splitlines())


def _number(word: str) -> int | None:
    token = word.casefold().strip()
    if token.isdigit():
        return int(token)
    return FRENCH_NUMBERS.get(token)


def _segments(text: str) -> list[str]:
    markers = list(MATCHDAY_RE.finditer(text))
    if not markers:
        return [text]
    segments: list[str] = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        segments.append(text[marker.start() : end])
    return segments


def _date_for_heading(segment: str, heading: re.Match[str]) -> str | None:
    effective = re.compile(
        r"(?:la\s+)?(?:suspension|sanction)\s+prend\s+effet\s+à\s+partir\s+du\s+(?:mardi\s+)?"
        r"(?P<day>\d{1,2})\s+(?P<month>janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)\s+(?P<year>20\d{2})",
        re.IGNORECASE,
    )
    dates = list(effective.finditer(segment))
    if not dates:
        return None
    closest = min(dates, key=lambda match: abs(match.start() - heading.start()))
    month = MONTHS[closest.group("month").casefold()]
    year = int(closest.group("year"))
    day = int(closest.group("day"))
    return f"{year:04d}-{month:02d}-{day:02d}"


def _reason(tail: str) -> tuple[str, str]:
    folded = tail.casefold()
    if "cinquième avertissement" in folded or "cinquieme avertissement" in folded:
        return "sospensione automatica dopo il quinto avvertimento", "yellow_accumulation_5"
    if "troisième avertissement" in folded or "troisieme avertissement" in folded:
        return "sospensione automatica dopo il terzo avvertimento (regime indicato dalla fonte)", "yellow_accumulation_3"
    return "decisione disciplinare LFP; motivo specifico non dettagliato nella scheda", "disciplinary_decision"


def parse_ligue1_text(text: str) -> dict[str, Any]:
    """Estrae giocatori, giornate ferme/sospese e motivo delle decisioni LFP."""
    plain = _plain_text(text)
    folded = plain.casefold()
    if "discipline" not in folded or ("commission de discipline" not in folded and "décisions" not in folded and "decisions" not in folded):
        return {"recognized": False, "reason": "intestazione dell'articolo disciplinare LFP assente", "rows_extracted": 0}
    headings_total = list(HEADING_RE.finditer(plain))
    if not headings_total:
        return {"recognized": False, "reason": "nessuna intestazione di sospensione LFP riconosciuta", "rows_extracted": 0}

    records: list[dict[str, Any]] = []
    for segment in _segments(plain):
        headings = list(HEADING_RE.finditer(segment))
        if not headings:
            continue
        players = list(PLAYER_RE.finditer(segment))
        for player in players:
            # LFP talvolta presenta prima il caso nominativo (es. «Comportement
            # de M. X») e subito dopo la sanzione; talvolta l'intestazione viene
            # prima del calciatore. Entrambi i formati sono associati solo
            # entro la stessa sezione di giornata e a distanza limitata.
            heading = min(headings, key=lambda item: abs(item.start() - player.start()))
            if abs(heading.start() - player.start()) > 650:
                continue
            count = _number(heading.group("count"))
            if count is None:
                continue
            tail = " ".join(heading.group("tail").split()).strip()
            reason, suspension_type = _reason(tail)
            suspended_match = re.search(
                r"\b(?:et|and)\s+(un|une|deux|trois|quatre|cinq|\d+)\s+matchs?\s+avec\s+sursis\b",
                tail,
                flags=re.IGNORECASE,
            )
            suspended_games = _number(suspended_match.group(1)) if suspended_match else 0
            team = " ".join(player.group("team").split()).strip(" .")
            player_name = " ".join(player.group("name").split()).strip()
            if player_name.startswith("M. "):
                player_name = player_name[3:]
            records.append({
                "player_name": player_name,
                "team_source": team,
                "games": count,
                "suspended_games": suspended_games,
                "reason": reason,
                "reason_source": tail,
                "suspension_type": suspension_type,
                "effective_from": _date_for_heading(segment, heading),
                "matchday_context": _matchday_context(segment),
            })

    unique: dict[tuple[str, str, int, int, str], dict[str, Any]] = {}
    for row in records:
        key = (
            row["player_name"].casefold(),
            row["team_source"].casefold(),
            row["games"],
            row["suspended_games"],
            row["suspension_type"],
        )
        unique[key] = row
    result = list(unique.values())
    recognized = bool(result)
    return {
        "recognized": recognized,
        "reason": None if recognized else "schema riconosciuto ma zero righe giocatore con sospensione",
        "suspended_players": result,
        "rows_extracted": len(result),
    }


def _matchday_context(segment: str) -> str | None:
    match = MATCHDAY_RE.search(segment)
    if not match:
        return None
    return " ".join(match.group(0).split())
