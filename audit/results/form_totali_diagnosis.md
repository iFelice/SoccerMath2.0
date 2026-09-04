# Forma (ult. 5) nella testa Totali: CON vs SENZA

Walk-forward no-leakage, 5 leghe, VALIDATION 2024/25 + TEST 2025/26. Testa Totali (lambda BASE, M=1) con xG stagionale primario e clip lambda [exp(-6), exp(3)]. A = xG/gol * forma ult.5 (clip [0.85,1.15]); B = xG/gol puri (baseline di lungo periodo). Delta = B - A (negativo = rimuovere la forma migliora).


## SERIE A  (VAL 380 + TEST 380 partite)

| Stagione | Mercato | Metrica | A CON forma | B SENZA forma | Delta | Migliore |
|---|---|---|---|---|---|---|
| 2024/25 | O/U2.5 | Brier | 0.2539 | 0.2453 | -0.0086 | SENZA |
| 2024/25 | O/U2.5 | LogLoss | 0.7015 | 0.6837 | -0.0179 | SENZA |
| 2024/25 | GG/NG | Brier | 0.2595 | 0.2504 | -0.0090 | SENZA |
| 2024/25 | GG/NG | LogLoss | 0.7128 | 0.6940 | -0.0188 | SENZA |
| 2025/26 | O/U2.5 | Brier | 0.2585 | 0.2501 | -0.0085 | SENZA |
| 2025/26 | O/U2.5 | LogLoss | 0.7130 | 0.6936 | -0.0194 | SENZA |
| 2025/26 | GG/NG | Brier | 0.2530 | 0.2480 | -0.0051 | SENZA |
| 2025/26 | GG/NG | LogLoss | 0.7004 | 0.6891 | -0.0113 | SENZA |

Std lambda totale: CON forma 0.477 | SENZA forma 0.275 | gol reali 1.524. Media lambda totale: CON 2.441 | SENZA 2.454 | reale 2.493.

## PREMIER LEAGUE  (VAL 380 + TEST 380 partite)

| Stagione | Mercato | Metrica | A CON forma | B SENZA forma | Delta | Migliore |
|---|---|---|---|---|---|---|
| 2024/25 | O/U2.5 | Brier | 0.2502 | 0.2400 | -0.0102 | SENZA |
| 2024/25 | O/U2.5 | LogLoss | 0.7017 | 0.6749 | -0.0267 | SENZA |
| 2024/25 | GG/NG | Brier | 0.2541 | 0.2460 | -0.0081 | SENZA |
| 2024/25 | GG/NG | LogLoss | 0.7029 | 0.6854 | -0.0175 | SENZA |
| 2025/26 | O/U2.5 | Brier | 0.2733 | 0.2608 | -0.0125 | SENZA |
| 2025/26 | O/U2.5 | LogLoss | 0.7474 | 0.7187 | -0.0288 | SENZA |
| 2025/26 | GG/NG | Brier | 0.2649 | 0.2555 | -0.0094 | SENZA |
| 2025/26 | GG/NG | LogLoss | 0.7263 | 0.7055 | -0.0208 | SENZA |

Std lambda totale: CON forma 0.778 | SENZA forma 0.600 | gol reali 1.596. Media lambda totale: CON 2.881 | SENZA 2.938 | reale 2.842.

## LA LIGA  (VAL 380 + TEST 380 partite)

| Stagione | Mercato | Metrica | A CON forma | B SENZA forma | Delta | Migliore |
|---|---|---|---|---|---|---|
| 2024/25 | O/U2.5 | Brier | 0.2489 | 0.2424 | -0.0065 | SENZA |
| 2024/25 | O/U2.5 | LogLoss | 0.6971 | 0.6793 | -0.0178 | SENZA |
| 2024/25 | GG/NG | Brier | 0.2731 | 0.2605 | -0.0126 | SENZA |
| 2024/25 | GG/NG | LogLoss | 0.7426 | 0.7150 | -0.0276 | SENZA |
| 2025/26 | O/U2.5 | Brier | 0.2584 | 0.2592 | +0.0008 | CON |
| 2025/26 | O/U2.5 | LogLoss | 0.7161 | 0.7151 | -0.0010 | SENZA |
| 2025/26 | GG/NG | Brier | 0.2762 | 0.2698 | -0.0064 | SENZA |
| 2025/26 | GG/NG | LogLoss | 0.7489 | 0.7344 | -0.0145 | SENZA |

Std lambda totale: CON forma 0.716 | SENZA forma 0.543 | gol reali 1.569. Media lambda totale: CON 2.335 | SENZA 2.295 | reale 2.657.

## BUNDESLIGA  (VAL 306 + TEST 306 partite)

