# Diagnosi compressione lambda — Variante A (tutto storico) vs Variante B (ultime 38 partite)

Campione: walk-forward no-leakage, VALIDATION 2024/25 + TEST 2025/26, 5 leghe.
Modello Poisson, stesso calcolo di diagnose_ou_gg.py. Media di lega avg_h/avg_a identica per entrambe le varianti (solo le statistiche di squadra cambiano).


## SERIE A

### 1. Std dev rapporti att/def TRA squadre — meta' stagione (15a giornata)

| Stagione | rapporto | std A (tutto storico) | std B (ult. 38) |
|---|---|---|---|
| 2024/25 | att_h | 0.2965 | 0.3027 |
| 2024/25 | def_h | 0.3324 | 0.3264 |
| 2024/25 | att_a | 0.3194 | 0.3262 |
| 2024/25 | def_a | 0.2749 | 0.2796 |
| 2025/26 | att_h | 0.3293 | 0.3343 |
| 2025/26 | def_h | 0.2724 | 0.2712 |
| 2025/26 | att_a | 0.2902 | 0.3068 |
| 2025/26 | def_a | 0.2696 | 0.2695 |

### 2. Std dev lambda_totale per partita (N=760, val+test)

- Variante A: **0.3995**
- Variante B: **0.4183**

### 3. Rapporto std_gol_reali / std_lambda

- std gol reali: 1.5245
- Variante A: **3.82**
- Variante B: **3.64**

### 4. Brier / LogLoss su O/U2.5 e GG (A vs B)

| Stagione | mercato | metric | A | B |
|---|---|---|---|---|
| 2024/25 | O/U2.5 | Brier | 0.2515 | 0.2538 |
| 2024/25 | O/U2.5 | LogLoss | 0.6968 | 0.7015 |
| 2024/25 | GG | Brier | 0.2528 | 0.2536 |
| 2024/25 | GG | LogLoss | 0.6988 | 0.7003 |
| 2025/26 | O/U2.5 | Brier | 0.2553 | 0.2572 |
| 2025/26 | O/U2.5 | LogLoss | 0.7043 | 0.7083 |
| 2025/26 | GG | Brier | 0.2489 | 0.2500 |
| 2025/26 | GG | LogLoss | 0.6913 | 0.6935 |


## PREMIER LEAGUE

### 1. Std dev rapporti att/def TRA squadre — meta' stagione (15a giornata)

| Stagione | rapporto | std A (tutto storico) | std B (ult. 38) |
|---|---|---|---|
| 2024/25 | att_h | 0.3112 | 0.2906 |
| 2024/25 | def_h | 0.3569 | 0.3517 |
| 2024/25 | att_a | 0.2563 | 0.2596 |
| 2024/25 | def_a | 0.2384 | 0.2373 |
| 2025/26 | att_h | 0.3104 | 0.2837 |
| 2025/26 | def_h | 0.3713 | 0.3825 |
| 2025/26 | att_a | 0.2611 | 0.2788 |
| 2025/26 | def_a | 0.2590 | 0.2567 |

### 2. Std dev lambda_totale per partita (N=760, val+test)

- Variante A: **0.4151**
- Variante B: **0.4429**

### 3. Rapporto std_gol_reali / std_lambda

- std gol reali: 1.5959
- Variante A: **3.84**
- Variante B: **3.60**

### 4. Brier / LogLoss su O/U2.5 e GG (A vs B)

| Stagione | mercato | metric | A | B |
|---|---|---|---|---|
| 2024/25 | O/U2.5 | Brier | 0.2420 | 0.2454 |
| 2024/25 | O/U2.5 | LogLoss | 0.6772 | 0.6845 |
| 2024/25 | GG | Brier | 0.2472 | 0.2501 |
| 2024/25 | GG | LogLoss | 0.6877 | 0.6940 |
| 2025/26 | O/U2.5 | Brier | 0.2487 | 0.2509 |
| 2025/26 | O/U2.5 | LogLoss | 0.6913 | 0.6963 |
| 2025/26 | GG | Brier | 0.2461 | 0.2474 |
| 2025/26 | GG | LogLoss | 0.6854 | 0.6884 |


## LA LIGA

### 1. Std dev rapporti att/def TRA squadre — meta' stagione (15a giornata)

| Stagione | rapporto | std A (tutto storico) | std B (ult. 38) |
|---|---|---|---|
| 2024/25 | att_h | 0.3159 | 0.3338 |
| 2024/25 | def_h | 0.2628 | 0.2634 |
| 2024/25 | att_a | 0.3262 | 0.3293 |
| 2024/25 | def_a | 0.2779 | 0.2732 |
| 2025/26 | att_h | 0.3424 | 0.3798 |
| 2025/26 | def_h | 0.3399 | 0.3277 |
| 2025/26 | att_a | 0.3193 | 0.3691 |
| 2025/26 | def_a | 0.2689 | 0.2721 |

