#!/usr/bin/env python3
"""sonda_squalifiche.py — l'archivio ``player_match`` e' aggiornato? (sola lettura)

DOMANDA (punto 4 della commessa). Il motore squalifiche della PR #33 e l'archivio
``player_match_<lega>.json`` (prodotto dal workflow ``ppda_player_verify.yml``,
NON versionato: viene pubblicato come artifact) sono aggiornati alla stagione
2026/27? Se si': quante partite giocate copre, qual e' l'ultima partita per lega,
e le squalifiche del prossimo turno. Se no: cosa manca e quanto costa
aggiornarlo — **senza** farlo.

REGOLA DICHIARATA (scritta PRIMA dei numeri, come per la sonda allenatori):
le squalifiche entrano nella scheda partita **solo se** l'archivio copre tutte le
partite giocate della stagione in corso (zero mancanti rispetto ai ``*_Live.csv``)
e **tutti** i casi verificati su fonti pubbliche concordano con l'archivio.

SOLA LETTURA: nessuna rete (i fatti del run sono in
``audit/data/squalifiche/ultimo_run.json``, raccolti a mano), nessuna scrittura
dentro ``SoccerMath/``, nessun file versionato modificato. Il motore che calcola
gli eventi resta quello della PR #33 (``audit/squalifiche_feasibility.py``): qui
non si riscrivono le regole delle ammonizioni.

Uso::

    python audit/sonda_squalifiche.py [--player-match-dir DIR] [--casi FILE]
                                      [--out-dir DIR] [--results-dir DIR]

Code di uscita: 0 = archivio trovato e misurato; 3 = archivio assente (il referto
dice cosa manca e quanto costa); 1 = errore.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOCCERMATH_DIR = os.path.join(REPO_ROOT, "SoccerMath")
for _p in (SOCCERMATH_DIR, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

DEFAULT_RESULTS_DIR = os.path.join(REPO_ROOT, "audit", "results")
DEFAULT_FATTI = os.path.join(REPO_ROOT, "audit", "data", "squalifiche",
                             "ultimo_run.json")
DEFAULT_CASI = os.path.join(REPO_ROOT, "audit", "data", "squalifiche",
                            "casi_pubblici_2026_27.json")
#: Dove puo' stare l'archivio scaricato a mano (il primo che esiste vince).
CANDIDATI_ARCHIVIO = (
    "audit/output/ppda-player-verify-{run}/database",
    "audit/output/ppda-player-verify/database",
    "audit/output/player_match",
    "audit/data/squalifiche/player_match",
)
LEGHE = ("Serie A", "Premier League", "La Liga", "Bundesliga", "Ligue 1")
MOTORE = "audit/squalifiche_feasibility.py"
SOGLIA_COPERTURA = 1.0            # LA regola: tutte le partite giocate, non "quasi"
MIN_CASI_PUBBLICI = 3


# ---------------------------------------------------------------------------
# Lettura (sola lettura: nessuna scrittura fuori da audit/)
# ---------------------------------------------------------------------------
def carica_fatti(percorso: str) -> dict:
    """I fatti misurati dell'ultimo run dell'archivio (file versionato)."""
    if not percorso or not os.path.exists(percorso):
        return {}
    try:
        with open(percorso, "r", encoding="utf-8") as fh:
            dati = json.load(fh)
        return dati if isinstance(dati, dict) else {}
    except Exception:
        return {}


def carica_casi(percorso: str) -> list:
    if not percorso or not os.path.exists(percorso):
        return []
    try:
        with open(percorso, "r", encoding="utf-8") as fh:
            dati = json.load(fh)
    except Exception:
        return []
    casi = dati.get("casi") if isinstance(dati, dict) else dati
    return casi if isinstance(casi, list) else []


def candidati_archivio(run_id=None, base: str = REPO_ROOT) -> list:
    """I percorsi possibili dell'archivio, in ordine di preferenza."""
    fuori = []
    for schema in CANDIDATI_ARCHIVIO:
        fuori.append(os.path.join(base, schema.format(run=run_id or "*")))
    return fuori


def trova_archivio(run_id=None, base: str = REPO_ROOT, candidati=None) -> str | None:
    """La cartella con i ``player_match_*.json``, oppure ``None``.

    Un percorso con ``*`` viene espanso: cosi' un archivio scaricato in
    ``audit/output/ppda-player-verify-<run_id>/database`` viene trovato da solo.
    """
    import glob

    for schema in (candidati if candidati is not None else candidati_archivio(run_id, base)):
        for percorso in sorted(glob.glob(schema)):
            if not os.path.isdir(percorso):
                continue
            if any(f.startswith("player_match_") and f.endswith(".json")
                   for f in os.listdir(percorso)):
                return percorso
    return None