| Stagione | Mercato | Metrica | A CON forma | B SENZA forma | Delta | Migliore |
|---|---|---|---|---|---|---|
| 2024/25 | O/U2.5 | Brier | 0.2379 | 0.2279 | -0.0100 | SENZA |
| 2024/25 | O/U2.5 | LogLoss | 0.6688 | 0.6458 | -0.0230 | SENZA |
| 2024/25 | GG/NG | Brier | 0.2433 | 0.2379 | -0.0054 | SENZA |
| 2024/25 | GG/NG | LogLoss | 0.6804 | 0.6688 | -0.0117 | SENZA |
| 2025/26 | O/U2.5 | Brier | 0.2510 | 0.2379 | -0.0131 | SENZA |
| 2025/26 | O/U2.5 | LogLoss | 0.6944 | 0.6662 | -0.0283 | SENZA |
| 2025/26 | GG/NG | Brier | 0.2505 | 0.2416 | -0.0088 | SENZA |
| 2025/26 | GG/NG | LogLoss | 0.6942 | 0.6752 | -0.0191 | SENZA |

Std lambda totale: CON forma 0.865 | SENZA forma 0.605 | gol reali 1.791. Media lambda totale: CON 3.010 | SENZA 2.988 | reale 3.185.

## LIGUE 1  (VAL 306 + TEST 306 partite)

| Stagione | Mercato | Metrica | A CON forma | B SENZA forma | Delta | Migliore |
|---|---|---|---|---|---|---|
| 2024/25 | O/U2.5 | Brier | 0.2515 | 0.2434 | -0.0081 | SENZA |
| 2024/25 | O/U2.5 | LogLoss | 0.7017 | 0.6801 | -0.0217 | SENZA |
| 2024/25 | GG/NG | Brier | 0.2593 | 0.2515 | -0.0078 | SENZA |
| 2024/25 | GG/NG | LogLoss | 0.7140 | 0.6967 | -0.0173 | SENZA |
| 2025/26 | O/U2.5 | Brier | 0.2509 | 0.2421 | -0.0088 | SENZA |
| 2025/26 | O/U2.5 | LogLoss | 0.6973 | 0.6769 | -0.0205 | SENZA |
| 2025/26 | GG/NG | Brier | 0.2601 | 0.2503 | -0.0098 | SENZA |
| 2025/26 | GG/NG | LogLoss | 0.7151 | 0.6939 | -0.0211 | SENZA |

Std lambda totale: CON forma 0.742 | SENZA forma 0.552 | gol reali 1.761. Media lambda totale: CON 2.794 | SENZA 2.712 | reale 2.899.

## AGGREGATO  (VAL 1752 + TEST 1752 partite)

| Stagione | Mercato | Metrica | A CON forma | B SENZA forma | Delta | Migliore |
|---|---|---|---|---|---|---|
| 2024/25 | O/U2.5 | Brier | 0.2488 | 0.2401 | -0.0087 | SENZA |
| 2024/25 | O/U2.5 | LogLoss | 0.6949 | 0.6736 | -0.0213 | SENZA |
| 2024/25 | GG/NG | Brier | 0.2584 | 0.2496 | -0.0088 | SENZA |
| 2024/25 | GG/NG | LogLoss | 0.7117 | 0.6928 | -0.0189 | SENZA |
| 2025/26 | O/U2.5 | Brier | 0.2591 | 0.2509 | -0.0082 | SENZA |
| 2025/26 | O/U2.5 | LogLoss | 0.7152 | 0.6960 | -0.0192 | SENZA |
| 2025/26 | GG/NG | Brier | 0.2614 | 0.2536 | -0.0078 | SENZA |
| 2025/26 | GG/NG | LogLoss | 0.7180 | 0.7009 | -0.0171 | SENZA |

Std lambda totale: CON forma 0.766 | SENZA forma 0.591 | gol reali 1.656. Media lambda totale: CON 2.675 | SENZA 2.663 | reale 2.796.

## Sintesi

- Confronti (lega x stagione x mercato x metrica) in cui SENZA forma batte CON forma: **39/40**.
- Brier O/U2.5 aggregato (V+T, 5 leghe): 0.2539 -> 0.2455.
- Brier GG/NG aggregato (V+T, 5 leghe): 0.2599 -> 0.2516.

### Raccomandazione

Sulla testa Totali usare la baseline pura di lungo periodo, senza la forma a 5 gare (in app.py: `att0_pure`/`def0_pure` alimentano la testa O/U2.5 e GG/NG; `att0`/`def0`, con forma, restano l'ancora S della normalizzazione della testa 1X2, che non viene toccata).
