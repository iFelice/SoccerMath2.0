#!/usr/bin/env python3
"""replay_topmix_mercato.py — replay OFFLINE del selettore ``topmix_mercato_v3``.

DOMANDA (punto 8 della commessa "quote live nel Top Mix"). Le scelte prodotte dal
selettore di mercato in produzione (``app.seleziona_riga_top_mix_mercato``,
de-vig proporzionale in ``market_odds``) riproducono i numeri della PR #49?

    PR #49 (audit/results/onex2_market_test.md §4 e §4d, campione pooled OOS
    2024/25 + 2025/26, quote B365 pre-chiusura de-vig proporzionale):

      scelte del mercato                        1302   hit 67,5%
      scelte del modello CON accordo            1144   hit 68,2%
      scelte del modello SENZA accordo           335   hit 43,6%

COME
----
* i DATI storici sono quelli della PR #49: ``onex2_market_test.build_frame()``
  (Poisson di produzione intercettato, Elo walker fedele, blend
  ``app.blend_elo_into_1x2``, quote B365H/D/A dei CSV in
  ``SoccerMath/database``). Nessuna formula viene riscritta;
* le PROBABILITA' DI MERCATO sono ricalcolate con il de-vig di PRODUZIONE
  (``market_odds.devig_proporzionale``), e la loro identita' con le colonne
  ``pre*`` della PR #49 e' verificata riga per riga e riportata;
* la SCELTA e' fatta dalla funzione di produzione
  ``app.seleziona_riga_top_mix_mercato`` (la stessa che gira nell'app): argmax
  delle probabilita' di mercato, ammissione a 0,55, segnale "d'accordo"
  (stesso esito ed entrambi >= 0,55);
* le differenze rispetto alla PR #49 vengono RIPORTATE, non corrette: se un
  numero non torna, il referto lo dice e il codice di uscita e' 1
  (``--tolleranza`` controlla quanto scarto e' ammesso prima di fallire).

NESSUNA RETE, NESSUNA SCRITTURA nel Registro, nessun commit.

Output
  * ``audit/results/replay_topmix_mercato.md``  referto (committato);
  * ``audit/output/replay_topmix_mercato.json`` payload (non versionato);
  * ``audit/output/replay_topmix_mercato_frame.csv`` cache del frame
    (non versionata: ``--no-cache`` la ignora e la ricostruisce).

Uso: ``python audit/replay_topmix_mercato.py [--no-cache] [--reps 0]``
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

OUT_DIR = os.path.join(_AUDIT_DIR, "output")
REPORT_PATH = os.path.join(_AUDIT_DIR, "results", "replay_topmix_mercato.md")
CACHE_PATH = os.path.join(OUT_DIR, "replay_topmix_mercato_frame.csv")
JSON_PATH = os.path.join(OUT_DIR, "replay_topmix_mercato.json")

# Numeri della PR #49 da riprodurre (audit/results/onex2_market_test.md).
RIFERIMENTO_PR49 = OrderedDict([
    ("scelte_mercato", {"n": 1302, "hit": 0.6751, "fonte": "§4, pooled OOS, mercato B365 pre (prop.)"}),
    ("accordo", {"n": 1144, "hit": 0.6818, "fonte": "§4d tabella B, scelte del modello CON consenso"}),
    ("senza_accordo", {"n": 335, "hit": 0.4358, "fonte": "§4d tabella B, scelte del modello SENZA consenso"}),
])

# Colonne del frame che servono (il frame completo ha ~80 colonne).
COLONNE_CACHE = ["league", "season", "date", "home", "away", "y_code",
                 "m0", "m1", "m2", "pre0", "pre1", "pre2", "pre_ok",
                 "B365H", "B365D", "B365A", "has_model"]

ESITO_DI_CODICE = {0: "1", 1: "X", 2: "2"}


def _importa_produzione():
    """Import tardivo: silenzia il rumore di Streamlit come fa onex2_market_test."""
    import onex2_market_test as OMT          # noqa: E402
    import market_odds as MO                 # noqa: E402
    import app as prod_app                   # noqa: E402
    return OMT, MO, prod_app


def costruisci_frame(usare_cache: bool = True) -> pd.DataFrame:
    """Frame storico della PR #49 (cache CSV opzionale: e' la parte lenta)."""
    os.makedirs(OUT_DIR, exist_ok=True)
    if usare_cache and os.path.exists(CACHE_PATH):
        df = pd.read_csv(CACHE_PATH, low_memory=False)
        print(f"frame letto dalla cache: {CACHE_PATH} ({len(df)} righe)", flush=True)
        return df
    OMT, _MO, _app = _importa_produzione()
    t0 = time.time()
    print("costruzione del frame (Poisson di produzione + Elo walker + quote)...", flush=True)
    df, diag, _base = OMT.build_frame()
    print(f"frame costruito in {time.time() - t0:.0f} s ({len(df)} righe)", flush=True)
    df = df[[c for c in COLONNE_CACHE if c in df.columns]].copy()
    df.to_csv(CACHE_PATH, index=False)
    with open(os.path.join(OUT_DIR, "replay_topmix_mercato_diag.json"), "w",
              encoding="utf-8") as fh:
        json.dump(diag, fh, ensure_ascii=False, indent=1, default=str)
    return df


