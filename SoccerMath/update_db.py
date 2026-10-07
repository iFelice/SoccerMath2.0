"""
update_db.py - Aggiorna i file *_Live.csv con i risultati piu' recenti
Eseguilo manualmente da terminale: python update_db.py
Oppure schedulalo con cron o GitHub Actions.
"""

import os
import sys
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
    get_current_season_start_year,
)
# Stessa igiene del rollover: nomi canonici, poi deduplica su Date+Home+Away.
from season_rollover import dedup_matches
from season_calendar import season_start_year_of
from season_rosters import save_league_roster, validate_current_rosters

# Per retrocompatibilità interna se importato altrove
CAMPIONATI = CAMPIONATI_UPDATE_DB
API_KEY_DATA = FOOTBALL_DATA_API_KEY

# Errori che impediscono davvero l'aggiornamento (chiave assente, HTTP != 200,
# rete). fetch_matches() risponde [] anche per un semplice "nessuna partita",
# quindi senza questo contatore un job con la secret rotta chiuderebbe con 0
# restando VERDE senza aggiornare nulla.
_FETCH_ERRORS = []


def fetch_matches(comp_id, season=None):
    api_key = config.FOOTBALL_DATA_API_KEY
    if not api_key:
        print("  [ATTENZIONE] FOOTBALL_DATA_API_KEY non configurata.")
        _FETCH_ERRORS.append(f"{comp_id}: FOOTBALL_DATA_API_KEY non configurata")
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
            _FETCH_ERRORS.append(f"{comp_id}: HTTP {r.status_code}")
            return []
        matches = r.json().get("matches", [])
        print("DATI RICEVUTI:", len(matches))
        return matches
    except Exception as e:
        print(f"  Errore fetch {comp_id}: {e}")
        _FETCH_ERRORS.append(f"{comp_id}: {e}")
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
        except Exception as e:
            logging.warning(f"Errore conversione match: {e}")
            continue

    return pd.DataFrame(rows)


def rosters_from_api_matches(matches):
    """R(lega, stagione) dal calendario API completo: ``{stagione: {squadre}}``.

    Va chiamata SULLE RISPOSTE GREZZE, prima di ``matches_to_df`` (che scarta
    le non giocate): la composizione del campionato si legge dal calendario,
    non dai risultati. Nomi canonici (``clean_name``, come i CSV) e stagione
    dal calcio d'inizio (``season_start_year_of``): le partite di agosto e
    quelle di maggio della stessa stagione finiscono nella stessa voce.
    """
    out = {}
    for m in matches or []:
        try:
            kickoff = datetime.fromisoformat(str(m.get("utcDate", "")).replace("Z", "+00:00"))
            stagione = season_start_year_of(kickoff)
        except Exception:
            continue
        try:
            home = clean_name(m["homeTeam"].get("shortName") or m["homeTeam"].get("name", ""))
            away = clean_name(m["awayTeam"].get("shortName") or m["awayTeam"].get("name", ""))
        except Exception:
            continue
        if not home or not away:
            continue
        out.setdefault(int(stagione), set()).update((home, away))
    return out


def save_rosters_from_matches(camp_name, matches):
    """Salva nel file versionato i roster visti nelle risposte API grezze."""
    rosters = rosters_from_api_matches(matches)
    if not rosters:
        return {}
    nome_esteso = CAMPIONATI_UPDATE_DB.get(camp_name, {}).get("name", camp_name)
    salvati = {}
    for stagione, squadre in sorted(rosters.items()):
        save_league_roster(nome_esteso, stagione, squadre)
        salvati[stagione] = len(squadre)
        print(f"  Roster {nome_esteso} {stagione}/{stagione + 1}: {len(squadre)} squadre salvate")
    return salvati


