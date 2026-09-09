# Margini migliorabili del selettore Top Mix — numeri

*Generato*: 2026-09-09T09:39:54+00:00 · *righe analizzate*: 3422 · *commit codice*: `01260c11c446`

> **Etichetta dei dati.** validation storica GIA' ESAMINATA (2024/25 e 2025/26 sono state usate per scegliere due teste, forma fuori dai totali, shrinkage PRIOR_MATCHES=6 e per confermare i pesi 0.6/0.4): NON e' un test intatto. Non è un hold-out. Nessuna soglia, peso o formula è stata cercata o cambiata in questo giro: le tabelle misurano il **costo di vincoli già esistenti**, non il valore di vincoli alternativi. Fonte: `audit/results/topmix_selector_replay_rows.csv` (output di `audit/topmix_selector_replay.py`, importato come convenzione di pool e di bootstrap, non ricalcolato dal motore).

## 0. Consistenza con l'artefatto committato

| Grandezza | ricalcolata | attesa (report) | Δ | ok |
|---|---:|---:|---:|:--:|
| candidate | 3422.0000 | 3422.0000 | 0.000000 | ✅ |
| A ammesse | 1865.0000 | 1865.0000 | 0.000000 | ✅ |
| B ammesse | 2020.0000 | 2020.0000 | 0.000000 | ✅ |
| A mostrate · prob media | 0.6639 | 0.6639 | 0.000000 | ✅ |
| A mostrate · hit rate | 0.6198 | 0.6198 | 0.000000 | ✅ |
| A mostrate · Brier | 0.2312 | 0.2312 | 0.000000 | ✅ |
| A mostrate · gap | 0.0441 | 0.0441 | 0.000000 | ✅ |
| A mostrate · mix 1 | 806.0000 | 806.0000 | 0.000000 | ✅ |
| A mostrate · mix 2 | 318.0000 | 318.0000 | 0.000000 | ✅ |
| A mostrate · mix GG | 372.0000 | 372.0000 | 0.000000 | ✅ |
| A mostrate · mix NG | 2.0000 | 2.0000 | 0.000000 | ✅ |
| A mostrate · mix O2.5 | 132.0000 | 132.0000 | 0.000000 | ✅ |
| A mostrate · mix U2.5 | 235.0000 | 235.0000 | 0.000000 | ✅ |
| top 10 · n pool | 74.0000 | 74.0000 | 0.000000 | ✅ |
| top 10 A · n | 740.0000 | 740.0000 | 0.000000 | ✅ |
| top 10 A · slot medi | 10.0000 | 10.0000 | 0.000000 | ✅ |
| top 10 A · prob media | 0.7324 | 0.7324 | 0.000000 | ✅ |
| top 10 A · hit rate | 0.7176 | 0.7176 | 0.000000 | ✅ |
| top 10 A · Brier | 0.2013 | 0.2013 | 0.000000 | ✅ |
| top 10 A · mix 1 | 455.0000 | 455.0000 | 0.000000 | ✅ |
| top 10 A · mix 2 | 110.0000 | 110.0000 | 0.000000 | ✅ |
| top 10 A · mix GG | 58.0000 | 58.0000 | 0.000000 | ✅ |
| top 10 A · mix O2.5 | 72.0000 | 72.0000 | 0.000000 | ✅ |
| top 10 A · mix U2.5 | 45.0000 | 45.0000 | 0.000000 | ✅ |

24/24 grandezze coincidono entro la tolleranza (0.0005 sulle metriche, ±0,5 sui conteggi): le tabelle sotto riutilizzano esattamente le stesse selezioni del replay pubblicato, non una loro reinterpretazione.

## 1. Dove finisce ogni partita candidata (attribuzione degli scarti)

Candidate **3422**, ammesse da A **1865** (54.5%).

