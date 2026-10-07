# Triage deriva Elo e seeding delle neopromosse

Generato sul commit `79407d293b73ef83d8ada619ae8dac392561a95a`. Data di esecuzione UTC: 2026-10-07T11:28:25.742649+00:00

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
| OK | `.venv/bin/pytest -q audit/test_elo_walker_parity.py audit/test_elo_drift_triage.py SoccerMath/test_elo_probs_from_ratings.py` | 1 failed, 20 passed in 14.44s |
| OK | `.venv/bin/python audit/elo_weight_retune.py` | 2026-10-07 11:27:40.352   [1/6] costruzione campione   Serie A          elo= 1570 poisson= 1570 join= 1570   Premier League   elo= 1570 poisson= 1570 join= 1570   La Liga          elo= 1591 poisson= 1591 join= 1591   Bundesliga       elo= 1260 poisson= 1260 join= 1260   Ligue 1          elo= 1343 poisson= 1343 join= 1343   totale righe: 7334 [2/6] artefatto per-partita   parquet=True righe=7334 [3/6] mismatch vecchia replica [4/6] griglia + bootstrap a blocchi   train (post burn-in) n=1752   validation 2024/25 n=1752   test 2025/26 n=1752   burn-in 2022/23 (solo descrittivo) n=1826 [5/6] dettaglio per lega [6/6] report scritto /home/user/SoccerMath2.0/audit/results/elo_weight_retune.md |
| OK | `git status --porcelain -- SoccerMath/` | (vuoto) |
| OK | `git diff --name-only origin/main...HEAD` finale | SoccerMath/models/elo_engine.py SoccerMath/test_elo_probs_from_ratings.py SoccerMath/test_elo_promoted_seed.py SoccerMath/test_legacy_elo_engine.py audit/elo_drift_triage.py audit/elo_weight_retune.py audit/fixtures/elo_probs_equivalence_main.jsonl.gz audit/fixtures/elo_probs_equivalence_main.manifest.json audit/fixtures/elo_s3_parity.json audit/fixtures/elo_walker_parity.json audit/make_elo_parity_fixture.py audit/make_elo_s3_parity_fixture.py audit/results/elo_drift_triage.md audit/results/elo_weight_retune.md audit/test_elo_probs_equivalence.py audit/test_elo_s3_parity.py audit/test_elo_walker_parity.py |

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

Media attiva = media dei rating delle squadre ATTIVE AL INIZIO DELLA GIORNATA della partita d'ingresso: sono quelle che avevano gia' disputato una partita quando la giornata e' iniziata, con i rating di quel momento. L'ordine delle partite della stessa data non influenza il risultato e nel backtest il seed non usa risultati non ancora disponibili al kickoff. `s0_seed` e' 1500 per mai viste e il rating stantio per ritorni; `s0_diff` e' s0_seed − media attiva. Per S1-S4 `*_active_mean`, `*_seed`, `*_diff` sono quelli effettivamente usati nella relativa rilanciata; quindi S2 e S3 riportano anche la media attiva di quella rilanciata, non un valore ricalcolato a posteriori.

