"""Parita' bit-per-bit del selettore Top Mix PRIMA / DOPO l'estrazione in funzione pura.

``audit/margini_migliorabili_topmix.md`` §9 punto 2 chiedeva di spostare la
selezione di riga (7 mercati, argmax, blend, soglie, veto) fuori da
``fetch_and_calc_top_mix``, cosi' da poterla testare senza HTTP, senza cache e
senza streamlit. Uno spostamento del genere e' neutro solo se dimostrato: qui il
corpo PRE-refactor (testo verbatim in ``test_fixtures/topmix_selettore_pre_refactor.py``,
generato da ``audit/make_topmix_selector_fixture.py``) viene eseguito nello
STESSO insieme di stub del percorso nuovo, e gli output confrontati carattere
per carattere.

Tre livelli, dal meno esigente al piu' completo:

* ``TestGuardieTesto`` (stdlib + ``app.py`` letto come testo): ogni riga della
  matematica di selezione deve ritrovarsi nel nuovo ``app.py``, oppure essere
  dichiarata "spostata" con un motivo. E' la guardia contro le riscritture: una
  soglia cambiata fa fallire il test.
* ``TestParitaGriglia`` / ``TestParitaCasiLimite`` (stdlib): le due funzioni
  ``fetch_and_calc_top_mix`` (vecchia dal fixture, nuova estratta da ``app.py``)
  girano sugli stessi deterministici stub su centinaia di partite sintetiche.
  Girano anche qui, senza streamlit/numpy/scipy/rete: e' il livello che alla repo
  mancava (l'unico test end-to-end esistente, ``audit/test_topmix_next_matchday.py``,
  chiede l'ambiente completo di Streamlit e SciPy).
* ``TestProvenienza``: il testo del fixture coincide ancora con il blob git da
  cui e' stato generato (skip se il clone non ha quell'oggetto).

Se il confronto fallisce, lo spostamento NON era neutro: correggere
``seleziona_riga_top_mix`` (o rimettere il corpo inline), senza toccare soglie
ne' pesi.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(HERE, "app.py")
FIXTURE_PATH = os.path.join(HERE, "test_fixtures", "topmix_selettore_pre_refactor.py")
REPO_ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)


def _carica_fixture():
    spec = importlib.util.spec_from_file_location("_topmix_pre_refactor", FIXTURE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIX = _carica_fixture()

CAMPI_MATCH = ("league", "giornata", "home", "away", "match_id", "utcDate", "rank")


# ----------------------------------------------------------- ``app.py`` come testo
def _sorgente_app() -> str:
    with open(APP_PATH, encoding="utf-8") as f:
        return f.read()


def _blocco(src: str, nome: str) -> str:
    """Sorgente di una funzione top-level. ``lineno`` punta alla ``def``, quindi il
    decoratore ``@st.cache_data`` non e' incluso: qui serve la funzione nuda, perche'
    la cache di Streamlit congelerebbe il risultato fra i due giri."""
    righe = src.splitlines(keepends=True)
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name == nome:
            return "".join(righe[node.lineno - 1: node.end_lineno])
    raise AssertionError(f"{nome} non trovata in app.py")


def _corpo(*blocchi: str) -> str:
    """Blocchi ripuliti del solo docstring: l'RFC cita i nomi che il codice non deve usare.

    I commenti restano: i divieti sono espressi come FORME DI CHIAMATA, quindi un
    commento che dice "se predict_elo_probs ha fallito" non conta come uso. Si
    passa un blocco per funzione perche' la matematica di selezione e' oggi
    distribuita su due funzioni.
    """
    fuori = []
    for blocco in blocchi:
        fn = ast.parse(blocco).body[0]
        righe = blocco.splitlines(keepends=True)
        primo = fn.body[0]
        ha_doc = (isinstance(primo, ast.Expr) and isinstance(primo.value, ast.Constant)
                  and isinstance(primo.value.value, str))
        start = primo.end_lineno if ha_doc else primo.lineno - 1
        fuori.append("".join(righe[start: fn.end_lineno]))
    return "".join(fuori)


def _costante(src: str, nome: str):
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == nome:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"costante {nome} non trovata in app.py")


SRC = _sorgente_app()
ELO_W = _costante(SRC, "ELO_ENSEMBLE_W")
FINESTRA = _costante(SRC, "TOP_MIX_ROUND_WINDOW_DAYS")


# ------------------------------------------------------------------ stub condivisi
class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload


class _Logging:
    """Raccoglie invece di scrivere: niente streamlit e niente file."""

    def __init__(self):
        self.warn = []

    def warning(self, msg, *a, **k):
        self.warn.append(str(msg))

    def info(self, msg, *a, **k):
        pass

    def error(self, msg, *a, **k):
        self.warn.append(str(msg))


class _Time:
    """``sleep`` azzerata (6,5 s per lega rallenterebbero il test); il resto e' reale."""

    sleep = staticmethod(lambda secondi: None)
    gmtime = staticmethod(time.gmtime)
    mktime = staticmethod(time.mktime)