| Scartata per | n | prob media mostrata | hit se accettata | gap | Brier |
|---|---:|---:|---:|---:|---:|
| soglia 0,55/0,60 (solo) | 1326 | 55.5% | 57.0% | -1.5% | 0.2452 |
| disaccordo Elo ≥ 0,25 (solo) | 194 | 65.8% | 64.9% | 0.8% | 0.2203 |
| entrambi i vincoli | 37 | 50.7% | 27.0% | 23.7% | 0.2640 |

Lettura: il gate di disaccordo è l'unico scarto che butta via partite **migliori della media delle ammesse** (hit 64.9% contro il 62.0%; Brier 0.2203 contro 0.2312). La soglia invece taglia bande in linea con la propria dichiarazione (hit 57.0% a fronte di 55.5% dichiarata): accettarle porterebbe volume, non valore — ed è, in negativo, ciò che ha reso inutile il selettore B (§3 e §4 del rapporto di replay).

### 1a. Le partite perse solo per il gate, per mercato

n = 194, prob media 65.8%, hit 64.9%, Brier 0.2203. Composizione: 2 107, 1 87.

| Mercato | n | prob | hit | gap | Brier |
|---|---:|---:|---:|---:|---:|
| 2 | 107 | 64.6% | 57.9% | 6.6% | 0.2425 |
| 1 | 87 | 67.3% | 73.6% | -6.3% | 0.1930 |

Il `1` bloccato dal gate ha una frequenza reale **superiore** a quella dichiarata (gap negativo): lì il disaccordo Elo sta scartando informazione, non rumore.

### 1b. Cosa c'è appena sotto la soglia (perché non è un margine)

Partite bocciate dal solo taglio di confidenza (gate rispettato), valutate sul mercato che A avrebbe mostrato:

| Banda | Famiglia | soglia oggi | n | prob media | hit | gap | Brier |
|---|---|---:|---:|---:|---:|---:|---:|
| [0.45, 0.50) | 1X2 | 0.55 | 32 | 48.4% | 46.9% | 1.5% | 0.2508 |
| [0.45, 0.50) | totali | 0.60 | 0 | — | — | — | — |
| [0.50, 0.55) | 1X2 | 0.55 | 161 | 52.9% | 57.1% | -4.2% | 0.2471 |
| [0.50, 0.55) | totali | 0.60 | 410 | 53.6% | 54.9% | -1.3% | 0.2479 |
| [0.55, 0.60) | 1X2 | 0.55 | 0 | — | — | — | — |
| [0.55, 0.60) | totali | 0.60 | 722 | 57.5% | 58.7% | -1.2% | 0.2430 |
| [0.60, 0.65) | 1X2 | 0.55 | 0 | — | — | — | — |
| [0.60, 0.65) | totali | 0.60 | 0 | — | — | — | — |

Nelle bande sotto soglia la frequenza reale è in linea con la probabilità dichiarata (gap fra −1,2 % e −4,2 %; hit massimo osservato 58.7%): il margine lì è **quantità di righe**, non qualità. A conferma: lo slot #10 si chiude in media a **66.6%** di confidence (minimo 56.0%, 10° percentile 64.0% su 74 pool): la fascia 0,55-0,60 contenderebbe uno slot solo nei pool più poveri (minimo 56.0%), mentre il grosso delle candidate scartate sta sotto. È la stessa ragione per cui le ~155 partite recuperate dal selettore B non arrivavano al prodotto (§3 e §4 del rapporto di replay).

## 2. Qualità delle righe ammesse, per mercato

| Mercato | n | prob media | hit | gap | Brier |
|---|---:|---:|---:|---:|---:|
| **tutte** | 1865 | 66.4% | 62.0% | 4.4% | 0.2312 |
| 1 | 806 | 69.4% | 65.5% | 3.9% | 0.2191 |
| GG | 372 | 62.9% | 59.4% | 3.5% | 0.2432 |
| 2 | 318 | 64.8% | 60.4% | 4.4% | 0.2312 |
| U2.5 | 235 | 63.5% | 57.9% | 5.6% | 0.2465 |
| O2.5 | 132 | 66.7% | 59.1% | 7.6% | 0.2434 |
| NG | 2 | 62.4% | 50.0% | 12.4% | 0.2580 |

