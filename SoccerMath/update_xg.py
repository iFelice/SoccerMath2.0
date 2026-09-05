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
    il file esistente NON viene sovrascritto e l'uscita e' diversa da zero.
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
from team_names import NAME_MAP, UNDERSTAT_NAME_MAP, canonical_team_name  # noqa: E402
from xg_archive import (  # noqa: E402
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

__all__ = [
    "NAME_MAP", "UNDERSTAT_NAME_MAP", "canonical_team_name",
    "MIN_TEAMS", "derive_league", "main",
]


def derive_league(
    league: str,
    season: int,
    *,
    database_dir=None,
    cutoff=None,
    min_teams: int = MIN_TEAMS,
    dry_run: bool = False,
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
        league, season, base_dir=database_dir, cutoff=cutoff, records=records)
    out.update(aggregate.to_dict())

    if len(aggregate.averages) < min_teams:
        out["errors"].append(
            f"solo {len(aggregate.averages)} squadre con partite valide "
            f"(minimo {min_teams}): file esistente lasciato invariato")
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
                        help="istante di previsione ISO-8601: include solo le "
                             "partite concluse prima (audit point-in-time)")
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

    for league in leagues:
        res = derive_league(
            league, args.season,
            database_dir=args.database_dir,
            cutoff=args.cutoff,
            min_teams=args.min_teams,
            dry_run=args.dry_run,
        )
        results.append(res)
        if res["errors"]:
            failures += 1
            for err in res["errors"]:
                log.error("%s", err)
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

    ok = len(leagues) - failures
    log.info("Completato: %d/%d leghe aggiornate", ok, len(leagues))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
