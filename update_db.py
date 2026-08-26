"""
update_db.py - Aggiorna i file *_Live.csv con i risultati piu' recenti
Eseguilo manualmente da terminale: python update_db.py
Oppure schedulalo con cron o GitHub Actions.
"""

import requests
import pandas as pd
import os
from datetime import datetime

from config import API_KEY_DATA  # oppure FOOTBALL_DATA_API_KEY

# Mapping campionati
CAMPIONATI = {
    "SerieA":       {"id": "SA",  "cols_home": "HomeTeam", "cols_away": "AwayTeam"},
    "Premier":      {"id": "PL",  "cols_home": "HomeTeam", "cols_away": "AwayTeam"},
    "LaLiga":       {"id": "PD",  "cols_home": "HomeTeam", "cols_away": "AwayTeam"},
    "Bundesliga":   {"id": "BL1", "cols_home": "HomeTeam", "cols_away": "AwayTeam"},
    "Ligue1":       {"id": "FL1", "cols_home": "HomeTeam", "cols_away": "AwayTeam"},
}

def clean_name(name):
    if not name:
        return ""
    n = str(name).strip()
    mapping = {
        "Manchester United": "Man United",
        "Manchester City": "Man City",
        "Tottenham Hotspur": "Tottenham",
        "Inter Milan": "Inter",
        "AC Milan": "Milan",
        "Atalanta BC": "Atalanta",
        "Hellas Verona": "Verona",
        "SS Lazio": "Lazio",
        "AS Roma": "Roma",
        "SSC Napoli": "Napoli",
        "Juventus FC": "Juventus",
        "Cagliari Calcio": "Cagliari",
        "Genoa CFC": "Genoa",
        "Udinese Calcio": "Udinese",
        "FC Internazionale Milano": "Inter",
        "ACF Fiorentina": "Fiorentina",
    }
    n = mapping.get(n, n)
    for r in ["FC", "BC", "AC ", "AS ", "SSC ", "SS ", "AFC ", "SV ", "1907", "Calcio", " CFC"]:
        n = n.replace(r, "")
    return n.strip()

def fetch_matches(comp_id):
    """Scarica tutte le partite finite della stagione corrente"""
    url = f"https://api.football-data.org/v4/competitions/{comp_id}/matches"
    headers = {"X-Auth-Token": API_KEY_DATA}
    params = {"status": "FINISHED"}
    
    try:
        r = requests.get(url, headers=headers, params=params)
        r.raise_for_status()
        return r.json().get("matches", [])
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
            if hthg > fthg: hthg = 0
            if htag > ftag: htag = 0
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
        except Exception as e:
            continue
    
    return pd.DataFrame(rows)

def update_live_csv(camp_name, comp_id):
    """Aggiorna il file Live.csv per un campionato"""
    live_path = f"./database/{camp_name}_Live.csv"
    
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
    
    for camp_name, info in CAMPIONATI.items():
        print(f"\n[{camp_name}]")
        update_live_csv(camp_name, info["id"])
    
    print("\n=== COMPLETATO ===")

if __name__ == "__main__":
    main()
