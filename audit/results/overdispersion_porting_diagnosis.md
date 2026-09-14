# Porting Poisson -> NB2-pooled (1X2 e O/U2.5, GG/NG resta Poisson) — audit sola lettura

*Generato: 2026-09-14T18:03:40+00:00 — script `audit/diagnose_overdispersion_porting.py`, nessuna scrittura su SoccerMath/.*

## Oggetto e protocollo

L'audit `diagnose_overdispersion_condizionale` (replica offline, snapshot xG statica) ha dimostrato che i gol reali sono piu' dispersi del Poisson condizionato al lambda per-partita: una NegBin NB2 pooled migliora 1X2 e O/U2.5 e peggiora GG/NG. Qui il test e' ripetuto sul **motore VIVO** (harness di `diagnose_motore_live_vs_replica.py`: `get_league_engine()` e `get_full_poisson_two_heads()` chiamati direttamente in replay point-in-time, CSV troncati per data, F_season con cutoff iniettato, **Elo ricalcolato dentro lo stesso contesto patchato** dai CSV troncati, come fa il Top Mix reale). Si chiede se il porting, oltre alla calibrazione, SPOSTA: (1) l'argmax del Top Mix, (2) le soglie 0.55/0.60 e il volume dei pick, (3) il gate di disaccordo Elo 0.25, (4) il ROI storico vs quote Bet365.

Walk-forward identico ai 6 audit precedenti: train 2022/23+2023/24 (prime 60 partite/lega solo in stato), validation 2024/25, test 2025/26, 5 leghe. **Alpha NB2 ristimato qui sul train live** (separatamente per le due teste: 1X2 usa i lambda normalizzati con forma+mercato, O/U usa i lambda puri F_season); GG/NG resta letteralmente Poisson in tutti gli scenari. Ogni scelta numerica e' fatta solo su train; validation e test non vengono mai toccati. L'argmax e' sempre calcolato sui mercati **Poisson/NB puro** (il blend Elo non entra nella scelta, come in produzione `fetch_and_calc_top_mix`); il blend 0.25*P+0.75*Elo agisce solo sulla confidence della riga 1X2 gia' scelta.

## Conformita' (verificata, non dichiarata)

