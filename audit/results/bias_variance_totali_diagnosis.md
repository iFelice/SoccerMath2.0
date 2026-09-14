# Bias e varianza del marginale Over/Under 2.5 (e confronto GG/NG) — audit sola lettura

*Generato: 2026-09-14T07:52:04+00:00 — script `audit/diagnose_bias_variance_totali.py`, nessuna modifica a SoccerMath/.*

## Oggetto e protocollo

Il marginale **Over/Under 2.5 grezzo di produzione** e' la Poisson indipendente sui lambda puri `att0_pure`/`def0_pure` (modello B di `diagnose_form_totali`, senza forma/mercato): e' il marginale che nell'audit di calibrazione aveva Brier peggiore del predittore costante. GG/NG e' ripetuto come confronto. Stesso walk-forward dei tre audit precedenti: train 2022/23+2023/24 (prime 60 partite/lega escluse), validation 2024/25, test 2025/26, 5 leghe; nessun parametro tocca validation/test.

La versione calibrata usa i parametri **(a,b,c) dell'audit calibration_layer, non ristimati**; riottenerli con la stessa pipeline solo-train e verificare che coincidano e' un controllo di riproducibilita', non una nuova stima.

## Conformita' (verificata, non dichiarata)

| Lega | n righe val+test | max|scarto| P(Over) vs form_totali B | max|scarto| P(GG) | esiti identici |
|---|---:|---:|---:|---|
| Serie A | 760 | 0.0e+00 | 0.0e+00 | si |
| Premier League | 760 | 0.0e+00 | 0.0e+00 | si |
| La Liga | 760 | 0.0e+00 | 0.0e+00 | si |
| Bundesliga | 612 | 0.0e+00 | 0.0e+00 | si |
| Ligue 1 | 612 | 0.0e+00 | 0.0e+00 | si |

Beta riusate vs report: max scarto Over 4.7e-05, GG 2.5e-05 (i parametri sono quelli pubblicati).

## Copertura

| Lega | Train | Validation | Test |
|---|---:|---:|---:|
| Serie A | 700 | 380 | 380 |
| Premier League | 700 | 380 | 380 |
| La Liga | 700 | 380 | 380 |
| Bundesliga | 552 | 306 | 306 |
| Ligue 1 | 626 | 306 | 306 |
| **AGGREGATO** | 3278 | 1752 | 1752 |

## 1. Decomposizione di Murphy (10 decili): Brier = Affidabilita' − Risoluzione + Incertezza

- **Affidabilita' (REL)**: distanza media tra probabilita' predetta e frequenza osservata nel decile (0 = perfetta); e' il costo del bias di livello/forma.
- **Risoluzione (RES)**: quanto la frequenza dei decili si discosta dalla frequenza marginale: e' il SEGNALE per partita che il modello sa estrarre (entra col segno meno, quindi abbassa il Brier).
- **Incertezza (UNC)**: p_base(1−p_base), il Brier irriducibile del predittore costante.
- **D = W − 2C (raffinamento entro-decili)**: passando dal forecast continuo alla media del proprio decile si perde W (varianza di p entro i bin) ma si guadagna 2C (covarianza entro-bin tra p ed esito). D negativo e stabile vorrebbe dire segnale nascosto dentro i bucket; in tabella, dopo calibrazione, |D| resta sotto i 4e-4 in aggregato e cambia segno tra split e leghe: non c'e' raffinamento entro-decile utilizzabile.

### O/U2.5 — Over 2.5

**VALIDATION**

