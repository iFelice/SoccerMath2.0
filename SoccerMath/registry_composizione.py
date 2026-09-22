"""Composizione del Registro vivo: che specie di righe contiene (SOLA LETTURA).

Risponde a una domanda precisa, nata da una verifica in UI: "perche' la tabella
del modello legacy ha 127 righe e quella del modello attuale 77?". I due numeri
**non** sono due campioni dello stesso esperimento:

* la tabella legacy contiene TUTTE le righe lette ``legacy``, e fra queste ci
  sono righe che il Top Mix non ha mai prodotto (Analisi Rapida, Billy) e righe
  di partite che il modello attuale non avrebbe selezionato (sotto soglia o
  veto: la causa la misura ``diagnose_scarti_model_variant``);
* la tabella attuale contiene solo le righe del motore Elo post-fix PR#24.

Qui si contano le righe per **origine**, **variante letta** e **stagione**, e si
dichiara quante stanno dentro la finestra ricostruibile del replay (le sole che
si possono rigiocare onestamente). Nessuna scrittura: il Registro si legge e
basta (``registry_coverage_check.load_registry_readonly``, lo stesso strato del
resto del programma: mai descrivere JSONBin quando il backend attivo e' Upstash).

Uso:

    python SoccerMath/registry_composizione.py                 # testo
    python SoccerMath/registry_composizione.py --json out.json # anche JSON
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from prediction_registry import (  # noqa: E402
    KICKOFF_UTC_FIELD,
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_LABELS,
    MODEL_VARIANT_LEGACY,
    MODEL_VERSION_FIELD,
    TZ_ITALY,
    entry_instant,
    is_current_model,
    model_variant_read,
    origin_of,
    parse_datetime,
    parse_kickoff,
)
from registry_coverage_check import load_registry_readonly  # noqa: E402
from replay_legacy_topmix import REPLAY_START_INSTANT  # noqa: E402
from season_calendar import season_label, season_start_year_of  # noqa: E402

# Origini etichettate come le mostra la UI (``prediction_registry.tipo_for_origin``).
ORIGINI_NOTE = {
    "top_mix": "Top Mix",
    "analisi_rapida": "Analisi Rapida",
    "billy": "Billy",
}


def _etichetta_origine(origine: Any) -> str:
    testo = str(origine or "").strip().lower()
    if not testo:
        return "senza campo origine"
    return ORIGINI_NOTE.get(testo, f"altra origine ({testo})")


def _stagione(riga: Dict[str, Any]) -> str:
    """Stagione della riga: il campo se c'e', altrimenti dalla data.

    Il confine e' quello unico della pipeline (``season_calendar``, 1 luglio).
    Una riga senza data leggibile non si inventa: finisce in "Sconosciuta", e
    il conteggio lo dice (e' la stessa etichetta che mette la UI).
    """
    campo = str(riga.get("stagione") or "").strip()
    if campo:
        return campo
    istante, _fonte = entry_instant(riga)
    if istante is None:
        return "Sconosciuta"
    return season_label(season_start_year_of(istante.date()))


def _fischio(riga: Dict[str, Any]) -> Optional[datetime]:
    """Fischio d'inizio della partita (ora italiana), None se non si legge.

    Prima scelta ``kickoff_utc`` (ISO UTC), poi la ``data`` italiana. E' il
    termine di confronto per capire se una riga e' nata PRIMA della partita (una
    previsione) o DOPO (un commento a cose fatte).
    """
    ko = parse_kickoff(riga.get(KICKOFF_UTC_FIELD))
    if ko is not None:
        return ko.astimezone(TZ_ITALY)
    return parse_datetime(riga.get("data"))


def puntualita(righe: List[Dict[str, Any]], *,
               origini: Tuple[str, ...] = ("top_mix",)) -> Dict[str, Any]:
    """Le righe sono state scritte PRIMA del fischio d'inizio? (nessun risultato noto)

    E' la proprieta' che rende le due tabelle un confronto fra modelli e non un
    commento a posteriori: una riga salvata dopo il fischio conosceva il
    risultato, e non e' una previsione. Il confronto e' fra l'istante di nascita
    della riga (``salvato_il``) e l'ora della partita.

    ``origini`` limita il conto alle righe che contano (default: solo Top Mix,
    cioe' cio' che finisce nelle due tabelle). Le righe senza fischio
    interpretabile NON si danno per buone: finiscono in una voce a parte.
    """
    per_origine = defaultdict(Counter)
    in_ritardo: Dict[str, List[str]] = defaultdict(list)
    senza_fischio: Dict[str, List[str]] = defaultdict(list)
    for riga in righe:
        grezza = str(origin_of(riga) or "").strip().lower()
        if grezza not in origini:
            continue
        origine = _etichetta_origine(origin_of(riga))
        nata, fonte = entry_instant(riga)
        fischio = _fischio(riga)
        if nata is None or fischio is None:
            per_origine[origine]["fischio o nascita non leggibili"] += 1
            senza_fischio[origine].append(dettaglio_riga(riga))
            continue
        if nata < fischio:
            per_origine[origine]["nate prima del fischio"] += 1
        else:
            per_origine[origine]["nate DOPO il fischio"] += 1
            ore = (nata - fischio).total_seconds() / 3600.0
            in_ritardo[origine].append(f"{dettaglio_riga(riga)} · scritta {ore:+.1f} h dopo "
                                       f"il fischio (nascita da `{fonte}`)")
    return {
        "per_origine": {k: dict(v) for k, v in per_origine.items()},
        "in_ritardo": {k: v for k, v in in_ritardo.items()},
        "senza_fischio": {k: v for k, v in senza_fischio.items()},
    }


def contenuto_tabelle(righe: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Cosa conterranno le DUE tabelle: solo Top Mix, per motore e per stagione.

    Non e' un conteggio dell'hash: e' esattamente il contenuto delle due tabelle
    (Top Mix, una per motore), cioe' il numero da confrontare con quello che si
    vede in pagina. Le righe di altre origini (Analisi Rapida, Billy, senza
    origine) NON entrano in nessuna delle due.
    """
    per_motore: Dict[str, Counter] = defaultdict(Counter)
    fuori: Dict[str, int] = {}
    for riga in righe:
        origine = str(origin_of(riga) or "").strip().lower()
        etichetta = _etichetta_origine(origin_of(riga))
        if origine != "top_mix":
            fuori[etichetta] = fuori.get(etichetta, 0) + 1
            continue
        per_motore[model_variant_read(riga)][_stagione(riga)] += 1
    return {
        "per_motore": {k: dict(v) for k, v in per_motore.items()},
        "totale_per_motore": {k: sum(v.values()) for k, v in per_motore.items()},
        "fuori_dalle_tabelle": fuori,
    }


