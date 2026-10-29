"""AppTest della scheda «🏟️ Partite»: un calendario per lega, niente «None».

COSA VERIFICA (commessa «calendario della scheda Partite» + «mai None» +
pulsante «🔄 Controlla i risultati» in cima al Registro).

* (a) con la barra laterale su Serie A, ognuna delle altre quattro leghe mostra
  SOLO le partite del proprio calendario (football-data finto, un calendario
  diverso per lega);
* (b) per ogni lega le partite non ancora iniziate PRESENTI nel file quote hanno
  tutte e tre le probabilita' 1/X/2 in tabella; quella che la fonte non copre
  resta con le celle vuote (stringa vuota, mai None/NaN);
* (c) una risposta 429 simulata: messaggio leggibile e NESSUNA tabella, mai le
  partite di un'altra lega;
* (d) la scheda aperta dal selettore «Apri la scheda» (la tabella della
  giornata e' HTML: la riga non si clicca piu') su una partita di Bundesliga,
  con la barra laterale su Serie A, mostra la classifica e gli obiettivi della
  Bundesliga;
* il pulsante «🔄 Controlla i risultati» e' il PRIMO elemento interattivo della
  scheda Registro e, dopo il clic, la tabella mostra l'esito nuovo nello stesso
  run;
* una passata su TUTTE le tabelle dell'app (tutte le schede, Strumenti compresi)
  non trova nessuna cella None/NaN/NaT ne' le scritte «None»/«nan»/«NaT», con
  righe giocate, righe senza modello e righe solo O/U (anche senza congiunta).

Nessuna rete: ``requests.get`` e' finto e risponde con i calendari/risultati del
fixture. Nessun file del repository viene toccato (database in una cartella
temporanea, registro in memoria).
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.dirname(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_apptest_scheda_pronostici import (  # noqa: E402
    ETICHETTA_CALCOLA,
    FixtureQuoteFinte,
    _BaseQuoteFinte,
    _iso,
    _riga_conclusa,
)
from test_apptest_topmix_presentazione import (  # noqa: E402
    SCHEDA_PARTITE,
    SCHEDA_REGISTRO,
    _radice_tab,
    _testi_della_tab,
)

#: Le cinque leghe, nell'ordine della barra laterale, con il codice
#: football-data usato dal fixture.
LEGHE = ["Serie A", "Premier League", "La Liga", "Bundesliga", "Ligue 1"]
CODICI = {"Serie A": "SA", "Premier League": "PL", "La Liga": "PD",
          "Bundesliga": "BL1", "Ligue 1": "FL1"}

#: Due partite per lega: la prima con le quote nel file, la seconda senza (la
#: fonte non la copre). I nomi sono quelli dei CSV della lega.
PARTITE = {
    "Serie A": [("Genoa", "Fiorentina", (0.55, 0.25, 0.20)),
                ("Torino", "Como", (0.50, 0.28, 0.22)),
                ("Atalanta", "Lazio", (0.52, 0.26, 0.22)),
                ("Bologna", "Cagliari", None),
                ("Napoli", "Parma", None)],
    "Premier League": [("Arsenal", "Chelsea", (0.50, 0.27, 0.23)),
                       ("Liverpool", "Everton", (0.48, 0.28, 0.24)),
                       ("Man City", "Man United", (0.46, 0.27, 0.27)),
                       ("Burnley", "Leeds", None),
                       ("Brighton", "Fulham", None)],
    "La Liga": [("Barcelona", "Betis", (0.62, 0.22, 0.16)),
                ("Getafe", "Osasuna", (0.45, 0.30, 0.25)),
                ("Ath Madrid", "Sevilla", (0.55, 0.26, 0.19)),
                ("Celta", "Espanol", None),
                ("Mallorca", "Alaves", None)],
    "Bundesliga": [("Bayern Munich", "Dortmund", (0.58, 0.24, 0.18)),
                   ("Leverkusen", "RB Leipzig", (0.52, 0.26, 0.22)),
                   ("Freiburg", "Mainz", (0.42, 0.30, 0.28)),
                   ("Augsburg", "Heidenheim", None),
                   ("Hoffenheim", "St Pauli", None)],
    "Ligue 1": [("Lyon", "Marseille", (0.48, 0.28, 0.24)),
                ("Le Havre", "Auxerre", (0.40, 0.31, 0.29)),
                ("Lille", "Nice", (0.47, 0.28, 0.25)),
                ("Nantes", "Metz", None),
                ("Lens", "Brest", None)],
}


class FixtureCinqueLeghe(FixtureQuoteFinte):
    """Lo stesso pianeta del fixture, ma con cinque calendari e cinque leghe."""

    @classmethod
    def _evento(cls, mid, casa, trasferta, probs, adesso):
        return {"id": mid, "commence_time": _iso(adesso + timedelta(hours=6 + mid % 7), True),
                "home_team": casa, "away_team": trasferta,
                "last_update": _iso(adesso, True),
                "libri": [cls._libro(*probs, adesso)]}

    @classmethod
    def payload_quote(cls, adesso):
        leghe = {}
        mid = 1200
        for lega in LEGHE:
            eventi = []
            for casa, trasferta, probs in PARTITE[lega]:
                if probs is None:
                    continue
                mid += 1
                eventi.append(cls._evento(mid, casa, trasferta, probs, adesso))
            leghe[lega] = {"eventi": eventi}
        n = sum(len(v["eventi"]) for v in leghe.values())
        return {
            "schema": "soccermath_live_odds_v1", "generato_il": _iso(adesso, True),
            "fonte": "the-odds-api", "piano": "starter", "regioni": "eu",
            "mercato": "h2h", "formato_quote": "decimal", "modalita": "fixture",
            "crediti": {"quota_mensile": 500, "usati_dall_ultimo_reset": 5,
                        "residui": 495},
            "n_leghe_ok": len(LEGHE), "n_leghe_con_quote": len(LEGHE),
            "n_leghe_richieste": len(LEGHE), "n_eventi": n,
            "n_eventi_con_libri": n, "n_eventi_con_pinnacle": n,
            "n_libri_totale": n, "leghe_con_eventi_senza_libri": [],
            "errori": [], "leghe_mancanti_rispetto_a_prima": [], "leghe": leghe,
        }

    @classmethod
    def calendario_per_lega(cls, lega, adesso):
        matches = []
        for k, (casa, trasferta, _probs) in enumerate(PARTITE[lega]):
            matches.append({
                "id": 8100 + LEGHE.index(lega) * 10 + k,
                "matchday": 7, "utcDate": _iso(adesso + timedelta(hours=8 + k), True),
                "status": "TIMED",
                "homeTeam": {"name": casa, "shortName": casa},
                "awayTeam": {"name": trasferta, "shortName": trasferta},
                "score": {"fullTime": {"home": None, "away": None}},
            })
        return {"matches": matches}


def _titolo(casa, trasferta):
    """«Casa - Trasferta» come lo scrive la tabella (nomi di vista)."""
    from display_names import display_name
    from team_names import resolve_team_name
    def uno(n):
        r = resolve_team_name(n)
        return display_name(r.canonical) if r.mapped else str(n)
    return f"{uno(casa)} - {uno(trasferta)}"


def _df_di(el):
    df = getattr(el, "value", None)
    if hasattr(df, "data"):
        df = df.data
    return df


def _primo_interattivo(at, scheda):
    """Il primo elemento interattivo della scheda, nell'ordine di disegno."""
    interattivi = {"button", "selectbox", "checkbox", "toggle", "radio",
                   "multiselect", "number_input", "text_input", "slider"}
    ordine = []

    def cammina(el):
        if type(el).__name__.lower() in interattivi:
            ordine.append(el)
        figli = getattr(el, "children", None)
        if figli:
            for c in (figli.values() if isinstance(figli, dict) else figli):
                cammina(c)

    cammina(_radice_tab(at, scheda))
    return ordine[0] if ordine else None


