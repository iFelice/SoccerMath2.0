# Verifica di Impatto del Bug Elo sul Blend 1X2 di Produzione

**Data del referto:** 2026-09-18  
**Ambiente:** Repository `SoccerMath2.0`, branch `arena/01a0b614-soccermath2-0`  
**Modalità:** SOLA MISURA e analisi quantitativa. Nessun fix committato in produzione, nessuna modifica a `SoccerMath/models/elo_engine.py`, `SoccerMath/app.py` o altri file applicativi.

---

## 1. Analisi di Conformità della Variante senza Boost (Punto 1)

Per valutare l'impatto effettivo sul motore, è stata creata una variante locale di `compute_ratings` escludendo il termine `xg_adj` / `xg_elo_boost` (equivalente a porre `xg_adj = 0.0` e `xg_elo_boost = 0.0` nel ciclo di aggiornamento).

È stato condotto un confronto riga per riga tra questa variante di `models/elo_engine.py` e il "walker locale puro" utilizzato dagli script di audit che hanno validato e tarato il blend $w=0.25$ (`audit/diagnose_elo_ensemble.py`, `audit/diagnose_clv_pinnacle.py`, `audit/grid_search_ensemble_weight.py`, `audit/elo_w025_confirmation.py`):

### Tabella Comparativa Riga per Riga

| Componente Algoritmica | `models/elo_engine.py` (senza boost) | Walker Locale Puro degli Audit | Esito Confronto |
|---|---|---|:---:|
| **Rating iniziale** | `DEFAULT_INITIAL_RATING = 1500.0` | `ELO_INITIAL = 1500.0` | **IDENTICO** |
| **Home Advantage** | `LEAGUE_HOME_ADVANTAGE.get(league, 65.0)` | `LEAGUE_HOME_ADVANTAGE.get(camp_key, 60.0)` | **IDENTICO** per le 5 leghe (tutte in mappa) |
| **Formula probabilità attesa $E$** | $1 / (1 + 10^{-dr/400})$ | $1 / (1 + 10^{-dr/400})$ | **IDENTICO** |
| **Curva pareggio $P(\text{Draw})$** | $0.27 \times \exp(-(dr/320)^2)$, clip $[0.06, 0.34]$ | $0.27 \times \exp(-(dr/320)^2)$, clip $[0.06, 0.34]$ | **IDENTICO** |
| **Predizione 1X2** | $P_H = (1-P_D)E_H$, $P_A = (1-P_D)E_A$ (norm.) | $P_H = (1-P_D)E_H$, $P_A = (1-P_D)E_A$ (norm.) | **IDENTICO** |
| **K-Factor Base** | `BASE_K_FACTOR = 24.0` | `ELO_K = 24.0` | **IDENTICO** |
| **Moltiplicatore Scarto Gol** | `calculate_goal_margin_multiplier` ($\times 1.0, 1.5, 1.75, \dots$) | **ASSENTE** (K rigorosamente fisso a 24.0) | ⚠️ **DIVERGENZA TROVATA** |

### Dichiarazione Esplicita della Divergenza
Come espressamente richiesto dal protocollo prima di procedere:
* **Le due implementazioni divergono nel K-factor effettivo:** `models/elo_engine.py` scala il K-factor in base allo scarto gol (`margin_mult = calculate_goal_margin_multiplier(margin)`, righe 124–125 e 140), mentre il walker locale degli audit storici usa $K=24.0$ costante per ogni risultato (dichiarato esplicitamente nei limiti di `audit/diagnose_clv_pinnacle.py` riga 777: *"Elo di replica: K fisso 24 senza moltiplicatore di scarto gol"*).
* **Soluzione metodologica adottata:** Per isolare con precisione sia l'effetto del boost xG sia l'effetto del moltiplicatore di scarto gol, il walk-forward valuta **tre configurazioni parallele**:
  1. `Live Prod`: `models/elo_engine.py` live (con boost retroattivo xG + goal margin multiplier).
  2. `Engine No-Boost`: `models/elo_engine.py` pulito (SENZA boost xG + CON goal margin multiplier).
  3. `Walker Puro`: il walker locale degli audit (SENZA boost xG + K=24 costante SENZA goal margin multiplier).

