"""
test_season_rosters.py - R(lega, stagione) dal file roster fin dal pre-stagione.

Il seed Elo degli ingressi in lega legge la composizione del campionato dal
file versionato ``database/season_rosters.json`` (salvato da ``update_db.py``
dal calendario API completo, prima dello scarto delle non giocate) invece che
dalle sole partite giocate. Precedenza, stagione per stagione:

* voce nel file -> il file (input offline e deterministico, nessuna rete);
* senza voce, stagione conclusa -> partite giocate, come prima;
* senza voce, stagione corrente -> ``EloSeedError``, come oggi (mai 1500
  silenzioso).

Casi coperti:

* il file reale copre 2022-2026 per le 5 leghe con le taglie attese e nomi
  canonici ordinati;
* per ogni stagione in cui esistono entrambe le fonti (file + giocate) le due
  coincidono, e il motore reale usa il file;
* le concluse senza voce ricadono sulle giocate; la corrente senza voce solleva;
* simulazione di inizio stagione 2026/27 per lega (DB troncato al giorno prima
  della prima giornata + file): seed di ogni entrante uguale al backtest
  troncato con roster esplicito, nessun ``EloSeedError``, ``predict_elo_probs``
  risponde per tutte le partite della prima giornata;
* ``update_db`` salva il roster anche dalle partite future ed esclude le
  future dai CSV come oggi (nessuna rete nei test);
* validazione taglie + tolleranza roster (15 luglio) e scadenza;
* ``app.py`` passa la stagione esplicita a ``predict_elo_probs``.

Esecuzione:  python SoccerMath/test_season_rosters.py
             python -m pytest SoccerMath/test_season_rosters.py -v
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import config as PROD_CONFIG  # noqa: E402
import season_calendar as SC  # noqa: E402
import season_rosters as SR  # noqa: E402
from models.elo_engine import (  # noqa: E402
    EloEngine,
    EloSeedError,
    predict_elo_probs,
    season_rosters_from_matches,
)
import models.elo_engine as ELO_MOD  # noqa: E402

LEGHE = ("Serie A", "Premier League", "La Liga", "Bundesliga", "Ligue 1")
TAGLIE_ATTESE = {"Serie A": 20, "Premier League": 20, "La Liga": 20,
                 "Bundesliga": 18, "Ligue 1": 18}
# Prima giornata 2026/27 dai CSV (min Date di *_Live.csv): la simulazione
# tronca al giorno prima di ciascuna.
PRIMA_GIORNATA_2026 = {
    "Serie A": date(2026, 8, 22),
    "Premier League": date(2026, 8, 21),
    "La Liga": date(2026, 8, 15),
    "Bundesliga": date(2026, 8, 28),
    "Ligue 1": date(2026, 8, 21),
}


class _DBTemp:
    """Copia del database reale in una cartella temporanea, config ripuntato.

    ``truncated_before`` (date): se dato, le righe con Date >= quella data
    vengono rimosse da tutti i CSV (simulazione pre-stagione). ``con_roster``
    decide se copiare anche ``season_rosters.json``.
    """

    def __init__(self, truncated_before=None, con_roster=True):
        self.truncated_before = truncated_before
        self.con_roster = con_roster
        self.tmp = None

    def __enter__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="roster_test_"))
        src = Path(PROD_CONFIG.DATABASE_DIR)
        cutoff = (pd.Timestamp(self.truncated_before)
                  if self.truncated_before is not None else None)
        for f in src.glob("*.csv"):
            df = pd.read_csv(f, on_bad_lines="warn", low_memory=False)
            if cutoff is not None and "Date" in df.columns:
                d = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
                df = df[d.notna() & (d < cutoff)]
            df.to_csv(self.tmp / f.name, index=False)
        if self.con_roster and (src / SR.ROSTER_FILENAME).exists():
            shutil.copy(src / SR.ROSTER_FILENAME, self.tmp / SR.ROSTER_FILENAME)
        self.old_dir = PROD_CONFIG.DATABASE_DIR
        self.old_cfg = {k: dict(v) for k, v in PROD_CONFIG.LEAGUES_CONFIG.items()}
        PROD_CONFIG.DATABASE_DIR = self.tmp
        for k, v in PROD_CONFIG.LEAGUES_CONFIG.items():
            for chiave in ("base_csv", "live_csv", "xg_json"):
                if v.get(chiave):
                    v[chiave] = str(self.tmp / Path(v[chiave]).name)
        for lega in LEGHE:
            ELO_MOD._ELO_ENGINES_CACHE.pop(lega, None)
            ELO_MOD._ELO_ENGINES_STAMP.pop(lega, None)
        return self

    def __exit__(self, *exc):
        PROD_CONFIG.DATABASE_DIR = self.old_dir
        for k, v in self.old_cfg.items():
            PROD_CONFIG.LEAGUES_CONFIG[k] = v
        for lega in LEGHE:
            ELO_MOD._ELO_ENGINES_CACHE.pop(lega, None)
            ELO_MOD._ELO_ENGINES_STAMP.pop(lega, None)
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False


def _motore(lega):
    for l in LEGHE:
        ELO_MOD._ELO_ENGINES_CACHE.pop(l, None)
        ELO_MOD._ELO_ENGINES_STAMP.pop(l, None)
    eng = EloEngine(lega)
    eng.compute_ratings()
    return eng


class TestFileReale(unittest.TestCase):
    def test_copertura_e_taglie(self):
        tutto = SR.load_season_rosters()
        self.assertEqual(sorted(tutto), sorted(LEGHE))
        for lega in LEGHE:
            stagioni = tutto[lega]
            self.assertEqual(sorted(stagioni), [2022, 2023, 2024, 2025, 2026], lega)
            for s, squadre in stagioni.items():
                attese = TAGLIE_ATTESE[lega]
                # La Ligue 1 era a 20 nel 2022/23, a 18 dal 2023/24.
                if lega == "Ligue 1" and s == 2022:
                    attese = 20
                self.assertEqual(len(set(squadre)), attese, f"{lega} {s}")
                self.assertEqual(sorted(squadre), list(squadre), f"{lega} {s}: ordinate")
                for t in squadre:
                    self.assertEqual(PROD_CONFIG.clean_name(t), t, f"{lega} {s}: {t!r}")

    def test_file_e_partite_giocate_coincidono_su_tutte_le_stagioni(self):
        """Per ogni stagione con entrambe le fonti, file == giocate."""
        tutto = SR.load_season_rosters()
        for lega in LEGHE:
            eng = _motore(lega)
            giocate = season_rosters_from_matches(eng.matches_df)
            for stagione in sorted(set(tutto[lega]) & set(giocate)):
                self.assertEqual(set(tutto[lega][stagione]), set(giocate[stagione]),
                                 f"{lega} {stagione}: file != giocate")

    def test_il_motore_reale_usa_il_file(self):
        tutto = SR.load_season_rosters()
        for lega in LEGHE:
            eng = _motore(lega)
            for stagione, squadre in tutto[lega].items():
                self.assertIn(stagione, eng.season_rosters, f"{lega} {stagione}")
                self.assertEqual(set(eng.season_rosters[stagione]), set(squadre),
                                 f"{lega} {stagione}")

    def test_nessuna_chiamata_di_rete_nel_loader(self):
        for nome in ("load_season_rosters", "load_league_rosters", "save_league_roster",
                     "validate_current_rosters"):
            nomi = set(getattr(SR, nome).__code__.co_names)
            for vietato in ("requests", "urlopen", "Urlopen", "Session", "socket", "urllib"):
                self.assertNotIn(vietato, nomi, f"{nome}: {sorted(nomi)}")
        sorgente = Path(SR.__file__).read_text(encoding="utf-8")
        for vietato in ("import requests", "import socket", "import urllib", "urlopen("):
            self.assertNotIn(vietato, sorgente)


class TestPrecedenzaFileGiocate(unittest.TestCase):
    def test_concluse_senza_voce_ricadono_sulle_giocate(self):
        """File con una sola stagione: le altre concluse vengono dai CSV."""
        with _DBTemp() as db:
            parziale = {"Serie A": {"2026": SR.load_season_rosters()["Serie A"][2026]}}
            (db.tmp / SR.ROSTER_FILENAME).write_text(json.dumps(parziale), encoding="utf-8")
            eng = _motore("Serie A")
            giocate = season_rosters_from_matches(eng.matches_df)
            for stagione in (2022, 2023, 2024, 2025):
                self.assertEqual(set(eng.season_rosters[stagione]), set(giocate[stagione]),
                                 stagione)
            self.assertEqual(set(eng.season_rosters[2026]), set(parziale["Serie A"]["2026"]))

    def test_corrente_senza_voce_solleva_come_oggi(self):
        """Pre-stagione senza roster salvato: EloSeedError, mai 1500 silente.

        DB troncato a prima del via (nessuna partita 2026 da processare) e
        file senza la voce 2026: il motore gira sulle concluse, ma il seed
        2026 solleva come oggi quando il roster manca.
        """
        corrente = PROD_CONFIG.get_current_season_start_year()
        with _DBTemp(truncated_before=date(2026, 8, 22)) as db:
            tutto = SR.load_season_rosters()
            for lega in list(tutto):
                tutto[lega].pop(corrente, None)
            (db.tmp / SR.ROSTER_FILENAME).write_text(json.dumps(tutto), encoding="utf-8")
            eng = _motore("Serie A")
            self.assertNotIn(corrente, eng.season_rosters)
            with self.assertRaises(EloSeedError):
                eng.promoted_seed(corrente)

    def test_roster_esplicito_vince_ancora_sul_file(self):
        """Il costruttore esplicito (backtest) non e' toccato dal file."""
        with _DBTemp() as db:
            tutto = SR.load_season_rosters()
            # Il file dice il falso (2026 copiata dalla 2025): l'esplicito
            # deve vincere comunque.
            tutto["Serie A"][2026] = list(tutto["Serie A"][2025])
            (db.tmp / SR.ROSTER_FILENAME).write_text(json.dumps(tutto), encoding="utf-8")
            reale = json.loads((Path(__file__).parent / "database"
                                / SR.ROSTER_FILENAME).read_text(encoding="utf-8"))
            roster = {int(s): set(v) for s, v in reale["Serie A"].items()}
            eng = EloEngine("Serie A", season_rosters={k: set(v) for k, v in roster.items()})
            eng.compute_ratings()
            self.assertEqual({k: set(v) for k, v in eng.season_rosters.items()}, roster)

    def test_file_malformato_vale_come_file_assente(self):
        """JSON corrotto: come se il file non ci fosse (errore esplicito)."""
        with _DBTemp(truncated_before=date(2026, 8, 22)) as db:
            (db.tmp / SR.ROSTER_FILENAME).write_text("non json {{{", encoding="utf-8")
            eng = _motore("Serie A")
            giocate = season_rosters_from_matches(eng.matches_df)
            corrente = PROD_CONFIG.get_current_season_start_year()
            for stagione in giocate:
                if stagione != corrente:
                    self.assertEqual(set(eng.season_rosters[stagione]), set(giocate[stagione]))
            self.assertNotIn(corrente, eng.season_rosters)
            with self.assertRaises(EloSeedError):
                eng.promoted_seed(corrente)


