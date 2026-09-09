# Ensemble Poisson+Elo: analisi di scopo sulla selezione a 7 mercati

Audit in sola lettura (nessuna modifica a SoccerMath/). Domanda: da d21f5c3 l'1X2 blendato (w=0.6) entra nell'argmax a 7 mercati di analisi_rapida_giornata() e delle card giornata. Quanto cambia il mercato selezionato rispetto al comportamento pre-modifica (Poisson puro, blend presente solo nella confidence del Top Mix)? E il cambio migliora o peggiora la scelta?

- **Regime A (PRE d21f5c3)**: argmax su mercati Poisson puro.
- **Regime B (POST d21f5c3)**: argmax su mercati con 1X2 = 0.6*Poisson + 0.4*Elo; Totali invariati.
- Stessa logica di selezione di produzione (stesso dizionario, stesso ordine).
- Brier di selezione = Brier binario (confidenza del mercato scelto vs esito reale del mercato scelto).
- ROI = puntata piatta 1 unita' alla quota B365 del mercato scelto; copre solo i mercati con quota nel CSV (1X2, O/U 2.5; GG/NG senza quota nei database football-data).

## 1) Campione live (stesso campionamento del test permanente, funzioni di produzione)

Partite campionate: 65 (>= 30) | best_mkt cambiato: **11/65 = 16.9%**

| Lega | Partita | Risultato | PRE (A) | conf A | POST (B) | conf B | scelto da A corretto? | scelto da B corretto? |
|---|---|---|---|---|---|---|---|---|
| Serie A | Udinese-Juventus | 0-3 | Vittoria Juventus | 0.619 | Under 2.5 | 0.549 | si' | no |
| Serie A | Udinese-Verona | 3-3 | Under 2.5 | 0.540 | Vittoria Udinese | 0.560 | no | no |
| Serie A | Lazio-Sassuolo | 2-1 | Under 2.5 | 0.547 | Vittoria Lazio | 0.557 | no | si' |
| Premier League | Brentford-Tottenham | 2-2 | Vittoria Brentford | 0.654 | Over 2.5 | 0.620 | no | si' |
| Premier League | Burnley-Bournemouth | 0-2 | GG | 0.568 | Vittoria Bournemouth | 0.598 | no | si' |
| Premier League | Chelsea-Everton | 2-0 | Vittoria Chelsea | 0.700 | Over 2.5 | 0.671 | si' | no |
| Premier League | Man United-Crystal Palace | 2-1 | Vittoria Man United | 0.731 | Over 2.5 | 0.666 | si' | si' |
| Bundesliga | Wolfsburg-Bochum | 4-0 | Vittoria Wolfsburg | 0.620 | Over 2.5 | 0.614 | si' | si' |
| Bundesliga | Leverkusen-Leipzig | 3-2 | Vittoria Leverkusen | 0.611 | GG | 0.588 | si' | si' |
| Bundesliga | Hamburg-Leverkusen | 0-1 | Vittoria Leverkusen | 0.666 | GG | 0.581 | si' | no |
| Ligue 1 | Nice-Marseille | 1-5 | Vittoria Marseille | 0.533 | GG | 0.527 | si' | si' |

Sui 11 flip con esito disponibile: scelta PRE corretta 7 volte, scelta POST corretta 7 volte.

## 2) Walk-forward storico (stesso harness di diagnose_elo_ensemble.py, cross-check bit-identico)

| Split | Regime | n | Brier sel. | LogLoss sel. | hit rate | conf media | ROI (B365) | n scommesse |
|---|---|---|---|---|---|---|---|---|
| VALIDATION 2024/25 | A (Poisson puro) | 1752 | 0.3097 | 0.8942 | 0.5257 | 0.7615 | -0.0366 | 1416 |
| VALIDATION 2024/25 | B (1X2 blendato) | 1752 | 0.3032 | 0.8563 | 0.5188 | 0.7356 | -0.0636 | 1258 |
| TEST 2025/26 | A (Poisson puro) | 1752 | 0.3006 | 0.8790 | 0.5531 | 0.7656 | 0.0081 | 1363 |
| TEST 2025/26 | B (1X2 blendato) | 1752 | 0.2951 | 0.8488 | 0.5468 | 0.7406 | -0.0140 | 1197 |
| AGGREGATO V+T | A (Poisson puro) | 3504 | 0.3051 | 0.8866 | 0.5394 | 0.7636 | -0.0147 | 2779 |
| AGGREGATO V+T | B (1X2 blendato) | 3504 | 0.2992 | 0.8526 | 0.5328 | 0.7381 | -0.0394 | 2455 |

Delta VALIDATION 2024/25 (B - A): Brier -0.0065 | LogLoss -0.0379 | ROI -0.0270
Delta TEST 2025/26 (B - A): Brier -0.0054 | LogLoss -0.0302 | ROI -0.0221
Delta AGGREGATO V+T (B - A): Brier -0.0060 | LogLoss -0.0341 | ROI -0.0247

## 3) Cambio di mercato selezionato (walk-forward)

Best_mkt cambiato in **793/3504 = 22.6%** delle partite (aggregato V+T).

Transizioni (base market PRE -> POST):

- 1 -> O: 235
- 2 -> O: 186
- 1 -> NG: 166
- 2 -> NG: 160
- 2 -> U: 11
- 1 -> U: 9
- NG -> 1: 8
- 2 -> GG: 5
- 1 -> GG: 4
- O -> 1: 3
- GG -> 1: 3
- U -> 1: 3

Sui soli flip: scelta PRE corretta 419/793 (52.8%), scelta POST corretta 396/793 (49.9%).

Sui soli flip: Brier selezione PRE 0.3288 vs POST 0.3168 (delta -0.0120); ROI PRE 0.0364 (782 scommesse) vs POST -0.0600 (458 scommesse).

## 4) Per lega (aggregato V+T)

| Lega | n | Brier A | Brier B | Δ | flip % | ROI A | ROI B |
|---|---|---|---|---|---|---|---|
| Serie A | 760 | 0.3116 | 0.3235 | +0.0119 | 19.5% | 0.0012 | -0.0329 |
| Premier League | 760 | 0.3129 | 0.2860 | -0.0269 | 27.5% | -0.0283 | -0.0200 |
| La Liga | 760 | 0.2742 | 0.2765 | +0.0023 | 20.4% | 0.0068 | -0.0455 |
| Bundesliga | 612 | 0.3032 | 0.3026 | -0.0006 | 18.8% | -0.0041 | -0.0430 |
| Ligue 1 | 612 | 0.3279 | 0.3102 | -0.0177 | 27.1% | -0.0546 | -0.0592 |

## Nota metodologica

- Il walk-forward e' lo STESSO di audit/results/elo_ensemble_diagnosis.md (verificato bit-a-bit su p1/pX/p2/e1/eX/e2/y per tutte le leghe).
- Il Brier di selezione misura insieme qualita' della scelta e calibrazione della confidenza sul mercato scelto; l'audit elo_ensemble misura la probabilita' 1X2 completa (3 esiti). I due numeri NON sono direttamente confrontabili in valore assoluto.
- Rumore: SE del Brier binario con n~3500 e' ~0.007; delta sotto questa soglia vanno letti come 'entro il rumore'.

