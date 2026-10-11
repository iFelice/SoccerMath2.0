# Ricalcolo descrittivo dello snapshot 10/10 senza gli eventi già iniziati

## Regola dichiarata (prima dei numeri; questa sezione non viene modificata dopo)

Un evento è **già iniziato alla chiamata** se `commence_time` ≤ istante della
chiamata della sua lega (stessa regola della produzione per le quote 1X2).
Gli eventi già iniziati sono esclusi dal ricalcolo e contati a parte.

Questo referto è **solo descrittivo**: gli esiti dichiarati nelle PR #59 e
PR #60 **non cambiano**. Per ciascun esito dichiarato si riporta se lo snapshot
del 10/10 era **contaminato** (i suoi conteggi includevano eventi già iniziati).

Si ricalcolano senza gli eventi iniziati, con le regole originali invariate:
la copertura della regola dell'85 % e la classificazione delle cause (PR #59,
regole D1/D2) e il numero di eventi confrontabili con mediana e massimo della
differenza assoluta su P(Over 2,5) fra le due griglie (PR #60, regole P4.1/P4.2).

Generato da `audit/totals_probe_senza_avviati.py` il 2026-10-11T21:28:08Z dallo snapshot reale `/home/user/SoccerMath2.0/audit/data/totals_probe/2026-10-10_1703` (sola lettura). Nessuna rete, nessuna chiamata a The Odds API, nessuna modifica a `SoccerMath/`.

## 1. Eventi già iniziati alla chiamata

Eventi totali dello snapshot: **82**. Già iniziati (`commence_time` ≤ istante della chiamata): **5**.

| lega | partita | calcio d'inizio (UTC) | giorni mancanti |
|---|---|---|---:|
| Premier League | Manchester United – Tottenham Hotspur | 2026-10-10T16:30:00Z | -0,0234 |
| Ligue 1 | Lille – Le Havre | 2026-10-10T15:14:00Z | -0,0762 |
| Bundesliga | RB Leipzig – Eintracht Frankfurt | 2026-10-10T16:30:00Z | -0,0234 |
| Serie A | Inter Milan – Parma | 2026-10-10T16:00:00Z | -0,0442 |
| La Liga | Barcelona – Getafe | 2026-10-10T16:33:00Z | -0,0213 |

## 2. PR #59 ricalcolata senza gli eventi iniziati (descrittivo)

Regola D1 invariata: un evento la supera se Pinnacle ha la linea 2,5 OPPURE almeno 3 bookmaker hanno la linea 2,5. Regola D2 invariata per la classificazione delle cause.

| voce | originale (82 eventi) | senza eventi iniziati |
|---|---:|---:|
| eventi | 82 | 77 |
| superano la regola | 56 | 55 |
| non la superano | 26 | 22 |
| copertura della regola | 68,3 % | 71,4 % |

| causa (D2) | originale | senza eventi iniziati |
|---|---:|---:|
| C1 Pinnacle assente | 2 | 2 |
| C2 Pinnacle con linea 1,5 | 1 | 0 |
| C2 Pinnacle con linea 3,5 | 5 | 5 |
| C2 Pinnacle con linea a quarti | 12 | 10 |
| C2 Pinnacle con linea altra mezza | 2 | 1 |
| C2 Pinnacle con linea intera | 4 | 4 |

Soglia dell'85 %: **non raggiunta** in entrambi i conteggi (68,3 % e 71,4 %). L'esito dichiarato nella PR #59 resta «NON superata».

## 3. PR #60 ricalcolata senza gli eventi iniziati (descrittivo)

Regole P4.1/P4.2 invariate: evento confrontabile se Pinnacle ha una linea ≠ 2,5 e almeno 3 ALTRI bookmaker hanno la 2,5; si confronta P(Over 2,5) delle due griglie (fit generalizzato, differenza assoluta).

| voce | originale | senza eventi iniziati |
|---|---:|---:|
| eventi confrontabili | 42 | 41 |
| mediana di Δ P(Over 2,5) (valore assoluto) | 0,64 pt | 0,54 pt |
| massimo di Δ P(Over 2,5) (valore assoluto) | 4,54 pt | 3,38 pt |

Eventi confrontabili che erano già iniziati (esclusi dal ricalcolo):

| partita | giorni mancanti | Δ P(Over 2,5) (pt) |
|---|---:|---:|
| Manchester United – Tottenham Hotspur | -0,0234 | 4,54 pt |

## 4. Esiti dichiarati nelle PR #59 e #60 e contaminazione

Gli esiti dichiarati **non cambiano**: qui sotto restano quelli già pubblicati, con accanto se lo snapshot del 10/10 era contaminato.

| esito dichiarato | fonte | snapshot contaminato | ricalcolo senza eventi iniziati |
|---|---|---|---|
| Regola dell'85 %: **NON superata** (56/82 = 68,3 %) | PR #59 §3 | **SÌ** (includeva 5 eventi iniziati) | copertura 71,4 % (55/77): esito invariato |
| 26 eventi non superano la regola, classificati per causa (C1 = 2, C2 varie) | PR #59 §3.1 | **SÌ** | 22 eventi, cause nella tabella §2 |
| 82 eventi, 77 con terna 1X2 Pinnacle, **42 confrontabili** | PR #60 §4.2 | **SÌ** | 41 confrontabili |
| Differenza su P(Over 2,5): mediana 0,64 pt, massimo 4,54 pt | PR #60 §4.2 | **SÌ** | mediana 0,54 pt, massimo 3,38 pt |
| P4.4: **NON utilizzabile** (mediana ≤ 1,5 pt; massimo 4,54 pt > 4 pt) | PR #60 §4.2 | **SÌ** (il massimo era l'evento iniziato Man Utd–Tottenham) | esito invariato: la regola P4.4 resta come dichiarata |
| 77 eventi con linea totals utilizzabile (entro 7 giorni: 53 eventi, 51 utilizzabili) | PR #60 §4.3 | **SÌ** | non ricalcolato: è un conteggio di disponibilità, non dei quattro numeri oggetto di questo punto |

## 5. Limiti

- Solo descrittivo: nessun esito delle PR #59/#60 è riassegnato e nessuna regola è rivalutata su questo snapshot.
- Lo snapshot resta unico (10/10/2026): i ricalcoli sono sensibilità, non stime di effetto.
- La terna 1X2 usata dalla PR #60 è di 8 ore prima della sonda totals: il disallineamento temporale resta anche senza gli eventi iniziati.
- `commence_time` assente o corrotto non viene classificato come iniziato (come in produzione).
