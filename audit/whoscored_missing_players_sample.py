"""
whoscored_missing_players_sample.py — campionamento stratificato SOLA LETTURA
delle assenze pre-match di WhoScored sul perimetro Parte B (5 leghe x
stagioni 2022/23–2026/27), per stimare la copertura REALE di
read_missing_players() (infortuni + squalifiche con status Out/Doubtful).

NON e' codice di produzione: e' lo strumento di verifica eseguito dal workflow
.github/workflows/whoscored_missing_sample.yml, stesso schema di
audit/ppda_deep_player_audit.py (Parte A). Non scrive nel repository: l'output
va nella cartella passata con --out-dir (fuori dal checkout in CI).

Strategia a due vie (decisa da sonde preliminari, refertate):
  1. SONDA HTTP pura (curl_cffi, TLS impersonation "chrome"): distingue il
     blocco del fingerprint Selenium dal blocco dell'IP/ASN. Se passa, il
     campionamento avviene via HTTP sugli stessi endpoint usati da soccerdata
     (pagina stagione -> stage, /tournaments/{stage}/data/?d=YYYYMM per il
     calendario JSON, /Matches/{id}/Preview per le assenze) con la stessa
     xpath di read_missing_players;
  2. altrimenti SONDA/via Selenium (soccerdata, uc=True) con attesa
     maggiorata;
  3. se anche quella e' bloccata: verdetto HARD_BLOCK (Cloudflare che serve la
     pagina di blocco su ogni tentativo), refertato come esito di fattibilita'.

Per ogni partita campionata (quantili equispaziati nella stagione per cella)
l'esito e' classificato in stati espliciti:
  OK_ROWS / OK_EMPTY_SECTION / SECTION_MISSING / BLOCKED / FAILED;
con circuit breaker (3 esiti negativi consecutivi -> resto cella SKIPPED).

La copertura dichiarata e' una STIMA su campione: il referto riporta per cella
il numero di partite tentate e i loro stati, non una promessa.
"""

from __future__ import annotations

import argparse
import json
import random
import re
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
    "Sorry, you have been blocked",
    "Attention Required",
)

DEFAULT_LEAGUES = [
    "ENG-Premier League",
    "ESP-La Liga",
    "ITA-Serie A",
    "GER-Bundesliga",
    "FRA-Ligue 1",
]

# ID stabili di WhoScored (verificati nelle URL pubbliche del sito)
LEAGUE_META = {
    "ENG-Premier League": {"region_id": 252, "league_id": 2, "slug": "England-Premier-League"},
    "ESP-La Liga": {"region_id": 206, "league_id": 8, "slug": "Spain-LaLiga"},
    "ITA-Serie A": {"region_id": 110, "league_id": 5, "slug": "Italy-Serie-A"},
    "GER-Bundesliga": {"region_id": 81, "league_id": 3, "slug": "Germany-Bundesliga"},
    "FRA-Ligue 1": {"region_id": 61, "league_id": 7, "slug": "France-Ligue-1"},
}

WHOSCORED_HOME = "https://www.whoscored.com/"
LEGACY_PREVIEW = "https://www.whoscored.com/Matches/1485184/Preview"

# soglia richiesta HTTP -> pausa per rate limit
HTTP_DELAY = 4.0


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


class Throttle:
    def __init__(self, delay: float):
        self.delay = delay
        self.last = 0.0

    def wait(self):
        elapsed = time.time() - self.last
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed + random.random())
        self.last = time.time()


def is_blocked_text(text: str) -> bool:
    return ("Sorry, you have been blocked" in text
            or "Attention Required" in text
            or any(m in text for m in CAPTCHA_MARKERS))


