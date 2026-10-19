"""AppTest della «scheda partita» (palla di vetro in parole) sul VERO ``app.py``.

Stessa fixture dei test di navigazione e di presentazione del Top Mix: snapshot
reale pinnato di ``live_odds.json``, database in una cartella temporanea,
orologio congelato a venerdi' 2026-10-16 18:00 ora italiana, rete finta,
registro in memoria. Nessun file reale viene toccato e nessuna chiamata di rete
parte da qui.

Cosa verifica, in parole povere:

* dalla scheda «🎯 Multiple», selezionare una riga di «Le più probabili» apre
  il RIQUADRO della partita giusta (i due nomi della riga sono quelli del
  titolo) con i blocchi in parole: probabilità dalle quote, classifica e
  obiettivi, forma, gol, precedenti — nessun pulsante «Scheda» nella scheda;
* dalla scheda «🏟️ Partite» — la PRIMA scheda, sempre in vista — la giornata si
  sceglie con i due selettori in testa (campionato e giornata) e la tabella
  elenca TUTTE le partite di quella giornata di quel campionato: quando si
  giocano, le probabilità 1/X/2 delle quote, il pronostico (lo stesso del Top
  Mix, sotto il 57% un trattino) e, per le
  partite già giocate, il risultato al posto delle probabilità. Selezionare la
  riga N apre la scheda della partita N (i pulsanti «Scheda» non esistono più);
* l'analisi odierna (Analisi Rapida e card del modello) sta DENTRO il riquadro
  chiuso «🔎 Dettagli» in fondo alla scheda: fuori non compaiono ne' quelle
  voci ne' le parole vietate del punto 6 della PR #64 (elenco unico in
  ``test_apptest_topmix_presentazione``), e nessuna cella scrive "None" o "nan";
* [facoltativo] con la variabile d'ambiente ``SCHEDA_RENDER_OUT`` impostata, il
  test SCRIVE nel file indicato il testo reso di due partite reali del prossimo
  turno (una di vertice e una di bassa classifica), preso dal riquadro aperto
  in AppTest: e' l'evidenza che accompagna la PR, non un testo scritto a mano.

Il riquadro e' un ``st.dialog`` (Streamlit >= 1.50, il minimo richiesto da
``SoccerMath/requirements.txt``): con una versione piu' vecchia il contenuto
viene disegnato in un ``st.expander`` sotto la riga, con lo stesso testo.
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(HERE, "app.py")
REPO_ROOT = os.path.dirname(HERE)
for _p in (HERE, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# La fixture (database in tmp, snapshot, orologio fermo, rete finta) e le
# utilita' di lettura del testo sono le stesse degli altri AppTest: una sola
# definizione per tutti.
from test_apptest_navigazione import _BaseAppTest, _iso  # noqa: E402
from test_apptest_topmix_presentazione import (  # noqa: E402
    PAROLE_VIETATE,
    SCHEDA_PARTITE,
    _elementi_della_tab,
    _testi_della_tab,
)

from display_names import display_name  # noqa: E402
from team_names import resolve_team_name  # noqa: E402

import market_odds as mo  # noqa: E402

#: Le due partite del prossimo turno di cui si stampa il testo reso: una di
#: vertice (Serie A) e una di bassa classifica (Ligue 1).
RENDER_VERTICE = ("Serie A", "Bologna", "Inter")
RENDER_BASSA = ("Ligue 1", "Le Havre", "Auxerre")


# ---------------------------------------------------------------------------
# Partite aggiunte al calendario della fixture (non sono nello snapshot, quindi
# la fonte delle quote non le copre: servono proprio a questo).
# ---------------------------------------------------------------------------
def _partita(casa, trasferta, utc, giornata, stato="SCHEDULED", gol=(None, None)):
    """Una riga di calendario nel formato della fonte (football-data)."""
    return {"utcDate": utc, "homeTeam": {"name": casa}, "awayTeam": {"name": trasferta},
            "matchday": giornata, "score": {"fullTime": {"home": gol[0], "away": gol[1]}},
            "status": stato}


#: Da giocare, senza quote: le tre celle 1/X/2 restano vuote.
EXTRA_SENZA_QUOTE = _partita("Bologna", "Monza", "2027-05-01T15:00:00Z", 8)
#: Gia' giocata: la tabella mostra il risultato al posto delle probabilita'.
EXTRA_GIA_GIOCATA = _partita("Inter", "Monza", "2027-05-02T15:00:00Z", 8,
                             stato="FINISHED", gol=(2, 1))
#: Una seconda giornata: per cambiare la tabella col selettore della giornata.
EXTRA_GIORNATA_9 = [_partita("Bologna", "Inter", "2027-05-08T15:00:00Z", 9),
                    _partita("Monza", "Bologna", "2027-05-09T15:00:00Z", 9)]


def _nomi_mostrati(nome: str) -> str:
    """Il nome come lo mostra la scheda (risoluzione + nome di vista)."""
    risolto = resolve_team_name(nome)
    return display_name(risolto.canonical) if risolto.mapped else str(nome)


def _titolo_atteso(casa: str, trasferta: str) -> str:
    return f"{_nomi_mostrati(casa)} - {_nomi_mostrati(trasferta)}"


class _BaseScheda(_BaseAppTest):
    """Fixture comune piu' il calendario della giornata per la scheda Partite."""

    @classmethod
    def _live_data(cls, lega: str, extra=None) -> list:
        """Le partite del prossimo turno di ``lega`` (quote dallo snapshot).

        Le date sono quelle degli eventi dello snapshot: tutte DOPO l'orologio
        congelato, cosi' sono le partite in programma. La giornata e' la 8 per
        tutte (la stessa delle altre fixture).
        """
        fuori = []
        for j, ev in enumerate(cls.eventi_per_lega.get(lega, [])):
            if not ev.get("commence_time") or ev["commence_time"] <= _iso(cls.ADESSO):
                continue
            fuori.append({
                "id": 9800000 + len(fuori),
                "utcDate": ev.get("commence_time"),
                "homeTeam": {"name": ev.get("home_team")},
                "awayTeam": {"name": ev.get("away_team")},
                "matchday": 8,
                "score": {"fullTime": {"home": None, "away": None}},
                "status": "SCHEDULED",
            })
        for k, m in enumerate(extra or []):
            m = dict(m)
            m["id"] = 9790000 + k
            fuori.append(m)
        return fuori

    @classmethod
    def _carica_giornata(cls, at, lega: str, extra=None, giornata=None):
        """Mette in ``session_state`` il calendario e sceglie la scheda.

        La giornata e' la PRIMA scheda («🏟️ Partite»), sempre in vista: non
        serve nessun interruttore. Campionato e giornata si scelgono con i due
        selettori in testa alla scheda, presi per CHIAVE (in pagina c'e' anche il
        selettore del campionato della barra laterale: l'etichetta da sola non
        basta a distinguerli)."""
        import app as app_mod
        # La scheda Partite NON legge piu' ``live_data``: il suo calendario
        # arriva da ``calendario_campionato`` (football-data finto). Le partite
        # extra entrano nella risposta della lega; ``live_data`` resta in
        # sessione solo come calendario della barra laterale e come atteso del
        # test (nomi e conteggi).
        calendario = cls._live_data(lega, extra)
        cls._extra_calendario[lega] = calendario
        at.session_state["live_data"] = calendario
        at.session_state["live_camp"] = lega
        chiavi = {app_mod.CHIAVE_CAMPIONATO_PARTITE: lega,
                  app_mod.CHIAVE_GIORNATA_PARTITE: giornata}
        for sb in at.selectbox:
            if (sb.key or "") in chiavi and chiavi[sb.key] is not None:
                sb.set_value(chiavi[sb.key])
        # ``calendario_campionato`` e' in cache (ttl 900): il calendario finto
        # e' appena cambiato, quindi la cache va svuotata o la scheda
        # ridisegnerebbe il turno precedente.
        import streamlit as st
        st.cache_data.clear()
        at.run(timeout=900)
        cls.eccezioni(at, f"giornata di {lega}")

    @staticmethod
    def _testo_giornata(at):
        """(fuori, dentro) della scheda «🏟️ Partite».

        Nella scheda non c'e' altro che la giornata: i selettori in testa, la
        tabella e il riquadro chiuso «Dettagli». Elo e Backtest stanno in
        «🔧 Strumenti avanzati», che qui non viene nemmeno acceso."""
        fuori, dentro = _testi_della_tab(at, SCHEDA_PARTITE)
        if not fuori:
            raise AssertionError("la scheda «🏟️ Partite» non rende niente")
        return fuori, dentro

    @classmethod
    def _tabella_giornata(cls, at):
        """Il DataFrame della giornata: l'unica tabella della scheda Partite."""
        import app as app_mod
        chiave = app_mod.chiave_tabella_corrente(app_mod.CHIAVE_TABELLA_PARTITE,
                                                 at.session_state)
        tabelle = [e for e in _elementi_della_tab(at, SCHEDA_PARTITE, "dataframe")
                   if str(getattr(e, "key", "") or "") == chiave]
        if len(tabelle) != 1:
            raise AssertionError(f"una sola tabella nella scheda Partite, "
                                 f"trovate {len(tabelle)} (chiave {chiave})")
        df = tabelle[0].value
        if hasattr(df, "data"):
            df = df.data
        return df

    @classmethod
    def _indice_riga(cls, at, casa: str, trasferta: str) -> int:
        """L'indice della riga della partita casa-trasferta nella tabella."""
        df = cls._tabella_giornata(at)
        atteso = _titolo_atteso(casa, trasferta)
        for i in range(len(df)):
            if str(df.iloc[i]["Partita"]) == atteso:
                return i
        raise AssertionError(f"nessuna riga {atteso!r} in {list(df['Partita'])}")

    @classmethod
    def _seleziona_riga(cls, at, indice: int):
        """Il clic sulla riga: la selezione della tabella (come nelle altre schede).

        La selezione va impostata sulla chiave con cui la tabella e' disegnata
        in questo momento (``chiave_tabella_corrente``): ogni riga cliccata alza
        la versione della chiave, e il clic successivo usa la chiave nuova.
        """
        import app as app_mod
        chiave = app_mod.chiave_tabella_corrente(app_mod.CHIAVE_TABELLA_PARTITE,
                                                 at.session_state)
        at.session_state[chiave] = {
            "selection": {"rows": [indice], "columns": [], "cells": []}}
        at.run(timeout=900)
        cls.eccezioni(at, f"selezione della riga {indice}")

    @staticmethod
    def _testo_riquadro(at, titolo: str = None) -> str:
        """Il testo del riquadro della scheda (markdown di primo livello).

        Con ``titolo`` il testo parte dal titolo del riquadro
        (``### Casa - Trasferta``): e' l'unico modo di non catturare anche il
        resto della pagina disegnata sotto, che il riquadro non e' la scheda.
        """
        valori = [str(getattr(el, "value", "") or "") for el in at.markdown]
        if titolo is None:
            return "\n".join(valori)
        atteso = f"### {titolo}"
        for i, v in enumerate(valori):
            if v.strip() == atteso:
                return "\n".join(valori[i:])
        raise AssertionError(f"riquadro {atteso!r} non trovato fra: "
                             f"{[v[:40] for v in valori if v.startswith('###')]}")

    @staticmethod
    def _valori_colonna(df, colonna):
        """I valori di una colonna come li legge la tabella (NaN -> ``None``)."""
        import pandas as pd
        return [None if pd.isna(v) else v for v in df[colonna].tolist()]

    @classmethod
    def _percentuali_colonna(cls, df, colonna):
        """Le celle «56,3%» di 1/X/2 come numeri (``None`` se la cella e' vuota)."""
        fuori = []
        for v in df[colonna].tolist():
            testo = str(v).strip()
            if not testo:
                fuori.append(None)
            else:
                fuori.append(float(testo.replace("%", "").replace(",", ".")))
        return fuori


