# Strato di calibrazione post-hoc: Temperature (1X2) e Beta (Over/GG) — audit sola lettura

*Generato: 2026-09-14T06:10:58+00:00 — script `audit/diagnose_calibration_layer.py`, nessuna modifica a SoccerMath/.*

## Protocollo (e l'errore che non si ripete)

Il tentativo precedente (Isotonic/Platt) era stato fittato su **validation e rivalutato sulla stessa validation**: il sovradattamento era invisibile ed e' emerso solo sul test. Qui **ogni parametro di calibrazione e' stimato esclusivamente sul TRAIN 2022/23+2023/24** (prime 60 partite/lega nello stato ma escluse dal campione, cold start); validation 2024/25 e test 2025/26 non vengono mai usati per stimare o ritoccare nulla. Le predizioni di train sono genuine predizioni walk-forward (lo stato vede solo partite precedenti), quindi fittare la calibrazione su di esse non e' leakage.

- 1X2: **temperature scaling** `q=softmax(log(p)/T)` sul vettore di probabilita', T unico (T=1 = identita'), MLE multinomiale solo su train, IC bootstrap 95% a 2000 resample stratificati per lega.
- O/U2.5 e GG/NG: **beta calibration** a 3 parametri mu(p)=sigmo(a·log p − b·log(1−p) + c), identita' in (1,1,0), MLE via IRLS solo su train, teste separate.
- Oltre alle basi attuali si ripete tutto sulle probabilita' **NegBin-pooled** dell'audit overdispersion (alpha di quella testa, stimata sullo stesso train): serve a vedere se le due correzioni si sommano o si sovrappongono.
- Brier e LogLoss con IC bootstrap sulla differenza appaiata (seed/2000 resample come gli altri audit); una differenza dentro l'IC e' rumore.

## Conformita' del protocollo (verificata, non dichiarata)

| Lega | n righe val+test | max\|scarto\| P(1),P(X),P(2) vs elo_ensemble | max\|scarto\| P(Over),P(GG) vs form_totali B | max\|scarto\| P(1) blendato vs combo | esiti identici |
|---|---:|---|---|---:|---|
| Serie A | 760 | 0.0e+00 | 0.0e+00 | 0.0e+00 | si |
| Premier League | 760 | 0.0e+00 | 0.0e+00 | 0.0e+00 | si |
| La Liga | 760 | 0.0e+00 | 0.0e+00 | 0.0e+00 | si |
| Bundesliga | 612 | 0.0e+00 | 0.0e+00 | 0.0e+00 | si |
| Ligue 1 | 612 | 0.0e+00 | 0.0e+00 | 0.0e+00 | si |

Scarto atteso **0.0e+00**: questo script non introduce un nuovo modello predittivo, usa lo stesso walk-forward degli ultimi due audit (testa 1X2 NORM-SUM + blend w=0.25, testa Totali modello B) e aggiunge solo la trasformazione post-hoc. L'invarianza di stato rispetto all'insieme di stagioni emesse e' verificata sul frame completo.

## Copertura campioni

| Lega | Train (fit calibrazione) | esclusi cold-start | Validation | Test |
|---|---:|---:|---:|---:|
| Serie A | 700 | 60 | 380 | 380 |
| Premier League | 700 | 60 | 380 | 380 |
| La Liga | 700 | 60 | 380 | 380 |
| Bundesliga | 552 | 60 | 306 | 306 |
| Ligue 1 | 626 | 60 | 306 | 306 |
| **AGGREGATO** | 3278 | 300 | 1752 | 1752 |

## 1. Temperature scaling 1X2 (stima SOLO su train)

| Base | T MLE | IC 95% bootstrap di T | include T=1? | % resample entro 0.02 da 1 |
|---|---:|---|---|---:|
| BLEND di produzione (0.25 Poisson + 0.75 Elo) | 0.9271 | [0.8563; 1.0069] | SI' (nessuna correzione dimostrabile) | 8.0% |
| Poisson puro testa 1X2 | 2.4919 | [2.2473; 2.7592] | NO | 0.0% |
| NegBin-pooled testa 1X2 (audit overdispersion) | 2.0456 | [1.8659; 2.2717] | NO | 0.0% |
| BLEND NegBin-pooled + Elo (0.25/0.75) | 0.8875 | [0.8202; 0.9630] | NO | 1.0% |

T>1 riscalda (meno sicurezza sui risultati estremi, come la NegBin); T<1 affilarebbe. Se l'IC include 1 per la base di produzione, il verdetto per quella base e' esplicitamente 'nessun disallineamento di confidenza da correggere'.

## 2. Beta calibration binaria (stima SOLO su train)

Identita' = (a,b,c)=(1,1,0): in tal caso mu(p)=p.

| Mercato/base | a | IC 95% a | b | IC 95% b | c | IC 95% c | identita' dentro gli IC? |
|---|---:|---|---:|---|---:|---|---|
| Over 2.5, Poisson testa Totali (attuale) | 0.3069 | [0.0155; 0.6104] | 0.0369 | [-0.1967; 0.2675] | 0.3358 | [-0.0607; 0.7420] | NO |
| Over 2.5, NegBin-pooled testa Totali | 0.3233 | [-0.0148; 0.6938] | 0.0615 | [-0.3127; 0.4176] | 0.3453 | [-0.1736; 0.9227] | NO |
| GG, Poisson testa Totali (attuale) | -0.0313 | [-0.2561; 0.2883] | 0.5934 | [0.2213; 0.9506] | -0.2367 | [-0.6486; 0.2601] | NO |
| GG, NegBin-pooled testa Totali | -0.0712 | [-0.3047; 0.2619] | 0.8176 | [0.2911; 1.2796] | -0.3470 | [-0.8091; 0.2475] | NO |

## 3. Valutazione fuori campione: Brier e LogLoss

Delta = calibrato − originale (negativo = migliora); IC 95% bootstrap sulla differenza appaiata. Prima l'aggregato 5 leghe, poi il dettaglio per lega (solo Brier).

### 1X2 — BLEND di produzione (0.25 Poisson + 0.75 Elo)

| Split | Brier orig | Brier cal | Δ Brier (IC 95%) | LogLoss orig | LogLoss cal | Δ LL (IC 95%) |
|---|---:|---:|---:|---:|---:|---:|
| validation | 0.5918 | 0.5928 | +0.0010 [-0.0001; 0.0021] | 0.9932 | 0.9948 | +0.0016 [-0.0001; 0.0033] |
| test | 0.5917 | 0.5929 | +0.0012 [0.0001; 0.0021] | 0.9930 | 0.9948 | +0.0018 [0.0001; 0.0035] |

