# Replay A vs B del selettore Top Mix — risultati numerici

*Generato*: 2026-09-05T19:45:48+00:00 · *commit codice*: `eead43cc7318`

> **Etichetta dei dati.** validation storica GIA' ESAMINATA (2024/25 e 2025/26 sono state usate per scegliere due teste, forma fuori dai totali, shrinkage PRIOR_MATCHES=6 e per confermare i pesi 0.6/0.4): NON e' un test intatto.
> Non e' un hold-out. Nessuna soglia e' stata cercata o cambiata in questo giro: 0.55 / 0.60 / 0.25 e pesi 0.6/0.4 sono quelli di `fetch_and_calc_top_mix`. Nessun `--apply`, nessuna scrittura sul registro, nessuna chiamata JSONBin, nessun merge in produzione.

## 0. Perimetro effettivo

- Leghe: Serie A, Premier League, La Liga, Bundesliga, Ligue 1
- Stagioni: 2024/25, 2025/26
- Giornate ricostruite: **384**
- Partite in calendario nelle stagioni replicate: **3504**
- Partite candidate (dopo `select_next_matchday_matches`): **3422**
- Partite mai candidate (recuperi fuori finestra o giocati mentre la giornata successiva era gia' aperta): **82**
- Partite della giornata escluse dalla finestra di round (`TOP_MIX_ROUND_WINDOW_DAYS=5`): **87**
- Righe duplicate scartate (una sola per `match_id`): 0

## 1. Frequenza di disaccordo sul mercato

Due letture: (a) sulle partite che **entrambi** mostrano, quante volte il mercato scelto e' diverso; (b) su tutte le candidate, quante volte cio' che B mostrerebbe e' diverso dall'argmax Poisson di A (include le partite che A scarta del tutto).

| Lega | Candidate | Ammesse A | Ammesse B | Entrambi ammessi | Mercato diverso (a) | Freq. (a) | Mercato diverso (b) | Freq. (b) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bundesliga | 603 | 419 | 459 | 419 | 29 | 6.9% | 69 | 11.4% |
| La Liga | 723 | 380 | 398 | 380 | 4 | 1.1% | 22 | 3.0% |
| Ligue 1 | 610 | 281 | 312 | 281 | 8 | 2.8% | 39 | 6.4% |
| Premier League | 742 | 422 | 473 | 422 | 23 | 5.5% | 74 | 10.0% |
| Serie A | 744 | 363 | 378 | 363 | 10 | 2.8% | 25 | 3.4% |
| **AGGREGATO** | 3422 | 1865 | 2020 | 1865 | 74 | 4.0% | 229 | 6.7% |

| Stagione | Candidate | Ammesse A | Ammesse B | Mercato diverso | Freq. disaccordo (su entrambi) |
|---|---:|---:|---:|---:|---:|
| 2024/25 | 1732 | 935 | 1024 | 43 | 4.6% |
| 2025/26 | 1690 | 930 | 996 | 31 | 3.3% |

## 2. Partite in disaccordo: hit rate e Brier sull'evento scelto da ciascuno

Ogni selettore e' valutato sull'evento che ha selezionato lui, con la probabilita' che avrebbe mostrato (`confidence`).

| Lega | n | prob media A | hit A | Brier A | prob media B | hit B | Brier B | ΔBrier (A−B) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bundesliga | 29 | 62.1% | 62.1% | 0.2238 | 65.7% | 51.7% | 0.2701 | -0.0463 |
| La Liga | 4 | 59.8% | 100.0% | 0.1632 | 64.4% | 75.0% | 0.1961 | -0.0329 |
| Ligue 1 | 8 | 60.1% | 50.0% | 0.2773 | 63.3% | 50.0% | 0.2720 | 0.0053 |
| Premier League | 23 | 62.1% | 69.6% | 0.2138 | 64.5% | 56.5% | 0.2501 | -0.0363 |
| Serie A | 10 | 59.4% | 70.0% | 0.2190 | 62.9% | 70.0% | 0.2158 | 0.0032 |
| **AGGREGATO** | 74 | 61.4% | 66.2% | 0.2225 | 64.6% | 56.8% | 0.2528 | -0.0302 |

| Stagione | n | hit A | Brier A | hit B | Brier B | ΔBrier (A−B) |
|---|---:|---:|---:|---:|---:|---:|
| 2024/25 | 43 | 79.1% | 0.1977 | 58.1% | 0.2512 | -0.0535 |
| 2025/26 | 31 | 48.4% | 0.2570 | 54.8% | 0.2549 | 0.0021 |

Incertezza (bootstrap a blocchi, blocco = giornata, coppie appaiate):

- ΔBrier A−B = -0.0302 (IC95% -0.0725 … 0.0108, 65 blocchi)
- Δhit rate A−B = 0.0946 (IC95% -0.0667 … 0.2533)

Su tutte le partite ammesse da entrambi (n = 1865): ΔBrier A−B = -0.0012 (IC95% -0.0029 … 0.0003), Δhit = 0.0038 (IC95% -0.0022 … 0.0099).

## 3. Partite scartate da A e accettate da B (e viceversa)

| Lega | Scartate da A / accettate da B | Scartate da B / accettate da A | prob media B (recuperate) | hit B | Brier B |
|---|---:|---:|---:|---:|---:|
| Bundesliga | 40 | 0 | 65.3% | 70.0% | 0.2128 |
| La Liga | 18 | 0 | 61.3% | 55.6% | 0.2595 |
| Ligue 1 | 31 | 0 | 61.7% | 67.7% | 0.2288 |
| Premier League | 51 | 0 | 62.5% | 49.0% | 0.2644 |
| Serie A | 15 | 0 | 60.6% | 66.7% | 0.2087 |
| **AGGREGATO** | 155 | 0 | 62.7% | 60.6% | 0.2380 |

Motivo per cui A aveva scartato l'intera partita (aggregato):

- A: disaccordo Elo >= 0.25: **94**
- A: confidence sotto soglia: **50**
- A: confidence sotto soglia + disaccordo Elo: **11**

Mercato con cui B recupera la partita (aggregato):

- O2.5: **85**
- 1: **39**
- GG: **18**
- 2: **8**
- U2.5: **4**
- NG: **1**

Nota: Per costruzione dev'essere 0: il mercato scelto da A e' valutato da B con la stessa formula, quindi se passa i filtri per A passa anche per B. Il replay lo conferma empiricamente (0 casi).

Esempi (prime 10 per confidence di B) del caso descritto: il mercato migliore veniva buttato via perche' il primo scelto non passava i filtri.

| Lega | Stagione | G. | Partita | Risultato | A: mercato | A: conf | A: disacc. Elo | B: mercato | B: conf | B: esito |
|---|---|---:|---|---|---|---:|---:|---|---:|---:|
| Bundesliga | 2024/25 | 33 | Bayern Munich - M'gladbach | 2-0 | 1 | 84.9% | 0.265 | O2.5 | 78.6% | no |
| Bundesliga | 2024/25 | 18 | Bayern Munich - Wolfsburg | 3-2 | 1 | 81.1% | 0.313 | O2.5 | 73.1% | sì |
| Bundesliga | 2024/25 | 30 | Dortmund - M'gladbach | 3-2 | 1 | 67.0% | 0.312 | O2.5 | 71.7% | sì |
| La Liga | 2024/25 | 25 | Las Palmas - Barcelona | 0-2 | 2 | 77.1% | 0.382 | O2.5 | 71.5% | no |
| Premier League | 2025/26 | 12 | Burnley - Chelsea | 0-2 | 2 | 71.3% | 0.393 | O2.5 | 71.5% | no |
| Premier League | 2024/25 | 25 | Southampton - Bournemouth | 1-3 | 2 | 74.8% | 0.265 | O2.5 | 71.2% | sì |
| Ligue 1 | 2024/25 | 20 | Brest - Paris SG | 2-5 | 2 | 67.5% | 0.319 | O2.5 | 71.1% | sì |
| Bundesliga | 2025/26 | 11 | RB Leipzig - Werder Bremen | 2-0 | 1 | 65.0% | 0.274 | O2.5 | 71.1% | no |
| Bundesliga | 2025/26 | 22 | Werder Bremen - Bayern Munich | 0-3 | 2 | 78.0% | 0.257 | O2.5 | 71.0% | sì |
| Bundesliga | 2024/25 | 21 | Bayern Munich - Werder Bremen | 3-0 | 1 | 83.1% | 0.282 | O2.5 | 70.4% | sì |

## 4. Copertura

| Lega | Giornate | Candidate/giornata | Ammesse A/giornata | Ammesse B/giornata | Giornate con 0 righe A | con 0 righe B |
|---|---:|---:|---:|---:|---:|---:|
| Bundesliga | 68 | 8.87 | 6.16 | 6.75 | 0 | 0 |
| La Liga | 75 | 9.64 | 5.07 | 5.31 | 0 | 0 |
| Ligue 1 | 68 | 8.97 | 4.13 | 4.59 | 0 | 0 |
| Premier League | 75 | 9.89 | 5.63 | 6.31 | 0 | 0 |
| Serie A | 76 | 9.79 | 4.78 | 4.97 | 0 | 0 |
| **AGGREGATO** | 362 | 9.45 | 5.15 | 5.58 | 0 | 0 |

Copertura sulle candidate: A 54.5% (1865/3422), B 59.0% (2020/3422).

Pool globale + taglio a 10 (settimana ISO del cutoff, 5 leghe insieme, taglio a 10, 74 pool):

| Selettore | righe | slot medi riempiti | prob media | hit rate | Brier |
|---|---:|---:|---:|---:|---:|
| A | 740 | 10.00 | 73.2% | 71.8% | 0.2013 |
| B | 740 | 10.00 | 73.4% | 72.0% | 0.2010 |

Bootstrap a blocchi sul pool (74 weekend, delta non appaiato): ΔBrier A−B = 0.0004 (IC95% -0.0041 … 0.0048), Δhit = -0.0027 (IC95% -0.0149 … 0.0095).

Tutte le righe che ciascun selettore mostrerebbe (insiemi di dimensione diversa, confronto non appaiato):

| Lega | n righe A | hit A | Brier A | n righe B | hit B | Brier B |
|---|---:|---:|---:|---:|---:|---:|
| Bundesliga | 419 | 63.7% | 0.2284 | 459 | 63.6% | 0.2299 |
| La Liga | 380 | 64.7% | 0.2159 | 398 | 64.1% | 0.2182 |
| Ligue 1 | 281 | 61.2% | 0.2355 | 312 | 61.9% | 0.2347 |
| Premier League | 422 | 59.7% | 0.2387 | 473 | 57.9% | 0.2432 |
| Serie A | 363 | 60.3% | 0.2383 | 378 | 60.6% | 0.2370 |
| **AGGREGATO** | 1865 | 62.0% | 0.2312 | 2020 | 61.5% | 0.2328 |

## 5. Composizione per mercato (conteggi)

| Insieme | 1 | X | 2 | O2.5 | U2.5 | GG | NG |
|---|---|---|---|---|---|---|---|
| A (pre-filtri, argmax Poisson) | 985 | 0 | 564 | 163 | 705 | 998 | 7 |
| A (mostrate) | 806 | 0 | 318 | 132 | 235 | 372 | 2 |
| B (mostrate) | 814 | 0 | 303 | 255 | 244 | 400 | 4 |

Top 10: A 1=455/B 1=439, A X=0/B X=0, A 2=110/B 2=107, A O2.5=72/B O2.5=111, A U2.5=45/B U2.5=37, A GG=58/B GG=46, A NG=0/B NG=0

## 6. Baseline: calibrazione dei sette mercati prima di qualsiasi selettore

Probabilita' Poisson di produzione su TUTTE le partite candidate (nessuna selezione): serve a distinguere un difetto del modello da un effetto dell'ordine di selezione (protocollo §5).

| Mercato | n | prob media | frequenza reale | gap | Brier |
|---|---:|---:|---:|---:|---:|
| 1 | 3422 | 43.7% | 43.0% | 0.007 | 0.2190 |
| X | 3422 | 22.1% | 25.2% | -0.031 | 0.1880 |
| 2 | 3422 | 34.2% | 31.8% | 0.024 | 0.1955 |
| O2.5 | 3422 | 53.0% | 53.3% | -0.003 | 0.2448 |
| U2.5 | 3422 | 47.0% | 46.7% | 0.003 | 0.2448 |
| GG | 3422 | 53.9% | 54.6% | -0.006 | 0.2476 |
| NG | 3422 | 46.1% | 45.4% | 0.006 | 0.2476 |

## 7. Affidabilita' per bucket sull'evento selezionato

| Bucket | n A | prob media A | hit A | n B | prob media B | hit B |
|---|---:|---:|---:|---:|---:|---:|
| [0.55,0.60) | 226 | 57.4% | 52.7% | 238 | 57.3% | 51.7% |
| [0.60,0.65) | 779 | 62.2% | 56.0% | 865 | 62.2% | 56.1% |
| [0.65,0.70) | 399 | 67.2% | 65.4% | 442 | 67.2% | 64.7% |
| [0.70,0.75) | 191 | 72.4% | 67.5% | 203 | 72.4% | 68.0% |
| [0.75,0.80) | 145 | 77.3% | 75.2% | 147 | 77.3% | 74.1% |
| [0.80,0.85) | 71 | 82.1% | 83.1% | 71 | 82.1% | 83.1% |
| [0.85,0.90) | 46 | 87.2% | 78.3% | 46 | 87.2% | 78.3% |
| [0.90,1.01) | 8 | 91.4% | 87.5% | 8 | 91.4% | 87.5% |

## 8. Dettaglio per lega e stagione

| Lega / stagione | Cand. | A amm. | B amm. | disacc. | hit A | Brier A | hit B | Brier B |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bundesliga | 2024/25 | 306 | 203 | 224 | 14 | 78.6% | 0.1901 | 35.7% | 0.3236 |
| Bundesliga | 2025/26 | 297 | 216 | 235 | 15 | 46.7% | 0.2552 | 66.7% | 0.2201 |
| La Liga | 2024/25 | 367 | 190 | 204 | 2 | 100.0% | 0.1960 | 100.0% | 0.1439 |
| La Liga | 2025/26 | 356 | 190 | 194 | 2 | 100.0% | 0.1305 | 50.0% | 0.2484 |
| Ligue 1 | 2024/25 | 306 | 127 | 145 | 2 | 50.0% | 0.2862 | 50.0% | 0.2899 |
| Ligue 1 | 2025/26 | 304 | 154 | 167 | 6 | 50.0% | 0.2744 | 50.0% | 0.2661 |
| Premier League | 2024/25 | 375 | 223 | 251 | 18 | 77.8% | 0.1973 | 66.7% | 0.2181 |
| Premier League | 2025/26 | 367 | 199 | 222 | 5 | 40.0% | 0.2730 | 20.0% | 0.3654 |
| Serie A | 2024/25 | 378 | 192 | 200 | 7 | 85.7% | 0.1891 | 71.4% | 0.2112 |
| Serie A | 2025/26 | 366 | 171 | 178 | 3 | 33.3% | 0.2888 | 66.7% | 0.2265 |

## 9. Limiti dichiarati (protocollo §6)

- Nessuno snapshot dello stato TIMED/SCHEDULED dell'API: i candidati sono le partite della giornata ricostruita dai CSV, non il feed del click.
- `matchday` non esiste nei CSV football-data.co.uk: e' ricostruito come n-esima partita di ciascuna squadra (max fra casa e trasferta). Sui recuperi differisce dalla numerazione ufficiale. Identico per A e per B.
- I nomi passati a `clean_name` sono quelli dei CSV, non gli `shortName` dell'API football-data.org.
- `MARKET_VALUES` e' statico e non versionato per stagione: applicato al 2024/25 e al 2025/26 e' leakage gia' dichiarato. Identico per A e per B.
- Gli xG di Understat vengono rivisti: l'archivio conserva l'ultimo valore, quindi il cutoff esclude le partite del giorno ma non le revisioni.
- Gli orari dei CSV sono trattati come UTC (fuso reale non dichiarato nel dato).
- La forma a 5 partite e' calcolata sul df multi-stagione, come in produzione: per una neopromossa include partite di stagioni precedenti.
- Il pool del taglio a 10 e' la settimana ISO del cutoff, non il pool live delle 5 leghe al momento del click.
- Elo non persistito: e' ricalcolato dai CSV troncati al cutoff.
