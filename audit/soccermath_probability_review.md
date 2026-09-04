# SoccerMath2.0 — Revisione motore probabilità: stato, evidenze, piano di lavoro

Documento di handoff. Riassume solo cose verificate sul codice/dati reali del repo
(`github.com/iFelice/SoccerMath2.0`, cartella `SoccerMath/`), non ipotesi.
Nessuna formula è stata modificata al momento della stesura: tutto quello che
segue è diagnosi, non intervento.

> **Aggiornamento (post-handoff):** interventi eseguiti in base alle diagnosi e
> tracciati qui sotto: (1) nella testa Totali (O/U2.5, GG/NG) del Poisson a Due
> Teste la forma a 5 gare è stata rimossa — la testa Totali usa ora la baseline
> pura `att0_pure`/`def0_pure` (xG/gol storici senza forma), mentre `att0`/`def0`
> e la testa 1X2 restano invariati — motivato da `diagnose_form_totali.py`
> (report in `results/form_totali_diagnosis.md`); (2) fix nomenclatura
> `"Athletic Bilbao" → "Ath Bilbao"` in `config.py`.

---

## 0. Stato del database (già sistemato, non toccare)

Le 5 leghe hanno ora struttura identica: `<Prefix>_2022.csv` … `<Prefix>_2025.csv`
(stagioni storiche, una per file, no duplicati) + `<Prefix>_Live.csv` (stagione
corrente, resettato a inizio stagione). `config.get_league_db_files()` risolve
tutto correttamente. Verificato via hash md5 (no duplicati) e range di date
(no overlap). **Non serve altro lavoro qui.**

---

## 1. Cosa è confermato che non va, nel motore di probabilità

Tutti i punti sotto sono stati verificati leggendo il codice sorgente attuale
(non l'analisi di ChatGPT sui suoi cappelli — quella ha dato lo spunto iniziale,
ogni punto è stato poi controllato riga per riga sul repo vero).

### 1.1 — Il motore più sofisticato non è quello validato
`app.py` (righe 409, 1047): commento esplicito *"Dixon-Coles è escluso
volutamente per velocità"*. Il backtest in-app (`run_historical_backtest`)
testa solo Poisson ed Elo. **Rettifica: Dixon-Coles NON è in produzione.**
È presente solo in `models/dixon_coles.py` ed è usato esclusivamente da
script offline (`SoccerMath/evaluate_models.py`,
`audit/backtest_experiment_all.py`, `SoccerMath/test_basic.py`); in `app.py`
resta soltanto l'import (riga 33), mai chiamato. La produzione utilizza il
**Poisson a Due Teste** (`get_full_poisson_two_heads` in `app.py`: testa 1X2
con lambda forma+mercato normalizzati alla somma base `att0`/`def0`, testa
Totali con lambda base puri `att0_pure`/`def0_pure` senza forma). Il punto
della sezione resta valido nella forma corretta: il motore più sofisticato
non è quello di produzione e non è mai stato misurato nel circuito live.

### 1.2 — Il modulo di validazione economica esiste ma è morto
`models/backtest.py` contiene `run_backtest`, `compare_models_backtest`,
`detect_value_bets` (bankroll, ROI, Brier Score, Log Loss). Cercato in tutto
il repo: l'unico riferimento fuori da quel file è l'import in `app.py` riga 34.
**Non vengono mai chiamate.** Il tab "📊 BACKTEST" dell'app gira su una funzione
diversa (`run_historical_backtest`) che non tocca mai una colonna di quota —
misura solo azzeccato/non azzeccato, mai valore economico.

### 1.3 — Doppio meccanismo di recency non giustificato
`models/dixon_coles.py`: `xi = 0.0019` (decay esponenziale, già una forma di
peso temporale) **più** `recent_boost = 1.3` fisso per le partite negli ultimi
60 giorni (riga 96). Due meccanismi sovrapposti per lo stesso scopo, il
secondo è un numero scelto a mano, mai testato contro alternative.

### 1.4 — Elo + xG: struttura asimmetrica
`models/elo_engine.py` riga 130: `xg_adj = (h_xg - a_xg) * 0.15` — usa solo
attacco-casa meno difesa-ospite. Il Poisson principale invece usa
correttamente `Attacco_H × Difesa_A` e `Attacco_A × Difesa_H` incrociati.
L'Elo non rispecchia questa struttura.

### 1.5 — xG: solo media stagionale
`update_xg.py` righe 108-109: `xG_avg = total_xg / matches_played`. Nessuna
finestra mobile (ultime 5/10), nessuno split casa/trasferta. Il dato non
distingue "la squadra di adesso" da "la squadra media della stagione".

