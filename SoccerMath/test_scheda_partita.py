"""Test del modulo puro ``scheda_partita`` (la scheda partita in parole).

Cosa verificano, in parole povere:

* la classifica della stagione e' IDENTICA a un conteggio rifatto a mano nel
  test riga per riga (metodo indipendente: lettura del CSV con il modulo
  ``csv`` di Python e dizionari, non le funzioni del modulo), su dati reali
  del repository;
* giornate rimaste (38 o 34 secondo le squadre del campionato), posizione di
  spareggio di Bundesliga e Ligue 1 e distanze in punti dal primo, dal quarto,
  dal sesto posto e dalla zona retrocessione;
* TUTTI i rami delle frasi degli obiettivi, con classifiche costruite a mano;
* le fasce dell'avversario ("forte", "media", "debole") calcolate con l'Elo
  PRIMA della partita, con i due test di non-leakage: cambiare il risultato di
  una partita FUTURA non cambia la fotografia Elo (ne' la fascia) di una
  partita PASSATA, e la fotografia e' l'ultimo rating precedente a quella data;
* i casi di dati insufficienti (neopromossa con due partite, campionato
  appena iniziato, blocco senza storico): il modulo li DICHIARA, non mostra
  numeri vuoti, e le percentuali non compaiono sotto le 5 partite;
* l'abbinamento delle partite in programma ai nomi dei CSV sullo snapshot
  pinnato di ``live_odds.json`` (commit ``e2f595e``, lo stesso dei test della
  PR #64), con il conteggio delle partite senza corrispondenza.

Nessun test legge i ``*_Live.csv`` o ``live_odds.json`` CORRENTI con valori
attesi fissi: la classifica e i conteggi sono ricalcolati nel test, e le quote
vengono dallo snapshot pinnato nel repository (``snap_test.snapshot_reale``).
"""
from __future__ import annotations

import csv
import os
import re
import sys
import unittest
from datetime import datetime, timezone

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
for _p in (HERE, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config  # noqa: E402
import market_odds as mo  # noqa: E402
import scheda_partita as sp  # noqa: E402
import snap_test  # noqa: E402
from models.elo_engine import EloEngine, get_elo_engine  # noqa: E402
from season_calendar import season_start_year_of  # noqa: E402
from team_aliases import clean_name  # noqa: E402

# Orologio congelato dei test: venerdi' 2026-10-16 18:00 ora italiana (lo
# stesso istante dei test di presentazione della PR #64).
ADESSO = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)
CAMP = "Serie A"


