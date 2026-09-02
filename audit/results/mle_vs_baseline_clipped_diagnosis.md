# MLE vs baseline euristica — effetto del clip sui lambda

Stessa architettura di `diagnose_mle_attack_defence.py` (walk-forward MLE con refit mensile, rho = 0 per tutte le varianti, valutazione VALIDATION 2024/25 + TEST 2025/26, 5 leghe, stessa costruzione delle celle). Funzioni MLE/valutazione importate in sola lettura da quello script.

**Unica modifica:** una variante della baseline applica ai lambda euristici lo STESSO clip usato in `mle_lambdas()` PRIMA di costruire la matrice: `lam = clip(lam, exp(-6), exp(3))` = `clip(lam, 0.002479, 20.0855)`. Tutto il resto della logica baseline (team_attr, avg_h/avg_a) e' identico.

Tre varianti:

1. **BASELINE_NOCLIP** — euristica originale, senza clip (riferimento).
2. **BASELINE_CLIPPED** — stessa euristica, con clip `[exp(-6), exp(3)]` sui lambda.
3. **MLE** — stima congiunta attacco/difesa, identica allo script precedente.

Metriche: Brier Score e Log Loss su 1X2, O/U2.5, GG/NG. Valori piu' bassi = migliore.

## Clip attivati (BASELINE_NOCLIP)

Numero di partite di validation+test in cui almeno uno tra `lambda_home`/`lambda_away` prodotto dall'euristica usciva dal range `[exp(-6), exp(3)]` = `[0.002479, 20.0855]` (cioe' dove il clip interviene davvero).

| Lega | N partite | Clip attivati | % |
|---|---:|---:|---:|
| Serie A | 760 | 0 | 0.00% |
| Premier League | 760 | 0 | 0.00% |
| La Liga | 760 | 1 | 0.13% |
| Bundesliga | 612 | 3 | 0.49% |
| Ligue 1 | 612 | 2 | 0.33% |
| **TOTALE 5 leghe** | 3504 | 6 | 0.17% |

## Costo computazionale

| Voce | Valore |
|---|---|
| Tempo totale esecuzione | 47.5 s |
| Numero totale di refit MLE eseguiti | 100 |

## SERIE A  (N=760 val+test, refit MLE=20, clip attivati=0)

| Mercato | Metrica | BASELINE_NOCLIP | BASELINE_CLIPPED | MLE | Migliore |
|---|---|---|---|---|---|
| 1X2 | Brier | 0.5884 | 0.5884 | 0.5893 | BASELINE_NOCLIP |
| 1X2 | LogLoss | 0.9858 | 0.9858 | 0.9878 | BASELINE_NOCLIP |
| O/U2.5 | Brier | 0.5068 | 0.5068 | 0.5105 | BASELINE_NOCLIP |
| O/U2.5 | LogLoss | 0.7005 | 0.7005 | 0.7045 | BASELINE_NOCLIP |
| GG/NG | Brier | 0.5017 | 0.5017 | 0.5033 | BASELINE_NOCLIP |
| GG/NG | LogLoss | 0.6951 | 0.6951 | 0.6968 | BASELINE_NOCLIP |

## PREMIER LEAGUE  (N=760 val+test, refit MLE=20, clip attivati=0)

| Mercato | Metrica | BASELINE_NOCLIP | BASELINE_CLIPPED | MLE | Migliore |
|---|---|---|---|---|---|
| 1X2 | Brier | 0.6082 | 0.6082 | 0.6077 | MLE |
| 1X2 | LogLoss | 1.0139 | 1.0139 | 1.0129 | MLE |
| O/U2.5 | Brier | 0.4907 | 0.4907 | 0.4896 | MLE |
| O/U2.5 | LogLoss | 0.6843 | 0.6843 | 0.6831 | MLE |
| GG/NG | Brier | 0.4933 | 0.4933 | 0.4902 | MLE |
| GG/NG | LogLoss | 0.6865 | 0.6865 | 0.6833 | MLE |

## LA LIGA  (N=760 val+test, refit MLE=20, clip attivati=1)

| Mercato | Metrica | BASELINE_NOCLIP | BASELINE_CLIPPED | MLE | Migliore |
|---|---|---|---|---|---|
| 1X2 | Brier | 0.5816 | 0.5816 | 0.5811 | MLE |
| 1X2 | LogLoss | 1.0127 | 0.9870 | 0.9788 | MLE |
| O/U2.5 | Brier | 0.4961 | 0.4961 | 0.4950 | MLE |
| O/U2.5 | LogLoss | 0.6892 | 0.6892 | 0.6883 | MLE |
| GG/NG | Brier | 0.5088 | 0.5088 | 0.5081 | MLE |
| GG/NG | LogLoss | 0.7026 | 0.7026 | 0.7019 | MLE |

