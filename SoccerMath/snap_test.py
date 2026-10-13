"""Puntamento degli snapshot reali pinnati per i test di presentazione (punto 6-8).

`database/live_odds.json` cambia OGNI GIORNO perche' il workflow lo riscrive:
un test che lo legga dal disco diventa roulotte. Qui si legge il blob del
COMMIT della base della presentazione (``e2f595e…``, merge attuale di main),
con lo stesso meccanismo ``git show`` usato dai test di parita' (fc1b45e,
078beef). Il risultato e' deterministico: 90 eventi, generato
2026-10-11T14:56:54Z.

Lo stesso vale per i ``*_Live.csv``, che il workflow ``update_database``
riscrive a ogni giornata: i test che devono leggere la CLASSIFICA di un
momento preciso (Le Havre ultima e Auxerre terzultima di Ligue 1, nel referto
della scheda partita) la leggono con :func:`blob_del_commit` dal commit
``SNAP_CSV_COMMIT`` — mai dal file corrente con valori attesi fissi.

Se un commit non e' raggiungibile (clone shallow), il test va in skip — come
gia' fanno gli altri test storici del repo.
"""
from __future__ import annotations

import json
import subprocess

# Commit (base di questa PR) il cui albero contiene lo snapshot reale dei
# 90 eventi usati dai nuovi test di presentazione.
SNAP_COMMIT = "e2f595e"
SNAP_PATH = "SoccerMath/database/live_odds.json"

# Commit il cui albero contiene i ``*_Live.csv`` citati nel referto della scheda
# partita (merge di main su cui e' costruita la PR): e' immutabile come lo
# snapshot delle quote, quindi la classifica letta da qui non balla.
SNAP_CSV_COMMIT = "92e4b23"

_PAYLOAD = None


def blob_del_commit(percorso: str, commit: str = SNAP_CSV_COMMIT):
    """Il testo di un file dell'albero di ``commit``, o ``None`` se non c'e'.

    ``percorso`` e' relativo alla radice del repository (es.
    ``SoccerMath/database/Ligue1_Live.csv``). Nessun file viene scritto: il
    chiamante decide dove mettere il testo, se gli serve su disco.
    """
    try:
        return subprocess.check_output(
            ["git", "show", f"{commit}:{percorso}"],
            stderr=subprocess.DEVNULL,
        ).decode("utf-8")
    except Exception:
        return None


def snapshot_reale():
    """Restituisce il payload dello snapshot reale pinnato, o None se il
    commit non e' disponibile (il chiamante va in skip)."""
    global _PAYLOAD
    if _PAYLOAD is None:
        try:
            raw = subprocess.check_output(
                ["git", "show", f"{SNAP_COMMIT}:{SNAP_PATH}"],
                stderr=subprocess.DEVNULL,
            ).decode("utf-8")
            _PAYLOAD = json.loads(raw)
        except Exception:
            return None
    # copia difensiva: i chiamanti non devono mutare il singleton
    return json.loads(json.dumps(_PAYLOAD))
