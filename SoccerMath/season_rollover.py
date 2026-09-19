"""
season_rollover.py - Archiviazione automatica del file Live a fine campionato.

A fine stagione (finestra luglio-agosto) ogni file <Prefix>_Live.csv contiene
ancora le partite del campionato appena concluso. Questo script:
  1. sposta le partite delle stagioni concluse in <Prefix>_<anno_inizio>.csv
     (es. a luglio 2027 le partite 2026/27 di SerieA_Live.csv finiscono in
     SerieA_2026.csv), unendo e deduplicando se l'archivio esiste gia';
  2. riscrive il file Live con le sole partite della stagione corrente
     (solo intestazione se non ce ne sono ancora), pronta per ripartire da 0
     con i dati della nuova stagione che update_db.py scarichera'.

Prima di archiviare, i nomi squadra del Live vengono normalizzati
(config.clean_name) e le righe deduplicate sulla chiave normalizzata: la
stessa partita registrata con due grafie diverse ("Nottingham" e
"Nott'm Forest") e' una sola riga, e l'archivio storico non eredita doppioni.

Lo script e' idempotente: eseguito piu' volte non duplica nulla.
La stagione corrente e' derivata dalla data (vedi config.get_current_season_start_year
e season_calendar.SEASON_START_MONTH): da luglio in poi si considera iniziata
la nuova stagione (confine verificato sul calendario reale delle 5 leghe).

Uso:
    python season_rollover.py             # rollover reale
    python season_rollover.py --dry-run   # mostra solo cosa farebbe
Schedulato con GitHub Actions nel workflow update_database.yml.
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

import config
from config import (
    DATABASE_DIR,
    LEAGUES_CONFIG,
    SEASON_START_MONTH,
    clean_name,
    get_current_season_start_year,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Chiave di deduplica: identica a quella usata da update_db.py. Viene applicata
# DOPO la normalizzazione dei nomi (normalize_team_columns), quindi due grafie
# della stessa squadra ("Nottingham" / "Nott'm Forest") sono la stessa riga.
DEDUP_KEYS = ["Date", "HomeTeam", "AwayTeam"]


def normalize_team_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Riscrive HomeTeam/AwayTeam con il nome canonico (config.clean_name).

    Le API live hanno cambiato grafia nel tempo (es. "Brighton Hove" ->
    "Brighton", "Atleti" -> "Ath Madrid"): update_db.py deduplicava sulla
    chiave grezza e la stessa partita finiva nel Live due volte (30 righe
    doppie rilevate il 19/09/2026). Normalizzare PRIMA di deduplicare rende la
    chiave stabile e impedisce che il rollover archivi un Live sporco.
    """
    out = df.copy()
    for col in ("HomeTeam", "AwayTeam"):
        if col in out.columns:
            out[col] = out[col].map(lambda v: clean_name(v) if isinstance(v, str) else v)
    return out


def dedup_matches(df: pd.DataFrame) -> pd.DataFrame:
    """Normalizza i nomi e deduplica su Date+HomeTeam+AwayTeam (keep='last',
    stessa regola di update_db.py e di get_league_engine)."""
    out = normalize_team_columns(df)
    if all(c in out.columns for c in DEDUP_KEYS):
        out = out.drop_duplicates(subset=DEDUP_KEYS, keep="last")
    return out.reset_index(drop=True)


def teams_without_market_value(df: pd.DataFrame, market_values=None) -> list:
    """Squadre presenti nel Live (nomi canonici) senza voce in config.MARKET_VALUES.

    La tabella resta scritta a mano (l'alternativa derivata dagli xG e' stata
    valutata e scartata: audit/results/market_prior_xg_report.md). Una squadra
    assente riceve il default 50 (fattore 0.925): non blocca nulla, ma al
    rollover va segnalata esplicitamente per l'aggiornamento estivo.
    """
    values = config.MARKET_VALUES if market_values is None else market_values
    teams = set()
    for col in ("HomeTeam", "AwayTeam"):
        if col in df.columns:
            teams.update(clean_name(v) for v in df[col].dropna().astype(str))
    return sorted(t for t in teams if t and t not in values)


