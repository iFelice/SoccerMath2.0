"""Regressioni PR #76: snapshot 16/10, nessuna rete o scrittura nel checkout."""
import copy
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'SoccerMath'), str(ROOT)]
import prediction_registry as R
import registry_coverage as C
import registry_store as B
import market_odds as M
from audit.totals_snapshot_fixture import payload_snapshot
from totals_mercato import calcola_totals


def campione():
    ev = next(e for e in M.eventi_quote(payload_snapshot()) if e['home_team'] == 'Real Madrid')
    p = M.probabilita_mercato(ev['libri'])['probs']['1']
    base = dict(match_id=ev['id'], home=ev['home_team'], away=ev['away_team'],
                kickoff_utc=ev['commence_time'], salvato_il='16/10/2026 15:20',
                origin=R.ORIGIN_TOP_MIX, tipo='Top Mix', selector_version=R.SELECTOR_VERSION_CURRENT,
                model_variant='current', mercato_standard='1', prob_sicuro=p * 100,
                prob_mercato=p, esito='⏳', campionato='La Liga')
    t = calcola_totals(ev['libri'], '1')
    ou = dict(base, origin=R.ORIGIN_MERCATO_OU, tipo='Gol (mercato)',
              selector_version='totals_mercato_v1', mercato_standard='OVER_2.5',
              prob_mercato=t['p_over'], prob_sicuro=t['p_over'] * 100,
              prob_mercato_prima=t['p_over'], prob_congiunta=t['p_congiunta'],
              mercato_fonte=t['fonte'], linea_pinnacle=t['linea_pinnacle'],
              salvato_il='17/10/2026 12:00')
    return base, ou


class TestOrigineMercatoOU(unittest.TestCase):
    def test_risoluzione_origine_esplicita_label_e_legacy_pr76(self):
        base, ou = campione()
        self.assertEqual('mercato_ou', R.resolve_origin('mercato_ou', 'Top Mix'))
        self.assertEqual('Gol (mercato)', R.tipo_for_origin('mercato_ou'))
        for row in (ou, dict(ou, origin='top_mix', tipo='Top Mix'), dict(ou, origin=''),
                    {'tipo': 'Gol (mercato)'}, {'pronostico_sicuro': 'Gol (mercato) - Top Mix'}):
            self.assertEqual('mercato_ou', R.origin_of(row))
        self.assertEqual('top_mix', R.origin_of(base))
        self.assertEqual('totals', R.famiglia_selettore(ou))

    def test_replay_indice_match_variante_non_sovrascrive_1x2(self):
        from replay_legacy_topmix import compare_with_registry
        base, ou = campione()
        t = SimpleNamespace(match_id=base['match_id'], home=base['home'], away=base['away'],
                            league='La Liga', utc=datetime(2026, 10, 18, 19, tzinfo=timezone.utc))
        click = SimpleNamespace(targets=[t], snapshot_sha='snapshot-16-10',
                                rows={'current': [dict(base, prob_val=base['prob_sicuro'])]})
        expected = compare_with_registry([base], [click])
        self.assertEqual(1, len(expected))
        for extra in (ou, dict(ou, origin='top_mix')):
            self.assertEqual(expected, compare_with_registry([base, extra], [click]))
            self.assertEqual(expected, compare_with_registry([extra, base], [click]))

    def test_coverage_dedup_conteggi_topmix_invariati(self):
        base, ou = campione()
        for extra in (ou, dict(ou, origin='top_mix')):
            self.assertEqual(C.top_mix_rows([base]), C.top_mix_rows([base, extra]))
            self.assertEqual(C.coverage_by_variant([base]), C.coverage_by_variant([base, extra]))
            self.assertEqual(R.dedup_visibili_top_mix([base]), R.dedup_visibili_top_mix([base, extra]))
            self.assertEqual(R.compute_stats([base]), R.compute_stats([base, extra]))
            self.assertEqual([base, extra], R.righe_visibili([base, extra]))

    def test_upsert_singolo_e_blocco_non_duplicano_ne_sovrascrivono_ou(self):
        base, ou = campione()
        updated = dict(ou, prob_mercato=.99, prob_congiunta=.9, mercato_fonte='altra',
                       salvato_il='18/10/2026 12:00')
        for old in (ou, dict(ou, origin='top_mix')):
            result, action = R.upsert_prediction_entry([base, old], updated)
            self.assertEqual([base, old], result)
            self.assertEqual('gia_presente', action)
            result, actions = R.upsert_prediction_entries([base, old], [updated, updated])
            self.assertEqual([base, old], result)
            self.assertEqual({'gia_presente': 2}, actions)
        result, actions = R.upsert_prediction_entries([base], [ou, updated])
        self.assertEqual([base, ou], result)
        self.assertEqual({'aggiunta': 1, 'gia_presente': 1}, actions)

    def test_backend_chiave_e_roundtrip_origine_ou(self):
        base, ou = campione()
        self.assertNotEqual(B.field_of(base), B.field_of(ou))
        self.assertIn('|mercato_ou|', B.field_of(ou))
        self.assertEqual(B.field_of(ou), B.field_of(dict(ou, origin='top_mix')))
        self.assertEqual(ou, B._row_from_value(ou))


class TestLegacyDryRun(unittest.TestCase):
    def test_legacy_compattato_e_grezzo_senza_totals_parita_b837823(self):
        from audit.live_odds_raw_fixtures import scrivi_fixture
        from audit.verifica_quote_legacy import verifica
        from update_live_odds import main
        root = ROOT / 'audit/data/live_odds_probe'
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            raw = d / 'raw'
            scrivi_fixture(str(raw))
            for fixture in (root, raw):
                out = d / 'legacy.json'
                self.assertEqual(0, main(['--fixture', str(fixture), '--out', str(out), '--dry-run']))
                self.assertFalse(out.exists())
                self.assertEqual(0, main(['--fixture', str(fixture), '--out', str(out)]))
                self.assertGreater(verifica(out, fixture), 0)
                out.unlink()