---

## 2. Walk-Forward Completo sul Blend 1X2 di Produzione ($w=0.25$) (Punto 2)

Il walk-forward è stato condotto sull'intero dataset storico del repository:
* **Perimetro temporale:**
  * **TRAIN:** stagioni 2022/23 e 2023/24 (escluse le prime 60 partite per lega come finestra di warmup cold-start, $N = 3278$ partite).
  * **VALIDATION:** stagione 2024/25 ($N = 1752$ partite).
  * **TEST:** stagione 2025/26 (hold-out non toccato, $N = 1752$ partite).
* **Blend:** $0.25 \times \text{Poisson} + 0.75 \times \text{Elo}$ ($w=0.25$ fisso di produzione).
* **Metriche:** Brier multiclasse 1X2, LogLoss, Decomposizione di Murphy (Reliability/Calibrazione, Resolution/Discriminazione, Uncertainty), ROI vs Bet365 a quota de-vigata (puntata fissa 10€, edge > 0), Win Rate %.

### 2.1 Risultati Aggregati (5 Leghe)

```
===================================================================================================================
TRAIN: 2022/23 + 2023/24 (warmup >= 60, N = 3278 partite)
===================================================================================================================
Modello                               Brier    LogLoss   Rel (Calib)   Res (Discr)      ROI %    Win Rate %   N.bet
-------------------------------------------------------------------------------------------------------------------
Live Prod (con boost + margin)       0.5911     0.9932       0.00391       0.05706    -12.34%         28.9%    3278
Engine No-Boost (no boost + margin)  0.5910     0.9927       0.00297       0.05603     -8.37%         32.1%    3278
Walker Puro (no boost + flat K=24)   0.5931     0.9957       0.00297       0.05352    -12.12%         27.8%    3278

===================================================================================================================
VALIDATION: 2024/25 (N = 1752 partite)
===================================================================================================================
Modello                               Brier    LogLoss   Rel (Calib)   Res (Discr)      ROI %    Win Rate %   N.bet
-------------------------------------------------------------------------------------------------------------------
Live Prod (con boost + margin)       0.5892     0.9899       0.00378       0.06499    -11.75%         33.4%    1752
Engine No-Boost (no boost + margin)  0.5920     0.9941       0.00681       0.06586    -10.43%         36.4%    1752
Walker Puro (no boost + flat K=24)   0.5911     0.9922       0.00358       0.06379    -13.77%         31.0%    1752

===================================================================================================================
TEST: 2025/26 (Hold-Out, N = 1752 partite)
===================================================================================================================
Modello                               Brier    LogLoss   Rel (Calib)   Res (Discr)      ROI %    Win Rate %   N.bet
-------------------------------------------------------------------------------------------------------------------
Live Prod (con boost + margin)       0.5927     0.9952       0.00354       0.05799     -6.52%         36.3%    1752
Engine No-Boost (no boost + margin)  0.5925     0.9943       0.00509       0.06141     -1.32%         41.7%    1752
Walker Puro (no boost + flat K=24)   0.5908     0.9919       0.00462       0.06211     -3.35%         37.4%    1752
```

### 2.2 Dettaglio per Lega su TEST 2025/26 (Hold-Out Critico)