| entry_id | league | season | team | type | last_seen_season | anni_assenza | n_active_before | active_mean_s0 | stale_s0 | s0_seed | s0_diff | S1_active_mean | S1_seed | S1_diff | S2_active_mean | S2_seed | S2_diff | S3_active_mean | S3_seed | S3_diff | S4_active_mean | S4_seed | S4_diff |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Serie A\|2023/24\|Frosinone | Serie A | 2023/24 | Frosinone | mai vista | - | - | 0 | - | 1500.0000 | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - |
| Serie A\|2023/24\|Genoa | Serie A | 2023/24 | Genoa | mai vista | - | - | 0 | - | 1500.0000 | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - |
| Serie A\|2023/24\|Cagliari | Serie A | 2023/24 | Cagliari | mai vista | - | - | 16 | 1518.0236 | 1500.0000 | 1500.0000 | -18.0236 | 1518.0236 | 1500.0000 | -18.0236 | 1518.0236 | 1468.0236 | -50.0000 | 1518.0236 | 1418.0236 | -100.0000 | 1518.0236 | 1418.0236 | -100.0000 |
| Serie A\|2024/25\|Parma | Serie A | 2024/25 | Parma | mai vista | - | - | 0 | - | 1500.0000 | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - |
| Serie A\|2024/25\|Venezia | Serie A | 2024/25 | Venezia | mai vista | - | - | 8 | 1560.5233 | 1500.0000 | 1500.0000 | -60.5233 | 1560.5233 | 1500.0000 | -60.5233 | 1559.4336 | 1509.4336 | -50.0000 | 1557.7634 | 1457.7634 | -100.0000 | 1557.7634 | 1457.7634 | -100.0000 |
| Serie A\|2024/25\|Como | Serie A | 2024/25 | Como | mai vista | - | - | 16 | 1541.9959 | 1500.0000 | 1500.0000 | -41.9959 | 1541.9959 | 1500.0000 | -41.9959 | 1541.0510 | 1491.0510 | -50.0000 | 1535.4168 | 1435.4168 | -100.0000 | 1535.4168 | 1435.4168 | -100.0000 |
| Serie A\|2025/26\|Sassuolo | Serie A | 2025/26 | Sassuolo | di ritorno | 2023/24 | 1.0000 | 0 | - | 1355.7697 | 1355.7697 | - | - | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - |
| Serie A\|2025/26\|Cremonese | Serie A | 2025/26 | Cremonese | di ritorno | 2022/23 | 2.0000 | 0 | - | 1382.2660 | 1382.2660 | - | - | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - |
| Serie A\|2025/26\|Pisa | Serie A | 2025/26 | Pisa | mai vista | - | - | 8 | 1535.5590 | 1500.0000 | 1500.0000 | -35.5590 | 1568.3046 | 1500.0000 | -68.3046 | 1567.2913 | 1517.2913 | -50.0000 | 1562.5298 | 1462.5298 | -100.0000 | 1562.5298 | 1462.5298 | -100.0000 |
| Serie A\|2026/27\|Monza | Serie A | 2026/27 | Monza | di ritorno | 2024/25 | 1.0000 | 0 | - | 1306.3930 | 1306.3930 | - | - | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - |
| Serie A\|2026/27\|Frosinone | Serie A | 2026/27 | Frosinone | di ritorno | 2023/24 | 2.0000 | 8 | 1558.0936 | 1420.1117 | 1420.1117 | -137.9818 | 1590.8594 | 1500.0000 | -90.8594 | 1590.1858 | 1540.1858 | -50.0000 | 1582.7537 | 1482.7537 | -100.0000 | 1582.7537 | 1466.2355 | -116.5181 |
| Serie A\|2026/27\|Venezia | Serie A | 2026/27 | Venezia | di ritorno | 2024/25 | 1.0000 | 8 | 1558.0936 | 1419.3116 | 1419.3116 | -138.7820 | 1590.8594 | 1500.0000 | -90.8594 | 1590.1858 | 1540.1858 | -50.0000 | 1582.7537 | 1482.7537 | -100.0000 | 1582.7537 | 1442.0867 | -140.6670 |
| Premier League\|2023/24\|Burnley | Premier League | 2023/24 | Burnley | mai vista | - | - | 0 | - | 1500.0000 | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - |
| Premier League\|2023/24\|Luton | Premier League | 2023/24 | Luton | mai vista | - | - | 2 | 1609.5571 | 1500.0000 | 1500.0000 | -109.5571 | 1609.5571 | 1500.0000 | -109.5571 | 1609.5571 | 1559.5571 | -50.0000 | 1609.5571 | 1509.5571 | -100.0000 | 1609.5571 | 1509.5571 | -100.0000 |
| Premier League\|2023/24\|Sheffield United | Premier League | 2023/24 | Sheffield United | mai vista | - | - | 2 | 1609.5571 | 1500.0000 | 1500.0000 | -109.5571 | 1609.5571 | 1500.0000 | -109.5571 | 1609.5571 | 1559.5571 | -50.0000 | 1609.5571 | 1509.5571 | -100.0000 | 1609.5571 | 1509.5571 | -100.0000 |
| Premier League\|2024/25\|Ipswich | Premier League | 2024/25 | Ipswich | mai vista | - | - | 2 | 1529.8439 | 1500.0000 | 1500.0000 | -29.8439 | 1529.8439 | 1500.0000 | -29.8439 | 1534.5125 | 1484.5125 | -50.0000 | 1530.5867 | 1430.5867 | -100.0000 | 1530.5867 | 1430.5867 | -100.0000 |
| Premier League\|2024/25\|Southampton | Premier League | 2024/25 | Southampton | di ritorno | 2022/23 | 1.0000 | 2 | 1529.8439 | 1328.5359 | 1328.5359 | -201.3080 | 1529.8439 | 1500.0000 | -29.8439 | 1534.5125 | 1484.5125 | -50.0000 | 1530.5867 | 1430.5867 | -100.0000 | 1530.5867 | 1379.5613 | -151.0254 |
| Premier League\|2024/25\|Leicester | Premier League | 2024/25 | Leicester | di ritorno | 2022/23 | 1.0000 | 18 | 1538.4221 | 1412.7184 | 1412.7184 | -125.7037 | 1547.9479 | 1500.0000 | -47.9479 | 1550.3146 | 1500.3146 | -50.0000 | 1540.8862 | 1440.8862 | -100.0000 | 1538.0514 | 1425.3849 | -112.6665 |
| Premier League\|2025/26\|Burnley | Premier League | 2025/26 | Burnley | di ritorno | 2023/24 | 1.0000 | 2 | 1649.3179 | 1363.6237 | 1363.6237 | -285.6941 | 1657.2515 | 1500.0000 | -157.2515 | 1660.2076 | 1610.2076 | -50.0000 | 1651.3775 | 1551.3775 | -100.0000 | 1649.3523 | 1456.9172 | -192.4351 |
| Premier League\|2025/26\|Sunderland | Premier League | 2025/26 | Sunderland | mai vista | - | - | 2 | 1649.3179 | 1500.0000 | 1500.0000 | -149.3179 | 1657.2515 | 1500.0000 | -157.2515 | 1660.2076 | 1610.2076 | -50.0000 | 1651.3775 | 1551.3775 | -100.0000 | 1649.3523 | 1549.3523 | -100.0000 |
| Premier League\|2025/26\|Leeds | Premier League | 2025/26 | Leeds | di ritorno | 2022/23 | 2.0000 | 18 | 1561.9059 | 1349.3383 | 1349.3383 | -212.5676 | 1577.6847 | 1500.0000 | -77.6847 | 1592.5334 | 1542.5334 | -50.0000 | 1577.4385 | 1477.4385 | -100.0000 | 1570.0024 | 1439.8364 | -130.1660 |
| Premier League\|2026/27\|Coventry City | Premier League | 2026/27 | Coventry City | mai vista | - | - | 0 | - | 1500.0000 | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - |
| Premier League\|2026/27\|Hull City | Premier League | 2026/27 | Hull City | mai vista | - | - | 2 | 1639.6855 | 1500.0000 | 1500.0000 | -139.6855 | 1648.2553 | 1500.0000 | -148.2553 | 1654.3562 | 1604.3562 | -50.0000 | 1646.8491 | 1546.8491 | -100.0000 | 1643.6322 | 1543.6322 | -100.0000 |
| Premier League\|2026/27\|Ipswich | Premier League | 2026/27 | Ipswich | di ritorno | 2024/25 | 1.0000 | 2 | 1639.6855 | 1328.1797 | 1328.1797 | -311.5058 | 1648.2553 | 1500.0000 | -148.2553 | 1654.3562 | 1604.3562 | -50.0000 | 1646.8491 | 1546.8491 | -100.0000 | 1643.6322 | 1427.4487 | -216.1835 |
| La Liga\|2023/24\|Las Palmas | La Liga | 2023/24 | Las Palmas | mai vista | - | - | 4 | 1459.7144 | 1500.0000 | 1500.0000 | 40.2856 | 1459.7144 | 1500.0000 | 40.2856 | 1459.7144 | 1409.7144 | -50.0000 | 1459.7144 | 1359.7144 | -100.0000 | 1459.7144 | 1359.7144 | -100.0000 |
| La Liga\|2023/24\|Alaves | La Liga | 2023/24 | Alaves | mai vista | - | - | 16 | 1511.5056 | 1500.0000 | 1500.0000 | -11.5056 | 1511.5056 | 1500.0000 | -11.5056 | 1505.8628 | 1455.8628 | -50.0000 | 1502.7378 | 1402.7378 | -100.0000 | 1502.7378 | 1402.7378 | -100.0000 |
| La Liga\|2023/24\|Granada | La Liga | 2023/24 | Granada | mai vista | - | - | 16 | 1511.5056 | 1500.0000 | 1500.0000 | -11.5056 | 1511.5056 | 1500.0000 | -11.5056 | 1505.8628 | 1455.8628 | -50.0000 | 1502.7378 | 1402.7378 | -100.0000 | 1502.7378 | 1402.7378 | -100.0000 |
| La Liga\|2024/25\|Leganes | La Liga | 2024/25 | Leganes | mai vista | - | - | 8 | 1508.9343 | 1500.0000 | 1500.0000 | -8.9343 | 1508.9343 | 1500.0000 | -8.9343 | 1498.0989 | 1448.0989 | -50.0000 | 1488.9711 | 1388.9711 | -100.0000 | 1488.9711 | 1388.9711 | -100.0000 |
| La Liga\|2024/25\|Espanol | La Liga | 2024/25 | Espanol | di ritorno | 2022/23 | 1.0000 | 16 | 1529.3565 | 1419.6013 | 1419.6013 | -109.7552 | 1529.3565 | 1500.0000 | -29.3565 | 1517.7644 | 1467.7644 | -50.0000 | 1507.0044 | 1407.0044 | -100.0000 | 1507.0044 | 1413.3029 | -93.7015 |
| La Liga\|2024/25\|Valladolid | La Liga | 2024/25 | Valladolid | di ritorno | 2022/23 | 1.0000 | 16 | 1529.3565 | 1409.8915 | 1409.8915 | -119.4650 | 1529.3565 | 1500.0000 | -29.3565 | 1517.7644 | 1467.7644 | -50.0000 | 1507.0044 | 1407.0044 | -100.0000 | 1507.0044 | 1408.4479 | -98.5564 |
| La Liga\|2025/26\|Oviedo | La Liga | 2025/26 | Oviedo | mai vista | - | - | 0 | - | 1500.0000 | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - | - | 1500.0000 | - |
| La Liga\|2025/26\|Levante | La Liga | 2025/26 | Levante | mai vista | - | - | 4 | 1524.8236 | 1500.0000 | 1500.0000 | -24.8236 | 1529.7924 | 1500.0000 | -29.7924 | 1520.8088 | 1470.8088 | -50.0000 | 1510.8223 | 1410.8223 | -100.0000 | 1511.0523 | 1411.0523 | -100.0000 |
| La Liga\|2025/26\|Elche | La Liga | 2025/26 | Elche | di ritorno | 2022/23 | 2.0000 | 16 | 1534.7414 | 1386.7311 | 1386.7311 | -148.0103 | 1541.6360 | 1500.0000 | -41.6360 | 1528.9811 | 1478.9811 | -50.0000 | 1512.7752 | 1412.7752 | -100.0000 | 1513.1443 | 1406.5410 | -106.6033 |
| La Liga\|2026/27\|Santander | La Liga | 2026/27 | Santander | mai vista | - | - | 4 | 1495.9342 | 1500.0000 | 1500.0000 | 4.0658 | 1507.0841 | 1500.0000 | -7.0841 | 1494.1677 | 1444.1677 | -50.0000 | 1476.5678 | 1376.5678 | -100.0000 | 1476.6408 | 1376.6408 | -100.0000 |
| La Liga\|2026/27\|Deportivo | La Liga | 2026/27 | Deportivo | mai vista | - | - | 8 | 1511.9120 | 1500.0000 | 1500.0000 | -11.9120 | 1521.9386 | 1500.0000 | -21.9386 | 1503.1451 | 1453.1451 | -50.0000 | 1477.9086 | 1377.9086 | -100.0000 | 1478.0342 | 1378.0342 | -100.0000 |
| La Liga\|2026/27\|Málaga | La Liga | 2026/27 | Málaga | mai vista | - | - | 10 | 1505.2222 | 1500.0000 | 1500.0000 | -5.2222 | 1516.8628 | 1500.0000 | -16.8628 | 1495.6555 | 1445.6555 | -50.0000 | 1464.9674 | 1364.9674 | -100.0000 | 1464.9322 | 1364.9322 | -100.0000 |
| Bundesliga\|2023/24\|Heidenheim | Bundesliga | 2023/24 | Heidenheim | mai vista | - | - | 2 | 1536.9707 | 1500.0000 | 1500.0000 | -36.9707 | 1536.9707 | 1500.0000 | -36.9707 | 1536.9707 | 1486.9707 | -50.0000 | 1536.9707 | 1436.9707 | -100.0000 | 1536.9707 | 1436.9707 | -100.0000 |
| Bundesliga\|2023/24\|Darmstadt | Bundesliga | 2023/24 | Darmstadt | mai vista | - | - | 14 | 1510.4458 | 1500.0000 | 1500.0000 | -10.4458 | 1510.4458 | 1500.0000 | -10.4458 | 1509.5152 | 1459.5152 | -50.0000 | 1505.9438 | 1405.9438 | -100.0000 | 1505.9438 | 1405.9438 | -100.0000 |
| Bundesliga\|2024/25\|Holstein Kiel | Bundesliga | 2024/25 | Holstein Kiel | mai vista | - | - | 2 | 1608.7054 | 1500.0000 | 1500.0000 | -108.7054 | 1608.7054 | 1500.0000 | -108.7054 | 1606.5762 | 1556.5762 | -50.0000 | 1602.5170 | 1502.5170 | -100.0000 | 1602.5170 | 1502.5170 | -100.0000 |
| Bundesliga\|2024/25\|St Pauli | Bundesliga | 2024/25 | St Pauli | mai vista | - | - | 14 | 1530.0743 | 1500.0000 | 1500.0000 | -30.0743 | 1530.0743 | 1500.0000 | -30.0743 | 1532.0507 | 1482.0507 | -50.0000 | 1524.2747 | 1424.2747 | -100.0000 | 1524.2747 | 1424.2747 | -100.0000 |
| Bundesliga\|2025/26\|Koln | Bundesliga | 2025/26 | Koln | di ritorno | 2023/24 | 1.0000 | 14 | 1550.4537 | 1390.9953 | 1390.9953 | -159.4583 | 1550.4537 | 1500.0000 | -50.4537 | 1549.5490 | 1499.5490 | -50.0000 | 1539.2921 | 1439.2921 | -100.0000 | 1539.2921 | 1411.6676 | -127.6246 |
| Bundesliga\|2025/26\|Hamburg | Bundesliga | 2025/26 | Hamburg | mai vista | - | - | 14 | 1550.4537 | 1500.0000 | 1500.0000 | -50.4537 | 1550.4537 | 1500.0000 | -50.4537 | 1549.5490 | 1499.5490 | -50.0000 | 1539.2921 | 1439.2921 | -100.0000 | 1539.2921 | 1439.2921 | -100.0000 |
| Bundesliga\|2026/27\|Elversberg | Bundesliga | 2026/27 | Elversberg | mai vista | - | - | 2 | 1769.3030 | 1500.0000 | 1500.0000 | -269.3030 | 1772.8487 | 1500.0000 | -272.8487 | 1772.1937 | 1722.1937 | -50.0000 | 1759.3993 | 1659.3993 | -100.0000 | 1758.5104 | 1658.5104 | -100.0000 |
| Bundesliga\|2026/27\|SC Paderborn | Bundesliga | 2026/27 | SC Paderborn | mai vista | - | - | 2 | 1769.3030 | 1500.0000 | 1500.0000 | -269.3030 | 1772.8487 | 1500.0000 | -272.8487 | 1772.1937 | 1722.1937 | -50.0000 | 1759.3993 | 1659.3993 | -100.0000 | 1758.5104 | 1658.5104 | -100.0000 |
| Bundesliga\|2026/27\|Schalke 04 | Bundesliga | 2026/27 | Schalke 04 | di ritorno | 2022/23 | 3.0000 | 14 | 1572.3874 | 1415.7795 | 1415.7795 | -156.6079 | 1578.2056 | 1500.0000 | -78.2056 | 1609.3053 | 1559.3053 | -50.0000 | 1586.5801 | 1486.5801 | -100.0000 | 1584.9789 | 1476.3290 | -108.6499 |
| Ligue 1\|2023/24\|Metz | Ligue 1 | 2023/24 | Metz | mai vista | - | - | 6 | 1560.3428 | 1500.0000 | 1500.0000 | -60.3428 | 1560.3428 | 1500.0000 | -60.3428 | 1560.3428 | 1510.3428 | -50.0000 | 1560.3428 | 1460.3428 | -100.0000 | 1560.3428 | 1460.3428 | -100.0000 |
| Ligue 1\|2023/24\|Le Havre | Ligue 1 | 2023/24 | Le Havre | mai vista | - | - | 6 | 1560.3428 | 1500.0000 | 1500.0000 | -60.3428 | 1560.3428 | 1500.0000 | -60.3428 | 1560.3428 | 1510.3428 | -50.0000 | 1560.3428 | 1460.3428 | -100.0000 | 1560.3428 | 1460.3428 | -100.0000 |
| Ligue 1\|2024/25\|St Etienne | Ligue 1 | 2024/25 | St Etienne | mai vista | - | - | 2 | 1597.5586 | 1500.0000 | 1500.0000 | -97.5586 | 1597.5586 | 1500.0000 | -97.5586 | 1599.6667 | 1549.6667 | -50.0000 | 1589.4433 | 1489.4433 | -100.0000 | 1589.4433 | 1489.4433 | -100.0000 |
| Ligue 1\|2024/25\|Angers | Ligue 1 | 2024/25 | Angers | di ritorno | 2022/23 | 1.0000 | 8 | 1585.2748 | 1301.6685 | 1301.6685 | -283.6063 | 1585.2748 | 1500.0000 | -85.2748 | 1592.5345 | 1542.5345 | -50.0000 | 1579.9320 | 1479.9320 | -100.0000 | 1579.9320 | 1390.8002 | -189.1318 |
| Ligue 1\|2024/25\|Auxerre | Ligue 1 | 2024/25 | Auxerre | di ritorno | 2022/23 | 1.0000 | 8 | 1585.2748 | 1414.0547 | 1414.0547 | -171.2201 | 1585.2748 | 1500.0000 | -85.2748 | 1592.5345 | 1542.5345 | -50.0000 | 1579.9320 | 1479.9320 | -100.0000 | 1579.9320 | 1446.9934 | -132.9387 |
| Ligue 1\|2025/26\|Paris | Ligue 1 | 2025/26 | Paris | mai vista | - | - | 8 | 1570.5921 | 1500.0000 | 1500.0000 | -70.5921 | 1582.6462 | 1500.0000 | -82.6462 | 1589.5167 | 1539.5167 | -50.0000 | 1576.8710 | 1476.8710 | -100.0000 | 1571.6198 | 1471.6198 | -100.0000 |
| Ligue 1\|2025/26\|Lorient | Ligue 1 | 2025/26 | Lorient | di ritorno | 2023/24 | 1.0000 | 8 | 1570.5921 | 1415.4214 | 1415.4214 | -155.1707 | 1582.6462 | 1500.0000 | -82.6462 | 1589.5167 | 1539.5167 | -50.0000 | 1576.8710 | 1476.8710 | -100.0000 | 1571.6198 | 1441.8094 | -129.8104 |
| Ligue 1\|2025/26\|Metz | Ligue 1 | 2025/26 | Metz | di ritorno | 2023/24 | 1.0000 | 8 | 1570.5921 | 1408.7939 | 1408.7939 | -161.7982 | 1582.6462 | 1500.0000 | -82.6462 | 1589.5167 | 1539.5167 | -50.0000 | 1576.8710 | 1476.8710 | -100.0000 | 1571.6198 | 1433.1944 | -138.4254 |
| Ligue 1\|2026/27\|Le Mans | Ligue 1 | 2026/27 | Le Mans | mai vista | - | - | 2 | 1603.5869 | 1500.0000 | 1500.0000 | -103.5869 | 1623.8095 | 1500.0000 | -123.8095 | 1635.3146 | 1585.3146 | -50.0000 | 1615.8352 | 1515.8352 | -100.0000 | 1606.7897 | 1506.7897 | -100.0000 |
| Ligue 1\|2026/27\|Troyes | Ligue 1 | 2026/27 | Troyes | di ritorno | 2022/23 | 3.0000 | 2 | 1603.5869 | 1327.6055 | 1327.6055 | -275.9814 | 1623.8095 | 1500.0000 | -123.8095 | 1635.3146 | 1585.3146 | -50.0000 | 1615.8352 | 1515.8352 | -100.0000 | 1606.7897 | 1484.3916 | -122.3980 |

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