# ---------------------------------------------------------------------------
# Sonda HTTP pura (senza browser)
# ---------------------------------------------------------------------------
def probe_http() -> dict:
    res = {"available": False, "attempts": []}
    try:
        from curl_cffi import requests as cr
    except Exception as e:
        res["error"] = f"curl_cffi non installato: {e!r}"
        return res
    res["available"] = True
    th = Throttle(HTTP_DELAY)
    for label, url in (("home", WHOSCORED_HOME), ("legacy_preview", LEGACY_PREVIEW)):
        for attempt in range(2):
            att = {"label": label, "attempt": attempt + 1}
            try:
                th.wait()
                r = cr.get(url, impersonate="chrome", timeout=40)
                body = r.text or ""
                att["http_status"] = r.status_code
                att["bytes"] = len(body)
                att["missing_players"] = 'id="missing-players"' in body
                att["allRegions"] = "allRegions" in body
                att["seasons_select"] = 'id="seasons"' in body
                att["blocked"] = is_blocked_text(body)
            except Exception as e:
                att["error"] = repr(e)
            res["attempts"].append(att)
            print(f"[sonda-http] {label} #{attempt + 1}: {att}", flush=True)
            if att.get("missing_players") or att.get("allRegions") or att.get("seasons_select"):
                break
            if attempt == 0:
                time.sleep(10)
    return res


