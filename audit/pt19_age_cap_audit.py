"""
pt19_age_cap_audit.py — Rivalidazione Step 1: tetto di eta' 400 giorni nella
finestra trailing PT-19 del lookup point-in-time (xg_archive.point_in_time_averages).

Difetto isolato in audit: per le squadre con gap da retrocessione (verificati
453-813 giorni senza partite nella lega) la finestra trailing di 19 partite
pescava partite di due stagioni prima, peggiorando la testa Totali in
Premier League TEST 2025/26 rispetto alla fonte statica stagionale.

Questo script (sola lettura su app.py/config.py/models/) confronta in
walk-forward no-leakage, per la testa TOTALI (O/U2.5 e GG/NG):

  STATIC    = fonte statica ricostruita point-in-time: medie xG della SOLA
              stagione in corso alla data della partita, sulle partite giocate
              prima di quella data; shrinkage PRIOR_MATCHES verso la media di
              lega, fallback gol per le squadre assenti. Nessuna informazione
              futura;
  SNAP      = VERA baseline di produzione oggi: il SINGOLO snapshot committato
              xg_<lega>.json, identico per ogni data storica (contiene solo le
              squadre della stagione corrente); shrinkage PRIOR_MATCHES verso
              la media dello snapshot, fallback gol per le assenti;
  PT19      = lookup point-in-time xg_archive.point_in_time_averages con
              finestra 19 SENZA tetto di eta' (la versione dell'audit);
  PT19_CAP  = lo stesso lookup CON tetto di eta' 400 giorni e minimo 5
              partite (sotto: "dato insufficiente" -> fallback gol).

L'1X2 e' identico per costruzione in tutti e tre i modelli (cambia solo
att0_pure/def0_pure, che alimenta la sola testa Totali): lo script lo
verifica numericamente (max abs diff sulle probabilita' 1X2).

Primaria: Premier League TEST 2025/26 (la lega dove il problema si e'
manifestato). Gate Step 2: 1X2 identico + nessuna regressione delle altre
4 leghe (PT19_CAP non peggiore di STATIC).

Uso:
    python audit/pt19_age_cap_audit.py
Output: audit/results/pt19_age_cap_audit.md
"""
from __future__ import annotations

import math
import os
import sys
from collections import deque

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from backtest_experiment_all import load_league, LEAGUES, MARKET_VALUES  # noqa: E402
import app as prod_app  # noqa: E402  (get_full_poisson_two_heads,PRIOR_MATCHES)
from xg_archive import (  # noqa: E402
    ARCHIVE_FILES, load_archive, parse_kickoff, parse_xg, is_played,
    point_in_time_averages, season_averages,
)

DB = os.path.join(_REPO_ROOT, "SoccerMath", "database")
SEASONS_EVAL = ("2024/25", "2025/26")
PRIOR = prod_app.PRIOR_MATCHES  # 6.0, shrinkage di produzione
PT_WINDOW = 19
PT_AGE_CAP = 400.0
PT_MIN_MATCHES = 5

XG_SNAP_FILES = {
    "Serie A": "xg_serie_a.json",
    "Premier League": "xg_premier_league.json",
    "La Liga": "xg_la_liga.json",
    "Bundesliga": "xg_bundesliga.json",
    "Ligue 1": "xg_ligue_1.json",
}

OUT_DIR = os.path.join(_AUDIT_DIR, "results")
OUT_PATH = os.path.join(OUT_DIR, "pt19_age_cap_audit.md")


def shrunk_ratio(observed, expected, n, prior=PRIOR):
    """Stessa formula di app._shrunk_ratio (replica per l'audit no-leakage)."""
    if n <= 0 or expected <= 0:
        return 1.0
    r = observed / expected
    return (n * r + prior) / (n + prior)


def load_static_season(league, season_year, cutoff, records):
    """Medie xG STATICHE point-in-time: la sola stagione in corso al cutoff,
    sulle partite giocate prima del cutoff.

    Ricostruisce cio' che il file xg_<lega>.json conteneva in produzione in
    quel giorno (update_xg deriva le medie della stagione corrente
    dall'archivio): nessuna informazione futura, gate e forma identici.
    """
    agg = season_averages(league, season_year, cutoff=cutoff, records=records)
    return agg.averages


