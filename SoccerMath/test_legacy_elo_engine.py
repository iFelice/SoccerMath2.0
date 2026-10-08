"""Provenienza e isolamento del motore Elo LEGACY (pre-PR#24).

Il Top Mix a due tabelle calcola il modello legacy con
``models/elo_engine_legacy.py``. Quel file deve essere il codice di produzione
di PRIMA del fix, non una ricostruzione: questi test lo dimostrano.

* ``TestProvenienzaVerbatim``: l'hash del blob git del file (ricalcolato in
  Python, senza git) e' ``784cecc9...``, cioe' l'oggetto che ``main`` aveva in
  ``SoccerMath/models/elo_engine.py`` fino ad ``a435436`` (ultimo commit
  prima del fix ``980e048``, merge PR#24 ``626cd0b``). Con un clone completo
  si chiede conferma anche a git.
* ``TestUnicaDifferenza``: il diff fra motore legacy e attuale e' SOLO il
  boost xG retroattivo di ``compute_ratings`` (import di ``get_understat_xg``,
  ``xg_data``, ``xg_adj``, ``xg_elo_boost`` in ``dr``) PIU' l'estrazione
  puramente strutturale di ``elo_probs_from_ratings`` (PR #30), che il file
  legacy non puo' ricevere perche' e' congelato verbatim al blob
  ``784cecc9...``. L'estrazione non cambia numeri: la condizione
  ``predict_elo_probs identica nei due motori``, che prima era un confronto di
  testo, e' ora verificata (a) come testo sulla forma delegante attesa e
  (b) come IDENTITA' NUMERICA bit-exact fra i due moduli su una griglia di
  rating e home advantage.
* ``TestConvivenza``: i due moduli hanno cache separate e danno probabilita'
  diverse sugli stessi dati (se le medie xG ci sono: senza, il boost e' 0 e i
  due motori coincidono per costruzione).
"""
from __future__ import annotations

import ast
import contextlib
from pathlib import Path
import difflib
import os
import subprocess
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402

import config as PROD_CONFIG  # noqa: E402

from models import legacy_elo as L  # noqa: E402
from models.elo_engine import PROMOTED_SEED_OFFSET  # noqa: E402

LEGACY_PATH = L.LEGACY_ELO_ENGINE_FILE
CURRENT_PATH = os.path.join(HERE, "models", "elo_engine.py")


def _git(*args):
    try:
        r = subprocess.run(["git", "-C", REPO_ROOT, *args], capture_output=True,
                           text=True, timeout=30)
    except Exception:
        return None
    return r.stdout if r.returncode == 0 else None


class TestProvenienzaVerbatim(unittest.TestCase):
    def test_blob_sha_ricalcolato_in_python(self):
        self.assertEqual(L.git_blob_sha(LEGACY_PATH), L.LEGACY_ELO_BLOB_SHA)
        self.assertTrue(L.legacy_engine_is_verbatim())

    def _clone_completo(self) -> bool:
        return (_git("rev-parse", "--is-shallow-repository") or "").strip() == "false"

    def test_git_conferma_che_e_il_file_pre_fix(self):
        """Il legacy e' VERBATIM, e questo non dipende dal clone.

        L'hash git del file lo ricalcola ``legacy_elo.git_blob_sha`` in Python:
        se e' uguale al blob dichiarato, il file non e' cambiato di un byte.
        Il confronto con l'oggetto nello store di git e' una seconda conferma
        sullo stesso file: in un clone completo e' OBBLIGATORIO, in un clone
        superficiale non puo' essere eseguito e non e' un test che si salta.
        """
        with open(LEGACY_PATH, encoding="utf-8") as f:
            contenuto = f.read()
        self.assertEqual(L.git_blob_sha(LEGACY_PATH), L.LEGACY_ELO_BLOB_SHA)
        self.assertTrue(L.legacy_engine_is_verbatim())
        if self._clone_completo():
            atteso = _git("rev-parse",
                          f"{L.LEGACY_ELO_SOURCE_COMMIT}:{L.LEGACY_ELO_SOURCE_PATH}")
            self.assertIsNotNone(atteso, "clone completo senza l'oggetto dichiarato")
            self.assertEqual(atteso.strip(), L.LEGACY_ELO_BLOB_SHA)
            self.assertEqual(_git("cat-file", "-p", L.LEGACY_ELO_BLOB_SHA), contenuto)

    def test_git_conferma_il_commit_che_lo_ha_sostituito(self):
        """Quando il clone e' completo, anche la cronologia e' obbligatoria."""
        log = _git("log", "--format=%H %cI", "-1", L.LEGACY_ELO_REPLACED_BY_COMMIT)
        if not self._clone_completo():
            # Senza cronologia non c'e' nulla da confrontare: l'integrita' del
            # file e' gia' asserita sopra e non dipende da git.
            self.assertIsNone(log)
            return
        self.assertIsNotNone(log, "clone completo senza il commit dichiarato")
        sha, quando = log.split()
        self.assertEqual(sha, L.LEGACY_ELO_REPLACED_BY_COMMIT)
        self.assertTrue(quando.startswith("2026-09-18T21:39:23"), quando)
        # Il blob del commit di fix e' gia' quello attuale, non piu' il legacy.
        dopo = _git("rev-parse", f"{L.LEGACY_ELO_REPLACED_BY_COMMIT}:{L.LEGACY_ELO_SOURCE_PATH}")
        self.assertIsNotNone(dopo)
        self.assertNotEqual(dopo.strip(), L.LEGACY_ELO_BLOB_SHA)
        # ... e il primo genitore della merge PR#24 e' proprio il commit sorgente.
        genitore = _git("rev-parse", f"{L.LEGACY_ELO_MERGE_COMMIT}^1")
        if genitore:
            self.assertEqual(genitore.strip(), L.LEGACY_ELO_SOURCE_COMMIT)


def _senza_docstring(src: str, nome_funzione: str) -> str:
    """Sorgente con le righe del docstring di ``nome_funzione`` rimosse.

    Serve al diff testuale: il docstring della funzione estratta (PR #30)
    documenta la formula ed e' lungo; pinnarlo riga per riga in questo test
    lo renderebbe un duplicato della documentazione. Il CODICE resta pinnato
    integralmente.
    """
    albero = ast.parse(src)
    righe = src.splitlines()
    for node in albero.body:
        if isinstance(node, ast.FunctionDef) and node.name == nome_funzione:
            doc = node.body[0] if node.body else None
            if (isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant)
                    and isinstance(doc.value.value, str)):
                return "\n".join(righe[:doc.lineno - 1] + righe[doc.end_lineno:])
            return src
    raise AssertionError(nome_funzione)


