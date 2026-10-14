"""AppTest della nuova navigazione a schede (tre schede + strumenti avanzati).

Copre i punti 1, 2, 3, 4 e 5 della commessa di navigazione, sul VERO ``app.py``
e sullo snapshot reale pinnato (``snap_test.snapshot_reale``), con orologio
congelato a venerdì 2026-10-16 18:00 ora italiana, rete finta e storage del
Registro in memoria (nessun file reale toccato, nessuna chiamata di rete).

Cosa verifica, in parole povere:

* le schede sono TRE all'apertura e la prima e' «🎯 Giocate»; con
  «🔧 Strumenti avanzati» acceso diventano QUATTRO e la quarta contiene Elo e
  Backtest invariati;
* la scheda Giocate si GUARDA senza premere niente: riga dell'aggiornamento
  quote, «Per raddoppiare», «Le più probabili», «Le scelte più sicure secondo
  le quote», «Prova la tua giocata» e «Dettagli» sono gia' in pagina al primo
  disegno;
* aprire la scheda (e ridisegnarla) NON scrive nulla: registro di mercato,
  registro ombra e proposte della settimana restano intatti finche' nessuno
  preme «📝 Registra le giocate della giornata»;
* quel pulsante scrive, e un secondo clic sullo stesso turno di quote non
  aggiunge righe doppie;
* se il confronto col modello non riesce, la caption lo dice una volta
  («Modello %: non disponibile»), le celle restano vuote e «Per raddoppiare»
  resta dov'e';
* la scheda «📒 Com'è andata» apre con il riepilogo in parole, i cui numeri
  tornano con quelli contati a mano sulle stesse righe, e il controllo dei
  risultati parte DA SOLO una volta per sessione (e non parte se nessuna
  partita e' finita da almeno tre ore).

Due sole istanze di AppTest (una in sola lettura, una per le scritture): ogni
esecuzione dell'app costa decine di secondi.
"""
from __future__ import annotations

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
APP_PATH = os.path.join(HERE, "app.py")
REPO_ROOT = os.path.dirname(HERE)
for _p in (HERE, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Il raccoglitore di testo (fuori/dentro i riquadri) e l'elenco delle parole
# vietate sono gli stessi della PR #64: una sola definizione, due schede.
from test_apptest_topmix_presentazione import (  # noqa: E402
    PAROLE_VIETATE,
    SCHEDA_MULTIPLE,
    SCHEDA_PAREGGI,
    SCHEDA_PRONOSTICI,
    SCHEDA_REGISTRO,
    SCHEDA_STRUMENTI,
    _elementi_della_tab,
    _testo_blocco,
    _testi_della_tab,
)

import re  # noqa: E402


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


class _BaseAppTest(unittest.TestCase):
    """Fixture comune: database in tmp, snapshot reale, orologio fermo, rete finta."""

    ADESSO = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)  # ven 18:00 Italia

    @classmethod
    def setUpClass(cls):
        try:
            from streamlit.testing.v1 import AppTest  # noqa: F401
        except ImportError:                                             # pragma: no cover
            raise unittest.SkipTest("streamlit.testing.v1 non disponibile")

        import snap_test
        cls.snap = snap_test.snapshot_reale()
        if cls.snap is None:
            raise unittest.SkipTest("Snapshot pinnato non raggiungibile (clone shallow?)")

        import config
        import market_odds
        import prediction_registry as pr
        import registry_store as rs
        import requests

        cls.tmp = Path(tempfile.mkdtemp(prefix="sm_apptest_nav_"))
        for f in sorted(Path(HERE, "database").iterdir()):
            if f.is_dir() or f.name in ("live_odds.json", "predictions.json"):
                continue
            try:
                (cls.tmp / f.name).symlink_to(f)
            except OSError:                                             # pragma: no cover
                shutil.copy2(f, cls.tmp / f.name)
        (cls.tmp / "live_odds.json").write_text(json.dumps(cls.snap), encoding="utf-8")

        # --- Registro visibile: righe di mercato con esiti noti -------------
        # Due concluse (1 ✅ / 1 ❌) e una ancora da giocare. I numeri del
        # riepilogo in parole vengono ricontati A MANO nel test, non riletti
        # dalla funzione che li produce.
        cls.adesso_reale = datetime.now(timezone.utc)
        cls.prima_prob = {7101: 0.625, 7102: 0.58, 7103: 0.60}
        cls.esiti_seed = {7101: "✅", 7102: "❌", 7103: "⏳"}
        righe = []
        for i, (mid, esito) in enumerate(sorted(cls.esiti_seed.items())):
            kickoff = (cls.adesso_reale - timedelta(hours=30) if esito != "⏳"
                       else cls.adesso_reale - timedelta(hours=9))
            righe.append({
                "match_id": mid, "home": f"Casa{i}", "away": f"Ospite{i}",
                "campionato": "Serie A", "giornata": 8,
                "data": kickoff.astimezone(tz=None).strftime("%d/%m/%Y %H:%M"),
                "pronostico_sicuro": "1 - Top Mix", "mercato_standard": "1",
                "top3": [], "prob_sicuro": round(cls.prima_prob[mid] * 100, 1),
                "risultati_attesi": "",
                "risultato_reale": ("2-0" if esito == "✅" else "0-1" if esito == "❌" else ""),
                "esito": esito, "tipo": "Top Mix", "stagione": "2026/27",
                "salvato_il": "16/10/2026 09:30", "origin": pr.ORIGIN_TOP_MIX,
                "selector_version": pr.SELECTOR_VERSION_MERCATO_V3,
                "model_variant": pr.MODEL_VARIANT_CURRENT,
                "model_version": pr.MODEL_VERSION_CURRENT,
                "rank": i + 1, "kickoff_utc": _iso(kickoff),
                "calculation_id": f"fixture{mid}",
                pr.PROB_MERCATO_FIELD: cls.prima_prob[mid],
                pr.QUOTA_MERCATO_FIELD: round(1.06 / cls.prima_prob[mid], 4),
                pr.MERCATO_FONTE_FIELD: "pinnacle", pr.MERCATO_N_LIBRI_FIELD: 1,
                pr.ACCORDO_MODELLO_FIELD: True, pr.PROB_MODELLO_FIELD: 63.0,
                pr.QUOTE_LIVE_ISTANTE_FIELD: "2026-10-16T10:00:00Z",
                pr.PROB_MERCATO_PRIMA_FIELD: cls.prima_prob[mid],
                pr.QUOTA_MERCATO_PRIMA_FIELD: round(1.06 / cls.prima_prob[mid], 4),
                pr.PROB_MODELLO_PRIMA_FIELD: 63.0,
                pr.ACCORDO_MODELLO_PRIMA_FIELD: True,
                pr.QUOTE_LIVE_ISTANTE_PRIMA_FIELD: "2026-10-16T10:00:00Z",
            })
        (cls.tmp / "predictions.json").write_text(
            json.dumps({"data": righe}), encoding="utf-8")
        cls.seed_mercato = righe

        # --- Proposte della settimana nel registro ombra --------------------
        cls.ombra_seed = [
            {"match_id": 8001, pr.OMBRA_FAMIGLIA_FIELD: "multipla_proposta_v1",
             "esito": "✅", "k": 2},
            {"match_id": 8002, pr.OMBRA_FAMIGLIA_FIELD: "multipla_proposta_v1",
             "esito": "❌", "k": 3},
            {"match_id": 8003, pr.OMBRA_FAMIGLIA_FIELD: "ou25", "esito": "✅"},
        ]

        cls._patches = []

        def patch(target, attr, valore):
            cls._patches.append(mock.patch.object(target, attr, valore))
            cls._patches[-1].start()

        patch(config, "DATABASE_DIR", cls.tmp)
        patch(config, "PREDICTIONS_FILE", str(cls.tmp / "predictions.json"))
        patch(market_odds, "_adesso_utc", lambda: cls.ADESSO)

        # --- Storage del Registro in memoria, con registro delle chiamate ---
        cls.chiamate_registro = []
        cls.storage_vivo = [dict(r) for r in righe]
        cls.storage_ombra = [dict(r) for r in cls.ombra_seed]

        def _load_rows(*a, **k):
            cls.chiamate_registro.append(("load_rows", len(cls.storage_vivo)))
            return [dict(r) for r in cls.storage_vivo], "fixture"

        def _save_rows(rows, *a, **k):
            cls.chiamate_registro.append(
                ("save_rows", tuple(sorted(int(r.get("match_id")) for r in rows))))
            cls.storage_vivo[:] = [dict(r) for r in rows]
            return {"remoto": "ok", "backend": "fixture", "righe_scritte": len(rows)}

        def _load_ombra(*a, **k):
            cls.chiamate_registro.append(("load_ombra_rows", len(cls.storage_ombra)))
            return [dict(r) for r in cls.storage_ombra], "fixture"

        def _save_ombra(rows, *a, **k):
            cls.chiamate_registro.append(
                ("save_ombra_rows", tuple(sorted(int(r.get("match_id")) for r in rows))))
            cls.storage_ombra[:] = [dict(r) for r in rows]
            return {"remoto": "ok", "backend": "fixture", "righe_scritte": len(rows)}

        patch(rs, "load_rows", _load_rows)
        patch(rs, "save_rows", _save_rows)
        patch(rs, "load_ombra_rows", _load_ombra)
        patch(rs, "save_ombra_rows", _save_ombra)

        # --- Rete finta: il calendario dice le partite dello snapshot -------
        cls.eventi_per_lega = {lega: (blocco.get("eventi") or [])
                               for lega, blocco in (cls.snap.get("leghe") or {}).items()
                               if blocco.get("eventi")}
        if not cls.eventi_per_lega:
            raise unittest.SkipTest("Snapshot senza eventi")

        import app as app_mod
        cls._league_code = {nome: cfg.get("code")
                            for nome, cfg in getattr(app_mod, "LEAGUES_CONFIG", {}).items()}
        cls._match_by_league = {}
        for i, (lega, eventi) in enumerate(sorted(cls.eventi_per_lega.items())):
            cls._match_by_league[lega] = [{
                "id": 9900000 + i * 1000 + j,
                "utcDate": ev.get("commence_time"),
                "homeTeam": {"name": ev.get("home_team")},
                "awayTeam": {"name": ev.get("away_team")},
                "matchday": 8,
                "score": {"fullTime": {"home": None, "away": None}},
                "status": "SCHEDULED",
            } for j, ev in enumerate(eventi)]

        cls.get_http = []

        def fake_get(url, **kw):
            cls.get_http.append(url)
            if "api.football-data.org" not in url:
                raise AssertionError(f"GET non ammessa in test: {url}")
            code = url.rstrip("/").split("/")[-2] if "/matches" in url else ""
            for lega, code_league in cls._league_code.items():
                if code == code_league and lega in cls._match_by_league:
                    return _Resp({"matches": cls._match_by_league[lega]})
            return _Resp({"matches": []})

        def niente_scrittura(metodo):
            def _f(url, **kw):
                raise AssertionError(f"{metodo} di rete non ammesso in test: {url}")
            return _f

        patch(requests, "get", fake_get)
        for metodo in ("put", "post", "patch", "delete"):
            patch(requests, metodo, niente_scrittura(metodo))
        patch(time, "sleep", lambda s: None)

        import streamlit as st
        st.cache_data.clear()
        cls._st = st

    @classmethod
    def tearDownClass(cls):
        for p in getattr(cls, "_patches", []):
            try:
                p.stop()
            except Exception:                                           # pragma: no cover
                pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- utilita' ----------------------------------------------------------
    @classmethod
    def eccezioni(cls, at, fase):
        e = [str(x.value) for x in at.exception]
        if e:
            raise AssertionError(f"eccezioni in {fase}: {e}")

    @staticmethod
    def _etichette_schede(at):
        schede = getattr(at, "tabs", None) or getattr(at, "tab")
        return [str(getattr(t, "label", "")) for t in schede]

    @staticmethod
    def _toggle(at, chiave):
        for t in at.toggle:
            if t.key == chiave:
                return t
        raise AssertionError(f"interruttore {chiave} non trovato")


