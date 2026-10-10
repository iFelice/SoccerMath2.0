## 1. Punto 1 — metodo di de-vig per la produzione (terna 1X2 Pinnacle)

Generato da `audit/devig_produzione.py` il 2026-10-10T19:17:34Z · campione primario 3536 partite (2022/23 + 2023/24) · conferma 2625 (2024/25 + 2025/26) · nessuna modifica a `SoccerMath/`, nessun `--write`, nessuna rete, nessuna chiave.

### 1.1 Copertura per lega e stagione (prima dei risultati)

| lega | stagione | partite con risultato | 1X2 + O/U 2,5 Pinnacle pre-chiusura completi | 1X2 + O/U 2,5 Pinnacle chiusura completi | senza Pinnacle pre-chiusura | date coperte da Pinnacle pre-chiusura |
|---|---|---|---|---|---|---|
| Serie A | 2022/23 | 380 | 380 | 380 | 0 | 13/08/2022 – 04/06/2023 |
| Serie A | 2023/24 | 380 | 380 | 380 | 0 | 19/08/2023 – 02/06/2024 |
| Premier League | 2022/23 | 380 | 379 | 379 | 1 | 05/08/2022 – 28/05/2023 |
| Premier League | 2023/24 | 380 | 372 | 373 | 8 | 11/08/2023 – 19/05/2024 |
| La Liga | 2022/23 | 380 | 380 | 380 | 0 | 12/08/2022 – 04/06/2023 |
| La Liga | 2023/24 | 380 | 379 | 380 | 1 | 11/08/2023 – 26/05/2024 |
| Bundesliga | 2022/23 | 306 | 292 | 294 | 14 | 05/08/2022 – 27/05/2023 |
| Bundesliga | 2023/24 | 306 | 292 | 293 | 14 | 18/08/2023 – 18/05/2024 |
| Ligue 1 | 2022/23 | 380 | 376 | 378 | 4 | 05/08/2022 – 03/06/2023 |
| Ligue 1 | 2023/24 | 306 | 306 | 306 | 0 | 11/08/2023 – 19/05/2024 |
| Serie A | 2024/25 | 380 | 379 | 380 | 1 | 17/08/2024 – 25/05/2025 |
| Serie A | 2025/26 | 380 | 200 | 198 | 180 | 23/08/2025 – 15/01/2026 |
| Premier League | 2024/25 | 380 | 377 | 377 | 3 | 16/08/2024 – 25/05/2025 |
| Premier League | 2025/26 | 380 | 210 | 210 | 170 | 15/08/2025 – 08/01/2026 |
| La Liga | 2024/25 | 380 | 378 | 378 | 2 | 15/08/2024 – 25/05/2025 |
| La Liga | 2025/26 | 380 | 188 | 188 | 192 | 15/08/2025 – 12/01/2026 |
| Bundesliga | 2024/25 | 306 | 297 | 297 | 9 | 23/08/2024 – 17/05/2025 |
| Bundesliga | 2025/26 | 306 | 142 | 142 | 164 | 22/08/2025 – 15/01/2026 |
| Ligue 1 | 2024/25 | 306 | 304 | 304 | 2 | 16/08/2024 – 17/05/2025 |
| Ligue 1 | 2025/26 | 306 | 152 | 152 | 154 | 15/08/2025 – 04/01/2026 |

Conteggi dopo la deduplicazione su lega × data × casa × trasferta e dopo aver scartato le partite senza risultato. Le colonne Pinnacle (`PSH/PSD/PSA`, `P>2.5/P<2.5`, `PSCH/PSCD/PSCA`, `PC>2.5/PC<2.5`) sono presenti nell'intestazione di tutti i 20 CSV (2022-2025, 5 leghe): nessuna stagione e' stata esclusa per mancanza delle colonne. La copertura NON e' completa in tutte le celle: sotto il 95 % di righe compilate — Serie A 2025/26: 200/380 (52,6 %), ultima data coperta 15/01/2026; Premier League 2025/26: 210/380 (55,3 %), ultima data coperta 08/01/2026; La Liga 2025/26: 188/380 (49,5 %), ultima data coperta 12/01/2026; Bundesliga 2025/26: 142/306 (46,4 %), ultima data coperta 15/01/2026; Ligue 1 2025/26: 152/306 (49,7 %), ultima data coperta 04/01/2026. Dove Pinnacle manca la partita esce dal campione: e' una proprieta' del dato scaricato, non una scelta di questo audit.

### 1.2 Verifica: la griglia riproduce la terna de-vigata

