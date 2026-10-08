"""
season_rosters.py - R(lega, stagione) dal CALENDARIO, non dalle partite giocate.

Il seed Elo degli ingressi in lega ha bisogno della composizione del
campionato PRIMA del via: promozioni, retrocessioni e calendario sono noti
prima della prima giornata, i risultati no. Derivare il roster dalle partite
GIOCATE (``season_rosters_from_matches``) funziona solo a stagione in corso,
quando ogni squadra ha gia' disputato almeno una partita; prima del via il
roster sarebbe vuoto e il seed solleverebbe ``EloSeedError``.

Questo modulo e' l'input offline e deterministico che chiude il buco:

* ``update_db.py`` salva qui, a ogni fetch, le squadre viste nel calendario
  COMPLETO dell'API (prima dello scarto delle partite non giocate, che
  restano escluse dai CSV come oggi);
* ``EloEngine.compute_ratings`` legge qui il roster della stagione corrente
  (e di qualunque stagione presente nel file) invece di ricavarlo dalle
  partite giocate; per le stagioni concluse senza voce nel file resta la
  derivazione dalle partite giocate, per la stagione corrente senza voce
  resta ``EloSeedError`` come oggi.

Nessuna chiamata di rete: il file e' versionato nel database
(``SoccerMath/database/season_rosters.json``) e committato dal workflow di
aggiornamento come i CSV. Formato::

    {"Serie A": {"2022": ["Atalanta", ...], ...}, ...}

chiavi di lega = nomi estesi di ``LEAGUES_CONFIG``, chiavi di stagione = anno
di inizio come stringa JSON, squadre = nomi canonici (``clean_name``) in
ordine alfabetico. Scrittura atomica (temp + rename) e ordinamento stabile:
stesso contenuto, stessi byte.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
from team_aliases import clean_name  # noqa: E402
from season_calendar import (  # noqa: E402
    roster_deadline,
    within_roster_tolerance,
)

log = logging.getLogger("season_rosters")

#: Nome del file dentro ``DATABASE_DIR``.
ROSTER_FILENAME = "season_rosters.json"

#: Taglia attesa del roster della stagione corrente, per lega (nomi estesi).
#: La Ligue 1 e' a 18 dal 2023/24 (nel 2022/23 era a 20: la validazione vale
#: solo per la stagione corrente, quindi la taglia storica non conta).
EXPECTED_ROSTER_SIZE = {
    "Serie A": 20,
    "Premier League": 20,
    "La Liga": 20,
    "Bundesliga": 18,
    "Ligue 1": 18,
}


def roster_path(database_dir=None) -> Path:
    """Percorso del file roster (``database_dir`` finto nei test)."""
    base = Path(database_dir) if database_dir is not None else Path(config.DATABASE_DIR)
    return base / ROSTER_FILENAME


def load_season_rosters(database_dir=None) -> Dict[str, Dict[int, List[str]]]:
    """Tutto il file roster: ``{lega: {stagione_int: [squadre]}}``.

    File assente -> ``{}`` (il chiamante ricade sulle partite giocate per le
    stagioni concluse e su ``EloSeedError`` per la corrente, come oggi).
    File illeggibile o malformato -> ``{}`` con WARNING: il motore non deve
    esplodere per un input ausiliario, e la validazione stretta vive nel
    workflow (``validate_current_rosters``), che invece fallisce in modo
    visibile. Nessuna rete, nessuna scrittura.
    """
    path = roster_path(database_dir)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("season_rosters: %s illeggibile (%s), ignorato", path, e)
        return {}
    if not isinstance(raw, dict):
        log.warning("season_rosters: %s non e' un oggetto, ignorato", path)
        return {}
    out: Dict[str, Dict[int, List[str]]] = {}
    for lega, stagioni in raw.items():
        if not isinstance(lega, str) or not isinstance(stagioni, dict):
            continue
        voci: Dict[int, List[str]] = {}
        for chiave, squadre in stagioni.items():
            try:
                stagione = int(chiave)
            except (TypeError, ValueError):
                continue
            if not isinstance(squadre, list):
                continue
            nomi = sorted({str(t) for t in squadre if isinstance(t, str) and str(t)})
            if nomi:
                voci[stagione] = nomi
        if voci:
            out[lega] = voci
    return out


def load_league_rosters(league_name: str, database_dir=None) -> Dict[int, set]:
    """Roster del file per UNA lega: ``{stagione_int: {squadre}}``.

    Accetta nome esteso, short_name o db_prefix (stessa risoluzione di
    ``config.get_league_config``): il file e' indicizzato per nome esteso.
    """
    tutto = load_season_rosters(database_dir)
    if league_name in tutto:
        return {s: set(v) for s, v in tutto[league_name].items()}
    info = config.get_league_config(league_name)
    esteso = (info.get("name") or "") if info else ""
    if esteso and esteso in tutto:
        return {s: set(v) for s, v in tutto[esteso].items()}
    return {}


def save_league_roster(league_name: str, season: int, teams,
                       database_dir=None) -> Path:
    """Salva (merge) il roster di UNA lega/stagione nel file versionato.

    ``league_name`` puo' essere esteso, short o prefisso: nel file finisce il
    nome esteso. ``teams`` e' un iterabile di nomi canonici (gia' passati da
    ``clean_name`` dal chiamante). Le altre voci restano intatte; scrittura
    atomica e ordinamento stabile (leghe, stagioni e squadre ordinate).
    Ritorna il percorso scritto.
    """
    info = config.get_league_config(league_name)
    esteso = (info.get("name") or league_name) if info else league_name
    stagione = int(season)
    nomi = sorted({str(t) for t in teams if t and str(t)})
    path = roster_path(database_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    voce = raw.get(esteso)
    if not isinstance(voce, dict):
        voce = {}
    voce[str(stagione)] = nomi
    raw[esteso] = voce
    ordinato = {lega: {str(s): raw[lega][str(s)] for s in sorted(int(k) for k in raw[lega])}
                for lega in sorted(raw)}
    testo = json.dumps(ordinato, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="season_rosters_", suffix=".json",
                               dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(testo)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return path


def _teams_from_csv(path: str) -> Set[str]:
    """Estrae i nomi canonici (HomeTeam/AwayTeam) di un CSV football-data."""
    out: Set[str] = set()
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                for col in ("HomeTeam", "AwayTeam"):
                    v = (row.get(col) or "").strip()
                    if v:
                        out.add(clean_name(v))
    except Exception:
        pass
    return out


def _known_teams(lega: str, database_dir, stagione: int,
                 tutto: Dict[str, Dict[int, List[str]]]) -> Set[str]:
    """Insieme dei nomi noti per una lega: CSV storici + stagione precedente
    dai roster + Live CSV della stagione corrente."""
    known: Set[str] = set()
    base = Path(database_dir) if database_dir is not None else Path(config.DATABASE_DIR)
    info = config.get_league_config(lega)
    if info:
        prefix = info.get("db_prefix") or info.get("short_name") or ""
        # storici
        for p in base.glob(f"{prefix}_20*.csv"):
            # _Live.csv viene gestito separatamente
            if "_Live" in p.name:
                continue
            known |= _teams_from_csv(str(p))
        # live CSV
        live_path = info.get("live_csv") or str(base / f"{prefix}_Live.csv")
        if os.path.exists(live_path):
            known |= _teams_from_csv(live_path)
    # anche la stagione precedente del roster e' un nome valido
    prev = (tutto.get(lega) or {}).get(stagione - 1) or []
    for t in prev:
        if t:
            known.add(str(t))
    return known


def validate_current_rosters(database_dir=None, now=None,
                             current_season: Optional[int] = None) -> List[str]:
    """Errori espliciti sul roster della stagione corrente (``[]`` = ok).

    Controlli, per ogni lega di ``EXPECTED_ROSTER_SIZE``:

    1. il roster esiste ed ha la taglia attesa (20, 18 per Bundesliga/Ligue 1);
    2. (a) ogni nome nel roster e' un punto fisso di ``clean_name``
       (``clean_name(t) == t``): previene nomi non normalizzati come "Köln";
    3. (b) per la stagione corrente, se il CSV Live contiene partite giocate,
       tutte le squadre ivi presenti devono comparire nel roster
       (altrimenti il seed si sbaglia sugli incumbent/entranti);
    4. (c) ogni nome nel roster deve comparire fra i nomi noti della lega
       (CSV storici + Live + roster della stagione precedente) OPPURE essere
       un entrante (R(s) - R(s-1)) dichiarato.

    Un roster MANCANTE e' ammesso solo entro il 15 luglio dell'anno di inizio
    stagione (``within_roster_tolerance``); dopo il termine, o se presente ma
    non valido, e' un errore che deve fallire il workflow in modo visibile.

    ``now`` accetta date/datetime/None (= adesso UTC); ``current_season``
    forza la stagione (i test non dipendono dall'orologio).
    """
    if current_season is None:
        current_season = config.get_current_season_start_year()
    stagione = int(current_season)
    if now is None:
        now = datetime.now(timezone.utc)
    tutto = load_season_rosters(database_dir)
    errori: List[str] = []
    for lega, attese in sorted(EXPECTED_ROSTER_SIZE.items()):
        squadre = (tutto.get(lega) or {}).get(stagione)
        if squadre is None:
            if within_roster_tolerance(stagione, when=now):
                continue
            errori.append(
                f"{lega} stagione {stagione}/{stagione + 1}: roster MANCANTE in "
                f"{ROSTER_FILENAME} oltre il termine del "
                f"{roster_deadline(stagione).isoformat()} (tolleranza roster: "
                f"assenza ammessa solo prima che il calendario sia pubblicato; "
                f"calendari 2026/27 pubblicati a giugno, primo kickoff mai "
                f"prima del 05/08)")
            continue
        uniche = sorted({str(t) for t in squadre if str(t)})

        # 1) taglia: se sbagliata gli altri controlli sono fuorvianti
        size_ok = True
        if len(uniche) != attese:
            size_ok = False
            errori.append(
                f"{lega} stagione {stagione}/{stagione + 1}: roster con "
                f"{len(uniche)} squadre in {ROSTER_FILENAME}, attese {attese}")

        # 2(a) punto fisso di clean_name
        bad_fixed = [t for t in uniche if clean_name(t) != t]
        for t in bad_fixed:
            errori.append(
                f"{lega} {stagione}/{stagione + 1}: nome nel roster non "
                f"e' un punto fisso di clean_name: {t!r} -> "
                f"{clean_name(t)!r}")

        # 2(b) e 2(c) hanno senso solo se il roster ha la taglia attesa.
        # Il check sul punto fisso (2a) non inibisce il confronto col Live CSV
        # perche' un nome non normalizzato (es. 'Köln') produce il mismatch
        # col Live ('Koln') che e' proprio il difetto che vogliamo segnalare.
        if size_ok:
            base = Path(database_dir) if database_dir is not None else Path(config.DATABASE_DIR)
            info = config.get_league_config(lega)
            live_set: Set[str] = set()
            if info:
                prefix = info.get("db_prefix") or info.get("short_name") or ""
                live_path = info.get("live_csv") or str(base / f"{prefix}_Live.csv")
                if os.path.exists(live_path):
                    live_set = _teams_from_csv(live_path)
            roster_set = set(uniche)
            if live_set:
                missing_in_roster = sorted(live_set - roster_set)
                if missing_in_roster:
                    errori.append(
                        f"{lega} {stagione}/{stagione + 1}: squadre presenti nel "
                        f"Live CSV ma assenti nel roster: {missing_in_roster}")

            # 2(c) nomi noti; le sconosciute sono ammesse solo come entranti
            prev = set((tutto.get(lega) or {}).get(stagione - 1) or [])
            entranti_dichiarati = roster_set - prev
            known = _known_teams(lega, database_dir, stagione, tutto)
            for t in uniche:
                if t in known:
                    continue
                if t in entranti_dichiarati:
                    continue
                errori.append(
                    f"{lega} {stagione}/{stagione + 1}: nome nel roster {t!r} "
                    f"non compare fra i nomi noti della lega (CSV storici + Live "
                    f"+ roster {stagione - 1}) e non e' un entrante dichiarato")
    return errori


def main(argv: Optional[List[str]] = None) -> int:
    """CLI del workflow: ``python season_rosters.py --check`` valida il roster
    della stagione corrente ed esce 1 con errori espliciti su stdout."""
    import argparse
    parser = argparse.ArgumentParser(
        description="Valida il roster della stagione corrente in "
                    f"{ROSTER_FILENAME} (vedi docstring del modulo).")
    parser.add_argument("--check", action="store_true",
                        help="valida e fallisce se il roster manca o e' incompleto")
    parser.add_argument("--season", type=int, default=None,
                        help="forza la stagione (anno di inizio, default: corrente)")
    parser.add_argument("--now", default=None,
                        help="data simulata ISO (YYYY-MM-DD), per verifiche manuali")
    args = parser.parse_args(argv)
    if not args.check:
        parser.print_help()
        return 0
    now = datetime.strptime(args.now, "%Y-%m-%d") if args.now else None
    errori = validate_current_rosters(now=now, current_season=args.season)
    if errori:
        for e in errori:
            print(f"[ERRORE roster] {e}")
        return 1
    stagione = args.season if args.season is not None else config.get_current_season_start_year()
    print(f"Roster stagione {stagione}/{stagione + 1}: ok "
          f"({', '.join(f'{l}={EXPECTED_ROSTER_SIZE[l]}' for l in sorted(EXPECTED_ROSTER_SIZE))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
