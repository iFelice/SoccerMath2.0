# Shrinkage onesto sui Totali (O/U2.5, GG/NG) — verifica indipendente

*Generato: 2026-09-19T17:16:46.015577+00:00 — script `audit/verify_shrinkage_totali.py`. Sola lettura: nessuna modifica a produzione, nessun fix committato in questa fase.*

## 0. Fonte e validazione sul motore live vero

Rigioco il replay con il **motore live vero** (`audit.topmix_selector_replay`: funzioni di produzione `get_league_engine`/`get_full_poisson_two_heads`/`predict_elo_probs`/`select_next_matchday_matches`, dati point-in-time) invece di riusare passivamente la replica memorizzata (`topmix_selector_replay_rows.csv`, 3422 candidate / 1865 ammesse). Verifica di identità fresh vs CSV:

- testa **Totali: 1873 righe identiche, 0 diverse** — la conf dei Totali è Poisson puro (nessun Elo per costruzione in `apply_selector_A`): il CSV del 17/09 è confermato base valida bit-per-bit;
- testa **1X2: 1549 conf diverse su 1549 (max Δ = 0.118), mercati diversi: 0** — lo stato Elo di produzione è cambiato dal 05/09 (drift fino a |Δconf|=0.118; su Bundesliga il Δ è uniforme lungo la stagione: è un cambio globale del motore Elo, non un effetto point-in-time). Il controllo 0.91 va quindi condotto sulla fonte del 17/09; il drift è riportato e non influenza i Totali (conf = Poisson puro).

Etichette: **TRAIN = 2024/25**, **VAL/TEST = 2025/26** (VAL = split per la stabilità di k*, TEST = valutazione frozen: stessi dati, ruoli diversi come da brief). Entrambe le stagioni sono già state esaminate in passato per il selettore (due teste, forma fuori dai totali, PRIOR_MATCHES=6, pesi 0.6/0.4): il TEST qui vale per la *domanda* shrinkage-totali, non è un hold-out assoluto. Campione = righe **ammesse** (quello che la produzione mostra). k* Brier-optimal in forma chiusa; k* LogLoss come sensibilità. Ancore pre-specificate: **UNCOND** = frequenza incondizionata dell'evento fra i candidati (≈ base rate di mercato); **PICKED** = hit rate realizzata delle ammesse per mercato. CI bootstrap 95% (2000 resample, seed 20260919).

## 1. k* ricalcolato per mercato, non aggregato

| Famiglia | Split | n | hit rate | conf media | k* UNCOND [CI95] | k* PICKED [CI95] | k* LogLoss UNCOND |
|---|---|---:|---:|---:|---:|---:|---:|
| O/U 2.5 | TRAIN | 215 | 60.0% | 64.8% | **0.637** [0.221; 1.000] | **0.000** [0.000; 0.524] | 0.632 |
| O/U 2.5 | VAL | 152 | 55.9% | 64.5% | **0.619** [0.000; 0.910] | **0.291** [0.054; 1.000] | 0.626 |
| O/U 2.5 | POOL | 367 | 58.3% | 64.7% | **0.635** [0.263; 0.895] | **0.282** [0.000; 1.000] | 0.634 |
| GG/NG | TRAIN | 172 | 59.9% | 63.0% | **0.611** [0.000; 1.000] | **0.271** [0.000; 1.000] | 0.614 |
| GG/NG | VAL | 202 | 58.9% | 62.8% | **0.456** [0.000; 0.675] | **0.000** [0.000; 0.639] | 0.454 |
| GG/NG | POOL | 374 | 59.4% | 62.9% | **0.517** [0.000; 1.000] | **0.000** [0.000; 0.676] | 0.517 |
| 1X2 (controllo) | TRAIN | 605 | 66.0% | 69.8% | **0.885** [0.757; 1.000] | **0.848** [0.464; 1.000] | 0.884 |
| 1X2 (controllo) | VAL | 595 | 64.2% | 69.3% | **0.846** [0.708; 0.949] | **0.804** [0.439; 1.000] | 0.856 |
| 1X2 (controllo) | POOL | 1200 | 65.1% | 69.6% | **0.866** [0.771; 0.943] | **0.832** [0.557; 1.000] | 0.871 |

Nota sull'1X2 in tabella: i valori «fresh» usano il motore di OGGI, il cui stato Elo è driftato rispetto al 05/09 (§0): per il confronto col ~0.91 a memoria vale la tabella in §2, calcolata sulla fonte del 17/09.

