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
  * DIAGNOSTICA preliminare con browser diretto (homepage + pagina lega):
    titolo, dimensioni, presenza della variabile JS allRegions, marcatori
    anti-bot — serve a distinguere "sito bloccato" da "attesa insufficiente";
  * un solo reader per lega (tutte le stagioni insieme), con attesa di
    assestamento pagina maggiorata rispetto al default della libreria;
  * per ogni cella (lega, stagione) sceglie --matches-per-cell partite a
    quantili equispaziati della data (stratificato sul tempo della stagione);
  * per ogni partita chiama read_missing_players(match_id=...) e classifica
    l'esito in stati espliciti:
      OK_ROWS           -> righe assenti presenti (copertura piena);
      OK_EMPTY_SECTION  -> pagina letta, sezione "missing-players" presente
                           nell'HTML cache ma 0 righe (nessun assente: valido);
      SECTION_MISSING   -> pagina letta ma la sezione non c'e' (buco strutturale);
      BLOCKED           -> anti-bot/CAPTCHA (incluso il raise di soccerdata
                           "CAPTCHA detected and could not be solved.");
      FAILED            -> eccezione (rete, parsing, match non trovato);
  * la sezione viene verificata sull'HTML che soccerdata mette comunque in
    cache (~/soccerdata/data/WhoScored/previews/...), cosi' "0 righe" si
    distingue da "sezione assente";
  * circuit breaker: 3 esiti negativi consecutivi in una cella -> il resto
    della cella e' marcato SKIPPED senza sprecare richieste;
  * se un fetch ritorna il JSON "null" (variabile JS assente) la cache viene
    ripulita e il reader ricreato, per non inquinare le celle successive;
  * produce report.json + report.md con copertura per lega, per stagione e
    per cella, e salva fino a --keep-pages pagine anomale per ispezione.

La copertura dichiarata e' una STIMA su campione: il referto riporta per cella
il numero di partite campionate e i suoi stati, non una promessa.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
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

WHOSCORED_HOME = "https://www.whoscored.com/"
LEAGUE_PAGES = {
    "ENG-Premier League": "https://www.whoscored.com/Regions/252/Tournaments/2/England-Premier-League",
    "ESP-La Liga": "https://www.whoscored.com/Regions/206/Tournaments/8/Spain-LaLiga",
}

WHO_DATA_DIR = Path.home() / "soccerdata" / "data" / "WhoScored"
# preview storica usata nella documentazione soccerdata (12/01/2021): se il
# blocco Cloudflare vale anche per lei, la persistenza storica e' irraggiungibile
LEGACY_PREVIEW = "https://www.whoscored.com/Matches/1485184/Preview"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seasons", nargs="+", default=["2223", "2324", "2425", "2526", "2627"])
    ap.add_argument("--leagues", nargs="+", default=DEFAULT_LEAGUES)
    ap.add_argument("--matches-per-cell", type=int, default=8,
                    help="partite campionate per cella lega-stagione (quantili equispaziati)")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--keep-pages", type=int, default=12,
                    help="max pagine HTML anomale da salvare per ispezione")
    ap.add_argument("--skip-diagnose", action="store_true")
    return ap.parse_args()


# ---------------------------------------------------------------------------
# Diagnosi diretta del sito (browser minimo, senza soccerdata)
# ---------------------------------------------------------------------------
def diagnose(out_dir: Path) -> dict:
    from seleniumbase import Driver

    pages_dir = out_dir / "debug_pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    res = {"attempts": []}
    driver = None
    try:
        try:
            driver = Driver(uc=True, headless=False)
            res["mode"] = "headless=False"
        except Exception as e:
            res["headless_false_error"] = repr(e)
            driver = Driver(uc=True, headless=True)
            res["mode"] = "headless=True"
        probe_urls = [("home", WHOSCORED_HOME), *LEAGUE_PAGES.items(),
                      ("legacy_preview", LEGACY_PREVIEW)]
        for label, url in probe_urls:
            # 3 tentativi a distanza: distingue blocco deterministico da sfida
            # Cloudflare transitoria
            for attempt in range(3):
                att = {"label": label, "attempt": attempt + 1, "url": url}
                try:
                    driver.get(url)
                    time.sleep(15)
                    src = driver.page_source or ""
                    att["title"] = driver.title
                    att["source_len"] = len(src)
                    att["allRegions"] = "allRegions" in src
                    att["seasons_select"] = 'id="seasons"' in src
                    att["missing_players"] = 'id="missing-players"' in src
                    att["captcha_markers"] = [m for m in CAPTCHA_MARKERS if m in src]
                    att["cloudflare_page"] = "cloudflare" in src.lower()
                    codes = re.findall(r"[Ee]rror(?:\s+code)?:?\s*(\d{4})", src)
                    att["cf_error_codes"] = sorted(set(codes))
                    h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", src, re.S)
                    att["h1"] = [re.sub(r"<[^>]+>", "", h).strip()[:120] for h in h1s[:3]]
                    fp = pages_dir / f"diag_{label}_{attempt + 1}.html"
                    fp.write_bytes(src.encode("utf-8", errors="ignore")[:512_000])
                except Exception as e:
                    att["error"] = repr(e)
                res["attempts"].append(att)
                print(f"[diagnosi] {label} #{attempt + 1}: {att}", flush=True)
                # se la pagina ha i dati cercati, inutile ritentare
                if att.get("allRegions") or att.get("seasons_select") or att.get("missing_players"):
                    break
                if attempt < 2:
                    time.sleep(20)
    except Exception as e:
        res["fatal"] = repr(e)
        res["traceback"] = traceback.format_exc(limit=4)
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
    return res


