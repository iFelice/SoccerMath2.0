"""AppTest della scheda partita GRAFICA sul vero ``app.py``.

Stessa fixture degli altri AppTest (snapshot pinnato, orologio congelato,
rete finta, database in tmp): si apre la scheda «🏟️ Partite», si seleziona
la riga di Bologna-Inter e nel riquadro devono esserci le CINQUE sezioni
HTML di ``scheda_grafica`` (Probabilità, Classifica, Forma, Gol,
Precedenti in stagione), con l'intestazione (partita, data e ora,
campionato, giornata).

Il controllo si fa due volte: con il tema SCURO (sotto AppTest
``st.context.theme.type`` non e' disponibile, quindi vale la ricaduta
"dark" di ``app._tema_scheda_grafica``) e con il tema CHIARO (la
proprieta' del tema di Streamlit viene forzata a "light" per la durata
del ridisegno). In entrambi i casi, e in tutto il testo del riquadro,
non deve comparire ``None``, ``nan`` o ``NaN``.

Altri due controlli: con l'interruttore «Segui tema sistema»
(``follow_system_toggle``) SPENTO la pagina e' forzata in chiaro e la
scheda deve usare la palette chiara anche senza context; e una scheda
la cui richiesta non porta la giornata (come quelle aperte da
Pronostici, che nascono dalle quote e non dal calendario) mostra nella
didascalia solo data, ora e campionato: niente «Giornata» e niente
«n/d».
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
for _p in (HERE, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_apptest_scheda_partita import RENDER_VERTICE, _BaseScheda  # noqa: E402

import scheda_grafica as sgr  # noqa: E402

TITOLI_SEZIONI = ("Probabilità", "Classifica", "Forma: ultime 5 partite",
                  "Gol", "Precedenti in stagione")


class TestSchedaGraficaAppTest(_BaseScheda):
    """Un solo AppTest: apertura della scheda e controllo delle sezioni."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from streamlit.testing.v1 import AppTest
        cls.at = AppTest.from_file(
            os.path.join(HERE, "app.py"), default_timeout=300)
        cls.at.run(timeout=900)
        cls.eccezioni(cls.at, "apertura della pagina")

    # -- utilita' ----------------------------------------------------------
    def _testo_scheda(self, titolo: str) -> str:
        valori = [str(getattr(el, "value", "") or "") for el in self.at.markdown]
        atteso = f"### {titolo}"
        for i, v in enumerate(valori):
            if v.strip() == atteso:
                return "\n".join(valori[i:])
        raise AssertionError(
            f"riquadro {atteso!r} non trovato fra: "
            f"{[v[:40] for v in valori if v.startswith('###')]}")

    def _apri_bologna_inter(self, tema_forzato=None):
        """Seleziona la riga Bologna-Inter e (ri)apre il riquadro.

        Con ``tema_forzato`` la proprieta' ``theme`` del context di
        Streamlit viene forzata per la durata del ridisegno che apre il
        riquadro: e' il modo di far leggere ad ``app`` un
        ``st.context.theme.type`` "light" sotto AppTest, dove il context
        del browser non esiste.
        """
        import app as app_mod
        self._carica_giornata(self.at, RENDER_VERTICE[0])
        indice = self._indice_riga(self.at, *RENDER_VERTICE[1:])
        chiave = app_mod.chiave_tabella_corrente(
            app_mod.CHIAVE_TABELLA_PARTITE, self.at.session_state)
        self.at.session_state[chiave] = {
            "selection": {"rows": [int(indice)], "columns": [], "cells": []}}
        if tema_forzato is None:
            self.at.run(timeout=900)
        else:
            from streamlit.runtime.context import (ContextProxy,
                                                    StreamlitTheme)
            with mock.patch.object(
                    ContextProxy, "theme",
                    new_callable=mock.PropertyMock,
                    return_value=StreamlitTheme({"type": tema_forzato})):
                self.at.run(timeout=900)
        self.eccezioni(self.at, f"apertura scheda (tema {tema_forzato})")
        from test_apptest_scheda_partita import _titolo_atteso
        return self._testo_scheda(_titolo_atteso(*RENDER_VERTICE[1:]))

    def _controlla_cinque_sezioni(self, testo: str, palette: str,
                                  giornata: bool = True):
        self.assertEqual(
            5, testo.count('class="sg sg-sezione"'),
            "le sezioni HTML della scheda devono essere cinque")
        for titolo in TITOLI_SEZIONI:
            with self.subTest(sezione=titolo):
                self.assertIn(titolo, testo)
        self.assertIn(sgr.PALETTE[palette]["sfondo"], testo,
                      f"la palette {palette} deve essere quella disegnata")
        for brutta in (r"\bNone\b", r"\bnan\b", r"\bNaN\b"):
            with self.subTest(brutta=brutta):
                self.assertIsNone(re.search(brutta, testo),
                                  f"{brutta} nel testo della scheda")
        # L'intestazione: partita, data e ora, campionato (e, se nota
        # dalla richiesta, anche la giornata).
        didascalie = "\n".join(str(getattr(el, "value", "") or "")
                               for el in self.at.caption)
        self.assertIn(RENDER_VERTICE[0], didascalie)
        if giornata:
            self.assertIn("Giornata 8", didascalie)

    # -- i due temi ---------------------------------------------------------
    def test_01_cinque_sezioni_tema_scuro(self):
        """Senza context del browser: ricaduta "dark", palette scura."""
        import app as app_mod
        self.assertEqual("dark", self._tema_atteso())
        testo = self._apri_bologna_inter()
        self._controlla_cinque_sezioni(testo, "scuro")
        self.assertTrue(callable(app_mod._tema_scheda_grafica))

    def test_02_cinque_sezioni_tema_chiaro(self):
        """Con theme.type forzato a "light": palette chiara."""
        testo = self._apri_bologna_inter(tema_forzato="light")
        self._controlla_cinque_sezioni(testo, "chiaro")

    def test_03_interruttore_spento_palette_chiara(self):
        """«Segui tema sistema» spento: pagina forzata in chiaro.

        Sotto AppTest il context non dice "light" (dice None, quindi la
        sola regola del context darebbe il fallback dark): con
        l'interruttore spento la scheda deve comunque disegnarsi con la
        palette chiara, come il resto della pagina forzata.
        """
        self.assertEqual("dark", self._tema_atteso(),
                         "senza interruttore varrebbe il fallback dark")
        interruttore = self._toggle(self.at, "follow_system_toggle")
        interruttore.set_value(False)
        self.at.run(timeout=900)
        self.eccezioni(self.at, "interruttore del tema spento")
        self.assertFalse(self._toggle(self.at, "follow_system_toggle").value)
        testo = self._apri_bologna_inter()
        self._controlla_cinque_sezioni(testo, "chiaro")
        self.assertNotIn(sgr.PALETTE["scuro"]["sfondo"], testo)

    def test_04_scheda_da_pronostici_senza_giornata(self):
        """Una richiesta senza giornata: didascalia senza «Giornata».

        E' la richiesta che arriva dalle schede delle quote (Pronostici
        e le altre tabelle), dove la riga nasce dalle quote e non dal
        calendario: lega, squadre e orario, nessun matchday. La
        didascalia deve mostrare solo data, ora e campionato: niente
        «Giornata» (niente stima dalle giornate giocate) e niente «n/d».
        """
        import app as app_mod
        from team_names import resolve_team_name
        from test_apptest_scheda_partita import _titolo_atteso

        def _can(nome):
            return resolve_team_name(nome).canonical

        evento = next(ev for ev in self.eventi_per_lega[RENDER_VERTICE[0]]
                      if _can(ev.get("home_team")) == _can(RENDER_VERTICE[1])
                      and _can(ev.get("away_team")) == _can(RENDER_VERTICE[2]))
        # La richiesta come nasce dalle righe delle quote: i nomi grezzi
        # della fonte (casa "Bologna", trasferta "Inter Milan") e
        # l'orario, nessun matchday del calendario.
        self.at.session_state[app_mod.SCHEDA_PARTITA_APERTA_CHIAVE] = {
            "lega": RENDER_VERTICE[0], "casa": evento.get("home_team"),
            "trasferta": evento.get("away_team"),
            "kickoff_utc": evento.get("commence_time"),
        }
        self.at.run(timeout=900)
        self.eccezioni(self.at, "scheda da Pronostici senza giornata")
        testo = self._testo_scheda(_titolo_atteso(*RENDER_VERTICE[1:]))
        self.assertEqual(5, testo.count('class="sg sg-sezione"'))
        didascalia_scheda = next(
            c for c in (str(getattr(el, "value", "") or "")
                        for el in self.at.caption)
            if RENDER_VERTICE[0] in c and "·" in c
            and re.search(r"\d{2}/\d{2}", c))
        self.assertNotIn("Giornata", didascalia_scheda)
        self.assertNotIn("n/d", didascalia_scheda)
        # Data e ora restano, il campionato pure.
        self.assertRegex(didascalia_scheda, r"\d{2}/\d{2}")
        self.assertRegex(didascalia_scheda, r"\d{2}:\d{2}")

    @staticmethod
    def _tema_atteso() -> str:
        """Il tema che l'app sceglie qui: sotto AppTest il context non c'e'."""
        try:
            import streamlit as st
            tipo = st.context.theme.type
        except Exception:
            tipo = None
        return "light" if str(tipo or "").lower() == "light" else "dark"


if __name__ == "__main__":
    unittest.main(verbosity=2)