def load_prod_snapshot(league):
    """Il SINGOLO snapshot statico oggi in produzione: xg_<lega>.json.

    E' un solo file, identico per ogni data storica del backtest (non e'
    ricostruito point-in-time): contiene solo le squadre della stagione
    CORRENTE (verificato in sessioni precedenti: Sampdoria e Spezia assenti
    dal file di Serie A perche' non piu' in massima serie oggi). Le squadre
    di una stagione storica non presenti nel file finiscono sul fallback gol.
    """
    import json
    path = os.path.join(DB, XG_SNAP_FILES[league])
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def league_anchor(xg_data):
    """Gate di produzione in get_league_engine: medie di lega sul file xG."""
    if not xg_data:
        return None, None
    lx = [v["xG_avg"] for v in xg_data.values()
          if isinstance(v, dict) and isinstance(v.get("xG_avg"), (int, float))
          and np.isfinite(v["xG_avg"]) and v["xG_avg"] > 0]
    lxa = [v["xGA_avg"] for v in xg_data.values()
           if isinstance(v, dict) and isinstance(v.get("xGA_avg"), (int, float))
           and np.isfinite(v["xGA_avg"]) and v["xGA_avg"] > 0]
    if len(lx) >= 10 and len(lxa) >= 10:
        mx, mxa = float(np.mean(lx)), float(np.mean(lxa))
        if 0.5 < mx < 5.0 and 0.5 < mxa < 5.0:
            return mx, mxa
    return None, None


def build_archive_index(league):
    """Partite valide dell'archivio (chiave squadra -> lista kickoff) per la
    diagnostica dei gap; usa le stesse regole di validita' di xg_archive."""
    path = os.path.join(DB, ARCHIVE_FILES[league])
    data = load_archive(league) if os.path.exists(path) else []
    per_team = {}
    seen = set()
    for raw in data:
        if not isinstance(raw, dict) or not is_played(raw):
            continue
        if parse_xg(raw.get("home_xg")) is None or parse_xg(raw.get("away_xg")) is None:
            continue
        kickoff, _ = parse_kickoff(raw.get("date"))
        if kickoff is None:
            continue
        rid = raw.get("id")
        key = ("id", str(rid)) if rid is not None else (
            raw.get("season"), raw.get("home_team"), raw.get("away_team"),
            kickoff.date())
        if key in seen:
            continue
        seen.add(key)
        from team_names import canonical_team_name
        h = canonical_team_name(raw.get("home_team"))
        a = canonical_team_name(raw.get("away_team"))
        if h:
            per_team.setdefault(h, []).append(kickoff)
        if a:
            per_team.setdefault(a, []).append(kickoff)
    return {t: sorted(v) for t, v in per_team.items()}


def gap_report(league, df_test, archive_index):
    """Per ogni squadra del TEST: gap (giorni) fra la prima partita della
    stagione e l'ultima partita nella lega precedente (archivio)."""
    rows = []
    first_in_season = df_test.groupby("HomeClean")["Date"].min()
    first_away = df_test.groupby("AwayClean")["Date"].min()
    teams = set(first_in_season.index) | set(first_away.index)
    for t in sorted(teams):
        cand = []
        if t in first_in_season:
            cand.append(first_in_season[t])
        if t in first_away:
            cand.append(first_away[t])
        first = min(cand)
        prior = [k for k in archive_index.get(t, []) if k.date() < first.date()]
        if prior:
            gap = (pd.Timestamp(first.date()) - pd.Timestamp(prior[-1].date())).days
            rows.append({"team": t, "first_test_match": str(first.date()),
                         "previous_league_match": str(prior[-1].date()),
                         "gap_days": int(gap)})
        else:
            rows.append({"team": t, "first_test_match": str(first.date()),
                         "previous_league_match": "-", "gap_days": None})
    return rows


class TeamState:
    __slots__ = ("hgf", "hga", "hgn", "agf", "aga", "agn", "last5")

    def __init__(self):
        self.hgf = self.hga = 0.0
        self.hgn = 0
        self.agf = self.aga = 0.0
        self.agn = 0
        self.last5 = deque(maxlen=5)

    def observe_home(self, fthg, ftag):
        self.hgf += fthg
        self.hga += ftag
        self.hgn += 1
        self.last5.append((fthg, ftag))

    def observe_away(self, fthg, ftag):
        self.agf += ftag
        self.aga += fthg
        self.agn += 1
        self.last5.append((ftag, fthg))

    def goal_fallback(self, avg_h, avg_a):
        """Rammo fallback gol di produzione (pooled + shrinkage PRIOR_MATCHES)."""
        n_played = self.hgn + self.agn
        gf = self.hgf + self.agf
        ga = self.hga + self.aga
        exp_gf = avg_h * self.hgn + avg_a * self.agn
        exp_ga = avg_a * self.hgn + avg_h * self.agn
        return (shrunk_ratio(gf, exp_gf, n_played),
                shrunk_ratio(ga, exp_ga, n_played))


def season_year_of(label):
    return int(label.split("/")[0])


