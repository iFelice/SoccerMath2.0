"""AppTest O/U con quote reali del 16/10, solo kickoff riposizionati nel futuro.

Lo storage, il calendario e la rete sono intercettati dal harness esistente.
Le cinque partite conservano nomi e quote dello snapshot, comprese quelle
senza scelta 1X2. Nessuna chiamata reale o scrittura al registro di produzione.
"""
import copy
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent.parent)]
from test_apptest_scheda_pronostici import (
    FixtureQuoteFinte, _BaseQuoteFinte, ETICHETTA_CALCOLA, SCHEDA_PRONOSTICI,
)
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
        self.assertEqual('n/d', solo['Modello %'])
        self.assertEqual('', solo['Insieme %'])
        self.assertEqual('', solo['Quote %'])
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
        self.assertEqual(['', ''], df['Quote %'].tolist()[1:])
        self.assertEqual(['', ''], df['Quota'].tolist()[1:])
        self.assertEqual(['—', '—'], df['Pronostico'].tolist()[1:])
        self.assertEqual(['n/d', 'n/d'], df['Modello %'].tolist()[1:])
        self.assertTrue(all(isinstance(v, str) for v in df['Quote %'].tolist()[1:]))

    def test_05_righe_1x2_identiche_alla_presentazione_b837823(self):
        import ast
        import subprocess
        import app as A
        src = subprocess.check_output(['git', 'show', 'b837823:SoccerMath/app.py'], text=True)
        node = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)
                    and n.name == 'riga_pronostico_da_mercato')
        ns = dict(A.__dict__)
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<base>', 'exec'), ns)
        rows, _ = A.righe_pronostici_dalle_quote(self.payload, self.ADESSO)
        for row in rows:
            if row.get('solo_ou'):
                continue
            before = ns[node.name](row, self.ADESSO)
            after = A.riga_pronostico_da_mercato(row, self.ADESSO)
            self.assertEqual(before, {k: after[k] for k in before})

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
