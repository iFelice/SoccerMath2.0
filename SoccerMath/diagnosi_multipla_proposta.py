"""Diagnosi (SOLA LETTURA) delle proposte settimanali ``multipla_proposta_v1``.

Perche' esiste. Le proposte di multipla della settimana (famiglia
``multipla_proposta_v1`` nel registro ombra ``sm:registro:ombra``) non vengono
mai valutate: ``app._applica_esiti`` le manda nel ramo senza giornata perche'
``match_id`` e' testuale (``multipla_<settimana>_k<k>``), e in
``_esiti_senza_giornata`` restano in attesa ``⏳`` con
``Grading O/U senza estremi ... campionato='Multi-lega', kickoff=None``.
La scheda Registro mostra quindi: ``Le proposte settimanali registrate: 12,
riuscite 0``.

Garanzie di sola lettura (stesso schema della PR 83):

1. legge il registro ombra (``sm:registro:ombra``) e il Registro vivo
   (``sm:registro``) da Upstash con il **solo comando ``HGETALL``** — nessuna
   scrittura da nessuna parte (niente ``HSET``/``HDEL``/``SET``, nessun file
   scritto, nessuna chiamata che muti stato);
2. calcola l'impronta ``sha256`` del contenuto grezzo di **entrambi** gli hash
   PRIMA dell'analisi e la ricalcola DOPO con un secondo ``HGETALL``: devono
   coincidere byte per byte;
3. non stampa mai chiavi, URL o token (verifica esplicita con sanificazione
   prima di stampare qualsiasi riga reale);
4. risponde nel log del job ai 4 quesiti della verifica:
   - Punto 1: funzione che scrive le righe (file e riga), campi salvati e una
     riga reale completa letta con ``HGETALL`` (piu' l'elenco integrale delle
     righe ``multipla_proposta_v1`` sanificate);
   - Punto 2: se ogni riga contiene l'elenco delle sue partite con
     ``match_id``, ``campionato``, ``kickoff`` ed ``esito giocato``;
   - Punto 3: per ciascuna delle righe ``multipla_proposta_v1``, se le singole
     partite si possono abbinare a righe gia' graduate del registro ombra o
     del Registro vivo — sia col criterio stretto ``(stessa partita, stessa
     giocata)`` sia per ``stessa partita`` con ``risultato_reale`` gia'
     graduato — e quante proposte sono gia' tutte concluse;
   - Punto 4: quante chiamate a football-data servirebbero per valutare quelle
     non abbinabili.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import market_odds as mo  # noqa: E402
import registry_store as rs  # noqa: E402
from config import LEAGUE_CODE_MAP, LEAGUES_CONFIG  # noqa: E402
from lista_giocate import (  # noqa: E402
    FAMIGLIA_OMBRA_MULTIPLA_PROPOSTA,
    SELECTOR_VERSION_MULTIPLA_PROPOSTA,
    parse_commence_time,
)
from prediction_registry import (  # noqa: E402
    DATA_FIELD,
    ESITO_PERSO,
    ESITO_VINTO,
    KICKOFF_UTC_FIELD,
    OMBRA_FAMIGLIA_FIELD,
    esito_mercato,
    model_variant_read,
    origin_of,
    parse_datetime,
    parse_kickoff,
    selector_version_of,
)
from team_names import resolve_team_name  # noqa: E402

UTC = timezone.utc
INIZIO_STAGIONE_CORRENTE = datetime(2026, 8, 1, tzinfo=UTC)

# Parole/pattern che non devono mai finire nel log se mai comparissero in una
# chiave o in un valore stringa. ``snapshot_sha`` e' l'impronta sha256 dei CSV
# del database (db_snapshot.snapshot_fingerprint), NON un segreto.
_CHIAVI_SENSIBILI = (
    "token",
    "secret",
    "api_key",
    "apikey",
    "password",
    "authorization",
    "bearer",
    "upstash_redis",
)
_VALORI_SENSIBILI_RE = re.compile(
    r"(upstash\.io|bearer\s+\S+|https?://[^\s\"']*token[^\s\"']*)",
    re.IGNORECASE,
)

# Campi scritti da ``lista_giocate.build_ombra_multipla_entry`` (righe 985-1011).
CAMPI_CODICE_BUILD_ENTRY: Tuple[str, ...] = (
    "match_id",
    "home",
    "away",
    "campionato",
    "giornata",
    "data",
    "pronostico_sicuro",
    "top3",
    "prob_sicuro",
    "quota",
    "quota_stimata",
    "quota_equa",
    "ev",
    "mercato_standard",
    "origin",
    "selector_version",
    "model_variant",
    "salvato_il",
    "snapshot_sha",
    "ombra",
    "ombra_famiglia",
    "settimana",
    "k",
    "giocate",
    "n_eventi",
)

# Campi scritti per ciascuna gamba in ``build_ombra_multipla_entry`` (righe 966-976).
CAMPI_CODICE_GAMBA: Tuple[str, ...] = (
    "partita",
    "lega",
    "giocata",
    "probabilita",
    "quota_stimata",
    "sovrascritta",
)


def impronta_hash(campi: Dict[str, Any]) -> str:
    """sha256 del contenuto GREZZO dell'hash (campo -> valore, ordinato)."""
    h = hashlib.sha256()
    for campo in sorted(campi):
        valore = campi[campo]
        testo = valore if isinstance(valore, str) else json.dumps(
            valore, ensure_ascii=False, sort_keys=True, default=str
        )
        h.update(campo.encode("utf-8"))
        h.update(b"\n")
        h.update(testo.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def leggi_hash_grezzo(chiave: str) -> Dict[str, Any]:
    """SOLO ``HGETALL``: l'unico comando Upstash di tutta la diagnosi."""
    risultato = rs.upstash_raw(["HGETALL", chiave]).get("result")
    return rs.hash_da_risposta(risultato, dove=f"HGETALL {chiave}")


def righe_da_hash_grezzo(
    valori: Dict[str, Any],
) -> Tuple[List[Tuple[str, Dict[str, Any]]], List[Dict[str, Any]]]:
    """Decodifica il grezzo di ``HGETALL`` con la stessa regola di ``rs.upstash_rows``.

    Ritorna ``(coppie_campo_riga, righe_ordinate)`` senza eseguire altre letture.
    """
    per_chiave: Dict[str, Tuple[str, str, Dict[str, Any]]] = {}
    for campo, valore in valori.items():
        riga = rs._row_from_value(valore)
        if riga is None:
            continue
        chiave = rs.field_of(riga)
        testo = json.dumps(riga, ensure_ascii=False, sort_keys=True, default=str)
        precedente = per_chiave.get(chiave)
        if precedente is not None:
            if precedente[1] != testo:
                raise rs.RegistryStoreError(
                    f"Due campi con stessa chiave logica ma contenuto diverso: "
                    f"`{precedente[0]}` vs `{campo}` (chiave `{chiave}`)"
                )
            if campo == chiave and precedente[0] != chiave:
                per_chiave[chiave] = (campo, testo, riga)
            continue
        per_chiave[chiave] = (campo, testo, riga)
    ordinate = sorted(per_chiave.values(), key=lambda voce: rs.field_of(voce[2]))
    return [(v[0], v[2]) for v in ordinate], [v[2] for v in ordinate]


def sanifica_oggetto(obj: Any, *, segreti_noti: Sequence[str] = ()) -> Tuple[Any, int]:
    """Rimuove qualunque chiave/token qualora fosse presente in un oggetto."""
    segreti_puliti = [s for s in segreti_noti if s and len(s) >= 6]
    oscurati = 0

    def _pulito(chiave: Optional[str], val: Any) -> Any:
        nonlocal oscurati
        if chiave is not None:
            k_low = chiave.lower()
            if any(tok in k_low for tok in _CHIAVI_SENSIBILI):
                oscurati += 1
                return "<OSCURATO>"
        if isinstance(val, dict):
            return {str(k): _pulito(str(k), v) for k, v in val.items()}
        if isinstance(val, list):
            return [_pulito(None, el) for el in val]
        if isinstance(val, str):
            if _VALORI_SENSIBILI_RE.search(val) or any(s in val for s in segreti_puliti):
                oscurati += 1
                return "<OSCURATO>"
        return val

    return _pulito(None, obj), oscurati


def kickoff_riga(riga: Dict[str, Any]) -> Optional[datetime]:
    """Istante della partita: ``kickoff_utc`` (autorevole) o ``data`` italiana."""
    ko = parse_kickoff(riga.get(KICKOFF_UTC_FIELD))
    if ko is not None:
        return ko
    return parse_datetime(riga.get(DATA_FIELD))


def coppia_canonica(home: Any, away: Any) -> Optional[Tuple[str, str]]:
    """Copia esatta di ``app._coppia_canonica``."""
    h = resolve_team_name(home)
    a = resolve_team_name(away)
    if not (h.mapped and a.mapped):
        return None
    return (h.canonical, a.canonical)


def estrai_squadre_partita(partita: Any) -> Tuple[str, str]:
    """Separa ``'Casa vs Trasferta'`` (formato di ``calcola_lista_giocate``)."""
    testo = str(partita or "").strip()
    if " vs " in testo:
        h, a = testo.split(" vs ", 1)
        return h.strip(), a.strip()
    if " - " in testo:
        h, a = testo.split(" - ", 1)
        return h.strip(), a.strip()
    return testo, ""


def parse_risultato_reale(valore: Any) -> Optional[Tuple[int, int]]:
    """Estrae ``(gh, ga)`` da ``'2-1'``; ``None`` se assente o non valido."""
    if not isinstance(valore, str):
        return None
    m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", valore)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def finestra_proposta(riga: Dict[str, Any]) -> Dict[str, Any]:
    """Ricava ``(dal, al, salvato_dt)`` dai soli campi salvati sulla proposta.

    * ``settimana == 'AAAA-MM-GG'`` (lunedì di chiusura Europe/Rome): le partite
      ammesse da ``giocate_nel_periodo(..., 'giornata')`` hanno kickoff fra
      ``salvato_il`` e lunedì 23:59 Europe/Rome -> ``[salvato_il_date, lunedi + 1g]``.
    * ``settimana == 'AAAA-Www'`` (formato ISO iniziale del 10-11/10/2026, prima
      di ``giocate_nel_periodo``): copre dalla data di salvataggio fino a
      ``max(domenica_ISO + 1g, salvato_date + 10g)``.
    """
    salvato_dt = parse_kickoff(riga.get("salvato_il")) or parse_datetime(riga.get(DATA_FIELD))
    settimana = str(riga.get("settimana") or "").strip()
    dal_d: Optional[date] = salvato_dt.date() if salvato_dt else None
    al_d: Optional[date] = None

    m_data = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", settimana)
    m_iso = re.match(r"^(\d{4})-W(\d{2})$", settimana)
    if m_data:
        lunedi = date(int(m_data.group(1)), int(m_data.group(2)), int(m_data.group(3)))
        martedi_apertura = lunedi - timedelta(days=6)
        if dal_d is None or dal_d > lunedi:
            dal_d = martedi_apertura
        al_d = lunedi + timedelta(days=1)
    elif m_iso:
        anno_iso, week_iso = int(m_iso.group(1)), int(m_iso.group(2))
        lun_iso = date.fromisocalendar(anno_iso, week_iso, 1)
        dom_iso = date.fromisocalendar(anno_iso, week_iso, 7)
        if dal_d is None:
            dal_d = lun_iso
        # Nella sosta nazionali W41 (10-11/10) live_odds conteneva il turno del
        # weekend successivo (16-19/10): +10g copre l'intero turno in 1 GET.
        al_d = max(dom_iso + timedelta(days=1), dal_d + timedelta(days=10))
    elif dal_d is not None:
        al_d = dal_d + timedelta(days=7)

    return {
        "salvato_dt": salvato_dt,
        "settimana": settimana,
        "dal": dal_d.strftime("%Y-%m-%d") if dal_d else None,
        "al": al_d.strftime("%Y-%m-%d") if al_d else None,
    }


def carica_indice_csv_live() -> Dict[Tuple[str, Tuple[str, str]], List[Dict[str, Any]]]:
    """Indice sola lettura ``(comp, coppia_canonica) -> partite finite`` dai ``*_Live.csv``."""
    indice: Dict[Tuple[str, Tuple[str, str]], List[Dict[str, Any]]] = {}
    for nome_lega, info in LEAGUES_CONFIG.items():
        comp = info["code"]
        percorso = info["live_csv"]
        if not os.path.exists(percorso):
            continue
        with open(percorso, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                coppia = coppia_canonica(row.get("HomeTeam"), row.get("AwayTeam"))
                fthg, ftag = (row.get("FTHG") or "").strip(), (row.get("FTAG") or "").strip()
                if coppia is None or not (fthg.isdigit() and ftag.isdigit()):
                    continue
                data_raw = (row.get("Date") or "").strip()
                data_iso = data_raw
                for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
                    try:
                        data_iso = datetime.strptime(data_raw, fmt).strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        continue
                indice.setdefault((comp, coppia), []).append({
                    "lega": nome_lega,
                    "comp": comp,
                    "date": data_iso,
                    "gh": int(fthg),
                    "ga": int(ftag),
                    "risultato": f"{int(fthg)}-{int(ftag)}",
                    "matchday": (row.get("Matchday") or "").strip(),
                })
    return indice


def carica_indice_quote_live() -> Dict[Tuple[str, Tuple[str, str]], List[Dict[str, Any]]]:
    """Indice sola lettura ``(comp, coppia_canonica) -> eventi`` da ``live_odds.json``."""
    indice: Dict[Tuple[str, Tuple[str, str]], List[Dict[str, Any]]] = {}
    payload = mo.carica_quote_live()
    if not payload:
        return indice
    for ev in mo.eventi_quote(payload):
        comp = LEAGUE_CODE_MAP.get(ev.get("lega"))
        coppia = coppia_canonica(ev.get("home_team"), ev.get("away_team"))
        if not comp or coppia is None:
            continue
        indice.setdefault((comp, coppia), []).append({
            "odds_id": ev.get("id"),
            "lega": ev.get("lega"),
            "commence_time": ev.get("commence_time"),
            "kickoff_dt": parse_commence_time(ev.get("commence_time")),
        })
    return indice


def _e_multipla_proposta(riga: Dict[str, Any]) -> bool:
    return (
        riga.get(OMBRA_FAMIGLIA_FIELD) == FAMIGLIA_OMBRA_MULTIPLA_PROPOSTA
        or riga.get("selector_version") == SELECTOR_VERSION_MULTIPLA_PROPOSTA
    )


def _descrivi_riga_abbinata(r: Dict[str, Any], sorgente: str) -> Dict[str, Any]:
    ko = kickoff_riga(r)
    return {
        "sorgente": sorgente,
        "match_id": r.get("match_id"),
        "fd_match_id": r.get("fd_match_id"),
        "giornata": r.get("giornata"),
        "origin": origin_of(r),
        "selector_version": selector_version_of(r),
        "ombra_famiglia": r.get(OMBRA_FAMIGLIA_FIELD),
        "model_variant": model_variant_read(r),
        "mercato_standard": str(r.get("mercato_standard") or "").strip().upper(),
        "kickoff": ko.isoformat() if ko else r.get(DATA_FIELD),
        "giorno": ko.strftime("%Y-%m-%d") if ko else None,
        "risultato_reale": r.get("risultato_reale"),
        "esito": r.get("esito"),
    }


def analizza_proposte(
    proposte_con_campo: Sequence[Tuple[str, Dict[str, Any]]],
    righe_ombra: Sequence[Dict[str, Any]],
    righe_vivo: Sequence[Dict[str, Any]],
    indice_csv: Optional[Dict[Tuple[str, Tuple[str, str]], List[Dict[str, Any]]]] = None,
    indice_odds: Optional[Dict[Tuple[str, Tuple[str, str]], List[Dict[str, Any]]]] = None,
    *,
    adesso: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Analisi completa (pura, sola lettura) delle righe ``multipla_proposta_v1``."""
    adesso = adesso or datetime.now(UTC)
    indice_csv = indice_csv if indice_csv is not None else {}
    indice_odds = indice_odds if indice_odds is not None else {}

    # Indicizza righe di ombra (escluse le multipla_proposta_v1) e vivo nella
    # stagione corrente 2026/2027 per (comp, coppia_canonica).
    idx_ombra: Dict[Tuple[str, Tuple[str, str]], List[Dict[str, Any]]] = {}
    for r in righe_ombra:
        if _e_multipla_proposta(r):
            continue
        comp = LEAGUE_CODE_MAP.get(r.get("campionato"))
        coppia = coppia_canonica(r.get("home"), r.get("away"))
        ko = kickoff_riga(r)
        if not comp or coppia is None:
            continue
        if ko is not None and ko < INIZIO_STAGIONE_CORRENTE:
            continue
        idx_ombra.setdefault((comp, coppia), []).append(r)

    idx_vivo: Dict[Tuple[str, Tuple[str, str]], List[Dict[str, Any]]] = {}
    for r in righe_vivo:
        if _e_multipla_proposta(r):
            continue
        comp = LEAGUE_CODE_MAP.get(r.get("campionato"))
        coppia = coppia_canonica(r.get("home"), r.get("away"))
        ko = kickoff_riga(r)
        if not comp or coppia is None:
            continue
        if ko is not None and ko < INIZIO_STAGIONE_CORRENTE:
            continue
        idx_vivo.setdefault((comp, coppia), []).append(r)

    # Ordina le proposte per salvato_il, settimana, k, match_id.
    proposte_ordinate = sorted(
        proposte_con_campo,
        key=lambda cr: (
            str(cr[1].get("salvato_il") or ""),
            str(cr[1].get("settimana") or ""),
            int(cr[1].get("k") or 0) if str(cr[1].get("k") or "").isdigit() else 0,
            str(cr[1].get("match_id") or ""),
        ),
    )

    # Verifica Punto 2 su tutte le righe e gambe.
    chiavi_righe_unione: Set[str] = set()
    chiavi_righe_intersezione: Optional[Set[str]] = None
    chiavi_gambe_unione: Set[str] = set()
    tot_gambe = 0
    gambe_con_partita = 0
    gambe_coppia_risolta = 0
    gambe_con_match_id = 0
    gambe_con_lega = 0
    gambe_lega_mappata = 0
    gambe_con_campionato = 0
    gambe_con_kickoff = 0
    gambe_con_giocata = 0
    gambe_giocata_valida = 0
    codici_giocata_trovati: Set[str] = set()

    dettaglio_proposte: List[Dict[str, Any]] = []

    for idx_p, (campo_hash, prop) in enumerate(proposte_ordinate, start=1):
        ks_r = set(prop.keys())
        chiavi_righe_unione |= ks_r
        chiavi_righe_intersezione = ks_r if chiavi_righe_intersezione is None else (chiavi_righe_intersezione & ks_r)

        fin = finestra_proposta(prop)
        salvato_dt: Optional[datetime] = fin["salvato_dt"]
        gambe_raw = prop.get("giocate") if isinstance(prop.get("giocate"), list) else []

        gambe_analizzate: List[Dict[str, Any]] = []
        for idx_g, g in enumerate(gambe_raw, start=1):
            if not isinstance(g, dict):
                continue
            tot_gambe += 1
            chiavi_gambe_unione |= set(g.keys())

            partita_str = g.get("partita")
            if partita_str:
                gambe_con_partita += 1
            home_raw, away_raw = estrai_squadre_partita(partita_str)
            coppia = coppia_canonica(home_raw, away_raw)
            if coppia is not None:
                gambe_coppia_risolta += 1

            if any(g.get(k) not in (None, "") for k in ("match_id", "id", "fd_match_id")):
                gambe_con_match_id += 1
            lega_str = g.get("lega")
            if lega_str not in (None, ""):
                gambe_con_lega += 1
            comp = LEAGUE_CODE_MAP.get(lega_str)
            if comp:
                gambe_lega_mappata += 1
            if g.get("campionato") not in (None, ""):
                gambe_con_campionato += 1
            if any(g.get(k) not in (None, "") for k in ("kickoff", "kickoff_utc", "commence_time", "utcDate", "data")):
                gambe_con_kickoff += 1

            giocata = str(g.get("giocata") or "").strip().upper()
            if giocata:
                gambe_con_giocata += 1
                codici_giocata_trovati.add(giocata)
                if esito_mercato(giocata, 1, 0) is not None:
                    gambe_giocata_valida += 1

            # Filtra righe candidate in ombra e vivo coerenti con salvato_dt.
            cand_ombra_all = idx_ombra.get((comp or "", coppia or ("", "")), []) if (comp and coppia) else []
            cand_vivo_all = idx_vivo.get((comp or "", coppia or ("", "")), []) if (comp and coppia) else []

            def _coerente(r: Dict[str, Any]) -> bool:
                ko = kickoff_riga(r)
                if ko is None or salvato_dt is None:
                    return True
                return ko >= (salvato_dt - timedelta(hours=24))

            cand_ombra = [r for r in cand_ombra_all if _coerente(r)]
            cand_vivo = [r for r in cand_vivo_all if _coerente(r)]

            grad_ombra = [r for r in cand_ombra if r.get("esito") in (ESITO_VINTO, ESITO_PERSO)]
            grad_vivo = [r for r in cand_vivo if r.get("esito") in (ESITO_VINTO, ESITO_PERSO)]
            attesa_ombra = [r for r in cand_ombra if r.get("esito") in (None, "⏳")]
            attesa_vivo = [r for r in cand_vivo if r.get("esito") in (None, "⏳")]

            # 3A) Criterio stretto: (stessa partita, stessa giocata) gia' graduata.
            sg_ombra = [
                r for r in grad_ombra
                if str(r.get("mercato_standard") or "").strip().upper() == giocata
            ]
            sg_vivo = [
                r for r in grad_vivo
                if str(r.get("mercato_standard") or "").strip().upper() == giocata
            ]
            sg_unione = sg_ombra + sg_vivo
            esiti_sg = sorted({str(r.get("esito")) for r in sg_unione})
            esito_stessa_giocata = esiti_sg[0] if len(esiti_sg) == 1 else None

            # 3B) Criterio per partita: stessa partita gia' graduata (con risultato_reale).
            sp_ombra = [r for r in grad_ombra if parse_risultato_reale(r.get("risultato_reale")) is not None]
            sp_vivo = [r for r in grad_vivo if parse_risultato_reale(r.get("risultato_reale")) is not None]
            sp_unione = sp_ombra + sp_vivo
            ris_set = sorted({str(r.get("risultato_reale")).strip() for r in sp_unione})
            esito_da_partita: Optional[str] = None
            risultato_partita: Optional[str] = None
            if len(ris_set) == 1:
                risultato_partita = ris_set[0]
                gh_ga = parse_risultato_reale(risultato_partita)
                if gh_ga is not None:
                    esito_da_partita = esito_mercato(giocata, gh_ga[0], gh_ga[1])

            # Riscontro CSV live (partite finite stagione 2026/27) e live_odds.json (partite future).
            csv_all = indice_csv.get((comp or "", coppia or ("", "")), []) if (comp and coppia) else []
            soglia_csv = (
                (salvato_dt - timedelta(days=2)).strftime("%Y-%m-%d")
                if salvato_dt is not None
                else "2026-08-01"
            )
            csv_matches = [c for c in csv_all if c["date"] >= soglia_csv]
            odds_matches = indice_odds.get((comp or "", coppia or ("", "")), []) if (comp and coppia) else []
            scartate_pre_salvataggio = (len(cand_ombra_all) - len(cand_ombra)) + (
                len(cand_vivo_all) - len(cand_vivo)
            )

            # Kickoff noto (da righe ombra/vivo o da live_odds).
            kickoff_noti: List[datetime] = []
            for r in cand_ombra + cand_vivo:
                ko = kickoff_riga(r)
                if ko is not None:
                    kickoff_noti.append(ko)
            for ev in odds_matches:
                if ev.get("kickoff_dt") is not None:
                    kickoff_noti.append(ev["kickoff_dt"])
            kickoff_noto = min(kickoff_noti) if kickoff_noti else None

            # Stato conclusione reale della partita oggi.
            conclusa_oggi = bool(sp_unione or sg_unione or csv_matches)
            esito_reale_gamba: Optional[str] = esito_stessa_giocata or esito_da_partita
            risultato_reale_gamba: Optional[str] = risultato_partita
            if esito_reale_gamba is None and csv_matches:
                risultato_reale_gamba = csv_matches[-1]["risultato"]
                esito_reale_gamba = esito_mercato(giocata, csv_matches[-1]["gh"], csv_matches[-1]["ga"])

            if conclusa_oggi:
                stato_partita = "CONCLUSA"
            elif kickoff_noto is not None and kickoff_noto > adesso:
                stato_partita = "FUTURA"
            elif kickoff_noto is not None:
                stato_partita = "INIZIATA_O_SCADUTA_NON_GRADUATA"
            else:
                stato_partita = "SCONOSCIUTA"

            giorno_effettivo = (
                kickoff_noto.strftime("%Y-%m-%d")
                if kickoff_noto is not None
                else (csv_matches[-1]["date"] if csv_matches else None)
            )
            in_finestra_settimana: Optional[bool] = None
            if giorno_effettivo and fin["dal"] and fin["al"]:
                in_finestra_settimana = bool(fin["dal"] <= giorno_effettivo <= fin["al"])

            mercati_grad_ombra = sorted({str(r.get("mercato_standard") or "") for r in grad_ombra})
            mercati_grad_vivo = sorted({str(r.get("mercato_standard") or "") for r in grad_vivo})

            gambe_analizzate.append({
                "idx_gamba": idx_g,
                "partita": partita_str,
                "home_raw": home_raw,
                "away_raw": away_raw,
                "coppia_canonica": coppia,
                "lega": lega_str,
                "comp": comp,
                "giocata": giocata,
                "probabilita": g.get("probabilita"),
                "quota_stimata": g.get("quota_stimata"),
                "abbinata_stessa_giocata_ombra": bool(sg_ombra),
                "abbinata_stessa_giocata_vivo": bool(sg_vivo),
                "abbinata_stessa_giocata": bool(sg_unione),
                "esito_stessa_giocata": esito_stessa_giocata,
                "righe_stessa_giocata": [_descrivi_riga_abbinata(r, "ombra") for r in sg_ombra]
                + [_descrivi_riga_abbinata(r, "vivo") for r in sg_vivo],
                "abbinata_stessa_partita_ombra": bool(sp_ombra),
                "abbinata_stessa_partita_vivo": bool(sp_vivo),
                "abbinata_stessa_partita": bool(sp_unione),
                "risultato_da_registri": risultato_partita,
                "risultati_distinti_registri": ris_set,
                "esito_da_stessa_partita": esito_da_partita,
                "mercati_graduati_ombra": mercati_grad_ombra,
                "mercati_graduati_vivo": mercati_grad_vivo,
                "righe_attesa_ombra": len(attesa_ombra),
                "righe_attesa_vivo": len(attesa_vivo),
                "esempio_attesa": (
                    _descrivi_riga_abbinata(attesa_ombra[0], "ombra")
                    if attesa_ombra
                    else (_descrivi_riga_abbinata(attesa_vivo[0], "vivo") if attesa_vivo else None)
                ),
                "csv_live": csv_matches[-1] if csv_matches else None,
                "scartate_pre_salvataggio": scartate_pre_salvataggio,
                "kickoff_noto": kickoff_noto.isoformat() if kickoff_noto else None,
                "giorno_noto": giorno_effettivo,
                "in_finestra_settimana": in_finestra_settimana,
                "conclusa_oggi": conclusa_oggi,
                "stato_partita": stato_partita,
                "risultato_reale_gamba": risultato_reale_gamba,
                "esito_reale_gamba": esito_reale_gamba,
            })

        n_g = len(gambe_analizzate)
        tutte_sg = n_g > 0 and all(x["abbinata_stessa_giocata"] for x in gambe_analizzate)
        tutte_sp = n_g > 0 and all(x["abbinata_stessa_partita"] for x in gambe_analizzate)
        tutte_concluse = n_g > 0 and all(x["conclusa_oggi"] for x in gambe_analizzate)

        def _esito_multipla(chiave_esito: str, pronte: bool) -> str:
            if not pronte:
                # Nota: se almeno una gamba gia' graduata e' ❌, la multipla e'
                # matematicamente gia' persa anche se un'altra gamba manca; ma
                # teniamo distinto 'tutte concluse' da 'parziale'.
                return "⏳"
            esiti = [x[chiave_esito] for x in gambe_analizzate]
            if any(e is None for e in esiti):
                return "⏳"
            return ESITO_VINTO if all(e == ESITO_VINTO for e in esiti) else ESITO_PERSO

        gia_persa_parziale_sg = any(x["esito_stessa_giocata"] == ESITO_PERSO for x in gambe_analizzate)
        gia_persa_parziale_sp = any(x["esito_da_stessa_partita"] == ESITO_PERSO for x in gambe_analizzate)

        dettaglio_proposte.append({
            "idx": idx_p,
            "campo_hash": campo_hash,
            "match_id": prop.get("match_id"),
            "settimana": prop.get("settimana"),
            "k": prop.get("k"),
            "n_eventi": prop.get("n_eventi"),
            "salvato_il": prop.get("salvato_il"),
            "data": prop.get(DATA_FIELD),
            "quota": prop.get("quota"),
            "prob_sicuro": prop.get("prob_sicuro"),
            "esito_attuale": prop.get("esito"),
            "finestra": fin,
            "gambe": gambe_analizzate,
            "n_gambe": n_g,
            "n_abbinate_stessa_giocata_ombra": sum(1 for x in gambe_analizzate if x["abbinata_stessa_giocata_ombra"]),
            "n_abbinate_stessa_giocata_vivo": sum(1 for x in gambe_analizzate if x["abbinata_stessa_giocata_vivo"]),
            "n_abbinate_stessa_giocata": sum(1 for x in gambe_analizzate if x["abbinata_stessa_giocata"]),
            "tutte_abbinate_stessa_giocata": tutte_sg,
            "esito_multipla_stessa_giocata": _esito_multipla("esito_stessa_giocata", tutte_sg),
            "gia_persa_parziale_stessa_giocata": gia_persa_parziale_sg,
            "n_abbinate_stessa_partita_ombra": sum(1 for x in gambe_analizzate if x["abbinata_stessa_partita_ombra"]),
            "n_abbinate_stessa_partita_vivo": sum(1 for x in gambe_analizzate if x["abbinata_stessa_partita_vivo"]),
            "n_abbinate_stessa_partita": sum(1 for x in gambe_analizzate if x["abbinata_stessa_partita"]),
            "tutte_abbinate_stessa_partita": tutte_sp,
            "esito_multipla_stessa_partita": _esito_multipla("esito_da_stessa_partita", tutte_sp),
            "gia_persa_parziale_stessa_partita": gia_persa_parziale_sp,
            "n_concluse_oggi": sum(1 for x in gambe_analizzate if x["conclusa_oggi"]),
            "tutte_concluse_oggi": tutte_concluse,
            "esito_multipla_reale_oggi": _esito_multipla("esito_reale_gamba", tutte_concluse),
            "riga_originale": prop,
        })

    # Calcolo chiamate football-data per valutare le gambe NON abbinabili (Punto 4).
    def _conta_chiamate_non_abbinabili(chiave_abbinata: str, *, solo_concluse: bool) -> Dict[str, Any]:
        gambe_mancanti: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        partite_distinte: Set[Tuple[str, Tuple[str, str], str]] = set()
        per_comp_settimana: Dict[Tuple[str, str], Tuple[str, str]] = {}
        per_comp_range: Dict[str, Tuple[str, str]] = {}
        per_comp_giorno_noto: Set[Tuple[str, str]] = set()
        senza_giorno_noto = 0

        for dp in dettaglio_proposte:
            fin = dp["finestra"]
            sett = str(fin["settimana"] or "")
            dal = str(fin["dal"] or "")
            al = str(fin["al"] or "")
            for g in dp["gambe"]:
                if g[chiave_abbinata]:
                    continue
                if solo_concluse and not g["conclusa_oggi"]:
                    continue
                gambe_mancanti.append((dp, g))
                comp = g["comp"] or "?"
                coppia = g["coppia_canonica"] or (g["home_raw"], g["away_raw"])
                partite_distinte.add((comp, coppia, sett))
                if g["comp"] and dal and al:
                    k_cs = (g["comp"], sett)
                    if k_cs not in per_comp_settimana:
                        per_comp_settimana[k_cs] = (dal, al)
                    else:
                        d0, a0 = per_comp_settimana[k_cs]
                        per_comp_settimana[k_cs] = (min(d0, dal), max(a0, al))
                    if g["comp"] not in per_comp_range:
                        per_comp_range[g["comp"]] = (dal, al)
                    else:
                        d0, a0 = per_comp_range[g["comp"]]
                        per_comp_range[g["comp"]] = (min(d0, dal), max(a0, al))
                if g["comp"] and g["giorno_noto"]:
                    per_comp_giorno_noto.add((g["comp"], g["giorno_noto"]))
                else:
                    senza_giorno_noto += 1

        return {
            "n_gambe_non_abbinabili": len(gambe_mancanti),
            "n_partite_distinte": len(partite_distinte),
            "chiamate_per_comp_settimana": len(per_comp_settimana),
            "gruppi_comp_settimana": [
                f"{comp}/{sett} ({dal}..{al})"
                for (comp, sett), (dal, al) in sorted(per_comp_settimana.items())
            ],
            "chiamate_per_comp_unione": len(per_comp_range),
            "gruppi_comp_unione": [
                f"{comp} ({dal}..{al})"
                for comp, (dal, al) in sorted(per_comp_range.items())
            ],
            "chiamate_per_comp_giorno_noto": len(per_comp_giorno_noto),
            "gruppi_comp_giorno_noto": [
                f"{comp}/{gg}" for comp, gg in sorted(per_comp_giorno_noto)
            ],
            "gambe_senza_giorno_noto": senza_giorno_noto,
        }

    chiamate_p4 = {
        "non_abbinabili_stessa_giocata_solo_concluse": _conta_chiamate_non_abbinabili(
            "abbinata_stessa_giocata", solo_concluse=True
        ),
        "non_abbinabili_stessa_giocata_tutte": _conta_chiamate_non_abbinabili(
            "abbinata_stessa_giocata", solo_concluse=False
        ),
        "non_abbinabili_stessa_partita_solo_concluse": _conta_chiamate_non_abbinabili(
            "abbinata_stessa_partita", solo_concluse=True
        ),
        "non_abbinabili_stessa_partita_tutte": _conta_chiamate_non_abbinabili(
            "abbinata_stessa_partita", solo_concluse=False
        ),
    }

    return {
        "n_proposte": len(dettaglio_proposte),
        "chiavi_righe_unione": sorted(chiavi_righe_unione),
        "chiavi_righe_intersezione": sorted(chiavi_righe_intersezione or set()),
        "punto2": {
            "tot_gambe": tot_gambe,
            "chiavi_gambe_unione": sorted(chiavi_gambe_unione),
            "gambe_con_partita": gambe_con_partita,
            "gambe_coppia_risolta": gambe_coppia_risolta,
            "gambe_con_match_id": gambe_con_match_id,
            "gambe_con_lega": gambe_con_lega,
            "gambe_lega_mappata": gambe_lega_mappata,
            "gambe_con_campionato": gambe_con_campionato,
            "gambe_con_kickoff": gambe_con_kickoff,
            "gambe_con_giocata": gambe_con_giocata,
            "gambe_giocata_valida": gambe_giocata_valida,
            "codici_giocata": sorted(codici_giocata_trovati),
        },
        "proposte": dettaglio_proposte,
        "punto4": chiamate_p4,
    }


def main() -> int:
    adesso = datetime.now(UTC)
    segreti_env = [
        os.getenv("UPSTASH_REDIS_REST_URL", ""),
        os.getenv("UPSTASH_REDIS_REST_TOKEN", ""),
        os.getenv("FOOTBALL_DATA_API_KEY", ""),
        os.getenv("ODDS_API_KEY", ""),
        os.getenv("JSONBIN_API_KEY", ""),
    ]
    print(
        f"DIAGNOSI-MULTIPLA| inizio {adesso.isoformat()} | sola lettura: unico comando "
        f"Upstash HGETALL, nessuna scrittura, nessuna attesa"
    )

    chiave_ombra = rs.shadow_hash_key()
    chiave_vivo = rs.hash_key()

    # 1) Lettura HGETALL PRIMA + impronte sha256 PRIMA (ombra e vivo).
    grezzo_ombra_prima = leggi_hash_grezzo(chiave_ombra)
    impronta_ombra_prima = impronta_hash(grezzo_ombra_prima)
    coppie_ombra, righe_ombra = righe_da_hash_grezzo(grezzo_ombra_prima)

    grezzo_vivo_prima = leggi_hash_grezzo(chiave_vivo)
    impronta_vivo_prima = impronta_hash(grezzo_vivo_prima)
    _coppie_vivo, righe_vivo = righe_da_hash_grezzo(grezzo_vivo_prima)

    print(
        f"REGISTRO-OMBRA| chiave {chiave_ombra} | campi grezzi {len(grezzo_ombra_prima)} | "
        f"righe logiche {len(righe_ombra)}"
    )
    print(f"IMPRONTA-OMBRA-PRIMA| sha256 {impronta_ombra_prima}")
    print(
        f"REGISTRO-VIVO| chiave {chiave_vivo} | campi grezzi {len(grezzo_vivo_prima)} | "
        f"righe logiche {len(righe_vivo)}"
    )
    print(f"IMPRONTA-VIVO-PRIMA| sha256 {impronta_vivo_prima}")

    # Composizione per famiglia nell'ombra e filtro multipla_proposta_v1.
    per_famiglia: Dict[str, int] = {}
    for r in righe_ombra:
        fam = str(r.get(OMBRA_FAMIGLIA_FIELD) or r.get("selector_version") or "sconosciuta")
        per_famiglia[fam] = per_famiglia.get(fam, 0) + 1
    proposte_con_campo = [(c, r) for c, r in coppie_ombra if _e_multipla_proposta(r)]
    n_riuscite_ui = sum(1 for _, r in proposte_con_campo if r.get("esito") == ESITO_VINTO)
    n_perse_ui = sum(1 for _, r in proposte_con_campo if r.get("esito") == ESITO_PERSO)
    n_attesa_ui = sum(1 for _, r in proposte_con_campo if r.get("esito") in (None, "⏳"))
    print(
        f"FAMIGLIE-OMBRA| {json.dumps(per_famiglia, ensure_ascii=False, sort_keys=True)} | "
        f"multipla_proposta_v1 trovate: {len(proposte_con_campo)} "
        f"(riuscite={n_riuscite_ui}, perse={n_perse_ui}, in_attesa={n_attesa_ui})"
    )

    indice_csv = carica_indice_csv_live()
    indice_odds = carica_indice_quote_live()
    analisi = analizza_proposte(
        proposte_con_campo,
        righe_ombra,
        righe_vivo,
        indice_csv,
        indice_odds,
        adesso=adesso,
    )

    # ------------------------------------------------------------------
    # PUNTO 1: funzione che scrive, campi salvati e riga reale completa
    # ------------------------------------------------------------------
    print("=" * 88)
    print(
        "PUNTO-1-CODICE| costruttore: SoccerMath/lista_giocate.py:956-1012 "
        "build_ombra_multipla_entry (entry dict alle righe 985-1011, giocate_serializzabili "
        "alle righe 966-976) | scrittura attiva in produzione: "
        "SoccerMath/lista_giocate.py:1072-1131 salva_tutte_proposte_k_registro_ombra "
        "(build_ombra_multipla_entry a riga 1113, rs.save_ombra_rows a riga 1125), "
        "chiamata da SoccerMath/app.py:5347-5349 dentro registra_giocate_della_giornata "
        "(definita a riga 5154) | funzione singola gemella: "
        "SoccerMath/lista_giocate.py:1015-1069 salva_proposta_multipla_registro_ombra "
        "(rs.save_ombra_rows a riga 1066)"
    )
    print(
        "PUNTO-1-MOTIVO-GRADING| in SoccerMath/app.py:1044 (_applica_esiti) la guardia "
        "`p.get('giornata') is not None and _match_id_numerico(p.get('match_id'))` vale False "
        "perche' match_id='multipla_<settimana>_k<k>' non e' numerico -> la riga finisce in "
        "_esiti_senza_giornata (SoccerMath/app.py:949-975), dove LEAGUE_CODE_MAP.get('Multi-lega')=None, "
        "kickoff_utc=None (_giorno_kickoff_riga=None) e _coppia_canonica(home, away)=None -> "
        "warning riga 971 'Grading O/U senza estremi ... resta ⏳'"
    )
    extra_reali = sorted(set(analisi["chiavi_righe_unione"]) - set(CAMPI_CODICE_BUILD_ENTRY))
    mancanti_in_qualcuna = sorted(set(CAMPI_CODICE_BUILD_ENTRY) - set(analisi["chiavi_righe_intersezione"]))
    print(
        f"PUNTO-1-CAMPI| campi di build_ombra_multipla_entry ({len(CAMPI_CODICE_BUILD_ENTRY)}): "
        f"{list(CAMPI_CODICE_BUILD_ENTRY)} | unione chiavi nelle {analisi['n_proposte']} righe reali "
        f"({len(analisi['chiavi_righe_unione'])}): {analisi['chiavi_righe_unione']} | "
        f"intersezione ({len(analisi['chiavi_righe_intersezione'])}): {analisi['chiavi_righe_intersezione']} | "
        f"campi extra aggiunti dopo la creazione (es. dal grading): {extra_reali} | "
        f"campi di build_ombra_multipla_entry assenti in almeno una riga reale: {mancanti_in_qualcuna}"
    )

    if analisi["proposte"]:
        prima = analisi["proposte"][0]
        riga_san, n_osc = sanifica_oggetto(prima["riga_originale"], segreti_noti=segreti_env)
        print(
            f"PUNTO-1-RIGA-REALE-COMPLETA| campo_hash={prima['campo_hash']} | "
            f"campi_oscurati={n_osc} | json={json.dumps(riga_san, ensure_ascii=False, sort_keys=True)}"
        )
        print("PUNTO-1-RIGA-REALE-INDENTATA-INIZIO")
        print(json.dumps(riga_san, ensure_ascii=False, indent=2, sort_keys=True))
        print("PUNTO-1-RIGA-REALE-INDENTATA-FINE")

        # Stampa tutte le righe multipla_proposta_v1 complete sanificate (1 riga ciascuna).
        for dp in analisi["proposte"]:
            r_san, n_o = sanifica_oggetto(dp["riga_originale"], segreti_noti=segreti_env)
            print(
                f"RIGA-OMBRA-COMPLETA| idx={dp['idx']}/{analisi['n_proposte']} | "
                f"campo_hash={dp['campo_hash']} | oscurati={n_o} | "
                f"json={json.dumps(r_san, ensure_ascii=False, sort_keys=True)}"
            )

    # ------------------------------------------------------------------
    # PUNTO 2: contenuto di giocate su ogni riga
    # ------------------------------------------------------------------
    print("=" * 88)
    p2 = analisi["punto2"]
    n_con_lista = sum(
        1 for dp in analisi["proposte"]
        if isinstance(dp["riga_originale"].get("giocate"), list)
        and len(dp["riga_originale"]["giocate"]) == dp["riga_originale"].get("n_eventi")
    )
    print(
        f"PUNTO-2-RIEPILOGO| righe con lista `giocate` di lunghezza == `n_eventi`: "
        f"{n_con_lista}/{analisi['n_proposte']} | gambe totali: {p2['tot_gambe']} | "
        f"chiavi presenti in ogni elemento di `giocate` (SoccerMath/lista_giocate.py:966-976): "
        f"{p2['chiavi_gambe_unione']} (codice: {list(CAMPI_CODICE_GAMBA)})"
    )
    print(
        f"PUNTO-2-CAMPI-GAMBA| "
        f"elenco_partite (`partita` 'Casa vs Trasferta'): SI ({p2['gambe_con_partita']}/{p2['tot_gambe']}, "
        f"coppia canonica risolta {p2['gambe_coppia_risolta']}/{p2['tot_gambe']}) | "
        f"match_id della singola partita: NO ({p2['gambe_con_match_id']}/{p2['tot_gambe']} — "
        f"presente in calcola_lista_giocate riga 744 come id The Odds API ma NON copiato da "
        f"build_ombra_multipla_entry righe 966-976) | "
        f"campionato: SI sotto la chiave `lega` ({p2['gambe_con_lega']}/{p2['tot_gambe']}, "
        f"mappate in LEAGUE_CODE_MAP {p2['gambe_lega_mappata']}/{p2['tot_gambe']}; "
        f"chiave `campionato` {p2['gambe_con_campionato']}/{p2['tot_gambe']}) | "
        f"kickoff: NO ({p2['gambe_con_kickoff']}/{p2['tot_gambe']} — `commence_time` e `data` "
        f"presenti in calcola_lista_giocate righe 749-750 ma NON copiati da "
        f"build_ombra_multipla_entry righe 966-976; sulla riga padre `kickoff_utc` assente) | "
        f"esito_giocato: SI sotto la chiave `giocata` ({p2['gambe_con_giocata']}/{p2['tot_gambe']}, "
        f"codici={p2['codici_giocata']}, validi per esito_mercato {p2['gambe_giocata_valida']}/{p2['tot_gambe']})"
    )

    # ------------------------------------------------------------------
    # PUNTO 3: abbinamento per ciascuna delle 12 righe e quante concluse
    # ------------------------------------------------------------------
    print("=" * 88)
    for dp in analisi["proposte"]:
        print(
            f"PROPOSTA| idx={dp['idx']}/{analisi['n_proposte']} | match_id={dp['match_id']} | "
            f"settimana={dp['settimana']} | k={dp['k']} | n_eventi={dp['n_gambe']} | "
            f"salvato_il={dp['salvato_il']} | finestra={dp['finestra']['dal']}..{dp['finestra']['al']} | "
            f"quota={dp['quota']} | prob={dp['prob_sicuro']}% | esito_attuale={dp['esito_attuale']!r} | "
            f"stessa_partita+stessa_giocata: {dp['n_abbinate_stessa_giocata']}/{dp['n_gambe']} "
            f"(ombra {dp['n_abbinate_stessa_giocata_ombra']}, vivo {dp['n_abbinate_stessa_giocata_vivo']}) "
            f"tutta={dp['tutte_abbinate_stessa_giocata']} esito={dp['esito_multipla_stessa_giocata']} | "
            f"stessa_partita(risultato_reale): {dp['n_abbinate_stessa_partita']}/{dp['n_gambe']} "
            f"(ombra {dp['n_abbinate_stessa_partita_ombra']}, vivo {dp['n_abbinate_stessa_partita_vivo']}) "
            f"tutta={dp['tutte_abbinate_stessa_partita']} esito={dp['esito_multipla_stessa_partita']} | "
            f"concluse_oggi: {dp['n_concluse_oggi']}/{dp['n_gambe']} "
            f"tutta_conclusa={dp['tutte_concluse_oggi']} esito_reale={dp['esito_multipla_reale_oggi']}"
        )
        for g in dp["gambe"]:
            fonti_sg = [
                f"{r['sorgente']}:{r['selector_version']}({r['mercato_standard']}->{r['esito']},ris={r['risultato_reale']},id={r['match_id']},ko={r['kickoff']})"
                for r in g["righe_stessa_giocata"]
            ]
            att_info = ""
            if g["esempio_attesa"]:
                ea = g["esempio_attesa"]
                att_info = (
                    f" | in_attesa(ombra={g['righe_attesa_ombra']},vivo={g['righe_attesa_vivo']},"
                    f"id={ea['match_id']},g={ea['giornata']},ko={ea['kickoff']})"
                )
            csv_info = ""
            if g["csv_live"]:
                c = g["csv_live"]
                csv_info = f" | csv_live={c['date']} {c['risultato']} (md={c['matchday']})"
            print(
                f"  GAMBA| prop={dp['idx']}#{g['idx_gamba']} | {g['partita']} "
                f"(canon={g['coppia_canonica']}) | lega={g['lega']} ({g['comp']}) | "
                f"giocata={g['giocata']} (q={g['quota_stimata']}, p={g['probabilita']}) | "
                f"stato={g['stato_partita']} (ko_noto={g['kickoff_noto']}, "
                f"in_finestra_settimana={g['in_finestra_settimana']}) | "
                f"stessa_giocata={'SI' if g['abbinata_stessa_giocata'] else 'NO'} "
                f"(ombra={'SI' if g['abbinata_stessa_giocata_ombra'] else 'NO'}, "
                f"vivo={'SI' if g['abbinata_stessa_giocata_vivo'] else 'NO'}, "
                f"esito={g['esito_stessa_giocata']}, fonti={fonti_sg}) | "
                f"stessa_partita_graduata={'SI' if g['abbinata_stessa_partita'] else 'NO'} "
                f"(ombra={'SI' if g['abbinata_stessa_partita_ombra'] else 'NO'}, "
                f"vivo={'SI' if g['abbinata_stessa_partita_vivo'] else 'NO'}, "
                f"ris={g['risultato_da_registri']}, esito_calcolato={g['esito_da_stessa_partita']}, "
                f"mercati_ombra={g['mercati_graduati_ombra']}, mercati_vivo={g['mercati_graduati_vivo']})"
                f"{att_info}{csv_info}"
            )

    proposte_list = analisi["proposte"]
    n_tot = len(proposte_list)
    n_tutte_concluse = sum(1 for x in proposte_list if x["tutte_concluse_oggi"])
    n_concluse_vinte = sum(
        1 for x in proposte_list if x["tutte_concluse_oggi"] and x["esito_multipla_reale_oggi"] == ESITO_VINTO
    )
    n_concluse_perse = sum(
        1 for x in proposte_list if x["tutte_concluse_oggi"] and x["esito_multipla_reale_oggi"] == ESITO_PERSO
    )
    n_tutte_sg = sum(1 for x in proposte_list if x["tutte_abbinate_stessa_giocata"])
    n_sg_vinte = sum(
        1 for x in proposte_list if x["tutte_abbinate_stessa_giocata"] and x["esito_multipla_stessa_giocata"] == ESITO_VINTO
    )
    n_sg_perse = sum(
        1 for x in proposte_list if x["tutte_abbinate_stessa_giocata"] and x["esito_multipla_stessa_giocata"] == ESITO_PERSO
    )
    n_tutte_sp = sum(1 for x in proposte_list if x["tutte_abbinate_stessa_partita"])
    n_sp_vinte = sum(
        1 for x in proposte_list if x["tutte_abbinate_stessa_partita"] and x["esito_multipla_stessa_partita"] == ESITO_VINTO
    )
    n_sp_perse = sum(
        1 for x in proposte_list if x["tutte_abbinate_stessa_partita"] and x["esito_multipla_stessa_partita"] == ESITO_PERSO
    )
    tot_g_sg = sum(x["n_abbinate_stessa_giocata"] for x in proposte_list)
    tot_g_sp = sum(x["n_abbinate_stessa_partita"] for x in proposte_list)
    tot_g_conc = sum(x["n_concluse_oggi"] for x in proposte_list)
    print(
        f"PUNTO-3-RIEPILOGO| proposte totali={n_tot} (gambe totali={p2['tot_gambe']}) | "
        f"proposte GIA' TUTTE CONCLUSE oggi={n_tutte_concluse}/{n_tot} "
        f"(riuscite ✅={n_concluse_vinte}, perse ❌={n_concluse_perse}, "
        f"non ancora tutte concluse={n_tot - n_tutte_concluse}; gambe concluse={tot_g_conc}/{p2['tot_gambe']}) | "
        f"abbinamento stretto (stessa partita, stessa giocata): proposte interamente abbinabili={n_tutte_sg}/{n_tot} "
        f"(✅={n_sg_vinte}, ❌={n_sg_perse}; gambe abbinate={tot_g_sg}/{p2['tot_gambe']}) | "
        f"abbinamento stessa partita gia' graduata (risultato_reale + esito_mercato): "
        f"proposte interamente abbinabili={n_tutte_sp}/{n_tot} "
        f"(✅={n_sp_vinte}, ❌={n_sp_perse}; gambe abbinate={tot_g_sp}/{p2['tot_gambe']})"
    )

    # ------------------------------------------------------------------
    # PUNTO 4: quante chiamate a football-data servirebbero
    # ------------------------------------------------------------------
    print("=" * 88)
    for etichetta, d4 in analisi["punto4"].items():
        print(
            f"PUNTO-4| caso={etichetta} | "
            f"gambe_non_abbinabili={d4['n_gambe_non_abbinabili']} | "
            f"partite_distinte={d4['n_partite_distinte']} | "
            f"GET per (comp, settimana) [solo campi multipla_proposta_v1]={d4['chiamate_per_comp_settimana']} "
            f"gruppi={d4['gruppi_comp_settimana']} | "
            f"GET per comp su range unione={d4['chiamate_per_comp_unione']} "
            f"gruppi={d4['gruppi_comp_unione']} | "
            f"GET per (comp, giorno_noto)={d4['chiamate_per_comp_giorno_noto']} "
            f"gruppi={d4['gruppi_comp_giorno_noto']} "
            f"(gambe senza giorno noto={d4['gambe_senza_giorno_noto']})"
        )

    # ------------------------------------------------------------------
    # Impronte DOPO: devono coincidere byte per byte con PRIMA
    # ------------------------------------------------------------------
    print("=" * 88)
    grezzo_ombra_dopo = leggi_hash_grezzo(chiave_ombra)
    impronta_ombra_dopo = impronta_hash(grezzo_ombra_dopo)
    grezzo_vivo_dopo = leggi_hash_grezzo(chiave_vivo)
    impronta_vivo_dopo = impronta_hash(grezzo_vivo_dopo)

    ombra_identica = (
        impronta_ombra_dopo == impronta_ombra_prima
        and len(grezzo_ombra_dopo) == len(grezzo_ombra_prima)
    )
    vivo_identica = (
        impronta_vivo_dopo == impronta_vivo_prima
        and len(grezzo_vivo_dopo) == len(grezzo_vivo_prima)
    )
    print(f"IMPRONTA-OMBRA-DOPO| sha256 {impronta_ombra_dopo}")
    print(f"IMPRONTA-VIVO-DOPO| sha256 {impronta_vivo_dopo}")
    print(
        f"VERIFICA| impronta ombra prima == dopo: {'SI' if ombra_identica else 'NO'} | "
        f"impronta vivo prima == dopo: {'SI' if vivo_identica else 'NO'} | "
        f"chiamate football-data effettuate: 0 | scritture effettuate: 0 (solo HGETALL)"
    )
    if not (ombra_identica and vivo_identica):
        print(
            "::error title=diagnosi-multipla::impronta del Registro cambiata durante la lettura"
        )
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
