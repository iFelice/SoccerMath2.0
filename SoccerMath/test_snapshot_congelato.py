"""Database CONGELATO e orologio FERMO per i test che leggono i dati veri.

Perche' esiste
--------------
Alcuni test del repository sono stati scritti su uno stato preciso del database
(la classifica della Bundesliga alla giornata 7, la ``live_odds.json`` di un
giorno, le xG di una certa settimana) ma lo leggevano dal file LIVE che i
workflow ``update_database`` (ogni 6 ore), ``live_odds`` (ogni giorno) e
``update_xg`` (martedi' e venerdi') riscrivono. Il censimento
``audit/results/referto_fixture_apptest_giornata7_2026-11-02.md`` (punto 4,
voci 1, 2, 3, 5, 8, 11, 12, 13) elenca quei test.

Questo modulo da' a quei test due cose, senza toccare ne' l'app ne' le
asserzioni:

1. **Una copia congelata del database**, presa dalla storia git del commit in
   cui i test sono stati scritti o aggiornati l'ultima volta (vedi
   ``test_fixtures/db_congelato/2026-10-29/README.md``). La cartella e'
   versionata nel repository (6,1 MB): nessuna rete, nessun ``git show`` a
   runtime, nessuna dipendenza da un clone completo.
2. **Un orologio fermo a un istante fisso** coerente con quella copia
   (``ADESSO_CONGELATO``), imposto su tutte le sorgenti d'ora che i test e
   l'app leggono, comprese le costanti di stagione che ``config`` calcola
   all'import dalla data vera.

Uso (context manager, anche annidati fra loro):

    from test_snapshot_congelato import database_congelato, orologio_fermo

    with database_congelato(), orologio_fermo():
        ...      # qui i CSV letti sono quelli del 2026-10-29 e
                 # datetime.now() e' ADESSO_CONGELATO

Nelle classi ``unittest`` che hanno gia' un ``setUpClass`` si usano
``avvia()``/``ferma()``:

    @classmethod
    def setUpClass(cls):
        cls._db_congelato = database_congelato()
        cls._db_congelato.avvia()
        ...

    @classmethod
    def tearDownClass(cls):
        cls._db_congelato.ferma()

Non scrive niente nel repository: ``database_congelato`` copia la fixture in
una cartella temporanea e ripunta ``config``/``xg_archive``/i due motori Elo
(la stessa tecnica di ``db_snapshot._redirect``, il modulo di produzione del
replay) e ripristina tutto alla fine. La copia e' necessaria perche' alcuni
test scrivono nella cartella del database: con i soli link simbolici
scriverebbero nel repository.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))

#: La copia congelata del database e il commit da cui e' stata presa.
DB_CONGELATO_DIR = os.path.join(HERE, "test_fixtures", "db_congelato", "2026-10-29")
DB_CONGELATO = os.path.join(DB_CONGELATO_DIR, "SoccerMath", "database")
DB_CONGELATO_COMMIT = "331dcd8"
DB_CONGELATO_DATA = "2026-10-29"

#: L'istante dell'orologio fermo. Sta DOPO l'ultima partita della copia
#: congelata (l'ultima riga scritta nei ``*_Live.csv`` del commit 331dcd8 e'
#: del 2026-10-29) e DOPO la ``generato_il`` della sua ``live_odds.json``:
#: nessun risultato della copia e' "futuro" e ogni partita e' gia' giocata.
#: E' anche il giorno in cui i test della scheda sono stati aggiornati alla
#: fixture della giornata 7 (commit 331dcd8, 2026-10-29 22:16 UTC).
ADESSO_CONGELATO = datetime(2026, 10, 29, 22, 0, tzinfo=timezone.utc)

#: Moduli leggeri che leggono l'ora vera: si importano e si patchano.
_MODULI_LEGGERI = ("config", "market_odds", "lista_giocate", "prediction_registry",
                   "xg_archive", "season_rosters", "season_rollover",
                   "scheda_partita")
#: Moduli pesanti (import lento, effetti collaterali): si patchano SOLO se il
#: test li ha gia' importati; un modulo non ancora importato non puo' leggere
#: l'ora.
_MODULI_PESANTI = ("app", "scraper_xg", "models.elo_engine",
                   "models.elo_engine_legacy")


def _classi_datetime_congelate(istante: datetime):
    """``datetime`` sostituto: ``now()``/``today()``/``utcnow()`` fermi.

    Costruito da ``type(datetime)`` + ``datetime`` vero, come fanno gia' gli
    AppTest del repository: le istanze restano ``isinstance(x, datetime)`` vere
    e tutte le altre operazioni (``strptime``, ``fromisoformat``, confronti,
    ``date()``) funzionano normalmente.
    """
    _real_dt = datetime

    class _MetaDtCongelata(type(_real_dt)):
        def __instancecheck__(self_cls, istanza):
            return isinstance(istanza, _real_dt)

    class _DtCongelata(_real_dt, metaclass=_MetaDtCongelata):
        __slots__ = ()

        @classmethod
        def now(cls_dt, tz=None):
            if tz is None:
                return istante.replace(tzinfo=None)
            return istante.astimezone(tz)

        @classmethod
        def utcnow(cls_dt, *a, **k):
            return istante.astimezone(timezone.utc).replace(tzinfo=None)

        @classmethod
        def today(cls_dt):
            return istante.replace(tzinfo=None)

    return _DtCongelata


def _moduli_da_patchare(extra=()):
    """I moduli il cui attributo ``datetime`` va sostituito.

    ``extra`` sono moduli aggiuntivi (tipicamente il file di test stesso, che
    ha importato ``datetime`` nel proprio namespace).
    """
    import importlib

    fuori = []
    for nome in _MODULI_LEGGERI:
        try:
            fuori.append(importlib.import_module(nome))
        except Exception:                       # pragma: no cover
            continue
    for nome in _MODULI_PESANTI:
        modulo = sys.modules.get(nome)
        if modulo is not None:
            fuori.append(modulo)
    for modulo in extra:
        if modulo is not None:
            fuori.append(modulo)
    # il modulo ``datetime`` stesso: lo script di ``app.py`` rieseguito da
    # AppTest fa ``from datetime import datetime`` a ogni run, quindi vede
    # l'attributo del modulo, non una copia presa prima.
    fuori.append(sys.modules["datetime"])
    visti, unici = set(), []
    for m in fuori:
        if id(m) not in visti:
            visti.add(id(m))
            unici.append(m)
    return unici


class orologio_fermo:
    """``datetime.now()`` fermo a ``ADESSO_CONGELATO`` (o all'istante dato).

    Congela anche ``market_odds._adesso_utc`` (la cucitura d'ora di produzione,
    «Funzione unica cosi' i test possono congelare l'orologio») e le costanti di
    stagione che ``config`` ha calcolato all'import dalla data vera
    (``CURRENT_SEASON_START_YEAR``, ``CURRENT_SEASON``, ``HISTORICAL_SEASONS``,
    ``ALL_SEASONS``), cosi' il quadro e' coerente con la copia congelata.
    """

    def __init__(self, istante: datetime = None, moduli=()):
        self.istante = istante or ADESSO_CONGELATO
        self.moduli = tuple(moduli)
        self._patch = []
        self._stagioni = None

    def avvia(self):
        from unittest import mock

        import season_calendar as sc

        dt_congelata = _classi_datetime_congelate(self.istante)
        self._patch = []
        for modulo in _moduli_da_patchare(self.moduli):
            if hasattr(modulo, "datetime"):
                p = mock.patch.object(modulo, "datetime", dt_congelata)
                p.start()
                self._patch.append(p)
            if hasattr(modulo, "_adesso_utc") and modulo.__name__ == "market_odds":
                p = mock.patch.object(modulo, "_adesso_utc", lambda: self.istante)
                p.start()
                self._patch.append(p)

        import config
        anno = sc.season_start_year_of(self.istante)
        self._stagioni = {k: getattr(config, k) for k in
                          ("CURRENT_SEASON_START_YEAR", "CURRENT_SEASON",
                           "HISTORICAL_SEASONS", "ALL_SEASONS")}
        config.CURRENT_SEASON_START_YEAR = anno
        config.CURRENT_SEASON = sc.season_label(anno)
        config.HISTORICAL_SEASONS = config.historical_seasons(anno)
        config.ALL_SEASONS = [config.CURRENT_SEASON] + [
            s for s in config.HISTORICAL_SEASONS if s != config.CURRENT_SEASON]
        return self.istante

    def ferma(self):
        import config

        for p in reversed(self._patch):
            try:
                p.stop()
            except Exception:                   # pragma: no cover
                pass
        self._patch = []
        if self._stagioni:
            for k, v in self._stagioni.items():
                setattr(config, k, v)
            self._stagioni = None

    def __enter__(self):
        return self.avvia()

    def __exit__(self, *exc):
        self.ferma()
        return False


class database_congelato:
    """Punta i moduli di produzione alla copia CONGELATA del database.

    Dentro il contesto ``config.DATABASE_DIR``, i percorsi di
    ``config.LEAGUES_CONFIG`` (``base_csv``/``live_csv``/``xg_json``),
    ``config.LEAGUE_FILE_MAP``, ``xg_archive`` e i due motori Elo leggono una
    cartella temporanea con la copia del commit ``DB_CONGELATO_COMMIT``. Alla
    fine si ripristina tutto: i test che devono restare sui dati VERI
    (``test_controlli_dati.py``, il workflow ``controlli_dati.yml``) non sono
    toccati.
    """

    def __init__(self, cartella: str = DB_CONGELATO):
        self.sorgente = cartella
        self.tmp = None
        self._snapshot = None

    def avvia(self):
        import db_snapshot

        self.tmp = Path(tempfile.mkdtemp(prefix="sm_db_congelato_"))
        for f in sorted(Path(self.sorgente).iterdir()):
            if f.is_dir():
                continue
            shutil.copy2(f, self.tmp / f.name)
        self._snapshot = db_snapshot._snapshot_paths()
        db_snapshot._redirect(str(self.tmp))
        _svuota_cache()
        return self.tmp

    def ferma(self):
        import db_snapshot

        db_snapshot._restore(self._snapshot)
        _svuota_cache()
        if self.tmp is not None:
            shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp = None

    def __enter__(self):
        return self.avvia()

    def __exit__(self, *exc):
        self.ferma()
        return False


def _svuota_cache():
    """Le cache che tengono dati del database (Poisson, motori Elo, st.cache_data)."""
    try:
        import db_snapshot
        db_snapshot.clear_engine_caches()
    except Exception:                           # pragma: no cover
        pass
    try:
        import streamlit as st
        st.cache_data.clear()
    except Exception:                           # pragma: no cover
        pass
