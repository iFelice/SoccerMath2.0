"""replay_legacy_topmix.py - Replay walk-forward, SENZA leakage, del Top Mix legacy.

Scopo (Commessa "Top Mix a due modelli", FASE 2): per ogni partita conclusa dal
giorno della merge di PR#24 (2026-09-18) a oggi, rifare il click "Calcola Top
Mix" come se fosse stato fatto UN SECONDO PRIMA DEL KICKOFF di quella partita,
con il motore Elo legacy (pre-PR#24, ``models/elo_engine_legacy.py``), e
scrivere nel Registro le righe che quel click avrebbe scritto: stessa forma
delle righe live (``build_prediction_entry``), ``model_variant = "legacy"``,
nessuna etichetta "ricostruita", nessuna riga esistente toccata.

Regola ferrea: la partita replicata puo' vedere SOLO dati disponibili PRIMA del
suo kickoff. Come viene garantito (ogni voce e' verificata e riportata):

1. **Database point-in-time da git** (``db_snapshot.database_at_instant``):
   per l'istante T = kickoff - 1 s si estrae ``SoccerMath/database`` dall'ultimo
   commit di ``main`` con committer date STRETTAMENTE < T. Il repo e' l'unico
   log storico dei CSV/xG che il modello legge: cio' che non era ancora
   committato non poteva essere letto da nessun click reale.
2. **Righe post-datate scartate**: i CSV live contengono a volte righe con data
   futura gia' "giocata" (es. una riga 21/10/2026 con risultato); ogni riga con
   Date > giorno UTC di T viene tolta dallo snapshot e conteggiata.
3. **Cutoff xG = T**: ``season_point_in_time_averages`` viene chiamata con
   ``cutoff=T`` (in produzione il cutoff e' ``datetime.now``, cioe' il click).
4. **Pool di fixture = solo partite con kickoff > T**, poi la STESSA
   ``select_next_matchday_matches(pool, now=T)`` della produzione.
5. **Autoverifica per ogni click**: commit < T; la partita bersaglio NON
   compare con risultato ne' nel CSV live ne' nell'archivio xG dello snapshot;
   il cutoff xG effettivamente usato e' T. Un fallimento blocca la scrittura.

Il calcolo per partita e' la funzione di produzione ``app.calcola_righe_top_mix``
(Poisson + selettore + i DUE Elo) e l'ordinamento ``app.classifica_top_mix``:
le righe ricostruite nascono dallo stesso codice di quelle live. La riga del
registro e' costruita da ``app.argomenti_registro_top_mix`` +
``app.build_prediction_entry`` (stessi argomenti del tab2), poi graduata con
``esito_mercato`` sul risultato finale (stesso grading di
``aggiorna_risultati_reali``). Per ogni click si persistono SOLO le righe
legacy della/e partita/e il cui kickoff e' T + 1 s: le altre partite del turno
vengono replicate al LORO kickoff, con il LORO snapshot.

Sorgenti delle fixture (``--fixtures``):

* ``api``  -> football-data.org (``FOOTBALL_DATA_API_KEY``): id partita,
  ``utcDate`` esatto, ``shortName`` identici a quelli del click live. E' la
  sorgente AUTOREVOLE; l'unica ammessa con ``--write``.
* ``csv``  -> offline: risultati dai ``*_Live.csv`` correnti + calendario
  (data/ora UTC) dall'archivio Understat ``xG archivio <lega>.json``. Serve a
  validare la meccanica dove non c'e' rete; id sintetici negativi
  (``-understat_id``), nomi CSV al posto degli shortName API: MAI ``--write``.

Modalita': default dry-run (referto markdown + JSON delle righe candidate in
``--out``). ``--write`` usa ``save_predictions`` di produzione ma con un
caricamento STRETTO del registro: se JSONBin e' configurato il GET deve
rispondere 200 (``load_predictions`` ricade in silenzio sul file locale, e un
PUT da quel fallback tronca il registro remoto), la lista fusa non puo' essere
piu' corta di quella caricata, OGNI riga preesistente deve ritrovarsi
identica, e l'esito remoto del PUT deve essere ``ok``.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import zlib
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# ``import app`` esegue lo script Streamlit in "bare mode": i suoi avvisi non
# servono a nessuno qui.
logging.getLogger("streamlit").setLevel(logging.ERROR)
for _nome in ("streamlit.runtime.caching", "streamlit.runtime.scriptrunner_utils",
              "streamlit.runtime.state", "streamlit.runtime.caching.cache_data_api"):
    logging.getLogger(_nome).setLevel(logging.ERROR)

from db_snapshot import REPO_ROOT, CommitInfo, database_at_instant, resolve_main_ref  # noqa: E402
from config import season_start_year  # noqa: E402
from registry_coverage import VARIANTI, coverage_by_variant, render_coverage, row_day  # noqa: E402
from prediction_registry import (  # noqa: E402
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_LABELS,
    MODEL_VARIANT_FIELD,
    MODEL_VARIANT_LEGACY,
    ORIGIN_TOP_MIX,
    dedup_key,
    esito_mercato,
    model_variant_of,
    origin_of,
    upsert_prediction_entry,
)

UTC = timezone.utc
# Merge di PR#24 in main. E' il confine fra le due commesse: PRIMA il modello
# legacy era quello live (e il Registro ha righe legacy), DOPO il modello
# attuale e' quello live (e il Registro ha righe attuali). Le due finestre
# [REPLAY_START_INSTANT, PR24_MERGE_INSTANT) e [PR24_MERGE_INSTANT, adesso)
# partizionano la storia ricostruibile: nessuna partita sta in entrambe.
PR24_MERGE_INSTANT = datetime(2026, 9, 18, 21, 51, 58, tzinfo=timezone.utc)
PR24_MERGE_DAY = PR24_MERGE_INSTANT.date()
SEASON_FIRST_DAY = date(2026, 8, 15)        # prima partita della stagione 2026/27 (dall'archivio)
# Primo istante da cui il replay e' ONESTO, misurato sul repo (non stimato):
# la stagione 2026/27 entra nei CSV live di main col commit 48e7768 del
# 2026-08-30T11:27:06Z. Prima di allora la cartella dati in git descrive la
# stagione PRECEDENTE (ultima riga 31/01/2026, e fino al 26/08/2026 sta pure
# nel vecchio percorso ``database/``): un "replay" di quelle partite darebbe al
# modello un database vecchio di un anno, cioe' non il modello che era live.
# La guardia ``snapshot_covers_season`` (per click e per lega) lo verifica
# comunque sui fatti, quindi la finestra non dipende da questa costante.
REPLAY_START_DAY = date(2026, 8, 30)        # = giorno UTC del commit 48e7768
REPLAY_START_INSTANT = datetime(2026, 8, 30, 11, 27, 6, tzinfo=timezone.utc)   # committer date di 48e7768
API_PAUSE_SECONDS = 6.5                     # 10 richieste/min sul piano free di football-data.org
ISO_Z = "%Y-%m-%dT%H:%M:%SZ"


class ReplayError(RuntimeError):
    """Errore che deve fermare il replay (leak rilevato, registro non affidabile)."""


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------
@dataclass
class Fixture:
    """Una partita come la vede il Top Mix: kickoff UTC, giornata, nomi grezzi."""
    league: str
    match_id: Any
    utc: datetime                     # kickoff, timezone-aware UTC
    matchday: Optional[int]
    home: str                         # nome GREZZO (shortName API / nome CSV offline)
    away: str
    status: str                       # FINISHED / TIMED / SCHEDULED / ...
    gh: Optional[int] = None
    ga: Optional[int] = None
    kickoff_source: str = "api"       # api | understat | csv_date_midnight
    matchday_inferred: bool = False

    @property
    def finished(self) -> bool:
        return self.status == "FINISHED" and self.gh is not None and self.ga is not None

    def as_api_match(self) -> Dict[str, Any]:
        """Forma consumata da ``select_next_matchday_matches`` e ``calcola_righe_top_mix``."""
        return {
            "id": self.match_id,
            "utcDate": self.utc.astimezone(UTC).strftime(ISO_Z),
            "matchday": self.matchday,
            "status": self.status,
            "homeTeam": {"shortName": self.home},
            "awayTeam": {"shortName": self.away},
        }


def _midnight_utc(giorno: date) -> datetime:
    return datetime(giorno.year, giorno.month, giorno.day, tzinfo=UTC)


def _int_or_none(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        f = float(v)
        if f != f:                      # NaN
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


def _dedup_fixtures(fixtures: List[Fixture]) -> List[Fixture]:
    """Una sola voce per partita (stesso ``match_id``), ordinate per kickoff.

    L'API puo' restituire la stessa partita piu' di una volta (fasi diverse
    della competizione, stagioni adiacenti): senza dedup il click la
    replicherebbe piu' volte e il referto mostrerebbe bersagli ripetuti.
    """
    viste: Dict[Any, Fixture] = {}
    for f in fixtures:
        chiave = f.match_id if f.match_id is not None else (f.league, f.utc, f.home, f.away)
        precedente = viste.get(chiave)
        if precedente is None or (f.finished and not precedente.finished):
            viste[chiave] = f
    return sorted(viste.values(), key=lambda f: f.utc)


def _get_con_ritentativi(getter: Callable[..., Any], url: str, *, headers: Dict[str, str],
                         timeout: int, tentativi: int, pausa: float,
                         dormi: Callable[[float], None] = time.sleep) -> Any:
    """GET con ritentativi sui soli errori transitori (429 rate-limit, 5xx).

    Il piano free di football-data.org risponde 429 appena si susseguono piu'
    run ravvicinati: senza ritentativo la CI falliva con "HTTP 429" e nessun
    referto, cioe' un guasto di rete travestito da errore del replay. Si
    rispetta ``Retry-After`` se c'e', altrimenti si allunga l'attesa.
    """
    ultima = None
    for n in range(max(1, tentativi)):
        ultima = getter(url, headers=headers, timeout=timeout)
        if getattr(ultima, "status_code", None) not in (429, 500, 502, 503, 504):
            return ultima
        if n + 1 >= max(1, tentativi):
            return ultima
        attesa = pausa * (n + 1)
        dopo = None
        try:
            dopo = (getattr(ultima, "headers", {}) or {}).get("Retry-After")
        except Exception:                                     # pragma: no cover - headers strani
            dopo = None
        try:
            if dopo:
                attesa = max(attesa, float(dopo))
        except (TypeError, ValueError):
            pass
        dormi(attesa)
    return ultima


def fixtures_from_api(api_key: str, leagues: Optional[Iterable[str]] = None, *,
                      http_get: Optional[Callable[..., Any]] = None,
                      pause: float = API_PAUSE_SECONDS,
                      tentativi: int = 4, dormi: Callable[[float], None] = time.sleep,
                      ) -> Dict[str, List[Fixture]]:
    """Tutte le partite di stagione per lega da football-data.org (1 GET per lega).

    Le leghe sono quelle di ``LEAGUES_CONFIG`` e NON le chiavi di
    ``LEAGUE_CODE_MAP``: quella mappa contiene anche gli alias ``short_name``
    ("SerieA", "Premier", "LaLiga", "Ligue1"), per cui iterarla scaricava ogni
    campionato DUE volte (9 GET invece di 5, con il rischio di rate-limit) e
    produceva fixture duplicate e con un nome di lega che non esiste in
    ``LEAGUES_CONFIG`` (KeyError nel controllo di leakage).
    """
    import requests
    from config import LEAGUE_CODE_MAP, LEAGUES_CONFIG
    if not api_key:
        raise ReplayError("FOOTBALL_DATA_API_KEY assente: --fixtures api non possibile")
    getter = http_get or requests.get
    out: Dict[str, List[Fixture]] = {}
    leghe = [l for l in (leagues or LEAGUES_CONFIG.keys()) if l in LEAGUE_CODE_MAP]
    for i, league in enumerate(leghe):
        if i:
            time.sleep(pause)
        r = _get_con_ritentativi(
            getter, f"https://api.football-data.org/v4/competitions/{LEAGUE_CODE_MAP[league]}/matches",
            headers={"X-Auth-Token": api_key}, timeout=30,
            tentativi=tentativi, pausa=max(API_PAUSE_SECONDS, pause), dormi=dormi)
        if r.status_code != 200:
            raise ReplayError(f"football-data.org {league}: HTTP {r.status_code}")
        fx: List[Fixture] = []
        for m in r.json().get("matches", []) or []:
            try:
                dt = datetime.fromisoformat(str(m.get("utcDate")).replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            score = ((m.get("score") or {}).get("fullTime") or {})
            home = (m.get("homeTeam") or {})
            away = (m.get("awayTeam") or {})
            fx.append(Fixture(
                league=league, match_id=m.get("id"), utc=dt.astimezone(UTC),
                matchday=m.get("matchday") if isinstance(m.get("matchday"), int) else None,
                home=home.get("shortName") or home.get("name", "?"),
                away=away.get("shortName") or away.get("name", "?"),
                status=str(m.get("status") or ""),
                gh=_int_or_none(score.get("home")), ga=_int_or_none(score.get("away")),
                kickoff_source="api"))
        out[league] = _dedup_fixtures(fx)
    return out


def fixtures_from_csv_and_archive(leagues: Optional[Iterable[str]] = None,
                                  db_dir: Optional[str] = None) -> Dict[str, List[Fixture]]:
    """Offline: risultati dai ``*_Live.csv`` correnti, calendario dall'archivio Understat.

    Il CSV ha solo la data (colonna ``Time`` vuota): l'ora UTC del kickoff viene
    dal record Understat della stessa coppia di squadre; se le due date non
    coincidono (calendario Understat con orario segnaposto, anticipi) si usa la
    mezzanotte UTC del giorno CSV, che e' PIU' conservativa (istante anteriore)
    e viene marcata ``csv_date_midnight``. Le partite non ancora nel CSV
    entrano nel pool con la giornata dedotta dalle righe CSV a +-3 giorni
    (marcate ``matchday_inferred``) o restano fuori se ambigua.
    """
    import pandas as pd
    from config import LEAGUES_CONFIG, clean_name
    from team_aliases import UNDERSTAT_NAME_MAP
    from xg_archive import archive_path

    out: Dict[str, List[Fixture]] = {}
    for league in list(leagues or LEAGUES_CONFIG.keys()):
        info = LEAGUES_CONFIG[league]
        live_csv = os.path.join(db_dir, os.path.basename(str(info["live_csv"]))) if db_dir else str(info["live_csv"])
        arch_file = archive_path(league, base_dir=db_dir) if db_dir else archive_path(league)
        df = pd.read_csv(live_csv, low_memory=False) if os.path.exists(live_csv) else pd.DataFrame()
        with open(arch_file, encoding="utf-8") as f:
            arch = json.load(f)
        stagione = max((int(r.get("season") or 0) for r in arch), default=0)
        idx: Dict[Tuple[str, str], List[Tuple[datetime, Dict[str, Any]]]] = {}
        for r in arch:
            if int(r.get("season") or 0) != stagione:
                continue
            try:
                d = datetime.strptime(str(r["date"]), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            except (KeyError, ValueError):
                continue
            ch = clean_name(UNDERSTAT_NAME_MAP.get(r["home_team"], r["home_team"]))
            ca = clean_name(UNDERSTAT_NAME_MAP.get(r["away_team"], r["away_team"]))
            idx.setdefault((ch, ca), []).append((d, r))

        fixtures: List[Fixture] = []
        used: set = set()
        md_by_date: List[Tuple[date, int]] = []
        for _, row in df.iterrows():
            try:
                giorno = datetime.strptime(str(row["Date"]), "%d/%m/%Y").date()
            except ValueError:
                continue
            ch, ca = clean_name(str(row["HomeTeam"])), clean_name(str(row["AwayTeam"]))
            matchday = _int_or_none(row.get("Matchday"))
            if matchday is not None:
                md_by_date.append((giorno, matchday))
            cands = [(d, r) for d, r in idx.get((ch, ca), []) if abs((d.date() - giorno).days) <= 1]
            if cands:
                d, r = min(cands, key=lambda x: abs((x[0].date() - giorno).days))
                used.add(r["id"])
                mid = -int(r["id"])
                if d.date() == giorno:
                    utc, src = d, "understat"
                else:
                    utc, src = _midnight_utc(giorno), "csv_date_midnight"
            else:
                mid = -(10 ** 9 + zlib.crc32(f"{league}|{giorno}|{ch}|{ca}".encode("utf-8")) % 10 ** 8)
                utc, src = _midnight_utc(giorno), "csv_date_midnight"
            gh, ga = _int_or_none(row.get("FTHG")), _int_or_none(row.get("FTAG"))
            fixtures.append(Fixture(
                league=league, match_id=mid, utc=utc, matchday=matchday,
                home=str(row["HomeTeam"]), away=str(row["AwayTeam"]),
                status="FINISHED" if (gh is not None and ga is not None) else "TIMED",
                gh=gh, ga=ga, kickoff_source=src))
        for (ch, ca), lst in idx.items():
            for d, r in lst:
                if r["id"] in used:
                    continue
                vicine = {md for gg, md in md_by_date if abs((gg - d.date()).days) <= 3}
                md = vicine.pop() if len(vicine) == 1 else None
                gh, ga = (_int_or_none(r.get("home_goals")), _int_or_none(r.get("away_goals"))) \
                    if r.get("is_result") else (None, None)
                fixtures.append(Fixture(
                    league=league, match_id=-int(r["id"]), utc=d, matchday=md,
                    home=UNDERSTAT_NAME_MAP.get(r["home_team"], r["home_team"]),
                    away=UNDERSTAT_NAME_MAP.get(r["away_team"], r["away_team"]),
                    status="FINISHED" if r.get("is_result") else "TIMED",
                    gh=gh, ga=ga, kickoff_source="understat", matchday_inferred=md is not None))
        out[league] = _dedup_fixtures(fixtures)
    return out


def target_fixtures(fixtures: Dict[str, List[Fixture]], day_from: date, day_to: date,
                    da_istante: Optional[datetime] = None,
                    a_istante: Optional[datetime] = None) -> List[Fixture]:
    """Partite CONCLUSE con kickoff nella finestra.

    Giorni ``[day_from, day_to]``; se sono dati ``da_istante``/``a_istante`` il
    confine e' l'ISTANTE (semintervallo ``[da_istante, a_istante)``), che e'
    quello che serve per partizionare esattamente su un merge git: con i soli
    giorni le partite del giorno del merge finirebbero in entrambe le commesse.
    """
    out = [f for lst in fixtures.values() for f in lst
           if f.finished and day_from <= f.utc.astimezone(UTC).date() <= day_to]
    if da_istante is not None:
        out = [f for f in out if f.utc >= da_istante]
    if a_istante is not None:
        out = [f for f in out if f.utc < a_istante]
    return sorted(out, key=lambda f: (f.utc, f.league, str(f.match_id)))


# ---------------------------------------------------------------------------
# Un click simulato all'istante T
# ---------------------------------------------------------------------------
@dataclass
class LeakCheck:
    """Prove di assenza di leakage di UN click: tutte devono essere True.

    ``snapshot_covers_season`` non e' una prova di leakage ma il complemento
    necessario: uno snapshot VECCHIO non fa trapelare nulla ma descrive un
    altro campionato (nel repo le partite di agosto 2026 hanno in git la
    stagione 2025/26), e replicarle sarebbe un numero inventato. Un click e'
    scrivibile solo se ``ok`` e ``snapshot_covers_season``.
    """
    commit_before_instant: bool
    targets_absent_from_live_csv: bool
    targets_absent_from_xg_archive: bool
    xg_cutoff_is_instant: bool
    snapshot_covers_season: bool = True
    future_rows_dropped: Dict[str, int] = field(default_factory=dict)
    dettagli: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (self.commit_before_instant and self.targets_absent_from_live_csv
                and self.targets_absent_from_xg_archive and self.xg_cutoff_is_instant)

    @property
    def scrivibile(self) -> bool:
        return self.ok and self.snapshot_covers_season


@dataclass
class ClickResult:
    instant: datetime
    commit: CommitInfo
    snapshot_sha: str
    pool_sizes: Dict[str, int]
    selected: Dict[str, int]
    rows: Dict[str, List[Dict[str, Any]]]     # variante -> righe classificate (tutte, nessun tetto)
    missing: List[str]
    leak: LeakCheck
    targets: List[Fixture]
    fuori_stagione: List[str] = field(default_factory=list)   # leghe con snapshot non della stagione
    archivio_xg: Dict[str, bool] = field(default_factory=dict)  # lega -> archivio xG presente nello snapshot

    @property
    def scrivibile(self) -> bool:
        return self.leak.scrivibile


def _csv_has_result(path: str, home_clean: str, away_clean: str, giorno: date, clean_name) -> bool:
    import pandas as pd
    if not os.path.exists(path):
        return False
    df = pd.read_csv(path, low_memory=False, usecols=lambda c: c in ("Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"))
    if df.empty:
        return False
    for _, row in df.iterrows():
        if clean_name(str(row["HomeTeam"])) != home_clean or clean_name(str(row["AwayTeam"])) != away_clean:
            continue
        try:
            gg = datetime.strptime(str(row["Date"]), "%d/%m/%Y").date()
        except ValueError:
            continue
        if abs((gg - giorno).days) <= 1:
            return True
    return False


def _archive_has_result(path: str, home_clean: str, away_clean: str, giorno: date, clean_name, umap) -> bool:
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        arch = json.load(f)
    for r in arch:
        if not r.get("is_result"):
            continue
        ch = clean_name(umap.get(r.get("home_team"), r.get("home_team")))
        ca = clean_name(umap.get(r.get("away_team"), r.get("away_team")))
        if ch != home_clean or ca != away_clean:
            continue
        try:
            gg = datetime.strptime(str(r["date"]), "%Y-%m-%d %H:%M:%S").date()
        except (KeyError, ValueError):
            continue
        if abs((gg - giorno).days) <= 1:
            return True
    return False


def live_csv_covers_season(db_dir: str, league: str, season_start: int) -> bool:
    """Lo snapshot contiene la stagione ``season_start`` (almeno una riga)?

    Un CSV live che si ferma alla stagione precedente non e' un dato "vecchio
    ma lecito": e' un ALTRO campionato. Le colonne usate sono le stesse del
    motore (``Date`` in formato gg/mm/aaaa).
    """
    import pandas as pd
    from config import LEAGUES_CONFIG
    info = LEAGUES_CONFIG.get(league)
    if not info:
        return False
    path = os.path.join(db_dir, os.path.basename(str(info["live_csv"])))
    if not os.path.exists(path):
        return False
    try:
        df = pd.read_csv(path, low_memory=False, usecols=lambda c: c in ("Date",))
    except Exception:
        return False
    if df.empty or "Date" not in df.columns:
        return False
    # NB: la variabile NON si chiama `date`, altrimenti oscura la classe `date`
    # del modulo e `date(season_start, 7, 1)` diventa una Series (TypeError).
    giorni = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    inizio = pd.Timestamp(datetime(season_start, 7, 1, tzinfo=UTC))
    return bool((giorni.dt.tz_localize(UTC, ambiguous="NaT", nonexistent="NaT") >= inizio).any())


def simulate_click(instant: datetime, fixtures: Dict[str, List[Fixture]], *,
                   targets: Optional[List[Fixture]] = None,
                   leagues: Optional[Iterable[str]] = None,
                   ref: Optional[str] = None, repo_root: str = REPO_ROOT,
                   snapshot_cache: Optional[str] = None,
                   snapshot_factory: Callable[..., Any] = database_at_instant) -> ClickResult:
    """Il click "Calcola Top Mix" all'istante ``instant`` con i soli dati di allora."""
    import app
    from config import LEAGUES_CONFIG, clean_name
    from team_aliases import UNDERSTAT_NAME_MAP
    from xg_archive import archive_path

    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    leghe = list(leagues or LEAGUES_CONFIG.keys())
    targets = list(targets or [])
    cutoffs: List[Any] = []
    originale = app.season_point_in_time_averages

    def _point_in_time(league, cutoff=None, **kw):
        # In produzione cutoff = datetime.now(utc) (l'istante del click).
        cutoffs.append(instant)
        return originale(league, cutoff=instant, **kw)

    with snapshot_factory(instant, ref=ref, repo_root=repo_root, cache_dir=snapshot_cache) as snap:
        app.season_point_in_time_averages = _point_in_time
        try:
            per_variante: Dict[str, List[Dict[str, Any]]] = {MODEL_VARIANT_CURRENT: [], MODEL_VARIANT_LEGACY: []}
            pool_sizes: Dict[str, int] = {}
            selected: Dict[str, int] = {}
            missing: List[str] = []
            fuori_stagione: List[str] = []
            stagione = season_start_year(instant.astimezone(UTC).year, instant.astimezone(UTC).month)
            for league in leghe:
                # Prima di tutto: la cartella dati dello snapshot parla di QUESTA
                # stagione? Se no, si salta la lega (nessuna riga inventata).
                if not live_csv_covers_season(snap.db_dir, league, stagione):
                    fuori_stagione.append(league)
                    pool_sizes[league] = 0
                    continue
                pool = [f.as_api_match() for f in fixtures.get(league, []) if f.utc > instant]
                pool_sizes[league] = len(pool)
                engine = app.get_league_engine(league)
                if not engine:
                    missing.append(league)
                    continue
                matches = app.select_next_matchday_matches(pool, now=instant)
                selected[league] = len(matches)
                righe = app.calcola_righe_top_mix(league, matches, engine)
                for variante, lista in righe.items():
                    per_variante[variante].extend(lista)
            rows = {v: app.classifica_top_mix(lst) for v, lst in per_variante.items()}
        finally:
            app.season_point_in_time_averages = originale

        # --- autoverifica dentro lo snapshot ---
        dettagli: List[str] = []
        commit_ok = snap.commit.committer_time < instant
        if not commit_ok:
            dettagli.append(f"commit {snap.commit.short} {snap.commit.committer_time.isoformat()} NON precede {instant.isoformat()}")
        csv_ok = arch_ok = True
        for t in targets:
            info = LEAGUES_CONFIG[t.league]
            hc, ac = clean_name(t.home), clean_name(t.away)
            giorno = t.utc.astimezone(UTC).date()
            live_path = os.path.join(snap.db_dir, os.path.basename(str(info["live_csv"])))
            if _csv_has_result(live_path, hc, ac, giorno, clean_name):
                csv_ok = False
                dettagli.append(f"LEAK CSV: {t.home}-{t.away} ({t.league}) presente in {os.path.basename(live_path)} dello snapshot")
            if _archive_has_result(archive_path(t.league, base_dir=snap.db_dir), hc, ac, giorno, clean_name, UNDERSTAT_NAME_MAP):
                arch_ok = False
                dettagli.append(f"LEAK xG: {t.home}-{t.away} ({t.league}) con risultato nell'archivio xG dello snapshot")
        cutoff_ok = bool(cutoffs) and all(c == instant for c in cutoffs)
        if not cutoffs:
            dettagli.append("season_point_in_time_averages mai chiamata (nessuna lega calcolata?)")
        stagione_ok = not fuori_stagione
        if fuori_stagione:
            dettagli.append("snapshot NON della stagione " + str(stagione) + " per: " + ", ".join(fuori_stagione)
                            + " (in git la cartella dati descrive un'altra stagione: righe non scritte)")
        leak = LeakCheck(commit_ok, csv_ok, arch_ok, cutoff_ok, stagione_ok,
                         dict(snap.future_rows_dropped), dettagli)
        # Presenza dell'archivio xG nello snapshot: non e' un leakage, e' un
        # dato in meno che il modello di allora non aveva (in git l'archivio
        # arriva il 01/09). Si dichiara, come la finestra.
        archivio: Dict[str, bool] = {}
        for lega in {t.league for t in targets} | set(leghe):
            archivio[lega] = os.path.exists(archive_path(lega, base_dir=snap.db_dir))
        return ClickResult(instant=instant, commit=snap.commit, snapshot_sha=snap.commit.short,
                           pool_sizes=pool_sizes, selected=selected, rows=rows, missing=missing,
                           leak=leak, targets=targets, fuori_stagione=fuori_stagione, archivio_xg=archivio)


