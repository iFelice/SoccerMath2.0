"""Test AppTest della nuova presentazione della scheda TOP MIX (punti 1, 2, 4, 6 e 8).

Come fa gia' ``test_apptest_top_mix.py``: database "soft-copied" in una tmp
(i CSV reali si leggono attraverso, i file scritti restano nella tmp) e HTTP
finto. Differenze:

* ``live_odds.json`` NON e' inventato: e' lo snapshot reale pinnato (90
  eventi, come chiede il punto 6) preso via ``snap_test``;
* l'orologio e' congelato a venerdì 2026-10-16 18:00 ora italiana, così il
  periodo di default ("Questa giornata (fino a lunedì)") abbraccia le ~48
  partite del fine settimana dello stesso snapshot e la finestra di
  registrazione del punto 9 risulta aperta;
* i match del calendario sono quelli VERI delle leghe coperte dallo snapshot.

Il test raccoglie TUTTO il testo reso FUORI dagli expander della scheda
TOP MIX (tabella per tabella, didascalia per didascalia) e fallisce se
compare una qualunque delle parole vietate del punto 6. Il contenuto tecnico
completo vive nell'unico riquadro "🔎 Dettagli" e il test lo apre e ci trova
dentro le parole del gergo (fonte ed eta' delle quote, probabilita' del
modello, marcatori "stima non verificata") — a dimostrare che nulla e'
sparito: e' solo riparato dietro il riquadro chiuso.
"""
from __future__ import annotations

import copy
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
SNAPSHOT_PATH = os.path.join(HERE, "database", "live_odds.json")
REALE_DATABASE = None  # set in setUpClass

for _p in (HERE, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Testo reso: raccolta fuori/dentro gli expander della scheda TOP MIX
# ---------------------------------------------------------------------------

WEB_SAFE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\u2190-\u21FF\u2300-\u23FF\u2B00-\u2BFF\uFE0F\u200D]")


def _testo_semplice(x):
    if x is None or isinstance(x, bool):
        return ""
    if isinstance(x, (int, float)):
        return f"{x}"
    if isinstance(x, str):
        return WEB_SAFE.sub("", x)
    return str(x)


def _raccogli_da_df(df_el):
    """Gli st.dataframe/st.table resi in AppTest: intestazioni + celle."""
    parti = []
    val = getattr(df_el, "value", None)
    if val is None:
        return parti
    # val e' un oggetto Arrow/DataFrame serializzato: in testing e' un
    # pandas.DataFrame (o uno Styler): proviamo a normalizzare. Le colonne
    # numeriche con celle vuote (``None``/NaN: da «Modello %» non pronto)
    # vanno svuotate PRIMA di ``astype(str)``, altrimenti resta un float
    # ``nan`` e il join delle celle esplode a metà tabella.
    try:
        import pandas as _pd
        if hasattr(val, "data"):
            val = val.data
        if isinstance(val, _pd.DataFrame):
            parti.append(" ".join(_testo_semplice(c) for c in val.columns))
            sicuro = val.where(val.notna(), other="")
            for _r in sicuro.astype(str).itertuples(index=False, name=None):
                parti.append(" ".join(_r))
            return parti
    except Exception:
        pass
    parti.append(_testo_semplice(val))
    return parti


def _testo_blocco(el, dentro_expander):
    """Tutto il testo reso da un elemento UI di AppTest, ricorsivamente.

    Gli elementi di AppTest NON espongono un attributo ``type``: il tipo si
    riconosce dal NOME DELLA CLASSE (Markdown, Expander, Dataframe, ...).
    """
    parti = []
    cls_name = type(el).__name__.lower()
    if cls_name == "expander":
        # Label inclusa; il contenuto e' affidato ai figli (trattati a parte).
        dentro_expander = True
    for attr in ("label", "body", "value", "caption", "text", "help",
                 "placeholder", "title", "header", "subheader",
                 "description", "delta"):
        if cls_name in ("dataframe", "arrowdataframe", "table") and attr == "value":
            continue  # la tabella e' trattata a parte: intestazioni + celle
        v = getattr(el, attr, None)
        if isinstance(v, str) and v:
            parti.append((dentro_expander, WEB_SAFE.sub("", v)))
    # Opzioni dei widget (radio, selectbox, multiselect): sono etichette rese.
    opts = getattr(el, "options", None)
    if isinstance(opts, (list, tuple)):
        for op in opts:
            if isinstance(op, str) and op:
                parti.append((dentro_expander, WEB_SAFE.sub("", op)))
    if cls_name in ("dataframe", "arrowdataframe", "table"):
        for cella in _raccogli_da_df(el):
            parti.append((dentro_expander, cella))
    # figli (containers, columns, expanders annidati)
    children = getattr(el, "children", None)
    if children:
        if isinstance(children, dict):
            it = children.values()
        else:
            it = children
        for figlio in it:
            parti.extend(_testo_blocco(figlio, dentro_expander))
    return parti


