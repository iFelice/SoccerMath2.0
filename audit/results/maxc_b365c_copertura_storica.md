# Copertura storica MaxC* vs B365C* (quote di chiusura football-data)

*Generato: 2026-09-19T13:32:05.040818+00:00 — script `audit/verify_maxc_b365c_storico.py`, sola lettura, nessuna modifica a produzione.*

Byte grezzi committati in `audit/data/fd_*.csv` (download via workflow GitHub Actions temporaneo, poi rimosso; sha256 per file nella tabella §1 e in `fd_maxc_storico_manifest.json`). Fonte: `football-data.co.uk mmz4281/{stagione}/{div}.csv`, nessuna trasformazione.

Perimetro richiesto: **2022/23, 2023/24, 2024/25, 2025/26** (train+val+test) × 5 leghe = 20 file. Aggiunti i 5 file 2026/27 SOLO per ricalcolare con la stessa metrica il baseline 2.22%/5.49% misurato in precedenza sul 2026/27. Regola quota valida: presente, numerica, > 1.0 (regola devig_1x2).

## 1. Le colonne esistono? Verifica esplicita header per header

Cerchi = esiste l'INTERA famiglia di chiusura `*CH/*CD/*CA` nell'header del file. `closing` = numero di book con blocco chiusura completo presente (contesto).

| File | Righe | Attese | MaxCH/CD/CA | B365CH/CD/CA | Altri blocchi chiusura | Div ok |
|---|---:|---:|:--:|:--:|:--:|:--:|
| `fd_I1_2223.csv` | 380 | 380 | sì | sì | 9 | sì |
| `fd_E0_2223.csv` | 380 | 380 | sì | sì | 9 | sì |
| `fd_SP1_2223.csv` | 380 | 380 | sì | sì | 9 | sì |
| `fd_D1_2223.csv` | 306 | 306 | sì | sì | 9 | sì |
| `fd_F1_2223.csv` | 380 | 380 | sì | sì | 9 | sì |
| `fd_I1_2324.csv` | 380 | 380 | sì | sì | 9 | sì |
| `fd_E0_2324.csv` | 380 | 380 | sì | sì | 9 | sì |
| `fd_SP1_2324.csv` | 380 | 380 | sì | sì | 9 | sì |
| `fd_D1_2324.csv` | 306 | 306 | sì | sì | 9 | sì |
| `fd_F1_2324.csv` | 306 | 306 | sì | sì | 9 | sì |
| `fd_I1_2425.csv` | 380 | 380 | sì | sì | 9 | sì |
| `fd_E0_2425.csv` | 380 | 380 | sì | sì | 9 | sì |
| `fd_SP1_2425.csv` | 380 | 380 | sì | sì | 9 | sì |
| `fd_D1_2425.csv` | 306 | 306 | sì | sì | 9 | sì |
| `fd_F1_2425.csv` | 306 | 306 | sì | sì | 9 | sì |
| `fd_I1_2526.csv` | 380 | 380 | sì | sì | 11 | sì |
| `fd_E0_2526.csv` | 380 | 380 | sì | sì | 11 | sì |
| `fd_SP1_2526.csv` | 380 | 380 | sì | sì | 11 | sì |
| `fd_D1_2526.csv` | 306 | 306 | sì | sì | 11 | sì |
| `fd_F1_2526.csv` | 306 | 306 | sì | sì | 11 | sì |
| `fd_I1_2627.csv` | 40 | — | sì | sì | 9 | sì |
| `fd_E0_2627.csv` | 40 | — | sì | sì | 9 | sì |
| `fd_SP1_2627.csv` | 59 | — | sì | sì | 9 | sì |
| `fd_D1_2627.csv` | 27 | — | sì | sì | 9 | sì |
| `fd_F1_2627.csv` | 36 | — | sì | sì | 9 | sì |