## 2. Stabilità TRAIN vs VAL (per ancora)

| Famiglia | Ancora | k* TRAIN | k* VAL | Δ | Esito (Δ≤0.15) |
|---|---|---:|---:|---:|---|
| O/U 2.5 | UNCOND | 0.637 | 0.619 | 0.018 | stabile |
| O/U 2.5 | PICKED | 0.000 | 0.291 | 0.291 | **INSTABILE** |
| GG/NG | UNCOND | 0.611 | 0.456 | 0.155 | **INSTABILE** |
| GG/NG | PICKED | 0.271 | 0.000 | 0.271 | **INSTABILE** |
| 1X2 (controllo) | UNCOND | 0.885 | 0.846 | 0.039 | stabile |
| 1X2 (controllo) | PICKED | 0.848 | 0.804 | 0.044 | stabile |

**Controllo di coerenza 1X2 (fonte 17/09, ancora PICKED):** k* = 0.901 sul pool (TRAIN 0.909, VAL 0.831) — **riproduce il ~0.91 a memoria**: la procedura è la stessa della misura precedente e il numero torna.

Lettura dei Totali:

- ancora **UNCOND**: O/U 2.5 è stabile (0.637 → 0.619; LogLoss d'accordo), GG/NG è al limite (Δ≈0.15, soglia passeggera) (0.611 → 0.456); i CI restano larghi (GG/NG TRAIN [0;1]): con n≈150–215 per stagione il singolo k* ha un'incertezza grande anche quando il punto è stabile;
- ancora **PICKED**: entrambe instabili e con valori degeneri (k*=0 su GG/NG VAL/POOL): la selezione tronca la distribuzione a ≥0.60 e la base realizzata coincide con la soglia — ancora inadatta a un uso con soglie.

**Segnalato come richiesto dal brief**: il fenomeno (sovraconfidenza dei Totali mostrati) è robusto e presente in ENTRAMBE le stagioni, ma il *valore* di k* per GG/NG non è stabilmente identificato; per O/U 2.5 l'ancora UNCOND dà un k* riproducibile (~0.62–0.64).

## 3. Walk-forward onesto su TEST 2025/26 (base e k congelati sul TRAIN)

| Famiglia | Ancora | k frozen | n TEST | Sopravvive ≥0.60 | Sparisce | Sopravvive su file intero (equiv. 741) |
|---|---|---:|---:|---:|---:|---:|
| O/U 2.5 | UNCOND | 0.637 | 152 | **55** | 97 | 122/741 |
| O/U 2.5 | PICKED | 0.000 | 152 | **57** | 95 | 132/741 |
| GG/NG | UNCOND | 0.611 | 202 | **80** | 122 | 153/741 |
| GG/NG | PICKED | 0.271 | 202 | **202** | 0 | 372/741 |

«File intero» = stesse (base, k) frozen applicate anche alle righe 2024/25 ammesse (protocollo per-famiglia; il pooled-fit uniforme è qui sotto).

**Verifica del numero a memoria 223/741.** La costruzione che lo approssima è `k* Brier sulle ammesse POOL, ancora UNCOND`: k* = 0.608 → sopravvive **236/741**. Stesso ordine di grandezza della stima a memoria (223/741), replica non esatta: il numero di memoria non è ricostruibile con precisione e va sostituito da questo ricalcolo. Sotto l'ancora PICKED il protocollo frozen dà risultati degenerati per l'uso con soglie (GGNG: la base realizzata ≈ 0.60 = soglia → non sparisce quasi nulla; OU25: k*≈0 → p* costante = base).

## 4. Reliability e Brier delle superstiti (TEST, bin costruiti sulla p grezza)

| Famiglia | Ancora | n sopravvissute | hit | conf raw media | Rel.err raw | Rel.err p* | Brier raw | Brier p* |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| O/U 2.5 | UNCOND | 55 | 61.8% | 68.2% | 0.1237 | **0.1019** | 0.2323 | **0.2325** |
| O/U 2.5 | PICKED | 57 | 49.1% | 65.7% | 0.1748 | **0.1871** | 0.2676 | **0.2807** |
| GG/NG | UNCOND | 80 | 56.2% | 65.0% | 0.0878 | **0.0498** | 0.2531 | **0.2481** |
| GG/NG | PICKED | 202 | 58.9% | 62.8% | 0.0393 | **0.0186** | 0.2453 | **0.2428** |

Lettura: sull'ancora UNCOND (quella supportata dai dati) la reliability delle superstiti migliora in entrambe le famiglie (O/U 0.124→0.102, GG/NG 0.088→0.050) mentre il Brier è praticamente neutro (O/U +0.0002, GG/NG −0.005): comprimere verso la base sistema le probabilità dichiarate senza cambiare la capacità discriminante sulle superstiti. Sull'ancora PICKED il confronto è degenere (k*=0 su O/U: p* costante) o peggiorativo.

## 5. Le righe che SPARISCONO: rumore o segnale genuino?

«Base UNCOND mix» = frequenza incondizionata degli eventi dei mercati spariti (miscela effettiva delle righe eliminate); «Base PICKED mix» = base frozen dell'ancora PICKED per quegli stessi mercati.

| Famiglia | Ancora | n sparite | hit rate reale | Wilson 95% | Base UNCOND mix | Base PICKED mix | Lettura |
|---|---|---:|---:|---:|---:|---:|---|
| O/U 2.5 | UNCOND | 97 | 52.6% | [42.7; 62.2]% | 48.1% | 47.6% | punto sopra la base ma CI che la include: rumore non escluso, segnale non provato |
| O/U 2.5 | PICKED | 95 | 60.0% | [49.9; 69.3]% | 47.0% | 56.4% | hit sopra la base incondizionata: segnale genuino perso |
| GG/NG | UNCOND | 122 | 60.7% | [51.8; 68.9]% | 53.9% | 55.3% | punto sopra la base ma CI che la include: rumore non escluso, segnale non provato |
| GG/NG | PICKED | 0 | — | — | — | — | nessuna sparizione |

**Sintesi (punto 4 del brief).** Le due ancore DICONO COSE DIVERTE sulle righe eliminate, e va riportato senza arbitrare: con l'ancora UNCOND (quella che riproduce l'ordine di grandezza della stima a memoria ed è stabile su O/U) le righe eliminate hanno hit rate **non distinguibili dalla base** (O/U 52.6% vs 48.1%; GG/NG 60.7% vs 53.9%, CI che include la base): lettura «rumore spacciato per confidenza», con la punta che su GG/NG il punto stimato è comunque +6.8 pp sopra la base. Con l'ancora PICKED le righe O/U eliminate mostrano invece un hit 60.0% netto sopra base (47.0%): **segnale genuino che lo shrinkage butterebbe via**. Non è automatico che le eliminate siano rumore: dipende dall'ancora, e l'incertezza (Wilson) non chiude la questione.

