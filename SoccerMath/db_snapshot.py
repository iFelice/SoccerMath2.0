"""Database point-in-time da git: "cosa vedeva l'app all'istante T".

Il replay walk-forward del Top Mix (``replay_legacy_topmix.py``) deve dare a
ogni partita SOLO i dati disponibili prima del suo kickoff. Il modo piu'
onesto di ricostruirli non e' filtrare i CSV di oggi per data (i CSV live non
hanno l'ora: una partita delle 18:45 e una delle 13:00 dello stesso giorno
sarebbero indistinguibili) ma prendere ``SoccerMath/database`` COM'ERA nel
commit di ``main`` in vigore a quell'istante: i commit "Auto-update live data"
sono pubblicati dal workflow ogni poche ore, e un commit con committer date
C < T non puo' contenere il risultato di una partita iniziata dopo T.

Questo modulo, senza checkout e senza toccare HEAD:

* trova l'ultimo commit di ``main`` con committer date < T (``main_head_at``);
* estrae la cartella dati di quel commit in una cartella temporanea
  (``git archive``): ``SoccerMath/database`` nel layout attuale, ``database``
  alla radice in quello storico (prima del riordino del 26/08/2026);
* opzionalmente scarta dai CSV le righe datate DOPO il giorno di T (dati
  anomali "dal futuro", p.es. una partita con data 21/10 e risultato gia'
  presente il 19/09: non e' il risultato che si sta predicendo, ma la regola
  e' "mai dati successivi al kickoff");
* punta ``config`` / ``scraper_xg`` / ``xg_archive`` / entrambi i motori Elo
  alla cartella estratta e svuota le loro cache; all'uscita ripristina tutto.

E' la stessa tecnica di ``audit/reconstruct_topmix_match.database_at_git_ref``,
qui in un modulo importabile dal codice applicativo e con in piu' la cache del
motore legacy e il filtro delle righe future.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
DATABASE_SUBDIR = "SoccerMath/database"

_PATH_KEYS = ("base_csv", "live_csv", "xg_json")


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------
def _git(args: List[str], repo_root: str = REPO_ROOT, check: bool = True) -> str:
    proc = subprocess.run(["git", "-C", repo_root, *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} fallito: {proc.stderr.strip()[:300]}")
    return proc.stdout


def resolve_main_ref(repo_root: str = REPO_ROOT,
                     candidates=("origin/main", "main", "HEAD")) -> str:
    """Primo ref risolvibile fra i candidati (in Actions il branch ha tutta la
    storia di main; ``origin/main`` c'e' con fetch-depth 0)."""
    for ref in candidates:
        proc = subprocess.run(["git", "-C", repo_root, "rev-parse", "--verify", "-q", ref],
                              capture_output=True, text=True)
        if proc.returncode == 0 and proc.stdout.strip():
            return ref
    raise RuntimeError("nessun ref git risolvibile fra %r" % (candidates,))


@dataclass
class CommitInfo:
    sha: str
    committer_time: datetime
    subject: str
    ref: str

    @property
    def short(self) -> str:
        return self.sha[:12]


def _parse_commit_line(line: str, ref: str) -> CommitInfo:
    sha, iso, subject = line.split("\x1f", 2)
    when = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    return CommitInfo(sha=sha, committer_time=when, subject=subject, ref=ref)


def main_head_at(instant: datetime, ref: Optional[str] = None,
                 repo_root: str = REPO_ROOT) -> CommitInfo:
    """Ultimo commit di ``ref`` con committer date STRETTAMENTE < ``instant``.

    Si cammina la storia ``--first-parent`` di ``main``: senza, ``git log``
    visiterebbe anche i commit dei branch mergiati DOPO l'istante (hanno date
    piu' vecchie della merge) e restituirebbe un albero che main non aveva
    ancora. ``--until`` e' inclusivo al secondo: si chiede fino a
    ``instant - 1s`` cosi' un commit pubblicato esattamente al kickoff resta
    fuori.
    """
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    ref = ref or resolve_main_ref(repo_root)
    limite = instant.astimezone(timezone.utc).replace(microsecond=0) - timedelta(seconds=1)
    out = _git(["log", "--first-parent", ref, f"--until={limite.isoformat()}", "-1",
                "--format=%H%x1f%cI%x1f%s"], repo_root).strip()
    if not out:
        raise RuntimeError(f"nessun commit su {ref} prima di {instant.isoformat()}")
    info = _parse_commit_line(out, ref)
    if not info.committer_time < instant:
        raise RuntimeError(f"commit {info.short} ({info.committer_time}) non precede {instant}")
    return info


def commit_info(sha_or_ref: str, repo_root: str = REPO_ROOT) -> CommitInfo:
    out = _git(["log", "-1", "--format=%H%x1f%cI%x1f%s", sha_or_ref], repo_root).strip()
    return _parse_commit_line(out, sha_or_ref)


# Il percorso dei dati e' cambiato una volta: fino al 26/08/2026 (riordino in
# ``SoccerMath/``) la cartella era ``database/`` alla RADICE del repo. Uno
# snapshot va letto da dove stava allora, altrimenti l'estrazione e' vuota e il
# motore non ha niente da leggere (e' il caso delle partite di agosto: vedi
# ``replay_legacy_topmix.WINDOW_NOTES``).
DATABASE_SUBDIRS = (DATABASE_SUBDIR, "database")


def database_prefix_at(sha: str, repo_root: str = REPO_ROOT) -> str:
    """Percorso della cartella dati NEL commit ``sha`` (layout nuovo o storico)."""
    for pref in DATABASE_SUBDIRS:
        proc = subprocess.run(["git", "-C", repo_root, "cat-file", "-e", f"{sha}:{pref}"],
                              capture_output=True)
        if proc.returncode == 0:
            return pref
    raise RuntimeError(f"commit {sha[:12]}: nessuna cartella dati fra {DATABASE_SUBDIRS}")


def extract_database_at(sha: str, dest: str, repo_root: str = REPO_ROOT) -> str:
    """``git archive`` della cartella dati al commit ``sha`` dentro ``dest``.

    Ritorna il percorso della cartella estratta: ``dest/SoccerMath/database``
    nel layout attuale, ``dest/database`` in quello storico.
    """
    dest = os.path.abspath(dest)
    os.makedirs(dest, exist_ok=True)
    pref = database_prefix_at(sha, repo_root)
    proc = subprocess.run(["git", "-C", repo_root, "archive", "--format=tar", sha, pref],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"git archive {sha} fallito: {proc.stderr.decode(errors='replace')[:300]}")
    with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:") as tar:
        try:
            tar.extractall(dest, filter="data")
        except TypeError:  # Python < 3.12 senza filtro
            tar.extractall(dest)
    db = os.path.join(dest, *pref.split("/"))
    if not os.path.isdir(db):
        raise RuntimeError(f"{pref} assente nel commit {sha}")
    return db


# ---------------------------------------------------------------------------
# filtro "mai dati successivi": righe CSV datate dopo il giorno del cutoff
# ---------------------------------------------------------------------------
def drop_future_dated_rows(db_dir: str, cutoff: datetime) -> Dict[str, int]:
    """Riscrive i CSV di ``db_dir`` senza le righe con Date > giorno UTC di ``cutoff``.

    Le righe del giorno stesso RESTANO: se sono nel commit (pubblicato prima
    del cutoff) erano davvero gia' concluse. Ritorna ``{file: righe_tolte}``
    per i soli file toccati.
    """
    import pandas as pd

    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    giorno = pd.Timestamp(cutoff.astimezone(timezone.utc).date())
    tolte: Dict[str, int] = {}
    for nome in sorted(os.listdir(db_dir)):
        if not nome.lower().endswith(".csv"):
            continue
        path = os.path.join(db_dir, nome)
        try:
            df = pd.read_csv(path, low_memory=False)
        except Exception:
            continue
        if "Date" not in df.columns or df.empty:
            continue
        date = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
        maschera = date.notna() & (date > giorno)
        n = int(maschera.sum())
        if n:
            df.loc[~maschera].to_csv(path, index=False)
            tolte[nome] = n
    return tolte


# ---------------------------------------------------------------------------
# redirezione dei moduli di produzione
# ---------------------------------------------------------------------------
def _snapshot_paths() -> Dict[str, Any]:
    import config
    import scraper_xg
    import xg_archive
    from models import elo_engine, elo_engine_legacy
    return {
        "config_DATABASE_DIR": config.DATABASE_DIR,
        "leagues": {name: {k: info.get(k) for k in _PATH_KEYS}
                    for name, info in config.LEAGUES_CONFIG.items()},
        "config_LEAGUE_FILE_MAP": dict(config.LEAGUE_FILE_MAP),
        "scraper_LEAGUE_FILE_MAP": dict(scraper_xg.LEAGUE_FILE_MAP),
        "xg_archive_DATABASE_DIR": xg_archive.DATABASE_DIR,
        "elo_DATABASE_DIR": elo_engine.DATABASE_DIR,
        "elo_legacy_DATABASE_DIR": elo_engine_legacy.DATABASE_DIR,
    }


def _redirect(new_db: str) -> None:
    import config
    import scraper_xg
    import xg_archive
    from models import elo_engine, elo_engine_legacy
    new_path = Path(new_db)
    config.DATABASE_DIR = new_path
    elo_engine.DATABASE_DIR = new_path
    elo_engine_legacy.DATABASE_DIR = new_path
    xg_archive.DATABASE_DIR = new_path
    for info in config.LEAGUES_CONFIG.values():
        for key in _PATH_KEYS:
            if info.get(key):
                info[key] = str(new_path / Path(str(info[key])).name)
    new_map = {name: info["xg_json"] for name, info in config.LEAGUES_CONFIG.items()}
    config.LEAGUE_FILE_MAP.clear()
    config.LEAGUE_FILE_MAP.update(new_map)
    scraper_xg.LEAGUE_FILE_MAP.clear()
    scraper_xg.LEAGUE_FILE_MAP.update(new_map)


def _restore(snap: Dict[str, Any]) -> None:
    import config
    import scraper_xg
    import xg_archive
    from models import elo_engine, elo_engine_legacy
    config.DATABASE_DIR = snap["config_DATABASE_DIR"]
    elo_engine.DATABASE_DIR = snap["elo_DATABASE_DIR"]
    elo_engine_legacy.DATABASE_DIR = snap["elo_legacy_DATABASE_DIR"]
    xg_archive.DATABASE_DIR = snap["xg_archive_DATABASE_DIR"]
    for name, paths in snap["leagues"].items():
        if name in config.LEAGUES_CONFIG:
            config.LEAGUES_CONFIG[name].update(paths)
    config.LEAGUE_FILE_MAP.clear()
    config.LEAGUE_FILE_MAP.update(snap["config_LEAGUE_FILE_MAP"])
    scraper_xg.LEAGUE_FILE_MAP.clear()
    scraper_xg.LEAGUE_FILE_MAP.update(snap["scraper_LEAGUE_FILE_MAP"])


def clear_engine_caches() -> None:
    """Svuota le cache che memorizzano dati del database: Poisson (st.cache_data
    di ``get_league_engine``) e i due motori Elo."""
    try:
        import app as _app
        _app.get_league_engine.clear()
    except Exception:
        pass
    try:
        from models import elo_engine
        elo_engine._ELO_ENGINES_CACHE.clear()
        elo_engine._ELO_ENGINES_STAMP.clear()
    except Exception:
        pass
    try:
        from models.legacy_elo import clear_legacy_elo_cache
        clear_legacy_elo_cache()
    except Exception:
        pass


@dataclass
class database_at_instant:
    """Context manager: database di ``main`` com'era all'istante ``instant``.

    Dentro il ``with`` le funzioni di produzione (``get_league_engine``,
    ``predict_elo_probs``, ``predict_elo_probs_legacy``, ``get_understat_xg``,
    ``season_point_in_time_averages``) leggono la cartella estratta.
    """
    instant: datetime
    ref: Optional[str] = None
    repo_root: str = REPO_ROOT
    drop_future_rows: bool = True
    cache_dir: Optional[str] = None      # riuso fra click che condividono commit + giorno
    commit: Optional[CommitInfo] = None
    db_dir: str = ""
    future_rows_dropped: Dict[str, int] = field(default_factory=dict)
    _tmp: str = ""
    _cached: bool = False
    _snap: Optional[Dict[str, Any]] = None

    def __enter__(self) -> "database_at_instant":
        self.commit = main_head_at(self.instant, self.ref, self.repo_root)
        if self.cache_dir:
            # Una giornata di partite condivide pochi commit: si estrae una
            # volta sola. La chiave comprende il GIORNO del cutoff, perche' le
            # righe post-datate scartate dipendono solo da quello.
            giorno = self.instant.astimezone(timezone.utc).date().isoformat()
            self._tmp = os.path.join(self.cache_dir, f"{self.commit.sha[:12]}-{giorno}")
            self._cached = os.path.isfile(os.path.join(self._tmp, _MARKER))
        else:
            self._tmp = tempfile.mkdtemp(prefix="sm_pit_db_")
        if self._cached:
            with open(os.path.join(self._tmp, _MARKER), encoding="utf-8") as f:
                meta = json.load(f)
            self.db_dir = os.path.join(self._tmp, meta["db_dir"])
            self.future_rows_dropped = {k: int(v) for k, v in (meta.get("dropped") or {}).items()}
        else:
            self.db_dir = extract_database_at(self.commit.sha, self._tmp, self.repo_root)
            if self.drop_future_rows:
                self.future_rows_dropped = drop_future_dated_rows(self.db_dir, self.instant)
            if self.cache_dir:
                with open(os.path.join(self._tmp, _MARKER), "w", encoding="utf-8") as f:
                    json.dump({"db_dir": os.path.relpath(self.db_dir, self._tmp),
                               "dropped": self.future_rows_dropped}, f)
        self._snap = _snapshot_paths()
        _redirect(self.db_dir)
        clear_engine_caches()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._snap is not None:
            _restore(self._snap)
        clear_engine_caches()
        if self._tmp and not self.cache_dir:
            shutil.rmtree(self._tmp, ignore_errors=True)
        return None


_MARKER = ".snapshot_meta.json"