**Tutte e 6 le colonne (MaxCH/MaxCD/MaxCA, B365CH/B365CD/B365CA) esistono in tutti i 25 file** — nessuna eccezione per stagione o lega: non sono una novità del 2026/27. Per contesto: i blocchi di chiusura sono presenti anche per gli altri book (PSCH, AvgCH, BWCH, …); i set di book cambiano leggermente tra le stagioni, Max e B365 ci sono sempre.

Conteggi righe coerenti con il perimetro noto (380 o 306 partite; Bundesliga sempre 306, Ligue 1 380 solo nel 2022/23 prima del passaggio a 18 squadre). Nessun file troncato, nessuna riga malformed.

## 2. Copertura per colonna — % righe con quota valida (lega × stagione)

| Lega | Stagione | Righe | MaxCH | MaxCD | MaxCA | MaxC* tripletta | B365CH | B365CD | B365CA | B365C* tripletta | Entrambi |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Serie A | 2022/23 | 380 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| Premier League | 2022/23 | 380 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| La Liga | 2022/23 | 380 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| Bundesliga | 2022/23 | 306 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| Ligue 1 | 2022/23 | 380 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| Serie A | 2023/24 | 380 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| Premier League | 2023/24 | 380 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| La Liga | 2023/24 | 380 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| Bundesliga | 2023/24 | 306 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| Ligue 1 | 2023/24 | 306 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| Serie A | 2024/25 | 380 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| Premier League | 2024/25 | 380 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| La Liga | 2024/25 | 380 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| Bundesliga | 2024/25 | 306 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| Ligue 1 | 2024/25 | 306 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| Serie A | 2025/26 | 380 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| Premier League | 2025/26 | 380 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| La Liga | 2025/26 | 380 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| Bundesliga | 2025/26 | 306 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| Ligue 1 | 2025/26 | 306 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| Serie A | 2026/27 | 40 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| Premier League | 2026/27 | 40 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| La Liga | 2026/27 | 59 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| Bundesliga | 2026/27 | 27 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |
| Ligue 1 | 2026/27 | 36 | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% | 100.0% | 100.0% | **100.0%** | 100.0% |

