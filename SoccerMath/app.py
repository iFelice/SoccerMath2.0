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
from xg_archive import season_point_in_time_averages
from models.elo_engine import get_current_elo, get_elo_engine, get_elo_leaderboard, predict_elo_probs, get_team_elo_history
from models.dixon_coles import get_dixon_coles_matrix, predict_dixon_coles_probs, get_dixon_coles_team_strengths
from models.backtest import run_backtest, compare_models_backtest, detect_value_bets
from display_names import display_name
# Quote 1X2 dal vivo: l'app LEGGE il file scritto dal workflow live_odds.yml,
# non chiama mai The Odds API (vincolo della commessa, verificato da
# test_quote_live.py::TestLAppNonChiamaLaFonte).
import market_odds
from market_odds import (
    AVVISO_INDIPENDENZA,
    ESITI as ESITI_MERCATO,
    FONTE_ASSENTE,
    FONTE_MEDIA_LIBRI,
    FONTE_PINNACLE,
    MASSIMO_RIGHE_MULTIPLA,
    MOTIVO_ASSENTE_DALLA_FONTE,
    MOTIVO_TERNA_NON_VALIDA,
    SOGLIA_ACCORDO,
    SOGLIA_ORE_QUOTE,
    STATO_ASSENTE,
    STATO_NON_LEGGIBILE,
    STATO_OK,
    STATO_SENZA_LEGHE,
    SOGLIA_TOPMIX_MERCATO,
    carica_quote_live,
    carica_quote_live_con_stato,
    cerca_quote,
    cerca_quote_con_motivo,
    indice_partite,
    multipla,
    probabilita_mercato,
)

from config import (
    FOOTBALL_DATA_API_KEY, GROQ_API_KEY, ODDS_API_KEY, JSONBIN_API_KEY, JSONBIN_BIN_ID,
    PREDICTIONS_FILE, LEAGUES_CONFIG, LEAGUE_CODE_MAP, LEAGUE_PREFIX_MAP, CURRENT_SEASON, clean_name, DATABASE_DIR,
    LEAGUE_HOME_ADVANTAGE, get_league_db_files, season_label, season_start_year,
    season_start_year_of, get_current_season_start_year,
)
from prediction_registry import (
    origin_of,
    EXCLUDED_FROM_CURRENT_STATS_FIELD,
    MODEL_VERSION_CURRENT,
    MODEL_VERSION_FIELD,
    MODEL_LABEL_CURRENT,
    MODEL_LABEL_LEGACY,
    MODEL_LABEL_PRE_FIX,
    PRE_FIX_TOOLTIP,
    CURRENT_MODEL_TOOLTIP,
    new_prediction_metadata,
    model_label,
    is_current_model,
    stats_all,
    backup_prediction_file,
    build_registry_datetime_column,
    # --- tracciamento Top Mix (audit/margini_migliorabili_topmix.md §7) ---
    SELECTOR_VERSION_CURRENT,
    SELECTOR_VERSION_PRE_1X2,
    SELECTOR_VERSION_OMBRA_BY_FAMIGLIA, OMBRA_FAMIGLIA_FIELD, OMBRA_FAMIGLIA_OU25, OMBRA_FAMIGLIA_GGNG,
    OMBRA_FAMIGLIA_1X2, SELECTOR_VERSION_OMBRA_1X2,
    ORIGIN_TOP_MIX_OMBRA,
    # --- Top Mix di mercato (topmix_mercato_v3): campi della riga visibile ---
    MERCATO_FONTE_FIELD, MERCATO_N_LIBRI_FIELD, PROB_MERCATO_FIELD,
    QUOTA_MERCATO_FIELD, ACCORDO_MODELLO_FIELD, PROB_MODELLO_FIELD,
    QUOTE_LIVE_ISTANTE_FIELD,
    PROB_MERCATO_PRIMA_FIELD, QUOTA_MERCATO_PRIMA_FIELD,
    PROB_MODELLO_PRIMA_FIELD, ACCORDO_MODELLO_PRIMA_FIELD,
    QUOTE_LIVE_ISTANTE_PRIMA_FIELD,
    OMBRA_FIELD, OMBRA_MERCATO_FIELD, OMBRA_CONFIDENCE_FIELD, OMBRA_AMMESSA_FIELD,
    OMBRA_SOGLIA_FIELD, OMBRA_VINCENTE_GLOBALE_FIELD, OMBRA_DATI_MANCANTI_FIELD,
    OMBRA_SOGLIA_TOTALI,
    is_ombra,
    righe_visibili,
    upsert_prediction_entries,
    ORIGIN_TOP_MIX,
    ORIGIN_ANALISI_RAPIDA,
    ORIGIN_BILLY,
    build_calculation_id,
    calibration_by_mercato,
    compute_calibration_stats,
    compute_stats,
    esito_mercato,
    resolve_origin,
    righe_non_iniziate,
    snapshot_fingerprint,
    tipo_for_origin,
    upsert_prediction_entry,
    overall_reliability_transfer_warning,
    # --- gate shadow (referto §11quater, piano §9 punto 4) ---
    GATE_SHADOW_CONFIDENCE_FIELD,
    GATE_SHADOW_AMMESSA_FIELD,
    GATE_OFF_CONFIDENCE_FIELD,
    GATE_OFF_AMMESSA_FIELD,
    gate_shadow_confidence,
    gate_shadow_fields_from_row,
    gate_off_confidence,
    gate_off_fields_from_row,
    # --- Top Mix a due motori: variante del modello (attuale / legacy) ---
    MODEL_VARIANT_FIELD,
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_LEGACY,
    MODEL_VARIANT_LABELS,
    model_variant_label,
    model_variant_of,
    # Lettura della variante per DATA quando il campo manca: e' quella che
    # l'utente deve vedere (una riga nata prima del merge di PR#24 e' del
    # motore di allora, cioe' legacy).
    model_variant_read,
    # --- famiglie del selettore: modello (fino al 09/10/2026) e mercato (dal) ---
    FAMIGLIA_SELETTORE_MODELLO,
    FAMIGLIA_SELETTORE_MERCATO,
    famiglia_selettore,
)
from models.legacy_elo import predict_elo_probs_legacy

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

def _stagione_da_utcdate(utc_date_str):
    """Anno di inizio stagione del calcio d'inizio (confine unico 1° luglio).

    Serve a ``predict_elo_probs``: il seed di una squadra senza rating ha
    bisogno della stagione della partita da prevedere (dato di calendario,
    noto prima del via). Se la data manca o e' illeggibile si ricade sulla
    stagione corrente: non deve mai alzare, altrimenti una ``utcDate`` rotta
    cancellerebbe l'intera partita invece di degradare l'Elo.
    """
    try:
        dt = datetime.fromisoformat(str(utc_date_str).replace("Z", "+00:00"))
        return season_start_year_of(dt)
    except Exception:
        return get_current_season_start_year()


def _roster_stagione(league, season):
    """R(lega, stagione): le squadre della stagione, dal roster del calendario.

    E' la STESSA fonte del motore Elo (``season_rosters_with_file``: file
    versionato ``database/season_rosters.json`` dove c'e', calendario delle
    giocate per le stagioni concluse): una squadra e' "nota" se il campionato
    di quell'anno la contiene, informazione di calendario nota prima del via.

    Ritorna l'insieme dei nomi puliti, o ``None`` se il roster della stagione
    non e' noto (o il motore non e' caricabile): in quel caso un nome fuori
    roster non e' distinguibile da una neopromossa senza dati e il chiamante
    resta permissivo (solo il caso "senza statistiche" e' valutabile). Read-only:
    usa il motore Elo gia' in cache, nessun ricalcolo.
    """
    if season is None:
        return None
    try:
        roster = get_elo_engine(league).season_rosters.get(int(season))
    except Exception as e:
        logging.warning(f"Roster {league} stagione {season} non disponibile: {e}")
        return None
    return {str(t) for t in roster} if roster is not None else None


def _stato_squadre_match(league, season, h, a, team_stats, origine):
    """Classifica i due lati di una partita contro R(stagione) e le stats del motore.

    Distingue i due soli motivi per cui ``team_stats.get(nome, default)`` e
    ``predict_elo_probs`` possono finire su un valore non calcolato:

    * caso (a) SCONOSCIUTO: il nome pulito NON e' in R(lega, stagione) —
      non e' una squadra di questo campionato (alias mancante, shortName
      dell'API cambiato, lega sbagliata). E' un errore a monte: NESSUNA
      statistica di default gli si puo' attribuire. Ogni occorrenza lascia un
      WARNING nel log con il nome GREZZO ricevuto e quello PULITO cercato.
    * caso (b) ROSTER SENZA STATISTICHE: il nome e' nel roster ma il motore
      non ha statistiche (neopromossa prima del debutto, dati non ancora
      sincronizzati). Caso legittimo: il comportamento non cambia (default
      att=1.0 def=1.0), ma il WARNING nel log lo dichiara.

    Ritorna ``(sconosciuti, senza_stats)``: liste di coppie ``(grezzo, pulito)``.
    Roster non disponibile (``None``) -> solo il caso (b) e' valutabile.
    """
    sconosciuti, senza_stats = [], []
    roster = _roster_stagione(league, season)
    for grezzo in (h, a):
        pulito = clean_name(grezzo)
        if roster is not None and pulito not in roster:
            sconosciuti.append((grezzo, pulito))
            logging.warning(
                f"{origine}: nome squadra SCONOSCIUTO, non e' nel roster di "
                f"{league} stagione {season}: grezzo '{grezzo}' -> pulito "
                f"'{pulito}'. Nessuna statistica di default gli si attribuisce.")
        elif pulito not in team_stats:
            senza_stats.append((grezzo, pulito))
            logging.warning(
                f"{origine}: squadra del roster di {league} stagione {season} "
                f"senza statistiche nel motore: grezzo '{grezzo}' -> pulito "
                f"'{pulito}'. Usate le statistiche di default att=1.0 def=1.0.")
    return sconosciuti, senza_stats


def dati_card_partita(match, team_stats, avg_h, avg_a, camp_sel):
    """Dati di UNA card della scheda PARTITE, fallback sui nomi espliciti.

    Stesso trattamento di Top Mix e Analisi Rapida:

    * caso (a) SCONOSCIUTO (nome pulito fuori da R(stagione) = errore a
      monte): NESSUNA statistica di default — ``m_poisson`` e ``m`` sono
      ``None`` e la card non va costruita; il WARNING nel log (nome grezzo e
      pulito, via ``_stato_squadre_match``) e l'avviso in scheda del chiamante
      dicono perche'.
    * caso (b) ROSTER SENZA STATISTICHE (neopromossa al debutto):
      comportamento di sempre (default att=1.0 def=1.0) piu' WARNING nel log e
      l'elenco in ``senza_stats`` per il marcatore nella card.

    Ritorna ``(h_api, a_api, m_poisson, m, sconosciuti, senza_stats)``.
    """
    h_api, a_api = match['homeTeam'].get('shortName') or match['homeTeam'].get('name', '?'), match['awayTeam'].get('shortName') or match['awayTeam'].get('name', '?')
    stagione_match = _stagione_da_utcdate(match.get('utcDate'))
    sconosciuti, senza_stats = _stato_squadre_match(
        camp_sel, stagione_match, h_api, a_api, team_stats, "PARTITE")
    if sconosciuti:
        return h_api, a_api, None, None, sconosciuti, senza_stats
    h_s = team_stats.get(clean_name(h_api), {"att": 1.0, "def": 1.0})
    a_s = team_stats.get(clean_name(a_api), {"att": 1.0, "def": 1.0})
    m_poisson = get_full_poisson_two_heads(h_s, a_s, avg_h, avg_a)
    # 1X2 mostrato = ensemble Poisson+Elo
    # (w=POISSON_1X2_WEIGHT, peso Poisson di produzione); Totali
    # (u25/gg) restano Poisson puro. m_poisson (puro)
    # viene passato a show_details per la selezione (argmax): il blend
    # deve restare fuori dall'argmax, come in analisi_rapida_giornata().
    m = blend_elo_into_1x2(m_poisson, h_api, a_api, camp_sel, season=stagione_match)
    return h_api, a_api, m_poisson, m, sconosciuti, senza_stats


