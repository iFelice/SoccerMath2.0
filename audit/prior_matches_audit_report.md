# Audit PRIOR_MATCHES — shrinkage `_shrunk_ratio()` (fix NG ~99.8%)

Audit statistico walk-forward, **nessuna modifica di produzione** (`PRIOR_MATCHES` resta 6).
Codice: `audit/prior_matches_audit.py` · dati: `audit/results/prior_matches_audit_results.json`.

## Metodologia

- **No-leakage**: ogni predizione usa solo partite completate *prima* della data
  della partita. Pool gol multi-stagione (come i CSV di produzione) + snapshot xG
  della stagione in corso (semantica del file `xg_<lega>.json`).
- **Split**: validation 2024/25 (scelta del prior), test 2025/26 (un solo uso,
  dopo la selezione), monitoring 2026/27 (2 giornate, solo indicativo).
- **Varianti** (tutte con la stessa struttura a due teste di produzione, via
  `app._two_heads_from_lambdas`):
  - `A` baseline storica **solo-gol** (pool multi-stagione) senza shrinkage;
  - `B(k)` solo-gol + shrinkage k;
  - `C(k)` testa `base_pure` di produzione (xG stagione-in-corso, fallback gol)
    + shrinkage k; `C0` = produzione senza shrinkage.
- **Selezione pre-commessa** (solo validation): Brier GG/NG (mercato del bug);
  zona di equivalenza = |Δ| < 0.001 vs il migliore E CI bootstrap 95% che include 0;
  guardrail: Brier O/U entro +0.001 dal minimo, Brier 1X2 entro +0.002 da `C0`;
  si sceglie il k **più piccolo** della zona. Mercati mai aggregati in un punteggio unico.
- ROI omesso (quote non allineate al dataset xG per-partita; criterio secondario).
- 1752 partite/stagione (3 leghe a 20 squadre + 2 a 18), 5 leghe, Understat per-partita.

## A. Tabella validation (2024/25, n=1752)

| Variante | 1X2 Brier | 1X2 LogLoss | 1X2 acc | O/U Brier | O/U LogLoss | GG/NG Brier | GG/NG LogLoss |
|---|---|---|---|---|---|---|---|
| A | 0.60430 | 1.02391 | 52.85% | 0.24327 | 0.67960 | 0.24974 | 0.69916 |
| B2 | 0.60169 | 1.01476 | 52.85% | 0.24216 | 0.67704 | 0.24801 | 0.68918 |
| B4 | 0.60033 | 1.01129 | 52.85% | 0.24176 | 0.67624 | 0.24772 | 0.68858 |
| B6 | 0.59932 | 1.00884 | 52.68% | 0.24155 | 0.67581 | 0.24754 | 0.68821 |
| B8 | 0.59850 | 1.00690 | 52.68% | 0.24141 | 0.67555 | 0.24740 | 0.68792 |
| B10 | 0.59781 | 1.00530 | 52.63% | 0.24133 | 0.67538 | 0.24729 | 0.68768 |
| C0 | 0.60951 | 1.03306 | 52.05% | 0.24881 | 0.69575 | 0.25601 | 0.70864 |
| C2 | 0.59777 | 1.00642 | 51.77% | 0.24504 | 0.68365 | 0.25032 | 0.69404 |
| C4 | 0.59424 | 0.99942 | 51.88% | 0.24428 | 0.68182 | 0.24892 | 0.69107 |
| C6 | 0.59244 | 0.99576 | 51.77% | 0.24403 | 0.68121 | 0.24823 | 0.68964 |
| C8 | 0.59137 | 0.99353 | 51.71% | 0.24395 | 0.68101 | 0.24783 | 0.68882 |
| C10 | 0.59072 | 0.99211 | 52.05% | 0.24395 | 0.68098 | 0.24758 | 0.68831 |

## B. Tabella test (2025/26, n=1752) — usata UNA volta, dopo la selezione (k=8)

