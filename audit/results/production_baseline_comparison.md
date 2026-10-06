# Baseline di Produzione vs Baseline Audit (solo-gol)

Walk-forward no-leakage (ogni partita usa solo i dati precedenti). Season: VALIDATION 2024/25 e TEST 2025/26. Modelli: AUDIT solo-gol | AUDIT+CLIP (lambda clip [exp(-6),exp(3)]) | PRODUZIONE ATTUALE (xG stagionale primario + forma ult.5 [0.85,1.15] + valore di mercato [0.85,1.25] + clip lambda) | PRODUZIONE_NORM_SUM (somma attesa normalizzata senza mercato) | PROD_DC / PROD_NORM_DC (come i due precedenti ma con correzione Dixon-Coles tau(x,y,rho) sulle 4 celle basse e rinormalizzazione; rho stimato via MLE solo su training 2022/23+2023/24 per lega) | PRODUZIONE_DUE_TESTE (1X2 da NORM_SUM, O/U2.5 e GG/NG da lambda base senza mercato M=1) e PRODUZIONE_DUE_TESTE_DC (idem + Dixon-Coles solo sulla testa Totali).

xG di produzione: snapshot stagionale statico da xg_<lega>.json (stesso file letto da get_league_engine); applicato costante alle partite, come fa il motore di produzione a un dato istante.

Nota metodologica: lo snapshot xG disponibile riflette la squadra ATTUALE. Applicandolo costante alle partite 2024/25 e 2025/26 si introduce un'informazione sui punti di forza delle rose odierne applicata a stagioni passate: i numeri di PRODUZIONE su queste stagioni vanno quindi letti come fedeli alla *struttura* del motore, ma l'eventuale edge/ROI in validation non va interpretato come edge out-of-sample reale.


## SERIE A  (VAL 380 + TEST 380 partite)

### Brier / LogLoss  (V=2024/25, T=2025/26)

| Modello | Mercato | Brier V | LogLoss V | Brier T | LogLoss T |
|---|---|---|---|---|---|
| AUDIT solo-gol | 1X2 | 0.5842 | 0.9795 | 0.5927 | 0.9921 |
| AUDIT solo-gol | O/U2.5 | 0.2515 | 0.6968 | 0.2553 | 0.7043 |
| AUDIT solo-gol | GG/NG | 0.2528 | 0.6988 | 0.2489 | 0.6913 |
| AUDIT + CLIP | 1X2 | 0.5842 | 0.9795 | 0.5927 | 0.9921 |
| AUDIT + CLIP | O/U2.5 | 0.2515 | 0.6968 | 0.2553 | 0.7043 |
| AUDIT + CLIP | GG/NG | 0.2528 | 0.6988 | 0.2489 | 0.6913 |
| PRODUZIONE ATTUALE | 1X2 | 0.6388 | 1.0678 | 0.6130 | 1.0548 |
| PRODUZIONE ATTUALE | O/U2.5 | 0.2820 | 0.7823 | 0.2967 | 0.8393 |
| PRODUZIONE ATTUALE | GG/NG | 0.2847 | 0.7777 | 0.2818 | 0.8217 |
| PRODUZIONE_NORM_SUM | 1X2 | 0.6352 | 1.0605 | 0.6100 | 1.0467 |
| PRODUZIONE_NORM_SUM | O/U2.5 | 0.2818 | 0.7745 | 0.2945 | 0.8327 |
| PRODUZIONE_NORM_SUM | GG/NG | 0.2871 | 0.7865 | 0.2838 | 0.8337 |
| PROD_DC | 1X2 | 0.6383 | 1.0679 | 0.6130 | 1.0556 |
| PROD_DC | O/U2.5 | 0.2820 | 0.7822 | 0.2967 | 0.8392 |
| PROD_DC | GG/NG | 0.2843 | 0.7764 | 0.2815 | 0.8206 |
| PROD_NORM_DC | 1X2 | 0.6347 | 1.0608 | 0.6100 | 1.0477 |
| PROD_NORM_DC | O/U2.5 | 0.2818 | 0.7745 | 0.2945 | 0.8326 |
| PROD_NORM_DC | GG/NG | 0.2866 | 0.7851 | 0.2834 | 0.8324 |
| PRODUZIONE_DUE_TESTE | 1X2 | 0.6352 | 1.0605 | 0.6100 | 1.0467 |
| PRODUZIONE_DUE_TESTE | O/U2.5 | 0.2818 | 0.7745 | 0.2945 | 0.8327 |
| PRODUZIONE_DUE_TESTE | GG/NG | 0.2846 | 0.7755 | 0.2816 | 0.8194 |
| PRODUZIONE_DUE_TESTE_DC | 1X2 | 0.6352 | 1.0605 | 0.6100 | 1.0467 |
| PRODUZIONE_DUE_TESTE_DC | O/U2.5 | 0.2818 | 0.7745 | 0.2945 | 0.8326 |
| PRODUZIONE_DUE_TESTE_DC | GG/NG | 0.2841 | 0.7743 | 0.2812 | 0.8182 |

### ROI % / Win rate % (edge>0)  (V=2024/25, T=2025/26)