# ---------------------------------------------------------------------------
# Reader con attesa maggiorata: copia di _download_and_save della libreria
# (soccerdata 1.9.1, _common.py) con EXTRA_SETTLE secondi aggiunti dopo il
# caricamento pagina, per dare tempo al JS del sito di definire le variabili
# (es. allRegions) prima dell'estrazione.
# ---------------------------------------------------------------------------
def make_reader_class(extra_settle: float):
    import random

    import soccerdata as sd
    from selenium.common.exceptions import JavascriptException

    class SampledWhoScored(sd.WhoScored):
        def _download_and_save(self, url, filepath=None, var=None):
            for i in range(5):
                try:
                    self._driver.get(url)
                    time.sleep(self.rate_limit + random.random() * self.max_delay + extra_settle)

                    if self._is_captcha_present():
                        if i < 4:
                            print(f"[captcha] tentativo {i + 1}/5 su {url}", flush=True)
                            self.solve_captcha()
                            if self._is_captcha_present():
                                self._driver.get(url)
                                time.sleep(5)
                        else:
                            raise Exception("CAPTCHA detected and could not be solved.")

                    try:
                        page_source = self._validate_page(url)
                    except Exception as e:
                        if "CAPTCHA detected" in str(e) and i < 4:
                            self.solve_captcha()
                            page_source = self._validate_page(url)
                        elif i < 4:
                            time.sleep(i * 10)
                            continue
                        else:
                            raise

                    if var is None:
                        response = page_source.encode("utf-8")
                    else:
                        try:
                            response = json.dumps(
                                self._driver.execute_script("return " + var)
                            ).encode("utf-8")
                        except JavascriptException:
                            response = json.dumps(None).encode("utf-8")
                    if not self.no_store and filepath is not None:
                        filepath.parent.mkdir(parents=True, exist_ok=True)
                        with filepath.open(mode="wb") as fh:
                            fh.write(response)
                    import io

                    return io.BytesIO(response)
                except Exception as e:  # fedele all'originale, retry inclusi
                    if "CAPTCHA detected" in str(e) and i < 4:
                        continue
                    print(f"[retry] errore su {url}: {e!r} (tentativo {i + 1}/5)", flush=True)
                    time.sleep(i * 10)
                    self._driver = self._init_webdriver()
                    continue
            raise ConnectionError(f"Could not download {url}.")

    return SampledWhoScored


def purge_null_caches() -> list:
    """Elimina le cache che contengono il JSON 'null' (variabile JS assente):
    se lasciate, soccerdata le riusa e ogni cella successiva fallisce subito."""
    purged = []
    if not WHO_DATA_DIR.exists():
        return purged
    for p in list(WHO_DATA_DIR.glob("tiers.json")) + list(WHO_DATA_DIR.glob("seasons/*.html")):
        try:
            content = p.read_text(errors="ignore").strip()
            if content == "null" or content.startswith("null"):
                p.unlink()
                purged.append(str(p))
        except Exception:
            pass
    return purged


def pick_quantile_matches(schedule: pd.DataFrame, k: int) -> pd.DataFrame:
    df = schedule.sort_values("date").reset_index()
    if len(df) <= k:
        return df
    idx = [round(q * (len(df) - 1)) for q in (i / (k + 1) for i in range(1, k + 1))]
    seen, out = set(), []
    for i in idx:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return df.loc[out]


def preview_cache_path(game_row) -> Path:
    return (WHO_DATA_DIR / "previews"
            / f"{game_row['league']}_{game_row['season']}"
            / f"{int(game_row['game_id'])}.html")


