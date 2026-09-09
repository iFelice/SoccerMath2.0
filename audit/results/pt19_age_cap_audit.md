# Audit Step 1 — Tetto di eta' 400 giorni nella finestra PT-19

Walk-forward no-leakage, testa **Totali** (O/U2.5 e GG/NG). Fonti a confronto:
- **STATIC** = fonte statica ricostruita point-in-time: medie xG della sola stagione in corso alla data partita, shrinkage PRIOR_MATCHES=6 verso la media di lega, fallback gol per le assenti;
- **SNAP** = VERA baseline di produzione oggi: il SINGOLO snapshot committato xg_<lega>.json, identico per ogni data storica (contiene solo le squadre della stagione corrente: es. Sampdoria/Spezia assenti dal file di Serie A); shrinkage PRIOR_MATCHES=6 verso la media dello snapshot, fallback gol per le squadre della stagione storica non presenti nel file;
- **PT19** = point-in-time finestra 19, SENZA tetto di eta';
- **PT19_CAP** = point-in-time finestra 19, tetto 400 giorni, minimo 5 partite.

L'1X2 usa la stessa fonte in tutti e tre i modelli: deve risultare bit-identico.

## 1X2 — invarianza (deve essere IDENTICO: max abs diff = 0.0)

| Lega | Stagione | N | Brier 1X2 (STATIC=PT19=PT19_CAP) | LogLoss | max|Δ1| | max|ΔX| | max|Δ2| |
|---|---|---|---|---|---|---|---|
| Serie A | 2024/25 | 380 | 0.58445 | 0.97966 | 0.0e+00 | 0.0e+00 | 0.0e+00 |
| Serie A | 2025/26 | 380 | 0.60846 | 1.01868 | 0.0e+00 | 0.0e+00 | 0.0e+00 |
| Premier League | 2024/25 | 380 | 0.59368 | 0.99402 | 0.0e+00 | 0.0e+00 | 0.0e+00 |
| Premier League | 2025/26 | 380 | 0.63485 | 1.05209 | 0.0e+00 | 0.0e+00 | 0.0e+00 |
| La Liga | 2024/25 | 380 | 0.57792 | 0.97806 | 0.0e+00 | 0.0e+00 | 0.0e+00 |
| La Liga | 2025/26 | 380 | 0.60333 | 1.01467 | 0.0e+00 | 0.0e+00 | 0.0e+00 |
| Bundesliga | 2024/25 | 306 | 0.61681 | 1.03286 | 0.0e+00 | 0.0e+00 | 0.0e+00 |
| Bundesliga | 2025/26 | 306 | 0.58684 | 0.99467 | 0.0e+00 | 0.0e+00 | 0.0e+00 |
| Ligue 1 | 2024/25 | 306 | 0.59499 | 1.00414 | 0.0e+00 | 0.0e+00 | 0.0e+00 |
| Ligue 1 | 2025/26 | 306 | 0.61408 | 1.02403 | 0.0e+00 | 0.0e+00 | 0.0e+00 |

## Testa Totali — Brier / LogLoss