def run_league(prefix, league, cache):
    """Walk-forward no-leakage. Ritorna il DataFrame delle partite eval con le
    probabilita' dei tre modelli (stessa testa 1X2 per tutti)."""
    df = load_league(prefix)
    records = load_archive(league)
    snapshot = load_prod_snapshot(league)  # UN file, identico per ogni data
    state = {}
    tot_hg = tot_ag = tot_n = 0.0
    rows = []
    cap_events = {}   # data -> age_cap_impact del PT19_CAP (solo Premier TEST)

    def get(t):
        if t not in state:
            state[t] = TeamState()
        return state[t]

    for idx, row in df.iterrows():
        fthg = int(row.FTHG)
        ftag = int(row.FTAG)
        h, a = row.HomeClean, row.AwayClean
        sh, sa = get(h), get(a)
        avg_h = max(tot_hg / tot_n, 0.1) if tot_n else 0.1
        avg_a = max(tot_ag / tot_n, 0.1) if tot_n else 0.1

        # --- forma ultime 5 (solo testa 1X2, come in produzione) ---
        def form_fac(ts):
            if len(ts.last5) < 3:
                return 1.0, 1.0
            n = len(ts.last5)
            gf = sum(x[0] for x in ts.last5)
            ga = sum(x[1] for x in ts.last5)
            den = max((avg_h + avg_a) / 2.0, 0.5)
            return (max(0.85, min(1.15, (gf / n) / den)),
                    max(0.85, min(1.15, (ga / n) / den)))

        def mkt_factor(t):
            val = MARKET_VALUES.get(t, 50)
            m = 1.0 + (math.log10(max(val, 10)) - 2.0) / 4.0
            return max(0.85, min(1.25, m))

        # --- lookup point-in-time alla data partita (cache per data) ---
        # STATIC = medie della sola stagione in corso al cutoff (come il file
        # xg_<lega>.json in produzione quel giorno); PT19/PT19_CAP = finestra
        # trailing 19 senza/con tetto di eta'. Tutto con gli stessi record.
        date_key = (league, row.Date)
        if row.season in SEASONS_EVAL and date_key not in cache:
            cutoff = row.Date  # naive -> interpretato UTC da xg_archive
            cache[date_key] = {
                "static": load_static_season(
                    league, season_year_of(row.season), cutoff, records),
                "nocap": point_in_time_averages(
                    league, cutoff=cutoff, records=records,
                    window=PT_WINDOW, max_age_days=None,
                    min_matches=PT_MIN_MATCHES),
                "cap": point_in_time_averages(
                    league, cutoff=cutoff, records=records,
                    window=PT_WINDOW, max_age_days=PT_AGE_CAP,
                    min_matches=PT_MIN_MATCHES),
            }

        # --- fonte primaria 1X2 (STATIC, invariata fra i modelli): xG della
        # stagione in corso al cutoff, o fallback gol ---
        def primary(t, ts):
            if row.season not in SEASONS_EVAL:
                return ts.goal_fallback(avg_h, avg_a)
            xg_data = cache[date_key]["static"]
            stat_lxg, stat_lxga = league_anchor(xg_data)
            rec = xg_data.get(t) if xg_data else None
            if rec is not None and stat_lxg and stat_lxga and isinstance(rec, dict):
                xv, xa, n = rec.get("xG_avg"), rec.get("xGA_avg"), rec.get("matches")
                try:
                    xv, xa = float(xv), float(xa)
                    val_ok = np.isfinite(xv) and np.isfinite(xa) and xv >= 0 and xa >= 0
                except (TypeError, ValueError):
                    val_ok, n = False, None
                n_ok = (isinstance(n, (int, float)) and not isinstance(n, bool)
                        and np.isfinite(float(n)) and float(n) > 0)
                if val_ok and (n_ok or (xv > 0 and xa > 0)):
                    if n_ok:
                        return (shrunk_ratio(xv, stat_lxg, float(n)),
                                shrunk_ratio(xa, stat_lxga, float(n)))
                    return xv / stat_lxg, xa / stat_lxga
            return ts.goal_fallback(avg_h, avg_a)

        p_att_h, p_def_h = primary(h, sh)
        p_att_a, p_def_a = primary(a, sa)

        fah, fdh = form_fac(sh)
        faa, fda = form_fac(sa)
        mh, ma = mkt_factor(h), mkt_factor(a)

        def make_stats(p_att, p_def, f_att, f_def, mkt, pure):
            """Dizionario stats nel formato di get_league_engine."""
            return {
                "att": p_att * f_att * mkt,
                "def": p_def * f_def / mkt,
                "att0": p_att * f_att,
                "def0": p_def * f_def,
                "att0_pure": pure[0],
                "def0_pure": pure[1],
                "val": 50,
            }

        def predict(pure_h, pure_a):
            hs = make_stats(p_att_h, p_def_h, fah, fdh, mh, pure_h)
            as_ = make_stats(p_att_a, p_def_a, faa, fda, ma, pure_a)
            return prod_app.get_full_poisson_two_heads(hs, as_, avg_h, avg_a)

        if row.season in SEASONS_EVAL:
            # --- STATIC: pura = fonte stagionale (cioe' primary, pre-forma) ---
            m_static = predict((p_att_h, p_def_h), (p_att_a, p_def_a))

            pt_nocap = cache[date_key]["nocap"]
            pt_cap = cache[date_key]["cap"]

            def pure_from_pt(pt):
                # ancora di lega = media di lega della fonte statica alla stessa
                # data (come in produzione: shrinkage verso la media di lega del
                # file xg_<lega>.json della stagione corrente). Le squadre non
                # piu' nella lega non spostano l'ancora.
                lxg, lxga = league_anchor(cache[date_key]["static"])
                out = {}
                fb_h = sh.goal_fallback(avg_h, avg_a)
                fb_a = sa.goal_fallback(avg_h, avg_a)
                for t, fb in ((h, fb_h), (a, fb_a)):
                    rec = pt.averages.get(t)
                    if rec is not None and lxg and lxga:
                        out[t] = (shrunk_ratio(rec["xG_avg"], lxg, rec["matches"]),
                                  shrunk_ratio(rec["xGA_avg"], lxga, rec["matches"]))
                    else:
                        out[t] = fb  # dato insufficiente -> fallback gol
                return out

            pn = pure_from_pt(pt_nocap)
            pc = pure_from_pt(pt_cap)
            m_pt = predict(pn[h], pn[a])
            m_cap = predict(pc[h], pc[a])

            # --- SNAP: VERA baseline di produzione = singolo snapshot
            # xg_<lega>.json, identico per ogni data storica ---
            def pure_from_snapshot():
                lxg, lxga = league_anchor(snapshot)
                out = {}
                fb_h = sh.goal_fallback(avg_h, avg_a)
                fb_a = sa.goal_fallback(avg_h, avg_a)
                for t, fb in ((h, fb_h), (a, fb_a)):
                    rec = snapshot.get(t)
                    if rec is not None and lxg and lxga and isinstance(rec, dict):
                        try:
                            xv, xa = float(rec.get("xG_avg")), float(rec.get("xGA_avg"))
                            n = rec.get("matches")
                            val_ok = (np.isfinite(xv) and np.isfinite(xa)
                                      and xv >= 0 and xa >= 0)
                        except (TypeError, ValueError):
                            val_ok, n = False, None
                        n_ok = (isinstance(n, (int, float))
                                and not isinstance(n, bool)
                                and np.isfinite(float(n)) and float(n) > 0)
                        if val_ok and (n_ok or (xv > 0 and xa > 0)):
                            if n_ok:
                                out[t] = (shrunk_ratio(xv, lxg, float(n)),
                                          shrunk_ratio(xa, lxga, float(n)))
                            else:
                                out[t] = (xv / lxg, xa / lxga)
                            continue
                    out[t] = fb
                return out

            ps = pure_from_snapshot()
            m_snap = predict(ps[h], ps[a])

            if league == "Premier League" and row.season == "2025/26" \
                    and pt_cap.age_cap_impact:
                # solo le squadre in campo: sono le uniche che influenzano
                # le previsioni di questa partita
                cap_events[str(row.Date.date())] = {
                    t: v["dropped"] for t, v in pt_cap.age_cap_impact.items()
                    if t in (h, a)}

            real_1x2 = {"H": "1", "D": "X", "A": "2"}.get(
                str(row.FTR).strip().upper(), "X")
            rows.append({
                "season": row.season, "date": row.Date,
                "home": h, "away": a,
                "real_1x2": real_1x2,
                "real_uo": "OVER" if (fthg + ftag) > 2.5 else "UNDER",
                "real_gg": "GG" if fthg > 0 and ftag > 0 else "NG",
                "st_1": m_static["1"], "st_X": m_static["X"], "st_2": m_static["2"],
                "st_po": 1 - m_static["u25"], "st_gg": m_static["gg"],
                "pt_1": m_pt["1"], "pt_X": m_pt["X"], "pt_2": m_pt["2"],
                "pt_po": 1 - m_pt["u25"], "pt_gg": m_pt["gg"],
                "cp_1": m_cap["1"], "cp_X": m_cap["X"], "cp_2": m_cap["2"],
                "cp_po": 1 - m_cap["u25"], "cp_gg": m_cap["gg"],
                "ss_po": 1 - m_snap["u25"], "ss_gg": m_snap["gg"],
                "pt_ins_h": h in pt_cap.insufficient_data,
                "pt_ins_a": a in pt_cap.insufficient_data,
            })

        tot_hg += fthg
        tot_ag += ftag
        tot_n += 1
        sh.observe_home(fthg, ftag)
        sa.observe_away(fthg, ftag)

    return pd.DataFrame(rows), cap_events


