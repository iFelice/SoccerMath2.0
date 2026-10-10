# Griglia implicita: varianti, tau, calibrazione e stima bet365 (audit, sola lettura)

Generato da `audit/griglia_varianti.py` il 2026-10-10T17:37:17Z · campione principale 3504 partite · sottocampione Pinnacle 2623 · nessuna modifica a `SoccerMath/`, nessun `--write`, nessuna chiamata di rete, nessuna chiave.

## 0. Regole dichiarate (scritte prima dei numeri)

Le regole sono nel codice (`audit/griglia_varianti.py`, docstring) e nel referto qui sotto; non sono state
modificate dopo aver visto i numeri.

- **R2 (tau).** Confronto cella per cella tra la produzione (`SoccerMath/models/dixon_coles.tau_correction`),
  la formula di Dixon & Coles (1997) come citata in arXiv:2103.07272 eq. (2) con x = gol casa e λ = media casa,
  e la convenzione di penaltyblog 1.13.1. Se la produzione fosse invertita, non si corregge: si misura l'effetto.
- **R3 (scelta della variante).** Metrica: Brier binario per partita sul mercato Gol (No Gol identico).
  d = Brier(X) − Brier(Y); d < 0 ⇒ X migliore. Bootstrap a blocchi lega × stagione × data, 2000 repliche,
  seme 20261010, IC 95% percentile. Passo 1: adottare A solo se l'IC 95% di A−B è interamente sotto zero.
  Passo 2 (altrimenti): adottare B solo se l'IC 95% di B−C è interamente sotto zero. Passo 3 (altrimenti): C.
  Lettura del brief: "altrimenti B" al passo 1 = B è la candidata al posto di A, poi confrontata con C.
  Il sottocampione Pinnacle applica la stessa procedura: è sensibilità, non decide.
- **R4 (calibrazione).** Per ogni coppia evento/complemento e partita si valuta l'esito con p più alta (p ≥ 0,5).
  Fasce di p: [0,55-0,65), [0,65-0,75), ≥ 0,75. IC 95% di f − p con bootstrap a blocchi, 2000 repliche,
  seme 20261011. **Regola:** un mercato entra nella lista delle giocate se in *ogni* fascia con n ≥ 100 l'IC
  di f − p contiene lo zero *oppure* |f − p| ≤ 0,03. Se nessuna fascia ha n ≥ 100, il mercato è
  «non valutabile» e resta fuori (lettura conservativa, dichiarata qui).
- **R5 (punto 5).** Descrittivo, senza regola di decisione. IC 95% bootstrap a blocchi, seme 20261012.
- **R6 (punto 6).** Descrittivo. Stima come PR #58 (R = q_B365 / p_depurata_Pinnacle di apertura, stimato in
  2024/25 per lega × tipo × fascia di quota equa Pinnacle; testato su 2025/26). Errore relativo
  |q̂/q − 1| e assoluto in punti di quota. Fasce per **quota reale** bet365.