def calcola_stagione_calcolo(data_str):
    """Etichetta di stagione ("2026/2027") della data di una partita.

    Il confine di stagione e' UNICO per tutta la pipeline (season_calendar,
    1° luglio, verificato sul calendario reale delle 5 leghe): prima qui si
    usava ``mese >= 8`` mentre rollover/config usavano ``mese >= 7``.
    """
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

        return season_label(season_start_year(anno, mese))
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
    /* Top Mix a due modelli: intestazioni distinte per le due tabelle */
    .top-mix-model { color: var(--sm-card-text); border-radius: 8px; padding: 12px 15px; margin: 18px 0 10px 0; border-left: 6px solid; font-size: 17px; text-transform: uppercase; letter-spacing: 0.5px; }
    .top-mix-current { background-color: rgba(40, 167, 69, 0.12); border-color: #28a745; }
    .top-mix-legacy { background-color: rgba(253, 126, 20, 0.12); border-color: #fd7e14; }
    .match-result { font-size: 18px; font-weight: 800; color: #28a745; margin-top: 5px; display: block; }
</style>
""", unsafe_allow_html=True)

# --- REGISTRO PREDIZIONI ---
def load_predictions():
    # Fonte remota primaria: il backend attivo (JSONBin come sempre, oppure
    # Upstash Redis se REGISTRY_BACKEND=upstash). In fallback il file locale,
    # SOLO se il backend non e' configurato o non risponde: un hash remoto
    # vuoto E' una risposta valida (registro vuoto), non un motivo per leggere
    # una copia locale vecchia.
    try:
        from registry_store import load_rows
        righe, fonte = load_rows(strict=False)
        if fonte != "nessuno" and righe is not None:
            return righe
    except Exception as e:
        logging.warning(f"Registro remoto non leggibile: {e}")
    if os.path.exists(PREDICTIONS_FILE):
        try:
            with open(PREDICTIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "data" in data: return data["data"]
                elif isinstance(data, list): return data
        except: return []
    return []

def save_predictions(preds):
    """Scrive il registro (locale e, se configurato, remoto) e dice com'e' andata.

    Backup prima di ogni scrittura: non si sovrascrive mai un registro esistente
    senza copia integrale. Il remoto viene aggiornato SOLO dopo che la scrittura
    locale e' riuscita.

    Ritorna ``{"locale": bool, "remoto": "ok"|"disattivato"|"errore"|"saltato"}``
    piu' ``remoto_dettaglio`` (codice HTTP e messaggio del servizio, troncati) e
    ``byte_scritti`` (dimensione del payload): il PUT non puo' piu' fallire in
    silenzio dentro un ``except: pass`` perche' il toast "Top Mix salvati!"
    verrebbe letto come una conferma di un record che non esiste (problema
    ``jsonbin_unchecked`` in ``audit/results/topmix_registry_tracking.json``), e
    quando fallisce serve sapere PERCHE' (es. il limite di 100 kB dei bin del
    piano free JSONBin: "Free users cannot create a record over 100kb").
    """
    esito = {"locale": False, "remoto": "saltato"}
    try:
        backup_prediction_file(PREDICTIONS_FILE)
        os.makedirs(DATABASE_DIR, exist_ok=True)
        with open(PREDICTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump({"data": preds}, f, ensure_ascii=False, indent=2)
        esito["locale"] = True
    except Exception as e:
        logging.warning(f"Scrittura registro locale fallita: {e}")
        esito["remoto"] = "saltato"
        return esito
    # Scrittura remota: backend attivo tramite lo strato unico. Con JSONBin e'
    # il PUT del bin intero di sempre; con Upstash e' un HSET dei SOLI campi
    # nuovi o cambiati, quindi non riscrive lo storico e non puo' cancellare le
    # righe che un altro scrittore ha aggiunto nel frattempo.
    try:
        from registry_store import backend as backend_attivo
        from registry_store import esito_scrittura, save_rows
        remoto = esito_scrittura(save_rows(preds))
    except Exception as e:
        # Se la scrittura non e' nemmeno partita (credenziali mancanti, rete
        # giu'), dire QUALE backend e' rimasto senza risposta: "n/d" non aiuta
        # chi legge il messaggio o il log.
        try:
            remoto = {"remoto": "errore", "remoto_dettaglio": f"{type(e).__name__}: {e}"[:300],
                      "backend": backend_attivo()}
        except Exception:
            remoto = {"remoto": "errore", "remoto_dettaglio": f"{type(e).__name__}: {e}"[:300]}
    esito["remoto"] = remoto.get("remoto", "errore")
    esito["backend_registro"] = remoto.get("backend", "n/d")
    if "byte" in remoto:
        esito["byte_scritti"] = remoto["byte"]
    for chiave in ("remoto_dettaglio", "comandi", "righe_scritte", "righe_saltate", "righe_hash"):
        if chiave in remoto:
            esito[chiave] = remoto[chiave]
    if esito["remoto"] not in ("ok", "disattivato"):
        logging.warning(f"Scrittura remota rifiutata/fallita: {esito.get('remoto_dettaglio', esito['remoto'])} "
                        f"(registro locale scritto, remoto NO)")
    return esito

def _mercato_name_tokens(name):
    """Token usati per riconoscere una squadra nel testo libero del pronostico.

    ``clean_name`` da solo non basta: il testo salvato usa spesso il nome
    display API (``Stade Rennais``, ``Barça``) mentre ``clean_name`` produce
    la chiave CSV (``Rennes``, ``Barcelona``), che non e' sottostringa.
    Si confrontano ENTRAMBI: grezzo e canonico.
    """
    raw = str(name or "").strip()
    if not raw:
        return []
    tokens = []
    seen = set()
    for tok in (raw.lower(), clean_name(raw).lower()):
        tok = (tok or "").strip()
        if tok and tok not in seen and len(tok) >= 2:
            seen.add(tok)
            tokens.append(tok)
    return tokens


def codice_mercato_selezionato(best_mkt, home=None, away=None):
    """Codice mercato noto al momento della generazione (non dal testo libero).

    Usato da Top Mix / Analisi Rapida / Billy quando il mercato e' gia'
    una delle sette chiavi di produzione. ``standardizza_mercato`` resta
    il fallback per i record vecchi e per il testo libero di Billy.
    """
    mapping = {
        "Pareggio": "X",
        "Over 2.5": "OVER_2.5",
        "Under 2.5": "UNDER_2.5",
        "GG": "GG",
        "NG": "NG",
    }
    if best_mkt in mapping:
        return mapping[best_mkt]
    if home is not None and best_mkt == f"Vittoria {home}":
        return "1"
    if away is not None and best_mkt == f"Vittoria {away}":
        return "2"
    return standardizza_mercato(best_mkt, home, away)


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
    
    # Vittoria casa (1) o trasferta (2) — disambigua con i nomi squadra.
    # Confronta il nome GREZZO e clean_name: il pronostico Top Mix e'
    # ``Vittoria {shortName}`` e shortName spesso non e' sottostringa del canonico.
    if home and away:
        win_re = re.search(r'\bvittoria\b|\bvince\b|\bwin\b|\b1\b|\b2\b', t)
        if win_re:
            h_hit = any(tok in t for tok in _mercato_name_tokens(home))
            a_hit = any(tok in t for tok in _mercato_name_tokens(away))
            if h_hit and not a_hit:
                return "1"
            if a_hit and not h_hit:
                return "2"
            if h_hit and a_hit:
                # Entrambi i nomi nel testo: resta la preferenza casa-prima
                # solo se il pattern non distingue; altrimenti il nome piu'
                # lungo (match piu' specifico) vince.
                h_tok = max(_mercato_name_tokens(home), key=len, default="")
                a_tok = max(_mercato_name_tokens(away), key=len, default="")
                if len(a_tok) > len(h_tok):
                    return "2"
                return "1"
    
    # Fallback esplicito per pattern numerici
    if re.search(r'\b1\b.*\b(casa|home|casalinga)\b|\b(casa|home|casalinga)\b.*\b1\b', t): return "1"
    if re.search(r'\b2\b.*\b(trasferta|away)\b|\b(trasferta|away)\b.*\b2\b', t): return "2"
    if re.search(r'^\s*1\b', t) and not re.search(r'\b2\b', t): return "1"
    if re.search(r'^\s*2\b', t) and not re.search(r'\b1\b', t): return "2"
    if re.search(r'^\s*x\b', t): return "X"
    
    return "ALTRO"

def build_prediction_entry(match_id, h, a, camp, giornata, match_date, pronostico, top3, prob, ris_attesi,
                           mercato_standard=None, origin=None, rank=None, kickoff_utc=None,
                           prob_poisson=None, prob_elo=None, elo_disponibile=None,
                           snapshot_sha=None,
                           gate_shadow_confidence=None, gate_shadow_ammessa=None,
                           gate_off_confidence=None, gate_off_ammessa=None,
                           model_variant=MODEL_VARIANT_CURRENT, salvato_il=None,
                           selector_version=None,
                           prob_mercato=None, quota_mercato=None, mercato_fonte=None,
                           mercato_n_libri=None, accordo_modello=None, prob_modello=None,
                           quote_live_istante=None):
    """Costruisce il record del registro (nessun I/O): la forma della riga vive QUI.

    E' la stessa funzione per il salvataggio live (``save_prediction_entry``)
    e per il replay walk-forward del modello legacy
    (``replay_legacy_topmix.py``): una riga ricostruita ha quindi ESATTAMENTE
    le chiavi di una riga normale, e l'unico campo che distingue i due motori
    e' ``model_variant`` (``current`` / ``legacy``). ``salvato_il`` e' l'ora di
    scrittura (default: adesso, ora italiana); il replay la passa esplicita.
    """
    stagione_reale = calcola_stagione_calcolo(match_date)
    metadata = new_prediction_metadata()
    mercato_code = mercato_standard if mercato_standard else standardizza_mercato(pronostico, h, a)
    orig = resolve_origin(origin, pronostico)
    sha = snapshot_sha if snapshot_sha is not None else snapshot_fingerprint(DATABASE_DIR)
    variante = str(model_variant or MODEL_VARIANT_CURRENT).strip().lower()
    # Versione del selettore: esplicita se passata; altrimenti quella che ha
    # prodotto la riga. Top Mix -> selettore attuale (solo 1X2); Analisi Rapida e
    # Billy -> selettore storico, cioe' la versione di sempre: il loro dedup non cambia.
    sel = selector_version or (SELECTOR_VERSION_CURRENT if orig == ORIGIN_TOP_MIX
                               else SELECTOR_VERSION_PRE_1X2)
    entry = {
        "match_id": match_id, "home": h, "away": a, "campionato": camp, "giornata": giornata,
        "data": match_date, "pronostico_sicuro": pronostico, "mercato_standard": mercato_code,
        "top3": top3, "prob_sicuro": prob, "risultati_attesi": ris_attesi,
        "risultato_reale": None, "esito": "⏳", "tipo": tipo_for_origin(orig),
        "stagione": stagione_reale,
        "salvato_il": salvato_il or datetime.now(ITALY_TZ).strftime("%d/%m/%Y %H:%M"),
        "origin": orig,
        "selector_version": sel,
        MODEL_VARIANT_FIELD: variante,
        "rank": rank,
        "kickoff_utc": kickoff_utc or "",
        "data_snapshot_sha": sha or "",
        "calculation_id": build_calculation_id(match_id, orig, sel,
                                               kickoff_utc, sha, rank, model_variant=variante),
        "poisson": prob_poisson,
        "elo": prob_elo,
        "elo_disponibile": elo_disponibile if elo_disponibile is not None else (prob_elo is not None),
        MODEL_VERSION_FIELD: metadata[MODEL_VERSION_FIELD],
        EXCLUDED_FROM_CURRENT_STATS_FIELD: metadata[EXCLUDED_FROM_CURRENT_STATS_FIELD],
    }
    # --- Gate shadow (referto §11quater): campi OPZIONALI e puramente
    # aggiuntivi. Se mancano o il calcolo e' fallito (None) il record resta
    # identico a prima: nessun campo reale (market/prob/rank/…) viene toccato.
    if gate_shadow_confidence is not None:
        entry[GATE_SHADOW_CONFIDENCE_FIELD] = gate_shadow_confidence
        entry[GATE_SHADOW_AMMESSA_FIELD] = bool(gate_shadow_ammessa)
    # --- Gate off (referto §11quinquies): secondo segnale, indipendente.
    # Stesso pattern del primo: se manca, il record resta identico.
    if gate_off_confidence is not None:
        entry[GATE_OFF_CONFIDENCE_FIELD] = gate_off_confidence
        entry[GATE_OFF_AMMESSA_FIELD] = bool(gate_off_ammessa)
    # --- Top Mix di mercato (``topmix_mercato_v3``): campi OPZIONALI della riga
    # visibile. Una riga scritta da una versione precedente non li ha e resta
    # leggibile come prima: nessun campo esistente viene toccato.
    if mercato_fonte is not None:
        entry[MERCATO_FONTE_FIELD] = mercato_fonte
        entry[MERCATO_N_LIBRI_FIELD] = mercato_n_libri
        entry[PROB_MERCATO_FIELD] = prob_mercato
        entry[QUOTA_MERCATO_FIELD] = quota_mercato
        entry[ACCORDO_MODELLO_FIELD] = bool(accordo_modello)
        entry[PROB_MODELLO_FIELD] = prob_modello
        entry[QUOTE_LIVE_ISTANTE_FIELD] = quote_live_istante
        # Prima registrazione: all prima scrittura, i campi _prima sono
        # identici ai campi attuali. Nell'upsert, questi campi vengono
        # preservati quando la riga viene aggiornata (ultima registrazione
        # nei campi attuali, prima registrazione nei campi _prima).
        entry[PROB_MERCATO_PRIMA_FIELD] = prob_mercato
        entry[QUOTA_MERCATO_PRIMA_FIELD] = quota_mercato
        entry[PROB_MODELLO_PRIMA_FIELD] = prob_modello
        entry[ACCORDO_MODELLO_PRIMA_FIELD] = bool(accordo_modello)
        entry[QUOTE_LIVE_ISTANTE_PRIMA_FIELD] = quote_live_istante
    return entry


def save_prediction_entry(match_id, h, a, camp, giornata, match_date, pronostico, top3, prob, ris_attesi,
                          mercato_standard=None, origin=None, rank=None, kickoff_utc=None,
                          prob_poisson=None, prob_elo=None, elo_disponibile=None,
                          snapshot_sha=None,
                          gate_shadow_confidence=None, gate_shadow_ammessa=None,
                          gate_off_confidence=None, gate_off_ammessa=None,
                          model_variant=MODEL_VARIANT_CURRENT, selector_version=None,
                          prob_mercato=None, quota_mercato=None, mercato_fonte=None,
                          mercato_n_libri=None, accordo_modello=None, prob_modello=None,
                          quote_live_istante=None):
    """Scrive UNA previsione nel registro e dice cosa ha fatto.

    Due modifiche puntuali, entrambe richieste da
    ``audit/margini_migliorabili_topmix.md`` §7 (problemi ``dedup_match_id``,
    ``origin_collapsed``, ``schema_gaps``):

    - la chiave di unicita' non e' piu' il solo ``match_id`` ma
      ``(match_id, origin, selector_version, model_variant)``: se Analisi
      Rapida o Billy hanno salvato per primi, la riga Top Mix NON sparisce
      piu', e un ricalcolo aggiorna la propria previsione finche' non e' stata
      giudicata; la riga legacy di una partita non tocca mai quella current;
    - ``tipo`` non e' piu' derivato dal testo libero del pronostico: l'origine
      la passa il chiamante (``origin=ORIGIN_TOP_MIX`` ecc.) e il testo resta
      solo il fallback per i record legacy.

    ``prob_poisson``/``prob_elo``/``elo_disponibile`` salvano le DUE componenti
    della confidence: senza di esse il numero del registro non e' riconducibile
    a nessun vincolo del selettore (e il fallback Elo silenzioso resta
    invisibile). ``gate_shadow_confidence``/``gate_shadow_ammessa`` sono i campi
    della modalita' ombra del veto (referto §11quater): OPZIONALI, aggiunti al
    record SOLO quando ``gate_shadow_confidence`` non e' ``None``, senza
    toccare nessun campo gia' salvato. ``gate_off_confidence``/
    ``gate_off_ammessa`` sono il SECONDO segnale ombra (referto §11quinquies:
    gate assente, nessuno sconto), stesso pattern, indipendente dal primo.
    ``model_variant`` dice con quale motore Elo e' stata calcolata la riga
    (``current`` default, ``legacy`` per la seconda tabella del Top Mix).
    La forma del record e' costruita da ``build_prediction_entry``.
    Ritorna ``{"azione", "remoto", "record"}``.
    """
    preds = load_predictions()
    entry = build_prediction_entry(
        match_id, h, a, camp, giornata, match_date, pronostico, top3, prob, ris_attesi,
        mercato_standard=mercato_standard, origin=origin, rank=rank, kickoff_utc=kickoff_utc,
        prob_poisson=prob_poisson, prob_elo=prob_elo, elo_disponibile=elo_disponibile,
        snapshot_sha=snapshot_sha,
        gate_shadow_confidence=gate_shadow_confidence, gate_shadow_ammessa=gate_shadow_ammessa,
        gate_off_confidence=gate_off_confidence, gate_off_ammessa=gate_off_ammessa,
        model_variant=model_variant, selector_version=selector_version,
        prob_mercato=prob_mercato, quota_mercato=quota_mercato, mercato_fonte=mercato_fonte,
        mercato_n_libri=mercato_n_libri, accordo_modello=accordo_modello,
        prob_modello=prob_modello, quote_live_istante=quote_live_istante)
    preds, azione = upsert_prediction_entry(preds, entry)
    if azione in ("gia_graduata", "gia_presente_altra_versione"):
        # gia_graduata: la previsione e' gia' stata giudicata, NON si tocca.
        # gia_presente_altra_versione: la stessa (tabella, partita, mercato) c'e' gia'
        # con un'altra versione del selettore: NON si aggiunge una riga accanto.
        # In entrambi i casi il record nuovo non viene scritto.
        return {"azione": azione, "remoto": "nessuna_scrittura", "record": None}
    esito = save_predictions(preds)
    remoto = esito.get("remoto") if isinstance(esito, dict) else "ignoto"
    return {"azione": azione, "remoto": remoto, "record": entry}

def build_ombra_entry(riga, *, salvato_il=None, snapshot_sha=None):
    """Record del registro OMBRA per UNA partita candidata (da ``calcola_righe_top_mix(..., ombra=...)``).

    Stessa forma di una riga normale (``build_prediction_entry``) con origine
    ``top_mix_ombra`` e la versione della SUA famiglia (``SELECTOR_VERSION_OMBRA_BY_FAMIGLIA``:
    O/U 2.5 e GG/NG sono due righe distinte per la stessa partita), piu' i campi
    ``ombra_*``. Non c'e' rank ne' Elo: la riga non e' mai stata mostrata.
    """
    conf = riga["confidence"]
    entry = build_prediction_entry(
        riga["match_id"], riga["home"], riga["away"], riga["league"], riga["giornata"],
        format_date_italy(riga["utcDate"], "%d/%m/%Y %H:%M"),
        f"{riga['market']} - Top Mix ombra", [], round(conf * 100, 1), "",
        mercato_standard=riga["mercato_standard"], origin=ORIGIN_TOP_MIX_OMBRA, rank=None,
        kickoff_utc=riga["utcDate"], prob_poisson=round(riga["poisson"] * 100, 1),
        prob_elo=None, elo_disponibile=False, snapshot_sha=snapshot_sha,
        model_variant=MODEL_VARIANT_CURRENT, salvato_il=salvato_il,
        selector_version=SELECTOR_VERSION_OMBRA_BY_FAMIGLIA[riga["famiglia"]],
    )
    entry[OMBRA_FIELD] = True
    entry[OMBRA_FAMIGLIA_FIELD] = riga["famiglia"]
    entry[OMBRA_MERCATO_FIELD] = riga["market"]
    entry[OMBRA_CONFIDENCE_FIELD] = round(conf, 6)
    entry[OMBRA_AMMESSA_FIELD] = bool(riga["ammessa"])
    entry[OMBRA_SOGLIA_FIELD] = OMBRA_SOGLIA_TOTALI
    entry[OMBRA_VINCENTE_GLOBALE_FIELD] = bool(riga["vincente_globale"])
    entry[OMBRA_DATI_MANCANTI_FIELD] = bool(riga.get("dati_mancanti"))
    return entry


def build_ombra_modello_entry(riga, model_variant=MODEL_VARIANT_CURRENT, *,
                              salvato_il=None, snapshot_sha=None):
    """Record del registro OMBRA per la scelta 1X2 di UN motore (Drago o Legacy).

    Dalla PR delle quote live il Top Mix visibile e' quello del mercato: le
    scelte 1X2 dei due motori non spariscono, passano qui. La riga ha la STESSA
    forma di una riga del Registro (``build_prediction_entry``) con:

    * ``origin`` = ``top_mix_ombra`` e ``ombra`` = True (hash separato
      ``sm:registro:ombra``: le letture del Registro visibile non la caricano);
    * ``selector_version`` = ``SELECTOR_VERSION_OMBRA_1X2`` e
      ``model_variant`` = ``current``/``legacy``: la chiave di dedup
      ``(match_id, origin, selector_version, model_variant)`` separa le due
      righe della stessa partita, quindi Drago e Legacy non si sovrascrivono
      mai fra loro ne' con le righe ombra dei Totali (famiglie diverse);
    * ``ombra_famiglia`` = ``1x2``, ``ombra_confidence`` = la confidence del
      modello, ``ombra_ammessa`` = se superava la soglia del selettore
      (0,55 con Elo / 0,60 senza): il confronto col mercato resta possibile.

    Le regole anti-doppione sono quelle di sempre (``upsert_prediction_entries``:
    una riga gia' giudicata non si tocca, un ricalcolo della stessa previsione
    la sostituisce).
    """
    # ``argomenti_registro_top_mix`` porta gia' origine ombra e versione ombra.
    args, kwargs = argomenti_registro_top_mix(riga, model_variant=model_variant)
    entry = build_prediction_entry(*args, **kwargs, salvato_il=salvato_il,
                                   snapshot_sha=snapshot_sha)
    conf = riga.get("prob")
    elo_disp = bool(riga.get("elo_disponibile", True))
    soglia = 0.55 if elo_disp else 0.60
    entry[OMBRA_FIELD] = True
    entry[OMBRA_FAMIGLIA_FIELD] = OMBRA_FAMIGLIA_1X2
    entry[OMBRA_MERCATO_FIELD] = riga.get("market")
    entry[OMBRA_CONFIDENCE_FIELD] = (None if conf is None else round(float(conf), 6))
    entry[OMBRA_AMMESSA_FIELD] = bool(conf is not None and float(conf) >= soglia)
    entry[OMBRA_SOGLIA_FIELD] = soglia
    entry[OMBRA_DATI_MANCANTI_FIELD] = bool(riga.get("dati_mancanti"))
    return entry


def salva_registro_ombra(righe_ombra, righe_modello=None):
    """Scrive le righe ombra nel registro OMBRA. Ritorna un esito (mai le righe).

    Due famiglie di righe, un solo blocco di scrittura:

    * ``righe_ombra``: le scelte Totali (O/U 2.5 e GG/NG) di ogni candidata;
    * ``righe_modello``: ``{variante: [righe]}`` con le scelte 1X2 di Drago e
      Legacy, che dalla PR delle quote live non sono piu' il Top Mix visibile.

    Una lettura STRICT (se l'hash non si legge, non si scrive nulla: un ``[]``
    falso riscriverebbe l'ombra da zero), un upsert in blocco (le righe gia'
    giudicate non si toccano mai) e una scrittura che tocca solo le righe nuove
    o cambiate. Non produce nessun output visibile: il chiamante decide se e
    come segnalare un errore di scrittura.
    """
    from registry_store import esito_scrittura, load_ombra_rows, save_ombra_rows
    candidate = [r for r in (righe_ombra or []) if r.get("match_id") is not None]
    modello = []
    for variante, lista in (righe_modello or {}).items():
        modello.extend((variante, r) for r in (lista or []) if r.get("match_id") is not None)
    if not candidate and not modello:
        return {"remoto": "nessuna_riga", "azioni": {}}
    try:
        esistenti, _fonte = load_ombra_rows(strict=True)
    except Exception as e:
        logging.warning(f"Registro ombra non letto, nessuna scrittura: {e}")
        return {"remoto": "errore", "remoto_dettaglio": f"{type(e).__name__}: {e}"[:300], "azioni": {}}
    try:
        sha = snapshot_fingerprint(DATABASE_DIR)      # una volta sola per il blocco
        entries = [build_ombra_entry(r, snapshot_sha=sha) for r in candidate]
        entries += [build_ombra_modello_entry(r, model_variant=v, snapshot_sha=sha)
                    for v, r in modello]
        lista, azioni = upsert_prediction_entries(esistenti, entries)
    except Exception as e:
        # Il Top Mix visibile e' gia' salvato a questo punto: un errore dell'ombra
        # resta un errore dell'ombra, non deve far fallire il click.
        logging.warning(f"Registro ombra: costruzione delle righe fallita, nessuna scrittura: {e}")
        return {"remoto": "errore", "remoto_dettaglio": f"{type(e).__name__}: {e}"[:300], "azioni": {}}
    if not (azioni.get("aggiunta") or azioni.get("aggiornata")):
        return {"remoto": "nessuna_scrittura", "azioni": azioni}
    try:
        esito = esito_scrittura(save_ombra_rows(lista))
    except Exception as e:
        logging.warning(f"Scrittura del registro ombra fallita: {e}")
        return {"remoto": "errore", "remoto_dettaglio": f"{type(e).__name__}: {e}"[:300], "azioni": azioni}
    esito["azioni"] = azioni
    if esito.get("remoto") not in ("ok", "disattivato"):
        logging.warning(f"Registro ombra: scrittura non riuscita ({esito.get('remoto_dettaglio', esito.get('remoto'))})")
    return esito


def _applica_esiti(preds, api_key, cache=None):
    """Grading delle righe ancora in attesa: UNA logica per il Registro vivo e per l'ombra.

    Modifica ``preds`` sul posto e ritorna ``(aggiornate, pending)``. ``cache`` e'
    il dizionario delle risposte per giornata condiviso fra le due passate
    (visibile e ombra): un solo giro di chiamate a football-data per giornata.
    """
    if cache is None:
        cache = {}
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
                # Grading UNICO ( prediction_registry.esito_mercato ): prima il
                # ramo per match_id graduava 14 mercati e il loop per giornata
                # solo 7, quindi un OVER_1.5/1X/X2/12 restava ⏳ per sempre.
                p["esito"] = esito_mercato(p.get("mercato_standard", ""), gh, ga) or "⏳"
                aggiornate += 1
            except Exception as e:
                logging.warning(f"Aggiornamento risultato per match_id {m_id} fallito: {e}")

    # --- Loop normale per giornata > 0 ---
    for (camp, giornata), camp_pending in grouped.items():
        comp = LEAGUE_CODE_MAP.get(camp)
        if not comp:
            continue
        chiave_cache = ("giornata", comp, giornata)
        if chiave_cache in cache:
            risultati_api = cache[chiave_cache]
        else:
            try:
                r = requests.get(
                    f"https://api.football-data.org/v4/competitions/{comp}/matches",
                    headers={"X-Auth-Token": api_key},
                    params={"matchday": giornata, "status": "FINISHED"},
                    timeout=15
                )
                if r.status_code != 200:
                    cache[chiave_cache] = None
                    continue
                risultati_api = {m["id"]: m for m in r.json().get("matches", [])}
                cache[chiave_cache] = risultati_api
            except Exception as e:
                # Non e' un `except: continue` muto: un fallback sul grading e'
                # un giorno di risultati che non arriva, e va visto.
                logging.warning(f"Aggiornamento risultati {camp} giornata {giornata} fallito: {e}")
                cache[chiave_cache] = None
                continue
        if risultati_api is None:
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
            # Stessa tabella del ramo per match_id: nessun mercato "non graduato
            # perche' salvato da un altro percorso".
            p["esito"] = esito_mercato(p.get("mercato_standard", ""), gh, ga) or "⏳"
            aggiornate += 1
    return aggiornate, len(pending)


def aggiorna_risultati_reali(api_key):
    """Grading del Registro vivo (e, nello stesso giro, di quello ombra).

    Ritorna ``(aggiornate, pending)`` del Registro visibile, come sempre. Il
    registro ombra viene valutato con le STESSE regole e le STESSE risposte HTTP
    (cache condivisa): un suo guasto non fa fallire il grading visibile, viene
    solo registrato nel log.
    """
    cache = {}
    preds = load_predictions()
    aggiornate, pending = _applica_esiti(preds, api_key, cache)
    if aggiornate > 0:
        save_predictions(preds)
    try:
        aggiorna_esiti_ombra(api_key, cache)
    except Exception as e:
        logging.warning(f"Grading del registro ombra non riuscito (il Registro visibile e' a posto): {e}")
    return aggiornate, pending


def aggiorna_esiti_ombra(api_key, cache=None):
    """Grading del registro OMBRA: stesse regole delle righe normali. Ritorna ``(aggiornate, pending)``.

    Lettura strict: con un errore di rete non scrive nulla. Scrive solo le righe
    giudicate in questo giro (``HSET`` diff).
    """
    from registry_store import esito_scrittura, load_ombra_rows, save_ombra_rows
    righe, _fonte = load_ombra_rows(strict=True)
    aggiornate, pending = _applica_esiti(righe, api_key, cache)
    if aggiornate > 0:
        esito = esito_scrittura(save_ombra_rows(righe))
        if esito.get("remoto") not in ("ok", "disattivato"):
            raise RuntimeError(f"scrittura ombra non riuscita: {esito.get('remoto_dettaglio', esito.get('remoto'))}")
    return aggiornate, pending

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


def _league_mean_gate(xg_data):
    """Medie di lega con gate di sanita', su un qualsiasi dizionario
    ``{squadra: {xG_avg, xGA_avg, ...}}``. Ritorna ``(mean_xg, mean_xga)``
    oppure ``(None, None)`` se il gate non passa.

    Logica UNICA (>=10 squadre con valori finiti e positivi; medie nel range
    di sanita' 0.5-5.0): usata sia per l'ancora di shrinkage della fonte
    F_season -- che deve essere derivata dai dati F_season stessi (fedele
    all'audit) e non dal file xG statico -- sia sul file xG stagionale dentro
    get_league_engine. Prima il secondo caso era una copia incollata, con il
    rischio di far divergere le due soglie di sanita'.
    """
    if not xg_data:
        return None, None
    lx = [v['xG_avg'] for v in xg_data.values()
          if isinstance(v, dict) and isinstance(v.get('xG_avg'), (int, float))
          and np.isfinite(v['xG_avg']) and v['xG_avg'] > 0]
    lxa = [v['xGA_avg'] for v in xg_data.values()
           if isinstance(v, dict) and isinstance(v.get('xGA_avg'), (int, float))
           and np.isfinite(v['xGA_avg']) and v['xGA_avg'] > 0]
    if len(lx) >= 10 and len(lxa) >= 10:
        mx, mxa = float(np.mean(lx)), float(np.mean(lxa))
        if 0.5 < mx < 5.0 and 0.5 < mxa < 5.0:
            return mx, mxa
    return None, None


# --- ENSEMBLE POISSON+ELO SULL'1X2 ---
# Peso della componente POISSON: la probabilita' finale e'
#   0.25 * Poisson + 0.75 * Elo.
# Il vecchio nome ELO_ENSEMBLE_W era fuorviante proprio perche' indicava il
# peso opposto. L'alias resta temporaneamente per gli import esterni, ma il
# codice di produzione usa solo il nome non ambiguo. Questa rinomina non cambia
# formule o numeri; l'eventuale ritaratura sul motore Elo corrente e' un audit
# separato.
# L'ensemble tocca SOLO le probabilita' 1X2 finali: stats del motore
# (att/def/att0/def0/att0_pure/def0_pure), Totali (O/U, GG/NG) e la
# funzione get_full_poisson_two_heads restano bit-identici.
POISSON_1X2_WEIGHT = 0.25
# Compatibilita' temporanea: non usare in nuovo codice.
ELO_ENSEMBLE_W = POISSON_1X2_WEIGHT


def blend_elo_into_1x2(m, home, away, league, w=POISSON_1X2_WEIGHT, elo_probs=None, elo_disponibile=True, season=None):
    """Ritorna una COPIA del dizionario Poisson con l'1X2 nella forma
    ``w*Poisson + (1-w)*Elo`` (peso Poisson = ``POISSON_1X2_WEIGHT``, valore
    attualmente in produzione). I Totali (u15/u25/u35/gg) e ogni
    altra chiave passano invariati. Se l'Elo non e' disponibile (errore del
    motore) ritorna il Poisson puro bit-identico: il degrado e' sempre
    controllato verso il comportamento pre-modifica.

    ``elo_probs`` serve al **secondo motore** (Analisi Rapida a due modelli,
    come il Top Mix): se dato, si usa quello invece di chiamare
    ``predict_elo_probs``. Con ``None`` il comportamento e' quello di sempre.
    ``elo_disponibile=False`` dice che QUEL motore non ha dato un Elo: si
    ritorna il Poisson puro invece di ricadere sull'Elo dell'altro motore.
    Senza questa distinzione la riga "legacy" senza Elo legacy verrebbe
    calcolata con l'Elo ATTUALE e sembrerebbe un risultato del motore legacy.

    ``season`` e' la stagione della partita (anno di inizio, da
    ``season_calendar``): viene passata a ``predict_elo_probs`` quando serve
    il seed. I chiamanti di produzione la passano sempre esplicitamente.
    """
    out = dict(m)
    if not elo_disponibile:
        return out
    try:
        elo_p = predict_elo_probs(home, away, league, season=season) if elo_probs is None else elo_probs
    except Exception:
        return out
    for k in ("1", "X", "2"):
        try:
            e = float(elo_p[k])
        except (KeyError, TypeError, ValueError):
            return dict(m)
        if not np.isfinite(e) or e < 0:
            return dict(m)
        out[k] = w * float(m[k]) + (1.0 - w) * e
    return out


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
        # Stesso gate di _league_mean_gate: prima era riscritto qui a mano
        # (due copie della medesima soglia di sanita', che potevano divergere:
        # audit/margini_migliorabili_topmix.md §1 riga 16).
        league_xg, league_xga = _league_mean_gate(xg_data)

    # --- FONTE POINT-IN-TIME PER LA TESTA TOTALI (F_season) ---
    # att0_pure/def0_pure (testa O/U2.5 e GG/NG) leggono le medie xG della
    # SOLA stagione in corso al cutoff (F_season: point-in-time, no leakage,
    # nessuna componente cross-season). Scelta validata in audit:
    # audit/results/pt19_cap_vs_fseason_clean.md — F_season mai peggiore e
    # migliore in aggregato della finestra trailing multi-stagione con tetto
    # 400gg (PT19_CAP), e fallback rate 2.74% vs 32.65% dello snapshot
    # statico; la finestra trailing pescava partite "stantie" nei gap da
    # retrocessione (verificati 453-813 giorni senza partite nella lega).
    # Squadre senza partite nella stagione in corso sono "dato insufficiente":
    # per loro il ramo qui sotto usa il fallback gol con shrinkage, lo stesso
    # dei casi a campione zero. La testa 1X2 (att/def/att0/def0) NON usa
    # questa fonte: resta sulla sorgente stagionale di get_understat_xg(),
    # invariata (1X2 bit-identico, test permanente
    # SoccerMath/test_pt19_totali_invariance.py).
    # Se il lookup non e' disponibile (archivio assente, errore) il
    # comportamento torna ESATTAMENTE quello precedente alla modifica.
    # L'ancora di shrinkage e' la media di lega DERIVATA DAL DIZIONARIO
    # F_season stesso (gate _league_mean_gate, fedele all'audit), non quella
    # del file xG statico: la fonte resta interamente point-in-time anche se
    # lo snapshot stagionale fosse stantio. Il lookup non dipende dal gate
    # del file xG (sorgenti indipendenti).
    fs_lookup = {}
    fs_anchor_xg = None
    fs_anchor_xga = None
    fs_active = False
    try:
        fs_lookup = season_point_in_time_averages(
            camp_key, cutoff=datetime.now(timezone.utc),
        ).averages
        fs_anchor_xg, fs_anchor_xga = _league_mean_gate(fs_lookup)
        fs_active = fs_anchor_xg is not None
    except Exception as e:
        logging.warning(f"Lookup point-in-time (F_season) non disponibile per {camp_key}: {e}")
        fs_lookup = {}

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
        # --- Fallback gol dal DB: rapporto pooled con shrinkage ---
        # Gol osservati e gol attesi da una squadra "media di lega"
        # (media casa in casa, media trasferta in trasferta), aggregati
        # su entrambi i ruoli: un solo ratio stabile invece della media
        # di ratio casa/trasferta separati (che con 1-2 partite e' rumore).
        # Calcolato sempre: serve alla testa 1X2 quando manca l'xG E alla
        # testa Totali quando il dato point-in-time e' insufficiente.
        h_gf = h_h['FTHG'].dropna(); a_gf = a_h['FTAG'].dropna()
        h_ga = h_h['FTAG'].dropna(); a_ga = a_h['FTHG'].dropna()
        n_played = len(h_gf) + len(a_gf)
        gf = float(h_gf.sum() + a_gf.sum())
        ga = float(h_ga.sum() + a_ga.sum())
        exp_gf = float(avg_h * len(h_gf) + avg_a * len(a_gf))
        exp_ga = float(avg_a * len(h_ga) + avg_h * len(a_ga))
        fb_att = _shrunk_ratio(gf, exp_gf, n_played)
        fb_defe = _shrunk_ratio(ga, exp_ga, n_played)
        if not use_xg:
            att = fb_att
            defe = fb_defe

        # --- Sanitizzazione finale: nessun ratio non-finito o <= 0 puo'
        # raggiungere le lambda (att/def == 0 => lambda 0 => NG 99.8%).
        if not (np.isfinite(att) and att > 0):
            att = 1.0
        if not (np.isfinite(defe) and defe > 0):
            defe = 1.0

        # Baseline pura di lungo periodo, SENZA forma: alimenta la testa
        # Totali (O/U2.5 e GG/NG). Evidenza empirica su 5 campionati
        # (40 confronti, vedi audit/diagnose_form_totali.py e
        # audit/results/form_totali_diagnosis.md): rimuovere la forma a 5
        # gare dai totali abbassa il Brier O/U2.5 da 0.2488 a 0.2401 e GG/NG
        # da 0.2584 a 0.2496.
        # Fonte: lookup point-in-time F_season (medie xG della sola stagione
        # in corso al cutoff, v. sopra; ancora di shrinkage = media di lega
        # derivata dal dizionario F_season). Squadra senza partite nella
        # stagione in corso = "dato insufficiente": stesso trattamento del
        # ramo a campione zero (fallback gol con shrinkage verso la media di
        # lega). Se il lookup non e' disponibile, la baseline resta identica
        # a quella precedente a questa modifica.
        use_fs = False
        if fs_active:
            fs_rec = fs_lookup.get(t)
            if isinstance(fs_rec, dict):
                try:
                    fs_xg_v = float(fs_rec.get('xG_avg'))
                    fs_xga_v = float(fs_rec.get('xGA_avg'))
                    fs_n = fs_rec.get('matches')
                    fs_ok = (np.isfinite(fs_xg_v) and np.isfinite(fs_xga_v)
                             and fs_xg_v >= 0 and fs_xga_v >= 0
                             and isinstance(fs_n, (int, float))
                             and not isinstance(fs_n, bool)
                             and np.isfinite(float(fs_n)) and float(fs_n) > 0)
                except (TypeError, ValueError):
                    fs_ok = False
                if fs_ok:
                    att0_pure = _shrunk_ratio(fs_xg_v, fs_anchor_xg, fs_n)
                    def0_pure = _shrunk_ratio(fs_xga_v, fs_anchor_xga, fs_n)
                    use_fs = True
        if not use_fs:
            if fs_active:
                # dato insufficiente nella stagione in corso: ramo a campione zero
                att0_pure = fb_att
                def0_pure = fb_defe
            else:
                # lookup non disponibile: comportamento pre-modifica
                att0_pure = att
                def0_pure = defe
        if not (np.isfinite(att0_pure) and att0_pure > 0):
            att0_pure = 1.0
        if not (np.isfinite(def0_pure) and def0_pure > 0):
            def0_pure = 1.0

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
            # [solo UI] shortName grezzi ("Atleti", "Barça") tradotti per la
            # stringa mostrata; nessun uso come chiave qui.
            risultati.append(f"{display_name(match['homeTeam'].get('shortName','?'))} {gh}-{ga} {display_name(match['awayTeam'].get('shortName','?'))} ({esito})")
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


def seleziona_riga_top_mix(m, elo_probs=None, elo_disponibile=True, home=None, away=None):
    """Riga Top Mix di UNA partita: argmax sui 1X2, blend, soglie e veto.

    Dalla PR che toglie i Totali dal Top Mix, la selezione VISIBILE sceglie solo
    fra Vittoria casa, Pareggio e Vittoria trasferta: Over/Under 2.5 e GG/NG non
    entrano mai nella tabella. Il motivo e' misurato (vedi la sezione "Totali" di
    ``prediction_registry.py``: BSS del modello sull'O/U 2.5 ~0,8% contro ~3,4%
    della chiusura di mercato; GG/NG sotto il base rate; Totali = 39,7% delle
    righe ammesse). Le partite che prima vincevano un Totale vengono RIVALUTATE
    sui soli 1X2: se la miglior scelta 1X2 supera la sua soglia entra con la sua
    riga, altrimenti non entra. Soglie (0,55 con Elo, 0,60 senza), blend e veto
    restano quelli di prima.

    Funzione PURA (nessuna richiesta HTTP, nessuna cache, nessun logging,
    nessuna scrittura nel registro): riceve solo i dati gia' calcolati per la
    partita e ritorna il dizionario della riga, oppure ``None`` se la partita
    va scartata. I campi legati al match (league, giornata, home, away,
    match_id, utcDate, rank) li aggiunge il chiamante.

    Perche' esiste: era il corpo di ``fetch_and_calc_top_mix``, cioe' l'unica
    parte di produzione senza test di comportamento -- esisteva solo la
    trascrizione ``apply_selector_A`` in ``audit/reconstruct_topmix_match.py``,
    allineata da un guard testuale sull'AST (referto
    ``audit/margini_migliorabili_topmix.md`` §4 punto 7 e §9 punto 2). Da qui il
    guard diventa un confronto di comportamento
    (``SoccerMath/test_topmix_selector_parity.py``). L'harness di audit RESTA una
    sua trascrizione, di proposito: e' il confronto esterno che tiene in vita la
    coerenza dei numeri, e unire le due copie lo distruggerebbe.

    Parametri
    ---------
    m : dict
        Output di ``get_full_poisson_two_heads``: chiavi "1", "X", "2", "u25", "gg".
        Qui si leggono solo "1", "X", "2": i Totali sono nel registro ombra.
    elo_probs : dict | None
        Output di ``predict_elo_probs`` (chiavi "1", "X", "2"); ``None`` se l'Elo
        non e' disponibile.
    elo_disponibile : bool
        False quando ``predict_elo_probs`` ha fallito: la confidence e' allora
        Poisson puro e vale la soglia 0,60, non 0,55.
    home, away : str
        Nomi (``shortName`` API) usati per le etichette "Vittoria {squadra}" e
        per il codice mercato.

    Ritorna ``dict | None`` con chiavi ``market``, ``mercato_standard``,
    ``prob``, ``prob_val``, ``poisson``, ``elo``, ``elo_disponibile``.
    """
    # Solo i tre 1X2, nello stesso ordine di prima: con lo stesso ordine di dict
    # lo spareggio fra due 1X2 uguali resta quello di sempre (casa, X, trasferta).
    mercati = {
        f"Vittoria {home}": m["1"], "Pareggio": m["X"], f"Vittoria {away}": m["2"],
    }
    best_mkt = max(mercati, key=mercati.get)
    poisson_prob = mercati[best_mkt]

    # Elo agreement (solo per 1X2). Con elo_probs assente/malformato la riga
    # resta Poisson puro: come il vecchio `except` che avvolgeva l'accesso.
    elo_prob = poisson_prob  # fallback
    if elo_disponibile:
        chiave_elo = None
        if best_mkt == f"Vittoria {home}":
            chiave_elo = "1"
        elif best_mkt == f"Vittoria {away}":
            chiave_elo = "2"
        elif best_mkt == "Pareggio":
            chiave_elo = "X"
        if chiave_elo is not None:
            valore = (elo_probs or {}).get(chiave_elo)
            if isinstance(valore, (int, float)) and not isinstance(valore, bool):
                elo_prob = valore
            else:
                elo_disponibile = False

    # Confidence: blend 1X2 Poisson/Elo (media pesata, stesso peso dell'ensemble
    # POISSON_1X2_WEIGHT, quindi la confidence coincide con la probabilita' 1X2
    # ensemble usata ovunque). Senza Elo: solo Poisson, soglia piu' alta.
    if not elo_disponibile:
        confidence = poisson_prob
        min_conf = 0.60
    else:
        confidence = POISSON_1X2_WEIGHT * poisson_prob + (1 - POISSON_1X2_WEIGHT) * elo_prob
        min_conf = 0.55

    # Filtro qualità: confidence minima e nessun disaccordo estremo
    if confidence >= min_conf and abs(poisson_prob - elo_prob) < 0.25:
        return {
            "market": best_mkt,
            "mercato_standard": codice_mercato_selezionato(best_mkt, home, away),
            "prob": confidence, "prob_val": round(confidence * 100, 1),
            "poisson": round(poisson_prob * 100, 1),
            "elo": round(elo_prob * 100, 1),
            # False SOLO se predict_elo_probs ha fallito: UI e registro
            # devono poter distinguere "Elo d'accordo" da "Elo assente".
            "elo_disponibile": elo_disponibile,
        }
    return None


def seleziona_riga_top_mix_mercato(prob_mercato, odds_mercato=None, prob_modello=None,
                                   fonte=None, n_libri=None, home=None, away=None):
    """Riga Top Mix di UNA partita decisa dal MERCATO (selettore ``topmix_mercato_v3``).

    Funzione PURA (stessi divieti di ``seleziona_riga_top_mix``: niente HTTP,
    cache, logging o scritture): riceve probabilita' e quote gia' calcolate e
    ritorna il dizionario della riga, oppure ``None`` se la partita non entra.

    Regola (PR #49, ``audit/results/onex2_market_test.md`` §4 e §4d):

    * esito = argmax delle tre probabilita' di mercato, nell'ordine 1, X, 2
      (primo massimo: lo stesso spareggio di ``max()`` su dict e di
      ``np.argmax`` usato dall'audit, cosi' i numeri del replay coincidono);
    * ammissione: probabilita' di mercato >= ``SOGLIA_TOPMIX_MERCATO`` (0,55).
      E' l'unica soglia della riga: il veto di produzione |Poisson-Elo| < 0,25
      NON si applica, perche' la scelta e' del mercato, che non ha Elo;
    * ``accordo`` (colonna "d'accordo"): modello e mercato sullo STESSO esito
      ed entrambi >= ``SOGLIA_ACCORDO`` (0,55). Senza probabilita' del modello
      l'accordo e' False: un'assenza non e' un consenso, come per l'Elo.

    Perche' il mercato decide e il modello resta accanto (numeri PR #49):
    scelte del mercato 1302 / 67,5%; del modello 1479 / 62,6%; del modello CON
    accordo 1144 / 68,2%; del modello SENZA accordo 335 / 43,6%. Il modello
    serve soprattutto a scartare, non a scegliere.

    NESSUN FILTRO SULLE QUOTE BASSE: una quota 1,10 resta in tabella se il
    mercato la da' come esito piu' probabile. La tabella individua le partite
    piu' probabili; scegliere una quota minima resta una decisione dell'utente
    (il calcolatore di multipla mostra l'edge, non lo giudica).

    Parametri
    ---------
    prob_mercato : dict | None
        Probabilita' de-vigate 1/X/2 (``market_odds.probabilita_mercato``).
    odds_mercato : dict | None
        Quote decimali della STESSA fonte delle probabilita'.
    prob_modello : dict | None
        Probabilita' blend del Drago (0,25 Poisson + 0,75 Elo) per 1/X/2, o
        ``None`` se il modello non e' disponibile per questa partita.
    fonte, n_libri : str | None, int | None
        ``pinnacle`` / ``media_libri`` e quanti libri hanno una terna valida:
        la riserva sulla media deve essere leggibile riga per riga.
    home, away : str
        Nomi display per le etichette "Vittoria {squadra}".

    Ritorna ``dict | None`` con ``market``, ``mercato_standard``, ``esito``,
    ``prob`` (probabilita' di mercato), ``prob_val``, ``quota``,
    ``prob_modello``, ``prob_modello_val``, ``accordo``, ``fonte``, ``n_libri``.
    """
    if not isinstance(prob_mercato, dict):
        return None
    valori = []
    for esito in ESITI_MERCATO:
        v = prob_mercato.get(esito)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
            return None
        valori.append(float(v))

    # argmax con spareggio sul primo massimo (ordine 1, X, 2)
    k = 0
    for i in range(1, len(valori)):
        if valori[i] > valori[k]:
            k = i
    esito = ESITI_MERCATO[k]
    prob = valori[k]
    if prob < SOGLIA_TOPMIX_MERCATO:
        return None

    quota = None
    if isinstance(odds_mercato, dict):
        q = odds_mercato.get(esito)
        if not isinstance(q, bool) and isinstance(q, (int, float)) and math.isfinite(float(q)) \
                and float(q) > 1.0:
            quota = float(q)

    # Probabilita' del modello (Drago) per lo STESSO esito e segnale di accordo.
    p_modello = None
    if isinstance(prob_modello, dict):
        v = prob_modello.get(esito)
        if not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(float(v)):
            p_modello = float(v)
    accordo = False
    if p_modello is not None:
        # stesso esito = argmax del modello uguale a quello del mercato
        m_valori = []
        for e in ESITI_MERCATO:
            mv = prob_modello.get(e)
            m_valori.append(float(mv) if (not isinstance(mv, bool)
                                          and isinstance(mv, (int, float))
                                          and math.isfinite(float(mv))) else -1.0)
        km = 0
        for i in range(1, len(m_valori)):
            if m_valori[i] > m_valori[km]:
                km = i
        stesso_esito = ESITI_MERCATO[km] == esito
        accordo = bool(stesso_esito and p_modello >= SOGLIA_ACCORDO
                       and prob >= SOGLIA_ACCORDO)

    if esito == "1":
        market = f"Vittoria {home}"
    elif esito == "2":
        market = f"Vittoria {away}"
    else:
        market = "Pareggio"

    return {
        "market": market,
        "mercato_standard": esito,
        "esito": esito,
        "prob": prob,
        "prob_val": round(prob * 100, 1),
        "quota": quota,
        "prob_modello": p_modello,
        "prob_modello_val": (None if p_modello is None else round(p_modello * 100, 1)),
        "accordo": accordo,
        "fonte": fonte,
        "n_libri": n_libri,
    }


def riga_top_mix_shadow(m, elo_probs=None, elo_disponibile=True, home=None, away=None):
    """Versione OMBRA del selettore per UNA candidate: gate come penalita' continua.

    Referto ``audit/margini_migliorabili_topmix.md`` §9 punto 4 e §11quater.
    Il veto di produzione ``abs(poisson_prob - elo_prob) < 0.25`` (che in
    ``seleziona_riga_top_mix`` fa sparire l'intera partita) qui NON scarta:
    al suo posto la confidence viene scalata dal fattore continuo
    ``0.25 / (0.25 + d)`` (``prediction_registry.gate_shadow_confidence``) e
    l'ammissione ombra e' il SOLO confronto ``conf_shadow >= min_conf``: i due
    filtri di oggi (soglia + veto) collassano in uno, senza nessun secondo
    taglio secco a un'altra soglia.

    Funzione PURA (stessi divieti di ``seleziona_riga_top_mix``: niente HTTP,
    cache, logging o scritture) e speculare alla sua matematica di selezione:
    ripercorre le stesse righe (argmax sui 1X2, stesso blend, stessa estrazione
    Elo, stesse soglie) SOLO per ricavare ``confidence`` e ``d`` su cui applicare
    la penalita'. La specularita' e' intenzionale e tenuta viva dal test di
    coerenza ``test_topmix_shadow_gate.py`` (sulle stesse griglie della parita'
    il lato reale di questa funzione deve coincidere con l'output di
    ``seleziona_riga_top_mix``); il selettore reale NON viene toccato.

    Ritorna SEMPRE un dict (mai ``None``): la candidate non viene mai scartata
    qui, l'ammissione ombra viaggia nel campo ``ammessa_shadow``. Chiavi:
    ``market``, ``mercato_standard``, ``prob`` (confidence REALE), ``prob_val``,
    ``poisson``, ``elo``, ``elo_disponibile``, ``min_conf``, ``disaccordo``
    (d = |P-E|), ``conf_shadow`` (confidence penalizzata), ``ammessa_shadow``
    (``conf_shadow >= min_conf``) e ``gate_avrebbe_scartato`` (``d >= 0.25``).
    Accanto, il SECONDO segnale (referto §11quinquies): ``conf_off`` (identita':
    nessuno sconto) e ``ammessa_off`` (``conf_off >= min_conf``).
    """
    # Copia speculare della selezione reale (vedi docstring): stessa argmax sui
    # 1X2, stesso blend, stesse soglie -- MAI il veto.
    mercati = {
        f"Vittoria {home}": m["1"], "Pareggio": m["X"], f"Vittoria {away}": m["2"],
    }
    best_mkt = max(mercati, key=mercati.get)
    poisson_prob = mercati[best_mkt]

    elo_prob = poisson_prob  # fallback, come nel selettore reale
    if elo_disponibile:
        chiave_elo = None
        if best_mkt == f"Vittoria {home}":
            chiave_elo = "1"
        elif best_mkt == f"Vittoria {away}":
            chiave_elo = "2"
        elif best_mkt == "Pareggio":
            chiave_elo = "X"
        if chiave_elo is not None:
            valore = (elo_probs or {}).get(chiave_elo)
            if isinstance(valore, (int, float)) and not isinstance(valore, bool):
                elo_prob = valore
            else:
                elo_disponibile = False

    if not elo_disponibile:
        confidence = poisson_prob
        min_conf = 0.60
    else:
        confidence = POISSON_1X2_WEIGHT * poisson_prob + (1 - POISSON_1X2_WEIGHT) * elo_prob
        min_conf = 0.55

    disaccordo = abs(poisson_prob - elo_prob)
    conf_shadow = gate_shadow_confidence(confidence, disaccordo)
    conf_off = gate_off_confidence(confidence, disaccordo)
    return {
        "market": best_mkt,
        "mercato_standard": codice_mercato_selezionato(best_mkt, home, away),
        "prob": confidence, "prob_val": round(confidence * 100, 1),
        "poisson": round(poisson_prob * 100, 1),
        "elo": round(elo_prob * 100, 1),
        "elo_disponibile": elo_disponibile,
        "min_conf": min_conf,
        "disaccordo": disaccordo,
        "conf_shadow": conf_shadow,
        "ammessa_shadow": bool(conf_shadow is not None and conf_shadow >= min_conf),
        "gate_avrebbe_scartato": disaccordo >= 0.25,
        "conf_off": conf_off,
        "ammessa_off": bool(conf_off is not None and conf_off >= min_conf),
    }


def righe_ombra_totali(m, home=None, away=None):
    """Scelte Totali ombra per UNA partita candidata: DUE righe, mai mostrate.

    Il registro ombra salva, per ogni candidata, due scelte separate (round 2):
    * ``ou25``: il piu' probabile fra Over 2.5 e Under 2.5;
    * ``ggng``: il piu' probabile fra GG e NG.
    Ciascuna con la sua ``confidence`` (probabilita' Poisson del mercato: i Totali non
    usano l'Elo, e il veto non li scarta mai) e la sua ammissione a ``OMBRA_SOGLIA_TOTALI``
    (0,60, bordo incluso).

    ``vincente_globale`` (per ciascuna famiglia): il selettore a sette mercati di allora
    l'avrebbe davvero MOSTRATA, cioe' il suo argmax su tutti e sette i mercati e' proprio
    quella scelta, e la scelta e' ammessa. Serve a separare nel registro le scelte che il
    vecchio Top Mix mostrava da quelle rimaste candidate sotto soglia o sotto un 1X2.

    Funzione PURA: nessuna richiesta HTTP, nessuna cache, nessun logging, nessuna
    scrittura. Ritorna SEMPRE una lista di due dict (mai ``None``).
    """
    tutti_i_totali = {"Over 2.5": 1 - m["u25"], "Under 2.5": m["u25"],
                      "GG": m["gg"], "NG": 1 - m["gg"]}
    sette = {
        f"Vittoria {home}": m["1"], "Pareggio": m["X"], f"Vittoria {away}": m["2"],
        **tutti_i_totali,
    }
    best_globale = max(sette, key=sette.get)
    famiglie = (
        (OMBRA_FAMIGLIA_OU25, {"Over 2.5": tutti_i_totali["Over 2.5"], "Under 2.5": tutti_i_totali["Under 2.5"]}),
        (OMBRA_FAMIGLIA_GGNG, {"GG": tutti_i_totali["GG"], "NG": tutti_i_totali["NG"]}),
    )
    out = []
    for famiglia, mercati in famiglie:
        best = max(mercati, key=mercati.get)
        confidence = mercati[best]
        ammessa = confidence >= OMBRA_SOGLIA_TOTALI
        out.append({
            "famiglia": famiglia,
            "market": best,
            "mercato_standard": codice_mercato_selezionato(best, home, away),
            "confidence": confidence,
            "poisson": confidence,
            "ammessa": bool(ammessa),
            "vincente_globale": bool(ammessa and best_globale == best),
        })
    return out


def _riga_ombra(league, match, h_disp, a_disp, riga, dati_mancanti=None):
    """Riga candidate del registro ombra: campi del match + scelta Totali ombra.

    E' il canale verso ``build_ombra_entry``: non entra mai in una tabella visibile.
    """
    return {
        "league": league, "giornata": match["matchday"],
        "home": h_disp, "away": a_disp,
        "match_id": match.get("id"), "utcDate": match["utcDate"],
        "market": riga["market"], "mercato_standard": riga["mercato_standard"],
        "confidence": riga["confidence"], "poisson": riga["poisson"],
        "ammessa": riga["ammessa"], "vincente_globale": riga["vincente_globale"],
        "famiglia": riga["famiglia"],
        "dati_mancanti": bool(dati_mancanti),
    }


def _riga_top_mix(league, match, h_disp, a_disp, riga, dati_mancanti=None):
    """Riga del Top Mix: campi del match + campi del selettore (stesso ordine di prima).

    ``dati_mancanti`` (caso b): squadre del roster senza statistiche nel motore,
    per le quali il Poisson ha usato le statistiche di default att=1.0 def=1.0.
    La chiave compare SOLO quando non e' vuota: una riga senza dati mancanti
    resta identica a prima, chiave per chiave.
    """
    out = {
        "league": league, "giornata": match['matchday'],
        "home": h_disp, "away": a_disp, "match_id": match.get("id"),
        "utcDate": match['utcDate'],
        "market": riga["market"],
        "mercato_standard": riga["mercato_standard"],
        "prob": riga["prob"], "prob_val": riga["prob_val"],
        "poisson": riga["poisson"], "elo": riga["elo"],
        "elo_disponibile": riga["elo_disponibile"],
        "rank": None,
    }
    if dati_mancanti:
        out["dati_mancanti"] = [pulito for _grezzo, pulito in dati_mancanti]
    return out


def _riga_top_mix_mercato(league, match, h_disp, a_disp, riga, quote_istante=None,
                          dati_mancanti=None):
    """Riga del Top Mix di MERCATO: campi del match + campi del selettore.

    Stessa forma di ``_riga_top_mix`` piu' i campi che rendono la scelta del
    mercato verificabile riga per riga: ``esito`` (1/X/2), ``quota`` (della
    stessa fonte della probabilita'), ``prob_modello`` (Drago sullo stesso
    esito), ``accordo``, ``fonte`` e ``n_libri`` (Pinnacle o media dei libri),
    ``quote_live_istante`` (quando il workflow ha scaricato le quote).

    ``dati_mancanti`` ha lo stesso significato di ``_riga_top_mix`` (stats di
    default per una squadra del roster senza statistiche): qui riguarda solo la
    colonna del modello, perche' la scelta e' del mercato.
    """
    out = {
        "league": league, "giornata": match['matchday'],
        "home": h_disp, "away": a_disp, "match_id": match.get("id"),
        "utcDate": match['utcDate'],
        "market": riga["market"],
        "mercato_standard": riga["mercato_standard"],
        "esito": riga["esito"],
        "prob": riga["prob"], "prob_val": riga["prob_val"],
        "quota": riga["quota"],
        "prob_modello": riga["prob_modello"],
        "prob_modello_val": riga["prob_modello_val"],
        "accordo": bool(riga["accordo"]),
        "fonte": riga["fonte"], "n_libri": riga["n_libri"],
        "quote_live_istante": quote_istante,
        "rank": None,
    }
    if dati_mancanti:
        out["dati_mancanti"] = [pulito for _grezzo, pulito in dati_mancanti]
    return out


def calcola_righe_top_mix(league, matches, engine, ombra=None, quote=None):
    """Righe Top Mix delle partite ``matches`` di una lega.

    Per ogni partita: stesso Poisson a due teste, poi il selettore puro
    (``seleziona_riga_top_mix``: argmax sui 1X2, blend, soglie 0,55/0,60, veto)
    viene applicato DUE volte con due Elo diversi:

    * ``current`` -> ``predict_elo_probs`` (``models/elo_engine.py``, post PR#24);
    * ``legacy``  -> ``predict_elo_probs_legacy`` (``models/elo_engine_legacy.py``,
      il blob pre-PR#24 byte per byte, vedi ``models/legacy_elo.py``).

    Ritorna ``{"current": [righe], "legacy": [righe]}`` NON ancora classificate
    (``rank`` None): le due liste possono contenere partite diverse, e' voluto.
    E' la stessa funzione che usa il replay walk-forward
    (``replay_legacy_topmix.py``), cosi' le righe ricostruite nascono dal
    medesimo codice di quelle live. Nessun I/O HTTP qui dentro.

    ``ombra``: lista opzionale. Se e' passata, riceve PER OGNI partita candidata
    (dopo lo scarto delle partite con nomi sconosciuti) DUE righe ombra, una per
    famiglia di Totali (O/U 2.5 e GG/NG: ``righe_ombra_totali``). Non entra nel
    risultato: e' il canale del registro ombra, che non viene mai mostrato in UI.

    ``quote``: indice delle quote dal vivo (``market_odds.indice_partite``, dal
    file scritto dal workflow). Se e' ``None`` la lista ``"mercato"`` resta
    vuota: e' il caso del replay walk-forward, che ricostruisce i click del
    MODELLO e non ha quote live. Quando e' dato, per ogni partita si aggiunge:

    * una riga in ``"mercato"`` se il mercato ha una terna valida e la sua
      probabilita' massima supera 0,55 (``seleziona_riga_top_mix_mercato``);
    * una voce in ``"senza_quote"`` se la partita NON ha quote (nessuna terna
      valida o coppia di nomi assente dalla fonte): la partita e' esclusa dal
      Top Mix e viene SEGNALATA, mai inventata.

    Ritorna ``{"current": [...], "legacy": [...], "mercato": [...],
    "senza_quote": [...]}``: le due liste del modello alimentano il registro
    OMBRA, ``"mercato"`` e' il Top Mix visibile.
    """
    team_stats, avg_h, avg_a, _ = engine
    righe = {MODEL_VARIANT_CURRENT: [], MODEL_VARIANT_LEGACY: [], "mercato": [], "senza_quote": []}
    indice_quote = (quote or {}).get("indice") if isinstance(quote, dict) else None
    istante_quote = (quote or {}).get("generato_il") if isinstance(quote, dict) else None
    for match in matches:
        h = match['homeTeam'].get('shortName') or match['homeTeam'].get('name', '?')
        a = match['awayTeam'].get('shortName') or match['awayTeam'].get('name', '?')
        # [solo UI] h/a RESTANO GREZZI per le chiavi qui sotto (clean_name,
        # Elo); il nome mostrato/salvato passa da display_name.
        h_disp, a_disp = display_name(h), display_name(a)
        # Fallback sui nomi: mai silenziosi. Caso (a) nome non nel roster della
        # stagione = errore a monte: la partita e' ESCLUSA da ENTRAMBE le
        # tabelle (nessuna statistica inventata, log col nome grezzo e quello
        # pulito). Caso (b) squadra del roster senza statistiche (neopromossa
        # prima del debutto): comportamento di sempre (default att=1.0 def=1.0)
        # piu' il warning nel log e il marcatore "dati_mancanti" sulla riga.
        sconosciuti, senza_stats = _stato_squadre_match(
            league, _stagione_da_utcdate(match.get('utcDate')), h, a,
            team_stats, "Top Mix")
        if sconosciuti:
            continue
        h_s = team_stats.get(clean_name(h), {"att": 1.0, "def": 1.0})
        a_s = team_stats.get(clean_name(a), {"att": 1.0, "def": 1.0})

        # Poisson a due teste: 1X2 da mercato normalizzato, O/U e GG da lambda base
        m_poisson = get_full_poisson_two_heads(h_s, a_s, avg_h, avg_a)

        # Registro ombra dei Totali: la stessa partita, la scelta che il vecchio
        # selettore avrebbe fatto sui Totali. Solo se il chiamante la vuole.
        if ombra is not None:
            ombra.extend(_riga_ombra(league, match, h_disp, a_disp, riga_ombra,
                                     dati_mancanti=senza_stats)
                         for riga_ombra in righe_ombra_totali(m_poisson, h_disp, a_disp))

        # Elo agreement (solo per 1X2): qui e' I/O (engine/cache Elo), la
        # decisione resta nella funzione pura.
        elo_probs, elo_disponibile = None, False
        try:
            elo_probs = predict_elo_probs(h, a, league, season=_stagione_da_utcdate(match.get('utcDate')))
            elo_disponibile = True
        except Exception as e:
            logging.warning(f"Elo non disponibile per {h} vs {a} ({league}): {e}")
        # Secondo motore: l'Elo legacy (pre-PR#24). Fallback marcato allo
        # stesso modo, indipendente dal primo.
        elo_legacy, elo_legacy_disponibile = None, False
        try:
            elo_legacy = predict_elo_probs_legacy(h, a, league)
            elo_legacy_disponibile = True
        except Exception as e:
            logging.warning(f"Elo legacy non disponibile per {h} vs {a} ({league}): {e}")

        # [solo UI] le etichette "Vittoria {squadra}" e il codice mercato
        # usano il nome display: mercato_standard resta identico perche'
        # etichetta e nome passati a codice_mercato_selezionato derivano
        # dalla STESSA variabile (come prima col grezzo).
        riga = seleziona_riga_top_mix(m_poisson, elo_probs, elo_disponibile, h_disp, a_disp)
        if riga is not None:
            righe[MODEL_VARIANT_CURRENT].append(_riga_top_mix(league, match, h_disp, a_disp, riga, dati_mancanti=senza_stats))
        riga_legacy = seleziona_riga_top_mix(m_poisson, elo_legacy, elo_legacy_disponibile, h_disp, a_disp)
        if riga_legacy is not None:
            righe[MODEL_VARIANT_LEGACY].append(_riga_top_mix(league, match, h_disp, a_disp, riga_legacy, dati_mancanti=senza_stats))

        # Top Mix VISIBILE: la scelta del mercato. Il modello (Drago) entra solo
        # come probabilita' sullo stesso esito e come segnale "d'accordo".
        if indice_quote is not None:
            evento, motivo_assenza = cerca_quote_con_motivo(
                indice_quote, h, a, match.get('utcDate'))
            mkt = probabilita_mercato((evento or {}).get("libri") or [])
            prob_mkt = mkt["probs"]
            # Probabilita' del Drago (blend 0,25 Poisson + 0,75 Elo) su 1/X/2:
            # la stessa funzione usata dalla PR #49 per il confronto.
            prob_drago = blend_elo_into_1x2(m_poisson, h, a, league,
                                            elo_probs=elo_probs,
                                            elo_disponibile=elo_disponibile,
                                            season=_stagione_da_utcdate(match.get('utcDate')))
            if prob_mkt is None:
                # Il motivo viene dalla regola che ha davvero scartato la
                # partita (``cerca_quote_con_motivo``), non ricostruito qui: se
                # l'evento c'e' ma la terna non vale il motivo e' quello, se
                # l'evento manca per la finestra o per l'assenza dalla fonte il
                # testo deve dirlo (si riparano in modi diversi).
                motivo = (MOTIVO_TERNA_NON_VALIDA % mkt["n_libri_totale"]
                          if evento else (motivo_assenza or MOTIVO_ASSENTE_DALLA_FONTE))
                logging.warning("Top Mix mercato: %s vs %s (%s) SENZA quote: %s. "
                                "Esclusa dal Top Mix.", h_disp, a_disp, league, motivo)
                righe["senza_quote"].append({
                    "league": league, "home": h_disp, "away": a_disp,
                    "match_id": match.get("id"), "utcDate": match['utcDate'],
                    "home_raw": h, "away_raw": a,
                    "evento_trovato": bool(evento),
                    "n_libri_totale": mkt["n_libri_totale"],
                    "motivo": motivo,
                })
                continue
            riga_mkt = seleziona_riga_top_mix_mercato(
                prob_mkt, mkt["odds"], prob_drago, fonte=mkt["fonte"],
                n_libri=mkt["n_libri"], home=h_disp, away=a_disp)
            if riga_mkt is not None:
                righe["mercato"].append(_riga_top_mix_mercato(
                    league, match, h_disp, a_disp, riga_mkt,
                    quote_istante=istante_quote, dati_mancanti=senza_stats))
    return righe


def classifica_top_mix(righe):
    """Ordina per probabilita' decrescente e assegna ``rank``: NESSUN tetto.

    Il vecchio tetto di dieci righe (slice sulla lista ordinata) e' stato
    tolto: si mostrano e si registrano TUTTE le partite sopra le soglie del
    selettore (0,55 sui 1X2 con Elo, 0,60 senza Elo: i Totali non entrano piu'
    nel Top Mix visibile), quante sono. Le soglie non cambiano.
    """
    ordinate = sorted(righe, key=lambda x: x['prob'], reverse=True)
    for i, r in enumerate(ordinate):
        r["rank"] = i + 1
    return ordinate


def carica_indice_quote_live():
    """Indice delle quote dal vivo per il Top Mix di mercato (nessuna rete).

    Legge ``SoccerMath/database/live_odds.json``, scritto SOLO dal workflow
    ``.github/workflows/live_odds.yml``: l'app non chiama mai The Odds API.
    Ritorna ``None`` se il file manca o non e' leggibile (il Top Mix di mercato
    resta vuoto e l'UI lo dice), altrimenti un dict con ``indice``,
    ``non_abbinati``, ``generato_il``, ``crediti`` e i conteggi.
    """
    payload, stato = carica_quote_live_con_stato(
        percorso=os.path.join(str(DATABASE_DIR), market_odds.LIVE_ODDS_FILE))
    stato_out = {
        "stato": stato,
        # ``indice`` resta None (non {}) quando il file non e' utilizzabile:
        # "il file non c'e'" e "il file c'e' ma non contiene partite" sono due
        # cose diverse, e ``calcola_righe_top_mix`` le distingue proprio su
        # ``indice is None`` (nessuna riga di mercato E nessuna segnalazione nel
        # primo caso, tutte le partite segnalate nel secondo).
        "indice": None, "non_abbinati": [], "n_eventi": 0, "n_indicizzati": 0,
        "generato_il": None, "eta_ore": None, "obsoleto": False, "dettaglio": None,
        "crediti": {}, "fonte": None, "regioni": None,
        "n_leghe_ok": None, "n_leghe_richieste": None,
    }
    if payload is None:
        stato_out["dettaglio"] = _DETTAGLIO_STATO_QUOTE[stato]
        return stato_out
    dati = indice_partite(payload)
    eta = market_odds.ore_da(payload.get("generato_il"))
    stato_out.update({
        "indice": dati["indice"],
        "non_abbinati": dati["non_abbinati"],
        "n_eventi": dati["n_eventi"],
        "n_indicizzati": dati["n_indicizzati"],
        "generato_il": payload.get("generato_il"),
        "eta_ore": eta,
        "obsoleto": bool(eta is not None and eta > SOGLIA_ORE_QUOTE),
        "crediti": payload.get("crediti") or {},
        "fonte": payload.get("fonte"),
        "regioni": payload.get("regioni"),
        "n_leghe_ok": payload.get("n_leghe_ok"),
        "n_leghe_richieste": payload.get("n_leghe_richieste"),
    })
    for na in dati["non_abbinati"]:
        logging.warning("Top Mix mercato: partita della fonte quote NON abbinata ai nomi "
                        "del progetto: %s vs %s (%s)", na.get("home_raw"), na.get("away_raw"),
                        na.get("lega"))
    if stato_out["obsoleto"]:
        logging.warning("Top Mix mercato: quote OBSOLETE, eta' %.1f h (soglia %d h), "
                        "scaricate il %s.", eta, SOGLIA_ORE_QUOTE, payload.get("generato_il"))
    return stato_out


@st.cache_data(ttl=1800, show_spinner="Calcolando Top Mix...")
def fetch_and_calc_top_mix():
    """Top Mix del turno: tabella di mercato + due modelli ombra. HTTP, motore, quote.

    La selezione di riga NON e' qui dentro: e' nelle funzioni pure
    ``seleziona_riga_top_mix`` (modello) e ``seleziona_riga_top_mix_mercato``
    (mercato), testate rispettivamente in
    ``SoccerMath/test_topmix_selector_parity.py`` e
    ``SoccerMath/test_topmix_mercato.py``; il calcolo per partita (due motori
    Elo, scelta Totali ombra, scelta di mercato) e' in ``calcola_righe_top_mix``.
    Qui restano solo I/O e assemblaggio. Igienizzati in precedenza (referto §4):
    timeout sulla GET, fallback Elo marcato, coda di rate-limit solo FRA le leghe
    (l'ultima non aspetta piu' nulla) e `rank` sulla riga.

    Ritorna ``(top_mercato, top_current, top_legacy, missing, ombra, senza_quote)``:

    * ``top_mercato``  il Top Mix VISIBILE (scelte del mercato, una tabella sola);
    * ``top_current`` / ``top_legacy``  le scelte 1X2 dei due motori: NON sono
      piu' mostrate, vanno nel registro ombra (``salva_registro_ombra``);
    * ``missing``      le leghe senza motore;
    * ``ombra``        le scelte Totali per ogni partita candidata (non mostrate);
    * ``senza_quote``  le partite senza alcuna quota: escluse dal Top Mix e
      segnalate in UI (Analisi Rapida le elenca per nome).
    """
    per_variante, missing = {MODEL_VARIANT_CURRENT: [], MODEL_VARIANT_LEGACY: []}, []
    righe_mercato, senza_quote = [], []
    ombra = []
    quote = carica_indice_quote_live()
    leghe = list(LEAGUES_CONFIG.keys())
    for i_lega, league in enumerate(leghe):
        if i_lega:
            # coda SOLO fra una lega e l'altra (10 richieste/min sul piano free)
            time.sleep(6.5)
        engine = get_league_engine(league)
        if not engine: missing.append(league); continue
        try:
            r = requests.get(f"https://api.football-data.org/v4/competitions/{LEAGUE_CODE_MAP[league]}/matches", headers={'X-Auth-Token': API_KEY_DATA}, params={"status": "TIMED,SCHEDULED"}, timeout=15)
            if r.status_code != 200: continue
            # Fix bug Top Mix: si seleziona la prossima giornata realmente
            # futura per data di gioco, non più il semplice min(matchday).
            matches = select_next_matchday_matches(r.json().get('matches', []))
        except Exception as e:
            logging.warning(f"Errore fetch Top Mix {league}: {e}")
            continue
        righe = calcola_righe_top_mix(league, matches, engine, ombra=ombra, quote=quote)
        for variante in (MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY):
            per_variante[variante].extend(righe[variante])
        righe_mercato.extend(righe["mercato"])
        senza_quote.extend(righe["senza_quote"])
    top_current = classifica_top_mix(per_variante[MODEL_VARIANT_CURRENT])
    top_legacy = classifica_top_mix(per_variante[MODEL_VARIANT_LEGACY])
    top_mercato = classifica_top_mix(righe_mercato)
    return top_mercato, top_current, top_legacy, missing, ombra, senza_quote


def argomenti_registro_top_mix(p, model_variant=MODEL_VARIANT_CURRENT):
    """Argomenti di ``save_prediction_entry`` / ``build_prediction_entry`` per la
    riga Top Mix del MODELLO ``p``: UN solo posto decide come una riga diventa
    un record del registro (tab2 live e replay walk-forward usano questo).

    Dalla PR delle quote live queste righe NON sono piu' il Top Mix visibile:
    il Registro visibile ospita le scelte del mercato
    (``argomenti_registro_top_mix_mercato``, ``SELECTOR_VERSION_CURRENT`` =
    ``topmix_mercato_v3``). Le righe del modello vanno nel registro OMBRA con
    ``SELECTOR_VERSION_OMBRA_1X2`` e la loro ``model_variant``: Drago e Legacy
    restano due righe distinte della stessa partita (stesse regole
    anti-doppione di prima, chiavi di dedup diverse, nessuna sovrascrittura).

    Gate shadow (referto §11quater): la riga GIOCATA porta anche i campi ombra
    (confidenza penalizzata dal disaccordo |P-E| e ammissione sotto il solo
    filtro conf_shadow >= soglia). Se il calcolo fallisce -> None -> campi
    assenti, record identico a prima. Nessun effetto su market/prob/rank reali.
    """
    campi_shadow = gate_shadow_fields_from_row(
        p.get("market"), p.get("prob"), p.get("poisson"), p.get("elo"),
        p.get("elo_disponibile", True),
    )
    campi_off = gate_off_fields_from_row(
        p.get("market"), p.get("prob"), p.get("poisson"), p.get("elo"),
        p.get("elo_disponibile", True),
    )
    args = (
        p['match_id'], p['home'], p['away'], p['league'], p['giornata'],
        format_date_italy(p['utcDate'], "%d/%m/%Y %H:%M"),
        f"{p['market']} - Top Mix", [], p['prob_val'], "",
    )
    kwargs = dict(
        mercato_standard=p.get("mercato_standard") or codice_mercato_selezionato(p.get("market"), p['home'], p['away']),
        # ORIGINE OMBRA: da questa PR le scelte del modello non sono piu' il
        # Top Mix visibile, quindi la riga e' di ombra. Sta QUI (e non nel
        # chiamante) perche' ``build_prediction_entry`` ricava da ``origin``
        # sia ``tipo`` sia ``calculation_id``: chi costruisce la riga deve
        # trovarla gia' giusta.
        origin=ORIGIN_TOP_MIX_OMBRA, rank=p.get("rank"),
        kickoff_utc=p.get('utcDate'), prob_poisson=p.get('poisson'),
        prob_elo=p.get('elo'), elo_disponibile=p.get("elo_disponibile", True),
        gate_shadow_confidence=(campi_shadow or {}).get(GATE_SHADOW_CONFIDENCE_FIELD),
        gate_shadow_ammessa=(campi_shadow or {}).get(GATE_SHADOW_AMMESSA_FIELD),
        gate_off_confidence=(campi_off or {}).get(GATE_OFF_CONFIDENCE_FIELD),
        gate_off_ammessa=(campi_off or {}).get(GATE_OFF_AMMESSA_FIELD),
        model_variant=model_variant,
        selector_version=SELECTOR_VERSION_OMBRA_1X2,
    )
    return args, kwargs


def argomenti_registro_top_mix_mercato(p):
    """Argomenti di registro per la riga del Top Mix di MERCATO ``p``.

    Speculare a ``argomenti_registro_top_mix`` ma per la tabella visibile:
    ``selector_version`` = ``SELECTOR_VERSION_CURRENT`` (``topmix_mercato_v3``),
    ``model_variant`` = ``current`` (la scelta non dipende dal motore: il
    modello entra solo come probabilita' di confronto e come segnale di
    accordo), e i campi di mercato (fonte, numero di libri, quota, probabilita'
    del modello, accordo, istante delle quote) che rendono la riga verificabile.

    ``prob_sicuro`` resta la percentuale della probabilita' che DECIDE, cioe'
    quella di mercato: il Registro e il grading leggono quel campo, e la
    colonna "d'accordo" viaggia nei campi dedicati.
    """
    args = (
        p['match_id'], p['home'], p['away'], p['league'], p['giornata'],
        format_date_italy(p['utcDate'], "%d/%m/%Y %H:%M"),
        f"{p['market']} - Top Mix", [], p['prob_val'], "",
    )
    kwargs = dict(
        mercato_standard=p.get("mercato_standard") or codice_mercato_selezionato(p.get("market"), p['home'], p['away']),
        origin=ORIGIN_TOP_MIX, rank=p.get("rank"),
        kickoff_utc=p.get('utcDate'),
        prob_modello=(None if p.get("prob_modello_val") is None else p["prob_modello_val"]),
        prob_mercato=(None if p.get("prob_val") is None else round(p["prob_val"] / 100.0, 6)),
        quota_mercato=p.get("quota"),
        mercato_fonte=p.get("fonte"),
        mercato_n_libri=p.get("n_libri"),
        accordo_modello=bool(p.get("accordo")),
        quote_live_istante=p.get("quote_live_istante"),
        model_variant=MODEL_VARIANT_CURRENT,
        selector_version=SELECTOR_VERSION_CURRENT,
    )
    return args, kwargs


def analisi_rapida_giornata(matches, team_stats, avg_h, avg_a, camp_sel, classifica_sess, giornata_n):
    """Analisi Rapida della giornata, sui DUE motori come il Top Mix.

    Per ogni partita la SCELTA e' una sola (argmax sui 7 mercati Poisson puri,
    decisione dell'audit ``audit/results/ensemble_scope_analisi_rapida.md``), ma
    viene salvata una riga per motore: l'Elo attuale (post-fix PR#24) e l'Elo
    legacy, ciascuno nella propria variante. Prima si scriveva una riga sola, che
    nel Registro non era confrontabile con i due modelli del Top Mix; le righe
    scritte allora restano dove sono (nessuna riscrittura).

    Ritorna il numero di RIGHE scritte (due per partita).

    Nomi fuori roster (caso a): la partita NON usa statistiche di default e
    nessuna riga viene scritta; l'avviso esplicito in UI e il WARNING nel log
    (nome grezzo e nome pulito) dicono perche'. Squadre del roster senza
    statistiche (caso b, per es. neopromossa prima del debutto): righe scritte
    come sempre (default att=1.0 def=1.0), con WARNING nel log e avviso in UI.
    """
    salvate = 0
    avvisi_sconosciuti = []
    stats_default = []
    # Partite senza quote di mercato: l'Analisi Rapida non le sceglie (continua a
    # usare il modello), ma le SEGNALA per nome. Sono le stesse partite escluse
    # dal Top Mix di mercato: un'assenza di quote non deve passare in silenzio.
    stato_quote = carica_indice_quote_live()
    # SENZA ``or {}``: un indice vuoto ({}) e un indice assente (None) non sono
    # la stessa cosa. Con ``or {}`` un file presente ma senza eventi diventava
    # indistinguibile da un file assente e NESSUNA partita veniva segnalata.
    indice_quote = (stato_quote or {}).get("indice")
    _avviso_stato_quote(stato_quote, "Analisi Rapida")
    if (stato_quote or {}).get("stato") == STATO_OK and (stato_quote or {}).get("obsoleto"):
        st.error(f"⚠️ Analisi Rapida: quote OBSOLETE, eta' {stato_quote['eta_ore']:.1f} h "
                 f"(soglia {SOGLIA_ORE_QUOTE} h), scaricate il "
                 f"{stato_quote.get('generato_il') or 'n/d'}. Le segnalazioni "
                 "'senza quote' restano valide, le probabilita' di mercato no.")
    _mostra_non_abbinati_fonte(stato_quote, "Analisi Rapida")
    senza_quote = []
    for match in matches:
        try:
            h, a = match['homeTeam'].get('shortName') or match['homeTeam'].get('name', '?'), match['awayTeam'].get('shortName') or match['awayTeam'].get('name', '?')
            # [solo UI] h/a RESTANO GREZZI per le chiavi (clean_name, Elo);
            # etichette, pronostico e campi home/away del registro usano il
            # nome display.
            h_disp, a_disp = display_name(h), display_name(a)
            m_id = match.get('id')
            if not m_id: continue
            # ``indice_quote is not None`` e NON la sua verita': con un file
            # valido ma SENZA eventi l'indice e' {} e ogni partita va segnalata.
            # Prima la condizione era ``if indice_quote and ...``: {} e' falsy,
            # quindi l'Analisi Rapida taceva proprio nel caso in cui nessuna
            # partita ha quote. ``stato_quote is not None`` tiene fuori il caso
            # "file non utilizzabile", gia' coperto dal messaggio sullo stato.
            if (stato_quote is not None and indice_quote is not None
                    and cerca_quote(indice_quote, h, a, match.get('utcDate')) is None):
                senza_quote.append(f"{h_disp} vs {a_disp}")
                logging.warning("Analisi Rapida: %s vs %s (%s) SENZA quote di mercato: "
                                "esclusa dal Top Mix di mercato.", h_disp, a_disp, camp_sel)
            # Fallback sui nomi: mai silenziosi (stessa classificazione del
            # Top Mix). Caso (a): nome non nel roster della stagione = errore
            # a monte -> NESSUNA riga, avviso esplicito. Caso (b): roster
            # senza statistiche -> righe come sempre, marcatore nel log e in UI.
            sconosciuti, senza_stats = _stato_squadre_match(
                camp_sel, _stagione_da_utcdate(match.get('utcDate')), h, a,
                team_stats, "Analisi Rapida")
            if sconosciuti:
                dettaglio = ", ".join(f"'{grezzo}' (pulito: '{pulito}')"
                                      for grezzo, pulito in sconosciuti)
                avvisi_sconosciuti.append(f"{h_disp} vs {a_disp}: {dettaglio}")
                st.warning(f"⚠️ Analisi Rapida: {h_disp} vs {a_disp} SALTATA: "
                           f"nome squadra non nel roster di {camp_sel}: {dettaglio}. "
                           f"Nessuna statistica di default usata, nessuna riga scritta.")
                continue
            if senza_stats:
                stats_default.extend(pulito for _grezzo, pulito in senza_stats)
            match_date_str = format_date_italy(match['utcDate'], "%d/%m/%Y %H:%M")
            h_s, a_s = team_stats.get(clean_name(h), {"att": 1.0, "def": 1.0}), team_stats.get(clean_name(a), {"att": 1.0, "def": 1.0})
            m = get_full_poisson_two_heads(h_s, a_s, avg_h, avg_a)
            # Selezione (argmax) sui mercati POISSON PURO: il blend 1X2 dentro
            # l'argmax sposta sistematicamente la scelta verso Over/NG e
            # peggiora hit rate/ROI (audit/results/ensemble_scope_analisi_rapida.md:
            # 22.6% di flip, ROI flip PRE +3.6% vs POST -6.0%, Serie A Brier +0.0119).
            mercati = {f"Vittoria {h_disp}": m["1"], "Pareggio": m["X"], f"Vittoria {a_disp}": m["2"], "Over 2.5": 1 - m["u25"], "Under 2.5": m["u25"], "GG": m["gg"], "NG": 1 - m["gg"]}
            best_mkt = max(mercati, key=mercati.get)
            # Probabilita' salvata: SOLO se il mercato scelto e' 1X2 si usa la
            # probabilita' blendata 0.6*Poisson+0.4*Elo (calibrazione validata
            # in audit/diagnose_elo_ensemble.py); i Totali restano Poisson puro.
            # Se l'Elo non e' disponibile blend_elo_into_1x2 ritorna il Poisson
            # puro bit-identico.
            # SECONDO MOTORE (come nel Top Mix): l'Elo pre-fix PR#24. Fallback
            # marcato e indipendente dal primo: se manca, la riga legacy si
            # scrive lo stesso col Poisson puro e `elo_disponibile=False` lo dice.
            elo_legacy, elo_legacy_disponibile = None, False
            try:
                elo_legacy = predict_elo_probs_legacy(h, a, camp_sel)
                elo_legacy_disponibile = True
            except Exception as e:
                logging.warning(f"Analisi Rapida: Elo legacy non disponibile per {h} vs {a} ({camp_sel}): {e}")
            # Due righe per partita, una per motore: la SCELTA (argmax sui mercati
            # Poisson puri) e' la stessa, cambia la probabilita' 1X2 (blendata con
            # l'Elo del motore) e la variante scritta nel Registro. Cosi' anche
            # l'Analisi Rapida si legge come i due modelli del Top Mix invece di
            # essere un'unica riga non confrontabile.
            stagione_partita = _stagione_da_utcdate(match.get('utcDate'))
            for variante in (MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY):
                if variante == MODEL_VARIANT_CURRENT:
                    m_blend = blend_elo_into_1x2(m, h, a, camp_sel, season=stagione_partita)
                    elo_disp = True
                else:
                    m_blend = blend_elo_into_1x2(m, h, a, camp_sel, elo_probs=elo_legacy,
                                                 elo_disponibile=elo_legacy_disponibile)
                    elo_disp = elo_legacy_disponibile
                prob_1x2_blend = {f"Vittoria {h_disp}": m_blend["1"], "Pareggio": m_blend["X"], f"Vittoria {a_disp}": m_blend["2"]}
                prob_best = prob_1x2_blend.get(best_mkt, mercati[best_mkt])
                pron = f"{best_mkt} - {prob_best:.0%} - Poisson Auto"
                top3 = [f"{i+1}. {k} - {v:.0%}" for i, (k, v) in enumerate(sorted([(k, v) for k, v in mercati.items() if k != best_mkt], key=lambda x: -x[1])[:3])]
                # Origine esplicita: senza di essa il Record "Poisson Auto" finiva
                # nel calderone "Analisi" e non era distinguibile dal Top Mix.
                save_prediction_entry(m_id, h_disp, a_disp, camp_sel, giornata_n, match_date_str, pron, top3, round(prob_best*100, 1), "", mercato_standard=codice_mercato_selezionato(best_mkt, h_disp, a_disp),
                                      origin=ORIGIN_ANALISI_RAPIDA, kickoff_utc=match.get('utcDate'),
                                      prob_poisson=round(mercati[best_mkt] * 100, 1),
                                      model_variant=variante)
                salvate += 1
        except Exception as e:
            logging.warning(f"Analisi Rapida: partita {h} vs {a} saltata: {e}")
    if stats_default:
        # Caso (b) dichiarato anche in UI: il Poisson di queste righe ha usato
        # le statistiche di default (squadre del roster ancora senza dati).
        st.info(f"ℹ️ Analisi Rapida: statistiche di default (att=1.0 def=1.0) per: "
                f"{', '.join(sorted(set(stats_default)))} (squadre del roster senza "
                f"statistiche nel motore, per es. al debutto). Dettaglio nel log.")
    if senza_quote:
        st.warning(f"⚠️ Analisi Rapida: {len(senza_quote)} partite SENZA quote di mercato "
                   f"(escluse dal Top Mix di mercato, nessuna probabilita' inventata): "
                   f"{'; '.join(senza_quote)}.")
    return salvate

@st.dialog("STRATEGIC ANALYSIS", width="large")
def show_details(h, a, m, m_poisson, camp_sel="Serie A", giornata_n=0):
    match_id, match_date_str, match_utc = None, "", None
    for mx in st.session_state.get("live_data", []):
        if clean_name(h) in clean_name(mx["homeTeam"].get("shortName", "") or mx["homeTeam"].get("name","")):
            match_id = mx.get("id"); match_date_str = format_date_italy(mx["utcDate"], "%d/%m/%Y %H:%M"); match_utc = mx.get("utcDate"); break
    # Selezione (argmax) sui 7 mercati POISSON PURO (m_poisson calcolato in
    # tab1 PRIMA del blend): il blend 1X2 dentro l'argmax sposta le scelte
    # verso i Totali e peggiora la qualita' della selezione
    # (audit/results/ensemble_scope_analisi_rapida.md); stessa regola di
    # analisi_rapida_giornata(). m (blendato) resta solo per la probabilita'.
    # GG/NG erano ESCLUSI qui ma non nel Top Mix ne' in Analisi Rapida: il
    # dialoghetto poteva indicare un mercato diverso dalla card per la stessa
    # partita (audit/margini_migliorabili_topmix.md §4 punto 4).
    mercati_puri = {f"Vittoria {h}": m_poisson['1'], "Pareggio": m_poisson['X'], f"Vittoria {a}": m_poisson['2'], "Over 2.5": 1-m_poisson['u25'], "Under 2.5": m_poisson['u25'], "GG": m_poisson['gg'], "NG": 1-m_poisson['gg']}
    mercato_top = max(mercati_puri, key=mercati_puri.get)
    # Probabilita' salvata: blendata (m e' l'1X2 Poisson+Elo mostrato nella
    # card) SOLO se il mercato scelto e' 1X2; per i Totali Poisson puro.
    prob_1x2_blend = {f"Vittoria {h}": m['1'], "Pareggio": m['X'], f"Vittoria {a}": m['2']}
    prob_top = prob_1x2_blend.get(mercato_top, mercati_puri[mercato_top])
    codice_top = codice_mercato_selezionato(mercato_top, h, a)

    if not groq_client:
        st.error("⚠️ Billy (Groq) non configurato. Devi creare il file .env come spiegato!")
        if match_id: save_prediction_entry(match_id, h, a, camp_sel, giornata_n, match_date_str, f"{mercato_top} - Fallback", [], round(prob_top*100, 1), "", mercato_standard=codice_top, origin=ORIGIN_BILLY)
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
                # Testa Totali su lambda PURE (M=1, senza forma ne' mercato),
                # come in produzione (get_full_poisson_two_heads): qui prima si
                # omettevano base_pure_h/base_pure_a e i totali del dialoghetto
                # giravano sulla testa con la forma a 5 gare, che l'audit ha
                # misurato come peggiore sui totali
                # (audit/results/form_totali_diagnosis.md: Brier O/U 0,2488 ->
                # 0,2401 senza forma).
                # _stat_num (non .get): un campo assente o NaN non deve far
                # esplodere il blocco e trasformare Billy in "Errore AI".
                attp_h = _stat_num(hs, "att0_pure", att0_h); defp_h = _stat_num(hs, "def0_pure", def0_h)
                attp_a = _stat_num(as_, "att0_pure", att0_a); defp_a = _stat_num(as_, "def0_pure", def0_a)
                m_adj = _two_heads_from_lambdas(base_h, base_a, mkt_h, mkt_a,
                                                 attp_h * defp_a * ah, attp_a * defp_h * aa)
            else:
                # fallback senza engine: testa singola neutra
                m_adj = get_full_poisson(1.3, 1.1)
            p1, pX, p2 = m_adj['1'], m_adj['X'], m_adj['2']

            # --- CONTESTO PER IL PROMPT (Elo, classifica, forma recente) ---
            # Il prompt ragionato ha bisogno di questi dati: senza di essi un
            # NameError verrebbe inghiottito dal try/except e Billy non risponderebbe.
            elo_non_disponibile = "Elo non disponibile per questa partita"
            try:
                elo_p = predict_elo_probs(h, a, camp_sel, season=_stagione_da_utcdate(match_utc))
                elo_disponibile = True
            except Exception as e:
                logging.warning(f"Elo non disponibile per {h} vs {a}: {e}")
                elo_p = None
                elo_disponibile = False
                st.warning(elo_non_disponibile)
            classifica = st.session_state.get("classifica", {}) or {}
            h_pos = classifica.get(clean_name(h), {}).get("pos", "N/D")
            a_pos = classifica.get(clean_name(a), {}).get("pos", "N/D")
            h_ris = contesto.get("h_risultati", [])
            a_ris = contesto.get("a_risultati", [])

            elo_riga_prompt = (f"- Elo: 1={elo_p['1']:.1%} | X={elo_p['X']:.1%} | "
                               f"2={elo_p['2']:.1%} (diff Elo={elo_p['elo_diff']:.0f})"
                               if elo_disponibile else f"- {elo_non_disponibile}")
            prompt = f"""Sei Billy Walters, esperto di betting con 40 anni di esperienza. Analizza {h} vs {a} ({camp_sel}).

DATI QUANTITATIVI DEI MODELLI:
- Poisson: 1={p1:.1%} | X={pX:.1%} | 2={p2:.1%}
{elo_riga_prompt}
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
            if match_id: save_prediction_entry(match_id, h, a, camp_sel, giornata_n, match_date_str, f"{mercato_top} - Errore AI", [], round(prob_top*100, 1), "", mercato_standard=codice_top, origin=ORIGIN_BILLY)

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
            .top-mix-model { color: #1a1d23 !important; }
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
                st.success(f"✅ {n} righe salvate ({len(matches)} partite x 2 motori: attuale e legacy)!")
        for idx, match in enumerate(matches):
            h_api, a_api, m_poisson, m, sconosciuti, senza_stats = dati_card_partita(match, team_stats, avg_h, avg_a, camp_sel)
            dt = format_date_italy(match['utcDate'])
            if m is None:
                # Caso (a): la card NON usa statistiche di default. L'avviso
                # esplicito in scheda (qui) e il WARNING nel log (nome grezzo e
                # pulito, in _stato_squadre_match) dicono perche'.
                dettaglio = ", ".join(f"'{grezzo}' (pulito: '{pulito}')"
                                      for grezzo, pulito in sconosciuti)
                st.warning(f"⚠️ PARTITE: {display_name(h_api)} vs {display_name(a_api)} "
                           f"non mostrata: nome squadra non nel roster di {camp_sel}: "
                           f"{dettaglio}. Nessuna statistica di default usata.")
                continue
            with st.container():
                st.markdown('<div class="match-card">', unsafe_allow_html=True)
                c_h, c1, c3, c5, c6 = st.columns([1.5, 1.2, 0.8, 1, 0.4])
                # [solo UI] il nome mostrato nella card passa da display_name
                # ("Atleti" -> "Atletico Madrid"); h_api/a_api RESTANO GREZZI
                # per le chiavi sopra (clean_name, blend Elo) e per
                # show_details, che fa matching contro live_data/classifica.
                with c_h: st.markdown(f"<span class='team-name'>{display_name(h_api)}<br>{display_name(a_api)}</span><br><span class='match-date'>🕒 {dt}</span>", unsafe_allow_html=True)
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
                        st.button("🔍", key=f"ex_{camp_sel}_{g_sel}_{idx}", on_click=show_details, args=(h_api, a_api, m, m_poisson, camp_sel, g_sel))
                if senza_stats:
                    # Caso (b) marcato nella card: il Poisson mostrato ha usato
                    # le statistiche di default (squadra del roster ancora
                    # senza dati nel motore, per es. al debutto).
                    st.markdown(f"<small>⚠️ stats di default (nessun dato: "
                                f"{', '.join(pulito for _grezzo, pulito in senza_stats)})</small>",
                                unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)
    else:
        if not engine:
            st.warning("⚠️ Database locale non trovato. Verifica che i file CSV siano presenti in `database/`.")
        elif not API_KEY_DATA:
            st.info("🔑 Inserisci l'API Key Football-Data nei Secrets e premi SINCRONIZZA.")
        else:
            st.info("👋 Premi SINCRONIZZA per caricare le partite del campionato selezionato.")

def _mostra_blocco_modello(records, titolo, sottotitolo):
    """Blocco statistiche di UN motore: le STESSE righe della sua tabella.

    Un solo modo di contare, quello della tabella: la variante letta (campo
    esplicito, oppure DATA quando il campo manca) sceglie sia il blocco sia la
    tabella, quindi i due numeri non possono divergere.
    """
    s = stats_all(records)
    st.markdown(f"##### {titolo} — {s['total']} righe")
    st.caption(sottotitolo)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Totale", s["total"])
    c2.metric("✅ Vinte", s["wins"],
              delta=f"{s['win_rate']:.1f}%" if s["decided"] else None,
              help="Percentuale calcolata solo sulle partite decise (esclude quelle in attesa).")
    c3.metric("❌ Perse", s["losses"])
    c4.metric("⏳ Attesa", s["pending"])


COLONNE_TOP_MIX_MERCATO = ["Partita", "Esito", "P mercato %", "Quota mercato",
                           "P modello Drago %", "D'accordo", "Fonte", "Eta' quote (h)"]


# Messaggio per ciascuno stato del file delle quote. Dire "il file non c'e'"
# quando il file c'e' ed e' corrotto nasconde un guasto reale: uno stato, un
# testo. Sono usati sia dal Top Mix sia dall'Analisi Rapida.
_DETTAGLIO_STATO_QUOTE = {
    STATO_ASSENTE: (
        f"{market_odds.LIVE_ODDS_FILE} non esiste: il workflow `live_odds.yml` non ha "
        "ancora scritto (prima esecuzione, oppure quota di crediti esaurita prima del "
        "primo giro)."),
    STATO_NON_LEGGIBILE: (
        f"{market_odds.LIVE_ODDS_FILE} ESISTE ma non e' leggibile o non e' JSON valido: "
        "scrittura interrotta o file corrotto. Le quote non sono utilizzabili."),
    STATO_SENZA_LEGHE: (
        f"{market_odds.LIVE_ODDS_FILE} ESISTE ed e' JSON valido, ma non contiene la "
        "chiave 'leghe': schema diverso dall'atteso "
        f"(`{market_odds.SCHEMA_LIVE_ODDS}`). Le quote non sono utilizzabili."),
    STATO_OK: "",
}


def _eta_quote_riga(p):
    """Eta' in ore delle quote di UNA riga (None -> ``'n/d'``).

    Un timestamp non interpretabile NON diventa "0 ore": tornerebbe una quota
    vecchia spacciata per fresca.
    """
    eta = market_odds.ore_da(p.get("quote_live_istante"))
    return "n/d" if eta is None else round(eta, 1)


def _mostra_non_abbinati_fonte(stato_quote, dove):
    """Elenca i nomi squadra della FONTE QUOTE che il progetto non riconosce.

    E' un avviso DIVERSO da quello sulle partite del calendario senza quote, e
    deve restare separato: qui il problema e' a monte (un nome della fonte fuori
    tabella, quindi un alias da aggiungere in ``team_aliases.py``), la' la
    partita e' nota ma la fonte non la copre. Confonderli farebbe cercare un
    alias dove non manca.
    """
    non_abbinati = (stato_quote or {}).get("non_abbinati") or []
    if not non_abbinati:
        return
    def _lato(n):
        parti = []
        if not n.get("home_riconosciuto"):
            parti.append(f"casa {n.get('home_raw')!r}")
        if not n.get("away_riconosciuto"):
            parti.append(f"trasferta {n.get('away_raw')!r}")
        return " e ".join(parti) or "coppia non risolta"
    st.warning(
        f"⚠️ {dove}: {len(non_abbinati)} partite della FONTE QUOTE con nomi squadra "
        "non riconosciuti dal progetto (nessun fuzzy matching: vanno aggiunti in "
        "`team_aliases.py`). "
        + "; ".join(f"{n.get('home_raw')} vs {n.get('away_raw')} "
                    f"({n.get('lega') or '?'}: {_lato(n)})" for n in non_abbinati))


def _avviso_stato_quote(stato_quote, dove):
    """Avviso sullo stato del file delle quote. Ritorna ``True`` se ha avvisato.

    Un messaggio diverso per ogni stato: l'assenza, la corruzione e lo schema
    sbagliato si riparano in modi diversi, e l'utente non deve indovinare quale
    dei tre e' capitato.
    """
    stato = (stato_quote or {}).get("stato")
    if stato == STATO_OK:
        return False
    st.warning(f"⚠️ {dove}: {_DETTAGLIO_STATO_QUOTE.get(stato, stato)}. "
               "Nessuna probabilita' di mercato viene inventata: l'Analisi Rapida "
               "usa solo il modello e il Top Mix di mercato resta vuoto.")
    return True


def _etichetta_fonte_mercato(riga):
    """Fonte della probabilita' di mercato, leggibile riga per riga.

    ``pinnacle`` = de-vig di Pinnacle (fonte primaria); ``media_libri`` =
    riserva sulla media dei libri disponibili, con il numero di libri: la
    riserva non deve mai passare per una quota di Pinnacle che non c'e'.
    """
    fonte = riga.get("fonte")
    n = riga.get("n_libri")
    if fonte == FONTE_PINNACLE:
        return "Pinnacle"
    if fonte == FONTE_MEDIA_LIBRI:
        return f"media di {n} libri" if n else "media dei libri"
    return fonte or "n/d"


def tabella_top_mix_mercato(righe):
    """DataFrame della TABELLA UNICA del Top Mix: una riga per partita.

    Colonne richieste dalla commessa: partita, esito scelto (1/X/2) dal mercato,
    probabilita' di mercato, quota di mercato, probabilita' del modello (Drago)
    per lo stesso esito, segnale "d'accordo si'/no". Accanto, la fonte della
    probabilita' (Pinnacle o media dei libri): senza di essa una riga di riserva
    sarebbe indistinguibile da una riga Pinnacle.

    Nessuna percentuale viene ricalcolata qui: sono i campi della riga prodotti
    da ``seleziona_riga_top_mix_mercato``.
    """
    return pd.DataFrame([
        {
            "Partita": f"{p['home']} vs {p['away']}",
            "Lega": p["league"],
            "Inizio": format_date_italy(p["utcDate"], "%d/%m %H:%M"),
            "Esito": p["esito"],
            "P mercato %": p["prob_val"],
            "Quota mercato": p["quota"],
            "P modello Drago %": p["prob_modello_val"],
            "D'accordo": "sì" if p.get("accordo") else "no",
            "Fonte": _etichetta_fonte_mercato(p),
            # Eta' delle quote riga per riga: la probabilita' di mercato vale
            # all'istante in cui il workflow l'ha scaricata, e l'utente deve
            # poterlo leggere sulla riga, non solo nell'intestazione.
            "Eta' quote (h)": _eta_quote_riga(p),
        }
        for p in righe
    ])[COLONNE_TOP_MIX_MERCATO + ["Lega", "Inizio"]] if righe else pd.DataFrame(
        columns=COLONNE_TOP_MIX_MERCATO + ["Lega", "Inizio"])


def _mostra_tabella_top_mix_mercato(righe, quote_meta=None):
    """La TABELLA UNICA del Top Mix (mercato) + il calcolatore di multipla.

    Nessun'altra tabella di scelte: Drago e Legacy non hanno una tabella
    visibile (le loro righe vanno nel registro ombra). Quando il file delle
    quote manca o non copre il turno lo si dice esplicitamente, invece di
    mostrare una tabella vuota che sembrerebbe "nessuna partita probabile".
    """
    st.markdown("##### 🌟 Top Mix — scelte del mercato")
    meta = quote_meta if isinstance(quote_meta, dict) else {}
    stato = meta.get("stato")
    if stato == STATO_OK:
        crediti = meta.get("crediti") or {}
        eta = meta.get("eta_ore")
        st.caption(
            f"Quote scaricate il **{meta.get('generato_il') or 'n/d'}** "
            + (f"(eta' **{eta:.1f} h**)" if eta is not None else "(eta' n/d)") + ", "
            f"{meta.get('fonte') or 'the-odds-api'}, regioni {meta.get('regioni') or 'eu'}, "
            f"{meta.get('n_leghe_ok')}/{meta.get('n_leghe_richieste')} leghe con eventi, "
            f"crediti residui {crediti.get('residui', 'n/d')} su "
            f"{crediti.get('quota_mensile', 500)}. "
            f"Soglia di ammissione: probabilita' di mercato ≥ "
            f"{SOGLIA_TOPMIX_MERCATO:.2f}. Nessun filtro sulle quote basse: la tabella "
            f"individua le partite piu' probabili, la quota minima la decide l'utente.")
        if meta.get("obsoleto"):
            # Quote vecchie: le righe RESTANO visibili (meglio una quota vecchia
            # dichiarata che una tabella vuota senza spiegazione), ma l'eta' si
            # legge qui e su ogni riga, non va indovinata.
            st.error(
                f"⚠️ Quote OBSOLETE: eta' {eta:.1f} h, oltre la soglia di "
                f"{SOGLIA_ORE_QUOTE} h (scaricate il {meta.get('generato_il') or 'n/d'}). "
                "Il workflow `live_odds.yml` non ha scritto di recente, oppure la sua "
                "quota di crediti e' esaurita e il file precedente e' stato conservato. "
                "Le probabilita' di mercato qui sotto sono quelle di allora.")
    elif stato is not None:
        st.caption(_DETTAGLIO_STATO_QUOTE.get(stato, stato))
    else:
        st.caption("File delle quote non disponibile: il workflow `live_odds.yml` non ha "
                   "ancora scritto `SoccerMath/database/live_odds.json` (oppure la quota "
                   "crediti era esaurita e il file precedente e' stato conservato).")
    if not righe:
        st.info("Nessuna partita con probabilita' di mercato ≥ "
                f"{SOGLIA_TOPMIX_MERCATO:.2f} in questo turno"
                + ("" if stato == STATO_OK else " (nessuna quota disponibile)."))
        return
    n_accordo = sum(1 for p in righe if p.get("accordo"))
    st.caption(f"{len(righe)} partite sopra soglia (nessun tetto di righe) · "
               f"{n_accordo} con il modello d'accordo · {len(righe) - n_accordo} senza accordo. "
               f"Nessuna tabella Legacy o Drago separata: le scelte dei due motori vanno nel "
               f"registro ombra.")
    st.dataframe(tabella_top_mix_mercato(righe), width="stretch", height=420, hide_index=True)


def righe_multipla(righe, etichette):
    """Le righe del Top Mix di mercato scelte per la multipla (per etichetta)."""
    per_etichetta = {etichetta_riga_multipla(p): p for p in righe}
    return [per_etichetta[e] for e in etichette if e in per_etichetta]


def etichetta_riga_multipla(p):
    """Etichetta univoca di una riga nel selettore della multipla."""
    return (f"#{p.get('rank') or '-'} {p['home']} vs {p['away']} — {p['esito']} "
            f"({p['prob_val']}% @ {p['quota'] if p.get('quota') is not None else 'n/d'})")


def calcolatore_multipla(righe):
    """Calcolatore di multipla del Top Mix di mercato (fino a 5 righe).

    Mostra probabilita' combinata, quota equa combinata (1/probabilita') e
    confronto con la quota offerta (prodotto delle quote selezionate), con
    l'edge risultante. L'avviso sull'indipendenza e' SEMPRE mostrato: non e' una
    nota a pie' di pagina opzionale, e' l'ipotesi su cui si regge il calcolo.

    Non giudica le quote basse: una quota 1,10 entra nella multipla come
    qualsiasi altra, l'edge dice quanto paga. La scelta di una quota minima
    resta dell'utente.
    """
    st.markdown("##### 🎟️ Calcolatore di multipla")
    if not righe:
        st.info("Nessuna riga nel Top Mix di mercato: la multipla non si puo' comporre.")
        return
    etichette = [etichetta_riga_multipla(p) for p in righe]
    scelte = st.multiselect(
        "Seleziona fino a 5 righe", etichette,
        max_selections=MASSIMO_RIGHE_MULTIPLA,
        help=f"Massimo {MASSIMO_RIGHE_MULTIPLA} righe. Probabilita' e quota vengono "
             f"dalla stessa fonte (Pinnacle o media dei libri).",
        key="multipla_selezione",
    )
    st.caption(AVVISO_INDIPENDENZA)
    if not scelte:
        return
    selezionate = righe_multipla(righe, scelte)
    esito = multipla([{"partita": f"{p['home']} vs {p['away']}", "esito": p["esito"],
                       "prob": p["prob"], "quota": p["quota"]} for p in selezionate])
    if not esito.get("ok"):
        st.error(esito.get("errore") or "Selezione non valida.")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Probabilita' combinata", f"{esito['probabilita_combinata'] * 100:.2f}%")
    c2.metric("Quota equa (1/prob)", f"{esito['quota_equa']:.2f}")
    c3.metric("Quota offerta", f"{esito['quota_offerta']:.2f}")
    c4.metric("Edge", f"{esito['edge'] * 100:+.2f}%",
              help="quota offerta / quota equa - 1. Positivo: la quota offerta "
                   "paga piu' della quota equa ricavata dalle probabilita' di mercato.")
    st.dataframe(pd.DataFrame(esito["righe"]).rename(columns={
        "n": "#", "partita": "Partita", "esito": "Esito", "prob": "Probabilita'",
        "quota": "Quota"}), width="stretch", hide_index=True)
    if esito["edge"] < 0:
        st.info("Edge negativo: la quota offerta paga MENO della quota equa. "
                "E' la situazione normale (margine del bookmaker), non un errore.")


# Nomi dei due modelli come li chiama il progetto (solo UI/etichette).
# Il motore attuale a due teste e' il "Drago a 2 Teste"; il vecchio, pre-fix
# PR#24, e' il "Legacy". I nomi TECNICI (``current``/``legacy``) e le etichette
# delle SCHEDE del record restano quelli dei referti: qui si cambia come si
# chiamano i due motori in pagina, non cosa contengono i dati.
NOMI_MODELLI = {MODEL_VARIANT_CURRENT: "Drago a 2 Teste", MODEL_VARIANT_LEGACY: "Legacy"}

# Confine fra le due FAMIGLIE di selettore nel Registro visibile: prima di questa
# data le righe Top Mix visibili sono scelte del MODELLO (v1/v2), da questa data
# sono scelte del MERCATO (``topmix_mercato_v3``). Il confine NON e' dedotto dai
# dati: e' la data in cui il selettore visibile e' cambiato, e dichiararlo evita
# che un filtro per stagione o per data faccia credere che una famiglia sia
# vuota perche' i dati mancano.
CONFINE_FAMIGLIA_MERCATO = "09/10/2026"
FAMIGLIA_ICONA = {FAMIGLIA_SELETTORE_MODELLO: "🧠", FAMIGLIA_SELETTORE_MERCATO: "🌟"}

# Colonne delle due tabelle del Registro, in un posto solo: cosi' le due
# tabelle non possono divergere fra loro.
REGISTRO_COLONNE = ["data", "stagione", "campionato", "home", "away", "mercato_standard",
                    "prob_sicuro", "risultato_reale", "esito", "origine"]


def _mostra_registro_modello(righe, titolo, sottotitolo, css_class, altezza=420):
    """Una delle DUE tabelle del Registro: solo le righe di un motore.

    L'etichetta del modello sta nell'intestazione, come nel Top Mix: dentro la
    tabella la colonna della variante sarebbe la stessa parola ripetuta su ogni
    riga, quindi non si mostra. Nessun tetto di righe.

    La colonna della SCHEDA del record (``model_version``) non c'e' piu': dice
    con quale versione di pipeline la riga e' stata SCRITTA, non con quale motore
    e' stata calcolata, e dentro una tabella intitolata a un motore sembrava un
    secondo modello ("scheda post-fix" nella tabella Legacy, per esempio, dove le
    righe del periodo ricostruito le ha scritte il codice attuale). Il dettaglio
    resta dichiarato nella didascalia del blocco Legacy, e i dati hanno ancora il
    campo: e' solo fuori dalla vista delle due tabelle.

    La conversione della data e' quella condivisa (``build_registry_datetime``)
    fatta a monte in tab5, e la colonna resta datetime64: l'ordinamento
    cliccando l'intestazione e' cronologico, il formato italiano lo da' la
    ``DatetimeColumn`` (nessuna stringa riconvertita dopo il sort).
    """
    st.markdown(f"<div class='top-mix-model {css_class}'><b>{titolo}</b> — {len(righe)} righe"
                f"<br><small>{sottotitolo}</small></div>", unsafe_allow_html=True)
    if righe.empty:
        st.info("Nessuna riga di questo motore con i filtri attivi.")
        return
    st.dataframe(
        righe[REGISTRO_COLONNE].sort_values(by="data", ascending=False, na_position="last"),
        width="stretch",
        height=altezza,
        column_config={
            # Colonna davvero datetime64 (non una stringa riconvertita dopo il
            # sort): il formato momentJS tiene la vista italiana identica.
            "data": st.column_config.DatetimeColumn(
                None,
                format="DD/MM/YYYY HH:mm",
            ),
        },
    )


# Colonne della tabella Registro per la famiglia MERCATO: include probabilita'
# del modello e segnale d'accordo, se registrati.
REGISTRO_MERCATO_COLONNE = ["data", "stagione", "campionato", "home", "away",
                            "mercato_standard", "prob_sicuro",
                            "prob_modello_col", "accordo_col",
                            "risultato_reale", "esito", "origine"]


def _mostra_registro_mercato(righe, altezza=420):
    """Tabella Registro per la famiglia MERCATO (topmix_mercato_v3).

    Mostra la probabilita' di mercato (prob_sicuro), la probabilita' del
    modello (Drago) se registrata, e il segnale d'accordo. Se i campi
    mancano, lo dice esplicitamente.
    """
    st.markdown(f"<div class='top-mix-model top-mix-mercato'><b>🌟 Mercato (topmix_mercato_v3)</b>"
                f" — {len(righe)} righe"
                f"<br><small>Scelte del mercato: de-vig proporzionale, soglia 0,55.</small></div>",
                unsafe_allow_html=True)
    if righe.empty:
        st.info("Nessuna riga della famiglia mercato con i filtri attivi.")
        return
    # Prepara le colonne per il modello e l'accordo
    df = righe.copy()
    if "prob_modello" in df.columns:
        df["prob_modello_col"] = df["prob_modello"].apply(
            lambda x: f"{x:.1f}%" if x is not None else "n/d")
    else:
        df["prob_modello_col"] = "non registrato"
    if "accordo_modello" in df.columns:
        df["accordo_col"] = df["accordo_modello"].apply(
            lambda x: "✅" if x else "—" if x is not None else "non registrato")
    else:
        df["accordo_col"] = "non registrato"

    colonne = [c for c in REGISTRO_MERCATO_COLONNE if c in df.columns]
    st.dataframe(
        df[colonne].sort_values(by="data", ascending=False, na_position="last"),
        width="stretch",
        height=altezza,
        column_config={
            "data": st.column_config.DatetimeColumn(None, format="DD/MM/YYYY HH:mm"),
            "prob_sicuro": st.column_config.NumberColumn("P mercato %", format="%.1f%%"),
            "prob_modello_col": st.column_config.TextColumn("P modello Drago %"),
            "accordo_col": st.column_config.TextColumn("D'accordo"),
        },
    )


with tab2:
    st.caption("Una tabella sola, basata sul **mercato**: la scelta (1/X/2) e' quella con la "
               "probabilita' di mercato piu' alta, ammessa se supera il **55%**. Accanto, la "
               "probabilita' del modello (Drago) sullo stesso esito e il segnale **d'accordo** "
               "(modello e mercato entrambi ≥ 55% sullo stesso esito). "
               "Le quote arrivano dal file scritto ogni giorno dal workflow `live_odds.yml`: "
               "l'app non chiama nessuna API di quote. "
               "Le scelte 1X2 di Drago e Legacy non sono piu' in tabella: continuano a essere "
               "registrate nel registro ombra (`sm:registro:ombra`).")
    # --- Pulsante "Calcola Top Mix": calcola, salva nel registro e persisti ---
    # Il risultato va in session_state cosi' un rerun (es. selezione di una riga
    # nel multiselect della multipla) non azzera la sezione. La scrittura nel
    # Registro avviene SOLO qui, alla pressione esplicita del pulsante.
    if st.button("🚀 Calcola Top Mix", type="primary"):
        (top_mercato, top_current, top_legacy, missing, ombra,
         senza_quote) = fetch_and_calc_top_mix()
        # fetch_and_calc_top_mix e' cached (ttl=1800) e il suo `now` e' congelato:
        # si rifiltra contro l'orologio reale PRIMA di mostrare e di salvare, cosi'
        # nessuna partita gia' iniziata puo' entrare nel registro (problema
        # `cache_30min` in audit/results/topmix_registry_tracking.json).
        top_mercato, scartate_mkt = righe_non_iniziate(top_mercato)
        top_current, scartate_cur = righe_non_iniziate(top_current)
        top_legacy, scartate_leg = righe_non_iniziate(top_legacy)
        # Stesso filtro sul registro ombra: nessuna partita gia' iniziata entra.
        ombra, _scartate_ombra = righe_non_iniziate(ombra)
        senza_quote, _scartate_sq = righe_non_iniziate(senza_quote)

        # --- Persisti in session_state: sopravvive ai rerun ---
        st.session_state["topmix_mercato"] = top_mercato
        st.session_state["topmix_current"] = top_current
        st.session_state["topmix_legacy"] = top_legacy
        st.session_state["topmix_missing"] = missing
        st.session_state["topmix_ombra"] = ombra
        st.session_state["topmix_senza_quote"] = senza_quote
        st.session_state["topmix_scartate_inizio"] = scartate_mkt + scartate_cur + scartate_leg

        # --- Scrittura Registro: solo su click, mai su rerun ---
        esiti_save = []
        for p in top_mercato:
            if not p.get('match_id'):
                continue
            args_reg, kwargs_reg = argomenti_registro_top_mix_mercato(p)
            esiti_save.append(save_prediction_entry(*args_reg, **kwargs_reg))
        # Il toast NON e' piu' incondizionato: "salvati!" era scritto anche
        # quando la scrittura remota (PUT su JSONBin, HSET su Upstash) era
        # fallita dentro un `except: pass`.
        n_err_remoto = sum(1 for e in esiti_save if e.get("remoto") == "errore")
        n_nuove = sum(1 for e in esiti_save if e.get("azione") == "aggiunta")
        n_agg = sum(1 for e in esiti_save if e.get("azione") == "aggiornata")
        n_gia = sum(1 for e in esiti_save
                    if e.get("azione") in ("gia_graduata", "gia_presente_altra_versione"))
        n_senza_id = sum(1 for e in esiti_save if e.get("azione") == "senza_chiave")
        if not esiti_save:
            st.info("Nessuna previsione da salvare: nessuna riga del Top Mix ha un match_id valido.")
        else:
            dettaglio = f"{n_nuove} nuove, {n_agg} aggiornate, {n_gia} gia' giudicate (non toccate)"
            if n_senza_id:
                dettaglio += f", {n_senza_id} senza match_id"
            if n_err_remoto:
                st.warning(f"⚠️ {n_err_remoto}/{len(esiti_save)} righe salvate SOLO in locale: "
                           f"scrittura remota fallita (vedi log). Registro: {dettaglio}.")
            else:
                st.success(f"✅ Top Mix nel registro: {dettaglio}.")

        # --- Registro OMBRA: Totali (due righe per candidata) + 1X2 di Drago e
        # Legacy, che non sono piu' il Top Mix visibile. Non vengono mostrate.
        # Se la scrittura fallisce si dice SOLO che non e' avvenuta (mai il contenuto).
        esito_ombra = salva_registro_ombra(
            ombra, righe_modello={MODEL_VARIANT_CURRENT: top_current,
                                  MODEL_VARIANT_LEGACY: top_legacy})
        if esito_ombra.get("remoto") not in ("ok", "disattivato", "nessuna_riga", "nessuna_scrittura"):
            st.warning(f"⚠️ Registro ombra non scritto: "
                       f"{esito_ombra.get('remoto_dettaglio', esito_ombra.get('remoto'))}")

    # --- Visualizzazione risultati da session_state (sopravvive ai rerun) ---
    # Tabella e calcolatore restano visibili finché l'utente non ricarica la
    # pagina o non preme di nuovo "Calcola Top Mix". La scrittura nel Registro
    # NON avviene qui: e' stata fatta nel blocco "if st.button" sopra.
    if "topmix_mercato" in st.session_state:
        top_mercato = st.session_state["topmix_mercato"]
        missing = st.session_state.get("topmix_missing", [])
        senza_quote = st.session_state.get("topmix_senza_quote", [])
        scartate_inizio = st.session_state.get("topmix_scartate_inizio", 0)

        if scartate_inizio:
            st.info(f"⏱️ {scartate_inizio} righe scartate perche' la partita e' gia' iniziata (cache di 30 minuti).")
        if missing:
            st.warning(f"⚠️ Mancanti: {', '.join(missing)}")

        if senza_quote:
            st.warning(
                f"⚠️ {len(senza_quote)} partite SENZA quote di mercato: escluse dal Top Mix "
                f"(nessuna probabilita' inventata). "
                + "; ".join(f"{r['home']} vs {r['away']} ({r['league']}: {r['motivo']})"
                            for r in senza_quote))

        stato_quote = carica_indice_quote_live()
        _avviso_stato_quote(stato_quote, "Top Mix")
        _mostra_non_abbinati_fonte(stato_quote, "Top Mix")
        _mostra_tabella_top_mix_mercato(top_mercato, stato_quote)
        calcolatore_multipla(top_mercato)

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
            sp = predict_elo_probs(sh, sa, camp_sel, season=get_current_season_start_year())
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
def _mostra_affidabilita(record_cal, etichetta=None):
    """Blocco Brier/gap del Registro su un insieme di record (una variante o tutti)."""
    cal_stat = compute_calibration_stats(record_cal)
    if not cal_stat["decise"]:
        return
    if etichetta:
        st.markdown(f"###### Affidabilita' — modello {etichetta}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Partite decise", cal_stat["decise"])
    c2.metric("Brier medio", f"{cal_stat['brier']:.4f}" if cal_stat["brier"] is not None else "n/d",
              help="Media di (probabilita' dichiarata - esito)^2 sulle partite gia' giudicate e con prob_sicuro valido. 0,25 = scommessa alla pari; sotto = meglio del caso per eventi binari.")
    c3.metric("Prob. media", f"{cal_stat['prob_media']:.1f}%" if cal_stat["prob_media"] is not None else "n/d")
    c4.metric("Gap prob - hit", f"{cal_stat['gap']:+.1f} pp" if cal_stat["gap"] is not None else "n/d",
              help="Positivo = il modello SI ESPONE piu' di quanto realizza (sovrastima la coda). E' LA STESSA GRANDAZZA misurata in audit/results/topmix_margins.md §2, ma qui sui dati LIVE del registro.")
    cal_by = calibration_by_mercato(record_cal, min_decise=5)
    if cal_by:
        st.caption("Affidabilita' per mercato e per origine (solo i tagli con almeno 5 partite decise). "
                   "Il gap positivo e' il costo di esporre il massimo fra 7 mercati.")
        st.dataframe(
            pd.DataFrame([{
                "Mercato": r["mercato"], "Origine": tipo_for_origin(r["origine"]),
                "Decise": r["decise"], "Prob. media": r["prob_media"],
                "Hit": r["hit_rate"], "Gap (pp)": r["gap"], "Brier": r["brier"],
            } for r in cal_by]),
            width="stretch", hide_index=True,
            column_config={
                "Prob. media": st.column_config.NumberColumn(format="%.1f%%"),
                "Hit": st.column_config.NumberColumn("Hit", format="%.1f%%"),
                "Gap (pp)": st.column_config.NumberColumn("Gap (pp)", format="%+.1f"),
                "Brier": st.column_config.NumberColumn("Brier", format="%.4f"),
            },
        )
    avvertenza = overall_reliability_transfer_warning(cal_stat)
    if avvertenza:
        st.caption("⚠️ " + avvertenza)


with tab5:
    st.subheader("📒 Registro Predizioni & Tracking")
    if st.button("🔄 Aggiorna Risultati", type="primary"):
        if API_KEY_DATA:
            with st.spinner("Controllando..."): agg, tot = aggiorna_risultati_reali(API_KEY_DATA)
            st.success(f"✅ Aggiornate {agg} partite!" if agg > 0 else f"ℹ️ Nessun nuovo risultato ({tot} in attesa).")
        else: st.error("API Key mancante!")
        
    preds = righe_visibili(load_predictions())
    if not preds: st.warning("Nessuna predizione.")
    else:
        df_preds = pd.DataFrame(preds)
        df_preds['stagione'] = df_preds['data'].apply(calcola_stagione_calcolo)
        # Classificazione esplicita: i record senza model_version restano
        # "Legacy" e NON vengono considerati automaticamente post-fix.
        df_preds['modello'] = [model_label(p) for p in preds]
        # Origine della previsione (Top Mix / Analisi Rapida / Billy): i record
        # scritti prima del campo `origin` vi risalgono dal testo, cosi' la
        # colonna non e' vuota per il passato e la misura e' separabile.
        df_preds['origine'] = [tipo_for_origin(origin_of(p)) for p in preds]
        # Variante del modello (Top Mix a due motori): "Attuale" / "Legacy".
        # Il campo manca nelle righe scritte prima del due-motori: la' decide la
        # DATA (una riga nata prima del merge di PR#24 e' del motore di allora,
        # cioe' Legacy). La colonna non e' mai vuota e i due motori restano
        # separabili, senza spacciare per "Attuale" cio' che l'attuale non ha
        # mai prodotto.
        # `variante_codice` e' il valore macchina (`current`/`legacy`): serve a
        # scegliere le righe delle DUE tabelle, cosi' la scelta non dipende mai
        # da come e' scritta un'etichetta.
        df_preds['variante_codice'] = [model_variant_read(p) for p in preds]
        df_preds['variante'] = [model_variant_label(p) for p in preds]

        # FIX ordinamento Registro: 'data' e' persistito come stringa italiana
        # ("05/09/2026 16:00") e sortarla come testo confronta prima il giorno
        # (04/09 -> 05/09 -> 10/10 -> 17/08 -> 21/08). Qui LA CONVERTIAMO SOLO
        # IN MEMORIA in un vero datetime (wall-clock Europe/Rome): i dati
        # persistiti (predictions.json / JSONBin) non vengono toccati ne'
        # migrati. Date ISO timezone-aware vengono convertite in Europe/Rome;
        # valori mancanti/non validi diventano NaT e finiscono in fondo.
        df_preds['data'] = build_registry_datetime_column(df_preds['data'])

        # NIENTE filtro "Modello": le due tabelle del Registro sono gia' una per
        # motore (Attuale / Legacy). Un filtro in piu' potrebbe svuotarne una e
        # far credere che quel motore non abbia righe.
        f_col1, f_col2, f_col3, f_col4 = st.columns(4)
        with f_col1:
            camp_options = ["Tutti"] + list(LEAGUES_CONFIG.keys())
            filter_camp = st.selectbox("Campionato", camp_options, index=0)
        with f_col2: 
            filter_status = st.selectbox("Esito", ["Tutti", "In Attesa (⏳)", "Vinte (✅)", "Perse (❌)"])
        with f_col3:
            # Senza questo filtro il win rate del Top Mix non e' separabile da
            # quello di Analisi Rapida/Billy (problema `origin_collapsed`).
            # Le etichette esistono gia' nei dati: nessuna lista hardcoded.
            filter_origine = st.selectbox("Origine", ["Tutti"] + sorted(set(df_preds["origine"].tolist())), index=0)
        with f_col4:
            stagioni_reali = sorted(df_preds['stagione'].unique().tolist(), reverse=True)
            default_stagione_idx = 1 if len(stagioni_reali) > 0 else 0
            filter_stagione = st.selectbox("Stagione", ["Tutti"] + stagioni_reali, index=default_stagione_idx)
            
        if filter_camp != "Tutti": df_preds = df_preds[df_preds["campionato"] == filter_camp]
        if filter_status == "In Attesa (⏳)": df_preds = df_preds[df_preds["esito"].isin(["⏳", None])]
        elif filter_status == "Vinte (✅)": df_preds = df_preds[df_preds["esito"] == "✅"]
        elif filter_status == "Perse (❌)": df_preds = df_preds[df_preds["esito"] == "❌"]
        if filter_stagione != "Tutti": df_preds = df_preds[df_preds["stagione"] == filter_stagione]
        if filter_origine != "Tutti": df_preds = df_preds[df_preds["origine"] == filter_origine]
        # Nessun filtro sulla variante: le due tabelle piu' sotto sono gia' una
        # per motore, e nessuna riga viene nascosta da un filtro in piu'.

        # Fix visivo: converte i vecchi 'None' in '⏳' e i risultati vuoti in '-'
        df_display = df_preds.fillna({"esito": "⏳", "risultato_reale": "-"})
        # UNA sola lettura della variante per tutta la pagina: blocchi, tabelle e
        # affidabilita' partono dalla stessa colonna `variante_codice`, calcolata
        # sulle righe del Registro (dove il campo manca davvero). Passare da un
        # DataFrame di pandas invece crea la colonna con NaN, e `str(nan)` e'
        # "nan": le righe senza campo sparivano dal blocco legacy (bug corretto
        # anche dentro `model_variant_read`, ma qui non si passa piu' di li').
        maschera_attuale = df_display["variante_codice"] == MODEL_VARIANT_CURRENT
        maschera_legacy = df_display["variante_codice"] == MODEL_VARIANT_LEGACY
        # DUE blocchi, uno per motore, con le STESSE righe delle due tabelle piu'
        # sotto. La fetta "scheda vecchia" del Registro non e' un terzo modello:
        # sono righe della tabella Legacy, quindi contano nel blocco Legacy e
        # sono dichiarate come dettaglio.
        attuale_records = df_display[maschera_attuale].to_dict("records")
        legacy_records = df_display[maschera_legacy].to_dict("records")
        parti_variante = {MODEL_VARIANT_CURRENT: attuale_records, MODEL_VARIANT_LEGACY: legacy_records}
        resto_records = df_display[~(maschera_attuale | maschera_legacy)].to_dict("records")
        if resto_records:
            # Variante non riconosciuta: non si nasconde (vedi la terza tabella).
            parti_variante["altro"] = resto_records
        all_records = df_display.to_dict("records")
        schede_vecchie = [r for r in legacy_records if not is_current_model(r)]

        # NESSUN totale unico: dal 09/10/2026 il Registro visibile contiene due
        # FAMIGLIE di selettore (le scelte storiche del MODELLO e quelle del
        # MERCATO). Sommarle conterebbe due volte la stessa partita quando le
        # due scelte coincidono (PR #49 §4d: 1144 su 1302) e mescolerebbe due
        # probabilita' diverse nello stesso Brier. Una intestazione per famiglia,
        # ciascuna con il proprio totale, win rate e Brier.
        for _fam, _etichetta, _nota in (
            (FAMIGLIA_SELETTORE_MODELLO,
             f"Modello storico (fino al {CONFINE_FAMIGLIA_MERCATO})",
             "Scelte 1X2 dei due motori (Drago/Legacy) scritte prima del Top Mix "
             "di mercato. Da questa data le nuove scelte del modello vanno nel "
             "registro ombra, quindi questa famiglia non cresce piu'."),
            (FAMIGLIA_SELETTORE_MERCATO,
             f"Mercato (topmix_mercato_v3) — dal {CONFINE_FAMIGLIA_MERCATO}",
             "Scelte del mercato (`topmix_mercato_v3`): de-vig proporzionale, "
             "soglia 0,55, fonte Pinnacle o media dei libri."),
        ):
            _stat = compute_stats(all_records, famiglia=_fam)
            _cal = compute_calibration_stats(all_records, famiglia=_fam)
            st.markdown(f"###### {FAMIGLIA_ICONA[_fam]} {_etichetta}")
            st.caption(_nota)
            if not _stat["total"]:
                st.caption("Nessuna riga di questa famiglia nel Registro visibile "
                           "(con i filtri selezionati).")
                continue
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Totale", _stat["total"])
            c2.metric("Vinte", f"{_stat['wins']} ({_stat['win_rate']:.1f}%)",
                      help="Percentuale sulle sole partite gia' giudicate.")
            c3.metric("Perse / Attesa", f"{_stat['losses']} / {_stat['pending']}")
            c4.metric("Brier medio",
                      f"{_cal['brier']:.4f}" if _cal["brier"] is not None else "n/d",
                      help="Media di (probabilita' dichiarata - esito)^2 sulle "
                           "partite giudicate. Calcolato SOLO su questa famiglia: "
                           "mescolare modello e mercato non descriverebbe nessuno dei due.")
            c5.metric("Gap prob - hit",
                      f"{_cal['gap']:+.1f} pp" if _cal["gap"] is not None else "n/d")

            # --- Sotto-famiglia MODELLO STORICO: blocchi Drago/Legacy ---
            if _fam == FAMIGLIA_SELETTORE_MODELLO:
                # Blocchi per motore, DENTRO la famiglia del modello
                _mostra_blocco_modello(
                    attuale_records, f"🟢 {NOMI_MODELLI[MODEL_VARIANT_CURRENT]}",
                    f"Righe della tabella 🟢 {NOMI_MODELLI[MODEL_VARIANT_CURRENT]}: "
                    "Elo post-fix PR#24, soglia 0,55 sui 1X2 (0,60 senza Elo). Totali fuori dal Top Mix.")
                _mostra_blocco_modello(
                    legacy_records, f"🟠 {NOMI_MODELLI[MODEL_VARIANT_LEGACY]} (Elo pre-fix PR#24)",
                    f"Righe della tabella 🟠 {NOMI_MODELLI[MODEL_VARIANT_LEGACY]}: "
                    "Elo pre-fix con boost xG retroattivo, stesse soglie.")
                # Il dettaglio delle schede NON e' un modello: e' la sotto-fetta del
                # blocco legacy scritta prima del versionamento dei record.
                if schede_vecchie:
                    st.caption(
                        f"📜 Di cui **{len(schede_vecchie)}** con la **scheda vecchia** (record scritto "
                        "prima del versionamento, senza `model_version`): sono nella tabella Legacy e "
                        "contano qui, ma restano fuori dalle metriche del modello attuale.")
                if any(r.get(EXCLUDED_FROM_CURRENT_STATS_FIELD) for r in attuale_records):
                    st.caption(
                        f"ℹ️ {sum(1 for r in attuale_records if r.get(EXCLUDED_FROM_CURRENT_STATS_FIELD))} "
                        "righe della tabella Attuale portano il flag di esclusione dalle metriche del modello "
                        "attuale: contate qui perche' sono nella tabella (l'aggregato di audit le esclude)."
                    )
                # Affidabilita' (Brier) per motore DENTRO la famiglia modello
                righe_famiglia_modello = [r for r in all_records
                                          if famiglia_selettore(r) == FAMIGLIA_SELETTORE_MODELLO]
                parti_variante_modello = {k: [r for r in v
                                              if famiglia_selettore(r) == FAMIGLIA_SELETTORE_MODELLO]
                                          for k, v in parti_variante.items()}
                if len(parti_variante_modello) > 1:
                    for v in sorted(parti_variante_modello, key=lambda v: v != MODEL_VARIANT_CURRENT):
                        _mostra_affidabilita(parti_variante_modello[v], etichetta=NOMI_MODELLI.get(v, MODEL_VARIANT_LABELS.get(v, v)))
                else:
                    _mostra_affidabilita(righe_famiglia_modello)

        # La SCHEDA del record (con quale versione di pipeline la riga e' stata
        # scritta) e' un altro discorso rispetto al motore che l'ha calcolata, e
        # non compare piu' come colonna: si dice a parole, una volta.
        st.caption(
            "**Come sono state scritte le righe** (non e' il motore, che e' il titolo delle due tabelle): "
            f"{MODEL_LABEL_CURRENT} = scritta dal versionamento attuale "
            f"(`{MODEL_VERSION_CURRENT}`, dal 04/09/2026) · "
            f"{MODEL_LABEL_PRE_FIX} = scritta prima del fix di regolarizzazione · "
            f"{MODEL_LABEL_LEGACY} = riga antecedente al versionamento."
        )

        # --- TABELLE DEL REGISTRO: organizzate per FAMIGLIA ---
        # Famiglia MERCATO: una tabella sola con probabilita' del modello e accordo
        maschera_mercato = df_display.apply(
            lambda r: famiglia_selettore(r.to_dict()) == FAMIGLIA_SELETTORE_MERCATO, axis=1)
        df_mercato = df_display[maschera_mercato]
        if not df_mercato.empty:
            _mostra_registro_mercato(df_mercato)
        else:
            st.info("Nessuna riga della famiglia mercato con i filtri attivi.")

        st.divider()

        # Famiglia MODELLO STORICO: due tabelle, una per motore
        _mostra_registro_modello(
            df_display[maschera_attuale], f"🟢 {NOMI_MODELLI[MODEL_VARIANT_CURRENT]}",
            "Elo attuale (models/elo_engine.py, post-fix PR#24) · soglia 0,55 sui 1X2 (0,60 senza Elo)",
            "top-mix-current")
        _mostra_registro_modello(
            df_display[maschera_legacy], f"🟠 {NOMI_MODELLI[MODEL_VARIANT_LEGACY]}",
            "Elo pre-fix PR#24 (models/elo_engine_legacy.py, boost xG retroattivo) · stesse soglie",
            "top-mix-legacy")
        # Una riga con una variante fuori dalle due non sparisce dal Registro:
        # finisce in una terza tabella di controllo, cosi' il totale mostrato
        # resta verificabile a occhio.
        resto = df_display[~(maschera_attuale | maschera_legacy)]
        if len(resto):
            st.warning(f"⚠️ {len(resto)} righe con variante non riconosciuta (ne' attuale ne' legacy): "
                       f"mostrate a parte, non nascoste.")
            st.dataframe(resto[REGISTRO_COLONNE + ["variante"]], width="stretch", height=200)

        # --- REGISTRO OMBRA: statistiche read-only ---
        # "Aggiorna Risultati" giudica anche le righe ombra (aggiorna_esiti_ombra,
        # stesse regole e stesse risposte HTTP). Qui mostriamo il loro stato,
        # i Brier per selettore e il confronto con il mercato sulle stesse partite.
        try:
            from registry_store import load_ombra_rows
            ombra_righe, ombra_fonte = load_ombra_rows(strict=True)
            if ombra_righe:
                st.divider()
                st.markdown("###### 👻 Registro ombra (sola lettura)")
                st.caption(
                    f"Righe ombra: **{len(ombra_righe)}** (fonte: {ombra_fonte}). "
                    "Drago e Legacy dal 09/10/2026 + Totali. "
                    "'Aggiorna Risultati' le giudica con le stesse regole del Registro visibile.")

                # Conteggio per stato
                ombra_decise = [r for r in ombra_righe
                                if r.get("esito") in ("✅", "❌")]
                ombra_pending = [r for r in ombra_righe
                                 if r.get("esito") in (None, "⏳")]
                c1, c2, c3 = st.columns(3)
                c1.metric("Totale ombra", len(ombra_righe))
                c2.metric("Giudicate", len(ombra_decise))
                c3.metric("In attesa", len(ombra_pending))

                # Statistiche per selettore (Drago / Legacy)
                for _variante, _etichetta in (
                    (MODEL_VARIANT_CURRENT, "Drago (ombra)"),
                    (MODEL_VARIANT_LEGACY, "Legacy (ombra)"),
                ):
                    righe_v = [r for r in ombra_righe
                               if r.get("model_variant") == _variante
                               and r.get("selector_version") == SELECTOR_VERSION_OMBRA_1X2]
                    if not righe_v:
                        continue
                    _stat_v = stats_all(righe_v)
                    _cal_v = compute_calibration_stats(righe_v)
                    st.markdown(f"**{_etichetta}** — {_stat_v['total']} righe "
                                f"({_stat_v['decided']} giudicate)")
                    if _cal_v["decise"]:
                        c1, c2, c3 = st.columns(3)
                        c1.metric("Hit rate", f"{_stat_v['win_rate']:.1f}%")
                        c2.metric("Brier", f"{_cal_v['brier']:.4f}"
                                  if _cal_v["brier"] is not None else "n/d")
                        c3.metric("Gap", f"{_cal_v['gap']:+.1f} pp"
                                  if _cal_v["gap"] is not None else "n/d")

                # Confronto ombra vs mercato sulle stesse partite
                mercato_per_match = {}
                for r in all_records:
                    mid = r.get("match_id")
                    if mid and famiglia_selettore(r) == FAMIGLIA_SELETTORE_MERCATO:
                        mercato_per_match[mid] = r

                confronto = []
                for r in ombra_decise:
                    mid = r.get("match_id")
                    if mid and mid in mercato_per_match:
                        mkt = mercato_per_match[mid]
                        if mkt.get("esito") in ("✅", "❌"):
                            confronto.append({
                                "match_id": mid,
                                "ombra_hit": r.get("esito") == "✅",
                                "mercato_hit": mkt.get("esito") == "✅",
                                "ombra_prob": r.get("prob_sicuro"),
                                "mercato_prob": mkt.get("prob_sicuro"),
                            })

                if confronto:
                    st.markdown("**Confronto ombra 1X2 vs mercato (stesse partite giudicate)**")
                    n_inter = len(confronto)
                    hit_ombra = sum(1 for c in confronto if c["ombra_hit"])
                    hit_mercato = sum(1 for c in confronto if c["mercato_hit"])
                    brier_ombra = (sum((c["ombra_prob"] / 100.0 - (1 if c["ombra_hit"] else 0)) ** 2
                                       for c in confronto) / n_inter) if n_inter else None
                    brier_mercato = (sum((c["mercato_prob"] / 100.0 - (1 if c["mercato_hit"] else 0)) ** 2
                                         for c in confronto) / n_inter) if n_inter else None
                    c1, c2, c3, c4, c5 = st.columns(5)
                    c1.metric("Partite in comune", n_inter)
                    c2.metric("Hit ombra", f"{hit_ombra / n_inter * 100:.1f}%")
                    c3.metric("Hit mercato", f"{hit_mercato / n_inter * 100:.1f}%")
                    c4.metric("Brier ombra", f"{brier_ombra:.4f}" if brier_ombra is not None else "n/d")
                    c5.metric("Brier mercato", f"{brier_mercato:.4f}" if brier_mercato is not None else "n/d")
            else:
                st.caption("👻 Registro ombra vuoto (nessuna riga trovata).")
        except Exception as e:
            st.warning(f"⚠️ Registro ombra non leggibile: {e}")
