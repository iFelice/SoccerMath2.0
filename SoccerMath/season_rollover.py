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

Lo script e' idempotente: eseguito piu' volte non duplica nulla.
La stagione corrente e' derivata dalla data (vedi config.get_current_season_start_year):
da luglio in poi si considera iniziata la nuova stagione.

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
    get_current_season_start_year,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Chiave di deduplica: identica a quella usata da update_db.py
DEDUP_KEYS = ["Date", "HomeTeam", "AwayTeam"]


def _season_of(dates: pd.Series) -> pd.Series:
    """
    Anno di inizio stagione per ogni data (Series datetime).
    Stagione ago-giu: da luglio in poi appartiene all'anno in corso.
    Le date non valide (NaT) producono NaN.
    """
    return dates.dt.year - (dates.dt.month < 7).astype(int)


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

    dates = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    seasons = _season_of(dates)

    # Le righe con data non valide restano nel Live (non si puo' archiviarle con certezza)
    keep_live = seasons.isna() | (seasons == current_season)
    df_current = df[keep_live].copy()
    df_old = df[~keep_live].copy()

    report["live_restanti"] = int(len(df_current))

    if df_old.empty:
        return report  # solo stagione corrente (o vuoto): niente da fare

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
            df_season = pd.concat([df_archive, df_season], ignore_index=True)
            df_season = df_season.drop_duplicates(subset=DEDUP_KEYS, keep="last")
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
        if report["status"] == "archived":
            archiviati += 1
            for season, (n, note) in sorted(report["archivi"].items()):
                logging.info("[%s] archiviato %s_%d.csv -> %d partite totali (%s)",
                             name, prefix, season, n, note)
            logging.info("[%s] Live pronto alla nuova stagione: %d partite della %d/%d",
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
