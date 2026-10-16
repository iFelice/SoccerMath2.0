"""AppTest delle schede nuove: «⚽ Pronostici» (col suo pulsante) e «🟰 Pareggi».

Il fixture e' costruito a mano: ``live_odds.json`` temporaneo con quote finte,
calendario football-data finto che racconta le stesse partite, database reale
solo in lettura (symlink), registro in memoria che conta le scritture. Nessuno
snapshot di quote pinnato, niente rete, nessun file reale toccato: i numeri
attesi si conoscono per costruzione. Solo il confronto con main (ultima classe)
legge ``app.py`` del commit base con ``git show`` e salta se il clone e' shallow.

Le date sono RELATIVE all'orologio reale (stessa scelta di
``test_apptest_top_mix.py``), perche' il percorso di registrazione scarta le
partite il cui kickoff e' gia' passato all'ora vera: un fixture con «17/10/2026
scritto a mano» funzionerebbe per qualche giorno e poi si svuoterebbe in
silenzio. L'orologio dell'app viene congelato allo stesso istante, e se quel
giorno cade troppo vicino al lunedi' di gioco viene spostato avanti di tre
giorni: cosi' «dentro la giornata» e «dopo lunedi'» restano due insiemi certi.

Cosa prova, sul VERO ``app.py``:

* «⚽ Pronostici», prima del click, mostra solo il pulsante, la riga «Ultima
  registrazione» e l'invito a premere: nessun numero, nessuna tabella, nessun
  riquadro chiuso (punto 2);
* il click calcola la giornata sulle quote del file, la registra nel Registro e
  lascia in vista UNA tabella con le sei colonne promesse (Quando, Partita,
  Pronostico, Quote %, Modello %, Quota), ordinate per «Quote %» decrescente,
  con la «Quota» = stima bet365 di QUELLA riga; «Modello %» e «Quota» sono testo
  formattato (virgola italiana) e la loro cella vuota e' una stringa vuota, non
  un "NaN" né un "None" — e la caption dice solo quante partite sono in tabella
  e quante restano nei prossimi giorni (punti 2 e 4);
* l'interruttore del periodo e' UN widget solo, e sta SOPRA la barra delle
  schede: lo leggono Pronostici, Pareggi e Multiple e nessuno dei tre testi
  rimanda a un'altra scheda per cercarlo. Cambiare periodo vuol dire chiedere
  un'altra giornata: la tabella dei pronostici si ritira e chiede un click nuovo
  — cosi' non si mescolano mai righe di due periodi — mentre la scheda Pareggi,
  che un click non ce l'ha, si allunga e basta; al click nuovo compare anche la
  partita dopo il lunedi', col marcatore ⏳ e la sua legenda sotto la tabella
  (punti 1 e 2);
* cliccare una riga apre la scheda partita di QUELLA riga e non scrive niente:
  nessun salvataggio nel Registro, nessuna chiamata di rete in uscita (punto 3);
* «🟰 Pareggi» elenca le X del periodo in ordine di probabilita', senza
  pulsante e senza scritture (punto 1);
* (punto 5) ``TestParitaScrittureColPulsanteVecchio`` riesegue lo stesso
  fixture contro l'``app.py`` del commit base e confronta le righe scritte: il
  pulsante nuovo non ha cambiato nessuna regola di registrazione.

L'ordine dei metodi conta: ``test_01`` e ``test_02`` guardano la pagina prima
del click, ``test_03`` lo preme, i successivi leggono lo stato che ne nasce
(l'esito resta in ``session_state``, ed e' parte della promessa). Un AppTest
costa ~40 s di import: dividerlo fra i metodi sarebbe costato dieci minuti.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(HERE, "app.py")
REPO_ROOT = os.path.dirname(HERE)
REALE_DATABASE = os.path.join(HERE, "database")

#: Commit base di questa PR: nel suo albero il pulsante si chiamava «Registra le
#: giocate della giornata» e le schede erano tre. Serve al confronto del punto 5.
BASE_MAIN = "27e482e"

for _p in (HERE, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_apptest_topmix_presentazione import (  # noqa: E402
    PAROLE_VIETATE,
    SCHEDA_MULTIPLE,
    SCHEDA_PAREGGI,
    SCHEDA_PRONOSTICI,
    SCHEDA_REGISTRO,
    _elementi_della_tab,
    _testi_della_tab,
)
from test_apptest_scheda_partita import _titolo_atteso  # noqa: E402

#: Le sei colonne promesse, nell'ordine.
COLONNE = ["Quando", "Partita", "Pronostico", "Quote %", "Modello %", "Quota"]

ETICHETTA_CALCOLA = "Calcola i pronostici della giornata"
ETICHETTA_VECCHIO = "Registra le giocate della giornata"

#: Campi che non sono un dato della giocata: l'ora del processo che scrive. Il
#: confronto del punto 5 li toglie dal paragone.
VOLATILI = ("salvato_il",)

ITALIA = timezone(timedelta(hours=2))  # l'ora in cui l'app mostra le date


def _id(riga):
    try:
        return int(riga.get("match_id"))
    except (TypeError, ValueError):
        return str(riga.get("match_id"))


def _quando_italiano(dt: datetime) -> str:
    """``sab 17/10, 19:45`` — formattazione attesa nelle celle «Quando»."""
    from lista_giocate import GIORNI_SETTIMANA_IT
    locale = dt.astimezone(ITALIA)
    return (f"{GIORNI_SETTIMANA_IT[locale.weekday()][:3]} "
            f"{locale.strftime('%d/%m')}, {locale.strftime('%H:%M')}")


class _Resp:
    """Risposta finta di ``requests.get``."""

    def __init__(self, payload, code=200):
        self._payload, self.status_code = payload, code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FixtureQuoteFinte:
    """Quote, calendario e orologio del fixture: una sola definizione, due usi.

    ``pianeta(adesso)`` costruisce le partite; ``payload_quote``/``calendario``
    sono quello che l'app legge dal file e quello che gli risponde il
    football-data finto.
    """

    #: ore di vantaggio sul fischio d'inizio, per le partite DENTRO la giornata.
    @staticmethod
    def pianifica(adesso: datetime) -> list:
        import lista_giocate as lg
        lunedi = lg.lunedi_gioco(adesso)
        entro = [adesso + timedelta(hours=h) for h in (8, 12, 16, 20)]
        oltre = lunedi + timedelta(hours=96)     # dopo lunedi', e oltre 3 giorni
        return [
            # (id, casa, trasferta, (p1, pX, p2), kickoff)
            (111, "Genoa", "Fiorentina", (0.60, 0.25, 0.15), entro[1]),
            (112, "Torino", "Como", (0.50, 0.28, 0.22), entro[0]),
            (113, "Roma", "Lecce", (0.66, 0.20, 0.14), entro[3]),
            (114, "Napoli", "Venezia", (0.20, 0.22, 0.58), entro[2]),
            (115, "Milan", "Juventus", (0.57, 0.23, 0.20), oltre),
        ]

    @staticmethod
    def _libro(p1: float, pX: float, p2: float, adesso: datetime,
               k: float = 1.06) -> dict:
        """Un solo libro (Pinnacle) con il 6% di margine: la de-vig riporta
        esattamente le probabilita' volute (le tre summano a 1)."""
        return {"key": "pinnacle", "title": "Pinnacle",
                "last_update": _iso(adesso, True),
                "h2h": {"home": round(k / p1, 4), "draw": round(k / pX, 4),
                        "away": round(k / p2, 4)}}

    @classmethod
    def payload_quote(cls, adesso: datetime) -> dict:
        eventi = []
        for mid, casa, trasferta, probs, kickoff in cls.pianifica(adesso):
            eventi.append({"id": mid, "commence_time": _iso(kickoff, True),
                           "home_team": casa, "away_team": trasferta,
                           "last_update": _iso(adesso, True),
                           "libri": [cls._libro(*probs, adesso)]})
        return {
            "schema": "soccermath_live_odds_v1", "generato_il": _iso(adesso, True),
            "fonte": "the-odds-api", "piano": "starter", "regioni": "eu",
            "mercato": "h2h", "formato_quote": "decimal", "modalita": "fixture",
            "crediti": {"quota_mensile": 500, "usati_dall_ultimo_reset": 5,
                        "residui": 495},
            "n_leghe_ok": 1, "n_leghe_con_quote": 1, "n_leghe_richieste": 1,
            "n_eventi": len(eventi), "n_eventi_con_libri": len(eventi),
            "n_eventi_con_pinnacle": len(eventi), "n_libri_totale": len(eventi),
            "leghe_con_eventi_senza_libri": [], "errori": [],
            "leghe_mancanti_rispetto_a_prima": [],
            "leghe": {"Serie A": {"eventi": eventi}},
        }

    @classmethod
    def calendario(cls, adesso: datetime) -> dict:
        """Il turno raccontato a football-data: le STESSE partite, con gli
        STESSI id, perche' e' su quello che l'app costruisce ``match_id``."""
        return {"matches": [
            {"id": mid, "matchday": 7, "utcDate": _iso(kickoff, True),
             "status": "TIMED",
             "homeTeam": {"name": casa, "shortName": casa},
             "awayTeam": {"name": trasferta, "shortName": trasferta},
             "score": {"fullTime": {"home": None, "away": None}}}
            for mid, casa, trasferta, _probs, kickoff in cls.pianifica(adesso)
        ]}