# ---------------------------------------------------------------------------
# Campionamento via HTTP (endpoint pubblici gia' usati da soccerdata)
# ---------------------------------------------------------------------------
class HttpSampler:
    def __init__(self, out_dir: Path, keep_pages: int):
        from curl_cffi import requests as cr
        self.cr = cr
        self.th = Throttle(HTTP_DELAY)
        self.out_dir = out_dir
        self.pages_dir = out_dir / "debug_pages"
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.kept_pages = 0
        self.keep_pages = keep_pages
        self.cache_dir = out_dir / "http_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch(self, url: str, tag: str) -> tuple[int, str]:
        self.th.wait()
        r = self.cr.get(url, impersonate="chrome", timeout=40)
        body = r.text or ""
        fp = self.cache_dir / f"{tag}.html"
        try:
            fp.write_bytes(body.encode("utf-8", errors="ignore")[:800_000])
        except Exception:
            pass
        return r.status_code, body

    def season_stage_id(self, meta: dict, season_label_ids: dict) -> int | None:
        return season_label_ids.get("stage_id")

    def league_seasons(self, league: str) -> dict:
        """Ritorna {stagione richiesta: {"season_id":..., "page_html": tag}}
        leggendo la pagina torneo (select seasons server-rendered)."""
        meta = LEAGUE_META[league]
        url = (f"https://www.whoscored.com/Regions/{meta['region_id']}"
               f"/Tournaments/{meta['league_id']}/{meta['slug']}")
        status, body = self.fetch(url, f"league_{league.replace(' ', '_')}")
        out = {"http_status": status, "blocked": is_blocked_text(body), "seasons": {}}
        if out["blocked"]:
            return out
        from lxml import html as lhtml
        try:
            tree = lhtml.fromstring(body)
        except Exception as e:
            out["parse_error"] = repr(e)
            return out
        for node in tree.xpath("//select[contains(@id,'seasons')]/option"):
            label = (node.text or "").strip()
            m = re.match(r"(\d{4})/(\d{2,4})", label)
            if not m:
                continue
            yy = m.group(2)[-2:]
            key = m.group(1)[2:] + yy  # es. "2022/2023" -> "2223"
            href = node.get("value") or ""
            sm = re.search(r"/Seasons/(\d+)", href)
            if sm:
                out["seasons"][key] = {"season_id": int(sm.group(1)), "label": label}
        return out

    def stage_ids(self, league: str, season_id: int) -> list:
        """Stage della stagione dalla pagina stagione (select stages o link
        Fixtures, entrambi server-rendered)."""
        meta = LEAGUE_META[league]
        url = (f"https://www.whoscored.com/Regions/{meta['region_id']}"
               f"/Tournaments/{meta['league_id']}/Seasons/{season_id}")
        status, body = self.fetch(url, f"season_{league.replace(' ', '_')}_{season_id}")
        if is_blocked_text(body):
            return []
        from lxml import html as lhtml
        try:
            tree = lhtml.fromstring(body)
        except Exception:
            return []
        stage_ids = []
        for node in tree.xpath("//select[contains(@id,'stages')]/option"):
            href = node.get("value") or ""
            m = re.search(r"/Stages/(\d+)", href)
            if m:
                stage_ids.append(int(m.group(1)))
        if not stage_ids:
            for href in tree.xpath("//a[text()='Fixtures']/@href"):
                m = re.search(r"/Stages/(\d+)", href)
                if m:
                    stage_ids.append(int(m.group(1)))
        return list(dict.fromkeys(stage_ids))

    def fixtures(self, stage_id: int, months: list) -> tuple[pd.DataFrame, int]:
        rows, blocked = [], 0
        for (year, month) in months:
            # 'd' usa il mese 1-indexed (soccerdata somma +1 al suo calendario
            # perche' lo riceve 0-indexed da wsCalendar; qui e' gia' 1-indexed)
            d = f"{year}{int(month):02d}"
            url = f"https://www.whoscored.com/tournaments/{stage_id}/data/?d={d}"
            try:
                status, body = self.fetch(url, f"fix_{stage_id}_{d}")
                if is_blocked_text(body):
                    blocked += 1
                    continue
                data = json.loads(body)
            except Exception:
                continue
            for tournament in data.get("tournaments", []) if isinstance(data, dict) else []:
                for mch in tournament.get("matches", []):
                    try:
                        # schema uguale a quello usato da soccerdata.read_schedule:
                        # id, startTimeUtc, homeTeamName, awayTeamName
                        rows.append({
                            "game_id": int(mch.get("id")),
                            "date": pd.to_datetime(mch.get("startTimeUtc"), utc=True),
                            "home_team": mch.get("homeTeamName"),
                            "away_team": mch.get("awayTeamName"),
                        })
                    except Exception:
                        continue
        df = pd.DataFrame(rows)
        return df, blocked

    def missing_players(self, game_id: int) -> dict:
        """Fetch della preview e parsing con la stessa xpath di soccerdata."""
        url = f"https://www.whoscored.com/Matches/{game_id}/Preview"
        status, body = self.fetch(url, f"preview_{game_id}")
        rec = {"game_id": game_id, "http_status": status, "bytes": len(body)}
        if is_blocked_text(body):
            rec["state"] = "BLOCKED"
            return rec
        from lxml import html as lhtml
        try:
            tree = lhtml.fromstring(body)
        except Exception as e:
            rec["state"] = "FAILED"
            rec["error"] = f"parse: {e!r}"
            return rec
        section = tree.xpath("//div[@id='missing-players']")
        if not section:
            rec["section_present"] = False
            rec["state"] = "SECTION_MISSING"
            return rec
        rec["section_present"] = True
        players = []
        for div_pos, side in ((2, "home"), (3, "away")):
            for node in tree.xpath(f"//div[@id='missing-players']/div[{div_pos}]/table/tbody/tr"):
                try:
                    pn = node.xpath("./td[contains(@class,'pn')]/a")
                    reason = node.xpath("./td[contains(@class,'reason')]/span/@title")
                    statusv = node.xpath("./td[contains(@class,'confirmed')]/text()")
                    players.append({
                        "side": side,
                        "player": pn[0].text.strip() if pn else None,
                        "player_id": int(pn[0].get("href").split("/")[2]) if pn else None,
                        "reason": reason[0] if reason else None,
                        "status": statusv[0].strip() if statusv else None,
                    })
                except Exception:
                    continue
        rec["rows"] = len(players)
        rec["players_sample"] = players[:6]
        rec["status_values"] = sorted({p["status"] for p in players if p.get("status")})
        rec["state"] = "OK_ROWS" if players else "OK_EMPTY_SECTION"
        # conservazione pagina anomala
        if rec["state"] not in ("OK_ROWS", "OK_EMPTY_SECTION") and self.kept_pages < self.keep_pages:
            dst = self.pages_dir / f"preview_{game_id}_{rec['state']}.html"
            dst.write_bytes(body.encode("utf-8", errors="ignore")[:512_000])
            self.kept_pages += 1
        return rec


