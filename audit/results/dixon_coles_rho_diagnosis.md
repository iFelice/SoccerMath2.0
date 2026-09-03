# Diagnosi rho Dixon-Coles (tau su 4 celle basse)

Stima MLE di rho su training 2022/23+2023/24 (solo dati di training, lambda walk-forward no-leakage). Applicazione su VALIDATION 2024/25 + TEST 2025/26. Baseline RHO_ZERO = rho 0 (Poisson puro).

## Valori di rho stimati

| Variante | Lega | rho |
|---|---|---|
| RHO_ZERO | tutte | 0.0000 |
| RHO_GLOBALE | pooled 5 leghe | -0.0470 |
| RHO_LEGA | Serie A | -0.0458 |
| RHO_LEGA | Premier League | 0.0092 |
| RHO_LEGA | La Liga | 0.0064 |
| RHO_LEGA | Bundesliga | -0.1159 |
| RHO_LEGA | Ligue 1 | -0.0882 |


## SERIE A  (N=760 val+test)

| Mercato | metrica | RHO_ZERO | RHO_GLOBALE | RHO_LEGA |
|---|---|---|---|---|
| 1X2 | Brier | 0.5884 | 0.5877 | 0.5877 |
| 1X2 | LogLoss | 0.9858 | 0.9844 | 0.9844 |
| O/U2.5 | Brier | 0.5068 | 0.5068 | 0.5068 |
| O/U2.5 | LogLoss | 0.7005 | 0.7005 | 0.7005 |
| GG/NG | Brier | 0.5017 | 0.5014 | 0.5014 |
| GG/NG | LogLoss | 0.6951 | 0.6947 | 0.6947 |
| Risultato esatto | Brier | 0.7522 | 0.7521 | 0.7521 |
| Risultato esatto | LogLoss | 1.6611 | 1.6604 | 1.6604 |
_(top-6 punteggi esatti: 1-1, 1-0, 0-1, 2-1, 0-0, 1-2)_


## PREMIER LEAGUE  (N=760 val+test)

| Mercato | metrica | RHO_ZERO | RHO_GLOBALE | RHO_LEGA |
|---|---|---|---|---|
| 1X2 | Brier | 0.6082 | 0.6074 | 0.6084 |
| 1X2 | LogLoss | 1.0139 | 1.0125 | 1.0142 |
| O/U2.5 | Brier | 0.4907 | 0.4907 | 0.4907 |
| O/U2.5 | LogLoss | 0.6843 | 0.6843 | 0.6843 |
| GG/NG | Brier | 0.4933 | 0.4928 | 0.4934 |
| GG/NG | LogLoss | 0.6865 | 0.6860 | 0.6867 |
| Risultato esatto | Brier | 0.7116 | 0.7116 | 0.7116 |
| Risultato esatto | LogLoss | 1.5827 | 1.5814 | 1.5831 |
_(top-6 punteggi esatti: 1-1, 2-1, 0-1, 2-2, 1-2, 1-0)_


## LA LIGA  (N=760 val+test)

| Mercato | metrica | RHO_ZERO | RHO_GLOBALE | RHO_LEGA |
|---|---|---|---|---|
| 1X2 | Brier | 0.5816 | 0.5815 | 0.5816 |
| 1X2 | LogLoss | 1.0127 | 1.0127 | 1.0127 |
| O/U2.5 | Brier | 0.4961 | 0.4961 | 0.4961 |
| O/U2.5 | LogLoss | 0.6892 | 0.6892 | 0.6892 |
| GG/NG | Brier | 0.5088 | 0.5069 | 0.5090 |
| GG/NG | LogLoss | 0.7026 | 0.7007 | 0.7029 |
| Risultato esatto | Brier | 0.7685 | 0.7688 | 0.7684 |
| Risultato esatto | LogLoss | 1.7305 | 1.7297 | 1.7307 |
_(top-6 punteggi esatti: 1-1, 1-0, 2-1, 1-2, 0-1, 2-0)_


## BUNDESLIGA  (N=612 val+test)

| Mercato | metrica | RHO_ZERO | RHO_GLOBALE | RHO_LEGA |
|---|---|---|---|---|
| 1X2 | Brier | 0.5958 | 0.5951 | 0.5947 |
| 1X2 | LogLoss | 1.0431 | 1.0420 | 1.0414 |
| O/U2.5 | Brier | 0.4655 | 0.4655 | 0.4655 |
| O/U2.5 | LogLoss | 0.6569 | 0.6569 | 0.6569 |
| GG/NG | Brier | 0.4871 | 0.4865 | 0.4858 |
| GG/NG | LogLoss | 0.7625 | 0.7619 | 0.7612 |
| Risultato esatto | Brier | 0.6320 | 0.6319 | 0.6318 |
| Risultato esatto | LogLoss | 1.5007 | 1.5001 | 1.5000 |
_(top-6 punteggi esatti: 1-1, 2-1, 1-2, 2-2, 1-0, 3-1)_


## LIGUE 1  (N=612 val+test)

| Mercato | metrica | RHO_ZERO | RHO_GLOBALE | RHO_LEGA |
|---|---|---|---|---|
| 1X2 | Brier | 0.5933 | 0.5936 | 0.5941 |
| 1X2 | LogLoss | 1.0342 | 1.0350 | 1.0362 |
| O/U2.5 | Brier | 0.4962 | 0.4962 | 0.4962 |
| O/U2.5 | LogLoss | 0.6898 | 0.6898 | 0.6898 |
| GG/NG | Brier | 0.5002 | 0.4999 | 0.4997 |
| GG/NG | LogLoss | 0.6931 | 0.6928 | 0.6926 |
| Risultato esatto | Brier | 0.6940 | 0.6940 | 0.6941 |
| Risultato esatto | LogLoss | 1.5987 | 1.5996 | 1.6013 |
_(top-6 punteggi esatti: 1-0, 1-1, 2-1, 2-0, 0-0, 3-1)_


## AGGREGATO — 5 LEGHE  (N=3504 val+test)

| Mercato | metrica | RHO_ZERO | RHO_GLOBALE |
|---|---|---|---|
| 1X2 | Brier | 0.5934 | 0.5929 |
| 1X2 | LogLoss | 1.0162 | 1.0155 |
| O/U2.5 | Brier | 0.4919 | 0.4919 |
| O/U2.5 | LogLoss | 0.6851 | 0.6851 |
| GG/NG | Brier | 0.4986 | 0.4979 |
| GG/NG | LogLoss | 0.7063 | 0.7055 |
| Risultato esatto | Brier | 0.7087 | 0.7086 |
| Risultato esatto | LogLoss | 1.5927 | 1.5918 |
_(nota: nell'aggregato RHO_LEGA coincide con RHO_GLOBALE perche' il pooling ha un unico rho; il confronto per-lega RHO_LEGA vs RHO_GLOBALE e' sopra)_
