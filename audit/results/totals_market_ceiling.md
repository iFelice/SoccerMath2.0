# Tetto pratico dei Totali: modello contro mercato (O/U 2.5 e GG/NG)

*Referto GENERATO da `audit/totals_market_ceiling.py` (sola lettura: nessuna modifica a `SoccerMath/`). Rigenerabile con `python audit/totals_market_ceiling.py` dalla radice del repo.*

- Generato: 2026-10-07T22:44:48+00:00 — commit `8f82c3ab46f36d73fad7f4547369aa95a401ffd4` (audit: script del confronto Totali modello vs mercato (tetto pratico O/U 2.5 e GG/NG))
- Bootstrap: 2000 repliche, seed 20261007, blocchi (lega x stagione x giornata = data della partita, come nei banchi PR #34/#39)
- De-vig di decisione: proporzionale (`backtest_experiment_all.devig_2way`); Shin riportato a parte (§2b)
- Finestra di valutazione: 2024/25, 2025/26 — solo partite con modello E quota
- Base rate per il BSS: base rate del TRAIN per lega e stagione (`baserate_oos.raw`, convenzione PR #34)
- Soglia di lettura fissata a priori: `CEILING_EPS = 0.002`

## 0. Quali probabilita' del modello (dichiarazione)

La commessa cita due precedenti che **non sono lo stesso codice**. Entrambi sono riportati per intero; la colonna primaria (quella dei verdetti) e' la testa Totali di produzione.

| colonna | codice riusato (importato, non riscritto) | precedente |
|---|---|---|
| `model_produzione` | `ppda_residual_test.production_totali`: P(Over 2.5) = 1 − `engine_u25`, P(GG) = `engine_gg`, `lambda_total` | test sul residuo PPDA (PR #33) e tiri (PR #39) |
| `model_banco_PR34` | `backtest_experiment_all.run_walkforward`: `poisson_o25` (P(Over 2.5)), `poisson_gg` | `audit/results/ev_and_baserate_fix.md` (PR #34), `baserate_oos.py` |

Controlli incrociati fra banchi (non assunzioni):

| controllo | valore |
|---|---|
| scarto massimo fra `engine_gg` e `walk_forward_gg_predictions` (valoreassoluto) | 0.121004359231 (Serie A) — per lega nel JSON |
| righe con esito GG diverso fra le due fonti | Bundesliga: 0; La Liga: 0; Ligue 1: 0; Premier League: 0; Serie A: 0 |
| righe BTTS senza aggancio al modello | Bundesliga: 0; La Liga: 0; Ligue 1: 0; Premier League: 0; Serie A: 0 |
| rinomine dei nomi CSV da parte della mappa esonimi del banco GG | Bundesliga: 0; La Liga: 0; Ligue 1: 0; Premier League: 0; Serie A: 0 |
| scarto `real_uo`/`real_gg` del banco vs esito ricalcolato dai gol | Serie A: ou=0 gg=0; Premier League: ou=0 gg=0; La Liga: ou=0 gg=0; Bundesliga: ou=0 gg=0; Ligue 1: ou=0 gg=0 |

## 1. Copertura delle quote

### 1a. Over/Under 2.5 (CSV football-data), per lega, stagione e colonna

`nn` = valori non nulli; `coppia` = entrambi i lati usabili (quota > 1,0); `ovr` = media di 1/q_over + 1/q_under sul campione con coppia. `B365*` apertura, `B365C*` chiusura bet365, `PC*` chiusura Pinnacle.

Le stagioni 2022/23-2023/24 sono riportate per completezza (servono al base rate del train); la finestra di valutazione e' 2024/25-2025/26. La riga 2026/27 dei CSV `*_Live.csv` ha 0 valori: i file Live non contengono quote O/U e restano fuori dall'analisi (limite dichiarato in §8).

| lega | stagione | righe | B365>2.5 | B365<2.5 | coppia ap. | ovr ap. | B365C>2.5 | B365C<2.5 | coppia ch. | ovr ch. | PC>2.5 | PC<2.5 | coppia PC | ovr PC |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Serie A | 2022/23 | 380 | 380 | 380 | 380 | 1.0446 | 380 | 380 | 380 | 1.0455 | 380 | 380 | 380 | 1.0284 |
| Serie A | 2023/24 | 380 | 380 | 380 | 380 | 1.0500 | 380 | 380 | 380 | 1.0506 | 380 | 380 | 380 | 1.0290 |
| Serie A | 2024/25 | 380 | 380 | 380 | 380 | 1.0460 | 380 | 380 | 380 | 1.0473 | 380 | 380 | 380 | 1.0300 |
| Serie A | 2025/26 | 380 | 380 | 380 | 380 | 1.0509 | 380 | 380 | 380 | 1.0508 | 198 | 198 | 198 | 1.0321 |
| Serie A | 2026/27 | 50 | 0 | 0 | 0 | - | 0 | 0 | 0 | - | 0 | 0 | 0 | - |
| Premier League | 2022/23 | 380 | 380 | 380 | 380 | 1.0450 | 380 | 380 | 380 | 1.0451 | 379 | 379 | 379 | 1.0291 |
| Premier League | 2023/24 | 380 | 380 | 380 | 380 | 1.0528 | 380 | 380 | 380 | 1.0519 | 373 | 373 | 373 | 1.0322 |
| Premier League | 2024/25 | 380 | 380 | 380 | 380 | 1.0503 | 380 | 380 | 380 | 1.0484 | 377 | 377 | 377 | 1.0333 |
| Premier League | 2025/26 | 380 | 380 | 380 | 380 | 1.0506 | 380 | 380 | 380 | 1.0505 | 210 | 210 | 210 | 1.0312 |
| Premier League | 2026/27 | 50 | 0 | 0 | 0 | - | 0 | 0 | 0 | - | 0 | 0 | 0 | - |
| La Liga | 2022/23 | 380 | 380 | 380 | 380 | 1.0483 | 380 | 380 | 380 | 1.0484 | 380 | 380 | 380 | 1.0294 |
| La Liga | 2023/24 | 380 | 380 | 380 | 380 | 1.0517 | 380 | 380 | 380 | 1.0521 | 380 | 380 | 380 | 1.0297 |
| La Liga | 2024/25 | 380 | 380 | 380 | 380 | 1.0498 | 380 | 380 | 380 | 1.0483 | 378 | 378 | 378 | 1.0319 |
| La Liga | 2025/26 | 380 | 380 | 380 | 380 | 1.0502 | 380 | 380 | 380 | 1.0501 | 189 | 189 | 188 | 1.0339 |
| La Liga | 2026/27 | 71 | 0 | 0 | 0 | - | 0 | 0 | 0 | - | 0 | 0 | 0 | - |
| Bundesliga | 2022/23 | 306 | 306 | 306 | 306 | 1.0490 | 306 | 306 | 306 | 1.0496 | 294 | 294 | 294 | 1.0298 |
| Bundesliga | 2023/24 | 306 | 306 | 306 | 306 | 1.0499 | 306 | 306 | 306 | 1.0488 | 293 | 293 | 293 | 1.0319 |
| Bundesliga | 2024/25 | 306 | 306 | 306 | 306 | 1.0506 | 306 | 306 | 306 | 1.0492 | 297 | 297 | 296 | 1.0320 |
| Bundesliga | 2025/26 | 306 | 306 | 306 | 306 | 1.0514 | 306 | 306 | 306 | 1.0516 | 142 | 142 | 142 | 1.0350 |
| Bundesliga | 2026/27 | 36 | 0 | 0 | 0 | - | 0 | 0 | 0 | - | 0 | 0 | 0 | - |
| Ligue 1 | 2022/23 | 380 | 380 | 380 | 380 | 1.0453 | 380 | 380 | 380 | 1.0457 | 378 | 378 | 378 | 1.0290 |
| Ligue 1 | 2023/24 | 306 | 306 | 306 | 306 | 1.0485 | 306 | 306 | 306 | 1.0470 | 306 | 306 | 306 | 1.0285 |
| Ligue 1 | 2024/25 | 306 | 306 | 306 | 306 | 1.0461 | 306 | 306 | 306 | 1.0473 | 304 | 304 | 303 | 1.0308 |
| Ligue 1 | 2025/26 | 306 | 306 | 306 | 306 | 1.0504 | 306 | 306 | 306 | 1.0509 | 152 | 152 | 152 | 1.0311 |
| Ligue 1 | 2026/27 | 45 | 0 | 0 | 0 | - | 0 | 0 | 0 | - | 0 | 0 | 0 | - |

### 1b. GG/NG (`audit/data/*_btts.json`, Oddsportal)

| lega | stagione | righe JSON | incrociate | bet365 | fallback | coppia assente | senza quota | data in conflitto | dup non risolti | senza risultato | overround medio |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Serie A | 2023/24 | 380 | 378 | 378 | 0 | 0 | 1 | 0 | 0 | 1 | 1.0695 |
| Serie A | 2024/25 | 380 | 379 | 378 | 1 | 0 | 0 | 0 | 0 | 1 | 1.0691 |
| Serie A | 2025/26 | 380 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 | 1.0689 |
| Premier League | 2023/24 | 380 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 | 1.0684 |
| Premier League | 2024/25 | 380 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 | 1.0721 |
| Premier League | 2025/26 | 380 | 380 | 377 | 3 | 0 | 0 | 0 | 0 | 0 | 1.0707 |
| La Liga | 2023/24 | 380 | 379 | 379 | 0 | 0 | 1 | 0 | 0 | 0 | 1.0701 |
| La Liga | 2024/25 | 380 | 380 | 380 | 0 | 0 | 0 | 0 | 0 | 0 | 1.0674 |
| La Liga | 2025/26 | 380 | 380 | 379 | 1 | 0 | 0 | 0 | 0 | 0 | 1.0696 |
| Bundesliga | 2023/24 | 308 | 306 | 306 | 0 | 2 | 0 | 0 | 0 | 0 | 1.0724 |
| Bundesliga | 2024/25 | 308 | 305 | 305 | 0 | 2 | 0 | 0 | 0 | 1 | 1.0722 |
| Bundesliga | 2025/26 | 308 | 306 | 306 | 0 | 2 | 0 | 0 | 0 | 0 | 1.0726 |
| Ligue 1 | 2023/24 | 310 | 306 | 306 | 0 | 4 | 0 | 0 | 0 | 0 | 1.0700 |
| Ligue 1 | 2024/25 | 309 | 305 | 305 | 0 | 4 | 0 | 0 | 0 | 0 | 1.0702 |
| Ligue 1 | 2025/26 | 310 | 305 | 305 | 0 | 4 | 0 | 0 | 0 | 1 | 1.0700 |

**Colonne disponibili per GG/NG**: un solo snapshot per partita (`submarket_name` = `Both Teams to Score`, `period` = `FullTime`, un record per bookmaker). Non esistono colonne di apertura/chiusura ne' Pinnacle in questi file: il confronto apertura-contro-chiusura per GG/NG e' **NON VERIFICABILE**.

### 1c. Campione di valutazione (modello E quota), per fonte e lega

| mercato | fonte | lega | n |
|---|---|---|---|
| OU2.5 | model_produzione | Bundesliga | 612 |
| OU2.5 | model_produzione | La Liga | 760 |
| OU2.5 | model_produzione | Ligue 1 | 612 |
| OU2.5 | model_produzione | Premier League | 760 |
| OU2.5 | model_produzione | Serie A | 760 |
| OU2.5 | model_banco_PR34 | Bundesliga | 612 |
| OU2.5 | model_banco_PR34 | La Liga | 760 |
| OU2.5 | model_banco_PR34 | Ligue 1 | 612 |
| OU2.5 | model_banco_PR34 | Premier League | 760 |
| OU2.5 | model_banco_PR34 | Serie A | 760 |
| OU2.5 | mercato_apertura_b365 | Bundesliga | 612 |
| OU2.5 | mercato_apertura_b365 | La Liga | 760 |
| OU2.5 | mercato_apertura_b365 | Ligue 1 | 612 |
| OU2.5 | mercato_apertura_b365 | Premier League | 760 |
| OU2.5 | mercato_apertura_b365 | Serie A | 760 |
| OU2.5 | mercato_chiusura_b365 | Bundesliga | 612 |
| OU2.5 | mercato_chiusura_b365 | La Liga | 760 |
| OU2.5 | mercato_chiusura_b365 | Ligue 1 | 612 |
| OU2.5 | mercato_chiusura_b365 | Premier League | 760 |
| OU2.5 | mercato_chiusura_b365 | Serie A | 760 |
| OU2.5 | mercato_chiusura_pinnacle | Bundesliga | 438 |
| OU2.5 | mercato_chiusura_pinnacle | La Liga | 566 |
| OU2.5 | mercato_chiusura_pinnacle | Ligue 1 | 455 |
| OU2.5 | mercato_chiusura_pinnacle | Premier League | 587 |
| OU2.5 | mercato_chiusura_pinnacle | Serie A | 578 |
| GG/NG | model_produzione | Bundesliga | 611 |
| GG/NG | model_produzione | La Liga | 760 |
| GG/NG | model_produzione | Ligue 1 | 610 |
| GG/NG | model_produzione | Premier League | 760 |
| GG/NG | model_produzione | Serie A | 759 |
| GG/NG | model_produzione_banco_GG | Bundesliga | 611 |
| GG/NG | model_produzione_banco_GG | La Liga | 760 |
| GG/NG | model_produzione_banco_GG | Ligue 1 | 610 |
| GG/NG | model_produzione_banco_GG | Premier League | 760 |
| GG/NG | model_produzione_banco_GG | Serie A | 759 |
| GG/NG | model_banco_PR34 | Bundesliga | 611 |
| GG/NG | model_banco_PR34 | La Liga | 760 |
| GG/NG | model_banco_PR34 | Ligue 1 | 610 |
| GG/NG | model_banco_PR34 | Premier League | 760 |
| GG/NG | model_banco_PR34 | Serie A | 759 |
| GG/NG | mercato_btts_oddsportal | Bundesliga | 611 |
| GG/NG | mercato_btts_oddsportal | La Liga | 760 |
| GG/NG | mercato_btts_oddsportal | Ligue 1 | 610 |
| GG/NG | mercato_btts_oddsportal | Premier League | 760 |
| GG/NG | mercato_btts_oddsportal | Serie A | 759 |

### 1d. Sonda F_season: giornate in cui la fonte xG della stagione in corso non e' attiva

Quando l'ancora di lega manca (`fs_active = False` in `app.get_league_engine`), la produzione assegna `att0_pure/def0_pure = att/def` (testa 1X2 con forma e fattore mercato), `production_totali` assegna il fallback gol e `walk_forward_gg_predictions` assegna `att/def` come la produzione: su queste righe i banchi divergono. La sonda chiama la stessa `xg_archive.season_point_in_time_averages` usata dai banchi e conta le coppie (stagione, giornata) con ancora assente.

| lega | coppie (stagione, data) esaminate | di cui F_season non attiva | stagioni interessate | date interessate | righe di valutazione escluse (O/U, 2024/25+2025/26) |
|---|---|---|---|---|---|
| Serie A | 544 | 10 | 2022/23, 2023/24, 2024/25, 2025/26, 2026/27 | 2022-08-13, 2022-08-14, 2023-08-19, 2023-08-20, 2024-08-17, 2024-08-18, 2025-08-23, 2025-08-24, 2026-08-22, 2026-08-23 | 16 |
| Premier League | 477 | 10 | 2022/23, 2023/24, 2024/25, 2025/26, 2026/27 | 2022-08-05, 2022-08-06, 2023-08-11, 2023-08-12, 2024-08-16, 2024-08-17, 2025-08-15, 2025-08-16, 2026-08-21, 2026-08-22 | 13 |
| La Liga | 600 | 13 | 2022/23, 2023/24, 2024/25, 2025/26, 2026/27 | 2022-08-12, 2022-08-13, 2022-08-14, 2023-08-11, 2023-08-12, 2024-08-15, 2024-08-16, 2024-08-17, 2025-08-15, 2025-08-16, 2026-08-15, 2026-08-16, 2026-08-17 | 11 |
| Bundesliga | 406 | 10 | 2022/23, 2023/24, 2024/25, 2025/26, 2026/27 | 2022-08-05, 2022-08-06, 2023-08-18, 2023-08-19, 2024-08-23, 2024-08-24, 2025-08-22, 2025-08-23, 2026-08-28, 2026-08-29 | 14 |
| Ligue 1 | 418 | 14 | 2022/23, 2023/24, 2024/25, 2025/26, 2026/27 | 2022-08-05, 2022-08-06, 2022-08-07, 2023-08-11, 2023-08-12, 2023-08-13, 2024-08-16, 2024-08-17, 2024-08-18, 2025-08-15, 2025-08-16, 2025-08-17, 2026-08-21, 2026-08-22 | 18 |

Differenza misurata fra i due banchi di produzione sulle righe incrociate GG/NG (`engine_gg` di `production_totali` contro `walk_forward_gg_predictions`):

| lega | righe con scarto | scarto massimo Δp | righe BTTS senza aggancio |
|---|---|---|---|
| Bundesliga | 21 | 0.115881425785 | 0 |
| La Liga | 16 | 0.099836548308 | 0 |
| Ligue 1 | 27 | 0.137575592183 | 0 |
| Premier League | 20 | 0.166281514289 | 0 |
| Serie A | 24 | 0.121004359231 | 0 |

## 2. Metriche per mercato e per fonte

Scomposizione di Murphy a 10 bin con la stessa funzione della PR #34 (`baserate_oos.decomp`): Brier = reliability − resolution + uncertainty. BSS contro il base rate del train, sulle stesse righe.

### OU2.5 — pooled

| fonte | n | media p | tasso reale | Brier | LogLoss | reliab. | resol. | uncert. | BSS Brier | BSS LogLoss |
|---|---|---|---|---|---|---|---|---|---|---|
| model_produzione | 3504 | 0.5294 | 0.5322 | 0.2446 | 0.6821 | 0.00094 | 0.00471 | 0.24896 | 0.0084 | 0.0062 |
| model_banco_PR34 | 3504 | 0.5182 | 0.5322 | 0.2460 | 0.6851 | 0.00316 | 0.00521 | 0.24896 | 0.0028 | 0.0020 |
| mercato_apertura_b365 | 3504 | 0.5293 | 0.5322 | 0.2399 | 0.6725 | 0.00018 | 0.00778 | 0.24896 | 0.0272 | 0.0202 |
| mercato_chiusura_b365 | 3504 | 0.5272 | 0.5322 | 0.2383 | 0.6693 | 0.00050 | 0.00954 | 0.24896 | 0.0337 | 0.0250 |
| mercato_chiusura_pinnacle | 2624 | 0.5229 | 0.5244 | 0.2388 | 0.6704 | 0.00086 | 0.00999 | 0.24941 | 0.0335 | 0.0246 |

### OU2.5 — per lega

| lega | fonte | n | Brier | LogLoss | resol. | reliab. | BSS Brier |
|---|---|---|---|---|---|---|---|
| Bundesliga | model_produzione | 612 | 0.2317 | 0.6558 | 0.00446 | 0.00031 | 0.0195 |
| Bundesliga | model_banco_PR34 | 612 | 0.2327 | 0.6569 | 0.00883 | 0.00701 | 0.0151 |
| Bundesliga | mercato_apertura_b365 | 612 | 0.2262 | 0.6436 | 0.01176 | 0.00199 | 0.0428 |
| Bundesliga | mercato_chiusura_b365 | 612 | 0.2234 | 0.6375 | 0.01193 | 0.00120 | 0.0548 |
| Bundesliga | mercato_chiusura_pinnacle | 438 | 0.2290 | 0.6497 | 0.00885 | 0.00115 | 0.0443 |
| La Liga | model_produzione | 760 | 0.2439 | 0.6807 | 0.00599 | 0.00154 | 0.0258 |
| La Liga | model_banco_PR34 | 760 | 0.2481 | 0.6892 | 0.00735 | 0.00570 | 0.0094 |
| La Liga | mercato_apertura_b365 | 760 | 0.2391 | 0.6710 | 0.01044 | 0.00066 | 0.0450 |
| La Liga | mercato_chiusura_b365 | 760 | 0.2365 | 0.6656 | 0.01300 | 0.00203 | 0.0554 |
| La Liga | mercato_chiusura_pinnacle | 566 | 0.2344 | 0.6614 | 0.01684 | 0.00375 | 0.0608 |
| Ligue 1 | model_produzione | 612 | 0.2441 | 0.6811 | 0.00518 | 0.00239 | 0.0176 |
| Ligue 1 | model_banco_PR34 | 612 | 0.2481 | 0.6898 | 0.00318 | 0.00477 | 0.0014 |
| Ligue 1 | mercato_apertura_b365 | 612 | 0.2388 | 0.6705 | 0.00997 | 0.00174 | 0.0388 |
| Ligue 1 | mercato_chiusura_b365 | 612 | 0.2373 | 0.6675 | 0.00984 | 0.00077 | 0.0447 |
| Ligue 1 | mercato_chiusura_pinnacle | 455 | 0.2402 | 0.6735 | 0.00864 | 0.00148 | 0.0340 |
| Premier League | model_produzione | 760 | 0.2506 | 0.6947 | 0.00070 | 0.00495 | -0.0137 |
| Premier League | model_banco_PR34 | 760 | 0.2453 | 0.6843 | 0.00470 | 0.00270 | 0.0077 |
| Premier League | mercato_apertura_b365 | 760 | 0.2448 | 0.6825 | 0.00215 | 0.00266 | 0.0101 |
| Premier League | mercato_chiusura_b365 | 760 | 0.2437 | 0.6805 | 0.00331 | 0.00077 | 0.0144 |
| Premier League | mercato_chiusura_pinnacle | 587 | 0.2432 | 0.6795 | 0.00370 | 0.00044 | 0.0161 |
| Serie A | model_produzione | 760 | 0.2499 | 0.6931 | 0.00197 | 0.00157 | -0.0029 |
| Serie A | model_banco_PR34 | 760 | 0.2534 | 0.7005 | 0.00191 | 0.00751 | -0.0172 |
| Serie A | mercato_apertura_b365 | 760 | 0.2479 | 0.6890 | 0.00272 | 0.00301 | 0.0052 |
| Serie A | mercato_chiusura_b365 | 760 | 0.2476 | 0.6887 | 0.00605 | 0.00517 | 0.0060 |
| Serie A | mercato_chiusura_pinnacle | 578 | 0.2449 | 0.6832 | 0.00647 | 0.00395 | 0.0161 |

### GG/NG — pooled

| fonte | n | media p | tasso reale | Brier | LogLoss | reliab. | resol. | uncert. | BSS Brier | BSS LogLoss |
|---|---|---|---|---|---|---|---|---|---|---|
| model_produzione | 3500 | 0.5389 | 0.5460 | 0.2475 | 0.6883 | 0.00078 | 0.00145 | 0.24788 | -0.0007 | -0.0006 |
| model_produzione_banco_GG | 3500 | 0.5387 | 0.5460 | 0.2476 | 0.6884 | 0.00087 | 0.00152 | 0.24788 | -0.0010 | -0.0008 |
| model_banco_PR34 | 3500 | 0.5085 | 0.5460 | 0.2493 | 0.7023 | 0.00368 | 0.00204 | 0.24788 | -0.0076 | -0.0209 |
| mercato_btts_oddsportal | 3500 | 0.5260 | 0.5460 | 0.2443 | 0.6816 | 0.00045 | 0.00338 | 0.24788 | 0.0125 | 0.0091 |

### GG/NG — per lega

| lega | fonte | n | Brier | LogLoss | resol. | reliab. | BSS Brier |
|---|---|---|---|---|---|---|---|
| Bundesliga | model_produzione | 611 | 0.2397 | 0.6723 | 0.00374 | 0.00155 | 0.0074 |
| Bundesliga | model_produzione_banco_GG | 611 | 0.2400 | 0.6729 | 0.00396 | 0.00173 | 0.0062 |
| Bundesliga | model_banco_PR34 | 611 | 0.2436 | 0.7401 | 0.00489 | 0.00761 | -0.0088 |
| Bundesliga | mercato_btts_oddsportal | 611 | 0.2388 | 0.6704 | 0.00469 | 0.00224 | 0.0113 |
| La Liga | model_produzione | 760 | 0.2486 | 0.6903 | 0.00263 | 0.00450 | 0.0028 |
| La Liga | model_produzione_banco_GG | 760 | 0.2489 | 0.6909 | 0.00215 | 0.00450 | 0.0015 |
| La Liga | model_banco_PR34 | 760 | 0.2544 | 0.7026 | 0.00505 | 0.01195 | -0.0205 |
| La Liga | mercato_btts_oddsportal | 760 | 0.2437 | 0.6803 | 0.00683 | 0.00478 | 0.0224 |
| Ligue 1 | model_produzione | 610 | 0.2496 | 0.6924 | 0.00058 | 0.00230 | -0.0020 |
| Ligue 1 | model_produzione_banco_GG | 610 | 0.2501 | 0.6936 | 0.00128 | 0.00346 | -0.0041 |
| Ligue 1 | model_banco_PR34 | 610 | 0.2499 | 0.6928 | 0.00365 | 0.00636 | -0.0033 |
| Ligue 1 | mercato_btts_oddsportal | 610 | 0.2450 | 0.6831 | 0.00307 | 0.00080 | 0.0165 |
| Premier League | model_produzione | 760 | 0.2469 | 0.6872 | 0.00114 | 0.00268 | -0.0057 |
| Premier League | model_produzione_banco_GG | 760 | 0.2467 | 0.6869 | 0.00211 | 0.00332 | -0.0050 |
| Premier League | model_banco_PR34 | 760 | 0.2467 | 0.6865 | 0.00139 | 0.00298 | -0.0046 |
| Premier League | mercato_btts_oddsportal | 760 | 0.2446 | 0.6824 | 0.00162 | 0.00056 | 0.0036 |
| Serie A | model_produzione | 759 | 0.2518 | 0.6968 | 0.00103 | 0.00113 | -0.0044 |
| Serie A | model_produzione_banco_GG | 759 | 0.2513 | 0.6959 | 0.00153 | 0.00122 | -0.0027 |
| Serie A | model_banco_PR34 | 759 | 0.2508 | 0.6949 | 0.00368 | 0.00445 | -0.0004 |
| Serie A | mercato_btts_oddsportal | 759 | 0.2484 | 0.6899 | 0.00202 | 0.00174 | 0.0091 |

### 2b. De-vig proporzionale contro Shin (stesse righe)

| mercato | fonte | n | Brier prop. | LogLoss prop. | z medio | overround | Brier Shin | LogLoss Shin | ΔBrier Shin−prop | ΔLogLoss Shin−prop |
|---|---|---|---|---|---|---|---|---|---|---|
| OU2.5 | apertura_b365 | 3504 | 0.2399 | 0.6725 | 0.0498 | 1.0496 | 0.2399 | 0.6725 | +0.00001 | +0.00002 |
| OU2.5 | chiusura_b365 | 3504 | 0.2383 | 0.6693 | 0.0496 | 1.0494 | 0.2383 | 0.6692 | -0.00003 | -0.00005 |
| OU2.5 | chiusura_pinnacle | 2624 | 0.2388 | 0.6704 | 0.0320 | 1.0319 | 0.2388 | 0.6704 | -0.00001 | -0.00001 |
| GG/NG | btts_oddsportal | 3496 | 0.2443 | 0.6817 | 0.0709 | 1.0708 | 0.2443 | 0.6817 | -0.00001 | -0.00001 |

## 3. Differenze appaiate (bootstrap a blocchi, IC 95%)

`Δ resolution` > 0 = la fonte A risolve meglio della fonte B; `Δ LogLoss` < 0 = la fonte A perde meno. Blocchi = lega x stagione x giornata; 2000 repliche. La colonna `IC≠0` dice se l'IC 95% esclude lo zero.

### OU2.5 — pooled

| contrasto | n | blocchi | Δ resolution | IC 95% | IC≠0 | Δ LogLoss | IC 95% | IC≠0 |
|---|---|---|---|---|---|---|---|---|
| chiusura B365 − modello produzione | 3504 | 1172 | +0.0048 | [+0.0026; +0.0075] | sì | -0.0129 | [-0.0179; -0.0083] | sì |
| chiusura B365 − modello banco PR34 | 3504 | 1172 | +0.0043 | [+0.0018; +0.0069] | sì | -0.0158 | [-0.0215; -0.0102] | sì |
| apertura B365 − modello produzione | 3504 | 1172 | +0.0031 | [+0.0012; +0.0054] | sì | -0.0096 | [-0.0136; -0.0055] | sì |
| apertura B365 − modello banco PR34 | 3504 | 1172 | +0.0026 | [+0.0003; +0.0047] | sì | -0.0125 | [-0.0179; -0.0072] | sì |
| chiusura Pinnacle − modello produzione | 2624 | 874 | +0.0061 | [+0.0033; +0.0093] | sì | -0.0147 | [-0.0200; -0.0091] | sì |
| chiusura B365 − apertura B365 | 3504 | 1172 | +0.0018 | [+0.0002; +0.0033] | sì | -0.0033 | [-0.0054; -0.0012] | sì |

### OU2.5 — per lega (chiusura di mercato contro modello di produzione)

| lega | n | Δ resolution | IC 95% | IC≠0 | Δ LogLoss | IC 95% | res. mercato | res. modello |
|---|---|---|---|---|---|---|---|---|
| Bundesliga | 612 | +0.0075 | [+0.0023; +0.0153] | sì | -0.0182 | [-0.0292; -0.0069] | 0.01193 | 0.00446 |
| La Liga | 760 | +0.0070 | [+0.0013; +0.0135] | sì | -0.0151 | [-0.0251; -0.0053] | 0.01300 | 0.00599 |
| Ligue 1 | 612 | +0.0047 | [-0.0031; +0.0124] | no | -0.0137 | [-0.0252; -0.0017] | 0.00984 | 0.00518 |
| Premier League | 760 | +0.0026 | [-0.0022; +0.0081] | no | -0.0142 | [-0.0241; -0.0044] | 0.00331 | 0.00070 |
| Serie A | 760 | +0.0041 | [-0.0004; +0.0099] | no | -0.0044 | [-0.0144; +0.0053] | 0.00605 | 0.00197 |

### OU2.5 — per lega (tutti gli altri contrasti)

| contrasto | lega | n | Δ resolution | IC 95% | IC≠0 | Δ LogLoss | IC 95% |
|---|---|---|---|---|---|---|---|
| chiusura B365 − modello produzione | Bundesliga | 612 | +0.0075 | [+0.0023; +0.0153] | sì | -0.0182 | [-0.0292; -0.0069] |
| chiusura B365 − modello produzione | La Liga | 760 | +0.0070 | [+0.0013; +0.0135] | sì | -0.0151 | [-0.0251; -0.0053] |
| chiusura B365 − modello produzione | Ligue 1 | 612 | +0.0047 | [-0.0031; +0.0124] | no | -0.0137 | [-0.0252; -0.0017] |
| chiusura B365 − modello produzione | Premier League | 760 | +0.0026 | [-0.0022; +0.0081] | no | -0.0142 | [-0.0241; -0.0044] |
| chiusura B365 − modello produzione | Serie A | 760 | +0.0041 | [-0.0004; +0.0099] | no | -0.0044 | [-0.0144; +0.0053] |
| chiusura B365 − modello banco PR34 | Bundesliga | 612 | +0.0031 | [-0.0062; +0.0107] | no | -0.0194 | [-0.0339; -0.0046] |
| chiusura B365 − modello banco PR34 | La Liga | 760 | +0.0056 | [-0.0015; +0.0129] | no | -0.0236 | [-0.0362; -0.0106] |
| chiusura B365 − modello banco PR34 | Ligue 1 | 612 | +0.0067 | [-0.0011; +0.0132] | no | -0.0223 | [-0.0352; -0.0097] |
| chiusura B365 − modello banco PR34 | Premier League | 760 | -0.0014 | [-0.0080; +0.0034] | no | -0.0038 | [-0.0161; +0.0083] |
| chiusura B365 − modello banco PR34 | Serie A | 760 | +0.0041 | [-0.0013; +0.0096] | no | -0.0118 | [-0.0232; -0.0009] |
| apertura B365 − modello produzione | Bundesliga | 612 | +0.0073 | [+0.0021; +0.0138] | sì | -0.0122 | [-0.0225; -0.0021] |
| apertura B365 − modello produzione | La Liga | 760 | +0.0044 | [-0.0005; +0.0107] | no | -0.0097 | [-0.0187; -0.0009] |
| apertura B365 − modello produzione | Ligue 1 | 612 | +0.0048 | [-0.0031; +0.0133] | no | -0.0107 | [-0.0223; +0.0008] |
| apertura B365 − modello produzione | Premier League | 760 | +0.0015 | [-0.0026; +0.0049] | no | -0.0122 | [-0.0207; -0.0035] |
| apertura B365 − modello produzione | Serie A | 760 | +0.0008 | [-0.0031; +0.0057] | no | -0.0040 | [-0.0126; +0.0039] |
| apertura B365 − modello banco PR34 | Bundesliga | 612 | +0.0029 | [-0.0071; +0.0099] | no | -0.0133 | [-0.0267; +0.0006] |
| apertura B365 − modello banco PR34 | La Liga | 760 | +0.0031 | [-0.0034; +0.0102] | no | -0.0182 | [-0.0307; -0.0058] |
| apertura B365 − modello banco PR34 | Ligue 1 | 612 | +0.0068 | [-0.0012; +0.0143] | no | -0.0194 | [-0.0314; -0.0076] |
| apertura B365 − modello banco PR34 | Premier League | 760 | -0.0025 | [-0.0097; +0.0018] | no | -0.0017 | [-0.0131; +0.0095] |
| apertura B365 − modello banco PR34 | Serie A | 760 | +0.0008 | [-0.0039; +0.0055] | no | -0.0115 | [-0.0217; -0.0017] |
| chiusura Pinnacle − modello produzione | Bundesliga | 438 | +0.0059 | [-0.0011; +0.0137] | no | -0.0155 | [-0.0295; -0.0022] |
| chiusura Pinnacle − modello produzione | La Liga | 566 | +0.0117 | [+0.0041; +0.0202] | sì | -0.0185 | [-0.0305; -0.0063] |
| chiusura Pinnacle − modello produzione | Ligue 1 | 455 | +0.0056 | [-0.0031; +0.0157] | no | -0.0135 | [-0.0264; +0.0006] |
| chiusura Pinnacle − modello produzione | Premier League | 587 | +0.0032 | [-0.0031; +0.0110] | no | -0.0162 | [-0.0270; -0.0060] |
| chiusura Pinnacle − modello produzione | Serie A | 578 | +0.0038 | [-0.0021; +0.0117] | no | -0.0096 | [-0.0217; +0.0027] |
| chiusura B365 − apertura B365 | Bundesliga | 612 | +0.0002 | [-0.0038; +0.0050] | no | -0.0061 | [-0.0107; -0.0014] |
| chiusura B365 − apertura B365 | La Liga | 760 | +0.0026 | [-0.0013; +0.0067] | no | -0.0054 | [-0.0098; -0.0006] |
| chiusura B365 − apertura B365 | Ligue 1 | 612 | -0.0001 | [-0.0057; +0.0052] | no | -0.0030 | [-0.0082; +0.0026] |
| chiusura B365 − apertura B365 | Premier League | 760 | +0.0012 | [-0.0023; +0.0056] | no | -0.0021 | [-0.0063; +0.0022] |
| chiusura B365 − apertura B365 | Serie A | 760 | +0.0033 | [-0.0008; +0.0080] | no | -0.0003 | [-0.0049; +0.0040] |

### 3b. Chiusura contro apertura (stessa fonte)

| mercato | confronto | n | Δ resolution | IC 95% | IC≠0 | Δ LogLoss | IC 95% |
|---|---|---|---|---|---|---|---|
| OU2.5 | chiusura − apertura (B365) | 3504 | +0.0018 | [+0.0002; +0.0033] | sì | -0.0033 | [-0.0054; -0.0012] |
| OU2.5 | chiusura − modello (B365) | 3504 | +0.0048 | [+0.0026; +0.0075] | sì | -0.0129 | [-0.0179; -0.0083] |
| OU2.5 | apertura − modello (B365) | 3504 | +0.0031 | [+0.0012; +0.0054] | sì | -0.0096 | [-0.0136; -0.0055] |
| GG/NG | NON VERIFICABILE: i file BTTS non hanno quote di apertura/chiusura | 0 | - | - | - | - | - |

### GG/NG — pooled

| contrasto | n | blocchi | Δ resolution | IC 95% | IC≠0 | Δ LogLoss | IC 95% | IC≠0 |
|---|---|---|---|---|---|---|---|---|
| mercato BTTS − modello produzione | 3500 | 1172 | +0.0019 | [+0.0004; +0.0036] | sì | -0.0066 | [-0.0099; -0.0031] | sì |
| mercato BTTS − modello banco GG | 3500 | 1172 | +0.0019 | [+0.0003; +0.0035] | sì | -0.0068 | [-0.0103; -0.0033] | sì |
| mercato BTTS − modello banco PR34 | 3500 | 1172 | +0.0013 | [-0.0006; +0.0029] | no | -0.0207 | [-0.0401; -0.0070] | sì |

### GG/NG — per lega (chiusura di mercato contro modello di produzione)

| lega | n | Δ resolution | IC 95% | IC≠0 | Δ LogLoss | IC 95% | res. mercato | res. modello |
|---|---|---|---|---|---|---|---|---|
| Bundesliga | 611 | +0.0010 | [-0.0053; +0.0075] | no | -0.0019 | [-0.0104; +0.0068] | 0.00469 | 0.00374 |
| La Liga | 760 | +0.0042 | [-0.0006; +0.0100] | no | -0.0099 | [-0.0166; -0.0030] | 0.00683 | 0.00263 |
| Ligue 1 | 610 | +0.0025 | [-0.0018; +0.0067] | no | -0.0093 | [-0.0167; -0.0022] | 0.00307 | 0.00058 |
| Premier League | 760 | +0.0005 | [-0.0030; +0.0054] | no | -0.0048 | [-0.0128; +0.0038] | 0.00162 | 0.00114 |
| Serie A | 759 | +0.0010 | [-0.0026; +0.0047] | no | -0.0068 | [-0.0142; +0.0000] | 0.00202 | 0.00103 |

### GG/NG — per lega (tutti gli altri contrasti)

| contrasto | lega | n | Δ resolution | IC 95% | IC≠0 | Δ LogLoss | IC 95% |
|---|---|---|---|---|---|---|---|
| mercato BTTS − modello produzione | Bundesliga | 611 | +0.0010 | [-0.0053; +0.0075] | no | -0.0019 | [-0.0104; +0.0068] |
| mercato BTTS − modello produzione | La Liga | 760 | +0.0042 | [-0.0006; +0.0100] | no | -0.0099 | [-0.0166; -0.0030] |
| mercato BTTS − modello produzione | Ligue 1 | 610 | +0.0025 | [-0.0018; +0.0067] | no | -0.0093 | [-0.0167; -0.0022] |
| mercato BTTS − modello produzione | Premier League | 760 | +0.0005 | [-0.0030; +0.0054] | no | -0.0048 | [-0.0128; +0.0038] |
| mercato BTTS − modello produzione | Serie A | 759 | +0.0010 | [-0.0026; +0.0047] | no | -0.0068 | [-0.0142; +0.0000] |
| mercato BTTS − modello banco GG | Bundesliga | 611 | +0.0007 | [-0.0055; +0.0074] | no | -0.0025 | [-0.0108; +0.0065] |
| mercato BTTS − modello banco GG | La Liga | 760 | +0.0047 | [-0.0003; +0.0105] | no | -0.0106 | [-0.0173; -0.0038] |
| mercato BTTS − modello banco GG | Ligue 1 | 610 | +0.0018 | [-0.0025; +0.0061] | no | -0.0105 | [-0.0186; -0.0032] |
| mercato BTTS − modello banco GG | Premier League | 760 | -0.0005 | [-0.0046; +0.0047] | no | -0.0045 | [-0.0125; +0.0039] |
| mercato BTTS − modello banco GG | Serie A | 759 | +0.0005 | [-0.0036; +0.0046] | no | -0.0059 | [-0.0137; +0.0015] |
| mercato BTTS − modello banco PR34 | Bundesliga | 611 | -0.0002 | [-0.0074; +0.0064] | no | -0.0697 | [-0.1778; +0.0023] |
| mercato BTTS − modello banco PR34 | La Liga | 760 | +0.0018 | [-0.0053; +0.0074] | no | -0.0223 | [-0.0339; -0.0104] |
| mercato BTTS − modello banco PR34 | Ligue 1 | 610 | -0.0006 | [-0.0067; +0.0034] | no | -0.0097 | [-0.0211; +0.0009] |
| mercato BTTS − modello banco PR34 | Premier League | 760 | +0.0002 | [-0.0033; +0.0041] | no | -0.0041 | [-0.0131; +0.0047] |
| mercato BTTS − modello banco PR34 | Serie A | 759 | -0.0017 | [-0.0066; +0.0025] | no | -0.0049 | [-0.0136; +0.0035] |

### 3b. Chiusura contro apertura (stessa fonte)

| mercato | confronto | n | Δ resolution | IC 95% | IC≠0 | Δ LogLoss | IC 95% |
|---|---|---|---|---|---|---|---|
| OU2.5 | chiusura − apertura (B365) | 3504 | +0.0018 | [+0.0002; +0.0033] | sì | -0.0033 | [-0.0054; -0.0012] |
| OU2.5 | chiusura − modello (B365) | 3504 | +0.0048 | [+0.0026; +0.0075] | sì | -0.0129 | [-0.0179; -0.0083] |
| OU2.5 | apertura − modello (B365) | 3504 | +0.0031 | [+0.0012; +0.0054] | sì | -0.0096 | [-0.0136; -0.0055] |
| GG/NG | NON VERIFICABILE: i file BTTS non hanno quote di apertura/chiusura | 0 | - | - | - | - | - |

### 3c. Sensibilita': stesse differenze senza le giornate con F_season non attiva

Sono le righe delle prime giornate di ogni stagione, quando l'ancora di lega degli xG della stagione in corso non esiste ancora (`fs_active = False` in `app.get_league_engine`, §1d). Su queste righe i tre codici divergono: la produzione usa `att0_pure = att` (testa 1X2 con forma e fattore mercato), `gg_ng_calibration.walk_forward_gg_predictions` la riproduce, mentre `ppda_residual_test.production_totali` (la colonna primaria di questo referto) usa il fallback gol: la differenza osservabile sui valori GG arriva a 0.166 di probabilita' (§1d). Escludendo quelle righe le differenze vengono ricalcolate: se il verdetto non cambia, non dipende dal ramo divergente. Per GG/NG la colonna `model_produzione_banco_GG` e' fedele alla produzione anche su queste righe.

| mercato | righe | escluse | righe ridotte | Δ resolution | IC 95% | Δ LogLoss | IC 95% |
|---|---|---|---|---|---|---|---|
| OU2.5 | 3504 | 72 | 3432 | +0.0047 | [+0.0025; +0.0074] | -0.0126 | [-0.0175; -0.0081] |
| GG/NG | 3500 | 72 | 3428 | +0.0020 | [+0.0003; +0.0037] | -0.0066 | [-0.0102; -0.0033] |

Metriche sulla stessa finestra ridotta:

| mercato | fonte | n | Brier | LogLoss | resol. | BSS Brier |
|---|---|---|---|---|---|---|
| OU2.5 | model_produzione | 3432 | 0.2443 | 0.6816 | 0.00484 | 0.0095 |
| OU2.5 | model_banco_PR34 | 3432 | 0.2457 | 0.6845 | 0.00532 | 0.0038 |
| OU2.5 | mercato_apertura_b365 | 3432 | 0.2398 | 0.6722 | 0.00768 | 0.0278 |
| OU2.5 | mercato_chiusura_b365 | 3432 | 0.2382 | 0.6691 | 0.00958 | 0.0341 |
| OU2.5 | mercato_chiusura_pinnacle | 2552 | 0.2386 | 0.6699 | 0.01013 | 0.0346 |
| GG/NG | model_produzione | 3428 | 0.2474 | 0.6879 | 0.00155 | -0.0005 |
| GG/NG | model_produzione_banco_GG | 3428 | 0.2474 | 0.6879 | 0.00155 | -0.0005 |
| GG/NG | model_banco_PR34 | 3428 | 0.2491 | 0.7022 | 0.00213 | -0.0076 |
| GG/NG | mercato_btts_oddsportal | 3428 | 0.2441 | 0.6813 | 0.00355 | 0.0127 |

Righe escluse, per lega (campione di valutazione):

| mercato | righe escluse | Bundesliga | La Liga | Ligue 1 | Premier League | Serie A |
|---|---|---|---|---|---|---|
| OU2.5 | 72 | 14 | 11 | 18 | 13 | 16 |
| GG/NG | 72 | 14 | 11 | 18 | 13 | 16 |

## 4. Dispersione dei lambda: mercato contro modello

La P(Under 2.5) de-vigata viene invertita in un lambda totale Poisson (`P(under) = exp(−λ)(1 + λ + λ²/2)`; la somma di due Poisson indipendenti e' Poisson, quindi l'inversione usa esattamente la probabilita' che il modello calcola). Per il modello di produzione il lambda totale e' anche esplicito (`lambda_total`): lo scarto massimo fra esplicito e invertito misura la fedelta' dell'inversione.

| lega | n | λ medio merc. | media log λ merc. | sd log λ merc. | n PC | media log λ PC | sd log λ PC | media log λ modello | sd log λ modello | media log λ banco | sd log λ banco | scarto max inversione |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Bundesliga | 612 | 3.120 | 1.1287 | 0.1339 | 438 | 1.1139 | 0.1133 | 1.1522 | 0.1064 | 0.8336 | 0.2165 | 0.00000000 |
| La Liga | 760 | 2.623 | 0.9474 | 0.1826 | 566 | 0.9321 | 0.1806 | 0.9394 | 0.1361 | 1.0297 | 0.1878 | 0.00000000 |
| Ligue 1 | 612 | 2.883 | 1.0506 | 0.1265 | 455 | 1.0479 | 0.1202 | 1.0259 | 0.1033 | 0.9282 | 0.1612 | 0.00000000 |
| Premier League | 760 | 2.962 | 1.0791 | 0.1157 | 587 | 1.0792 | 0.1173 | 1.0973 | 0.0983 | 0.8917 | 0.1526 | 0.00000000 |
| Serie A | 760 | 2.556 | 0.9316 | 0.1148 | 578 | 0.9317 | 0.1155 | 0.9395 | 0.1055 | 1.0337 | 0.1510 | 0.00000000 |

## 5. Il modello aggiunge qualcosa al mercato? (encompassing, rolling-origin)

Logistica `esito ~ logit(p_modello) + logit(p_mercato di chiusura)`: stima su 2023/24 (valutazione 2024/25) e su 2023/24+2024/25 (valutazione 2025/26). `ΔLogLoss combo − solo mercato` e' fuori campione, con bootstrap a blocchi.

### OU2.5 — modello `model_produzione` (mercato: `mercato_chiusura_b365`)

| stima su | valuta su | n stima → n val. | β modello (IC 95%) | β mercato (IC 95%) | costante (IC 95%) | ΔLogLoss combo−mercato | IC 95% |
|---|---|---|---|---|---|---|---|
| 2023/24 | 2024/25 | 1752 → 1752 | +0.0674 [-0.3229; +0.4576] | +1.2113 [+0.8546; +1.5680] | +0.0529 [-0.0473; +0.1531] | +0.0014 | [-0.0018; +0.0045] |
| 2023/24, 2024/25 | 2025/26 | 3504 → 1752 | -0.1615 [-0.4329; +0.1098] | +1.2818 [+1.0302; +1.5333] | +0.0299 [-0.0413; +0.1011] | +0.0009 | [-0.0011; +0.0029] |

Dettaglio per lega nella valutazione (LogLoss: mercato / modello / combinazione):

| stima su | valuta su | lega | n | LogLoss mercato | LogLoss modello | LogLoss combo | ΔLogLoss combo−mercato |
|---|---|---|---|---|---|---|---|
| 2023/24 | 2024/25 | Bundesliga | 306 | 0.6369 | 0.6624 | 0.6348 | -0.0020 |
| 2023/24 | 2024/25 | La Liga | 380 | 0.6593 | 0.6755 | 0.6594 | +0.0001 |
| 2023/24 | 2024/25 | Ligue 1 | 306 | 0.6700 | 0.6787 | 0.6703 | +0.0003 |
| 2023/24 | 2024/25 | Premier League | 380 | 0.6768 | 0.6913 | 0.6846 | +0.0078 |
| 2023/24 | 2024/25 | Serie A | 380 | 0.6766 | 0.6944 | 0.6765 | -0.0001 |
| 2023/24, 2024/25 | 2025/26 | Bundesliga | 306 | 0.6382 | 0.6491 | 0.6361 | -0.0020 |
| 2023/24, 2024/25 | 2025/26 | La Liga | 380 | 0.6720 | 0.6858 | 0.6726 | +0.0006 |
| 2023/24, 2024/25 | 2025/26 | Ligue 1 | 306 | 0.6650 | 0.6836 | 0.6639 | -0.0011 |
| 2023/24, 2024/25 | 2025/26 | Premier League | 380 | 0.6842 | 0.6982 | 0.6846 | +0.0004 |
| 2023/24, 2024/25 | 2025/26 | Serie A | 380 | 0.7008 | 0.6917 | 0.7067 | +0.0059 |

### OU2.5 — modello `model_banco_PR34_variante` (mercato: `mercato_chiusura_b365`)

| stima su | valuta su | n stima → n val. | β modello (IC 95%) | β mercato (IC 95%) | costante (IC 95%) | ΔLogLoss combo−mercato | IC 95% |
|---|---|---|---|---|---|---|---|
| 2023/24 | 2024/25 | 1752 → 1752 | +0.1154 [-0.1190; +0.3499] | +1.1442 [+0.8109; +1.4775] | +0.0594 [-0.0413; +0.1602] | +0.0012 | [-0.0020; +0.0043] |
| 2023/24, 2024/25 | 2025/26 | 3504 → 1752 | +0.0649 [-0.1149; +0.2447] | +1.1100 [+0.8709; +1.3490] | +0.0285 [-0.0427; +0.0997] | +0.0009 | [-0.0009; +0.0028] |

Dettaglio per lega nella valutazione (LogLoss: mercato / modello / combinazione):

| stima su | valuta su | lega | n | LogLoss mercato | LogLoss modello | LogLoss combo | ΔLogLoss combo−mercato |
|---|---|---|---|---|---|---|---|
| 2023/24 | 2024/25 | Bundesliga | 306 | 0.6369 | 0.6479 | 0.6337 | -0.0032 |
| 2023/24 | 2024/25 | La Liga | 380 | 0.6593 | 0.6831 | 0.6598 | +0.0006 |
| 2023/24 | 2024/25 | Ligue 1 | 306 | 0.6700 | 0.6893 | 0.6711 | +0.0012 |
| 2023/24 | 2024/25 | Premier League | 380 | 0.6768 | 0.6772 | 0.6827 | +0.0059 |
| 2023/24 | 2024/25 | Serie A | 380 | 0.6766 | 0.6968 | 0.6771 | +0.0005 |
| 2023/24, 2024/25 | 2025/26 | Bundesliga | 306 | 0.6382 | 0.6659 | 0.6360 | -0.0022 |
| 2023/24, 2024/25 | 2025/26 | La Liga | 380 | 0.6720 | 0.6953 | 0.6737 | +0.0018 |
| 2023/24, 2024/25 | 2025/26 | Ligue 1 | 306 | 0.6650 | 0.6904 | 0.6650 | +0.0000 |
| 2023/24, 2024/25 | 2025/26 | Premier League | 380 | 0.6842 | 0.6913 | 0.6846 | +0.0005 |
| 2023/24, 2024/25 | 2025/26 | Serie A | 380 | 0.7008 | 0.7043 | 0.7044 | +0.0036 |

### GG/NG — modello `model_produzione` (mercato: `mercato_gg_oddsportal`)

| stima su | valuta su | n stima → n val. | β modello (IC 95%) | β mercato (IC 95%) | costante (IC 95%) | ΔLogLoss combo−mercato | IC 95% |
|---|---|---|---|---|---|---|---|
| 2023/24 | 2024/25 | 1749 → 1749 | +0.1223 [-0.3891; +0.6336] | +1.2880 [+0.7493; +1.8268] | +0.0877 [-0.0170; +0.1925] | +0.0009 | [-0.0031; +0.0045] |
| 2023/24, 2024/25 | 2025/26 | 3498 → 1751 | -0.1972 [-0.5514; +0.1571] | +1.2954 [+0.9177; +1.6730] | +0.1188 [+0.0439; +0.1936] | +0.0003 | [-0.0027; +0.0032] |

Dettaglio per lega nella valutazione (LogLoss: mercato / modello / combinazione):

| stima su | valuta su | lega | n | LogLoss mercato | LogLoss modello | LogLoss combo | ΔLogLoss combo−mercato |
|---|---|---|---|---|---|---|---|
| 2023/24 | 2024/25 | Bundesliga | 305 | 0.6681 | 0.6740 | 0.6710 | +0.0029 |
| 2023/24 | 2024/25 | La Liga | 380 | 0.6845 | 0.6888 | 0.6811 | -0.0034 |
| 2023/24 | 2024/25 | Ligue 1 | 305 | 0.6803 | 0.6901 | 0.6788 | -0.0015 |
| 2023/24 | 2024/25 | Premier League | 380 | 0.6838 | 0.6856 | 0.6896 | +0.0059 |
| 2023/24 | 2024/25 | Serie A | 379 | 0.6881 | 0.7059 | 0.6888 | +0.0006 |
| 2023/24, 2024/25 | 2025/26 | Bundesliga | 306 | 0.6726 | 0.6706 | 0.6731 | +0.0005 |
| 2023/24, 2024/25 | 2025/26 | La Liga | 380 | 0.6762 | 0.6918 | 0.6683 | -0.0078 |
| 2023/24, 2024/25 | 2025/26 | Ligue 1 | 305 | 0.6858 | 0.6947 | 0.6907 | +0.0048 |
| 2023/24, 2024/25 | 2025/26 | Premier League | 380 | 0.6811 | 0.6889 | 0.6802 | -0.0008 |
| 2023/24, 2024/25 | 2025/26 | Serie A | 380 | 0.6917 | 0.6876 | 0.6975 | +0.0058 |

### GG/NG — modello `model_banco_PR34_variante` (mercato: `mercato_gg_oddsportal`)

| stima su | valuta su | n stima → n val. | β modello (IC 95%) | β mercato (IC 95%) | costante (IC 95%) | ΔLogLoss combo−mercato | IC 95% |
|---|---|---|---|---|---|---|---|
| 2023/24 | 2024/25 | 1749 → 1749 | -0.1012 [-0.3229; +0.1206] | +1.4797 [+1.0468; +1.9126] | +0.0838 [-0.0199; +0.1875] | +0.0022 | [-0.0024; +0.0068] |
| 2023/24, 2024/25 | 2025/26 | 3498 → 1751 | +0.0127 [-0.0748; +0.1001] | +1.1297 [+0.8589; +1.4005] | +0.1081 [+0.0359; +0.1803] | +0.0003 | [-0.0026; +0.0032] |

Dettaglio per lega nella valutazione (LogLoss: mercato / modello / combinazione):

| stima su | valuta su | lega | n | LogLoss mercato | LogLoss modello | LogLoss combo | ΔLogLoss combo−mercato |
|---|---|---|---|---|---|---|---|
| 2023/24 | 2024/25 | Bundesliga | 305 | 0.6681 | 0.7277 | 0.6702 | +0.0020 |
| 2023/24 | 2024/25 | La Liga | 380 | 0.6845 | 0.7030 | 0.6808 | -0.0037 |
| 2023/24 | 2024/25 | Ligue 1 | 305 | 0.6803 | 0.6909 | 0.6889 | +0.0086 |
| 2023/24 | 2024/25 | Premier League | 380 | 0.6838 | 0.6877 | 0.6899 | +0.0061 |
| 2023/24 | 2024/25 | Serie A | 379 | 0.6881 | 0.6984 | 0.6872 | -0.0009 |
| 2023/24, 2024/25 | 2025/26 | Bundesliga | 306 | 0.6726 | 0.7525 | 0.6723 | -0.0003 |
| 2023/24, 2024/25 | 2025/26 | La Liga | 380 | 0.6762 | 0.7022 | 0.6700 | -0.0062 |
| 2023/24, 2024/25 | 2025/26 | Ligue 1 | 305 | 0.6858 | 0.6946 | 0.6914 | +0.0056 |
| 2023/24, 2024/25 | 2025/26 | Premier League | 380 | 0.6811 | 0.6854 | 0.6808 | -0.0003 |
| 2023/24, 2024/25 | 2025/26 | Serie A | 380 | 0.6917 | 0.6913 | 0.6955 | +0.0038 |

## 6. Verdetto (regola fissata a priori, applicata dal codice)

**TETTO RAGGIUNTO** se `resolution(chiusura) − resolution(modello) < 0.002` (pooled) **oppure** se l'IC 95% della differenza include lo zero; **MARGINE ESISTENTE** se la differenza e' >= 0.002 con IC che esclude lo zero.

**Convenzione di segno (da leggere prima della tabella).** `Δ resolution = resolution(mercato di chiusura) − resolution(modello)`: un Δ positivo significa che e' **il mercato** a risolvere meglio, cioe' che il modello sta SOTTO il mercato. Con la regola fissata dalla commessa: `TETTO RAGGIUNTO` = il modello e' a livello del mercato (nessun margine ulteriore ottenibile); `MARGINE ESISTENTE` = il divario fra mercato e modello e' materiale (>= soglia con IC che esclude lo zero). La colonna `lettura speculare` applica la STESSA regola alla differenza nel verso opposto (`modello − mercato`), per rendere esplicito cosa cambia se la commessa intendeva quello: le due letture differiscono solo per l'etichetta, non per i numeri.

| mercato | modello | fonte di mercato | Δ resolution | IC 95% | IC≠0 | verdetto (regola letterale) | lettura speculare | motivo |
|---|---|---|---|---|---|---|---|---|
| OU2.5 | model_produzione | mercato_chiusura_b365 | +0.0048 | [+0.0026; +0.0075] | sì | MARGINE ESISTENTE | TETTO RAGGIUNTO | differenza >= soglia con IC 95% che esclude lo zero |
| OU2.5 | model_banco_PR34 | mercato_chiusura_b365 | +0.0043 | [+0.0018; +0.0069] | sì | MARGINE ESISTENTE | TETTO RAGGIUNTO | differenza >= soglia con IC 95% che esclude lo zero |
| OU2.5 | model_produzione | mercato_chiusura_pinnacle | +0.0061 | [+0.0033; +0.0093] | sì | MARGINE ESISTENTE | TETTO RAGGIUNTO | differenza >= soglia con IC 95% che esclude lo zero |
| GG/NG | model_produzione | mercato_gg_oddsportal | +0.0019 | [+0.0004; +0.0036] | sì | TETTO RAGGIUNTO | TETTO RAGGIUNTO | differenza < soglia |
| GG/NG | model_produzione_banco_GG | mercato_gg_oddsportal | +0.0019 | [+0.0003; +0.0035] | sì | TETTO RAGGIUNTO | TETTO RAGGIUNTO | differenza < soglia |
| GG/NG | model_banco_PR34 | mercato_gg_oddsportal | +0.0013 | [-0.0006; +0.0029] | no | TETTO RAGGIUNTO | TETTO RAGGIUNTO | differenza < soglia |

Ripartizione del margine fra apertura e chiusura (solo dove il verdetto e' MARGINE ESISTENTE; altrimenti la tabella resta come diagnostica fissata a priori):

| mercato | confronto | n | Δ resolution | IC 95% | Δ LogLoss |
|---|---|---|---|---|---|
| OU2.5 | chiusura − apertura (B365) | 3504 | +0.0018 | [+0.0002; +0.0033] | -0.0033 |
| OU2.5 | chiusura − modello (B365) | 3504 | +0.0048 | [+0.0026; +0.0075] | -0.0129 |
| OU2.5 | apertura − modello (B365) | 3504 | +0.0031 | [+0.0012; +0.0054] | -0.0096 |
| GG/NG | NON VERIFICABILE: i file BTTS non hanno quote di apertura/chiusura | - | - | - | - |

**Quanta parte del divario mercato-modello e' gia' nelle aperture (informazione disponibile prima).** Composizione additiva: `Δres(chiusura − modello) = Δres(apertura − modello) + Δres(chiusura − apertura)`.

| mercato | Δres gia' in apertura (B365) | quota del divario totale | Δres solo in chiusura (chiusura − apertura) | quota |
|---|---|---|---|---|
| OU2.5 | +0.0031 | 64% del divario totale | +0.0018 | 36% |
| GG/NG | NON VERIFICABILE | - | - | - |

Per GG/NG la ripartizione apertura/chiusura e' NON VERIFICABILE: i file BTTS hanno un unico snapshot per partita (§1b).

## 7. Conformita' della commessa: esito, comando, evidenza

| punto | esito | comando | evidenza |
|---|---|---|---|
| 0. `git diff origin/main HEAD` vuoto all'inizio | OK | `git diff origin/main HEAD --stat` | nessuna riga: branch allineato a `origin/main` (merge PR #40) |
| 0. venv pulito con `SoccerMath/requirements.txt` + `requirements-audit.txt` | OK | `python -m venv .venv && .venv/bin/pip install -r SoccerMath/requirements.txt -r requirements-audit.txt pytest` | installazione exit 0 (scipy 1.17.1, statsmodels 0.15.0, scikit-learn 1.9.1 come da pin) |
| 0. probabilita' del modello riusate, non riscritte | OK | `from ppda_residual_test import production_totali`; `from backtest_experiment_all import run_walkforward` | §0 del referto: due colonne dichiarate, con controllo incrociato \|engine_gg − walk_forward_gg_predictions\| = 0.121004359231 |
| 1. O/U 2.5: apertura e chiusura B365 + Pinnacle | OK | `python audit/totals_market_ceiling.py` | §1a: B365 apertura e chiusura presenti su tutte le righe; Pinnacle parziale |
| 1. GG/NG da `audit/data/*_btts.json` | OK | `python audit/totals_market_ceiling.py` (join del banco `gg_ng_calibration`) | 5249 righe incrociate su 2023/24-2025/26; bet365 in 5244/5249 righe |
| 1. Apertura/chiusura per GG/NG | NON VERIFICABILE | lettura dei campi `submarket_name`/`period` dei JSON | un solo record per bookmaker, nessun campo temporale, nessun Pinnacle |
| 1. De-vig proporzionale E Shin, decisione sul proporzionale | OK | `python audit/totals_market_ceiling.py` | §2b: entrambi riportati (Brier/LogLoss), la decisione usa il proporzionale |
| 1. Valutazione su 2024/25 e 2025/26, solo modello+quota | OK | `python audit/totals_market_ceiling.py` | §1c/§2: n per lega e per fonte; nessuna imputazione |
| 1. Base rate del train come PR #34 | OK | `from baserate_oos import raw as train_base_rate` | funzione importata: stagioni precedenti a quella valutata, per lega |
| 2. Brier, LogLoss, reliability/resolution/uncertainty, BSS | OK | `from baserate_oos import decomp` (+ verifica `check_ok`) | §2: scomposizione 10 bin identica alla PR #34; la verifica per blocchi riproduce `decomp` a meno di 1e-9 su ogni contrasto |
| 2. Differenze appaiate con bootstrap a blocchi, 2000 repliche, IC 95% | OK | `python audit/totals_market_ceiling.py --reps 2000` | §3: pooled e per lega; blocchi lega x stagione x giornata; seed 20261007 |
| 2. Chiusura contro apertura (stessa fonte, B365) | OK | `python audit/totals_market_ceiling.py` | §3b: Δ resolution(chiusura − apertura) = +0.0018 [+0.0002; +0.0033]; per GG/NG non verificabile |
| 3. Inversione della P(Over) in lambda totale e dispersione di log lambda | OK | `python audit/totals_market_ceiling.py` | §4: inversione esatta; scarto massimo lambda esplicito/invertito per lega riportato |
| 4. Encompassing rolling-origin con IC e ΔLogLoss fuori campione | OK | `python audit/totals_market_ceiling.py` | §5: due fold per entrambe le colonne di modello, coefficienti con IC 95% |
| 4. Colonna del banco PR #34 stimata anche sul 2023/24 | OK | `run_market_value_old` (train = sola 2022/23) | il banco primario parte da 2024/25: per la stima su 2023/24 si usa la variante del banco, dichiarata in §5 e nei limiti |
| 5. Lettura fissata a priori applicata dal codice | OK | `CEILING_EPS = 0.002` + funzione `verdict()` | O/U 2.5 (produzione): MARGINE ESISTENTE; O/U 2.5 (banco PR #34): MARGINE ESISTENTE; GG/NG (produzione): TETTO RAGGIUNTO; GG/NG (banco PR #34): TETTO RAGGIUNTO |
| 6. `git diff --name-only origin/main...HEAD` solo `audit/` | OK | `git diff --name-only origin/main...HEAD` + `git status --porcelain` | file toccati al momento della generazione: `audit/results/totals_market_ceiling.md`, `audit/totals_market_ceiling.py` |
| 6. CI di Audit e Replay su push e pull_request | NON OK sul check `Audit` alla run di pull_request (causa estranea al diff, verificata); OK su `Replay` e sulla run di push | `.github/workflows/topmix_audit.yml`, `.github/workflows/replay_legacy_topmix.yml`; `gh pr checks`; `pytest -q` sugli stessi 18 file del check `Audit` | i due workflow si attivano su push `arena/**` e su pull_request verso `main` (letti dallo script). Il checkout di pull_request fonde con il tip di main (`55b7039 Auto-update live data 2026-10-07T22:20Z`), che contiene l'aggiornamento automatico di `SoccerMath/database/season_rosters.json`; sugli stessi 18 file: questo branch -> 329 passed in 45.89s; tip di origin/main -> 10 failed, 319 passed in 43.96s |

## 8. Limiti e cose non verificabili

- Le quote Over/Under 2.5 arrivano dai CSV football-data del repo: `B365*` e' il prezzo registrato dal provider come apertura, `B365C*`/`PC*` la chiusura. Non c'e' un timestamp della singola quotazione: "apertura" e "chiusura" valgono come etichette del provider, non come istanti verificati nel repo.
- Le quote GG/NG sono un SINGOLO snapshot Oddsportal per partita (un record per bookmaker, nessun campo temporale): per GG/NG il confronto chiusura-contro-apertura e' NON VERIFICABILE e non esiste una fonte Pinnacle. Per le 43 righe senza bet365 usabile il banco GG prende il primo bookmaker disponibile (fallback dichiarato riga per riga).
- La copertura Pinnacle (chiusura) e' parziale nel 2025/26: le metriche di quella fonte sono calcolate sul suo campione (riportato) e le differenze appaiate solo sulle righe in cui la quota esiste.
- Il base rate del train e' calcolato su TUTTE le righe dei CSV delle stagioni precedenti (nessuna esclusione), esattamente come `baserate_oos.raw` nella PR #34.
- La scomposizione di Murphy usa 10 bin di ampiezza uguale su [0,1] e la resolution con riferimento la frequenza media del campione: e' `baserate_oos.decomp`, quindi i valori non sono confrontabili con scomposizioni a bin diversi.
- La giornata non esiste nei CSV football-data: il blocco del bootstrap e' la DATA della partita (stessa scelta dei banchi PR #34 e PR #39), non il turno di campionato.
- La regressione encompassing ha due regressori: non esplora interazioni, non contiene il fattore campo ne' altre fonti, e la combinazione e' stimata senza vincoli (i coefficienti possono essere entrambi positivi per collinearita' fra modello e mercato).
- Il banco PR #34 (`run_walkforward`) non produce previsioni per il 2023/24, stagione richiesta dal protocollo di stima: per quella colonna l'encompassing usa `run_market_value_old` (train = sola 2022/23), dichiarato in §5. La colonna di produzione non ha questo problema: `production_totali` copre tutte le stagioni.
- Le due colonne di modello sono banchi DIFFERENTI con fonti diverse (produzione: xG F_season con shrinkage; banco: medie gol walk-forward): i loro valori non sono sostituibili fra loro e sono riportati separatamente.
- Su 108 righe (le prime giornate di stagione, 2023/24-2025/26) il lookup F_season non e' attivo e i due banchi di produzione divergono: `ppda_residual_test.production_totali` (colonna primaria per O/U e GG) usa il fallback gol, mentre la produzione e `gg_ng_calibration.walk_forward_gg_predictions` usano `att/def` della testa 1X2 (`SoccerMath/app.py`, ramo `else` di `use_fs`). Su GG/NG l'effetto e' misurabile (scarto massimo 0.166, §1d) e la colonna `model_produzione_banco_GG` e' fedele alla produzione; per O/U non esiste un secondo banco fedele, quindi su quelle righe la colonna primaria non e' verificabile contro la produzione: la sensibilita' in §3c le esclude e mostra che i verdetti non cambiano.
- Il check CI `Audit Top Mix` risulta ROSSO sulla run di pull_request e VERDE sulla run di push dello stesso commit. La causa non e' questo diff: il checkout di pull_request fonde con il tip di main, che dopo l'apertura della PR ha ricevuto l'aggiornamento automatico di `SoccerMath/database/season_rosters.json`; sugli stessi 18 file del check, su questo branch i test passano e al tip di main falliscono (dettaglio ed esiti in §7 e §9). Conseguenza: la CI di questa PR resta rossa sul check `Audit` finche' main non torna verde su quel set di test.

## 9. Evidenze: comandi eseguiti e loro output

`git rev-parse HEAD`

```text
db3290d4e5c256a911113dcbda233fba934fbff7
```

`git log -1 --pretty=%s`

```text
audit: referto del confronto Totali modello vs mercato (2000 repliche, seed 20261007)
```

`git status --porcelain`

```text
 M audit/results/totals_market_ceiling.md
 M audit/totals_market_ceiling.py
```

`git diff --name-only origin/main...HEAD  (le sole modifiche di questo branch: confronto dal merge-base)`

```text
audit/results/totals_market_ceiling.md
audit/totals_market_ceiling.py
```

`git diff --stat origin/main...HEAD`

```text
audit/results/totals_market_ceiling.md |  703 ++++++++++++
 audit/totals_market_ceiling.py         | 1907 ++++++++++++++++++++++++++++++++
 2 files changed, 2610 insertions(+)
```

`git diff --name-only origin/main HEAD  (due punti: include anche i commit che main ha ricevuto DOPO il merge-base, non attribuibili a questo branch)`

```text
SoccerMath/database/season_rosters.json
audit/results/totals_market_ceiling.md
audit/totals_market_ceiling.py
```

`python -V`

```text
Python 3.11.2
```

`versioni pacchetti`

```text
numpy 2.4.6; pandas 3.0.6; scipy 1.17.1; statsmodels 0.15.0; streamlit 1.65.0; scikit-learn 1.9.1
```

`pytest -q sui test dei banchi riusati`

```text
......................................................................   [100%]
70 passed in 4.81s
```

`git log -1 --oneline origin/main`

```text
55b7039 Auto-update live data 2026-10-07T22:20Z
```

`pytest -q sui 18 file del check CI 'Audit Top Mix' (questo branch)`

```text
329 passed in 45.89s
```

`pytest -q sugli stessi 18 file in un worktree al tip di origin/main`

```text
10 failed, 319 passed in 43.96s
```

`python audit/totals_market_ceiling.py`

```text
[    0.0s] cornice O/U: production_totali + run_walkforward + variante + quote …
[  286.1s]   righe 7334; stagioni ['2022/23', '2023/24', '2024/25', '2025/26', '2026/27']
[  286.1s] cornice GG/NG: join Oddsportal + walk-forward di produzione …
[  311.1s]   righe incrociate 5249
[  311.1s] sonda F_season: su quali giornate la fonte non e' attiva (ramo divergente) …
[  321.7s]   coppie (stagione, giornata) con F_season non attiva: 57
[  322.1s] metriche per fonte …
[  322.2s] de-vig Shin …
[  322.3s] bootstrap a blocchi (differenze appaiate) …
[  323.2s] dispersione dei lambda …
[  323.3s] regressione encompassing …
[  323.5s] verdetti …
[  323.5s] sensibilita': senza le righe con F_season non attiva …
(sezione rigenerata dopo il commit: i numeri del referto NON sono stati ricalcolati)
(sezione rigenerata dopo il commit: i numeri del referto NON sono stati ricalcolati)
(sezione rigenerata dopo il commit: i numeri del referto NON sono stati ricalcolati)
(sezione rigenerata dopo il commit: i numeri del referto NON sono stati ricalcolati)
(sezione rigenerata dopo il commit: i numeri del referto NON sono stati ricalcolati)
```

## 10. Output pesanti (non versionati)

- `audit/output/totals_market_ceiling_rows.csv`: 12583 righe partita per partita (tutte le fonti e le quote)
- `audit/output/totals_market_ceiling.json`: payload completo di questa esecuzione

## 11. Sintesi in chiusura (le tabelle richieste dalla commessa)

### 11a. Resolution e BSS per fonte e mercato (pooled)

| mercato | fonte | n | resolution | reliability | BSS Brier | BSS LogLoss |
|---|---|---|---|---|---|---|
| OU2.5 | model_produzione | 3504 | 0.004706 | 0.000944 | +0.0084 | +0.0062 |
| OU2.5 | model_banco_PR34 | 3504 | 0.005212 | 0.003161 | +0.0028 | +0.0020 |
| OU2.5 | mercato_apertura_b365 | 3504 | 0.007779 | 0.000185 | +0.0272 | +0.0202 |
| OU2.5 | mercato_chiusura_b365 | 3504 | 0.009544 | 0.000495 | +0.0337 | +0.0250 |
| OU2.5 | mercato_chiusura_pinnacle | 2624 | 0.009989 | 0.000862 | +0.0335 | +0.0246 |
| GG/NG | model_produzione | 3500 | 0.001447 | 0.000783 | -0.0007 | -0.0006 |
| GG/NG | model_produzione_banco_GG | 3500 | 0.001520 | 0.000874 | -0.0010 | -0.0008 |
| GG/NG | model_banco_PR34 | 3500 | 0.002041 | 0.003678 | -0.0076 | -0.0209 |
| GG/NG | mercato_btts_oddsportal | 3500 | 0.003383 | 0.000447 | +0.0125 | +0.0091 |

### 11b. Differenze di resolution con IC 95% (chiusura di mercato − modello, pooled)

| mercato | fonte di mercato | modello | Δ resolution | IC 95% | Δ LogLoss | verdetto |
|---|---|---|---|---|---|---|
| OU2.5 | mercato_chiusura_b365 | model_produzione | +0.0048 | [+0.0026; +0.0075] | -0.0129 | MARGINE ESISTENTE |
| OU2.5 | mercato_chiusura_b365 | model_banco_PR34 | +0.0043 | [+0.0018; +0.0069] | -0.0158 | MARGINE ESISTENTE |
| OU2.5 | mercato_chiusura_pinnacle | model_produzione | +0.0061 | [+0.0033; +0.0093] | -0.0147 | MARGINE ESISTENTE |
| GG/NG | mercato_gg_oddsportal | model_produzione | +0.0019 | [+0.0004; +0.0036] | -0.0066 | TETTO RAGGIUNTO |
| GG/NG | mercato_gg_oddsportal | model_produzione_banco_GG | +0.0019 | [+0.0003; +0.0035] | -0.0068 | TETTO RAGGIUNTO |
| GG/NG | mercato_gg_oddsportal | model_banco_PR34 | +0.0013 | [-0.0006; +0.0029] | -0.0207 | TETTO RAGGIUNTO |

### 11c. Dispersione dei lambda (log λ, per lega)

| lega | n | media log λ mercato | sd log λ mercato | media log λ modello | sd log λ modello | rapporto sd |
|---|---|---|---|---|---|---|
| Bundesliga | 612 | 1.1287 | 0.1339 | 1.1522 | 0.1064 | 1.259 |
| La Liga | 760 | 0.9474 | 0.1826 | 0.9394 | 0.1361 | 1.341 |
| Ligue 1 | 612 | 1.0506 | 0.1265 | 1.0259 | 0.1033 | 1.225 |
| Premier League | 760 | 1.0791 | 0.1157 | 1.0973 | 0.0983 | 1.176 |
| Serie A | 760 | 0.9316 | 0.1148 | 0.9395 | 0.1055 | 1.088 |

### 11d. Coefficienti encompassing (chiusura, pooled sulla finestra di valutazione)

| mercato | modello | stima su | valuta su | β modello (IC 95%) | β mercato (IC 95%) | ΔLogLoss combo−mercato | IC 95% |
|---|---|---|---|---|---|---|---|
| OU2.5 | model_produzione | 2023/24 | 2024/25 | 0.067 [-0.323; +0.458] | 1.211 [+0.855; +1.568] | +0.0014 | [-0.0018; +0.0045] |
| OU2.5 | model_produzione | 2023/24+2024/25 | 2025/26 | -0.162 [-0.433; +0.110] | 1.282 [+1.030; +1.533] | +0.0009 | [-0.0011; +0.0029] |
| OU2.5 | model_banco_PR34_variante | 2023/24 | 2024/25 | 0.115 [-0.119; +0.350] | 1.144 [+0.811; +1.478] | +0.0012 | [-0.0020; +0.0043] |
| OU2.5 | model_banco_PR34_variante | 2023/24+2024/25 | 2025/26 | 0.065 [-0.115; +0.245] | 1.110 [+0.871; +1.349] | +0.0009 | [-0.0009; +0.0028] |
| GG/NG | model_produzione | 2023/24 | 2024/25 | 0.122 [-0.389; +0.634] | 1.288 [+0.749; +1.827] | +0.0009 | [-0.0031; +0.0045] |
| GG/NG | model_produzione | 2023/24+2024/25 | 2025/26 | -0.197 [-0.551; +0.157] | 1.295 [+0.918; +1.673] | +0.0003 | [-0.0027; +0.0032] |
| GG/NG | model_banco_PR34_variante | 2023/24 | 2024/25 | -0.101 [-0.323; +0.121] | 1.480 [+1.047; +1.913] | +0.0022 | [-0.0024; +0.0068] |
| GG/NG | model_banco_PR34_variante | 2023/24+2024/25 | 2025/26 | 0.013 [-0.075; +0.100] | 1.130 [+0.859; +1.400] | +0.0003 | [-0.0026; +0.0032] |

### 11e. Verdetto per mercato (colonna di produzione; banchi secondari in §6)

| mercato | Δ resolution (chiusura − modello) | IC 95% | verdetto |
|---|---|---|---|
| OU2.5 | +0.0048 | [+0.0026; +0.0075] | MARGINE ESISTENTE |
| GG/NG | +0.0019 | [+0.0004; +0.0036] | TETTO RAGGIUNTO |

### 11f. Verdetto di processo

| controllo | esito | comando | evidenza |
|---|---|---|---|
| nessuna modifica a `SoccerMath/` | OK | `git status --porcelain` + `git diff --name-only` | `audit/results/totals_market_ceiling.md`, `audit/totals_market_ceiling.py` |
| diff confinato ad `audit/` | OK | `git diff --name-only origin/main HEAD` | nessun file fuori da `audit/` |
| test dei banchi riusati | OK | `pytest -q` sui 5 file di test dei banchi | 70 passed in 4.81s |

**Verdetto di processo: MERGEABLE** — il contributo tocca solo `audit/`, non modifica `SoccerMath/` e i test dei banchi riusati passano; referto e script sono riproducibili con `python audit/totals_market_ceiling.py`. Avvertenza: il check CI `Audit Top Mix` resta rosso sulla run di pull_request per il motivo documentato in §7 e §8 (merge con il tip di main, non con questo diff), mentre `Replay Top Mix legacy` e la run di push dello stesso commit sono verdi.

