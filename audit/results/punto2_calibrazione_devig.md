## 2. Punto 2 — calibrazione dei derivati rifatta con tre de-vig degli input

Generato da `audit/griglia_devig.py` il 2026-10-10T19:35:14Z · campione 3504 partite (B365, 2024/25 + 2025/26) · variante **A** (Dixon-Coles con ρ per partita) · stesse fasce e stessa regola di ingresso R4 di PR #59 · nessuna modifica a `SoccerMath/`, nessun `--write`, nessuna rete, nessuna chiave.

### 2.1 Campione e riproduzione del fit

| metodo di de-vig | partite | residuo massimo sui 4 vincoli | ρ mediano | λ mediano | μ mediano |
|---|---|---|---|---|---|
| proporzionale | 3504 | 1.5e-12 | -0,0781 | 1,478 | 1,168 |
| Shin | 3504 | 1.2e-12 | -0,0723 | 1,484 | 1,160 |
| potenza | 3504 | 2.0e-12 | -0,0663 | 1,485 | 1,158 |

**Controllo di parità con PR #59 (de-vig proporzionale).** Confrontate 14 celle (mercato, fascia) con la tabella del punto 4 di `audit/results/griglia_varianti.md`: tutti i conteggi n coincidono esattamente e il massimo scarto su f − p è **0.04 punti** (dovuto all'arrotondamento a un decimale del referto PR #59). Le colonne potenza e Shin sono calcolate con lo stesso codice e gli stessi semi: l'unica differenza è il de-vig degli input.

### 2.2 f − p con segno, per mercato, fascia e metodo

Esito valutato: quello con p più alta nella coppia evento/complemento (p ≥ 0,5). f − p in punti percentuali con IC 95% a blocchi (lega × stagione × data, 2000 repliche, seme 20261011).

#### Gol — esiti: No Gol / Gol

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 1661 | 58,68 % | 58,64 % | -0,0 pt [-2,5 pt; 2,3 pt] | sì |
| proporzionale | 0,65-0,75 | 126 | 67,37 % | 63,49 % | -3,9 pt [-12,6 pt; 5,1 pt] | sì |
| proporzionale | ≥0,75 | 0 | n/d | n/d | n/d | no |
| potenza | 0,55-0,65 | 1695 | 58,79 % | 58,58 % | -0,2 pt [-2,6 pt; 2,1 pt] | sì |
| potenza | 0,65-0,75 | 181 | 67,44 % | 60,22 % | -7,2 pt [-14,4 pt; 0,3 pt] | sì |
| potenza | ≥0,75 | 0 | n/d | n/d | n/d | no |
| Shin | 0,55-0,65 | 1684 | 58,76 % | 59,14 % | 0,4 pt [-1,9 pt; 2,7 pt] | sì |
| Shin | 0,65-0,75 | 155 | 67,45 % | 59,35 % | -8,1 pt [-15,5 pt; -0,0 pt] | sì |
| Shin | ≥0,75 | 0 | n/d | n/d | n/d | no |

| de-vig | esito R4 |
|---|---|
| proporzionale | CALIBRATO: entra nella lista |
| potenza | CALIBRATO: entra nella lista |
| Shin | non calibrato: resta fuori |

