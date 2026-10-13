"""AppTest della «scheda partita» (palla di vetro in parole) sul VERO ``app.py``.

Stessa fixture dei test di navigazione e di presentazione del Top Mix: snapshot
reale pinnato di ``live_odds.json``, database in una cartella temporanea,
orologio congelato a venerdi' 2026-10-16 18:00 ora italiana, rete finta,
registro in memoria. Nessun file reale viene toccato e nessuna chiamata di rete
parte da qui.

Cosa verifica, in parole povere:

* dalla scheda «🎯 Giocate», il pulsante «Scheda» di «Le più probabili» apre il
  RIQUADRO della partita giusta (i due nomi del pulsante sono quelli del titolo)
  con i blocchi in parole: probabilità dalle quote, classifica e obiettivi,
  forma, gol, precedenti;
* dalla scheda «🏟️ Partite» la giornata e' elencata in parole (data e ora
  italiane, 1/X/2 quando le quote ci sono, «Quote non ancora disponibili»
  quando non ci sono) e il pulsante «Scheda» della riga apre la stessa scheda
  della partita giusta;
* l'analisi odierna (Analisi Rapida e card del modello) sta DENTRO il riquadro
  chiuso «🔎 Dettagli»: fuori non compaiono ne' quelle voci ne' le parole
  vietate del punto 6 della PR #64 (elenco unico in
  ``test_apptest_topmix_presentazione``);
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
    _testi_della_tab,
)

import scheda_partita as sp  # noqa: E402
from display_names import display_name  # noqa: E402
from team_names import resolve_team_name  # noqa: E402

#: Le due partite del prossimo turno di cui si stampa il testo reso: una di
#: vertice (Serie A) e una di bassa classifica (Ligue 1).
RENDER_VERTICE = ("Serie A", "Bologna", "Inter")
RENDER_BASSA = ("Ligue 1", "Le Havre", "Auxerre")


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
    def _carica_giornata(cls, at, lega: str, extra=None):
        """Mette in ``session_state`` la giornata e sceglie il campionato."""
        at.session_state["live_data"] = cls._live_data(lega, extra)
        at.session_state["live_camp"] = lega
        for sb in at.selectbox:
            if "CAMPIONATO" in str(getattr(sb, "label", "")):
                sb.set_value(lega)
        at.run(timeout=900)
        cls.eccezioni(at, f"giornata di {lega}")

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
    def _pulsante(at, chiave):
        for b in at.button:
            if b.key == chiave:
                return b
        raise AssertionError(f"pulsante {chiave} non trovato")

    @classmethod
    def _indice_riga(cls, at, chiave_prefisso: str, casa: str, trasferta: str) -> int:
        """L'indice del pulsante «Scheda» della partita casa-trasferta."""
        atteso = _titolo_atteso(casa, trasferta)
        for b in at.button:
            if (b.key or "").startswith(chiave_prefisso) and (b.help or "") == atteso:
                return int(b.key.rsplit("_", 1)[1])
        disponibili = [(b.key, b.help) for b in at.button
                       if (b.key or "").startswith(chiave_prefisso)]
        raise AssertionError(f"nessuna riga {atteso!r} fra {disponibili}")


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

    # -- 1. dal pulsante «Scheda» delle Giocate -----------------------------
    def test_01_il_pulsante_scheda_apre_la_partita_giusta(self):
        pulsanti = [b for b in self.at.button
                    if (b.key or "").startswith("scheda_piu_probabili_")]
        self.assertTrue(pulsanti, "«Le più probabili» deve avere i pulsanti «Scheda»")
        self.assertTrue([b for b in self.at.button
                         if (b.key or "").startswith("scheda_raddoppio_")],
                        "«Per raddoppiare» deve avere i pulsanti «Scheda»")
        scelto = pulsanti[0]
        chiave, aiuto = scelto.key, scelto.help
        # Il suggerimento del pulsante porta i nomi come arrivano dalle quote;
        # il titolo della scheda porta i nomi di vista (es. «Borussia Dortmund»
        # -> «Dortmund»): la stessa risoluzione dei due lati.
        casa, trasferta = [x.strip() for x in aiuto.split(" - ", 1)]
        atteso = _titolo_atteso(casa, trasferta)
        self._pulsante(self.at, chiave).click()
        self.at.run(timeout=900)
        self.eccezioni(self.at, "apertura della scheda dalle Giocate")
        testo = self._testo_riquadro(self.at, atteso)
        for titolo in ("Probabilità (dalle quote dei bookmaker)",
                       "Classifica e obiettivi",
                       "Forma: ultime 5 partite di campionato",
                       "Gol", "Precedenti stagionali"):
            with self.subTest(blocco=titolo):
                self.assertIn(titolo, testo)
        self.assertIn(f"### {atteso}", testo,
                      "il riquadro deve essere quello della partita del pulsante")
        self.assertIn(_nomi_mostrati(trasferta), testo,
                      "nel riquadro ci sono i nomi delle due squadre del pulsante")
        self.assertIn("Quote %", testo)
        self.assertIn("Modello %", testo)
        # In vista, in chiaro: le percentuali delle quote e i punti delle due
        # squadre. Nessun punteggio o indice inventato dalla scheda.
        self.assertRegex(testo, r"Quote % \d+,\d%")
        self.assertRegex(testo, r"\d+° posto")
        for parola in PAROLE_VIETATE:
            with self.subTest(parola=parola):
                self.assertIsNone(re.search(parola, testo, re.IGNORECASE),
                                  f"parola vietata nella scheda: {parola!r}")

    # -- 2. la scheda Partite: giornata in parole ---------------------------
    def test_02_la_giornata_e_elencata_in_parole(self):
        extra = [{"utcDate": "2027-05-01T15:00:00Z",
                  "homeTeam": {"name": "Bologna"}, "awayTeam": {"name": "Monza"},
                  "matchday": 8, "score": {"fullTime": {"home": None, "away": None}},
                  "status": "SCHEDULED"}]
        self._carica_giornata(self.at, "Serie A", extra=extra)
        fuori, dentro = _testi_della_tab(self.at, 1)
        testo = "\n".join(fuori)
        righe = self.at.session_state["live_data"]
        for m in righe:
            casa, trasferta = m["homeTeam"]["name"], m["awayTeam"]["name"]
            with self.subTest(partita=f"{casa} - {trasferta}"):
                self.assertIn(_titolo_atteso(casa, trasferta), testo)
        # 1, X, 2 in parole dove le quote ci sono; la riga senza quote lo dice.
        prima = righe[0]
        self.assertIn("Vince " + _nomi_mostrati(prima["homeTeam"]["name"]), testo)
        self.assertIn("Pareggio", testo)
        self.assertIn("Vince " + _nomi_mostrati(prima["awayTeam"]["name"]), testo)
        self.assertIn(sp.FRASE_QUOTE_ASSENTI, testo)
        # Data e ora italiane: "sabato 17/10, ore 18:00" e simili.
        self.assertRegex(testo, r"(luned|marted|mercoled|gioved|venerd|sabato|domenica) \d{2}/\d{2}, ore \d{2}:\d{2}")
        pulsanti = [b for b in self.at.button
                    if (b.key or "").startswith("partite_scheda_")]
        self.assertEqual(len(pulsanti), len(righe),
                         "una riga della giornata = un pulsante «Scheda»")
        # L'analisi odierna sta DENTRO «Dettagli» (riquadro chiuso), non in vista.
        self.assertIn("Analisi Rapida", "\n".join(dentro))
        self.assertNotIn("Analisi Rapida", testo)
        etichette = [str(e.label or "") for e in self.at.expander]
        self.assertTrue(any(e.strip().endswith("Dettagli") for e in etichette), etichette)
        for parola in PAROLE_VIETATE:
            with self.subTest(parola=parola):
                self.assertIsNone(re.search(parola, testo, re.IGNORECASE),
                                  f"parola vietata fuori dai Dettagli: {parola!r}")

    # -- 3. il pulsante «Scheda» della giornata -----------------------------
    def test_03_la_giornata_apre_la_scheda_della_partita_giusta(self):
        i = self._indice_riga(self.at, "partite_scheda_", *RENDER_VERTICE[1:])
        self._pulsante(self.at, f"partite_scheda_{i}").click()
        self.at.run(timeout=900)
        self.eccezioni(self.at, "apertura della scheda dalla scheda Partite")
        testo = self._testo_riquadro(self.at, _titolo_atteso(*RENDER_VERTICE[1:]))
        self.assertIn(f"### {_titolo_atteso(*RENDER_VERTICE[1:])}", testo)
        # La lega e la data stanno nella riga sotto il titolo (caption).
        didascalie = "\n".join(str(getattr(el, "value", "") or "") for el in self.at.caption)
        self.assertIn(RENDER_VERTICE[0], didascalie)
        self.assertIn("Quote %", testo)
        self.assertIn("Al comando della classifica", testo)  # Inter e' prima
        self._scrivi_render("vertice", testo, RENDER_VERTICE)

    # -- 4. [facoltativo] il secondo render, dalla stessa strada ------------
    def test_04_render_della_partita_di_bassa_classifica(self):
        if not self.render_out:
            self.skipTest("SCHEDA_RENDER_OUT non impostata: nessun file da scrivere")
        self._carica_giornata(self.at, RENDER_BASSA[0])
        i = self._indice_riga(self.at, "partite_scheda_", *RENDER_BASSA[1:])
        self._pulsante(self.at, f"partite_scheda_{i}").click()
        self.at.run(timeout=900)
        self.eccezioni(self.at, "apertura della scheda della partita di bassa")
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