def months_for_season(season_key: str, now: datetime) -> list:
    """Agosto->maggio della stagione; per la stagione corrente si ferma al
    mese corrente."""
    start_year = 2000 + int(season_key[:2])
    months = []
    for i in range(10):  # ago(8)..mag(5)
        m = 8 + i
        y = start_year + (1 if m > 12 else 0)
        mm = m if m <= 12 else m - 12
        first_of_month = datetime(y, mm, 1, tzinfo=timezone.utc)
        if first_of_month > now:
            break
        months.append((y, mm))
    return months


def http_sampling(args, probe: dict, env_info: dict) -> tuple[list, dict]:
    sampler = HttpSampler(args.out_dir, args.keep_pages)
    cells = []
    extra = {"per_league_seasons": {}}
    for league in args.leagues:
        print(f"=== HTTP {league} ===", flush=True)
        cell_seasons = {}
        cells_league = []
        try:
            linfo = sampler.league_seasons(league)
        except Exception as e:
            linfo = {"blocked": False, "seasons": {}, "error": repr(e)}
        extra["per_league_seasons"][league] = {
            "http_status": linfo.get("http_status"),
            "blocked": linfo.get("blocked"),
            "seasons_found": sorted(linfo.get("seasons", {}).keys()),
        }
        if linfo.get("blocked") or linfo.get("error"):
            for season in args.seasons:
                cells.append({"league": league, "season": season, "matches": [],
                              "fatal": ("HARD_BLOCK pagina lega" if linfo.get("blocked")
                                        else f"pagina lega: {linfo.get('error')}")})
            continue
        for season in args.seasons:
            cell = {"league": league, "season": season, "matches": []}
            cells_league.append(cell)
            sinfo = linfo.get("seasons", {}).get(season)
            if not sinfo:
                cell["fatal"] = f"stagione {season} assente dalla pagina lega"
                continue
            try:
                stage_ids = sampler.stage_ids(league, sinfo["season_id"])
            except Exception as e:
                cell["fatal"] = f"stage: {e!r}"
                continue
            if not stage_ids:
                cell["fatal"] = "nessuno stage trovato nella pagina stagione"
                continue
            now = datetime.now(timezone.utc)
            months = months_for_season(season, now)
            frames = []
            blocked_months = 0
            for stage_id in stage_ids:
                try:
                    df, nb = sampler.fixtures(stage_id, months)
                    blocked_months += nb
                except Exception as e:
                    cell["fatal"] = f"fixtures: {e!r}"
                    df = pd.DataFrame()
                if len(df):
                    frames.append(df)
            if not frames:
                cell["fatal"] = (cell.get("fatal")
                                 or (f"calendari bloccati da Cloudflare ({blocked_months} mesi)"
                                     if blocked_months else "calendario vuoto"))
                continue
            schedule = pd.concat(frames).drop_duplicates("game_id").sort_values("date")
            cell["schedule_rows"] = int(len(schedule))
            sample = pick_quantile_matches(schedule, args.matches_per_cell)
            consecutive_bad = 0
            rows_iter = list(sample.iterrows())
            for pos, (_, row) in enumerate(rows_iter):
                if consecutive_bad >= 3:
                    for _, rest in rows_iter[pos:]:
                        cell["matches"].append({
                            "game_id": int(rest["game_id"]),
                            "date": str(rest["date"]),
                            "home": rest.get("home_team"),
                            "away": rest.get("away_team"),
                            "state": cell.get("skip_reason", "SKIPPED_BLOCKED"),
                            "skipped": True,
                        })
                    break
                rec = sampler.missing_players(int(row["game_id"]))
                rec.update({"date": str(row["date"]), "home": row.get("home_team"),
                            "away": row.get("away_team"),
                            "played": bool(pd.to_datetime(row["date"], utc=True) < now)})
                cell["matches"].append(rec)
                if rec["state"] in ("BLOCKED", "FAILED"):
                    consecutive_bad += 1
                    if consecutive_bad == 3:
                        cell["skip_reason"] = ("SKIPPED_BLOCKED" if rec["state"] == "BLOCKED"
                                               else "SKIPPED_FAILED")
                else:
                    consecutive_bad = 0
                print(f"[{league} {season}] {str(rec.get('date'))[:10]} "
                      f"{rec.get('home')} vs {rec.get('away')}: {rec['state']} "
                      f"(rows={rec.get('rows')})", flush=True)
        cells.extend(cells_league)
    return cells, extra