def campionatura(df: pd.DataFrame) -> pd.DataFrame:
    """Lo stesso campione della PR #49: 2024/25 + 2025/26, modello E quote B365 pre."""
    OMT, _MO, _app = _importa_produzione()
    m = df["season"].isin(OMT.EVAL_SEASONS) & df["has_model"].astype(bool) & df["pre_ok"].astype(bool)
    return df[m].reset_index(drop=True)


def applica_selettore(campione: pd.DataFrame):
    """Applica il selettore di PRODUZIONE riga per riga. Ritorna un DataFrame di righe."""
    _OMT, MO, prod_app = _importa_produzione()
    righe = []
    max_scarto_devig = 0.0
    for r in campione.itertuples(index=False):
        # de-vig di PRODUZIONE sulle quote grezze B365 pre-chiusura
        quote = (r.B365H, r.B365D, r.B365A)
        p = MO.devig_proporzionale(quote)
        if p is None:
            righe.append({"ammessa": False, "motivo": "terna non valida"})
            continue
        # verifica di identita' con le colonne de-vigate della PR #49
        max_scarto_devig = max(max_scarto_devig,
                               abs(p[0] - r.pre0), abs(p[1] - r.pre1), abs(p[2] - r.pre2))
        probs = {"1": p[0], "X": p[1], "2": p[2]}
        modello = {"1": r.m0, "X": r.m1, "2": r.m2}
        sel = prod_app.seleziona_riga_top_mix_mercato(
            probs, {"1": quote[0], "X": quote[1], "2": quote[2]},
            modello, fonte=MO.FONTE_PINNACLE, n_libri=1,
            home=r.home, away=r.away)
        esito_reale = ESITO_DI_CODICE[int(r.y_code)]
        argmax_modello = max(modello, key=lambda k: modello[k])
        righe.append({
            "league": r.league, "season": r.season, "date": str(r.date),
            "home": r.home, "away": r.away,
            "esito_reale": esito_reale,
            "ammessa": sel is not None,
            "esito": (sel or {}).get("esito"),
            "prob_mercato": (sel or {}).get("prob"),
            "quota": (sel or {}).get("quota"),
            "prob_modello": (sel or {}).get("prob_modello"),
            "accordo": bool((sel or {}).get("accordo")),
            "vincente": (sel is not None and sel["esito"] == esito_reale),
            # ricontrollo indipendente della regola di consenso della PR #49
            "consenso_pr49": bool(argmax_modello == max(probs, key=lambda k: probs[k])
                                  and modello[argmax_modello] >= MO.SOGLIA_ACCORDO
                                  and probs[max(probs, key=lambda k: probs[k])] >= MO.SOGLIA_ACCORDO),
            "scelta_modello_ammessa": bool(modello[argmax_modello] >= MO.SOGLIA_TOPMIX_MERCATO),
            "esito_modello": argmax_modello,
            "vincente_modello": argmax_modello == esito_reale,
        })
    return pd.DataFrame(righe), max_scarto_devig


