"""lista_giocate.py — Generazione e ottimizzazione lista giocate (versione lista_giocate_v1).

Modulo di produzione puro (senza dipendenze da Streamlit o UI).
Fornisce:
1. Stima quota bet365 per 1X2 e Doppia Chance (PR #58 punto D).
2. Estrazione e calcolo delle giocate candidate da snapshot quote live (Pinnacle de-vig / media libri).
3. Ricerca esaustiva della proposta di multipla (1-4 eventi, quota [2.00, 3.00], max prob).
4. Costruzione record per il registro ombra (famiglia multipla_proposta_v1, immutabile per settimana).
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import market_odds as mo
import prediction_registry as pr

LISTA_GIOCATE_VERSION = "lista_giocate_v1"
FAMIGLIA_OMBRA_MULTIPLA_PROPOSTA = "multipla_proposta_v1"
SELECTOR_VERSION_MULTIPLA_PROPOSTA = "multipla_proposta_v1"

PARAMETRI_STIMA_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "database",
    "parametri_b365_stima_v1.json"
)

_PARAMETRI_CACHE: Optional[Dict[str, Any]] = None


def carica_parametri_stima(percorso: Optional[str] = None) -> Dict[str, Any]:
    """Carica i parametri di stima quota bet365 salvati nel file versionato."""
    global _PARAMETRI_CACHE
    p = percorso or PARAMETRI_STIMA_FILE
    if _PARAMETRI_CACHE is not None and percorso is None:
        return _PARAMETRI_CACHE
    with open(p, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if percorso is None:
        _PARAMETRI_CACHE = data
    return data


def fascia_quota_equa(fair_odd: float, fasce: Sequence[Dict[str, Any]]) -> str:
    """Assegna la fascia di quota equa [lo, hi)."""
    for f in fasce:
        if f["min"] <= fair_odd < f["max"]:
            return f["label"]
    return "≥5,00"


def stima_quota_b365(p: float, lega: str, tipo: str = "1X2", params: Optional[Dict[str, Any]] = None) -> Optional[float]:
    """Stima quota bet365 per un esito dato p de-vig Pinnacle (PR #58 punto D).

    q_hat = 1.0 / (p * R(lega, tipo, fascia))
    """
    if p is None or not math.isfinite(p) or p <= 0.0 or p > 1.0:
        return None
    par = params or carica_parametri_stima()
    fair_odd = 1.0 / p
    fascia = fascia_quota_equa(fair_odd, par["fasce_quota_equa"])
    
    r_loc = par.get("R_loc", {})
    r_tipo_map = par.get("R_tipo", {})
    r_glob = par.get("R_glob", {})
    r_fixed = float(par.get("R_fixed", 1.0519))
    
    key_loc = f"{lega}|{tipo}|{fascia}"
    if key_loc in r_loc:
        r = r_loc[key_loc]
    elif f"{tipo}|{fascia}" in r_tipo_map:
        r = r_tipo_map[f"{tipo}|{fascia}"]
    elif tipo in r_glob:
        r = r_glob[tipo]
    else:
        r = r_fixed
        
    return 1.0 / (p * r)


def stima_quota_b365_1x2(p: float, lega: str, params: Optional[Dict[str, Any]] = None) -> Optional[float]:
    """Stima quota bet365 per esito 1X2 dato p de-vig Pinnacle."""
    return stima_quota_b365(p, lega, tipo="1X2", params=params)


def stima_quota_b365_dc(qa: Optional[float], qb: Optional[float]) -> Optional[float]:
    """Stima quota bet365 per doppia chance: 1 / (1/qa + 1/qb)."""
    if qa is None or qb is None or not math.isfinite(qa) or not math.isfinite(qb):
        return None
    if qa <= 0.0 or qb <= 0.0:
        return None
    denom = (1.0 / qa) + (1.0 / qb)
    if denom <= 0.0:
        return None
    return 1.0 / denom


def parse_commence_time(ts: Any) -> Optional[datetime]:
    """Interpreta ISO datetime con offset o Z."""
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        dt = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Presentazione in parole e periodo di gioco (commessa presentazione TOP MIX).
#
# Tutte funzioni PURE: nessuna rete, nessun file, nessun streamlit. La data
# "adesso" arriva sempre dal chiamante (o dalla cucitura unica
# ``market_odds._adesso_utc``), cosi' i test possono congelare l'orologio su
# un istante fissato.
# ---------------------------------------------------------------------------

ROMA = ZoneInfo("Europe/Rome")

GIORNI_SETTIMANA_IT = ("lunedì", "martedì", "mercoledì", "giovedì",
                       "venerdì", "sabato", "domenica")

MESE_IT = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
           "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre")

# Etichette dei due valori del controllo "Periodo" (punto 8).
PERIODO_GIORNATA = "giornata"
PERIODO_TUTTE = "tutte"
ETICHETTA_PERIODO_GIORNATA = "Questa giornata (fino a lunedì)"
ETICHETTA_PERIODO_TUTTE = "Tutte le partite in programma"

# Frase mostrata sopra la sezione quando almeno una partita visibile e' lontana.
FRASE_QUOTE_PROVVISORIE = (
    "Le quote delle partite lontane vengono aggiornate ogni giorno. "
    "Per una giocata affidabile guarda la lista il venerdì o il sabato."
)
MARCATORE_QUOTE_PROVVISORIE = "quote provvisorie: possono cambiare"


def _a_roma(dt: datetime) -> datetime:
    """Un datetime aware convertito in Europe/Rome (naive trattato come UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ROMA)


def _adesso(istante: Optional[datetime]) -> datetime:
    """L'istante del calcolo: parametro esplicito o la cucitura condivisa."""
    return istante if istante is not None else mo._adesso_utc()


def giocata_in_parole(giocata: str, home: str, away: str) -> str:
    """Traduce un esito 1X2 / doppia chance in parole (punto 3).

    1  -> "Vince <casa>"             X  -> "Pareggio"
    2  -> "Vince <trasferta>"        12 -> "Non finisce in pareggio"
    1X -> "<casa> non perde"         X2 -> "<trasferta> non perde"

    La sigla NON e' nel risultato: la riattacca chi mostra
    (``giocata_in_parole_con_sigla``), perche' il formato ("fra parentesi,
    piccola") dipende dal contesto (cella di tabella o testo HTML).
    """
    g = str(giocata or "").strip()
    if g == "1":
        return f"Vince {home}"
    if g == "X":
        return "Pareggio"
    if g == "2":
        return f"Vince {away}"
    if g == "1X":
        return f"{home} non perde"
    if g == "X2":
        return f"{away} non perde"
    if g == "12":
        return "Non finisce in pareggio"
    raise ValueError(f"Giocata non traducibile: {giocata!r}")


def giocata_in_parole_con_sigla(giocata: str, home: str, away: str) -> str:
    """Come ``giocata_in_parole`` con la sigla fra parentesi: "Vince Roma (1)"."""
    coda = ""
    try:
        parole = giocata_in_parole(giocata, home, away)
    except ValueError:
        # Valore fuori dal repertorio: si mostra com'e', mai una frase inventata.
        parole = str(giocata or "")
    if str(giocata or "").strip() and parole != str(giocata or "").strip():
        coda = f" ({str(giocata).strip()})"
    return parole + coda


def quando_italiano(ts: Any) -> str:
    """Data di una partita in parole: "sabato 17/10, ore 15:00" (Europe/Rome)."""
    dt = parse_commence_time(ts) if isinstance(ts, str) else ts
    if dt is None:
        return "data n/d"
    dt = _a_roma(dt)
    return (f"{GIORNI_SETTIMANA_IT[dt.weekday()]} {dt.day:02d}/{dt.month:02d}, "
            f"ore {dt.hour:02d}:{dt.minute:02d}")


def riesce_circa(probabilita: Any) -> str:
    """Probabilita' in parole: 0.4732 -> "47 volte su 100"."""
    p = float(probabilita)
    n = int(round(p * 100.0))
    n = max(0, min(100, n))
    return f"{n} volte su 100"


def quota_italiana(quota: Any, nd: str = "n/d") -> str:
    """Quota decimale con la virgola italiana: 2.0 -> "2,00"."""
    try:
        q = float(quota)
    except (TypeError, ValueError):
        return nd
    if not math.isfinite(q):
        return nd
    return f"{q:.2f}".replace(".", ",")


def paga_circa(quota: Any) -> str:
    """Quota in parole: 2.0 -> "2,00 volte la puntata"."""
    return f"{quota_italiana(quota)} volte la puntata"


def ritorno_su_100(probabilita: Any, quota: Any) -> int:
    """100 € giocati x probabilita' x quota, arrotondati all'euro (punto 1)."""
    return int(round(100.0 * float(probabilita) * float(quota)))


# ---------------------------------------------------------------------------
# Periodo di gioco: la giornata fino al lunedì (punto 8)
# ---------------------------------------------------------------------------

def lunedi_gioco(istante: Optional[datetime] = None) -> datetime:
    """Primo lunedì successivo o coincidente con l'istante, alle 23:59:59 (Europe/Rome).

    E' il confine della "giornata" di gioco: di venerdì vale il lunedì tre
    giorni dopo, di lunedì vale il lunedì stesso. Il calcolo vive nel fuso
    Europe/Rome, quindi il cambio ora legale/solare e' rispettato: il lunedì
    dopo l'ultima domenica di ottobre chiude a 23:59 CET (UTC+1), non CEST.
    """
    ora = _a_roma(_adesso(istante))
    giorni_al_lunedi = (7 - ora.weekday()) % 7   # 0 se oggi e' gia' lunedì
    lunedi = (ora + timedelta(days=giorni_al_lunedi)).date()
    return datetime(lunedi.year, lunedi.month, lunedi.day,
                    23, 59, 59, 999999, tzinfo=ROMA)


def giocate_nel_periodo(
    giocate: Sequence[Dict[str, Any]],
    istante: Optional[datetime] = None,
    periodo: str = PERIODO_GIORNATA,
) -> List[Dict[str, Any]]:
    """Le giocate il cui calcio d'inizio rientra nel periodo scelto (punto 8).

    Sono ammesse solo partite NON ancora iniziate (``commence_time`` dopo
    l'istante del calcolo). Con ``periodo='giornata'`` (predefinito) il
    kickoff dev'essere anche entro le 23:59 del primo lunedì successivo o
    coincidente con l'istante; con ``periodo='tutte'`` non c'e' limite
    superiore. Una giocata senza data valida non entra mai: una partita
    senza orario non puo' onorare nessun periodo.
    """
    ora = _adesso(istante)
    if ora.tzinfo is None:
        ora = ora.replace(tzinfo=timezone.utc)
    fine = lunedi_gioco(ora) if periodo == PERIODO_GIORNATA else None
    out: List[Dict[str, Any]] = []
    for g in giocate or []:
        dt = parse_commence_time(g.get("commence_time"))
        if dt is None or dt <= ora:
            continue
        if fine is not None and _a_roma(dt) > fine:
            continue
        out.append(g)
    return out


def prossima_partita(
    giocate: Sequence[Dict[str, Any]],
    istante: Optional[datetime] = None,
) -> Optional[datetime]:
    """Il kickoff più vicino fra le giocate non ancora iniziate (o None)."""
    ora = _adesso(istante)
    if ora.tzinfo is None:
        ora = ora.replace(tzinfo=timezone.utc)
    kickoff = []
    for g in giocate or []:
        dt = parse_commence_time(g.get("commence_time"))
        if dt is not None and dt > ora:
            kickoff.append(dt)
    return min(kickoff) if kickoff else None


def e_partita_provvisoria(g: Dict[str, Any], istante: Optional[datetime] = None,
                          giorni: int = 3) -> bool:
    """True se la partita inizia fra PIU' di ``giorni``: le sue quote possono cambiare."""
    dt = parse_commence_time(g.get("commence_time"))
    if dt is None:
        return False
    ora = _adesso(istante)
    if ora.tzinfo is None:
        ora = ora.replace(tzinfo=timezone.utc)
    return (dt - ora) > timedelta(days=giorni)


def miccia_provvisoria(giocate: Sequence[Dict[str, Any]],
                       istante: Optional[datetime] = None) -> bool:
    """True se almeno una delle giocate mostrate riguarda una partita lontana."""
    return any(e_partita_provvisoria(g, istante) for g in giocate or [])


def suffisso_provvisoria(g: Dict[str, Any], istante: Optional[datetime] = None) -> str:
    """Il marcatore da apporre a una riga lontana, o stringa vuota."""
    return f" — {MARCATORE_QUOTE_PROVVISORIE}" if e_partita_provvisoria(g, istante) else ""


def aggiornamento_quote_parole(
    generato_il: Any,
    istante: Optional[datetime] = None,
) -> str:
    """La freschezza delle quote in parole, ora italiana (punto 8).

    Stesso giorno: "Quote aggiornate oggi alle 16:56". Ieri: "Attenzione:
    quote di ieri, non ancora aggiornate oggi." Prima di ieri: la data e'
    detta per esteso. Un file senza data leggibile non diventa "aggiornato".
    """
    dt = parse_commence_time(generato_il)
    if dt is None:
        return "Data di aggiornamento delle quote non leggibile: le quote potrebbero non essere di oggi."
    gen_roma = _a_roma(dt)
    ora_roma = _a_roma(_adesso(istante))
    giorni = (ora_roma.date() - gen_roma.date()).days
    if giorni <= 0:
        return f"Quote aggiornate oggi alle {gen_roma.hour:02d}:{gen_roma.minute:02d}"
    if giorni == 1:
        return "Attenzione: quote di ieri, non ancora aggiornate oggi."
    return (f"Attenzione: quote di {GIORNI_SETTIMANA_IT[gen_roma.weekday()]} "
            f"{gen_roma.day:02d}/{gen_roma.month:02d}, non aggiornate oggi.")


# ---------------------------------------------------------------------------
# Contenuto dei riquadri in vista (punti 1 e 2)
# ---------------------------------------------------------------------------

def descrivi_leg(g: Dict[str, Any], istante: Optional[datetime] = None) -> str:
    """Una giocata di una proposta in una riga sola, con data e ora italiane.

    "venerdì 16/10, ore 20:45 — Frosinone vs Sassuolo: Vince Frosinone (1)"
    piu' il marcatore delle quote lontane quando serve.
    """
    giocata = str(g.get("giocata") or g.get("esito") or "")
    try:
        parole = giocata_in_parole_con_sigla(giocata, g.get("home") or "?", g.get("away") or "?")
    except Exception:
        parole = giocata
    return (f"{quando_italiano(g.get('commence_time'))} — "
            f"{g.get('partita') or (str(g.get('home','?')) + ' vs ' + str(g.get('away','?')))}: "
            f"{parole}{suffisso_provvisoria(g, istante)}")


def righe_riquadro_raddoppio(
    best_by_k: Dict[int, Optional[Dict[str, Any]]],
    istante: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Le righe della tabella "Per raddoppiare" (punto 1), una per k esistente.

    I numeri sono QUELLI di ``cerca_proposta_multipla``: probabilita', quota
    totale e 100 x p x q si leggono qui senza essere ricalcolati altrove, e
    la riga con la probabilita' piu' alta porta ``migliore=True`` (il segno
    discreto della commessa).
    """
    righe: List[Dict[str, Any]] = []
    for k in (1, 2, 3, 4):
        item = (best_by_k or {}).get(k)
        if not item:
            continue
        righe.append({
            "k": k,
            "n_partite": len(item.get("giocate", [])),
            "partite": [descrivi_leg(g, istante) for g in item.get("giocate", [])],
            "probabilita": float(item["probabilita"]),
            "quota_totale": float(item["quota_totale"]),
            "riesce": riesce_circa(item["probabilita"]),
            "paga": paga_circa(item["quota_totale"]),
            "ritorno_100": ritorno_su_100(item["probabilita"], item["quota_totale"]),
            "provvisoria": any(e_partita_provvisoria(g, istante)
                               for g in item.get("giocate", [])),
            "migliore": False,
        })
    if righe:
        top = max(righe, key=lambda r: r["probabilita"])
        top["migliore"] = True
    return righe


def migliori_giocate_per_partita(
    giocate: Sequence[Dict[str, Any]],
    quota_min: float = 1.20,
) -> List[Dict[str, Any]]:
    """La giocata piu' probabile di OGNI partita, fra quelle con quota >= quota_min.

    Usata dalla lista "Le piu' probabili" (punto 2): una riga per partita al
    massimo, ordinate per probabilita' decrescente (le giocate in ingresso lo
    sono gia', quindi la prima incontrata per partita e' anche la migliore).
    """
    migliore: Dict[str, Dict[str, Any]] = {}
    for g in giocate or []:
        q = g.get("quota_b365_stimata")
        if q is None:
            continue
        try:
            if float(q) < float(quota_min):
                continue
        except (TypeError, ValueError):
            continue
        mid = str(g.get("match_id") or g.get("partita"))
        if mid not in migliore:
            migliore[mid] = g
    return list(migliore.values())


# ---------------------------------------------------------------------------
# «Prova la tua giocata»: confronto con le quote bet365 (punto 3, rifinitura)
# ---------------------------------------------------------------------------

# Tolleranza per dire che bet365 paga "come previsto": +-0,02 sulla quota.
TOLLERANZA_CONFRONTO_QUOTA = 0.02

# Righe di spiegazione fisse del riquadro (testo visibile, parole solo).
ISTRUZIONI_PROVA_LA_TUA_GIOCATA = (
    "Inserisci le quote che vedi su bet365 per sapere quanto paga davvero la tua giocata."
)
LINEA_PARTITE_INDIPENDENTI = "Il calcolo considera le partite indipendenti fra loro."
NOME_LIBRAIO = "bet365"


def e_doppia_chance(giocata: Any) -> bool:
    """True se la giocata e' una doppia chance (1X, X2, 12)."""
    return str(giocata or "").strip() in ("1X", "X2", "12")


def identificativo_giocata(g: Dict[str, Any]) -> str:
    """Chiave stabile di una giocata: «match_id|sigla» (usata dai widget)."""
    giocata = str(g.get("giocata") or g.get("esito") or "").strip()
    return f"{g.get('match_id')}|{giocata}"


def probabilita_giocata(g: Dict[str, Any]) -> float:
    """La probabilita' della giocata come si legge dalla lista (0..1).

    La lista la conserva in ``probabilita``; i vecchi pezzi chiamati ``prob``
    e le proposte (``prob_b365_stimata``) restano leggibili come ripiego, ma
    una giocata senza nessuna delle tre NON diventa uno 0 silenzioso.
    """
    for chiave in ("probabilita", "prob_b365_stimata", "prob"):
        v = g.get(chiave)
        if v is None:
            continue
        try:
            p = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(p) and 0.0 <= p <= 1.0:
            return p
    return 0.0


def quota_stimata_giocata(g: Dict[str, Any]) -> Optional[float]:
    """La quota che l'app si aspetta su bet365 per questa giocata (o None).

    Per 1X2 e' la quota equa (1/p a partire dalle quote della fonte); per le
    doppie chance e' una stima (meno precisa, perche' le doppie sul sito del
    bookmaker dipendono da quanto il banco arrotonda). Restituisce float o
    None quando il valore non e' disponibile.
    """
    q = g.get("quota_b365_stimata")
    try:
        q = float(q)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(q) or q <= 1.0:
        return None
    return q


def hint_quota_stimata(g: Dict[str, Any]) -> str:
    """Suggerimento sotto la casella: «L'app si aspetta circa 2,00».

    Per le doppie chance aggiunge «(stima meno precisa)», perche' il valore
    deriva da quote principali e il bookmaker arrotonda in modo diverso.
    """
    q = quota_stimata_giocata(g)
    if q is None:
        return "L'app non ha una stima per questa giocata."
    base = f"L'app si aspetta circa {quota_italiana(q)}"
    if e_doppia_chance(g.get("giocata") or g.get("esito")):
        return f"{base} (stima meno precisa)"
    return base


def confronto_quota_bet365(
    quota_bet365: Any,
    quota_stimata: Any,
    tolleranza: float = TOLLERANZA_CONFRONTO_QUOTA,
) -> str:
    """Verdetto su una casella: «bet365 paga più / meno / come previsto».

    Due quote entro ``tolleranza`` (0,02) valgono «come previsto». Il nome del
    bookmaker sta nel testo perche' e' il sito che l'utente ha davanti.
    """
    q = float(quota_bet365)
    e = float(quota_stimata)
    if not all(math.isfinite(v) for v in (q, e)):
        return ""
    if q > e + tolleranza:
        return f"{NOME_LIBRAIO} paga più del previsto"
    if q < e - tolleranza:
        return f"{NOME_LIBRAIO} paga meno del previsto"
    return f"{NOME_LIBRAIO} paga come previsto"


def titolo_risultato_giocata(n_compilate: int, n_gambe: int) -> str:
    """Dicitura sopra i numeri, in base a quante caselle sono state riempite:

    * tutte vuote:  «Con le quote previste dall'app»
    * alcune:       «Con N quote di bet365 e M previste dall'app»
    * tutte:        «Con le quote di bet365»
    """
    n_compilate = int(n_compilate)
    n_gambe = int(n_gambe)
    if n_compilate <= 0:
        return "Con le quote previste dall'app"
    if n_compilate >= n_gambe:
        return f"Con le quote di {NOME_LIBRAIO}"
    return f"Con {n_compilate} quote di {NOME_LIBRAIO} e {n_gambe - n_compilate} previste dall'app"


def esito_prova_giocata(
    gambe: Sequence[Dict[str, Any]],
    quote_bet365: Sequence[Optional[float]],
) -> Dict[str, Any]:
    """I numeri del riquadro «Prova la tua giocata» (punto 3, rifinitura).

    ``gambe`` sono le giocate scelte; ``quote_bet365[i]`` e' la quota letta sul
    sito per la gamba i, oppure None se la casella e' rimasta vuota (e allora
    vale la stima dell'app). Probabilita' e quota si combinano per prodotto,
    esattamente come ``cerca_proposta_multipla`` fa con le quote stimate:
    nessun numero cambia, cambia solo da dove arriva la quota di ogni gamba.
    """
    n = len(gambe or [])
    p_tot = 1.0
    q_tot = 1.0
    n_compilate = 0
    q_bloccante = False  # una casella compilata ma inutilizzabile o senza stima
    for i, g in enumerate(gambe or []):
        p_tot *= probabilita_giocata(g)
        if not math.isfinite(p_tot) or p_tot <= 0.0:
            p_tot = 0.0
        inserita = quote_bet365[i] if i < len(quote_bet365 or []) else None
        q_used = quota_stimata_giocata(g)
        if inserita is not None:
            try:
                q_in = float(inserita)
            except (TypeError, ValueError):
                q_in = None
            if q_in is not None and math.isfinite(q_in) and q_in > 1.0:
                q_used = q_in
                n_compilate += 1
        if q_used is None:
            q_bloccante = True
            q_tot = 0.0
            break
        q_tot *= q_used
    ritorno = ritorno_su_100(p_tot, q_tot) if not q_bloccante else 0
    return {
        "n_gambe": n,
        "n_compilate": n_compilate,
        "probabilita": p_tot,
        "quota_totale": q_tot,
        "riesce": riesce_circa(p_tot),
        "paga": paga_circa(q_tot) if not q_bloccante else "n/d",
        "ritorno_100": ritorno,
        "trattenuta_su_100": (max(0, 100 - ritorno) if not q_bloccante else None),
        "titolo": titolo_risultato_giocata(n_compilate, n),
    }


def righe_mercato_nel_periodo(
    righe: Sequence[Dict[str, Any]],
    istante: Optional[datetime] = None,
    periodo: str = PERIODO_GIORNATA,
) -> List[Dict[str, Any]]:
    """Le righe del Top Mix di mercato il cui kickoff cade nel periodo (punto 5a).

    Stessa regola di ``giocate_nel_periodo`` applicata però alle righe del
    selettore di mercato (chiave kickoff diversa: ``kickoff_utc``); con
    ``periodo='tutte'`` tornano tutte le righe non ancora iniziate. Una riga
    senza kickoff leggibile non entra mai: non sappiamo quando si gioca.
    """
    ora = _adesso(istante)
    if ora.tzinfo is None:
        ora = ora.replace(tzinfo=timezone.utc)
    fine = lunedi_gioco(ora) if periodo == PERIODO_GIORNATA else None
    out: List[Dict[str, Any]] = []
    for r in righe or []:
        dt = parse_commence_time(r.get("kickoff_utc") or r.get("utcDate"))
        if dt is None or dt <= ora:
            continue
        if fine is not None and _a_roma(dt) > fine:
            continue
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# Lista completa delle giocate (punto: lista estesa)
# ---------------------------------------------------------------------------

def calcola_lista_giocate(
    payload_quote: Optional[Dict[str, Any]],
    adesso_utc: Optional[datetime] = None,
    params_stima: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Estrae tutte le 6 giocate per ogni partita non iniziata con quote valide.

    Restituisce:
    - 'giocate': lista di dict per ogni giocata candidata, ordinata per prob decrescente
    - 'n_partite_totali': int
    - 'n_partite_ammesse': int
    - 'n_escluse_iniziate': int
    - 'n_escluse_senza_quote': int
    - 'escluse_dettaglio': lista di info sulle partite escluse
    """
    if not payload_quote or not isinstance(payload_quote, dict):
        return {
            "giocate": [],
            "n_partite_totali": 0,
            "n_partite_ammesse": 0,
            "n_escluse_iniziate": 0,
            "n_escluse_senza_quote": 0,
            "escluse_dettaglio": [],
            "stato_quote": "assente" if payload_quote is None else "non_valido",
        }

    now = adesso_utc or mo._adesso_utc()
    params = params_stima or carica_parametri_stima()
    eventi = mo.eventi_quote(payload_quote)
    
    n_iniziate = 0
    n_senza_quote = 0
    escluse_dettaglio = []
    ammesse = []
    
    for ev in eventi:
        home = ev.get("home_team") or "?"
        away = ev.get("away_team") or "?"
        match_str = f"{home} vs {away}"
        lega = ev.get("lega") or "?"
        commence_str = ev.get("commence_time")
        dt_commence = parse_commence_time(commence_str)
        
        # 1. Filtro iniziate
        if dt_commence is not None and dt_commence <= now:
            n_iniziate += 1
            escluse_dettaglio.append({
                "partita": match_str,
                "lega": lega,
                "motivo": "gia_iniziata",
                "commence_time": commence_str
            })
            continue
            
        # 2. Quote di mercato con la STESSA funzione di topmix_mercato_v3
        libri = ev.get("libri") or []
        mkt = mo.probabilita_mercato(libri)
        probs = mkt.get("probs")
        if probs is None or not all(probs.get(e) is not None for e in ("1", "X", "2")):
            n_senza_quote += 1
            escluse_dettaglio.append({
                "partita": match_str,
                "lega": lega,
                "motivo": "quote_non_valide",
                "commence_time": commence_str
            })
            continue
            
        ammesse.append((ev, mkt))

    giocate: List[Dict[str, Any]] = []
    
    for ev, mkt in ammesse:
        home = ev.get("home_team") or "?"
        away = ev.get("away_team") or "?"
        match_str = f"{home} vs {away}"
        match_id = str(ev.get("id") or f"{home}_{away}_{ev.get('commence_time')}")
        lega = ev.get("lega") or "?"
        commence_str = ev.get("commence_time")
        dt_commence = parse_commence_time(commence_str)
        data_str = dt_commence.strftime("%d/%m/%Y %H:%M") if dt_commence else (commence_str or "")
        
        fonte = mkt.get("fonte")
        eta_ore = mo.ore_da(payload_quote.get("generato_il"), adesso=now)
        
        p1 = float(mkt["probs"]["1"])
        px = float(mkt["probs"]["X"])
        p2 = float(mkt["probs"]["2"])
        
        q1_est = stima_quota_b365_1x2(p1, lega, params)
        qx_est = stima_quota_b365_1x2(px, lega, params)
        q2_est = stima_quota_b365_1x2(p2, lega, params)
        
        q1x_est = stima_quota_b365_dc(q1_est, qx_est)
        qx2_est = stima_quota_b365_dc(qx_est, q2_est)
        q12_est = stima_quota_b365_dc(q1_est, q2_est)
        
        specs = [
            ("1", p1, q1_est, False),
            ("X", px, qx_est, False),
            ("2", p2, q2_est, False),
            ("1X", p1 + px, q1x_est, True),
            ("X2", px + p2, qx2_est, True),
            ("12", p1 + p2, q12_est, True),
        ]
        
        for esito, p_val, q_val, is_dc in specs:
            fair = 1.0 / p_val if p_val > 0 else float("inf")
            q_arr = round(q_val, 2) if q_val is not None else None
            is_giocabile = bool(q_arr is not None and q_arr > 1.01)
            nota_stima = "stima non verificata" if is_dc else "fit 2024/25"
            stato_quota = "non giocabile" if not is_giocabile else nota_stima
            giocate.append({
                "match_id": match_id,
                "partita": match_str,
                "home": home,
                "away": away,
                "lega": lega,
                "data": data_str,
                "commence_time": commence_str,
                "giocata": esito,
                "esito": esito,
                "probabilita": p_val,
                "prob_percentuale": round(p_val * 100.0, 2),
                "quota_equa": round(fair, 2),
                "quota_b365_stimata": q_arr,
                "quota_stimata_effettiva": q_arr,
                "is_dc": is_dc,
                "giocabile": is_giocabile,
                "nota_stima": nota_stima,
                "stato_quota": stato_quota,
                "fonte": "Pinnacle" if fonte == mo.FONTE_PINNACLE else f"media {mkt.get('n_libri')} libri",
                "eta_ore": eta_ore,
                "generato_il": payload_quote.get("generato_il"),
            })

    # Ordinamento per probabilità decrescente
    giocate.sort(key=lambda x: x["probabilita"], reverse=True)
    
    return {
        "giocate": giocate,
        "n_partite_totali": len(eventi),
        "n_partite_ammesse": len(ammesse),
        "n_escluse_iniziate": n_iniziate,
        "n_escluse_senza_quote": n_senza_quote,
        "escluse_dettaglio": escluse_dettaglio,
    }


def cerca_proposta_multipla(
    giocate_ordinate: Sequence[Dict[str, Any]],
    fascia_min: float = 2.00,
    fascia_max: float = 3.00,
    top_k: int = 40,
) -> Dict[str, Any]:
    """Ricerca esaustiva delle combinazioni da 1 a 4 giocate con quota stimata in [2, 3].

    Al massimo 1 giocata per partita.
    Candidati: 40 giocate con probabilità più alta + tutte le singole con quota in [2, 3].
    Le giocate non giocabili (quota stimata arrotondata <= 1.01) non entrano fra i candidati.
    Il campo quota_stimata_effettiva si ricava da quota_b365_stimata dentro la funzione
    prima di selezionare i candidati.
    Massimizza il prodotto delle probabilità.
    """
    import itertools

    if not giocate_ordinate:
        return {
            "migliore_assoluta": None,
            "per_k": {1: None, 2: None, 3: None, 4: None},
            "candidati_totali": 0,
            "messaggio": "Nessuna giocata disponibile per la proposta di multipla."
        }

    # Normalizza e filtra giocate giocabili (> 1.01)
    giocate_giocabili = []
    for g in giocate_ordinate:
        g_c = dict(g)
        if g_c.get("quota_stimata_effettiva") is None:
            g_c["quota_stimata_effettiva"] = g_c.get("quota_b365_stimata")
        q_eff = g_c.get("quota_stimata_effettiva")
        # Escludi giocate non giocabili (<= 1.01) o con quota mancante
        if q_eff is not None and round(float(q_eff), 2) > 1.01:
            giocate_giocabili.append(g_c)

    if not giocate_giocabili:
        return {
            "migliore_assoluta": None,
            "per_k": {1: None, 2: None, 3: None, 4: None},
            "candidati_totali": 0,
            "messaggio": "Nessuna giocata giocabile disponibile per la proposta di multipla."
        }

    # Candidati: 40 con prob più alta + singole con quota stimata in [fascia_min, fascia_max]
    top_plays = list(giocate_giocabili[:top_k])
    extra_singles = [
        g for g in giocate_giocabili[top_k:]
        if g.get("quota_stimata_effettiva") is not None
        and fascia_min <= g["quota_stimata_effettiva"] <= fascia_max
    ]
    
    candidati_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for g in top_plays + extra_singles:
        k = (str(g.get("match_id")), str(g.get("giocata")))
        if k not in candidati_map:
            candidati_map[k] = g
            
    candidati = list(candidati_map.values())
    
    # Raggruppa per match_id
    by_match: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for g in candidati:
        by_match[str(g.get("match_id"))].append(g)
        
    matches = list(by_match.values())
    best_by_k: Dict[int, Optional[Dict[str, Any]]] = {1: None, 2: None, 3: None, 4: None}
    
    # 1 giocata (singola)
    for g in candidati:
        q = g.get("quota_stimata_effettiva")
        if q is not None and fascia_min <= q <= fascia_max:
            p = g["probabilita"]
            if best_by_k[1] is None or p > best_by_k[1]["probabilita"]:
                best_by_k[1] = {
                    "k": 1,
                    "probabilita": p,
                    "quota_totale": q,
                    "quota_equa": 1.0 / p if p > 0 else float("inf"),
                    "ev": p * q - 1.0,
                    "giocate": [g]
                }

    # Da 2 a 4 giocate
    tol = 1e-9
    for k in (2, 3, 4):
        if len(matches) < k:
            continue
        for match_comb in itertools.combinations(matches, k):
            for choice in itertools.product(*match_comb):
                q_tot = 1.0
                p_tot = 1.0
                valid = True
                for g in choice:
                    q = g.get("quota_stimata_effettiva")
                    if q is None:
                        valid = False
                        break
                    q_tot *= q
                    p_tot *= g["probabilita"]
                    if q_tot > fascia_max + tol:
                        valid = False
                        break
                if valid and (fascia_min - tol) <= q_tot <= (fascia_max + tol):
                    if best_by_k[k] is None or p_tot > best_by_k[k]["probabilita"]:
                        best_by_k[k] = {
                            "k": k,
                            "probabilita": p_tot,
                            "quota_totale": q_tot,
                            "quota_equa": 1.0 / p_tot if p_tot > 0 else float("inf"),
                            "ev": p_tot * q_tot - 1.0,
                            "giocate": list(choice)
                        }

    valid_combos = [v for v in best_by_k.values() if v is not None]
    best_abs = max(valid_combos, key=lambda x: x["probabilita"]) if valid_combos else None

    # Guardia logica EV su combinazioni calcolate solo con quote stimate
    for item in list(valid_combos):
        has_manual = any(g.get("is_manual") for g in item.get("giocate", []))
        if not has_manual and item.get("ev", 0.0) > 0.0:
            item["stima_incoerente"] = True
            resp = [g for g in item.get("giocate", []) if (g.get("quota_b365_stimata") or 0.0) * g["probabilita"] > 1.0]
            item["giocata_responsabile"] = resp[0] if resp else item.get("giocate", [{}])[0]
    
    messaggio = None
    if best_abs is None:
        messaggio = f"Nessuna combinazione da 1 a 4 giocate rientra nella fascia di quota stimata fra {fascia_min:.2f} e {fascia_max:.2f}."
        
    return {
        "migliore_assoluta": best_abs,
        "per_k": best_by_k,
        "candidati_totali": len(candidati),
        "messaggio": messaggio,
    }


# ---------------------------------------------------------------------------
# Settimana di gioco del registro ombra multipla_proposta_v1 (punto 9)
# ---------------------------------------------------------------------------
# La settimana di gioco va da MARTEDI' 00:00 a LUNEDI' 23:59 (Europe/Rome) e
# sostituisce la settimana ISO come chiave della prima registrazione.
# L'identificativo e' la data del lunedì di chiusura, in forma AAAA-MM-GG:
# il match_id resta ``multipla_<settimana>_k<k>`` (es. ``multipla_2026-10-19_k1``).
#
# Compatibilità: le righe gia' scritte con chiave ISO (es. settimana
# "2026-W42") restano intatte. Il controllo di duplicato confronta la chiave
# NUOVA con quella ESATTA: una riga ISO non coincide mai con una chiave-data
# (formati diversi), quindi non viene ne' riscritta ne' scartata alla lettura —
# continua a essere letta come qualsiasi altra riga ombra.

def settimana_gioco(dt: Optional[datetime]) -> str:
    """Identificativo della settimana di gioco: data del lunedì di chiusura.

    Settimana di gioco = da martedì 00:00 a lunedì 23:59 (Europe/Rome). Il
    martedì PRIMA di mezzanotte appartiene ancora alla settimana chiusa la
    notte prima; dal martedì 00:00 si apre una settimana nuova, il cui lunedì
    di chiusura e' sei giorni dopo.
    """
    ora = _a_roma(dt if dt is not None else mo._adesso_utc())
    giorni_al_lunedi = (7 - ora.weekday()) % 7   # 0 se oggi e' gia' lunedì
    lunedi_chiusura = (ora + timedelta(days=giorni_al_lunedi)).date()
    return lunedi_chiusura.strftime("%Y-%m-%d")


def in_finestra_registrazione_multipla(istante: Optional[datetime] = None) -> bool:
    """True se l'istante e' fra venerdì 00:00 e lunedì 23:59 (Europe/Rome).

    La prima registrazione della proposta avviene solo in questa finestra
    (punto 9): da martedì a giovedì non si scrive nulla, perche' le quote
    lontane dal weekend cambierebbero ancora troppo.
    """
    ora = _a_roma(_adesso(istante))
    return ora.weekday() in (4, 5, 6, 0)   # venerdì, sabato, domenica, lunedì


def _motivo_fuori_finestra(istante: datetime) -> str:
    return (f"Fuori finestra di registrazione ({GIORNI_SETTIMANA_IT[_a_roma(istante).weekday()]}): "
            "le proposte si registrano solo da venerdì 00:00 a lunedì 23:59.")


def build_ombra_multipla_entry(
    proposta: Dict[str, Any],
    istante_utc: Optional[datetime] = None,
    snapshot_sha: Optional[str] = None,
    k: Optional[int] = None,
) -> Dict[str, Any]:
    """Costruisce il record per il registro ombra (famiglia multipla_proposta_v1)."""
    now = istante_utc or mo._adesso_utc()
    iso_now = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    settimana = settimana_gioco(now)
    
    giocate_serializzabili = []
    for g in proposta.get("giocate", []):
        giocate_serializzabili.append({
            "partita": g.get("partita"),
            "lega": g.get("lega"),
            "giocata": g.get("giocata"),
            "probabilita": round(float(g.get("probabilita", 0.0)), 6),
            "quota_stimata": round(float(g.get("quota_stimata_effettiva") or g.get("quota_b365_stimata") or 0.0), 2),
            "sovrascritta": bool(g.get("sovrascritta", False)),
        })
        
    p_tot = float(proposta.get("probabilita", 0.0))
    q_tot = float(proposta.get("quota_totale", 0.0))
    ev = float(proposta.get("ev", p_tot * q_tot - 1.0))
    n_ev = len(giocate_serializzabili)
    k_val = k if k is not None else proposta.get("k", n_ev)
    match_id_str = f"multipla_{settimana}_k{k_val}" if k_val else f"multipla_{settimana}"
    
    entry = {
        "match_id": match_id_str,
        "home": f"Multipla proposta {settimana} (k={k_val})",
        "away": f"{n_ev} eventi",
        "campionato": "Multi-lega",
        "giornata": 0,
        "data": now.strftime("%d/%m/%Y %H:%M"),
        "pronostico_sicuro": f"Multipla {n_ev} eventi @ {q_tot:.2f}",
        "top3": [f"{g['partita']} ({g['giocata']})" for g in giocate_serializzabili[:3]],
        "prob_sicuro": round(p_tot * 100.0, 1),
        "quota": round(q_tot, 2),
        "quota_stimata": round(q_tot, 2),
        "quota_equa": round(1.0 / p_tot, 2) if p_tot > 0 else None,
        "ev": round(ev, 4),
        "mercato_standard": "MULTIPLA_PROPOSTA",
        "origin": pr.ORIGIN_TOP_MIX_OMBRA,
        "selector_version": SELECTOR_VERSION_MULTIPLA_PROPOSTA,
        "model_variant": pr.MODEL_VARIANT_CURRENT,
        "salvato_il": iso_now,
        "snapshot_sha": snapshot_sha or "",
        "ombra": True,
        "ombra_famiglia": FAMIGLIA_OMBRA_MULTIPLA_PROPOSTA,
        "settimana": settimana,
        "k": k_val,
        "giocate": giocate_serializzabili,
        "n_eventi": n_ev,
    }
    return entry


def salva_proposta_multipla_registro_ombra(
    proposta: Dict[str, Any],
    istante_utc: Optional[datetime] = None,
    snapshot_sha: Optional[str] = None,
    k: Optional[int] = None,
) -> Dict[str, Any]:
    """Salva una proposta nel registro ombra come famiglia multipla_proposta_v1.

    Prima registrazione per settimana di gioco (per ciascun k) mai sovrascritta.
    La scrittura avviene SOLO fra venerdì 00:00 e lunedì 23:59 (Europe/Rome),
    sull'istante del calcolo passato dal chiamante: da martedì a giovedì non
    si scrive nulla (punto 9). Nessuna scrittura nel registro di mercato.
    """
    import registry_store as rs
    if not proposta or not proposta.get("giocate"):
        return {"remoto": "nessuna_riga", "motivo": "proposta_vuota"}

    now = _adesso(istante_utc)
    if not in_finestra_registrazione_multipla(now):
        return {"remoto": "fuori_finestra", "motivo": _motivo_fuori_finestra(now)}

    settimana = settimana_gioco(now)
    k_val = k if k is not None else proposta.get("k", len(proposta.get("giocate", [])))
    match_id_target = f"multipla_{settimana}_k{k_val}" if k_val else f"multipla_{settimana}"
    
    try:
        esistenti, fonte = rs.load_ombra_rows(strict=True)
    except Exception as e:
        return {"remoto": "errore", "errore": f"load_ombra_rows: {e}"}
        
    esistenti = esistenti or []
    
    # Verifica se esiste già una riga per questa settimana nella famiglia multipla_proposta_v1 per questo k (o legacy senza k)
    gia_registrata = any(
        e.get("ombra_famiglia") == FAMIGLIA_OMBRA_MULTIPLA_PROPOSTA
        and e.get("settimana") == settimana
        and (e.get("match_id") == match_id_target or (k_val is None and e.get("match_id") == f"multipla_{settimana}"))
        for e in esistenti
    )
    if gia_registrata:
        return {
            "remoto": "gia_registrata_settimana",
            "settimana": settimana,
            "k": k_val,
            "motivo": f"Prima registrazione per la settimana {settimana} (k={k_val}) gia' presente: mai sovrascritta."
        }
        
    entry = build_ombra_multipla_entry(proposta, istante_utc=now, snapshot_sha=snapshot_sha, k=k_val)
    nuove_righe = list(esistenti) + [entry]
    
    try:
        esito = rs.save_ombra_rows(nuove_righe)
        return esito
    except Exception as e:
        return {"remoto": "errore", "errore": f"save_ombra_rows: {e}"}


def salva_tutte_proposte_k_registro_ombra(
    best_by_k: Dict[int, Optional[Dict[str, Any]]],
    istante_utc: Optional[datetime] = None,
    snapshot_sha: Optional[str] = None
) -> Dict[str, Any]:
    """Salva una riga per ciascun k disponibile (1, 2, 3, 4) nel registro ombra.

    Stessa regola di prima registrazione settimanale mai sovrascritta per ogni k,
    e stessa finestra: SOLO fra venerdì 00:00 e lunedì 23:59 (punto 9).
    """
    import registry_store as rs
    now = _adesso(istante_utc)
    if not in_finestra_registrazione_multipla(now):
        return {"remoto": "fuori_finestra", "motivo": _motivo_fuori_finestra(now)}

    settimana = settimana_gioco(now)
    
    try:
        esistenti, fonte = rs.load_ombra_rows(strict=True)
    except Exception as e:
        return {"remoto": "errore", "errore": f"load_ombra_rows: {e}"}
        
    esistenti = esistenti or []
    nuove_righe = list(esistenti)
    salvate_k = []
    gia_presenti_k = []

    for k in (1, 2, 3, 4):
        item = best_by_k.get(k)
        if not item or not item.get("giocate"):
            continue
        match_id_target = f"multipla_{settimana}_k{k}"
        gia_registrata = any(
            e.get("ombra_famiglia") == FAMIGLIA_OMBRA_MULTIPLA_PROPOSTA
            and e.get("settimana") == settimana
            and (e.get("match_id") == match_id_target or e.get("k") == k)
            for e in nuove_righe
        )
        if gia_registrata:
            gia_presenti_k.append(k)
            continue
        entry = build_ombra_multipla_entry(item, istante_utc=now, snapshot_sha=snapshot_sha, k=k)
        nuove_righe.append(entry)
        salvate_k.append(k)

    if not salvate_k:
        return {
            "remoto": "gia_registrata_settimana" if gia_presenti_k else "nessuna_riga",
            "settimana": settimana,
            "gia_presenti_k": gia_presenti_k,
        }

    try:
        esito = rs.save_ombra_rows(nuove_righe)
        esito["salvate_k"] = salvate_k
        esito["gia_presenti_k"] = gia_presenti_k
        return esito
    except Exception as e:
        return {"remoto": "errore", "errore": f"save_ombra_rows: {e}"}
