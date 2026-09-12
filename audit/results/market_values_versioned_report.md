# MARKET_VALUES versionato per stagione — impatto sul 1X2 (audit sola lettura)

*Generato: 2026-09-11T23:03:59+00:00 — script `audit/market_values_versioned.py`, nessuna modifica a SoccerMath/. Dettaglio completo (n scommesse, CI, unmatched) in `market_values_versioned_detail.json`.*

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
| STATIC (config, prima) | 0.6740 | 1.1556 | 0.6322 | 1.1208 | -1.81 | 380 | 10.27 | 380 | -1.42 | 7.91 |
| VERSIONED (point-in-time, dopo) | 0.6741 | 1.1534 | 0.6332 | 1.1193 | -3.81 | 380 | 5.96 | 380 | -2.21 | 5.94 |
| NO_MKT (fattore 1, riferimento) | 0.6855 | 1.1690 | 0.6363 | 1.1159 | -5.38 | 380 | 8.56 | 380 | -6.07 | 5.93 |

(Brier/LogLoss su testa Poisson NORM-SUM pura; ROI a puntata fissa 10, selezione edge>0 sull'esito a edge massimo vs fair de-vigata del book, settle sullo stesso book — stessa convenzione di production_baseline_comparison.md. NB = n scommesse B365.)

### Premier League

| Variante | Brier V | LogLoss V | Brier T | LogLoss T | ROI B365 V | NB V | ROI B365 T | NB T | ROI Avg V | ROI Avg T |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| STATIC (config, prima) | 0.6428 | 1.0910 | 0.6577 | 1.1033 | -5.01 | 380 | 7.66 | 380 | -4.79 | 6.78 |
| VERSIONED (point-in-time, dopo) | 0.6426 | 1.0904 | 0.6565 | 1.1014 | -9.32 | 380 | 6.87 | 380 | -6.68 | 6.52 |
| NO_MKT (fattore 1, riferimento) | 0.6432 | 1.0899 | 0.6541 | 1.0968 | -0.27 | 380 | 8.05 | 380 | 0.78 | 8.16 |

(Brier/LogLoss su testa Poisson NORM-SUM pura; ROI a puntata fissa 10, selezione edge>0 sull'esito a edge massimo vs fair de-vigata del book, settle sullo stesso book — stessa convenzione di production_baseline_comparison.md. NB = n scommesse B365.)

### La Liga

| Variante | Brier V | LogLoss V | Brier T | LogLoss T | ROI B365 V | NB V | ROI B365 T | NB T | ROI Avg V | ROI Avg T |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| STATIC (config, prima) | 0.6237 | 1.0777 | 0.6350 | 1.1019 | -9.70 | 380 | -8.76 | 380 | -7.79 | -7.98 |
| VERSIONED (point-in-time, dopo) | 0.6279 | 1.0847 | 0.6331 | 1.0999 | -8.71 | 380 | -7.19 | 380 | -8.97 | -7.86 |
| NO_MKT (fattore 1, riferimento) | 0.6347 | 1.0838 | 0.6397 | 1.0984 | -4.46 | 380 | -8.49 | 380 | -4.57 | -13.24 |

(Brier/LogLoss su testa Poisson NORM-SUM pura; ROI a puntata fissa 10, selezione edge>0 sull'esito a edge massimo vs fair de-vigata del book, settle sullo stesso book — stessa convenzione di production_baseline_comparison.md. NB = n scommesse B365.)

### Bundesliga

| Variante | Brier V | LogLoss V | Brier T | LogLoss T | ROI B365 V | NB V | ROI B365 T | NB T | ROI Avg V | ROI Avg T |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| STATIC (config, prima) | 0.6663 | 1.2347 | 0.6631 | 1.1603 | 12.09 | 306 | 0.39 | 306 | 14.53 | -3.48 |
| VERSIONED (point-in-time, dopo) | 0.6656 | 1.2358 | 0.6629 | 1.1591 | 10.84 | 306 | -0.35 | 306 | 13.69 | -1.27 |
| NO_MKT (fattore 1, riferimento) | 0.6679 | 1.2227 | 0.6677 | 1.1558 | 10.29 | 306 | -6.89 | 306 | 10.50 | -8.26 |

(Brier/LogLoss su testa Poisson NORM-SUM pura; ROI a puntata fissa 10, selezione edge>0 sull'esito a edge massimo vs fair de-vigata del book, settle sullo stesso book — stessa convenzione di production_baseline_comparison.md. NB = n scommesse B365.)

### Ligue 1

| Variante | Brier V | LogLoss V | Brier T | LogLoss T | ROI B365 V | NB V | ROI B365 T | NB T | ROI Avg V | ROI Avg T |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| STATIC (config, prima) | 0.6580 | 1.1326 | 0.6513 | 1.0957 | 1.75 | 306 | -3.78 | 306 | -4.13 | -5.92 |
| VERSIONED (point-in-time, dopo) | 0.6534 | 1.1262 | 0.6527 | 1.0983 | 0.64 | 306 | -3.26 | 306 | -4.72 | -4.89 |
| NO_MKT (fattore 1, riferimento) | 0.6738 | 1.1492 | 0.6641 | 1.1155 | 2.09 | 306 | -5.59 | 306 | 2.72 | -5.89 |

(Brier/LogLoss su testa Poisson NORM-SUM pura; ROI a puntata fissa 10, selezione edge>0 sull'esito a edge massimo vs fair de-vigata del book, settle sullo stesso book — stessa convenzione di production_baseline_comparison.md. NB = n scommesse B365.)

### AGGREGATO 5 leghe

| Variante | Brier V | LogLoss V | Brier T | LogLoss T | ROI B365 V | ROI B365 T | ROI Avg V | ROI Avg T |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| STATIC (config, prima) | 0.6522 | 1.1345 | 0.6471 | 1.1154 | -1.16 | 1752 | 1.40 | 1752 | -1.22 | -0.18 |
| VERSIONED (point-in-time, dopo) | 0.6521 | 1.1345 | 0.6468 | 1.1145 | -2.73 | 1752 | 0.59 | 1752 | -2.31 | -0.08 |
| NO_MKT (fattore 1, riferimento) | 0.6602 | 1.1393 | 0.6513 | 1.1149 | -0.03 | 1752 | -0.42 | 1752 | 0.17 | -2.29 |

## Significatività delle differenze (bootstrap appaiato)

2000 resample, seed 20260905, CI percentile 2.5-97.5 (convenzione topmix_margins). Stesso resample di righe per entrambe le varianti: differenze appaiate. «sig» = l'IC esclude lo 0.

**VALIDATION 2024/25** — confronto su Brier / LogLoss / ROI B365 (aggregato 5 leghe):

| Confronto | Metrica | Delta | CI 2.5% | CI 97.5% | sig |
|---|---|---:|---:|---:|:---:|
| VERSIONED − STATIC | Brier | -0.0000 | -0.0013 | +0.0012 | no |
| VERSIONED − STATIC | LogLoss | -0.0000 | -0.0022 | +0.0022 | no |
| VERSIONED − STATIC | ROI B365 | -1.5679 | -4.1632 | +0.8253 | no |
| NO_MKT − STATIC | Brier | +0.0080 | +0.0043 | +0.0116 | **sì** |
| NO_MKT − STATIC | LogLoss | +0.0048 | -0.0014 | +0.0112 | no |
| NO_MKT − STATIC | ROI B365 | +1.1364 | -2.8482 | +5.1102 | no |

**TEST 2025/26** — confronto su Brier / LogLoss / ROI B365 (aggregato 5 leghe):

| Confronto | Metrica | Delta | CI 2.5% | CI 97.5% | sig |
|---|---|---:|---:|---:|:---:|
| VERSIONED − STATIC | Brier | -0.0003 | -0.0020 | +0.0016 | no |
| VERSIONED − STATIC | LogLoss | -0.0009 | -0.0039 | +0.0021 | no |
| VERSIONED − STATIC | ROI B365 | -0.8042 | -3.0656 | +1.5040 | no |
| NO_MKT − STATIC | Brier | +0.0042 | +0.0004 | +0.0079 | **sì** |
| NO_MKT − STATIC | LogLoss | -0.0006 | -0.0070 | +0.0059 | no |
| NO_MKT − STATIC | ROI B365 | -1.8162 | -5.2654 | +1.7968 | no |

Divergenza effettiva fra le fonti: il |fattore versionato − fattore statico| medio per squadra-partita eval è 0.0312 (max 0.1893 su 7008 slot): i valori veri sono cambiati rispetto allo statico, ma la formula logaritmica con clip [0.85,1.25] comprime la differenza.

## Lettura

1. **Calibrazione: il point-in-time non cambia nulla di misurabile.** Il Brier aggregato passa da 0.6522 (static) a 0.6521 (versioned) in validation (-0.0000, CI [-0.0013;+0.0012], NON significativo) e da 0.6471 a 0.6468 in test. Il fattore di produzione comprime qualsiasi valore in [0.85,1.25] (media |Δfactor| 0.0312): sostituire i valori odierni con quelli storici veri sposta le probabilità troppo poco perché il leakage del valore di mercato sia la leva che la calibrazione sente.

2. **Il segnale «esiste un valore di mercato» conta, la sua data no.** Rimuovere del tutto il fattore (NO_MKT) peggiora il Brier di +0.0080 in validation (CI [+0.0043;+0.0116], significativo): la forza economica delle rose è informazione reale, anche datata e grezza. Ma tra «valore di oggi applicato al passato» (static, con leakage) e «valore vero della stagione» (versioned) la differenza è rumore: la correzione del leakage non era quella che cambiava i numeri.

3. **ROI: nessuna differenza significativa fra le fonti.** In validation il ROI B365 (testa Poisson) va da -1.16% (static) a -2.73% (versioned), delta -1.57 punti, CI [-4.16;+0.83]: dentro il rumore. Come nel grid search del peso Elo, differenze di ROI di questo ordine su ~1.5k partite/split non sono evidenza di nulla.

4. **Riscontro della stima di `market_value_comparison.txt`.** La vecchia stima (−17,4% → −1,5% su Serie A validation) confrontava il Poisson SENZA fattore mercato contro il Poisson CON fattore statico: la direzione si conferma (il fattore mercato migliora la selezione value bet), ma quell'entità dipendeva dallo stato xG dell'epoca. E la parte «versionato» della proposta §5 di `margini_migliorabili_topmix.md` non aggiunge nulla di misurabile né in calibrazione né in ROI: il guadagno veniva (quando veniva) dall'avere UN fattore mercato, non dalla sua data.

5. **Per il codice di produzione la misura è neutra.** Nessun motivo dati-driven di sostituire MARKET_VALUES statico con i CSV versionati per il solo 1X2: i numeri non migliorano. Resta valido l'argomento di pulizia metodologica (no-leakage per costruzione), che però non è ciò che questo audit era chiamato a misurare.

## Limiti dichiarati

1. **Rilevazioni due volte l'anno** (15/9 e 15/2): il fattore e' costante tra le due date; il mercato reale si muove ogni settimana. E' comunque una ricostruzione molto piu' fedele dello statico odierno, che su una partita del 2022 applicava il valore del 2026.
2. **Partite prima del 15/9**: usano la rilevazione post-estiva della loro stagione (unico snapshot disponibile), tecnicamente successiva al kickoff di poche settimane; effetto limitato alle prime 2-3 giornate.
3. **Elo e forma non dipendono dal fattore mercato** (solo la testa Poisson lo usa): le differenze misurate sono attribuibili al solo cambio di fonte, con confronto appaiato nella stessa passata.
4. **xG snapshot statico**: limite ereditato dalla pipeline condivisa, documentato in `clv_pinnacle_report.md`.
5. Il CSV campionato copre i roster di 5 leghe x 4 stagioni verificati riga per riga e in queste run il fallback e' 0 su ogni partita eval; rimane implementato il fallback a fattore 1 (contato, mai valori di altre stagioni) per robustezza a futuri re-upload.