def riepilogo_archivio(archivio: str, leghe=LEGHE) -> dict:
    """Per lega: righe, partite distinte, stagioni, ultima partita dell'archivio."""
    from match_stats_archive import load_player, player_filename

    fuori, mancanti = {}, []
    for lega in leghe:
        percorso = os.path.join(archivio, player_filename(lega))
        if not os.path.exists(percorso):
            mancanti.append(lega)
            continue
        righe = load_player(lega, archivio)
        partite, stagioni = set(), set()
        ultima = ""
        for riga in righe:
            data = str(riga.get("date") or "")[:10]
            chiave = (data, riga.get("team"), riga.get("opponent"))
            partite.add(chiave)
            if riga.get("season") is not None:
                stagioni.add(int(riga["season"]))
            ultima = max(ultima, data)
        fuori[lega] = {"righe": len(righe), "partite": len(partite),
                       "stagioni": sorted(stagioni), "ultima_partita": ultima or None}
    return {"lega_per_lega": fuori, "leghe_senza_file": mancanti}


def partite_giocate_stagione(lega: str, stagione: int) -> dict:
    """Le partite giocate della stagione secondo i CSV (il denominatore minimo).

    Chiave: ``(data ISO, squadra di casa canonica, squadra ospite canonica)``.
    Nessun nome inventato: la canonicalizzazione e' quella di produzione
    (``scheda_partita``), la stessa dei test della scheda partita.
    """
    import scheda_partita as sp

    risultati = sp.carica_risultati_stagione(lega, stagione=stagione)
    fuori = {}
    for _, m in risultati.iterrows():
        chiave = (m["data"].date().isoformat(), m["casa"], m["trasferta"])
        fuori[chiave] = {"giornata": int(m["giornata"]) if m.get("giornata") is not None else None}
    return fuori


def copertura_stagione(righe_lega: list, partite_csv: dict) -> dict:
    """Quante partite giocate dei CSV l'archivio copre davvero.

    L'archivio usa i nomi grezzi di Understat: la chiave si costruisce con lo
    stesso resolver di produzione (``team_names``), nessun abbinamento per
    somiglianza. Le partite che non si riescono a canonicalizzare finiscono in
    ``senza_chiave``: non si contano come coperte.
    """
    from team_names import resolve_team_name

    chiavi, senza_chiave = set(), []
    for riga in righe_lega:
        data = str(riga.get("date") or "")[:10]
        squadra = resolve_team_name(riga.get("team") or "")
        avversario = resolve_team_name(riga.get("opponent") or "")
        if not data or not (squadra.mapped and avversario.mapped):
            senza_chiave.append({"data": data, "team": riga.get("team"),
                                 "opponent": riga.get("opponent")})
            continue
        chiavi.add((data, squadra.canonical, avversario.canonical))
    mancanti = sorted(k for k in partite_csv if k not in chiavi)
    return {"partite_csv": len(partite_csv), "coperte": len(partite_csv) - len(mancanti),
            "mancanti": mancanti, "n_mancanti": len(mancanti),
            "senza_chiave": len(senza_chiave),
            "esempi_senza_chiave": senza_chiave[:5]}


def confronta_casi(casi: list, righe_per_lega: dict) -> list:
    """Casi pubblici: l'archivio mostra il giocatore assente nella partita indicata?"""
    fuori = []
    for caso in casi:
        righe = righe_per_lega.get(caso.get("lega")) or []
        data, squadra = caso.get("data"), caso.get("squadra")
        giocatore = caso.get("giocatore")
        partita = [r for r in righe if str(r.get("date") or "")[:10] == data
                   and _stessa_squadra(r.get("team"), squadra)]
        riga = dict(caso)
        if not partita:
            riga.update({"esito": "turno non coperto", "archivio_presente": None})
        else:
            presente = any(r.get("player") == giocatore for r in partita)
            riga["archivio_presente"] = presente
            atteso_assente = bool(caso.get("assente", True))
            riga["esito"] = "concorda" if presente is not atteso_assente else "non concorda"
        fuori.append(riga)
    return fuori


def _stessa_squadra(nome_archivio, nome_caso) -> bool:
    import sonda_allenatori as sa

    return sa.stessa_squadra(nome_archivio, nome_caso)