| Scope | Versione | Affidabilita' REL | Risoluzione RES | D=W−2C entro-decili | Incertezza UNC | Brier | REL/UNC | RES/UNC |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **AGGREGATO** | grezzo | 0.0259 | 0.0019 | +0.0015 | 0.2488 | 0.2744 | 10.4% | 0.8% |
| **AGGREGATO** | beta-calibrato | 0.0009 | 0.0019 | +0.0003 | 0.2488 | 0.2482 | 0.4% | 0.8% |
| Serie A | grezzo | 0.0419 | 0.0036 | +0.0017 | 0.2497 | 0.2896 | 16.8% | 1.4% |
| Serie A | beta-calibrato | 0.0067 | 0.0036 | -0.0001 | 0.2497 | 0.2527 | 2.7% | 1.4% |
| Premier League | grezzo | 0.0225 | 0.0050 | +0.0003 | 0.2457 | 0.2634 | 9.1% | 2.0% |
| Premier League | beta-calibrato | 0.0049 | 0.0050 | +0.0000 | 0.2457 | 0.2456 | 2.0% | 2.0% |
| La Liga | grezzo | 0.0134 | 0.0068 | +0.0007 | 0.2498 | 0.2572 | 5.4% | 2.7% |
| La Liga | beta-calibrato | 0.0046 | 0.0068 | +0.0003 | 0.2498 | 0.2479 | 1.8% | 2.7% |
| Bundesliga | grezzo | 0.0352 | 0.0038 | +0.0020 | 0.2404 | 0.2738 | 14.6% | 1.6% |
| Bundesliga | beta-calibrato | 0.0047 | 0.0038 | +0.0011 | 0.2404 | 0.2424 | 2.0% | 1.6% |
| Ligue 1 | grezzo | 0.0543 | 0.0105 | +0.0004 | 0.2469 | 0.2912 | 22.0% | 4.2% |
| Ligue 1 | beta-calibrato | 0.0158 | 0.0109 | -0.0000 | 0.2469 | 0.2518 | 6.4% | 4.4% |

**TEST**

| Scope | Versione | Affidabilita' REL | Risoluzione RES | D=W−2C entro-decili | Incertezza UNC | Brier | REL/UNC | RES/UNC |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **AGGREGATO** | grezzo | 0.0231 | 0.0023 | +0.0002 | 0.2491 | 0.2701 | 9.3% | 0.9% |
| **AGGREGATO** | beta-calibrato | 0.0009 | 0.0023 | -0.0004 | 0.2491 | 0.2473 | 0.4% | 0.9% |
| Serie A | grezzo | 0.0418 | 0.0035 | +0.0034 | 0.2482 | 0.2900 | 16.9% | 1.4% |
| Serie A | beta-calibrato | 0.0072 | 0.0035 | +0.0005 | 0.2482 | 0.2524 | 2.9% | 1.4% |
| Premier League | grezzo | 0.0209 | 0.0041 | +0.0016 | 0.2475 | 0.2659 | 8.4% | 1.6% |
| Premier League | beta-calibrato | 0.0036 | 0.0041 | +0.0003 | 0.2475 | 0.2473 | 1.5% | 1.6% |
| La Liga | grezzo | 0.0163 | 0.0116 | -0.0009 | 0.2500 | 0.2538 | 6.5% | 4.7% |
| La Liga | beta-calibrato | 0.0084 | 0.0116 | -0.0004 | 0.2500 | 0.2464 | 3.4% | 4.7% |
| Bundesliga | grezzo | 0.0412 | 0.0047 | +0.0009 | 0.2312 | 0.2686 | 17.8% | 2.0% |
| Bundesliga | beta-calibrato | 0.0131 | 0.0047 | +0.0001 | 0.2312 | 0.2397 | 5.7% | 2.0% |
| Ligue 1 | grezzo | 0.0271 | 0.0074 | +0.0035 | 0.2493 | 0.2725 | 10.9% | 3.0% |
| Ligue 1 | beta-calibrato | 0.0072 | 0.0074 | +0.0007 | 0.2493 | 0.2498 | 2.9% | 3.0% |


### GG/NG — GG

**VALIDATION**