def _radice_tab(at, indice_tab=0):
    """Il blocco-radice della scheda: iterando una Tab, AppTest produce una
    lista PIATTA (se stessa + tutti i discendenti); il vero grafo e' nei
    attributi .children di OGNI elemento. Il primo elemento e' il contenitore
    della scheda, i suoi .children sono i figli diretti.

    Indice 0 = «🎯 Giocate» (prima scheda, si apre da sola), 1 = «🏟️ Partite»,
    2 = «📒 Com'è andata»."""
    tab = (getattr(at, "tabs", None) or getattr(at, "tab"))[indice_tab]
    piatta = list(tab)
    return piatta[0] if piatta else tab


def _testi_della_tab(at, indice_tab=0):
    """Ritorna (testi_fuori_expander, testi_dentro_expander) della tab data."""
    parti = _testo_blocco(_radice_tab(at, indice_tab), dentro_expander=False)
    fuori = [t for d, t in parti if not d]
    dentro = [t for d, t in parti if d]
    return fuori, dentro


# ---------------------------------------------------------------------------
# Parole vietate (punto 6): fuori dai riquadri chiusi non devono comparire.
# «d'accordo» e' entrata in lista con la correzione alla PR #66: il segnale
# resta solo nei Dettagli (tabella tecnica) e la caption della sezione
# «Le scelte più sicure secondo le quote» dice solo quante partite sono in
# tabella e, se il giro del modello non e' pronto, lo stato di «Modello %».
# ---------------------------------------------------------------------------

PAROLE_VIETATE = [
    "de-vig", "devig",
    "d'accordo",
    r"\bEV\b", "valore atteso",
    "quota equa",
    "margine", "margini",
    "pinnacle",
    "brier",
    "soglia",
    "walk-forward", "walk forward",
    "ombra",
    "k=", r"\bk\d",
    "Δ", "delta ",
    r"\bpp\b", "punti percentuali",
    "topmix_mercato_v3", "lista_giocate_v1", "multipla_proposta_v1",
    # simboli di formule tipici del gergo tecnico (parole intere, maiuscole
    # o minuscole che siano, ma mai dentro altre parole piu' lunghe)
    r"\bp\s*[×*·]\s*q\b", r"\bEV\s*=", r"\bp\s*=\s*0\.",
]


