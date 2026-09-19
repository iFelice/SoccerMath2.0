"""
update_xg.py - Medie xG stagionali derivate dall'archivio per-partita.

QUESTO SCRIPT NON SCARICA PIU' NULLA DA UNDERSTAT.
L'unica acquisizione Understat e' ``update_all_xg_db.py`` (root del repo), che
salva l'archivio per-partita ``database/xG archivio <lega>.json``. Qui si
derivano soltanto i file ``database/xg_<lega>.json`` consumati dall'app:

    {"Inter": {"xG_avg": 2.36, "xGA_avg": 0.83, "matches": 3}, ...}

con, per ogni partita valida della stagione richiesta:
    squadra di casa   -> xG = home_xg, xGA = away_xg
    squadra ospite    -> xG = away_xg, xGA = home_xg
    matches           -> partite valide effettivamente incluse

Il file mantiene il nome storico per compatibilita' (workflow, import esistenti,
``audit/test_ng_regression.py`` che usa ``update_xg.NAME_MAP``).

Uso:
    python update_xg.py                        # stagione corrente, tutte le leghe
    python update_xg.py --season 2025
    python update_xg.py --league "Serie A" --dry-run
    python update_xg.py --cutoff 2026-09-05T12:00:00+02:00   # audit point-in-time
    python update_xg.py --report audit/results/xg_derivation.json

Garanzie:
  * niente shrinkage qui (resta in ``app.get_league_engine``, PRIOR_MATCHES=6);
  * scrittura atomica: un errore non lascia file parziali;
  * se l'archivio manca/non valida o produce meno di ``--min-teams`` squadre,
    il file esistente NON viene sovrascritto e l'uscita e' diversa da zero;
    ECCEZIONE dichiarata: se la stagione richiesta ha meno di ``--min-teams``
    partite in archivio (pre-stagione o prima giornata, tipicamente luglio -
    agosto dopo il rollover del 1° luglio) la lega viene SALTATA con uscita 0
    (``season_not_started`` / ``season_starting`` nel report): il file della
    stagione precedente resta valido e la catena automatica non fallisce.
    La tolleranza vale SOLO entro il 15 settembre dell'anno di inizio stagione
    (``season_calendar.pre_season_deadline``): oltre quella data una stagione
    ancora vuota o quasi e' un guasto (date illeggibili, cutoff sbagliato,
    stagione mai acquisita a monte) o un calendario eccezionale, e BLOCCA
    invece di essere scambiata per pre-stagione;
  * VALIDAZIONE NOMI BLOCCANTE E PREVENTIVA: se un nome dell'archivio non e'
    risolto dalla tabella condivisa (``team_aliases``), o se due nomi grezzi
    diversi collassano sullo stesso nome canonico senza essere dichiarati in
    ``ACCEPTED_COLLISIONS``, la lega fallisce PRIMA di scrivere. I nomi gia'
    canonici sono accettati esplicitamente (nessun falso allarme) e non c'e'
    nessun fuzzy matching: niente viene indovinato.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import CURRENT_SEASON_START_YEAR  # noqa: E402
from season_calendar import (  # noqa: E402
    pre_season_deadline,
    within_pre_season_tolerance,
)
from team_names import NAME_MAP, UNDERSTAT_NAME_MAP, canonical_team_name  # noqa: E402
from xg_archive import (  # noqa: E402
    ARCHIVE_TIMEZONE,
    CUTOFF_POLICIES,
    DEFAULT_CUTOFF_POLICY,
    LEAGUES,
    SeasonAggregate,
    archive_path,
    averages_path,
    load_archive,
    season_averages,
    validate_archive,
    write_averages,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("update_xg")

# Numero minimo di squadre perche' il file derivato sia utilizzabile:
# ``scraper_xg.get_understat_xg`` e ``get_league_engine`` scartano i file con
# meno di 10 squadre, quindi pubblicarne uno piu' piccolo significherebbe
# soltanto distruggere l'ultimo insieme valido.
MIN_TEAMS = 10

# Collisioni dichiarate: nome canonico -> nomi grezzi che possono legittimamente
# convergere nella STESSA stagione (es. due grafie note dello stesso club nello
# stesso archivio). Vuoto: sui dati reali delle 5 leghe, stagioni 2022-2026, non
# esiste nessuna collisione (vedi audit/results/xg_name_audit.md). Aggiungere una
# voce qui e' una decisione esplicita e tracciabile, non un silenzioso "ok".
ACCEPTED_COLLISIONS: Dict[str, List[str]] = {}

__all__ = [
    "NAME_MAP", "UNDERSTAT_NAME_MAP", "canonical_team_name",
    "MIN_TEAMS", "ACCEPTED_COLLISIONS", "mapping_errors",
    "derive_league", "main",
]


def mapping_errors(
    aggregate: SeasonAggregate,
    *,
    league: str = "",
    accepted_collisions: Optional[Dict[str, List[str]]] = None,
) -> List[str]:
    """Errori di mappatura che devono BLOCCARE la pubblicazione.

    1. nomi non risolti: presenti nell'archivio ma assenti dalla tabella
       condivisa e non riconducibili a un nome canonico dichiarato. Verrebbero
       pubblicati con il nome grezzo e l'engine non li troverebbe (cadrebbe sul
       fallback gol) senza che nessuno se ne accorga;
    2. collisioni non giustificate: due nomi grezzi diversi che finiscono sullo
       stesso nome canonico, sommando partite di squadre potenzialmente diverse.
    """
    accepted = ACCEPTED_COLLISIONS if accepted_collisions is None else accepted_collisions
    prefix = f"{league}: " if league else ""
    errors: List[str] = []

    unmapped = sorted(aggregate.unmapped_names)
    if unmapped:
        errors.append(
            f"{prefix}{len(unmapped)} nomi non risolti dalla tabella condivisa "
            f"(team_aliases.py): {', '.join(unmapped)}. "
            "Aggiungere l'alias esplicito prima di pubblicare le medie.")

    for canonical, raws in aggregate.name_collisions.items():
        if sorted(accepted.get(canonical, [])) == raws:
            continue
        errors.append(
            f"{prefix}collisione non dichiarata su '{canonical}': "
            f"{', '.join(raws)}. Se e' corretta, dichiararla in "
            "update_xg.ACCEPTED_COLLISIONS.")
    return errors


# Partite della stagione scartate NON per difetto dei dati xG: non giocate,
# oltre il cutoff, o senza squadre. Il resto (giocate ed eleggibili) e' il
# numeratore con cui si distingue "stagione non ancora iniziata" da "xG assenti".
_NOT_YET_PLAYABLE = (
    "non_giocata", "dopo_cutoff", "giorno_del_cutoff_o_dopo",
    "data_illeggibile_con_cutoff", "squadra_mancante",
)


def played_before_cutoff(aggregate: SeasonAggregate) -> int:
    """Partite della stagione gia' giocate ed entro il cutoff (a prescindere
    dalla validita' degli xG)."""
    skipped = aggregate.skipped or {}
    return max(0, aggregate.matches_in_season
               - sum(skipped.get(k, 0) for k in _NOT_YET_PLAYABLE))


