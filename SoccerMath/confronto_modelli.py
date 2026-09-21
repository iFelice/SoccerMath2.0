"""Percentuale di successo dei due motori, SENZA le righe di transizione (SOLA LETTURA).

Domanda a cui risponde: la percentuale di successo della tabella Legacy e' davvero
piu' alta di quella del Drago a 2 Teste, o la differenza sta dentro il margine di
errore di un campione piccolo?

Il conto si fa sui CLICK VERI del Registro, escludendo le righe di TRANSIZIONE:
quelle che nessuno dei due motori definitivi riproduce pur essendo partite giocate
dentro la finestra ricostruibile (``REPLAY_START_INSTANT``). Sono le righe scritte
da un codice intermedio, ne' il vecchio ne' il nuovo: contarle in una delle due
tabelle falserebbe il confronto fra i motori.

Per ogni motore si stampa: righe, decise, vinte, perse, in attesa, percentuale di
successo con intervallo di Wilson al 95%, probabilita' media dichiarata, Brier e
gap di calibrazione. Il confronto fra i due usa:

* l'intervallo di confidenza della DIFFERENZA (metodo ibrido di Newcombe);
* il test esatto di Fisher sulla tabella 2x2;
* la differenza minima rilevabile (MDE) all'80% di potenza con questi numeri;
* quante righe servirebbero perche' una differenza cosi' si veda davvero;
* due controprove APPAIATE (stesse partite, un solo confronto per partita):
  - sui CLICK VERI del Registro: le partite che hanno la riga di ENTRAMBI i
    motori (due click in momenti diversi: stesso avversario, dati diversi);
  - sulle ricostruzioni del replay: stesso istante, stessi dati, due motori.
  Per ognuna, test esatto di McNemar sulle coppie discordanti.

Verdetto esplicito: se l'intervallo della differenza contiene lo zero, il campione
NON basta a dire chi e' piu' forte. Il referto lo dice a parole, non lo nasconde.

Nessuna scrittura, in nessun caso: questo strumento legge e riferisce.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone
from math import comb, erf, sqrt
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from prediction_registry import (  # noqa: E402
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_LEGACY,
    dedup_key,
    entry_instant,
    model_variant_read,
    origin_of,
    outcome_of_entry,
    prob_of_entry,
)
from registry_coverage_check import load_registry_readonly  # noqa: E402
from replay_legacy_topmix import REPLAY_START_INSTANT  # noqa: E402
from righe_non_ricostruite import kickoff_della_riga  # noqa: E402
from season_calendar import season_label, season_start_year_of  # noqa: E402

UTC = timezone.utc
Z95 = 1.959963984540054     # quantile normale 97,5%
STAGIONE_CORRENTE = "2026/2027"
LIMITE_MERCATI = 12         # quanti mercati stampare nel referto compatto

NOMI = {
    "drago": "Drago a 2 Teste (motore attuale)",
    "legacy_pulito": "Legacy, senza le righe di transizione",
    "legacy_riprodotto": "Legacy, solo righe rifatte dal replay",
    "legacy_solo_stagione": f"Legacy pulito, sola stagione {STAGIONE_CORRENTE}",
    "legacy_tutto": "Legacy come in tabella (transizione inclusa)",
    "transizione": "Righe di transizione (ESCLUSE dal confronto)",
    "legacy_fuori_finestra": "Legacy non rifatte: partita prima della finestra",
}


# ---------------------------------------------------------------------------
# Statistica di base (nessuna dipendenza esterna: scipy non e' in requirements)
# ---------------------------------------------------------------------------
def wilson(vinte: int, decise: int, z: float = Z95) -> Tuple[float, float]:
    """Intervallo di Wilson al 95% per una proporzione (k su n)."""
    if decise <= 0:
        return (0.0, 1.0)
    p = vinte / decise
    den = 1.0 + z * z / decise
    centro = (p + z * z / (2.0 * decise)) / den
    semi = (z / den) * sqrt(p * (1.0 - p) / decise + z * z / (4.0 * decise * decise))
    return (max(0.0, centro - semi), min(1.0, centro + semi))


def fisher_esatto(a: int, b: int, c: int, d: int) -> float:
    """p-value a due code del test esatto di Fisher per la tabella [[a,b],[c,d]].

    Somma le probabilita' ipergeometriche di tutte le tabelle con gli stessi
    margini che non sono piu' probabili di quella osservata (criterio standard).
    """
    n = a + b + c + d
    if n == 0:
        return 1.0
    riga1, col1 = a + b, a + c
    if riga1 in (0, n) or col1 in (0, n):
        return 1.0
    minimo, massimo = max(0, col1 - (n - riga1)), min(riga1, col1)

    def p_di(x: int) -> float:
        return comb(riga1, x) * comb(n - riga1, col1 - x) / comb(n, col1)

    p_oss = p_di(a)
    p = sum(p_di(x) for x in range(minimo, massimo + 1) if p_di(x) <= p_oss * (1.0 + 1e-9))
    return min(1.0, max(0.0, p))


def newcombe_diff(vinte1: int, decise1: int, vinte2: int, decise2: int,
                  z: float = Z95) -> Tuple[float, float]:
    """IC 95% della DIFFERENZA p1 - p2 (metodo ibrido di Newcombe, "score").

    E' la differenza fra due proporzioni indipendenti senza assumere normalita'
    dei conteggi: con 40-60 righe decise e' l'ipotesi sbagliata da evitare.
    """
    if decise1 <= 0 or decise2 <= 0:
        return (float("-inf"), float("inf"))
    p1, p2 = vinte1 / decise1, vinte2 / decise2
    lo1, hi1 = wilson(vinte1, decise1, z)
    lo2, hi2 = wilson(vinte2, decise2, z)
    d = p1 - p2
    semi_lo = sqrt((p1 - lo1) ** 2 + (hi2 - p2) ** 2)
    semi_hi = sqrt((hi1 - p1) ** 2 + (p2 - lo2) ** 2)
    return (d - semi_lo, d + semi_hi)


def _z_quantile(p: float) -> float:
    """Quantile normale standard (inverso approssimato di Phi, Acklam)."""
    if p <= 0.0:
        return float("-inf")
    if p >= 1.0:
        return float("inf")
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    p_bassa, p_alta = 0.02425, 1.0 - 0.02425
    if p < p_bassa:
        q = sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p > p_alta:
        q = sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)


def _phi(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def potenza(diff: float, p1: float, n1: int, p2: float, n2: int,
            alpha: float = 0.05) -> float:
    """Potenza del confronto fra due proporzioni (approssimazione normale)."""
    if n1 <= 0 or n2 <= 0:
        return 0.0
    z = abs(_z_quantile(alpha / 2.0))
    p_bar = (p1 * n1 + p2 * n2) / (n1 + n2)
    se0 = sqrt(p_bar * (1.0 - p_bar) * (1.0 / n1 + 1.0 / n2))
    se1 = sqrt(p1 * (1.0 - p1) / n1 + p2 * (1.0 - p2) / n2)
    if se1 <= 0:
        return 1.0
    critico = z * se0
    return min(1.0, _phi((abs(diff) - critico) / se1) + _phi((-abs(diff) - critico) / se1))


def mde(p1: float, n1: int, n2: int, target: float = 0.80) -> Optional[float]:
    """Differenza minima rilevabile all'80% di potenza con questi numeri.

    Cerca la differenza ``d`` per cui il confronto fra p1 e p1 - d con n1 e n2
    righe decise raggiunge la potenza ``target``.
    """
    if n1 <= 0 or n2 <= 0 or p1 <= 0.0:
        return None
    lo, hi = 0.0, p1
    if potenza(hi, p1, n1, 0.0, n2) < target:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if potenza(mid, p1, n1, p1 - mid, n2) < target:
            lo = mid
        else:
            hi = mid
    return hi


def n_per_gruppo(p1: float, diff: float, target: float = 0.80,
                 massimo: int = 20000) -> Optional[int]:
    """Righe decise PER MOTORE perche' una differenza ``diff`` si veda all'80%."""
    if diff <= 0:
        return None
    p2 = max(0.0, p1 - diff)
    for n in range(5, massimo + 1):
        if potenza(diff, p1, n, p2, n) >= target:
            return n
    return None


def mcnemar_esatto(b: int, c: int) -> float:
    """p-value a due code del test esatto di McNemar (b e c = coppie discordanti)."""
    n = b + c
    if n == 0:
        return 1.0
    m = min(b, c)
    p = 2.0 * sum(comb(n, k) for k in range(m + 1)) / (2.0 ** n)
    return min(1.0, p)


# ---------------------------------------------------------------------------
# Lettura delle righe
# ---------------------------------------------------------------------------
def stagione_della_riga(riga: Dict[str, Any]) -> str:
    """Stagione dichiarata, oppure ricavata dalla data di scrittura (mai vuota)."""
    campo = str(riga.get("stagione") or "").strip()
    if campo:
        return campo
    istante, _fonte = entry_instant(riga)
    if istante is None:
        return "Sconosciuta"
    return season_label(season_start_year_of(istante.date()))


def statistiche(righe: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Numeri di un gruppo di righe: successi, intervallo, calibrazione."""
    righe = list(righe)
    vinte = sum(1 for r in righe if outcome_of_entry(r) == 1)
    perse = sum(1 for r in righe if outcome_of_entry(r) == 0)
    decise = vinte + perse
    attesa = len(righe) - decise
    coppie = [(prob_of_entry(r), outcome_of_entry(r)) for r in righe]
    coppie = [(p, y) for p, y in coppie if p is not None and y is not None]
    n_prob = len(coppie)
    hit_prob = (sum(y for _p, y in coppie) / n_prob) if n_prob else None
    prob_media = (sum(p for p, _y in coppie) / n_prob) if n_prob else None
    brier = (sum((p - y) ** 2 for p, y in coppie) / n_prob) if n_prob else None
    per_mercato: Dict[str, Dict[str, int]] = {}
    for r in righe:
        mkt = str(r.get("mercato_standard") or "ALTRO").strip().upper() or "ALTRO"
        cella = per_mercato.setdefault(mkt, {"righe": 0, "vinte": 0, "perse": 0, "attesa": 0})
        cella["righe"] += 1
        y = outcome_of_entry(r)
        cella["vinte" if y == 1 else ("perse" if y == 0 else "attesa")] += 1
    return {
        "righe": len(righe),
        "vinte": vinte, "perse": perse, "attesa": attesa, "decise": decise,
        "successo": (vinte / decise) if decise else None,
        "ic95": (wilson(vinte, decise)[0], wilson(vinte, decise)[1]) if decise else None,
        "successo_su_probabilita": hit_prob,
        "prob_media": prob_media, "brier": brier,
        "gap": (prob_media - hit_prob) if (prob_media is not None and hit_prob is not None) else None,
        "per_mercato": per_mercato,
    }