S0 = produzione SENZA il seeding degli ingressi, cioe' la produzione pre-adozione di S3 (`NoSeedEngine`: stesso motore, `_is_entry` sempre falso, cosi' l'unica differenza rispetto alle altre varianti e' il seed). S1 = 1500 per tutti gli ingressi. S2 = media attiva −50. S3 = media attiva −100. S4 = ritorni con `0.5^anni_assenza` sul rating stantio verso media−100, mai viste a media−100. Nessun parametro e' stimato. Le rilanciate partono dalla prima partita e cambiano solo il seed prima della prima partita dell'ingresso.

L'evidenza dell'ordine usato e' nel file pesante per-partita; l'esecuzione ha prodotto anche `audit/output/elo_drift_triage_per_match.csv.gz` con pre/post rating e probabilita' per S0-S4.

| variant | n_entries | mean_entry_diff | sd_entry_diff | min_entry_diff | max_entry_diff |
|---|---|---|---|---|---|
| S0 | 55 | -109.6937 | 89.6984 | -311.5058 | 40.2856 |
| S1 | 55 | -72.8056 | 61.6003 | -272.8487 | 40.2856 |
| S2 | 55 | -50.0000 | 0.0000 | -50.0000 | -50.0000 |
| S3 | 55 | -100.0000 | 0.0000 | -100.0000 | -100.0000 |
| S4 | 55 | -113.2066 | 26.5560 | -216.1835 | -93.7015 |

