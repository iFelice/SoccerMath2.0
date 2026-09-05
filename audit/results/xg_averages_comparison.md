# Confronto medie xG: file di riferimento vs derivate dall'archivio

Stagione derivata: **2026** (anno di inizio). Le medie derivate usano solo partite concluse con entrambi gli xG numerici, finiti e non negativi; nessuno shrinkage (resta in `get_league_engine`, PRIOR_MATCHES=6).

Riferimento ("attuale"): file `xg_<lega>.json` committati in `origin/main`, cioe' lo stato precedente al consolidamento.

## Serie A

- riferimento: `origin/main:SoccerMath/database/xg_serie_a.json`
- squadre nel file di riferimento: **27** (campo `matches` presente: 0)
- squadre derivate dall'archivio 2026: **20** (partite valide usate: 20 su 380 in calendario)
- presenti in entrambi: **20**; solo nel riferimento: **7**; solo derivate: **0**
- solo nel riferimento: `Cremonese`, `Empoli`, `Pisa`, `Salernitana`, `Sampdoria`, `Spezia`, `Verona`

| Squadra | xG rif. | xG derivato | Δ xG | xGA rif. | xGA derivato | Δ xGA | matches derivati |
|---|---|---|---|---|---|---|---|
| Atalanta | 1.61 | 0.55 | -1.060 | 1.04 | 1.968 | +0.928 | 2 |
| Bologna | 1.304 | 1.65 | +0.346 | 1.043 | 0.491 | -0.552 | 2 |
| Cagliari | 0.959 | 0.79 | -0.169 | 1.314 | 2.501 | +1.187 | 2 |
| Como | 1.264 | 1.742 | +0.478 | 1.039 | 1.577 | +0.538 | 2 |
| Fiorentina | 1.343 | 1.052 | -0.291 | 1.079 | 2.864 | +1.785 | 2 |
| Frosinone | 1.237 | 1.159 | -0.078 | 1.703 | 2.217 | +0.514 | 2 |
| Genoa | 0.944 | 0.622 | -0.322 | 1.159 | 1.635 | +0.476 | 2 |
| Inter | 1.826 | 2.755 | +0.929 | 0.883 | 0.77 | -0.113 | 2 |
| Juventus | 1.387 | 2.22 | +0.833 | 0.866 | 0.283 | -0.583 | 2 |
| Lazio | 1.337 | 1.459 | +0.122 | 1.008 | 1.404 | +0.396 | 2 |
| Lecce | 0.813 | 1.828 | +1.015 | 1.317 | 3.665 | +2.348 | 2 |
| Milan | 1.53 | 2.48 | +0.950 | 1.062 | 0.826 | -0.236 | 2 |
| Monza | 0.97 | 1.557 | +0.587 | 1.57 | 1.281 | -0.289 | 2 |
| Napoli | 1.477 | 1.095 | -0.382 | 0.815 | 0.799 | -0.016 | 2 |
| Parma | 0.943 | 0.615 | -0.328 | 1.225 | 1.54 | +0.315 | 2 |
| Roma | 1.356 | 3.956 | +2.600 | 0.972 | 0.745 | -0.227 | 2 |
| Sassuolo | 1.078 | 2.123 | +1.045 | 1.337 | 1.212 | -0.125 | 2 |
| Torino | 0.987 | 1.316 | +0.329 | 1.162 | 1.643 | +0.481 | 2 |
| Udinese | 1.056 | 1.572 | +0.516 | 1.251 | 2.142 | +0.891 | 2 |
| Venezia | 0.943 | 1.858 | +0.915 | 1.517 | 2.835 | +1.318 | 2 |

Scostamento medio assoluto: xG 0.665, xGA 0.666.

## Premier League

- riferimento: `origin/main:SoccerMath/database/xg_premier_league.json`
- squadre nel file di riferimento: **27** (campo `matches` presente: 0)
- squadre derivate dall'archivio 2026: **20** (partite valide usate: 20 su 380 in calendario)
- presenti in entrambi: **18**; solo nel riferimento: **9**; solo derivate: **2**
- solo nel riferimento: `Brighton Hove`, `Burnley`, `Leeds United`, `Leicester`, `Nottingham`, `Southampton`, `West Ham`, `Wolverhampton`, `Wolves`
- solo derivate: `Coventry City`, `Hull City`