Su 500 partite estratte a caso dal campione primario (seme 20261023) il fit Dixon-Coles su 1X2 + Over 2,5 restituisce una griglia la cui terna 1X2 differisce dalla terna de-vigata in ingresso per al piu' **5.56e-13** (residuo massimo sui 4 vincoli: 5.56e-13). Il sistema ha 3 parametri e 3 vincoli indipendenti, quindi la metrica del punto 1 puo' essere calcolata direttamente sulle probabilita' de-vigate: la griglia non aggiunge e non toglie nulla.

### 1.3 ΔLogLoss e ΔBrier appaiati rispetto al proporzionale

**campione PRIMARIO (2022/23 + 2023/24) — Pinnacle di pre-chiusura — n = 3536** (LogLoss proporzionale 0,97053, Brier proporzionale 0,57748)

| confronto (metodo − proporzionale) | metrica | media per partita | IC 95% a blocchi | lettura |
|---|---|---|---|---|
| potenza | ΔLogLoss | -0,000517 | [-0,001106; 0,000091] | IC contiene 0 |
| potenza (ΔBrier) | ΔBrier | -0,000252 | [-0,000619; 0,000114] | IC contiene 0 |
| Shin | ΔLogLoss | -0,000498 | [-0,000920; -0,000084] | IC tutta < 0 |
| Shin (ΔBrier) | ΔBrier | -0,000224 | [-0,000470; 0,000025] | IC contiene 0 |
| Shin-potenza | ΔLogLoss | 0,000019 | [-0,000204; 0,000221] | IC contiene 0 |

**campione di CONFERMA (2024/25 + 2025/26) — Pinnacle di pre-chiusura — n = 2625** (LogLoss proporzionale 0,96837, Brier proporzionale 0,57616)

| confronto (metodo − proporzionale) | metrica | media per partita | IC 95% a blocchi | lettura |
|---|---|---|---|---|
| potenza | ΔLogLoss | -0,000794 | [-0,001596; 0,000021] | IC contiene 0 |
| potenza (ΔBrier) | ΔBrier | -0,000345 | [-0,000831; 0,000128] | IC contiene 0 |
| Shin | ΔLogLoss | -0,000652 | [-0,001216; -0,000084] | IC tutta < 0 |
| Shin (ΔBrier) | ΔBrier | -0,000281 | [-0,000608; 0,000032] | IC contiene 0 |
| Shin-potenza | ΔLogLoss | 0,000142 | [-0,000134; 0,000408] | IC contiene 0 |

Negativo = meglio del proporzionale. Blocchi = lega × stagione × data; 2000 repliche; seme 20261020.

### 1.4 Sensibilità: Pinnacle di chiusura

| campione (chiusura) | metodo | n | ΔLogLoss medio | IC 95% | lettura |
|---|---|---|---|---|---|
| primario (2022/23 + 2023/24) | potenza | 3543 | -0,000512 | [-0,001061; 0,000050] | IC contiene 0 |
| primario (2022/23 + 2023/24) | Shin | 3543 | -0,000485 | [-0,000860; -0,000110] | IC tutta < 0 |
| conferma (2024/25 + 2025/26) | potenza | 2623 | -0,000721 | [-0,001402; -0,000006] | IC tutta < 0 |
| conferma (2024/25 + 2025/26) | Shin | 2623 | -0,000558 | [-0,001043; -0,000052] | IC tutta < 0 |

### 1.5 Calibrazione dell'esito più probabile (argmax)

**PRIMARIO (2022/23 + 2023/24) — n = 3536**

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] |
|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 693 | 59,46 % | 60,89 % | 1,44 pt [-2,46 pt; 5,15 pt] |
| proporzionale | 0,65-0,75 | 443 | 69,56 % | 73,81 % | 4,26 pt [0,23 pt; 8,40 pt] |
| proporzionale | ≥0,75 | 178 | 79,95 % | 79,78 % | -0,17 pt [-5,80 pt; 5,47 pt] |
| potenza | 0,55-0,65 | 708 | 59,42 % | 60,45 % | 1,03 pt [-2,66 pt; 4,65 pt] |
| potenza | 0,65-0,75 | 446 | 69,61 % | 71,08 % | 1,47 pt [-2,69 pt; 5,63 pt] |
| potenza | ≥0,75 | 231 | 80,52 % | 80,52 % | 0,00 pt [-5,16 pt; 5,17 pt] |
| Shin | 0,55-0,65 | 709 | 59,48 % | 60,51 % | 1,03 pt [-2,64 pt; 4,67 pt] |
| Shin | 0,65-0,75 | 443 | 69,66 % | 72,23 % | 2,57 pt [-1,65 pt; 6,71 pt] |
| Shin | ≥0,75 | 212 | 80,32 % | 80,19 % | -0,13 pt [-5,46 pt; 5,11 pt] |