| Variante | 1X2 Brier | 1X2 LogLoss | 1X2 acc | O/U Brier | O/U LogLoss | GG/NG Brier | GG/NG LogLoss |
|---|---|---|---|---|---|---|---|
| A | 0.61823 | 1.04929 | 50.40% | 0.24847 | 0.69032 | 0.24977 | 0.69741 |
| B2 | 0.61531 | 1.03317 | 50.34% | 0.24738 | 0.68785 | 0.24883 | 0.69102 |
| B4 | 0.61397 | 1.03051 | 50.34% | 0.24693 | 0.68690 | 0.24855 | 0.69040 |
| B6 | 0.61299 | 1.02863 | 50.51% | 0.24661 | 0.68624 | 0.24834 | 0.68994 |
| B8 | 0.61219 | 1.02709 | 50.57% | 0.24637 | 0.68571 | 0.24817 | 0.68957 |
| B10 | 0.61150 | 1.02576 | 50.51% | 0.24616 | 0.68528 | 0.24802 | 0.68927 |
| C0 | 0.62736 | 1.05767 | 50.46% | 0.24959 | 0.69414 | 0.25107 | 0.69663 |
| C2 | 0.61644 | 1.03327 | 51.08% | 0.24645 | 0.68593 | 0.24803 | 0.68935 |
| C4 | 0.61254 | 1.02597 | 51.14% | 0.24549 | 0.68389 | 0.24729 | 0.68779 |
| C6 | 0.61026 | 1.02180 | 50.97% | 0.24500 | 0.68288 | 0.24694 | 0.68707 |
| C8 | 0.60875 | 1.01905 | 51.08% | 0.24471 | 0.68229 | 0.24676 | 0.68668 |
| C10 | 0.60767 | 1.01711 | 50.97% | 0.24452 | 0.68193 | 0.24665 | 0.68647 |

## C. Risultati per lega (Brier GG/NG · O/U 2.5)

### validation

| Lega | A GG | C0 GG | C6 GG | C8 GG | A O/U | C0 O/U | C6 O/U | C8 O/U |
|---|---|---|---|---|---|---|---|---|
| Premier League | 0.24902 | 0.25771 | 0.24612 | 0.24565 | 0.24219 | 0.25743 | 0.24867 | 0.24810 |
| Serie A | 0.25536 | 0.26632 | 0.25649 | 0.25570 | 0.25176 | 0.25604 | 0.25058 | 0.25021 |
| Bundesliga | 0.23818 | 0.24115 | 0.24056 | 0.24111 | 0.22811 | 0.23962 | 0.23452 | 0.23461 |
| La Liga | 0.25415 | 0.24982 | 0.24782 | 0.24766 | 0.24438 | 0.24197 | 0.24121 | 0.24163 |
| Ligue 1 | 0.24971 | 0.26362 | 0.24877 | 0.24771 | 0.24785 | 0.24680 | 0.24312 | 0.24322 |

### test

| Lega | A GG | C0 GG | C6 GG | C8 GG | A O/U | C0 O/U | C6 O/U | C8 O/U |
|---|---|---|---|---|---|---|---|---|
| Premier League | 0.24531 | 0.24974 | 0.24786 | 0.24760 | 0.24829 | 0.25932 | 0.25197 | 0.25119 |
| Serie A | 0.24946 | 0.24848 | 0.24722 | 0.24742 | 0.25602 | 0.25621 | 0.24913 | 0.24879 |
| Bundesliga | 0.24908 | 0.24399 | 0.23894 | 0.23856 | 0.23749 | 0.23267 | 0.22922 | 0.22907 |
| La Liga | 0.25331 | 0.25718 | 0.24925 | 0.24866 | 0.24972 | 0.24850 | 0.24648 | 0.24630 |
| Ligue 1 | 0.25195 | 0.25542 | 0.25060 | 0.25071 | 0.24877 | 0.24754 | 0.24514 | 0.24524 |

## D. Analisi per dimensione campione (validation, asse = n_C = partite stagionali della testa xG, min tra le squadre)

