# Combo 1X2 + Totali: griglia congiunta vs prodotto naive (audit sola lettura)

*Generato: 2026-09-13T22:09:24+00:00 — script `audit/diagnose_combo_1x2_totali.py`, nessuna modifica a SoccerMath/.* Brier = mean((p - y)^2) sull'indicatore binario della combo; piu' basso = meglio.*

Walk-forward no-leakage, 5 leghe, TRAIN 2022/23+2023/24 (le prime 60 partite/lega restano nello stato ma sono escluse dal campione: cold start), VALIDATION 2024/25 (conferma), TEST 2025/26 (sola lettura, mai usata per scegliere). Testa 1X2 = NORM-SUM di `diagnose_elo_ensemble.run_models` (xG snapshot + forma ult.5 + fattore mercato, somma normalizzata alla base con forma); testa Totali = lambda puri senza forma ne' mercato di `diagnose_form_totali` (modello B); Elo sequenziale K=24 e blend w=0.25 (`app.ELO_ENSEMBLE_W`). Griglia congiunta = matrice 15x15 di `app._poisson_market` con somma sulle celle (h,a) della combo, supporto troncato e non rinormalizzato come in produzione. Conformita' verificata bit-a-bit (vedi sotto).

Versioni a confronto (stessa partita, stesso stato):

- **(a) griglia congiunta lambda 1X2 (att/def + mercato)**
- **(b) griglia congiunta lambda Totali (att0_pure/def0_pure)**
- **(c) prodotto naive P(1) blendato x P(totale) testa Totali**
- **(c0) prodotto naive P(1) Poisson puro x P(totale) [controllo]**

La (c) e' esattamente cio' che si otterrebbe oggi moltiplicando i due numeri che il Top Mix mette in scheda; la (c0) e' lo stesso prodotto senza Elo, serve a separare 'manca la correlazione' da 'dentro c'e' anche l'Elo'.