class TestSchedaPartitaAppTest(_BaseScheda):
    """Un solo AppTest, piu' disegni: apertura, dialog, giornata, render."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from streamlit.testing.v1 import AppTest
        cls.at = AppTest.from_file(APP_PATH, default_timeout=300)
        cls.at.run(timeout=900)
        cls.eccezioni(cls.at, "apertura della pagina")
        cls.render_out = os.environ.get("SCHEDA_RENDER_OUT")
        # Le evidenze facoltative non possono sovrascrivere file del checkout,
        # nemmeno se una variabile d'ambiente punta a un referto tracciato.
        if cls.render_out and Path(cls.render_out).resolve().is_relative_to(Path(REPO_ROOT).resolve()):
            cls.render_out = str(cls.tmp / "render-opzionale.txt")

    # -- 1. dalla riga di «Le più probabili» della scheda Multiple -----------
    def test_01_la_riga_selezionata_apre_la_partita_giusta(self):
        import app as app_mod
        from test_apptest_topmix_presentazione import SCHEDA_MULTIPLE, _elementi_della_tab
        # Nella scheda Multiple non c'e' nessun pulsante «Scheda»: il clic e' la
        # selezione della riga della tabella, come in Pronostici e Pareggi.
        self.assertEqual([], [b for b in self.at.button
                              if (b.key or "").startswith(("scheda_piu_probabili_",
                                                           "scheda_raddoppio_"))])
        self.assertEqual([], [b for b in _elementi_della_tab(self.at, SCHEDA_MULTIPLE, "button")
                              if (b.label or "").strip() == "Scheda"])
        chiave_piu_probabili = app_mod.chiave_tabella_corrente(
            app_mod.CHIAVE_TABELLA_PIU_PROBABILI, self.at.session_state)
        tabelle = [e for e in _elementi_della_tab(self.at, SCHEDA_MULTIPLE, "dataframe")
                   if str(getattr(e, "key", "") or "") == chiave_piu_probabili]
        self.assertEqual(1, len(tabelle), "«Le più probabili» e' una tabella sola")
        df = tabelle[0].value
        if hasattr(df, "data"):
            df = df.data
        self.assertGreaterEqual(len(df), 2)
        # La riga porta i nomi come arrivano dalle quote; il titolo della scheda
        # porta i nomi di vista (es. «Borussia Dortmund» -> «Dortmund»): la
        # stessa risoluzione dei due lati.
        casa, trasferta = [x.strip() for x in str(df.iloc[1]["Partita"]).split(" - ", 1)]
        atteso = _titolo_atteso(casa, trasferta)
        self.at.session_state[chiave_piu_probabili] = {
            "selection": {"rows": [1], "columns": [], "cells": []}}
        self.at.run(timeout=900)
        self.eccezioni(self.at, "apertura della scheda dalla riga di «Le più probabili»")
        testo = self._testo_riquadro(self.at, atteso)
        for titolo in ("Probabilità (dalle quote dei bookmaker)",
                       "Classifica e obiettivi",
                       "Forma: ultime 5 partite di campionato",
                       "Gol", "Precedenti stagionali"):
            with self.subTest(blocco=titolo):
                self.assertIn(titolo, testo)
        self.assertIn(f"### {atteso}", testo,
                      "il riquadro deve essere quello della partita della riga")
        self.assertIn(_nomi_mostrati(trasferta), testo,
                      "nel riquadro ci sono i nomi delle due squadre della riga")
        self.assertIn("Quote %", testo)
        self.assertIn("Modello %", testo)
        # In vista, in chiaro: le percentuali delle quote e i punti delle due
        # squadre. Nessun punteggio o indice inventato dalla scheda.
        self.assertRegex(testo, r"Quote % \d+,\d")
        # La riga delle probabilita' e' quella delle tabelle di «Giocate»: la
        # sigla dell'esito e i due NUMERI, senza parentesi e senza il simbolo %.
        for esito in ("1", "X", "2"):
            with self.subTest(esito=esito):
                self.assertRegex(testo, rf"(?m)^{esito} · Quote % \d+,\d · Modello % ")
        self.assertIsNone(re.search(r"\d+,\d\s*%", testo),
                          "nella scheda la percentuale resta un numero, senza simbolo")
        self.assertRegex(testo, r"\d+° posto")
        for parola in PAROLE_VIETATE:
            with self.subTest(parola=parola):
                self.assertIsNone(re.search(parola, testo, re.IGNORECASE),
                                  f"parola vietata nella scheda: {parola!r}")

    # -- 2. la scheda Partite: la tabella della giornata --------------------
    def test_02_la_giornata_e_in_tabella(self):
        """Una riga per partita della giornata scelta, nel campionato scelto.

        Il conteggio atteso e' quello del CALENDARIO della fixture (le partite
        della giornata 8 di Serie A), contato qui e non riletto dall'app: se la
        tabella ne mostra di piu' o di meno, il test lo dice.
        """
        import app as app_mod
        self._carica_giornata(self.at, "Serie A",
                              extra=[EXTRA_SENZA_QUOTE, EXTRA_GIA_GIOCATA])
        df = self._tabella_giornata(self.at)
        calendario = [m for m in self.at.session_state["live_data"]
                      if int(m["matchday"]) == 8]
        self.assertEqual(len(calendario), len(df),
                         "una riga per ogni partita della giornata del calendario")
        self.assertEqual(list(app_mod.COLONNE_PARTITE), list(df.columns),
                         "le colonne della tabella, in quest'ordine")
        self.assertEqual({_titolo_atteso(m["homeTeam"]["name"], m["awayTeam"]["name"])
                          for m in calendario},
                         {str(p) for p in df["Partita"].tolist()},
                         "le righe sono le partite del calendario, «Casa - Trasferta»")
        # I pulsanti «Scheda» non esistono piu': si clicca la riga.
        self.assertEqual([], [b for b in self.at.button
                              if (b.key or "").startswith("partite_scheda_")])
        # «Quando»: lo stesso formato delle altre schede, con il marcatore ⏳
        # sulle partite che giocano fra piu' di tre giorni.
        for quando in df["Quando"].tolist():
            with self.subTest(quando=quando):
                self.assertRegex(str(quando),
                                 r"^(lun|mar|mer|gio|ven|sab|dom) \d{2}/\d{2}, "
                                 r"\d{2}:\d{2}( ⏳)?$")
        # 1, X, 2 sono TESTO con una cifra decimale e la virgola italiana
        # («56,3%»), perche' le partite giocate e quelle senza quote hanno la
        # cella vuota e una NumberColumn scriverebbe «None»; «Pronostico» e' lo
        # STESSO pronostico del Top Mix: l'esito piu' alto della riga, ma solo
        # se arriva a SOGLIA_TOPMIX_MERCATO (sotto, un trattino).
        p1, px, p2 = (self._percentuali_colonna(df, c) for c in ("1", "X", "2"))
        pronostici = [str(x) for x in df["Pronostico"].tolist()]
        for i in range(len(df)):
            terna = {"1": p1[i], "X": px[i], "2": p2[i]}
            with self.subTest(riga=int(i), partita=str(df.iloc[i]["Partita"])):
                if any(v is None for v in terna.values()):
                    self.assertEqual("", pronostici[i],
                                     "senza numeri nessun pronostico inventato")
                    continue
                for esito, v in terna.items():
                    self.assertEqual(round(float(v), 1), float(v),
                                     f"{esito}: una cifra decimale")
                    self.assertTrue(0.0 < float(v) < 100.0, f"{esito}: {v}")
                # Lo stesso pronostico del Top Mix: l'esito piu' alto solo se
                # arriva al 57%, altrimenti il trattino. Le celle sono
                # arrotondate a una cifra: chi sfiora la soglia vale il massimo.
                migliore = max(("1", "X", "2"), key=lambda e: terna[e])
                atteso = mo.esito_ammesso(
                    {e: float(terna[e]) / 100.0 for e in terna})
                if atteso == mo.TRATTINO_PRONOSTICO and (
                        float(terna[migliore]) / 100.0
                        >= mo.SOGLIA_TOPMIX_MERCATO - 0.0005):
                    atteso = migliore
                self.assertEqual(atteso, pronostici[i],
                                 "il pronostico e' quello del Top Mix")
        self.assertTrue(any(v is not None for v in p1),
                        "lo snapshot ha le quote: almeno una riga deve mostrarle")
        self.assertTrue(any(v is None for v in p1),
                        "la partita senza quote deve avere le celle vuote")

    def test_02b_senza_quote_celle_vuote_e_partita_giocata_col_risultato(self):
        """Le due righe speciali: senza quote (celle vuote) e gia' giocata.

        Di una partita conclusa la tabella mostra il RISULTATO al posto delle
        probabilita': le quote di una partita gia' giocata non dicono niente.
        """
        df = self._tabella_giornata(self.at)
        p1, px, p2 = (self._valori_colonna(df, c) for c in ("1", "X", "2"))
        i_senza = self._indice_riga(self.at, EXTRA_SENZA_QUOTE["homeTeam"]["name"],
                                    EXTRA_SENZA_QUOTE["awayTeam"]["name"])
        self.assertEqual(("", "", ""), (p1[i_senza], px[i_senza], p2[i_senza]),
                         "senza quote le tre celle restano vuote")
        self.assertEqual("", str(df.iloc[i_senza]["Risultato"]),
                         "una partita da giocare non ha un risultato")
        i_giocata = self._indice_riga(self.at, EXTRA_GIA_GIOCATA["homeTeam"]["name"],
                                      EXTRA_GIA_GIOCATA["awayTeam"]["name"])
        self.assertEqual("2-1", str(df.iloc[i_giocata]["Risultato"]),
                         "la partita giocata mostra il risultato finale")
        self.assertEqual(("", "", ""), (p1[i_giocata], px[i_giocata], p2[i_giocata]),
                         "il risultato prende il posto delle probabilita'")
        self.assertEqual("", str(df.iloc[i_giocata]["Pronostico"]),
                         "su una partita conclusa nessun pronostico")

    def test_02c_nel_testo_reso_nessun_none_e_nessuna_parola_vietata(self):
        """Il testo reso della scheda: pulito, e tecnico solo nei Dettagli."""
        fuori, dentro = self._testo_giornata(self.at)
        testo = "\n".join(fuori)
        for riga_testo in fuori + dentro:
            for brutta in (r"\bNone\b", r"\bnan\b"):
                with self.subTest(testo=riga_testo[:40], brutta=brutta):
                    self.assertIsNone(re.search(brutta, riga_testo, re.IGNORECASE),
                                      "nessuna cella scrive None o nan")
        # L'analisi odierna sta DENTRO «Dettagli» (riquadro chiuso), non in vista.
        self.assertIn("Analisi Rapida", "\n".join(dentro))
        self.assertNotIn("Analisi Rapida", testo)
        etichette = [str(e.label or "") for e in self.at.expander]
        self.assertTrue(any(e.strip().endswith("Dettagli") for e in etichette), etichette)
        for parola in PAROLE_VIETATE:
            with self.subTest(parola=parola):
                self.assertIsNone(re.search(parola, testo, re.IGNORECASE),
                                  f"parola vietata fuori dai Dettagli: {parola!r}")

    def test_02d_cambiare_campionato_cambia_le_partite(self):
        """Il selettore del campionato decide di quale campionato e' la tabella."""
        self._carica_giornata(self.at, RENDER_BASSA[0])
        df = self._tabella_giornata(self.at)
        calendario = [m for m in self.at.session_state["live_data"]
                      if int(m["matchday"]) == 8]
        self.assertEqual(len(calendario), len(df),
                         "il conteggio e' quello del calendario di questo campionato")
        self.assertIn(_titolo_atteso(*RENDER_BASSA[1:]),
                      {str(p) for p in df["Partita"].tolist()})
        fuori, _ = self._testo_giornata(self.at)
        self.assertIn(f"{RENDER_BASSA[0].upper()} - GIORNATA 8", "\n".join(fuori))

    def test_02e_cambiare_giornata_cambia_la_tabella(self):
        """Il selettore della giornata: le giornate del calendario, e una tabella
        diversa per ciascuna."""
        import app as app_mod
        self._carica_giornata(self.at, "Serie A", extra=EXTRA_GIORNATA_9, giornata=8)
        df8 = self._tabella_giornata(self.at)
        selettori = [s for s in self.at.selectbox
                     if (s.key or "") == app_mod.CHIAVE_GIORNATA_PARTITE]
        self.assertEqual(1, len(selettori), "un selettore della giornata nella scheda")
        self.assertEqual([8, 9], [int(x) for x in selettori[0].options],
                         "le giornate sono quelle del calendario")
        self._carica_giornata(self.at, "Serie A", extra=EXTRA_GIORNATA_9, giornata=9)
        df9 = self._tabella_giornata(self.at)
        self.assertEqual(len(EXTRA_GIORNATA_9), len(df9),
                         "la giornata 9 ha solo le sue partite")
        self.assertNotEqual([str(x) for x in df8["Partita"].tolist()],
                            [str(x) for x in df9["Partita"].tolist()],
                            "cambiare giornata cambia la tabella")
        self.assertEqual({_titolo_atteso(m["homeTeam"]["name"], m["awayTeam"]["name"])
                          for m in EXTRA_GIORNATA_9},
                         {str(p) for p in df9["Partita"].tolist()})
        fuori, _ = self._testo_giornata(self.at)
        self.assertIn("SERIE A - GIORNATA 9", "\n".join(fuori))

    # -- 3. il clic sulla riga della giornata -------------------------------
    def test_03_la_riga_apre_la_scheda_della_partita_giusta(self):
        """Selezionare la riga N apre la scheda della partita della riga N."""
        self._carica_giornata(self.at, RENDER_VERTICE[0])
        df = self._tabella_giornata(self.at)
        self.assertGreaterEqual(len(df), 4, "la giornata ha abbastanza partite")
        i = self._indice_riga(self.at, *RENDER_VERTICE[1:])
        self.assertEqual(_titolo_atteso(*RENDER_VERTICE[1:]), str(df.iloc[i]["Partita"]))
        # Tre righe diverse (la prima, quella cercata e l'ultima): per ciascuna,
        # il riquadro che si apre e' quello della partita di QUELLA riga. Della
        # partita di vertice si controlla anche il contesto (lega, quote,
        # classifica): e' la stessa scheda che apre la scheda Multiple.
        for indice in sorted({0, i, len(df) - 1}):
            with self.subTest(riga=int(indice)):
                self._seleziona_riga(self.at, int(indice))
                atteso = str(df.iloc[indice]["Partita"])
                testo = self._testo_riquadro(self.at, atteso)
                self.assertIn(f"### {atteso}", testo,
                              "il riquadro e' quello della partita della riga")
                if int(indice) != i:
                    continue
                # La lega e la data stanno nella riga sotto il titolo (caption).
                didascalie = "\n".join(str(getattr(el, "value", "") or "")
                                       for el in self.at.caption)
                self.assertIn(RENDER_VERTICE[0], didascalie)
                self.assertIn("Quote %", testo)
                self.assertIn("Al comando della classifica", testo)  # Inter e' prima
                self._scrivi_render("vertice", testo, RENDER_VERTICE)

    # -- 4. [facoltativo] il secondo render, dalla stessa strada ------------
    def test_04_render_della_partita_di_bassa_classifica(self):
        if not self.render_out:
            self.skipTest("SCHEDA_RENDER_OUT non impostata: nessun file da scrivere")
        self._carica_giornata(self.at, RENDER_BASSA[0])
        self._seleziona_riga(self.at, self._indice_riga(self.at, *RENDER_BASSA[1:]))
        testo = self._testo_riquadro(self.at, _titolo_atteso(*RENDER_BASSA[1:]))
        self.assertIn(f"### {_titolo_atteso(*RENDER_BASSA[1:])}", testo)
        self.assertIn("Classifica e obiettivi", testo)
        self._scrivi_render("bassa", testo, RENDER_BASSA)

    def _scrivi_render(self, etichetta: str, testo: str, partita):
        if not self.render_out:
            return
        blocco = [f"## {etichetta}: {_titolo_atteso(*partita[1:])} ({partita[0]})", "",
                  "```", testo.rstrip(), "```", ""]
        with open(self.render_out, "a", encoding="utf-8") as fh:
            fh.write("\n".join(blocco) + "\n")