def update_live_csv(camp_name, comp_id, live_path=None):
    """Aggiorna il file Live.csv per un campionato"""
    if not live_path:
        live_path = str(DATABASE_DIR / f"{camp_name}_Live.csv")

    stagione_corrente = get_current_season_start_year()
    print(f"  Fetching {camp_name} ({comp_id}) stagione {stagione_corrente}...")
    matches = fetch_matches(comp_id, season=stagione_corrente)

    if not matches:
        print(f"  Nessuna partita trovata per {camp_name}")
        return

    # Roster PRIMA dello scarto delle non giocate: le partite senza risultato
    # restano escluse dai CSV come oggi, ma le squadre che compongono il
    # campionato si salvano comunque (servono al seed Elo fin dal pre-stagione).
    try:
        save_rosters_from_matches(camp_name, matches)
    except Exception as e:
        print(f"  [ATTENZIONE] roster non salvato per {camp_name}: {e}")
        _FETCH_ERRORS.append(f"{comp_id}: roster non salvato: {e}")

    df_new = matches_to_df(matches)
    if df_new.empty:
        print(f"  DataFrame vuoto per {camp_name}")
        return

    # Se esiste il file, merge evitando duplicati
    def _write(frame, path, nota):
        # "Date" e' una stringa gg/mm/aaaa: un ordinamento alfabetico la tratterebbe
        # come testo (01/02/2026 prima di 02/09/2025), mescolando le stagioni.
        ordine = pd.to_datetime(frame["Date"], dayfirst=True, errors="coerce")
        frame = frame.assign(_ord=ordine).sort_values("_ord", kind="stable").drop(columns="_ord")
        frame.to_csv(path, index=False)
        print(f"  {nota}: {os.path.basename(path)} ({len(frame)} partite, "
              f"{pd.to_datetime(frame['Date'], dayfirst=True, errors='coerce').min():%d/%m/%Y} -> "
              f"{pd.to_datetime(frame['Date'], dayfirst=True, errors='coerce').max():%d/%m/%Y})")

    if os.path.exists(live_path):
        try:
            df_old = pd.read_csv(live_path, on_bad_lines="skip", low_memory=False)
            # Unisci e rimuovi duplicati basandosi su Date+HomeTeam+AwayTeam.
            # I nomi vengono PRIMA normalizzati (clean_name): le righe scritte
            # quando l'API usava un'altra grafia ("Nottingham" vs "Nott'm
            # Forest") sono la stessa partita e non devono raddoppiare.
            df_merged = pd.concat([df_old, df_new], ignore_index=True)
            prima_merge = len(df_merged)
            df_merged = dedup_matches(df_merged)
            _write(df_merged, live_path, f"Aggiornato (+{len(df_merged) - len(df_old)} nuove, "
                                        f"{prima_merge - len(df_merged)} duplicati sovrascritti)")
        except Exception as e:
            print(f"  Errore merge {camp_name}: {e}")
            _FETCH_ERRORS.append(f"{comp_id}: errore merge su {live_path}: {e}")
            _write(df_new, live_path, "Ricreato")
    else:
        _write(df_new, live_path, "Creato")


def main():
    print(f"=== UPDATE DATABASE - {datetime.now().strftime('%d/%m/%Y %H:%M')} ===")

    for camp_key, info in CAMPIONATI_UPDATE_DB.items():
        print(f"\n[{info['name']}]")
        update_live_csv(camp_key, info["id"], info.get("live_path"))

    # Roster della stagione corrente: dopo il 15 luglio deve esserci ed essere
    # completo (20 squadre, 18 per Bundesliga e Ligue 1), altrimenti il job
    # fallisce con errore esplicito invece di girare senza seed Elo. Prima del
    # termine l'assenza e' ammessa (calendario non ancora pubblicato, stessa
    # logica della tolleranza pre-stagione della PR #27).
    try:
        for errore in validate_current_rosters():
            print(f"  [ERRORE roster] {errore}")
            _FETCH_ERRORS.append(errore)
    except Exception as e:
        print(f"  [ERRORE roster] validazione fallita: {e}")
        _FETCH_ERRORS.append(f"roster: validazione fallita: {e}")

    print("\n=== COMPLETATO ===")
    if _FETCH_ERRORS:
        print("\n[ERRORE] aggiornamenti non completati:")
        for errore in _FETCH_ERRORS:
            print(f"  - {errore}")
        sys.exit(1)


if __name__ == "__main__":
    main()