| Lega | Split | Brier orig | Brier cal | Δ | verdetto |
|---|---|---:|---:|---:|---|
| Serie A | validation | 0.5935 | 0.5944 | +0.0009 | entro l'IC: rumore |
| Serie A | test | 0.5901 | 0.5915 | +0.0014 | entro l'IC: rumore |
| Premier League | validation | 0.5908 | 0.5924 | +0.0015 | entro l'IC: rumore |
| Premier League | test | 0.6123 | 0.6145 | +0.0022 | entro l'IC: rumore |
| La Liga | validation | 0.5805 | 0.5807 | +0.0002 | entro l'IC: rumore |
| La Liga | test | 0.5836 | 0.5842 | +0.0006 | entro l'IC: rumore |
| Bundesliga | validation | 0.6116 | 0.6143 | +0.0027 | entro l'IC: rumore |
| Bundesliga | test | 0.5780 | 0.5787 | +0.0007 | entro l'IC: rumore |
| Ligue 1 | validation | 0.5852 | 0.5848 | -0.0003 | entro l'IC: rumore |
| Ligue 1 | test | 0.5918 | 0.5926 | +0.0008 | entro l'IC: rumore |

### 1X2 — Poisson puro testa 1X2

| Split | Brier orig | Brier cal | Δ Brier (IC 95%) | LogLoss orig | LogLoss cal | Δ LL (IC 95%) |
|---|---:|---:|---:|---:|---:|---:|
| validation | 0.6523 | 0.6148 | -0.0375 [-0.0497; -0.0249] | 1.1344 | 1.0279 | -0.1065 [-0.1336; -0.0792] |
| test | 0.6471 | 0.6103 | -0.0368 [-0.0490; -0.0245] | 1.1154 | 1.0202 | -0.0952 [-0.1220; -0.0707] |

| Lega | Split | Brier orig | Brier cal | Δ | verdetto |
|---|---|---:|---:|---:|---|
| Serie A | validation | 0.6740 | 0.6179 | -0.0562 | MIGLIORE (IC senza zero) |
| Serie A | test | 0.6322 | 0.6010 | -0.0312 | MIGLIORE (IC senza zero) |
| Premier League | validation | 0.6428 | 0.6106 | -0.0322 | MIGLIORE (IC senza zero) |
| Premier League | test | 0.6577 | 0.6190 | -0.0387 | MIGLIORE (IC senza zero) |
| La Liga | validation | 0.6237 | 0.6038 | -0.0198 | entro l'IC: rumore |
| La Liga | test | 0.6350 | 0.6055 | -0.0295 | MIGLIORE (IC senza zero) |
| Bundesliga | validation | 0.6669 | 0.6143 | -0.0527 | MIGLIORE (IC senza zero) |
| Bundesliga | test | 0.6632 | 0.6080 | -0.0552 | MIGLIORE (IC senza zero) |
| Ligue 1 | validation | 0.6580 | 0.6306 | -0.0274 | entro l'IC: rumore |
| Ligue 1 | test | 0.6513 | 0.6194 | -0.0319 | MIGLIORE (IC senza zero) |

### 1X2 — NegBin-pooled testa 1X2 (audit overdispersion)

| Split | Brier orig | Brier cal | Δ Brier (IC 95%) | LogLoss orig | LogLoss cal | Δ LL (IC 95%) |
|---|---:|---:|---:|---:|---:|---:|
| validation | 0.6366 | 0.6140 | -0.0225 [-0.0319; -0.0124] | 1.0862 | 1.0272 | -0.0590 [-0.0787; -0.0396] |
| test | 0.6325 | 0.6106 | -0.0218 [-0.0313; -0.0127] | 1.0754 | 1.0215 | -0.0540 [-0.0720; -0.0356] |

| Lega | Split | Brier orig | Brier cal | Δ | verdetto |
|---|---|---:|---:|---:|---|
| Serie A | validation | 0.6544 | 0.6191 | -0.0353 | MIGLIORE (IC senza zero) |
| Serie A | test | 0.6188 | 0.6009 | -0.0179 | entro l'IC: rumore |
| Premier League | validation | 0.6278 | 0.6099 | -0.0179 | entro l'IC: rumore |
| Premier League | test | 0.6420 | 0.6192 | -0.0228 | MIGLIORE (IC senza zero) |
| La Liga | validation | 0.6132 | 0.6031 | -0.0101 | entro l'IC: rumore |
| La Liga | test | 0.6246 | 0.6078 | -0.0168 | entro l'IC: rumore |
| Bundesliga | validation | 0.6486 | 0.6134 | -0.0352 | MIGLIORE (IC senza zero) |
| Bundesliga | test | 0.6433 | 0.6080 | -0.0353 | MIGLIORE (IC senza zero) |
| Ligue 1 | validation | 0.6425 | 0.6272 | -0.0153 | entro l'IC: rumore |
| Ligue 1 | test | 0.6365 | 0.6183 | -0.0182 | entro l'IC: rumore |

### 1X2 — BLEND NegBin-pooled + Elo (0.25/0.75)

| Split | Brier orig | Brier cal | Δ Brier (IC 95%) | LogLoss orig | LogLoss cal | Δ LL (IC 95%) |
|---|---:|---:|---:|---:|---:|---:|
| validation | 0.5912 | 0.5924 | +0.0012 [-0.0004; 0.0029] | 0.9923 | 0.9942 | +0.0020 [-0.0007; 0.0046] |
| test | 0.5913 | 0.5929 | +0.0016 [-0.0001; 0.0032] | 0.9926 | 0.9949 | +0.0023 [-0.0003; 0.0050] |

| Lega | Split | Brier orig | Brier cal | Δ | verdetto |
|---|---|---:|---:|---:|---|
| Serie A | validation | 0.5923 | 0.5933 | +0.0010 | entro l'IC: rumore |
| Serie A | test | 0.5896 | 0.5915 | +0.0019 | entro l'IC: rumore |
| Premier League | validation | 0.5904 | 0.5925 | +0.0021 | entro l'IC: rumore |
| Premier League | test | 0.6117 | 0.6149 | +0.0032 | entro l'IC: rumore |
| La Liga | validation | 0.5803 | 0.5803 | +0.0000 | entro l'IC: rumore |
| La Liga | test | 0.5835 | 0.5843 | +0.0008 | entro l'IC: rumore |
| Bundesliga | validation | 0.6112 | 0.6153 | +0.0041 | entro l'IC: rumore |
| Bundesliga | test | 0.5776 | 0.5783 | +0.0007 | entro l'IC: rumore |
| Ligue 1 | validation | 0.5842 | 0.5834 | -0.0008 | entro l'IC: rumore |
| Ligue 1 | test | 0.5914 | 0.5924 | +0.0009 | entro l'IC: rumore |

### O/U2.5 — Over 2.5, Poisson testa Totali (attuale)

| Split | Brier orig | Brier cal | Δ Brier (IC 95%) | LogLoss orig | LogLoss cal | Δ LL (IC 95%) |
|---|---:|---:|---:|---:|---:|---:|
| validation | 0.2744 | 0.2482 | -0.0262 [-0.0334; -0.0191] | 0.7564 | 0.6895 | -0.0669 [-0.0846; -0.0491] |
| test | 0.2701 | 0.2473 | -0.0228 [-0.0301; -0.0155] | 0.7507 | 0.6878 | -0.0629 [-0.0825; -0.0443] |

