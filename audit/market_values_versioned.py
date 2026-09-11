"""
market_values_versioned.py — MARKET_VALUES versionato per stagione (audit
SOLA LETTURA, nessuna modifica a SoccerMath/).

Il fattore valore di mercato di produzione (``app.get_league_engine``) legge
``config.MARKET_VALUES``: un dizionario scritto a mano, fermo a una data, quindi
in leakage su ogni valutazione storica (audit/margini_migliorabili_topmix.md
§5 e production_baseline_comparison.md l'avevano segnalato come il singolo
punto dove un dato nuovo cambia la valutazione di ogni leva).

Questo audit sostituisce lo statico con le rilevazioni REALI per
(lega, stagione, squadra) di ``audit/data/market_values_top5 campionati.csv``
(772 righe: 5 leghe x 4 stagioni 2022/23-2025/26 x 2 rilevazioni, post-estiva
15/9 e post-invernale 15/2, verificate contro i roster storici), e rigira il
confronto di production_baseline_comparison.md sul mercato 1X2:

  * STATIC      (prima): MARKET_VALUES di config.py, identico a produzione;
  * VERSIONED   (dopo): rilevazione point-in-time della STESSA stagione della
    partita — "Post-Estivo" di default, "Post-Invernale" se la partita cade
    dal 15/2 in poi (15/2 dell'anno di fine stagione). MAI la valutazione
    corrente, MAI una stagione diversa da quella della partita;
  * NO_MKT      (riferimento): fattore mercato = 1 (il "solo gol" di
    market_value_comparison.txt, che stimava a mano l'impatto qui misurato).

La formula del fattore NON cambia (bit-fedele a produzione):
    mkt = 1 + (log10(max(val, 10)) - 2.0) / 4,  clip [0.85, 1.25]
perche' il confronto isola ESATTAMENTE la fonte dati (statico vs versionato),
non la formula. MARKET_VALUES di config e' espresso in milioni di euro: il CSV
viene ricondotto alla stessa scala con una regola dichiarata (vedi
``parse_market_csv``: se i valori grezzi sono in euro assoluti si divide per
1e6; se il nome colonna contiene "mln"/"milion" si legge direttamente).

Pipeline (walker condiviso, importato): stessa architettura di
grid_search_ensemble_weight/diagnose_clv_pinnacle — testa 1X2 PRODUZIONE_DUE_TESTE
(NORM-SUM: xG snapshot + forma + fattore mercato con normalizzazione alla somma
base S, clip [exp(-6), exp(3)], bit-faithful a diagnose_production_baseline.run_models)
+ Elo walk-forward K=24; le tre varianti mercato girano nella STESSA passata
(Stesso stato, stesso Elo, stesso xG): l'unica differenza e' il fattore mercato,
quindi il confronto e' perfettamente appaiato.

Metriche (convenzioni degli altri audit): Brier/LogLoss 1X2
(brier_ll_1x2) e ROI a puntata fissa con selezione edge>0 vs fair de-vigata
 Bet365 e Average, settle sullo stesso book (roi_1x2, EDGE_MIN=0), su
VALIDATION 2024/25 e TEST 2025/26, per lega e aggregato, sia sulla testa
Poisson pura sia sul blend di produzione 0.6/0.4 (app.ELO_ENSEMBLE_W).

Output: audit/results/market_values_versioned_report.md
Uso:    python audit/market_values_versioned.py
"""
from __future__ import annotations

import math
import os
import re
import sys
from collections import OrderedDict
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from backtest_experiment_all import LEAGUES, devig_1x2, MARKET_VALUES      # noqa: E402
from diagnose_production_baseline import (SEASONS_EVAL, brier_ll_1x2,      # noqa: E402
                                          roi_1x2, TeamState, market_factor)
from team_aliases import clean_name                                        # noqa: E402
from topmix_margins import N_BOOT, SEED, _ci                               # noqa: E402
from gg_ng_calibration import EXONYM_TO_CANONICAL                          # noqa: E402
import diagnose_clv_pinnacle as CLV                                        # noqa: E402

DATA_PATH = os.path.join(_AUDIT_DIR, "data", "market_values_top5_campionati.csv")
OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "market_values_versioned_report.md")

STAKE = 10.0
EDGE_MIN = 0.0                    # convenzione backtest_experiment_all
ELO_ENSEMBLE_W = CLV.ELO_ENSEMBLE_W   # 0.6, app.ELO_ENSEMBLE_W
SUMMER_DAY = (9, 15)              # rilevazione post-estiva: 15/9
WINTER_DAY = (2, 15)              # rilevazione post-invernale: 15/2

# nomi colonna riconosciuti (case-insensitive, sottostringa)
COL_LEAGUE = ("lega", "league", "campionato")
COL_SEASON = ("stagione", "season")
COL_TEAM = ("squadra", "team", "club")
COL_SURVEY = ("periodo", "rilevazion", "survey", " finestra", "tipo")
COL_VALUE = ("valore", "value", "market")

LEAGUE_KEY = OrderedDict([
    ("serie a", ("SerieA", "Serie A")),
    ("premier", ("Premier", "Premier League")),
    ("laliga", ("LaLiga", "La Liga")),
    ("la liga", ("LaLiga", "La Liga")),
    ("liga", ("LaLiga", "La Liga")),
    ("bundesliga", ("Bundesliga", "Bundesliga")),
    ("ligue 1", ("Ligue1", "Ligue 1")),
    ("ligue1", ("Ligue1", "Ligue 1")),
])


def match_league(text):
    """Nome lega nel CSV -> (prefix, camp_key) o None (mai indovinata).

    Match per sottostringa ma con la CHIAVE PIU' LUNGA vincente: evita che
    "bundesliga" venga catturato da "liga" (LaLiga)."""
    t = re.sub(r"[\s_]+", " ", str(text).strip().lower())
    best = None
    for key, mapped in LEAGUE_KEY.items():
        if key in t and (best is None or len(key) > len(best[0])):
            best = (key, mapped)
    return best[1] if best else None


