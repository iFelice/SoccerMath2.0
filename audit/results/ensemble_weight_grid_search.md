# Grid search peso ensemble Poisson+Elo su 1X2 (audit sola lettura)

*Generato: 2026-10-06T21:27:39+00:00 — script `audit/grid_search_ensemble_weight.py`, nessuna modifica a SoccerMath/.*

Griglia w in {0.0, 0.1, 0.2, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0} (peso Poisson; 1-w su Elo). **w=0.6 e' il valore attuale di produzione** (`app.POISSON_1X2_WEIGHT`). Selezione solo su TRAIN 2022/23+2023/24, conferma su VALIDATION 2024/25, TEST 2025/26 sola lettura. Pipeline: walker condiviso di `diagnose_clv_pinnacle` (NORM-SUM bit-faithful a `run_models` + Elo K=24 di `diagnose_elo_ensemble`), esteso a emettere anche le stagioni di train — lo stato non cambia (test di consistenza).

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
| 0.0 peggio | 0.6009 | [0.5920; 0.6095] | +0.0081 | [0.0051; 0.0109] | si | 1.0073 | [0.9947; 1.0195] | +0.0120 | [0.0079; 0.0160] | -17.93 [-24.06; -11.63] | -16.62 [-22.70; -10.09] |
| 0.1 peggio | 0.5964 | [0.5873; 0.6055] | +0.0035 | [0.0018; 0.0052] | si | 1.0008 | [0.9878; 1.0135] | +0.0055 | [0.0030; 0.0078] | -16.10 [-22.05; -9.77] | -14.90 [-20.85; -8.37] |
| 0.2 peggio | 0.5936 | [0.5839; 0.6032] | +0.0007 | [0.0002; 0.0013] | si | 0.9966 | [0.9830; 1.0099] | +0.0013 | [0.0004; 0.0020] | -14.83 [-20.92; -8.40] | -13.72 [-19.76; -7.36] |
| 0.2 (attuale) | 0.5928 | [0.5829; 0.6025] | +0.0000 | [0.0000; 0.0000] | no | 0.9953 | [0.9814; 1.0091] | +0.0000 | [0.0000; 0.0000] | -14.11 [-20.12; -7.71] | -13.19 [-19.25; -6.82] |
| 0.3 ≈0.6 (rumore) | 0.5925 | [0.5824; 0.6025] | -0.0003 | [-0.0009; 0.0003] | no | 0.9946 | [0.9803; 1.0087] | -0.0007 | [-0.0015; 0.0002] | -12.67 [-18.69; -6.32] | -11.30 [-17.35; -4.95] |
| 0.4 ≈0.6 (rumore) | 0.5932 | [0.5824; 0.6040] | +0.0003 | [-0.0013; 0.0022] | no | 0.9950 | [0.9800; 1.0100] | -0.0003 | [-0.0027; 0.0023] | -9.66 [-15.43; -3.52] | -9.12 [-15.05; -2.97] |
| 0.5 ≈0.6 (rumore) | 0.5955 | [0.5838; 0.6073] | +0.0027 | [-0.0000; 0.0057] | no | 0.9979 | [0.9813; 1.0144] | +0.0026 | [-0.0015; 0.0069] | -8.50 [-14.09; -2.35] | -7.70 [-13.43; -1.78] |
| 0.6 peggio | 0.5997 | [0.5870; 0.6123] | +0.0068 | [0.0029; 0.0110] | si | 1.0036 | [0.9853; 1.0218] | +0.0082 | [0.0025; 0.0144] | -8.17 [-13.65; -2.44] | -7.24 [-12.60; -1.51] |
| 0.7 peggio | 0.6055 | [0.5921; 0.6192] | +0.0127 | [0.0076; 0.0180] | si | 1.0125 | [0.9929; 1.0320] | +0.0172 | [0.0094; 0.0255] | -7.37 [-12.42; -2.25] | -7.98 [-12.91; -2.81] |
| 0.8 peggio | 0.6131 | [0.5989; 0.6278] | +0.0202 | [0.0141; 0.0268] | si | 1.0256 | [1.0047; 1.0475] | +0.0303 | [0.0205; 0.0408] | -6.47 [-11.39; -1.26] | -4.44 [-9.38; 0.69] |
| 0.9 peggio | 0.6223 | [0.6074; 0.6382] | +0.0295 | [0.0222; 0.0372] | si | 1.0448 | [1.0218; 1.0689] | +0.0495 | [0.0369; 0.0625] | -4.54 [-9.40; 0.49] | -3.42 [-8.31; 1.80] |
| 1.0 peggio | 0.6333 | [0.6174; 0.6502] | +0.0405 | [0.0318; 0.0494] | si | 1.0783 | [1.0505; 1.1057] | +0.0830 | [0.0656; 0.1015] | -2.84 [-7.74; 2.11] | -1.60 [-6.58; 3.56] |

## Selezione su TRAIN