class TestSimulazioneInizioStagione2026(unittest.TestCase):
    """DB troncato al giorno prima della prima giornata + file roster.

    Il \"backtest\" di riferimento e' lo stesso DB troncato con il roster
    INTEGRALE passato esplicitamente (il meccanismo dei backtest su CSV
    troncati, vedi ``make_elo_parity_fixture._roster_completo``): a parita' di
    partite viste, file ed esplicito devono dare gli stessi seed bit-exact.
    """

    def _confronto_lega(self, lega):
        prima = PRIMA_GIORNATA_2026[lega]
        giornata1 = self._giornata1(lega)  # dal DB reale, prima di troncare
        self.assertTrue(giornata1, lega)
        with _DBTemp(truncated_before=prima, con_roster=True):
            # Il troncamento ha tolto davvero tutta la 2026/27 giocata.
            eng_file = _motore(lega)
            self.assertNotIn(prima, set(pd.Timestamp(d).date()
                                        for d in eng_file.matches_df["Date_Parsed"]),
                             f"{lega}: troncamento fallito")
            self.assertIn(2026, eng_file.season_rosters, f"{lega}: roster 2026 dal file")
            # Backtest: stesso troncamento, roster integrale esplicito.
            tutto = SR.load_season_rosters()
            roster_completo = {s: set(v) for s, v in tutto[lega].items()}
            eng_back = EloEngine(lega, season_rosters={k: set(v) for k, v in roster_completo.items()})
            eng_back.compute_ratings()
            # Stesse partite viste, stessi roster, stessi rating finali.
            self.assertEqual(len(eng_file.matches_df), len(eng_back.matches_df))
            self.assertEqual({k: set(v) for k, v in eng_file.season_rosters.items()},
                             {k: set(v) for k, v in eng_back.season_rosters.items()})
            for squadra, valore in eng_file.ratings.items():
                self.assertEqual(repr(valore), repr(eng_back.ratings[squadra]), squadra)
            # Seed di ogni entrante 2026: file == backtest, nessun errore.
            roster25 = set(tutto[lega][2025])
            entranti = sorted(set(tutto[lega][2026]) - roster25)
            self.assertTrue(entranti, lega)
            seed_file, seed_back = {}, {}
            for squadra in entranti:
                seed_file[squadra] = repr(eng_file.promoted_seed(2026))
                seed_back[squadra] = repr(eng_back.promoted_seed(2026))
                self.assertEqual(seed_file[squadra], seed_back[squadra], squadra)
            # predict_elo_probs per tutte le partite della prima giornata.
            import time
            ELO_MOD._ELO_ENGINES_CACHE[lega] = eng_file
            ELO_MOD._ELO_ENGINES_STAMP[lega] = time.monotonic()
            try:
                for casa, fuori in giornata1:
                    p = predict_elo_probs(casa, fuori, lega, season=2026)
                    self.assertAlmostEqual(p["1"] + p["X"] + p["2"], 1.0, places=3)
            finally:
                ELO_MOD._ELO_ENGINES_CACHE.pop(lega, None)
                ELO_MOD._ELO_ENGINES_STAMP.pop(lega, None)
            return entranti, seed_file, len(giornata1)

    def _giornata1(self, lega):
        """(casa, fuori) della prima giornata 2026 dai CSV reali (grezzi)."""
        prefix = PROD_CONFIG.LEAGUES_CONFIG[lega]["db_prefix"]
        df = pd.read_csv(Path(PROD_CONFIG.DATABASE_DIR) / f"{prefix}_Live.csv",
                         on_bad_lines="warn", low_memory=False)
        # I *_Live.csv contengono solo la stagione in corso: la minima e' la 1.
        df = df[df["Matchday"] == df["Matchday"].min()]
        return sorted(zip(df["HomeTeam"], df["AwayTeam"]))

    def test_serie_a(self):
        entranti, seed, n = self._confronto_lega("Serie A")
        self.assertEqual(entranti, ["Frosinone", "Monza", "Venezia"])
        self.assertEqual(n, 10)

    def test_premier_league(self):
        entranti, seed, n = self._confronto_lega("Premier League")
        self.assertEqual(entranti, ["Coventry City", "Hull City", "Ipswich"])
        self.assertEqual(n, 10)

    def test_la_liga(self):
        entranti, seed, n = self._confronto_lega("La Liga")
        self.assertEqual(entranti, ["Deportivo", "Málaga", "Santander"])
        self.assertEqual(n, 10)

    def test_bundesliga(self):
        entranti, seed, n = self._confronto_lega("Bundesliga")
        self.assertEqual(entranti, ["Elversberg", "SC Paderborn", "Schalke 04"])
        self.assertEqual(n, 9)

    def test_ligue_1(self):
        entranti, seed, n = self._confronto_lega("Ligue 1")
        self.assertEqual(entranti, ["Le Mans", "Troyes"])
        self.assertEqual(n, 9)

    def test_tabella_seed_pre_stagione(self):
        """Stampa la tabella per lega (evidenza, non solo asserzioni)."""
        righe = []
        for lega in LEGHE:
            entranti, seed, n = self._confronto_lega(lega)
            for squadra in entranti:
                righe.append((lega, squadra, seed[squadra], n))
        print("\n  lega | entrante | seed pre-stagione 2026 | partite giornata 1")
        for lega, squadra, s, n in righe:
            print(f"  {lega} | {squadra} | {s} | {n}")
        self.assertEqual(len(righe), 3 + 3 + 3 + 3 + 2)