| Modello | Mercato | Quota | N V | WR V | ROI V | N T | WR T | ROI T |
|---|---|---|---|---|---|---|---|---|
| AUDIT solo-gol | 1X2 | B365 | 326 | 30.7 | -16.52 | 336 | 31.8 | -8.66 |
| AUDIT solo-gol | 1X2 | Avg | 333 | 31.2 | -17.19 | 320 | 33.1 | -4.79 |
| AUDIT solo-gol | O/U2.5 | B365 | 290 | 47.6 | -13.11 | 264 | 47.7 | -4.59 |
| AUDIT solo-gol | O/U2.5 | Avg | 276 | 49.3 | -10.12 | 243 | 47.3 | -7.37 |
| AUDIT + CLIP | 1X2 | B365 | 326 | 30.7 | -16.52 | 336 | 31.8 | -8.66 |
| AUDIT + CLIP | 1X2 | Avg | 333 | 31.2 | -17.19 | 320 | 33.1 | -4.79 |
| AUDIT + CLIP | O/U2.5 | B365 | 290 | 47.6 | -13.11 | 264 | 47.7 | -4.59 |
| AUDIT + CLIP | O/U2.5 | Avg | 276 | 49.3 | -10.12 | 243 | 47.3 | -7.37 |
| PRODUZIONE ATTUALE | 1X2 | B365 | 375 | 41.3 | -7.10 | 360 | 47.8 | 7.12 |
| PRODUZIONE ATTUALE | 1X2 | Avg | 374 | 42.2 | -5.05 | 358 | 48.3 | 8.22 |
| PRODUZIONE ATTUALE | O/U2.5 | B365 | 359 | 50.1 | -6.47 | 345 | 50.7 | -4.87 |
| PRODUZIONE ATTUALE | O/U2.5 | Avg | 355 | 49.9 | -7.46 | 336 | 50.9 | -6.28 |
| PRODUZIONE_NORM_SUM | 1X2 | B365 | 371 | 40.2 | -8.63 | 359 | 47.6 | 9.94 |
| PRODUZIONE_NORM_SUM | 1X2 | Avg | 369 | 40.4 | -8.03 | 356 | 47.8 | 8.83 |
| PRODUZIONE_NORM_SUM | O/U2.5 | B365 | 357 | 48.7 | -9.11 | 340 | 52.4 | -1.79 |
| PRODUZIONE_NORM_SUM | O/U2.5 | Avg | 356 | 48.3 | -10.04 | 334 | 52.1 | -3.63 |
| PROD_DC | 1X2 | B365 | 374 | 41.2 | -7.18 | 361 | 48.2 | 8.69 |
| PROD_DC | 1X2 | Avg | 373 | 42.1 | -5.11 | 357 | 48.7 | 9.40 |
| PROD_DC | O/U2.5 | B365 | 359 | 50.1 | -6.47 | 345 | 50.7 | -4.87 |
| PROD_DC | O/U2.5 | Avg | 355 | 49.9 | -7.46 | 336 | 50.9 | -6.28 |
| PROD_NORM_DC | 1X2 | B365 | 371 | 40.2 | -8.63 | 361 | 47.4 | 10.18 |
| PROD_NORM_DC | 1X2 | Avg | 371 | 40.7 | -6.28 | 357 | 47.9 | 9.66 |
| PROD_NORM_DC | O/U2.5 | B365 | 357 | 48.7 | -9.11 | 340 | 52.4 | -1.79 |
| PROD_NORM_DC | O/U2.5 | Avg | 356 | 48.3 | -10.04 | 334 | 52.1 | -3.63 |
| PRODUZIONE_DUE_TESTE | 1X2 | B365 | 371 | 40.2 | -8.63 | 359 | 47.6 | 9.94 |
| PRODUZIONE_DUE_TESTE | 1X2 | Avg | 369 | 40.4 | -8.03 | 356 | 47.8 | 8.83 |
| PRODUZIONE_DUE_TESTE | O/U2.5 | B365 | 357 | 48.7 | -9.11 | 340 | 52.4 | -1.79 |
| PRODUZIONE_DUE_TESTE | O/U2.5 | Avg | 356 | 48.3 | -10.04 | 334 | 52.1 | -3.63 |
| PRODUZIONE_DUE_TESTE_DC | 1X2 | B365 | 371 | 40.2 | -8.63 | 359 | 47.6 | 9.94 |
| PRODUZIONE_DUE_TESTE_DC | 1X2 | Avg | 369 | 40.4 | -8.03 | 356 | 47.8 | 8.83 |
| PRODUZIONE_DUE_TESTE_DC | O/U2.5 | B365 | 357 | 48.7 | -9.11 | 340 | 52.4 | -1.79 |
| PRODUZIONE_DUE_TESTE_DC | O/U2.5 | Avg | 356 | 48.3 | -10.04 | 334 | 52.1 | -3.63 |


## PREMIER LEAGUE  (VAL 380 + TEST 380 partite)

### Brier / LogLoss  (V=2024/25, T=2025/26)

| Modello | Mercato | Brier V | LogLoss V | Brier T | LogLoss T |
|---|---|---|---|---|---|
| AUDIT solo-gol | 1X2 | 0.5965 | 0.9961 | 0.6200 | 1.0316 |
| AUDIT solo-gol | O/U2.5 | 0.2420 | 0.6772 | 0.2487 | 0.6913 |
| AUDIT solo-gol | GG/NG | 0.2472 | 0.6877 | 0.2461 | 0.6854 |
| AUDIT + CLIP | 1X2 | 0.5965 | 0.9961 | 0.6200 | 1.0316 |
| AUDIT + CLIP | O/U2.5 | 0.2420 | 0.6772 | 0.2487 | 0.6913 |
| AUDIT + CLIP | GG/NG | 0.2472 | 0.6877 | 0.2461 | 0.6854 |
| PRODUZIONE ATTUALE | 1X2 | 0.6157 | 1.0385 | 0.6457 | 1.0727 |
| PRODUZIONE ATTUALE | O/U2.5 | 0.2568 | 0.7118 | 0.2737 | 0.7492 |
| PRODUZIONE ATTUALE | GG/NG | 0.2519 | 0.6978 | 0.2636 | 0.7217 |
| PRODUZIONE_NORM_SUM | 1X2 | 0.6158 | 1.0377 | 0.6451 | 1.0711 |
| PRODUZIONE_NORM_SUM | O/U2.5 | 0.2562 | 0.7085 | 0.2728 | 0.7457 |
| PRODUZIONE_NORM_SUM | GG/NG | 0.2528 | 0.6999 | 0.2643 | 0.7232 |
| PROD_DC | 1X2 | 0.6157 | 1.0385 | 0.6456 | 1.0727 |
| PROD_DC | O/U2.5 | 0.2568 | 0.7118 | 0.2737 | 0.7492 |
| PROD_DC | GG/NG | 0.2519 | 0.6977 | 0.2636 | 0.7217 |
| PROD_NORM_DC | 1X2 | 0.6157 | 1.0377 | 0.6451 | 1.0711 |
| PROD_NORM_DC | O/U2.5 | 0.2562 | 0.7085 | 0.2728 | 0.7457 |
| PROD_NORM_DC | GG/NG | 0.2528 | 0.6999 | 0.2643 | 0.7232 |
| PRODUZIONE_DUE_TESTE | 1X2 | 0.6158 | 1.0377 | 0.6451 | 1.0711 |
| PRODUZIONE_DUE_TESTE | O/U2.5 | 0.2562 | 0.7085 | 0.2728 | 0.7457 |
| PRODUZIONE_DUE_TESTE | GG/NG | 0.2514 | 0.6967 | 0.2635 | 0.7218 |
| PRODUZIONE_DUE_TESTE_DC | 1X2 | 0.6158 | 1.0377 | 0.6451 | 1.0711 |
| PRODUZIONE_DUE_TESTE_DC | O/U2.5 | 0.2562 | 0.7085 | 0.2728 | 0.7457 |
| PRODUZIONE_DUE_TESTE_DC | GG/NG | 0.2514 | 0.6967 | 0.2635 | 0.7217 |

### ROI % / Win rate % (edge>0)  (V=2024/25, T=2025/26)