# ---------------------------------------------------------------------------
# Dalle righe del click alle righe del registro
# ---------------------------------------------------------------------------
def entries_for_targets(click: ClickResult, variant: str = MODEL_VARIANT_LEGACY) -> List[Dict[str, Any]]:
    """Righe del registro (gia' graduate) per le SOLE partite bersaglio del click.

    Stessa catena del tab2: ``argomenti_registro_top_mix`` ->
    ``build_prediction_entry`` (``snapshot_sha`` = commit dello snapshot,
    ``salvato_il`` = istante del click in ora italiana) -> grading con
    ``esito_mercato`` come ``aggiorna_risultati_reali``.
    """
    import app
    per_id = {str(t.match_id): t for t in click.targets}
    salvato_il = click.instant.astimezone(app.ITALY_TZ).strftime("%d/%m/%Y %H:%M")
    out: List[Dict[str, Any]] = []
    for p in click.rows.get(variant, []):
        t = per_id.get(str(p.get("match_id")))
        if t is None or not p.get("match_id"):
            continue
        args, kwargs = app.argomenti_registro_top_mix(p, model_variant=variant)
        entry = app.build_prediction_entry(*args, **kwargs, snapshot_sha=click.snapshot_sha,
                                           salvato_il=salvato_il)
        if t.gh is not None and t.ga is not None:
            entry["risultato_reale"] = f"{t.gh}-{t.ga}"
            entry["esito"] = esito_mercato(entry.get("mercato_standard", ""), t.gh, t.ga) or "⏳"
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Registro: caricamento stretto, fusione senza sovrascritture, scrittura
# ---------------------------------------------------------------------------
def strict_load_registry() -> Tuple[List[Dict[str, Any]], str]:
    """Carica il registro SENZA fallback silenziosi. Ritorna ``(righe, fonte)``.

    ``app.load_predictions`` ricade sul file locale se il GET remoto fallisce:
    per una LETTURA va bene, ma prima di un PUT che riscrive tutto il bin
    significherebbe sostituire il registro remoto con una copia locale magari
    vuota o vecchia. Qui il GET remoto deve rispondere 200 e avere la forma
    attesa, altrimenti si alza ``ReplayError``.
    """
    from config import PREDICTIONS_FILE
    from registry_store import RegistryStoreError, load_rows
    try:
        righe, fonte = load_rows(strict=True)
    except RegistryStoreError as e:
        raise ReplayError(f"registro remoto non leggibile: {e}") from e
    if fonte != "nessuno" and righe is not None:
        return righe, fonte
    if os.path.exists(PREDICTIONS_FILE):
        with open(PREDICTIONS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return data["data"], "locale"
        if isinstance(data, list):
            return data, "locale"
        raise ReplayError("registro locale in forma inattesa")
    return [], "locale"


def _canon(entry: Dict[str, Any]) -> str:
    return json.dumps(entry, sort_keys=True, ensure_ascii=False, default=str)


def merge_entries(existing: List[Dict[str, Any]], entries: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Counter]:
    """Aggiunge al registro le righe del replay SENZA toccare nulla di esistente.

    - solo righe con variante esplicita (``current`` o ``legacy``: il replay
      scrive per entrambi i modelli) e origine Top Mix: qualunque altra cosa e'
      un bug e ferma la scrittura;
    - una riga la cui chiave (``dedup_key``) esiste gia' viene SALTATA, non
      aggiornata (idempotenza: rilanciare il replay non modifica nulla, e una
      riga del modello attuale scritta da un click vero NON viene riscritta da
      una riga ricostruita);
    - a fusione fatta OGNI riga preesistente deve essere ancora li', identica.
    """
    for e in entries:
        variante = model_variant_of(e)
        if variante not in VARIANTI:
            raise ReplayError(f"riga senza variante valida nel replay: {e.get('home')}-{e.get('away')} {e.get(MODEL_VARIANT_FIELD)!r}")
        if origin_of(e) != ORIGIN_TOP_MIX:
            raise ReplayError(f"riga con origine inattesa nel replay: {origin_of(e)!r}")
    prima = [_canon(p) for p in existing]
    chiavi = {dedup_key(p) for p in existing}
    merged = copy.deepcopy(list(existing))
    azioni: Counter = Counter()
    for e in entries:
        if dedup_key(e) in chiavi:
            azioni["gia_presente"] += 1
            continue
        merged, az = upsert_prediction_entry(merged, e)
        azioni[az] += 1
        chiavi.add(dedup_key(e))
    if len(merged) < len(existing):
        raise ReplayError("la fusione ha ACCORCIATO il registro: scrittura rifiutata")
    dopo = Counter(_canon(p) for p in merged)
    for c in prima:
        if dopo[c] <= 0:
            raise ReplayError("una riga preesistente e' cambiata o sparita durante la fusione: scrittura rifiutata")
        dopo[c] -= 1
    if len(merged) != len(existing) + azioni["aggiunta"] + azioni["senza_chiave"]:
        raise ReplayError("conteggio righe incoerente dopo la fusione: scrittura rifiutata")
    return merged, azioni


def scrittura_fallita(esito: Dict[str, Any]) -> bool:
    """True se con ``--write`` il Registro NON e' stato scritto e non e' vero
    che non ci fosse nulla da aggiungere.

    Un errore silenzioso qui farebbe credere scritto un Registro che non lo e'
    (fusione mai avvenuta, PUT remoto fallito, Registro remoto vuoto).
    """
    if esito.get("scritto"):
        return False
    return esito.get("azioni", {}).get("aggiunta") != 0


def write_to_registry(entries: List[Dict[str, Any]], *, dry_run: bool = True) -> Dict[str, Any]:
    """Fusione + (se non dry-run) scrittura con ``app.save_predictions``.

    ``entries`` puo' contenere righe del modello attuale E del legacy: la
    fusione aggiunge solo chiavi nuove, quindi le righe scritte dai click veri
    restano intatte.
    """
    import app
    import registry_store
    existing, fonte = strict_load_registry()
    # Il backend remoto e' "configurato" se e' quello attivo: con JSONBin servono
    # chiave e bin, con Upstash URL e token. In entrambi i casi un registro
    # remoto VUOTO fa rifiutare la scrittura (mai scrivere sopra il nulla).
    remoto_configurato = fonte in (registry_store.BACKEND_JSONBIN, registry_store.BACKEND_UPSTASH)
    if remoto_configurato and not existing:
        raise ReplayError("registro remoto configurato ma VUOTO: mi rifiuto di scrivere sopra")
    merged, azioni = merge_entries(existing, entries)
    esito: Dict[str, Any] = {"fonte": fonte, "righe_prima": len(existing), "righe_dopo": len(merged),
                             "azioni": dict(azioni), "scritto": False, "remoto": "n/d"}
    if dry_run or not azioni["aggiunta"]:
        return esito
    esito["byte_payload"] = len(json.dumps({"data": merged}, ensure_ascii=False).encode("utf-8"))
    r = app.save_predictions(merged)
    esito["scritto"] = bool(r.get("locale"))
    esito["remoto"] = r.get("remoto")
    if remoto_configurato and r.get("remoto") != "ok":
        raise ReplayError(f"PUT remoto non riuscito: {r} (payload {esito['byte_payload']} byte, "
                          f"fusione {len(merged)} righe)")
    return esito


def _prima_di_pr24(riga: Dict[str, Any]) -> bool:
    """True se la riga del registro descrive una partita giocata PRIMA di PR#24.

    Prima di quel merge il motore live era quello vecchio: la riga e' quindi
    un'uscita del modello legacy, qualunque cosa dica il suo campo variante
    (assente nei record storici, dove vale "current"). Il giorno della partita
    si legge da ``kickoff_utc`` (autorevole) o da ``data`` italiana.
    """
    ko = riga.get("kickoff_utc")
    if isinstance(ko, str) and ko.strip():
        try:
            d = datetime.fromisoformat(ko.strip().replace("Z", "+00:00"))
            return (d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)) < PR24_MERGE_INSTANT
        except ValueError:
            pass
    giorno = row_day(riga)                      # da kickoff_utc o da 'data' italiana
    if giorno is None:
        return False
    return giorno < PR24_MERGE_INSTANT.date()


