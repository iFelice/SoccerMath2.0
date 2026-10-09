"""
market_odds.py — Quote 1X2 dal vivo e probabilita' di mercato (de-vig).

COSA FA QUESTO MODULO
---------------------
Legge ``SoccerMath/database/live_odds.json`` (scritto SOLO dal workflow
``.github/workflows/live_odds.yml`` tramite ``update_live_odds.py``: l'app non
chiama MAI The Odds API) e ricava, per ogni partita, la PROBABILITA' DI MERCATO
e la QUOTA di mercato con cui il Top Mix sceglie.

Perche' il mercato decide (numeri, non opinioni — PR #49,
``audit/results/onex2_market_test.md`` §4 e §4d):

* scelte del mercato (B365 pre-chiusura, de-vig proporzionale): 1302, hit 67,5%;
* scelte del modello (blend 0,25 Poisson + 0,75 Elo): 1479, hit 62,6%;
* scelte del modello CON accordo del mercato: 1144, hit 68,2%;
* scelte del modello SENZA accordo del mercato: 335, hit 43,6%.

Il modello non viene buttato: serve soprattutto a SCARTARE (la colonna
"d'accordo" del Top Mix) e resta registrato nel registro ombra.

REGOLE DI CALCOLO (tutte pure, nessuna rete, nessuna cache)
-----------------------------------------------------------
1. De-vig PROPORZIONALE (``devig_proporzionale``): ``p_i = (1/o_i) / sum(1/o_j)``,
   la stessa formula di ``backtest_experiment_all.devig_1x2`` usata dalla PR #49.
   La somma delle tre probabilita' e' 1 per costruzione (verificata dai test).
2. Fonte della probabilita', riga per riga (campo ``fonte``):
   * ``pinnacle``    Pinnacle presente con una terna h2h completa: e' il book
                     con la LogLoss migliore fra quelli misurati
                     (``audit/results/bookmaker_source_test.md`` §1a: 0,9634
                     contro 0,9719 di Bet365) ed e' l'unico dei book dei CSV
                     disponibile nella fonte dal vivo su tutte e 5 le leghe;
   * ``media_libri`` Pinnacle manca: RISERVA sulla media delle probabilita'
                     de-vigate dei book disponibili (stesso criterio del
                     "consenso" di ``bookmaker_source_test.md`` §1a:
                     EQUIVALENTE a Bet365 alla regola C1-C2-C3). Il numero di
                     book usati sta in ``n_libri``;
   * ``nessuna_quota`` nessuna terna valida: la partita NON entra nel Top Mix
                     e viene SEGNALATA (mai inventata, mai silently scartata).
3. Quota di mercato mostrata = la quota della fonte che ha prodotto la
   probabilita' (Pinnacle se ``fonte=pinnacle``, media dei book se
   ``media_libri``): il calcolatore di multipla confronta probabilita' e quota
   della STESSA fonte, non di due fonti diverse.

Il modulo NON importa streamlit: e' usabile da app, workflow e replay offline.
"""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from team_names import resolve_team_name

# Logger nominato (non la root): i test possono intercettare i suoi messaggi e
# verificare che un nome non abbinato venga davvero LOGGATO, non ignorato.
LOG = logging.getLogger("market_odds")

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------
ESITI: Tuple[str, str, str] = ("1", "X", "2")
ETICHETTE_ESITO = {"1": "1 (casa)", "X": "X (pareggio)", "2": "2 (trasferta)"}

LIVE_ODDS_FILE = "live_odds.json"
SCHEMA_LIVE_ODDS = "soccermath_live_odds_v1"

# Bookmaker primario e etichette della fonte (campo ``fonte`` della riga).
BOOKMAKER_PRIMARIO = "pinnacle"
FONTE_PINNACLE = "pinnacle"
FONTE_MEDIA_LIBRI = "media_libri"
FONTE_ASSENTE = "nessuna_quota"
FONTI_NOTE = (FONTE_PINNACLE, FONTE_MEDIA_LIBRI, FONTE_ASSENTE)

