# Diagnosi MLE attacco/difesa (Dixon-Coles) vs euristica team_attr()

Confronto della stima dei parametri di forza squadra, isolando il **solo** effetto della stima attack/defence: **entrambe** le varianti usano rho = 0 (nessuna correzione tau di Dixon-Coles sulle celle basse).

- **BASELINE** — euristica attuale `team_attr()` (medie di rapporti gol semplici per squadra), la stessa di `diagnose_ou_gg.py` / `diagnose_dixon_coles_rho.py` e della produzione. Riusa `run_walkforward_lambda` (import in sola lettura).
- **MLE** — stima congiunta di massima verosimiglianza Poisson: per ogni squadra `attack_i`, `defence_i`; un `home_adv` globale.

```
log(lambda_home) = home_adv + attack_home - defence_away
log(lambda_away) =            attack_away - defence_home
```

Vincolo di identificabilita': media(attack_i) = 0 (ricentraggio degli attacchi nella funzione obiettivo). Ottimizzazione con `scipy.optimize.minimize(method="L-BFGS-B")`.

**Walk-forward no-leakage con refit mensile.** A ogni inizio-mese i parametri MLE vengono rifittati usando SOLO le partite con `Date < inizio mese` (finestra di training espansiva, mai dati futuri rispetto al refit); quei parametri fissi predicono poi tutte le partite del mese. Il primo refit parte dalle prime partite disponibili (2022/23).

**Valutazione.** VALIDATION 2024/25 + TEST 2025/26, tutte le 5 leghe. Metriche Brier Score e Log Loss su 1X2, Over/Under 2.5, GG/NG. Stessa costruzione delle celle (`build_matrix` rho=0, `market_probs_from_matrix`) degli script precedenti.

