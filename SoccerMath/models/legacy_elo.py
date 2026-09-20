"""Motore Elo LEGACY (pre-PR#24): provenienza e punto di accesso unico.

Il Top Mix calcola DUE modelli: quello attuale (``models/elo_engine.py``,
senza boost xG) e quello legacy, cioe' l'Elo esattamente come era in
produzione PRIMA del fix di PR#24. Il legacy NON e' una ricostruzione
approssimata: ``models/elo_engine_legacy.py`` e' il blob git
``784cecc97286f5a74a105b3cf051146388f1270a`` copiato byte per byte
(``git show a435436:SoccerMath/models/elo_engine.py``); il test
``test_legacy_elo_engine.py`` ricalcola l'hash del blob e fallisce se il file
diverge di un solo byte.

Dove e quando e' stato sostituito (``git log`` di ``main``):

* blob legacy in vigore da ``16d4e73`` (2026-09-09) a ``a435436``
  (2026-09-18 20:03 UTC, ultimo commit di ``main`` prima del fix);
* sostituito dal commit ``980e048`` "fix(elo): remove retroactive xG boost in
  compute_ratings and unify Elo formula" (2026-09-18 21:39:23 UTC);
* entrato in ``main`` con la merge ``626cd0b`` di PR#24
  (2026-09-18 21:51:58 UTC).

L'UNICA differenza fra i due motori e' il boost xG retroattivo di
``compute_ratings`` (``xg_adj`` da ``get_understat_xg(lega)``, ``xg_elo_boost``
in ``dr``): K, vantaggio casa, curva del pareggio e ``predict_elo_probs`` sono
identici. Il modulo verbatim ha la sua cache (``_ELO_ENGINES_CACHE``) separata
da quella del motore attuale, quindi i due convivono nello stesso processo.
"""
from __future__ import annotations

import hashlib
import os

from models import elo_engine_legacy as _legacy

# --- provenienza (verificata da test_legacy_elo_engine.py) -------------------
LEGACY_ELO_ENGINE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "elo_engine_legacy.py")
LEGACY_ELO_BLOB_SHA = "784cecc97286f5a74a105b3cf051146388f1270a"
LEGACY_ELO_SOURCE_COMMIT = "a435436cef7dcaf835b79a5151ef7f8d9d10879b"   # ultimo main pre-fix
LEGACY_ELO_SOURCE_PATH = "SoccerMath/models/elo_engine.py"
LEGACY_ELO_REPLACED_BY_COMMIT = "980e04851b91345e697e62fe7f50b425a3d6d2b5"
LEGACY_ELO_REPLACED_BY_TIME_UTC = "2026-09-18T21:39:23Z"
LEGACY_ELO_MERGE_COMMIT = "626cd0bcc0fbc1806ebf9b13d48de829a0380b25"       # merge PR#24
LEGACY_ELO_MERGE_TIME_UTC = "2026-09-18T21:51:58Z"


def git_blob_sha(path: str = LEGACY_ELO_ENGINE_FILE) -> str:
    """Hash dell'oggetto blob come lo calcola git (``git hash-object``), senza git."""
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def legacy_engine_is_verbatim() -> bool:
    return git_blob_sha() == LEGACY_ELO_BLOB_SHA


# --- accesso al motore --------------------------------------------------------
# Alias diretti al modulo verbatim: nessun wrapper "intelligente" in mezzo,
# altrimenti il legacy non sarebbe piu' il codice di prima.
get_elo_engine_legacy = _legacy.get_elo_engine
predict_elo_probs_legacy = _legacy.predict_elo_probs
EloEngineLegacy = _legacy.EloEngine


def clear_legacy_elo_cache() -> None:
    """Svuota la cache del motore legacy (test e replay point-in-time)."""
    _legacy._ELO_ENGINES_CACHE.clear()
    _legacy._ELO_ENGINES_STAMP.clear()