### 2. Std dev lambda_totale per partita (N=760, val+test)

- Variante A: **0.4980**
- Variante B: **0.5790**

### 3. Rapporto std_gol_reali / std_lambda

- std gol reali: 1.5685
- Variante A: **3.15**
- Variante B: **2.71**

### 4. Brier / LogLoss su O/U2.5 e GG (A vs B)

| Stagione | mercato | metric | A | B |
|---|---|---|---|---|
| 2024/25 | O/U2.5 | Brier | 0.2451 | 0.2458 |
| 2024/25 | O/U2.5 | LogLoss | 0.6831 | 0.6848 |
| 2024/25 | GG | Brier | 0.2546 | 0.2528 |
| 2024/25 | GG | LogLoss | 0.7030 | 0.6993 |
| 2025/26 | O/U2.5 | Brier | 0.2510 | 0.2484 |
| 2025/26 | O/U2.5 | LogLoss | 0.6953 | 0.6900 |
| 2025/26 | GG | Brier | 0.2541 | 0.2516 |
| 2025/26 | GG | LogLoss | 0.7022 | 0.6969 |


## BUNDESLIGA

### 1. Std dev rapporti att/def TRA squadre — meta' stagione (15a giornata)

| Stagione | rapporto | std A (tutto storico) | std B (ult. 38) |
|---|---|---|---|
| 2024/25 | att_h | 0.3289 | 0.3497 |
| 2024/25 | def_h | 0.3326 | 0.3375 |
| 2024/25 | att_a | 0.2882 | 0.2917 |
| 2024/25 | def_a | 0.2225 | 0.2247 |
| 2025/26 | att_h | 0.3138 | 0.3139 |
| 2025/26 | def_h | 0.3114 | 0.3228 |
| 2025/26 | att_a | 0.3210 | 0.3541 |
| 2025/26 | def_a | 0.2059 | 0.2031 |

### 2. Std dev lambda_totale per partita (N=612, val+test)

- Variante A: **0.6038**
- Variante B: **0.6313**

### 3. Rapporto std_gol_reali / std_lambda

- std gol reali: 1.7911
- Variante A: **2.97**
- Variante B: **2.84**

### 4. Brier / LogLoss su O/U2.5 e GG (A vs B)

| Stagione | mercato | metric | A | B |
|---|---|---|---|---|
| 2024/25 | O/U2.5 | Brier | 0.2282 | 0.2286 |
| 2024/25 | O/U2.5 | LogLoss | 0.6479 | 0.6486 |
| 2024/25 | GG | Brier | 0.2374 | 0.2378 |
| 2024/25 | GG | LogLoss | 0.7725 | 0.7733 |
| 2025/26 | O/U2.5 | Brier | 0.2372 | 0.2383 |
| 2025/26 | O/U2.5 | LogLoss | 0.6659 | 0.6682 |
| 2025/26 | GG | Brier | 0.2498 | 0.2509 |
| 2025/26 | GG | LogLoss | 0.7976 | 0.7999 |


## LIGUE 1

### 1. Std dev rapporti att/def TRA squadre — meta' stagione (15a giornata)

| Stagione | rapporto | std A (tutto storico) | std B (ult. 38) |
|---|---|---|---|
| 2024/25 | att_h | 0.3086 | 0.3081 |
| 2024/25 | def_h | 0.2205 | 0.2402 |
| 2024/25 | att_a | 0.3027 | 0.2854 |
| 2024/25 | def_a | 0.3897 | 0.3842 |
| 2025/26 | att_h | 0.3045 | 0.3340 |
| 2025/26 | def_h | 0.2167 | 0.2266 |
| 2025/26 | att_a | 0.2701 | 0.2821 |
| 2025/26 | def_a | 0.2986 | 0.2932 |

### 2. Std dev lambda_totale per partita (N=612, val+test)

- Variante A: **0.4436**
- Variante B: **0.4662**

### 3. Rapporto std_gol_reali / std_lambda

- std gol reali: 1.7614
- Variante A: **3.97**
- Variante B: **3.78**

### 4. Brier / LogLoss su O/U2.5 e GG (A vs B)

| Stagione | mercato | metric | A | B |
|---|---|---|---|---|
| 2024/25 | O/U2.5 | Brier | 0.2479 | 0.2479 |
| 2024/25 | O/U2.5 | LogLoss | 0.6893 | 0.6894 |
| 2024/25 | GG | Brier | 0.2497 | 0.2506 |
| 2024/25 | GG | LogLoss | 0.6917 | 0.6935 |
| 2025/26 | O/U2.5 | Brier | 0.2483 | 0.2509 |
| 2025/26 | O/U2.5 | LogLoss | 0.6904 | 0.6963 |
| 2025/26 | GG | Brier | 0.2505 | 0.2513 |
| 2025/26 | GG | LogLoss | 0.6945 | 0.6962 |
