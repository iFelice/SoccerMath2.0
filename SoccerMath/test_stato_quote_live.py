"""test_stato_quote_live.py — stato del file quote, obsolescenza, finestra, famiglie.

Copre le quattro correzioni alla PR del Top Mix di mercato. Ogni test e'
deterministico: i file delle quote sono SCRITTI dal test in una cartella
temporanea, quindi non dipendono da ``database/live_odds.json`` ne' dall'orologio
di sistema (l'eta' e' sempre calcolata contro un ``adesso`` fissato).

1. STATO del file: ``assente`` / ``non_leggibile`` / ``senza_leghe`` / ``ok``,
   con un messaggio DIVERSO per ciascuno (dire "il file non c'e'" quando il file
   c'e' ed e' corrotto nasconde un guasto reale).
2. OBSOLESCENZA: ``ore_da`` e ``SOGLIA_ORE_QUOTE`` = 36 h; oltre soglia le righe
   restano visibili ma l'eta' si legge in UI e su ogni riga.
3. FINESTRA di ``cerca_quote``: oltre ``MASSIMO_SCARTO_ORARIO_QUOTE`` (72 h)
   nessun evento viene agganciato e la partita va in "senza quote".
4. ``non_abbinati`` della fonte: avviso dedicato, distinto dalle partite del
   calendario senza quote.
5. STATISTICHE per famiglia di selettore: modello e mercato non si sommano.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

logging.getLogger("streamlit").setLevel(logging.ERROR)

import market_odds as mo  # noqa: E402
import prediction_registry as R  # noqa: E402
import app  # noqa: E402

# Istante di riferimento fisso: nessun test dipende dall'orologio di sistema.
ADESSO = datetime(2026, 10, 9, 20, 0, 0, tzinfo=timezone.utc)
FRESCO = (ADESSO - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")     # 2 h
VECCHIO = (ADESSO - timedelta(hours=37)).strftime("%Y-%m-%dT%H:%M:%SZ")   # 37 h > 36
KICKOFF = "2026-10-10T13:00:00Z"


def _pulisci_cache_radice():
    """Svuota la cache dei livelli del logger RADICE.

    ``logging.disable(CRITICAL)`` (chiamato a livello di MODULO da sei file di
    test dell'audit, prima che pytest esegua qualunque test) fa memorizzare
    ``False`` in ``Logger._cache`` per ogni livello gia' chiesto. Il ripristino
    ``logging.disable(NOTSET)`` svuota la cache dei logger NOMINATI ma non
    quella della radice, quindi i ``logging.warning`` di app.py (che passano
    dalla radice) restano muti. Senza questa pulizia il test passa da solo e
    fallisce in suite completa.
    """
    logging.getLogger()._cache.clear()


def _pulisci_cache_livelli_log():
    """Svuota la cache dei livelli di ogni logger.

    ``logging.disable(CRITICAL)`` (chiamato a livello di MODULO da sei file di
    test dell'audit, prima che pytest esegua qualunque test) non si limita a
    alzare ``manager.disable``: fa memorizzare ``False`` in ``Logger._cache``
    per ogni livello gia' chiesto. ``logging.disable(NOTSET)`` rimette a zero il
    disable ma NON svuota quella cache, quindi un logger interrogato durante il
    disable resta muto anche dopo. Senza questa pulizia i test sui log passano
    da soli e falliscono in suite completa.
    """
    logger = [logging.getLogger()]
    logger.extend(v for v in logging.root.manager.loggerDict.values()
                  if isinstance(v, logging.Logger))
    for lg in logger:
        lg._cache.clear()


class RipristinaLogging:
    """Riabilita i log: sei file di test dell'audit li disabilitano a import."""

    def setUp(self):
        self._disable_precedente = logging.root.manager.disable
        logging.disable(logging.NOTSET)
        _pulisci_cache_radice()
        _pulisci_cache_livelli_log()
        mo._AVVISI_DATI.discard("file_assente")
        if hasattr(super(), "setUp"):
            super().setUp()

    def tearDown(self):
        logging.disable(self._disable_precedente)
        _pulisci_cache_radice()
        _pulisci_cache_livelli_log()


def evento(home, away, commence=KICKOFF, libri="pinnacle"):
    if libri == "pinnacle":
        lista = [{"key": "pinnacle", "h2h": {"home": 1.62, "draw": 4.1, "away": 6.0}}]
    elif libri == "nessuno":
        lista = [{"key": "pinnacle", "h2h": {"home": None, "draw": 4.1, "away": 6.0}}]
    else:
        lista = libri
    return {"id": f"{home}-{away}", "commence_time": commence,
            "home_team": home, "away_team": away, "libri": lista}


def payload(eventi, generato_il=FRESCO, lega="Serie A"):
    return {"schema": mo.SCHEMA_LIVE_ODDS, "generato_il": generato_il,
            "leghe": {lega: {"eventi": eventi}}}


class FileTemporaneo:
    """Mixin: scrive live_odds.json in una tmp dir e punta l'app li'.

    NON deriva da ``unittest.TestCase`` di proposito. Se lo facesse, l'MRO delle
    classi che combinano i due mixin metterebbe ``TestCase`` PRIMA di
    ``RipristinaLogging`` e il ``super().setUp()`` di questa classe si fermerebbe
    su ``TestCase.setUp`` (che non fa nulla): i log resterebbero disabilitati e i
    test sui WARNING passerebbero da soli fallendo in suite completa. L'ordine
    delle basi e' quindi ``(FileTemporaneo, RipristinaLogging, TestCase)``.
    """

    def setUp(self):
        super().setUp()          # RipristinaLogging: senza, i log restano spenti
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, mo.LIVE_ODDS_FILE)

    def scrivi(self, obj):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)

    def stato(self):
        with mock.patch.object(app, "DATABASE_DIR", self.tmp.name):
            return app.carica_indice_quote_live()