### 1.6 — Pesi e soglie dell'ensemble: costanti scritte a mano
`app.py` righe 686-690:
```
confidence = 0.6 * poisson_prob + 0.4 * elo_prob
min_conf = 0.60   # Over/Under, GG/NG
min_conf = 0.55   # 1X2
```
più un filtro `abs(poisson_prob - elo_prob) < 0.25` non documentato altrove.
Sei numeri (0.6, 0.4, 0.55, 0.60, 0.25, e implicitamente 0.15 del punto 1.4)
mai validati contro alternative.

### 1.7 — Valori di mercato: statici, non sincronizzati con nessuna stagione
`config.py`, dizionario `MARKET_VALUES` scritto a mano (Inter 600, Milan 550…).
Nessuno script lo aggiorna. Usato per un fattore moltiplicativo
attacco/difesa in ogni previsione, comprese quelle storiche nel backtest —
**rischio di leakage temporale**: i valori di oggi vengono implicitamente
applicati anche a partite del 2022, quando le rose (e quindi i valori reali)
erano diverse.

### 1.8 — Nessuna quota storica per GG/NG
Verificato sui CSV: colonne 1X2 (`B365H/D/A`, `AvgH/D/A`, `MaxH/D/A`) e
Over/Under 2.5 (`B365>2.5`, `Avg>2.5`, ecc.) sempre presenti. **Zero colonne
BTTS/GG in nessuna stagione, nessuna lega.** Non è un bug del codice, è un
limite della fonte dati (football-data.co.uk). Le previsioni GG/NG possono
essere validate solo su calibrazione, mai su edge/ROI, a meno di procurarsi
un'altra fonte di quote.

### 1.9 — Il set di bookmaker cambia nel tempo
Verificato su Serie A: 2022-23 ha `B365,BW,IW,PS,WH,VC`; 2024-25 sostituisce
`IW,VC` con `BF,1XB`; 2025-26 cambia ancora (`BFD,BMGM,BV,CL,LB`). Solo
`B365H/D/A` e `AvgH/D/A`/`MaxH/D/A` sono presenti al 100% in ogni stagione —
sono gli unici utilizzabili per confronti coerenti nel tempo.

---

## 2. Prova empirica: esperimento walk-forward su Serie A (già eseguito)

Script allegati: `backtest_experiment.py` + `analyze.py`. Replicano la logica
walk-forward esistente (no leakage: ogni previsione usa solo dati precedenti
alla partita) ma con split per stagione reale invece che per N partite fisse,
registrando probabilità + quota pre-match + de-vig per ogni riga.

**Split usato:** train 2022/23+2023/24 → validation 2024/25 → test 2025/26 →
monitor 2026/27 (solo osservativo, campione troppo piccolo per giudizi).

**Risultato principale (Serie A, 380 partite/stagione, mercato 1X2, edge vs
B365 de-vigato):**

| Stagione | Modello | Brier↓ | LogLoss↓ | Win rate | ROI |
|---|---|---|---|---|---|
| 2024/25 (val) | Poisson | 0.584 | 0.980 | 33.2% | -17.41% |
| 2024/25 (val) | Elo | 0.595 | 1.000 | 25.0% | -25.35% |
| 2024/25 (val) | SoccerMath (0.6P+0.4Elo) | 0.586 | 0.983 | 27.9% | -24.43% |
| 2025/26 (test) | Poisson | 0.593 | 0.992 | 36.6% | -1.92% |
| 2025/26 (test) | Elo | 0.601 | 1.009 | 27.1% | -15.52% |
| 2025/26 (test) | SoccerMath (0.6P+0.4Elo) | 0.594 | 0.995 | 33.7% | -6.71% |

Poisson puro batte l'ensemble e l'Elo su ogni metrica, in entrambe le
stagioni. L'Elo peggiora sistematicamente il risultato.

**Test di selettività (soglia minima di edge dichiarato prima di scommettere,
stagione test):**

| Soglia edge | N. bet | Win rate | ROI |
|---|---|---|---|
| ≥0% | 380 | 33.7% | -6.71% |
| ≥2% | 350 | 34.3% | -4.12% |
| ≥4% | 250 | 32.0% | -6.66% |
| ≥6% | 145 | 26.9% | -29.89% |
| ≥8% | 79 | 26.6% | -19.11% |
| ≥10% | 35 | 25.7% | -36.00% |

**Win rate e ROI peggiorano quando il modello dichiara più fiducia, non
migliorano.** Questo è il segnale diretto di un modello scalibrato: l'"edge"
che produce è rumore travestito da segnale, non informazione reale sul
mercato.

**Verdetto misurato:** su Serie A, con l'implementazione attuale, nessuna
evidenza di edge su 1X2 o Over/Under 2.5, in nessuna delle due stagioni
testate. Non ancora verificato sulle altre 4 leghe.

