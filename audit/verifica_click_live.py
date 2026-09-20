"""verifica_click_live.py - Il replay rifa' davvero i click VERI? (campione)

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

Prima di PR#24 il motore live era quello VECCHIO: le righe di quel periodo si
confrontano con la riga ricostruita del modello LEGACY (anche quando il campo
variante e' assente e vale "current" per i record storici). Dopo PR#24 si
confrontano con la variante dichiarata nella riga.

Sola lettura: legge il Registro, non scrive nulla.

Uso:
    python audit/verifica_click_live.py --from 2026-08-30 --to 2026-09-20 \\
        --per-variante 3 --out audit/results/verifica_click_live.md
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

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
    model_variant_of,
)
from registry_coverage import top_mix_rows  # noqa: E402

ITALY = None  # riempito in main() da app.ITALY_TZ


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
    """Quale riga ricostruita si confronta con questa riga del Registro.

    Prima di PR#24 il motore live era il VECCHIO (legacy), anche se la riga non
    porta il campo variante; dopo, la variante della riga e' quella vera.
    """
    if replay._prima_di_pr24(riga):
        return MODEL_VARIANT_LEGACY
    return model_variant_of(riga)


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


def main(argv: Optional[List[str]] = None) -> int:
    global ITALY
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from", dest="day_from", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                    default=None)
    ap.add_argument("--to", dest="day_to", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                    default=None)
    ap.add_argument("--per-variante", type=int, default=3,
                    help="quante righe verificare per periodo (pre e post PR#24)")
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
    periodo = top
    pre = [r for r in periodo if replay._prima_di_pr24(r)]
    post = [r for r in periodo if not replay._prima_di_pr24(r)]
    campione: List[Dict[str, Any]] = []
    for gruppo in (pre, post):
        scelte = sorted(gruppo, key=lambda r: str(r.get("salvato_il") or ""))[:max(0, args.per_variante)]
        campione.extend(scelte)

    leghe = sorted({r.get("campionato") for r in campione if r.get("campionato")})
    fixtures: Dict[str, List[Any]] = {}
    if campione and args.fixtures == "api":
        from config import FOOTBALL_DATA_API_KEY
        fixtures = replay.fixtures_from_api(FOOTBALL_DATA_API_KEY, leghe)
    elif campione:
        fixtures = replay.fixtures_from_csv_and_archive(leghe)
    risultati = [verifica_riga(r, fixtures, snapshot_cache=args.snapshot_cache) for r in campione]

    n_ok = sum(1 for x in risultati if x["esito"] == "coincide")
    L = ["# Il replay rifa' i click veri? (campione, ricostruzione all'istante del salvataggio)", "",
         f"Registro: {fonte} · righe Top Mix nel periodo: {len(periodo)} "
         f"(prima di PR#24: {len(pre)}, dopo: {len(post)}) · campione verificato: {len(risultati)}", ""]
    L.append("| riga del Registro | salvata il | motore di allora | ricostruzione | coincide |")
    L.append("|---|---|---|---|---|")
    for x in risultati:
        r = x["riga"]
        etichetta = (MODEL_VARIANT_LABELS.get(x.get("variante"), x.get("variante"))
                     if x["esito"] != "non ricostruibile" else "-")
        L.append(f"| {r.get('home')} - {r.get('away')} ({r.get('campionato')}) | {r.get('salvato_il')} | "
                 f"{etichetta} | {x.get('replay_mercato')} {x.get('replay_prob')}% "
                 f"(snapshot {x.get('snapshot')}) | {x['esito']} |")
    L.append("")
    L.append(f"**{n_ok}/{len(risultati)} coincidono** ricostruendo il click all'istante del salvataggio.")
    for x in risultati:
        if x.get("note"):
            r = x["riga"]
            L.append(f"- nota: {r.get('home')} - {r.get('away')} — {x['note']}")
    testo = "\n".join(L) + "\n"
    print(testo)
    non_ric = sum(1 for x in risultati if x["esito"] == "non ricostruibile")
    if risultati and non_ric == len(risultati):
        print(f"[verifica] NESSUNA riga ricostruibile: {risultati[0].get('motivo')}", file=sys.stderr)
        if args.out:
            os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(testo)
        return 1
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(testo)
        print(f"[verifica] referto: {args.out}")
    if risultati and n_ok == 0 and non_ric < len(risultati):
        print("[verifica] NESSUNA coincidenza: il metodo di ricostruzione non riproduce i click veri.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