## 5. Metriche appaiate contro S0

LogLoss 1X2: delta = variante − S0; negativo = meglio. Bootstrap a blocchi `squadra × stagione`, 2000 repliche, seed 20260905, percentili 2.5/97.5. Le righe sono osservazioni team-match: se due ingressi giocano fra loro la partita appare una volta per ciascuna squadra-blocco; per questo sono riportate sia righe team-match sia partite uniche. Per `all_matches` ogni partita e' rappresentata dai due team-side, così il blocco resta squadra×stagione.

| metric | variant | n_team_match_rows | n_unique_matches | n_team_seasons | S0_logloss | variant_logloss | delta_logloss | CI95 | ci_excludes_zero | improves |
|---|---|---|---|---|---|---|---|---|---|---|
| primary_first10_blend | S1 | 410 | 389 | 41 | 0.9930 | 0.9886 | -0.0045 | [-0.014524; +0.005590] | false | false |
| primary_first10_blend | S2 | 410 | 389 | 41 | 0.9930 | 0.9904 | -0.0027 | [-0.016035; +0.010621] | false | false |
| primary_first10_blend | S3 | 410 | 389 | 41 | 0.9930 | 0.9810 | -0.0120 | [-0.021387; -0.003007] | true | true |
| primary_first10_blend | S4 | 410 | 389 | 41 | 0.9930 | 0.9808 | -0.0122 | [-0.019875; -0.005427] | true | true |
| first5_blend | S1 | 205 | 197 | 41 | 0.9880 | 0.9854 | -0.0025 | [-0.022175; +0.016073] | false | false |
| first5_blend | S2 | 205 | 197 | 41 | 0.9880 | 0.9908 | 0.0029 | [-0.021537; +0.026654] | false | false |
| first5_blend | S3 | 205 | 197 | 41 | 0.9880 | 0.9758 | -0.0122 | [-0.029708; +0.005609] | false | false |
| first5_blend | S4 | 205 | 197 | 41 | 0.9880 | 0.9713 | -0.0166 | [-0.030906; -0.003553] | true | true |
| first10_elo | S1 | 410 | 389 | 41 | 1.0109 | 1.0054 | -0.0054 | [-0.020861; +0.010720] | false | false |
| first10_elo | S2 | 410 | 389 | 41 | 1.0109 | 1.0099 | -0.0010 | [-0.021155; +0.020127] | false | false |
| first10_elo | S3 | 410 | 389 | 41 | 1.0109 | 0.9950 | -0.0159 | [-0.030251; -0.001385] | true | true |
| first10_elo | S4 | 410 | 389 | 41 | 1.0109 | 0.9937 | -0.0171 | [-0.028186; -0.006936] | true | true |
| all_matches_blend | S1 | 10512 | 5256 | 288 | 0.9901 | 0.9904 | 0.0003 | [-0.000534; +0.001305] | false | false |
| all_matches_blend | S2 | 10512 | 5256 | 288 | 0.9901 | 0.9905 | 0.0005 | [-0.000671; +0.001668] | false | false |
| all_matches_blend | S3 | 10512 | 5256 | 288 | 0.9901 | 0.9895 | -0.0006 | [-0.001515; +0.000286] | false | false |
| all_matches_blend | S4 | 10512 | 5256 | 288 | 0.9901 | 0.9892 | -0.0009 | [-0.001579; -0.000163] | true | true |

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
| 2023/24 | 13 | -38.7966 | 46.8537 | 39.1634 | 65.0263 | -38.7966 | -50.0000 | -100.0000 | -100.0000 |
| 2024/25 | 14 | -106.8226 | 106.8226 | 70.5383 | 57.7564 | -52.6685 | -50.0000 | -100.0000 | -113.6939 |
| 2025/26 | 14 | -132.1314 | 132.1314 | 89.3346 | 71.8717 | -80.0697 | -50.0000 | -100.0000 | -120.4604 |
| 2026/27 | 14 | -151.3171 | 151.9948 | 124.1391 | 99.1391 | -116.3031 | -50.0000 | -100.0000 | -117.0347 |