# ---------------------------------------------------------------------------
# Via Selenium (soccerdata) — fallback se la sonda HTTP e' bloccata ma il
# browser passa, e per caratterizzare il blocco quando nessuna via passa.
# ---------------------------------------------------------------------------
def diagnose_selenium(out_dir: Path, quick: bool) -> dict:
    from seleniumbase import Driver

    pages_dir = out_dir / "debug_pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    res = {"attempts": []}
    driver = None
    probe_urls = [("home", WHOSCORED_HOME),
                  ("legacy_preview", LEGACY_PREVIEW)]
    if not quick:
        probe_urls.insert(1, ("league_page", LEAGUE_PAGES_URL))
    max_attempts = 1 if quick else 3
    try:
        try:
            driver = Driver(uc=True, headless=False)
            res["mode"] = "headless=False"
        except Exception as e:
            res["headless_false_error"] = repr(e)
            driver = Driver(uc=True, headless=True)
            res["mode"] = "headless=True"
        for label, url in probe_urls:
            for attempt in range(max_attempts):
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
                    att["blocked"] = is_blocked_text(src)
                    h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", src, re.S)
                    att["h1"] = [re.sub(r"<[^>]+>", "", h).strip()[:120] for h in h1s[:3]]
                    fp = pages_dir / f"diag_{label}_{attempt + 1}.html"
                    fp.write_bytes(src.encode("utf-8", errors="ignore")[:512_000])
                except Exception as e:
                    att["error"] = repr(e)
                res["attempts"].append(att)
                print(f"[diagnosi-selenium] {label} #{attempt + 1}: {att}", flush=True)
                if att.get("allRegions") or att.get("seasons_select") or att.get("missing_players"):
                    break
                if attempt < max_attempts - 1:
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


LEAGUE_PAGES_URL = ("https://www.whoscored.com/Regions/252/Tournaments/2/"
                    "England-Premier-League")


def make_reader_class(extra_settle: float):
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
                except Exception as e:
                    if "CAPTCHA detected" in str(e) and i < 4:
                        continue
                    print(f"[retry] errore su {url}: {e!r} (tentativo {i + 1}/5)", flush=True)
                    time.sleep(i * 10)
                    self._driver = self._init_webdriver()
                    continue
            raise ConnectionError(f"Could not download {url}.")

    return SampledWhoScored


