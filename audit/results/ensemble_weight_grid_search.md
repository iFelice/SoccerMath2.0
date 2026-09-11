# Grid search peso ensemble Poisson+Elo su 1X2 (audit sola lettura)

*Generato: 2026-09-11T22:32:36+00:00 — script `audit/grid_search_ensemble_weight.py`, nessuna modifica a SoccerMath/.*

Griglia w in {0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0} (peso Poisson; 1-w su Elo). **w=0.6 e' il valore attuale di produzione** (`app.ELO_ENSEMBLE_W`). Selezione solo su TRAIN 2022/23+2023/24, conferma su VALIDATION 2024/25, TEST 2025/26 sola lettura. Pipeline: walker condiviso di `diagnose_clv_pinnacle` (NORM-SUM bit-faithful a `run_models` + Elo K=24 di `diagnose_elo_ensemble`), esteso a emettere anche le stagioni di train — lo stato non cambia (test di consistenza).

Bootstrap: 2000 resample di righe, seed 20260905, CI percentile 2.5-97.5 (costanti `_ci` di `topmix_margins.py`). ROI: puntata fissa 10, selezione edge>0 vs fair de-vigata del book, settle sullo stesso book (`roi_1x2`/`EDGE_MIN=0` di `diagnose_production_baseline`).

## Copertura campioni

| Lega | Train (n) | Train escluse cold-start | Validation (n) | Test (n) | B365 mancante (V+T) | Avg mancante (V+T) |
|---|---:|---:|---:|---:|---:|---:|
| Serie A | 700 | 60 | 380 | 380 | 0 | 0 |
| Premier League | 700 | 60 | 380 | 380 | 0 | 0 |
| La Liga | 700 | 60 | 380 | 380 | 0 | 0 |
| Bundesliga | 552 | 60 | 306 | 306 | 0 | 0 |
| Ligue 1 | 626 | 60 | 306 | 306 | 0 | 0 |
| **AGGREGATO** | 3278 | 300 | 1752 | 1752 | 0 | 0 |

Le prime 60 partite per lega (2022/23) restano nello stato ma sono escluse dal campione di valutazione TRAIN per il cold start (DB vuoto: medie gol/forma/Elo non informativi); validation e test restano censuari come negli altri audit. La sensibilita' della scelta alla finestra di warmup e' nella tabella di selezione.

## Grid su TRAIN (aggregato 5 leghe, n=3278)

| w | Brier | CI 95% | Δ Brier vs 0.6 | CI 95% Δ | Δ>0 segn. | LogLoss | CI 95% | Δ LogLoss vs 0.6 | CI 95% Δ | ROI B365 | ROI Avg |
|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 0.0 meglio | 0.6009 | [0.5920; 0.6095] | -0.0079 | [-0.0156; -0.0000] | si | 1.0073 | [0.9947; 1.0195] | -0.0096 | [-0.0208; 0.0019] | -15.82 [-21.63; -9.74] | -15.03 [-20.89; -8.94] |
| 0.1 meglio | 0.5968 | [0.5876; 0.6059] | -0.0120 | [-0.0184; -0.0054] | si | 1.0014 | [0.9884; 1.0142] | -0.0155 | [-0.0249; -0.0059] | -15.20 [-20.90; -9.20] | -14.23 [-20.13; -8.07] |
| 0.2 meglio | 0.5949 | [0.5852; 0.6047] | -0.0139 | [-0.0190; -0.0086] | si | 0.9984 | [0.9849; 1.0124] | -0.0185 | [-0.0261; -0.0107] | -14.65 [-20.28; -8.78] | -13.59 [-19.33; -7.44] |
| 0.3 meglio | 0.5951 | [0.5848; 0.6057] | -0.0136 | [-0.0175; -0.0097] | si | 0.9983 | [0.9840; 1.0130] | -0.0186 | [-0.0244; -0.0126] | -10.91 [-16.44; -5.10] | -10.54 [-16.38; -4.51] |
| 0.4 meglio | 0.5975 | [0.5866; 0.6087] | -0.0112 | [-0.0138; -0.0086] | si | 1.0012 | [0.9857; 1.0167] | -0.0158 | [-0.0198; -0.0117] | -10.47 [-15.97; -4.87] | -8.41 [-14.04; -2.53] |
| 0.5 meglio | 0.6021 | [0.5903; 0.6140] | -0.0067 | [-0.0080; -0.0054] | si | 1.0072 | [0.9903; 1.0242] | -0.0097 | [-0.0118; -0.0076] | -8.96 [-14.22; -3.56] | -6.89 [-12.33; -1.24] |
| 0.6 (attuale) | 0.6088 | [0.5959; 0.6218] | +0.0000 | [0.0000; 0.0000] | no | 1.0169 | [0.9981; 1.0356] | +0.0000 | [0.0000; 0.0000] | -7.30 [-12.51; -1.96] | -6.75 [-12.09; -1.29] |
| 0.7 peggio | 0.6176 | [0.6036; 0.6318] | +0.0089 | [0.0075; 0.0102] | si | 1.0311 | [1.0105; 1.0522] | +0.0142 | [0.0119; 0.0165] | -6.23 [-11.14; -1.17] | -3.59 [-8.84; 1.67] |
| 0.8 peggio | 0.6286 | [0.6136; 0.6440] | +0.0199 | [0.0172; 0.0225] | si | 1.0512 | [1.0285; 1.0747] | +0.0343 | [0.0293; 0.0395] | -4.06 [-8.87; 1.15] | -5.48 [-10.16; -0.54] |
| 0.9 peggio | 0.6418 | [0.6257; 0.6582] | +0.0330 | [0.0290; 0.0371] | si | 1.0806 | [1.0549; 1.1069] | +0.0637 | [0.0552; 0.0725] | -4.69 [-9.37; 0.27] | -5.07 [-9.61; -0.24] |
| 1.0 peggio | 0.6571 | [0.6397; 0.6749] | +0.0483 | [0.0428; 0.0539] | si | 1.1352 | [1.1031; 1.1669] | +0.1183 | [0.1027; 0.1346] | -4.95 [-9.51; -0.09] | -4.81 [-9.38; -0.00] |

