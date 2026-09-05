"""
xg_pipeline_audit.py - Audit sui dati REALI del repository (5 leghe).

Produce due rapporti in ``audit/results/``:

  1. ``xg_name_audit.md``
     Confronto sistematico, lega per lega e stagione per stagione, fra:
       * i titoli Understat presenti negli archivi per-partita,
       * i nomi dei CSV storici football-data (nomi grezzi e ``clean_name``),
       * i nomi effettivamente usati dal motore live (``get_league_engine`` /
         ``elo_engine`` indicizzano su ``clean_name(CSV)``).
     Riporta corrispondenze, alias, collisioni e nomi irrisolti, distinguendo
     le squadre assenti per diversa copertura stagionale dagli errori di
     mapping. Nessun fuzzy matching: solo la tabella esplicita di
     ``SoccerMath/team_names.py``.

  2. ``xg_averages_comparison.md``
     Confronto fra le medie ``xg_<lega>.json`` attualmente committate e quelle
     derivate dall'archivio per la stagione richiesta: copertura, differenze,
     squadre presenti solo da un lato.

Uso:
    python audit/xg_pipeline_audit.py [--season 2026]
    python audit/xg_pipeline_audit.py --database-dir /tmp/verify/database \
        --results-dir /tmp/verify/reports --baseline-ref ""

``--database-dir`` permette di auditare uno snapshot appena scaricato in una
cartella temporanea (modalita' verifica in CI) senza toccare i dati committati.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict

import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from config import clean_name  # noqa: E402
from team_names import resolve_team_name  # noqa: E402
from xg_archive import (  # noqa: E402
    LEAGUES, load_archive, parse_season, season_averages,
)

# Dati del repository. ``DB_DIR`` puo' essere spostato con --database-dir (per
# auditare uno snapshot appena scaricato); ``REPO_DB_DIR`` resta il riferimento
# committato, usato come baseline nel confronto delle medie.
REPO_DB_DIR = os.path.join(_REPO_ROOT, "SoccerMath", "database")
DB_DIR = REPO_DB_DIR
RESULTS_DIR = os.path.join(_AUDIT_DIR, "results")

LEAGUE_PREFIX = {
    "Serie A": "SerieA",
    "Premier League": "Premier",
    "La Liga": "LaLiga",
    "Bundesliga": "Bundesliga",
    "Ligue 1": "Ligue1",
}
XG_FILES = {
    "Serie A": "xg_serie_a.json",
    "Premier League": "xg_premier_league.json",
    "La Liga": "xg_la_liga.json",
    "Bundesliga": "xg_bundesliga.json",
    "Ligue 1": "xg_ligue_1.json",
}


def csv_path(league: str, season: int, current_season: int) -> str:
    """CSV football-data: sempre quelli committati nel repository.

    Anche quando si audita un archivio scaricato altrove (--database-dir), il
    riferimento dei nomi canonici resta il CSV del repo.
    """
    prefix = LEAGUE_PREFIX[league]
    name = f"{prefix}_Live.csv" if season >= current_season else f"{prefix}_{season}.csv"
    candidate = os.path.join(DB_DIR, name)
    if os.path.exists(candidate):
        return candidate
    return os.path.join(REPO_DB_DIR, name)


def csv_teams(path: str):
    """{canonico: {nomi grezzi}} dal CSV football-data."""
    out = defaultdict(set)
    if not os.path.exists(path):
        return out
    df = pd.read_csv(path, low_memory=False)
    for col in ("HomeTeam", "AwayTeam"):
        if col not in df.columns:
            continue
        for raw in df[col].dropna().unique():
            out[clean_name(raw)].add(str(raw))
    return out


def archive_titles(records, season: int):
    """{titolo Understat: n. partite} nella stagione."""
    out = defaultdict(int)
    for rec in records:
        if parse_season(rec.get("season")) != season:
            continue
        for key in ("home_team", "away_team"):
            name = rec.get(key)
            if name:
                out[str(name)] += 1
    return out


def build_name_audit(seasons, current_season):
    report = {}
    for league in LEAGUES:
        records = load_archive(league, DB_DIR)
        league_rows = []
        for season in seasons:
            titles = archive_titles(records, season)
            csv_map = csv_teams(csv_path(league, season, current_season))
            canonical_csv = set(csv_map)

            rows, collisions = [], defaultdict(list)
            for title in sorted(titles):
                res = resolve_team_name(title)
                collisions[res.canonical].append(title)
                if res.canonical in canonical_csv:
                    status = "ok"
                else:
                    status = "mapping_da_verificare"
                rows.append({
                    "understat": title,
                    "canonical": res.canonical,
                    "mapped": res.mapped,
                    "matches": titles[title],
                    "csv_aliases": sorted(csv_map.get(res.canonical, [])),
                    "status": status,
                })
            csv_only = sorted(t for t in canonical_csv
                              if t not in {r["canonical"] for r in rows})
            league_rows.append({
                "season": season,
                "understat_teams": len(titles),
                "csv_teams": len(canonical_csv),
                "rows": rows,
                "collisions": {k: v for k, v in collisions.items() if len(v) > 1},
                "csv_only": csv_only,
            })
        report[league] = league_rows
    return report


def render_name_audit(report, seasons, current_season) -> str:
    out = ["# Audit mapping nomi xG - 5 leghe, dati reali del repository", ""]
    out.append("Nome canonico = `clean_name(nome CSV football-data)`, cioe' la "
               "chiave con cui `app.get_league_engine` e `models/elo_engine.py` "
               "indicizzano le squadre. Fonte unica di traduzione: "
               "`SoccerMath/team_names.py`.")
    out.append("")
    out.append(f"Stagioni analizzate: {', '.join(str(s) for s in seasons)} "
               f"(stagione corrente: {current_season}, CSV `*_Live.csv`).")
    out.append("")

    total_rows = total_ok = total_unmapped = 0
    problems = []
    for league, league_rows in report.items():
        out.append(f"## {league}")
        out.append("")
        out.append("| Stagione | Squadre Understat | Squadre CSV | Corrispondenze | "
                   "Alias espliciti | Collisioni | Non risolti |")
        out.append("|---|---|---|---|---|---|---|")
        for entry in league_rows:
            rows = entry["rows"]
            ok = sum(1 for r in rows if r["status"] == "ok")
            aliases = sum(1 for r in rows if r["mapped"] and r["understat"] != r["canonical"])
            bad = [r for r in rows if r["status"] != "ok"]
            total_rows += len(rows)
            total_ok += ok
            total_unmapped += len(bad)
            out.append(f"| {entry['season']} | {entry['understat_teams']} | "
                       f"{entry['csv_teams']} | {ok}/{len(rows)} | {aliases} | "
                       f"{len(entry['collisions'])} | {len(bad)} |")
            for r in bad:
                problems.append(f"{league} {entry['season']}: "
                                f"`{r['understat']}` -> `{r['canonical']}` "
                                f"non presente fra i nomi CSV della stagione")
            for canonical, titles in entry["collisions"].items():
                problems.append(f"{league} {entry['season']}: collisione su "
                                f"`{canonical}` da {titles}")
            if entry["csv_only"]:
                problems.append(
                    f"{league} {entry['season']}: nomi CSV senza controparte "
                    f"Understat: {entry['csv_only']} (copertura, non mapping)")
        out.append("")

        # dettaglio alias (solo dove il titolo Understat != canonico)
        seen = {}
        for entry in league_rows:
            for r in entry["rows"]:
                if r["understat"] != r["canonical"] or r["csv_aliases"]:
                    key = (r["understat"], r["canonical"])
                    seen.setdefault(key, set()).update(r["csv_aliases"])
        if seen:
            out.append("<details><summary>Alias e nomi CSV corrispondenti</summary>")
            out.append("")
            out.append("| Titolo Understat | Nome canonico | Nomi grezzi nei CSV |")
            out.append("|---|---|---|")
            for (understat, canonical), csv_names in sorted(seen.items()):
                out.append(f"| `{understat}` | `{canonical}` | "
                           f"{', '.join('`%s`' % n for n in sorted(csv_names)) or '-'} |")
            out.append("")
            out.append("</details>")
            out.append("")

    out.insert(4, f"**Sintesi:** {total_ok}/{total_rows} coppie "
                  f"(lega, stagione, squadra) risolte sul nome CSV corretto; "
                  f"{total_unmapped} non risolte.\n")
    out.append("## Anomalie e note")
    out.append("")
    if problems:
        for p in problems:
            out.append(f"- {p}")
    else:
        out.append("- Nessuna anomalia: tutti i titoli Understat degli archivi "
                   "si risolvono in un nome presente nei CSV della stessa "
                   "stagione, senza collisioni.")
    out.append("")

    out.append("## Controlli espliciti richiesti")
    out.append("")
    out.append("| Nome in ingresso | Nome canonico risolto | Presente nella tabella esplicita |")
    out.append("|---|---|---|")
    for name in ["Bayer Leverkusen", "Bayer 04 Leverkusen", "Leverkusen",
                 "Borussia Dortmund", "Dortmund", "Borussia M.Gladbach",
                 "M'gladbach", "Borussia Mönchengladbach", "FC Cologne", "Köln",
                 "FC Koln", "RasenBallsport Leipzig", "RB Leipzig", "Leipzig",
                 "VfB Stuttgart", "Stuttgart", "Athletic Club", "Athletic Bilbao",
                 "Ath Bilbao", "Hull", "Hull City", "Coventry", "Coventry City",
                 "St. Pauli", "St Pauli", "Saint-Etienne", "St Etienne",
                 "Paris Saint Germain", "Paris FC"]:
        res = resolve_team_name(name)
        out.append(f"| `{name}` | `{res.canonical}` | {'si' if res.mapped else 'no (solo clean_name)'} |")
    out.append("")
    return "\n".join(out)


def _baseline_averages(league: str, ref: str):
    """Medie xG di riferimento: file committato in ``ref`` (default main).

    Serve a confrontare le medie PRE-consolidamento con quelle derivate anche
    dopo che i file ``xg_<lega>.json`` sono stati rigenerati nel working tree.
    """
    rel = os.path.relpath(os.path.join(REPO_DB_DIR, XG_FILES[league]), _REPO_ROOT)
    if ref:
        try:
            raw = subprocess.run(
                ["git", "show", f"{ref}:{rel}"],
                cwd=_REPO_ROOT, capture_output=True, check=True, text=True).stdout
            return json.loads(raw), f"{ref}:{rel}"
        except (subprocess.CalledProcessError, json.JSONDecodeError, OSError):
            pass
    path = os.path.join(REPO_DB_DIR, XG_FILES[league])
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), rel
    return {}, rel


def build_averages_comparison(season: int, baseline_ref: str = "") -> str:
    out = ["# Confronto medie xG: file di riferimento vs derivate dall'archivio", ""]
    out.append(f"Stagione derivata: **{season}** (anno di inizio). "
               "Le medie derivate usano solo partite concluse con entrambi gli "
               "xG numerici, finiti e non negativi; nessuno shrinkage "
               "(resta in `get_league_engine`, PRIOR_MATCHES=6).")
    if baseline_ref:
        out.append("")
        out.append(f"Riferimento (\"attuale\"): file `xg_<lega>.json` committati in "
                   f"`{baseline_ref}`, cioe' lo stato precedente al consolidamento.")
    out.append("")
    for league in LEAGUES:
        existing, source = _baseline_averages(league, baseline_ref)
        agg = season_averages(league, season, base_dir=DB_DIR)
        derived = agg.averages

        both = sorted(set(existing) & set(derived))
        only_existing = sorted(set(existing) - set(derived))
        only_derived = sorted(set(derived) - set(existing))

        out.append(f"## {league}")
        out.append("")
        out.append(f"- riferimento: `{source}`")
        out.append(f"- squadre nel file di riferimento: **{len(existing)}** "
                   f"(campo `matches` presente: "
                   f"{sum(1 for v in existing.values() if isinstance(v, dict) and 'matches' in v)})")
        out.append(f"- squadre derivate dall'archivio {season}: **{len(derived)}** "
                   f"(partite valide usate: {agg.matches_used} su "
                   f"{agg.matches_in_season} in calendario)")
        out.append(f"- presenti in entrambi: **{len(both)}**; "
                   f"solo nel riferimento: **{len(only_existing)}**; "
                   f"solo derivate: **{len(only_derived)}**")
        if only_existing:
            out.append(f"- solo nel riferimento: {', '.join('`%s`' % t for t in only_existing)}")
        if only_derived:
            out.append(f"- solo derivate: {', '.join('`%s`' % t for t in only_derived)}")
        out.append("")
        if both:
            out.append("| Squadra | xG rif. | xG derivato | Δ xG | xGA rif. | "
                       "xGA derivato | Δ xGA | matches derivati |")
            out.append("|---|---|---|---|---|---|---|---|")
            d_xg = d_xga = 0.0
            for team in both:
                cur = existing[team] if isinstance(existing[team], dict) else {}
                new = derived[team]
                cxg = cur.get("xG_avg")
                cxga = cur.get("xGA_avg")
                dxg = (new["xG_avg"] - cxg) if isinstance(cxg, (int, float)) else None
                dxga = (new["xGA_avg"] - cxga) if isinstance(cxga, (int, float)) else None
                if dxg is not None:
                    d_xg += abs(dxg)
                if dxga is not None:
                    d_xga += abs(dxga)
                out.append(
                    f"| {team} | {cxg} | {new['xG_avg']} | "
                    f"{'%+.3f' % dxg if dxg is not None else 'n/d'} | {cxga} | "
                    f"{new['xGA_avg']} | {'%+.3f' % dxga if dxga is not None else 'n/d'} | "
                    f"{new['matches']} |")
            out.append("")
            out.append(f"Scostamento medio assoluto: xG {d_xg / len(both):.3f}, "
                       f"xGA {d_xga / len(both):.3f}.")
            out.append("")
        if agg.teams_without_valid_matches:
            out.append("Squadre viste in stagione senza partite valide (escluse "
                       "dal file, fallback gol nell'engine): "
                       + ", ".join(f"`{t}`" for t in agg.teams_without_valid_matches))
            out.append("")
        if agg.unmapped_names:
            out.append(f"Nomi Understat senza mapping esplicito: {agg.unmapped_names}")
            out.append("")
        if agg.duplicates or agg.conflicts:
            out.append(f"Duplicati: {len(agg.duplicates)} - conflitti: {len(agg.conflicts)}")
            out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Audit nomi e medie xG (dati reali)")
    parser.add_argument("--season", type=int, default=None,
                        help="stagione per il confronto delle medie (default: corrente)")
    parser.add_argument("--seasons", nargs="+", type=int, default=None,
                        help="stagioni da auditare (default: tutte quelle in archivio)")
    parser.add_argument("--baseline-ref", default="origin/main",
                        help="ref git da cui leggere le medie di riferimento "
                             "(default: origin/main; stringa vuota = working tree)")
    parser.add_argument("--database-dir", default=None,
                        help="cartella dei dati da auditare "
                             "(default: SoccerMath/database)")
    parser.add_argument("--results-dir", default=None,
                        help="cartella dei report (default: audit/results)")
    args = parser.parse_args(argv)

    global DB_DIR, RESULTS_DIR
    if args.database_dir:
        DB_DIR = os.path.abspath(args.database_dir)
    if args.results_dir:
        RESULTS_DIR = os.path.abspath(args.results_dir)

    from config import CURRENT_SEASON_START_YEAR
    current = CURRENT_SEASON_START_YEAR
    season = args.season or current

    if args.seasons:
        seasons = sorted(args.seasons)
    else:
        found = set()
        for league in LEAGUES:
            for rec in load_archive(league, DB_DIR):
                s = parse_season(rec.get("season"))
                if s:
                    found.add(s)
        seasons = sorted(found)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    report = build_name_audit(seasons, current)
    name_md = render_name_audit(report, seasons, current)
    with open(os.path.join(RESULTS_DIR, "xg_name_audit.md"), "w", encoding="utf-8") as f:
        f.write(name_md + "\n")

    cmp_md = build_averages_comparison(season, args.baseline_ref)
    with open(os.path.join(RESULTS_DIR, "xg_averages_comparison.md"), "w",
              encoding="utf-8") as f:
        f.write(cmp_md + "\n")

    print(name_md)
    print()
    print(cmp_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
