# Replay offline del Top Mix di mercato (`topmix_mercato_v3`)

Generato da `audit/replay_topmix_mercato.py` il 2026-10-09T13:07:08Z (commit `bcbeb74`, branch `arena/ffcc5cc6-soccermath2-0`). Nessuna rete, nessuna scrittura nel Registro.

Comando: `python audit/replay_topmix_mercato.py`.

## 0. Cosa riproduce

| Elemento | Fonte |
|---|---|
| Quote | CSV storici `SoccerMath/database/*_2024.csv` e `*_2025.csv`, colonne B365H/B365D/B365A (pre-chiusura, come nella PR #49) |
| De-vig | `market_odds.devig_proporzionale` (PRODUZIONE), verificato riga per riga contro le colonne `pre*` della PR #49: scarto massimo 0.00e+00 |
| Scelta | `app.seleziona_riga_top_mix_mercato` (PRODUZIONE): argmax delle probabilita' di mercato, ammissione a 0,55 |
| Segnale "d'accordo" | `market_odds.SOGLIA_ACCORDO` = 0,55, stesso esito (definizione PR #49 §4d) |
| Probabilita' del modello | colonne `m0/m1/m2` del frame PR #49 (blend 0,25 Poisson + 0,75 Elo walker) |
| Campione | 3504 righe (2024/25 + 2025/26, con modello e con terna B365 pre) |

## 1. Confronto con la PR #49

| Voce | Fonte PR #49 | n PR #49 | n replay | Δn | hit PR #49 | hit replay | Δhit | coincide |
|---|---|---|---|---|---|---|---|---|
| scelte_mercato | §4, pooled OOS, mercato B365 pre (prop.) | 1302 | 1302 | +0 | 0.6751 | 0.6751 | +0.0000 | SÌ |
| accordo | §4d tabella B, scelte del modello CON consenso | 1144 | 1144 | +0 | 0.6818 | 0.6818 | +0.0000 | SÌ |
| senza_accordo | §4d tabella B, scelte del modello SENZA consenso | 335 | 335 | +0 | 0.4358 | 0.4358 | +0.0000 | SÌ |

**Esito del confronto: PARITÀ** (tolleranze dichiarate: Δn ≤ 0, |Δhit| ≤ 0.0005).

## 2. Numeri del replay

| Gruppo | n | vinte | hit rate | IC 95% (Wilson) |
|---|---|---|---|---|
| Scelte del mercato (soglia 0,55) | 1302 | 879 | 0.6751 | [0.6492; 0.7000] |
| Scelte del modello CON accordo | 1144 | 780 | 0.6818 | [0.6543; 0.7082] |
| Scelte del modello SENZA accordo | 335 | 146 | 0.4358 | [0.3837; 0.4894] |

Lettura delle scelte di MERCATO separate per accordo (informazione aggiuntiva, non fa parte del confronto con la PR #49):

| Gruppo | n | vinte | hit rate |
|---|---|---|---|
| Scelte del mercato CON accordo del modello | 1144 | 780 | 0.6818 |
| Scelte del mercato SENZA accordo | 158 | 99 | 0.6266 |

## 3. Limiti dichiarati

- Le quote sono quelle dei CSV storici (B365 pre-chiusura), NON quelle dal vivo di The Odds API: il piano gratuito non include lo storico, quindi il replay offline non puo' usare la fonte di produzione.
- La colonna 'fonte' del replay vale `pinnacle` per costruzione (un solo libro, B365): la riserva sulla media dei libri non e' esercitabile sui CSV, che hanno una sola terna per fonte. E' coperta dai test unitari, non da questo replay.
- Il campione e' quello della PR #49 (2024/25 + 2025/26 con modello e terna B365 pre): le righe 2026/27 non hanno quote nei CSV e non entrano.
- L'hit rate del replay non ha intervalli bootstrap a blocchi: usa Wilson, che non tiene conto della correlazione fra partite della stessa giornata. Gli IC della PR #49 sono bootstrap a blocchi e sono quindi piu' larghi.
- Il frame e' messo in cache in audit/output/ (non versionato): con --no-cache viene ricostruito da zero (~2-4 minuti).