- **Derivati (punti 3–4).** Gol/No Gol; Over/Under 1,5 e 3,5; doppia chance 1X, X2, 12; 1+Over 1,5; 2+Over 1,5;
  1X+Over 1,5; 1X+Under 3,5 (elenco del brief). X2+Under 3,5 (in PR #58, non nel brief) è calcolato e marcato
  «extra»; non decide nulla. 1X2 e O/U 2,5 restano fuori.

## 1. Campione e controlli di riproduzione

| lega | stagione | partite nel campione |
|---|---|---|
| Serie A | 2024/25 | 380 |
| Serie A | 2025/26 | 380 |
| Premier League | 2024/25 | 380 |
| Premier League | 2025/26 | 380 |
| La Liga | 2024/25 | 380 |
| La Liga | 2025/26 | 380 |
| Bundesliga | 2024/25 | 306 |
| Bundesliga | 2025/26 | 306 |
| Ligue 1 | 2024/25 | 306 |
| Ligue 1 | 2025/26 | 306 |

| variante | residuo massimo sulle 4 quote (1, X, 2, O 2,5) | partite con residuo > 1e-6 |
|---|---|---|
| A (DC, rho per partita) | max 1.5e-12 | 0 |
| B (DC, rho fisso) | max 0,0491 · mediana 0,0093 | 3503 |
| C (Poisson, rho = 0) | max 0,0610 · mediana 0,0157 | 3504 |

Riferimento PR #58: A riproduce le quote con residuo ≤ 1e-12 (qui: max 1.5e-12); C ha residuo massimo 0,061 nel referto PR #58 (qui: max 0,061).

## 2. Punto 2 — convenzione tau (produzione vs articolo vs penaltyblog)

Esempio numerico: λ = 1,0, μ = 1,5, ρ = −0,10 (λ e μ sono i gol attesi di casa e trasferta).

| cella (x gol casa, y gol trasferta) | produzione `tau_correction` | Dixon & Coles 1997 (eq. 2 come citata) | penaltyblog 1.13.1 (letta dal sorgente) |
|---|---|---|---|
| (0,0) | 1,1500 | 1,1500 | 1,1500 |
| (0,1) | 0,9000 | 0,9000 | 0,8500 |
| (1,0) | 0,8500 | 0,8500 | 0,9000 |
| (1,1) | 1,1000 | 1,1000 | 1,1000 |

Produzione = articolo: **SÌ** · produzione = penaltyblog: **NO**.

**Conclusione:** la produzione coincide con l'articolo; è penaltyblog a usare λ e μ scambiati nelle celle (0,1) e (1,0). La produzione **non** è invertita e non viene modificata. Per quantificare la differenza che la convenzione penaltyblog produrrebbe sui derivati (scenario NON in produzione), con i parametri di A per partita:

| evento | max abs Δ prob. | mediana abs Δ |
|---|---|---|
| Gol | 0,01290 | 0,000670 |
| Over 1.5 | 0,02344 | 0,000970 |
| Over 3.5 | 0,01479 | 0,000380 |
| 1X | 0,01601 | 0,002674 |
| X2 | 0,02085 | 0,002835 |
| 12 | 0,00484 | 0,000318 |
| 1+Over 1.5 | 0,02063 | 0,000352 |
| 2+Over 1.5 | 0,01227 | 0,000239 |
| 1X+Over 1.5 | 0,02245 | 0,000615 |
| 1X+Under 3.5 | 0,02496 | 0,002935 |
| X2+Under 3.5 | 0,01935 | 0,002810 |

## 3. Punto 3 — ρ per partita e confronto delle varianti

### 3.1 Distribuzione di ρ in A (campione principale)

| percentile | p1 | p5 | p25 | p50 | p75 | p95 | p99 |
|---|---|---|---|---|---|---|---|
| ρ | -0,181 | -0,146 | -0,106 | -0,078 | -0,048 | 0,020 | 0,090 |

Partite al bordo dei limiti (|ρ| ≥ 0,49, con limiti ±0,5 come in `griglia_core`): **0,00 %**. Partite con almeno una cella tau negativa (clip a 0 attivo): **0,00 %**. ρ mediano 2024/25 = -0,081, 2025/26 = -0,076; ρ fisso applicato da B al 2025/26 = **-0,0811**.

### 3.2 Brier appaiato su Gol (regola R3)

| confronto | ΔBrier (X − Y) per partita | IC 95% a blocchi | esito |
|---|---|---|---|
| A − B (Gol) | -0,00039 | [-0,00076; -0,00004] | X migliore (IC < 0) |
| B − C (Gol) | -0,00026 | [-0,00055; 0,00004] | nessuna differenza dimostrata |

**Decisione R3 (campione principale): variante A.**

### 3.3 Tutti i derivati: Brier(A) − Brier(B) e Brier(A) − Brier(C)

| evento (primario) | A − B: media [IC 95%] | A − C: media [IC 95%] |
|---|---|---|
| Gol | -0,00039 [-0,00076; -0,00004] | -0,00065 [-0,00112; -0,00019] |
| Over 1.5 | -0,00010 [-0,00041; 0,00021] | -0,00015 [-0,00055; 0,00027] |
| Over 3.5 | 0,00000 [-0,00013; 0,00013] | 0,00003 [-0,00013; 0,00019] |
| 1X | 0,00012 [-0,00014; 0,00036] | -0,00000 [-0,00031; 0,00030] |
| X2 | -0,00021 [-0,00041; -0,00000] | -0,00027 [-0,00052; -0,00001] |
| 12 | -0,00014 [-0,00060; 0,00029] | -0,00036 [-0,00092; 0,00019] |
| 1+Over 1.5 | 0,00009 [-0,00002; 0,00020] | 0,00007 [-0,00007; 0,00021] |
| 2+Over 1.5 | -0,00004 [-0,00012; 0,00004] | -0,00001 [-0,00011; 0,00008] |
| 1X+Over 1.5 | 0,00011 [-0,00024; 0,00044] | -0,00007 [-0,00052; 0,00038] |
| 1X+Under 3.5 | 0,00009 [-0,00007; 0,00024] | 0,00006 [-0,00014; 0,00025] |
| X2+Under 3.5 (extra) | -0,00006 [-0,00021; 0,00009] | -0,00010 [-0,00029; 0,00009] |

Negativo = A migliore. Il Brier di un evento e del suo complemento è identico.

### 3.4 Sensibilità: sottocampione Pinnacle di chiusura

| confronto | ΔBrier (X − Y) | IC 95% | esito |
|---|---|---|---|
| A − B (Gol) | -0,00065 | [-0,00119; -0,00011] | X migliore (IC < 0) |
| B − C (Gol) | -0,00011 | [-0,00046; 0,00023] | nessuna differenza dimostrata |

Decisione sul sottocampione Pinnacle (sola sensibilità): variante A. Concorda con il campione principale.

## 4. Punto 4 — calibrazione dei derivati, variante A

Per ogni coppia evento/complemento: esito con p più alta per partita (p ≥ 0,5). Fasce [0,55-0,65), [0,65-0,75), ≥ 0,75. f − p con IC 95% a blocchi (R4).

### Gol — esiti: No Gol / Gol

| fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|
| 0,55-0,65 | 1661 | 58,68 % | 58,64 % | -0,0 pt [-2,5 pt; 2,3 pt] | sì |
| 0,65-0,75 | 126 | 67,37 % | 63,49 % | -3,9 pt [-12,6 pt; 5,1 pt] | sì |
| ≥0,75 | 0 | n/d | n/d | n/d | n/d |

**Esito R4: CALIBRATO: entra nella lista.**

### Over 1.5 — esiti: Under 1.5 / Over 1.5

| fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|
| 0,55-0,65 | 146 | 62,17 % | 60,96 % | -1,2 pt [-9,7 pt; 6,7 pt] | sì |
| 0,65-0,75 | 1134 | 71,26 % | 71,25 % | -0,0 pt [-2,6 pt; 2,6 pt] | sì |
| ≥0,75 | 2222 | 81,16 % | 81,32 % | 0,2 pt [-1,5 pt; 1,7 pt] | sì |

**Esito R4: CALIBRATO: entra nella lista.**

### Over 3.5 — esiti: Under 3.5 / Over 3.5

| fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|
| 0,55-0,65 | 802 | 60,16 % | 60,22 % | 0,1 pt [-3,6 pt; 3,5 pt] | sì |
| 0,65-0,75 | 1593 | 69,97 % | 69,93 % | -0,0 pt [-2,3 pt; 2,1 pt] | sì |
| ≥0,75 | 894 | 79,18 % | 81,10 % | 1,9 pt [-0,8 pt; 4,5 pt] | sì |

**Esito R4: CALIBRATO: entra nella lista.**

### 1X — esiti: 2 / 1X

| fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|
| 0,55-0,65 | 775 | 60,08 % | 58,58 % | -1,5 pt [-4,9 pt; 1,9 pt] | sì |
| 0,65-0,75 | 938 | 70,07 % | 70,79 % | 0,7 pt [-2,3 pt; 3,6 pt] | sì |
| ≥0,75 | 1443 | 83,45 % | 84,55 % | 1,1 pt [-0,8 pt; 3,0 pt] | sì |

**Esito R4: CALIBRATO: entra nella lista.**

### X2 — esiti: 1 / X2

| fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|
| 0,55-0,65 | 1222 | 59,87 % | 59,74 % | -0,1 pt [-2,8 pt; 2,6 pt] | sì |
| 0,65-0,75 | 916 | 69,64 % | 72,82 % | 3,2 pt [0,2 pt; 5,9 pt] | sì |
| ≥0,75 | 727 | 81,31 % | 85,28 % | 4,0 pt [1,5 pt; 6,5 pt] | sì |

**Esito R4: non calibrato: resta fuori.**

### 12 — esiti: X / 12

| fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|
| 0,55-0,65 | 2 | 63,76 % | 50,00 % | -13,8 pt [-63,4 pt; 35,8 pt] | no |
| 0,65-0,75 | 2039 | 71,97 % | 71,11 % | -0,9 pt [-2,8 pt; 1,1 pt] | sì |
| ≥0,75 | 1463 | 79,59 % | 79,97 % | 0,4 pt [-1,6 pt; 2,4 pt] | sì |

**Esito R4: CALIBRATO: entra nella lista.**

### 1+Over 1.5 — esiti: non (1 + Over 1,5) / 1+Over 1.5

| fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|
| 0,55-0,65 | 959 | 59,83 % | 61,84 % | 2,0 pt [-1,1 pt; 4,9 pt] | sì |
| 0,65-0,75 | 1027 | 69,90 % | 72,93 % | 3,0 pt [0,4 pt; 5,9 pt] | sì |
| ≥0,75 | 1068 | 82,61 % | 85,30 % | 2,7 pt [0,5 pt; 4,7 pt] | sì |

**Esito R4: non calibrato: resta fuori.**

### 2+Over 1.5 — esiti: non (2 + Over 1,5) / 2+Over 1.5

| fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|
| 0,55-0,65 | 482 | 60,23 % | 60,58 % | 0,3 pt [-4,1 pt; 4,8 pt] | sì |
| 0,65-0,75 | 669 | 70,50 % | 69,36 % | -1,1 pt [-4,7 pt; 2,4 pt] | sì |
| ≥0,75 | 2116 | 85,10 % | 85,07 % | -0,0 pt [-1,5 pt; 1,4 pt] | sì |

**Esito R4: CALIBRATO: entra nella lista.**

### 1X+Over 1.5 — esiti: non (1X + Over 1,5) / 1X+Over 1.5

| fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|
| 0,55-0,65 | 1389 | 59,70 % | 59,97 % | 0,3 pt [-2,3 pt; 3,0 pt] | sì |
| 0,65-0,75 | 846 | 69,50 % | 70,21 % | 0,7 pt [-2,6 pt; 3,9 pt] | sì |
| ≥0,75 | 368 | 79,70 % | 84,24 % | 4,5 pt [0,8 pt; 8,2 pt] | sì |

**Esito R4: non calibrato: resta fuori.**

### 1X+Under 3.5 — esiti: non (1X + Under 3,5) / 1X+Under 3.5

| fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|
| 0,55-0,65 | 1633 | 59,21 % | 61,05 % | 1,8 pt [-0,5 pt; 4,2 pt] | sì |
| 0,65-0,75 | 430 | 68,80 % | 71,86 % | 3,1 pt [-1,1 pt; 7,3 pt] | sì |
| ≥0,75 | 122 | 79,81 % | 83,61 % | 3,8 pt [-3,3 pt; 10,2 pt] | sì |

**Esito R4: CALIBRATO: entra nella lista.**

### X2+Under 3.5 (extra) — esiti: non (X2 + Under 3,5) / X2+Under 3.5

| fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|
| 0,55-0,65 | 1355 | 59,39 % | 58,82 % | -0,6 pt [-3,2 pt; 1,9 pt] | sì |
| 0,65-0,75 | 666 | 69,58 % | 72,67 % | 3,1 pt [-0,3 pt; 6,4 pt] | sì |
| ≥0,75 | 451 | 81,15 % | 82,93 % | 1,8 pt [-1,6 pt; 5,4 pt] | sì |

**Esito R4: CALIBRATO: entra nella lista.**

### Lista delle giocate (R4)

Entrano nella lista (elenco del brief): Gol, Over 1.5, Over 3.5, 1X, 12, 2+Over 1.5, 1X+Under 3.5.

Extra fuori elenco (PR #58, non decide nulla): X2+Under 3.5.

## 5. Punto 5 — fascia alta su 1X2 (p ≥ 0,65), IC 95%

Stessa tabella con tre metodi di de-vig su B365 (campione principale, 3504) e con il confronto Pinnacle proporzionale vs B365 sullo stesso sottocampione (2623).

| campione / bookmaker | de-vig | esito | n | p media | frequenza | f − p [IC 95%] |
|---|---|---|---|---|---|---|
| B365 (3504) | proporzionale | 1 | 500 | 72,92 % | 77,80 % | 4,9 pt [1,2 pt; 8,6 pt] |
| B365 (3504) | proporzionale | X | 0 | n/d | n/d | n/d |
| B365 (3504) | proporzionale | 2 | 122 | 70,65 % | 76,23 % | 5,6 pt [-2,2 pt; 12,7 pt] |
| B365 (3504) | Shin | 1 | 547 | 73,82 % | 75,69 % | 1,9 pt [-1,7 pt; 5,5 pt] |
| B365 (3504) | Shin | X | 0 | n/d | n/d | n/d |
| B365 (3504) | Shin | 2 | 129 | 71,87 % | 75,97 % | 4,1 pt [-3,3 pt; 11,1 pt] |
| B365 (3504) | potenza | 1 | 571 | 74,28 % | 75,31 % | 1,0 pt [-2,4 pt; 4,7 pt] |
| B365 (3504) | potenza | X | 0 | n/d | n/d | n/d |
| B365 (3504) | potenza | 2 | 136 | 72,28 % | 76,47 % | 4,2 pt [-3,3 pt; 11,2 pt] |
| B365 (2623) | proporzionale | 1 | 369 | 72,30 % | 78,59 % | 6,3 pt [2,0 pt; 10,6 pt] |
| B365 (2623) | proporzionale | X | 0 | n/d | n/d | n/d |
| B365 (2623) | proporzionale | 2 | 93 | 70,24 % | 76,34 % | 6,1 pt [-2,7 pt; 14,3 pt] |
| B365 (2623) | Shin | 1 | 405 | 73,20 % | 76,05 % | 2,9 pt [-1,4 pt; 7,0 pt] |
| B365 (2623) | Shin | X | 0 | n/d | n/d | n/d |
| B365 (2623) | Shin | 2 | 98 | 71,48 % | 75,51 % | 4,0 pt [-4,7 pt; 12,5 pt] |
| B365 (2623) | potenza | 1 | 420 | 73,71 % | 75,48 % | 1,8 pt [-2,4 pt; 6,0 pt] |
| B365 (2623) | potenza | X | 0 | n/d | n/d | n/d |
| B365 (2623) | potenza | 2 | 103 | 71,93 % | 75,73 % | 3,8 pt [-4,6 pt; 12,2 pt] |
| Pinnacle (2623) | proporzionale | 1 | 386 | 73,29 % | 77,72 % | 4,4 pt [0,1 pt; 8,7 pt] |
| Pinnacle (2623) | proporzionale | X | 0 | n/d | n/d | n/d |
| Pinnacle (2623) | proporzionale | 2 | 100 | 71,36 % | 73,00 % | 1,6 pt [-7,3 pt; 9,7 pt] |

## 6. Punto 6 — stima della quota bet365 (fit 2024/25, test 2025/26), coda dell'errore

Modello della PR #58 (`lega × tipo × fascia di quota equa Pinnacle`). Fasce per quota **reale** bet365. Errore relativo = |q̂/q − 1|; errore assoluto = |q̂ − q| in punti di quota.

| fascia di quota reale | n | errore rel. mediano | P90 | P99 | errore assoluto mediano (quota) | P90 (quota) | P99 (quota) |
|---|---|---|---|---|---|---|---|
| 1,20-1,50 | 232 | 0,95 % | 2,50 % | 4,70 % | 0,013 | 0,034 | 0,060 |
| 1,50-2,00 | 1250 | 0,91 % | 2,26 % | 3,54 % | 0,015 | 0,039 | 0,066 |
| 2,00-3,00 | 1287 | 1,30 % | 3,01 % | 5,68 % | 0,030 | 0,070 | 0,140 |
| oltre 3,00 | 1704 | 2,23 % | 6,66 % | 16,96 % | 0,086 | 0,361 | 1,872 |
| **tutte le quote** | 4490 | 1,36 % | 4,09 % | 12,55 % | 0,032 | 0,163 | 1,043 |

Fuori dalle quattro fasce (quota < 1,20): 17 osservazioni. Controllo di parità con PR #58 (errore relativo mediano complessivo, test 2025/26, lega × fascia × tipo): 1,36 % (PR: 1,36 %); P90 4,09 % (PR: 4,09 %).

## 7. Limiti

- Il campione usa la data come proxy della giornata (il CSV non ha la giornata), come PR #58.
- Le quote B365 «ant.» sono dichiarate pre-partita come in PR #58; l'orario di rilevazione non è nel CSV.
- Pinnacle di apertura (PS*) per la stima bet365 (punto 6), chiusura (PSC*) per il punto 5: come PR #58.
- I derivati 1X+Under 3,5 e Over/Under 1,5 / 3,5 non sono quotati nel campione: sono ricavati dalla griglia, quindi la calibrazione misura la griglia, non una quota diretta.
- La calibrazione non dice nulla sul valore economico di una giocata a quota.
- Il tau di produzione e il fit per partita sono quelli di PR #58; nessuna variante tocca la produzione.

