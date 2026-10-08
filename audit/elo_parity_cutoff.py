"""
elo_parity_cutoff.py — troncamento del database a un CUTOFF dichiarato per lega.

UTILITY DI TEST: nessuna riga di produzione. La usano i test di parita' Elo
(``test_elo_s3_parity.py``, ``test_elo_walker_parity.py``,
``test_elo_probs_equivalence.py``).

Perche'
-------
Ogni fixture di parita' congela numeri calcolati su un database che, al momento
della generazione, arrivava a una certa data per ogni lega: quella data e' il
``cutoff`` dichiarato nel manifest della fixture. Il bot aggiunge partite nei
``*_Live.csv`` con date successive. Se un test costruisse il motore sul database
INTERO:

  * conteggi e stato finale cambierebbero (le partite nuove entrano nel calcolo);
  * ``EloEngine.load_and_preprocess_matches`` ordina con ``sort_values`` senza
    ``kind`` (quicksort, non stabile): al variare della dimensione dell'array le
    partite della STESSA data cambiano posto, e i confronti per posizione
    (``prod_order``, ``prod_pos_nel_db_completo``, ``zip`` sui record) danno
    falsi negativi anche quando nessun rating e' cambiato.

Quindi un test di parita' confronta SOLO le partite con data <= cutoff[lega].

Come
----
``database_fino_a_cutoff(cutoff)`` copia i CSV del database corrente
(``config.DATABASE_DIR``) in una cartella temporanea tenendo, per ogni lega, le
sole righe con Date (dayfirst) <= cutoff[lega]; copia i ``.json`` (roster
``season_rosters.json``, xG) e ripunta ``config`` come il meccanismo P3 di
``make_elo_parity_fixture._RepointDB``. Il database sorgente non viene mai
scritto. Il troncamento e' INCLUSIVO: il cutoff e' la data massima della
fixture, quindi tutte le partite della fixture restano dentro.

Perche' il cutoff e' per lega
-----------------------------
La massima data delle fixture e' 2026-10-21 (una riga della Liga gia' presente
nel database), mentre le altre leghe finiscono al 2026-09-20. Un cutoff unico a
2026-10-21 includerebbe anche le partite aggiunte dal bot tra il 21/09 e il
21/10 in Serie A, Premier, Bundesliga e Ligue 1 (per esempio una partita di
Serie A datata 27/09, come nello scenario di prova A): il cutoff e' per lega.

Guardia: ``leggi_cutoff`` rifiuta un cutoff mancante, incompleto o non in formato
YYYY-MM-DD, cosi' il test fallisce in modo esplicito invece di troncare a caso.
"""
from __future__ import annotations

import contextlib
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

_AUDIT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _AUDIT_DIR.parent
for _p in (str(_AUDIT_DIR), str(_REPO_ROOT / "SoccerMath")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config as PROD_CONFIG                       # noqa: E402
import models.elo_engine as PROD_ELO               # noqa: E402
from make_elo_parity_fixture import _RepointDB     # noqa: E402  (meccanismo P3)

LEAGUES = ("Serie A", "Premier League", "La Liga", "Bundesliga", "Ligue 1")
_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def leggi_cutoff(dichiarato, leghe=LEAGUES) -> dict:
    """Valida il cutoff dichiarato nel manifest: una data YYYY-MM-DD per ogni lega.

    Solleva AssertionError se il manifest non ha il blocco ``cutoff``, se manca
    una lega o se una data non e' valida. Non inventa mai un valore di default.
    """
    if not isinstance(dichiarato, dict):
        raise AssertionError("manifest senza blocco 'cutoff' per lega: rigenerare "
                             "il generatore o aggiungere il cutoff dedotto dai dati")
    mancanti = [lg for lg in leghe if lg not in dichiarato]
    if mancanti:
        raise AssertionError(f"cutoff mancante per le leghe {mancanti}")
    out = {}
    for lg in leghe:
        v = dichiarato[lg]
        if not (isinstance(v, str) and _DATA.match(v)):
            raise AssertionError(f"cutoff non valido per {lg}: {v!r} (atteso YYYY-MM-DD)")
        out[lg] = pd.Timestamp(v).strftime("%Y-%m-%d")
    return out


def _lega_del_file(nome: str):
    """Lega a cui appartiene un CSV del database, dal prefisso ``db_prefix``."""
    prefisso = nome.split("_")[0]
    for lg, info in PROD_CONFIG.LEAGUES_CONFIG.items():
        if info["db_prefix"] == prefisso:
            return lg
    return None


def _svuota_cache_leghe() -> None:
    for lg in LEAGUES:
        PROD_ELO._ELO_ENGINES_CACHE.pop(lg, None)
        PROD_ELO._ELO_ENGINES_STAMP.pop(lg, None)


@contextlib.contextmanager
def database_fino_a_cutoff(cutoff: dict):
    """Ripunta ``config`` a una copia del database troncata per lega (Date <= cutoff).

    Dentro il blocco ``with`` ogni ``EloEngine`` di produzione (e ogni
    ``build_walker_table``) legge solo le partite fino al cutoff di ciascuna
    lega. Alla fine config e cache vengono ripristinati.
    """
    cutoff = leggi_cutoff(cutoff)
    src = Path(PROD_CONFIG.DATABASE_DIR)
    tmp = Path(tempfile.mkdtemp(prefix="elo_parity_cutoff_"))
    try:
        for f in sorted(src.glob("*.csv")):
            lg = _lega_del_file(f.name)
            if lg is None:
                raise AssertionError(f"CSV senza lega riconosciuta nel database: {f.name}")
            df = pd.read_csv(f, on_bad_lines="warn", low_memory=False)
            if "Date" in df.columns:
                d = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
                df = df[d.notna() & (d <= pd.Timestamp(cutoff[lg]))]
            df.to_csv(tmp / f.name, index=False)
        for f in sorted(src.glob("*.json")):
            shutil.copy(f, tmp / f.name)
        _svuota_cache_leghe()
        with _RepointDB(tmp):
            try:
                yield tmp
            finally:
                _svuota_cache_leghe()
    finally:
        _svuota_cache_leghe()
        shutil.rmtree(tmp, ignore_errors=True)