| Modello | Mercato | Quota | N V | WR V | ROI V | N T | WR T | ROI T |
|---|---|---|---|---|---|---|---|---|
| AUDIT solo-gol | 1X2 | B365 | 327 | 34.9 | -5.35 | 337 | 30.3 | -16.74 |
| AUDIT solo-gol | 1X2 | Avg | 336 | 34.5 | -10.15 | 335 | 29.9 | -19.61 |
| AUDIT solo-gol | O/U2.5 | B365 | 266 | 47.4 | 2.92 | 274 | 52.9 | 3.04 |
| AUDIT solo-gol | O/U2.5 | Avg | 261 | 46.7 | 2.39 | 252 | 51.2 | -2.44 |
| AUDIT + CLIP | 1X2 | B365 | 327 | 34.9 | -5.35 | 337 | 30.3 | -16.74 |
| AUDIT + CLIP | 1X2 | Avg | 336 | 34.5 | -10.15 | 335 | 29.9 | -19.61 |
| AUDIT + CLIP | O/U2.5 | B365 | 266 | 47.4 | 2.92 | 274 | 52.9 | 3.04 |
| AUDIT + CLIP | O/U2.5 | Avg | 261 | 46.7 | 2.39 | 252 | 51.2 | -2.44 |
| PRODUZIONE ATTUALE | 1X2 | B365 | 362 | 40.3 | 1.46 | 357 | 43.4 | 13.36 |
| PRODUZIONE ATTUALE | 1X2 | Avg | 365 | 39.2 | -4.65 | 358 | 41.6 | 6.80 |
| PRODUZIONE ATTUALE | O/U2.5 | B365 | 319 | 48.6 | -4.82 | 337 | 48.4 | -7.78 |
| PRODUZIONE ATTUALE | O/U2.5 | Avg | 316 | 49.1 | -4.05 | 312 | 47.8 | -9.89 |
| PRODUZIONE_NORM_SUM | 1X2 | B365 | 362 | 39.0 | -2.54 | 359 | 43.5 | 15.08 |
| PRODUZIONE_NORM_SUM | 1X2 | Avg | 368 | 38.3 | -6.41 | 357 | 41.2 | 8.15 |
| PRODUZIONE_NORM_SUM | O/U2.5 | B365 | 314 | 47.5 | -3.93 | 331 | 46.5 | -10.18 |
| PRODUZIONE_NORM_SUM | O/U2.5 | Avg | 315 | 47.3 | -4.16 | 311 | 46.3 | -11.64 |
| PROD_DC | 1X2 | B365 | 362 | 40.1 | -1.03 | 357 | 43.4 | 13.36 |
| PROD_DC | 1X2 | Avg | 365 | 39.2 | -4.65 | 358 | 41.9 | 7.95 |
| PROD_DC | O/U2.5 | B365 | 319 | 48.6 | -4.82 | 337 | 48.4 | -7.78 |
| PROD_DC | O/U2.5 | Avg | 316 | 49.1 | -4.05 | 312 | 47.8 | -9.89 |
| PROD_NORM_DC | 1X2 | B365 | 362 | 39.0 | -2.54 | 359 | 43.5 | 15.08 |
| PROD_NORM_DC | 1X2 | Avg | 368 | 38.3 | -6.41 | 357 | 41.5 | 9.31 |
| PROD_NORM_DC | O/U2.5 | B365 | 314 | 47.5 | -3.93 | 331 | 46.5 | -10.18 |
| PROD_NORM_DC | O/U2.5 | Avg | 315 | 47.3 | -4.16 | 311 | 46.3 | -11.64 |
| PRODUZIONE_DUE_TESTE | 1X2 | B365 | 362 | 39.0 | -2.54 | 359 | 43.5 | 15.08 |
| PRODUZIONE_DUE_TESTE | 1X2 | Avg | 368 | 38.3 | -6.41 | 357 | 41.2 | 8.15 |
| PRODUZIONE_DUE_TESTE | O/U2.5 | B365 | 314 | 47.5 | -3.93 | 331 | 46.5 | -10.18 |
| PRODUZIONE_DUE_TESTE | O/U2.5 | Avg | 315 | 47.3 | -4.16 | 311 | 46.3 | -11.64 |
| PRODUZIONE_DUE_TESTE_DC | 1X2 | B365 | 362 | 39.0 | -2.54 | 359 | 43.5 | 15.08 |
| PRODUZIONE_DUE_TESTE_DC | 1X2 | Avg | 368 | 38.3 | -6.41 | 357 | 41.2 | 8.15 |
| PRODUZIONE_DUE_TESTE_DC | O/U2.5 | B365 | 314 | 47.5 | -3.93 | 331 | 46.5 | -10.18 |
| PRODUZIONE_DUE_TESTE_DC | O/U2.5 | Avg | 315 | 47.3 | -4.16 | 311 | 46.3 | -11.64 |


## LA LIGA  (VAL 380 + TEST 380 partite)

### Brier / LogLoss  (V=2024/25, T=2025/26)

| Modello | Mercato | Brier V | LogLoss V | Brier T | LogLoss T |
|---|---|---|---|---|---|
| AUDIT solo-gol | 1X2 | 0.5766 | 0.9727 | 0.5866 | 1.0527 |
| AUDIT solo-gol | O/U2.5 | 0.2451 | 0.6831 | 0.2510 | 0.6953 |
| AUDIT solo-gol | GG/NG | 0.2546 | 0.7030 | 0.2541 | 0.7022 |
| AUDIT + CLIP | 1X2 | 0.5766 | 0.9727 | 0.5866 | 1.0013 |
| AUDIT + CLIP | O/U2.5 | 0.2451 | 0.6831 | 0.2511 | 0.6953 |
| AUDIT + CLIP | GG/NG | 0.2546 | 0.7030 | 0.2541 | 0.7022 |
| PRODUZIONE ATTUALE | 1X2 | 0.5977 | 1.0320 | 0.6206 | 1.0726 |
| PRODUZIONE ATTUALE | O/U2.5 | 0.2604 | 0.7380 | 0.2649 | 0.7338 |
| PRODUZIONE ATTUALE | GG/NG | 0.2857 | 0.7739 | 0.2753 | 0.7508 |
| PRODUZIONE_NORM_SUM | 1X2 | 0.5961 | 1.0210 | 0.6172 | 1.0629 |
| PRODUZIONE_NORM_SUM | O/U2.5 | 0.2590 | 0.7271 | 0.2599 | 0.7218 |
| PRODUZIONE_NORM_SUM | GG/NG | 0.2906 | 0.7862 | 0.2800 | 0.7621 |
| PROD_DC | 1X2 | 0.5978 | 1.0324 | 0.6204 | 1.0736 |
| PROD_DC | O/U2.5 | 0.2604 | 0.7380 | 0.2649 | 0.7338 |
| PROD_DC | GG/NG | 0.2850 | 0.7721 | 0.2746 | 0.7490 |
| PROD_NORM_DC | 1X2 | 0.5961 | 1.0216 | 0.6171 | 1.0642 |
| PROD_NORM_DC | O/U2.5 | 0.2590 | 0.7271 | 0.2599 | 0.7218 |
| PROD_NORM_DC | GG/NG | 0.2899 | 0.7842 | 0.2792 | 0.7602 |
| PRODUZIONE_DUE_TESTE | 1X2 | 0.5961 | 1.0210 | 0.6172 | 1.0629 |
| PRODUZIONE_DUE_TESTE | O/U2.5 | 0.2590 | 0.7271 | 0.2599 | 0.7218 |
| PRODUZIONE_DUE_TESTE | GG/NG | 0.2824 | 0.7661 | 0.2715 | 0.7425 |
| PRODUZIONE_DUE_TESTE_DC | 1X2 | 0.5961 | 1.0210 | 0.6172 | 1.0629 |
| PRODUZIONE_DUE_TESTE_DC | O/U2.5 | 0.2590 | 0.7271 | 0.2599 | 0.7218 |
| PRODUZIONE_DUE_TESTE_DC | GG/NG | 0.2817 | 0.7644 | 0.2708 | 0.7407 |

