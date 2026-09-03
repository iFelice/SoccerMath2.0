# Baseline di Produzione vs Baseline Audit (solo-gol)

Walk-forward no-leakage (ogni partita usa solo i dati precedenti). Season: VALIDATION 2024/25 e TEST 2025/26. Modelli: AUDIT solo-gol | AUDIT+CLIP (lambda clip [exp(-6),exp(3)]) | PRODUZIONE ATTUALE (xG stagionale primario + forma ult.5 [0.85,1.15] + valore di mercato [0.85,1.25] + clip lambda) | PRODUZIONE_NORM_SUM (somma attesa normalizzata senza mercato) | PROD_DC / PROD_NORM_DC (come i due precedenti ma con correzione Dixon-Coles tau(x,y,rho) sulle 4 celle basse e rinormalizzazione; rho stimato via MLE solo su training 2022/23+2023/24 per lega).

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
| PRODUZIONE ATTUALE | 1X2 | 0.5768 | 0.9649 | 0.6038 | 1.0179 |
| PRODUZIONE ATTUALE | O/U2.5 | 0.2550 | 0.7055 | 0.2631 | 0.7226 |
| PRODUZIONE ATTUALE | GG/NG | 0.2599 | 0.7140 | 0.2546 | 0.7042 |
| PRODUZIONE_NORM_SUM | 1X2 | 0.5748 | 0.9615 | 0.5999 | 1.0083 |
| PRODUZIONE_NORM_SUM | O/U2.5 | 0.2539 | 0.7015 | 0.2585 | 0.7130 |
| PRODUZIONE_NORM_SUM | GG/NG | 0.2620 | 0.7189 | 0.2575 | 0.7114 |
| PROD_DC | 1X2 | 0.5759 | 0.9636 | 0.6035 | 1.0179 |
| PROD_DC | O/U2.5 | 0.2550 | 0.7055 | 0.2631 | 0.7226 |
| PROD_DC | GG/NG | 0.2594 | 0.7128 | 0.2544 | 0.7036 |
| PROD_NORM_DC | 1X2 | 0.5740 | 0.9603 | 0.5997 | 1.0084 |
| PROD_NORM_DC | O/U2.5 | 0.2539 | 0.7015 | 0.2585 | 0.7130 |
| PROD_NORM_DC | GG/NG | 0.2614 | 0.7176 | 0.2572 | 0.7107 |

### ROI % / Win rate % (edge>0)  (V=2024/25, T=2025/26)

