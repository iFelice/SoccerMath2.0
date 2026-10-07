"""
test_elo_s3_parity.py — Parita' BIT-EXACT fra il motore di produzione
``models/elo_engine.py`` (con il seeding degli ingressi in lega adottato dalla
PR che applica S3) e la variante ``S3`` di ``audit/elo_drift_triage.py``.

Fixture: ``audit/fixtures/elo_s3_parity.json``
Generata da: ``audit/make_elo_s3_parity_fixture.py`` sul commit dichiarato
dentro la fixture stessa.

Cosa e' negato (e come)
----------------------
  V1  il commit dichiarato nel manifest esiste in questo repository;
  V2  gli object id degli input (produzione + audit) registrati nel manifest
      sono davvero quelli di QUEL commit: il manifest non puo' dichiarare un
      commit e descriverne un altro;
  S  per ogni ingresso dichiarato in fixture, il seed che la produzione
      applica e' il seed S3, ed e' la definizione condivisa: media dei rating
      delle squadre ATTIVE subito prima della partita d'ingresso, meno
      ``PROMOTED_SEED_OFFSET`` (ripresa di ``_seed_for_variant("S3")``);
  P  per tutte le partite in fixture, rating pre-partita, rating post-partita,
      ``expected_score_home``, ``p_draw`` e la terna Elo 1X2 del motore di
      produzione coincidono, per ``repr()`` esatto del float.

Nessuna tolleranza numerica: se la produzione si allontana di un solo ULP il
test e' rosso. La provenienza non e' una whitelist su main (la stessa scelta di
``test_elo_walker_parity.py``): la fixture puo' invecchiare, basta che continui
a descrivere la produzione del commit che dichiara.

Esecuzione:  python audit/test_elo_s3_parity.py
             python -m pytest audit/test_elo_s3_parity.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

_AUDIT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _AUDIT_DIR.parent
for _p in (str(_AUDIT_DIR), str(_REPO_ROOT / "SoccerMath")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import elo_walker_core as WALKER                        # noqa: E402
from models.elo_engine import (                          # noqa: E402
    EloEngine,
    PROMOTED_SEED_OFFSET,
    elo_probs_from_ratings,
)

FIXTURE = _AUDIT_DIR / "fixtures" / "elo_s3_parity.json"
COLONNE = ("elo_home_pre", "elo_away_pre", "elo_home_post", "elo_away_post",
           "e_H", "p_draw", "elo_1", "elo_X", "elo_2")

_CACHE: dict = {}


def _git(*args):
    try:
        r = subprocess.run(["git", "-C", str(_REPO_ROOT), *args], capture_output=True,
                           text=True, timeout=60)
    except Exception:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _produzione(league: str) -> list:
    """Righe per-partita della PRODUZIONE, lette da ``EloEngine`` e basta.

    ``_prematch_ratings`` ricostruisce l'accoppiamento riga <-> voce di history
    con un cursore per squadra: non ricalcola nessun rating. La conversione 1X2
    e' la funzione pura di produzione, sugli stessi rating pre-partita.
    """
    if league in _CACHE:
        return _CACHE[league]
    engine = EloEngine(league)
    engine.compute_ratings()
    df = engine.matches_df.reset_index(drop=True)
    pre = WALKER._prematch_ratings(engine).reset_index(drop=True)
    righe = []
    for i in range(len(df)):
        rh = float(pre["elo_home_pre"].iloc[i])
        ra = float(pre["elo_away_pre"].iloc[i])
        p = elo_probs_from_ratings(rh, ra, engine.home_adv)
        righe.append({
            "prod_order": int(i),
            "date": str(pd.Timestamp(df["Date_Parsed"].iloc[i]).date()),
            "home": df["HomeClean"].iloc[i],
            "away": df["AwayClean"].iloc[i],
            "elo_home_pre": repr(rh),
            "elo_away_pre": repr(ra),
            "elo_home_post": repr(float(pre["elo_home_post"].iloc[i])),
            "elo_away_post": repr(float(pre["elo_away_post"].iloc[i])),
            "e_H": repr(float(p["expected_score_home"])),
            "p_draw": repr(float(p["X"])),
            "elo_1": repr(float(p["1"])),
            "elo_X": repr(float(p["X"])),
            "elo_2": repr(float(p["2"])),
        })
    _CACHE[league] = righe
    return righe


def _stato_prima(righe: list, i: int) -> dict:
    """Rating delle squadre ATTIVE AL INIZIO della giornata della riga ``i``.

    Stessa definizione dell'audit (``active_teams``: le squadre con almeno una
    partita anteriore alla giornata, nell'ordine di produzione), ricavata dai
    rating post-partita della produzione.
    """
    stato: dict = {}
    for j in range(i):
        stato[righe[j]["home"]] = float(righe[j]["elo_home_post"])
        stato[righe[j]["away"]] = float(righe[j]["elo_away_post"])
    return stato


def _fixture():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


class TestProvenienza(unittest.TestCase):
    """La fixture dichiara DUE commit e i test li controllano entrambi.

    * ``reference_production_commit``: la produzione da cui vengono gli update
      Elo e la conversione 1X2. Deve essere un commit ANCORA SENZA il seeding,
      altrimenti la reference non sarebbe indipendente dalla produzione che
      si sta validando;
    * ``audit_logic_commit``: la logica del seeding (quella che definisce
      «ingresso» e «media attiva»).
    """

    def _hex(self, sha, cosa):
        self.assertTrue(len(sha) == 40 and all(c in "0123456789abcdef" for c in sha),
                        f"{cosa}: sha non valido: {sha}")

    def test_V1_commit_dichiarati_esistono(self):
        prov = _fixture()["provenance"]
        for chiave in ("commit", "reference_production_commit", "audit_logic_commit"):
            sha = prov[chiave]
            self._hex(sha, chiave)
            self.assertIsNotNone(_git("cat-file", "-t", sha),
                                 f"{chiave}={sha} non presente nel clone")

    def test_V2_oid_degli_input_corrispondono_ai_commit_dichiarati(self):
        prov = _fixture()["provenance"]
        gruppi = {"production_input_oids": prov["reference_production_commit"],
                  "audit_input_oids": prov["audit_logic_commit"]}
        for gruppo, sha in gruppi.items():
            for path, oid in prov[gruppo].items():
                atteso = _git("rev-parse", f"{sha}:{path}")
                self.assertIsNotNone(atteso, f"{path} assente al commit {sha}")
                self.assertEqual(atteso, oid, f"{path}: manifest e commit non coincidono")

    def test_V3_la_reference_non_ha_il_seeding(self):
        """Il motore di produzione da cui viene la reference deve essere quello
        PRIMA della modifica: senza seeding, quindi senza la costante."""
        sha = _fixture()["provenance"]["reference_production_commit"]
        sorgente = _git("cat-file", "-p", f"{sha}:SoccerMath/models/elo_engine.py")
        self.assertIsNotNone(sorgente)
        self.assertNotIn("PROMOTED_SEED_OFFSET", sorgente,
                         "la reference non e' piu' indipendente dalla produzione")
        attuale = _git("cat-file", "-p",
                       "HEAD:SoccerMath/models/elo_engine.py")
        self.assertIn("PROMOTED_SEED_OFFSET", attuale)


class TestParitaBitExact(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = _fixture()

    def test_totale_partite_attese(self):
        # Il numero e' quello dichiarato dalla fixture, non una costante scritta
        # qui: se il DB cresce, la fixture va rigenerata e questo test lo segnala.
        self.assertEqual(sum(b["n_matches"] for b in self.fx["leagues"].values()),
                         self.fx["total_matches"])

    def test_seed_di_produzione_uguale_al_seed_S3(self):
        """Il seed applicato dalla produzione coincide col seed dichiarato in
        fixture, ed e' la definizione condivisa: media attiva - 100.

        Il seed di produzione e' il rating che il motore da' alla squadra subito
        prima della sua partita d'ingresso, cioe' il suo ``elo_*_pre`` su quella
        riga. Qui media attiva e seed sono ricalcolati indipendentemente dallo
        stato della produzione (i rating post-partita, riga per riga), quindi il
        test non riusa la formula del motore: la ricalcola e la confronta.

        Lo stato e' quello a INIZIO GIORNATA: la prima riga di ogni data
        fotografa le squadre che avevano gia' giocato, e le partite successive
        della stessa giornata non lo modificano. Due ingressi nella stessa
        giornata leggono quindi lo stesso stato e prendono lo stesso seed.
        """
        for league, blk in self.fx["leagues"].items():
            righe = _produzione(league)
            per_partita: dict = {}
            giornata: dict = {}      # stato cumulato della stagione in corso
            for e in blk["entries"].values():
                per_partita.setdefault(e["prod_order"], []).append(e)
            stato: dict = {}          # squadra -> rating a inizio giornata
            giorno_corrente = None
            for i, r in enumerate(righe):
                giorno = r["date"]
                if giorno != giorno_corrente:
                    giorno_corrente = giorno
                    stato = dict(giornata)      # snapshot: la giornata non lo tocca
                for e in sorted(per_partita.get(i, []), key=lambda z: z["team"]):
                    media = float(np.mean([stato[t] for t in sorted(stato)]))
                    seed = media + PROMOTED_SEED_OFFSET
                    self.assertEqual(len(stato), e["n_active_before"],
                                     f"{league} {e['team']}: numero di squadre attive")
                    self.assertEqual(repr(media), e["active_mean"],
                                     f"{league} {e['team']}@{i}: media attiva != S3")
                    self.assertEqual(repr(seed), e["seed"],
                                     f"{league} {e['team']}@{i}: seed != seed S3")
                    pre = (float(r["elo_home_pre"]) if r["home"] == e["team"]
                           else float(r["elo_away_pre"]))
                    self.assertEqual(repr(pre), e["seed"],
                                     f"{league} {e['team']}@{i}: seed produzione != seed S3")
                giornata[r["home"]] = float(r["elo_home_post"])
                giornata[r["away"]] = float(r["elo_away_post"])

    def test_parita_per_partita_bit_exact(self):
        diffs = []
        for league, blk in self.fx["leagues"].items():
            righe = _produzione(league)
            if len(righe) != blk["n_matches"]:
                diffs.append((league, "n_matches", blk["n_matches"], len(righe)))
                continue
            for attesa, gotta in zip(blk["matches"], righe):
                for c in COLONNE:
                    if attesa[c] != gotta[c]:
                        diffs.append((league, attesa["date"], attesa["home"], attesa["away"],
                                      c, attesa[c], gotta[c]))
        self.assertEqual(len(diffs), 0, f"{len(diffs)} differenze, prime: {diffs[:5]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)