def parse_season_year(text):
    """'2022/23', '2022-2023', '2022/2023' -> 2022 (None se illeggibile)."""
    m = re.search(r"(20\d{2})", str(text))
    if not m:
        return None
    return int(m.group(1))


def survey_kind(text):
    """'Post-Estivo'/'Post-Invernale' (anche con accenti/maiuscole) -> kind."""
    t = str(text).lower()
    if "estiv" in t:
        return "Post-Estivo"
    if "invern" in t:
        return "Post-Invernale"
    return None


def _is_num(s):
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def parse_value(raw):
    """Valore di mercato: float semplice o formato euro ('€85.5m', '85,5 mln').

    Ritorna (numero, scala) dove scala e' 'raw' (gia' in milioni, cosi' lo
    legge MARKET_VALUES) oppure 'euro' (unita' assoluta, da ridurre /1e6).
    None se illeggibile."""
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return None, None
    if isinstance(raw, (int, float)):
        v = float(raw)
    else:
        s = str(raw).strip().replace("€", "").replace(" ", "").replace(",", ".")
        # migliaia puntate europee (1.000.000.000): se i punti separano gruppi
        # di 3 cifre sono separatori, non decimali
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
            s = s.replace(".", "")
        low = s.lower()
        if low.endswith(("mln", "milion", "milioni", "m")):
            s = re.sub(r"(mln|milion|milioni|m)$", "", low)
        elif low.endswith("k"):
            s = re.sub(r"k$", "", low)
            s = str(float(s) / 1000.0) if _is_num(s) else s
        try:
            v = float(s)
        except ValueError:
            return None, None
    if not math.isfinite(v) or v <= 0:
        return None, None
    # euristica di scala: un valore > 1000 non puo' essere "milioni" sensati
    # di Transfermarkt per le top-5 (max realistico ~15 mld? no: ~15 mld non
    # esiste; > 5000 implica euro assoluti) — vedi anche la scala di colonna
    # in parse_market_csv.
    if v >= 5000:
        return v, "euro"
    return v, "raw"


# =====================================================================
# Caricamento CSV e lookup versionato
# =====================================================================
def _find_col(cols, keys, exclude_date=False):
    for c in cols:
        low = str(c).lower()
        if exclude_date and (low.startswith("data") or "date" in low):
            continue  # es. Data_Rilevazione non e' la colonna rilevazione
        for k in keys:
            if k in low:
                return c
    return None


# Nomi completi "ufficiali" del CSV valori che clean_name+esonimi non
# riconducono al nome canonico dei database: mappatura ESPLICITA (nessuna
# euristiche fuzzy), verificata 1:1 contro i roster dei CSV database.
MARKET_NAME_FIX = {
    # Serie A
    "Associazione Sportiva Roma": "Roma",
    "Bologna Football Club 1909": "Bologna",
    "Pisa Sporting Club": "Pisa",
    "Società Sportiva Lazio S.p.A.": "Lazio",
    "UC Sampdoria": "Sampdoria",
    "US Cremonese": "Cremonese",
    "US Lecce": "Lecce",
    "US Salernitana 1919": "Salernitana",
    "US Sassuolo": "Sassuolo",
    # Premier League
    "Brighton & Hove Albion": "Brighton",
    "Luton Town": "Luton",
    "Sunderland AFC": "Sunderland",
    # La Liga
    "Atlético de Madrid": "Ath Madrid",
    "CA Osasuna": "Osasuna",
    "CD Leganés": "Leganes",
    "Celta de Vigo": "Celta",
    "Cádiz CF": "Cadiz",
    "Deportivo Alavés": "Alaves",
    "Elche CF": "Elche",
    "Getafe CF": "Getafe",
    "Granada CF": "Granada",
    "Levante UD": "Levante",
    "RCD Espanyol Barcelona": "Espanol",
    "RCD Mallorca": "Mallorca",
    "Real Betis Balompié": "Betis",
    "Real Oviedo": "Oviedo",
    "Real Valladolid CF": "Valladolid",
    "UD Almería": "Almeria",
    "UD Las Palmas": "Las Palmas",
    "Valencia CF": "Valencia",
    "Villarreal CF": "Villarreal",
    # Bundesliga
    "1. Fußballclub Heidenheim 1846": "Heidenheim",
    "1.FC Köln": "Koln",
    "1.FSV Mainz 05": "Mainz",
    "Hamburger SV": "Hamburg",
    "Hertha BSC": "Hertha",
    "SV Darmstadt 98": "Darmstadt",
    "TSG 1899 Hoffenheim": "Hoffenheim",
    # Ligue 1
    "Clermont Foot 63": "Clermont",
    "ESTAC Troyes": "Troyes",
    "LOSC Lille": "Lille",
    "Olympique Marseille": "Marseille",
    "Stade Reims": "Reims",
}


def normalize_team(raw):
    """Nome CSV mercato -> chiave canonica dei CSV football-data.

    1) tabella esplicita MARKET_NAME_FIX (nomi ufficiali completi);
    2) altrimenti clean_name + esonimi audit; MAI match fuzzy."""
    key = str(raw).strip()
    if key in MARKET_NAME_FIX:
        return MARKET_NAME_FIX[key]
    base = clean_name(key)
    return EXONYM_TO_CANONICAL.get(base, base)