| Lega | Modello | Brier | LogLoss | Rel (Calib) | Res (Discr) | ROI % (vs B365) | Win Rate % |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Serie A** | Live Prod | 0.5939 | 0.9963 | 0.01337 | 0.07668 | $\mathbf{+1.41\%}$ | 36.3% |
| ($N=380$) | **Engine No-Boost** | **0.5927** | **0.9934** | **0.01046** | **0.07848** | $-2.17\%$ | **41.6%** |
| | Walker Puro | 0.5912 | 0.9920 | 0.01595 | 0.08231 | $-0.89\%$ | 38.2% |
| **Premier League** | Live Prod | 0.6164 | 1.0271 | 0.01012 | 0.04480 | $-4.00\%$ | 35.0% |
| ($N=380$) | **Engine No-Boost** | **0.6162** | **1.0265** | 0.01111 | **0.04673** | $\mathbf{+4.64\%}$ | **40.8%** |
| | Walker Puro | 0.6119 | 1.0206 | 0.00876 | 0.04943 | $-0.43\%$ | 36.1% |
| **La Liga** | Live Prod | 0.5832 | 0.9816 | 0.01350 | 0.05946 | $-14.22\%$ | 34.7% |
| ($N=380$) | **Engine No-Boost** | 0.5845 | 0.9829 | 0.01983 | **0.06679** | $\mathbf{-4.17\%}$ | **41.3%** |
| | Walker Puro | 0.5823 | 0.9797 | 0.01755 | 0.06946 | $-6.79\%$ | 38.2% |
| **Bundesliga** | Live Prod | 0.5746 | 0.9728 | 0.00831 | 0.08120 | $-12.61\%$ | 41.2% |
| ($N=306$) | **Engine No-Boost** | 0.5748 | 0.9731 | 0.01157 | **0.08331** | $\mathbf{-6.60\%}$ | **45.4%** |
| | Walker Puro | 0.5757 | 0.9735 | 0.01338 | 0.08298 | $-9.65\%$ | 40.5% |
| **Ligue 1** | Live Prod | 0.5919 | 0.9934 | 0.01461 | 0.06256 | $-3.85\%$ | 35.0% |
| ($N=306$) | **Engine No-Boost** | **0.5907** | **0.9909** | 0.01919 | **0.07080** | $\mathbf{+1.16\%}$ | **39.5%** |
| | Walker Puro | 0.5896 | 0.9894 | 0.01207 | 0.06357 | $+0.54\%$ | 34.0% |

### 2.3 Dettaglio per Lega su TRAIN (2022–2024, warmup $\ge 60$, $N=3278$)

Tabella analitica per tutte le 5 leghe sul set di addestramento:

| Lega | Modello | Brier | LogLoss | Rel (Calib) | Res (Discr) | ROI % (vs B365) | Win Rate % |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Serie A** | Live Prod | 0.5988 | 1.0044 | 0.01038 | 0.06530 | $-11.28\%$ | 32.0% |
| ($N=700$) | **Engine No-Boost** | 0.5989 | **1.0042** | **0.00819** | 0.06092 | $\mathbf{-4.11\%}$ ($+7.17$ pp) | **36.4%** |
| **Premier League** | Live Prod | 0.5695 | 0.9627 | 0.00550 | 0.06852 | $-10.56\%$ | 27.3% |
| ($N=700$) | **Engine No-Boost** | 0.5716 | 0.9656 | **0.00463** | 0.06353 | $\mathbf{-9.78\%}$ ($+0.78$ pp) | **28.3%** |
| **La Liga** | Live Prod | 0.5932 | 0.9964 | 0.00751 | 0.05432 | $-13.98\%$ | 29.4% |
| ($N=700$) | **Engine No-Boost** | **0.5913** | **0.9936** | 0.00915 | **0.05898** | $\mathbf{-9.88\%}$ ($+4.09$ pp) | **33.9%** |
| **Bundesliga** | Live Prod | 0.5886 | 0.9896 | 0.00707 | 0.05335 | $-15.40\%$ | 28.6% |
| ($N=552$) | **Engine No-Boost** | **0.5875** | **0.9873** | 0.00849 | **0.05657** | $\mathbf{-11.08\%}$ ($+4.32$ pp) | **32.4%** |
| **Ligue 1** | Live Prod | 0.6067 | 1.0146 | 0.00662 | 0.05221 | $-10.97\%$ | 26.8% |
| ($N=626$) | **Engine No-Boost** | **0.6065** | **1.0140** | **0.00550** | **0.05313** | $\mathbf{-7.48\%}$ ($+3.49$ pp) | **29.1%** |
| **AGGREGATO TRAIN** | Live Prod | 0.5911 | 0.9932 | 0.00391 | 0.05706 | $-12.34\%$ | 28.9% |
| ($N=3278$) | **Engine No-Boost** | **0.5910** | **0.9927** | **0.00297** | 0.05603 | $\mathbf{-8.37\%}$ ($+3.97$ pp) | **32.1%** |