# ---------------------------------------------------------------- 1. stati
class TestStatiDelFile(FileTemporaneo, RipristinaLogging, unittest.TestCase):
    """Un messaggio per ogni modo di non avere quote."""

    def test_assente(self):
        s = self.stato()
        self.assertEqual(mo.STATO_ASSENTE, s["stato"])
        self.assertIsNone(s["indice"])
        self.assertIn("non esiste", s["dettaglio"])
        self.assertNotIn("non c'e'", s["dettaglio"],
                         "il testo deve dire che il file non ESISTE, non un generico 'non c'e'")

    def test_non_leggibile(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{non e' json")
        s = self.stato()
        self.assertEqual(mo.STATO_NON_LEGGIBILE, s["stato"])
        self.assertIsNone(s["indice"])
        self.assertIn("ESISTE", s["dettaglio"],
                      "il file c'e': il messaggio non deve dire che manca")
        self.assertIn("non e' leggibile", s["dettaglio"])

    def test_senza_leghe(self):
        # JSON valido ma senza la chiave 'leghe': schema sbagliato o scrittura
        # interrotta. E' un guasto, non un'assenza.
        self.scrivi({"schema": mo.SCHEMA_LIVE_ODDS, "generato_il": FRESCO})
        s = self.stato()
        self.assertEqual(mo.STATO_SENZA_LEGHE, s["stato"])
        self.assertIsNone(s["indice"])
        self.assertIn("ESISTE", s["dettaglio"])
        self.assertIn("leghe", s["dettaglio"])

    def test_ok_con_eventi(self):
        self.scrivi(payload([evento("Inter", "Roma")]))
        s = self.stato()
        self.assertEqual(mo.STATO_OK, s["stato"])
        self.assertEqual(1, len(s["indice"]))
        self.assertIsNone(s["dettaglio"])
        self.assertFalse(s["obsoleto"])

    def test_ok_senza_eventi_ha_indice_vuoto_non_assente(self):
        """Il caso che prima passava in silenzio: file valido, zero partite."""
        self.scrivi(payload([]))
        s = self.stato()
        self.assertEqual(mo.STATO_OK, s["stato"])
        self.assertIsNotNone(s["indice"], "indice vuoto, NON None: le partite vanno segnalate")
        self.assertEqual({}, s["indice"])

    def test_i_quattro_stati_sono_tutti_distinti(self):
        self.assertEqual(4, len(set(mo.STATI_FILE_QUOTE)))
        testi = set()
        for stato in (mo.STATO_ASSENTE, mo.STATO_NON_LEGGIBILE, mo.STATO_SENZA_LEGHE):
            testi.add(app._DETTAGLIO_STATO_QUOTE[stato])
        self.assertEqual(3, len(testi), "tre stati, tre messaggi diversi")

    def test_carica_quote_live_con_stato_e_retrocompatibile(self):
        p, stato = mo.carica_quote_live_con_stato(self.path)
        self.assertIsNone(p)
        self.assertEqual(mo.STATO_ASSENTE, stato)
        self.assertIsNone(mo.carica_quote_live(self.path),
                          "il wrapper vecchio continua a tornare solo il payload")


# ------------------------------------------------------- 2. obsolescenza
class TestObsolescenza(FileTemporaneo, RipristinaLogging, unittest.TestCase):
    """L'orologio e' CONGELATO su ADESSO: nessun test dipende dall'ora reale."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(mo, "_adesso_utc", return_value=ADESSO)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_ore_da(self):
        self.assertAlmostEqual(2.0, mo.ore_da(FRESCO, ADESSO), places=6)
        self.assertAlmostEqual(37.0, mo.ore_da(VECCHIO, ADESSO), places=6)
        self.assertAlmostEqual(-2.0, mo.ore_da(
            (ADESSO + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"), ADESSO), places=6)

    def test_ore_da_non_valido_torna_none_non_zero(self):
        for valore in (None, "", "   ", "non una data", 12345):
            self.assertIsNone(mo.ore_da(valore, ADESSO), repr(valore))

    def test_soglia_e_36_ore(self):
        self.assertEqual(36, mo.SOGLIA_ORE_QUOTE)

    def test_file_vecchio_di_37_ore_e_obsoleto(self):
        self.scrivi(payload([evento("Inter", "Roma")], generato_il=VECCHIO))
        s = self.stato()
        self.assertEqual(mo.STATO_OK, s["stato"], "vecchio non vuol dire inutilizzabile")
        self.assertTrue(s["obsoleto"])
        self.assertAlmostEqual(37.0, s["eta_ore"], places=1)

    def test_file_fresco_non_e_obsoleto(self):
        self.scrivi(payload([evento("Inter", "Roma")], generato_il=FRESCO))
        self.assertFalse(self.stato()["obsoleto"])

    def test_timestamp_corrotto_non_diventa_fresco(self):
        self.scrivi(payload([evento("Inter", "Roma")], generato_il="ieri"))
        s = self.stato()
        self.assertIsNone(s["eta_ore"])
        self.assertFalse(s["obsoleto"], "non si dichiara obsoleto cio' che non si sa datare")

    def test_le_righe_restano_visibili_con_eta(self):
        """Oltre soglia le righe NON spariscono: l'eta' si legge sulla riga."""
        riga = {"home": "Inter", "away": "Roma", "league": "Serie A", "giornata": 8,
                "utcDate": KICKOFF, "market": "Vittoria Inter", "mercato_standard": "1",
                "esito": "1", "prob": 0.6006, "prob_val": 60.1, "quota": 1.62,
                "prob_modello": 0.612, "prob_modello_val": 61.2, "accordo": True,
                "fonte": mo.FONTE_PINNACLE, "n_libri": 1, "quote_live_istante": VECCHIO,
                "rank": 1}
        tab = app.tabella_top_mix_mercato([riga])
        self.assertIn("Eta' quote (h)", tab.columns)
        self.assertAlmostEqual(37.0, float(tab["Eta' quote (h)"].iloc[0]), places=1)
        # e la riga senza timestamp non finge un'eta'
        riga2 = dict(riga, quote_live_istante=None)
        self.assertEqual("n/d", app.tabella_top_mix_mercato([riga2])["Eta' quote (h)"].iloc[0])

    def test_log_di_obsolescenza(self):
        self.scrivi(payload([evento("Inter", "Roma")], generato_il=VECCHIO))
        with self.assertLogs(level="WARNING") as cat:
            self.stato()
        self.assertIn("OBSOLETE", "\n".join(cat.output))


# ------------------------------------------------------------- 3. finestra
class TestFinestraDiAbbinamento(RipristinaLogging, unittest.TestCase):

    def indice_con(self, commence):
        return mo.indice_partite({"leghe": {"Serie A": {
            "eventi": [evento("Inter", "Roma", commence)]}}})["indice"]

    def test_soglia_dichiarata(self):
        self.assertEqual(72.0, mo.MASSIMO_SCARTO_ORARIO_QUOTE)

    def test_evento_del_05_contro_partita_del_12_non_aggancia(self):
        """Il test richiesto: 7 giorni di distanza, nessuna quota."""
        idx = self.indice_con("2026-10-05T13:00:00Z")
        self.assertIsNone(mo.cerca_quote(idx, "Inter", "Roma", "2026-10-12T18:45:00Z"))

    def test_evento_della_stessa_giornata_aggancia(self):
        idx = self.indice_con("2026-10-10T13:00:00Z")
        self.assertIsNotNone(mo.cerca_quote(idx, "Inter", "Roma", "2026-10-10T18:45:00Z"))

    def test_la_finestra_vale_anche_con_un_solo_candidato(self):
        """Prima la finestra era aggirata: con un candidato si tornava subito."""
        idx = self.indice_con("2026-10-05T13:00:00Z")
        self.assertEqual(1, len(idx[("Inter", "Roma")]))
        self.assertIsNone(mo.cerca_quote(idx, "Inter", "Roma", "2026-10-12T18:45:00Z"))

    def test_72_ore_sono_ancora_dentro(self):
        idx = self.indice_con("2026-10-10T13:00:00Z")
        # 71 h dopo: dentro. 73 h dopo: fuori.
        self.assertIsNotNone(mo.cerca_quote(idx, "Inter", "Roma", "2026-10-13T12:00:00Z"))
        self.assertIsNone(mo.cerca_quote(idx, "Inter", "Roma", "2026-10-13T14:30:00Z"))

    def test_finestra_disattivabile(self):
        idx = self.indice_con("2026-10-05T13:00:00Z")
        self.assertIsNotNone(mo.cerca_quote(idx, "Inter", "Roma", "2026-10-12T18:45:00Z",
                                            max_delta_ore=None))

    def test_senza_utcdate_nessuna_finestra(self):
        """Senza kickoff di riferimento non c'e' distanza da misurare."""
        idx = self.indice_con("2026-10-05T13:00:00Z")
        self.assertIsNotNone(mo.cerca_quote(idx, "Inter", "Roma"))

    def test_fuori_finestra_logga_e_la_partita_va_in_senza_quote(self):
        idx = self.indice_con("2026-10-05T13:00:00Z")
        with self.assertLogs("market_odds", level="WARNING") as cat:
            self.assertIsNone(mo.cerca_quote(idx, "Inter", "Roma", "2026-10-12T18:45:00Z"))
        self.assertIn("nessuno entro", "\n".join(cat.output))

    def test_motivo_della_riga_senza_quote(self):
        """End-to-end: partita con evento fuori finestra -> senza_quote col motivo."""
        def _match(mid, h, a):
            return {"id": mid, "matchday": 8, "utcDate": "2026-10-12T18:45:00Z",
                    "homeTeam": {"shortName": h}, "awayTeam": {"shortName": a}}
        stats = {"Inter": {"att": 1.25, "def": 0.85}, "Roma": {"att": 1.05, "def": 0.95}}
        elo = lambda h, a, l, season=None: {"1": 0.58, "X": 0.24, "2": 0.18}
        quote = {"indice": self.indice_con("2026-10-05T13:00:00Z"), "generato_il": FRESCO}
        with mock.patch.object(app, "predict_elo_probs", side_effect=elo), \
             mock.patch.object(app, "predict_elo_probs_legacy", side_effect=elo), \
             mock.patch.object(app, "_roster_stagione", return_value=None):
            righe = app.calcola_righe_top_mix(
                "Serie A", [_match(1, "Inter", "Roma")], (stats, 1.45, 1.15, None), quote=quote)
        self.assertEqual([], righe["mercato"])
        self.assertEqual(1, len(righe["senza_quote"]))
        self.assertEqual(mo.MOTIVO_FUORI_FINESTRA, righe["senza_quote"][0]["motivo"])


# ------------------------------------------------------ 4. non abbinati
class TestNonAbbinatiDellaFonte(FileTemporaneo, RipristinaLogging, unittest.TestCase):

    def test_nome_sconosciuto_esce_in_non_abbinati(self):
        self.scrivi(payload([evento("Inter", "Squadra Mai Vista FC")]))
        s = self.stato()
        self.assertEqual(1, len(s["non_abbinati"]))
        na = s["non_abbinati"][0]
        self.assertEqual("Squadra Mai Vista FC", na["away_raw"])
        self.assertEqual("Serie A", na["lega"])
        self.assertFalse(na["away_riconosciuto"])
        self.assertEqual(0, s["n_indicizzati"])

    def test_avviso_dedicato_distinto_da_quello_sulle_partite(self):
        self.scrivi(payload([evento("Inter", "Squadra Mai Vista FC")]))
        stato = self.stato()
        with mock.patch.object(app.st, "warning") as warn:
            app._mostra_non_abbinati_fonte(stato, "Top Mix")
        self.assertEqual(1, warn.call_count)
        testo = str(warn.call_args)
        self.assertIn("FONTE QUOTE", testo)
        self.assertIn("Squadra Mai Vista FC", testo)
        self.assertIn("Serie A", testo)
        self.assertIn("team_aliases.py", testo)
        # e' un avviso DIVERSO da quello sulle partite del calendario senza quote
        self.assertNotIn("partite SENZA quote di mercato", testo)

    def test_nessun_avviso_se_tutti_i_nomi_sono_noti(self):
        self.scrivi(payload([evento("Inter", "Roma")]))
        with mock.patch.object(app.st, "warning") as warn:
            app._mostra_non_abbinati_fonte(self.stato(), "Top Mix")
        self.assertEqual(0, warn.call_count)

    def test_messaggi_per_stato_usati_da_tab2_e_analisi_rapida(self):
        for stato, parola in ((mo.STATO_ASSENTE, "non esiste"),
                              (mo.STATO_NON_LEGGIBILE, "leggibile"),
                              (mo.STATO_SENZA_LEGHE, "leghe")):
            with mock.patch.object(app.st, "warning") as warn:
                self.assertTrue(app._avviso_stato_quote({"stato": stato}, "Top Mix"))
            self.assertIn(parola, str(warn.call_args), stato)
        with mock.patch.object(app.st, "warning") as warn:
            self.assertFalse(app._avviso_stato_quote({"stato": mo.STATO_OK}, "Top Mix"))
        self.assertEqual(0, warn.call_count, "con stato ok non c'e' niente da avvisare")


# ------------------------------------------------- 5. statistiche per famiglia
class TestStatistichePerFamiglia(unittest.TestCase):
    RIGA = {"league": "Serie A", "giornata": 5, "home": "Inter", "away": "Roma",
            "match_id": 4242, "utcDate": "2026-10-03T18:45:00Z",
            "market": "Vittoria Inter", "mercato_standard": "1",
            "prob": 0.6123, "prob_val": 61.2, "poisson": 58.0, "elo": 62.3,
            "elo_disponibile": True, "rank": 3}

    def setUp(self):
        mkt = dict(self.RIGA, prob=0.6006, prob_val=60.06, quota=1.62,
                   fonte=mo.FONTE_PINNACLE, n_libri=1, prob_modello_val=61.2,
                   accordo=True, quote_live_istante=FRESCO, rank=1)
        a2, k2 = app.argomenti_registro_top_mix(self.RIGA)
        k2 = dict(k2, origin=R.ORIGIN_TOP_MIX,
                  selector_version=R.SELECTOR_VERSION_MODELLO_1X2)
        self.v2 = app.build_prediction_entry(*a2, **k2, snapshot_sha="s",
                                             salvato_il="01/10/2026 10:00")
        a3, k3 = app.argomenti_registro_top_mix_mercato(mkt)
        self.v3 = app.build_prediction_entry(*a3, **k3, snapshot_sha="s",
                                             salvato_il="09/10/2026 08:20")
        for e in (self.v2, self.v3):
            e["esito"] = "✅"
            e["risultato_reale"] = "2-0"
        self.entrate, self.azioni = R.upsert_prediction_entries([self.v2], [self.v3])

    def test_la_stessa_partita_registrata_da_v2_e_v3_dà_due_statistiche(self):
        self.assertEqual({"aggiunta": 1}, dict(self.azioni))
        self.assertEqual(2, len(self.entrate))
        modello = R.compute_stats(self.entrate, famiglia=R.FAMIGLIA_SELETTORE_MODELLO)
        mercato = R.compute_stats(self.entrate, famiglia=R.FAMIGLIA_SELETTORE_MERCATO)
        self.assertEqual(1, modello["total"])
        self.assertEqual(1, mercato["total"])
        self.assertEqual(1, R.compute_calibration_stats(
            self.entrate, famiglia=R.FAMIGLIA_SELETTORE_MODELLO)["total"])
        self.assertEqual(1, R.compute_calibration_stats(
            self.entrate, famiglia=R.FAMIGLIA_SELETTORE_MERCATO)["total"])

    def test_senza_filtro_il_totale_mescola_ancora(self):
        """Il default resta quello di prima: chi vuole il misto lo chiede."""
        self.assertEqual(2, R.compute_stats(self.entrate)["total"])
        self.assertIsNone(R.compute_stats(self.entrate)["famiglia"])

    def test_brier_diverso_per_famiglia(self):
        b_modello = R.compute_calibration_stats(
            self.entrate, famiglia=R.FAMIGLIA_SELETTORE_MODELLO)["brier"]
        b_mercato = R.compute_calibration_stats(
            self.entrate, famiglia=R.FAMIGLIA_SELETTORE_MERCATO)["brier"]
        b_misto = R.compute_calibration_stats(self.entrate)["brier"]
        self.assertAlmostEqual((1 - 0.612) ** 2, b_modello, places=6)
        self.assertAlmostEqual((1 - 0.6006) ** 2, b_mercato, places=6)
        self.assertNotAlmostEqual(b_modello, b_mercato, places=6)
        # il misto sta fra i due: e' il numero che non descrive nessuno dei due
        self.assertTrue(min(b_modello, b_mercato) < b_misto < max(b_modello, b_mercato))

    def test_famiglia_sconosciuta_dà_zero_righe(self):
        self.assertEqual(0, R.compute_stats(self.entrate, famiglia="altro")["total"])

    def test_le_righe_ombra_non_entrano_in_nessuna_famiglia(self):
        """L'ombra ha la sua famiglia ma NON entra nelle statistiche visibili."""
        ombra = app.build_ombra_modello_entry(self.RIGA, snapshot_sha="s",
                                              salvato_il="09/10/2026 08:20")
        self.assertTrue(R.is_ombra(ombra))
        self.assertEqual(R.FAMIGLIA_SELETTORE_MODELLO, R.famiglia_selettore(ombra))
        con_ombra = self.entrate + [ombra]
        attesi = {None: 2, R.FAMIGLIA_SELETTORE_MODELLO: 1, R.FAMIGLIA_SELETTORE_MERCATO: 1}
        for fam, atteso in attesi.items():
            self.assertEqual(atteso, R.compute_stats(con_ombra, famiglia=fam)["total"],
                             f"famiglia {fam}: l'ombra non entra nelle statistiche visibili")

    def test_il_confine_delle_famiglie_e_dichiarato(self):
        self.assertEqual("09/10/2026", app.CONFINE_FAMIGLIA_MERCATO)
        self.assertEqual({"🧠", "🌟"}, set(app.FAMIGLIA_ICONA.values()))
        src = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
        i = src.index("with tab5:")
        tab5 = src[i:src.index("with tab6:") if "with tab6:" in src[i:] else len(src)]
        self.assertIn("FAMIGLIA_SELETTORE_MODELLO", tab5)
        self.assertIn("FAMIGLIA_SELETTORE_MERCATO", tab5)
        self.assertIn("CONFINE_FAMIGLIA_MERCATO", tab5)
        self.assertNotIn("Totale registro (audit complessivo)", tab5,
                         "nessun totale unico che mescoli le due famiglie")


# ------------------------------------------- 6. Analisi Rapida con indice vuoto
class TestAnalisiRapidaConIndiceVuoto(FileTemporaneo, RipristinaLogging, unittest.TestCase):
    """Il caso che prima taceva: file valido, zero eventi."""

    MATCH = {"id": 1, "matchday": 8, "utcDate": "2026-10-10T13:00:00Z",
             "homeTeam": {"shortName": "Inter"}, "awayTeam": {"shortName": "Roma"}}
    STATS = {"Inter": {"att": 1.25, "def": 0.85}, "Roma": {"att": 1.05, "def": 0.95}}

    def _gira(self, stato):
        salvate = []
        with mock.patch.object(app, "carica_indice_quote_live", return_value=stato), \
             mock.patch.object(app, "predict_elo_probs",
                               return_value={"1": 0.6, "X": 0.2, "2": 0.2}), \
             mock.patch.object(app, "predict_elo_probs_legacy",
                               return_value={"1": 0.6, "X": 0.2, "2": 0.2}), \
             mock.patch.object(app, "save_prediction_entry",
                               side_effect=lambda *a, **k: salvate.append((a, k)) or {"azione": "aggiunta"}), \
             mock.patch.object(app, "_roster_stagione", return_value={"Inter", "Roma"}), \
             mock.patch.object(app.st, "warning") as warn, \
             mock.patch.object(app.st, "info"), \
             mock.patch.object(app.st, "error") as err:
            app.analisi_rapida_giornata([self.MATCH], self.STATS, 1.5, 1.2,
                                        "Serie A", {}, 8)
        return salvate, warn, err

    def test_indice_vuoto_segnala_la_partita(self):
        stato = {"stato": mo.STATO_OK, "indice": {}, "non_abbinati": [],
                 "eta_ore": 2.0, "obsoleto": False, "dettaglio": None}
        _salvate, warn, _err = self._gira(stato)
        testi = " ".join(str(c) for c in warn.call_args_list)
        self.assertIn("SENZA quote di mercato", testi)
        self.assertIn("Inter vs Roma", testi)

    def test_file_assente_dice_lo_stato_senza_elencare_partite(self):
        stato = {"stato": mo.STATO_ASSENTE, "indice": None, "non_abbinati": [],
                 "eta_ore": None, "obsoleto": False,
                 "dettaglio": app._DETTAGLIO_STATO_QUOTE[mo.STATO_ASSENTE]}
        _salvate, warn, _err = self._gira(stato)
        testi = " ".join(str(c) for c in warn.call_args_list)
        self.assertIn("non esiste", testi)
        self.assertNotIn("SENZA quote di mercato", testi,
                         "con il file assente l'elenco per partita sarebbe solo rumore")

    def test_quote_obsolete_danno_st_error(self):
        stato = {"stato": mo.STATO_OK, "indice": {}, "non_abbinati": [],
                 "eta_ore": 37.0, "obsoleto": True, "dettaglio": None,
                 "generato_il": VECCHIO}
        _salvate, _warn, err = self._gira(stato)
        self.assertEqual(1, err.call_count)
        self.assertIn("OBSOLETE", str(err.call_args))
        self.assertIn("37.0", str(err.call_args))


if __name__ == "__main__":
    unittest.main(verbosity=2)
