"""
whoscored_missing_players_sample.py — campionamento stratificato SOLA LETTURA
di soccerdata.WhoScored.read_missing_players() sul perimetro Parte B
(5 leghe x stagioni 2022/23–2026/27), per stimare la copertura REALE delle
assenze pre-match storiche (infortuni + squalifiche con status Out/Doubtful).

NON e' codice di produzione: e' lo strumento di verifica eseguito dal workflow
.github/workflows/whoscored_missing_sample.yml, stesso schema di
audit/ppda_deep_player_audit.py (Parte A). Non scrive nel repository: l'output
va nella cartella passata con --out-dir (fuori dal checkout in CI).

Metodo:
  * per ogni cella (lega, stagione) legge lo schedule e sceglie
    --matches-per-cell partite a quantili equispaziati della data (stratificato
    sul tempo della stagione);
  * per ogni partita selezionata chiama read_missing_players(match_id=...) e
    classifica l'esito in uno stato esplicito:
      OK_ROWS           -> righe assenti presenti (copertura piena);
      OK_EMPTY_SECTION  -> pagina letta, sezione "missing-players" presente nel
                           HTML cache ma 0 righe (nessun assente: dato valido);
      SECTION_MISSING   -> pagina letta ma la sezione non c'e' (buco strutturale);
      BLOCKED           -> pagina letta ma con marcatori anti-bot/CAPTCHA;
      FAILED            -> eccezione (rete, parsing, match non trovato);
  * la sezione viene verificata sull'HTML che soccerdata mette comunque in
    cache (~/soccerdata/data/WhoScored/previews/...), cosi' "0 righe" si
    distingue da "sezione assente";
  * produce report.json + report.md con copertura per lega, per stagione e
    per cella, e salva fino a --keep-pages pagine anomale per ispezione.

La copertura dichiarata e' una STIMA su campione: il referto riporta per cella
il numero di partite campionate e il suo intervallo, non una promessa.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

CAPTCHA_MARKERS = (
    "Verify you are human",
    "Checking your browser",
    "Just a moment...",
    "Ray ID:",
    "cf-challenge",
    "Please stand by",
)

DEFAULT_LEAGUES = [
    "ENG-Premier League",
    "ESP-La Liga",
    "ITA-Serie A",
    "GER-Bundesliga",
    "FRA-Ligue 1",
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seasons", nargs="+", default=["2223", "2324", "2425", "2526", "2627"])
    ap.add_argument("--leagues", nargs="+", default=DEFAULT_LEAGUES)
    ap.add_argument("--matches-per-cell", type=int, default=8,
                    help="partite campionate per cella lega-stagione (quantili equispaziati)")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--keep-pages", type=int, default=12,
                    help="max pagine HTML anomale da salvare per ispezione")
    return ap.parse_args()


def pick_quantile_matches(schedule: pd.DataFrame, k: int) -> pd.DataFrame:
    """Sceglie k partite a quantili equispaziati della data (stratificazione
    temporale). In caso di meno partite disponibili, le prende tutte."""
    df = schedule.sort_values("date").reset_index()
    if len(df) <= k:
        return df
    idx = [round(q * (len(df) - 1)) for q in (i / (k + 1) for i in range(1, k + 1))]
    # dedup mantenendo l'ordine
    seen, out = set(), []
    for i in idx:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return df.loc[out]


def preview_cache_paths(game_row) -> list[Path]:
    """Percorsi candidati della preview in cache (soccerdata usa DATA_DIR
    globale ~/soccerdata/data anche quando il reader ha data_dir custom)."""
    league, season, gid = game_row["league"], game_row["season"], game_row["game_id"]
    rel = Path("WhoScored") / "previews" / f"{league}_{season}" / f"{gid}.html"
    return [Path.home() / "soccerdata" / "data" / rel]


def inspect_cached_page(game_row) -> dict:
    info = {"cache_found": False, "section_present": None, "captcha": None, "bytes": None}
    for p in preview_cache_paths(game_row):
        if p.exists():
            info["cache_found"] = True
            raw = p.read_bytes()
            info["bytes"] = len(raw)
            text = raw.decode("utf-8", errors="ignore")
            info["section_present"] = 'id="missing-players"' in text
            info["captcha"] = next((m for m in CAPTCHA_MARKERS if m in text), None)
            break
    return info


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    pages_dir = args.out_dir / "debug_pages"
    pages_dir.mkdir(exist_ok=True)
    kept_pages = 0

    import soccerdata as sd
    from importlib.metadata import version

    env_info = {
        "python": sys.version.split()[0],
        "soccerdata": version("soccerdata"),
        "pandas": pd.__version__,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "seasons": args.seasons,
        "leagues": args.leagues,
        "matches_per_cell": args.matches_per_cell,
    }

    cells = []
    for league in args.leagues:
        for season in args.seasons:
            cell = {"league": league, "season": season, "matches": []}
            cells.append(cell)
            try:
                ws = sd.WhoScored(leagues=league, seasons=season)
            except Exception as e:  # driver/Chrome: esito strutturale
                cell["fatal"] = f"constructor: {e!r}"
                continue
            try:
                schedule = ws.read_schedule().reset_index()
                cell["schedule_rows"] = int(len(schedule))
            except Exception as e:
                cell["fatal"] = f"schedule: {e!r}"
                cell["traceback"] = traceback.format_exc(limit=3)
                continue
            sample = pick_quantile_matches(schedule, args.matches_per_cell)
            now = datetime.now(timezone.utc)
            for _, row in sample.iterrows():
                rec = {
                    "game_id": None if pd.isna(row.get("game_id")) else int(row["game_id"]),
                    "date": str(row.get("date")),
                    "home": row.get("home_team"),
                    "away": row.get("away_team"),
                    "played": bool(row.get("date") is not None and pd.to_datetime(row.get("date"), utc=True) < now),
                }
                try:
                    mp = ws.read_missing_players(match_id=rec["game_id"])
                    rec["rows"] = int(len(mp))
                    if rec["rows"] > 0:
                        status = mp.reset_index().get("status")
                        rec["status_values"] = sorted(status.dropna().unique().tolist()) if status is not None else []
                        rec["reason_sample"] = mp.reset_index()["reason"].dropna().unique()[:5].tolist() if "reason" in mp.reset_index().columns else []
                except Exception as e:
                    rec["rows"] = None
                    rec["error"] = repr(e)
                rec.update(inspect_cached_page(row))
                # classificazione esplicita
                if rec.get("error"):
                    rec["state"] = "FAILED"
                elif rec.get("captcha"):
                    rec["state"] = "BLOCKED"
                elif rec["rows"] and rec["rows"] > 0:
                    rec["state"] = "OK_ROWS"
                elif rec.get("section_present") is True:
                    rec["state"] = "OK_EMPTY_SECTION"
                elif rec.get("cache_found") and rec.get("section_present") is False:
                    rec["state"] = "SECTION_MISSING"
                else:
                    rec["state"] = "UNCERTAIN_NO_CACHE"
                # conserva pagine anomale per ispezione (con tetto)
                if rec["state"] not in ("OK_ROWS", "OK_EMPTY_SECTION") and kept_pages < args.keep_pages:
                    for p in preview_cache_paths(row):
                        if p.exists():
                            dst = pages_dir / f"{league.replace('/', '_')}_{season}_{rec['game_id']}_{rec['state']}.html"
                            dst.write_bytes(p.read_bytes()[:512_000])
                            kept_pages += 1
                            break
                cell["matches"].append(rec)
                print(f"[{league} {season}] {rec.get('date','?')[:10]} "
                      f"{rec.get('home','?')} vs {rec.get('away','?')}: {rec['state']} "
                      f"(rows={rec.get('rows')})", flush=True)

    # ---- sintesi per cella, lega, stagione -------------------------------
    def cell_summary(cell: dict) -> dict:
        ms = cell.get("matches", [])
        n = len(ms)
        by_state = {}
        for m in ms:
            by_state[m["state"]] = by_state.get(m["state"], 0) + 1
        usable = by_state.get("OK_ROWS", 0) + by_state.get("OK_EMPTY_SECTION", 0)
        return {
            "league": cell["league"],
            "season": cell["season"],
            "n_sampled": n,
            "states": by_state,
            "usable": usable,
            "coverage_pct": round(100.0 * usable / n, 1) if n else None,
            "fatal": cell.get("fatal"),
            "schedule_rows": cell.get("schedule_rows"),
        }

    summaries = [cell_summary(c) for c in cells]

    def agg(key: str) -> list:
        out = {}
        for s in summaries:
            k = s[key]
            a = out.setdefault(k, {"usable": 0, "n": 0, "states": {}})
            a["usable"] += s["usable"]
            a["n"] += s["n_sampled"]
            for st, c in s["states"].items():
                a["states"][st] = a["states"].get(st, 0) + c
        return [{"key": k, **v, "coverage_pct": round(100.0 * v["usable"] / v["n"], 1) if v["n"] else None}
                for k, v in sorted(out.items())]

    report = {
        "env": env_info,
        "per_cell": summaries,
        "per_league": agg("league"),
        "per_season": agg("season"),
        "kept_debug_pages": kept_pages,
    }
    (args.out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Campionamento WhoScored read_missing_players — copertura perimetro Parte B",
        "",
        f"- generato: `{report['env']['generated_utc']}` (soccerdata `{report['env']['soccerdata']}`, python {report['env']['python']})",
        f"- stagioni: `{report['env']['seasons']}`; leghe: {len(report['env']['leagues'])}; partite per cella: {report['env']['matches_per_cell']}",
        "",
        "## Per lega",
        "",
        "| Lega | Campionate | Utilizzabili | Copertura | Stati |",
        "|---|---|---|---|---|",
    ]
    for a in report["per_league"]:
        lines.append(f"| {a['key']} | {a['n']} | {a['usable']} | {a['coverage_pct']}% | {a['states']} |")
    lines += ["", "## Per stagione", "", "| Stagione | Campionate | Utilizzabili | Copertura | Stati |", "|---|---|---|---|---|"]
    for a in report["per_season"]:
        lines.append(f"| {a['key']} | {a['n']} | {a['usable']} | {a['coverage_pct']}% | {a['states']} |")
    lines += ["", "## Per cella", "", "| Lega | Stagione | n | stati | copertura | fatale |", "|---|---|---|---|---|---|"]
    for s in summaries:
        lines.append(f"| {s['league']} | {s['season']} | {s['n_sampled']} | {s['states']} | {s['coverage_pct']}% | {s['fatal'] or ''} |")
    lines += [
        "",
        "Stati: OK_ROWS = righe assenti presenti; OK_EMPTY_SECTION = sezione presente ma 0 assenti (dato valido);",
        "SECTION_MISSING = pagina letta senza sezione (buco); BLOCKED = anti-bot; FAILED = eccezione; UNCERTAIN_NO_CACHE = senza cache ispezionabile.",
    ]
    md = "\n".join(lines)
    (args.out_dir / "report.md").write_text(md, encoding="utf-8")
    print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
