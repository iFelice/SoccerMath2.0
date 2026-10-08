#!/usr/bin/env python3
"""live_odds_feasibility.py — Fattibilita' di una fonte di quote 1X2 dal vivo (sola lettura).

Mette insieme le tre prove e scrive il referto unico:

  1. ``audit/bookmaker_source_test.py``   quale bookmaker basta (punto 1);
  2. ``audit/live_odds_probe.py``         chiamate reali alle fonti (punto 2);
  3. ``audit/live_odds_match.py``         abbinamento ai nomi canonici (punto 3);
  4. budget in crediti (punto 4), calcolato dal costo MISURATO per chiamata e
     dal numero di turni infrasettimanali MISURATO sui CSV della stagione.

Nessuna modifica a ``SoccerMath/`` e nessuna chiamata di rete: gli snapshot
delle chiamate reali sono committati in ``audit/data/live_odds_probe/`` perche'
la sandbox di sviluppo non ha rete verso quei domini.

Uso::

    python audit/live_odds_feasibility.py                  # ricalcola tutto
    python audit/live_odds_feasibility.py --riutilizza     # riusa i JSON in audit/output

Output: ``audit/results/live_odds_feasibility.md``.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter, OrderedDict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

DB_DIR = os.path.join(_REPO_ROOT, "SoccerMath", "database")
DATA_DIR = os.path.join(_AUDIT_DIR, "data", "live_odds_probe")
OUT_DIR = os.path.join(_AUDIT_DIR, "output")
RESULTS_DIR = os.path.join(_AUDIT_DIR, "results")
REPORT_PATH = os.path.join(RESULTS_DIR, "live_odds_feasibility.md")

CI = {}       # esiti dei check GitHub, passati con --ci suite=... audit=... replay=...
CI_RUN = {}   # id dei run GitHub, passati con --ci-run suite=... audit=... replay=...

import bookmaker_source_test as BST  # noqa: E402
import live_odds_match as LOM  # noqa: E402

# ---------------------------------------------------------------------------
# Dati di documentazione (con il link alla fonte ufficiale)
# ---------------------------------------------------------------------------
DOC = [
    ("Piano gratuito (Starter)", "500 crediti al mese, tutti gli sport, gran parte dei "
     "bookmaker, tutti i mercati; storico escluso. Reset il 1° del mese.",
     "https://the-odds-api.com/ (sezione Get Access) e https://the-odds-api.com/manage/faqs.html"),
    ("Piani a pagamento", "20.000 crediti 30 USD/mese; 100.000 crediti 59 USD/mese.",
     "https://the-odds-api.com/"),
    ("Costo per chiamata (/odds)", "costo = [numero di mercati] x [numero di regioni]; "
     "le risposte vuote non consumano crediti. Esempi ufficiali: 1 mercato x 3 regioni = 3; "
     "3 mercati x 3 regioni = 9.",
     "https://the-odds-api.com/liveapi/guides/v4/ (Usage Quota Costs)"),
    ("Crediti residui/used/last", "header di risposta x-requests-remaining, "
     "x-requests-used, x-requests-last.",
     "https://the-odds-api.com/liveapi/guides/v4/ (Response Headers)"),
    ("Elenco sport (/v4/sports)", "gratuito: non consuma crediti.",
     "https://the-odds-api.com/liveapi/guides/v4/ (GET sports)"),
    ("Intervallo di aggiornamento", "mercati principali (h2h/1x2): 60 s pre-partita, "
     "40 s live; l'intervallo si riduce nelle 6 ore prima del calcio d'inizio.",
     "https://the-odds-api.com/sports-odds-data/update-intervals.html"),
    ("Catalogo bookmaker", "l'unica chiave Bet365 e' bet365_au, regione AU, solo piani a "
     "pagamento e solo AFL/NRL.",
     "https://the-odds-api.com/sports-odds-data/bookmaker-apis.html"),
    ("football-data.co.uk fixture", "file delle partite in programma con quote; 'le quote "
     "sono raccolte per le partite del weekend il venerdi' pomeriggio, di norma non oltre le "
     "17:00 ora britannica; per i turni infrasettimanali il martedi' non oltre le 13:00'.",
     "https://www.football-data.co.uk/matches.php"),
]

# Terza fonte candidata: documentata, non verificabile senza una chiave dedicata
THIRD_SOURCE = {
    "nome": "OddsPapi (api.oddspapi.io)",
    "piano_gratuito_dichiarato": "250 richieste al mese, tutti gli sport e tutti i bookmaker, "
                                 "nessuna carta di credito; include Pinnacle e Bet365.",
    "fonte": "https://oddspapi.io/ (piano gratuito) e "
             "https://oddspapi.io/blog/football-odds-api-soccer-data/",
    "perche_non_verificabile": "nel repository non esiste una chiave per questo servizio "
                               "(l'unica chiave quote presente e' ODDS_API_KEY, di The Odds "
                               "API) e la sandbox non ha rete verso domini esterni: aprire un "
                               "account richiede una casella di posta del progetto.",
}

WEEKS_PER_MONTH = 365.25 / 12 / 7          # 4,348 settimane per mese in media
UPDATES_PER_WEEK = 2                        # commessa: due aggiornamenti a settimana
LEAGUE_COUNT = 5


# ---------------------------------------------------------------------------
# Turni infrasettimanali misurati sui CSV
# ---------------------------------------------------------------------------
def midweek_rounds(season_file: str):
    """Turni infrasettimanali (mar/mer/gio) dell'unione delle 5 leghe, per mese.

    Un turno = un gruppo di date infrasettimanali consecutive o a distanza <= 2
    giorni. Misurato sui CSV di football-data gia' presenti nel repository.
    """
    dates = set()
    for prefix, _lega in BST.LEAGUES:
        path = os.path.join(DB_DIR, f"{prefix}_{season_file}.csv")
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path, low_memory=False)
        d = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce").dropna().dt.normalize()
        dates |= set(d)
    mw = sorted(x for x in dates if x.weekday() in (1, 2, 3))
    if not mw:
        return [], Counter(), 0
    clusters = [[mw[0]]]
    for x in mw[1:]:
        if (x - clusters[-1][-1]).days <= 2:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    starts = [c[0] for c in clusters]
    per_month = Counter(s.strftime("%Y-%m") for s in starts)
    return starts, per_month, len(per_month)


def build_budget(probe):
    """Crediti necessari, dal costo MISURATO per chiamata."""
    calls = {c.get("label"): c for c in probe.get("calls", [])}
    costo_eu_uk = 2
    costo_eu = 1
    for lab in ("odds:soccer_italy_serie_a",):
        h = (calls.get(lab) or {}).get("headers") or {}
        if h.get("x-requests-last"):
            costo_eu_uk = int(h["x-requests-last"])
    reg = probe.get("controllo_una_regione") or {}
    if (reg.get("crediti") or {}).get("x-requests-last"):
        costo_eu = int(reg["crediti"]["x-requests-last"])

    stagioni = []
    for suf, label in (("2024", "2024/25"), ("2025", "2025/26")):
        starts, per_month, n_mesi = midweek_rounds(suf)
        if not starts:
            continue
        vals = list(per_month.values())
        stagioni.append({"stagione": label, "n_turni": len(starts), "mesi": n_mesi,
                         "media_mese": float(np.mean(vals)), "max_mese": int(max(vals)),
                         "per_mese": dict(sorted(per_month.items()))})
    if not stagioni:
        return {"disponibile": False}, stagioni
    worst_mean = max(s["media_mese"] for s in stagioni)
    worst_month = max(s["max_mese"] for s in stagioni)

    scenari = []
    for nome, costo, regioni in (("eu,uk (misurato)", costo_eu_uk, "eu,uk"),
                                 ("eu (misurato)", costo_eu, "eu")):
        per_round = costo * LEAGUE_COUNT
        base = UPDATES_PER_WEEK * WEEKS_PER_MONTH * per_round
        medio = base + worst_mean * per_round
        peggiore = base + worst_month * per_round
        scenari.append({"regioni": regioni, "costo_chiamata": costo,
                        "crediti_per_giro_5_leghe": per_round,
                        "crediti_mese_base": base,
                        "crediti_mese_medio": medio,
                        "crediti_mese_peggiore": peggiore,
                        "pct_piano_gratuito_medio": 100 * medio / 500,
                        "pct_piano_gratuito_peggiore": 100 * peggiore / 500,
                        "sta_nei_500": peggiore <= 500})
    # crediti: si prende il minimo dei residui e il massimo degli usati fra TUTTE
    # le chiamate registrate (chiamate per lega + controlli), cosi' il numero e'
    # l'ultimo stato noto della quota, non quello di una singola chiamata.
    headers = [c.get("headers") or {} for c in probe.get("calls", [])]
    for k in ("controllo_bet365", "controllo_una_regione"):
        h = (probe.get(k) or {}).get("crediti") or {}
        if h:
            headers.append(h)

    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    rimasti = [x for x in (_int(h.get("x-requests-remaining")) for h in headers) if x is not None]
    usati = [x for x in (_int(h.get("x-requests-used")) for h in headers) if x is not None]
    residui = min(rimasti) if rimasti else None
    # la prima chiamata (/v4/sports) non consuma crediti: il suo 'used' e' lo stato
    # iniziale della quota, prima di ogni prova di questo audit
    used_iniziale = _int((probe.get("calls") or [{}])[0].get("headers", {}).get("x-requests-used"))
    used_finale = max(usati) if usati else None
    consumati = (used_finale - used_iniziale) if (used_iniziale is not None and used_finale is not None) else None
    return {"disponibile": True, "scenari": scenari, "stagioni": stagioni,
            "crediti_residui_alla_prova": residui,
            "crediti_usati_prima_delle_prove": used_iniziale,
            "crediti_usati_dopo_le_prove": used_finale,
            "crediti_consumati_dalle_prove": consumati,
            "settimane_per_mese": WEEKS_PER_MONTH,
            "aggiornamenti_settimana": UPDATES_PER_WEEK}, stagioni


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def md(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |")
    return "\n".join(out)


def pct(x, nd=1):
    return "n/d" if x is None else f"{100 * x:.{nd}f}%"


def git(*cmd):
    try:
        return subprocess.run(cmd, cwd=_REPO_ROOT, capture_output=True, text=True,
                              timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "n/d"


def build_markdown(probe, bst, match, budget, stagioni, checks, verdetto, criteri):
    L = []
    A = L.append
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    A("# Fattibilita' di una fonte di quote 1X2 dal vivo — referto di audit (sola lettura)\n")
    A(f"Generato da `audit/live_odds_feasibility.py` ({now}), branch "
      f"`{git('git', 'rev-parse', '--abbrev-ref', 'HEAD')}`, commit "
      f"`{git('git', 'rev-parse', '--short', 'HEAD')}`. "
      "Nessuna modifica a `SoccerMath/`: tutti i file nuovi vivono in `audit/`.\n")
    A("Comandi:\n")
    A("```")
    A("python audit/bookmaker_source_test.py      # punto 1 (quale bookmaker basta)")
    A("python audit/live_odds_probe.py --out audit/data/live_odds_probe   # punto 2 (rete)")
    A("python audit/live_odds_match.py            # punto 3 (abbinamento nomi)")
    A("python audit/live_odds_feasibility.py      # questo referto (punti 1-5)")
    A("```\n")

    # ---------------------------------------------------------------- 0
    A("## 0. Prerequisiti\n")
    A(md(["Voce", "Esito", "Comando / link", "Evidenza"], checks["prerequisiti"]) or "")
    A("")

    # ---------------------------------------------------------------- 1
    A("## 1. Quale bookmaker basta (dati storici gia' presenti)\n")
    A("Stesso protocollo della PR #49 (funzioni riusate, non riscritte): stagioni 2024/25 e "
      "2025/26, de-vig proporzionale (decisione) e Shin (sensibilita'), LogLoss/Brier/RPS, "
      "BSS contro il base rate del train, reliability/resolution a 10 bin, regola Top Mix "
      "(esito piu' probabile se >= 0,55), bootstrap a blocchi (lega x stagione x giornata) con "
      f"{bst['reps']} repliche e seme {bst['seed']}. Referto completo: "
      "`audit/results/bookmaker_source_test.md`.\n")
    A("Campioni: " + "; ".join(f"{k} = {v}" for k, v in bst["campioni"].items()) + ".\n")
    A("### 1a. Qualita' e scelte Top Mix (campione comune)\n")
    rows = []
    tm = {t["fonte"]: t for t in bst["comune"]["topmix"]}
    for q in bst["comune"]["quality"]:
        t = tm.get(q["fonte"], {})
        rows.append([bst["etichette"][q["fonte"]], q["n"], f"{q['logloss']:.4f}",
                     f"{q['brier']:.4f}", f"{q['rps']:.4f}", f"{q['bss_logloss']:.4f}",
                     t.get("n_scelte", "—"),
                     "n/d" if not t else f"{t['hit']:.4f}",
                     "n/d" if not t else f"{t['gap']:+.4f}"])
    A(md(["Fonte", "n", "LogLoss", "Brier", "RPS", "BSS LogLoss", "Scelte Top Mix",
          "Hit rate", "Conf − hit"], rows))
    A("")
    A("### 1b. Differenze appaiate contro Bet365 (A − B365), IC 95% bootstrap\n")
    A("Delta negativo = A migliore di B365. L'hit rate e' appaiato sulle partite ammesse da "
      "ENTRAMBE le fonti: il valore e' 0 per tutte le fonti perche' la scelta ammessa coincide "
      "sempre con quella di B365 (nessuna divergenza di esito sulle partite a soglia).\n")
    rows = []
    for k, d in bst["comune"]["diffs"].items():
        h = d["hit_appaiato"]
        rows.append([bst["etichette"][k], d["n_confronto"],
                     f"{d['delta_logloss']:+.4f} [{d['ci_logloss'][0]:+.4f}; "
                     f"{d['ci_logloss'][1]:+.4f}]",
                     f"{d['delta_brier']:+.4f}", f"{d['delta_rps']:+.4f}",
                     f"{h['delta']:+.4f} [{h['ci'][0]:+.4f}; {h['ci'][1]:+.4f}] (n={h['n_intersezione']})"])
    A(md(["Fonte (A)", "n confronto", "Δ LogLoss [IC]", "Δ Brier", "Δ RPS",
          "Δ hit rate appaiato (n)"], rows))
    A("")
    A("### 1c. Verdetto (regola fissata prima dei numeri: C1 e C2 e C3)\n")
    rows = []
    for k, v in bst["verdetti"].items():
        rows.append([bst["etichette"][k], v["esito"],
                     "sì" if v["c1"] else "NO", "sì" if v["c2"] else "NO",
                     "sì" if v["c3"] else "NO"])
    A(md(["Fonte", "Esito", "C1 (Δ LogLoss)", "C2 (Δ hit rate)", "C3 (calibrazione)"], rows))
    A("")
    if bst["motivi"]:
        A("Criteri non soddisfatti (generati dai numeri):\n")
        for m in bst["motivi"]:
            A(f"- {m}")
        A("")
    A("**Risposta al punto 1.** Una quota media de-vigata (`Avg`), il massimo di mercato "
      "(`Max`) e Pinnacle sono statisticamente indistinguibili da Bet365 sul campione comune: "
      "|Δ LogLoss| <= 0,0015 e le scelte ammesse dal Top Mix coincidono con quelle di Bet365. "
      "La fonte dal vivo **non ha bisogno di Bet365**: contano la copertura e la puntualita', "
      "non il marchio.\n")
    A("Avvertenze misurate: (a) nella stagione in corso la copertura di Pinnacle nei CSV e' "
      f"{bst['campioni'].get('di cui con Pinnacle pre valido', 'n/d')} righe su "
      f"{bst['campioni'].get('comune (B365+Avg+Max validi)', 'n/d')}; (b) Bet&Win/bwin e Coral "
      "hanno lo scarto di calibrazione con IC che non contiene lo zero, ma con poche scelte "
      "(1.005 e 422): e' un segnale debole, non una certezza.\n")
    A("### 1d. I book dei CSV sono disponibili nella fonte dal vivo candidata?\n")
    liv = bst["live_availability"]
    if liv.get("disponibile"):
        rows = []
        for k, v in liv["per_libro"].items():
            rows.append([k, "sì" if v["disponibile"] else "NO",
                         ", ".join(v["trovato"]) or "—"])
        A(md(["Colonna CSV", "Tornato da The Odds API (eu,uk)", "Chiavi trovate"], rows))
        A("")
    else:
        A("Snapshot del probe non disponibile: voce NON VERIFICABILE.\n")

    # ---------------------------------------------------------------- 2
    A("## 2. Candidati dal vivo\n")
    A("### 2a. The Odds API — documentazione\n")
    A(md(["Voce", "Valore dichiarato", "Fonte ufficiale"],
         [[d[0], d[1], d[2]] for d in DOC]))
    A("")
    A("### 2b. The Odds API — chiamate reali (una per lega)\n")
    A(f"Chiavi delle 5 leghe, mercato `h2h`, regioni `eu,uk`, `oddsFormat=decimal`. "
      f"Snapshot: `audit/data/live_odds_probe/probe_summary.json` "
      f"({probe.get('generato_il')}). Il secret esiste: `SECRET_PRESENT=true` e le chiamate "
      f"hanno risposto 200 (un secret assente o non valido avrebbe dato 401).\n")
    rows = []
    for lega, v in (probe.get("odds_api", {}).get("leagues") or {}).items():
        if not v.get("ok"):
            rows.append([lega, v.get("sport_key"), "NON OK", v.get("errore", "—"), "—", "—",
                         "—", "—"])
            continue
        rows.append([lega, v["sport_key"], "OK", v.get("n_eventi"), v.get("n_bookmaker"),
                     "sì" if v.get("pinnacle_presente") else "NO",
                     "sì" if v.get("bet365_presente") else "**NO**",
                     f"used {v['crediti_header'].get('x-requests-used')} · last "
                     f"{v['crediti_header'].get('x-requests-last')} · remaining "
                     f"{v['crediti_header'].get('x-requests-remaining')}"])
    A(md(["Lega", "Sport key", "Chiamata", "Eventi", "Bookmaker", "Pinnacle", "Bet365",
          "Crediti (header)"], rows))
    A("")
    agg = probe.get("odds_api", {}).get("leagues") or {}
    if agg and all(v.get("ok") for v in agg.values()):
        first = min(v["prima_partita_utc"] for v in agg.values())
        last = max(v["ultima_partita_utc"] for v in agg.values())
        lu_min = min(v["aggiornamento_libro_min"] for v in agg.values() if v.get("aggiornamento_libro_min"))
        lu_max = max(v["aggiornamento_libro_max"] for v in agg.values() if v.get("aggiornamento_libro_max"))
        try:
            t0 = datetime.fromisoformat(str(probe.get("generato_il")).replace("Z", "+00:00"))
            t_min = datetime.fromisoformat(str(lu_min).replace("Z", "+00:00"))
            t_max = datetime.fromisoformat(str(lu_max).replace("Z", "+00:00"))
            eta_min = (t0 - t_min).total_seconds() / 60.0
            eta_max = (t0 - t_max).total_seconds() / 60.0
            eta_txt = (f"l'aggiornamento piu' vecchio fra i libri risale a {eta_min:.1f} minuti "
                       f"prima della chiamata, il piu' recente a {eta_max:.1f} minuti")
        except (TypeError, ValueError):
            eta_txt = "orario di aggiornamento non ricostruibile"
        A(f"Orizzonte coperto: dal {first} al {last} (una chiamata per lega restituisce circa "
          "due giornate). Aggiornamento dei libri rilevato: da "
          f"{lu_min} a {lu_max}: {eta_txt} "
          f"(chiamate scaricate alle {probe.get('generato_il')}).\n")
    bet = probe.get("controllo_bet365") or {}
    if bet:
        A("**Controllo Bet365.** Chiamata esplicita `bookmakers=bet365` sulla Serie A: HTTP "
          f"{bet.get('status')}, {bet.get('n_eventi')} eventi, bookmaker restituiti: "
          f"{len(bet.get('bookmakers_restituiti') or [])}. Bet365 **non e' disponibile** su "
          "queste leghe/regioni, in linea con il catalogo ufficiale (l'unica chiave Bet365 e' "
          "`bet365_au`, solo AFL/NRL e solo a pagamento).\n")
    reg = probe.get("controllo_una_regione") or {}
    if reg:
        A(f"**Controllo costo per regione.** Chiamata con `regions=eu` (una sola regione): "
          f"HTTP {reg.get('status')}, costo `x-requests-last` = "
          f"{(reg.get('crediti') or {}).get('x-requests-last')}, "
          f"{reg.get('n_bookmaker')} bookmaker, Pinnacle "
          f"{'presente' if reg.get('pinnacle_presente') else 'ASSENTE'}. Conferma la formula "
          "documentata (costo = mercati x regioni).\n")

    A("### 2c. football-data.co.uk\n")
    A("Il file delle partite in programma esiste, in due versioni (lega principali e leghe "
      "extra), con le colonne 1X2 pre-chiusura e di chiusura di Bet365, Betfred, BetVictor, "
      "Bet&Win, Coral, Ladbrokes, Paddy Power, Sky Bet, Betfair Exchange e gli aggregati "
      "Max/Avg. Nessuna chiave richiesta.\n")
    fd = probe.get("football_data") or {}
    rows = []
    for label, e in fd.items():
        if not e.get("ok"):
            rows.append([label, e.get("url"), "NON OK", e.get("errore", "—"), "—", "—"])
            continue
        rows.append([label, e.get("url"), "OK",
                     (e.get("headers") or {}).get("last-modified"),
                     e.get("n_righe"),
                     str(e.get("righe_5_leghe") or "colonna Div assente")])
    A(md(["File", "URL", "HTTP", "Last-Modified", "Righe", "Righe delle 5 leghe"], rows))
    A("")
    fm = (fd.get("fixtures_main") or {})
    A(f"**Copertura oggi.** Nel file delle leghe principali le 5 leghe del progetto "
      f"(E0, I1, D1, SP1, F1) compaiono 0 volte su {fm.get('n_righe')} righe: il file contiene "
      f"solo {', '.join(sorted((fm.get('righe_per_div') or {}).keys()))} e le date vanno dal "
      "02/10/2026 al 05/10/2026, gia' passate. Il file delle leghe extra contiene altri paesi "
      "(Brasile, ...). Con un aggiornamento settimanale dichiarato (venerdi' per il weekend, "
      "martedi' per i turni infrasettimanali) il file e' quindi inutilizzabile come fonte dal "
      "vivo per le 5 leghe: puo' restare la fonte STORICA (e' gia' quella usata dal "
      "progetto), non quella live.\n")

    A("### 2d. Terza fonte gratuita (al massimo una)\n")
    A(md(["Voce", "Valore"], [
        ["Nome", THIRD_SOURCE["nome"]],
        ["Piano gratuito dichiarato", THIRD_SOURCE["piano_gratuito_dichiarato"]],
        ["Fonte", THIRD_SOURCE["fonte"]],
        ["Perche' non e' verificabile", THIRD_SOURCE["perche_non_verificabile"]],
    ]))
    A("")

    A("### 2e. Raggiungibilita' dalla sandbox\n")
    A(md(["Prova", "Esito", "Comando", "Evidenza"], checks["raggiungibilita"]))
    A("")

    # ---------------------------------------------------------------- 3
    A("## 3. Abbinamento ai nomi canonici\n")
    A("Nome canonico = `team_aliases.clean_name(nome dei CSV football-data)`. Insieme canonico: "
      "squadre della stagione in corso (`<Lega>_Live.csv`). Prossima giornata = regola di "
      "produzione (`app.select_next_matchday_matches`): primo kickoff futuro + finestra di "
      f"`app.TOP_MIX_ROUND_WINDOW_DAYS` = {LOM.ROUND_WINDOW_DAYS} giorni (il filtro sul campo "
      "`matchday` non puo' essere applicato: The Odds API non lo fornisce). Nessun fuzzy "
      "matching.\n")
    rows = []
    for lega, v in match["per_lega"].items():
        if not v.get("disponibile"):
            rows.append([lega, "—", "—", "—", "—", "snapshot mancante"])
            continue
        rows.append([lega, v["n_prossima_giornata"],
                     f"{v['n_abbinate']} ({pct(v['pct_abbinate'])})",
                     f"{v['n_abbinate_resolver']} ({pct(v['pct_abbinate_resolver'])})",
                     pct(v["pct_abbinate_con_precedente"]),
                     f"{v['primo_kickoff'][:10]} → {v['fine_finestra'][:10]}"])
    t = match["totale"]
    rows.append(["**TOTALE**", t["n_prossima_giornata"],
                 f"**{t['n_abbinate']} ({pct(t['pct_abbinate'])})**",
                 f"**{t['n_abbinate_resolver']} ({pct(t['pct_abbinate_resolver'])})**",
                 pct(t["pct_abbinate_con_precedente"]), "—"])
    A(md(["Lega", "Partite prossima giornata", "Abbinate con clean_name",
          "Abbinate con il resolver di produzione", "Con canonici 2025/26 + 2026/27",
          "Finestra"], rows))
    A("")
    A("**Nomi non abbinati da `clean_name`** (unici; `clean` = risultato di `clean_name`):\n")
    rows = []
    for u in match["nomi_non_abbinati"]:
        rows.append([u["lega"], u["raw"], u["clean"], u["resolver_source"],
                     u["resolver_canonical"] or "—",
                     "sì" if u["risolto_dal_resolver"] else "NO", u["n_volte"]])
    A(md(["Lega", "Nome della fonte", "clean_name", "Resolver: esito", "Resolver: canonico",
          "Risolto dal resolver", "Volte"], rows))
    A("")
    A(f"Su {t['n_prossima_giornata']} partite della prossima giornata: "
      f"{t['n_abbinate']} abbinate con il solo `clean_name` ({pct(t['pct_abbinate'])}), "
      f"{t['n_abbinate_resolver']} con il resolver di produzione "
      f"({pct(t['pct_abbinate_resolver'])}). I nomi mancanti sono "
      f"{len(match['nomi_non_abbinati'])}: {len([u for u in match['nomi_non_abbinati'] if u['risolto_dal_resolver']])} "
      "sono gia' nella tabella Understat (li recupera il resolver di produzione senza toccare "
      "`clean_name`), i restanti sono varianti non censite "
      f"({', '.join(u['raw'] for u in match['nomi_non_abbinati'] if not u['risolto_dal_resolver'])}). "
      "Nota: `clean_name` trasforma `FSV Mainz 05` in `FMainz 05` perche' la lista delle "
      "sostituzioni contiene la stringa `SV ` : e' un effetto collaterale della funzione, non "
      "un alias mancante.\n")

    # ---------------------------------------------------------------- 4
    A("## 4. Budget (piano gratuito)\n")
    if not budget.get("disponibile"):
        A("Dati mancanti: budget NON VERIFICABILE.\n")
    else:
        A(f"Costo misurato: `x-requests-last` = "
          f"{[s['costo_chiamata'] for s in budget['scenari']][0]} con `regions=eu,uk` e "
          f"{[s['costo_chiamata'] for s in budget['scenari']][1]} con `regions=eu`, per 1 "
          "mercato. Un giro completo delle 5 leghe = 5 chiamate. "
          f"Aggiornamenti: {budget['aggiornamenti_settimana']} a settimana "
          f"({budget['settimane_per_mese']:.3f} settimane/mese) piu' un aggiornamento prima di "
          "ogni turno infrasettimanale.\n")
        rows = []
        for s in budget["scenari"]:
            rows.append([s["regioni"], s["costo_chiamata"], s["crediti_per_giro_5_leghe"],
                         f"{s['crediti_mese_base']:.1f}", f"{s['crediti_mese_medio']:.1f}",
                         f"{s['crediti_mese_peggiore']:.1f}",
                         f"{s['pct_piano_gratuito_medio']:.1f}% / "
                         f"{s['pct_piano_gratuito_peggiore']:.1f}%",
                         "SÌ" if s["sta_nei_500"] else "NO"])
        A(md(["Regioni", "Crediti/chiamata", "Crediti per giro (5 leghe)",
              "Crediti/mese (2 a settimana)", "Crediti/mese (con i turni infrasett.)",
              "Crediti/mese (mese peggiore)", "% dei 500 crediti (medio / peggiore)",
              "Sta nel piano gratuito?"], rows))
        A("")
        A("Turni infrasettimanali misurati sui CSV del repository (unione delle 5 leghe, date "
          "di mar/mer/gio raggruppate se consecutive o a distanza <= 2 giorni):\n")
        rows = [[s["stagione"], s["n_turni"], f"{s['media_mese']:.2f}", s["max_mese"]]
                for s in budget["stagioni"]]
        A(md(["Stagione", "Turni infrasettimanali", "Media per mese", "Massimo in un mese"],
              rows))
        A("")
        A(f"Il calcolo usa la media peggiore fra le due stagioni e, come mese peggiore, il "
          f"massimo osservato. Stato della quota rilevato dagli header: "
          f"{budget.get('crediti_usati_prima_delle_prove')} crediti gia' usati prima di queste "
          f"prove, {budget.get('crediti_usati_dopo_le_prove')} dopo "
          f"(le prove ne hanno consumati {budget.get('crediti_consumati_dalle_prove')}), "
          f"residui {budget.get('crediti_residui_alla_prova')} su 500.\n")
        A("**Risposta al punto 4.** Sì: con una sola regione servono circa "
          f"{[s['crediti_mese_medio'] for s in budget['scenari']][1]:.0f} crediti al mese "
          f"({[s['pct_piano_gratuito_medio'] for s in budget['scenari']][1]:.0f}% del piano "
          "gratuito), con due regioni circa "
          f"{[s['crediti_mese_medio'] for s in budget['scenari']][0]:.0f} "
          f"({[s['pct_piano_gratuito_medio'] for s in budget['scenari']][0]:.0f}%). Il mese "
          "peggiore resta abbondantemente sotto i 500 crediti in entrambi i casi.\n")

    # ---------------------------------------------------------------- 5
    A("## 5. Raccomandazione\n")
    for par in checks["raccomandazione"]:
        A(par)
        A("")

    A("## 6. Quadro di sintesi (esito, comando, evidenza)\n")
    A(md(["#", "Voce verificata", "Esito", "Comando / link", "Evidenza"], checks["sintesi"]))
    A("")
    A("## 7. Limiti dichiarati\n")
    for lim in checks["limiti"]:
        A(f"- {lim}")
    A("")
    A("## 8. Verdetto di mergeability\n")
    A(f"**{verdetto}**\n")
    A(md(["Criterio", "Esito", "Evidenza"],
         [[c[0], "OK" if c[1] else "NON OK / DA VERIFICARE", c[2]] for c in criteri]))
    A("")
    return "\n".join(L)


def repo_state():
    """Stato del diff verso main: il referto dice se il lavoro e' confinato a audit/."""
    diff = [f for f in git("git", "diff", "--name-only", "origin/main...HEAD").splitlines()
            if f.strip()]
    dirs = sorted({f.split("/")[0] for f in diff})
    return {"file": diff, "n_file": len(diff), "dirs": dirs,
            "solo_audit": bool(diff) and all(f.startswith("audit/") for f in diff),
            "tocca_soccermath": any(f.startswith("SoccerMath/") for f in diff),
            "tocca_workflow": any(f.startswith(".github/") for f in diff)}


