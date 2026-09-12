# Fascia di quota reale del Top Mix — soglia 1,50 (audit sola lettura)

*Generato: 2026-09-11T23:38:27.664146+00:00 — script `audit/diagnose_quota_minima.py`, nessuna modifica a SoccerMath/.*

Le righe ammesse del selettore Top Mix (replay consolidato di `seleziona_riga_top_mix`, funzione pura importata da `SoccerMath/app.py`: 3422 candidate, 1865 ammesse, stagioni 2024/25+2025/26 — **validation storica gia' esaminata**, non un test intatto) vengono agganciate alla QUOTA REALE del mercato scelto: B365 dai CSV storici per 1X2 e O/U 2.5, quote BTTS (bet365/fallback dichiarato) dai file `audit/data/*_btts.json` via `gg_ng_calibration.join_btts_file` riusato identico. Le righe sono divise per quota reale < 1.50 vs >= 1.50 (soglia del protocollo, non ottimizzata sui dati). Mai 1/confidence, mai quota implicita del modello; righe senza quota usabile ESCLUSE e CONTEGGIATE, mai assegnate a una fascia.

## 0. Perimetro e consistenza

* Sorgente righe: `audit/results/topmix_selector_replay_rows.csv` (committato, 3422 candidate, 1865 ammesse — identico a `topmix_margins.py`).
* Selettore: `seleziona_riga_top_mix` di produzione (parita' comportamentale garantita da `SoccerMath/test_topmix_selector_parity.py`; qui la funzione e' importata e il replay NON viene rieseguito).
* Quote: B365 per 1X2 (B365H/D/A) e O/U 2.5 (B365>2.5/B365<2.5) dai CSV `SoccerMath/database/`; GG/NG dai JSON oddsportal (bet365 se presente, altrimenti primo book usabile — convenzione `gg_ng_calibration`).
* Nota join: il replay conserva i nomi GREZZI football-data in `home`/`away` (es. «Bayern Munich», «RB Leipzig» in Bundesliga): la chiave di join applica la stessa normalizzazione dei database (`team_aliases.clean_name`), identica a quella di `load_league` e del join BTTS. Copertura risultata 100% su ogni mercato.
* Brier = media di (confidence − esito)² sull'evento scelto, stessa definizione di `topmix_margins.quality` (verificata nei test); ROI = puntata fissa 10 su OGNI riga ammessa con quota, settle sulla quota reale del book (le ammesse sono le selezioni gia' puntate dal Top Mix).

## 1. Copertura dell'aggancio quota reale

| Voce | Righe |
|---|---:|
| Ammesse dal replay | 1865 |
| Con quota reale usabile | 1865 |
| **Totale escluse** | **0** |

Nessuna riga senza quota e' finita in una fascia. Verifica di coerenza dell'esito: ricalcolando l'esito del mercato dai gol del replay, ``hit_mismatch`` = 0 (la mappa mercato->esito di questo audit coincide con quella del replay).

Copertura per mercato:

| Mercato | con quota | ammesse | copertura |
|---|---:|---:|---:|
| 1 | 806 | 806 | 100.0% |
| 2 | 318 | 318 | 100.0% |
| GG | 372 | 372 | 100.0% |
| NG | 2 | 2 | 100.0% |
| O2.5 | 132 | 132 | 100.0% |
| U2.5 | 235 | 235 | 100.0% |

## 2. Fasce di quota reale (< 1.50 vs >= 1.50)

| Fascia | n | hit-rate | Brier | conf media | quota media | ROI |
|---|---:|---:|---:|---:|---:|---:|
| quota < 1.50 | 723 | 74.4% (CI [+0.713;+0.776]) | 0.192 (CI [+0.178;+0.206]) | 0.720 | 1.34 | -1.14% (CI [-5.42;+3.03]) |
| quota >= 1.50 | 1142 | 54.1% (CI [+0.513;+0.568]) | 0.256 (CI [+0.249;+0.264]) | 0.629 | 1.68 | -10.22% (CI [-14.93;-5.70]) |
| intero campione ammesso | 1865 | 62.0% (CI [+0.597;+0.641]) | 0.231 (CI [+0.224;+0.239]) | 0.664 | 1.55 | -6.70% (CI [-10.07;-3.41]) |

Tutte le CI: bootstrap 2000 resample, seed 20260905, percentile 2.5-97.5 (convenzione `topmix_margins._ci`). Lo stesso resample e' applicato a tutte le celle e ai delta della sezione 4: i confronti sono appaiati. Una cella con troppo pochi casi (CI istabile in oltre meta' dei resample) e' marcata senza CI, mai stimata a caso.

## 3. Scomposizione per mercato dentro ciascuna fascia

| Mercato | Fascia | n | hit-rate | Brier | conf media | ROI |
|---|---|---:|---:|---:|---:|---:|
| 1 | >= 1.50 | 344 | 52.3% | 0.262 | 0.629 | -11.96% (CI [-20.97;-2.92]) |
| 1 | < 1.50 | 462 | 75.3% | 0.187 | 0.743 | -1.95% (CI [-7.34;+3.19]) |