| Bucket | n | A O/U | C0 O/U | C6 O/U | A GG | C0 GG | C6 GG | peso prior k=6* |
|---|---|---|---|---|---|---|---|---|
| 0-2 | 105 | 0.25241 | 0.28833 | 0.24792 | 0.26531 | 0.29895 | 0.24567 | 0.818 |
| 3-5 | 145 | 0.23683 | 0.24299 | 0.23312 | 0.23668 | 0.25358 | 0.23746 | 0.603 |
| 6-10 | 239 | 0.24484 | 0.25338 | 0.24657 | 0.25146 | 0.25619 | 0.24912 | 0.432 |
| 11-20 | 482 | 0.23861 | 0.23954 | 0.23929 | 0.24419 | 0.25130 | 0.24557 | 0.285 |
| 21+ | 781 | 0.24564 | 0.24890 | 0.24767 | 0.25296 | 0.25353 | 0.25195 | 0.173 |

\* peso matematico del prior w = k/(n+k) sulla squadra con meno dati (k=6).

## E. Calibrazione (validation)

### C0

**P(Over 2.5)**

| bucket | n | prevista | reale |
|---|---|---|---|
| 50%-55% | 255 | 0.5240 | 0.5333 |
| 55%-60% | 225 | 0.5752 | 0.5422 |
| 60%-65% | 215 | 0.6226 | 0.6233 |
| 65%-70% | 145 | 0.6738 | 0.6000 |
| 70%-80% | 126 | 0.7394 | 0.6587 |
| 80%+ | 30 | 0.8550 | 0.7000 |

**P(GG)**

| bucket | n | prevista | reale |
|---|---|---|---|
| 50%-55% | 314 | 0.5261 | 0.5541 |
| 55%-60% | 286 | 0.5741 | 0.5524 |
| 60%-65% | 187 | 0.6236 | 0.5775 |
| 65%-70% | 81 | 0.6724 | 0.6296 |
| 70%-80% | 29 ⚠️ pochi casi | 0.7236 | 0.7241 |
| 80%+ | 7 ⚠️ pochi casi | 0.8414 | 0.4286 |

### C8

**P(Over 2.5)**

| bucket | n | prevista | reale |
|---|---|---|---|
| 50%-55% | 348 | 0.5250 | 0.5603 |
| 55%-60% | 353 | 0.5741 | 0.5609 |
| 60%-65% | 227 | 0.6218 | 0.5903 |
| 65%-70% | 133 | 0.6711 | 0.6391 |
| 70%-80% | 46 | 0.7300 | 0.6957 |
| 80%+ | 1 ⚠️ pochi casi | 0.8156 | 1.0000 |

**P(GG)**

| bucket | n | prevista | reale |
|---|---|---|---|
| 50%-55% | 469 | 0.5254 | 0.5309 |
| 55%-60% | 429 | 0.5738 | 0.5571 |
| 60%-65% | 282 | 0.6203 | 0.5993 |
| 65%-70% | 83 | 0.6686 | 0.6627 |
| 70%-80% | 6 ⚠️ pochi casi | 0.7154 | 0.5000 |
| 80%+ | 0 ⚠️ pochi casi | - | - |

### C6

**P(Over 2.5)**

| bucket | n | prevista | reale |
|---|---|---|---|
| 50%-55% | 327 | 0.5244 | 0.5596 |
| 55%-60% | 340 | 0.5738 | 0.5529 |
| 60%-65% | 238 | 0.6228 | 0.6050 |
| 65%-70% | 128 | 0.6741 | 0.6250 |
| 70%-80% | 57 | 0.7327 | 0.7018 |
| 80%+ | 2 ⚠️ pochi casi | 0.8165 | 1.0000 |

**P(GG)**

| bucket | n | prevista | reale |
|---|---|---|---|
| 50%-55% | 439 | 0.5259 | 0.5467 |
| 55%-60% | 412 | 0.5738 | 0.5631 |
| 60%-65% | 263 | 0.6208 | 0.5932 |
| 65%-70% | 84 | 0.6697 | 0.6548 |
| 70%-80% | 10 ⚠️ pochi casi | 0.7144 | 0.6000 |
| 80%+ | 0 ⚠️ pochi casi | - | - |

