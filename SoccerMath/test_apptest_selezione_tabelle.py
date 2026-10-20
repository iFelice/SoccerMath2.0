"""La spunta blu non resta: le tabelle cliccabili si consumano la selezione.

COSA VERIFICA (commessa «spunta blu che resta»)
-----------------------------------------------
Clic su una riga di una tabella cliccabile (le QUATTRO: «🏟️ Partite»,
«⚽ Pronostici», «🟰 Pareggi», «🎯 Multiple — Le più probabili»):

* (a) la scheda della partita si apre UNA volta;
* (b) nello stesso disegno la tabella è già senza righe selezionate: la
  spunta blu non resta, e quando il riquadro si chiude con la X (che non fa
  un nuovo disegno) la pagina resta com'è, tabella pulita;
* (c) selezionando di nuovo la STESSA riga la scheda si riapre;
* (d) tutto questo per ognuna delle tabelle cliccabili.

Meccanismo in prova (``app.chiave_tabella_pulita``): PRIMA di disegnare la
tabella si legge la selezione da ``st.session_state[chiave]``; se c'è una
riga, la richiesta della scheda viene salvata e la versione della chiave
della tabella sale — la tabella si disegna con una chiave NUOVA, quindi
senza selezione. La chiave corrente si legge con
``app.chiave_tabella_corrente(base, at.session_state)``: è lì che i test
impostano il clic.

In coda, la prova «mai None/nan/NaN» su TUTTE le tabelle dell'app: dove la
quota manca davvero la cella resta vuota — nessuna cella rende «None»,
«nan» o «NaN» (le celle numeriche mancanti sono l'unico vuoto ammesso, e la
colonna di testo non contiene MAI un non-numero).

Un solo AppTest (import ~40 s): i metodi hanno numeri perché l'ordine conta.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(HERE, "app.py")
for _p in (HERE, os.path.dirname(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_apptest_scheda_partita import _titolo_atteso  # noqa: E402
from test_apptest_scheda_pronostici import (  # noqa: E402
    ETICHETTA_CALCOLA,
    _BaseQuoteFinte,
)
from test_apptest_topmix_presentazione import (  # noqa: E402
    SCHEDA_MULTIPLE,
    SCHEDA_PAREGGI,
    SCHEDA_PARTITE,
    SCHEDA_PRONOSTICI,
    _elementi_della_tab,
)

#: Le quattro chiavi base delle tabelle cliccabili (le prime due hanno
#: ``app.CHIAVE_*``; Pronostici e Pareggi passano per ``_mostra_tabella_periodo``).
CHIAVE_PRONOSTICI = "pronostici_tabella_periodo"
CHIAVE_PAREGGI = "pareggi_tabella_periodo"


def _partita(casa, trasferta, utc, giornata, stato="SCHEDULED", gol=(None, None)):
    """Una riga di calendario nel formato della fonte (football-data)."""
    return {"utcDate": utc, "homeTeam": {"name": casa}, "awayTeam": {"name": trasferta},
            "matchday": giornata, "score": {"fullTime": {"home": gol[0], "away": gol[1]}},
            "status": stato}


class TestSpuntaNonRimane(_BaseQuoteFinte):
    """(a)(b)(c) su tutte e quattro le tabelle cliccabili (d)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import app as app_mod
        # Il calendario del fixture entra come «live_data» dell'app: la scheda
        # Partite lo mostra con la giornata 7. In piu' una partita SENZA quote:
        # le sue celle 1/X/2 devono restare vuote (prova in coda al file).
        matches = [dict(m) for m in cls.FIXTURE.calendario(cls.ADESSO)["matches"]]
        matches.append(_partita("Bologna", "Monza", "2027-05-01T15:00:00Z", 7))
        cls.at.session_state["live_data"] = matches
        cls.at.session_state["live_camp"] = "Serie A"
        chiavi = {app_mod.CHIAVE_CAMPIONATO_PARTITE: "Serie A"}
        for sb in cls.at.selectbox:
            if (sb.key or "") in chiavi:
                sb.set_value(chiavi[sb.key])
        cls.at.run(timeout=900)
        cls.eccezioni(cls.at, "giornata della scheda Partite")

    # ------------------------------------------------------------------ aiuti
    @classmethod
    def _chiave(cls, chiave_base):
        import app as app_mod
        return app_mod.chiave_tabella_corrente(chiave_base, cls.at.session_state)

    @classmethod
    def _tabella_per_chiave(cls, chiave_base, scheda):
        chiave = cls._chiave(chiave_base)
        return [e for e in _elementi_della_tab(cls.at, scheda, "dataframe")
                if str(getattr(e, "key", "") or "") == chiave]

    @classmethod
    def _indice_partita(cls, chiave_base, scheda, casa, trasferta):
        """L'indice della riga ``casa - trasferta`` nella tabella corrente.

        La cella «Partita» porta i nomi come arrivano dalla fonte della riga
        (quote o calendario): si confronta con quella stringa, mentre il titolo
        della scheda si aspetta i nomi di vista (``_titolo_atteso``).
        """
        tabelle = cls._tabella_per_chiave(chiave_base, scheda)
        if len(tabelle) != 1:
            raise AssertionError(f"{chiave_base}: {len(tabelle)} tabelle con la chiave corrente")
        df = tabelle[0].value
        if hasattr(df, "data"):
            df = df.data
        atteso = f"{casa} - {trasferta}"
        for i in range(len(df)):
            if str(df.iloc[i]["Partita"]) == atteso:
                return i
        raise AssertionError(f"nessuna riga {atteso!r} in {list(df['Partita'])}")

    @classmethod
    def _titoli_scheda(cls):
        return [str(getattr(el, "value", "") or "").strip() for el in cls.at.markdown]

    @classmethod
    def _partita_della_riga(cls, chiave_base, scheda, indice):
        """La coppia (casa, trasferta) della riga ``indice``, come nella cella."""
        tabelle = cls._tabella_per_chiave(chiave_base, scheda)
        df = tabelle[0].value
        if hasattr(df, "data"):
            df = df.data
        return tuple(s.strip() for s in str(df.iloc[indice]["Partita"]).split(" - ", 1))

    def _verifica_spunta(self, chiave_base, scheda_tab, casa, trasferta):
        """(a) si apre una volta, (b) tabella vuota nello stesso run, (c) si riapre."""
        import app as app_mod
        indice = self._indice_partita(chiave_base, scheda_tab, casa, trasferta)
        atteso = _titolo_atteso(casa, trasferta)
        # --- il clic: la selezione sulla chiave con cui la tabella e' ora ---
        chiave_prima = self._chiave(chiave_base)
        self.at.session_state[chiave_prima] = {
            "selection": {"rows": [indice], "columns": [], "cells": []}}
        self.at.run(timeout=900)
        self.eccezioni(self.at, f"clic riga {indice} di {chiave_base}")
        # (a) la scheda si apre, UNA volta (due titoli = aperta due volte)
        titoli = self._titoli_scheda()
        self.assertEqual(1, titoli.count("### " + atteso),
                         f"{chiave_base}: la scheda di {atteso} si apre "
                         f"{titoli.count('### ' + atteso)} volte")
        # (b) nello stesso run la tabella e' nata SENZA selezione: la chiave e'
        # cambiata (la tabella si e' ridisegnata pulita) e la chiave nuova non
        # ha righe selezionate.
        chiave_dopo = self._chiave(chiave_base)
        self.assertNotEqual(chiave_prima, chiave_dopo,
                            f"{chiave_base}: la versione della chiave sale dopo il clic")
        tabelle = self._tabella_per_chiave(chiave_base, scheda_tab)
        self.assertEqual(1, len(tabelle),
                         f"{chiave_base}: la tabella in vista usa la chiave nuova {chiave_dopo}")
        self.assertIsNone(app_mod.riga_selezionata(self.at.session_state.get(chiave_dopo)),
                          f"{chiave_base}: la tabella ridisegnata non ha righe selezionate")
        # La vecchia chiave non e' piu' quella di nessuna tabella in vista:
        # la spunta blu del clic non puo' restare sulla pagina.
        self.assertNotEqual(chiave_prima, str(getattr(tabelle[0], "key", "") or ""))
        # (c) la STESSA riga, di nuovo: la scheda si riapre
        self.at.session_state[chiave_dopo] = {
            "selection": {"rows": [indice], "columns": [], "cells": []}}
        self.at.run(timeout=900)
        self.eccezioni(self.at, f"secondo clic sulla stessa riga {indice} di {chiave_base}")
        titoli = self._titoli_scheda()
        self.assertEqual(1, titoli.count("### " + atteso),
                         f"{chiave_base}: la stessa riga cliccata due volte riapre la scheda")

    # -------------------------------------------------------------- (d) x 4
    def test_01_partite_la_spunta_non_rimane(self):
        import app as app_mod
        self._verifica_spunta(app_mod.CHIAVE_TABELLA_PARTITE, SCHEDA_PARTITE,
                              "Genoa", "Fiorentina")

    def test_02_pareggi_la_spunta_non_rimane(self):
        # La prima riga dei pareggi: la scheda mostra solo le X sopra il 30%
        # (Genoa 33% e Torino 31%), Napoli - Venezia (22%) non c'e' piu'.
        self._verifica_spunta(CHIAVE_PAREGGI, SCHEDA_PAREGGI, "Genoa", "Fiorentina")

    def test_03_multiple_la_spunta_non_rimane(self):
        import app as app_mod
        chiave = app_mod.CHIAVE_TABELLA_PIU_PROBABILI
        casa, trasferta = self._partita_della_riga(chiave, SCHEDA_MULTIPLE, 0)
        self._verifica_spunta(chiave, SCHEDA_MULTIPLE, casa, trasferta)

    def test_04_pronostici_la_spunta_non_rimane(self):
        # La tabella dei pronostici esiste solo dopo il click (e il click non
        # cambia il meccanismo della selezione).
        self._premi_click(self.at, ETICHETTA_CALCOLA)
        self._verifica_spunta(CHIAVE_PRONOSTICI, SCHEDA_PRONOSTICI, "Roma", "Lecce")

    # -------------------------------------------- mai "None"/"nan"/"NaN" ----
    NON_NUMERO = re.compile(r"\b(none|nan|nat)\b", re.IGNORECASE)

    def test_05_mai_none_nan_in_nessuna_tabella_dell_app(self):
        """Dove la quota manca davvero la cella resta VUOTA: nessuna tabella
        dell'app rende «None», «nan» o «NaN».

        Le celle si leggono come le legge la pagina: un non-numero numerico e'
        il vuoto delle colonne che si ordinano al clic (le uniche ammesse a
        mancare di un numero, vedi test_02b di test_apptest_scheda_partita);
        una colonna di TESTO invece contiene solo stringhe — se una di quelle
        fosse un None di Python o un NaN, la tabella trascritta (``to_string``,
        copia, stampa) scriverebbe «None»/«NaN», che e' esattamente la scritta
        vietata.
        """
        import pandas as pd
        # Le nuove celle O/U sono testo, anche quando la fonte legacy non le ha.
        pron = self._tabella_per_chiave(CHIAVE_PRONOSTICI, SCHEDA_PRONOSTICI)[0].value
        for nome in ("Gol", "Insieme %"):
            self.assertIn(nome, pron.columns)
            self.assertTrue(all(isinstance(v, str) for v in pron[nome]))
        tabelle = list(self.at.dataframe or [])
        if hasattr(self.at, "table"):
            tabelle += list(self.at.table or [])
        self.assertGreater(len(tabelle), 3, "l'app deve avere le sue tabelle da controllare")
        # Stesso controllo anche sulle celle NON vuote dello snapshot reale,
        # inclusa una partita O/U senza scelta 1X2 e una sotto soglia O/U.
        from types import SimpleNamespace
        from datetime import datetime, timezone
        from audit.totals_snapshot_fixture import payload_snapshot
        import app as app_mod
        snapshot = payload_snapshot()
        ora = datetime(2026, 10, 16, 13, 20, 26, tzinfo=timezone.utc)
        righe_ou, _ = app_mod.righe_pronostici_dalle_quote(snapshot, ora)
        normalizzate = [app_mod.riga_pronostico_da_mercato(r, ora) for r in righe_ou]
        df_ou, _ = app_mod.tabella_pronostici_visibile(normalizzate)
        self.assertTrue(any(df_ou["Gol"]))
        self.assertTrue(any(df_ou["Insieme %"]))
        self.assertIn("—", df_ou["Pronostico"].tolist())
        tabelle.append(SimpleNamespace(value=df_ou, key="snapshot_totals"))
        for el in tabelle:
            df = getattr(el, "value", None)
            if df is None:
                continue
            if hasattr(df, "data"):
                df = df.data
            if not isinstance(df, pd.DataFrame) or df.empty:
                continue
            chiave = str(getattr(el, "key", "") or "") or "<senza chiave>"
            for colonna in df.columns:
                numerica = pd.api.types.is_numeric_dtype(df[colonna])
                for cella in df[colonna].tolist():
                    if pd.isna(cella):
                        # Colonna numerica: il vuoto si puo' mancare (la cella
                        # e' vuota sullo schermo). Colonna di testo: NO — un
                        # None/NaN di testo e' la scritta «None»/«nan».
                        if not numerica:
                            self.fail(f"tabella {chiave}, colonna {colonna!r}: "
                                      f"cella di testo non-numero ({cella!r})")
                        continue
                    testo = str(cella)
                    self.assertIsNone(self.NON_NUMERO.search(testo),
                                      f"tabella {chiave}, colonna {colonna!r}: "
                                      f"cella {testo!r} rende un non-numero")
                    if numerica:
                        self.assertIsInstance(cella, (int, float),
                                              f"tabella {chiave}, colonna {colonna!r}: "
                                              f"cella {testo!r} non e' un numero")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
