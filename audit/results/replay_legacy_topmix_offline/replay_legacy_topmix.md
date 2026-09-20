# Replay walk-forward Top Mix legacy (no-leakage)

Generato: 2026-09-20T15:08:00Z · finestra 2026-09-18 → 2026-09-20 · fixture: `csv` · ref snapshot: `origin/main`

**Leak check complessivo: OK** · click simulati: 14 · righe legacy candidate: 10 · righe current equivalenti (NON scritte): 11

Registro: {"scritto": false, "motivo": "dry-run offline, registro locale"}

- nota: 1 partite con kickoff incerto (mezzanotte UTC del giorno CSV, piu' conservativo): Monaco-Lens
- nota: 26 fixture del pool con giornata dedotta dalle righe CSV vicine (offline)
- nota: 1496 fixture senza giornata: escluse dal pool da select_next_matchday_matches

## Click simulati

| T (UTC) | snapshot | commit time | bersagli | pool | selez. | sopra soglia cur/leg | righe legacy persistite | leak |
|---|---|---|---|---|---|---|---|---|
| 2026-09-17T23:59:59Z | `d446f2480d7c` | 2026-09-17T20:37:51Z | Monaco-Lens (Ligue 1, 2-1) | 1550 | 43 | 18/17 | — | OK |
| 2026-09-18T18:29:59Z | `5039d0f746fc` | 2026-09-18T15:17:03Z | Bayern-Union Berlin (Bundesliga, 7-0) | 1549 | 42 | 17/16 | Bayern-Union Berlin 1 86.2% rank 1 ✅ | OK (+1 righe future scartate) |
| 2026-09-18T18:44:59Z | `5039d0f746fc` | 2026-09-18T15:17:03Z | Monza-Sassuolo (Serie A, 2-1) | 1548 | 41 | 16/15 | — | OK (+1 righe future scartate) |
| 2026-09-18T18:59:59Z | `5039d0f746fc` | 2026-09-18T15:17:03Z | Espanol-Elche (La Liga, 1-3)<br>Brentford-Chelsea (Premier League, 3-0) | 1547 | 40 | 16/15 | Brentford-Chelsea GG 65.3% rank 4 ❌ | OK (+1 righe future scartate) |
| 2026-09-19T11:29:59Z | `d95efb3a4098` | 2026-09-19T01:50:40Z | Tottenham-Aston Villa (Premier League, 2-3) | 1545 | 38 | 15/14 | — | OK (+1 righe future scartate) |
| 2026-09-19T11:59:59Z | `d95efb3a4098` | 2026-09-19T01:50:40Z | Osasuna-Vallecano (La Liga, 1-1) | 1544 | 37 | 15/14 | — | OK (+1 righe future scartate) |
| 2026-09-19T12:59:59Z | `d95efb3a4098` | 2026-09-19T01:50:40Z | Paris-Strasbourg (Ligue 1, 2-1)<br>Toulouse-Le Havre (Ligue 1, 3-2)<br>Angers-Troyes (Ligue 1, 2-0)<br>Le Mans-Lorient (Ligue 1, 2-1)<br>Lyon-Rennes (Ligue 1, 4-0)<br>Udinese-Cagliari (Serie A, 0-1)<br>Bologna-Torino (Serie A, 1-1) | 1543 | 36 | 15/14 | Bologna-Torino UNDER_2.5 61.2% rank 12 ✅ | OK (+1 righe future scartate) |
| 2026-09-19T13:29:59Z | `d95efb3a4098` | 2026-09-19T01:50:40Z | M'gladbach-Mainz (Bundesliga, 3-4)<br>Ein Frankfurt-Freiburg (Bundesliga, 2-2)<br>Hamburg-Koln (Bundesliga, 2-1)<br>Werder Bremen-Augsburg (Bundesliga, 3-2) | 1534 | 27 | 13/12 | Borussia Mönchengladbach-Mainz GG 62.1% rank 8 ✅<br>Werder Bremen-Augsburg GG 61.5% rank 10 ✅<br>Hamburg-Koln GG 60.7% rank 11 ✅ | OK (+1 righe future scartate) |
| 2026-09-19T13:59:59Z | `d95efb3a4098` | 2026-09-19T01:50:40Z | Newcastle-Hull City (Premier League, 2-1)<br>Brighton-Arsenal (Premier League, 3-0)<br>Everton-Ipswich (Premier League, 1-0) | 1530 | 23 | 10/9 | Brighton-Arsenal GG 63.2% rank 6 ❌ | OK (+1 righe future scartate) |
| 2026-09-19T14:14:59Z | `d95efb3a4098` | 2026-09-19T01:50:40Z | Ath Bilbao-Alaves (La Liga, 0-0) | 1525 | 18 | 8/7 | — | OK (+1 righe future scartate) |
| 2026-09-19T15:59:59Z | `660ba48888fd` | 2026-09-19T14:54:25Z | Roma-Inter (Serie A, 2-2) | 1524 | 17 | 8/7 | — | OK (+1 righe future scartate) |
| 2026-09-19T16:29:59Z | `660ba48888fd` | 2026-09-19T14:54:25Z | Stuttgart-Dortmund (Bundesliga, 0-1)<br>Celta-Santander (La Liga, 5-0)<br>Nott'm Forest-Coventry City (Premier League, 0-1) | 1523 | 16 | 8/7 | Stuttgart-Dortmund GG 68.0% rank 2 ❌ | OK (+1 righe future scartate) |
| 2026-09-19T18:44:59Z | `660ba48888fd` | 2026-09-19T14:54:25Z | Venezia-Lazio (Serie A, 0-2) | 1520 | 13 | 6/6 | Venezia-Lazio 2 57.5% rank 6 ✅ | OK (+1 righe future scartate) |
| 2026-09-19T18:59:59Z | `660ba48888fd` | 2026-09-19T14:54:25Z | Sevilla-Barcelona (La Liga, 1-3) | 1519 | 12 | 5/5 | Sevilla-Barcelona 2 64.4% rank 3 ✅ | OK (+1 righe future scartate) |

## Tabella leakage per click

| T | commit < T | bersaglio assente dal CSV | bersaglio assente da xG | cutoff xG = T | righe future scartate | dettagli |
|---|---|---|---|---|---|---|
| 2026-09-17T23:59:59Z | True | True | True | True | — | — |
| 2026-09-18T18:29:59Z | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-18T18:44:59Z | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-18T18:59:59Z | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-19T11:29:59Z | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-19T11:59:59Z | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-19T12:59:59Z | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-19T13:29:59Z | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-19T13:59:59Z | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-19T14:14:59Z | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-19T15:59:59Z | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-19T16:29:59Z | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-19T18:44:59Z | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-19T18:59:59Z | True | True | True | True | {"LaLiga_Live.csv": 1} | — |

## Righe legacy candidate

| data | lega | partita | mercato | prob | rank | esito | risultato | snapshot | salvato_il |
|---|---|---|---|---|---|---|---|---|---|
| 18/09/2026 20:30 | Bundesliga | Bayern-Union Berlin | 1 | 86.2% | 1 | ✅ | 7-0 | `5039d0f746fc` | 18/09/2026 20:29 |
| 18/09/2026 21:00 | Premier League | Brentford-Chelsea | GG | 65.3% | 4 | ❌ | 3-0 | `5039d0f746fc` | 18/09/2026 20:59 |
| 19/09/2026 15:00 | Serie A | Bologna-Torino | UNDER_2.5 | 61.2% | 12 | ✅ | 1-1 | `d95efb3a4098` | 19/09/2026 14:59 |
| 19/09/2026 15:30 | Bundesliga | Borussia Mönchengladbach-Mainz | GG | 62.1% | 8 | ✅ | 3-4 | `d95efb3a4098` | 19/09/2026 15:29 |
| 19/09/2026 15:30 | Bundesliga | Werder Bremen-Augsburg | GG | 61.5% | 10 | ✅ | 3-2 | `d95efb3a4098` | 19/09/2026 15:29 |
| 19/09/2026 15:30 | Bundesliga | Hamburg-Koln | GG | 60.7% | 11 | ✅ | 2-1 | `d95efb3a4098` | 19/09/2026 15:29 |
| 19/09/2026 16:00 | Premier League | Brighton-Arsenal | GG | 63.2% | 6 | ❌ | 3-0 | `d95efb3a4098` | 19/09/2026 15:59 |
| 19/09/2026 18:30 | Bundesliga | Stuttgart-Dortmund | GG | 68.0% | 2 | ❌ | 0-1 | `660ba48888fd` | 19/09/2026 18:29 |
| 19/09/2026 20:45 | Serie A | Venezia-Lazio | 2 | 57.5% | 6 | ✅ | 0-2 | `660ba48888fd` | 19/09/2026 20:44 |
| 19/09/2026 21:00 | La Liga | Sevilla-Barcelona | 2 | 64.4% | 3 | ✅ | 1-3 | `660ba48888fd` | 19/09/2026 20:59 |
