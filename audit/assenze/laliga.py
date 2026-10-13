"""Parser puro dei comunicati disciplinari RFEF (Primera División / La Liga)."""
from __future__ import annotations

import re
from typing import Any

from .core import normalize_text, strip_markup_line

# Denominazioni ufficiali incontrate nei comunicati Primera División; servono
# anche a ricostruire il caso RFEF J7 in cui pdftotext ha intercalato il testo
# della sanzione dentro le parentesi del nome squadra.
LALIGA_SOURCE_TEAM_NAMES = (
    "Club Atlético de Madrid", "Club Atlético Osasuna", "Real Racing Club de Santander",
    "Real Sociedad de Fútbol", "Real Betis Balompié", "Rayo Vallecano de Madrid",
    "RCD Espanyol de Barcelona", "Real Madrid CF", "RC Celta de Vigo", "Sevilla FC",
    "Valencia CF", "Athletic Club", "Deportivo Alavés", "Elche CF", "Getafe CF",
    "Levante UD", "Villarreal CF", "RC Deportivo", "Málaga CF", "FC Barcelona",
)

ARTICLE_RE = re.compile(r"\(?\s*Art[ií]culo\s*:\s*([0-9.]+)\s*\)?", re.IGNORECASE)
SUSPENSION_RE = re.compile(r"\b(?P<games>\d+)\s+partidos?\s+de\s+suspensi[oó]n\s+por\b", re.IGNORECASE)
NAME_RE = re.compile(
    r"(?m)^\s*(?P<name>[A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ, .\"'’\-]+?)\s*(?=\s*(?:\(|\d+\s+partidos?))"
)


def _plain_text(text: str) -> str:
    return "\n".join(strip_markup_line(line) for line in normalize_text(text).splitlines())


def _player_section(text: str) -> tuple[str | None, int | None, str | None]:
    upper = text.upper()
    start = upper.find("I JUGADORES")
    end = upper.find("II-ENTRENADORES", start + 1) if start >= 0 else -1
    if start < 0 or end < 0 or end <= start:
        return None, None, None
    jornada = re.search(r"\bJORNADA\s*:\s*(\d{1,2})\b", text, flags=re.IGNORECASE)
    return text[start + len("I JUGADORES") : end], int(jornada.group(1)) if jornada else None, None


def _clean_candidate_text(chunk: str) -> str:
    kept = []
    for raw_line in chunk.splitlines():
        line = strip_markup_line(raw_line)
        if not line:
            continue
        upper = line.upper()
        if (
            "REAL FEDERACIÓN ESPAÑOLA" in upper
            or "REAL FEDERACION ESPANOLA" in upper
            or "COMUNICACION PUBLICA" in upper
            or "COMUNICACIÓN PÚBLICA" in upper
            or "CAMPEONATO NACIONAL" in upper
            or "TEMPORADA:" in upper
            or "JORNADA:" in upper
            or upper in {"I JUGADORES", "II-ENTRENADORES", "I JUGADORES"}
            or re.match(r"^\d+\.\s*-", line)
        ):
            continue
        kept.append(line)
    return "\n".join(kept)