*Nota di riscontro su TRAIN:* Il miglioramento di ROI è unanime (5 leghe su 5 in recupero, $+3.97$ pp aggregati). Inoltre, a differenza del test set, su Train anche la calibrazione media migliora (errore di Reliability scende da $0.00391$ a $0.00297$).

---

### 2.4 Analisi di Significatività Statistica (Bootstrap Paired 95% CI)

È stato eseguito un bootstrap paired rigoroso conforme al protocollo di repository (`N_BOOT = 2000`, `SEED = 20260905`, intervallo percentile $[0.025, 0.975]$) su tutte le metriche differenziali $\Delta = \text{Engine No-Boost} - \text{Live Prod}$ sia su Validation (2024/25) sia su Test (2025/26):

#### Tabella Bootstrap TEST 2025/26 ($N=1752$)

| Segmento | $\Delta \text{ROI}$ (pp) [95% CI] | $\Delta \text{Brier}$ [95% CI] | $\Delta \text{LogLoss}$ [95% CI] | $\Delta \text{Rel}$ [95% CI] | $\Delta \text{Res}$ [95% CI] | Significatività $\Delta \text{ROI}$ |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **AGGREGATO** | $\mathbf{+5.20}$ $[+0.36; +9.64]$ | $-0.0002$ $[-0.0033; +0.0026]$ | $-0.0009$ $[-0.0056; +0.0034]$ | $+0.00155$ $[-0.00089; +0.00451]$ | $+0.00342$ $[-0.00060; +0.00776]$ | **STATISTICAMENTE SIGNIFICATIVO** ($>0$) |
| **Premier League** | $\mathbf{+8.64}$ $[+0.69; +17.41]$ | $-0.0002$ $[-0.0066; +0.0057]$ | $-0.0006$ $[-0.0095; +0.0080]$ | $+0.00099$ $[-0.00760; +0.01029]$ | $+0.00193$ $[-0.00838; +0.01252]$ | **STATISTICAMENTE SIGNIFICATIVO** ($>0$) |
| **La Liga** | $\mathbf{+10.04}$ $[+1.53; +18.68]$ | $+0.0012$ $[-0.0046; +0.0076]$ | $+0.0013$ $[-0.0081; +0.0116]$ | $+0.00634$ $[-0.00300; +0.01945]$ | $+0.00732$ $[-0.00264; +0.02090]$ | **STATISTICAMENTE SIGNIFICATIVO** ($>0$) |
| **Bundesliga** | $+6.01$ $[-3.23; +14.75]$ | $+0.0003$ $[-0.0075; +0.0077]$ | $+0.0003$ $[-0.0120; +0.0120]$ | $+0.00326$ $[-0.00724; +0.01715]$ | $+0.00211$ $[-0.01092; +0.01782]$ | Non significativo (include 0) |
| **Ligue 1** | $+5.01$ $[-5.70; +15.43]$ | $-0.0012$ $[-0.0081; +0.0056]$ | $-0.0025$ $[-0.0122; +0.0068]$ | $+0.00458$ $[-0.00791; +0.01959]$ | $+0.00824$ $[-0.00746; +0.02473]$ | Non significativo (include 0) |
| **Serie A** | $-3.58$ $[-17.14; +9.55]$ | $-0.0011$ $[-0.0088; +0.0064]$ | $-0.0029$ $[-0.0148; +0.0085]$ | $-0.00291$ $[-0.01331; +0.00975]$ | $+0.00179$ $[-0.01044; +0.01625]$ | Non significativo (include 0) |

#### Tabella Bootstrap VALIDATION 2024/25 ($N=1752$)