| Modello | Mercato | Quota | N V | WR V | ROI V | N T | WR T | ROI T |
|---|---|---|---|---|---|---|---|---|
| AUDIT solo-gol | 1X2 | B365 | 380 | 33.2 | -17.41 | 380 | 36.6 | -1.92 |
| AUDIT solo-gol | 1X2 | Avg | 380 | 34.2 | -15.46 | 380 | 35.8 | -6.19 |
| AUDIT solo-gol | O/U2.5 | B365 | 380 | 48.7 | -11.05 | 380 | 48.7 | -4.48 |
| AUDIT solo-gol | O/U2.5 | Avg | 380 | 48.2 | -11.86 | 380 | 48.2 | -7.47 |
| AUDIT + CLIP | 1X2 | B365 | 380 | 33.2 | -17.41 | 380 | 36.6 | -1.92 |
| AUDIT + CLIP | 1X2 | Avg | 380 | 34.2 | -15.46 | 380 | 35.8 | -6.19 |
| AUDIT + CLIP | O/U2.5 | B365 | 380 | 48.7 | -11.05 | 380 | 48.7 | -4.48 |
| AUDIT + CLIP | O/U2.5 | Avg | 380 | 48.2 | -11.86 | 380 | 48.2 | -7.47 |
| PRODUZIONE ATTUALE | 1X2 | B365 | 380 | 48.7 | 1.56 | 380 | 45.3 | -1.82 |
| PRODUZIONE ATTUALE | 1X2 | Avg | 380 | 47.9 | 0.15 | 380 | 45.8 | -1.74 |
| PRODUZIONE ATTUALE | O/U2.5 | B365 | 380 | 48.2 | -11.47 | 380 | 53.2 | -0.04 |
| PRODUZIONE ATTUALE | O/U2.5 | Avg | 380 | 48.9 | -10.36 | 380 | 53.4 | -1.02 |
| PRODUZIONE_NORM_SUM | 1X2 | B365 | 380 | 47.9 | 1.25 | 380 | 44.2 | -4.27 |
| PRODUZIONE_NORM_SUM | 1X2 | Avg | 380 | 47.4 | 0.59 | 380 | 45.0 | -4.12 |
| PRODUZIONE_NORM_SUM | O/U2.5 | B365 | 380 | 46.8 | -13.52 | 380 | 53.2 | -0.87 |
| PRODUZIONE_NORM_SUM | O/U2.5 | Avg | 380 | 47.9 | -12.18 | 380 | 52.6 | -3.80 |
| PROD_DC | 1X2 | B365 | 380 | 48.9 | 3.61 | 380 | 45.0 | -2.63 |
| PROD_DC | 1X2 | Avg | 380 | 48.2 | 1.43 | 380 | 45.5 | -2.90 |
| PROD_DC | O/U2.5 | B365 | 380 | 48.2 | -11.47 | 380 | 53.2 | -0.04 |
| PROD_DC | O/U2.5 | Avg | 380 | 48.9 | -10.36 | 380 | 53.4 | -1.02 |
| PROD_NORM_DC | 1X2 | B365 | 380 | 48.2 | 2.71 | 380 | 44.7 | -1.62 |
| PROD_NORM_DC | 1X2 | Avg | 380 | 47.6 | 3.72 | 380 | 43.4 | -8.93 |
| PROD_NORM_DC | O/U2.5 | B365 | 380 | 46.8 | -13.52 | 380 | 53.2 | -0.87 |
| PROD_NORM_DC | O/U2.5 | Avg | 380 | 47.9 | -12.18 | 380 | 52.6 | -3.80 |


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
| PRODUZIONE ATTUALE | 1X2 | 0.5846 | 0.9838 | 0.6245 | 1.0358 |
| PRODUZIONE ATTUALE | O/U2.5 | 0.2518 | 0.7106 | 0.2717 | 0.7437 |
| PRODUZIONE ATTUALE | GG/NG | 0.2552 | 0.7051 | 0.2664 | 0.7293 |
| PRODUZIONE_NORM_SUM | 1X2 | 0.5830 | 0.9798 | 0.6232 | 1.0336 |
| PRODUZIONE_NORM_SUM | O/U2.5 | 0.2502 | 0.7017 | 0.2733 | 0.7474 |
| PRODUZIONE_NORM_SUM | GG/NG | 0.2572 | 0.7095 | 0.2687 | 0.7346 |
| PROD_DC | 1X2 | 0.5845 | 0.9836 | 0.6244 | 1.0356 |
| PROD_DC | O/U2.5 | 0.2518 | 0.7106 | 0.2717 | 0.7437 |
| PROD_DC | GG/NG | 0.2551 | 0.7050 | 0.2663 | 0.7291 |
| PROD_NORM_DC | 1X2 | 0.5829 | 0.9797 | 0.6231 | 1.0335 |
| PROD_NORM_DC | O/U2.5 | 0.2502 | 0.7016 | 0.2733 | 0.7474 |
| PROD_NORM_DC | GG/NG | 0.2571 | 0.7093 | 0.2686 | 0.7343 |

### ROI % / Win rate % (edge>0)  (V=2024/25, T=2025/26)

