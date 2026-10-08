"""
make_elo_s3_parity_fixture.py — GENERATORE della fixture congelata del seeding
S3 (variante ``S3`` di ``audit/elo_drift_triage.py``, la sola adottata dalla PR
che applica il seeding alla produzione).

Cosa contiene
-------------
Per ogni lega e per ogni partita nell'ORDINE DI PRODUZIONE (``prod_order``, lo
stesso ordine che ``EloEngine.compute_ratings`` usa): rating pre-partita di casa
e trasferta, rating post-partita, ``e_H``, ``p_draw`` e la terna Elo 1X2 della
rilanciata S3. Tutti i float sono serializzati con ``repr()`` e riletti con
``float()``: il confronto con la produzione e' BIT-EXACT, non tollerante.

La fixture e' prodotta ESCLUSIVAMENTE riutilizzando la logica dell'audit: la
classificazione degli ingressi (``_entry_records``) e' quella di
``audit/elo_drift_triage.py`` e il seed e' quello di ``_seed_for_variant("S3")``
= media dei rating delle squadre ATTIVE AL INIZIO DELLA GIORNATA della partita
d'ingresso, meno 100. Nessuna formula Elo e' riscritta qui: gli update li fa
``EloEngine.compute_ratings`` di produzione e la conversione 1X2
``elo_probs_from_ratings`` di produzione.

Perche' due commit
------------------
Il riferimento deve essere la produzione PRIMA della modifica (che non ha il
seeding): se girasse sul branch, ``compute_ratings`` applicherebbe da se' i
seed e la fixture non sarebbe piu' un riferimento indipendente. Il generatore
quindi prepara un worktree al commit ``--rif`` (di default il main da cui parte
il branch), ci copia dentro la logica dell'AUDIT di questo branch e calcola la
variante S3 li'. La provenienza dichiara i due commit e i loro object id:

  * ``reference_production_commit`` + ``production_input_oids``: da quale
    commit vengono gli input di produzione (motore, config, database);
  * ``audit_logic_commit`` + ``audit_input_oids``: da quale commit viene la
    LOGICA del seeding;
  * ``database_usato``: il DATABASE effettivamente letto, che e' quello del
    branch (``commit`` + ``tree_oid``), copiato nel worktree al posto di quello
    di ``reference_production_commit``. I due commit coincidono quando il
    database del branch e' quello dello stesso albero di produzione; quando
    divergono (es. correzione dati sulla Liga) il manifest lo dice, invece di
    lasciarlo implicito: la fixture e' rigenerata sul database corretto, con il
    CODICE di produzione invariato.

Il frame su cui girano le funzioni dell'audit e' ricostruito dai CSV con la
STESSA pipeline di produzione (``EloEngine.load_and_preprocess_matches``); la
colonna ``season`` e' la stagione DERIVATA dalla data con
``config.season_start_year_of``. L'equivalenza di quella colonna con l'etichetta
del file usata dall'audit (``backtest_experiment_all.load_league``) e' un fatto
verificato e ricontrollabile: 0 discrepanze su 7332 partite sulle 5 leghe
(dopo la correzione dati della Liga: le due righe fittizie di Levante-Ath
Bilbao non entrano piu' nel conteggio).

Come ``make_elo_parity_fixture`` (PR #30), il generatore RIFIUTA di scrivere se
il working tree degli input di produzione o dell'audit e' sporco: altrimenti i
commit nel manifest non descriverebbero i numeri scritti.

Uso:  .venv/bin/python audit/make_elo_s3_parity_fixture.py [--rif <commit>]
Out:  audit/fixtures/elo_s3_parity.json
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

_AUDIT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _AUDIT_DIR.parent
for _p in (str(_AUDIT_DIR), str(_REPO_ROOT / "SoccerMath")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import elo_walker_core as WALKER                        # noqa: E402
from config import season_start_year_of                  # noqa: E402
from elo_drift_triage import (                           # noqa: E402
    _entry_records,
    run_variant,
)
from models.elo_engine import EloEngine                  # noqa: E402

OUT_PATH = _AUDIT_DIR / "fixtures" / "elo_s3_parity.json"

#: input di PRODUZIONE da cui dipende, bit per bit, il contenuto numerico
PRODUCTION_INPUTS = (
    "SoccerMath/models/elo_engine.py",   # EloEngine.compute_ratings: gli update
    "SoccerMath/config.py",              # season_start_year_of, clean_name, DB
    "SoccerMath/database",               # tree: i CSV letti dal motore
)
#: input dell'AUDIT da cui dipende la LOGICA del seeding S3
AUDIT_INPUTS = ("audit/elo_drift_triage.py", "audit/elo_walker_core.py")

#: anno di inizio della prima stagione della tupla SEASONS dell'audit
S3_BASE_START_YEAR = 2022


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=_REPO_ROOT).decode().strip()


def _oids(commit: str, paths) -> dict:
    return {p: _git("rev-parse", f"{commit}:{p}") for p in paths}


def _build_frame(engine: EloEngine, league: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(frame per l'audit, raw del motore) nello stesso ordine di produzione."""
    raw = engine.matches_df.copy().reset_index(drop=True)
    walker = WALKER.build_walker_table(league, engine=engine).reset_index(drop=True)
    if len(raw) != len(walker):
        raise AssertionError(f"raw/walker non allineati: {league}")
    pre = WALKER._prematch_ratings(engine).reset_index(drop=True)
    seasons = [season_start_year_of(ts) - S3_BASE_START_YEAR for ts in raw["Date_Parsed"]]
    frame = walker.assign(
        prod_order=np.arange(len(walker), dtype=int),
        season=[f"{S3_BASE_START_YEAR + i}/{(S3_BASE_START_YEAR + i + 1) % 100:02d}" for i in seasons],
        elo_home_post=pre["elo_home_post"].to_numpy(),
        elo_away_post=pre["elo_away_post"].to_numpy(),
        match_key=[f"{r['date']}|{r['home']}|{r['away']}" for _, r in walker.iterrows()],
        league=league,
    )
    return frame, raw