| Controllo | Esito |
|---|---:|
| Pmf NB2 custom vs `scipy.stats.nbinom`, max scarto | 3.2e-14 |
| Replay live a oggi vs produzione non patchata (stats motore), max scarto | 0.0e+00 |
| Lambda delle due teste ricostruiti vs `get_full_poisson_two_heads`, max scarto (1X2 / Totali) | 0.0e+00 / 0.0e+00 |
| Motore VERO con `_poisson_market` sostituito dalla NB2 agli alpha dello scenario (1/X/2, u25) vs questo audit, max scarto | 0.0e+00 |
| Idem con alpha MECCANICI 0.219/0.189 (solo validazione pipeline, non usati per le probabilita'), max scarto | 0.0e+00 |
| Scarto GG fra motore patchato 'tutto NB2' (alpha meccanici) e GG lasciato Poisson — forzatura che un porting 'tutto NB2' introdurrebbe | 7.2e-02 |
| Partite con disaccordo tra `seleziona_riga_top_mix` (produzione) e scomposizione shadow (soglia AND gate) | 0 |

I check con il motore reale dimostrano che uno scenario NB2 passerebbe ESATTAMENTE dalla vera `_two_heads_from_lambdas` (stessa normalizzazione, stessi clip, stesso troncamento 15x15 non rinormalizzato): la patch inietta la pmf dentro il motore, non una replica. Lo scarto GG (riga alpha meccanici) e' atteso e voluto: un porting 'tutto NB2' muoverebbe anche GG, che invece va lasciato Poisson (la patch reale di porting dovrebbe applicare la NB2 alla sola testa 1X2 e al solo ramo O/U, non al ramo GG).

Copertura del replay (partite saltate = neopromosse senza stato al cutoff, come negli audit live/prior):

| Lega | eleggibili | valutate | saltate | giornate-motore |
|---|---:|---:|---:|---:|
| Serie A | 1460 | 1453 | 7 | 508 |
| Premier League | 1460 | 1455 | 5 | 444 |
| La Liga | 1460 | 1454 | 6 | 545 |
| Bundesliga | 1164 | 1159 | 5 | 374 |
| Ligue 1 | 1238 | 1234 | 4 | 386 |
| **totale** | **6782** | **6755** | **27** | **2257** |

Copertura quote su validation+test (1744+1746 partite): 3490 partite con almeno una quota B365 1X2/O/U, 3486 con quota BTTS (GG/NG, archivi audit come in `diagnose_quota_minima`); 0 senza alcuna quota. Convenzione ROI: stake unitario flat, profitto `(q-1)*hit - (1-hit)` (stessa di `backtest_experiment_all`).

## 1. Alpha NB2 ristimato sul TRAIN LIVE (motore reale)

MLE condizionale ai lambda per-partita emessi dal motore vero al cutoff (2 righe-squadra per partita di train, escluse le prime 60 per lega); IC 95% bootstrap 2000 per partita stratificato per lega. Confronto con i valori della replica offline (0.21904 / 0.18911).

| Testa | alpha MLE live | IC 95% | alpha replica offline | alpha robusto (lambda>=0.1) | % resample al confine 0 | righe |
|---|---:|---|---:|---:|---:|---:|
| 1X2 (lambda normalizzati forma+mercato) | 0.01197 | [0.00000; 0.03676] | 0.21904 | 0.01197 | 16.1% | 6530 |
| Totali (lambda puri F_season) | 0.00000 | [0.00000; 0.00052] | 0.18911 | 0.00000 | 97.2% | 6530 |

Alpha per lega (solo descrittivo; il porting usa quello pooled, parsimonia gia' motivata nell'audit di replica):

| Testa | Serie A | Premier League | La Liga | Bundesliga | Ligue 1 |
|---|---:|---:|---:|---:|---:|
| 1x2 | 0.0000 | 0.0349 | 0.0174 | 0.0318 | 0.0000 |
| tot | 0.0000 | 0.0024 | 0.0000 | 0.0043 | 0.0000 |

**Diagnostica di forma per split** (alpha qui e' solo diagnostica, mai usata per le probabilita'; Pearson robusta = media di (k-lambda)^2/lambda sulle righe lambda>=0.1; 1 = esattamente Poisson):

| Testa | split | alpha MLE (diagnostica) | Pearson robusta | Var reale E[(k-l)^2] | E[lambda] Poisson | Var lambda | P(0) reale | P(0) Poisson |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1X2 | train | 0.0120 | 1.116 | 1.438 | 1.382 | 0.370 | 0.258 | 0.293 |
| 1X2 | validation | 0.0000 (confine) | 1.075 | 1.411 | 1.393 | 0.354 | 0.253 | 0.289 |
| 1X2 | test | 0.0000 (confine) | 1.060 | 1.359 | 1.372 | 0.311 | 0.263 | 0.290 |
| Totali | train | 0.0000 (confine) | 0.979 | 1.363 | 1.388 | 0.178 | 0.258 | 0.270 |
| Totali | validation | 0.0000 (confine) | 0.955 | 1.354 | 1.414 | 0.176 | 0.253 | 0.263 |
| Totali | test | 0.0000 (confine) | 0.933 | 1.305 | 1.403 | 0.142 | 0.263 | 0.262 |

Confronto con la replica offline (stesso campione tipo, ma lambda della replica modello B a snapshot statica, senza il trattamento live): Pearson robusta 1.67-1.81 e Var(lambda) ~0.77 sulla testa Totali, P(0) Poisson predetta 0.31-0.35 contro 0.25-0.26 reale. Sul motore VIVO questi indicatori collassano su Poisson: Pearson 0.93-1.12, Var(lambda) 0.14-0.37 e P(0) predetta 0.26-0.29 a ridosso del reale. Lo shrinkage `_shrunk_ratio` (PRIOR_MATCHES=6) e la fonte F_season point-in-time comprimono lo spread dei lambda che nella replica generava l'overdispersion apparente: il motore di produzione, a differenza della replica, regolarizza gia' quello scarto.

## 2. Calibrazione sul motore VIVO: Brier/LogLoss (NB - Poisson)

Delta negativo = NB migliora; IC 95% bootstrap 2000 stratificato per lega, appaiato riga per riga.

### Aggregato 5 leghe

| Mercato | split | Brier Poisson | Brier NB | ΔBrier (IC) | LL Poisson | LL NB | ΔLL (IC) |
|---|---|---:|---:|---|---:|---:|---|
| 1X2 | validation | 0.5985 | 0.5983 | -0.0002 [-0.0004; -0.0001] | 1.0026 | 1.0021 | -0.0005 [-0.0007; -0.0002] |
| O/U2.5 | validation | 0.2437 | 0.2437 | +0.0000 [+0.0000; +0.0000] | 0.6806 | 0.6806 | +0.0000 [+0.0000; +0.0000] |
| GG/NG (controllo: invariato) | validation | 0.2481 | 0.2481 | +0.0000 [+0.0000; +0.0000] | 0.6893 | 0.6893 | +0.0000 [+0.0000; +0.0000] |
| 1X2 | test | 0.5979 | 0.5977 | -0.0001 [-0.0003; -0.0000] | 1.0015 | 1.0012 | -0.0002 [-0.0005; -0.0000] |
| O/U2.5 | test | 0.2450 | 0.2450 | +0.0000 [+0.0000; +0.0000] | 0.6830 | 0.6830 | +0.0000 [+0.0000; +0.0000] |
| GG/NG (controllo: invariato) | test | 0.2466 | 0.2466 | +0.0000 [+0.0000; +0.0000] | 0.6864 | 0.6864 | +0.0000 [+0.0000; +0.0000] |

Le righe O/U2.5 e GG/NG sono identiche **al bit** (delta 0.0000): l'alpha MLE della testa Totali e' esattamente al confine Poisson, quindi `markets_nb(..., alpha=0)` richiama la pmf Poisson di produzione. Sulla 1X2 l'alpha train e' minuscolo (0.012, IC che tocca lo zero): il delta e' al piu' -0.0002, cioe' ~100 volte piu' piccolo dei -0.016 della replica, e gli alpha diagnostici ricalcolati su validation/test sono 0.0 (§1): non c'e' guadagno tenibile.

### Per lega: ΔBrier (IC 95%)

| Mercato | split | Serie A | Premier League | La Liga | Bundesliga | Ligue 1 |
|---|---|---|---|---|---|---|
| 1X2 | validation | -0.0002 [-0.0004; +0.0001] | -0.0002 [-0.0005; +0.0001] | -0.0001 [-0.0004; +0.0001] | -0.0003 [-0.0007; +0.0000] | -0.0004 [-0.0007; -0.0000] |
| O/U2.5 | validation | +0.0000 [+0.0000; +0.0000] | +0.0000 [+0.0000; +0.0000] | +0.0000 [+0.0000; +0.0000] | +0.0000 [+0.0000; +0.0000] | +0.0000 [+0.0000; +0.0000] |
| 1X2 | test | -0.0002 [-0.0004; +0.0001] | -0.0002 [-0.0005; +0.0000] | -0.0001 [-0.0004; +0.0001] | -0.0000 [-0.0004; +0.0003] | -0.0001 [-0.0004; +0.0001] |
| O/U2.5 | test | +0.0000 [+0.0000; +0.0000] | +0.0000 [+0.0000; +0.0000] | +0.0000 [+0.0000; +0.0000] | +0.0000 [+0.0000; +0.0000] | +0.0000 [+0.0000; +0.0000] |

## 3. L'ARGMAX del Top Mix cambia? (7 mercati, versione pura)

Per ogni partita l'argmax e' ricalcolato con le stesse righe di produzione (`seleziona_riga_top_mix` / shadow) sui 7 mercati puri; sotto scenario NB2 le probabilita' di 1/X/2 e Over/Under 2.5 vengono dalla NB2, GG/NG restano le Poisson di produzione.

| Split | Lega | partite | argmax cambiati | % |
|---|---|---:|---:|---:|
| validation | Serie A | 377 | 3 | 0.8% |
| validation | Premier League | 379 | 1 | 0.3% |
| validation | La Liga | 379 | 0 | 0.0% |
| validation | Bundesliga | 304 | 0 | 0.0% |
| validation | Ligue 1 | 305 | 0 | 0.0% |
| validation | AGGREGATO | 1744 | 4 | 0.2% |
| test | Serie A | 379 | 2 | 0.5% |
| test | Premier League | 379 | 4 | 1.1% |
| test | La Liga | 378 | 2 | 0.5% |
| test | Bundesliga | 305 | 4 | 1.3% |
| test | Ligue 1 | 305 | 0 | 0.0% |
| test | AGGREGATO | 1746 | 12 | 0.7% |
| **val+test** | **AGGREGATO** | **3490** | **16** | **0.5%** |

Transizioni per classe di mercato (codice Poisson -> codice NB2), val+test; 1/2 = vittoria casa/trasferta, X = pareggio, O2.5/U2.5 = Over/Under, GG/NG:

| Da (Poisson) | A (NB2) | partite |
|---|---|---:|
| 1 | O2.5 | 7 |
| 2 | GG | 3 |
| 1 | U2.5 | 2 |
| 1 | GG | 2 |
| 2 | U2.5 | 1 |
| 2 | O2.5 | 1 |

Distribuzione degli argmax (val+test, tutte le partite):

| Mercato | Poisson | NB2 |
|---|---:|---:|
| 1 | 907 | 896 |
| X | 0 | 0 |
| 2 | 424 | 419 |
| O2.5 | 352 | 360 |
| U2.5 | 754 | 757 |
| GG | 1022 | 1027 |
| NG | 31 | 31 |

Casi limite (argmax cambiato, margine del mercato vincitore sul secondo piccolo in ALMENO una delle due versioni; esito reale in coda):

| Data | Lega | Partita | Ris. | argmax Poisson (p) | argmax NB2 (p) | P preso? | NB preso? |
|---|---|---|---|---|---|:--:|:--:|
| 2025-11-29 | Bundesliga | Union Berlin - Heidenheim | 1-2 | Vittoria Union Berlin (0.620) | Over 2.5 (0.620) | no | SI |
| 2025-12-02 | Premier League | Newcastle - Tottenham | 2-2 | Vittoria Newcastle (0.525) | Under 2.5 (0.524) | no | no |
| 2025-12-08 | La Liga | Osasuna - Levante | 2-0 | Vittoria Osasuna (0.533) | GG (0.532) | SI | no |
| 2026-02-18 | La Liga | Levante - Villarreal | 0-1 | Vittoria Villarreal (0.568) | GG (0.567) | SI | no |
| 2026-01-06 | Serie A | Pisa - Como | 0-3 | Vittoria Como (0.560) | Under 2.5 (0.559) | SI | no |
| 2026-03-14 | Premier League | West Ham - Man City | 1-1 | Vittoria Man City (0.630) | Over 2.5 (0.628) | no | no |
| 2025-11-24 | Serie A | Sassuolo - Pisa | 2-2 | Vittoria Sassuolo (0.528) | Under 2.5 (0.527) | no | no |
| 2025-01-26 | Serie A | Milan - Parma | 3-2 | Vittoria Milan (0.664) | Over 2.5 (0.664) | SI | SI |
| 2025-12-12 | Bundesliga | Union Berlin - Leipzig | 3-1 | Vittoria Leipzig (0.604) | GG (0.603) | no | SI |
| 2024-12-08 | Serie A | Fiorentina - Cagliari | 1-0 | Vittoria Fiorentina (0.614) | Over 2.5 (0.614) | SI | no |

## 4. Soglie 0.55/0.60, gate Elo 0.25 e volume dei pick

Lo scenario usa le SOGLIE INVARIATE di produzione (0.55 per la riga 1X2 con confidence di blend `0.25*P + 0.75*Elo`, 0.60 per le righe Over/Under/GG/NG in Poisson puro) e il veto invariato `|P - Elo| < 0.25`. Si contano solo gli spostamenti indotti dal cambio di distribuzione.

### 4.1 Superamento soglia (ignorando il veto) e ammissione finale

| split | lega | n | sopra soglia P | sopra soglia NB | la perdono | la guadagnano | ammesse P | ammesse NB | perse | guadagnate | mercato cambiato fra le ammesse |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| validation | Serie A | 377 | 163 | 162 | 1 | 0 | 160 | 160 | 0 | 0 | 3 |
| validation | Premier League | 379 | 214 | 214 | 0 | 0 | 213 | 213 | 0 | 0 | 1 |
| validation | La Liga | 379 | 196 | 195 | 1 | 0 | 193 | 192 | 1 | 0 | 0 |
| validation | Bundesliga | 304 | 210 | 210 | 0 | 0 | 209 | 209 | 0 | 0 | 0 |
| validation | Ligue 1 | 305 | 116 | 116 | 0 | 0 | 114 | 114 | 0 | 0 | 0 |
| validation | AGGREGATO | 1744 | 899 | 897 | 2 | 0 | 889 | 888 | 1 | 0 | 4 |
| test | Serie A | 379 | 142 | 142 | 0 | 0 | 137 | 137 | 0 | 0 | 0 |
| test | Premier League | 379 | 190 | 190 | 1 | 1 | 187 | 187 | 1 | 1 | 1 |
| test | La Liga | 378 | 170 | 170 | 0 | 0 | 167 | 168 | 0 | 1 | 0 |
| test | Bundesliga | 305 | 215 | 215 | 1 | 1 | 214 | 214 | 1 | 1 | 3 |
| test | Ligue 1 | 305 | 129 | 129 | 0 | 0 | 128 | 128 | 0 | 0 | 0 |
| test | AGGREGATO | 1746 | 846 | 846 | 2 | 2 | 833 | 834 | 2 | 3 | 4 |

Causa delle ammissioni perse/guadagnate (aggregato):

| split | direzione | sola soglia | solo gate | entrambi | altro (cambio di mercato verso/da riga senza Elo) |
|---|---|---:|---:|---:|---:|
| validation | perse | 1 | 0 | 0 | 0 |
| validation | guadagnate | 0 | 0 | 0 | 0 |
| test | perse | 2 | 0 | 0 | 0 |
| test | guadagnate | 1 | 1 | 1 | 0 |

### 4.2 Gate di disaccordo Elo (|P - Elo| >= 0.25)

**Cosa verrebbe sostituito.** Il gate confronta la probabilita' Poisson pura del mercato 1X2 gia' selezionato con quella Elo. Il porting tocca **solo il primo termine** (la fonte Poisson: la sua componente nella confidence di blend `0.25*P + 0.75*Elo` e la P del veto); **l'Elo non viene toccato** (stessi rating, stessi CSV troncati) e la logica/soglia 0.25 del gate resta identica. Non si patcha nulla: si misura solo quante partite cambierebbero stato.

| split | lega | argmax 1X2 P | argmax 1X2 NB | veto P | veto NB | nuovi veti | veti rimossi |
|---|---|---:|---:|---:|---:|---:|---:|
| validation | Serie A | 146 | 143 | 26 | 26 | 0 | 0 |
| validation | Premier League | 135 | 134 | 13 | 12 | 0 | 1 |
| validation | La Liga | 153 | 153 | 11 | 11 | 0 | 0 |
| validation | Bundesliga | 107 | 107 | 10 | 10 | 0 | 0 |
| validation | Ligue 1 | 129 | 129 | 17 | 16 | 0 | 1 |
| validation | AGGREGATO | 670 | 666 | 77 | 75 | 0 | 2 |
| test | Serie A | 168 | 166 | 23 | 23 | 0 | 0 |
| test | Premier League | 133 | 129 | 20 | 18 | 0 | 2 |
| test | La Liga | 143 | 141 | 18 | 17 | 0 | 1 |
| test | Bundesliga | 104 | 100 | 7 | 6 | 0 | 1 |
| test | Ligue 1 | 113 | 113 | 20 | 20 | 0 | 0 |
| test | AGGREGATO | 661 | 649 | 88 | 84 | 0 | 4 |

## 5. ROI / win-rate vs quote reali (B365 + archivio BTTS)

Due regimi: **argmax ogni partita** (contro-fattuale diagnostico: il cambio di argmax punta nella direzione giusta?) e **solo pick ammessi** dal selettore di produzione (soglia AND gate: il volume reale del Top Mix). Stake unitario flat, assenti le partite senza quota per il mercato scelto. ΔROI = NB - Poisson, IC 95% bootstrap stratificato per lega appaiato sulle partite comuni.

### 5.1 Argmax di OGNI partita

| Split | Poisson | NB2 | ΔROI NB-P (IC) |
|---|---|---|---|
| validation | n=1744, WR 60.1%, q media 1.65, ROI -3.90% [-7.77; +0.23] | n=1744, WR 60.1%, q media 1.65, ROI -3.89% [-7.43; -0.11] | +0.00% [-0.25; +0.26] (n=1744) |
| test | n=1746, WR 59.6%, q media 1.67, ROI -2.87% [-6.48; +0.81] | n=1746, WR 59.6%, q media 1.67, ROI -2.87% [-6.70; +0.89] | -0.01% [-0.50; +0.49] (n=1746) |
| val+test | n=3490, WR 59.9%, q media 1.66, ROI -3.38% [-5.95; -0.55] | n=3490, WR 59.9%, q media 1.66, ROI -3.38% [-6.11; -0.75] | -0.00% [-0.27; +0.26] (n=3490) |

Sulle **16 partite con argmax cambiato** (testa a testa sulle partite con quota per entrambi i pick):

- Poisson: n=16, WR 43.8%, q media 1.71, ROI -32.88% [-60.00; -6.31]
- NB2: n=16, WR 43.8%, q media 1.64, ROI -33.19% [-56.75; -5.81]
- ΔROI NB-P: -0.31% [-39.69; +38.75] (n=16)

Per lega (val+test):

| Lega | Poisson | NB2 |
|---|---|---|
| Serie A | n=756, WR 58.7%, q media 1.71, ROI -2.48% [-8.32; +3.88] | n=756, WR 58.5%, q media 1.71, ROI -2.89% [-8.92; +3.32] |
| Premier League | n=758, WR 58.4%, q media 1.64, ROI -6.47% [-12.23; -0.57] | n=758, WR 58.7%, q media 1.64, ROI -6.08% [-12.03; -0.11] |
| La Liga | n=757, WR 60.8%, q media 1.65, ROI -3.06% [-9.06; +2.70] | n=757, WR 60.5%, q media 1.65, ROI -3.52% [-9.51; +2.27] |
| Bundesliga | n=609, WR 62.7%, q media 1.60, ROI -2.67% [-8.84; +3.47] | n=609, WR 63.1%, q media 1.60, ROI -2.08% [-8.16; +3.83] |
| Ligue 1 | n=610, WR 59.2%, q media 1.71, ROI -1.77% [-8.17; +4.78] | n=610, WR 59.2%, q media 1.71, ROI -1.77% [-8.51; +4.90] |

### 5.2 Solo pick AMMESSI dal selettore

| Split | Poisson | NB2 | ΔROI NB-P (IC) |
|---|---|---|---|
| validation | n=889, WR 64.5%, q media 1.51, ROI -4.71% [-9.40; +0.24] | n=888, WR 64.4%, q media 1.51, ROI -4.76% [-9.83; -0.09] | +0.01% [-0.49; +0.49] (n=888) |
| test | n=833, WR 64.7%, q media 1.53, ROI -3.47% [-8.63; +1.45] | n=834, WR 64.9%, q media 1.53, ROI -3.19% [-7.85; +1.75] | +0.22% [-0.02; +0.70] (n=831) |
| val+test | n=1722, WR 64.6%, q media 1.52, ROI -4.11% [-7.69; -0.71] | n=1722, WR 64.6%, q media 1.52, ROI -4.00% [-7.59; -0.61] | +0.11% [-0.18; +0.46] (n=1719) |

Per lega (val+test):

| Lega | Poisson | NB2 |
|---|---|---|
| Serie A | n=297, WR 64.6%, q media 1.55, ROI -1.51% [-9.87; +7.21] | n=297, WR 64.3%, q media 1.55, ROI -1.97% [-10.43; +6.66] |
| Premier League | n=400, WR 60.5%, q media 1.52, ROI -10.00% [-17.31; -2.70] | n=400, WR 61.0%, q media 1.52, ROI -9.27% [-16.54; -2.22] |
| La Liga | n=360, WR 66.7%, q media 1.49, ROI -3.25% [-10.49; +4.28] | n=360, WR 66.4%, q media 1.49, ROI -3.68% [-10.98; +3.91] |
| Bundesliga | n=423, WR 66.7%, q media 1.51, ROI -1.44% [-8.18; +5.84] | n=423, WR 66.9%, q media 1.51, ROI -1.00% [-8.04; +5.59] |
| Ligue 1 | n=242, WR 64.5%, q media 1.53, ROI -3.51% [-13.26; +5.69] | n=242, WR 64.5%, q media 1.53, ROI -3.51% [-12.60; +5.84] |

## 6. Conclusione esplicita

**Stima.** Gli alpha NB2 ristimati sul train del motore VIVO sono 0.0120 (1X2, IC [0.0000; 0.0368], 16% resample al confine) e 0.0000 (Totali, 97% al confine): NON i 0.219/0.189 della replica offline. La Pearson robusta condizionale e' 0.93-1.12 (~1 = Poisson esatto; era 1.67-1.81 nella replica) e la varianza reale E[(k-lambda)^2] eguaglia o resta SOTTO E[lambda] su tutti gli split. Con alpha=0.19 della replica la varianza predetta salirebbe a ~1.8 contro ~1.36-1.43 osservato: la NB2 qui peggiorerebbe il conteggio, non lo correggerebbe.

**Calibrazione.** ΔBrier 1X2 -0.0002 (val, IC [-0.0004; -0.0001]) / -0.0001 (test, IC [-0.0003; -0.0000]); O/U2.5 +0.0000 [+0.0000; +0.0000] / +0.0000 [+0.0000; +0.0000]. GG/NG e' identico per costruzione (zero delta).

**Impatto operativo (3490 partite val+test).**

1. **Argmax**: cambia in 16/3490 partite (0.46%) — v. tabella e transizioni in §3.
2. **Soglie 0.55/0.60**: sopra-soglia perse/guadagnate 2/0 in val e 2/2 in test; ammissioni finali del selettore 889->888 (val, netto -1) e 833->834 (test, netto +1); spostamento massimo 0.6% delle righe ammesse.
3. **Gate Elo 0.25**: la sostituzione tocca SOLO il termine Poisson (e il 25% della confidence di blend 0.25*P+0.75*E); Elo, peso e regola 0.25 restano identici. Nuovi veti/rimossi: 0/2 in val, 0/4 in test (denominatori di righe 1X2 in §4.2). Non si patcha il gate: e' la descrizione di quanto cambierebbe il suo input.
4. **ROI/WR vs quote reali**: v. §5 (argmax ogni partita e soli pick ammessi), incluso il testa a testa sulle partite con argmax cambiato.

### VERDETTO

**NON fare il porting: sul motore VIVO non c'e' overdispersion condizionale residua da correggere.** L'NB2-pooled che migliorava la replica offline (alpha 0.22/0.19) qui collassa sul confine Poisson (alpha 0.012/0.000): lo shrinkage di produzione (_shrunk_ratio, PRIOR_MATCHES=6) e la fonte F_season point-in-time comprimono gia' lo spread dei lambda (Var lambda 0.14-0.37 contro ~0.77 della replica), che era la fonte dell'overdispersion apparente. NB2(alpha~0) e' algebricamente il Poisson, quindi il 'miglioramento di calibrazione gia' noto' NON si conferma sul motore vero (i delta di §2 sono identicamente nulli sui Totali e -0.0002 sulla 1X2, due ordini di grandezza sotto i -0.016 della replica e senza tenuta fuori campione), e di conseguenza:

- l'argmax cambia in 16/3490 partite (0.46%): fuoco di paglia, senza guadagno di calibrazione alle spalle;
- le soglie 0.55/0.60 **non vanno riviste**: il volume di pick si muove di 0.6% al massimo (§4), cioe' non si muove materialmente, ma non c'e' comunque alcun motivo per spostarle dato che il presupposto (code mal predette) non esiste sul vivo;
- il gate Elo non richiede interventi: il suo input Poisson resta il Poisson attuale;
- il ROI (§5) non differisce in modo significativo: il cambio di argmax non punta in nessuna direzione sistematica.

Risposta esplicita alla domanda del task: il porting non e' 'sicuro da fare perche' ininfluente', e' **inutile e non raccomandato**: aggiungerebbe un parametro (anzi due, uno per testa) e una biforcazione per mercato senza miglioramento misurabile sul motore reale. Il risultato della replica resta valido come diagnosi della replica stessa (lambda non shrinkati a snapshot statica), ma non come mandato a cambiare la distribuzione di produzione. GG/NG resta Poisson in ogni caso. Se in futuro cambiera' la pipeline dei lambda (es. disattivando/shrinkando diversamente F_season), alpha dovrà essere ristimato prima di ogni decisione.

**Lato economico.** Regime argmax-ogni-partita, val+test: Poisson -3.38% vs NB2 -3.38% (Δ -0.00% [-0.27; +0.26], n=3490). Sui soli pick ammessi: Poisson -4.11% vs NB2 -4.00% (Δ +0.11% [-0.18; +0.46], n=1719). Questi numeri ROI sono su stagioni coinvolte nelle scelte di modello (non un test intatto) e vanno letti come coerenza direzionale, non come promessa di profitto.

## Limiti dichiarati

1. **Alpha pooled unico per testa**: stessa scelta di parsimonia dell'audit di replica; gli alpha per lega restano solo descrittivi. Griglia 15x15 troncata e non rinormalizzata, come produzione.
2. **GG/NG escluso per costruzione**: l'NB2 su quella testa peggiora in modo coerente (audit overdispersion §4); lo scenario NB2 tiene il valore Poisson bit-per-bit. Un eventuale porting nel motore deve quindi biforcare la pmf per mercato, non sostituire `_poisson_market` in blocco.
3. **Il blend Elo e la 1X2 prodotta**: qui si sostituisce la sola marginale Poisson dentro la confidence di blend (0.25) e dentro il gate; non si ritara il peso del blend. L'Elo e' quello vero ricalcolato dai CSV troncati nel contesto patchato.
4. **Quote**: B365 1X2/O/U dai CSV football-data; GG/NG dalle quote BTTS degli archivi audit (stesse fonti e join di `diagnose_quota_minima`); le partite senza quota per il mercato selezionato sono escluse dal blocco ROI e contate in copertura.
5. **Validation non e' un test intatto**: le stagioni 2024/25+2025/26 hanno guidato scelte di modelli precedenti; l'etichetta e' la stessa usata da tutti gli audit di questo ciclo.
6. **Cutoff a giorno** (mezzogiorno UTC, politica previous_day) e bare-mode streamlit: identici agli audit motore-live/prior.

## Riferimenti incrociati

- `audit/results/overdispersion_condizionale_diagnosis.md`: dimostrazione dell'overdispersion e della NB2 sulla replica, alpha;
- `audit/results/motore_live_vs_replica_diagnosis.md`: harness live qui riusata;
- `audit/results/topmix_selector_replay.md` e `audit/results/topmix_shadow_gate.md`: selettore, soglie e gate;
- `audit/results/quota_minima_report.md`: fonti quote e convenzione ROI.
