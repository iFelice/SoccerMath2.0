# Sonda The Odds API — mercato totals (audit, offline)

Generato da `audit/totals_probe_analysis.py` il 2026-10-10T17:03:44Z a partire da 5 snapshot in `audit/data/totals_probe/`. Nessuna chiamata di rete, nessuna chiave.

## 1. Crediti spesi

| lega (sport_key) | x-requests-last (crediti della chiamata) |
|---|---|
| soccer_epl | 1 |
| soccer_france_ligue_one | 1 |
| soccer_germany_bundesliga | 1 |
| soccer_italy_serie_a | 1 |
| soccer_spain_la_liga | 1 |

**Crediti spesi: 5.** Ultimo stato del conto: used=61, remaining=439.

## 2. Eventi e Pinnacle

| lega | file | status | eventi |
|---|---|---|---|
| Premier League | soccer_epl.json | 200 | 17 |
| Ligue 1 | soccer_france_ligue_one.json | 200 | 17 |
| Bundesliga | soccer_germany_bundesliga.json | 200 | 12 |
| Serie A | soccer_italy_serie_a.json | 200 | 19 |
| La Liga | soccer_spain_la_liga.json | 200 | 17 |

- Eventi totali: **82**.
- Eventi con **Pinnacle** sul mercato totals: **80** (97.6 %).

## 3. Linee per bookmaker (una linea per libro e per evento)

| bookmaker | eventi con totals | linea 2,5 | linea 2,25 | linea 2,75 | linea altre |
|---|---|---|---|---|---|
| tipico_de | 80 | 50 | 0 | 0 | 30 |
| pinnacle | 80 | 14 | 6 | 22 | 38 |
| pmu_fr | 80 | 55 | 0 | 0 | 25 |
| leovegas_se | 80 | 56 | 0 | 0 | 24 |
| unibet_se | 80 | 56 | 0 | 0 | 24 |
| unibet_nl | 80 | 55 | 0 | 0 | 25 |
| nordicbet | 79 | 74 | 0 | 0 | 5 |
| onexbet | 77 | 55 | 0 | 0 | 22 |
| williamhill | 75 | 75 | 0 | 0 | 0 |
| codere_it | 72 | 49 | 0 | 0 | 23 |
| matchbook | 36 | 20 | 0 | 0 | 16 |
| coolbet | 32 | 13 | 0 | 0 | 19 |
| betonlineag | 27 | 13 | 0 | 0 | 14 |
| gtbets | 24 | 17 | 0 | 0 | 7 |
| mybookieag | 17 | 14 | 0 | 0 | 3 |
| betanysports | 12 | 6 | 1 | 0 | 5 |

## 4. Eventi con linea 2,5 e linee asiatiche

| misura | eventi |
|---|---|
| con una linea 2,5 da almeno un bookmaker | 77 |
| con una linea 2,5 da Pinnacle | 14 |
| con SOLO linee asiatiche (2,25 / 2,75), nessuna 2,5 | 0 |
| con almeno una linea asiatica (candidati alla sensibilita') | 28 |

## 5. Trattamento delle linee asiatiche

Decisione dichiarata in `audit/totals_probe_analysis.py` (prima dei dati): **esclusione** nel confronto principale; la conversione e' solo sensibilita', non implementata. Motivo: una linea 2,25/2,75 e' una combinazione di mezze puntate su linee vicine con rimborso parziale. Per convertirla in P(Over 2,5) bisogna assumere come il libro prezza le due meta': non e' un dato osservato.

## 6. Limiti

- Una linea per libro e per evento: se un libro offre piu' linee nello stesso evento se ne tiene la piu' bassa.
- La sonda misura la DISPONIBILITA' delle linee, non le quote Over/Under: le quote sono nel corpo grezzo e non vengono usate qui.
- L'ora della rilevazione e' quella della chiamata (`fetched_at_utc`), non l'ora di chiusura del mercato.
