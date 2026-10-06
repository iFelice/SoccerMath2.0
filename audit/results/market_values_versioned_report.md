# MARKET_VALUES versionato per stagione — impatto sul 1X2 (audit sola lettura)

*Generato: 2026-10-06T21:31:42+00:00 — script `audit/market_values_versioned.py`, nessuna modifica a SoccerMath/. Dettaglio completo (n scommesse, CI, unmatched) in `market_values_versioned_detail.json`.*

Sostituisce il fattore valore di mercato statico (`config.MARKET_VALUES`, scritto a mano e fermo a una data, applicato UGUALE a tutte le stagioni passate: leakage) con le rilevazioni reali per (lega, stagione, squadra) del CSV campionato, point-in-time: **Post-Estivo** (15/9) di default, **Post-Invernale** (15/2) per le partite dalla metà febbraio in poi, sempre della STESSA stagione della partita. La formula del fattore resta bit-fedele a produzione (`1+(log10(max(val,10))-2)/4`, clip [0.85,1.25]); cambia solo la fonte del valore. Confronto appaiato nella stessa passata walk-forward (stesso stato/Elo/xG): STATIC (prima), VERSIONED (dopo), NO_MKT (fattore 1, il riferimento «senza mercato»).

> **Nota sui livelli assoluti.** I Brier della testa Poisson su questi dati sono più alti di quelli di `production_baseline_comparison.md`: lo snapshot xG corrente (`xg_<lega>.json`) è più polarizzato di quello esistente all'epoca di quel report, e la testa NORM-SUM ne eredita l'overconfidence (stessa deriva già documentata in `ensemble_weight_grid_search.md`). Il confronto di QUESTO audit è appaiato sulla stessa identica pipeline/dati, quindi le differenze fra varianti non sono toccate dalla deriva; i livelli assoluti non vanno confrontati col report storico.

## Dati di copertura del CSV valori

File: `audit/data/market_values_top5_campionati.csv` — 772 righe lette, 772 righe usate (rilevazioni: Post-Estivo 386, Post-Invernale 386), valori in milioni da 24.8 a 1363.2. Date rilevazione coerenti con la finestra 15/9–15/2: 772/772.

Nessuna riga scartata: tutte le (lega, stagione, squadra, rilevazione) del CSV sono state riconosciute e normalizzate.

| Lega | Stagione | Righe Post-Estivo | Righe Post-Invernale |
|---|---|---:|---:|
| Bundesliga | 2022/23 | 18 | 18 |
| Bundesliga | 2023/24 | 18 | 18 |
| Bundesliga | 2024/25 | 18 | 18 |
| Bundesliga | 2025/26 | 18 | 18 |
| La Liga | 2022/23 | 20 | 20 |
| La Liga | 2023/24 | 20 | 20 |
| La Liga | 2024/25 | 20 | 20 |
| La Liga | 2025/26 | 20 | 20 |
| Ligue 1 | 2022/23 | 20 | 20 |
| Ligue 1 | 2023/24 | 18 | 18 |
| Ligue 1 | 2024/25 | 18 | 18 |
| Ligue 1 | 2025/26 | 18 | 18 |
| Premier League | 2022/23 | 20 | 20 |
| Premier League | 2023/24 | 20 | 20 |
| Premier League | 2024/25 | 20 | 20 |
| Premier League | 2025/26 | 20 | 20 |
| Serie A | 2022/23 | 20 | 20 |
| Serie A | 2023/24 | 20 | 20 |
| Serie A | 2024/25 | 20 | 20 |
| Serie A | 2025/26 | 20 | 20 |

## Uso point-in-time nelle partite eval

| Lega | Partite eval | Rilev. Post-Estivo | Rilev. Post-Invernale | Fallback (valore mancante) |
|---|---:|---:|---:|---:|
| Serie A | 760 | 483 squadre-partita | 277 | 0 |
| Premier League | 760 | 501 squadre-partita | 259 | 0 |
| La Liga | 760 | 464 squadre-partita | 296 | 0 |
| Bundesliga | 612 | 385 squadre-partita | 227 | 0 |
| Ligue 1 | 612 | 384 squadre-partita | 228 | 0 |

