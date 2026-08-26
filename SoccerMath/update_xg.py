"""
update_xg.py - Scarica gli xG da Understat automaticamente
Include retry esponenziale, rotazione header e fallback statistico automatico (per Ligue 1 e tutte le leghe).
"""

import base64
import codecs
import glob
import json
import os
import random
import re
import time
import pandas as pd
import requests

from config import (
    CURRENT_SEASON_START_YEAR,
    DATABASE_DIR,
    LEAGUES_CONFIG,
    LEAGUES_UNDERSTAT,
    TEAM_NAME_MAP,
    clean_name,
)

# Alias per retrocompatibilità
LEAGUES = LEAGUES_UNDERSTAT
NAME_MAP = TEAM_NAME_MAP

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]


def fetch_xg_understat(league_key, league_id, season, max_retries=3):
    """
    Scarica i dati xG da Understat con sistema di retry esponenziale e rotazione header.
    """
    url = f"https://understat.com/league/{league_id}/{season}"
    print(f"Fetching {url}...")

    for attempt in range(1, max_retries + 1):
        try:
            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
            }
            resp = requests.get(url, headers=headers, timeout=15)

            if resp.status_code == 404:
                print(f"  Stagione {season} non ancora disponibile su Understat per {league_key}.")
                return None
            if resp.status_code == 429 or resp.status_code == 403:
                print(f"  Understat rate-limit/blocco (HTTP {resp.status_code}), tentativo {attempt}/{max_retries}...")
                time.sleep(2 ** attempt)
                continue
            if resp.status_code != 200:
                print(f"  Errore HTTP {resp.status_code}, tentativo {attempt}/{max_retries}...")
                time.sleep(2 ** attempt)
                continue

            match = re.search(r'var teamsData = JSON.parse\(\'(.*?)\'\);', resp.text)
            if not match:
                print("  Struttura pagina Understat cambiata o dati non trovati.")
                return None

            encoded_data = match.group(1)
            decoded_bytes = base64.b64decode(encoded_data)
            decoded_str = codecs.escape_decode(decoded_bytes)[0].decode('utf-8')

            teams_data = json.loads(decoded_str)

            result = {}
            for team_id, team_info in teams_data.items():
                understat_name = team_info.get("title", "")
                cleaned = clean_name(understat_name)

                history = team_info.get("history", [])
                if not history:
                    continue

                total_xg = sum(float(m.get("xG", 0)) for m in history)
                total_xga = sum(float(m.get("xGA", 0)) for m in history)
                matches_played = len(history)

                result[cleaned] = {
                    "xG_avg": round(total_xg / matches_played, 3) if matches_played > 0 else 0,
                    "xGA_avg": round(total_xga / matches_played, 3) if matches_played > 0 else 0
                }

            return result

        except Exception as e:
            print(f"  Tentativo {attempt}/{max_retries} fallito per {league_key}: {e}")
            time.sleep(2 ** attempt)

    return None


def estimate_xg_from_csv_matches(league_key, info):
    """
    Fallback statistico: calcola xG stimati direttamente dalle partite storiche e live
    quando Understat non è raggiungibile o non ha dati per la lega.
    """
    print(f"  [FALLBACK STATISTICO] Calcolo xG da database CSV per {league_key}...")
    league_name = info.get("name", league_key)
    cfg = LEAGUES_CONFIG.get(league_name, {})
    prefix = cfg.get("db_prefix", "Ligue1")

    files = glob.glob(str(DATABASE_DIR / f"{prefix}*.csv"))
    if not files:
        return {}

    dfs = []
    for f in files:
        try:
            df_tmp = pd.read_csv(f, on_bad_lines="skip", low_memory=False)
            if not df_tmp.empty and "HomeTeam" in df_tmp.columns and "AwayTeam" in df_tmp.columns:
                dfs.append(df_tmp)
        except Exception:
            pass

    if not dfs:
        return {}

    df = pd.concat(dfs, ignore_index=True).dropna(subset=["HomeTeam", "AwayTeam", "FTR"])
    df["HomeClean"] = df["HomeTeam"].apply(clean_name)
    df["AwayClean"] = df["AwayTeam"].apply(clean_name)

    teams = sorted(list(set(df["HomeClean"]).union(set(df["AwayClean"]))))
    result = {}

    avg_h = df["FTHG"].dropna().astype(float).mean() if not df.empty else 1.45
    avg_a = df["FTAG"].dropna().astype(float).mean() if not df.empty else 1.15

    for t in teams:
        h_m = df[df["HomeClean"] == t]
        a_m = df[df["AwayClean"] == t]

        n_m = len(h_m) + len(a_m)
        if n_m == 0:
            continue

        # Calcolo gol fatti e subiti medi ponderati con volume tiri se disponibili
        gf_h = h_m["FTHG"].dropna().astype(float).sum()
        gf_a = a_m["FTAG"].dropna().astype(float).sum()
        ga_h = h_m["FTAG"].dropna().astype(float).sum()
        ga_a = a_m["FTHG"].dropna().astype(float).sum()

        xg_for = (gf_h + gf_a) / n_m
        xg_against = (ga_h + ga_a) / n_m

        # Se presenti statistiche tiri in porta (HST, AST), arricchisce la stima xG
        if "HST" in df.columns and "AST" in df.columns:
            try:
                sot_for = h_m["HST"].dropna().astype(float).sum() + a_m["AST"].dropna().astype(float).sum()
                sot_against = h_m["AST"].dropna().astype(float).sum() + a_m["HST"].dropna().astype(float).sum()
                if sot_for > 0 and sot_against > 0:
                    xg_shots_for = (sot_for / n_m) * 0.32
                    xg_shots_against = (sot_against / n_m) * 0.32
                    xg_for = 0.6 * xg_for + 0.4 * xg_shots_for
                    xg_against = 0.6 * xg_against + 0.4 * xg_shots_against
            except Exception:
                pass

        result[t] = {
            "goals_avg": round(float(xg_for), 3),
            "goals_against_avg": round(float(xg_against), 3),
            "note": "fallback_from_goals_not_real_xg"
        }

    return result


def update_league_xg(league_key, info):
    """
    Tenta di scaricare gli xG per la stagione configurata.
    Se non disponibili, tenta la stagione precedente o attiva il fallback statistico.
    """
    season = info.get("season", CURRENT_SEASON_START_YEAR)
    data = fetch_xg_understat(league_key, info["id"], season)

    # Fallback stagione precedente se stagione corrente vuota
    if (not data or len(data) < 10) and season > 2024:
        fallback_season = season - 1
        print(f"  Tentativo fallback stagione precedente: {fallback_season} per {league_key}...")
        fallback_data = fetch_xg_understat(league_key, info["id"], fallback_season)
        if fallback_data and len(fallback_data) >= 10:
            data = fallback_data

    # Fallback statistico dai file CSV del database
    if not data or len(data) < 10:
        data = estimate_xg_from_csv_matches(league_key, info)

    return data


def main():
    os.makedirs(DATABASE_DIR, exist_ok=True)
    successi = 0

    for league_key, info in LEAGUES_UNDERSTAT.items():
        data = update_league_xg(league_key, info)
        if data and len(data) >= 10:
            path = info.get("json_path", str(DATABASE_DIR / f"xg_{league_key}.json"))
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"  Salvato: {path} ({len(data)} squadre)")
            successi += 1
        else:
            print(f"  SKIP {league_key} - Dati insufficienti o non disponibili")

        time.sleep(2)

    print(f"\nCompletato: {successi}/{len(LEAGUES_UNDERSTAT)} campionati aggiornati")


if __name__ == "__main__":
    main()