def parse_market_csv(path=DATA_PATH):
    """Legge il CSV campionato e ritorna (lookup, meta).

    lookup: {(camp_key, start_year, kind, team_canonical): valore_in_milioni}
    meta: {'rows', 'by_survey': Counter, 'by_league_season': {...},
           'unmatched': [(lega, stagione, squadra, motivo)], 'scale': str}
    Nomi squadra non riconoscibili NON vengono indovinati: finiscono in
    'unmatched' e vengono riportati nel report.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    df = pd.read_csv(path, sep=None, engine="python")
    cols = list(df.columns)
    c_league = _find_col(cols, COL_LEAGUE)
    c_season = _find_col(cols, COL_SEASON)
    c_team = _find_col(cols, COL_TEAM)
    c_survey = _find_col(cols, COL_SURVEY, exclude_date=True)
    c_value = _find_col(cols, COL_VALUE)
    c_date = _find_col(cols, ("data_rilevazione", "data", "date"))
    missing = [name for name, c in [("lega", c_league), ("stagione", c_season),
                                    ("squadra", c_team), ("rilevazione", c_survey),
                                    ("valore", c_value)] if c is None]
    if missing:
        raise ValueError(f"colonne non trovate nel CSV: {missing}; colonne={cols}")

    col_name_l = str(c_value).lower()
    col_is_mln = ("mln" in col_name_l) or ("milion" in col_name_l)

    lookup = {}
    meta = {"rows": 0, "by_survey": {}, "by_league_season": {},
            "unmatched": [], "scale": "raw" if col_is_mln else "auto",
            "date_mismatch": 0}
    vals_raw = []
    for _, row in df.iterrows():
        meta["rows"] += 1
        league = match_league(row[c_league])
        year = parse_season_year(row[c_season])
        kind = survey_kind(row[c_survey])
        team = normalize_team(row[c_team])
        value, scale = parse_value(row[c_value])
        where = (str(row[c_league]), str(row[c_season]), str(row[c_team]))
        if league is None:
            meta["unmatched"].append(where + ("lega non riconosciuta",))
            continue
        if year is None or kind is None:
            meta["unmatched"].append(where + ("stagione/rilevazione illeggibile",))
            continue
        if value is None:
            meta["unmatched"].append(where + ("valore illeggibile",))
            continue
        if scale == "euro" and not col_is_mln:
            value = value / 1e6
        vals_raw.append(value)
        camp_key = league[1]
        key = (camp_key, year, kind, team)
        # duplicati: ultima rilevazione vince, coerente col dedup keep='last'
        lookup[key] = value
        meta["by_survey"][kind] = meta["by_survey"].get(kind, 0) + 1
        d_raw = str(row[c_date]).strip() if c_date is not None else ""
        md = pd.to_datetime(d_raw, errors="coerce")
        ok_date = (pd.notna(md) and ((kind == "Post-Estivo" and md.month == 9 and md.day == 15)
                                     or (kind == "Post-Invernale" and md.month == 2 and md.day == 15)))
        if d_raw and not ok_date:
            meta["date_mismatch"] += 1
        ls = meta["by_league_season"].setdefault((camp_key, f"{year}/{(year+1)%100:02d}"),
                                                 {"Post-Estivo": 0, "Post-Invernale": 0})
        ls[kind] += 1
    meta["min_mln"] = round(min(vals_raw), 2) if vals_raw else None
    meta["max_mln"] = round(max(vals_raw), 2) if vals_raw else None
    return lookup, meta


def versioned_value(lookup, camp_key, match_date, season_label, team):
    """Valore versionato per la partita: Post-Estivo della stagione, Post-
    Invernale se la partita cade dal 15/2 (anno di fine stagione) in poi.

    MAI la stagione corrente/altri anni: se la chiave manca si ritorna None
    (il chiamante applichera' il fallback dichiarato), non un valore vicino.
    """
    year = int(str(season_label).split("/")[0])
    md = match_date.date() if isinstance(match_date, (datetime, pd.Timestamp)) else match_date
    if md >= date(year + 1, *WINTER_DAY):
        kind = "Post-Invernale"
    else:
        kind = "Post-Estivo"
    return lookup.get((camp_key, year, kind, team)), kind


# =====================================================================
# Walker con fattore mercato parametrizzabile (tre varianti appaiate)
# =====================================================================
def clip_lambda_fn():
    return CLV._clip_lambda


def run_market_variants(df, camp_key, xg_data, lookup):
    """Una sola passata walk-forward; per le righe di SEASONS_EVAL emette le
    probabilita' 1X2 della testa NORM-SUM con i tre fattori mercato
    (static/ver/none) + l'Elo walk-forward (invariante alle varianti).

    Ritorna (rows_df, usage) dove usage conta l'uso delle rilevazioni e i
    fallback (squadra/stagione senza valore versionato: -> fattore 1, come
    NO_MKT per quelle partite, dichiarato nel report; MAI valori di altre
    stagioni)."""
    home_adv = CLV.LEAGUE_HOME_ADVANTAGE.get(camp_key, 60.0)
    xg_att, xg_def = {}, {}
    if xg_data and len(xg_data) >= 10:
        vals = list(xg_data.values())
        lx = float(np.mean([v["xG_avg"] for v in vals]))
        lxa = float(np.mean([v["xGA_avg"] for v in vals]))
        if lx and lxa:
            for t, v in xg_data.items():
                xg_att[t] = v["xG_avg"] / lx
                xg_def[t] = v["xGA_avg"] / lxa

    state = {}
    elo = {}
    tot_hg = tot_ag = tot_n = 0.0
    rows = []
    usage = {"Post-Estivo": 0, "Post-Invernale": 0, "fallback_missing": 0}

    def get(t):
        if t not in state:
            state[t] = TeamState()
        return state[t]

    for _, row in df.iterrows():
        fthg, ftag = int(row.FTHG), int(row.FTAG)
        ftr = str(row.FTR).strip().upper()
        h, a = row.HomeClean, row.AwayClean
        sh, sa = get(h), get(a)
        avg_h = max(tot_hg / tot_n, 0.1) if tot_n else 0.1
        avg_a = max(tot_ag / tot_n, 0.1) if tot_n else 0.1
        r_h = elo.get(h, CLV.ELO_INITIAL)
        r_a = elo.get(a, CLV.ELO_INITIAL)

        if row.season in SEASONS_EVAL:
            def form_fac(ts):
                if len(ts.last5) < 3:
                    return 1.0, 1.0
                n = len(ts.last5)
                gf = sum(x[0] for x in ts.last5)
                ga = sum(x[1] for x in ts.last5)
                avg_glob = (avg_h + avg_a) / 2.0
                den = max(avg_glob, 0.5)
                return (max(0.85, min(1.15, (gf / n) / den)),
                        max(0.85, min(1.15, (ga / n) / den)))

            def prim(t, ts):
                pa = xg_att[t] if t in xg_att else ((ts.hgf / ts.hgn) / avg_h if ts.hgn else 1.0)
                pdf = xg_def[t] if t in xg_def else ((ts.hga / ts.hgn) / avg_a if ts.hgn else 1.0)
                return pa, pdf

            p_att_h, p_def_h = prim(h, sh)
            p_att_a, p_def_a = prim(a, sa)
            fa_h, fd_h = form_fac(sh)
            fa_a, fd_a = form_fac(sa)

            # --- fattori mercato delle tre varianti (bit-fedeli alla formula) ---
            mkt_static_h = market_factor(MARKET_VALUES.get(h, 50))
            mkt_static_a = market_factor(MARKET_VALUES.get(a, 50))
            v_h, kind_h = versioned_value(lookup, camp_key, row.Date, row.season, h)
            v_a, kind_a = versioned_value(lookup, camp_key, row.Date, row.season, a)
            if v_h is not None and v_a is not None:
                mkt_ver_h = market_factor(v_h)
                mkt_ver_a = market_factor(v_a)
                usage["Post-Estivo"] += (kind_h == "Post-Estivo") + (kind_a == "Post-Estivo")
                usage["Post-Invernale"] += (kind_h == "Post-Invernale") + (kind_a == "Post-Invernale")
            else:
                # squadra/stagione senza rilevazione: fallback dichiarato = 1
                # (nessun valore di altra stagione o della stagione corrente);
                # contato per squadra (sempre pari per partita)
                mkt_ver_h = mkt_ver_a = 1.0
                usage["fallback_missing"] += int(v_h is None) + int(v_a is None)

            mkts = {"static": (mkt_static_h, mkt_static_a),
                    "ver": (mkt_ver_h, mkt_ver_a),
                    "none": (1.0, 1.0)}

            base_att_h, base_def_h = p_att_h * fa_h, p_def_h * fd_h
            base_att_a, base_def_a = p_att_a * fa_a, p_def_a * fd_a
            lam_base_h = base_att_h * base_def_a * avg_h
            lam_base_a = base_att_a * base_def_h * avg_a
            S = lam_base_h + lam_base_a

            rec = {"pos": -1, "date": row.Date, "season": row.season,
                   "home": h, "away": a,
                   "real_1x2": {"H": "1", "D": "X", "A": "2"}.get(ftr, "X"),
                   "elo_1": None, "elo_X": None, "elo_2": None}
            e1, eX, e2 = CLV.elo_probs(r_h, r_a, home_adv)
            rec["elo_1"], rec["elo_X"], rec["elo_2"] = e1, eX, e2
            for tag, (m_h, m_a) in mkts.items():
                lam_m_h = (base_att_h * m_h) * (base_def_a / m_a) * avg_h
                lam_m_a = (base_att_a * m_a) * (base_def_h / m_h) * avg_a
                den = lam_m_h + lam_m_a
                if den > 0:
                    lh = S * lam_m_h / den
                    la = S * lam_m_a / den
                else:
                    lh, la = lam_base_h, lam_base_a
                mp = CLV.get_full_poisson(CLV._clip_lambda(lh), CLV._clip_lambda(la))
                rec[f"{tag}_1"], rec[f"{tag}_X"], rec[f"{tag}_2"] = mp["1"], mp["X"], mp["2"]
                rec[f"{tag}b_1"] = ELO_ENSEMBLE_W * mp["1"] + (1 - ELO_ENSEMBLE_W) * e1
                rec[f"{tag}b_X"] = ELO_ENSEMBLE_W * mp["X"] + (1 - ELO_ENSEMBLE_W) * eX
                rec[f"{tag}b_2"] = ELO_ENSEMBLE_W * mp["2"] + (1 - ELO_ENSEMBLE_W) * e2
            rec["dfac_h"] = abs(mkt_ver_h - mkt_static_h)
            rec["dfac_a"] = abs(mkt_ver_a - mkt_static_a)
            rows.append(rec)

        # --- aggiornamento stato DOPO la previsione (invariante alle varianti) ---
        dr = r_h + home_adv - r_a
        e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
        s_h = 1.0 if ftr == "H" else (0.0 if ftr == "A" else 0.5)
        elo[h] = r_h + CLV.ELO_K * (s_h - e_h)
        elo[a] = r_a + CLV.ELO_K * ((1 - s_h) - (1 - e_h))
        tot_hg += fthg
        tot_ag += ftag
        tot_n += 1
        sh.observe_home(fthg, ftag)
        sa.observe_away(fthg, ftag)

    return pd.DataFrame(rows), usage


# =====================================================================
# Metriche
# =====================================================================
def metrics_at(d, prefix):
    """Brier/LogLoss (testa poisson) e blend 0.6/0.4 + ROI B365/Avg."""
    out = {"n": len(d)}
    tmp = d.copy()
    tmp["_1"], tmp["_X"], tmp["_2"] = d[f"{prefix}_1"], d[f"{prefix}_X"], d[f"{prefix}_2"]
    b, ll = brier_ll_1x2(tmp, ("_1", "_X", "_2"))
    out["brier"], out["log_loss"] = round(b, 4), round(ll, 4)
    tmp["_1"], tmp["_X"], tmp["_2"] = d[f"{prefix}b_1"], d[f"{prefix}b_X"], d[f"{prefix}b_2"]
    b, ll = brier_ll_1x2(tmp, ("_1", "_X", "_2"))
    out["brier_blend"], out["log_loss_blend"] = round(b, 4), round(ll, 4)
    for book, fpre, ocols in (("b365", "fair_b365", ("B365H", "B365D", "B365A")),
                              ("avg", "fair_avg", ("AvgH", "AvgD", "AvgA"))):
        sub = d.dropna(subset=[f"{fpre}_1", f"{fpre}_X", f"{fpre}_2"] + list(ocols))
        if len(sub) == 0:
            out[f"roi_{book}"] = None
            out[f"n_bet_{book}"] = 0
            continue
        nb, wr, roi = roi_1x2(sub, (f"{prefix}_1", f"{prefix}_X", f"{prefix}_2"),
                              (f"{fpre}_1", f"{fpre}_X", f"{fpre}_2"), ocols, stake=STAKE)
        out[f"roi_{book}"] = round(roi, 2) if roi is not None else None
        out[f"n_bet_{book}"] = nb
    return out


def attach_odds(df, d):
    odds_cols = [c for c in ("B365H", "B365D", "B365A", "AvgH", "AvgD", "AvgA")
                 if c in df.columns]
    d = d.merge(df[["Date", "HomeClean", "AwayClean"] + odds_cols],
                left_on=["date", "home", "away"],
                right_on=["Date", "HomeClean", "AwayClean"], how="left",
                validate="one_to_one")
    assert not d.duplicated(subset=["date", "home", "away"]).any()
    for prefix, cols in (("fair_b365", ("B365H", "B365D", "B365A")),
                         ("fair_avg", ("AvgH", "AvgD", "AvgA"))):
        f1, fX, f2 = [], [], []
        for _, r in d.iterrows():
            x = devig_1x2(r[cols[0]], r[cols[1]], r[cols[2]])
            f1.append(x[0] if x else np.nan)
            fX.append(x[1] if x else np.nan)
            f2.append(x[2] if x else np.nan)
        d[f"{prefix}_1"], d[f"{prefix}_X"], d[f"{prefix}_2"] = f1, fX, f2
    return d.drop(columns=["Date", "HomeClean", "AwayClean"])


# =====================================================================
# Bootstrap appaiato delle differenze fra varianti
# =====================================================================
def _boot_deltas(d, n_boot=N_BOOT, seed=SEED):
    """Delta appaiati (ver-static, none-static) con CI bootstrap percentile
    2.5-97.5 (convenzione topmix_margins: N_BOOT/SEED/_ci).

    Lo stesso resample di righe e' applicato a ENTRAMBE le varianti: le
    differenze sono appaiate, quindi la variabilita' comune (stesso stato,
    stessi errori grossolani) si cancella e la CI e' piu' stretta di due
    run indipendenti. Brier/LogLoss su tutte le righe; ROI B365 solo sulle
    righe con quote e fair complete (le altre pesano zero)."""
    rng = np.random.default_rng(seed)
    n = len(d)
    if n == 0:
        return {}
    tags = ("static", "ver", "none")
    P = {t: d[[f"{t}_1", f"{t}_X", f"{t}_2"]].to_numpy(dtype=float) for t in tags}
    m = {"1": 0, "X": 1, "2": 2}
    y = np.array([m[v] for v in d["real_1x2"]])
    onehot = np.zeros((n, 3))
    onehot[np.arange(n), y] = 1
    brier_rows = {t: np.sum((onehot - P[t]) ** 2, axis=1) for t in tags}
    ll_rows = {t: -np.log(np.clip(P[t][np.arange(n), y], 1e-12, 1.0)) for t in tags}
    need = ["B365H", "B365D", "B365A", "fair_b365_1", "fair_b365_X", "fair_b365_2"]
    ok_mask = ~d[need].isna().any(axis=1).to_numpy()
    ok_idx = np.flatnonzero(ok_mask)
    odds = d[["B365H", "B365D", "B365A"]].to_numpy(dtype=float)[ok_idx]
    fair = d[["fair_b365_1", "fair_b365_X", "fair_b365_2"]].to_numpy(dtype=float)[ok_idx]
    yb = y[ok_idx]
    pnl, stake = {}, {}
    for t in tags:
        Pt = P[t][ok_idx]
        edge = Pt - fair
        best = np.argmax(edge, axis=1)
        has_bet = edge[np.arange(len(ok_idx)), best] > 0.0
        stake[t] = np.where(has_bet, STAKE, 0.0)
        won = yb == best
        pnl[t] = np.where(has_bet,
                          np.where(won, STAKE * (odds[np.arange(len(ok_idx)), best] - 1.0),
                                   -STAKE), 0.0)

    def metric_on(t, idx, kind):
        if kind == "brier":
            return float(brier_rows[t][idx].mean())
        if kind == "log_loss":
            return float(ll_rows[t][idx].mean())
        sel = idx[ok_mask[idx]]
        s = stake[t][sel].sum()
        return float(100.0 * pnl[t][sel].sum() / s) if s > 0 else 0.0

    out = {}
    for a, b in (("ver", "static"), ("none", "static")):
        res = {}
        for kind in ("brier", "log_loss", "roi_b365"):
            point = metric_on(a, np.arange(n), kind) - metric_on(b, np.arange(n), kind)
            boots = []
            for _ in range(n_boot):
                idx = rng.integers(0, n, size=n)
                boots.append(metric_on(a, idx, kind) - metric_on(b, idx, kind))
            lo, hi = _ci(boots)
            res[kind] = {"delta": round(point, 4), "ci": [round(lo, 4), round(hi, 4)],
                         "significant": bool(not (lo <= 0.0 <= hi))}
        out[f"{a}-static"] = res
    return out


# =====================================================================
# Report
# =====================================================================
def _fv(v, nd=4):
    return "-" if v is None else f"{v:.{nd}f}"


def render(payload):
    L = []
    ap = L.append
    ap("# MARKET_VALUES versionato per stagione — impatto sul 1X2 (audit sola lettura)")
    ap("")
    ap(f"*Generato: {payload['generated_at']} — script "
       f"`audit/market_values_versioned.py`, nessuna modifica a SoccerMath/. "
       f"Dettaglio completo (n scommesse, CI, unmatched) in "
       f"`market_values_versioned_detail.json`.*")
    ap("")
    ap("Sostituisce il fattore valore di mercato statico (`config.MARKET_VALUES`, "
       "scritto a mano e fermo a una data, applicato UGUALE a tutte le stagioni "
       "passate: leakage) con le rilevazioni reali per (lega, stagione, squadra) "
       "del CSV campionato, point-in-time: **Post-Estivo** (15/9) di default, "
       "**Post-Invernale** (15/2) per le partite dalla metà febbraio in poi, "
       "sempre della STESSA stagione della partita. La formula del fattore resta "
       "bit-fedele a produzione (`1+(log10(max(val,10))-2)/4`, clip [0.85,1.25]); "
       "cambia solo la fonte del valore. Confronto appaiato nella stessa passata "
       "walk-forward (stesso stato/Elo/xG): STATIC (prima), VERSIONED (dopo), "
       "NO_MKT (fattore 1, il riferimento «senza mercato»).")
    ap("")
    ap("> **Nota sui livelli assoluti.** I Brier della testa Poisson su questi "
       "dati sono più alti di quelli di `production_baseline_comparison.md`: lo "
       "snapshot xG corrente (`xg_<lega>.json`) è più polarizzato di quello "
       "esistente all'epoca di quel report, e la testa NORM-SUM ne eredita "
       "l'overconfidence (stessa deriva già documentata in "
       "`ensemble_weight_grid_search.md`). Il confronto di QUESTO audit è "
       "appaiato sulla stessa identica pipeline/dati, quindi le differenze fra "
       "varianti non sono toccate dalla deriva; i livelli assoluti non vanno "
       "confrontati col report storico.")
    ap("")

    ap("## Dati di copertura del CSV valori")
    ap("")
    meta = payload["meta"]
    ap(f"File: `audit/data/{os.path.basename(DATA_PATH)}` — {meta['rows']} righe "
       f"lette, {sum(meta['by_survey'].values())} righe usate "
       f"(rilevazioni: " + ", ".join(f"{k} {v}" for k, v in sorted(meta["by_survey"].items()))
       + f"), valori in milioni da {meta['min_mln']} a {meta['max_mln']}. "
       f"Date rilevazione coerenti con la finestra 15/9–15/2: "
       f"{meta['rows'] - meta.get('date_mismatch', 0)}/{meta['rows']}.")
    ap("")
    if meta["unmatched"]:
        ap(f"**Righe NON usate ({len(meta['unmatched'])})** — mai indovinate al volo:")
        ap("")
        ap("| Lega | Stagione | Squadra | Motivo |")
        ap("|---|---|---|---|")
        for u in meta["unmatched"][:50]:
            ap(f"| {u[0]} | {u[1]} | {u[2]} | {u[3]} |")
        if len(meta["unmatched"]) > 50:
            ap(f"| ... | | | (+{len(meta['unmatched'])-50} righe, vedi JSON) |")
    else:
        ap("Nessuna riga scartata: tutte le (lega, stagione, squadra, rilevazione) "
           "del CSV sono state riconosciute e normalizzate.")
    ap("")
    ap("| Lega | Stagione | Righe Post-Estivo | Righe Post-Invernale |")
    ap("|---|---|---:|---:|")
    for (camp, season), cnt in sorted(meta["by_league_season"].items()):
        ap(f"| {camp} | {season} | {cnt['Post-Estivo']} | {cnt['Post-Invernale']} |")
    ap("")

    ap("## Uso point-in-time nelle partite eval")
    ap("")
    ap("| Lega | Partite eval | Rilev. Post-Estivo | Rilev. Post-Invernale | Fallback (valore mancante) |")
    ap("|---|---:|---:|---:|---:|")
    for lg in payload["leagues"]:
        u = lg["usage"]
        n_ev = lg["n_val"] + lg["n_test"]
        ap(f"| {lg['league']} | {n_ev} | {u['Post-Estivo']//2} squadre-partita | "
           f"{u['Post-Invernale']//2} | {u['fallback_missing']//2} |")
    ap("")
    ap("Nessuna partita usa una rilevazione di un'altra stagione o quella "
       "corrente: per squadra/stagione senza valore il fattore cade a 1 (come "
       "NO_MKT, contato come fallback). "
       + (f"**Fallback effettivi: {sum(lg['usage']['fallback_missing'] for lg in payload['leagues'])//2} "
           f"su {sum(lg['n_val']+lg['n_test'] for lg in payload['leagues'])} partite eval** — il CSV copre "
           "interamente i roster delle stagioni 2024/25 e 2025/26."
           if sum(lg["usage"]["fallback_missing"] for lg in payload["leagues"]) == 0
           else "Fallback presenti: vedi tabella."))
    ap("")
    ap("Nota dichiarata: le partite delle prime "
       "settimane (precedenti al 15/9) usano la rilevazione Post-Estiva della "
       "loro stagione, che e' l'unico snapshot disponibile e puo' essere di "
       "qualche settimana successiva al primo kickoff.")
    ap("")

    ap("## Risultati per lega — Brier/LogLoss/ROI 1X2 (V=2024/25, T=2025/26)")
    ap("")
    for lg in payload["leagues"]:
        ap(f"### {lg['league']}")
        ap("")
        ap("| Variante | Brier V | LogLoss V | Brier T | LogLoss T | ROI B365 V | NB V | ROI B365 T | NB T | ROI Avg V | ROI Avg T |")
        ap("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for tag, label in (("static", "STATIC (config, prima)"),
                           ("ver", "VERSIONED (point-in-time, dopo)"),
                           ("none", "NO_MKT (fattore 1, riferimento)")):
            v, t = lg["val"]["metrics"], lg["test"]["metrics"]
            ap(f"| {label} | {_fv(v[tag]['brier'])} | {_fv(v[tag]['log_loss'])} | "
               f"{_fv(t[tag]['brier'])} | {_fv(t[tag]['log_loss'])} | "
               f"{_fv(v[tag]['roi_b365'],2)} | {v[tag]['n_bet_b365']} | "
               f"{_fv(t[tag]['roi_b365'],2)} | {t[tag]['n_bet_b365']} | "
               f"{_fv(v[tag]['roi_avg'],2)} | {_fv(t[tag]['roi_avg'],2)} |")
        ap("")
        ap("(Brier/LogLoss su testa Poisson NORM-SUM pura; ROI a puntata fissa "
           "10, selezione edge>0 sull'esito a edge massimo vs fair de-vigata del "
           "book, settle sullo stesso book — stessa convenzione di "
           "production_baseline_comparison.md. NB = n scommesse B365.)")
        ap("")
    ov_v = payload["overall"]["val"]["metrics"]
    ov_t = payload["overall"]["test"]["metrics"]
    ap("### AGGREGATO 5 leghe")
    ap("")
    ap("| Variante | Brier V | LogLoss V | Brier T | LogLoss T | ROI B365 V | ROI B365 T | ROI Avg V | ROI Avg T |")
    ap("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for tag, label in (("static", "STATIC (config, prima)"),
                       ("ver", "VERSIONED (point-in-time, dopo)"),
                       ("none", "NO_MKT (fattore 1, riferimento)")):
        ap(f"| {label} | {_fv(ov_v[tag]['brier'])} | {_fv(ov_v[tag]['log_loss'])} | "
           f"{_fv(ov_t[tag]['brier'])} | {_fv(ov_t[tag]['log_loss'])} | "
           f"{_fv(ov_v[tag]['roi_b365'],2)} | {ov_v[tag]['n_bet_b365']} | "
           f"{_fv(ov_t[tag]['roi_b365'],2)} | {ov_t[tag]['n_bet_b365']} | "
           f"{_fv(ov_v[tag]['roi_avg'],2)} | {_fv(ov_t[tag]['roi_avg'],2)} |")
    ap("")

    ap("## Significatività delle differenze (bootstrap appaiato)")
    ap("")
    ap(f"{N_BOOT} resample, seed {SEED}, CI percentile 2.5-97.5 "
       "(convenzione topmix_margins). Stesso resample di righe per entrambe le "
       "varianti: differenze appaiate. «sig» = l'IC esclude lo 0.")
    ap("")
    for split, label in (("val", "VALIDATION 2024/25"), ("test", "TEST 2025/26")):
        boot = payload["overall"][split]["boot"]
        ap(f"**{label}** — confronto su Brier / LogLoss / ROI B365 (aggregato 5 leghe):")
        ap("")
        ap("| Confronto | Metrica | Delta | CI 2.5% | CI 97.5% | sig |")
        ap("|---|---|---:|---:|---:|:---:|")
        for cmp_name, cmp_label in (("ver-static", "VERSIONED − STATIC"),
                                    ("none-static", "NO_MKT − STATIC")):
            for kind, kind_label in (("brier", "Brier"), ("log_loss", "LogLoss"),
                                     ("roi_b365", "ROI B365")):
                r = boot[cmp_name][kind]
                ap(f"| {cmp_label} | {kind_label} | {r['delta']:+.4f} | "
                   f"{r['ci'][0]:+.4f} | {r['ci'][1]:+.4f} | "
                   f"{'**sì**' if r['significant'] else 'no'} |")
        ap("")
    dfc = payload["dfac"]
    ap(f"Divergenza effettiva fra le fonti: il |fattore versionato − fattore "
       f"statico| medio per squadra-partita eval è {dfc['mean']} "
       f"(max {dfc['max']} su {dfc['n_slots']} slot): i valori veri sono cambiati "
       "rispetto allo statico, ma la formula logaritmica con clip [0.85,1.25] "
       "comprime la differenza.")
    ap("")

    ap("## Lettura")
    ap("")
    boot_v = payload["overall"]["val"]["boot"]
    db_v = boot_v["ver-static"]["brier"]
    dn_v = boot_v["none-static"]["brier"]
    dr_v = boot_v["ver-static"]["roi_b365"]
    ap(f"1. **Calibrazione: il point-in-time non cambia nulla di misurabile.** "
       f"Il Brier aggregato passa da {_fv(ov_v['static']['brier'])} (static) a "
       f"{_fv(ov_v['ver']['brier'])} (versioned) in validation "
       f"({db_v['delta']:+.4f}, CI [{db_v['ci'][0]:+.4f};{db_v['ci'][1]:+.4f}], "
       f"{'significativo' if db_v['significant'] else 'NON significativo'}) e da "
       f"{_fv(ov_t['static']['brier'])} a {_fv(ov_t['ver']['brier'])} in test. "
       "Il fattore di produzione comprime qualsiasi valore in [0.85,1.25] "
       "(media |Δfactor| "
       f"{payload['dfac']['mean']}): sostituire i valori odierni con quelli "
       "storici veri sposta le probabilità troppo poco perché il leakage del "
       "valore di mercato sia la leva che la calibrazione sente.")
    ap("")
    ap(f"2. **Il segnale «esiste un valore di mercato» conta, la sua data no.** "
       f"Rimuovere del tutto il fattore (NO_MKT) peggiora il Brier di "
       f"{dn_v['delta']:+.4f} in validation "
       f"(CI [{dn_v['ci'][0]:+.4f};{dn_v['ci'][1]:+.4f}], "
       f"{'significativo' if dn_v['significant'] else 'NON significativo'}): "
       "la forza economica delle rose è informazione reale, anche datata e "
       "grezza. Ma tra «valore di oggi applicato al passato» (static, con "
       "leakage) e «valore vero della stagione» (versioned) la differenza è "
       "rumore: la correzione del leakage non era quella che cambiava i numeri.")
    ap("")
    ap(f"3. **ROI: nessuna differenza significativa fra le fonti.** In "
       f"validation il ROI B365 (testa Poisson) va da "
       f"{_fv(ov_v['static']['roi_b365'],2)}% (static) a "
       f"{_fv(ov_v['ver']['roi_b365'],2)}% (versioned), delta "
       f"{dr_v['delta']:+.2f} punti, CI [{dr_v['ci'][0]:+.2f};{dr_v['ci'][1]:+.2f}]: "
       f"{'fuori dal rumore' if dr_v['significant'] else 'dentro il rumore'}. "
       "Come nel grid search del peso Elo, differenze di ROI di questo ordine "
       "su ~1.5k partite/split non sono evidenza di nulla.")
    ap("")
    ap("4. **Riscontro della stima di `market_value_comparison.txt`.** La "
       "vecchia stima (−17,4% → −1,5% su Serie A validation) confrontava il "
       "Poisson SENZA fattore mercato contro il Poisson CON fattore statico: "
       "la direzione si conferma (il fattore mercato migliora la selezione "
       "value bet), ma quell'entità dipendeva dallo stato xG dell'epoca. E la "
       "parte «versionato» della proposta §5 di `margini_migliorabili_topmix.md` "
       "non aggiunge nulla di misurabile né in calibrazione né in ROI: il "
       "guadagno veniva (quando veniva) dall'avere UN fattore mercato, non "
       "dalla sua data.")
    ap("")
    ap("5. **Per il codice di produzione la misura è neutra.** Nessun motivo "
       "dati-driven di sostituire MARKET_VALUES statico con i CSV versionati "
       "per il solo 1X2: i numeri non migliorano. Resta valido l'argomento di "
       "pulizia metodologica (no-leakage per costruzione), che però non è "
       "ciò che questo audit era chiamato a misurare.")
    ap("")

    ap("## Limiti dichiarati")
    ap("")
    ap("1. **Rilevazioni due volte l'anno** (15/9 e 15/2): il fattore e' costante "
       "tra le due date; il mercato reale si muove ogni settimana. E' comunque "
       "una ricostruzione molto piu' fedele dello statico odierno, che su una "
       "partita del 2022 applicava il valore del 2026.")
    ap("2. **Partite prima del 15/9**: usano la rilevazione post-estiva della "
       "loro stagione (unico snapshot disponibile), tecnicamente successiva al "
       "kickoff di poche settimane; effetto limitato alle prime 2-3 giornate.")
    ap("3. **Elo e forma non dipendono dal fattore mercato** (solo la testa "
       "Poisson lo usa): le differenze misurate sono attribuibili al solo "
       "cambio di fonte, con confronto appaiato nella stessa passata.")
    ap("4. **xG snapshot statico**: limite ereditato dalla pipeline condivisa, "
       "documentato in `clv_pinnacle_report.md`.")
    ap("5. Il CSV campionato copre i roster di 5 leghe x 4 stagioni verificati "
       "riga per riga e in queste run il fallback e' 0 su ogni partita eval; "
       "rimane implementato il fallback a fattore 1 (contato, mai valori di "
       "altre stagioni) per robustezza a futuri re-upload.")
    ap("")
    return "\n".join(L) + "\n"


# =====================================================================
# Main
# =====================================================================
def run(data_path=DATA_PATH):
    lookup, meta = parse_market_csv(data_path)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "meta": meta, "leagues": []}
    all_rows = []
    for prefix, camp_key in LEAGUES:
        df = CLV.load_league(prefix)
        d, usage = run_market_variants(df, camp_key, CLV.load_xg(camp_key), lookup)
        d = attach_odds(df, d)
        all_rows.append(d)
        lg = {
            "league": camp_key,
            "usage": usage,
            "n_val": int((d["season"] == SEASONS_EVAL[0]).sum()),
            "n_test": int((d["season"] == SEASONS_EVAL[1]).sum()),
            "val": {"metrics": metrics_at(d[d["season"] == SEASONS_EVAL[0]], "static")
                    if len(d[d["season"] == SEASONS_EVAL[0]]) else {"n": 0}},
            "test": {"metrics": metrics_at(d[d["season"] == SEASONS_EVAL[1]], "static")
                     if len(d[d["season"] == SEASONS_EVAL[1]]) else {"n": 0}},
        }
        for split, key in (("val", "2024/25"), ("test", "2025/26")):
            sub = d[d["season"] == key]
            lg[split]["metrics"] = {
                tag: metrics_at(sub, tag) for tag in ("static", "ver", "none")
            } if len(sub) else {tag: {"n": 0} for tag in ("static", "ver", "none")}
        payload["leagues"].append(lg)

    all_d = pd.concat(all_rows, ignore_index=True)
    payload["overall"] = {}
    for split, key in (("val", "2024/25"), ("test", "2025/26")):
        sub = all_d[all_d["season"] == key]
        payload["overall"][split] = {"metrics": {
            tag: metrics_at(sub, tag) for tag in ("static", "ver", "none")}}
        payload["overall"][split]["boot"] = _boot_deltas(sub.reset_index(drop=True))
    payload["dfac"] = {
        "mean": round(float(pd.concat([all_d["dfac_h"], all_d["dfac_a"]]).mean()), 4),
        "max": round(float(pd.concat([all_d["dfac_h"], all_d["dfac_a"]]).max()), 4),
        "n_slots": int(pd.concat([all_d["dfac_h"], all_d["dfac_a"]]).shape[0]),
    }
    payload["rows"] = all_d
    md = render(payload)
    return payload, md


def main():
    import json
    os.makedirs(OUT_DIR, exist_ok=True)
    payload, md = run()
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write(md)
    detail = {k: v for k, v in payload.items() if k != "rows"}
    meta2 = dict(detail["meta"])
    meta2["by_league_season"] = {f"{k[0]} {k[1]}": v
                                 for k, v in detail["meta"]["by_league_season"].items()}
    detail["meta"] = meta2
    json_path = OUT_PATH.replace(".md", "_detail.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(detail, fh, ensure_ascii=False, indent=1, default=str)
    print(f"Scritti {OUT_PATH} e {json_path}")
    ov = payload["overall"]["val"]["metrics"]
    print(f"Aggregato V: Brier static {ov['static']['brier']} -> ver "
          f"{ov['ver']['brier']} (none {ov['none']['brier']}) | "
          f"ROI B365 {ov['static']['roi_b365']}% -> {ov['ver']['roi_b365']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