def _team_from_chunk(chunk: str, games_match: re.Match[str]) -> str | None:
    folded = chunk.casefold()
    # Percorso normale: denominazione completa presente in una parentesi o in
    # un testo contiguo. Si sceglie l'alias più lungo per evitare match parziali.
    for known in sorted(LALIGA_SOURCE_TEAM_NAMES, key=len, reverse=True):
        match = re.search(re.escape(known), chunk, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()

    # La trascrizione reale di alcuni PDF RFEF può ordinare male i blocchi di
    # testo. J7, per esempio, rendeva ``(Real 1 partido ... consiguiente
    # Sociedad de Fútbol)``. Ricostruisce solo se prefisso e suffisso combaciano
    # esattamente con una denominazione ufficiale nota (nessun fuzzy matching).
    group = None
    for candidate in re.finditer(r"\(([^()]*)\)", chunk, flags=re.DOTALL):
        if candidate.start() <= games_match.start() <= candidate.end():
            group = candidate.group(1)
            break
    if group is not None:
        local_game = SUSPENSION_RE.search(group)
        if local_game:
            prefix = group[: local_game.start()].strip().casefold()
            suffix = group[local_game.end() :].strip().casefold()
            for known in sorted(LALIGA_SOURCE_TEAM_NAMES, key=len, reverse=True):
                key = known.casefold()
                if prefix and key.startswith(prefix):
                    remainder = key[len(prefix) :].strip()
                    if remainder and remainder in suffix:
                        return known

    # Fallback conservativo: restituisce il testo fra parentesi più vicino alla
    # sanzione; il crosswalk lo marcherà come non abbinato se non canonico.
    groups = list(re.finditer(r"\(([^()]*)\)", chunk, flags=re.DOTALL))
    if groups:
        before = [g for g in groups if g.end() <= games_match.start()]
        after = [g for g in groups if g.start() >= games_match.end()]
        selected = before[-1] if before else (after[0] if after else groups[0])
        raw = selected.group(1)
        raw = re.sub(r"\d+\s+partidos?\s+de\s+suspensi[oó]n\s+por.*", "", raw, flags=re.IGNORECASE | re.DOTALL)
        return " ".join(raw.split()).strip(" .;,") or None
    return None


def _reason_from_chunk(chunk: str, heading: str) -> tuple[str, str]:
    folded = (heading + " " + chunk).casefold()
    if "doble amonestación" in folded or "doble amonestacion" in folded:
        return "doppia ammonizione e conseguente espulsione", "double_yellow"
    if "expulsión directa" in folded or "expulsion directa" in folded:
        return "espulsione diretta durante la partita", "direct_red"
    if "acumulación de amonestaciones" in folded or "acumulacion de amonestaciones" in folded:
        return "accumulo di ammonizioni", "yellow_accumulation"
    trimmed = " ".join(heading.split()).strip(" .:-")
    return (trimmed or "sospensione RFEF; motivo non normalizzato"), "disciplinary_suspension"


def parse_laliga_text(text: str) -> dict[str, Any]:
    """Estrae solo squalifiche calciatori dalla sezione I JUGADORES.

    Le sanzioni per allenatori/ausiliari sono deliberatamente fuori perimetro.
    """
    plain = _plain_text(text)
    folded = plain.casefold()
    if "comunicacion publica de los acuerdos" not in folded and "comunicación pública de los acuerdos" not in folded:
        return {"recognized": False, "reason": "intestazione del comunicato RFEF assente", "rows_extracted": 0}
    section, matchday, _ = _player_section(plain)
    if section is None or matchday is None:
        return {"recognized": False, "reason": "sezione I JUGADORES/JORNADA non riconosciuta", "rows_extracted": 0}
    if "SUSPENSI" not in section.upper() or not ARTICLE_RE.search(section):
        return {"recognized": False, "reason": "sezione sanzioni o riferimenti ad articolo non riconosciuti", "rows_extracted": 0}

    headings = list(re.finditer(r"(?m)^\s*\d+\.\s*-\s*(?P<heading>[^\n]+)", section))
    article_matches = list(ARTICLE_RE.finditer(section))
    rows: list[dict[str, Any]] = []
    cursor = 0
    for article in article_matches:
        chunk = section[cursor : article.start()]
        cursor = article.end()
        suspension = SUSPENSION_RE.search(chunk)
        if not suspension:
            continue

        active_heading = ""
        for heading in headings:
            if heading.start() <= article.start():
                active_heading = heading.group("heading").strip()
            else:
                break
        candidate = _clean_candidate_text(chunk)
        name_matches = list(NAME_RE.finditer(candidate))
        if not name_matches:
            continue
        # Il primo blocco ARTICLE_RE può comprendere anche l'elenco di
        # ammonizioni che precede la prima squalifica; la riga del sanzionato
        # è l'ultima sequenza nominativa prima del riferimento all'articolo.
        name_match = name_matches[-1]
        name = " ".join(name_match.group("name").split()).strip(" .")
        row_start = chunk.casefold().rfind(name.casefold())
        row_chunk = chunk[row_start:] if row_start >= 0 else chunk
        row_suspension = SUSPENSION_RE.search(row_chunk) or suspension
        team = _team_from_chunk(row_chunk, row_suspension)
        if not name or not team:
            continue
        reason, suspension_type = _reason_from_chunk(row_chunk, active_heading)
        rows.append({
            "player_name": name,
            "team_source": team,
            "games": int(suspension.group("games")),
            "reason": reason,
            "suspension_type": suspension_type,
            "disciplinary_article": article.group(1),
            "matchday": matchday,
        })

    unique: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            row["player_name"].casefold(),
            row["team_source"].casefold(),
            row["games"],
            row["disciplinary_article"],
        )
        unique[key] = row
    records = list(unique.values())
    recognized = bool(records)
    return {
        "recognized": recognized,
        "reason": None if recognized else "schema riconosciuto ma zero righe giocatore con squalifica",
        "matchday": matchday,
        "suspended_players": records,
        "rows_extracted": len(records),
    }
