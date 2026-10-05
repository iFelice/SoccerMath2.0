# Audit della conversione Elo -> 1X2 (punto 3 della roadmap Elo)

Generato: 2026-10-05T17:57:13+00:00 UTC  
Commit: `d28e9244f8c48517ed9cf37e7c3cf8c9a7819362`  
Produzione (`SoccerMath/`) modificata rispetto a HEAD: **(pulita: nessuna modifica)**  
`app.POISSON_1X2_WEIGHT` letto in sola lettura: **0.25** (non modificato)  
Bootstrap: 2000 repliche, seed 20260905, blocchi (lega x stagione x giornata), IC percentile 2.5-97.5  
Comando unico che rigenera tutto: `python audit/elo_conversion_audit.py`

> **AUDIT DI SOLA LETTURA. Nulla e' stato applicato.** Nessun file sotto `SoccerMath/` e' stato modificato: le funzioni di produzione (`elo_probs_from_ratings`, `blend_elo_into_1x2`, `seleziona_riga_top_mix`, `riga_top_mix_shadow`, `classifica_top_mix`) sono importate e usate cosi' come sono.

## 0bis. Prerequisiti (punto 0 del mandato)

### P.1 La produzione contiene `elo_probs_from_ratings` (PR #30)

**Comando**
```
grep -n 'def elo_probs_from_ratings' SoccerMath/models/elo_engine.py
```

**Output**
```
234:def elo_probs_from_ratings(r_h: float, r_a: float, home_adv: float) -> dict:
```

**Esito**: PRESENTE.

### P.2 La produzione non e' stata toccata da questo audit

**Comando**
```
git diff --stat origin/main HEAD -- SoccerMath/
```

**Output**
```
(vuoto)
```

**Esito**: nessuna modifica alla produzione. Il requisito del mandato (`git diff origin/main HEAD` vuoto) valeva all'inizio del lavoro ed e' stato verificato allora; da li' in poi il branch ha aggiunto **solo** file sotto `audit/` e una riga in `.gitignore`, quindi il diff ristretto a `SoccerMath/` resta vuoto.

### P.3 Il walker usa `elo_probs_from_ratings`, non la cache globale

**Comando**
```
python -c "import elo_walker_core as W; print(sorted(set(W.build_walker_table.__code__.co_names)))"
```

**Output** (nomi referenziati dal bytecode del walker)
```
['DataFrame', 'EloEngine', '_prematch_ratings', 'append', 'at', 'compute_ratings', 'elo_probs_from_ratings', 'get', 'home_adv', 'iterrows', 'matches_df', 'pd', 'str', 'strip', 'upper']
```

**Esito**: OK — `elo_probs_from_ratings` compare; simboli di cache/stato globale presenti: nessuno. Il walker non scrive piu' nella cache globale di modulo e non muta `engine.ratings` (verificato anche a runtime dal test P0, sotto).

### P.4 Provenienza della fixture: niente whitelist su main

