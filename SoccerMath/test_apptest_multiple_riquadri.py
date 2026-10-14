"""AppTest della scheda «🎯 Multiple» riorganizzata (riquadri + una tabella).

Stessa fixture degli altri AppTest (``test_apptest_navigazione._BaseAppTest``):
snapshot reale pinnato di ``live_odds.json``, database in una cartella
temporanea, orologio congelato a venerdi' 2026-10-16 18:00 ora italiana, rete
finta, registro in memoria. Nessun file reale viene toccato e nessuna chiamata
di rete parte da qui.

Cosa verifica, in parole povere:

* in vista nella scheda non c'e' nessun pulsante «Scheda» e nessuna delle frasi
  tolte (le tre didascalie di testa, il riquadro «Per raddoppiare» con la sua
  legenda e i suoi pulsanti, i filtri e il «Mostra altre» di «Le più
  probabili», il testo «quote provvisorie» dentro la colonna Partita);
* i riquadri sono da 1 a 4, con il titolo Singola/Doppia/Tripla/Quadrupla (la ★
  su quello che riesce più spesso) e i NUMERI — quota totale e «Riesce» —
  uguali all'output di ``lista_giocate.cerca_proposta_multipla`` sullo stesso
  snapshot e lo stesso periodo; ogni partita ha la riga «Casa - Trasferta» e
  sotto «sigla · giorno abbreviato ora»;
* il pulsante «Prova con le quote bet365» apre «Prova la tua giocata» con
  numero di giocate e gambe precaricate (caselle bet365 vuote);
* «Le più probabili» e' UNA tabella con le sei colonne di Pronostici/Pareggi,
  una riga per partita, tutte le righe, ordinata per «Quote %» decrescente;
  selezionare la riga N apre la scheda della partita N;
* nel testo reso della scheda — Dettagli compresi — non compare mai "None",
  "nan" o "NaN"; fuori dai Dettagli non compaiono le parole vietate (PR #64).

[facoltativo] con la variabile d'ambiente ``MULTIPLE_RENDER_OUT`` impostata, il
test SCRIVE nel file indicato il testo reso dei riquadri e delle prime 5 righe
di «Le più probabili», preso da AppTest: e' l'evidenza che accompagna la PR, non
un testo scritto a mano.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(HERE, "app.py")
REPO_ROOT = os.path.dirname(HERE)
for _p in (HERE, REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_apptest_navigazione import _BaseAppTest  # noqa: E402
from test_apptest_topmix_presentazione import (  # noqa: E402
    PAROLE_VIETATE,
    SCHEDA_MULTIPLE,
    _elementi_della_tab,
    _raccogli_da_df,
    _radice_tab,
    _testi_della_tab,
    _testo_blocco,
)

#: Le frasi che la riorganizzazione ha tolto dalla vista della scheda.
FRASI_TOLTE = (
    "Le quote vengono aggiornate ogni giorno",
    "Quote aggiornate oggi alle",
    "Le quote delle partite lontane vengono aggiornate ogni giorno",
    "Per raddoppiare",
    "Su 100 € giocati tornano in media",
    "★ = la giocata che riesce più spesso",
    "Scheda partita:",
    "Usa nel calcolatore",
    "Ogni partita aggiunta abbassa le probabilità di riuscita",
    "Mostra altre",
    "Campionato",
    "quote provvisorie: possono cambiare",
)

NON_NUMERO = re.compile(r"\b(nan|none|nat)\b", re.IGNORECASE)


def _figli(el):
    ch = getattr(el, "children", None)
    if not ch:
        return []
    return list(ch.values() if isinstance(ch, dict) else ch)


def _nome_classe(el):
    return type(el).__name__.lower()


class TestMultipleRiquadri(_BaseAppTest):
    """Un solo AppTest, piu' disegni: apertura, pulsante, clic sulla riga."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from streamlit.testing.v1 import AppTest
        cls.at = AppTest.from_file(APP_PATH, default_timeout=300)
        cls.at.run(timeout=900)
        cls.eccezioni(cls.at, "apertura della pagina")
        cls.render_out = os.environ.get("MULTIPLE_RENDER_OUT")

    # -- attese dallo snapshot (stessi numeri dei riquadri) -----------------
    @classmethod
    def _attese(cls):
        import lista_giocate as lg
        res = lg.calcola_lista_giocate(cls.snap, adesso_utc=cls.ADESSO)
        in_periodo = lg.giocate_nel_periodo(res["giocate"], cls.ADESSO, "giornata")
        prop = lg.cerca_proposta_multipla(in_periodo)
        return in_periodo, prop

    # -- lettura dei riquadri resi ------------------------------------------
    @classmethod
    def _riquadri_resi(cls, at):
        """I contenitori col bordo che hanno il pulsante del riquadro: per
        ciascuno titolo, righe di testo, metriche (label -> valore) e la
        chiave del pulsante."""
        trovati = []

        def cammina(el, colonne_sorelle):
            figli = _figli(el)
            bottoni = [f for f in figli if _nome_classe(f) == "button"]
            chiave = next((str(getattr(b, "key", "") or "") for b in bottoni
                           if str(getattr(b, "key", "") or "").startswith("prova_quote_b365_")),
                          None)
            if chiave:
                testi = [t for _d, t in _testo_blocco(el, dentro_expander=False)]
                metriche = {}
                titoli = []     # il markdown grezzo: ``_testo_blocco`` toglie i simboli (★)

                def raccogli_metriche(x):
                    if _nome_classe(x) == "metric":
                        metriche[str(getattr(x, "label", ""))] = str(getattr(x, "value", ""))
                    if _nome_classe(x) == "markdown" and \
                            str(getattr(x, "value", "") or "").startswith("#####"):
                        titoli.append(str(x.value))
                    for f in _figli(x):
                        raccogli_metriche(f)
                raccogli_metriche(el)
                trovati.append({"chiave": chiave, "k": int(chiave.rsplit("_", 1)[1]),
                                "testi": testi, "metriche": metriche,
                                "titolo": titoli[0] if titoli else "",
                                # quante colonne ha la fila in cui sta il riquadro
                                # (0 = non sta dentro una colonna)
                                "colonne": colonne_sorelle})
                return
            for f in figli:
                if _nome_classe(f) == "column":
                    cammina(f, sum(1 for x in figli if _nome_classe(x) == "column"))
                else:
                    cammina(f, colonne_sorelle)

        cammina(_radice_tab(at, SCHEDA_MULTIPLE), 0)
        return trovati

    @classmethod
    def _df_probabili(cls, at):
        import app as app_mod
        for el in _elementi_della_tab(at, SCHEDA_MULTIPLE, "dataframe"):
            if str(getattr(el, "key", "") or "") == app_mod.CHIAVE_TABELLA_PIU_PROBABILI:
                val = getattr(el, "value", None)
                if val is not None and hasattr(val, "data"):
                    val = val.data
                return val
        # In mancanza della chiave sull'elemento, e' la PRIMA tabella in vista
        # (le altre stanno nei riquadri chiusi, che vengono dopo).
        tabelle = _elementi_della_tab(at, SCHEDA_MULTIPLE, "dataframe")
        if not tabelle:
            raise AssertionError("nessuna tabella nella scheda Multiple")
        val = getattr(tabelle[0], "value", None)
        return val.data if val is not None and hasattr(val, "data") else val

    @staticmethod
    def _esp_prova(at):
        for e in at.expander:
            if "Prova la tua giocata" in (e.label or ""):
                return e
        raise AssertionError("riquadro «Prova la tua giocata» non trovato")

    @staticmethod
    def _widget(at, classe, prefisso):
        acc = getattr(at, classe.lower().replace("numberinput", "number_input"), [])
        return [w for w in acc if str(getattr(w, "key", "") or "").startswith(prefisso)]

    # -- 1. niente pulsanti «Scheda», niente frasi tolte --------------------
    def test_01_in_vista_niente_scheda_e_niente_frasi_tolte(self):
        fuori, dentro = _testi_della_tab(self.at, SCHEDA_MULTIPLE)
        testo = " \n".join(fuori)
        self.assertTrue(testo, "la scheda e' bianca")
        self.assertIn("Multiple", testo)
        etichette = [str(b.label or "") for b in
                     _elementi_della_tab(self.at, SCHEDA_MULTIPLE, "button")]
        self.assertEqual([], [e for e in etichette if e.strip() == "Scheda"],
                         "nessun pulsante «Scheda» nella scheda Multiple")
        self.assertEqual([], [b for b in self.at.button
                              if (b.key or "").startswith(("scheda_piu_probabili_",
                                                           "scheda_raddoppio_",
                                                           "usa_calc_r_"))])
        for frase in FRASI_TOLTE:
            with self.subTest(frase=frase):
                self.assertNotIn(frase, testo)
        # Le parole vietate (PR #64) restano fuori dalla vista.
        basso = testo.lower()
        for parola in PAROLE_VIETATE:
            with self.subTest(parola=parola):
                self.assertIsNone(re.search(parola, basso, re.IGNORECASE),
                                  f"parola vietata in vista: {parola!r}")
        # Il contenuto tecnico non e' sparito: sta nei Dettagli.
        testo_dentro = " \n".join(dentro)
        for atteso in ("Per raddoppiare", "Su 100 € giocati tornano in media",
                       "lista_giocate_v1", "Quota equa"):
            with self.subTest(dentro=atteso):
                self.assertIn(atteso, testo_dentro)

    # -- 2. i riquadri: da 1 a 4, con i numeri della ricerca -----------------
    def test_02_i_riquadri_rendono_i_numeri_di_cerca_proposta_multipla(self):
        import app as app_mod
        import lista_giocate as lg
        _in_periodo, prop = self._attese()
        per_k = {k: v for k, v in prop["per_k"].items() if v}
        self.assertTrue(per_k, "a venerdi' lo snapshot ha almeno una proposta")
        righe = lg.righe_riquadro_raddoppio(prop["per_k"], self.ADESSO)
        migliore = next((r["k"] for r in righe if r.get("migliore")), None)

        resi = self._riquadri_resi(self.at)
        self.assertEqual(sorted(per_k), [r["k"] for r in resi],
                         "un riquadro per ogni numero di partite con proposta, in ordine")
        self.assertTrue(1 <= len(resi) <= 4)
        self.assertEqual([4] * len(resi), [r["colonne"] for r in resi],
                         "i riquadri stanno affiancati in st.columns(4)")
        for r in resi:
            k, item = r["k"], per_k[r["k"]]
            with self.subTest(k=k):
                titolo = r["titolo"].replace("#####", "").strip()
                self.assertEqual(app_mod.NOMI_MULTIPLA_PER_K[k],
                                 titolo.replace("★", "").strip())
                self.assertEqual(k == migliore, titolo.startswith("★"),
                                 "la ★ sta sul riquadro che riesce più spesso")
                # NUMERI: quota totale e probabilita' combinata della ricerca.
                self.assertEqual(lg.quota_italiana(item["quota_totale"]),
                                 r["metriche"].get("Quota"))
                self.assertEqual(f"{int(round(item['probabilita'] * 100))}%",
                                 r["metriche"].get("Riesce"))
                # Ogni partita: «Casa - Trasferta» e, sotto, «sigla · quando».
                testo = "\n".join(r["testi"])
                self.assertEqual(k, len(item["giocate"]))
                for g in item["giocate"]:
                    self.assertIn(f"{g['home']} - {g['away']}", testo)
                    lontana = lg.e_partita_provvisoria(g, self.ADESSO)
                    self.assertIn(f"{str(g['giocata']).strip()} · "
                                  f"{app_mod._quando_breve(g['commence_time'], lontana)}",
                                  testo)
                self.assertIn(app_mod.ETICHETTA_PROVA_QUOTE_BET365, testo)
                self.assertNotIn("Per raddoppiare", testo)

    # -- 3. «Le più probabili»: una tabella, tutte le righe, stesse colonne ---
    def test_03_le_piu_probabili_una_tabella_con_le_sei_colonne(self):
        import app as app_mod
        import lista_giocate as lg
        in_periodo, _prop = self._attese()
        attese = lg.migliori_giocate_per_partita(in_periodo, 1.20)
        df = self._df_probabili(self.at)
        self.assertEqual(app_mod.COLONNE_PRONOSTICI, list(df.columns))
        self.assertEqual(len(attese), len(df), "tutte le righe, una per partita")
        partite = [f"{g['home']} - {g['away']}" for g in attese]
        self.assertEqual(len(partite), len(set(partite)))
        self.assertEqual(sorted(partite), sorted(str(x) for x in df["Partita"]))
        quote = [float(x) for x in df["Quote %"]]
        self.assertEqual(quote, sorted(quote, reverse=True), "ordine «Quote %» decrescente")
        for g in attese:
            riga = df[df["Partita"] == f"{g['home']} - {g['away']}"].iloc[0]
            with self.subTest(partita=riga["Partita"]):
                self.assertEqual(str(g["giocata"]).strip(), riga["Pronostico"])
                self.assertEqual(round(g["probabilita"] * 100.0, 1), float(riga["Quote %"]))
                self.assertEqual(lg.quota_italiana(g["quota_b365_stimata"]), riga["Quota"])
                self.assertNotIn("provvisorie", str(riga["Partita"]))
                self.assertRegex(str(riga["Quando"]),
                                 r"^(lun|mar|mer|gio|ven|sab|dom) \d{2}/\d{2}, \d{2}:\d{2}")
        # Il filtro «Paga almeno» c'e', con il suo valore predefinito.
        sel = [s for s in self.at.selectbox if (s.key or "") == "lg_paga_almeno"]
        self.assertEqual(1, len(sel))
        self.assertEqual("1,20", sel[0].value)
        # Le tabelle in vista (fuori dai riquadri chiusi) sono una sola.
        fuori_exp = []

        def cammina(el, dentro):
            if _nome_classe(el) == "expander":
                dentro = True
            if _nome_classe(el) in ("dataframe", "arrowdataframe") and not dentro:
                fuori_exp.append(el)
            for f in _figli(el):
                cammina(f, dentro)
        cammina(_radice_tab(self.at, SCHEDA_MULTIPLE), False)
        self.assertEqual(1, len(fuori_exp), "una sola tabella in vista")

    # -- 4. nessun "None"/"nan" nel testo reso, Dettagli compresi -----------
    def test_04_nessun_none_o_nan_nel_testo_reso_dettagli_compresi(self):
        fuori, dentro = _testi_della_tab(self.at, SCHEDA_MULTIPLE)
        pezzi = list(fuori) + list(dentro)
        for el in _elementi_della_tab(self.at, SCHEDA_MULTIPLE, "dataframe"):
            pezzi += [str(c) for c in _raccogli_da_df(el)]
            df = getattr(el, "value", None)
            if df is not None and hasattr(df, "to_string"):
                pezzi.append(df.to_string(index=False))
        testo = " \n".join(pezzi)
        self.assertTrue(testo)
        self.assertEqual([], NON_NUMERO.findall(testo),
                         f"non-numero nel testo reso: {testo[:200]!r}")
        self.assertNotIn("NaN", testo)

    # -- 5. «Prova con le quote bet365» apre il calcolatore precaricato ------
    def test_05_prova_con_le_quote_bet365_precarica_e_apre(self):
        import lista_giocate as lg
        _in_periodo, prop = self._attese()
        resi = self._riquadri_resi(self.at)
        self.assertTrue(resi)
        scelto = resi[-1]                       # il riquadro con piu' partite
        k, item = scelto["k"], prop["per_k"][scelto["k"]]
        bottoni = [b for b in self.at.button if (b.key or "") == scelto["chiave"]]
        self.assertEqual(1, len(bottoni))
        bottoni[0].click()
        self.at.run(timeout=900)
        self.eccezioni(self.at, "clic su «Prova con le quote bet365»")
        self.assertTrue(self.at.session_state.get("prova_aperto"))
        exp = self._esp_prova(self.at)
        if getattr(exp, "expanded", None) is not None:
            self.assertTrue(bool(exp.expanded), "dopo il clic il riquadro e' aperto")
        sel_n = self._widget(self.at, "Selectbox", "prova_n_gambe")
        self.assertEqual(1, len(sel_n))
        self.assertEqual(k, int(sel_n[0].value))
        attese = [lg.descrivi_leg(g, self.ADESSO) for g in item["giocate"]]
        gambe = self._widget(self.at, "Selectbox", "prova_gamba_")
        self.assertEqual(k, len(gambe))
        for i, a in enumerate(attese):
            self.assertEqual(a, gambe[i].value)
        caselle = self._widget(self.at, "NumberInput", "prova_quota_")
        self.assertEqual(k, len(caselle))
        self.assertTrue(all(c.value is None for c in caselle), "caselle bet365 VUOTE")
        # E i riquadri sono ancora al loro posto, con gli stessi numeri.
        self.assertEqual([r["metriche"] for r in resi],
                         [r["metriche"] for r in self._riquadri_resi(self.at)])

    # -- 6. il clic sulla riga N apre la scheda della partita N --------------
    def test_06_selezionare_la_riga_apre_la_scheda_di_quella_partita(self):
        import app as app_mod
        from test_apptest_scheda_partita import _titolo_atteso
        df = self._df_probabili(self.at)
        self.assertGreaterEqual(len(df), 3)
        for n in (2, 0):
            casa, trasferta = [s.strip() for s in str(df.iloc[n]["Partita"]).split(" - ", 1)]
            self.at.session_state[app_mod.CHIAVE_TABELLA_PIU_PROBABILI] = {
                "selection": {"rows": [n], "columns": [], "cells": []}}
            self.at.run(timeout=900)
            self.eccezioni(self.at, f"clic sulla riga {n}")
            titoli = [str(getattr(el, "value", "") or "").strip() for el in self.at.markdown]
            atteso = "### " + _titolo_atteso(casa, trasferta)
            with self.subTest(riga=n):
                self.assertIn(atteso, titoli, f"la riga {n} apre la sua partita")
                blocco = "\n".join(titoli[titoli.index(atteso):])
                self.assertIn("Probabilità (dalle quote dei bookmaker)", blocco)
        # Il clic e' una lettura: nessuna scrittura nel registro.
        self.assertEqual([], [c for c in self.chiamate_registro
                              if c[0].startswith("save_")])

    # -- 7. l'evidenza: il testo reso, se richiesto --------------------------
    def test_07_render_dei_riquadri_e_delle_prime_righe(self):
        import app as app_mod
        if not self.render_out:
            self.skipTest("MULTIPLE_RENDER_OUT non impostata")
        righe_out = ["# Scheda 🎯 Multiple — testo reso da AppTest (snapshot pinnato, "
                     "orologio 2026-10-16 18:00 Italia, periodo «giornata»)", ""]
        fuori, _ = _testi_della_tab(self.at, SCHEDA_MULTIPLE)
        testa = []
        for t in fuori:
            if t.startswith("#####") or t == "Paga almeno":
                break
            testa.append(t)
        righe_out += ["## Testa", *[f"  {t}" for t in dict.fromkeys(testa)], ""]
        righe_out.append("## Riquadri")
        for r in self._riquadri_resi(self.at):
            righe_out.append(f"[{r['titolo'].replace('#####', '').strip()}]")
            # Il lettore di AppTest legge due attributi dello stesso elemento
            # (``value`` e ``body``): ogni riga compare due volte, qui una.
            for t in dict.fromkeys(r["testi"]):
                if t.startswith("#####"):
                    continue
                if t in r["metriche"]:
                    righe_out.append(f"  {t} {r['metriche'][t]}")
                elif t in r["metriche"].values():
                    continue
                else:
                    righe_out.append(f"  {t}")
            righe_out.append("")
        df = self._df_probabili(self.at)
        righe_out += ["## Le più probabili (prime 5 righe)",
                      "  Paga almeno: " + next(s.value for s in self.at.selectbox
                                               if (s.key or "") == "lg_paga_almeno"),
                      "  " + " | ".join(app_mod.COLONNE_PRONOSTICI)]
        for _i, riga in df.head(5).iterrows():
            righe_out.append("  " + " | ".join(str(riga[c]) for c in app_mod.COLONNE_PRONOSTICI))
        righe_out.append(f"  ... {len(df)} righe in tutto")
        with open(self.render_out, "w", encoding="utf-8") as fh:
            fh.write("\n".join(righe_out) + "\n")


if __name__ == "__main__":
    unittest.main()
