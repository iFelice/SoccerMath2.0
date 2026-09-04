# Ensemble Poisson + Elo sulla testa 1X2

Walk-forward no-leakage, 5 leghe, VALIDATION 2024/25 + TEST 2025/26. Poisson = lambda di produzione (xG + forma + mercato, somma normalizzata). Elo = sequenziale K=24, home advantage per lega, pareggio gaussiano (stessa formula del backtest in-app). Ensemble = w*Poisson + (1-w)*Elo. In produzione (Value Bets) w = 0.6.


## SERIE A  (VAL 380 + TEST 380 partite)

| Modello | Brier V | LogLoss V | Brier T | LogLoss T |
|---|---|---|---|---|
| POISSON (prod 1X2) | 0.5748 | 0.9615 | 0.5999 | 1.0083 |
| ELO | 0.5951 | 1.0001 | 0.6008 | 1.0087 |
| ENSEMBLE w=0.5 | 0.5770 | 0.9695 | 0.5920 | 0.9931 |
| ENSEMBLE w=0.6 | 0.5753 | 0.9659 | 0.5923 | 0.9932 |
| ENSEMBLE w=0.7 | 0.5742 | 0.9632 | 0.5932 | 0.9945 |
| ENSEMBLE w=0.8 | 0.5738 | 0.9615 | 0.5948 | 0.9972 |
| ENSEMBLE w=0.9 | 0.5740 | 0.9608 | 0.5970 | 1.0016 |

## PREMIER LEAGUE  (VAL 380 + TEST 380 partite)

| Modello | Brier V | LogLoss V | Brier T | LogLoss T |
|---|---|---|---|---|
| POISSON (prod 1X2) | 0.5830 | 0.9798 | 0.6232 | 1.0336 |
| ELO | 0.5928 | 0.9953 | 0.6173 | 1.0305 |
| ENSEMBLE w=0.5 | 0.5785 | 0.9719 | 0.6146 | 1.0234 |
| ENSEMBLE w=0.6 | 0.5779 | 0.9705 | 0.6155 | 1.0239 |
| ENSEMBLE w=0.7 | 0.5781 | 0.9703 | 0.6167 | 1.0252 |
| ENSEMBLE w=0.8 | 0.5790 | 0.9716 | 0.6184 | 1.0272 |
| ENSEMBLE w=0.9 | 0.5806 | 0.9746 | 0.6206 | 1.0300 |

## LA LIGA  (VAL 380 + TEST 380 partite)

| Modello | Brier V | LogLoss V | Brier T | LogLoss T |
|---|---|---|---|---|
| POISSON (prod 1X2) | 0.5650 | 0.9590 | 0.5923 | 1.0010 |
| ELO | 0.5818 | 0.9799 | 0.5832 | 0.9811 |
| ENSEMBLE w=0.5 | 0.5640 | 0.9516 | 0.5801 | 0.9759 |
| ENSEMBLE w=0.6 | 0.5627 | 0.9491 | 0.5813 | 0.9779 |
| ENSEMBLE w=0.7 | 0.5621 | 0.9480 | 0.5832 | 0.9812 |
| ENSEMBLE w=0.8 | 0.5623 | 0.9485 | 0.5856 | 0.9859 |
| ENSEMBLE w=0.9 | 0.5633 | 0.9514 | 0.5887 | 0.9923 |

## BUNDESLIGA  (VAL 306 + TEST 306 partite)

| Modello | Brier V | LogLoss V | Brier T | LogLoss T |
|---|---|---|---|---|
| POISSON (prod 1X2) | 0.6160 | 1.0327 | 0.5719 | 0.9708 |
| ELO | 0.6212 | 1.0360 | 0.5777 | 0.9768 |
| ENSEMBLE w=0.5 | 0.6072 | 1.0147 | 0.5670 | 0.9612 |
| ENSEMBLE w=0.6 | 0.6071 | 1.0144 | 0.5668 | 0.9607 |
| ENSEMBLE w=0.7 | 0.6080 | 1.0157 | 0.5671 | 0.9612 |
| ENSEMBLE w=0.8 | 0.6098 | 1.0186 | 0.5681 | 0.9628 |
| ENSEMBLE w=0.9 | 0.6124 | 1.0238 | 0.5697 | 0.9658 |

## LIGUE 1  (VAL 306 + TEST 306 partite)

| Modello | Brier V | LogLoss V | Brier T | LogLoss T |
|---|---|---|---|---|
| POISSON (prod 1X2) | 0.5668 | 0.9658 | 0.5990 | 1.0019 |
| ELO | 0.5801 | 0.9789 | 0.5945 | 0.9973 |
| ENSEMBLE w=0.5 | 0.5599 | 0.9500 | 0.5892 | 0.9865 |
| ENSEMBLE w=0.6 | 0.5591 | 0.9490 | 0.5900 | 0.9870 |
| ENSEMBLE w=0.7 | 0.5594 | 0.9496 | 0.5913 | 0.9887 |
| ENSEMBLE w=0.8 | 0.5608 | 0.9523 | 0.5933 | 0.9915 |
| ENSEMBLE w=0.9 | 0.5633 | 0.9575 | 0.5958 | 0.9958 |

## AGGREGATO  (VAL 1752 + TEST 1752 partite)

| Modello | Brier V | LogLoss V | Brier T | LogLoss T |
|---|---|---|---|---|
| POISSON (prod 1X2) | 0.5803 | 0.9781 | 0.5983 | 1.0045 |
| ELO | 0.5937 | 0.9972 | 0.5954 | 0.9999 |
| ENSEMBLE w=0.5 | 0.5768 | 0.9706 | 0.5895 | 0.9892 |
| ENSEMBLE w=0.6 | 0.5759 | 0.9688 | 0.5901 | 0.9898 |
| ENSEMBLE w=0.7 | 0.5757 | 0.9683 | 0.5912 | 0.9914 |
| ENSEMBLE w=0.8 | 0.5764 | 0.9693 | 0.5930 | 0.9943 |
| ENSEMBLE w=0.9 | 0.5779 | 0.9722 | 0.5953 | 0.9985 |

## Sintesi

Miglior Brier 1X2 per (lega x stagione), su 10 casi:

- POISSON (prod 1X2): 0
- ELO: 0
- ENSEMBLE w=0.5: 4
- ENSEMBLE w=0.6: 4
- ENSEMBLE w=0.7: 1
- ENSEMBLE w=0.8: 1
- ENSEMBLE w=0.9: 0

Classifica aggregata (Brier 1X2, V+T, 5 leghe):

1. ENSEMBLE w=0.6: Brier 0.5830 | LogLoss 0.9793
2. ENSEMBLE w=0.5: Brier 0.5832 | LogLoss 0.9799
3. ENSEMBLE w=0.7: Brier 0.5835 | LogLoss 0.9798
4. ENSEMBLE w=0.8: Brier 0.5847 | LogLoss 0.9818
5. ENSEMBLE w=0.9: Brier 0.5866 | LogLoss 0.9853
6. POISSON (prod 1X2): Brier 0.5893 | LogLoss 0.9913
7. ELO: Brier 0.5946 | LogLoss 0.9986