# Soglie del selettore di mercato. 0,55 e' la soglia di produzione del Top Mix
# (``app.seleziona_riga_top_mix`` con Elo) ed e' la soglia usata dalla PR #49
# per le scelte di mercato: cambiarla cambia i numeri del replay.
SOGLIA_TOPMIX_MERCATO = 0.55
# "D'accordo": modello e mercato sullo STESSO esito, entrambi >= 0,55
# (definizione della PR #49 §4d, tabella B).
SOGLIA_ACCORDO = 0.55

# Calcolatore di multipla: al massimo 5 righe (vincolo della commessa).
MASSIMO_RIGHE_MULTIPLA = 5
MINIMO_RIGHE_MULTIPLA = 1

# Tolleranza per le verifiche di somma/arrotondamento.
TOLLERANZA = 1e-9

# Avvisi gia' dati, per non ripetere lo stesso messaggio a ogni ricarica
# (vedi il ramo "file assente" di carica_quote_live).
_AVVISI_DATI: set = set()


# ---------------------------------------------------------------------------
# 1. De-vig proporzionale
# ---------------------------------------------------------------------------
def devig_proporzionale(quote: Sequence[float]) -> Optional[Tuple[float, float, float]]:
    """De-vig PROPORZIONALE di una terna 1/X/2. Ritorna ``None`` se non valida.

    ``p_i = (1/o_i) / sum_j(1/o_j)``: la somma delle tre probabilita' e' 1 per
    costruzione. E' la stessa formula di ``backtest_experiment_all.devig_1x2``
    (la fonte usata dalla PR #49), riscritta senza pandas per restare una foglia.

    Non valida = quote mancanti, non numeriche, non finite o <= 1,0 (una quota
    <= 1 darebbe una probabilita' implicita >= 1 e un overround senza senso).
    """
    if quote is None or len(quote) != 3:
        return None
    inverse = []
    for q in quote:
        if isinstance(q, bool) or not isinstance(q, (int, float)):
            return None
        qf = float(q)
        if not math.isfinite(qf) or qf <= 1.0:
            return None
        inverse.append(1.0 / qf)
    totale = inverse[0] + inverse[1] + inverse[2]
    if totale <= 0.0:
        return None
    return (inverse[0] / totale, inverse[1] / totale, inverse[2] / totale)


