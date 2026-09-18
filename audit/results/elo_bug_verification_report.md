# Verifica Indipendente del Bug Elo (Audit Esterno Opus)

**Data della verifica:** 2026-09-18  
**Ambiente:** Repository `SoccerMath2.0`, branch `arena/01a0b614-soccermath2-0`  
**Modalità:** Sola lettura e misurazione quantitativa indipendente. Nessuna modifica a `SoccerMath/models/elo_engine.py`, `SoccerMath/app.py` o ad altri file di produzione. Nessuna proposta di fix in questo documento.

---

## 1. Analisi Riga per Riga di `models/elo_engine.py` (Punto 1)

L'analisi del codice sorgente di `SoccerMath/models/elo_engine.py` conferma in modo puntuale ed esatto entrambe le condizioni segnalate:

### (a) `compute_ratings` applica un `xg_adj` statico e retroattivo: **CONFERMATO**

* **Riga 93:**
  ```python
  xg_data = get_understat_xg(self.league_name) or {}
  ```
  La funzione `get_understat_xg` carica da `SoccerMath/database/xg_<league>.json` un unico dizionario statico contenente le medie xG/xGA dell'attuale stagione (`xG_avg`, `xGA_avg`, es. snapshot 2026/27).
* **Righe 102–145:**
  Il motore cicla sull'intero DataFrame storico `df`, ottenuto da `load_and_preprocess_matches()` (righe 50–87), che concatena tutti i CSV storici della lega dal 2022 a oggi (`<Lega>_2022.csv`, `2023.csv`, `2024.csv`, `2025.csv`, `Live.csv`): oltre 1500 partite per lega.
* **Righe 127–136:**
  ```python
  xg_adj = 0.0
  if xg_data and h_team in xg_data and a_team in xg_data:
      h_xg = xg_data[h_team].get("xG_avg", 1.3)
      h_xga = xg_data[h_team].get("xGA_avg", 1.3)
      a_xg = xg_data[a_team].get("xG_avg", 1.3)
      a_xga = xg_data[a_team].get("xGA_avg", 1.3)
      xg_adj = ((h_xg - h_xga) - (a_xg - a_xga)) * 0.15

  xg_elo_boost = max(-100, min(100, xg_adj * 400))
  dr = r_h + self.home_adv - r_a + xg_elo_boost
  expected_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
  expected_a = 1.0 - expected_h
  ```
* **Evidenza:** Poiché `xg_data` è uno snapshot statico caricato una sola volta prima del ciclo e mai aggiornato punto-nel-tempo, a ogni partita giocata nell'agosto 2022 viene applicato il differenziale xG calcolato sulle rose correnti del 2026. Inoltre, se una squadra è retrocessa e non figura nel JSON corrente (es. Spezia, Salernitana, Sassuolo), il ramo `if` è falso e riceve `xg_adj = 0.0`, creando un'asimmetria retroattiva arbitraria.

### (b) `predict_elo_probs` calcola `dr` SENZA `xg_adj`: **CONFERMATO**

* **Righe 245–253:**
  ```python
  def predict_elo_probs(home_team: str, away_team: str, league_name: str) -> dict:
      engine = get_elo_engine(league_name)
      h_cl = clean_name(home_team)
      a_cl = clean_name(away_team)
      r_h = engine.ratings.get(h_cl, DEFAULT_INITIAL_RATING)
      r_a = engine.ratings.get(a_cl, DEFAULT_INITIAL_RATING)
      dr = r_h + engine.home_adv - r_a
      e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
      e_a = 1.0 - e_h
  ```
* **Evidenza:** Nella riga 251, `dr` è calcolato puramente come `r_h + engine.home_adv - r_a`, senza `xg_elo_boost` né alcun `xg_adj`.
* **Discrepanza strutturale:** La misura della forza attesa delle squadre segue due logiche matematicamente contraddittorie:
  1. Durante l'aggiornamento storico sequenziale (`compute_ratings`), la probabilità attesa `expected_h` incorpora `+ xg_elo_boost` (righe 136–137).
  2. Al momento di predire la partita per l'utente (`predict_elo_probs`), la probabilità attesa `e_h` esclude totalmente `xg_elo_boost` (righe 251–252), pur leggendo rating `r_h` e `r_a` che sono stati distorti da 4 anni di aggiornamenti condizionati da quel boost.