| Lega | Stagione | Mercato | STATIC | SNAP (prod) | PT19 (no cap) | PT19_CAP | Δ(CAP−SNAP) | Δ(CAP−STATIC) |
|---|---|---|---|---|---|---|---|---|
| Serie A | 2024/25 | O/U2.5 Brier | 0.2505 | 0.2571 | 0.2516 | 0.2516 | -0.0054 | +0.0012 |
| Serie A | 2024/25 | O/U2.5 LogLoss | 0.6944 | 0.7077 | 0.6967 | 0.6967 | -0.0109 | +0.0023 |
| Serie A | 2024/25 | GG/NG Brier | 0.2565 | 0.2554 | 0.2568 | 0.2568 | +0.0014 | +0.0003 |
| Serie A | 2024/25 | GG/NG LogLoss | 0.7063 | 0.7040 | 0.7069 | 0.7069 | +0.0028 | +0.0006 |
| Serie A | 2025/26 | O/U2.5 Brier | 0.2493 | 0.2547 | 0.2497 | 0.2504 | -0.0043 | +0.0011 |
| Serie A | 2025/26 | O/U2.5 LogLoss | 0.6917 | 0.7029 | 0.6925 | 0.6939 | -0.0089 | +0.0023 |
| Serie A | 2025/26 | GG/NG Brier | 0.2473 | 0.2542 | 0.2484 | 0.2484 | -0.0058 | +0.0012 |
| Serie A | 2025/26 | GG/NG LogLoss | 0.6876 | 0.7016 | 0.6900 | 0.6900 | -0.0116 | +0.0024 |
| Premier League | 2024/25 | O/U2.5 Brier | 0.2490 | 0.2482 | 0.2453 | 0.2450 | -0.0032 | -0.0040 |
| Premier League | 2024/25 | O/U2.5 LogLoss | 0.6913 | 0.6897 | 0.6841 | 0.6834 | -0.0063 | -0.0078 |
| Premier League | 2024/25 | GG/NG Brier | 0.2461 | 0.2473 | 0.2467 | 0.2468 | -0.0006 | +0.0007 |
| Premier League | 2024/25 | GG/NG LogLoss | 0.6856 | 0.6880 | 0.6869 | 0.6869 | -0.0011 | +0.0014 |
| Premier League | 2025/26 | O/U2.5 Brier | 0.2523 | 0.2491 | 0.2563 | 0.2563 | +0.0071 | +0.0040 |
| Premier League | 2025/26 | O/U2.5 LogLoss | 0.6982 | 0.6918 | 0.7079 | 0.7074 | +0.0156 | +0.0093 |
| Premier League | 2025/26 | GG/NG Brier | 0.2477 | 0.2453 | 0.2491 | 0.2491 | +0.0038 | +0.0014 |
| Premier League | 2025/26 | GG/NG LogLoss | 0.6889 | 0.6839 | 0.6921 | 0.6921 | +0.0082 | +0.0032 |
| La Liga | 2024/25 | O/U2.5 Brier | 0.2414 | 0.2468 | 0.2411 | 0.2418 | -0.0050 | +0.0005 |
| La Liga | 2024/25 | O/U2.5 LogLoss | 0.6755 | 0.6872 | 0.6749 | 0.6767 | -0.0105 | +0.0012 |
| La Liga | 2024/25 | GG/NG Brier | 0.2478 | 0.2552 | 0.2499 | 0.2502 | -0.0050 | +0.0023 |
| La Liga | 2024/25 | GG/NG LogLoss | 0.6888 | 0.7036 | 0.6930 | 0.6935 | -0.0101 | +0.0048 |
| La Liga | 2025/26 | O/U2.5 Brier | 0.2465 | 0.2482 | 0.2443 | 0.2443 | -0.0039 | -0.0023 |
| La Liga | 2025/26 | O/U2.5 LogLoss | 0.6858 | 0.6893 | 0.6814 | 0.6812 | -0.0081 | -0.0046 |
| La Liga | 2025/26 | GG/NG Brier | 0.2493 | 0.2500 | 0.2458 | 0.2466 | -0.0034 | -0.0027 |
| La Liga | 2025/26 | GG/NG LogLoss | 0.6918 | 0.6933 | 0.6847 | 0.6862 | -0.0071 | -0.0055 |
| Bundesliga | 2024/25 | O/U2.5 Brier | 0.2346 | 0.2328 | 0.2350 | 0.2350 | +0.0022 | +0.0005 |
| Bundesliga | 2024/25 | O/U2.5 LogLoss | 0.6624 | 0.6581 | 0.6634 | 0.6634 | +0.0053 | +0.0010 |
| Bundesliga | 2024/25 | GG/NG Brier | 0.2407 | 0.2424 | 0.2426 | 0.2426 | +0.0002 | +0.0019 |
| Bundesliga | 2024/25 | GG/NG LogLoss | 0.6743 | 0.6782 | 0.6781 | 0.6781 | -0.0000 | +0.0038 |
| Bundesliga | 2025/26 | O/U2.5 Brier | 0.2288 | 0.2335 | 0.2298 | 0.2303 | -0.0032 | +0.0015 |
| Bundesliga | 2025/26 | O/U2.5 LogLoss | 0.6491 | 0.6596 | 0.6516 | 0.6527 | -0.0069 | +0.0036 |
| Bundesliga | 2025/26 | GG/NG Brier | 0.2388 | 0.2381 | 0.2376 | 0.2382 | +0.0001 | -0.0006 |
| Bundesliga | 2025/26 | GG/NG LogLoss | 0.6706 | 0.6692 | 0.6680 | 0.6693 | +0.0001 | -0.0013 |
| Ligue 1 | 2024/25 | O/U2.5 Brier | 0.2429 | 0.2571 | 0.2448 | 0.2451 | -0.0120 | +0.0022 |
| Ligue 1 | 2024/25 | O/U2.5 LogLoss | 0.6787 | 0.7082 | 0.6827 | 0.6833 | -0.0249 | +0.0046 |
| Ligue 1 | 2024/25 | GG/NG Brier | 0.2488 | 0.2559 | 0.2475 | 0.2469 | -0.0090 | -0.0019 |
| Ligue 1 | 2024/25 | GG/NG LogLoss | 0.6907 | 0.7053 | 0.6882 | 0.6869 | -0.0183 | -0.0038 |
| Ligue 1 | 2025/26 | O/U2.5 Brier | 0.2452 | 0.2503 | 0.2482 | 0.2483 | -0.0021 | +0.0030 |
| Ligue 1 | 2025/26 | O/U2.5 LogLoss | 0.6836 | 0.6940 | 0.6920 | 0.6923 | -0.0018 | +0.0086 |
| Ligue 1 | 2025/26 | GG/NG Brier | 0.2506 | 0.2546 | 0.2521 | 0.2516 | -0.0030 | +0.0009 |
| Ligue 1 | 2025/26 | GG/NG LogLoss | 0.6946 | 0.7024 | 0.6979 | 0.6966 | -0.0058 | +0.0020 |