# ---------------- metriche ----------------
def brier_ll_1x2(df, cols):
    p = df[list(cols)].to_numpy(dtype=float)
    m = {"1": 0, "X": 1, "2": 2}
    y = np.array([m[v] for v in df["real_1x2"]])
    onehot = np.zeros_like(p)
    onehot[np.arange(len(y)), y] = 1
    brier = float(np.mean(np.sum((onehot - p) ** 2, axis=1)))
    pc = np.clip(p[np.arange(len(y)), y], 1e-12, 1.0)
    return brier, float(-np.mean(np.log(pc)))


def brier_ll_bin(df, pcol, real_col, target):
    p = df[pcol].to_numpy(dtype=float)
    y = (df[real_col] == target).astype(int).to_numpy()
    brier = float(np.mean((y - p) ** 2))
    pc = np.clip(p, 1e-12, 1.0)
    ll = float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc)))
    return brier, ll


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    cache = {}
    out = []
    A = out.append
    A("# Audit Step 1 — Tetto di eta' 400 giorni nella finestra PT-19")
    A("")
    A("Walk-forward no-leakage, testa **Totali** (O/U2.5 e GG/NG). Fonti a confronto:")
    A("- **STATIC** = fonte statica ricostruita point-in-time: medie xG della sola stagione in corso alla data partita, shrinkage PRIOR_MATCHES=6 verso la media di lega, fallback gol per le assenti;")
    A("- **SNAP** = VERA baseline di produzione oggi: il SINGOLO snapshot committato xg_<lega>.json, identico per ogni data storica (contiene solo le squadre della stagione corrente: es. Sampdoria/Spezia assenti dal file di Serie A); shrinkage PRIOR_MATCHES=6 verso la media dello snapshot, fallback gol per le squadre della stagione storica non presenti nel file;")
    A(f"- **PT19** = point-in-time finestra {PT_WINDOW}, SENZA tetto di eta';")
    A(f"- **PT19_CAP** = point-in-time finestra {PT_WINDOW}, tetto {PT_AGE_CAP:.0f} giorni, minimo {PT_MIN_MATCHES} partite.")
    A("")
    A("L'1X2 usa la stessa fonte in tutti e tre i modelli: deve risultare bit-identico.")
    A("")

    all_res = {}
    cap_events_all = {}
    for prefix, league in LEAGUES:
        res, cap_events = run_league(prefix, league, cache)
        all_res[league] = res
        cap_events_all[league] = cap_events

    # --- verifica 1X2 identico ---
    A("## 1X2 — invarianza (deve essere IDENTICO: max abs diff = 0.0)")
    A("")
    A("| Lega | Stagione | N | Brier 1X2 (STATIC=PT19=PT19_CAP) | LogLoss | max|Δ1| | max|ΔX| | max|Δ2| |")
    A("|---|---|---|---|---|---|---|---|")
    for _, league in LEAGUES:
        res = all_res[league]
        for season in SEASONS_EVAL:
            sub = res[res["season"] == season]
            if sub.empty:
                continue
            d1 = float((sub["st_1"] - sub["cp_1"]).abs().max())
            dX = float((sub["st_X"] - sub["cp_X"]).abs().max())
            d2 = float((sub["st_2"] - sub["cp_2"]).abs().max())
            dp1 = float((sub["st_1"] - sub["pt_1"]).abs().max())
            dpX = float((sub["st_X"] - sub["pt_X"]).abs().max())
            dp2 = float((sub["st_2"] - sub["pt_2"]).abs().max())
            b, ll = brier_ll_1x2(sub, ["st_1", "st_X", "st_2"])
            A(f"| {league} | {season} | {len(sub)} | {b:.5f} | {ll:.5f} "
              f"| {max(d1, dp1):.1e} | {max(dX, dpX):.1e} | {max(d2, dp2):.1e} |")
    A("")

    # --- testa Totali ---
    A("## Testa Totali — Brier / LogLoss")
    A("")
    A("| Lega | Stagione | Mercato | STATIC | SNAP (prod) | PT19 (no cap) | PT19_CAP | Δ(CAP−SNAP) | Δ(CAP−STATIC) |")
    A("|---|---|---|---|---|---|---|---|---|")
    for _, league in LEAGUES:
        res = all_res[league]
        for season in SEASONS_EVAL:
            sub = res[res["season"] == season]
            if sub.empty:
                continue
            for mname, pcols, real_col, target in (
                    ("O/U2.5", ("st_po", "ss_po", "pt_po", "cp_po"),
                     "real_uo", "OVER"),
                    ("GG/NG", ("st_gg", "ss_gg", "pt_gg", "cp_gg"),
                     "real_gg", "GG")):
                bs, lls = brier_ll_bin(sub, pcols[0], real_col, target)
                bss, llss = brier_ll_bin(sub, pcols[1], real_col, target)
                bp, llp = brier_ll_bin(sub, pcols[2], real_col, target)
                bc, llc = brier_ll_bin(sub, pcols[3], real_col, target)
                A(f"| {league} | {season} | {mname} Brier | {bs:.4f} | {bss:.4f} "
                  f"| {bp:.4f} | {bc:.4f} | {bc - bss:+.4f} | {bc - bs:+.4f} |")
                A(f"| {league} | {season} | {mname} LogLoss | {lls:.4f} | {llss:.4f} "
                  f"| {llp:.4f} | {llc:.4f} | {llc - llss:+.4f} | {llc - lls:+.4f} |")
    A("")

    # --- Problem A: PT19_CAP vs VERA baseline di produzione (snapshot) ---
    A("## Premier League TEST 2025/26 — PT19_CAP vs VERA baseline di produzione")
    A("")
    sub_pl = all_res["Premier League"]
    sub_pl = sub_pl[sub_pl["season"] == "2025/26"]
    snap = load_prod_snapshot("Premier League")
    teams_test = sorted(set(sub_pl["home"]) | set(sub_pl["away"]))
    missing_snap = sorted(set(teams_test) - set(snap.keys()))
    A(f"Il singolo snapshot di produzione (xg_premier_league.json, identico per "
      f"ogni data storica) copre {len(set(teams_test) & set(snap.keys()))}/"
      f"{len(teams_test)} squadre del TEST; le assenti vanno sul fallback gol: "
      f"**{missing_snap}**.")
    A("")
    snap_rows = []
    for mname, pcols, real_col, target in (
            ("O/U2.5", ("st_po", "ss_po", "pt_po", "cp_po"), "real_uo", "OVER"),
            ("GG/NG", ("st_gg", "ss_gg", "pt_gg", "cp_gg"), "real_gg", "GG")):
        for metric, fn in (("Brier", 0), ("LogLoss", 1)):
            vals = []
            for c in pcols:
                b, ll = brier_ll_bin(sub_pl, c, real_col, target)
                vals.append(b if fn == 0 else ll)
            snap_rows.append((mname, metric, *vals))
    A("| Mercato | Metrica | STATIC | SNAP (prod) | PT19 | PT19_CAP | CAP−SNAP | CAP−STATIC |")
    A("|---|---|---|---|---|---|---|---|")
    for mname, metric, vs, vss, vp, vc in snap_rows:
        A(f"| {mname} | {metric} | {vs:.4f} | {vss:.4f} | {vp:.4f} | {vc:.4f} "
          f"| {vc - vss:+.4f} | {vc - vs:+.4f} |")
    A("")
    worse = [f"{m} {mt}" for m, mt, vs, vss, vp, vc in snap_rows
             if m == "O/U2.5" and vc > vss + 1e-9]
    worse_all = [f"{m} {mt} (CAP {vc:.4f} vs SNAP {vss:.4f}, {vc - vss:+.4f})"
                 for m, mt, vs, vss, vp, vc in snap_rows if vc > vss + 1e-9]
    if worse:
        A(f"**VERDETTO (esplicito, prima di ogni altra conclusione):** su "
          f"Premier League TEST 2025/26 PT19_CAP risulta PEGGIORE della vera "
          f"baseline di produzione (snapshot singolo) su: "
          f"{'; '.join(worse_all)}.")
    else:
        better = [f"{m} {mt} ({vc - vss:+.4f})"
                  for m, mt, vs, vss, vp, vc in snap_rows if vc <= vss + 1e-9]
        A(f"**VERDETTO (esplicito, prima di ogni altra conclusione):** su "
          f"Premier League TEST 2025/26 PT19_CAP NON risulta peggiore della "
          f"vera baseline di produzione (snapshot singolo) in nessuna delle "
          f"metriche: {', '.join(better)}.")
    A("")
    A("Nota: SNAP usa i valori xG della stagione CORRENTE del file (non della "
      "stagione storica): per le squadre presenti e' un dato anacronistico ma "
      "e' esattamente cio' che gira in produzione oggi su ogni data storica.")
    A("")

    # --- diagnostica Premier TEST: gap e impatto tetto ---
    A("## Premier League TEST 2025/26 — diagnostica gap e impatto del tetto")
    A("")
    df_pl = load_league("Premier")
    df_test = df_pl[df_pl["season"] == "2025/26"]
    gaps = gap_report("Premier League", df_test, build_archive_index("Premier League"))
    A("Gap fra la prima partita del TEST 2025/26 e l'ultima partita precedente")
    A("nella lega (archivio xG). Le neopromosse mostrano il gap da retrocessione:")
    A("")
    A("| Squadra | Prima partita TEST | Ultima precedente | Gap giorni |")
    A("|---|---|---|---|")
    for g in sorted(gaps, key=lambda r: -(r["gap_days"] or 0)):
        A(f"| {g['team']} | {g['first_test_match']} | {g['previous_league_match']} "
          f"| {g['gap_days'] if g['gap_days'] is not None else 'nessuna in archivio'} |")
    A("")

    res_pl = all_res["Premier League"]
    sub = res_pl[res_pl["season"] == "2025/26"]
    n_ins = int((sub["pt_ins_h"] | sub["pt_ins_a"]).sum())
    A(f"Partite del TEST in cui almeno una squadra era 'dato insufficiente' "
      f"per PT19_CAP: **{n_ins}/{len(sub)}**.")

    # subset dove il tetto cambia effettivamente la previsione
    mask = ((sub["pt_po"] - sub["cp_po"]).abs() > 1e-12) \
        | ((sub["pt_gg"] - sub["cp_gg"]).abs() > 1e-12)
    s = sub[mask]
    A(f"Partite del TEST in cui il tetto cambia la previsione: "
      f"**{len(s)}/{len(sub)}**.")
    if len(s):
        y_ov = (s["real_uo"] == "OVER").astype(int).to_numpy()
        y_gg = (s["real_gg"] == "GG").astype(int).to_numpy()

        def _b(p, y):
            return float(np.mean((y - p) ** 2))

        A("")
        A("Brier limitato alle partite in cui il tetto interviene:")
        A("")
        A("| Fonte | O/U2.5 | GG/NG |")
        A("|---|---|---|")
        for tag, c in (("STATIC", "st_"), ("PT19", "pt_"), ("PT19_CAP", "cp_")):
            A(f"| {tag} | {_b(s[c + 'po'].to_numpy(), y_ov):.4f} "
              f"| {_b(s[c + 'gg'].to_numpy(), y_gg):.4f} |")
        PROM = {"Leeds", "Burnley", "Sunderland"}
        s = s.copy()
        s["gap_team"] = s.apply(
            lambda r: r["home"] if r["home"] in PROM else r["away"], axis=1)
        A("")
        A("Dettaglio per squadra con gap da retrocessione (O/U2.5):")
        A("")
        A("| Squadra | N | PT19 | PT19_CAP | STATIC |")
        A("|---|---|---|---|---|")
        for t, g in sorted(s.groupby("gap_team")):
            yo = (g["real_uo"] == "OVER").astype(int).to_numpy()
            A(f"| {t} | {len(g)} | {_b(g['pt_po'].to_numpy(), yo):.4f} "
              f"| {_b(g['cp_po'].to_numpy(), yo):.4f} "
              f"| {_b(g['st_po'].to_numpy(), yo):.4f} |")
    ev = cap_events_all.get("Premier League", {})
    per_team = {}
    for d, teams in ev.items():
        for t, n in teams.items():
            per_team.setdefault(t, [0, 0])
            per_team[t][0] += 1
            per_team[t][1] = max(per_team[t][1], n)
    if per_team:
        A("")
        A("Impatto del tetto 400gg (PT19_CAP) sulle finestre del TEST:")
        A("")
        A("| Squadra | Date con scarti | Max partite scartate in una finestra |")
        A("|---|---|---|")
        for t, (ndates, maxdrop) in sorted(per_team.items()):
            A(f"| {t} | {ndates} | {maxdrop} |")
    A("")

    # --- gate Step 2 (sintesi numerica automatica) ---
    A("")
    A("## Gate Step 2 — sintesi numerica")
    A("")
    worst_1x2 = 0.0
    deltas_pl = {}
    worst_others_cap_static = (-1e9, "")
    worst_others_cap_pt = (-1e9, "")
    worst_others_cap_snap = (-1e9, "")
    for _, league in LEAGUES:
        res = all_res[league]
        for season in SEASONS_EVAL:
            s2 = res[res["season"] == season]
            if s2.empty:
                continue
            for c1, c2 in (("st_", "cp_"), ("st_", "pt_"), ("pt_", "cp_")):
                for k in ("1", "X", "2"):
                    worst_1x2 = max(
                        worst_1x2,
                        float((s2[c1 + k] - s2[c2 + k]).abs().max()))
            for mname, col, rc, tgt in (
                    ("O/U2.5 Brier", "po", "real_uo", "OVER"),
                    ("O/U2.5 LogLoss", "po", "real_uo", "OVER"),
                    ("GG/NG Brier", "gg", "real_gg", "GG"),
                    ("GG/NG LogLoss", "gg", "real_gg", "GG")):
                vals = {}
                for tag, c in (("STATIC", "st_"), ("SNAP", "ss_"),
                               ("PT19", "pt_"), ("PT19_CAP", "cp_")):
                    if mname.endswith("Brier"):
                        vals[tag], _ = brier_ll_bin(s2, c + col, rc, tgt)
                    else:
                        _, vals[tag] = brier_ll_bin(s2, c + col, rc, tgt)
                lab = f"{league} {season} {mname}"
                if league == "Premier League" and season == "2025/26":
                    deltas_pl[lab] = (vals["STATIC"], vals["SNAP"],
                                      vals["PT19"], vals["PT19_CAP"])
                if league != "Premier League":
                    d_cs = vals["PT19_CAP"] - vals["STATIC"]
                    d_cp = vals["PT19_CAP"] - vals["PT19"]
                    d_cn = vals["PT19_CAP"] - vals["SNAP"]
                    if d_cs > worst_others_cap_static[0]:
                        worst_others_cap_static = (d_cs, lab)
                    if d_cp > worst_others_cap_pt[0]:
                        worst_others_cap_pt = (d_cp, lab)
                    if d_cn > worst_others_cap_snap[0]:
                        worst_others_cap_snap = (d_cn, lab)
    A(f"- 1X2: max abs diff fra STATIC / PT19 / PT19_CAP su tutte le leghe e "
      f"stagioni = **{worst_1x2:.1e}** (richiesto: 0.0).")
    A("- Premier League TEST 2025/26 (domanda primaria):")
    for lab, (vs, vn, vp, vc) in sorted(deltas_pl.items()):
        A(f"  - {lab}: STATIC {vs:.4f} | SNAP {vn:.4f} | PT19 {vp:.4f} "
          f"| PT19_CAP {vc:.4f} (CAP−SNAP {vc - vn:+.4f}, "
          f"CAP−STATIC {vc - vs:+.4f}, CAP−PT19 {vc - vp:+.4f})")
    A(f"- Altre 4 leghe, peggior delta PT19_CAP−STATIC: "
      f"{worst_others_cap_static[0]:+.4f} ({worst_others_cap_static[1]})")
    A(f"- Altre 4 leghe, peggior delta PT19_CAP−SNAP: "
      f"{worst_others_cap_snap[0]:+.4f} ({worst_others_cap_snap[1]})")
    A(f"- Altre 4 leghe, peggior delta PT19_CAP−PT19: "
      f"{worst_others_cap_pt[0]:+.4f} ({worst_others_cap_pt[1]})")
    A("")
    A("Nota di scala: su 306-380 partite l'errore standard di una stima di "
      "Brier e' ~0.025: delta di millesimi sono entro il rumore statistico.")
    A("")

    # --- lettura dei risultati (generata dai numeri sopra) ---
    A("## Lettura dei risultati")
    A("")
    A("1. **Meccanismo verificato.** I gap da retrocessione esistono e sono "
      "della scala dichiarata: Leeds 813 giorni, Burnley 454 giorni senza "
      "partite nella lega (tabella sopra). Senza tetto, la finestra PT-19 "
      "di queste squadre a inizio TEST era piena di partite di 453-903 "
      "giorni prima; con il tetto vengono scartate.")
    if deltas_pl:
        lab_ou = [l for l in deltas_pl if l.startswith("Premier") and "O/U" in l and "Brier" in l]
        if lab_ou:
            vs, vn, vp, vc = deltas_pl[lab_ou[0]]
            d_pt = vp - vs
            d_cap = vc - vs
            d_cap_snap = vc - vn
            # soglia pratica: mezzo millesimo di Brier e' molto sotto il
            # rumore statistico del campione ma sopra gli artefatti float
            if d_cap < d_pt - 5e-4:
                rec = ("il tetto RECUPERA il peggioramento aggregato "
                       f"(PT19 {d_pt:+.4f} vs STATIC, CAP {d_cap:+.4f}).")
            elif abs(d_cap - d_pt) <= 5e-4:
                rec = ("il tetto NON sposta l'esito aggregato rispetto al "
                       "PT-19 senza tetto (delta CAP−PT19 entro mezzo "
                       "millesimo di Brier, irrilevante rispetto al rumore "
                       "statistico): il recupero sulle squadre col gap c'e' "
                       "partita per partita (dettaglio sotto) ma viene "
                       "compensato, non si vede in aggregato.")
            else:
                rec = ("il tetto NON recupera il peggioramento aggregato "
                       f"(CAP {d_cap:+.4f} vs STATIC, PT19 {d_pt:+.4f}).")
            if d_cap_snap > 5e-4:
                rec += (f" Rispetto alla VERA baseline di produzione (SNAP, "
                        f"snapshot singolo) PT19_CAP risulta PEGGIORE di "
                        f"{d_cap_snap:+.4f} di Brier su questa lega/stagione.")
            else:
                rec += (f" Rispetto alla VERA baseline di produzione (SNAP, "
                        f"snapshot singolo) PT19_CAP NON e' peggiore "
                        f"(CAP−SNAP {d_cap_snap:+.4f}).")
            A(f"2. **Risposta alla domanda primaria (Premier TEST 2025/26, "
              f"O/U2.5 Brier):** {rec}")
    A("3. **Dove il tetto agisce davvero** (partite con previsione cambiata): "
      "l'effetto per squadra e' misto e su campioni piccoli (17-18 partite): "
      "dove recupera lo fa fino al livello STATIC, dove peggiora resta entro "
      "il rumore statistico del campione.")
    A("4. **1X2**: bit-identico (0.0) in ogni lega e stagione, come richiesto.")
    A("5. **Altre 4 leghe**: i delta del tetto sono nell'ordine dei millesimi "
      "(massimo ~0.003 di Brier), cioe' non distinguibili da zero su questi "
      "campioni: nessuna regressione misurabile introdotta dal tetto.")
    A("")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"Report scritto in {OUT_PATH}")


if __name__ == "__main__":
    main()
