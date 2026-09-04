import streamlit as st
import json
import pandas as pd
import numpy as np
import os
import math
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
    LEAGUE_HOME_ADVANTAGE, get_league_db_files,
)
from prediction_registry import (
    EXCLUDED_FROM_CURRENT_STATS_FIELD,
    MODEL_VERSION_CURRENT,
    MODEL_VERSION_FIELD,
    MODEL_LABEL_CURRENT,
    MODEL_LABEL_PRE_FIX,
    PRE_FIX_TOOLTIP,
    CURRENT_MODEL_TOOLTIP,
    new_prediction_metadata,
    model_label,
    stats_current_model,
    stats_historical,
    stats_all,
    backup_prediction_file,
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
    if not data_str or data_str == "Data N/D" or not isinstance(data_str, str):
        # isinstance: le righe del registro senza campo 'data' arrivano come NaN
        return "Sconosciuta"
    try:
        if "-" in data_str and "/" not in data_str:
            dt = datetime.fromisoformat(data_str.replace("Z", "+00:00"))
            anno, mese = dt.year, dt.month
        else:
            parts = data_str.split('/')
            if len(parts) >= 3:
                mese = int(parts[1])
                anno_str = parts[2].split(' ')[0].split('|')[0].strip()
                anno = int(anno_str)
            elif len(parts) == 2:
                mese_str = parts[1].split('|')[0].split(' ')[0].strip()
                mese = int(mese_str)
                anno = datetime.now(ITALY_TZ).year
            else:
                return "Sconosciuta"
        
        if mese >= 8: 
            return f"{anno}/{anno+1}"
        else: 
            return f"{anno-1}/{anno}"
    except Exception as e:
        logging.warning(f"Errore calcolo stagione per '{data_str}': {e}")
        return "Sconosciuta"

# --- CSS CUSTOM (solo elementi propri, NON sovrascrive il tema Streamlit) ---
# IMPORTANTE: le versioni recenti di Streamlit NON espongono a livello globale
# le variabili CSS del tema (--st-* o i vecchi --background-color/--text-color).
# Affidarsi a quelle variabili faceva cadere le card sul fallback bianco #ffffff
# in DARK mode (caselle bianche con testo bianco). Usiamo quindi variabili
# PROPRIE (--sm-*) e una media query sul tema di sistema: Streamlit segue già
# il sistema grazie a [theme.dark] nel config.toml, quindi i due restano allineati.
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700;900&display=swap');
    html, body, [data-testid="stApp"] { font-family: 'Inter', sans-serif; }
    [data-testid="stSidebarContent"] { padding-left: 20px !important; padding-right: 10px !important; }

    /* Variabili tema custom: valori chiari di default, scuri in dark mode */
    :root {
        --sm-card-bg: #ffffff;
        --sm-card-text: #1a1d23;
        --sm-card-border: rgba(128,128,128,0.2);
        --sm-accent: #0056b3;
        --sm-muted-bg: #f8f9fa;
    }
    @media (prefers-color-scheme: dark) {
        :root {
            --sm-card-bg: #262730;
            --sm-card-text: #fafafa;
            --sm-card-border: rgba(255,255,255,0.12);
            --sm-accent: #66a3ff;
            --sm-muted-bg: #1c1e26;
        }
    }

    /* Banner: aspect-ratio evita margini negativi pericolosi */
    .safari-safe-banner { 
        width: 100%; 
        aspect-ratio: 1056 / 2496;
        max-height: 600px;
        background-image: url('https://github.com/iFelice/SoccerMath2.0/blob/main/SoccerMath/images/Banner%20soccermath2.0.png?raw=true'); 
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center center; 
        margin-bottom: 5px;
    }

    .match-card { 
        background-color: var(--sm-card-bg); 
        color: var(--sm-card-text);
        border-radius: 12px; 
        padding: 3px; 
        margin-bottom: 8px; 
        border: 1px solid var(--sm-card-border); 
        box-shadow: 0 2px 8px rgba(0,0,0,0.05); 
    }
    .team-name { font-size: 19px; font-weight: 800; color: var(--sm-card-text); text-transform: uppercase; }
    .label-header { color: var(--sm-accent); font-size: 15px !important; font-weight: 900; text-transform: uppercase; display: block; margin-bottom: 5px; border-bottom: 2px solid var(--sm-card-border); padding-bottom: 3px; }
    .match-date { font-size: 13px; font-weight: 800; color: var(--sm-accent) !important; display: block; margin-top: 5px; }
    .stat-container { background-color: var(--sm-muted-bg); color: var(--sm-card-text); border: 1px solid var(--sm-card-border); border-radius: 8px; padding: 10px; text-align: center; height: 100%; }
    .top-mix-row { background-color: var(--sm-card-bg); color: var(--sm-card-text); border: 1px solid var(--sm-card-border); border-radius: 8px; padding: 15px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; }
    .match-result { font-size: 18px; font-weight: 800; color: #28a745; margin-top: 5px; display: block; }
</style>
""", unsafe_allow_html=True)

# --- REGISTRO PREDIZIONI ---
def load_predictions():
    # Fonte remota primaria se configurata; in fallback il file locale.
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
    # Backup prima di ogni scrittura: non si sovrascrive mai un registro
    # esistente senza copia integrale. Il remoto viene aggiornato SOLO dopo
    # che la scrittura locale e' riuscita.
    backup_prediction_file(PREDICTIONS_FILE)
    os.makedirs(DATABASE_DIR, exist_ok=True)
    with open(PREDICTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"data": preds}, f, ensure_ascii=False, indent=2)
    if JSONBIN_API_KEY and JSONBIN_BIN_ID:
        try:
            requests.put(
                f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}",
                json={"data": preds},
                headers={"X-Master-Key": JSONBIN_API_KEY, "Content-Type": "application/json"},
                timeout=5,
            )
        except: pass

def standardizza_mercato(testo, home=None, away=None):
    if not testo:
        return "ALTRO"
    t = testo.lower()
    
    # Under/Over (con o senza spazio)
    if re.search(r'\bunder\s*1\.5\b', t): return "UNDER_1.5"
    if re.search(r'\bover\s*1\.5\b', t): return "OVER_1.5"
    if re.search(r'\bunder\s*2\.5\b', t): return "UNDER_2.5"
    if re.search(r'\bover\s*2\.5\b', t): return "OVER_2.5"
    if re.search(r'\bunder\s*3\.5\b', t): return "UNDER_3.5"
    if re.search(r'\bover\s*3\.5\b', t): return "OVER_3.5"
    
    # Doppia Chance
    if re.search(r'\b1x\b|\b1/x\b|\bhome/draw\b', t): return "1X"
    if re.search(r'\bx2\b|\bx/2\b|\bdraw/away\b', t): return "X2"
    if re.search(r'\b12\b|\b1/2\b|\bhome/away\b', t): return "12"
    
    # Goal/No Goal (\b = word boundary, evita "sugg" → "gg")
    if re.search(r'\bgg\b|\bgoal/goal\b|\bboth teams to score\b|\bbtts\b', t): return "GG"
    if re.search(r'\bng\b|\bno goal\b|\bno goals\b', t): return "NG"
    
    # Pareggio
    if re.search(r'\bpareggio\b|\bdraw\b|\bmatch nul\b', t): return "X"
    
    # Vittoria casa (1) o trasferta (2) — disambigua con i nomi squadra
    if home and away:
        h_clean = clean_name(home).lower()
        a_clean = clean_name(away).lower()
        
        if h_clean in t and re.search(r'\bvittoria\b|\bvince\b|\bwin\b|\b1\b', t):
            return "1"
        if a_clean in t and re.search(r'\bvittoria\b|\bvince\b|\bwin\b|\b2\b', t):
            return "2"
    
    # Fallback esplicito per pattern numerici
    if re.search(r'\b1\b.*\b(casa|home|casalinga)\b|\b(casa|home|casalinga)\b.*\b1\b', t): return "1"
    if re.search(r'\b2\b.*\b(trasferta|away)\b|\b(trasferta|away)\b.*\b2\b', t): return "2"
    if re.search(r'^\s*1\b', t) and not re.search(r'\b2\b', t): return "1"
    if re.search(r'^\s*2\b', t) and not re.search(r'\b1\b', t): return "2"
    if re.search(r'^\s*x\b', t): return "X"
    
    return "ALTRO"

def save_prediction_entry(match_id, h, a, camp, giornata, match_date, pronostico, top3, prob, ris_attesi):
    preds = load_predictions()
    if any(p.get("match_id") == match_id for p in preds): return
    stagione_reale = calcola_stagione_calcolo(match_date)
    metadata = new_prediction_metadata()
    preds.append({
        "match_id": match_id, "home": h, "away": a, "campionato": camp, "giornata": giornata,
        "data": match_date, "pronostico_sicuro": pronostico, "mercato_standard": standardizza_mercato(pronostico, h, a),
        "top3": top3, "prob_sicuro": prob, "risultati_attesi": ris_attesi,
        "risultato_reale": None, "esito": "⏳", "tipo": "Top Mix" if "Top Mix" in pronostico else "Analisi", 
        "stagione": stagione_reale, "salvato_il": datetime.now(ITALY_TZ).strftime("%d/%m/%Y %H:%M"),
        MODEL_VERSION_FIELD: metadata[MODEL_VERSION_FIELD],
        EXCLUDED_FROM_CURRENT_STATS_FIELD: metadata[EXCLUDED_FROM_CURRENT_STATS_FIELD],
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
                if m == "UNDER_1.5": p["esito"] = "✅" if tot < 2 else "❌"
                elif m == "OVER_1.5": p["esito"] = "✅" if tot > 1 else "❌"
                elif m == "UNDER_2.5": p["esito"] = "✅" if tot < 3 else "❌"
                elif m == "OVER_2.5": p["esito"] = "✅" if tot > 2 else "❌"
                elif m == "UNDER_3.5": p["esito"] = "✅" if tot < 4 else "❌"
                elif m == "OVER_3.5": p["esito"] = "✅" if tot > 3 else "❌"
                elif m == "1X": p["esito"] = "✅" if gh >= ga else "❌"
                elif m == "X2": p["esito"] = "✅" if ga >= gh else "❌"
                elif m == "12": p["esito"] = "✅" if gh != ga else "❌"
                elif m == "GG": p["esito"] = "✅" if gh > 0 and ga > 0 else "❌"
                elif m == "NG": p["esito"] = "✅" if gh == 0 or ga == 0 else "❌"
                elif m == "X": p["esito"] = "✅" if gh == ga else "❌"
                elif m == "1": p["esito"] = "✅" if gh > ga else "❌"
                elif m == "2": p["esito"] = "✅" if ga > gh else "❌"
                else: p["esito"] = "⏳"
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

# Peso del prior "media di lega" (shrinkage empirico-bayesiano), espresso in
# partite equivalenti: con n partite osservate la stima del rapporto
# attacco/difesa e' (n*r + PRIOR_MATCHES) / (n + PRIOR_MATCHES).
# Fix NG ~99.8%: senza questo prior una neopromossa con 0 gol in 2 partite
# di DB otteneva ratio 0.0 ESATTO -> lambda 0 -> clip exp(-6) -> NG 99.8%.
PRIOR_MATCHES = 6.0


def _shrunk_ratio(observed, expected, n_matches, prior=PRIOR_MATCHES):
    """Rapporto observed/expected con shrinkage verso 1.0 (media di lega).

    Dati assenti (n<=0), atteso nullo o totali non finiti -> 1.0: il modello
    degrada in modo controllato sulla media di lega invece che verso 0.
    Con prior=6: 0 gol in 2 partite -> 0.75; a 38 partite il prior pesa ~14%.
    """
    try:
        n_matches = float(n_matches)
        observed, expected = float(observed), float(expected)
    except (TypeError, ValueError):
        return 1.0
    if not (np.isfinite(observed) and np.isfinite(expected) and np.isfinite(n_matches)):
        return 1.0
    if n_matches <= 0 or expected <= 0:
        return 1.0
    r = observed / expected
    if not np.isfinite(r):
        return 1.0
    return (n_matches * r + prior) / (n_matches + prior)


@st.cache_data(ttl=3600)
def get_league_engine(camp_key):
    # I file (storici + base + live) vengono risolti in config: solo il pattern
    # "{prefix}.csv" lasciava fuori, ad esempio, PremierLeague.csv.
    files = get_league_db_files(camp_key)
    if not files:
        return None
    dfs = []
    for f in files:
        try:
            df_tmp = pd.read_csv(f, on_bad_lines='warn', low_memory=False)
            dfs.append(df_tmp)
        except Exception as e:
            logging.warning(f"Errore lettura CSV {f}: {e}")
    if not dfs:
        return None
    df = pd.concat(dfs, ignore_index=True).copy()
    if 'peso' not in df.columns:
        df['peso'] = 1.0
    df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
    df = df.dropna(subset=['HomeTeam', 'AwayTeam', 'FTR']).sort_values('Date', kind='stable')
    df['HomeClean'] = df['HomeTeam'].apply(clean_name)
    df['AwayClean'] = df['AwayTeam'].apply(clean_name)
    df = df.drop_duplicates(subset=['Date', 'HomeClean', 'AwayClean'], keep='last').reset_index(drop=True).copy()
    
    avg_h = np.average(df['FTHG'].dropna(), weights=df.loc[df['FTHG'].notna(), 'peso'])
    avg_a = np.average(df['FTAG'].dropna(), weights=df.loc[df['FTAG'].notna(), 'peso'])
    
    # --- FATTORI FORMA (ultime 5 partite) ---
    df_sorted = df.sort_values('Date', kind='stable')
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
        # Medie di lega su soli valori finiti e positivi; range di sanita'
        # 0.5-5.0: nessun campionato reale sta fuori da questo intervallo
        # (media xG per squadra/partita ~1.2-1.6 nelle top 5), quindi valori
        # fuori range = file xG corrotto -> si ignora la fonte xG.
        _lx = [v['xG_avg'] for v in xg_data.values()
               if isinstance(v, dict) and isinstance(v.get('xG_avg'), (int, float))
               and np.isfinite(v['xG_avg']) and v['xG_avg'] > 0]
        _lxa = [v['xGA_avg'] for v in xg_data.values()
                if isinstance(v, dict) and isinstance(v.get('xGA_avg'), (int, float))
                and np.isfinite(v['xGA_avg']) and v['xGA_avg'] > 0]
        if len(_lx) >= 10 and len(_lxa) >= 10:
            _m_xg, _m_xga = float(np.mean(_lx)), float(np.mean(_lxa))
            if 0.5 < _m_xg < 5.0 and 0.5 < _m_xga < 5.0:
                league_xg, league_xga = _m_xg, _m_xga

    # --- PRIOR EMPIRICO PER CAMPIONI PICCOLI (fix NG ~99.8%) ---
    # Il rapporto attacco/difesa usa lo shrinkage verso la media di lega
    # definito a livello di modulo (_shrunk_ratio, PRIOR_MATCHES): senza
    # prior una neopromossa con 0 gol in 2 partite di DB otteneva ratio
    # 0.0 ESATTO -> lambda pura 0 -> clip exp(-6) = 0.002479 -> NG 99.8%
    # (v. audit/test_ng_regression.py e audit/repro_ng_anomaly.py).

    stats = {}
    for t in pd.concat([df['HomeClean'], df['AwayClean']]).unique():
        h_h = df[df['HomeClean']==t]
        a_h = df[df['AwayClean']==t]
        # --- Testa dati xG: validita' + shrinkage se noto il campione ---
        xg_rec = xg_data.get(t) if xg_data else None
        use_xg = False
        if (xg_rec is not None and league_xg and league_xga
                and isinstance(xg_rec, dict)):
            xg_v = xg_rec.get('xG_avg')
            xga_v = xg_rec.get('xGA_avg')
            n_xg = xg_rec.get('matches')  # aggiunto da update_xg.py col fix NG
            try:
                xg_v = float(xg_v); xga_v = float(xga_v)
                val_ok = (np.isfinite(xg_v) and np.isfinite(xga_v)
                          and xg_v >= 0 and xga_v >= 0)
            except (TypeError, ValueError):
                val_ok = False
                n_xg = None
            n_ok = (isinstance(n_xg, (int, float)) and not isinstance(n_xg, bool)
                    and np.isfinite(float(n_xg)) and float(n_xg) > 0)
            # Senza 'matches' (file xG vecchi) uno xG_avg==0 non e' distinguibile
            # da un dato rotto: si va di fallback sui gol. Con 'matches' noto lo
            # shrinkage gestisce anche uno 0.0 autentico (0.00 xG in n partite).
            if val_ok and (n_ok or (xg_v > 0 and xga_v > 0)):
                if n_ok:
                    att = _shrunk_ratio(xg_v, league_xg, n_xg)
                    defe = _shrunk_ratio(xga_v, league_xga, n_xg)
                else:
                    att = xg_v / league_xg
                    defe = xga_v / league_xga
                use_xg = True
        if not use_xg:
            # --- Fallback gol dal DB: rapporto pooled con shrinkage ---
            # Gol osservati e gol attesi da una squadra "media di lega"
            # (media casa in casa, media trasferta in trasferta), aggregati
            # su entrambi i ruoli: un solo ratio stabile invece della media
            # di ratio casa/trasferta separati (che con 1-2 partite e' rumore).
            h_gf = h_h['FTHG'].dropna(); a_gf = a_h['FTAG'].dropna()
            h_ga = h_h['FTAG'].dropna(); a_ga = a_h['FTHG'].dropna()
            n_played = len(h_gf) + len(a_gf)
            gf = float(h_gf.sum() + a_gf.sum())
            ga = float(h_ga.sum() + a_ga.sum())
            exp_gf = float(avg_h * len(h_gf) + avg_a * len(a_gf))
            exp_ga = float(avg_a * len(h_ga) + avg_h * len(a_ga))
            att = _shrunk_ratio(gf, exp_gf, n_played)
            defe = _shrunk_ratio(ga, exp_ga, n_played)

        # --- Sanitizzazione finale: nessun ratio non-finito o <= 0 puo'
        # raggiungere le lambda (att/def == 0 => lambda 0 => NG 99.8%).
        if not (np.isfinite(att) and att > 0):
            att = 1.0
        if not (np.isfinite(defe) and defe > 0):
            defe = 1.0
        
        # Baseline pura di lungo periodo (xG/gol storici puliti), SENZA forma:
        # alimenta la testa Totali (O/U2.5 e GG/NG). Evidenza empirica su 5
        # campionati (40 confronti, vedi audit/diagnose_form_totali.py e
        # audit/results/form_totali_diagnosis.md): rimuovere la forma a 5 gare
        # dai totali abbassa il Brier O/U2.5 da 0.2488 a 0.2401 e GG/NG da
        # 0.2584 a 0.2496.
        att0_pure = att
        def0_pure = defe

        # La forma resta SOLO nella testa 1X2 (att/def): att0/def0 continuano a
        # includerla perche' fanno da ancora (S = base_h + base_a) alla
        # normalizzazione dei lambda 1X2 in _two_heads_from_lambdas.
        form = form_factors.get(t, {'att': 1.0, 'def': 1.0})
        att = att * form['att']
        defe = defe * form['def']
        att0 = att
        def0 = defe

        val = mkt_values.get(t, 50)
        # Fattore mercato logaritmico: big (+20%), medie (+5%), piccole (-7%), neopromosse (-15%)
        mkt_factor = 1 + (np.log10(max(val, 10)) - 2.0) / 4
        mkt_factor = max(0.85, min(1.25, mkt_factor))
        # Architettura a due teste: conservo sia i rapporti BASE (senza valore
        # di mercato, M=1) sia quelli aggiustati dal fattore mercato. La testa
        # 1X2 usera' i lambda con mercato normalizzati alla somma base; la testa
        # O/U2.5 e GG/NG usera' i lambda puri (att0_pure/def0_pure), senza
        # distorsione di forma o mercato.
        stats[t] = {
            'att': att * mkt_factor,
            'def': defe / mkt_factor,
            'att0': att0,         # base con forma, M=1 (ancora S della testa 1X2)
            'def0': def0,         # base con forma, M=1 (ancora S della testa 1X2)
            'att0_pure': att0_pure,  # baseline pura, M=1, senza forma: testa Totali
            'def0_pure': def0_pure,  # baseline pura, M=1, senza forma: testa Totali
            'val': val
        }
    return stats, avg_h, avg_a, df

@st.cache_data(ttl=86400, show_spinner="Backtest storico in corso...")
def run_historical_backtest(camp_key, min_train=30, step=5, max_test=300):
    """
    Backtest walk-forward sul database storico locale.
    Per ogni finestra temporale usa SOLO le partite precedenti (no leakage) per
    stimare i parametri Poisson e la griglia Elo, poi predice le partite successive.
    Le partite testate sono le ULTIME max_test (max_test=None = tutte), così il
    giudizio sui modelli riguarda la forma recente e non stagioni di 3 anni fa.
    Dixon-Coles è escluso volutamente per velocità.
    """
    prefix = LEAGUE_PREFIX_MAP.get(camp_key)
    if not prefix:
        return pd.DataFrame()

    # Teniamo solo le colonne necessarie: i CSV football-data ne hanno >100 e
    # le maschere booleane per squadra costerebbero una copia gigante del frame.
    required_cols = ['Date', 'HomeTeam', 'AwayTeam', 'FTR', 'FTHG', 'FTAG']
    dfs = []
    for f in get_league_db_files(camp_key):
        try:
            df_tmp = pd.read_csv(f, on_bad_lines='warn', low_memory=False)
            if not all(c in df_tmp.columns for c in required_cols):
                continue
            dfs.append(df_tmp[required_cols].copy())
        except Exception:
            pass
    if not dfs:
        return pd.DataFrame()

    df = pd.concat(dfs, ignore_index=True)
    df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
    df['FTHG'] = pd.to_numeric(df['FTHG'], errors='coerce')
    df['FTAG'] = pd.to_numeric(df['FTAG'], errors='coerce')
    # sort stabile: a pari data (tipico di una giornata) l'ordine resta quello dei file
    df = df.dropna(subset=['Date', 'HomeTeam', 'AwayTeam', 'FTR', 'FTHG', 'FTAG']).sort_values('Date', kind='stable')
    df['HomeClean'] = df['HomeTeam'].apply(clean_name)
    df['AwayClean'] = df['AwayTeam'].apply(clean_name)
    df = df[(df['HomeClean'] != "") & (df['AwayClean'] != "")]
    df = df.drop_duplicates(subset=['Date', 'HomeClean', 'AwayClean'], keep='last').reset_index(drop=True)

    n = len(df)
    if n < min_train + 10:
        return pd.DataFrame()

    # Finestra out-of-sample: le partite più recenti. Con min_train=30, step=5 e
    # max_test=300 si valutano ~60 riaddestramenti sugli ultimi 300 incontri.
    start = min(n, max(min_train, n - max_test)) if max_test else min_train

    results = []
    mapping_ftr = {'H': '1', 'D': 'X', 'A': '2'}
    home_adv = LEAGUE_HOME_ADVANTAGE.get(camp_key, 65.0)

    for i in range(start, n, step):
        train = df.iloc[:i]
        test = df.iloc[i:min(i+step, n)]

        # Guardie minime: medie gol di lega non devono poter andare a zero
        avg_h = max(float(train['FTHG'].mean()), 0.1)
        avg_a = max(float(train['FTAG'].mean()), 0.1)

        # Forze attacco/difesa: groupby invece di una maschera per squadra
        # (equivalente a mean() su un frame senza NaN, ma ~40x piu' veloce)
        home_gf = train.groupby('HomeClean')['FTHG'].mean()
        home_ga = train.groupby('HomeClean')['FTAG'].mean()
        away_gf = train.groupby('AwayClean')['FTAG'].mean()
        away_ga = train.groupby('AwayClean')['FTHG'].mean()
        stats = {}
        for t in pd.concat([train['HomeClean'], train['AwayClean']]).unique():
            att_h = home_gf[t] if t in home_gf.index else avg_h
            def_h = home_ga[t] if t in home_ga.index else avg_a
            att_a = away_gf[t] if t in away_gf.index else avg_a
            def_a = away_ga[t] if t in away_ga.index else avg_h
            stats[t] = {'att': (att_h / avg_h + att_a / avg_a) / 2,
                        'def': (def_h / avg_a + def_a / avg_h) / 2}

        # Elo ricostruito in ordine cronologico sul solo train
        elo_ratings = {}
        for row in train.itertuples(index=False):
            h, a = row.HomeClean, row.AwayClean
            ftr = str(row.FTR).strip().upper()
            r_h = elo_ratings.get(h, 1500.0)
            r_a = elo_ratings.get(a, 1500.0)
            dr = r_h + home_adv - r_a
            e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
            s_h = 1.0 if ftr == 'H' else (0.0 if ftr == 'A' else 0.5)
            k = 24.0
            elo_ratings[h] = r_h + k * (s_h - e_h)
            elo_ratings[a] = r_a + k * ((1-s_h) - (1-e_h))

        for row in test.itertuples(index=False):
            h, a = row.HomeClean, row.AwayClean
            fthg, ftag = int(row.FTHG), int(row.FTAG)
            real = mapping_ftr.get(str(row.FTR).strip().upper(), 'X')

            hs = stats.get(h, {'att': 1.0, 'def': 1.0})
            as_ = stats.get(a, {'att': 1.0, 'def': 1.0})
            m_p = get_full_poisson(hs['att'] * as_['def'] * avg_h, as_['att'] * hs['def'] * avg_a)
            pois_pred = max([('1', m_p['1']), ('X', m_p['X']), ('2', m_p['2'])], key=lambda x: x[1])[0]

            r_h = elo_ratings.get(h, 1500.0)
            r_a = elo_ratings.get(a, 1500.0)
            dr = r_h + home_adv - r_a
            e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
            p_draw = 0.27 * math.exp(-((dr / 320.0) ** 2))
            p_draw = max(0.06, min(0.34, p_draw))
            p_home = (1.0 - p_draw) * e_h
            p_away = (1.0 - p_draw) * (1.0 - e_h)
            elo_pred = max([('1', p_home), ('X', p_draw), ('2', p_away)], key=lambda x: x[1])[0]

            tot = fthg + ftag
            u25_real = 'UNDER_2.5' if tot < 3 else 'OVER_2.5'
            gg_real = 'GG' if fthg > 0 and ftag > 0 else 'NG'

            results.append({
                'date': row.Date, 'home': h, 'away': a, 'real_1x2': real,
                'poisson_1x2': pois_pred, 'poisson_ok': pois_pred == real,
                'elo_1x2': elo_pred, 'elo_ok': elo_pred == real,
                'real_uo': u25_real, 'poisson_uo': 'UNDER_2.5' if m_p['u25'] > 0.5 else 'OVER_2.5',
                'poisson_uo_ok': ('UNDER_2.5' if m_p['u25'] > 0.5 else 'OVER_2.5') == u25_real,
                'real_gg': gg_real, 'poisson_gg': 'GG' if m_p['gg'] > 0.5 else 'NG',
                'poisson_gg_ok': ('GG' if m_p['gg'] > 0.5 else 'NG') == gg_real,
            })

    return pd.DataFrame(results)


def _clip_lambda(x):
    """Clip dei lambda al range validato in audit/ (log-spazio [-6, 3]).

    Input non finiti (NaN/+inf/-inf): un lambda non finito segnala un bug a
    monte (statistiche corrotte). Il valore neutro 1.0 (tasso di gol medio
    di lega, prior a massima entropia per un tasso Poisson) evita che NaN
    produca silenziosamente il clip SUPERIORE: con i confronti float Python
    max(0.002479, min(20.0855, nan)) restituiva 20.0855, cioe' una squadra
    "infinitamente" prolifica. La pipeline a monte (get_league_engine)
    sanitizza comunque le statistiche, quindi questo e' un ultimo argine.
    """
    x = float(x)
    if not math.isfinite(x):
        return 1.0
    return max(0.002479, min(20.0855, x))  # [exp(-6), exp(3)]


def _poisson_market(h_e, a_e, max_goals=15):
    """Matrice congiunta Poisson su un singolo paio di lambda (clip interno).
    Ritorna probabilita' 1/X/2, Under 1.5/2.5/3.5 e GG."""
    h_e = _clip_lambda(h_e)
    a_e = _clip_lambda(a_e)
    h_p = [poisson.pmf(i, h_e) for i in range(max_goals)]
    a_p = [poisson.pmf(i, a_e) for i in range(max_goals)]
    matrix = np.outer(h_p, a_p)

    def get_u(limit):
        return float(sum(matrix[i, j] for i in range(max_goals) for j in range(max_goals)
                         if i + j < limit))

    return {
        "1": float(np.sum(np.tril(matrix, -1))),
        "X": float(np.sum(np.diag(matrix))),
        "2": float(np.sum(np.triu(matrix, 1))),
        "u15": get_u(1.5),
        "u25": get_u(2.5),
        "u35": get_u(3.5),
        "gg": float((1 - h_p[0]) * (1 - a_p[0])),
    }


def get_full_poisson(h_e, a_e, max_goals=15):
    """Poisson a testa singola (clip interno). Mantenuto per retro-compatibilita':
    backtest storico e' un confronto baseline senza mercato e resta invariato."""
    return _poisson_market(h_e, a_e, max_goals)


def _two_heads_from_lambdas(base_h, base_a, mkt_h, mkt_a,
                            base_pure_h=None, base_pure_a=None, max_goals=15):
    """Architettura a due teste su lambda raw (senza clip).

    Testa 1X2: i lambda con mercato vengono normalizzati vincolando la loro somma
    alla somma attesa BASE S = base_h + base_a, mantenendone la proporzione
    relativa (lambda_H* = S * mkt_H / (mkt_H + mkt_A)). Poi clip e matrice.
    S usa base_h/base_a (con forma): questo e' esattamente il comportamento
    storico e non viene toccato (att0/def0 continuano a includere la forma).

    Testa O/U e GG/NG: si usano i lambda base PURI di lungo periodo
    (base_pure_h/base_pure_a, M=1, senza forma ne' mercato), con clip; se i
    lambda puri non vengono forniti (retro-compatibilita') si ripiega su
    base_h/base_a, come prima dell'introduzione di att0_pure/def0_pure.
    """
    S = base_h + base_a
    den = mkt_h + mkt_a
    if den > 0:
        norm_h = S * mkt_h / den
        norm_a = S * mkt_a / den
    else:
        norm_h, norm_a = base_h, base_a
    m1 = _poisson_market(norm_h, norm_a, max_goals)     # testa 1X2
    t_h = base_h if base_pure_h is None else base_pure_h
    t_a = base_a if base_pure_a is None else base_pure_a
    m0 = _poisson_market(t_h, t_a, max_goals)           # testa Totali
    return {
        "1": m1["1"], "X": m1["X"], "2": m1["2"],
        "u15": m0["u15"], "u25": m0["u25"], "u35": m0["u35"],
        "gg": m0["gg"],
    }


def _stat_num(ts, key, default):
    v = ts.get(key) if isinstance(ts, dict) else None
    return v if isinstance(v, (int, float)) and v == v else default  # v==v esclude NaN


def get_full_poisson_two_heads(hs, as_, avg_h, avg_a, max_goals=15):
    """Wrapper di alto livello sui dizionari 'stats' del motore.

    Ogni dizionario squadra deve avere att/def (aggiustati da forma e mercato,
    testa 1X2), att0/def0 (base con forma, M=1: ancora S della normalizzazione
    1X2) e att0_pure/def0_pure (baseline pura di lungo periodo, M=1, senza
    forma: testa O/U2.5 e GG/NG). Se att0_pure/def0_pure mancano si ripiega su
    att0/def0 (comportamento precedente); se mancano att0/def0 si ripiega su
    att/def (== modello a testa singola equivalente, ma con normalizzazione
    della somma su se stessa).
    """
    hs = hs or {}
    as_ = as_ or {}
    att0_h = _stat_num(hs, "att0", _stat_num(hs, "att", 1.0))
    def0_h = _stat_num(hs, "def0", _stat_num(hs, "def", 1.0))
    att0_a = _stat_num(as_, "att0", _stat_num(as_, "att", 1.0))
    def0_a = _stat_num(as_, "def0", _stat_num(as_, "def", 1.0))
    mkt_h = _stat_num(hs, "att", 1.0) * _stat_num(as_, "def", 1.0) * avg_h
    mkt_a = _stat_num(as_, "att", 1.0) * _stat_num(hs, "def", 1.0) * avg_a
    base_h = att0_h * def0_a * avg_h
    base_a = att0_a * def0_h * avg_a
    # Baseline pura per la testa Totali (senza forma). Fallback su att0/def0.
    attp_h = _stat_num(hs, "att0_pure", att0_h)
    defp_h = _stat_num(hs, "def0_pure", def0_h)
    attp_a = _stat_num(as_, "att0_pure", att0_a)
    defp_a = _stat_num(as_, "def0_pure", def0_a)
    base_pure_h = attp_h * defp_a * avg_h
    base_pure_a = attp_a * defp_h * avg_a
    return _two_heads_from_lambdas(base_h, base_a, mkt_h, mkt_a,
                                   base_pure_h, base_pure_a, max_goals)

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
    except Exception as e:
        logging.warning(f"Errore ultimi risultati team {team_id}: {e}")
        return []

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
    except Exception as e:
        logging.warning(f"Errore infraset team {team_id}: {e}")
        pass
    return giocate, programmate

def _match_team_name(target_clean, api_name):
    """Match robusto tra nome target pulito e nome API. Evita falsi positivi parziali."""
    if not target_clean or not api_name:
        return False
    api_clean = clean_name(api_name)
    if target_clean.lower() == api_clean.lower():
        return True
    # Contenimento con word boundary: es. "Roma" matcha "AS Roma" ma NON "Bromley"
    t = target_clean.lower()
    a = api_clean.lower()
    if t in a:
        idx = a.find(t)
        before = idx == 0 or a[idx - 1] == ' '
        after = idx + len(t) == len(a) or a[idx + len(t)] == ' '
        return before and after
    if a in t:
        idx = t.find(a)
        before = idx == 0 or t[idx - 1] == ' '
        after = idx + len(a) == len(t) or t[idx + len(a)] == ' '
        return before and after
    return False

def get_contesto_partita(h, a, camp_sel):
    h_id, a_id = get_team_fd_id(h, camp_sel), get_team_fd_id(a, camp_sel)
    contesto = {
        "h_risultati": get_ultimi_risultati_fd(h_id, camp_sel) if h_id else [],
        "a_risultati": get_ultimi_risultati_fd(a_id, camp_sel) if a_id else [],
        "h_infortunati": [], "a_infortunati": [],
        "h_infraset": [], "a_infraset": [],
        "h_infraset_prog": [], "a_infraset_prog": []
    }
    camp_code = LEAGUE_CODE_MAP.get(camp_sel, "SA")
    match_date = datetime.now(timezone.utc)
    match_id_found = None
    h_clean = clean_name(h)
    for mx in st.session_state.get("live_data", []):
        api_home = mx["homeTeam"].get("shortName", "") or mx["homeTeam"].get("name", "")
        if _match_team_name(h_clean, api_home):
            try:
                match_date = datetime.fromisoformat(mx["utcDate"].replace("Z", "+00:00"))
                match_id_found = mx["id"]
            except Exception:
                pass
            break
    if h_id:
        contesto["h_infraset"], contesto["h_infraset_prog"] = get_infraset_data(
            h_id, camp_code, match_date.isoformat(), datetime.now(timezone.utc).isoformat()
        )
    if a_id:
        contesto["a_infraset"], contesto["a_infraset_prog"] = get_infraset_data(
            a_id, camp_code, match_date.isoformat(), datetime.now(timezone.utc).isoformat()
        )
    return contesto, match_id_found

# Una giornata di campionato si gioca in pochi giorni (weekend + eventuale
# anticipo/posticipo): una partita della stessa "matchday" ma settimane più
# avanti nel calendario è un recupero/posticipo anomalo e non deve entrare
# nel Top Mix del giorno.
TOP_MIX_ROUND_WINDOW_DAYS = 5


def _parse_utc_date(utc_date_str):
    """Converte 'utcDate' ISO 8601 (es. '2026-09-06T14:00:00Z') in datetime timezone-aware.

    Restituisce None se il valore è mancante o non valido, così il chiamante
    scarta la partita senza mai confrontare datetime naive con aware.
    """
    if not utc_date_str or not isinstance(utc_date_str, str):
        return None
    try:
        dt = datetime.fromisoformat(utc_date_str.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:  # difensivo: data senza offset -> trattata come UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def select_next_matchday_matches(matches, now=None):
    """Seleziona tutte e sole le partite della prossima giornata realmente futura.

    Fix bug Top Mix: prima la selezione usava min(matchday) sulle partite
    TIMED/SCHEDULED restituite dall'API, che NON garantisce sia la prossima
    giornata da giocare (partite passate ancora TIMED, recuperi lontani nel
    calendario o dati anomali potevano far entrare nel Top Mix del giorno
    partite di giornate molto più avanti, es. fine ottobre). Ora:

    1. 'utcDate' viene convertito in datetime timezone-aware;
    2. vengono scartate le partite con data/ora <= now (restano solo quelle
       realmente future) e quelle con dati anomali (utcDate/matchday mancanti
       o non validi);
    3. la prossima giornata è quella della prima partita futura per data di
       gioco effettiva (kickoff più vicino), NON il min(matchday);
    4. si restituiscono solo le partite di quella giornata che cadono nella
       stessa finestra di round: giornate future successive (non contigue) o
       recuperi isolati della stessa giornata ma lontani nel calendario non
       possono mai entrare.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:  # difensivo: mai confrontare naive con aware
        now = now.replace(tzinfo=timezone.utc)

    future = []
    for m in matches or []:
        md = m.get("matchday")
        dt = _parse_utc_date(m.get("utcDate"))
        if dt is None or not isinstance(md, int) or dt <= now:
            continue
        future.append((dt, md, m))
    if not future:
        return []

    # Ordina per data reale di gioco (non per matchday): la prima partita
    # futura individua la giornata ancora da giocare.
    future.sort(key=lambda t: t[0])
    first_kickoff, next_matchday = future[0][0], future[0][1]
    window_end = first_kickoff + timedelta(days=TOP_MIX_ROUND_WINDOW_DAYS)

    return [m for dt, md, m in future
            if md == next_matchday and dt <= window_end]


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
            # Fix bug Top Mix: si seleziona la prossima giornata realmente
            # futura per data di gioco, non più il semplice min(matchday).
            matches = select_next_matchday_matches(r.json().get('matches', []))
        except Exception as e:
            logging.warning(f"Errore fetch Top Mix {league}: {e}")
            continue
        for match in matches:
            h = match['homeTeam'].get('shortName') or match['homeTeam'].get('name', '?')
            a = match['awayTeam'].get('shortName') or match['awayTeam'].get('name', '?')
            h_s = team_stats.get(clean_name(h), {"att": 1.0, "def": 1.0})
            a_s = team_stats.get(clean_name(a), {"att": 1.0, "def": 1.0})
            
            # Poisson a due teste: 1X2 da mercato normalizzato, O/U e GG da lambda base
            m_poisson = get_full_poisson_two_heads(h_s, a_s, avg_h, avg_a)
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
            m = get_full_poisson_two_heads(h_s, a_s, avg_h, avg_a)
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
                # due teste: base (M=1) e con mercato, con i moltiplicatori infraset
                att0_h = hs.get("att0", hs.get("att", 1.0)); def0_h = hs.get("def0", hs.get("def", 1.0))
                att0_a = as_.get("att0", as_.get("att", 1.0)); def0_a = as_.get("def0", as_.get("def", 1.0))
                mkt_h = hs.get("att", 1.0) * h_mult_att * as_.get("def", 1.0) * a_mult_def * ah
                mkt_a = as_.get("att", 1.0) * a_mult_att * hs.get("def", 1.0) * h_mult_def * aa
                base_h = att0_h * h_mult_att * def0_a * a_mult_def * ah
                base_a = att0_a * a_mult_att * def0_h * h_mult_def * aa
                m_adj = _two_heads_from_lambdas(base_h, base_a, mkt_h, mkt_a)
            else:
                # fallback senza engine: testa singola neutra
                m_adj = get_full_poisson(1.3, 1.1)
            p1, pX, p2 = m_adj['1'], m_adj['X'], m_adj['2']

            # --- CONTESTO PER IL PROMPT (Elo, classifica, forma recente) ---
            # Il prompt ragionato ha bisogno di questi dati: senza di essi un
            # NameError verrebbe inghiottito dal try/except e Billy non risponderebbe.
            try:
                elo_p = predict_elo_probs(h, a, camp_sel)
            except Exception as e:
                logging.warning(f"Elo non disponibile per {h} vs {a}: {e}")
                elo_p = {'1': p1, 'X': pX, '2': p2, 'elo_diff': 0.0}
            classifica = st.session_state.get("classifica", {}) or {}
            h_pos = classifica.get(clean_name(h), {}).get("pos", "N/D")
            a_pos = classifica.get(clean_name(a), {}).get("pos", "N/D")
            h_ris = contesto.get("h_risultati", [])
            a_ris = contesto.get("a_risultati", [])

            prompt = f"""Sei Billy Walters, esperto di betting con 40 anni di esperienza. Analizza {h} vs {a} ({camp_sel}).

DATI QUANTITATIVI DEI MODELLI:
- Poisson: 1={p1:.1%} | X={pX:.1%} | 2={p2:.1%}
- Elo: 1={elo_p['1']:.1%} | X={elo_p['X']:.1%} | 2={elo_p['2']:.1%} (diff Elo={elo_p['elo_diff']:.0f})
- Classifica attuale: {h} è {h_pos}° in classifica, {a} è {a_pos}°
- Ultimi 5 risultati {h}: {', '.join(h_ris[-5:]) if h_ris else 'N/D'}
- Ultimi 5 risultati {a}: {', '.join(a_ris[-5:]) if a_ris else 'N/D'}

COMPITO:
1. Confronta le probabilità dei modelli con la forma recente e la posizione in classifica.
2. Se i dati quantitativi e la forma recente sono in forte disaccordo, spiega quale fattore prevale e perché.
3. Considera eventuali fattori esterni (fatica da infraset, derby, calo di forma).
4. Dai UN SOLO pronostico principale nel formato esatto:
   PRONOSTICO SICURO: "[Mercato] - [Probabilità%] - [Motivo in 1 riga]"

RISPONDI IN ITALIANO. Sii diretto e concreto, niente frasi generiche."""

            # max_tokens più alto: il prompt ragionato produce una risposta più lunga e
            # la riga PRONOSTICO SICURO è in coda -> con 500 token veniva tagliata via.
            try: res = groq_client.chat.completions.create(model="openai/gpt-oss-120b", messages=[{"role": "user", "content": prompt}], max_tokens=900)
            except Exception as e_model:
                logging.warning(f"Modello primario non disponibile ({e_model}); fallback qwen")
                res = groq_client.chat.completions.create(model="qwen/qwen3.6-27b", messages=[{"role": "user", "content": prompt}], max_tokens=900)
            
            testo = res.choices[0].message.content.replace("**", "").replace("*", "")
            # Mostra SEMPRE il testo di Billy
            st.markdown(f"<div style='color: var(--sm-card-text, #1a1a1a); font-size:15px; line-height:1.6;'>{testo}</div>", unsafe_allow_html=True)
            
            # Cerca di salvare nel registro in modo flessibile
            pronostico_trovato = ""
            for riga in testo.split("\n"):
                rs = riga.strip().lstrip("#>-* ").strip()
                if "PRONOSTICO SICURO" in rs.upper():
                    pronostico_trovato = rs.replace("PRONOSTICO SICURO:", "").replace("PRONOSTICO SICURO :", "").strip()
                    # Billy a volte avvolge il pronostico in virgolette: vanno tolte
                    pronostico_trovato = pronostico_trovato.strip(' "\'`')
                    break
            
            # --- VALUE BET CALCULATOR ---
            st.divider()
            st.subheader("💰 Value Bet Check")
            
            # Determina probabilità del mercato effettivo pronosticato
            mkt_std = standardizza_mercato(pronostico_trovato, h, a) if pronostico_trovato else ""
            if mkt_std == "1": prob_modello = p1
            elif mkt_std == "X": prob_modello = pX
            elif mkt_std == "2": prob_modello = p2
            elif mkt_std == "UNDER_2.5": prob_modello = m_adj['u25']
            elif mkt_std == "OVER_2.5": prob_modello = 1 - m_adj['u25']
            elif mkt_std == "GG": prob_modello = m_adj['gg']
            elif mkt_std == "NG": prob_modello = 1 - m_adj['gg']
            else: prob_modello = max(p1, pX, p2)
            
            col_q, col_ev = st.columns(2)
            with col_q:
                quota_book = st.number_input("Quota Bookmaker", min_value=1.01, max_value=50.0, value=2.00, step=0.05, key=f"qb_{match_id}")
            ev = (prob_modello * quota_book) - 1
            with col_ev:
                st.metric("EV (Expected Value)", f"{ev:.2%}")
                if ev > 0.05:
                    st.success("✅ VALUE BET FORTE")
                elif ev > 0:
                    st.info("🟡 Margine positivo")
                else:
                    st.error("❌ Nessun valore")
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

    do_sync = st.button("🟢 SINCRONIZZA", disabled=has_data, width="stretch")
    do_refresh = st.button("♾️ Refresh", width="stretch")

    # --- CHAT BILLY ---
    st.divider()
    st.subheader("💬 Chiedi a Billy")
    chat_msg = st.text_input("Scrivi qui...", placeholder="Es: Chi vince Milan-Inter?", key="billy_chat_input", label_visibility="collapsed")
    if st.button("Invia", width="stretch", key="billy_chat_send") and chat_msg and groq_client:
        with st.spinner("Billy pensa..."):
            try:
                chat_res = groq_client.chat.completions.create(
                    model="openai/gpt-oss-120b",
                    messages=[{"role": "user", "content": f"Sei Billy Walters, esperto di betting. Rispondi in italiano, breve e concreto. Domanda: {chat_msg}"}],
                    max_tokens=400,
                    temperature=0.5
                )
                # teniamo la risposta in session_state: così non sparisce alla
                # prima interazione successiva (click su un tab, un filtro, ecc.)
                st.session_state["billy_chat_answer"] = (chat_msg, chat_res.choices[0].message.content)
            except Exception as e:
                st.session_state["billy_chat_answer"] = (chat_msg, f"__ERR__{e}")
    if "billy_chat_answer" in st.session_state:
        asked, answer = st.session_state["billy_chat_answer"]
        answer = answer or "(nessuna risposta dal modello)"
        with st.container():
            st.caption(f"💭 {asked}")
            if answer.startswith("__ERR__"):
                st.error(f"Errore chat: {answer[7:]}")
            else:
                st.info(answer)
    elif chat_msg and not groq_client:
        st.error("Billy non è configurato. Aggiungi GROQ_API_KEY nei Secrets.")

    # --- TEMA ---
    st.divider()
    follow_system = st.toggle("🌓 Segui tema sistema", value=True, key="follow_system_toggle",
                              help="Attivo = si adatta al tema del dispositivo. Disattivo = forza modalità chiara.")
    if not follow_system:
        # Modalità chiara forzata. Streamlit resta internamente in dark (se il sistema
        # è dark), quindi NON basta toccare le variabili: il testo nativo (markdown,
        # metriche, widget) ha colori iniettati via Emotion. Qui forziamo in modo
        # esplicito sfondi CHIARI e testi SCURI con !important, sia per gli elementi
        # custom sia per i componenti Streamlit, per evitare testo bianco su bianco.
        st.markdown("""
        <style>
            :root {
                color-scheme: light;
                --sm-card-bg: #ffffff !important;
                --sm-card-text: #1a1d23 !important;
                --sm-card-border: rgba(128,128,128,0.2) !important;
                --sm-accent: #0056b3 !important;
                --sm-muted-bg: #f8f9fa !important;
            }
            /* Sfondo pagina, header e toolbar */
            body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stToolbar"] {
                background-color: #ffffff !important;
                color: #1a1d23 !important;
            }
            [data-testid="stDecoration"] { background-color: #ffffff !important; }
            /* Sidebar */
            .stSidebar, [data-testid="stSidebar"], [data-testid="stSidebarContent"] {
                background-color: #f0f2f6 !important;
                color: #1a1d23 !important;
            }
            /* Testo generico: markdown (card incluse), titoli, caption, label */
            [data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p,
            [data-testid="stMarkdownContainer"] li { color: #1a1d23 !important; }
            h1, h2, h3, h4, h5, h6 { color: #1a1d23 !important; }
            [data-testid="stCaptionContainer"] { color: #555555 !important; }
            label { color: #1a1d23 !important; }
            /* Widget di input */
            .stButton button { background-color: #ffffff !important; color: #1a1d23 !important; border: 1px solid #d1d5db !important; }
            .stTextInput input, .stTextArea textarea { background-color: #ffffff !important; color: #1a1d23 !important; }
            .stSelectbox div[data-baseweb="select"], .stSelectbox div[data-baseweb="select"] > div,
            .stMultiSelect div[data-baseweb="select"] { background-color: #ffffff !important; color: #1a1d23 !important; }
            .stSelectbox [data-baseweb="popover"] *, .stMultiSelect [data-baseweb="popover"] * { color: #1a1d23 !important; background-color: #ffffff !important; }
            /* Tab */
            .stTabs [data-baseweb="tab-list"] { background-color: #ffffff !important; }
            .stTabs [data-baseweb="tab"] { color: #1a1d23 !important; }
            .stTabs [aria-selected="true"] { color: #0056b3 !important; }
            /* Metriche (registro e backtest): valore ed etichetta ben visibili */
            [data-testid="stMetricValue"] { color: #1a1d23 !important; }
            [data-testid="stMetricLabel"] { color: #555555 !important; }
            [data-testid="stMetricDelta"] { color: #0056b3 !important; }
            /* Expander e toggle */
            [data-testid="stExpander"] { background-color: #f8f9fa !important; color: #1a1d23 !important; }
            [data-testid="stToggle"] label { color: #1a1d23 !important; }
            /* Card custom: forzate a chiaro (il testo inline colorato, es. verde,
               resta intatto perché qui non usiamo selettori universali) */
            .match-card { background-color: #ffffff !important; color: #1a1d23 !important; border: 1px solid #e0e4e9 !important; }
            .stat-container { background-color: #f8f9fa !important; color: #1a1d23 !important; border: 1px solid #e0e4e9 !important; }
            .top-mix-row { background-color: #ffffff !important; color: #1a1d23 !important; border: 1px solid #e0e4e9 !important; }
            .team-name { color: #1a1d23 !important; }
            .label-header { color: #0056b3 !important; border-bottom: 2px solid #e0e4e9 !important; }
            .match-date { color: #0056b3 !important; }
        </style>
        """, unsafe_allow_html=True)

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
            h_s = team_stats.get(clean_name(h_api), {"att": 1.0, "def": 1.0})
            a_s = team_stats.get(clean_name(a_api), {"att": 1.0, "def": 1.0})
            m = get_full_poisson_two_heads(h_s, a_s, avg_h, avg_a)
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
        st.dataframe(elo_df, width="stretch", height=400)
        st.divider(); teams = sorted(elo_df["Squadra"].tolist())
        c1, c2 = st.columns(2)
        with c1: sh = st.selectbox("Casa", teams, key="sh")
        with c2: sa = st.selectbox("Trasf.", teams, index=1 if len(teams)>1 else 0, key="sa")
        if sh and sa:
            sp = predict_elo_probs(sh, sa, camp_sel)
            st.markdown(f"<div style='background:#30363d; height:24px; display:flex; overflow:hidden; margin-top:10px; border-radius:8px;'><div style='width:{sp['1']*100}%; background:#28a745; text-align:center; color:white; font-size:12px; font-weight:700; line-height:24px;'>1: {sp['1']:.0%}</div><div style='width:{sp['X']*100}%; background:#ffc107; text-align:center; color:black; font-size:12px; font-weight:700; line-height:24px;'>X: {sp['X']:.0%}</div><div style='width:{sp['2']*100}%; background:#dc3545; text-align:center; color:white; font-size:12px; font-weight:700; line-height:24px;'>2: {sp['2']:.0%}</div></div>", unsafe_allow_html=True)

with tab4:
    st.subheader("📊 Backtest Storico (Walk-Forward)")
    st.caption("Simula Poisson ed Elo sulle partite già giocate usando SOLO i dati precedenti "
               "(le ~300 più recenti, riaddestrate ogni 5 giornate). Dixon-Coles è escluso per velocità.")

    if st.button("🚀 Avvia Backtest", type="primary"):
        with st.spinner("Calcolo in corso... può richiedere 1-2 minuti"):
            df_back = run_historical_backtest(camp_sel)
        st.session_state["backtest_df"] = df_back
        st.session_state["backtest_camp"] = camp_sel

    # Il risultato viene tenuto in session_state così non sparisce al primo
    # rerun (click su un altro tab, cambio filtro, sincronizzazione, ecc.)
    if "backtest_df" in st.session_state and st.session_state.get("backtest_camp") != camp_sel:
        st.info("🔄 Campionato cambiato: premi di nuovo 'Avvia Backtest' per ricalcolare.")
    elif "backtest_df" in st.session_state and st.session_state.get("backtest_camp") == camp_sel:
        df_back = st.session_state["backtest_df"].copy()
        if df_back.empty:
            st.warning("Dati insufficienti per il backtest (servono almeno 40 partite storiche).")
        else:
            n = len(df_back)
            pois_wr = df_back['poisson_ok'].mean() * 100
            elo_wr = df_back['elo_ok'].mean() * 100
            uo_wr = df_back['poisson_uo_ok'].mean() * 100
            gg_wr = df_back['poisson_gg_ok'].mean() * 100

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Partite testate", n)
            c2.metric("Poisson 1X2", f"{pois_wr:.1f}%")
            c3.metric("Elo 1X2", f"{elo_wr:.1f}%")
            c4.metric("Poisson U/O + GG", f"{(uo_wr+gg_wr)/2:.1f}%")

            st.divider()
            comp_data = []
            for mkt in ['1X2', 'Under/Over 2.5', 'GG/NG']:
                if mkt == '1X2':
                    comp_data.append({"Mercato": mkt, "Poisson": f"{pois_wr:.1f}%", "Elo": f"{elo_wr:.1f}%"})
                elif mkt == 'Under/Over 2.5':
                    comp_data.append({"Mercato": mkt, "Poisson": f"{uo_wr:.1f}%", "Elo": "N/D"})
                else:
                    comp_data.append({"Mercato": mkt, "Poisson": f"{gg_wr:.1f}%", "Elo": "N/D"})
            st.dataframe(pd.DataFrame(comp_data), width="stretch", hide_index=True)
            st.caption(f"Baseline (punto di riferimento): 1X2 ~45%, Under/Over e GG/NG ~50%. "
                       f"Con {n} partite il campione è ancora rumoroso: sotto ~150 considera i valori come indicativi.")

            df_back['cum_pois'] = df_back['poisson_ok'].expanding().mean() * 100
            df_back['cum_elo'] = df_back['elo_ok'].expanding().mean() * 100
            st.line_chart(df_back[['cum_pois', 'cum_elo']].rename(columns={'cum_pois': 'Poisson 1X2', 'cum_elo': 'Elo 1X2'}))

            with st.expander("Vedi ultimi 20 risultati"):
                df_show = df_back[['date', 'home', 'away', 'real_1x2', 'poisson_1x2', 'elo_1x2', 'real_uo', 'poisson_uo', 'real_gg', 'poisson_gg']].tail(20).copy()
                df_show['date'] = pd.to_datetime(df_show['date']).dt.strftime('%d/%m/%Y')
                st.dataframe(df_show, width="stretch", hide_index=True)


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
        # Classificazione esplicita: i record senza model_version restano
        # "Legacy" e NON vengono considerati automaticamente post-fix.
        df_preds['modello'] = [model_label(p) for p in preds]

        f_col1, f_col2, f_col3 = st.columns(3)
        with f_col1:
            camp_options = ["Tutti"] + list(LEAGUES_CONFIG.keys())
            filter_camp = st.selectbox("Campionato", camp_options, index=0)
        with f_col2: 
            filter_status = st.selectbox("Esito", ["Tutti", "In Attesa (⏳)", "Vinte (✅)", "Perse (❌)"])
        with f_col3: 
            stagioni_reali = sorted(df_preds['stagione'].unique().tolist(), reverse=True)
            default_stagione_idx = 1 if len(stagioni_reali) > 0 else 0
            filter_stagione = st.selectbox("Stagione", ["Tutti"] + stagioni_reali, index=default_stagione_idx)
            
        if filter_camp != "Tutti": df_preds = df_preds[df_preds["campionato"] == filter_camp]
        if filter_status == "In Attesa (⏳)": df_preds = df_preds[df_preds["esito"].isin(["⏳", None])]
        elif filter_status == "Vinte (✅)": df_preds = df_preds[df_preds["esito"] == "✅"]
        elif filter_status == "Perse (❌)": df_preds = df_preds[df_preds["esito"] == "❌"]
        if filter_stagione != "Tutti": df_preds = df_preds[df_preds["stagione"] == filter_stagione]

        filtered_records = df_preds.to_dict("records")
        current_stats = stats_current_model(filtered_records)
        historical_stats = stats_historical(filtered_records)
        all_stats = stats_all(filtered_records)

        st.caption(
            "Statistiche separate: il win rate del **modello attuale** usa SOLO le predizioni "
            f"`{MODEL_VERSION_CURRENT}`; le predizioni pre-fix e i record legacy/ambiguo restano "
            "visibili per audit ma sono esclusi dalle metriche attuali."
        )

        st.markdown("##### 📊 Modello attuale")
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Totale", current_stats["total"])
        s2.metric("✅ Vinte", current_stats["wins"],
                  delta=f"{current_stats['win_rate']:.1f}%" if current_stats["decided"] else None,
                  help="Percentuale calcolata solo sulle partite decise del modello attuale (esclude quelle in attesa).")
        s3.metric("❌ Perse", current_stats["losses"])
        s4.metric("⏳ Attesa", current_stats["pending"])

        st.markdown("##### 📜 Storico / pre-fix (audit)")
        h1, h2, h3, h4 = st.columns(4)
        h1.metric("Totale", historical_stats["total"])
        h2.metric("✅ Vinte", historical_stats["wins"],
                  delta=f"{historical_stats['win_rate']:.1f}%" if historical_stats["decided"] else None,
                  help="Win rate storico/audit separato, calcolato solo sulle partite decise non incluse nel modello attuale.")
        h3.metric("❌ Perse", historical_stats["losses"])
        h4.metric("⏳ Attesa", historical_stats["pending"])

        st.caption(
            f"Totale registro (audit complessivo): Totale {all_stats['total']}, "
            f"Vinte {all_stats['wins']} ({all_stats['win_rate']:.1f}% su decise), "
            f"Perse {all_stats['losses']}, Attesa {all_stats['pending']}."
        )

        # Fix visivo: converte i vecchi 'None' in '⏳' e i risultati vuoti in '-'
        df_display = df_preds.fillna({"esito": "⏳", "risultato_reale": "-"})
        st.caption(
            f"{MODEL_LABEL_PRE_FIX} = {PRE_FIX_TOOLTIP} · "
            f"{MODEL_LABEL_CURRENT} = {CURRENT_MODEL_TOOLTIP}"
        )
        st.dataframe(
            df_display[
                ["data", "stagione", "campionato", "home", "away", "mercato_standard",
                 "prob_sicuro", "risultato_reale", "esito", "modello"]
            ].sort_values(by="data", ascending=False),
            width="stretch",
            height=500,
            column_config={
                "modello": st.column_config.TextColumn(
                    "Modello",
                    help=f"{MODEL_LABEL_PRE_FIX}: {PRE_FIX_TOOLTIP}\n\n{MODEL_LABEL_CURRENT}: {CURRENT_MODEL_TOOLTIP}",
                )
            },
        )