## 6. Coerenza per lega (k* UNCOND Brier)

| Famiglia | Lega | n TRAIN | k* TRAIN [CI95] | n POOL | k* POOL [CI95] | hit POOL | conf media POOL |
|---|---|---:|---|---:|---|---:|---:|
| O/U 2.5 | Bundesliga | 53 | 0.802 [0.00; 1.00] | 76 | 0.760 [0.00; 1.00] | 64.5% | 68.0% |
| O/U 2.5 | La Liga | 71 | 0.842 [0.10; 1.00] | 129 | 0.796 [0.00; 1.00] | 59.7% | 64.1% |
| O/U 2.5 | Ligue 1 | 13 | n/d (n<15) | 20 | 0.849 [0.00; 1.00] | 60.0% | 63.0% |
| O/U 2.5 | Premier League | 18 | 0.180 [0.00; 1.00] | 47 | 0.000 [0.00; 0.83] | 46.8% | 64.4% |
| O/U 2.5 | Serie A | 60 | 0.377 [0.00; 1.00] | 95 | 0.532 [0.00; 1.00] | 56.8% | 63.2% |
| GG/NG | Bundesliga | 69 | 1.000 [0.00; 1.00] | 153 | 1.000 [0.00; 1.00] | 64.1% | 63.3% |
| GG/NG | La Liga | 8 | n/d (n<15) | 16 | 0.322 [0.00; 1.00] | 56.2% | 62.2% |
| GG/NG | Ligue 1 | 12 | n/d (n<15) | 51 | 0.000 [0.00; 0.02] | 47.1% | 62.0% |
| GG/NG | Premier League | 77 | 0.135 [0.00; 1.00] | 147 | 0.392 [0.00; 0.71] | 59.2% | 63.0% |
| GG/NG | Serie A | 6 | n/d (n<15) | 7 | n/d (n<15) | n/d | n/d |

