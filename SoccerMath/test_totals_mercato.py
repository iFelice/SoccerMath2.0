"""Produzione O/U: solo fixture offline del 16/10 e casi limite sintetici."""
import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import numpy as np
import totals_mercato as T
import market_odds as M
from audit import griglia_core as G
from audit.totals_snapshot_fixture import payload_snapshot, write_raw
from update_live_odds import libri_dell_evento, totals_dal_bookmaker, MERCATO


class TestTotalsMercato(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = payload_snapshot()
        cls.events = M.eventi_quote(cls.payload)

    def test_parita_snapshot_tutti_gli_eventi_fittabili(self):
        n = 0
        for ev in self.events:
            pin = next(b for b in ev['libri'] if b['key'] == 'pinnacle')
            lines = sorted((float(k), v) for k, v in pin['totals'].items()
                           if G.devig_prop([v.get('Over', 0), v.get('Under', 0)]) is not None)
            line, q = lines[0]
            probs = G.devig_prop(M.ternaria_h2h(pin))
            target = G.devig_prop([q['Over'], q['Under']])[0]
            fit = G.fit_implicit_line(*probs, target, line)
            if not fit['converged'] or fit['max_abs_resid'] > 1e-5:
                continue
            m = G.dc_matrix(fit['lam'], fit['mu'], fit['rho'])
            actual = T.calcola_totals(ev['libri'])
            self.assertTrue(actual, ev['id'])
            self.assertLessEqual(abs(actual['p_over'] - G.grid_line_prob(m, 2.5)), 1e-9)
            n += 1
        self.assertEqual(97, n)
        print(f'Parità snapshot: {n} eventi, tolleranza 1e-9')

    def test_linee_intere_mezze_quarti(self):
        for line in (2, 2.25, 2.5, 2.75, 3, 3.5, 4.5):
            m = T.dc_matrix(1.9, 1.4, -.06)
            for side in ('over', 'under'):
                np.testing.assert_allclose(T.grid_line_parts(m, line, side), G.grid_line_parts(m, line, side), atol=1e-15)
            self.assertAlmostEqual(1, T.grid_line_prob(m, line) + T.grid_line_prob(m, line, 'under'))

    def test_legacy_senza_totals_si_legge_senza_ou(self):
        old = json.loads((HERE.parent / 'audit/data/totals_probe/2026-10-16_1320/_live_odds_pinnato.json').read_text())
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'live_odds.json').write_text(json.dumps(old))
            payload = M.carica_quote_live(str(Path(d, "live_odds.json")))
            self.assertTrue(payload)
            for e in M.eventi_quote(payload):
                self.assertEqual({}, T.calcola_totals(e['libri']))

    def test_riserva_mediana_minimo_tre_e_terna_di_riserva(self):
        ev = self.events[0]
        libri = copy.deepcopy(ev['libri'])
        for b in libri:
            b.pop('totals', None)
        for b, q in zip(libri[:3], (1.4, 1.9, 2.2)):
            b['totals'] = {'2.5': {'Over': q, 'Under': 2.0}}
        pin = next(b for b in libri if b['key'] == 'pinnacle')
        pin.pop('totals', None)
        # Exactly three distinct non-Pinnacle books.
        nonpin = [b for b in libri if b['key'] != 'pinnacle'][:3]
        for b, q in zip(nonpin, (1.4, 1.9, 2.2)):
            b['totals'] = {'2.5': {'Over': q, 'Under': 2.0}}
        for source in (nonpin + [pin], nonpin):
            t = T.calcola_totals(source)
            self.assertEqual('consenso_2.5', t['fonte'])
            self.assertEqual('', t['linea_pinnacle'])
            self.assertAlmostEqual(2 / 3.9, t['target'])
        self.assertEqual({}, T.calcola_totals(nonpin[:2] + [pin]))
        self.assertEqual({}, T.calcola_totals([nonpin[0]] * 3))

    def test_primaria_linea_piu_bassa_valida(self):
        pin = copy.deepcopy(next(b for b in self.events[0]['libri'] if b['key'] == 'pinnacle'))
        pin['totals'] = {'3.5': {'Over': 2, 'Under': 2}, '3.25': {'Over': 2, 'Under': 2},
                         '2.5': {'Over': float('nan'), 'Under': 2}, 'no': {}, '2.6': {'Over': 2, 'Under': 2}}
        self.assertEqual(3.25, T.calcola_totals([pin])['linea_pinnacle'])

    def test_congiunta_e_riquadro_non_prodotto(self):
        e = next(e for e in self.events if e['home_team'] == 'Real Madrid')
        t = T.calcola_totals(e['libri'], '1')
        p = t['probs_1x2']
        fit = G.fit_implicit_line(p['1'], p['X'], p['2'], t['target'], t['linea_fit'])
        m = G.dc_matrix(fit['lam'], fit['mu'], fit['rho'])
        self.assertAlmostEqual(float(m[(G.I > G.J) & (G.I + G.J > 2.5)].sum()), t['p_congiunta'], places=12)
        self.assertGreater(abs(t['p_congiunta'] - p['1'] * t['p_over']), .001)
        self.assertNotIn('p_congiunta', T.calcola_totals(e['libri']))

    def test_soglia_e_celle_senza_non_numeri(self):
        for over, expected in ((.669999, ''), (.67, 'Over'), (1 - .67, 'Under'), (.5, '')):
            # Griglia normalizzata costruita per esercitare il bordo senza fit.
            m = np.zeros((T.N, T.N)); m[3, 0] = over; m[0, 0] = 1-over
            with patch.object(T, '_fit_grid', return_value=m):
                t = T.calcola_totals(self.events[0]['libri'], '1')
            self.assertEqual(expected, t['pronostico'])
            self.assertEqual(bool(expected), 'p_congiunta' in t)
            for v in T.celle_totals(t).values():
                self.assertIsInstance(v, str)
                self.assertNotRegex(v.lower(), r'none|nan')

    def test_writer_conserva_tutte_le_linee_e_totals_senza_h2h(self):
        b = {'key': 'test', 'markets': [{'key': 'totals', 'outcomes': [
            {'name': side, 'price': 1.9, 'point': line}
            for line in (2, 2.25, 2.5, 2.75, 3.5) for side in ('Over', 'Under')]}]}
        self.assertEqual('h2h,totals', MERCATO)
        self.assertEqual(5, len(totals_dal_bookmaker(b)))
        self.assertEqual(5, len(libri_dell_evento({'bookmakers': [b]})[0]['totals']))
        with tempfile.TemporaryDirectory() as d:
            write_raw(d)
            e = json.loads(next(Path(d).glob('*.json')).read_text())['events'][0]
            self.assertTrue(any(b['totals'] for b in libri_dell_evento(e)))
            from update_live_odds import scarica_lega_fixture
            blocks = [scarica_lega_fixture(sport, d) for sport in (
                'soccer_italy_serie_a', 'soccer_epl', 'soccer_spain_la_liga',
                'soccer_germany_bundesliga', 'soccer_france_ligue_one')]
            self.assertEqual(97, sum(b['n_eventi'] for b in blocks))
            for block in blocks:
                self.assertIsNone(block['errore'])
                for ev in block['eventi']:
                    self.assertTrue(any(b.get('totals') for b in ev['libri']))


if __name__ == '__main__':
    unittest.main()
