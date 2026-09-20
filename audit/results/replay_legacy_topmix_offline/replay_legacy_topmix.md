# Replay walk-forward Top Mix, due modelli (no-leakage)

Generato: 2026-09-20T19:35:20Z · finestra 2026-09-18 → 2026-09-20 · fixture: `csv` · ref snapshot: `origin/main` · modelli scritti: **Attuale + Legacy**

**Leak check complessivo: OK** · **finestra dichiarata ricostruibile: OK** · click simulati: 10 (scrivibili: 10) · righe destinate al Registro: 9 Attuale + 8 Legacy

Registro: {"scritto": false, "motivo": "dry-run offline, registro locale"}

- nota: finestra richiesta 2026-09-18 → 2026-09-20, limiti a istante [2026-09-18T21:51:58Z, +∞); primo istante onesto ricostruibile dal repo: 2026-08-30 (commit 48e7768, il primo con la stagione 2026/27 nei CSV live; prima di allora in git c'e' un'altra stagione)
- nota: 26 fixture del pool con giornata dedotta dalle righe CSV vicine (offline)
- nota: 1496 fixture senza giornata: escluse dal pool da select_next_matchday_matches

## Click simulati

| T (UTC) | snapshot | commit time | bersagli | pool | selez. | sopra soglia att/leg | righe attuale | righe legacy | leak |
|---|---|---|---|---|---|---|---|---|---|
| 2026-09-19T11:29:59Z | `d95efb3a4098` | 2026-09-19T01:50:40Z | Tottenham-Aston Villa (Premier League, 2-3) | 1545 | 38 | 15/14 | — | — | OK (+1 righe future scartate) |
| 2026-09-19T11:59:59Z | `d95efb3a4098` | 2026-09-19T01:50:40Z | Osasuna-Vallecano (La Liga, 1-1) | 1544 | 37 | 15/14 | — | — | OK (+1 righe future scartate) |
| 2026-09-19T12:59:59Z | `d95efb3a4098` | 2026-09-19T01:50:40Z | Paris-Strasbourg (Ligue 1, 2-1)<br>Toulouse-Le Havre (Ligue 1, 3-2)<br>Angers-Troyes (Ligue 1, 2-0)<br>Le Mans-Lorient (Ligue 1, 2-1)<br>Lyon-Rennes (Ligue 1, 4-0)<br>Udinese-Cagliari (Serie A, 0-1)<br>Bologna-Torino (Serie A, 1-1) | 1543 | 36 | 15/14 | Bologna-Torino UNDER_2.5 61.2% rank 13 ✅ | Bologna-Torino UNDER_2.5 61.2% rank 12 ✅ | OK (+1 righe future scartate) |
| 2026-09-19T13:29:59Z | `d95efb3a4098` | 2026-09-19T01:50:40Z | M'gladbach-Mainz (Bundesliga, 3-4)<br>Ein Frankfurt-Freiburg (Bundesliga, 2-2)<br>Hamburg-Koln (Bundesliga, 2-1)<br>Werder Bremen-Augsburg (Bundesliga, 3-2) | 1534 | 27 | 13/12 | Borussia Mönchengladbach-Mainz GG 62.1% rank 9 ✅<br>Werder Bremen-Augsburg GG 61.5% rank 11 ✅<br>Hamburg-Koln GG 60.7% rank 12 ✅ | Borussia Mönchengladbach-Mainz GG 62.1% rank 8 ✅<br>Werder Bremen-Augsburg GG 61.5% rank 10 ✅<br>Hamburg-Koln GG 60.7% rank 11 ✅ | OK (+1 righe future scartate) |
| 2026-09-19T13:59:59Z | `d95efb3a4098` | 2026-09-19T01:50:40Z | Newcastle-Hull City (Premier League, 2-1)<br>Brighton-Arsenal (Premier League, 3-0)<br>Everton-Ipswich (Premier League, 1-0) | 1530 | 23 | 10/9 | Brighton-Arsenal GG 63.2% rank 6 ❌ | Brighton-Arsenal GG 63.2% rank 6 ❌ | OK (+1 righe future scartate) |
| 2026-09-19T14:14:59Z | `d95efb3a4098` | 2026-09-19T01:50:40Z | Ath Bilbao-Alaves (La Liga, 0-0) | 1525 | 18 | 8/7 | — | — | OK (+1 righe future scartate) |
| 2026-09-19T15:59:59Z | `660ba48888fd` | 2026-09-19T14:54:25Z | Roma-Inter (Serie A, 2-2) | 1524 | 17 | 8/7 | — | — | OK (+1 righe future scartate) |
| 2026-09-19T16:29:59Z | `660ba48888fd` | 2026-09-19T14:54:25Z | Stuttgart-Dortmund (Bundesliga, 0-1)<br>Celta-Santander (La Liga, 5-0)<br>Nott'm Forest-Coventry City (Premier League, 0-1) | 1523 | 16 | 8/7 | Stuttgart-Dortmund GG 68.0% rank 4 ❌<br>Nottingham Forest-Coventry City 1 58.8% rank 8 ❌ | Stuttgart-Dortmund GG 68.0% rank 2 ❌ | OK (+1 righe future scartate) |
| 2026-09-19T18:44:59Z | `660ba48888fd` | 2026-09-19T14:54:25Z | Venezia-Lazio (Serie A, 0-2) | 1520 | 13 | 6/6 | Venezia-Lazio 2 62.3% rank 5 ✅ | Venezia-Lazio 2 57.5% rank 6 ✅ | OK (+1 righe future scartate) |
| 2026-09-19T18:59:59Z | `660ba48888fd` | 2026-09-19T14:54:25Z | Sevilla-Barcelona (La Liga, 1-3) | 1519 | 12 | 5/5 | Sevilla-Barcelona 2 72.3% rank 1 ✅ | Sevilla-Barcelona 2 64.4% rank 3 ✅ | OK (+1 righe future scartate) |

## Tabella leakage per click

| T | commit < T | bersaglio assente dal CSV | bersaglio assente da xG | cutoff xG = T | snapshot della stagione | righe future scartate | dettagli |
|---|---|---|---|---|---|---|---|
| 2026-09-19T11:29:59Z | True | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-19T11:59:59Z | True | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-19T12:59:59Z | True | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-19T13:29:59Z | True | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-19T13:59:59Z | True | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-19T14:14:59Z | True | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-19T15:59:59Z | True | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-19T16:29:59Z | True | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-19T18:44:59Z | True | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-19T18:59:59Z | True | True | True | True | True | {"LaLiga_Live.csv": 1} | — |

## Righe del modello attuale (Attuale) destinate al Registro

| data | lega | partita | mercato | prob | rank | esito | risultato | snapshot | salvato_il |
|---|---|---|---|---|---|---|---|---|---|
| 19/09/2026 15:00 | Serie A | Bologna-Torino | UNDER_2.5 | 61.2% | 13 | ✅ | 1-1 | `d95efb3a4098` | 19/09/2026 14:59 |
| 19/09/2026 15:30 | Bundesliga | Borussia Mönchengladbach-Mainz | GG | 62.1% | 9 | ✅ | 3-4 | `d95efb3a4098` | 19/09/2026 15:29 |
| 19/09/2026 15:30 | Bundesliga | Werder Bremen-Augsburg | GG | 61.5% | 11 | ✅ | 3-2 | `d95efb3a4098` | 19/09/2026 15:29 |
| 19/09/2026 15:30 | Bundesliga | Hamburg-Koln | GG | 60.7% | 12 | ✅ | 2-1 | `d95efb3a4098` | 19/09/2026 15:29 |
| 19/09/2026 16:00 | Premier League | Brighton-Arsenal | GG | 63.2% | 6 | ❌ | 3-0 | `d95efb3a4098` | 19/09/2026 15:59 |
| 19/09/2026 18:30 | Bundesliga | Stuttgart-Dortmund | GG | 68.0% | 4 | ❌ | 0-1 | `660ba48888fd` | 19/09/2026 18:29 |
| 19/09/2026 18:30 | Premier League | Nottingham Forest-Coventry City | 1 | 58.8% | 8 | ❌ | 0-1 | `660ba48888fd` | 19/09/2026 18:29 |
| 19/09/2026 20:45 | Serie A | Venezia-Lazio | 2 | 62.3% | 5 | ✅ | 0-2 | `660ba48888fd` | 19/09/2026 20:44 |
| 19/09/2026 21:00 | La Liga | Sevilla-Barcelona | 2 | 72.3% | 1 | ✅ | 1-3 | `660ba48888fd` | 19/09/2026 20:59 |

## Righe del modello legacy (Legacy) destinate al Registro

| data | lega | partita | mercato | prob | rank | esito | risultato | snapshot | salvato_il |
|---|---|---|---|---|---|---|---|---|---|
| 19/09/2026 15:00 | Serie A | Bologna-Torino | UNDER_2.5 | 61.2% | 12 | ✅ | 1-1 | `d95efb3a4098` | 19/09/2026 14:59 |
| 19/09/2026 15:30 | Bundesliga | Borussia Mönchengladbach-Mainz | GG | 62.1% | 8 | ✅ | 3-4 | `d95efb3a4098` | 19/09/2026 15:29 |
| 19/09/2026 15:30 | Bundesliga | Werder Bremen-Augsburg | GG | 61.5% | 10 | ✅ | 3-2 | `d95efb3a4098` | 19/09/2026 15:29 |
| 19/09/2026 15:30 | Bundesliga | Hamburg-Koln | GG | 60.7% | 11 | ✅ | 2-1 | `d95efb3a4098` | 19/09/2026 15:29 |
| 19/09/2026 16:00 | Premier League | Brighton-Arsenal | GG | 63.2% | 6 | ❌ | 3-0 | `d95efb3a4098` | 19/09/2026 15:59 |
| 19/09/2026 18:30 | Bundesliga | Stuttgart-Dortmund | GG | 68.0% | 2 | ❌ | 0-1 | `660ba48888fd` | 19/09/2026 18:29 |
| 19/09/2026 20:45 | Serie A | Venezia-Lazio | 2 | 57.5% | 6 | ✅ | 0-2 | `660ba48888fd` | 19/09/2026 20:44 |
| 19/09/2026 21:00 | La Liga | Sevilla-Barcelona | 2 | 64.4% | 3 | ✅ | 1-3 | `660ba48888fd` | 19/09/2026 20:59 |

## Copertura per modello (stesso campione?)

```
Copertura Top Mix nel periodo 2026-09-18 → 2026-09-20:
- modello Attuale: 9 partite (9 righe)
- modello Legacy: 8 partite (8 righe)
- partite con ENTRAMBI i modelli: 8
- solo modello Attuale: 1 partite
    · Nottingham Forest - Coventry City (Premier League, 19/09/2026 18:30) 1 58.8% ❌
- i due campioni NON coincidono: le partite mancanti sono quelle sotto le soglie del selettore (0,55 1X2 / 0,60 Totali) o scartate dal veto di disaccordo per QUEL modello
```