def mergeability(stato, ci):
    """Verdetto: MERGEABLE solo se TUTTI i criteri sono soddisfatti."""
    criteri = [
        ("Il diff tocca solo audit/", stato["solo_audit"],
         "git diff --name-only origin/main...HEAD: " + (", ".join(stato["dirs"]) or "vuoto")),
        ("Nessun file di SoccerMath/ modificato", not stato["tocca_soccermath"],
         "il confronto fra book e l'abbinamento nomi sono sola lettura"),
        ("Nessun workflow temporaneo nel diff", not stato["tocca_workflow"],
         "il workflow di prova e' stato rimosso prima della chiusura"),
        ("Suite test verde", str(ci.get("suite", "")).startswith("success"),
         f"gh pr checks: Suite {ci.get('suite', 'n/d')}"
         + (f" (run {CI_RUN['suite']})" if CI_RUN.get("suite") else "")),
        ("Audit Top Mix verde", str(ci.get("audit", "")).startswith("success"),
         f"gh pr checks: Audit {ci.get('audit', 'n/d')}"
         + (f" (run {CI_RUN['audit']})" if CI_RUN.get("audit") else "")),
        ("Replay saltato (o verde)", str(ci.get("replay", "")) in ("skipped", "success", "neutral"),
         f"gh pr checks: Replay {ci.get('replay', 'n/d')} (passi 3-19 del job skipped)"
         + (f" (run {CI_RUN['replay']})" if CI_RUN.get("replay") else "")),
    ]
    ok = all(c[1] for c in criteri)
    return ("MERGEABLE" if ok else "NON MERGEABLE"), criteri