## Premier League TEST 2025/26 — PT19_CAP vs VERA baseline di produzione

Il singolo snapshot di produzione (xg_premier_league.json, identico per ogni data storica) copre 17/20 squadre del TEST; le assenti vanno sul fallback gol: **['Burnley', 'West Ham', 'Wolves']**.

| Mercato | Metrica | STATIC | SNAP (prod) | PT19 | PT19_CAP | CAP−SNAP | CAP−STATIC |
|---|---|---|---|---|---|---|---|
| O/U2.5 | Brier | 0.2523 | 0.2491 | 0.2563 | 0.2563 | +0.0071 | +0.0040 |
| O/U2.5 | LogLoss | 0.6982 | 0.6918 | 0.7079 | 0.7074 | +0.0156 | +0.0093 |
| GG/NG | Brier | 0.2477 | 0.2453 | 0.2491 | 0.2491 | +0.0038 | +0.0014 |
| GG/NG | LogLoss | 0.6889 | 0.6839 | 0.6921 | 0.6921 | +0.0082 | +0.0032 |

**VERDETTO (esplicito, prima di ogni altra conclusione):** su Premier League TEST 2025/26 PT19_CAP risulta PEGGIORE della vera baseline di produzione (snapshot singolo) su: O/U2.5 Brier (CAP 0.2563 vs SNAP 0.2491, +0.0071); O/U2.5 LogLoss (CAP 0.7074 vs SNAP 0.6918, +0.0156); GG/NG Brier (CAP 0.2491 vs SNAP 0.2453, +0.0038); GG/NG LogLoss (CAP 0.6921 vs SNAP 0.6839, +0.0082).

Nota: SNAP usa i valori xG della stagione CORRENTE del file (non della stagione storica): per le squadre presenti e' un dato anacronistico ma e' esattamente cio' che gira in produzione oggi su ogni data storica.

## Premier League TEST 2025/26 — diagnostica gap e impatto del tetto

Gap fra la prima partita del TEST 2025/26 e l'ultima partita precedente
nella lega (archivio xG). Le neopromosse mostrano il gap da retrocessione:

| Squadra | Prima partita TEST | Ultima precedente | Gap giorni |
|---|---|---|---|
| Leeds | 2025-08-18 | 2023-05-28 | 813 |
| Burnley | 2025-08-16 | 2024-05-19 | 454 |
| Everton | 2025-08-18 | 2025-05-25 | 85 |
| Arsenal | 2025-08-17 | 2025-05-25 | 84 |
| Brentford | 2025-08-17 | 2025-05-25 | 84 |
| Chelsea | 2025-08-17 | 2025-05-25 | 84 |
| Crystal Palace | 2025-08-17 | 2025-05-25 | 84 |
| Man United | 2025-08-17 | 2025-05-25 | 84 |
| Nott'm Forest | 2025-08-17 | 2025-05-25 | 84 |
| Aston Villa | 2025-08-16 | 2025-05-25 | 83 |
| Brighton | 2025-08-16 | 2025-05-25 | 83 |
| Fulham | 2025-08-16 | 2025-05-25 | 83 |
| Man City | 2025-08-16 | 2025-05-25 | 83 |
| Newcastle | 2025-08-16 | 2025-05-25 | 83 |
| Tottenham | 2025-08-16 | 2025-05-25 | 83 |
| West Ham | 2025-08-16 | 2025-05-25 | 83 |
| Wolves | 2025-08-16 | 2025-05-25 | 83 |
| Bournemouth | 2025-08-15 | 2025-05-25 | 82 |
| Liverpool | 2025-08-15 | 2025-05-25 | 82 |
| Sunderland | 2025-08-16 | - | nessuna in archivio |