def selenium_sampling(args) -> list:
    cells = []
    ReaderClass = make_reader_class(extra_settle=8.0)
    who_dir = Path.home() / "soccerdata" / "data" / "WhoScored"

    def purge_null():
        if not who_dir.exists():
            return
        for p in list(who_dir.glob("tiers.json")) + list(who_dir.glob("seasons/*.html")):
            try:
                if p.read_text(errors="ignore").strip().startswith("null"):
                    p.unlink()
            except Exception:
                pass

    for league in args.leagues:
        purge_null()
        ws = None
        schedule = None
        fatal = None
        try:
            ws = ReaderClass(leagues=league, seasons=args.seasons)
            schedule = ws.read_schedule().reset_index()
        except Exception as e:
            fatal = f"schedule: {e!r}"
            if "NoneType" in str(e):
                purge_null()
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
        if fatal or schedule is None:
            for season in args.seasons:
                cells.append({"league": league, "season": season, "matches": [], "fatal": fatal})
            continue
        now = datetime.now(timezone.utc)
        for season in args.seasons:
            cell = {"league": league, "season": season, "matches": []}
            cells.append(cell)
            sub = schedule[schedule["season"].astype(str) == str(season)]
            if len(sub) == 0:
                alt = schedule[schedule["season"].astype(str).str.contains(str(season)[-2:])]
                sub = alt if len(alt) else sub
            if len(sub) == 0:
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
                            "state": cell.get("skip_reason", "SKIPPED_BLOCKED"),
                            "skipped": True,
                        })
                    break
                rec = {"game_id": None if pd.isna(row.get("game_id")) else int(row["game_id"]),
                       "date": str(row.get("date")),
                       "home": row.get("home_team"), "away": row.get("away_team")}
                try:
                    mp = ws.read_missing_players(match_id=rec["game_id"])
                    rec["rows"] = int(len(mp))
                except Exception as e:
                    rec["rows"] = None
                    rec["error"] = repr(e)
                err = (rec.get("error") or "").lower()
                if rec.get("error") and ("captcha" in err or "blocked" in err or "nonetype" in err):
                    rec["state"] = "BLOCKED" if "captcha" in err or "blocked" in err else "FAILED"
                elif rec["rows"] and rec["rows"] > 0:
                    rec["state"] = "OK_ROWS"
                else:
                    rec["state"] = "UNCERTAIN_NO_CACHE"
                cell["matches"].append(rec)
                if rec["state"] in ("BLOCKED", "FAILED"):
                    consecutive_bad += 1
                    if consecutive_bad == 3:
                        cell["skip_reason"] = "SKIPPED_BLOCKED"
                else:
                    consecutive_bad = 0
                print(f"[selenium {league} {season}] {str(rec.get('date'))[:10]}: "
                      f"{rec['state']} (rows={rec.get('rows')})", flush=True)
        try:
            ws._driver.quit()
        except Exception:
            pass
    return cells


# ---------------------------------------------------------------------------
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