**Lettura (punto 5 del brief, lezione PPDA).** Il k* aggregato NON è lo stesso segnale ovunque: O/U va da k*≈0.80 (Bundesliga, La Liga) a k*≈0-0.53 (Premier, Serie A: dove l'hit rate dei picks è 46.8–56.8%, ben sotto la conf ~63–64%); GG/NG va da 1.00 (Bundesliga: nessuna sovraconfidenza) a ~0-0.39 (Ligue 1: hit 47.1% contro conf dichiarata 62% — la famiglia peggiore in assoluto). Nota: la Serie A ha solo 7 righe GG/NG ammesse in due stagioni (il selettore lì sceglie quasi solo 1X2 e O/U): per GG/NG la Serie A è di fatto fuori perimetro. Un eventuale k* unico applicato a tutte le leghe comprimerebbe nel modo sbagliato almeno due leghe su cinque.

## 7. Se si applicasse: alternative di soglia su TEST (ancora UNCOND frozen)

| Famiglia | Oggi raw≥0.60 | (a) p*≥0.60 | (b) t* a pari qualità (hit ≥ oggi) | (c) a pari volume |
|---|---:|---:|---:|---:|
| O/U 2.5 | n=152, hit 55.9% | n=55, hit 61.8% | t*=0.4, n=152 | hit 55.9% |
| GG/NG | n=202, hit 58.9% | n=80, hit 56.2% | t*=0.4, n=202 | hit 58.9% |

Nota semantica: il confronto è DENTRO le ammesse (tutte ≥0.60 per costruzione): «t*=0.40, n=tutte» significa che sulla TEST 2025/26 l'ordinamento raw≥0.60 non ha gradiente di qualità interno — tenendole tutte l'hit rate non scende. (a) mostra l'effetto della soglia onesta su p*: volume −64% su O/U (con hit che SALGONO a 61.8%: le eliminate erano rumore) e −60% su GG/NG (con hit che SCENDE a 56.2%: le eliminate erano in media buone). Le due famiglie si comportano in modo opposto.

## 8. Raccomandazione

**Non applicare lo shrinkage a produzione in questa fase.** In sintesi:

1. la *procedura* è validata (l'1X2 di controllo riproduce il ~0.91) e il fenomeno esiste: i Totali ammessi dichiarano 63–65% con hit rate reali 56–60% in ENTRAMBE le stagioni. Sull'ancora UNCOND il k* di O/U 2.5 è riproducibile (~0.62–0.64 in TRAIN, VAL e pool); quello di GG/NG è al limite (0.61→0.46) e i CI restano larghi; sull'ancora PICKED i k* sono degeneri. Inoltre il k* NON è coerente tra leghe (§6): un singolo k aggregato comprimerebbe nel modo sbagliato almeno due leghe su cinque. Come parametro di SOGLIA non è pronto;

2. **se** si volesse procedere nonostante ciò, la variante coerente con i dati è: **ricalibrare SOLO la probabilità mostrata** — ancora UNCOND, k≈0.63 stimato sul pool (e ricongelato ogni stagione), selezione invariata `raw ≥ 0.60`. È un cambio di sola presentazione: nessuna riga cambia, l'utente legge 55–60% ciò che oggi viene etichettato 63–65%. Limitandolo a O/U 2.5 il k* è il più stabile; estenderlo a GG/NG espone all'instabilità del suo k*;

3. la variante aggressiva — sostituire la soglia fissa con una soglia su p* — ha effetti OPPOSTI sulle due famiglie sulla TEST (§7a): su O/U 2.5 migliora la qualità (hit 55.9%→61.8% a volume −64%: le eliminate erano rumore), su GG/NG la peggiora (58.9%→56.2% a volume −60%: le eliminate erano in media buone). NON è una sola decisione ma due, e quella GG/NG oggi sarebbe sbagliata. Qualunque cambio di soglia è inoltre una decisione di prodotto sul volume mostrato, da fare solo con k* stabilizzati (almeno un'altra stagione di dati) e per lega, non aggregati;

4. la soglia ricalibrata equivalente «a pari qualità» (§7b) su questa TEST degenera (t* = base: tenere tutto non peggiora l'hit rate): è il segno che DENTRO le ammesse l'ordinamento raw non ha gradiente utile su quest'anno — ulteriore motivo per non fissare soglie su questo k*.

---

*Audit di sola verifica: produzione intoccata; il replay del motore gira in directory temporanee point-in-time, nessuna scrittura su database/registro; nessuna funzione di produzione modificata.*