| Modello | Mercato | Quota | N V | WR V | ROI V | N T | WR T | ROI T |
|---|---|---|---|---|---|---|---|---|
| AUDIT solo-gol | 1X2 | B365 | 380 | 36.6 | -9.24 | 380 | 33.7 | -11.65 |
| AUDIT solo-gol | 1X2 | Avg | 380 | 36.3 | -10.98 | 380 | 32.6 | -20.14 |
| AUDIT solo-gol | O/U2.5 | B365 | 380 | 50.3 | 3.69 | 380 | 53.7 | 3.26 |
| AUDIT solo-gol | O/U2.5 | Avg | 380 | 49.7 | 3.26 | 380 | 52.1 | -1.74 |
| AUDIT + CLIP | 1X2 | B365 | 380 | 36.6 | -9.24 | 380 | 33.7 | -11.65 |
| AUDIT + CLIP | 1X2 | Avg | 380 | 36.3 | -10.98 | 380 | 32.6 | -20.14 |
| AUDIT + CLIP | O/U2.5 | B365 | 380 | 50.3 | 3.69 | 380 | 53.7 | 3.26 |
| AUDIT + CLIP | O/U2.5 | Avg | 380 | 49.7 | 3.26 | 380 | 52.1 | -1.74 |
| PRODUZIONE ATTUALE | 1X2 | B365 | 380 | 48.4 | 7.99 | 380 | 42.4 | 1.75 |
| PRODUZIONE ATTUALE | 1X2 | Avg | 380 | 47.9 | 6.87 | 380 | 43.2 | 2.69 |
| PRODUZIONE ATTUALE | O/U2.5 | B365 | 380 | 57.1 | 9.49 | 380 | 48.4 | -5.00 |
| PRODUZIONE ATTUALE | O/U2.5 | Avg | 380 | 56.8 | 9.05 | 380 | 48.2 | -6.94 |
| PRODUZIONE_NORM_SUM | 1X2 | B365 | 380 | 48.9 | 11.24 | 380 | 41.8 | 3.61 |
| PRODUZIONE_NORM_SUM | 1X2 | Avg | 380 | 47.9 | 5.39 | 380 | 41.6 | 1.90 |
| PRODUZIONE_NORM_SUM | O/U2.5 | B365 | 380 | 55.8 | 7.68 | 380 | 48.4 | -4.67 |
| PRODUZIONE_NORM_SUM | O/U2.5 | Avg | 380 | 56.6 | 9.46 | 380 | 48.9 | -5.31 |
| PROD_DC | 1X2 | B365 | 380 | 48.9 | 10.57 | 380 | 43.2 | 4.62 |
| PROD_DC | 1X2 | Avg | 380 | 47.6 | 6.49 | 380 | 42.9 | 1.77 |
| PROD_DC | O/U2.5 | B365 | 380 | 57.1 | 9.49 | 380 | 48.4 | -5.00 |
| PROD_DC | O/U2.5 | Avg | 380 | 56.8 | 9.05 | 380 | 48.2 | -6.94 |
| PROD_NORM_DC | 1X2 | B365 | 380 | 48.7 | 10.06 | 380 | 41.6 | 3.21 |
| PROD_NORM_DC | 1X2 | Avg | 380 | 48.4 | 7.82 | 380 | 41.6 | 2.36 |
| PROD_NORM_DC | O/U2.5 | B365 | 380 | 55.8 | 7.68 | 380 | 48.4 | -4.67 |
| PROD_NORM_DC | O/U2.5 | Avg | 380 | 56.6 | 9.46 | 380 | 48.9 | -5.31 |


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
| PRODUZIONE ATTUALE | 1X2 | 0.5666 | 0.9645 | 0.5942 | 1.0031 |
| PRODUZIONE ATTUALE | O/U2.5 | 0.2496 | 0.7012 | 0.2571 | 0.7136 |
| PRODUZIONE ATTUALE | GG/NG | 0.2758 | 0.7487 | 0.2795 | 0.7562 |
| PRODUZIONE_NORM_SUM | 1X2 | 0.5650 | 0.9590 | 0.5923 | 1.0010 |
| PRODUZIONE_NORM_SUM | O/U2.5 | 0.2489 | 0.6971 | 0.2584 | 0.7161 |
| PRODUZIONE_NORM_SUM | GG/NG | 0.2804 | 0.7594 | 0.2846 | 0.7679 |
| PROD_DC | 1X2 | 0.5666 | 0.9644 | 0.5942 | 1.0033 |
| PROD_DC | O/U2.5 | 0.2496 | 0.7012 | 0.2571 | 0.7136 |
| PROD_DC | GG/NG | 0.2756 | 0.7481 | 0.2792 | 0.7555 |
| PROD_NORM_DC | 1X2 | 0.5649 | 0.9590 | 0.5924 | 1.0014 |
| PROD_NORM_DC | O/U2.5 | 0.2489 | 0.6971 | 0.2584 | 0.7161 |
| PROD_NORM_DC | GG/NG | 0.2802 | 0.7589 | 0.2843 | 0.7672 |