def _iso(dt: datetime, _utc: bool = True) -> str:
    """L'istante come lo scrivono i file: UTC, ``…T…Z``."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Le scritture, contate
# ---------------------------------------------------------------------------

class _RegistroFinto:
    """I due storage in memoria dell'app, con la lista delle chiamate."""

    def __init__(self, semi=()):
        self.vivo = [dict(r) for r in semi]
        self.ombra = []
        self.chiamate = []

    def installa(self, patch):
        import registry_store as _rs

        def load_rows(*a, **k):
            self.chiamate.append(("load_rows", len(self.vivo)))
            return list(self.vivo), "fixture"

        def save_rows(rows, *a, **k):
            rows = [dict(r) for r in (rows or [])]
            self.chiamate.append(("save_rows", sorted(map(_id, rows))))
            self.vivo = rows
            return {"remoto": "ok", "backend": "fixture", "righe_scritte": len(rows)}

        def load_ombra(*a, **k):
            self.chiamate.append(("load_ombra_rows", len(self.ombra)))
            return list(self.ombra), "fixture"

        def save_ombra(rows, *a, **k):
            rows = [dict(r) for r in (rows or [])]
            self.chiamate.append(("save_ombra_rows", sorted(map(_id, rows))))
            self.ombra = rows
            return {"remoto": "ok", "backend": "fixture", "righe_scritte": len(rows)}

        patch(_rs, "load_rows", load_rows)
        patch(_rs, "save_rows", save_rows)
        patch(_rs, "load_ombra_rows", load_ombra)
        patch(_rs, "save_ombra_rows", save_ombra)

    @property
    def scritture(self):
        return [c for c in self.chiamate if c[0].startswith("save")]


def _riga_conclusa(adesso: datetime) -> dict:
    """Una riga GIUDICATA della famiglia Mercato: al Registro serve qualcosa da
    mostrare, e non deve essere toccata dal rinfresco delle righe in attesa."""
    import prediction_registry as pr
    passata = adesso - timedelta(days=9)
    return {
        "match_id": 7001, "home": "Atalanta", "away": "Lazio",
        "campionato": "Serie A", "giornata": 6,
        "data": passata.strftime("%d/%m/%Y %H:%M"),
        "pronostico_sicuro": "1 - Top Mix", "mercato_standard": "1", "top3": [],
        "prob_sicuro": 61.0, "risultati_attesi": "", "risultato_reale": "2-0",
        "esito": "✅", "tipo": "Top Mix", "stagione": "2026/27",
        "salvato_il": (passata - timedelta(days=1)).strftime("%d/%m/%Y %H:%M"),
        "origin": pr.ORIGIN_TOP_MIX,
        "selector_version": pr.SELECTOR_VERSION_MERCATO_V3,
        "model_variant": pr.MODEL_VARIANT_CURRENT,
        "model_version": pr.MODEL_VERSION_CURRENT,
        "rank": 1, "kickoff_utc": _iso(passata, True),
        "calculation_id": "fixture7001",
        pr.PROB_MERCATO_FIELD: 0.61, pr.QUOTA_MERCATO_FIELD: 1.75,
        pr.MERCATO_FONTE_FIELD: "pinnacle", pr.MERCATO_N_LIBRI_FIELD: 1,
        pr.ACCORDO_MODELLO_FIELD: True, pr.PROB_MODELLO_FIELD: 60.0,
        pr.QUOTE_LIVE_ISTANTE_FIELD: _iso(passata - timedelta(days=2), True),
        pr.PROB_MERCATO_PRIMA_FIELD: 0.61, pr.QUOTA_MERCATO_PRIMA_FIELD: 1.75,
        pr.PROB_MODELLO_PRIMA_FIELD: 60.0, pr.ACCORDO_MODELLO_PRIMA_FIELD: True,
        pr.QUOTE_LIVE_ISTANTE_PRIMA_FIELD: _iso(passata - timedelta(days=2), True),
    }