def cell_summary(cell: dict) -> dict:
    ms = cell.get("matches", [])
    attempted = [m for m in ms if not m.get("skipped")]
    skipped = len(ms) - len(attempted)
    by_state = {}
    for m in attempted:
        st = m.get("state", "MISSING")
        by_state[st] = by_state.get(st, 0) + 1
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
        "schedule_rows": cell.get("schedule_rows"),
    }


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "debug_pages").mkdir(exist_ok=True)

    import soccerdata as sd  # noqa: F401  (garantisce versione installata)
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

    # 1) sonda HTTP pura
    probe = probe_http()
    env_info["http_probe"] = probe
    http_ok = any(a.get("missing_players") or a.get("allRegions") or a.get("seasons_select")
                  for a in probe.get("attempts", []))

    cells, extra = [], {}
    if http_ok:
        env_info["path"] = "http"
        cells, extra = http_sampling(args, probe, env_info)
        env_info["http_sampling_extra"] = extra
    else:
        # 2) characterizzazione del blocco via Selenium
        diag = diagnose_selenium(args.out_dir, quick=False)
        env_info["selenium_diagnose"] = diag
        sel_ok = any(a.get("allRegions") or a.get("seasons_select") or a.get("missing_players")
                     for a in diag.get("attempts", []))
        if sel_ok:
            env_info["path"] = "selenium"
            cells = selenium_sampling(args)
        else:
            env_info["path"] = "hard_blocked"
            env_info["hard_blocked"] = True
            for league in args.leagues:
                for season in args.seasons:
                    cells.append({"league": league, "season": season, "matches": [],
                                  "fatal": "HARD_BLOCK: Cloudflare blocca questo client/IP su ogni via (HTTP e browser)"})

    # ---- sintesi e referto -------------------------------------------------
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
    }
    (args.out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Campionamento WhoScored assenze pre-match — copertura perimetro Parte B",
        "",
        f"- generato: `{report['env']['generated_utc']}` (soccerdata `{report['env']['soccerdata']}`, python {report['env']['python']})",
        f"- stagioni: `{report['env']['seasons']}`; leghe: {len(report['env']['leagues'])}; partite per cella: {report['env']['matches_per_cell']}",
        f"- via usata: **{env_info.get('path')}**",
        "",
        "## Sonda HTTP (curl_cffi, no browser)",
        "",
        "| Pagina #tentativo | status | bytes | dati | bloccata |", "|---|---|---|---|---|",
    ]
    for att in probe.get("attempts", []):
        dati = ("missing-players" if att.get("missing_players")
                else "allRegions" if att.get("allRegions")
                else "seasons" if att.get("seasons_select") else "NESSUNO")
        lines.append(f"| {att.get('label')} #{att.get('attempt')} | {att.get('http_status')} | "
                     f"{att.get('bytes')} | {dati} | {att.get('blocked') or att.get('error','')} |")
    if not probe.get("available"):
        lines.append(f"\nSonda non disponibile: {probe.get('error')}")
    diag = env_info.get("selenium_diagnose")
    if diag:
        lines += ["", "## Diagnosi Selenium (uc=True)", f"Driver: `{diag.get('mode','?')}`", "",
                  "| Pagina #tentativo | titolo | bytes | dati | h1 |", "|---|---|---|---|---|"]
        for att in diag.get("attempts", []):
            dati = ("allRegions" if att.get("allRegions")
                    else "seasons" if att.get("seasons_select")
                    else "missing-players" if att.get("missing_players") else "NESSUNO")
            lines.append(f"| {att.get('label')} #{att.get('attempt')} | {str(att.get('title'))[:40]} | "
                         f"{att.get('source_len')} | {dati} | {str(att.get('h1') or att.get('error') or '')[:70]} |")
    if env_info.get("hard_blocked"):
        lines += ["", "**VERDETTO: HARD_BLOCK — il sito blocca questo client/IP su ogni via tentata "
                  "(HTTP con TLS impersonation e browser undetected-chromedriver). Le celle sotto non "
                  "riflettono la qualita' del dato ma l'inaccessibilita' della fonte da infrastruttura "
                  "datacenter.**"]
    lines += ["", "## Per lega", "", "| Lega | Tentate | Utilizzabili | Copertura | Stati |", "|---|---|---|---|---|"]
    for a in report["per_league"]:
        lines.append(f"| {a['key']} | {a['n']} | {a['usable']} | {a['coverage_pct']}% | {a['states']} |")
    lines += ["", "## Per stagione", "", "| Stagione | Tentate | Utilizzabili | Copertura | Stati |", "|---|---|---|---|---|"]
    for a in report["per_season"]:
        lines.append(f"| {a['key']} | {a['n']} | {a['usable']} | {a['coverage_pct']}% | {a['states']} |")
    lines += ["", "## Per cella", "", "| Lega | Stagione | n provate | saltate | stati | copertura | note |", "|---|---|---|---|---|---|---|"]
    for s in summaries:
        note = s["fatal"] or s["skip_reason"] or ""
        lines.append(f"| {s['league']} | {s['season']} | {s['n_sampled']} | {s['n_skipped_by_breaker']} | "
                     f"{s['states']} | {s['coverage_pct']}% | {note} |")
    lines += [
        "",
        "Stati: OK_ROWS = righe assenti presenti; OK_EMPTY_SECTION = sezione presente ma 0 assenti (dato valido);",
        "SECTION_MISSING = pagina letta senza sezione (buco); BLOCKED = anti-bot/Cloudflare; FAILED = eccezione;",
        "UNCERTAIN_NO_CACHE = senza cache ispezionabile; SKIPPED_* = non tentate dopo 3 esiti negativi consecutivi.",
    ]
    md = "\n".join(lines)
    (args.out_dir / "report.md").write_text(md, encoding="utf-8")
    print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
