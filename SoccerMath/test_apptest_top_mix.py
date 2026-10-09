"""AppTest sul VERO ``app.py``: click "Calcola Top Mix", multipla, Registro.

Perche' questo file esiste (punto 4 delle rifiniture dopo la PR #53): la verifica
precedente del flusso tab2 era un test strutturale sul ``session_state`` e
l'esecuzione vera girava su un file separato che RISCRIVEVA l'UI della multipla.
Cosi' non si era mai visto il pulsante vero premuto sul codice vero, ed e'
esattamente li' che la PR #53 aveva il difetto (una scrittura nel Registro per
riga). ``test_apptest_multipla.py`` resta: e' il giro del solo calcolatore, senza
app.

Cosa prova, in un solo giro:

* la tabella del Top Mix mostra solo le partite sopra soglia (``0,55``);
* una riga GIA' nel Registro, la cui partita e' ricaduta sotto soglia, viene
  aggiornata alla lettura del turno (``0,58 -> ~0,50``) con ``sotto_soglia_ora``
  a ``True``, i campi ``*_prima`` intatti e SENZA righe nuove;
* il Registro viene scritto UNA VOLTA SOLA per click (non una per riga);
* selezionare due righe nel multiselect della multipla lascia visibili tabella e
  calcolatore e NON scrive nulla e NON rifà chiamate (la scrittura vive solo nel
  blocco del pulsante);
* il campo "Quota offerta dal tuo bookmaker" parte vuoto e senza margine; pieno,
  il margine e' ``quota * probabilita' combinata - 1``.

Come si evita l'HTTP senza toccare ``app.py``: ``fetch_and_calc_top_mix`` e'
``@st.cache_data``, quindi mockpare LA FUNZIONE non funziona (il decoratore la
ricrea a ogni esecuzione del file). Si sostituisce cio' che la funzione chiama:
``requests.get/put/post``, ``time.sleep`` e i due percorsi in ``config``
(database e ``predictions.json``) puntati su una copia temporanea del database
con un ``live_odds.json`` di fixture costruito a mano.
``carica_indice_quote_live`` NON e' cached: il file viene riletto a ogni run, e
questo e' il perche' il fixture sta su disco e non in un mock.

Nessuna chiamata di rete, nessun file reale toccato, nessun backup scritto nel
database del progetto.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

APP_PATH = os.path.join(HERE, "app.py")
REALE_DATABASE = os.path.join(HERE, "database")


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _libro(p1, pX, p2, k=1.06):
    """Un solo libro (Pinnacle) con il 6% di margine: la de-vig riporta le probabilita'.

    Le quote sono ``k/p`` e ``probabilita_mercato`` divide per la somma delle
    implicite, che per questo fixture e' ``k * (p1+pX+p2) = k``: le probabilita'
    tornano quelle volute, e il margine del libro resta visibile nel ``devig``.
    """
    return {"key": "pinnacle", "title": "Pinnacle",
            "h2h": {"home": round(k / p1, 4), "draw": round(k / pX, 4),
                    "away": round(k / p2, 4)}}


class _Resp:
    """Risposta finta di ``requests.get``: solo ``.status_code`` e ``.json()``."""

    def __init__(self, payload, code=200):
        self._payload, self.status_code = payload, code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class TestAppTestCalcolaTopMix(unittest.TestCase):
    """Un solo run del pulsante, tutte le asserzioni della commessa."""

    @classmethod
    def setUpClass(cls):
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:                                      # pragma: no cover
            raise unittest.SkipTest("streamlit.testing.v1 non disponibile")

        import config
        import prediction_registry as pr
        import requests

        cls.tmp = Path(tempfile.mkdtemp(prefix="sm_apptest_"))
        # Copia "morbida" del database: i CSV reali si leggono attraverso, i due
        # file che l'app scrivesse restano nel tmp. ``live_odds.json`` e
        # ``predictions.json`` NON si linkano: sono i due file di questo test.
        for f in sorted(Path(REALE_DATABASE).iterdir()):
            if f.name in ("live_odds.json", "predictions.json"):
                continue
            (cls.tmp / f.name).symlink_to(f)

        ora = datetime.now(timezone.utc)
        cls.calcio = _iso(ora + timedelta(hours=20))
        cls.istante = _iso(ora)
        # 111 e 113 sopra soglia, 112 SOTTO: e' la partita del caso di commessa.
        cls.probs = {"111": (0.60, 0.25, 0.15), "112": (0.50, 0.28, 0.22),
                     "113": (0.66, 0.20, 0.14)}
        cls.squadre = {"111": ("Genoa", "Fiorentina"), "112": ("Torino", "Como"),
                       "113": ("Roma", "Lecce")}
        eventi = [{"id": eid, "commence_time": cls.calcio,
                   "home_team": cls.squadre[eid][0], "away_team": cls.squadre[eid][1],
                   "last_update": cls.istante,
                   "libri": [dict(_libro(*cls.probs[eid]), last_update=cls.istante)]}
                  for eid in sorted(cls.probs)]
        (cls.tmp / "live_odds.json").write_text(json.dumps({
            "schema": "soccermath_live_odds_v1", "generato_il": cls.istante,
            "fonte": "the-odds-api", "piano": "starter", "regioni": "eu",
            "mercato": "h2h", "formato_quote": "decimal", "modalita": "fixture",
            "crediti": {"quota_mensile": 500, "usati_dall_ultimo_reset": 5, "residui": 495},
            "n_leghe_ok": 1, "n_leghe_con_quote": 1, "n_leghe_richieste": 5,
            "n_eventi": len(eventi), "n_eventi_con_libri": len(eventi),
            "n_eventi_con_pinnacle": len(eventi), "n_libri_totale": len(eventi),
            "leghe_con_eventi_senza_libri": [], "errori": [],
            "leghe_mancanti_rispetto_a_prima": [],
            "leghe": {"Serie A": {"eventi": eventi}},
        }), encoding="utf-8")

        # Registro di partenza: UNA sola riga, la partita 112, registrata ieri a
        # 0,58 (allora era sopra soglia). Nel fixture di quote la stessa partita
        # vale ~0,50: e' il caso dell'enunciato, scritto a mano per non dover
        # importare ``app`` in questo processo (vedi il docstring del file).
        cls.prima_prob = 0.58
        cls.riga_112 = {
            "match_id": 112, "home": "Torino", "away": "Como",
            "campionato": "Serie A", "giornata": 7,
            "data": (ora + timedelta(hours=20)).strftime("%d/%m/%Y %H:%M"),
            "pronostico_sicuro": "1 - Top Mix", "mercato_standard": "1",
            "top3": [], "prob_sicuro": round(cls.prima_prob * 100, 1),
            "risultati_attesi": "", "risultato_reale": None, "esito": "⏳",
            "tipo": "Top Mix", "stagione": "2026",
            "salvato_il": (ora - timedelta(days=1)).strftime("%d/%m/%Y %H:%M"),
            "origin": "top_mix", "selector_version": pr.SELECTOR_VERSION_CURRENT,
            "model_variant": pr.MODEL_VARIANT_CURRENT, "rank": 3,
            "kickoff_utc": cls.calcio, "data_snapshot_sha": "fixture",
            "calculation_id": "fixture112", "poisson": None, "elo": None,
            "elo_disponibile": False, "model_version": pr.MODEL_VERSION_CURRENT,
            "excluded_from_current_stats": False,
            pr.PROB_MERCATO_FIELD: cls.prima_prob,
            pr.QUOTA_MERCATO_FIELD: round(1.06 / cls.prima_prob, 4),
            pr.MERCATO_FONTE_FIELD: "pinnacle", pr.MERCATO_N_LIBRI_FIELD: 1,
            pr.ACCORDO_MODELLO_FIELD: False, pr.PROB_MODELLO_FIELD: 53.0,
            pr.QUOTE_LIVE_ISTANTE_FIELD: "2026-01-01T00:00:00Z",
            pr.PROB_MERCATO_PRIMA_FIELD: cls.prima_prob,
            pr.QUOTA_MERCATO_PRIMA_FIELD: round(1.06 / cls.prima_prob, 4),
            pr.PROB_MODELLO_PRIMA_FIELD: 53.0,
            pr.ACCORDO_MODELLO_PRIMA_FIELD: False,
            pr.QUOTE_LIVE_ISTANTE_PRIMA_FIELD: "2026-01-01T00:00:00Z",
        }
        cls.salvato_il_prima = cls.riga_112["salvato_il"]
        cls.prediction_file = cls.tmp / "predictions.json"
        cls.prediction_file.write_text(
            json.dumps({"data": [cls.riga_112]}, ensure_ascii=False), encoding="utf-8")

        # --- le parti dell'app che si sostituiscono (e si restaurano) ---
        cls._patches = []

        def patch(target, attr, valore):
            cls._patches.append(mock.patch.object(target, attr, valore))
            cls._patches[-1].start()

        patch(config, "DATABASE_DIR", cls.tmp)
        patch(config, "PREDICTIONS_FILE", str(cls.prediction_file))

        cls.chiamate = []

        def fake_get(url, **kw):
            cls.chiamate.append(("GET", url))
            code = url.rstrip("/").split("/")[-2]
            if code != "SA":
                return _Resp({"matches": []})
            return _Resp({"matches": [cls._match(eid) for eid in sorted(cls.probs)]})

        def niente_rete(metodo):
            def _f(url, **kw):
                cls.chiamate.append((metodo, url))
                raise AssertionError(f"{metodo} di rete non ammesso in test: {url}")
            return _f

        patch(requests, "get", fake_get)
        for metodo in ("put", "post", "patch", "delete"):
            patch(requests, metodo, niente_rete(metodo))
        patch(time, "sleep", lambda s: None)

        # Contatore delle scritture locali: ``save_predictions`` fa SEMPRE un
        # backup prima di scrivere, quindi contare i backup conta le scritture.
        cls.scritture = []
        cls._backup_originale = pr.backup_prediction_file

        def backup(path, *a, **k):
            cls.scritture.append(str(path))
            return cls._backup_originale(path, *a, **k)

        patch(pr, "backup_prediction_file", backup)

        cls.at = AppTest.from_file(APP_PATH, default_timeout=600)
        cls.at.run()
        cls.eccezioni("apertura della pagina")

    @classmethod
    def tearDownClass(cls):
        for patcher in reversed(getattr(cls, "_patches", [])):
            try:
                patcher.stop()
            except Exception:                                    # pragma: no cover
                pass
        import prediction_registry as pr
        pr.backup_prediction_file = cls._backup_originale
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ------------------------------------------------------------------ aiuti
    @classmethod
    def _match(cls, eid):
        h, a = cls.squadre[eid]
        return {"id": int(eid), "matchday": 7, "utcDate": cls.calcio, "status": "TIMED",
                "homeTeam": {"name": h, "shortName": h},
                "awayTeam": {"name": a, "shortName": a}}

    @classmethod
    def eccezioni(cls, fase):
        e = [str(x.value) for x in cls.at.exception]
        if e:
            raise AssertionError(f"eccezioni in {fase}: {e}")

    def righe_registro(self):
        return json.loads(self.prediction_file.read_text(encoding="utf-8"))["data"]

    # ------------------------------------------------------------------- prova
    def test_click_top_mix(self):
        import market_odds as mo

        self.assertEqual([], self.scritture, "aprire la pagina non scrive il Registro")
        self.assertEqual([], self.chiamate, "aprire la pagina non chiama la rete")

        # --- 1) premere "Calcola Top Mix" ---------------------------------
        bottoni = [b for b in self.at.button if "Calcola Top Mix" in b.label]
        self.assertEqual(1, len(bottoni), "un solo pulsante del Top Mix in pagina")
        bottoni[0].click()
        self.at.run()
        self.eccezioni("click su Calcola Top Mix")

        top = self.at.session_state["topmix_mercato"]
        self.assertEqual({111, 113}, {int(r["match_id"]) for r in top},
                         "sotto soglia (112) non entra in tabella: il gate del selettore")
        for r in top:
            self.assertGreaterEqual(r["prob"], mo.SOGLIA_TOPMIX_MERCATO, r["match_id"])

        # --- 2) UNA sola scrittura, non una per riga -----------------------
        self.assertEqual(1, len(self.scritture),
                         f"scritture del Registro: {self.scritture}, attesa una sola")
        self.assertEqual([], [c for c in self.chiamate if c[0] != "GET"],
                         "nessuna PUT/POST: o il remoto e' spento, o il test non lo mocka")

        # --- 3) la riga sotto soglia viene riallineata ----------------------
        registro = self.righe_registro()
        self.assertEqual(3, len(registro),
                         "2 righe ammesse + la 112 gia' registrata: sotto soglia non "
                         "nasce nessuna riga nuova")
        by_id = {int(r["match_id"]): r for r in registro}
        self.assertEqual({111, 112, 113}, set(by_id))
        riga = by_id[112]

        # Il numero atteso viene dalla STESSA funzione di produzione sulle STESSE
        # libro del fixture: non e' uno 0,52 scritto a mano che si conferma da solo.
        attesa = mo.probabilita_mercato([_libro(*self.probs["112"])])["probs"]["1"]
        self.assertLess(attesa, mo.SOGLIA_TOPMIX_MERCATO, "il fixture deve stare sotto soglia")
        self.assertEqual(round(attesa * 100, 1), riga["prob_sicuro"],
                         "l'ULTIMA registrazione scende a quanto dice il mercato adesso")
        self.assertAlmostEqual(round(attesa, 6), riga["prob_mercato"], places=6)
        self.assertTrue(riga["sotto_soglia_ora"], "il flag dice che oggi NON sarebbe in tabella")
        # La PRIMA registrazione e' un fatto storico: intatta.
        self.assertAlmostEqual(self.prima_prob, riga["prob_mercato_prima"], places=6)
        self.assertEqual(round(1.06 / self.prima_prob, 4), riga["quota_mercato_prima"])
        self.assertEqual(53.0, riga["prob_modello_prima"])
        self.assertEqual("2026-01-01T00:00:00Z", riga["quote_live_istante_prima"])
        self.assertNotEqual(58.0, riga["prob_sicuro"], "il campo attuale scende, il _prima no")
        self.assertEqual(self.salvato_il_prima, riga["salvato_il_originario"],
                         "il timestamp della prima scrittura resta leggibile")
        self.assertNotEqual(self.salvato_il_prima, riga["salvato_il"],
                            "e l'ultimo aggiornamento ha il suo timestamp")
        self.assertEqual("1", riga["mercato_standard"], "la scelta registrata non cambia")
        self.assertEqual(3, riga["rank"], "rank e calculation_id non vengono riscritti")
        self.assertEqual("fixture112", riga["calculation_id"])
        # Le righe ammesse portano il flag a False (sopra soglia per definizione)
        self.assertFalse(by_id[111]["sotto_soglia_ora"])
        self.assertFalse(by_id[113]["sotto_soglia_ora"])

        # --- 4) multipla: tabella e calcolatore restano visibili ------------
        mss = [m for m in self.at.multiselect if m.key == "multipla_selezione"]
        self.assertEqual(1, len(mss), "il multiselect della multipla c'e'")
        self.assertEqual(2, len(mss[0].options), "due righe da scegliere, le due ammesse")
        self.scritture.clear()
        self.chiamate.clear()
        mss[0].set_value(list(mss[0].options))
        self.at.run()
        self.eccezioni("selezione di due righe")

        self.assertEqual([], self.scritture,
                         "un rerun di UI non scrive il Registro: la scrittura vive nel click")
        self.assertEqual([], self.chiamate, "un rerun non rifà le chiamate HTTP")
        df = [e for e in self.at if type(e).__name__ in ("Dataframe", "ArrowDataFrame")]
        self.assertGreaterEqual(len(df), 2, "tabella Top Mix + tabella della multipla visibili")
        ms_dopo = [m for m in self.at.multiselect if m.key == "multipla_selezione"]
        self.assertEqual(1, len(ms_dopo), "il calcolatore non e' sparito col rerun")
        self.assertEqual(2, len(ms_dopo[0].value), "la selezione resta dopo il rerun")
        metriche = {m.label: m.value for m in self.at.metric}
        self.assertIn("Probabilita' combinata", metriche, list(metriche))
        self.assertIn("Quota equa (1/prob)", metriche, list(metriche))

        # --- 5) campo opzionale vuoto = nessun margine ---------------------
        nis = [n for n in self.at.number_input if n.key == "multipla_quota_bookmaker"]
        self.assertEqual(1, len(nis), "il campo 'Quota offerta dal tuo bookmaker' c'e'")
        self.assertIsNone(nis[0].value, "il campo parte VUOTO: nessuna quota di default")
        self.assertNotIn("Margine sulla tua quota", metriche,
                         "senza quota inserita il margine non si mostra")

        # --- 6) quota inserita -> margine = quota * prob - 1 ----------------
        prob_comb = 1.0
        for r in top:
            prob_comb *= r["prob"]
        self.assertTrue(0.0 < prob_comb < 1.0, prob_comb)
        quota = 2.85
        nis[0].set_value(quota)
        self.at.run()
        self.eccezioni("quota del bookmaker inserita")
        dopo = {m.label: m.value for m in self.at.metric}
        self.assertIn("Margine sulla tua quota", dopo, list(dopo))
        mostrato = float(dopo["Margine sulla tua quota"].replace("%", "").replace("+", ""))
        self.assertAlmostEqual(quota * prob_comb - 1.0, mostrato / 100.0, places=3)
        self.assertEqual([], self.scritture, "nemmeno la multipla scrive il Registro")

        # --- 7) secondo click: SEMPRE una scrittura per click, non per riga ---
        # Il secondo click non e' "niente da fare": le righe ammesse vengono
        # riscritte (timestamp nuovo) e il Registro si allinea di nuovo. Cio' che
        # deve valere e' la promessa della commessa: UNA scrittura per click, una
        # riga sola per partita, e la prima registrazione ancora intatta.
        self.scritture.clear()
        self.chiamate.clear()
        [b for b in self.at.button if "Calcola Top Mix" in b.label][0].click()
        self.at.run()
        self.eccezioni("secondo click")
        self.assertLessEqual(len(self.scritture), 1,
                             f"secondo click: scritture {self.scritture}, attesa <= 1")
        registro2 = self.righe_registro()
        self.assertEqual(3, len(registro2), "il secondo click non duplica nessuna riga")
        again = {int(r["match_id"]): r for r in registro2}[112]
        self.assertAlmostEqual(self.prima_prob, again["prob_mercato_prima"], places=6,
                               msg="e i campi _prima restano la prima scrittura, sempre")
        self.assertEqual(self.salvato_il_prima, again["salvato_il_originario"])
        self.assertTrue(again["sotto_soglia_ora"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