| Lega | Split | Brier orig | Brier cal | Δ | verdetto |
|---|---|---:|---:|---:|---|
| Serie A | validation | 0.2896 | 0.2527 | -0.0369 | MIGLIORE (IC senza zero) |
| Serie A | test | 0.2900 | 0.2524 | -0.0375 | MIGLIORE (IC senza zero) |
| Premier League | validation | 0.2634 | 0.2456 | -0.0178 | MIGLIORE (IC senza zero) |
| Premier League | test | 0.2659 | 0.2473 | -0.0186 | MIGLIORE (IC senza zero) |
| La Liga | validation | 0.2572 | 0.2479 | -0.0093 | entro l'IC: rumore |
| La Liga | test | 0.2538 | 0.2464 | -0.0074 | entro l'IC: rumore |
| Bundesliga | validation | 0.2738 | 0.2424 | -0.0313 | MIGLIORE (IC senza zero) |
| Bundesliga | test | 0.2686 | 0.2397 | -0.0289 | MIGLIORE (IC senza zero) |
| Ligue 1 | validation | 0.2912 | 0.2518 | -0.0394 | MIGLIORE (IC senza zero) |
| Ligue 1 | test | 0.2725 | 0.2498 | -0.0227 | MIGLIORE (IC senza zero) |

### O/U2.5 — Over 2.5, NegBin-pooled testa Totali

| Split | Brier orig | Brier cal | Δ Brier (IC 95%) | LogLoss orig | LogLoss cal | Δ LL (IC 95%) |
|---|---:|---:|---:|---:|---:|---:|
| validation | 0.2694 | 0.2482 | -0.0212 [-0.0278; -0.0149] | 0.7404 | 0.6895 | -0.0509 [-0.0660; -0.0356] |
| test | 0.2661 | 0.2473 | -0.0188 [-0.0255; -0.0121] | 0.7368 | 0.6877 | -0.0491 [-0.0654; -0.0318] |

| Lega | Split | Brier orig | Brier cal | Δ | verdetto |
|---|---|---:|---:|---:|---|
| Serie A | validation | 0.2830 | 0.2527 | -0.0303 | MIGLIORE (IC senza zero) |
| Serie A | test | 0.2830 | 0.2523 | -0.0307 | MIGLIORE (IC senza zero) |
| Premier League | validation | 0.2579 | 0.2456 | -0.0124 | MIGLIORE (IC senza zero) |
| Premier League | test | 0.2607 | 0.2473 | -0.0134 | MIGLIORE (IC senza zero) |
| La Liga | validation | 0.2547 | 0.2479 | -0.0068 | entro l'IC: rumore |
| La Liga | test | 0.2522 | 0.2464 | -0.0058 | entro l'IC: rumore |
| Bundesliga | validation | 0.2681 | 0.2424 | -0.0257 | MIGLIORE (IC senza zero) |
| Bundesliga | test | 0.2666 | 0.2397 | -0.0269 | MIGLIORE (IC senza zero) |
| Ligue 1 | validation | 0.2861 | 0.2518 | -0.0343 | MIGLIORE (IC senza zero) |
| Ligue 1 | test | 0.2684 | 0.2498 | -0.0186 | MIGLIORE (IC senza zero) |

### GG/NG — GG, Poisson testa Totali (attuale)

| Split | Brier orig | Brier cal | Δ Brier (IC 95%) | LogLoss orig | LogLoss cal | Δ LL (IC 95%) |
|---|---:|---:|---:|---:|---:|---:|
| validation | 0.2788 | 0.2484 | -0.0304 [-0.0374; -0.0237] | 0.7682 | 0.6899 | -0.0783 [-0.0990; -0.0590] |
| test | 0.2731 | 0.2478 | -0.0253 [-0.0326; -0.0176] | 0.7596 | 0.6887 | -0.0709 [-0.0936; -0.0503] |

| Lega | Split | Brier orig | Brier cal | Δ | verdetto |
|---|---|---:|---:|---:|---|
| Serie A | validation | 0.2987 | 0.2532 | -0.0455 | MIGLIORE (IC senza zero) |
| Serie A | test | 0.2845 | 0.2531 | -0.0314 | MIGLIORE (IC senza zero) |
| Premier League | validation | 0.2571 | 0.2432 | -0.0139 | MIGLIORE (IC senza zero) |
| Premier League | test | 0.2603 | 0.2461 | -0.0142 | MIGLIORE (IC senza zero) |
| La Liga | validation | 0.2785 | 0.2494 | -0.0291 | MIGLIORE (IC senza zero) |
| La Liga | test | 0.2683 | 0.2448 | -0.0236 | MIGLIORE (IC senza zero) |
| Bundesliga | validation | 0.2822 | 0.2456 | -0.0366 | MIGLIORE (IC senza zero) |
| Bundesliga | test | 0.2908 | 0.2429 | -0.0479 | MIGLIORE (IC senza zero) |
| Ligue 1 | validation | 0.2780 | 0.2504 | -0.0276 | MIGLIORE (IC senza zero) |
| Ligue 1 | test | 0.2629 | 0.2518 | -0.0111 | entro l'IC: rumore |

### GG/NG — GG, NegBin-pooled testa Totali

| Split | Brier orig | Brier cal | Δ Brier (IC 95%) | LogLoss orig | LogLoss cal | Δ LL (IC 95%) |
|---|---:|---:|---:|---:|---:|---:|
| validation | 0.2844 | 0.2486 | -0.0358 [-0.0440; -0.0278] | 0.7813 | 0.6904 | -0.0909 [-0.1136; -0.0699] |
| test | 0.2788 | 0.2478 | -0.0309 [-0.0391; -0.0231] | 0.7724 | 0.6889 | -0.0835 [-0.1068; -0.0607] |

| Lega | Split | Brier orig | Brier cal | Δ | verdetto |
|---|---|---:|---:|---:|---|
| Serie A | validation | 0.3046 | 0.2535 | -0.0511 | MIGLIORE (IC senza zero) |
| Serie A | test | 0.2878 | 0.2536 | -0.0342 | MIGLIORE (IC senza zero) |
| Premier League | validation | 0.2600 | 0.2432 | -0.0167 | MIGLIORE (IC senza zero) |
| Premier League | test | 0.2624 | 0.2460 | -0.0164 | MIGLIORE (IC senza zero) |
| La Liga | validation | 0.2873 | 0.2493 | -0.0380 | MIGLIORE (IC senza zero) |
| La Liga | test | 0.2799 | 0.2447 | -0.0351 | MIGLIORE (IC senza zero) |
| Bundesliga | validation | 0.2866 | 0.2461 | -0.0405 | MIGLIORE (IC senza zero) |
| Bundesliga | test | 0.2989 | 0.2428 | -0.0562 | MIGLIORE (IC senza zero) |
| Ligue 1 | validation | 0.2839 | 0.2509 | -0.0330 | MIGLIORE (IC senza zero) |
| Ligue 1 | test | 0.2662 | 0.2519 | -0.0143 | entro l'IC: rumore |

