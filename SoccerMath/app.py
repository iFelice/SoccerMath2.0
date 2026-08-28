import streamlit as st
import json
import pandas as pd
import numpy as np
import os
import requests
import glob
import re
import time
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
from scipy.stats import poisson
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

st.set_page_config(page_title="SoccerMath 2.0", layout="wide", initial_sidebar_state="expanded")

ITALY_TZ = ZoneInfo("Europe/Rome")

try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None

try:
    from groq import Groq
except ImportError:
    Groq = None

from scraper_xg import get_understat_xg, get_market_values
from models.elo_engine import get_current_elo, get_elo_leaderboard, predict_elo_probs, get_team_elo_history
from models.dixon_coles import get_dixon_coles_matrix, predict_dixon_coles_probs, get_dixon_coles_team_strengths
from models.backtest import run_backtest, compare_models_backtest, detect_value_bets

from config import (
    FOOTBALL_DATA_API_KEY, GROQ_API_KEY, ODDS_API_KEY, JSONBIN_API_KEY, JSONBIN_BIN_ID,
    PREDICTIONS_FILE, LEAGUES_CONFIG, LEAGUE_CODE_MAP, LEAGUE_PREFIX_MAP, CURRENT_SEASON, clean_name, DATABASE_DIR,
)

API_KEY_ODDS = ODDS_API_KEY
API_KEY_DATA = FOOTBALL_DATA_API_KEY

try:
    groq_client = Groq(api_key=GROQ_API_KEY) if (Groq and GROQ_API_KEY) else None
except Exception:
    groq_client = None

def format_date_italy(utc_date_str, fmt="%d/%m | %H:%M"):
    try:
        dt = datetime.fromisoformat(utc_date_str.replace("Z", "+00:00"))
        return dt.astimezone(ITALY_TZ).strftime(fmt)
    except Exception:
        return "Data N/D"

def calcola_stagione_calcolo(data_str):
    if not data_str or data_str == "Data N/D": 
        return "Sconosciuta"
    try:
        parts = data_str.split('/')
        if len(parts) >= 3:
            mese = int(parts[1])
            anno_str = parts[2].split(' ')[0].split('|')[0].strip()
            anno = int(anno_str)
        elif len(parts) == 2:
            # Formato "dd/mm | HH:MM" senza anno → usa anno corrente
            mese = int(parts[1].split('|')[0].strip())
            anno = datetime.now(ITALY_TZ).year
        else:
            return "Sconosciuta"
        
        if mese >= 8: 
            return f"{anno}/{anno+1}"
        elif mese <= 5: 
            return f"{anno-1}/{anno}"
        else: 
            return f"{anno-1}/{anno}"
    except: 
        pass
    return "Sconosciuta"

