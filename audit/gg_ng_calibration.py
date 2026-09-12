"""
gg_ng_calibration.py — Audit di SOLA LETTURA: calibrazione (e, dove il campione
lo consente, ROI/edge) del mercato GG/NG usando le quote reali multi-bookmaker
caricate in ``audit/data/*_btts.json`` (20 file = 5 leghe x 4 stagioni
2022/23..2025/26, formato oddsportal: home_team/away_team/match_date/
home_score/away_score/btts_market[]).

NON tocca SoccerMath/: app.py, config.py, team_aliases.py, models/, database/
sono letti o importati in sola lettura (stessa disciplina degli altri audit:
backtest_experiment_all.py, diagnose_production_baseline.py, pt19_cap_vs_fseason_clean.py).

Pipeline (punti 1-4 del protocollo):

1. JOIN DETERMINISTICO JSON <-> CSV
   - home_team/away_team normalizzati con ``team_aliases.clean_name()`` (import
     da SoccerMath/team_aliases.py) + tabella locale di esonimi italiani
     (Oddsportal scrive "Marsiglia", "RB Lipsia", ...: alias che non competono a
     team_aliases.py, che mappa varianti API/CSV; la tabella resta QUI, nel
     audit, perche' SoccerMath/ non viene modificato).
   - chiave primaria: (squadra_casa_norm, squadra_trasferta_norm, stagione) sul
     CSV football-data corrispondente (in un girone all'italiana l'accoppiata
     orientata e' unica: verificato su tutti i 20 CSV, e comunque gestita).
   - match_date: conferma/disambiguazione SECONDARIA (toleranza +/-1 giorno per
     fuso), mai chiave primaria (59% dei record JSON ha match_date nullo).
   - qualunque coppia duplicata dentro la stessa stagione (lato JSON, es.
     Spezia-Verona 2022/23 presente anche in Coppa Italia; o lato CSV se mai
     accadesse) e' segnalata nel report come "NON RISOLTA AUTOMATICAMENTE":
     si assegna un esemplare solo se la data lo conferma, mai a caso.
   - partite senza home_score/away_score valorizzato: escluse e contate per file.

2. QUOTA BTTS
   - bet365 (match case-insensitive su "bet365") se presente in btts_market,
   - altrimenti il primo bookmaker USABILE nell'ordine dell'array (fallback;
     gli esiti bloccati in ``blocked_outcomes`` e le quote non valide sono
     saltati). Bookmaker usato: riga per riga nel sidecar JSON, aggregato per
     file nel report, con conteggio dei fallback.

3. PROBABILITA'
   - implicita de-vigata: normalizzazione proporzionale standard 1/quota diviso
     overround, identica a ``backtest_experiment_all.devig_2way`` (metodo gia'
     usato nel progetto per i mercati a 2 esiti; ``diagnose_clv_pinnacle`` non
     esiste nel repo, quindi vale il precedente elencato).
   - modello di produzione: replica walk-forward no-leakage di
     ``app.get_league_engine`` + ``app.get_full_poisson_two_heads`` (funzioni di
     produzione IMPORTATE, non riscritte): att0_pure/def0_pure (testa Totali =
     GG/NG) da F_season, cioe' ``xg_archive.season_point_in_time_averages``
     con cutoff = data della partita e stagione = stagione corrente, shrinkage
     ``app._shrunk_ratio`` (PRIOR_MATCHES=6) verso l'ancora = media di lega
     derivata dal dizionario F_season stesso (``app._league_mean_gate``), rami
     di fallback identici alla produzione; att/def/att0/def0 (testa 1X2, con
     forma ultime 5 e fattore mercato) ricostruiti come in
     ``diagnose_production_baseline.run_models``. MAI statistiche che includano
     la partita corrente o successive: lo stato viene aggiornato DOPO la
     previsione, F_season usa il cutoff point-in-time, le medie gol di lega
     (avg_h/avg_a) sono cumulative sulle sole partite precedenti (produzione
     userebbe la media sull'intero DB: deviazione forzata dal vincolo
     walk-forward, dichiarata nel report).

4. REPORT ``audit/results/gg_ng_calibration.md`` (+ sidecar ``.json`` con il
   dettaglio riga per riga)
   - per ogni lega e aggregato: Brier/LogLoss/hit-rate del modello vs
     probabilita' implicita di mercato, media probabilita' vs tasso reale,
     tabelle di calibrazione (stessi bins di ``ou_gg_calibration.py``);
   - tasso di copertura per stagione: incrociate vs scartate (join fallito,
     risultato mancante, data in conflitto, duplicati non risolti, quota
     mancante); accordo punteggi JSON vs CSV come sanitita' del join;
   - ROI/edge a puntata fissa (stake 10) quando la probabilita' del modello
     supera quella di mercato di una soglia: soglia 0 (convenzione
     ``backtest_experiment_all.EDGE_MIN = 0`` e roi_* in
     ``diagnose_production_baseline.py``), con sensibilita' 2% e 5%.

Uso:    python audit/gg_ng_calibration.py
Output: audit/results/gg_ng_calibration.md, audit/results/gg_ng_calibration.json
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import Counter, OrderedDict, deque
from datetime import datetime, timezone

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from backtest_experiment_all import load_league, MARKET_VALUES  # noqa: E402  (sola lettura)
from draw_correction import brier_binary, log_loss_binary       # noqa: E402
import app as prod_app                                          # noqa: E402  (sola lettura)
from xg_archive import load_archive, season_point_in_time_averages  # noqa: E402
from team_aliases import clean_name                             # noqa: E402

DATA_DIR = os.path.join(_AUDIT_DIR, "data")
OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_MD = os.path.join(OUT_DIR, "gg_ng_calibration.md")
OUT_JSON = os.path.join(OUT_DIR, "gg_ng_calibration.json")

# (slug nel nome file JSON) -> (prefisso CSV, chiave lega xg_archive/app, nome lega)
BTTS_FILES = OrderedDict([
    ("italy-serie-a", ("SerieA", "Serie A", "Serie A")),
    ("england-premier-league", ("Premier", "Premier League", "Premier League")),
    ("spain-laliga", ("LaLiga", "La Liga", "La Liga")),
    ("germany-bundesliga", ("Bundesliga", "Bundesliga", "Bundesliga")),
    ("france-ligue-1", ("Ligue1", "Ligue 1", "Ligue 1")),
])
SEASON_LABELS = ("2022-2023", "2023-2024", "2024-2025", "2025-2026")

# ------------------------------------------------------------------
# Esonimi Oddsportal (italiano) -> nomi canonici dei CSV football-data.
# Applicati DOPO clean_name. Audit-local: team_aliases.py mappa le varianti
# API/CSV, non i titoli italiani del sito quote; SoccerMath/ non si tocca.
# ------------------------------------------------------------------
EXONYM_TO_CANONICAL = {
    # Premier League
    "Manchester Utd": "Man United",
    "Sheffield Utd": "Sheffield United",
    # La Liga
    "Ath. Bilbao": "Ath Bilbao",
    "Atl. Madrid": "Ath Madrid",
    "Barcellona": "Barcelona",
    "Cadice": "Cadiz",
    "Celta Vigo": "Celta",
    "Maiorca": "Mallorca",
    "Siviglia": "Sevilla",
    # Bundesliga
    "Amburgo": "Hamburg",
    "Augusta": "Augsburg",
    "Brema": "Werder Bremen",
    "Colonia": "Koln",          # clean_name("FC Koln") = "Koln"
    "Francoforte": "Ein Frankfurt",
    "Friburgo": "Freiburg",
    "Kiel": "Holstein Kiel",
    "Magonza": "Mainz",
    "Monchengladbach": "M'gladbach",
    "RB Lipsia": "Leipzig",     # clean_name("RB Leipzig") = "Leipzig"
    "St. Pauli": "St Pauli",
    "Stoccarda": "Stuttgart",
    "Union Berlino": "Union Berlin",
    # Ligue 1
    "Lilla": "Lille",
    "Lione": "Lyon",
    "Marsiglia": "Marseille",
    "Nizza": "Nice",
    "St. Etienne": "St Etienne",
    "Strasburgo": "Strasbourg",
    "Tolosa": "Toulouse",
}

PRIMARY_BOOKMAKER_KEY = "bet365"   # match case-insensitive su bookmaker_name
STAKE = 10.0                       # puntata fissa, come backtest_experiment_all.STAKE
EDGE_THRESHOLDS = (0.0, 0.02, 0.05)
EDGE_PRIMARY = 0.0                 # convenzione EDGE_MIN=0 dei backtest del repo
DATE_TOLERANCE_DAYS = 1            # fuso: un match serale puo' differire di 1 giorno
CALIB_BINS = [0, 0.40, 0.45, 0.50, 0.55, 0.60, 1.01]  # stessi bins di ou_gg_calibration.py
MIN_N_ROI = 30                     # sotto questo campione il ROI e' dichiarato non affidabile


# =====================================================================
# Utilita' di parsing
# =====================================================================
def parse_int(value):
    """Intero da '5', 5, None -> None se assente/illegibile (mai 0 di default)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_float(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def parse_utc_date(value):
    """'2023-03-05 11:30:00 UTC' -> datetime UTC; None se assente/illegibile."""
    if not value or not isinstance(value, str):
        return None
    txt = value.strip().replace(" UTC", "").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(txt, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def season_start_year(season_label):
    """'2022-2023' (JSON) o '2022/23' (CSV) -> 2022."""
    txt = str(season_label).replace("/", "-")
    head = txt.split("-")[0]
    return int(head) if head.isdigit() and len(head) == 4 else None


def season_label_of(season):
    """'2022-2023' (file JSON) -> '2022/23' (etichetta stagione di load_league)."""
    start = season_start_year(season)
    if start is None:
        raise ValueError(f"stagione illeggibile: {season!r}")
    return f"{start}/{(start + 1) % 100:02d}"


def normalize_name(raw):
    """Nome grezzo -> chiave canonica dei CSV: clean_name + esonimi audit."""
    base = clean_name(raw)
    return EXONYM_TO_CANONICAL.get(base, base)


# =====================================================================
# Punto 2: scelta quota BTTS + de-vig
# =====================================================================
def pick_btts_entry(btts_market):
    """Selezione quota: bet365 se presente (e usabile), altrimenti il primo
    bookmaker usabile nell'ordine dell'array.

    Usabile = entrambe le quote presenti, finite e > 1.0 (stessa regola di
    ``backtest_experiment_all.devig_2way``) e nessuno dei due esiti in
    ``blocked_outcomes``. Ritorna ``(info | None)`` con
    ``{'index', 'bookmaker', 'o_yes', 'o_no', 'fallback'}``.
    """
    usable = []
    for i, entry in enumerate(btts_market or []):
        if not isinstance(entry, dict):
            continue
        blocked = entry.get("blocked_outcomes") or []
        if "btts_yes" in blocked or "btts_no" in blocked:
            continue
        o_yes = parse_float(entry.get("btts_yes"))
        o_no = parse_float(entry.get("btts_no"))
        if o_yes is None or o_no is None:
            continue
        if o_yes <= 1.0 or o_no <= 1.0:   # quota non valida/negativa: scartata
            continue
        usable.append({
            "index": i,
            "bookmaker": str(entry.get("bookmaker_name") or "?"),
            "o_yes": o_yes,
            "o_no": o_no,
        })
    for info in usable:                    # priorita' bet365
        if PRIMARY_BOOKMAKER_KEY in info["bookmaker"].lower():
            info["fallback"] = False
            return info
    if usable:                             # fallback: primo usabile nell'ordine
        info = dict(usable[0])
        info["fallback"] = True
        return info
    return None


def devig_two_way(o_yes, o_no):
    """De-vig proporzionale standard (1/quota diviso overround), identica a
    ``backtest_experiment_all.devig_2way``. Ritorna ``(p_yes, p_no)`` o None."""
    if o_yes is None or o_no is None:
        return None
    if not (math.isfinite(o_yes) and math.isfinite(o_no)):
        return None
    if o_yes <= 1.0 or o_no <= 1.0:
        return None
    iy, in_ = 1.0 / o_yes, 1.0 / o_no
    tot = iy + in_
    p_yes = iy / tot
    return p_yes, 1.0 - p_yes


# =====================================================================
# Punto 1: join deterministico JSON <-> CSV
# =====================================================================
# Stati del join (vanno nel report e nel sidecar):
#   ok                       -> incrociata, con quota
#   no_score                 -> home_score/away_score mancanti nel JSON
#   pair_absent              -> coppia normalizzata assente dal CSV della stagione
#   csv_duplicate            -> coppia duplicata nel CSV: NON risolta
#   date_mismatch            -> data JSON presente e incompatibile con la data CSV
#   duplicate_not_resolved   -> coppia duplicata nel JSON non disambiguabile: NON risolta
#   odds_missing             -> incrociata ma nessun bookmaker usabile
JOIN_OK = "ok"


def build_join_index(season_df):
    """Indice (casa_norm, trasferta_norm) -> [posizioni nel df stagione].

    In un girone all'italiana la lista ha sempre un elemento; se ne avesse piu'
    la coppia e' dichiarata ambigua (``csv_duplicate``), mai assegnata a caso.
    """
    index = OrderedDict()
    for pos, row in enumerate(season_df.itertuples(index=False)):
        key = (row.HomeClean, row.AwayClean)
        index.setdefault(key, []).append(pos)
    return index


def join_btts_file(json_rows, season_df, date_tol_days=DATE_TOLERANCE_DAYS):
    """Join deterministico di un file JSON sulla stagione CSV corrispondente.

    ``season_df`` e' il pezzo di ``load_league(prefix)`` di quella stagione
    (gia' con nomi puliti e deduplica per data+coppie). Ritorna una lista di
    record, uno per riga JSON, nell'ordine di arrivo (determinismo: stesso
    input -> stesso output), con stato del join, quota scelta e dati CSV.
    """
    csv_index = build_join_index(season_df)
    csv_dates = list(season_df["Date"])
    csv_fthg = list(season_df["FTHG"])
    csv_ftag = list(season_df["FTAG"])

    # --- passata 1: normalizzazione + lookup coppia -------------------------
    records = []
    groups = OrderedDict()          # (home_key, away_key) -> [record]
    for json_pos, m in enumerate(json_rows or []):
        rec = {
            "json_index": json_pos,
            "home_raw": m.get("home_team"),
            "away_raw": m.get("away_team"),
            "home_key": normalize_name(m.get("home_team") or ""),
            "away_key": normalize_name(m.get("away_team") or ""),
            "match_date_raw": m.get("match_date"),
            "match_date": parse_utc_date(m.get("match_date")),
            "home_score": parse_int(m.get("home_score")),
            "away_score": parse_int(m.get("away_score")),
            "status": None,
            "csv_pos": None,
        }
        if rec["home_score"] is None or rec["away_score"] is None:
            rec["status"] = "no_score"
            records.append(rec)
            continue
        candidates = csv_index.get((rec["home_key"], rec["away_key"]), [])
        if not candidates:
            rec["status"] = "pair_absent"
            records.append(rec)
            continue
        if len(candidates) > 1:
            rec["status"] = "csv_duplicate"
            rec["csv_pos_candidates"] = list(candidates)
            records.append(rec)
            continue
        rec["csv_pos"] = candidates[0]
        records.append(rec)
        groups.setdefault((rec["home_key"], rec["away_key"]), []).append(rec)

    # --- passata 2: coppie duplicate nel JSON -> disambiguazione per data ---
    for key, grp in groups.items():
        if len(grp) <= 1:
            continue
        csv_pos = grp[0]["csv_pos"]
        csv_date = csv_dates[csv_pos]
        confirmed = []
        for rec in grp:
            if rec["match_date"] is not None and pd.notna(csv_date):
                delta = abs((rec["match_date"].date() - csv_date.date()).days)
                if delta <= date_tol_days:
                    confirmed.append(rec)
        if len(confirmed) == 1:
            keep = confirmed[0]
            for rec in grp:
                if rec is keep:
                    rec["status"] = None          # riprendo dalla passata 3
                    rec["dup_group"] = True
                else:
                    rec["status"] = "duplicate_not_resolved"
                    rec["dup_reason"] = "duplicato nella stessa stagione: tenuto solo l'esemplare con data coerente col CSV"
        else:
            for rec in grp:
                rec["status"] = "duplicate_not_resolved"
                rec["dup_reason"] = ("duplicato nella stessa stagione e nessun esemplare unico con data coerente col CSV"
                                     if not confirmed else
                                     "duplicato nella stessa stagione: piu' esemplari con data coerente col CSV")

    # --- passata 3: conferma data (secondaria) + quota -----------------------
    for rec in records:
        if rec["status"] is not None:
            continue
        csv_pos = rec["csv_pos"]
        csv_date = csv_dates[csv_pos]
        if rec["match_date"] is not None and pd.notna(csv_date):
            delta = abs((rec["match_date"].date() - csv_date.date()).days)
            if delta > date_tol_days:
                rec["status"] = "date_mismatch"
                rec["csv_date"] = csv_date
                continue
        rec["status"] = JOIN_OK
        rec["csv_date"] = csv_date
        rec["fthg"] = int(csv_fthg[csv_pos])
        rec["ftag"] = int(csv_ftag[csv_pos])
        rec["scores_agree"] = (rec["fthg"] == rec["home_score"]
                               and rec["ftag"] == rec["away_score"])
        info = pick_btts_entry((json_rows[rec["json_index"]] or {}).get("btts_market"))
        if info is None:
            rec["status"] = "odds_missing"
            continue
        fair = devig_two_way(info["o_yes"], info["o_no"])
        if fair is None or not (0.0 < fair[0] < 1.0):    # non dovrebbe accadere
            rec["status"] = "odds_missing"
            continue
        rec["bookmaker"] = info["bookmaker"]
        rec["bookmaker_fallback"] = info["fallback"]
        rec["bookmaker_index"] = info["index"]
        rec["o_yes"] = info["o_yes"]
        rec["o_no"] = info["o_no"]
        rec["p_fair_gg"] = fair[0]
        rec["overround"] = 1.0 / info["o_yes"] + 1.0 / info["o_no"]
    return records


# =====================================================================
# Punto 3: probabilita' del modello di produzione (walk-forward no-leakage)
# =====================================================================
class _TeamState:
    """Aggregati per-squadra solo-gol aggiornabili in passata (no-leakage),
    stessa struttura di diagnose_production_baseline.TeamState."""
    __slots__ = ("hgf", "hga", "hgn", "agf", "aga", "agn", "last5")

    def __init__(self):
        self.hgf = 0.0; self.hga = 0.0; self.hgn = 0
        self.agf = 0.0; self.aga = 0.0; self.agn = 0
        self.last5 = deque(maxlen=5)

    def observe_home(self, fthg, ftag):
        self.hgf += fthg; self.hga += ftag; self.hgn += 1
        self.last5.append((fthg, ftag))

    def observe_away(self, fthg, ftag):
        self.agf += ftag; self.aga += fthg; self.agn += 1
        self.last5.append((ftag, fthg))


def _market_factor(val):
    """Fattore valore di mercato: formula ESATTA di app.get_league_engine."""
    mkt = 1.0 + (math.log10(max(val, 10)) - 2.0) / 4.0
    return max(0.85, min(1.25, mkt))


def walk_forward_gg_predictions(df, league_key, targets, fs_records):
    """Passata cronologica sul df di lega; per le righe in ``targets`` (set di
    posizioni) registra la P(GG) del modello di produzione CALCOLATA SOLO con
    statistiche precedenti la partita.

    Replica fedele dei rami di ``app.get_league_engine`` che alimentano la testa
    Totali di ``app.get_full_poisson_two_heads``:
      att0_pure/def0_pure <- F_season (season_point_in_time_averages con
      cutoff = data partita, stagione = stagione corrente) con shrinkage
      _shrunk_ratio verso l'ancora = media di lega del dizionario F_season
      (_league_mean_gate); squadra senza partite nella stagione in corso ->
      fallback gol con shrinkage (identico al ramo a campione zero).
    La testa 1X2 (att/def/att0/def0, con forma ultime 5 e fattore mercato) viene
    ricostruita come in diagnose_production_baseline.run_models con fonte gol
    (l'xG statico di produzione non e' point-in-time): NON influisce su GG,
    che dipende solo da att0_pure/def0_pure e da avg_h/avg_a.

    Ritorna ``{posizione_df: p_gg_model}`` e un contatore diagnostico.
    """
    shrunk = prod_app._shrunk_ratio
    league_gate = prod_app._league_mean_gate
    two_heads = prod_app.get_full_poisson_two_heads

    state = {}
    tot_hg = tot_ag = 0.0
    tot_n = 0
    fs_cache = {}
    fs_inactive_rows = 0
    predictions = {}

    def get_state(t):
        if t not in state:
            state[t] = _TeamState()
        return state[t]

    def fallback_ratios(ts, avg_h, avg_a):
        """Rapporti pooled gol con shrinkage: ramo fallback di produzione."""
        n = ts.hgn + ts.agn
        gf = ts.hgf + ts.agf
        ga = ts.hga + ts.aga
        exp_gf = avg_h * ts.hgn + avg_a * ts.agn
        exp_ga = avg_a * ts.hgn + avg_h * ts.agn
        return shrunk(gf, exp_gf, n), shrunk(ga, exp_ga, n)

    def form_factor(ts, avg_h, avg_a):
        """Forma ultime 5: formula ESATTA di app.get_league_engine."""
        if len(ts.last5) < 3:
            return 1.0, 1.0
        n = len(ts.last5)
        gf = sum(x[0] for x in ts.last5)
        ga = sum(x[1] for x in ts.last5)
        avg_glob = (avg_h + avg_a) / 2.0
        den = max(avg_glob, 0.5)
        return (max(0.85, min(1.15, (gf / n) / den)),
                max(0.85, min(1.15, (ga / n) / den)))

    for pos, row in enumerate(df.itertuples(index=False)):
        h, a = row.HomeClean, row.AwayClean
        fthg, ftag = int(row.FTHG), int(row.FTAG)
        avg_h = max(tot_hg / tot_n, 0.1) if tot_n else 0.1
        avg_a = max(tot_ag / tot_n, 0.1) if tot_n else 0.1

        if pos in targets:
            season_year = int(str(row.season).split("/")[0])
            cache_key = (season_year, row.Date.date())
            if cache_key not in fs_cache:
                agg = season_point_in_time_averages(
                    league_key, cutoff=row.Date.to_pydatetime(),
                    season=season_year, records=fs_records)
                anchor_xg, anchor_xga = league_gate(agg.averages)
                fs_cache[cache_key] = (agg.averages if anchor_xg is not None else {},
                                       anchor_xg, anchor_xga, anchor_xg is not None)
            fs_lookup, anchor_xg, anchor_xga, fs_active = fs_cache[cache_key]
            if not fs_active:
                fs_inactive_rows += 1

            stats = {}
            for t in (h, a):
                ts = get_state(t)
                fb_att, fb_defe = fallback_ratios(ts, avg_h, avg_a)
                # testa 1X2 (non influisce su GG): fonte gol + forma + mercato
                form_att, form_def = form_factor(ts, avg_h, avg_a)
                mkt = _market_factor(MARKET_VALUES.get(t, 50))
                att = fb_att * form_att
                defe = fb_defe * form_def
                # testa Totali (GG/NG): F_season point-in-time, rami di produzione
                pure_att = pure_defe = None
                if fs_active:
                    fs_rec = fs_lookup.get(t)
                    if isinstance(fs_rec, dict):
                        try:
                            fs_xg = float(fs_rec.get("xG_avg"))
                            fs_xga = float(fs_rec.get("xGA_avg"))
                            fs_n = fs_rec.get("matches")
                            ok = (np.isfinite(fs_xg) and np.isfinite(fs_xga)
                                  and fs_xg >= 0 and fs_xga >= 0
                                  and isinstance(fs_n, (int, float))
                                  and not isinstance(fs_n, bool)
                                  and np.isfinite(float(fs_n)) and float(fs_n) > 0)
                        except (TypeError, ValueError):
                            ok = False
                        if ok:
                            pure_att = shrunk(fs_xg, anchor_xg, fs_n)
                            pure_defe = shrunk(fs_xga, anchor_xga, fs_n)
                    if pure_att is None:
                        # squadra senza partite nella stagione in corso: ramo a
                        # campione zero di produzione (fallback gol, shrinkage)
                        pure_att, pure_defe = fb_att, fb_defe
                else:
                    # lookup non disponibile (non atteso sui dati correnti):
                    # comportamento pre-modifica = baseline con forma
                    pure_att, pure_defe = att, defe
                if not (np.isfinite(pure_att) and pure_att > 0):
                    pure_att = 1.0
                if not (np.isfinite(pure_defe) and pure_defe > 0):
                    pure_defe = 1.0
                stats[t] = {
                    "att": att * mkt,
                    "def": defe / mkt,
                    "att0": att,          # base con forma, M=1 (ancora S testa 1X2)
                    "def0": defe,
                    "att0_pure": pure_att,  # baseline pura F_season: testa Totali
                    "def0_pure": pure_defe,
                }
            m = two_heads(stats[h], stats[a], avg_h, avg_a)
            predictions[pos] = float(m["gg"])

        # aggiornamento stato DOPO la previsione: mai leakage verso il futuro
        tot_hg += fthg; tot_ag += ftag; tot_n += 1
        get_state(h).observe_home(fthg, ftag)
        get_state(a).observe_away(fthg, ftag)

    diagnostics = {"fs_inactive_rows": fs_inactive_rows, "rows_seen": int(tot_n)}
    return predictions, diagnostics


# =====================================================================
# Metriche (convenzioni del repo: draw_correction.brier_binary / log_loss_binary)
# =====================================================================
def hit_rate(probs, outcomes):
    """Quota di previsioni corrette al cutoff 0.5 (lato con prob. > 50%)."""
    if not probs:
        return None
    hits = [1.0 if (p > 0.5) == bool(y) else 0.0 for p, y in zip(probs, outcomes)]
    return float(np.mean(hits))


def calibration_table(probs, outcomes, bins=CALIB_BINS):
    """Tabella di calibrazione fine (stessi bins di ou_gg_calibration.py)."""
    out = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        sel = [(p, y) for p, y in zip(probs, outcomes) if lo <= p < hi]
        n = len(sel)
        out.append({
            "bucket": f"{int(lo*100)}-{int(hi*100)}%",
            "n": n,
            "prob_media": round(float(np.mean([p for p, _ in sel])) * 100, 1) if n else None,
            "tasso_reale": round(float(np.mean([float(y) for _, y in sel])) * 100, 1) if n else None,
        })
    return out


def simulate_roi(rows, threshold=EDGE_PRIMARY, stake=STAKE):
    """ROI/edge a puntata fissa, convenzione del repo (EDGE_MIN=0, quota REALE
    non de-vigata): il modello scommette GG se p_model - p_fair_gg > soglia,
    NG se p_fair_gg - p_model > soglia."""
    bankroll = 0.0
    n_bet = 0
    wins = 0
    for r in rows:
        edge_gg = r["p_model"] - r["p_fair_gg"]
        if edge_gg > threshold:
            side, odd = "GG", r["o_yes"]
        elif -edge_gg > threshold:
            side, odd = "NG", r["o_no"]
        else:
            continue
        n_bet += 1
        won = (side == "GG") == bool(r["real_gg"])
        wins += int(won)
        bankroll += stake * (odd - 1.0) if won else -stake
    roi = (bankroll / (n_bet * stake) * 100.0) if n_bet else None
    wr = (wins / n_bet * 100.0) if n_bet else None
    return {"threshold": threshold, "n_bet": n_bet, "win_rate_pct": wr,
            "roi_pct": roi, "bankroll_units": round(bankroll / stake, 2)}


# =====================================================================
# Aggregazioni di report
# =====================================================================
def metrics_block(rows):
    """Brier/LogLoss/hit-rate modello vs mercato + medie vs tasso reale."""
    if not rows:
        return {"n": 0,
                "model": {"brier": None, "log_loss": None, "hit_rate_pct": None,
                          "prob_media_pct": None},
                "market": {"brier": None, "log_loss": None, "hit_rate_pct": None,
                           "prob_media_pct": None},
                "tasso_reale_pct": None}
    y = [1 if r["real_gg"] else 0 for r in rows]
    p_mod = [r["p_model"] for r in rows]
    p_mkt = [r["p_fair_gg"] for r in rows]
    return {
        "n": len(rows),
        "model": {
            "brier": round(brier_binary(np.array(y, dtype=float), np.array(p_mod)), 4),
            "log_loss": round(log_loss_binary(np.array(y, dtype=float), np.array(p_mod)), 4),
            "hit_rate_pct": round(hit_rate(p_mod, y) * 100, 1) if rows else None,
            "prob_media_pct": round(float(np.mean(p_mod)) * 100, 1) if rows else None,
        },
        "market": {
            "brier": round(brier_binary(np.array(y, dtype=float), np.array(p_mkt)), 4),
            "log_loss": round(log_loss_binary(np.array(y, dtype=float), np.array(p_mkt)), 4),
            "hit_rate_pct": round(hit_rate(p_mkt, y) * 100, 1) if rows else None,
            "prob_media_pct": round(float(np.mean(p_mkt)) * 100, 1) if rows else None,
        },
        "tasso_reale_pct": round(float(np.mean(y)) * 100, 1) if rows else None,
    }


def _fmt(v, nd=2, suffix=""):
    return "-" if v is None else f"{v:.{nd}f}{suffix}"


# =====================================================================
# Main
# =====================================================================
def load_btts_dataset():
    """Tutti i file ``audit/data/*_btts.json`` come {(slug, season): rows}."""
    dataset = OrderedDict()
    for fname in sorted(os.listdir(DATA_DIR)):
        if not fname.endswith("_btts.json"):
            continue
        stem = fname[: -len("_btts.json")]
        slug, season = stem.rsplit("_", 1)
        with open(os.path.join(DATA_DIR, fname), "r", encoding="utf-8") as fh:
            dataset[(slug, season)] = json.load(fh)
    return dataset


def run(league_order=None):
    """Esegue l'audit completo. Ritorna (payload_dict, markdown_str)."""
    dataset = load_btts_dataset()
    league_order = league_order or list(BTTS_FILES.keys())

    file_stats = []          # una voce per file JSON (lega x stagione)
    joined_rows = []         # righe incrociate con quota (per metriche/ROI)
    unresolved_pairs = []    # coppie duplicate NON risolte automaticamente
    absent_teams = Counter() # squadre in coppie mai incrociate (coppe/altre divisioni)

    for slug in league_order:
        prefix, league_key, league_name = BTTS_FILES[slug]
        df = load_league(prefix)                       # sola lettura, cache-like
        fs_records = load_archive(league_key)          # archivio xG per-partita
        for season in SEASON_LABELS:
            fname = f"{slug}_{season}_btts.json"
            json_rows = dataset.get((slug, season))
            if json_rows is None:
                continue
            season_label = season_label_of(season)
            season_mask = (df["season"] == season_label).to_numpy()
            season_pos_map = list(np.flatnonzero(season_mask))   # pos locale -> pos df lega
            season_df = df[season_mask].reset_index(drop=True)
            recs = join_btts_file(json_rows, season_df)

            # --- contatori per file ---
            counts = Counter(r["status"] for r in recs)
            dated = sum(1 for r in recs if r["match_date"] is not None)
            joined = [r for r in recs if r["status"] == JOIN_OK]
            for r in recs:
                if r["status"] in ("pair_absent",):
                    absent_teams[r["home_key"]] += 1
                    absent_teams[r["away_key"]] += 1
                if r["status"] == "duplicate_not_resolved":
                    unresolved_pairs.append({
                        "file": fname,
                        "pair": f"{r['home_key']} - {r['away_key']}",
                        "motivo": r.get("dup_reason", ""),
                        "json_index": r["json_index"],
                        "home_score": r["home_score"],
                        "away_score": r["away_score"],
                        "match_date": r["match_date_raw"],
                    })

            # --- P(GG) modello walk-forward per le righe incrociate ---
            targets = {season_pos_map[r["csv_pos"]] for r in joined}
            if len(targets) != len(joined):
                raise AssertionError(f"{fname}: piu' righe JSON mappate sulla stessa "
                                     f"partita CSV ({len(joined)} righe -> {len(targets)} partite)")
            preds, diag = walk_forward_gg_predictions(df, league_key, targets, fs_records)
            if diag["fs_inactive_rows"]:
                print(f"[WARN] {fname}: F_season inattivo su {diag['fs_inactive_rows']} righe "
                      f"(fallback produzione pre-modifica)")

            fb_counter = Counter()
            for r in joined:
                if r["bookmaker_fallback"]:
                    fb_counter[r["bookmaker"]] += 1
                pos = season_pos_map[r["csv_pos"]]
                crow = season_df.iloc[r["csv_pos"]]
                r_out = {
                    "file": fname,
                    "league": league_name,
                    "season": season_label,
                    "home_raw": r["home_raw"],
                    "away_raw": r["away_raw"],
                    "home": r["home_key"],
                    "away": r["away_key"],
                    "match_date_json": r["match_date_raw"],
                    "csv_date": str(crow["Date"].date()) if pd.notna(crow["Date"]) else None,
                    "json_home_score": r["home_score"],
                    "json_away_score": r["away_score"],
                    "fthg": r["fthg"],
                    "ftag": r["ftag"],
                    "scores_agree": r.get("scores_agree"),
                    "bookmaker": r["bookmaker"],
                    "bookmaker_fallback": r["bookmaker_fallback"],
                    "bookmaker_index": r["bookmaker_index"],
                    "o_yes": r["o_yes"],
                    "o_no": r["o_no"],
                    "overround": round(r["overround"], 4),
                    "p_fair_gg": round(r["p_fair_gg"], 6),
                    "p_model": round(preds[pos], 6),
                    "real_gg": bool(r["fthg"] > 0 and r["ftag"] > 0),
                    "p_model_in_range": 0.0 <= preds[pos] <= 1.0,
                }
                joined_rows.append(r_out)

            file_stats.append({
                "file": fname,
                "league": league_name,
                "season": season_label,
                "rows": len(recs),
                "dated": dated,
                "no_score": counts.get("no_score", 0),
                "pair_absent": counts.get("pair_absent", 0),
                "csv_duplicate": counts.get("csv_duplicate", 0),
                "date_mismatch": counts.get("date_mismatch", 0),
                "duplicate_not_resolved": counts.get("duplicate_not_resolved", 0),
                "odds_missing": counts.get("odds_missing", 0),
                "joined": len(joined),
                "join_rate_pct": round(100.0 * len(joined) / len(recs), 1) if recs else None,
                "scores_agree": sum(1 for r in joined if r.get("scores_agree")),
                "bet365": sum(1 for r in joined if not r["bookmaker_fallback"]),
                "fallback": sum(1 for r in joined if r["bookmaker_fallback"]),
                "fallback_books": dict(fb_counter),
            })

    # ===== aggregazioni =====
    leagues_payload = OrderedDict()
    for slug in league_order:
        league_name = BTTS_FILES[slug][2]
        rows = [r for r in joined_rows if r["league"] == league_name]
        if not rows:
            continue
        by_season = OrderedDict()
        for season in [season_label_of(s) for s in SEASON_LABELS]:
            srows = [r for r in rows if r["season"] == season]
            if srows:
                by_season[season] = metrics_block(srows)
        leagues_payload[league_name] = {
            "metrics": metrics_block(rows),
            "by_season": by_season,
            "roi": {str(t): simulate_roi(rows, t) for t in EDGE_THRESHOLDS},
            "calib_model": calibration_table([r["p_model"] for r in rows],
                                             [1 if r["real_gg"] else 0 for r in rows]),
            "calib_market": calibration_table([r["p_fair_gg"] for r in rows],
                                              [1 if r["real_gg"] else 0 for r in rows]),
        }

    overall = metrics_block(joined_rows)
    overall_roi = {str(t): simulate_roi(joined_rows, t) for t in EDGE_THRESHOLDS}
    overall_calib_model = calibration_table([r["p_model"] for r in joined_rows],
                                            [1 if r["real_gg"] else 0 for r in joined_rows])
    overall_calib_market = calibration_table([r["p_fair_gg"] for r in joined_rows],
                                             [1 if r["real_gg"] else 0 for r in joined_rows])

    roi_by_season = OrderedDict()
    for season in [season_label_of(s) for s in SEASON_LABELS]:
        srows = [r for r in joined_rows if r["season"] == season]
        if srows:
            roi_by_season[season] = simulate_roi(srows, EDGE_PRIMARY)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "protocol": {
            "bookmaker_policy": f"bet365 ('{PRIMARY_BOOKMAKER_KEY}', case-insensitive) se presente e usabile, altrimenti primo bookmaker usabile nell'ordine dell'array",
            "devig": "normalizzazione proporzionale 1/quota diviso overround (identica a backtest_experiment_all.devig_2way)",
            "model": "get_full_poisson_two_heads (app.py, importata) - testa Totali att0_pure/def0_pure da F_season (season_point_in_time_averages, cutoff=data partita) con shrinkage _shrunk_ratio/ancora _league_mean_gate; walk-forward no-leakage",
            "roi": f"puntata fissa {STAKE}, soglia edge>{EDGE_PRIMARY} (convenzione backtest_experiment_all.EDGE_MIN), quota reale non de-vigata",
            "date_tolerance_days": DATE_TOLERANCE_DAYS,
        },
        "totals": {
            "files": len(file_stats),
            "json_rows": sum(f["rows"] for f in file_stats),
            "joined": len(joined_rows),
            "scores_agree": sum(1 for r in joined_rows if r["scores_agree"]),
        },
        "files": file_stats,
        "unresolved_pairs": unresolved_pairs,
        "absent_teams": [{"team": t, "rows": c}
                         for t, c in sorted(absent_teams.items(),
                                            key=lambda kv: (-kv[1], kv[0]))],
        "leagues": leagues_payload,
        "overall": {
            "metrics": overall,
            "roi": overall_roi,
            "roi_by_season": roi_by_season,
            "calib_model": overall_calib_model,
            "calib_market": overall_calib_market,
        },
        "rows": joined_rows,
    }
    md = render_markdown(payload, file_stats, leagues_payload, joined_rows,
                         overall, overall_roi, overall_calib_model,
                         overall_calib_market, roi_by_season, unresolved_pairs)
    return payload, md


# =====================================================================
# Render markdown
# =====================================================================
def render_markdown(payload, file_stats, leagues_payload, joined_rows,
                    overall, overall_roi, overall_calib_model,
                    overall_calib_market, roi_by_season, unresolved_pairs):
    L = []
    ap = L.append
    ap("# Audit calibrazione GG/NG — quote reali multi-bookmaker (audit/data)")
    ap("")
    ap(f"*Generato: {payload['generated_at']} — script sola lettura "
       f"`audit/gg_ng_calibration.py`, nessuna modifica a SoccerMath/.*")
    ap("")
    tot = payload["totals"]
    ap(f"**Campione**: {tot['files']} file JSON (5 leghe x 4 stagioni 2022/23-2025/26), "
       f"{tot['json_rows']} righe quote, **{tot['joined']} partite incrociate** con quota "
       f"BTTS e risultato CSV. Accordo punteggi JSON vs CSV: "
       f"{tot['scores_agree']}/{tot['joined']} "
       f"({100.0*tot['scores_agree']/max(tot['joined'],1):.1f}%).")
    ap("")

    ap("## Metodo")
    ap("")
    ap("- **Join**: chiave primaria `(squadra_casa_normalizzata, squadra_trasferta_normalizzata, stagione)`; "
       "normalizzazione con `team_aliases.clean_name()` + tabella locale di esonimi italiani "
       "(Oddsportal scrive \"Marsiglia\", \"RB Lipsia\", \"Ath. Bilbao\", ...: alias non competono a "
       "`team_aliases.py`, che non e' stato modificato). In un girone all'italiana la coppia orientata e' "
       "unica per stagione: nessun CSV del dataset presenta duplicati (verificato), e il caso e' comunque gestito.")
    ap("- **Data**: conferma/disambiguazione secondaria con tolleranza ±1 giorno "
       "(fuso); mai chiave primaria — 4.183/7.102 record JSON (59%) hanno `match_date` nullo. "
       "Un record con data incompatibile con il CSV viene scartato (`date_mismatch`): e' tipicamente "
       "la copia di coppa con lo stesso orientamento della partita di campionato.")
    ap("- **Coppie duplicate nella stessa stagione**: mai assegnate a caso. Unico caso del dataset: "
       "Spezia-Verona 2022/23 (presente anche in Coppa Italia). Risolto solo l'esemplare con data "
       "coerente col CSV; gli altri risultano **\"non risolti automaticamente\"** e sono elencati sotto.")
    ap("- **Risultato mancante**: partite JSON senza `home_score`/`away_score` escluse e contate per file.")
    ap("- **Quota**: `bet365` se presente e usabile, altrimenti primo bookmaker usabile nell'ordine "
       "dell'array (fallback). Non usabili: esiti in `blocked_outcomes`, quote assenti/non finite/<= 1.0.")
    ap("- **De-vig**: normalizzazione proporzionale standard `1/quota / (1/q_yes + 1/q_no)` — lo stesso "
       "metodo del progetto per i mercati a 2 esiti (`backtest_experiment_all.devig_2way`; "
       "`diagnose_clv_pinnacle` non esiste nel repo).")
    ap("- **Modello**: `app.get_full_poisson_two_heads` **importata** (non riscritta). Testa Totali "
       "(GG/NG) = `att0_pure`/`def0_pure` da **F_season** (`xg_archive.season_point_in_time_averages`, "
       "medie xG della sola stagione in corso al cutoff = data della partita) con shrinkage "
       "`_shrunk_ratio` (prior 6 partite) verso l'ancora = media di lega del dizionario F_season "
       "(`_league_mean_gate`); squadra senza partite nella stagione in corso -> fallback gol con "
       "shrinkage, identico al ramo a campione zero di `get_league_engine`. La testa 1X2 (att/def con "
       "forma ultime 5 e fattore mercato) e' ricostruita con fonte gol walk-forward: **non influisce su "
       "GG** (che dipende solo da att0_pure/def0_pure e dalle medie gol di lega).")
    ap("- **Walk-forward**: nessuna partita usa statistiche che la includano o includano partite "
       "successive: lo stato (gol cumulati, forma, medie di lega) viene aggiornato **dopo** la "
       "previsione e F_season usa il cutoff point-in-time. Deviazione dichiarata: produzione usa le "
       "medie gol calcolate sull'intero DB; qui sono cumulative sulle sole partite precedenti (le prime "
       "partite di 2022/23 partono da medie non ancora informative — effetto da cold start).")
    ap("- **ROI/edge**: puntata fissa 10; il modello scommette GG se `P_model(GG) - P_fair(GG) > soglia`, "
       "NG se `P_fair(GG) - P_model(GG) > soglia`; vincita sulla quota reale non de-vigata. Soglia "
       "primaria 0 = convenzione `EDGE_MIN` di `backtest_experiment_all.py` e dei `roi_*` di "
       "`diagnose_production_baseline.py`; sensibilita' a 2% e 5%.")
    ap("")

    ap("## Copertura per file (lega x stagione)")
    ap("")
    ap("| File | Righe | Con data | Senza risultato | Pair assente | Data in conflitto | Dup. non risolti | Quota mancante | **Incrociate** | Tasso incrocio |")
    ap("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for f in file_stats:
        ap(f"| `{f['file']}` | {f['rows']} | {f['dated']} | {f['no_score']} | "
           f"{f['pair_absent']} | {f['date_mismatch']} | {f['duplicate_not_resolved']} | "
           f"{f['odds_missing']} | **{f['joined']}** | {_fmt(f['join_rate_pct'],1,'%')} |")
    ap("")
    tot_rows = sum(f["rows"] for f in file_stats)
    ap(f"Totale: {tot_rows} righe, "
       f"{sum(f['joined'] for f in file_stats)} incrociate "
       f"({100.0*sum(f['joined'] for f in file_stats)/max(tot_rows,1):.1f}%). "
       f"Le righe non incrociate sono in gran parte partite di Coppa/altre divisioni catturate dallo "
       f"scraping h2h di Oddsportal (squadre mai presenti nei CSV della lega: vedi lista sotto) o copie "
       f"di coppa con data incompatibile.")
    ap("")

    ap("## Bookmaker usato")
    ap("")
    ap("Riga per riga nel sidecar `gg_ng_calibration.json` (campo `bookmaker`). Per file:")
    ap("")
    ap("| File | bet365 (priorita') | Fallback | Bookmaker fallback usati |")
    ap("|---|---:|---:|---:|")
    fb_books = Counter()
    for r in joined_rows:
        if r["bookmaker_fallback"]:
            fb_books[r["bookmaker"]] += 1
    for f in file_stats:
        detail = ", ".join(f"{b} ({c})" for b, c in
                           sorted(f["fallback_books"].items(), key=lambda kv: (-kv[1], kv[0])))
        ap(f"| `{f['file']}` | {f['bet365']} | {f['fallback']} | {detail or '-'} |")
    ap("")
    n_fb = sum(f["fallback"] for f in file_stats)
    n_all = sum(f["bet365"] + f["fallback"] for f in file_stats)
    ap(f"**Fallback totale: {n_fb}/{n_all} righe "
       f"({100.0*n_fb/max(n_all,1):.1f}%)** — il bet365 e' presente e usabile in tutte le altre. "
       f"Bookmaker fallback incontrati: " +
       (", ".join(f"{b} ({c})" for b, c in sorted(fb_books.items(), key=lambda kv: -kv[1])) or "nessuno") + ".")
    ap("")

    ap("## Coppie duplicate nella stessa stagione — NON risolte automaticamente")
    ap("")
    if unresolved_pairs:
        ap("| File | Coppia | Esemplari scartati | Motivo |")
        ap("|---|---|---:|---|")
        for u in unresolved_pairs:
            ap(f"| `{u['file']}` | {u['pair']} | 1 | {u['motivo']} |")
    else:
        ap("Nessuna coppia duplicata non risolvibile.")
    ap("")

    ap("## Squadre in coppie mai incrociate (coppe / altre divisioni)")
    ap("")
    ap("Squadre che compaiono nei file quote ma non esistono nei CSV della lega-stagione corrispondente "
       "(tipicamente partite di Coppa catturate dallo scraping h2h):")
    ap("")
    abs_teams = payload["absent_teams"]
    if abs_teams:
        ap(", ".join(f"{e['team']} ({e['rows']})" for e in abs_teams))
    else:
        ap("Nessuna.")
    ap("")

    ap("## Calibrazione: modello vs mercato (Brier / LogLoss / hit-rate)")
    ap("")
    ap("Mercato: P_fair(GG) de-vigata della quota scelta. Hit-rate: quota di previsioni corrette al "
       "cutoff 0.5. Brier/LogLoss su esito binario GG=1.")
    ap("")
    ap("| Campione | n | Brier modello | Brier mercato | LogLoss modello | LogLoss mercato | Hit-rate modello | Hit-rate mercato | Prob. media modello | Prob. media mercato | Tasso reale GG |")
    ap("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for league_name, lp in leagues_payload.items():
        mk = lp["metrics"]
        ap(f"| **{league_name}** | {mk['n']} | {_fmt(mk['model']['brier'],4)} | {_fmt(mk['market']['brier'],4)} | "
           f"{_fmt(mk['model']['log_loss'],4)} | {_fmt(mk['market']['log_loss'],4)} | "
           f"{_fmt(mk['model']['hit_rate_pct'],1,'%')} | {_fmt(mk['market']['hit_rate_pct'],1,'%')} | "
           f"{_fmt(mk['model']['prob_media_pct'],1,'%')} | {_fmt(mk['market']['prob_media_pct'],1,'%')} | "
           f"{_fmt(mk['tasso_reale_pct'],1,'%')} |")
        for season, smk in lp["by_season"].items():
            ap(f"| — {season} | {smk['n']} | {_fmt(smk['model']['brier'],4)} | {_fmt(smk['market']['brier'],4)} | "
               f"{_fmt(smk['model']['log_loss'],4)} | {_fmt(smk['market']['log_loss'],4)} | "
               f"{_fmt(smk['model']['hit_rate_pct'],1,'%')} | {_fmt(smk['market']['hit_rate_pct'],1,'%')} | "
               f"{_fmt(smk['model']['prob_media_pct'],1,'%')} | {_fmt(smk['market']['prob_media_pct'],1,'%')} | "
               f"{_fmt(smk['tasso_reale_pct'],1,'%')} |")
    om = overall
    ap(f"| **AGGREGATO** | {om['n']} | {_fmt(om['model']['brier'],4)} | {_fmt(om['market']['brier'],4)} | "
       f"{_fmt(om['model']['log_loss'],4)} | {_fmt(om['market']['log_loss'],4)} | "
       f"{_fmt(om['model']['hit_rate_pct'],1,'%')} | {_fmt(om['market']['hit_rate_pct'],1,'%')} | "
       f"{_fmt(om['model']['prob_media_pct'],1,'%')} | {_fmt(om['market']['prob_media_pct'],1,'%')} | "
       f"{_fmt(om['tasso_reale_pct'],1,'%')} |")
    ap("")

    ap("### Tabelle di calibrazione (bins di ou_gg_calibration.py) — aggregato")
    ap("")
    ap("| Bucket P(GG) | n | P media modello | Tasso reale | P media mercato | Tasso reale mercato |")
    ap("|---|---:|---:|---:|---:|---:|")
    for cm, cmt in zip(overall_calib_model, overall_calib_market):
        ap(f"| {cm['bucket']} | {cm['n']} | {_fmt(cm['prob_media'],1,'%')} | {_fmt(cm['tasso_reale'],1,'%')} | "
           f"{_fmt(cmt['prob_media'],1,'%')} | {_fmt(cmt['tasso_reale'],1,'%')} |")
    ap("")

    ap("## ROI / edge a puntata fissa")
    ap("")
    ap(f"Il modello scommette il lato con edge positivo oltre la soglia; vincita a quota reale; stake {STAKE:.0f}. "
       f"ROI = bankroll / totale puntato. Campioni con n < {MIN_N_ROI} scommesse non sono affidabili.")
    ap("")
    ap("| Campione | Soglia edge | Scommesse | Win rate | ROI | Bankroll (unita') |")
    ap("|---|---:|---:|---:|---:|---:|")
    for league_name, lp in leagues_payload.items():
        for thr_key, roi in lp["roi"].items():
            if roi["n_bet"] == 0:
                ap(f"| **{league_name}** | {float(thr_key):.0%} | 0 | - | - | - |")
                continue
            flag = "" if roi["n_bet"] >= MIN_N_ROI else " *(campione insufficiente)*"
            ap(f"| **{league_name}** | {float(thr_key):.0%} | {roi['n_bet']}{flag} | "
               f"{_fmt(roi['win_rate_pct'],1,'%')} | {_fmt(roi['roi_pct'],2,'%')} | {roi['bankroll_units']:+.1f} |")
    for thr_key, roi in overall_roi.items():
        if roi["n_bet"] == 0:
            ap(f"| **AGGREGATO** | {float(thr_key):.0%} | 0 | - | - | - |")
            continue
        flag = "" if roi["n_bet"] >= MIN_N_ROI else " *(campione insufficiente)*"
        ap(f"| **AGGREGATO** | {float(thr_key):.0%} | {roi['n_bet']}{flag} | "
           f"{_fmt(roi['win_rate_pct'],1,'%')} | {_fmt(roi['roi_pct'],2,'%')} | {roi['bankroll_units']:+.1f} |")
    ap("")
    ap("### ROI per stagione (soglia 0, aggregato)")
    ap("")
    ap("| Stagione | Scommesse | Win rate | ROI |")
    ap("|---|---:|---:|---:|")
    for season, roi in roi_by_season.items():
        ap(f"| {season} | {roi['n_bet']} | {_fmt(roi['win_rate_pct'],1,'%')} | {_fmt(roi['roi_pct'],2,'%')} |")
    ap("")

    ap("## Limiti dichiarati")
    ap("")
    ap("1. **Coppie di coppa non datate**: una partita di Coppa con lo stesso orientamento di quella di "
       "campionato, senza `match_date` nel JSON e senza gemella datata nello stesso file, e' "
       "indistinguibile e verrebbe incrociata al campionato. La stima dell'effetto e' il tasso di "
       "`date_mismatch` tra righe datate (tabella copertura): e' un limite del dato, non del join.")
    ap("2. **Cold start 2022/23**: il walk-forward parte dal DB vuoto (il progetto non conserva storico "
       "anteriore); le medie gol di lega e i fallback gol sono poco informativi nelle prime giornate. "
       "In produzione quelle medie usano l'intero DB disponibile oggi.")
    ap("3. **xG rivisti**: l'archivio conserva gli xG Understat all'ultimo valore; una ricostruzione "
       "point-in-time usa xG potenzialmente piu' recenti di quelli visibili all'epoca (limite gia' "
       "documentato in `xg_archive.py`).")
    ap("4. **Quote pre-match non timestampate**: i file non permettono di verificare l'istante esatto di "
       "raccozione della quota; si assume apertura/pre-chiusura oddsportal come da scraping.")
    ap("5. Il ROI con soglia 0 e' la convenzione dei backtest del repo, NON una strategia consigliata: "
       "un edge calcolato sul de-vig di un solo bookmaker include il rumore di quotazione.")
    ap("")
    return "\n".join(L) + "\n"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    payload, md = run()
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write(md)
    print(f"Scritto {OUT_MD}")
    print(f"Scritto {OUT_JSON}")
    tot = payload["totals"]
    om = payload["overall"]["metrics"]
    print(f"Partite incrociate: {tot['joined']}/{tot['json_rows']} | "
          f"Brier modello {om['model']['brier']:.4f} vs mercato {om['market']['brier']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