def compare_with_registry(existing: List[Dict[str, Any]], clicks: List[ClickResult]) -> List[Dict[str, Any]]:
    """Fedelta' del replay: riga ricostruita vs riga GIA' nel registro, per VARIANTE.

    Per ogni partita bersaglio che ha nel registro una riga Top Mix della
    stessa variante scritta da un click reale si confrontano mercato e
    probabilita'. Coincidenze = conferma che snapshot/pool/motore riproducono
    il click vero; scarti = da spiegare (snapshot diverso dall'istante del
    click reale, cache 30').

    Il confronto e' per variante perche' le due commesse guardano due periodi
    diversi: nel periodo del replay simmetrico (prima di PR#24) il registro ha
    righe LEGACY prodotte dal modello allora live, quindi e' proprio la
    variante legacy a dover tornare; dopo PR#24 vale il contrario.
    """
    per_chiave: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for p in existing:
        if origin_of(p) != ORIGIN_TOP_MIX or p.get("match_id") is None:
            continue
        per_chiave[(str(p["match_id"]), model_variant_of(p))] = p
    out: List[Dict[str, Any]] = []
    # Controllo INCROCIATO sulle righe scritte PRIMA di PR#24: il motore allora
    # live era quello VECCHIO, e le sue righe sono nel registro senza campo di
    # variante (che per i record storici vale "current"): confrontarle con le
    # righe ricostruite del modello ATTUALE sarebbe mele contro pere. Il termine
    # di paragone giusto e' la riga LEGACY ricostruita, ed e' anche la verifica
    # piu' forte che si possa fare: il replay rifa' davvero il click di allora?
    for c in clicks:
        for t in c.targets:
            reale = per_chiave.get((str(t.match_id), MODEL_VARIANT_CURRENT))
            if reale is None or not _prima_di_pr24(reale):
                continue
            mia = {str(r.get("match_id")): r for r in c.rows.get(MODEL_VARIANT_LEGACY, [])}.get(str(t.match_id))
            out.append({
                "match": f"{t.home}-{t.away}", "league": t.league, "kickoff": t.utc.strftime(ISO_Z),
                "variante": "legacy (incrociata: riga scritta prima di PR#24, motore allora live)",
                "registro_mercato": reale.get("mercato_standard"), "registro_prob": reale.get("prob_sicuro"),
                "registro_snapshot": reale.get("data_snapshot_sha"), "registro_salvato_il": reale.get("salvato_il"),
                "replay_mercato": mia.get("mercato_standard") if mia else None,
                "replay_prob": mia.get("prob_val") if mia else None,
                "replay_snapshot": c.snapshot_sha,
                "coincide": bool(mia) and mia.get("mercato_standard") == reale.get("mercato_standard")
                            and mia.get("prob_val") == reale.get("prob_sicuro"),
            })
    for c in clicks:
        for variante in VARIANTI:
            mie = {str(r.get("match_id")): r for r in c.rows.get(variante, [])}
            for t in c.targets:
                reale = per_chiave.get((str(t.match_id), variante))
                if reale is None:
                    continue
                mia = mie.get(str(t.match_id))
                out.append({
                    "match": f"{t.home}-{t.away}", "league": t.league, "kickoff": t.utc.strftime(ISO_Z),
                    "variante": variante,
                    "registro_mercato": reale.get("mercato_standard"), "registro_prob": reale.get("prob_sicuro"),
                    "registro_snapshot": reale.get("data_snapshot_sha"), "registro_salvato_il": reale.get("salvato_il"),
                    "replay_mercato": mia.get("mercato_standard") if mia else None,
                    "replay_prob": mia.get("prob_val") if mia else None,
                    "replay_snapshot": c.snapshot_sha,
                    "coincide": bool(mia) and mia.get("mercato_standard") == reale.get("mercato_standard")
                                and mia.get("prob_val") == reale.get("prob_sicuro"),
                })
    return out


