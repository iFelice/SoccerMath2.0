"""plugin pytest SOLO per la verifica del referto: orologio vero +30 giorni.

Non fa parte della suite (il nome non e' ``test_*.py`` e non e' tracciato in un
workflow): si carica a mano con ``-p verifica_orologio_pytest`` nella sola
verifica "gruppo 1 con il database live e l'orologio vero spostato avanti di 30
giorni". Usa ``time-machine``, che sostituisce l'ora VERA (C, ``datetime``,
``time.time``, ``pandas.Timestamp.now``) in tutta l'interprete, compreso
l'AppTest che esegue ``app.py`` in un namespace separato. ``tick=True`` fa
scorrere l'orologio spostato, come quello vero.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

GIORNI = int(os.environ.get("AVANTI_GIORNI", "30"))
_traveller = None


def pytest_configure(config):
    global _traveller
    import time_machine

    quando = datetime.now(timezone.utc) + timedelta(days=GIORNI)
    _traveller = time_machine.travel(quando, tick=True)
    _traveller.start()
    print(f"\n[orologio] ora VERA spostata avanti di {GIORNI} giorni: "
          f"{datetime.now(timezone.utc).isoformat()} (time.time()={time.time():.0f})")


def pytest_unconfigure(config):
    global _traveller
    if _traveller is not None:
        print(f"\n[orologio] ora VERA riportata: {datetime.now(timezone.utc).isoformat()}")
        _traveller.stop()
        _traveller = None
