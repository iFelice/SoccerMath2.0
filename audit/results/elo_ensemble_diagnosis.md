# Diagnosi: ensemble 0.6*Poisson + 0.4*Elo sul 1X2 (5 leghe)

_Generato da `diagnose_elo_ensemble.py` il 04/09/2026 08:25._

## Domanda
La confidence dell'app sul 1X2 (Top Mix) e' `0.6*Poisson + 0.4*Elo` con
filtro di disaccordo `|p_poisson - p_elo| < 0.25`: i pesi e la soglia,
scritti a mano, migliorano davvero la calibrazione rispetto al solo Poisson?

## Metodologia (walk-forward, no leakage)
- Window: **validation 2024/25 + test 2025/26**, 5 leghe; training 2022/23+2023/24.
- Poisson 1X2 = testa 1X2 del Poisson a Due Teste di produzione (lambda
  forma+mercato normalizzati alla somma base pura, clip, matrice 15x15).
- Elo = formula esatta di `models/elo_engine.py` (K x margine gol, boost xG
  solo nell'aggiornamento, p_draw gaussiana clip [0.06, 0.34]), rating
  ricostruito cronologicamente senza futuro.
- Metriche: Brier multiclasse, LogLoss, win rate (definizioni di `models/backtest.py`).

## Risultato per lega

| Lega | N | Brier Poisson | Brier Elo | Brier Ensemble | LogLoss P/E/Ens | Win% P/E/Ens |
|---|---|---|---|---|---|---|
| Serie A | 760 | 0.602 | 0.605 | 0.594 | 1.012/1.014/0.995 | 52.6%/51.2%/52.2% |
| Premier League | 760 | 0.629 | 0.612 | 0.614 | 1.047/1.022/1.021 | 49.5%/50.0%/49.1% |
| La Liga | 760 | 0.595 | 0.591 | 0.585 | 1.013/0.993/0.983 | 52.1%/51.6%/51.8% |
| Bundesliga | 612 | 0.607 | 0.607 | 0.597 | 1.034/1.017/1.003 | 51.6%/50.3%/51.1% |
| Ligue 1 | 612 | 0.612 | 0.596 | 0.595 | 1.039/1.000/0.999 | 52.0%/52.8%/52.8% |
| **Pooled** | **3504** | **0.609** | **0.602** | **0.597** | **1.028/1.009/1.000** | **51.5%/51.1%/51.4%** |

## Ensemble vs Poisson, partita per partita

| Lega | % partite con Brier ensemble < Poisson |
|---|---|
| Serie A | 42.5% |
| Premier League | 47.9% |
| La Liga | 42.1% |
| Bundesliga | 44.8% |
| Ligue 1 | 44.3% |
| **Pooled** | **44.3%** |

## Filtro di disaccordo dell'app (outcome scelto dal Poisson)

| Lega | media |p_pois - p_elo| | % partite rifiutate (diff ≥ 0.25) | Win% ensemble sul sottinsieme accettato |
|---|---|---|---|
| Serie A | 0.121 | 7.4% | 51.4% |
| Premier League | 0.120 | 7.4% | 48.7% |
| La Liga | 0.117 | 7.4% | 51.3% |
| Bundesliga | 0.132 | 11.3% | 49.4% |
| Ligue 1 | 0.131 | 10.9% | 51.7% |
| **Pooled** | **0.123** | **8.7%** | **50.5%** |

## Verdetto

**Con la formulazione di produzione attuale, l'ensemble 0.6P+0.4E migliora il Brier pooled rispetto alla sola testa 1X2 del Poisson** (0.609 → 0.597) e il LogLoss (1.028 → 1.000), batte il Poisson in Brier in tutte e 5 le leghe (l'Elo puro: 3 su 5). Attenzione pero' alla struttura del vantaggio: partita per partita l'ensemble e' migliore solo nel 44% dei casi, e il win rate dei tre modelli e' praticamente identico (51.5% / 51.1% / 51.4%): il Brier scende per poche partite molto migliorate, mentre sulla maggior parte l'ensemble aggiunge lieve rumore. Il filtro di disaccordo scarta il 9% delle partite ma il win rate del sottinsieme accettato (50.5%) e' INFERIORE a quello sull'intero (51.4%): oggi non funziona da gate di qualita'. Nota: questo contrasta con il risultato di `analyze.py` su Serie A (Poisson > ensemble), che confrontava un Poisson a testa singola SENZA forma/mercato e un Elo semplificato (K fisso, senza xG): la testa 1X2 di produzione (Due Teste) e l'Elo di produzione (K x margine gol + xG) sono formulazioni diverse. **Conclusione: i pesi 0.6/0.4 e la soglia 0.25 restano costanti non validate (punto 1.6) e il gap di Brier pooled (~0.012) e' dentro il rumore di questo campione: serve la grid search del piano (Priorita' 2, punto 8) per decidere.**
