"""
make_elo_probs_equivalence_fixture.py — Generatore della fixture di
EQUIVALENZA BIT-EXACT per l'estrazione di ``elo_probs_from_ratings``
da ``models/elo_engine.predict_elo_probs``.

AUDIT, SOLA LETTURA. Lo script non importa nulla di nuovo: chiama solo
``models.elo_engine.predict_elo_probs`` (API pubblica gia' esistente su main)
ed ``EloEngine``. Puo' quindi essere eseguito IDENTICO sul worktree di main
(prima della modifica) e sul branch (dopo la modifica); i due output devono
coincidere bit per bit.

Due blocchi, come richiesto:

  (a) GRIGLIA SINTETICA — coppie di rating da 1200 a 1900 a passo 10
      (71 x 71 = 5041 coppie) per l'home advantage di CIASCUNA delle 5 leghe
      (``config.LEAGUE_HOME_ADVANTAGE``), per un totale di 25205 casi.
      I rating vengono forniti a ``predict_elo_probs`` installando un motore
      con ``ratings`` controllati nella cache di modulo
      ``models.elo_engine._ELO_ENGINES_CACHE`` (unica via su main: la
      funzione non accetta rating in input — e' esattamente il motivo della
      PR). La cache viene ripristinata a fine blocco.

  (b) PARTITE STORICHE POINT-IN-TIME — ``predict_elo_probs`` su TUTTE le
      partite di TUTTE le leghe presenti nel database, con lo stato del
      motore precedente alla partita. I rating pre-partita non sono
      ricalcolati: si leggono dai campi ``elo_before`` che
      ``EloEngine.compute_ratings()`` scrive in ``engine.history``.

Output: un JSONL (gzip) con, per ogni caso, il ``repr`` di OGNI valore di
OGNI chiave del dict restituito, piu' un manifest JSON con lo SHA-256 del
contenuto non compresso e i conteggi.

Uso:
    python audit/make_elo_probs_equivalence_fixture.py --out <prefisso>

Esempio (confronto main vs branch):
    python audit/make_elo_probs_equivalence_fixture.py --out /tmp/fx_main
    python audit/make_elo_probs_equivalence_fixture.py --out /tmp/fx_branch
    cmp /tmp/fx_main.jsonl /tmp/fx_branch.jsonl
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

import models.elo_engine as PROD_ELO                           # noqa: E402
from models.elo_engine import EloEngine, predict_elo_probs     # noqa: E402
from config import LEAGUE_HOME_ADVANTAGE, clean_name           # noqa: E402

LEAGUES = ("Serie A", "Premier League", "La Liga", "Bundesliga", "Ligue 1")
GRID_LO, GRID_HI, GRID_STEP = 1200, 1900, 10
HOME_TOKEN = "__HOME__"
AWAY_TOKEN = "__AWAY__"


class _StubEngine:
    """Oggetto minimo con la stessa superficie che ``predict_elo_probs``
    legge dal motore in cache: ``ratings`` e ``home_adv``."""

    def __init__(self, home_adv):
        self.ratings = {}
        self.home_adv = home_adv


def _install(league, engine):
    PROD_ELO._ELO_ENGINES_CACHE[league] = engine
    PROD_ELO._ELO_ENGINES_STAMP[league] = time.monotonic()


def _uninstall(league):
    PROD_ELO._ELO_ENGINES_CACHE.pop(league, None)
    PROD_ELO._ELO_ENGINES_STAMP.pop(league, None)


def _rec(kind, meta, probs):
    """Record canonico: repr(float) di OGNI valore di OGNI chiave."""
    return {
        "kind": kind,
        "meta": meta,
        "probs_repr": {k: repr(v) for k, v in sorted(probs.items())},
    }


def block_a(emit):
    """Griglia sintetica di rating x home advantage per lega."""
    assert clean_name(HOME_TOKEN) == HOME_TOKEN, "token alterato da clean_name"
    assert clean_name(AWAY_TOKEN) == AWAY_TOKEN, "token alterato da clean_name"
    values = list(range(GRID_LO, GRID_HI + 1, GRID_STEP))
    n = 0
    for league in LEAGUES:
        home_adv = LEAGUE_HOME_ADVANTAGE[league]
        stub = _StubEngine(home_adv)
        _install(league, stub)
        try:
            for r_h in values:
                for r_a in values:
                    stub.ratings = {HOME_TOKEN: float(r_h), AWAY_TOKEN: float(r_a)}
                    p = predict_elo_probs(HOME_TOKEN, AWAY_TOKEN, league)
                    emit(_rec("grid", {"league": league, "home_adv": repr(home_adv),
                                       "r_h": repr(float(r_h)), "r_a": repr(float(r_a))}, p))
                    n += 1
        finally:
            _uninstall(league)
    return n


def block_b(emit):
    """Tutte le partite storiche, stato del motore point-in-time."""
    n = 0
    for league in LEAGUES:
        _uninstall(league)
        engine = EloEngine(league)
        engine.compute_ratings()
        df = engine.matches_df
        final_ratings = dict(engine.ratings)
        cur = defaultdict(int)
        _install(league, engine)
        try:
            for i, (_, row) in enumerate(df.iterrows()):
                if i % 200 == 0:
                    PROD_ELO._ELO_ENGINES_STAMP[league] = time.monotonic()
                h, a = row["HomeClean"], row["AwayClean"]
                eh = engine.history[h][cur[h]]
                ea = engine.history[a][cur[a]]
                assert eh["date"] == row["Date_Parsed"] and eh["opponent"] == a and eh["is_home"]
                assert ea["date"] == row["Date_Parsed"] and ea["opponent"] == h and not ea["is_home"]
                cur[h] += 1
                cur[a] += 1
                engine.ratings = {h: eh["elo_before"], a: ea["elo_before"]}
                p = predict_elo_probs(row["HomeTeam"], row["AwayTeam"], league)
                emit(_rec("match", {"league": league,
                                    "date": str(row["Date_Parsed"]),
                                    "home_raw": str(row["HomeTeam"]),
                                    "away_raw": str(row["AwayTeam"]),
                                    "r_h": repr(float(eh["elo_before"])),
                                    "r_a": repr(float(ea["elo_before"]))}, p))
                n += 1
        finally:
            engine.ratings = final_ratings
            _uninstall(league)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True,
                    help="prefisso: scrive <out>.jsonl.gz e <out>.manifest.json")
    args = ap.parse_args(argv)

    lines = []
    emit = lambda r: lines.append(json.dumps(r, sort_keys=True, ensure_ascii=False))  # noqa: E731

    na = block_a(emit)
    nb = block_b(emit)
    # cutoff dichiarato per lega = data massima dei record di partita (dedotta dai dati)
    cutoff = {}
    for s in lines:
        r = json.loads(s)
        if r["kind"] == "match":
            lg = r["meta"]["league"]
            cutoff[lg] = max(cutoff.get(lg, ""), r["meta"]["date"][:10])
    payload = "\n".join(lines) + "\n"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    out_jsonl = f"{args.out}.jsonl.gz"
    out_manifest = f"{args.out}.manifest.json"
    # mtime=0: il .gz deve essere riproducibile byte per byte (niente timestamp)
    with open(out_jsonl, "wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb",
                           compresslevel=9, mtime=0) as f:
            f.write(payload.encode("utf-8"))
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                       cwd=_REPO_ROOT).decode().strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain",
                                         "--", "SoccerMath/"],
                                        cwd=_REPO_ROOT).decode().strip()
    except Exception:                                      # pragma: no cover
        head, dirty = "(git non disponibile)", "(n/d)"
    manifest = {
        "_schema": "elo_probs_equivalence/1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo_head_commit": head,
        "produzione_sporca_rispetto_al_commit": dirty or "(pulita)",
        "generator": "audit/make_elo_probs_equivalence_fixture.py",
        "grid": {"lo": GRID_LO, "hi": GRID_HI, "step": GRID_STEP,
                 "leagues": list(LEAGUES),
                 "home_adv": {k: repr(LEAGUE_HOME_ADVANTAGE[k]) for k in LEAGUES}},
        "n_grid": na, "n_match": nb, "n_total": na + nb,
        "cutoff": cutoff,
        "sha256_payload_non_compresso": digest,
    }
    with open(out_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)

    print(json.dumps(manifest, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
