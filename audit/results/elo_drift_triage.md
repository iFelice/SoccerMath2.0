# Triage deriva Elo e seeding delle neopromosse

Generato sul commit `257d163217b09455edb1e93f899e9bfd499d0d59`. Data di esecuzione UTC: 2026-10-07T14:52:40.543243+00:00

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
| OK | `.venv/bin/pytest -q audit/test_elo_walker_parity.py audit/test_elo_drift_triage.py SoccerMath/test_elo_probs_from_ratings.py` | 21 passed in 16.02s |
| OK | `.venv/bin/python audit/elo_weight_retune.py` | 2026-10-07 14:51:55.847   [1/6] costruzione campione   Serie A          elo= 1570 poisson= 1570 join= 1570   Premier League   elo= 1570 poisson= 1570 join= 1570   La Liga          elo= 1591 poisson= 1591 join= 1591   Bundesliga       elo= 1260 poisson= 1260 join= 1260   Ligue 1          elo= 1343 poisson= 1343 join= 1343   totale righe: 7334 [2/6] artefatto per-partita   parquet=True righe=7334 [3/6] mismatch vecchia replica [4/6] griglia + bootstrap a blocchi   train (post burn-in) n=1752   validation 2024/25 n=1752   test 2025/26 n=1752   burn-in 2022/23 (solo descrittivo) n=1826 [5/6] dettaglio per lega [6/6] report scritto /home/user/SoccerMath2.0/audit/results/elo_weight_retune.md |
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
| OK | Vincolo diff del mandato (aggiornato) | il diff di questa PR tocca `SoccerMath/models/elo_engine.py` e i suoi test: e' la **correzione di produzione** del seed, autorizzata esplicitamente dal mandato corrente. `.github/` resta assente dal diff (`git diff --check` exit 0) |

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
| Serie A\|2023/24\|Frosinone | Serie A | 2023/24 | Frosinone | mai vista | - | - | 17 | 1525.6278 | 1500.0000 | 1500.0000 | -25.6278 | 1525.6278 | 1500.0000 | -25.6278 | 1525.6278 | 1475.6278 | -50.0000 | 1525.6278 | 1425.6278 | -100.0000 | 1525.6278 | 1425.6278 | -100.0000 |
| Serie A\|2023/24\|Genoa | Serie A | 2023/24 | Genoa | mai vista | - | - | 17 | 1525.6278 | 1500.0000 | 1500.0000 | -25.6278 | 1525.6278 | 1500.0000 | -25.6278 | 1525.6278 | 1475.6278 | -50.0000 | 1525.6278 | 1425.6278 | -100.0000 | 1525.6278 | 1425.6278 | -100.0000 |
| Serie A\|2023/24\|Cagliari | Serie A | 2023/24 | Cagliari | mai vista | - | - | 17 | 1527.5529 | 1500.0000 | 1500.0000 | -27.5529 | 1527.5529 | 1500.0000 | -27.5529 | 1527.4020 | 1477.4020 | -50.0000 | 1527.1076 | 1427.1076 | -100.0000 | 1527.1076 | 1427.1076 | -100.0000 |
| Serie A\|2024/25\|Parma | Serie A | 2024/25 | Parma | mai vista | - | - | 17 | 1550.8251 | 1500.0000 | 1500.0000 | -50.8251 | 1550.8251 | 1500.0000 | -50.8251 | 1547.4562 | 1497.4562 | -50.0000 | 1540.3692 | 1440.3692 | -100.0000 | 1540.3692 | 1440.3692 | -100.0000 |
| Serie A\|2024/25\|Venezia | Serie A | 2024/25 | Venezia | mai vista | - | - | 17 | 1550.7746 | 1500.0000 | 1500.0000 | -50.7746 | 1550.7746 | 1500.0000 | -50.7746 | 1547.4066 | 1497.4066 | -50.0000 | 1540.2186 | 1440.2186 | -100.0000 | 1540.2186 | 1440.2186 | -100.0000 |
| Serie A\|2024/25\|Como | Serie A | 2024/25 | Como | mai vista | - | - | 17 | 1551.3879 | 1500.0000 | 1500.0000 | -51.3879 | 1551.3879 | 1500.0000 | -51.3879 | 1548.0202 | 1498.0202 | -50.0000 | 1540.7113 | 1440.7113 | -100.0000 | 1540.7113 | 1440.7113 | -100.0000 |
| Serie A\|2025/26\|Sassuolo | Serie A | 2025/26 | Sassuolo | di ritorno | 2023/24 | 1.0000 | 17 | 1573.3333 | 1355.7697 | 1355.7697 | -217.5636 | 1573.3333 | 1500.0000 | -73.3333 | 1570.0991 | 1520.0991 | -50.0000 | 1555.9459 | 1455.9459 | -100.0000 | 1555.9459 | 1401.3623 | -154.5836 |
| Serie A\|2025/26\|Cremonese | Serie A | 2025/26 | Cremonese | di ritorno | 2022/23 | 2.0000 | 17 | 1573.3333 | 1382.2660 | 1382.2660 | -191.0673 | 1573.3333 | 1500.0000 | -73.3333 | 1570.0991 | 1520.0991 | -50.0000 | 1555.9459 | 1455.9459 | -100.0000 | 1555.9459 | 1437.5259 | -118.4200 |
| Serie A\|2025/26\|Pisa | Serie A | 2025/26 | Pisa | mai vista | - | - | 17 | 1572.4578 | 1500.0000 | 1500.0000 | -72.4578 | 1572.9076 | 1500.0000 | -72.9076 | 1569.7705 | 1519.7705 | -50.0000 | 1555.4068 | 1455.4068 | -100.0000 | 1555.2616 | 1455.2616 | -100.0000 |
| Serie A\|2026/27\|Monza | Serie A | 2026/27 | Monza | di ritorno | 2024/25 | 1.0000 | 17 | 1583.6896 | 1306.3930 | 1306.3930 | -277.2966 | 1595.5930 | 1500.0000 | -95.5930 | 1595.3275 | 1545.3275 | -50.0000 | 1574.7879 | 1474.7879 | -100.0000 | 1571.2534 | 1380.8812 | -190.3722 |
| Serie A\|2026/27\|Frosinone | Serie A | 2026/27 | Frosinone | di ritorno | 2023/24 | 2.0000 | 17 | 1583.7801 | 1420.1117 | 1420.1117 | -163.6683 | 1595.8382 | 1500.0000 | -95.8382 | 1595.6376 | 1545.6376 | -50.0000 | 1575.0253 | 1475.0253 | -100.0000 | 1571.3994 | 1452.0782 | -119.3212 |
| Serie A\|2026/27\|Venezia | Serie A | 2026/27 | Venezia | di ritorno | 2024/25 | 1.0000 | 17 | 1583.7801 | 1419.3116 | 1419.3116 | -164.4685 | 1595.8382 | 1500.0000 | -95.8382 | 1595.6376 | 1545.6376 | -50.0000 | 1575.0253 | 1475.0253 | -100.0000 | 1571.3994 | 1430.6623 | -140.7372 |
| Premier League\|2023/24\|Burnley | Premier League | 2023/24 | Burnley | mai vista | - | - | 17 | 1524.0828 | 1500.0000 | 1500.0000 | -24.0828 | 1524.0828 | 1500.0000 | -24.0828 | 1524.0828 | 1474.0828 | -50.0000 | 1524.0828 | 1424.0828 | -100.0000 | 1524.0828 | 1424.0828 | -100.0000 |
| Premier League\|2023/24\|Luton | Premier League | 2023/24 | Luton | mai vista | - | - | 17 | 1524.7889 | 1500.0000 | 1500.0000 | -24.7889 | 1524.7889 | 1500.0000 | -24.7889 | 1524.7161 | 1474.7161 | -50.0000 | 1524.5902 | 1424.5902 | -100.0000 | 1524.5902 | 1424.5902 | -100.0000 |
| Premier League\|2023/24\|Sheffield United | Premier League | 2023/24 | Sheffield United | mai vista | - | - | 17 | 1524.7889 | 1500.0000 | 1500.0000 | -24.7889 | 1524.7889 | 1500.0000 | -24.7889 | 1524.7161 | 1474.7161 | -50.0000 | 1524.5902 | 1424.5902 | -100.0000 | 1524.5902 | 1424.5902 | -100.0000 |
| Premier League\|2024/25\|Ipswich | Premier League | 2024/25 | Ipswich | mai vista | - | - | 17 | 1553.9152 | 1500.0000 | 1500.0000 | -53.9152 | 1553.9152 | 1500.0000 | -53.9152 | 1550.9885 | 1500.9885 | -50.0000 | 1545.3383 | 1445.3383 | -100.0000 | 1545.3383 | 1445.3383 | -100.0000 |
| Premier League\|2024/25\|Southampton | Premier League | 2024/25 | Southampton | di ritorno | 2022/23 | 1.0000 | 17 | 1553.9152 | 1328.5359 | 1328.5359 | -225.3793 | 1553.9152 | 1500.0000 | -53.9152 | 1550.9885 | 1500.9885 | -50.0000 | 1545.3383 | 1445.3383 | -100.0000 | 1545.3383 | 1386.9371 | -158.4012 |
| Premier League\|2024/25\|Leicester | Premier League | 2024/25 | Leicester | di ritorno | 2022/23 | 1.0000 | 17 | 1554.7711 | 1412.7184 | 1412.7184 | -142.0527 | 1554.9996 | 1500.0000 | -54.9996 | 1552.0892 | 1502.0892 | -50.0000 | 1546.2320 | 1446.2320 | -100.0000 | 1546.1513 | 1429.4348 | -116.7165 |
| Premier League\|2025/26\|Burnley | Premier League | 2025/26 | Burnley | di ritorno | 2023/24 | 1.0000 | 17 | 1575.9839 | 1363.6237 | 1363.6237 | -212.3602 | 1585.2467 | 1500.0000 | -85.2467 | 1582.8099 | 1532.8099 | -50.0000 | 1571.5257 | 1471.5257 | -100.0000 | 1568.8418 | 1403.0700 | -165.7718 |
| Premier League\|2025/26\|Sunderland | Premier League | 2025/26 | Sunderland | mai vista | - | - | 17 | 1575.9839 | 1500.0000 | 1500.0000 | -75.9839 | 1585.2467 | 1500.0000 | -85.2467 | 1582.8099 | 1532.8099 | -50.0000 | 1571.5257 | 1471.5257 | -100.0000 | 1568.8418 | 1468.8418 | -100.0000 |
| Premier League\|2025/26\|Leeds | Premier League | 2025/26 | Leeds | di ritorno | 2022/23 | 2.0000 | 17 | 1575.8391 | 1349.3383 | 1349.3383 | -226.5008 | 1585.4915 | 1500.0000 | -85.4915 | 1583.2946 | 1533.2946 | -50.0000 | 1571.6722 | 1471.6722 | -100.0000 | 1568.7642 | 1438.9077 | -129.8565 |
| Premier League\|2026/27\|Coventry City | Premier League | 2026/27 | Coventry City | mai vista | - | - | 17 | 1578.6750 | 1500.0000 | 1500.0000 | -78.6750 | 1599.2683 | 1500.0000 | -99.2683 | 1601.7991 | 1551.7991 | -50.0000 | 1583.5211 | 1483.5211 | -100.0000 | 1576.8863 | 1476.8863 | -100.0000 |
| Premier League\|2026/27\|Hull City | Premier League | 2026/27 | Hull City | mai vista | - | - | 17 | 1578.9817 | 1500.0000 | 1500.0000 | -78.9817 | 1599.5495 | 1500.0000 | -99.5495 | 1602.1610 | 1552.1610 | -50.0000 | 1583.7998 | 1483.7998 | -100.0000 | 1577.1636 | 1477.1636 | -100.0000 |
| Premier League\|2026/27\|Ipswich | Premier League | 2026/27 | Ipswich | di ritorno | 2024/25 | 1.0000 | 17 | 1578.9817 | 1328.1797 | 1328.1797 | -250.8021 | 1599.5495 | 1500.0000 | -99.5495 | 1602.1610 | 1552.1610 | -50.0000 | 1583.7998 | 1483.7998 | -100.0000 | 1577.1636 | 1393.6242 | -183.5394 |
| La Liga\|2023/24\|Las Palmas | La Liga | 2023/24 | Las Palmas | mai vista | - | - | 17 | 1516.6927 | 1500.0000 | 1500.0000 | -16.6927 | 1516.6927 | 1500.0000 | -16.6927 | 1516.6927 | 1466.6927 | -50.0000 | 1516.6927 | 1416.6927 | -100.0000 | 1516.6927 | 1416.6927 | -100.0000 |
| La Liga\|2023/24\|Alaves | La Liga | 2023/24 | Alaves | mai vista | - | - | 17 | 1516.8449 | 1500.0000 | 1500.0000 | -16.8449 | 1516.8449 | 1500.0000 | -16.8449 | 1516.7792 | 1466.7792 | -50.0000 | 1516.6781 | 1416.6781 | -100.0000 | 1516.6781 | 1416.6781 | -100.0000 |
| La Liga\|2023/24\|Granada | La Liga | 2023/24 | Granada | mai vista | - | - | 17 | 1516.8449 | 1500.0000 | 1500.0000 | -16.8449 | 1516.8449 | 1500.0000 | -16.8449 | 1516.7792 | 1466.7792 | -50.0000 | 1516.6781 | 1416.6781 | -100.0000 | 1516.6781 | 1416.6781 | -100.0000 |
| La Liga\|2024/25\|Leganes | La Liga | 2024/25 | Leganes | mai vista | - | - | 17 | 1540.6056 | 1500.0000 | 1500.0000 | -40.6056 | 1540.6056 | 1500.0000 | -40.6056 | 1535.8712 | 1485.8712 | -50.0000 | 1528.7800 | 1428.7800 | -100.0000 | 1528.7800 | 1428.7800 | -100.0000 |
| La Liga\|2024/25\|Espanol | La Liga | 2024/25 | Espanol | di ritorno | 2022/23 | 1.0000 | 17 | 1540.5582 | 1419.6013 | 1419.6013 | -120.9569 | 1540.5582 | 1500.0000 | -40.5582 | 1535.8038 | 1485.8038 | -50.0000 | 1528.6125 | 1428.6125 | -100.0000 | 1528.6125 | 1424.1069 | -104.5056 |
| La Liga\|2024/25\|Valladolid | La Liga | 2024/25 | Valladolid | di ritorno | 2022/23 | 1.0000 | 17 | 1540.5582 | 1409.8915 | 1409.8915 | -130.6667 | 1540.5582 | 1500.0000 | -40.5582 | 1535.8038 | 1485.8038 | -50.0000 | 1528.6125 | 1428.6125 | -100.0000 | 1528.6125 | 1419.2520 | -109.3605 |
| La Liga\|2025/26\|Oviedo | La Liga | 2025/26 | Oviedo | mai vista | - | - | 17 | 1555.5052 | 1500.0000 | 1500.0000 | -55.5052 | 1563.0481 | 1500.0000 | -63.0481 | 1557.2007 | 1507.2007 | -50.0000 | 1543.8752 | 1443.8752 | -100.0000 | 1543.2962 | 1443.2962 | -100.0000 |
| La Liga\|2025/26\|Levante | La Liga | 2025/26 | Levante | mai vista | - | - | 17 | 1556.0028 | 1500.0000 | 1500.0000 | -56.0028 | 1563.5318 | 1500.0000 | -63.5318 | 1557.7128 | 1507.7128 | -50.0000 | 1544.2832 | 1444.2832 | -100.0000 | 1543.7041 | 1443.7041 | -100.0000 |
| La Liga\|2025/26\|Elche | La Liga | 2025/26 | Elche | di ritorno | 2022/23 | 2.0000 | 17 | 1556.6273 | 1386.7311 | 1386.7311 | -169.8962 | 1564.1436 | 1500.0000 | -64.1436 | 1558.3552 | 1508.3552 | -50.0000 | 1544.8309 | 1444.8309 | -100.0000 | 1544.2516 | 1429.8715 | -114.3801 |
| La Liga\|2026/27\|Santander | La Liga | 2026/27 | Santander | mai vista | - | - | 17 | 1557.6873 | 1500.0000 | 1500.0000 | -57.6873 | 1570.0092 | 1500.0000 | -70.0092 | 1566.0781 | 1516.0781 | -50.0000 | 1545.7099 | 1445.7099 | -100.0000 | 1544.3907 | 1444.3907 | -100.0000 |
| La Liga\|2026/27\|Deportivo | La Liga | 2026/27 | Deportivo | mai vista | - | - | 17 | 1557.5087 | 1500.0000 | 1500.0000 | -57.5087 | 1569.8107 | 1500.0000 | -69.8107 | 1565.9183 | 1515.9183 | -50.0000 | 1545.4546 | 1445.4546 | -100.0000 | 1544.1350 | 1444.1350 | -100.0000 |
| La Liga\|2026/27\|Málaga | La Liga | 2026/27 | Málaga | mai vista | - | - | 17 | 1557.7084 | 1500.0000 | 1500.0000 | -57.7084 | 1569.9410 | 1500.0000 | -69.9410 | 1566.0814 | 1516.0814 | -50.0000 | 1545.5402 | 1445.5402 | -100.0000 | 1544.2270 | 1444.2270 | -100.0000 |
| Bundesliga\|2023/24\|Heidenheim | Bundesliga | 2023/24 | Heidenheim | mai vista | - | - | 16 | 1512.6340 | 1500.0000 | 1500.0000 | -12.6340 | 1512.6340 | 1500.0000 | -12.6340 | 1512.6340 | 1462.6340 | -50.0000 | 1512.6340 | 1412.6340 | -100.0000 | 1512.6340 | 1412.6340 | -100.0000 |
| Bundesliga\|2023/24\|Darmstadt | Bundesliga | 2023/24 | Darmstadt | mai vista | - | - | 16 | 1513.4756 | 1500.0000 | 1500.0000 | -13.4756 | 1513.4756 | 1500.0000 | -13.4756 | 1513.3657 | 1463.3657 | -50.0000 | 1513.2313 | 1413.2313 | -100.0000 | 1513.2313 | 1413.2313 | -100.0000 |
| Bundesliga\|2024/25\|Holstein Kiel | Bundesliga | 2024/25 | Holstein Kiel | mai vista | - | - | 16 | 1531.6846 | 1500.0000 | 1500.0000 | -31.6846 | 1531.6846 | 1500.0000 | -31.6846 | 1527.9970 | 1477.9970 | -50.0000 | 1523.0559 | 1423.0559 | -100.0000 | 1523.0559 | 1423.0559 | -100.0000 |
| Bundesliga\|2024/25\|St Pauli | Bundesliga | 2024/25 | St Pauli | mai vista | - | - | 16 | 1532.2927 | 1500.0000 | 1500.0000 | -32.2927 | 1532.2927 | 1500.0000 | -32.2927 | 1528.5667 | 1478.5667 | -50.0000 | 1523.5271 | 1423.5271 | -100.0000 | 1523.5271 | 1423.5271 | -100.0000 |
| Bundesliga\|2025/26\|Koln | Bundesliga | 2025/26 | Koln | di ritorno | 2023/24 | 1.0000 | 16 | 1546.4440 | 1390.9953 | 1390.9953 | -155.4487 | 1546.4440 | 1500.0000 | -46.4440 | 1540.9717 | 1490.9717 | -50.0000 | 1531.1132 | 1431.1132 | -100.0000 | 1531.1132 | 1407.1954 | -123.9178 |
| Bundesliga\|2025/26\|Hamburg | Bundesliga | 2025/26 | Hamburg | mai vista | - | - | 16 | 1546.4440 | 1500.0000 | 1500.0000 | -46.4440 | 1546.4440 | 1500.0000 | -46.4440 | 1540.9717 | 1490.9717 | -50.0000 | 1531.1132 | 1431.1132 | -100.0000 | 1531.1132 | 1431.1132 | -100.0000 |
| Bundesliga\|2026/27\|Elversberg | Bundesliga | 2026/27 | Elversberg | mai vista | - | - | 15 | 1564.7395 | 1500.0000 | 1500.0000 | -64.7395 | 1571.1582 | 1500.0000 | -71.1582 | 1565.4014 | 1515.4014 | -50.0000 | 1550.0052 | 1450.0052 | -100.0000 | 1548.5969 | 1448.5969 | -100.0000 |
| Bundesliga\|2026/27\|SC Paderborn | Bundesliga | 2026/27 | SC Paderborn | mai vista | - | - | 15 | 1564.7395 | 1500.0000 | 1500.0000 | -64.7395 | 1571.1582 | 1500.0000 | -71.1582 | 1565.4014 | 1515.4014 | -50.0000 | 1550.0052 | 1450.0052 | -100.0000 | 1548.5969 | 1448.5969 | -100.0000 |
| Bundesliga\|2026/27\|Schalke 04 | Bundesliga | 2026/27 | Schalke 04 | di ritorno | 2022/23 | 3.0000 | 15 | 1563.4868 | 1415.7795 | 1415.7795 | -147.7073 | 1569.8888 | 1500.0000 | -69.8888 | 1564.2217 | 1514.2217 | -50.0000 | 1548.6082 | 1448.6082 | -100.0000 | 1547.1977 | 1443.2705 | -103.9273 |
| Ligue 1\|2023/24\|Metz | Ligue 1 | 2023/24 | Metz | mai vista | - | - | 16 | 1540.2043 | 1500.0000 | 1500.0000 | -40.2043 | 1540.2043 | 1500.0000 | -40.2043 | 1540.2043 | 1490.2043 | -50.0000 | 1540.2043 | 1440.2043 | -100.0000 | 1540.2043 | 1440.2043 | -100.0000 |
| Ligue 1\|2023/24\|Le Havre | Ligue 1 | 2023/24 | Le Havre | mai vista | - | - | 16 | 1540.2043 | 1500.0000 | 1500.0000 | -40.2043 | 1540.2043 | 1500.0000 | -40.2043 | 1540.2043 | 1490.2043 | -50.0000 | 1540.2043 | 1440.2043 | -100.0000 | 1540.2043 | 1440.2043 | -100.0000 |
| Ligue 1\|2024/25\|St Etienne | Ligue 1 | 2024/25 | St Etienne | mai vista | - | - | 15 | 1561.5514 | 1500.0000 | 1500.0000 | -61.5514 | 1561.5514 | 1500.0000 | -61.5514 | 1560.5829 | 1510.5829 | -50.0000 | 1555.6624 | 1455.6624 | -100.0000 | 1555.6624 | 1455.6624 | -100.0000 |
| Ligue 1\|2024/25\|Angers | Ligue 1 | 2024/25 | Angers | di ritorno | 2022/23 | 1.0000 | 15 | 1561.9054 | 1301.6685 | 1301.6685 | -260.2369 | 1561.9054 | 1500.0000 | -61.9054 | 1560.9552 | 1510.9552 | -50.0000 | 1555.9577 | 1455.9577 | -100.0000 | 1555.9577 | 1378.8131 | -177.1446 |
| Ligue 1\|2024/25\|Auxerre | Ligue 1 | 2024/25 | Auxerre | di ritorno | 2022/23 | 1.0000 | 15 | 1561.9054 | 1414.0547 | 1414.0547 | -147.8507 | 1561.9054 | 1500.0000 | -61.9054 | 1560.9552 | 1510.9552 | -50.0000 | 1555.9577 | 1455.9577 | -100.0000 | 1555.9577 | 1435.0062 | -120.9515 |
| Ligue 1\|2025/26\|Paris | Ligue 1 | 2025/26 | Paris | mai vista | - | - | 15 | 1566.2081 | 1500.0000 | 1500.0000 | -66.2081 | 1582.6095 | 1500.0000 | -82.6095 | 1583.5047 | 1533.5047 | -50.0000 | 1570.6800 | 1470.6800 | -100.0000 | 1565.0319 | 1465.0319 | -100.0000 |
| Ligue 1\|2025/26\|Lorient | Ligue 1 | 2025/26 | Lorient | di ritorno | 2023/24 | 1.0000 | 15 | 1566.2081 | 1415.4214 | 1415.4214 | -150.7867 | 1582.6095 | 1500.0000 | -82.6095 | 1583.5047 | 1533.5047 | -50.0000 | 1570.6800 | 1470.6800 | -100.0000 | 1565.0319 | 1437.6473 | -127.3847 |
| Ligue 1\|2025/26\|Metz | Ligue 1 | 2025/26 | Metz | di ritorno | 2023/24 | 1.0000 | 15 | 1566.2081 | 1408.7939 | 1408.7939 | -157.4142 | 1582.6095 | 1500.0000 | -82.6095 | 1583.5047 | 1533.5047 | -50.0000 | 1570.6800 | 1470.6800 | -100.0000 | 1565.0319 | 1426.2644 | -138.7675 |
| Ligue 1\|2026/27\|Le Mans | Ligue 1 | 2026/27 | Le Mans | mai vista | - | - | 16 | 1568.3533 | 1500.0000 | 1500.0000 | -68.3533 | 1590.7100 | 1500.0000 | -90.7100 | 1596.6735 | 1546.6735 | -50.0000 | 1576.0780 | 1476.0780 | -100.0000 | 1567.3159 | 1467.3159 | -100.0000 |
| Ligue 1\|2026/27\|Troyes | Ligue 1 | 2026/27 | Troyes | di ritorno | 2022/23 | 3.0000 | 16 | 1568.3533 | 1327.6055 | 1327.6055 | -240.7478 | 1590.7100 | 1500.0000 | -90.7100 | 1596.6735 | 1546.6735 | -50.0000 | 1576.0780 | 1476.0780 | -100.0000 | 1567.3159 | 1449.8521 | -117.4638 |

