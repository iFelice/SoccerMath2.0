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


<!-- conferma-w025:start -->
## Conferma cambio produzione: ELO_ENSEMBLE_W 0.6 -> 0.25 (2026-09-12T09:21:46+00:00)

Audit di conferma SOLA LETTURA riusando la pipeline di questo report (walker condiviso, stesse righe, stesse quote, stesso bootstrap): griglia ridotta ai due pesi (0.25 candidato vs 0.6 attuale), delta appaiati 2000 resample, seed 20260905, CI percentile 2.5-97.5 (`_ci` di `topmix_margins`), convenzioni identiche alle sezioni sopra. Stesso dettaglio per lega di `production_baseline_comparison.md`; l'aggregato è in coda.

### VALIDATION 2024/25

| Campione | n | Brier 0.6 | Brier 0.25 | Δ Brier (CI) | sig | LogLoss 0.6 | LogLoss 0.25 | Δ LogLoss (CI) | sig |
|---|---:|---:|---:|---:|:---:|---:|---:|---:|:---:|
| Serie A | 380 | 0.6151 | 0.5935 | -0.0216 [-0.0353;-0.0079] | **sì** | 1.0186 | 0.9941 | -0.0245 [-0.0451;-0.0036] | **sì** |
| Premier League | 380 | 0.6043 | 0.5908 | -0.0134 [-0.0258;-0.0013] | **sì** | 1.0108 | 0.9921 | -0.0188 [-0.0368;-0.0010] | **sì** |
| La Liga | 380 | 0.5918 | 0.5805 | -0.0113 [-0.0219;-0.0011] | **sì** | 0.9923 | 0.9768 | -0.0155 [-0.0325;+0.0009] | no |
| Bundesliga | 306 | 0.6213 | 0.6114 | -0.0099 [-0.0263;+0.0062] | no | 1.0448 | 1.0238 | -0.0210 [-0.0481;+0.0047] | no |
| Ligue 1 | 306 | 0.6084 | 0.5852 | -0.0232 [-0.0362;-0.0097] | **sì** | 1.0156 | 0.9836 | -0.0320 [-0.0511;-0.0116] | **sì** |
| AGGREGATO | 1752 | 0.6076 | 0.5918 | -0.0158 [-0.0217;-0.0099] | **sì** | 1.0153 | 0.9933 | -0.0220 [-0.0306;-0.0129] | **sì** |

ROI a puntata fissa (edge>0, stesso book per scommessa; CI own bootstrap, niente delta appaiato: le selezioni dei due pesi differiscono, denominatori non confrontabili 1:1):

| Campione | n bet B365 0.6 | ROI B365 0.6 (CI) | n bet B365 0.25 | ROI B365 0.25 (CI) | n bet Avg 0.6 | ROI Avg 0.6 | n bet Avg 0.25 | ROI Avg 0.25 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Serie A | 380 | -5.59 [-19.50;+7.47] | 380 | -26.56 [-39.99;-13.10] | 380 | -4.58 | 380 | -30.88 |
| Premier League | 380 | -5.03 [-20.04;+11.49] | 380 | -11.53 [-27.51;+5.55] | 380 | -6.52 | 380 | -16.21 |
| La Liga | 380 | -8.17 [-22.01;+6.38] | 380 | -10.98 [-28.02;+7.90] | 380 | -5.29 | 380 | -9.71 |
| Bundesliga | 306 | 12.18 [-4.32;+28.15] | 306 | -13.12 [-28.34;+2.47] | 306 | 13.25 | 306 | -10.33 |
| Ligue 1 | 306 | -3.11 [-20.79;+15.24] | 306 | -9.11 [-27.85;+9.20] | 306 | -4.64 | 306 | -9.37 |
| AGGREGATO | 1752 | -2.49 [-9.11;+4.56] | 1752 | -14.53 [-22.18;-7.03] | 1752 | -2.05 | 1752 | -15.76 |

### TEST 2025/26

