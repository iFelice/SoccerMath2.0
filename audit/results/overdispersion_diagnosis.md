# Diagnosi overdispersion — gol segnati in casa (FTHG) e in trasferta (FTAG)

Campione: TUTTE le stagioni complete disponibili **2022/23, 2023/24, 2024/25, 2025/26** per le 5 leghe (la stagione Live 2026/27 e' esclusa perche' incompleta).

Le due serie di conteggio (FTHG = gol segnati dai padroni di casa, FTAG = gol segnati dagli ospiti) sono trattate **separatamente**, non come totale della partita.

Metodo:

- **Poisson pura** (MLE, 1 parametro: lambda = media). Per definizione varianza = media.
- **Negative Binomial NB2** (MLE, 2 parametri: mu, alpha), parametrizzazione media-dispersione `Var = mu + alpha * mu^2`. Fit con `statsmodels.discrete.NegativeBinomial` (loglike NB2) su sola intercetta; alpha = **parametro di dispersione** (alpha = 0 => Poisson pura).
- **AIC** = 2k - 2*logL, **BIC** = k*ln(n) - 2*logL (k=1 Poisson, k=2 NegBin). Valori piu' bassi = modello preferito.
- **Indice di dispersione** = varianza campionaria (ddof=1) / media. `> 1` overdispersion rispetto a Poisson; `~ 1` Poisson adeguata.

## Tabella riassuntiva per lega / serie

| Lega | Serie | n | Media | Varianza | Indice disp. (var/media) | AIC Poisson | AIC NegBin | BIC Poisson | BIC NegBin | alpha NegBin |
|---|---|---|---|---|---|---|---|---|---|---|
| Serie A | FTHG (gol casa) | 1520 | 1.366 | 1.421 | 1.040 | 4547.3 | 4548.2 | 4552.7 | 4558.9 | 0.0284 |
| Serie A | FTAG (gol trasferta) | 1520 | 1.174 | 1.186 | 1.010 | 4257.7 | 4259.7 | 4263.1 | 4270.3 | 0.0087 |
| Premier League | FTHG (gol casa) | 1520 | 1.618 | 1.731 | 1.069 | 4888.2 | 4886.8 | 4893.5 | 4897.4 | 0.0433 |
| Premier League | FTAG (gol trasferta) | 1520 | 1.336 | 1.417 | 1.061 | 4520.7 | 4520.2 | 4526.1 | 4530.8 | 0.0438 |
| La Liga | FTHG (gol casa) | 1520 | 1.491 | 1.546 | 1.036 | 4689.3 | 4690.4 | 4694.7 | 4701.1 | 0.0232 |
| La Liga | FTAG (gol trasferta) | 1520 | 1.126 | 1.093 | 0.970 | 4148.4 | 4150.4 | 4153.7 | 4161.0 | 0.0003 |
| Bundesliga | FTHG (gol casa) | 1224 | 1.768 | 2.049 | 1.159 | 4130.5 | 4118.9 | 4135.6 | 4129.1 | 0.0906 |
| Bundesliga | FTAG (gol trasferta) | 1224 | 1.422 | 1.548 | 1.088 | 3757.7 | 3755.4 | 3762.8 | 3765.6 | 0.0617 |
| Ligue 1 | FTHG (gol casa) | 1298 | 1.529 | 1.666 | 1.090 | 4094.7 | 4091.9 | 4099.8 | 4102.3 | 0.0577 |
| Ligue 1 | FTAG (gol trasferta) | 1298 | 1.296 | 1.447 | 1.116 | 3856.2 | 3850.6 | 3861.4 | 3860.9 | 0.0875 |

## Confronto modelli: delta AIC/BIC (Poisson - NegBin) e verdetto

delta positivo = la NegBin e' preferita (AIC/BIC piu' basso). Regola pratica: |delta| < 2 differenza trascurabile, 2-6 debole, 6-10 forte, > 10 molto forte a favore del modello migliore.

| Lega | Serie | dAIC (P-NB) | dBIC (P-NB) | Indice disp. | Modello preferito |
|---|---|---|---|---|---|
| Serie A | FTHG (gol casa) | -0.9 | -6.2 | 1.040 | Poisson |
| Serie A | FTAG (gol trasferta) | -1.9 | -7.3 | 1.010 | Poisson |
| Premier League | FTHG (gol casa) | 1.4 | -3.9 | 1.069 | Poisson |
| Premier League | FTAG (gol trasferta) | 0.5 | -4.8 | 1.061 | Poisson |
| La Liga | FTHG (gol casa) | -1.1 | -6.4 | 1.036 | Poisson |
| La Liga | FTAG (gol trasferta) | -2.0 | -7.3 | 0.970 | Poisson |
| Bundesliga | FTHG (gol casa) | 11.7 | 6.5 | 1.159 | NegBin |
| Bundesliga | FTAG (gol trasferta) | 2.3 | -2.8 | 1.088 | Poisson |
| Ligue 1 | FTHG (gol casa) | 2.7 | -2.5 | 1.090 | Poisson |
| Ligue 1 | FTAG (gol trasferta) | 5.7 | 0.5 | 1.116 | equivalenti |

## Sintesi

- Serie totali analizzate: **10** (2 serie x 5 leghe).
- Serie con indice di dispersione > 1.05 (overdispersion apprezzabile): **6/10**.
- Serie con indice di dispersione < 0.95 (underdispersion): **0/10**.
- Serie in cui la NegBin batte la Poisson per **AIC** (delta > 2): **4/10**.
- Serie in cui la NegBin batte la Poisson per **BIC** (delta > 2): **1/10**.

- Indice di dispersione medio su tutte le serie: **1.064**.
- alpha NegBin medio su tutte le serie: **0.0445** (vicino a 0 => la Poisson e' gia' una buona approssimazione).

**Lettura.** Un indice di dispersione vicino a 1 e un alpha vicino a 0, con AIC/BIC che non preferiscono nettamente la NegBin, indicano che la distribuzione dei gol segnati (per singola squadra, casa o trasferta) e' ben descritta da una Poisson pura: l'eventuale sovradispersione osservata nei gol *totali* di partita nasce dalla somma/correlazione delle due marginali e dall'eterogeneita' tra squadre, non dalla marginale di conteggio in se'. Dove invece l'indice supera 1 e la NegBin e' preferita da BIC, c'e' overdispersion reale nella marginale.

## Note

- Dati caricati via `load_league` da `backtest_experiment_all.py` (import in sola lettura): stessa pulizia/dedup usata dal backtest. Nessun file di SoccerMath/ e' stato modificato.
- Varianza campionaria con `ddof=1`. Con n grande (centinaia di osservazioni per serie) la differenza rispetto a ddof=0 e' trascurabile per l'indice di dispersione.
- La NegBin e' fittata con la parametrizzazione media-dispersione NB2; il parametro riportato e' alpha. Conversione a `scipy.stats.nbinom`: size `r = 1/alpha`, prob `p = r/(r+mu)`.
- Tutti i fit NegBin (statsmodels) sono andati a convergenza.