## Selezione su TRAIN

* **w\* (min Brier su train aggregato): 0.2** — NON coincide con il 0.6 di produzione.
* **w\* (min LogLoss su train aggregato): 0.3**.
* Delta Brier(w* vs 0.6) = -0.0139, CI 95% [-0.0190; -0.0086] → **distinguibile**.
* Delta LogLoss(w* vs 0.6) = -0.0185, CI 95% [-0.0261; -0.0107] → distinguibile.

Argmin per lega (diagnostica, la selezione di produzione e' globale):

| Lega | w* Brier | Brier a w* | Brier a 0.6 | w* LogLoss |
|---|---:|---:|---:|---:|
| Serie A | 0.3 | 0.6038 | 0.6182 | 0.3 |
| Premier League | 0.3 | 0.5729 | 0.5831 | 0.3 |
| La Liga | 0.2 | 0.5950 | 0.6077 | 0.2 |
| Bundesliga | 0.2 | 0.5927 | 0.6167 | 0.2 |
| Ligue 1 | 0.2 | 0.6106 | 0.6210 | 0.3 |

Sensibilità alla finestra di warmup (train aggregato, escluse le prime 120 partite/lega): w* = 0.2 — invariato rispetto al warmup 60.

## Conferma su VALIDATION 2024/25 (con il w* trovato su train)

| w | Brier | LogLoss | Δ Brier vs 0.6 | CI 95% Δ | ROI B365 | ROI Avg |
|---:|---:|---:|---:|---:|---:|---:|
| 0.2 (w* train) | 0.5913 | 0.9928 | -0.0163 | [-0.0230; -0.0096] | -15.22 | -16.14 |
| 0.3 (w* logloss train) | 0.5927 | 0.9943 | -0.0149 | [-0.0199; -0.0099] | -12.52 | -12.83 |
| 0.6 (attuale) | 0.6076 | 1.0153 | +0.0000 | [0.0000; 0.0000] | -2.49 | -2.05 |

La conferma e' **positiva e distinguishibile**: su validation il w* di train 0.2 e' meglio del 0.6 con CI del Delta che non contiene 0.

## Lettura finale su TEST 2025/26 (mai usato per scegliere)

| w | Brier | LogLoss | Δ Brier vs 0.6 | CI 95% Δ | ROI B365 | ROI Avg |
|---:|---:|---:|---:|---:|---:|---:|
| 0.2 (w* train) | 0.5915 | 0.9931 | -0.0135 | [-0.0202; -0.0069] | -3.67 | -6.69 |
| 0.6 (attuale) | 0.6051 | 1.0117 | +0.0000 | [0.0000; 0.0000] | -0.79 | -1.65 |

## Lettura

1. **Il minimo di Brier/LogLoss su train NON cade su 0.6**: w* = 0.2 (Brier) e 0.3 (LogLoss), con Delta rispetto al 0.6 FUORI dall'IC bootstrap (-0.0139, CI [-0.0190; -0.0086]). L'argmin e' coerente tra le 5 leghe (0.2-0.3) e stabile alla finestra di warmup (0.2 escludendo 120 partite/lega).
2. **Conferma su validation**: w* 0.2 resta meglio del 0.6 e la differenza e' distinguishibile (CI senza zero). Anche restringendo al range storico di `diagnose_elo_ensemble` [0.5; 0.9], su validation l'argmin cade a 0.5: il bordo basso del range, non l'ottimo interno 0.6 del run storico (eseguito su uno stato dei dati/xG diverso; il range 0.5-0.9 non includeva mai la zona 0.0-0.4 dove sta il minimo attuale).
3. **Test (sola lettura)**: w* 0.2 resta meglio del 0.6, Delta distinguibile (-0.0135, CI [-0.0202; -0.0069]).
4. **Calibrazione ≠ redditività**: il w* migliore su Brier/LogLoss ha ROI B365 train -14.65% vs -7.30%, validation -15.22% vs -2.49%, test -3.67% vs -0.79% (w* vs 0.6): il blend più Elo scommessa più e peggio, quello attuale meno e meglio. Abbassare ELO_ENSEMBLE_W migliora le metriche di calibrazione e peggiora il ROI storico: qualsiasi cambio di produzione deve pesare entrambi gli aspetti (qui si misura, non si decide).

## Limiti dichiarati

1. **Cold start del train**: le predizioni 2022/23 nascono da DB vuoto (gli altri audit prevedevano solo validation/test con due stagioni piene di training). Il warmup esclude dal campione le prime 60 partite/lega ma lo stato conserva il rumore residuo; la sensibilita' e' riportata.
2. **xG snapshot statico** e **Elo di replica** (K fisso, niente moltiplicatore di scarto/boost xG): stessi limiti documentati in `clv_pinnacle_report.md` §Limiti, ereditati dalla pipeline condivisa.
3. **ROI con edge>0 su un solo book per scommessa**: convenzione dei backtest del repo, non una strategia consigliata; il volume di scommesse a w estremi (0.0/1.0) puo' variare molto e i ROI estremi hanno CI ampie.
4. La griglia e' discreta a step 0.1 su un solo dataset: anche un w* distinguibile su train va letto come indicazione di direzione, non come valore ottimo da impiantare (stessa lezione dell'audit rho Dixon-Coles).