Attenzione a un particolare non casuale: (a) e (b) usano le marginali IMPLICITE della propria griglia (il P(1) di (a) non contiene l'Elo, e l'Over di (a) e' quello della testa 1X2 non quello mostrato in scheda), quindi il confronto raw (a) vs (c) mescola tre effetti: correlazione, scelta della testa per il totale, contributo dell'Elo. Per separarli sono disponibili due controlli: (c0) = prodotto delle marginali cosi' come le mostriamo oggi ma senza Elo, e il `naive stessa griglia` (ref) = prodotto delle marginali DELLA STESSA matrice usata per la somma sulle celle. Lì le marginali sono identiche per costruzione, quindi (griglia − ref) E' il termine di correlazione e niente altro: e' la cifra da leggere per rispondere alla domanda dell'audit.

## Conformita' del protocollo (verificata, non dichiarata)

Le marginali di questo walk-forward sono state confrontate riga per riga con le due diagnosi da cui ereditano il modello, su validation+test:

| Lega | n righe confrontate | max \|scarto\| P(1) vs diagnose_elo_ensemble | max \|scarto\| P(Over) vs diagnose_form_totali | esiti reali identici |
|---|---:|---:|---:|---|
| Serie A | 760 | 0.0e+00 | 0.0e+00 | si |
| Premier League | 760 | 0.0e+00 | 0.0e+00 | si |
| La Liga | 760 | 0.0e+00 | 0.0e+00 | si |
| Bundesliga | 612 | 0.0e+00 | 0.0e+00 | si |
| Ligue 1 | 612 | 0.0e+00 | 0.0e+00 | si |

Scarto zero = le tre colonne della testa 1X2 e la testa Totali di questo audit sono lo STESSO numero che producono gli audit di riferimento: qui ci sono solo in piu' le somme sulle celle della matrice. In piu', `check_state_invariance` verifica che emettere anche le stagioni di train non sposti di un bit le predizioni di validation/test (nessuna leakage dall'estensione del campione).

## Copertura campioni

| Lega | Train (n) | Train escluse cold-start | Validation (n) | Test (n) |
|---|---:|---:|---:|---:|
| Serie A | 700 | 60 | 380 | 380 |
| Premier League | 700 | 60 | 380 | 380 |
| La Liga | 700 | 60 | 380 | 380 |
| Bundesliga | 552 | 60 | 306 | 306 |
| Ligue 1 | 626 | 60 | 306 | 306 |
| **AGGREGATO** | 3278 | 300 | 1752 | 1752 |

## Combo 1 + Over 2.5 — primaria (quella chiesta)

vittoria casa E >=3 gol totali: le due componenti condividono i lambda della stessa squadra forte in casa, correlazione attesa > 0.

### 1 + Over 2.5 — TRAIN 2022/23+2023/24 (direzione, nessuna ritaratura) (aggregato 5 leghe, n=3278)

| Versione | Brier | LogLoss | Segnale vs costante | Pred. media | Frequ. osservata | Bias | Δ Brier vs (c) | IC 95% Δ | Δ vs (c0) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| a_grid_1x2 | 0.2184 | 0.6823 | -7.6% | 0.2736 | 0.2831 | -0.0095 | +0.0207 | [0.0161; 0.0254] | +0.0036 |
| b_grid_totali | 0.2206 | 0.6734 | -8.7% | 0.2780 | 0.2831 | -0.0051 | +0.0229 | [0.0188; 0.0271] | +0.0057 |
| c_naive_blend | 0.1977 | 0.5887 | 2.6% | 0.2346 | 0.2831 | -0.0485 | +0.0000 | [0.0000; 0.0000] | -0.0172 |
| c0_naive_puro | 0.2149 | 0.6650 | -5.9% | 0.2450 | 0.2831 | -0.0381 | +0.0172 | [0.0137; 0.0207] | +0.0000 |

Predittore costante (frequenza base del campione): Brier 0.2030. `Segnale vs costante` = 100*(1 - Brier/Brier costante): quanto la versione sa davvero distinguere le combo vinte da quelle perse. Il riferimento usa la frequenza del campione stesso (in-sample): e' una scala per leggere i delta, non una strategia reperibile sul mercato.

Lettura Δ Brier vs (c): a_grid_1x2 PEGGIORE (IC senza zero); b_grid_totali PEGGIORE (IC senza zero); c0_naive_puro PEGGIORE (IC senza zero).

### 1 + Over 2.5 — VALIDATION 2024/25 (conferma) (aggregato 5 leghe, n=1752)

| Versione | Brier | LogLoss | Segnale vs costante | Pred. media | Frequ. osservata | Bias | Δ Brier vs (c) | IC 95% Δ | Δ vs (c0) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| a_grid_1x2 | 0.2039 | 0.6333 | -5.0% | 0.2674 | 0.2637 | +0.0037 | +0.0161 | [0.0104; 0.0218] | +0.0019 |
| b_grid_totali | 0.2067 | 0.6348 | -6.4% | 0.2716 | 0.2637 | +0.0079 | +0.0188 | [0.0137; 0.0240] | +0.0046 |
| c_naive_blend | 0.1879 | 0.5641 | 3.3% | 0.2354 | 0.2637 | -0.0283 | +0.0000 | [0.0000; 0.0000] | -0.0142 |
| c0_naive_puro | 0.2020 | 0.6239 | -4.0% | 0.2393 | 0.2637 | -0.0244 | +0.0142 | [0.0102; 0.0182] | +0.0000 |

Predittore costante (frequenza base del campione): Brier 0.1942. `Segnale vs costante` = 100*(1 - Brier/Brier costante): quanto la versione sa davvero distinguere le combo vinte da quelle perse. Il riferimento usa la frequenza del campione stesso (in-sample): e' una scala per leggere i delta, non una strategia reperibile sul mercato.

Lettura Δ Brier vs (c): a_grid_1x2 PEGGIORE (IC senza zero); b_grid_totali PEGGIORE (IC senza zero); c0_naive_puro PEGGIORE (IC senza zero).

### 1 + Over 2.5 — TEST 2025/26 (sola lettura) (aggregato 5 leghe, n=1752)

| Versione | Brier | LogLoss | Segnale vs costante | Pred. media | Frequ. osservata | Bias | Δ Brier vs (c) | IC 95% Δ | Δ vs (c0) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| a_grid_1x2 | 0.2054 | 0.6350 | -2.6% | 0.2576 | 0.2768 | -0.0192 | +0.0131 | [0.0080; 0.0183] | +0.0025 |
| b_grid_totali | 0.2046 | 0.6209 | -2.2% | 0.2622 | 0.2768 | -0.0146 | +0.0122 | [0.0074; 0.0172] | +0.0016 |
| c_naive_blend | 0.1923 | 0.5754 | 3.9% | 0.2288 | 0.2768 | -0.0481 | +0.0000 | [0.0000; 0.0000] | -0.0106 |
| c0_naive_puro | 0.2030 | 0.6243 | -1.4% | 0.2298 | 0.2768 | -0.0470 | +0.0106 | [0.0070; 0.0144] | +0.0000 |

Predittore costante (frequenza base del campione): Brier 0.2002. `Segnale vs costante` = 100*(1 - Brier/Brier costante): quanto la versione sa davvero distinguere le combo vinte da quelle perse. Il riferimento usa la frequenza del campione stesso (in-sample): e' una scala per leggere i delta, non una strategia reperibile sul mercato.

Lettura Δ Brier vs (c): a_grid_1x2 PEGGIORE (IC senza zero); b_grid_totali PEGGIORE (IC senza zero); c0_naive_puro PEGGIORE (IC senza zero).

### 1 + Over 2.5 — Brier per singola lega

| Lega | Split | a_grid_1x2 | b_grid_totali | c_naive_blend | c0_naive_puro |
|---|---|---:|---:|---:|---:|
| Serie A | train | 0.2075 | 0.2058 | 0.1760 | 0.1987 |
| Serie A | validation | 0.1934 | 0.1932 | 0.1743 | 0.1900 |
| Serie A | test | 0.1787 | 0.1782 | 0.1667 | 0.1769 |
| Premier League | train | 0.2233 | 0.2265 | 0.2056 | 0.2199 |
| Premier League | validation | 0.1986 | 0.1998 | 0.1846 | 0.1949 |
| Premier League | test | 0.2099 | 0.2015 | 0.1970 | 0.2048 |
| La Liga | train | 0.2043 | 0.2046 | 0.1867 | 0.1998 |
| La Liga | validation | 0.1845 | 0.1910 | 0.1757 | 0.1852 |
| La Liga | test | 0.1950 | 0.1989 | 0.1956 | 0.1981 |
| Bundesliga | train | 0.2606 | 0.2632 | 0.2316 | 0.2598 |
| Bundesliga | validation | 0.2075 | 0.2104 | 0.1879 | 0.2025 |
| Bundesliga | test | 0.2355 | 0.2332 | 0.2095 | 0.2287 |
| Ligue 1 | train | 0.2038 | 0.2107 | 0.1956 | 0.2045 |
| Ligue 1 | validation | 0.2442 | 0.2476 | 0.2238 | 0.2461 |
| Ligue 1 | test | 0.2159 | 0.2195 | 0.1972 | 0.2134 |

### 1 + Over 2.5 — quante volte ogni versione vince il Brier (lega x split, 15 casi)

a_grid_1x2: 1/15 | b_grid_totali: 0/15 | c_naive_blend: 14/15 | c0_naive_puro: 0/15

## Combo 2 + Under 2.5 — controllo

vittoria trasferta E <=2 gol totali: combo 'di partita chiusa', stesso tipo di assunzione di indipendenza nella direzione opposta.

### 2 + Under 2.5 — TRAIN 2022/23+2023/24 (direzione, nessuna ritaratura) (aggregato 5 leghe, n=3278)

| Versione | Brier | LogLoss | Segnale vs costante | Pred. media | Frequ. osservata | Bias | Δ Brier vs (c) | IC 95% Δ | Δ vs (c0) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| a_grid_1x2 | 0.1096 | 0.3817 | -3.2% | 0.1463 | 0.1208 | +0.0255 | +0.0031 | [0.0018; 0.0046] | -0.0051 |
| b_grid_totali | 0.1096 | 0.3825 | -3.2% | 0.1409 | 0.1208 | +0.0201 | +0.0031 | [0.0016; 0.0047] | -0.0051 |
| c_naive_blend | 0.1065 | 0.3657 | -0.3% | 0.1584 | 0.1208 | +0.0376 | +0.0000 | [0.0000; 0.0000] | -0.0082 |
| c0_naive_puro | 0.1147 | 0.3969 | -8.0% | 0.1685 | 0.1208 | +0.0477 | +0.0082 | [0.0063; 0.0101] | +0.0000 |

Predittore costante (frequenza base del campione): Brier 0.1062. `Segnale vs costante` = 100*(1 - Brier/Brier costante): quanto la versione sa davvero distinguere le combo vinte da quelle perse. Il riferimento usa la frequenza del campione stesso (in-sample): e' una scala per leggere i delta, non una strategia reperibile sul mercato.

Lettura Δ Brier vs (c): a_grid_1x2 PEGGIORE (IC senza zero); b_grid_totali PEGGIORE (IC senza zero); c0_naive_puro PEGGIORE (IC senza zero).

### 2 + Under 2.5 — VALIDATION 2024/25 (conferma) (aggregato 5 leghe, n=1752)

| Versione | Brier | LogLoss | Segnale vs costante | Pred. media | Frequ. osservata | Bias | Δ Brier vs (c) | IC 95% Δ | Δ vs (c0) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| a_grid_1x2 | 0.1191 | 0.4115 | -5.6% | 0.1478 | 0.1296 | +0.0182 | +0.0029 | [0.0009; 0.0050] | -0.0047 |
| b_grid_totali | 0.1193 | 0.4157 | -5.8% | 0.1423 | 0.1296 | +0.0128 | +0.0031 | [0.0006; 0.0056] | -0.0046 |
| c_naive_blend | 0.1162 | 0.3932 | -3.0% | 0.1622 | 0.1296 | +0.0326 | +0.0000 | [0.0000; 0.0000] | -0.0077 |
| c0_naive_puro | 0.1239 | 0.4252 | -9.9% | 0.1690 | 0.1296 | +0.0395 | +0.0077 | [0.0052; 0.0102] | +0.0000 |

Predittore costante (frequenza base del campione): Brier 0.1128. `Segnale vs costante` = 100*(1 - Brier/Brier costante): quanto la versione sa davvero distinguere le combo vinte da quelle perse. Il riferimento usa la frequenza del campione stesso (in-sample): e' una scala per leggere i delta, non una strategia reperibile sul mercato.

Lettura Δ Brier vs (c): a_grid_1x2 PEGGIORE (IC senza zero); b_grid_totali PEGGIORE (IC senza zero); c0_naive_puro PEGGIORE (IC senza zero).

### 2 + Under 2.5 — TEST 2025/26 (sola lettura) (aggregato 5 leghe, n=1752)

| Versione | Brier | LogLoss | Segnale vs costante | Pred. media | Frequ. osservata | Bias | Δ Brier vs (c) | IC 95% Δ | Δ vs (c0) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| a_grid_1x2 | 0.1125 | 0.3858 | -3.3% | 0.1539 | 0.1244 | +0.0295 | +0.0028 | [0.0007; 0.0049] | -0.0043 |
| b_grid_totali | 0.1112 | 0.3816 | -2.1% | 0.1471 | 0.1244 | +0.0227 | +0.0015 | [-0.0010; 0.0038] | -0.0056 |
| c_naive_blend | 0.1097 | 0.3701 | -0.7% | 0.1678 | 0.1244 | +0.0434 | +0.0000 | [0.0000; 0.0000] | -0.0071 |
| c0_naive_puro | 0.1168 | 0.3982 | -7.2% | 0.1761 | 0.1244 | +0.0516 | +0.0071 | [0.0043; 0.0096] | +0.0000 |

Predittore costante (frequenza base del campione): Brier 0.1089. `Segnale vs costante` = 100*(1 - Brier/Brier costante): quanto la versione sa davvero distinguere le combo vinte da quelle perse. Il riferimento usa la frequenza del campione stesso (in-sample): e' una scala per leggere i delta, non una strategia reperibile sul mercato.

Lettura Δ Brier vs (c): a_grid_1x2 PEGGIORE (IC senza zero); b_grid_totali entro l'IC: rumore; c0_naive_puro PEGGIORE (IC senza zero).

### 2 + Under 2.5 — Brier per singola lega

| Lega | Split | a_grid_1x2 | b_grid_totali | c_naive_blend | c0_naive_puro |
|---|---|---:|---:|---:|---:|
| Serie A | train | 0.1263 | 0.1259 | 0.1207 | 0.1337 |
| Serie A | validation | 0.1293 | 0.1308 | 0.1215 | 0.1342 |
| Serie A | test | 0.1468 | 0.1467 | 0.1432 | 0.1497 |
| Premier League | train | 0.1001 | 0.1005 | 0.0991 | 0.1043 |
| Premier League | validation | 0.1268 | 0.1257 | 0.1239 | 0.1291 |
| Premier League | test | 0.1076 | 0.1059 | 0.1041 | 0.1082 |
| La Liga | train | 0.1196 | 0.1202 | 0.1175 | 0.1227 |
| La Liga | validation | 0.1063 | 0.1063 | 0.1056 | 0.1099 |
| La Liga | test | 0.1100 | 0.1098 | 0.1091 | 0.1145 |
| Bundesliga | train | 0.0871 | 0.0860 | 0.0823 | 0.0939 |
| Bundesliga | validation | 0.1165 | 0.1158 | 0.1123 | 0.1217 |
| Bundesliga | test | 0.0874 | 0.0851 | 0.0811 | 0.0960 |
| Ligue 1 | train | 0.1102 | 0.1102 | 0.1078 | 0.1143 |
| Ligue 1 | validation | 0.1157 | 0.1169 | 0.1172 | 0.1243 |
| Ligue 1 | test | 0.1043 | 0.1018 | 0.1044 | 0.1104 |

### 2 + Under 2.5 — quante volte ogni versione vince il Brier (lega x split, 15 casi)

a_grid_1x2: 1/15 | b_grid_totali: 1/15 | c_naive_blend: 13/15 | c0_naive_puro: 0/15

## Combo X + Over 2.5 — controllo (correlazione negativa)

pareggio E >=3 gol: qui l'indipendenza sbaglia di segno (1-1 e 2-2 convivono male con un pari a reti inviolate), test robusto.

### X + Over 2.5 — TRAIN 2022/23+2023/24 (direzione, nessuna ritaratura) (aggregato 5 leghe, n=3278)

| Versione | Brier | LogLoss | Segnale vs costante | Pred. media | Frequ. osservata | Bias | Δ Brier vs (c) | IC 95% Δ | Δ vs (c0) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| a_grid_1x2 | 0.0667 | 0.2901 | -2.2% | 0.0385 | 0.0702 | -0.0317 | -0.0020 | [-0.0034; -0.0007] | -0.0002 |
| b_grid_totali | 0.0664 | 0.2798 | -1.9% | 0.0460 | 0.0702 | -0.0241 | -0.0023 | [-0.0036; -0.0010] | -0.0005 |
| c_naive_blend | 0.0687 | 0.2704 | -5.3% | 0.1152 | 0.0702 | +0.0451 | +0.0000 | [0.0000; 0.0000] | +0.0018 |
| c0_naive_puro | 0.0669 | 0.2643 | -2.6% | 0.0939 | 0.0702 | +0.0238 | -0.0018 | [-0.0025; -0.0010] | +0.0000 |

Predittore costante (frequenza base del campione): Brier 0.0652. `Segnale vs costante` = 100*(1 - Brier/Brier costante): quanto la versione sa davvero distinguere le combo vinte da quelle perse. Il riferimento usa la frequenza del campione stesso (in-sample): e' una scala per leggere i delta, non una strategia reperibile sul mercato.

Lettura Δ Brier vs (c): a_grid_1x2 MIGLIORE (IC senza zero); b_grid_totali MIGLIORE (IC senza zero); c0_naive_puro MIGLIORE (IC senza zero).

### X + Over 2.5 — VALIDATION 2024/25 (conferma) (aggregato 5 leghe, n=1752)

| Versione | Brier | LogLoss | Segnale vs costante | Pred. media | Frequ. osservata | Bias | Δ Brier vs (c) | IC 95% Δ | Δ vs (c0) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| a_grid_1x2 | 0.0664 | 0.2950 | -2.5% | 0.0389 | 0.0696 | -0.0308 | -0.0012 | [-0.0030; 0.0007] | -0.0001 |
| b_grid_totali | 0.0658 | 0.2785 | -1.6% | 0.0462 | 0.0696 | -0.0235 | -0.0017 | [-0.0034; -0.0000] | -0.0006 |
| c_naive_blend | 0.0676 | 0.2653 | -4.3% | 0.1091 | 0.0696 | +0.0395 | +0.0000 | [0.0000; 0.0000] | +0.0011 |
| c0_naive_puro | 0.0665 | 0.2661 | -2.6% | 0.0952 | 0.0696 | +0.0256 | -0.0011 | [-0.0020; -0.0002] | +0.0000 |

Predittore costante (frequenza base del campione): Brier 0.0648. `Segnale vs costante` = 100*(1 - Brier/Brier costante): quanto la versione sa davvero distinguere le combo vinte da quelle perse. Il riferimento usa la frequenza del campione stesso (in-sample): e' una scala per leggere i delta, non una strategia reperibile sul mercato.

Lettura Δ Brier vs (c): a_grid_1x2 entro l'IC: rumore; b_grid_totali MIGLIORE (IC senza zero); c0_naive_puro MIGLIORE (IC senza zero).

### X + Over 2.5 — TEST 2025/26 (sola lettura) (aggregato 5 leghe, n=1752)

| Versione | Brier | LogLoss | Segnale vs costante | Pred. media | Frequ. osservata | Bias | Δ Brier vs (c) | IC 95% Δ | Δ vs (c0) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| a_grid_1x2 | 0.0684 | 0.3093 | -1.8% | 0.0373 | 0.0725 | -0.0352 | -0.0008 | [-0.0025; 0.0010] | +0.0001 |
| b_grid_totali | 0.0682 | 0.2967 | -1.4% | 0.0447 | 0.0725 | -0.0278 | -0.0010 | [-0.0027; 0.0006] | -0.0002 |
| c_naive_blend | 0.0692 | 0.2749 | -3.0% | 0.1059 | 0.0725 | +0.0334 | +0.0000 | [0.0000; 0.0000] | +0.0009 |
| c0_naive_puro | 0.0683 | 0.2681 | -1.7% | 0.0937 | 0.0725 | +0.0212 | -0.0009 | [-0.0017; -0.0000] | +0.0000 |

Predittore costante (frequenza base del campione): Brier 0.0672. `Segnale vs costante` = 100*(1 - Brier/Brier costante): quanto la versione sa davvero distinguere le combo vinte da quelle perse. Il riferimento usa la frequenza del campione stesso (in-sample): e' una scala per leggere i delta, non una strategia reperibile sul mercato.

Lettura Δ Brier vs (c): a_grid_1x2 entro l'IC: rumore; b_grid_totali entro l'IC: rumore; c0_naive_puro MIGLIORE (IC senza zero).

### X + Over 2.5 — Brier per singola lega

| Lega | Split | a_grid_1x2 | b_grid_totali | c_naive_blend | c0_naive_puro |
|---|---|---:|---:|---:|---:|
| Serie A | train | 0.0725 | 0.0718 | 0.0716 | 0.0705 |
| Serie A | validation | 0.0688 | 0.0684 | 0.0690 | 0.0673 |
| Serie A | test | 0.0668 | 0.0663 | 0.0672 | 0.0661 |
| Premier League | train | 0.0730 | 0.0729 | 0.0748 | 0.0736 |
| Premier League | validation | 0.0792 | 0.0780 | 0.0809 | 0.0779 |
| Premier League | test | 0.0739 | 0.0733 | 0.0757 | 0.0745 |
| La Liga | train | 0.0586 | 0.0585 | 0.0608 | 0.0590 |
| La Liga | validation | 0.0479 | 0.0477 | 0.0488 | 0.0492 |
| La Liga | test | 0.0497 | 0.0500 | 0.0517 | 0.0514 |
| Bundesliga | train | 0.0737 | 0.0732 | 0.0765 | 0.0727 |
| Bundesliga | validation | 0.0886 | 0.0885 | 0.0884 | 0.0869 |
| Bundesliga | test | 0.0875 | 0.0873 | 0.0855 | 0.0849 |
| Ligue 1 | train | 0.0561 | 0.0562 | 0.0607 | 0.0593 |
| Ligue 1 | validation | 0.0482 | 0.0475 | 0.0516 | 0.0521 |
| Ligue 1 | test | 0.0679 | 0.0676 | 0.0692 | 0.0679 |

### X + Over 2.5 — quante volte ogni versione vince il Brier (lega x split, 15 casi)

a_grid_1x2: 2/15 | b_grid_totali: 6/15 | c_naive_blend: 0/15 | c0_naive_puro: 7/15

## Quanto pesa la correlazione 1X2 x Totali in pratica

Tre punti di vista sullo stesso fenomeno: (i) la correlazione che le griglie congiunte implicano e che il prodotto naive pone a zero, (ii) la correlazione EMPIRICA tra i due eventi realised, (iii) il danno in Brier di chi la ignora.

| Combo | Split | ρ implicita griglia 1X2 | ρ implicita griglia Totali | ρ empirica (gol reali) | Δ Brier (a-c) | Δ Brier (b-c) |
|---|---|---:|---:|---:|---:|---:|
| 1 + Over 2.5 | train | +0.1472 | +0.1527 | +0.1782 | +0.0207 | +0.0229 |
| 1 + Over 2.5 | validation | +0.1469 | +0.1508 | +0.1595 | +0.0161 | +0.0188 |
| 1 + Over 2.5 | test | +0.1435 | +0.1486 | +0.1755 | +0.0131 | +0.0122 |
| 2 + Under 2.5 | train | -0.1021 | -0.0979 | -0.0862 | +0.0031 | +0.0031 |
| 2 + Under 2.5 | validation | -0.1037 | -0.1004 | -0.1038 | +0.0029 | +0.0031 |
| 2 + Under 2.5 | test | -0.1073 | -0.1028 | -0.0827 | +0.0028 | +0.0015 |
| X + Over 2.5 | train | -0.2916 | -0.2909 | -0.2956 | -0.0020 | -0.0023 |
| X + Over 2.5 | validation | -0.2926 | -0.2914 | -0.2948 | -0.0012 | -0.0017 |
| X + Over 2.5 | test | -0.2925 | -0.2913 | -0.2875 | -0.0008 | -0.0010 |

`ρ implicita` = correlazione point-biserial tra i due eventi che emerge dalla matrice congiunta, mediata sulle partite: il prodotto naive ha ρ = 0 per definizione. `ρ empirica` = correlazione di Pearson tra i due indicatori osservati sullo stesso campione.

### Il solo termine di correlazione (marginali identiche per costruzione)

Stesso P(testa) e stesso P(totale), unica differenza: somma sulle celle della matrice congiunta oppure prodotto delle due marginali. La differenza di Brier qui sotto E' il peso della correlazione 1X2 x Totali, liberata da altri effetti; Δ negativo = la griglia congiunta batte il prodotto, cioe' ignorare la correlazione costa.

| Combo | Split | Testa usata | Brier griglia | Brier prodotto stessa griglia | Δ (correlazione pura) | IC 95% Δ | Verdetto |
|---|---|---|---:|---:|---:|---:|---|
| 1 + Over 2.5 | train | 1X2 (con mercato) | 0.2184 | 0.2177 | +0.0007 | [-0.0006; 0.0020] | entro l'IC: rumore |
| 1 + Over 2.5 | train | Totali (pura) | 0.2206 | 0.2189 | +0.0016 | [0.0003; 0.0030] | PEGGIORE (IC senza zero) |
| 1 + Over 2.5 | validation | 1X2 (con mercato) | 0.2039 | 0.2030 | +0.0010 | [-0.0007; 0.0027] | entro l'IC: rumore |
| 1 + Over 2.5 | validation | Totali (pura) | 0.2067 | 0.2051 | +0.0016 | [-0.0002; 0.0033] | entro l'IC: rumore |
| 1 + Over 2.5 | test | 1X2 (con mercato) | 0.2054 | 0.2057 | -0.0003 | [-0.0020; 0.0014] | entro l'IC: rumore |
| 1 + Over 2.5 | test | Totali (pura) | 0.2046 | 0.2047 | -0.0001 | [-0.0019; 0.0016] | entro l'IC: rumore |
| 2 + Under 2.5 | train | 1X2 (con mercato) | 0.1096 | 0.1146 | -0.0050 | [-0.0059; -0.0042] | MIGLIORE (IC senza zero) |
| 2 + Under 2.5 | train | Totali (pura) | 0.1096 | 0.1142 | -0.0046 | [-0.0054; -0.0038] | MIGLIORE (IC senza zero) |
| 2 + Under 2.5 | validation | 1X2 (con mercato) | 0.1191 | 0.1242 | -0.0051 | [-0.0063; -0.0039] | MIGLIORE (IC senza zero) |
| 2 + Under 2.5 | validation | Totali (pura) | 0.1193 | 0.1238 | -0.0045 | [-0.0057; -0.0033] | MIGLIORE (IC senza zero) |
| 2 + Under 2.5 | test | 1X2 (con mercato) | 0.1125 | 0.1178 | -0.0053 | [-0.0066; -0.0040] | MIGLIORE (IC senza zero) |
| 2 + Under 2.5 | test | Totali (pura) | 0.1112 | 0.1157 | -0.0045 | [-0.0057; -0.0032] | MIGLIORE (IC senza zero) |
| X + Over 2.5 | train | 1X2 (con mercato) | 0.0667 | 0.0663 | +0.0004 | [-0.0005; 0.0013] | entro l'IC: rumore |
| X + Over 2.5 | train | Totali (pura) | 0.0664 | 0.0669 | -0.0004 | [-0.0013; 0.0005] | entro l'IC: rumore |
| X + Over 2.5 | validation | 1X2 (con mercato) | 0.0664 | 0.0662 | +0.0002 | [-0.0011; 0.0014] | entro l'IC: rumore |
| X + Over 2.5 | validation | Totali (pura) | 0.0658 | 0.0665 | -0.0006 | [-0.0019; 0.0007] | entro l'IC: rumore |
| X + Over 2.5 | test | 1X2 (con mercato) | 0.0684 | 0.0679 | +0.0005 | [-0.0008; 0.0018] | entro l'IC: rumore |
| X + Over 2.5 | test | Totali (pura) | 0.0682 | 0.0685 | -0.0003 | [-0.0017; 0.0010] | entro l'IC: rumore |

### Fattore di correlazione k: stimato SUL TRAIN, letto fuori campione

Se il difetto del prodotto naive e' il LIVELLO (il termine di correlazione omesso), un solo moltiplicatore per tipo di combo dovrebbe riassumerlo. k e' stimato SOLO sul TRAIN come `frequenza osservata / probabilita' media` e applicato a validation e test senza nessun ricalibramento (p_corr = clip(k*p, 0, 1)). E' il modo piu' economico di misurare quanto vale davvero la correlazione, senza toccare il motore.

| Combo | Base | k (train) | VAL: bias rel. base → corretto | VAL: Brier base → corretto | Δ (IC 95%) | TEST: bias rel. base → corretto | TEST: Brier base → corretto | Δ (IC 95%) |
|---|---|---:|---|---|---|---|---|---|
| 1 + Over 2.5 | naive mostrata (P(1) con Elo) | 1.2067 | -10.7% → +7.7% | 0.1879 → 0.1913 | +0.0034 ([0.0008; 0.0060]) | -17.4% → -0.3% | 0.1923 → 0.1932 | +0.0009 ([-0.0015; 0.0036]) |
| 1 + Over 2.5 | naive pura (P(1) senza Elo) | 1.1555 | -9.3% → +4.7% | 0.2020 → 0.2103 | +0.0083 ([0.0058; 0.0108]) | -17.0% → -4.1% | 0.2030 → 0.2083 | +0.0053 ([0.0031; 0.0077]) |
| 2 + Under 2.5 | naive mostrata (P(1) con Elo) | 0.7626 | +25.2% → -4.5% | 0.1162 → 0.1129 | -0.0033 ([-0.0049; -0.0017]) | +34.9% → +2.8% | 0.1097 → 0.1063 | -0.0035 ([-0.0052; -0.0018]) |
| 2 + Under 2.5 | naive pura (P(1) senza Elo) | 0.7171 | +30.5% → -6.4% | 0.1239 → 0.1159 | -0.0080 ([-0.0103; -0.0057]) | +41.5% → +1.5% | 0.1168 → 0.1085 | -0.0083 ([-0.0108; -0.0058]) |
| X + Over 2.5 | naive mostrata (P(1) con Elo) | 0.6088 | +56.7% → -4.6% | 0.0676 → 0.0651 | -0.0024 ([-0.0036; -0.0013]) | +46.1% → -11.1% | 0.0692 → 0.0674 | -0.0018 ([-0.0029; -0.0007]) |
| X + Over 2.5 | naive pura (P(1) senza Elo) | 0.7470 | +36.8% → +2.2% | 0.0665 → 0.0653 | -0.0012 ([-0.0018; -0.0005]) | +29.3% → -3.4% | 0.0683 → 0.0675 | -0.0009 ([-0.0015; -0.0002]) |

`Δ` = Brier corretto − Brier base: negativo = il moltiplicatore migliora. L'ultima coppia di colonne e' sul TEST, dove nulla e' stato tarato.

### Bias sistematico del prodotto naive (aggregato 5 leghe)

Se il prodotto naive sottostima sistematicamente la frequenza reale, il suo errore NON e' solo rumore di correlazione ma anche livello: qui si separano le due cose.

| Combo | Split | Versione | Pred. media | Frequ. osservata | Bias | Bias relativo |
|---|---|---|---:|---:|---:|---:|
| 1 + Over 2.5 | train | a_grid_1x2 | 0.2736 | 0.2831 | -0.0095 | -3.4% |
| 1 + Over 2.5 | train | b_grid_totali | 0.2780 | 0.2831 | -0.0051 | -1.8% |
| 1 + Over 2.5 | train | c_naive_blend | 0.2346 | 0.2831 | -0.0485 | -17.1% |
| 1 + Over 2.5 | train | c0_naive_puro | 0.2450 | 0.2831 | -0.0381 | -13.5% |
| 1 + Over 2.5 | validation | a_grid_1x2 | 0.2674 | 0.2637 | +0.0037 | +1.4% |
| 1 + Over 2.5 | validation | b_grid_totali | 0.2716 | 0.2637 | +0.0079 | +3.0% |
| 1 + Over 2.5 | validation | c_naive_blend | 0.2354 | 0.2637 | -0.0283 | -10.7% |
| 1 + Over 2.5 | validation | c0_naive_puro | 0.2393 | 0.2637 | -0.0244 | -9.3% |
| 1 + Over 2.5 | test | a_grid_1x2 | 0.2576 | 0.2768 | -0.0192 | -6.9% |
| 1 + Over 2.5 | test | b_grid_totali | 0.2622 | 0.2768 | -0.0146 | -5.3% |
| 1 + Over 2.5 | test | c_naive_blend | 0.2288 | 0.2768 | -0.0481 | -17.4% |
| 1 + Over 2.5 | test | c0_naive_puro | 0.2298 | 0.2768 | -0.0470 | -17.0% |
| 2 + Under 2.5 | train | a_grid_1x2 | 0.1463 | 0.1208 | +0.0255 | +21.1% |
| 2 + Under 2.5 | train | b_grid_totali | 0.1409 | 0.1208 | +0.0201 | +16.6% |
| 2 + Under 2.5 | train | c_naive_blend | 0.1584 | 0.1208 | +0.0376 | +31.1% |
| 2 + Under 2.5 | train | c0_naive_puro | 0.1685 | 0.1208 | +0.0477 | +39.5% |
| 2 + Under 2.5 | validation | a_grid_1x2 | 0.1478 | 0.1296 | +0.0182 | +14.1% |
| 2 + Under 2.5 | validation | b_grid_totali | 0.1423 | 0.1296 | +0.0128 | +9.8% |
| 2 + Under 2.5 | validation | c_naive_blend | 0.1622 | 0.1296 | +0.0326 | +25.2% |
| 2 + Under 2.5 | validation | c0_naive_puro | 0.1690 | 0.1296 | +0.0395 | +30.5% |
| 2 + Under 2.5 | test | a_grid_1x2 | 0.1539 | 0.1244 | +0.0295 | +23.7% |
| 2 + Under 2.5 | test | b_grid_totali | 0.1471 | 0.1244 | +0.0227 | +18.3% |
| 2 + Under 2.5 | test | c_naive_blend | 0.1678 | 0.1244 | +0.0434 | +34.9% |
| 2 + Under 2.5 | test | c0_naive_puro | 0.1761 | 0.1244 | +0.0516 | +41.5% |
| X + Over 2.5 | train | a_grid_1x2 | 0.0385 | 0.0702 | -0.0317 | -45.2% |
| X + Over 2.5 | train | b_grid_totali | 0.0460 | 0.0702 | -0.0241 | -34.4% |
| X + Over 2.5 | train | c_naive_blend | 0.1152 | 0.0702 | +0.0451 | +64.2% |
| X + Over 2.5 | train | c0_naive_puro | 0.0939 | 0.0702 | +0.0238 | +33.9% |
| X + Over 2.5 | validation | a_grid_1x2 | 0.0389 | 0.0696 | -0.0308 | -44.2% |
| X + Over 2.5 | validation | b_grid_totali | 0.0462 | 0.0696 | -0.0235 | -33.7% |
| X + Over 2.5 | validation | c_naive_blend | 0.1091 | 0.0696 | +0.0395 | +56.7% |
| X + Over 2.5 | validation | c0_naive_puro | 0.0952 | 0.0696 | +0.0256 | +36.8% |
| X + Over 2.5 | test | a_grid_1x2 | 0.0373 | 0.0725 | -0.0352 | -48.6% |
| X + Over 2.5 | test | b_grid_totali | 0.0447 | 0.0725 | -0.0278 | -38.3% |
| X + Over 2.5 | test | c_naive_blend | 0.1059 | 0.0725 | +0.0334 | +46.1% |
| X + Over 2.5 | test | c0_naive_puro | 0.0937 | 0.0725 | +0.0212 | +29.3% |

### Affidabilita' per quintili (combo primaria, validation e test separate)

**VALIDATION** — quintili della previsione di ciascuna versione (bin diversi per versione per costruzione: confrontare il *bias*, non la riga).

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| a_grid_1x2 | Q1 | 351 | 0.0264 | 0.1396 | -0.1132 |
| a_grid_1x2 | Q2 | 350 | 0.1025 | 0.1829 | -0.0804 |
| a_grid_1x2 | Q3 | 350 | 0.2022 | 0.2629 | -0.0606 |
| a_grid_1x2 | Q4 | 350 | 0.3547 | 0.3314 | +0.0232 |
| a_grid_1x2 | Q5 | 351 | 0.6510 | 0.4017 | +0.2493 |
| b_grid_totali | Q1 | 351 | 0.0441 | 0.1738 | -0.1297 |
| b_grid_totali | Q2 | 350 | 0.1302 | 0.2257 | -0.0955 |
| b_grid_totali | Q3 | 350 | 0.2220 | 0.2343 | -0.0123 |
| b_grid_totali | Q4 | 350 | 0.3469 | 0.3029 | +0.0441 |
| b_grid_totali | Q5 | 351 | 0.6146 | 0.3818 | +0.2328 |
| c_naive_blend | Q1 | 351 | 0.0813 | 0.1311 | -0.0498 |
| c_naive_blend | Q2 | 350 | 0.1381 | 0.1971 | -0.0591 |
| c_naive_blend | Q3 | 350 | 0.1995 | 0.2657 | -0.0662 |
| c_naive_blend | Q4 | 350 | 0.2830 | 0.3086 | -0.0255 |
| c_naive_blend | Q5 | 351 | 0.4749 | 0.4160 | +0.0589 |
| c0_naive_puro | Q1 | 351 | 0.0295 | 0.1510 | -0.1215 |
| c0_naive_puro | Q2 | 350 | 0.0949 | 0.1943 | -0.0994 |
| c0_naive_puro | Q3 | 350 | 0.1772 | 0.2543 | -0.0771 |
| c0_naive_puro | Q4 | 350 | 0.3038 | 0.3143 | -0.0105 |
| c0_naive_puro | Q5 | 351 | 0.5905 | 0.4046 | +0.1860 |

**TEST** — quintili della previsione di ciascuna versione (bin diversi per versione per costruzione: confrontare il *bias*, non la riga).

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| a_grid_1x2 | Q1 | 351 | 0.0218 | 0.1282 | -0.1064 |
| a_grid_1x2 | Q2 | 350 | 0.0956 | 0.2171 | -0.1215 |
| a_grid_1x2 | Q3 | 350 | 0.1919 | 0.2657 | -0.0738 |
| a_grid_1x2 | Q4 | 350 | 0.3390 | 0.3343 | +0.0047 |
| a_grid_1x2 | Q5 | 351 | 0.6394 | 0.4387 | +0.2007 |
| b_grid_totali | Q1 | 351 | 0.0369 | 0.1396 | -0.1027 |
| b_grid_totali | Q2 | 350 | 0.1207 | 0.2371 | -0.1164 |
| b_grid_totali | Q3 | 350 | 0.2163 | 0.2857 | -0.0694 |
| b_grid_totali | Q4 | 350 | 0.3434 | 0.3000 | +0.0434 |
| b_grid_totali | Q5 | 351 | 0.5935 | 0.4217 | +0.1719 |
| c_naive_blend | Q1 | 351 | 0.0736 | 0.1624 | -0.0888 |
| c_naive_blend | Q2 | 350 | 0.1355 | 0.1743 | -0.0388 |
| c_naive_blend | Q3 | 350 | 0.1932 | 0.2657 | -0.0725 |
| c_naive_blend | Q4 | 350 | 0.2741 | 0.3314 | -0.0573 |
| c_naive_blend | Q5 | 351 | 0.4672 | 0.4501 | +0.0170 |
| c0_naive_puro | Q1 | 351 | 0.0246 | 0.1396 | -0.1150 |
| c0_naive_puro | Q2 | 350 | 0.0889 | 0.2029 | -0.1139 |
| c0_naive_puro | Q3 | 350 | 0.1676 | 0.2743 | -0.1067 |
| c0_naive_puro | Q4 | 350 | 0.2947 | 0.3200 | -0.0253 |
| c0_naive_puro | Q5 | 351 | 0.5730 | 0.4473 | +0.1257 |

## Selezione (su TRAIN) e conferma (su VALIDATION); TEST sola lettura

- Combo primaria 1 + Over 2.5: Brier minimo su TRAIN = **c_naive_blend** (0.1977); su VALIDATION la stessa versione vale 0.1879 e su TEST 0.1923.
- train: ordine dal migliore al peggiore — c_naive_blend (0.1977) < c0_naive_puro (0.2149) < a_grid_1x2 (0.2184) < b_grid_totali (0.2206)
- validation: ordine dal migliore al peggiore — c_naive_blend (0.1879) < c0_naive_puro (0.2020) < a_grid_1x2 (0.2039) < b_grid_totali (0.2067)
- test: ordine dal migliore al peggiore — c_naive_blend (0.1923) < c0_naive_puro (0.2030) < b_grid_totali (0.2046) < a_grid_1x2 (0.2054)

## Lettura

1. **La dipendenza tra le due teste esiste ed e' quella che il modello disegna, non un artefatto** (validation, media sulle partite): 1 + Over 2.5: modello +0.147 (griglia 1X2) / +0.151 (griglia Totali), dati +0.159; 2 + Under 2.5: modello -0.104 (griglia 1X2) / -0.100 (griglia Totali), dati -0.104; X + Over 2.5: modello -0.293 (griglia 1X2) / -0.291 (griglia Totali), dati -0.295. Il segno torna anche sul test e sul train; per X + Over 2.5 la correlazione e' forte e NEGATIVA (il pareggio vive di 0-0 e 1-1), per 1 + Over 2.5 e' media e POSITIVA. Chi moltiplica le due probabilita' sta imponendo rho = 0 a un blocco di eventi che rho lo ha, e lo sbaglio ha direzione diversa a seconda della combo.
2. **Sul Brier della combo primaria, pero', il termine di correlazione non emerge**: griglia − prodotto a marginali identiche vale +0.0007 (train), +0.0010 (validation), -0.0003 (test) sulla testa 1X2 e +0.0016 (train), +0.0016 (validation), -0.0001 (test) sulla testa Totali. L'unica casella fuori dall'IC bootstrap e' +0.0016 (train, testa Totali) e va nella direzione opposta: li' la griglia congiunta risulta PEGGIORE del prodotto. Detto in modo sgradevole ma esatto: su questa combo la scelta tra (a), (b) e (c) NON e' distinguibile con il Brier, quindi il Brier da solo non autorizza nessuna delle tre.
3. **Dove la correlazione pesa davvero e' il LIVELLO, cioe' il prezzo**: 1 + Over 2.5: prodotto naive -17.1% (train) -10.7% (validation) -17.4% (test); griglia congiunta -3.4% +1.4% -6.9%; 2 + Under 2.5: prodotto naive +31.1% (train) +25.2% (validation) +34.9% (test); griglia congiunta +21.1% +14.1% +23.7%; X + Over 2.5: prodotto naive +64.2% (train) +56.7% (validation) +46.1% (test); griglia congiunta -45.2% -44.2% -48.6%. Il prodotto naive sbaglia sempre dello stesso segno nei tre split (sottostima la 1 + Over di un sesto-quinto, sovrastima la X + Over di meta'), mentre la griglia congiunta riduce l'errore assoluto di livello in 8 casi su 9 (combo x split) e ne inverte il segno su 2 combo su 3: incorpora la dipendenza, ma non e' un correttivo neutro — dove le marginali Poisson sono gia' troppo sicure, la somma sulle celle le rende ancora piu' estreme. Per una combo il numero che conta e' questa distanza tra probabilita' mostrata e frequenza reale, e li' la correlazione costa un ordine di grandezza piu' di quanto il Brier faccia vedere.
4. **Perche' il prodotto naive vince la classifica Brier (e non perche' l'indipendenza sia vera)**: le marginali della testa 1X2 sono over-disperse in coda e la correlazione le amplifica. Nell'ultimo quintile della (a) su validation si promette 0.651, se ne vedono 0.402 (bias +0.249); nella (c), stessa coda di partite, si promette 0.475, se ne vedono 0.416 (bias +0.059). Moltiplicare due probabilita' minori di uno comprime la dispersione, la somma sulle celle della matrice la espande: sul Brier la compensazione accidentale del prodotto batte la joint coerente della griglia. E' un risultato giusto per la ragione sbagliata — leggerlo come 'la correlazione non serve' sarebbe un errore di lettura, non un risultato dell'audit.
5. **Quanto vale il solo termine omesso**: k stimato sul TRAIN vale 1.2067 sul prodotto mostrato e 1.1555 su quello puro. Applicato out-of-sample riporta vicino allo zero l'errore di livello della primaria (bias relativo validation -10.7% → +7.7%, test -17.4% → -0.3%) MA il Brier della primaria peggiora: Δ +0.0034 (IC [0.0008; 0.0060], fuori zero) su validation e +0.0009 (IC [-0.0015; 0.0036], dentro zero) su test. Sulle due combo di controllo, invece, la stessa correzione MIGLIORA il Brier in modo distinguibile: 2 + Under 2.5 Δ -0.0033 (IC [-0.0049; -0.0017], fuori zero) e X + Over 2.5 Δ -0.0024 (IC [-0.0036; -0.0013], fuori zero) su validation. k non e' unico: 1 + Over 2.5 1.207, 2 + Under 2.5 0.763, X + Over 2.5 0.609 — chi correggesse la correlazione con un fattore globale sbaglierebbe meta' delle combo per costruzione.

   E' il punto piu' scomodo dell'audit e va letto senza scorciatoie: sulla combo primaria le due cose si tirano in direzioni opposte (livello giusto, Brier peggiore), perche' il prodotto naive compensava con il suo difetto l'over-dispersione delle marginali. Ne segue che **il Brier non e' il criterio giusto per scegliere come costruire una probabilita' di combo**: premia lo shrinkage sulle code e su eventi rari perdona chi sottostima in modo uniforme. Il criterio da usare, se un giorno le combo si esporranno, e' il bias di calibrazione (e la coda), con il Brier come secondo parere.
6. **Le combo di controllo**: 2 + Under 2.5: Δ (griglia − prodotto, stesse marginali) -0.0051 su validation, IC [-0.0063; -0.0039] → MIGLIORE (IC senza zero) | X + Over 2.5: Δ (griglia − prodotto, stesse marginali) +0.0002 su validation, IC [-0.0011; 0.0014] → entro l'IC: rumore — su 2 + Under 2.5 la griglia congiunta batte il prodotto in modo distinguibile anche a marginali identiche; su X + Over 2.5 e sulla primaria resta dentro il rumore. Il meccanismo che separa i casi sta nelle colonne Bias: la correzione di correlazione conviene quando migliora il livello SENZA pagare in dispersione (2 + Under 2.5 su validation: joint 0.1478 contro prodotto-stessa-griglia 0.1704, reale 0.1296); non conviene quando recupera il livello ma allarga la coda oltre il vero (combo primaria, ultimo quintile 0.651 promesso contro 0.402 osservato).

**In sintesi, per chi dovesse mai esporre una probabilita' di combo**: nessuna delle tre versioni e' giusta su tutte le combo, e va detto senza scontorni. Sulla primaria la griglia congiunta riporta il livello verso la verita' (bias relativo validation -10.7% del prodotto contro +1.4% della griglia) e anche la 2 + Under 2.5 migliora (+25.2% → +14.1%), ma su X + Over 2.5 la griglia sbaglia nella direzione opposta e con modulo maggiore (-44.2% della griglia contro +56.7% del prodotto): li' la frequenza vera sta IN MEZZO alle due stime, e la matrice indipendente esagera la dipendenza negativa tra pareggio e gol. Il quadro onesto e': il prodotto naive ha un errore di livello sistematico e direzionalmente coerente (sottostima le combo vittoria+over, sovrastima pareggio+over e trasferta+under); la griglia congiunta e' l'unica che incorpora la dipendenza, ma eredita l'over-dispersione delle marginali Poisson e su quel tipo di stima la amplifica. Se un giorno le combo entreranno in scheda, la scelta va fatta su bias di livello e comportamento della coda (con la k per tipo di combo come pavimento economico di confronto), non sulla classifica Brier, che qui premia la cancellazione accidentale. Nessuna modifica di produzione e' suggerita da questo script: qui si misura, non si decide.

## Limiti dichiarati

1. **Marginali da snapshot xG statico, non la fonte point-in-time di produzione.** La testa Totali live legge `att0_pure`/`def0_pure` dalla finestra point-in-time di `get_league_engine` (F_season/PT19_CAP con shrinkage); qui si usano i lambda puri da snapshot xG come in `diagnose_form_totali`, per restare bit-identici a un audit gia' validato. Cio' sposta il LIVELLO delle marginali, non il confronto griglia-vs-prodotto: (a)/(b)/(c0) usano le stesse identiche marginali e differiscono solo per il termine di correlazione.
2. **Elo di replica** (K fisso, home advantage da config, niente boost xG), come in `diagnose_elo_ensemble`: la (c) usa il P(1) blendato con quell'Elo, non il rating live dell'app. Stesso limite di `clv_pinnacle_report.md` §Limiti.
3. **Matrice troncata a 15 reti e non rinormalizzata** (comportamento di produzione): le probabilita' di combo somma su quel supporto, quindi risultano coerenti con le marginali mostrate ma leggermente sotto la loro somma teorica.
4. **Cold start del TRAIN**: 2022/23 parte da DB vuoto; il warmup esclude le prime 60 partite/lega dal campione ma lo stato conserva il rumore residuo (stessa convenzione del grid search).
5. **Nessuna quota per le combo**: i database del repo non hanno quote 1X2+Totale, quindi qui si misura solo la CALIBRAZIONE della probabilita' di combo, non la sua convenienza. Un Brier migliore su una combo non implica un ROI positivo: per quello servirebbe il prezzo della combo, che non c'e'.
7. **Il Brier come unico criterio e' fuorviante su eventi rari**: per una combo con base rate 0.07-0.28 il termine E[p^2] domina la differenza tra due versioni, e un modello che sottostima in modo uniforme puo' risultare migliore anche se la sua frequenza media e' sbagliata del 17%. Per questo nel report le tabelle di bias/affidabilita' non sono un optional: senza, la classifica Brier porterebbe alla conclusione sbagliata ('la correlazione non serve').
6. **Un solo punto di osservazione temporale**: snapshot 2026-09; le conclusioni vanno lette come direzione, non come coefficiente di correlazione da cablare (stessa lezione dell'audit rho Dixon-Coles).

## Riferimenti incrociati

- `audit/results/elo_ensemble_diagnosis.md` e `audit/results/ensemble_weight_grid_search.md`: da cui vengono la testa 1X2 NORM-SUM e il peso d'insieme w;
- `audit/results/form_totali_diagnosis.md`: da cui viene la testa Totali a lambda puri;
- `audit/results/ensemble_scope_analisi_rapida.md`: mostra che l'1X2 blendato entra gia' nell'argmax a 7 mercati di `analisi_rapida_giornata`; questo audit aggiunge il pezzo mancante: cosa succede se 1X2 e Totali vengono combinati in un'unica scommessa.

