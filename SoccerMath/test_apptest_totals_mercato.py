"""AppTest O/U con quote reali del 16/10, solo kickoff riposizionati nel futuro.

Lo storage, il calendario e la rete sono intercettati dal harness esistente.
Le cinque partite conservano nomi e quote dello snapshot, comprese quelle
senza scelta 1X2. Nessuna chiamata reale o scrittura al registro di produzione.
"""
import copy
import json
import sys

import pandas as pd
from datetime import timedelta
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent.parent)]
from test_apptest_scheda_pronostici import (
    FixtureQuoteFinte, _BaseQuoteFinte, ETICHETTA_CALCOLA, SCHEDA_PRONOSTICI, SCHEDA_REGISTRO,
)
from test_apptest_topmix_presentazione import _riquadro_della_tab
from audit.totals_snapshot_fixture import payload_snapshot
import market_odds as M
import totals_mercato as T


class FixtureSnapshot(FixtureQuoteFinte):
    @classmethod
    def eventi(cls):
        es = M.eventi_quote(payload_snapshot())
        return [next(e for e in es if e['home_team'] == h) for h in
                ('Real Madrid', 'Bayern Munich', 'Manchester City', 'Hamburger SV', 'Everton')]

    @classmethod
    def pianifica(cls, adesso):
        return [(111 + i, e['home_team'], e['away_team'],
                 tuple(M.probabilita_mercato(e['libri'])['probs'].values()),
                 adesso + timedelta(hours=8 + i * 2)) for i, e in enumerate(cls.eventi())]

    @classmethod
    def payload_quote(cls, adesso):
        payload = super().payload_quote(adesso)
        for ev, real in zip(payload['leghe']['Serie A']['eventi'], cls.eventi()):
            ev['libri'] = copy.deepcopy(real['libri'])
        return payload