#### Over 1.5 — esiti: Under 1.5 / Over 1.5

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 146 | 62,17 % | 60,96 % | -1,2 pt [-9,7 pt; 6,7 pt] | sì |
| proporzionale | 0,65-0,75 | 1134 | 71,26 % | 71,25 % | -0,0 pt [-2,6 pt; 2,6 pt] | sì |
| proporzionale | ≥0,75 | 2222 | 81,16 % | 81,32 % | 0,2 pt [-1,5 pt; 1,7 pt] | sì |
| potenza | 0,55-0,65 | 180 | 61,92 % | 63,89 % | 2,0 pt [-5,5 pt; 8,8 pt] | sì |
| potenza | 0,65-0,75 | 1119 | 71,05 % | 71,22 % | 0,2 pt [-2,5 pt; 2,9 pt] | sì |
| potenza | ≥0,75 | 2195 | 81,54 % | 81,37 % | -0,2 pt [-1,9 pt; 1,4 pt] | sì |
| Shin | 0,55-0,65 | 163 | 61,93 % | 63,80 % | 1,9 pt [-5,8 pt; 9,3 pt] | sì |
| Shin | 0,65-0,75 | 1124 | 71,08 % | 71,17 % | 0,1 pt [-2,5 pt; 2,8 pt] | sì |
| Shin | ≥0,75 | 2210 | 81,41 % | 81,31 % | -0,1 pt [-1,7 pt; 1,5 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | CALIBRATO: entra nella lista |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

#### Over 3.5 — esiti: Under 3.5 / Over 3.5

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 802 | 60,16 % | 60,22 % | 0,1 pt [-3,6 pt; 3,5 pt] | sì |
| proporzionale | 0,65-0,75 | 1593 | 69,97 % | 69,93 % | -0,0 pt [-2,3 pt; 2,1 pt] | sì |
| proporzionale | ≥0,75 | 894 | 79,18 % | 81,10 % | 1,9 pt [-0,8 pt; 4,5 pt] | sì |
| potenza | 0,55-0,65 | 674 | 60,25 % | 61,72 % | 1,5 pt [-2,6 pt; 5,1 pt] | sì |
| potenza | 0,65-0,75 | 1581 | 69,78 % | 69,89 % | 0,1 pt [-2,1 pt; 2,2 pt] | sì |
| potenza | ≥0,75 | 903 | 79,67 % | 80,95 % | 1,3 pt [-1,4 pt; 3,9 pt] | sì |
| Shin | 0,55-0,65 | 821 | 59,53 % | 60,41 % | 0,9 pt [-2,7 pt; 4,3 pt] | sì |
| Shin | 0,65-0,75 | 1589 | 69,87 % | 69,86 % | -0,0 pt [-2,2 pt; 2,1 pt] | sì |
| Shin | ≥0,75 | 895 | 79,53 % | 81,12 % | 1,6 pt [-1,1 pt; 4,2 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | CALIBRATO: entra nella lista |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

#### 1X — esiti: 2 / 1X

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 775 | 60,08 % | 58,58 % | -1,5 pt [-4,9 pt; 1,9 pt] | sì |
| proporzionale | 0,65-0,75 | 938 | 70,07 % | 70,79 % | 0,7 pt [-2,3 pt; 3,6 pt] | sì |
| proporzionale | ≥0,75 | 1443 | 83,45 % | 84,55 % | 1,1 pt [-0,8 pt; 3,0 pt] | sì |
| potenza | 0,55-0,65 | 818 | 59,92 % | 58,92 % | -1,0 pt [-4,4 pt; 2,3 pt] | sì |
| potenza | 0,65-0,75 | 881 | 70,04 % | 70,37 % | 0,3 pt [-2,8 pt; 3,4 pt] | sì |
| potenza | ≥0,75 | 1511 | 83,96 % | 84,32 % | 0,4 pt [-1,5 pt; 2,3 pt] | sì |
| Shin | 0,55-0,65 | 804 | 59,98 % | 58,96 % | -1,0 pt [-4,4 pt; 2,3 pt] | sì |
| Shin | 0,65-0,75 | 896 | 70,07 % | 70,42 % | 0,4 pt [-2,7 pt; 3,3 pt] | sì |
| Shin | ≥0,75 | 1490 | 83,89 % | 84,36 % | 0,5 pt [-1,4 pt; 2,4 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | CALIBRATO: entra nella lista |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

#### X2 — esiti: 1 / X2

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 1222 | 59,87 % | 59,74 % | -0,1 pt [-2,8 pt; 2,6 pt] | sì |
| proporzionale | 0,65-0,75 | 916 | 69,64 % | 72,82 % | 3,2 pt [0,2 pt; 5,9 pt] | sì |
| proporzionale | ≥0,75 | 727 | 81,31 % | 85,28 % | 4,0 pt [1,5 pt; 6,5 pt] | sì |
| potenza | 0,55-0,65 | 1234 | 59,63 % | 59,00 % | -0,6 pt [-3,3 pt; 2,2 pt] | sì |
| potenza | 0,65-0,75 | 887 | 69,68 % | 71,59 % | 1,9 pt [-1,0 pt; 4,8 pt] | sì |
| potenza | ≥0,75 | 823 | 81,83 % | 83,84 % | 2,0 pt [-0,4 pt; 4,3 pt] | sì |
| Shin | 0,55-0,65 | 1225 | 59,71 % | 59,10 % | -0,6 pt [-3,3 pt; 2,2 pt] | sì |
| Shin | 0,65-0,75 | 914 | 69,76 % | 71,55 % | 1,8 pt [-1,1 pt; 4,7 pt] | sì |
| Shin | ≥0,75 | 775 | 81,83 % | 84,77 % | 2,9 pt [0,5 pt; 5,4 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | non calibrato: resta fuori |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

#### 12 — esiti: X / 12

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 2 | 63,76 % | 50,00 % | -13,8 pt [-63,4 pt; 35,8 pt] | no |
| proporzionale | 0,65-0,75 | 2039 | 71,97 % | 71,11 % | -0,9 pt [-2,8 pt; 1,1 pt] | sì |
| proporzionale | ≥0,75 | 1463 | 79,59 % | 79,97 % | 0,4 pt [-1,6 pt; 2,4 pt] | sì |
| potenza | 0,55-0,65 | 2 | 63,57 % | 50,00 % | -13,6 pt [-63,1 pt; 36,0 pt] | no |
| potenza | 0,65-0,75 | 1825 | 71,93 % | 70,79 % | -1,1 pt [-3,1 pt; 0,9 pt] | sì |
| potenza | ≥0,75 | 1677 | 79,88 % | 79,19 % | -0,7 pt [-2,6 pt; 1,2 pt] | sì |
| Shin | 0,55-0,65 | 2 | 63,62 % | 50,00 % | -13,6 pt [-63,2 pt; 36,0 pt] | no |
| Shin | 0,65-0,75 | 1877 | 71,93 % | 70,70 % | -1,2 pt [-3,2 pt; 0,8 pt] | sì |
| Shin | ≥0,75 | 1625 | 79,64 % | 79,57 % | -0,1 pt [-2,1 pt; 1,9 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | CALIBRATO: entra nella lista |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

#### 1+Over 1.5 — esiti: non (1 + Over 1,5) / 1+Over 1.5

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 959 | 59,83 % | 61,84 % | 2,0 pt [-1,1 pt; 4,9 pt] | sì |
| proporzionale | 0,65-0,75 | 1027 | 69,90 % | 72,93 % | 3,0 pt [0,4 pt; 5,9 pt] | sì |
| proporzionale | ≥0,75 | 1068 | 82,61 % | 85,30 % | 2,7 pt [0,5 pt; 4,7 pt] | sì |
| potenza | 0,55-0,65 | 926 | 60,00 % | 61,77 % | 1,8 pt [-1,3 pt; 4,9 pt] | sì |
| potenza | 0,65-0,75 | 1004 | 69,98 % | 72,21 % | 2,2 pt [-0,4 pt; 5,1 pt] | sì |
| potenza | ≥0,75 | 1110 | 83,02 % | 85,14 % | 2,1 pt [-0,0 pt; 4,2 pt] | sì |
| Shin | 0,55-0,65 | 927 | 59,90 % | 61,70 % | 1,8 pt [-1,3 pt; 4,9 pt] | sì |
| Shin | 0,65-0,75 | 1018 | 69,89 % | 72,50 % | 2,6 pt [-0,1 pt; 5,3 pt] | sì |
| Shin | ≥0,75 | 1098 | 82,89 % | 85,15 % | 2,3 pt [0,1 pt; 4,3 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | non calibrato: resta fuori |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

#### 2+Over 1.5 — esiti: non (2 + Over 1,5) / 2+Over 1.5

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 482 | 60,23 % | 60,58 % | 0,3 pt [-4,1 pt; 4,8 pt] | sì |
| proporzionale | 0,65-0,75 | 669 | 70,50 % | 69,36 % | -1,1 pt [-4,7 pt; 2,4 pt] | sì |
| proporzionale | ≥0,75 | 2116 | 85,10 % | 85,07 % | -0,0 pt [-1,5 pt; 1,4 pt] | sì |
| potenza | 0,55-0,65 | 470 | 60,13 % | 60,00 % | -0,1 pt [-4,7 pt; 4,2 pt] | sì |
| potenza | 0,65-0,75 | 659 | 70,43 % | 69,80 % | -0,6 pt [-4,2 pt; 2,9 pt] | sì |
| potenza | ≥0,75 | 2131 | 85,69 % | 84,89 % | -0,8 pt [-2,3 pt; 0,6 pt] | sì |
| Shin | 0,55-0,65 | 473 | 60,11 % | 60,47 % | 0,4 pt [-4,2 pt; 4,8 pt] | sì |
| Shin | 0,65-0,75 | 665 | 70,43 % | 69,62 % | -0,8 pt [-4,3 pt; 2,7 pt] | sì |
| Shin | ≥0,75 | 2125 | 85,54 % | 84,89 % | -0,6 pt [-2,1 pt; 0,8 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | CALIBRATO: entra nella lista |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

#### 1X+Over 1.5 — esiti: non (1X + Over 1,5) / 1X+Over 1.5

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 1389 | 59,70 % | 59,97 % | 0,3 pt [-2,3 pt; 3,0 pt] | sì |
| proporzionale | 0,65-0,75 | 846 | 69,50 % | 70,21 % | 0,7 pt [-2,6 pt; 3,9 pt] | sì |
| proporzionale | ≥0,75 | 368 | 79,70 % | 84,24 % | 4,5 pt [0,8 pt; 8,2 pt] | sì |
| potenza | 0,55-0,65 | 1341 | 59,69 % | 58,99 % | -0,7 pt [-3,3 pt; 2,0 pt] | sì |
| potenza | 0,65-0,75 | 844 | 69,45 % | 70,50 % | 1,0 pt [-2,2 pt; 4,2 pt] | sì |
| potenza | ≥0,75 | 467 | 80,28 % | 80,73 % | 0,4 pt [-3,2 pt; 4,1 pt] | sì |
| Shin | 0,55-0,65 | 1354 | 59,69 % | 59,23 % | -0,5 pt [-3,1 pt; 2,2 pt] | sì |
| Shin | 0,65-0,75 | 846 | 69,46 % | 70,33 % | 0,9 pt [-2,5 pt; 4,0 pt] | sì |
| Shin | ≥0,75 | 441 | 80,08 % | 81,63 % | 1,6 pt [-2,2 pt; 5,2 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | non calibrato: resta fuori |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

#### 1X+Under 3.5 — esiti: non (1X + Under 3,5) / 1X+Under 3.5

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 1633 | 59,21 % | 61,05 % | 1,8 pt [-0,5 pt; 4,2 pt] | sì |
| proporzionale | 0,65-0,75 | 430 | 68,80 % | 71,86 % | 3,1 pt [-1,1 pt; 7,3 pt] | sì |
| proporzionale | ≥0,75 | 122 | 79,81 % | 83,61 % | 3,8 pt [-3,3 pt; 10,2 pt] | sì |
| potenza | 0,55-0,65 | 1619 | 59,32 % | 59,98 % | 0,7 pt [-1,7 pt; 3,0 pt] | sì |
| potenza | 0,65-0,75 | 489 | 68,75 % | 69,33 % | 0,6 pt [-3,4 pt; 4,7 pt] | sì |
| potenza | ≥0,75 | 154 | 80,28 % | 83,77 % | 3,5 pt [-2,8 pt; 9,2 pt] | sì |
| Shin | 0,55-0,65 | 1623 | 59,31 % | 60,38 % | 1,1 pt [-1,2 pt; 3,5 pt] | sì |
| Shin | 0,65-0,75 | 476 | 68,80 % | 70,38 % | 1,6 pt [-2,4 pt; 5,7 pt] | sì |
| Shin | ≥0,75 | 140 | 80,19 % | 83,57 % | 3,4 pt [-3,4 pt; 9,3 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | CALIBRATO: entra nella lista |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

#### X2+Under 3.5 (extra) — esiti: non (X2 + Under 3,5) / X2+Under 3.5

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 1355 | 59,39 % | 58,82 % | -0,6 pt [-3,2 pt; 1,9 pt] | sì |
| proporzionale | 0,65-0,75 | 666 | 69,58 % | 72,67 % | 3,1 pt [-0,3 pt; 6,4 pt] | sì |
| proporzionale | ≥0,75 | 451 | 81,15 % | 82,93 % | 1,8 pt [-1,6 pt; 5,4 pt] | sì |
| potenza | 0,55-0,65 | 1321 | 59,40 % | 58,59 % | -0,8 pt [-3,5 pt; 1,8 pt] | sì |
| potenza | 0,65-0,75 | 672 | 69,37 % | 70,98 % | 1,6 pt [-1,8 pt; 5,0 pt] | sì |
| potenza | ≥0,75 | 536 | 81,80 % | 82,09 % | 0,3 pt [-2,9 pt; 3,7 pt] | sì |
| Shin | 0,55-0,65 | 1330 | 59,38 % | 58,72 % | -0,7 pt [-3,4 pt; 1,9 pt] | sì |
| Shin | 0,65-0,75 | 676 | 69,39 % | 71,60 % | 2,2 pt [-1,1 pt; 5,6 pt] | sì |
| Shin | ≥0,75 | 510 | 81,48 % | 82,55 % | 1,1 pt [-2,2 pt; 4,6 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | CALIBRATO: entra nella lista |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

### 2.3 Sintesi: lo scarto cambia col metodo di de-vig?

| mercato | f − p proporzionale (fasce con n ≥ 100) | f − p potenza | f − p Shin | l'esito R4 cambia col metodo |
|---|---|---|---|---|
| Gol | 0,55-0,65: -0,0 pt; 0,65-0,75: -3,9 pt | 0,55-0,65: -0,2 pt; 0,65-0,75: -7,2 pt | 0,55-0,65: 0,4 pt; 0,65-0,75: -8,1 pt | sì |
| Over 1.5 | 0,55-0,65: -1,2 pt; 0,65-0,75: -0,0 pt; ≥0,75: 0,2 pt | 0,55-0,65: 2,0 pt; 0,65-0,75: 0,2 pt; ≥0,75: -0,2 pt | 0,55-0,65: 1,9 pt; 0,65-0,75: 0,1 pt; ≥0,75: -0,1 pt | no |
| Over 3.5 | 0,55-0,65: 0,1 pt; 0,65-0,75: -0,0 pt; ≥0,75: 1,9 pt | 0,55-0,65: 1,5 pt; 0,65-0,75: 0,1 pt; ≥0,75: 1,3 pt | 0,55-0,65: 0,9 pt; 0,65-0,75: -0,0 pt; ≥0,75: 1,6 pt | no |
| 1X | 0,55-0,65: -1,5 pt; 0,65-0,75: 0,7 pt; ≥0,75: 1,1 pt | 0,55-0,65: -1,0 pt; 0,65-0,75: 0,3 pt; ≥0,75: 0,4 pt | 0,55-0,65: -1,0 pt; 0,65-0,75: 0,4 pt; ≥0,75: 0,5 pt | no |
| X2 | 0,55-0,65: -0,1 pt; 0,65-0,75: 3,2 pt; ≥0,75: 4,0 pt | 0,55-0,65: -0,6 pt; 0,65-0,75: 1,9 pt; ≥0,75: 2,0 pt | 0,55-0,65: -0,6 pt; 0,65-0,75: 1,8 pt; ≥0,75: 2,9 pt | sì |
| 12 | 0,65-0,75: -0,9 pt; ≥0,75: 0,4 pt | 0,65-0,75: -1,1 pt; ≥0,75: -0,7 pt | 0,65-0,75: -1,2 pt; ≥0,75: -0,1 pt | no |
| 1+Over 1.5 | 0,55-0,65: 2,0 pt; 0,65-0,75: 3,0 pt; ≥0,75: 2,7 pt | 0,55-0,65: 1,8 pt; 0,65-0,75: 2,2 pt; ≥0,75: 2,1 pt | 0,55-0,65: 1,8 pt; 0,65-0,75: 2,6 pt; ≥0,75: 2,3 pt | sì |
| 2+Over 1.5 | 0,55-0,65: 0,3 pt; 0,65-0,75: -1,1 pt; ≥0,75: -0,0 pt | 0,55-0,65: -0,1 pt; 0,65-0,75: -0,6 pt; ≥0,75: -0,8 pt | 0,55-0,65: 0,4 pt; 0,65-0,75: -0,8 pt; ≥0,75: -0,6 pt | no |
| 1X+Over 1.5 | 0,55-0,65: 0,3 pt; 0,65-0,75: 0,7 pt; ≥0,75: 4,5 pt | 0,55-0,65: -0,7 pt; 0,65-0,75: 1,0 pt; ≥0,75: 0,4 pt | 0,55-0,65: -0,5 pt; 0,65-0,75: 0,9 pt; ≥0,75: 1,6 pt | sì |
| 1X+Under 3.5 | 0,55-0,65: 1,8 pt; 0,65-0,75: 3,1 pt; ≥0,75: 3,8 pt | 0,55-0,65: 0,7 pt; 0,65-0,75: 0,6 pt; ≥0,75: 3,5 pt | 0,55-0,65: 1,1 pt; 0,65-0,75: 1,6 pt; ≥0,75: 3,4 pt | no |
| X2+Under 3.5 (extra) | 0,55-0,65: -0,6 pt; 0,65-0,75: 3,1 pt; ≥0,75: 1,8 pt | 0,55-0,65: -0,8 pt; 0,65-0,75: 1,6 pt; ≥0,75: 0,3 pt | 0,55-0,65: -0,7 pt; 0,65-0,75: 2,2 pt; ≥0,75: 1,1 pt | no |

#### 2.3.1 I tre mercati fuori lista: lo scarto cambia col metodo?

**X2.**
 proporzionale: 0,55-0,65: -0,1 pt [-2,8 pt; 2,6 pt], 0,65-0,75: 3,2 pt [0,2 pt; 5,9 pt], ≥0,75: 4,0 pt [1,5 pt; 6,5 pt]. Esito R4: non calibrato: resta fuori.
 potenza: 0,55-0,65: -0,6 pt [-3,3 pt; 2,2 pt], 0,65-0,75: 1,9 pt [-1,0 pt; 4,8 pt], ≥0,75: 2,0 pt [-0,4 pt; 4,3 pt]. Esito R4: CALIBRATO: entra nella lista.
 Shin: 0,55-0,65: -0,6 pt [-3,3 pt; 2,2 pt], 0,65-0,75: 1,8 pt [-1,1 pt; 4,7 pt], ≥0,75: 2,9 pt [0,5 pt; 5,4 pt]. Esito R4: CALIBRATO: entra nella lista.
  - fascia 0,55-0,65: lo scarto passa da -0,1 pt (proporzionale) a -0,6 pt (potenza) e -0,6 pt (Shin): resta dello stesso segno, ampiezza massima 0,5 pt.
  - fascia 0,65-0,75: lo scarto passa da 3,2 pt (proporzionale) a 1,9 pt (potenza) e 1,8 pt (Shin): resta dello stesso segno, ampiezza massima 1,4 pt.
  - fascia ≥0,75: lo scarto passa da 4,0 pt (proporzionale) a 2,0 pt (potenza) e 2,9 pt (Shin): resta dello stesso segno, ampiezza massima 2,0 pt.

**1+Over 1.5.**
 proporzionale: 0,55-0,65: 2,0 pt [-1,1 pt; 4,9 pt], 0,65-0,75: 3,0 pt [0,4 pt; 5,9 pt], ≥0,75: 2,7 pt [0,5 pt; 4,7 pt]. Esito R4: non calibrato: resta fuori.
 potenza: 0,55-0,65: 1,8 pt [-1,3 pt; 4,9 pt], 0,65-0,75: 2,2 pt [-0,4 pt; 5,1 pt], ≥0,75: 2,1 pt [-0,0 pt; 4,2 pt]. Esito R4: CALIBRATO: entra nella lista.
 Shin: 0,55-0,65: 1,8 pt [-1,3 pt; 4,9 pt], 0,65-0,75: 2,6 pt [-0,1 pt; 5,3 pt], ≥0,75: 2,3 pt [0,1 pt; 4,3 pt]. Esito R4: CALIBRATO: entra nella lista.
  - fascia 0,55-0,65: lo scarto passa da 2,0 pt (proporzionale) a 1,8 pt (potenza) e 1,8 pt (Shin): resta dello stesso segno, ampiezza massima 0,2 pt.
  - fascia 0,65-0,75: lo scarto passa da 3,0 pt (proporzionale) a 2,2 pt (potenza) e 2,6 pt (Shin): resta dello stesso segno, ampiezza massima 0,8 pt.
  - fascia ≥0,75: lo scarto passa da 2,7 pt (proporzionale) a 2,1 pt (potenza) e 2,3 pt (Shin): resta dello stesso segno, ampiezza massima 0,6 pt.

**1X+Over 1.5.**
 proporzionale: 0,55-0,65: 0,3 pt [-2,3 pt; 3,0 pt], 0,65-0,75: 0,7 pt [-2,6 pt; 3,9 pt], ≥0,75: 4,5 pt [0,8 pt; 8,2 pt]. Esito R4: non calibrato: resta fuori.
 potenza: 0,55-0,65: -0,7 pt [-3,3 pt; 2,0 pt], 0,65-0,75: 1,0 pt [-2,2 pt; 4,2 pt], ≥0,75: 0,4 pt [-3,2 pt; 4,1 pt]. Esito R4: CALIBRATO: entra nella lista.
 Shin: 0,55-0,65: -0,5 pt [-3,1 pt; 2,2 pt], 0,65-0,75: 0,9 pt [-2,5 pt; 4,0 pt], ≥0,75: 1,6 pt [-2,2 pt; 5,2 pt]. Esito R4: CALIBRATO: entra nella lista.
  - fascia 0,55-0,65: lo scarto passa da 0,3 pt (proporzionale) a -0,7 pt (potenza) e -0,5 pt (Shin): **cambia segno**.
  - fascia 0,65-0,75: lo scarto passa da 0,7 pt (proporzionale) a 1,0 pt (potenza) e 0,9 pt (Shin): resta dello stesso segno, ampiezza massima 0,3 pt.
  - fascia ≥0,75: lo scarto passa da 4,5 pt (proporzionale) a 0,4 pt (potenza) e 1,6 pt (Shin): resta dello stesso segno, ampiezza massima 4,1 pt.

### 2.4 Doppia chance: somma diretta delle 1X2 (senza griglia) contro la griglia

| de-vig | doppia chance | |Δ| mediana | |Δ| media | p95 | differenza MASSIMA |Δ| |
|---|---|---|---|---|---|
| proporzionale | 1X | 1.1e-16 | 2.3e-15 | 1.1e-15 | **7.4e-13** |
| proporzionale | X2 | 1.1e-16 | 2.0e-15 | 8.9e-16 | **7.3e-13** |
| proporzionale | 12 | 2.2e-16 | 4.0e-15 | 1.7e-15 | **1.5e-12** |
| potenza | 1X | 1.1e-16 | 1.9e-15 | 1.1e-15 | **9.9e-13** |
| potenza | X2 | 1.1e-16 | 1.4e-15 | 7.8e-16 | **1.0e-12** |
| potenza | 12 | 2.2e-16 | 3.1e-15 | 1.7e-15 | **2.0e-12** |
| Shin | 1X | 1.1e-16 | 1.7e-15 | 1.1e-15 | **6.8e-13** |
| Shin | X2 | 1.1e-16 | 1.3e-15 | 8.8e-16 | **5.4e-13** |
| Shin | 12 | 2.2e-16 | 2.7e-15 | 1.8e-15 | **1.2e-12** |

Δ = (p₁ + pX dalla terna de-vigata) − P(doppia chance) dalla griglia, in frazione di probabilità (1e-16 = una unità di macchina). La somma diretta è calcolata SENZA griglia: P(1X) = p₁ + pX, P(X2) = pX + p₂, P(12) = p₁ + p₂.

**Le due vie coincidono al livello di macchina, con ogni de-vig.** Non è un caso: il fit vincola la griglia a riprodurre ESATTAMENTE la terna 1X2 (3 parametri, 3 vincoli indipendenti, residuo massimo ~1e-12) e 1X, X2 e 12 sono unioni di celle 1X2 (1X = «1» ∪ «X», X2 = «X» ∪ «2», 12 = «1» ∪ «2»), quindi la loro probabilità è la somma delle tre di partenza qualunque cosa faccia il modello dentro le celle: la differenza massima è solo l'errore di arrotondamento in virgola mobile. La conseguenza pratica è che sulla doppia chance la griglia NON aggiunge nulla al de-vig: al contrario di Over 1,5, Over 3,5, Gol e delle combinazioni (1+Over 1,5, 1X+Over 1,5, 1X+Under 3,5), dove il valore dipende da come la massa è distribuita dentro la griglia.

### 2.5 Limiti

- Campione unico (3.504 partite B365, due stagioni): i conti per fascia non sono indipendenti fra mercati derivati dalla stessa griglia.
- Il de-vig e' applicato sia alla terna 1X2 sia all'Over/Under 2,5: i due effetti non sono separati in questa tabella.
- R4 non e' una misura di valore economico: dice solo se la frequenza osservata e' compatibile con la probabilita' dichiarata.
- «Non valutabile» (nessuna fascia con n ≥ 100) e' una lettura conservativa: il mercato resta fuori (regola di PR #59, non modificata).