### 3b. Confronto con il predittore costante (quanta risoluzione resta?)

Una mappa di calibrazione monotona conserva l'ordinamento delle partite (Spearman = 1 per costruzione): cambia solo il LIVELLO delle probabilita', mai la classifica. Se dopo la calibrazione il Brier raggiunge quello del predittore costante (sempre la frequenza base del campione, in-sample), il miglioramento e' ottenuto ritirando quasi tutta la discriminazione: e' un guadagno formale ma operativamente vuol dire 'di quella probabilita' per partita non resta nulla'.

| Mercato/base | Split | Brier originale | Brier calibrato | Brier costante | skill residua calibrato vs costante |
|---|---|---:|---:|---:|---:|
| 1X2: BLEND di produzione (0.25 Poisson + 0.75 Elo) | validation | 0.5918 | 0.5928 | 0.6521 | +9.1% |
| 1X2: BLEND di produzione (0.25 Poisson + 0.75 Elo) | test | 0.5917 | 0.5929 | 0.6483 | +8.6% |
| 1X2: Poisson puro testa 1X2 | validation | 0.6523 | 0.6148 | 0.6521 | +5.7% |
| 1X2: Poisson puro testa 1X2 | test | 0.6471 | 0.6103 | 0.6483 | +5.9% |
| 1X2: NegBin-pooled testa 1X2 (audit overdispersion) | validation | 0.6366 | 0.6140 | 0.6521 | +5.8% |
| 1X2: NegBin-pooled testa 1X2 (audit overdispersion) | test | 0.6325 | 0.6106 | 0.6483 | +5.8% |
| 1X2: BLEND NegBin-pooled + Elo (0.25/0.75) | validation | 0.5912 | 0.5924 | 0.6521 | +9.2% |
| 1X2: BLEND NegBin-pooled + Elo (0.25/0.75) | test | 0.5913 | 0.5929 | 0.6483 | +8.5% |
| O/U2.5: Over 2.5, Poisson testa Totali (attuale) | validation | 0.2744 | 0.2482 | 0.2488 | +0.3% |
| O/U2.5: Over 2.5, Poisson testa Totali (attuale) | test | 0.2701 | 0.2473 | 0.2491 | +0.7% |
| O/U2.5: Over 2.5, NegBin-pooled testa Totali | validation | 0.2694 | 0.2482 | 0.2488 | +0.3% |
| O/U2.5: Over 2.5, NegBin-pooled testa Totali | test | 0.2661 | 0.2473 | 0.2491 | +0.7% |
| GG/NG: GG, Poisson testa Totali (attuale) | validation | 0.2788 | 0.2484 | 0.2472 | -0.5% |
| GG/NG: GG, Poisson testa Totali (attuale) | test | 0.2731 | 0.2478 | 0.2485 | +0.3% |
| GG/NG: GG, NegBin-pooled testa Totali | validation | 0.2844 | 0.2486 | 0.2472 | -0.6% |
| GG/NG: GG, NegBin-pooled testa Totali | test | 0.2788 | 0.2478 | 0.2485 | +0.3% |

Skill > 0 = la versione calibrata sa ancora distinguere le partite meglio dell'ignoranza della frequenza fissa; skill ~ 0 o negativa = la calibrazione ha di fatto cancellato la testa predittiva.

## 4. TEST DI OVERFITTING ESPLICITO (sezione dedicata)

Stessa riga per ogni variante: guadagno IN-SAMPLE sul train (dove il modello e' stato fittato, solo riferimento), poi delta su validation e su test **separatamente**, Brier e LogLoss. Il tentativo fallito in passato mostrava un delta train/validation gradevole e un test che invertiva. 'Tiene?' = SI' solo se il delta Brier e' negativo con IC sotto zero (o al piu' non significativo ma negativo) in ENTRAMBI gli split, senza inversione di segno, e la LogLoss non peggiora in modo significativo.

| Variante | ΔBrier train (in-sample) | ΔBrier validation (IC) | ΔBrier test (IC) | ΔLL validation | ΔLL test | Tiene su V e T? |
|---|---:|---:|---:|---:|---:|---|
| 1X2: BLEND di produzione (0.25 Poisson + 0.75 Elo) | -0.0004 | +0.0010 [-0.0001; 0.0021] | +0.0012 [0.0001; 0.0021] | +0.0016 [-0.0001; 0.0033] | +0.0018 [0.0001; 0.0035] | NO: peggiora in modo significativo |
| 1X2: Poisson puro testa 1X2 | -0.0420 | -0.0375 [-0.0497; -0.0249] | -0.0368 [-0.0490; -0.0245] | -0.1065 [-0.1336; -0.0792] | -0.0952 [-0.1220; -0.0707] | SI', IC fuori zero su entrambi |
| 1X2: NegBin-pooled testa 1X2 (audit overdispersion) | -0.0263 | -0.0225 [-0.0319; -0.0124] | -0.0218 [-0.0313; -0.0127] | -0.0590 [-0.0787; -0.0396] | -0.0540 [-0.0720; -0.0356] | SI', IC fuori zero su entrambi |
| 1X2: BLEND NegBin-pooled + Elo (0.25/0.75) | -0.0009 | +0.0012 [-0.0004; 0.0029] | +0.0016 [-0.0001; 0.0032] | +0.0020 [-0.0007; 0.0046] | +0.0023 [-0.0003; 0.0050] | NO: inversione/instabilita' |
| O/U2.5: Over 2.5, Poisson testa Totali (attuale) | -0.0252 | -0.0262 [-0.0334; -0.0191] | -0.0228 [-0.0301; -0.0155] | -0.0669 [-0.0846; -0.0491] | -0.0629 [-0.0825; -0.0443] | SI', IC fuori zero su entrambi |
| O/U2.5: Over 2.5, NegBin-pooled testa Totali | -0.0201 | -0.0212 [-0.0278; -0.0149] | -0.0188 [-0.0255; -0.0121] | -0.0509 [-0.0660; -0.0356] | -0.0491 [-0.0654; -0.0318] | SI', IC fuori zero su entrambi |
| GG/NG: GG, Poisson testa Totali (attuale) | -0.0205 | -0.0304 [-0.0374; -0.0237] | -0.0253 [-0.0326; -0.0176] | -0.0783 [-0.0990; -0.0590] | -0.0709 [-0.0936; -0.0503] | SI', IC fuori zero su entrambi |
| GG/NG: GG, NegBin-pooled testa Totali | -0.0268 | -0.0358 [-0.0440; -0.0278] | -0.0309 [-0.0391; -0.0231] | -0.0909 [-0.1136; -0.0699] | -0.0835 [-0.1068; -0.0607] | SI', IC fuori zero su entrambi |