Confronto primo/ultimo anno disponibile:
| target | primo_abs_distance | ultimo_abs_distance | delta_ultimo_meno_primo |
|---|---|---|---|
| S2 -50 | 39.1634 | 124.1391 | 84.9757 |
| S3 -100 | 65.0263 | 99.1391 | 34.1128 |

Questo confronto non prova una compensazione causale: mostra solo se la distanza media osservata si riduce o aumenta nel campione disponibile.

## 7. Regola di decisione fissata prima dei risultati

APRIRE audit completo solo se almeno una variante ha `delta_logloss < 0` nella primaria, IC95% che esclude 0 (IC tutto negativo), e nella colonna `all_matches_blend` non peggiora oltre +0.0005. Altrimenti CHIUDERE la pista deriva: S0 resta produzione e la deriva diventa nota.

| variant | primary_delta | primary_CI95 | primary_IC_tutto_negativo | all_delta | all_threshold_+0.0005 | rule_passes |
|---|---|---|---|---|---|---|
| S1 | -0.0045 | [-0.014524; +0.005590] | false | 0.0003 | true | false |
| S2 | -0.0027 | [-0.016035; +0.010621] | false | 0.0005 | true | false |
| S3 | -0.0120 | [-0.021387; -0.003007] | true | -0.0006 | true | true |
| S4 | -0.0122 | [-0.019875; -0.005427] | true | -0.0009 | true | true |

