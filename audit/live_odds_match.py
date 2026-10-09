#!/usr/bin/env python3
"""live_odds_match.py — Abbinamento dei nomi della fonte dal vivo ai nomi canonici (sola lettura).

DOMANDA (punto 3 della commessa). Quante partite della PROSSIMA GIORNATA delle
5 leghe, prese dalla fonte dal vivo candidata (The Odds API), si abbinano ai
nomi canonici del progetto senza scrivere nuovo codice di normalizzazione?

REGole USATE (nessuna riscrittura):
  * nome canonico = ``team_aliases.clean_name(nome dei CSV football-data)``,
    la stessa funzione usata da ``app.get_league_engine``, ``models/elo_engine.py``
    e ``config.MARKET_VALUES``;
  * l'insieme dei nomi canonici e' costruito dai CSV della stagione in corso
    (``SoccerMath/database/<Lega>_Live.csv``); come sensibilita' si usa
    l'unione con la stagione 2025/26;
  * la PROSSIMA GIORNATA segue la regola di produzione
    (``app.select_next_matchday_matches``): prima partita futura per data di
    gioco effettiva + finestra ``app.TOP_MIX_ROUND_WINDOW_DAYS``. La differenza
    dichiarata: l'API football-data.org fornisce il campo ``matchday``, The Odds
    API no, quindi il filtro "stesso matchday" non puo' essere applicato e si
    usa solo la finestra temporale.

Nessuna modifica a ``SoccerMath/``, nessuna chiamata di rete: legge gli
snapshot committati in ``audit/data/live_odds_probe/``.

Uso: ``python audit/live_odds_match.py``
Output: ``audit/output/live_odds_match.json`` (non versionato).
"""
from __future__ import annotations

import json
import os
import sys
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

from team_aliases import CANONICAL_NAMES, clean_name  # noqa: E402  (foglia, nessuna dipendenza)
from team_names import resolve_team_name  # noqa: E402  (sensibilita')

DB_DIR = os.path.join(_REPO_ROOT, "SoccerMath", "database")
DATA_DIR = os.path.join(_AUDIT_DIR, "data", "live_odds_probe")
OUT_DIR = os.path.join(_AUDIT_DIR, "output")

# prefisso CSV -> (nome lega, sport key The Odds API)
LEAGUES = OrderedDict([
    ("SerieA", ("Serie A", "soccer_italy_serie_a")),
    ("Premier", ("Premier League", "soccer_epl")),
    ("LaLiga", ("La Liga", "soccer_spain_la_liga")),
    ("Bundesliga", ("Bundesliga", "soccer_germany_bundesliga")),
    ("Ligue1", ("Ligue 1", "soccer_france_ligue_one")),
])
# stagione in corso (file _Live) e stagione precedente (sensibilita')
CURRENT_SUFFIX = "Live"
PREV_SUFFIX = "2025"
# finestra di round: stessa costante di produzione (app.TOP_MIX_ROUND_WINDOW_DAYS)
ROUND_WINDOW_DAYS = 5


def load_snapshot(sport_key):
    path = os.path.join(DATA_DIR, f"odds_api_{sport_key}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def canonical_names(prefix, suffixes) -> set:
    """clean_name di HomeTeam/AwayTeam dei CSV indicati (nessun fuzzy matching)."""
    out = set()
    for suf in suffixes:
        path = os.path.join(DB_DIR, f"{prefix}_{suf}.csv")
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path, low_memory=False)
        for col in ("HomeTeam", "AwayTeam"):
            if col in df.columns:
                out |= {clean_name(v) for v in df[col].dropna().astype(str)}
    return {n for n in out if n}


def next_matchday(events, now):
    """Regola di produzione senza il campo matchday (la fonte non lo fornisce)."""
    fut = []
    for e in events:
        ts = e.get("commence_time")
        if not ts:
            continue
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt > now:
            fut.append((dt, e))
    if not fut:
        return [], None, None
    fut.sort(key=lambda t: t[0])
    first = fut[0][0]
    window_end = first + timedelta(days=ROUND_WINDOW_DAYS)
    return [e for dt, e in fut if dt <= window_end], first, window_end


