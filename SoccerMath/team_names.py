"""
team_names.py - Unica fonte di normalizzazione dei nomi squadra (resolver).

I DATI stanno in ``team_aliases.py`` (modulo foglia, senza dipendenze dal
progetto), condiviso con ``config.py``: qui c'e' solo la logica di
risoluzione. Cosi' non esistono piu' tabelle sovrapposte fra
``config.TEAM_NAME_MAP`` e questo modulo, e non ci sono import circolari.

Nome CANONICO = ``clean_name(nome dei CSV football-data)``, cioe' la chiave con
cui i consumatori reali indicizzano le squadre:

  * ``app.get_league_engine`` costruisce ``stats`` con chiave
    ``clean_name(df['HomeTeam'])`` e cerca gli xG con ``xg_data.get(t)``;
  * ``models/elo_engine.py`` fa lo stesso su ``HomeClean``/``AwayClean``;
  * ``config.MARKET_VALUES`` e' indicizzato sugli stessi nomi.

Esiti possibili della risoluzione (``NameResolution.source``):

  ``"alias"``      il nome grezzo e' in tabella (titolo Understat o alias API);
  ``"canonical"``  il nome e' gia' un nome canonico dichiarato (accettato
                   esplicitamente: nessun falso allarme sui nomi canonici);
  ``"unknown"``    il nome non e' riconosciuto. Non viene indovinato (nessun
                   fuzzy matching): si applica solo ``clean_name`` e il
                   chiamante lo segnala. Nel percorso di produzione
                   (``update_xg.derive_league``) un ``unknown`` BLOCCA la
                   pubblicazione delle medie.
"""

from __future__ import annotations

from typing import Dict, List, NamedTuple

from team_aliases import (
    ALL_ALIASES,
    CANONICAL_NAMES,
    TEAM_NAME_MAP,
    UNDERSTAT_NAME_MAP,
    clean_name,
    conflicting_aliases,
)

# Tabella completa usata dal resolver (alias API + titoli Understat + nomi
# canonici che mappano su se' stessi). Manutenuta in team_aliases.py.
NAME_MAP: Dict[str, str] = ALL_ALIASES

__all__ = [
    "NAME_MAP", "TEAM_NAME_MAP", "UNDERSTAT_NAME_MAP", "CANONICAL_NAMES",
    "NameResolution", "resolve_team_name", "canonical_team_name",
    "canonical_names", "aliases_for", "conflicting_aliases",
]


class NameResolution(NamedTuple):
    """Esito della normalizzazione di un nome squadra."""

    raw: str
    canonical: str
    source: str  # "alias" | "canonical" | "unknown" | "empty"

    @property
    def mapped(self) -> bool:
        """True se il nome e' riconosciuto (alias esplicito o nome canonico)."""
        return self.source in ("alias", "canonical")


def resolve_team_name(name) -> NameResolution:
    """Normalizza ``name`` verso il nome canonico usato dall'app."""
    raw = "" if name is None else str(name).strip()
    if not raw:
        return NameResolution(raw="", canonical="", source="empty")

    mapped_name = NAME_MAP.get(raw)
    if mapped_name is not None:
        canonical = clean_name(mapped_name)
        source = "canonical" if raw == canonical else "alias"
        return NameResolution(raw=raw, canonical=canonical, source=source)

    # Nome gia' canonico scritto in una forma che clean_name normalizza
    # (es. "FC Koln" -> "Koln"): accettato perche' il risultato e' un nome
    # canonico DICHIARATO, non un'ipotesi.
    cleaned = clean_name(raw)
    if cleaned in CANONICAL_NAMES:
        return NameResolution(raw=raw, canonical=cleaned, source="canonical")

    return NameResolution(raw=raw, canonical=cleaned, source="unknown")


def canonical_team_name(name) -> str:
    """Nome canonico (chiave usata da get_league_engine / elo_engine)."""
    return resolve_team_name(name).canonical


def canonical_names() -> set:
    """Insieme dei nomi canonici conosciuti."""
    return set(CANONICAL_NAMES)


def aliases_for(canonical: str) -> List[str]:
    """Tutti i nomi grezzi che si risolvono in ``canonical`` (ordinati)."""
    target = clean_name(canonical)
    return sorted(k for k, v in NAME_MAP.items() if clean_name(v) == target)
