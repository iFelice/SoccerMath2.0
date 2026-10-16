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
        self.assertTrue(solo['Gol'].startswith('Over 2,5'))
        ou = [r for r in self.registro.vivo if r.get('selector_version') == T.TOTALS_VERSION]
        self.assertEqual(4, len(ou))
        for e in ou:
            self.assertEqual('OVER_2.5', e['mercato_standard'])
            self.assertEqual(e['prob_mercato'], e['prob_mercato_prima'])
            self.assertIn('linea_pinnacle', e)
            self.assertTrue(e['mercato_fonte'].startswith('pinnacle_linea_'))
        self.assertNotIn('prob_congiunta', next(e for e in ou if e['home'] == 'Hamburger SV'))
        for col in ('Gol', 'Insieme %'):
            self.assertTrue(all(isinstance(v, str) for v in df[col]))
            self.assertFalse(df[col].str.contains(r'None|nan|NaN').any())
        # Output reale raccolto per il referto, non una tabella ricopiata a mano.
        dest = Path(__file__).resolve().parent.parent / 'audit/results/totals_mercato_v1'
        dest.mkdir(parents=True, exist_ok=True)
        (dest / 'apptest-table.txt').write_text(df.to_string(index=False) + '\n')
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
