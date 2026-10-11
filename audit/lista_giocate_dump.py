#!/usr/bin/env python3
"""audit/lista_giocate_dump.py

Stampa per un file di quote e un istante passati da riga di comando:
- generato_il
- conteggi ammesse / escluse (iniziate e senza quote)
- prime 20 righe (data, lega, partita, giocata, p, quota equa, quota stimata, fonte ed età)
- margini per tipo di esito (min, mediana, max)
- proposta di multipla per k (1, 2, 3, 4) e costo per evento aggiunto rispetto a k-1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
SM_DIR = os.path.join(REPO_ROOT, "SoccerMath")

for p in (REPO_ROOT, SM_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import market_odds as mo
import lista_giocate as lg


def parse_args():
    parser = argparse.ArgumentParser(description="Dump diagnostico di lista_giocate_v1.")
    parser.add_argument(
        "--file",
        default=os.path.join(SM_DIR, "database", "live_odds.json"),
        help="Percorso al file live_odds.json (default: SoccerMath/database/live_odds.json)",
    )
    parser.add_argument(
        "--adesso",
        default="2026-10-11T13:00:00Z",
        help="Istante ISO UTC di riferimento (default: 2026-10-11T13:00:00Z)",
    )
    return parser.parse_args()


def calcola_mediana(valori: list[float]) -> float:
    if not valori:
        return 0.0
    s = sorted(valori)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def main():
    args = parse_args()
    file_path = args.file
    adesso_str = args.adesso

    dt_adesso = datetime.fromisoformat(adesso_str.replace("Z", "+00:00"))
    if dt_adesso.tzinfo is None:
        dt_adesso = dt_adesso.replace(tzinfo=timezone.utc)

    if not os.path.exists(file_path):
        print(f"Errore: file non trovato: {file_path}", file=sys.stderr)
        sys.exit(1)

    with open(file_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    generato_il = payload.get("generato_il", "n/d")
    print(f"generato_il: {generato_il}")
    print(f"istante_riferimento: {dt_adesso.strftime('%Y-%m-%dT%H:%M:%SZ')}")

    res = lg.calcola_lista_giocate(payload, adesso_utc=dt_adesso)

    print("\n--- CONTEGGI PARTITE ED ESCLUSIONI ---")
    print(f"Partite totali nel file: {res['n_partite_totali']}")
    print(f"Partite ammesse (non iniziate con quote): {res['n_partite_ammesse']}")
    print(f"Partite escluse (già iniziate): {res['n_escluse_iniziate']}")
    print(f"Partite escluse (senza quote valide): {res['n_escluse_senza_quote']}")
    print(f"Totale giocate generate: {len(res['giocate'])}")

    print("\n--- PRIME 20 RIGHE (ordinate per probabilità decrescente) ---")
    header = f"{'#':<3} | {'Data':<16} | {'Lega':<15} | {'Partita':<35} | {'G':<3} | {'p':<7} | {'1/p':<5} | {'q_est':<5} | {'Stato/Nota':<20} | {'Fonte':<20}"
    print(header)
    print("-" * len(header))
    for i, g in enumerate(res["giocate"][:20], 1):
        p_pct = f"{g['probabilita']*100:.2f}%"
        q_eq = f"{g['quota_equa']:.2f}"
        q_est = f"{g['quota_b365_stimata']:.2f}" if g.get("quota_b365_stimata") is not None else "n/d"
        partita = g["partita"][:35]
        lega = g["lega"][:15]
        data_s = g.get("data", "")[:16]
        nota = g.get("stato_quota", g.get("nota_stima", ""))[:20]
        fonte = g.get("fonte", "")[:20]
        print(f"{i:<3} | {data_s:<16} | {lega:<15} | {partita:<35} | {g['giocata']:<3} | {p_pct:<7} | {q_eq:<5} | {q_est:<5} | {nota:<20} | {fonte:<20}")

    print("\n--- MARGINI PER TIPO DI ESITO (p * q_stimata - 1) ---")
    esiti_order = ["1", "X", "2", "1X", "X2", "12"]
    margini_per_tipo = {e: [] for e in esiti_order}
    for g in res["giocate"]:
        es = g["giocata"]
        p = g["probabilita"]
        q = g.get("quota_b365_stimata")
        if q is not None and p > 0:
            m = p * q - 1.0
            if es in margini_per_tipo:
                margini_per_tipo[es].append(m)

    for es in esiti_order:
        vals = margini_per_tipo[es]
        if vals:
            min_m = min(vals) * 100.0
            med_m = calcola_mediana(vals) * 100.0
            max_m = max(vals) * 100.0
            print(f"Esito {es:<2} (n={len(vals)}): min = {min_m:+.2f}%, mediana = {med_m:+.2f}%, max = {max_m:+.2f}%")

    print("\n--- PROPOSTA MULTIPLA PER K (in fascia quota stimata [2,00; 3,00]) ---")
    prop = lg.cerca_proposta_multipla(res["giocate"], fascia_min=2.00, fascia_max=3.00, top_k=40)
    best_by_k = prop.get("per_k", {})

    for k in (1, 2, 3, 4):
        item = best_by_k.get(k)
        if item is None:
            print(f"k={k}: Nessuna combinazione valida in fascia [2,00; 3,00]")
        else:
            p_val = item["probabilita"]
            q_val = item["quota_totale"]
            q_eq = item["quota_equa"]
            ev_val = item["ev"]
            costo_str = ""
            if k > 1:
                prev_item = best_by_k.get(k - 1)
                if prev_item:
                    diff_pt = (p_val - prev_item["probabilita"]) * 100.0
                    costo_str = f" | Costo vs k={k-1}: {diff_pt:+.2f} punti di probabilità"
            print(f"k={k}: p = {p_val*100:.2f}%, quota = {q_val:.2f}, quota equa = {q_eq:.2f}, EV = {ev_val*100:+.2f}%{costo_str}")
            for g in item.get("giocate", []):
                print(f"     - {g['partita']} ({g['giocata']}) [p = {g['probabilita']*100:.2f}%, q = {g['quota_b365_stimata']:.2f}]")


if __name__ == "__main__":
    main()