class TestUpdateDbSalvaIlRoster(unittest.TestCase):
    def _api(self, utc, casa, fuori, gh=None, ga=None, md=1, stato="FINISHED"):
        return {"utcDate": utc, "matchday": md, "status": stato,
                "homeTeam": {"shortName": casa, "name": casa},
                "awayTeam": {"shortName": fuori, "name": fuori},
                "score": {"winner": ("HOME_TEAM" if gh is not None and ga is not None and gh > ga
                                     else "DRAW" if gh is not None else None),
                          "fullTime": {"home": gh, "away": ga},
                          "halfTime": {"home": 0, "away": 0}}}

    def test_future_nel_roster_ma_non_nei_csv(self):
        from update_db import matches_to_df, rosters_from_api_matches
        partite = [
            self._api("2026-08-22T16:00:00Z", "Inter", "Monza", 2, 0),
            self._api("2026-08-30T16:00:00Z", "Milan", "Lazio"),  # futura
            self._api("2027-05-20T16:00:00Z", "Roma", "Napoli"),  # futura di maggio
        ]
        roster = rosters_from_api_matches(partite)
        self.assertEqual(roster[2026], {"Inter", "Monza", "Milan", "Lazio", "Roma", "Napoli"})
        df = matches_to_df(partite)
        self.assertEqual(len(df), 1, "le non giocate restano fuori dai CSV come oggi")

    def test_matches_to_df_scrive_solo_le_finished(self):
        """Lo stato decide, non il punteggio: un ``score.fullTime`` non nullo su
        una partita non conclusa (0-0 provvisorio della sospensione, riga del
        recupero servita dall'API come fullTime) NON entra nei CSV."""
        from update_db import matches_to_df
        casi = [
            ("FINISHED", 2, 1),
            ("IN_PLAY", 1, 0),        # in corso: il punteggio e' provvisorio
            ("SUSPENDED", 0, 0),      # sospesa (Levante-Ath Bilbao 16/09/2026)
            ("POSTPONED", 0, 0),      # rinviata, riga alla data del recupero
            ("AWARDED", 3, 0),        # a tavolino: non e' un dato di gioco
            ("SCHEDULED", None, None),
            ("CANCELLED", None, None),
            (None, 0, 0),             # status assente: non e' una conclusione
        ]
        for stato, gh, ga in casi:
            with self.subTest(stato=stato):
                partita = self._api("2026-10-03T16:00:00Z", "Inter", "Monza", gh, ga, md=7)
                if stato is None:
                    partita.pop("status")
                else:
                    partita["status"] = stato
                df = matches_to_df([partita])
                if stato == "FINISHED":
                    self.assertEqual(len(df), 1, "FINISHED deve entrare")
                    self.assertEqual((int(df.iloc[0]["FTHG"]), int(df.iloc[0]["FTAG"])), (gh, ga))
                else:
                    self.assertEqual(len(df), 0, f"{stato} non deve entrare nei CSV")

    def test_matches_to_df_lista_mista_tiene_solo_le_concluse(self):
        from update_db import matches_to_df
        partite = [
            self._api("2026-09-20T16:00:00Z", "Betis", "Getafe", 1, 0, md=6),
            self._api("2026-09-16T18:45:00Z", "Levante", "Ath Bilbao", 0, 0, md=6,
                      stato="SUSPENDED"),
            self._api("2026-10-21T19:00:00Z", "Levante", "Ath Bilbao", 0, 0, md=6,
                      stato="POSTPONED"),
            self._api("2026-10-25T16:00:00Z", "Valencia", "Celta", None, None, md=8,
                      stato="TIMED"),
        ]
        df = matches_to_df(partite)
        self.assertEqual(len(df), 1)
        self.assertEqual((df.iloc[0]["HomeTeam"], df.iloc[0]["AwayTeam"]), ("Betis", "Getafe"))
        self.assertEqual(df.iloc[0]["Date"], "20/09/2026")

    def test_salvataggio_merge_e_ordinamento_stabile(self):
        with _DBTemp() as db:
            (db.tmp / SR.ROSTER_FILENAME).unlink(missing_ok=True)
            SR.save_league_roster("SerieA", 2026, ["Napoli", "Inter", "Inter", "Milan"])
            SR.save_league_roster("Premier League", 2026, ["Arsenal", "Chelsea"])
            tutto = SR.load_season_rosters(database_dir=db.tmp)
            self.assertEqual(tutto["Serie A"][2026], ["Inter", "Milan", "Napoli"])
            self.assertEqual(tutto["Premier League"][2026], ["Arsenal", "Chelsea"])
            prima = (db.tmp / SR.ROSTER_FILENAME).read_bytes()
            SR.save_league_roster("Serie A", 2026, ["Milan", "Napoli", "Inter"])
            dopo = (db.tmp / SR.ROSTER_FILENAME).read_bytes()
            self.assertEqual(prima, dopo, "stesso contenuto, stessi byte")