| Scope | Versione | Affidabilita' REL | Risoluzione RES | D=W−2C entro-decili | Incertezza UNC | Brier | REL/UNC | RES/UNC |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **AGGREGATO** | grezzo | 0.0329 | 0.0014 | +0.0000 | 0.2472 | 0.2788 | 13.3% | 0.6% |
| **AGGREGATO** | beta-calibrato | 0.0025 | 0.0014 | -0.0000 | 0.2472 | 0.2484 | 1.0% | 0.6% |
| Serie A | grezzo | 0.0610 | 0.0108 | -0.0012 | 0.2498 | 0.2987 | 24.4% | 4.3% |
| Serie A | beta-calibrato | 0.0148 | 0.0108 | -0.0006 | 0.2498 | 0.2532 | 5.9% | 4.3% |
| Premier League | grezzo | 0.0204 | 0.0063 | -0.0015 | 0.2446 | 0.2571 | 8.4% | 2.6% |
| Premier League | beta-calibrato | 0.0055 | 0.0063 | -0.0005 | 0.2446 | 0.2432 | 2.3% | 2.6% |
| La Liga | grezzo | 0.0322 | 0.0009 | -0.0011 | 0.2482 | 0.2785 | 13.0% | 0.3% |
| La Liga | beta-calibrato | 0.0024 | 0.0009 | -0.0004 | 0.2482 | 0.2494 | 1.0% | 0.3% |
| Bundesliga | grezzo | 0.0445 | 0.0076 | +0.0001 | 0.2453 | 0.2822 | 18.1% | 3.1% |
| Bundesliga | beta-calibrato | 0.0077 | 0.0073 | -0.0001 | 0.2453 | 0.2456 | 3.1% | 3.0% |
| Ligue 1 | grezzo | 0.0427 | 0.0091 | -0.0010 | 0.2453 | 0.2780 | 17.4% | 3.7% |
| Ligue 1 | beta-calibrato | 0.0140 | 0.0091 | +0.0002 | 0.2453 | 0.2504 | 5.7% | 3.7% |

**TEST**

| Scope | Versione | Affidabilita' REL | Risoluzione RES | D=W−2C entro-decili | Incertezza UNC | Brier | REL/UNC | RES/UNC |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **AGGREGATO** | grezzo | 0.0272 | 0.0029 | +0.0003 | 0.2485 | 0.2731 | 10.9% | 1.2% |
| **AGGREGATO** | beta-calibrato | 0.0021 | 0.0029 | -0.0000 | 0.2485 | 0.2478 | 0.9% | 1.2% |
| Serie A | grezzo | 0.0375 | 0.0014 | +0.0006 | 0.2478 | 0.2845 | 15.1% | 0.5% |
| Serie A | beta-calibrato | 0.0082 | 0.0030 | +0.0002 | 0.2478 | 0.2531 | 3.3% | 1.2% |
| Premier League | grezzo | 0.0148 | 0.0025 | +0.0016 | 0.2463 | 0.2603 | 6.0% | 1.0% |
| Premier League | beta-calibrato | 0.0017 | 0.0025 | +0.0006 | 0.2463 | 0.2461 | 0.7% | 1.0% |
| La Liga | grezzo | 0.0345 | 0.0119 | +0.0001 | 0.2457 | 0.2683 | 14.1% | 4.9% |
| La Liga | beta-calibrato | 0.0110 | 0.0119 | +0.0000 | 0.2457 | 0.2448 | 4.5% | 4.9% |
| Bundesliga | grezzo | 0.0584 | 0.0051 | +0.0013 | 0.2362 | 0.2908 | 24.7% | 2.2% |
| Bundesliga | beta-calibrato | 0.0117 | 0.0051 | +0.0001 | 0.2362 | 0.2429 | 5.0% | 2.2% |
| Ligue 1 | grezzo | 0.0186 | 0.0064 | +0.0008 | 0.2500 | 0.2629 | 7.4% | 2.5% |
| Ligue 1 | beta-calibrato | 0.0079 | 0.0064 | +0.0003 | 0.2500 | 0.2518 | 3.2% | 2.5% |


### Test di coerenza interna (monotonia, identita' Murphy)

Una mappa di calibrazione monotona lascia immutato l'ordinamento delle partite; con decili a frequenza uguale i bin contengono le stesse identiche partite prima e dopo la calibrazione, quindi la Risoluzione deve restare invariata e deve calare solo l'Affidabilita'. Chiusura contabile: per la previsione sostituita dalla media del proprio decile vale Brier_bin = REL − RES + UNC; per la previsione continua Brier = Brier_bin + D con D = W − 2C, dove W e' la varianza di p entro i decili e C la covarianza media entro-decile tra p ed esito: D negativo significa che esiste discriminazione anche dentro i bucket (un canale di segnale che i decili non vedono).

| Evento | max errore identita' | ΔRISOLUZIONE max | Spearman min | partite cambiate di decile (max) | inversioni di rango (V+T, aggregato) |
|---|---:|---:|---:|---:|---:|
| O/U2.5 | 8.3e-17 | 4.7e-04 | 1.000000 | 0.33% | 0 |
| GG/NG | 1.1e-16 | 1.7e-03 | 0.990003 | 7.89% | 31 |

