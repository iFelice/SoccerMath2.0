#!/usr/bin/env python3
"""Analisi preregistrata della seconda sonda totals — offline, un solo snapshot.

Non interroga alcuna API. Per default cerca uno snapshot nuovo sotto
``audit/data/totals_probe/`` e ignora esplicitamente quello storico
``2026-10-10_1703``. Senza uno snapshot nuovo stampa «seconda sonda non eseguita»
e non produce risultati numerici né un referto.

Con uno snapshot nuovo, le quote 1X2 Pinnacle sono abbinate per event id da
``SoccerMath/database/live_odds.json``; il timestamp di quella fonte viene
riportato nel referto. Linee multiple nello stesso bookmaker: si usa la linea
valida più bassa, coerentemente con le analisi storiche.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)

from griglia_core import dc_matrix, devig_prop, fit_implicit_line, grid_line_prob  # noqa: E402

DATA_ROOT = os.path.join(_AUDIT_DIR, "data", "totals_probe")
BASELINE_SNAPSHOT_NAME = "2026-10-10_1703"
BASELINE_SNAPSHOT_DIR = os.path.join(DATA_ROOT, BASELINE_SNAPSHOT_NAME)
BASELINE_FETCHED_AT = datetime(2026, 10, 10, 17, 3, 43, tzinfo=timezone.utc)
LIVE_ODDS = os.path.join(_REPO, "SoccerMath", "database", "live_odds.json")
REPORT = os.path.join(_AUDIT_DIR, "results", "totals_probe_seconda_analisi.md")
PINNACLE = "pinnacle"
WINDOW = timedelta(days=7)
MIN_COVERAGE = 0.85
MIN_COMPARABLE = 20
MAX_MEDIAN_PP = 1.5
MAX_P90_PP = 3.0

RULE_TEXT = """# Seconda sonda totals — analisi offline

## Regola preregistrata (prima dei risultati)

Si considerano solo gli eventi NON INIZIATI con calcio d'inizio entro 7 giorni
dopo la chiamata: un evento con `commence_time` ≤ istante della chiamata è già
iniziato (come nella produzione delle quote 1X2) e viene escluso e contato a
parte. La regola (a)(b)(c) si applica solo agli eventi non iniziati.

- **(a) Copertura:** passa se almeno l'85% degli eventi ha una linea totals utilizzabile: Pinnacle con qualunque linea oppure almeno 3 bookmaker con la linea 2,5.
- **(b) Concordanza:** sugli eventi con Pinnacle su una linea diversa da 2,5 e almeno 3 altri bookmaker con la 2,5, si confrontano le due griglie. Passa se la mediana della differenza assoluta su P(Over 2,5) è ≤ 1,5 punti percentuali e il 90° percentile è ≤ 3 punti, con almeno 20 eventi confrontabili. Con meno di 20 eventi l'esito è «non decidibile».
- **(c) Proposta:** totals con fit generalizzato è proponibile per la produzione solo se (a) e (b) passano entrambe.