# ---------------------------------------------------------------------------
# Orchestrazione
# ---------------------------------------------------------------------------
@dataclass
class ReplayReport:
    generato_il: str
    finestra: Tuple[str, str]
    sorgente_fixture: str
    ref: str
    clicks: List[Dict[str, Any]]
    entries_legacy: List[Dict[str, Any]]
    entries_current: List[Dict[str, Any]]
    leak_ok: bool
    note: List[str]
    modelli: List[str] = field(default_factory=lambda: list(VARIANTI))
    finestra_ok: bool = True
    entries_legacy_non_scritte: List[Dict[str, Any]] = field(default_factory=list)
    entries_current_non_scritte: List[Dict[str, Any]] = field(default_factory=list)
    registro: Dict[str, Any] = field(default_factory=dict)
    fedelta: List[Dict[str, Any]] = field(default_factory=list)
    coverage: Dict[str, Any] = field(default_factory=dict)

    @property
    def scrivibile(self) -> bool:
        """Si scrive solo se NESSUN click ha buchi di leakage e la finestra dichiarata regge."""
        return self.leak_ok and self.finestra_ok

    def entries_da_scrivere(self) -> List[Dict[str, Any]]:
        """Le righe dei modelli richiesti, in ordine di click."""
        out: List[Dict[str, Any]] = []
        if MODEL_VARIANT_CURRENT in self.modelli:
            out.extend(self.entries_current)
        if MODEL_VARIANT_LEGACY in self.modelli:
            out.extend(self.entries_legacy)
        return out


