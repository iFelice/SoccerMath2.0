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
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

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
                "quota_b365_stimata": round(q_val, 2) if q_val is not None else None,
                "is_dc": is_dc,
                "nota_stima": "stima non verificata" if is_dc else "fit 2024/25",
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

    # Candidati: 40 con prob più alta + singole con quota stimata in [2.00, 3.00]
    top_plays = list(giocate_ordinate[:top_k])
    extra_singles = [
        g for g in giocate_ordinate[top_k:]
        if g.get("quota_stimata_effettiva") is not None
        and fascia_min <= g["quota_stimata_effettiva"] <= fascia_max
    ]
    
    candidati_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for g in top_plays + extra_singles:
        # Prepara quota_stimata_effettiva se non presente
        g_copy = dict(g)
        if "quota_stimata_effettiva" not in g_copy:
            g_copy["quota_stimata_effettiva"] = g_copy.get("quota_b365_stimata")
        k = (str(g_copy.get("match_id")), str(g_copy.get("giocata")))
        if k not in candidati_map:
            candidati_map[k] = g_copy
            
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


def settimana_gioco(dt: Optional[datetime]) -> str:
    """Restituisce l'identificativo ISO anno-settimana: es. '2026-W41'."""
    if dt is None:
        dt = mo._adesso_utc()
    iso_year, iso_week, _ = dt.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def build_ombra_multipla_entry(
    proposta: Dict[str, Any],
    istante_utc: Optional[datetime] = None,
    snapshot_sha: Optional[str] = None
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
    
    entry = {
        "match_id": f"multipla_{settimana}",
        "home": f"Multipla proposta {settimana}",
        "away": f"{len(giocate_serializzabili)} eventi",
        "campionato": "Multi-lega",
        "giornata": 0,
        "data": now.strftime("%d/%m/%Y %H:%M"),
        "pronostico_sicuro": f"Multipla {len(giocate_serializzabili)} eventi @ {q_tot:.2f}",
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
        "giocate": giocate_serializzabili,
        "n_eventi": len(giocate_serializzabili),
    }
    return entry


def salva_proposta_multipla_registro_ombra(
    proposta: Dict[str, Any],
    istante_utc: Optional[datetime] = None,
    snapshot_sha: Optional[str] = None
) -> Dict[str, Any]:
    """Salva la proposta migliore nel registro ombra come famiglia multipla_proposta_v1.

    Prima registrazione per settimana di gioco mai sovrascritta.
    Nessuna scrittura nel registro di mercato.
    """
    import registry_store as rs
    if not proposta or not proposta.get("giocate"):
        return {"remoto": "nessuna_riga", "motivo": "proposta_vuota"}
        
    now = istante_utc or mo._adesso_utc()
    settimana = settimana_gioco(now)
    
    try:
        esistenti, fonte = rs.load_ombra_rows(strict=True)
    except Exception as e:
        return {"remoto": "errore", "errore": f"load_ombra_rows: {e}"}
        
    esistenti = esistenti or []
    
    # Verifica se esiste già una riga per questa settimana nella famiglia multipla_proposta_v1
    gia_registrata = any(
        e.get("ombra_famiglia") == FAMIGLIA_OMBRA_MULTIPLA_PROPOSTA and e.get("settimana") == settimana
        for e in esistenti
    )
    if gia_registrata:
        return {
            "remoto": "gia_registrata_settimana",
            "settimana": settimana,
            "motivo": f"Prima registrazione per la settimana {settimana} gia' presente: mai sovrascritta."
        }
        
    entry = build_ombra_multipla_entry(proposta, istante_utc=now, snapshot_sha=snapshot_sha)
    nuove_righe = list(esistenti) + [entry]
    
    try:
        esito = rs.save_ombra_rows(nuove_righe)
        return esito
    except Exception as e:
        return {"remoto": "errore", "errore": f"save_ombra_rows: {e}"}
