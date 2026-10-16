"""Tabella numerica riproducibile: snapshot immobile, selettore reale invariato."""
from __future__ import annotations

import ast
import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'SoccerMath'), str(ROOT)]
from audit.totals_snapshot_fixture import SNAPSHOT, payload_snapshot
from market_odds import eventi_quote, probabilita_mercato, SOGLIA_TOPMIX_MERCATO, SOGLIA_ACCORDO, ESITI
from totals_mercato import calcola_totals


def selector_offline():
    # Esegue l'AST del selettore reale, non una sua riscrittura. Nessun import
    # dell'app, nessuna rete o scrittura collaterale durante il referto.
    source = (ROOT / 'SoccerMath/app.py').read_text()
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == 'seleziona_riga_top_mix_mercato')
    ns = dict(math=math, ESITI_MERCATO=ESITI, SOGLIA_TOPMIX_MERCATO=SOGLIA_TOPMIX_MERCATO,
              SOGLIA_ACCORDO=SOGLIA_ACCORDO)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'app.py:selector', 'exec'), ns)
    return ns[fn.name]


def righe_snapshot():
    payload = payload_snapshot()
    start = datetime.fromisoformat(json.loads((SNAPSHOT / '_summary.json').read_text())['generato_il'].replace('Z', '+00:00'))
    end = start + timedelta(days=7)
    selector = selector_offline()
    all_rows = []
    for ev in eventi_quote(payload):
        market = probabilita_mercato(ev['libri'])
        sel = selector(market['probs'], market['odds'], home=ev['home_team'], away=ev['away_team'])
        t = calcola_totals(ev['libri'], sel['esito'] if sel else '')
        if not t:
            continue
        all_rows.append({
            'partita': ev['home_team'] + '–' + ev['away_team'],
            'kickoff': ev['commence_time'], 'fonte': t['fonte'], 'linea_pinnacle': t['linea_pinnacle'],
            'p_over': t['p_over'], 'p_under': t['p_under'],
            'pronostico_1x2': sel['esito'] if sel else '',
            'p_1x2': sel['prob'] if sel else '', 'p_congiunta': t.get('p_congiunta', ''),
            'nella_finestra': start <= datetime.fromisoformat(ev['commence_time'].replace('Z', '+00:00')) < end,
        })
    return start, end, all_rows


def markdown_table(rows):
    out = ['| Partita | Fonte | Linea Pinnacle | P Over 2,5 | P Under 2,5 | 1X2 | P 1X2 | P congiunta |',
           '|---|---|---:|---:|---:|:---:|---:|---:|']
    def perc(v):
        return f'{v * 100:.9f}%' if isinstance(v, (int, float)) else '—'
    for r in rows:
        out.append(f"| {r['partita']} | {r['fonte']} | {r['linea_pinnacle']} | {perc(r['p_over'])} | "
                   f"{perc(r['p_under'])} | {r['pronostico_1x2'] or '—'} | {perc(r['p_1x2'])} | {perc(r['p_congiunta'])} |")
    return '\n'.join(out)


if __name__ == '__main__':
    start, end, rows = righe_snapshot()
    window = [r for r in rows if r['nella_finestra']]
    shown = [r for r in window if max(r['p_over'], r['p_under']) >= .67]
    print(f'Finestra UTC: [{start.isoformat()}, {end.isoformat()})')
    print(f'Eventi fittabili: {len(rows)}; nella finestra: {len(window)}; O/U >= 0.67: {len(shown)}\n')
    print(markdown_table(shown))
    print('\n## Tre partite richieste (a parte)\n')
    print(markdown_table([next(r for r in rows if r['partita'].startswith(h))
                          for h in ('Real Madrid–Sevilla', 'Bayern Munich–RB Leipzig', 'Manchester City–Ipswich Town')]))
