"""
update_db_rich.py — Arricchisce i ``*_Live.csv`` della stagione corrente con le
colonne "ricche" di football-data.co.uk (quote, tiri, tiri in porta, corner,
falli, cartellini, Div, Time), oggi vuote: ``update_db.py`` scrive soltanto le
10 colonne che arrivano dall'API football-data.org (Date, squadre, risultati,
Matchday) e l'header del CSV e' un residuo del concat con il file precedente.

Perche' un modulo separato e perche' cosi'
----------------------------------------
Il merge e' **per colonna**, non per riga: il file esistente e il CSV scaricato
vengono allineati sulla chiave

    (Date normalizzata a datetime, clean_name(HomeTeam), clean_name(AwayTeam))

e, riga per riga, si riempie **solo la cella che oggi e' vuota**.

VIETATO ``pd.concat([vecchio, nuovo])`` + ``drop_duplicates(keep="last")``:
e' esattamente il meccanismo con cui il bug delle colonne vuote si ricreerebbe
da solo. update_db.py (che qui NON si tocca) concatena il frame vecchio con le
righe API (10 colonne, le altre 121 vuote) e tiene l'ultima: al run successivo
le 121 colonne ricche verrebbero riscritte vuote. Con il merge per colonna una
cella gia' valorizzata non viene MAI toccata, quindi la sequenza
update_db_rich -> update_db -> update_db_rich lascia il dato ricco dove non
arriva l'API e lo completa dove arriva (vedi il referto in audit/results/).

Precedenza
----------
* il file attuale vince su ``Matchday`` (football-data.co.uk non ce l'ha) e su
  ``Date/HomeTeam/AwayTeam/FTHG/FTAG/FTR/HTHG/HTAG/HTR`` (chiave o dato
  prodotto da update_db.py dall'API): queste colonne non vengono MAI scritte;
* football-data.co.uk vince sulle restanti 121 colonne (Div, Time, quote,
  tiri, corner, falli, cartellini), ma solo dove il valore attuale e' vuoto.

Nessun set fisso di colonne
---------------------------
Le colonne bookmaker driftano fra stagioni (IW*/VC* nel 22/23, 1XB*/BF* nel
24/25, BFD*/BMGM* nel 25/26, PP*/SKB* nel 26/27): il merge unisce l'UNIONE
delle colonne presenti, senza assumere nessuno schema.

Uso
---
    python SoccerMath/update_db_rich.py                      # download reale
    python SoccerMath/update_db_rich.py --dry-run            # nessuna scrittura
    python SoccerMath/update_db_rich.py --source-dir DIR     # CSV gia' scaricati ({FD_CODE}.csv)
    python SoccerMath/update_db_rich.py --cache-dir DIR      # scarica in DIR e riusa
    python SoccerMath/update_db_rich.py --database-dir DIR   # dove stanno i *_Live.csv
    python SoccerMath/update_db_rich.py --json-out run.json  # referto machine-readable

Exit code: 0 se tutte le leghe sono state processate, 1 se almeno una lega
fallisce download o parse (l'elenco delle leghe fallite e' stampato a video).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd
import requests

# Importare config forza il caricamento del .env (chiavi, override di stagione).
import config  # noqa: F401
from config import CURRENT_SEASON_START_YEAR, DATABASE_DIR, LEAGUES_CONFIG, clean_name

# ==========================================
# Costanti della fonte football-data.co.uk
# ==========================================
FD_BASE_URL = "https://www.football-data.co.uk/mmz4281"
FD_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
# soccerdata legge i CSV grezzi con latin-1 fino alla 23/24 e utf-8-sig da 24/25:
# stesso criterio qui, derivato dall'anno di inizio stagione (2425 -> 2024).
FD_ENCODING_UTF8_FROM = 2024
REQUEST_TIMEOUT = 30

# Colonne che formano la chiave di allineamento fra i due file.
KEY_COLUMNS: Tuple[str, ...] = ("Date", "HomeTeam", "AwayTeam")
# Colonne che il file attuale vince sempre: non vengono MAI scritte da qui.
LOCAL_WINS: Tuple[str, ...] = KEY_COLUMNS + (
    "FTHG", "FTAG", "FTR", "HTHG", "HTAG", "HTR", "Matchday",
)
# Valori considerati "vuoti" in un CSV letto come testo.
BLANK_TOKENS = {"", "nan", "na", "n/a", "none", "null", "<na>"}
# Tolleranza sul giorno (fusi/orari serali: la data API puo' slittare di 1).
DEFAULT_TOLERANCE_DAYS = 1
# Sonde di copertura richieste dalla commessa (quote Bet365 e tiri casa).
COVERAGE_PROBES: Tuple[str, ...] = ("B365H", "HS")
# Colonna che distingue una partita conclusa da una non ancora giocata.
PLAYED_PROBE = "FTHG"

CSV_LINE_TERMINATOR = "\n"   # i *_Live.csv attuali sono LF (i CSV di football-data sono CRLF)
CSV_ENCODING_OUT = "utf-8"   # senza BOM: i *_Live.csv attuali non ce l'hanno


class FetchError(RuntimeError):
    """Download non riuscito (rete, HTTP != 200, file locale assente)."""


class ParseError(RuntimeError):
    """CSV scaricato non leggibile o privo delle colonne chiave."""


# ==========================================
# Stagione ed encoding
# ==========================================
def season_code(start_year: Optional[int] = None) -> str:
    """Chiave stagione football-data.co.uk DERIVATA dall'anno di inizio.

    2026 -> "2627". L'anno non e' mai scritto a mano: arriva da
    ``config.CURRENT_SEASON_START_YEAR`` (che a sua volta legge la data di oggi
    o l'override ``M4_CURRENT_SEASON_START_YEAR``).
    """
    year = CURRENT_SEASON_START_YEAR if start_year is None else int(start_year)
    return f"{year % 100:02d}{(year + 1) % 100:02d}"


def fd_encoding(start_year: Optional[int] = None) -> str:
    """Encoding del CSV: latin-1 fino alla 23/24, UTF-8-SIG da 24/25 in su."""
    year = CURRENT_SEASON_START_YEAR if start_year is None else int(start_year)
    return "utf-8-sig" if year >= FD_ENCODING_UTF8_FROM else "latin-1"


def league_fd_codes() -> Dict[str, str]:
    """Mappa lega -> codice football-data (I1/E0/SP1/D1/F1) da LEAGUES_CONFIG.

    Non esiste un dizionario parallelo in questo modulo: la mappa vive solo in
    ``config.LEAGUES_CONFIG`` (campo ``fd_code``).
    """
    return {name: info.get("fd_code", "") for name, info in LEAGUES_CONFIG.items()}


# ==========================================
# Lettura
# ==========================================
def _is_blank(value) -> bool:
    return value is None or str(value).strip().lower() in BLANK_TOKENS


def _is_nat(value) -> bool:
    return value is pd.NaT or (value is not None and bool(pd.isna(value)))


def read_csv_text(payload, encoding: str) -> pd.DataFrame:
    """Legge un CSV come TESTO (nessuna inferenza di tipo, nessun NaN).

    Leggere tutto come stringa e' la garanzia piu' forte dell'invarianza di
    produzione: il file di output e' il file di input con, in piu', solo le
    celle che prima erano vuote. Nessun 13 -> 13.0, nessun reflow delle date.
    """
    try:
        handle = io.BytesIO(payload) if isinstance(payload, (bytes, bytearray)) else payload
        df = pd.read_csv(
            handle,
            dtype=str,
            keep_default_na=False,
            na_filter=False,
            encoding=encoding,
        )
    except Exception as exc:  # pragma: no cover - dipende dal payload reale
        raise ParseError(f"lettura CSV non riuscita: {exc}") from exc
    missing = [c for c in KEY_COLUMNS if c not in df.columns]
    if missing:
        raise ParseError(f"CSV senza le colonne chiave {missing}")
    if df.empty:
        raise ParseError("CSV senza righe di partite")
    return df


def read_existing_csv(path: str) -> pd.DataFrame:
    """Legge il ``*_Live.csv`` attuale come testo (utf-8, con o senza BOM)."""
    if not os.path.exists(path):
        raise FetchError(f"file assente: {path}")
    return read_csv_text(path, "utf-8-sig")


# ==========================================
# Download
# ==========================================
def fetch_csv_bytes(fd_code: str, season: str, session=None,
                    timeout: int = REQUEST_TIMEOUT) -> bytes:
    """Scarica il CSV grezzo di una lega. Nessun ripiego: o i byte o errore."""
    url = f"{FD_BASE_URL}/{season}/{fd_code}.csv"
    headers = {"User-Agent": FD_USER_AGENT, "Accept": "text/csv,*/*"}
    getter = session.get if session is not None else requests.get
    try:
        resp = getter(url, headers=headers, timeout=timeout)
    except Exception as exc:
        raise FetchError(f"richiesta fallita {url}: {exc}") from exc
    status = getattr(resp, "status_code", None)
    if status is not None and status != 200:
        raise FetchError(f"HTTP {status} su {url}")
    content = getattr(resp, "content", b"")
    if not content:
        raise FetchError(f"risposta vuota su {url}")
    return content


def resolve_source_payload(fd_code: str, season: str, source_dir: Optional[str],
                           cache_dir: Optional[str], refresh: bool,
                           session=None, timeout: int = REQUEST_TIMEOUT
                           ) -> Tuple[bytes, Dict[str, object]]:
    """Ottiene i byte del CSV: da --source-dir, da --cache-dir o dalla rete."""
    meta: Dict[str, object] = {"fd_code": fd_code, "season": season}
    if source_dir:
        path = os.path.join(source_dir, f"{fd_code}.csv")
        if not os.path.exists(path):
            raise FetchError(f"CSV locale assente: {path}")
        with open(path, "rb") as fh:
            payload = fh.read()
        meta.update({"origin": "source-dir", "path": path, "http_status": None,
                     "fetched_at": None})
    elif cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        path = os.path.join(cache_dir, f"{fd_code}_{season}.csv")
        if os.path.exists(path) and not refresh:
            with open(path, "rb") as fh:
                payload = fh.read()
            meta.update({"origin": "cache", "path": path, "http_status": None,
                         "fetched_at": None})
        else:
            payload = fetch_csv_bytes(fd_code, season, session=session, timeout=timeout)
            with open(path, "wb") as fh:
                fh.write(payload)
            meta.update({"origin": "network(cache)", "path": path, "http_status": 200,
                         "fetched_at": _utc_now_iso()})
    else:
        payload = fetch_csv_bytes(fd_code, season, session=session, timeout=timeout)
        meta.update({"origin": "network", "path": None, "http_status": 200,
                     "fetched_at": _utc_now_iso()})
    meta["bytes"] = len(payload)
    meta["sha256"] = hashlib.sha256(payload).hexdigest()
    return payload, meta


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ==========================================
# Merge per colonna
# ==========================================
def build_keys(df: pd.DataFrame) -> List[Tuple[object, str, str]]:
    """Chiave di allineamento: (data normalizzata, clean_name(H), clean_name(A))."""
    dates = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce").dt.normalize()
    homes = df["HomeTeam"].map(clean_name)
    aways = df["AwayTeam"].map(clean_name)
    return list(zip(dates.tolist(), homes.tolist(), aways.tolist()))


def classify_unmatched(key: Tuple[object, str, str],
                       source_teams: set,
                       source_max_date,
                       tolerance_days: int = DEFAULT_TOLERANCE_DAYS) -> str:
    """Motivo per cui una riga del file attuale non trova la sua partita.

    Serve al criterio di copertura: ogni partita non coperta deve avere un
    motivo dichiarato, non un generico "dato mancante".
    """
    date, home, away = key
    missing = sorted({t for t in (home, away) if t not in source_teams})
    if missing:
        return ("nome squadra non allineato: " + ", ".join(missing) +
                " non compare fra i nomi del CSV football-data dopo clean_name()")
    if source_max_date is not None and date is not None and not pd.isna(date) \
            and date > source_max_date:
        return ("partita successiva all'ultimo aggiornamento del CSV "
                f"(ultima data presente: {source_max_date:%d/%m/%Y})")
    return ("partita assente nel CSV football-data "
            f"(chiave data+squadre non trovata, tolleranza +/- {tolerance_days} giorni)")


def merge_columns(existing: pd.DataFrame, source: pd.DataFrame,
                  protected: Sequence[str] = LOCAL_WINS,
                  tolerance_days: int = DEFAULT_TOLERANCE_DAYS,
                  ) -> Tuple[pd.DataFrame, Dict[str, object]]:
    """Allinea ``source`` su ``existing`` e riempie SOLO le celle vuote.

    Ritorna (frame unito, statistiche). Il frame unito ha:
      * lo stesso numero di righe e lo stesso ordine di ``existing``
        (nessuna riga aggiunta, nessuna riga rimossa: le partite presenti solo
        su football-data non entrano nel database);
      * le colonne di ``existing`` nel loro ordine, seguite dalle colonne di
        ``source`` non ancora presenti.
    """
    merged = existing.copy()
    src_keys = build_keys(source)
    dst_keys = build_keys(existing)

    # Indice posizionale delle righe sorgenti. Chiavi duplicate (non dovrebbero
    # esserci: una partita per data/squadre) contate, non risolte a caso.
    buckets: Dict[Tuple[object, str, str], List[int]] = {}
    duplicate_source_keys = 0
    for pos, key in enumerate(src_keys):
        if _is_nat(key[0]):
            continue
        if key in buckets:
            duplicate_source_keys += 1
        buckets.setdefault(key, []).append(pos)

    offsets = [0] + [d for d in range(1, max(0, tolerance_days) + 1) for d in (-d, d)]

    match_pos: List[Optional[int]] = [None] * len(merged)
    match_kind: List[str] = ["unmatched"] * len(merged)
    used_source_rows = set()
    # Una stessa chiave puo' comparire PIU' VOLTE nel file attuale (update_db.py
    # scrive il nome breve dell'API, poi la stessa partita ricompare con il nome
    # canonico: es. "Dortmund-HSV" e "Dortmund-Hamburg", "Alaves" e "Alaves").
    # In quel caso la riga sorgente va RIUSATA, non contesa: sono la stessa
    # partita scritta due volte, e app.py comunque la deduplica al caricamento.
    key_to_source: Dict[Tuple[object, str, str], int] = {}

    # Passaggio 1: data esatta. Passaggio 2: +/- N giorni, stesse squadre.
    for offset in offsets:
        for i, key in enumerate(dst_keys):
            if match_pos[i] is not None:
                continue
            date, home, away = key
            if _is_nat(date) or not home or not away:
                continue
            if key in key_to_source:
                match_pos[i] = key_to_source[key]
                match_kind[i] = "exact" if offset == 0 else f"date{offset:+d}"
                continue
            probe = key if offset == 0 else (date + timedelta(days=offset), home, away)
            for pos in buckets.get(probe, []):
                if pos in used_source_rows:
                    continue
                match_pos[i] = pos
                match_kind[i] = "exact" if offset == 0 else f"date{offset:+d}"
                used_source_rows.add(pos)
                key_to_source[key] = pos
                break

    # Riempimento per colonna: solo celle vuote, mai le colonne protette.
    fillable = [c for c in source.columns if c not in protected]
    new_columns = [c for c in fillable if c not in merged.columns]

    cells_filled = 0
    filled_by_column: Dict[str, int] = {}
    src_cache: Dict[str, List[str]] = {}

    for col in fillable:
        src_values = src_cache.setdefault(col, source[col].tolist())
        current = merged[col].tolist() if col in merged.columns else [""] * len(merged)
        changed = 0
        for i, pos in enumerate(match_pos):
            if pos is None:
                continue
            if not _is_blank(current[i]):
                continue           # <<< il dato gia' presente NON si tocca mai
            new_value = src_values[pos]
            if _is_blank(new_value):
                continue           # un nullo non sovrascrive nulla
            current[i] = new_value
            changed += 1
        merged[col] = current
        if changed:
            filled_by_column[col] = changed
            cells_filled += changed
    # Le nuove colonne nascono vuote per le righe non appaiate: gia' gestito da
    # current = [""] * len(merged) qui sopra.

    source_teams = {home for _, home, _ in src_keys} | {away for _, _, away in src_keys}
    src_dates = [d for d, _, _ in src_keys if not _is_nat(d)]
    source_max_date = max(src_dates) if src_dates else None

    unmatched = []
    for i, kind in enumerate(match_kind):
        if kind != "unmatched":
            continue
        date, home, away = dst_keys[i]
        unmatched.append({
            "row_index": int(i),
            "Date": merged["Date"].iloc[i],
            "HomeTeam": merged["HomeTeam"].iloc[i],
            "AwayTeam": merged["AwayTeam"].iloc[i],
            "HomeClean": home,
            "AwayClean": away,
            "reason": classify_unmatched(dst_keys[i], source_teams, source_max_date,
                                         tolerance_days),
        })

    stats: Dict[str, object] = {
        "rows": len(merged),
        "columns_before": len(existing.columns),
        "columns_after": len(merged.columns),
        "columns_added": new_columns,
        "cells_filled": cells_filled,
        "filled_by_column": filled_by_column,
        "matched_exact": match_kind.count("exact"),
        "matched_tolerance": sum(1 for k in match_kind if k.startswith("date")),
        "unmatched": len(unmatched),
        "unmatched_rows": unmatched,
        "duplicate_source_keys": duplicate_source_keys,
        "source_rows": len(source),
        "source_rows_unused": len(source) - len(used_source_rows),
        "protected_columns_never_written": list(protected),
    }
    return merged, stats


def coverage_report(original: pd.DataFrame, merged: pd.DataFrame,
                    probes: Sequence[str] = COVERAGE_PROBES,
                    played_probe: str = PLAYED_PROBE,
                    reasons: Optional[Dict[int, str]] = None) -> Dict[str, object]:
    """Copertura delle sonde sulle partite gia' concluse (FTHG valorizzato)."""
    played = [not _is_blank(v) for v in original.get(played_probe, pd.Series(dtype=str)).tolist()]
    played_idx = [i for i, ok in enumerate(played) if ok]
    out: Dict[str, object] = {
        "played_matches": len(played_idx),
    }
    for probe in probes:
        if probe not in merged.columns:
            out[probe] = {"covered": 0, "ratio": 0.0, "missing": len(played_idx),
                          "missing_rows": []}
            continue
        values = merged[probe].tolist()
        missing = []
        for i in played_idx:
            if _is_blank(values[i]):
                missing.append({
                    "row_index": int(i),
                    "Date": merged["Date"].iloc[i],
                    "HomeTeam": merged["HomeTeam"].iloc[i],
                    "AwayTeam": merged["AwayTeam"].iloc[i],
                    "HomeClean": clean_name(merged["HomeTeam"].iloc[i]),
                    "AwayClean": clean_name(merged["AwayTeam"].iloc[i]),
                    "reason": (reasons or {}).get(
                        int(i), "colonna non presente nella riga appaiata"),
                })
        covered = len(played_idx) - len(missing)
        out[probe] = {
            "covered": covered,
            "played": len(played_idx),
            "ratio": (covered / len(played_idx)) if played_idx else 0.0,
            "missing": len(missing),
            "missing_rows": missing,
        }
    return out


# ==========================================
# Scrittura atomica
# ==========================================
def atomic_write_csv(path: str, df: pd.DataFrame,
                     line_terminator: str = CSV_LINE_TERMINATOR,
                     encoding: str = CSV_ENCODING_OUT) -> None:
    """Scrive su file temporaneo e poi rinomina: nessun file a meta'."""
    tmp = f"{path}.tmp"
    try:
        df.to_csv(tmp, index=False, lineterminator=line_terminator, encoding=encoding)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:  # pragma: no cover
                pass


# ==========================================
# Singola lega
# ==========================================
def enrich_league(league_name: str, info: Dict[str, object], season: str,
                  database_dir: str = str(DATABASE_DIR),
                  source_dir: Optional[str] = None,
                  cache_dir: Optional[str] = None,
                  refresh: bool = False,
                  session=None,
                  dry_run: bool = False,
                  tolerance_days: int = DEFAULT_TOLERANCE_DAYS,
                  timeout: int = REQUEST_TIMEOUT) -> Dict[str, object]:
    """Arricchisce il ``*_Live.csv`` di una lega. Solleva FetchError/ParseError."""
    fd_code = info.get("fd_code") or ""
    if not fd_code:
        raise FetchError(f"{league_name}: campo 'fd_code' mancante in LEAGUES_CONFIG")
    prefix = info.get("db_prefix") or info.get("short_name") or league_name
    live_path = os.path.join(database_dir, f"{prefix}_Live.csv")

    encoding = fd_encoding()
    payload, source_meta = resolve_source_payload(
        fd_code, season, source_dir=source_dir, cache_dir=cache_dir,
        refresh=refresh, session=session, timeout=timeout)
    source = read_csv_text(payload, encoding)
    source_meta["encoding"] = encoding
    source_meta["rows"] = len(source)
    source_meta["columns"] = list(source.columns)

    if not os.path.exists(live_path):
        raise FetchError(f"{league_name}: {live_path} assente (nessun arricchimento)")

    existing = read_existing_csv(live_path)
    merged, stats = merge_columns(existing, source, tolerance_days=tolerance_days)
    reasons = {row["row_index"]: row["reason"] for row in stats["unmatched_rows"]}
    coverage = coverage_report(existing, merged, reasons=reasons)

    columns_before = list(existing.columns)
    written = False
    if not dry_run:
        atomic_write_csv(live_path, merged)
        written = True

    return {
        "league": league_name,
        "fd_code": fd_code,
        "live_path": live_path,
        "season": season,
        "source": source_meta,
        "columns_before": columns_before,
        "columns_after": list(merged.columns),
        "written": written,
        "dry_run": dry_run,
        "merge": stats,
        "coverage": coverage,
    }


# ==========================================
# CLI
# ==========================================
def _print_run(entry: Dict[str, object]) -> None:
    merge = entry["merge"]
    cov = entry["coverage"]
    probe_txt = ", ".join(
        f"{p}={cov[p]['covered']}/{cov[p].get('played', cov[p]['covered'] + cov[p]['missing'])}"
        f" ({cov[p]['ratio']:.1%})" for p in COVERAGE_PROBES)
    print(f"[{entry['league']}] {entry['fd_code']} {entry['season']} — "
          f"{merge['rows']} righe, {merge['matched_exact']} appaiate esatte, "
          f"{merge['matched_tolerance']} appaiate con tolleranza, "
          f"{merge['unmatched']} non appaiate")
    print(f"    colonne {merge['columns_before']} -> {merge['columns_after']} "
          f"(+{len(merge['columns_added'])}), celle riempite {merge['cells_filled']}, "
          f"copertura {probe_txt}")
    if merge["unmatched"]:
        print(f"    NON appaiate ({merge['unmatched']}):")
        for row in merge["unmatched_rows"]:
            print(f"      - {row['Date']} {row['HomeTeam']} - {row['AwayTeam']} "
                  f"[{row['HomeClean']}/{row['AwayClean']}]")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Arricchisce i *_Live.csv con le colonne football-data.co.uk")
    parser.add_argument("--database-dir", default=str(DATABASE_DIR),
                        help="cartella dei *_Live.csv (default: config.DATABASE_DIR)")
    parser.add_argument("--source-dir", default=None,
                        help="usa CSV gia' scaricati ({FD_CODE}.csv) invece della rete")
    parser.add_argument("--cache-dir", default=None,
                        help="scarica in questa cartella e riusa i file presenti")
    parser.add_argument("--refresh", action="store_true",
                        help="con --cache-dir: riscarica anche se il file c'e' gia'")
    parser.add_argument("--league", action="append", default=None,
                        help="limita a una lega (ripetibile; nome in LEAGUES_CONFIG)")
    parser.add_argument("--dry-run", action="store_true",
                        help="calcola tutto ma non scrive i CSV")
    parser.add_argument("--tolerance-days", type=int, default=DEFAULT_TOLERANCE_DAYS,
                        help="tolleranza sulla data nel secondo passaggio (default 1)")
    parser.add_argument("--timeout", type=int, default=REQUEST_TIMEOUT,
                        help="timeout HTTP in secondi (default 30)")
    parser.add_argument("--json-out", default=None,
                        help="scrive qui il referto machine-readable del run")
    args = parser.parse_args(argv)

    season = season_code()
    print(f"=== UPDATE DB RICH — stagione {season} "
          f"(da config.CURRENT_SEASON_START_YEAR={CURRENT_SEASON_START_YEAR}) ===")

    report: Dict[str, object] = {
        "season": season,
        "generated_at": _utc_now_iso(),
        "database_dir": args.database_dir,
        "dry_run": bool(args.dry_run),
        "tolerance_days": args.tolerance_days,
        "leagues": {},
        "failures": [],
    }
    failures: List[str] = []

    for league_name, info in LEAGUES_CONFIG.items():
        if args.league and league_name not in args.league:
            continue
        try:
            entry = enrich_league(
                league_name, info, season,
                database_dir=args.database_dir,
                source_dir=args.source_dir,
                cache_dir=args.cache_dir,
                refresh=args.refresh,
                dry_run=args.dry_run,
                tolerance_days=args.tolerance_days,
                timeout=args.timeout)
            report["leagues"][league_name] = entry
            _print_run(entry)
        except (FetchError, ParseError, OSError) as exc:
            failures.append(f"{league_name}: {exc}")
            report["leagues"][league_name] = {"league": league_name, "error": str(exc)}
            print(f"[{league_name}] FALLITA: {exc}")

    report["failures"] = failures
    report["exit_code"] = 1 if failures else 0

    if args.json_out:
        try:
            with open(args.json_out, "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, indent=2, sort_keys=True)
        except OSError as exc:  # pragma: no cover
            print(f"[ATTENZIONE] referto JSON non scritto: {exc}")

    print("\n=== COMPLETATO ===")
    if failures:
        print("[ERRORE] leghe non aggiornate:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