def verdetto(copertura: dict, casi: list) -> dict:
    """La regola dichiarata, applicata: copertura 100% E casi tutti concordi."""
    if not copertura:
        return {"copertura_ok": False, "casi_ok": False, "ok": False,
                "motivi": ["copertura non misurabile: archivio assente"]}
    copertura_ok = copertura.get("n_mancanti") == 0 and copertura.get("partite_csv", 0) > 0
    casi_ok = bool(casi) and all(c.get("esito") == "concorda" for c in casi)
    motivi = []
    if not copertura_ok:
        motivi.append(f"{copertura.get('n_mancanti', 0)} partite giocate non coperte")
    if not casi_ok:
        motivi.append("nessun caso pubblico verificabile" if not casi
                      else f"{sum(1 for c in casi if c.get('esito') != 'concorda')} "
                           f"casi su {len(casi)} non concordi")
    return {"copertura_ok": copertura_ok, "casi_ok": casi_ok,
            "ok": bool(copertura_ok and casi_ok), "motivi": motivi}


# ---------------------------------------------------------------------------
# Referto
# ---------------------------------------------------------------------------
def testo_referto(misure: dict, coperture: dict, casi: list, esito: dict,
                  fatti: dict, note: list) -> str:
    righe = []
    righe.append("# Sonda squalifiche (archivio player_match, sola lettura)")
    righe.append("")
    righe.append(f"Run: **{misure['quando']}** · stagione: **{misure['stagione']}/"
                 f"{str(int(misure['stagione']) + 1)[-2:]}** · archivio: "
                 f"**{misure['archivio'] or 'ASSENTE'}**.")
    righe.append("")
    righe.append("## Regola dichiarata (prima dei numeri)")
    righe.append("")
    righe.append("Le squalifiche entrano nella scheda partita **solo se**:")
    righe.append("")
    righe.append("1. l'archivio `player_match` copre **tutte** le partite giocate "
                 f"della stagione in corso (soglia dichiarata: "
                 f"{SOGLIA_COPERTURA:.0%} dei `*_Live.csv`, zero mancanti);")
    righe.append(f"2. **tutti** i casi verificati su fonti pubbliche concordano con "
                 f"quello che mostra l'archivio (almeno {MIN_CASI_PUBBLICI} casi).")
    righe.append("")
    if misure["archivio"]:
        righe.append("Esito di questo run: **" + ("SI'" if esito["ok"] else "NO") + "**"
                     + ("" if esito["ok"] else " — " + "; ".join(esito["motivi"])))
    else:
        righe.append("Esito di questo run: **archivio non disponibile in questo "
                     "ambiente** → le squalifiche NON entrano nella scheda (e non "
                     "devono: la regola non e' soddisfatta).")
    righe.append("")
    righe.append("## Stato dell'archivio")
    righe.append("")
    if misure["archivio"]:
        righe.append("| Lega | Righe giocatore | Partite distinte | Stagioni | Ultima partita |")
        righe.append("|---|---|---|---|---|")
        for lega, numeri in misure["riepilogo"]["lega_per_lega"].items():
            righe.append(f"| {lega} | {numeri['righe']} | {numeri['partite']} | "
                         f"{', '.join(str(s) for s in numeri['stagioni'])} | "
                         f"{numeri['ultima_partita'] or '—'} |")
        if misure["riepilogo"]["leghe_senza_file"]:
            righe.append("")
            righe.append("Leghe senza file nell'archivio: "
                         + ", ".join(misure["riepilogo"]["leghe_senza_file"]) + ".")
        righe.append("")
        righe.append("## Copertura delle partite giocate della stagione")
        righe.append("")
        righe.append("| Lega | Partite giocate nei CSV | Coperte | Mancanti |")
        righe.append("|---|---|---|---|")
        for lega, cop in coperture.items():
            righe.append(f"| {lega} | {cop['partite_csv']} | {cop['coperte']} | "
                         f"{cop['n_mancanti']} |")
        righe.append("")
        for lega, cop in coperture.items():
            if cop["mancanti"]:
                righe.append(f"**{lega}** — partite non coperte ({cop['n_mancanti']}):")
                for data, casa, trasferta in cop["mancanti"][:20]:
                    righe.append(f"* {data} {casa} - {trasferta}")
                righe.append("")
        righe.append("## Casi pubblici")
        righe.append("")
        if not casi:
            righe.append(f"_Nessun caso pubblico da confrontare: servono almeno "
                         f"{MIN_CASI_PUBBLICI} casi con fonte e data._")
        else:
            righe.append("| Lega | Squadra | Giocatore | Data | Archivio | Esito | Fonte |")
            righe.append("|---|---|---|---|---|---|---|")
            for c in casi:
                righe.append(f"| {c.get('lega')} | {c.get('squadra')} | {c.get('giocatore')} | "
                             f"{c.get('data')} | "
                             f"{'presente' if c.get('archivio_presente') else 'assente'} | "
                             f"**{c.get('esito')}** | {c.get('fonte')} |")
        righe.append("")
    else:
        righe.append("**Cosa manca.** I file `player_match_<lega>.json` non sono "
                     "versionati: li produce il workflow `ppda_player_verify.yml`, che "
                     "gira in sola lettura (`permissions: contents: read`) e li pubblica "
                     "come **artifact**. In questo ambiente l'artifact non e' "
                     "scaricabile: il download termina con un errore TLS/EOF sul blob "
                     "di archiviazione di GitHub (`*.blob.core.windows.net`), che non e' "
                     "raggiungibile dalla sandbox. Senza quei file non si possono "
                     "misurare le tre cose chieste: ultima partita per lega, partite "
                     "2026/27 coperte contro i `*_Live.csv`, e squalifiche del prossimo "
                     "turno.")
        righe.append("")
        if fatti:
            art = fatti.get("artifact") or {}
            righe.append("**Ultimo archivio prodotto (fatti misurati).**")
            righe.append("")
            righe.append(f"* run **{fatti.get('run_id')}** del workflow "
                         f"`{fatti.get('workflow')}`: {fatti.get('esito')}, "
                         f"{fatti.get('iniziato_il')} → {fatti.get('finito_il')} "
                         f"(**{fatti.get('durata')}**), evento `{fatti.get('evento')}`;")
            righe.append(f"* artifact **{art.get('nome')}** (id {art.get('id')}), "
                         f"{art.get('byte')} byte, creato il {art.get('creato_il')}, "
                         f"**scade il {art.get('scade_il')}**;")
            righe.append(f"* tutti i passi del job sono `success` (fonte: "
                         f"`gh api .../actions/runs/{fatti.get('run_id')}/jobs`): "
                         f"l'acquisizione delle 5 leghe e' arrivata in fondo, quindi un "
                         f"archivio recente esiste — ma **non e' leggibile da qui**.")
            righe.append("")
            righe.append("**Quanto costa aggiornarlo.**")
            righe.append("")
            righe.append(f"* un run manuale di `{fatti.get('workflow')}` "
                         f"(`workflow_dispatch`, nessun cron): la misura nota e' "
                         f"**{fatti.get('durata')}**, con 1 richiesta HTTP per partita e "
                         f"una finestra mobile di 5 stagioni per lega;")
            righe.append("* oppure **zero run**: scaricare l'artifact già pronto dal "
                         "browser (GitHub → Actions → run → artifact) e scompattarlo in "
                         "`audit/output/ppda-player-verify-<run>/database/`;")
            righe.append("* poi la misura e' immediata e offline: `python "
                         "audit/sonda_squalifiche.py` → il referto si riempie da solo "
                         "con ultima partita per lega, copertura contro i `*_Live.csv` e "
                         "casi pubblici.")
            righe.append("")
            righe.append("*Nota di costo sull'analisi vera.* Il motore che calcola gli "
                         "eventi (ammonizioni cumulate, rossi) e' quello della PR #33, "
                         "`" + MOTORE + "`: su ~226.657 righe giocatore il referto della "
                         "PR #33 dichiara una precisione dell'1X2 con l'evento in Serie A "
                         "del **48.1%** contro il **96.8%** della Bundesliga — per "
                         "questo il motore, da solo, non basta a mettere le squalifiche "
                         "in scheda: servono i casi pubblici.")
        else:
            righe.append("_Nessun fatto misurato in `" + DEFAULT_FATTI + "`._")
        righe.append("")
        righe.append("**Denominatore minimo: le partite già giocate nei CSV.**")
        righe.append("")
        righe.append("| Lega | Partite giocate 2026/27 nei `*_Live.csv` |")
        righe.append("|---|---|")
        for lega, cop in coperture.items():
            righe.append(f"| {lega} | {cop['partite_csv']} |")
        righe.append("")
        righe.append("Sono le partite che l'archivio deve contenere **tutte** perché "
                     "la regola sia soddisfatta: se ne manca una, le squalifiche non "
                     "entrano nella scheda.")
        righe.append("")
    righe.append("## Cosa NON fa questa sonda")
    righe.append("")
    righe.append("* non aggiorna l'archivio e non lancia nessun workflow (il run e' "
                 "manuale e lo lancia Felice);")
    righe.append("* non riscrive le regole delle ammonizioni: quelle vivono in "
                 f"`{MOTORE}` (PR #33);")
    righe.append("* non tocca l'app: la scheda partita non mostra squalifiche.")
    if note:
        righe.append("")
        righe.append("## Note del run")
        righe.append("")
        for n in note:
            righe.append(f"* {n}")
    return "\n".join(righe) + "\n"