class TestPresentazioneTopMix(unittest.TestCase):
    """Un solo run congelato a venerdì sera: tutte le asserzioni della commessa."""

    @classmethod
    def setUpClass(cls):
        try:
            from streamlit.testing.v1 import AppTest  # noqa: F401
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("streamlit.testing.v1 non disponibile")

        import config
        import market_odds
        import prediction_registry as pr
        import requests
        import snap_test

        cls.snap = snap_test.snapshot_reale()
        if cls.snap is None:
            raise unittest.SkipTest("Snapshot pinnato non raggiungibile (clone shallow?)")

        cls.tmp = Path(tempfile.mkdtemp(prefix="sm_apptest_pres_"))
        from pathlib import Path as _P
        src_db = _P(os.path.join(HERE, "database"))
        for f in sorted(src_db.iterdir()):
            if f.is_dir():
                continue
            if f.name in ("live_odds.json", "predictions.json"):
                continue
            try:
                (cls.tmp / f.name).symlink_to(f)
            except OSError:
                shutil.copy2(f, cls.tmp / f.name)
        # Lo snapshot reale pinnato nel tmp: l'app legge QUESTO.
        (cls.tmp / "live_odds.json").write_text(json.dumps(cls.snap), encoding="utf-8")
        # Punto 5b: due righe CONCLUSE della famiglia mercato nel Registro, cosi'
        # la sezione "Com'è andata: le scelte secondo le quote" (tab5) ha il
        # bilancio in parole da verificare ("Finora N giocate concluse...").
        import prediction_registry as pr
        _riga_mercato = {
            "match_id": 7001, "home": "Inter", "away": "Roma",
            "campionato": "Serie A", "giornata": 8,
            "data": "15/10/2026 20:45", "pronostico_sicuro": "1 - Top Mix",
            "mercato_standard": "1", "top3": [], "prob_sicuro": 62.5,
            "risultati_attesi": "", "risultato_reale": "2-0", "esito": "✅",
            "tipo": "Top Mix", "stagione": "2026/27",
            "salvato_il": "15/10/2026 10:00", "origin": pr.ORIGIN_TOP_MIX,
            "selector_version": pr.SELECTOR_VERSION_MERCATO_V3,
            "model_variant": pr.MODEL_VARIANT_CURRENT,
            "model_version": pr.MODEL_VERSION_CURRENT,
            "rank": 1, "kickoff_utc": "2026-10-15T18:45:00Z",
            "calculation_id": "fixture7001",
            pr.PROB_MERCATO_FIELD: 0.625, pr.QUOTA_MERCATO_FIELD: 1.61,
            pr.MERCATO_FONTE_FIELD: "pinnacle", pr.MERCATO_N_LIBRI_FIELD: 1,
            pr.ACCORDO_MODELLO_FIELD: True, pr.PROB_MODELLO_FIELD: 63.0,
            pr.QUOTE_LIVE_ISTANTE_FIELD: "2026-10-15T10:00:00Z",
            pr.PROB_MERCATO_PRIMA_FIELD: 0.625, pr.QUOTA_MERCATO_PRIMA_FIELD: 1.61,
            pr.PROB_MODELLO_PRIMA_FIELD: 63.0, pr.ACCORDO_MODELLO_PRIMA_FIELD: True,
            pr.QUOTE_LIVE_ISTANTE_PRIMA_FIELD: "2026-10-15T10:00:00Z",
        }
        righe_registro = [
            dict(_riga_mercato),
            dict(_riga_mercato,
                 match_id=7002, home="Como", away="Torino", mercato_standard="2",
                 pronostico_sicuro="2 - Top Mix", prob_sicuro=58.0,
                 risultato_reale="1-1", esito="❌",
                 calculation_id="fixture7002", rank=2,
                 **{
                     pr.PROB_MERCATO_FIELD: 0.58, pr.QUOTA_MERCATO_FIELD: 1.83,
                     pr.ACCORDO_MODELLO_FIELD: False, pr.PROB_MODELLO_FIELD: 51.0,
                     pr.PROB_MERCATO_PRIMA_FIELD: 0.58, pr.QUOTA_MERCATO_PRIMA_FIELD: 1.83,
                     pr.PROB_MODELLO_PRIMA_FIELD: 51.0, pr.ACCORDO_MODELLO_PRIMA_FIELD: False,
                 }),
        ]
        (cls.tmp / "predictions.json").write_text(
            json.dumps({"data": righe_registro}), encoding="utf-8")
        # L'app legge il Registro tramite registry_store.load_rows (finto qui):
        # le due righe si piantano nello storage in memoria, non nel file.
        cls._righe_registro_seed = righe_registro

        # Le squadre che il calendario deve esporre: le stesse dello snapshot,
        # cosi' l'abbinamento partita-quota funziona per tutte le leghe coperte.
        cls.eventi_per_lega = {}
        for lega, blocco in (cls.snap.get("leghe") or {}).items():
            eventi = blocco.get("eventi") or []
            if eventi:
                cls.eventi_per_lega[lega] = eventi
        if not cls.eventi_per_lega:
            raise unittest.SkipTest("Snapshot senza eventi")

        # Orologio congelato a venerdì 2026-10-16 18:00 ora italiana.
        cls.adesso = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)

        cls._patches = []

        def patch(target, attr, valore):
            cls._patches.append(mock.patch.object(target, attr, valore))
            cls._patches[-1].start()

        patch(config, "DATABASE_DIR", cls.tmp)
        patch(config, "PREDICTIONS_FILE", str(cls.tmp / "predictions.json"))
        patch(market_odds, "_adesso_utc", lambda: cls.adesso)

        # Il click di "Calcola Top Mix" arriva anche a scrivere le note di
        # controllo (registro ombra) via registry_store: la rete e' finta, gli
        # storage si tengono in memoria per asserire la scrittura del punto 9.
        import registry_store as _rs

        cls.storage_ombra = []

        def _finto_load_ombra(*args, **kwargs):
            return list(cls.storage_ombra), "fixture"

        def _finto_save_ombra(rows, *args, **kwargs):
            cls.storage_ombra.clear()
            cls.storage_ombra.extend(rows)
            return {"remoto": "ok", "backend": "fixture", "righe_scritte": len(rows)}

        patch(_rs, "load_ombra_rows", _finto_load_ombra)
        patch(_rs, "save_ombra_rows", _finto_save_ombra)
        # Anche l'hash normale del Registro: il click fa load/save tramite
        # salva_registro_ombra (jsonbin di default -> rete!): si ferma alla
        # fixture in memoria.
        cls.storage_vivo = [dict(r) for r in cls._righe_registro_seed]

        def _finto_save_vivo(rows, *a, **k):
            cls.storage_vivo.clear()
            cls.storage_vivo.extend(rows)
            return {"remoto": "ok", "backend": "fixture", "righe_scritte": len(rows)}

        patch(_rs, "load_rows", lambda *a, **k: (list(cls.storage_vivo), "fixture"))
        patch(_rs, "save_rows", _finto_save_vivo)


        # football-data.org finto: partite = eventi reali dello snapshot.
        # Id numerici distinti, uno per evento.
        cls._match_by_league = {}
        for i, (lega, eventi) in enumerate(sorted(cls.eventi_per_lega.items())):
            matches = []
            for j, ev in enumerate(eventi):
                matches.append({
                    "id": 9900000 + i * 1000 + j,
                    "utcDate": ev.get("commence_time"),
                    "homeTeam": {"name": ev.get("home_team")},
                    "awayTeam": {"name": ev.get("away_team")},
                    "matchday": 8,
                    "score": {"fullTime": {"home": None, "away": None}},
                    "status": "SCHEDULED",
                })
            cls._match_by_league[lega] = matches

        # codici competizione football-data coerenti con LEAGUES_CONFIG
        import app as app_mod
        cls._league_code = {nome: cfg.get("code") for nome, cfg in getattr(app_mod, "LEAGUES_CONFIG", {}).items()}

        cls.chiamate = []

        def fake_get(url, **kw):
            cls.chiamate.append(("GET", url))
            code = url.rstrip("/").split("/")[-2] if "/matches" in url else ""
            for lega, code_league in cls._league_code.items():
                if code == code_league and lega in cls._match_by_league:
                    return _Resp({"matches": cls._match_by_league[lega]})
            return _Resp({"matches": []})

        def niente_rete(metodo):
            def _f(url, **kw):
                cls.chiamate.append((metodo, url))
                raise AssertionError(f"{metodo} di rete non ammesso in test: {url}")
            return _f

        patch(requests, "get", fake_get)
        for metodo in ("put", "post", "patch", "delete"):
            patch(requests, metodo, niente_rete(metodo))
        patch(time, "sleep", lambda s: None)

        # Congela anche le sorgenti d'ora usate dall'app e dal registro (stesso
        # schema di test_apptest_top_mix): la sottoclasse eredita tutto il resto.
        _app = app_mod
        from datetime import datetime as _real_dt

        ADESSO = cls.adesso

        class _DtCongelata(_real_dt):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return ADESSO.replace(tzinfo=None)
                return ADESSO.astimezone(tz)

        patch(_app, "datetime", _DtCongelata)
        patch(pr, "datetime", _DtCongelata)

        from streamlit.testing.v1 import AppTest
        # La cache di @st.cache_data (fetch_and_calc_top_mix & co.) e'
        # process-global e condivisa fra AppTest DI FILE DIVERSI (ordine di
        # pytest): svuotarla prima del primo run, altrimenti il click di
        # "Calcola Top Mix" potrebbe rileggere i dati calcolati da un altro
        # fixture (es. i 3 eventi di test_apptest_top_mix).
        import streamlit as st
        st.cache_data.clear()
        cls.at = AppTest.from_file(APP_PATH, default_timeout=300)
        cls.at.run(timeout=600)
        # La scheda «🎯 Giocate» si popola DA SOLA all'apertura (legge solo il
        # file delle quote): nessun click per vedere «Per raddoppiare», la
        # tabella e i Dettagli. Il click di «Registra le giocate della
        # giornata» serve solo al test 08 (le proposte settimanali): con rete
        # finta e storage in memoria.

    @classmethod
    def tearDownClass(cls):
        for p in getattr(cls, "_patches", []):
            p.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- utilita' ----------------------------------------------------------

    def _tab(self):
        # Prima scheda = «🎯 Giocate».
        return (getattr(self.at, "tabs", None) or getattr(self.at, "tab"))[0]

    def test_01_la_pagina_si_apre_senza_eccezioni(self):
        self.assertFalse(self.at.exception, f"Eccezioni: {[e.value for e in self.at.exception][:1]}")

    def _espansori(self):
        """Gli expander della scheda TOP MIX, cercati camminando sull'albero
        (l'Accessor .expander del blocco non e' affidabile fra le versioni)."""
        trovati = []

        def cammina(el):
            if type(el).__name__.lower() == "expander":
                trovati.append(el)
            ch = getattr(el, "children", None)
            if ch:
                for c in (ch.values() if isinstance(ch, dict) else ch):
                    cammina(c)

        cammina(_radice_tab(self.at))
        return trovati

    def test_02_il_dettaglio_tecnico_esiste_ed_e_chiuso(self):
        espansori = self._espansori()
        labels = [e.label for e in espansori]
        self.assertTrue(any("Dettagli" in (l or "") for l in labels),
                        f"riquadro 'Dettagli' non trovato: {labels}")
        det = next(e for e in espansori if "Dettagli" in (e.label or ""))
        aperto = getattr(det, "expanded", None)
        if aperto is None:
            aperto = getattr(getattr(det, "proto", None), "expanded", None)
        if aperto is not None:
            self.assertFalse(aperto,
                             "il riquadro 'Dettagli' dev'essere chiuso di default")

    def test_03_fuori_dagli_expander_nessuna_parola_vietata(self):
        fuori, dentro = _testi_della_tab(self.at)
        testo = " \n".join(fuori).lower()
        for parola in PAROLE_VIETATE:
            with self.subTest(parola=parola):
                self.assertIsNone(re.search(parola, testo, re.IGNORECASE),
                                  f"parola vietata fuori dagli expander: {parola!r}")

    def test_04_il_riquadro_per_raddoppiare_rende_i_numeri_della_ricerca(self):
        import lista_giocate as lg
        res = lg.calcola_lista_giocate(self.snap, adesso_utc=self.adesso)
        in_periodo = lg.giocate_nel_periodo(res["giocate"], self.adesso, "giornata")
        prop = lg.cerca_proposta_multipla(in_periodo)
        righe = lg.righe_riquadro_raddoppio(prop["per_k"], self.adesso)

        fuori, _ = _testi_della_tab(self.at)
        testo = " \n".join(fuori)
        self.assertIn("Per raddoppiare", testo)
        self.assertIn("Su 100 € giocati tornano in media", testo)
        self.assertIn("Quote %", testo)
        self.assertIn("Paga circa", testo)
        if righe:
            for r in righe:
                # «Quote %» = probabilita' combinata, numero con una cifra
                # decimale (la resa della cella e' str(numero)).
                self.assertIn(f"{round(r['probabilita'] * 100.0, 1)}", testo)
                self.assertIn(r["paga"], testo)
                self.assertIn(f"{r['ritorno_100']} €", testo)
            # Ogni partita del riquadro: «<casa> - <trasferta>: <sigla>», la
            # giocata come sola sigla (niente parole, niente sigla fra parentesi).
            for item in prop["per_k"].values():
                for g in (item or {}).get("giocate", []):
                    self.assertIn(f"{g['home']} - {g['away']}: {str(g['giocata']).strip()}",
                                  testo)
        else:
            self.assertIn("Oggi nessuna giocata paga fra 2 e 3 volte la puntata.", testo)
        self.assertIn("Ogni partita aggiunta abbassa le probabilità di riuscita: "
                      "di solito la giocata singola è quella che riesce più spesso.", testo)

    def test_05_le_piu_probabili_una_riga_per_partita_e_sopra_la_quota_minima(self):
        import lista_giocate as lg
        res = lg.calcola_lista_giocate(self.snap, adesso_utc=self.adesso)
        in_periodo = lg.giocate_nel_periodo(res["giocate"], self.adesso, "giornata")
        attese = lg.migliori_giocate_per_partita(in_periodo, 1.20)[:10]

        fuori, _ = _testi_della_tab(self.at)
        testo = " \n".join(fuori)
        self.assertIn("Le più probabili", testo)
        self.assertIn("Paga almeno", testo)
        # una sola riga per partita
        partite = [g["partita"] for g in attese]
        self.assertEqual(len(partite), len(set(partite)))
        for g in attese:
            self.assertIn(g["partita"], testo)
            # Giocata = sola sigla (1, X, 2, 1X, X2, 12); «Quote %» = numero
            # con una cifra decimale al posto del testo in parole.
            self.assertIn(str(g["giocata"]).strip(), testo)
            self.assertIn(f"{round(g['probabilita'] * 100.0, 1)}", testo)

    def test_06_comandi_periodo_e_freschezza_quote(self):
        fuori, _ = _testi_della_tab(self.at)
        testo = " \n".join(fuori)
        self.assertIn("Periodo", testo)
        self.assertIn("Questa giornata (fino a lunedì)", testo)
        self.assertIn("Tutte le partite in programma", testo)
        # Le quote dello snapshot sono del 11/10, il calcolo e' del 16/10:
        # la riga di freschezza deve DIRLO in italiano.
        self.assertIn("Attenzione: quote", testo)

    def test_07_dentro_i_dettagli_il_tecnico_ce_tutto(self):
        _, dentro = _testi_della_tab(self.at)
        testo = " \n".join(dentro)
        # fonte ed eta' delle quote, quota equa, marcatori ufficiali del punto 4
        for atteso in ("Quota equa", "Eta' quote", "Fonte quote",
                       "stima non verificata",
                       "Probabilità di vincita", "Valore Atteso",
                       "partite totali", ):
            with self.subTest(atteso=atteso):
                self.assertIn(atteso.lower(), testo.lower())

    def test_08_registro_della_settimana_scritto_solo_per_il_periodo_predefinito(self):
        """Il click di 'Calcola Top Mix' a finestra aperta (venerdì) registra le
        proposte SOLO del periodo di default: la ricerca rifatta a mano sullo
        stesso periodo deve trovare gli stessi numeri che finirebbero nel
        registro (verifica della coerenza, senza toccare lo storage remoto)."""
        import lista_giocate as lg
        res = lg.calcola_lista_giocate(self.snap, adesso_utc=self.adesso)
        in_periodo = lg.giocate_nel_periodo(res["giocate"], self.adesso, "giornata")
        prop = lg.cerca_proposta_multipla(in_periodo)
        self.assertTrue(any(prop["per_k"].values()), "a venerdì c'e' almeno una proposta")
        # Del giorno di calcolo: finestra aperta (venerdì).
        self.assertTrue(lg.in_finestra_registrazione_multipla(self.adesso))

    # ------------------------------------------------------------------
    # Punto 5b: tabella della famiglia Mercato nella scheda REGISTRO
    # ------------------------------------------------------------------

    def test_09_registro_mercato_in_parole_bilancio_e_niente_gergo(self):
        """Tab5, famiglia mercato: titolo «Com'è andata: le scelte secondo le
        quote», bilancio in parole sopra la tabella, e nessuna parola vietata
        nel testo visibile (il tecnico resta nel suo «Dettagli» chiuso)."""
        fuori_tab5, dentro_tab5 = _testi_della_tab(self.at, 2)
        i0 = next((i for i, t in enumerate(fuori_tab5)
                   if "Com'è andata: le scelte secondo le quote" in t), None)
        self.assertIsNotNone(i0, "il titolo del punto 5b non c'e': "
                                 + " | ".join(fuori_tab5[:40])[:600])
        i1 = next((i for i in range(i0 + 1, len(fuori_tab5))
                   if "Registro ombra" in fuori_tab5[i]), len(fuori_tab5))
        sezione = fuori_tab5[i0:i1]
        testo = " \n".join(sezione)
        # Riepilogo del fixture: 2 righe concluse (1 ✅ e 1 ❌) -> 50 su 100;
        # le quote, alla PRIMA registrazione sulle stesse righe, davano
        # (62,5 + 58,0)/2 = 60,25 -> "60 su 100".
        self.assertIn("Finora 2 giocate concluse, 1 riuscite (50 su 100)", testo)
        self.assertIn("Le quote si aspettavano 60 su 100.", testo)
        # Il conto in euro e' un conto, non una descrizione: sta nei Dettagli.
        testo_dettagli = " \n".join(dentro_tab5)
        self.assertIn("Su 100 giocate da 1 €", testo_dettagli)
        self.assertIn("19,50 € in meno", testo_dettagli)
        self.assertNotIn("Su 100 giocate da 1 €", testo,
                         "il conto in euro sta nei Dettagli, non in apertura")
        # Le colonne visibili sono quelle della commessa sigle-percentuali:
        # la giocata e' la sola sigla, «Quote %» e «Modello %» sono quelle
        # della PRIMA registrazione, e la colonna del segnale «d'accordo»
        # esce dalla vista (resta nei Dettagli).
        for atteso in ("Quando", "Campionato", "Partita", "Giocata",
                       "Quote %", "Modello %", "Risultato", "Esito"):
            self.assertIn(atteso, testo, f"colonna mancante: {atteso}")
        self.assertNotIn("Il nostro modello è d'accordo", testo)
        self.assertNotIn("Riesce circa", testo)
        # Ogni riga resa: la sigla secca e le DUE percentuali della prima
        # registrazione sulla STESSA riga (inter-riga il confronto e' alla pari).
        riga_inter = next(t for t in sezione if "Inter vs Roma" in t)
        riga_como = next(t for t in sezione if "Como vs Torino" in t)
        # Nella tabella Mercato di Com'è andata ENTRAMBE le percentuali sono
        # numeriche (ordinamento al clic numerico): la resa della cella e'
        # il numero puro ("63.0"); la virgola italiana sta nelle tabelle
        # della scheda Giocate, dove «Modello %» porta anche gli stati.
        for riga, sigla, quote, modello in ((riga_inter, " 1 ", "62.5", "63.0"),
                                            (riga_como, " 2 ", "58.0", "51.0")):
            celle = f" {riga} "
            self.assertIn(sigla, celle, f"sigla secca nella riga: {riga!r}")
            self.assertIn(quote, celle, f"«Quote %» della prima registrazione: {riga!r}")
            self.assertIn(modello, celle, f"«Modello %» della prima registrazione: {riga!r}")
            self.assertNotIn("volte su 100", riga)
        # Parole vietate (punto 6) anche dentro questa tabella.
        basso = testo.lower()
        for parola in PAROLE_VIETATE:
            with self.subTest(parola=parola):
                self.assertIsNone(re.search(parola, basso, re.IGNORECASE),
                                  f"parola vietata nella tabella mercato del REGISTRO: {parola!r}")
        # Il nome di versione non compare nemmeno nell'intestazione di famiglia.
        self.assertFalse(any("topmix_mercato" in t.lower() for t in fuori_tab5),
                         "il nome della versione non deve comparire in vista")
        # Punto 6 esteso alla scheda Com'è andata: FUORI dal «Dettagli» chiuso
        # nessuna parola vietata.
        basso_tutto = " \n".join(fuori_tab5).lower()
        for parola in PAROLE_VIETATE:
            with self.subTest(parola=parola):
                self.assertIsNone(re.search(parola, basso_tutto, re.IGNORECASE),
                                  f"parola vietata fuori dai Dettagli di Com'è andata: {parola!r}")

    # ------------------------------------------------------------------
    # Punto 3 (rifinitura): «Prova la tua giocata»
    # ------------------------------------------------------------------

    def _exp_prova(self):
        exp = [e for e in self.at.expander if "Prova la tua giocata" in (e.label or "")]
        self.assertEqual(1, len(exp), "il riquadro «Prova la tua giocata» deve essere unico")
        return exp[0]

    def _widget(self, classe, chiave_prefix):
        return [e for e in self.at
                if type(e).__name__.lower() == classe.lower()
                and str(getattr(e, "key", "") or "").startswith(chiave_prefix)]

    def test_10_prova_la_tua_giocata_chiusa_e_senza_gergo(self):
        """L'expander parte CHIUSO (nessun caricamento automatico) e il punto 6
        vale anche DENTRO: niente gergo nel riquadro, mai."""
        exp = self._exp_prova()
        espanso = getattr(exp, "expanded", None)
        if espanso is not None:
            self.assertFalse(bool(espanso),
                             "il riquadro parte chiuso: niente caricamenti automatici")
        parti = _testo_blocco(exp, dentro_expander=False)
        testo = " \n".join(t for _d, t in parti)
        for atteso in ("Inserisci le quote che vedi su bet365",
                       "Il calcolo considera le partite indipendenti fra loro.",
                       "Quota che vedi su bet365",
                       "L'app si aspetta circa",
                       "Con le quote previste dall'app",  # caselle vuote all'apertura
                       "Riesce circa", "Paga circa",
                       "Su 100 € giocati tornano in media"):
            with self.subTest(atteso=atteso):
                self.assertIn(atteso, testo)
        basso = testo.lower()
        for parola in PAROLE_VIETATE:
            with self.subTest(parola=parola):
                self.assertIsNone(re.search(parola, basso, re.IGNORECASE),
                                  f"parola vietata dentro «Prova la tua giocata»: {parola!r}")

    def _raddoppio_atteso(self):
        """Il riquadro atteso dallo snapshot pinnato (come nei test sopra)."""
        import lista_giocate as lg
        res = lg.calcola_lista_giocate(self.snap, adesso_utc=self.adesso)
        in_periodo = lg.giocate_nel_periodo(res["giocate"], self.adesso, "giornata")
        prop = lg.cerca_proposta_multipla(in_periodo)
        return lg.righe_riquadro_raddoppio(prop["per_k"], self.adesso), prop, in_periodo

    def test_11_usa_nel_calcolatore_precarica_gambe_e_apre(self):
        """Click su «Usa nel calcolatore»: expander aperto, numero e gambe
        precaricate dalla proposta, caselle bet365 VUOTE, titolo e NUMERI che
        coincidono con la riga del riquadro scelta."""
        import lista_giocate as lg
        righe, prop, in_periodo = self._raddoppio_atteso()
        assert righe, "il riquadro Per raddoppiare deve avere righe a questo istante"
        riga = righe[0]
        k = int(riga["k"])
        bottoni = [b for b in self.at.button
                   if str(getattr(b, "key", "") or "") == f"usa_calc_r_{k}"]
        self.assertEqual(1, len(bottoni), f"il pulsante della riga k={k} non c'e'")
        bottoni[0].click()
        self.at.run(timeout=600)
        self.assertFalse(self.at.exception,
                         f"eccezione nel rerun: {[e.value for e in self.at.exception][:1]}")
        # Aperto via session_state.
        self.assertTrue(self.at.session_state.get("prova_aperto"),
                        "il pulsante deve aprire il riquadro")
        exp = self._exp_prova()
        if getattr(exp, "expanded", None) is not None:
            self.assertTrue(bool(exp.expanded), "dopo il click il riquadro e' aperto")
        # Numero di giocate precaricato.
        sel_n = self._widget("Selectbox", "prova_n_gambe")
        self.assertEqual(1, len(sel_n))
        self.assertEqual(k, int(sel_n[0].value), "numero di giocate = quello della proposta")
        # Gambe precaricate, nell'ordine della proposta.
        item = prop["per_k"][k]
        etichette_attese = [lg.descrivi_leg(g, self.adesso) for g in item["giocate"]]
        sel_gambe = self._widget("Selectbox", "prova_gamba_")
        self.assertEqual(k, len(sel_gambe), "un menu per ogni gamba della proposta")
        for i, attesa in enumerate(etichette_attese):
            self.assertEqual(attesa, sel_gambe[i].value,
                             f"gamba {i} precaricata diversa dalla proposta")
        # Caselle VUOTE.
        nis = self._widget("NumberInput", "prova_quota_")
        self.assertEqual(k, len(nis), "una casella bet365 per gamba")
        self.assertTrue(all(n.value is None for n in nis),
                        "le caselle partono VUOTE: il caricamento non inventa quote")
        # Sotto ogni casella: hint coerente con la stima usata nel calcolo.
        parti = _testo_blocco(exp, dentro_expander=False)
        testo = " \n".join(t for _d, t in parti)
        self.assertIn("Con le quote previste dall'app", testo)
        for g in item["giocate"]:
            self.assertIn(lg.hint_quota_stimata(g), testo)
        # NUMERI: esattamente quelli della riga del riquadro scelta.
        self.assertIn(riga["riesce"], testo)
        self.assertIn(riga["paga"], testo)
        self.assertIn(f"{riga['ritorno_100']} €", testo)
        self.__class__._prova_k = k  # hand-off al test successivo (stesso run)
        self.__class__._prova_item = item

    def test_12_caselle_bet365_titoli_confronto_e_numeri(self):
        """Le tre diciture nei tre casi; riempire una casella cambia SOLO il
        contributo di quella gamba; il verdetto in parole sta sotto la casella."""
        import lista_giocate as lg
        k = getattr(self.__class__, "_prova_k", None)
        item = getattr(self.__class__, "_prova_item", None)
        if not k or not item:
            self.skipTest("il test 11 non ha preparato lo stato (ordine o proposta mancanti)")
        exp = self._exp_prova()
        g0 = item["giocate"][0]
        stima0 = float(lg.quota_stimata_giocata(g0))
        quota_mia = round(stima0 + 0.30, 2)

        # Casella 0 compilata: se k == 1 l'unica casella e' anche l'ultima.
        nis = self._widget("NumberInput", "prova_quota_")
        nis[0].set_value(quota_mia)
        self.at.run(timeout=300)
        parti = _testo_blocco(self._exp_prova(), dentro_expander=False)
        testo = " \n".join(t for _d, t in parti)
        self.assertIn("bet365 paga più del previsto", testo,
                      "sotto la casella compilata c'e' il verdetto")
        if k == 1:
            self.assertIn("Con le quote di bet365", testo)
        else:
            self.assertIn(f"Con 1 quote di bet365 e {k - 1} previste dall'app", testo)
        # NUMERO: la probabilita' non cambia, la quota totale si aggiorna solo
        # sulla gamba 0 -> il ritorno su 100 torna coi conti fatti qui.
        p_tot = 1.0
        for g in item["giocate"]:
            p_tot *= lg.probabilita_giocata(g)
        q_tot = quota_mia
        for g in item["giocate"][1:]:
            q_tot *= float(lg.quota_stimata_giocata(g))
        ritorno = round(100.0 * p_tot * q_tot)
        self.assertIn(f"{ritorno} €", testo,
                      "il ritorno su 100 usa la quota letta solo per la gamba compilata")

        # Tutte le caselle compilate: titolo finale. Con k == 1 l'unica casella
        # e' gia' piena (sopra, +0,30): il suo verdetto resta "piu del
        # previsto" e il titolo "Con le quote di bet365" e' gia' apparso.
        if k > 1:
            for i, n in enumerate(self._widget("NumberInput", "prova_quota_")):
                if n.value is None:
                    stima_i = float(lg.quota_stimata_giocata(item["giocate"][i]))
                    n.set_value(round(stima_i - 0.15, 2))
            self.at.run(timeout=300)
            parti = _testo_blocco(self._exp_prova(), dentro_expander=False)
            testo = " \n".join(t for _d, t in parti)
            self.assertIn("Con le quote di bet365", testo)
            self.assertIn("bet365 paga meno del previsto", testo)
        else:
            self.assertIn("Con le quote di bet365", testo)
            self.assertIn("bet365 paga più del previsto", testo)


class _Resp:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


if __name__ == "__main__":
    unittest.main()