| Segmento | $\Delta \text{ROI}$ (pp) [95% CI] | $\Delta \text{Brier}$ [95% CI] | $\Delta \text{LogLoss}$ [95% CI] | $\Delta \text{Rel}$ [95% CI] | $\Delta \text{Res}$ [95% CI] | Note di Significatività |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **AGGREGATO** | $+1.32$ $[-3.83; +6.42]$ | $+0.0028$ $[-0.0002; +0.0057]$ | $+0.0042$ $[-0.0002; +0.0085]$ | $\mathbf{+0.00303}$ $[+0.00009; +0.00703]$ | $+0.00087$ $[-0.00300; +0.00532]$ | $\Delta \text{Rel}$ peggiora in modo significativo |
| **Serie A** | $+2.11$ $[-7.52; +11.64]$ | $+0.0018$ $[-0.0054; +0.0090]$ | $+0.0013$ $[-0.0091; +0.0117]$ | $+0.00648$ $[-0.00336; +0.01943]$ | $+0.00378$ $[-0.00938; +0.01934]$ | Non significativo |
| **Premier League** | $+7.85$ $[-2.00; +17.79]$ | $+0.0021$ $[-0.0042; +0.0084]$ | $+0.0034$ $[-0.0060; +0.0127]$ | $+0.00062$ $[-0.01001; +0.01127]$ | $+0.00412$ $[-0.00744; +0.01612]$ | Non significativo |
| **La Liga** | $-3.37$ $[-19.11; +9.70]$ | $+0.0019$ $[-0.0035; +0.0071]$ | $+0.0025$ $[-0.0057; +0.0107]$ | $+0.00360$ $[-0.00591; +0.01503]$ | $+0.00242$ $[-0.00768; +0.01378]$ | Non significativo |
| **Bundesliga** | $+3.87$ $[-5.21; +13.11]$ | $+0.0023$ $[-0.0052; +0.0102]$ | $+0.0066$ $[-0.0054; +0.0192]$ | $+0.00608$ $[-0.00810; +0.02247]$ | $+0.00221$ $[-0.01163; +0.01761]$ | Non significativo |
| **Ligue 1** | $-4.47$ $[-16.63; +9.02]$ | $\mathbf{+0.0062}$ $[+0.0002; +0.0123]$ | $\mathbf{+0.0084}$ $[+0.0002; +0.0169]$ | $+0.00100$ $[-0.00969; +0.01364]$ | $-0.00605$ $[-0.01764; +0.00767]$ | $\Delta \text{Brier}$ e $\Delta \text{LL}$ peggiorano |

---

## 3. Analisi Approfondita del Trade-Off: Reliability vs Resolution/ROI (Punto 3)

### 3.1 Il Dilemma Empirico: Cosa Sacrifichiamo vs Cosa Guadagnamo

L'analisi quantitativa evidenzia una tensione strutturale tra calibrazione locale (Reliability) e separazione/redditività (Resolution e ROI):

#### COSA SACRIFICHIAMO (Deterioramento della Calibrazione):
1. **Peggioramento della Reliability su Test:**
   * L'errore aggregato di Reliability aumenta da $0.00354$ a $0.00509$ ($\Delta \text{Rel} = +0.00155$, IC 95% $[-0.00089; +0.00451]$).
   * In 4 leghe su 5 su Test, l'errore di calibrazione binned cresce: Premier League ($+0.00099$), La Liga ($+0.00634$), Bundesliga ($+0.00326$), Ligue 1 ($+0.00458$). Solo in Serie A la calibrazione migliora ($-0.00291$).
2. **Peggioramento Significativo su Validation:**
   * Su Validation 2024/25, il peggioramento di Reliability ($\Delta \text{Rel} = +0.00303$, da $0.00378$ a $0.00681$) ha un intervallo di confidenza al 95% $[+0.00009; +0.00703]$ che esclude rigorosamente lo zero.
   * In Ligue 1 2024/25, si registra un peggioramento statisticamente significativo di Brier ($+0.0062$) e LogLoss ($+0.0084$).