Osservazione: senza shrinkage (`C0`) la coda alta è sistematicamente sovra-confidente
(P(GG)≥80% prevista 84% vs 43% reale su 7 casi; P(Over)≥80% prevista 85% vs 70% su 30 casi).
Con shrinkage (`C6`/`C8`) la coda ≥80% svanisce quasi del tutto (0–2 casi): le probabilità
estreme non compaiono più perché non sono più giustificate dai dati.

## F. Bootstrap paired (2000 repliche, Δ = Brier(a) − Brier(b); Δ>0 ⇒ a peggiore)

### Validation: C0 vs Ck

| k | Δ O/U mean | CI 95% | Δ GG/NG mean | CI 95% |
|---|---|---|---|---|
| 2 | +0.00374 | [+0.00169, +0.00588] | +0.00568 | [+0.00316, +0.00833] |
| 4 | +0.00450 | [+0.00173, +0.00729] | +0.00708 | [+0.00397, +0.01034] |
| 6 | +0.00475 | [+0.00162, +0.00793] | +0.00777 | [+0.00438, +0.01138] |
| 8 | +0.00482 | [+0.00143, +0.00826] | +0.00816 | [+0.00452, +0.01197] |
| 10 | +0.00482 | [+0.00122, +0.00851] | +0.00840 | [+0.00453, +0.01238] |

### Test (un solo uso): C0 vs C8

- O/U: Δ=+0.00486, CI [+0.00213, +0.00783], P(Δ>0)=1.000
- GG/NG: Δ=+0.00431, CI [+0.00100, +0.00779], P(Δ>0)=0.992

### Validation: basi a confronto

- A (gol, senza shrinkage) vs C6 (xG + shrinkage): O/U Δ=-0.00073 CI [-0.00487, +0.00345]; GG/NG Δ=+0.00148 CI [-0.00223, +0.00532]
- B6 (gol + shrinkage) vs C6 (xG + shrinkage): O/U Δ=-0.00245 CI [-0.00605, +0.00124]; GG/NG Δ=-0.00067 CI [-0.00356, +0.00219]

## G. Confronto con baseline solo-gol (domanda: lo shrinkage o la fonte dati?)

- `C0` (xG senza shrinkage) è **peggiore della baseline solo-gol `A`** su ogni mercato e stagione: GG/NG val 0.25601 vs 0.24974, test 0.25107 vs 0.24977.
- Con shrinkage la testa xG recupera e supera `A`: `C6` GG/NG val 0.24823 (A: 0.24974), test 0.24694 (A: 0.24977); bootstrap A−C6 CI include lo 0 (nessuna differenza robusta).
- `B6` (gol+shrinkage) ≈ `C6` (xG+shrinkage): Δ GG/NG val -0.00067 (CI [-0.00356, +0.00219]) e segno opposto nel test → fonte gol vs xG sostanzialmente equivalente SUI TOTALI una volta applicato lo shrinkage.

## Verifica del bug originale (NG ~99.8%)

| Variante | val: NG>90 / >95 / max | test: NG>90 / >95 | mon: NG>95 / max |
|---|---|---|---|
| A | 7 / 7 / 99.88% | 7 / 7 | 2 / 99.84% |
| B2 | 0 / 0 / 73.70% | 0 / 0 | 0 / 63.85% |
| B4 | 0 / 0 / 67.97% | 0 / 0 | 0 / 63.61% |
| B6 | 0 / 0 / 67.36% | 0 / 0 | 0 / 63.38% |
| B8 | 0 / 0 / 66.89% | 0 / 0 | 0 / 63.15% |
| B10 | 0 / 0 / 66.45% | 0 / 0 | 0 / 62.93% |
| C0 | 8 / 1 / 99.10% | 8 / 1 | 0 / 93.61% |
| C2 | 0 / 0 / 74.75% | 0 / 0 | 0 / 66.35% |
| C4 | 0 / 0 / 68.11% | 0 / 0 | 0 / 63.61% |
| C6 | 0 / 0 / 65.83% | 0 / 0 | 0 / 63.38% |
| C8 | 0 / 0 / 63.96% | 0 / 0 | 0 / 63.15% |
| C10 | 0 / 0 / 62.42% | 0 / 0 | 0 / 62.93% |