def derive_league(
    league: str,
    season: int,
    *,
    database_dir=None,
    cutoff=None,
    cutoff_policy: str = DEFAULT_CUTOFF_POLICY,
    day_timezone=None,
    min_teams: int = MIN_TEAMS,
    dry_run: bool = False,
    allow_unmapped_names: bool = False,
) -> Dict:
    """Deriva e (se valido) scrive ``xg_<lega>.json`` per una lega."""
    out: Dict = {
        "league": league,
        "season": season,
        "written": False,
        "path": averages_path(league, database_dir),
        "errors": [],
    }
    src = archive_path(league, database_dir)
    if not os.path.exists(src):
        out["errors"].append(f"archivio mancante: {src}")
        return out
    try:
        records = load_archive(league, database_dir)
    except Exception as exc:  # file corrotto / JSON invalido
        out["errors"].append(f"archivio illeggibile ({exc})")
        return out

    problems = validate_archive(records, league=league, min_matches=1)
    if problems:
        out["errors"].extend(problems)
        return out

    aggregate: SeasonAggregate = season_averages(
        league, season, base_dir=database_dir, cutoff=cutoff,
        cutoff_policy=cutoff_policy,
        day_timezone=ARCHIVE_TIMEZONE if day_timezone is None else day_timezone,
        records=records)
    out.update(aggregate.to_dict())

    # --- validazione nomi PRIMA di qualunque scrittura -------------------
    name_problems = mapping_errors(aggregate, league=league)
    if name_problems:
        if allow_unmapped_names:
            out["warnings"] = name_problems
            for problem in name_problems:
                log.warning("%s (ignorato per --allow-unmapped-names)", problem)
        else:
            out["errors"].extend(name_problems)
            return out  # file precedente intatto: niente scrittura parziale

    if len(aggregate.averages) < min_teams:
        # Pre-stagione / prima giornata: la stagione richiesta (di default
        # quella corrente, che dal 1° luglio e' la NUOVA stagione) non ha
        # ancora abbastanza partite nell'archivio. Non e' un guasto: il file
        # della stagione precedente resta al suo posto e la catena automatica
        # (workflow update_xg) non deve fallire finche' Understat non pubblica
        # le prime giornate. Con almeno ``min_teams`` partite in stagione e
        # ancora meno di ``min_teams`` squadre valide il problema e' invece
        # reale (xG mancanti nell'archivio) e resta bloccante.
        played = played_before_cutoff(aggregate)
        if played < min_teams:
            # ...ma SOLO finche' l'istante di riferimento (il cutoff, oppure
            # "adesso" se non e' dato) resta entro il 15 settembre dell'anno
            # di inizio stagione. Oltre quella data (su nessuna delle 25
            # stagioni lega x 2022/23->2026/27 osservate c'erano meno di 27
            # partite giocate al 15/9) la scarsita' di partite NON e'
            # pre-stagione: senza questo limite un archivio con le date
            # illeggibili, un cutoff sbagliato o la stagione mai acquisita a
            # monte verrebbe scambiato per "non ancora iniziata" per sempre,
            # con uscita 0 e il file vecchio al suo posto.
            as_of = (aggregate.cutoff.date()
                     if getattr(aggregate, "cutoff", None) is not None else None)
            if within_pre_season_tolerance(season, when=as_of):
                out["season_not_started"] = played == 0
                out["season_starting"] = played > 0
                out["pre_season"] = (
                    f"stagione {season}/{season + 1} non ancora "
                    f"{'iniziata' if played == 0 else 'a regime'}: "
                    f"{played} partite giocate su {aggregate.matches_in_season} in "
                    f"archivio, {len(aggregate.averages)} squadre valide (minimo "
                    f"{min_teams}); file esistente lasciato invariato (pre-stagione, "
                    "non e' un errore)")
                return out
            skipped = aggregate.skipped or {}
            out["errors"].append(
                f"stagione {season}/{season + 1} con solo {played} partite "
                f"giocate su {aggregate.matches_in_season} in archivio "
                f"({len(aggregate.averages)} squadre valide, minimo {min_teams}) "
                f"con istante di riferimento oltre il "
                f"{pre_season_deadline(season).isoformat()} (termine della "
                "tolleranza pre-stagione): non e' pre-stagione. Possibili cause: "
                f"date illeggibili ({skipped.get('data_illeggibile_con_cutoff', 0)} "
                f"partite), cutoff errato, stagione mai acquisita a monte o "
                "calendario eccezionale — verifica manuale; file esistente "
                "lasciato invariato")
            return out
        out["errors"].append(
            f"solo {len(aggregate.averages)} squadre con partite valide "
            f"(minimo {min_teams}) su {played} partite giocate in stagione: "
            "file esistente lasciato invariato")
        return out

    if not dry_run:
        write_averages(aggregate, out["path"])
        out["written"] = True
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deriva le medie xG stagionali dall'archivio per-partita "
                    "(nessuno scraping: l'acquisizione e' update_all_xg_db.py)")
    parser.add_argument("--season", type=int, default=CURRENT_SEASON_START_YEAR,
                        help="anno di inizio stagione (default: stagione corrente)")
    parser.add_argument("--league", action="append", dest="leagues",
                        choices=list(LEAGUES),
                        help="limita a una lega (ripetibile)")
    parser.add_argument("--database-dir", default=None,
                        help="cartella dei dati (default: SoccerMath/database)")
    parser.add_argument("--cutoff", default=None,
                        help="istante di previsione ISO-8601 (audit point-in-time)")
    parser.add_argument("--cutoff-policy", default=DEFAULT_CUTOFF_POLICY,
                        choices=list(CUTOFF_POLICIES),
                        help="previous_day (default, conservativo: esclude tutto "
                             "il giorno del cutoff, quindi anche le partite in "
                             "corso) oppure kickoff_unsafe (kickoff < cutoff, "
                             "non verificato)")
    parser.add_argument("--day-timezone", default="UTC",
                        help="fuso in cui contare i giorni per il cutoff "
                             "(default UTC, es. Europe/Rome)")
    parser.add_argument("--allow-unmapped-names", action="store_true",
                        help="NON usare in produzione: declassa a warning gli "
                             "errori di mappatura invece di bloccare")
    parser.add_argument("--min-teams", type=int, default=MIN_TEAMS,
                        help=f"squadre minime per pubblicare il file (default {MIN_TEAMS})")
    parser.add_argument("--dry-run", action="store_true",
                        help="calcola e stampa senza scrivere nulla")
    parser.add_argument("--report", default=None,
                        help="salva un riepilogo JSON della derivazione")
    args = parser.parse_args(argv)

    leagues = args.leagues or list(LEAGUES)
    results = []
    failures = 0
    skipped = 0

    for league in leagues:
        res = derive_league(
            league, args.season,
            database_dir=args.database_dir,
            cutoff=args.cutoff,
            cutoff_policy=args.cutoff_policy,
            day_timezone=args.day_timezone,
            min_teams=args.min_teams,
            dry_run=args.dry_run,
            allow_unmapped_names=args.allow_unmapped_names,
        )
        results.append(res)
        if res["errors"]:
            failures += 1
            for err in res["errors"]:
                log.error("%s", err)
            continue
        if res.get("pre_season"):
            skipped += 1
            log.info("%s: %s", league, res["pre_season"])
            continue
        log.info(
            "%s %s: %d squadre, %d partite valide su %d in stagione%s%s",
            "[dry-run]" if args.dry_run else "OK", league,
            res["teams"], res["matches_used"], res["matches_in_season"],
            f" (cutoff {res['cutoff']})" if res.get("cutoff") else "",
            "" if res["written"] else " [non scritto]",
        )
        if res["unmapped_names"]:
            log.warning("%s: nomi Understat senza mapping esplicito: %s",
                        league, ", ".join(sorted(res["unmapped_names"])))
        if res.get("name_collisions"):
            log.warning("%s: collisioni di nomi: %s", league,
                        res["name_collisions"])
        if res["conflicts"]:
            log.warning("%s: %d conflitti xG sulla stessa partita",
                        league, len(res["conflicts"]))
        if res["teams_without_valid_matches"]:
            log.info("%s: senza partite valide (fallback gol nell'engine): %s",
                     league, ", ".join(res["teams_without_valid_matches"]))

    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)) or ".", exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump({"season": args.season, "leagues": results}, f,
                      ensure_ascii=False, indent=2)
        log.info("Report salvato in %s", args.report)

    ok = len(leagues) - failures - skipped
    log.info("Completato: %d/%d leghe aggiornate%s", ok, len(leagues),
             f", {skipped} in attesa dell'inizio stagione" if skipped else "")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