| Campione | n | Brier 0.6 | Brier 0.25 | Δ Brier (CI) | sig | LogLoss 0.6 | LogLoss 0.25 | Δ LogLoss (CI) | sig |
|---|---:|---:|---:|---:|:---:|---:|---:|---:|:---:|
| Serie A | 380 | 0.5959 | 0.5901 | -0.0058 [-0.0187;+0.0074] | no | 0.9985 | 0.9905 | -0.0080 [-0.0292;+0.0127] | no |
| Premier League | 380 | 0.6222 | 0.6123 | -0.0099 [-0.0223;+0.0020] | no | 1.0316 | 1.0206 | -0.0110 [-0.0289;+0.0062] | no |
| La Liga | 380 | 0.5981 | 0.5836 | -0.0146 [-0.0251;-0.0042] | **sì** | 1.0041 | 0.9817 | -0.0224 [-0.0395;-0.0056] | **sì** |
| Bundesliga | 306 | 0.6020 | 0.5780 | -0.0240 [-0.0394;-0.0081] | **sì** | 1.0119 | 0.9766 | -0.0353 [-0.0590;-0.0110] | **sì** |
| Ligue 1 | 306 | 0.6070 | 0.5918 | -0.0151 [-0.0295;-0.0009] | **sì** | 1.0124 | 0.9926 | -0.0198 [-0.0407;+0.0007] | no |
| AGGREGATO | 1752 | 0.6051 | 0.5917 | -0.0134 [-0.0192;-0.0076] | **sì** | 1.0117 | 0.9930 | -0.0186 [-0.0276;-0.0099] | **sì** |

ROI a puntata fissa (edge>0, stesso book per scommessa; CI own bootstrap, niente delta appaiato: le selezioni dei due pesi differiscono, denominatori non confrontabili 1:1):

| Campione | n bet B365 0.6 | ROI B365 0.6 (CI) | n bet B365 0.25 | ROI B365 0.25 (CI) | n bet Avg 0.6 | ROI Avg 0.6 | n bet Avg 0.25 | ROI Avg 0.25 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Serie A | 380 | 9.58 [-5.57;+25.36] | 380 | 2.98 [-13.29;+20.74] | 380 | 9.23 | 380 | 2.41 |
| Premier League | 380 | 1.01 [-12.68;+15.31] | 380 | 3.44 [-11.24;+19.99] | 380 | -0.31 | 380 | 0.11 |
| La Liga | 380 | -6.32 [-19.71;+7.47] | 380 | -7.90 [-21.97;+7.47] | 380 | -7.97 | 380 | -11.63 |
| Bundesliga | 306 | -1.79 [-16.12;+13.55] | 306 | -12.20 [-26.52;+3.36] | 306 | -3.68 | 306 | -5.53 |
| Ligue 1 | 306 | -8.01 [-24.04;+9.34] | 306 | -0.25 [-18.30;+18.91] | 306 | -6.95 | 306 | -1.28 |
| AGGREGATO | 1752 | -0.79 [-7.35;+6.08] | 1752 | -2.50 [-9.50;+4.81] | 1752 | -1.65 | 1752 | -3.16 |

### Verdetto di conferma

**Calibrazione (Brier): il miglioramento a w=0.25 è distinguibile (CI senza zero) in ENTRAMBI validation e test in AGGREGATO: V -0.0158 [-0.0217;-0.0099], T -0.0134 [-0.0192;-0.0076]. LogLoss aggregato: V -0.0220 [-0.0306;-0.0129], T -0.0186 [-0.0276;-0.0099].**

Per lega (Brier, distinguibile in ENTRAMBI gli split): Serie A no, Premier League no, La Liga sì, Bundesliga no, Ligue 1 sì. Direzione: 10/10 delta per-(lega,split) negativi (nessuna eccezione al segno).

Significatività per lega: Brier distinguibile in 4/5 leghe in validation e 3/5 in test; nessuna cella (lega, split) mostra un PEGGIORAMENTO distinguibile.

La conferma richiesta per il cambio di produzione è SODDISFATTA sul piano della calibrazione: significativo su entrambi gli split in aggregato, direzione coerente in ogni lega e split, mai un peggioramento significativo per lega. Le leghe singole non sempre raggiungono la significatività da sole (306-380 partite a cella: potere statistico limitato), ma non c'e' nessuna lega che si comporti diversamente dalle altre.

Promemoria del report grid (vale qui): calibrazione ≠ redditività — il peso più basso scommessa di più e con ROI storico peggiore; questa sezione misura, la decisione resta al porting.

<!-- conferma-w025:end -->