def inspect_cached_page(game_row) -> dict:
    info = {"cache_found": False, "section_present": None, "captcha": None, "bytes": None}
    p = preview_cache_path(game_row)
    if p.exists():
        raw = p.read_bytes()
        info["cache_found"] = True
        info["bytes"] = len(raw)
        text = raw.decode("utf-8", errors="ignore")
        info["section_present"] = 'id="missing-players"' in text
        info["captcha"] = next((m for m in CAPTCHA_MARKERS if m in text), None)
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

    diag = {} if args.skip_diagnose else diagnose(args.out_dir)
    env_info["diagnose"] = diag

    # Se OGNI tentativo di diagnosi non ha ottenuto alcun dato (blocco hard del
    # sito, es. Cloudflare che serve la pagina di blocco agli IP del runner),
    # non ha senso sparare ~100 richieste destinate a fallire: si referta il
    # blocco come esito di fattibilita' a se' stante.
    hard_block = bool(diag) and bool(diag.get("attempts")) and all(
        not (a.get("allRegions") or a.get("seasons_select") or a.get("missing_players"))
        for a in diag["attempts"]
    )
    cells = []
    if hard_block:
        env_info["hard_blocked"] = True
        for league in args.leagues:
            for season in args.seasons:
                cells.append({"league": league, "season": season, "matches": [],
                              "fatal": "HARD_BLOCK: sito irraggiungibile da questo client/IP (vedi diagnosi)"})

    ReaderClass = None if hard_block else make_reader_class(extra_settle=8.0)

    for league in ([] if hard_block else args.leagues):
        print(f"=== {league} ===", flush=True)
        purged = purge_null_caches()
        ws = None
        schedule = None
        fatal = None
        try:
            ws = ReaderClass(leagues=league, seasons=args.seasons)
        except Exception as e:
            fatal = f"constructor: {e!r}"
        if ws is not None:
            try:
                schedule = ws.read_schedule().reset_index()
            except Exception as e:
                fatal = f"schedule: {e!r}"
                tb = traceback.format_exc(limit=3)
                # cache 'null' avvelenata -> ripulisci e riprova una volta
                if "NoneType" in str(e):
                    purged += purge_null_caches()
                    try:
                        try:
                            ws._driver.quit()
                        except Exception:
                            pass
                        ws = ReaderClass(leagues=league, seasons=args.seasons)
                        schedule = ws.read_schedule().reset_index()
                        fatal = None
                    except Exception as e2:
                        fatal = f"schedule(retry): {e2!r}"
        purged += purge_null_caches()

        if fatal or schedule is None:
            for season in args.seasons:
                cells.append({"league": league, "season": season, "matches": [], "fatal": fatal,
                              "purged": purged})
            continue

        present_seasons = list(schedule["season"].unique())
        print(f"[{league}] schedule righe={len(schedule)} stagioni={present_seasons}", flush=True)
        now = datetime.now(timezone.utc)

        for season in args.seasons:
            cell = {"league": league, "season": season, "matches": [], "purged": purged}
            cells.append(cell)
            sub = schedule[schedule["season"].astype(str) == str(season)]
            if len(sub) == 0:
                # stagione assente dallo schedule: informazione di copertura
                alt = schedule[schedule["season"].astype(str).str.contains(str(season)[-2:])]
                if len(alt) > 0:
                    cell["season_alias"] = sorted(alt["season"].astype(str).unique().tolist())
                    sub = alt
                else:
                    cell["fatal"] = "stagione assente dallo schedule"
                    continue
            sample = pick_quantile_matches(sub, args.matches_per_cell)
            consecutive_bad = 0
            rows_iter = list(sample.iterrows())
            for pos, (_, row) in enumerate(rows_iter):
                if consecutive_bad >= 3:
                    for _, rest in rows_iter[pos:]:
                        cell["matches"].append({
                            "game_id": None if pd.isna(rest.get("game_id")) else int(rest["game_id"]),
                            "date": str(rest.get("date")),
                            "home": rest.get("home_team"),
                            "away": rest.get("away_team"),
                            "state": cell.get("skip_reason", "SKIPPED_BLOCKED"),
                            "skipped": True,
                        })
                    break
                rec = {
                    "game_id": None if pd.isna(row.get("game_id")) else int(row["game_id"]),
                    "date": str(row.get("date")),
                    "home": row.get("home_team"),
                    "away": row.get("away_team"),
                    "played": bool(row.get("date") is not None
                                   and pd.to_datetime(row.get("date"), utc=True) < now),
                }
                try:
                    mp = ws.read_missing_players(match_id=rec["game_id"])
                    rec["rows"] = int(len(mp))
                    if rec["rows"] > 0:
                        flat = mp.reset_index()
                        if "status" in flat.columns:
                            rec["status_values"] = sorted(flat["status"].dropna().unique().tolist())
                        if "reason" in flat.columns:
                            rec["reason_sample"] = flat["reason"].dropna().unique()[:5].tolist()
                except Exception as e:
                    rec["rows"] = None
                    rec["error"] = repr(e)
                rec.update(inspect_cached_page(row))
                err = (rec.get("error") or "").lower()
                if rec.get("error") and ("captcha" in err or "blocked" in err):
                    rec["state"] = "BLOCKED"
                elif rec.get("error"):
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
                if rec["state"] in ("BLOCKED", "FAILED"):
                    consecutive_bad += 1
                    if consecutive_bad == 3:
                        cell["skip_reason"] = ("SKIPPED_BLOCKED" if rec["state"] == "BLOCKED"
                                               else "SKIPPED_FAILED")
                else:
                    consecutive_bad = 0
                if rec["state"] not in ("OK_ROWS", "OK_EMPTY_SECTION") and kept_pages < args.keep_pages:
                    p = preview_cache_path(row)
                    if p.exists():
                        dst = pages_dir / f"{league.replace('/', '_')}_{season}_{rec['game_id']}_{rec['state']}.html"
                        dst.write_bytes(p.read_bytes()[:512_000])
                        kept_pages += 1
                cell["matches"].append(rec)
                print(f"[{league} {season}] {rec.get('date','?')[:10]} "
                      f"{rec.get('home','?')} vs {rec.get('away','?')}: {rec['state']} "
                      f"(rows={rec.get('rows')})", flush=True)
        try:
            ws._driver.quit()
        except Exception:
            pass

    # ---- sintesi -----------------------------------------------------------
    def cell_summary(cell: dict) -> dict:
        ms = cell.get("matches", [])
        attempted = [m for m in ms if not m.get("skipped")]
        skipped = len(ms) - len(attempted)
        by_state = {}
        for m in attempted:
            by_state[m["state"]] = by_state.get(m["state"], 0) + 1
        usable = by_state.get("OK_ROWS", 0) + by_state.get("OK_EMPTY_SECTION", 0)
        return {
            "league": cell["league"],
            "season": cell["season"],
            "n_sampled": len(attempted),
            "n_skipped_by_breaker": skipped,
            "states": by_state,
            "usable": usable,
            "coverage_pct": round(100.0 * usable / len(attempted), 1) if attempted else None,
            "fatal": cell.get("fatal"),
            "skip_reason": cell.get("skip_reason"),
            "season_alias": cell.get("season_alias"),
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
    ]
    if diag:
        lines += ["## Diagnosi diretta del sito", "",
                  f"Driver: `{diag.get('mode', '?')}`", "",
                  "| Pagina #tentativo | titolo | bytes | dati presenti | cf_error | h1 |", "|---|---|---|---|---|---|"]
        for att in diag.get("attempts", []):
            dati = ("allRegions" if att.get("allRegions")
                    else "seasons" if att.get("seasons_select")
                    else "missing-players" if att.get("missing_players") else "NESSUNO")
            lines.append(f"| {att.get('label')} #{att.get('attempt')} | {str(att.get('title'))[:45]} | "
                         f"{att.get('source_len')} | {dati} | {att.get('cf_error_codes') or ''} | "
                         f"{str(att.get('h1') or att.get('error') or '')[:80]} |")
        blocked_all = all(not (a.get("allRegions") or a.get("seasons_select")
                               or a.get("missing_players")) for a in diag.get("attempts", []))
        cf_any = any(a.get("cloudflare_page") or a.get("cf_error_codes")
                     for a in diag.get("attempts", []))
        if blocked_all and cf_any:
            lines += ["", "**VERDETTO DIAGNOSI: il sito blocca questo client/IP (pagina Cloudflare "
                      "senza dati in TUTTI i tentativi): le prove sotto riflettono il blocco, non la "
                      "qualita' del dato.**"]
        if diag.get("fatal"):
            lines.append(f"\nDiagnosi fatale: `{diag['fatal']}`")
        lines.append("")
    lines += [
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
    lines += ["", "## Per cella", "", "| Lega | Stagione | n provate | saltate | stati | copertura | note |", "|---|---|---|---|---|---|---|"]
    for s in summaries:
        note = s["fatal"] or s["skip_reason"] or (f"alias={s['season_alias']}" if s.get("season_alias") else "")
        lines.append(f"| {s['league']} | {s['season']} | {s['n_sampled']} | {s['n_skipped_by_breaker']} | {s['states']} | {s['coverage_pct']}% | {note} |")
    lines += [
        "",
        "Stati: OK_ROWS = righe assenti presenti; OK_EMPTY_SECTION = sezione presente ma 0 assenti (dato valido);",
        "SECTION_MISSING = pagina letta senza sezione (buco); BLOCKED = anti-bot/CAPTCHA; FAILED = eccezione;",
        "UNCERTAIN_NO_CACHE = senza cache ispezionabile; SKIPPED_* = non tentate dopo 3 esiti negativi consecutivi.",
    ]
    md = "\n".join(lines)
    (args.out_dir / "report.md").write_text(md, encoding="utf-8")
    print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