def run_replay(fixtures: Dict[str, List[Fixture]], day_from: date, day_to: date, *,
               sorgente: str, ref: Optional[str] = None, repo_root: str = REPO_ROOT,
               leagues: Optional[Iterable[str]] = None,
               models: Iterable[str] = VARIANTI,
               snapshot_cache: Optional[str] = None,
               snapshot_factory: Callable[..., Any] = database_at_instant,
               da_istante: Optional[datetime] = None, a_istante: Optional[datetime] = None,
               log: Callable[[str], None] = print) -> Tuple[ReplayReport, List[ClickResult]]:
    """Replay walk-forward dei modelli richiesti su ``[day_from, day_to]``.

    Ogni click e' un istante T = kickoff - 1 s di UNA o piu' partite; per ogni
    click si producono le righe di ENTRAMBI i modelli (lo stesso click le
    calcola insieme), ma solo quelle dei modelli in ``models`` vengono scritte
    nel Registro: le altre restano nel referto come controprova.
    """
    ref = ref or resolve_main_ref(repo_root)
    modelli = [m for m in models if m in VARIANTI] or list(VARIANTI)
    bersagli = target_fixtures(fixtures, day_from, day_to, da_istante=da_istante, a_istante=a_istante)
    if leagues:
        leghe = set(leagues)
        bersagli = [b for b in bersagli if b.league in leghe]
    per_istante: Dict[datetime, List[Fixture]] = {}
    for b in bersagli:
        per_istante.setdefault(b.utc - timedelta(seconds=1), []).append(b)
    note: List[str] = []
    note.append(f"finestra richiesta {day_from.isoformat()} → {day_to.isoformat()}"
                + (f", limiti a istante [{da_istante.strftime(ISO_Z) if da_istante else '-∞'}, "
                   f"{a_istante.strftime(ISO_Z) if a_istante else '+∞'})" if (da_istante or a_istante) else "")
                + f"; "
                f"primo istante onesto ricostruibile dal repo: {REPLAY_START_DAY.isoformat()} "
                "(commit 48e7768, il primo con la stagione 2026/27 nei CSV live; "
                "prima di allora in git c'e' un'altra stagione)")
    if day_to < REPLAY_START_DAY:
        note.append("ATTENZIONE: nessuna partita della finestra ricade dopo l'inizio ricostruibile")
    incerti = [b for b in bersagli if b.kickoff_source == "csv_date_midnight"]
    if incerti:
        note.append(f"{len(incerti)} partite con kickoff incerto (mezzanotte UTC del giorno CSV, piu' conservativo): "
                    + ", ".join(f"{b.home}-{b.away}" for b in incerti))
    dedotte = sum(1 for lst in fixtures.values() for f in lst if f.matchday_inferred)
    if dedotte:
        note.append(f"{dedotte} fixture del pool con giornata dedotta dalle righe CSV vicine (offline)")
    senza_md = sum(1 for lst in fixtures.values() for f in lst if f.matchday is None)
    if senza_md:
        note.append(f"{senza_md} fixture senza giornata: escluse dal pool da select_next_matchday_matches")

    clicks: List[ClickResult] = []
    entries: Dict[str, List[Dict[str, Any]]] = {v: [] for v in VARIANTI}
    non_scritte: Dict[str, List[Dict[str, Any]]] = {v: [] for v in VARIANTI}
    righe_click: List[Dict[str, Any]] = []
    for T in sorted(per_istante):
        tg = per_istante[T]
        log(f"[replay] T={T.strftime(ISO_Z)}  bersagli={', '.join(f'{b.home}-{b.away}' for b in tg)}")
        c = simulate_click(T, fixtures, targets=tg, leagues=leagues, ref=ref, repo_root=repo_root,
                           snapshot_factory=snapshot_factory, snapshot_cache=snapshot_cache)
        clicks.append(c)
        # Un click non scrivibile (leak O snapshot di un'altra stagione) non
        # produce righe da registrare: resta nel referto con i suoi dettagli.
        destinazioni = (entries, non_scritte) if c.scrivibile else (non_scritte, non_scritte)
        leg = entries_for_targets(c, MODEL_VARIANT_LEGACY)
        cur = entries_for_targets(c, MODEL_VARIANT_CURRENT)
        for variante, righe in ((MODEL_VARIANT_LEGACY, leg), (MODEL_VARIANT_CURRENT, cur)):
            destinazioni[0 if variante in modelli else 1][variante].extend(righe)
        righe_click.append({
            "instant": T.strftime(ISO_Z),
            "snapshot": {"sha": c.commit.sha, "short": c.commit.short,
                         "committer_time": c.commit.committer_time.strftime(ISO_Z), "subject": c.commit.subject},
            "bersagli": [{"match_id": b.match_id, "league": b.league, "home": b.home, "away": b.away,
                          "kickoff": b.utc.strftime(ISO_Z), "kickoff_source": b.kickoff_source,
                          "risultato": f"{b.gh}-{b.ga}"} for b in tg],
            "pool": c.pool_sizes, "selezionate": c.selected, "leghe_senza_motore": c.missing,
            "sopra_soglia": {v: len(r) for v, r in c.rows.items()},
            "leghe_senza_stagione": c.fuori_stagione,
            "archivio_xg": c.archivio_xg,
            "righe_current": [f"{e['home']}-{e['away']} {e['mercato_standard']} {e['prob_sicuro']}% rank {e['rank']} {e['esito']}" for e in cur],
            "righe_legacy": [f"{e['home']}-{e['away']} {e['mercato_standard']} {e['prob_sicuro']}% rank {e['rank']} {e['esito']}" for e in leg],
            "leak": {"commit_before_instant": c.leak.commit_before_instant,
                     "targets_absent_from_live_csv": c.leak.targets_absent_from_live_csv,
                     "targets_absent_from_xg_archive": c.leak.targets_absent_from_xg_archive,
                     "xg_cutoff_is_instant": c.leak.xg_cutoff_is_instant,
                     "snapshot_covers_season": c.leak.snapshot_covers_season,
                     "future_rows_dropped": c.leak.future_rows_dropped,
                     "ok": c.leak.ok, "scrivibile": c.leak.scrivibile, "dettagli": c.leak.dettagli},
        })
    # Due cose diverse, tenute separate nel referto:
    # * ``leak_ok``: la regola ferrea (commit < T, bersaglio assente da CSV e
    #   archivio xG, cutoff xG = T). Un False qui e' un problema VERO.
    # * ``finestra_ok``: nessun click DENTRO la finestra dichiarata ha lo
    #   snapshot di un'altra stagione. Prima dell'inizio ricostruibile i click
    #   sono saltati per costruzione, non per errore.
    leak_ok = all(c.leak.ok for c in clicks)
    fuori_finestra = [c for c in clicks if not c.leak.snapshot_covers_season
                      and c.instant >= REPLAY_START_INSTANT]
    finestra_ok = not fuori_finestra
    n_fuori = sum(len(c.fuori_stagione) for c in clicks)
    n_prima = sum(1 for c in clicks if c.instant < REPLAY_START_INSTANT)
    if n_fuori:
        note.append(f"{n_fuori} click-lega saltati perche' lo snapshot in git non e' della stagione in corso"
                    + (f" (di cui {n_prima} click PRIMA dell'inizio ricostruibile {REPLAY_START_INSTANT.strftime(ISO_Z)}: "
                       "esclusi per costruzione, non rigiocabili in modo onesto)" if n_prima else ""))
    if fuori_finestra:
        note.append(f"ATTENZIONE: {len(fuori_finestra)} click DENTRO la finestra dichiarata non sono ricostruibili")
    senza_archivio = sum(1 for c in clicks if not all(c.archivio_xg.values()))
    if senza_archivio:
        note.append(f"{senza_archivio} click con snapshot PRIVO dell'archivio xG (in git arriva il 01/09): "
                    "la testa O/U ha usato il fallback, esattamente come la produzione con quei dati")
    n_scarti = sum(len(v) for v in non_scritte.values())
    if n_scarti:
        note.append(f"{n_scarti} righe calcolate ma NON destinate al Registro (modello non richiesto o click non scrivibile)")
    report = ReplayReport(
        generato_il=datetime.now(UTC).strftime(ISO_Z), finestra=(day_from.isoformat(), day_to.isoformat()),
        sorgente_fixture=sorgente, ref=ref, clicks=righe_click,
        entries_legacy=entries[MODEL_VARIANT_LEGACY], entries_current=entries[MODEL_VARIANT_CURRENT],
        entries_legacy_non_scritte=non_scritte[MODEL_VARIANT_LEGACY],
        entries_current_non_scritte=non_scritte[MODEL_VARIANT_CURRENT],
        modelli=modelli, leak_ok=leak_ok, finestra_ok=finestra_ok, note=note)
    return report, clicks


