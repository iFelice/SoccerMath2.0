# Confronto pulito: F_season vs PT19_CAP (fonte point-in-time della testa Totali)

Walk-forward no-leakage, 5 leghe, VAL 2024/25 + TEST 2025/26, testa **Totali** (O/U2.5 e GG/NG). Lo snapshot di produzione e' ESCLUSO dal verdetto (contaminato da informazione futura entro la stessa stagione); resta come nota in fondo.

- **F_season** = medie xG della sola stagione in corso al cutoff (point-in-time, no leakage) + shrinkage PRIOR_MATCHES=6 + fallback gol (fonte isolata nel Problema B: Premier TEST O/U2.5 Brier 0.252257);
- **PT19_CAP** = finestra trailing 19 multi-stagione, tetto 400 giorni, minimo 5 partite (la fonte attualmente cablata in app.py su questo branch).

La testa 1X2 usa la stessa fonte nei due bracci: verificata bit-identica sotto.

**1X2 F_season vs PT19_CAP: max abs diff = 0.0e+00** (atteso 0.0: cambia solo att0_pure/def0_pure).

Sanity check Premier TEST 2025/26 O/U2.5 Brier: F_season 0.252257 (atteso 0.252257 dal Problema B), PT19_CAP 0.256253 (atteso ~0.2563 dall'audit).

## Risultati per lega e stagione (Brier / LogLoss, delta = PT19_CAP − F_season)

| Lega | Stagione | N | Mercato | Metrica | F_season | PT19_CAP | Δ | Vincitore |
|---|---|---|---|---|---|---|---|---|
| Serie A | 2024/25 | 380 | O/U2.5 | Brier | 0.2505 | 0.2516 | +0.0012 | ≈ rumore |
| Serie A | 2024/25 | 380 | O/U2.5 | LogLoss | 0.6944 | 0.6967 | +0.0023 | **F_season** |
| Serie A | 2024/25 | 380 | GG/NG | Brier | 0.2565 | 0.2568 | +0.0003 | ≈ rumore |
| Serie A | 2024/25 | 380 | GG/NG | LogLoss | 0.7063 | 0.7069 | +0.0006 | ≈ rumore |
| Serie A | 2025/26 | 380 | O/U2.5 | Brier | 0.2493 | 0.2504 | +0.0011 | ≈ rumore |
| Serie A | 2025/26 | 380 | O/U2.5 | LogLoss | 0.6917 | 0.6939 | +0.0023 | **F_season** |
| Serie A | 2025/26 | 380 | GG/NG | Brier | 0.2473 | 0.2484 | +0.0012 | ≈ rumore |
| Serie A | 2025/26 | 380 | GG/NG | LogLoss | 0.6876 | 0.6900 | +0.0024 | **F_season** |
| Premier League | 2024/25 | 380 | O/U2.5 | Brier | 0.2490 | 0.2450 | -0.0040 | **PT19_CAP** |
| Premier League | 2024/25 | 380 | O/U2.5 | LogLoss | 0.6913 | 0.6834 | -0.0078 | **PT19_CAP** |
| Premier League | 2024/25 | 380 | GG/NG | Brier | 0.2461 | 0.2468 | +0.0007 | ≈ rumore |
| Premier League | 2024/25 | 380 | GG/NG | LogLoss | 0.6856 | 0.6869 | +0.0014 | ≈ rumore |
| Premier League | 2025/26 | 380 | O/U2.5 | Brier | 0.2523 | 0.2563 | +0.0040 | **F_season** |
| Premier League | 2025/26 | 380 | O/U2.5 | LogLoss | 0.6982 | 0.7074 | +0.0093 | **F_season** |
| Premier League | 2025/26 | 380 | GG/NG | Brier | 0.2477 | 0.2491 | +0.0014 | ≈ rumore |
| Premier League | 2025/26 | 380 | GG/NG | LogLoss | 0.6889 | 0.6921 | +0.0032 | **F_season** |
| La Liga | 2024/25 | 380 | O/U2.5 | Brier | 0.2414 | 0.2418 | +0.0005 | ≈ rumore |
| La Liga | 2024/25 | 380 | O/U2.5 | LogLoss | 0.6755 | 0.6767 | +0.0012 | ≈ rumore |
| La Liga | 2024/25 | 380 | GG/NG | Brier | 0.2478 | 0.2502 | +0.0023 | **F_season** |
| La Liga | 2024/25 | 380 | GG/NG | LogLoss | 0.6888 | 0.6935 | +0.0048 | **F_season** |
| La Liga | 2025/26 | 380 | O/U2.5 | Brier | 0.2465 | 0.2443 | -0.0023 | **PT19_CAP** |
| La Liga | 2025/26 | 380 | O/U2.5 | LogLoss | 0.6858 | 0.6812 | -0.0046 | **PT19_CAP** |
| La Liga | 2025/26 | 380 | GG/NG | Brier | 0.2493 | 0.2466 | -0.0027 | **PT19_CAP** |
| La Liga | 2025/26 | 380 | GG/NG | LogLoss | 0.6918 | 0.6862 | -0.0055 | **PT19_CAP** |
| Bundesliga | 2024/25 | 306 | O/U2.5 | Brier | 0.2346 | 0.2350 | +0.0005 | ≈ rumore |
| Bundesliga | 2024/25 | 306 | O/U2.5 | LogLoss | 0.6624 | 0.6634 | +0.0010 | ≈ rumore |
| Bundesliga | 2024/25 | 306 | GG/NG | Brier | 0.2407 | 0.2426 | +0.0019 | ≈ rumore |
| Bundesliga | 2024/25 | 306 | GG/NG | LogLoss | 0.6743 | 0.6781 | +0.0038 | **F_season** |
| Bundesliga | 2025/26 | 306 | O/U2.5 | Brier | 0.2288 | 0.2303 | +0.0015 | ≈ rumore |
| Bundesliga | 2025/26 | 306 | O/U2.5 | LogLoss | 0.6491 | 0.6527 | +0.0036 | **F_season** |
| Bundesliga | 2025/26 | 306 | GG/NG | Brier | 0.2388 | 0.2382 | -0.0006 | ≈ rumore |
| Bundesliga | 2025/26 | 306 | GG/NG | LogLoss | 0.6706 | 0.6693 | -0.0013 | ≈ rumore |
| Ligue 1 | 2024/25 | 306 | O/U2.5 | Brier | 0.2429 | 0.2451 | +0.0022 | **F_season** |
| Ligue 1 | 2024/25 | 306 | O/U2.5 | LogLoss | 0.6787 | 0.6833 | +0.0046 | **F_season** |
| Ligue 1 | 2024/25 | 306 | GG/NG | Brier | 0.2488 | 0.2469 | -0.0019 | ≈ rumore |
| Ligue 1 | 2024/25 | 306 | GG/NG | LogLoss | 0.6907 | 0.6869 | -0.0038 | **PT19_CAP** |
| Ligue 1 | 2025/26 | 306 | O/U2.5 | Brier | 0.2452 | 0.2483 | +0.0030 | **F_season** |
| Ligue 1 | 2025/26 | 306 | O/U2.5 | LogLoss | 0.6836 | 0.6923 | +0.0086 | **F_season** |
| Ligue 1 | 2025/26 | 306 | GG/NG | Brier | 0.2506 | 0.2516 | +0.0009 | ≈ rumore |
| Ligue 1 | 2025/26 | 306 | GG/NG | LogLoss | 0.6946 | 0.6966 | +0.0020 | ≈ rumore |

## Pool per lega (VAL 2024/25 + TEST 2025/26) e aggregato

| Ambito | N | Mercato | Metrica | F_season | PT19_CAP | Δ |
|---|---|---|---|---|---|---|
| Serie A | 760 | O/U2.5 | Brier | 0.2499 | 0.2510 | +0.0011 |
| Serie A | 760 | O/U2.5 | LogLoss | 0.6931 | 0.6953 | +0.0023 |
| Serie A | 760 | GG/NG | Brier | 0.2519 | 0.2526 | +0.0007 |
| Serie A | 760 | GG/NG | LogLoss | 0.6969 | 0.6984 | +0.0015 |
| Premier League | 760 | O/U2.5 | Brier | 0.2506 | 0.2506 | -0.0000 |
| Premier League | 760 | O/U2.5 | LogLoss | 0.6947 | 0.6954 | +0.0007 |
| Premier League | 760 | GG/NG | Brier | 0.2469 | 0.2480 | +0.0010 |
| Premier League | 760 | GG/NG | LogLoss | 0.6872 | 0.6895 | +0.0023 |
| La Liga | 760 | O/U2.5 | Brier | 0.2439 | 0.2430 | -0.0009 |
| La Liga | 760 | O/U2.5 | LogLoss | 0.6807 | 0.6790 | -0.0017 |
| La Liga | 760 | GG/NG | Brier | 0.2486 | 0.2484 | -0.0002 |
| La Liga | 760 | GG/NG | LogLoss | 0.6903 | 0.6899 | -0.0004 |
| Bundesliga | 612 | O/U2.5 | Brier | 0.2317 | 0.2327 | +0.0010 |
| Bundesliga | 612 | O/U2.5 | LogLoss | 0.6558 | 0.6581 | +0.0023 |
| Bundesliga | 612 | GG/NG | Brier | 0.2398 | 0.2404 | +0.0006 |
| Bundesliga | 612 | GG/NG | LogLoss | 0.6724 | 0.6737 | +0.0013 |
| Ligue 1 | 612 | O/U2.5 | Brier | 0.2441 | 0.2467 | +0.0026 |
| Ligue 1 | 612 | O/U2.5 | LogLoss | 0.6811 | 0.6878 | +0.0066 |
| Ligue 1 | 612 | GG/NG | Brier | 0.2497 | 0.2492 | -0.0005 |
| Ligue 1 | 612 | GG/NG | LogLoss | 0.6927 | 0.6918 | -0.0009 |
| **TOTALE 5 leghe** | 3504 | O/U2.5 | Brier | 0.2446 | 0.2452 | +0.0007 |
| **TOTALE 5 leghe** | 3504 | O/U2.5 | LogLoss | 0.6821 | 0.6840 | +0.0018 |
| **TOTALE 5 leghe** | 3504 | GG/NG | Brier | 0.2476 | 0.2480 | +0.0004 |
| **TOTALE 5 leghe** | 3504 | GG/NG | LogLoss | 0.6884 | 0.6892 | +0.0008 |

## Fallback rate per lega/stagione (quota partite con almeno una squadra in fallback)

F_season: squadra senza partite nella stagione in corso al cutoff. PT19 (no cap): squadra assente/dato insufficiente nella finestra trailing senza tetto. PT19_CAP: idem con tetto 400gg. SNAP: squadra assente dallo snapshot di produzione corrente (solo copertura, per il riferimento '32,65% originale').

| Lega | Stagione | N | F_season | PT19 (no cap) | PT19_CAP | SNAP assenti |
|---|---|---|---|---|---|---|
| Serie A | 2024/25 | 380 | 2.63% | 3.95% | 3.95% | 19.47% |
| Serie A | 2025/26 | 380 | 2.63% | 1.32% | 3.68% | 28.42% |
| Premier League | 2024/25 | 380 | 2.63% | 1.32% | 3.68% | 36.84% |
| Premier League | 2025/26 | 380 | 2.63% | 1.32% | 3.68% | 28.42% |
| La Liga | 2024/25 | 380 | 2.63% | 1.32% | 3.42% | 44.74% |
| La Liga | 2025/26 | 380 | 2.63% | 2.63% | 3.42% | 28.42% |
| Bundesliga | 2024/25 | 306 | 2.94% | 3.27% | 3.27% | 49.02% |
| Bundesliga | 2025/26 | 306 | 2.94% | 1.63% | 3.27% | 31.37% |
| Ligue 1 | 2024/25 | 306 | 2.94% | 1.63% | 4.90% | 40.52% |
| Ligue 1 | 2025/26 | 306 | 2.94% | 1.63% | 4.58% | 21.57% |
| **TOTALE** | | 3504 | 2.74% | 2.00% | 3.77% | 32.65% |

**Risposta alla domanda sul 32,65% originale**: il 32,65% e' la quota aggregata di partite con almeno una squadra assente dallo snapshot di produzione (colonna SNAP assenti). F_season DA SOLO, senza alcuna componente cross-season, porta il fallback rate al 2.74% aggregato: la riduzione rispetto al 32.65% originale NON dipende dalla componente cross-season (che in F_season non esiste ed e' quella risultata dannosa): e' tutta coperta dalla disponibilita' in-season (le squadre hanno partite della stagione in corso gia' dalla prima giornata utile; il fallback resta solo alla giornata 1).

## Verdetto per lega (pool VAL+TEST, O/U2.5 Brier) e raccomandazione

- Serie A: F_season 0.2499 vs PT19_CAP 0.2510 (Δ +0.0011) -> entro il rumore.
- Premier League: F_season 0.2506 vs PT19_CAP 0.2506 (Δ -0.0000) -> entro il rumore.
- La Liga: F_season 0.2439 vs PT19_CAP 0.2430 (Δ -0.0009) -> entro il rumore.
- Bundesliga: F_season 0.2317 vs PT19_CAP 0.2327 (Δ +0.0010) -> entro il rumore.
- Ligue 1: F_season 0.2441 vs PT19_CAP 0.2467 (Δ +0.0026) -> vince **F_season**.

RACCOMANDAZIONE: esito MISTO (1 leghe F_season, 0 PT19_CAP, 4 entro il rumore): nessuna raccomandazione unica forzata; dettaglio lega per lega sopra. Direzione aggregata: su 3504 partite F_season vince l'O/U2.5 Brier complessivo di +0.0007 e non perde MAI in modo netto in nessuna lega (nessun pool di lega con delta oltre la soglia di rumore a favore di PT19_CAP).

Nota di scala: errore standard del Brier ~0.025 su 306-380 partite (~0.018 sul pool di 700 partite per lega): soglia 'rumore' usata: ±0.002.

## Nota: snapshot di produzione (ESCLUSO dal verdetto)

Il singolo snapshot committato xg_<lega>.json e' contaminato da informazione futura entro la stessa stagione (per le squadre ancora in lega usa i valori xG della stagione corrente del file, non della stagione storica): non e' una base valida per decidere la fonte point-in-time. Per riferimento, su Premier League TEST 2025/26 (dall'audit pt19_age_cap_audit.md): SNAP O/U2.5 Brier 0.2491 vs F_season 0.2523 vs PT19_CAP 0.2563; le squadre del TEST assenti dallo snapshot erano Burnley, West Ham, Wolves (fallback gol).