def classifica(righe: Sequence[Dict[str, Any]],
               proposte: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Divide le righe Top Mix del Registro nei gruppi del confronto.

    * ``drago``: variante attuale (motore a due teste), tutte.
    * ``legacy_pulito``: variante legacy TRANNE le righe di transizione.
    * ``legacy_riprodotto``: sotto-insieme verificato dal replay (la forma
      definitiva del motore vecchio: la riga viene rifatta identica).
    * ``transizione``: righe che il replay non propone e la cui partita e' dentro
      la finestra ricostruibile: codice intermedio, ne' vecchio ne' nuovo.
    * ``legacy_fuori_finestra`` (dettaglio, incluso in ``legacy_pulito``): righe
      non proposte perche' la partita e' giocata prima dell'inizio della finestra
      (una partita di maggio non e' rigiocabile in modo onesto).
    """
    chiavi = {tuple(dedup_key(p)) for p in proposte}
    top_mix = [r for r in (righe or [])
               if str(origin_of(r) or "").strip().lower() == "top_mix"]
    gruppi: Dict[str, List[Dict[str, Any]]] = {k: [] for k in
                                              ("drago", "legacy_pulito", "legacy_riprodotto",
                                               "transizione", "legacy_fuori_finestra", "altro")}
    anomalie = {"drago_non_riproposto": 0}
    for r in top_mix:
        variante = model_variant_read(r)
        proposta = tuple(dedup_key(r)) in chiavi
        ko = kickoff_della_riga(r)
        dentro = ko is not None and ko >= REPLAY_START_INSTANT
        if variante == MODEL_VARIANT_CURRENT:
            gruppi["drago"].append(r)
            if not proposta:
                anomalie["drago_non_riproposto"] += 1
        elif variante == MODEL_VARIANT_LEGACY:
            if proposta:
                gruppi["legacy_riprodotto"].append(r)
                gruppi["legacy_pulito"].append(r)
            elif dentro:
                gruppi["transizione"].append(r)
            else:
                gruppi["legacy_pulito"].append(r)
                gruppi["legacy_fuori_finestra"].append(r)
        else:
            gruppi["altro"].append(r)
    return {"gruppi": gruppi, "anomalie": anomalie, "righe_registro": len(righe or []),
            "righe_top_mix": len(top_mix), "proposte_dal_replay": len(chiavi)}


# ---------------------------------------------------------------------------
# Confronti appaiati (stesse partite, un confronto per partita)
# ---------------------------------------------------------------------------
def _confronto_appaiato(coppie: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]],
                        con_distanza: bool = False) -> Dict[str, Any]:
    """McNemar esatto su coppie (drago, legacy) della STESSA partita.

    ``b`` = partite che il Legacy indovina e il Drago no; ``c`` il contrario.
    Le coppie con un esito mancante non entrano nel test (l'esito ancora in
    attesa non e' un pareggio: e' un dato che non c'e').
    """
    b = c = 0
    vinte = {MODEL_VARIANT_CURRENT: 0, MODEL_VARIANT_LEGACY: 0}
    decise = {MODEL_VARIANT_CURRENT: 0, MODEL_VARIANT_LEGACY: 0}
    stessi = diversi = 0
    distanze: List[float] = []
    for cur, leg in coppie:
        if str(cur.get("mercato_standard") or "") == str(leg.get("mercato_standard") or ""):
            stessi += 1
        else:
            diversi += 1
        if con_distanza:
            i1, _ = entry_instant(cur)
            i2, _ = entry_instant(leg)
            if i1 is not None and i2 is not None:
                distanze.append(abs((i1 - i2).total_seconds()) / 86400.0)
        yc, yl = outcome_of_entry(cur), outcome_of_entry(leg)
        for variante, y in ((MODEL_VARIANT_CURRENT, yc), (MODEL_VARIANT_LEGACY, yl)):
            if y is not None:
                decise[variante] += 1
                vinte[variante] += y
        if yc is None or yl is None:
            continue
        if yl == 1 and yc == 0:
            b += 1
        elif yl == 0 and yc == 1:
            c += 1
    return {
        "coppie": len(coppie),
        "coppie_decisi": b + c + sum(
            1 for cur, leg in coppie
            if outcome_of_entry(cur) is not None and outcome_of_entry(leg) is not None),
        "b_legacy_vince_drago_perde": b,
        "c_drago_vince_legacy_perde": c,
        "mcnemar_p": mcnemar_esatto(b, c),
        "decise": decise, "vinte": vinte,
        "stessi_mercati": stessi, "mercati_diversi": diversi,
        "dist_giorni_mediana": (statistics.median(distanze) if distanze else None),
    }


def _per_match_id(righe: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for r in righe or []:
        mid = r.get("match_id")
        if mid is None:
            continue
        variante = model_variant_read(r)
        cella = out.setdefault(str(mid), {})
        # una sola riga per (partita, motore): se ce ne fossero due, vince la prima
        cella.setdefault(variante, r)
    return out


def coppie_registro(gruppo_drago: Sequence[Dict[str, Any]],
                    gruppo_legacy: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Coppie sui CLICK VERI: partite che hanno la riga di entrambi i motori.

    Sono due click in momenti diversi (prima e dopo il merge), quindi i dati non
    sono gli stessi: il confronto resta appaiato per partita, non per istante.
    """
    per_id = _per_match_id(gruppo_drago)
    for mid, cella in _per_match_id(gruppo_legacy).items():
        per_id.setdefault(mid, {}).update(cella)
    coppie = [(v[MODEL_VARIANT_CURRENT], v[MODEL_VARIANT_LEGACY])
              for v in per_id.values()
              if MODEL_VARIANT_CURRENT in v and MODEL_VARIANT_LEGACY in v]
    d = _confronto_appaiato(coppie, con_distanza=True)
    d["partite_con_entrambi"] = len(coppie)
    d["partite_con_righe"] = len(per_id)
    return d


def coppie_replay(proposte: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Coppie sulle RICOSTRUZIONI: stesso istante, stessi dati, due motori.

    Le righe del replay non sono click veri: servono solo a rispondere a "a
    parita' di partita e di dati, chi indovina di piu'?".
    """
    per_id = _per_match_id(proposte)
    coppie = [(v[MODEL_VARIANT_CURRENT], v[MODEL_VARIANT_LEGACY])
              for v in per_id.values()
              if MODEL_VARIANT_CURRENT in v and MODEL_VARIANT_LEGACY in v]
    d = _confronto_appaiato(coppie)
    d["partite_con_entrambi"] = len(coppie)
    d["partite_con_righe"] = len(per_id)
    return d


# ---------------------------------------------------------------------------
# Confronto fra i due motori
# ---------------------------------------------------------------------------
def confronto_due_motori(st_drago: Dict[str, Any], st_legacy: Dict[str, Any]) -> Dict[str, Any]:
    """Differenza legacy meno drago, con intervallo, test e potenza."""
    vd, dd = st_drago["vinte"], st_drago["decise"]
    vl, dl = st_legacy["vinte"], st_legacy["decise"]
    out: Dict[str, Any] = {"decise_drago": dd, "decise_legacy": dl}
    if dd == 0 or dl == 0:
        out["motivo"] = "un motore non ha righe decise: confronto impossibile"
        return out
    diff = vl / dl - vd / dd
    lo, hi = newcombe_diff(vl, dl, vd, dd)
    p = fisher_esatto(vl, dl - vl, vd, dd - vd)
    out.update({
        "diff": diff, "ic95_diff": (lo, hi), "fisher_p": p,
        "mde80": mde(vl / dl, dl, dd),
        "n_per_gruppo_alla_diff_osservata": n_per_gruppo(vl / dl, abs(diff)) if diff else None,
        "significativo": lo > 0.0 or hi < 0.0,
    })
    return out


def ritmo_settimanale(gruppi: Dict[str, List[Dict[str, Any]]], giorni: int = 21) -> Dict[str, Any]:
    """Righe scritte per motore nelle ultime ``giorni`` giornate: quanto cresce il campione."""
    adesso = datetime.now(UTC)
    out: Dict[str, Any] = {"giorni": giorni}
    for nome in ("drago", "legacy_pulito"):
        n = sum(1 for r in gruppi.get(nome, [])
                if (entry_instant(r)[0] is not None and entry_instant(r)[0] >= adesso - timedelta(days=giorni)))
        out[nome] = n / (giorni / 7.0)
    return out


def verdetto(d: Dict[str, Any]) -> str:
    """La risposta in una frase, senza giri di parole."""
    c = d.get("confronto") or {}
    if c.get("diff") is None:
        return "confronto non calcolabile: mancano righe decise in uno dei due motori"
    diff_pp = c["diff"] * 100.0
    lo, hi = c["ic95_diff"][0] * 100.0, c["ic95_diff"][1] * 100.0
    verso = "piu' alta" if diff_pp > 0 else "piu' bassa"
    base = (f"la percentuale Legacy e' {verso} di {abs(diff_pp):.1f} punti, ma l'intervallo di "
            f"confidenza della differenza va da {lo:+.1f} a {hi:+.1f} punti")
    if c["significativo"]:
        return (base + f" (zero escluso, Fisher p={c['fisher_p']:.3f}): con questi numeri la differenza "
                "non si spiega col solo caso. Resta un campione piccolo: e' un indizio forte, non una "
                "misura stabile.")
    mde_pp = "n.d." if c["mde80"] is None else f"{c['mde80'] * 100.0:.1f}"
    return (base + f", cioe' COMPRENDE lo zero (Fisher p={c['fisher_p']:.3f}): con questo campione la "
            f"differenza sta dentro il normale margine di errore. Con questi numeri si vedrebbe solo una "
            f"differenza di almeno {mde_pp} punti. Il campione NON basta per dire quale motore e' piu' "
            "forte.")


def _settimane(mancano: int, ritmo: float) -> str:
    if ritmo <= 0.05:
        return "il campione non cresce da solo (nessuna riga nuova nel periodo)"
    return f"~{mancano / ritmo:.0f} settimane al ritmo attuale ({ritmo:.1f} righe/settimana)"


def _attesa(d: Dict[str, Any]) -> Optional[str]:
    """Quanto manca, al ritmo attuale, per un campione che regga un verdetto.

    Due misure, tenute separate perche' dicono cose diverse:

    * una differenza **di 10 punti** (il tipo di scarto che conta davvero fra due
      motori): quante righe decise servono per motore e quanto tempo e' al ritmo;
    * la differenza **osservata oggi**: se e' piccola, il numero di righe
      necessarie e' enorme, e dirlo e' la risposta onesta ("non e' un campione
      che si raggiunge in una stagione").
    """
    c = d.get("confronto") or {}
    if c.get("diff") is None:
        return None
    st = d["statistiche"]
    p1 = st["legacy_pulito"]["successo"]
    if p1 is None:
        return None
    r = ritmo_settimanale(d["gruppi"])
    parti: List[str] = []
    n10 = n_per_gruppo(p1, 0.10)
    if n10:
        mancano_l = max(0, n10 - st["legacy_pulito"]["decise"])
        mancano_d = max(0, n10 - st["drago"]["decise"])
        parti.append(f"per vedere una differenza di 10 punti all'80% servono ~{n10} righe decise "
                     f"per motore: mancano {mancano_l} al Legacy e {mancano_d} al Drago "
                     f"({_settimane(max(mancano_l, mancano_d), (r.get('drago') or 0.0) * 0.7)})")
    n_oss = c.get("n_per_gruppo_alla_diff_osservata")
    if n_oss:
        parti.append(f"per vedere la differenza osservata ({c['diff'] * 100.0:+.1f} punti) "
                     f"servirebbero ~{n_oss} righe decise per motore"
                     + (" (fuori portata: la differenza e' troppo piccola per questi numeri)"
                        if n_oss > 2000 else ""))
    return "; ".join(parti) if parti else None


def costruisci(righe: Sequence[Dict[str, Any]], proposte: Sequence[Dict[str, Any]],
               fonte: str = "") -> Dict[str, Any]:
    d = classifica(righe, proposte)
    g = d["gruppi"]
    d["statistiche"] = {
        "drago": statistiche(g["drago"]),
        "legacy_pulito": statistiche(g["legacy_pulito"]),
        "legacy_riprodotto": statistiche(g["legacy_riprodotto"]),
        "legacy_tutto": statistiche(g["legacy_pulito"] + g["transizione"]),
        "transizione": statistiche(g["transizione"]),
        "legacy_fuori_finestra": statistiche(g["legacy_fuori_finestra"]),
        "legacy_solo_stagione": statistiche(
            [r for r in g["legacy_pulito"] if stagione_della_riga(r) == STAGIONE_CORRENTE]),
        "altro": statistiche(g["altro"]),
    }
    d["confronto"] = confronto_due_motori(d["statistiche"]["drago"], d["statistiche"]["legacy_pulito"])
    d["confronti_robustezza"] = {
        chiave: confronto_due_motori(d["statistiche"]["drago"], d["statistiche"][chiave])
        for chiave in ("legacy_solo_stagione", "legacy_riprodotto")}
    d["coppie_registro"] = coppie_registro(g["drago"], g["legacy_pulito"])
    d["coppie_registro_tutte"] = coppie_registro(g["drago"], g["legacy_pulito"] + g["transizione"])
    d["coppie_replay"] = coppie_replay(proposte)
    d["attesa"] = _attesa(d)
    d["fonte"] = fonte
    d["verdetto"] = verdetto(d)
    return d


# ---------------------------------------------------------------------------
# Referto
# ---------------------------------------------------------------------------
def _pct(x: Optional[float], dec: int = 1) -> str:
    return "n.d." if x is None else f"{x * 100.0:.{dec}f}%"


def _ic(st: Dict[str, Any]) -> str:
    return f"{st['ic95'][0] * 100.0:.1f}-{st['ic95'][1] * 100.0:.1f}" if st.get("ic95") else "n.d."


def _confronto_testo(nome: str, c: Dict[str, Any]) -> str:
    if c.get("diff") is None:
        return f"{nome}: {c.get('motivo', 'n.d.')}"
    mde_pp = "n.d." if c["mde80"] is None else f"{c['mde80'] * 100.0:.1f} pp"
    return (f"{nome}: {c['diff'] * 100.0:+.1f} pp (IC95 {c['ic95_diff'][0] * 100.0:+.1f}.."
            f"{c['ic95_diff'][1] * 100.0:+.1f}) · Fisher p={c['fisher_p']:.3f} · MDE(80%) {mde_pp} · "
            f"fuori dal margine: {'si' if c['significativo'] else 'NO'}")


def _riga_coppie(nome: str, r: Dict[str, Any], extra: str = "") -> str:
    if not r.get("partite_con_entrambi"):
        return f"COPPIE| {nome} | nessuna partita con entrambi i motori{extra}"
    return (f"COPPIE| {nome} | coppie {r['partite_con_entrambi']} | Legacy vince-Drago perde "
            f"{r['b_legacy_vince_drago_perde']} | Drago vince-Legacy perde "
            f"{r['c_drago_vince_legacy_perde']} | McNemar p={r['mcnemar_p']:.3f} | "
            f"stesso mercato {r['stessi_mercati']} / mercati diversi {r['mercati_diversi']}{extra}")


def righe_compatti(d: Dict[str, Any]) -> List[str]:
    """Righe brevi prefissate, per i referti con tetto di caratteri (annotazioni CI)."""
    g = d["gruppi"]
    out: List[str] = ["CAMPIONE| " + " | ".join([
        f"Registro Top Mix {d['righe_top_mix']}",
        f"proposte dal replay {d['proposte_dal_replay']}",
        f"Drago {len(g['drago'])}",
        f"Legacy pulito {len(g['legacy_pulito'])}",
        f"transizione escluse {len(g['transizione'])}",
        f"Legacy in tabella {len(g['legacy_pulito']) + len(g['transizione'])}",
        f"di cui non rifatte (partita prima della finestra) {len(g['legacy_fuori_finestra'])}",
    ])]
    for chiave in ("drago", "legacy_pulito", "legacy_solo_stagione", "legacy_riprodotto",
                   "legacy_tutto", "transizione", "legacy_fuori_finestra"):
        st = d["statistiche"].get(chiave)
        if not st:
            continue
        brier = "n.d." if st["brier"] is None else f"{st['brier']:.3f}"
        out.append(f"GRUPPO| {NOMI.get(chiave, chiave)} | righe {st['righe']} | decise {st['decise']} | "
                   f"vinte {st['vinte']} | perse {st['perse']} | attesa {st['attesa']} | "
                   f"successo {_pct(st['successo'])} | IC95 {_ic(st)} | prob media "
                   f"{_pct(st['prob_media'])} | Brier {brier}")
    c = d.get("confronto") or {}
    out.append("CONFRONTO| " + _confronto_testo("Legacy pulito meno Drago", c))
    for chiave, c2 in (d.get("confronti_robustezza") or {}).items():
        out.append("ROBUSTEZZA| " + _confronto_testo(NOMI.get(chiave, chiave), c2))
    out.append(_riga_coppie("click veri del Registro (partite con entrambe le righe)",
                            d.get("coppie_registro") or {},
                            extra=(" | distanza mediana fra i due click: "
                                   f"{(d['coppie_registro'].get('dist_giorni_mediana') or 0):.1f} giorni"
                                   if d.get("coppie_registro") else "")))
    out.append(_riga_coppie("ricostruzioni del replay (stesso istante, stessi dati)",
                            d.get("coppie_replay") or {}))
    tutte = d.get("coppie_registro_tutte") or {}
    pulite = d.get("coppie_registro") or {}
    if tutte.get("partite_con_entrambi") and tutte != pulite:
        out.append(f"COPPIE| click veri se si tenesse dentro anche la transizione | coppie "
                   f"{tutte['partite_con_entrambi']} (contro {pulite.get('partite_con_entrambi', 0)} "
                   f"pulite) | l'esclusione toglie "
                   f"{tutte['partite_con_entrambi'] - pulite.get('partite_con_entrambi', 0)} coppie")
    for mkt, cella in sorted((d["statistiche"]["drago"].get("per_mercato") or {}).items(),
                             key=lambda kv: -(kv[1]["vinte"] + kv[1]["perse"]))[:LIMITE_MERCATI]:
        leg = (d["statistiche"]["legacy_pulito"].get("per_mercato") or {}).get(mkt, {})
        dec_d = cella["vinte"] + cella["perse"]
        dec_l = leg.get("vinte", 0) + leg.get("perse", 0)
        if dec_d < 3 and dec_l < 3:
            continue
        out.append(f"MERCATO| {mkt} | Drago {cella['vinte']}/{dec_d}"
                   f" ({_pct(cella['vinte'] / dec_d if dec_d else None)}) | "
                   f"Legacy {leg.get('vinte', 0)}/{dec_l} "
                   f"({_pct(leg.get('vinte', 0) / dec_l if dec_l else None)})")
    out.append(f"VERDETTO| {d['verdetto']}")
    if d.get("attesa"):
        out.append(f"RITMO| {d['attesa']}")
    return out


def righe_testo(d: Dict[str, Any]) -> List[str]:
    g = d["gruppi"]
    L: List[str] = ["## Percentuale di successo dei due motori, senza le righe di transizione (sola lettura)", ""]
    L.append(f"- righe del Registro: **{d['righe_registro']}** · Top Mix: **{d['righe_top_mix']}** · "
             f"righe proposte dal replay: **{d['proposte_dal_replay']}**")
    L.append(f"- **Drago a 2 Teste {len(g['drago'])}** · **Legacy pulito {len(g['legacy_pulito'])}** · "
             f"**transizione (escluse) {len(g['transizione'])}** · "
             f"(Legacy come in tabella {len(g['legacy_pulito']) + len(g['transizione'])})")
    L.append(f"- righe Drago non riproposte dal replay: {d['anomalie']['drago_non_riproposto']} · "
             f"righe Legacy rifatte dal replay: {len(g['legacy_riprodotto'])}")
    L.append("")
    L.append("| gruppo | righe | decise | vinte | perse | attesa | successo | IC 95% | prob. media | Brier |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for chiave in ("drago", "legacy_pulito", "legacy_solo_stagione", "legacy_riprodotto",
                   "legacy_tutto", "transizione", "legacy_fuori_finestra", "altro"):
        st = d["statistiche"].get(chiave)
        if not st or (chiave == "altro" and st["righe"] == 0):
            continue
        brier = "n.d." if st["brier"] is None else f"{st['brier']:.3f}"
        L.append(f"| {NOMI.get(chiave, chiave)} | {st['righe']} | {st['decise']} | {st['vinte']} | "
                 f"{st['perse']} | {st['attesa']} | **{_pct(st['successo'])}** | {_ic(st)} | "
                 f"{_pct(st['prob_media'])} | {brier} |")
    c = d.get("confronto") or {}
    L.append("")
    L.append("### Confronto Legacy − Drago (righe pulite)")
    if c.get("diff") is None:
        L.append(f"- {c.get('motivo', 'confronto non calcolabile')}")
    else:
        L.append(f"- differenza: **{c['diff'] * 100.0:+.1f} pp** · IC 95% "
                 f"{c['ic95_diff'][0] * 100.0:+.1f} … {c['ic95_diff'][1] * 100.0:+.1f} pp")
        L.append(f"- test esatto di Fisher: **p = {c['fisher_p']:.3f}**")
        mde_pp = "n.d." if c["mde80"] is None else f"{c['mde80'] * 100.0:.1f} pp"
        L.append(f"- differenza minima rilevabile all'80% di potenza con questi numeri: **{mde_pp}**")
        L.append(f"- righe decise per motore necessarie per vedere la differenza osservata all'80%: "
                 f"**{c['n_per_gruppo_alla_diff_osservata'] or 'n.d.'}** "
                 f"(oggi {c['decise_drago']} Drago e {c['decise_legacy']} Legacy)")
    for chiave, c2 in (d.get("confronti_robustezza") or {}).items():
        L.append(f"- controprova, {NOMI.get(chiave, chiave)}: {_confronto_testo('', c2).lstrip(': ')}")
    L.append("")
    L.append("### Controprove appaiate (stesse partite, un confronto per partita)")
    r = d.get("coppie_registro") or {}
    if r.get("partite_con_entrambi"):
        L.append(f"- **click veri** ({r['partite_con_entrambi']} partite con la riga di entrambi i "
                 f"motori, due click a distanza mediana di "
                 f"{(r.get('dist_giorni_mediana') or 0):.1f} giorni): concordanti senza esito decisivo "
                 f"o con lo stesso esito; discordanti Legacy vince/Drago perde "
                 f"{r['b_legacy_vince_drago_perde']} contro Drago vince/Legacy perde "
                 f"{r['c_drago_vince_legacy_perde']} · **McNemar p = {r['mcnemar_p']:.3f}**")
    else:
        L.append("- click veri: nessuna partita con la riga di entrambi i motori")
    rt = d.get("coppie_registro_tutte") or {}
    if rt.get("partite_con_entrambi") and rt != r:
        L.append(f"- se si tenesse dentro anche la transizione le coppie sui click veri sarebbero "
                 f"{rt['partite_con_entrambi']} (invece di {r.get('partite_con_entrambi', 0)}): "
                 f"l'esclusione ne toglie {rt['partite_con_entrambi'] - r.get('partite_con_entrambi', 0)}")
    r2 = d.get("coppie_replay") or {}
    if r2.get("partite_con_entrambi"):
        L.append(f"- **ricostruzioni** ({r2['partite_con_entrambi']} partite, stesso istante e stessi "
                 f"dati): discordanti {r2['b_legacy_vince_drago_perde']} a "
                 f"{r2['c_drago_vince_legacy_perde']} · **McNemar p = {r2['mcnemar_p']:.3f}** · stesso "
                 f"mercato {r2['stessi_mercati']} / mercati diversi {r2['mercati_diversi']} · sulle "
                 f"stesse partite Drago {r2['vinte'][MODEL_VARIANT_CURRENT]}/{r2['decise'][MODEL_VARIANT_CURRENT]} "
                 f"e Legacy {r2['vinte'][MODEL_VARIANT_LEGACY]}/{r2['decise'][MODEL_VARIANT_LEGACY]}")
    else:
        L.append("- ricostruzioni: nessuna partita con entrambi i motori nel referto")
    L.append("")
    L.append(f"**Verdetto**: {d['verdetto']}")
    if d.get("attesa"):
        L.append(f"- {d['attesa']}")
    return L


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--replay-json", default=None,
                    help="referto JSON del replay (serve a riconoscere le righe di transizione)")
    ap.add_argument("--compatto", action="store_true", help="righe brevi prefissate per le annotazioni")
    ap.add_argument("--json", dest="json_out", default=None, help="scrive il dettaglio in JSON")
    args = ap.parse_args(argv)

    righe, fonte = load_registry_readonly()
    if righe is None:
        print("::error title=successo::Registro non leggibile (ne' remoto ne' locale)")
        return 2
    if not args.replay_json or not os.path.exists(args.replay_json):
        print(f"::error title=successo::referto del replay non trovato ({args.replay_json}): senza le "
              "righe proposte non si distinguono le righe di transizione")
        return 2
    with open(args.replay_json, encoding="utf-8") as f:
        report = json.load(f)
    proposte: List[Dict[str, Any]] = []
    for campo in ("entries_current", "entries_legacy",
                  "entries_current_non_scritte", "entries_legacy_non_scritte"):
        proposte.extend(report.get(campo) or [])

    d = costruisci(righe, proposte, fonte=fonte)
    d["replay_json"] = args.replay_json
    print("\n".join(righe_compatti(d) if args.compatto else righe_testo(d)))
    if fonte not in ("upstash", "jsonbin"):
        print(f"::warning title=successo::sto leggendo la copia '{fonte}', NON il Registro vivo")
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
