# CLV vs Pinnacle — mercato 1X2 (audit sola lettura)

*Generato: 2026-09-11T22:22:40.930902+00:00 — script `audit/diagnose_clv_pinnacle.py`, nessuna modifica a SoccerMath/.*

Split walk-forward identico agli altri audit: train 2022/23+2023/24, validation (V) 2024/25, test (T) 2025/26. Il Live 2026/27 resta fuori dall'eval (nessuna quota Pinnacle comunque).

## Copertura quote Pinnacle (partite senza quota: ESCLUSE, non stimate)

Quota valida = presente, numerica e > 1.0 (regola di `devig_1x2`). Il campione usabile richiede PRE **e** chiusura: senza una delle due la partita esce da tutte le metriche Pinnacle/CLV (Bet365/Avg vengono mascherate per-riga se mancanti). Nessuna imputazione.

| Lega | Stagione | Partite | PSH ok | PSH mancante | PSCH ok | PSCH mancante | Usabili (pre+close) | % usabili | Eval |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| Serie A | 2022/23 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | no |
| Serie A | 2023/24 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | no |
| Serie A | 2024/25 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | si |
| Serie A | 2025/26 | 380 | 200 | 180 | 198 | 182 | 198 | 52.1% | si |
| Serie A | 2026/27 | 30 | 0 | 30 | 0 | 30 | 0 | 0.0% | no |
| Premier League | 2022/23 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | no |
| Premier League | 2023/24 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | no |
| Premier League | 2024/25 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | si |
| Premier League | 2025/26 | 380 | 210 | 170 | 210 | 170 | 210 | 55.3% | si |
| Premier League | 2026/27 | 30 | 0 | 30 | 0 | 30 | 0 | 0.0% | no |
| La Liga | 2022/23 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | no |
| La Liga | 2023/24 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | no |
| La Liga | 2024/25 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | si |
| La Liga | 2025/26 | 380 | 189 | 191 | 188 | 192 | 188 | 49.5% | si |
| La Liga | 2026/27 | 41 | 0 | 41 | 0 | 41 | 0 | 0.0% | no |
| Bundesliga | 2022/23 | 306 | 306 | 0 | 306 | 0 | 306 | 100.0% | no |
| Bundesliga | 2023/24 | 306 | 306 | 0 | 306 | 0 | 306 | 100.0% | no |
| Bundesliga | 2024/25 | 306 | 306 | 0 | 306 | 0 | 306 | 100.0% | si |
| Bundesliga | 2025/26 | 306 | 150 | 156 | 149 | 157 | 149 | 48.7% | si |
| Bundesliga | 2026/27 | 18 | 0 | 18 | 0 | 18 | 0 | 0.0% | no |
| Ligue 1 | 2022/23 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | no |
| Ligue 1 | 2023/24 | 306 | 306 | 0 | 306 | 0 | 306 | 100.0% | no |
| Ligue 1 | 2024/25 | 306 | 306 | 0 | 306 | 0 | 306 | 100.0% | si |
| Ligue 1 | 2025/26 | 306 | 153 | 153 | 153 | 153 | 153 | 50.0% | si |
| Ligue 1 | 2026/27 | 27 | 0 | 27 | 0 | 27 | 0 | 0.0% | no |