### ROI % / Win rate % (edge>0)  (V=2024/25, T=2025/26)

| Modello | Mercato | Quota | N V | WR V | ROI V | N T | WR T | ROI T |
|---|---|---|---|---|---|---|---|---|
| AUDIT solo-gol | 1X2 | B365 | 380 | 35.0 | -10.20 | 380 | 35.0 | -16.59 |
| AUDIT solo-gol | 1X2 | Avg | 380 | 33.9 | -14.41 | 380 | 35.5 | -15.31 |
| AUDIT solo-gol | O/U2.5 | B365 | 380 | 45.5 | -12.07 | 380 | 49.5 | -1.01 |
| AUDIT solo-gol | O/U2.5 | Avg | 380 | 46.1 | -11.99 | 380 | 52.6 | 1.28 |
| AUDIT + CLIP | 1X2 | B365 | 380 | 35.0 | -10.20 | 380 | 35.0 | -16.59 |
| AUDIT + CLIP | 1X2 | Avg | 380 | 33.9 | -14.41 | 380 | 35.5 | -15.31 |
| AUDIT + CLIP | O/U2.5 | B365 | 380 | 45.5 | -12.07 | 380 | 49.5 | -1.01 |
| AUDIT + CLIP | O/U2.5 | Avg | 380 | 46.1 | -11.99 | 380 | 52.6 | 1.28 |
| PRODUZIONE ATTUALE | 1X2 | B365 | 380 | 50.3 | 9.20 | 380 | 47.1 | -0.09 |
| PRODUZIONE ATTUALE | 1X2 | Avg | 380 | 49.2 | 5.95 | 380 | 46.6 | -1.58 |
| PRODUZIONE ATTUALE | O/U2.5 | B365 | 380 | 56.3 | -0.12 | 380 | 55.5 | 1.38 |
| PRODUZIONE ATTUALE | O/U2.5 | Avg | 380 | 56.6 | 0.09 | 380 | 55.5 | -0.55 |
| PRODUZIONE_NORM_SUM | 1X2 | B365 | 380 | 49.5 | 8.46 | 380 | 46.6 | 2.56 |
| PRODUZIONE_NORM_SUM | 1X2 | Avg | 380 | 48.7 | 6.62 | 380 | 45.8 | -0.87 |
| PRODUZIONE_NORM_SUM | O/U2.5 | B365 | 380 | 55.8 | -0.01 | 380 | 52.9 | -0.72 |
| PRODUZIONE_NORM_SUM | O/U2.5 | Avg | 380 | 56.8 | 2.09 | 380 | 52.6 | -3.34 |
| PROD_DC | 1X2 | B365 | 380 | 49.7 | 7.02 | 380 | 47.4 | 1.36 |
| PROD_DC | 1X2 | Avg | 380 | 49.2 | 5.95 | 380 | 46.6 | -1.58 |
| PROD_DC | O/U2.5 | B365 | 380 | 56.3 | -0.12 | 380 | 55.5 | 1.38 |
| PROD_DC | O/U2.5 | Avg | 380 | 56.6 | 0.09 | 380 | 55.5 | -0.55 |
| PROD_NORM_DC | 1X2 | B365 | 380 | 48.9 | 6.86 | 380 | 45.8 | 0.68 |
| PROD_NORM_DC | 1X2 | Avg | 380 | 48.4 | 5.20 | 380 | 45.5 | -1.29 |
| PROD_NORM_DC | O/U2.5 | B365 | 380 | 55.8 | -0.01 | 380 | 52.9 | -0.72 |
| PROD_NORM_DC | O/U2.5 | Avg | 380 | 56.8 | 2.09 | 380 | 52.6 | -3.34 |


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
| PRODUZIONE ATTUALE | 1X2 | 0.6191 | 1.0415 | 0.5735 | 0.9774 |
| PRODUZIONE ATTUALE | O/U2.5 | 0.2385 | 0.6712 | 0.2484 | 0.6882 |
| PRODUZIONE ATTUALE | GG/NG | 0.2460 | 0.6863 | 0.2535 | 0.7009 |
| PRODUZIONE_NORM_SUM | 1X2 | 0.6160 | 1.0327 | 0.5719 | 0.9708 |
| PRODUZIONE_NORM_SUM | O/U2.5 | 0.2379 | 0.6688 | 0.2510 | 0.6944 |
| PRODUZIONE_NORM_SUM | GG/NG | 0.2497 | 0.6947 | 0.2575 | 0.7100 |
| PROD_DC | 1X2 | 0.6181 | 1.0420 | 0.5726 | 0.9763 |
| PROD_DC | O/U2.5 | 0.2385 | 0.6712 | 0.2484 | 0.6882 |
| PROD_DC | GG/NG | 0.2447 | 0.6836 | 0.2511 | 0.6959 |
| PROD_NORM_DC | 1X2 | 0.6152 | 1.0339 | 0.5711 | 0.9702 |
| PROD_NORM_DC | O/U2.5 | 0.2379 | 0.6688 | 0.2510 | 0.6944 |
| PROD_NORM_DC | GG/NG | 0.2481 | 0.6914 | 0.2548 | 0.7044 |