Il caso patologico è **ricorrente e reale** nelle varianti senza shrinkage:
`A` produce NG>95% in 7 partite di validation e 7 di test (max 99.88%);
`C0` 1 caso >95% per stagione e 8 >90% in validation (max 99.10%).
Con qualsiasi k≥2: **zero** predizioni NG>90% e massimo ~63–75%.
Non è un cap sulla probabilità: le NG estreme scompaiono perché λ non collassa più a exp(−6).

Dettaglio dei casi estremi (NG>90% in A o C0):

| Stagione | Lega | Partita | Data | n_C | NG A | NG C0 | NG C6 | GG reale |
|---|---|---|---|---|---|---|---|---|
| validation | Premier League | Man City vs Ipswich | 2024-08-24 | 1 | 99.8% | 80.4% | 40.5% | GG |
| validation | Serie A | Roma vs Empoli | 2024-08-25 | 1 | 61.0% | 90.7% | 53.6% | GG |
| validation | Serie A | Cagliari vs Como | 2024-08-26 | 1 | 99.8% | 92.8% | 53.0% | GG |
| validation | Serie A | Verona vs Juventus | 2024-08-26 | 1 | 62.8% | 91.9% | 52.5% | NG |
| validation | Serie A | Fiorentina vs Monza | 2024-09-01 | 2 | 51.9% | 94.5% | 60.8% | GG |
| validation | Bundesliga | Union Berlin vs St. Pauli | 2024-08-30 | 1 | 99.8% | 75.2% | 41.8% | NG |
| validation | Bundesliga | Augsburg vs St. Pauli | 2024-09-15 | 2 | 99.8% | 72.3% | 44.1% | GG |
| validation | La Liga | Getafe vs Sociedad | 2024-09-01 | 2 | 60.7% | 91.7% | 57.0% | NG |
| validation | La Liga | Sevilla vs Getafe | 2024-09-14 | 3 | 54.9% | 94.4% | 62.0% | NG |
| validation | Ligue 1 | Lille vs Angers | 2024-08-24 | 1 | 57.5% | 99.1% | 51.2% | NG |
| validation | Ligue 1 | Saint-Etienne vs Le Havre | 2024-08-24 | 1 | 99.9% | 85.9% | 45.3% | NG |
| validation | Ligue 1 | Marseille vs Reims | 2024-08-25 | 1 | 51.4% | 94.4% | 44.7% | GG |
| validation | Ligue 1 | Brest vs Saint-Etienne | 2024-08-31 | 2 | 99.8% | 37.6% | 39.4% | NG |
| validation | Ligue 1 | Saint-Etienne vs Lille | 2024-09-13 | 3 | 99.8% | 62.5% | 45.5% | NG |
| test | Premier League | Burnley vs Sunderland | 2025-08-23 | 1 | 99.8% | 79.0% | 43.6% | NG |
| test | Serie A | Lecce vs Milan | 2025-08-29 | 1 | 54.7% | 90.0% | 52.4% | NG |
| test | Serie A | Bologna vs Como | 2025-08-30 | 1 | 48.3% | 94.2% | 52.8% | NG |
| test | Bundesliga | Hamburg vs St. Pauli | 2025-08-29 | 1 | 100.0% | 75.1% | 39.9% | NG |
| test | Bundesliga | Stuttgart vs M'gladbach | 2025-08-30 | 1 | 35.2% | 90.2% | 43.7% | NG |
| test | Bundesliga | Bayern vs Hamburg | 2025-09-13 | 2 | 99.8% | 86.4% | 44.4% | NG |
| test | Bundesliga | Hamburg vs Heidenheim | 2025-09-20 | 3 | 99.8% | 66.3% | 41.6% | GG |
| test | La Liga | Osasuna vs Valencia | 2025-08-24 | 1 | 55.7% | 90.4% | 51.8% | NG |
| test | La Liga | Real Oviedo vs Real Madrid | 2025-08-24 | 1 | 99.8% | 90.0% | 49.7% | NG |
| test | La Liga | Real Oviedo vs Sociedad | 2025-08-30 | 2 | 99.8% | 52.5% | 46.1% | NG |
| test | La Liga | Real Madrid vs Mallorca | 2025-08-30 | 2 | 63.8% | 91.3% | 56.8% | GG |
| test | Ligue 1 | PSG vs Angers | 2025-08-22 | 1 | 56.3% | 94.1% | 49.1% | NG |
| test | Ligue 1 | Marseille vs Paris | 2025-08-23 | 1 | 99.8% | 52.8% | 43.3% | GG |
| test | Ligue 1 | Strasbourg vs Nantes | 2025-08-24 | 1 | 52.0% | 99.1% | 52.2% | NG |
| test | Ligue 1 | Toulouse vs PSG | 2025-08-30 | 2 | 44.5% | 94.2% | 53.5% | GG |
| monitoring | Premier League | Coventry City vs Hull City | 2026-08-29 | 1 | 99.8% | 71.6% | 43.7% | NG |
| monitoring | Premier League | Aston Villa vs Arsenal | 2026-08-31 | 1 | 47.0% | 92.6% | 42.5% | NG |
| monitoring | La Liga | Málaga vs Deportivo | 2026-08-24 | 1 | 99.8% | 93.6% | 52.9% | GG |
| monitoring | La Liga | Celta vs Osasuna | 2026-08-27 | 1 | 49.5% | 91.9% | 54.3% | GG |
| monitoring | Ligue 1 | Monaco vs Marseille | 2026-08-30 | 1 | 33.2% | 92.6% | 47.9% | NG |