* **w\* (min Brier su train aggregato): 0.3** — NON coincide con il 0.6 di produzione.
* **w\* (min LogLoss su train aggregato): 0.3**.
* Delta Brier(w* vs 0.6) = -0.0003, CI 95% [-0.0009; 0.0003] → **dentro l'IC: rumore, non un miglioramento vero**.
* Delta LogLoss(w* vs 0.6) = -0.0007, CI 95% [-0.0015; 0.0002] → dentro l'IC.

Argmin per lega (diagnostica, la selezione di produzione e' globale):

| Lega | w* Brier | Brier a w* | Brier a 0.6 | w* LogLoss |
|---|---:|---:|---:|---:|
| Serie A | 0.3 | 0.6009 | 0.6015 | 0.4 |
| Premier League | 0.2 | 0.5752 | 0.5752 | 0.2 |
| La Liga | 0.3 | 0.5904 | 0.5909 | 0.4 |
| Bundesliga | 0.3 | 0.5892 | 0.5894 | 0.3 |
| Ligue 1 | 0.3 | 0.6075 | 0.6079 | 0.4 |

Sensibilità alla finestra di warmup (train aggregato, escluse le prime 120 partite/lega): w* = 0.3 — invariato rispetto al warmup 60.

## Conferma su VALIDATION 2024/25 (con il w* trovato su train)

| w | Brier | LogLoss | Δ Brier vs 0.6 | CI 95% Δ | ROI B365 | ROI Avg |
|---:|---:|---:|---:|---:|---:|---:|
| 0.2 (attuale) | 0.5890 | 0.9893 | +0.0000 | [0.0000; 0.0000] | -11.64 | -13.72 |
| 0.3 (w* train) | 0.5891 | 0.9891 | +0.0001 | [-0.0006; 0.0008] | -13.52 | -12.69 |

La conferma su validation **non distingue** w* dal 0.6 (CI del Delta che contiene 0): la scelta produttiva resta il 0.6 e la variazione osservata su train e' compatibile con il rumore.

## Lettura finale su TEST 2025/26 (mai usato per scegliere)

| w | Brier | LogLoss | Δ Brier vs 0.6 | CI 95% Δ | ROI B365 | ROI Avg |
|---:|---:|---:|---:|---:|---:|---:|
| 0.2 (attuale) | 0.5904 | 0.9913 | +0.0000 | [0.0000; 0.0000] | -4.98 | -6.06 |
| 0.3 (w* train) | 0.5903 | 0.9910 | -0.0000 | [-0.0007; 0.0007] | -3.51 | -3.74 |

## Lettura

1. **Il minimo di Brier/LogLoss su train NON cade su 0.6**: w* = 0.3 (Brier) e 0.3 (LogLoss), con Delta rispetto al 0.6 dentro dall'IC bootstrap (-0.0003, CI [-0.0009; 0.0003]). L'argmin e' coerente tra le 5 leghe (0.2-0.3) e stabile alla finestra di warmup (0.3 escludendo 120 partite/lega).
2. **Conferma su validation**: w* 0.3 resta peggio del 0.6 e la differenza e' dentro l'IC (rumore). Anche restringendo al range storico di `diagnose_elo_ensemble` [0.5; 0.9], su validation l'argmin cade a 0.5: il bordo basso del range, non l'ottimo interno 0.6 del run storico (eseguito su uno stato dei dati/xG diverso; il range 0.5-0.9 non includeva mai la zona 0.0-0.4 dove sta il minimo attuale).
3. **Test (sola lettura)**: w* 0.3 resta meglio del 0.6, Delta dentro l'IC (-0.0000, CI [-0.0007; 0.0007]).
4. **Calibrazione ≠ redditività**: il w* migliore su Brier/LogLoss ha ROI B365 train -12.67% vs -14.11%, validation -13.52% vs -11.64%, test -3.51% vs -4.98% (w* vs 0.6): il blend più Elo scommessa più e peggio, quello attuale meno e meglio. Abbassare POISSON_1X2_WEIGHT migliora le metriche di calibrazione e peggiora il ROI storico: qualsiasi cambio di produzione deve pesare entrambi gli aspetti (qui si misura, non si decide).

## Limiti dichiarati

1. **Cold start del train**: le predizioni 2022/23 nascono da DB vuoto (gli altri audit prevedevano solo validation/test con due stagioni piene di training). Il warmup esclude dal campione le prime 60 partite/lega ma lo stato conserva il rumore residuo; la sensibilita' e' riportata.
2. **xG snapshot statico** e **Elo di replica** (K fisso, niente moltiplicatore di scarto/boost xG): stessi limiti documentati in `clv_pinnacle_report.md` §Limiti, ereditati dalla pipeline condivisa.
3. **ROI con edge>0 su un solo book per scommessa**: convenzione dei backtest del repo, non una strategia consigliata; il volume di scommesse a w estremi (0.0/1.0) puo' variare molto e i ROI estremi hanno CI ampie.
4. La griglia e' discreta a step 0.1 su un solo dataset: anche un w* distinguibile su train va letto come indicazione di direzione, non come valore ottimo da impiantare (stessa lezione dell'audit rho Dixon-Coles).