Sull'oggetto primario (Over 2.5) il test e' perfetto: ΔRisoluzione 0.0e+00 in aggregato (max per-lega 4.7e-04, per soli patiti al bordo dei decili), Spearman 1.000000, nessuna inversione di rango. Su GG/NG si contano 31 inversioni di rango in aggregato, tutte a p<0.0505, ovvero nella coda che riguarda 0.91% delle righe: il coefficiente beta a=-0.031 e' leggermente negativo e la mappa, monotona crescente sull'intervallo di probabilita' usato, si ripiega solo sotto p*=a/(a−b)=0.0501 (reti inviolabili quasi impossibili); l'effetto su Risoluzione e' 4.5e-05 in aggregato (max per-lega 1.7e-03), sostanzialmente zero. Gli scarti per-lega sono effetti di confine dei decili (fino al 7.9% delle righe si sposta di bucket), non segnale creato dalla mappa: una trasformazione monotona non puo' creare risoluzione.

| Evento | Split | W entro-decili | C cov entro-decili | D=W−2C | REL grezzo→cal | RES grezzo→cal | Brier grezzo→cal (continuo) | Brier_bin calibrato | UNC |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| O/U2.5 | validation | 0.0001 | -0.0001 | +0.0003 | 0.0259→0.0009 | 0.0019→0.0019 | 0.2744→0.2482 | 0.2478 | 0.2488 |
| O/U2.5 | test | 0.0003 | +0.0003 | -0.0004 | 0.0231→0.0009 | 0.0023→0.0023 | 0.2701→0.2473 | 0.2477 | 0.2491 |
| GG/NG | validation | 0.0001 | +0.0001 | -0.0000 | 0.0329→0.0025 | 0.0014→0.0014 | 0.2788→0.2484 | 0.2484 | 0.2472 |
| GG/NG | test | 0.0001 | +0.0001 | -0.0000 | 0.0272→0.0021 | 0.0029→0.0029 | 0.2731→0.2478 | 0.2478 | 0.2485 |

Lettura: REL crolla di 1-2 ordini di grandezza mentre RES e' immutata (Over) o quasi (GG): la beta calibration rimuove il bias di livello e non tocca il segnale. Ma RES e' minuscola anche da grezza (0.001-0.003 contro UNC~0.25), e anche il termine di raffinamento entro-decili D non regala nulla: la colonna C (covarianza tra p od esito dentro i bucket) e' circa zero, quindi il forecast continuo non e' migliore della media del proprio decile. Il problema non e' la calibrazione, e' l'assenza di segnale per partita.

## 2. Risoluzione in termini assoluti

La varianza delle probabilita' predette misura quanto il modello distingue le partite, indipendentemente dal bias: anche un predittore perfettamente calibrato ma piatto non e' utile. Lo std massimo teorico e' sqrt(UNC)=sqrt(p_base(1−p_base)); Var(p)/UNC e' la frazione di varianza 'usata' rispetto a un segno binario perfetto, RES/UNC la frazione di incertezza realmente spiegata dai decili.

| Evento | Split | Versione | std P | std max sqrt(UNC) | Var(P)/UNC | RES/UNC |
|---|---|---|---:|---:|---:|---:|
| O/U2.5 | validation | grezzo | 0.1917 | 0.4988 | 14.8% | 0.8% |
| O/U2.5 | validation | beta-calibrato | 0.0373 | 0.4988 | 0.6% | 0.8% |
| O/U2.5 | test | grezzo | 0.1925 | 0.4991 | 14.9% | 0.9% |
| O/U2.5 | test | beta-calibrato | 0.0435 | 0.4991 | 0.8% | 0.9% |
| GG/NG | validation | grezzo | 0.1597 | 0.4972 | 10.3% | 0.6% |
| GG/NG | validation | beta-calibrato | 0.0445 | 0.4972 | 0.8% | 0.6% |
| GG/NG | test | grezzo | 0.1635 | 0.4985 | 10.8% | 1.2% |
| GG/NG | test | beta-calibrato | 0.0449 | 0.4985 | 0.8% | 1.2% |

Per lega (RES/UNC, grezzo → calibrato):

