# Sonda The Odds API — dettaglio per lega (mercato totals, audit offline)

Generato da `audit/totals_probe_per_lega.py` il 2026-10-10T17:11:51Z dagli snapshot di `audit/data/totals_probe/`. Nessuna chiamata di rete, nessuna chiave.

## Regola dichiarata (prima dei dati)

Totals entra in produzione solo se **almeno il 85 %** degli eventi ha la linea **2,5 da Pinnacle** oppure **da almeno 3 bookmaker** (linea 2,5 esatta sul mercato totals).

## Crediti e residui

| lega | sport_key | crediti chiamata (x-requests-last) | residui (x-requests-remaining) |
|---|---|---|---|
| Premier League | soccer_epl | 1 | 440 |
| Ligue 1 | soccer_france_ligue_one | 1 | 437 |
| Bundesliga | soccer_germany_bundesliga | 1 | 438 |
| Serie A | soccer_italy_serie_a | 1 | 441 |
| La Liga | soccer_spain_la_liga | 1 | 439 |

Crediti spesi nel run: **5** (una chiamata per lega, 5 chiamate).

## Eventi, Pinnacle e linee 2,5

| lega | eventi | con Pinnacle | Pinnacle: 2,5 | Pinnacle: altra intera/mezza | Pinnacle: asiatica | 2,5 da ≥1 libro | 2,5 da ≥3 libri | regola soddisfatta | quota regola |
|---|---|---|---|---|---|---|---|---|---|
| Premier League | 17 | 15 | 4 | 7 | 4 | 16 | 13 | 13 | 76.5 % |
| Ligue 1 | 17 | 17 | 3 | 5 | 9 | 16 | 13 | 13 | 76.5 % |
| Bundesliga | 12 | 12 | 0 | 8 | 4 | 11 | 2 | 2 | 16.7 % |
| Serie A | 19 | 19 | 4 | 4 | 11 | 18 | 16 | 16 | 84.2 % |
| La Liga | 17 | 17 | 3 | 2 | 12 | 16 | 12 | 12 | 70.6 % |
| **totale** | **82** | **80** | **14** | **26** | **40** | **77** | **56** | **56** | **68.3 %** |

Pinnacle: la linea considerata è quella del libro più vicina a 2,5 (se ne offre più d'una). «Intera o mezza (altra)» = linee x,0 o x,5 diverse da 2,5; «asiatica» = quarti x,25 / x,75.

## Esito della regola

Eventi che soddisfano la regola: **56 / 82 = 68.3 %** (soglia 85 %). Esito: **NON superata**. Per lega: vedi colonna «quota regola».

Eventi con linee multiple dello stesso libro nello stesso evento: 0 (contati a livello evento).