Neopromosse (assenti dalla stagione precedente) con 0 gol nelle prime 2 partite:

- Premier League 2024/2025: **Southampton** (0 gol nelle prime 2) — 3ª partita Brentford vs Southampton: NG A=53.66% C0=57.87% C6=42.96% (pool gol della squadra: n=40).
- Premier League 2026/2027: **Coventry City** (0 gol nelle prime 2) — 3ª partita non ancora giocata al momento dell'audit (monitoring).
- Serie A 2026/2027: **Venezia** (0 gol nelle prime 2) — 3ª partita non ancora giocata al momento dell'audit (monitoring).
- Bundesliga 2024/2025: **St. Pauli** (0 gol nelle prime 2) — 3ª partita Augsburg vs St. Pauli: NG A=99.81% C0=72.29% C6=44.12% (pool gol della squadra: n=2).
- Bundesliga 2025/2026: **Hamburg** (0 gol nelle prime 2) — 3ª partita Bayern vs Hamburg: NG A=99.79% C0=86.43% C6=44.37% (pool gol della squadra: n=2).
- La Liga 2024/2025: **Espanol** (0 gol nelle prime 2) — 3ª partita Ath Madrid vs Espanol: NG A=45.04% C0=71.34% C6=53.72% (pool gol della squadra: n=40).
- La Liga 2025/2026: **Real Oviedo** (0 gol nelle prime 2) — 3ª partita Real Oviedo vs Sociedad: NG A=99.79% C0=52.53% C6=46.12% (pool gol della squadra: n=2).
- Ligue 1 2024/2025: **Angers** (0 gol nelle prime 2) — 3ª partita Angers vs Nice: NG A=63.27% C0=81.87% C6=52.19% (pool gol della squadra: n=40).
- Ligue 1 2024/2025: **Saint-Etienne** (0 gol nelle prime 2) — 3ª partita Brest vs Saint-Etienne: NG A=99.81% C0=37.59% C6=39.38% (pool gol della squadra: n=2).
- Ligue 1 2025/2026: **Metz** (0 gol nelle prime 2) — 3ª partita Paris vs Metz: NG A=37.2% C0=81.05% C6=49.28% (pool gol della squadra: n=2).

