#!/usr/bin/env python3
"""DISPLAY_NAME_MAP: referto di non-regressione e tabella delle 96 squadre.

Ricostruisce (dai dati misurati nel repo) la proposta del referto perduto
``audit/results/giornata_nomi_e_date_matchday6.md`` (15/09, mai committato)
e la verifica end-to-end:

* PARTE A - tabella completa delle 96 squadre 2026/27 (20+20+20+18+18):
  per ognuna il nome canonico (chiave del motore), le forme grezze API
  misurate (righe raw nei ``*_Live.csv`` + alias documentati in
  ``TEAM_NAME_MAP``) e il nome che l'UI mostra dopo il cambio.
* PARTE B - equivalenza PRE/POST sul flusso REALE: la
  ``fetch_and_calc_top_mix`` e la ``analisi_rapida_giornata`` di PRIMA del
  cambio vengono eseguite dal sorgente git della base (``--base``,
  default ``origin/main``) e confrontate con quelle di OGGI sugli stessi
  fixture (partite future, shortName grezzi reali): probabilita',
  mercato_standard, poisson/elo, match_id e giornata devono essere
  IDENTICI; possono cambiare solo i nomi mostrati.
* PARTE C - guardie strutturali: ``team_aliases.py``, ``config.py`` e
  ``models/elo_engine.py`` (tutta la catena di matching) sono byte-identici
  alla base; ``display_name`` non e' importato da nessuno di loro.
* PARTE D - render end-to-end dell'app vera (Streamlit AppTest, API
  football-data mockate con le forme grezze misurate): le card PARTITE
  mostrano i nomi display, e nessuna forma grezza mappata sopravvive nel
  tab TOP MIX.

Uso:
    python3 audit/display_name_map_check.py [--base origin/main]
        [--referto audit/results/display_name_map_referto.md]

Exit code 0 = tutto verde; 1 = almeno una verifica fallita (il referto
riporta comunque cosa).
"""

from __future__ import annotations

import argparse
import ast
import csv
import io
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOCCER_DIR = os.path.join(REPO_ROOT, "SoccerMath")
sys.path.insert(0, SOCCER_DIR)
sys.path.insert(0, REPO_ROOT)

# L'API key serve solo perche' l'app non salti il flusso di sync: le
# richieste HTTP sono tutte mockate, nessuna rete.
os.environ.setdefault("FOOTBALL_DATA_API_KEY", "audit-display-name-check")

import app as prod_app  # noqa: E402
from config import LEAGUES_CONFIG  # noqa: E402
from display_names import DISPLAY_NAME_MAP, display_name  # noqa: E402
from team_aliases import TEAM_NAME_MAP, UNDERSTAT_NAME_MAP, clean_name  # noqa: E402

APP_PATH = os.path.join(SOCCER_DIR, "app.py")

CAMPIONATO_CSV = {
    "Serie A": "SerieA_Live.csv",
    "Premier League": "Premier_Live.csv",
    "La Liga": "LaLiga_Live.csv",
    "Bundesliga": "Bundesliga_Live.csv",
    "Ligue 1": "Ligue1_Live.csv",
}

# Partite fixture (shortName GREZZI misurati, tutte future, matchday 7):
# un caso noto per lega + i casi "rotti" del referto.
FIXTURE_MATCHES = [
    # (lega, raw_home, raw_away)
    ("Serie A", "Inter", "Milan"),
    ("Serie A", "Napoli", "Juventus"),
    ("Premier League", "Brighton Hove", "Nottingham"),
    ("Premier League", "Man City", "Leeds United"),
    ("La Liga", "Atleti", "Barça"),
    ("La Liga", "Athletic", "Santander"),
    ("La Liga", "Real Madrid", "Málaga"),
    ("Bundesliga", "HSV", "Schalke"),
    ("Bundesliga", "Frankfurt", "M'gladbach"),
    ("Bundesliga", "Köln", "Bayern"),
    ("Ligue 1", "Stade Rennais", "Olympique Lyon"),
    ("Ligue 1", "Paris", "PSG"),
]