class TestValidazioneETolleranza(unittest.TestCase):
    def test_taglie_e_scadenza(self):
        self.assertEqual(SR.EXPECTED_ROSTER_SIZE["Serie A"], 20)
        self.assertEqual(SR.EXPECTED_ROSTER_SIZE["Bundesliga"], 18)
        self.assertEqual(SR.EXPECTED_ROSTER_SIZE["Ligue 1"], 18)
        self.assertEqual(SC.roster_deadline(2026), date(2026, 7, 15))
        self.assertTrue(SC.within_roster_tolerance(2026, date(2026, 7, 15)))
        self.assertFalse(SC.within_roster_tolerance(2026, date(2026, 7, 16)))
        self.assertTrue(SC.within_roster_tolerance(2026, date(2026, 6, 30)))

    def test_file_reale_valido_oltre_il_termine(self):
        errori = SR.validate_current_rosters(now=datetime(2026, 10, 7), current_season=2026)
        self.assertEqual(errori, [])

    def test_mancante_tollerato_prima_non_dopo(self):
        # Il database e' troncato alla data simulata: con un orologio di luglio
        # 2026 un DB di ottobre conterrebbe righe "future" e il controllo sui
        # *_Live.csv (date future) segnalerebbe un difetto del FIXTURE, non del
        # roster. Il test resta su cio' che verifica: la tolleranza del roster.
        with _DBTemp(truncated_before=datetime(2026, 7, 10)) as db:
            (db.tmp / SR.ROSTER_FILENAME).unlink(missing_ok=True)
            ok = SR.validate_current_rosters(database_dir=db.tmp, current_season=2026,
                                             now=datetime(2026, 7, 10))
            self.assertEqual(ok, [])
            ko = SR.validate_current_rosters(database_dir=db.tmp, current_season=2026,
                                             now=datetime(2026, 7, 16))
            self.assertEqual(len(ko), 5)
            self.assertTrue(all("MANCANTE" in e for e in ko))

    def test_incompleto_fallisce_anche_entro_il_termine(self):
        with _DBTemp(truncated_before=datetime(2026, 7, 10)) as db:
            (db.tmp / SR.ROSTER_FILENAME).write_text(
                json.dumps({"Serie A": {"2026": ["Inter", "Milan"]}}), encoding="utf-8")
            errori = SR.validate_current_rosters(database_dir=db.tmp, current_season=2026,
                                                 now=datetime(2026, 7, 10))
            self.assertEqual(len(errori), 1)
            self.assertIn("2 squadre", errori[0])
            self.assertIn("attese 20", errori[0])

    def test_nome_non_punto_fisso_fallisce(self):
        """Regressione: 'Köln' nel roster deve fallire perche' non e' un
        punto fisso di clean_name (clean_name('Köln')=='Koln'!='Köln')."""
        with _DBTemp() as db:
            with open(db.tmp / SR.ROSTER_FILENAME, "r", encoding="utf-8") as f:
                data = json.load(f)
            # inietta 'Köln' al posto di 'Koln' nel Bundesliga 2026
            data["Bundesliga"]["2026"] = [
                ("Köln" if t == "Koln" else t) for t in data["Bundesliga"]["2026"]
            ]
            with open(db.tmp / SR.ROSTER_FILENAME, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            errori = SR.validate_current_rosters(database_dir=db.tmp, current_season=2026,
                                                 now=datetime(2026, 10, 7))
            self.assertTrue(any("punto fisso" in e and "Köln" in e for e in errori),
                            f"atteso errore su 'Köln', trovati: {errori}")
            # e anche il Live CSV mismatch (Koln vs Köln)
            self.assertTrue(any("Live CSV" in e and "Koln" in e for e in errori),
                            f"atteso errore Live CSV Koln, trovati: {errori}")


class TestControlloLiveCsv(unittest.TestCase):
    """I due difetti misurati su LaLiga_Live.csv (Levante-Ath Bilbao):
    riga con data futura (21/10/2026) e coppia (HomeTeam, AwayTeam) ripetuta
    nella stessa stagione (16/09/2026 sospesa + 21/10/2026 recupero).

    Il controllo vive in ``validate_live_csvs``, richiamato da
    ``validate_current_rosters``: e' il passo che il workflow esegue
    (``python season_rosters.py --check``) PRIMA del commit dei CSV.
    """

    COLONNE_RIGA = ("Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR",
                    "HTHG", "HTAG", "HTR", "Matchday")

    def _aggiungi_righe(self, path: Path, righe):
        """Aggiunge righe ``(data, casa, ospite, gol_casa, gol_ospite)`` al CSV."""
        df = pd.read_csv(path, low_memory=False)
        nuove = []
        for giorno, casa, ospite, gh, ga in righe:
            voce = {c: None for c in df.columns}
            voce.update({"Date": giorno, "HomeTeam": casa, "AwayTeam": ospite,
                         "FTHG": gh, "FTAG": ga,
                         "FTR": "H" if gh > ga else ("A" if ga > gh else "D"),
                         "HTHG": 0, "HTAG": 0,
                         "HTR": "H" if gh > ga else ("A" if ga > gh else "D"),
                         "Matchday": 6})
            nuove.append(voce)
        df = pd.concat([df, pd.DataFrame(nuove)], ignore_index=True)
        df.to_csv(path, index=False)

    def test_data_futura_e_errore(self):
        with _DBTemp() as db:
            live = db.tmp / "LaLiga_Live.csv"
            self._aggiungi_righe(live, [("21/10/2026", "Levante", "Ath Bilbao", 0, 0)])
            errori = SR.validate_live_csvs(db.tmp, datetime(2026, 10, 8))
            self.assertTrue(
                any("DATA FUTURA" in e and "Levante-Ath Bilbao" in e for e in errori),
                f"atteso errore di data futura, trovati: {errori}")

    def test_coppia_ripetuta_nella_stessa_stagione_e_errore(self):
        with _DBTemp() as db:
            live = db.tmp / "LaLiga_Live.csv"
            # entrambe nel passato del "now" simulato: cosi' l'unico errore
            # possibile e' la ripetizione, non la data futura
            self._aggiungi_righe(live, [("16/09/2026", "Levante", "Ath Bilbao", 0, 0),
                                        ("21/10/2026", "Levante", "Ath Bilbao", 0, 0)])
            errori = SR.validate_live_csvs(db.tmp, datetime(2026, 11, 1))
            self.assertEqual([e for e in errori if "DATA FUTURA" in e], [],
                             f"nessuna data e' futura a novembre: {errori}")
            self.assertTrue(
                any("ripetuta nella stagione" in e and "Levante-Ath Bilbao" in e
                    and "16/09/2026" in e and "21/10/2026" in e for e in errori),
                f"atteso errore di coppia ripetuta, trovati: {errori}")

    def test_andata_e_ritorno_nella_stessa_stagione_non_e_un_errore(self):
        """La coppia e' ORDINATA (casa, ospite): il ritorno e' un'altra coppia."""
        with _DBTemp() as db:
            live = db.tmp / "LaLiga_Live.csv"
            self._aggiungi_righe(live, [("10/01/2027", "Ath Bilbao", "Levante", 2, 0)])
            errori = SR.validate_live_csvs(db.tmp, datetime(2027, 1, 11))
            self.assertEqual(errori, [], f"atteso nessun errore, trovati: {errori}")

    def test_validate_current_rosters_include_il_controllo(self):
        """Il passo del workflow vede i difetti anche con il roster a posto."""
        with _DBTemp() as db:
            self._aggiungi_righe(db.tmp / "LaLiga_Live.csv",
                                 [("21/10/2026", "Levante", "Ath Bilbao", 0, 0)])
            errori = SR.validate_current_rosters(database_dir=db.tmp, current_season=2026,
                                                 now=datetime(2026, 10, 8))
            self.assertTrue(any("DATA FUTURA" in e for e in errori),
                            f"il roster e' valido: resta il solo errore del CSV, trovati: {errori}")

    def test_database_reale_senza_date_future_ne_coppie_ripetute(self):
        """Sentinella sui dati committati: le due righe di Levante-Ath Bilbao
        (16/09 sospesa, 21/10 recupero) sono state rimosse e non devono
        tornare. Il confronto e' sull'orologio reale, come in produzione."""
        errori = SR.validate_live_csvs()
        self.assertEqual(errori, [], f"database reale non pulito: {errori}")
        # e il controllo non e' vacuo: nelle stagioni complete esistono le
        # partite di ritorno (stessa coppia di squadre, ordine invertito, stessa
        # stagione) e NON sono un errore. I Live CSV della stagione in corso si
        # fermano alla giornata 7, quindi la prova usa uno storico.
        storico = Path(PROD_CONFIG.DATABASE_DIR) / "LaLiga_2025.csv"
        coppie = {(c, o) for _, c, o in SR._live_rows(storico)}
        self.assertTrue(any((o, c) in coppie and (c, o) in coppie for c, o in coppie),
                        "nessuna andata/ritorno nello storico: il test non prova nulla")
        self.assertEqual(SR.validate_live_csvs(database_dir=None), [],
                         "le andate/ritorni dello storico non sono duplicati")


class TestAppPassaLaStagione(unittest.TestCase):
    def test_stagione_da_utcdate(self):
        import app as PROD_APP
        self.assertEqual(PROD_APP._stagione_da_utcdate("2026-08-22T16:00:00Z"), 2026)
        self.assertEqual(PROD_APP._stagione_da_utcdate("2027-01-15T20:45:00Z"), 2026)
        self.assertEqual(PROD_APP._stagione_da_utcdate("2027-07-01T00:00:00Z"), 2027)
        corrente = PROD_CONFIG.get_current_season_start_year()
        self.assertEqual(PROD_APP._stagione_da_utcdate(None), corrente)
        self.assertEqual(PROD_APP._stagione_da_utcdate("rotta"), corrente)

    def test_blend_inoltra_la_stagione(self):
        import app as PROD_APP
        from unittest import mock
        m = {"1": 0.5, "X": 0.3, "2": 0.2, "u25": 0.5, "gg": 0.5}
        with mock.patch.object(PROD_APP, "predict_elo_probs",
                               return_value={"1": 0.5, "X": 0.3, "2": 0.2}) as pred:
            PROD_APP.blend_elo_into_1x2(dict(m), "H", "A", "Serie A", season=2026)
            pred.assert_called_once_with("H", "A", "Serie A", season=2026)


if __name__ == "__main__":
    unittest.main(verbosity=2)