La regola non si applica allo snapshot del 10/10. Le differenze sono assolute; il 90° percentile usa il quantile lineare di NumPy. La linea di un bookmaker, se multipla, è la più bassa linea valida. Il fit usa la terna 1X2 Pinnacle de-vigata proporzionalmente e, per la griglia di consenso, la mediana delle probabilità 2,5 degli altri bookmaker de-vigate proporzionalmente.
"""


def parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_valid_price(value: Any) -> bool:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(price) and price > 1.0


def _line_key(point: Any) -> float | None:
    try:
        line = float(point)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(line) or line <= 0 or abs(line * 4 - round(line * 4)) > 1e-8:
        return None
    return line


def extract_book_lines(event: dict) -> dict[str, dict[float, dict[str, Any]]]:
    """Ritorna bookmaker -> linea -> prezzi Over/Under e last_update.

    Una linea è utilizzabile solo se entrambe le quote sono finite e > 1.
    """
    out: dict[str, dict[float, dict[str, Any]]] = {}
    for bookmaker in event.get("bookmakers") or []:
        key = bookmaker.get("key")
        if not key:
            continue
        for market in bookmaker.get("markets") or []:
            if market.get("key") != "totals":
                continue
            by_line: dict[float, dict[str, Any]] = {}
            for outcome in market.get("outcomes") or []:
                name = outcome.get("name")
                line = _line_key(outcome.get("point"))
                if name not in ("Over", "Under") or line is None:
                    continue
                by_line.setdefault(line, {})[name] = outcome.get("price")
            valid = {line: {"Over": pair.get("Over"), "Under": pair.get("Under"),
                            "last_update": bookmaker.get("last_update")}
                     for line, pair in by_line.items()
                     if _is_valid_price(pair.get("Over")) and _is_valid_price(pair.get("Under"))}
            if valid:
                out.setdefault(key, {}).update(valid)
    return out


def load_snapshot(snapshot_dir: str) -> tuple[list[dict], datetime | None]:
    """Carica un singolo snapshot, mai una fusione di run diversi."""
    events: list[dict] = []
    call_times: list[datetime] = []
    for path in sorted(glob.glob(os.path.join(snapshot_dir, "*.json"))):
        if os.path.basename(path).startswith("_"):
            continue
        with open(path, encoding="utf-8") as fh:
            env = json.load(fh)
        fetched = parse_utc(env.get("fetched_at_utc"))
        if fetched:
            call_times.append(fetched)
        for raw in env.get("body") or []:
            commence = parse_utc(raw.get("commence_time"))
            events.append({
                "id": raw.get("id"), "league": env.get("lega"),
                "home": raw.get("home_team"), "away": raw.get("away_team"),
                "commence_time": commence, "fetched_at": fetched,
                "book_lines": extract_book_lines(raw),
            })
    # Ogni evento conserva il timestamp della sua specifica chiamata/lega.
    return events, (max(call_times) if call_times else None)


def load_pinnacle_1x2(path: str = LIVE_ODDS) -> tuple[dict[str, tuple[float, float, float]], str | None]:
    """Event id -> quote raw casa/pareggio/trasferta del libro Pinnacle."""
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    out: dict[str, tuple[float, float, float]] = {}
    for league in (payload.get("leghe") or {}).values():
        for event in league.get("eventi") or []:
            for book in event.get("libri") or []:
                h2h = book.get("h2h") or {}
                if book.get("key") != PINNACLE or not all(
                        _is_valid_price(h2h.get(k)) for k in ("home", "draw", "away")):
                    continue
                out[event.get("id")] = tuple(float(h2h[k]) for k in ("home", "draw", "away"))
    return out, payload.get("generato_il")


def in_window(event: dict) -> bool:
    """Solo eventi NON iniziati e entro 7 giorni dalla chiamata.

    Come nella produzione delle quote 1X2 (``update_live_odds.normalizza_eventi``):
    un evento con ``commence_time`` ≤ istante della chiamata è già iniziato e non
    entra nella regola (a)(b)(c). ``commence_time`` assente/corrotto non è
    classificabile e resta fuori dalla finestra.
    """
    kickoff = event.get("commence_time")
    fetched = event.get("fetched_at")
    if not isinstance(kickoff, datetime) or not isinstance(fetched, datetime):
        return False
    delta = kickoff - fetched
    return timedelta(0) < delta <= WINDOW


def eventi_iniziati(events: list[dict]) -> list[dict]:
    """Eventi già iniziati all'istante della chiamata (commence_time ≤ fetched_at).

    Stessa regola della produzione 1X2: kickoff ≤ istante di acquisizione;
    ``commence_time`` assente o corrotto NON viene classificato come iniziato.
    """
    out = []
    for event in events:
        kickoff = event.get("commence_time")
        fetched = event.get("fetched_at")
        if isinstance(kickoff, datetime) and isinstance(fetched, datetime) \
                and kickoff <= fetched:
            out.append(event)
    return out


def selected_line(book_lines: dict[float, dict[str, Any]]) -> tuple[float, dict[str, Any]] | None:
    """Linea valida più bassa del bookmaker, per avere una regola deterministica."""
    if not book_lines:
        return None
    line = min(book_lines)
    return line, book_lines[line]


def _has_usable_pinnacle(book_lines: dict[str, dict[float, dict[str, Any]]]) -> bool:
    return bool(book_lines.get(PINNACLE))


def _count_25(book_lines: dict[str, dict[float, dict[str, Any]]], exclude_pin: bool = False) -> int:
    return sum(1 for key, lines in book_lines.items()
               if (not exclude_pin or key != PINNACLE) and any(abs(line - 2.5) < 1e-9 for line in lines))


def fit_comparable_event(event: dict, h2h: dict[str, tuple[float, float, float]]) -> dict | None:
    """Confronta le due griglie dell'evento; None se non è confrontabile/fittabile."""
    eid = event.get("id")
    odds_1x2 = h2h.get(eid)
    if odds_1x2 is None:
        return None
    lines = event["book_lines"]
    pinnacle = selected_line(lines.get(PINNACLE, {}))
    if pinnacle is None:
        return None
    pinnacle_line, pinnacle_prices = pinnacle
    if abs(pinnacle_line - 2.5) < 1e-9:
        return None
    other_25 = []
    for key, bookmaker_lines in lines.items():
        if key == PINNACLE or not any(abs(line - 2.5) < 1e-9 for line in bookmaker_lines):
            continue
        quote = bookmaker_lines[next(line for line in bookmaker_lines if abs(line - 2.5) < 1e-9)]
        p = devig_prop([quote["Over"], quote["Under"]])
        if p is not None:
            other_25.append(float(p[0]))
    if len(other_25) < 3:
        return None
    p1x2 = devig_prop(odds_1x2)
    p_pin = devig_prop([pinnacle_prices["Over"], pinnacle_prices["Under"]])
    if p1x2 is None or p_pin is None:
        return None
    target_consensus = float(np.median(other_25))
    fit_pin = fit_implicit_line(*p1x2, float(p_pin[0]), line=pinnacle_line, side="over", rho_free=True)
    fit_consensus = fit_implicit_line(*p1x2, target_consensus, line=2.5, side="over", rho_free=True)
    fits = (fit_pin, fit_consensus)
    if any(not f.get("converged") or not math.isfinite(f.get("max_abs_resid", float("nan")))
           or f["max_abs_resid"] > 1e-7 for f in fits):
        return None
    p25_pin = grid_line_prob(dc_matrix(fit_pin["lam"], fit_pin["mu"], fit_pin["rho"]), 2.5, "over")
    p25_consensus = grid_line_prob(dc_matrix(fit_consensus["lam"], fit_consensus["mu"],
                                             fit_consensus["rho"]), 2.5, "over")
    return {
        "id": eid, "league": event.get("league"), "home": event.get("home"), "away": event.get("away"),
        "pinnacle_line": pinnacle_line, "n_other_25": len(other_25),
        "p_over25_pin_grid": float(p25_pin), "p_over25_consensus_grid": float(p25_consensus),
        "diff_pp": abs(float(p25_pin) - float(p25_consensus)) * 100.0,
        "fit_pin": fit_pin, "fit_consensus": fit_consensus,
    }