| Squadra | xG rif. | xG derivato | Δ xG | xGA rif. | xGA derivato | Δ xGA | matches derivati |
|---|---|---|---|---|---|---|---|
| Arsenal | 1.47 | 1.689 | +0.219 | 0.676 | 0.42 | -0.256 | 2 |
| Aston Villa | 1.239 | 0.279 | -0.960 | 1.077 | 2.764 | +1.687 | 2 |
| Bournemouth | 1.276 | 1.483 | +0.207 | 1.075 | 2.069 | +0.994 | 2 |
| Brentford | 1.263 | 2.827 | +1.564 | 1.222 | 0.953 | -0.269 | 2 |
| Brighton | 1.603 | 2.897 | +1.294 | 1.401 | 2.052 | +0.651 | 2 |
| Chelsea | 1.354 | 3.206 | +1.852 | 1.025 | 1.604 | +0.579 | 2 |
| Crystal Palace | 1.038 | 1.579 | +0.541 | 1.071 | 2.009 | +0.938 | 2 |
| Everton | 0.985 | 1.557 | +0.572 | 1.02 | 2.244 | +1.224 | 2 |
| Fulham | 1.098 | 1.221 | +0.123 | 1.072 | 2.073 | +1.001 | 2 |
| Ipswich | 0.996 | 1.695 | +0.699 | 2.022 | 3.022 | +1.000 | 2 |
| Leeds | 1.353 | 0.808 | -0.545 | 1.587 | 1.135 | -0.452 | 2 |
| Liverpool | 1.557 | 2.205 | +0.648 | 1.001 | 2.237 | +1.236 | 2 |
| Man City | 1.571 | 2.521 | +0.950 | 0.868 | 0.817 | -0.051 | 2 |
| Man United | 1.255 | 3.322 | +2.067 | 1.089 | 1.651 | +0.562 | 2 |
| Newcastle | 1.272 | 1.302 | +0.030 | 1.085 | 2.126 | +1.041 | 2 |
| Nott'm Forest | 1.348 | 1.768 | +0.420 | 1.393 | 0.873 | -0.520 | 2 |
| Sunderland | 0.7 | 1.37 | +0.670 | 0.758 | 1.304 | +0.546 | 2 |
| Tottenham | 1.19 | 0.938 | -0.252 | 1.292 | 2.526 | +1.234 | 2 |

Scostamento medio assoluto: xG 0.756, xGA 0.791.

## La Liga

- riferimento: `origin/main:SoccerMath/database/xg_la_liga.json`
- squadre nel file di riferimento: **32** (campo `matches` presente: 0)
- squadre derivate dall'archivio 2026: **20** (partite valide usate: 31 su 380 in calendario)
- presenti in entrambi: **18**; solo nel riferimento: **14**; solo derivate: **2**
- solo nel riferimento: `Alavés`, `Athletic`, `Atleti`, `Barça`, `Espanyol`, `Girona`, `Las Palmas`, `Leganes`, `Mallorca`, `Oviedo`, `Rayo Vallecano`, `Real Oviedo`, `Real Sociedad`, `Valladolid`
- solo derivate: `Deportivo`, `Málaga`

| Squadra | xG rif. | xG derivato | Δ xG | xGA rif. | xGA derivato | Δ xGA | matches derivati |
|---|---|---|---|---|---|---|---|
| Alaves | 1.022 | 1.807 | +0.785 | 1.232 | 0.759 | -0.473 | 3 |
| Ath Bilbao | 1.271 | 1.607 | +0.336 | 0.993 | 2.028 | +1.035 | 3 |
| Ath Madrid | 1.718 | 1.187 | -0.531 | 0.89 | 1.617 | +0.727 | 3 |
| Barcelona | 2.512 | 3.709 | +1.197 | 1.028 | 0.822 | -0.206 | 3 |
| Betis | 1.314 | 1.528 | +0.214 | 1.08 | 1.823 | +0.743 | 3 |
| Celta | 1.166 | 0.619 | -0.547 | 1.079 | 1.618 | +0.539 | 4 |
| Elche | 0.843 | 1.28 | +0.437 | 0.978 | 2.385 | +1.407 | 3 |
| Espanol | 1.094 | 1.32 | +0.226 | 1.369 | 1.891 | +0.522 | 3 |
| Getafe | 0.724 | 0.778 | +0.054 | 0.908 | 1.72 | +0.812 | 3 |
| Levante | 0.795 | 1.501 | +0.706 | 1.154 | 1.608 | +0.454 | 3 |
| Osasuna | 0.949 | 1.498 | +0.549 | 1.15 | 0.822 | -0.328 | 3 |
| Real Madrid | 1.711 | 3.091 | +1.380 | 0.829 | 0.747 | -0.082 | 3 |
| Santander | 2.0 | 1.898 | -0.102 | 2.0 | 0.942 | -1.058 | 3 |
| Sevilla | 1.02 | 1.355 | +0.335 | 1.187 | 1.618 | +0.431 | 3 |
| Sociedad | 1.131 | 1.385 | +0.254 | 1.242 | 1.641 | +0.399 | 4 |
| Valencia | 0.923 | 0.909 | -0.014 | 1.179 | 0.97 | -0.209 | 3 |
| Vallecano | 1.166 | 1.182 | +0.016 | 1.231 | 2.399 | +1.168 | 3 |
| Villarreal | 1.461 | 1.921 | +0.460 | 1.059 | 1.207 | +0.148 | 3 |

Scostamento medio assoluto: xG 0.452, xGA 0.597.

## Bundesliga

- riferimento: `origin/main:SoccerMath/database/xg_bundesliga.json`
- squadre nel file di riferimento: **25** (campo `matches` presente: 0)
- squadre derivate dall'archivio 2026: **18** (partite valide usate: 9 su 306 in calendario)
- presenti in entrambi: **15**; solo nel riferimento: **10**; solo derivate: **3**
- solo nel riferimento: `Bochum`, `Bremen`, `Frankfurt`, `HSV`, `Heidenheim`, `Holstein Kiel`, `Köln`, `St Pauli`, `St. Pauli`, `Wolfsburg`
- solo derivate: `Elversberg`, `SC Paderborn`, `Schalke 04`

