"""Ricostruzione diagnostica di un pronostico Top Mix usando le funzioni di produzione.

Vincoli (rispettati):
  * nessuna riscrittura parallela del motore: si importano e si CHIAMANO
    ``get_league_engine``, ``get_full_poisson_two_heads``, ``_shrunk_ratio``,
    ``_stat_num``, ``_clip_lambda``, ``_two_heads_from_lambdas``,
    ``predict_elo_probs``, ``clean_name``, ``get_understat_xg``,
    ``get_market_values``, ``select_next_matchday_matches``;
  * NON si chiamano ``save_prediction_entry``, ``save_predictions``,
    ``load_predictions``, ``fetch_and_calc_top_mix``, ``analisi_rapida_giornata``
    (niente scrittura registro, niente JSONBin, niente fetch Top Mix a 5 leghe);
  * i sette mercati restano 1, X, 2, Over/Under 2.5, GG/NG;
  * formule, soglie, pesi NON vengono modificati.

Il selettore A e' l'orchestrazione riga-per-riga del loop in
``fetch_and_calc_top_mix`` (max Poisson, poi mix Elo e filtri), invocata sulle
probabilita' di produzione. Il selettore B (diagnostico) applica gli STESSI
pesi/soglie a tutti i mercati e poi prende il massimo ammissibile: serve a
isolare l'effetto dell'ordine, non a cercare nuove soglie.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
_SOCCER = os.path.join(_REPO_ROOT, "SoccerMath")
if _SOCCER not in sys.path:
    sys.path.insert(0, _SOCCER)

os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")

# Import di produzione. Non si chiamano le funzioni di salvataggio.
from config import (  # noqa: E402
    CURRENT_SEASON,
    CURRENT_SEASON_START_YEAR,
    FOOTBALL_DATA_API_KEY,
    LEAGUE_CODE_MAP,
    MARKET_VALUES,
    clean_name,
    get_league_db_files,
)
from models.elo_engine import predict_elo_probs  # noqa: E402
from prediction_registry import MODEL_VERSION_CURRENT  # noqa: E402
from scraper_xg import get_understat_xg, get_market_values  # noqa: E402
from team_names import resolve_team_name  # noqa: E402
from xg_archive import (  # noqa: E402
    is_played,
    load_archive,
    parse_kickoff,
    parse_season,
    parse_xg,
    season_averages,
)

import app as _prod  # noqa: E402

# Funzioni di produzione usate (elencate per audit: niente parallelo).
get_league_engine = _prod.get_league_engine
get_full_poisson_two_heads = _prod.get_full_poisson_two_heads
_shrunk_ratio = _prod._shrunk_ratio
_stat_num = _prod._stat_num
_clip_lambda = _prod._clip_lambda
_two_heads_from_lambdas = _prod._two_heads_from_lambdas
select_next_matchday_matches = _prod.select_next_matchday_matches
PRIOR_MATCHES = _prod.PRIOR_MATCHES
TOP_MIX_ROUND_WINDOW_DAYS = _prod.TOP_MIX_ROUND_WINDOW_DAYS

# Guardia: queste NON devono essere invocate da questo modulo.
_FORBIDDEN_CALLS = (
    "save_prediction_entry",
    "save_predictions",
    "load_predictions",
    "fetch_and_calc_top_mix",
    "analisi_rapida_giornata",
)

# Soglie/pesi copiati da fetch_and_calc_top_mix (app.py). Non sono nuovi valori:
# un test AST verifica che coincidano col sorgente di produzione.
OU_GG_MARKETS = ("Over 2.5", "Under 2.5", "GG", "NG")
MIN_CONF_OU_GG = 0.60
MIN_CONF_1X2 = 0.55
POISSON_WEIGHT = 0.6
ELO_WEIGHT = 0.4
ELO_DISAGREE_MAX = 0.25
TOP_N = 10
TARGET_DISPLAY = 92.1

SEVEN_MARKET_KEYS = ("1", "X", "2", "Over 2.5", "Under 2.5", "GG", "NG")

# Nomi API candidati (ASSUNZIONE, non snapshot). football-data.org v4 usa di
# solito shortName "Schalke" / "Bayern". Senza snapshot API non e' verificato.
DEFAULT_API_CANDIDATES: Tuple[Tuple[str, str], ...] = (
    ("Schalke", "Bayern"),
    ("Schalke 04", "Bayern"),
    ("FC Schalke 04", "FC Bayern München"),
    ("Schalke 04", "Bayern Munich"),
    ("Schalke", "Bayern Munich"),
)


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT, text=True
        ).strip()
    except Exception:
        return ""


def git_commit_0695e9e_present() -> bool:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "0695e9e611e481d2a9f5648a3a9fcd4412f86070"],
            cwd=_REPO_ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
        return bool(out)
    except Exception:
        return False


def _json_safe(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    if isinstance(obj, float):
        if math.isfinite(obj):
            return obj
        return None
    if hasattr(obj, "item") and callable(obj.item):
        try:
            return _json_safe(obj.item())
        except Exception:
            pass
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


def evidence(status: str, value: Any, note: str = "") -> Dict[str, Any]:
    return {"status": status, "value": _json_safe(value), "note": note}


def seven_markets(h: str, a: str, m_poisson: Dict[str, float]) -> Dict[str, float]:
    """Gli stessi sette mercati di fetch_and_calc_top_mix, stesse chiavi."""
    return {
        f"Vittoria {h}": float(m_poisson["1"]),
        "Pareggio": float(m_poisson["X"]),
        f"Vittoria {a}": float(m_poisson["2"]),
        "Over 2.5": float(1.0 - m_poisson["u25"]),
        "Under 2.5": float(m_poisson["u25"]),
        "GG": float(m_poisson["gg"]),
        "NG": float(1.0 - m_poisson["gg"]),
    }


def apply_selector_A(
    mercati: Dict[str, float],
    home_api: str,
    away_api: str,
    elo_p: Optional[Dict[str, float]],
) -> Dict[str, Any]:
    """Selettore di produzione: max Poisson, poi mix Elo e filtri.

    Trascrizione del loop in ``fetch_and_calc_top_mix`` (app.py). I numeri
    0.6/0.4, 0.55, 0.60, 0.25 sono quelli del sorgente, non alternative.
    """
    best_mkt = max(mercati, key=mercati.get)
    poisson_prob = mercati[best_mkt]
    elo_prob = poisson_prob  # fallback di produzione
    elo_used = False
    if elo_p is not None:
        if best_mkt == f"Vittoria {home_api}":
            elo_prob = elo_p["1"]
            elo_used = True
        elif best_mkt == f"Vittoria {away_api}":
            elo_prob = elo_p["2"]
            elo_used = True
        elif best_mkt == "Pareggio":
            elo_prob = elo_p["X"]
            elo_used = True
    if best_mkt in OU_GG_MARKETS:
        confidence = poisson_prob
        min_conf = MIN_CONF_OU_GG
    else:
        confidence = POISSON_WEIGHT * poisson_prob + ELO_WEIGHT * elo_prob
        min_conf = MIN_CONF_1X2
    disagree = abs(poisson_prob - elo_prob)
    admitted = bool(confidence >= min_conf and disagree < ELO_DISAGREE_MAX)
    return {
        "selector": "A_max_poisson_then_mix_and_filters",
        "best_market": best_mkt,
        "poisson_prob": poisson_prob,
        "elo_prob": elo_prob,
        "elo_used_for_selected": elo_used,
        "confidence": confidence,
        "prob_val": round(confidence * 100.0, 1),
        "min_conf": min_conf,
        "disagree": disagree,
        "admitted": admitted,
        "filters": {
            "min_conf": min_conf,
            "elo_disagree_max": ELO_DISAGREE_MAX,
            "poisson_weight": POISSON_WEIGHT,
            "elo_weight": ELO_WEIGHT,
        },
    }


def apply_selector_B(
    mercati: Dict[str, float],
    home_api: str,
    away_api: str,
    elo_p: Optional[Dict[str, float]],
) -> Dict[str, Any]:
    """Alternativa diagnostica: probabilita' finali di tutti i mercati, filtri, max ammissibile.

    Stessi modelli, stessi sette mercati, stesse soglie/pesi. Cambia solo
    l'ordine: prima si applica a ogni mercato la trasformazione che A applica
    solo al massimo Poisson, poi si sceglie il massimo ammissibile.
    """
    scored: List[Dict[str, Any]] = []
    for name, poisson_prob in mercati.items():
        elo_prob = poisson_prob
        elo_used = False
        if name in OU_GG_MARKETS:
            confidence = poisson_prob
            min_conf = MIN_CONF_OU_GG
        else:
            if elo_p is not None:
                if name == f"Vittoria {home_api}":
                    elo_prob = elo_p["1"]
                    elo_used = True
                elif name == f"Vittoria {away_api}":
                    elo_prob = elo_p["2"]
                    elo_used = True
                elif name == "Pareggio":
                    elo_prob = elo_p["X"]
                    elo_used = True
            confidence = POISSON_WEIGHT * poisson_prob + ELO_WEIGHT * elo_prob
            min_conf = MIN_CONF_1X2
        disagree = abs(poisson_prob - elo_prob)
        admitted = bool(confidence >= min_conf and disagree < ELO_DISAGREE_MAX)
        scored.append({
            "market": name,
            "poisson_prob": poisson_prob,
            "elo_prob": elo_prob,
            "elo_used": elo_used,
            "confidence": confidence,
            "prob_val": round(confidence * 100.0, 1),
            "min_conf": min_conf,
            "disagree": disagree,
            "admitted": admitted,
        })
    admitted_rows = [r for r in scored if r["admitted"]]
    chosen = None
    if admitted_rows:
        chosen = max(admitted_rows, key=lambda r: r["confidence"])
    return {
        "selector": "B_final_probs_then_filters_then_max_admissible",
        "all_markets": scored,
        "best_market": None if chosen is None else chosen["market"],
        "confidence": None if chosen is None else chosen["confidence"],
        "prob_val": None if chosen is None else chosen["prob_val"],
        "admitted": chosen is not None,
        "n_admitted": len(admitted_rows),
        "filters": {
            "min_conf_ou_gg": MIN_CONF_OU_GG,
            "min_conf_1x2": MIN_CONF_1X2,
            "elo_disagree_max": ELO_DISAGREE_MAX,
            "poisson_weight": POISSON_WEIGHT,
            "elo_weight": ELO_WEIGHT,
        },
    }


def _league_xg_means(xg_data: Optional[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float], Dict[str, Any]]:
    """Stessa regola di get_league_engine per le medie di lega xG/xGA."""
    meta: Dict[str, Any] = {"used": False, "n_xg": 0, "n_xga": 0}
    if not xg_data or len(xg_data) < 10:
        return None, None, meta
    import numpy as np
    _lx = [v["xG_avg"] for v in xg_data.values()
           if isinstance(v, dict) and isinstance(v.get("xG_avg"), (int, float))
           and np.isfinite(v["xG_avg"]) and v["xG_avg"] > 0]
    _lxa = [v["xGA_avg"] for v in xg_data.values()
            if isinstance(v, dict) and isinstance(v.get("xGA_avg"), (int, float))
            and np.isfinite(v["xGA_avg"]) and v["xGA_avg"] > 0]
    meta["n_xg"] = len(_lx)
    meta["n_xga"] = len(_lxa)
    if len(_lx) >= 10 and len(_lxa) >= 10:
        _m_xg, _m_xga = float(np.mean(_lx)), float(np.mean(_lxa))
        if 0.5 < _m_xg < 5.0 and 0.5 < _m_xga < 5.0:
            meta["used"] = True
            return _m_xg, _m_xga, meta
    return None, None, meta


def _form_from_df(df, team_clean: str, avg_h: float, avg_a: float) -> Dict[str, Any]:
    """Stessa regola di get_league_engine: ultime 5 partite del df concatenato."""
    df_sorted = df.sort_values("Date", kind="stable")
    t_matches = df_sorted[(df_sorted["HomeClean"] == team_clean) | (df_sorted["AwayClean"] == team_clean)].tail(5)
    rows = []
    gf = 0.0
    gt = 0.0
    for _, r in t_matches.iterrows():
        if r["HomeClean"] == team_clean:
            g_for, g_ag = r["FTHG"], r["FTAG"]
            venue = "H"
            opp = r["AwayClean"]
        else:
            g_for, g_ag = r["FTAG"], r["FTHG"]
            venue = "A"
            opp = r["HomeClean"]
        gf += float(g_for)
        gt += float(g_ag)
        date_val = r["Date"]
        rows.append({
            "date": date_val.strftime("%Y-%m-%d") if hasattr(date_val, "strftime") else str(date_val),
            "venue": venue,
            "opponent": opp,
            "gf": int(g_for) if g_for == g_for else None,
            "ga": int(g_ag) if g_ag == g_ag else None,
        })
    if len(t_matches) >= 3:
        avg_glob = (avg_h + avg_a) / 2.0
        att = max(0.85, min(1.15, (gf / len(t_matches)) / max(avg_glob, 0.5)))
        defe = max(0.85, min(1.15, (gt / len(t_matches)) / max(avg_glob, 0.5)))
    else:
        att, defe = 1.0, 1.0
    return {
        "n": int(len(t_matches)),
        "matches": rows,
        "gf": gf,
        "ga": gt,
        "att": float(att),
        "def": float(defe),
        "note": (
            "Le ultime 5 partite sono sul df multi-stagione di get_league_engine "
            "(storici + live), non sulla sola stagione corrente."
        ),
    }


def _xg_matches_for_team(league: str, canonical: str, season: int) -> Dict[str, Any]:
    records = load_archive(league)
    included = []
    skipped = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if parse_season(rec.get("season")) != season:
            continue
        home = resolve_team_name(rec.get("home_team"))
        away = resolve_team_name(rec.get("away_team"))
        if canonical not in (home.canonical, away.canonical):
            continue
        played = is_played(rec)
        hx, ax = parse_xg(rec.get("home_xg")), parse_xg(rec.get("away_xg"))
        kickoff, _ = parse_kickoff(rec.get("date"))
        item = {
            "id": rec.get("id"),
            "date": rec.get("date"),
            "home_raw": rec.get("home_team"),
            "away_raw": rec.get("away_team"),
            "home_canonical": home.canonical,
            "away_canonical": away.canonical,
            "home_xg": hx,
            "away_xg": ax,
            "home_goals": rec.get("home_goals"),
            "away_goals": rec.get("away_goals"),
            "is_result": played,
            "kickoff": kickoff.isoformat() if kickoff else None,
        }
        if played and hx is not None and ax is not None:
            if canonical == home.canonical:
                item["xg"], item["xga"] = hx, ax
            else:
                item["xg"], item["xga"] = ax, hx
            included.append(item)
        else:
            skipped.append(item)
    agg = season_averages(league, season)
    file_avg = agg.averages.get(canonical)
    return {
        "season": season,
        "matches_included": included,
        "matches_skipped": skipped,
        "n_included": len(included),
        "archive_average": file_avg,
        "unmapped_home_or_away": [
            r for r in included + skipped
            if False
        ],
    }


def _csv_presence(league: str, canonical: str) -> List[Dict[str, Any]]:
    import pandas as pd
    rows = []
    for path in get_league_db_files(league):
        try:
            df = pd.read_csv(path, on_bad_lines="warn", low_memory=False)
        except Exception as exc:
            rows.append({"file": os.path.basename(path), "error": str(exc)})
            continue
        if "HomeTeam" not in df.columns:
            continue
        hc = df["HomeTeam"].apply(clean_name)
        ac = df["AwayTeam"].apply(clean_name)
        n = int(((hc == canonical) | (ac == canonical)).sum())
        raw_home = sorted({str(x) for x in df.loc[hc == canonical, "HomeTeam"].unique()})
        raw_away = sorted({str(x) for x in df.loc[ac == canonical, "AwayTeam"].unique()})
        rows.append({
            "file": os.path.basename(path),
            "n_matches": n,
            "raw_names_as_home": raw_home,
            "raw_names_as_away": raw_away,
            "exists": True,
        })
    return rows


def _goals_fallback_ratio(df, team_clean: str, avg_h: float, avg_a: float) -> Dict[str, Any]:
    h_h = df[df["HomeClean"] == team_clean]
    a_h = df[df["AwayClean"] == team_clean]
    h_gf = h_h["FTHG"].dropna()
    a_gf = a_h["FTAG"].dropna()
    h_ga = h_h["FTAG"].dropna()
    a_ga = a_h["FTHG"].dropna()
    n_played = len(h_gf) + len(a_gf)
    gf = float(h_gf.sum() + a_gf.sum())
    ga = float(h_ga.sum() + a_ga.sum())
    exp_gf = float(avg_h * len(h_gf) + avg_a * len(a_gf))
    exp_ga = float(avg_a * len(h_ga) + avg_h * len(a_ga))
    att = _shrunk_ratio(gf, exp_gf, n_played)
    defe = _shrunk_ratio(ga, exp_ga, n_played)
    raw_att = (gf / exp_gf) if exp_gf > 0 and n_played > 0 else None
    raw_def = (ga / exp_ga) if exp_ga > 0 and n_played > 0 else None
    return {
        "n_played": int(n_played),
        "gf": gf,
        "ga": ga,
        "exp_gf": exp_gf,
        "exp_ga": exp_ga,
        "ratio_att_raw": raw_att,
        "ratio_def_raw": raw_def,
        "ratio_att_shrunk": float(att),
        "ratio_def_shrunk": float(defe),
        "prior": PRIOR_MATCHES,
    }


def trace_team(
    league: str,
    api_name: str,
    team_stats: Dict[str, Any],
    avg_h: float,
    avg_a: float,
    df,
    xg_data: Optional[Dict[str, Any]],
    league_xg: Optional[float],
    league_xga: Optional[float],
) -> Dict[str, Any]:
    resolution = resolve_team_name(api_name)
    canonical = clean_name(api_name)
    in_engine = canonical in team_stats
    stats = team_stats.get(canonical)
    used_fallback_default = stats is None
    if stats is None:
        stats = {"att": 1.0, "def": 1.0}

    xg_rec = xg_data.get(canonical) if xg_data else None
    xg_key_hit = xg_rec is not None
    shrinkage = None
    source = "unknown"
    if (
        xg_rec is not None and league_xg and league_xga and isinstance(xg_rec, dict)
    ):
        try:
            xg_v = float(xg_rec.get("xG_avg"))
            xga_v = float(xg_rec.get("xGA_avg"))
            import numpy as np
            val_ok = (np.isfinite(xg_v) and np.isfinite(xga_v) and xg_v >= 0 and xga_v >= 0)
        except (TypeError, ValueError):
            xg_v = xga_v = None
            val_ok = False
        n_xg = xg_rec.get("matches")
        n_ok = (isinstance(n_xg, (int, float)) and not isinstance(n_xg, bool)
                and n_xg == n_xg and float(n_xg) > 0)
        if val_ok and (n_ok or (xg_v > 0 and xga_v > 0)):
            raw_att = xg_v / league_xg if league_xg else None
            raw_def = xga_v / league_xga if league_xga else None
            if n_ok:
                att_s = _shrunk_ratio(xg_v, league_xg, n_xg)
                def_s = _shrunk_ratio(xga_v, league_xga, n_xg)
                source = "xg_shrunk"
            else:
                att_s = raw_att
                def_s = raw_def
                source = "xg_raw_no_matches_field"
            shrinkage = {
                "xG_avg": xg_v,
                "xGA_avg": xga_v,
                "matches": n_xg if n_ok else None,
                "league_xg": league_xg,
                "league_xga": league_xga,
                "ratio_att_raw": raw_att,
                "ratio_def_raw": raw_def,
                "ratio_att_shrunk": float(att_s),
                "ratio_def_shrunk": float(def_s),
                "prior": PRIOR_MATCHES,
                "n_ok": bool(n_ok),
            }
    goals = _goals_fallback_ratio(df, canonical, avg_h, avg_a)
    if source == "unknown":
        source = "goals_fallback"

    form = _form_from_df(df, canonical, avg_h, avg_a)
    mkt_values = get_market_values()
    val = mkt_values.get(canonical, 50)
    val_in_table = canonical in MARKET_VALUES
    import numpy as np
    mkt_factor = 1 + (np.log10(max(val, 10)) - 2.0) / 4
    mkt_factor = float(max(0.85, min(1.25, mkt_factor)))

    engine_att0_pure = stats.get("att0_pure") if isinstance(stats, dict) else None
    engine_def0_pure = stats.get("def0_pure") if isinstance(stats, dict) else None
    engine_att0 = stats.get("att0") if isinstance(stats, dict) else None
    engine_def0 = stats.get("def0") if isinstance(stats, dict) else None
    engine_att = stats.get("att") if isinstance(stats, dict) else None
    engine_def = stats.get("def") if isinstance(stats, dict) else None

    # Verifica: att0_pure di produzione vs shrinkage tracciato.
    match_pure = None
    if shrinkage and engine_att0_pure is not None:
        match_pure = (
            math.isclose(engine_att0_pure, shrinkage["ratio_att_shrunk"], rel_tol=0, abs_tol=1e-9)
            and math.isclose(engine_def0_pure, shrinkage["ratio_def_shrunk"], rel_tol=0, abs_tol=1e-9)
        )
    elif source == "goals_fallback" and engine_att0_pure is not None:
        match_pure = (
            math.isclose(engine_att0_pure, goals["ratio_att_shrunk"], rel_tol=0, abs_tol=1e-9)
            and math.isclose(engine_def0_pure, goals["ratio_def_shrunk"], rel_tol=0, abs_tol=1e-9)
        )

    csv_rows = _csv_presence(league, canonical)
    xg_matches = _xg_matches_for_team(league, canonical, CURRENT_SEASON_START_YEAR)

    elo_in = None
    try:
        from models.elo_engine import get_current_elo
        ratings = get_current_elo(league)
        elo_in = canonical in ratings
        elo_rating = ratings.get(canonical)
    except Exception as exc:
        elo_rating = None
        elo_in = f"error:{exc}"

    return {
        "api_name": api_name,
        "canonical": canonical,
        "name_resolution": {
            "raw": resolution.raw,
            "canonical": resolution.canonical,
            "source": resolution.source,
            "mapped": resolution.mapped,
        },
        "in_engine_stats": in_engine,
        "used_default_1_1_fallback": used_fallback_default,
        "xg_key_hit": xg_key_hit,
        "xg_record": xg_rec,
        "strength_source": source,
        "shrinkage_xg": shrinkage,
        "goals_fallback": goals,
        "form_last5": form,
        "market_value": {
            "canonical_key": canonical,
            "in_MARKET_VALUES": val_in_table,
            "value": val,
            "default_if_missing": 50,
            "mkt_factor": mkt_factor,
            "status": "verified" if val_in_table else "fallback",
        },
        "engine_stats": {
            "att": engine_att, "def": engine_def,
            "att0": engine_att0, "def0": engine_def0,
            "att0_pure": engine_att0_pure, "def0_pure": engine_def0_pure,
            "val": stats.get("val") if isinstance(stats, dict) else None,
        },
        "trace_matches_engine_att0_pure": match_pure,
        "csv_presence": csv_rows,
        "xg_matches_season": xg_matches,
        "in_elo": elo_in,
        "elo_rating": elo_rating,
        "elo_default_if_missing": 1500.0,
    }


def lambdas_from_production_stats(hs, as_, avg_h, avg_a) -> Dict[str, Any]:
    """Lambda come in get_full_poisson_two_heads, usando _stat_num di produzione."""
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
    attp_h = _stat_num(hs, "att0_pure", att0_h)
    defp_h = _stat_num(hs, "def0_pure", def0_h)
    attp_a = _stat_num(as_, "att0_pure", att0_a)
    defp_a = _stat_num(as_, "def0_pure", def0_a)
    base_pure_h = attp_h * defp_a * avg_h
    base_pure_a = attp_a * defp_h * avg_a
    S = base_h + base_a
    den = mkt_h + mkt_a
    if den > 0:
        norm_h = S * mkt_h / den
        norm_a = S * mkt_a / den
    else:
        norm_h, norm_a = base_h, base_a
    return {
        "avg_h": float(avg_h),
        "avg_a": float(avg_a),
        "base_h_1x2_anchor": float(base_h),
        "base_a_1x2_anchor": float(base_a),
        "mkt_h": float(mkt_h),
        "mkt_a": float(mkt_a),
        "norm_h_1x2": float(norm_h),
        "norm_a_1x2": float(norm_a),
        "norm_h_1x2_clipped": float(_clip_lambda(norm_h)),
        "norm_a_1x2_clipped": float(_clip_lambda(norm_a)),
        "base_pure_h_totals": float(base_pure_h),
        "base_pure_a_totals": float(base_pure_a),
        "base_pure_h_clipped": float(_clip_lambda(base_pure_h)),
        "base_pure_a_clipped": float(_clip_lambda(base_pure_a)),
    }


def reconstruct_match(
    home_api: str,
    away_api: str,
    league: str = "Bundesliga",
    *,
    api_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    sha = git_sha()
    engine = get_league_engine(league)
    if not engine:
        return {
            "ok": False,
            "error": f"get_league_engine({league!r}) ha restituito None",
            "git_sha": sha,
        }
    team_stats, avg_h, avg_a, df = engine
    xg_data = get_understat_xg(league)
    league_xg, league_xga, league_meta = _league_xg_means(xg_data)

    home_trace = trace_team(league, home_api, team_stats, avg_h, avg_a, df, xg_data, league_xg, league_xga)
    away_trace = trace_team(league, away_api, team_stats, avg_h, avg_a, df, xg_data, league_xg, league_xga)

    h_s = team_stats.get(clean_name(home_api), {"att": 1.0, "def": 1.0})
    a_s = team_stats.get(clean_name(away_api), {"att": 1.0, "def": 1.0})
    default_used_h = clean_name(home_api) not in team_stats
    default_used_a = clean_name(away_api) not in team_stats

    lambdas = lambdas_from_production_stats(h_s, a_s, avg_h, avg_a)
    m_poisson = get_full_poisson_two_heads(h_s, a_s, avg_h, avg_a)
    m_from_lambdas = _two_heads_from_lambdas(
        lambdas["base_h_1x2_anchor"], lambdas["base_a_1x2_anchor"],
        lambdas["mkt_h"], lambdas["mkt_a"],
        lambdas["base_pure_h_totals"], lambdas["base_pure_a_totals"],
    )
    poisson_crosscheck = {
        k: math.isclose(float(m_poisson[k]), float(m_from_lambdas[k]), rel_tol=0, abs_tol=1e-12)
        for k in ("1", "X", "2", "u25", "gg")
    }

    mercati = seven_markets(home_api, away_api, m_poisson)

    elo_p = None
    elo_error = None
    try:
        elo_p = predict_elo_probs(home_api, away_api, league)
    except Exception as exc:
        elo_error = str(exc)

    sel_a = apply_selector_A(mercati, home_api, away_api, elo_p)
    sel_b = apply_selector_B(mercati, home_api, away_api, elo_p)

    missing: List[str] = []
    if api_snapshot is None:
        missing.append(
            "snapshot API football-data (nomi shortName/name, match_id, utcDate, "
            "status TIMED/SCHEDULED al momento del Top Mix)"
        )
    missing.append(
        "snapshot Elo al millisecondo del click (l'Elo e' ricalcolato ora dai CSV "
        "dello snapshot 0695e9e: verificato sui dati committati, non su un dump Elo persistito)"
    )
    missing.append(
        "registro JSONBin della riga Top Mix (prob_sicuro, mercato, salvato_il, rank)"
    )

    reproduced = (
        sel_a["admitted"]
        and abs(float(sel_a["prob_val"]) - TARGET_DISPLAY) < 0.05
    )

    return {
        "ok": True,
        "git_sha": sha,
        "snapshot_commit": "0695e9e611e481d2a9f5648a3a9fcd4412f86070",
        "snapshot_commit_present": git_commit_0695e9e_present(),
        "current_equals_snapshot": sha.startswith("0695e9e"),
        "model_version": MODEL_VERSION_CURRENT,
        "reconstructed_at_utc": datetime.now(timezone.utc).isoformat(),
        "league": league,
        "season_engine_xg": CURRENT_SEASON,
        "season_start_year": CURRENT_SEASON_START_YEAR,
        "prior_matches": PRIOR_MATCHES,
        "round_window_days": TOP_MIX_ROUND_WINDOW_DAYS,
        "forbidden_functions_not_called": list(_FORBIDDEN_CALLS),
        "api_names": {
            "home_received": evidence(
                "verified" if api_snapshot else "assumption",
                home_api,
                "Nome passato a clean_name come farebbe fetch_and_calc_top_mix "
                "(shortName or name). Senza snapshot API e' un candidato.",
            ),
            "away_received": evidence(
                "verified" if api_snapshot else "assumption",
                away_api,
                "Come home_received.",
            ),
            "api_snapshot": api_snapshot,
        },
        "canonical_names": {
            "home": home_trace["canonical"],
            "away": away_trace["canonical"],
        },
        "league_goal_averages": {
            "avg_h": float(avg_h),
            "avg_a": float(avg_a),
            "n_matches_df": int(len(df)),
            "note": "Medie gol sul df concatenato (storici + live), produzione.",
            "status": "verified",
        },
        "league_xg_averages": {
            "league_xg": league_xg,
            "league_xga": league_xga,
            "meta": league_meta,
            "n_teams_in_xg_file": 0 if not xg_data else len(xg_data),
            "status": "verified" if league_meta.get("used") else "fallback",
        },
        "home": home_trace,
        "away": away_trace,
        "defaults_att_def_1": {
            "home": default_used_h,
            "away": default_used_a,
            "note": (
                "Se True, team_stats.get(..., {att:1, def:1}) di produzione: "
                "manca att0_pure e la testa Totali ripiega su att/def=1."
            ),
        },
        "lambdas": lambdas,
        "poisson_two_heads": {k: float(m_poisson[k]) for k in m_poisson},
        "poisson_crosscheck_vs_lambdas": poisson_crosscheck,
        "seven_markets_poisson": mercati,
        "elo_1x2": elo_p,
        "elo_error": elo_error,
        "selector_A": sel_a,
        "selector_B": sel_b,
        "selectors_agree": sel_a.get("best_market") == sel_b.get("best_market"),
        "target_92_1": {
            "target_prob_val": TARGET_DISPLAY,
            "reproduced_by_selector_A": reproduced,
            "selector_A_prob_val": sel_a.get("prob_val"),
            "selector_B_prob_val": sel_b.get("prob_val"),
            "gap_A": None if sel_a.get("prob_val") is None else round(float(sel_a["prob_val"]) - TARGET_DISPLAY, 3),
        },
        "missing_for_bit_exact_replay": missing,
        "csv_files": [os.path.basename(p) for p in get_league_db_files(league)],
    }


def try_fetch_api_names(
    league: str,
    home_hint: str,
    away_hint: str,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """GET sola lettura a football-data. Nessuna scrittura, niente JSONBin."""
    key = api_key if api_key is not None else FOOTBALL_DATA_API_KEY
    out: Dict[str, Any] = {
        "attempted": bool(key),
        "ok": False,
        "reason": None,
        "match": None,
    }
    if not key:
        out["reason"] = "FOOTBALL_DATA_API_KEY assente"
        return out
    import requests
    code = LEAGUE_CODE_MAP.get(league)
    if not code:
        out["reason"] = f"nessun codice API per {league}"
        return out
    try:
        r = requests.get(
            f"https://api.football-data.org/v4/competitions/{code}/matches",
            headers={"X-Auth-Token": key},
            timeout=20,
        )
    except Exception as exc:
        out["reason"] = f"errore di rete: {exc}"
        return out
    out["http_status"] = r.status_code
    if r.status_code != 200:
        out["reason"] = f"HTTP {r.status_code}"
        return out
    matches = r.json().get("matches") or []
    out["n_matches"] = len(matches)
    hints_h = {home_hint.lower(), clean_name(home_hint).lower(), "schalke", "schalke 04"}
    hints_a = {away_hint.lower(), clean_name(away_hint).lower(), "bayern", "bayern munich"}

    def _names(team: dict) -> List[str]:
        return [str(team.get("shortName") or ""), str(team.get("name") or "")]

    found = None
    for m in matches:
        hn = [x.lower() for x in _names(m.get("homeTeam") or {})]
        an = [x.lower() for x in _names(m.get("awayTeam") or {})]
        if any(any(h in n or n in h for h in hints_h) for n in hn if n) and \
           any(any(a in n or n in a for a in hints_a) for n in an if n):
            found = m
            break
        # anche speculare (Bayern in casa)
        if any(any(h in n or n in h for h in hints_h) for n in an if n) and \
           any(any(a in n or n in a for a in hints_a) for n in hn if n):
            found = m
            break
    if not found:
        out["reason"] = "partita non presente nella risposta API corrente"
        return out
    ht, at = found.get("homeTeam") or {}, found.get("awayTeam") or {}
    out["ok"] = True
    out["match"] = {
        "id": found.get("id"),
        "utcDate": found.get("utcDate"),
        "status": found.get("status"),
        "matchday": found.get("matchday"),
        "home_shortName": ht.get("shortName"),
        "home_name": ht.get("name"),
        "away_shortName": at.get("shortName"),
        "away_name": at.get("name"),
        "display_home": ht.get("shortName") or ht.get("name"),
        "display_away": at.get("shortName") or at.get("name"),
        "note": (
            "Nomi ATTUALI dell'API, non uno snapshot al momento del 92,1%. "
            "Usarli come 'stato attuale', non come prova del click originale."
        ),
    }
    timed = [m for m in matches if m.get("status") in ("TIMED", "SCHEDULED")]
    selected = select_next_matchday_matches(timed)
    out["next_matchday_ids"] = [m.get("id") for m in selected]
    out["in_next_matchday"] = found.get("id") in out["next_matchday_ids"]
    return out


def reconstruct_schalke_bayern(
    *,
    fetch_api: bool = False,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    api_info = {"attempted": False, "ok": False, "reason": "non richiesto"}
    if fetch_api:
        api_info = try_fetch_api_names("Bundesliga", "Schalke", "Bayern", api_key=api_key)

    results = []
    names_to_try: List[Tuple[str, str]] = list(DEFAULT_API_CANDIDATES)
    if api_info.get("ok") and api_info.get("match"):
        m = api_info["match"]
        pair = (m["display_home"], m["display_away"])
        names_to_try = [pair] + [c for c in names_to_try if c != pair]

    for home, away in names_to_try:
        rec = reconstruct_match(
            home, away, "Bundesliga",
            api_snapshot=api_info.get("match") if api_info.get("ok") else None,
        )
        rec["candidate_api_names"] = {"home": home, "away": away}
        results.append(rec)

    # La ricostruzione "principale" e' il primo candidato (API attuale se c'e',
    # altrimenti shortName tipici Schalke/Bayern).
    primary = results[0] if results else {}
    reproduced_any = [
        {
            "home": r["candidate_api_names"]["home"],
            "away": r["candidate_api_names"]["away"],
            "prob_val_A": (r.get("selector_A") or {}).get("prob_val"),
            "market_A": (r.get("selector_A") or {}).get("best_market"),
            "reproduced": (r.get("target_92_1") or {}).get("reproduced_by_selector_A"),
        }
        for r in results if r.get("ok")
    ]
    return {
        "primary": primary,
        "all_name_candidates": reproduced_any,
        "api_fetch": api_info,
        "identical_poisson_across_mapped_candidates": _poisson_identical(results),
    }


def _poisson_identical(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    mapped = []
    for r in results:
        if not r.get("ok"):
            continue
        h = r.get("home") or {}
        a = r.get("away") or {}
        if h.get("used_default_1_1_fallback") or a.get("used_default_1_1_fallback"):
            continue
        mapped.append(r)
    if len(mapped) < 2:
        return {"comparable": len(mapped), "identical": True}
    keys = ("1", "X", "2", "u25", "gg")
    first = mapped[0]["poisson_two_heads"]
    ok = all(
        all(math.isclose(float(r["poisson_two_heads"][k]), float(first[k]), rel_tol=0, abs_tol=1e-12)
            for k in keys)
        for r in mapped[1:]
    )
    return {"comparable": len(mapped), "identical": ok}


def write_json(payload: Dict[str, Any], path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_json_safe(payload), f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ricostruzione diagnostica Top Mix (sola lettura)")
    parser.add_argument("--home", default="Schalke")
    parser.add_argument("--away", default="Bayern")
    parser.add_argument("--league", default="Bundesliga")
    parser.add_argument("--fetch-api", action="store_true",
                        help="GET football-data (nomi attuali). Non scrive nulla.")
    parser.add_argument("--all-candidates", action="store_true",
                        help="Prova i candidati di nomi API Schalke/Bayern.")
    parser.add_argument("--output", default=None,
                        help="Percorso JSON di output")
    args = parser.parse_args(argv)

    if args.all_candidates or (args.home == "Schalke" and args.away == "Bayern"):
        payload = reconstruct_schalke_bayern(fetch_api=args.fetch_api)
    else:
        payload = {
            "primary": reconstruct_match(args.home, args.away, args.league),
            "all_name_candidates": [],
            "api_fetch": try_fetch_api_names(args.league, args.home, args.away) if args.fetch_api
            else {"attempted": False},
        }
    out = args.output or os.path.join(
        _AUDIT_DIR, "results", "schalke_bayern_921.json"
    )
    write_json(payload, out)
    primary = payload.get("primary") or {}
    sel = primary.get("selector_A") or {}
    tgt = primary.get("target_92_1") or {}
    print(f"output: {out}")
    print(f"canonical: {primary.get('canonical_names')}")
    print(f"selector A: {sel.get('best_market')}  {sel.get('prob_val')}%")
    print(f"92.1% riprodotto: {tgt.get('reproduced_by_selector_A')}")
    print(f"mancanti: {primary.get('missing_for_bit_exact_replay')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