def wilson(vinte: int, decise: int, z: float = 1.959963984540054):
    if decise <= 0:
        return (0.0, 1.0)
    p = vinte / decise
    den = 1.0 + z * z / decise
    centro = (p + z * z / (2.0 * decise)) / den
    semi = (z / den) * math.sqrt(p * (1.0 - p) / decise + z * z / (4.0 * decise * decise))
    return (max(0.0, centro - semi), min(1.0, centro + semi))


def riassunto(righe: pd.DataFrame):
    scelte = righe[righe["ammessa"]]
    n = len(scelte)
    vinte = int(scelte["vincente"].sum())
    # gruppo "d'accordo": le scelte del MODELLO ammesse con consenso di mercato
    # (definizione della PR #49 §4d tabella B)
    cons = righe[righe["scelta_modello_ammessa"] & righe["consenso_pr49"]]
    non_cons = righe[righe["scelta_modello_ammessa"] & ~righe["consenso_pr49"]]
    # e il sottoinsieme delle scelte di MERCATO che hanno anche l'accordo
    mkt_acc = scelte[scelte["accordo"]]
    mkt_no = scelte[~scelte["accordo"]]
    out = {
        "righe_campione": int(len(righe)),
        "scelte_mercato": {"n": n, "vinte": vinte,
                           "hit": (vinte / n if n else None),
                           "hit_ic": list(wilson(vinte, n))},
        "accordo": {"n": int(len(cons)), "vinte": int(cons["vincente_modello"].sum()),
                    "hit": (float(cons["vincente_modello"].mean()) if len(cons) else None),
                    "hit_ic": list(wilson(int(cons["vincente_modello"].sum()), len(cons)))},
        "senza_accordo": {"n": int(len(non_cons)),
                          "vinte": int(non_cons["vincente_modello"].sum()),
                          "hit": (float(non_cons["vincente_modello"].mean()) if len(non_cons) else None),
                          "hit_ic": list(wilson(int(non_cons["vincente_modello"].sum()), len(non_cons)))},
        "scelte_mercato_con_accordo": {"n": int(len(mkt_acc)),
                                       "vinte": int(mkt_acc["vincente"].sum()),
                                       "hit": (float(mkt_acc["vincente"].mean()) if len(mkt_acc) else None)},
        "scelte_mercato_senza_accordo": {"n": int(len(mkt_no)),
                                         "vinte": int(mkt_no["vincente"].sum()),
                                         "hit": (float(mkt_no["vincente"].mean()) if len(mkt_no) else None)},
    }
    return out


def confronta(riass: dict, tolleranza_n: int = 0, tolleranza_hit: float = 0.0005):
    """Differenze rispetto alla PR #49: riportate sempre, mai nascoste."""
    coppie = [("scelte_mercato", riass["scelte_mercato"]),
              ("accordo", riass["accordo"]),
              ("senza_accordo", riass["senza_accordo"])]
    righe = []
    tutte_ok = True
    for chiave, ottenuto in coppie:
        atteso = RIFERIMENTO_PR49[chiave]
        dn = ottenuto["n"] - atteso["n"]
        dh = (ottenuto["hit"] - atteso["hit"]) if ottenuto["hit"] is not None else None
        ok = abs(dn) <= tolleranza_n and (dh is not None and abs(dh) <= tolleranza_hit)
        tutte_ok = tutte_ok and ok
        righe.append({"voce": chiave, "fonte_pr49": atteso["fonte"],
                      "n_pr49": atteso["n"], "n_replay": ottenuto["n"], "delta_n": dn,
                      "hit_pr49": atteso["hit"], "hit_replay": ottenuto["hit"],
                      "delta_hit": dh, "coincide": ok})
    return righe, tutte_ok