class TestSelettoreGiornata(unittest.TestCase):
    """Le due funzioni del selettore della giornata, senza AppTest.

    Sono le funzioni estratte dalla barra laterale: qui si legge il criterio
    (la prossima giornata e' la prima con almeno una partita da giocare,
    l'ultima quando sono tutte giocate) anche nei casi che il calendario della
    fixture non produce.
    """

    ADESSO = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)

    @staticmethod
    def _calendario():
        return [
            {"matchday": 7, "utcDate": "2026-10-03T13:00:00Z"},   # tutta giocata
            {"matchday": 7, "utcDate": "2026-10-04T13:00:00Z"},
            {"matchday": 8, "utcDate": "2026-10-17T13:00:00Z"},   # da giocare
            {"matchday": 9, "utcDate": "2026-10-24T13:00:00Z"},   # da giocare
            {"matchday": "non leggibile"},                        # nessuna giornata
            {"utcDate": "2026-10-25T13:00:00Z"},                  # nessuna giornata
        ]

    def test_le_giornate_sono_quelle_del_calendario(self):
        import app as app_mod
        self.assertEqual([7, 8, 9], app_mod.giornate_del_calendario(self._calendario()),
                         "in ordine, senza doppioni e senza giornate inventate")
        self.assertEqual([], app_mod.giornate_del_calendario([]))
        self.assertEqual([], app_mod.giornate_del_calendario(None))

    def test_la_prossima_giornata_e_la_prima_da_giocare(self):
        import app as app_mod
        giornate = app_mod.giornate_del_calendario(self._calendario())
        indice = app_mod.indice_prossima_giornata(giornate, self._calendario(), self.ADESSO)
        self.assertEqual(1, indice, "la 7 e' tutta giocata: la prossima e' la 8")
        self.assertEqual(8, giornate[indice])

    def test_tutte_giocate_resta_l_ultima_giornata(self):
        import app as app_mod
        dopo = datetime(2026, 11, 1, tzinfo=timezone.utc)
        giornate = app_mod.giornate_del_calendario(self._calendario())
        indice = app_mod.indice_prossima_giornata(giornate, self._calendario(), dopo)
        self.assertEqual(len(giornate) - 1, indice)
        self.assertEqual(9, giornate[indice], "si resta sull'ultima, coi suoi risultati")

    def test_senza_date_leggibili_nessuna_giornata_si_inventa(self):
        import app as app_mod
        righe = [{"matchday": 5, "utcDate": "non una data"}]
        giornate = app_mod.giornate_del_calendario(righe)
        self.assertEqual([5], giornate)
        self.assertEqual(0, app_mod.indice_prossima_giornata(giornate, righe, self.ADESSO))


if __name__ == "__main__":
    unittest.main(verbosity=2)