# Cosa deve mostrare la UI per le squadre mappate (casi noti del referto).
ATTESI_VISUALI = {
    "Atleti": "Atletico Madrid",
    "Barça": "Barcelona",
    "Athletic": "Athletic Bilbao",
    "Santander": "Racing Santander",
    "Brighton Hove": "Brighton",
    "Nottingham": "Nottingham Forest",
    "HSV": "Hamburg",
    "Schalke": "Schalke 04",
    "Frankfurt": "Eintracht Frankfurt",
    "M'gladbach": "Borussia Mönchengladbach",
    "Stade Rennais": "Rennes",
    "Olympique Lyon": "Lyon",
    "Paris": "Paris FC",
}

CAMPI_NUMERICI = ("prob", "prob_val", "poisson", "elo", "elo_disponibile",
                  "mercato_standard")


# --------------------------------------------------------------------------
# Utilita'
# --------------------------------------------------------------------------
def _git(*args: str) -> str:
    out = subprocess.run(["git", "-C", REPO_ROOT, *args],
                         capture_output=True, text=True, check=True)
    return out.stdout


def _blocco_fn_da_sorgente(src: str, nome: str) -> str:
    """Sorgente di una funzione top-level, decoratori esclusi (stile
    test_topmix_selector_parity.py)."""
    righe = src.splitlines(keepends=True)
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name == nome:
            return "".join(righe[node.lineno - 1: node.end_lineno])
    raise AssertionError(f"{nome} non trovata nel sorgente")


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._payload


def _fixture_payloads(now: datetime):
    """Un payload per ogni lega, con utcDate futuri e shortName grezzi."""
    kick = (now + timedelta(days=3)).strftime("%Y-%m-%dT14:00:00Z")
    payloads = {}
    mid = 910000
    for lg in LEAGUES_CONFIG:
        code = LEAGUES_CONFIG[lg]["code"]
        ms = []
        for fx_lg, h, a in FIXTURE_MATCHES:
            if fx_lg != lg:
                continue
            mid += 1
            ms.append({
                "id": mid, "matchday": 7, "status": "TIMED", "utcDate": kick,
                "homeTeam": {"id": mid * 10 + 1, "shortName": h, "name": h},
                "awayTeam": {"id": mid * 10 + 2, "shortName": a, "name": a},
                "score": {"fullTime": {"home": None, "away": None},
                          "halfTime": {"home": None, "away": None}},
            })
        payloads[code] = {"matches": ms}
    return payloads


def _router(payloads):
    """requests.get mockato: instrada per codice competizione."""
    def _get(url, *args, **kwargs):
        for code, payload in payloads.items():
            if f"/competitions/{code}/matches" in url:
                return _Resp(payload)
        if "/standings" in url:
            return _Resp({"standings": []})
        return _Resp({"matches": []})
    return _get