### ROI % / Win rate % (edge>0)  (V=2024/25, T=2025/26)

| Modello | Mercato | Quota | N V | WR V | ROI V | N T | WR T | ROI T |
|---|---|---|---|---|---|---|---|---|
| AUDIT solo-gol | 1X2 | B365 | 306 | 29.7 | -31.75 | 306 | 38.6 | -5.99 |
| AUDIT solo-gol | 1X2 | Avg | 306 | 29.4 | -30.50 | 306 | 40.2 | -2.80 |
| AUDIT solo-gol | O/U2.5 | B365 | 306 | 56.5 | 0.58 | 306 | 46.1 | -12.37 |
| AUDIT solo-gol | O/U2.5 | Avg | 306 | 55.6 | -1.56 | 306 | 45.1 | -16.34 |
| AUDIT + CLIP | 1X2 | B365 | 306 | 29.7 | -31.75 | 306 | 38.6 | -5.99 |
| AUDIT + CLIP | 1X2 | Avg | 306 | 29.4 | -30.50 | 306 | 40.2 | -2.80 |
| AUDIT + CLIP | O/U2.5 | B365 | 306 | 56.5 | 0.58 | 306 | 46.1 | -12.37 |
| AUDIT + CLIP | O/U2.5 | Avg | 306 | 55.6 | -1.56 | 306 | 45.1 | -16.34 |
| PRODUZIONE ATTUALE | 1X2 | B365 | 306 | 44.1 | -11.85 | 306 | 51.0 | 0.96 |
| PRODUZIONE ATTUALE | 1X2 | Avg | 306 | 45.8 | -7.72 | 306 | 51.0 | 1.09 |
| PRODUZIONE ATTUALE | O/U2.5 | B365 | 306 | 56.2 | 2.12 | 306 | 48.7 | -10.45 |
| PRODUZIONE ATTUALE | O/U2.5 | Avg | 306 | 55.2 | -0.06 | 306 | 47.7 | -13.98 |
| PRODUZIONE_NORM_SUM | 1X2 | B365 | 306 | 43.8 | -10.68 | 306 | 50.7 | 1.46 |
| PRODUZIONE_NORM_SUM | 1X2 | Avg | 306 | 45.8 | -4.86 | 306 | 50.7 | 0.41 |
| PRODUZIONE_NORM_SUM | O/U2.5 | B365 | 306 | 53.3 | 0.16 | 306 | 43.1 | -16.50 |
| PRODUZIONE_NORM_SUM | O/U2.5 | Avg | 306 | 52.3 | -1.31 | 306 | 44.1 | -17.35 |
| PROD_DC | 1X2 | B365 | 306 | 41.5 | -17.12 | 306 | 47.1 | -4.96 |
| PROD_DC | 1X2 | Avg | 306 | 41.8 | -15.44 | 306 | 48.4 | -2.09 |
| PROD_DC | O/U2.5 | B365 | 306 | 56.2 | 2.12 | 306 | 48.7 | -10.45 |
| PROD_DC | O/U2.5 | Avg | 306 | 55.2 | -0.06 | 306 | 47.7 | -13.98 |
| PROD_NORM_DC | 1X2 | B365 | 306 | 41.8 | -13.20 | 306 | 47.1 | -3.25 |
| PROD_NORM_DC | 1X2 | Avg | 306 | 42.2 | -12.26 | 306 | 47.7 | -2.90 |
| PROD_NORM_DC | O/U2.5 | B365 | 306 | 53.3 | 0.16 | 306 | 43.1 | -16.50 |
| PROD_NORM_DC | O/U2.5 | Avg | 306 | 52.3 | -1.31 | 306 | 44.1 | -17.35 |


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
| PRODUZIONE ATTUALE | 1X2 | 0.5692 | 0.9736 | 0.6012 | 1.0059 |
| PRODUZIONE ATTUALE | O/U2.5 | 0.2530 | 0.7090 | 0.2505 | 0.6965 |
| PRODUZIONE ATTUALE | GG/NG | 0.2636 | 0.7230 | 0.2616 | 0.7182 |
| PRODUZIONE_NORM_SUM | 1X2 | 0.5668 | 0.9658 | 0.5990 | 1.0019 |
| PRODUZIONE_NORM_SUM | O/U2.5 | 0.2515 | 0.7017 | 0.2509 | 0.6973 |
| PRODUZIONE_NORM_SUM | GG/NG | 0.2690 | 0.7350 | 0.2646 | 0.7249 |
| PROD_DC | 1X2 | 0.5693 | 0.9749 | 0.6008 | 1.0064 |
| PROD_DC | O/U2.5 | 0.2530 | 0.7090 | 0.2505 | 0.6965 |
| PROD_DC | GG/NG | 0.2630 | 0.7218 | 0.2610 | 0.7168 |
| PROD_NORM_DC | 1X2 | 0.5670 | 0.9675 | 0.5987 | 1.0026 |
| PROD_NORM_DC | O/U2.5 | 0.2515 | 0.7017 | 0.2509 | 0.6973 |
| PROD_NORM_DC | GG/NG | 0.2683 | 0.7335 | 0.2638 | 0.7232 |

