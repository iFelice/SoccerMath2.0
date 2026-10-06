#!/usr/bin/env python3
"""Fattibilita' della feature squalifiche (sola lettura).

Questo script non scarica fonti nuove, non modifica ``SoccerMath/`` e non usa
componenti di modello. Produce un report riproducibile partendo solo dai file
presenti nel checkout: inventario delle fonti, copertura delle sorgenti
committate, e stato di verificabilita' dei conteggi/validazione/potenza.

Se in futuro i file ``player_match_<lega>.json`` verranno versionati o forniti in
una cartella locale, lo script li rilevera' come fonte disponibile; in questo
intervento non li acquisisce e non prova a ricostruirli dalla rete.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = REPO_ROOT / "audit" / "results"
DEFAULT_OUTPUT = REPO_ROOT / "audit" / "output"
DEFAULT_DATABASE = REPO_ROOT / "SoccerMath" / "database"

ANALYSIS_SEASONS = [2023, 2024, 2025]
ACCUMULATION_BURNIN_SEASON = 2022
ALL_SEASONS = [2022, 2023, 2024, 2025]


@dataclass(frozen=True)
class LeagueConfig:
    name: str
    csv_stem: str
    xg_archive: str
    player_match_file: str
    ppda_file: str
    btts_slug: str


LEAGUES: Sequence[LeagueConfig] = (
    LeagueConfig(
        "Serie A",
        "SerieA",
        "xG archivio serie A.json",
        "player_match_serie_a.json",
        "ppda_deep_serie_a.json",
        "italy-serie-a",
    ),
    LeagueConfig(
        "Premier League",
        "Premier",
        "xG archivio premier league.json",
        "player_match_premier_league.json",
        "ppda_deep_premier_league.json",
        "england-premier-league",
    ),
    LeagueConfig(
        "La Liga",
        "LaLiga",
        "xG archivio la liga.json",
        "player_match_la_liga.json",
        "ppda_deep_la_liga.json",
        "spain-laliga",
    ),
    LeagueConfig(
        "Bundesliga",
        "Bundesliga",
        "xG archivio bundesliga.json",
        "player_match_bundesliga.json",
        "ppda_deep_bundesliga.json",
        "germany-bundesliga",
    ),
    LeagueConfig(
        "Ligue 1",
        "Ligue1",
        "xG archivio ligue 1.json",
        "player_match_ligue_1.json",
        "ppda_deep_ligue_1.json",
        "france-ligue-1",
    ),
)

INVENTORY_PATHS = [
    "audit/results/assenze_certe_valore_feasibility.md",
    "audit/results/assenze_formazioni_probabili_feasibility.md",
    "audit/results/assenze_formazioni_soccerdata_zero_cost_verification.md",
    "audit/results/ppda_deep_player_feasibility.md",
    "audit/results/ppda_deep_player_feasibility.json",
    "audit/ppda_deep_player_audit.py",
    "audit/whoscored_missing_players_sample.py",
    "update_all_ppda_player_db.py",
    ".github/workflows/ppda_player_verify.yml",
    ".github/workflows/whoscored_missing_sample.yml",
]

SUSPENSION_RULES = {
    "Serie A": (
        "accumulo progressivo 5, poi 4,4,3,2, poi ogni ammonizione; "
        "coppe separate; le ammonizioni inefficaci restano fino a fine stagione "
        "o trasferimento in altra Lega"
    ),
    "Premier League": (
        "5 gialli entro la 19a partita di campionato della squadra -> 1 turno; "
        "10 entro la 32a -> 2 turni; 15 in stagione -> 3 turni; gialli per "
        "competizione, rossi domestici cross-competition"
    ),
    "La Liga": (
        "5 gialli nella stessa stagione/competizione -> 1 turno, cicli da 5; "
        "doppia ammonizione non conta per il ciclo; esenzione ultima giornata "
        "post-riforma art. 112.4"
    ),
    "Bundesliga": (
        "5a, 10a, 15a ammonizione -> 1 turno; conteggio per competizione; "
        "reset a fine stagione"
    ),
    "Ligue 1": (
        "fino al 2024/25: 3 ammonizioni in finestra di 10 incontri ufficiali; "
        "dal 2025/26: regola a 5 gialli; coppe nazionali comunicanti, quindi "
        "fonte solo campionato sottocopre"
    ),
}

GROUND_TRUTH_CANDIDATES = {
    "Serie A": "comunicati ufficiali Giudice Sportivo Lega Serie A/FIGC, non presenti come dati nel repo",
    "Premier League": "pagina ufficiale Premier League suspensions/decisioni FA, non presente come dati nel repo",
    "La Liga": "resoluciones del Juez de Competicion RFEF, non presenti come dati nel repo",
    "Bundesliga": "decisioni Sportgericht DFB, non presenti come dati nel repo",
    "Ligue 1": "decisioni Commission de Discipline LFP, non presenti come dati nel repo",
}

AMBIGUITIES = [
    "durata oltre un turno dei rossi diretti: non deducibile dai soli cartellini",
    "rossi da coppe nazionali in Premier League: possono essere scontati in campionato ma non sono nel dataset di campionato",
    "Ligue 1: fino al 2024/25 la finestra mobile comprende coppe nazionali; dal 2025/26 cambia il regime; con dati solo campionato la fonte sottostima vicino alla soglia",
    "La Liga: quinta gialla all'ultima giornata esclusa dalla squalifica successiva post art. 112.4",
    "trasferimenti e cambi lega: possono azzerare o rendere non confrontabile il ciclo secondo regole documentate; serve anagrafica/ground truth per verificarli",
]

REQUIRED_PLAYER_FIELDS = {
    "cartellini per giocatore e partita": ["yellow_cards", "red_cards"],
    "minuti giocati": ["minutes"],
    "titolarita'": ["non disponibile nel player_match Understat; si puo' inferire solo in modo imperfetto da minutes>=~90 o servirebbe lineup"],
    "ruolo": ["position"],
}


def run_git(args: Sequence[str]) -> str:
    try:
        out = subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True, stderr=subprocess.STDOUT)
        return out.strip()
    except subprocess.CalledProcessError as exc:
        return f"ERRORE git {' '.join(args)}: exit={exc.returncode}\n{exc.output.strip()}"


def sha256_short(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "n/d"
    return f"{100.0 * value:.1f}%"


def season_label(year: int) -> str:
    return f"{year}/{str(year + 1)[-2:]}"


def file_meta(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": str(path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path)}
    stat = path.stat()
    return {
        "exists": True,
        "path": str(path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path),
        "bytes": stat.st_size,
        "sha256_16": sha256_short(path),
        "modified_utc": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).isoformat(),
    }


def first_and_head_commit(path: str) -> Dict[str, str]:
    logs = run_git(["log", "--follow", "--format=%H%x09%cI%x09%s", "--", path]).splitlines()
    if not logs or logs == [""]:
        return {"first": "n/d", "head": "n/d"}
    head = logs[0]
    first = logs[-1]
    return {"first": first, "head": head}


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def analyze_csv_sources(database_dir: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    card_cols = ["HY", "AY", "HR", "AR"]
    for league in LEAGUES:
        rows = []
        for season in ALL_SEASONS:
            path = database_dir / f"{league.csv_stem}_{season}.csv"
            item: Dict[str, Any] = {"season": season, "file": str(path.relative_to(REPO_ROOT)), **file_meta(path)}
            if path.exists():
                with path.open(newline="", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    records = list(reader)
                    item["rows"] = len(records)
                    item["columns"] = reader.fieldnames or []
                item["team_card_columns_present"] = all(c in item["columns"] for c in card_cols)
                if records and item["team_card_columns_present"]:
                    item["rows_with_all_team_card_counts"] = sum(
                        1 for r in records if all(str(r.get(c, "")).strip() != "" for c in card_cols)
                    )
                    item["team_card_coverage"] = item["rows_with_all_team_card_counts"] / len(records)
                else:
                    item["rows_with_all_team_card_counts"] = 0
                    item["team_card_coverage"] = None
                item["has_player_cards"] = False
                item["has_minutes"] = False
                item["has_starting_xi"] = False
                item["has_role"] = False
                item["known_gap"] = "solo aggregati squadra (HY/AY/HR/AR), nessun giocatore"
            rows.append(item)
        out[league.name] = rows
    return out


def analyze_xg_archives(database_dir: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for league in LEAGUES:
        path = database_dir / league.xg_archive
        meta = file_meta(path)
        seasons: Dict[str, Any] = {}
        if path.exists():
            data = read_json(path)
            for season in ALL_SEASONS:
                recs = [r for r in data if int(r.get("season", -1)) == season]
                seasons[str(season)] = {
                    "rows": len(recs),
                    "is_result_true": sum(bool(r.get("is_result")) for r in recs),
                    "xg_present": sum(r.get("home_xg") is not None and r.get("away_xg") is not None for r in recs),
                    "has_player_fields": False,
                    "has_cards": False,
                    "has_minutes": False,
                    "has_roles": False,
                }
        out[league.name] = {"file": meta, "seasons": seasons}
    return out


def analyze_btts_sources(audit_data_dir: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for league in LEAGUES:
        rows = []
        for season in ALL_SEASONS:
            y2 = str(season + 1)
            path = audit_data_dir / f"{league.btts_slug}_{season}-{y2}_btts.json"
            item: Dict[str, Any] = {"season": season, **file_meta(path)}
            if path.exists():
                data = read_json(path)
                item["rows"] = len(data) if isinstance(data, list) else None
                dates = []
                scraped = []
                if isinstance(data, list):
                    for rec in data:
                        if isinstance(rec, dict):
                            if rec.get("match_date"):
                                dates.append(rec.get("match_date"))
                            if rec.get("scraped_date"):
                                scraped.append(rec.get("scraped_date"))
                item["match_date_present"] = len(dates)
                item["scraped_date_min"] = min(scraped) if scraped else None
                item["scraped_date_max"] = max(scraped) if scraped else None
                item["has_player_fields"] = False
                item["known_gap"] = "quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo"
            rows.append(item)
        out[league.name] = rows
    return out


def summarize_ppda_report(path: Path) -> Dict[str, Any]:
    meta = file_meta(path)
    out: Dict[str, Any] = {"file": meta, "leagues": {}}
    if not path.exists():
        return out
    data = read_json(path)
    out["generated_at"] = data.get("generated_at")
    out["run_url"] = data.get("run_url")
    for league in LEAGUES:
        entry = (data.get("leagues") or {}).get(league.name) or {}
        files = entry.get("files") or {}
        coverage = entry.get("coverage") or {}
        pm_file = files.get("player_match") or {}
        pm_cov = (coverage.get("player_match") or {}).get("seasons") or {}
        out["leagues"][league.name] = {
            "reported_player_match_file_exists_in_run": pm_file.get("exists"),
            "reported_player_match_bytes": pm_file.get("bytes"),
            "reported_player_match_sha256": pm_file.get("sha256"),
            "reported_seasons": {
                s: {
                    "reference_matches": v.get("reference_matches"),
                    "present_matches": v.get("present_matches"),
                    "rows": v.get("rows"),
                    "coverage": v.get("presence_ratio"),
                }
                for s, v in sorted(pm_cov.items())
                if int(s) in ALL_SEASONS
            },
        }
    return out


def find_player_match_files(search_dirs: Sequence[Path]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for league in LEAGUES:
        matches: List[Dict[str, Any]] = []
        for directory in search_dirs:
            path = directory / league.player_match_file
            if path.exists():
                matches.append(file_meta(path))
        out[league.name] = matches
    return out


def validate_player_match_schema(path: Path) -> Dict[str, Any]:
    """Inspect a local player_match json if present; no reconstruction here."""
    result: Dict[str, Any] = {"path": str(path), "exists": path.exists(), "schema_ok": False}
    if not path.exists():
        return result
    try:
        data = read_json(path)
    except Exception as exc:  # pragma: no cover - diagnostic path
        result["error"] = str(exc)
        return result
    if not isinstance(data, list):
        result["error"] = f"json type {type(data).__name__}, attesa lista"
        return result
    result["rows"] = len(data)
    columns = set()
    for rec in data[:1000]:
        if isinstance(rec, dict):
            columns.update(rec)
    result["sample_columns"] = sorted(columns)
    required = {"season", "id", "date", "team", "opponent", "player_id", "player", "position", "minutes", "yellow_cards", "red_cards"}
    result["missing_required_columns_in_sample"] = sorted(required - columns)
    result["schema_ok"] = not result["missing_required_columns_in_sample"]
    return result


def build_source_availability(
    csv_sources: Dict[str, Any],
    xg_sources: Dict[str, Any],
    btts_sources: Dict[str, Any],
    ppda_report: Dict[str, Any],
    player_files: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Dict[str, Any]]:
    availability: Dict[str, Dict[str, Any]] = {}
    for league in LEAGUES:
        league_avail: Dict[str, Any] = {}
        for season in ALL_SEASONS:
            key = str(season)
            csv_row = next((r for r in csv_sources[league.name] if r.get("season") == season), {})
            btts_row = next((r for r in btts_sources[league.name] if r.get("season") == season), {})
            xg_row = (xg_sources.get(league.name, {}).get("seasons") or {}).get(key, {})
            ppda_row = (
                ppda_report.get("leagues", {})
                .get(league.name, {})
                .get("reported_seasons", {})
                .get(key, {})
            )
            league_avail[key] = {
                "matches_csv": csv_row.get("rows"),
                "team_cards_csv_coverage": csv_row.get("team_card_coverage"),
                "xg_rows": xg_row.get("rows"),
                "xg_present": xg_row.get("xg_present"),
                "btts_rows": btts_row.get("rows"),
                "reported_player_match_rows_in_external_run": ppda_row.get("rows"),
                "reported_player_match_coverage_in_external_run": ppda_row.get("coverage"),
                "local_player_match_file_present": bool(player_files.get(league.name)),
                "player_cards_per_match_available_in_repo": bool(player_files.get(league.name)),
                "red_cards_per_player_available_in_repo": bool(player_files.get(league.name)),
                "minutes_available_in_repo": bool(player_files.get(league.name)),
                "starting_xi_available_in_repo": False,
                "role_available_in_repo": bool(player_files.get(league.name)),
                "known_holes": source_holes_for(league.name, bool(player_files.get(league.name))),
            }
        availability[league.name] = league_avail
    return availability


def source_holes_for(league: str, has_player_match: bool) -> List[str]:
    holes = []
    if not has_player_match:
        holes.append("file player_match_<lega>.json non presente nel checkout: cartellini/minuti/ruolo per giocatore non verificabili")
    holes.append("nessuna ground truth ufficiale versionata nel repo")
    holes.append("football-data CSV contiene solo cartellini aggregati squadra HY/AY/HR/AR")
    holes.append("titolarita' XI non presente nei dati committati")
    if league == "Ligue 1":
        holes.append("coppe nazionali comunicanti non presenti nei dati di campionato: accumuli Ligue 1 sottocoperti")
    if league == "Premier League":
        holes.append("rossi domestici cross-competition non osservabili con sole partite di campionato")
    return holes


def downstream_status(player_files: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    any_player = any(player_files[league.name] for league in LEAGUES)
    if any_player:
        reason = "Sono presenti file player_match locali; questo script ne valida lo schema ma non implementa ancora ricostruzione eventi."
    else:
        reason = (
            "Nessun file player_match_<lega>.json e nessuna ground truth ufficiale nel checkout; "
            "le fonti committate non contengono identita' giocatore per cartellini/minuti/ruoli."
        )
    status = {
        "events_reconstruction": "NON VERIFICABILE" if not any_player else "NON ESEGUITA",
        "events_reason": reason,
        "known_before_kickoff_violations": None,
        "validation_precision_recall": "NON VERIFICABILE",
        "validation_reason": (
            "ground truth ufficiali non presenti nel repo; controllo minimo presenza/assenza richiede player_match della partita saltata"
        ),
        "high_usage_counts": "NON VERIFICABILE",
        "high_usage_reason": "minuti per giocatore nelle ultime 5 partite non disponibili come dati locali verificabili",
        "power_A_1x2": "NON VERIFICABILE",
        "power_B_totals": "NON VERIFICABILE",
        "power_reason": "matrice eventi ad alto utilizzo assente; non e' possibile generare simulazioni appaiate su eventi reali",
        "posterior_prior_ratio_A": None,
        "posterior_prior_ratio_B": None,
        "decision_A": "NO-GO tecnico / NON VERIFICABILE",
        "decision_B": "NO-GO tecnico / NON VERIFICABILE",
    }
    return status


def markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    def cell(v: Any) -> str:
        if v is None:
            return "n/d"
        text = str(v)
        return text.replace("\n", "<br>").replace("|", "\\|")

    lines = ["| " + " | ".join(cell(h) for h in headers) + " |"]
    lines.append("|" + "|".join("---" for _ in headers) + "|")
    for row in rows:
        lines.append("| " + " | ".join(cell(v) for v in row) + " |")
    return "\n".join(lines)


def code_block(text: str) -> str:
    return "```\n" + (text.rstrip() or "(nessun output)") + "\n```"


def rel(path: str | Path) -> str:
    p = Path(path)
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def render_report(summary: Dict[str, Any]) -> str:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    lines: List[str] = []
    add = lines.append

    add("# Fattibilita' feature squalifiche — conteggi, sorgenti, potenza")
    add("")
    add(f"Generato: `{now}` UTC")
    add(f"Commit: `{summary['git']['head']}`")
    add("")
    add("> Perimetro: sola lettura in `audit/`; nessun download di fonti nuove; nessuna modifica a `SoccerMath/`, lambda o rating.")
    add("")

    add("## 0. Prerequisiti e ambiente")
    add("")
    add("Evidenza raccolta dal checkout prima dell'analisi e dallo script:")
    add("")
    prereq_rows = [
        ["branch", summary["git"]["branch"]],
        ["HEAD", summary["git"]["head"]],
        ["repository shallow", summary["git"]["is_shallow"]],
        ["origin/main...HEAD (al momento dello script)", summary["git"]["diff_name_status_origin_main_head"] or "(vuoto)"],
        ["audit/elo_walker_core.py", "presente" if (REPO_ROOT / "audit/elo_walker_core.py").exists() else "MANCANTE"],
        ["requirements-audit.txt", "presente" if (REPO_ROOT / "requirements-audit.txt").exists() else "MANCANTE"],
        ["audit/elo_weight_retune.py", "presente" if (REPO_ROOT / "audit/elo_weight_retune.py").exists() else "MANCANTE"],
        ["audit/results/elo_weight_retune.md", "presente" if (REPO_ROOT / "audit/results/elo_weight_retune.md").exists() else "MANCANTE"],
    ]
    add(markdown_table(["Check", "Output"], prereq_rows))
    add("")
    add("Nota prerequisito `elo_weight_retune`: il run preliminare ha cambiato solo `Generato` e `Commit`; il file e' stato ripristinato e non viene committato. I numeri del report non hanno diff.")
    add("")

    add("## 1. Inventario repo sulle squalifiche e assenze")
    add("")
    inventory_rows = []
    for item in summary["inventory"]:
        meta = item["meta"]
        inventory_rows.append([
            item["path"],
            "si" if meta.get("exists") else "no",
            meta.get("bytes", "n/d"),
            (item["commits"].get("first") or "n/d")[:96],
            (item["commits"].get("head") or "n/d")[:96],
            item["role"],
        ])
    add(markdown_table(["Percorso", "Esiste", "Byte", "Primo commit", "Ultimo commit", "Contenuto utile"], inventory_rows))
    add("")
    add("Regole per lega gia' documentate nel repo (fonte principale: `audit/results/assenze_certe_valore_feasibility.md`):")
    add("")
    add(markdown_table(["Lega", "Regola documentata"], [[k, v] for k, v in SUSPENSION_RULES.items()]))
    add("")
    add("Casi limite / ambigui documentati o necessari da escludere dai conteggi principali:")
    add("")
    for entry in AMBIGUITIES:
        add(f"- {entry}")
    add("")
    add("Ground truth candidate documentate ma non versionate come dati:")
    add("")
    add(markdown_table(["Lega", "Candidate"], [[k, v] for k, v in GROUND_TRUTH_CANDIDATES.items()]))
    add("")

    add("## 1.1 Fonti dati disponibili nel checkout")
    add("")
    add("### CSV football-data (`SoccerMath/database/*_<stagione>.csv`)")
    csv_rows = []
    for league, seasons in summary["csv_sources"].items():
        for item in seasons:
            csv_rows.append([
                league,
                season_label(item["season"]),
                item.get("rows"),
                "si" if item.get("team_card_columns_present") else "no",
                fmt_pct(item.get("team_card_coverage")),
                "no",
                item.get("known_gap"),
            ])
    add(markdown_table(["Lega", "Stagione", "Partite", "HY/AY/HR/AR", "Copertura team-card", "Player-card", "Buco noto"], csv_rows))
    add("")
    add("### Archivi xG Understat committati")
    xg_rows = []
    for league, item in summary["xg_sources"].items():
        for season, vals in (item.get("seasons") or {}).items():
            xg_rows.append([
                league,
                season_label(int(season)),
                vals.get("rows"),
                vals.get("is_result_true"),
                vals.get("xg_present"),
                "no",
                "match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo",
            ])
    add(markdown_table(["Lega", "Stagione", "Righe", "Risultati", "xG presenti", "Player fields", "Buco noto"], xg_rows))
    add("")
    add("### `audit/data/*_btts.json`")
    btts_rows = []
    for league, seasons in summary["btts_sources"].items():
        for item in seasons:
            btts_rows.append([
                league,
                season_label(item["season"]),
                item.get("rows"),
                item.get("match_date_present"),
                item.get("scraped_date_min"),
                item.get("scraped_date_max"),
                item.get("known_gap"),
            ])
    add(markdown_table(["Lega", "Stagione", "Righe", "match_date presenti", "scraped min", "scraped max", "Buco noto"], btts_rows))
    add("")
    add("### Player-match Understat: referto presente, dati assenti nel checkout")
    ppda_rows = []
    for league, vals in summary["ppda_report"].get("leagues", {}).items():
        for season, season_vals in vals.get("reported_seasons", {}).items():
            ppda_rows.append([
                league,
                season_label(int(season)),
                season_vals.get("reference_matches"),
                season_vals.get("present_matches"),
                season_vals.get("rows"),
                fmt_pct(season_vals.get("coverage")),
                "si" if summary["player_match_files"].get(league) else "no",
            ])
    add(markdown_table(["Lega", "Stagione", "Partite referto", "Con righe nel run esterno", "Righe giocatore nel run esterno", "Copertura referto", "File locale"], ppda_rows))
    add("")
    add("Campi necessari dichiarati dal codice `update_all_ppda_player_db.py` / `audit/ppda_deep_player_audit.py`:")
    add("")
    add(markdown_table(["Necessita'", "Campi / stato"], [[k, ", ".join(v)] for k, v in REQUIRED_PLAYER_FIELDS.items()]))
    add("")

    add("## 2. Ricostruzione eventi certi")
    add("")
    ds = summary["downstream_status"]
    add(f"Stato: **{ds['events_reconstruction']}**")
    add("")
    add(f"Motivo verificabile: {ds['events_reason']}")
    add("")
    add("Conteggi eventi certi per lega/stagione: NON VERIFICABILE nel checkout corrente.")
    add("")
    add("Violazioni condizione 'nota prima del kickoff della partita saltata': NON VERIFICABILE (serve data evento giocatore e partita saltata).")
    add("")

    add("## 3. Validazione della sorgente")
    add("")
    validation_rows = []
    for league in [l.name for l in LEAGUES]:
        validation_rows.append([
            league,
            "NON VERIFICABILE",
            "ground truth ufficiale non presente nel repo",
            "NON VERIFICABILE",
            "controllo minimo richiede player_match della partita saltata; file locale assente",
        ])
    add(markdown_table(["Lega", "Precision/Recall", "Motivo", "Violazioni presenza", "Motivo controllo minimo"], validation_rows))
    add("")

    add("## 4. Alto utilizzo")
    add("")
    add("Definizione fissata: giocatore con almeno il 60% dei minuti disponibili nelle ultime 5 partite di campionato della sua squadra prima della partita saltata, usando solo dati precedenti al kickoff. Sensibilita': 40%.")
    add("")
    add("Stato: **NON VERIFICABILE** nel checkout corrente, per assenza dei minuti per giocatore in file locali. Il referto `ppda_deep_player_feasibility` documenta che tali campi erano presenti in un artifact esterno, ma l'artifact non e' versionato nel repo.")
    add("")

    add("## 5. Conteggi richiesti")
    add("")
    count_rows = []
    for league in [l.name for l in LEAGUES]:
        for season in ANALYSIS_SEASONS:
            count_rows.append([
                league,
                season_label(season),
                "NON VERIFICABILE",
                "NON VERIFICABILE",
                "NON VERIFICABILE",
                "NON VERIFICABILE",
                "NON VERIFICABILE",
                "player_match/ground truth assenti",
            ])
    add(markdown_table([
        "Lega", "Stagione", "Partite con squalificato certo", "Partite con alto utilizzo >=60%",
        "Distribuzione ruolo", "Assenze multiple", "Cluster squadre/giocatori", "Motivo"
    ], count_rows))
    add("")

    add("## 6. Potenza statistica")
    add("")
    add("Punti d'iniezione dichiarati:")
    add("- A) 1X2: shock transitorio sul differenziale Elo `d_match = d + Δ_H − Δ_A`, metrica LogLoss 1X2.")
    add("- B) Totali: shock su lambda in scala logaritmica, metrica LogLoss Over/Under 2.5.")
    add("")
    power_rows = [
        ["A", "15 Elo", "NON VERIFICABILE", "NON VERIFICABILE", "matrice eventi alto utilizzo assente"],
        ["A", "30 Elo", "NON VERIFICABILE", "NON VERIFICABILE", "matrice eventi alto utilizzo assente"],
        ["A", "50 Elo", "NON VERIFICABILE", "NON VERIFICABILE", "matrice eventi alto utilizzo assente"],
        ["B", "0.05 log-lambda", "NON VERIFICABILE", "NON VERIFICABILE", "matrice eventi alto utilizzo e ruoli assente"],
        ["B", "0.10 log-lambda", "NON VERIFICABILE", "NON VERIFICABILE", "matrice eventi alto utilizzo e ruoli assente"],
        ["B", "0.15 log-lambda", "NON VERIFICABILE", "NON VERIFICABILE", "matrice eventi alto utilizzo e ruoli assente"],
    ]
    add(markdown_table(["Punto", "δ vero", "Potenza α=5%", "MDE 80%", "Motivo"], power_rows))
    add("")

    add("## 7. Prior e rapporto posterior/prior")
    add("")
    add("Prior fissati: A) δ ~ N(0, 30²) punti Elo; B) δ ~ N(0, 0.10²) log-lambda.")
    add("")
    add(markdown_table(["Punto", "Rapporto sd posterior/prior", "Stato"], [
        ["A", "NON VERIFICABILE", "numero eventi reali ad alto utilizzo non disponibile"],
        ["B", "NON VERIFICABILE", "numero eventi reali ad alto utilizzo e ruoli non disponibile"],
    ]))
    add("")

    add("## 8. Regola di decisione")
    add("")
    add(markdown_table(["Punto", "Regola GO", "Evidenza disponibile", "Verdetto operativo"], [
        ["A 1X2", "MDE 80% <= 30 Elo e posterior/prior <= 0.7", "MDE e rapporto non calcolabili da fonti locali", ds["decision_A"]],
        ["B Totali", "MDE 80% <= 0.10 log-lambda e posterior/prior <= 0.7", "MDE e rapporto non calcolabili da fonti locali", ds["decision_B"]],
    ]))
    add("")
    add("Il verdetto sopra e' operativo per questa PR: non dichiara effetto negativo, dichiara che il campione verificabile dal repo non puo' rispondere.")
    add("")

    add("## 9. Output e riproducibilita'")
    add("")
    add("File prodotti:")
    add("- `audit/squalifiche_feasibility.py` — script sola lettura;")
    add("- `audit/results/squalifiche_feasibility.md` — questo report;")
    add("- `audit/output/squalifiche_feasibility_sources.json` — dettaglio macchina, ignorato da git.")
    add("")
    add("Comando riproducibile:")
    add(code_block("python audit/squalifiche_feasibility.py"))
    add("")
    add("Stato git dopo generazione report (al momento dello script):")
    add(code_block(summary["git"].get("status_short", "")))
    add("")

    add("## Chiusura richiesta")
    add("")
    add("- Inventario fonti: riportato in §1 e §1.1 con percorsi, commit, copertura e buchi.")
    add("- Eventi certi per lega/stagione: NON VERIFICABILE perché manca nel repo la fonte giocatore-partita con cartellini.")
    add("- Validazione sorgente: NON VERIFICABILE perché ground truth ufficiali e player_match locale sono assenti.")
    add("- Conteggi alto utilizzo: NON VERIFICABILE perché mancano minuti per giocatore in file locali.")
    add("- Potenza/MDE A e B: NON VERIFICABILE perché non esiste matrice eventi reali ad alto utilizzo.")
    add("- Rapporto posterior/prior: NON VERIFICABILE perché manca il numero eventi reali.")
    add("- Verdetto: A = NO-GO tecnico / NON VERIFICABILE; B = NO-GO tecnico / NON VERIFICABILE; pista in raccolta prospettica o previo versionamento della fonte player_match/ground truth.")

    return "\n".join(lines) + "\n"


def inventory_role(path: str) -> str:
    roles = {
        "audit/results/assenze_certe_valore_feasibility.md": "regole squalifiche per lega, casi limite, ground truth candidate, limiti Ligue 1/WhoScored",
        "audit/results/assenze_formazioni_probabili_feasibility.md": "ricerca fonti assenze/formazioni e profondita' storica",
        "audit/results/assenze_formazioni_soccerdata_zero_cost_verification.md": "audit sorgente soccerdata 1.9.1: XI storiche e WhoScored missing players",
        "audit/results/ppda_deep_player_feasibility.md": "copertura player_match/PPDA/deep generata da artifact esterno",
        "audit/results/ppda_deep_player_feasibility.json": "dettaglio macchina del referto PPDA/player_match",
        "audit/ppda_deep_player_audit.py": "script audit copertura player_match/PPDA/deep",
        "audit/whoscored_missing_players_sample.py": "campionamento WhoScored missing players, no dati versionati",
        "update_all_ppda_player_db.py": "pipeline acquisizione Understat player_match con cartellini/minuti/ruolo",
        ".github/workflows/ppda_player_verify.yml": "workflow verifica acquisizione player_match come artifact non versionato",
        ".github/workflows/whoscored_missing_sample.yml": "workflow campionamento WhoScored HARD_BLOCK documentato",
    }
    return roles.get(path, "")


def build_summary(args: argparse.Namespace) -> Dict[str, Any]:
    database_dir = Path(args.database_dir).resolve()
    results_dir = Path(args.results_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    audit_data_dir = REPO_ROOT / "audit" / "data"

    inventory = []
    for path in INVENTORY_PATHS:
        p = REPO_ROOT / path
        inventory.append({
            "path": path,
            "meta": file_meta(p),
            "commits": first_and_head_commit(path),
            "role": inventory_role(path),
        })

    csv_sources = analyze_csv_sources(database_dir)
    xg_sources = analyze_xg_archives(database_dir)
    btts_sources = analyze_btts_sources(audit_data_dir)
    ppda_report = summarize_ppda_report(results_dir / "ppda_deep_player_feasibility.json")

    search_dirs = [database_dir, REPO_ROOT / "audit" / "data", output_dir, REPO_ROOT / "database"]
    player_match_files = find_player_match_files(search_dirs)
    player_match_schema = {
        league.name: [validate_player_match_schema(Path(item["path"])) for item in player_match_files.get(league.name, [])]
        for league in LEAGUES
    }

    source_availability = build_source_availability(csv_sources, xg_sources, btts_sources, ppda_report, player_match_files)
    status = downstream_status(player_match_files)

    summary = {
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "git": {
            "branch": run_git(["branch", "--show-current"]),
            "head": run_git(["rev-parse", "HEAD"]),
            "is_shallow": run_git(["rev-parse", "--is-shallow-repository"]),
            "diff_name_status_origin_main_head": run_git(["diff", "--name-status", "origin/main", "HEAD"]),
            "status_short": run_git(["status", "--short"]),
        },
        "inventory": inventory,
        "csv_sources": csv_sources,
        "xg_sources": xg_sources,
        "btts_sources": btts_sources,
        "ppda_report": ppda_report,
        "player_match_files": player_match_files,
        "player_match_schema": player_match_schema,
        "source_availability": source_availability,
        "downstream_status": status,
    }
    return summary


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-dir", default=str(DEFAULT_DATABASE), help="cartella database committata")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS), help="cartella report audit/results")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT), help="cartella output pesanti/non versionati")
    parser.add_argument("--report", default=str(DEFAULT_RESULTS / "squalifiche_feasibility.md"), help="report markdown da scrivere")
    parser.add_argument("--json", default=str(DEFAULT_OUTPUT / "squalifiche_feasibility_sources.json"), help="JSON diagnostico in audit/output")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    summary = build_summary(args)

    json_path = Path(args.json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write("\n")

    report = render_report(summary)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    print(f"scritto {rel(report_path)}")
    print(f"scritto {rel(json_path)} (ignorato da git se audit/output/ e' in .gitignore)")
    print(summary["downstream_status"]["events_reconstruction"] + ": " + summary["downstream_status"]["events_reason"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
