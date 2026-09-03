# Diagnosi time-decay (peso temporale Dixon-Coles) — effetto isolato

Peso phi(t)=exp(-xi*giorni) sulle medie att/def per squadra. xi stimato con MLE (Poisson sui gol reali) SOLO su training 2022/23+2023/24. Tutte le metriche applicano lo stesso rho Dixon-Coles pooling fisso RHO=-0.0470 (da diagnose_dixon_coles_rho.py), cosi' il confronto isola il solo effetto del time-decay.

## Valori di xi stimati

| Variante | xi | emivita (ln2/xi) |
|---|---|---|
| XI_ZERO | 0 | inf |
| XI_GLOBALE (pooled) | 0.002127 | 326 gg |
| XI_LEGA (Serie A) | 0.001270 | 546 gg |
| XI_LEGA (Premier League) | 0.003372 | 206 gg |
| XI_LEGA (La Liga) | 0.001733 | 400 gg |
| XI_LEGA (Bundesliga) | 0.002545 | 272 gg |
| XI_LEGA (Ligue 1) | 0.001064 | 651 gg |


## SERIE A  (N=760 val+test)

| Mercato | metrica | XI_ZERO | XI_GLOBALE | XI_LEGA |
|---|---|---|---|---|
| 1X2 | Brier | 0.5877 | 0.5896 | 0.5887 |
| 1X2 | LogLoss | 0.9844 | 0.9875 | 0.9859 |
| O/U2.5 | Brier | 0.5068 | 0.5105 | 0.5087 |
| O/U2.5 | LogLoss | 0.7005 | 0.7047 | 0.7026 |
| GG/NG | Brier | 0.5014 | 0.5048 | 0.5031 |
| GG/NG | LogLoss | 0.6947 | 0.6982 | 0.6965 |


## PREMIER LEAGUE  (N=760 val+test)

| Mercato | metrica | XI_ZERO | XI_GLOBALE | XI_LEGA |
|---|---|---|---|---|
| 1X2 | Brier | 0.6074 | 0.6015 | 0.6011 |
| 1X2 | LogLoss | 1.0125 | 1.0038 | 1.0034 |
| O/U2.5 | Brier | 0.4907 | 0.4970 | 0.5034 |
| O/U2.5 | LogLoss | 0.6843 | 0.6908 | 0.6974 |
| GG/NG | Brier | 0.4928 | 0.4961 | 0.4994 |
| GG/NG | LogLoss | 0.6860 | 0.6895 | 0.6930 |


## LA LIGA  (N=760 val+test)

| Mercato | metrica | XI_ZERO | XI_GLOBALE | XI_LEGA |
|---|---|---|---|---|
| 1X2 | Brier | 0.5815 | 0.5809 | 0.5807 |
| 1X2 | LogLoss | 1.0127 | 1.0120 | 1.0117 |
| O/U2.5 | Brier | 0.4961 | 0.4915 | 0.4918 |
| O/U2.5 | LogLoss | 0.6892 | 0.6843 | 0.6846 |
| GG/NG | Brier | 0.5069 | 0.5010 | 0.5014 |
| GG/NG | LogLoss | 0.7007 | 0.6945 | 0.6950 |


## BUNDESLIGA  (N=612 val+test)

| Mercato | metrica | XI_ZERO | XI_GLOBALE | XI_LEGA |
|---|---|---|---|---|
| 1X2 | Brier | 0.5951 | 0.5994 | 0.6004 |
| 1X2 | LogLoss | 1.0420 | 1.0491 | 1.0509 |
| O/U2.5 | Brier | 0.4655 | 0.4690 | 0.4701 |
| O/U2.5 | LogLoss | 0.6569 | 0.6610 | 0.6622 |
| GG/NG | Brier | 0.4865 | 0.4872 | 0.4875 |
| GG/NG | LogLoss | 0.7619 | 0.7627 | 0.7630 |


## LIGUE 1  (N=612 val+test)

| Mercato | metrica | XI_ZERO | XI_GLOBALE | XI_LEGA |
|---|---|---|---|---|
| 1X2 | Brier | 0.5936 | 0.5912 | 0.5919 |
| 1X2 | LogLoss | 1.0350 | 1.0313 | 1.0324 |
| O/U2.5 | Brier | 0.4962 | 0.4956 | 0.4951 |
| O/U2.5 | LogLoss | 0.6898 | 0.6896 | 0.6888 |
| GG/NG | Brier | 0.4999 | 0.5026 | 0.5008 |
| GG/NG | LogLoss | 0.6928 | 0.6957 | 0.6938 |


## AGGREGATO — 5 LEGHE  (N=3504 val+test)

| Mercato | metrica | XI_ZERO | XI_GLOBALE |
|---|---|---|---|
| 1X2 | Brier | 0.5929 | 0.5923 |
| 1X2 | LogLoss | 1.0155 | 1.0147 |
| O/U2.5 | Brier | 0.4919 | 0.4936 |
| O/U2.5 | LogLoss | 0.6851 | 0.6870 |
| GG/NG | Brier | 0.4979 | 0.4986 |
| GG/NG | LogLoss | 0.7055 | 0.7063 |
_(nell'aggregato XI_LEGA coincide con XI_GLOBALE: un solo xi pooled; il confronto per-lega XI_LEGA vs XI_GLOBALE e' sopra)_
