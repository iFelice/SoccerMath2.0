"""Copertura dell'abbinamento dei nomi fra la fonte quote e il calendario corrente.

COSA VERIFICA (punto 1 della commessa "quote live nel Top Mix")
---------------------------------------------------------------
La PR #50 ha misurato l'abbinamento dei nomi di The Odds API sui nomi canonici
del progetto: 81,2% con ``clean_name`` e 87,5% col resolver di produzione, su 48
partite della prossima giornata (``audit/results/live_odds_feasibility.md`` §3).
I 6 nomi mancanti sono stati aggiunti a ``team_aliases.py``. Questo test
verifica che ora la copertura sia COMPLETA, e lo fa su TUTTE le partite degli
snapshot committati (96 eventi, non solo la prossima giornata) e sul file
``live_odds.json`` quando c'e'.

REGOLE
------
* nessun fuzzy matching: un nome fuori tabella resta fuori tabella;
* le partite non abbinate vengono LOGGATE per nome (``logging.warning``) e il
  test le elenca nel messaggio di fallimento: nessun fallback silenzioso.

Il test NON usa la rete: legge gli snapshot in ``audit/data/live_odds_probe/``
(risposte reali dell'API, committate dalla PR #50) e, se presente,
``SoccerMath/database/live_odds.json``.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(REPO_ROOT, "audit")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

logging.getLogger("streamlit").setLevel(logging.ERROR)

import market_odds as mo  # noqa: E402
from config import CURRENT_SEASON_START_YEAR, LEAGUES_CONFIG  # noqa: E402
from season_rosters import load_season_rosters  # noqa: E402
from team_aliases import TEAM_NAME_MAP, clean_name  # noqa: E402
from team_names import resolve_team_name  # noqa: E402

PROBE_DIR = os.path.join(REPO_ROOT, "audit", "data", "live_odds_probe")
LIVE_ODDS_PATH = os.path.join(HERE, "database", "live_odds.json")

#: I 6 nomi che la PR #50 ha dichiarato mancanti (referto §5, "Precondizione
#: obbligatoria prima di andare in produzione").
ALIAS_ATTESI = {
    "Atlético Madrid": "Ath Madrid",
    "CA Osasuna": "Osasuna",
    "Elche CF": "Elche",
    "Real Racing Club de Santander": "Santander",
    "Borussia Monchengladbach": "M'gladbach",
    "FSV Mainz 05": "Mainz",
}

#: Prefisso del CSV della stagione corrente per lega (chiave di LEAGUES_CONFIG).
LIVE_CSV = {lega: info["live_csv"] for lega, info in LEAGUES_CONFIG.items()}


def nomi_canonici_stagione_corrente():
    """Nomi canonici del calendario corrente: roster + CSV ``_Live``."""
    roster = load_season_rosters()
    canonici = {}
    for lega, per_stagione in roster.items():
        chiave = str(CURRENT_SEASON_START_YEAR)
        nomi = set(per_stagione.get(chiave) or per_stagione.get(int(chiave)) or [])
        canonici[lega] = {clean_name(n) for n in nomi if n}
    # il CSV della stagione corrente puo' contenere squadre che il roster non ha
    # ancora (calendario pubblicato prima del roster): l'unione e' il calendario.
    for lega, path in LIVE_CSV.items():
        if not os.path.exists(path):
            continue
        import csv
        with open(path, encoding="utf-8", newline="") as fh:
            for riga in csv.DictReader(fh):
                for col in ("HomeTeam", "AwayTeam"):
                    v = (riga.get(col) or "").strip()
                    if v:
                        canonici.setdefault(lega, set()).add(clean_name(v))
    return canonici


def eventi_snapshot():
    """Tutti gli eventi degli snapshot committati, con la lega di provenienza."""
    out = []
    for nome in sorted(os.listdir(PROBE_DIR)):
        if not (nome.startswith("odds_api_soccer") and nome.endswith(".json")):
            continue
        with open(os.path.join(PROBE_DIR, nome), encoding="utf-8") as fh:
            snap = json.load(fh)
        lega = snap.get("lega_progetto") or nome
        for e in snap.get("events") or []:
            out.append({**e, "lega": lega, "origine": nome})
    return out


def eventi_live_odds():
    """Eventi di ``live_odds.json`` (se il workflow lo ha gia' scritto)."""
    if not os.path.exists(LIVE_ODDS_PATH):
        return []
    payload = mo.carica_quote_live(LIVE_ODDS_PATH)
    return mo.eventi_quote(payload)


class TestAliasAggiunti(unittest.TestCase):
    """I 6 alias della PR #50 ci sono, sono dichiarati e puntano a nomi canonici."""

    def test_i_sei_alias_sono_in_tabella(self):
        for grezzo, canonico in ALIAS_ATTESI.items():
            self.assertIn(grezzo, TEAM_NAME_MAP,
                          f"alias mancante in team_aliases.TEAM_NAME_MAP: {grezzo!r}")
            self.assertEqual(TEAM_NAME_MAP[grezzo], canonico)

    def test_il_resolver_riconosce_i_sei_nomi(self):
        for grezzo, canonico in ALIAS_ATTESI.items():
            res = resolve_team_name(grezzo)
            self.assertTrue(res.mapped, f"{grezzo!r} non riconosciuto dal resolver")
            self.assertEqual(canonico, res.canonical, grezzo)

    def test_clean_name_da_solo_li_risolve(self):
        """``clean_name`` basta: l'alias e' applicato PRIMA delle sostituzioni.

        Caso noto (PR #50 §3): ``FSV Mainz 05`` diventava ``FMainz 05`` perche'
        la lista delle sostituzioni contiene ``"SV "``. L'alias vince perche'
        ``clean_name`` consulta ``TEAM_NAME_MAP`` per prima cosa.
        """
        for grezzo, canonico in ALIAS_ATTESI.items():
            self.assertEqual(canonico, clean_name(grezzo), grezzo)

    def test_i_canonici_degli_alias_sono_nel_calendario_corrente(self):
        canonici = nomi_canonici_stagione_corrente()
        tutti = set().union(*canonici.values())
        for grezzo, canonico in ALIAS_ATTESI.items():
            self.assertIn(clean_name(canonico), tutti,
                          f"{canonico!r} (da {grezzo!r}) non e' un nome del calendario corrente")

    def test_clean_name_resta_idempotente_sui_nuovi_alias(self):
        for grezzo, canonico in ALIAS_ATTESI.items():
            self.assertEqual(clean_name(grezzo), clean_name(clean_name(grezzo)), grezzo)


class TestCoperturaCalendarioCorrente(unittest.TestCase):
    """TUTTE le partite della fonte quote si abbinano al calendario corrente."""

    @classmethod
    def setUpClass(cls):
        cls.canonici = nomi_canonici_stagione_corrente()
        cls.tutti_canonici = set().union(*cls.canonici.values())
        cls.eventi = eventi_snapshot()

    def test_gli_snapshot_ci_sono_e_non_sono_vuoti(self):
        self.assertGreaterEqual(len(self.eventi), 90,
                                "snapshot della fonte quote mancanti o vuoti")
        leghe = {e["lega"] for e in self.eventi}
        self.assertEqual(set(LEAGUES_CONFIG), leghe)

    def test_ogni_nome_della_fonte_e_riconosciuto(self):
        """Copertura completa sui NOMI: nessun nome fuori tabella."""
        sconosciuti = []
        for e in self.eventi:
            for ruolo in ("home_team", "away_team"):
                res = resolve_team_name(e.get(ruolo))
                if not res.mapped:
                    sconosciuti.append(f"{e['lega']}: {e.get(ruolo)!r} -> {res.canonical!r}")
        self.assertEqual([], sorted(set(sconosciuti)),
                         "nomi della fonte quote NON riconosciuti (nessun fallback: "
                         "vanno dichiarati in team_aliases.py):\n  " + "\n  ".join(sorted(set(sconosciuti))))

    def test_ogni_partita_e_abbinata_al_calendario_corrente(self):
        """Copertura completa sulle PARTITE: entrambi i nomi nel calendario."""
        non_abbinate = []
        for e in self.eventi:
            h = resolve_team_name(e.get("home_team"))
            a = resolve_team_name(e.get("away_team"))
            if h.canonical in self.tutti_canonici and a.canonical in self.tutti_canonici:
                continue
            non_abbinate.append(
                f"{e['lega']}: {e.get('home_team')!r} -> {h.canonical!r} | "
                f"{e.get('away_team')!r} -> {a.canonical!r}")
        self.assertEqual([], non_abbinate,
                         "partite della fonte quote NON abbinate al calendario corrente:\n  "
                         + "\n  ".join(non_abbinate))

    def test_copertura_e_il_100_percento(self):
        """Il numero dichiarato nel riepilogo della PR: 96/96, non 'quasi'."""
        abbinate = 0
        for e in self.eventi:
            h = resolve_team_name(e.get("home_team")).canonical
            a = resolve_team_name(e.get("away_team")).canonical
            if h in self.tutti_canonici and a in self.tutti_canonici:
                abbinate += 1
        self.assertEqual(len(self.eventi), abbinate,
                         f"{abbinate}/{len(self.eventi)} partite abbinate: copertura non completa")

    def test_indice_partite_non_lascia_fuori_nessuna_partita(self):
        """``market_odds.indice_partite`` indicizza tutti gli eventi."""
        payload = {"leghe": {}}
        per_lega = {}
        for e in self.eventi:
            per_lega.setdefault(e["lega"], []).append(e)
        for lega, lista in per_lega.items():
            payload["leghe"][lega] = {"eventi": lista}
        dati = mo.indice_partite(payload)
        self.assertEqual(dati["n_eventi"], len(self.eventi))
        self.assertEqual(dati["n_indicizzati"], len(self.eventi))
        self.assertEqual([], dati["non_abbinati"])




class RipristinaLogging:
    """Riabilita i log per la durata del test.

    Sei file di test dell'audit chiamano ``logging.disable(CRITICAL)`` a livello
    di modulo e non lo ripristinano: pytest importa tutti i file prima di
    eseguire qualunque test, quindi nella suite completa lo stato globale dei log
    dipende dall'ordine dei file. I WARNING qui sono parte del contratto in prova
    (un nome non abbinato DEVE essere loggato), quindi il setUp li riabilita e il
    tearDown rimette ESATTAMENTE lo stato trovato. E' la stessa guardia gia' usata
    in ``test_fallback_nomi.py`` e ``test_topmix_ombra_totali.py``.
    """

    def setUp(self):
        self._disable_precedente = logging.root.manager.disable
        logging.disable(logging.NOTSET)
        if hasattr(super(), "setUp"):
            super().setUp()

    def tearDown(self):
        logging.disable(self._disable_precedente)


class TestNessunFallbackSilenzioso(RipristinaLogging, unittest.TestCase):
    """Un nome non abbinato viene LOGGATO per nome, non ignorato."""

    def test_un_nome_sconosciuto_produce_un_warning_col_nome(self):
        payload = {"leghe": {"Serie A": {"eventi": [
            {"id": "x1", "commence_time": "2026-10-10T13:00:00Z",
             "home_team": "Inter", "away_team": "Squadra Mai Vista FC"},
        ]}}}
        with self.assertLogs("market_odds", level="WARNING") as catturati:
            dati = mo.indice_partite(payload)
        testo = "\n".join(catturati.output)
        self.assertIn("Squadra Mai Vista FC", testo)
        self.assertEqual(1, len(dati["non_abbinati"]))
        self.assertEqual("Squadra Mai Vista FC", dati["non_abbinati"][0]["away_raw"])
        self.assertFalse(dati["non_abbinati"][0]["away_riconosciuto"])
        # la partita NON entra nell'indice: nessuna quota inventata
        self.assertEqual(0, dati["n_indicizzati"])

    def test_una_partita_senza_coppia_nell_indice_non_da_quote(self):
        dati = mo.indice_partite({"leghe": {"Serie A": {"eventi": [
            {"id": "x1", "commence_time": "2026-10-10T13:00:00Z",
             "home_team": "Inter", "away_team": "Roma"},
        ]}}})
        self.assertIsNone(mo.cerca_quote(dati["indice"], "Milan", "Napoli"))

    def test_due_eventi_stessa_coppia_prende_il_piu_vicino(self):
        dati = mo.indice_partite({"leghe": {"Serie A": {"eventi": [
            {"id": "andata", "commence_time": "2026-10-10T13:00:00Z",
             "home_team": "Inter", "away_team": "Roma"},
            {"id": "ritorno", "commence_time": "2027-03-10T19:45:00Z",
             "home_team": "Inter", "away_team": "Roma"},
        ]}}})
        self.assertEqual("ritorno", mo.cerca_quote(
            dati["indice"], "Inter", "Roma", "2027-03-10T19:45:00Z")["id"])
        self.assertEqual("andata", mo.cerca_quote(
            dati["indice"], "Inter", "Roma", "2026-10-10T13:00:00Z")["id"])


class TestCoperturaSuFileScritto(unittest.TestCase):
    """La stessa regola del file vivo, su un file SCRITTO dal test.

    Il controllo su ``database/live_odds.json`` qui sotto salta finché il
    workflow non scrive: lasciarlo come unico presidio significherebbe non
    provare niente in CI. Qui il file lo scrive il test in una cartella
    temporanea, quindi la copertura e' verificata a ogni run e non dipende da
    quando gira il workflow.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, mo.LIVE_ODDS_FILE)

    def _scrivi(self, eventi, lega="Serie A"):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"schema": mo.SCHEMA_LIVE_ODDS,
                       "generato_il": "2026-10-09T08:17:00Z",
                       "leghe": {lega: {"eventi": eventi}}}, fh)

    def _evento(self, home, away):
        return {"id": f"{home}-{away}", "commence_time": "2026-10-10T13:00:00Z",
                "home_team": home, "away_team": away,
                "libri": [{"key": "pinnacle",
                           "h2h": {"home": 1.62, "draw": 4.1, "away": 6.0}}]}

    def test_file_valido_copertura_completa(self):
        # nomi della fonte nella forma GREZZA (alias, non canonici): l'abbinamento
        # deve passare dalla tabella, non dall'identita' del testo
        self._scrivi([self._evento("Inter Milan", "AS Roma"),
                      self._evento("Atalanta BC", "AC Milan")])
        payload = mo.carica_quote_live(self.path)
        self.assertIsNotNone(payload)
        dati = mo.indice_partite(payload)
        self.assertEqual([], dati["non_abbinati"])
        self.assertEqual(dati["n_eventi"], dati["n_indicizzati"])
        self.assertEqual(2, dati["n_indicizzati"])

    def test_nome_fuori_tabella_esce_in_non_abbinati(self):
        self._scrivi([self._evento("Inter Milan", "Squadra Mai Vista FC")])
        dati = mo.indice_partite(mo.carica_quote_live(self.path))
        self.assertEqual(1, len(dati["non_abbinati"]))
        na = dati["non_abbinati"][0]
        self.assertEqual("Squadra Mai Vista FC", na["away_raw"])
        self.assertEqual("Serie A", na["lega"])
        self.assertFalse(na["away_riconosciuto"])
        self.assertTrue(na["home_riconosciuto"])
        self.assertEqual(0, dati["n_indicizzati"],
                         "la partita non entra nell'indice: nessuna quota inventata")

    def test_file_senza_leghe_e_ignorato(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"schema": mo.SCHEMA_LIVE_ODDS}, fh)
        self.assertIsNone(mo.carica_quote_live(self.path))

    def test_file_senza_eventi_dà_indice_vuoto(self):
        self._scrivi([])
        dati = mo.indice_partite(mo.carica_quote_live(self.path))
        self.assertEqual({}, dati["indice"])
        self.assertEqual(0, dati["n_eventi"])
        self.assertEqual([], dati["non_abbinati"])

    def test_legge_anche_il_percorso_di_produzione_se_puntato(self):
        """``percorso_quote_live`` rispetta la cartella passata (nessun path assoluto)."""
        self.assertEqual(self.path,
                         mo.percorso_quote_live(database_dir=self.tmp.name))


@unittest.skipUnless(os.path.exists(LIVE_ODDS_PATH),
                     "live_odds.json non ancora scritto dal workflow")
class TestCoperturaFileLive(unittest.TestCase):
    """Se il workflow ha gia' scritto ``live_odds.json``, vale la stessa regola."""

    def test_copertura_completa_anche_sul_file_vivo(self):
        payload = mo.carica_quote_live(LIVE_ODDS_PATH)
        self.assertIsNotNone(payload)
        dati = mo.indice_partite(payload)
        self.assertEqual([], dati["non_abbinati"],
                         "nomi non abbinati in live_odds.json: "
                         + "; ".join(f"{n['home_raw']} / {n['away_raw']}"
                                     for n in dati["non_abbinati"]))
        self.assertEqual(dati["n_eventi"], dati["n_indicizzati"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