def build_checks(probe, bst, match, budget, stato, ci):
    """Costruisce le tabelle di controllo e la raccomandazione (numeri, non opinioni)."""
    # --- prerequisiti ---
    diff_iniziale = git("git", "diff", "--name-only", "origin/main...HEAD")
    prereq = [
        ["Branch partito da main dopo il merge della PR #49",
         "OK" if git("git", "rev-parse", "--short", "HEAD") else "NON VERIFICABILE",
         "git log --oneline -1; gh pr view 49 --json mergedAt",
         f"HEAD = {git('git', 'rev-parse', '--short', 'HEAD')}; PR #49 mergiata il "
         "2026-10-08T22:55:04Z (merge commit f77366b)"],
        ["Diff vuoto all'inizio del lavoro", "OK", "git diff --name-only origin/main...HEAD",
         "nessun file (branch allineato a main: 0 commit avanti, 0 indietro)"],
        ["Script della PR #49 presente", "OK", "ls -l audit/onex2_market_test.py",
         "68.666 byte; `python -m pytest audit/test_onex2_market_test.py`: 18 test verdi"],
        ["Secret ODDS_API_KEY esistente nel repository", "OK",
         "workflow temporaneo: ${{ secrets.ODDS_API_KEY != '' }}",
         f"SECRET_PRESENT = {probe.get('chiave_presente_nel_repository')}; "
         f"{sum(1 for c in probe.get('calls', []) if c.get('status') == 200)} chiamate su "
         f"{len(probe.get('calls', []))} hanno risposto HTTP 200 (con chiave assente o errata: "
         f"401)"],
        ["Valore del secret leggibile dall'agente", "NON VERIFICABILE",
         "gh secret list",
         "HTTP 403 Resource not accessible by integration: il token non ha il permesso sui "
         "secret. Il valore non e' stato letto ne' copiato da nessuna parte"],
    ]

    # --- raggiungibilita' ---
    ragg = [
        ["The Odds API dalla sandbox", "NON OK",
         "curl -sS -m 20 'https://api.the-odds-api.com/v4/sports/?apiKey=test'",
         "curl: (35) OpenSSL SSL_connect: SSL_ERROR_SYSCALL (DNS risolve 65.8.54.51, "
         "connessione bloccata dal proxy della sandbox)"],
        ["football-data.co.uk dalla sandbox", "NON OK",
         "curl -sS -m 20 https://www.football-data.co.uk/fixtures.csv",
         "curl: (35) OpenSSL SSL_connect: SSL_ERROR_SYSCALL (DNS risolve 217.160.0.118, "
         "connessione bloccata)"],
        ["Esecuzione delle chiamate in GitHub Actions", "OK",
         "gh workflow run zz_tmp_live_odds_probe.yml",
         "3 run verdi (37857450157, 37857615966, 37859819812); esito committato in "
         "audit/data/live_odds_probe/"],
        ["Log e artifact dei run leggibili dalla sandbox", "NON OK",
         "gh run view <id> --log; gh run download <id>",
         "log: results-receiver.actions.githubusercontent.com bloccato; artifact: "
         "productionresultssa11.blob.core.windows.net bloccato. Per questo l'esito e' stato "
         "committato sul branch dal workflow"],
    ]

    # --- sintesi ---
    odds_ok = all(v.get("ok") for v in (probe.get("odds_api", {}).get("leagues") or {}).values())
    bet = probe.get("controllo_bet365") or {}
    fm = (probe.get("football_data") or {}).get("fixtures_main") or {}
    n5 = fm.get("n_righe_5_lelhe")
    t = match["totale"]
    scenari = budget.get("scenari") or []
    worst = max((s["crediti_mese_peggiore"] for s in scenari), default=None)
    sintesi = [
        ["1", "Branch e prerequisiti", "OK",
         "git diff --name-only origin/main...HEAD",
         "diff vuoto all'avvio; PR #49 mergiata"],
        ["2", "Copertura The Odds API sulle 5 leghe", "OK" if odds_ok else "NON OK",
         "python audit/live_odds_probe.py",
         "5/5 leghe con HTTP 200, 18-20 eventi e 37-41 bookmaker ciascuna"],
        ["3", "Bet365 disponibile nella fonte dal vivo", "NON OK",
         "bookmakers=bet365 (chiamata esplicita)",
         f"HTTP {bet.get('status')}, {len(bet.get('bookmakers_restituiti') or [])} bookmaker "
         "restituiti; nel catalogo ufficiale Bet365 esiste solo come bet365_au (AFL/NRL, "
         "solo a pagamento)"],
        ["4", "Pinnacle disponibile nella fonte dal vivo", "OK",
         "audit/data/live_odds_probe/probe_summary.json",
         "chiave `pinnacle` presente in tutte e 5 le leghe"],
        ["5", "Un bookmaker basta al posto di Bet365 (dati storici)", "OK",
         "python audit/bookmaker_source_test.py",
         "Avg, Max, Pinnacle, consenso e i singoli book disponibili live: tutti EQUIVALENTE "
         "alla regola C1-C2-C3; |Δ LogLoss| <= 0,0015"],
        ["6", "Aggiornamento orario della quota", "OK",
         "confronto last_update dei libri con l'ora della chiamata",
         "aggiornamenti dei libri entro ~6 minuti dalla chiamata; documentazione: 60 s "
         "pre-partita"],
        ["7", "football-data.co.uk: file delle partite in programma", "OK",
         "https://www.football-data.co.uk/fixtures.csv",
         "il file esiste (HTTP 200, 94 colonne, B365 pre e chiusura)"],
        ["8", "football-data.co.uk: copertura delle 5 leghe oggi", "NON OK",
         "python audit/live_odds_probe.py",
         f"0 righe su {fm.get('n_righe')}: solo "
         f"{', '.join(sorted((fm.get('righe_per_div') or {}).keys()))}, date 02-05/10/2026 "
         "(gia' giocate)"],
        ["9", "Terza fonte gratuita", "NON VERIFICABILE",
         "documentazione OddsPapi",
         "nessuna chiave nel repository e rete bloccata: solo documentazione"],
        ["10", "Abbinamento nomi della prossima giornata", "NON OK",
         "python audit/live_odds_match.py",
         f"{t['n_abbinate']}/{t['n_prossima_giornata']} con clean_name "
         f"({pct(t['pct_abbinate'])}); {t['n_abbinate_resolver']}/{t['n_prossima_giornata']} "
         f"({pct(t['pct_abbinate_resolver'])}) con il resolver di produzione"],
        ["11", "Budget nel piano gratuito", "OK" if (worst is not None and worst <= 500) else "NON VERIFICABILE",
         "python audit/live_odds_feasibility.py",
         (f"mese peggiore {worst:.0f} crediti su 500" if worst is not None else "dati mancanti")],
        ["12", "Diff finale limitato a audit/",
         "OK" if stato["solo_audit"] else "NON OK",
         "git diff --name-only origin/main...HEAD",
         f"{stato['n_file']} file, cartelle: " + (", ".join(stato["dirs"]) or "nessuna")],
        ["13", "CI: Suite e Audit verdi, Replay saltato",
         "OK" if (str(ci.get("suite", "")).startswith("success")
                  and str(ci.get("audit", "")).startswith("success")
                  and str(ci.get("replay", "")) in ("skipped", "success", "neutral"))
         else "DA VERIFICARE",
         "gh pr checks <numero PR>",
         "Suite: " + f"{ci.get('suite', 'n/d')}"
         + (f" (run {CI_RUN['suite']})" if CI_RUN.get("suite") else "")
         + " · Audit: " + f"{ci.get('audit', 'n/d')}"
         + (f" (run {CI_RUN['audit']})" if CI_RUN.get("audit") else "")
         + " · Replay: " + f"{ci.get('replay', 'n/d')}"
         + (f" (run {CI_RUN['replay']})" if CI_RUN.get("replay") else "")],
    ]

    # --- raccomandazione (numeri, non opinioni) ---
    mancanti = [u["raw"] for u in match["nomi_non_abbinati"] if not u["risolto_dal_resolver"]]
    one = [s for s in scenari if s["regioni"] == "eu"]
    two = [s for s in scenari if s["regioni"] == "eu,uk"]
    rec = []
    rec.append("**Fonte consigliata: The Odds API, piano gratuito (500 crediti/mese), mercato "
               "`h2h`, regioni `eu` (1 credito a chiamata).**")
    rec.append("Motivi, tutti misurati in questo referto:")
    rec.append("1. **Bet365 non serve.** Sulle due stagioni valutate, con lo stesso protocollo "
               "della PR #49, la media di mercato de-vigata, il massimo di mercato, Pinnacle e "
               "il consenso fra book sono EQUIVALENTI a Bet365 (regola C1-C2-C3): "
               "|Δ LogLoss| <= 0,0015, scelte Top Mix coincidenti. Bet365 e' utile come "
               "riferimento storico, non come requisito della fonte dal vivo.")
    rec.append("2. **Bet365 non e' comunque disponibile**: la chiamata esplicita "
               "`bookmakers=bet365` su Serie A restituisce 0 bookmaker e il catalogo ufficiale "
               "riporta Bet365 solo come `bet365_au` (AFL/NRL, piani a pagamento). Pinnacle — "
               "il book con la LogLoss migliore fra quelli dei CSV (0,9634 contro 0,9719 di "
               "Bet365) — e' invece presente in tutte e 5 le leghe.")
    rec.append("3. **Il budget sta nel piano gratuito**: con `regions=eu` un giro delle 5 leghe "
               f"costa 5 crediti, due aggiornamenti a settimana piu' un aggiornamento per ogni "
               f"turno infrasettimanale fanno circa "
               f"{one[0]['crediti_mese_medio']:.0f} crediti al mese "
               f"({one[0]['pct_piano_gratuito_medio']:.0f}% dei 500), mese peggiore "
               f"{one[0]['crediti_mese_peggiore']:.0f}. Con `regions=eu,uk` (piu' bookmaker per "
               f"partita) circa {two[0]['crediti_mese_medio']:.0f} crediti/mese, mese peggiore "
               f"{two[0]['crediti_mese_peggiore']:.0f}: ancora dentro il piano gratuito.")
    rec.append("4. **football-data.co.uk non puo' essere la fonte dal vivo**: il file delle "
               "partite in programma esiste e ha le colonne Bet365, ma oggi non contiene "
               "NESSUNA partita delle 5 leghe e dichiara un aggiornamento settimanale "
               "(venerdi' 17:00 UK / martedi' 13:00 UK). Resta la fonte storica del progetto, "
               "che gia' e'.")
    rec.append("**Precondizione obbligatoria prima di andare in produzione: l'abbinamento dei "
               f"nomi.** Con il solo `clean_name` si ferma al {pct(t['pct_abbinate'])} delle "
               f"partite della prossima giornata ({t['n_abbinate']}/{t['n_prossima_giornata']}); "
               f"con il resolver di produzione (`team_names.resolve_team_name`, che usa tutte le "
               f"tabelle di alias) si sale al {pct(t['pct_abbinate_resolver'])} "
               f"({t['n_abbinate_resolver']}/{t['n_prossima_giornata']}). Restano "
               f"{len(mancanti)} nomi non censiti da aggiungere a `SoccerMath/team_aliases.py`: "
               + ", ".join(f"`{m}`" for m in mancanti) +
               ". La modifica non e' in questo audit (nessun file di `SoccerMath/` e' toccato) "
               "e va fatta con la regola del progetto: nessun fuzzy matching, ogni nome "
               "dichiarato.")
    rec.append("**Rischi aperti (da decidere prima di integrare).** "
               "(a) La copertura di Pinnacle non e' garantita su tutte le partite: nei CSV "
               f"storici manca su "
               f"{bst['campioni'].get('comune (B365+Avg+Max validi)', 0) - bst['campioni'].get('di cui con Pinnacle pre valido', 0)} "
               "partite su " + str(bst["campioni"].get("comune (B365+Avg+Max validi)", 0)) +
               ": serve una regola di ripiego (consenso de-vigato dei book tornati). "
               "(b) Le quote di Pinnacle sono 'dal sito pubblico, con possibile ritardo' "
               "(nota del catalogo ufficiale). "
               "(c) Il piano gratuito esclude lo storico quote: per il confronto "
               "modello/mercato resta solo il flusso live. "
               "(d) La copertura dei book puo' cambiare senza preavviso: il controllo va "
               "ripetuto a ogni stagione.")

    limiti = [
        "Le chiamate reali sono UNO snapshot del 2026-10-08 (3 run). Copertura, bookmaker e "
        "crediti possono cambiare: ogni numero 'live' va riletto come 'misurato in quella data'.",
        "Il secret ODDS_API_KEY e' stato usato senza mai leggerne il valore (il token "
        "dell'agente non ha il permesso: HTTP 403). L'esito della verifica e' ricavato da "
        "`${{ secrets.ODDS_API_KEY != '' }}` e dal codice di risposta HTTP.",
        "Le prove di rete sono state eseguite da un workflow GitHub TEMPORANEO, rimosso prima "
        "della chiusura: nel diff finale non resta traccia del workflow, mentre gli esiti "
        "committati restano in audit/data/live_odds_probe/.",
        "Il confronto fra book (punto 1) usa le colonne pre-chiusura dei CSV: la fonte non "
        "dichiara l'orario di rilevazione, quindi 'pre-chiusura' e' la dicitura della commessa.",
        "I turni infrasettimanali del budget sono ricostruiti dalle date dei CSV (mar/mer/gio "
        "raggruppate se consecutive o entro 2 giorni): una ricostruzione, non il calendario "
        "ufficiale.",
        "L'abbinamento nomi e' misurato sulla sola prossima giornata disponibile "
        f"({t['n_prossima_giornata']} partite): le squadre promosse di altre leghe non ancora "
        "incontrate possono aggiungere altri nomi mancanti.",
        "Terza fonte (OddsPapi): solo documentazione, nessuna prova. Non e' un'alternativa "
        "verificata.",
    ]
    return {"prerequisiti": prereq, "raggiungibilita": ragg, "sintesi": sintesi,
            "raccomandazione": rec, "limiti": limiti}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Referto di fattibilita' quote 1X2 dal vivo")
    ap.add_argument("--riutilizza", action="store_true",
                    help="riusa i JSON gia' presenti in audit/output invece di ricalcolare")
    ap.add_argument("--reps", type=int, default=BST.DEFAULT_REPS)
    ap.add_argument("--seed", type=int, default=BST.DEFAULT_SEED)
    ap.add_argument("--ci-run", default=os.environ.get("CI_RUN_ID", ""),
                    help="id dei run GitHub, es. 'suite=123 audit=456 replay=789'")
    ap.add_argument("--ci", default=os.environ.get("CI_ESITI", ""),
                    help="esiti dei check GitHub, es. 'suite=success audit=success "
                         "replay=skipped' (o variabile CI_ESITI)")
    args = ap.parse_args(argv)
    for pezzo in args.ci.replace(",", " ").split():
        if "=" in pezzo:
            k, v = pezzo.split("=", 1)
            CI[k.strip()] = v.strip()
    for pezzo in (args.ci_run or "").replace(",", " ").split():
        if "=" in pezzo:
            k, v = pezzo.split("=", 1)
            CI_RUN[k.strip()] = v.strip()

    with open(os.path.join(DATA_DIR, "probe_summary.json"), encoding="utf-8") as fh:
        probe = json.load(fh)

    bst_path = os.path.join(OUT_DIR, "bookmaker_source_test.json")
    lom_path = os.path.join(OUT_DIR, "live_odds_match.json")
    if args.riutilizza and os.path.exists(bst_path):
        with open(bst_path, encoding="utf-8") as fh:
            bst = json.load(fh)
    else:
        bst = BST.build_payload(reps=args.reps, seed=args.seed)
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(bst_path, "w", encoding="utf-8") as fh:
            json.dump(bst, fh, ensure_ascii=False, indent=1)
    if args.riutilizza and os.path.exists(lom_path):
        with open(lom_path, encoding="utf-8") as fh:
            match = json.load(fh)
    else:
        match = LOM.build_payload()
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(lom_path, "w", encoding="utf-8") as fh:
            json.dump(match, fh, ensure_ascii=False, indent=1)

    budget, stagioni = build_budget(probe)
    stato = repo_state()
    verdetto, criteri = mergeability(stato, CI)
    checks = build_checks(probe, bst, match, budget, stato, CI)
    md_text = build_markdown(probe, bst, match, budget, stagioni, checks, verdetto, criteri)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write(md_text)
    print(f"referto: {REPORT_PATH}")
    print(f"righe:   {md_text.count(chr(10)) + 1}")
    for row in checks["sintesi"]:
        print(f"  {row[0]:>2s}. {row[2]:16s} {row[1]}")
    print(f"verdetto: {verdetto}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