def _quota_num(value: Any) -> Optional[float]:
    """Quota come float, o None se non e' un numero finito > 1."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if not math.isfinite(v) or v <= 1.0:
        return None
    return v


def ternaria_h2h(libro: Dict[str, Any]) -> Optional[Tuple[float, float, float]]:
    """Terna (casa, pareggio, trasferta) di UN libro, o None se incompleta.

    Accetta la forma scritta da ``update_live_odds.py`` (``{"h2h": {...}}``) e
    quella piatta degli snapshot di prova (``{"home": ..., "draw": ..., "away": ...}``).
    """
    if not isinstance(libro, dict):
        return None
    h2h = libro.get("h2h")
    src = h2h if isinstance(h2h, dict) else libro
    home = _quota_num(src.get("home"))
    draw = _quota_num(src.get("draw"))
    away = _quota_num(src.get("away"))
    if home is None or draw is None or away is None:
        return None
    return (home, draw, away)


def probabilita_mercato(
    libri: Iterable[Dict[str, Any]],
    bookmaker_primario: str = BOOKMAKER_PRIMARIO,
) -> Dict[str, Any]:
    """Probabilita' e quota di mercato di UNA partita, con la fonte dichiarata.

    ``libri`` = lista dei bookmaker della partita (elementi con ``key`` e
    ``h2h``). Regola (vedi il docstring del modulo):

    * Pinnacle con terna valida -> de-vig di Pinnacle, quota di Pinnacle;
    * altrimenti -> RISERVA sulla media delle probabilita' de-vigate dei libri
      con terna valida e sulla media delle loro quote, fonte ``media_libri``;
    * nessun libro valido -> ``probs is None``, fonte ``nessuna_quota``.

    Ritorna un dict con ``probs`` (dict 1/X/2 o None), ``odds`` (dict 1/X/2 o
    None), ``fonte``, ``n_libri`` (libri con terna valida), ``n_libri_totale``,
    ``primario_presente`` e ``libri_usati`` (chiavi dei libri entrati nel conto).
    """
    lista = [l for l in (libri or []) if isinstance(l, dict)]
    primario_presente = False
    valide: List[Tuple[str, Tuple[float, float, float], Tuple[float, float, float]]] = []
    for libro in lista:
        chiave = str(libro.get("key") or "").strip()
        terna = ternaria_h2h(libro)
        if chiave.lower() == bookmaker_primario:
            primario_presente = True
        if terna is None:
            continue
        prob = devig_proporzionale(terna)
        if prob is None:
            continue
        valide.append((chiave, prob, terna))

    if not valide:
        return {"probs": None, "odds": None, "fonte": FONTE_ASSENTE, "n_libri": 0,
                "n_libri_totale": len(lista), "primario_presente": primario_presente,
                "libri_usati": []}

    scelta = [v for v in valide if v[0].lower() == bookmaker_primario]
    if scelta:
        _chiave, prob, terna = scelta[0]
        fonte = FONTE_PINNACLE
        usate = [scelta[0][0]]
    else:
        n = len(valide)
        prob = tuple(sum(v[1][k] for v in valide) / n for k in range(3))
        terna = tuple(sum(v[2][k] for v in valide) / n for k in range(3))
        fonte = FONTE_MEDIA_LIBRI
        usate = [v[0] for v in valide]

    return {
        "probs": {esito: float(prob[k]) for k, esito in enumerate(ESITI)},
        "odds": {esito: float(terna[k]) for k, esito in enumerate(ESITI)},
        "fonte": fonte,
        "n_libri": len(valide),
        "n_libri_totale": len(lista),
        "primario_presente": primario_presente,
        "libri_usati": usate,
    }


# ---------------------------------------------------------------------------
# 2. Lettura del file scritto dal workflow
# ---------------------------------------------------------------------------
def percorso_quote_live(database_dir: Optional[str] = None) -> str:
    """Percorso di ``live_odds.json`` (stessa cartella dei CSV del database)."""
    if database_dir:
        return os.path.join(str(database_dir), LIVE_ODDS_FILE)
    from config import DATABASE_DIR  # import tardivo: questo modulo resta una foglia
    return os.path.join(str(DATABASE_DIR), LIVE_ODDS_FILE)


def carica_quote_live(percorso: Optional[str] = None,
                      database_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Legge ``live_odds.json``. Ritorna ``None`` (con log) se manca o non vale.

    L'assenza del file NON e' un errore dell'app: significa che il workflow non
    ha ancora scritto (prima esecuzione, oppure quota crediti esaurita e file
    precedente conservato). Il chiamante lo dice all'utente, non inventa quote.
    """
    path = percorso or percorso_quote_live(database_dir)
    if not os.path.exists(path):
        # Prima del primo giro del workflow il file NON esiste: e' lo stato
        # atteso, non un errore. Si avvisa una volta per processo e poi in
        # DEBUG, cosi' chi ha il workflow attivo non si vede ripetere lo stesso
        # avviso a ogni ricarica e chi non ce l'ha lo legge subito.
        if "file_assente" in _AVVISI_DATI:
            LOG.debug("Quote live: %s ancora assente.", path)
        else:
            _AVVISI_DATI.add("file_assente")
            LOG.warning("Quote live: %s non presente (il workflow non ha ancora "
                        "scritto): il Top Mix di mercato non e' calcolabile.", path)
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError) as e:
        LOG.warning("Quote live: %s non leggibile (%s: %s).", path, type(e).__name__, e)
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("leghe"), dict):
        LOG.warning("Quote live: %s senza la chiave 'leghe': file ignorato.", path)
        return None
    return payload