Il test ereditato dal punto 2 asseriva `git diff --stat <sha cablato> -- SoccerMath/ == ""`, cioe' "la produzione di oggi deve essere identica a quella di un commit scritto a mano nel test". E' una whitelist, e si e' rotta appena la produzione e' cambiata (PR #30/#31):

```
AssertionError: 'SoccerMath/models/elo_engine.py [...] 3 files changed, 322 insertions(+), 15 deletions(-)' != '' : la produzione e' stata modificata: la fixture non e' piu' quella di main
```

Il test riscritto verifica invece che la fixture sia stata generata dal commit dichiarato **nel suo manifest**:

```json
{
 "commit": "3f9f04278096aba2bc96fc5335a45ccd0d219094",
 "production_input_oids": {
  "SoccerMath/models/elo_engine.py": "f76e6db59ee6c055c014d039a69938d80d399c2b",
  "SoccerMath/config.py": "656bc59788bc2d9848f9538973985db21f77e49f",
  "SoccerMath/database": "4650d65444bd7bc262d5f55dd7a55203097aaa63"
 }
}
```

* **V0** il manifest ha il blocco `provenance` e il test non contiene sha cablati (se lo contenesse, il test stesso fallisce: si rilegge);
* **V1** il commit dichiarato esiste nel repository;
* **V2** gli object id git degli input di produzione nel manifest sono quelli di **quel** commit (`git rev-parse <commit>:<path>`);
* **V3** la fixture e' **rigenerabile bit-exact** estraendo quel commit in un worktree ed eseguendovi il generatore.

Cosi' il test non si rompe alla prossima PR di produzione: non guarda mai dove sta main. Cio' che nega e' solo che la fixture menta sulla propria origine.

### P.5 Rilancio dei test di parita' P1-P4 (devono restare bit-exact)

**Comando**
```
python -m pytest audit/test_elo_walker_parity.py -v -s
```

**Output**
```
============================= test session starts ==============================
collecting ... collected 9 items

audit/test_elo_walker_parity.py::TestProvenienzaFixture::test_v0_manifest_ha_il_blocco_di_provenienza PASSED
audit/test_elo_walker_parity.py::TestProvenienzaFixture::test_v1_commit_dichiarato_esiste PASSED
audit/test_elo_walker_parity.py::TestProvenienzaFixture::test_v2_oid_produzione_coerenti_col_commit_dichiarato 
  V2 OK: 3 input di produzione coerenti con 3f9f04278096
PASSED
audit/test_elo_walker_parity.py::TestProvenienzaFixture::test_v3_fixture_rigenerabile_dal_commit_dichiarato 
  V3 OK: fixture rigenerata da 3f9f04278096 identica (5 leghe, 133 rating finali)
PASSED
audit/test_elo_walker_parity.py::TestParitaWalker::test_p0_walker_non_tocca_la_cache_globale 
  P0 OK: cache globale intatta per tutte e 5 le leghe; co_names(build_walker_table) include elo_probs_from_ratings e nessun simbolo di cache
PASSED
audit/test_elo_walker_parity.py::TestParitaWalker::test_p1_stato_finale_identico PASSED
audit/test_elo_walker_parity.py::TestParitaWalker::test_p2_conversione_identica 
  P2 OK: 50 accoppiamenti, fixture == predict_elo_probs == elo_probs_from_ratings
PASSED
audit/test_elo_walker_parity.py::TestParitaWalker::test_p3_walk_forward_vs_produzione_troncata PASSED
audit/test_elo_walker_parity.py::TestNoLeakage::test_p4_alterare_il_risultato_non_cambia_la_previsione 
  P4: righe successive modificate = 467 / 569
PASSED

============================== 9 passed in 7.80s ===============================
```

**Esito**: TUTTI VERDI — `============================== 9 passed in 7.80s ===============================`. P1 (stato finale), P2 (conversione), P3 (walk-forward contro la produzione su CSV troncati) e P4 (no-leakage) restano **bit-exact** dopo il passaggio del walker alla funzione pura; P0 e' il nuovo controllo di non interferenza con la cache globale.

### P.6 Gli artefatti pesanti non sono in git e sono rigenerabili

**Comando**
```
git check-ignore -v audit/output/*  &&  git ls-files audit/output/
```

**Output**
```
.gitignore:44:audit/output/	audit/output/elo_walker_per_match.parquet
.gitignore:44:audit/output/	audit/output/elo_walker_per_match.csv.gz
.gitignore:44:audit/output/	audit/output/elo_conversion_pooled.csv.gz
--- tracciati sotto audit/output/: ---
(vuoto sopra = nessuno)
```

**Esito**: `audit/output/` e' ignorata da git; nessun parquet o csv.gz e' tracciato. Si rigenerano con:

```
python audit/elo_weight_retune.py      # elo_walker_per_match.parquet/.csv.gz
python audit/elo_conversion_audit.py   # elo_conversion_pooled.csv.gz
```

## 0. La formula di `p_draw` e da cosa dipende

**Comando**
```
python -c "from models.elo_engine import elo_probs_from_ratings as f; print(f.__doc__)"
```

**Output** — estratto testuale della docstring di produzione (`SoccerMath/models/elo_engine.py`, punto 3 della formula):

```
3. probabilita' di pareggio: campana gaussiana centrata sull'equilibrio
       (dr = 0), ampiezza 0.27, scala 320, troncata nell'intervallo
       [0.06, 0.34]::

           p_draw = 0.27 * exp(-((dr / 320) ** 2))
           p_draw = max(0.06, min(0.34, p_draw))
```

**Righe di codice corrispondenti**

```python
p_draw = 0.27 * math.exp(-((dr / 320.0) ** 2))
p_draw = max(0.06, min(0.34, p_draw))
p_home = (1.0 - p_draw) * e_h
p_away = (1.0 - p_draw) * e_a
total = p_home + p_draw + p_away
```

**Esito — formula esatta e dipendenze**

```
p_draw = 0.27 * exp(-((dr / 320)**2))
p_draw = max(0.06, min(0.34, p_draw))        # troncamento in [0.06, 0.34]
```

`p_draw` dipende da **un solo input**: `dr = r_h + home_adv - r_a`, cioe'

* `r_h`  — rating Elo della squadra di casa;
* `r_a`  — rating Elo della squadra in trasferta;
* `home_adv` — vantaggio casalingo in punti Elo, per lega (`config.LEAGUE_HOME_ADVANTAGE`, default `HOME_ADVANTAGE = 65.0`).

I tre entrano **solo** nella combinazione `dr`: `p_draw` e' una funzione pari di `dr` (dipende da `dr**2`), massima in `dr = 0` con valore 0.27, decrescente verso il pavimento 0.06. Il tetto 0.34 e' **irraggiungibile** (il massimo e' 0.27), quindi l'unico ramo di troncamento attivo e' il pavimento 0.06, che scatta per `|dr| > 320*sqrt(ln(0.27/0.06))` ~ 481.6 punti Elo. `p_draw` **non** dipende dalla lega se non attraverso `home_adv` dentro `dr`, non dipende dalla stagione, dalla giornata, dalle squadre o dal Poisson.

Nota: nella terna finale `"X" = round(p_draw / total, 4)` con `total = 1` per costruzione, quindi la `X` di produzione **e'** `p_draw` arrotondata a 4 decimali.

## 1. Campione e disegno di valutazione

**Comando**: `python audit/elo_conversion_audit.py` (sezione S1)

**Output**

| league | n_walker_elo | n_poisson_walker | n_join | solo_walker | solo_poisson |
|---|---|---|---|---|---|
| Serie A | 1570 | 1570 | 1570 | 0 | 0 |
| Premier League | 1570 | 1570 | 1570 | 0 | 0 |
| La Liga | 1591 | 1591 | 1591 | 0 | 0 |
| Bundesliga | 1260 | 1260 | 1260 | 0 | 0 |
| Ligue 1 | 1343 | 1343 | 1343 | 0 | 0 |

| split | n |
|---|---|
| 2023/24 | 1752 |
| 2024/25 | 1752 |
| 2025/26 | 1752 |
| burn-in | 1826 |
| esclusa | 252 |

**Esito**: rolling-origin dichiarato prima di guardare i risultati.

| | stima | valutazione | n valutazione |
|---|---|---|---|
| Fold 1 | 2023/24 | 2024/25 | 1752 |
| Fold 2 | 2023/24 + 2024/25 | 2025/26 | 1752 |
| **Pooled** | — | 2024/25 + 2025/26 | **3504** |

`2022/23` e' burn-in: **mai** usata per stimare parametri (resta solo nello stato Elo). `2026/27` esclusa. Il pooled dei due fold fa 3504 partite, come dichiarato nel mandato.

## 2. Righe con `p_draw > 2*min(e_H, 1-e_H)` (conteggio PRE-modello)

**Comando**: `python audit/elo_conversion_audit.py` (sezione S2)

**Output — per split**

| split | n_attive | n | quota |
|---|---|---|---|
| 2023/24 | 0 | 1752 | 0.000000 |
| 2024/25 | 2 | 1752 | 0.001142 |
| 2025/26 | 0 | 1752 | 0.000000 |
| burn-in | 0 | 1826 | 0.000000 |
| esclusa | 0 | 252 | 0.000000 |

**Output — per split x lega** (solo righe con almeno un caso, piu' il totale)

| split | league | n_attive | n | quota |
|---|---|---|---|---|
| 2024/25 | Premier League | 2 | 380 | 0.005263 |

**Output — per split x fascia di |d_elo_diff|**

| split | fascia_d | n_attive | n | quota |
|---|---|---|---|---|
| 2023/24 | [0,25) | 0 | 224 | 0.000000 |
| 2023/24 | [25,50) | 0 | 201 | 0.000000 |
| 2023/24 | [50,100) | 0 | 406 | 0.000000 |
| 2023/24 | [100,200) | 0 | 572 | 0.000000 |
| 2023/24 | [200,400) | 0 | 330 | 0.000000 |
| 2023/24 | >=400 | 0 | 19 | 0.000000 |
| 2024/25 | [0,25) | 0 | 183 | 0.000000 |
| 2024/25 | [25,50) | 0 | 191 | 0.000000 |
| 2024/25 | [50,100) | 0 | 338 | 0.000000 |
| 2024/25 | [100,200) | 0 | 574 | 0.000000 |
| 2024/25 | [200,400) | 0 | 423 | 0.000000 |
| 2024/25 | >=400 | 2 | 43 | 0.046512 |
| 2025/26 | [0,25) | 0 | 207 | 0.000000 |
| 2025/26 | [25,50) | 0 | 182 | 0.000000 |
| 2025/26 | [50,100) | 0 | 354 | 0.000000 |
| 2025/26 | [100,200) | 0 | 523 | 0.000000 |
| 2025/26 | [200,400) | 0 | 446 | 0.000000 |
| 2025/26 | >=400 | 0 | 40 | 0.000000 |
| burn-in | [0,25) | 0 | 289 | 0.000000 |
| burn-in | [25,50) | 0 | 271 | 0.000000 |
| burn-in | [50,100) | 0 | 584 | 0.000000 |
| burn-in | [100,200) | 0 | 500 | 0.000000 |
| burn-in | [200,400) | 0 | 179 | 0.000000 |
| burn-in | >=400 | 0 | 3 | 0.000000 |
| esclusa | [0,25) | 0 | 26 | 0.000000 |
| esclusa | [25,50) | 0 | 33 | 0.000000 |
| esclusa | [50,100) | 0 | 65 | 0.000000 |
| esclusa | [100,200) | 0 | 74 | 0.000000 |
| esclusa | [200,400) | 0 | 49 | 0.000000 |
| esclusa | >=400 | 0 | 5 | 0.000000 |

**Output — elenco completo delle righe attive**

| league | season | giornata | date | home | away | d_exact | e_H | p_draw | real_1x2 |
|---|---|---|---|---|---|---|---|---|---|
| Premier League | 2024/25 | 9 | 2024-10-26 | Man City | Southampton | 613.4276 | 0.9716 | 0.0600 | 1 |
| Premier League | 2024/25 | 28 | 2025-03-08 | Liverpool | Southampton | 622.6909 | 0.9730 | 0.0600 | 1 |

**Esito — caso peggiore**

* Totale su tutto il campione (tutte le stagioni, 7334 righe): **2 righe** attivano il vincolo.
* Caso peggiore per fascia: split **2024/25**, fascia **>=400** -> 2/43 = **4.6512%**.
* Caso peggiore per lega: split **2024/25**, lega **Premier League** -> 2/380 = **0.5263%**.

Lettura: il vincolo di B morde **solo** nella coda estrema `|d| >= 400`, dove il pavimento `p_draw = 0.06` incontra `2*min(e_H,1-e_H) < 0.06` (cioe' `e_H > 0.97`, che richiede `dr > 604` punti Elo). Il massimo |d| osservato e' **622.7**. **Attenzione**: questo conta solo dove il *troncamento* di B si attiva; B differisce da A0 su **tutte** le righe con `e_H != 0.5`, perche' ripartisce la massa del pareggio in modo diverso (vedi sezione 3).

## 3. Varianti messe a confronto

Tutte sono funzioni **pure** di `d = r_h + home_adv - r_a` (piu' i parametri stimati). Tutte chiudono con lo stesso passo finale della produzione: normalizzazione sulla somma e arrotondamento a 4 decimali.

| variante | parametri | definizione |
|---|---|---|
| **A0** | nessuno | conversione di produzione, invariata: `elo_probs_from_ratings(d, 0, 0)` (dr = d) |
| **Abeta** | `beta` (1) | la stessa mappa di produzione applicata a `beta*d`: beta scala il differenziale per l'INTERA mappa, quindi anche `p_draw`, che dipende da d |
| **B** | nessuno | expectation-preserving: `pd_eff = min(p_draw, 2*min(e_H,1-e_H))`, `P(1)=e_H-pd_eff/2`, `P(X)=pd_eff`, `P(2)=1-e_H-pd_eff/2` |
| **C** | `tau0,tau1,beta` (3) | ordered logit, ordine 2 < X < 1: `P(Y<=k)=sigmoid(tau_k - beta*d)` |
| _MNL_ | `aX,bX,a2,b2` (4) | _diagnostica, NON candidata_: multinomial logit su d |

Davidson: **escluso da questo giro**, come da mandato.

**Controlli di correttezza delle implementazioni** (comando: `python audit/test_elo_conversion_audit.py`)

* `A0` prodotta da questo script coincide **bit per bit** con `elo_probs_from_ratings` di produzione su una griglia di 4005 valori di d;
* `Abeta` con `beta = 1` coincide **bit per bit** con `A0`;
* B preserva il punteggio atteso Elo: `P(1) + P(X)/2 = e_H` (a meno dell'arrotondamento a 4 decimali). A0 **non** lo preserva: `P(1)+P(X)/2 = (1-p_draw)*e_H + p_draw/2`, che vale `e_H` solo per `e_H = 0.5`. Questa e' la differenza strutturale fra A0 e B.

## 4. Parametri stimati per fold

**Comando**: `python audit/elo_conversion_audit.py` (sezione S3). Criterio: minimizzazione della LogLoss delle probabilita' **solo-Elo** sui soli dati di stima del fold.

| fold | stima_su | variante | NLL_stima | parametri |
|---|---|---|---|---|
| Fold 1 | 2023/24 | A0 | 0.995397 | (nessuno) |
| Fold 1 | 2023/24 | Abeta | 0.995292 | beta=1.0320738 |
| Fold 1 | 2023/24 | B | 0.989004 | (nessuno) |
| Fold 1 | 2023/24 | C | 0.982184 | tau0=-0.58425565, tau1=0.70281758, beta=0.0061604982 |
| Fold 1 | 2023/24 | MNL | 0.981088 | aX=-0.15578633, bX=-0.0038160041, a2=0.060879051, b2=-0.0083160329 |
| Fold 2 | 2023/24+2024/25 | A0 | 0.996944 | (nessuno) |
| Fold 2 | 2023/24+2024/25 | Abeta | 0.996430 | beta=0.92235356 |
| Fold 2 | 2023/24+2024/25 | B | 0.994484 | (nessuno) |
| Fold 2 | 2023/24+2024/25 | C | 0.986438 | tau0=-0.55293177, tau1=0.68272937, beta=0.0054862481 |
| Fold 2 | 2023/24+2024/25 | MNL | 0.985938 | aX=-0.18007752, bX=-0.0036337462, a2=0.084486874, b2=-0.0072816822 |

**Controllo incrociato di C: scipy MLE vs statsmodels `OrderedModel`**

| fold | tau0_sm | tau1_sm | beta_sm | NLL_sm | max_scarto_parametri | scarto_NLL |
|---|---|---|---|---|---|---|
| Fold 1 | -5.843e-01 | 7.028e-01 | 6.160e-03 | 9.822e-01 | 4.101e-08 | 4.441e-16 |
| Fold 2 | -5.529e-01 | 6.827e-01 | 5.486e-03 | 9.864e-01 | 5.223e-08 | 9.992e-16 |

**Esito**: `statsmodels.miscmodels.ordinal_model.OrderedModel` **e'** disponibile; le due stime coincidono a meno di ~1e-7 sui parametri e ~1e-15 sulla NLL su entrambi i fold. La forma di C e' quindi verificata l'una contro l'altra, come richiesto.

**w scelto (Livello 2, passo b: griglia 0..1 passo 0.05 sul blend, scelto sui soli dati di stima)**

| fold | variante | w_scelto | LL_stima_al_w_scelto |
|---|---|---|---|
| Fold 1 | A0 | 0.350000 | 0.984645 |
| Fold 1 | Abeta | 0.350000 | 0.984738 |
| Fold 1 | B | 0.300000 | 0.980777 |
| Fold 1 | C | 0.250000 | 0.974448 |
| Fold 2 | A0 | 0.300000 | 0.987899 |
| Fold 2 | Abeta | 0.300000 | 0.987221 |
| Fold 2 | B | 0.300000 | 0.986718 |
| Fold 2 | C | 0.250000 | 0.980106 |

Per riferimento, il w di produzione e' **0.25** e non e' stato toccato.

## 5. Livello 1 — isolamento a w fisso

**Comando**: `python audit/elo_conversion_audit.py` (sezione S4). I parametri delle mappe sono quelli del fold (stimati sui soli dati di stima); qui si fissa w e si confrontano le varianti a parita' di tutto il resto. Delta = (a - b), **negativo = la prima e' migliore**.

### 5.1 w = 0.25 (peso di produzione)

| fold | confronto | n | n_blocchi | LL_a | LL_b | dLL | dLL_lo | dLL_hi | dBrier |
|---|---|---|---|---|---|---|---|---|---|
| Fold 1 | B vs A0 | 1752 | 182 | 0.992643 | 0.991141 | 0.001502 | -0.001737 | 0.005094 | 0.001993 |
| Fold 1 | Abeta vs A0 | 1752 | 182 | 0.991952 | 0.991141 | 0.000810 | 0.000258 | 0.001408 | 0.000478 |
| Fold 1 | C vs Abeta | 1752 | 182 | 0.987682 | 0.991952 | -0.004270 | -0.009897 | 0.001524 | -0.001382 |
| Fold 2 | B vs A0 | 1752 | 182 | 0.997500 | 0.993727 | 0.003772 | 0.000467 | 0.007120 | 0.003009 |
| Fold 2 | Abeta vs A0 | 1752 | 182 | 0.992254 | 0.993727 | -0.001473 | -0.002839 | -0.000217 | -0.001006 |
| Fold 2 | C vs Abeta | 1752 | 182 | 0.992381 | 0.992254 | 0.000127 | -0.004841 | 0.004977 | 0.000302 |
| POOLED | B vs A0 | 3504 | 364 | 0.995072 | 0.992434 | 0.002637 | 0.000341 | 0.005070 | 0.002501 |
| POOLED | Abeta vs A0 | 3504 | 364 | 0.992103 | 0.992434 | -0.000331 | -0.001029 | 0.000363 | -0.000264 |
| POOLED | C vs Abeta | 3504 | 364 | 0.990031 | 0.992103 | -0.002071 | -0.005924 | 0.001700 | -0.000540 |

### 5.2 w = 0.0 (solo Elo, diagnostica)

| fold | confronto | n | n_blocchi | LL_a | LL_b | dLL | dLL_lo | dLL_hi | dBrier |
|---|---|---|---|---|---|---|---|---|---|
| Fold 1 | B vs A0 | 1752 | 182 | 0.999965 | 0.998493 | 0.001472 | -0.002773 | 0.005993 | 0.002503 |
| Fold 1 | Abeta vs A0 | 1752 | 182 | 0.999589 | 0.998493 | 0.001096 | 0.000363 | 0.001853 | 0.000583 |
| Fold 1 | C vs Abeta | 1752 | 182 | 0.993488 | 0.999589 | -0.006101 | -0.013648 | 0.001645 | -0.001688 |
| Fold 2 | B vs A0 | 1752 | 182 | 1.005921 | 1.001529 | 0.004392 | 0.000151 | 0.008688 | 0.003856 |
| Fold 2 | Abeta vs A0 | 1752 | 182 | 0.999856 | 1.001529 | -0.001673 | -0.003505 | 0.000021 | -0.001043 |
| Fold 2 | C vs Abeta | 1752 | 182 | 0.998859 | 0.999856 | -0.000996 | -0.007420 | 0.005308 | -0.000034 |
| POOLED | B vs A0 | 3504 | 364 | 1.002943 | 1.000011 | 0.002932 | -0.000064 | 0.006011 | 0.003179 |
| POOLED | Abeta vs A0 | 3504 | 364 | 0.999722 | 1.000011 | -0.000288 | -0.001238 | 0.000659 | -0.000230 |
| POOLED | C vs Abeta | 3504 | 364 | 0.996174 | 0.999722 | -0.003549 | -0.008674 | 0.001420 | -0.000861 |

**Esito Livello 1 (pooled, w = 0.25)**

* **B vs A0**: dLogLoss = +0.002637 [+0.000341, +0.005070] — IC esclude 0, a favore della seconda.
* **Abeta vs A0**: dLogLoss = -0.000331 [-0.001029, +0.000363] — IC include 0, a favore della prima.
* **C vs Abeta**: dLogLoss = -0.002071 [-0.005924, +0.001700] — IC include 0, a favore della prima.

I confronti a w = 0 hanno lo stesso segno e ordine di grandezza (leggermente amplificati, come atteso togliendo il Poisson che diluisce al 25%): l'effetto misurato viene dalla conversione, non dal blend.

## 6. Livello 2 — sistemi completi (tabella pooled e per fold)

**Comando**: `python audit/elo_conversion_audit.py` (sezione S5). Per ogni variante e per ogni fold: (a) parametri della mappa stimati sui dati di stima massimizzando la LogLoss solo-Elo; (b) w scelto sulla griglia 0..1 passo 0.05 sul blend, sempre sui soli dati di stima. Poi **tutto congelato** e valutato sul fold successivo. Delta vs **A0**.

| fold | confronto | n | n_blocchi | LL_a | LL_b | dLL | dLL_lo | dLL_hi | dBrier | dBr_lo | dBr_hi | RPS_a | RPS_b |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Fold 1 | Abeta vs A0 | 1752 | 182 | 0.992213 | 0.991472 | 0.000741 | 0.000247 | 0.001282 | 0.000429 | 0.000154 | 0.000718 | 0.201887 | 0.201766 |
| Fold 1 | B vs A0 | 1752 | 182 | 0.992659 | 0.991472 | 0.001187 | -0.001806 | 0.004430 | 0.001410 | -0.000405 | 0.003271 | 0.202408 | 0.201766 |
| Fold 1 | C vs A0 | 1752 | 182 | 0.987682 | 0.991472 | -0.003791 | -0.009094 | 0.001698 | -0.001538 | -0.004039 | 0.000936 | 0.201561 | 0.201766 |
| Fold 2 | Abeta vs A0 | 1752 | 182 | 0.992076 | 0.993535 | -0.001459 | -0.002741 | -0.000277 | -0.000980 | -0.001755 | -0.000265 | 0.201678 | 0.201995 |
| Fold 2 | B vs A0 | 1752 | 182 | 0.997283 | 0.993535 | 0.003748 | 0.000535 | 0.006921 | 0.002831 | 0.001196 | 0.004552 | 0.203409 | 0.201995 |
| Fold 2 | C vs A0 | 1752 | 182 | 0.992381 | 0.993535 | -0.001154 | -0.006171 | 0.003670 | -0.000721 | -0.002870 | 0.001356 | 0.202359 | 0.201995 |
| POOLED | Abeta vs A0 | 3504 | 364 | 0.992144 | 0.992504 | -0.000359 | -0.001006 | 0.000288 | -0.000276 | -0.000678 | 0.000110 | 0.201782 | 0.201880 |
| POOLED | B vs A0 | 3504 | 364 | 0.994971 | 0.992504 | 0.002467 | 0.000252 | 0.004661 | 0.002120 | 0.000870 | 0.003303 | 0.202909 | 0.201880 |
| POOLED | C vs A0 | 3504 | 364 | 0.990031 | 0.992504 | -0.002472 | -0.006143 | 0.001072 | -0.001130 | -0.002811 | 0.000452 | 0.201960 | 0.201880 |

Legenda: `LL_a` = LogLoss della variante, `LL_b` = LogLoss di A0, `dLL = LL_a - LL_b` appaiato riga per riga, IC 95% da bootstrap a blocchi; `dBrier` idem sul Brier 1X2 (vincolo di sicurezza: <= +0.0005).

## 7. Diagnostiche (non criteri)

**Comando**: `python audit/elo_conversion_audit.py` (sezione S6)

### 7.1 RPS, LogLoss, Brier pooled

| variante | RPS | LogLoss | Brier |
|---|---|---|---|
| A0 | 0.201880 | 0.992504 | 0.591304 |
| Abeta | 0.201782 | 0.992144 | 0.591028 |
| B | 0.202909 | 0.994971 | 0.593425 |
| C | 0.201960 | 0.990031 | 0.590175 |

### 7.2 Calibrazione per esito a decili (slope e intercept)

Retta `frequenza osservata ~ intercept + slope * probabilita' prevista` sui 10 decili, pesata per numerosita'. Calibrazione perfetta: slope 1, intercept 0.

| variante | esito | n_decili | slope | intercept | p_media | oss_media | max_gap_decile |
|---|---|---|---|---|---|---|---|
| A0 | 1 | 10 | 0.905334 | 0.023549 | 0.449040 | 0.430080 | 0.079718 |
| A0 | X | 10 | 0.826316 | 0.075799 | 0.213234 | 0.251998 | 0.075305 |
| A0 | 2 | 10 | 0.902459 | 0.013148 | 0.337715 | 0.317922 | 0.062118 |
| Abeta | 1 | 10 | 0.914472 | 0.020850 | 0.447504 | 0.430080 | 0.073559 |
| Abeta | X | 10 | 0.838474 | 0.072067 | 0.214593 | 0.251998 | 0.071345 |
| Abeta | 2 | 10 | 0.917585 | 0.007877 | 0.337893 | 0.317922 | 0.054632 |
| B | 1 | 10 | 0.825241 | 0.053238 | 0.456645 | 0.430080 | 0.111541 |
| B | X | 10 | 0.819056 | 0.077442 | 0.213118 | 0.251998 | 0.083705 |
| B | 2 | 10 | 0.813029 | 0.049438 | 0.330227 | 0.317922 | 0.102973 |
| C | 1 | 10 | 0.865537 | 0.057138 | 0.430879 | 0.430080 | 0.056664 |
| C | X | 10 | 0.833911 | 0.048543 | 0.243977 | 0.251998 | 0.063811 |
| C | 2 | 10 | 0.850042 | 0.041542 | 0.325137 | 0.317922 | 0.069364 |

### 7.3 Delta LogLoss vs A0 per fascia di |d|

| variante | fascia | n | dLL | lo | hi |
|---|---|---|---|---|---|
| Abeta | [0,25) | 390 | -0.000008 | -0.000163 | 0.000144 |
| Abeta | [25,50) | 373 | -0.000212 | -0.000574 | 0.000142 |
| Abeta | [50,100) | 692 | -0.000074 | -0.000650 | 0.000515 |
| Abeta | [100,200) | 1097 | -0.000575 | -0.001579 | 0.000457 |
| Abeta | [200,400) | 869 | -0.000642 | -0.002670 | 0.001617 |
| Abeta | >=400 | 83 | 0.000754 | -0.007439 | 0.007943 |
| B | [0,25) | 390 | -0.000464 | -0.002006 | 0.001049 |
| B | [25,50) | 373 | 0.001116 | -0.001607 | 0.003949 |
| B | [50,100) | 692 | -0.001405 | -0.004757 | 0.002056 |
| B | [100,200) | 1097 | 0.004577 | 0.000157 | 0.009280 |
| B | [200,400) | 869 | 0.003778 | -0.002414 | 0.009586 |
| B | >=400 | 83 | 0.012986 | -0.011484 | 0.046776 |
| C | [0,25) | 390 | -0.000355 | -0.007008 | 0.006440 |
| C | [25,50) | 373 | -0.001933 | -0.010213 | 0.006300 |
| C | [50,100) | 692 | -0.003093 | -0.009334 | 0.003068 |
| C | [100,200) | 1097 | -0.000223 | -0.006405 | 0.006189 |
| C | [200,400) | 869 | -0.006585 | -0.016360 | 0.003385 |
| C | >=400 | 83 | 0.003653 | -0.033525 | 0.040963 |

### 7.4 Favorite estreme

| soglia_maxP | n | variante | dLL | lo | hi |
|---|---|---|---|---|---|
| 0.700000 | 625 | Abeta | -0.000011 | -0.002832 | 0.002797 |
| 0.700000 | 625 | B | 0.004080 | -0.003387 | 0.012108 |
| 0.700000 | 625 | C | -0.007660 | -0.020306 | 0.004916 |
| 0.800000 | 251 | Abeta | -0.001748 | -0.006886 | 0.003119 |
| 0.800000 | 251 | B | 0.006718 | -0.005031 | 0.021029 |
| 0.800000 | 251 | C | -0.004246 | -0.026008 | 0.016912 |

### 7.5 Righe con squadre mai viste o di ritorno

| gruppo | n | variante | dLL | lo | hi |
|---|---|---|---|---|---|
| mai viste / di ritorno | 514 | Abeta | -0.001921 | -0.004103 | 0.000173 |
| resto | 2990 | Abeta | -0.000091 | -0.000778 | 0.000610 |
| mai viste / di ritorno | 514 | B | -0.002319 | -0.007863 | 0.003534 |
| resto | 2990 | B | 0.003290 | 0.000906 | 0.005634 |
| mai viste / di ritorno | 514 | C | -0.009243 | -0.018145 | -0.000098 |
| resto | 2990 | C | -0.001308 | -0.005227 | 0.002384 |

### 7.6 Segno di Delta LogLoss per lega e per fold

| variante | lega | stagione | n | dLL | lo | hi | segno |
|---|---|---|---|---|---|---|---|
| Abeta | Bundesliga | 2024/25 | 306 | 0.002269 | 0.000837 | 0.004121 | + |
| Abeta | Bundesliga | 2025/26 | 306 | -0.001336 | -0.004969 | 0.002194 | - |
| Abeta | La Liga | 2024/25 | 380 | 0.000525 | -0.000615 | 0.001727 | + |
| Abeta | La Liga | 2025/26 | 380 | -0.001007 | -0.003204 | 0.001105 | - |
| Abeta | Ligue 1 | 2024/25 | 306 | -0.000250 | -0.001000 | 0.000505 | - |
| Abeta | Ligue 1 | 2025/26 | 306 | -0.000744 | -0.003934 | 0.002257 | - |
| Abeta | Premier League | 2024/25 | 380 | 0.001022 | 0.000117 | 0.001891 | + |
| Abeta | Premier League | 2025/26 | 380 | -0.002325 | -0.005407 | 0.000342 | - |
| Abeta | Serie A | 2024/25 | 380 | 0.000242 | -0.000555 | 0.001140 | + |
| Abeta | Serie A | 2025/26 | 380 | -0.001720 | -0.003557 | 0.000080 | - |
| B | Bundesliga | 2024/25 | 306 | 0.009993 | 0.000486 | 0.022107 | + |
| B | Bundesliga | 2025/26 | 306 | 0.003513 | -0.006085 | 0.013387 | + |
| B | La Liga | 2024/25 | 380 | 0.001002 | -0.004449 | 0.006886 | + |
| B | La Liga | 2025/26 | 380 | 0.005901 | -0.000080 | 0.011941 | + |
| B | Ligue 1 | 2024/25 | 306 | -0.000315 | -0.006515 | 0.005622 | - |
| B | Ligue 1 | 2025/26 | 306 | 0.001962 | -0.004778 | 0.008960 | + |
| B | Premier League | 2024/25 | 380 | 0.000594 | -0.005696 | 0.006793 | + |
| B | Premier League | 2025/26 | 380 | 0.000916 | -0.004722 | 0.006924 | + |
| B | Serie A | 2024/25 | 380 | -0.003919 | -0.009904 | 0.002614 | - |
| B | Serie A | 2025/26 | 380 | 0.006055 | -0.000482 | 0.012542 | + |
| C | Bundesliga | 2024/25 | 306 | -0.001161 | -0.016802 | 0.015251 | - |
| C | Bundesliga | 2025/26 | 306 | -0.005074 | -0.014828 | 0.004074 | - |
| C | La Liga | 2024/25 | 380 | 0.000037 | -0.008381 | 0.008678 | + |
| C | La Liga | 2025/26 | 380 | 0.007630 | -0.002437 | 0.018055 | + |
| C | Ligue 1 | 2024/25 | 306 | 0.004234 | -0.007301 | 0.015154 | + |
| C | Ligue 1 | 2025/26 | 306 | -0.000163 | -0.009466 | 0.009215 | - |
| C | Premier League | 2024/25 | 380 | -0.006132 | -0.018232 | 0.006215 | - |
| C | Premier League | 2025/26 | 380 | -0.008616 | -0.021057 | 0.002755 | - |
| C | Serie A | 2024/25 | 380 | -0.013858 | -0.024511 | -0.002370 | - |
| C | Serie A | 2025/26 | 380 | -0.000116 | -0.011267 | 0.010383 | - |

### 7.7 Diagnostica NON candidata: multinomial logit su d vs C

| fold | confronto | n | LL_a | LL_b | dLL | dLL_lo | dLL_hi | max_abs_diff | mean_abs_diff |
|---|---|---|---|---|---|---|---|---|---|
| Fold 1 | MNL vs C (solo-Elo, w=0) | 1752 | 0.994296 | 0.993488 | 0.000808 | -0.002300 | 0.003989 | 0.051900 | 0.012015 |
| Fold 2 | MNL vs C (solo-Elo, w=0) | 1752 | 1.000707 | 0.998859 | 0.001848 | -0.000107 | 0.003803 | 0.039400 | 0.008511 |

**Esito**: il multinomial logit **non** diverge molto da C. Su entrambi i fold la differenza media per componente e' 0.0085-0.0120 e la massima 0.0519; la differenza di LogLoss e' positiva (MNL leggermente peggiore in validazione, pur avendo un parametro in piu') con IC che include lo zero. Nessuna divergenza da segnalare.

## 8. Impatto Top Mix

**Comando**: `python audit/elo_conversion_audit.py` (sezione S7)

**Fattibilita'**: **VERIFICABILE senza toccare la produzione.** Il selettore `app.seleziona_riga_top_mix` e' una funzione **pura** che accetta `elo_probs` iniettate dal chiamante; `app.riga_top_mix_shadow` espone `disaccordo` e `gate_avrebbe_scartato` (il selettore reale ritorna `None` sia per soglia sia per veto, quindi da solo non permetterebbe di distinguere le due cause); `app.classifica_top_mix` ordina e assegna il rank. Tutte e tre sono importate e usate **invariate**. La testa Poisson e i mercati Totali (u25, gg) sono tenuti **fissi** fra le varianti: l'unica cosa che cambia e' l'Elo iniettato, quindi ogni differenza misurata e' attribuibile alla conversione.

Perimetro: **TUTTE** le candidate dei due fold di valutazione (1752 per fold), non solo quelle ammesse.

| fold | variante | n_candidate | ammesse_A0 | ammesse_var | ammissione_cambia | entrate | uscite | veto_cambia | veto_in | veto_out | d_confidence_media_tutte | d_confidence_media_ammesse_da_entrambe | giornate | top10_ordine_diverso | top10_composizione_diversa | righe_con_rank_diverso | righe_in_rank_confrontabili |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Fold 1 | Abeta | 1752 | 1233 | 1248 | 15 | 15 | 0 | 11 | 0 | 11 | 0.002083 | 0.002455 | 182 | 45 | 15 | 95 | 1233 |
| Fold 1 | B | 1752 | 1233 | 1293 | 60 | 60 | 0 | 40 | 0 | 40 | 0.009884 | 0.010741 | 182 | 124 | 51 | 329 | 1233 |
| Fold 1 | C | 1752 | 1233 | 1260 | 27 | 27 | 0 | 29 | 5 | 24 | 0.002188 | 0.003440 | 182 | 64 | 27 | 145 | 1233 |
| Fold 2 | Abeta | 1752 | 1250 | 1213 | 37 | 0 | 37 | 31 | 31 | 0 | -0.005086 | -0.005892 | 182 | 96 | 35 | 237 | 1213 |
| Fold 2 | B | 1752 | 1250 | 1307 | 57 | 57 | 0 | 41 | 2 | 39 | 0.009365 | 0.010418 | 182 | 130 | 52 | 325 | 1250 |
| Fold 2 | C | 1752 | 1250 | 1237 | 29 | 8 | 21 | 25 | 24 | 1 | -0.003695 | -0.003744 | 182 | 89 | 27 | 202 | 1229 |

Legenda: `entrate`/`uscite` = righe che la variante ammette e A0 no / viceversa. `veto_in`/`veto_out` = righe su cui il veto `|P-E| >= 0.25` si attiva con la variante e non con A0 / viceversa. `top10_ordine_diverso` = giornate (lega x stagione x giornata) in cui la sequenza dei primi 10 cambia; `top10_composizione_diversa` = giornate in cui cambia proprio l'INSIEME dei primi 10.

## 9. Chiusura

### 9.1 Violazioni del vincolo di B

**2 righe su 7334** (tutte le stagioni) hanno `p_draw > 2*min(e_H, 1-e_H)`, cioe' attivano il troncamento di B. Caso peggiore: split 2024/25, fascia >=400 (4.6512%). Nei due fold di valutazione le righe attive sono 2 su 3504.

### 9.2 Parametri stimati per fold (beta, tau, w)

| fold | variante | beta | tau0 | tau1 | w |
|---|---|---|---|---|---|
| Fold 1 | A0 |  |  |  | 0.350000 |
| Fold 1 | Abeta | 1.032074 |  |  | 0.350000 |
| Fold 1 | B |  |  |  | 0.300000 |
| Fold 1 | C | 0.006160 | -0.584256 | 0.702818 | 0.250000 |
| Fold 2 | A0 |  |  |  | 0.300000 |
| Fold 2 | Abeta | 0.922354 |  |  | 0.300000 |
| Fold 2 | B |  |  |  | 0.300000 |
| Fold 2 | C | 0.005486 | -0.552932 | 0.682729 | 0.250000 |

### 9.3 Tabella pooled e per fold: dLogLoss, IC, dBrier

**Livello 2 (sistemi completi), confronto vs A0**

| fold | confronto | n | dLL | dLL_lo | dLL_hi | dBrier | dBr_lo | dBr_hi |
|---|---|---|---|---|---|---|---|---|
| Fold 1 | Abeta vs A0 | 1752 | 0.000741 | 0.000247 | 0.001282 | 0.000429 | 0.000154 | 0.000718 |
| Fold 1 | B vs A0 | 1752 | 0.001187 | -0.001806 | 0.004430 | 0.001410 | -0.000405 | 0.003271 |
| Fold 1 | C vs A0 | 1752 | -0.003791 | -0.009094 | 0.001698 | -0.001538 | -0.004039 | 0.000936 |
| Fold 2 | Abeta vs A0 | 1752 | -0.001459 | -0.002741 | -0.000277 | -0.000980 | -0.001755 | -0.000265 |
| Fold 2 | B vs A0 | 1752 | 0.003748 | 0.000535 | 0.006921 | 0.002831 | 0.001196 | 0.004552 |
| Fold 2 | C vs A0 | 1752 | -0.001154 | -0.006171 | 0.003670 | -0.000721 | -0.002870 | 0.001356 |
| POOLED | Abeta vs A0 | 3504 | -0.000359 | -0.001006 | 0.000288 | -0.000276 | -0.000678 | 0.000110 |
| POOLED | B vs A0 | 3504 | 0.002467 | 0.000252 | 0.004661 | 0.002120 | 0.000870 | 0.003303 |
| POOLED | C vs A0 | 3504 | -0.002472 | -0.006143 | 0.001072 | -0.001130 | -0.002811 | 0.000452 |

**Livello 1 (w = 0.25 fisso)**

| fold | confronto | n | dLL | dLL_lo | dLL_hi | dBrier |
|---|---|---|---|---|---|---|
| Fold 1 | B vs A0 | 1752 | 0.001502 | -0.001737 | 0.005094 | 0.001993 |
| Fold 1 | Abeta vs A0 | 1752 | 0.000810 | 0.000258 | 0.001408 | 0.000478 |
| Fold 1 | C vs Abeta | 1752 | -0.004270 | -0.009897 | 0.001524 | -0.001382 |
| Fold 2 | B vs A0 | 1752 | 0.003772 | 0.000467 | 0.007120 | 0.003009 |
| Fold 2 | Abeta vs A0 | 1752 | -0.001473 | -0.002839 | -0.000217 | -0.001006 |
| Fold 2 | C vs Abeta | 1752 | 0.000127 | -0.004841 | 0.004977 | 0.000302 |
| POOLED | B vs A0 | 3504 | 0.002637 | 0.000341 | 0.005070 | 0.002501 |
| POOLED | Abeta vs A0 | 3504 | -0.000331 | -0.001029 | 0.000363 | -0.000264 |
| POOLED | C vs Abeta | 3504 | -0.002071 | -0.005924 | 0.001700 | -0.000540 |

**Livello 1 (w = 0, diagnostica)**

| fold | confronto | n | dLL | dLL_lo | dLL_hi | dBrier |
|---|---|---|---|---|---|---|
| Fold 1 | B vs A0 | 1752 | 0.001472 | -0.002773 | 0.005993 | 0.002503 |
| Fold 1 | Abeta vs A0 | 1752 | 0.001096 | 0.000363 | 0.001853 | 0.000583 |
| Fold 1 | C vs Abeta | 1752 | -0.006101 | -0.013648 | 0.001645 | -0.001688 |
| Fold 2 | B vs A0 | 1752 | 0.004392 | 0.000151 | 0.008688 | 0.003856 |
| Fold 2 | Abeta vs A0 | 1752 | -0.001673 | -0.003505 | 0.000021 | -0.001043 |
| Fold 2 | C vs Abeta | 1752 | -0.000996 | -0.007420 | 0.005308 | -0.000034 |
| POOLED | B vs A0 | 3504 | 0.002932 | -0.000064 | 0.006011 | 0.003179 |
| POOLED | Abeta vs A0 | 3504 | -0.000288 | -0.001238 | 0.000659 | -0.000230 |
| POOLED | C vs Abeta | 3504 | -0.003549 | -0.008674 | 0.001420 | -0.000861 |

### 9.4 Impatto Top Mix (sintesi)

| variante | ammissione_cambia | veto_cambia | righe_con_rank_diverso | top10_composizione_diversa | giornate | su_candidate |
|---|---|---|---|---|---|---|
| Abeta | 52 | 42 | 332 | 50 | 364 | 3504 |
| B | 117 | 81 | 654 | 103 | 364 | 3504 |
| C | 56 | 54 | 347 | 54 | 364 | 3504 |

### 9.5 Verdetto per variante

Regola decisionale, fissata **prima** di guardare i risultati:

* **BATTE A0** se: dLogLoss pooled < 0 **e** IC al 95% che esclude lo 0 **e** dLogLoss < 0 in **entrambi** i fold **e** dBrier <= +0.0005;
* **NON INFERIORE** — via riservata dal mandato alla sola **B**: estremo superiore dell'IC di dLogLoss < +0.0005 **e** dBrier <= +0.0005;
* **PEGGIORE** se l'IC di dLogLoss sta tutto sopra 0, o se il vincolo di Brier e' violato;
* **NON DISTINGUIBILE** altrimenti.

| variante | dLL_pooled | lo | hi | dBrier | dLL_fold1 | dLL_fold2 | IC_esclude_0 | negativo_in_entrambi | soglia_non_inf_rispettata | brier_ok | verdetto |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Abeta | -0.000359 | -0.001006 | 0.000288 | -0.000276 | 0.000741 | -0.001459 | False | False | True | True | NON DISTINGUIBILE |
| B | 0.002467 | 0.000252 | 0.004661 | 0.002120 | 0.001187 | 0.003748 | True | False | False | False | PEGGIORE |
| C | -0.002472 | -0.006143 | 0.001072 | -0.001130 | -0.003791 | -0.001154 | False | True | False | True | NON DISTINGUIBILE |

* **Abeta -> NON DISTINGUIBILE**
* **B -> PEGGIORE**
* **C -> NON DISTINGUIBILE**

Nota, da non confondere con un verdetto: **Abeta** soddisfa anche la soglia di non-inferiorita' (estremo superiore dell'IC +0.000288 < +0.0005, dBrier -0.000276 <= +0.0005). Il mandato riserva pero' quella via alla sola B, quindi il verdetto di Abeta resta NON DISTINGUIBILE.

### 9.6 Interpretazione secondo la griglia del mandato

* C vs A0 (Livello 2, pooled): **NON DISTINGUIBILE**.
* Abeta vs A0 (Livello 2, pooled): **NON DISTINGUIBILE**.
* C vs Abeta (Livello 1, pooled, w=0.25): dLogLoss = -0.002071 [-0.005924, +0.001700] — IC include lo 0.

Nessuna delle tre chiavi di lettura del mandato ("C batte A0 ma non Abeta = era scala", "C batte Abeta = la forma conta", "Abeta batte tutto = il problema era la scala") si attiva: **nessuna variante soddisfa il criterio BATTE A0**, e tutti e tre i confronti di Livello 1 che coinvolgono C hanno IC che includono lo zero. Il campione di 3504 partite non separa le ipotesi.

### 9.7 Nulla e' stato applicato

Nessun file sotto `SoccerMath/` e' stato toccato; `app.POISSON_1X2_WEIGHT` resta 0.25; nessuna variante e' stata introdotta in produzione; nessun merge e' stato eseguito.

---

## Appendice A — log completo della run

```
========================================================================
S0. Formula di p_draw (dalla docstring di produzione)
========================================================================
3. probabilita' di pareggio: campana gaussiana centrata sull'equilibrio
       (dr = 0), ampiezza 0.27, scala 320, troncata nell'intervallo
       [0.06, 0.34]::

           p_draw = 0.27 * exp(-((dr / 320) ** 2))
           p_draw = max(0.06, min(0.34, p_draw))
codice:
    p_draw = 0.27 * math.exp(-((dr / 320.0) ** 2))
    p_draw = max(0.06, min(0.34, p_draw))
    p_home = (1.0 - p_draw) * e_h
    p_away = (1.0 - p_draw) * e_a
    total = p_home + p_draw + p_away

produzione sporca rispetto a HEAD: (pulita)

========================================================================
S1. Campione
========================================================================
| league | n_walker_elo | n_poisson_walker | n_join | solo_walker | solo_poisson |
|---|---|---|---|---|---|
| Serie A | 1570 | 1570 | 1570 | 0 | 0 |
| Premier League | 1570 | 1570 | 1570 | 0 | 0 |
| La Liga | 1591 | 1591 | 1591 | 0 | 0 |
| Bundesliga | 1260 | 1260 | 1260 | 0 | 0 |
| Ligue 1 | 1343 | 1343 | 1343 | 0 | 0 |

| split | n |
|---|---|
| 2023/24 | 1752 |
| 2024/25 | 1752 |
| 2025/26 | 1752 |
| burn-in | 1826 |
| esclusa | 252 |

========================================================================
S2. Righe con p_draw > 2*min(e_H, 1-e_H)  (pre-modello)
========================================================================
per split:
| split | n_attive | n | quota |
|---|---|---|---|
| 2023/24 | 0 | 1752 | 0.000000 |
| 2024/25 | 2 | 1752 | 0.001142 |
| 2025/26 | 0 | 1752 | 0.000000 |
| burn-in | 0 | 1826 | 0.000000 |
| esclusa | 0 | 252 | 0.000000 |

totale righe attive: 2 / 7334

caso peggiore per (split x fascia):
| split | fascia_d | n_attive | n | quota |
|---|---|---|---|---|
| 2024/25 | >=400 | 2 | 43 | 0.046512 |

caso peggiore per (split x lega):
| split | league | n_attive | n | quota |
|---|---|---|---|---|
| 2024/25 | Premier League | 2 | 380 | 0.005263 |

elenco completo delle righe attive:
| league | season | giornata | date | home | away | d_exact | e_H | p_draw | real_1x2 |
|---|---|---|---|---|---|---|---|---|---|
| Premier League | 2024/25 | 9 | 2024-10-26 | Man City | Southampton | 613.4276 | 0.9716 | 0.0600 | 1 |
| Premier League | 2024/25 | 28 | 2025-03-08 | Liverpool | Southampton | 622.6909 | 0.9730 | 0.0600 | 1 |

========================================================================
S3. Stima dei parametri per fold (LogLoss solo-Elo sui dati di stima)
========================================================================

--- Fold 1: stima su 2023/24 (n=1752), valutazione su 2024/25 ---
  A0     NLL_stima=0.995397  (nessuno)
  Abeta  NLL_stima=0.995292  beta=1.0320738
  B      NLL_stima=0.989004  (nessuno)
  C      NLL_stima=0.982184  tau0=-0.58425565, tau1=0.70281758, beta=0.0061604982
  MNL    NLL_stima=0.981088  aX=-0.15578633, bX=-0.0038160041, a2=0.060879051, b2=-0.0083160329

--- Fold 2: stima su 2023/24+2024/25 (n=3504), valutazione su 2025/26 ---
  A0     NLL_stima=0.996944  (nessuno)
  Abeta  NLL_stima=0.996430  beta=0.92235356
  B      NLL_stima=0.994484  (nessuno)
  C      NLL_stima=0.986438  tau0=-0.55293177, tau1=0.68272937, beta=0.0054862481
  MNL    NLL_stima=0.985938  aX=-0.18007752, bX=-0.0036337462, a2=0.084486874, b2=-0.0072816822

Controllo incrociato C: scipy MLE vs statsmodels OrderedModel
  Fold 1: statsmodels tau0=-0.58425561 tau1=0.70281761 beta=0.0061604978 NLL=0.98218358 | max scarto parametri=4.101e-08 | scarto NLL=4.441e-16
  Fold 2: statsmodels tau0=-0.55293172 tau1=0.6827294 beta=0.0054862475 NLL=0.98643825 | max scarto parametri=5.223e-08 | scarto NLL=9.992e-16

========================================================================
S4. Livello 1 — isolamento a w fisso
========================================================================

--- w = 0.25 ---
| fold | confronto | n | n_blocchi | LL_a | LL_b | dLL | dLL_lo | dLL_hi | dBrier |
|---|---|---|---|---|---|---|---|---|---|
| Fold 1 | B vs A0 | 1752 | 182 | 0.992643 | 0.991141 | 0.001502 | -0.001737 | 0.005094 | 0.001993 |
| Fold 1 | Abeta vs A0 | 1752 | 182 | 0.991952 | 0.991141 | 0.000810 | 0.000258 | 0.001408 | 0.000478 |
| Fold 1 | C vs Abeta | 1752 | 182 | 0.987682 | 0.991952 | -0.004270 | -0.009897 | 0.001524 | -0.001382 |
| Fold 2 | B vs A0 | 1752 | 182 | 0.997500 | 0.993727 | 0.003772 | 0.000467 | 0.007120 | 0.003009 |
| Fold 2 | Abeta vs A0 | 1752 | 182 | 0.992254 | 0.993727 | -0.001473 | -0.002839 | -0.000217 | -0.001006 |
| Fold 2 | C vs Abeta | 1752 | 182 | 0.992381 | 0.992254 | 0.000127 | -0.004841 | 0.004977 | 0.000302 |
| POOLED | B vs A0 | 3504 | 364 | 0.995072 | 0.992434 | 0.002637 | 0.000341 | 0.005070 | 0.002501 |
| POOLED | Abeta vs A0 | 3504 | 364 | 0.992103 | 0.992434 | -0.000331 | -0.001029 | 0.000363 | -0.000264 |
| POOLED | C vs Abeta | 3504 | 364 | 0.990031 | 0.992103 | -0.002071 | -0.005924 | 0.001700 | -0.000540 |

--- w = 0.0 ---
| fold | confronto | n | n_blocchi | LL_a | LL_b | dLL | dLL_lo | dLL_hi | dBrier |
|---|---|---|---|---|---|---|---|---|---|
| Fold 1 | B vs A0 | 1752 | 182 | 0.999965 | 0.998493 | 0.001472 | -0.002773 | 0.005993 | 0.002503 |
| Fold 1 | Abeta vs A0 | 1752 | 182 | 0.999589 | 0.998493 | 0.001096 | 0.000363 | 0.001853 | 0.000583 |
| Fold 1 | C vs Abeta | 1752 | 182 | 0.993488 | 0.999589 | -0.006101 | -0.013648 | 0.001645 | -0.001688 |
| Fold 2 | B vs A0 | 1752 | 182 | 1.005921 | 1.001529 | 0.004392 | 0.000151 | 0.008688 | 0.003856 |
| Fold 2 | Abeta vs A0 | 1752 | 182 | 0.999856 | 1.001529 | -0.001673 | -0.003505 | 0.000021 | -0.001043 |
| Fold 2 | C vs Abeta | 1752 | 182 | 0.998859 | 0.999856 | -0.000996 | -0.007420 | 0.005308 | -0.000034 |
| POOLED | B vs A0 | 3504 | 364 | 1.002943 | 1.000011 | 0.002932 | -0.000064 | 0.006011 | 0.003179 |
| POOLED | Abeta vs A0 | 3504 | 364 | 0.999722 | 1.000011 | -0.000288 | -0.001238 | 0.000659 | -0.000230 |
| POOLED | C vs Abeta | 3504 | 364 | 0.996174 | 0.999722 | -0.003549 | -0.008674 | 0.001420 | -0.000861 |

========================================================================
S5. Livello 2 — sistemi completi (parametri + w scelti sui dati di stima)
========================================================================

--- Fold 1 ---
  A0     w*=0.35  LL_stima=0.984645  [(nessuno)]
  Abeta  w*=0.35  LL_stima=0.984738  [beta=1.03207]
  B      w*=0.30  LL_stima=0.980777  [(nessuno)]
  C      w*=0.25  LL_stima=0.974448  [tau0=-0.584256, tau1=0.702818, beta=0.0061605]

--- Fold 2 ---
  A0     w*=0.30  LL_stima=0.987899  [(nessuno)]
  Abeta  w*=0.30  LL_stima=0.987221  [beta=0.922354]
  B      w*=0.30  LL_stima=0.986718  [(nessuno)]
  C      w*=0.25  LL_stima=0.980106  [tau0=-0.552932, tau1=0.682729, beta=0.00548625]

tabella Livello 2:
| fold | confronto | n | n_blocchi | LL_a | LL_b | dLL | dLL_lo | dLL_hi | dBrier | RPS_a | RPS_b |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Fold 1 | Abeta vs A0 | 1752 | 182 | 0.992213 | 0.991472 | 0.000741 | 0.000247 | 0.001282 | 0.000429 | 0.201887 | 0.201766 |
| Fold 1 | B vs A0 | 1752 | 182 | 0.992659 | 0.991472 | 0.001187 | -0.001806 | 0.004430 | 0.001410 | 0.202408 | 0.201766 |
| Fold 1 | C vs A0 | 1752 | 182 | 0.987682 | 0.991472 | -0.003791 | -0.009094 | 0.001698 | -0.001538 | 0.201561 | 0.201766 |
| Fold 2 | Abeta vs A0 | 1752 | 182 | 0.992076 | 0.993535 | -0.001459 | -0.002741 | -0.000277 | -0.000980 | 0.201678 | 0.201995 |
| Fold 2 | B vs A0 | 1752 | 182 | 0.997283 | 0.993535 | 0.003748 | 0.000535 | 0.006921 | 0.002831 | 0.203409 | 0.201995 |
| Fold 2 | C vs A0 | 1752 | 182 | 0.992381 | 0.993535 | -0.001154 | -0.006171 | 0.003670 | -0.000721 | 0.202359 | 0.201995 |
| POOLED | Abeta vs A0 | 3504 | 364 | 0.992144 | 0.992504 | -0.000359 | -0.001006 | 0.000288 | -0.000276 | 0.201782 | 0.201880 |
| POOLED | B vs A0 | 3504 | 364 | 0.994971 | 0.992504 | 0.002467 | 0.000252 | 0.004661 | 0.002120 | 0.202909 | 0.201880 |
| POOLED | C vs A0 | 3504 | 364 | 0.990031 | 0.992504 | -0.002472 | -0.006143 | 0.001072 | -0.001130 | 0.201960 | 0.201880 |

verdetti:
| variante | dLL_pooled | lo | hi | dBrier | dLL_fold1 | dLL_fold2 | IC_esclude_0 | negativo_in_entrambi | soglia_non_inf_rispettata | brier_ok | verdetto |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Abeta | -0.000359 | -0.001006 | 0.000288 | -0.000276 | 0.000741 | -0.001459 | False | False | True | True | NON DISTINGUIBILE |
| B | 0.002467 | 0.000252 | 0.004661 | 0.002120 | 0.001187 | 0.003748 | True | False | False | False | PEGGIORE |
| C | -0.002472 | -0.006143 | 0.001072 | -0.001130 | -0.003791 | -0.001154 | False | True | False | True | NON DISTINGUIBILE |

[tempo finora 13.7s]

========================================================================
S6. Diagnostiche (non criteri)
========================================================================

6.1 RPS pooled per variante
| variante | RPS | LogLoss | Brier |
|---|---|---|---|
| A0 | 0.201880 | 0.992504 | 0.591304 |
| Abeta | 0.201782 | 0.992144 | 0.591028 |
| B | 0.202909 | 0.994971 | 0.593425 |
| C | 0.201960 | 0.990031 | 0.590175 |

6.2 Calibrazione a decili per esito (slope e intercept, pooled)
| variante | esito | n_decili | slope | intercept | p_media | oss_media | max_gap_decile |
|---|---|---|---|---|---|---|---|
| A0 | 1 | 10 | 0.905334 | 0.023549 | 0.449040 | 0.430080 | 0.079718 |
| A0 | X | 10 | 0.826316 | 0.075799 | 0.213234 | 0.251998 | 0.075305 |
| A0 | 2 | 10 | 0.902459 | 0.013148 | 0.337715 | 0.317922 | 0.062118 |
| Abeta | 1 | 10 | 0.914472 | 0.020850 | 0.447504 | 0.430080 | 0.073559 |
| Abeta | X | 10 | 0.838474 | 0.072067 | 0.214593 | 0.251998 | 0.071345 |
| Abeta | 2 | 10 | 0.917585 | 0.007877 | 0.337893 | 0.317922 | 0.054632 |
| B | 1 | 10 | 0.825241 | 0.053238 | 0.456645 | 0.430080 | 0.111541 |
| B | X | 10 | 0.819056 | 0.077442 | 0.213118 | 0.251998 | 0.083705 |
| B | 2 | 10 | 0.813029 | 0.049438 | 0.330227 | 0.317922 | 0.102973 |
| C | 1 | 10 | 0.865537 | 0.057138 | 0.430879 | 0.430080 | 0.056664 |
| C | X | 10 | 0.833911 | 0.048543 | 0.243977 | 0.251998 | 0.063811 |
| C | 2 | 10 | 0.850042 | 0.041542 | 0.325137 | 0.317922 | 0.069364 |

6.3 Delta LogLoss vs A0 per fascia di |d| (pooled)
| variante | fascia | n | dLL | lo | hi |
|---|---|---|---|---|---|
| Abeta | [0,25) | 390 | -0.000008 | -0.000163 | 0.000144 |
| Abeta | [25,50) | 373 | -0.000212 | -0.000574 | 0.000142 |
| Abeta | [50,100) | 692 | -0.000074 | -0.000650 | 0.000515 |
| Abeta | [100,200) | 1097 | -0.000575 | -0.001579 | 0.000457 |
| Abeta | [200,400) | 869 | -0.000642 | -0.002670 | 0.001617 |
| Abeta | >=400 | 83 | 0.000754 | -0.007439 | 0.007943 |
| B | [0,25) | 390 | -0.000464 | -0.002006 | 0.001049 |
| B | [25,50) | 373 | 0.001116 | -0.001607 | 0.003949 |
| B | [50,100) | 692 | -0.001405 | -0.004757 | 0.002056 |
| B | [100,200) | 1097 | 0.004577 | 0.000157 | 0.009280 |
| B | [200,400) | 869 | 0.003778 | -0.002414 | 0.009586 |
| B | >=400 | 83 | 0.012986 | -0.011484 | 0.046776 |
| C | [0,25) | 390 | -0.000355 | -0.007008 | 0.006440 |
| C | [25,50) | 373 | -0.001933 | -0.010213 | 0.006300 |
| C | [50,100) | 692 | -0.003093 | -0.009334 | 0.003068 |
| C | [100,200) | 1097 | -0.000223 | -0.006405 | 0.006189 |
| C | [200,400) | 869 | -0.006585 | -0.016360 | 0.003385 |
| C | >=400 | 83 | 0.003653 | -0.033525 | 0.040963 |

6.4 Favorite estreme (max probabilita' A0 sopra soglia)
| soglia_maxP | n | variante | dLL | lo | hi |
|---|---|---|---|---|---|
| 0.700000 | 625 | Abeta | -0.000011 | -0.002832 | 0.002797 |
| 0.700000 | 625 | B | 0.004080 | -0.003387 | 0.012108 |
| 0.700000 | 625 | C | -0.007660 | -0.020306 | 0.004916 |
| 0.800000 | 251 | Abeta | -0.001748 | -0.006886 | 0.003119 |
| 0.800000 | 251 | B | 0.006718 | -0.005031 | 0.021029 |
| 0.800000 | 251 | C | -0.004246 | -0.026008 | 0.016912 |

6.5 Righe con squadre mai viste o di ritorno
| gruppo | n | variante | dLL | lo | hi |
|---|---|---|---|---|---|
| mai viste / di ritorno | 514 | Abeta | -0.001921 | -0.004103 | 0.000173 |
| resto | 2990 | Abeta | -0.000091 | -0.000778 | 0.000610 |
| mai viste / di ritorno | 514 | B | -0.002319 | -0.007863 | 0.003534 |
| resto | 2990 | B | 0.003290 | 0.000906 | 0.005634 |
| mai viste / di ritorno | 514 | C | -0.009243 | -0.018145 | -0.000098 |
| resto | 2990 | C | -0.001308 | -0.005227 | 0.002384 |
  (mai viste=14, di ritorno=500)

6.6 Segno di Delta LogLoss per lega e per fold
| variante | lega | stagione | n | dLL | lo | hi | segno |
|---|---|---|---|---|---|---|---|
| Abeta | Bundesliga | 2024/25 | 306 | 0.002269 | 0.000837 | 0.004121 | + |
| Abeta | Bundesliga | 2025/26 | 306 | -0.001336 | -0.004969 | 0.002194 | - |
| Abeta | La Liga | 2024/25 | 380 | 0.000525 | -0.000615 | 0.001727 | + |
| Abeta | La Liga | 2025/26 | 380 | -0.001007 | -0.003204 | 0.001105 | - |
| Abeta | Ligue 1 | 2024/25 | 306 | -0.000250 | -0.001000 | 0.000505 | - |
| Abeta | Ligue 1 | 2025/26 | 306 | -0.000744 | -0.003934 | 0.002257 | - |
| Abeta | Premier League | 2024/25 | 380 | 0.001022 | 0.000117 | 0.001891 | + |
| Abeta | Premier League | 2025/26 | 380 | -0.002325 | -0.005407 | 0.000342 | - |
| Abeta | Serie A | 2024/25 | 380 | 0.000242 | -0.000555 | 0.001140 | + |
| Abeta | Serie A | 2025/26 | 380 | -0.001720 | -0.003557 | 0.000080 | - |
| B | Bundesliga | 2024/25 | 306 | 0.009993 | 0.000486 | 0.022107 | + |
| B | Bundesliga | 2025/26 | 306 | 0.003513 | -0.006085 | 0.013387 | + |
| B | La Liga | 2024/25 | 380 | 0.001002 | -0.004449 | 0.006886 | + |
| B | La Liga | 2025/26 | 380 | 0.005901 | -0.000080 | 0.011941 | + |
| B | Ligue 1 | 2024/25 | 306 | -0.000315 | -0.006515 | 0.005622 | - |
| B | Ligue 1 | 2025/26 | 306 | 0.001962 | -0.004778 | 0.008960 | + |
| B | Premier League | 2024/25 | 380 | 0.000594 | -0.005696 | 0.006793 | + |
| B | Premier League | 2025/26 | 380 | 0.000916 | -0.004722 | 0.006924 | + |
| B | Serie A | 2024/25 | 380 | -0.003919 | -0.009904 | 0.002614 | - |
| B | Serie A | 2025/26 | 380 | 0.006055 | -0.000482 | 0.012542 | + |
| C | Bundesliga | 2024/25 | 306 | -0.001161 | -0.016802 | 0.015251 | - |
| C | Bundesliga | 2025/26 | 306 | -0.005074 | -0.014828 | 0.004074 | - |
| C | La Liga | 2024/25 | 380 | 0.000037 | -0.008381 | 0.008678 | + |
| C | La Liga | 2025/26 | 380 | 0.007630 | -0.002437 | 0.018055 | + |
| C | Ligue 1 | 2024/25 | 306 | 0.004234 | -0.007301 | 0.015154 | + |
| C | Ligue 1 | 2025/26 | 306 | -0.000163 | -0.009466 | 0.009215 | - |
| C | Premier League | 2024/25 | 380 | -0.006132 | -0.018232 | 0.006215 | - |
| C | Premier League | 2025/26 | 380 | -0.008616 | -0.021057 | 0.002755 | - |
| C | Serie A | 2024/25 | 380 | -0.013858 | -0.024511 | -0.002370 | - |
| C | Serie A | 2025/26 | 380 | -0.000116 | -0.011267 | 0.010383 | - |

conteggio dei segni per variante:
| variante | + | - |
|---|---|---|
| Abeta | 4 | 6 |
| B | 8 | 2 |
| C | 3 | 7 |

6.7 DIAGNOSTICA (non candidata): multinomial logit su d vs C
| fold | confronto | n | LL_a | LL_b | dLL | dLL_lo | dLL_hi | max_abs_diff | mean_abs_diff |
|---|---|---|---|---|---|---|---|---|---|
| Fold 1 | MNL vs C (solo-Elo, w=0) | 1752 | 0.994296 | 0.993488 | 0.000808 | -0.002300 | 0.003989 | 0.051900 | 0.012015 |
| Fold 2 | MNL vs C (solo-Elo, w=0) | 1752 | 1.000707 | 0.998859 | 0.001848 | -0.000107 | 0.003803 | 0.039400 | 0.008511 |

========================================================================
S7. Impatto Top Mix (selettore PURO di produzione, Elo iniettato)
========================================================================
  Fold 1 Abeta  ammissione_cambia=  15 veto_cambia= 11 dconf=+0.002083 rank_div=  95 top10_comp=15/182
  Fold 1 B      ammissione_cambia=  60 veto_cambia= 40 dconf=+0.009884 rank_div= 329 top10_comp=51/182
  Fold 1 C      ammissione_cambia=  27 veto_cambia= 29 dconf=+0.002188 rank_div= 145 top10_comp=27/182
  Fold 2 Abeta  ammissione_cambia=  37 veto_cambia= 31 dconf=-0.005086 rank_div= 237 top10_comp=35/182
  Fold 2 B      ammissione_cambia=  57 veto_cambia= 41 dconf=+0.009365 rank_div= 325 top10_comp=52/182
  Fold 2 C      ammissione_cambia=  29 veto_cambia= 25 dconf=-0.003695 rank_div= 202 top10_comp=27/182

| fold | variante | n_candidate | ammesse_A0 | ammesse_var | ammissione_cambia | entrate | uscite | veto_cambia | veto_in | veto_out | d_confidence_media_tutte | d_confidence_media_ammesse_da_entrambe | giornate | top10_ordine_diverso | top10_composizione_diversa | righe_con_rank_diverso | righe_in_rank_confrontabili |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Fold 1 | Abeta | 1752 | 1233 | 1248 | 15 | 15 | 0 | 11 | 0 | 11 | 0.002083 | 0.002455 | 182 | 45 | 15 | 95 | 1233 |
| Fold 1 | B | 1752 | 1233 | 1293 | 60 | 60 | 0 | 40 | 0 | 40 | 0.009884 | 0.010741 | 182 | 124 | 51 | 329 | 1233 |
| Fold 1 | C | 1752 | 1233 | 1260 | 27 | 27 | 0 | 29 | 5 | 24 | 0.002188 | 0.003440 | 182 | 64 | 27 | 145 | 1233 |
| Fold 2 | Abeta | 1752 | 1250 | 1213 | 37 | 0 | 37 | 31 | 31 | 0 | -0.005086 | -0.005892 | 182 | 96 | 35 | 237 | 1213 |
| Fold 2 | B | 1752 | 1250 | 1307 | 57 | 57 | 0 | 41 | 2 | 39 | 0.009365 | 0.010418 | 182 | 130 | 52 | 325 | 1250 |
| Fold 2 | C | 1752 | 1250 | 1237 | 29 | 8 | 21 | 25 | 24 | 1 | -0.003695 | -0.003744 | 182 | 89 | 27 | 202 | 1229 |

artefatto: audit/output/elo_conversion_pooled.csv.gz (3504 righe)

[tempo totale 15.2s]
```