#: main da cui parte il branch: produzione SENZA seeding, la reference
DEFAULT_REF = "9957f417ff5690bfd07210b4e1cdbb2388949281"

AUDIT_COPY = ("audit/elo_drift_triage.py", "audit/elo_walker_core.py",
              "audit/make_elo_s3_parity_fixture.py")


def _arg(flag: str, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def _genera_in_ref(ref: str, out_path: Path, head: str) -> int:
    """Calcola la fixture in un worktree pulito a ``ref``.

    Il worktree ha la PRODUZIONE di ``ref`` (motore senza seeding) e la LOGICA
    dell'audit di questo branch. Il DATABASE invece e' quello del branch
    (``head``): viene copiato nel worktree al posto di quello di ``ref``. Serve
    a rigenerare le fixture su un database CORRETTO senza cambiare il codice di
    produzione di riferimento: le due righe fittizie di Levante-Ath Bilbao
    (16/09/2026 sospesa, 21/10/2026 data del recupero) rimosse da
    ``LaLiga_Live.csv`` non devono entrare nei numeri della fixture, altrimenti
    restano congelati due risultati mai giocati. La scelta e' dichiarata nel
    manifest (``provenance.database_usato``) e i CSV non vengono mai riscritti.
    """
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="elo_s3_ref_")
    try:
        subprocess.run(["git", "worktree", "add", "--detach", tmp, ref],
                       cwd=_REPO_ROOT, check=True)
        for rel in AUDIT_COPY:
            shutil.copy(_REPO_ROOT / rel, Path(tmp) / rel)
        # database del branch dentro il worktree (il codice resta quello di ref)
        db_src = _REPO_ROOT / "SoccerMath" / "database"
        db_dst = Path(tmp) / "SoccerMath" / "database"
        for f in sorted(db_src.iterdir()):
            if f.is_file():
                shutil.copy(f, db_dst / f.name)
        for f in sorted(db_dst.iterdir()):
            if f.is_file() and not (db_src / f.name).exists():
                f.unlink()
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run(
            [sys.executable, str(Path(tmp) / "audit" / "make_elo_s3_parity_fixture.py"),
             "--interno", "--out", str(out_path.resolve()),
             "--prod-commit", ref, "--audit-commit", head,
             "--database-commit", head],
            cwd=tmp, env=env)
        return r.returncode
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", tmp],
                       cwd=_REPO_ROOT, check=False)
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    head = _git("rev-parse", "HEAD")
    if "--interno" not in sys.argv:
        # Fuori dal worktree i file devono essere gia' committati: e' il controllo
        # che rende il manifest onesto. Dentro, i file di audit sono stati
        # copiati da questo branch e sono per definizione quelli dichiarati.
        dirty = _git("status", "--porcelain", "--", *PRODUCTION_INPUTS, *AUDIT_INPUTS)
        if dirty:
            raise SystemExit(
                "RIFIUTO DI GENERARE: gli input di produzione/audit hanno modifiche non "
                "committate, il commit dichiarato nel manifest non le descriverebbe.\n"
                + dirty)
    out_path = Path(_arg("--out", str(OUT_PATH)))
    prod_commit = _arg("--prod-commit")
    audit_commit = _arg("--audit-commit")
    #: commit da cui viene il DATABASE (il branch, con i dati corretti): dentro
    #: il worktree HEAD e' il commit di produzione, quindi arriva dal chiamante.
    database_commit = _arg("--database-commit", head)
    if "--interno" not in sys.argv:
        return _genera_in_ref(_arg("--rif", DEFAULT_REF), out_path, head)
    # --- il calcolo vero e proprio, dentro il worktree --------------------
    fixture = {
        "_schema": "elo_s3_parity/2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo_head_commit": head,
        "generato_da": "audit/make_elo_s3_parity_fixture.py; logica di seeding "
                       "importata da audit/elo_drift_triage.py (variante S3), update "
                       "Elo e 1X2 di models/elo_engine.py non modificato",
        "offset": -100.0,
        "definizione_seed": "media dei rating delle squadre attive AL INIZIO DELLA "
                            "GIORNATA della partita d'ingresso, piu' l'offset",
        "provenance": {
            "commit": head,
            "reference_production_commit": prod_commit,
            "audit_logic_commit": audit_commit,
            "production_input_oids": _oids(prod_commit, PRODUCTION_INPUTS),
            "audit_input_oids": _oids(audit_commit, AUDIT_INPUTS),
            # Il codice e' quello di ``reference_production_commit``, il
            # database e' quello di ``database_usato.commit`` (il branch, con i
            # dati corretti). I due commit coincidono quando la fixture nasce
            # sul database dello stesso albero di produzione; qui no, ed e'
            # dichiarato invece di essere implicito.
            "database_usato": {
                "commit": database_commit,
                "tree_oid": _git("rev-parse", f"{database_commit}:SoccerMath/database"),
                "motivo": "rigenerazione sul database CORRETTO: rimosse da "
                          "LaLiga_Live.csv le due righe fittizie di "
                          "Levante-Ath Bilbao (16/09/2026 sospesa per pioggia e "
                          "21/10/2026 data del recupero, entrambe 0-0), che "
                          "congelavano due risultati mai giocati. Il commit di "
                          "riferimento resta quello con il codice di produzione "
                          "SENZA seeding: cambia il dato, non il codice.",
            },
        },
        "cutoff": {},
        "leagues": {},
        "total_matches": 0,
    }
    total = 0
    for league in WALKER.LEAGUES:
        engine = EloEngine(league)
        engine.compute_ratings()
        frame, raw = _build_frame(engine, league)
        records = _entry_records(frame)
        out, used_entries = run_variant("S3", league, frame, raw, records)
        fixture["leagues"][league] = {
            "home_adv": engine.home_adv,
            "n_matches": int(len(out)),
            "entries": {
                rec["entry_id"]: {
                    "type": rec["type"],
                    "season": rec["season"],
                    "team": rec["team"],
                    "prod_order": int(rec["prod_order"]),
                    "n_active_before": int(rec["n_active_before"]),
                    "seed": repr(float(used_entries[rec["entry_id"]]["seed"])),
                    "active_mean": repr(float(used_entries[rec["entry_id"]]["active_mean"])),
                }
                for rec in records
            },
            "matches": [
                {
                    "prod_order": int(r["prod_order"]),
                    "date": str(frame["date"].iloc[int(r["prod_order"])].date()),
                    "home": frame["home"].iloc[int(r["prod_order"])],
                    "away": frame["away"].iloc[int(r["prod_order"])],
                    "elo_home_pre": repr(float(r["elo_home_pre"])),
                    "elo_away_pre": repr(float(r["elo_away_pre"])),
                    "elo_home_post": repr(float(r["elo_home_post"])),
                    "elo_away_post": repr(float(r["elo_away_post"])),
                    "e_H": repr(float(r["e_H"])),
                    "p_draw": repr(float(r["p_draw"])),
                    "elo_1": repr(float(r["elo_1"])),
                    "elo_X": repr(float(r["elo_X"])),
                    "elo_2": repr(float(r["elo_2"])),
                }
                for _, r in out.iterrows()
            ],
        }
        # cutoff dichiarato per lega = data massima della fixture (dedotta dai dati)
        fixture["cutoff"][league] = max(m["date"] for m in fixture["leagues"][league]["matches"])
        total += len(out)
        print(f"  {league:16s} n={len(out):5d} ingressi={len(records):3d}")
    fixture["total_matches"] = int(total)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(fixture, f, indent=1, ensure_ascii=False, sort_keys=False)
    print(f"scritta {out_path}")
    print(f"commit di produzione (reference): {prod_commit}")
    print(f"commit della logica S3:           {audit_commit}")
    print(f"partite totali: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
