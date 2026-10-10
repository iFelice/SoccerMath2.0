## 3. Punto 3 — diagnosi della sonda totals (sui file grezzi, offline)

Generato da `audit/totals_probe_diagnosi.py` il 2026-10-10T19:25:30Z dai 5 snapshot grezzi in `audit/data/totals_probe/`. Nessuna chiamata di rete, nessuna chiave, nessuna nuova richiesta a The Odds API.

Eventi totali: **82** · superano la regola: **56** (68,3 %) · non la superano: **26** (31,7 %). Soglia dell'85 %: **NON superata** (come in PR #59). Solo descrittivo: nessuna conseguenza sul codice.

### 3.1 I 26 eventi che non superano la regola, per causa

Causa assegnata per priorità (D2): C1 Pinnacle assente → C2 Pinnacle con linea ≠ 2,5 → C3 Pinnacle 2,5 con meno di 3 libri → C4 altro. Poiché la regola è un OR, tutti i 26 hanno anche meno di 3 libri con la 2,5: il conteggio per numero di libri è sotto.

| causa | eventi |
|---|---|
| C1 Pinnacle assente | 2 |
| C2 Pinnacle con linea 1,5 | 1 |
| C2 Pinnacle con linea 3,5 | 5 |
| C2 Pinnacle con linea a quarti | 12 |
| C2 Pinnacle con linea altra mezza | 2 |
| C2 Pinnacle con linea intera | 4 |

| lega | eventi | superano la regola | non la superano | C1 Pinnacle assente | C2 Pinnacle con linea 1,5 | C2 Pinnacle con linea 3,5 | C2 Pinnacle con linea a quarti | C2 Pinnacle con linea altra mezza | C2 Pinnacle con linea intera |
|---|---|---|---|---|---|---|---|---|---|
| Premier League | 17 | 13 | 4 | 2 | 0 | 1 | 0 | 0 | 1 |
| Ligue 1 | 17 | 13 | 4 | 0 | 1 | 0 | 3 | 0 | 0 |
| Bundesliga | 12 | 2 | 10 | 0 | 0 | 3 | 3 | 2 | 2 |
| Serie A | 19 | 16 | 3 | 0 | 0 | 0 | 2 | 0 | 1 |
| La Liga | 17 | 12 | 5 | 0 | 0 | 1 | 4 | 0 | 0 |
| **totale** | 82 | 56 | 26 | 2 | 1 | 5 | 12 | 2 | 4 |

#### 3.1.1 Linea di Pinnacle nei 26 eventi (quando presente)

| linea Pinnacle | eventi |
|---|---|
| 1,5 | 1 |
| 3,5 | 5 |
| a quarti | 12 |
| altra mezza | 2 |
| assente | 2 |
| intera | 4 |

Valori esatti della linea Pinnacle nei 26 eventi: **1.5** × 1, **3.0** × 4, **3.25** × 6, **3.5** × 5, **3.75** × 5, **4.5** × 2, **4.75** × 1.

#### 3.1.2 Quanti libri offrono la 2,5 nei 26 eventi

| libri con la linea 2,5 | eventi |
|---|---|
| 0 | 5 |
| 1 | 0 |
| 2 | 21 |

C3 è vuota **per costruzione**: se Pinnacle ha la 2,5 la regola è soddisfatta, quindi un evento che non la supera non può avere Pinnacle a 2,5.

### 3.2 Giorni mancanti al calcio d'inizio al momento della chiamata

| misura | giorni |
|---|---|
| n | 82 |
| minimo | -0,08 |
| p10 | 0,07 |
| p25 | 0,92 |
| mediana | 6,85 |
| p75 | 7,83 |
| p90 | 8,07 |
| massimo | 13,98 |
| media | 4,97 |

| fascia di giorni mancanti | eventi | quota |
|---|---|---|
| < 0 (già iniziata) | 5 | 6,1 % |
| [0-1) | 20 | 24,4 % |
| [1-2) | 4 | 4,9 % |
| [2-7) | 24 | 29,3 % |
| [7-14) | 29 | 35,4 % |
| ≥ 14 | 0 | 0,0 % |