def match_names(events, canon):
    """Per ogni evento: esito dell'abbinamento di casa e trasferta.

    Due misure, entrambe senza fuzzy matching:
      * ``clean_name`` (quello chiesto dalla commessa): il nome e' abbinato se
        ``clean_name(raw)`` e' un nome canonico della stagione in corso;
      * ``resolve_team_name`` (sensibilita'): il resolver di produzione usa
        TUTTE le tabelle di alias (API + Understat) e non solo TEAM_NAME_MAP.
    """
    rows = []
    for e in events:
        rec = {"id": e.get("id"), "commence_time": e.get("commence_time"),
               "home_raw": e.get("home_team"), "away_raw": e.get("away_team"),
               "home_clean": None, "away_clean": None,
               "home_ok": False, "away_ok": False,
               "home_resolver_source": None, "away_resolver_source": None,
               "home_resolver_canonical": None, "away_resolver_canonical": None,
               "home_resolver_ok": False, "away_resolver_ok": False}
        for ruolo in ("home", "away"):
            raw = e.get(f"{ruolo}_team")
            c = clean_name(raw)
            res = resolve_team_name(raw)
            rec[f"{ruolo}_clean"] = c
            rec[f"{ruolo}_ok"] = c in canon
            rec[f"{ruolo}_resolver_source"] = res.source
            rec[f"{ruolo}_resolver_canonical"] = res.canonical
            # riconosciuto dal resolver E il nome canonico e' in stagione
            rec[f"{ruolo}_resolver_ok"] = bool(res.mapped and res.canonical in canon)
        rec["match_ok"] = bool(rec["home_ok"] and rec["away_ok"])
        rec["match_ok_resolver"] = bool(rec["home_resolver_ok"] and rec["away_resolver_ok"])
        rows.append(rec)
    return rows


def nomi_non_abbinati(per_league):
    """Elenco dei NOMI (unici) non abbinati da clean_name, con l'esito del resolver."""
    out = {}
    for lega, v in per_league.items():
        for r in v.get("righe", []):
            for ruolo in ("home", "away"):
                if r[f"{ruolo}_ok"]:
                    continue
                raw = r[f"{ruolo}_raw"]
                key = (lega, raw)
                if key in out:
                    out[key]["n_volte"] += 1
                    continue
                out[key] = {"lega": lega, "raw": raw, "clean": r[f"{ruolo}_clean"],
                            "resolver_source": r[f"{ruolo}_resolver_source"],
                            "resolver_canonical": r[f"{ruolo}_resolver_canonical"],
                            "risolto_dal_resolver": bool(r[f"{ruolo}_resolver_ok"]),
                            "n_volte": 1}
    return sorted(out.values(), key=lambda x: (x["lega"], x["raw"]))


def build_payload(snapshot_now=None):
    """snapshot_now: istante di riferimento (default: quello dello snapshot)."""
    summary_path = os.path.join(DATA_DIR, "probe_summary.json")
    summary = None
    if os.path.exists(summary_path):
        with open(summary_path, encoding="utf-8") as fh:
            summary = json.load(fh)

    if snapshot_now is None:
        # istante dello snapshot: le partite "future" sono future rispetto ad allora.
        # Le chiamate in probe_summary.json usano la chiave "fetched_at_utc"
        # (i singoli file per lega usano "scaricato_il"): si accettano entrambe,
        # in modo che il risultato non dipenda dall'ora in cui si riesegue.
        times = []
        for c in (summary or {}).get("calls", []):
            for k in ("fetched_at_utc", "scaricato_il"):
                v = c.get(k)
                if v:
                    times.append(v)
                    break
        if not times and (summary or {}).get("generato_il"):
            times = [summary["generato_il"]]
        snapshot_now = (datetime.fromisoformat(max(times).replace("Z", "+00:00"))
                        if times else datetime.now(timezone.utc))
    if snapshot_now.tzinfo is None:
        snapshot_now = snapshot_now.replace(tzinfo=timezone.utc)

    per_league = {}
    unmatched_all = []
    for prefix, (lega, skey) in LEAGUES.items():
        snap = load_snapshot(skey)
        if snap is None:
            per_league[lega] = {"disponibile": False, "motivo": "snapshot mancante"}
            continue
        canon = canonical_names(prefix, [CURRENT_SUFFIX])
        canon_prev = canonical_names(prefix, [CURRENT_SUFFIX, PREV_SUFFIX])
        events = snap.get("events") or []
        nd, first, window_end = next_matchday(events, snapshot_now)
        rows = match_names(nd, canon)
        sens = {r["id"]: r for r in match_names(nd, canon_prev)}
        for r in rows:
            s = sens.get(r["id"], {})
            r["match_ok_con_precedente"] = bool(s.get("match_ok", False))
            if not r["match_ok"]:
                unmatched_all.append({"lega": lega, "id": r["id"],
                                      "commence_time": r["commence_time"],
                                      "home_raw": r["home_raw"], "home_clean": r["home_clean"],
                                      "away_raw": r["away_raw"], "away_clean": r["away_clean"],
                                      "home_resolver_source": r["home_resolver_source"],
                                      "away_resolver_source": r["away_resolver_source"],
                                      "match_ok_con_precedente": r["match_ok_con_precedente"]})
        n = len(rows)
        ok = sum(1 for r in rows if r["match_ok"])
        ok_prev = sum(1 for r in rows if r["match_ok_con_precedente"])
        ok_res = sum(1 for r in rows if r["match_ok_resolver"])
        per_league[lega] = {
            "disponibile": True,
            "sport_key": skey,
            "snapshot_scaricato_il": snap.get("scaricato_il"),
            "n_eventi_snapshot": snap.get("n_eventi"),
            "n_canonici_stagione_corrente": len(canon),
            "n_canonici_con_precedente": len(canon_prev),
            "n_canonici_tabella_alias": len(CANONICAL_NAMES),
            "primo_kickoff": first.isoformat() if first else None,
            "fine_finestra": window_end.isoformat() if window_end else None,
            "n_prossima_giornata": n,
            "n_abbinate": ok,
            "pct_abbinate": (ok / n) if n else None,
            "pct_abbinate_con_precedente": (ok_prev / n) if n else None,
            "n_abbinate_resolver": ok_res,
            "pct_abbinate_resolver": (ok_res / n) if n else None,
            "righe": rows,
        }

    tot_n = sum(v["n_prossima_giornata"] for v in per_league.values() if v.get("disponibile"))
    tot_ok = sum(v["n_abbinate"] for v in per_league.values() if v.get("disponibile"))
    tot_ok_prev = sum(v.get("pct_abbinate_con_precedente", 0) * v["n_prossima_giornata"]
                      for v in per_league.values() if v.get("disponibile"))
    tot_ok_res = sum(v["n_abbinate_resolver"] for v in per_league.values() if v.get("disponibile"))
    payload = {
        "generato_il": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "istante_di_riferimento": snapshot_now.isoformat(),
        "finestra_round_giorni": ROUND_WINDOW_DAYS,
        "snapshot_odds_api": (summary or {}).get("generato_il"),
        "per_lega": per_league,
        "totale": {"n_prossima_giornata": tot_n, "n_abbinate": tot_ok,
                   "pct_abbinate": (tot_ok / tot_n) if tot_n else None,
                   "pct_abbinate_con_precedente": (tot_ok_prev / tot_n) if tot_n else None,
                   "n_abbinate_resolver": tot_ok_res,
                   "pct_abbinate_resolver": (tot_ok_res / tot_n) if tot_n else None},
        "non_abbinati": unmatched_all,
        "nomi_non_abbinati": nomi_non_abbinati(per_league),
        "limiti": [
            "L'insieme canonico primario e' quello della stagione in corso (file _Live.csv): "
            "una squadra promossa nella stagione in corso e' inclusa solo se gia' presente.",
            "The Odds API non fornisce il campo 'matchday': la prossima giornata e' la "
            "finestra temporale di produzione (primo kickoff futuro + %d giorni), non il "
            "filtro sul numero di giornata usato da app.select_next_matchday_matches."
            % ROUND_WINDOW_DAYS,
            "Nessun fuzzy matching: un nome fuori tabella NON viene indovinato (come in "
            "produzione, dove un nome sconosciuto blocca la riga).",
        ],
    }
    return payload