# --- CSS CUSTOM (solo elementi propri, NON sovrascrive il tema Streamlit) ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700;900&display=swap');
    html, body, [data-testid="stApp"] { font-family: 'Inter', sans-serif; }
    [data-testid="stSidebarContent"] { padding-left: 20px !important; padding-right: 10px !important; }
    .main .block-container {
        max-width: 100% !important; 
        padding-left: 0rem !important; 
        padding-right: 0rem !important; 
    }
     /* Header nascosto disabilitato: nasconde anche il toggle sidebar */
    /* [data-testid="stHeader"] { display: none !important; } */
    
    /* Banner personalizzato M4 */
    .safari-safe-banner { 
        width: 100%; 
        height: 0;
        padding-bottom: 35%;
        background-image: url('https://github.com/iFelice/SoccerMath2.0/blob/main/SoccerMath/images/Banner%20soccermath2.0.png?raw=true'); 
        background-size: 100% 100%;
        background-position: center center; 
        margin-top: 0px !important; 
        margin-bottom: 20px;
        margin-left: -1rem; 
        margin-right: -1rem;
    }

    .match-card { background-color: #ffffff; border-radius: 12px; padding: 3px; margin-bottom: 8px; border: 1px solid #e0e4e9; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }
    .team-name { font-size: 19px; font-weight: 800; color: #1a1d23; text-transform: uppercase; }
    .label-header { color: #0056b3; font-size: 15px !important; font-weight: 900; text-transform: uppercase; display: block; margin-bottom: 5px; border-bottom: 2px solid #e0e4e9; padding-bottom: 3px; }
    .match-date { font-size: 13px; font-weight: 800; color: #3b82f6 !important; display: block; margin-top: 5px; }
    .stat-container { background-color: #f8f9fa; border: 1px solid #e0e4e9; border-radius: 8px; padding: 10px; text-align: center; height: 100%; }
    .top-mix-row { background-color: #ffffff; border: 1px solid #e0e4e9; border-radius: 8px; padding: 15px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; }
    .match-result { font-size: 18px; font-weight: 800; color: #28a745; margin-top: 5px; display: block; }
</style>
""", unsafe_allow_html=True)

# --- REGISTRO PREDIZIONI ---
def load_predictions():
    if JSONBIN_API_KEY and JSONBIN_BIN_ID:
        try:
            r = requests.get(f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest", headers={"X-Master-Key": JSONBIN_API_KEY}, timeout=5)
            if r.status_code == 200:
                rec = r.json().get("record", {})
                if isinstance(rec, dict) and "data" in rec: return rec["data"]
                elif isinstance(rec, list): return rec
        except: pass
    if os.path.exists(PREDICTIONS_FILE):
        try:
            with open(PREDICTIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "data" in data: return data["data"]
                elif isinstance(data, list): return data
        except: return []
    return []

def save_predictions(preds):
    if JSONBIN_API_KEY and JSONBIN_BIN_ID:
        try: requests.put(f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}", json={"data": preds}, headers={"X-Master-Key": JSONBIN_API_KEY, "Content-Type": "application/json"}, timeout=5)
        except: pass
    os.makedirs("database", exist_ok=True)
    with open(PREDICTIONS_FILE, "w", encoding="utf-8") as f: json.dump({"data": preds}, f, ensure_ascii=False, indent=2)

def standardizza_mercato(testo):
    t = testo.lower()
    if "under 2.5" in t or "under2.5" in t: return "UNDER_2.5"
    if "over 2.5" in t or "over2.5" in t: return "OVER_2.5"
    if "gg" in t or "goal/goal" in t: return "GG"
    if "ng" in t or "no goal" in t: return "NG"
    if "pareggio" in t or "draw" in t or " x " in t: return "X"
    if "vittoria" in t or "vince" in t or "1 -" in t: return "1"
    if "2 -" in t: return "2"
    return "ALTRO"

def save_prediction_entry(match_id, h, a, camp, giornata, match_date, pronostico, top3, prob, ris_attesi):
    preds = load_predictions()
    if any(p.get("match_id") == match_id for p in preds): return
    stagione_reale = calcola_stagione_calcolo(match_date)
    preds.append({
        "match_id": match_id, "home": h, "away": a, "campionato": camp, "giornata": giornata,
        "data": match_date, "pronostico_sicuro": pronostico, "mercato_standard": standardizza_mercato(pronostico),
        "top3": top3, "prob_sicuro": prob, "risultati_attesi": ris_attesi,
        "risultato_reale": None, "esito": "⏳", "tipo": "Top Mix" if "Top Mix" in pronostico else "Analisi", 
        "stagione": stagione_reale, "salvato_il": datetime.now(ITALY_TZ).strftime("%d/%m/%Y %H:%M")
    })
    save_predictions(preds)

def aggiorna_risultati_reali(api_key):
    preds = load_predictions()
    aggiornate = 0
    # FIX: is not None invece di truthiness, così giornata=0 non viene esclusa
    pending = [p for p in preds if p.get("esito") in [None, "⏳"] and p.get("campionato") is not None and p.get("giornata") is not None]
    if not pending:
        return 0, 0
    from collections import defaultdict
    grouped = defaultdict(list)
    for p in pending:
        grouped[(p["campionato"], p["giornata"])].append(p)
    
    # --- FIX GIORNATA 0: chiamata diretta per match_id ---
    for camp in list(LEAGUES_CONFIG.keys()):
        zero_day_preds = grouped.pop((camp, 0), [])
        for p in zero_day_preds:
            m_id = p.get("match_id")
            if not m_id:
                continue
            try:
                r = requests.get(
                    f"https://api.football-data.org/v4/matches/{m_id}",
                    headers={"X-Auth-Token": api_key},
                    timeout=10
                )
                if r.status_code != 200:
                    continue
                match = r.json()
                gh = match["score"]["fullTime"]["home"]
                ga = match["score"]["fullTime"]["away"]
                if gh is None:
                    continue
                p["risultato_reale"] = f"{gh}-{ga}"
                tot = gh + ga
                m = p.get("mercato_standard", "").upper()
                if m == "UNDER_2.5":
                    p["esito"] = "✅" if tot < 3 else "❌"
                elif m == "OVER_2.5":
                    p["esito"] = "✅" if tot > 2 else "❌"
                elif m == "GG":
                    p["esito"] = "✅" if gh > 0 and ga > 0 else "❌"
                elif m == "NG":
                    p["esito"] = "✅" if gh == 0 or ga == 0 else "❌"
                elif m == "X":
                    p["esito"] = "✅" if gh == ga else "❌"
                elif m == "1":
                    p["esito"] = "✅" if gh > ga else "❌"
                elif m == "2":
                    p["esito"] = "✅" if ga > gh else "❌"
                else:
                    p["esito"] = "⏳"
                aggiornate += 1
            except:
                pass
    
    # --- Loop normale per giornata > 0 ---
    for (camp, giornata), camp_pending in grouped.items():
        comp = LEAGUE_CODE_MAP.get(camp)
        if not comp:
            continue
        try:
            r = requests.get(
                f"https://api.football-data.org/v4/competitions/{comp}/matches",
                headers={"X-Auth-Token": api_key},
                params={"matchday": giornata, "status": "FINISHED"},
                timeout=15
            )
            if r.status_code != 200:
                continue
            risultati_api = {m["id"]: m for m in r.json().get("matches", [])}
        except:
            continue
        for p in camp_pending:
            m_id = p.get("match_id")
            if not m_id or m_id not in risultati_api:
                p["esito"] = "⏳"
                continue
            match = risultati_api[m_id]
            gh = match["score"]["fullTime"]["home"]
            ga = match["score"]["fullTime"]["away"]
            if gh is None:
                continue
            p["risultato_reale"] = f"{gh}-{ga}"
            tot = gh + ga
            m = p.get("mercato_standard", "").upper()
            if m == "UNDER_2.5":
                p["esito"] = "✅" if tot < 3 else "❌"
            elif m == "OVER_2.5":
                p["esito"] = "✅" if tot > 2 else "❌"
            elif m == "GG":
                p["esito"] = "✅" if gh > 0 and ga > 0 else "❌"
            elif m == "NG":
                p["esito"] = "✅" if gh == 0 or ga == 0 else "❌"
            elif m == "X":
                p["esito"] = "✅" if gh == ga else "❌"
            elif m == "1":
                p["esito"] = "✅" if gh > ga else "❌"
            elif m == "2":
                p["esito"] = "✅" if ga > gh else "❌"
            else:
                p["esito"] = "⏳"
            aggiornate += 1
    
    if aggiornate > 0:
        save_predictions(preds)
    return aggiornate, len(pending)

# --- MOTORI LOGICI ---
@st.cache_data
def get_league_engine(camp_key):
    prefix = LEAGUE_PREFIX_MAP.get(camp_key)
    if not prefix: 
        return None
    dfs = []
    for f in sorted(glob.glob(str(DATABASE_DIR / f"{prefix}_20*.csv"))):
        try: 
            df_tmp = pd.read_csv(f, on_bad_lines='skip', low_memory=False)
            df_tmp['peso'] = 1.0
            dfs.append(df_tmp)
        except Exception as e: 
            logging.warning(f"Errore lettura CSV {f}: {e}")
    for f in glob.glob(str(DATABASE_DIR / f"{prefix}_Live.csv")):
        try: 
            df_tmp = pd.read_csv(f, on_bad_lines='skip', low_memory=False)
            df_tmp['peso'] = 1.0
            dfs.append(df_tmp)
        except Exception as e: 
            logging.warning(f"Errore lettura CSV {f}: {e}")
    for f in glob.glob(str(DATABASE_DIR / f"{prefix}.csv")):
        try: 
            df_tmp = pd.read_csv(f, on_bad_lines='skip', low_memory=False)
            df_tmp['peso'] = 1.0
            dfs.append(df_tmp)
        except Exception as e: 
            logging.warning(f"Errore lettura CSV {f}: {e}")
    if not dfs: 
        return None
    df = pd.concat(dfs, ignore_index=True)
    df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
    df = df.dropna(subset=['HomeTeam', 'AwayTeam', 'FTR']).sort_values('Date')
    df['HomeClean'] = df['HomeTeam'].apply(clean_name)
    df['AwayClean'] = df['AwayTeam'].apply(clean_name)
    if 'peso' not in df.columns: 
        df['peso'] = 1.0
    
    avg_h = np.average(df['FTHG'].dropna(), weights=df.loc[df['FTHG'].notna(), 'peso'])
    avg_a = np.average(df['FTAG'].dropna(), weights=df.loc[df['FTAG'].notna(), 'peso'])
    
    # --- FATTORI FORMA (ultime 5 partite) ---
    df_sorted = df.sort_values('Date')
    form_factors = {}
    for t in pd.concat([df['HomeClean'], df['AwayClean']]).unique():
        t_matches = df_sorted[(df_sorted['HomeClean']==t) | (df_sorted['AwayClean']==t)].tail(5)
        if len(t_matches) >= 3:
            gf = 0
            gt = 0
            for _, r in t_matches.iterrows():
                if r['HomeClean'] == t:
                    gf += r['FTHG']
                    gt += r['FTAG']
                else:
                    gf += r['FTAG']
                    gt += r['FTHG']
            avg_glob = (avg_h + avg_a) / 2
            form_factors[t] = {
                'att': max(0.85, min(1.15, (gf / len(t_matches)) / max(avg_glob, 0.5))),
                'def': max(0.85, min(1.15, (gt / len(t_matches)) / max(avg_glob, 0.5)))
            }
        else:
            form_factors[t] = {'att': 1.0, 'def': 1.0}
    
    xg_data = get_understat_xg(camp_key)
    mkt_values = get_market_values()
    league_xg = None
    league_xga = None
    if xg_data and len(xg_data) >= 10: 
        league_xg = np.mean([v['xG_avg'] for v in xg_data.values()])
        league_xga = np.mean([v['xGA_avg'] for v in xg_data.values()])
    
    stats = {}
    for t in pd.concat([df['HomeClean'], df['AwayClean']]).unique():
        h_h = df[df['HomeClean']==t]
        a_h = df[df['AwayClean']==t]
        if xg_data and t in xg_data and league_xg and league_xga: 
            att = xg_data[t]['xG_avg'] / league_xg
            defe = xg_data[t]['xGA_avg'] / league_xga
        else:
            att_h = np.average(h_h['FTHG'].dropna(), weights=h_h.loc[h_h['FTHG'].notna(), 'peso']) / avg_h if not h_h.empty else 1.0
            att_a = np.average(a_h['FTAG'].dropna(), weights=a_h.loc[a_h['FTAG'].notna(), 'peso']) / avg_a if not a_h.empty else 1.0
            def_h = np.average(h_h['FTAG'].dropna(), weights=h_h.loc[h_h['FTAG'].notna(), 'peso']) / avg_a if not h_h.empty else 1.0
            def_a = np.average(a_h['FTHG'].dropna(), weights=a_h.loc[a_h['FTHG'].notna(), 'peso']) / avg_h if not a_h.empty else 1.0
            att = (att_h + att_a) / 2
            defe = (def_h + def_a) / 2
        
        form = form_factors.get(t, {'att': 1.0, 'def': 1.0})
        att = att * form['att']
        defe = defe * form['def']
        
        val = mkt_values.get(t, 50)
        # Fattore mercato logaritmico: big (+20%), medie (+5%), piccole (-7%), neopromosse (-15%)
        mkt_factor = 1 + (np.log10(max(val, 10)) - 2.0) / 4
        mkt_factor = max(0.85, min(1.25, mkt_factor))
        stats[t] = {
            'att': att * mkt_factor,
            'def': defe / mkt_factor,
            'val': val
        }
    return stats, avg_h, avg_a, df

def get_full_poisson(h_e, a_e, max_goals=15):
    h_p = [poisson.pmf(i, h_e) for i in range(max_goals)]
    a_p = [poisson.pmf(i, a_e) for i in range(max_goals)]
    matrix = np.outer(h_p, a_p)
    def get_u(limit):
        return sum(matrix[i,j] for i in range(max_goals) for j in range(max_goals) if i+j < limit)
    return {
        "1": np.sum(np.tril(matrix, -1)),
        "X": np.sum(np.diag(matrix)),
        "2": np.sum(np.triu(matrix, 1)),
        "u25": get_u(2.5),
        "gg": (1-h_p[0])*(1-a_p[0])
    }

def calcola_segnali(risultati, infraset_giocate, infraset_programmate, stand, *args):
    mult_att, mult_def = 1.0, 1.0
    if infraset_giocate: mult_att -= 0.04; mult_def -= 0.05
    if infraset_programmate: mult_att -= 0.02
    return max(0.78, min(1.22, mult_att)), max(0.78, min(1.22, mult_def)), ""

def get_team_fd_id(team_name, camp_sel):
    for match in st.session_state.get("live_data", []):
        for team in [match["homeTeam"], match["awayTeam"]]:
            if clean_name(team.get("shortName", "") or team.get("name", "")).lower() == clean_name(team_name).lower(): return team["id"]
    return None

@st.cache_data(ttl=3600)
def get_ultimi_risultati_fd(team_id, camp_sel, n=5):
    comp = LEAGUE_CODE_MAP.get(camp_sel, "SA")
    try:
        r = requests.get(f"https://api.football-data.org/v4/teams/{team_id}/matches", headers={"X-Auth-Token": API_KEY_DATA}, params={"status": "FINISHED", "limit": 15, "competitions": comp})
        risultati = []
        for match in r.json().get("matches", [])[-n:]:
            gh, ga, winner = match["score"]["fullTime"]["home"], match["score"]["fullTime"]["away"], match["score"]["winner"]
            is_home = match["homeTeam"]["id"] == team_id
            esito = "V" if (is_home and winner == "HOME_TEAM") or (not is_home and winner == "AWAY_TEAM") else ("X" if winner == "DRAW" else "P")
            risultati.append(f"{match['homeTeam'].get('shortName','?')} {gh}-{ga} {match['awayTeam'].get('shortName','?')} ({esito})")
        return risultati
    except: return []

@st.cache_data(ttl=3600)
def get_infraset_data(team_id, camp_code, match_date_str, now_utc_str):
    match_date = datetime.fromisoformat(match_date_str); window_start = match_date - timedelta(days=7); giocate, programmate = [], []
    try:
        r = requests.get(f"https://api.football-data.org/v4/teams/{team_id}/matches", headers={"X-Auth-Token": API_KEY_DATA}, params={"status": "FINISHED", "limit": 10})
        for m in r.json().get("matches", []):
            if m.get("competition", {}).get("code", "") == camp_code: continue
            try:
                dt = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
                if window_start <= dt < match_date: giocate.append(f"{dt.strftime('%d/%m')} {m.get('competition',{}).get('name','')}: {m['score']['fullTime'].get('home')}-{m['score']['fullTime'].get('away')}")
            except: pass
    except: pass
    return giocate, programmate

def get_contesto_partita(h, a, camp_sel):
    h_id, a_id = get_team_fd_id(h, camp_sel), get_team_fd_id(a, camp_sel)
    contesto = {"h_risultati": get_ultimi_risultati_fd(h_id, camp_sel) if h_id else [], "a_risultati": get_ultimi_risultati_fd(a_id, camp_sel) if a_id else [], "h_infortunati": [], "a_infortunati": [], "h_infraset": [], "a_infraset": [], "h_infraset_prog": [], "a_infraset_prog": []}
    camp_code = LEAGUE_CODE_MAP.get(camp_sel, "SA"); match_date = datetime.now(timezone.utc); match_id_found = None
    for mx in st.session_state.get("live_data", []):
        if clean_name(h) in clean_name(mx["homeTeam"].get("shortName", "") or mx["homeTeam"].get("name", "")):
            try: match_date = datetime.fromisoformat(mx["utcDate"].replace("Z", "+00:00")); match_id_found = mx["id"]
            except: pass
            break
    if h_id: contesto["h_infraset"], contesto["h_infraset_prog"] = get_infraset_data(h_id, camp_code, match_date.isoformat(), datetime.now(timezone.utc).isoformat())
    if a_id: contesto["a_infraset"], contesto["a_infraset_prog"] = get_infraset_data(a_id, camp_code, match_date.isoformat(), datetime.now(timezone.utc).isoformat())
    return contesto, match_id_found

@st.cache_data(ttl=1800, show_spinner="Calcolando Top 10...")
def fetch_and_calc_top_mix():
    all_preds, missing = [], []
    for league in LEAGUES_CONFIG.keys():
        engine = get_league_engine(league)
        if not engine: missing.append(league); continue
        team_stats, avg_h, avg_a, _ = engine
        try:
            r = requests.get(f"https://api.football-data.org/v4/competitions/{LEAGUE_CODE_MAP[league]}/matches", headers={'X-Auth-Token': API_KEY_DATA}, params={"status": "TIMED,SCHEDULED"})
            if r.status_code != 200: continue
            matches = [m for m in r.json().get('matches', []) if m['matchday'] == sorted(set([m['matchday'] for m in r.json().get('matches', [])]))[0]]
        except: continue
        for match in matches:
            h = match['homeTeam'].get('shortName') or match['homeTeam'].get('name', '?')
            a = match['awayTeam'].get('shortName') or match['awayTeam'].get('name', '?')
            h_s = team_stats.get(clean_name(h), {"att": 1.0, "def": 1.0})
            a_s = team_stats.get(clean_name(a), {"att": 1.0, "def": 1.0})
            
            # Poisson
            m_poisson = get_full_poisson(h_s["att"] * a_s["def"] * avg_h, a_s["att"] * h_s["def"] * avg_a)
            mercati = {
                f"Vittoria {h}": m_poisson["1"], "Pareggio": m_poisson["X"], f"Vittoria {a}": m_poisson["2"],
                "Over 2.5": 1 - m_poisson["u25"], "Under 2.5": m_poisson["u25"],
                "GG": m_poisson["gg"], "NG": 1 - m_poisson["gg"]
            }
            best_mkt = max(mercati, key=mercati.get)
            poisson_prob = mercati[best_mkt]
            
            # Elo agreement (solo per 1X2)
            elo_prob = poisson_prob  # fallback
            try:
                elo_p = predict_elo_probs(h, a, league)
                if best_mkt == f"Vittoria {h}":
                    elo_prob = elo_p["1"]
                elif best_mkt == f"Vittoria {a}":
                    elo_prob = elo_p["2"]
                elif best_mkt == "Pareggio":
                    elo_prob = elo_p["X"]
            except:
                pass
            
            # Confidence = media tra Poisson ed Elo (se Elo è vicino, conferma; se lontano, penalizza)
            # Per mercati O/U e GG dove Elo non esiste, usiamo solo Poisson ma richiediamo soglia più alta
            if best_mkt in ["Over 2.5", "Under 2.5", "GG", "NG"]:
                confidence = poisson_prob
                min_conf = 0.60
            else:
                # Per 1X2: media armonica pesata (Elo ha peso 40%, Poisson 60%)
                confidence = 0.6 * poisson_prob + 0.4 * elo_prob
                min_conf = 0.55
            
            # Filtro qualità: confidence minima e nessun disaccordo estremo
            if confidence >= min_conf and abs(poisson_prob - elo_prob) < 0.25:
                all_preds.append({
                    "league": league, "giornata": match['matchday'],
                    "home": h, "away": a, "match_id": match.get("id"),
                    "utcDate": match['utcDate'], "market": best_mkt,
                    "prob": confidence, "prob_val": round(confidence * 100, 1),
                    "poisson": round(poisson_prob * 100, 1),
                    "elo": round(elo_prob * 100, 1)
                })
        time.sleep(6.5)
    return sorted(all_preds, key=lambda x: x['prob'], reverse=True)[:10], missing

def analisi_rapida_giornata(matches, team_stats, avg_h, avg_a, camp_sel, classifica_sess, giornata_n):
    salvate = 0
    for match in matches:
        try:
            h, a = match['homeTeam'].get('shortName') or match['homeTeam'].get('name', '?'), match['awayTeam'].get('shortName') or match['awayTeam'].get('name', '?')
            m_id = match.get('id')
            if not m_id: continue
            match_date_str = format_date_italy(match['utcDate'], "%d/%m/%Y %H:%M")
            h_s, a_s = team_stats.get(clean_name(h), {"att": 1.0, "def": 1.0}), team_stats.get(clean_name(a), {"att": 1.0, "def": 1.0})
            m = get_full_poisson(h_s["att"] * a_s["def"] * avg_h, a_s["att"] * h_s["def"] * avg_a)
            mercati = {f"Vittoria {h}": m["1"], "Pareggio": m["X"], f"Vittoria {a}": m["2"], "Over 2.5": 1 - m["u25"], "Under 2.5": m["u25"], "GG": m["gg"], "NG": 1 - m["gg"]}
            best_mkt = max(mercati, key=mercati.get)
            pron = f"{best_mkt} - {mercati[best_mkt]:.0%} - Poisson Auto"
            top3 = [f"{i+1}. {k} - {v:.0%}" for i, (k, v) in enumerate(sorted([(k, v) for k, v in mercati.items() if k != best_mkt], key=lambda x: -x[1])[:3])]
            save_prediction_entry(m_id, h, a, camp_sel, giornata_n, match_date_str, pron, top3, round(mercati[best_mkt]*100, 1), "")
            salvate += 1
        except: pass
    return salvate

@st.dialog("STRATEGIC ANALYSIS", width="large")
def show_details(h, a, m, camp_sel="Serie A", giornata_n=0):
    match_id, match_date_str = None, ""
    for mx in st.session_state.get("live_data", []):
        if clean_name(h) in clean_name(mx["homeTeam"].get("shortName", "") or mx["homeTeam"].get("name","")):
            match_id = mx.get("id"); match_date_str = format_date_italy(mx["utcDate"], "%d/%m/%Y %H:%M"); break
    mercato_top = max({f"Vittoria {h}": m['1'], "Pareggio": m['X'], f"Vittoria {a}": m['2'], "Over 2.5": 1-m['u25'], "Under 2.5": m['u25']}, key=lambda k: {f"Vittoria {h}": m['1'], "Pareggio": m['X'], f"Vittoria {a}": m['2'], "Over 2.5": 1-m['u25'], "Under 2.5": m['u25']}[k])
    prob_top = {f"Vittoria {h}": m['1'], "Pareggio": m['X'], f"Vittoria {a}": m['2'], "Over 2.5": 1-m['u25'], "Under 2.5": m['u25']}[mercato_top]

    if not groq_client:
        st.error("⚠️ Billy (Groq) non configurato. Devi creare il file .env come spiegato!")
        if match_id: save_prediction_entry(match_id, h, a, camp_sel, giornata_n, match_date_str, f"{mercato_top} - Fallback", [], round(prob_top*100, 1), "")
        return

    with st.spinner("Billy sta analizzando..."):
        try:
            contesto, _ = get_contesto_partita(h, a, camp_sel)
            h_mult_att, h_mult_def, _ = calcola_segnali(contesto.get("h_risultati", []), contesto.get("h_infraset", []), contesto.get("h_infraset_prog", []), st.session_state.get("classifica", {}).get(clean_name(h), {}))
            a_mult_att, a_mult_def, _ = calcola_segnali(contesto.get("a_risultati", []), contesto.get("a_infraset", []), contesto.get("a_infraset_prog", []), st.session_state.get("classifica", {}).get(clean_name(a), {}))
            engine_data = get_league_engine(camp_sel)
            if engine_data:
                ts, ah, aa, _ = engine_data
                hs, as_ = ts.get(clean_name(h), {"att": 1.0, "def": 1.0}), ts.get(clean_name(a), {"att": 1.0, "def": 1.0})
                h_exp, a_exp = hs["att"] * h_mult_att * as_["def"] * a_mult_def * ah, as_["att"] * a_mult_att * hs["def"] * h_mult_def * aa
            else: h_exp, a_exp = 1.3, 1.1
            m_adj = get_full_poisson(h_exp, a_exp)
            p1, pX, p2 = m_adj['1'], m_adj['X'], m_adj['2']
            
            prompt = f"""Sei Billy Walters. Analizza {h} vs {a}. POISSON(1:{p1:.1%} X:{pX:.1%} 2:{p2:.1%}). RISPONDI COSI': PRONOSTICO SICURO: "[mercato] - [%] - [motivo]" """
            try: res = groq_client.chat.completions.create(model="openai/gpt-oss-120b", messages=[{"role": "user", "content": prompt}], max_tokens=500)
            except: res = groq_client.chat.completions.create(model="qwen/qwen3.6-27b", messages=[{"role": "user", "content": prompt}], max_tokens=500)
            
            testo = res.choices[0].message.content.replace("**", "").replace("*", "")
            # Mostra SEMPRE il testo di Billy
            st.markdown(f"<div style='color:#1a1a1a; font-size:15px; line-height:1.6;'>{testo}</div>", unsafe_allow_html=True)
            
            # Cerca di salvare nel registro in modo flessibile
            pronostico_trovato = ""
            for riga in testo.split("\n"):
                rs = riga.strip()
                if "PRONOSTICO SICURO" in rs.upper():
                    pronostico_trovato = rs.replace("PRONOSTICO SICURO:", "").replace("PRONOSTICO SICURO :", "").strip()
                    break
            
            # --- VALUE BET CALCULATOR ---
            st.divider()
            st.subheader("💰 Value Bet Check")
            col_q, col_ev = st.columns(2)
            with col_q:
                quota_book = st.number_input("Quota Bookmaker", min_value=1.01, max_value=50.0, value=2.00, step=0.05, key=f"qb_{match_id}")
            prob_modello = max(p1, pX, p2)  # probabilità del pronostico principale
            ev = (prob_modello * quota_book) - 1
            with col_ev:
                st.metric("EV (Expected Value)", f"{ev:.2%}")
                if ev > 0.05:
                    st.success("✅ VALUE BET FORTE")
                elif ev > 0:
                    st.info("🟡 Margine positivo")
                else:
                    st.error("❌ Nessun valore")
            
            if match_id and pronostico_trovato:
                save_prediction_entry(match_id, h, a, camp_sel, giornata_n, match_date_str, pronostico_trovato, [], round(prob_modello*100, 1), "")
                st.success("✅ Salvato Billy!")
        except Exception as e:
            st.error(f"Errore AI: {e}")
            if match_id: save_prediction_entry(match_id, h, a, camp_sel, giornata_n, match_date_str, f"{mercato_top} - Errore AI", [], round(prob_top*100, 1), "")

# Banner
st.markdown("""<div class="safari-safe-banner"></div>""", unsafe_allow_html=True)

# Avviso prominente se manca l'API Key
if not API_KEY_DATA:
    st.error("🔴 **FOOTBALL_DATA_API_KEY mancante!** Vai su Streamlit Cloud → **App Settings → Secrets** e aggiungi:\n```toml\nFOOTBALL_DATA_API_KEY = \"tua-chiave\"\n```")

# --- SIDEBAR ---
with st.sidebar:
    st.title("🎩 Billy Walters Chat")
    with st.expander("🔧 Diagnostica", expanded=False):
        if not Groq: st.error("Lib 'groq' non installata (pip3 install groq)")
        elif not GROQ_API_KEY: st.error("GROQ_API_KEY mancante nel file .env!")
        else: st.success("✅ Billy OK")
        
        if not API_KEY_DATA: st.error("FOOTBALL_DATA_API_KEY mancante!")
        else: st.success("✅ API Data OK")

    camp_sel = st.selectbox("CAMPIONATO", list(LEAGUES_CONFIG.keys()))
    camp_cached = st.session_state.get("live_camp", None)
    has_data = bool("live_data" in st.session_state and st.session_state.get("live_data") and camp_cached == camp_sel)
    col_s1, col_s2 = st.columns([2, 1])
    with col_s1: do_sync = st.button("🔄 SINCRONIZZA", disabled=has_data)
    with col_s2: do_refresh = st.button("↺ Refresh")
    
    if do_sync or do_refresh:
        if not API_KEY_DATA:
            st.error("⚠️ Impossibile sincronizzare: API Key Football-Data mancante. Configurala nei Secrets.")
        else:
            with st.spinner("Scaricando dati da Football-Data..."):
                try:
                    resp = requests.get(
                        f"https://api.football-data.org/v4/competitions/{LEAGUE_CODE_MAP[camp_sel]}/matches",
                        headers={'X-Auth-Token': API_KEY_DATA},
                        timeout=15
                    )
                    if resp.status_code == 200:
                        st.session_state.live_data = resp.json().get('matches', [])
                        st.session_state.live_camp = camp_sel
                        st.success(f"✅ {len(st.session_state.live_data)} partite caricate!")
                    elif resp.status_code == 401:
                        st.error("🔴 Errore 401: API Key non valida o scaduta. Verifica su football-data.org.")
                    elif resp.status_code == 429:
                        st.error("🟠 Errore 429: troppe richieste. Aspetta 1 minuto e riprova.")
                    else:
                        st.error(f"Errore API ({resp.status_code}): {resp.text[:200]}")
                except requests.exceptions.Timeout:
                    st.error("⏱️ Timeout: il server Football-Data non risponde. Riprova tra qualche istante.")
                except Exception as e:
                    st.error(f"Errore imprevisto: {e}")
            try:
                stand_resp = requests.get(
                    f"https://api.football-data.org/v4/competitions/{LEAGUE_CODE_MAP[camp_sel]}/standings",
                    headers={"X-Auth-Token": API_KEY_DATA},
                    timeout=15
                )
                if stand_resp.status_code == 200:
                    st.session_state.classifica = {
                        clean_name(r["team"].get("shortName") or r["team"].get("name")): {
                            "pos": r["position"], "punti": r["points"], "pg": r["playedGames"],
                            "gf": r["goalsFor"], "gs": r["goalsAgainst"]
                        }
                        for r in stand_resp.json().get("standings", [])[0].get("table", [])
                    }
            except Exception:
                pass
        
    if "live_data" in st.session_state and st.session_state.live_data:
        giornate = sorted(list(set([int(m.get('matchday', 0)) for m in st.session_state.live_data])))
        default_idx = 0
        now_utc = datetime.now(timezone.utc)
        for i, g in enumerate(giornate):
            for m in st.session_state.live_data:
                if m['matchday'] == g:
                    try:
                        if datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")) > now_utc: default_idx = i; break
                    except: pass
            if default_idx != 0: break
        g_sel = st.selectbox("GIORNATA", giornate, index=default_idx)
    else: g_sel = None

engine = get_league_engine(camp_sel)
tab1, tab2, tab3, tab4, tab5 = st.tabs(["🏟️ PARTITE", "🌟 TOP MIX", "⚡ ELO RATING", "📊 BACKTEST", "📒 REGISTRO"])

with tab1:
    if 'live_data' in st.session_state and st.session_state.live_data and g_sel is not None and engine:
        team_stats, avg_h, avg_a, _ = engine
        matches = [m for m in st.session_state.live_data if int(m.get('matchday', 0)) == int(g_sel)]
        col_title, col_btn = st.columns([4, 1])
        with col_title: st.subheader(f"🏟️ {camp_sel.upper()} - GIORNATA {g_sel}")
        with col_btn:
            if st.button("⚡ Analisi Rapida"):
                with st.spinner("Calcolo..."): n = analisi_rapida_giornata(matches, team_stats, avg_h, avg_a, camp_sel, st.session_state.get("classifica", {}), g_sel)
                st.success(f"✅ {n} salvate!")
        for idx, match in enumerate(matches):
            h_api, a_api = match['homeTeam'].get('shortName') or match['homeTeam'].get('name', '?'), match['awayTeam'].get('shortName') or match['awayTeam'].get('name', '?')
            dt = format_date_italy(match['utcDate'])
            m = get_full_poisson((team_stats.get(clean_name(h_api), {'att': 1.0, 'def': 1.0})['att'] * team_stats.get(clean_name(a_api), {'att': 1.0, 'def': 1.0})['def'] * avg_h), (team_stats.get(clean_name(a_api), {'att': 1.0, 'def': 1.0})['att'] * team_stats.get(clean_name(h_api), {'att': 1.0, 'def': 1.0})['def'] * avg_a))
            with st.container():
                st.markdown('<div class="match-card">', unsafe_allow_html=True)
                c_h, c1, c3, c5, c6 = st.columns([1.5, 1.2, 0.8, 1, 0.4])
                with c_h: st.markdown(f"<span class='team-name'>{h_api}<br>{a_api}</span><br><span class='match-date'>🕒 {dt}</span>", unsafe_allow_html=True)
                with c1: st.markdown(f"<div class='stat-container'><span class='label-header'>1X2</span><div style='display:flex; justify-content:space-around'><div>1<br><b>{m['1']:.0%}</b></div><div>X<br><b>{m['X']:.0%}</b></div><div>2<br><b>{m['2']:.0%}</b></div></div></div>", unsafe_allow_html=True)
                with c3: st.markdown(f"<div class='stat-container'><span class='label-header'>U/O 2.5</span><b>{m['u25']:.0%}</b> / <b>{(1-m['u25']):.0%}</b></div>", unsafe_allow_html=True)
                with c5: st.markdown(f"<div class='stat-container'><span class='label-header'>GG/NG</span><b>{m['gg']:.0%}</b> / <b>{(1-m['gg']):.0%}</b></div>", unsafe_allow_html=True)
                with c6:
                    if match.get('status') == "FINISHED":
                        gh = match["score"]["fullTime"]["home"]
                        ga = match["score"]["fullTime"]["away"]
                        st.markdown(f"<div style='text-align:center; color:#28a745; font-weight:800; font-size:18px;'>🏁<br>{gh}-{ga}</div>", unsafe_allow_html=True)
                    else:
                        st.write("<br>", unsafe_allow_html=True)
                        st.button("🔍", key=f"ex_{camp_sel}_{g_sel}_{idx}", on_click=show_details, args=(h_api, a_api, m, camp_sel, g_sel))
                st.markdown("</div>", unsafe_allow_html=True)
    else:
        if not engine:
            st.warning("⚠️ Database locale non trovato. Verifica che i file CSV siano presenti in `database/`.")
        elif not API_KEY_DATA:
            st.info("🔑 Inserisci l'API Key Football-Data nei Secrets e premi SINCRONIZZA.")
        else:
            st.info("👋 Premi SINCRONIZZA per caricare le partite del campionato selezionato.")

with tab2:
    if st.button("🚀 Calcola Top 10", type="primary"):
        top_10, missing = fetch_and_calc_top_mix()
        if missing: st.warning(f"⚠️ Mancanti: {', '.join(missing)}")
        for i, p in enumerate(top_10):
            dt = format_date_italy(p['utcDate'], "%d/%m %H:%M")
            st.markdown(f"<div class='top-mix-row'><div><b>#{i+1}</b> - {p['home']} vs {p['away']}<br><small>🏆 {p['league']} | 🕒 {dt}</small></div><div style='text-align: right; color: #28a745; font-weight: 800;'>{p['market']}<br><small>{p['prob_val']}%</small></div></div>", unsafe_allow_html=True)
            if p.get('match_id'): save_prediction_entry(p['match_id'], p['home'], p['away'], p['league'], p['giornata'], format_date_italy(p['utcDate'], "%d/%m/%Y %H:%M"), f"{p['market']} - Top Mix", [], p['prob_val'], "")
        st.success("✅ Top Mix salvati!")

with tab3:
    st.subheader(f"⚡ Elo - {camp_sel}")
    elo_df = get_elo_leaderboard(camp_sel)
    if not elo_df.empty:
        st.dataframe(elo_df, use_container_width=True, height=400)
        st.divider(); teams = sorted(elo_df["Squadra"].tolist())
        c1, c2 = st.columns(2)
        with c1: sh = st.selectbox("Casa", teams, key="sh")
        with c2: sa = st.selectbox("Trasf.", teams, index=1 if len(teams)>1 else 0, key="sa")
        if sh and sa:
            sp = predict_elo_probs(sh, sa, camp_sel)
            st.markdown(f"<div style='background:#30363d; height:24px; display:flex; overflow:hidden; margin-top:10px; border-radius:8px;'><div style='width:{sp['1']*100}%; background:#28a745; text-align:center; color:white; font-size:12px; font-weight:700; line-height:24px;'>1: {sp['1']:.0%}</div><div style='width:{sp['X']*100}%; background:#ffc107; text-align:center; color:black; font-size:12px; font-weight:700; line-height:24px;'>X: {sp['X']:.0%}</div><div style='width:{sp['2']*100}%; background:#dc3545; text-align:center; color:white; font-size:12px; font-weight:700; line-height:24px;'>2: {sp['2']:.0%}</div></div>", unsafe_allow_html=True)

with tab4:
    st.subheader("📊 Backtest Engine")
    st.info("🛠️ Il modulo Backtest è temporaneamente disabilitato. Il file `models/backtest.py` richiede un aggiornamento interno per gestire i nuovi nomi dei file CSV storici (es. SerieA_2023.csv). Le altre funzioni (Pronostici, Elo, Registro) sono pienamente operative.")
    # Ho rimosso il bottone per evitare che l'app crashi su un file che non possiamo modificare ora

# --- TAB 5 REGISTRO ---
with tab5:
    st.subheader("📒 Registro Predizioni & Tracking")
    if st.button("🔄 Aggiorna Risultati", type="primary"):
        if API_KEY_DATA:
            with st.spinner("Controllando..."): agg, tot = aggiorna_risultati_reali(API_KEY_DATA)
            st.success(f"✅ Aggiornate {agg} partite!" if agg > 0 else f"ℹ️ Nessun nuovo risultato ({tot} in attesa).")
        else: st.error("API Key mancante!")
        
    preds = load_predictions()
    if not preds: st.warning("Nessuna predizione.")
    else:
        df_preds = pd.DataFrame(preds)
        df_preds['stagione'] = df_preds['data'].apply(calcola_stagione_calcolo)

        f_col1, f_col2, f_col3 = st.columns(3)
        with f_col1:
            camp_options = ["Tutti"] + list(LEAGUES_CONFIG.keys())
            default_camp_idx = camp_options.index(camp_sel) if camp_sel in camp_options else 0
            filter_camp = st.selectbox("Campionato", camp_options, index=default_camp_idx)
        with f_col2: filter_status = st.selectbox("Esito", ["Tutti", "In Attesa (⏳)", "Vinte (✅)", "Perse (❌)"])
        with f_col3: 
            stagioni_reali = sorted(df_preds['stagione'].unique().tolist(), reverse=True)
            filter_stagione = st.selectbox("Stagione", ["Tutti"] + stagioni_reali)
            
        if filter_camp != "Tutti": df_preds = df_preds[df_preds["campionato"] == filter_camp]
        if filter_status == "In Attesa (⏳)": df_preds = df_preds[df_preds["esito"].isin(["⏳", None])]
        elif filter_status == "Vinte (✅)": df_preds = df_preds[df_preds["esito"] == "✅"]
        elif filter_status == "Perse (❌)": df_preds = df_preds[df_preds["esito"] == "❌"]
        if filter_stagione != "Tutti": df_preds = df_preds[df_preds["stagione"] == filter_stagione]
        
        tot, vinte, perse = len(df_preds), len(df_preds[df_preds["esito"] == "✅"]), len(df_preds[df_preds["esito"] == "❌"])
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Totale", tot)
        s2.metric("✅ Vinte", vinte, delta=f"{(vinte/tot*100) if tot > 0 else 0:.1f}%")
        s3.metric("❌ Perse", perse)
        s4.metric("⏳ Attesa", len(df_preds[df_preds["esito"] == "⏳"]))
        
        # Fix visivo: converte i vecchi 'None' in '⏳' e i risultati vuoti in '-'
        df_display = df_preds.fillna({"esito": "⏳", "risultato_reale": "-"})
        
        st.dataframe(df_display[["data", "stagione", "campionato", "home", "away", "mercato_standard", "prob_sicuro", "risultato_reale", "esito"]].sort_values(by="data", ascending=False), use_container_width=True, height=500)