def _season_of(dates: pd.Series) -> pd.Series:
    """
    Anno di inizio stagione per ogni data (Series datetime).
    Stagione ago-giu: dal mese SEASON_START_MONTH (luglio) in poi appartiene
    all'anno in corso (stessa regola di config/season_calendar).
    Le date non valide (NaT) producono NaN.
    """
    return dates.dt.year - (dates.dt.month < SEASON_START_MONTH).astype(int)


def _sort_by_date(frame: pd.DataFrame) -> pd.DataFrame:
    """Ordina per data reale (la colonna Date e' testo gg/mm/aaaa, non va ordinata alfabeticamente)."""
    if "Date" in frame.columns and len(frame) > 0:
        ordine = pd.to_datetime(frame["Date"], dayfirst=True, errors="coerce")
        frame = frame.assign(_ord=ordine).sort_values("_ord", kind="stable").drop(columns="_ord")
    return frame.reset_index(drop=True)


def rollover_league(prefix: str, live_path, current_season: int, dry_run: bool = False) -> dict:
    """
    Rollover per un singolo campionato. Ritorna un report:
    {"prefix", "status": "noop"|"archived", "archivi": {season: n_partite}, "live_restanti": n}
    e solleva eccezioni in caso di errore (gestite da run_rollover).
    """
    report = {"prefix": prefix, "status": "noop", "archivi": {}, "live_restanti": 0}

    live_file = Path(live_path)
    if not live_file.exists():
        return report

    try:
        df = pd.read_csv(live_file, on_bad_lines="skip", low_memory=False)
    except pd.errors.EmptyDataError:
        return report  # file vivo ma vuoto: nulla da archiviare

    if df.empty or "Date" not in df.columns or "HomeTeam" not in df.columns or "AwayTeam" not in df.columns:
        return report

    # Pulizia PRIMA di archiviare: nomi canonici + deduplica sulla chiave
    # normalizzata. Un Live con la stessa partita in due grafie non deve mai
    # finire nell'archivio storico (ne' restare nel Live della nuova stagione).
    righe_prima = len(df)
    df = dedup_matches(df)
    report["duplicati_rimossi"] = int(righe_prima - len(df))

    dates = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    seasons = _season_of(dates)

    # Le righe con data non valide restano nel Live (non si puo' archiviarle con certezza)
    keep_live = seasons.isna() | (seasons == current_season)
    df_current = df[keep_live].copy()
    df_old = df[~keep_live].copy()

    report["live_restanti"] = int(len(df_current))
    report["senza_market_value"] = teams_without_market_value(df_current)

    if df_old.empty:
        if report["duplicati_rimossi"]:
            # Nulla da archiviare, ma il Live conteneva doppioni: lo si riscrive
            # pulito (idempotente: alla seconda esecuzione non cambia piu' nulla).
            report["status"] = "cleaned"
            if not dry_run:
                _sort_by_date(df_current).to_csv(live_file, index=False)
        return report  # solo stagione corrente (o vuoto): niente da archiviare

    for season in sorted(int(s) for s in seasons[~keep_live].dropna().unique()):
        df_season = df_old[seasons[~keep_live] == season].copy()
        if df_season.empty:
            continue
        archive_path = live_file.parent / f"{prefix}_{season}.csv"
        note = "creato"
        if archive_path.exists():
            try:
                df_archive = pd.read_csv(archive_path, on_bad_lines="skip", low_memory=False)
            except pd.errors.EmptyDataError:
                df_archive = pd.DataFrame()
            prima = len(df_archive)
            # L'archivio storico puo' contenere i nomi originali di football-data
            # (es. "Bayern Munich"): la deduplica confronta le chiavi normalizzate
            # senza riscrivere le righe gia' archiviate.
            merged = pd.concat([df_archive, df_season], ignore_index=True)
            key = normalize_team_columns(merged[DEDUP_KEYS]) if all(c in merged.columns for c in DEDUP_KEYS) else None
            if key is not None:
                merged = merged[~key.duplicated(keep="last")]
            df_season = merged
            note = f"unito (+{len(df_season) - prima} nuove)"
        df_season = _sort_by_date(df_season)
        report["archivi"][season] = (len(df_season), note)
        if not dry_run:
            df_season.to_csv(archive_path, index=False)

    # Riscrive il Live con le sole partite della stagione corrente (o solo intestazione)
    df_current = _sort_by_date(df_current)
    if not dry_run:
        df_current.to_csv(live_file, index=False)
    report["status"] = "archived"
    report["senza_market_value"] = teams_without_market_value(df_current)
    return report


