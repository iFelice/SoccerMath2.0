# Diagnosi: forma a 5 gare sulla testa Totali (O/U2.5, GG/NG)

_Generato da `diagnose_form_totali.py` il 04/09/2026 08:24._

## Domanda
Nella testa Totali del Poisson a Due Teste (lambda base, M=1, senza mercato),
il fattore forma a 5 gare di `app.py::get_league_engine` migliora o peggiora
la calibrazione di Over/Under 2.5 e GG/NG?

## Metodologia (walk-forward, no leakage)
- Window: **validation 2024/25 + test 2025/26**, 5 leghe; training 2022/23+2023/24.
- Alla riga `idx` si usano solo righe `< idx`; la forma usa le ultime 5 partite
  strettamente precedenti (clip [0.85, 1.15], identici a `app.py`).
- Baseline att/def da gol storici per ruolo (media squadra / media lega),
  identici al ramo gol-storici di `get_league_engine` (gli xG esistono solo per
  la stagione corrente: usarli qui sarebbe leakage).
- Lambda Totali: `lam_h = att_h*def_a*avg_h`, `lam_a = att_a*def_h*avg_a`,
  matrice Poisson 15x15, `p_over25 = 1 - P(tot<2.5)`,
  `p_gg = (1-e^-lam_h)(1-e^-lam_a)`. Metrica: **Brier score** binario.
- **40 confronti a blocchi**: finestra di ogni lega divisa in 8 blocchi
  consecutivi; per blocco si confronta il Brier delle varianti. B = 'senza forma'.

## Risultato per lega

| Lega | N | O/U2.5 Brier A→B | Δ O/U2.5 | GG/NG Brier A→B | Δ GG/NG | Blocchi B (8, entrambi i mercati) |
|---|---|---|---|---|---|---|
| Serie A | 760 | 0.2629 → 0.2534 | +0.0094 | 0.2576 → 0.2509 | +0.0067 | 7/8 (O/U 7/8, GG 8/8, medio 7/8) |
| Premier League | 760 | 0.2587 → 0.2453 | +0.0133 | 0.2573 → 0.2467 | +0.0106 | 8/8 (O/U 8/8, GG 8/8, medio 8/8) |
| La Liga | 760 | 0.2536 → 0.2481 | +0.0055 | 0.2643 → 0.2544 | +0.0099 | 7/8 (O/U 7/8, GG 8/8, medio 8/8) |
| Bundesliga | 612 | 0.2450 → 0.2327 | +0.0123 | 0.2497 → 0.2436 | +0.0062 | 6/8 (O/U 7/8, GG 6/8, medio 7/8) |
| Ligue 1 | 612 | 0.2583 → 0.2481 | +0.0102 | 0.2591 → 0.2501 | +0.0090 | 7/8 (O/U 8/8, GG 7/8, medio 8/8) |
| **Pooled** | **3504** | **0.2560 → 0.2460** | **+0.0101** | **0.2579 → 0.2493** | **+0.0086** | **35/40** (O/U 37/40, GG 37/40, medio 38/40) |

A = con forma (comportamento precedente), B = senza forma (baseline pura).

**Confronti a blocchi (40 = 8 blocchi x 5 leghe): la Variante B (senza forma) ha il Brier migliore in 35/40 blocchi su entrambi i mercati, 37/40 su O/U2.5, 37/40 su GG/NG e 38/40 sul Brier medio. Su tutti e 10 confronti per-lega (5 leghe x 2 mercati) il Brier pooled migliora SEMPRE togliendo la forma.**

## Meccanica: quanto muove la forma?

| Lega | % partite con forma ≠ 1 | Σ|fattore−1| media | Δλ_totale medio |
|---|---|---|---|
| Serie A | 100% | 0.518 | 0.285 |
| Premier League | 100% | 0.515 | 0.309 |
| La Liga | 100% | 0.515 | 0.278 |
| Bundesliga | 100% | 0.509 | 0.338 |
| Ligue 1 | 100% | 0.518 | 0.321 |

In (quasi) ogni partita almeno un fattore forma diverso da 1 scatta (clip ±15%) e
sposta i lambda totali di diverse decime di gol in media: spostamenti che non si
confermano nel risultato reale, quindi il Brier peggiora nella stragrande maggioranza
dei blocchi.

## Verdetto

**La forma a 5 gare è rumore per la testa Totali.** Togliere la forma migliora il Brier pooled in tutte e 5 le leghe, su entrambi i mercati (10/10 confronti per-lega), e nel globale O/U2.5 scende da 0.2560 a 0.2460 (+0.0101) e GG/NG da 0.2579 a 0.2493 (+0.0086). A livello di blocchi la Variante B vince 37/40 su O/U2.5 e 37/40 su GG/NG (entrambi i mercati nello stesso blocco: 35/40): il segnale è sistematico, gli scarti a blocchi sono rumorosi per il piccolo numero di partite per blocco.

**Conseguenza adottata in produzione**: `get_league_engine` conserva la forma
solo su `att`/`def` (testa 1X2, che resta forma+mercato normalizzati alla somma
base); `att0`/`def0` — e quindi la testa Totali — sono la baseline pura di lungo
periodo (xG/gol storici puliti), senza forma.