def git_facts():
    def run(*cmd):
        try:
            return subprocess.run(cmd, cwd=_REPO_ROOT, capture_output=True, text=True,
                                  timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    return {"commit": run("git", "rev-parse", "--short", "HEAD"),
            "branch": run("git", "rev-parse", "--abbrev-ref", "HEAD")}


def scrivi_referto(payload: dict) -> str:
    r = payload["riassunto"]
    P = []
    P.append("# Replay offline del Top Mix di mercato (`topmix_mercato_v3`)\n")
    P.append(f"Generato da `audit/replay_topmix_mercato.py` il {payload['generato_il']} "
             f"(commit `{payload['git']['commit']}`, branch `{payload['git']['branch']}`). "
             f"Nessuna rete, nessuna scrittura nel Registro.\n")
    P.append("Comando: `python audit/replay_topmix_mercato.py`.\n")
    P.append("## 0. Cosa riproduce\n")
    P.append("| Elemento | Fonte |\n|---|---|")
    P.append("| Quote | CSV storici `SoccerMath/database/*_2024.csv` e `*_2025.csv`, colonne "
             "B365H/B365D/B365A (pre-chiusura, come nella PR #49) |")
    P.append("| De-vig | `market_odds.devig_proporzionale` (PRODUZIONE), verificato riga per "
             f"riga contro le colonne `pre*` della PR #49: scarto massimo "
             f"{payload['max_scarto_devig']:.2e} |")
    P.append("| Scelta | `app.seleziona_riga_top_mix_mercato` (PRODUZIONE): argmax delle "
             "probabilita' di mercato, ammissione a 0,55 |")
    P.append("| Segnale \"d'accordo\" | `market_odds.SOGLIA_ACCORDO` = 0,55, stesso esito "
             "(definizione PR #49 §4d) |")
    P.append("| Probabilita' del modello | colonne `m0/m1/m2` del frame PR #49 (blend 0,25 "
             "Poisson + 0,75 Elo walker) |")
    P.append(f"| Campione | {r['righe_campione']} righe (2024/25 + 2025/26, con modello e "
             "con terna B365 pre) |\n")

    P.append("## 1. Confronto con la PR #49\n")
    P.append("| Voce | Fonte PR #49 | n PR #49 | n replay | Δn | hit PR #49 | hit replay | Δhit | coincide |\n"
             "|---|---|---|---|---|---|---|---|---|")
    for riga in payload["confronto"]:
        P.append(f"| {riga['voce']} | {riga['fonte_pr49']} | {riga['n_pr49']} | "
                 f"{riga['n_replay']} | {riga['delta_n']:+d} | {riga['hit_pr49']:.4f} | "
                 f"{riga['hit_replay']:.4f} | {riga['delta_hit']:+.4f} | "
                 f"{'SÌ' if riga['coincide'] else 'NO'} |")
    P.append("")
    P.append(f"**Esito del confronto: {'PARITÀ' if payload['parita'] else 'DIFFERENZE PRESENTI'}** "
             f"(tolleranze dichiarate: Δn ≤ {payload['tolleranza_n']}, "
             f"|Δhit| ≤ {payload['tolleranza_hit']}).\n")
    if not payload["parita"]:
        P.append("Le differenze NON sono state corrette: sono riportate come sono.\n")

    P.append("## 2. Numeri del replay\n")
    P.append("| Gruppo | n | vinte | hit rate | IC 95% (Wilson) |\n|---|---|---|---|---|")
    for etichetta, chiave in (("Scelte del mercato (soglia 0,55)", "scelte_mercato"),
                              ("Scelte del modello CON accordo", "accordo"),
                              ("Scelte del modello SENZA accordo", "senza_accordo")):
        g = r[chiave]
        ic = g.get("hit_ic") or [None, None]
        P.append(f"| {etichetta} | {g['n']} | {g['vinte']} | "
                 f"{(g['hit'] if g['hit'] is not None else float('nan')):.4f} | "
                 f"[{ic[0]:.4f}; {ic[1]:.4f}] |")
    P.append("")
    P.append("Lettura delle scelte di MERCATO separate per accordo (informazione aggiuntiva, "
             "non fa parte del confronto con la PR #49):\n")
    P.append("| Gruppo | n | vinte | hit rate |\n|---|---|---|---|")
    for etichetta, chiave in (("Scelte del mercato CON accordo del modello", "scelte_mercato_con_accordo"),
                              ("Scelte del mercato SENZA accordo", "scelte_mercato_senza_accordo")):
        g = r[chiave]
        P.append(f"| {etichetta} | {g['n']} | {g['vinte']} | "
                 f"{(g['hit'] if g['hit'] is not None else float('nan')):.4f} |")
    P.append("")

    P.append("## 3. Limiti dichiarati\n")
    for l in payload["limiti"]:
        P.append(f"- {l}")
    P.append("")
    return "\n".join(P)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-cache", action="store_true", help="ricostruisce il frame (lento)")
    ap.add_argument("--tolleranza-n", type=int, default=0,
                    help="scarto massimo ammesso sul numero di scelte (default 0)")
    ap.add_argument("--tolleranza-hit", type=float, default=0.0005,
                    help="scarto massimo ammesso sull'hit rate (default 0.0005)")
    ap.add_argument("--json", default=JSON_PATH)
    ap.add_argument("--report", default=REPORT_PATH)
    ap.add_argument("--righe", default=os.path.join(OUT_DIR, "replay_topmix_mercato_rows.csv"))
    args = ap.parse_args(argv)

    os.makedirs(OUT_DIR, exist_ok=True)
    frame = costruisci_frame(usare_cache=not args.no_cache)
    campione = campionatura(frame)
    righe, max_scarto = applica_selettore(campione)
    riass = riassunto(righe)
    confronto, parita = confronta(riass, args.tolleranza_n, args.tolleranza_hit)

    payload = {
        "generato_il": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git": git_facts(),
        "riferimento": "audit/results/onex2_market_test.md (PR #49) §4 e §4d",
        "max_scarto_devig": float(max_scarto),
        "tolleranza_n": args.tolleranza_n,
        "tolleranza_hit": args.tolleranza_hit,
        "riassunto": riass,
        "confronto": confronto,
        "parita": bool(parita),
        "limiti": [
            "Le quote sono quelle dei CSV storici (B365 pre-chiusura), NON quelle dal vivo di "
            "The Odds API: il piano gratuito non include lo storico, quindi il replay offline "
            "non puo' usare la fonte di produzione.",
            "La colonna 'fonte' del replay vale `pinnacle` per costruzione (un solo libro, "
            "B365): la riserva sulla media dei libri non e' esercitabile sui CSV, che hanno una "
            "sola terna per fonte. E' coperta dai test unitari, non da questo replay.",
            "Il campione e' quello della PR #49 (2024/25 + 2025/26 con modello e terna B365 "
            "pre): le righe 2026/27 non hanno quote nei CSV e non entrano.",
            "L'hit rate del replay non ha intervalli bootstrap a blocchi: usa Wilson, che non "
            "tiene conto della correlazione fra partite della stessa giornata. Gli IC della "
            "PR #49 sono bootstrap a blocchi e sono quindi piu' larghi.",
            "Il frame e' messo in cache in audit/output/ (non versionato): con --no-cache viene "
            "ricostruito da zero (~2-4 minuti).",
        ],
    }
    righe.to_csv(args.righe, index=False)
    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1, default=str)
    referto = scrivi_referto(payload)
    with open(args.report, "w", encoding="utf-8") as fh:
        fh.write(referto)

    print(referto)
    print(f"\njson:   {args.json}")
    print(f"righe:  {args.righe}")
    print(f"referto: {args.report}")
    print(f"\n[esito] parita' con la PR #49: {'SÌ' if parita else 'NO (differenze riportate)'}")
    return 0 if parita else 1


if __name__ == "__main__":
    raise SystemExit(main())
