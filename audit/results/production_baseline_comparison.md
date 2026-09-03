# Baseline di Produzione vs Baseline Audit (solo-gol)

Walk-forward no-leakage (ogni partita usa solo i dati precedenti). Season: VALIDATION 2024/25 e TEST 2025/26. Modelli: AUDIT solo-gol | AUDIT+CLIP (lambda clip [exp(-6),exp(3)]) | PRODUZIONE (xG stagionale primario + forma ult.5 [0.85,1.15] + valore di mercato [0.85,1.25] + clip lambda).

xG di produzione: snapshot stagionale statico da xg_<lega>.json (stesso file letto da get_league_engine); applicato costante alle partite, come fa il motore di produzione a un dato istante.

Nota metodologica: lo snapshot xG disponibile riflette la squadra ATTUALE. Applicandolo
costante alle partite 2024/25 e 2025/26 si introduce un'informazione sui punti di forza
delle rose odierne applicata a stagioni passate: i numeri di PRODUZIONE su queste
stagioni vanno quindi letti come fedeli alla *struttura* del motore, ma l'eventuale
edge/ROI in validation non va interpretato come edge out-of-sample reale.


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
| PRODUZIONE | 1X2 | 0.5768 | 0.9649 | 0.6038 | 1.0179 |
| PRODUZIONE | O/U2.5 | 0.2550 | 0.7055 | 0.2631 | 0.7226 |
| PRODUZIONE | GG/NG | 0.2599 | 0.7140 | 0.2546 | 0.7042 |

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
| PRODUZIONE | 1X2 | B365 | 380 | 48.7 | 1.56 | 380 | 45.3 | -1.82 |
| PRODUZIONE | 1X2 | Avg | 380 | 47.9 | 0.15 | 380 | 45.8 | -1.74 |
| PRODUZIONE | O/U2.5 | B365 | 380 | 48.2 | -11.47 | 380 | 53.2 | -0.04 |
| PRODUZIONE | O/U2.5 | Avg | 380 | 48.9 | -10.36 | 380 | 53.4 | -1.02 |


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
| PRODUZIONE | 1X2 | 0.5846 | 0.9838 | 0.6320 | 1.0465 |
| PRODUZIONE | O/U2.5 | 0.2518 | 0.7106 | 0.2717 | 0.7437 |
| PRODUZIONE | GG/NG | 0.2552 | 0.7051 | 0.2673 | 0.7314 |

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
| PRODUZIONE | 1X2 | B365 | 380 | 48.4 | 7.99 | 380 | 43.4 | 2.03 |
| PRODUZIONE | 1X2 | Avg | 380 | 47.9 | 6.87 | 380 | 43.4 | 1.11 |
| PRODUZIONE | O/U2.5 | B365 | 380 | 57.1 | 9.49 | 380 | 48.4 | -5.48 |
| PRODUZIONE | O/U2.5 | Avg | 380 | 56.8 | 9.05 | 380 | 48.2 | -7.46 |


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
| PRODUZIONE | 1X2 | 0.5695 | 0.9674 | 0.5868 | 0.9886 |
| PRODUZIONE | O/U2.5 | 0.2483 | 0.6988 | 0.2554 | 0.7100 |
| PRODUZIONE | GG/NG | 0.2760 | 0.7491 | 0.2798 | 0.7566 |

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
| PRODUZIONE | 1X2 | B365 | 380 | 46.8 | 4.24 | 380 | 43.2 | -3.17 |
| PRODUZIONE | 1X2 | Avg | 380 | 47.4 | 7.93 | 380 | 43.4 | -2.78 |
| PRODUZIONE | O/U2.5 | B365 | 380 | 57.6 | 1.37 | 380 | 56.8 | 3.08 |
| PRODUZIONE | O/U2.5 | Avg | 380 | 57.9 | 1.89 | 380 | 56.6 | 0.17 |


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
| PRODUZIONE | 1X2 | 0.6227 | 1.0474 | 0.5710 | 0.9733 |
| PRODUZIONE | O/U2.5 | 0.2392 | 0.6735 | 0.2472 | 0.6845 |
| PRODUZIONE | GG/NG | 0.2456 | 0.6855 | 0.2542 | 0.7024 |

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
| PRODUZIONE | 1X2 | B365 | 306 | 43.1 | -13.85 | 306 | 49.7 | -3.38 |
| PRODUZIONE | 1X2 | Avg | 306 | 45.1 | -8.64 | 306 | 50.3 | -1.58 |
| PRODUZIONE | O/U2.5 | B365 | 306 | 54.6 | -0.56 | 306 | 48.7 | -11.86 |
| PRODUZIONE | O/U2.5 | Avg | 306 | 54.6 | -1.22 | 306 | 48.0 | -14.14 |


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
| PRODUZIONE | 1X2 | 0.5697 | 0.9746 | 0.6014 | 1.0067 |
| PRODUZIONE | O/U2.5 | 0.2531 | 0.7097 | 0.2503 | 0.6961 |
| PRODUZIONE | GG/NG | 0.2636 | 0.7230 | 0.2617 | 0.7184 |

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
| PRODUZIONE | 1X2 | B365 | 306 | 55.2 | 15.07 | 306 | 47.7 | -2.16 |
| PRODUZIONE | 1X2 | Avg | 306 | 55.2 | 13.97 | 306 | 47.4 | -3.37 |
| PRODUZIONE | O/U2.5 | B365 | 306 | 52.6 | -3.84 | 306 | 52.9 | 0.67 |
| PRODUZIONE | O/U2.5 | Avg | 306 | 52.6 | -3.81 | 306 | 53.6 | 0.35 |


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
| PRODUZIONE | 1X2 | 0.5837 | 0.9856 | 0.6001 | 1.0080 |
| PRODUZIONE | O/U2.5 | 0.2498 | 0.7003 | 0.2583 | 0.7132 |
| PRODUZIONE | GG/NG | 0.2605 | 0.7163 | 0.2640 | 0.7236 |

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
| PRODUZIONE | 1X2 | B365 | 1752 | 48.4 | 3.20 | 1752 | 45.6 | -1.61 |
| PRODUZIONE | 1X2 | Avg | 1752 | 48.6 | 4.18 | 1752 | 45.8 | -1.61 |
| PRODUZIONE | O/U2.5 | B365 | 1752 | 54.1 | -0.90 | 1752 | 52.1 | -2.48 |
| PRODUZIONE | O/U2.5 | Avg | 1752 | 54.2 | -0.75 | 1752 | 52.1 | -4.21 |
