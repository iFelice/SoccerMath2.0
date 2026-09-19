"""
market_prior.py - Prior di qualita' squadra DERIVATO DAI DATI (xG Understat),
candidato a sostituire la tabella scritta a mano ``config.MARKET_VALUES``.

STATO (19/09/2026): VALUTATO E NON ADOTTATO. Il walk-forward di
``audit/market_prior_xg.py`` (stesso protocollo dell'audit 11/09, CI bootstrap
appaiate, per lega e aggregato) mostra che il prior xG pre-registrato NON
migliora la tabella: Brier identico in VALIDATION 2024/25 ma peggiore in modo
significativo in TEST 2025/26 (+0.0042, CI [+0.0011; +0.0075]); nessuna delle
27 configurazioni della griglia batte la tabella in TEST; ROI mai
significativo. ``app.get_league_engine`` continua a usare ``MARKET_VALUES``.
Il modulo resta come strumento di audit (riproducibile, testato) per una
rivalutazione futura con piu' stagioni di archivio: NON e' collegato all'app.

Perche'
-------
``app.get_league_engine`` moltiplica attacco e divide difesa di ogni squadra per
un "fattore mercato" ricavato dal valore di rosa in milioni di euro, letto da un
dizionario a mano fermo a una data: da aggiornare ogni estate, in leakage sugli
audit storici, e privo di ogni squadra promossa o rinominata dopo l'ultima
revisione (default 50 -> fattore 0.925). Questo modulo ricava la STESSA
grandezza - un fattore di qualita' in [0.85, 1.25] - dall'archivio xG
per-partita gia' acquisito (``xG archivio <lega>.json``), in modo
point-in-time e senza interventi manuali al rollover.

Definizione (tutti i parametri sono pre-registrati in ``XgPriorParams`` e
verificati walk-forward in ``audit/market_prior_xg.py`` PRIMA dell'adozione)
-------------------------------------------------------------------------
Per la squadra ``t``, stagione ``s`` (anno di inizio), istante ``as_of``:

  q_prev  = xGD medio per partita di ``t`` nella stagione ``s-1``
            (xGD = xG fatti - xG concessi; media di lega = 0 per costruzione).
            Squadra promossa (assente in ``s-1``): media delle squadre
            retrocesse da ``s-1`` (quelle che ha sostituito) - regola
            dichiarata, nessun valore inventato. Nessuna stagione ``s-1`` in
            archivio: 0 (media di lega).
  prior   = persistence * q_prev              (regressione verso la media)
  q_cur   = xGD medio nelle partite di ``s`` GIOCATE PRIMA di ``as_of``
            (giorno del kickoff < giorno di as_of: politica previous_day di
            xg_archive), n_cur = numero di tali partite.
  q       = (prior_matches * prior + n_cur * q_cur) / (prior_matches + n_cur)
  factor  = clip(1 + slope * q, lo, hi)

Il fattore ha lo stesso intervallo [0.85, 1.25] della formula di produzione
(``1 + (log10(max(val,10)) - 2) / 4``), cosi' il confronto con la tabella
isola la FONTE dell'informazione, non la scala dell'effetto.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Sequence, Tuple

from season_calendar import season_start_year_of
from team_names import canonical_team_name
from xg_archive import is_played, parse_kickoff, parse_season, parse_xg

# Fattore neutro (= NO_MKT) quando non esiste alcuna informazione.
NEUTRAL_FACTOR = 1.0


@dataclass(frozen=True)
class XgPriorParams:
    """Parametri PRE-REGISTRATI (vedi audit/market_prior_xg.py)."""
    persistence: float = 0.65    # quota dello xGD della stagione precedente che si conserva
    prior_matches: float = 10.0  # peso del prior, in partite, nella media con la stagione corrente
    slope: float = 0.25          # xGD/partita -> fattore (q=+1.0 -> 1.25, q=-0.6 -> 0.85)
    lo: float = 0.85             # stesso clip del fattore mercato di produzione
    hi: float = 1.25


DEFAULT_PARAMS = XgPriorParams()


def _as_day(when) -> Optional[date]:
    if when is None:
        return None
    if isinstance(when, datetime):
        return when.date()
    if isinstance(when, date):
        return when
    try:  # pandas.Timestamp e simili
        return when.to_pydatetime().date()
    except AttributeError:
        return None


class XgPriorIndex:
    """Indice per (stagione, squadra) delle partite giocate con xG valido,
    costruito una volta sola dall'archivio per-partita di una lega."""

    def __init__(self, records: Sequence[dict], resolver=canonical_team_name):
        # (season, team) -> liste parallele ordinate per giorno: days, xgd
        self._days: Dict[Tuple[int, str], List[date]] = {}
        self._xgd: Dict[Tuple[int, str], List[float]] = {}
        self._teams: Dict[int, set] = {}
        rows: Dict[Tuple[int, str], List[Tuple[date, float]]] = {}
        for rec in records or []:
            if not isinstance(rec, dict):
                continue
            season = parse_season(rec.get("season"))
            if season is None:
                continue
            home = resolver(rec.get("home_team"))
            away = resolver(rec.get("away_team"))
            if not home or not away:
                continue
            # le squadre della stagione sono note dal calendario (anche non giocato)
            self._teams.setdefault(season, set()).update((home, away))
            if not is_played(rec):
                continue
            kickoff, _ = parse_kickoff(rec.get("date"))
            hx, ax = parse_xg(rec.get("home_xg")), parse_xg(rec.get("away_xg"))
            if kickoff is None or hx is None or ax is None:
                continue
            day = kickoff.date()
            rows.setdefault((season, home), []).append((day, hx - ax))
            rows.setdefault((season, away), []).append((day, ax - hx))
        for key, items in rows.items():
            items.sort(key=lambda x: x[0])
            self._days[key] = [d for d, _ in items]
            self._xgd[key] = [v for _, v in items]

    # ----------------------------------------------------------------- dati
    def seasons(self) -> List[int]:
        return sorted(self._teams)

    def teams(self, season: int) -> set:
        return set(self._teams.get(int(season), set()))

    def xgd_until(self, team: str, season: int, as_of=None) -> Tuple[float, int]:
        """(somma xGD, n partite) di ``team`` in ``season`` con giorno del
        kickoff < giorno di ``as_of`` (tutte se ``as_of`` e' None)."""
        key = (int(season), team)
        days = self._days.get(key)
        if not days:
            return 0.0, 0
        day = _as_day(as_of)
        n = len(days) if day is None else bisect_left(days, day)
        if n <= 0:
            return 0.0, 0
        return float(sum(self._xgd[key][:n])), n

    # --------------------------------------------------------------- prior
    def previous_season_quality(self, team: str, season: int, as_of=None) -> Tuple[Optional[float], str]:
        """xGD medio della stagione precedente: (valore, origine).

        origine: "previous_season" | "promoted" (media delle retrocesse) |
        "no_history" (nessuna stagione precedente in archivio -> None)."""
        prev = int(season) - 1
        if prev not in self._teams:
            return None, "no_history"
        tot, n = self.xgd_until(team, prev, as_of)
        if n > 0:
            return tot / n, "previous_season"
        relegated = self._teams.get(prev, set()) - self._teams.get(int(season), set())
        vals = []
        for other in relegated:
            t2, n2 = self.xgd_until(other, prev, as_of)
            if n2 > 0:
                vals.append(t2 / n2)
        if vals:
            return float(sum(vals) / len(vals)), "promoted"
        return None, "no_history"

    def quality(self, team: str, season: int, as_of=None,
                params: XgPriorParams = DEFAULT_PARAMS) -> dict:
        """Qualita' combinata ``q`` e la sua scomposizione (per log/audit)."""
        q_prev, source = self.previous_season_quality(team, season, as_of)
        prior = params.persistence * q_prev if q_prev is not None else 0.0
        tot_cur, n_cur = self.xgd_until(team, season, as_of)
        q_cur = tot_cur / n_cur if n_cur else 0.0
        denom = params.prior_matches + n_cur
        q = (params.prior_matches * prior + n_cur * q_cur) / denom if denom > 0 else 0.0
        return {"q": q, "q_prev": q_prev, "prior": prior, "q_cur": q_cur,
                "n_cur": n_cur, "source": source}

    def factor(self, team: str, season: int, as_of=None,
               params: XgPriorParams = DEFAULT_PARAMS) -> float:
        """Fattore di qualita' in [lo, hi] (stesso ruolo del fattore mercato)."""
        info = self.quality(team, season, as_of, params)
        if info["source"] == "no_history" and info["n_cur"] == 0:
            return NEUTRAL_FACTOR
        return factor_from_quality(info["q"], params)


def factor_from_quality(q: float, params: XgPriorParams = DEFAULT_PARAMS) -> float:
    if q is None or not math.isfinite(q):
        return NEUTRAL_FACTOR
    return max(params.lo, min(params.hi, 1.0 + params.slope * q))


def build_index(league: str, base_dir=None, records: Optional[Sequence[dict]] = None) -> XgPriorIndex:
    """Indice della lega dall'archivio per-partita (``xg_archive.load_archive``)."""
    if records is None:
        from xg_archive import load_archive  # import locale: evita cicli negli audit
        records = load_archive(league, base_dir)
    return XgPriorIndex(records)


def factors_for_teams(index: XgPriorIndex, teams: Sequence[str], as_of=None,
                      season: Optional[int] = None,
                      params: XgPriorParams = DEFAULT_PARAMS) -> Dict[str, float]:
    """Fattori per un insieme di squadre alla data ``as_of`` (default: adesso),
    per la stagione ``season`` (default: quella di ``as_of``)."""
    when = as_of or datetime.now()
    if season is None:
        season = season_start_year_of(when)
    return {t: index.factor(t, season, when, params) for t in teams}