---

## 3. Piano di lavoro — ordine di priorità

Principio guida per tutto il piano: **prima misurare, poi decidere se
correggere.** Non ottimizzare parametri sul passato per far salire un ROI —
è l'errore di overfitting più facile in cui cadere qui, ed è stato segnalato
esplicitamente anche nel ragionamento di ChatGPT che ha originato questa
revisione.

### Priorità 0 — Estendere l'infrastruttura di misura (nessun rischio, nessuna formula toccata)
1. Replicare `backtest_experiment.py` / `analyze.py` sulle altre 4 leghe
   (Premier, La Liga, Bundesliga, Ligue 1) — bastano gli stessi script,
   cambiando solo il prefisso file. Obiettivo: capire se il problema di
   calibrazione è specifico di Serie A o sistemico su tutto il motore.
2. Portare `calculate_brier_score` / `calculate_log_loss` (già scritte in
   `models/backtest.py`, mai usate) dentro `run_historical_backtest()`
   nell'app, così la calibrazione è visibile anche nel tab BACKTEST live,
   non solo nello script esterno.
3. Aggiungere il confronto edge-vs-quota-de-vigata anche alle previsioni
   *live* dell'app (oggi il tab predizioni confronta solo `confidence` contro
   una soglia fissa, mai contro la quota di mercato reale). Serve per capire,
   partita per partita, se il modello sta davvero trovando qualcosa che il
   mercato non ha già prezzato.

### Priorità 1 — Correzioni strutturali a basso rischio (bug logici, non tuning)
4. **Elo + xG (punto 1.4):** riscrivere l'adjustment con struttura simmetrica
   Attacco×Difesa incrociata, coerente con quello che già fa il Poisson.
   Poi ri-misurare con lo script del punto 1 — non sostituire alla cieca,
   confrontare prima/dopo su validation.
5. **Market values (punto 1.7):** o versionare `MARKET_VALUES` per stagione
   (serve una fonte storica, es. Transfermarkt archiviato per anno), o
   escludere il fattore mercato dal backtest storico finché non è
   time-consistent — altrimenti ogni numero di backtest sulle stagioni
   vecchie è viziato da leakage.
6. **Dixon-Coles nel backtest reale (punto 1.1):** includerlo nel confronto
   walk-forward (già presente in `models/backtest.py` come opzione, mai
   collegato) invece di escluderlo per velocità. Se il costo computazionale
   è il problema, testarlo su un sottoinsieme (es. solo stagione test) prima
   di deciderne l'inclusione permanente.

### Priorità 2 — Sperimentazione controllata sui parametri (solo dopo P0+P1)
7. Xi (0.0019) e recent boost (1.3, punto 1.3): trasformarli in un singolo
   parametro da sweepare su una griglia (es. xi variabile, boost 0/10/20/30/40%)
   validato su 2024/25, mai deciso a occhio.
8. Pesi ensemble (0.6/0.4) e soglie di confidenza (0.55/0.60) e la soglia di
   disaccordo (0.25): stessa logica — grid search su validation, verifica su
   test, mai tuning diretto sul test set.
9. xG con finestra mobile (punto 1.5): richiede prima un cambio nel formato
   dati (`update_xg.py`/`scraper_xg.py` oggi salvano solo la media stagionale
   per squadra, non lo storico partita-per-partita) — è un lavoro sullo
   strato dati, non solo sul modello, va pianificato come task a parte.

### Nota permanente
2026/27 resta **solo monitoraggio prospettico**, mai usato per validare o
tarare nulla — è l'unico modo per avere, in futuro, un vero test fuori
campione non contaminato da retrospettiva.

---

## 4. File allegati
- `backtest_experiment.py` — carica Serie A, split per stagione, walk-forward
  con quote pre-match e de-vig.
- `analyze.py` — calcola Brier/LogLoss/edge/ROI/drawdown e produce le tabelle
  di questo documento. Da qui si parte per replicare sulle altre leghe.
- `diagnose_form_totali.py` — walk-forward su 5 leghe (2024/25+2025/26): Brier
  O/U2.5 e GG/NG della testa Totali con forma a 5 gare vs senza (baseline pura).
  Report: `results/form_totali_diagnosis.md`. Base dell'intervento in `app.py`
  (testa Totali con `att0_pure`/`def0_pure` senza forma).
- `diagnose_elo_ensemble.py` — walk-forward su 5 leghe (2024/25+2025/26):
  Poisson (testa 1X2 di produzione) vs Elo vs ensemble 0.6P+0.4E sul 1X2,
  con Brier/LogLoss/win rate e analisi del filtro di disaccordo 0.25.
  Report: `results/elo_ensemble_diagnosis.md`.