| lega | eventi | minimo | mediana | massimo |
|---|---|---|---|---|
| Premier League | 17 | -0,02 | 6,87 | 13,98 |
| Ligue 1 | 17 | -0,08 | 6,07 | 8,07 |
| Bundesliga | 12 | -0,02 | 6,85 | 7,93 |
| Serie A | 19 | -0,04 | 6,07 | 9,07 |
| La Liga | 17 | -0,02 | 6,79 | 9,08 |

### 3.3 Stessa classificazione separata: entro 7 giorni e oltre 7 giorni

| gruppo | eventi | superano la regola | quota | non la superano |
|---|---|---|---|---|
| entro 7 giorni | 53 | 32 | 60,4 % | 21 |
| oltre 7 giorni | 29 | 24 | 82,8 % | 5 |
| **tutti** | 82 | 56 | 68,3 % | 26 |

Causa degli eventi che non superano la regola, nei due gruppi:

| gruppo | non superano | C1 Pinnacle assente | C2 Pinnacle con linea 1,5 | C2 Pinnacle con linea 3,5 | C2 Pinnacle con linea a quarti | C2 Pinnacle con linea altra mezza | C2 Pinnacle con linea intera |
|---|---|---|---|---|---|---|---|
| entro 7 giorni | 21 | 0 | 1 | 3 | 11 | 2 | 4 |
| oltre 7 giorni | 5 | 2 | 0 | 2 | 1 | 0 | 0 |

«Entro 7 giorni» = giorni mancanti ≤ 7 (comprese le partite gia' iniziate al momento della chiamata); «oltre 7 giorni» = giorni mancanti > 7. Lettura solo descrittiva: la quota dell'85 % non e' raggiunta in nessuno dei due gruppi.

### 3.4 Costo reale della sonda in crediti (dagli header)

| # (ordine di tempo) | sport_key | fetched_at_utc | x-requests-last (costo) | x-requests-used | x-requests-remaining | eventi |
|---|---|---|---|---|---|---|
| 1 | soccer_italy_serie_a | 2026-10-10T17:03:43Z | 1 | 59 | 441 | 19 |
| 2 | soccer_epl | 2026-10-10T17:03:43Z | 1 | 60 | 440 | 17 |
| 3 | soccer_spain_la_liga | 2026-10-10T17:03:43Z | 1 | 61 | 439 | 17 |
| 4 | soccer_germany_bundesliga | 2026-10-10T17:03:44Z | 1 | 62 | 438 | 12 |
| 5 | soccer_france_ligue_one | 2026-10-10T17:03:44Z | 1 | 63 | 437 | 17 |

**Crediti spesi nel run: 5** (una chiamata per lega, 5 chiamate). Stato finale (ultima chiamata in ordine di tempo, `soccer_france_ligue_one` alle 2026-10-10T17:03:44Z): **used = 63, remaining = 437**. Stato prima del run (prima chiamata, `soccer_italy_serie_a`): used = 59, remaining = 441.

**Correzione dello stato finale.** `audit/results/totals_probe_analysis.md` riporta «used=61, remaining=439»: è lo stato della chiamata `soccer_spain_la_liga`, l'ULTIMA LEGA IN ORDINE ALFABETICO, non l'ultima chiamata in ordine di tempo. Con la chiave (`fetched_at_utc`, `x-requests-used`) l'ultima chiamata è `soccer_france_ligue_one` (usati 63, residui 437). La correzione è stata applicata in `audit/totals_probe_analysis.py` (funzione `ordine_cronologico` + scelta dello stato finale) e in `audit/totals_probe.py` (stato finale preso per max della stessa chiave, non dall'ultima lega del ciclo). Il numero di crediti spesi (5) non cambia: cambia lo stato del conto attribuito al run.

### 3.5 Limiti

- La sonda misura la DISPONIBILITÀ delle linee totals, non le quote Over/Under: le quote sono nel corpo grezzo e qui non sono state usate (solo nel punto 4, per il confronto fra griglie).
- Una linea per libro e per evento: se un libro offre più linee se ne tiene la più bassa, come in `totals_probe_analysis.py`.
- L'ora della chiamata è `fetched_at_utc` (risoluzione 1 secondo): i giorni mancanti hanno quindi un'incertezza dell'ordine del secondo, irrilevante sulle fasce usate.
- Lo snapshot è unico (2026-10-10): la relazione fra giorni mancanti e disponibilità della 2,5 è misurata su 82 eventi di una sola giornata tipo ed è descrittiva, non una stampa di un effetto.