| Squadra | xG rif. | xG derivato | Δ xG | xGA rif. | xGA derivato | Δ xGA | matches derivati |
|---|---|---|---|---|---|---|---|
| Augsburg | 0.943 | 5.536 | +4.593 | 1.3 | 1.837 | +0.537 | 1 |
| Bayern | 2.652 | 4.079 | +1.427 | 0.749 | 1.25 | +0.501 | 1 |
| Dortmund | 1.581 | 1.313 | -0.268 | 1.058 | 1.106 | +0.048 | 1 |
| Ein Frankfurt | 1.864 | 2.119 | +0.255 | 1.582 | 2.283 | +0.701 | 1 |
| Freiburg | 1.2 | 2.385 | +1.185 | 1.318 | 0.949 | -0.369 | 1 |
| Hamburg | 1.229 | 1.106 | -0.123 | 1.661 | 1.313 | -0.348 | 1 |
| Hoffenheim | 1.298 | 1.923 | +0.625 | 1.413 | 2.314 | +0.901 | 1 |
| Koln | 1.47 | 2.314 | +0.844 | 1.656 | 1.923 | +0.267 | 1 |
| Leipzig | 1.409 | 3.765 | +2.356 | 1.174 | 1.234 | +0.060 | 1 |
| Leverkusen | 1.61 | 2.615 | +1.005 | 1.083 | 1.4 | +0.317 | 1 |
| M'gladbach | 1.213 | 1.234 | +0.021 | 1.4 | 3.765 | +2.365 | 1 |
| Mainz | 1.111 | 1.549 | +0.438 | 1.178 | 0.691 | -0.487 | 1 |
| Stuttgart | 1.581 | 1.25 | -0.331 | 1.195 | 4.079 | +2.884 | 1 |
| Union Berlin | 0.946 | 2.283 | +1.337 | 1.225 | 2.119 | +0.894 | 1 |
| Werder Bremen | 1.409 | 0.949 | -0.460 | 1.732 | 2.385 | +0.653 | 1 |

Scostamento medio assoluto: xG 1.018, xGA 0.755.

## Ligue 1

- riferimento: `origin/main:SoccerMath/database/xg_ligue_1.json`
- squadre nel file di riferimento: **23** (campo `matches` presente: 0)
- squadre derivate dall'archivio 2026: **18** (partite valide usate: 19 su 306 in calendario)
- presenti in entrambi: **16**; solo nel riferimento: **7**; solo derivate: **2**
- solo nel riferimento: `Metz`, `Montpellier`, `Nantes`, `Olympique Lyon`, `Reims`, `St Etienne`, `Stade Rennais`
- solo derivate: `Le Mans`, `Troyes`

| Squadra | xG rif. | xG derivato | Δ xG | xGA rif. | xGA derivato | Δ xGA | matches derivati |
|---|---|---|---|---|---|---|---|
| Angers | 0.793 | 1.818 | +1.025 | 1.283 | 1.49 | +0.207 | 2 |
| Auxerre | 0.998 | 1.736 | +0.738 | 1.205 | 3.448 | +2.243 | 2 |
| Brest | 1.129 | 3.138 | +2.009 | 1.32 | 1.039 | -0.281 | 2 |
| Le Havre | 0.861 | 0.883 | +0.022 | 1.36 | 1.982 | +0.622 | 2 |
| Lens | 1.361 | 4.034 | +2.673 | 0.926 | 1.783 | +0.857 | 2 |
| Lille | 1.224 | 1.14 | -0.084 | 0.926 | 2.203 | +1.277 | 3 |
| Lorient | 0.89 | 1.501 | +0.611 | 0.965 | 1.385 | +0.420 | 2 |
| Lyon | 1.731 | 1.534 | -0.197 | 1.308 | 1.63 | +0.322 | 2 |
| Marseille | 1.576 | 1.803 | +0.227 | 1.098 | 0.901 | -0.197 | 2 |
| Monaco | 1.401 | 1.633 | +0.232 | 1.168 | 0.958 | -0.210 | 2 |
| Nice | 1.257 | 0.839 | -0.418 | 1.226 | 2.499 | +1.273 | 2 |
| PSG | 2.032 | 1.206 | -0.826 | 0.791 | 1.037 | +0.246 | 2 |
| Paris | 0.965 | 2.283 | +1.318 | 1.129 | 0.465 | -0.664 | 2 |
| Rennes | 1.546 | 2.276 | +0.730 | 1.405 | 1.677 | +0.272 | 2 |
| Strasbourg | 1.327 | 1.026 | -0.301 | 1.183 | 2.651 | +1.468 | 2 |
| Toulouse | 1.149 | 2.145 | +0.996 | 1.08 | 1.817 | +0.737 | 3 |

Scostamento medio assoluto: xG 0.775, xGA 0.706.