def _clean_name(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _codice_mercato_selezionato(best, h, a):
    """Etichetta finta ma deterministica.

    Serve solo a verificare che il selettore chiami il codice con le stesse
    argomentazioni: la mappatura reale mercato -> codice e' coperta da
    ``test_standardizza_mercato.py``.
    """
    return f"STD<{best}|{h}|{a}>"


def _parse_utc(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------ mondo sintetico
LEGHE = ("SerieA", "Premier", "LaLiga", "Bundesliga", "Ligue1")
# Le quattro facce dell'"Elo non c'e'": predittore assente, dict vuoto, dict
# senza la chiave del mercato scelto, predittore che solleva.
ELO_MANCANTI = (None, {}, {"X": 0.5}, ConnectionError("elo non raggiungibile"))
CODICI = {"SerieA": "SA", "Premier": "PL", "LaLiga": "LL", "Bundesliga": "BL", "Ligue1": "FR1"}


def _partita(h, a, lega, mid, matchday, utc, poisson, elo):
    return {"_mid": mid, "h": h, "a": a, "lega": lega, "matchday": matchday,
            "utc": utc, "poisson": poisson, "elo": elo}


def _payload(elemi):
    """Dalla lista di ``_partita`` alle strutture che gli stub devono restituire."""
    per_lega, stats, poisson, elo = {lg: [] for lg in LEGHE}, {lg: {} for lg in LEGHE}, {}, {}
    for e in elemi:
        poisson[e["_mid"]] = e["poisson"]
        elo[e["_mid"]] = e["elo"]
        for nome in (e["h"], e["a"]):
            stats[e["lega"]][_clean_name(nome)] = {"att": 1.0, "def": 1.0, "_mid": e["_mid"]}
        per_lega[e["lega"]].append({
            "id": 900000 + e["_mid"], "matchday": e["matchday"], "status": "TIMED",
            "utcDate": e["utc"],
            "homeTeam": {"shortName": e["h"], "name": e["h"]},
            "awayTeam": {"shortName": e["a"], "name": e["a"]},
        })
    return {"per_lega": per_lega, "stats": stats, "poisson": poisson, "elo": elo,
            "nomi": {_clean_name(e["h"]): e["_mid"] for e in elemi}}


MODI = ("1", "X", "2", "Over", "Under", "GG", "NG")
# Bordi esatti, non "vicino": e' qui che un refactor distratto cambia esito.
SOGLIE_ESATTE = (0.55, 0.5499, 0.60, 0.5999)


def _vettore_forzato(modo, valore):
    """Vettore Poisson in cui UN mercato preciso e' l'argmax, esattamente a ``valore``.

    Vincolo strutturale del selettore: Over+Under = 1 e GG+NG = 1, quindi il
    massimo dei totali e' sempre >= 0.5 e un mercato 1X2 puo' vincere solo sopra
    0.5. Mettendo u25 = gg = 0.5 i quattro totali valgono tutti 0.5: cosi' il
    vincitore 1X2 resta esattamente sul filo della soglia 0.55.
    """
    w = valore
    if modo in ("1", "X", "2"):
        meta = (1.0 - w) / 2.0
        m = {"1": meta, "X": meta, "2": meta, "u25": 0.5, "gg": 0.5}
        m[modo] = w
        return m
    if modo in ("Over", "Under"):
        m = {"1": 0.20, "X": 0.15, "2": 0.10, "u25": 0.5, "gg": 0.5}
        m["u25"] = 1.0 - w if modo == "Over" else w
        return m
    m = {"1": 0.20, "X": 0.15, "2": 0.10, "u25": 0.5, "gg": 0.5}
    m["gg"] = w if modo == "GG" else 1.0 - w
    return m


def _genera_griglia(n: int = 1400, seed: int = 20260909):
    """Partite sintetiche che coprono i rami: ogni argmax, bordi di soglia, 5 Elo.

    Nulla e' casuale nel confronto: il seed fissa i valori, cosi' il test e'
    riproducibile carattere per carattere. Le date sono tutte future (le passate
    le scarta ``select_next_matchday_matches``) e ricadono nella finestra di
    round: un match scartato dall'I/O sarebbe un caso non confrontato.
    """
    rng = random.Random(seed)
    base = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=1)
    elemi = []
    for i in range(n):
        lega = LEGHE[i % len(LEGHE)]
        giro = i // len(LEGHE)
        h, a = f"{CODICI[lega]}Casa{giro}", f"{CODICI[lega]}Trasferta{giro}"
        modo = MODI[i % len(MODI)]
        # un caso su quattro atterra ESATTAMENTE su una soglia, non vicino
        valore = SOGLIE_ESATTE[i % 4] if i % 4 == 0 else rng.uniform(0.51, 0.95)
        if i < len(MODI):
            # "vetrina": un caso per ogni mercato, con il valore massimo possibile
            # e un Elo perfettamente concorde. Sono le 7 righe che garantiscono
            # che il test_tutti_i_rami_esplorati abbia davvero visto ogni ramo.
            valore = 0.999
        poisson = _vettore_forzato(modo, valore)
        if i < len(MODI):
            elemi.append(_partita(h, a, lega, i, 12, base.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                  poisson, dict(poisson)))
            continue

        s = rng.random()
        if s < 0.40:                      # Elo vicino: discordanza entro il veto
            delta = rng.uniform(0.0, 0.24) * rng.choice([-1.0, 1.0])
            elo = {"1": min(0.99, max(0.01, poisson["1"] + delta)),
                   "X": min(0.99, max(0.01, poisson["X"] + delta)),
                   "2": min(0.99, max(0.01, poisson["2"] + delta))}
        elif s < 0.60:                    # Elo lontano: il veto deve potersi vedere
            elo = {"1": max(0.01, poisson["1"] - rng.uniform(0.25, 0.6)),
                   "X": min(0.99, poisson["X"] + 0.4),
                   "2": min(0.99, poisson["2"] + rng.uniform(0.25, 0.5))}
        elif s < 0.72:                    # dizionario incompleto: nel vecchio era KeyError
            elo = {"1": poisson["1"]}
        elif s < 0.82:                    # vuoti e None: altri percorsi di eccezione
            elo = {}
        elif s < 0.92:
            elo = None
        else:                             # predittore che solleva
            elo = ConnectionError("elo cache rotta")

        elemi.append(_partita(h, a, lega, i, 12,
                              (base + timedelta(days=giro % 4, hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                              poisson, elo))
    return elemi


def assert_solo_elo_in_meno(tc, vecchio, nuovo):
    """Confronto fra i log dei due percorsi: nessun avviso nuovo, al massimo meno Elo.

    Prima un ``KeyError`` sull'accesso a ``elo_p[...]`` finiva nel ``except`` e
    produceva un ``logging.warning``; ora la stessa condizione e' il flag
    ``elo_disponibile`` sulla riga, dove il registro la legge davvero. Un avviso
    in PIU', o un avviso di fetch diverso, e' invece una regressione.
    """
    for w in nuovo:
        tc.assertIn(w, vecchio, "avviso introdotto ex novo dal refactor")
    for w in vecchio:
        if w not in nuovo:
            tc.assertTrue(w.startswith("Elo non disponibile per"), w)


# ------------------------------------------------------------------ esecuzioni
def _esegui(vecchio: bool, elemi):
    """Esegue la Top Mix PRIMA (testo del fixture) o DOPO (testo di app.py).

    Gli stub sono identici nei due namespace: cambia solo il codice chiamato.
    Restituisce il JSON delle righe SENZA ``sort_keys`` - quindi l'ordine delle
    chiavi fa parte del confronto, ed e' giusto cosi': e' quell'ordine a decidere
    l'ordine delle colonne del DataFrame che la UI costruisce sulle righe - piu'
    gli avvisi di log e i timeout delle GET.
    """
    mondo = _payload(elemi)
    ns = {
        "LEAGUES_CONFIG": {lg: {} for lg in LEGHE},
        "LEAGUE_CODE_MAP": dict(CODICI),
        "API_KEY_DATA": "TEST-KEY",
        "ELO_ENSEMBLE_W": ELO_W,
        "TOP_MIX_ROUND_WINDOW_DAYS": FINESTRA,
        "logging": _Logging(),
        "time": _Time,
        "datetime": datetime,
        "timedelta": timedelta,
        "timezone": timezone,
        "_parse_utc_date": _parse_utc,
        "clean_name": _clean_name,
        "codice_mercato_selezionato": _codice_mercato_selezionato,
        "get_league_engine": lambda lega: (mondo["stats"][lega], 1.45, 1.15, 20),
        "get_full_poisson_two_heads": _poisson_stub(mondo),
        "predict_elo_probs": _elo_stub(mondo),
        "requests": _Requests(mondo),
    }
    # La scelta della giornata e' la STESSA funzione reale di app.py in entrambi i
    # namespace: il refactor non la tocca, e condividerla garantisce che le due
    # esecuzioni vedano esattamente la stessa lista di partite.
    exec(_blocco(SRC, "select_next_matchday_matches"), ns)
    if vecchio:
        exec(FIX.TESTO_FUNZIONE, ns)
    else:
        exec(_blocco(SRC, "seleziona_riga_top_mix"), ns)
        exec(_blocco(SRC, "fetch_and_calc_top_mix"), ns)
    top, missing = ns["fetch_and_calc_top_mix"]()
    return (json.dumps({"top": top, "missing": missing}), list(ns["logging"].warn),
            mondo.get("timeouts", []))


def _poisson_stub(mondo):
    def stub(h_s, a_s, avg_h, avg_a):
        assert h_s["_mid"] == a_s["_mid"], "squadre di partite diverse nel medesimo match"
        return dict(mondo["poisson"][h_s["_mid"]])     # copia: il selettore non deve mutare
    return stub


def _elo_stub(mondo):
    def stub(h, a, league):
        spec = mondo["elo"][mondo["nomi"][_clean_name(h)]]
        if isinstance(spec, Exception):
            raise spec
        return spec
    return stub


class _Requests:
    """GET finta: risponde con le partite della lega chiesta, e registra i timeout.

    Il registro vive nel `mondo` della singola esecuzione, non su un attributo di
    classe: i test della stessa classe girano nello stesso processo e un
    contatore globale crescerebbe di test in test.
    """

    def __init__(self, mondo):
        self.mondo = mondo

    def get(self, url, headers=None, params=None, timeout=None):
        self.mondo.setdefault("timeouts", []).append(timeout)
        code = re.search(r"competitions/([^/]+)/", url).group(1)
        lega = next(l for l, c in CODICI.items() if c == code)
        return _Resp({"matches": self.mondo["per_lega"][lega]})


class TestGuardieTesto(unittest.TestCase):
    """La matematica di selezione deve essere stata SPOSTATA, non riscritta."""

    # Righe che il fixture cita e che nel nuovo codice non possono comparire
    # identiche: ognuna con il suo perche'. Se il selettore perde una riga non
    # dichiarata qui, il test fallisce: e' esattamente lo scopo della guardia.
    DICHIARATE = {
        "elo_prob, elo_disponibile = poisson_prob, True":
            "l'I/O su Elo e' uscito dal selettore: `elo_disponibile` arriva dal chiamante",
        "try:": "il try ora avvolge solo predict_elo_probs, nel chiamante",
        "except Exception as e:": "idem: il `except` sta in fetch_and_calc_top_mix",
        "elo_p = predict_elo_probs(h, a, league)": "chiamata in fetch, non nel selettore",
        'logging.warning(f"Elo non disponibile per {h} vs {a} ({league}): {e}")':
            "resta nel chiamante: il logging non appartiene a una funzione pura",
        'elo_prob = elo_p["1"]': "letta con .get + controllo sul tipo (hardening)",
        'elo_prob = elo_p["2"]': "letta con .get + controllo sul tipo (hardening)",
        'elo_prob = elo_p["X"]': "letta con .get + controllo sul tipo (hardening)",
    }
    NORMALIZZA = [("m_poisson[", "m["), ('f"Vittoria {h}"', 'f"Vittoria {home}"'),
                  ('f"Vittoria {a}"', 'f"Vittoria {away}"'), ("elo_p[", "elo_probs["),
                  ("{h}", "{home}"), ("{a}", "{away}")]

    def _nuovo(self):
        return _blocco(SRC, "seleziona_riga_top_mix") + _blocco(SRC, "fetch_and_calc_top_mix")

    def test_ogni_riga_di_selezione_replicata_o_dichiarata(self):
        nuovo = {r.strip() for r in self._nuovo().splitlines()}
        for riga in FIX.RIGHE_CHIAVE:
            r = riga
            for a, b in self.NORMALIZZA:
                r = r.replace(a, b)
            if r in nuovo:
                continue
            self.assertIn(riga, self.DICHIARATE,
                          f"riga della vecchia selezione sparita senza dichiarazione: {riga!r}")

    def test_soglie_pesi_e_gate_ancora_letterali(self):
        nuovo = _corpo(_blocco(SRC, "seleziona_riga_top_mix"),
                       _blocco(SRC, "fetch_and_calc_top_mix"))
        for atteso in ("min_conf = 0.60", "min_conf = 0.55",
                       "abs(poisson_prob - elo_prob) < 0.25",
                       "confidence = ELO_ENSEMBLE_W * poisson_prob + (1 - ELO_ENSEMBLE_W) * elo_prob",
                       "best_mkt = max(mercati, key=mercati.get)",
                       "top_10 = sorted(all_preds, key=lambda x: x['prob'], reverse=True)[:10]"):
            self.assertIn(atteso, nuovo, atteso)

    def test_il_corpo_puro_non_tocca_io(self):
        corpo = _corpo(_blocco(SRC, "seleziona_riga_top_mix"))
        for vietato in ("requests.", "st.", "save_prediction", "get_league_engine(",
                        "predict_elo_probs(", "logging.", "time.sleep", "open(",
                        "api.football-data"):
            self.assertNotIn(vietato, corpo, vietato)
        self.assertEqual(0, corpo.count("try:"), "un try qui dentro vuol dire I/O mascherato")

    def test_il_fixture_non_e_importato_da_app(self):
        """Il fixture di confronto deve restare fuori dal percorso di produzione."""
        self.assertNotIn("topmix_selettore_pre_refactor", SRC)
        self.assertNotIn("seleziona_riga_top_mix_PRIMA", SRC)

    def test_orchestratore_assembla_leggendo_il_selettore(self):
        fetch = _blocco(SRC, "fetch_and_calc_top_mix")
        for chiave in FIX.CHIAVI_RIGA:
            if chiave in CAMPI_MATCH:
                continue      # campi del match: li aggiunge l'orchestratore
            self.assertRegex(fetch, '"%s": riga\\["%s"\\]' % (chiave, chiave), chiave)


class TestParitaGriglia(unittest.TestCase):
    """Stesso input, due implementazioni: output identico carattere per carattere."""

    @classmethod
    def setUpClass(cls):
        cls.elemi = _genera_griglia()
        _Requests.timeouts = []
        cls.vecchio, cls.log_v, cls.to_v = _esegui(True, cls.elemi)
        cls.nuovo, cls.log_n, cls.to_n = _esegui(False, cls.elemi)
        cls.top_v = json.loads(cls.vecchio)["top"]
        cls.top_n = json.loads(cls.nuovo)["top"]

    def test_il_fixture_produce_righe_da_confrontare(self):
        self.assertEqual(10, len(self.top_v), "input troppo povero: nessun confronto reale")

    def test_output_identico(self):
        self.assertEqual(self.vecchio, self.nuovo)

    def test_ordine_delle_chiavi_identico(self):
        self.assertEqual([list(r) for r in self.top_v], [list(r) for r in self.top_n])

    def test_chiavi_del_selettore_allineate_al_fixture(self):
        attese = [k for k in FIX.CHIAVI_RIGA if k not in CAMPI_MATCH]
        self.assertEqual(attese, [k for k in self.top_v[0] if k not in CAMPI_MATCH])

    def test_tutti_i_rami_esplorati(self):
        """Altrimenti la parita' non avrebbe coperto 1X2 e totali separatamente."""
        visti = {r["market"] for r in self.top_v} | {r["market"] for r in self.top_n}
        self.assertTrue(any(m.startswith("Vittoria") for m in visti), visti)
        for totale in ("Over 2.5", "Under 2.5", "GG", "NG"):
            self.assertIn(totale, visti)
        # Il ramo "Elo assente" ha soglia 0.60 e qui non arriva mai in vetta:
        # lo si confronta a parte, in test_griglia_con_elo_assente_parita_e_flag_acceso.

    def test_griglia_con_elo_assente_parita_e_flag_acceso(self):
        """Ripete il confronto dove il ramo "Elo assente" E' quello che passa.

        Nella griglia generale il top 10 e' pieno di righe sopra 0.9 con Elo
        concorde, quindi li' il ramo debole non si vede mai: qui tutti i valori
        stanno fra 0.60 e 0.63 (la fascia dove la soglia 0.60 decide) e l'Elo e'
        sempre mancante o rotto. Se l'estrazione avesse perso un `False`, la
        soglia sarebbe tornata 0.55 e le due liste avrebbero differito.
        """
        base = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=1)
        elemi = []
        for i in range(90):
            lega = LEGHE[i % len(LEGHE)]
            h, a = f"ELOMANCA{i}Casa", f"ELOMANCA{i}Trasferta"
            modo = MODI[i % len(MODI)]
            valore = 0.60 + 0.003 * (i % 10)
            poisson = _vettore_forzato(modo, valore)
            elemi.append(_partita(h, a, lega, i, 12,
                                  (base + timedelta(hours=i % 9)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                  poisson, ELO_MANCANTI[i % len(ELO_MANCANTI)]))
        vecchio, log_v, _ = _esegui(True, elemi)
        nuovo, log_n, _ = _esegui(False, elemi)
        self.assertEqual(vecchio, nuovo)
        righe = json.loads(nuovo)["top"]
        self.assertEqual(10, len(righe), "griglia troppo povera: nessun confronto")
        self.assertTrue(any(not r["elo_disponibile"] for r in righe), righe)
        # Sui totali l'Elo non viene nemmeno letto, quindi il flag resta True:
        # e' il comportamento di prima, e la soglia 0.60 e' gia' quella dei totali.
        for r in righe:
            if r["market"].startswith(("Vittoria", "Pareggio")):
                self.assertFalse(r["elo_disponibile"], r)
        assert_solo_elo_in_meno(self, log_v, log_n)

    def test_rank_e_ordamento(self):
        self.assertEqual(list(range(1, 11)), [r["rank"] for r in self.top_n])
        probs = [r["prob"] for r in self.top_n]
        self.assertEqual(probs, sorted(probs, reverse=True))

    def test_log_nessun_avviso_nuovo_e_solo_elo_in_meno(self):
        """Lo spostamento del `try` non introduce avvisi ne' ne perde di fetch.

        Gli unici messaggi che possono scomparire sono "Elo non disponibile": la
        causa (dict incompleto) oggi viaggia sul flag `elo_disponibile` della
        riga, dove conta, invece che su un log.
        """
        fetch_v = [w for w in self.log_v if w.startswith("Errore fetch Top Mix")]
        fetch_n = [w for w in self.log_n if w.startswith("Errore fetch Top Mix")]
        self.assertEqual([], fetch_v)             # input pulito: nessuna fetch fallita
        self.assertEqual(fetch_v, fetch_n)
        assert_solo_elo_in_meno(self, self.log_v, self.log_n)

    def test_timeout_sulla_get_invariato(self):
        """Cinque leghe, una GET da 15 s di timeout per parte, prima e dopo."""
        atteso = [15] * len(LEGHE)
        self.assertEqual(atteso, self.to_v, "timeout GET cambiato (prima)")
        self.assertEqual(atteso, self.to_n, "timeout GET cambiato (dopo)")


class TestParitaCasiLimite(unittest.TestCase):
    """I punti dove un refactor si rompe: bordi di soglia, gate, Elo assente/malformato."""

    def _entrambi(self, poisson, elo, home="Casa", away="Trasferta"):
        utc = (datetime.now(timezone.utc).replace(microsecond=0)
               + timedelta(days=1, hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        e = _partita(home, away, "SerieA", 0, 12, utc, poisson, elo)
        v, log_v, _ = _esegui(True, [e])
        n, log_n, _ = _esegui(False, [e])
        return json.loads(v), json.loads(n), (log_v, log_n)

    def assert_parita(self, poisson, elo, **kw):
        v, n, log = self._entrambi(poisson, elo, **kw)
        self.assertEqual(v, n, f"divergenza su {poisson} / elo={elo}")
        return n

    def test_confidence_esattamente_sulla_soglia_1x2(self):
        # P = E = 0.55 -> conf = 0.55, e il gate e' `>=`: ammessa.
        n = self.assert_parita({"1": 0.55, "X": 0.20, "2": 0.25, "u25": 0.50, "gg": 0.50},
                               {"1": 0.55, "X": 0.20, "2": 0.25})
        self.assertEqual(1, len(n["top"]), n)
        self.assertAlmostEqual(0.55, n["top"][0]["prob"], places=12)

    def test_appena_sotto_la_soglia_1x2(self):
        n = self.assert_parita({"1": 0.5499, "X": 0.20, "2": 0.2500, "u25": 0.50, "gg": 0.50},
                               {"1": 0.5499, "X": 0.20, "2": 0.25})
        self.assertEqual([], n["top"])

    def test_blend_del_1x2_non_e_il_massimo_dei_mercati(self):
        # Poisson 0.60, Elo 0.40 -> conf = 0.6*0.60 + 0.4*0.40 = 0.52 < 0.55: fuori.
        n = self.assert_parita({"1": 0.60, "X": 0.15, "2": 0.15, "u25": 0.50, "gg": 0.50},
                               {"1": 0.40, "X": 0.15, "2": 0.45})
        self.assertEqual([], n["top"])

    def test_soglia_dei_totali_a_0_60_e_bordo(self):
        for val, atteso in ((0.60, 1), (0.5999, 0)):
            m = {"1": 0.10, "X": 0.10, "2": 0.10, "u25": 1.0 - val, "gg": 0.5}
            n = self.assert_parita(m, {"1": 0.50, "X": 0.20, "2": 0.30})
            self.assertEqual(atteso, len(n["top"]), (val, n))
            if atteso:
                self.assertEqual("Over 2.5", n["top"][0]["market"])
                self.assertEqual(n["top"][0]["prob"], n["top"][0]["poisson"] / 100.0)

    def test_veto_a_discrepanza_esatta(self):
        """|P-E| == 0.25 NON e' ammesso (< stretto), 0.2499999 si': confine movente.

        Vettori a 0.80 (prima 0.70): con ELO_ENSEMBLE_W=0.25 la confidence a
        0.70 cadrebbe sotto 0.55 e il confine verrebbe deciso dalla soglia di
        ammissibilita', non dal veto (adattato al porting w=0.25, 2026-09-12)."""
        for delta, atteso in ((0.25, 0), (0.2499999, 1)):
            m = {"1": 0.80, "X": 0.10, "2": 0.10, "u25": 0.50, "gg": 0.50}
            n = self.assert_parita(m, {"1": 0.80 - delta, "X": 0.10, "2": 0.10})
            self.assertEqual(atteso, len(n["top"]), (delta, n))

    def test_elo_assente_rialza_la_soglia_a_0_60_anche_per_il_1x2(self):
        for p1, atteso in ((0.56, 0), (0.61, 1)):
            m = {"1": p1, "X": 0.20, "2": 0.25, "u25": 0.50, "gg": 0.50}
            for assente in (None, {}, {"X": 0.20}, ConnectionError("giu'")):
                n = self.assert_parita(m, assente)
                self.assertEqual(atteso, len(n["top"]), (p1, assente, n))
                if atteso:
                    self.assertFalse(n["top"][0]["elo_disponibile"])
                    self.assertEqual(n["top"][0]["elo"], n["top"][0]["poisson"])

    def test_pareggio_e_vittoria_trasferta_stesso_codice(self):
        for chiave, mercato in (("X", "Pareggio"), ("2", "Vittoria Trasferta")):
            m = {"1": 0.05, "X": 0.05, "2": 0.05, "u25": 0.25, "gg": 0.25}
            m[chiave] = 0.80
            n = self.assert_parita(m, {"1": 0.20, "X": 0.80, "2": 0.80})
            self.assertEqual(mercato, n["top"][0]["market"], (chiave, n))
            self.assertEqual(f"STD<{mercato}|Casa|Trasferta>", n["top"][0]["mercato_standard"])

    def test_un_solo_match_e_rank_uno(self):
        n = self.assert_parita({"1": 0.90, "X": 0.05, "2": 0.05, "u25": 0.50, "gg": 0.50},
                               {"1": 0.90, "X": 0.05, "2": 0.05})
        self.assertEqual([1], [r["rank"] for r in n["top"]])

    def test_valore_elo_non_numerico_non_fa_piu_esplodere_il_batch(self):
        """Differenza VOLUTA e unidirezionale: qui la parita' NON puo' valere.

        PRIMA ``elo_prob = elo_p["1"]`` con un valore non numerico sollevava
        ``TypeError`` fuori dal ``try`` (il try copriva la sola chiamata, non
        l'accesso) e perdeva l'intero batch di 5 leghe. DOPO, il controllo sul
        tipo marca la riga ``elo_disponibile=False`` e la lascia Poisson puro.
        E' l'unico punto in cui il comportamento nuovo e' piu' permissivo: la
        riga prodotta e' comunque quella che il selettore avrebbe prodotto con
        un Elo semplicemente assente (vedi test_elo_assente_...).
        """
        m = {"1": 0.80, "X": 0.10, "2": 0.10, "u25": 0.50, "gg": 0.50}
        utc = (datetime.now(timezone.utc).replace(microsecond=0)
               + timedelta(days=1, hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        e = _partita("Casa", "Trasferta", "SerieA", 0, 12, utc, m, {"1": "0.70", "X": 0.10, "2": 0.10})
        with self.assertRaises(TypeError):
            _esegui(True, [e])
        nuovo, _, _ = _esegui(False, [e])
        n = json.loads(nuovo)
        self.assertEqual(1, len(n["top"]), n)
        self.assertFalse(n["top"][0]["elo_disponibile"])
        self.assertEqual(n["top"][0]["prob"], n["top"][0]["poisson"] / 100.0)
        # identica alla riga che lo STESSO input produce con Elo assente: la
        # tolleranza non apre una terza via, si appoggia a un percorso gia' testato
        assente, _, _ = _esegui(False, [_partita("Casa", "Trasferta", "SerieA", 0, 12, utc, m, None)])
        self.assertEqual(n["top"], json.loads(assente)["top"])


class TestProvenienza(unittest.TestCase):
    """Il fixture deve restare il sorgente di ``ORIGINE``, non una parafrasi."""

    def test_testo_allineato_al_blob(self):
        try:
            r = subprocess.run(["git", "-C", REPO_ROOT, "show", f"{FIX.ORIGINE}:{FIX.BLOB}"],
                               capture_output=True, text=True, timeout=30)
        except Exception as e:                                   # pragma: no cover
            self.skipTest(f"git non disponibile: {e}")
        if r.returncode != 0:
            self.skipTest(f"blob {FIX.ORIGINE} non nel clone (shallow?): rigenerare con "
                          "`python audit/make_topmix_selector_fixture.py`")
        righe = r.stdout.splitlines(keepends=True)
        for node in ast.parse(r.stdout).body:
            if isinstance(node, ast.FunctionDef) and node.name == FIX.NOME:
                testo = "".join(righe[node.lineno - 1: node.end_lineno])
                deco = righe[node.lineno - 2] if node.lineno >= 2 else ""
                if testo.startswith(deco):        # come fa il generatore: niente fette a vuoto
                    testo = testo[len(deco):]
                self.assertEqual(testo, FIX.TESTO_FUNZIONE,
                                 "fixture divergente dal blob: rigenerarlo")
                return
        self.fail(f"{FIX.NOME} non trovata nel blob")

    def test_righe_chiave_contengono_le_soglie(self):
        self.assertGreater(len(FIX.RIGHE_CHIAVE), 15, FIX.RIGHE_CHIAVE)
        join = "\n".join(FIX.RIGHE_CHIAVE)
        for atteso in ("min_conf = 0.60", "min_conf = 0.55", "abs(poisson_prob - elo_prob) < 0.25",
                       "best_mkt = max(mercati"):
            self.assertIn(atteso, join, atteso)

    def test_fixture_dichiara_l_origine(self):
        self.assertRegex(FIX.ORIGINE, r"^[0-9a-f]{7,40}$")
        self.assertEqual("SoccerMath/app.py", FIX.BLOB)
        self.assertEqual("fetch_and_calc_top_mix", FIX.NOME)


if __name__ == "__main__":
    unittest.main(verbosity=2)