class _BaseQuoteFinte(unittest.TestCase):
    """Database in tmp, quote finte, orologio fermo, rete finta, registro in memoria.

    ``APP`` e' il file da eseguire: il test del punto 5 lo punta alla copia del
    codice di main, tutta il resto della fixture resta identico.
    """

    APP = APP_PATH
    FIXTURE = FixtureQuoteFinte

    @classmethod
    def setUpClass(cls):
        try:
            from streamlit.testing.v1 import AppTest  # noqa: F401
        except ImportError:                                     # pragma: no cover
            raise unittest.SkipTest("streamlit.testing.v1 non disponibile")

        import config
        import lista_giocate as lg
        import market_odds
        import prediction_registry as pr
        import requests
        import streamlit as st

        cls.ADESSO = datetime.now(timezone.utc).replace(microsecond=0)
        # Se il giorno vero e' troppo vicino al lunedi' di gioco, la «giornata»
        # sarebbe troppo corta per ospitare le partite del fixture: si sposta
        # l'orologio dell'app avanti di tre giorni (le partite restano nel futuro
        # reale, quindi il filtro «solo pre-partita» non le scarta).
        if lg.lunedi_gioco(cls.ADESSO) - cls.ADESSO < timedelta(hours=26):
            cls.ADESSO += timedelta(days=3)
        cls.partite = cls.FIXTURE.pianifica(cls.ADESSO)
        cls.payload = cls.FIXTURE.payload_quote(cls.ADESSO)
        cls.riga_seed = _riga_conclusa(cls.ADESSO)

        cls.tmp = Path(tempfile.mkdtemp(prefix="sm_apptest_pron_"))
        cls._link_del_database()
        (cls.tmp / "live_odds.json").write_text(
            json.dumps(cls.payload, ensure_ascii=False), encoding="utf-8")
        cls.prediction_file = cls.tmp / "predictions.json"
        cls.prediction_file.write_text(
            json.dumps({"data": [cls.riga_seed]}, ensure_ascii=False), encoding="utf-8")

        cls._patches = []

        def patch(target, attr, valore):
            cls._patches.append(mock.patch.object(target, attr, valore))
            cls._patches[-1].start()

        patch(config, "DATABASE_DIR", cls.tmp)
        patch(config, "PREDICTIONS_FILE", str(cls.prediction_file))
        patch(market_odds, "_adesso_utc", lambda: cls.ADESSO)

        cls.registro = _RegistroFinto([cls.riga_seed])
        cls.registro.installa(patch)

        # ``save_predictions`` fa sempre un backup prima di scrivere: contare i
        # backup conta le scritture del file locale (che qui sta nel tmp).
        cls.scritture = []
        cls._backup_originale = pr.backup_prediction_file

        def backup(path, *a, **k):
            cls.scritture.append(str(path))
            return cls._backup_originale(path, *a, **k)

        patch(pr, "backup_prediction_file", backup)

        # --- rete finta: il calendario del fixture, nessun metodo di scrittura ---
        cls.chiamate = []
        risposte = {"SA": cls.FIXTURE.calendario(cls.ADESSO)}

        def fake_get(url, **kw):
            cls.chiamate.append(("GET", url))
            code = url.rstrip("/").split("/")[-2] if "/matches" in url else ""
            return _Resp(risposte.get(code, {"matches": []}))

        def niente_rete(metodo):
            def _f(url, **kw):
                cls.chiamate.append((metodo, url))
                raise AssertionError(f"{metodo} di rete non ammesso in test: {url}")
            return _f

        patch(requests, "get", fake_get)
        for metodo in ("put", "post", "patch", "delete"):
            patch(requests, metodo, niente_rete(metodo))
        patch(time, "sleep", lambda s: None)

        # La cache ``@st.cache_data`` e' di processo e condivisa fra gli AppTest
        # di file diversi: svuotarla, o il click rilegge dati di un altro fixture.
        st.cache_data.clear()

        cls.at = AppTest.from_file(cls.APP, default_timeout=600)
        cls.at.run(timeout=900)
        cls.eccezioni(cls.at, "apertura della pagina")
        cls.senza_modello(cls.at)
        cls.at.run(timeout=900)
        cls.eccezioni(cls.at, "pagina con il giro del modello non disponibile")

    @classmethod
    def _link_del_database(cls):
        for f in sorted(Path(REALE_DATABASE).iterdir()):
            if f.is_dir() or f.name in ("live_odds.json", "predictions.json"):
                continue
            try:
                (cls.tmp / f.name).symlink_to(f)
            except OSError:
                shutil.copy2(f, cls.tmp / f.name)

    @classmethod
    def senza_modello(cls, at):
        """Dichiara il giro del modello NON disponibile, in sola lettura.

        Lo stato si scrive direttamente in sessione perche' AppTest esegue lo
        script in un namespace separato (stessa strada di
        ``test_apptest_navigazione``): le celle di «Modello %» restano vuote e
        deve bastare la caption dello stato."""
        at.session_state["confronto_modello_stato"] = "non_disponibile"
        at.session_state["confronto_modello_righe"] = []
        at.session_state["confronto_modello_errore"] = "RuntimeError: giro giù"
        at.session_state["confronto_modello_1x2"] = []

    @classmethod
    def tearDownClass(cls):
        for patcher in reversed(getattr(cls, "_patches", [])):
            try:
                patcher.stop()
            except Exception:                                   # pragma: no cover
                pass
        import prediction_registry as pr
        pr.backup_prediction_file = cls._backup_originale
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ------------------------------------------------------------------ aiuti
    @staticmethod
    def eccezioni(at, fase: str):
        e = [str(x.value) for x in at.exception]
        if e:
            raise AssertionError(f"eccezioni in {fase}: {e[:2]}")

    @staticmethod
    def _pulsante(at, etichetta: str):
        for b in at.button:
            if etichetta in (b.label or ""):
                return b
        raise AssertionError(f"pulsante {etichetta!r} non trovato")

    def _nessun_non_numero(self, df):
        """Nessuna cella di nessuna tabella rende un non-numero.

        Si guarda il DataFrame RESO (dtype e celle), perche' e' li' che un
        ``NaN`` numerico ricompare quando qualcuno trascrive la tabella o la
        legge da AppTest: le colonne che possono mancare di un numero sono di
        TESTO, con stringa vuota.
        """
        for colonna in df.columns:
            for cella in df[colonna]:
                test = str(cella).strip().lower()
                self.assertNotIn(test, ("nan", "none", "nat"),
                                 f"cella di {colonna!r} che rende {test!r}")
                self.assertNotIn("n/d", test, "nessuno «n/d» in una cella in tabella")

    @staticmethod
    def _toggle(at, chiave: str, valore: bool):
        """Accende/spegne l'interruttore del periodo e ridisegna."""
        for t in at.toggle:
            if (t.key or "") == chiave:
                t.set_value(valore)
                at.run(timeout=900)
                return
        raise AssertionError(f"interruttore {chiave!r} non trovato")

    @classmethod
    def _premi_click(cls, at, etichetta: str):
        cls._pulsante(at, etichetta).click()
        at.run(timeout=900)
        cls.eccezioni(at, f"click su {etichetta}")

    @staticmethod
    def _df(at, scheda, indice=0):
        """Il DataFrame reso nella scheda, come pandas: celle vere, non testo."""
        tabelle = _elementi_della_tab(at, scheda, "dataframe")
        if len(tabelle) <= indice:
            raise AssertionError(f"{scheda}: {len(tabelle)} tabelle, chiesta la {indice}")
        val = getattr(tabelle[indice], "value", None)
        if val is not None and hasattr(val, "data"):
            val = val.data
        return val

    @classmethod
    def _uniche(cls, at, scheda):
        """I testi in vista della scheda, uno per elemento.

        Il lettore di ``_testi_della_tab`` raccoglie piu' attributi dello stesso
        elemento (``body`` e ``value`` per una caption): le righe sono duplicate,
        e contarle cosi' direbbe il doppio di quanto vede una persona."""
        return list(dict.fromkeys(_testi_della_tab(at, scheda)[0]))

    @classmethod
    def _testo(cls, at, scheda):
        return " \n".join(cls._uniche(at, scheda))

    def righe_su_disco(self):
        return json.loads(self.prediction_file.read_text(encoding="utf-8"))["data"]