### ROI % / Win rate % (edge>0)  (V=2024/25, T=2025/26)

| Modello | Mercato | Quota | N V | WR V | ROI V | N T | WR T | ROI T |
|---|---|---|---|---|---|---|---|---|
| AUDIT solo-gol | 1X2 | B365 | 312 | 33.3 | -5.68 | 326 | 31.6 | -19.58 |
| AUDIT solo-gol | 1X2 | Avg | 325 | 32.0 | -12.48 | 297 | 32.3 | -21.01 |
| AUDIT solo-gol | O/U2.5 | B365 | 286 | 44.4 | -11.69 | 294 | 48.3 | -0.59 |
| AUDIT solo-gol | O/U2.5 | Avg | 276 | 43.8 | -13.27 | 253 | 45.5 | -8.97 |
| AUDIT + CLIP | 1X2 | B365 | 312 | 33.3 | -5.68 | 326 | 31.6 | -19.58 |
| AUDIT + CLIP | 1X2 | Avg | 325 | 32.0 | -12.48 | 297 | 32.3 | -21.01 |
| AUDIT + CLIP | O/U2.5 | B365 | 286 | 44.4 | -11.69 | 294 | 48.3 | -0.59 |
| AUDIT + CLIP | O/U2.5 | Avg | 276 | 43.8 | -13.27 | 253 | 45.5 | -8.97 |
| PRODUZIONE ATTUALE | 1X2 | B365 | 368 | 45.7 | 2.35 | 370 | 43.0 | -12.03 |
| PRODUZIONE ATTUALE | 1X2 | Avg | 373 | 45.6 | 2.73 | 369 | 43.4 | -11.85 |
| PRODUZIONE ATTUALE | O/U2.5 | B365 | 342 | 56.4 | -4.58 | 341 | 54.0 | -6.75 |
| PRODUZIONE ATTUALE | O/U2.5 | Avg | 346 | 56.1 | -4.73 | 327 | 53.8 | -9.27 |
| PRODUZIONE_NORM_SUM | 1X2 | B365 | 370 | 44.9 | 1.94 | 367 | 42.2 | -12.14 |
| PRODUZIONE_NORM_SUM | 1X2 | Avg | 373 | 44.8 | 2.08 | 367 | 42.2 | -13.49 |
| PRODUZIONE_NORM_SUM | O/U2.5 | B365 | 337 | 56.4 | -3.48 | 342 | 54.4 | -4.35 |
| PRODUZIONE_NORM_SUM | O/U2.5 | Avg | 335 | 56.7 | -2.80 | 325 | 55.4 | -4.90 |
| PROD_DC | 1X2 | B365 | 373 | 45.3 | 1.20 | 368 | 42.9 | -11.54 |
| PROD_DC | 1X2 | Avg | 373 | 45.6 | 3.28 | 369 | 42.8 | -13.64 |
| PROD_DC | O/U2.5 | B365 | 342 | 56.4 | -4.58 | 341 | 54.0 | -6.75 |
| PROD_DC | O/U2.5 | Avg | 346 | 56.1 | -4.73 | 327 | 53.8 | -9.27 |
| PROD_NORM_DC | 1X2 | B365 | 373 | 44.5 | 1.19 | 365 | 42.5 | -11.30 |
| PROD_NORM_DC | 1X2 | Avg | 374 | 44.1 | 1.81 | 367 | 41.7 | -15.01 |
| PROD_NORM_DC | O/U2.5 | B365 | 337 | 56.4 | -3.48 | 342 | 54.4 | -4.35 |
| PROD_NORM_DC | O/U2.5 | Avg | 335 | 56.7 | -2.80 | 325 | 55.4 | -4.90 |
| PRODUZIONE_DUE_TESTE | 1X2 | B365 | 370 | 44.9 | 1.94 | 367 | 42.2 | -12.14 |
| PRODUZIONE_DUE_TESTE | 1X2 | Avg | 373 | 44.8 | 2.08 | 367 | 42.2 | -13.49 |
| PRODUZIONE_DUE_TESTE | O/U2.5 | B365 | 337 | 56.4 | -3.48 | 342 | 54.4 | -4.35 |
| PRODUZIONE_DUE_TESTE | O/U2.5 | Avg | 335 | 56.7 | -2.80 | 325 | 55.4 | -4.90 |
| PRODUZIONE_DUE_TESTE_DC | 1X2 | B365 | 370 | 44.9 | 1.94 | 367 | 42.2 | -12.14 |
| PRODUZIONE_DUE_TESTE_DC | 1X2 | Avg | 373 | 44.8 | 2.08 | 367 | 42.2 | -13.49 |
| PRODUZIONE_DUE_TESTE_DC | O/U2.5 | B365 | 337 | 56.4 | -3.48 | 342 | 54.4 | -4.35 |
| PRODUZIONE_DUE_TESTE_DC | O/U2.5 | Avg | 335 | 56.7 | -2.80 | 325 | 55.4 | -4.90 |


## BUNDESLIGA  (VAL 306 + TEST 306 partite)

### Brier / LogLoss  (V=2024/25, T=2025/26)

