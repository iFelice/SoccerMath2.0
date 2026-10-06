# CLV vs Pinnacle — mercato 1X2 (audit sola lettura)

*Generato: 2026-10-06T21:26:10.215759+00:00 — script `audit/diagnose_clv_pinnacle.py`, nessuna modifica a SoccerMath/.*

Split walk-forward identico agli altri audit: train 2022/23+2023/24, validation (V) 2024/25, test (T) 2025/26. Il Live 2026/27 resta fuori dall'eval (nessuna quota Pinnacle comunque).

## Copertura quote Pinnacle (partite senza quota: ESCLUSE, non stimate)

Quota valida = presente, numerica e > 1.0 (regola di `devig_1x2`). Il campione usabile richiede PRE **e** chiusura: senza una delle due la partita esce da tutte le metriche Pinnacle/CLV (Bet365/Avg vengono mascherate per-riga se mancanti). Nessuna imputazione.

| Lega | Stagione | Partite | PSH ok | PSH mancante | PSCH ok | PSCH mancante | Usabili (pre+close) | % usabili | Eval |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| Serie A | 2022/23 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | no |
| Serie A | 2023/24 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | no |
| Serie A | 2024/25 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | si |
| Serie A | 2025/26 | 380 | 200 | 180 | 198 | 182 | 198 | 52.1% | si |
| Serie A | 2026/27 | 50 | 0 | 50 | 0 | 50 | 0 | 0.0% | no |
| Premier League | 2022/23 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | no |
| Premier League | 2023/24 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | no |
| Premier League | 2024/25 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | si |
| Premier League | 2025/26 | 380 | 210 | 170 | 210 | 170 | 210 | 55.3% | si |
| Premier League | 2026/27 | 50 | 0 | 50 | 0 | 50 | 0 | 0.0% | no |
| La Liga | 2022/23 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | no |
| La Liga | 2023/24 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | no |
| La Liga | 2024/25 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | si |
| La Liga | 2025/26 | 380 | 189 | 191 | 188 | 192 | 188 | 49.5% | si |
| La Liga | 2026/27 | 71 | 0 | 71 | 0 | 71 | 0 | 0.0% | no |
| Bundesliga | 2022/23 | 306 | 306 | 0 | 306 | 0 | 306 | 100.0% | no |
| Bundesliga | 2023/24 | 306 | 306 | 0 | 306 | 0 | 306 | 100.0% | no |
| Bundesliga | 2024/25 | 306 | 306 | 0 | 306 | 0 | 306 | 100.0% | si |
| Bundesliga | 2025/26 | 306 | 150 | 156 | 149 | 157 | 149 | 48.7% | si |
| Bundesliga | 2026/27 | 36 | 0 | 36 | 0 | 36 | 0 | 0.0% | no |
| Ligue 1 | 2022/23 | 380 | 380 | 0 | 380 | 0 | 380 | 100.0% | no |
| Ligue 1 | 2023/24 | 306 | 306 | 0 | 306 | 0 | 306 | 100.0% | no |
| Ligue 1 | 2024/25 | 306 | 306 | 0 | 306 | 0 | 306 | 100.0% | si |
| Ligue 1 | 2025/26 | 306 | 153 | 153 | 153 | 153 | 153 | 50.0% | si |
| Ligue 1 | 2026/27 | 45 | 0 | 45 | 0 | 45 | 0 | 0.0% | no |