**Verdetto audit completo: APRIRE.**

Il verdetto MERGEABLE/NON MERGEABLE qui sotto riguarda la PR di audit, non un cambio produzione: la richiesta vieta modifiche a `SoccerMath/` e vieta il merge automatico.

## 8. Esito PR

| Esito | Comando | Evidenza/output |
|---|---|---|
| OK | `git status --porcelain -- SoccerMath/` | (vuoto) |
| NON OK | `git diff --name-only origin/main...HEAD` | SoccerMath/models/elo_engine.py SoccerMath/test_elo_probs_from_ratings.py SoccerMath/test_elo_promoted_seed.py SoccerMath/test_legacy_elo_engine.py audit/elo_drift_triage.py audit/elo_weight_retune.py audit/fixtures/elo_probs_equivalence_main.jsonl.gz audit/fixtures/elo_probs_equivalence_main.manifest.json audit/fixtures/elo_s3_parity.json audit/fixtures/elo_walker_parity.json audit/make_elo_parity_fixture.py audit/make_elo_s3_parity_fixture.py audit/results/elo_drift_triage.md audit/results/elo_weight_retune.md audit/test_elo_probs_equivalence.py audit/test_elo_s3_parity.py audit/test_elo_walker_parity.py |
| OK | `git status --porcelain --branch` | ## arena/c2604760-soccermath2-0 |

**Verdetto PR: NON MERGEABLE.** Non e' stato eseguito alcun merge.

## 9. Riproducibilita' e file

Comando unico:
```
.venv/bin/python audit/elo_drift_triage.py
```

Script: `audit/elo_drift_triage.py`. Report: `audit/results/elo_drift_triage.md`. Artefatti pesanti: `audit/output/elo_drift_triage_per_match.csv.gz`, `elo_drift_triage_entries.csv`, `elo_drift_triage_metrics.csv`, `elo_drift_triage_drift.csv`; sono rigenerabili e ignorati da git.