`audit/output/elo_drift_triage_entries.csv` contiene la stessa tabella senza il limite di visualizzazione del report.

### 3.1 Tabella ingressi con roster: 55 ingressi storici

Elenco completo dei **55** ingressi storici (13 nella stagione 2023/24, 14 in 2024/25, 14 in 2025/26, 14 in 2026/27) con `|I|` e la media degli incumbent letti dallo stato di **inizio data** della partita d'ingresso. Il fallback `1500` non compare in nessuna riga: la prima stagione del database (2022/23) non ha stagione precedente e resta burn-in, e in nessun'altra stagione `I` e' risultata vuota.

| # | data | lega | stagione | squadra entrante | \|I\| | media I | seed S3 | fallback |
|---|---|---|---|---|---|---|---|---|
| 1 | 2023-08-19 | Bundesliga | 2023/24 | Heidenheim | 16 | 1512.6340 | 1412.6340 | no |
| 2 | 2023-08-20 | Bundesliga | 2023/24 | Darmstadt | 16 | 1513.2313 | 1413.2313 | no |
| 3 | 2024-08-24 | Bundesliga | 2024/25 | Holstein Kiel | 16 | 1523.0559 | 1423.0559 | no |
| 4 | 2024-08-25 | Bundesliga | 2024/25 | St Pauli | 16 | 1523.5271 | 1423.5271 | no |
| 5 | 2025-08-24 | Bundesliga | 2025/26 | Hamburg | 16 | 1531.1132 | 1431.1132 | no |
| 6 | 2025-08-24 | Bundesliga | 2025/26 | Koln | 16 | 1531.1132 | 1431.1132 | no |
| 7 | 2026-08-29 | Bundesliga | 2026/27 | Elversberg | 15 | 1550.0052 | 1450.0052 | no |
| 8 | 2026-08-29 | Bundesliga | 2026/27 | SC Paderborn | 15 | 1550.0052 | 1450.0052 | no |
| 9 | 2026-08-30 | Bundesliga | 2026/27 | Schalke 04 | 15 | 1548.6082 | 1448.6082 | no |
| 10 | 2023-08-12 | La Liga | 2023/24 | Las Palmas | 17 | 1516.6927 | 1416.6927 | no |
| 11 | 2023-08-14 | La Liga | 2023/24 | Alaves | 17 | 1516.6781 | 1416.6781 | no |
| 12 | 2023-08-14 | La Liga | 2023/24 | Granada | 17 | 1516.6781 | 1416.6781 | no |
| 13 | 2024-08-17 | La Liga | 2024/25 | Leganes | 17 | 1528.7800 | 1428.7800 | no |
| 14 | 2024-08-19 | La Liga | 2024/25 | Espanol | 17 | 1528.6125 | 1428.6125 | no |
| 15 | 2024-08-19 | La Liga | 2024/25 | Valladolid | 17 | 1528.6125 | 1428.6125 | no |
| 16 | 2025-08-15 | La Liga | 2025/26 | Oviedo | 17 | 1543.8752 | 1443.8752 | no |
| 17 | 2025-08-16 | La Liga | 2025/26 | Levante | 17 | 1544.2832 | 1444.2832 | no |
| 18 | 2025-08-18 | La Liga | 2025/26 | Elche | 17 | 1544.8309 | 1444.8309 | no |
| 19 | 2026-08-16 | La Liga | 2026/27 | Santander | 17 | 1545.7099 | 1445.7099 | no |
| 20 | 2026-08-17 | La Liga | 2026/27 | Deportivo | 17 | 1545.4546 | 1445.4546 | no |
| 21 | 2026-08-19 | La Liga | 2026/27 | Málaga | 17 | 1545.5402 | 1445.5402 | no |
| 22 | 2023-08-13 | Ligue 1 | 2023/24 | Le Havre | 16 | 1540.2043 | 1440.2043 | no |
| 23 | 2023-08-13 | Ligue 1 | 2023/24 | Metz | 16 | 1540.2043 | 1440.2043 | no |
| 24 | 2024-08-17 | Ligue 1 | 2024/25 | St Etienne | 15 | 1555.6624 | 1455.6624 | no |
| 25 | 2024-08-18 | Ligue 1 | 2024/25 | Angers | 15 | 1555.9577 | 1455.9577 | no |
| 26 | 2024-08-18 | Ligue 1 | 2024/25 | Auxerre | 15 | 1555.9577 | 1455.9577 | no |
| 27 | 2025-08-17 | Ligue 1 | 2025/26 | Lorient | 15 | 1570.6800 | 1470.6800 | no |
| 28 | 2025-08-17 | Ligue 1 | 2025/26 | Metz | 15 | 1570.6800 | 1470.6800 | no |
| 29 | 2025-08-17 | Ligue 1 | 2025/26 | Paris | 15 | 1570.6800 | 1470.6800 | no |
| 30 | 2026-08-22 | Ligue 1 | 2026/27 | Le Mans | 16 | 1576.0780 | 1476.0780 | no |
| 31 | 2026-08-22 | Ligue 1 | 2026/27 | Troyes | 16 | 1576.0780 | 1476.0780 | no |
| 32 | 2023-08-11 | Premier League | 2023/24 | Burnley | 17 | 1524.0828 | 1424.0828 | no |
| 33 | 2023-08-12 | Premier League | 2023/24 | Luton | 17 | 1524.5902 | 1424.5902 | no |
| 34 | 2023-08-12 | Premier League | 2023/24 | Sheffield United | 17 | 1524.5902 | 1424.5902 | no |
| 35 | 2024-08-17 | Premier League | 2024/25 | Ipswich | 17 | 1545.3383 | 1445.3383 | no |
| 36 | 2024-08-17 | Premier League | 2024/25 | Southampton | 17 | 1545.3383 | 1445.3383 | no |
| 37 | 2024-08-19 | Premier League | 2024/25 | Leicester | 17 | 1546.2320 | 1446.2320 | no |
| 38 | 2025-08-16 | Premier League | 2025/26 | Burnley | 17 | 1571.5257 | 1471.5257 | no |
| 39 | 2025-08-16 | Premier League | 2025/26 | Sunderland | 17 | 1571.5257 | 1471.5257 | no |
| 40 | 2025-08-18 | Premier League | 2025/26 | Leeds | 17 | 1571.6722 | 1471.6722 | no |
| 41 | 2026-08-21 | Premier League | 2026/27 | Coventry City | 17 | 1583.5211 | 1483.5211 | no |
| 42 | 2026-08-22 | Premier League | 2026/27 | Hull City | 17 | 1583.7998 | 1483.7998 | no |
| 43 | 2026-08-22 | Premier League | 2026/27 | Ipswich | 17 | 1583.7998 | 1483.7998 | no |
| 44 | 2023-08-19 | Serie A | 2023/24 | Frosinone | 17 | 1525.6278 | 1425.6278 | no |
| 45 | 2023-08-19 | Serie A | 2023/24 | Genoa | 17 | 1525.6278 | 1425.6278 | no |
| 46 | 2023-08-21 | Serie A | 2023/24 | Cagliari | 17 | 1527.1076 | 1427.1076 | no |
| 47 | 2024-08-17 | Serie A | 2024/25 | Parma | 17 | 1540.3692 | 1440.3692 | no |
| 48 | 2024-08-18 | Serie A | 2024/25 | Venezia | 17 | 1540.2186 | 1440.2186 | no |
| 49 | 2024-08-19 | Serie A | 2024/25 | Como | 17 | 1540.7113 | 1440.7113 | no |
| 50 | 2025-08-23 | Serie A | 2025/26 | Cremonese | 17 | 1555.9459 | 1455.9459 | no |
| 51 | 2025-08-23 | Serie A | 2025/26 | Sassuolo | 17 | 1555.9459 | 1455.9459 | no |
| 52 | 2025-08-24 | Serie A | 2025/26 | Pisa | 17 | 1555.4068 | 1455.4068 | no |
| 53 | 2026-08-22 | Serie A | 2026/27 | Monza | 17 | 1574.7879 | 1474.7879 | no |
| 54 | 2026-08-23 | Serie A | 2026/27 | Frosinone | 17 | 1575.0253 | 1475.0253 | no |
| 55 | 2026-08-23 | Serie A | 2026/27 | Venezia | 17 | 1575.0253 | 1475.0253 | no |