def main(argv=None):
    payload = build_payload()
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "live_odds_match.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    print(f"istante di riferimento: {payload['istante_di_riferimento']}")
    print(f"{'Lega':16s} {'partite':>8s} {'clean':>7s} {'%':>7s} {'resolver':>9s} {'%':>7s} {'% (con 2025/26)':>16s}")
    for lega, v in payload["per_lega"].items():
        if not v.get("disponibile"):
            print(f"{lega:16s} {'—':>8s} snapshot mancante")
            continue
        print(f"{lega:16s} {v['n_prossima_giornata']:8d} {v['n_abbinate']:7d} "
              f"{100 * v['pct_abbinate']:6.1f}% {v['n_abbinate_resolver']:9d} "
              f"{100 * v['pct_abbinate_resolver']:6.1f}% "
              f"{100 * v['pct_abbinate_con_precedente']:15.1f}%")
    t = payload["totale"]
    print(f"{'TOTALE':16s} {t['n_prossima_giornata']:8d} {t['n_abbinate']:7d} "
          f"{100 * t['pct_abbinate']:6.1f}% {t['n_abbinate_resolver']:9d} "
          f"{100 * t['pct_abbinate_resolver']:6.1f}% "
          f"{100 * t['pct_abbinate_con_precedente']:15.1f}%")
    print("\nNomi NON abbinati da clean_name (unici):")
    for u in payload["nomi_non_abbinati"]:
        print(f"  {u['lega']:14s} {u['raw']:36s} -> {u['clean']:36s} "
              f"resolver: {u['resolver_source']:9s} {u['resolver_canonical'] or '—'}"
              f"{'  [risolto]' if u['risolto_dal_resolver'] else ''}")
    if payload["non_abbinati"]:
        print("\nPartite NON abbinate (entrambi i nomi richiesti):")
        for u in payload["non_abbinati"]:
            print(f"  {u['lega']}: {u['home_raw']} -> {u['home_clean']} "
                  f"({u['home_resolver_source']}) | "
                  f"{u['away_raw']} -> {u['away_clean']} ({u['away_resolver_source']})")
    else:
        print("\nNomi NON abbinati: nessuno")
    print(f"\njson: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