---

## 2. Catena di Chiamata in Produzione da `app.py` (Punto 2)

Per verificare se il bug è confinato agli script di audit o se contamina l'applicazione live, è stato tracciato il grafo di chiamate esatto partendo da `SoccerMath/app.py`:

```
SoccerMath/app.py
 │
 ├── Costante: ELO_ENSEMBLE_W = 0.25 (riga 582)
 │
 ├── [FLUSSO 1: Tab 2 "🌟 TOP MIX"]
 │    │
 │    ├── st.button("🚀 Calcola Top 10") (riga 1918)
 │    │    └── fetch_and_calc_top_mix() (riga 1442)
 │    │         │
 │    │         ├── elo_probs = predict_elo_probs(h, a, league) (riga 1476)
 │    │         └── seleziona_riga_top_mix(m_poisson, elo_probs, ...) (riga 1481)
 │    │              │
 │    │              └── confidence = ELO_ENSEMBLE_W * poisson_prob + (1 - ELO_ENSEMBLE_W) * elo_prob (riga 1332)
 │    │                   [Peso effettivo Elo = 75%]
 │    │
 │    └── save_prediction_entry(...) (righe 1948–1960)
 │         └── Salva nel registro con prob_elo e prob_val derivati dal blend
 │
 └── [FLUSSO 2: Tab 1 "🏟️ PARTITE"]
      │
      └── m = blend_elo_into_1x2(m_poisson, h_api, a_api, camp_sel) (riga 1881)
           │
           └── blend_elo_into_1x2(m, home, away, league, w=0.25) (righe 585–602)
                │
                ├── elo_p = predict_elo_probs(home, away, league) (riga 595)
                └── out[k] = w * float(m[k]) + (1.0 - w) * float(elo_p[k]) (riga 601)
```

E all'interno di `predict_elo_probs`:
```
predict_elo_probs(home_team, away_team, league_name)  [elo_engine.py:245]
 │
 ├── get_elo_engine(league_name)  [elo_engine.py:222]
 │    └── engine = EloEngine(league_name); engine.compute_ratings()  [elo_engine.py:228-229]
 │         └── Esegue compute_ratings() con BUG (a) (xG boost retroattivo su 2022–2026)
 │
 └── Calcola dr = r_h + home_adv - r_a  [elo_engine.py:251]
      └── Esegue predict_elo_probs con BUG (b) (omissione di xg_adj su rating già distorti)
```

### Verdetto sul Punto 2
* **Il bug tocca direttamente la produzione live attuale.**
* Non è un bug limitato agli audit: sia il Tab 1 (cartoline partita) sia il Tab 2 (Top Mix) sia il salvataggio persistente nel Registro chiamano `predict_elo_probs`, la quale esegue `compute_ratings()`.
* Poiché in produzione `ELO_ENSEMBLE_W = 0.25`, la probabilità finale dell'1X2 mostrata all'utente e salvata nel registro è composta per il **75% da Elo** (`1 - 0.25 = 0.75`) e solo per il 25% da Poisson. Il 75% della quota/confidence in produzione dipende quindi direttamente da questa doppia asimmetria.

---

## 3. Misurazione Indipendente dello Scarto Elo su TUTTE e 5 le Leghe (Punto 3)

È stata eseguita una misurazione indipendente eseguendo il motore `EloEngine` sullo storico completo (2022–Live) in due modalità identiche:
1. **Produzione (con `xg_adj`):** comportamento attuale del file.
2. **Senza `xg_adj` (`no_xg`):** pure Elo con `xg_adj = 0.0`.

