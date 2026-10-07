"""
make_elo_parity_fixture.py — GENERATORE della fixture congelata per il test di
parita' del walker Elo (punto A.3 della roadmap).

La fixture e' prodotta ESCLUSIVAMENTE da codice di produzione non modificato
(``models/elo_engine.py`` al commit dichiarato nella fixture stessa). Questo
script non contiene alcuna formula Elo: costruisce ``EloEngine`` di produzione
e chiama ``predict_elo_probs`` di produzione.

Tre blocchi nella fixture:

  1. ``final_ratings``  — ``EloEngine(lega).compute_ratings()`` sul DB completo.
  2. ``now_fixtures``   — ``predict_elo_probs`` di produzione (DB completo) su
     un campione deterministico di accoppiamenti.
  3. ``cutoff_cases``   — il vero riferimento walk-forward: per alcune date di
     cutoff, un motore di produzione costruito su CSV TRONCATI a
     ``Date_Parsed < cutoff`` e le sue ``predict_elo_probs`` per le partite di
     quella data. Il walker deve riprodurle bit-exact.

Troncamento: i CSV vengono riscritti filtrati in una cartella temporanea e
``config.DATABASE_DIR`` / ``config.LEAGUES_CONFIG[*]['base_csv'|'live_csv']``
vengono ripuntati li' PER LA DURATA DELLA GENERAZIONE (monkeypatch in-process,
nessun file di produzione toccato, nessun CSV del repo riscritto).

Uso:  python audit/make_elo_parity_fixture.py
Out:  audit/fixtures/elo_walker_parity.json
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

import config as PROD_CONFIG                                   # noqa: E402
import models.elo_engine as PROD_ELO                           # noqa: E402
from models.elo_engine import EloEngine, predict_elo_probs     # noqa: E402

LEAGUES = ("Serie A", "Premier League", "La Liga", "Bundesliga", "Ligue 1")
OUT_DIR = os.path.join(_AUDIT_DIR, "fixtures")
OUT_PATH = os.path.join(OUT_DIR, "elo_walker_parity.json")
OUT_PATH_USED: list = []

#: date di cutoff per lega: si scelgono i QUANTILI dell'indice di produzione,
#: spostati alla PRIMA partita della sua data (vedi nota sul tie-order).
CUTOFF_QUANTILES = (0.25, 0.50, 0.75, 0.95)
#: cutoff aggiuntivi che cadono sulla PRIMA giornata di una stagione con
#: neopromosse: e' il caso in cui l'insieme attivo e' piu' corto e in cui la
#: definizione del seed e' quella che decide il rating dell'ingresso.
CUTOFF_PRIMA_GIORNATA = ("2024-08-17", "2025-08-15", "2026-08-21")
N_NOW_FIXTURES = 10


def _git(*args):
    return subprocess.check_output(["git", *args], cwd=_REPO_ROOT).decode().strip()


#: Input di PRODUZIONE da cui dipende, bit per bit, il contenuto numerico
#: della fixture. Per ognuno si registra l'object id git al commit di
#: generazione: un blob per i file, un tree per la cartella del DB (un solo
#: hash che copre tutti i CSV e i loro contenuti).
PRODUCTION_INPUTS = (
    "SoccerMath/models/elo_engine.py",   # EloEngine, predict_elo_probs, formula 1X2
    "SoccerMath/config.py",              # LEAGUE_HOME_ADVANTAGE, clean_name, get_league_db_files
    "SoccerMath/database",               # tree: tutti i CSV letti da load_and_preprocess_matches
)


def production_input_oids(commit: str) -> dict:
    """``{path: object id git al commit}`` per gli input di produzione.

    Non dipende dal working tree: legge l'oggetto git del commit indicato.
    """
    return {p: _git("rev-parse", f"{commit}:{p}") for p in PRODUCTION_INPUTS}


def _fresh_engine(league: str) -> EloEngine:
    """Motore di produzione pulito (bypassa la cache di modulo)."""
    PROD_ELO._ELO_ENGINES_CACHE.pop(league, None)
    PROD_ELO._ELO_ENGINES_STAMP.pop(league, None)
    e = EloEngine(league)
    e.compute_ratings()
    return e


def _roster_completo() -> dict:
    """R(lega, stagione) dal database INTEGRALE, calcolato una volta sola.

    Il roster e' un input esplicito: nel backtest su CSV troncati il motore
    riceve questo e non quello ricavato dal DB tagliato, cosi' il riferimento
    del seed non dipende da quanto e' stato troncato il database. Stessa
    sorgente per il walker e per il motore di produzione.
    """
    out = {}
    for lg in LEAGUES:
        e = _fresh_engine(lg)
        out[lg] = {k: set(v) for k, v in e.season_rosters.items()}
    return out


def _probs_via_production(league: str, engine: EloEngine, pairs,
                          season=None):
    """``predict_elo_probs`` di produzione con ``engine`` in cache."""
    import time
    PROD_ELO._ELO_ENGINES_CACHE[league] = engine
    PROD_ELO._ELO_ENGINES_STAMP[league] = time.monotonic()
    out = []
    for home_raw, away_raw in pairs:
        p = predict_elo_probs(home_raw, away_raw, league, season=season)
        out.append({"home_raw": home_raw, "away_raw": away_raw, "probs": p})
    PROD_ELO._ELO_ENGINES_CACHE.pop(league, None)
    PROD_ELO._ELO_ENGINES_STAMP.pop(league, None)
    return out


def _write_truncated_db(tmp_dir: str, cutoff: pd.Timestamp):
    """Copia i CSV del DB in ``tmp_dir`` tenendo solo le righe con
    Date (dayfirst) < cutoff. Nessun file di produzione modificato."""
    src = Path(PROD_CONFIG.DATABASE_DIR)
    dst = Path(tmp_dir)
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.glob("*.csv"):
        df = pd.read_csv(f, on_bad_lines="warn", low_memory=False)
        if "Date" in df.columns:
            d = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
            df = df[d.notna() & (d < cutoff)]
        df.to_csv(dst / f.name, index=False)
    for f in src.glob("*.json"):
        shutil.copy(f, dst / f.name)


class _RepointDB:
    """Monkeypatch di config.DATABASE_DIR e dei percorsi assoluti in
    LEAGUES_CONFIG, ripristinati all'uscita."""

    def __init__(self, tmp_dir):
        self.tmp = Path(tmp_dir)

    def __enter__(self):
        self.old_dir = PROD_CONFIG.DATABASE_DIR
        self.old_cfg = {k: dict(v) for k, v in PROD_CONFIG.LEAGUES_CONFIG.items()}
        PROD_CONFIG.DATABASE_DIR = self.tmp
        for k, v in PROD_CONFIG.LEAGUES_CONFIG.items():
            for key in ("base_csv", "live_csv", "xg_json"):
                if v.get(key):
                    v[key] = str(self.tmp / Path(v[key]).name)
        return self

    def __exit__(self, *exc):
        PROD_CONFIG.DATABASE_DIR = self.old_dir
        for k, v in self.old_cfg.items():
            PROD_CONFIG.LEAGUES_CONFIG[k] = v
        return False


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    head = _git("rev-parse", "HEAD")
    # La fixture e' valida solo se gli input di produzione in working tree
    # coincidono con quelli del commit dichiarato: altrimenti il commit scritto
    # nel manifest non descriverebbe i numeri generati.
    sporco = _git("status", "--porcelain", "--", *PRODUCTION_INPUTS)
    if sporco:
        raise SystemExit(
            "RIFIUTO DI GENERARE: gli input di produzione hanno modifiche non "
            "committate, il commit dichiarato nel manifest non li descriverebbe.\n"
            + sporco)
    fixture = {
        "_schema": "elo_walker_parity/2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo_head_commit": head,
        "generato_da": "audit/make_elo_parity_fixture.py usando solo "
                       "models/elo_engine.py (EloEngine, predict_elo_probs) non modificato",
        # Provenienza AUTOCONTENUTA: nessun riferimento a main o a una
        # whitelist di commit. Il test ricostruisce la fixture dal commit
        # qui dichiarato e la confronta bit-exact; questi object id git
        # dicono esattamente QUALE produzione quel commit contiene.
        "provenance": {
            "commit": head,
            "production_input_oids": production_input_oids(head),
        },
        "leagues": {},
    }

    # --- blocchi 1 e 2: DB completo ---------------------------------------
    full_tables = {}
    for lg in LEAGUES:
        eng = _fresh_engine(lg)
        df = eng.matches_df
        full_tables[lg] = df
        tail = df.tail(N_NOW_FIXTURES)
        pairs = list(zip(tail["HomeTeam"], tail["AwayTeam"]))
        fixture["leagues"][lg] = {
            "n_matches_full_db": int(len(df)),
            "first_date": str(df["Date_Parsed"].min()),
            "last_date": str(df["Date_Parsed"].max()),
            "home_adv": eng.home_adv,
            "final_ratings": {t: repr(float(r)) for t, r in sorted(eng.ratings.items())},
            "now_fixtures": _probs_via_production(lg, eng, pairs),
            "cutoff_cases": [],
        }

    # --- blocco 3: cutoff walk-forward ------------------------------------
    # Le date di cutoff sono comuni a tutte le leghe (un solo troncamento per
    # cutoff), prese dai quantili della Premier League per semplicita'.
    roster_completo = _roster_completo()
    ref = full_tables["Premier League"]
    cutoffs = []
    for q in CUTOFF_QUANTILES:
        i = int(q * (len(ref) - 1))
        cutoffs.append(pd.Timestamp(ref["Date_Parsed"].iloc[i]).normalize())
    cutoffs += [pd.Timestamp(s) for s in CUTOFF_PRIMA_GIORNATA]
    cutoffs = sorted(set(cutoffs))

    for cutoff in cutoffs:
        tmp = tempfile.mkdtemp(prefix="elo_parity_db_")
        try:
            _write_truncated_db(tmp, cutoff)
            with _RepointDB(tmp):
                for lg in LEAGUES:
                    full = full_tables[lg]
                    same_day = full[full["Date_Parsed"] == cutoff]
                    if same_day.empty:
                        continue
                    # SOLO la prima partita della data nell'ORDINE DI PRODUZIONE:
                    # per quella, lo stato del walker e' esattamente l'insieme
                    # {Date_Parsed < cutoff}; per le successive della stessa
                    # data il walker ha gia' assorbito le precedenti.
                    first_pos = int(full.index.get_indexer([same_day.index[0]])[0])
                    row = full.loc[same_day.index[0]]
                    eng_t = EloEngine(lg, season_rosters=roster_completo[lg])
                    eng_t.compute_ratings()
                    n_trunc = int(len(eng_t.matches_df))
                    season_cutoff = int(cutoff.year - (cutoff.month <= 6))
                    probs = _probs_via_production(
                        lg, eng_t, [(row["HomeTeam"], row["AwayTeam"])],
                        season=season_cutoff)[0]
                    # Il loader di produzione riordina per data con un sort
                    # instabile: sul DB troncato le partite della stessa
                    # giornata possono quindi NON essere nello stesso ordine
                    # del walker. Senza il seeding l'ordine dentro la giornata
                    # e' irrilevante (le partite di una giornata sono
                    # disgiunte: nessuna squadra gioca due volte lo stesso
                    # giorno, verificato su tutti i 2445 blocchi); col seeding
                    # non lo e' piu', perche' il seed di una neo-promossa
                    # dipende da quali partite della giornata sono state
                    # gia' processate. Si registra quindi anche se i due
                    # motori hanno mangiato le righe nello stesso ordine:
                    # il test asserisce la parita' bit-exact esattamente li'.
                    ordine_walker = list(zip(full.iloc[:n_trunc]["HomeClean"],
                                            full.iloc[:n_trunc]["AwayClean"]))
                    ordine_troncato = list(zip(eng_t.matches_df["HomeClean"],
                                               eng_t.matches_df["AwayClean"]))
                    # Rating realmente usati dalla produzione: se la squadra
                    # non e' ancora nel DB troncato predict_elo_probs passa
                    # engine.promoted_seed(), non DEFAULT_INITIAL_RATING.
                    def _rating_usato(team, _s=season_cutoff, _e=eng_t):
                        r = _e.ratings.get(team)
                        return float(r if r is not None else _e.promoted_seed(_s))
                    fixture["leagues"][lg]["cutoff_cases"].append({
                        "cutoff": str(cutoff.date()),
                        "n_matches_nel_motore_troncato": n_trunc,
                        "prod_pos_nel_db_completo": first_pos,
                        "ordine_uguale_alla_produzione": ordine_walker == ordine_troncato,
                        "home_raw": row["HomeTeam"], "away_raw": row["AwayTeam"],
                        "home": row["HomeClean"], "away": row["AwayClean"],
                        "probs": probs["probs"],
                        "ratings_troncati": {
                            row["HomeClean"]: repr(_rating_usato(row["HomeClean"])),
                            row["AwayClean"]: repr(_rating_usato(row["AwayClean"])),
                        },
                    })
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    out_path = OUT_PATH
    if "--out" in sys.argv:
        out_path = sys.argv[sys.argv.index("--out") + 1]
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(fixture, f, indent=1, ensure_ascii=False, sort_keys=False)
    OUT_PATH_USED.append(out_path)
    print(f"scritta {out_path}")
    print(f"commit di generazione: {head}")
    for p, oid in fixture["provenance"]["production_input_oids"].items():
        print(f"  input produzione {p:34s} {oid}")
    for lg in LEAGUES:
        b = fixture["leagues"][lg]
        print(f"  {lg:16s} n={b['n_matches_full_db']:5d} "
              f"now_fixtures={len(b['now_fixtures'])} cutoff_cases={len(b['cutoff_cases'])}")


if __name__ == "__main__":
    main()