class TestCalendarioDellaScheda(_BaseQuoteFinte):
    """(a)(b)(c)(d): il calendario della scheda e' quello della lega scelta."""

    FIXTURE = FixtureCinqueLeghe
    #: Dizionari PROPRI: mutarli non deve cambiare le altre classi di test.
    ERRORI_CALENDARIO = {}
    RISULTATI_FINTI = {}

    @classmethod
    def risposte_calendario(cls):
        return {CODICI[lega]: FixtureCinqueLeghe.calendario_per_lega(lega, cls.ADESSO)
                for lega in LEGHE}

    @classmethod
    def _scegli_lega(cls, lega):
        import app as app_mod
        import streamlit as st
        for sb in cls.at.selectbox:
            if (sb.key or "") == app_mod.CHIAVE_CAMPIONATO_PARTITE:
                sb.set_value(lega)
        st.cache_data.clear()
        cls.at.run(timeout=900)
        cls.eccezioni(cls.at, f"scheda Partite su {lega}")

    @classmethod
    def _tabella_partite(cls):
        """La tabella della giornata, letta dall'HTML (non e' piu' un dataframe).

        La scheda Partite disegna la giornata con
        ``scheda_grafica.html_tabella_partite``: ``tabella_giornata`` rilegge
        quel blocco come DataFrame con le sette colonne, e i controlli sulle
        celle restano gli stessi di prima (celle vuote = stringa vuota).
        """
        from test_html_tabella_partite import tabella_giornata
        df = tabella_giornata(cls.at, SCHEDA_PARTITE)
        if df.empty:
            raise AssertionError("una sola tabella Partite, trovata nessuna")
        return df

    def test_01_ogni_lega_ha_il_suo_calendario(self):
        import pandas as pd
        # Evidenza per il referto: se PARTITE_OUT e' impostata, il test scrive
        # le prime cinque righe della tabella di ogni lega, come le ha lette da
        # AppTest (file fuori dal repository: nessun file tracciato).
        evidenza = []
        # La barra laterale resta su Serie A (e' il primo campionato della
        # lista): la scheda non deve mai leggerla.
        self.assertEqual("Serie A", self.at.sidebar.selectbox[0].value)
        for lega in LEGHE:
            with self.subTest(lega=lega):
                self._scegli_lega(lega)
                df = self._tabella_partite()
                self.assertEqual("Serie A", self.at.sidebar.selectbox[0].value,
                                 "la barra laterale resta su Serie A")
                if os.environ.get("PARTITE_OUT"):
                    evidenza.append(f"== {lega} (barra laterale: "
                                    f"{self.at.sidebar.selectbox[0].value}) ==")
                    evidenza.append(df.head(5).to_string(index=False))
                attese = {_titolo(c, t) for c, t, _p in PARTITE[lega]}
                self.assertEqual(attese, {str(x) for x in df["Partita"].tolist()},
                                 f"{lega}: la tabella deve contenere solo le sue partite")
                altre = {_titolo(c, t)
                         for altra in LEGHE if altra != lega
                         for c, t, _p in PARTITE[altra]}
                self.assertFalse(altre & {str(x) for x in df["Partita"].tolist()},
                                 f"{lega}: nessuna partita di un'altra lega")
                # (b) le partite con le quote hanno TUTTE e tre le probabilita';
                # quella senza evento resta vuota.
                for casa, trasferta, probs in PARTITE[lega]:
                    riga = df[df["Partita"] == _titolo(casa, trasferta)].iloc[0]
                    if probs is None:
                        self.assertEqual(("", "", ""),
                                         (riga["1"], riga["X"], riga["2"]),
                                         f"{lega}/{casa}: senza quote celle vuote")
                        continue
                    for esito in ("1", "X", "2"):
                        self.assertRegex(str(riga[esito]), r"^\d{1,2},\d%$",
                                         f"{lega}/{casa}: {esito} deve avere la percentuale")
                    self.assertFalse(pd.isna(riga["1"]))
        # (c) 429 simulato: messaggio, nessuna tabella, nessuna partita altrui.
        self.ERRORI_CALENDARIO["PL"] = 429
        try:
            self._scegli_lega("Premier League")
        finally:
            del self.ERRORI_CALENDARIO["PL"]
        errori = " \n".join(str(e.value) for e in self.at.error)
        self.assertIn("429", errori)
        fuori, dentro = _testi_della_tab(self.at, SCHEDA_PARTITE)
        self.assertNotIn('class="sg-tabella"', " \n".join(fuori + dentro),
                         "con il 429 la scheda non disegna la tabella")
        testo = " \n".join(fuori + dentro)
        self.assertNotIn(_titolo("Genoa", "Fiorentina"), testo)
        self.assertNotIn(_titolo("Arsenal", "Chelsea"), testo)
        # (d) Bundesliga aperta con la barra su Serie A: classifica tedesca.
        # La scheda si apre dal selettore «Apri la scheda» + «Apri» (la riga
        # della tabella non si clicca piu': la tabella e' HTML).
        self._scegli_lega("Bundesliga")
        df = self._tabella_partite()
        attesa = _titolo("Bayern Munich", "Dortmund")
        self.assertIn(attesa, [str(p) for p in df["Partita"].tolist()])
        from test_html_tabella_partite import apri_scheda
        apri_scheda(self.at, attesa)
        self.eccezioni(self.at, "scheda Bundesliga con la barra su Serie A")
        titolo = "### " + _titolo("Bayern Munich", "Dortmund")
        valori = [str(m.value) for m in self.at.markdown]
        self.assertIn(titolo, valori)
        i = valori.index(titolo)
        testo = "\n".join(valori[i:i + 30])
        # La scheda è quella grafica (``scheda_grafica``): cinque sezioni
        # HTML, coi titoli nuovi e la barra con la sua percentuale.
        self.assertEqual(5, testo.count('class="sg sg-sezione"'),
                         "la scheda aperta deve avere le cinque sezioni HTML")
        for titolo_sezione in ("Probabilità", "Classifica",
                               "Forma: ultime 5 partite di campionato", "Gol",
                               "Precedenti in stagione"):
            self.assertIn(titolo_sezione, testo)
        self.assertRegex(testo, r'sg-valore">\d+,\d%</span>',
                         "almeno una percentuale delle barre 1/X/2")
        self.assertIn("Bayern", testo)
        self.assertRegex(testo, r"\d+°")
        # Se la scheda leggesse la classifica della barra laterale (Serie A),
        # per il Bayern non ci sarebbe nessuna riga di classifica.
        self.assertNotIn("Bayern: dati di classifica insufficienti", testo)
        self.assertNotIn("Dortmund: dati di classifica insufficienti", testo)
        if os.environ.get("PARTITE_OUT"):
            with open(os.environ["PARTITE_OUT"], "w", encoding="utf-8") as f:
                f.write("\n\n".join(evidenza) + "\n")


