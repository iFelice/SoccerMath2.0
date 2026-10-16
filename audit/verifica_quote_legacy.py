"""Controllo offline del writer legacy: output reale vs codice della PR #76.

Il dry-run non scrive file: il chiamante genera anche un JSON in /tmp con
--fixture (sempre zero rete) e questo controllo confronta le sue P 1X2 con
writer e matematica al commit b837823. Nessun import del modulo O/U.
"""
import argparse
import json
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'SoccerMath'))
BASE = 'b837823'


def modulo_base(name):
    text = subprocess.check_output(['git', 'show', f'{BASE}:SoccerMath/{name}.py'], cwd=ROOT, text=True)
    module = types.ModuleType('_legacy_' + name)
    module.__file__ = str(ROOT / 'SoccerMath' / (name + '.py'))
    exec(compile(text, module.__file__, 'exec'), module.__dict__)
    return module


def verifica(file, fixture):
    payload = json.loads(Path(file).read_text())
    assert isinstance(payload.get('leghe'), dict) and payload['leghe'], 'leghe assenti'
    writer = modulo_base('update_live_odds')
    market = modulo_base('market_odds')
    n = 0
    for lega, sport in writer.LEGA_SPORT_KEY.items():
        before = writer.scarica_lega_fixture(sport, str(fixture))
        actual = payload['leghe'][lega]['eventi']
        expected = {ev['id']: ev for ev in before['eventi']}
        assert {ev['id'] for ev in actual} == set(expected)
        for ev in actual:
            assert not any(b.get('totals') for b in ev['libri']), 'totals nel formato legacy'
            p = market.probabilita_mercato(ev['libri'])
            old = market.probabilita_mercato(expected[ev['id']]['libri'])
            assert p == old, f'1X2 modificato: {ev["id"]}'
            n += 1
    print(f'Legacy: leghe=5; eventi={n}; P 1X2 identiche a {BASE} (differenza=0); nessun dato O/U')
    return n


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', required=True)
    parser.add_argument('--fixture', required=True)
    args = parser.parse_args()
    verifica(args.file, args.fixture)
