"""diagnose_scarti_model_variant.py - Perche' una partita la copre un modello solo.

Risponde alla domanda della commessa "Replay simmetrico": le partite coperte da
un solo modello sono un BUCO del replay o una decisione del selettore?

Metodo (misurato, non ipotizzato). Per ogni partita segnalata dalla copertura:

1. si esegue un click VERO (``replay.simulate_click``) all'istante kickoff - 1 s,
   lo stesso istante dei replay: nessuna scorciatoia, nessun ricalcolo a mano;
2. si intercetta ``app.seleziona_riga_top_mix`` mentre gira il click, cosi' i
   numeri che si leggono sono ESATTAMENTE quelli che il selettore ha visto
   (Poisson a due teste ed Elo di ciascun motore). Non c'e' una seconda copia
   della formula: se cambia il selettore, cambia anche questa diagnosi;
3. per ogni variante si applica ``app.riga_top_mix_shadow`` (funzione pura di
   produzione, gia' testata) agli STESSI ingressi intercettati: dice quant'e'
   la confidence reale, quale soglia valeva (0,55 1X2 / 0,60 Totali) e se il
   veto di disaccordo |P - E| >= 0,25 avrebbe scartato;
4. si confronta con le righe che il click ha davvero prodotto: riga presente =
   selezionata; riga assente = scartata, e il motivo e' quello che il punto 3
   nomina.

Uso:
    python audit/diagnose_scarti_model_variant.py \
        --dump audit/results/replay_sym_offline/registro_offline_fuso.json \
        --coverage audit/results/replay_sym_offline/coverage_unione.json \
        --snapshot-cache /tmp/sm_snap_cache \
        --out audit/results/replay_sym_offline/diagnosi_scarti.md

NON scrive nel Registro: e' sola lettura, come il controllo di copertura.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOCCER = os.path.join(ROOT, "SoccerMath")
for p in (SOCCER,):
    if p not in sys.path:
        sys.path.insert(0, p)

import app  # noqa: E402
import replay_legacy_topmix as replay  # noqa: E402
from config import LEAGUES_CONFIG  # noqa: E402
from prediction_registry import (  # noqa: E402
    MODEL_VARIANT_CURRENT,
    MODEL_VARIANT_LEGACY,
    MODEL_VARIANT_LABELS,
)

ISO_Z = "%Y-%m-%dT%H:%M:%SZ"


def _kickoff(riga: Dict[str, Any]) -> datetime:
    """Istante del kickoff della riga del Registro.

    ``kickoff_utc`` e' la fonte autorevole (c'e' in tutte le righe scritte dal
    Top Mix a due motori e in quelle del replay). Le righe STORICHE, scritte
    quando il campo non esisteva, hanno solo ``data`` = 'gg/mm/aaaa HH:MM'
    nell'ora italiana: si deduce da li' e il referto lo dichiara
    (``kickoff_dedotto``), perche' e' una ricostruzione, non un dato.
    """
    ko = riga.get("kickoff_utc")
    if ko:
        d = datetime.fromisoformat(str(ko).replace("Z", "+00:00"))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
    from prediction_registry import parse_datetime
    d = parse_datetime(riga.get("data"))
    if d is None:
        raise SystemExit(f"riga senza kickoff_utc ne' data utilizzabile: {riga}")
    return d.astimezone(timezone.utc)


def intercetta_selettore(chiamate: List[Dict[str, Any]]):
    """Sostituisce ``app.seleziona_riga_top_mix`` con un wrapper che registra gli
    ingressi e delega tutto il resto alla funzione vera."""
    originale = app.seleziona_riga_top_mix

    def wrapper(m, elo_probs=None, elo_disponibile=True, home=None, away=None):
        riga = originale(m, elo_probs, elo_disponibile, home, away)
        chiamate.append({"poisson": m, "elo_probs": elo_probs, "elo_disponibile": elo_disponibile,
                         "home": home, "away": away, "riga": riga})
        return riga

    return originale, wrapper


def _scelta_riga(righe: List[Dict[str, Any]], match_id: Any) -> Optional[Dict[str, Any]]:
    for r in righe:
        if str(r.get("match_id")) == str(match_id):
            return r
    return None


def diagnosi_partita(riga: Dict[str, Any], fixtures: Dict[str, List[Any]], *,
                     snapshot_cache: Optional[str]) -> Dict[str, Any]:
    """Un click vero sulla partita, poi la lettura di cosa ha visto il selettore."""
    lega = riga["campionato"]
    ko = _kickoff(riga)
    dedotto = not bool(str(riga.get("kickoff_utc") or "").strip())
    istante = ko - timedelta(seconds=1)
    target = next((f for f in fixtures.get(lega, []) if str(f.match_id) == str(riga.get("match_id"))), None)
    if target is None:
        raise SystemExit(f"partita non trovata nelle fixture: {riga}")
    chiamate: List[Dict[str, Any]] = []
    originale, wrapper = intercetta_selettore(chiamate)
    app.seleziona_riga_top_mix = wrapper
    try:
        click = replay.simulate_click(istante, fixtures, targets=[target], leagues=[lega],
                                      snapshot_cache=snapshot_cache)
    finally:
        app.seleziona_riga_top_mix = originale
    if not click.leak.ok or not click.leak.snapshot_covers_season:
        raise SystemExit(f"click non scrivibile su {riga['partita']}: {click.leak.dettagli}")

    h_disp, a_disp = app.display_name(target.home), app.display_name(target.away)
    coppia = [c for c in chiamate if c["home"] == h_disp and c["away"] == a_disp]
    if len(coppia) != 2:
        raise SystemExit(f"attese 2 chiamate al selettore per {riga['partita']}, trovate {len(coppia)}")
    # L'ordine e' quello del codice di produzione: prima il modello attuale,
    # poi il legacy (stessa partita, stesso Poisson, Elo diverso).
    esiti: Dict[str, Any] = {}
    for variante, chiamata in zip((MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY), coppia):
        ombra = app.riga_top_mix_shadow(chiamata["poisson"], chiamata["elo_probs"],
                                        chiamata["elo_disponibile"], h_disp, a_disp)
        scelta = _scelta_riga(click.rows.get(variante, []), target.match_id)
        if scelta is not None:
            # Controprova del metodo: dove il selettore NON ha scartato, la
            # matematica ombra deve dare gli stessi numeri della riga vera.
            # Se non li da', il motivo attribuito alla variante assente non e'
            # affidabile e la diagnosi deve fallire invece di stampare numeri
            # che sembrano buoni.
            if (scelta.get("mercato_standard") != ombra["mercato_standard"]
                    or scelta.get("prob_val") != round(ombra["prob"] * 100, 1)):
                raise SystemExit(
                    f"controprova fallita su {riga['partita']} ({variante}): riga "
                    f"{scelta.get('mercato_standard')} {scelta.get('prob_val')}% vs ombra "
                    f"{ombra['mercato_standard']} {round(ombra['prob'] * 100, 1)}%")
            motivo = "selezionata"
        elif ombra["gate_avrebbe_scartato"]:
            motivo = "veto (disaccordo >= 0,25)"
        elif ombra["prob"] < ombra["min_conf"]:
            motivo = f"sotto soglia ({ombra['prob']:.3f} < {ombra['min_conf']:.2f})"
        else:
            motivo = "scartata (motivo non attribuito: verificare)"
        esiti[variante] = {
            "motivo": motivo,
            "mercato": scelta.get("mercato_standard") if scelta else ombra["mercato_standard"],
            "confidence": scelta.get("prob_val") if scelta else round(ombra["prob"] * 100, 1),
            "poisson": scelta.get("poisson") if scelta else ombra["poisson"],
            "elo": scelta.get("elo") if scelta else ombra["elo"],
            "soglia": round(ombra["min_conf"] * 100, 1),
            "disaccordo": round(ombra["disaccordo"] * 100, 1),
            "elo_disponibile": ombra["elo_disponibile"],
        }
    return {"partita": riga["partita"], "campionato": lega, "kickoff": ko.strftime(ISO_Z),
            "match_id": riga.get("match_id"), "snapshot_sha": click.snapshot_sha,
            # 'kickoff_dedotto': l'istante non veniva dal campo kickoff_utc ma dalla
            # data italiana. Va nel referto: e' una ricostruzione, non un dato.
            "kickoff_dedotto": dedotto,
            "prodotta_da": riga.get("mercato"), "esiti": esiti}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dump", required=True, help="copia fusa del registro (formato predictions.json)")
    ap.add_argument("--coverage", required=True, help="JSON della copertura (da registry_coverage_check)")
    ap.add_argument("--snapshot-cache", default=None, metavar="DIR")
    ap.add_argument("--ref", default=None, help="ref git di main (default: origin/main, poi main)")
    ap.add_argument("--fixtures", choices=("csv", "api"), default="csv",
                    help="sorgente delle fixture. 'csv' (default) = archivi del repo, con id "
                         "SINTETICI; le righe del Registro vivo hanno gli id dell'API, quindi "
                         "per misurarle serve 'api'")
    ap.add_argument("--out", default=None, metavar="FILE", help="referto markdown")
    args = ap.parse_args(argv)

    with open(args.coverage, encoding="utf-8") as f:
        cov = json.load(f)
    tutte: List[Tuple[str, Dict[str, Any]]] = []
    for variante in (MODEL_VARIANT_CURRENT, MODEL_VARIANT_LEGACY):
        for r in cov["solo"].get(variante, []):
            tutte.append((variante, r))
    if not tutte:
        print("Nessuna partita coperta da un solo modello: niente da diagnosticare.")
        return 0

    leghe = sorted({r["campionato"] for _, r in tutte})
    # Le righe del Registro vivo portano i match_id dell'API: con le fixture dei
    # CSV (id sintetici) nessuna partita verrebbe trovata e la diagnosi direbbe
    # "non diagnosticabile" su tutto, senza misurare niente.
    if args.fixtures == "api":
        from config import FOOTBALL_DATA_API_KEY
        fixtures = replay.fixtures_from_api(FOOTBALL_DATA_API_KEY, leghe)
    else:
        fixtures = replay.fixtures_from_csv_and_archive(leghe)
    dettagli = []
    non_diagnosticabili: List[Tuple[Dict[str, Any], str]] = []
    for variante, r in sorted(tutte, key=lambda x: (x[1].get("kickoff_utc") or "", x[1]["partita"])):
        # Una riga che non si riesce a rigiocare (kickoff assente, partita non
        # nelle fixture, controprova fallita) NON deve fermare la diagnosi delle
        # altre: viene dichiarata a parte, con il motivo. Il silenzio no.
        try:
            d = diagnosi_partita(r, fixtures, snapshot_cache=args.snapshot_cache)
        except (SystemExit, Exception) as e:  # SystemExit: gli errori "parlanti" del modulo
            motivo = str(getattr(e, "code", None) or e)
            non_diagnosticabili.append((r, motivo))
            print(f"{r['partita']} ({r['campionato']}): NON diagnosticabile -> {motivo}")
            continue
        d["variante_presente"] = variante
        d["variante_assente"] = MODEL_VARIANT_LEGACY if variante == MODEL_VARIANT_CURRENT else MODEL_VARIANT_CURRENT
        dettagli.append(d)
        assente = d["esiti"][d["variante_assente"]]
        print(f"{d['partita']} ({d['campionato']}, {d['kickoff']}): "
              f"{MODEL_VARIANT_LABELS[d['variante_presente']]} c'e' ({d['prodotta_da']} "
              f"{d['esiti'][d['variante_presente']]['confidence']}%), "
              f"{MODEL_VARIANT_LABELS[d['variante_assente']]} assente -> {assente['motivo']}")

    L = ["# Perche' le partite coperte da un solo modello non sono un buco", "",
         "Ogni riga nasce da un click VERO all'istante kickoff - 1 s: gli ingressi del selettore",
         "sono quelli intercettati mentre il click girava, non un ricalcolo a parte.",
         ""]
    L.append("| partita | campione | modello presente | modello assente | motivo dell'assenza |")
    L.append("|---|---|---|---|---|")
    for d in dettagli:
        pres, ass = d["variante_presente"], d["variante_assente"]
        e_p, e_a = d["esiti"][pres], d["esiti"][ass]
        ded = " (kickoff dedotto dalla data italiana)" if d.get("kickoff_dedotto") else ""
        L.append(f"| {d['partita']} ({d['campionato']}, {d['kickoff']}{ded}) | {d['match_id']} | "
                 f"{MODEL_VARIANT_LABELS[pres]}: {d['prodotta_da']} {e_p['confidence']}% "
                 f"(soglia {e_p['soglia']}%, disaccordo {e_p['disaccordo']}%) | "
                 f"{MODEL_VARIANT_LABELS[ass]}: {e_a['mercato']} {e_a['confidence']}% | "
                 f"**{e_a['motivo']}** (P {e_a['poisson']}%, E {e_a['elo']}%, "
                 f"disaccordo {e_a['disaccordo']}%, soglia {e_a['soglia']}%) |")
    L.append("")
    motivi = {}
    for d in dettagli:
        m = d["esiti"][d["variante_assente"]]["motivo"].split(" (")[0]
        motivi[m] = motivi.get(m, 0) + 1
    L.append("Riepilogo: " + " · ".join(f"{k}: {v}" for k, v in sorted(motivi.items())) + ".")
    L.append("")
    if non_diagnosticabili:
        L.append(f"### Non diagnosticabili: {len(non_diagnosticabili)} su {len(tutte)}")
        L.append("")
        L.append("| partita | campione | motivo |")
        L.append("|---|---|---|")
        for r, motivo in non_diagnosticabili:
            L.append(f"| {r['partita']} | {r['campionato']} | {motivo[:300]} |")
        L.append("")
        L.append("Queste righe non sono state rigiocate: il motivo della loro copertura a un solo")
        L.append("modello resta NON misurato e va trattato come tale (non come un'assenza spiegata).")
        L.append("")
    L.append("Conseguenza: nessuna riga viene inventata per far coincidere i campioni. Le soglie")
    L.append("(0,55 1X2 / 0,60 Totali) e il veto restano quelli di produzione, e per il modello")
    L.append("assente il Registro non ha nulla da scrivere perche' quel modello, su quella partita,")
    L.append("non ha espresso una scelta.")
    testo = "\n".join(L) + "\n"
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(testo)
        print(f"[diagnosi] referto: {args.out}")
    print(f"NON DIAGNOSTICABILI: {len(non_diagnosticabili)} su {len(tutte)}")
    # 3 = diagnosi fatta ma con righe dichiarate non misurate (il chiamante
    # decide se e' un guasto o una dichiarazione: la causa resta parziale).
    return 3 if non_diagnosticabili else 0


if __name__ == "__main__":
    sys.exit(main())