Nessuna partita usa una rilevazione di un'altra stagione o quella corrente: per squadra/stagione senza valore il fattore cade a 1 (come NO_MKT, contato come fallback). **Fallback effettivi: 0 su 3504 partite eval** — il CSV copre interamente i roster delle stagioni 2024/25 e 2025/26.

Nota dichiarata: le partite delle prime settimane (precedenti al 15/9) usano la rilevazione Post-Estiva della loro stagione, che e' l'unico snapshot disponibile e puo' essere di qualche settimana successiva al primo kickoff.

## Risultati per lega — Brier/LogLoss/ROI 1X2 (V=2024/25, T=2025/26)

### Serie A

| Variante | Brier V | LogLoss V | Brier T | LogLoss T | ROI B365 V | NB V | ROI B365 T | NB T | ROI Avg V | ROI Avg T |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| STATIC (config, prima) | 0.6352 | 1.0605 | 0.6100 | 1.0467 | -8.63 | 371 | 9.94 | 359 | -8.03 | 8.83 |
| VERSIONED (point-in-time, dopo) | 0.6344 | 1.0573 | 0.6103 | 1.0453 | -7.20 | 370 | 14.14 | 366 | -8.95 | 15.14 |
| NO_MKT (fattore 1, riferimento) | 0.6411 | 1.0682 | 0.6099 | 1.0386 | -7.71 | 368 | 12.68 | 361 | -8.03 | 15.66 |