| Modello | Mercato | Brier V | LogLoss V | Brier T | LogLoss T |
|---|---|---|---|---|---|
| AUDIT solo-gol | 1X2 | 0.6137 | 1.0279 | 0.5779 | 1.0583 |
| AUDIT solo-gol | O/U2.5 | 0.2282 | 0.6479 | 0.2372 | 0.6659 |
| AUDIT solo-gol | GG/NG | 0.2374 | 0.7500 | 0.2498 | 0.7751 |
| AUDIT + CLIP | 1X2 | 0.6137 | 1.0279 | 0.5778 | 0.9928 |
| AUDIT + CLIP | O/U2.5 | 0.2282 | 0.6479 | 0.2372 | 0.6659 |
| AUDIT + CLIP | GG/NG | 0.2373 | 0.6800 | 0.2497 | 0.7051 |
| PRODUZIONE ATTUALE | 1X2 | 0.6597 | 1.2173 | 0.6248 | 1.0960 |
| PRODUZIONE ATTUALE | O/U2.5 | 0.2584 | 0.7489 | 0.2537 | 0.7123 |
| PRODUZIONE ATTUALE | GG/NG | 0.2717 | 0.7927 | 0.2742 | 0.7506 |
| PRODUZIONE_NORM_SUM | 1X2 | 0.6558 | 1.1907 | 0.6221 | 1.0811 |
| PRODUZIONE_NORM_SUM | O/U2.5 | 0.2580 | 0.7396 | 0.2574 | 0.7181 |
| PRODUZIONE_NORM_SUM | GG/NG | 0.2772 | 0.8079 | 0.2801 | 0.7666 |
| PROD_DC | 1X2 | 0.6592 | 1.2196 | 0.6236 | 1.0978 |
| PROD_DC | O/U2.5 | 0.2584 | 0.7489 | 0.2537 | 0.7123 |
| PROD_DC | GG/NG | 0.2705 | 0.7897 | 0.2721 | 0.7458 |
| PROD_NORM_DC | 1X2 | 0.6544 | 1.1944 | 0.6210 | 1.0838 |
| PROD_NORM_DC | O/U2.5 | 0.2580 | 0.7396 | 0.2574 | 0.7181 |
| PROD_NORM_DC | GG/NG | 0.2757 | 0.8042 | 0.2778 | 0.7611 |
| PRODUZIONE_DUE_TESTE | 1X2 | 0.6558 | 1.1907 | 0.6221 | 1.0811 |
| PRODUZIONE_DUE_TESTE | O/U2.5 | 0.2580 | 0.7396 | 0.2574 | 0.7181 |
| PRODUZIONE_DUE_TESTE | GG/NG | 0.2671 | 0.7813 | 0.2694 | 0.7388 |
| PRODUZIONE_DUE_TESTE_DC | 1X2 | 0.6558 | 1.1907 | 0.6221 | 1.0811 |
| PRODUZIONE_DUE_TESTE_DC | O/U2.5 | 0.2580 | 0.7396 | 0.2574 | 0.7181 |
| PRODUZIONE_DUE_TESTE_DC | GG/NG | 0.2658 | 0.7781 | 0.2672 | 0.7338 |

### ROI % / Win rate % (edge>0)  (V=2024/25, T=2025/26)

| Modello | Mercato | Quota | N V | WR V | ROI V | N T | WR T | ROI T |
|---|---|---|---|---|---|---|---|---|
| AUDIT solo-gol | 1X2 | B365 | 269 | 27.1 | -31.46 | 253 | 34.4 | -9.57 |
| AUDIT solo-gol | 1X2 | Avg | 276 | 28.3 | -31.30 | 228 | 35.5 | -9.10 |
| AUDIT solo-gol | O/U2.5 | B365 | 216 | 54.2 | -0.61 | 195 | 41.0 | -17.64 |
| AUDIT solo-gol | O/U2.5 | Avg | 209 | 56.5 | 2.52 | 168 | 39.9 | -20.54 |
| AUDIT + CLIP | 1X2 | B365 | 269 | 27.1 | -31.46 | 253 | 34.4 | -9.57 |
| AUDIT + CLIP | 1X2 | Avg | 276 | 28.3 | -31.30 | 228 | 35.5 | -9.10 |
| AUDIT + CLIP | O/U2.5 | B365 | 216 | 54.2 | -0.61 | 195 | 41.0 | -17.64 |
| AUDIT + CLIP | O/U2.5 | Avg | 209 | 56.5 | 2.52 | 168 | 39.9 | -20.54 |
| PRODUZIONE ATTUALE | 1X2 | B365 | 299 | 49.2 | 5.30 | 300 | 49.7 | 3.29 |
| PRODUZIONE ATTUALE | 1X2 | Avg | 301 | 48.8 | 5.20 | 300 | 50.3 | 4.42 |
| PRODUZIONE ATTUALE | O/U2.5 | B365 | 270 | 53.3 | -5.27 | 283 | 53.4 | -3.48 |
| PRODUZIONE ATTUALE | O/U2.5 | Avg | 273 | 53.5 | -4.49 | 274 | 53.3 | -5.07 |
| PRODUZIONE_NORM_SUM | 1X2 | B365 | 303 | 48.8 | 4.25 | 301 | 49.2 | 5.01 |
| PRODUZIONE_NORM_SUM | 1X2 | Avg | 304 | 48.7 | 4.50 | 300 | 49.7 | 2.96 |
| PRODUZIONE_NORM_SUM | O/U2.5 | B365 | 277 | 50.5 | -7.04 | 278 | 52.2 | -3.95 |
| PRODUZIONE_NORM_SUM | O/U2.5 | Avg | 274 | 49.3 | -8.79 | 272 | 51.8 | -5.67 |
| PROD_DC | 1X2 | B365 | 300 | 48.3 | 3.45 | 300 | 48.0 | 0.62 |
| PROD_DC | 1X2 | Avg | 301 | 48.5 | 5.60 | 299 | 48.5 | 0.47 |
| PROD_DC | O/U2.5 | B365 | 270 | 53.3 | -5.27 | 283 | 53.4 | -3.48 |
| PROD_DC | O/U2.5 | Avg | 273 | 53.5 | -4.49 | 274 | 53.3 | -5.07 |
| PROD_NORM_DC | 1X2 | B365 | 300 | 48.0 | 2.87 | 301 | 47.5 | 3.70 |
| PROD_NORM_DC | 1X2 | Avg | 301 | 48.5 | 7.27 | 299 | 48.5 | 5.00 |
| PROD_NORM_DC | O/U2.5 | B365 | 277 | 50.5 | -7.04 | 278 | 52.2 | -3.95 |
| PROD_NORM_DC | O/U2.5 | Avg | 274 | 49.3 | -8.79 | 272 | 51.8 | -5.67 |
| PRODUZIONE_DUE_TESTE | 1X2 | B365 | 303 | 48.8 | 4.25 | 301 | 49.2 | 5.01 |
| PRODUZIONE_DUE_TESTE | 1X2 | Avg | 304 | 48.7 | 4.50 | 300 | 49.7 | 2.96 |
| PRODUZIONE_DUE_TESTE | O/U2.5 | B365 | 277 | 50.5 | -7.04 | 278 | 52.2 | -3.95 |
| PRODUZIONE_DUE_TESTE | O/U2.5 | Avg | 274 | 49.3 | -8.79 | 272 | 51.8 | -5.67 |
| PRODUZIONE_DUE_TESTE_DC | 1X2 | B365 | 303 | 48.8 | 4.25 | 301 | 49.2 | 5.01 |
| PRODUZIONE_DUE_TESTE_DC | 1X2 | Avg | 304 | 48.7 | 4.50 | 300 | 49.7 | 2.96 |
| PRODUZIONE_DUE_TESTE_DC | O/U2.5 | B365 | 277 | 50.5 | -7.04 | 278 | 52.2 | -3.95 |
| PRODUZIONE_DUE_TESTE_DC | O/U2.5 | Avg | 274 | 49.3 | -8.79 | 272 | 51.8 | -5.67 |