**Totale eval (V+T): 2650 partite usabili su 3504 (75.6%).** Le mancanze sono concentrate in 2025/26 (stagione in corso allo scraping: Pinnacle presente solo sulle partite gia' disputate con quotazione chiusa) e nel Live 2026/27 (nessuna quota); le stagioni 2022/23-2024/25 sono coperte al 100%. PSH vs PSCH differiscono per 1-2 partite per lega nel 2025/26 (partite appena giocate: apertura senza chiusura): escluse come da protocollo.

## Metodo

- **Modello**: testa 1X2 PRODUZIONE_DUE_TESTE (NORM-SUM: xG snapshot + forma ultime 5 + fattore mercato, lambda normalizzati alla somma base S, clip [exp(-6), exp(3)]) con ensemble Elo **opzione b gia' in produzione**: 1X2 = 0.6*Poisson + 0.4*Elo (`app.ELO_ENSEMBLE_W`, validato in `diagnose_elo_ensemble.py`, applicato in `app.blend_elo_into_1x2`). Elo walk-forward K=24 replica di `diagnose_elo_ensemble.py`, aggiornato DOPO ogni previsione: nessuna partita usa se stessa o il futuro. Il ramo NORM-SUM del walker e' verificato bit-faithful a `diagnose_production_baseline.run_models` da `test_diagnose_clv_pinnacle.py`.
- **De-vig**: proporzionale standard `1/quota / overround` = `devig_1x2` di `backtest_experiment_all.py` (il brief citava `devig_2way`: e' la variante a 2 esiti dello stesso file; per il 1X2 vale il precedente a 3 esiti).
- **CLV (protocollo)**: sul lato scommesso dal modello (edge>0 vs linea PRE Pinnacle de-vigata, convenzione `EDGE_MIN=0`): `CLV = P_modello(lato) - P_chiusura(lato)`. Accanto, il **CLV classico** `P_pre(lato) - P_chiusura(lato)` (prezzo preso vs chiusura) per il confronto con la letteratura: il primo misura l'edge residuo del modello a chiusura, il secondo la qualita' del prezzo preso.
- **ROI a puntata fissa**: (a) sulle stesse scommesse CLV, settle alla **chiusura Pinnacle** come prezzo di riferimento richiesto (e a pre, informativo); (b) ROI per book con selezione edge>0 vs quel book e settle sulle quote reali di quel book (`roi_1x2` di `diagnose_production_baseline.py`, identica agli altri audit).
- **Bootstrap**: 2000 resample di righe, seed 20260905, CI percentile 2.5-97.5 (costanti `N_BOOT`/`SEED` e formula `_ci` di `topmix_margins.py`; il file `diagnose_rho_bootstrap.py` citato dal protocollo non esiste nel repo, e `diagnose_dixon_coles_rho.py` non contiene bootstrap).

## Calibrazione 1X2: modello vs Pinnacle pre vs chiusura vs Bet365 vs Avg

Campione = partite eval con Pinnacle pre+close valide (Bet365/Avg mascherate per-riga dove mancano). Brier/LogLoss multiclasse (`brier_ll_1x2`).

| Campione | Book | n V | Brier V | LogLoss V | n T | Brier T | LogLoss T | n tot | Brier tot | LogLoss tot |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Serie A** | MODELLO | 380 | 0.6151 | 1.0186 | 198 | 0.6024 | 1.0029 | 578 | 0.6107 | 1.0133 |
| **Serie A** | PIN pre | 380 | 0.5660 | 0.9506 | 198 | 0.5937 | 0.9905 | 578 | 0.5755 | 0.9642 |
| **Serie A** | PIN close | 380 | 0.5669 | 0.9513 | 198 | 0.5948 | 0.9907 | 578 | 0.5764 | 0.9648 |
| **Serie A** | Bet365 | 380 | 0.5684 | 0.9548 | 198 | 0.5942 | 0.9922 | 578 | 0.5773 | 0.9676 |
| **Serie A** | Avg | 380 | 0.5669 | 0.9519 | 198 | 0.5933 | 0.9902 | 578 | 0.5759 | 0.9650 |
| **Premier League** | MODELLO | 380 | 0.6043 | 1.0108 | 210 | 0.6112 | 1.0159 | 590 | 0.6067 | 1.0127 |
| **Premier League** | PIN pre | 380 | 0.5788 | 0.9703 | 210 | 0.5917 | 0.9888 | 590 | 0.5834 | 0.9769 |
| **Premier League** | PIN close | 380 | 0.5751 | 0.9664 | 210 | 0.5911 | 0.9875 | 590 | 0.5808 | 0.9739 |
| **Premier League** | Bet365 | 380 | 0.5787 | 0.9708 | 210 | 0.5925 | 0.9910 | 590 | 0.5836 | 0.9780 |
| **Premier League** | Avg | 380 | 0.5789 | 0.9706 | 210 | 0.5912 | 0.9878 | 590 | 0.5833 | 0.9767 |
| **La Liga** | MODELLO | 380 | 0.5918 | 0.9923 | 188 | 0.5739 | 0.9664 | 568 | 0.5859 | 0.9837 |
| **La Liga** | PIN pre | 380 | 0.5635 | 0.9524 | 188 | 0.5590 | 0.9445 | 568 | 0.5620 | 0.9498 |
| **La Liga** | PIN close | 380 | 0.5593 | 0.9463 | 188 | 0.5614 | 0.9484 | 568 | 0.5600 | 0.9470 |
| **La Liga** | Bet365 | 380 | 0.5640 | 0.9534 | 188 | 0.5581 | 0.9431 | 568 | 0.5621 | 0.9500 |
| **La Liga** | Avg | 380 | 0.5639 | 0.9532 | 188 | 0.5591 | 0.9445 | 568 | 0.5623 | 0.9503 |
| **Bundesliga** | MODELLO | 306 | 0.6213 | 1.0448 | 149 | 0.5912 | 0.9920 | 455 | 0.6115 | 1.0275 |
| **Bundesliga** | PIN pre | 306 | 0.5913 | 0.9898 | 149 | 0.5424 | 0.9226 | 455 | 0.5753 | 0.9678 |
| **Bundesliga** | PIN close | 306 | 0.5901 | 0.9882 | 149 | 0.5409 | 0.9205 | 455 | 0.5740 | 0.9660 |
| **Bundesliga** | Bet365 | 306 | 0.5902 | 0.9883 | 149 | 0.5423 | 0.9222 | 455 | 0.5745 | 0.9666 |
| **Bundesliga** | Avg | 306 | 0.5913 | 0.9900 | 149 | 0.5428 | 0.9231 | 455 | 0.5754 | 0.9681 |
| **Ligue 1** | MODELLO | 306 | 0.6084 | 1.0156 | 153 | 0.5850 | 0.9827 | 459 | 0.6006 | 1.0046 |
| **Ligue 1** | PIN pre | 306 | 0.5668 | 0.9585 | 153 | 0.5648 | 0.9532 | 459 | 0.5661 | 0.9567 |
| **Ligue 1** | PIN close | 306 | 0.5643 | 0.9550 | 153 | 0.5691 | 0.9592 | 459 | 0.5659 | 0.9564 |
| **Ligue 1** | Bet365 | 306 | 0.5676 | 0.9601 | 153 | 0.5640 | 0.9523 | 459 | 0.5664 | 0.9575 |
| **Ligue 1** | Avg | 306 | 0.5668 | 0.9584 | 153 | 0.5649 | 0.9534 | 459 | 0.5662 | 0.9567 |
| **AGGREGATO** | MODELLO | 1752 | 0.6076 | 1.0153 | 898 | 0.5937 | 0.9931 | 2650 | 0.6029 | 1.0077 |
| **AGGREGATO** | PIN pre | 1752 | 0.5728 | 0.9635 | 898 | 0.5725 | 0.9628 | 2650 | 0.5727 | 0.9633 |
| **AGGREGATO** | PIN close | 1752 | 0.5706 | 0.9606 | 898 | 0.5736 | 0.9641 | 2650 | 0.5716 | 0.9618 |
| **AGGREGATO** | Bet365 | 1752 | 0.5734 | 0.9647 | 898 | 0.5725 | 0.9632 | 2650 | 0.5731 | 0.9642 |
| **AGGREGATO** | Avg | 1752 | 0.5731 | 0.9640 | 898 | 0.5724 | 0.9626 | 2650 | 0.5729 | 0.9636 |

## CLV sul lato scommesso (edge>0 vs Pinnacle pre)

`CLV modello = P_modello(lato) - P_chiusura(lato)` (protocollo); `CLV classico = P_pre(lato) - P_chiusura(lato)`. CI bootstrap 95%. ROI chiusura = scommesse settle a quote chiuse Pinnacle (prezzo di riferimento); ROI pre = alle quote pre effettivamente battute.

| Campione | Scommesse | CLV medio | CI 95% | CLV>0 | CLV classico | CI 95% | Clas.>0 | Win rate | ROI chiusura | CI 95% | ROI pre |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Serie A** 2024/25 | 380 | 13.05% | [12.13; 13.98]% | 97.1% | 0.21% | [-0.04; 0.47]% | 53.9% | 40.0% | -2.22% | [-16.19; 11.80]% | -3.10% |
| **Serie A** 2025/26 | 198 | 13.01% | [11.75; 14.23]% | 97.0% | 0.16% | [-0.19; 0.51]% | 47.5% | 45.5% | 16.24% | [-5.49; 37.39]% | 14.97% |
| **Serie A** tot | 578 | 13.04% | [12.30; 13.79]% | 97.1% | 0.19% | [-0.01; 0.40]% | 51.7% | 41.9% | 4.11% | [-7.14; 16.56]% | 3.09% |
| **Premier League** 2024/25 | 380 | 10.58% | [9.82; 11.39]% | 96.6% | 0.14% | [-0.15; 0.41]% | 54.5% | 38.2% | -3.94% | [-19.64; 14.01]% | -5.77% |
| **Premier League** 2025/26 | 210 | 10.59% | [9.62; 11.61]% | 97.6% | -0.10% | [-0.40; 0.19]% | 43.3% | 39.0% | -3.00% | [-21.42; 17.57]% | -3.18% |
| **Premier League** tot | 590 | 10.58% | [9.94; 11.20]% | 96.9% | 0.05% | [-0.15; 0.27]% | 50.5% | 38.5% | -3.61% | [-16.12; 9.49]% | -4.84% |
| **La Liga** 2024/25 | 380 | 10.56% | [9.77; 11.34]% | 96.3% | 0.20% | [-0.11; 0.50]% | 52.6% | 38.9% | -2.06% | [-16.70; 13.04]% | -2.72% |
| **La Liga** 2025/26 | 188 | 10.81% | [9.89; 11.78]% | 98.4% | 0.09% | [-0.17; 0.34]% | 52.1% | 42.6% | 0.44% | [-18.86; 21.33]% | -0.62% |
| **La Liga** tot | 568 | 10.64% | [10.08; 11.24]% | 97.0% | 0.16% | [-0.06; 0.39]% | 52.5% | 40.1% | -1.23% | [-12.66; 11.01]% | -2.02% |
| **Bundesliga** 2024/25 | 306 | 12.59% | [11.61; 13.63]% | 96.7% | 0.36% | [0.04; 0.69]% | 54.6% | 45.8% | 17.06% | [0.15; 35.00]% | 14.64% |
| **Bundesliga** 2025/26 | 149 | 13.42% | [12.02; 14.93]% | 98.0% | 0.40% | [0.04; 0.79]% | 55.0% | 43.6% | 1.48% | [-22.63; 31.49]% | -0.93% |
| **Bundesliga** tot | 455 | 12.87% | [12.06; 13.71]% | 97.1% | 0.37% | [0.13; 0.62]% | 54.7% | 45.1% | 11.95% | [-1.63; 27.14]% | 9.54% |
| **Ligue 1** 2024/25 | 306 | 10.98% | [10.07; 11.94]% | 96.4% | -0.04% | [-0.39; 0.29]% | 54.6% | 34.6% | -0.33% | [-19.45; 20.38]% | -1.58% |
| **Ligue 1** 2025/26 | 153 | 11.75% | [10.55; 13.04]% | 98.0% | 0.20% | [-0.21; 0.63]% | 54.9% | 39.2% | 7.29% | [-17.41; 34.72]% | 4.60% |
| **Ligue 1** tot | 459 | 11.24% | [10.48; 12.01]% | 96.9% | 0.04% | [-0.24; 0.30]% | 54.7% | 36.2% | 2.21% | [-13.37; 17.91]% | 0.48% |
| **AGGREGATO** | 2650 | 11.64% | [11.33; 11.96]% | 97.0% | 0.16% | [0.06; 0.26]% | 52.6% | 40.3% | 2.26% | [-3.65; 8.51]% | 0.88% |

**Lettura**: il CLV di protocollo (11.64%, 97.0% positivo) e' molto piu' alto del CLV classico (0.16%): misura la distanza modello-mercato, non la qualita' del prezzo. Il modello e' sistematicamente meno calibrato della chiusura (Brier 0.6029 vs 0.5716; Delta Brier modello-chiusura +0.0312, CI [0.0224; 0.0398]), quindi un lato con edge positivo vs pre di solito resta in edge anche a chiusura: e' il segno della calibrazione peggiore del modello, non di skill. Il segnale da guardare e' il CLV classico (0.16%, CI [0.06; 0.26]%): l'informazione del modello al momento della scommessa batte la chiusura solo di un margine sottile.

## ROI per book (edge>0 vs quel book, settle su quote reali, puntata 10)

| Campione | Book | Righe | Scommesse | Win rate | ROI |
|---|---|---:|---:|---:|---:|
| **Serie A** | PIN pre | 578 | 578 | 41.9% | 3.09% |
| **Serie A** | PIN close | 578 | 578 | 42.2% | 5.20% |
| **Serie A** | Bet365 | 578 | 578 | 41.7% | 0.59% |
| **Serie A** | Avg | 578 | 578 | 42.0% | 0.85% |
| **Premier League** | PIN pre | 590 | 590 | 38.5% | -4.84% |
| **Premier League** | PIN close | 590 | 590 | 39.3% | -1.45% |
| **Premier League** | Bet365 | 590 | 590 | 39.0% | -5.31% |
| **Premier League** | Avg | 590 | 590 | 38.6% | -6.06% |
| **La Liga** | PIN pre | 568 | 568 | 40.1% | -2.02% |
| **La Liga** | PIN close | 568 | 568 | 39.1% | -2.78% |
| **La Liga** | Bet365 | 568 | 568 | 39.3% | -6.84% |
| **La Liga** | Avg | 568 | 568 | 40.1% | -4.68% |
| **Bundesliga** | PIN pre | 455 | 455 | 45.1% | 9.54% |
| **Bundesliga** | PIN close | 455 | 455 | 42.4% | 6.29% |
| **Bundesliga** | Bet365 | 455 | 455 | 46.4% | 7.99% |
| **Bundesliga** | Avg | 455 | 455 | 45.5% | 7.96% |
| **Ligue 1** | PIN pre | 459 | 459 | 36.2% | 0.48% |
| **Ligue 1** | PIN close | 459 | 459 | 35.5% | 0.08% |
| **Ligue 1** | Bet365 | 459 | 459 | 36.4% | -2.81% |
| **Ligue 1** | Avg | 459 | 459 | 36.2% | -3.60% |
| **AGGREGATO** | PIN pre | 2650 | 2650 | 40.3% | 0.88% |
| **AGGREGATO** | PIN close | 2650 | 2650 | 39.8% | 1.31% |
| **AGGREGATO** | Bet365 | 2650 | 2650 | 40.5% | -1.64% |
| **AGGREGATO** | Avg | 2650 | 2650 | 40.5% | -1.42% |

## Pinnacle da' un segnale diverso da Bet365/Avg?

Delta Brier appaiati (B - A) sullo stesso campione, CI bootstrap 95%. Delta > 0 significa che il book B e' MENO calibrated (Brier peggiore).

| Confronto | n | Delta Brier | CI 95% |
|---|---:|---:|---:|
| MODELLO - PIN close | 2650 | +0.0312 | [+0.0224; +0.0398] |
| PIN close - Bet365 | 2650 | -0.0014 | [-0.0032; +0.0004] |
| PIN close - Avg | 2650 | -0.0012 | [-0.0030; +0.0006] |

Sul campione aggregato la differenza tra chiusura Pinnacle e Bet365 non e' distinguishable dal rumore (CI che contiene 0): Pinnacle e Bet365/Avg danno lo stesso tipo di segnale di calibrazione sui dati correnti; la differenza pratica sta nel prezzo (margine tipicamente minore su Pinnacle), non nella direzione.

## Limiti dichiarati

1. **xG snapshot statico**: la testa 1X2 usa `xg_<lega>.json` aggiornato a oggi (come in tutti gli audit del progetto che replicano la produzione): nelle stagioni passate lo snapshot e' piu' informativo di quanto fosse all'epoca. Vale anche per il boost xG assente nell'Elo di replica.
2. **Elo di replica**: K fisso 24 senza moltiplicatore di scarto gol e senza boost xG (formula `predict_elo_probs` di produzione), secondo la replica validata di `diagnose_elo_ensemble.py` che ha introdotto il blend 0.6/0.4 in produzione.
3. **CLV protocollo vs classico**: il CLV richiesto misura l'edge residuo del modello a chiusura (probabilita', non prezzi): e' sensibile alla calibrazione del modello, non solo al timing della scommessa. Il CLV classico e' riportato per separare i due effetti.
4. **Chiusura come prezzo di riferimento**: il ROI a chiusura non e' eseguibile in pratica (la selezione avviene sulla linea pre): e' il riferimento richiesto dal protocollo, il ROI a pre e' riportato accanto.
5. **Quote una sola casa per confronto**: Pinnacle pre/chiusura non hanno timestamp; le colonne football-data sono apertura e chiusura come da rilascio del dataset. Bet365/Avg usano le stesse convenzioni degli altri audit (B365*/Avg*).