**Totale eval (V+T): 2650 partite usabili su 3504 (75.6%).** Le mancanze sono concentrate in 2025/26 (stagione in corso allo scraping: Pinnacle presente solo sulle partite gia' disputate con quotazione chiusa) e nel Live 2026/27 (nessuna quota); le stagioni 2022/23-2024/25 sono coperte al 100%. PSH vs PSCH differiscono per 1-2 partite per lega nel 2025/26 (partite appena giocate: apertura senza chiusura): escluse come da protocollo.

## Metodo

- **Modello**: testa 1X2 PRODUZIONE_DUE_TESTE (NORM-SUM: xG snapshot + forma ultime 5 + fattore mercato, lambda normalizzati alla somma base S, clip [exp(-6), exp(3)]) con ensemble Elo **opzione b gia' in produzione**: 1X2 = 0.25*Poisson + 0.75*Elo (`app.POISSON_1X2_WEIGHT`, validato in `diagnose_elo_ensemble.py`, applicato in `app.blend_elo_into_1x2`). Elo walk-forward K=24 replica di `diagnose_elo_ensemble.py`, aggiornato DOPO ogni previsione: nessuna partita usa se stessa o il futuro. Il ramo NORM-SUM del walker e' verificato bit-faithful a `diagnose_production_baseline.run_models` da `test_diagnose_clv_pinnacle.py`.
- **De-vig**: proporzionale standard `1/quota / overround` = `devig_1x2` di `backtest_experiment_all.py` (il brief citava `devig_2way`: e' la variante a 2 esiti dello stesso file; per il 1X2 vale il precedente a 3 esiti).
- **CLV (protocollo)**: sul lato scommesso dal modello (edge>0 vs linea PRE Pinnacle de-vigata, convenzione `EDGE_MIN=0`): `CLV = P_modello(lato) - P_chiusura(lato)`. Accanto, il **CLV classico** `P_pre(lato) - P_chiusura(lato)` (prezzo preso vs chiusura) per il confronto con la letteratura: il primo misura l'edge residuo del modello a chiusura, il secondo la qualita' del prezzo preso.
- **ROI a puntata fissa**: (a) sulle stesse scommesse CLV, settle alla **chiusura Pinnacle** come prezzo di riferimento richiesto (e a pre, informativo); (b) ROI per book con selezione edge>0 vs quel book e settle sulle quote reali di quel book (`roi_1x2` di `diagnose_production_baseline.py`, identica agli altri audit).
- **Bootstrap**: 2000 resample di righe, seed 20260905, CI percentile 2.5-97.5 (costanti `N_BOOT`/`SEED` e formula `_ci` di `topmix_margins.py`; il file `diagnose_rho_bootstrap.py` citato dal protocollo non esiste nel repo, e `diagnose_dixon_coles_rho.py` non contiene bootstrap).

## Calibrazione 1X2: modello vs Pinnacle pre vs chiusura vs Bet365 vs Avg

Campione = partite eval con Pinnacle pre+close valide (Bet365/Avg mascherate per-riga dove mancano). Brier/LogLoss multiclasse (`brier_ll_1x2`).

| Campione | Book | n V | Brier V | LogLoss V | n T | Brier T | LogLoss T | n tot | Brier tot | LogLoss tot |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Serie A** | MODELLO | 380 | 0.5897 | 0.9888 | 198 | 0.6024 | 1.0072 | 578 | 0.5940 | 0.9951 |
| **Serie A** | PIN pre | 380 | 0.5660 | 0.9506 | 198 | 0.5937 | 0.9905 | 578 | 0.5755 | 0.9642 |
| **Serie A** | PIN close | 380 | 0.5669 | 0.9513 | 198 | 0.5948 | 0.9907 | 578 | 0.5764 | 0.9648 |
| **Serie A** | Bet365 | 380 | 0.5684 | 0.9548 | 198 | 0.5942 | 0.9922 | 578 | 0.5773 | 0.9676 |
| **Serie A** | Avg | 380 | 0.5669 | 0.9519 | 198 | 0.5933 | 0.9902 | 578 | 0.5759 | 0.9650 |
| **Premier League** | MODELLO | 380 | 0.5878 | 0.9879 | 210 | 0.5938 | 0.9950 | 590 | 0.5899 | 0.9904 |
| **Premier League** | PIN pre | 380 | 0.5788 | 0.9703 | 210 | 0.5917 | 0.9888 | 590 | 0.5834 | 0.9769 |
| **Premier League** | PIN close | 380 | 0.5751 | 0.9664 | 210 | 0.5911 | 0.9875 | 590 | 0.5808 | 0.9739 |
| **Premier League** | Bet365 | 380 | 0.5787 | 0.9708 | 210 | 0.5925 | 0.9910 | 590 | 0.5836 | 0.9780 |
| **Premier League** | Avg | 380 | 0.5789 | 0.9706 | 210 | 0.5912 | 0.9878 | 590 | 0.5833 | 0.9767 |
| **La Liga** | MODELLO | 380 | 0.5767 | 0.9709 | 188 | 0.5621 | 0.9512 | 568 | 0.5718 | 0.9644 |
| **La Liga** | PIN pre | 380 | 0.5635 | 0.9524 | 188 | 0.5590 | 0.9445 | 568 | 0.5620 | 0.9498 |
| **La Liga** | PIN close | 380 | 0.5593 | 0.9463 | 188 | 0.5614 | 0.9484 | 568 | 0.5600 | 0.9470 |
| **La Liga** | Bet365 | 380 | 0.5640 | 0.9534 | 188 | 0.5581 | 0.9431 | 568 | 0.5621 | 0.9500 |
| **La Liga** | Avg | 380 | 0.5639 | 0.9532 | 188 | 0.5591 | 0.9445 | 568 | 0.5623 | 0.9503 |
| **Bundesliga** | MODELLO | 306 | 0.6116 | 1.0236 | 149 | 0.5568 | 0.9467 | 455 | 0.5937 | 0.9984 |
| **Bundesliga** | PIN pre | 306 | 0.5913 | 0.9898 | 149 | 0.5424 | 0.9226 | 455 | 0.5753 | 0.9678 |
| **Bundesliga** | PIN close | 306 | 0.5901 | 0.9882 | 149 | 0.5409 | 0.9205 | 455 | 0.5740 | 0.9660 |
| **Bundesliga** | Bet365 | 306 | 0.5902 | 0.9883 | 149 | 0.5423 | 0.9222 | 455 | 0.5745 | 0.9666 |
| **Bundesliga** | Avg | 306 | 0.5913 | 0.9900 | 149 | 0.5428 | 0.9231 | 455 | 0.5754 | 0.9681 |
| **Ligue 1** | MODELLO | 306 | 0.5824 | 0.9803 | 153 | 0.5742 | 0.9678 | 459 | 0.5796 | 0.9762 |
| **Ligue 1** | PIN pre | 306 | 0.5668 | 0.9585 | 153 | 0.5648 | 0.9532 | 459 | 0.5661 | 0.9567 |
| **Ligue 1** | PIN close | 306 | 0.5643 | 0.9550 | 153 | 0.5691 | 0.9592 | 459 | 0.5659 | 0.9564 |
| **Ligue 1** | Bet365 | 306 | 0.5676 | 0.9601 | 153 | 0.5640 | 0.9523 | 459 | 0.5664 | 0.9575 |
| **Ligue 1** | Avg | 306 | 0.5668 | 0.9584 | 153 | 0.5649 | 0.9534 | 459 | 0.5662 | 0.9567 |
| **AGGREGATO** | MODELLO | 1752 | 0.5890 | 0.9893 | 898 | 0.5796 | 0.9759 | 2650 | 0.5858 | 0.9848 |
| **AGGREGATO** | PIN pre | 1752 | 0.5728 | 0.9635 | 898 | 0.5725 | 0.9628 | 2650 | 0.5727 | 0.9633 |
| **AGGREGATO** | PIN close | 1752 | 0.5706 | 0.9606 | 898 | 0.5736 | 0.9641 | 2650 | 0.5716 | 0.9618 |
| **AGGREGATO** | Bet365 | 1752 | 0.5734 | 0.9647 | 898 | 0.5725 | 0.9632 | 2650 | 0.5731 | 0.9642 |
| **AGGREGATO** | Avg | 1752 | 0.5731 | 0.9640 | 898 | 0.5724 | 0.9626 | 2650 | 0.5729 | 0.9636 |

## CLV sul lato scommesso (edge>0 vs Pinnacle pre)

`CLV modello = P_modello(lato) - P_chiusura(lato)` (protocollo); `CLV classico = P_pre(lato) - P_chiusura(lato)`. CI bootstrap 95%. ROI chiusura = scommesse settle a quote chiuse Pinnacle (prezzo di riferimento); ROI pre = alle quote pre effettivamente battute.

| Campione | Scommesse | CLV medio | CI 95% | CLV>0 | CLV classico | CI 95% | Clas.>0 | Win rate | ROI chiusura | CI 95% | ROI pre |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Serie A** 2024/25 | 375 | 7.05% | [6.58; 7.55]% | 96.5% | 0.34% | [0.10; 0.57]% | 56.0% | 23.7% | -27.73% | [-42.64; -11.75]% | -29.71% |
| **Serie A** 2025/26 | 195 | 6.70% | [6.13; 7.28]% | 99.0% | 0.61% | [0.30; 0.92]% | 57.9% | 31.8% | -8.04% | [-29.87; 14.99]% | -10.13% |
| **Serie A** tot | 570 | 6.93% | [6.57; 7.31]% | 97.4% | 0.43% | [0.24; 0.63]% | 56.7% | 26.5% | -20.99% | [-33.30; -7.83]% | -23.01% |
| **Premier League** 2024/25 | 369 | 6.23% | [5.80; 6.68]% | 95.7% | 0.12% | [-0.15; 0.39]% | 56.1% | 28.2% | -6.36% | [-24.71; 13.07]% | -9.14% |
| **Premier League** 2025/26 | 205 | 6.85% | [6.20; 7.49]% | 98.0% | 0.05% | [-0.22; 0.33]% | 51.7% | 30.2% | -5.41% | [-26.82; 17.21]% | -5.91% |
| **Premier League** tot | 574 | 6.46% | [6.10; 6.84]% | 96.5% | 0.09% | [-0.11; 0.29]% | 54.5% | 28.9% | -6.02% | [-20.07; 9.25]% | -7.99% |
| **La Liga** 2024/25 | 373 | 6.80% | [6.32; 7.27]% | 96.8% | 0.41% | [0.12; 0.71]% | 58.2% | 30.0% | 1.54% | [-19.75; 25.45]% | -3.02% |
| **La Liga** 2025/26 | 181 | 5.65% | [5.12; 6.19]% | 99.4% | 0.29% | [0.05; 0.52]% | 55.2% | 31.5% | -3.04% | [-27.67; 22.96]% | -5.94% |
| **La Liga** tot | 554 | 6.43% | [6.08; 6.80]% | 97.7% | 0.37% | [0.18; 0.58]% | 57.2% | 30.5% | 0.05% | [-16.21; 18.17]% | -3.98% |
| **Bundesliga** 2024/25 | 295 | 6.86% | [6.35; 7.40]% | 95.3% | 0.50% | [0.20; 0.80]% | 59.3% | 30.8% | -5.46% | [-25.25; 16.33]% | -8.48% |
| **Bundesliga** 2025/26 | 144 | 7.03% | [6.02; 8.10]% | 93.8% | 0.30% | [-0.09; 0.72]% | 50.7% | 33.3% | -17.06% | [-37.22; 5.67]% | -18.38% |
| **Bundesliga** tot | 439 | 6.92% | [6.44; 7.41]% | 94.8% | 0.43% | [0.19; 0.67]% | 56.5% | 31.7% | -9.26% | [-24.05; 7.71]% | -11.73% |
| **Ligue 1** 2024/25 | 296 | 6.89% | [6.34; 7.48]% | 93.9% | 0.02% | [-0.31; 0.35]% | 53.4% | 28.7% | 0.45% | [-20.43; 23.39]% | 0.22% |
| **Ligue 1** 2025/26 | 151 | 5.87% | [5.25; 6.53]% | 95.4% | 0.10% | [-0.32; 0.53]% | 51.7% | 29.8% | -1.02% | [-27.65; 29.34]% | -2.81% |
| **Ligue 1** tot | 447 | 6.55% | [6.10; 6.99]% | 94.4% | 0.04% | [-0.22; 0.31]% | 52.8% | 29.1% | -0.05% | [-16.68; 16.47]% | -0.81% |
| **AGGREGATO** | 2584 | 6.65% | [6.47; 6.83]% | 96.3% | 0.28% | [0.18; 0.37]% | 55.6% | 29.2% | -7.54% | [-14.21; -0.50]% | -9.83% |

**Lettura**: il CLV di protocollo (6.65%, 96.3% positivo) e' molto piu' alto del CLV classico (0.28%): misura la distanza modello-mercato, non la qualita' del prezzo. Il modello e' sistematicamente meno calibrato della chiusura (Brier 0.5858 vs 0.5716; Delta Brier modello-chiusura +0.0142, CI [0.0095; 0.0192]), quindi un lato con edge positivo vs pre di solito resta in edge anche a chiusura: e' il segno della calibrazione peggiore del modello, non di skill. Il segnale da guardare e' il CLV classico (0.28%, CI [0.18; 0.37]%): l'informazione del modello al momento della scommessa batte la chiusura solo di un margine sottile.

## ROI per book (edge>0 vs quel book, settle su quote reali, puntata 10)

| Campione | Book | Righe | Scommesse | Win rate | ROI |
|---|---|---:|---:|---:|---:|
| **Serie A** | PIN pre | 578 | 570 | 26.5% | -23.01% |
| **Serie A** | PIN close | 578 | 574 | 26.8% | -19.83% |
| **Serie A** | Bet365 | 578 | 554 | 27.6% | -21.03% |
| **Serie A** | Avg | 578 | 558 | 26.9% | -25.63% |
| **Premier League** | PIN pre | 590 | 574 | 28.9% | -7.99% |
| **Premier League** | PIN close | 590 | 582 | 28.4% | -7.04% |
| **Premier League** | Bet365 | 590 | 541 | 29.4% | -8.15% |
| **Premier League** | Avg | 590 | 559 | 28.1% | -12.68% |
| **La Liga** | PIN pre | 568 | 554 | 30.5% | -3.98% |
| **La Liga** | PIN close | 568 | 562 | 30.1% | 0.87% |
| **La Liga** | Bet365 | 568 | 525 | 30.9% | -5.33% |
| **La Liga** | Avg | 568 | 529 | 30.2% | -9.01% |
| **Bundesliga** | PIN pre | 455 | 439 | 31.7% | -11.73% |
| **Bundesliga** | PIN close | 455 | 445 | 32.1% | -8.96% |
| **Bundesliga** | Bet365 | 455 | 403 | 30.5% | -16.99% |
| **Bundesliga** | Avg | 455 | 409 | 31.1% | -14.90% |
| **Ligue 1** | PIN pre | 459 | 447 | 29.1% | -0.81% |
| **Ligue 1** | PIN close | 459 | 452 | 26.8% | -5.74% |
| **Ligue 1** | Bet365 | 459 | 433 | 28.4% | -4.37% |
| **Ligue 1** | Avg | 459 | 421 | 29.0% | -2.78% |
| **AGGREGATO** | PIN pre | 2650 | 2584 | 29.2% | -9.83% |
| **AGGREGATO** | PIN close | 2650 | 2615 | 28.8% | -8.25% |
| **AGGREGATO** | Bet365 | 2650 | 2456 | 29.3% | -11.24% |
| **AGGREGATO** | Avg | 2650 | 2476 | 28.9% | -13.50% |

## Pinnacle da' un segnale diverso da Bet365/Avg?

Delta Brier appaiati (B - A) sullo stesso campione, CI bootstrap 95%. Delta > 0 significa che il book B e' MENO calibrated (Brier peggiore).

| Confronto | n | Delta Brier | CI 95% |
|---|---:|---:|---:|
| MODELLO - PIN close | 2650 | +0.0142 | [+0.0095; +0.0192] |
| PIN close - Bet365 | 2650 | -0.0014 | [-0.0032; +0.0004] |
| PIN close - Avg | 2650 | -0.0012 | [-0.0030; +0.0006] |

Sul campione aggregato la differenza tra chiusura Pinnacle e Bet365 non e' distinguishable dal rumore (CI che contiene 0): Pinnacle e Bet365/Avg danno lo stesso tipo di segnale di calibrazione sui dati correnti; la differenza pratica sta nel prezzo (margine tipicamente minore su Pinnacle), non nella direzione.

## Limiti dichiarati

1. **xG snapshot statico**: la testa 1X2 usa `xg_<lega>.json` aggiornato a oggi (come in tutti gli audit del progetto che replicano la produzione): nelle stagioni passate lo snapshot e' piu' informativo di quanto fosse all'epoca. Vale anche per il boost xG assente nell'Elo di replica.
2. **Elo di replica**: K fisso 24 senza moltiplicatore di scarto gol e senza boost xG (formula `predict_elo_probs` di produzione), secondo la replica validata di `diagnose_elo_ensemble.py` che ha introdotto il blend 0.6/0.4 in produzione.
3. **CLV protocollo vs classico**: il CLV richiesto misura l'edge residuo del modello a chiusura (probabilita', non prezzi): e' sensibile alla calibrazione del modello, non solo al timing della scommessa. Il CLV classico e' riportato per separare i due effetti.
4. **Chiusura come prezzo di riferimento**: il ROI a chiusura non e' eseguibile in pratica (la selezione avviene sulla linea pre): e' il riferimento richiesto dal protocollo, il ROI a pre e' riportato accanto.
5. **Quote una sola casa per confronto**: Pinnacle pre/chiusura non hanno timestamp; le colonne football-data sono apertura e chiusura come da rilascio del dataset. Bet365/Avg usano le stesse convenzioni degli altri audit (B365*/Avg*).