## LIGUE 1  (VAL 306 + TEST 306 partite)

### Brier / LogLoss  (V=2024/25, T=2025/26)

| Modello | Mercato | Brier V | LogLoss V | Brier T | LogLoss T |
|---|---|---|---|---|---|
| AUDIT solo-gol | 1X2 | 0.5881 | 1.0696 | 0.5984 | 0.9989 |
| AUDIT solo-gol | O/U2.5 | 0.2479 | 0.6893 | 0.2483 | 0.6904 |
| AUDIT solo-gol | GG/NG | 0.2497 | 0.6917 | 0.2505 | 0.6945 |
| AUDIT + CLIP | 1X2 | 0.5881 | 1.0068 | 0.5984 | 0.9989 |
| AUDIT + CLIP | O/U2.5 | 0.2479 | 0.6893 | 0.2483 | 0.6904 |
| AUDIT + CLIP | GG/NG | 0.2497 | 0.6917 | 0.2505 | 0.6945 |
| PRODUZIONE ATTUALE | 1X2 | 0.6285 | 1.0704 | 0.6258 | 1.0440 |
| PRODUZIONE ATTUALE | O/U2.5 | 0.2682 | 0.7340 | 0.2715 | 0.7455 |
| PRODUZIONE ATTUALE | GG/NG | 0.2726 | 0.7393 | 0.2732 | 0.7444 |
| PRODUZIONE_NORM_SUM | 1X2 | 0.6271 | 1.0649 | 0.6256 | 1.0432 |
| PRODUZIONE_NORM_SUM | O/U2.5 | 0.2690 | 0.7356 | 0.2706 | 0.7424 |
| PRODUZIONE_NORM_SUM | GG/NG | 0.2762 | 0.7470 | 0.2731 | 0.7442 |
| PROD_DC | 1X2 | 0.6294 | 1.0741 | 0.6253 | 1.0452 |
| PROD_DC | O/U2.5 | 0.2682 | 0.7340 | 0.2715 | 0.7455 |
| PROD_DC | GG/NG | 0.2720 | 0.7379 | 0.2725 | 0.7426 |
| PROD_NORM_DC | 1X2 | 0.6282 | 1.0689 | 0.6252 | 1.0445 |
| PROD_NORM_DC | O/U2.5 | 0.2690 | 0.7356 | 0.2706 | 0.7424 |
| PROD_NORM_DC | GG/NG | 0.2754 | 0.7453 | 0.2723 | 0.7424 |
| PRODUZIONE_DUE_TESTE | 1X2 | 0.6271 | 1.0649 | 0.6256 | 1.0432 |
| PRODUZIONE_DUE_TESTE | O/U2.5 | 0.2690 | 0.7356 | 0.2706 | 0.7424 |
| PRODUZIONE_DUE_TESTE | GG/NG | 0.2701 | 0.7341 | 0.2743 | 0.7467 |
| PRODUZIONE_DUE_TESTE_DC | 1X2 | 0.6271 | 1.0649 | 0.6256 | 1.0432 |
| PRODUZIONE_DUE_TESTE_DC | O/U2.5 | 0.2690 | 0.7356 | 0.2706 | 0.7424 |
| PRODUZIONE_DUE_TESTE_DC | GG/NG | 0.2694 | 0.7328 | 0.2736 | 0.7452 |

### ROI % / Win rate % (edge>0)  (V=2024/25, T=2025/26)