def run_rollover(db_dir=None, now=None, dry_run: bool = False) -> int:
    """
    Esegue il rollover per tutti i campionati in LEAGUES_CONFIG.
    Ritorna il numero di campionati archiviati; solleva l'ultimo errore se
    tutti i campionati hanno fallito.
    """
    db_dir = Path(db_dir) if db_dir else Path(DATABASE_DIR)
    current_season = get_current_season_start_year(now)
    now_str = (now or datetime.now()).strftime("%d/%m/%Y")
    logging.info("=== ROLLOVER STAGIONE - oggi: %s - stagione corrente: %d/%d ===",
                 now_str, current_season, current_season + 1)
    if dry_run:
        logging.info("Modalita' DRY-RUN: nessun file verra' modificato.")

    archiviati, errori = 0, 0
    last_error = None
    for name, info in LEAGUES_CONFIG.items():
        prefix = info.get("db_prefix") or info.get("short_name")
        # NB: il percorso si risolve SEMPRE da db_dir (che nel test e' temporaneo):
        # info["live_csv"] punta al database reale e ignorerebbe l'override.
        live_path = db_dir / f"{prefix}_Live.csv"
        try:
            report = rollover_league(prefix, live_path, current_season, dry_run=dry_run)
        except Exception as e:
            logging.error("[%s] errore durante il rollover: %s", name, e)
            errori += 1
            last_error = e
            continue
        if report.get("duplicati_rimossi"):
            logging.info("[%s] %d righe duplicate (stessa partita, grafie diverse) rimosse dal Live",
                         name, report["duplicati_rimossi"])
        if report.get("senza_market_value"):
            logging.warning("[%s] squadre del Live senza voce in config.MARKET_VALUES "
                            "(useranno il default 50): %s", name,
                            ", ".join(report["senza_market_value"]))
        if report["status"] == "archived":
            archiviati += 1
            for season, (n, note) in sorted(report["archivi"].items()):
                logging.info("[%s] archiviato %s_%d.csv -> %d partite totali (%s)",
                             name, prefix, season, n, note)
            logging.info("[%s] Live pronto alla nuova stagione: %d partite della %d/%d",
                         name, report["live_restanti"], current_season, current_season + 1)
        elif report["status"] == "cleaned":
            logging.info("[%s] nulla da archiviare: Live ripulito dai duplicati (%d partite della %d/%d)",
                         name, report["live_restanti"], current_season, current_season + 1)
        else:
            logging.info("[%s] nulla da archiviare (Live gia' allineato alla stagione %d/%d)",
                         name, current_season, current_season + 1)

    if errori:
        logging.warning("Rollover completato con %d errori su %d campionati.", errori, len(LEAGUES_CONFIG))
        if errori == len(LEAGUES_CONFIG) and last_error:
            raise last_error
    elif archiviati:
        logging.info("Rollover completato: %d campionati archiviati.", archiviati)
    else:
        logging.info("Rollover completato: nessuna archiviazione necessaria.")
    return archiviati


def main():
    parser = argparse.ArgumentParser(description="Archiviazione automatica fine stagione (vedi docstring).")
    parser.add_argument("--dry-run", action="store_true", help="mostra solo le azioni previste, senza modificare file")
    parser.add_argument("--now", default=None, help="data simulata ISO (YYYY-MM-DD), per test/manuali")
    args = parser.parse_args()

    now = datetime.strptime(args.now, "%Y-%m-%d") if args.now else None
    try:
        run_rollover(now=now, dry_run=args.dry_run)
    except Exception as e:
        logging.error("Rollover fallito: %s", e)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