class TestUnicaDifferenza(unittest.TestCase):
    #: righe presenti SOLO nel legacy (boost xG) o spostate dal refactor PR #30
    RIMOSSE_ATTESE = [
        'from typing import Dict, List',
        'from scraper_xg import get_understat_xg',
        'def __init__(self, league_name: str, home_adv: float = None, base_k: float = BASE_K_FACTOR):',
        'xg_data = get_understat_xg(self.league_name) or {}',
        'xg_adj = 0.0',
        'if xg_data and h_team in xg_data and a_team in xg_data:',
        'h_xg = xg_data[h_team].get("xG_avg", 1.3)',
        'h_xga = xg_data[h_team].get("xGA_avg", 1.3)',
        'a_xg = xg_data[a_team].get("xG_avg", 1.3)',
        'a_xga = xg_data[a_team].get("xGA_avg", 1.3)',
        'xg_adj = ((h_xg - h_xga) - (a_xg - a_xga)) * 0.15',
        '',
        'xg_elo_boost = max(-100, min(100, xg_adj * 400))',
        'dr = r_h + self.home_adv - r_a + xg_elo_boost',
        'def predict_elo_probs(home_team: str, away_team: str, league_name: str) -> dict:',
        'engine = get_elo_engine(league_name)',
        'h_cl = clean_name(home_team)',
        'a_cl = clean_name(away_team)',
        'r_h = engine.ratings.get(h_cl, DEFAULT_INITIAL_RATING)',
        'r_a = engine.ratings.get(a_cl, DEFAULT_INITIAL_RATING)',
        'dr = r_h + engine.home_adv - r_a',
        '"elo_diff": round(dr, 1), "home_adv": engine.home_adv,',
    ]
    #: righe presenti SOLO nell'attuale (docstring della funzione pura escluso).
    #:
    #: La lista e' stata aggiornata dalla PR che adotta il seeding S3 degli
    #: ingressi in lega (media delle attive - 100). Le righe nuove sono
    #: esattamente e soltanto quelle di QUELLA modifica: l'import di
    #: ``season_start_year_of``, la costante ``PROMOTED_SEED_OFFSET`` con il
    #: suo commento che cita la PR #35, i due attributi di stato degli ingressi,
    #: i metodi ``_is_entry`` e ``promoted_seed``, i tre passaggi dentro
    #: ``compute_ratings`` e i tre del ramo di predizione. Nessuna riga delle
    #: precedenti (l'estrazione di ``elo_probs_from_ratings``) e' cambiata o
    #: sparita, e nessuna riga NUOVA e' stata esclusa dalla lista: i docstring
    #: dei due metodi nuovi sono pinnati come tutto il resto del codice.
    #:
    #: La lista e' stata aggiornata una seconda volta dalla PR che rende il
    #: roster disponibile fin da prima della prima giornata
    #: (``season_rosters_with_file``): le righe nuove sono esattamente e
    #: soltanto quelle di QUELLA modifica (import di
    #: ``get_current_season_start_year`` e ``load_league_rosters``, funzione
    #: ``season_rosters_with_file`` col suo docstring, e in ``compute_ratings``
    #: la chiamata a ``season_rosters_with_file`` al posto di
    #: ``season_rosters_from_matches``). Nessuna riga precedente e' cambiata o
    #: sparita: ``predict_elo_probs``, il seeding, K, home advantage e la
    #: conversione 1X2 restano quelli pinnati sopra.
    #:
    #: La lista e' stata aggiornata una terza volta dalla PR che toglie il
    #: fallback silenzioso sui nomi squadra: in ``predict_elo_probs`` il seed
    #: d'ingresso e' solo per le VERE entranti (nome pulito in R(stagione)) e
    #: un nome fuori roster solleva ``EloSeedError`` col nome grezzo e quello
    #: pulito. Le righe nuove sono la coda del docstring della funzione e il
    #: ramo di controllo sul roster; nulla di K, home advantage, draw, blend,
    #: ``promoted_seed`` o ``compute_ratings``.
    AGGIUNTE_ATTESE = [
        'from typing import Dict, List, Optional',
        'get_current_season_start_year,',
        'season_start_year_of,',
        '',
        'from season_rosters import load_league_rosters',
        '',
        '#: Distacco applicato al seeding delle squadre che ENTRANO in una lega.',
        '#:',
        '#: La PR #35 (audit ``audit/elo_drift_triage.py``, variante ``S3``) ha',
        '#: misurato la deriva dei rating di ingresso: la produzione partiva da 1500',
        '#: per le neopromosse mai viste e riprendeva il rating stantio per quelle di',
        "#: ritorno, restando cosi' ~100 punti sopra la media delle squadre attive al",
        "#: momento del loro esordio in lega. Il seeding S3 e' la media dei rating",
        "#: delle squadre ATTIVE in quel momento (cioe' di quelle che hanno gia'",
        "#: disputato almeno una partita in lega, nell'ordine di produzione) piu'",
        '#: questo offset; il triage lo ha validato su 55 ingressi in 5 leghe',
        '#: (DeltaLogLoss -0.018010 sulle prime 10 partite delle neopromosse).',
        '#:',
        "#: Non e' un parametro stimato: e' la costante dichiarata dalla variante S3",
        "#: dell'audit, replicata qui senza modificarla. Nessun altro pezzo del motore",
        "#: e' stato toccato: K, home advantage, moltiplicatore di scarto, draw e pesi",
        '#: del blend restano quelli di prima.',
        'PROMOTED_SEED_OFFSET = -100.0',
        '',
        '',
        'class EloSeedError(RuntimeError):',
        '"""Il seed di un ingresso non e\' ricavabile senza guardare il futuro.',
        '',
        "Non e' un'eccezione da silenziare: ogni percorso di produzione che la",
        'intercetta deve degradare in modo DICHIARATO (``elo_disponibile = False``',
        "piu' un WARNING nel log) e non ripiegare su ``DEFAULT_INITIAL_RATING``.",
        "Il fallback silenzioso e' il difetto che questa eccezione sostituisce:",
        "1500 e' un numero plausibile, quindi un roster assente o una stagione non",
        'dichiarata Sparirebbero dentro il risultato senza lasciare traccia, e la',
        "previsione sembrerebbe normale mentre il riferimento e' inventato.",
        '',
        'Unico fallback ammesso: ``DEFAULT_INITIAL_RATING`` per la PRIMA stagione',
        "del database, che non ha stagione precedente ed e' il burn-in dichiarato.",
        '"""',
        '',
        '',
        'def season_rosters_from_matches(df: pd.DataFrame) -> Dict[int, set]:',
        '"""R(lega, stagione) = le squadre che compongono la lega in quella stagione.',
        '',
        "FONTE: il calendario della stagione, cioe' l'insieme delle squadre che",
        "compaiono nelle partite di quell'anno nei CSV di questa lega. Non e' un",
        'risultato: promozioni e retrocessioni sono decise e pubblicate prima del',
        "via, e il calendario della stagione e' pubblicato prima del via. Per la",
        "stagione in corso la stessa fonte e' il file ``*_Live.csv``, che l'app usa",
        'anche per le partite in programma.',
        '',
        "``season_rosters`` puo' essere passato al costruttore quando il database",
        'non contiene il calendario completo (per esempio un backtest su CSV',
        'troncati): il caller passa allora il roster della stagione integrale,',
        "cosi' il riferimento del seed non dipende da quanto DB e' stato tagliato.",
        '"""',
        'out: Dict[int, set] = {}',
        'stagioni = df["Date_Parsed"].map(season_start_year_of)',
        'for season, blocco in df.groupby(stagioni.to_numpy()):',
        'squadre = set(blocco["HomeClean"].unique()).union(',
        'set(blocco["AwayClean"].unique()))',
        'out[int(season)] = {str(t) for t in squadre}',
        'return out',
        '',
        '',
        'def season_rosters_with_file(league_name: str, df: pd.DataFrame) -> Dict[int, set]:',
        '"""R(lega, stagione) dal file roster dove presente, altrimenti dalle giocate.',
        '',
        'Precedenza, stagione per stagione: il file versionato',
        '``database/season_rosters.json`` (input offline e deterministico, salvato',
        "da ``update_db.py`` dal calendario COMPLETO dell'API prima dello scarto",
        'delle non giocate) vince sempre dove ha una voce; dove non ne ha, le',
        'stagioni concluse ricadono sulle partite giocate come prima, mentre la',
        'stagione CORRENTE resta senza roster e il seed solleva ``EloSeedError``',
        'come oggi. La corrente non si ricava mai dalle giocate: a inizio stagione,',
        "con poche partite disputate, l'insieme delle squadre viste sarebbe un",
        'sottoinsieme del campionato e il riferimento del seed sarebbe sbagliato.',
        '"""',
        'giocate = season_rosters_from_matches(df)',
        'try:',
        'schedario = load_league_rosters(league_name)',
        'except Exception:',
        'schedario = {}',
        'corrente = get_current_season_start_year()',
        'out = {s: set(t) for s, t in giocate.items() if s != corrente}',
        'for stagione, squadre in schedario.items():',
        'out[int(stagione)] = {str(t) for t in squadre}',
        'return out',
        'def __init__(self, league_name: str, home_adv: float = None,',
        'base_k: float = BASE_K_FACTOR,',
        'season_rosters: Dict[int, set] | None = None):',
        "# Seeding degli ingressi in lega (PR #35): stagione dell'ultima partita",
        '# disputata da ciascuna squadra e stagione della prima partita del',
        '# database, che resta il burn-in e non genera ingressi.',
        'self.entry_season: Dict[str, int] = {}',
        'self.first_season: Optional[int] = None',
        '#: Stato dei rating degli INCUMBENT al BEGINNING of the day being',
        '#: processed, taken before any match of that day. The seed of an entry',
        '#: reads this and nothing else, so it cannot depend on the order of the',
        '#: matches of the same date nor on results not yet available at kickoff.',
        '#: Season the snapshot belongs to, and the rule that defines the set.',
        'self._day_start_state: Dict[str, float] = {}',
        'self._day_start_season: Optional[int] = None',
        '#: R(lega, stagione): composizione del campionato, dal calendario.',
        '#: Se non passata viene ricavata dal database caricato.',
        'self.season_rosters: Dict[int, set] = {}',
        '#: Roster passato esplicitamente dal chiamante (backtest su DB',
        '#: troncati): se None si ricava dal database caricato.',
        'self._season_rosters_input = season_rosters',
        '#: I(lega, stagione): le squadre di R che hanno giocato in questa lega',
        "#: anche nella stagione precedente. E' l'insieme di riferimento del",
        "#: seed ed e' FISSO per tutta la stagione.",
        'self.incumbents: Dict[int, tuple] = {}',
        '',
        'def _is_entry(self, team: str, season: int) -> bool:',
        '"""La squadra ``team`` sta giocando la sua prima partita in lega?',
        '',
        'Ingresso = MAI VISTA (nessuna partita precedente in questa lega) oppure',
        "DI RITORNO dopo una o piu' stagioni di assenza: nell'ordine di",
        'produzione, ``season_start_year_of`` della partita corrente meno la',
        'stagione della sua ultima partita supera 1.',
        '',
        "La prima stagione del database non genera ingressi: e' il burn-in,",
        "l'unica condizione iniziale che il motore ha sempre avuto, e resta a",
        '``DEFAULT_INITIAL_RATING`` come prima della PR #35.',
        '"""',
        'ultima = self.entry_season.get(team)',
        'if ultima is None:',
        'return season > self.first_season',
        'return season - ultima > 1',
        '',
        'def _incumbent(self, season: int) -> tuple:',
        '"""I(lega, stagione): R(s) ∩ R(s−1), in ordine alfabetico.',
        '',
        'Vuota per la prima stagione del database (nessuna stagione',
        "precedente): e' il burn-in, che resta a DEFAULT_INITIAL_RATING.",
        '"""',
        'if season not in self.incumbents:',
        'roster = self.season_rosters.get(season, set())',
        'stagioni = sorted(self.season_rosters)',
        'precedente = [s for s in stagioni if s < season]',
        'prima = set(self.season_rosters[precedente[-1]]) if precedente else set()',
        'self.incumbents[season] = tuple(sorted(roster & prima))',
        'return self.incumbents[season]',
        '',
        'def _snapshot_day_start(self, season: Optional[int] = None) -> None:',
        '"""Fotografa lo stato delle squadre attive PRIMA della giornata.',
        '',
        "``season`` e' la stagione della giornata che sta per essere processata.",
        "Il riferimento del seed e' I(lega, stagione) = R(s) ∩ R(s−1): le",
        "squadre che compongono il campionato in quella stagione e c'erano gia'",
        'nella stagione precedente. Sono una COMPOSIZIONE DEL CALENDARIO, nota',
        'prima del via, non un risultato: vedi ``season_rosters_from_matches``.',
        "Una retrocessa non e' in R(s) e una neo-promossa non e' in R(s−1), per",
        "costruzione nessuna delle due entra nel riferimento. L'insieme e'",
        'fisso per tutta la stagione, i rating dentro cambiano giorno per',
        "giorno: e' per questo che il seed resta indipendente dall'ordine delle",
        'partite della stessa data.',
        '"""',
        'if season is None:',
        'season = self._day_start_season',
        'self._day_start_season = season',
        '# Solo gli INCUMBENT della stagione: sono le squadre che fanno parte',
        "# del campionato e c'erano gia' nella stagione precedente. Una",
        '# neo-promossa o una retrocessa non ci sono per costruzione, e una',
        '# squadra che non ha ancora giocato in stagione porta qui il suo',
        '# rating di fine stagione precedente, senza dover aspettare la sua',
        "# prima partita. L'insieme e' fisso per tutta la stagione: cambia solo",
        '# il rating che in esso si legge.',
        'self._day_start_state = {',
        't: self.ratings[t]',
        'for t in self._incumbent(season)',
        'if t in self.ratings',
        '} if season is not None else {}',
        '',
        'def promoted_seed(self, season: Optional[int] = None) -> float:',
        '"""Rating iniziale di una squadra che entra in lega (PR #35).',
        '',
        "``season`` e' la stagione della partita da prevedere. E' informazione",
        "di CALENDARIO, nota prima del via, quindi non e' look-ahead. **Non e'",
        "opzionale**: con ``season=None`` non si puo' sapere a quale stagione",
        "appartiene la partita successiva, perche' a fine database l'ultimo",
        "giorno processato puo' essere l'ultimo della stagione o un giorno",
        'qualunque in mezzo. Leggere in quel caso lo snapshot di fine database',
        "significa leggere gli incumbent dell'ULTIMA stagione processata: se la",
        "partita e' della stagione dopo il riferimento e' sbagliato, e se il",
        "roster non e' noto il risultato e' un numero inventato che sembra",
        'plausibile. Quindi ``season=None`` solleva ``EloSeedError``.',
        '',
        'Media dei rating delle squadre INCUMBENT al **inizio della data della',
        "partita** — cioe' di quelle che compongono il campionato nella stagione",
        "corrente e c'erano gia' nella stagione precedente, con i rating che",
        'avevano in quel momento (per chi non ha ancora giocato in stagione',
        "quello di fine stagione precedente) — piu' ``PROMOTED_SEED_OFFSET``.",
        '',
        "Il riferimento si legge da ``self.ratings``, che a quel punto e' gia'",
        'lo stato di inizio della giornata: le partite ancora da giocare non',
        "hanno cambiato nessun rating, quindi nessuna modifica e' necessaria e il",
        "risultato non dipende dall'ordine delle partite della stessa data.",
        '',
        'Anche ``R(s)`` assente o vuoto e ``I(s)`` vuoto sono ``EloSeedError``:',
        "il roster e' la composizione del campionato e non si puo' ricavare",
        'dalle partite giocate, quindi a inizio stagione (nessuna partita',
        "ancora disputata) non e' disponibile. L'unico fallback ammesso e'",
        '``DEFAULT_INITIAL_RATING`` per la prima stagione del database, che non',
        "ha stagione precedente: e' il burn-in dichiarato.",
        '"""',
        'if season is None:',
        'raise EloSeedError(',
        'f"promoted_seed(): season=None non e\' ammesso in "',
        'f"{self.league_name}. Lo snapshot di fine database "',
        'f"(_day_start_state, stagione "',
        'f"{self._day_start_season}) appartiene all\'ULTIMA stagione "',
        'f"processata e non dice a quale stagione appartiene la "',
        'f"partita successiva: passare season esplicitamente."',
        ')',
        'if season not in self.season_rosters:',
        'raise EloSeedError(',
        'f"promoted_seed(): nessun roster per la stagione {season} in "',
        'f"{self.league_name}. Roster conosciuti: "',
        'f"{sorted(self.season_rosters)}."',
        ')',
        'roster = self.season_rosters[season]',
        'if not roster:',
        'raise EloSeedError(',
        'f"promoted_seed(): roster VUOTO per la stagione {season} in "',
        'f"{self.league_name}. R(s) e\' la composizione del campionato: "',
        'f"si ricava dal CALENDARIO, non dalle partite giocate, quindi "',
        'f"a inizio stagione non e\' disponibile da questa fonte."',
        ')',
        'if not [s for s in sorted(self.season_rosters) if s < season]:',
        'if season == self.first_season:',
        '# Prima stagione del database: non ha stagione precedente.',
        "# E' il burn-in dichiarato, l'unica condizione iniziale che il",
        '# motore ha sempre avuto (PR #35 e seguenti).',
        'return DEFAULT_INITIAL_RATING',
        'raise EloSeedError(',
        'f"promoted_seed(): la stagione {season} in "',
        'f"{self.league_name} non ha stagione precedente nel roster e "',
        'f"non e\' la prima stagione del database ({self.first_season}): "',
        'f"il fallback a {DEFAULT_INITIAL_RATING:.0f} e\' dichiarato "',
        'f"solo per il burn-in."',
        ')',
        'incumbent = self._incumbent(season)',
        'if not incumbent:',
        'raise EloSeedError(',
        'f"promoted_seed(): I({season}) = R({season}) ∩ "',
        'f"R(stagione precedente) e\' vuota in {self.league_name}, "',
        'f"|R({season})|={len(roster)}. Il roster della stagione "',
        'f"precedente e\' assente o non e\' quello dell\'anno prima."',
        ')',
        '# Lo stato da cui si legge la media dipende da DOVE siamo:',
        '#',
        '# * ramo storico (``compute_ratings``): lo snapshot congelato di inizio',
        '#   giornata, NON i rating correnti. Se si leggessero i rating correnti',
        '#   il seed cambierebbe a seconda di quante partite della stessa data',
        "#   sono gia' state elaborate, e l'ordine dentro la giornata",
        "#   riporterebbe dentro il seed. Lo snapshot e' della stessa stagione",
        '#   per costruzione: `_snapshot_day_start(season)` viene chiamata al',
        '#   cambio di data, subito prima di qualsiasi partita di quella data.',
        '# * ramo di predizione (``predict_elo_probs``): i rating di fine',
        "#   database, che sono gia' lo stato di inizio della prossima",
        '#   giornata, ristretti a I della stagione richiesta. Se la stagione',
        "#   richiesta e' proprio l'ultima elaborata, il congelato e i rating",
        "#   coincidono; se e' una stagione successiva il congelato non parla",
        '#   di lei e va ricostruito.',
        'if self._day_start_season == season:',
        'stato = self._day_start_state',
        'else:',
        'stato = {t: self.ratings[t] for t in incumbent if t in self.ratings}',
        'if not stato:',
        'raise EloSeedError(',
        'f"promoted_seed(): nessuno dei {len(incumbent)} incumbent di "',
        'f"{self.league_name} nella stagione {season} ha un rating "',
        'f"(snapshot congelato: {len(self._day_start_state)} voci "',
        'f"per la stagione {self._day_start_season}). Non si puo\' "',
        'f"ricavare la media: ripiegare su "',
        'f"{DEFAULT_INITIAL_RATING:.0f} maschererebbe un dato mancante."',
        ')',
        'return float(np.mean([stato[t] for t in sorted(stato)])) + PROMOTED_SEED_OFFSET',
        "# compute_ratings e' un ricalcolo completo: lo stato degli ingressi",
        '# riparte da zero come i rating.',
        'self.entry_season = {}',
        'self._day_start_state = {}',
        'self._day_start_season = None',
        'self.incumbents = {}',
        'roster = self._season_rosters_input',
        'if roster:',
        'self.season_rosters = {int(k): {str(t) for t in v}',
        'for k, v in roster.items()}',
        'else:',
        'self.season_rosters = season_rosters_with_file(self.league_name, df)',
        'self.first_season = season_start_year_of(df["Date_Parsed"].iloc[0])',
        'giorno_corrente = None',
        'season = season_start_year_of(row["Date_Parsed"])',
        '# UN solo snapshot per giornata, preso PRIMA di qualunque sua',
        "# partita: e' lo stato che il seed deve vedere. Le righe sono",
        "# ordinate per data, quindi il cambio di data e' il momento esatto",
        "# in cui congelarlo; dentro la giornata non si tocca piu'.",
        'if pd.Timestamp(row["Date_Parsed"]).normalize() != giorno_corrente:',
        'giorno_corrente = pd.Timestamp(row["Date_Parsed"]).normalize()',
        'self._snapshot_day_start(season)',
        "# Seeding d'ingresso (PR #35). `season` e' passata esplicitamente:",
        "# il riferimento e' I(lega, stagione) della giornata che sta per",
        '# essere processata, non "l\'ultima processata". Se due squadre',
        '# esbordiscono nella stessa partita i seed sono applicati in',
        "# sequenza, in ordine alfabetico di nome: e' l'ordine con cui",
        '# _entry_records elenca gli ingressi e con cui la variante S3',
        "# dell'audit li assegna. Il riferimento letto e' I della stagione e",
        "# non contiene gli ingressi (un ingresso non e' incumbent per",
        "# costruzione), quindi l'ordine serve solo a rendere deterministico",
        '# il risultato float, non a scegliere chi vede chi.',
        'for team in sorted((h_team, a_team)):',
        'if self._is_entry(team, season):',
        'self.ratings[team] = self.promoted_seed(season)',
        'for team in (h_team, a_team):',
        'self.entry_season[team] = season',
        'dr = r_h + self.home_adv - r_a',
        '# Fine database: lo snapshot diventa lo stato di inizio della PROSSIMA',
        "# giornata, cioe' quello che predict_elo_probs usa per una squadra che",
        '# non ha ancora rating in lega. Stessa definizione del ramo storico.',
        'self._snapshot_day_start()',
        'def elo_probs_from_ratings(r_h: float, r_a: float, home_adv: float) -> dict:',
        'dr = r_h + home_adv - r_a',
        '"elo_diff": round(dr, 1), "home_adv": home_adv,',
        '',
        '',
        'def predict_elo_probs(home_team: str, away_team: str, league_name: str,',
        'season: Optional[int] = None) -> dict:',
        '"""1X2 da Elo. ``season`` e\' obbligatoria SOLO se serve il seed.',
        '',
        "Se entrambe le squadre hanno gia' un rating in lega il valore di ``season``",
        'non viene letto: il risultato non dipende dal seed e resta identico a',
        'prima. Se invece una squadra non ha ancora rating (neopromossa non ancora',
        'presente nei CSV, quindi alla sua prima partita) il seed serve, e allora',
        '``season=None`` solleva ``EloSeedError`` invece di ricadere su 1500: il',
        'chiamante di produzione gira dentro un ``try/except`` che segna',
        "``elo_disponibile = False`` e lascia un WARNING, quindi il degrado e'",
        'dichiarato e nessuna previsione viene inventata.',
        '',
        "Il seed d'ingresso resta alle VERE entranti: una squadra senza rating ma",
        'presente in R(lega, stagione) (il calendario, vedi',
        "``season_rosters_with_file``). Un nome pulito che NON e' nel roster della",
        "stagione non e' un ingresso: e' un nome che questa lega non conosce",
        "(errore a monte: alias mancante, shortName dell'API cambiato, lega",
        'sbagliata) e assegnargli la media degli incumbent produrrebbe un numero',
        'plausibile per una squadra inesistente. In quel caso solleva',
        '``EloSeedError`` riportando il nome GREZZO ricevuto e quello PULITO con',
        "cui e' stato cercato il roster: il chiamante degrada in modo dichiarato",
        'invece di pubblicare un seed inventato.',
        '"""',
        'engine = get_elo_engine(league_name)',
        'h_cl = clean_name(home_team)',
        'a_cl = clean_name(away_team)',
        'r_h = engine.ratings.get(h_cl)',
        'r_a = engine.ratings.get(a_cl)',
        '# Squadra senza rating in questa lega = neopromossa alla prima partita e non',
        '# ancora presente nei CSV: si applica lo stesso seeding di compute_ratings',
        "# (media degli incumbent - 100), non DEFAULT_INITIAL_RATING. `season` e' la",
        '# stagione della partita da prevedere (dato di calendario, noto prima del',
        "# via): senza di lei l'ultimo giorno del database non direbbe a quale",
        '# stagione appartiene la partita successiva, e il riferimento letto sarebbe',
        "# quello dell'ultima stagione processata invece di quello giusto.",
        'if r_h is None or r_a is None:',
        'if season is None:',
        'raise EloSeedError(',
        'f"predict_elo_probs({home_team!r}, {away_team!r}, "',
        'f"{league_name!r}): {\'h\' if r_h is None else \'a\'} non ha un "',
        'f"rating in lega, quindi serve il seed di ingresso, che "',
        'f"richiede la stagione della partita. Passare season="',
        'f"esplicitamente: senza, il riferimento sarebbe quello "',
        'f"dell\'ultima stagione processata "',
        'f"({engine._day_start_season}) invece di quello giusto."',
        ')',
        "# Il seed e' solo per le vere entranti: chi non e' in R(stagione) non",
        "# e' un ingresso, e' un nome sconosciuto (errore a monte). Se la",
        '# stagione non ha proprio roster il controllo qui sotto non sa',
        '# dire niente: lo fa poi `promoted_seed`, che in quel caso solleva',
        '# la sua EloSeedError "nessun roster per la stagione".',
        'roster = engine.season_rosters.get(int(season))',
        'if roster is not None:',
        'ignoti = [(lato, grezzo, pulito)',
        'for lato, grezzo, pulito, rating in (',
        '("home", home_team, h_cl, r_h),',
        '("away", away_team, a_cl, r_a))',
        'if rating is None and pulito not in roster]',
        'if ignoti:',
        'dettagli = "; ".join(',
        'f"{lato}: nome grezzo {grezzo!r} -> pulito {pulito!r} "',
        'f"non e\' in R({league_name}, {season})"',
        'for lato, grezzo, pulito in ignoti)',
        'raise EloSeedError(',
        'f"predict_elo_probs({home_team!r}, {away_team!r}, "',
        'f"{league_name!r}, season={season}): nome squadra "',
        'f"sconosciuto, il seed d\'ingresso non si applica a nomi "',
        'f"fuori roster. {dettagli}. Roster noto: "',
        'f"{sorted(roster)}."',
        ')',
        'if r_h is None:',
        'r_h = engine.promoted_seed(season)',
        'if r_a is None:',
        'r_a = engine.promoted_seed(season)',
        'return elo_probs_from_ratings(r_h, r_a, engine.home_adv)',
    ]

    @classmethod
    def setUpClass(cls):
        with open(LEGACY_PATH, encoding="utf-8") as f:
            cls.legacy = f.read()
        with open(CURRENT_PATH, encoding="utf-8") as f:
            cls.current = f.read()

    def test_il_diff_e_solo_il_boost_xg(self):
        corrente = _senza_docstring(self.current, "elo_probs_from_ratings")
        diff = list(difflib.unified_diff(self.legacy.splitlines(), corrente.splitlines(),
                                         lineterm="", n=0))
        rimosse = [l[1:].strip() for l in diff if l.startswith("-") and not l.startswith("---")]
        aggiunte = [l[1:].strip() for l in diff if l.startswith("+") and not l.startswith("+++")]
        self.assertEqual(rimosse, self.RIMOSSE_ATTESE)
        self.assertEqual(aggiunte, self.AGGIUNTE_ATTESE)

    def _fn(self, src, nome):
        for node in ast.parse(src).body:
            if isinstance(node, ast.FunctionDef) and node.name == nome:
                return ast.unparse(node)
        raise AssertionError(nome)

    def test_get_elo_engine_identica_nei_due_motori(self):
        self.assertEqual(self._fn(self.legacy, "get_elo_engine"),
                         self._fn(self.current, "get_elo_engine"))

    def test_predict_elo_probs_attuale_e_sola_delega(self):
        """La versione attuale e' ESATTAMENTE la forma delegante attesa.

        La lista di delegate ammesse e' cambiata dalla PR che adotta il seeding
        S3 degli ingressi in lega: la funzione non puo' piu' delegare con
        ``ratings.get(nome, DEFAULT_INITIAL_RATING)``, perche' una squadra alla
        sua prima partita e non ancora presente nei CSV non ha rating e va
        seminata come in ``compute_ratings`` (media delle attive - 100). Il
        test resta percio' un confronto di testo ESATTO, non un "contains" e
        non un "delegate": ogni riga della funzione resta pinnata. Il confronto
        passa da ``ast.unparse``, che scarta i commenti, quindi i tre commenti
        esplicativi del ramo di fallback non compaiono qui: sono pinnati riga per
        riga in ``AGGIUNTE_ATTESE`` piu' sopra, che lavora sul sorgente grezzo.
        """
        self.assertEqual(
            self._fn(self.current, "predict_elo_probs"),
            'def predict_elo_probs(home_team: str, away_team: str, league_name: str, season: Optional[int]=None) -> dict:\n    """1X2 da Elo. ``season`` e\' obbligatoria SOLO se serve il seed.\n\n    Se entrambe le squadre hanno gia\' un rating in lega il valore di ``season``\n    non viene letto: il risultato non dipende dal seed e resta identico a\n    prima. Se invece una squadra non ha ancora rating (neopromossa non ancora\n    presente nei CSV, quindi alla sua prima partita) il seed serve, e allora\n    ``season=None`` solleva ``EloSeedError`` invece di ricadere su 1500: il\n    chiamante di produzione gira dentro un ``try/except`` che segna\n    ``elo_disponibile = False`` e lascia un WARNING, quindi il degrado e\'\n    dichiarato e nessuna previsione viene inventata.\n\n    Il seed d\'ingresso resta alle VERE entranti: una squadra senza rating ma\n    presente in R(lega, stagione) (il calendario, vedi\n    ``season_rosters_with_file``). Un nome pulito che NON e\' nel roster della\n    stagione non e\' un ingresso: e\' un nome che questa lega non conosce\n    (errore a monte: alias mancante, shortName dell\'API cambiato, lega\n    sbagliata) e assegnargli la media degli incumbent produrrebbe un numero\n    plausibile per una squadra inesistente. In quel caso solleva\n    ``EloSeedError`` riportando il nome GREZZO ricevuto e quello PULITO con\n    cui e\' stato cercato il roster: il chiamante degrada in modo dichiarato\n    invece di pubblicare un seed inventato.\n    """\n    engine = get_elo_engine(league_name)\n    h_cl = clean_name(home_team)\n    a_cl = clean_name(away_team)\n    r_h = engine.ratings.get(h_cl)\n    r_a = engine.ratings.get(a_cl)\n    if r_h is None or r_a is None:\n        if season is None:\n            raise EloSeedError(f"predict_elo_probs({home_team!r}, {away_team!r}, {league_name!r}): {(\'h\' if r_h is None else \'a\')} non ha un rating in lega, quindi serve il seed di ingresso, che richiede la stagione della partita. Passare season=esplicitamente: senza, il riferimento sarebbe quello dell\'ultima stagione processata ({engine._day_start_season}) invece di quello giusto.")\n        roster = engine.season_rosters.get(int(season))\n        if roster is not None:\n            ignoti = [(lato, grezzo, pulito) for lato, grezzo, pulito, rating in ((\'home\', home_team, h_cl, r_h), (\'away\', away_team, a_cl, r_a)) if rating is None and pulito not in roster]\n            if ignoti:\n                dettagli = \'; \'.join((f"{lato}: nome grezzo {grezzo!r} -> pulito {pulito!r} non e\' in R({league_name}, {season})" for lato, grezzo, pulito in ignoti))\n                raise EloSeedError(f"predict_elo_probs({home_team!r}, {away_team!r}, {league_name!r}, season={season}): nome squadra sconosciuto, il seed d\'ingresso non si applica a nomi fuori roster. {dettagli}. Roster noto: {sorted(roster)}.")\n    if r_h is None:\n        r_h = engine.promoted_seed(season)\n    if r_a is None:\n        r_a = engine.promoted_seed(season)\n    return elo_probs_from_ratings(r_h, r_a, engine.home_adv)')

    def test_predict_elo_probs_identica_nei_due_motori_bit_exact(self):
        """Identita' NUMERICA legacy vs attuale: stessi rating, stesso
        home advantage, dizionari bit-identici su tutte le chiavi.

        Sostituisce il vecchio confronto di testo, che il refactor PR #30
        rende strutturalmente impossibile (il legacy e' congelato verbatim).
        """
        import time
        import models.elo_engine as attuale
        import models.elo_engine_legacy as legacy

        class _Stub:
            def __init__(self, ratings, home_adv):
                self.ratings = dict(ratings)
                self.home_adv = home_adv

        lega = "__PARITA_LEGACY__"
        for home_adv in (55.0, 56.0, 58.0, 60.0, 70.0):
            for r_h in range(1200, 1901, 50):
                for r_a in range(1200, 1901, 50):
                    stub_a = _Stub({"CASA": float(r_h), "FUORI": float(r_a)}, home_adv)
                    stub_l = _Stub({"CASA": float(r_h), "FUORI": float(r_a)}, home_adv)
                    attuale._ELO_ENGINES_CACHE[lega] = stub_a
                    attuale._ELO_ENGINES_STAMP[lega] = time.monotonic()
                    legacy._ELO_ENGINES_CACHE[lega] = stub_l
                    legacy._ELO_ENGINES_STAMP[lega] = time.monotonic()
                    try:
                        a = attuale.predict_elo_probs("CASA", "FUORI", lega)
                        b = legacy.predict_elo_probs("CASA", "FUORI", lega)
                    finally:
                        attuale._ELO_ENGINES_CACHE.pop(lega, None)
                        attuale._ELO_ENGINES_STAMP.pop(lega, None)
                        legacy._ELO_ENGINES_CACHE.pop(lega, None)
                        legacy._ELO_ENGINES_STAMP.pop(lega, None)
                    self.assertEqual(sorted(a), sorted(b))
                    for k in a:
                        self.assertEqual(repr(a[k]), repr(b[k]),
                                         f"chiave {k} r_h={r_h} r_a={r_a} ha={home_adv}")

    def test_costanti_identiche(self):
        for nome in ("DEFAULT_INITIAL_RATING", "HOME_ADVANTAGE", "BASE_K_FACTOR",
                     "ELO_ENGINE_TTL_SECONDS"):
            self.assertIn(nome, self.legacy)
            riga_l = next(l for l in self.legacy.splitlines() if l.startswith(nome))
            riga_c = next(l for l in self.current.splitlines() if l.startswith(nome))
            self.assertEqual(riga_l, riga_c)