### ROI % / Win rate % (edge>0)  (V=2024/25, T=2025/26)

| Modello | Mercato | Quota | N V | WR V | ROI V | N T | WR T | ROI T |
|---|---|---|---|---|---|---|---|---|
| AUDIT solo-gol | 1X2 | B365 | 306 | 38.2 | -4.16 | 306 | 34.3 | -9.55 |
| AUDIT solo-gol | 1X2 | Avg | 306 | 37.6 | -7.93 | 306 | 35.3 | -10.12 |
| AUDIT solo-gol | O/U2.5 | B365 | 306 | 49.3 | -5.00 | 306 | 44.8 | -13.50 |
| AUDIT solo-gol | O/U2.5 | Avg | 306 | 51.0 | -2.56 | 306 | 45.8 | -13.77 |
| AUDIT + CLIP | 1X2 | B365 | 306 | 38.2 | -4.16 | 306 | 34.3 | -9.55 |
| AUDIT + CLIP | 1X2 | Avg | 306 | 37.6 | -7.93 | 306 | 35.3 | -10.12 |
| AUDIT + CLIP | O/U2.5 | B365 | 306 | 49.3 | -5.00 | 306 | 44.8 | -13.50 |
| AUDIT + CLIP | O/U2.5 | Avg | 306 | 51.0 | -2.56 | 306 | 45.8 | -13.77 |
| PRODUZIONE ATTUALE | 1X2 | B365 | 306 | 54.9 | 14.48 | 306 | 48.0 | -2.59 |
| PRODUZIONE ATTUALE | 1X2 | Avg | 306 | 54.9 | 13.38 | 306 | 47.7 | -3.73 |
| PRODUZIONE ATTUALE | O/U2.5 | B365 | 306 | 52.6 | -3.84 | 306 | 52.6 | 0.05 |
| PRODUZIONE ATTUALE | O/U2.5 | Avg | 306 | 52.3 | -4.30 | 306 | 53.6 | 0.35 |
| PRODUZIONE_NORM_SUM | 1X2 | B365 | 306 | 54.9 | 16.10 | 306 | 45.8 | -3.81 |
| PRODUZIONE_NORM_SUM | 1X2 | Avg | 306 | 54.2 | 12.51 | 306 | 46.1 | -4.75 |
| PRODUZIONE_NORM_SUM | O/U2.5 | B365 | 306 | 51.3 | -3.82 | 306 | 52.0 | 1.32 |
| PRODUZIONE_NORM_SUM | O/U2.5 | Avg | 306 | 51.3 | -4.11 | 306 | 52.3 | -0.09 |
| PROD_DC | 1X2 | B365 | 306 | 55.2 | 16.25 | 306 | 47.7 | -2.04 |
| PROD_DC | 1X2 | Avg | 306 | 54.9 | 14.01 | 306 | 48.7 | 2.10 |
| PROD_DC | O/U2.5 | B365 | 306 | 52.6 | -3.84 | 306 | 52.6 | 0.05 |
| PROD_DC | O/U2.5 | Avg | 306 | 52.3 | -4.30 | 306 | 53.6 | 0.35 |
| PROD_NORM_DC | 1X2 | B365 | 306 | 53.3 | 12.52 | 306 | 45.8 | -1.79 |
| PROD_NORM_DC | 1X2 | Avg | 306 | 54.2 | 14.62 | 306 | 46.7 | 0.73 |
| PROD_NORM_DC | O/U2.5 | B365 | 306 | 51.3 | -3.82 | 306 | 52.0 | 1.32 |
| PROD_NORM_DC | O/U2.5 | Avg | 306 | 51.3 | -4.11 | 306 | 52.3 | -0.09 |


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
| PRODUZIONE ATTUALE | 1X2 | 0.5823 | 0.9838 | 0.6005 | 1.0094 |
| PRODUZIONE ATTUALE | O/U2.5 | 0.2499 | 0.7003 | 0.2589 | 0.7147 |
| PRODUZIONE ATTUALE | GG/NG | 0.2605 | 0.7163 | 0.2636 | 0.7228 |
| PRODUZIONE_NORM_SUM | 1X2 | 0.5803 | 0.9781 | 0.5983 | 1.0045 |
| PRODUZIONE_NORM_SUM | O/U2.5 | 0.2488 | 0.6949 | 0.2591 | 0.7152 |
| PRODUZIONE_NORM_SUM | GG/NG | 0.2640 | 0.7242 | 0.2670 | 0.7308 |
| PROD_DC | 1X2 | 0.5820 | 0.9838 | 0.6002 | 1.0093 |
| PROD_DC | O/U2.5 | 0.2499 | 0.7003 | 0.2589 | 0.7147 |
| PROD_DC | GG/NG | 0.2600 | 0.7153 | 0.2629 | 0.7213 |
| PROD_NORM_DC | 1X2 | 0.5799 | 0.9783 | 0.5980 | 1.0046 |
| PROD_NORM_DC | O/U2.5 | 0.2488 | 0.6949 | 0.2591 | 0.7152 |
| PROD_NORM_DC | GG/NG | 0.2634 | 0.7230 | 0.2663 | 0.7291 |