def _righe_grezze(percorso: str) -> list:
    """Le righe del CSV cosi' come sono, lette senza pandas."""
    with open(percorso, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def classifica_contata_a_mano(percorso: str, stagione: int) -> dict:
    """Classifica rifatta a mano sulle righe grezze del CSV (nessun pandas).

    Ritorna ``{squadra: {"punti", "giocate", "vinte", "pari", "perse", "gf", "gs"}}``.
    Le partite senza risultato (``FTR`` vuoto) restano fuori, come nel modulo.
    """
    tabelle: dict = {}

    def _riga(squadra: str) -> dict:
        return tabelle.setdefault(squadra, {"punti": 0, "giocate": 0, "vinte": 0,
                                            "pari": 0, "perse": 0, "gf": 0, "gs": 0})

    for r in _righe_grezze(percorso):
        data = (r.get("Date") or "").strip()
        ftr = (r.get("FTR") or "").strip()
        if not data or not ftr:
            continue
        if not (r.get("FTHG") or "").strip() or not (r.get("FTAG") or "").strip():
            continue  # come il modulo: senza gol la riga non entra
        giorno, mese, anno = (int(x) for x in data.split("/"))
        if season_start_year_of(datetime(anno, mese, giorno)) != stagione:
            continue
        casa, trasferta = clean_name(r["HomeTeam"]), clean_name(r["AwayTeam"])
        gh, ga = int(r["FTHG"]), int(r["FTAG"])
        rc, rt = _riga(casa), _riga(trasferta)
        rc["giocate"] += 1
        rt["giocate"] += 1
        rc["gf"] += gh
        rc["gs"] += ga
        rt["gf"] += ga
        rt["gs"] += gh
        if gh > ga:
            rc["punti"] += 3
            rc["vinte"] += 1
            rt["perse"] += 1
        elif gh < ga:
            rt["punti"] += 3
            rt["vinte"] += 1
            rc["perse"] += 1
        else:
            rc["punti"] += 1
            rt["punti"] += 1
            rc["pari"] += 1
            rt["pari"] += 1
    return tabelle


def _df_per_motore(risultati: pd.DataFrame) -> pd.DataFrame:
    """Da ``carica_risultati_stagione`` alle colonne che il motore Elo legge."""
    df = pd.DataFrame({
        "Date_Parsed": pd.to_datetime(risultati["data"]),
        "HomeClean": risultati["casa"].tolist(),
        "AwayClean": risultati["trasferta"].tolist(),
        "FTHG": risultati["gol_casa"].astype(int).tolist(),
        "FTAG": risultati["gol_ospiti"].astype(int).tolist(),
    })
    df["FTR"] = ["H" if h > a else ("A" if a > h else "D")
                 for h, a in zip(df["FTHG"], df["FTAG"])]
    return df.sort_values("Date_Parsed", kind="stable").reset_index(drop=True)


class _EngineDaDataFrame(EloEngine):
    """Motore Elo alimentato da un DataFrame gia' pronto (nessun file letto).

    Serve ai test di non-leakage: il motore vero, con il suo seeding, su due
    versioni della stessa stagione (originale e con un risultato futuro
    cambiato).
    """

    def __init__(self, league: str, df: pd.DataFrame):
        super().__init__(league)
        self._df = df

    def load_and_preprocess_matches(self) -> pd.DataFrame:
        self.matches_df = self._df.copy()
        return self.matches_df


class TestClassificaRiconataAMano(unittest.TestCase):
    """La classifica del modulo = conteggio indipendente, riga per riga."""

    @classmethod
    def setUpClass(cls):
        cls.percorso = sp.percorso_live_csv(CAMP)
        if not cls.percorso or not os.path.exists(cls.percorso):
            raise unittest.SkipTest("CSV della stagione non trovato")
        cls.stagione = config.get_current_season_start_year()
        cls.risultati = sp.carica_risultati_stagione(CAMP, stagione=cls.stagione)
        cls.classifica = sp.classifica(cls.risultati)
        cls.attesa = classifica_contata_a_mano(cls.percorso, cls.stagione)

    def test_una_riga_per_squadra_e_nessun_doppione(self):
        nomi = [r["squadra"] for r in self.classifica]
        self.assertEqual(len(nomi), len(set(nomi)))
        self.assertEqual(sorted(nomi), sorted(self.attesa.keys()))

    def test_punti_giocate_gol_identici_al_conteggio_a_mano(self):
        self.assertTrue(self.classifica, "nessuna partita della stagione in corso")
        for r in self.classifica:
            with self.subTest(squadra=r["squadra"]):
                atteso = self.attesa[r["squadra"]]
                self.assertEqual(r["punti"], atteso["punti"])
                self.assertEqual(r["giocate"], atteso["giocate"])
                self.assertEqual(r["vinte"], atteso["vinte"])
                self.assertEqual(r["pari"], atteso["pari"])
                self.assertEqual(r["perse"], atteso["perse"])
                self.assertEqual(r["gf"], atteso["gf"])
                self.assertEqual(r["gs"], atteso["gs"])
                self.assertEqual(r["dr"], atteso["gf"] - atteso["gs"])

    def test_somma_dei_PUNTI_delle_partite_del_csv(self):
        """Punti distribuiti, giocati e gol totali: due conti che devono tornare."""
        partite = sum(r["giocate"] for r in self.classifica) // 2
        punti = sum(r["punti"] for r in self.classifica)
        gol = sum(r["gf"] for r in self.classifica)
        mano_partite = len([r for r in _righe_grezze(self.percorso)
                            if (r.get("FTR") or "").strip()
                            and (r.get("FTHG") or "").strip()
                            and (r.get("FTAG") or "").strip()
                            and season_start_year_of(
                                datetime(int(r["Date"].split("/")[2]),
                                         int(r["Date"].split("/")[1]),
                                         int(r["Date"].split("/")[0]))) == self.stagione])
        mano_punti = sum(r["punti"] for r in self.attesa.values())
        mano_gol = sum(r["gf"] for r in self.attesa.values())
        self.assertEqual(partite, mano_partite)
        self.assertEqual(punti, mano_punti)
        self.assertEqual(gol, mano_gol)

    def test_ordinamento_e_posizioni(self):
        for i, r in enumerate(self.classifica, start=1):
            self.assertEqual(r["pos"], i)
        chiavi = [(-r["punti"], -r["dr"], -r["gf"], r["squadra"]) for r in self.classifica]
        self.assertEqual(chiavi, sorted(chiavi))


class TestGiornateEDistanze(unittest.TestCase):
    """Giornate rimaste (38 o 34) e distanze in punti dalle posizioni."""

    def test_giornate_totali_dal_numero_di_squadre(self):
        self.assertEqual(sp.giornate_totali(20), 38)
        self.assertEqual(sp.giornate_totali(18), 34)

    def test_giornate_rimaste(self):
        self.assertEqual(sp.giornate_rimaste(20, 0), 38)
        self.assertEqual(sp.giornate_rimaste(20, 6), 32)
        self.assertEqual(sp.giornate_rimaste(18, 5), 29)
        self.assertEqual(sp.giornate_rimaste(18, 40), 0)

    def test_numero_squadre_dal_roster_di_calendario(self):
        self.assertEqual(sp.numero_squadre("Serie A"), 20)
        self.assertEqual(sp.numero_squadre("Bundesliga"), 18)
        self.assertEqual(sp.numero_squadre("Ligue 1"), 18)

    def test_posizione_zero_e_spareggio(self):
        self.assertEqual(sp.posizione_zero("Serie A", 20), 18)
        self.assertEqual(sp.posizione_zero("Bundesliga", 18), 16)
        self.assertFalse(sp.e_zona_spareggio("Serie A", 18, 20))
        self.assertTrue(sp.e_zona_spareggio("Bundesliga", 16, 18))
        self.assertTrue(sp.e_zona_spareggio("Ligue 1", 16, 18))

    def test_distanze_sulla_classifica_vera(self):
        risultati = sp.carica_risultati_stagione(CAMP)
        if risultati.empty:
            self.skipTest("nessun risultato della stagione in corso")
        cl = sp.classifica(risultati)
        n = sp.numero_squadre(CAMP, risultati=risultati)
        prima = cl[0]
        p = sp.posta_in_palio(cl, CAMP, prima["squadra"], n)
        self.assertEqual(p["dal_primo"], 0)
        self.assertFalse(p["in_zona"])
        for riferimento, chiave in ((0, "dal_primo"), (3, "dal_quarto"), (5, "dal_sesto")):
            if riferimento < len(cl):
                self.assertEqual(p[chiave], cl[riferimento]["punti"] - prima["punti"])
        zona = next(r for r in cl if r["pos"] == sp.posizione_zero(CAMP, n))
        self.assertEqual(p["dalla_zona"], prima["punti"] - zona["punti"])
        self.assertEqual(p["giornate_rimaste"], sp.giornate_rimaste(n, prima["giocate"]))


class TestFrasiObiettivi(unittest.TestCase):
    """Tutti i rami delle regole, con classifiche costruite a mano."""

    BASE_20 = [30, 28, 26, 25, 24, 23, 22, 21, 20, 19,
               18, 17, 16, 15, 14, 13, 12, 11, 10, 9]
    BASE_18 = [30, 28, 26, 25, 24, 23, 22, 21, 20, 19,
               18, 17, 16, 15, 14, 13, 12, 11]

    def _frase(self, pos: int, punti_squadra: int, punti_riferimento: dict,
               n_squadre: int = 20, camp: str = "Serie A", giornate: int = 10) -> str:
        base = list(self.BASE_18 if n_squadre == 18 else self.BASE_20)
        for p, pt in punti_riferimento.items():
            base[p - 1] = pt
        base[pos - 1] = punti_squadra
        cl = [{"pos": i, "squadra": f"S{i:02d}", "nome": f"S{i:02d}", "punti": pt,
               "giocate": giornate, "vinte": 0, "pari": 0, "perse": 0,
               "gf": 0, "gs": 0, "dr": 0}
              for i, pt in enumerate(base, start=1)]
        dati = sp.posta_in_palio(cl, camp, f"S{pos:02d}", n_squadre)
        self.assertIsNotNone(dati, "classe di prova non costruita")
        return sp.frase_obiettivi(dati, giornate, camp)

    def test_prima_di_cinque_giornate(self):
        self.assertEqual(self._frase(1, 12, {}, giornate=4), sp.FRASE_APPENA_INIZIATO)
        self.assertNotEqual(self._frase(1, 15, {}, giornate=5), sp.FRASE_APPENA_INIZIATO)

    def test_al_comando(self):
        self.assertEqual(self._frase(1, 30, {}), "Al comando della classifica.")

    def test_in_corsa_per_il_titolo(self):
        # Il titolo e' SOLO delle prime 3 posizioni (POSIZIONI_TITOLO = 3).
        self.assertEqual(self._frase(2, 24, {1: 30}),
                         "In corsa per il titolo: 6 punti dal primo posto.")
        self.assertEqual(self._frase(3, 26, {1: 30}),
                         "In corsa per il titolo: 4 punti dal primo posto.")
        # Una seconda a pari punti col primo e' appaiata, non "al comando".
        self.assertEqual(self._frase(2, 30, {1: 30}),
                         "In corsa per il titolo: appaiata al primo posto.")

    def test_la_soglia_del_titolo_vale_solo_dentro_le_prime_tre(self):
        # 8ª a 6 punti dal primo: NON e' "in corsa per il titolo" (il distacco
        # e' da zona Europa), e la frase ricade sulla regola successiva.
        frase = self._frase(8, 24, {1: 30})
        self.assertNotIn("titolo", frase)
        self.assertEqual(frase, "In zona Europa: 1 punto sopra il sesto posto.")

    def test_fuori_dalla_soglia_del_titolo(self):
        frase = self._frase(9, 18, {1: 30, 6: 24})
        self.assertNotIn("titolo", frase)
        self.assertEqual(frase, "In corsa per l'Europa: 6 punti dal sesto posto.")
        # 4ª a 6 punti dal primo: fuori dalle prime 3, ricade sull'Europa.
        quarta = self._frase(4, 24, {1: 30, 6: 20})
        self.assertNotIn("titolo", quarta)
        self.assertEqual(quarta, "In zona Europa: 4 punti sopra il sesto posto.")

    def test_ultime_due_retrocessione_diretta(self):
        # 20 squadre (Serie A, Premier, La Liga): zona dalla 18a, ma la frase
        # della retrocessione diretta e' delle ULTIME DUE, con la distanza
        # dalla SALVEZZA (la 17a, prima posizione fuori dalla zona diretta).
        self.assertEqual(self._frase(19, 12, {17: 15, 18: 12}),
                         "In zona retrocessione diretta: 3 punti dalla salvezza.")
        self.assertEqual(self._frase(20, 4, {17: 12, 18: 12}),
                         "In zona retrocessione diretta: 8 punti dalla salvezza.")

    def test_prima_posizione_della_zona_appaiata(self):
        # La 18a di 20 e' la PRIMA della zona: non e' "ultima due", quindi
        # resta la frase della lotta per non retrocedere (appaiata alla zona).
        self.assertEqual(self._frase(18, 12, {17: 15}),
                         "Lotta per non retrocedere: appaiata alla zona retrocessione.")

    def test_dentro_la_zona_se_la_classifica_non_e_allineata(self):
        # Ramo di sicurezza: se la prima posizione della zona non e' quella
        # della squadra (classifica corta o incompleta), si dice di quanto e'
        # dentro la zona invece di inventare una appaiatura.
        p = {"pos": 18, "punti": 10, "giocate": 10, "in_zona": True,
             "spareggio": False, "ultime_due": False, "dalla_zona": -3,
             "dal_primo": 20, "dal_sesto": 13, "n_squadre": 20}
        self.assertEqual(sp.frase_obiettivi(p, 10, "Serie A"),
                         "Lotta per non retrocedere: 3 punti dentro la zona retrocessione.")

    def test_spareggio_bundesliga_e_ligue_1(self):
        # Terzultima (16a di 18) con 14 punti, penultima a 12: la distanza che
        # conta e' quella dalla retrocessione DIRETTA.
        frase = self._frase(16, 14, {17: 12, 18: 10}, n_squadre=18,
                            camp="Bundesliga", giornate=10)
        self.assertEqual(frase, "Spareggio: terzultima, 2 punti sopra la retrocessione diretta.")
        appaiata = self._frase(16, 12, {17: 12, 18: 10}, n_squadre=18,
                               camp="Ligue 1", giornate=10)
        self.assertEqual(appaiata,
                         "Spareggio: terzultima, appaiata alla retrocessione diretta.")

    def test_la_nota_spareggio_e_solo_della_terzultima(self):
        # La nota "(terzultima = spareggio)" NON e' un avviso di zona: e' della
        # sola squadra che occupa quella posizione. La 15a di 18 sta 4 punti
        # sopra la zona e la sua frase non parla di spareggio.
        frase = self._frase(15, 16, {16: 12, 17: 9, 18: 6}, n_squadre=18,
                            camp="Bundesliga", giornate=10)
        self.assertEqual(frase, "Lotta per non retrocedere: 4 punti sopra la zona.")
        self.assertNotIn("spareggio", frase)
        # In Serie A (20 squadre) la parola non compare mai.
        self.assertNotIn("spareggio", self._frase(17, 10, {18: 9}))
        # La 17a di 18 (penultima) e' in retrocessione DIRETTA, non spareggio.
        penultima = self._frase(17, 8, {16: 12, 18: 6}, n_squadre=18,
                                camp="Ligue 1", giornate=10)
        self.assertEqual(penultima,
                         "In zona retrocessione diretta: 4 punti dalla salvezza.")
        self.assertNotIn("spareggio", penultima)
        # Ultima di 18: stessa frase, distanza dalla terzultima (la salvezza).
        ultima = self._frase(18, 6, {16: 12, 17: 8}, n_squadre=18,
                             camp="Ligue 1", giornate=10)
        self.assertEqual(ultima,
                         "In zona retrocessione diretta: 6 punti dalla salvezza.")

    def test_lotta_per_non_retrocedere_sopra_la_zona(self):
        self.assertEqual(self._frase(17, 10, {18: 9}),
                         "Lotta per non retrocedere: 1 punto sopra la zona.")
        self.assertEqual(self._frase(16, 15, {18: 9}),
                         "Lotta per non retrocedere: 6 punti sopra la zona.")
        self.assertNotIn("Lotta per non retrocedere", self._frase(16, 16, {18: 9}))

    def test_appaiata_alla_zona(self):
        self.assertEqual(self._frase(17, 9, {18: 9}),
                         "Lotta per non retrocedere: appaiata alla zona retrocessione.")

    def test_zona_europa(self):
        self.assertEqual(self._frase(6, 20, {6: 20}), "In zona Europa: al sesto posto.")
        self.assertEqual(self._frase(4, 24, {1: 32, 6: 20}),
                         "In zona Europa: 4 punti sopra il sesto posto.")

    def test_zona_tranquilla(self):
        self.assertEqual(self._frase(10, 19, {6: 26, 18: 9}),
                         "Zona tranquilla: 7 punti dal sesto posto, "
                         "10 punti sopra la zona retrocessione.")

    def test_classifica_non_disponibile(self):
        self.assertEqual(sp.frase_obiettivi(None, 10, CAMP),
                         "Classifica non disponibile: dati di questa stagione insufficienti.")


class TestLeHavreEAuxerreSulloSnapshotFissato(unittest.TestCase):
    """Le Havre e Auxerre di Ligue 1, con la classifica dello SNAPSHOT fissato.

    La classifica non viene dai ``*_Live.csv`` correnti (che il workflow
    ``update_database`` riscrive a ogni giornata, e un test con valori attesi
    fissi su quei file balla): viene dal blob del commit ``SNAP_CSV_COMMIT``,
    lo stesso stato citato nel referto della scheda partita — Le Havre ultima
    (18ª) e Auxerre terzultima (16ª), quindi la prima con la frase della
    retrocessione diretta e la seconda con quella dello spareggio.

    Cosa verifica: le due frasi, il fatto che la nota dello spareggio NON esca
    dalla terzultima (la penultima Troyes e l'ultima Le Havre non ce l'hanno) e
    che le distanze mostrate siano quelle del conteggio indipendente.
    """

    CAMP = "Ligue 1"
    STAGIONE = 2026
    PERCORSO = "SoccerMath/database/Ligue1_Live.csv"

    @classmethod
    def setUpClass(cls):
        raw = snap_test.blob_del_commit(cls.PERCORSO)
        if raw is None:
            raise unittest.SkipTest("CSV dello snapshot fissato non raggiungibile "
                                    "(clone shallow?)")
        import tempfile
        cls.tmp = tempfile.mkdtemp(prefix="scheda_ligue1_")
        cls.file = os.path.join(cls.tmp, "Ligue1_Live.csv")
        with open(cls.file, "w", encoding="utf-8") as fh:
            fh.write(raw)
        cls.risultati = sp.carica_risultati_stagione(cls.CAMP, stagione=cls.STAGIONE,
                                                     percorso=cls.file)
        if cls.risultati.empty:
            raise unittest.SkipTest("snapshot fissato senza partite giocate")
        cls.classifica = sp.classifica(cls.risultati)
        cls.n_squadre = sp.numero_squadre(cls.CAMP, cls.STAGIONE, cls.risultati)
        if not cls.n_squadre:
            raise unittest.SkipTest("numero di squadre non determinabile")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(getattr(cls, "tmp", ""), ignore_errors=True)

    def _posta(self, squadra: str) -> dict:
        dati = sp.posta_in_palio(self.classifica, self.CAMP, squadra, self.n_squadre)
        self.assertIsNotNone(dati, f"{squadra} non e' nella classifica dello snapshot")
        return dati

    def _frase(self, squadra: str) -> str:
        dati = self._posta(squadra)
        return sp.frase_obiettivi(dati, dati["giocate"], self.CAMP)

    def test_le_havre_e_ultima_e_retrocede_direttamente(self):
        dati = self._posta("Le Havre")
        self.assertEqual(self.n_squadre, dati["pos"], "Le Havre e' ultima")
        self.assertTrue(dati["ultime_due"])
        self.assertFalse(dati["spareggio"])
        # La salvezza e' la terzultima (16ª di 18): 6 - 2 = 4 punti.
        self.assertEqual(16, dati["pos_salvezza"])
        self.assertEqual(4, dati["dalla_salvezza"])
        self.assertEqual(self._frase("Le Havre"),
                         "In zona retrocessione diretta: 4 punti dalla salvezza.")
        self.assertNotIn("spareggio", self._frase("Le Havre"))

    def test_auxerre_e_terzultima_e_gioca_lo_spareggio(self):
        dati = self._posta("Auxerre")
        self.assertEqual(self.n_squadre - 2, dati["pos"], "Auxerre e' terzultima")
        self.assertTrue(dati["spareggio"])
        self.assertFalse(dati["ultime_due"])
        frase = self._frase("Auxerre")
        self.assertEqual(frase, "Spareggio: terzultima, 2 punti sopra "
                                "la retrocessione diretta.")
        self.assertIn("retrocessione diretta", frase)

    def test_la_nota_spareggio_non_esce_dalla_terzultima(self):
        # La penultima (Troyes) prende la frase della retrocessione diretta:
        # la nota dello spareggio non e' un avviso di zona.
        penultima = self._posta("Troyes")
        self.assertEqual(self.n_squadre - 1, penultima["pos"])
        self.assertTrue(penultima["ultime_due"])
        self.assertFalse(penultima["spareggio"])
        self.assertNotIn("spareggio", self._frase("Troyes"))
        # Nessuna delle altre squadre di mezzo porta la nota.
        for riga in self.classifica:
            if riga["squadra"] in ("Auxerre",):
                continue
            with self.subTest(squadra=riga["squadra"]):
                dati = sp.posta_in_palio(self.classifica, self.CAMP,
                                         riga["squadra"], self.n_squadre)
                self.assertNotIn("spareggio",
                                 sp.frase_obiettivi(dati, dati["giocate"], self.CAMP))

    def test_le_distanze_sono_quelle_del_conteggio_indipendente(self):
        """Punti e posizione di Le Havre e Auxerre rifatti a mano nel test."""
        tabelle = classifica_contata_a_mano(self.file, self.STAGIONE)
        ordinate = sorted(tabelle.items(),
                          key=lambda kv: (-kv[1]["punti"], -(kv[1]["gf"] - kv[1]["gs"]),
                                          -kv[1]["gf"], kv[0]))
        for squadra, pos_attesa in (("Le Havre", self.n_squadre), ("Auxerre", 16)):
            with self.subTest(squadra=squadra):
                pos = next(i for i, (nome, _) in enumerate(ordinate, start=1)
                           if nome == squadra)
                self.assertEqual(pos_attesa, pos)
                dati = self._posta(squadra)
                self.assertEqual(tabelle[squadra]["punti"], dati["punti"])
                self.assertEqual(tabelle[squadra]["giocate"], dati["giocate"])
                self.assertEqual(sp.giornate_totali(self.n_squadre) - dati["giocate"],
                                 dati["giornate_rimaste"])


class TestFasceEloENonLeakage(unittest.TestCase):
    """Forma, fasce dell'avversario e non-leakage dell'Elo."""

    @classmethod
    def setUpClass(cls):
        cls.risultati = sp.carica_risultati_stagione(CAMP)
        if cls.risultati.empty:
            raise unittest.SkipTest("nessun risultato della stagione in corso")
        cls.df_completo = _df_per_motore(cls.risultati)

    def _storico(self, df: pd.DataFrame) -> dict:
        engine = _EngineDaDataFrame(CAMP, df)
        engine.compute_ratings()
        return sp.storico_elo_da_engine(engine)

    def test_fasce_terzili(self):
        foto = {f"S{i:02d}": float(100 + i) for i in range(20)}
        fasce = sp.fasce_elo(foto)
        self.assertEqual(len(fasce), 20)
        self.assertEqual(sum(1 for v in fasce.values() if v == "debole"), 7)
        self.assertEqual(sum(1 for v in fasce.values() if v == "forte"), 7)
        self.assertEqual(sum(1 for v in fasce.values() if v == "media"), 6)
        self.assertEqual(fasce["S00"], "debole")
        self.assertEqual(fasce["S19"], "forte")
        self.assertEqual(sp.fasce_elo({"A": 1500.0, "B": 1600.0}), {})
        self.assertEqual(sp.fasce_elo({}), {})

    def test_foto_elo_e_lultimo_rating_prima_della_data(self):
        """Verifica indipendente: la foto e' l'ultimo ``elo_dopo`` precedente."""
        storico = self._storico(self.df_completo)
        data = pd.Timestamp(self.risultati["data"].max()).normalize()
        foto = sp.fotografia_elo(storico, data)
        for squadra, righe in storico.items():
            precedenti = [r for r in righe if r["data"] < data]
            atteso = precedenti[-1]["elo_dopo"] if precedenti else sp.ELO_INIZIALE
            with self.subTest(squadra=squadra):
                self.assertAlmostEqual(foto[squadra], atteso, places=9)
        # La partita giocata proprio in quella data NON entra nella foto.
        giocate_quel_giorno = self.risultati[self.risultati["data"] == data]
        if not giocate_quel_giorno.empty:
            squadra = giocate_quel_giorno.iloc[0]["casa"]
            righe = [r for r in storico[squadra] if r["data"] == data]
            if righe:
                self.assertNotEqual(round(foto[squadra], 6),
                                    round(righe[-1]["elo_dopo"], 6))

    def test_forma_usa_le_fasce_della_fotografia(self):
        storico = self._storico(self.df_completo)
        fotografie = sp.fotografie_delle_date(storico, list(self.risultati["data"]))
        squadra = self.risultati["casa"].iloc[0]
        forma = sp.forma_recente(self.risultati, squadra, fotografie)
        self.assertTrue(forma["partite"])
        self.assertTrue(forma["sufficiente"])
        for p in forma["partite"]:
            foto = fotografie[pd.Timestamp(p["data"]).normalize()]
            atteso = sp.banda_avversario(sp.fasce_elo(foto), p["avversario"])
            self.assertEqual(p["banda_avversario"], atteso)
            self.assertIn(p["banda_avversario"], sp.FASCE_ELO)
        self.assertEqual(forma["vinte"] + forma["pari"] + forma["perse"],
                         len(forma["partite"]))

    def test_cambiare_il_risultato_di_una_partita_futura_non_cambia_il_passato(self):
        """Il caso esplicito della commessa: si riscrive una partita futura."""
        taglio = pd.Timestamp(self.risultati["data"].max()).normalize()
        future = self.df_completo[self.df_completo["Date_Parsed"] >= taglio]
        if future.empty:
            self.skipTest("nessuna partita futura note nel CSV")
        modificato = self.df_completo.copy()
        i = future.index[0]
        modificato.loc[i, "FTHG"], modificato.loc[i, "FTAG"] = 5, 0
        modificato.loc[i, "FTR"] = "H"
        giornata = pd.Timestamp(modificato.loc[i, "Date_Parsed"]).normalize()
        prima = sp.fotografia_elo(self._storico(self.df_completo), giornata)
        dopo = sp.fotografia_elo(self._storico(modificato), giornata)
        self.assertEqual(prima, dopo)
        self.assertEqual(sp.fasce_elo(prima), sp.fasce_elo(dopo))
        # Il test sa riconoscere la frode: DOPO quella data le due storie
        # divergono (altrimenti non starebbe verificando niente).
        fine = pd.Timestamp(self.df_completo["Date_Parsed"].max()) + pd.Timedelta(days=1)
        self.assertNotEqual(sp.fotografia_elo(self._storico(self.df_completo), fine),
                            sp.fotografia_elo(self._storico(modificato), fine))

    def test_forma_reale_dal_motore_di_produzione(self):
        """Il motore vero (cache di produzione) alimenta il blocco forma."""
        storico = sp.storico_elo_da_engine(get_elo_engine(CAMP))
        self.assertTrue(storico)
        fotografie = sp.fotografie_delle_date(storico, list(self.risultati["data"]))
        squadra = self.risultati["casa"].iloc[-1]
        forma = sp.forma_recente(self.risultati, squadra, fotografie)
        self.assertGreaterEqual(forma["n"], len(forma["partite"]))
        self.assertEqual(len(forma["partite"]), min(5, forma["n"]))
        for p in forma["partite"]:
            self.assertIn(p["esito"], ("V", "X", "P"))
            self.assertIn(p["banda_avversario"], sp.FASCE_ELO)


class TestDatiInsufficienti(unittest.TestCase):
    """Il modulo dichiara i dati insufficienti invece di mostrare numeri vuoti."""

    def _risultati_minimi(self) -> pd.DataFrame:
        df = pd.DataFrame(
            [("2026-08-22", "Neopromossa", "Inter", 0, 2),
             ("2026-08-29", "Inter", "Neopromossa", 3, 1)],
            columns=["data", "casa", "trasferta", "gol_casa", "gol_ospiti"])
        df["data"] = pd.to_datetime(df["data"])
        df["giornata"] = [1, 2]
        df["casa_display"] = df["casa"]
        df["trasferta_display"] = df["trasferta"]
        return df

    def test_forma_con_meno_di_tre_partite(self):
        forma = sp.forma_recente(self._risultati_minimi(), "Neopromossa", {})
        self.assertEqual(forma["n"], 2)
        self.assertFalse(forma["sufficiente"])
        self.assertTrue(sp.testo_forma(forma).startswith("Dati insufficienti: solo 2 partite"))

    def test_forma_senza_partite(self):
        vuoto = sp.carica_risultati_stagione(CAMP, stagione=1999)
        forma = sp.forma_recente(vuoto, "Inter", {})
        self.assertEqual(forma["n"], 0)
        self.assertTrue(sp.testo_forma(forma).startswith("Dati insufficienti: nessuna partita"))

    def test_gol_con_meno_di_tre_partite(self):
        gol = sp.statistiche_gol(self._risultati_minimi(), "Neopromossa")
        self.assertFalse(gol["sufficiente"])
        self.assertIsNone(gol["stagione"]["media_fatti"])
        righe = sp.testo_gol(gol)
        self.assertTrue(righe[0].startswith("Dati insufficienti: solo 2 partite"))
        self.assertIn("Partite con entrambe a segno: 1 su 2 partite.", righe)
        self.assertTrue(all("%" not in r for r in righe),
                        "sotto le 5 partite nessuna percentuale")

    def test_gol_senza_partite(self):
        vuoto = sp.carica_risultati_stagione(CAMP, stagione=1999)
        gol = sp.statistiche_gol(vuoto, "Inter")
        self.assertEqual(gol["stagione"]["partite"], 0)
        self.assertTrue(sp.testo_gol(gol)[0].startswith("Dati insufficienti: nessuna partita"))

    def test_percentuale_solo_da_cinque_partite(self):
        self.assertEqual(sp.conteggio_in_parole(1, 2), "1 su 2 partite")
        self.assertEqual(sp.conteggio_in_parole(3, 4), "3 su 4 partite")
        self.assertEqual(sp.conteggio_in_parole(3, 5), "3 su 5 partite (60%)")
        self.assertEqual(sp.conteggio_in_parole(0, 0), "0 su 0 partite")

    def test_classifica_vuota(self):
        self.assertEqual(sp.classifica(pd.DataFrame()), [])
        self.assertIsNone(sp.posta_in_palio([], CAMP, "Inter", 20))

    def test_scheda_senza_risultati_dichiara_i_dati_mancanti(self):
        scheda = sp.costruisci_scheda(CAMP, "Inter", "Roma", risultati=pd.DataFrame(),
                                      storico_elo={})
        self.assertFalse(scheda["risultati_disponibili"])
        blocchi = dict(sp.blocchi_scheda(scheda))
        self.assertIn("Classifica e obiettivi", blocchi)
        self.assertTrue(any("insufficient" in r for r in blocchi["Classifica e obiettivi"]))
        self.assertIn("Dati mancanti", blocchi)
        self.assertEqual(len(blocchi["Dati mancanti"]), 2)  # risultati + rating
        self.assertIn("Quote non ancora disponibili", " ".join(blocchi["Probabilità (dalle quote dei bookmaker)"]))

    def test_precedenti_quando_non_si_sono_ancora_affrontate(self):
        df = self._risultati_minimi()
        self.assertEqual(sp.precedenti_stagionali(df, "Inter", "Milan"), [])
        scheda = sp.costruisci_scheda(CAMP, "Inter", "Milan", risultati=df, storico_elo={})
        righe = dict(sp.blocchi_scheda(scheda))["Precedenti stagionali"]
        self.assertEqual(righe, ["Le due squadre non si sono ancora affrontate in questa stagione."])


class TestQuoteEAbbinamento(unittest.TestCase):
    """Probabilita' dalle quote (snapshot pinnato) e abbinamento delle partite."""

    @classmethod
    def setUpClass(cls):
        cls.snap = snap_test.snapshot_reale()
        if cls.snap is None:
            raise unittest.SkipTest("snapshot pinnato non raggiungibile (clone shallow?)")
        cls.eventi = [e for e in mo.eventi_quote(cls.snap) if e.get("libri")]
        if not cls.eventi:
            raise unittest.SkipTest("snapshot senza eventi con quote")

    def test_evento_e_probabilita_dalla_stessa_fonte(self):
        evento = self.eventi[0]
        prob = sp.probabilita_di(evento)
        atteso = mo.probabilita_mercato(evento["libri"])
        self.assertTrue(prob["disponibile"])
        for esito in ("1", "X", "2"):
            self.assertAlmostEqual(prob["quote"][esito], atteso["probs"][esito], places=12)
        # La percentuale mostrata e' la stessa di "Quote %" delle tabelle (1 cifra)
        self.assertEqual(sp.percento_una_cifra(prob["quote"]["1"]),
                         round(atteso["probs"]["1"] * 100.0, 1))

    def test_evento_senza_libri_non_inventa_numeri(self):
        prob = sp.probabilita_di({"home_team": "A", "away_team": "B", "libri": []})
        self.assertFalse(prob["disponibile"])
        self.assertIsNone(prob["quote"])
        self.assertEqual(sp.probabilita_in_parole(None, "A", "B"), sp.FRASE_QUOTE_ASSENTI)

    def test_probabilita_in_parole(self):
        prob = {"disponibile": True, "quote": {"1": 0.45, "X": 0.28, "2": 0.27}}
        self.assertEqual(sp.probabilita_in_parole(prob["quote"], "Inter", "Roma"),
                         "Vince Inter 45,0% · Pareggio 28,0% · Vince Roma 27,0%")
        self.assertEqual(sp.probabilita_in_parole({"1": 0.45, "X": None, "2": 0.27},
                                                 "Inter", "Roma"),
                         sp.FRASE_QUOTE_ASSENTI)

    def test_modello_per_esito(self):
        mappa = {("Inter", "Roma"): {"1": 52.3, "X": 24.0, "2": 23.7}}
        self.assertEqual(sp.modello_per_esito(mappa, "Inter", "Roma", "1"), 52.3)
        self.assertEqual(sp.modello_per_esito(mappa, "Inter", "Roma", "2"), 23.7)
        self.assertIsNone(sp.modello_per_esito(mappa, "Roma", "Inter", "1"))
        self.assertIsNone(sp.modello_per_esito(None, "Inter", "Roma", "1"))
        # Una lista al posto della mappa non e' una terna: nessun numero inventato.
        self.assertIsNone(sp.modello_per_esito([{"1": 50.0}], "Inter", "Roma", "1"))

    def test_abbina_partite_sullo_snapshot(self):
        per_lega = {}
        for lega in ("Serie A", "Premier League", "La Liga", "Bundesliga", "Ligue 1"):
            ris = sp.carica_risultati_stagione(lega)
            per_lega[lega] = set(ris["casa"]) | set(ris["trasferta"])
        abb = sp.abbina_partite(self.snap, ADESSO, per_lega)
        self.assertGreater(abb["n"], 0)
        self.assertEqual(abb["n"], abb["n_abbinate"] + abb["n_non_abbinate"])
        self.assertEqual(abb["n"], len(abb["tutte"]))
        # Snapshot pinnato + roster della stagione: nessuna partita in
        # programma resta senza corrispondenza (il numero sta nel referto).
        self.assertEqual(abb["n_non_abbinate"], 0, abb["non_abbinate"])
        for p in abb["partite"]:
            self.assertTrue(p["abbinata"])
            self.assertIsNone(p["motivo"])
            self.assertGreater(p["kickoff_utc"], ADESSO.strftime("%Y-%m-%dT%H:%M:%SZ"))
            self.assertIn(p["lega"], per_lega)
            self.assertIn(",", p["quando"])  # data e ora italiane

    def test_partita_senza_corrispondenza_viene_elencata(self):
        payload = {"leghe": {"Serie A": {"eventi": [
            {"id": "x1", "commence_time": "2026-10-17T18:00:00Z",
             "home_team": "Squadra Inventata", "away_team": "Inter"},
            {"id": "x2", "commence_time": "2026-10-17T20:00:00Z",
             "home_team": "Bologna", "away_team": "Inter"},
        ]}}}
        abb = sp.abbina_partite(payload, ADESSO, {"Serie A": {"Bologna", "Inter"}})
        self.assertEqual(abb["n"], 2)
        self.assertEqual(abb["n_non_abbinate"], 1)
        mancante = abb["non_abbinate"][0]
        self.assertEqual(mancante["casa"], "Squadra Inventata")
        self.assertEqual(mancante["motivo"], "nome squadra non riconosciuto")
        self.assertTrue(abb["partite"][0]["abbinata"])

    def test_squadra_fuori_dai_risultati_viene_elencata(self):
        payload = {"leghe": {"Serie A": {"eventi": [
            {"id": "y1", "commence_time": "2026-10-18T18:00:00Z",
             "home_team": "Bologna", "away_team": "Inter"},
        ]}}}
        abb = sp.abbina_partite(payload, ADESSO, {"Serie A": {"Inter"}})
        self.assertEqual(abb["n_non_abbinate"], 1)
        self.assertEqual(abb["non_abbinate"][0]["motivo"],
                         "squadra fuori dai risultati della lega")

    def test_righe_partite_giornata_con_e_senza_quote(self):
        evento = self.eventi[0]
        matches = [
            {"lega": evento["lega"], "casa": evento["home_team"],
             "trasferta": evento["away_team"], "utcDate": evento["commence_time"]},
            {"lega": "Serie A", "casa": "Inter", "trasferta": "Monza",
             "utcDate": "2027-05-01T15:00:00Z"},
        ]
        righe = sp.righe_partite_giornata(matches, self.snap, ADESSO)
        self.assertEqual(len(righe), 2)
        self.assertIn("Vince", righe[0]["in_parole"])
        self.assertEqual(righe[1]["in_parole"], sp.FRASE_QUOTE_ASSENTI)
        for r in righe:
            self.assertIn(",", r["quando"])  # data e ora italiane
        # Una quota di un'altra lega non viene usata per questa partita.
        righe_sbagliate = sp.righe_partite_giornata(
            [{"lega": "Bundesliga", "casa": evento["home_team"],
              "trasferta": evento["away_team"], "utcDate": evento["commence_time"]}],
            self.snap, ADESSO)
        if evento["lega"] != "Bundesliga":
            self.assertEqual(righe_sbagliate[0]["in_parole"], sp.FRASE_QUOTE_ASSENTI)


class TestSchedaCompleta(unittest.TestCase):
    """La scheda intera su una partita vera dello snapshot pinnato."""

    @classmethod
    def setUpClass(cls):
        cls.snap = snap_test.snapshot_reale()
        if cls.snap is None:
            raise unittest.SkipTest("snapshot pinnato non raggiungibile (clone shallow?)")
        cls.risultati = sp.carica_risultati_stagione(CAMP)
        if cls.risultati.empty:
            raise unittest.SkipTest("nessun risultato della stagione in corso")
        cls.evento = sp.evento_di(cls.snap, "Bologna", "Inter")
        if cls.evento is None:
            raise unittest.SkipTest("Bologna-Inter non e' nello snapshot pinnato")

    @classmethod
    def _storico_di_prova(cls) -> dict:
        engine = _EngineDaDataFrame(CAMP, _df_per_motore(cls.risultati))
        engine.compute_ratings()
        return sp.storico_elo_da_engine(engine)

    def _scheda(self, casa, trasferta):
        evento = sp.evento_di(self.snap, casa, trasferta)
        return sp.costruisci_scheda(CAMP, casa, trasferta,
                                    kickoff_utc=(evento or {}).get("commence_time"),
                                    evento_quote=evento, risultati=self.risultati,
                                    storico_elo=self._storico_di_prova())

    def test_blocchi_e_righe_coerenti(self):
        scheda = self._scheda("Bologna", "Inter")
        blocchi = dict(sp.blocchi_scheda(scheda))
        for titolo in ("Probabilità (dalle quote dei bookmaker)", "Classifica e obiettivi",
                       "Forma: ultime 5 partite di campionato", "Gol",
                       "Precedenti stagionali"):
            self.assertIn(titolo, blocchi)
        testo = sp.testo_scheda(scheda)
        self.assertIn("Bologna - Inter", testo)
        self.assertIn("Quote %", testo)
        self.assertIn(scheda["classifica"]["casa"]["frase"], testo)
        self.assertIn(scheda["classifica"]["trasferta"]["frase"], testo)

    def test_probabilita_e_forma_sono_quelle_dei_dati(self):
        scheda = self._scheda("Bologna", "Inter")
        prob = scheda["probabilita"]
        self.assertTrue(prob["disponibile"])
        atteso = mo.probabilita_mercato(self.evento["libri"])["probs"]
        for esito in ("1", "X", "2"):
            self.assertAlmostEqual(prob["quote"][esito], atteso[esito], places=12)
        forma = scheda["forma"]["casa"]
        self.assertEqual(sum(1 for p in forma["partite"] if p["esito"] == "V"),
                         forma["vinte"])
        # Il "Modello %" non c'e' (nessuna mappa passata): non si inventa.
        self.assertFalse(prob["modello_disponibile"])
        self.assertTrue(all(v is None for v in prob["modello"].values()))

    def test_modello_per_esito_nella_scheda(self):
        mappa = {("Bologna", "Inter"): {"1": 17.0, "X": 25.0, "2": 58.0}}
        scheda = sp.costruisci_scheda(CAMP, "Bologna", "Inter",
                                      evento_quote=self.evento, modello_1x2=mappa,
                                      risultati=self.risultati,
                                      storico_elo=self._storico_di_prova())
        self.assertTrue(scheda["probabilita"]["modello_disponibile"])
        self.assertEqual(scheda["probabilita"]["modello"]["2"], 58.0)
        righe = dict(sp.blocchi_scheda(scheda))["Probabilità (dalle quote dei bookmaker)"]
        # Come nelle tabelle di «Giocate»: la sigla e i due NUMERI, senza
        # parentesi e senza il simbolo % (sta nelle voci «Quote %»/«Modello %»).
        self.assertTrue(any(r.startswith("2 · Quote % ") and " · Modello % 58,0" in r
                            for r in righe), righe)
        for r, sigla in zip(righe, ("1", "X", "2")):
            with self.subTest(riga=r):
                self.assertTrue(r.startswith(sigla + " · Quote % "), r)
                self.assertNotIn("(", r)
                self.assertIsNone(re.search(r"\d\s?%", r),
                                  f"la percentuale resta un numero, senza simbolo: {r!r}")

    def test_precedenti_stagionali_se_gia_giocata(self):
        riga = self.risultati.iloc[0]
        scheda = self._scheda(riga["casa_display"], riga["trasferta_display"])
        precedenti = scheda["precedenti"]
        self.assertTrue(precedenti)
        self.assertEqual(precedenti[0]["casa"], riga["casa"])
        self.assertIn(precedenti[0]["risultato"], sp.testo_scheda(scheda))

    def test_nessuna_rete_e_nessun_ricalcolo(self):
        """La scheda non tocca la rete e non ricalcola quote: dati passati a mano."""
        scheda = sp.costruisci_scheda(CAMP, "Bologna", "Inter",
                                      evento_quote=self.evento,
                                      risultati=self.risultati, storico_elo={})
        self.assertEqual(scheda["versione"], sp.SCHEDA_PARTITA_VERSION)
        self.assertTrue(scheda["lega"] == CAMP)
        self.assertIn("Bologna", scheda["casa"]["nome"])
        self.assertFalse(scheda["elo_disponibile"])
        righe = dict(sp.blocchi_scheda(scheda))["Forma: ultime 5 partite di campionato"]
        self.assertTrue(any("fascia non disponibile" in r for r in righe))


if __name__ == "__main__":
    unittest.main(verbosity=2)