Il gap (prob − hit) va da GG 3.5% a NG 12.4%: la `confidence` **non è una scala unica fra mercati**, ed è la scala con cui la top 10 viene ordinata (`sorted(..., key=prob, reverse=True)[:10]`). Vedi §5 per perché questo non si corregge gratis.

## 3. Ammesse per fascia di disaccordo (il gate lavora già dentro le ammesse)

| Fascia \|poisson − elo\| | n | prob media | hit | gap | Brier |
|---|---:|---:|---:|---:|---:|
| [0.00, 0.05) | 974 | 64.7% | 60.4% | 4.3% | 0.2372 |
| [0.05, 0.15) | 499 | 68.6% | 64.9% | 3.7% | 0.2212 |
| [0.15, 0.25) | 392 | 67.8% | 62.2% | 5.5% | 0.2289 |

Se il disaccordo fosse segnale, le righe con `|Δ|` alto dovrebbero essere le peggiori delle ammesse. Non lo sono (le bande sono vicine, e la peggior Brier non è quella a disaccordo massimo): il contenuto informativo del disaccordo è già assorbito dal blend `0.6·Poisson + 0.4·Elo`, che **penalizza** la confidence. Il gate hard aggiunge una seconda penalità, questa volta a senso unico (esclusione).

## 4. Top 10: gate come cancellazione vs gate come penalità

Pool: settimana ISO del cutoff + stagione, 5 leghe insieme, taglio a 10 — **74** pool. Stesso identico ordinamento per probabilità; gli insiemi cambiano solo perché una riga con `|Δ| ≥ 0,25` viene ammessa invece di essere scartata.

| Configurazione | righe | slot medi | prob media | hit | Brier |
|---|---:|---:|---:|---:|---:|
| con il gate (produzione) | 740 | 10.00 | 73.2% | 71.8% | 0.2013 |
| senza il gate (stesse soglie) | 740 | 10.00 | 73.8% | 72.6% | 0.1978 |
| **Δ (senza − con)** | 0 | — | 0.6% | 0.8% | -0.0035 |

Bootstrap a blocchi sul pool (blocco = weekend, Δ non appaiato, 74 blocchi, 2000 draw, seed 20260905): ΔBrier = -0.0035 (IC95% -0.0080 … 0.0011), Δhit = 0.8% (IC95% -0.4% … 1.9%).

Composizione: con il gate 1=455, 2=110, O2.5=72, GG=58, U2.5=45 · senza 1=476, 2=134, O2.5=57, GG=40, U2.5=33.

Confidence che chiude il 10° slot, sui pool che lo riempiono: media 66.6%, minimo 56.0% (10° percentile 64.0%).

### 4a. Cosa entra e cosa esce dagli slot

Cambiano **74 slot su 740** (10.0% degli slot riempiti).

| | n | prob | hit | gap | Brier |
|---|---:|---:|---:|---:|---:|
| entrerebbero (oggi bloccate) | 74 | 72.3% | 74.3% | -2.1% | 0.1846 |
| uscirebbero | 74 | 66.6% | 66.2% | 0.4% | 0.2199 |

Mercati in entrata: 1 42, 2 32. Le righe che il gate blocca e che avrebbero un posto in top 10 sono **tutte 1X2** e, su queste due stagioni, più affidabili di quelle che sostituiscono. È il singolo punto con il delta più favorevole emerso dall'analisi; resta **non dimostrato** (intervallo che include lo zero) e su validation riusata: è un candidato per la conferma prospettica, non un cambiamento da varare adesso.

### 4b. Valore marginale dello slot

| | n | prob | hit | gap | Brier |
|---|---:|---:|---:|---:|---:|
| righe 1-10 del pool | 720 | 73.4% | 71.9% | 1.5% | 0.2004 |
| righe 11-15 dello stesso pool | 360 | 64.7% | 56.4% | 8.3% | 0.2521 |