Delta = BASELINE - MLE: **positivo => MLE migliore** (Brier/LogLoss piu' bassi).

## Costo computazionale

L'architettura MLE e' piu' pesante dell'euristica: rifitta decine di parametri (2 per squadra + home_adv) a ogni inizio-mese.

| Voce | Valore |
|---|---|
| Tempo totale esecuzione | 33.9 s |
| Tempo speso nel walk-forward MLE (5 leghe) | 8.9 s |
| Tempo speso nella BASELINE euristica (5 leghe) | 1.0 s |
| Numero totale di refit MLE eseguiti | 100 |
| Tempo medio per refit MLE | 0.089 s |

## SERIE A  (N=760 val+test, refit MLE=20)

| Mercato | Metrica | BASELINE | MLE | Delta (base-MLE) |
|---|---|---|---|---|
| 1X2 | Brier | 0.5884 | 0.5893 | -0.0009 (BASELINE meglio) |
| 1X2 | LogLoss | 0.9858 | 0.9878 | -0.0020 (BASELINE meglio) |
| O/U2.5 | Brier | 0.5068 | 0.5105 | -0.0037 (BASELINE meglio) |
| O/U2.5 | LogLoss | 0.7005 | 0.7045 | -0.0040 (BASELINE meglio) |
| GG/NG | Brier | 0.5017 | 0.5033 | -0.0016 (BASELINE meglio) |
| GG/NG | LogLoss | 0.6951 | 0.6968 | -0.0018 (BASELINE meglio) |

## PREMIER LEAGUE  (N=760 val+test, refit MLE=20)

| Mercato | Metrica | BASELINE | MLE | Delta (base-MLE) |
|---|---|---|---|---|
| 1X2 | Brier | 0.6082 | 0.6077 | +0.0005 (MLE meglio) |
| 1X2 | LogLoss | 1.0139 | 1.0129 | +0.0009 (MLE meglio) |
| O/U2.5 | Brier | 0.4907 | 0.4896 | +0.0011 (MLE meglio) |
| O/U2.5 | LogLoss | 0.6843 | 0.6831 | +0.0012 (MLE meglio) |
| GG/NG | Brier | 0.4933 | 0.4902 | +0.0031 (MLE meglio) |
| GG/NG | LogLoss | 0.6865 | 0.6833 | +0.0033 (MLE meglio) |

## LA LIGA  (N=760 val+test, refit MLE=20)

| Mercato | Metrica | BASELINE | MLE | Delta (base-MLE) |
|---|---|---|---|---|
| 1X2 | Brier | 0.5816 | 0.5811 | +0.0005 (MLE meglio) |
| 1X2 | LogLoss | 1.0127 | 0.9788 | +0.0339 (MLE meglio) |
| O/U2.5 | Brier | 0.4961 | 0.4950 | +0.0011 (MLE meglio) |
| O/U2.5 | LogLoss | 0.6892 | 0.6883 | +0.0009 (MLE meglio) |
| GG/NG | Brier | 0.5088 | 0.5081 | +0.0007 (MLE meglio) |
| GG/NG | LogLoss | 0.7026 | 0.7019 | +0.0006 (MLE meglio) |

## BUNDESLIGA  (N=612 val+test, refit MLE=20)

| Mercato | Metrica | BASELINE | MLE | Delta (base-MLE) |
|---|---|---|---|---|
| 1X2 | Brier | 0.5958 | 0.5965 | -0.0007 (BASELINE meglio) |
| 1X2 | LogLoss | 1.0431 | 1.0144 | +0.0287 (MLE meglio) |
| O/U2.5 | Brier | 0.4655 | 0.4621 | +0.0034 (MLE meglio) |
| O/U2.5 | LogLoss | 0.6569 | 0.6543 | +0.0026 (MLE meglio) |
| GG/NG | Brier | 0.4871 | 0.4868 | +0.0003 (MLE meglio) |
| GG/NG | LogLoss | 0.7625 | 0.6888 | +0.0737 (MLE meglio) |

## LIGUE 1  (N=612 val+test, refit MLE=20)

| Mercato | Metrica | BASELINE | MLE | Delta (base-MLE) |
|---|---|---|---|---|
| 1X2 | Brier | 0.5933 | 0.5950 | -0.0018 (BASELINE meglio) |
| 1X2 | LogLoss | 1.0342 | 1.0043 | +0.0299 (MLE meglio) |
| O/U2.5 | Brier | 0.4962 | 0.4961 | +0.0001 (MLE meglio) |
| O/U2.5 | LogLoss | 0.6898 | 0.6901 | -0.0003 (BASELINE meglio) |
| GG/NG | Brier | 0.5002 | 0.5016 | -0.0014 (BASELINE meglio) |
| GG/NG | LogLoss | 0.6931 | 0.6996 | -0.0065 (BASELINE meglio) |

## AGGREGATO — 5 LEGHE  (N=3504 val+test)

| Mercato | Metrica | BASELINE | MLE | Delta (base-MLE) |
|---|---|---|---|---|
| 1X2 | Brier | 0.5934 | 0.5938 | -0.0004 (BASELINE meglio) |
| 1X2 | LogLoss | 1.0162 | 0.9988 | +0.0174 (MLE meglio) |
| O/U2.5 | Brier | 0.4919 | 0.4916 | +0.0003 (MLE meglio) |
| O/U2.5 | LogLoss | 0.6851 | 0.6851 | +0.0000 (MLE meglio) |
| GG/NG | Brier | 0.4986 | 0.4983 | +0.0003 (MLE meglio) |
| GG/NG | LogLoss | 0.7063 | 0.6941 | +0.0122 (MLE meglio) |

## Sintesi

- Celle metrica per-lega confrontate: **30** (5 leghe x 3 mercati x 2 metriche).
- Celle in cui la MLE batte la BASELINE: **19/30**.
- Nell'aggregato la MLE vince su **5/6** celle (3 mercati x 2 metriche).

**Lettura.** La MLE congiunta e' teoricamente piu' corretta dell'euristica (stima i parametri massimizzando la verosimiglianza del modello effettivamente usato per predire), ma e' molto piu' costosa (refit di 2*n_squadre+1 parametri a ogni mese). Il confronto qui misura se il guadagno predittivo out-of-sample giustifica il costo: delta vicini a zero indicano che l'euristica, molto piu' leggera, e' gia' competitiva; delta sistematicamente positivi indicano un vantaggio reale della MLE.

## Note

- Entrambe le varianti: rho = 0 (nessuna correzione DC celle basse), cosi' il delta isola solo l'effetto della stima attack/defence.
- MLE: vincolo media(attack)=0 imposto per ricentraggio nella funzione obiettivo (rimuove l'unica ridondanza del modello). Squadre neopromosse non presenti nel training del mese: attack=defence=0 (forza media di lega), home_adv comunque applicato.
- Refit mensile a finestra espansiva: nessun dato con `Date >= inizio mese` entra nel training di quel mese (no-leakage).
- Import in sola lettura da `backtest_experiment_all.py` (`load_league`, `LEAGUES`) e da `diagnose_dixon_coles_rho.py` (`run_walkforward_lambda`, `build_matrix`, `market_probs_from_matrix`, `brier_logloss`). Nessun file di SoccerMath/ modificato.