class TestSchedaPronostici(_BaseQuoteFinte):
    """Le schede nuove: un solo AppTest, i metodi nell'ordine dei numeri."""

    # -- 1. prima del click -------------------------------------------------
    def test_01_prima_del_click_la_scheda_non_mostra_numeri(self):
        testo = self._testo(self.at, SCHEDA_PRONOSTICI)
        self.assertIn(ETICHETTA_CALCOLA, testo)
        # La riga cita la data SCRITTA dal Registro (``salvato_il``), non un
        # orario ricostruito dalla partita: qui si controlla che sia quella.
        from lista_giocate import GIORNI_SETTIMANA_IT
        istante = datetime.strptime(self.riga_seed["salvato_il"], "%d/%m/%Y %H:%M")
        attesa = (f"Ultima registrazione: {GIORNI_SETTIMANA_IT[istante.weekday()]} "
                  f"{istante.strftime('%d/%m/%Y')}, ore {istante.strftime('%H:%M')}")
        self.assertIn(attesa, testo, "la riga dice l'ultima scrittura del Registro")
        self.assertIn("Premi il pulsante per calcolare i pronostici della giornata.",
                      testo)
        # Sotto il pulsante non c'e' nessun'altra frase: l'aiuto che spiegava il
        # giro ("Calcola le scelte della giornata sulle quote del file... Nessun
        # servizio esterno viene chiamato.") e' tolto, e con lui la promessa che
        # nessuno ha chiesto di leggere ogni volta.
        self.assertNotIn("Nessun servizio esterno viene chiamato", testo)
        self.assertNotIn("Calcola le scelte della giornata", testo)
        self.assertEqual([], _elementi_della_tab(self.at, SCHEDA_PRONOSTICI, "dataframe"),
                         "nessuna tabella, prima del click")
        self.assertEqual([], _elementi_della_tab(self.at, SCHEDA_PRONOSTICI, "expander"),
                         "e nessun riquadro chiuso")
        for parola in ("Quote %", "Modello %", "Quando", "Le scelte più sicure"):
            with self.subTest(parola=parola):
                self.assertNotIn(parola, testo)
        self.assertEqual([], self.scritture, "aprire la pagina non scrive il Registro")
        self.assertEqual([], self.registro.scritture,
                         f"nessuna scrittura nel registro: {self.registro.chiamate}")

    # -- 2. la scheda Pareggi non ha bisogno di click ----------------------
    def test_02_pareggi_elenca_le_X_del_periodo(self):
        import lista_giocate as lg
        res = lg.calcola_lista_giocate(self.payload, adesso_utc=self.ADESSO)
        in_periodo = lg.giocate_nel_periodo(res["giocate"], self.ADESSO,
                                            lg.PERIODO_GIORNATA)
        attesi = [g for g in in_periodo if str(g.get("giocata") or "").strip() == "X"]
        self.assertEqual(4, len(attesi), "il fixture ha quattro partite nel periodo")

        self.assertIn("Anche il pareggio più probabile esce circa 1 volta su 3.",
                      self._testo(self.at, SCHEDA_PAREGGI))
        df = self._df(self.at, SCHEDA_PAREGGI)
        self.assertEqual(COLONNE, list(df.columns), "le sei colonne promesse")
        self.assertEqual(len(attesi), len(df), "una riga per ogni pareggio del periodo")
        self.assertEqual(["X"] * len(df), list(df["Pronostico"]),
                         "la scheda Pareggi non mostra altri esiti")
        self.assertEqual([round(float(g["probabilita"]) * 100.0, 1)
                          for g in sorted(attesi, key=lambda g: -g["probabilita"])],
                         [round(float(x), 1) for x in df["Quote %"]],
                         "in ordine di probabilita', come le altre tabelle")
        self.assertEqual(["Torino - Como", "Genoa - Fiorentina", "Napoli - Venezia",
                          "Roma - Lecce"], list(df["Partita"]))
        self.assertEqual([], self.scritture, "la scheda Pareggi legge e non scrive niente")
        self.assertEqual([], _elementi_della_tab(self.at, SCHEDA_PAREGGI, "button"),
                         "e non ha pulsanti da premere")

    # -- 3. il click --------------------------------------------------------
    def test_03_il_click_calcola_e_lascia_la_tabella_in_vista(self):
        import app as app_mod
        import lista_giocate as lg
        self.assertIsNotNone(self._pulsante(self.at, ETICHETTA_CALCOLA))
        self._premi_click(self.at, ETICHETTA_CALCOLA)

        # Le righe attese sono quelle del SELETTORE sulle stesse quote: qui si
        # verifica l'aggancio fra il pulsante e la tabella, non la matematica.
        attese, _info = app_mod.righe_mercato_dalle_quote(self.payload, self.ADESSO)
        in_periodo = lg.righe_mercato_nel_periodo(attese, self.ADESSO,
                                                  lg.PERIODO_GIORNATA)
        self.assertEqual(4, len(attese), "quattro scelte sopra il 55% nel file")
        self.assertEqual(3, len(in_periodo), "una gioca dopo lunedi': e' fuori periodo")

        df = self._df(self.at, SCHEDA_PRONOSTICI)
        self.assertEqual(COLONNE + ["Gol", "Insieme %"], list(df.columns))
        self.assertEqual(len(in_periodo), len(df))
        self.assertEqual(["Roma - Lecce", "Genoa - Fiorentina", "Napoli - Venezia"],
                         list(df["Partita"]), "la tabella e' l'elenco delle scelte")
        self.assertEqual([66.0, 60.0, 58.0], [round(float(x), 1) for x in df["Quote %"]])
        self.assertEqual(["1", "1", "2"], list(df["Pronostico"]))
        # Ogni riga porta la DATA DELLA PROPRIA partita (non un turno unico):
        # l'aggancio e' riga per riga, cosi' un disallineamento di una cella
        # verrebbe visto.
        calcio = {f"{casa} - {trasferta}": kickoff
                  for _mid, casa, trasferta, _p, kickoff in self.partite}
        self.assertEqual([_quando_italiano(calcio[p]) for p in df["Partita"]],
                         list(df["Quando"]), "data e ora italiane nella colonna stretta")
        # «Modello %» e «Quota» sono TESTO formattato: qui il giro del modello
        # non c'e', quindi le tre celle sono tre stringhe vuote. Non un NaN, non
        # un "n/d", non una colonna numerica che si trascrive "nan".
        self.assertEqual(["", "", ""], list(df["Modello %"]), list(df["Modello %"]))
        self._nessun_non_numero(df)
        # ...e vale anche per la tabella dei pareggi, che di righe senza lettura
        # del modello ne ha di mestiere.
        self._nessun_non_numero(self._df(self.at, SCHEDA_PAREGGI))
        uniche = self._uniche(self.at, SCHEDA_PRONOSTICI)
        testo = " \n".join(uniche)
        self.assertIn("3 partite in tabella.", testo)
        self.assertIn("Altre 1 nei prossimi giorni.", testo,
                      "le partite fuori periodo si dichiarano")
        self.assertNotIn("Modello %: non disponibile", testo,
                         "la caption non parla piu' dello stato del modello")
        self.assertNotIn("dopo lunedì", testo, "e non nomina l'interruttore")
        self.assertNotIn("Multiple", testo, "né manda il lettore in un'altra scheda")
        self.assertNotIn("Accendi", testo, "l'interruttore sta sopra le schede: non serve dirlo")
        # L'esito del click sta in UNA riga, e le righe restano in sessione.
        self.assertRegex(testo, r"Registrate \d+ giocate nuove|Niente di nuovo da registrare")
        self.assertEqual(2, len([t for t in uniche
                                 if "Registrate" in t or "Niente di nuovo" in t]),
                         "esiti separati 1X2 e O/U")
        salvate = self.at.session_state[app_mod.CHIAVE_PRONOSTICI]
        self.assertEqual(4, len(salvate["righe"]),
                         "in sessione stanno TUTTE le righe del calcolo: il periodo "
                         "e' un filtro di lettura, non un ricalcolo")
        self.assertEqual(lg.ETICHETTA_PERIODO_GIORNATA, salvate["periodo"],
                         "il calcolo e' congelato al periodo del click")
        # E il Registro ha le righe nuove: stesse partite della tabella, perche'
        # il pulsante promette di registrarle.
        self.assertIn(111, sorted(_id(r) for r in self.registro.vivo))
        self.assertIn(113, sorted(_id(r) for r in self.registro.vivo))

    # -- 4. la colonna Quota ------------------------------------------------
    def test_04_quota_di_ogni_riga_e_la_sua_stima_bet365(self):
        import lista_giocate as lg
        df = self._df(self.at, SCHEDA_PRONOSTICI)
        self.assertEqual(3, len(df))
        prob = {"Genoa - Fiorentina": 0.60, "Roma - Lecce": 0.66,
                "Napoli - Venezia": 0.58}
        for partita, p in prob.items():
            with self.subTest(partita=partita):
                riga = df[df["Partita"] == partita].iloc[0]
                attesa = lg.stima_quota_b365_1x2(p, "Serie A")
                self.assertIsNotNone(attesa, "nel fixture la stima dev'esserci")
                # La cella e' la stima scritta in italiano: 1,55 e non "nan",
                # non 1.55, non "n/d".
                self.assertEqual(lg.quota_italiana(attesa), riga["Quota"],
                                 "la «Quota» della riga dev'essere la stima bet365 "
                                 "di QUELLA riga")
        # Due decimali con la virgola, come promesso, e nessun numero inventato:
        # ogni cella e' finita e maggiore di uno.
        for q in df["Quota"]:
            self.assertRegex(str(q), r"^\d+,\d{2}$")
            self.assertGreater(float(str(q).replace(",", ".")), 1.0)
        # Piu' probabilita' vuol dire quota piu' bassa: se la colonna fosse
        # spostata di una riga, questo si romperebbe.
        per_quota = sorted(float(str(q).replace(",", ".")) for q in df["Quota"])
        by_quote = df.sort_values("Quote %", ascending=False)
        self.assertEqual(per_quota,
                         sorted(float(str(q).replace(",", ".")) for q in by_quote["Quota"]),
                         "l'ordine della tabella e' «Quote %» decrescente")

    # -- 5. il clic su una riga apre la scheda, senza scrivere -------------
    def test_05_cliccare_una_riga_apre_la_scheda_di_quella_partita(self):
        import app as app_mod
        self.scritture.clear()
        self.registro.chiamate.clear()
        self.chiamate.clear()
        # La selezione di ``st.dataframe`` si pilota da ``session_state``: sono
        # POSIZIONI nella tabella mostrata (1 = Genoa - Fiorentina, la seconda).
        # La chiave e' quella con cui la tabella e' disegnata ORA: ogni riga
        # cliccata alza la versione della chiave (chiave_tabella_corrente).
        chiave = app_mod.chiave_tabella_corrente("pronostici_tabella_periodo",
                                                 self.at.session_state)
        self.at.session_state[chiave] = {
            "selection": {"rows": [1], "columns": [], "cells": []}}
        self.at.run(timeout=900)
        self.eccezioni(self.at, "clic sulla riga della tabella")
        titoli = [str(getattr(el, "value", "") or "").strip() for el in self.at.markdown]
        atteso = "### " + _titolo_atteso("Genoa", "Fiorentina")
        self.assertIn(atteso, titoli,
                      "il riquadro dev'essere la scheda della partita di quella riga")
        blocco = "\n".join(titoli[titoli.index(atteso):])
        self.assertIn("Probabilità (dalle quote dei bookmaker)", blocco)
        self.assertRegex(blocco, r"Quote % \d+,\d")
        # Una lettura non e' una scrittura: nessun salvataggio, nessuna PUT/POST.
        self.assertEqual([], self.scritture, "il clic su una riga non scrive il Registro")
        self.assertEqual([], self.registro.scritture,
                         f"nessuna scrittura nel registro: {self.registro.chiamate}")
        self.assertEqual([], [c for c in self.chiamate if c[0] != "GET"])
        # ...e la tabella e' sempre lei, con le sue righe e gli stessi numeri.
        self.assertEqual(3, len(self._df(self.at, SCHEDA_PRONOSTICI)))

    def test_06_un_altra_riga_apre_un_altra_partita(self):
        import app as app_mod
        chiave = app_mod.chiave_tabella_corrente("pronostici_tabella_periodo",
                                                 self.at.session_state)
        self.at.session_state[chiave] = {
            "selection": {"rows": [0], "columns": [], "cells": []}}
        self.at.run(timeout=900)
        self.eccezioni(self.at, "clic sulla prima riga")
        titoli = [str(getattr(el, "value", "") or "").strip() for el in self.at.markdown]
        self.assertIn("### " + _titolo_atteso("Roma", "Lecce"), titoli,
                      "la riga 0 e' Roma - Lecce, la piu' probabile")
        self.assertNotIn("### " + _titolo_atteso("Genoa", "Fiorentina"), titoli,
                         "il riquadro e' quello dell'ultima riga cliccata, non il precedente")

    def test_07_il_clic_sulla_tabella_dei_pareggi_fa_lo_stesso(self):
        df_x = self._df(self.at, SCHEDA_PAREGGI)
        casa, trasferta = [s.strip() for s in str(df_x.iloc[2]["Partita"]).split(" - ", 1)]
        self.assertEqual("Napoli - Venezia", f"{casa} - {trasferta}")
        self.scritture.clear()
        self.registro.chiamate.clear()
        import app as app_mod
        chiave = app_mod.chiave_tabella_corrente("pareggi_tabella_periodo",
                                                 self.at.session_state)
        self.at.session_state[chiave] = {
            "selection": {"rows": [2], "columns": [], "cells": []}}
        self.at.run(timeout=900)
        self.eccezioni(self.at, "clic sulla terza riga dei pareggi")
        titoli = [str(getattr(el, "value", "") or "").strip() for el in self.at.markdown]
        self.assertIn("### " + _titolo_atteso(casa, trasferta), titoli,
                      "anche qui il clic sulla riga apre la sua partita")
        self.assertEqual([], self.scritture, "e non scrive niente")
        self.assertEqual([], self.registro.scritture)

    # -- 8. il periodo e' un'altra giornata: si chiede un nuovo click ------
    def test_08_il_periodo_e_un_calcolo_nuovo_non_una_tabella_mista(self):
        """Accendere «Mostra anche i prossimi giorni» vuol dire chiedere un'altra
        giornata: la tabella dei pronostici si ritira e chiede un nuovo click
        (senza scrivere ne' cancellare niente), la scheda Pareggi — che un click
        non ce l'ha — si allunga e basta.

        E' il patto del punto 2 della commessa: la tabella che si legge e'
        QUELLA che il pulsante ha calcolato, mai un miscuglio di due periodi.
        """
        import app as app_mod
        chiuse = len(self._df(self.at, SCHEDA_PRONOSTICI))
        x_prima = len(self._df(self.at, SCHEDA_PAREGGI))
        self.registro.chiamate.clear()
        self.scritture.clear()
        self._toggle(self.at, app_mod.CHIAVE_PROSSIMI_GIORNI, True)
        try:
            self.assertEqual([], _elementi_della_tab(self.at, SCHEDA_PRONOSTICI, "dataframe"),
                             "con il periodo cambiato la tabella si ritira")
            self.assertIn("Premi il pulsante per calcolare i pronostici della giornata.",
                          self._testo(self.at, SCHEDA_PRONOSTICI))
            self.assertEqual([], self.registro.scritture,
                              "cambiare periodo non scrive e non cancella nulla")
            self.assertEqual([], self.scritture)
            # I pareggi seguono lo STESSO interruttore (e' uno stato condiviso).
            self.assertEqual(x_prima + 1, len(self._df(self.at, SCHEDA_PAREGGI)))
            # Al nuovo click la tabella torna, e con la partita dopo lunedi'
            # dentro il periodo: niente piu' conto delle righe nascoste.
            self._premi_click(self.at, ETICHETTA_CALCOLA)
            df = self._df(self.at, SCHEDA_PRONOSTICI)
            self.assertEqual(chiuse + 1, len(df), "la partita lontana si aggiunge")
            self.assertIn("Milan - Juventus", list(df["Partita"]))
            self.assertIn("4 partite in tabella.", self._testo(self.at, SCHEDA_PRONOSTICI))
            self.assertNotIn("nei prossimi giorni", self._testo(self.at, SCHEDA_PRONOSTICI),
                             "con l'interruttore acceso non c'e' niente da dichiarare")
            # ⏳ solo sulla riga lontana, e la sua legenda una volta sola.
            lontane = [q for q in df["Quando"] if str(q).endswith("⏳")]
            self.assertEqual(1, len(lontane), list(df["Quando"]))
            lunga = [p for p in self.partite if p[0] == 115][0][4]
            self.assertEqual(_quando_italiano(lunga) + " ⏳", lontane[0])
            parti = _testi_della_tab(self.at, SCHEDA_PRONOSTICI)[0]
            self.assertEqual(1, len([p for p in dict.fromkeys(parti)
                                     if "quote ancora provvisorie" in p]),
                             "la legenda del marcatore sta sotto la tabella, una volta")
        finally:
            self._toggle(self.at, app_mod.CHIAVE_PROSSIMI_GIORNI, False)
            self.at.run(timeout=900)

    # -- 13. zero "NaN" e zero "None" nel testo reso ----------------------
    NON_NUMERO = re.compile(r"\b(nan|none|nat)\b", re.IGNORECASE)

    def test_13_nel_testo_reso_zero_nan_zero_none(self):
        """Il testo reso di Pronostici (dopo il click) e di Pareggi non contiene
        nessuna occorrenza di "NaN", "nan", "None": zero, non "una di meno".

        Le celle si guardano tre volte, perche' i tre lettori sono tre posti
        diversi dove il non-numero ricomparirebbe: le frasi della scheda, le
        celle come il browser le riceve (``_raccogli_da_df``) e la trascrizione
        ``to_string`` della tabella, che e' quella di chi copia o stampa la
        vista. Il fixture non ha il giro del modello: TUTTE le righe sono senza
        lettura, e questo e' esattamente il caso che la commessa chiede di
        provare (una riga con «Modello %» vuoto non deve scrivere niente).
        """
        from test_apptest_topmix_presentazione import _raccogli_da_df
        if not _elementi_della_tab(self.at, SCHEDA_PRONOSTICI, "dataframe"):
            # il metodo non deve dipendere dall'ordine: se la tabella non c'e',
            # il click lo fa qui
            self._premi_click(self.at, ETICHETTA_CALCOLA)
        for scheda in (SCHEDA_PRONOSTICI, SCHEDA_PAREGGI):
            with self.subTest(scheda=scheda):
                pezzi = list(_testi_della_tab(self.at, scheda)[0])
                for el in _elementi_della_tab(self.at, scheda, "dataframe"):
                    pezzi += [str(c) for c in _raccogli_da_df(el)]
                    df = getattr(el, "value", None)
                    if df is not None and hasattr(df, "to_string"):
                        pezzi.append(df.to_string(index=False))
                self.assertTrue(pezzi, f"{scheda}: nessuna cosa resa da controllare")
                testo = " \n".join(pezzi)
                self.assertEqual([], self.NON_NUMERO.findall(testo),
                                 f"non-numero nel testo reso di {scheda}: "
                                 f"{testo[:240]!r}")
                self.assertNotIn("n/d", testo.replace("Modello % per i gol: n/d", ""),
                                 "n/d ammesso solo per O/U")
                self.assertNotIn("Non disponibile", testo)
        # e la prova non deve essere vuota: almeno una riga senza modello, qui e
        # nella tabella dei pareggi, dev'esserci per davvero.
        for scheda in (SCHEDA_PRONOSTICI, SCHEDA_PAREGGI):
            df = self._df(self.at, scheda)
            vuote = sum(1 for v in df["Modello %"] if str(v) == "")
            self.assertGreaterEqual(vuote, 1, f"{scheda}: nessuna cella vuota da provare")

    # -- 14. la vista tecnica del Top Mix sta nei Dettagli dei Pronostici ---
    def test_14_la_vista_tecnica_del_top_mix_sta_nei_dettagli_dei_pronostici(self):
        """La tabella tecnica «Top Mix — scelte del mercato» (fonte, eta' delle
        quote, probabilita' del modello, segnale d'accordo) sta nel riquadro
        chiuso «Dettagli» della scheda Pronostici, dopo il click: TUTTE le righe
        del calcolo (in sessione stanno tutte, il periodo e' un filtro di
        lettura della tabella in vista), e nessuna cella "None"/"nan" (vuota).
        Nei Dettagli della scheda Multiple non c'e' piu'."""
        import app as app_mod
        if not _elementi_della_tab(self.at, SCHEDA_PRONOSTICI, "dataframe"):
            self._premi_click(self.at, ETICHETTA_CALCOLA)
        _fuori, dentro = _testi_della_tab(self.at, SCHEDA_PRONOSTICI)
        self.assertIn("Top Mix — scelte del mercato (vista tecnica)", " \n".join(dentro))
        tabelle = _elementi_della_tab(self.at, SCHEDA_PRONOSTICI, "dataframe")
        self.assertEqual(2, len(tabelle), "la tabella in vista e quella tecnica nei Dettagli")
        tecnica = tabelle[1].value
        if hasattr(tecnica, "data"):
            tecnica = tecnica.data
        self.assertEqual(app_mod.COLONNE_TOP_MIX_MERCATO + ["Lega", "Inizio"],
                         list(tecnica.columns))
        in_vista = self._df(self.at, SCHEDA_PRONOSTICI)
        self.assertGreaterEqual(len(tecnica), len(in_vista))
        partite_tecniche = {str(p).replace(" vs ", " - ") for p in tecnica["Partita"]}
        for partita in in_vista["Partita"]:
            self.assertIn(str(partita), partite_tecniche)
        self.assertEqual([], self.NON_NUMERO.findall(tecnica.to_string(index=False)))
        self.assertNotIn("n/d", tecnica.to_string(index=False))
        _fuori_m, dentro_m = _testi_della_tab(self.at, SCHEDA_MULTIPLE)
        self.assertNotIn("vista tecnica", " \n".join(dentro_m))

    # -- 9. secondo click: una scrittura per click, nessuna riga doppia ----
    def test_09_secondo_click_non_duplica_niente(self):
        ids_prima = sorted(_id(r) for r in self.registro.vivo)
        self.assertGreater(len(ids_prima), 1, "il primo click deve aver scritto")
        self.registro.chiamate.clear()
        self.scritture.clear()
        self._premi_click(self.at, ETICHETTA_CALCOLA)
        self.assertEqual(ids_prima, sorted(_id(r) for r in self.registro.vivo),
                         "lo stesso turno di quote non aggiunge righe doppie")
        scritture = self.registro.scritture
        self.assertLessEqual(len([c for c in scritture if c[0] == "save_rows"]), 1,
                             f"una scrittura per click, anche il secondo: {scritture}")
        self.assertLessEqual(len(self.scritture), 1,
                             f"una scrittura del file per click: {self.scritture}")
        # Il file locale e il registro in memoria sono lo stesso elenco: la
        # scheda «Com'e' andata» legge quelle righe li', non qui.
        self.assertEqual(ids_prima, sorted(_id(r) for r in self.righe_su_disco()))
        self.assertEqual(1, len([b for b in _elementi_della_tab(
            self.at, SCHEDA_PRONOSTICI, "button") if ETICHETTA_CALCOLA in (b.label or "")]),
            "il pulsante resta uno solo, anche dopo due click")

    # -- 10. il punto 6 della PR #64 vale anche nelle schede nuove ---------
    def test_10_in_vista_niente_gergo(self):
        for scheda in (SCHEDA_PRONOSTICI, SCHEDA_PAREGGI, SCHEDA_MULTIPLE):
            testo = self._testo(self.at, scheda).lower()
            self.assertTrue(testo, f"la scheda {scheda} e' bianca")
            for parola in PAROLE_VIETATE:
                with self.subTest(scheda=scheda, parola=parola):
                    self.assertIsNone(re.search(parola, testo, re.IGNORECASE),
                                      f"parola vietata in vista su {scheda}: {parola!r}")

    # -- 11. le altre schede non hanno perso niente ------------------------
    def test_11_registro_e_multiple_restano_come_erano(self):
        etichette = [str(e.label or "") for e in _elementi_della_tab(
            self.at, SCHEDA_REGISTRO, "expander")]
        self.assertTrue(any(e.strip().endswith("Dettagli") for e in etichette), etichette)
        df_x = self._df(self.at, SCHEDA_PAREGGI)
        self.assertEqual(COLONNE, list(df_x.columns))
        testo_multipla = self._testo(self.at, SCHEDA_MULTIPLE)
        self.assertIn("Le più probabili", testo_multipla)
        # I riquadri delle proposte: uno per numero di partite che la ricerca
        # trova su QUESTE quote (stessa funzione, stesso periodo), con il nome
        # Singola/Doppia/Tripla/Quadrupla e il pulsante del calcolatore; la
        # tabella «Per raddoppiare» sta nei Dettagli.
        import app as app_mod
        import lista_giocate as lg
        res = lg.calcola_lista_giocate(self.payload, adesso_utc=self.ADESSO)
        in_periodo = lg.giocate_nel_periodo(res["giocate"], self.ADESSO, "giornata")
        per_k = {k: v for k, v in lg.cerca_proposta_multipla(in_periodo)["per_k"].items() if v}
        chiavi = sorted(int((b.key or "").rsplit("_", 1)[1]) for b in
                        _elementi_della_tab(self.at, SCHEDA_MULTIPLE, "button")
                        if (b.key or "").startswith("prova_quote_b365_"))
        self.assertEqual(sorted(per_k), chiavi, "un riquadro per proposta trovata")
        for k in per_k:
            with self.subTest(k=k):
                self.assertIn(app_mod.NOMI_MULTIPLA_PER_K[k], testo_multipla)
        if not per_k:
            self.assertIn(app_mod.FRASE_NESSUNA_COMBINAZIONE, testo_multipla)
        self.assertNotIn("Per raddoppiare", testo_multipla)
        etichette_riquadri = "\n".join(str(e.label or "") for e in self.at.expander)
        self.assertIn("Prova la tua giocata", etichette_riquadri,
                      "il calcolatore resta nel suo riquadro")
        # Il pulsante di registrazione NON sta piu' nella scheda delle giocate.
        self.assertEqual([], [b for b in _elementi_della_tab(self.at, SCHEDA_MULTIPLE, "button")
                              if ETICHETTA_CALCOLA in (b.label or "")])

    # -- 12. l'interruttore del periodo sta sopra le schede ----------------
    def test_12_l_interruttore_e_sopra_le_schede_e_vale_per_tre_schede(self):
        """Un widget solo, fuori da tutte le schede, e il suo effetto si vede
        nello stesso momento su Pronostici, Pareggi e Multiple.

        La posizione e' la promessa: l'interruttore non sta piu' in testa alla
        scheda Multiple (dove chi leggeva i Pronostici doveva andarlo a cercare),
        e nessuna frase in vista lo nomina.
        """
        import app as app_mod
        comandi = [t for t in self.at.toggle
                   if (t.key or "") == app_mod.CHIAVE_PROSSIMI_GIORNI]
        self.assertEqual(1, len(comandi),
                         "un solo interruttore del periodo in tutta la pagina")
        for scheda in (SCHEDA_PRONOSTICI, SCHEDA_PAREGGI, SCHEDA_MULTIPLE, SCHEDA_REGISTRO):
            self.assertEqual([], _elementi_della_tab(self.at, scheda, "toggle"),
                              f"l'interruttore non deve stare dentro {scheda!r}")
        # Il testo del comando resta pulito dal gergo vietato (la pagina non lo
        # contiene piu' dentro una scheda: va controllato dove sta davvero).
        parole = ((comandi[0].label or "") + " " + str(getattr(comandi[0], "help", "") or "")).lower()
        for vietata in PAROLE_VIETATE:
            with self.subTest(parola=vietata):
                self.assertIsNone(re.search(vietata, parole, re.IGNORECASE),
                                  f"gergo nel comando del periodo: {vietata!r}")

        prima = {"pronostici": self._testo(self.at, SCHEDA_PRONOSTICI),
                 "pareggi": len(self._df(self.at, SCHEDA_PAREGGI)),
                 "multiple": sum(len(e.value) for e in
                                 _elementi_della_tab(self.at, SCHEDA_MULTIPLE, "dataframe"))}
        self._toggle(self.at, app_mod.CHIAVE_PROSSIMI_GIORNI, True)
        try:
            # Pronostici: il periodo nuovo e' un altro calcolo, la tabella si
            # ritira (test_08) — cio' prova che la scheda legge lo stesso stato.
            self.assertIn("Premi il pulsante per calcolare i pronostici della giornata.",
                          self._testo(self.at, SCHEDA_PRONOSTICI))
            # Pareggi: una X in piu', senza premere niente.
            self.assertEqual(prima["pareggi"] + 1, len(self._df(self.at, SCHEDA_PAREGGI)))
            # Multiple: le sue tabelle si allungano con la partita lontana.
            after = sum(len(e.value) for e in
                        _elementi_della_tab(self.at, SCHEDA_MULTIPLE, "dataframe"))
            self.assertGreater(after, prima["multiple"],
                               "la scheda Multiple segue lo stesso interruttore")
        finally:
            self._toggle(self.at, app_mod.CHIAVE_PROSSIMI_GIORNI, False)
            self.at.run(timeout=900)
        self.assertEqual(prima["pareggi"], len(self._df(self.at, SCHEDA_PAREGGI)),
                         "spento, la tabella dei pareggi torna com'era")