class TestConvivenza(unittest.TestCase):
    def test_moduli_e_cache_distinti(self):
        import models.elo_engine as attuale
        import models.elo_engine_legacy as legacy
        self.assertIsNot(attuale, legacy)
        self.assertIsNot(attuale._ELO_ENGINES_CACHE, legacy._ELO_ENGINES_CACHE)
        self.assertIs(L.predict_elo_probs_legacy, legacy.predict_elo_probs)
        self.assertIs(L.get_elo_engine_legacy, legacy.get_elo_engine)

    def test_stessi_dati_probabilita_diverse_se_ci_sono_le_medie_xg(self):
        from scraper_xg import get_understat_xg
        from models.elo_engine import predict_elo_probs
        if not get_understat_xg("Serie A"):
            self.skipTest("medie xG assenti: senza boost i due motori coincidono per costruzione")
        L.clear_legacy_elo_cache()
        a = predict_elo_probs("Inter", "Milan", "Serie A")
        b = L.predict_elo_probs_legacy("Inter", "Milan", "Serie A")
        self.assertEqual(set(a), set(b))
        self.assertNotEqual((a["elo_home"], a["elo_away"]), (b["elo_home"], b["elo_away"]))
        # entrambe distribuzioni valide
        for p in (a, b):
            self.assertAlmostEqual(p["1"] + p["X"] + p["2"], 1.0, places=3)
            self.assertEqual(p["home_adv"], a["home_adv"])