(Brier/LogLoss su testa Poisson NORM-SUM pura; ROI a puntata fissa 10, selezione edge>0 sull'esito a edge massimo vs fair de-vigata del book, settle sullo stesso book — stessa convenzione di production_baseline_comparison.md. NB = n scommesse B365.)

### Premier League

| Variante | Brier V | LogLoss V | Brier T | LogLoss T | ROI B365 V | NB V | ROI B365 T | NB T | ROI Avg V | ROI Avg T |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| STATIC (config, prima) | 0.6158 | 1.0377 | 0.6451 | 1.0711 | -2.54 | 362 | 15.08 | 359 | -6.41 | 8.15 |
| VERSIONED (point-in-time, dopo) | 0.6171 | 1.0402 | 0.6455 | 1.0729 | -6.10 | 357 | 7.85 | 357 | -5.78 | 5.36 |
| NO_MKT (fattore 1, riferimento) | 0.6212 | 1.0465 | 0.6468 | 1.0751 | -6.17 | 357 | 8.28 | 363 | -6.92 | 6.80 |

(Brier/LogLoss su testa Poisson NORM-SUM pura; ROI a puntata fissa 10, selezione edge>0 sull'esito a edge massimo vs fair de-vigata del book, settle sullo stesso book — stessa convenzione di production_baseline_comparison.md. NB = n scommesse B365.)

### La Liga

| Variante | Brier V | LogLoss V | Brier T | LogLoss T | ROI B365 V | NB V | ROI B365 T | NB T | ROI Avg V | ROI Avg T |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| STATIC (config, prima) | 0.5961 | 1.0210 | 0.6172 | 1.0629 | 1.94 | 370 | -12.14 | 367 | 2.08 | -13.49 |
| VERSIONED (point-in-time, dopo) | 0.5990 | 1.0249 | 0.6138 | 1.0584 | 0.00 | 367 | -10.80 | 364 | -6.79 | -11.68 |
| NO_MKT (fattore 1, riferimento) | 0.5970 | 1.0132 | 0.6086 | 1.0403 | -0.03 | 360 | -12.10 | 359 | -1.41 | -12.54 |

(Brier/LogLoss su testa Poisson NORM-SUM pura; ROI a puntata fissa 10, selezione edge>0 sull'esito a edge massimo vs fair de-vigata del book, settle sullo stesso book — stessa convenzione di production_baseline_comparison.md. NB = n scommesse B365.)

### Bundesliga

| Variante | Brier V | LogLoss V | Brier T | LogLoss T | ROI B365 V | NB V | ROI B365 T | NB T | ROI Avg V | ROI Avg T |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| STATIC (config, prima) | 0.6558 | 1.1907 | 0.6221 | 1.0811 | 4.25 | 303 | 5.01 | 301 | 4.50 | 2.96 |
| VERSIONED (point-in-time, dopo) | 0.6555 | 1.1915 | 0.6225 | 1.0804 | 5.15 | 301 | 5.89 | 305 | 5.24 | 2.03 |
| NO_MKT (fattore 1, riferimento) | 0.6539 | 1.1719 | 0.6244 | 1.0721 | 1.50 | 299 | 0.93 | 302 | 1.71 | 1.57 |

(Brier/LogLoss su testa Poisson NORM-SUM pura; ROI a puntata fissa 10, selezione edge>0 sull'esito a edge massimo vs fair de-vigata del book, settle sullo stesso book — stessa convenzione di production_baseline_comparison.md. NB = n scommesse B365.)

### Ligue 1

| Variante | Brier V | LogLoss V | Brier T | LogLoss T | ROI B365 V | NB V | ROI B365 T | NB T | ROI Avg V | ROI Avg T |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| STATIC (config, prima) | 0.6271 | 1.0649 | 0.6256 | 1.0432 | -2.99 | 293 | 10.77 | 290 | -2.78 | 9.42 |
| VERSIONED (point-in-time, dopo) | 0.6228 | 1.0588 | 0.6266 | 1.0452 | 1.45 | 291 | 5.20 | 293 | 1.01 | -0.18 |
| NO_MKT (fattore 1, riferimento) | 0.6435 | 1.0859 | 0.6394 | 1.0642 | -7.97 | 298 | 4.17 | 297 | -4.17 | 1.89 |

(Brier/LogLoss su testa Poisson NORM-SUM pura; ROI a puntata fissa 10, selezione edge>0 sull'esito a edge massimo vs fair de-vigata del book, settle sullo stesso book — stessa convenzione di production_baseline_comparison.md. NB = n scommesse B365.)

### AGGREGATO 5 leghe

| Variante | Brier V | LogLoss V | Brier T | LogLoss T | ROI B365 V | ROI B365 T | ROI Avg V | ROI Avg T |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| STATIC (config, prima) | 0.6247 | 1.0705 | 0.6240 | 1.0609 | -1.76 | 1699 | 5.46 | 1676 | -2.34 | 2.81 |
| VERSIONED (point-in-time, dopo) | 0.6246 | 1.0703 | 0.6237 | 1.0602 | -1.70 | 1686 | 4.37 | 1685 | -3.57 | 2.25 |
| NO_MKT (fattore 1, riferimento) | 0.6299 | 1.0728 | 0.6253 | 1.0572 | -4.15 | 1682 | 2.83 | 1682 | -3.95 | 2.74 |

## Significatività delle differenze (bootstrap appaiato)

2000 resample, seed 20260905, CI percentile 2.5-97.5 (convenzione topmix_margins). Stesso resample di righe per entrambe le varianti: differenze appaiate. «sig» = l'IC esclude lo 0.

**VALIDATION 2024/25** — confronto su Brier / LogLoss / ROI B365 (aggregato 5 leghe):

| Confronto | Metrica | Delta | CI 2.5% | CI 97.5% | sig |
|---|---|---:|---:|---:|:---:|
| VERSIONED − STATIC | Brier | -0.0000 | -0.0013 | +0.0013 | no |
| VERSIONED − STATIC | LogLoss | -0.0002 | -0.0024 | +0.0021 | no |
| VERSIONED − STATIC | ROI B365 | +0.0606 | -1.9937 | +2.1522 | no |
| NO_MKT − STATIC | Brier | +0.0052 | +0.0014 | +0.0089 | **sì** |
| NO_MKT − STATIC | LogLoss | +0.0023 | -0.0038 | +0.0087 | no |
| NO_MKT − STATIC | ROI B365 | -2.3900 | -6.3169 | +1.8006 | no |

**TEST 2025/26** — confronto su Brier / LogLoss / ROI B365 (aggregato 5 leghe):

| Confronto | Metrica | Delta | CI 2.5% | CI 97.5% | sig |
|---|---|---:|---:|---:|:---:|
| VERSIONED − STATIC | Brier | -0.0004 | -0.0021 | +0.0015 | no |
| VERSIONED − STATIC | LogLoss | -0.0007 | -0.0036 | +0.0023 | no |
| VERSIONED − STATIC | ROI B365 | -1.0933 | -3.5388 | +1.2006 | no |
| NO_MKT − STATIC | Brier | +0.0013 | -0.0025 | +0.0050 | no |
| NO_MKT − STATIC | LogLoss | -0.0037 | -0.0100 | +0.0027 | no |
| NO_MKT − STATIC | ROI B365 | -2.6342 | -6.8940 | +1.5210 | no |

Divergenza effettiva fra le fonti: il |fattore versionato − fattore statico| medio per squadra-partita eval è 0.0312 (max 0.1893 su 7008 slot): i valori veri sono cambiati rispetto allo statico, ma la formula logaritmica con clip [0.85,1.25] comprime la differenza.

## Lettura

1. **Calibrazione: il point-in-time non cambia nulla di misurabile.** Il Brier aggregato passa da 0.6247 (static) a 0.6246 (versioned) in validation (-0.0000, CI [-0.0013;+0.0013], NON significativo) e da 0.6240 a 0.6237 in test. Il fattore di produzione comprime qualsiasi valore in [0.85,1.25] (media |Δfactor| 0.0312): sostituire i valori odierni con quelli storici veri sposta le probabilità troppo poco perché il leakage del valore di mercato sia la leva che la calibrazione sente.

2. **Il segnale «esiste un valore di mercato» conta, la sua data no.** Rimuovere del tutto il fattore (NO_MKT) peggiora il Brier di +0.0052 in validation (CI [+0.0014;+0.0089], significativo): la forza economica delle rose è informazione reale, anche datata e grezza. Ma tra «valore di oggi applicato al passato» (static, con leakage) e «valore vero della stagione» (versioned) la differenza è rumore: la correzione del leakage non era quella che cambiava i numeri.

3. **ROI: nessuna differenza significativa fra le fonti.** In validation il ROI B365 (testa Poisson) va da -1.76% (static) a -1.70% (versioned), delta +0.06 punti, CI [-1.99;+2.15]: dentro il rumore. Come nel grid search del peso Elo, differenze di ROI di questo ordine su ~1.5k partite/split non sono evidenza di nulla.

4. **Riscontro della stima di `market_value_comparison.txt`.** La vecchia stima (−17,4% → −1,5% su Serie A validation) confrontava il Poisson SENZA fattore mercato contro il Poisson CON fattore statico: la direzione si conferma (il fattore mercato migliora la selezione value bet), ma quell'entità dipendeva dallo stato xG dell'epoca. E la parte «versionato» della proposta §5 di `margini_migliorabili_topmix.md` non aggiunge nulla di misurabile né in calibrazione né in ROI: il guadagno veniva (quando veniva) dall'avere UN fattore mercato, non dalla sua data.

5. **Per il codice di produzione la misura è neutra.** Nessun motivo dati-driven di sostituire MARKET_VALUES statico con i CSV versionati per il solo 1X2: i numeri non migliorano. Resta valido l'argomento di pulizia metodologica (no-leakage per costruzione), che però non è ciò che questo audit era chiamato a misurare.

## Limiti dichiarati

1. **Rilevazioni due volte l'anno** (15/9 e 15/2): il fattore e' costante tra le due date; il mercato reale si muove ogni settimana. E' comunque una ricostruzione molto piu' fedele dello statico odierno, che su una partita del 2022 applicava il valore del 2026.
2. **Partite prima del 15/9**: usano la rilevazione post-estiva della loro stagione (unico snapshot disponibile), tecnicamente successiva al kickoff di poche settimane; effetto limitato alle prime 2-3 giornate.
3. **Elo e forma non dipendono dal fattore mercato** (solo la testa Poisson lo usa): le differenze misurate sono attribuibili al solo cambio di fonte, con confronto appaiato nella stessa passata.
4. **xG snapshot statico**: limite ereditato dalla pipeline condivisa, documentato in `clv_pinnacle_report.md`.
5. Il CSV campionato copre i roster di 5 leghe x 4 stagioni verificati riga per riga e in queste run il fallback e' 0 su ogni partita eval; rimane implementato il fallback a fattore 1 (contato, mai valori di altre stagioni) per robustezza a futuri re-upload.

