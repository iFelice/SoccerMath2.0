"""
update_db.py - Aggiorna i file *_Live.csv con i risultati piu' recenti
Eseguilo manualmente da terminale: python update_db.py
Oppure schedulalo con cron o GitHub Actions.
"""

import os
from datetime import datetime
import pandas as pd
import requests
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Importare config forza il caricamento del file .env
import config
from config import (
    CAMPIONATI_UPDATE_DB,
    DATABASE_DIR,
    FOOTBALL_DATA_API_KEY,
    clean_name,
)

# Per retrocompatibilità interna se importato altrove
CAMPIONATI = CAMPIONATI_UPDATE_DB
API_KEY_DATA = FOOTBALL_DATA_API_KEY


def fetch_matches(comp_id, season=None):
    api_key = config.FOOTBALL_DATA_API_KEY
    if not api_key:
        print("  [ATTENZIONE] FOOTBALL_DATA_API_KEY non configurata.")
        return []

    url = f"https://api.football-data.org/v4/competitions/{comp_id}/matches"
    headers = {"X-Auth-Token": api_key}
    params = {}
    if season:
        params["season"] = season

    try:
        r = requests.get(url, headers=headers, params=params, timeout=20)
        print("STATUS CODE:", r.status_code)
        if r.status_code != 200:
            print("RISPOSTA API:", r.text)
            return []
        matches = r.json().get("matches", [])
        print("DATI RICEVUTI:", len(matches))
        return matches
    except Exception as e:
        print(f"  Errore fetch {comp_id}: {e}")
        return []


def matches_to_df(matches):
    """Converte le partite nel formato CSV compatibile con il database"""
    rows = []
    for m in matches:
        try:
            date_str = m["utcDate"][:10]  # YYYY-MM-DD
            date_fmt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%Y")

            home = clean_name(m["homeTeam"].get("shortName") or m["homeTeam"].get("name", ""))
            away = clean_name(m["awayTeam"].get("shortName") or m["awayTeam"].get("name", ""))

            fthg = m["score"]["fullTime"]["home"]
            ftag = m["score"]["fullTime"]["away"]

            if fthg is None or ftag is None:
                continue

            winner = m["score"]["winner"]
            if winner == "HOME_TEAM":
                ftr = "H"
            elif winner == "AWAY_TEAM":
                ftr = "A"
            else:
                ftr = "D"

            hthg = m["score"].get("halfTime", {}).get("home", 0) or 0
            htag = m["score"].get("halfTime", {}).get("away", 0) or 0
            if hthg > fthg:
                hthg = 0
            if htag > ftag:
                htag = 0
            htr = "H" if hthg > htag else ("A" if htag > hthg else "D")

            matchday = m.get("matchday", 0)

            rows.append({
                "Date": date_fmt,
                "HomeTeam": home,
                "AwayTeam": away,
                "FTHG": int(fthg),
                "FTAG": int(ftag),
                "FTR": ftr,
                "HTHG": int(hthg),
                "HTAG": int(htag),
                "HTR": htr,
                "Matchday": matchday,
            })
        except Exception:
            continue

    return pd.DataFrame(rows)


def update_live_csv(camp_name, comp_id, live_path=None):
    """Aggiorna il file Live.csv per un campionato"""
    if not live_path:
        live_path = str(DATABASE_DIR / f"{camp_name}_Live.csv")

    print(f"  Fetching {camp_name} ({comp_id})...")
    matches = fetch_matches(comp_id)

    if not matches:
        print(f"  Nessuna partita trovata per {camp_name}")
        return

    df_new = matches_to_df(matches)
    if df_new.empty:
        print(f"  DataFrame vuoto per {camp_name}")
        return

    # Se esiste il file, merge evitando duplicati
    if os.path.exists(live_path):
        try:
            df_old = pd.read_csv(live_path, on_bad_lines="skip", low_memory=False)
            # Unisci e rimuovi duplicati basandosi su Date+HomeTeam+AwayTeam
            df_merged = pd.concat([df_old, df_new], ignore_index=True)
            df_merged = df_merged.drop_duplicates(subset=["Date", "HomeTeam", "AwayTeam"], keep="last")
            df_merged = df_merged.sort_values("Date")
            df_merged.to_csv(live_path, index=False)
            print(f"  Aggiornato: {live_path} ({len(df_new)} partite nuove, {len(df_merged)} totali)")
        except Exception as e:
            print(f"  Errore merge {camp_name}: {e}")
            df_new.to_csv(live_path, index=False)
    else:
        df_new.to_csv(live_path, index=False)
        print(f"  Creato: {live_path} ({len(df_new)} partite)")


def main():
    print(f"=== UPDATE DATABASE - {datetime.now().strftime('%d/%m/%Y %H:%M')} ===")

    for camp_key, info in CAMPIONATI_UPDATE_DB.items():
        print(f"\n[{info['name']}]")
        update_live_csv(camp_key, info["id"], info.get("live_path"))

    print("\n=== COMPLETATO ===")


if __name__ == "__main__":
    main()