class TestTabelleERegistro(_BaseQuoteFinte):
    """Tutte le tabelle senza None; il pulsante dei risultati in cima al Registro."""

    FIXTURE = FixtureQuoteFinte
    ERRORI_CALENDARIO = {}
    RISULTATI_FINTI = {}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Una riga ANCORA da giocare, con un risultato che il football-data
        # finto sa: e' quella che il pulsante deve chiudere nello stesso run.
        cls.pending = _riga_conclusa(cls.ADESSO)
        cls.pending.update({
            "match_id": 7002, "home": "Casa Pending", "away": "Ospite Pending",
            "giornata": 6, "risultato_reale": "", "esito": "⏳",
            "data": (cls.ADESSO - timedelta(hours=1)).strftime("%d/%m/%Y %H:%M"),
            "kickoff_utc": _iso(cls.ADESSO + timedelta(days=1), True),
        })
        cls.registro.vivo.append(dict(cls.pending))
        cls.RISULTATI_FINTI[("SA", 6)] = [{
            "id": 7002, "score": {"fullTime": {"home": 2, "away": 1}},
            "status": "FINISHED",
        }]
        cls.at.run(timeout=900)
        cls.eccezioni(cls.at, "Registro con una riga in attesa")

    NON_NUMERO = re.compile(r"\b(none|nan|nat)\b", re.IGNORECASE)

    def _tabelle(self):
        import pandas as pd
        elementi = list(self.at.dataframe or []) + list(getattr(self.at, "table", None) or [])
        fuori = []
        for el in elementi:
            df = _df_di(el)
            if isinstance(df, pd.DataFrame):
                fuori.append((str(getattr(el, "key", "") or "<senza chiave>"), df))
        return fuori

    def _controlla_tabelle(self, fase):
        import pandas as pd
        tabelle = self._tabelle()
        self.assertGreater(len(tabelle), 3, f"{fase}: le tabelle dell'app ci sono")
        for chiave, df in tabelle:
            if df.empty:
                continue
            for colonna in df.columns:
                numerica = pd.api.types.is_numeric_dtype(df[colonna])
                for cella in df[colonna].tolist():
                    with self.subTest(fase=fase, tabella=chiave, colonna=str(colonna)):
                        self.assertFalse(pd.isna(cella),
                                         f"cella mancante in {chiave}/{colonna}: {cella!r}")
                        testo = str(cella)
                        self.assertIsNone(self.NON_NUMERO.search(testo),
                                          f"{chiave}/{colonna}: {testo!r}")
                        if not numerica:
                            self.assertIsInstance(cella, str)

    def test_01_nessun_none_in_nessuna_scheda(self):
        import app as app_mod
        # Tutte le schede accese, compreso «Strumenti avanzati».
        for t in self.at.toggle:
            if (t.key or "") == "strumenti_avanzati":
                t.set_value(True)
        self.at.run(timeout=900)
        self.eccezioni(self.at, "tutte le schede accese")
        # La tabella dei Pronostici esiste solo dopo il clic; le righe solo O/U
        # arrivano dalla stessa normalizzazione usata dall'app.
        self._premi_click(self.at, ETICHETTA_CALCOLA)
        self._controlla_tabelle("dopo il calcolo dei pronostici")
        # Righe solo O/U, anche senza la probabilita' congiunta: nessuna cella
        # puo' diventare NaN/None, tranne la «Quote %» di queste righe. Li' il
        # valore mancante e' voluto: la colonna resta numerica (ProgressColumn)
        # e la cella e' vuota a schermo — mai la scritta «None»/«nan».
        import pandas as pd
        from audit.totals_snapshot_fixture import payload_snapshot
        # ADESSO del fixture è dinamico (now), mentre lo snapshot è del
        # 2026-10-16: con now=2026-10-29 gli eventi sono già scaduti e non
        # entrerebbero in tabella. Per rendere il check indipendente dalla
        # data reale si usa un orologio fisso prima del primo evento dello
        # snapshot (18:45 del 16/10), come già fanno gli altri test con
        # snapshot pinnati (ADESSO fisso 16/10 in test_scheda_partita.py).
        snapshot = payload_snapshot()
        adesso_fisso = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
        righe_ou, _ = app_mod.righe_pronostici_dalle_quote(snapshot, adesso_fisso)
        normalizzate = [app_mod.riga_pronostico_da_mercato(r, adesso_fisso)
                        for r in righe_ou]
        for r in normalizzate:
            r.pop("totals", None)          # O/U senza congiunta
        df_ou, _ = app_mod.tabella_pronostici_visibile([
            dict(r, solo_ou=True) for r in normalizzate])
        self.assertTrue(any(df_ou["Pronostico"] == "—"))
        self.assertTrue(pd.api.types.is_numeric_dtype(df_ou["Quote %"]),
                        "«Quote %» resta numerica anche con le righe solo gol")
        self.assertEqual("—", df_ou["Pronostico"].iloc[-1])
        self.assertTrue(pd.isna(df_ou["Quote %"].iloc[-1]),
                        "riga solo gol: «Quote %» mancante (NaN), non stringa vuota")
        for colonna in df_ou.columns:
            for cella in df_ou[colonna].tolist():
                if pd.isna(cella):
                    self.assertEqual("Quote %", colonna,
                                     f"O/U senza congiunta: valore mancante in {colonna!r}")
                    continue
                self.assertFalse(pd.isna(cella),
                                 f"O/U senza congiunta: {colonna}={cella!r}")

    def test_02_pulsante_controlla_i_risultati_in_cima(self):
        import pandas as pd
        primo = _primo_interattivo(self.at, SCHEDA_REGISTRO)
        self.assertIsNotNone(primo)
        self.assertEqual("btn_ricontrolla_risultati", getattr(primo, "key", None),
                         "il primo comando del Registro e' «Controlla i risultati»")
        self.assertIn("Controlla i risultati", getattr(primo, "label", "") or "")
        # Clic: la riga in attesa riceve il risultato del football-data finto e
        # la tabella lo mostra GIA' in questo run (nessun secondo rerun).
        for b in self.at.button:
            if (b.key or "") == "btn_ricontrolla_risultati":
                b.click()
        self.at.run(timeout=900)
        self.eccezioni(self.at, "clic su Controlla i risultati")
        messaggi = " \n".join([str(s.value) for s in self.at.success]
                              + [str(i.value) for i in self.at.info])
        self.assertRegex(messaggi, r"Aggiornate 1 partite")
        self.assertEqual("✅", self._esito_pending())
        tabelle = self._tabelle()
        attesa = "Casa Pending vs Ospite Pending"
        trovate = [df for _k, df in tabelle
                   if "Esito" in df.columns and "Partita" in df.columns
                   and (df["Partita"] == attesa).any()]
        self.assertTrue(trovate, "la riga aggiornata compare nella tabella del Registro")
        riga = trovate[0][trovate[0]["Partita"] == attesa].iloc[0]
        self.assertEqual("✅", riga["Esito"])
        self.assertEqual("2-1", riga["Risultato"])

    def _esito_pending(self):
        for r in self.registro.vivo:
            if r.get("match_id") == 7002:
                return r.get("esito")
        return None


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