«Tripletta» = righe con tutte e tre le quote del book valide (il minimo per calcolare l'overround o de-vigare). «Entrambi» = righe utilizzabili per un confronto diretto MaxC* vs B365C*.

## 3. Overround implicito medio (1/h+1/d+1/a−1) — MaxC* vs B365C*

| Lega | Stagione | n Max | MaxC* media | MaxC* mediana | MaxC* min–max | n B365 | B365C* media | B365C* mediana | Δ (B365−Max) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Serie A | 2022/23 | 380 | **-0.70%** | -0.55% | -24.33–1.82% | 380 | **5.63%** | 5.62% | +6.33 pp |
| Premier League | 2022/23 | 380 | **-0.91%** | -0.70% | -8.75–1.16% | 380 | **5.40%** | 5.38% | +6.31 pp |
| La Liga | 2022/23 | 380 | **-0.67%** | -0.48% | -8.65–1.49% | 380 | **5.59%** | 5.60% | +6.26 pp |
| Bundesliga | 2022/23 | 306 | **-0.94%** | -0.79% | -7.35–1.61% | 306 | **5.41%** | 5.49% | +6.35 pp |
| Ligue 1 | 2022/23 | 380 | **-0.71%** | -0.55% | -6.41–1.36% | 380 | **5.48%** | 5.56% | +6.19 pp |
| Serie A | 2023/24 | 380 | **-0.42%** | -0.23% | -6.43–1.99% | 380 | **5.49%** | 5.52% | +5.91 pp |
| Premier League | 2023/24 | 380 | **-0.93%** | -0.67% | -16.67–1.69% | 380 | **5.39%** | 5.49% | +6.32 pp |
| La Liga | 2023/24 | 380 | **-0.46%** | -0.19% | -7.80–1.95% | 380 | **5.39%** | 5.40% | +5.86 pp |
| Bundesliga | 2023/24 | 306 | **-0.67%** | -0.36% | -13.26–1.89% | 306 | **5.48%** | 5.45% | +6.15 pp |
| Ligue 1 | 2023/24 | 306 | **-0.37%** | -0.22% | -6.65–1.86% | 306 | **5.39%** | 5.47% | +5.76 pp |
| Serie A | 2024/25 | 380 | **0.26%** | 0.46% | -5.66–2.40% | 380 | **5.63%** | 5.59% | +5.36 pp |
| Premier League | 2024/25 | 380 | **0.11%** | 0.23% | -4.47–2.19% | 380 | **5.55%** | 5.57% | +5.45 pp |
| La Liga | 2024/25 | 380 | **0.18%** | 0.38% | -5.16–2.38% | 380 | **5.65%** | 5.63% | +5.47 pp |
| Bundesliga | 2024/25 | 306 | **0.03%** | 0.24% | -7.08–2.44% | 306 | **5.61%** | 5.63% | +5.58 pp |
| Ligue 1 | 2024/25 | 306 | **0.21%** | 0.37% | -10.51–2.81% | 306 | **5.65%** | 5.60% | +5.44 pp |
| Serie A | 2025/26 | 380 | **2.40%** | 2.53% | -2.51–4.55% | 380 | **5.69%** | 5.63% | +3.30 pp |
| Premier League | 2025/26 | 380 | **1.88%** | 1.96% | -2.95–3.96% | 380 | **5.59%** | 5.56% | +3.71 pp |
| La Liga | 2025/26 | 380 | **2.19%** | 2.56% | -58.13–4.63% | 380 | **5.64%** | 5.55% | +3.45 pp |
| Bundesliga | 2025/26 | 306 | **2.49%** | 2.68% | -4.71–4.59% | 306 | **5.66%** | 5.64% | +3.17 pp |
| Ligue 1 | 2025/26 | 306 | **2.29%** | 2.51% | -13.01–4.70% | 306 | **5.62%** | 5.57% | +3.33 pp |
| Serie A | 2026/27 | 40 | **2.37%** | 2.45% | 0.15–4.37% | 40 | **5.65%** | 5.69% | +3.28 pp |
| Premier League | 2026/27 | 40 | **2.05%** | 2.36% | -9.36–3.79% | 40 | **5.63%** | 5.58% | +3.58 pp |
| La Liga | 2026/27 | 59 | **2.33%** | 2.54% | -0.74–4.08% | 59 | **5.46%** | 5.44% | +3.13 pp |
| Bundesliga | 2026/27 | 27 | **2.69%** | 2.85% | 0.66–4.59% | 27 | **5.63%** | 5.56% | +2.94 pp |
| Ligue 1 | 2026/27 | 36 | **2.58%** | 2.77% | 0.83–4.47% | 36 | **5.72%** | 5.72% | +3.14 pp |

### Aggregati

| Aggregato | MaxC* micro | MaxC* macro | B365C* micro | B365C* macro | n |
|---|---:|---:|---:|---:|---:|
| 2022/23 | -0.78% | -0.79% | 5.51% | 5.50% | 1826 |
| 2023/24 | -0.57% | -0.57% | 5.43% | 5.43% | 1752 |
| 2024/25 | 0.16% | 0.16% | 5.62% | 5.62% | 1752 |
| 2025/26 | 2.24% | 2.25% | 5.64% | 5.64% | 1752 |
| 2026/27 (baseline) | 2.37% | 2.40% | 5.60% | 5.62% | 202 |
| **Walk-forward 2022/23–2025/26** | 0.25% | 0.26% | 5.55% | 5.55% | 7082 |

micro = media sulle righe in pool; macro = media non pesata delle leghe.

## 4. Conferma/smentita del 2.22%/5.49% (misurato solo sul 2026/27)

| Grandezza (2026/27, 5 leghe) | misura precedente | ricalcolo di oggi |
|---|---:|---:|
| Overround MaxC* | 2.22% | **2.37%** |
| Overround B365C* | 5.49% | **5.60%** |
| Righe con tripletta | non dichiarato | 202 |

Il ricalcolo di oggi sul 2026/27 (202 partite chiuse entro il 2026-09-17, file freschi di oggi) conferma il baseline in sostanza: MaxC* 2.37% contro 2,22%, B365C* 5.60% contro 5,49%. Lo scarto di ~0,1–0,2 pp è atteso: il file 2026/27 cresce a ogni matchday e la misura precedente era presa su un campione più piccolo. **Confermato.**

Due letture che la sola stagione live non permetteva:

1. **Il 5,49% di B365C* non è un'anomalia del live**: sulle 20 combinazioni lega×stagione del walk-forward B365C* sta sempre tra 5.39% e 5.69% (dev. std 0.10 pp): è il livello strutturale del margine Bet365 di chiusura su football-data, identico nel 2022/23 e nel 2026/27.

2. **Il 2,22% di MaxC* è il punto ALTO del suo range storico, non la norma**: l'overround MaxC* per stagione (micro) vale 2022/23 -0.78%, 2023/24 -0.57%, 2024/25 0.16%, 2025/26 2.24%; è NEGATIVO in 2022/23, 2023/24 (max per esito preso su book diversi ⇒ insieme quasi arbitraggibile) e sale progressivamente fino a ~2,2–2,5% nelle ultime due stagioni. Storicamente MaxC* «comprime» il margine molto più di B365C* (Δ ~+6 pp nel 2022/23, ~+3 pp oggi — vedi §3).

## 5. Quanto MaxC* e B365C* sono diversi (righe con entrambi)

Gap di prezzo medio `(|MaxC−B365C|)/B365C` e differenza media delle probabilità de-vigate proporzionali, in punti percentuali (pp), per esito. `%B365=max` = quante volte B365C è già il prezzo massimo di mercato per quell'esito.

| Lega | Stagione | n | gap H | gap D | gap A | Δp H | Δp D | Δp A | max |Δp| | %B365=max (H/D/A) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Serie A | 2022/23 | 380 | 7.81% | 5.91% | 9.21% | -0.05 | +0.22 | -0.18 | 13.60 | 0/1/1% |
| Premier League | 2022/23 | 380 | 7.67% | 6.64% | 10.08% | +0.09 | +0.10 | -0.19 | 4.93 | 0/1/1% |
| La Liga | 2022/23 | 380 | 7.61% | 5.64% | 9.72% | -0.03 | +0.27 | -0.23 | 5.18 | 0/1/1% |
| Bundesliga | 2022/23 | 306 | 7.44% | 6.22% | 9.09% | -0.01 | +0.17 | -0.16 | 6.29 | 0/2/1% |
| Ligue 1 | 2022/23 | 380 | 7.00% | 6.50% | 10.14% | +0.23 | +0.09 | -0.32 | 4.45 | 1/1/2% |
| Serie A | 2023/24 | 380 | 7.16% | 5.61% | 10.39% | +0.08 | +0.25 | -0.33 | 27.23 | 1/2/0% |
| Premier League | 2023/24 | 380 | 7.52% | 7.17% | 11.62% | +0.24 | -0.01 | -0.23 | 5.23 | 0/1/1% |
| La Liga | 2023/24 | 380 | 6.50% | 5.64% | 9.54% | +0.16 | +0.16 | -0.31 | 5.51 | 1/1/1% |
| Bundesliga | 2023/24 | 306 | 7.11% | 6.65% | 10.30% | +0.15 | +0.07 | -0.23 | 7.68 | 0/1/1% |
| Ligue 1 | 2023/24 | 306 | 6.16% | 5.61% | 8.61% | +0.20 | +0.13 | -0.33 | 3.64 | 1/1/1% |
| Serie A | 2024/25 | 380 | 6.38% | 5.03% | 8.18% | +0.07 | +0.17 | -0.24 | 4.07 | 1/2/1% |
| Premier League | 2024/25 | 380 | 6.25% | 5.94% | 8.89% | +0.15 | +0.01 | -0.16 | 4.60 | 1/0/1% |
| La Liga | 2024/25 | 380 | 6.61% | 5.33% | 9.04% | +0.08 | +0.17 | -0.26 | 5.65 | 0/1/1% |
| Bundesliga | 2024/25 | 306 | 6.62% | 5.84% | 10.02% | +0.19 | +0.11 | -0.30 | 4.12 | 1/0/1% |
| Ligue 1 | 2024/25 | 306 | 6.07% | 5.52% | 8.51% | +0.17 | +0.09 | -0.26 | 5.86 | 0/1/1% |
| Serie A | 2025/26 | 380 | 3.78% | 3.14% | 5.44% | +0.14 | +0.04 | -0.18 | 3.68 | 20/26/18% |
| Premier League | 2025/26 | 380 | 4.09% | 3.06% | 6.11% | +0.17 | +0.16 | -0.32 | 3.99 | 14/26/9% |
| La Liga | 2025/26 | 380 | 3.39% | 3.36% | 6.39% | +0.24 | +0.06 | -0.30 | 28.59 | 21/27/16% |
| Bundesliga | 2025/26 | 306 | 3.34% | 2.87% | 5.35% | +0.16 | +0.07 | -0.23 | 4.89 | 18/34/17% |
| Ligue 1 | 2025/26 | 306 | 3.32% | 3.49% | 5.76% | +0.26 | -0.02 | -0.23 | 8.69 | 22/24/17% |
| Serie A | 2026/27 | 40 | 2.74% | 4.20% | 5.22% | +0.44 | -0.16 | -0.28 | 2.25 | 32/20/12% |
| Premier League | 2026/27 | 40 | 2.80% | 3.74% | 5.85% | +0.39 | -0.01 | -0.38 | 7.19 | 18/15/10% |
| La Liga | 2026/27 | 59 | 3.78% | 4.11% | 5.21% | +0.14 | -0.11 | -0.03 | 2.53 | 15/27/25% |
| Bundesliga | 2026/27 | 27 | 2.55% | 3.42% | 4.39% | +0.23 | -0.10 | -0.13 | 2.28 | 22/33/15% |
| Ligue 1 | 2026/27 | 36 | 3.06% | 3.56% | 4.01% | +0.10 | -0.08 | -0.01 | 2.57 | 36/17/33% |

**Code anomale** (3 righe su 7284 congiunte, 0.04%): chiaramente refusi della fonte, non buchi di copertura — un eventuale uso di MaxC* come riferimento settlement deve gestirle per riga:
  - `fd_I1_2223.csv` 2023-01-13 Napoli–Juventus: MaxC=[3.85, 4.00, 4.05] vs B365C=[1.95, 3.40, 3.80] (Δp max 13.6 pp)
  - `fd_I1_2324.csv` 2024-04-25 Udinese–Roma: MaxC=[5.30, 1.75, 4.08] vs B365C=[3.25, 3.20, 2.30] (Δp max 27.2 pp)
  - `fd_SP1_2526.csv` 2025-08-16 Mallorca–Barcelona: MaxC=[9.50, 7.80, 5.40] vs B365C=[9.50, 5.50, 1.30] (Δp max 28.6 pp)

## 6. Verdetto

**MaxC* ha copertura sufficiente su TUTTO il perimetro walk-forward** (soglia tripletta ≥ 99.0%): colonne sempre presenti, copertura ~100% in ogni lega/stagione, nessun buco. Dal punto di vista della SOLE DISPONIBILITA' DEI DATI può essere riferimento CLV di chiusura su train+val+test.

Riserva metodologica (non di copertura): l'overround di MaxC* è vicino allo zero e a volte NEGATIVO (max per esito preso su book diversi ⇒ insieme quasi arbitraggibile). Come riferimento «prezzo meglio disponibile in mercato» è legittimo e conservativo (CLV più difficile da battere); come prezzo di settlement realistico è ottimistico (nessuno può effettivamente puntare l'intera tripletta ai massimi). B365C* ha copertura identica ma overround reale ~5,5% in ogni stagione: riferimento più «morto», e un CLV positivo contro B365C* è più facile per costruzione.

---

*Audit di sola verifica: nessun file di produzione toccato; il workflow temporaneo di download è stato rimosso prima di questo commit.*
