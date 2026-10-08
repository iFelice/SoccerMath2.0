"""Regola di RIENTRO dei Totali nel Top Mix visibile, letta dal registro OMBRA (sola lettura).

Decisione presa PRIMA di avere i dati (fissata a priori, non negoziabile a posteriori):

* i Totali restano FUORI dal Top Mix visibile. GG/NG restano fuori in modo DEFINITIVO
  (il modello non batte il base rate, ``totals_market_ceiling.md`` §11a): per loro il
  registro ombra continua a registrare, ma nessuna regola di rientro li riguarda;
* solo Over/Under 2.5 puo' rientrare, e solo se il campione ombra e' sufficiente e
  fuori campione (stagione 2026/27 in poi), con DUE criteri che devono valere insieme:

  (a) calibrazione: ``hit rate - confidenza media dichiarata >= -2 pp`` con IC 95%
      che include zero o sta sopra zero (cioe' il limite superiore dell'IC >= 0);
  (b) valore: ``hit rate - base rate O/U >= +5 pp`` con IC 95% che esclude zero
      (il limite inferiore dell'IC > 0).

Il base rate O/U 2.5 e' la frequenza storica di Over (o di Under) nelle stagioni
2022/23-2025/26 della stessa lega, dai CSV del repo; la stagione in corso (``*_Live``)
non entra mai nel riferimento.

Lo script legge il registro ombra (hash ``REGISTRY_SHADOW_HASH_KEY``, sola lettura) o un
export JSON (``--file``), calcola N, (a) e (b) con bootstrap a blocchi (blocco = lega,
giornata, stagione: le scelte della stessa giornata non sono indipendenti), e scrive un
referto JSON e Markdown. Non scrive nel registro, non tocca il Top Mix.

Uso:
    python audit/topmix_ombra_rientro.py                       # live (Upstash), se configurato
    python audit/topmix_ombra_rientro.py --file export.json    # export locale
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SOCCERMATH = ROOT / "SoccerMath"
if str(SOCCERMATH) not in sys.path:
    sys.path.insert(0, str(SOCCERMATH))

# ----------------------------------------------------------------- COSTANTI (a priori)
RIENTRO_MERCATI_OU = ("OVER_2.5", "UNDER_2.5")   # solo O/U 2.5; GG/NG fuori in modo definitivo
RIENTRO_GG_NG = "fuori_definitivamente"          # registrati in ombra, mai rientrano
RIENTRO_STAGIONE_MIN_ANNO = 2026                 # fuori campione: stagione 2026/2027 in poi
RIENTRO_N_MIN = 300                              # scelte O/U ombra ammesse e giudicate, minimo
RIENTRO_MARGINE_CALIBRAZIONE = -0.02             # (a) hit - confidenza media >= -2 pp (IC: include 0 o sopra)
RIENTRO_MARGINE_BASE_RATE = 0.05                 # (b) hit - base rate >= +5 pp (IC 95% esclude 0)
RIENTRO_LIVELLO_IC = 0.95
RIENTRO_REPLICHE_BOOTSTRAP = 2000
RIENTRO_SEME = 20261008
RIENTRO_STAGIONI_BASE_RATE = (2022, 2023, 2024, 2025)  # file *_YYYY.csv = stagione YYYY/YYYY+1
RIENTRO_ORIGINE = "top_mix_ombra"
RIENTRO_SELETTORE = "topmix_ombra_totali_v1"

REFERTO_JSON = ROOT / "audit" / "results" / "topmix_ombra_rientro.json"
REFERTO_MD = ROOT / "audit" / "results" / "topmix_ombra_rientro.md"
DB_DIR = SOCCERMATH / "database"

_ESITI_GIUDICATI = ("\u2705", "\u274c")


# ----------------------------------------------------------------- base rate
def _anno_stagione(stagione: Any) -> Optional[int]:
    """'2026/2027' -> 2026. Ritorna None se non interpretabile."""
    m = re.match(r"^\s*(\d{4})\s*/\s*(\d{4})\s*$", str(stagione or ""))
    return int(m.group(1)) if m else None


def base_rate_over25(db_dir: Path = DB_DIR, stagioni: Tuple[int, ...] = RIENTRO_STAGIONI_BASE_RATE
                     ) -> Dict[str, Dict[str, Any]]:
    """Frequenza storica di Over 2.5 per lega, dalle stagioni di riferimento (sola lettura).

    Usa SOLO i file ``<prefisso>_<anno>.csv`` con anno in ``stagioni``: il ``*_Live`` (stagione
    in corso) e il file base non entrano mai. Ritorna ``{lega: {"n", "over", "rate"}}``.
    """
    from config import LEAGUES_CONFIG  # noqa: WPS433 (import locale: config legge i secret)
    risultato: Dict[str, Dict[str, Any]] = {}
    for lega, info in LEAGUES_CONFIG.items():
        prefisso = info.get("db_prefix") or info.get("short_name") or lega
        n = over = 0
        for anno in stagioni:
            percorso = Path(db_dir) / f"{prefisso}_{anno}.csv"
            if not percorso.exists():
                continue
            with open(percorso, encoding="latin-1", newline="") as f:
                for riga in csv.DictReader(f):
                    try:
                        gol = int(riga["FTHG"]) + int(riga["FTAG"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    n += 1
                    over += 1 if gol > 2 else 0
        if n:
            risultato[lega] = {"n": n, "over": over, "rate": over / n}
    return risultato


# ----------------------------------------------------------------- lettura del campione
def carica_registro_ombra(sorgente: str, file: Optional[str]) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """Righe del registro ombra. Ritorna ``(righe | None, descrizione_sorgente)``.

    ``None`` = sorgente non raggiungibile (si riporta NON VERIFICABILE, non si conta zero).
    """
    if file:
        with open(file, encoding="utf-8") as f:
            dati = json.load(f)
        if isinstance(dati, dict) and isinstance(dati.get("data"), list):
            dati = dati["data"]
        if not isinstance(dati, list):
            raise ValueError(f"{file}: attesa una lista di righe")
        return dati, f"file {Path(file).name} ({len(dati)} righe)"
    try:
        from registry_store import load_ombra_rows, shadow_hash_key
        righe, _fonte = load_ombra_rows(strict=True)
        return righe, f"upstash hash {shadow_hash_key()} ({len(righe)} righe)"
    except Exception as e:  # noqa: BLE001 - qui l'errore e' il dato: va riportato, non nascosto
        return None, f"upstash non raggiungibile: {type(e).__name__}: {e}"[:400]


def scelte_ou_ammesse(righe: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Filtra il campione: righe ombra O/U ammesse, fuori campione. Conta anche cio' che esclude."""
    conteggi = {"righe_totali": len(righe), "non_ombra": 0, "non_ou": 0, "non_ammesse": 0,
                "dentro_campione_precedente": 0, "senza_stagione": 0}
    campione: List[Dict[str, Any]] = []
    for r in righe:
        if not isinstance(r, dict):
            conteggi["non_ombra"] += 1
            continue
        if r.get("ombra") is not True or r.get("origin") != RIENTRO_ORIGINE:
            conteggi["non_ombra"] += 1
            continue
        if r.get("mercato_standard") not in RIENTRO_MERCATI_OU:
            conteggi["non_ou"] += 1
            continue
        if r.get("ombra_ammessa") is not True:
            conteggi["non_ammesse"] += 1
            continue
        anno = _anno_stagione(r.get("stagione"))
        if anno is None:
            conteggi["senza_stagione"] += 1
            continue
        if anno < RIENTRO_STAGIONE_MIN_ANNO:
            conteggi["dentro_campione_precedente"] += 1
            continue
        campione.append(r)
    return {"righe": campione, "conteggi": conteggi}