| Modello | Mercato | Quota | N V | WR V | ROI V | N T | WR T | ROI T |
|---|---|---|---|---|---|---|---|---|
| AUDIT solo-gol | 1X2 | B365 | 259 | 33.6 | -10.20 | 255 | 29.8 | -10.51 |
| AUDIT solo-gol | 1X2 | Avg | 268 | 35.1 | -6.82 | 232 | 31.5 | -4.37 |
| AUDIT solo-gol | O/U2.5 | B365 | 220 | 45.5 | -10.96 | 193 | 41.5 | -17.20 |
| AUDIT solo-gol | O/U2.5 | Avg | 209 | 45.5 | -9.79 | 161 | 41.0 | -19.29 |
| AUDIT + CLIP | 1X2 | B365 | 259 | 33.6 | -10.20 | 255 | 29.8 | -10.51 |
| AUDIT + CLIP | 1X2 | Avg | 268 | 35.1 | -6.82 | 232 | 31.5 | -4.37 |
| AUDIT + CLIP | O/U2.5 | B365 | 220 | 45.5 | -10.96 | 193 | 41.5 | -17.20 |
| AUDIT + CLIP | O/U2.5 | Avg | 209 | 45.5 | -9.79 | 161 | 41.0 | -19.29 |
| PRODUZIONE ATTUALE | 1X2 | B365 | 295 | 37.6 | -1.80 | 291 | 42.3 | 10.00 |
| PRODUZIONE ATTUALE | 1X2 | Avg | 299 | 38.1 | -1.17 | 284 | 41.2 | 1.61 |
| PRODUZIONE ATTUALE | O/U2.5 | B365 | 274 | 45.3 | -10.04 | 269 | 51.3 | 0.36 |
| PRODUZIONE ATTUALE | O/U2.5 | Avg | 273 | 45.8 | -9.81 | 257 | 50.2 | -4.09 |
| PRODUZIONE_NORM_SUM | 1X2 | B365 | 293 | 36.5 | -2.99 | 290 | 41.4 | 10.77 |
| PRODUZIONE_NORM_SUM | 1X2 | Avg | 297 | 36.7 | -2.78 | 285 | 41.1 | 9.42 |
| PRODUZIONE_NORM_SUM | O/U2.5 | B365 | 271 | 45.0 | -8.88 | 264 | 49.2 | -1.75 |
| PRODUZIONE_NORM_SUM | O/U2.5 | Avg | 273 | 45.1 | -9.30 | 255 | 48.2 | -5.48 |
| PROD_DC | 1X2 | B365 | 296 | 37.5 | -1.01 | 293 | 39.6 | -0.25 |
| PROD_DC | 1X2 | Avg | 294 | 37.8 | -4.01 | 294 | 39.5 | -2.13 |
| PROD_DC | O/U2.5 | B365 | 274 | 45.3 | -10.04 | 269 | 51.3 | 0.36 |
| PROD_DC | O/U2.5 | Avg | 273 | 45.8 | -9.81 | 257 | 50.2 | -4.09 |
| PROD_NORM_DC | 1X2 | B365 | 294 | 36.4 | -1.26 | 295 | 38.6 | 0.96 |
| PROD_NORM_DC | 1X2 | Avg | 296 | 35.8 | -4.93 | 292 | 38.4 | -0.95 |
| PROD_NORM_DC | O/U2.5 | B365 | 271 | 45.0 | -8.88 | 264 | 49.2 | -1.75 |
| PROD_NORM_DC | O/U2.5 | Avg | 273 | 45.1 | -9.30 | 255 | 48.2 | -5.48 |
| PRODUZIONE_DUE_TESTE | 1X2 | B365 | 293 | 36.5 | -2.99 | 290 | 41.4 | 10.77 |
| PRODUZIONE_DUE_TESTE | 1X2 | Avg | 297 | 36.7 | -2.78 | 285 | 41.1 | 9.42 |
| PRODUZIONE_DUE_TESTE | O/U2.5 | B365 | 271 | 45.0 | -8.88 | 264 | 49.2 | -1.75 |
| PRODUZIONE_DUE_TESTE | O/U2.5 | Avg | 273 | 45.1 | -9.30 | 255 | 48.2 | -5.48 |
| PRODUZIONE_DUE_TESTE_DC | 1X2 | B365 | 293 | 36.5 | -2.99 | 290 | 41.4 | 10.77 |
| PRODUZIONE_DUE_TESTE_DC | 1X2 | Avg | 297 | 36.7 | -2.78 | 285 | 41.1 | 9.42 |
| PRODUZIONE_DUE_TESTE_DC | O/U2.5 | B365 | 271 | 45.0 | -8.88 | 264 | 49.2 | -1.75 |
| PRODUZIONE_DUE_TESTE_DC | O/U2.5 | Avg | 273 | 45.1 | -9.30 | 255 | 48.2 | -5.48 |


## AGGREGATO — 5 LEGHE  (VAL 1752 + TEST 1752 partite)

### Brier / LogLoss  (V=2024/25, T=2025/26)

| Modello | Mercato | Brier V | LogLoss V | Brier T | LogLoss T |
|---|---|---|---|---|---|
| AUDIT solo-gol | 1X2 | 0.5910 | 1.0058 | 0.5957 | 1.0266 |
| AUDIT solo-gol | O/U2.5 | 0.2434 | 0.6797 | 0.2486 | 0.6904 |
| AUDIT solo-gol | GG/NG | 0.2488 | 0.7050 | 0.2498 | 0.7076 |
| AUDIT + CLIP | 1X2 | 0.5910 | 0.9948 | 0.5957 | 1.0040 |
| AUDIT + CLIP | O/U2.5 | 0.2434 | 0.6797 | 0.2486 | 0.6904 |
| AUDIT + CLIP | GG/NG | 0.2488 | 0.6928 | 0.2498 | 0.6954 |
| PRODUZIONE ATTUALE | 1X2 | 0.6267 | 1.0802 | 0.6260 | 1.0678 |
| PRODUZIONE ATTUALE | O/U2.5 | 0.2653 | 0.7431 | 0.2729 | 0.7583 |
| PRODUZIONE ATTUALE | GG/NG | 0.2734 | 0.7555 | 0.2736 | 0.7587 |
| PRODUZIONE_NORM_SUM | 1X2 | 0.6247 | 1.0705 | 0.6240 | 1.0609 |
| PRODUZIONE_NORM_SUM | O/U2.5 | 0.2649 | 0.7370 | 0.2716 | 0.7540 |
| PRODUZIONE_NORM_SUM | GG/NG | 0.2768 | 0.7645 | 0.2762 | 0.7669 |
| PROD_DC | 1X2 | 0.6267 | 1.0814 | 0.6257 | 1.0688 |
| PROD_DC | O/U2.5 | 0.2653 | 0.7431 | 0.2729 | 0.7583 |
| PROD_DC | GG/NG | 0.2728 | 0.7540 | 0.2729 | 0.7569 |
| PROD_NORM_DC | 1X2 | 0.6245 | 1.0720 | 0.6237 | 1.0621 |
| PROD_NORM_DC | O/U2.5 | 0.2649 | 0.7370 | 0.2716 | 0.7540 |
| PROD_NORM_DC | GG/NG | 0.2761 | 0.7628 | 0.2754 | 0.7649 |
| PRODUZIONE_DUE_TESTE | 1X2 | 0.6247 | 1.0705 | 0.6240 | 1.0609 |
| PRODUZIONE_DUE_TESTE | O/U2.5 | 0.2649 | 0.7370 | 0.2716 | 0.7540 |
| PRODUZIONE_DUE_TESTE | GG/NG | 0.2713 | 0.7502 | 0.2721 | 0.7548 |
| PRODUZIONE_DUE_TESTE_DC | 1X2 | 0.6247 | 1.0705 | 0.6240 | 1.0609 |
| PRODUZIONE_DUE_TESTE_DC | O/U2.5 | 0.2649 | 0.7370 | 0.2716 | 0.7540 |
| PRODUZIONE_DUE_TESTE_DC | GG/NG | 0.2707 | 0.7487 | 0.2714 | 0.7530 |

### ROI % / Win rate % (edge>0)  (V=2024/25, T=2025/26)