`|I|` va da **15** a **17**: 17 in Serie A, Premier League e La Liga (campionati da 20, con 3 promosse); in Bundesliga e Ligue 1, da 18 squadre, vale 18 meno le promosse e quindi 15 o 16. Nessuna delle 55 righe ha un ingresso dentro `I`, nessuna squadra fuori roster compare in `I`, e in tutte e 55 `seed = media I − 100` esattamente.

### 3.2 Tabella ingressi con roster: 14 ingressi 2026/27

Il roster 2026/27 viene dalla stessa sorgente di calendario che l'app usa per le partite programmate (i CSV `*_Live.csv` della stagione corrente), verificata come roster completo in tutte e 5 le leghe: Serie A 20/20, Premier League 20/20, La Liga 20/20, Bundesliga 18/18, Ligue 1 18/18.

| # | data | lega | stagione | squadra entrante | \|I\| | media I | seed S3 |
|---|---|---|---|---|---|---|---|
| 1 | 2026-08-29 | Bundesliga | 2026/27 | Elversberg | 15 | 1550.0052 | 1450.0052 |
| 2 | 2026-08-29 | Bundesliga | 2026/27 | SC Paderborn | 15 | 1550.0052 | 1450.0052 |
| 3 | 2026-08-30 | Bundesliga | 2026/27 | Schalke 04 | 15 | 1548.6082 | 1448.6082 |
| 4 | 2026-08-16 | La Liga | 2026/27 | Santander | 17 | 1545.7099 | 1445.7099 |
| 5 | 2026-08-17 | La Liga | 2026/27 | Deportivo | 17 | 1545.4546 | 1445.4546 |
| 6 | 2026-08-19 | La Liga | 2026/27 | Málaga | 17 | 1545.5402 | 1445.5402 |
| 7 | 2026-08-22 | Ligue 1 | 2026/27 | Le Mans | 16 | 1576.0780 | 1476.0780 |
| 8 | 2026-08-22 | Ligue 1 | 2026/27 | Troyes | 16 | 1576.0780 | 1476.0780 |
| 9 | 2026-08-21 | Premier League | 2026/27 | Coventry City | 17 | 1583.5211 | 1483.5211 |
| 10 | 2026-08-22 | Premier League | 2026/27 | Hull City | 17 | 1583.7998 | 1483.7998 |
| 11 | 2026-08-22 | Premier League | 2026/27 | Ipswich | 17 | 1583.7998 | 1483.7998 |
| 12 | 2026-08-22 | Serie A | 2026/27 | Monza | 17 | 1574.7879 | 1474.7879 |
| 13 | 2026-08-23 | Serie A | 2026/27 | Frosinone | 17 | 1575.0253 | 1475.0253 |
| 14 | 2026-08-23 | Serie A | 2026/27 | Venezia | 17 | 1575.0253 | 1475.0253 |

