# Triage deriva Elo e seeding delle neopromosse

Generato sul commit `3419422de148d2d1a78c9abeb5bdd82ebbfd133b`. Data di esecuzione UTC: 2026-10-06T22:33:13.534124+00:00

> **Audit di sola lettura. Nessuna modifica a `SoccerMath/`; nessuna variante e' stata applicata alla produzione.** S0 e' la produzione corrente; S1-S4 vivono esclusivamente in questo script di audit.

## 0. Evidenze e prerequisiti

Le verifiche del punto 0 sono state eseguite prima di scrivere i nuovi file audit. Il comando di allineamento non era necessario: HEAD era gia' uguale a `origin/main`; il clone iniziale era shallow ed e' stato reso completo con `git fetch --unshallow origin`.

| Esito | Comando | Evidenza/output |
|---|---|---|
| OK | `test -f audit/results/ev_and_baserate_fix.md` | EXISTS |
| OK | `git rev-parse HEAD; git rev-parse origin/main` | entrambi `8e3f135d269c45ae2e573b6635ebb21f92390929` |
| OK | `git diff --name-only origin/main HEAD` (all'inizio) | (vuoto) |
| OK | `git rev-parse --is-shallow-repository` dopo `git fetch --unshallow origin` | false |
| OK | `.venv/bin/pip install -r SoccerMath/requirements.txt -r requirements-audit.txt pytest` | exit 0; installazione completata |
| OK | `.venv/bin/pip check` | No broken requirements found. |
| OK | `.venv/bin/pytest -q audit/test_elo_walker_parity.py audit/test_elo_drift_triage.py SoccerMath/test_elo_probs_from_ratings.py` | 20 passed in 11.83s |
| OK | `.venv/bin/python audit/elo_weight_retune.py` | 2026-10-06 22:32:32.220   [1/6] costruzione campione   Serie A          elo= 1570 poisson= 1570 join= 1570   Premier League   elo= 1570 poisson= 1570 join= 1570   La Liga          elo= 1591 poisson= 1591 join= 1591   Bundesliga       elo= 1260 poisson= 1260 join= 1260   Ligue 1          elo= 1343 poisson= 1343 join= 1343   totale righe: 7334 [2/6] artefatto per-partita   parquet=True righe=7334 [3/6] mismatch vecchia replica [4/6] griglia + bootstrap a blocchi   train (post burn-in) n=1752   validation 2024/25 n=1752   test 2025/26 n=1752   burn-in 2022/23 (solo descrittivo) n=1826 [5/6] dettaglio per lega [6/6] report scritto /home/user/SoccerMath2.0/audit/results/elo_weight_retune.md |
| OK | `git status --porcelain -- SoccerMath/` | (vuoto) |
| OK | `git diff --name-only origin/main...HEAD` finale | audit/elo_drift_triage.py audit/results/elo_drift_triage.md audit/test_elo_drift_triage.py |

### Ambiente e CI esistente

```text
numpy 2.4.6
pandas 3.0.6
scipy 1.17.1
pyarrow 25.0.1
statsmodels 0.15.0
```

La CI gia' versionata contiene workflow separati di Audit e Replay; la verifica seguente riporta gli step sostanziali richiesti senza aggiungere file fuori da `audit/`:
| Esito | Workflow/controllo | Step sostanziali/evidenza |
|---|---|---|
| OK | .github/workflows/topmix_audit.yml | push + pull_request; installazione requirements + pytest audit; esecuzione audit; controllo diff su SoccerMath/audit/results; artifact |
| OK | .github/workflows/replay_legacy_topmix.yml | push + pull_request; installazione requirements; test no-leakage; replay dry-run/write esplicito; controllo nessuna modifica; artifact |
| OK | Vincolo diff del mandato | il diff finale contiene solo audit/; nessuna modifica a SoccerMath/ |

### Limiti verificabili del dato

| league | n_2026_27 | min_date | max_date |
|---|---|---|---|
| Serie A | 50 | 2026-08-22 | 2026-09-20 |
| Premier League | 50 | 2026-08-21 | 2026-09-20 |
| La Liga | 71 | 2026-08-15 | 2026-10-21 |
| Bundesliga | 36 | 2026-08-28 | 2026-09-20 |
| Ligue 1 | 45 | 2026-08-21 | 2026-09-20 |

`2026/27` e' quindi disponibile nei CSV locali per tutte le 5 leghe ed e' usata solo per descrizione/ingressi, non nella metrica primaria. La data massima locale di La Liga (`2026-10-21`) e' successiva alla data di esecuzione dichiarata (`2026-10-06` UTC): l'origine di questa riga futura non e' verificabile con i soli file del repository; non e' stata corretta o esclusa.

La classificazione `mai vista`/`di ritorno` e' operativa: deriva dalla partecipazione osservata nei CSV e non verifica lo status ufficiale di promossa/retrocessa con una fonte esterna. Le giornate ufficiali non sono presenti nei CSV; "prime 5/10" significa prime 5/10 partite della squadra nell'ordine temporale del walker, con i pari-data lasciati nell'ordine di produzione documentato da `elo_walker_core.py`.

## 1. Tabella per-partita e controllo di parita' S0

Output rigenerato da `audit/elo_weight_retune.py`: `audit/output/elo_walker_per_match.csv.gz` (ignorato da git). Il controllo S0 seguente confronta il rerun segmentato audit-only con il `build_walker_table` esistente, inclusi rating pre/post e probabilita' Elo:

| Controllo | Output |
|---|---|
| leagues | 5 |
| rows | 7334 |
| max_abs_pre | 0.0000 |
| max_abs_post | 0.0000 |
| max_abs_prob | 0.0000 |
| all_equal | true |
| per_league | [{"league": "Serie A", "rows": 1570, "max_abs_pre": 0.0, "max_abs_post": 0.0, "max_abs_prob": 0.0}, {"league": "Premier League", "rows": 1570, "max_abs_pre": 0.0, "max_abs_post": 0.0, "max_abs_prob": 0.0}, {"league": "La Liga", "rows": 1591, "max_abs_pre": 0.0, "max_abs_post": 0.0, "max_abs_prob": 0.0}, {"league": "Bundesliga", "rows": 1260, "max_abs_pre": 0.0, "max_abs_post": 0.0, "max_abs_prob": 0.0}, {"league": "Ligue 1", "rows": 1343, "max_abs_pre": 0.0, "max_abs_post": 0.0, "max_abs_prob": 0.0}] |

| join |
|---|
| Serie A: walker=1570 baseline=1570 join=1570 date=2022-08-13..2026-09-20 |
| Premier League: walker=1570 baseline=1570 join=1570 date=2022-08-05..2026-09-20 |
| La Liga: walker=1591 baseline=1591 join=1591 date=2022-08-12..2026-10-21 |
| Bundesliga: walker=1260 baseline=1260 join=1260 date=2022-08-05..2026-09-20 |
| Ligue 1: walker=1343 baseline=1343 join=1343 date=2022-08-05..2026-09-20 |

S0 e' chiamata di controllo; la sua coincidenza e' un prerequisito per leggere S1-S4 come sole variazioni dell'ingresso. Il dict `_CarryRatings` intercetta esclusivamente la prima assegnazione `1500` del metodo di produzione fra due segmenti; l'update Elo, il moltiplicatore di scarto, l'xG snapshot e `elo_probs_from_ratings` restano quelli importati.

## 2. Deriva per lega e stagione

Squadre attive = tutte le squadre con almeno una partita nella stagione. Start = rating prima della prima partita di ciascuna squadra; end = rating dopo l'ultima. Deviazione standard = popolazione (`ddof=0`). La colonna cumulata confronta la media/deviazione di fine stagione con lo start 2022/23 della stessa lega.

| league | season | n_active | start_mean | start_sd_population | end_mean | end_sd_population | season_delta_mean_end_minus_start | season_delta_sd_end_minus_start | cumulative_mean_vs_2022_23_start | cumulative_sd_vs_2022_23_start |
|---|---|---|---|---|---|---|---|---|---|---|
| Serie A | 2022/23 | 20 | 1500.0000 | 0.0000 | 1500.0000 | 94.5836 | 0.0000 | 94.5836 | 0.0000 | 94.5836 |
| Serie A | 2023/24 | 20 | 1521.7836 | 71.7303 | 1521.7836 | 116.2602 | 0.0000 | 44.5298 | 21.7836 | 116.2602 |
| Serie A | 2024/25 | 20 | 1543.2013 | 93.1652 | 1543.2013 | 127.3642 | 0.0000 | 34.1991 | 43.2013 | 127.3642 |
| Serie A | 2025/26 | 20 | 1549.2351 | 120.8737 | 1549.2351 | 127.1664 | 0.0000 | 6.2927 | 49.2351 | 127.1664 |
| Serie A | 2026/27 | 20 | 1553.4270 | 122.1540 | 1553.4270 | 128.7078 | 0.0000 | 6.5538 | 53.4270 | 128.7078 |
| Premier League | 2022/23 | 20 | 1500.0000 | 0.0000 | 1500.0000 | 103.0425 | 0.0000 | 103.0425 | 0.0000 | 103.0425 |
| Premier League | 2023/24 | 20 | 1520.4704 | 84.9287 | 1520.4704 | 129.9040 | 0.0000 | 44.9753 | 20.4704 | 129.9040 |
| Premier League | 2024/25 | 20 | 1532.8906 | 116.4051 | 1532.8906 | 134.5263 | 0.0000 | 18.1212 | 32.8906 | 134.5263 |
| Premier League | 2025/26 | 20 | 1550.2344 | 108.2030 | 1550.2344 | 106.4612 | 0.0000 | -1.7419 | 50.2344 | 106.4612 |
| Premier League | 2026/27 | 20 | 1558.2827 | 96.9259 | 1558.2827 | 99.8340 | 0.0000 | 2.9081 | 58.2827 | 99.8340 |
| La Liga | 2022/23 | 20 | 1500.0000 | 0.0000 | 1500.0000 | 77.2295 | 0.0000 | 77.2295 | 0.0000 | 77.2295 |
| La Liga | 2023/24 | 20 | 1514.1888 | 66.2752 | 1514.1888 | 116.2975 | 0.0000 | 50.0223 | 14.1888 | 116.2975 |
| La Liga | 2024/25 | 20 | 1525.9894 | 104.7557 | 1525.9894 | 128.3554 | 0.0000 | 23.5997 | 25.9894 | 128.3554 |
| La Liga | 2025/26 | 20 | 1541.5160 | 109.5819 | 1541.5160 | 106.8128 | 0.0000 | -2.7691 | 41.5160 | 106.8128 |
| La Liga | 2026/27 | 20 | 1549.0342 | 100.7706 | 1549.0342 | 108.1341 | 0.0000 | 7.3635 | 49.0342 | 108.1341 |
| Bundesliga | 2022/23 | 18 | 1500.0000 | 0.0000 | 1500.0000 | 80.9262 | 0.0000 | 80.9262 | 0.0000 | 80.9262 |
| Bundesliga | 2023/24 | 18 | 1511.2302 | 72.5004 | 1511.2302 | 120.1030 | 0.0000 | 47.6026 | 11.2302 | 120.1030 |
| Bundesliga | 2024/25 | 18 | 1528.1641 | 104.7260 | 1528.1641 | 113.8368 | 0.0000 | 9.1108 | 28.1641 | 113.8368 |
| Bundesliga | 2025/26 | 18 | 1535.2277 | 107.7090 | 1535.2277 | 131.1789 | 0.0000 | 23.4699 | 35.2277 | 131.1789 |
| Bundesliga | 2026/27 | 18 | 1549.2707 | 118.9760 | 1549.2707 | 121.9494 | 0.0000 | 2.9734 | 49.2707 | 121.9494 |
| Ligue 1 | 2022/23 | 20 | 1500.0000 | 0.0000 | 1500.0000 | 103.0886 | 0.0000 | 103.0886 | 0.0000 | 103.0886 |
| Ligue 1 | 2023/24 | 18 | 1535.7372 | 65.9528 | 1535.7372 | 99.9042 | 0.0000 | 33.9514 | 35.7372 | 99.9042 |
| Ligue 1 | 2024/25 | 18 | 1535.4997 | 105.5010 | 1535.4997 | 122.6815 | 0.0000 | 17.1806 | 35.4997 | 122.6815 |
| Ligue 1 | 2025/26 | 18 | 1545.4076 | 110.1439 | 1545.4076 | 108.4225 | 0.0000 | -1.7214 | 45.4076 | 108.4225 |
| Ligue 1 | 2026/27 | 18 | 1551.1810 | 102.7244 | 1551.1810 | 104.9840 | 0.0000 | 2.2596 | 51.1810 | 104.9840 |

Output pesante corrispondente: `audit/output/elo_drift_triage_drift.csv`. Non viene inferita una causa dalla sola deriva: sono esposti i valori necessari per decidere un audit completo.

## 3. Ingressi in lega

Media attiva prima del primo match = media dei rating S0 delle squadre gia' apparse in una riga precedente nell'ordine del walker. `s0_seed` e' 1500 per mai viste e il rating stantio per ritorni; `s0_diff` e' s0_seed − media attiva. Per S1-S4 `*_active_mean`, `*_seed`, `*_diff` sono quelli effettivamente usati nella relativa rilanciata; quindi S2 e S3 riportano anche la media attiva di quella rilanciata, non un valore ricalcolato a posteriori.

| entry_id | league | season | team | type | last_seen_season | anni_assenza | n_active_before | active_mean_s0 | stale_s0 | s0_seed | s0_diff | S1_active_mean | S1_seed | S1_diff | S2_active_mean | S2_seed | S2_diff | S3_active_mean | S3_seed | S3_diff | S4_active_mean | S4_seed | S4_diff |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Serie A\|2023/24\|Frosinone | Serie A | 2023/24 | Frosinone | mai vista | - | - | 20 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1450.0000 | -50.0000 | 1500.0000 | 1400.0000 | -100.0000 | 1500.0000 | 1400.0000 | -100.0000 |
| Serie A\|2023/24\|Genoa | Serie A | 2023/24 | Genoa | mai vista | - | - | 21 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1497.6190 | 1447.6190 | -50.0000 | 1495.2381 | 1395.2381 | -100.0000 | 1495.2381 | 1395.2381 | -100.0000 |
| Serie A\|2023/24\|Cagliari | Serie A | 2023/24 | Cagliari | mai vista | - | - | 22 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1495.3463 | 1445.3463 | -50.0000 | 1490.6926 | 1390.6926 | -100.0000 | 1490.6926 | 1390.6926 | -100.0000 |
| Serie A\|2024/25\|Parma | Serie A | 2024/25 | Parma | mai vista | - | - | 23 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1493.1724 | 1443.1724 | -50.0000 | 1486.3448 | 1386.3448 | -100.0000 | 1486.3448 | 1386.3448 | -100.0000 |
| Serie A\|2024/25\|Venezia | Serie A | 2024/25 | Venezia | mai vista | - | - | 24 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1491.0891 | 1441.0891 | -50.0000 | 1482.1781 | 1382.1781 | -100.0000 | 1482.1781 | 1382.1781 | -100.0000 |
| Serie A\|2024/25\|Como | Serie A | 2024/25 | Como | mai vista | - | - | 25 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1489.0891 | 1439.0891 | -50.0000 | 1478.1781 | 1378.1781 | -100.0000 | 1478.1781 | 1378.1781 | -100.0000 |
| Serie A\|2025/26\|Sassuolo | Serie A | 2025/26 | Sassuolo | di ritorno | 2023/24 | 1.0000 | 26 | 1500.0000 | 1355.7697 | 1355.7697 | -144.2303 | 1500.0000 | 1500.0000 | 0.0000 | 1487.1660 | 1437.1660 | -50.0000 | 1474.3320 | 1374.3320 | -100.0000 | 1474.3320 | 1358.6558 | -115.6762 |
| Serie A\|2025/26\|Cremonese | Serie A | 2025/26 | Cremonese | di ritorno | 2022/23 | 2.0000 | 26 | 1500.0000 | 1382.2660 | 1382.2660 | -117.7340 | 1505.5473 | 1500.0000 | -5.5473 | 1490.5410 | 1440.5410 | -50.0000 | 1475.5379 | 1375.5379 | -100.0000 | 1474.9349 | 1376.7677 | -98.1672 |
| Serie A\|2025/26\|Pisa | Serie A | 2025/26 | Pisa | mai vista | - | - | 26 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1510.0755 | 1500.0000 | -10.0755 | 1492.7823 | 1442.7823 | -50.0000 | 1475.2791 | 1375.2791 | -100.0000 | 1474.7235 | 1374.7235 | -100.0000 |
| Serie A\|2026/27\|Monza | Serie A | 2026/27 | Monza | di ritorno | 2024/25 | 1.0000 | 27 | 1500.0000 | 1306.3930 | 1306.3930 | -193.6070 | 1509.7024 | 1500.0000 | -9.7024 | 1490.9305 | 1440.9305 | -50.0000 | 1471.5754 | 1371.5754 | -100.0000 | 1471.0197 | 1325.4310 | -145.5888 |
| Serie A\|2026/27\|Frosinone | Serie A | 2026/27 | Frosinone | di ritorno | 2023/24 | 2.0000 | 27 | 1500.0000 | 1420.1117 | 1420.1117 | -79.8883 | 1516.8730 | 1500.0000 | -16.8730 | 1496.4040 | 1446.4040 | -50.0000 | 1474.9729 | 1374.9729 | -100.0000 | 1472.7082 | 1375.5893 | -97.1189 |
| Serie A\|2026/27\|Venezia | Serie A | 2026/27 | Venezia | di ritorno | 2024/25 | 1.0000 | 27 | 1500.0000 | 1419.3116 | 1419.3116 | -80.6884 | 1519.8318 | 1500.0000 | -19.8318 | 1498.0329 | 1448.0329 | -50.0000 | 1474.6300 | 1374.6300 | -100.0000 | 1472.3881 | 1368.2978 | -104.0903 |
| Premier League\|2023/24\|Burnley | Premier League | 2023/24 | Burnley | mai vista | - | - | 20 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1450.0000 | -50.0000 | 1500.0000 | 1400.0000 | -100.0000 | 1500.0000 | 1400.0000 | -100.0000 |
| Premier League\|2023/24\|Luton | Premier League | 2023/24 | Luton | mai vista | - | - | 21 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1497.6190 | 1447.6190 | -50.0000 | 1495.2381 | 1395.2381 | -100.0000 | 1495.2381 | 1395.2381 | -100.0000 |
| Premier League\|2023/24\|Sheffield United | Premier League | 2023/24 | Sheffield United | mai vista | - | - | 22 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1495.3463 | 1445.3463 | -50.0000 | 1490.6926 | 1390.6926 | -100.0000 | 1490.6926 | 1390.6926 | -100.0000 |
| Premier League\|2024/25\|Ipswich | Premier League | 2024/25 | Ipswich | mai vista | - | - | 23 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1493.1724 | 1443.1724 | -50.0000 | 1486.3448 | 1386.3448 | -100.0000 | 1486.3448 | 1386.3448 | -100.0000 |
| Premier League\|2024/25\|Southampton | Premier League | 2024/25 | Southampton | di ritorno | 2022/23 | 1.0000 | 24 | 1500.0000 | 1328.5359 | 1328.5359 | -171.4641 | 1500.0000 | 1500.0000 | 0.0000 | 1491.0891 | 1441.0891 | -50.0000 | 1482.1781 | 1382.1781 | -100.0000 | 1482.1781 | 1355.3570 | -126.8211 |
| Premier League\|2024/25\|Leicester | Premier League | 2024/25 | Leicester | di ritorno | 2022/23 | 1.0000 | 24 | 1500.0000 | 1412.7184 | 1412.7184 | -87.2816 | 1507.1443 | 1500.0000 | -7.1443 | 1495.7788 | 1445.7788 | -50.0000 | 1484.4132 | 1384.4132 | -100.0000 | 1483.2957 | 1398.0070 | -85.2887 |
| Premier League\|2025/26\|Burnley | Premier League | 2025/26 | Burnley | di ritorno | 2023/24 | 1.0000 | 24 | 1500.0000 | 1363.6237 | 1363.6237 | -136.3763 | 1510.7811 | 1500.0000 | -10.7811 | 1497.1563 | 1447.1563 | -50.0000 | 1483.2339 | 1383.2339 | -100.0000 | 1482.6827 | 1355.2380 | -127.4447 |
| Premier League\|2025/26\|Sunderland | Premier League | 2025/26 | Sunderland | mai vista | - | - | 24 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1516.4634 | 1500.0000 | -16.4634 | 1501.3666 | 1451.3666 | -50.0000 | 1485.5439 | 1385.5439 | -100.0000 | 1483.8263 | 1383.8263 | -100.0000 |
| Premier League\|2025/26\|Leeds | Premier League | 2025/26 | Leeds | di ritorno | 2022/23 | 2.0000 | 25 | 1500.0000 | 1349.3383 | 1349.3383 | -150.6617 | 1515.8049 | 1500.0000 | -15.8049 | 1499.3666 | 1449.3666 | -50.0000 | 1481.5439 | 1381.5439 | -100.0000 | 1479.8263 | 1372.2043 | -107.6220 |
| Premier League\|2026/27\|Coventry City | Premier League | 2026/27 | Coventry City | mai vista | - | - | 25 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1521.8313 | 1500.0000 | -21.8313 | 1503.3677 | 1453.3677 | -50.0000 | 1482.8321 | 1382.8321 | -100.0000 | 1480.7409 | 1380.7409 | -100.0000 |
| Premier League\|2026/27\|Hull City | Premier League | 2026/27 | Hull City | mai vista | - | - | 26 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1520.9917 | 1500.0000 | -20.9917 | 1501.4447 | 1451.4447 | -50.0000 | 1478.9860 | 1378.9860 | -100.0000 | 1476.8947 | 1376.8947 | -100.0000 |
| Premier League\|2026/27\|Ipswich | Premier League | 2026/27 | Ipswich | di ritorno | 2024/25 | 1.0000 | 27 | 1500.0000 | 1328.1797 | 1328.1797 | -171.8203 | 1520.2142 | 1500.0000 | -20.2142 | 1499.5928 | 1449.5928 | -50.0000 | 1475.2823 | 1375.2823 | -100.0000 | 1473.1910 | 1330.6754 | -142.5156 |
| La Liga\|2023/24\|Las Palmas | La Liga | 2023/24 | Las Palmas | mai vista | - | - | 20 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1450.0000 | -50.0000 | 1500.0000 | 1400.0000 | -100.0000 | 1500.0000 | 1400.0000 | -100.0000 |
| La Liga\|2023/24\|Alaves | La Liga | 2023/24 | Alaves | mai vista | - | - | 21 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1497.6190 | 1447.6190 | -50.0000 | 1495.2381 | 1395.2381 | -100.0000 | 1495.2381 | 1395.2381 | -100.0000 |
| La Liga\|2023/24\|Granada | La Liga | 2023/24 | Granada | mai vista | - | - | 22 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1495.3463 | 1445.3463 | -50.0000 | 1490.6926 | 1390.6926 | -100.0000 | 1490.6926 | 1390.6926 | -100.0000 |
| La Liga\|2024/25\|Leganes | La Liga | 2024/25 | Leganes | mai vista | - | - | 23 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1493.1724 | 1443.1724 | -50.0000 | 1486.3448 | 1386.3448 | -100.0000 | 1486.3448 | 1386.3448 | -100.0000 |
| La Liga\|2024/25\|Espanol | La Liga | 2024/25 | Espanol | di ritorno | 2022/23 | 1.0000 | 24 | 1500.0000 | 1419.6013 | 1419.6013 | -80.3987 | 1500.0000 | 1500.0000 | 0.0000 | 1491.0891 | 1441.0891 | -50.0000 | 1482.1781 | 1382.1781 | -100.0000 | 1482.1781 | 1400.8897 | -81.2884 |
| La Liga\|2024/25\|Valladolid | La Liga | 2024/25 | Valladolid | di ritorno | 2022/23 | 1.0000 | 24 | 1500.0000 | 1409.8915 | 1409.8915 | -90.1085 | 1503.3499 | 1500.0000 | -3.3499 | 1491.9844 | 1441.9844 | -50.0000 | 1480.6188 | 1380.6188 | -100.0000 | 1481.3985 | 1395.6450 | -85.7535 |
| La Liga\|2025/26\|Oviedo | La Liga | 2025/26 | Oviedo | mai vista | - | - | 24 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1507.1045 | 1500.0000 | -7.1045 | 1493.3216 | 1443.3216 | -50.0000 | 1479.3992 | 1379.3992 | -100.0000 | 1480.8049 | 1380.8049 | -100.0000 |
| La Liga\|2025/26\|Levante | La Liga | 2025/26 | Levante | mai vista | - | - | 25 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1506.8203 | 1500.0000 | -6.8203 | 1491.3216 | 1441.3216 | -50.0000 | 1475.3992 | 1375.3992 | -100.0000 | 1476.8049 | 1376.8049 | -100.0000 |
| La Liga\|2025/26\|Elche | La Liga | 2025/26 | Elche | di ritorno | 2022/23 | 2.0000 | 26 | 1500.0000 | 1386.7311 | 1386.7311 | -113.2689 | 1506.5580 | 1500.0000 | -6.5580 | 1489.3985 | 1439.3985 | -50.0000 | 1471.5530 | 1371.5530 | -100.0000 | 1472.9587 | 1376.4018 | -96.5569 |
| La Liga\|2026/27\|Santander | La Liga | 2026/27 | Santander | mai vista | - | - | 26 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1510.9145 | 1500.0000 | -10.9145 | 1491.4242 | 1441.4242 | -50.0000 | 1470.9692 | 1370.9692 | -100.0000 | 1472.5615 | 1372.5615 | -100.0000 |
| La Liga\|2026/27\|Deportivo | La Liga | 2026/27 | Deportivo | mai vista | - | - | 27 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1510.5102 | 1500.0000 | -10.5102 | 1489.5723 | 1439.5723 | -50.0000 | 1467.2655 | 1367.2655 | -100.0000 | 1468.8578 | 1368.8578 | -100.0000 |
| La Liga\|2026/27\|Málaga | La Liga | 2026/27 | Málaga | mai vista | - | - | 28 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1510.1349 | 1500.0000 | -10.1349 | 1487.7866 | 1437.7866 | -50.0000 | 1463.6941 | 1363.6941 | -100.0000 | 1465.2863 | 1365.2863 | -100.0000 |
| Bundesliga\|2023/24\|Heidenheim | Bundesliga | 2023/24 | Heidenheim | mai vista | - | - | 18 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1450.0000 | -50.0000 | 1500.0000 | 1400.0000 | -100.0000 | 1500.0000 | 1400.0000 | -100.0000 |
| Bundesliga\|2023/24\|Darmstadt | Bundesliga | 2023/24 | Darmstadt | mai vista | - | - | 19 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1497.3684 | 1447.3684 | -50.0000 | 1494.7368 | 1394.7368 | -100.0000 | 1494.7368 | 1394.7368 | -100.0000 |
| Bundesliga\|2024/25\|Holstein Kiel | Bundesliga | 2024/25 | Holstein Kiel | mai vista | - | - | 20 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1494.8684 | 1444.8684 | -50.0000 | 1489.7368 | 1389.7368 | -100.0000 | 1489.7368 | 1389.7368 | -100.0000 |
| Bundesliga\|2024/25\|St Pauli | Bundesliga | 2024/25 | St Pauli | mai vista | - | - | 21 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1492.4875 | 1442.4875 | -50.0000 | 1484.9749 | 1384.9749 | -100.0000 | 1484.9749 | 1384.9749 | -100.0000 |
| Bundesliga\|2025/26\|Koln | Bundesliga | 2025/26 | Koln | di ritorno | 2023/24 | 1.0000 | 22 | 1500.0000 | 1390.9953 | 1390.9953 | -109.0047 | 1500.0000 | 1500.0000 | 0.0000 | 1490.2147 | 1440.2147 | -50.0000 | 1480.4295 | 1380.4295 | -100.0000 | 1480.4295 | 1381.1599 | -99.2696 |
| Bundesliga\|2025/26\|Hamburg | Bundesliga | 2025/26 | Hamburg | mai vista | - | - | 22 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1504.9548 | 1500.0000 | -4.9548 | 1492.6582 | 1442.6582 | -50.0000 | 1480.3631 | 1380.3631 | -100.0000 | 1480.3963 | 1380.3963 | -100.0000 |
| Bundesliga\|2026/27\|Elversberg | Bundesliga | 2026/27 | Elversberg | mai vista | - | - | 23 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1504.7393 | 1500.0000 | -4.7393 | 1490.4843 | 1440.4843 | -50.0000 | 1476.0153 | 1376.0153 | -100.0000 | 1476.0485 | 1376.0485 | -100.0000 |
| Bundesliga\|2026/27\|SC Paderborn | Bundesliga | 2026/27 | SC Paderborn | mai vista | - | - | 24 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1504.5419 | 1500.0000 | -4.5419 | 1488.4009 | 1438.4009 | -50.0000 | 1471.8486 | 1371.8486 | -100.0000 | 1471.8818 | 1371.8818 | -100.0000 |
| Bundesliga\|2026/27\|Schalke 04 | Bundesliga | 2026/27 | Schalke 04 | di ritorno | 2022/23 | 3.0000 | 25 | 1500.0000 | 1415.7795 | 1415.7795 | -84.2205 | 1504.3602 | 1500.0000 | -4.3602 | 1486.4009 | 1436.4009 | -50.0000 | 1467.8486 | 1367.8486 | -100.0000 | 1467.8818 | 1373.8690 | -94.0128 |
| Ligue 1\|2023/24\|Metz | Ligue 1 | 2023/24 | Metz | mai vista | - | - | 20 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1450.0000 | -50.0000 | 1500.0000 | 1400.0000 | -100.0000 | 1500.0000 | 1400.0000 | -100.0000 |
| Ligue 1\|2023/24\|Le Havre | Ligue 1 | 2023/24 | Le Havre | mai vista | - | - | 21 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1497.6190 | 1447.6190 | -50.0000 | 1495.2381 | 1395.2381 | -100.0000 | 1495.2381 | 1395.2381 | -100.0000 |
| Ligue 1\|2024/25\|St Etienne | Ligue 1 | 2024/25 | St Etienne | mai vista | - | - | 22 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1495.3463 | 1445.3463 | -50.0000 | 1490.6926 | 1390.6926 | -100.0000 | 1490.6926 | 1390.6926 | -100.0000 |
| Ligue 1\|2024/25\|Angers | Ligue 1 | 2024/25 | Angers | di ritorno | 2022/23 | 1.0000 | 23 | 1500.0000 | 1301.6685 | 1301.6685 | -198.3315 | 1500.0000 | 1500.0000 | 0.0000 | 1493.1724 | 1443.1724 | -50.0000 | 1486.3448 | 1386.3448 | -100.0000 | 1486.3448 | 1344.0066 | -142.3382 |
| Ligue 1\|2024/25\|Auxerre | Ligue 1 | 2024/25 | Auxerre | di ritorno | 2022/23 | 1.0000 | 23 | 1500.0000 | 1414.0547 | 1414.0547 | -85.9453 | 1508.6231 | 1500.0000 | -8.6231 | 1499.3248 | 1449.3248 | -50.0000 | 1490.0264 | 1390.0264 | -100.0000 | 1488.1856 | 1401.1201 | -87.0655 |
| Ligue 1\|2025/26\|Paris | Ligue 1 | 2025/26 | Paris | mai vista | - | - | 23 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1512.3599 | 1500.0000 | -12.3599 | 1500.8582 | 1450.8582 | -50.0000 | 1488.9817 | 1388.9817 | -100.0000 | 1487.6232 | 1387.6232 | -100.0000 |
| Ligue 1\|2025/26\|Lorient | Ligue 1 | 2025/26 | Lorient | di ritorno | 2023/24 | 1.0000 | 24 | 1500.0000 | 1415.4214 | 1415.4214 | -84.5786 | 1511.8449 | 1500.0000 | -11.8449 | 1498.7749 | 1448.7749 | -50.0000 | 1484.8150 | 1384.8150 | -100.0000 | 1483.4566 | 1395.0245 | -88.4321 |
| Ligue 1\|2025/26\|Metz | Ligue 1 | 2025/26 | Metz | di ritorno | 2023/24 | 1.0000 | 24 | 1500.0000 | 1408.7939 | 1408.7939 | -91.2061 | 1515.3690 | 1500.0000 | -15.3690 | 1500.3491 | 1450.3491 | -50.0000 | 1483.9076 | 1383.9076 | -100.0000 | 1482.9746 | 1377.6965 | -105.2781 |
| Ligue 1\|2026/27\|Le Mans | Ligue 1 | 2026/27 | Le Mans | mai vista | - | - | 24 | 1500.0000 | 1500.0000 | 1500.0000 | 0.0000 | 1519.1692 | 1500.0000 | -19.1692 | 1502.8238 | 1452.8238 | -50.0000 | 1484.3863 | 1384.3863 | -100.0000 | 1483.1945 | 1383.1945 | -100.0000 |
| Ligue 1\|2026/27\|Troyes | Ligue 1 | 2026/27 | Troyes | di ritorno | 2022/23 | 3.0000 | 25 | 1500.0000 | 1327.6055 | 1327.6055 | -172.3945 | 1518.4025 | 1500.0000 | -18.4025 | 1500.8238 | 1450.8238 | -50.0000 | 1480.3863 | 1380.3863 | -100.0000 | 1479.1945 | 1372.7459 | -106.4486 |

`audit/output/elo_drift_triage_entries.csv` contiene la stessa tabella senza il limite di visualizzazione del report.

### Prime 5 e 10 partite (S0 produzione)

`ppg_real_3pt` usa 3/1/0; `elo_expected_score` e' l'`e_H` logistico (dal punto di vista della squadra, scala 0-1) e `elo_expected_points_3pt` e' la sua conversione x3. L'errore richiesto e' `S reale − e_H` dal punto di vista della squadra; `logloss_elo_1x2` e `logloss_blend_1x2` sono medie per squadra-ampiezza. Se una stagione disponibile non ha ancora 5 o 10 partite per la squadra, `n` mostra il prefisso osservato: nessuna imputazione e' stata fatta e la finestra completa non e' verificabile.

| entry_id | league | season | team | n | window | ppg_real_3pt | elo_expected_score | elo_expected_points_3pt | error_S_minus_e | logloss_elo_1x2 | logloss_blend_1x2 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Serie A\|2023/24\|Frosinone | Serie A | 2023/24 | Frosinone | 5 | 5 | 1.6000 | 0.5025 | 1.5076 | 0.0975 | 1.0123 | 1.0099 |
| Serie A\|2023/24\|Frosinone | Serie A | 2023/24 | Frosinone | 10 | 10 | 1.2000 | 0.5003 | 1.5010 | -0.0503 | 0.9605 | 0.9337 |
| Serie A\|2023/24\|Genoa | Serie A | 2023/24 | Genoa | 5 | 5 | 0.8000 | 0.3909 | 1.1728 | -0.0909 | 1.1588 | 1.1770 |
| Serie A\|2023/24\|Genoa | Serie A | 2023/24 | Genoa | 10 | 10 | 1.1000 | 0.4383 | 1.3150 | -0.0383 | 1.0114 | 1.0458 |
| Serie A\|2023/24\|Cagliari | Serie A | 2023/24 | Cagliari | 5 | 5 | 0.4000 | 0.4208 | 1.2624 | -0.2208 | 0.9867 | 0.9254 |
| Serie A\|2023/24\|Cagliari | Serie A | 2023/24 | Cagliari | 10 | 10 | 0.6000 | 0.4118 | 1.2353 | -0.1618 | 0.9486 | 0.8752 |
| Serie A\|2024/25\|Parma | Serie A | 2024/25 | Parma | 5 | 5 | 1.0000 | 0.4712 | 1.4136 | -0.0712 | 1.1645 | 1.1628 |
| Serie A\|2024/25\|Parma | Serie A | 2024/25 | Parma | 10 | 10 | 0.9000 | 0.4531 | 1.3592 | -0.0531 | 1.3502 | 1.3486 |
| Serie A\|2024/25\|Venezia | Serie A | 2024/25 | Venezia | 5 | 5 | 0.8000 | 0.3635 | 1.0904 | -0.0635 | 0.9102 | 0.8917 |
| Serie A\|2024/25\|Venezia | Serie A | 2024/25 | Venezia | 10 | 10 | 0.8000 | 0.3864 | 1.1592 | -0.0864 | 0.9133 | 0.8981 |
| Serie A\|2024/25\|Como | Serie A | 2024/25 | Como | 5 | 5 | 1.0000 | 0.3660 | 1.0980 | 0.0340 | 1.1446 | 1.0751 |
| Serie A\|2024/25\|Como | Serie A | 2024/25 | Como | 10 | 10 | 0.9000 | 0.4137 | 1.2410 | -0.0637 | 0.9921 | 0.9699 |
| Serie A\|2025/26\|Sassuolo | Serie A | 2025/26 | Sassuolo | 5 | 5 | 1.2000 | 0.2491 | 0.7472 | 0.1509 | 0.7882 | 0.7963 |
| Serie A\|2025/26\|Sassuolo | Serie A | 2025/26 | Sassuolo | 10 | 10 | 1.3000 | 0.3102 | 0.9307 | 0.1398 | 0.9362 | 0.9218 |
| Serie A\|2025/26\|Cremonese | Serie A | 2025/26 | Cremonese | 5 | 5 | 1.8000 | 0.3928 | 1.1783 | 0.3072 | 1.4306 | 1.5037 |
| Serie A\|2025/26\|Cremonese | Serie A | 2025/26 | Cremonese | 10 | 10 | 1.4000 | 0.3476 | 1.0427 | 0.2024 | 1.2292 | 1.2355 |
| Serie A\|2025/26\|Pisa | Serie A | 2025/26 | Pisa | 5 | 5 | 0.4000 | 0.3459 | 1.0377 | -0.1459 | 1.0997 | 0.9699 |
| Serie A\|2025/26\|Pisa | Serie A | 2025/26 | Pisa | 10 | 10 | 0.6000 | 0.3604 | 1.0812 | -0.0604 | 1.2318 | 1.0333 |
| Serie A\|2026/27\|Monza | Serie A | 2026/27 | Monza | 5 | 5 | 0.8000 | 0.2146 | 0.6439 | 0.0854 | 0.8768 | 0.9000 |
| Serie A\|2026/27\|Monza | Serie A | 2026/27 | Monza | 5 | 10 | 0.8000 | 0.2146 | 0.6439 | 0.0854 | 0.8768 | 0.9000 |
| Serie A\|2026/27\|Frosinone | Serie A | 2026/27 | Frosinone | 5 | 5 | 2.0000 | 0.3604 | 1.0813 | 0.3396 | 1.1507 | 1.1393 |
| Serie A\|2026/27\|Frosinone | Serie A | 2026/27 | Frosinone | 5 | 10 | 2.0000 | 0.3604 | 1.0813 | 0.3396 | 1.1507 | 1.1393 |
| Serie A\|2026/27\|Venezia | Serie A | 2026/27 | Venezia | 5 | 5 | 0.0000 | 0.3462 | 1.0386 | -0.3462 | 0.6932 | 0.6701 |
| Serie A\|2026/27\|Venezia | Serie A | 2026/27 | Venezia | 5 | 10 | 0.0000 | 0.3462 | 1.0386 | -0.3462 | 0.6932 | 0.6701 |
| Premier League\|2023/24\|Burnley | Premier League | 2023/24 | Burnley | 5 | 5 | 0.2000 | 0.4196 | 1.2587 | -0.3196 | 0.9414 | 0.8305 |
| Premier League\|2023/24\|Burnley | Premier League | 2023/24 | Burnley | 10 | 10 | 0.4000 | 0.4085 | 1.2255 | -0.2585 | 0.9147 | 0.7768 |
| Premier League\|2023/24\|Luton | Premier League | 2023/24 | Luton | 5 | 5 | 0.2000 | 0.4785 | 1.4356 | -0.3785 | 0.9890 | 0.9034 |
| Premier League\|2023/24\|Luton | Premier League | 2023/24 | Luton | 10 | 10 | 0.5000 | 0.4414 | 1.3241 | -0.2414 | 0.9788 | 0.9712 |
| Premier League\|2023/24\|Sheffield United | Premier League | 2023/24 | Sheffield United | 5 | 5 | 0.2000 | 0.4674 | 1.4021 | -0.3674 | 0.9629 | 0.8805 |
| Premier League\|2023/24\|Sheffield United | Premier League | 2023/24 | Sheffield United | 10 | 10 | 0.1000 | 0.3902 | 1.1705 | -0.3402 | 0.7949 | 0.6794 |
| Premier League\|2024/25\|Ipswich | Premier League | 2024/25 | Ipswich | 5 | 5 | 0.6000 | 0.4034 | 1.2103 | -0.1034 | 0.9997 | 1.0305 |
| Premier League\|2024/25\|Ipswich | Premier League | 2024/25 | Ipswich | 10 | 10 | 0.5000 | 0.4496 | 1.3487 | -0.1996 | 1.0631 | 1.0349 |
| Premier League\|2024/25\|Southampton | Premier League | 2024/25 | Southampton | 5 | 5 | 0.2000 | 0.2776 | 0.8329 | -0.1776 | 0.7183 | 0.6431 |
| Premier League\|2024/25\|Southampton | Premier League | 2024/25 | Southampton | 10 | 10 | 0.4000 | 0.2406 | 0.7217 | -0.0906 | 0.6407 | 0.6089 |
| Premier League\|2024/25\|Leicester | Premier League | 2024/25 | Leicester | 5 | 5 | 0.6000 | 0.3738 | 1.1213 | -0.0738 | 1.1288 | 1.1471 |
| Premier League\|2024/25\|Leicester | Premier League | 2024/25 | Leicester | 10 | 10 | 1.0000 | 0.3916 | 1.1747 | 0.0084 | 1.0124 | 1.0149 |
| Premier League\|2025/26\|Burnley | Premier League | 2025/26 | Burnley | 5 | 5 | 0.8000 | 0.2860 | 0.8579 | 0.0140 | 0.8332 | 0.8436 |
| Premier League\|2025/26\|Burnley | Premier League | 2025/26 | Burnley | 10 | 10 | 1.0000 | 0.2756 | 0.8269 | 0.0744 | 0.7059 | 0.7427 |
| Premier League\|2025/26\|Sunderland | Premier League | 2025/26 | Sunderland | 5 | 5 | 1.6000 | 0.5097 | 1.5292 | 0.0903 | 1.1922 | 1.2413 |
| Premier League\|2025/26\|Sunderland | Premier League | 2025/26 | Sunderland | 10 | 10 | 1.8000 | 0.5003 | 1.5009 | 0.1497 | 1.1714 | 1.1801 |
| Premier League\|2025/26\|Leeds | Premier League | 2025/26 | Leeds | 5 | 5 | 1.4000 | 0.2431 | 0.7294 | 0.2569 | 1.0101 | 0.9843 |
| Premier League\|2025/26\|Leeds | Premier League | 2025/26 | Leeds | 10 | 10 | 1.1000 | 0.3109 | 0.9326 | 0.0891 | 0.9640 | 0.9558 |
| Premier League\|2026/27\|Coventry City | Premier League | 2026/27 | Coventry City | 5 | 5 | 0.6000 | 0.3070 | 0.9210 | -0.1070 | 0.7875 | 0.7749 |
| Premier League\|2026/27\|Coventry City | Premier League | 2026/27 | Coventry City | 5 | 10 | 0.6000 | 0.3070 | 0.9210 | -0.1070 | 0.7875 | 0.7749 |
| Premier League\|2026/27\|Hull City | Premier League | 2026/27 | Hull City | 5 | 5 | 1.6000 | 0.4260 | 1.2779 | 0.1740 | 1.1848 | 1.2302 |
| Premier League\|2026/27\|Hull City | Premier League | 2026/27 | Hull City | 5 | 10 | 1.6000 | 0.4260 | 1.2779 | 0.1740 | 1.1848 | 1.2302 |
| Premier League\|2026/27\|Ipswich | Premier League | 2026/27 | Ipswich | 5 | 5 | 1.2000 | 0.2120 | 0.6360 | 0.1880 | 0.8289 | 0.8013 |
| Premier League\|2026/27\|Ipswich | Premier League | 2026/27 | Ipswich | 5 | 10 | 1.2000 | 0.2120 | 0.6360 | 0.1880 | 0.8289 | 0.8013 |
| La Liga\|2023/24\|Las Palmas | La Liga | 2023/24 | Las Palmas | 5 | 5 | 0.4000 | 0.4554 | 1.3661 | -0.2554 | 1.0400 | 1.0332 |
| La Liga\|2023/24\|Las Palmas | La Liga | 2023/24 | Las Palmas | 10 | 10 | 1.1000 | 0.4693 | 1.4079 | -0.0693 | 0.9719 | 0.9933 |
| La Liga\|2023/24\|Alaves | La Liga | 2023/24 | Alaves | 5 | 5 | 1.2000 | 0.5275 | 1.5824 | -0.1275 | 0.9093 | 0.9582 |
| La Liga\|2023/24\|Alaves | La Liga | 2023/24 | Alaves | 10 | 10 | 0.9000 | 0.4963 | 1.4889 | -0.1463 | 1.0890 | 1.1111 |
| La Liga\|2023/24\|Granada | La Liga | 2023/24 | Granada | 5 | 5 | 0.6000 | 0.4353 | 1.3060 | -0.2353 | 0.8150 | 0.8273 |
| La Liga\|2023/24\|Granada | La Liga | 2023/24 | Granada | 10 | 10 | 0.6000 | 0.4191 | 1.2574 | -0.1691 | 0.9904 | 1.0413 |
| La Liga\|2024/25\|Leganes | La Liga | 2024/25 | Leganes | 5 | 5 | 1.0000 | 0.5415 | 1.6244 | -0.1415 | 1.0590 | 1.0679 |
| La Liga\|2024/25\|Leganes | La Liga | 2024/25 | Leganes | 10 | 10 | 0.8000 | 0.4829 | 1.4488 | -0.1329 | 1.0504 | 1.0200 |
| La Liga\|2024/25\|Espanol | La Liga | 2024/25 | Espanol | 5 | 5 | 1.4000 | 0.3871 | 1.1614 | 0.1129 | 1.1892 | 1.2074 |
| La Liga\|2024/25\|Espanol | La Liga | 2024/25 | Espanol | 10 | 10 | 1.0000 | 0.3321 | 0.9963 | 0.0179 | 0.8876 | 0.8883 |
| La Liga\|2024/25\|Valladolid | La Liga | 2024/25 | Valladolid | 5 | 5 | 0.8000 | 0.3080 | 0.9240 | -0.0080 | 0.6375 | 0.6343 |
| La Liga\|2024/25\|Valladolid | La Liga | 2024/25 | Valladolid | 10 | 10 | 0.8000 | 0.3504 | 1.0512 | -0.0504 | 0.8610 | 0.8655 |
| La Liga\|2025/26\|Oviedo | La Liga | 2025/26 | Oviedo | 5 | 5 | 0.6000 | 0.3979 | 1.1938 | -0.1979 | 0.7288 | 0.6782 |
| La Liga\|2025/26\|Oviedo | La Liga | 2025/26 | Oviedo | 10 | 10 | 0.7000 | 0.4013 | 1.2038 | -0.1513 | 0.8901 | 0.8445 |
| La Liga\|2025/26\|Levante | La Liga | 2025/26 | Levante | 5 | 5 | 0.8000 | 0.4187 | 1.2561 | -0.1187 | 0.9370 | 0.9272 |
| La Liga\|2025/26\|Levante | La Liga | 2025/26 | Levante | 10 | 10 | 0.9000 | 0.4172 | 1.2517 | -0.0672 | 1.0092 | 0.9728 |
| La Liga\|2025/26\|Elche | La Liga | 2025/26 | Elche | 5 | 5 | 1.8000 | 0.3586 | 1.0759 | 0.3414 | 1.4658 | 1.3914 |
| La Liga\|2025/26\|Elche | La Liga | 2025/26 | Elche | 10 | 10 | 1.4000 | 0.3593 | 1.0779 | 0.1907 | 1.2815 | 1.2333 |
| La Liga\|2026/27\|Santander | La Liga | 2026/27 | Santander | 5 | 5 | 1.4000 | 0.4708 | 1.4123 | 0.0292 | 0.9408 | 0.9839 |
| La Liga\|2026/27\|Santander | La Liga | 2026/27 | Santander | 7 | 10 | 1.0000 | 0.4058 | 1.2175 | -0.0487 | 0.8097 | 0.8251 |
| La Liga\|2026/27\|Deportivo | La Liga | 2026/27 | Deportivo | 5 | 5 | 1.8000 | 0.4677 | 1.4031 | 0.2323 | 1.3107 | 1.3057 |
| La Liga\|2026/27\|Deportivo | La Liga | 2026/27 | Deportivo | 7 | 10 | 1.4286 | 0.4860 | 1.4580 | 0.0854 | 1.3171 | 1.3049 |
| La Liga\|2026/27\|Málaga | La Liga | 2026/27 | Málaga | 5 | 5 | 0.6000 | 0.3720 | 1.1161 | -0.0720 | 0.9476 | 0.9084 |
| La Liga\|2026/27\|Málaga | La Liga | 2026/27 | Málaga | 7 | 10 | 0.4286 | 0.3827 | 1.1482 | -0.1685 | 0.9133 | 0.8450 |
| Bundesliga\|2023/24\|Heidenheim | Bundesliga | 2023/24 | Heidenheim | 5 | 5 | 0.8000 | 0.4359 | 1.3077 | -0.1359 | 1.0545 | 1.0823 |
| Bundesliga\|2023/24\|Heidenheim | Bundesliga | 2023/24 | Heidenheim | 10 | 10 | 1.0000 | 0.4638 | 1.3913 | -0.1138 | 1.0507 | 1.0217 |
| Bundesliga\|2023/24\|Darmstadt | Bundesliga | 2023/24 | Darmstadt | 5 | 5 | 0.2000 | 0.4152 | 1.2456 | -0.3152 | 0.8659 | 0.8510 |
| Bundesliga\|2023/24\|Darmstadt | Bundesliga | 2023/24 | Darmstadt | 10 | 10 | 0.7000 | 0.4367 | 1.3101 | -0.1867 | 0.8443 | 0.8452 |
| Bundesliga\|2024/25\|Holstein Kiel | Bundesliga | 2024/25 | Holstein Kiel | 5 | 5 | 0.2000 | 0.4786 | 1.4359 | -0.3786 | 1.0195 | 0.9337 |
| Bundesliga\|2024/25\|Holstein Kiel | Bundesliga | 2024/25 | Holstein Kiel | 10 | 10 | 0.5000 | 0.4016 | 1.2049 | -0.2016 | 1.1028 | 1.0620 |
| Bundesliga\|2024/25\|St Pauli | Bundesliga | 2024/25 | St Pauli | 5 | 5 | 0.8000 | 0.4303 | 1.2908 | -0.1303 | 1.2158 | 1.1890 |
| Bundesliga\|2024/25\|St Pauli | Bundesliga | 2024/25 | St Pauli | 10 | 10 | 0.8000 | 0.4192 | 1.2575 | -0.1192 | 1.0866 | 1.0643 |
| Bundesliga\|2025/26\|Koln | Bundesliga | 2025/26 | Koln | 5 | 5 | 1.4000 | 0.3148 | 0.9443 | 0.1852 | 1.1187 | 1.1761 |
| Bundesliga\|2025/26\|Koln | Bundesliga | 2025/26 | Koln | 10 | 10 | 1.4000 | 0.3567 | 1.0700 | 0.1433 | 1.0340 | 1.0604 |
| Bundesliga\|2025/26\|Hamburg | Bundesliga | 2025/26 | Hamburg | 5 | 5 | 1.0000 | 0.4790 | 1.4371 | -0.0790 | 0.9522 | 0.9905 |
| Bundesliga\|2025/26\|Hamburg | Bundesliga | 2025/26 | Hamburg | 10 | 10 | 0.9000 | 0.4587 | 1.3760 | -0.1087 | 1.0113 | 1.0014 |
| Bundesliga\|2026/27\|Elversberg | Bundesliga | 2026/27 | Elversberg | 4 | 5 | 1.7500 | 0.3773 | 1.1319 | 0.2477 | 1.0067 | 1.0879 |
| Bundesliga\|2026/27\|Elversberg | Bundesliga | 2026/27 | Elversberg | 4 | 10 | 1.7500 | 0.3773 | 1.1319 | 0.2477 | 1.0067 | 1.0879 |
| Bundesliga\|2026/27\|SC Paderborn | Bundesliga | 2026/27 | SC Paderborn | 4 | 5 | 1.0000 | 0.3803 | 1.1410 | -0.0053 | 0.9453 | 0.9424 |
| Bundesliga\|2026/27\|SC Paderborn | Bundesliga | 2026/27 | SC Paderborn | 4 | 10 | 1.0000 | 0.3803 | 1.1410 | -0.0053 | 0.9453 | 0.9424 |
| Bundesliga\|2026/27\|Schalke 04 | Bundesliga | 2026/27 | Schalke 04 | 4 | 5 | 1.2500 | 0.3044 | 0.9133 | 0.1956 | 1.5110 | 1.5212 |
| Bundesliga\|2026/27\|Schalke 04 | Bundesliga | 2026/27 | Schalke 04 | 4 | 10 | 1.2500 | 0.3044 | 0.9133 | 0.1956 | 1.5110 | 1.5212 |
| Ligue 1\|2023/24\|Metz | Ligue 1 | 2023/24 | Metz | 5 | 5 | 1.6000 | 0.3907 | 1.1720 | 0.2093 | 1.2020 | 1.2082 |
| Ligue 1\|2023/24\|Metz | Ligue 1 | 2023/24 | Metz | 10 | 10 | 0.9000 | 0.4284 | 1.2851 | -0.0784 | 1.0940 | 1.0850 |
| Ligue 1\|2023/24\|Le Havre | Ligue 1 | 2023/24 | Le Havre | 5 | 5 | 1.2000 | 0.4342 | 1.3025 | 0.0658 | 1.2844 | 1.2893 |
| Ligue 1\|2023/24\|Le Havre | Ligue 1 | 2023/24 | Le Havre | 10 | 10 | 1.1000 | 0.4526 | 1.3577 | -0.0025 | 1.1528 | 1.1497 |
| Ligue 1\|2024/25\|St Etienne | Ligue 1 | 2024/25 | St Etienne | 5 | 5 | 0.6000 | 0.3622 | 1.0865 | -0.1622 | 0.8712 | 0.9224 |
| Ligue 1\|2024/25\|St Etienne | Ligue 1 | 2024/25 | St Etienne | 10 | 10 | 1.0000 | 0.4411 | 1.3232 | -0.0911 | 0.9525 | 0.9567 |
| Ligue 1\|2024/25\|Angers | Ligue 1 | 2024/25 | Angers | 5 | 5 | 0.4000 | 0.2178 | 0.6535 | -0.0178 | 0.8621 | 0.8793 |
| Ligue 1\|2024/25\|Angers | Ligue 1 | 2024/25 | Angers | 10 | 10 | 1.0000 | 0.2091 | 0.6274 | 0.1909 | 1.3421 | 1.2473 |
| Ligue 1\|2024/25\|Auxerre | Ligue 1 | 2024/25 | Auxerre | 5 | 5 | 0.6000 | 0.3395 | 1.0184 | -0.1395 | 0.8156 | 0.8167 |
| Ligue 1\|2024/25\|Auxerre | Ligue 1 | 2024/25 | Auxerre | 10 | 10 | 1.3000 | 0.3322 | 0.9966 | 0.1178 | 1.0636 | 1.1228 |
| Ligue 1\|2025/26\|Paris | Ligue 1 | 2025/26 | Paris | 5 | 5 | 1.2000 | 0.4639 | 1.3918 | -0.0639 | 0.8918 | 0.9413 |
| Ligue 1\|2025/26\|Paris | Ligue 1 | 2025/26 | Paris | 10 | 10 | 1.1000 | 0.4584 | 1.3752 | -0.0584 | 1.0042 | 1.0513 |
| Ligue 1\|2025/26\|Lorient | Ligue 1 | 2025/26 | Lorient | 5 | 5 | 0.8000 | 0.3197 | 0.9592 | -0.0197 | 0.8302 | 0.8944 |
| Ligue 1\|2025/26\|Lorient | Ligue 1 | 2025/26 | Lorient | 10 | 10 | 0.9000 | 0.3216 | 0.9648 | 0.0284 | 1.1359 | 1.1308 |
| Ligue 1\|2025/26\|Metz | Ligue 1 | 2025/26 | Metz | 5 | 5 | 0.2000 | 0.2956 | 0.8868 | -0.1956 | 0.6258 | 0.5912 |
| Ligue 1\|2025/26\|Metz | Ligue 1 | 2025/26 | Metz | 10 | 10 | 0.5000 | 0.2788 | 0.8363 | -0.0788 | 0.7199 | 0.7189 |
| Ligue 1\|2026/27\|Le Mans | Ligue 1 | 2026/27 | Le Mans | 5 | 5 | 1.2000 | 0.4481 | 1.3442 | 0.0519 | 1.1009 | 1.1411 |
| Ligue 1\|2026/27\|Le Mans | Ligue 1 | 2026/27 | Le Mans | 5 | 10 | 1.2000 | 0.4481 | 1.3442 | 0.0519 | 1.1009 | 1.1411 |
| Ligue 1\|2026/27\|Troyes | Ligue 1 | 2026/27 | Troyes | 5 | 5 | 0.8000 | 0.2277 | 0.6832 | 0.0723 | 0.9354 | 0.9876 |
| Ligue 1\|2026/27\|Troyes | Ligue 1 | 2026/27 | Troyes | 5 | 10 | 0.8000 | 0.2277 | 0.6832 | 0.0723 | 0.9354 | 0.9876 |

## 4. Varianti di seeding

S0 = produzione corrente. S1 = 1500 per tutti gli ingressi. S2 = media attiva −50. S3 = media attiva −100. S4 = ritorni con `0.5^anni_assenza` sul rating stantio verso media−100, mai viste a media−100. Nessun parametro e' stimato. Le rilanciate partono dalla prima partita e cambiano solo il seed prima della prima partita dell'ingresso.

L'evidenza dell'ordine usato e' nel file pesante per-partita; l'esecuzione ha prodotto anche `audit/output/elo_drift_triage_per_match.csv.gz` con pre/post rating e probabilita' per S0-S4.

| variant | n_entries | mean_entry_diff | sd_entry_diff | min_entry_diff | max_entry_diff |
|---|---|---|---|---|---|
| S0 | 55 | -44.4220 | 63.6250 | -198.3315 | 0.0000 |
| S1 | 55 | -6.0912 | 7.0809 | -21.8313 | 0.0000 |
| S2 | 55 | -50.0000 | 0.0000 | -50.0000 | -50.0000 |
| S3 | 55 | -100.0000 | 0.0000 | -100.0000 | -100.0000 |
| S4 | 55 | -102.4869 | 12.3077 | -145.5888 | -81.2884 |

## 5. Metriche appaiate contro S0

LogLoss 1X2: delta = variante − S0; negativo = meglio. Bootstrap a blocchi `squadra × stagione`, 2000 repliche, seed 20260905, percentili 2.5/97.5. Le righe sono osservazioni team-match: se due ingressi giocano fra loro la partita appare una volta per ciascuna squadra-blocco; per questo sono riportate sia righe team-match sia partite uniche. Per `all_matches` ogni partita e' rappresentata dai due team-side, così il blocco resta squadra×stagione.

| metric | variant | n_team_match_rows | n_unique_matches | n_team_seasons | S0_logloss | variant_logloss | delta_logloss | CI95 | ci_excludes_zero | improves |
|---|---|---|---|---|---|---|---|---|---|---|
| primary_first10_blend | S1 | 410 | 389 | 41 | 0.9930 | 0.9886 | -0.0045 | [-0.014524; +0.005590] | false | false |
| primary_first10_blend | S2 | 410 | 389 | 41 | 0.9930 | 0.9779 | -0.0151 | [-0.023696; -0.006404] | true | true |
| primary_first10_blend | S3 | 410 | 389 | 41 | 0.9930 | 0.9750 | -0.0180 | [-0.031543; -0.005516] | true | true |
| primary_first10_blend | S4 | 410 | 389 | 41 | 0.9930 | 0.9752 | -0.0178 | [-0.031070; -0.005159] | true | true |
| first5_blend | S1 | 205 | 197 | 41 | 0.9880 | 0.9854 | -0.0025 | [-0.022175; +0.016073] | false | false |
| first5_blend | S2 | 205 | 197 | 41 | 0.9880 | 0.9700 | -0.0180 | [-0.032623; -0.003054] | true | true |
| first5_blend | S3 | 205 | 197 | 41 | 0.9880 | 0.9637 | -0.0243 | [-0.044313; -0.005079] | true | true |
| first5_blend | S4 | 205 | 197 | 41 | 0.9880 | 0.9626 | -0.0254 | [-0.045441; -0.006204] | true | true |
| first10_elo | S1 | 410 | 389 | 41 | 1.0109 | 1.0054 | -0.0054 | [-0.020861; +0.010720] | false | false |
| first10_elo | S2 | 410 | 389 | 41 | 1.0109 | 0.9874 | -0.0235 | [-0.037366; -0.009572] | true | true |
| first10_elo | S3 | 410 | 389 | 41 | 1.0109 | 0.9826 | -0.0283 | [-0.047854; -0.009197] | true | true |
| first10_elo | S4 | 410 | 389 | 41 | 1.0109 | 0.9829 | -0.0280 | [-0.046750; -0.009122] | true | true |
| all_matches_blend | S1 | 10512 | 5256 | 288 | 0.9901 | 0.9904 | 0.0003 | [-0.000534; +0.001305] | false | false |
| all_matches_blend | S2 | 10512 | 5256 | 288 | 0.9901 | 0.9893 | -0.0007 | [-0.001486; -0.000025] | true | true |
| all_matches_blend | S3 | 10512 | 5256 | 288 | 0.9901 | 0.9894 | -0.0007 | [-0.001698; +0.000282] | false | false |
| all_matches_blend | S4 | 10512 | 5256 | 288 | 0.9901 | 0.9893 | -0.0007 | [-0.001701; +0.000233] | false | false |

Numerosita' dei sottoinsiemi:

| subset | n_team_match_rows | n_unique_matches | n_team_seasons |
|---|---|---|---|
| primary_first10_blend | 410 | 389 | 41 |
| first5_blend | 205 | 197 | 41 |
| first10_elo | 410 | 389 | 41 |
| all_matches_blend | 10512 | 5256 | 288 |

La metrica primaria e' `primary_first10_blend`; le altre tre sono diagnostiche fissate nel mandato: prime 5/blend, prime 10/solo Elo (`w=0`) e tutte le partite/blend.

## 6. La deriva compensa davvero il seeding?

Confronto descrittivo delle differenze d'ingresso S0 con i target S2 (−50) e S3 (−100). Distanza più bassa significa avvicinamento al target; non e' una stima di parametro e non modifica la regola decisionale.

| season | n_entries | mean_diff_S0 | mean_abs_diff_S0 | mean_abs_distance_to_S2_minus50 | mean_abs_distance_to_S3_minus100 | mean_diff_S1 | mean_diff_S2 | mean_diff_S3 | mean_diff_S4 |
|---|---|---|---|---|---|---|---|---|---|
| 2023/24 | 13 | 0.0000 | 0.0000 | 50.0000 | 100.0000 | 0.0000 | -50.0000 | -100.0000 | -100.0000 |
| 2024/25 | 14 | -50.9664 | 50.9664 | 58.1093 | 73.2901 | -1.3655 | -50.0000 | -100.0000 | -100.6111 |
| 2025/26 | 14 | -67.6472 | 67.6472 | 60.5043 | 56.8208 | -8.8345 | -50.0000 | -100.0000 | -102.7462 |
| 2026/27 | 14 | -55.9014 | 55.9014 | 63.0442 | 78.0732 | -13.7298 | -50.0000 | -100.0000 | -106.4125 |

Confronto primo/ultimo anno disponibile:
| target | primo_abs_distance | ultimo_abs_distance | delta_ultimo_meno_primo |
|---|---|---|---|
| S2 -50 | 50.0000 | 63.0442 | 13.0442 |
| S3 -100 | 100.0000 | 78.0732 | -21.9268 |

Questo confronto non prova una compensazione causale: mostra solo se la distanza media osservata si riduce o aumenta nel campione disponibile.

## 7. Regola di decisione fissata prima dei risultati

APRIRE audit completo solo se almeno una variante ha `delta_logloss < 0` nella primaria, IC95% che esclude 0 (IC tutto negativo), e nella colonna `all_matches_blend` non peggiora oltre +0.0005. Altrimenti CHIUDERE la pista deriva: S0 resta produzione e la deriva diventa nota.

| variant | primary_delta | primary_CI95 | primary_IC_tutto_negativo | all_delta | all_threshold_+0.0005 | rule_passes |
|---|---|---|---|---|---|---|
| S1 | -0.0045 | [-0.014524; +0.005590] | false | 0.0003 | true | false |
| S2 | -0.0151 | [-0.023696; -0.006404] | true | -0.0007 | true | true |
| S3 | -0.0180 | [-0.031543; -0.005516] | true | -0.0007 | true | true |
| S4 | -0.0178 | [-0.031070; -0.005159] | true | -0.0007 | true | true |

**Verdetto audit completo: APRIRE.**

Il verdetto MERGEABLE/NON MERGEABLE qui sotto riguarda la PR di audit, non un cambio produzione: la richiesta vieta modifiche a `SoccerMath/` e vieta il merge automatico.

## 8. Esito PR

| Esito | Comando | Evidenza/output |
|---|---|---|
| OK | `git status --porcelain -- SoccerMath/` | (vuoto) |
| OK | `git diff --name-only origin/main...HEAD` | audit/elo_drift_triage.py audit/results/elo_drift_triage.md audit/test_elo_drift_triage.py |
| OK | `git status --porcelain --branch` | ## arena/05412f92-soccermath2-0  M audit/elo_drift_triage.py  M audit/results/elo_drift_triage.md |

**Verdetto PR: MERGEABLE.** Non e' stato eseguito alcun merge.

## 9. Riproducibilita' e file

Comando unico:
```
.venv/bin/python audit/elo_drift_triage.py
```

Script: `audit/elo_drift_triage.py`. Report: `audit/results/elo_drift_triage.md`. Artefatti pesanti: `audit/output/elo_drift_triage_per_match.csv.gz`, `elo_drift_triage_entries.csv`, `elo_drift_triage_metrics.csv`, `elo_drift_triage_drift.csv`; sono rigenerabili e ignorati da git.

