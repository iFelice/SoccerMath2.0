"""Misura i due tempi richiesti dalla commessa di navigazione (punto 2).

    1. dall'apertura della scheda «🎯 Giocate» alla comparsa di
       «Per raddoppiare»;
    2. dall'apertura della scheda alla fine del confronto col modello.

Come si misura, e perche' cosi'. ``AppTest`` porta l'app a quiete prima di
restituire il controllo, quindi gli stati intermedi non si osservano dal test:
si mettono dei segnatempo DENTRO il giro, agganciandosi a funzioni che l'app
chiama davvero.

* apertura della scheda = prima chiamata a ``streamlit.set_page_config`` (prima
  istruzione Streamlit di ``app.py``);
* comparsa di «Per raddoppiare» = prima chiamata a
  ``lista_giocate.cerca_proposta_multipla``: il riquadro la chiama e poi si
  disegna, quindi e' l'istante immediatamente precedente alla resa;
* fine del confronto col modello = uscita dallo ``st.spinner`` con l'etichetta
  ``app.CONFRONTO_SPINNER`` ("Confronto con il nostro modello…"), che in
  ``concludi_confronto_modello`` avvolge esattamente ``fetch_and_calc_top_mix``.

Si aggancia ``streamlit`` e ``lista_giocate`` (moduli condivisi) e non ``app``:
``AppTest`` esegue ``app.py`` come ``__main__``, quindi rattoppare gli attributi
del modulo ``app`` non toccerebbe il giro in corso.

Cosa e' finto, dichiarato nel referto:

* le GET del calendario sono servite dal fixture (stesse partite dello
  snapshot): la latenza di rete di football-data NON entra nella misura, che
  quindi e' un LIMITE INFERIORE del tempo reale;
* la coda di rispetto del rate-limit fra una lega e l'altra
  (``time.sleep(6.5)``) e' invece LASCIATA VERA, perche' in produzione c'e';
* le quote sono lo snapshot reale pinnato (``snap_test.snapshot_reale``),
  l'orologio e' congelato a venerdì 2026-10-16 18:00 ora italiana.

Uso:  ``python audit/misura_tempi_apertura.py``
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
SOCCER = os.path.join(REPO_ROOT, "SoccerMath")
for _p in (SOCCER, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ADESSO = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)  # ven 18:00 Italia


class _Resp:
    def __init__(self, payload, code=200):
        self._payload, self.status_code = payload, code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def main():
    import config
    import lista_giocate as lg
    import market_odds
    import registry_store as rs
    import requests
    import snap_test
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    snap = snap_test.snapshot_reale()
    if snap is None:
        print("Snapshot pinnato non raggiungibile (clone shallow?): misura non eseguita.")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="sm_misura_tempi_"))
    for f in sorted(Path(SOCCER, "database").iterdir()):
        if f.is_dir() or f.name in ("live_odds.json", "predictions.json"):
            continue
        try:
            (tmp / f.name).symlink_to(f)
        except OSError:
            shutil.copy2(f, tmp / f.name)
    (tmp / "live_odds.json").write_text(json.dumps(snap), encoding="utf-8")
    (tmp / "predictions.json").write_text(json.dumps({"data": []}), encoding="utf-8")

    eventi_per_lega = {lega: (b.get("eventi") or [])
                       for lega, b in (snap.get("leghe") or {}).items() if b.get("eventi")}

    import app as app_mod
    league_code = {n: c.get("code") for n, c in app_mod.LEAGUES_CONFIG.items()}
    match_by_league = {}
    for i, (lega, eventi) in enumerate(sorted(eventi_per_lega.items())):
        match_by_league[lega] = [{
            "id": 9900000 + i * 1000 + j, "utcDate": ev.get("commence_time"),
            "homeTeam": {"name": ev.get("home_team")},
            "awayTeam": {"name": ev.get("away_team")}, "matchday": 8,
            "score": {"fullTime": {"home": None, "away": None}}, "status": "SCHEDULED",
        } for j, ev in enumerate(eventi)]

    def fake_get(url, **kw):
        code = url.rstrip("/").split("/")[-2] if "/matches" in url else ""
        for lega, code_league in league_code.items():
            if code == code_league and lega in match_by_league:
                return _Resp({"matches": match_by_league[lega]})
        return _Resp({"matches": []})

    def vieta(metodo):
        def _f(url, **kw):
            raise AssertionError(f"{metodo} di rete non ammesso: {url}")
        return _f

    # --- segnatempo -------------------------------------------------------
    t = {}

    set_page_config_vero = st.set_page_config

    def set_page_config_segna(*a, **k):
        t.setdefault("apertura", time.perf_counter())
        return set_page_config_vero(*a, **k)

    cerca_vera = lg.cerca_proposta_multipla

    def cerca_segna(*a, **k):
        t.setdefault("raddoppio", time.perf_counter())
        return cerca_vera(*a, **k)

    spinner_vero = st.spinner

    class _SpinnerSegna:
        def __init__(self, message="", *a, **k):
            self._etichetta = message
            self._interno = spinner_vero(message, *a, **k)

        def __enter__(self):
            if self._etichetta == app_mod.CONFRONTO_SPINNER:
                t["modello_inizio"] = time.perf_counter()
            return self._interno.__enter__()

        def __exit__(self, *exc):
            esito = self._interno.__exit__(*exc)
            if self._etichetta == app_mod.CONFRONTO_SPINNER:
                t["modello_fine"] = time.perf_counter()
            return esito

    storage = {"vivo": [], "ombra": []}
    with mock.patch.object(config, "DATABASE_DIR", tmp), \
         mock.patch.object(config, "PREDICTIONS_FILE", str(tmp / "predictions.json")), \
         mock.patch.object(market_odds, "_adesso_utc", lambda: ADESSO), \
         mock.patch.object(rs, "load_rows", lambda *a, **k: (list(storage["vivo"]), "f")), \
         mock.patch.object(rs, "save_rows",
                           lambda rows, *a, **k: storage["vivo"].extend(rows) or {"remoto": "ok"}), \
         mock.patch.object(rs, "load_ombra_rows", lambda *a, **k: (list(storage["ombra"]), "f")), \
         mock.patch.object(rs, "save_ombra_rows",
                           lambda rows, *a, **k: storage["ombra"].extend(rows) or {"remoto": "ok"}), \
         mock.patch.object(requests, "get", fake_get), \
         mock.patch.object(requests, "put", vieta("PUT")), \
         mock.patch.object(requests, "post", vieta("POST")), \
         mock.patch.object(requests, "patch", vieta("PATCH")), \
         mock.patch.object(requests, "delete", vieta("DELETE")), \
         mock.patch.object(st, "set_page_config", set_page_config_segna), \
         mock.patch.object(st, "spinner", _SpinnerSegna), \
         mock.patch.object(lg, "cerca_proposta_multipla", cerca_segna):
        st.cache_data.clear()
        at = AppTest.from_file(os.path.join(SOCCER, "app.py"), default_timeout=900)
        at.run(timeout=1800)
        t["fine_giro"] = time.perf_counter()
        eccezioni = [str(e.value) for e in at.exception]
        stato = at.session_state.get("confronto_modello_stato")

    shutil.rmtree(tmp, ignore_errors=True)

    if eccezioni:
        print(f"Misura non valida: eccezioni {eccezioni[:1]}")
        return 1

    apertura = t.get("apertura")
    if apertura is None:
        print("Segnatempo di apertura mancante: misura non valida.")
        return 1
    raddoppio = (t["raddoppio"] - apertura) if "raddoppio" in t else None
    modello = (t["modello_fine"] - apertura) if "modello_fine" in t else None
    coda = (t["modello_fine"] - t["modello_inizio"]) if "modello_fine" in t else None
    giro = t["fine_giro"] - apertura

    print("=== Tempi di apertura della scheda «🎯 Giocate» (snapshot reale) ===")
    print(f"stato del confronto col modello : {stato}")
    print(f"apertura -> «Per raddoppiare»   : {raddoppio:.2f} s" if raddoppio is not None
          else "apertura -> «Per raddoppiare»   : non misurato")
    print(f"apertura -> fine confronto      : {modello:.2f} s" if modello is not None
          else "apertura -> fine confronto      : non misurato")
    print(f"  di cui solo confronto         : {coda:.2f} s" if coda is not None else "")
    print(f"apertura -> fine giro completo  : {giro:.2f} s")
    print("Nota: GET del calendario servite dal fixture (latenza di rete esclusa,")
    print("quindi limite inferiore); coda di rate-limit fra le leghe lasciata vera.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