# ---------------------------------------------------------------------------
# Punto 5: le scritture del pulsante nuovo = quelle del pulsante vecchio.
# ---------------------------------------------------------------------------

class TestParitaScrittureColPulsanteVecchio(unittest.TestCase):
    """Lo stesso fixture eseguito su ``app.py`` di adesso e su quello di ``main``.

    Il file di main viene materializzato accanto all'originale
    (``_app_pulsante_vecchio.py``, cancellato a fine classe) perche' ha bisogno
    degli stessi moduli fratelli; le due esecuzioni usano due cartelle
    temporanee separate e li confronta campo per campo. Tolti i campi che
    registrano il momento dell'esecuzione — ``salvato_il`` (``VOLATILI``) e le
    quattro impronte derivate dall'istante e dallo snapshot letto — perche'
    quelli cambiano anche fra due esecuzioni dello stesso codice.
    """

    @classmethod
    def setUpClass(cls):
        try:
            from streamlit.testing.v1 import AppTest  # noqa: F401
        except ImportError:                                     # pragma: no cover
            raise unittest.SkipTest("streamlit.testing.v1 non disponibile")
        # Il file di main, con il pulsante vecchio: scritto qui e cancellato in
        # tearDownClass.
        try:
            src = subprocess.check_output(
                ["git", "-C", REPO_ROOT, "show", f"{BASE_MAIN}:SoccerMath/app.py"],
                stderr=subprocess.DEVNULL).decode("utf-8")
        except Exception:                                       # pragma: no cover
            raise unittest.SkipTest(f"il commit base {BASE_MAIN} non e' raggiungibile "
                                    "(clone shallow?): niente confronto con main")
        import lista_giocate as lg
        assert ETICHETTA_VECCHIO in src, "il file di main non e' quello atteso"
        assert "def _scheda_pronostici" not in src, "il file di main ha gia' le schede nuove"
        cls.vecchio = Path(HERE) / "_app_pulsante_vecchio.py"
        cls.vecchio.write_text(src, encoding="utf-8")

        # Un orologio solo per TUTTE le esecuzioni della classe: le due passate
        # devono vedere lo stesso identico fixture, o il confronto sarebbe iniquo.
        cls.ADESSO = datetime.now(timezone.utc).replace(microsecond=0)
        if lg.lunedi_gioco(cls.ADESSO) - cls.ADESSO < timedelta(hours=26):
            cls.ADESSO += timedelta(days=3)
        cls.payload = FixtureQuoteFinte.payload_quote(cls.ADESSO)
        cls.riga_seed = _riga_conclusa(cls.ADESSO)

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "vecchio", None) is not None and cls.vecchio.exists():
            cls.vecchio.unlink()

    @staticmethod
    def _normalizza(righe):
        out = [{k: v for k, v in r.items() if k not in VOLATILI}
               for r in (righe or []) if isinstance(r, dict)]
        return sorted(out, key=lambda r: str(r.get("match_id")))

    def _esegui(self, percorso_app, etichetta: str) -> dict:
        """Una passata completa: apertura, giro del modello dichiarato giu', due
        click sul pulsante. Ritorna quello che e' stato scritto."""
        import config
        import market_odds
        import prediction_registry as pr
        import requests
        import streamlit as st
        from streamlit.testing.v1 import AppTest

        adesso = type(self).ADESSO        # lo stesso istante del fixture delle schede
        payload = type(self).payload
        seed = type(self).riga_seed

        tmp = Path(tempfile.mkdtemp(prefix="sm_apptest_parity_"))
        for f in sorted(Path(REALE_DATABASE).iterdir()):
            if f.is_dir() or f.name in ("live_odds.json", "predictions.json"):
                continue
            try:
                (tmp / f.name).symlink_to(f)
            except OSError:
                shutil.copy2(f, tmp / f.name)
        (tmp / "live_odds.json").write_text(json.dumps(payload, ensure_ascii=False),
                                            encoding="utf-8")
        prediction_file = tmp / "predictions.json"
        prediction_file.write_text(json.dumps({"data": [seed]}, ensure_ascii=False),
                                    encoding="utf-8")

        patches = []

        def patch(target, attr, valore):
            patches.append(mock.patch.object(target, attr, valore))
            patches[-1].start()

        registro = _RegistroFinto([seed])
        registro.installa(patch)
        scritture, chiamate = [], []
        originale = pr.backup_prediction_file

        def conta_backup(path, *a, **k):
            scritture.append(str(path))
            return originale(path, *a, **k)

        risposte = {"SA": FixtureQuoteFinte.calendario(adesso)}

        def fake_get(url, **kw):
            chiamate.append(("GET", url))
            code = url.rstrip("/").split("/")[-2] if "/matches" in url else ""
            return _Resp(risposte.get(code, {"matches": []}))

        def niente_rete(metodo):
            def _f(url, **kw):
                chiamate.append((metodo, url))
                raise AssertionError(f"{metodo} di rete non ammesso in test: {url}")
            return _f

        patch(config, "DATABASE_DIR", tmp)
        patch(config, "PREDICTIONS_FILE", str(prediction_file))
        patch(market_odds, "_adesso_utc", lambda: adesso)
        patch(pr, "backup_prediction_file", conta_backup)
        patch(requests, "get", fake_get)
        for metodo in ("put", "post", "patch", "delete"):
            patch(requests, metodo, niente_rete(metodo))
        patch(time, "sleep", lambda s: None)

        st.cache_data.clear()
        try:
            at = AppTest.from_file(str(percorso_app), default_timeout=600)
            at.run(timeout=900)
            self._senza_modello(at)
            at.run(timeout=900)
            for _ in range(2):
                for b in at.button:
                    if etichetta in (b.label or ""):
                        b.click()
                        break
                else:
                    raise AssertionError(f"pulsante {etichetta!r} non trovato "
                                         f"in {percorso_app}")
                at.run(timeout=900)
                e = [str(x.value) for x in at.exception]
                self.assertFalse(e, f"eccezioni su {percorso_app.name}: {e[:2]}")
            return {
                "vivo": self._normalizza(registro.vivo),
                "ombra": self._normalizza(registro.ombra),
                "disco": self._normalizza(
                    json.loads(prediction_file.read_text(encoding="utf-8"))["data"]),
                "chiamate": list(registro.chiamate),
                "scritture_file": len(scritture),
                "rete": [c for c in chiamate if c[0] != "GET"],
            }
        finally:
            for p in reversed(patches):
                try:
                    p.stop()
                except Exception:                               # pragma: no cover
                    pass
            pr.backup_prediction_file = originale
            st.cache_data.clear()
            shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def _senza_modello(at):
        at.session_state["confronto_modello_stato"] = "non_disponibile"
        at.session_state["confronto_modello_righe"] = []
        at.session_state["confronto_modello_1x2"] = []

    @staticmethod
    def _senza_impronte(righe):
        """Toglie quello che racconta QUANDO il giro e' scattato.

        ``league_fingerprint``, ``calculation_id``, ``data_snapshot_sha`` e
        ``salvato_il_originario`` derivano dall'istante dell'esecuzione e dal file
        snapshot letto in quell'istante: le due passate sono a un minuto di distanza
        e li vedresti diversi anche con codice identico. Qui si confrontano le
        RIGHE — chi gioca, cosa si prevede, in che stato e' la scrittura — non
        l'orologio. Che la normalizzazione non copra nulla lo garantiscono i due
        subTest seguenti: gli STESSI nomi di campo riga per riga, e le impronte
        presenti e ben formate da entrambe le parti.
        """
        via = {"league_fingerprint", "calculation_id", "data_snapshot_sha",
               "salvato_il_originario"}
        return [{k: v for k, v in r.items() if k not in via} if isinstance(r, dict) else None
                for r in righe]

    def test_01_stesse_righe_stesse_chiamate(self):
        nuovo = self._esegui(Path(APP_PATH), ETICHETTA_CALCOLA)
        vecchio = self._esegui(self.vecchio, ETICHETTA_VECCHIO)
        with self.subTest("registro di mercato"):
            self.assertEqual(self._senza_impronte(vecchio["vivo"]),
                             self._senza_impronte(nuovo["vivo"]),
                             "il pulsante nuovo scrive le stesse righe, con gli "
                             "stessi valori")
        with self.subTest("registro ombra"):
            self.assertEqual(self._senza_impronte(vecchio["ombra"]),
                             self._senza_impronte(nuovo["ombra"]),
                             "e le stesse note di controllo")
        with self.subTest("campi identici"):
            for nome in ("vivo", "ombra"):
                self.assertEqual([sorted(r) if isinstance(r, dict) else None for r in vecchio[nome]],
                                 [sorted(r) if isinstance(r, dict) else None for r in nuovo[nome]],
                                 "%s: stesse colonne, nessuna aggiunta o rimozione" % nome)
            self.assertGreaterEqual(len(vecchio["vivo"]), 1, "il Fixture deve registrare qualcosa")
        with self.subTest("le impronte ci sono, da tutte e due le parti"):
            import re
            for nome in ("vivo", "ombra"):
                for riga in vecchio[nome] + nuovo[nome]:
                    if isinstance(riga, dict) and "data_snapshot_sha" in riga:
                        self.assertRegex(str(riga["data_snapshot_sha"]), r"^[0-9a-f]{12}$")
            self.assertEqual([_id(r) for r in vecchio["vivo"]], [_id(r) for r in nuovo["vivo"]],
                             "le identita' scritte nel Registro sono le stesse")
        with self.subTest("file del Registro"):
            self.assertEqual([_id(r) for r in vecchio["disco"]],
                             [_id(r) for r in nuovo["disco"]],
                             "le righe sul disco sono le stesse, nello stesso ordine")
        with self.subTest("numero di scritture"):
            self.assertEqual(vecchio["scritture_file"], nuovo["scritture_file"],
                             "lo stesso numero di scritture del file")
            self.assertEqual([c[0] for c in vecchio["chiamate"]],
                             [c[0] for c in nuovo["chiamate"]],
                             "le stesse chiamate al registro, nello stesso ordine")
        self.assertTrue(len(vecchio["vivo"]) > 1,
                        "il confronto non deve essere fra due vuoti")
        self.assertEqual([], vecchio["rete"], "nemmeno il pulsante vecchio scrive in rete")
        self.assertEqual([], nuovo["rete"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