class TestSchedeLettura(_BaseAppTest):
    """Un solo run in sola lettura: schede, contenuti immediati, Com'è andata."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from streamlit.testing.v1 import AppTest
        cls.at = AppTest.from_file(APP_PATH, default_timeout=300)
        cls.at.run(timeout=900)
        cls.eccezioni(cls.at, "apertura della pagina")

    def test_01_le_schede_sono_quattro_e_la_prima_e_pronostici(self):
        """Quattro schede fisse, in quest'ordine. La quinta (gli strumenti
        avanzati) non si conta: l'interruttore e' spento all'apertura."""
        self.assertEqual([SCHEDA_PRONOSTICI, SCHEDA_PAREGGI, SCHEDA_MULTIPLE,
                          SCHEDA_REGISTRO],
                         self._etichette_schede(self.at))

    def test_02_strumenti_avanzati_spento_all_avvio(self):
        self.assertFalse(self._toggle(self.at, "strumenti_avanzati").value,
                         "l'interruttore degli strumenti avanzati parte spento")

    def test_03_multiple_si_legge_senza_premere_niente(self):
        """Le due liste per la multipla stanno in vista da subito; la tabella
        delle scelte del mercato no: si e' spostata in «⚽ Pronostici» e vuole
        un click."""
        fuori, dentro = _testi_della_tab(self.at, SCHEDA_MULTIPLE)
        testo = " \n".join(fuori)
        for atteso in ("Per raddoppiare", "Le più probabili"):
            with self.subTest(atteso=atteso):
                self.assertIn(atteso, testo)
        self.assertNotIn("Le scelte più sicure secondo le quote", testo)
        etichette = [str(e.label or "") for e in self.at.expander]
        self.assertTrue(any("Prova la tua giocata" in e for e in etichette), etichette)
        self.assertTrue(any(e.strip().endswith("Dettagli") for e in etichette), etichette)
        # La riga dell'aggiornamento delle quote sta in testa alla scheda.
        self.assertRegex(testo, r"[Qq]uote")
        # Il tecnico (parole vietate della PR #64) sta nei riquadri chiusi.
        for parola in PAROLE_VIETATE:
            with self.subTest(parola=parola):
                self.assertIsNone(re.search(parola, testo, re.IGNORECASE),
                                  f"parola vietata fuori dai Dettagli: {parola!r}")
        self.assertTrue(dentro, "i Dettagli devono contenere qualcosa")

    def test_03b_pronostici_prima_del_clic_e_un_pulsante_solo(self):
        """Punto 2: la scheda si apre sul pulsante, sulla riga dell'ultima
        registrazione e sull'invito. Nessun numero, nessuna tabella, niente che
        aspetti il giro del modello."""
        import app as app_mod
        fuori, dentro = _testi_della_tab(self.at, SCHEDA_PRONOSTICI)
        testo = " \n".join(fuori)
        self.assertIn("Ultima registrazione:", testo)
        self.assertIn("Premi il pulsante per calcolare i pronostici della giornata.",
                      testo)
        self.assertEqual(1, len([b for b in _elementi_della_tab(
            self.at, SCHEDA_PRONOSTICI, "button")
            if "Calcola i pronostici della giornata" in (b.label or "")]),
            "un solo pulsante di calcolo nella scheda")
        self.assertEqual([], _elementi_della_tab(self.at, SCHEDA_PRONOSTICI, "dataframe"),
                         "prima del click non c'e' nessuna tabella")
        self.assertEqual([], dentro, "e nessun riquadro chiuso")
        for parola in ("Quote %", "Modello %", "Le scelte più sicure"):
            with self.subTest(parola=parola):
                self.assertNotIn(parola, testo)
        # L'interruttore del periodo e' UNO SOLO e vive nella testa della scheda
        # 🎯 Multiple: una chiave non puo' alimentare due widget nella stessa
        # pagina, e le altre due schede leggono lo stesso stato
        # (``periodo_selezionato``) dicendo dove si accende.
        comandi = [t for t in self.at.toggle
                   if (t.key or "") == app_mod.CHIAVE_PROSSIMI_GIORNI]
        self.assertEqual(1, len(comandi),
                         "un solo interruttore del periodo in tutta la pagina")
        self.assertIn(app_mod.ETICHETTA_PROSSIMI_GIORNI,
                      " \n".join(_testi_della_tab(self.at, SCHEDA_MULTIPLE)[0]),
                      "e sta nella scheda Multiple")
        self.assertNotIn(app_mod.ETICHETTA_PROSSIMI_GIORNI, testo,
                         "non duplicato in Pronostici")

    def test_03c_pareggi_non_chiede_nessun_click(self):
        """La scheda Pareggi legge le quote e basta: nessun pulsante, nessun
        calcolo da attivare."""
        fuori, dentro = _testi_della_tab(self.at, SCHEDA_PAREGGI)
        testo = " \n".join(fuori)
        self.assertTrue(testo, "la scheda Pareggi non deve essere bianca")
        self.assertNotIn("Calcola i pronostici", testo)
        self.assertEqual([], [e for e in _elementi_della_tab(
            self.at, SCHEDA_PAREGGI, "button") if "Calcola" in (e.label or "")])

    def test_04_colonna_modello_percento_presente(self):
        """La vista mostra «Modello %» (probabilità del modello per lo stesso
        esito); il segnale «d'accordo» esce da TUTTA la parte in vista —
        colonna e conteggi nella caption — e resta solo nei Dettagli (campo
        nei dati, tabella tecnica)."""
        fuori, dentro = _testi_della_tab(self.at, SCHEDA_MULTIPLE)
        testo = " \n".join(fuori)
        self.assertIn("Modello %", testo)
        self.assertIn("Quote %", testo)
        self.assertNotIn("d'accordo", testo.lower(),
                         "«d'accordo» (colonna o conteggio) non sta piu' in vista")
        # La caption del conteggio segue la tabella in «⚽ Pronostici», dopo il
        # click: la legge test_apptest_scheda_pronostici.
        self.assertNotIn("partite in tabella", testo)

    def test_05_andata_riepilogo_torna_con_i_conti_fatti_a_mano(self):
        """I numeri della frase in testa sono quelli delle righe del fixture."""
        concluse = [m for m, e in self.esiti_seed.items() if e in ("✅", "❌")]
        n = len(concluse)
        m = sum(1 for x in concluse if self.esiti_seed[x] == "✅")
        x_cento = int(round(100.0 * m / n))
        y_cento = int(round(100.0 * sum(self.prima_prob[x] for x in concluse) / n))
        attesa = (f"Finora {n} giocate concluse, {m} riuscite ({x_cento}%). "
                  f"Quote: {y_cento}%. Modello: 63%.")
        fuori, _ = _testi_della_tab(self.at, SCHEDA_REGISTRO)
        self.assertIn(attesa, " \n".join(fuori))

    def test_06_andata_proposte_settimanali(self):
        """K e J lette dal registro ombra: 2 proposte, 1 riuscita."""
        fuori, _ = _testi_della_tab(self.at, SCHEDA_REGISTRO)
        self.assertIn("Le proposte settimanali registrate: 2, riuscite 1",
                      " \n".join(fuori))

    def test_07_andata_fuori_dai_dettagli_nessuna_parola_vietata(self):
        fuori, _ = _testi_della_tab(self.at, SCHEDA_REGISTRO)
        testo = " \n".join(fuori).lower()
        for parola in PAROLE_VIETATE:
            with self.subTest(parola=parola):
                self.assertIsNone(re.search(parola, testo, re.IGNORECASE),
                                  f"parola vietata fuori dai Dettagli di Com'è andata: {parola!r}")

    def test_08_andata_tecniche_nel_riquadro_chiuso(self):
        _, dentro = _testi_della_tab(self.at, SCHEDA_REGISTRO)
        testo = " \n".join(dentro).lower()
        for atteso in ("registro ombra", "brier"):
            with self.subTest(atteso=atteso):
                self.assertIn(atteso, testo)

    def test_09_controllo_risultati_parte_da_solo_una_volta(self):
        """C'e' una riga in attesa finita da 9 ore e la chiave c'e': parte.

        Senza chiave la nota resta nei Dettagli e in vista non compare nessun
        errore: qui la chiave viene messa e il controllo deve partire UNA volta
        per sessione (il secondo disegno non lo rifà).
        """
        import config
        with mock.patch.object(config, "FOOTBALL_DATA_API_KEY", "chiave-finta"):
            self.at.run(timeout=900)
            self.eccezioni(self.at, "controllo automatico dei risultati")
            self.assertTrue(self.at.session_state.get("risultati_controllati_in_sessione"),
                            "il controllo automatico deve partire all'apertura")
            get_prima = len(self.get_http)
            self.at.run(timeout=900)
            self.eccezioni(self.at, "secondo disegno")
            self.assertEqual(get_prima, len(self.get_http),
                             "una volta per sessione: il secondo disegno non richiama la fonte")

    def test_10_con_strumenti_avanzati_le_schede_diventano_quattro(self):
        self._toggle(self.at, "strumenti_avanzati").set_value(True)
        self.at.run(timeout=900)
        self.eccezioni(self.at, "strumenti avanzati accesi")
        self.assertEqual([SCHEDA_PRONOSTICI, SCHEDA_PAREGGI, SCHEDA_MULTIPLE,
                          SCHEDA_REGISTRO, SCHEDA_STRUMENTI],
                         self._etichette_schede(self.at))
        fuori, _ = _testi_della_tab(self.at, SCHEDA_STRUMENTI)
        testo = " \n".join(fuori)
        self.assertIn("Elo", testo)
        self.assertIn("Backtest", testo)
        # La vecchia scheda «🏟️ Partite» non e' piu' una scheda: e' il pezzo in
        # fondo a questa. Qui il calendario non e' stato sincronizzato, quindi
        # della giornata si legge l'invito a premere SINCRONIZZA (il contenuto,
        # con i pulsanti «Scheda», e' verificato in test_apptest_scheda_partita).
        self.assertIn("SINCRONIZZA", testo)
        self.assertFalse([b for b in self.at.button
                          if (b.key or "").startswith("partite_scheda_")],
                         "senza giornata non ci sono righe da elencare")
        # E le altre schede non si spostano: il loro contenuto e' lo stesso.
        self.assertIn("Per raddoppiare",
                      " \n".join(_testi_della_tab(self.at, SCHEDA_MULTIPLE)[0]))


