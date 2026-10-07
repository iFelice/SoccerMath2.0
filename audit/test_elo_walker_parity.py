"""
test_elo_walker_parity.py — Punto A.3: parita' BIT-EXACT fra il walker Elo
fedele (audit/elo_walker_core.py) e il codice di produzione, su fixture
congelata.

Fixture: audit/fixtures/elo_walker_parity.json
Generata da: audit/make_elo_parity_fixture.py (solo codice di produzione)

PROVENIENZA DELLA FIXTURE (riscritta: niente whitelist su main)
---------------------------------------------------------------
La versione precedente di questo test asseriva

    git diff --stat <commit-cablato> -- SoccerMath/   ==   ""

cioe' "la produzione di oggi deve essere identica a quella di un commit
scritto a mano nel test". E' una whitelist: si rompe alla PRIMA PR che tocca
la produzione anche solo per un refactor bit-exact (ed e' esattamente quello
che e' successo con la PR #30, che ha estratto ``elo_probs_from_ratings``).
Un test di provenienza non deve dipendere da dove sta main.

La fixture dichiara da sola il commit che l'ha generata, nel suo manifest:

    fixture["provenance"] = {
        "commit": <sha>,
        "production_input_oids": {<path di produzione>: <object id git>, ...}
    }

I tre controlli di provenienza, tutti RELATIVI AL COMMIT DICHIARATO e nessuno
relativo a main:

  V1  il commit dichiarato esiste in questo repository;
  V2  gli object id degli input di produzione registrati nel manifest sono
      davvero quelli di QUEL commit (``git rev-parse <commit>:<path>``):
      il manifest non puo' dichiarare un commit e descriverne un altro;
  V3  (prova forte) la fixture e' RIGENERABILE da quel commit: si estrae il
      commit in un worktree git separato, vi si esegue il generatore e si
      confronta bit-exact il blocco numerico ``leagues``.

Conseguenza voluta: la produzione puo' evolvere quanto vuole senza rompere
questo test. Cio' che il test nega e' solo che la fixture menta sulla propria
origine. La corrispondenza fra fixture e produzione di OGGI e' invece
compito di P1/P2/P3, che la misurano come fatto, non come whitelist.

Controlli di parita':
  P0  non interferenza: il walker non legge ne' scrive la cache globale di
      modulo ``_ELO_ENGINES_CACHE`` / ``_ELO_ENGINES_STAMP``.
  P1  stato finale: il rating ``elo_after`` dell'ultima partita di ogni
      squadra nel walker == ``EloEngine.ratings`` di produzione (repr esatto).
  P2  conversione: le probabilita' del walker (``elo_probs_from_ratings``)
      == ``predict_elo_probs`` di produzione sulle stesse coppie (bit-exact).
  P3  walk-forward: per ogni cutoff della fixture, le probabilita' del walker
      per la PRIMA partita della data di cutoff == quelle di un motore di
      PRODUZIONE costruito su CSV troncati a ``Date < cutoff`` (bit-exact),
      inclusi i rating pre-partita.
  P4  no-leakage (classe TestNoLeakage).

Esecuzione:
    python audit/test_elo_walker_parity.py
    python -m pytest audit/test_elo_walker_parity.py -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

import models.elo_engine as PROD_ELO                       # noqa: E402
from models.elo_engine import (                            # noqa: E402
    EloEngine, predict_elo_probs, elo_probs_from_ratings,
)
import elo_walker_core as W                                 # noqa: E402

FIXTURE_PATH = os.path.join(_AUDIT_DIR, "fixtures", "elo_walker_parity.json")
GENERATOR_PATH = os.path.join(_AUDIT_DIR, "make_elo_parity_fixture.py")

with open(FIXTURE_PATH, encoding="utf-8") as _f:
    FIX = json.load(_f)


def _git(*args, cwd=_REPO_ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd,
                                   stderr=subprocess.STDOUT).decode().strip()


class TestProvenienzaFixture(unittest.TestCase):
    """Provenienza AUTOCONTENUTA: tutto e' relativo al commit che la fixture
    dichiara. Nessun riferimento a main, nessun commit cablato nel test."""

    def test_v0_manifest_ha_il_blocco_di_provenienza(self):
        self.assertIn("provenance", FIX,
                      "la fixture non dichiara da quale commit viene")
        prov = FIX["provenance"]
        self.assertIn("commit", prov)
        self.assertIn("production_input_oids", prov)
        self.assertTrue(prov["production_input_oids"],
                        "nessun input di produzione registrato")
        # coerenza interna del manifest
        self.assertEqual(prov["commit"], FIX["repo_head_commit"])
        # il test NON deve contenere commit cablati: lo si verifica leggendosi
        with open(os.path.abspath(__file__), encoding="utf-8") as f:
            src = f.read()
        import re as _re
        cablati = _re.findall(r"[\"\']([0-9a-f]{40})[\"\']", src)
        self.assertEqual(cablati, [],
                         f"commit cablati nel test (whitelist): {cablati}")

    def test_v1_commit_dichiarato_esiste(self):
        commit = FIX["provenance"]["commit"]
        try:
            tipo = _git("cat-file", "-t", commit)
        except subprocess.CalledProcessError as e:
            self.fail(f"il commit dichiarato {commit} non esiste in questo "
                      f"repository: {e.output.decode().strip()}")
        self.assertEqual(tipo, "commit")

    def test_v2_oid_produzione_coerenti_col_commit_dichiarato(self):
        commit = FIX["provenance"]["commit"]
        attesi = FIX["provenance"]["production_input_oids"]
        errori = []
        for path, oid_dichiarato in sorted(attesi.items()):
            try:
                oid_reale = _git("rev-parse", f"{commit}:{path}")
            except subprocess.CalledProcessError as e:
                errori.append(f"{path}: non risolvibile al commit {commit[:12]} "
                              f"({e.output.decode().strip()})")
                continue
            if oid_reale != oid_dichiarato:
                errori.append(f"{path}: manifest={oid_dichiarato} "
                              f"commit={oid_reale}")
        if errori:
            self.fail("il manifest non descrive il commit che dichiara:\n  "
                      + "\n  ".join(errori))
        print(f"\n  V2 OK: {len(attesi)} input di produzione coerenti con "
              f"{commit[:12]}")

    def test_v3_fixture_rigenerabile_dal_commit_dichiarato(self):
        """Prova forte: si rigenera la fixture ESEGUENDO la produzione del
        commit dichiarato (worktree separato) e si confronta il blocco
        numerico bit-exact. Indipendente da dove sta main e da cosa contiene
        il working tree di oggi."""
        commit = FIX["provenance"]["commit"]
        wt = tempfile.mkdtemp(prefix="elo_prov_wt_")
        shutil.rmtree(wt, ignore_errors=True)          # git vuole il path libero
        out_json = os.path.join(tempfile.mkdtemp(prefix="elo_prov_out_"),
                                "rigenerata.json")
        try:
            try:
                _git("worktree", "add", "--detach", wt, commit)
            except subprocess.CalledProcessError as e:
                self.skipTest("NON VERIFICABILE: git worktree non disponibile "
                              f"o commit non estraibile: {e.output.decode().strip()}")
            # il generatore e' uno strumento di audit, non di produzione:
            # si porta quello di oggi sopra la PRODUZIONE del commit dichiarato.
            os.makedirs(os.path.join(wt, "audit"), exist_ok=True)
            shutil.copy(GENERATOR_PATH, os.path.join(wt, "audit"))
            proc = subprocess.run(
                [sys.executable, os.path.join("audit", "make_elo_parity_fixture.py"),
                 "--out", out_json],
                cwd=wt, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0,
                             f"generatore fallito nel worktree:\n{proc.stdout}\n{proc.stderr}")
            with open(out_json, encoding="utf-8") as f:
                rig = json.load(f)
            self.assertEqual(rig["provenance"]["commit"], commit,
                             "il worktree non e' al commit dichiarato")
            self.assertEqual(
                rig["provenance"]["production_input_oids"],
                FIX["provenance"]["production_input_oids"],
                "gli input di produzione rigenerati non coincidono col manifest")
            # confronto BIT-EXACT del blocco numerico
            self.assertEqual(
                json.dumps(rig["leagues"], sort_keys=True, ensure_ascii=False),
                json.dumps(FIX["leagues"], sort_keys=True, ensure_ascii=False),
                "la fixture NON e' riproducibile dal commit che dichiara")
            n = sum(len(v["final_ratings"]) for v in FIX["leagues"].values())
            print(f"\n  V3 OK: fixture rigenerata da {commit[:12]} identica "
                  f"({len(FIX['leagues'])} leghe, {n} rating finali)")
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", wt],
                           cwd=_REPO_ROOT, capture_output=True)
            shutil.rmtree(wt, ignore_errors=True)
            shutil.rmtree(os.path.dirname(out_json), ignore_errors=True)


#: soglie ammesse SOLO per i casi P3 in cui il DB troncato e' stato
#: ri-mangiato in un ordine diverso da quello di produzione (vedi il
#: docstring di test_p3_walk_forward_vs_produzione_troncata)
class TestParitaWalker(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.engines = {}
        cls.tables = {}
        cls.cache_prima = {}
        cls.cache_dopo = {}
        cls.ratings_intatti = {}
        for lg in W.LEAGUES:
            PROD_ELO._ELO_ENGINES_CACHE.pop(lg, None)
            PROD_ELO._ELO_ENGINES_STAMP.pop(lg, None)
            e = EloEngine(lg)
            e.compute_ratings()
            cls.engines[lg] = e
            rating_finali = {t: repr(float(r)) for t, r in e.ratings.items()}
            cls.cache_prima[lg] = W.cache_snapshot()
            cls.tables[lg] = W.build_walker_table(lg, engine=e)
            cls.cache_dopo[lg] = W.cache_snapshot()
            cls.ratings_intatti[lg] = (
                rating_finali == {t: repr(float(r)) for t, r in e.ratings.items()})

    # ---- P0 -------------------------------------------------------------
    def test_p0_walker_non_tocca_la_cache_globale(self):
        """Il walker usa la funzione PURA elo_probs_from_ratings: non deve
        leggere ne' scrivere _ELO_ENGINES_CACHE / _ELO_ENGINES_STAMP, ne'
        mutare engine.ratings."""
        for lg in W.LEAGUES:
            self.assertEqual(self.cache_prima[lg], self.cache_dopo[lg],
                             f"{lg}: build_walker_table ha toccato la cache globale")
            self.assertTrue(self.ratings_intatti[lg],
                            f"{lg}: build_walker_table ha mutato engine.ratings")
        # e la cache deve essere rimasta VUOTA per queste leghe: il walker non
        # ci ha mai scritto nulla (nessun engine installato, nessun timestamp)
        for lg in W.LEAGUES:
            self.assertNotIn(lg, PROD_ELO._ELO_ENGINES_CACHE,
                             f"{lg}: engine lasciato nella cache globale")
            self.assertNotIn(lg, PROD_ELO._ELO_ENGINES_STAMP,
                             f"{lg}: timestamp lasciato nella cache globale")
        # prova strutturale: i nomi globali/attributi referenziati dal
        # bytecode di build_walker_table (co_names ignora commenti e
        # docstring) contengono la funzione pura e NON la cache di modulo.
        nomi = set(W.build_walker_table.__code__.co_names)
        self.assertIn("elo_probs_from_ratings", nomi,
                      f"il walker non chiama la funzione pura; co_names={sorted(nomi)}")
        for vietato in ("_ELO_ENGINES_CACHE", "_ELO_ENGINES_STAMP",
                        "predict_elo_probs", "get_elo_engine"):
            self.assertNotIn(vietato, nomi,
                             f"il walker referenzia ancora {vietato}")
        print("\n  P0 OK: cache globale intatta per tutte e 5 le leghe; "
              f"co_names(build_walker_table) include elo_probs_from_ratings "
              f"e nessun simbolo di cache")

    # ---- P1 -------------------------------------------------------------
    def test_p1_stato_finale_identico(self):
        for lg in W.LEAGUES:
            eng = self.engines[lg]
            atteso = FIX["leagues"][lg]["final_ratings"]
            ottenuto = {t: repr(float(r)) for t, r in eng.ratings.items()}
            self.assertEqual(ottenuto, atteso, f"{lg}: rating finali != fixture")
            # il walker ricostruisce lo stesso stato finale dagli elo_after
            d = self.tables[lg]
            last = {}
            for _, r in d.iterrows():
                last[r["home"]] = r["elo_home_pre"]
                last[r["away"]] = r["elo_away_pre"]
            # elo_after dell'ultima partita per squadra, ripreso da history
            post = {}
            for team, hist in eng.history.items():
                if hist:
                    post[team] = repr(float(hist[-1]["elo_after"]))
            self.assertEqual(post, atteso, f"{lg}: elo_after finali != fixture")

    # ---- P2 -------------------------------------------------------------
    def test_p2_conversione_identica(self):
        """Due lati, stesso bit:
        (a) produzione di oggi (predict_elo_probs) vs fixture congelata;
        (b) via del walker (elo_probs_from_ratings, funzione pura) vs la
            stessa produzione, sugli stessi rating."""
        import config as PROD_CONFIG
        n = 0
        for lg in W.LEAGUES:
            eng = self.engines[lg]
            PROD_ELO._ELO_ENGINES_CACHE[lg] = eng
            PROD_ELO._ELO_ENGINES_STAMP[lg] = time.monotonic()
            for case in FIX["leagues"][lg]["now_fixtures"]:
                got = predict_elo_probs(case["home_raw"], case["away_raw"], lg)
                # (a) produzione vs fixture
                for k, v in case["probs"].items():
                    self.assertEqual(repr(got[k]), repr(v),
                                     f"{lg} {case['home_raw']}-{case['away_raw']} chiave {k}")
                # (b) walker (funzione pura) vs produzione
                r_h = eng.ratings.get(PROD_CONFIG.clean_name(case["home_raw"]),
                                      PROD_ELO.DEFAULT_INITIAL_RATING)
                r_a = eng.ratings.get(PROD_CONFIG.clean_name(case["away_raw"]),
                                      PROD_ELO.DEFAULT_INITIAL_RATING)
                puro = elo_probs_from_ratings(r_h, r_a, eng.home_adv)
                for k in got:
                    self.assertEqual(repr(puro[k]), repr(got[k]),
                                     f"{lg} {case['home_raw']}-{case['away_raw']} "
                                     f"chiave {k}: funzione pura != predict_elo_probs")
                n += 1
            PROD_ELO._ELO_ENGINES_CACHE.pop(lg, None)
            PROD_ELO._ELO_ENGINES_STAMP.pop(lg, None)
        print(f"\n  P2 OK: {n} accoppiamenti, fixture == predict_elo_probs == "
              f"elo_probs_from_ratings")

    # ---- P3 -------------------------------------------------------------
    def test_p3_walk_forward_vs_produzione_troncata(self):
        """Stato del walker contro un motore di PRODUZIONE costruito sui soli
        CSV con data antecedente al cutoff, bit-exact.

        Il loader riordina per data con un sort instabile, quindi sul DB
        troncato qualche partita della stessa giornata puo' cambiare posto.
        Finche' il seed guardava lo stato "in quel momento" questo rompeva la
        parita': il seed di una neo-promossa contava le partite della sua
        giornata gia' acquisite, e nel backtest poteva usare risultati non
        disponibili prima del kickoff. Con il seed letto a INIZIO giornata
        l'ordine dentro la giornata e' di nuovo irrilevante — le partite di una
        giornata sono disgiunte, nessuna squadra gioca due volte lo stesso
        giorno — e il confronto torna bit-exact su tutti i cutoff.

        Il test non ha soglie: ogni scarto e' un fallimento.
        """
        diffs = []
        for lg in W.LEAGUES:
            d = self.tables[lg]
            for case in FIX["leagues"][lg]["cutoff_cases"]:
                pos = case["prod_pos_nel_db_completo"]
                row = d.iloc[pos]
                self.assertEqual(row["home"], case["home"])
                self.assertEqual(row["away"], case["away"])
                self.assertEqual(str(pd.Timestamp(row["date"]).date()), case["cutoff"])
                att = case["probs"]
                for col, key in (("elo_1", "1"), ("elo_X", "X"), ("elo_2", "2"),
                                 ("d", "elo_diff"), ("e_H", "expected_score_home")):
                    if repr(float(row[col])) != repr(float(att[key])):
                        diffs.append((lg, case["cutoff"], col,
                                      float(row[col]), float(att[key])))
                for team, rr in case["ratings_troncati"].items():
                    col = "elo_home_pre" if team == case["home"] else "elo_away_pre"
                    if repr(float(row[col])) != rr:
                        diffs.append((lg, case["cutoff"], col,
                                      float(row[col]), float(rr)))
        if diffs:
            msg = "\n".join(f"  {a} cutoff={b} {c}: walker={e!r} produzione={f!r} "
                            f"delta={e - f:+.10g}" for a, b, c, e, f in diffs)
            self.fail(f"P3 NON OK, {len(diffs)} differenze:\n{msg}")


class TestNoLeakage(unittest.TestCase):
    """P4: test di causalita'. Si altera il RISULTATO di una partita nei CSV
    (copia temporanea del DB, originale intatto) e si verifica che le
    probabilita' Elo del walker PER QUELLA partita non cambino di un bit,
    mentre quelle delle partite successive delle stesse squadre cambino.
    Se il walker guardasse il risultato della partita che prevede, la prima
    verifica fallirebbe."""

    LEAGUE = "Premier League"

    def test_p4_alterare_il_risultato_non_cambia_la_previsione(self):
        import shutil
        import tempfile
        import config as PROD_CONFIG
        from make_elo_parity_fixture import _RepointDB

        base = W.build_walker_table(self.LEAGUE)
        target = 1000                       # riga di prova, in mezzo alla serie
        row = base.iloc[target]

        tmp = tempfile.mkdtemp(prefix="elo_leak_db_")
        try:
            src = str(PROD_CONFIG.DATABASE_DIR)
            for f in os.listdir(src):
                shutil.copy(os.path.join(src, f), os.path.join(tmp, f))
            # inverte il risultato della partita bersaglio in tutti i CSV
            cambiate = 0
            for f in os.listdir(tmp):
                if not f.endswith(".csv"):
                    continue
                p = os.path.join(tmp, f)
                df = pd.read_csv(p, on_bad_lines="warn", low_memory=False)
                if not {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"}.issubset(df.columns):
                    continue
                dt = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
                m = ((dt == pd.Timestamp(row["date"]))
                     & (df["HomeTeam"] == row["home_raw"])
                     & (df["AwayTeam"] == row["away_raw"]))
                if m.any():
                    df.loc[m, "FTHG"] = 9
                    df.loc[m, "FTAG"] = 0
                    df.loc[m, "FTR"] = "H"
                    df.to_csv(p, index=False)
                    cambiate += int(m.sum())
            self.assertGreater(cambiate, 0, "partita bersaglio non trovata nei CSV")

            with _RepointDB(tmp):
                PROD_ELO._ELO_ENGINES_CACHE.pop(self.LEAGUE, None)
                alt = W.build_walker_table(self.LEAGUE)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            PROD_ELO._ELO_ENGINES_CACHE.pop(self.LEAGUE, None)

        self.assertEqual(len(alt), len(base))
        for col in ("elo_1", "elo_X", "elo_2", "elo_home_pre", "elo_away_pre"):
            self.assertEqual(repr(float(alt.iloc[target][col])),
                             repr(float(base.iloc[target][col])),
                             f"LEAKAGE: {col} della partita bersaglio e' cambiato")
        # le righe precedenti sono identiche
        pre_eq = (alt.iloc[:target][["elo_1", "elo_X", "elo_2"]].to_numpy()
                  == base.iloc[:target][["elo_1", "elo_X", "elo_2"]].to_numpy()).all()
        self.assertTrue(pre_eq, "il passato e' cambiato: ordinamento non deterministico")
        # almeno una riga successiva deve essere cambiata (l'update ha effetto)
        post_diff = (alt.iloc[target + 1:][["elo_1", "elo_X", "elo_2"]].to_numpy()
                     != base.iloc[target + 1:][["elo_1", "elo_X", "elo_2"]].to_numpy()).any()
        self.assertTrue(post_diff, "l'aggiornamento non ha avuto alcun effetto a valle")
        n_post = int((alt.iloc[target + 1:][["elo_1", "elo_X", "elo_2"]].to_numpy()
                      != base.iloc[target + 1:][["elo_1", "elo_X", "elo_2"]].to_numpy())
                     .any(axis=1).sum())
        print(f"\n  P4: righe successive modificate = {n_post} / {len(base) - target - 1}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
