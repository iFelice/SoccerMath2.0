"""verifica_click_live.py - Il replay rifa' davvero i click VERI? (campione, solo versione in prova)

Il referto del replay dichiara una "fedelta'" fra righe del Registro e righe
ricostruite, ma il confronto e' volutamente severo: le righe del Registro sono
state scritte **nell'istante in cui l'utente ha premuto il bottone** (con i dati
di allora e la selezione della "prossima giornata" di allora), mentre il replay
ricostruisce a **kickoff - 1 s**. Se i due istanti cadono in giorni diversi, il
dato e' diverso e i numeri DEVONO differire: non e' un difetto del replay.

Questa verifica toglie il dubbio alla radice: per un campione di righe del
Registro ricostruisce il click **all'istante del loro salvataggio** (campo
``salvato_il``, ora italiana) e confronta mercato e probabilita' con quelli
scritti davvero. Se il motore e la regola sono quelli giusti, il numero torna;
se non torna, la differenza e' del metodo e va spiegata.

Cosa entra nel campione, e cosa no
----------------------------------
* Solo le righe scritte dalla versione del selettore IN PROVA
  (``prediction_registry.SELECTOR_VERSION_CURRENT``). Una riga di una versione
  precedente e' l'uscita di un selettore diverso da quello che il replay rifa:
  non e' verificabile con il codice attuale. Viene contata come NON VERIFICABILE,
  per versione, nel referto.
* Il motore "di allora" e' quello in vigore quando la riga e' stata SALVATA, non
  quello della partita (vedi ``variante_da_confrontare``).

Esiti (ultima riga stampata: ``[verifica] esito: ...``)
-------------------------------------------------------
* 0 righe della versione in prova: ``verifica rimandata, 0 righe v2``. Nessun
  campione, nessuna fixture scaricata, exit 0: la verifica non ha materiale.
* righe della versione in prova e almeno una coincide: ``ok``, exit 0.
* righe della versione in prova e nessuna coincide: ``fallita``, exit 1.

Sola lettura: legge il Registro, non scrive nulla.

Uso:
    python audit/verifica_click_live.py --from 2026-08-30 --to 2026-09-20 \\
        --per-variante 3 --out audit/results/verifica_click_live.md
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOCCER = os.path.join(ROOT, "SoccerMath")
if SOCCER not in sys.path:
    sys.path.insert(0, SOCCER)

import replay_legacy_topmix as replay  # noqa: E402
import registry_coverage_check as check  # noqa: E402
from prediction_registry import (  # noqa: E402
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_LEGACY,
    MODEL_VARIANT_LABELS,
    SELECTOR_VERSION_CURRENT,
    model_variant_read,
    selector_version_of,
)
from registry_coverage import top_mix_rows  # noqa: E402

ITALY = None  # riempito in main() da app.ITALY_TZ

ESITO_RIMANDATA = "verifica rimandata, 0 righe v2"
ESITO_OK = "ok"
ESITO_FALLITA = "fallita"


def istante_del_salvataggio(riga: Dict[str, Any]) -> Optional[datetime]:
    """Istante UTC in cui la riga fu salvata: dal campo ``salvato_il`` italiano."""
    testo = str(riga.get("salvato_il") or "").strip()
    if not testo:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            d = datetime.strptime(testo, fmt)
        except ValueError:
            continue
        if fmt.endswith("Z"):
            return d.replace(tzinfo=timezone.utc)
        return d.replace(tzinfo=ITALY).astimezone(timezone.utc) if ITALY else d.replace(tzinfo=timezone.utc)
    return None


def variante_da_confrontare(riga: Dict[str, Any]) -> str:
    """Motore che ha prodotto la riga: quello in vigore quando e' stata SALVATA.

    Usa la stessa regola di lettura del Registro (``model_variant_read``): il
    campo esplicito vince; senza campo, ``legacy`` se la riga e' nata prima del
    merge di PR#24 (18/09/2026 21:51 UTC), ``current`` dopo.

    NON si guarda il giorno della partita. Errore corretto: prima si usava
    ``_prima_di_pr24`` (giorno del kickoff). Milan-Lecce, salvata il 15/09 su una
    partita del 20/09, veniva confrontata con l'Attuale, mentre l'uscita salvata
    era quella del motore vecchio (legacy: 64,5%, riprodotta esattamente).
    """
    return model_variant_read(riga)


def verifica_riga(riga: Dict[str, Any], fixtures: Dict[str, List[Any]], *,
                  snapshot_cache: Optional[str]) -> Dict[str, Any]:
    lega = riga.get("campionato")
    istante = istante_del_salvataggio(riga)
    target = next((f for f in fixtures.get(lega, [])
                   if str(f.match_id) == str(riga.get("match_id"))), None)
    if istante is None or target is None:
        return {"riga": riga, "esito": "non ricostruibile",
                "motivo": ("senza salvato_il" if istante is None
                           else f"match_id {riga.get('match_id')} assente fra le fixture: "
                                f"gli id del Registro sono quelli dell'API, non i sintetici dei CSV")}
    variante = variante_da_confrontare(riga)
    click = replay.simulate_click(istante, fixtures, targets=[target], leagues=[lega],
                                  snapshot_cache=snapshot_cache)
    mia = next((r for r in click.rows.get(variante, [])
                if str(r.get("match_id")) == str(riga.get("match_id"))), None)
    coincide = bool(mia) and mia.get("mercato_standard") == riga.get("mercato_standard") \
        and mia.get("prob_val") == riga.get("prob_sicuro")
    return {"riga": riga, "esito": "coincide" if coincide else "differisce",
            "variante": variante, "istante": istante, "snapshot": click.snapshot_sha,
            "salvato_il": riga.get("salvato_il"),
            "registro_mercato": riga.get("mercato_standard"), "registro_prob": riga.get("prob_sicuro"),
            "replay_mercato": mia.get("mercato_standard") if mia else None,
            "replay_prob": mia.get("prob_val") if mia else None,
            "note": ("la riga non e' stata riselezionata a quell'istante: la partita era fuori dal "
                     "pool della prossima giornata, o sotto soglia/veto in quella ricostruzione")
                    if mia is None else ""}


def _chiave_cronologica(riga: Dict[str, Any]):
    """Ordine cronologico vero (non lessicografico su dd/mm/yyyy): senza istante, in fondo."""
    istante = istante_del_salvataggio(riga)
    return (istante is None, istante or datetime.min.replace(tzinfo=timezone.utc))


def main(argv: Optional[List[str]] = None) -> int:
    global ITALY
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from", dest="day_from", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                    default=None)
    ap.add_argument("--to", dest="day_to", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                    default=None)
    ap.add_argument("--per-variante", type=int, default=3,
                    help="quante righe v2 verificare per variante (attuale, legacy), le piu' vecchie")
    ap.add_argument("--fixtures", choices=("api", "csv"), default="api",
                    help="sorgente delle fixture: api = football-data.org (stessi match_id del Registro, "
                         "default), csv = offline (gli id sintetici dei CSV NON coincidono con quelli scritti "
                         "dall'app: serve solo per le prove in locale)")
    ap.add_argument("--snapshot-cache", default=None, metavar="DIR")
    ap.add_argument("--out", default=None, metavar="FILE")
    args = ap.parse_args(argv)

    import app  # noqa: F401  (definisce ITALY_TZ e le funzioni usate dal replay)
    ITALY = app.ITALY_TZ

    righe, fonte = check.load_registry_readonly()
    # ``top_mix_rows`` e' l'unico filtro "Top Mix nel periodo" del progetto: qui
    # si usa quello, cosi' periodo e copertura non possono divergere.
    top = top_mix_rows(righe, args.day_from, args.day_to)
    in_prova = [r for r in top if selector_version_of(r) == SELECTOR_VERSION_CURRENT]
    non_verificabili = Counter(selector_version_of(r) or "(senza versione)"
                               for r in top if selector_version_of(r) != SELECTOR_VERSION_CURRENT)

    gruppi: Dict[str, List[Dict[str, Any]]] = {MODEL_VARIANT_CURRENT: [], MODEL_VARIANT_LEGACY: []}
    for r in in_prova:
        gruppi.setdefault(variante_da_confrontare(r), []).append(r)
    campione: List[Dict[str, Any]] = []
    for variante in sorted(gruppi):
        campione.extend(sorted(gruppi[variante], key=_chiave_cronologica)[:max(0, args.per_variante)])

    leghe = sorted({r.get("campionato") for r in campione if r.get("campionato")})
    fixtures: Dict[str, List[Any]] = {}
    if campione and args.fixtures == "api":
        from config import FOOTBALL_DATA_API_KEY
        fixtures = replay.fixtures_from_api(FOOTBALL_DATA_API_KEY, leghe)
    elif campione:
        fixtures = replay.fixtures_from_csv_and_archive(leghe)
    risultati = [verifica_riga(r, fixtures, snapshot_cache=args.snapshot_cache) for r in campione]

    n_ok = sum(1 for x in risultati if x["esito"] == "coincide")
    if not in_prova:
        esito, rc = ESITO_RIMANDATA, 0
    elif not campione:
        esito, rc = "verifica rimandata: campione vuoto (--per-variante 0)", 0
    elif n_ok > 0:
        esito, rc = f"{ESITO_OK} ({n_ok}/{len(risultati)} righe v2 coincidono)", 0
    else:
        esito, rc = f"{ESITO_FALLITA} (nessuna delle {len(risultati)} righe v2 verificate coincide)", 1

    L = ["# Il replay rifa' i click veri? (campione: solo la versione del selettore in prova)", "",
         f"**Esito verifica: {esito}**", "",
         f"Registro: {fonte} · righe Top Mix nel periodo: {len(top)} · "
         f"versione in prova `{SELECTOR_VERSION_CURRENT}`: {len(in_prova)} · "
         f"campione verificato: {len(risultati)}", ""]
    if non_verificabili:
        L.append("NON VERIFICABILI (scritte da una versione del selettore diversa da quella in prova):")
        for versione, n in sorted(non_verificabili.items()):
            L.append(f"- `{versione}`: {n} righe")
        L.append(f"- totale NON VERIFICABILI: {sum(non_verificabili.values())}")
        L.append("")
    if risultati:
        L.append("| riga del Registro | salvata il | motore di allora | nel Registro | ricostruzione | coincide |")
        L.append("|---|---|---|---|---|---|")
    for x in risultati:
        r = x["riga"]
        etichetta = (MODEL_VARIANT_LABELS.get(x.get("variante"), x.get("variante"))
                     if x["esito"] != "non ricostruibile" else "-")
        L.append(f"| {r.get('home')} - {r.get('away')} ({r.get('campionato')}) | {r.get('salvato_il')} | "
                 f"{etichetta} | {r.get('mercato_standard')} {r.get('prob_sicuro')}% | "
                 f"{x.get('replay_mercato')} {x.get('replay_prob')}% "
                 f"(snapshot {x.get('snapshot')}) | {x['esito']} |")
    L.append("")
    L.append(f"**{n_ok}/{len(risultati)} coincidono** ricostruendo il click all'istante del salvataggio.")
    for x in risultati:
        if x.get("note"):
            r = x["riga"]
            L.append(f"- nota: {r.get('home')} - {r.get('away')} — {x['note']}")
    # L'ultima riga e' l'esito: e' quella che finisce nel riepilogo del job (e nel referto).
    L.append(f"[verifica] esito: {esito}")
    testo = "\n".join(L) + "\n"
    print(testo, flush=True)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(testo)
        print(f"[verifica] referto: {args.out}")
    if rc:
        print("[verifica] il metodo di ricostruzione non riproduce i click veri (righe v2 presenti, nessuna coincide)",
              file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