class TestScrittureSoloSuClick(_BaseAppTest):
    """Aprire non scrive; scrive solo il pulsante, e non duplica."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from streamlit.testing.v1 import AppTest
        cls.at = AppTest.from_file(APP_PATH, default_timeout=300)
        cls.at.run(timeout=900)
        cls.eccezioni(cls.at, "apertura della pagina")

    @staticmethod
    def _scritture(log):
        return [c for c in log if c[0] in ("save_rows", "save_ombra_rows")]

    def test_01_aprire_e_ridisegnare_non_scrive_nulla(self):
        self.assertEqual([], self._scritture(self.chiamate_registro),
                         f"scritture senza clic: {self._scritture(self.chiamate_registro)}")
        self.at.run(timeout=900)
        self.eccezioni(self.at, "ridisegno della pagina")
        self.assertEqual([], self._scritture(self.chiamate_registro),
                         "nemmeno il ridisegno scrive")

    def test_02_ultima_registrazione_letta_dal_registro(self):
        # La riga sta in testa alla scheda che ha il pulsante: prima era «Giocate».
        fuori, _ = _testi_della_tab(self.at, SCHEDA_PRONOSTICI)
        self.assertIn("Ultima registrazione: venerdì 16/10/2026, ore 09:30",
                      " \n".join(fuori))

    def test_03_un_clic_scrive_e_lo_dice(self):
        prima = len(self.storage_vivo)
        self.chiamate_registro.clear()
        bottoni = [b for b in self.at.button
                   if "Calcola i pronostici della giornata" in (b.label or "")]
        self.assertEqual(1, len(bottoni), "un solo pulsante di registrazione")
        bottoni[0].click()
        self.at.run(timeout=900)
        self.eccezioni(self.at, "clic su Registra le giocate della giornata")

        scritte = self._scritture(self.chiamate_registro)
        self.assertTrue([c for c in scritte if c[0] == "save_rows"],
                        f"il registro di mercato deve essere scritto: {scritte}")
        self.assertTrue([c for c in scritte if c[0] == "save_ombra_rows"],
                        f"anche il registro ombra: {scritte}")
        # UNA scrittura del registro visibile per clic, non una per riga.
        self.assertEqual(1, len([c for c in scritte if c[0] == "save_rows"]),
                         f"una sola scrittura del registro visibile: {scritte}")
        # La prima registrazione non viene mai sovrascritta.
        by_id = {int(r["match_id"]): r for r in self.storage_vivo}
        for mid, prob in self.prima_prob.items():
            self.assertAlmostEqual(prob, by_id[mid]["prob_mercato_prima"], places=6,
                                   msg=f"la prima registrazione di {mid} deve restare intatta")
        self.assertGreater(len(self.storage_vivo), prima,
                           "il clic aggiunge le giocate della giornata")
        fuori, _ = _testi_della_tab(self.at, SCHEDA_PRONOSTICI)
        testo = " \n".join(fuori)
        self.assertRegex(testo, r"Registrate \d+ giocate nuove|Niente di nuovo da registrare")
        self.assertIn("Le scelte più sicure secondo le quote", testo,
                      "dopo il click la tabella compare nella stessa scheda")

    def test_04_secondo_clic_sulle_stesse_quote_non_duplica(self):
        ids_prima = sorted(int(r["match_id"]) for r in self.storage_vivo)
        self.chiamate_registro.clear()
        [b for b in self.at.button
         if "Calcola i pronostici della giornata" in (b.label or "")][0].click()
        self.at.run(timeout=900)
        self.eccezioni(self.at, "secondo clic")
        ids_dopo = sorted(int(r["match_id"]) for r in self.storage_vivo)
        self.assertEqual(ids_prima, ids_dopo,
                         "lo stesso turno di quote non aggiunge righe doppie")
        self.assertLessEqual(len([c for c in self._scritture(self.chiamate_registro)
                                  if c[0] == "save_rows"]), 1,
                             "una scrittura per clic, anche il secondo")

    def test_05_se_il_modello_non_risponde_il_resto_resta_in_piedi(self):
        """Giro del modello NON disponibile: le celle di «Modello %» restano
        vuote (numeri, non parole) e la caption lo dice UNA volta («Modello %:
        non disponibile»); «Per raddoppiare» resta dove e'. Lo stato lo
        scriviamo direttamente in session (AppTest esegue lo script in un
        namespace separato: la funzione del giro non e' intercettabile dal
        ``import app`` dei test; la transizione in_calcolo -> fallito e'
        coperta dalla classe del giro e dalla caption, testata a parte)."""
        import requests
        self.chiamate_registro.clear()
        self._st.cache_data.clear()
        # Stato del confronto FALLITO + nessun dato del giro: le tabelle in
        # vista devono restare in piedi, con le celle di «Modello %» vuote.
        self.at.session_state["confronto_modello_stato"] = "non_disponibile"
        self.at.session_state["confronto_modello_righe"] = []
        self.at.session_state["confronto_modello_errore"] = "RuntimeError: giro giu'"
        self.at.session_state["confronto_modello_1x2"] = []

        def get_giu(url, **kw):
            self.get_http.append(url)
            raise RuntimeError("fonte del calendario non raggiungibile")

        with mock.patch.object(requests, "get", get_giu):
            self.at.run(timeout=900)
        self.eccezioni(self.at, "confronto col modello non disponibile")
        # «Per raddoppiare» sta nella scheda Multiple, la tabella dei pronostici
        # in Pronostici. Qui non si preme niente: un confronto fallito non scrive
        # e non toglie niente in vista (la caption dello stato segue la tabella,
        # e la tabella arriva solo dopo un click: test_apptest_scheda_pronostici).
        fuori, _ = _testi_della_tab(self.at, SCHEDA_MULTIPLE)
        testo = " \n".join(fuori)
        self.assertIn("Per raddoppiare", testo,
                      "il confronto col modello non e' un prerequisito")
        self.assertNotIn("Modello %: non disponibile", testo,
                         "la caption dello stato sta sotto la tabella, non qui")
        # In questa classe il click c'e' gia' stato (test 03): la tabella e'
        # rimasta in vista, come promesso. Il lettore di AppTest duplica ogni
        # caption (due attributi dello stesso elemento), quindi si conta sulle
        # righe uniche: la frase dello stato deve comparire UNA volta sola, non
        # una per riga.
        fuori_pr, _ = _testi_della_tab(self.at, SCHEDA_PRONOSTICI)
        uniche = list(dict.fromkeys(fuori_pr))
        self.assertEqual(1, sum(t.count("Modello %: non disponibile") for t in uniche),
                         "la caption dice una volta che il giro del modello non c'e'")
        self.assertIn("Le scelte più sicure secondo le quote", " \n".join(fuori_pr))
        self.assertNotIn("n/d", testo,
                         "le celle restano vuote: nessuno stato scritto nella colonna")
        self.assertNotIn("d'accordo", testo.lower(),
                         "nemmeno con il modello giu' compare il segnale in vista")
        self.assertEqual([], self._scritture(self.chiamate_registro),
                         "un confronto fallito non scrive nulla")


if __name__ == "__main__":
    unittest.main()