Il taglio a 10 è netto (le 11-15 sono peggio di ~15 pp di hit): **la dimensione 10 non è il problema**; il problema è la graduatoria con cui si riempie.

## 5. Scala dei mercati: perché il bias non si corregge gratis

Bias per mercato (`prob − hit` sulle righe ammesse), stimato **su una sola stagione** e trasferito all'altra (2024/25 ⇄ 2025/26).

| Mercato | bias 2024/25 | bias 2025/26 | scarto |
|---|---:|---:|---:|
| 1 | 3.5% | 4.4% | 0.9 pp |
| 2 | 0.9% | 7.3% | 6.4 pp |
| GG | 3.0% | 3.9% | 0.9 pp |
| O2.5 | 0.8% | 16.6% | 15.8 pp |
| U2.5 | 7.0% | 3.7% | 3.3 pp |

Scarto medio del bias fra le due stagioni: **5.4 pp**. Il gap di scala c'è, ma la sua *entità* non è stabile: è rumore di coda del mercato selezionato, non una costante stimabile su 740 righe.

**Applica il bias dell'altra stagione a `2025/26`**

| | n | prob | hit | gap | Brier |
|---|---:|---:|---:|---:|---:|
| top 10 ordinata su prob grezza (oggi) | 370 | 72.8% | 71.4% | 1.5% | 0.2019 |
| top 10 ordinata su prob − bias | 370 | 72.7% | 70.0% | 2.7% | 0.2056 |

- riordinare con la correzione: ΔBrier +0.0037 (positivo = peggiora), Δhit -1.4 pp
- esporre la probabilità corretta (stesse righe): Brier 0.2023 (Δ +0.0003)

**Applica il bias dell'altra stagione a `2024/25`**

| | n | prob | hit | gap | Brier |
|---|---:|---:|---:|---:|---:|
| top 10 ordinata su prob grezza (oggi) | 370 | 73.7% | 72.2% | 1.5% | 0.2007 |
| top 10 ordinata su prob − bias | 370 | 73.2% | 70.0% | 3.2% | 0.2073 |

- riordinare con la correzione: ΔBrier +0.0066 (positivo = peggiora), Δhit -2.2 pp
- esporre la probabilità corretta (stesse righe): Brier 0.2047 (Δ +0.0040)

In entrambe le direzioni la correzione per mercato **peggiora** Brier: la correzione sbagliata sposta l'ordine più di quanto corregga il livello. Quindi: il margine «rendere confrontabili le scale» è reale (è ciò che fa fallire il selettore B, §6 del rapporto di replay), ma non è incassabile su queste due stagioni — serve una curva di calibrazione per mercato stimata sull'intero campione di base (dove la baseline è già calibrata: gap ≤ 3,1 pp) e una conferma prospettica.

### 5b. Curva di affidabilita' globale (senza toccare la selezione)

Regressione isotona (PAVA) fitata sulle righe ammesse di una stagione e applicata all'altra. Essendo monotona **non cambia l'ordine** della top 10: corregge solo il numero esposto.

