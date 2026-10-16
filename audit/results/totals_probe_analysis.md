# Sonda The Odds API — mercato totals (audit, offline)

Generato da `audit/totals_probe_analysis.py` il 2026-10-16T13:20:26Z a partire da 5 snapshot in `/home/runner/work/SoccerMath2.0/SoccerMath2.0/audit/data/totals_probe/2026-10-16_1320`. Nessuna chiamata di rete, nessuna chiave.

## 1. Crediti spesi

| lega (sport_key) | x-requests-last (crediti della chiamata) |
|---|---|
| soccer_epl | 1 |
| soccer_france_ligue_one | 1 |
| soccer_germany_bundesliga | 1 |
| soccer_italy_serie_a | 1 |
| soccer_spain_la_liga | 1 |

**Crediti spesi: 5.** Ultimo stato del conto: used=103, remaining=397.

Lo stato finale e' quello dell'**ultima chiamata in ordine di tempo** (`soccer_france_ligue_one` alle 2026-10-16T13:20:26Z), NON dell'ultima lega in ordine alfabetico: le due cose coincidono solo per caso. Ordine delle chiamate:

| # | sport_key | fetched_at_utc | x-requests-used | x-requests-remaining |
|---|---|---|---|---|
| 1 | soccer_italy_serie_a | 2026-10-16T13:20:26Z | 99 | 401 |
| 2 | soccer_epl | 2026-10-16T13:20:26Z | 100 | 400 |
| 3 | soccer_spain_la_liga | 2026-10-16T13:20:26Z | 101 | 399 |
| 4 | soccer_germany_bundesliga | 2026-10-16T13:20:26Z | 102 | 398 |
| 5 | soccer_france_ligue_one | 2026-10-16T13:20:26Z | 103 | 397 |

## 2. Eventi e Pinnacle

| lega | file | status | eventi |
|---|---|---|---|
| Premier League | soccer_epl.json | 200 | 20 |
| Ligue 1 | soccer_france_ligue_one.json | 200 | 18 |
| Bundesliga | soccer_germany_bundesliga.json | 200 | 18 |
| Serie A | soccer_italy_serie_a.json | 200 | 20 |
| La Liga | soccer_spain_la_liga.json | 200 | 21 |

- Eventi totali: **97**.
- Eventi con **Pinnacle** sul mercato totals: **97** (100.0 %).

## 3. Linee per bookmaker (una linea per libro e per evento)

| bookmaker | eventi con totals | linea 2,5 | linea 2,25 | linea 2,75 | linea altre |
|---|---|---|---|---|---|
| marathonbet | 97 | 62 | 0 | 0 | 35 |
| onexbet | 97 | 64 | 0 | 0 | 33 |
| williamhill | 97 | 97 | 0 | 0 | 0 |
| tipico_de | 97 | 59 | 0 | 0 | 38 |
| pinnacle | 97 | 16 | 9 | 26 | 46 |
| leovegas_se | 97 | 65 | 0 | 0 | 32 |
| unibet_nl | 97 | 65 | 0 | 0 | 32 |
| unibet_se | 97 | 65 | 0 | 0 | 32 |
| pmu_fr | 97 | 65 | 0 | 0 | 32 |
| nordicbet | 86 | 86 | 0 | 0 | 0 |
| betsson | 86 | 86 | 0 | 0 | 0 |
| codere_it | 48 | 31 | 0 | 0 | 17 |
| betonlineag | 48 | 16 | 0 | 0 | 32 |
| coolbet | 48 | 15 | 0 | 0 | 33 |
| gtbets | 38 | 26 | 0 | 0 | 12 |
| matchbook | 23 | 14 | 0 | 0 | 9 |
| mybookieag | 20 | 15 | 0 | 0 | 5 |
| betanysports | 20 | 9 | 0 | 0 | 11 |

## 4. Eventi con linea 2,5 e linee asiatiche

| misura | eventi |
|---|---|
| con una linea 2,5 da almeno un bookmaker | 97 |
| con una linea 2,5 da Pinnacle | 16 |
| con SOLO linee asiatiche (2,25 / 2,75), nessuna 2,5 | 0 |
| con almeno una linea asiatica (candidati alla sensibilita') | 35 |

## 5. Trattamento delle linee asiatiche

Decisione dichiarata in `audit/totals_probe_analysis.py` (prima dei dati): **esclusione** nel confronto principale; la conversione e' solo sensibilita', non implementata. Motivo: una linea 2,25/2,75 e' una combinazione di mezze puntate su linee vicine con rimborso parziale. Per convertirla in P(Over 2,5) bisogna assumere come il libro prezza le due meta': non e' un dato osservato.

## 6. Limiti

- Una linea per libro e per evento: se un libro offre piu' linee nello stesso evento se ne tiene la piu' bassa.
- La sonda misura la DISPONIBILITA' delle linee, non le quote Over/Under: le quote sono nel corpo grezzo e non vengono usate qui.
- L'ora della rilevazione e' quella della chiamata (`fetched_at_utc`), non l'ora di chiusura del mercato.