class TestAppTotals(_BaseQuoteFinte):
    FIXTURE = FixtureSnapshot

    def test_01_tabella_snapshot_e_registro_separato(self):
        self._premi_click(self.at, ETICHETTA_CALCOLA)
        df = self._df(self.at, SCHEDA_PRONOSTICI)
        self.assertIn('Gol', df.columns)
        self.assertIn('Insieme %', df.columns)
        self.assertEqual(4, sum(bool(v) for v in df['Gol']))
        solo = df[df['Partita'].str.startswith('Hamburger SV')].iloc[0]
        self.assertEqual('—', solo['Pronostico'])
        self.assertNotIn('Modello %', df.columns,
                         'la tabella del periodo non ha piu la colonna Modello %')
        self.assertEqual('', solo['Insieme %'])
        # Righe solo gol: «Quote %» e' un valore MANCANTE (NaN), non una
        # stringa vuota — la ProgressColumn disegna la cella vuota.
        self.assertTrue(pd.isna(solo['Quote %']))
        self.assertEqual('', solo['Quota'])
        self.assertTrue(solo['Gol'].startswith('Over 2,5'))
        ou = [r for r in self.registro.vivo if r.get('selector_version') == T.TOTALS_VERSION]
        self.assertEqual(4, len(ou))
        for e in ou:
            self.assertEqual('OVER_2.5', e['mercato_standard'])
            self.assertEqual('mercato_ou', e['origin'])
            self.assertEqual('Gol (mercato)', e['tipo'])
            self.assertEqual(e['prob_mercato'], e['prob_mercato_prima'])
            self.assertIn('linea_pinnacle', e)
            self.assertTrue(e['mercato_fonte'].startswith('pinnacle_linea_'))
        self.assertNotIn('prob_congiunta', next(e for e in ou if e['home'] == 'Hamburger SV'))
        for col in ('Gol', 'Insieme %'):
            self.assertTrue(all(isinstance(v, str) for v in df[col]))
            self.assertFalse(df[col].str.contains(r'None|nan|NaN').any())
        self.prime_ou = copy.deepcopy(ou)
        self.__class__.prime_ou = ou

    def test_02_secondo_click_congela_prima_registrazione_ou(self):
        # Il prezzo cambia al secondo click: la prima probabilità, fonte e
        # congiunta registrate NON devono essere ricalcolate/sovrascritte.
        payload = copy.deepcopy(self.payload)
        for ev in payload["leghe"]["Serie A"]["eventi"]:
            for b in ev["libri"]:
                for q in b.get("totals", {}).values():
                    q["Over"], q["Under"] = 2.0, 2.0
        (self.tmp / "live_odds.json").write_text(json.dumps(payload))
        import streamlit as st
        st.cache_data.clear()
        self._premi_click(self.at, ETICHETTA_CALCOLA)
        ou = [r for r in self.registro.vivo if r.get('selector_version') == T.TOTALS_VERSION]
        self.assertEqual(self.prime_ou, ou)
        from prediction_registry import famiglia_selettore
        self.assertTrue(all(famiglia_selettore(r) == 'totals' for r in ou))
        self.assertEqual(3, sum('prob_congiunta' in r for r in ou))

    def test_03_scheda_partita_sopra_e_sotto_soglia(self):
        import scheda_partita as S
        for ev in self.FIXTURE.eventi():
            card = S.costruisci_scheda('Serie A', ev['home_team'], ev['away_team'],
                                      evento_quote=ev, storico_elo={})
            text = S.testo_scheda(card)
            self.assertIn('Gol:', text)
            if ev['home_team'] == 'Everton':
                self.assertIn('P(Over 2,5)', text)
                self.assertIn('nessun pronostico', text)
            else:
                self.assertIn('Gol: Over 2,5', text)

    def test_04_solo_ou_in_fondo_per_probabilita_non_percentuale_arrotondata(self):
        import app as A
        rows, _ = A.righe_pronostici_dalle_quote(self.payload, self.ADESSO)
        only = next(r for r in rows if r.get('solo_ou'))
        high = copy.deepcopy(only)
        high['home'] = 'Solo OU alto'
        high['totals']['p_over'], high['totals']['p_under'] = .697, .303
        low = copy.deepcopy(only)
        low['home'] = 'Solo OU basso'
        low['totals']['p_over'], low['totals']['p_under'] = .694, .306
        one = next(r for r in rows if not r.get('solo_ou'))
        normalized = [A.riga_pronostico_da_mercato(r, self.ADESSO) for r in (low, high, one)]
        df, ordered = A.tabella_pronostici_visibile(normalized)
        self.assertEqual([one['home'], 'Solo OU alto', 'Solo OU basso'],
                         [r['Partita'].split(' - ')[0] for r in ordered])
        # Le due righe solo gol non hanno una probabilita' 1X2: «Quote %» e'
        # NaN, e la colonna resta NUMERICA (ProgressColumn, ordinamento per
        # valore) invece di convertirsi a testo.
        self.assertTrue(pd.api.types.is_numeric_dtype(df['Quote %']))
        self.assertTrue(df['Quote %'].iloc[1:].isna().all())
        self.assertEqual(['', ''], df['Quota'].tolist()[1:])
        self.assertEqual(['—', '—'], df['Pronostico'].tolist()[1:])
        self.assertNotIn('Modello %', df.columns)

    def test_05_righe_1x2_identiche_alla_presentazione_b837823(self):
        """La riga 1X2 e' quella di ``b837823``, con due differenze dichiarate.

        Il confronto e' con la funzione del commit ``b837823`` (la
        presentazione da cui la tabella e' nata): stessi valori, chiave per
        chiave. Le differenze volute sono due, e il test le scrive invece di
        saltarle, cosi' una terza — o il ritorno di una di queste — lo fa
        fallire:

        * «Modello %» non c'e' piu': il modello sta nella scheda partita e nei
          Dettagli, non nelle tabelle in vista;
        * ci sono due chiavi di servizio, ``solo_ou`` e ``_prob_ou``: non sono
          colonne, le legge l'ordinamento delle righe che hanno solo i gol.
        """
        import ast
        import subprocess
        import app as A
        try:
            src = subprocess.check_output(
                ['git', 'show', 'b837823:SoccerMath/app.py'], text=True,
                stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            # Clone shallow: il commit di riferimento non c'e'. Stessa regola
            # di ``snap_test``: il test si salta, non fallisce.
            self.skipTest('commit b837823 non raggiungibile (clone shallow)')
        node = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)
                    and n.name == 'riga_pronostico_da_mercato')
        ns = dict(A.__dict__)
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<base>', 'exec'), ns)
        rows, _ = A.righe_pronostici_dalle_quote(self.payload, self.ADESSO)
        tolte = {"Modello %"}                       # la colonna uscita da qui
        aggiunte = {"solo_ou", "_prob_ou"}           # chiavi di servizio
        viste = 0
        for row in rows:
            if row.get('solo_ou'):
                continue
            before = ns[node.name](row, self.ADESSO)
            after = A.riga_pronostico_da_mercato(row, self.ADESSO)
            viste += 1
            with self.subTest(partita=after["Partita"]):
                self.assertEqual((set(before) - set(after), set(after) - set(before)),
                                 (tolte, aggiunte),
                                 "le sole differenze sono «Modello %» (via) e "
                                 "le due chiavi di servizio (dentro)")
                comuni = [k for k in before if k not in tolte]
                self.assertEqual({k: before[k] for k in comuni},
                                 {k: after[k] for k in comuni})
        self.assertGreater(viste, 0, "nessuna riga 1X2 da confrontare")

    def test_06_frasi_topmix_e_ou_filtrate_per_origine(self):
        import app as A
        from test_totals_correzioni import campione
        base, ou = campione()
        self.assertEqual(A.ultima_registrazione_mercato([base]),
                         A.ultima_registrazione_mercato([base, ou]))
        self.assertEqual('Gol · Nessuna registrazione finora', A.ultima_registrazione_ou([base]))
        self.assertEqual(A.ultima_registrazione_ou([ou]), A.ultima_registrazione_ou([base, ou]))
        self.assertIn('17/10/2026', A.ultima_registrazione_ou([base, ou]))
        self.assertNotIn('17/10/2026', A.ultima_registrazione_mercato([base, ou]))

    def test_07_multiple_liste_conteggi_e_riquadri_invariati_con_ou_nel_registro(self):
        import app as A
        import lista_giocate as L
        from unittest.mock import patch
        from test_totals_correzioni import campione
        base, ou = campione()
        with patch.object(A, 'load_predictions', return_value=[base]):
            old = L.calcola_lista_giocate(self.payload, self.ADESSO)
        with patch.object(A, 'load_predictions', return_value=[base, ou]):
            new = L.calcola_lista_giocate(self.payload, self.ADESSO)
        self.assertEqual(old, new)
        self.assertEqual(L.migliori_giocate_per_partita(old['giocate']),
                         L.migliori_giocate_per_partita(new['giocate']))
        # Le proposte di Multiple nascono solo dalle stesse giocate 1X2,
        # non dal registro: anche il pool e il numero di partite restano uguali.
        self.assertEqual(old['n_partite_ammesse'], new['n_partite_ammesse'])
        self.assertEqual(A.riquadri_multiple(L.cerca_proposta_multipla(old['giocate']), self.ADESSO),
                         A.riquadri_multiple(L.cerca_proposta_multipla(new['giocate']), self.ADESSO))

    def test_08_tabella_gol_mercato_registro_scala_percentuale(self):
        from test_apptest_topmix_presentazione import _elementi_della_tab, _testi_della_tab
        df_gol = self._df(self.at, SCHEDA_REGISTRO, 0)
        self.assertEqual(
            ['Quando', 'Partita', 'Pronostico', 'Quote %', 'Insieme %', 'Risultato', 'Esito'],
            list(df_gol.columns),
        )
        self.assertEqual(
            ['Real Madrid - Sevilla', 'Bayern Munich - RB Leipzig',
             'Manchester City - Ipswich Town', 'Hamburger SV - VfB Stuttgart'],
            df_gol['Partita'].tolist(),
        )
        self.assertEqual(['⏳'] * 4, df_gol['Esito'].tolist())
        per_partita = df_gol.set_index('Partita')
        self.assertEqual('85,1', per_partita.loc['Bayern Munich - RB Leipzig', 'Quote %'])
        self.assertEqual('70,4', per_partita.loc['Bayern Munich - RB Leipzig', 'Insieme %'])
        self.assertEqual('68,2', per_partita.loc['Real Madrid - Sevilla', 'Quote %'])
        self.assertEqual('59,0', per_partita.loc['Real Madrid - Sevilla', 'Insieme %'])
        self.assertEqual('69,3', per_partita.loc['Hamburger SV - VfB Stuttgart', 'Quote %'])
        self.assertEqual('', per_partita.loc['Hamburger SV - VfB Stuttgart', 'Insieme %'])
        # Modello %, Fonte e Linea Pinnacle stanno nella tabella tecnica dentro i Dettagli.
        dettagli = next(e for e in _elementi_della_tab(self.at, SCHEDA_REGISTRO, 'expander')
                        if 'Dettagli' in str(e.label or ''))
        tabelle_dettagli = []
        for el in _elementi_della_tab(self.at, SCHEDA_REGISTRO, 'dataframe')[1:]:
            val = getattr(el, 'value', None)
            if val is not None and hasattr(val, 'data'):
                val = val.data
            if hasattr(val, 'columns') and list(val.columns) == ['Partita', 'Pronostico', 'Modello %', 'Fonte', 'Linea Pinnacle']:
                tabelle_dettagli.append(val)
        self.assertEqual(1, len(tabelle_dettagli))
        df_tec = tabelle_dettagli[0]
        self.assertEqual(df_gol['Partita'].tolist(), df_tec['Partita'].tolist())
        self.assertEqual(['n/d'] * 4, df_tec['Modello %'].tolist())
        self.assertTrue(all(str(v).startswith('pinnacle_linea_') for v in df_tec['Fonte']))
        _, dentro = _testi_della_tab(self.at, SCHEDA_REGISTRO)
        self.assertIn('Linea Pinnacle', ' \n'.join(dentro))

    def test_09_ordine_tabella_gol_mercato_in_attesa_e_concluse_mescolate(self):
        import app as A
        from test_totals_correzioni import campione
        _, base_ou = campione()
        righe_mescolate = [
            dict(base_ou, match_id='m1', home='Casa C2', away='Ospite C2',
                 data='15/10/2026 18:30', kickoff_utc='2026-10-15T16:30:00Z',
                 risultato_reale='2-1', esito='✅'),
            dict(base_ou, match_id='m2', home='Casa A2', away='Ospite A2',
                 data='18/10/2026 20:45', kickoff_utc='2026-10-18T18:45:00Z',
                 risultato_reale=None, esito='⏳'),
            dict(base_ou, match_id='m3', home='Casa C1', away='Ospite C1',
                 data='16/10/2026 20:45', kickoff_utc='2026-10-16T18:45:00Z',
                 risultato_reale='1-0', esito='❌'),
            dict(base_ou, match_id='m4', home='Casa A1', away='Ospite A1',
                 data='18/10/2026 15:00', kickoff_utc='2026-10-18T13:00:00Z',
                 risultato_reale=None, esito=None),
            dict(base_ou, match_id='m5', home='Casa C3', away='Ospite C3',
                 data='14/10/2026 20:45', kickoff_utc='2026-10-14T18:45:00Z',
                 risultato_reale='3-1', esito='✅'),
        ]
        df = A.tabella_gol_mercato(righe_mescolate)
        self.assertEqual(
            ['Quando', 'Partita', 'Pronostico', 'Quote %', 'Insieme %', 'Risultato', 'Esito'],
            list(df.columns),
        )
        self.assertEqual(
            ['Casa A1 - Ospite A1', 'Casa A2 - Ospite A2',
             'Casa C1 - Ospite C1', 'Casa C2 - Ospite C2', 'Casa C3 - Ospite C3'],
            df['Partita'].tolist(),
        )
        self.assertEqual(
            ['18/10/2026 15:00', '18/10/2026 20:45',
             '16/10/2026 20:45', '15/10/2026 18:30', '14/10/2026 20:45'],
            df['Quando'].tolist(),
        )
        self.assertEqual(['⏳', '⏳', '❌', '✅', '✅'], df['Esito'].tolist())
        self.assertEqual(['', '', '1-0', '2-1', '3-1'], df['Risultato'].tolist())
        df_tec = A.tabella_gol_mercato_tecnica(righe_mescolate)
        self.assertEqual(
            ['Partita', 'Pronostico', 'Modello %', 'Fonte', 'Linea Pinnacle'],
            list(df_tec.columns),
        )
        self.assertEqual(df['Partita'].tolist(), df_tec['Partita'].tolist())

    def test_10_riepilogo_gol_mercato_dieci_concluse_otto_riuscite(self):
        import app as A
        from test_totals_correzioni import campione
        from test_apptest_topmix_presentazione import _testi_della_tab
        _, base_ou = campione()
        # Senza voci concluse nello snapshot iniziale il riquadro del gol dice
        # «n/d» e non ha delta: nessuno 0% inventato.
        gol = _riquadro_della_tab(self.at, SCHEDA_REGISTRO, 'Registro gol')
        self.assertEqual('n/d', gol.value)
        self.assertFalse(gol.delta)
        # La frase in parole resta la forma di controllo dei riquadri: qui non
        # si disegna piu' in scheda, ma deve dire gli stessi numeri.
        self.assertEqual('Gol: nessuna giocata conclusa finora.', A.sintesi_gol_mercato([]))
        # Registro di prova con 10 voci O/U: 8 riuscite e 2 fallite.
        dieci_voci = [
            dict(
                base_ou,
                match_id=f'ou_{i}',
                home=f'Squadra Casa {i}',
                away=f'Squadra Ospite {i}',
                campionato='Serie A',
                stagione='2026/2027',
                data=f'{10 + i:02d}/10/2026 18:00',
                kickoff_utc=f'2026-10-{10 + i:02d}T16:00:00Z',
                prob_mercato_prima=0.72,
                prob_sicuro=72.0,
                risultato_reale='2-1' if i < 8 else '1-0',
                esito='✅' if i < 8 else '❌',
            )
            for i in range(10)
        ]
        frase = A.sintesi_gol_mercato(dieci_voci)
        self.assertEqual('Gol: finora 10 giocate concluse, 8 riuscite (80%). Quote: 72%.', frase)
        self.assertIn('10 giocate concluse, 8 riuscite (80%)', frase)
        precedenti = copy.deepcopy(self.registro.vivo)
        try:
            self.registro.vivo[:] = [r for r in precedenti if r.get('selector_version') != T.TOTALS_VERSION] + dieci_voci
            self.at.run(timeout=900)
            self.eccezioni(self.at, 'riepilogo 10 voci O/U')
            fuori_dopo, _ = _testi_della_tab(self.at, SCHEDA_REGISTRO)
            # Il riquadro del gol legge le stesse righe della tabella: 8 su 10
            # sono l'80%; le attese (probabilita' della prima registrazione,
            # 0,72 su tutte e dieci) sono il 72%, quindi lo scarto e' +8 punti.
            gol_dopo = _riquadro_della_tab(self.at, SCHEDA_REGISTRO, 'Registro gol')
            self.assertEqual('80%', gol_dopo.value)
            self.assertEqual('+8 punti sulle attese', gol_dopo.delta)
            self.assertIn('8 riuscite su 10 concluse', gol_dopo.help)
            # La frase non si disegna piu' in scheda (gli stessi numeri stanno
            # nel riquadro) e non deve comparire nemmeno nel testo reso.
            self.assertNotIn('Gol: finora', ' \n'.join(fuori_dopo))
            df_gol = self._df(self.at, SCHEDA_REGISTRO, 0)
            self.assertEqual(10, len(df_gol))
        finally:
            self.registro.vivo[:] = precedenti
            self.at.run(timeout=900)

    def test_11_filtri_esito_e_origine_su_tabella_gol_mercato(self):
        from test_totals_correzioni import campione
        from test_apptest_topmix_presentazione import _testi_della_tab
        base_1x2, base_ou = campione()
        riga_1x2 = dict(
            base_1x2,
            match_id='1x2_1',
            home='Inter',
            away='Roma',
            campionato='Serie A',
            stagione='2026/2027',
            data='15/10/2026 20:45',
            kickoff_utc='2026-10-15T18:45:00Z',
            prob_mercato_prima=0.65,
            risultato_reale='2-0',
            esito='✅',
        )
        voci_ou = [
            dict(
                base_ou,
                match_id=f'ou_f_{i}',
                home=f'Casa {i}',
                away=f'Ospite {i}',
                campionato='Serie A' if i < 5 else 'La Liga',
                stagione='2026/2027',
                data=f'{10 + i:02d}/10/2026 18:00',
                kickoff_utc=f'2026-10-{10 + i:02d}T16:00:00Z',
                prob_mercato_prima=0.70,
                prob_sicuro=70.0,
                risultato_reale='2-1' if i < 8 else ('1-0' if i < 10 else None),
                esito='✅' if i < 8 else ('❌' if i < 10 else '⏳'),
            )
            for i in range(11)
        ]
        tutti = [riga_1x2] + voci_ou
        precedenti = copy.deepcopy(self.registro.vivo)
        try:
            self.registro.vivo[:] = tutti
            self.at.run(timeout=900)
            sel_esito = next(s for s in self.at.selectbox if s.label == 'Esito')
            sel_origine = next(s for s in self.at.selectbox if s.label == 'Origine')
            self.assertIn('Gol (mercato)', list(sel_origine.options))
            # Filtro Origine = Gol (mercato), Esito = Vinte (✅)
            sel_origine.set_value('Gol (mercato)')
            sel_esito.set_value('Vinte (✅)')
            self.at.run(timeout=900)
            self.eccezioni(self.at, 'filtro Gol (mercato) + Vinte')
            df_vinte = self._df(self.at, SCHEDA_REGISTRO, 0)
            self.assertEqual(8, len(df_vinte))
            self.assertEqual(['✅'] * 8, df_vinte['Esito'].tolist())
            fuori_vinte, _ = _testi_della_tab(self.at, SCHEDA_REGISTRO)
            self.assertIn('Nessuna riga della famiglia mercato con i filtri attivi.', ' \n'.join(fuori_vinte))
            # Filtro Esito = Perse (❌)
            next(s for s in self.at.selectbox if s.label == 'Esito').set_value('Perse (❌)')
            self.at.run(timeout=900)
            df_perse = self._df(self.at, SCHEDA_REGISTRO, 0)
            self.assertEqual(2, len(df_perse))
            self.assertEqual(['❌'] * 2, df_perse['Esito'].tolist())
            # Filtro Origine = Top Mix: la tabella Gol - mercato viene filtrata via
            next(s for s in self.at.selectbox if s.label == 'Esito').set_value('Tutti')
            next(s for s in self.at.selectbox if s.label == 'Origine').set_value('Top Mix')
            self.at.run(timeout=900)
            fuori_topmix, _ = _testi_della_tab(self.at, SCHEDA_REGISTRO)
            self.assertNotIn('Gol — mercato', ' \n'.join(fuori_topmix))
        finally:
            self.registro.vivo[:] = precedenti
            next(s for s in self.at.selectbox if s.label == 'Esito').set_value('Tutti')
            next(s for s in self.at.selectbox if s.label == 'Origine').set_value('Tutti')
            self.at.run(timeout=900)