def render_markdown(rep: ReplayReport) -> str:
    etichette = MODEL_VARIANT_LABELS
    modelli_txt = " + ".join(etichette.get(m, m) for m in rep.modelli)
    L: List[str] = []
    L.append("# Replay walk-forward Top Mix, due modelli (no-leakage)\n")
    L.append(f"Generato: {rep.generato_il} · finestra {rep.finestra[0]} → {rep.finestra[1]} · "
             f"fixture: `{rep.sorgente_fixture}` · ref snapshot: `{rep.ref}` · modelli scritti: **{modelli_txt}**\n")
    n_scrivibili = sum(1 for c in rep.clicks if c["leak"].get("scrivibile"))
    L.append(f"**Leak check complessivo: {'OK' if rep.leak_ok else 'FALLITO'}** "
             f"· **finestra dichiarata ricostruibile: {'OK' if rep.finestra_ok else 'FALLITA'}** "
             f"· click simulati: {len(rep.clicks)} (scrivibili: {n_scrivibili}) "
             f"· righe destinate al Registro: "
             f"{len(rep.entries_current)} {etichette.get(MODEL_VARIANT_CURRENT, '')} + "
             f"{len(rep.entries_legacy)} {etichette.get(MODEL_VARIANT_LEGACY, '')}\n")
    if rep.registro:
        L.append(f"Registro: {json.dumps(rep.registro, ensure_ascii=False)}\n")
    for n in rep.note:
        L.append(f"- nota: {n}")
    L.append("\n## Click simulati\n")
    L.append("| T (UTC) | snapshot | commit time | bersagli | pool | selez. | sopra soglia att/leg | righe attuale | righe legacy | leak |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for c in rep.clicks:
        s = c["snapshot"]; lk = c["leak"]
        bers = "<br>".join(f"{b['home']}-{b['away']} ({b['league']}, {b['risultato']})" for b in c["bersagli"])
        drop = sum(lk["future_rows_dropped"].values())
        L.append(f"| {c['instant']} | `{s['short']}` | {s['committer_time']} | {bers} | "
                 f"{sum(c['pool'].values())} | {sum(c['selezionate'].values())} | "
                 f"{c['sopra_soglia'].get('current', 0)}/{c['sopra_soglia'].get('legacy', 0)} | "
                 f"{'<br>'.join(c['righe_current']) or '—'} | "
                 f"{'<br>'.join(c['righe_legacy']) or '—'} | "
                 f"{'OK' if lk['scrivibile'] else 'FAIL'}"
                 f"{' (no stagione: ' + ', '.join(c['leghe_senza_stagione']) + ')' if c.get('leghe_senza_stagione') else ''}"
                 f"{' (+' + str(drop) + ' righe future scartate)' if drop else ''} |")
    L.append("\n## Tabella leakage per click\n")
    L.append("| T | commit < T | bersaglio assente dal CSV | bersaglio assente da xG | cutoff xG = T | snapshot della stagione | righe future scartate | dettagli |")
    L.append("|---|---|---|---|---|---|---|---|")
    for c in rep.clicks:
        lk = c["leak"]
        L.append(f"| {c['instant']} | {lk['commit_before_instant']} | {lk['targets_absent_from_live_csv']} | "
                 f"{lk['targets_absent_from_xg_archive']} | {lk['xg_cutoff_is_instant']} | "
                 f"{lk['snapshot_covers_season']} | "
                 f"{json.dumps(lk['future_rows_dropped']) if lk['future_rows_dropped'] else '—'} | "
                 f"{'; '.join(lk['dettagli']) or '—'} |")
    if rep.fedelta:
        n_ok = sum(1 for f in rep.fedelta if f["coincide"])
        L.append(f"\n## Fedelta' (righe del registro vs replay, per variante): "
                 f"{n_ok}/{len(rep.fedelta)} coincidono\n")
        L.append("| partita | variante | registro | replay | snapshot reg./replay | coincide |")
        L.append("|---|---|---|---|---|---|")
        for f in rep.fedelta:
            L.append(f"| {f['match']} ({f['league']}) | {etichette.get(f.get('variante'), f.get('variante'))} | "
                     f"{f['registro_mercato']} {f['registro_prob']}% | "
                     f"{f['replay_mercato']} {f['replay_prob']}% | "
                     f"`{f['registro_snapshot']}` / `{f['replay_snapshot']}` | {f['coincide']} |")
    for variante, etichetta in ((MODEL_VARIANT_CURRENT, "modello attuale"),
                                (MODEL_VARIANT_LEGACY, "modello legacy")):
        righe = rep.entries_current if variante == MODEL_VARIANT_CURRENT else rep.entries_legacy
        L.append(f"\n## Righe del {etichetta} ({etichette.get(variante, variante)}) destinate al Registro\n")
        if not righe:
            L.append("Nessuna: nessuna partita bersaglio sopra le soglie con questo modello.")
            continue
        L.append("| data | lega | partita | mercato | prob | rank | esito | risultato | snapshot | salvato_il |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for e in righe:
            L.append(f"| {e['data']} | {e['campionato']} | {e['home']}-{e['away']} | {e['mercato_standard']} | "
                     f"{e['prob_sicuro']}% | {e['rank']} | {e['esito']} | {e['risultato_reale']} | "
                     f"`{e['data_snapshot_sha']}` | {e['salvato_il']} |")
    if rep.coverage:
        L.append("\n## Copertura per modello (stesso campione?)\n")
        L.append("```\n" + render_coverage(rep.coverage) + "\n```")
    return "\n".join(L) + "\n"


def _parse_day(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _parse_instant(s: str) -> datetime:
    """Istante ISO-8601 UTC: ``2026-09-18T21:51:58Z`` (accetta anche ``+00:00``)."""
    t = s.strip().replace("Z", "+00:00")
    d = datetime.fromisoformat(t)
    return d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from", dest="day_from", type=_parse_day, default=REPLAY_START_DAY,
                    help="primo giorno (UTC) delle partite da replicare, YYYY-MM-DD "
                         f"(default: {REPLAY_START_DAY.isoformat()}, primo istante ricostruibile dal repo)")
    ap.add_argument("--to", dest="day_to", type=_parse_day, default=datetime.now(UTC).date(),
                    help="ultimo giorno (UTC), YYYY-MM-DD (default: oggi)")
    ap.add_argument("--from-instant", dest="da_istante", type=_parse_instant, default=None,
                    metavar="ISO", help="confine iniziale a ISTANTE (YYYY-MM-DDTHH:MM:SSZ), incluso")
    ap.add_argument("--to-instant", dest="a_istante", type=_parse_instant, default=None,
                    metavar="ISO", help="confine finale a ISTANTE, ESCLUSO: serve a partizionare "
                                        "esattamente su un merge git senza sovrapposizioni")
    ap.add_argument("--fixtures", choices=("api", "csv"), default="csv",
                    help="sorgente fixture: api = football-data.org (autorevole), csv = offline (validazione)")
    ap.add_argument("--model", choices=("both", MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY), default="both",
                    help="quali modelli rigiocare e scrivere: both (default) = attuale + legacy, "
                         "stesso Poisson e stesse soglie, ognuno con la sua variante nel Registro")
    ap.add_argument("--leagues", nargs="*", default=None, help="sottoinsieme di leghe (nomi di LEAGUES_CONFIG)")
    ap.add_argument("--ref", default=None, help="ref git di main (default: origin/main, poi main)")
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "audit", "results", "replay_legacy_topmix"),
                    help="cartella per referto markdown + JSON")
    ap.add_argument("--write", action="store_true",
                    help="scrive le righe nel registro (richiede --fixtures api); default: dry-run")
    ap.add_argument("--dump-merged", default=None, metavar="FILE",
                    help="scrive in FILE (formato predictions.json) registro caricato + righe candidate, "
                         "SENZA toccare il registro: serve alla verifica visiva su un'anteprima di branch")
    ap.add_argument("--snapshot-cache", default=None, metavar="DIR",
                    help="riusa le estrazioni gia' fatte (chi passa da questa cartella la tiene: usare una tmp "
                         "usa-e-getta se non si vuole conservarla)")
    args = ap.parse_args(argv)

    if args.write and args.fixtures != "api":
        print("ERRORE: --write richiede --fixtures api (id partita e nomi identici al click live).", file=sys.stderr)
        return 2
    modelli = list(VARIANTI) if args.model == "both" else [args.model]
    cache = args.snapshot_cache
    cache_effimera = None
    if not cache:
        cache_effimera = tempfile.mkdtemp(prefix="sm_replay_snap_")
        cache = cache_effimera
    try:
        if args.fixtures == "api":
            from config import FOOTBALL_DATA_API_KEY
            fixtures = fixtures_from_api(FOOTBALL_DATA_API_KEY, args.leagues)
        else:
            fixtures = fixtures_from_csv_and_archive(args.leagues)

        report, clicks = run_replay(fixtures, args.day_from, args.day_to, sorgente=args.fixtures,
                                    da_istante=args.da_istante, a_istante=args.a_istante,
                                    ref=args.ref, leagues=args.leagues, models=modelli,
                                    snapshot_cache=cache)

        # Registro: confronto di fedelta', copertura e fusione (dry-run o scrittura)
        try:
            existing, fonte = strict_load_registry()
        except Exception as e:  # senza registro (offline) si va avanti col solo referto
            existing, fonte = [], f"non disponibile ({e})"
        report.fedelta = compare_with_registry(existing, clicks) if existing else []
        da_scrivere = report.entries_da_scrivere()
        # Copertura: si misura sul registro FUSO (righe esistenti + righe nuove),
        # cosi' il numero risponde alla domanda "per ogni partita del periodo il
        # Registro ha ENTRAMBI i modelli?" e non "quante ne scrive il replay?".
        try:
            fuso, _ = merge_entries(existing, da_scrivere) if existing else (da_scrivere, Counter())
            report.coverage = coverage_by_variant(fuso, args.day_from, args.day_to)
        except ReplayError as e:
            report.coverage = {"errore": str(e)}
        if not report.scrivibile:
            report.registro = {"scritto": False,
                               "motivo": ("leak check fallito" if not report.leak_ok
                                          else "finestra dichiarata non ricostruibile: click senza la stagione nei dati")}
        elif args.fixtures == "api" or existing:
            try:
                report.registro = write_to_registry(da_scrivere, dry_run=not args.write)
            except ReplayError as e:
                report.registro = {"scritto": False, "errore": str(e)}
        else:
            report.registro = {"scritto": False, "motivo": f"dry-run offline, registro {fonte}"}

        if args.dump_merged and report.scrivibile:
            try:
                merged, _ = merge_entries(existing, da_scrivere)
                os.makedirs(os.path.dirname(os.path.abspath(args.dump_merged)), exist_ok=True)
                with open(args.dump_merged, "w", encoding="utf-8") as f:
                    json.dump({"data": merged}, f, ensure_ascii=False, indent=2)
                report.note.append(f"copia fusa (registro + candidate) scritta in {args.dump_merged}: {len(merged)} righe")
            except ReplayError as e:
                report.note.append(f"copia fusa NON scritta: {e}")

        os.makedirs(args.out, exist_ok=True)
        md = os.path.join(args.out, "replay_legacy_topmix.md")
        js = os.path.join(args.out, "replay_legacy_topmix.json")
        with open(md, "w", encoding="utf-8") as f:
            f.write(render_markdown(report))
        with open(js, "w", encoding="utf-8") as f:
            json.dump(asdict(report), f, ensure_ascii=False, indent=2, default=str)
        print(render_markdown(report))
        print(f"[replay] referto: {md}\n[replay] json: {js}")
        if not report.scrivibile:
            return 1
        if args.write and scrittura_fallita(report.registro):
            print(f"[replay] SCRITTURA NON RIUSCITA: {report.registro}", file=sys.stderr)
            return 1
        return 0
    finally:
        if cache_effimera:
            shutil.rmtree(cache_effimera, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
