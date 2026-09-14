# Prior di shrinkage adattivo a n (testa Totali e 1X2) — audit sola lettura

*Generato: 2026-09-14T14:25:49+00:00 — script `audit/diagnose_prior_adattivo.py`, nessuna scrittura su SoccerMath/.*

## Oggetto e protocollo

`app._shrunk_ratio(observed, expected, n, prior=PRIOR_MATCHES=6)` contrae ogni rapporto di forza verso la media di lega con un peso fisso equivalente a 6 partite, qualunque sia il campione n. Si testa se un prior **adattivo a n** — forte con pochi dati, debole con tanti — batta la costante. L'harness e' quella del confronto motore-live-vs-replica: chiamata DIRETTA a `get_league_engine()` in replay point-in-time (CSV troncati per data, cutoff nella vera F_season), non la replica offline statica. Walk-forward: train 2022/23+2023/24 con le prime 60 partite/lega solo in stato, validation 2024/25, test 2025/26, 5 leghe; ogni scelta numerica e' fatta SOLAMENTE su train.

Famiglie: **A** k costante {2,4,6,8,10,14,20} (6 = produzione); **B** k per bucket di n in-stagione [0-3],[4-8],[>8] (7^3=343 terne, la monotonia e' verificata sui risultati, non imposta); **C** k continuo k0/(1+n/tau), 6x6=36 configurazioni. Criterio di scelta su train: Brier medio dei due marginali Totali (Over 2.5 e GG). Valutazione held-out con IC bootstrap 2000 stratificato per lega, appaiato, sulla differenza vs k=6.

## Conformita' (verificata, non dichiarata)

| Controllo | Esito |
|---|---:|
| Validazione harness: replay a oggi vs produzione non patchata (tutte le stats) | 0.0e+00 |
| Builder dei ratio (tutti i k, tutte le giornate) vs motore reale a k=6, max scarto | 2.2e-16 |
| `vec_market` vettorizzato vs `app._poisson_market`, max scarto | 1.3e-15 |
| Motore VERO con `_shrunk_ratio` patchato sulla strategia 3-bucket vincente vs builder, max scarto | 2.2e-16 |
| idem per la strategia continua vincente | 2.2e-16 |
| Squadre-stato con n F_season diverso dal conteggio CSV in-stagione | 44/43132 |

I primi tre controlli provano che l'harness e il builder riproducono la produzione; gli ultimi due che le strategie adaptive qui valutate sono ESATTAMENTE cio' che uscirebbe dal motore reale se il prior cambiasse (il monkeypatch sostituisce solo il peso k dentro la formula identica).

Copertura del replay (le partite saltate sono neopromosse alla prima giornata: il motore al cutoff non ha ancora la squadra nel dizionario e la produzione stessa usa default neutri 1.0, come nei 14 casi censiti in motore_live_vs_replica; qui si escludono per non dare un k a una squadra senza stato):

| Lega | partite eleggibili | valutate | saltate |
|---|---:|---:|---:|
| Serie A | 1460 | 1453 | 7 |
| Premier League | 1460 | 1455 | 5 |
| La Liga | 1460 | 1454 | 6 |
| Bundesliga | 1164 | 1159 | 5 |
| Ligue 1 | 1238 | 1234 | 4 |
| **totale** | **6782** | **6755** | **27** |

I 44 disallineamenti su 43132 team-stato tra n F_season e conteggio CSV in-stagione sono differenze di 1 partita dovute a partite posticipate/recuperate presenti in una delle due fonti (es. Udinese-Roma nell'aprile 2024); impattano l'assegnazione del bucket solo in caso di attraversamento delle soglie 3/8 e non cambiano alcuna conclusione.

## 1. Distribuzione di n (partite gia' giocate in stagione)

n conteggiato al cutoff, separatamente casa/trasferta, per split:

| Split | lato | bucket [0-3] | [4-8] | [>8] | n mediano |
|---|---|---:|---:|---:|---:|
| train | casa | 172 | 383 | 2710 | 20 |
| train | trasferta | 174 | 379 | 2712 | 20 |
| validation | casa | 176 | 240 | 1328 | 18 |
| validation | trasferta | 176 | 240 | 1328 | 18 |
| test | casa | 179 | 240 | 1327 | 18 |
| test | trasferta | 179 | 240 | 1327 | 18 |

Nota sulla testa 1X2: la sua sorgente xG e' l'istantanea statica `xg_*.json` (non esiste un archivio point-in-time per quella testa; solo F_season, che alimenta i Totali, e' storico). Quell'istantanea oggi contiene 2-3 partite per tutte le squadre, quindi la chiamata reale a `_shrunk_ratio` per la 1X2 passa sempre n=2-3: su questa testa l'adattivita' a n e' di fatto quasi costante (bucket basso), e il confronto 1X2 va letto di conseguenza. E' il comportamento del motore vero, non un'approssimazione dell'audit.

## 2. Scelta su TRAIN (mai validation/test)

Brier Totali medio (Over+GG) su train, in punti x10000:

| Strategia | parametri | Brier train x1e4 | vs k=6 |
|---|---|---:|---:|
| k=6 produzione | costante | 2430.6 | — |
| k costante | k=2 | 2439.1 | +8.5 |
| k costante | k=4 | 2432.8 | +2.2 |
| k costante | k=8 | 2429.9 | -0.7 |
| k costante | k=10 | 2430.0 | -0.6 |
| k costante | k=14 | 2430.9 | +0.3 |
| k costante | k=20 | 2433.0 | +2.4 |
| **3 bucket [0-3],[4-8],[>8]** | k = (20, 4, 10) | 2429.1 | -1.5 |
| **continuo k0/(1+n/tau)** | k0=40, tau=12 | 2492.6 | +62.0 |

**ANOMALIA DI MONOTONIA**: la terna preferita (20, 4, 10) NON e' non-crescente con n. Il bucket [0-3] chiede molto shrinkage (k=20, conforme all'ipotesi), il bucket [4-8] pochissimo (k=4) e il bucket [>8] risale a k=10: una forma a U, non un decadimento. Non viene scartata dalla griglia, ma e' il classico andamento di un minimum trovato a caso nel rumore di train (il guadagno e' di 1.5 x1e4 e, come si vede in §3, non si trasferisce); e' comunque il segnale che l'ipotesi 'prior debole con tanti dati' non e' supportata in questo storico.

I 3 bucket battono il continuo su train di 63.6 punti x1e4 (il continuo e' anzi peggiore della baseline, v. sotto): la forma discreta e' la candidata, ma decide l'held-out.

**La famiglia continua e' scartata gia' su train**: la sua migliore configurazione (k0=40, tau=12, per giunta ai bordi della griglia: k0 e tau massimi, cioe' il decadimento piu' lento possibile) ha Brier 2492.6, PEGGIORE del k=6 (2430.6). Una k che decade a zero con l'aumentare di n contraddice questi dati: il Brier non vuole meno shrinkage sui campioni abbondanti, se mai il contrario.

Robustezza della griglia discreta su train: 92 terne su 343 hanno Brier inferiore a k=6, con guadagno massimo -1.5 x1e4: un bacino di configurazioni quasi equivalenti, tipico segnale di assenza di struttura adattiva robusta.

## 3. Validation e test: Totali (aggregato 5 leghe)

Metriche assolute del k=6 di produzione e delta delle varianti con IC 95% bootstrap (2000, stratificato per lega, appaiato). Delta negativo = migliora.

### Livelli assoluti k=6

| Split | Brier Over | Brier GG | Brier Totali | LL Over | LL GG | Brier 1X2 | LL 1X2 |
|---|---:|---:|---:|---:|---:|---:|---:|
| validation | 0.2437 | 0.2481 | 0.2459 | 0.6806 | 0.6893 | 0.5985 | 1.0026 |
| test | 0.2450 | 0.2466 | 0.2458 | 0.6830 | 0.6864 | 0.5979 | 1.0015 |

### Delta vs k=6 (Brier/LL)

| Variante | split | ΔBrier Over | ΔBrier GG | ΔBrier Totali | ΔLL Over | ΔLL GG |
|---|---|---|---|---|---|---|
| k costante ottimo k=8 | validation | -0.0001 [-0.0004; +0.0002] | -0.0004 [-0.0008; -0.0001] | **-0.0003 [-0.0005; +0.0000]** | -0.0003 [-0.0010; +0.0004] | -0.0009 [-0.0015; -0.0002] |
| k costante ottimo k=8 | test | -0.0003 [-0.0006; -0.0000] | -0.0002 [-0.0005; +0.0001] | **-0.0002 [-0.0005; +0.0000]** | -0.0006 [-0.0012; +0.0000] | -0.0004 [-0.0010; +0.0003] |
| 3 bucket (20, 4, 10) | validation | +0.0000 [-0.0007; +0.0008] | -0.0000 [-0.0007; +0.0006] | **+0.0000 [-0.0006; +0.0006]** | +0.0000 [-0.0014; +0.0016] | -0.0000 [-0.0014; +0.0013] |
| 3 bucket (20, 4, 10) | test | -0.0002 [-0.0008; +0.0005] | +0.0002 [-0.0004; +0.0008] | **+0.0000 [-0.0005; +0.0005]** | -0.0004 [-0.0018; +0.0010] | +0.0004 [-0.0009; +0.0016] |
| continuo k0=40,tau=12 | validation | +0.0063 [+0.0016; +0.0108] | +0.0079 [+0.0038; +0.0118] | **+0.0071 [+0.0035; +0.0109]** | +0.0134 [+0.0040; +0.0227] | +0.0163 [+0.0081; +0.0246] |
| continuo k0=40,tau=12 | test | +0.0095 [+0.0053; +0.0139] | +0.0058 [+0.0020; +0.0097] | **+0.0076 [+0.0040; +0.0111]** | +0.0202 [+0.0115; +0.0290] | +0.0119 [+0.0042; +0.0201] |

## 4. Stessa lente sulla testa 1X2 (aggregato)

| Variante | split | ΔBrier 1X2 | ΔLogLoss 1X2 |
|---|---|---|---|
| k costante ottimo k=8 | validation | -0.0022 [-0.0033; -0.0011] | -0.0036 [-0.0054; -0.0019] |
| k costante ottimo k=8 | test | -0.0012 [-0.0023; -0.0002] | -0.0020 [-0.0037; -0.0004] |
| 3 bucket (20, 4, 10) | validation | -0.0025 [-0.0058; +0.0005] | -0.0032 [-0.0085; +0.0018] |
| 3 bucket (20, 4, 10) | test | -0.0002 [-0.0035; +0.0030] | -0.0001 [-0.0052; +0.0048] |
| continuo k0=40,tau=12 | validation | -0.0043 [-0.0090; +0.0004] | -0.0067 [-0.0138; +0.0002] |
| continuo k0=40,tau=12 | test | +0.0001 [-0.0043; +0.0046] | -0.0002 [-0.0068; +0.0069] |

## 5. Per lega (delta Brier, IC 95%)

| Variante | split | Lega | ΔBrier Totali | ΔBrier 1X2 |
|---|---|---|---|---|
| k costante ottimo k=8 | validation | Serie A | -0.0006 [-0.0013; +0.0000] | -0.0034 [-0.0060; -0.0008] |
| k costante ottimo k=8 | validation | Premier League | -0.0006 [-0.0010; -0.0001] | -0.0014 [-0.0036; +0.0007] |
| k costante ottimo k=8 | validation | La Liga | +0.0001 [-0.0006; +0.0007] | -0.0021 [-0.0044; +0.0002] |
| k costante ottimo k=8 | validation | Bundesliga | +0.0004 [-0.0003; +0.0011] | -0.0001 [-0.0026; +0.0023] |
| k costante ottimo k=8 | validation | Ligue 1 | -0.0005 [-0.0011; +0.0001] | -0.0040 [-0.0066; -0.0016] |
| k costante ottimo k=8 | test | Serie A | -0.0000 [-0.0005; +0.0004] | -0.0008 [-0.0033; +0.0016] |
| k costante ottimo k=8 | test | Premier League | -0.0005 [-0.0011; +0.0001] | -0.0010 [-0.0030; +0.0010] |
| k costante ottimo k=8 | test | La Liga | -0.0004 [-0.0010; +0.0002] | -0.0017 [-0.0041; +0.0007] |
| k costante ottimo k=8 | test | Bundesliga | -0.0002 [-0.0008; +0.0003] | -0.0011 [-0.0036; +0.0013] |
| k costante ottimo k=8 | test | Ligue 1 | +0.0001 [-0.0006; +0.0007] | -0.0016 [-0.0041; +0.0008] |
| 3 bucket (20, 4, 10) | validation | Serie A | -0.0010 [-0.0025; +0.0003] | -0.0071 [-0.0156; +0.0019] |
| 3 bucket (20, 4, 10) | validation | Premier League | -0.0005 [-0.0015; +0.0004] | -0.0029 [-0.0102; +0.0040] |
| 3 bucket (20, 4, 10) | validation | La Liga | +0.0013 [+0.0002; +0.0026] | +0.0034 [-0.0002; +0.0070] |
| 3 bucket (20, 4, 10) | validation | Bundesliga | +0.0004 [-0.0010; +0.0019] | +0.0031 [-0.0044; +0.0104] |
| 3 bucket (20, 4, 10) | validation | Ligue 1 | -0.0001 [-0.0014; +0.0012] | -0.0094 [-0.0182; -0.0011] |
| 3 bucket (20, 4, 10) | test | Serie A | +0.0004 [-0.0006; +0.0014] | +0.0012 [-0.0069; +0.0097] |
| 3 bucket (20, 4, 10) | test | Premier League | -0.0005 [-0.0015; +0.0007] | -0.0013 [-0.0083; +0.0055] |
| 3 bucket (20, 4, 10) | test | La Liga | -0.0001 [-0.0012; +0.0010] | +0.0021 [-0.0015; +0.0061] |
| 3 bucket (20, 4, 10) | test | Bundesliga | -0.0005 [-0.0017; +0.0006] | -0.0009 [-0.0089; +0.0065] |
| 3 bucket (20, 4, 10) | test | Ligue 1 | +0.0007 [-0.0007; +0.0022] | -0.0026 [-0.0110; +0.0061] |
| continuo k0=40,tau=12 | validation | Serie A | +0.0048 [-0.0032; +0.0132] | -0.0068 [-0.0177; +0.0043] |
| continuo k0=40,tau=12 | validation | Premier League | +0.0035 [-0.0034; +0.0107] | -0.0030 [-0.0119; +0.0056] |
| continuo k0=40,tau=12 | validation | La Liga | +0.0137 [+0.0051; +0.0225] | -0.0024 [-0.0131; +0.0086] |
| continuo k0=40,tau=12 | validation | Bundesliga | +0.0030 [-0.0058; +0.0120] | +0.0032 [-0.0063; +0.0129] |
| continuo k0=40,tau=12 | validation | Ligue 1 | +0.0101 [+0.0024; +0.0181] | -0.0128 [-0.0233; -0.0019] |
| continuo k0=40,tau=12 | test | Serie A | +0.0059 [-0.0011; +0.0129] | +0.0026 [-0.0081; +0.0137] |
| continuo k0=40,tau=12 | test | Premier League | +0.0050 [-0.0016; +0.0123] | -0.0010 [-0.0091; +0.0071] |
| continuo k0=40,tau=12 | test | La Liga | +0.0051 [-0.0024; +0.0128] | +0.0005 [-0.0107; +0.0111] |
| continuo k0=40,tau=12 | test | Bundesliga | +0.0129 [+0.0047; +0.0218] | -0.0000 [-0.0092; +0.0091] |
| continuo k0=40,tau=12 | test | Ligue 1 | +0.0109 [+0.0024; +0.0188] | -0.0021 [-0.0125; +0.0080] |

## 6. Conclusione esplicita

Su train le candidate adaptive muovono il Brier Totali di -1.5 (3 bucket) e +62.0 (continuo) punti x1e4 contro k=6; miglior costante k=8 (-0.7).

### VERDETTO: **mi fermo — nessuna versione adattiva batte k=6 fisso con IC fuori dallo zero su ENTRAMBI validation e test in modo coerente.**

La strategia 3 bucket (20, 4, 10) ha ΔBrier Totali +0.0000 [-0.0006; +0.0006] in validation e +0.0000 [-0.0005; +0.0005] nel test: il micro-guadagno di train (-1.5 x1e4) NON si trasferisce (delta held-out ~0, IC attorno allo zero su entrambi gli split), coerentemente col fatto che la terna e' non monotona e quindi insegue rumore di train. Il continuo k0=40,tau=12 perde gia' in train e peggiora in modo netto held-out (+0.0071 [+0.0035; +0.0109] / +0.0076 [+0.0040; +0.0111]): l'ipotesi 'meno shrinkage con piu' dati' e' smentita, non supportata.

**PRIOR_MATCHES=6 resta la scelta di produzione per l'oggetto di questo audit (prior adattivo).** La zona di equivalenza tra costanti 6/8/10 trovata in passato si estende anche a un prior funzione di n: il Brier Totali non e' sensibile alla legge di contrazione. Unico segnale coerente, ma NON adattivo: la costante k=8 (migliore in train) mostra ΔBrier Totali -0.0003 [-0.0005; +0.0000] / -0.0002 [-0.0005; +0.0000] (IC che tocca lo zero) e un piccolo miglioramento della sola 1X2 con IC fuori zero su entrambi gli split (-0.0022 [-0.0033; -0.0011] / -0.0012 [-0.0023; -0.0002]). E' una questione costante-vs-costante, estranea all'ipotesi adattiva: se ne tiene nota come eventuale micro-ritocco, non come evidenza per un k(n). Eventuali miglioramenti sostanziali dei Totali passano per una fonte piu' informativa (piu' risoluzione, v. audit motore-live), non per la taratura del peso di shrinkage.


## Limiti dichiarati

1. **Scelta su Brier Totali**: la griglia ottimizza il Brier medio di Over e GG in aggregato 5 leghe (ogni partita peso uguale); una selezione per mercato o per lega potrebbe dare parametri diversi, ma violerebbe la disciplina di un solo modello globale scelto su train.
2. **n della 1X2 congelato dall'istantanea**: la sorgente xG della testa 1X2 non ha archivio point-in-time (n=2-3 per tutte le squadre oggi); l'adattivita' su quella testa e' quindi di fatto non esercitata. Il test adattivo pieno riguarda i Totali via F_season.
3. **Bucket e griglie fissate a priori**: [0-3]/[4-8]/[>8] e le griglie di k/k0/tau sono scelte prima di guardare validation/test; forme funzionali diverse (es. decadimento esponenziale) non sono esplorate.
4. **Cutoff a giorno** (`previous_day`) e ambiente bare-mode: come nell'audit motore-live-vs-replica.

## Riferimenti incrociati

- `audit/results/motore_live_vs_replica_diagnosis.md`: harness live riusata, F_season e fallback;
- `audit/results/calibration_layer_diagnosis.md`: shrinkage e costanti di produzione;
- `audit/results/bias_variance_totali_diagnosis.md`: Risoluzione dei marginali Totali.