def decision(eligible_events: list[dict], comparisons: list[dict]) -> dict:
    n_window = len(eligible_events)
    n_covered = sum(bool(_has_usable_pinnacle(e["book_lines"]) or _count_25(e["book_lines"]) >= 3)
                    for e in eligible_events)
    coverage = n_covered / n_window if n_window else None
    coverage_pass = coverage is not None and coverage >= MIN_COVERAGE
    diffs = np.asarray([c["diff_pp"] for c in comparisons], dtype=float)
    n_comp = int(diffs.size)
    if n_comp >= MIN_COMPARABLE:
        median = float(np.median(diffs))
        p90 = float(np.percentile(diffs, 90))
        concordance_pass = median <= MAX_MEDIAN_PP and p90 <= MAX_P90_PP
        concordance_status = "PASSA" if concordance_pass else "NON PASSA"
    else:
        median = p90 = None
        concordance_pass = False
        concordance_status = "NON DECIDIBILE"
    return {
        "n_window": n_window, "n_covered": n_covered, "coverage": coverage,
        "coverage_pass": coverage_pass, "n_comparable": n_comp,
        "median_diff_pp": median, "p90_diff_pp": p90,
        "concordance_pass": concordance_pass, "concordance_status": concordance_status,
        "production_proposable": bool(coverage_pass and concordance_pass),
    }