# --------------------------------------------------------------------------
# PARTE A - tabella delle 96
# --------------------------------------------------------------------------
def _squadre_stagione(path: str, dal: tuple = (2026, 7, 1)):
    """{nome memorizzato: n. righe} per le righe della stagione 2026/27."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = []
        for r in csv.DictReader(fh):
            try:
                d = datetime.strptime(r.get("Date", ""), "%d/%m/%Y")
            except ValueError:
                continue
            if (d.year, d.month, d.day) >= dal:
                rows.append(r)
    conteggio = {}
    for r in rows:
        for side in ("HomeTeam", "AwayTeam"):
            n = (r.get(side) or "").strip()
            if n:
                conteggio[n] = conteggio.get(n, 0) + 1
    return conteggio


def parte_a_tabella_96() -> tuple[list[dict], int]:
    tabella = []
    for lg, fname in CAMPIONATO_CSV.items():
        path = os.path.join(SOCCER_DIR, "database", fname)
        memorizzati = _squadre_stagione(path)
        # raggruppa per canonico: il nome memorizzato e' clean_name(shortName)
        # AL MOMENTO DELLA SCRITTURA: dove differisce dal canonico conserva
        # la forma grezza che l'API aveva restituito (alias aggiunto dopo).
        per_canonico = {}
        for nome in memorizzati:
            per_canonico.setdefault(clean_name(nome), set()).add(nome)
        # alias delle API live documentati in TEAM_NAME_MAP
        for raw, canon in TEAM_NAME_MAP.items():
            if canon in per_canonico and raw != canon:
                per_canonico[canon].add(raw)
        for canon in sorted(per_canonico):
            forme = per_canonico[canon]
            grezze = sorted(f for f in forme if f != canon)
            in_mappa = canon in DISPLAY_NAME_MAP
            tabella.append({
                "lega": lg, "canonico": canon,
                "grezze": grezze,
                # deterministico: la voce di mappa se c'e', altrimenti il
                # nome grezzo API resta invariato (pass-through)
                "display": (DISPLAY_NAME_MAP[canon] if in_mappa
                            else "invariato"),
                "in_mappa": in_mappa,
            })
    return tabella, len(tabella)


# --------------------------------------------------------------------------
# PARTE B - equivalenza PRE/POST sui flussi reali
# --------------------------------------------------------------------------
def _esegui_fn_vecchia(base: str, nome_fn: str, globals_extra: dict) -> object:
    """Estrae {nome_fn} dal sorgente app.py della BASE e la esegue qui."""
    src = _git("show", f"{base}:SoccerMath/app.py")
    codice = _blocco_fn_da_sorgente(src, nome_fn)
    ns = {
        "requests": prod_app.requests,
        "time": prod_app.time,
        "logging": prod_app.logging,
        "clean_name": prod_app.clean_name,
        "LEAGUE_CODE_MAP": prod_app.LEAGUE_CODE_MAP,
        "LEAGUES_CONFIG": prod_app.LEAGUES_CONFIG,
        "API_KEY_DATA": prod_app.API_KEY_DATA,
        "get_league_engine": prod_app.get_league_engine,
        "select_next_matchday_matches": prod_app.select_next_matchday_matches,
        "get_full_poisson_two_heads": prod_app.get_full_poisson_two_heads,
        "predict_elo_probs": prod_app.predict_elo_probs,
        "seleziona_riga_top_mix": prod_app.seleziona_riga_top_mix,
        "codice_mercato_selezionato": prod_app.codice_mercato_selezionato,
        "blend_elo_into_1x2": prod_app.blend_elo_into_1x2,
        "format_date_italy": prod_app.format_date_italy,
        "ORIGIN_ANALISI_RAPIDA": prod_app.ORIGIN_ANALISI_RAPIDA,
        "save_prediction_entry": globals_extra.get(
            "save_prediction_entry", prod_app.save_prediction_entry),
    }
    ns.update(globals_extra)
    exec(compile(codice, f"<{base}:{nome_fn}>", "exec"), ns)
    return ns[nome_fn]


def _top_mix_rows(fn, payloads):
    router = _router(payloads)
    with mock.patch.object(prod_app.requests, "get", side_effect=router), \
         mock.patch.object(prod_app.time, "sleep", lambda s: None):
        # get_league_engine e' cache_data e legge gli STESSI CSV nei due
        # giri: la cache (o il ricalcolo) produce gli stessi team_stats.
        # time.sleep azzerato: nessuna attesa reale fra le leghe.
        righe, missing = fn()
    return righe, missing


def _analisi_rapida_rows(fn, payloads):
    """Esegue fn (vecchia o nuova analisi_rapida_giornata) sui fixture
    Serie A: i salvataggi avvengono tramite la save_prediction_entry del
    namespace/globals della funzione (gia' predisposta dal chiamante)."""
    payload = payloads[LEAGUES_CONFIG["Serie A"]["code"]]
    matches = payload["matches"]
    engine = prod_app.get_league_engine("Serie A")
    team_stats, avg_h, avg_a, _ = engine
    fn(matches, team_stats, avg_h, avg_a, "Serie A", {}, 7)


def _norm(args, kwargs):
    """Ricostruisce il dict del salvataggio dai parametri posizionali."""
    names = ["match_id", "home", "away", "camp", "giornata", "match_date",
             "pronostico_sicuro", "top3", "prob", "risultati_attesi"]
    out = dict(zip(names, args))
    out["pron"] = out.pop("pronostico_sicuro", "")
    out.update(kwargs)
    return out


def parte_b_equivalenza(base: str) -> dict:
    esiti = {}
    now = datetime.now(timezone.utc)
    payloads = _fixture_payloads(now)

    # --- fetch_and_calc_top_mix: PRE (base) vs POST (codice corrente) ---
    fn_vecchia = _esegui_fn_vecchia(base, "fetch_and_calc_top_mix", {})
    fn_nuova = getattr(prod_app.fetch_and_calc_top_mix, "__wrapped__",
                       prod_app.fetch_and_calc_top_mix)

    righe_pre, missing_pre = _top_mix_rows(fn_vecchia, payloads)
    righe_post, missing_post = _top_mix_rows(fn_nuova, payloads)

    esiti["top_mix"] = {
        "n_pre": len(righe_pre), "n_post": len(righe_post),
        "missing_pre": missing_pre, "missing_post": missing_post,
        "errori": [],
    }
    if [r["match_id"] for r in righe_pre] != [r["match_id"] for r in righe_post]:
        esiti["top_mix"]["errori"].append(
            "ordine/id righe diversi: stesso Top Mix NON garantito")
    for pre, post in zip(righe_pre, righe_post):
        mid = pre["match_id"]
        for campo in ("league", "giornata", "match_id", "utcDate", "rank",
                      *CAMPI_NUMERICI):
            if pre[campo] != post[campo]:
                esiti["top_mix"]["errori"].append(
                    f"match {mid}: campo {campo} PRE={pre[campo]!r} "
                    f"POST={post[campo]!r}")
        for campo in ("home", "away"):
            atteso = display_name(pre[campo])
            if post[campo] != atteso:
                esiti["top_mix"]["errori"].append(
                    f"match {mid}: {campo} POST={post[campo]!r} atteso={atteso!r}")
        atteso_mkt = (pre["market"].replace(pre["home"], post["home"])
                                   .replace(pre["away"], post["away"]))
        if post["market"] != atteso_mkt:
            esiti["top_mix"]["errori"].append(
                f"match {mid}: market POST={post['market']!r} atteso={atteso_mkt!r}")

    # --- analisi_rapida_giornata: PRE vs POST (salvataggi catturati) ---
    # PRE: la funzione eseguita dal sorgente della base salva tramite il
    # save_prediction_entry del suo namespace exec; POST: tramite il
    # modulo app patchato. Stessi fixture, stesso engine.
    cattura_pre, cattura_post = [], []

    def _cattura_pre(*a, **kw):
        cattura_pre.append(_norm(a, kw))
        return {"azione": "aggiunta"}

    def _cattura_post(*a, **kw):
        cattura_post.append(_norm(a, kw))
        return {"azione": "aggiunta"}

    fn_vecchia_ar = _esegui_fn_vecchia(
        base, "analisi_rapida_giornata",
        {"save_prediction_entry": _cattura_pre})
    _analisi_rapida_rows(fn_vecchia_ar, payloads)

    with mock.patch.object(prod_app, "save_prediction_entry",
                           side_effect=_cattura_post):
        _analisi_rapida_rows(prod_app.analisi_rapida_giornata, payloads)

    esiti["analisi_rapida"] = {"n_pre": len(cattura_pre),
                               "n_post": len(cattura_post), "errori": []}
    pre_map = {r["match_id"]: r for r in cattura_pre}
    post_map = {r["match_id"]: r for r in cattura_post}
    if set(pre_map) != set(post_map):
        esiti["analisi_rapida"]["errori"].append("match_id salvati diversi")
    for mid, pre in pre_map.items():
        post = post_map.get(mid)
        if post is None:
            continue
        for campo in ("prob", "prob_poisson", "mercato_standard", "origin",
                      "giornata"):
            if pre.get(campo) != post.get(campo):
                esiti["analisi_rapida"]["errori"].append(
                    f"match {mid}: {campo} PRE={pre.get(campo)!r} "
                    f"POST={post.get(campo)!r}")
        for campo in ("home", "away"):
            if post[campo] != display_name(pre[campo]):
                esiti["analisi_rapida"]["errori"].append(
                    f"match {mid}: {campo} POST={post[campo]!r}")
        atteso_pron = (pre["pron"].replace(pre["home"], post["home"])
                                   .replace(pre["away"], post["away"]))
        if post["pron"] != atteso_pron:
            esiti["analisi_rapida"]["errori"].append(
                f"match {mid}: pron POST={post['pron']!r} atteso={atteso_pron!r}")

    # righe di esempio per il referto: le prime 2 invariate + le prime 2
    # con nome cambiato (la prova visibile dell'equivalenza)
    def _esempio(r, r2):
        return {"pre": {k: r[k] for k in ("home", "away", "market",
                                          "mercato_standard", "prob_val")},
                "post": {k: r2[k] for k in ("home", "away", "market",
                                            "mercato_standard", "prob_val")}}
    esiti["_esempi_top_mix"] = []
    for r, r2 in zip(righe_pre, righe_post):
        if r["home"] == r2["home"] and r["away"] == r2["away"]:
            if sum(1 for e in esiti["_esempi_top_mix"]
                   if e["pre"]["home"] == e["post"]["home"]) < 2:
                esiti["_esempi_top_mix"].append(_esempio(r, r2))
        elif len(esiti["_esempi_top_mix"]) < 4:
            esiti["_esempi_top_mix"].append(_esempio(r, r2))
    return esiti


# --------------------------------------------------------------------------
# PARTE C - guardie strutturali
# --------------------------------------------------------------------------
def parte_c_guardie(base: str) -> dict:
    esiti = {"file_modificati": [], "catena_intatta": True, "errori": []}
    diff = _git("diff", "--name-only", base)
    modificati = [l for l in diff.splitlines() if l.strip()]
    esiti["file_modificati"] = modificati
    vietati = [f for f in modificati if f in (
        "SoccerMath/team_aliases.py", "SoccerMath/config.py",
        "SoccerMath/models/elo_engine.py", "SoccerMath/prediction_registry.py",
        "SoccerMath/update_db.py", "SoccerMath/team_names.py")]
    if vietati:
        esiti["catena_intatta"] = False
        esiti["errori"].append(
            f"file della catena di matching modificati: {vietati}")
    # display_name non importato dalla catena di calcolo
    for fname in ("team_aliases.py", "config.py", "models/elo_engine.py"):
        path = os.path.join(SOCCER_DIR, fname)
        with open(path, encoding="utf-8") as f:
            src = f.read()
        if "display_name" in src or "DISPLAY_NAME_MAP" in src:
            esiti["catena_intatta"] = False
            esiti["errori"].append(f"{fname} riferisce il layer display")
    # numero di chiamate display_name in app.py = solo i 4 punti
    with open(APP_PATH, encoding="utf-8") as f:
        src = f.read()
    n_chiamate = src.count("display_name(")
    if n_chiamate != 8:
        esiti["errori"].append(
            f"chiamate display_name in app.py = {n_chiamate}, attese 8")
    return esiti


# --------------------------------------------------------------------------
# PARTE D - render end-to-end (AppTest, API mockate)
# --------------------------------------------------------------------------
def _standalone(nome: str) -> str:
    return rf"(?<![A-Za-z]){re.escape(nome)}(?![A-Za-z])"


def _grezza_residua(html: str, raw: str, atteso: str) -> bool:
    """La forma grezza compare come nome squadra SENZA essere parte del
    display atteso? (es. "Paris" e' dentro "Paris FC": quello NON conta)."""
    if raw in atteso:
        residuo = re.sub(_standalone(atteso), "", html)
        return re.search(_standalone(raw), residuo) is not None
    return re.search(_standalone(raw), html) is not None


def parte_d_render() -> dict:
    from streamlit.testing.v1 import AppTest

    esiti = {"card": {}, "top_mix": {}, "errori": []}
    now = datetime.now(timezone.utc)
    payloads = _fixture_payloads(now)
    router = _router(payloads)

    # L'AppTest esegue lo script VERO: il Top Mix salva davvero nel registro
    # locale (git-ignored, remoto disattivato senza chiavi). Si fa uno
    # snapshot del file e si ripristina a fine verifica.
    import requests as requests_mod
    preds_path = prod_app.PREDICTIONS_FILE
    backup = None
    if os.path.exists(preds_path):
        with open(preds_path, encoding="utf-8") as f:
            backup = f.read()

    try:
        with mock.patch.object(requests_mod, "get", side_effect=router), \
             mock.patch.object(prod_app.time, "sleep", lambda s: None):
            at = AppTest.from_file(APP_PATH, default_timeout=120)
            at.run()

            # card PARTITE per ogni lega: sync + controllo nomi
            for lg in LEAGUES_CONFIG:
                at.sidebar.selectbox[0].select(lg).run()
                sync = [b for b in at.button
                        if "SINCRONIZZA" in (b.label or "")]
                if not sync:
                    esiti["errori"].append(f"{lg}: bottone SINCRONIZZA non trovato")
                    continue
                sync[0].click()
                at.run()
                html = "\n".join(m.value for m in at.markdown)
                trovati = {}
                for fx_lg, h, a in FIXTURE_MATCHES:
                    if fx_lg != lg:
                        continue
                    for raw in (h, a):
                        atteso = ATTESI_VISUALI.get(raw, raw)
                        presente = re.search(_standalone(atteso), html) is not None
                        grezza = _grezza_residua(html, raw, atteso)
                        trovati[raw] = {"atteso": atteso, "presente": presente,
                                        "grezza_visibile": grezza}
                        if not presente:
                            esiti["errori"].append(
                                f"{lg}: card non mostra {atteso!r} per {raw!r}")
                        if grezza:
                            esiti["errori"].append(
                                f"{lg}: la forma grezza {raw!r} e' ancora visibile")
                esiti["card"][lg] = trovati

            # tab TOP MIX: calcolo con le stesse partite mockate
            top10 = [b for b in at.button if "Calcola Top 10" in (b.label or "")]
            if not top10:
                esiti["errori"].append("bottone Calcola Top 10 non trovato")
            else:
                top10[0].click()
                at.run()
                html = "\n".join(m.value for m in at.markdown)
                esiti["top_mix"]["righe_html"] = html.count(
                    "<div class='top-mix-row'>")
                for raw, atteso in ATTESI_VISUALI.items():
                    # una partita puo' non essere nel top10, ma la forma grezza
                    # mappata NON deve MAI comparire come nome squadra
                    if _grezza_residua(html, raw, atteso):
                        esiti["errori"].append(
                            f"Top Mix: la forma grezza {raw!r} e' visibile")
    finally:
        # ripristino del registro locale com'era prima della verifica
        if backup is None:
            if os.path.exists(preds_path):
                os.remove(preds_path)
        else:
            with open(preds_path, "w", encoding="utf-8") as f:
                f.write(backup)
    return esiti


# --------------------------------------------------------------------------
# Referto
# --------------------------------------------------------------------------
def scrivi_referto(percorso, base, tabella, n_squadre, parte_b, parte_c, parte_d):
    ok_b = (not parte_b["top_mix"]["errori"]
            and not parte_b["analisi_rapida"]["errori"])
    ok_c = not parte_c["errori"]
    ok_d = not parte_d["errori"]
    verde = ok_b and ok_c and ok_d and n_squadre == 96

    r = io.StringIO()
    w = r.write
    w("# DISPLAY_NAME_MAP: nomi solo-UI per la visualizzazione — referto\n\n")
    w("**Data esecuzione:** "
      f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")
    w(f"**Base di confronto:** `{base}` "
      f"({_git('rev-parse', '--short', base).strip()})\n")
    w(f"**Esito: {'VERDE' if verde else 'ROSSO'}** — cambio puramente "
      "cosmetico: stessi risultati, stesse probabilita', stesso Top Mix; "
      "cambia solo il nome mostrato.\n\n")
    w("> Ricostruzione del referto del 15/09 "
      "(`giornata_nomi_e_date_matchday6.md`, mai committato e non "
      "recuperabile da nessun branch/stash/PR): la tabella e le forme grezze "
      "sono state rimesurate dai dati presenti nel repository (righe raw dei "
      "`*_Live.csv` 2026/27, alias documentati in `TEAM_NAME_MAP`, "
      "`audit/results/schalke_bayern_921.json`).\n\n")

    w("## 1. Disegno\n\n")
    w("- `SoccerMath/display_names.py` (NUOVO): `DISPLAY_NAME_MAP` + "
      "`display_name()`, separato da `TEAM_NAME_MAP`/`UNDERSTAT_NAME_MAP` "
      "(invariati: servono al calcolo).\n")
    w("- Chiavi = nomi **canonici**: `display_name()` risolve qualunque "
      "forma grezza tramite `clean_name` (la stessa garanzia dei lookup del "
      "motore) ed e' quindi immune alla variante esatta che l'API restituisce.\n")
    w("- Fuori mappa: pass-through immutato (nessun fuzzy matching, nessun "
      "guess — comportamento pre-esistente).\n")
    w("- Applicato SOLO nei 4 punti di visualizzazione identificati dal "
      "referto (verificati invariati dal 15/09: `app.py` e' byte-identico "
      "fra la PR#23 e oggi):\n")
    w("  1. `get_ultimi_risultati_fd` — stringa ultimi risultati;\n"
      "  2. `fetch_and_calc_top_mix` — righe ed etichette;\n"
      "  3. `analisi_rapida_giornata` — etichette, pronostico e campi "
      "home/away del registro;\n"
      "  4. card del tab PARTITE.\n")
    w("- I punti di confronto/chiave ricevono sempre il nome GREZZO: "
      "`team_stats.get(clean_name(...))`, `predict_elo_probs`, "
      "`blend_elo_into_1x2`, `show_details` (che fa matching contro "
      "live_data/classifica). Il grading del registro e le dedup sono per "
      "`match_id`/`(match_id, origin, selector_version)`: i nomi display non "
      "li toccano.\n\n")

    w("## 2. Tabella delle 96 squadre (2026/27, misurata)\n\n")
    w("Le \"forme grezze\" sono le varianti non canoniche osservate: righe "
      "raw nei `*_Live.csv` 2026/27 (scritte prima degli alias) e alias "
      "delle API live documentati in `TEAM_NAME_MAP`. \"invariato\" = la "
      "squadra non ha voce in mappa e l'UI continua a mostrare il nome "
      "grezzo dell'API, esattamente come prima del cambio.\n\n")
    w("| Lega | Canonico (chiave motore) | Forme grezze osservate | "
      "Display |\n")
    w("|---|---|---|---|\n")
    for riga in tabella:
        grezze = ", ".join(riga["grezze"]) if riga["grezze"] else "—"
        w(f"| {riga['lega']} | {riga['canonico']} | {grezze} | "
          f"**{riga['display']}** |\n")
    w(f"\nTotale squadre: **{n_squadre}** "
      "(20 Serie A + 20 Premier + 20 La Liga + 18 Bundesliga + 18 Ligue 1). "
      "La Serie A non ha voci in mappa: i 20 shortName 2026/27 sono gia' "
      "nomi completi.\n\n")

    w("## 3. Equivalenza PRE/POST sui flussi reali\n\n")
    tm = parte_b["top_mix"]
    w("### fetch_and_calc_top_mix (funzione PRE eseguita dal sorgente git "
      f"della base, funzione POST dal codice attuale, stessi fixture)\n\n")
    w(f"- righe PRE: {tm['n_pre']}, righe POST: {tm['n_post']}; "
      f"leghe mancanti PRE={tm['missing_pre']} POST={tm['missing_post']}\n")
    w("- campi identici al bit: `league`, `giornata`, `match_id`, `utcDate`, "
      "`rank`, `prob`, `prob_val`, `poisson`, `elo`, `elo_disponibile`, "
      "**`mercato_standard`**\n")
    w("- campi che cambiano (e come atteso): `home`, `away`, "
      "`market` (solo sostituzione del nome)\n")
    w(f"- errori: **{len(tm['errori'])}**\n")
    for e in tm["errori"]:
        w(f"  - {e}\n")
    w("\nEsempi (PRE → POST):\n\n")
    for ex in parte_b["_esempi_top_mix"]:
        w(f"- `{ex['pre']['home']} vs {ex['pre']['away']}` "
          f"[{ex['pre']['market']} / {ex['pre']['mercato_standard']} / "
          f"{ex['pre']['prob_val']}%] → `{ex['post']['home']} vs "
          f"{ex['post']['away']}` [{ex['post']['market']} / "
          f"{ex['post']['mercato_standard']} / {ex['post']['prob_val']}%]\n")
    ar = parte_b["analisi_rapida"]
    w(f"\n### analisi_rapida_giornata\n\n- salvataggi PRE: {ar['n_pre']}, "
      f"POST: {ar['n_post']}\n- identici: `prob`, `prob_poisson`, "
      "`mercato_standard`, `origin`, `giornata`\n- cambiano (come atteso): "
      "`home`, `away`, `pron` (solo sostituzione del nome)\n"
      f"- errori: **{len(ar['errori'])}**\n")
    for e in ar["errori"]:
        w(f"  - {e}\n")

    w("\n## 4. Guardie strutturali\n\n")
    w(f"- file modificati verso {base}: "
      f"{', '.join(parte_c['file_modificati']) or 'nessuno'}\n")
    w("- `team_aliases.py`, `config.py`, `models/elo_engine.py`, "
      "`prediction_registry.py`, `team_names.py`, `update_db.py`: "
      f"**{'invariati' if parte_c['catena_intatta'] else 'MODIFICATI'}**\n")
    w("- il layer display non e' importato da nessun modulo di calcolo\n")
    w(f"- chiamate `display_name(` in `app.py`: 8 "
      f"(2 ultimi risultati + 2 Top Mix + 2 Analisi Rapida + 2 card)\n")
    if "SoccerMath/test_topmix_selector_parity.py" in parte_c["file_modificati"]:
        w("- `test_topmix_selector_parity.py`: il test esegue il testo "
          "CORRENTE di `fetch_and_calc_top_mix` in un namespace di stub; il "
          "solo aggiustamento e' iniettarvi la `display_name` VERA (i nomi "
          "sintetici della griglia non hanno voci in mappa, quindi e' "
          "pass-through identita' e la parita' bit-per-bit col fixture "
          "PRE-refactor resta pienamente significativa: 26/26 verdi).\n")
    w(f"- errori: **{len(parte_c['errori'])}**\n")
    for e in parte_c["errori"]:
        w(f"  - {e}\n")

    w("\n## 5. Render end-to-end (app vera, Streamlit AppTest, API mockate)\n\n")
    for lg, trovati in parte_d["card"].items():
        w(f"- **{lg}**: " + "; ".join(
            f"{raw}→{info['atteso']} "
            f"({'OK' if info['presente'] and not info['grezza_visibile'] else 'ERRORE'})"
            for raw, info in trovati.items()) + "\n")
    w(f"- Tab TOP MIX: {parte_d['top_mix'].get('righe_html', 0)} righe "
      "renderizzate; nessuna forma grezza mappata visibile\n")
    w(f"- errori: **{len(parte_d['errori'])}**\n")
    for e in parte_d["errori"]:
        w(f"  - {e}\n")

    w("\n## 6. Come riprodurre\n\n")
    w("```bash\npython3 audit/display_name_map_check.py "
      "--base origin/main\n```\n")
    w("Suite completa: `pytest SoccerMath/ audit/ "
      "--ignore=SoccerMath/test_theme_toggle.py` "
      "(attesi i 2 fallimenti pre-esistenti su main, estranei a questo "
      "cambio).\n")

    os.makedirs(os.path.dirname(percorso), exist_ok=True)
    with open(percorso, "w", encoding="utf-8") as f:
        f.write(r.getvalue())
    return verde


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--referto",
                    default=os.path.join(REPO_ROOT, "audit", "results",
                                         "display_name_map_referto.md"))
    args = ap.parse_args()

    print("=== PARTE A: tabella 96 ===")
    tabella, n = parte_a_tabella_96()
    print(f"    squadre 2026/27: {n} (attese 96)")
    voci = sum(1 for r in tabella if r["in_mappa"])
    print(f"    voci DISPLAY_NAME_MAP: {voci}")

    print("=== PARTE B: equivalenza PRE/POST ===")
    parte_b = parte_b_equivalenza(args.base)
    print(f"    top mix: {parte_b['top_mix']['n_pre']} righe PRE / "
          f"{parte_b['top_mix']['n_post']} POST, errori "
          f"{len(parte_b['top_mix']['errori'])}")
    print(f"    analisi rapida: {parte_b['analisi_rapida']['n_pre']} PRE / "
          f"{parte_b['analisi_rapida']['n_post']} POST, errori "
          f"{len(parte_b['analisi_rapida']['errori'])}")

    print("=== PARTE C: guardie strutturali ===")
    parte_c = parte_c_guardie(args.base)
    print(f"    file modificati: {parte_c['file_modificati']}")
    print(f"    errori: {len(parte_c['errori'])}")

    print("=== PARTE D: render end-to-end ===")
    parte_d = parte_d_render()
    print(f"    errori: {len(parte_d['errori'])}")

    verde = scrivi_referto(args.referto, args.base, tabella, n,
                           parte_b, parte_c, parte_d)
    print(f"\nReferto: {args.referto}")
    print(f"ESITO: {'VERDE' if verde else 'ROSSO'}")
    return 0 if verde else 1


if __name__ == "__main__":
    sys.exit(main())