## BUNDESLIGA  (N=612 val+test, refit MLE=20, clip attivati=3)

| Mercato | Metrica | BASELINE_NOCLIP | BASELINE_CLIPPED | MLE | Migliore |
|---|---|---|---|---|---|
| 1X2 | Brier | 0.5958 | 0.5958 | 0.5965 | BASELINE_CLIPPED |
| 1X2 | LogLoss | 1.0431 | 1.0103 | 1.0144 | BASELINE_CLIPPED |
| O/U2.5 | Brier | 0.4655 | 0.4655 | 0.4621 | MLE |
| O/U2.5 | LogLoss | 0.6569 | 0.6569 | 0.6543 | MLE |
| GG/NG | Brier | 0.4871 | 0.4871 | 0.4868 | MLE |
| GG/NG | LogLoss | 0.7625 | 0.6926 | 0.6888 | MLE |

## LIGUE 1  (N=612 val+test, refit MLE=20, clip attivati=2)

| Mercato | Metrica | BASELINE_NOCLIP | BASELINE_CLIPPED | MLE | Migliore |
|---|---|---|---|---|---|
| 1X2 | Brier | 0.5933 | 0.5933 | 0.5950 | BASELINE_CLIPPED |
| 1X2 | LogLoss | 1.0342 | 1.0028 | 1.0043 | BASELINE_CLIPPED |
| O/U2.5 | Brier | 0.4962 | 0.4962 | 0.4961 | MLE |
| O/U2.5 | LogLoss | 0.6898 | 0.6898 | 0.6901 | BASELINE_CLIPPED |
| GG/NG | Brier | 0.5002 | 0.5002 | 0.5016 | BASELINE_NOCLIP |
| GG/NG | LogLoss | 0.6931 | 0.6931 | 0.6996 | BASELINE_NOCLIP |

## AGGREGATO — 5 LEGHE  (N=3504 val+test)

| Mercato | Metrica | BASELINE_NOCLIP | BASELINE_CLIPPED | MLE | Migliore |
|---|---|---|---|---|---|
| 1X2 | Brier | 0.5934 | 0.5934 | 0.5938 | BASELINE_CLIPPED |
| 1X2 | LogLoss | 1.0162 | 0.9994 | 0.9988 | MLE |
| O/U2.5 | Brier | 0.4919 | 0.4919 | 0.4916 | MLE |
| O/U2.5 | LogLoss | 0.6851 | 0.6851 | 0.6851 | BASELINE_CLIPPED |
| GG/NG | Brier | 0.4986 | 0.4986 | 0.4983 | MLE |
| GG/NG | LogLoss | 0.7063 | 0.6941 | 0.6941 | BASELINE_CLIPPED |

## Sintesi

- Clip attivati in totale: **6/3504** partite (0.17%).
- Celle metrica per-lega: **30** (5 leghe x 3 mercati x 2 metriche).
- Celle in cui il clip cambia il risultato (NOCLIP != CLIPPED): **18/30**; di queste, il clip **migliora** in **12**.
- Celle in cui la MLE resta la migliore delle tre: **17/30**.

**Lettura.** Se BASELINE_CLIPPED recupera gran parte del divario di LogLoss verso la MLE, allora il vantaggio della MLE osservato nello script precedente era in buona parte dovuto ai lambda estremi mal calibrati dell'euristica (che il clip taglia), non a una stima attack/defence intrinsecamente migliore. Il numero di clip attivati quantifica quanto spesso il fenomeno si presenta.

## Note

- rho = 0 per tutte e tre le varianti (nessuna correzione DC celle basse): il confronto isola stima dei lambda + clip.
- Bound del clip identici a `mle_lambdas()`: log-spazio [-6.0, 3.0] => lineare [0.002479, 20.0855].
- Il conteggio dei clip e' calcolato sui lambda pre-clip dell'euristica (BASELINE_NOCLIP), indipendentemente dalla variante.
- Import in sola lettura da `backtest_experiment_all.py`, `diagnose_dixon_coles_rho.py` e `diagnose_mle_attack_defence.py`. Nessun file di SoccerMath/ modificato.