# ----------------------------------------------------------------- statistiche
def _media(valori: List[float]) -> Optional[float]:
    return sum(valori) / len(valori) if valori else None


def _stime(giudicate: List[Dict[str, Any]], base: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """(a) hit - confidenza media e (b) hit - base rate, sulle righe giudicate con base disponibile."""
    if not giudicate:
        return None
    y = [1.0 if r["esito"] == "\u2705" else 0.0 for r in giudicate]
    conf = [float(r["ombra_confidence"]) for r in giudicate]
    rif = []
    for r in giudicate:
        b = base.get(r["campionato"])
        if b is None:
            rif.append(None)
            continue
        p_over = b["rate"]
        rif.append(p_over if r["mercato_standard"] == "OVER_2.5" else 1.0 - p_over)
    return {
        "hit": _media(y),
        "confidenza_media": _media(conf),
        "a": _media(y) - _media(conf),
        "b_valori": [yi - ri for yi, ri in zip(y, rif) if ri is not None],
    }


def _ic(valori: List[float], livello: float) -> Tuple[Optional[float], Optional[float]]:
    """Intervallo percentile (es. 2,5% - 97,5%)."""
    if not valori:
        return None, None
    v = sorted(valori)
    coda = (1.0 - livello) / 2.0
    lo = v[max(0, min(len(v) - 1, math.floor(coda * (len(v) - 1))))]
    hi = v[max(0, min(len(v) - 1, math.ceil((1.0 - coda) * (len(v) - 1))))]
    return lo, hi


def bootstrap(giudicate: List[Dict[str, Any]], base: Dict[str, Dict[str, Any]],
              repliche: int = RIENTRO_REPLICHE_BOOTSTRAP, seme: int = RIENTRO_SEME) -> Dict[str, Any]:
    """Bootstrap a blocchi (lega, giornata, stagione). Deterministico (seme fisso)."""
    blocchi: Dict[Tuple[Any, Any, Any], List[Dict[str, Any]]] = {}
    for r in giudicate:
        chiave = (r.get("campionato"), r.get("giornata"), r.get("stagione"))
        blocchi.setdefault(chiave, []).append(r)
    liste = list(blocchi.values())
    rng = random.Random(seme)
    a_rep: List[float] = []
    b_rep: List[float] = []
    for _ in range(repliche if len(liste) > 1 else 0):
        scelti = [liste[rng.randrange(len(liste))] for _ in liste]
        campione = [r for blocco in scelti for r in blocco]
        s = _stime(campione, base)
        if s is None or not s["b_valori"]:
            continue
        a_rep.append(s["a"])
        b_rep.append(_media(s["b_valori"]))
    alfa = RIENTRO_LIVELLO_IC
    return {"blocchi": len(liste), "repliche_valide": len(a_rep),
            "a_ic": _ic(a_rep, alfa), "b_ic": _ic(b_rep, alfa)}


def valuta(righe_campione: List[Dict[str, Any]], base: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    giudicate = [r for r in righe_campione if r.get("esito") in _ESITI_GIUDICATI]
    in_attesa = len(righe_campione) - len(giudicate)
    n = len(giudicate)
    out: Dict[str, Any] = {
        "ammesse_fuori_campione": len(righe_campione), "giudicate_N": n, "in_attesa": in_attesa,
        "N_minimo": RIENTRO_N_MIN, "N_sufficiente": n >= RIENTRO_N_MIN,
    }
    if n == 0:
        out.update({"esito_criteri": "N insufficiente: nessuna scelta giudicata"})
        return out
    s = _stime(giudicate, base)
    b_ok = [r for r in giudicate if r["campionato"] in base]
    out.update({
        "over_scelte": sum(1 for r in giudicate if r["mercato_standard"] == "OVER_2.5"),
        "under_scelte": sum(1 for r in giudicate if r["mercato_standard"] == "UNDER_2.5"),
        "senza_base_rate": n - len(b_ok),
        "hit_rate": s["hit"], "confidenza_media": s["confidenza_media"],
        "a_stima": s["a"], "b_stima": _media(s["b_valori"]) if s["b_valori"] else None,
    })
    bs = bootstrap(giudicate, base)
    out.update({"bootstrap": bs})
    a_lo, a_hi = bs["a_ic"]
    b_lo, b_hi = bs["b_ic"]
    a_ok = (out["a_stima"] is not None and out["a_stima"] >= RIENTRO_MARGINE_CALIBRAZIONE
            and a_hi is not None and a_hi >= 0.0)
    b_ok_crit = (out["b_stima"] is not None and out["b_stima"] >= RIENTRO_MARGINE_BASE_RATE
                 and b_lo is not None and b_lo > 0.0)
    out.update({"criterio_a_ok": a_ok, "criterio_b_ok": b_ok_crit})
    return out


def decisione(valutazione: Dict[str, Any]) -> str:
    """Esito in una riga. Il rientro richiede N sufficiente E (a) E (b)."""
    if not valutazione.get("N_sufficiente"):
        return (f"NON RIENTRA: N insufficiente ({valutazione.get('giudicate_N', 0)} su "
                f"{RIENTRO_N_MIN} scelte O/U ombra ammesse giudicate, stagione "
                f"{RIENTRO_STAGIONE_MIN_ANNO}/{RIENTRO_STAGIONE_MIN_ANNO + 1}+)")
    if valutazione.get("criterio_a_ok") and valutazione.get("criterio_b_ok"):
        return "RIENTRO AMMESSO (solo O/U 2.5; GG/NG restano fuori)"
    falliti = [n for n, k in (("a", "criterio_a_ok"), ("b", "criterio_b_ok")) if not valutazione.get(k)]
    return f"NON RIENTRA: criteri non soddisfatti ({', '.join(falliti)})"


# ----------------------------------------------------------------- referto
def _pct(x: Optional[float]) -> str:
    return "n/d" if x is None else f"{x * 100:+.2f} pp"


def _ic_pct(ic: Tuple[Optional[float], Optional[float]]) -> str:
    lo, hi = ic
    return "n/d" if lo is None else f"[{lo * 100:+.2f}; {hi * 100:+.2f}] pp"


def referto(sorgente_descr: str, stato: str, righe_campione: Optional[List[Dict[str, Any]]],
            conteggi: Optional[Dict[str, Any]], base: Dict[str, Dict[str, Any]],
            valutazione: Optional[Dict[str, Any]], esito: str) -> Dict[str, Any]:
    return {
        "generato_il": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sorgente": sorgente_descr, "stato_lettura": stato,
        "costanti": {
            "mercati_ou": list(RIENTRO_MERCATI_OU), "gg_ng": RIENTRO_GG_NG,
            "stagione_min": f"{RIENTRO_STAGIONE_MIN_ANNO}/{RIENTRO_STAGIONE_MIN_ANNO + 1}",
            "N_min": RIENTRO_N_MIN, "margine_calibrazione_pp": RIENTRO_MARGINE_CALIBRAZIONE * 100,
            "margine_base_rate_pp": RIENTRO_MARGINE_BASE_RATE * 100, "livello_ic": RIENTRO_LIVELLO_IC,
            "repliche_bootstrap": RIENTRO_REPLICHE_BOOTSTRAP, "seme": RIENTRO_SEME,
            "stagioni_base_rate": list(RIENTRO_STAGIONI_BASE_RATE), "origine": RIENTRO_ORIGINE,
            "selettore": RIENTRO_SELETTORE,
        },
        "base_rate_over25": base,
        "campione": conteggi,
        "valutazione": valutazione,
        "esito": esito,
    }


def scrivi_markdown(r: Dict[str, Any], percorso: Path) -> None:
    v = r.get("valutazione") or {}
    k = r["costanti"]
    righe = [
        "# Regola di rientro dei Totali nel Top Mix (registro ombra)",
        "",
        f"Generato: `{r['generato_il']}` - sola lettura, nessuna scrittura nel registro.",
        "",
        f"**Sorgente:** {r['sorgente']}  ",
        f"**Stato della lettura:** {r['stato_lettura']}",
        "",
        f"## Esito",
        "",
        f"**{r['esito']}**",
        "",
        "## Costanti (fissate prima dei dati)",
        "",
        "| costante | valore |",
        "|---|---|",
        f"| mercati che possono rientrare | {', '.join(k['mercati_ou'])} (solo O/U 2.5) |",
        f"| GG/NG | {k['gg_ng']} (registrati in ombra, mai rientrano) |",
        f"| campione fuori campione | stagione {k['stagione_min']} in poi |",
        f"| N minimo (scelte O/U ammesse giudicate) | {k['N_min']} |",
        f"| (a) margine calibrazione | hit - confidenza media >= {k['margine_calibrazione_pp']:+.0f} pp, IC include 0 o sta sopra |",
        f"| (b) margine base rate | hit - base rate O/U >= {k['margine_base_rate_pp']:+.0f} pp, IC esclude 0 |",
        f"| IC | {k['livello_ic'] * 100:.0f}% percentile, bootstrap a blocchi lega-giornata-stagione |",
        f"| repliche / seme | {k['repliche_bootstrap']} / {k['seme']} |",
        f"| base rate O/U | stagioni {', '.join(f'{a}/{a + 1}' for a in k['stagioni_base_rate'])} dai CSV del repo (esclusa la stagione in corso) |",
        "",
        "## Base rate Over 2.5 (riferimento, per lega)",
        "",
        "| lega | partite | Over 2.5 | tasso |",
        "|---|---:|---:|---:|",
    ]
    for lega, b in sorted(r["base_rate_over25"].items()):
        righe.append(f"| {lega} | {b['n']} | {b['over']} | {b['rate'] * 100:.1f}% |")
    if not r["base_rate_over25"]:
        righe.append("| (nessun CSV di riferimento trovato) | - | - | - |")
    righe += ["", "## Campione", ""]
    c = r.get("campione") or {}
    if c:
        righe += ["| voce | n |", "|---|---:|"]
        for chiave, valore in c.items():
            righe.append(f"| {chiave} | {valore} |")
    else:
        righe.append("Nessun dato letto: la sorgente non era raggiungibile (vedi stato).")
    righe += ["", "## Criteri", ""]
    if v:
        righe += [
            f"- scelte O/U ammesse fuori campione: {v.get('ammesse_fuori_campione', 0)}; "
            f"giudicate (N): **{v.get('giudicate_N', 0)}** (minimo {RIENTRO_N_MIN}); in attesa: {v.get('in_attesa', 0)}",
        ]
        if "hit_rate" in v:
            righe += [
                f"- Over: {v.get('over_scelte', 0)}, Under: {v.get('under_scelte', 0)}, senza base rate: {v.get('senza_base_rate', 0)}",
                f"- hit rate: {v['hit_rate'] * 100:.2f}%; confidenza media dichiarata: {v['confidenza_media'] * 100:.2f}%",
                f"- (a) hit - confidenza: {_pct(v['a_stima'])}, IC {_ic_pct(v['bootstrap']['a_ic'])} -> "
                f"{'OK' if v['criterio_a_ok'] else 'NON OK'}",
                f"- (b) hit - base rate O/U: {_pct(v['b_stima'])}, IC {_ic_pct(v['bootstrap']['b_ic'])} -> "
                f"{'OK' if v['criterio_b_ok'] else 'NON OK'}",
                f"- blocchi bootstrap: {v['bootstrap']['blocchi']}, repliche valide: {v['bootstrap']['repliche_valide']}",
            ]
        else:
            righe.append(f"- {v.get('esito_criteri', 'criteri non calcolati')}")
    else:
        righe.append("Criteri non calcolati: nessun dato letto.")
    righe += ["", "_Lettura della regola: vedi docstring di `audit/topmix_ombra_rientro.py`. "
              "Il rientro richiede N sufficiente e (a) e (b) insieme._", ""]
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text("\n".join(righe), encoding="utf-8")


def esegui(sorgente: str, file: Optional[str], db_dir: Path, out_json: Path, out_md: Path) -> Dict[str, Any]:
    base = base_rate_over25(db_dir)
    if sorgente == "file" and not file:
        raise ValueError("--sorgente file richiede --file")
    righe, descr = carica_registro_ombra("file" if file else "upstash", file)
    if righe is None:
        r = referto(descr, "NON VERIFICABILE", None, None, base, None,
                    "NON VERIFICABILE: registro ombra non letto dalla sorgente richiesta. "
                    "Nessun conteggio e' stato fatto: zero non significa 'nessuna scelta'.")
    else:
        campione = scelte_ou_ammesse(righe)
        val = valuta(campione["righe"], base)
        r = referto(descr, "LETTO (sola lettura)", None, campione["conteggi"], base, val, decisione(val))
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(r, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    scrivi_markdown(r, out_md)
    return r


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--sorgente", choices=("upstash", "file"), default="upstash",
                   help="upstash = registro ombra vivo (sola lettura); file = export JSON")
    p.add_argument("--file", help="export JSON del registro ombra (con --sorgente file)")
    p.add_argument("--db-dir", default=str(DB_DIR))
    p.add_argument("--out-json", default=str(REFERTO_JSON))
    p.add_argument("--out-md", default=str(REFERTO_MD))
    a = p.parse_args(argv)
    r = esegui("file" if a.file else a.sorgente, a.file, Path(a.db_dir), Path(a.out_json), Path(a.out_md))
    print(r["esito"])
    print(f"sorgente: {r['sorgente']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