| Evento | Split | Serie A | Premier League | La Liga | Bundesliga | Ligue 1 |
|---|---|---:|---:|---:|---:|---:|
| O/U2.5 | validation | 1.4%→1.4% | 2.0%→2.0% | 2.7%→2.7% | 1.6%→1.6% | 4.2%→4.4% |
| O/U2.5 | test | 1.4%→1.4% | 1.6%→1.6% | 4.7%→4.7% | 2.0%→2.0% | 3.0%→3.0% |
| GG/NG | validation | 4.3%→4.3% | 2.6%→2.6% | 0.3%→0.3% | 3.1%→3.0% | 3.7%→3.7% |
| GG/NG | test | 0.5%→1.2% | 1.0%→1.0% | 4.9%→4.9% | 2.2%→2.2% | 2.5%→2.5% |

## 3. Deriva temporale dei tassi reali

Over 2.5 rate, GG rate e gol/partita medi per split (IC 95% bootstrap). Il train e' il periodo su cui i parametri di calibrazione sono fissati; validation e test non possono ritoccarli.

### Aggregato 5 leghe

| Split | n | Over 2.5 rate (IC 95%) | GG rate (IC 95%) | gol/partita |
|---|---:|---|---|---:|
| train | 3278 | 0.534 [0.517; 0.550] | 0.545 [0.527; 0.561] | 2.823 |
| validation | 1752 | 0.534 [0.511; 0.558] | 0.553 [0.529; 0.575] | 2.827 |
| test | 1752 | 0.530 [0.507; 0.554] | 0.539 [0.515; 0.563] | 2.765 |

### Over 2.5 rate per lega e split

| Lega | train (IC) | validation (IC) | test (IC) | delta test−train |
|---|---|---|---|---:|
| Serie A | 0.474 [0.436; 0.511] | 0.482 [0.432; 0.532] | 0.458 [0.405; 0.511] | -0.016 |
| Premier League | 0.590 [0.553; 0.627] | 0.566 [0.513; 0.613] | 0.550 [0.500; 0.597] | -0.040 |
| La Liga | 0.460 [0.424; 0.497] | 0.487 [0.434; 0.537] | 0.500 [0.450; 0.550] | +0.040 |
| Bundesliga | 0.625 [0.583; 0.665] | 0.598 [0.546; 0.650] | 0.637 [0.582; 0.690] | +0.012 |
| Ligue 1 | 0.542 [0.502; 0.578] | 0.556 [0.500; 0.614] | 0.526 [0.471; 0.585] | -0.015 |

### GG rate per lega e split

| Lega | train | validation | test | delta test−train |
|---|---:|---:|---:|---:|
| Serie A | 0.510 | 0.516 | 0.453 | -0.057 |
| Premier League | 0.564 | 0.574 | 0.561 | -0.004 |
| La Liga | 0.501 | 0.542 | 0.566 | +0.064 |
| Bundesliga | 0.612 | 0.569 | 0.618 | +0.005 |
| Ligue 1 | 0.550 | 0.569 | 0.507 | -0.043 |

### Livello predetto vs osservato (grezzo e calibrato)

| Evento | Split | P media grezza | P media calibrata | frequenza reale | bias grezzo | bias calibrato |
|---|---|---:|---:|---:|---:|---:|
| O/U2.5 | validation | 0.5133 | 0.5338 | 0.5342 | -0.0210 | -0.0005 |
| O/U2.5 | test | 0.5002 | 0.5301 | 0.5303 | -0.0301 | -0.0002 |
| GG/NG | validation | 0.4536 | 0.5442 | 0.5525 | -0.0989 | -0.0083 |
| GG/NG | test | 0.4427 | 0.5416 | 0.5388 | -0.0962 | +0.0028 |

**Lettura.** Aggregato, il tasso Over e' piatto (0.534 → 0.534 → 0.530) mentre i gol/partita scendono leggermente nel test (2.823 → 2.827 → 2.765, -0.059); per lega gli spostamenti test−train sono tra -0.040 e +0.040, dentro l'ampiezza degli IC 95% (circa ±0.05): non c'e' un trend aggregato certo, ma il livello VAGA per lega e periodo. Soprattutto, la sottostima grezza dell'Over esiste gia' verso la base train (-0.021/-0.030 su validation/test, con tasso train praticamente uguale): e' dunque un difetto STRUTTURALE di soglia della Poisson indipendente (code troppo leggere), non prodotto dalla deriva. La deriva spiega invece perche' una calibrazione statica vada riaggiustata periodicamente: insegue un livello che si muove per lega.