Nota metodologica: il delta in-sample e' sempre ottimistico per costruzione (gli stessi dati definiscono T o beta); e' messo solo per mostrare la dimensione dell'ottimismo e confrontarla col fuori-campione. Se il guadagno train e' grande ma validation/test no, quello e' sovradattamento.

## 5. Affidabilita' per quintili: originale vs calibrato

Stessa lente degli ultimi due audit (Q1/Q5 in grassetto). Per l'1X2 si usano gli esiti 1 e 2 (le code dove la sovra-sicurezza e' massima) del blend di produzione e della base NegBin+Elo; per i mercati binari le basi Poisson e NegBin-pooled.

### VALIDATION

**1X2 blend di produzione, esito 1 (casa) — validation (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| originale | **Q1** | 351 | 0.2170 | 0.1795 | +0.0375 |
| originale | Q2 | 350 | 0.3368 | 0.2971 | +0.0396 |
| originale | Q3 | 350 | 0.4346 | 0.4229 | +0.0117 |
| originale | Q4 | 350 | 0.5412 | 0.5000 | +0.0412 |
| originale | **Q5** | 351 | 0.7110 | 0.7009 | +0.0102 |
| calibrato | **Q1** | 351 | 0.2083 | 0.1795 | +0.0288 |
| calibrato | Q2 | 350 | 0.3367 | 0.2971 | +0.0395 |
| calibrato | Q3 | 350 | 0.4428 | 0.4229 | +0.0199 |
| calibrato | Q4 | 350 | 0.5578 | 0.5000 | +0.0578 |
| calibrato | **Q5** | 351 | 0.7348 | 0.7009 | +0.0339 |

**1X2 blend di produzione, esito 2 (trasferta) — validation (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| originale | **Q1** | 351 | 0.1422 | 0.1054 | +0.0368 |
| originale | Q2 | 350 | 0.2322 | 0.2457 | -0.0136 |
| originale | Q3 | 350 | 0.3077 | 0.3171 | -0.0094 |
| originale | Q4 | 350 | 0.4013 | 0.4029 | -0.0016 |
| originale | **Q5** | 351 | 0.5712 | 0.5812 | -0.0100 |
| calibrato | **Q1** | 351 | 0.1303 | 0.1054 | +0.0249 |
| calibrato | Q2 | 350 | 0.2240 | 0.2457 | -0.0217 |
| calibrato | Q3 | 350 | 0.3052 | 0.3171 | -0.0120 |
| calibrato | Q4 | 350 | 0.4066 | 0.4029 | +0.0037 |
| calibrato | **Q5** | 351 | 0.5889 | 0.5812 | +0.0077 |

**1X2 NegBin-pooled+Elo, esito 1 (casa) — validation (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| originale | **Q1** | 351 | 0.2217 | 0.1766 | +0.0451 |
| originale | Q2 | 350 | 0.3391 | 0.3057 | +0.0334 |
| originale | Q3 | 350 | 0.4327 | 0.4171 | +0.0155 |
| originale | Q4 | 350 | 0.5338 | 0.5029 | +0.0310 |
| originale | **Q5** | 351 | 0.6993 | 0.6980 | +0.0013 |
| calibrato | **Q1** | 351 | 0.2083 | 0.1766 | +0.0317 |
| calibrato | Q2 | 350 | 0.3392 | 0.3057 | +0.0335 |
| calibrato | Q3 | 350 | 0.4456 | 0.4171 | +0.0284 |
| calibrato | Q4 | 350 | 0.5596 | 0.5029 | +0.0568 |
| calibrato | **Q5** | 351 | 0.7366 | 0.6980 | +0.0386 |

**1X2 NegBin-pooled+Elo, esito 2 (trasferta) — validation (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| originale | **Q1** | 351 | 0.1469 | 0.1026 | +0.0444 |
| originale | Q2 | 350 | 0.2370 | 0.2457 | -0.0087 |
| originale | Q3 | 350 | 0.3094 | 0.3143 | -0.0049 |
| originale | Q4 | 350 | 0.3980 | 0.4057 | -0.0077 |
| originale | **Q5** | 351 | 0.5607 | 0.5840 | -0.0233 |
| calibrato | **Q1** | 351 | 0.1283 | 0.1026 | +0.0257 |
| calibrato | Q2 | 350 | 0.2244 | 0.2486 | -0.0242 |
| calibrato | Q3 | 350 | 0.3054 | 0.3114 | -0.0060 |
| calibrato | Q4 | 350 | 0.4061 | 0.4057 | +0.0004 |
| calibrato | **Q5** | 351 | 0.5882 | 0.5840 | +0.0042 |

**O/U2.5: Over 2.5, Poisson testa Totali (attuale) — validation (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| originale | **Q1** | 351 | 0.2535 | 0.5043 | -0.2507 |
| originale | Q2 | 350 | 0.3905 | 0.5057 | -0.1153 |
| originale | Q3 | 350 | 0.5051 | 0.5314 | -0.0263 |
| originale | Q4 | 350 | 0.6296 | 0.5429 | +0.0868 |
| originale | **Q5** | 351 | 0.7876 | 0.5869 | +0.2007 |
| calibrato | **Q1** | 351 | 0.4782 | 0.5043 | -0.0261 |
| calibrato | Q2 | 350 | 0.5161 | 0.5057 | +0.0104 |
| calibrato | Q3 | 350 | 0.5378 | 0.5314 | +0.0064 |
| calibrato | Q4 | 350 | 0.5573 | 0.5429 | +0.0144 |
| calibrato | **Q5** | 351 | 0.5796 | 0.5869 | -0.0073 |

**O/U2.5: Over 2.5, NegBin-pooled testa Totali — validation (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| originale | **Q1** | 351 | 0.2575 | 0.5043 | -0.2468 |
| originale | Q2 | 350 | 0.3822 | 0.5114 | -0.1292 |
| originale | Q3 | 350 | 0.4828 | 0.5286 | -0.0458 |
| originale | Q4 | 350 | 0.5896 | 0.5429 | +0.0468 |
| originale | **Q5** | 351 | 0.7286 | 0.5840 | +0.1445 |
| calibrato | **Q1** | 351 | 0.4785 | 0.5043 | -0.0258 |
| calibrato | Q2 | 350 | 0.5158 | 0.5114 | +0.0043 |
| calibrato | Q3 | 350 | 0.5374 | 0.5286 | +0.0089 |
| calibrato | Q4 | 350 | 0.5570 | 0.5429 | +0.0141 |
| calibrato | **Q5** | 351 | 0.5803 | 0.5840 | -0.0038 |

**GG/NG: GG, Poisson testa Totali (attuale) — validation (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| originale | **Q1** | 351 | 0.2323 | 0.5442 | -0.3119 |
| originale | Q2 | 350 | 0.3691 | 0.5771 | -0.2081 |
| originale | Q3 | 350 | 0.4485 | 0.5486 | -0.1001 |
| originale | Q4 | 350 | 0.5387 | 0.5200 | +0.0187 |
| originale | **Q5** | 351 | 0.6793 | 0.5726 | +0.1067 |
| calibrato | **Q1** | 351 | 0.4938 | 0.5442 | -0.0504 |
| calibrato | Q2 | 350 | 0.5171 | 0.5771 | -0.0601 |
| calibrato | Q3 | 350 | 0.5355 | 0.5486 | -0.0131 |
| calibrato | Q4 | 350 | 0.5604 | 0.5200 | +0.0404 |
| calibrato | **Q5** | 351 | 0.6142 | 0.5726 | +0.0415 |

**GG/NG: GG, NegBin-pooled testa Totali — validation (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| originale | **Q1** | 351 | 0.2136 | 0.5442 | -0.3306 |
| originale | Q2 | 350 | 0.3354 | 0.5771 | -0.2417 |
| originale | Q3 | 350 | 0.4048 | 0.5486 | -0.1438 |
| originale | Q4 | 350 | 0.4838 | 0.5286 | -0.0448 |
| originale | **Q5** | 351 | 0.6092 | 0.5641 | +0.0451 |
| calibrato | **Q1** | 351 | 0.4934 | 0.5584 | -0.0650 |
| calibrato | Q2 | 350 | 0.5170 | 0.5743 | -0.0573 |
| calibrato | Q3 | 350 | 0.5355 | 0.5371 | -0.0016 |
| calibrato | Q4 | 350 | 0.5612 | 0.5286 | +0.0327 |
| calibrato | **Q5** | 351 | 0.6147 | 0.5641 | +0.0506 |

### TEST

**1X2 blend di produzione, esito 1 (casa) — test (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| originale | **Q1** | 351 | 0.2116 | 0.1909 | +0.0207 |
| originale | Q2 | 350 | 0.3332 | 0.3714 | -0.0382 |
| originale | Q3 | 350 | 0.4301 | 0.4200 | +0.0101 |
| originale | Q4 | 350 | 0.5366 | 0.4829 | +0.0537 |
| originale | **Q5** | 351 | 0.7172 | 0.7350 | -0.0179 |
| calibrato | **Q1** | 351 | 0.2026 | 0.1909 | +0.0117 |
| calibrato | Q2 | 350 | 0.3328 | 0.3714 | -0.0386 |
| calibrato | Q3 | 350 | 0.4379 | 0.4200 | +0.0179 |
| calibrato | Q4 | 350 | 0.5528 | 0.4829 | +0.0699 |
| calibrato | **Q5** | 351 | 0.7409 | 0.7350 | +0.0058 |

**1X2 blend di produzione, esito 2 (trasferta) — test (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| originale | **Q1** | 351 | 0.1388 | 0.0997 | +0.0391 |
| originale | Q2 | 350 | 0.2348 | 0.2286 | +0.0062 |
| originale | Q3 | 350 | 0.3101 | 0.2857 | +0.0244 |
| originale | Q4 | 350 | 0.4054 | 0.3543 | +0.0511 |
| originale | **Q5** | 351 | 0.5775 | 0.5584 | +0.0190 |
| calibrato | **Q1** | 351 | 0.1269 | 0.0997 | +0.0272 |
| calibrato | Q2 | 350 | 0.2269 | 0.2286 | -0.0017 |
| calibrato | Q3 | 350 | 0.3078 | 0.2857 | +0.0220 |
| calibrato | Q4 | 350 | 0.4110 | 0.3543 | +0.0567 |
| calibrato | **Q5** | 351 | 0.5956 | 0.5584 | +0.0372 |

**1X2 NegBin-pooled+Elo, esito 1 (casa) — test (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| originale | **Q1** | 351 | 0.2160 | 0.1909 | +0.0252 |
| originale | Q2 | 350 | 0.3362 | 0.3714 | -0.0353 |
| originale | Q3 | 350 | 0.4282 | 0.4171 | +0.0111 |
| originale | Q4 | 350 | 0.5296 | 0.4943 | +0.0353 |
| originale | **Q5** | 351 | 0.7053 | 0.7265 | -0.0212 |
| calibrato | **Q1** | 351 | 0.2021 | 0.1909 | +0.0113 |
| calibrato | Q2 | 350 | 0.3358 | 0.3686 | -0.0327 |
| calibrato | Q3 | 350 | 0.4406 | 0.4200 | +0.0206 |
| calibrato | Q4 | 350 | 0.5548 | 0.4943 | +0.0605 |
| calibrato | **Q5** | 351 | 0.7425 | 0.7265 | +0.0160 |

**1X2 NegBin-pooled+Elo, esito 2 (trasferta) — test (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| originale | **Q1** | 351 | 0.1433 | 0.1054 | +0.0379 |
| originale | Q2 | 350 | 0.2392 | 0.2171 | +0.0221 |
| originale | Q3 | 350 | 0.3115 | 0.2971 | +0.0144 |
| originale | Q4 | 350 | 0.4012 | 0.3457 | +0.0555 |
| originale | **Q5** | 351 | 0.5672 | 0.5613 | +0.0059 |
| calibrato | **Q1** | 351 | 0.1247 | 0.1054 | +0.0193 |
| calibrato | Q2 | 350 | 0.2269 | 0.2229 | +0.0040 |
| calibrato | Q3 | 350 | 0.3079 | 0.2886 | +0.0193 |
| calibrato | Q4 | 350 | 0.4098 | 0.3486 | +0.0613 |
| calibrato | **Q5** | 351 | 0.5953 | 0.5613 | +0.0341 |

**O/U2.5: Over 2.5, Poisson testa Totali (attuale) — test (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| originale | **Q1** | 351 | 0.2347 | 0.4929 | -0.2582 |
| originale | Q2 | 350 | 0.3871 | 0.4771 | -0.0900 |
| originale | Q3 | 350 | 0.4947 | 0.5314 | -0.0368 |
| originale | Q4 | 350 | 0.6105 | 0.5400 | +0.0705 |
| originale | **Q5** | 351 | 0.7740 | 0.6097 | +0.1644 |
| calibrato | **Q1** | 351 | 0.4670 | 0.4929 | -0.0259 |
| calibrato | Q2 | 350 | 0.5154 | 0.4771 | +0.0382 |
| calibrato | Q3 | 350 | 0.5361 | 0.5314 | +0.0046 |
| calibrato | Q4 | 350 | 0.5545 | 0.5400 | +0.0145 |
| calibrato | **Q5** | 351 | 0.5777 | 0.6097 | -0.0320 |

**O/U2.5: Over 2.5, NegBin-pooled testa Totali — test (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| originale | **Q1** | 351 | 0.2393 | 0.4929 | -0.2536 |
| originale | Q2 | 350 | 0.3791 | 0.4800 | -0.1009 |
| originale | Q3 | 350 | 0.4736 | 0.5314 | -0.0579 |
| originale | Q4 | 350 | 0.5731 | 0.5371 | +0.0360 |
| originale | **Q5** | 351 | 0.7166 | 0.6097 | +0.1069 |
| calibrato | **Q1** | 351 | 0.4675 | 0.4929 | -0.0254 |
| calibrato | Q2 | 350 | 0.5150 | 0.4800 | +0.0350 |
| calibrato | Q3 | 350 | 0.5356 | 0.5314 | +0.0042 |
| calibrato | Q4 | 350 | 0.5541 | 0.5371 | +0.0170 |
| calibrato | **Q5** | 351 | 0.5783 | 0.6097 | -0.0314 |

**GG/NG: GG, Poisson testa Totali (attuale) — test (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| originale | **Q1** | 351 | 0.2122 | 0.4758 | -0.2636 |
| originale | Q2 | 350 | 0.3609 | 0.5514 | -0.1905 |
| originale | Q3 | 350 | 0.4414 | 0.5029 | -0.0615 |
| originale | Q4 | 350 | 0.5270 | 0.5943 | -0.0673 |
| originale | **Q5** | 351 | 0.6718 | 0.5698 | +0.1020 |
| calibrato | **Q1** | 351 | 0.4907 | 0.4758 | +0.0149 |
| calibrato | Q2 | 350 | 0.5153 | 0.5514 | -0.0361 |
| calibrato | Q3 | 350 | 0.5337 | 0.5029 | +0.0308 |
| calibrato | Q4 | 350 | 0.5569 | 0.5943 | -0.0374 |
| calibrato | **Q5** | 351 | 0.6115 | 0.5698 | +0.0417 |

**GG/NG: GG, NegBin-pooled testa Totali — test (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| originale | **Q1** | 351 | 0.1955 | 0.4786 | -0.2831 |
| originale | Q2 | 350 | 0.3282 | 0.5514 | -0.2232 |
| originale | Q3 | 350 | 0.3987 | 0.4971 | -0.0984 |
| originale | Q4 | 350 | 0.4733 | 0.6000 | -0.1267 |
| originale | **Q5** | 351 | 0.6023 | 0.5670 | +0.0354 |
| calibrato | **Q1** | 351 | 0.4903 | 0.4929 | -0.0026 |
| calibrato | Q2 | 350 | 0.5151 | 0.5371 | -0.0221 |
| calibrato | Q3 | 350 | 0.5340 | 0.5000 | +0.0340 |
| calibrato | Q4 | 350 | 0.5575 | 0.5971 | -0.0396 |
| calibrato | **Q5** | 351 | 0.6119 | 0.5670 | +0.0449 |

### Escursione predittiva Q5−Q1 (quanta disparita' resta?)

Valori aggregati; una mappa di calibrazione che 'aggiusta il livello' lascia un'escursione ampia, una che ritira verso la frequenza base la comprime verso zero.

| Variante | Split | Q5-Q1 originale | Q5-Q1 calibrato |
|---|---|---:|---:|
| 1X2 blend produzione, esito 1 | validation | 0.494 | 0.526 |
| 1X2 blend produzione, esito 2 | validation | 0.429 | 0.459 |
| 1X2 NegBin+Elo, esito 1 | validation | 0.478 | 0.528 |
| 1X2 NegBin+Elo, esito 2 | validation | 0.414 | 0.460 |
| O/U2.5: Over 2.5, Poisson testa Totali (attuale) | validation | 0.534 | 0.101 |
| O/U2.5: Over 2.5, NegBin-pooled testa Totali | validation | 0.471 | 0.102 |
| GG/NG: GG, Poisson testa Totali (attuale) | validation | 0.447 | 0.120 |
| GG/NG: GG, NegBin-pooled testa Totali | validation | 0.396 | 0.121 |
| 1X2 blend produzione, esito 1 | test | 0.506 | 0.538 |
| 1X2 blend produzione, esito 2 | test | 0.439 | 0.469 |
| 1X2 NegBin+Elo, esito 1 | test | 0.489 | 0.540 |
| 1X2 NegBin+Elo, esito 2 | test | 0.424 | 0.471 |
| O/U2.5: Over 2.5, Poisson testa Totali (attuale) | test | 0.539 | 0.111 |
| O/U2.5: Over 2.5, NegBin-pooled testa Totali | test | 0.477 | 0.111 |
| GG/NG: GG, Poisson testa Totali (attuale) | test | 0.460 | 0.121 |
| GG/NG: GG, NegBin-pooled testa Totali | test | 0.407 | 0.122 |

## 6. Verdetto e regola d'arresto

### 6.1 La probabilita' 1X2 di PRODUZIONE e' gia' calibrata: nessun disallineamento di confidenza da correggere

Sul BLEND di produzione 0.25 Poisson + 0.75 Elo (cio' che l'app mostra oggi) la temperatura stimata solo su train vale T=0.927 con IC 95% [0.8563; 1.0069]: **l'IC include T=1**, quindi per la base che conta davvero il verdetto richiesto dal protocollo e' esplicito: non c'e' disallineamento di confidenza da correggere. Applicando comunque T, il Brier non migliora (validation +0.0010 [-0.0001; 0.0021], test +0.0012 [0.0001; 0.0021]) e la LogLoss peggiora leggermente: il test di overfitting §4 lo boccia, come deve.

Sulla variante NegBin+Elo (il piu' vicino a un 'produrre la NB2 dell'audit precedente dentro il blend') T=0.887 [0.8202; 0.9630] e' significativamente sotto 1 sul train, ma il guadagno NON si riproduce fuori campione (ΔBrier +0.0012/+0.0016, IC che includono lo zero o leggermente positivi): esattamente il pattern 'bello sul fit, assente sul test' che il controllo esplicito doveva intercettare.

### 6.2 Le marginali PURE sono molto sovra-sicure, ma ritararle non raggiunge il blend

Sulle marginali Poisson pure (quelle cioe' prive di Elo) la temperatura e' grande e lontanissima da 1: T=2.49 [2.2473; 2.7592] per il Poisson, T=2.05 [1.8659; 2.2717] per la NegBin-pooled, con miglioramenti fuori-campione enormi e stabili (ΔBrier Poisson -0.0375/-0.0368). Tuttavia, anche dopo la calibrazione, quelle marginali restano PEGGIORI del blend di produzione non calibrato: Brier validation 0.6148 (Poisson+T) e 0.6140 (NB+T) contro 0.5918 del blend; test 0.6103/0.6106 contro 0.5917. L'ensemble con Elo assorbe gia' da solo, e meglio, la sovra-sicurezza della marginale Poisson: e' la stessa lezione degli audit ensemble, ora riletta dal lato della calibrazione.

### 6.3 Beta calibration sui binari: vince formalmente su entrambi gli split, ma ritirando quasi tutta la discriminazione

- O/U2.5 base pois: ΔBrier -0.0262 [-0.0334; -0.0191] validation, -0.0228 [-0.0301; -0.0155] test -> SI', IC fuori zero su entrambi; ma Brier calibrato 0.2482/0.2473 contro il predittore costante 0.2488/0.2491 (skill residua +0.3%/+0.7%).
- O/U2.5 base nb: ΔBrier -0.0212 [-0.0278; -0.0149] validation, -0.0188 [-0.0255; -0.0121] test -> SI', IC fuori zero su entrambi; ma Brier calibrato 0.2482/0.2473 contro il predittore costante 0.2488/0.2491 (skill residua +0.3%/+0.7%).
- GG/NG base pois: ΔBrier -0.0304 [-0.0374; -0.0237] validation, -0.0253 [-0.0326; -0.0176] test -> SI', IC fuori zero su entrambi; ma Brier calibrato 0.2484/0.2478 contro il predittore costante 0.2472/0.2485 (skill residua -0.5%/+0.3%).
- GG/NG base nb: ΔBrier -0.0358 [-0.0440; -0.0278] validation, -0.0309 [-0.0391; -0.0231] test -> SI', IC fuori zero su entrambi; ma Brier calibrato 0.2486/0.2478 contro il predittore costante 0.2472/0.2485 (skill residua -0.6%/+0.3%).

Il criterio formale richiesto (IC fuori zero su validation E test in modo coerente) e' soddisfatto per le 4 varianti binarie e per le marginali 1X2 pure; non lo e' per le due probabilita' 1X2 produttive (blend e NB+Elo). Ma la tabella 3b e l'escursione Q5-Q1 del §5 impongono la lettura onesta: la mappa beta comprime le probabilita' quasi sulla frequenza base, quindi il 'miglioramento' del Brier e' in larghissima parte cancellazione di una falsa precisione, non apprendimento di segnale per partita. Dopo la calibrazione il modello binario, ricostruito qui con i lambda dello snapshot xG statico, non sa distinguere Over da Under (o GG da NG) meglio della frequenza di campionato. Non e' un lasciapassare a mettere la mappa in produzione sul motore live point-in-time: prima andrebbe ripetuta la stessa stima sui numeri veri dell'engine e li' verificata la risoluzione residua.

### 6.4 NegBin e calibrazione: correzioni SOSTITUTIVE, non additive

Gli endpoint dopo calibrazione coincidono a prescindere dalla base di partenza: Over validation Poisson+beta 0.2482 ≈ NegBin+beta 0.2482; GG 0.2484 ≈ 0.2486; sull'1X2 0.6148 ≈ 0.6140. In tutti i casi la mappa di calibrazione e' ancora 'attiva' sulla base NegBin (i parametri non tornano all'identita'), ma porta allo stesso punto finale della calibrazione sul Poisson: NegBin e temperatura/beta correggono prevalentemente lo STESSO difetto (code troppo spinte, livello sbagliato). Sovrapporle entrambe non somma guadagno. Rispetto all'audit overdispersion c'e' coerenza ma anche complementarieta' di conclusione: la NB2 corregge la dispersione delle soglie ma peggiora GG; la beta calibration corregge il livello di tutti i binari ma annullandone la risoluzione; nessuna delle due e' un ritocco gratuito.

### Conclusione e regola d'arresto

**Sulla probabilita' 1X2 effettivamente mostrata dall'app (blend Poisson+Elo), nessuno strato di calibrazione post-hoc batte l'originale con IC fuori zero su validation E test: la regola d'arresto scatta e si scrive esplicitamente — non si autorizza nessuna modifica di produzione, e il T=1 resta confermato.** Sui binari puri la beta calibration supera formalmente il test previsto dal protocollo, ma solo riportando la testa alla frequenza costante: e' la prova che quelle probabilita', nella ricostruzione a snapshot di questi audit, non contengono risoluzione per partita dopo l'aggiustamento di livello, non una richiesta di deployment. Il tentativo Isotonic/Platt fittato sulla validation non e' ripetuto: ogni parametro qui veniva dal solo train, e il §4 mostra per ogni variante train/validation/test separatamente, senza inversioni nascoste.

Varianti formalmente bocciate dal test di overfitting (§4):

- 1X2 / base 'blend': NO: peggiora in modo significativo.
- 1X2 / base 'nb_blend': NO: inversione/instabilita'.

## Limiti dichiarati

1. **Solo mappe globale monotone**: un solo T (o un solo terno beta) per tutte le partite; errori di calibrazione che dipendono dalla lega, dal livello di quota o dal tipo di partita non sono raggiungibili, e i quintili §5 servono anche a mostrarlo.
2. **Train come calibration set**: i parametri usano predizioni walk-forward su 2022/23+2023/24 (circa 3.3k partite 1X2, meno 60 di warmup per lega); e' il piu' grande campione non contaminato di cui disponiamo, ma proviene da uno snapshot xG statico (stesso limite dei tre audit precedenti): il livello assoluto delle probabilita' non e' quello live point-in-time.
3. **Beta MLE non regolarizzata se quanto basta** (solo una ridge 1e-8): in caso di separazione completa le stime divergerebbero; le probabilita' sono troncate dalla griglia a 15 gol e non toccano 0/1, e gli IC bootstrap coprono il caso; cio' nonostante parametri molto maggiori di 1 in valore assoluto vanno letti come instabilita', non come effetti fisici.
4. **La NegBin usata come base e' quella pooled** dell'audit precedente (alpha stimato sullo stesso treno): le conclusioni sulla sovrapposizione dei due correttivi valgono per quella parametrizzazione, non per eventuali NB per-lega.
5. **Nessuna quota in questo script**: si misura solo calibrazione (Brier/LogLoss/quintili), non convenienza economica.
6. **Mappe pooled, non per lega**: un solo T e un solo terno beta per tutte le leghe; il termine noto c fissa il livello alla frequenza media del train, non a quella futura (che non e' nota al momento della predizione). Una calibrazione per lega catturerebbe livelli diversi (es. Bundesliga piu' over) ma non era oggetto qui.
7. **Il collasso sulla costante e' un limite d'uso, non solo un numero**: quando la mappa comprime quasi tutta l'escursione (§5), il Brier formale migliora ma la probabilita' per partita perde valore; prima di qualunque adozione andrebbe ripetuta la stima sui numeri dell'engine point-in-time (non sui lambda a snapshot xG statico di questi audit), che hanno un livello e una dispersione diversi.
8. **Beta calibration in 0 e 1**: le probabilita' di griglia non toccano gli estremi ma si avvicinano; il clip a 1e-6 e la ridge 1e-8 stabilizzano la MLE, e gli IC bootstrap segnalano eventuali instabilita' dei parametri.

## Riferimenti incrociati

- `audit/results/elo_ensemble_diagnosis.md` e `audit/results/form_totali_diagnosis.md`: marginali di riferimento;
- `audit/results/combo_1x2_totali_diagnosis.md`: walk-forward condiviso, blend w e cross-check bit-a-bit;
- `audit/results/overdispersion_condizionale_diagnosis.md`: baseline NegBin-pooled riutilizzata qui per il test di ridondanza;
- Kull, Silva Filho, Flach (2015), *Beta calibration: a well-founded and empirically successful correction...*; Guo et al. (2017) per la temperature scaling.