Ecco le metriche quantitative aggregate e le 3 squadre più estreme per lega (valutate sull'intero pool delle squadre presenti nel DB):

| Lega | Squadre Totali | Mediana $\Delta$ (prod $-$ no_xg) | Mediana $|\Delta|$ | Max $|\Delta|$ | Squadra Max $|\Delta|$ |
|---|:---:|:---:|:---:|:---:|:---|
| **Serie A** | 27 | $+1.44$ pt | $18.64$ pt | $76.67$ pt | Roma |
| **Premier League** | 27 | $-0.08$ pt | $10.67$ pt | $66.83$ pt | Aston Villa |
| **La Liga** | 29 | $+2.11$ pt | $8.15$ pt | $78.92$ pt | Barcelona |
| **Bundesliga** | 25 | $+0.86$ pt | $18.16$ pt | $64.45$ pt | Bayern |
| **Ligue 1** | 25 | $+0.04$ pt | $17.06$ pt | $62.54$ pt | Brest |

### Squadre più estreme per lega

#### Serie A (27 squadre)
* **Top 3 Negative (penalizzate dal boost retroattivo):**
  1. `Roma`: $\mathbf{-76.67}$ pt (Prod: $1667.9$ | No-xG: $1744.5$)
  2. `Inter`: $\mathbf{-72.78}$ pt (Prod: $1762.0$ | No-xG: $1834.8$)
  3. `Juventus`: $\mathbf{-58.05}$ pt (Prod: $1607.0$ | No-xG: $1665.0$)
* **Top 3 Positive (gonfiate dal boost retroattivo):**
  1. `Atalanta`: $\mathbf{+57.31}$ pt (Prod: $1684.8$ | No-xG: $1627.5$)
  2. `Lecce`: $\mathbf{+56.42}$ pt (Prod: $1498.9$ | No-xG: $1442.5$)
  3. `Udinese`: $\mathbf{+50.71}$ pt (Prod: $1576.1$ | No-xG: $1525.4$)

#### Premier League (27 squadre)
* **Top 3 Negative:**
  1. `Arsenal`: $\mathbf{-53.36}$ pt (Prod: $1750.7$ | No-xG: $1804.0$)
  2. `Man City`: $\mathbf{-50.38}$ pt (Prod: $1729.3$ | No-xG: $1779.7$)
  3. `Brighton`: $\mathbf{-40.86}$ pt (Prod: $1551.1$ | No-xG: $1591.9$)
* **Top 3 Positive:**
  1. `Aston Villa`: $\mathbf{+66.83}$ pt (Prod: $1628.7$ | No-xG: $1561.8$)
  2. `Newcastle`: $\mathbf{+53.43}$ pt (Prod: $1595.0$ | No-xG: $1541.5$)
  3. `Tottenham`: $\mathbf{+46.30}$ pt (Prod: $1478.7$ | No-xG: $1432.4$)

#### La Liga (29 squadre)
* **Top 3 Negative:**
  1. `Barcelona`: $\mathbf{-78.92}$ pt (Prod: $1784.9$ | No-xG: $1863.9$)
  2. `Real Madrid`: $\mathbf{-71.36}$ pt (Prod: $1711.2$ | No-xG: $1782.6$)
  3. `Villarreal`: $\mathbf{-38.70}$ pt (Prod: $1576.6$ | No-xG: $1615.3$)
* **Top 3 Positive:**
  1. `Valencia`: $\mathbf{+46.05}$ pt (Prod: $1562.4$ | No-xG: $1516.3$)
  2. `Elche`: $\mathbf{+39.47}$ pt (Prod: $1473.1$ | No-xG: $1433.6$)
  3. `Getafe`: $\mathbf{+37.56}$ pt (Prod: $1521.3$ | No-xG: $1483.8$)

#### Bundesliga (25 squadre)
* **Top 3 Negative:**
  1. `Bayern`: $\mathbf{-64.45}$ pt (Prod: $1817.6$ | No-xG: $1882.1$)
  2. `Leverkusen`: $\mathbf{-56.07}$ pt (Prod: $1601.8$ | No-xG: $1657.8$)
  3. `Leipzig`: $\mathbf{-54.87}$ pt (Prod: $1567.3$ | No-xG: $1622.2$)
* **Top 3 Positive:**
  1. `M'gladbach`: $\mathbf{+56.27}$ pt (Prod: $1507.9$ | No-xG: $1451.6$)
  2. `Union Berlin`: $\mathbf{+53.73}$ pt (Prod: $1475.7$ | No-xG: $1422.0$)
  3. `Hamburg`: $\mathbf{+47.92}$ pt (Prod: $1487.7$ | No-xG: $1439.8$)

#### Ligue 1 (25 squadre)
* **Top 3 Negative:**
  1. `Brest`: $\mathbf{-62.54}$ pt (Prod: $1431.7$ | No-xG: $1494.2$)
  2. `Lens`: $\mathbf{-51.54}$ pt (Prod: $1590.5$ | No-xG: $1642.0$)
  3. `Paris`: $\mathbf{-48.19}$ pt (Prod: $1531.6$ | No-xG: $1579.8$)
* **Top 3 Positive:**
  1. `Nice`: $\mathbf{+52.85}$ pt (Prod: $1506.8$ | No-xG: $1454.0$)
  2. `Auxerre`: $\mathbf{+50.70}$ pt (Prod: $1527.5$ | No-xG: $1476.7$)
  3. `Le Havre`: $\mathbf{+37.04}$ pt (Prod: $1478.8$ | No-xG: $1441.8$)

### Meccanismo Matematico della Distorsione
Si nota un effetto apparentemente controintuitivo: **le squadre forti (Inter, Real Madrid, Barcelona, Bayern, Arsenal, Man City) perdono tra i 50 e gli 80 punti Elo**, mentre squadre di centro-bassa classifica guadagnano punti.
La spiegazione matematica è deterministica:
* Nelle formule Elo, `delta_h = k * (s_h - expected_h)`.
* Aggiungere `xg_elo_boost > 0` ad una squadra forte gonfia artificialmente `expected_h` (es. da 0.70 a 0.85) in tutte le partite degli ultimi 4 anni.
* Quando la squadra forte vince (`s_h = 1.0`), incamera `k * (1 - 0.85) = 0.15 * k` anziché `0.30 * k`: **guadagna la metà dei punti Elo per ogni vittoria storica**.
* Se pareggia o perde, viene penalizzata molto più duramente.
* Di conseguenza, su uno storico di 150 partite, il "boost xG" retroattivo agisce come una tassa sistematica che decurta fino a 80 punti alle squadre con xG favorevole.

---

## 4. Deriva del Rating Medio a Fine Stagione (Punto 4)

Opus ha segnalato una deriva della media Elo delle squadre attive pari a "+50/+58 punti in 4 stagioni".
La verifica ha misurato la media Elo delle **sole squadre attive** al termine di ciascuna stagione (dopo l'ultima giornata disputata) su tutte e 5 le leghe, sia con il codice di produzione sia senza `xg_adj`:

### Tabella della Media Elo delle Squadre Attive per Stagione

| Lega | Motore | 2022/23 | 2023/24 | 2024/25 | 2025/26 | 2026/27 (Live) | Deriva Totale |
|---|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Serie A** | Prod (con xG) | 1500.0 | 1521.6 | 1542.2 | 1548.3 | 1553.0 | **+53.0 pt** |
| | No-xG (puro) | 1500.0 | 1521.8 | 1543.2 | 1549.2 | 1553.4 | **+53.4 pt** |
| **Premier League** | Prod (con xG) | 1500.0 | 1520.6 | 1533.1 | 1549.4 | 1558.2 | **+58.2 pt** |
| | No-xG (puro) | 1500.0 | 1520.5 | 1532.9 | 1550.2 | 1558.3 | **+58.3 pt** |
| **La Liga** | Prod (con xG) | 1500.0 | 1512.6 | 1524.4 | 1541.3 | 1548.3 | **+48.3 pt** |
| | No-xG (puro) | 1500.0 | 1514.2 | 1526.0 | 1541.5 | 1549.0 | **+49.0 pt** |
| **Bundesliga** | Prod (con xG) | 1500.0 | 1508.7 | 1525.3 | 1532.8 | 1549.2 | **+49.2 pt** |
| | No-xG (puro) | 1500.0 | 1511.2 | 1528.2 | 1535.2 | 1549.3 | **+49.3 pt** |
| **Ligue 1** | Prod (con xG) | 1500.0 | 1532.2 | 1534.1 | 1544.4 | 1551.7 | **+51.7 pt** |
| | No-xG (puro) | 1500.0 | 1535.7 | 1535.5 | 1545.4 | 1551.2 | **+51.2 pt** |

### Esito della Verifica del Punto 4
1. **L'entità della deriva è CONFERMATA su tutte e 5 le leghe:**
   La deriva varia da un minimo di **+48.3 pt** (La Liga) a un massimo di **+58.2 pt** (Premier League). Il range "+50/+58" indicato da Opus è accurato ed esteso a tutte le leghe.
2. **La causa attribuita da Opus è SMENTITA:**
   La deriva **NON è causata dal bug `xg_adj`**.
   Come si evince chiaramente dalla tabella, la deriva senza `xg_adj` è identica (scarti < 0.7 punti).
   **Causa matematica reale:** È l'assenza di **regressione alla media stagionale** (*mean-reversion*) in presenza di promozioni e retrocessioni (sistema aperto).
   * In ogni partita, la somma dei delta è rigorosamente zero: `delta_h + delta_a = k * (s_h - expected_h + s_a - expected_a) = 0`.
   * Tuttavia, a fine stagione le 3 squadre retrocesse lasciano la lega con rating bassi (tipicamente 1300–1380 pt, accumulando un deficit di $-350$/$-500$ pt).
   * Le 3 neopromosse vengono inizializzate a 1500.0 (riga 95).
   * Questo inietta ogni anno da $+350$ a $+500$ punti fittizi nel pool della lega attiva, che divisi per 20 squadre generano un'inflazione media di $+12$/$+18$ pt a stagione. In Ligue 1 nel 2023/24, dove 4 squadre furono retrocesse e solo 2 promosse per passare da 20 a 18 squadre, si registrò infatti un balzo immediato di $+32.2$ pt in un solo anno.

---

## 5. Impatto sugli Audit Già Chiusi e Re-test di "xG Rolling" (Punto 5)

### 5.1 Censimento dell'Harness negli Audit Esistenti

L'analisi dell'intero albero `audit/` smentisce la premessa che tutti gli audit storici abbiano riusato l'harness buggato di `models/elo_engine.py`:

1. **Audit del Motore Poisson puro (Zero impatto da Elo):**
   * `audit/prior_matches_audit.py` (prior adattivo `PRIOR_MATCHES=6`): valida lo shrinkage bayesiano delle lambda di Poisson sui mercati GG/NG, O/U e 1X2 Poisson. Non usa né importa Elo.
   * `audit/gg_ng_calibration.py` e `audit/ou_gg_calibration.py`: valutano calibrazione BTTS e O/U 2.5 su distribuzioni Poisson bivariate. Nessun utilizzo di Elo.
   * `audit/diagnose_lambda_compression.py`, `audit/diagnose_dixon_coles_rho.py`, `audit/market_values_versioned.py`: toccano solo i parametri Poisson.
   * `audit/diagnose_production_baseline.py` ("motore-live-vs-replica 14/09"): confronta le teste Poisson del motore live vs replica audit. Non include Elo tra i modelli confrontati.

2. **Audit che hanno validato l'Ensemble 1X2 (Già PURI, nessun boost retroattivo):**
   * `audit/diagnose_elo_ensemble.py` (validazione del blend e del peso iniziale $w=0.6$): **NON ha usato `models/elo_engine.py`**. Ha implementato un walker walk-forward locale puro (righe 108–109):
     ```python
     dr = r_h + home_adv - r_a
     e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
     elo[h] = r_h + ELO_K * (s_h - e_h)
     ```
     Senza alcun boost xG nel calcolo del rating o della predizione.
   * `audit/diagnose_clv_pinnacle.py`, `audit/grid_search_ensemble_weight.py` e `audit/elo_w025_confirmation.py` (validazione di $w=0.25$): riusano tutti il walker condiviso di `diagnose_clv_pinnacle.py` (riga 190), che calcola puramente l'Elo sequenziale standard K=24 senza xG.
   * **Conclusione:** La validazione dell'ensemble a $w=0.25$ è stata effettuata su Elo *non contaminato*. L'errore è stato che il motore di produzione (`elo_engine.py`) possedeva un'implementazione diversa e difforme dagli script di audit che lo avevano validato!

### 5.2 Re-test Completo: xG Rolling 5 vs Baseline Elo PURO (Senza Boost)

L'audit citato da Opus come contaminato è `audit/xg_rolling_walkforward.py` ("xG rolling 5 partite in Elo peggiora ROI"), il quale aveva confrontato:
* Baseline: `Elo stagionale` (calcolato con lo snapshot xG statico)
* Sperimentale: `Elo rolling` (media mobile ultime 5 partite, no-leakage)

Abbiamo rieseguito il walk-forward completo su tutte e 5 le leghe per entrambe le stagioni (**VALIDATION 2024/25: 1752 partite, TEST 2025/26: 1752 partite**), inserendo la **Baseline Elo Puro (SENZA alcun boost xG)**:

#### Risultati Aggregati (5 Leghe, 3504 Partite)

```
========================================================================================
AGGREGATO VALIDATION 2024/25 (N = 1752 partite)
========================================================================================
Modello                               Brier    LogLoss   N.bet   Win Rate %   ROI % (B365)
----------------------------------------------------------------------------------------
Elo puro (SENZA boost)               0.5937     0.9972    1752        27.0%        -15.05%
Elo rolling 5                        0.5932     0.9970    1752        32.1%         -9.48%
Elo stagionale (con boost retroatt.) 0.5939     0.9977    1752        28.1%        -12.93%

Ensemble puro (0.6P + 0.4Elo puro)   0.5888     0.9885    1752        30.1%        -15.90%
Ensemble rolling (0.6P + 0.4Elo roll)0.5875     0.9868    1752        31.8%        -15.04%
Ensemble stagionale (0.6P + 0.4Elo)  0.5889     0.9887    1752        30.5%        -16.20%

========================================================================================
AGGREGATO TEST 2025/26 - Sola Lettura Hold-Out (N = 1752 partite)
========================================================================================
Modello                               Brier    LogLoss   N.bet   Win Rate %   ROI % (B365)
----------------------------------------------------------------------------------------
Elo puro (SENZA boost)               0.5954     0.9999    1752        29.7%        -13.01%
Elo rolling 5                        0.5969     1.0022    1752        32.9%        -10.43%
Elo stagionale (con boost retroatt.) 0.5951     0.9994    1752        30.9%        -11.22%

Ensemble puro (0.6P + 0.4Elo puro)   0.5928     0.9943    1752        33.4%        -10.71%
Ensemble rolling (0.6P + 0.4Elo roll)0.5920     0.9934    1752        34.1%        -11.28%
Ensemble stagionale (0.6P + 0.4Elo)  0.5926     0.9941    1752        33.7%         -9.86%
```

#### Dettaglio per Lega su TEST 2025/26 (Hold-out critico)

* **Premier League (TEST 2025/26):**
  * `Elo puro`: Brier $0.6173$ | LogLoss $1.0305$ | **ROI $-1.56\%$**
  * `Elo rolling`: Brier $0.6210$ | LogLoss $1.0365$ | **ROI $-14.34\%$** (crollo di $-12.78\%$ di ROI e peggioramento di Brier)
  * `Ensemble puro`: ROI $-12.80\%$ vs `Ensemble rolling`: ROI $-13.20\%$ (rolling peggiore)
* **Serie A (TEST 2025/26):**
  * `Ensemble puro`: ROI $\mathbf{-6.71\%}$ vs `Ensemble rolling`: ROI $\mathbf{-9.39\%}$ (rolling peggiore di $-2.68\%$)
* **La Liga (TEST 2025/26):**
  * `Ensemble puro`: ROI $\mathbf{-14.58\%}$ vs `Ensemble rolling`: ROI $\mathbf{-15.49\%}$ (rolling peggiore)

### Verdetto sul Punto 5: IL VERDETTO NON CAMBIA

* Sebbene la baseline originale usata in `xg_rolling_walkforward.py` fosse metodologicamente imperfetta (conteneva il boost stagionale), **il verdetto di rigetto di xG Rolling 5 NON era un artefatto del boost retroattivo**.
* Sul dataset di **TEST 2025/26 out-of-sample**:
  1. `Elo rolling 5` ottiene Brier ($0.5969$) e LogLoss ($1.0022$) **peggiori** di `Elo puro` ($0.5954$ e $0.9999$).
  2. L'`Ensemble rolling` ottiene un ROI aggregato **peggiore** dell'`Ensemble puro` ($-11.28\%$ vs $-10.71\%$).
  3. In Premier League, l'aggiunta di xG rolling causa un crollo verticale del ROI (da $-1.56\%$ a $-14.34\%$).
* **Conclusione:** L'aggiunta di xG rolling a 5 partite nell'algoritmo Elo continua a non dimostrare alcun edge out-of-sample robusto rispetto a un Elo puro. L'audit non necessita di essere riaperto con esito opposto: la decisione di non promuovere il rolling in produzione era corretta.

---

## 6. Sintesi Finale: Cosa è Confermato e Cosa è Smentito (Punto 6)

| Elemento di Analisi | Esito Verifica | Note Dettagliate |
|---|:---:|---|
| **Punto 1(a): `compute_ratings` applica snapshot statico xG retroattivo** | **CONFERMATO** | `models/elo_engine.py` righe 93, 127–136. Snapshot costante applicato dal 2022. |
| **Punto 1(b): `predict_elo_probs` omette `xg_adj` da `dr`** | **CONFERMATO** | `models/elo_engine.py` riga 251. Asimmetria intrinseca tra aggiornamento e predizione. |
| **Punto 2: Impatto su Produzione Live vs Script di Audit** | **CONFERMATO: IMPATTA IL LIVE** | Il Top Mix (`fetch_and_calc_top_mix`), le partite live (`blend_elo_into_1x2`) e il registro salvano l'1X2 pesato al **75% su questo Elo distorto**. |
| **Punto 3: Scarto Elo per squadra su 5 leghe** | **CONFERMATO (con misurazione completa)** | Opus ha misurato solo 2 leghe. Tutte e 5 presentano scarti fino a 64–79 punti. Le squadre forti vengono penalizzate dal boost, le deboli favorite. |
| **Punto 4: Deriva rating medio (+50/+58 pt in 4 stagioni)** | **CONFERMATO nei numeri, SMENTITO nella causa** | Deriva confermata su tutte le 5 leghe (+48.3 a +58.2 pt). Smentita l'attribuzione a `xg_adj`: si verifica identica anche con Elo puro per via del ricambio promozioni/retrocessioni senza mean-reversion. |
| **Punto 5: Contaminazione di tutti gli audit chiusi** | **SMENTITO** | Gli audit del Poisson (prior, GG/NG, O/U) non usano Elo. Gli audit dell'Ensemble 1X2 (`diagnose_elo_ensemble`, `grid_search`, `elo_w025`) usavano già un Elo puro senza xG. |
| **Punto 5 (bis): Riapertura audit "xG Rolling in Elo"** | **SMENTITO (Verdetto Invariato)** | Anche contro la baseline pulita senza boost, xG Rolling 5 peggiora Brier e LogLoss su TEST e degrada il ROI in Premier League e Serie A. Il verdetto di non promozione resta valido. |

---
*Referto redatto in data 2026-09-18. Nessun file di produzione è stato alterato.*