### ROI % / Win rate % (edge>0)  (V=2024/25, T=2025/26)

| Modello | Mercato | Quota | N V | WR V | ROI V | N T | WR T | ROI T |
|---|---|---|---|---|---|---|---|---|
| AUDIT solo-gol | 1X2 | B365 | 1752 | 34.6 | -14.26 | 1752 | 35.6 | -9.25 |
| AUDIT solo-gol | 1X2 | Avg | 1752 | 34.4 | -15.57 | 1752 | 35.7 | -11.29 |
| AUDIT solo-gol | O/U2.5 | B365 | 1752 | 49.8 | -4.98 | 1752 | 48.8 | -5.00 |
| AUDIT solo-gol | O/U2.5 | Avg | 1752 | 49.8 | -5.19 | 1752 | 49.0 | -6.98 |
| AUDIT + CLIP | 1X2 | B365 | 1752 | 34.6 | -14.26 | 1752 | 35.6 | -9.25 |
| AUDIT + CLIP | 1X2 | Avg | 1752 | 34.4 | -15.57 | 1752 | 35.7 | -11.29 |
| AUDIT + CLIP | O/U2.5 | B365 | 1752 | 49.8 | -4.98 | 1752 | 48.8 | -5.00 |
| AUDIT + CLIP | O/U2.5 | Avg | 1752 | 49.8 | -5.19 | 1752 | 49.0 | -6.98 |
| PRODUZIONE ATTUALE | 1X2 | B365 | 1752 | 49.3 | 4.53 | 1752 | 46.5 | -0.32 |
| PRODUZIONE ATTUALE | 1X2 | Avg | 1752 | 49.0 | 3.80 | 1752 | 46.6 | -0.60 |
| PRODUZIONE ATTUALE | O/U2.5 | B365 | 1752 | 54.1 | -0.75 | 1752 | 51.8 | -2.61 |
| PRODUZIONE ATTUALE | O/U2.5 | Avg | 1752 | 54.0 | -1.03 | 1752 | 51.8 | -4.23 |
| PRODUZIONE_NORM_SUM | 1X2 | B365 | 1752 | 49.0 | 5.49 | 1752 | 45.6 | 0.00 |
| PRODUZIONE_NORM_SUM | 1X2 | Avg | 1752 | 48.7 | 4.07 | 1752 | 45.6 | -1.43 |
| PRODUZIONE_NORM_SUM | O/U2.5 | B365 | 1752 | 52.6 | -1.91 | 1752 | 50.1 | -4.01 |
| PRODUZIONE_NORM_SUM | O/U2.5 | Avg | 1752 | 53.1 | -1.09 | 1752 | 50.3 | -5.75 |
| PROD_DC | 1X2 | B365 | 1752 | 48.9 | 4.45 | 1752 | 45.9 | -0.50 |
| PROD_DC | 1X2 | Avg | 1752 | 48.3 | 2.76 | 1752 | 46.2 | -0.59 |
| PROD_DC | O/U2.5 | B365 | 1752 | 54.1 | -0.75 | 1752 | 51.8 | -2.61 |
| PROD_DC | O/U2.5 | Avg | 1752 | 54.0 | -1.03 | 1752 | 51.8 | -4.23 |
| PROD_NORM_DC | 1X2 | B365 | 1752 | 48.2 | 4.14 | 1752 | 44.9 | -0.39 |
| PROD_NORM_DC | 1X2 | Avg | 1752 | 48.2 | 4.04 | 1752 | 44.8 | -2.08 |
| PROD_NORM_DC | O/U2.5 | B365 | 1752 | 52.6 | -1.91 | 1752 | 50.1 | -4.01 |
| PROD_NORM_DC | O/U2.5 | Avg | 1752 | 53.1 | -1.09 | 1752 | 50.3 | -5.75 |