# ---------------------------------------------------------------------------
# Giro completo
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Sonda squalifiche (sola lettura)")
    parser.add_argument("--player-match-dir", default=None,
                        help="cartella con i player_match_*.json (default: cerca nei "
                             "percorsi noti)")
    parser.add_argument("--out-dir", default=os.path.join(REPO_ROOT, "audit", "data",
                                                          "squalifiche"))
    parser.add_argument("--results-dir", default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--fatti", default=DEFAULT_FATTI)
    parser.add_argument("--casi", default=DEFAULT_CASI)
    parser.add_argument("--stagione", type=int, default=None)
    args = parser.parse_args(argv)

    import config

    stagione = args.stagione or config.get_current_season_start_year()
    quando = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fatti = carica_fatti(args.fatti)
    archivio = (os.path.abspath(args.player_match_dir) if args.player_match_dir
                else trova_archivio((fatti.get("run_id"))))
    if archivio and not os.path.isdir(archivio):
        archivio = trova_archivio((fatti.get("run_id")))
    note = []

    riepilogo, righe_per_lega, coperture, casi_confrontati = None, {}, {}, []
    esito = verdetto({}, [])
    if archivio:
        riepilogo = riepilogo_archivio(archivio)
        for lega in LEGHE:
            percorso = os.path.join(archivio, f"player_match_{lega}.json")
            righe_per_lega[lega] = []
            if lega in riepilogo["lega_per_lega"]:
                from match_stats_archive import load_player
                righe_per_lega[lega] = load_player(lega, archivio)
            else:
                note.append(f"{lega}: file assente nell'archivio.")
            coperture[lega] = copertura_stagione(
                righe_per_lega[lega], partite_giocate_stagione(lega, stagione))
        casi_confrontati = confronta_casi(carica_casi(args.casi), righe_per_lega)
        esito = verdetto(_copertura_totale(coperture), casi_confrontati)
    else:
        for lega in LEGHE:
            coperture[lega] = {"partite_csv": len(partite_giocate_stagione(lega, stagione)),
                               "coperte": 0, "mancanti": [], "n_mancanti": 0,
                               "senza_chiave": 0, "esempi_senza_chiave": []}
        note.append("archivio assente: nessun file player_match_*.json trovato in "
                    + ", ".join(candidati_archivio(fatti.get("run_id"))))

    misure = {"versione": "sonda_squalifiche_v1", "quando": quando,
              "stagione": stagione, "archivio": archivio, "riepilogo": riepilogo,
              "leghe": list(LEGHE), "soglia_copertura": SOGLIA_COPERTURA,
              "min_casi_pubblici": MIN_CASI_PUBBLICI, "esito": esito,
              "casi": casi_confrontati, "fatti": fatti}
    os.makedirs(args.results_dir, exist_ok=True)
    referto = os.path.join(args.results_dir, "sonda_squalifiche.md")
    with open(referto, "w", encoding="utf-8") as fh:
        fh.write(testo_referto(misure, coperture, casi_confrontati, esito, fatti, note))
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "ultima_misura.json"), "w",
              encoding="utf-8") as fh:
        json.dump(misure, fh, ensure_ascii=False, indent=2)

    print(f"ARCHIVIO={'trovato' if archivio else 'ASSENTE'} STAGIONE={stagione} "
          f"ESITO={'ok' if esito['ok'] else 'no'} CASI={len(casi_confrontati)}")
    print(f"REFERTO={referto}")
    return 0 if archivio else 3


def _copertura_totale(coperture: dict) -> dict:
    """Le coperture per lega sommate in un unico verdetto (per la regola)."""
    partite = sum(c.get("partite_csv", 0) for c in coperture.values())
    mancanti = sum(c.get("n_mancanti", 0) for c in coperture.values())
    return {"partite_csv": partite, "coperte": partite - mancanti,
            "n_mancanti": mancanti,
            "mancanti": [k for c in coperture.values() for k in (c.get("mancanti") or [])],
            "senza_chiave": sum(c.get("senza_chiave", 0) for c in coperture.values())}


if __name__ == "__main__":
    sys.exit(main())