## 4. Conclusione esplicita: quanta risoluzione resta?

**Over 2.5 (oggetto primario)**

- Grezzo: Affidabilita' 0.0259/0.0231 (val/test), Risoluzione 0.0019/0.0023, Incertezza 0.2488/0.2491; il Brier grezzo (0.2744/0.2701) e' sopra l'Incertezza: il costo di affidabilita' (bias di livello) piu' che annulla il segnale.
- Beta-calibrato: Affidabilita' ridotta a 0.0009/0.0009, Risoluzione invariata 0.0019/0.0023 (sull'Over i test di coerenza sopra danno Delta_RES=0.0e+00 in aggregato, Spearman 1.0000; il massimo scarto per-lega e' 4.7e-04 e nasce da patiti di probabilita' sul bordo del decile); il Brier calibrato (0.2482/0.2473) e' praticamente uguale all'Incertezza (skill vs costante +0.3%/+0.7%).
- In valori assoluti, dopo calibrazione lo std di P(Over) e' 0.037/0.043 contro un massimo teorico 0.499/0.499; la frazione di incertezza spiegata dai decili e' 0.8%/0.9% (grezzo: 0.8%/0.9%).

**GG/NG (confronto)**

- Risoluzione post-calibrazione 0.0014/0.0029 = 0.6%/1.2% dell'incertezza; stesso ordine di grandezza di Over.

**Deriva.** Over rate aggregato: train 0.534, validation 0.534, test 0.530 (gol/partita 2.823 → 2.827 → 2.765); la tabella §3 mostra per lega quanto il livello si muove tra i tre periodi: una calibrazione statica fissata sul train insegue un bersaglio mobile, il che spiega perche' serva riaggiustare periodicamente anche quando il segnale per partita resta nullo.

### VERDETTO: **la Risoluzione residua post-calibrazione e' vicina a zero — nessun segnale da suddividere in bucket, la pista 3 rischia di aggiungere solo rumore.**

Dopo aver rimosso il bias di livello con la mappa monotona (che per costruzione conserva tutto il segnale esistente, come dimostrato su Over da Delta_RES=0, Spearman=1 e bin identici), i decili spiegano solo il 0.8%/0.9% dell'incertezza intrinseca su validation/test, e il Brier calibrato coincide col predittore costante. Tradotto: la testa Totali grezza, nella ricostruzione a snapshot xG di questi audit, non sa dire quali partite saranno Over oltre alla frequenza di campionato; l'unico difetto reale e' il LIVELLO, e anche quello e' instabile per deriva temporale (§3). Suddividere in bucket/selezioni queste probabilita' (pista 3) non si appoggia a potere discriminante residuo: qualsiasi ordinamento per bucket sarebbe etichettatura di rumore. Prima di riaprire la pista servirebbe una fonte predittiva con risoluzione propria (es. engine point-in-time live, che usa finestre e shrinkage diversi dall'snapshot statico), e soltanto DOPO andrebbe verificata nuovamente la decomposizione. Nessuna modifica di produzione e' autorizzata da questo audit.

## Limiti dichiarati

1. **Snapshot xG statico**: i lambda sono quelli della replica di audit (come nei tre audit precedenti), non la fonte point-in-time live (`att0_pure/def0_p` con F_season/PT19_CAP e shrinkage): la risoluzione del motore di produzione potrebbe differire, e la conclusione sulla pista 3 vale per questa ricostruzione.
2. **Decili a frequenza uguale**: e' la scelta richiesta e rende il test di invarianza della Risoluzione esatto; bin a bordi fissi darebbero numeri leggermente diversi ma non cambierebbero il rapporto di grandezza.
3. **Beta pooled**: un solo terno (a,b,c) per mercato, fissato sul train; la deriva per lega non e' corretta e si vede in §3.
4. **Nessuna quota**: si decompone accuratezza probabilistica, non convenienza economica.

## Riferimenti incrociati

- `audit/results/form_totali_diagnosis.md`: marginale grezzo modello B;
- `audit/results/calibration_layer_diagnosis.md`: parametri beta riusati qui, collasso sul predittore costante;
- `audit/results/overdispersion_condizionale_diagnosis.md`: NegBin sulle soglie e fallimento su GG;
- `audit/results/combo_1x2_totali_diagnosis.md`: walk-forward e cross-check condivisi.