**CONFERMA (2024/25 + 2025/26) — n = 2625**

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] |
|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 516 | 59,40 % | 59,30 % | -0,10 pt [-4,41 pt; 4,06 pt] |
| proporzionale | 0,65-0,75 | 334 | 69,63 % | 74,85 % | 5,22 pt [0,46 pt; 9,77 pt] |
| proporzionale | ≥0,75 | 141 | 79,22 % | 83,69 % | 4,47 pt [-2,43 pt; 10,66 pt] |
| potenza | 0,55-0,65 | 519 | 59,36 % | 58,96 % | -0,40 pt [-4,83 pt; 3,80 pt] |
| potenza | 0,65-0,75 | 349 | 69,79 % | 70,77 % | 0,98 pt [-3,74 pt; 5,64 pt] |
| potenza | ≥0,75 | 179 | 80,31 % | 82,68 % | 2,37 pt [-3,59 pt; 7,94 pt] |
| Shin | 0,55-0,65 | 513 | 59,39 % | 59,26 % | -0,13 pt [-4,49 pt; 4,01 pt] |
| Shin | 0,65-0,75 | 346 | 69,68 % | 71,68 % | 1,99 pt [-2,60 pt; 6,45 pt] |
| Shin | ≥0,75 | 168 | 79,86 % | 83,33 % | 3,47 pt [-2,73 pt; 9,33 pt] |

### 1.6 Esito della regola dichiarata (R1.7)

| condizione | esito |
|---|---|
| (a1) IC 95% di ΔLogLoss(potenza − proporzionale) tutta < 0 sul primario | NO (IC [-0,001106; 0,000091]) |
| (a2) stima puntuale di ΔLogLoss(potenza − proporzionale) ≤ 0 sulla conferma | SÌ (puntuale -0,000794) |
| (b) IC 95% di ΔLogLoss(Shin − potenza) tutta < 0 sul primario | NO (IC [-0,000204; 0,000221]) |

**Proposta: proporzionale.** (Solo proposta: nessuna modifica al codice di produzione in questo audit.)

### 1.7 Descrittivo: soglia p ≥ 0,55 di topmix_mercato_v3 sulle 3.504 partite

Campione delle 3.504 partite di PR #59 (B365, 2024/25 + 2025/26). Scelta = argmax della terna de-vigata (primo massimo in ordine 1, X, 2) con p ≥ 0,55, come in `app.seleziona_riga_top_mix_mercato`. Nessuna regola di decisione.

#### 1.7.1 Sorgente B365 (definisce il campione)

| de-vig | scelte (p ≥ 0,55) | hit rate | cambia esito (su 3504) | cambia esito restando sopra soglia | entra | esce |
|---|---|---|---|---|---|---|
| proporzionale | 1302 | 67,51 % | — | — | — | — |
| potenza | 1465 | 66,28 % | 0 / 3504 | 0 | 163 (hit 56,44 %) | 0 (hit n/d) |
| Shin | 1407 | 66,45 % | 0 / 3504 | 0 | 105 (hit 53,33 %) | 0 (hit n/d) |

Su 3504 partite (attese 3.504 di PR #59). «Cambia esito» e' contato su tutte le partite del campione; «cambia esito restando sopra soglia» solo fra le scelte ammesse da entrambi i metodi. Tra parentesi l'hit rate delle scelte che entrano/escono.

**Perche' «cambia esito» e' 0 con ogni metodo:** proporzionale, potenza e Shin sono trasformazioni *monotone crescenti* di π_i = 1/q_i (la potenza con esponente k ≥ 1, Shin con z < 1), quindi l'argmax della terna e' lo stesso per costruzione: nessuna scelta puo' cambiare esito. Puo' cambiare solo il livello di p, e qui il livello sale (potenza e Shin tolgono meno al favorito del proporzionale): entrano solo nuove scelte, nessuna esce.

**Controllo di parita' con PR #49/PR #59:** con il de-vig proporzionale le scelte di mercato sono 1302 con hit rate 67,51 %: coincidono con i 1302 / 67,5 % del replay `topmix_mercato_v3`.

#### 1.7.2 Sensibilità: Pinnacle di pre-chiusura (stesse partite, dove disponibile)

| de-vig | scelte (p ≥ 0,55) | hit rate | cambia esito | cambia esito restando sopra soglia | entra | esce |
|---|---|---|---|---|---|---|
| proporzionale | 991 | 68,01 % | — | — | — | — |
| potenza | 1047 | 66,95 % | 0 / 2625 | 0 | 56 (hit 48,21 %) | 0 (hit n/d) |
| Shin | 1027 | 67,38 % | 0 / 2625 | 0 | 36 (hit 50,00 %) | 0 (hit n/d) |

Stesse partite, filtrate su quelle con terna Pinnacle di pre-chiusura e O/U 2,5 Pinnacle completi: 2625 su 3504. La colonna «cambia esito» e' calcolata su questo sottoinsieme.