| Modello | Mercato | Quota | N V | WR V | ROI V | N T | WR T | ROI T |
|---|---|---|---|---|---|---|---|---|
| AUDIT solo-gol | 1X2 | B365 | 1493 | 32.0 | -13.40 | 1507 | 31.5 | -13.30 |
| AUDIT solo-gol | 1X2 | Avg | 1538 | 32.2 | -15.38 | 1412 | 32.3 | -12.35 |
| AUDIT solo-gol | O/U2.5 | B365 | 1278 | 47.6 | -6.97 | 1220 | 47.0 | -5.99 |
| AUDIT solo-gol | O/U2.5 | Avg | 1231 | 48.1 | -5.97 | 1077 | 45.7 | -10.43 |
| AUDIT + CLIP | 1X2 | B365 | 1493 | 32.0 | -13.40 | 1507 | 31.5 | -13.30 |
| AUDIT + CLIP | 1X2 | Avg | 1538 | 32.2 | -15.38 | 1412 | 32.3 | -12.35 |
| AUDIT + CLIP | O/U2.5 | B365 | 1278 | 47.6 | -6.97 | 1220 | 47.0 | -5.99 |
| AUDIT + CLIP | O/U2.5 | Avg | 1231 | 48.1 | -5.97 | 1077 | 45.7 | -10.43 |
| PRODUZIONE ATTUALE | 1X2 | B365 | 1699 | 42.8 | -0.13 | 1678 | 45.2 | 4.04 |
| PRODUZIONE ATTUALE | 1X2 | Avg | 1712 | 42.8 | -0.79 | 1669 | 44.9 | 1.67 |
| PRODUZIONE ATTUALE | O/U2.5 | B365 | 1564 | 50.9 | -6.14 | 1575 | 51.5 | -4.76 |
| PRODUZIONE ATTUALE | O/U2.5 | Avg | 1563 | 51.0 | -6.06 | 1506 | 51.2 | -7.08 |
| PRODUZIONE_NORM_SUM | 1X2 | B365 | 1699 | 41.8 | -1.76 | 1676 | 44.7 | 5.46 |
| PRODUZIONE_NORM_SUM | 1X2 | Avg | 1711 | 41.7 | -2.34 | 1665 | 44.3 | 2.81 |
| PRODUZIONE_NORM_SUM | O/U2.5 | B365 | 1556 | 49.8 | -6.44 | 1555 | 51.0 | -4.52 |
| PRODUZIONE_NORM_SUM | O/U2.5 | Avg | 1553 | 49.5 | -6.94 | 1497 | 50.9 | -6.26 |
| PROD_DC | 1X2 | B365 | 1705 | 42.5 | -1.10 | 1679 | 44.5 | 2.25 |
| PROD_DC | 1X2 | Avg | 1706 | 42.6 | -1.10 | 1677 | 44.3 | 0.41 |
| PROD_DC | O/U2.5 | B365 | 1564 | 50.9 | -6.14 | 1575 | 51.5 | -4.76 |
| PROD_DC | O/U2.5 | Avg | 1563 | 51.0 | -6.06 | 1506 | 51.2 | -7.08 |
| PROD_NORM_DC | 1X2 | B365 | 1700 | 41.6 | -1.88 | 1681 | 44.0 | 3.78 |
| PROD_NORM_DC | 1X2 | Avg | 1710 | 41.5 | -1.92 | 1672 | 43.6 | 1.48 |
| PROD_NORM_DC | O/U2.5 | B365 | 1556 | 49.8 | -6.44 | 1555 | 51.0 | -4.52 |
| PROD_NORM_DC | O/U2.5 | Avg | 1553 | 49.5 | -6.94 | 1497 | 50.9 | -6.26 |
| PRODUZIONE_DUE_TESTE | 1X2 | B365 | 1699 | 41.8 | -1.76 | 1676 | 44.7 | 5.46 |
| PRODUZIONE_DUE_TESTE | 1X2 | Avg | 1711 | 41.7 | -2.34 | 1665 | 44.3 | 2.81 |
| PRODUZIONE_DUE_TESTE | O/U2.5 | B365 | 1556 | 49.8 | -6.44 | 1555 | 51.0 | -4.52 |
| PRODUZIONE_DUE_TESTE | O/U2.5 | Avg | 1553 | 49.5 | -6.94 | 1497 | 50.9 | -6.26 |
| PRODUZIONE_DUE_TESTE_DC | 1X2 | B365 | 1699 | 41.8 | -1.76 | 1676 | 44.7 | 5.46 |
| PRODUZIONE_DUE_TESTE_DC | 1X2 | Avg | 1711 | 41.7 | -2.34 | 1665 | 44.3 | 2.81 |
| PRODUZIONE_DUE_TESTE_DC | O/U2.5 | B365 | 1556 | 49.8 | -6.44 | 1555 | 51.0 | -4.52 |
| PRODUZIONE_DUE_TESTE_DC | O/U2.5 | Avg | 1553 | 49.5 | -6.94 | 1497 | 50.9 | -6.26 |


## SINTESI — CLASSIFICA COMPARATIVA (AGGREGATO 5 LEGHE)

Ranking delle alternative per Brier 1X2 Validation; per ogni modello sono riportati anche O/U2.5, GG/NG e ROI 1X2 (Bet365).

| Modello | Brier 1X2 V | Brier 1X2 T | Brier O/U V | Brier O/U T | Brier GG V | Brier GG T | ROI 1X2 V% | ROI 1X2 T% |
|---|---|---|---|---|---|---|---|---|
| AUDIT + CLIP | 0.5910 | 0.5957 | 0.2434 | 0.2486 | 0.2488 | 0.2498 | -13.40 | -13.30 |
| AUDIT solo-gol | 0.5910 | 0.5957 | 0.2434 | 0.2486 | 0.2488 | 0.2498 | -13.40 | -13.30 |
| PROD_NORM_DC | 0.6245 | 0.6237 | 0.2649 | 0.2716 | 0.2761 | 0.2754 | -1.88 | 3.78 |
| PRODUZIONE_NORM_SUM | 0.6247 | 0.6240 | 0.2649 | 0.2716 | 0.2768 | 0.2762 | -1.76 | 5.46 |
| PRODUZIONE_DUE_TESTE | 0.6247 | 0.6240 | 0.2649 | 0.2716 | 0.2713 | 0.2721 | -1.76 | 5.46 |
| PRODUZIONE_DUE_TESTE_DC | 0.6247 | 0.6240 | 0.2649 | 0.2716 | 0.2707 | 0.2714 | -1.76 | 5.46 |
| PROD_DC | 0.6267 | 0.6257 | 0.2653 | 0.2729 | 0.2728 | 0.2729 | -1.10 | 2.25 |
| PRODUZIONE ATTUALE | 0.6267 | 0.6260 | 0.2653 | 0.2729 | 0.2734 | 0.2736 | -0.13 | 4.04 |

### Raccomandazione ingegneristica per SoccerMath/app.py

Su AGGREGATO (3.504 partite): miglior 1X2 = AUDIT + CLIP (Brier V 0.5910, ROI 1X2 V -13.40%); miglior O/U2.5 = AUDIT + CLIP (Brier V 0.2434); miglior GG/NG = AUDIT + CLIP (Brier V 0.2488). Se un unico modello domina su 1X2, O/U e GG si puo' implementare in SoccerMath/app.py; altrimenti adottare l'architettura a due teste (1X2 da NORM_SUM, Totali da base senza mercato).