| Target (fit sull'altra) | n | prob grezza | hit | Brier grezza | prob calibrata | Brier calibrata | ΔBrier |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2024/25 (fit su 2025/26) | 370 | 73.7% | 72.2% | 0.2007 | 70.9% | 0.2023 | 0.0016 |
| 2025/26 (fit su 2024/25) | 370 | 72.8% | 71.4% | 0.2019 | 70.8% | 0.2027 | 0.0007 |

Lettura: i ΔBrier sono **entro mezzo punto di Brier** (max 1.6 millesimi): la curva globale trasferisce in modo approssimativo, non migliora. Togliendo la sovrastima si passa da un gap di +1,5 pp a uno di segno opposto: si sta **sovra-correggendo** la coda alta, che e' poi l'unica regione che il Top Mix mostra.

Spostamento del numero esposto: -2.8 … -2.0 pp. Conclusione operativa identica in ogni caso: **il numero mostrato non si tocca con questi dati** (coerente con §7 del rapporto di replay: curve di A e B sovrapposte, sovrastima = effetto coda del selezionare il massimo).

## 6. Copertura per lega e mercati mai raggiungibili

| Lega | candidate | ammesse | copertura | prob media | hit | Brier |
|---|---:|---:|---:|---:|---:|---:|
| Bundesliga | 603 | 419 | 69.5% | 67.2% | 63.7% | 0.2284 |
| La Liga | 723 | 380 | 52.6% | 66.5% | 64.7% | 0.2159 |
| Ligue 1 | 610 | 281 | 46.1% | 65.8% | 61.2% | 0.2355 |
| Premier League | 742 | 422 | 56.9% | 65.9% | 59.7% | 0.2387 |
| Serie A | 744 | 363 | 48.8% | 66.3% | 60.3% | 0.2383 |

Mercato scelto (argmax Poisson) sulle candidate, e dopo i filtri:

```
argmax:  {"2": 564, "GG": 998, "U2.5": 705, "1": 985, "O2.5": 163, "NG": 7}
mostrate: {"2": 318, "U2.5": 235, "1": 806, "GG": 372, "O2.5": 132, "NG": 2}
```

`X` non è **mai** argmax e non può superare 0,55: il pareggio è un mercato morto del Top Mix, ed è il mercato con il maggiore disallineamento della baseline (22,1 % dichiarato contro 25,2 % reale, §6 del rapporto di replay). `NG` è vivo solo nominalmente.

## 7. Stato dei dati del replay (per leggere i numeri sopra)

- Elo non disponibile in 0/3422 partite candidate; `team_stats` assente per almeno una squadra in 14 partite (in quei casi il ramo di produzione ripiega su `att=def=1.0`: è il percorso che `fetch_and_calc_top_mix` percorre senza segnalarlo).
- mercati ammessi per partita dal selettore B: 0 → 1402, 1 → 1183, 2 → 614, 3 → 223
- giornate del replay senza xG point-in-time: 10/384 (2.6%), tutte la 1ª giornata → la testa Totali era su fallback-gol solo a campionato appena aperto (dettaglio: {"Bundesliga 2024": 1, "Bundesliga 2025": 1, "La Liga 2024": 1, "La Liga 2025": 1, "Ligue 1 2024": 1, "Ligue 1 2025": 1, "Premier League 2024": 1, "Premier League 2025": 1, "Serie A 2024": 1, "Serie A 2025": 1}).

## 8. Cosa questi numeri NON dimostrano

- **Non sono una taratura.** Nessuna soglia/peso è stata cercata; §4 è il costo di un vincolo esistente, non la bontà del suo rimpiazzo.
- **Sono validation riusata.** 2024/25 + 2025/26 sono le stagioni su cui il motore è già stato scelto (`audit/topmix_selector_audit_protocol.md` §3).
- **Δ non appaiato.** Le due top 10 di §4 contengono partite diverse: il bootstrap sul pool è il minimo che si possa fare, non un test appaiato.
- **74 swap su 740 slot** su 3 422 partite: potenza bassa di proposito, non di trascuratezza.
- **Ricostruzione, non live.** I candidati vengono dai CSV (nessuno snapshot API TIMED/SCHEDULED); `match_id` è la chiave del replay (`Lega|anno|indice`: 3422 distinti su 3422 righe, 0 duplicati), non l'id di football-data.org; forma e calcolo point-in-time con i limiti dichiarati in §9 del rapporto di replay. Gli identici limiti valgono per A e per B, quindi non spostano i confronti interni, ma impediscono di chiamare questo un replay bit-identico del Top Mix live.

## 9. Riproduzione

```bash
python audit/topmix_margins.py                 # scrive audit/results/topmix_margins.{md,json}
python audit/topmix_margins.py --rows <csv> --out <md> --json <json>
python audit/test_topmix_margins.py   # 33 test, solo stdlib (pytest non serve)
```