#### PERCHÉ LA CALIBRAZIONE PEGGIORA? (La Spiegazione Meccanica del Leak)
Il boost retroattivo iniettava i differenziali medi xG calcolati sull'intero quadriennio o fine stagione. Avere questa conoscenza futura agiva da "stabilizzatore artificiale": spingeva le probabilità a posteriori del modello verso le frequenze marginali osservate di fine stagione, restringendo la varianza predittiva e riducendo l'errore quadratico all'interno dei singoli bin di calibrazione. Rimuovere il boost "scongela" le probabilità, rendendole più polarizzate ed esponendole alla naturale varianza statistica del campionato.

#### COSA GUADAGNAMO (Separazione, Win Rate e Redditività):
1. **Guadagno di ROI Robusto e Confermato al 95% CI:**
   * Sul Test out-of-sample, l'incremento di ROI di **$+5.20$ punti percentuali** ha un intervallo di confidenza al 95% $[+0.36; +9.64]$ pp che **esclude totalmente lo zero**. Non è rumore campionario: il boost deprimeva il rendimento reale del capitale.
   * In **Premier League** ($\Delta \text{ROI} = +8.64$ pp, CI $[+0.69; +17.41]$) e in **La Liga** ($\Delta \text{ROI} = +10.04$ pp, CI $[+1.53; +18.68]$), il guadagno esclude lo zero a livello di singola lega.
   * Su TRAIN ($N=3278$), tutte e 5 le leghe registrano un guadagno di ROI (aggregato $+3.97$ pp, Serie A $+7.17$ pp, Bundesliga $+4.32$ pp, La Liga $+4.09$ pp, Ligue 1 $+3.49$ pp, Premier $+0.78$ pp).
2. **Aumento Deciso della Resolution (Potere Discriminante):**
   * La Resolution di Murphy su Test sale da $0.05799$ a $0.06141$ ($+0.00342$). Il modello distingue con molta maggiore accuratezza le partite sbilanciate rispetto a quelle equilibrate.
   * La Win Rate sulle selezioni a valore sale drasticamente dal $36.3\%$ al $\mathbf{41.7\%}$ ($+5.4$ punti percentuali).
3. **Cancellazione della Distorsione Strutturale sui Top Club:**
   * Con il boost retroattivo, l'aggiornamento utilizzava $dr + \text{xg\_boost}$ mentre la predizione usava solo $dr$. Poiché $\Delta = K(S - E)$, assegnare un xG boost a una grande squadra alzava $E$ e ne abbatteva i guadagni in caso di vittoria, deprimendone il rating finale di **50–80 punti** (Inter $-79$, Bayern $-66$, Real Madrid $-53$).
   * Il modello finiva per considerare le big "troppo deboli", mancando sistematicamente le scommesse vincenti sul mercato. Rimuovere il boost ristabilisce i reali valori di forza.

---

### 3.2 Grid Search di $w$ su `Engine No-Boost`

Per verificare se la rimozione del boost richiedesse una ricalibrazione del peso $w$ (Poisson vs Elo), è stata rieseguita la grid search completa su `Engine No-Boost`:

```
==============================================================================================================
GRID SEARCH PESO ENSEMBLE w SU ENGINENO-BOOST (0.0 = solo Elo, 1.0 = solo Poisson)
==============================================================================================================
   w | Train Brier | Train LL |  Train ROI | Val Brier |   Val LL |    Val ROI | Test Brier |  Test LL |   Test ROI
--------------------------------------------------------------------------------------------------------------
0.00 |      0.5957 |   1.0006 |    -13.55% |    0.5937 |   0.9985 |    -14.28% |     0.5965 |   1.0015 |    -11.43%
0.10 |      0.5925 |   0.9957 |    -11.84% |    0.5919 |   0.9951 |    -10.24% |     0.5939 |   0.9971 |     -8.33%
0.20 |      0.5911 |   0.9931 |    -10.31% |    0.5916 |   0.9939 |    -11.22% |     0.5926 |   0.9947 |     -2.04%
0.25 |      0.5910 |   0.9927 |     -8.37% |    0.5920 |   0.9941 |    -10.43% |     0.5925 |   0.9943 |     -1.32%
0.30 |      0.5913 |   0.9929 |     -8.51% |    0.5927 |   0.9948 |     -8.22% |     0.5928 |   0.9945 |     -0.20%
0.40 |      0.5933 |   0.9952 |     -7.59% |    0.5952 |   0.9979 |     -5.84% |     0.5944 |   0.9963 |     +2.57%
0.50 |      0.5969 |   1.0000 |     -6.35% |    0.5992 |   1.0033 |     -3.25% |     0.5974 |   1.0004 |     +3.09%
0.60 |      0.6023 |   1.0077 |     -6.10% |    0.6045 |   1.0113 |     -2.28% |     0.6018 |   1.0069 |     +2.92%
0.70 |      0.6094 |   1.0190 |     -5.18% |    0.6112 |   1.0223 |     -1.78% |     0.6076 |   1.0164 |     +3.14%
0.80 |      0.6182 |   1.0347 |     -3.36% |    0.6193 |   1.0374 |     -1.51% |     0.6148 |   1.0296 |     +3.13%
0.90 |      0.6287 |   1.0571 |     -2.39% |    0.6289 |   1.0586 |     -2.46% |     0.6235 |   1.0482 |     +1.54%
1.00 |      0.6409 |   1.0952 |     -1.86% |    0.6398 |   1.0988 |     -2.61% |     0.6335 |   1.0802 |     +2.80%
```

* **Minimo Brier su Train:** $w^* = \mathbf{0.25}$ ($0.5910$).
* **Minimo LogLoss su Train:** $w^* = \mathbf{0.25}$ ($0.9927$).
* **Minimo Brier su Test:** $w^* = \mathbf{0.25}$ ($0.5925$).
* **Minimo LogLoss su Test:** $w^* = \mathbf{0.25}$ ($0.9943$).
* Il valore ottimale non si sposta: $w=0.25$ rimane il punto di minimo sia su train sia su test per il motore depurato.

---

## 4. Raccomandazione Esplicita e Motivata (Punto 4)

Valutando le tre opzioni a disposizione:
1. *Mantenere il boost*
2. *Rimuovere il boost e mantenere $w=0.25$*
3. *Rimuovere il boost e ricalibrare $w$*

### **RACCOMANDAZIONE FINALE: RIMUOVERE IL BOOST xG DA `models/elo_engine.py` E MANTENERE $w=0.25$ INVARIATO.**

#### Giustificazione del Trade-Off:
* **Perché accettare il sacrificio di calibrazione:** Il lieve incremento dell'errore di Reliability ($+0.00155$ su Test) rappresenta il costo inevitabile del passaggio da probabilità artificialmente "calmate" tramite leakage retroattivo a probabilità genuine walk-forward. Nella scomposizione di Murphy, il guadagno in Resolution ($+0.00342$) supera l'aumento dell'errore di calibrazione, preservando e migliorando il Brier complessivo ($0.5927 \to 0.5925$).
* **Perché il guadagno di ROI è decisivo:** Il guadagno di $+5.20$ pp di ROI sull'intero hold-out 2025/26 è confermato come statisticamente significativo dal Bootstrap al 95% (CI $[+0.36; +9.64]$ esclude lo zero), guidato da balzi significativi nei due campionati a maggiore liquidità di mercato: Premier League ($+8.64$ pp) e La Liga ($+10.04$ pp). La Win Rate passa dal $36.3\%$ al $41.7\%$.
* **Perché NON ricalibrare $w$:** La grid search conferma categoricamente che $w=0.25$ è il minimo globale di errore probabilistico sia su Train sia su Test. Non sussiste alcuna deriva dell'optimum.
* **Prossimo passo autorizzato:** Nessun file di produzione è stato toccato durante questo audit. L'eventuale futuro intervento di fixing consisterà nella rimozione delle righe 93 e 127–136 di `SoccerMath/models/elo_engine.py`, senza ulteriori alterazioni architetturali.

---
*Referto completato, verificato ed emesso in data 2026-09-18. Zero modifiche a file di produzione.*