PREFIX = PROD_CONFIG.LEAGUES_CONFIG["Serie A"]["db_prefix"]


class TestDifferenzaAttesa(unittest.TestCase):
    """Differenza ATTESA fra legacy e attuale: solo il seed d'ingresso.

    Il legacy resta intatto e resta il riferimento del replay; questa modifica
    cambia il motore corrente in un punto solo e dichiarato. Il test costruisce
    un database sintetico con una neopromossa mai vista e con due squadre che
    ritornano dopo una stagione di assenza, e verifica che:

      * finche' nessuna squadra entra in lega, i due motori sono identici bit
        per bit, non "quasi": stessi float, stesso ``repr``, tutta la stagione
        di burn-in;
      * nel giorno dell'ingresso le altre squadre sono ancora identiche (il
        seed guarda l'inizio della giornata, quindi non ruba niente alla
        giornata stessa);
      * a divergere e' solo la squadra che entra: il legacy la lascia a 1500
        (mai vista) o sul rating stantio (ritorno), l'attuale la mette a
        media delle attive a inizio giornata - 100;
      * due ingressi nella stessa partita prendono lo stesso seed.
    """

    COLONNE = ["HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR", "Date"]
    #: lega e prefisso reali: il loader di file del motore legacy e' lo stesso
    #: di produzione e risolve i CSV dal db_prefix di config
    LEGA = "Serie A"

    STAGIONI = {
        # 2022/23: quattro squadre, burn-in, nessun ingresso
        "2022": [
            {"HomeTeam": "Alfa", "AwayTeam": "Beta", "FTHG": 2, "FTAG": 0, "FTR": "H",
             "Date": "13/08/2022"},
            {"HomeTeam": "Alfa", "AwayTeam": "Gamma", "FTHG": 3, "FTAG": 1, "FTR": "H",
             "Date": "14/08/2022"},
            {"HomeTeam": "Alfa", "AwayTeam": "Delta", "FTHG": 0, "FTAG": 2, "FTR": "A",
             "Date": "15/08/2022"},
            {"HomeTeam": "Beta", "AwayTeam": "Gamma", "FTHG": 1, "FTAG": 1, "FTR": "D",
             "Date": "16/08/2022"},
            {"HomeTeam": "Beta", "AwayTeam": "Delta", "FTHG": 2, "FTAG": 2, "FTR": "D",
             "Date": "17/08/2022"},
            {"HomeTeam": "Gamma", "AwayTeam": "Delta", "FTHG": 3, "FTAG": 0, "FTR": "H",
             "Date": "18/08/2022"},
        ],
        # 2023/24: Beta e Delta assenti, Epsilon non e' mai stata vista.
        # L'ingresso e' il SECONDO giorno di stagione: il primo giorno l'insieme
        # attivo (squadre che hanno gia' giocato nella stagione corrente) e'
        # vuoto e il seed cadrebbe sul fallback dichiarato.
        "2023": [
            {"HomeTeam": "Alfa", "AwayTeam": "Gamma", "FTHG": 1, "FTAG": 1, "FTR": "D",
             "Date": "18/08/2023"},
            {"HomeTeam": "Epsilon", "AwayTeam": "Alfa", "FTHG": 1, "FTAG": 2, "FTR": "A",
             "Date": "19/08/2023"},
        ],
        # 2024/25: Beta e Delta ritornano, nella stessa partita, secondo giorno
        "2024": [
            {"HomeTeam": "Alfa", "AwayTeam": "Gamma", "FTHG": 2, "FTAG": 1, "FTR": "H",
             "Date": "18/08/2024"},
            {"HomeTeam": "Delta", "AwayTeam": "Beta", "FTHG": 0, "FTAG": 3, "FTR": "A",
             "Date": "19/08/2024"},
        ],
    }

    @contextlib.contextmanager
    def _db(self, righe_per_stagione):
        import pandas as pd
        from models import elo_engine as E
        tmp = tempfile.mkdtemp(prefix="elo_legacy_diff_")
        try:
            for stagione, righe in righe_per_stagione.items():
                pd.DataFrame(righe, columns=self.COLONNE).to_csv(
                    Path(tmp) / f"{PREFIX}_{stagione}.csv", index=False)
            self._old = (PROD_CONFIG.DATABASE_DIR,
                         {k: dict(v) for k, v in PROD_CONFIG.LEAGUES_CONFIG.items()})
            PROD_CONFIG.DATABASE_DIR = Path(tmp)
            for k, v in PROD_CONFIG.LEAGUES_CONFIG.items():
                for chiave in ("base_csv", "live_csv", "xg_json"):
                    if v.get(chiave):
                        v[chiave] = str(Path(tmp) / os.path.basename(v[chiave]))
            E._ELO_ENGINES_CACHE.pop(self.LEGA, None)
            E._ELO_ENGINES_STAMP.pop(self.LEGA, None)
            L.clear_legacy_elo_cache()
            yield
        finally:
            PROD_CONFIG.DATABASE_DIR = self._old[0]
            for k, v in PROD_CONFIG.LEAGUES_CONFIG.items():
                PROD_CONFIG.LEAGUES_CONFIG[k] = self._old[1][k]
            L.clear_legacy_elo_cache()
            shutil.rmtree(tmp, ignore_errors=True)

    def _entrambi(self):
        from models.elo_engine import EloEngine
        with self._db(self.STAGIONI):
            attuale = EloEngine(self.LEGA)
            attuale.compute_ratings()
            legacy = L.EloEngineLegacy(self.LEGA)
            legacy.compute_ratings()
            return attuale, legacy

    @staticmethod
    def _stato_prima(eng, squadra, n):
        return repr(eng.history[squadra][n - 1]["elo_before"])

    @staticmethod
    def _stato_a_inizio_giornata(eng, giorno, squadre):
        """Rating delle squadre date l'ultima partita PRIMA di ``giorno``.

        Il seed e' la media di questo stato: il riferimento che il test usa per
        ricalcolarlo da solo, non la formula del motore.
        """
        import pandas as pd
        stato = {}
        for squadra in squadre:
            ultimo = [h for h in eng.history[squadra]
                      if pd.Timestamp(h["date"]) < pd.Timestamp(giorno)]
            if ultimo:
                stato[squadra] = float(ultimo[-1]["elo_after"])
        return stato

    def test_prima_del_ingresso_i_due_motori_coincidono_bit_per_bit(self):
        """Nessuna squadra e' entrata: i due motori devono essere lo stesso."""
        attuale, legacy = self._entrambi()
        for squadra in ("Alfa", "Beta", "Gamma", "Delta"):
            a = [(str(h["date"]), repr(h["elo_before"]), repr(h["elo_after"]))
                 for h in attuale.history[squadra]]
            b = [(str(h["date"]), repr(h["elo_before"]), repr(h["elo_after"]))
                 for h in legacy.history[squadra]]
            self.assertEqual(a[:3], b[:3],
                             f"{squadra}: divergono prima dell'ingresso, il seed "
                             f"non doveva cambiare nient'altro")
            # tutta la stagione di burn-in, riga per riga
            solo_2022 = [x for x in a if x[0].endswith("2022")]
            self.assertEqual(solo_2022, [x for x in b if x[0].endswith("2022")],
                             f"{squadra}: burn-in non identico")

    def test_solo_la_squadra_che_entra_diverge(self):
        import pandas as pd
        attuale, legacy = self._entrambi()
        attivi_2022 = ["Alfa", "Beta", "Gamma", "Delta"]

        # Epsilon: MAI VISTA -> legacy 1500, attuale media di inizio giornata - 100
        self.assertEqual(repr(legacy.history["Epsilon"][0]["elo_before"]), "1500.0")
        # ATTIVE = chi ha gia' giocato NEL 2023/24: solo Alfa e Gamma.
        # Beta e Delta hanno un rating (stagione 2022/23) ma non fanno piu'
        # parte del campionato: sono fuori dal riferimento.
        stato = self._stato_a_inizio_giornata(legacy, "2023-08-19", ["Alfa", "Gamma"])
        self.assertEqual(set(stato), {"Alfa", "Gamma"})
        seed = float(np.mean([stato[t] for t in sorted(stato)])) + PROMOTED_SEED_OFFSET
        self.assertEqual(self._stato_prima(attuale, "Epsilon", 1), repr(seed))
        self.assertNotEqual(repr(seed), "1500.0")
        # nel giorno dell'ingresso le altre squadre sono ancora IDENTICHE: il seed
        # guarda l'inizio della giornata, non ruba niente al suo corso
        self.assertEqual(self._stato_prima(attuale, "Alfa", 4),
                         self._stato_prima(legacy, "Alfa", 4))

        # Delta e Beta, DI RITORNO dopo una stagione di assenza: il legacy
        # riparte dal rating STANTIO, l'attuale dal seed di inizio giornata
        for squadra in ("Delta", "Beta"):
            storico = legacy.history[squadra]
            self.assertEqual(str(pd.Timestamp(storico[-1]["date"]).date()),
                             "2024-08-19")
            self.assertEqual(repr(storico[-1]["elo_before"]),
                             repr(storico[-2]["elo_after"]),
                             f"{squadra}: il legacy riparte dallo stantio")
        stato_2024 = self._stato_a_inizio_giornata(
            attuale, "2024-08-19", ["Alfa", "Gamma"])
        seed_ritorno = (float(np.mean([stato_2024[t] for t in sorted(stato_2024)]))
                        + PROMOTED_SEED_OFFSET)
        for squadra in ("Delta", "Beta"):
            self.assertEqual(repr(attuale.history[squadra][-1]["elo_before"]),
                             repr(seed_ritorno))
            self.assertNotEqual(repr(attuale.history[squadra][-1]["elo_before"]),
                                repr(legacy.history[squadra][-1]["elo_before"]))
        # due ingressi nella stessa partita: stesso seed, non "il secondo vede
        # il primo"
        self.assertEqual(repr(attuale.history["Delta"][-1]["elo_before"]),
                         repr(attuale.history["Beta"][-1]["elo_before"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