def eventi_quote(payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Tutti gli eventi del payload, con la lega di provenienza aggiunta."""
    out: List[Dict[str, Any]] = []
    for lega, blocco in ((payload or {}).get("leghe") or {}).items():
        if not isinstance(blocco, dict):
            continue
        for evento in blocco.get("eventi") or []:
            if isinstance(evento, dict):
                out.append({**evento, "lega": lega})
    return out


# ---------------------------------------------------------------------------
# 3. Abbinamento dei nomi (nessun fallback silenzioso)
# ---------------------------------------------------------------------------
def _kickoff(evento: Dict[str, Any]) -> Optional[datetime]:
    """``commence_time`` ISO 8601 -> datetime aware UTC (None se non valido)."""
    valore = evento.get("commence_time")
    if not isinstance(valore, str) or not valore:
        return None
    try:
        dt = datetime.fromisoformat(valore.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def indice_partite(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Indice degli eventi per coppia di nomi canonici ``(casa, trasferta)``.

    I nomi della fonte quote passano dal resolver di produzione
    (``team_names.resolve_team_name``): un nome non riconosciuto NON viene
    indovinato (nessun fuzzy matching) e la partita resta fuori dall'indice,
    con un WARNING nel log che dice il nome grezzo. Le partite non abbinate
    sono anche nel campo ``non_abbinati`` del risultato, cosi' l'UI e i test
    possono elencarle per nome invece di scoprirle dal silenzio.

    Ritorna ``{"indice": {(casa, trasferta): [evento, ...]}, "non_abbinati": [...],
    "n_eventi": int, "n_indicizzati": int}``.
    """
    indice: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    non_abbinati: List[Dict[str, Any]] = []
    n_eventi = 0
    for evento in eventi_quote(payload):
        n_eventi += 1
        home_raw = evento.get("home_team")
        away_raw = evento.get("away_team")
        home_res = resolve_team_name(home_raw)
        away_res = resolve_team_name(away_raw)
        if not (home_res.mapped and away_res.mapped):
            for ruolo, res in (("casa", home_res), ("trasferta", away_res)):
                if res.mapped:
                    continue
                LOG.warning(
                    "Quote live: nome squadra NON abbinato (%s) '%s' -> '%s' "
                    "(%s vs %s, %s): partita senza quote, nessun fallback.",
                    ruolo, res.raw, res.canonical, home_raw, away_raw,
                    evento.get("lega") or "?")
            non_abbinati.append({
                "lega": evento.get("lega"), "id": evento.get("id"),
                "commence_time": evento.get("commence_time"),
                "home_raw": home_raw, "away_raw": away_raw,
                "home_canonico": home_res.canonical, "away_canonico": away_res.canonical,
                "home_riconosciuto": bool(home_res.mapped),
                "away_riconosciuto": bool(away_res.mapped),
            })
            continue
        chiave = (home_res.canonical, away_res.canonical)
        indice.setdefault(chiave, []).append(evento)
    return {"indice": indice, "non_abbinati": non_abbinati,
            "n_eventi": n_eventi, "n_indicizzati": sum(len(v) for v in indice.values())}


def cerca_quote(indice: Dict[Tuple[str, str], List[Dict[str, Any]]],
                home: str, away: str,
                utc_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Evento della fonte quote per ``(home, away)``: il piu' vicino al kickoff.

    Una coppia casa/trasferta si gioca due volte a stagione, ma l'ordine
    casa-trasferta distingue le due partite; se la fonte ne riporta piu' di una
    (doppione o anticipo/posticipo) si prende quella con ``commence_time`` piu'
    vicino a ``utc_date`` della partita football-data. Se ``utc_date`` manca o
    non e' valido si prende la prima: la scelta e' dichiarata nel campo
    ``scelta_su_piu_eventi`` del risultato.

    Ritorna ``None`` se la coppia non e' nell'indice (nessuna quota: il chiamante
    esclude la partita dal Top Mix e la segnala).
    """
    home_res = resolve_team_name(home)
    away_res = resolve_team_name(away)
    if not (home_res.mapped and away_res.mapped):
        return None
    candidati = indice.get((home_res.canonical, away_res.canonical)) or []
    if not candidati:
        return None
    if len(candidati) == 1:
        return candidati[0]
    riferimento = None
    if isinstance(utc_date, str) and utc_date:
        try:
            dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
            riferimento = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            riferimento = None
    if riferimento is None:
        return candidati[0]
    return min(candidati, key=lambda e: abs((_kickoff(e) or riferimento) - riferimento))


# ---------------------------------------------------------------------------
# 4. Calcolatore di multipla
# ---------------------------------------------------------------------------
AVVISO_INDIPENDENZA = (
    "Le probabilita' combinate moltiplicano le probabilita' delle singole "
    "partite: il calcolo presume che gli esiti siano INDIPENDENTI. Non lo sono "
    "del tutto (stesse squadre, stessa giornata, infortuni e meteo condivisi), "
    "quindi la probabilita' combinata reale puo' essere diversa da quella "
    "mostrata, in entrambe le direzioni."
)


def multipla(righe: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Multipla di 1..5 righe del Top Mix di mercato.

    Ogni riga deve portare ``prob`` (probabilita' di mercato, frazione in
    (0,1)) e ``quota`` (quota decimale > 1). Calcola:

    * ``probabilita_combinata`` = prodotto delle probabilita' (ipotesi di
      indipendenza, dichiarata in ``avviso``);
    * ``quota_equa`` = 1 / probabilita_combinata (la quota a margine zero);
    * ``quota_offerta`` = prodotto delle quote selezionate;
    * ``edge`` = quota_offerta * probabilita_combinata - 1 (positivo = la quota
      offerta paga piu' della quota equa).

    Ritorna ``{"ok": False, "errore": ...}`` se la selezione non e' valida:
    nessun numero viene inventato.
    """
    lista = list(righe or [])
    if len(lista) < MINIMO_RIGHE_MULTIPLA:
        return {"ok": False, "errore": f"Seleziona almeno {MINIMO_RIGHE_MULTIPLA} riga."}
    if len(lista) > MASSIMO_RIGHE_MULTIPLA:
        return {"ok": False,
                "errore": f"Al massimo {MASSIMO_RIGHE_MULTIPLA} righe (selezionate {len(lista)})."}

    prob_parziale = 1.0
    quota_parziale = 1.0
    dettagli: List[Dict[str, Any]] = []
    for i, riga in enumerate(lista, start=1):
        if not isinstance(riga, dict):
            return {"ok": False, "errore": f"Riga {i}: formato non valido."}
        prob = riga.get("prob")
        quota = riga.get("quota")
        if isinstance(prob, bool) or not isinstance(prob, (int, float)) \
                or not math.isfinite(float(prob)) or not (0.0 < float(prob) < 1.0):
            return {"ok": False, "errore": f"Riga {i}: probabilita' non valida ({prob!r})."}
        q = _quota_num(quota)
        if q is None:
            return {"ok": False, "errore": f"Riga {i}: quota non valida ({quota!r})."}
        prob_parziale *= float(prob)
        quota_parziale *= q
        dettagli.append({"n": i, "partita": riga.get("partita") or "",
                         "esito": riga.get("esito") or "", "prob": float(prob), "quota": q})

    if prob_parziale <= 0.0:
        return {"ok": False, "errore": "Probabilita' combinata non positiva."}
    quota_equa = 1.0 / prob_parziale
    return {
        "ok": True,
        "n_righe": len(lista),
        "righe": dettagli,
        "probabilita_combinata": prob_parziale,
        "probabilita_combinata_pct": round(prob_parziale * 100.0, 4),
        "quota_equa": quota_equa,
        "quota_offerta": quota_parziale,
        "edge": quota_parziale * prob_parziale - 1.0,
        "avviso": AVVISO_INDIPENDENZA,
    }
