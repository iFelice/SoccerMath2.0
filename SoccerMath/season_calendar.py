"""
season_calendar.py - UNICA definizione del confine di stagione.

Modulo foglia (nessun import di progetto, come ``team_aliases``): puo' essere
importato da ``config``, ``prediction_registry``, ``app``, ``season_rollover``,
``xg_archive`` e dagli script di acquisizione senza creare cicli.

Regola
------
La stagione ``Y/Y+1`` inizia il 1° luglio dell'anno ``Y`` (``SEASON_START_MONTH
= 7``): una data con mese >= 7 appartiene alla stagione che inizia nel suo
anno, altrimenti a quella iniziata l'anno prima.

Perche' luglio e non agosto (verifica sul calendario reale, 2026-09-19)
-----------------------------------------------------------------------
Prima di questa unificazione convivevano due regole: ``mese >= 7`` (config,
season_rollover, xg_archive) e ``mese >= 8`` (app.calcola_stagione_calcolo,
prediction_registry.season_from_entry). La scelta e' stata fatta sui dati,
non per assunzione:

* su tutte le partite delle 5 leghe presenti negli archivi Understat e nei CSV
  (8.834 partite, stagioni 2022/23 -> 2026/27, calendario 2026/27 completo)
  il primo calcio d'inizio di una stagione non cade MAI prima del 5 agosto
  (2022/23: Bundesliga, Premier League, Ligue 1, stagione compressa dal
  Mondiale invernale) e l'ultimo MAI dopo il 4 giugno (2022/23: La Liga,
  Serie A). Nessuna partita a luglio: le due regole classificano in modo
  identico il 100% delle partite reali e coincidono con l'etichetta ``season``
  assegnata da Understat;
* il confine va quindi messo nella zona morta giugno-agosto: il 1° luglio
  dista 27 giorni dall'ultima partita osservata e 35 dal primo kickoff
  osservato; il 1° agosto disterebbe solo 4 giorni dal primo kickoff (5/8),
  cioe' un calendario anticipato di una settimana lo farebbe fallire;
* e' la stessa convenzione della fonte dati (``soccerdata.Understat
  .read_seasons``: ``season_id = year if month >= 7 else year - 1``);
* limite dichiarato: nella stagione 2019/20 (pandemia) Premier League e La
  Liga finirono a luglio e la Serie A il 2 agosto; nessuna regola a mese
  intero classifica correttamente quel caso (la Serie A cadrebbe fuori anche
  con agosto). Fuori dal perimetro dati e trattato come anomalia nota.

Qui vive anche il TERMINE della tolleranza pre-stagione (15 settembre
dell'anno di inizio stagione): il limite temporale oltre il quale l'assenza
della stagione nuova dai dati smette di essere un ritardo fisiologico e
diventa un guasto da segnalare (vedi ``pre_season_deadline``).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional, Union

# Mese in cui inizia la nuova stagione (1 = gennaio ... 7 = luglio).
SEASON_START_MONTH = 7

# Ampiezza della finestra stagionale usata da tutta la pipeline: stagione
# corrente + 4 precedenti (archivio xG Understat, HISTORICAL_SEASONS, PPDA).
SEASON_WINDOW = 5

# Termine della tolleranza pre-stagione (mese e giorno): ultimo giorno in cui
# l'assenza della stagione Y/Y+1 dai dati Understat e' considerata innocua
# ("non ancora iniziata") invece che un guasto di acquisizione.
#
# Valore scelto SUI DATI, non per assunzione: su tutte le 25 combinazioni
# lega x stagione 2022/23 -> 2026/27 presenti negli archivi (calendari
# completi, incluso il post-Mondiale 2026/27) il primo kickoff piu' tardivo
# e' stato il 28/08/2026 (Bundesliga) e al 15/9 di ogni stagione ogni lega
# aveva gia' almeno 27 partite giocate, contro le 10 richieste dalla pipeline
# (MIN_TEAMS). Un 15 settembre con meno di 10 partite giocate non e' mai
# successo: se accade e' o un guasto (scrape rotto, date illeggibili, cutoff
# sbagliato) o un calendario eccezionale, e in entrambi i casi la catena deve
# fallire in modo visibile invece di tollerare in silenzio.
PRE_SEASON_TOLERANCE_MONTH = 9
PRE_SEASON_TOLERANCE_DAY = 15

DateLike = Union[datetime, date]


def season_start_year(year: int, month: int) -> int:
    """Anno di inizio della stagione a cui appartiene (anno, mese)."""
    year = int(year)
    month = int(month)
    if not 1 <= month <= 12:
        raise ValueError(f"mese non valido: {month!r}")
    return year if month >= SEASON_START_MONTH else year - 1


def season_start_year_of(when: DateLike) -> int:
    """Anno di inizio stagione di una data/datetime (naive o aware)."""
    return season_start_year(when.year, when.month)


def season_label(start_year: int, short: bool = False) -> str:
    """``2026 -> "2026/2027"`` (``short=True``: ``"2026/27"``)."""
    start_year = int(start_year)
    end = start_year + 1
    return f"{start_year}/{end % 100:02d}" if short else f"{start_year}/{end}"


def soccerdata_season_code(start_year: int) -> str:
    """Codice stagione di soccerdata: ``2026 -> "2627"``."""
    start_year = int(start_year)
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def season_window(current_start_year: int, size: int = SEASON_WINDOW) -> List[int]:
    """Ultime ``size`` stagioni (anni di inizio) in ordine crescente, corrente
    inclusa: ``season_window(2026) -> [2022, 2023, 2024, 2025, 2026]``."""
    size = int(size)
    if size < 1:
        raise ValueError(f"size deve essere >= 1, trovato {size}")
    current_start_year = int(current_start_year)
    return list(range(current_start_year - size + 1, current_start_year + 1))


def parse_season_start_year(value) -> Optional[int]:
    """``"2026/2027"``, ``"2026/27"``, ``"2627"``, ``2026`` -> 2026 (None se
    illeggibile). Versione minimale, senza dipendenze, per i chiamanti che
    devono solo riconoscere l'anno di inizio."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit() and len(text) == 4:
        if text.startswith(("19", "20")):
            return int(text)
        first, second = int(text[:2]), int(text[2:])
        if second == (first + 1) % 100:
            return 2000 + first
        return None
    head = text.split("/")[0].split("-")[0].strip()
    if head.isdigit() and len(head) == 4:
        return int(head)
    return None


def pre_season_deadline(season_start_year: int) -> date:
    """Ultimo giorno in cui l'assenza della stagione indicata e' tollerata:
    ``2026 -> 15/09/2026`` (vedi ``PRE_SEASON_TOLERANCE_*`` per la
    motivazione sui dati)."""
    return date(int(season_start_year), PRE_SEASON_TOLERANCE_MONTH,
                PRE_SEASON_TOLERANCE_DAY)


def within_pre_season_tolerance(season_start_year: int,
                                when: Optional[DateLike] = None) -> bool:
    """True se ``when`` (default: adesso, data UTC) e' ancora entro la
    finestra in cui l'assenza della stagione ``season_start_year`` e'
    innocua, cioe' ``when`` <= 15 settembre dell'anno di inizio stagione.

    Confronto a livello di DATA (il fuso e' irrilevante su un confine a
    mesi di distanza). ``when`` accetta date, datetime o None (= oggi).
    E' un limite solo SUPERIORE: prima del 1° luglio la stagione non esiste
    ancora e l'assenza resta ovviamente innocua."""
    if when is None:
        when = datetime.now(timezone.utc)
    if isinstance(when, datetime):
        when = when.date()
    return when <= pre_season_deadline(season_start_year)