| 2 | >= 1.50 | 222 | 53.6% | 0.253 | 0.616 | -6.52% (CI [-18.48;+5.04]) |
| 2 | < 1.50 | 96 | 76.0% | 0.180 | 0.720 | 2.21% (CI [-9.53;+12.96]) |

| GG | >= 1.50 | 301 | 57.1% | 0.248 | 0.627 | -8.49% (CI [-18.02;+0.54]) |
| GG | < 1.50 | 71 | 69.0% | 0.221 | 0.637 | -2.86% (CI [-17.73;+11.66]) |

| NG | >= 1.50 | 2 | 50.0% | 0.258 | 0.624 | -16.50% (CI [-100.00;+67.00]) |
| NG | < 1.50 | 0 | - | - | - | - |

| O2.5 | >= 1.50 | 99 | 54.5% | 0.259 | 0.660 | -12.61% (CI [-28.24;+3.71]) |
| O2.5 | < 1.50 | 33 | 72.7% | 0.197 | 0.690 | 0.33% (CI [-22.07;+21.46]) |

| U2.5 | >= 1.50 | 174 | 52.9% | 0.261 | 0.628 | -13.05% (CI [-24.93;-0.51]) |
| U2.5 | < 1.50 | 61 | 72.1% | 0.204 | 0.656 | 0.90% (CI [-15.56;+17.00]) |


## 4. Confronto esplicito: subset quota >= 1.50 vs INTERO campione

Delta appaiati (stesso resample) subset − intero campione e subset − complementare. La domanda del protocollo: restringere BUTTA VIA valore (ROI delta significativamente negativo) o lo PRESERVA (delta indistinguibile da zero)? «sig» = l'IC esclude lo 0.

| Confronto | Metrica | Delta | CI 2.5% | CI 97.5% | sig |
|---|---|---:|---:|---:|:---:|
| subset − intero campione | hit-rate | -0.079 | -0.096 | -0.062 | **sì** |
| subset − intero campione | Brier | +0.0250 | +0.0184 | +0.0316 | **sì** |
| subset − intero campione | ROI | -3.52 | -6.00 | -1.14 | **sì** |
| subset − fascia corta | hit-rate | -0.203 | -0.245 | -0.161 | **sì** |
| subset − fascia corta | Brier | +0.0644 | +0.0477 | +0.0805 | **sì** |
| subset − fascia corta | ROI | -9.08 | -15.56 | -2.89 | **sì** |

## 5. Lettura

1. **Composizione.** Il 61% del campione ammesso (1142 su 1865) ha quota >= 1.50; la fascia corta (< 1.50, 723 righe) e' fatta soprattutto da favoriti 1 e Under 2.5 (sezione 3).

2. **Calibrazione subset vs intero.** Delta Brier +0.0250 (CI [+0.0184;+0.0316], significativo). Il confronto assoluto fra fasce va letto con la confidenza media in mano (colonna «conf media»): la fascia corta e' quella a confidenza piu' alta, quindi un suo Brier basso non e' una sorpresa.

3. **Valore.** ROI subset − intero: -3.52 punti (CI [-6.00;-1.14], significativo); ROI subset − fascia corta: -9.08 (CI [-15.56;-2.89]).

4. **Risposta alla domanda del protocollo: NO — su questo campione restringere a quota >= 1.50 BUTTA VIA valore invece di preservarlo.** Tutti e tre i delta subset−intero sono significativamente negativi (hit-rate -0.079, Brier +0.0250, ROI -3.52 punti): il filtro elimina proprio il segmento migliore (quota corta: hit-rate 74.4%, Brier 0.192, ROI -1.14% con CI che include lo 0, cioè vicino al pareggio) e lascia solo il segmento peggiore. L'effetto e' TRASVERSALE: dentro ogni mercato la fascia corta ha Brier e ROI migliori della fascia lunga (sezione 3).

## 6. Limiti dichiarati

1. **Stagioni gia' esaminate**: il replay 2024/25+2025/26 e' la stessa validation storica degli altri audit Top Mix (soglie, pesi e gate sono stati scelti su questi dati): nessun numero qui e' out-of-sample.
2. **Soglia 1,50 del protocollo**, non ottimizzata: nessuna scansione di soglie; qualunque altra soglia andrebbe testata con la stessa disciplina (selezione su train, conferma su validation) prima di credervi.
3. **Quote B365 pre-match** (colonne CSV, non line live) e BTTS oddsportal con fallback multi-book dichiarato per file: stessa fonte degli audit precedenti, quindi stessi limiti di realismo di esecuzione.
4. **Brier fra fasce non e' paragonabile in assoluto**: le fasce hanno confidenze medie diverse; il Brier per fascia misura la calibrazione del modello SU quella fascia, non la qualita' della fascia.
5. Le righe senza quota usabile sono escluse e contate (sezione 1): se la mancanza di quota fosse correlata all'esito, le fasce subirebbero un bias di selezione non correggibile.
6. ROI a puntata fissa su selezioni del selettore: niente stake variabili/Kelly, niente accumuli: come gli altri audit Top Mix.

## 7. Riproduzione

```
python audit/diagnose_quota_minima.py
```

Deterministico: bootstrap con seed fisso (20260905), righe lette dal CSV committato (stesso replay di `topmix_margins.py`). Dettaglio completo nel sidecar `quota_minima_report_detail.json`.