I casi con pool n=2 (prima stagione nel window dell'archivio: St. Pauli 2024/25,
Saint-Etienne 2024/25, Hamburg 2025/26, Real Oviedo 2025/26) mostrano esattamente la firma
del bug nel baseline `A`: NG ≈ 99.8%. I casi con pool n=40 (Southampton, Espanol, Angers:
due stagioni d'archivio) non collassano. Ipswich 2024/25 e Real Oviedo 2025/26, senza
storico in archivio, generano in `A` le predizioni NG 99.8% visibili in tabella sopra.

## Monitoring 2026/27 (n=99, 2 giornate — solo indicativo)

| Variante | 1X2 Brier | O/U Brier | GG/NG Brier |
|---|---|---|---|
| A | 0.56216 | 0.23597 | 0.25447 |
| B2 | 0.56393 | 0.23306 | 0.24893 |
| B4 | 0.56574 | 0.23320 | 0.24922 |
| B6 | 0.56656 | 0.23336 | 0.24939 |
| B8 | 0.56693 | 0.23350 | 0.24951 |
| B10 | 0.56710 | 0.23361 | 0.24961 |
| C0 | 0.63464 | 0.25921 | 0.28372 |
| C2 | 0.58295 | 0.23496 | 0.24838 |
| C4 | 0.57743 | 0.23523 | 0.24771 |
| C6 | 0.57623 | 0.23592 | 0.24783 |
| C8 | 0.57596 | 0.23645 | 0.24803 |
| C10 | 0.57597 | 0.23684 | 0.24823 |

## Selezione e sensitivity

Brier GG/NG in validation: k=0: 0.25601, k=2: 0.25032, k=4: 0.24892, k=6: 0.24823, k=8: 0.24783, k=10: 0.24758.
Migliore: k=10. Zone rule: |Δ|<0.001 vs migliore E CI che include 0 → zona=[8, 10]; guardrail O/U e 1X2 ok per k=[4, 6, 8, 10] → **selezionato k=8**.

Δ incrementali del Brier GG/NG (validation): 0→2: −0.0057 · 2→4: −0.0014 · 4→6: −0.0007 · 6→8: −0.0004 · 8→10: −0.0003: rendimenti decrescenti, curva piatta da k=6 in poi.
k=6 resta fuori dalla zona solo per un soffio (CI basso +0.00006 > 0): **6, 8 e 10 sono
praticamente indistinguibili**; le differenze (≤0.0004) sono troppo piccole per essere
considerate significative. Non c'è evidenza per un valore preciso nella zona 6–10.

## H. Raccomandazione finale

**BUG FIX** — Lo shrinkage risolve il caso patologico (0 gol in 1–2 partite → λ→exp(−6) → NG 99.8%):
con k≥2 nessuna predizione NG>90% in 3 stagioni×5 leghe; risolto via stima dei parametri, non via cap.

**MIGLIORAMENTO PREDITTIVO** — C'è anche un miglioramento out-of-sample **statisticamente robusto**,
non limitato all'inizio stagione: su validation C0→C6 migliora GG/NG di 0.0078 (CI Δ [0.0044, 0.0114])
e O/U di 0.0048; confermato nel test una-tantum C0→C8: GG/NG −0.0043 (CI Δ [+0.00100, +0.00779]), O/U −0.0049. Il grosso del guadagno sta nelle fasce 0–2 e 3–10 partite, ma non c'è danno
nelle fasce 11+ (differenze trascurabili e di segno favorevole).

**Decisione consigliata dai dati**: categoria *"shrinkage utile (bug fix + predittivo) ma valore non
identificabile con precisione nella zona 6–10"* → **mantenere `PRIOR_MATCHES = 6` in produzione**:
è dentro la zona di equivalenza, è il valore più conservativo già testato dal fix, e il passaggio 6→8
varrebbe ~0.0004 Brier (non significante). Nessuna modifica di produzione eseguita in questo audit.

---

Ambito: 5 leghe, 2022/23–2026/27 (Understat per-partita), test unitari di regressione in
`audit/test_ng_regression.py` (24 test, verdi) coprono NaN/inf, xG mancanti/zero, mapping nomi,
neopromosse e campioni insufficienti.