In tutte e 14 le righe `seed = media I − 100` esattamente e il fallback `1500` non compare.

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
| S0 | 55 | -97.0232 | 75.6112 | -277.2966 | -12.6340 |
| S1 | 55 | -58.0413 | 25.6696 | -99.5495 | -12.6340 |
| S2 | 55 | -50.0000 | 0.0000 | -50.0000 | -50.0000 |
| S3 | 55 | -100.0000 | 0.0000 | -100.0000 | -100.0000 |
| S4 | 55 | -113.0095 | 23.3342 | -190.3722 | -100.0000 |

## 5. Metriche appaiate contro S0

LogLoss 1X2: delta = variante − S0; negativo = meglio. Bootstrap a blocchi `squadra × stagione`, 2000 repliche, seed 20260905, percentili 2.5/97.5. Le righe sono osservazioni team-match: se due ingressi giocano fra loro la partita appare una volta per ciascuna squadra-blocco; per questo sono riportate sia righe team-match sia partite uniche. Per `all_matches` ogni partita e' rappresentata dai due team-side, così il blocco resta squadra×stagione.

| metric | variant | n_team_match_rows | n_unique_matches | n_team_seasons | S0_logloss | variant_logloss | delta_logloss | CI95 | ci_excludes_zero | improves |
|---|---|---|---|---|---|---|---|---|---|---|
| primary_first10_blend | S1 | 410 | 389 | 41 | 0.9930 | 0.9886 | -0.0045 | [-0.014524; +0.005590] | false | false |
| primary_first10_blend | S2 | 410 | 389 | 41 | 0.9930 | 0.9850 | -0.0081 | [-0.019027; +0.003617] | false | false |
| primary_first10_blend | S3 | 410 | 389 | 41 | 0.9930 | 0.9747 | -0.0183 | [-0.028576; -0.007930] | true | true |
| primary_first10_blend | S4 | 410 | 389 | 41 | 0.9930 | 0.9744 | -0.0186 | [-0.027877; -0.009881] | true | true |
| first5_blend | S1 | 205 | 197 | 41 | 0.9880 | 0.9854 | -0.0025 | [-0.022175; +0.016073] | false | false |
| first5_blend | S2 | 205 | 197 | 41 | 0.9880 | 0.9813 | -0.0067 | [-0.028422; +0.014203] | false | false |
| first5_blend | S3 | 205 | 197 | 41 | 0.9880 | 0.9662 | -0.0218 | [-0.040503; -0.003100] | true | true |
| first5_blend | S4 | 205 | 197 | 41 | 0.9880 | 0.9626 | -0.0254 | [-0.041025; -0.010076] | true | true |
| first10_elo | S1 | 410 | 389 | 41 | 1.0109 | 1.0054 | -0.0054 | [-0.020861; +0.010720] | false | false |
| first10_elo | S2 | 410 | 389 | 41 | 1.0109 | 0.9996 | -0.0112 | [-0.027719; +0.006491] | false | false |
| first10_elo | S3 | 410 | 389 | 41 | 1.0109 | 0.9823 | -0.0286 | [-0.044420; -0.012407] | true | true |
| first10_elo | S4 | 410 | 389 | 41 | 1.0109 | 0.9814 | -0.0295 | [-0.042999; -0.016711] | true | true |
| all_matches_blend | S1 | 10512 | 5256 | 288 | 0.9901 | 0.9904 | 0.0003 | [-0.000534; +0.001305] | false | false |
| all_matches_blend | S2 | 10512 | 5256 | 288 | 0.9901 | 0.9902 | 0.0001 | [-0.000922; +0.001181] | false | false |
| all_matches_blend | S3 | 10512 | 5256 | 288 | 0.9901 | 0.9892 | -0.0009 | [-0.001801; -0.000034] | true | true |
| all_matches_blend | S4 | 10512 | 5256 | 288 | 0.9901 | 0.9889 | -0.0011 | [-0.001866; -0.000440] | true | true |