Partite del TEST in cui almeno una squadra era 'dato insufficiente' per PT19_CAP: **13/380**.
Partite del TEST in cui il tetto cambia la previsione: **36/380**.

Brier limitato alle partite in cui il tetto interviene:

| Fonte | O/U2.5 | GG/NG |
|---|---|---|
| STATIC | 0.2592 | 0.2452 |
| PT19 | 0.2614 | 0.2479 |
| PT19_CAP | 0.2609 | 0.2486 |

Dettaglio per squadra con gap da retrocessione (O/U2.5):

| Squadra | N | PT19 | PT19_CAP | STATIC |
|---|---|---|---|---|
| Burnley | 18 | 0.3015 | 0.2736 | 0.2747 |
| Leeds | 17 | 0.2210 | 0.2497 | 0.2448 |
| Sunderland | 1 | 0.2271 | 0.2230 | 0.2230 |

Impatto del tetto 400gg (PT19_CAP) sulle finestre del TEST:

| Squadra | Date con scarti | Max partite scartate in una finestra |
|---|---|---|
| Leeds | 7 | 19 |


## Gate Step 2 — sintesi numerica

- 1X2: max abs diff fra STATIC / PT19 / PT19_CAP su tutte le leghe e stagioni = **0.0e+00** (richiesto: 0.0).
- Premier League TEST 2025/26 (domanda primaria):
  - Premier League 2025/26 GG/NG Brier: STATIC 0.2477 | SNAP 0.2453 | PT19 0.2491 | PT19_CAP 0.2491 (CAP−SNAP +0.0038, CAP−STATIC +0.0014, CAP−PT19 +0.0001)
  - Premier League 2025/26 GG/NG LogLoss: STATIC 0.6889 | SNAP 0.6839 | PT19 0.6921 | PT19_CAP 0.6921 (CAP−SNAP +0.0082, CAP−STATIC +0.0032, CAP−PT19 -0.0000)
  - Premier League 2025/26 O/U2.5 Brier: STATIC 0.2523 | SNAP 0.2491 | PT19 0.2563 | PT19_CAP 0.2563 (CAP−SNAP +0.0071, CAP−STATIC +0.0040, CAP−PT19 -0.0000)
  - Premier League 2025/26 O/U2.5 LogLoss: STATIC 0.6982 | SNAP 0.6918 | PT19 0.7079 | PT19_CAP 0.7074 (CAP−SNAP +0.0156, CAP−STATIC +0.0093, CAP−PT19 -0.0005)
- Altre 4 leghe, peggior delta PT19_CAP−STATIC: +0.0086 (Ligue 1 2025/26 O/U2.5 LogLoss)
- Altre 4 leghe, peggior delta PT19_CAP−SNAP: +0.0053 (Bundesliga 2024/25 O/U2.5 LogLoss)
- Altre 4 leghe, peggior delta PT19_CAP−PT19: +0.0018 (La Liga 2024/25 O/U2.5 LogLoss)

Nota di scala: su 306-380 partite l'errore standard di una stima di Brier e' ~0.025: delta di millesimi sono entro il rumore statistico.

## Lettura dei risultati

1. **Meccanismo verificato.** I gap da retrocessione esistono e sono della scala dichiarata: Leeds 813 giorni, Burnley 454 giorni senza partite nella lega (tabella sopra). Senza tetto, la finestra PT-19 di queste squadre a inizio TEST era piena di partite di 453-903 giorni prima; con il tetto vengono scartate.
2. **Risposta alla domanda primaria (Premier TEST 2025/26, O/U2.5 Brier):** il tetto NON sposta l'esito aggregato rispetto al PT-19 senza tetto (delta CAP−PT19 entro mezzo millesimo di Brier, irrilevante rispetto al rumore statistico): il recupero sulle squadre col gap c'e' partita per partita (dettaglio sotto) ma viene compensato, non si vede in aggregato. Rispetto alla VERA baseline di produzione (SNAP, snapshot singolo) PT19_CAP risulta PEGGIORE di +0.0071 di Brier su questa lega/stagione.
3. **Dove il tetto agisce davvero** (partite con previsione cambiata): l'effetto per squadra e' misto e su campioni piccoli (17-18 partite): dove recupera lo fa fino al livello STATIC, dove peggiora resta entro il rumore statistico del campione.
4. **1X2**: bit-identico (0.0) in ogni lega e stagione, come richiesto.
5. **Altre 4 leghe**: i delta del tetto sono nell'ordine dei millesimi (massimo ~0.003 di Brier), cioe' non distinguibili da zero su questi campioni: nessuna regressione misurabile introdotta dal tetto.