def _fmt(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "n/d"
    return f"{value:.{digits}f}".replace(".", ",")


def build_report(snapshot_dir: str, call_time: str | None, live_time: str | None,
                 stats: dict, comparisons: list[dict], n_missing_1x2: int) -> str:
    lines = [RULE_TEXT.rstrip(), "", "## Snapshot e fonti", "",
             f"- Snapshot analizzato: `{snapshot_dir}` (un solo run).",
             f"- Ultima chiamata totals: `{call_time or 'n/d'}`.",
             f"- Snapshot 1X2 Pinnacle: `{live_time or 'n/d'}`; abbinamento per id evento.",
             f"- Eventi già iniziati alla chiamata (`commence_time` ≤ istante della "
             f"chiamata): **{int(stats.get('n_iniziati_esclusi', 0) or 0)}** — esclusi "
             f"dall'analisi, come nella produzione delle quote 1X2.",
             f"- Eventi entro 7 giorni senza terna 1X2 Pinnacle utilizzabile: {n_missing_1x2}.", "",
             "## Risultati", "",
             "### (a) Copertura", "",
             "| eventi nella finestra | con linea utilizzabile | copertura | soglia | esito |",
             "|---:|---:|---:|---:|---|",
             f"| {stats['n_window']} | {stats['n_covered']} | "
             f"{_fmt(stats['coverage'] * 100 if stats['coverage'] is not None else None)}% | 85% | "
             f"{'PASSA' if stats['coverage_pass'] else ('NON DECIDIBILE' if stats['coverage'] is None else 'NON PASSA')} |",
             "", "### (b) Concordanza", "",
             "| confrontabili | mediana | 90° percentile | soglie | esito |",
             "|---:|---:|---:|---|---|",
             f"| {stats['n_comparable']} | {_fmt(stats['median_diff_pp'])} pt | "
             f"{_fmt(stats['p90_diff_pp'])} pt | ≤1,5 pt / ≤3 pt; n≥20 | {stats['concordance_status']} |",
             "", "### (c) Proponibilità", "",
             f"**{'PROPONIBILE' if stats['production_proposable'] else 'NON PROPONIBILE'}** "
             "(serve il superamento congiunto di (a) e (b)).", "",
             "### Eventi confrontabili", "",
             "| evento | lega | linea Pinnacle | altri libri a 2,5 | P(Over 2,5) griglia Pinnacle | "
             "P(Over 2,5) griglia consenso | differenza assoluta |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for c in comparisons:
        lines.append(f"| {c['home']} – {c['away']} | {c['league']} | {c['pinnacle_line']:g} | "
                     f"{c['n_other_25']} | {_fmt(c['p_over25_pin_grid'] * 100)}% | "
                     f"{_fmt(c['p_over25_consensus_grid'] * 100)}% | {_fmt(c['diff_pp'])} pt |")
    lines.append("")
    return "\n".join(lines)


def discover_new_snapshot(data_root: str = DATA_ROOT) -> str | None:
    """Seleziona il run più recente dopo il baseline 10/10, mai il baseline stesso."""
    root = Path(data_root)
    candidates: list[tuple[datetime, str]] = []
    if not root.is_dir():
        return None
    for folder in root.iterdir():
        if not folder.is_dir() or folder.name == BASELINE_SNAPSHOT_NAME:
            continue
        summary_path = folder / "_summary.json"
        if not summary_path.is_file():
            continue
        try:
            with summary_path.open(encoding="utf-8") as fh:
                summary = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        timestamp = parse_utc(summary.get("generato_il"))
        if timestamp is None:
            timestamp = parse_utc(summary.get("ultima_chiamata", {}).get("fetched_at_utc"))
        if timestamp is None or timestamp <= BASELINE_FETCHED_AT:
            continue
        candidates.append((timestamp, str(folder)))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", default=None,
                    help="cartella di un nuovo snapshot; il baseline 2026-10-10_1703 è sempre escluso")
    ap.add_argument("--live-odds", default=LIVE_ODDS, help="snapshot locale h2h Pinnacle, solo lettura")
    ap.add_argument("--report", default=REPORT, help="percorso del referto Markdown")
    args = ap.parse_args(argv)

    snapshot_dir = args.snapshot or discover_new_snapshot()
    if not snapshot_dir or os.path.abspath(snapshot_dir) == os.path.abspath(BASELINE_SNAPSHOT_DIR):
        print(RULE_TEXT.rstrip())
        print("\nseconda sonda non eseguita")
        return 0

    # Anche un path esplicito deve rappresentare un run successivo al baseline.
    events, _latest_call = load_snapshot(snapshot_dir)
    summary_path = os.path.join(snapshot_dir, "_summary.json")
    try:
        with open(summary_path, encoding="utf-8") as fh:
            summary = json.load(fh)
    except (OSError, json.JSONDecodeError):
        summary = {}
    snapshot_time = parse_utc(summary.get("generato_il")) or parse_utc(
        summary.get("ultima_chiamata", {}).get("fetched_at_utc"))
    if snapshot_time is None or snapshot_time <= BASELINE_FETCHED_AT:
        print(RULE_TEXT.rstrip())
        print("\nseconda sonda non eseguita")
        return 0

    try:
        h2h, live_time = load_pinnacle_1x2(args.live_odds)
    except (OSError, json.JSONDecodeError):
        h2h, live_time = {}, None

    # Solo eventi non iniziati (regola della produzione 1X2): i già iniziati sono
    # esclusi e contati, e la regola (a)(b)(c) non li riguarda.
    iniziati = eventi_iniziati(events)
    eligible = [event for event in events if in_window(event)]
    comparisons = []
    missing_1x2 = 0
    for event in eligible:
        if event.get("id") not in h2h:
            missing_1x2 += 1
        comparison = fit_comparable_event(event, h2h)
        if comparison is not None:
            comparisons.append(comparison)
    stats = decision(eligible, comparisons)
    stats["n_iniziati_esclusi"] = len(iniziati)
    times = [event["fetched_at"] for event in eligible if event.get("fetched_at")]
    call_time = max(times).strftime("%Y-%m-%dT%H:%M:%SZ") if times else None
    text = build_report(snapshot_dir, call_time, live_time, stats, comparisons, missing_1x2)
    report_path = os.path.abspath(args.report)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    print(f"[seconda sonda] referto: {report_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
