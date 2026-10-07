# Tiri e tiri in porta sul residuo della testa Totali: referto

Referto GENERATO da `audit/shots_residual_test.py` (sola lettura: nessuna modifica a `SoccerMath/`).

- Rigenerabile con: `python audit/shots_residual_test.py` (sola lettura; il commit di generazione e' in `meta.commit` del JSON)
- Banco riusato: `audit/ppda_residual_test.py`, `audit/build_ppda_deep_rolling.py`, `audit/test_ppda_deep_rolling.py` (branch `arena/01a0aaed-soccermath2-0`, commit `be09532`)
- Stagioni: 2022/23, 2023/24, 2024/25, 2025/26 (2022/23 solo riscaldamento, 2026/27 escluso)
- Prior di shrinkage: `app.PRIOR_MATCHES` = 6.0
- Bootstrap: 2000 repliche, seed 20261007, blocchi (lega x stagione x giornata)

## 0. Definizioni fissate prima di guardare i numeri

Stato per squadra a INIZIO GIORNATA: entrano solo le partite con data STRETTAMENTE precedente a quella della partita (tutte le partite di una giornata vedono lo stesso stato e lo stato si aggiorna dopo la giornata). Shrinkage `app._shrunk_ratio(observed, expected, n, prior=PRIOR_MATCHES)` letto dalla produzione (prior = 6.0); con n = 0 il rapporto e' 1.0, quindi la feature vale 0 in log-spazio.

- `x_vol` (casa) = log(tiri fatti casa / media lega) + log(tiri concessi trasferta / media lega)
- `x_sot` (casa) = log(quota tiri in porta fatti casa / media lega) + log(quota tiri in porta concessi trasferta / media lega)
- simmetrico per la trasferta; **solo queste due covariate**.

`quota` = HST/HS (frazione di tiri in porta sul totale dei tiri). La lettura alternativa (tiri in porta per partita) e' nella sezione 7.

Media di lega point-in-time: media per squadra-partita calcolata sulle stesse partite gia' viste (tiri: totale tiri delle due squadre / 2 / n; quota: totale tiri in porta / totale tiri).

Modello dei fold: `lambda_nuova = lambda_prod * exp(b1*x_vol + b2*x_sot)` con b1, b2 COMUNI alle 5 leghe e ai due lati, stimati per massima verosimiglianza Poisson sui gol (GLM con `offset = log(lambda_prod)`; le righe casa e trasferta sono impilate). Probabilita' da `app._poisson_market` (matrice dei punteggi di produzione).

## 1. Copertura di HS/AS/HST/AST (football-data)

| lega | stagione | righe | righe con almeno un valore mancante | HS | AS | HST | AST |
|---|---|---|---|---|---|---|---|
| Serie A | 2022/23 | 380 | 0 | 0 | 0 | 0 | 0 |
| Serie A | 2023/24 | 380 | 0 | 0 | 0 | 0 | 0 |
| Serie A | 2024/25 | 380 | 0 | 0 | 0 | 0 | 0 |
| Serie A | 2025/26 | 380 | 0 | 0 | 0 | 0 | 0 |
| Serie A | 2026/27 (esclusa) | 50 | 50 | 50 | 50 | 50 | 50 |
| Premier League | 2022/23 | 380 | 0 | 0 | 0 | 0 | 0 |
| Premier League | 2023/24 | 380 | 0 | 0 | 0 | 0 | 0 |
| Premier League | 2024/25 | 380 | 0 | 0 | 0 | 0 | 0 |
| Premier League | 2025/26 | 380 | 0 | 0 | 0 | 0 | 0 |
| Premier League | 2026/27 (esclusa) | 50 | 50 | 50 | 50 | 50 | 50 |
| La Liga | 2022/23 | 380 | 0 | 0 | 0 | 0 | 0 |
| La Liga | 2023/24 | 380 | 0 | 0 | 0 | 0 | 0 |
| La Liga | 2024/25 | 380 | 0 | 0 | 0 | 0 | 0 |
| La Liga | 2025/26 | 380 | 0 | 0 | 0 | 0 | 0 |
| La Liga | 2026/27 (esclusa) | 71 | 71 | 71 | 71 | 71 | 71 |
| Bundesliga | 2022/23 | 306 | 0 | 0 | 0 | 0 | 0 |
| Bundesliga | 2023/24 | 306 | 0 | 0 | 0 | 0 | 0 |
| Bundesliga | 2024/25 | 306 | 1 | 1 | 1 | 1 | 1 |
| Bundesliga | 2025/26 | 306 | 0 | 0 | 0 | 0 | 0 |
| Bundesliga | 2026/27 (esclusa) | 36 | 36 | 36 | 36 | 36 | 36 |
| Ligue 1 | 2022/23 | 380 | 0 | 0 | 0 | 0 | 0 |
| Ligue 1 | 2023/24 | 306 | 0 | 0 | 0 | 0 | 0 |
| Ligue 1 | 2024/25 | 306 | 0 | 0 | 0 | 0 | 0 |
| Ligue 1 | 2025/26 | 306 | 0 | 0 | 0 | 0 | 0 |
| Ligue 1 | 2026/27 (esclusa) | 45 | 45 | 45 | 45 | 45 | 45 |

Partite in perimetro con statistiche complete: **7081** su 7082 (1 scartata per valori mancanti).

Partite scartate (fuori dal dataset e quindi anche dallo stato point-in-time, nessuna imputazione):

| lega | stagione | data | casa | trasferta | colonne mancanti |
|---|---|---|---|---|---|
| Bundesliga | 2024/25 | 2024-12-14 | Union Berlin | Bochum | HS, AS, HST, AST |

## 2. Lambda di produzione (testa Totali, point-in-time)

Ricostruzione walk-forward con il banco riusato (`ppda_residual_test.production_totali`): `att0_pure`/`def0_pure` dalla fonte F_season al cutoff della partita, shrinkage `_shrunk_ratio` e media gol cumulative delle partite precedenti, poi `app._clip_lambda(att0_pure * def0_pure_avversario * media_gol)`.

Verifica ESEGUITA, non assunta: le probabilita' Under 2.5 e GG della ricostruzione (`app._poisson_market` sui due lambda) vengono confrontate con quelle restituite dal motore di produzione (`app.get_full_poisson_two_heads` importata, applicata agli stessi dizionari di statistiche). Lo scarto massimo assoluto e' la prova che il lambda usato nel test e' quello di produzione.

| lega | partite | scarto max Under 2.5 ricostruito vs motore | scarto max GG | fallback gol (partite) 2023/24 | 2024/25 | 2025/26 |
|---|---|---|---|---|---|---|
| Serie A | 1520 | 0.00e+00 | 0.00e+00 | 10 | 10 | 10 |
| Premier League | 1520 | 0.00e+00 | 0.00e+00 | 10 | 10 | 10 |
| La Liga | 1520 | 0.00e+00 | 0.00e+00 | 10 | 10 | 10 |
| Bundesliga | 1224 | 0.00e+00 | 0.00e+00 | 9 | 9 | 9 |
| Ligue 1 | 1298 | 0.00e+00 | 0.00e+00 | 9 | 9 | 9 |

Fallback gol = partite in cui la fonte F_season non passa il gate (tipicamente la prima giornata di stagione) e `att0_pure`/`def0_pure` ricadono sul fallback gol di produzione. Nessuna partita del dataset e' rimasta senza lambda di produzione (non agganciate: 0 in tutte le leghe).

## 3. Ridondanza: x_vol / x_sot vs parametri puri di produzione

Partner di ogni feature sono i due parametri che entrano nella lambda di quella partita: per il lato casa, `att0_pure` della squadra di casa e `def0_pure` dell'avversaria (trasferta); per il lato trasferta, il simmetrico. Tutto in log-spazio come il modello.

| lega | covariata (lato) | n | corr con log(att0_pure) | corr con log(def0_pure dell'avversaria) |
|---|---|---|---|---|
| Bundesliga | x_vol_home | 1223 | 0.532 | 0.560 |
| Bundesliga | x_sot_home | 1223 | 0.499 | 0.076 |
| Bundesliga | x_vol_away | 1223 | 0.543 | 0.582 |
| Bundesliga | x_sot_away | 1223 | 0.501 | 0.092 |
| La Liga | x_vol_home | 1520 | 0.605 | 0.458 |
| La Liga | x_sot_home | 1520 | 0.373 | 0.279 |
| La Liga | x_vol_away | 1520 | 0.591 | 0.457 |
| La Liga | x_sot_away | 1520 | 0.386 | 0.287 |
| Ligue 1 | x_vol_home | 1298 | 0.592 | 0.384 |
| Ligue 1 | x_sot_home | 1298 | 0.483 | 0.188 |
| Ligue 1 | x_vol_away | 1298 | 0.607 | 0.393 |
| Ligue 1 | x_sot_away | 1298 | 0.452 | 0.224 |
| Premier League | x_vol_home | 1520 | 0.531 | 0.547 |
| Premier League | x_sot_home | 1520 | 0.309 | 0.041 |
| Premier League | x_vol_away | 1520 | 0.514 | 0.545 |
| Premier League | x_sot_away | 1520 | 0.279 | 0.032 |
| Serie A | x_vol_home | 1520 | 0.554 | 0.468 |
| Serie A | x_sot_home | 1520 | 0.382 | 0.257 |
| Serie A | x_vol_away | 1520 | 0.563 | 0.457 |
| Serie A | x_sot_away | 1520 | 0.388 | 0.262 |

## 4. Coefficienti per fold (coefficienti comuni alle 5 leghe)

| fold | stima su | n osservazioni (lati) | x_vol | x_sot | LR vs solo offset | p | dispersione di Pearson |
|---|---|---|---|---|---|---|---|
| fold1 | 2023/24 | 3504 | 0.4478 [0.2993, 0.5963] | 0.1957 [-0.0934, 0.4847] | 41.76 | 8.549e-10 | 0.9504 |
| fold2 | 2023/24+2024/25 | 7006 | 0.4563 [0.3502, 0.5624] | 0.2355 [0.0211, 0.4499] | 87.15 | 1.189e-19 | 0.9535 |

## 5. LogLoss O/U 2.5 e GG/NG (pooled sui due fold)

| mercato | modello | LogLoss | Brier | reliability | resolution |
|---|---|---|---|---|---|
| O/U 2.5 | produzione | 0.682104 | 0.244545 | 0.000947 | 0.007500 |
| O/U 2.5 | tiri | 0.682061 | 0.244500 | 0.001305 | 0.010276 |
| GG/NG | produzione | 0.688337 | 0.247579 | 0.000780 | 0.003926 |
| GG/NG | tiri | 0.688623 | 0.247715 | 0.001063 | 0.005035 |

| mercato | Delta LogLoss (tiri - produzione) | IC 95% bootstrap | quota di repliche con Delta < 0 | blocchi |
|---|---|---|---|---|
| O/U 2.5 | -0.000042 | [-0.002071, +0.002093] | 0.5210 | 1172 |
| GG/NG | +0.000287 | [-0.001023, +0.001637] | 0.3275 | 1172 |

| fold | lega | mercato | Delta LogLoss | n |
|---|---|---|---|---|
| fold1 | Bundesliga | O/U 2.5 | -0.002714 | 305 |
| fold1 | La Liga | O/U 2.5 | -0.002652 | 380 |
| fold1 | Ligue 1 | O/U 2.5 | -0.004121 | 306 |
| fold1 | Premier League | O/U 2.5 | +0.002861 | 380 |
| fold1 | Serie A | O/U 2.5 | +0.000988 | 380 |
| fold2 | Bundesliga | O/U 2.5 | -0.004004 | 306 |
| fold2 | La Liga | O/U 2.5 | +0.002940 | 380 |
| fold2 | Ligue 1 | O/U 2.5 | -0.003329 | 306 |
| fold2 | Premier League | O/U 2.5 | +0.001668 | 380 |
| fold2 | Serie A | O/U 2.5 | +0.005207 | 380 |
| fold1 | Bundesliga | GG/NG | -0.001869 | 305 |
| fold1 | La Liga | GG/NG | +0.000033 | 380 |
| fold1 | Ligue 1 | GG/NG | +0.001563 | 306 |
| fold1 | Premier League | GG/NG | +0.001783 | 380 |
| fold1 | Serie A | GG/NG | -0.000619 | 380 |
| fold2 | Bundesliga | GG/NG | +0.005215 | 306 |
| fold2 | La Liga | GG/NG | +0.003850 | 380 |
| fold2 | Ligue 1 | GG/NG | -0.002682 | 306 |
| fold2 | Premier League | GG/NG | -0.003645 | 380 |
| fold2 | Serie A | GG/NG | -0.000556 | 380 |

Segno di Delta O/U per lega e per fold: {"Bundesliga": {"fold1": -0.002713708767671408, "fold2": -0.004004181149706798}, "La Liga": {"fold1": -0.002652321955462833, "fold2": 0.0029401460146475378}, "Ligue 1": {"fold1": -0.004121179613886694, "fold2": -0.0033286046151572712}, "Premier League": {"fold1": 0.00286060187538828, "fold2": 0.0016676612907264854}, "Serie A": {"fold1": 0.0009877335519500319, "fold2": 0.005206587015890385}}

### LR test in-sample per lega (informativo, NON criterio)

| fold | lega | LR | df | p |
|---|---|---|---|---|
| fold1 | Bundesliga | 7.98 | 2 | 0.01853 |
| fold1 | La Liga | 21.55 | 2 | 2.089e-05 |
| fold1 | Ligue 1 | 4.55 | 2 | 0.1026 |
| fold1 | Premier League | 11.44 | 2 | 0.003279 |
| fold1 | Serie A | 7.16 | 2 | 0.02785 |
| fold2 | Bundesliga | 17.80 | 2 | 0.0001365 |
| fold2 | La Liga | 29.27 | 2 | 4.403e-07 |
| fold2 | Ligue 1 | 7.95 | 2 | 0.01878 |
| fold2 | Premier League | 17.85 | 2 | 0.0001327 |
| fold2 | Serie A | 20.50 | 2 | 3.539e-05 |

## 6. Test di leakage con iniezione controllata

| variante | max scarto | differenze | esito |
|---|---|---|---|
| (a+b) troncamento e iniezione di futuro estremo | 0.00e+00 | 0 | OK |
| (c) leak vero (statistiche della partita stessa) | 0.093368 | 500 | OK (rilevato su tutte le partite campionate) |

Partite campionate: 125 (25 per lega, seed 20261007).

## 7. Verdetto (regola fissata a priori)

- Delta LogLoss O/U pooled < 0: SI (Delta = -0.000042)
- IC 95% che esclude lo zero: NO ([-0.002071, +0.002093])
- Negativo in entrambi i fold: NO ({"fold1": -0.000933, "fold2": 0.000848})
- Vincolo GG/NG rispettato (Delta <= +0.0005): SI (Delta = +0.000287)

**Verdetto: CHIUDERE la pista tiri: nessuna integrazione**

Sensibilita' dichiarata (NON e' il primary): due letture alternative, riportate per completezza: (1) x_sot come tasso di tiri in porta per partita invece che come quota sul totale tiri; (2) medie di stagione invece che cumulative. Il verdetto resta quello del primary.

| sensibilita' | Delta LogLoss O/U | IC 95% | Delta LogLoss GG/NG | IC 95% |
|---|---|---|---|---|
| x_sot come tiri in porta per partita | -0.000056 | [-0.002099, +0.002079] | +0.000281 | [-0.001029, +0.001616] |
| medie di stagione (stato azzerato a inizio stagione) | +0.001705 | [+0.000059, +0.003457] | +0.000816 | [-0.000067, +0.001773] |

## 8. Conformita' alla richiesta (esito / comando / evidenza)

| requisito | esito | comando | evidenza |
|---|---|---|---|
| Solo `audit/` toccato (nessuna modifica a `SoccerMath/`) | NON VERIFICABILE dal referto | `git diff --name-only origin/main...HEAD` | dipende dal contesto git del branch: l'esito e' riportato nella PR, non qui |
| Banco PPDA/deep riusato, non riscritto | OK | `git show be09532:audit/ppda_residual_test.py` | `audit/ppda_residual_test.py` (production_totali) + `audit/build_ppda_deep_rolling.py` (test di leakage) dal branch `arena/01a0aaed-soccermath2-0`, commit `be09532` |
| Copertura HS/AS/HST/AST per lega e stagione | OK | `python audit/shots_residual_test.py` | sezione 1: 7081/7082 partite complete, 1 scartate |
| Lambda di produzione point-in-time senza toccare la produzione | OK | `production_totali` (banco) + `app.get_full_poisson_two_heads` | scarto massimo ricostruzione vs motore = 0.00e+00 (Under 2.5) |
| Feature fissate, due covariate | OK | sezione 0 | `x_vol`, `x_sot` point-in-time a inizio giornata, shrinkage PRIOR_MATCHES |
| Leakage: nessuna finestra in avanti | OK | varianti (a) e (b) del test | max scarto 0.00e+00 su 125 partite |
| Leakage: il test rileva un leak vero | OK (rilevato su tutte le partite campionate) | variante (c) del test | rilevato su 125/125 partite, max scarto 0.0934 |
| Ridondanza riportata prima dei modelli | OK | sezione 3 | correlazioni x_vol / x_sot vs log(att0_pure), log(def0_pure) per lega |
| Rolling-origin fissato (2023/24 -> 2024/25; +2024/25 -> 2025/26) | OK | sezione 4 | n osservazioni di stima 3504 e 7006 lati |
| Bootstrap a blocchi, 2000 repliche, IC 95% | OK | sezione 5 | 1172 blocchi (lega x stagione x giornata), seed 20261007 |
| Sicurezza GG/NG entro +0.0005 | OK | sezione 5 | Delta +0.000287 |
| Regola di decisione applicata meccanicamente | OK | sezione 7 | CHIUDERE la pista tiri: nessuna integrazione |

Dettaglio macchina-leggibile: JSON del run (`--json`, con il comando di riferimento in `audit/output/shots_residual_test.json`, non versionato; `audit/output/` e' in `.gitignore`).