Numerosita' dei sottoinsiemi:

| subset | n_team_match_rows | n_unique_matches | n_team_seasons |
|---|---|---|---|
| primary_first10_blend | 410 | 389 | 41 |
| first5_blend | 205 | 197 | 41 |
| first10_elo | 410 | 389 | 41 |
| all_matches_blend | 10512 | 5256 | 288 |

La metrica primaria e' `primary_first10_blend`; le altre tre sono diagnostiche fissate nel mandato: prime 5/blend, prime 10/solo Elo (`w=0`) e tutte le partite/blend.

### 5.1 Le tre definizioni del riferimento a confronto

Le tre colonne sono la stessa procedura, le stesse 4 varianti, gli stessi 2000 bootstrap a blocchi con seed 20260905, gli stessi 7.334 match: cambia solo l'insieme di riferimento `I` usato per costruire il seed degli ingressi.

- **Originale con retrocessioni** (`123b942`): `I` = squadre in lega che hanno giocato nella stagione corrente **oppure** nella precedente (le retrocessioni tornano dentro l'attivo).
- **Gia' giocate** (`df23df5`): `I` = squadre che hanno **gia' giocato** nella stagione corrente. A inizio stagione `I` e' vuoto o 1–2 squadre, quindi il seed non e' confrontabile tra partite: e' la definizione che questa PR sostituisce.
- **Roster** (questo report, `HEAD`): `I = R(s) ∩ R(s−1)`, dove `R(s)` e' la composizione del campionato derivata dal calendario di stagione, nota prima del calcio d'inizio.

`S0` (nessun seed) non dipende dalla definizione e resta identico: LogLoss 0.9930 sulla primaria, 1.0109 su `first10_elo`, 0.9901 su tutte le partite. Solo S1–S4 si spostano, ed e' il confronto fra loro che isola l'effetto della definizione.

#### Primaria `primary_first10_blend` (delta LogLoss, negativo = meglio)

| variante | originale con retrocessioni | gia' giocate | roster |
|---|---|---|---|
| S1 | -0.0045 (IC include 0) | -0.0045 (IC include 0) | -0.0045 (IC include 0) |
| S2 | **-0.0149** `[-0.023437; -0.006229]` | -0.0027 `[-0.016035; +0.010621]` (IC include 0) | -0.0081 `[-0.019027; +0.003617]` (IC include 0) |
| S3 | -0.0177 `[-0.030901; -0.005302]` | -0.0120 `[-0.021387; -0.003007]` | **-0.0183** `[-0.028576; -0.007930]` |
| S4 | -0.0176 `[-0.030657; -0.005091]` | -0.0122 `[-0.019875; -0.005427]` | -0.0186 `[-0.027877; -0.009881]` |

#### Tutte le partite `all_matches_blend` (soglia di non peggioramento: +0.0005)

| variante | originale con retrocessioni | gia' giocate | roster |
|---|---|---|---|
| S1 | +0.0003 (IC include 0) | +0.0003 (IC include 0) | +0.0003 (IC include 0) |
| S2 | -0.0007 `[-0.001466; -0.000001]` | +0.0005 `[-0.000671; +0.001668]` | +0.0001 `[-0.000922; +0.001181]` |
| S3 | -0.0007 `[-0.001664; +0.000304]` (IC include 0) | -0.0006 `[-0.001515; +0.000286]` (IC include 0) | **-0.0009** `[-0.001801; -0.000034]` |
| S4 | -0.0007 `[-0.001682; +0.000232]` (IC include 0) | -0.0009 `[-0.001579; -0.000163]` | -0.0011 `[-0.001866; -0.000440]` |

Cosa si legge nelle tre colonne:

1. **"Gia' giocate" e' la piu' debole delle tre.** S2 sulla primaria e' -0.0027 con IC che include 0 e su tutte le partite S2 peggiora (+0.0005). Con un `I` che a inizio stagione non contiene nessuna squadra, il seed coincide con 1500 e le varianti non hanno potere di distinguersi.
2. **Il roster e' l'unico dei tre in cui S3 ha i due IC negativi insieme**: primaria `[-0.028576; -0.007930]` e tutte le partite `[-0.001801; -0.000034]`. Sotto "originale" e "gia' giocate" S3 sulla primaria e' negativo ma su tutte le partite l'IC tocca zero.
3. **Il roster recupera gran parte del vantaggio della definizione originale sulla primaria** (-0.0183 contro -0.0177) pur essendo privo di look-ahead, mentre su tutte le partite e' migliore delle altre due (-0.0009 contro -0.0007 e -0.0006, entrambi con IC che include 0).
4. **S4 resta migliore di S3 di circa 0.0003 sulla primaria in tutte e tre le colonne.** La differenza e' molto piu' piccola della larghezza degli IC e S4 resta una variante non dichiarata: non viene promossa e non viene aggiunto alcun offset, perche' la regola fissa S3 come variante dichiarata.

Comandi per riprodurre le due colonne storiche:

```
git show 123b942:audit/results/elo_drift_triage.md   # originale con retrocessioni
git show df23df5:audit/results/elo_drift_triage.md   # gia' giocate
.venv/bin/python audit/elo_drift_triage.py            # roster (questo report)
```

## 6. La deriva compensa davvero il seeding?

Confronto descrittivo delle differenze d'ingresso S0 con i target S2 (−50) e S3 (−100). Distanza più bassa significa avvicinamento al target; non e' una stima di parametro e non modifica la regola decisionale.

| season | n_entries | mean_diff_S0 | mean_abs_diff_S0 | mean_abs_distance_to_S2_minus50 | mean_abs_distance_to_S3_minus100 | mean_diff_S1 | mean_diff_S2 | mean_diff_S3 | mean_diff_S4 |
|---|---|---|---|---|---|---|---|---|---|
| 2023/24 | 13 | -23.7977 | 23.7977 | 26.2023 | 76.2023 | -23.7977 | -50.0000 | -100.0000 | -100.0000 |
| 2024/25 | 14 | -100.0129 | 100.0129 | 56.5010 | 61.0076 | -49.0628 | -50.0000 | -100.0000 | -113.3628 |
| 2025/26 | 14 | -132.4028 | 132.4028 | 82.9108 | 64.8883 | -71.9285 | -50.0000 | -100.0000 | -119.5059 |
| 2026/27 | 14 | -126.6489 | 126.6489 | 76.6489 | 65.4498 | -84.9302 | -50.0000 | -100.0000 | -118.2401 |

Confronto primo/ultimo anno disponibile:
| target | primo_abs_distance | ultimo_abs_distance | delta_ultimo_meno_primo |
|---|---|---|---|
| S2 -50 | 26.2023 | 76.6489 | 50.4465 |
| S3 -100 | 76.2023 | 65.4498 | -10.7525 |

Questo confronto non prova una compensazione causale: mostra solo se la distanza media osservata si riduce o aumenta nel campione disponibile.

## 7. Regola di decisione fissata prima dei risultati

APRIRE audit completo solo se almeno una variante ha `delta_logloss < 0` nella primaria, IC95% che esclude 0 (IC tutto negativo), e nella colonna `all_matches_blend` non peggiora oltre +0.0005. Altrimenti CHIUDERE la pista deriva: S0 resta produzione e la deriva diventa nota.

| variant | primary_delta | primary_CI95 | primary_IC_tutto_negativo | all_delta | all_threshold_+0.0005 | rule_passes |
|---|---|---|---|---|---|---|
| S1 | -0.0045 | [-0.014524; +0.005590] | false | 0.0003 | true | false |
| S2 | -0.0081 | [-0.019027; +0.003617] | false | 0.0001 | true | false |
| S3 | -0.0183 | [-0.028576; -0.007930] | true | -0.0009 | true | true |
| S4 | -0.0186 | [-0.027877; -0.009881] | true | -0.0011 | true | true |

**Verdetto audit completo: APRIRE.**

Il verdetto MERGEABLE/NON MERGEABLE qui sotto riguarda la PR di audit, non un cambio produzione: la richiesta vieta modifiche a `SoccerMath/` e vieta il merge automatico.

## 8. Esito PR #36

Chiusura della correzione della definizione del seed: da "chi ha gia' giocato nella stagione corrente" al **roster di stagione** `R(s) ∩ R(s−1)`, identico in produzione e in audit. PR #36 aperta su `main`, **non merged**.

### 8.1 Definizione e implementazione

| Esito | Comando | Evidenza/output |
|---|---|---|
| OK | `grep -n "season_rosters\|_incumbent\|promoted_seed" SoccerMath/models/elo_engine.py` | `season_rosters` e' input esplicito del costruttore (riga 88), `_incumbent` calcola `R(s) ∩ R(s−1)` (riga 142), `promoted_seed(season=None)` (riga 186) |
| OK | `audit/elo_drift_triage.py` | stessa definizione di incumbent, ricavata dal calendario di stagione |
| OK | `audit/make_elo_parity_fixture.py` | helper `_roster_completo()`: il roster completo passa identico al walker troncato e alla produzione |
| OK | `grep -n "season" SoccerMath/models/elo_engine.py` (ramo di predizione) | `predict_elo_probs(..., season=None)` accetta la stagione e chiama `promoted_seed(season)` con la stessa funzione |
| OK | fallback 1500 | e' il burn-in della prima stagione del database (2022/23): **0 ingressi** su 55 in cui `I` risulti vuota |

### 8.2 Tabella ingressi (55 + 14)

| Esito | Comando | Evidenza/output |
|---|---|---|
| OK | `/home/user/scratch/entries_roster.py` | **55** ingressi storici, tabella completa in §3.1 |
| OK | `dump_ingressi.py` sul ramo | **14** ingressi 2026/27, tabella in §3.2 |
| OK | `\|I\|` sui 55 | min **15**, max **17**; 17 in Serie A/Premier League/La Liga, 15–16 in Bundesliga e Ligue 1 (18 squadre) |
| OK | ispezione di `I` su tutti i 55 | **0** ingressi dentro `I`, **0** squadre fuori roster dentro `I` |
| OK | `seed = media I − 100` | esatto in 55/55 |
| OK | gate roster 2026/27 sui CSV `*_Live.csv` | Serie A 20/20, Premier League 20/20, La Liga 20/20, Bundesliga 18/18, Ligue 1 18/18 |

### 8.3 Parita', invarianza e troncamento

| Esito | Comando | Evidenza/output |
|---|---|---|
| OK | `pytest audit/test_elo_s3_parity.py` | **7334/7334** match bit-exatti produzione vs audit S3 |
| OK | `pytest audit/test_elo_s3_parity.py` (suite) | 6 passed |
| OK | `/home/user/scratch/ordine_invarianza.py` | 5 semi di permutazione (20261007, 42, 1337, 99991, 7): **0** differenze di rating finale, **0** differenze di 1X2 per partita; `ESITO: OK` |
| OK | `/home/user/scratch/p3_cutoff.py` | **33/33** casi bit-exact sui 8 cutoff, di cui i 5 primi-giorni-di-stagione 2023-08-19, 2024-08-17, 2025-08-15, 2026-08-21, 2026-08-22; **11/11** casi entranti |
| OK | `pytest -k p3_walk_forward_vs_produzione_troncata` | 1 passed |

### 8.4 Triage sulle tre definizioni

Tre colonne in §5.1 (originale con retrocessioni `123b942`, gia' giocate `df23df5`, roster). Regola di decisione invariata, nessuna variante nuova, nessun offset nuovo.

| variante | primaria roster (IC95) | tutte le partite roster (IC95) | regola |
|---|---|---|---|
| S1 | -0.0045 (include 0) | +0.0003 (include 0) | non passa |
| S2 | -0.0081 (include 0) | +0.0001 (include 0) | non passa |
| **S3** | **-0.0183** `[-0.028576; -0.007930]` | **-0.0009** `[-0.001801; -0.000034]` | **passa** |
| S4 | -0.0186 `[-0.027877; -0.009881]` | -0.0011 `[-0.001866; -0.000440]` | passa ma non dichiarata |

**S3 resta la variante dichiarata**: sulla primaria l'IC e' tutto negativo e su tutte le partite il delta e' negativo, quindi non peggiora oltre +0.0005. S4 e' migliore di ~0.0003 sulla primaria, molto meno della larghezza degli IC: non viene promossa e non viene aggiunto alcun offset.

### 8.5 Chiusura tecnica

| Esito | Comando | Evidenza/output |
|---|---|---|
| OK | `.venv/bin/python -m pytest -q -rs --ignore=SoccerMath/test_theme_toggle.py` | **1177 passed**, 1006 subtests passed, **0 failed, 0 skipped, 0 error**, 1 warning |
| OK | `.venv/bin/python -W ignore SoccerMath/test_theme_toggle.py` | "TUTTI I TEST PASSATI"; e' uno **script**, non un modulo pytest: chiama `sys.exit(0)` a fine file e non e' collezionabile. Comportamento identico su `9957f41`, file non toccato da questa PR (`git diff 9957f41 HEAD -- SoccerMath/test_theme_toggle.py` vuoto) |
| OK | `pytest audit/test_elo_s3_parity.py audit/test_elo_walker_parity.py audit/test_elo_probs_equivalence.py SoccerMath/test_elo_promoted_seed.py SoccerMath/test_legacy_elo_engine.py SoccerMath/test_elo_probs_from_ratings.py` | **67 passed**, 0 skipped (i 2 skip di `test_legacy_elo_engine.py` sono stati riscritti e ora asseriscono la differenza attesa esatta) |
| OK | `git diff --check` | exit 0, nessun output |
| OK | `git diff --name-only origin/main...HEAD \| grep -c '^\.github/'` | **0**: `.github/` non e' nel diff |
| OK | `git diff --name-only origin/main...HEAD` | 16 file: `SoccerMath/models/elo_engine.py`, 3 test di produzione, 9 file `audit/`, 2 fixture, questo referto |
| OK | `git status --porcelain --branch` | `## arena/c2604760-soccermath2-0` pulito |
| OK | `gh run list --branch arena/c2604760-soccermath2-0` | 4 run su `4e00ae0`, tutti `success`: Audit `push` 37644124749, Audit `pull_request` 37644129871, Replay `push` 37644124746, Replay `pull_request` 37644129909 |
| **NON VERIFICABILE in CI** | workflow `topmix_audit.yml` / `replay_legacy_topmix.yml` | La CI **non esegue i test Elo di audit**: `test_elo_s3_parity.py`, `test_elo_walker_parity.py`, `test_elo_probs_equivalence.py` e `test_elo_promoted_seed.py` non compaiono in nessuna delle due liste. Il loro esito e' solo locale (67 passed sopra) e va riportato esplicitamente; i test Elo aggiunti alla CI Audit appartengono a una PR separata. |

**Verdetto PR #36: MERGEABLE**, sulla base di tutti i controlli sopra. Non e' stato eseguito alcun merge.

## 9. Impatto 2026/27 e Top Mix A/B main-vs-branch

Ricalcolato da zero su questo ramo, contro il main `9957f41` (il merge di PR #35), con gli stessi comandi e la stessa finestra.

### 9.1 Seed degli ingressi 2026/27

I 14 ingressi e i loro seed sono in §3.2: `seed = media I − 100`, `|I|` fra 15 e 17, fallback `1500` mai presente. Il seed non e' piu' una media di 1–2 squadre a inizio stagione.

### 9.2 Impatto sui rating finali

Comando:

```
.venv/bin/python /home/user/scratch/dump_ingressi.py <albero> <out.json>
```

| Esito | Evidenza |
|---|---|
| OK | 55 ingressi enumerati dal ramo, 0 fallback |
| OK | rating finali diversi dal main su **129 delle 133** squadre, delta da **−46.83** a **+145.73** Elo |
| OK | tutte e 14 le entranti 2026/27 hanno rating finale diverso dal main |

| lega | entrante | rating finale main | rating finale roster | delta |
|---|---|---|---|---|
| Serie A | Monza | 1315.9781 | 1461.7106 | +145.73 |
| Serie A | Frosinone | 1483.4524 | 1528.9790 | +45.53 |
| Serie A | Venezia | 1361.2035 | 1406.3561 | +45.15 |
| Premier League | Coventry City | 1474.0003 | 1460.2210 | −13.78 |
| Premier League | Hull City | 1528.5243 | 1515.0454 | −13.48 |
| Premier League | Ipswich | 1346.0437 | 1477.9410 | +131.90 |
| La Liga | Santander | 1480.1324 | 1435.5216 | −44.61 |
| La Liga | Deportivo | 1520.0488 | 1473.9450 | −46.10 |
| La Liga | Málaga | 1461.2584 | 1414.4245 | −46.83 |
| Bundesliga | Elversberg | 1523.7811 | 1479.2218 | −44.56 |
| Bundesliga | SC Paderborn | 1503.1130 | 1457.8959 | −45.22 |
| Bundesliga | Schalke 04 | 1436.8216 | 1461.8026 | +24.98 |
| Ligue 1 | Le Mans | 1506.2306 | 1487.4289 | −18.80 |
| Ligue 1 | Troyes | 1325.9912 | 1450.0825 | +124.09 |

Il segno del delta non e' sistematico perche' nel main chi entrava a inizio stagione partiva da un `I` vuoto o minuscolo (seed ~1400–1500), mentre nel ramo parte dalla media dei 15–17 incumbent (seed ~1445–1584). Le 129 squadre non entranti cambiano per propagazione dagli ingressi e per il fatto che il seed degli ingressi delle stagioni precedenti cambia la loro base di rating.

### 9.3 Top Mix A/B main-vs-branch

Comando identico sulle due colonne, snapshot `origin/main`, finestra 2026-08-30 → 2026-10-06, fixture `csv`, modello `Attuale`:

```
.venv/bin/python SoccerMath/replay_legacy_topmix.py --from 2026-08-30 --to 2026-10-06 \
  --fixtures csv --model current --ref origin/main --out <out> --snapshot-cache /tmp/snapcache
```

| Esito | main `9957f41` | ramo roster |
|---|---|---|
| OK | leak check **OK** | leak check **OK** |
| OK | finestra dichiarata ricostruibile **OK** | finestra dichiarata ricostruibile **OK** |
| OK | 104 click simulati | 104 click simulati |
| OK | 79 righe modello Attuale | 79 righe modello Attuale |
| OK | 0 righe modello Legacy (nessuna partita sopra soglia) | 0 righe modello Legacy |

| Esito | main `9957f41` | ramo roster |
|---|---|---|
| OK | 59/79 = **74.68%** (IC95 Wald [65.09%; 84.27%]) | 58/79 = **73.42%** (IC95 Wald [63.68%; 83.16%]) |

Il confronto riga per riga:

| controllo | esito |
|---|---|
| Insieme di partite e mercati selezionati | 79 in entrambe le colonne |
| Righe presenti solo nel main | 2 — `Ipswich-Liverpool 2` (71.4%, ✅), `Man United-Ipswich 1` (83.7%, ✅) |
| Righe presenti solo nel ramo | 2 — `Lille-Troyes 1` (65.9%, ✅), `Le Mans-Lens 2` (55.8%, ❌) |
| Probabilita' diverse sulle 77 righe comuni | 32 (scarto massimo **6.0 punti**), delta massimo di rank 2 |
| Esiti diversi sulle 77 righe comuni | 0 |

Delta complessivo **−1.27 punti percentuali (−1 pick su 79)**. Test esatto di Fisher a due code sulle due hit rate: **p = 0.9288**, differenza non significativa; il rank si sposta al massimo di 2 posizioni e le due selezioni che escono sono in Premier League (le due entranti Ipswich e Coventry pesano di piu' nel ramo) mentre quelle che entrano sono in Ligue 1 (Troyes e Le Mans, che nel main avevano seed troppo alti).

## 10. Riproducibilita' e file

Comando unico:
```
.venv/bin/python audit/elo_drift_triage.py
```

Script: `audit/elo_drift_triage.py`. Report: `audit/results/elo_drift_triage.md`. Artefatti pesanti: `audit/output/elo_drift_triage_per_match.csv.gz`, `elo_drift_triage_entries.csv`, `elo_drift_triage_metrics.csv`, `elo_drift_triage_drift.csv`; sono rigenerabili e ignorati da git.