def _in_finestra(riga: Dict[str, Any]) -> Optional[bool]:
    """La riga sta nella finestra ricostruibile del replay? ``None`` se non si sa."""
    istante, _fonte = entry_instant(riga)
    if istante is None:
        return None
    return istante >= REPLAY_START_INSTANT


def dettaglio_riga(riga: Dict[str, Any]) -> str:
    """Una riga in una riga di testo: partita, data, origine, variante, scheda."""
    istante, fonte = entry_instant(riga)
    return (f"{riga.get('home')} - {riga.get('away')} · {riga.get('data') or 'data n/d'} · "
            f"origine `{riga.get('origin') or 'assente'}` · letto "
            f"{MODEL_VARIANT_LABELS.get(model_variant_read(riga), model_variant_read(riga))} · "
            f"nato {istante.strftime('%d/%m/%Y %H:%M') if istante else 'istante n/d'} "
            f"({fonte}) · `model_version` {riga.get(MODEL_VERSION_FIELD) or 'assente'} · "
            f"match_id {riga.get('match_id')}")


def analizza(righe: List[Dict[str, Any]], *, origini_escluse: Tuple[str, ...] = ("top_mix",)) -> Dict[str, Any]:
    """Conteggi della composizione: nessuna scrittura, nessuna finestra nascosta.

    ``origini_escluse`` sono le origini che NON si vogliono elencare riga per
    riga (default: ``top_mix``, che e' la grande maggioranza): nel risultato
    finisce l'**elenco** di tutte le altre, per rispondere a "quali partite sono
    quelle righe?", non solo a "quante sono".
    """
    per_origine: Counter = Counter()
    per_variante: Counter = Counter()
    per_stagione: Counter = Counter()
    incrocio = defaultdict(Counter)          # origine -> variante
    stagione_per_origine = defaultdict(Counter)   # origine -> stagione
    scheda_vecchia = Counter()               # origine -> righe senza model_version
    per_finestra = Counter()
    elenco: Dict[str, List[str]] = defaultdict(list)
    senza_campo_variante = 0
    istante_ignoto = 0
    for riga in righe:
        grezza = str(origin_of(riga) or "").strip().lower()
        origine = _etichetta_origine(origin_of(riga))
        variante = model_variant_read(riga)
        per_origine[origine] += 1
        per_variante[variante] += 1
        stagione = _stagione(riga)
        per_stagione[stagione] += 1
        incrocio[origine][variante] += 1
        stagione_per_origine[origine][stagione] += 1
        if grezza not in origini_escluse:
            elenco[origine].append(dettaglio_riga(riga))
        if not str(riga.get(MODEL_VERSION_FIELD) or "").strip():
            scheda_vecchia[origine] += 1
        dentro = _in_finestra(riga)
        per_finestra["dentro la finestra ricostruibile" if dentro else
                     ("fuori finestra (prima del 30/08/2026)" if dentro is False else
                      "istante non leggibile")] += 1
        if not str(riga.get("model_variant") or "").strip():
            senza_campo_variante += 1
        if entry_instant(riga)[0] is None:
            istante_ignoto += 1
    return {
        "righe": len(righe),
        "per_origine": dict(per_origine),
        "per_variante": dict(per_variante),
        "per_stagione": dict(per_stagione),
        "origine_per_variante": {k: dict(v) for k, v in incrocio.items()},
        "origine_per_stagione": {k: dict(v) for k, v in stagione_per_origine.items()},
        "senza_campo_variante": senza_campo_variante,
        "istante_ignoto": istante_ignoto,
        "scheda_vecchia_per_origine": dict(scheda_vecchia),
        "finestra": dict(per_finestra),
        "elenco": {k: sorted(v) for k, v in elenco.items()},
        "confine_finestra": REPLAY_START_INSTANT.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _righe_testo(d: Dict[str, Any]) -> List[str]:
    L: List[str] = ["## Composizione del Registro (sola lettura)", ""]
    L.append(f"- righe totali: **{d['righe']}** · finestra ricostruibile dal {d['confine_finestra']}")
    L.append("- per origine: " + ", ".join(f"**{k}** {v}" for k, v in sorted(d["per_origine"].items())))
    L.append("- per variante LETTA (campo o DATA): "
             + ", ".join(f"`{MODEL_VARIANT_LABELS.get(k, k)}` **{v}**"
                         for k, v in sorted(d["per_variante"].items())))
    L.append("- per stagione: " + ", ".join(f"**{k}** {v}" for k, v in sorted(d["per_stagione"].items())))
    L.append("- " + " · ".join(f"{k}: **{v}**" for k, v in sorted(d["finestra"].items())))
    L.append(f"- righe senza campo `model_variant`: **{d['senza_campo_variante']}** · "
             f"senza istante leggibile: **{d['istante_ignoto']}**")
    L.append("")
    L.append("| origine | righe | lette attuale | lette legacy | senza `model_version` | stagioni |")
    L.append("|---|---|---|---|---|---|")
    for origine, conteggi in sorted(d["origine_per_variante"].items(),
                                    key=lambda kv: -sum(kv[1].values())):
        stagioni = " · ".join(f"{s} {n}" for s, n in
                              sorted(d["origine_per_stagione"].get(origine, {}).items(), reverse=True))
        L.append(f"| {origine} | {sum(conteggi.values())} | "
                 f"{conteggi.get(MODEL_VARIANT_CURRENT, 0)} | "
                 f"{conteggi.get(MODEL_VARIANT_LEGACY, 0)} | "
                 f"{d['scheda_vecchia_per_origine'].get(origine, 0)} | {stagioni} |")
    for origine, voci in sorted(d["elenco"].items()):
        L.append("")
        L.append(f"### Elenco righe — origine {origine} ({len(voci)})")
        for voce in voci:
            L.append(f"- {voce}")

    ct = d.get("contenuto_tabelle") or {}
    if ct:
        L.append("")
        L.append("### Contenuto delle due tabelle (solo Top Mix, per motore)")
        tot = ct.get("totale_per_motore", {})
        L.append("- DRAGO A 2 TESTE (`current`): **" + str(tot.get(MODEL_VARIANT_CURRENT, 0)) + "** righe · "
                 + (" · ".join(f"{s} {n}" for s, n in sorted(ct["per_motore"].get(MODEL_VARIANT_CURRENT, {}).items(), reverse=True))
                    or "nessuna stagione"))
        L.append("- LEGACY (`legacy`): **" + str(tot.get(MODEL_VARIANT_LEGACY, 0)) + "** righe · "
                 + (" · ".join(f"{s} {n}" for s, n in sorted(ct["per_motore"].get(MODEL_VARIANT_LEGACY, {}).items(), reverse=True))
                    or "nessuna stagione"))
        fuori = ct.get("fuori_dalle_tabelle", {})
        L.append("- fuori dalle due tabelle: " + (", ".join(f"{k} {v}" for k, v in sorted(fuori.items()))
                                                  or "niente") + " (per costruzione: non sono Top Mix)")

    pu = d.get("puntualita") or {}
    if pu:
        L.append("")
        L.append("### Puntualita': righe nate PRIMA del fischio (nessun risultato noto)")
        L.append("| origine | nate prima | nate DOPO | non verificabili |")
        L.append("|---|---|---|---|")
        for origine, conteggi in sorted(pu.get("per_origine", {}).items()):
            L.append(f"| {origine} | {conteggi.get('nate prima del fischio', 0)} | "
                     f"**{conteggi.get('nate DOPO il fischio', 0)}** | "
                     f"{conteggi.get('fischio o nascita non leggibili', 0)} |")
        for origine, voci in sorted((pu.get("in_ritardo") or {}).items()):
            L.append("")
            L.append(f"#### Nate DOPO il fischio — origine {origine} ({len(voci)})")
            for voce in voci:
                L.append(f"- {voce}")
        for origine, voci in sorted((pu.get("senza_fischio") or {}).items()):
            L.append("")
            L.append(f"#### Fischio/nascita non leggibili — origine {origine} ({len(voci)})")
            for voce in voci:
                L.append(f"- {voce}")
    return L


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", dest="json_out", default=None, help="scrive il dettaglio in JSON")
    ap.add_argument("--compatto", action="store_true",
                    help="riepilogo breve prefissato TABELLE|/PUNTUALE|/RITARDO| (referti con tetto di caratteri)")
    ap.add_argument("--escludi", default="top_mix",
                    help="origini di cui NON elencare le righe una per una (default: top_mix, "
                         "cioe' si elencano tutte le righe che NON sono Top Mix)")
    args = ap.parse_args(argv)

    righe, fonte = load_registry_readonly()
    if righe is None:
        print("::error title=composizione::Registro non leggibile (ne' remoto ne' locale)")
        return 2
    d = analizza(righe, origini_escluse=tuple(
        o.strip().lower() for o in args.escludi.split(",") if o.strip()))
    d["fonte"] = fonte
    # Le due misure che servono al riordino delle tabelle: cosa conterra' ciascuna
    # (solo Top Mix) e se le righe sono vere previsioni (nate prima del fischio).
    d["contenuto_tabelle"] = contenuto_tabelle(righe)
    d["puntualita"] = puntualita(righe)
    testo = "\n".join(_righe_testo(d)) + "\n"
    print(testo)
    if d["fonte"] not in ("upstash", "jsonbin"):
        print(f"::warning title=composizione::sto leggendo la copia '{d['fonte']}', "
              "NON il Registro vivo")
    if args.compatto:
        ct = d["contenuto_tabelle"]
        pu = d["puntualita"]
        print("TABELLE| " + " | ".join([
            "Drago a 2 Teste: " + str(ct["totale_per_motore"].get(MODEL_VARIANT_CURRENT, 0)),
            "Legacy: " + str(ct["totale_per_motore"].get(MODEL_VARIANT_LEGACY, 0)),
            "fuori dalle due tabelle: " + ", ".join(f"{k} {v}" for k, v in sorted(ct["fuori_dalle_tabelle"].items())),
        ]))
        for origine, conteggi in sorted(pu.get("per_origine", {}).items()):
            print(f"PUNTUALE| origine {origine} | prima del fischio: "
                  f"{conteggi.get('nate prima del fischio', 0)} | DOPO il fischio: "
                  f"{conteggi.get('nate DOPO il fischio', 0)} | non verificabili: "
                  f"{conteggi.get('fischio o nascita non leggibili', 0)}")
        for origine, voci in sorted((pu.get("in_ritardo") or {}).items()):
            for voce in voci:
                print(f"RITARDO| [{origine}] {voce[:300]}")
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        print(f"[composizione] json: {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
