# Audit calibrazione GG/NG — quote reali multi-bookmaker (audit/data)

*Generato: 2026-09-10T22:09:37+00:00 — script sola lettura `audit/gg_ng_calibration.py`, nessuna modifica a SoccerMath/.*

**Campione**: 20 file JSON (5 leghe x 4 stagioni 2022/23-2025/26), 7102 righe quote, **7073 partite incrociate** con quota BTTS e risultato CSV. Accordo punteggi JSON vs CSV: 7073/7073 (100.0%).

## Metodo

- **Join**: chiave primaria `(squadra_casa_normalizzata, squadra_trasferta_normalizzata, stagione)`; normalizzazione con `team_aliases.clean_name()` + tabella locale di esonimi italiani (Oddsportal scrive "Marsiglia", "RB Lipsia", "Ath. Bilbao", ...: alias non competono a `team_aliases.py`, che non e' stato modificato). In un girone all'italiana la coppia orientata e' unica per stagione: nessun CSV del dataset presenta duplicati (verificato), e il caso e' comunque gestito.
- **Data**: conferma/disambiguazione secondaria con tolleranza ±1 giorno (fuso); mai chiave primaria — 4.183/7.102 record JSON (59%) hanno `match_date` nullo. Un record con data incompatibile con il CSV viene scartato (`date_mismatch`): e' tipicamente la copia di coppa con lo stesso orientamento della partita di campionato.
- **Coppie duplicate nella stessa stagione**: mai assegnate a caso. Unico caso del dataset: Spezia-Verona 2022/23 (presente anche in Coppa Italia). Risolto solo l'esemplare con data coerente col CSV; gli altri risultano **"non risolti automaticamente"** e sono elencati sotto.
- **Risultato mancante**: partite JSON senza `home_score`/`away_score` escluse e contate per file.
- **Quota**: `bet365` se presente e usabile, altrimenti primo bookmaker usabile nell'ordine dell'array (fallback). Non usabili: esiti in `blocked_outcomes`, quote assenti/non finite/<= 1.0.
- **De-vig**: normalizzazione proporzionale standard `1/quota / (1/q_yes + 1/q_no)` — lo stesso metodo del progetto per i mercati a 2 esiti (`backtest_experiment_all.devig_2way`; `diagnose_clv_pinnacle` non esiste nel repo).
- **Modello**: `app.get_full_poisson_two_heads` **importata** (non riscritta). Testa Totali (GG/NG) = `att0_pure`/`def0_pure` da **F_season** (`xg_archive.season_point_in_time_averages`, medie xG della sola stagione in corso al cutoff = data della partita) con shrinkage `_shrunk_ratio` (prior 6 partite) verso l'ancora = media di lega del dizionario F_season (`_league_mean_gate`); squadra senza partite nella stagione in corso -> fallback gol con shrinkage, identico al ramo a campione zero di `get_league_engine`. La testa 1X2 (att/def con forma ultime 5 e fattore mercato) e' ricostruita con fonte gol walk-forward: **non influisce su GG** (che dipende solo da att0_pure/def0_pure e dalle medie gol di lega).
- **Walk-forward**: nessuna partita usa statistiche che la includano o includano partite successive: lo stato (gol cumulati, forma, medie di lega) viene aggiornato **dopo** la previsione e F_season usa il cutoff point-in-time. Deviazione dichiarata: produzione usa le medie gol calcolate sull'intero DB; qui sono cumulative sulle sole partite precedenti (le prime partite di 2022/23 partono da medie non ancora informative — effetto da cold start).
- **ROI/edge**: puntata fissa 10; il modello scommette GG se `P_model(GG) - P_fair(GG) > soglia`, NG se `P_fair(GG) - P_model(GG) > soglia`; vincita sulla quota reale non de-vigata. Soglia primaria 0 = convenzione `EDGE_MIN` di `backtest_experiment_all.py` e dei `roi_*` di `diagnose_production_baseline.py`; sensibilita' a 2% e 5%.

## Copertura per file (lega x stagione)

| File | Righe | Con data | Senza risultato | Pair assente | Data in conflitto | Dup. non risolti | Quota mancante | **Incrociate** | Tasso incrocio |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `italy-serie-a_2022-2023_btts.json` | 381 | 150 | 0 | 0 | 0 | 1 | 0 | **380** | 99.7% |
| `italy-serie-a_2023-2024_btts.json` | 380 | 153 | 1 | 0 | 0 | 0 | 1 | **378** | 99.5% |
| `italy-serie-a_2024-2025_btts.json` | 380 | 155 | 1 | 0 | 0 | 0 | 0 | **379** | 99.7% |
| `italy-serie-a_2025-2026_btts.json` | 380 | 155 | 0 | 0 | 0 | 0 | 0 | **380** | 100.0% |
| `england-premier-league_2022-2023_btts.json` | 380 | 153 | 0 | 0 | 0 | 0 | 0 | **380** | 100.0% |
| `england-premier-league_2023-2024_btts.json` | 380 | 160 | 0 | 0 | 0 | 0 | 0 | **380** | 100.0% |
| `england-premier-league_2024-2025_btts.json` | 380 | 146 | 0 | 0 | 0 | 0 | 0 | **380** | 100.0% |
| `england-premier-league_2025-2026_btts.json` | 380 | 144 | 0 | 0 | 0 | 0 | 0 | **380** | 100.0% |
| `spain-laliga_2022-2023_btts.json` | 380 | 150 | 0 | 0 | 0 | 0 | 0 | **380** | 100.0% |
| `spain-laliga_2023-2024_btts.json` | 380 | 141 | 0 | 0 | 0 | 0 | 1 | **379** | 99.7% |
| `spain-laliga_2024-2025_btts.json` | 380 | 151 | 0 | 0 | 0 | 0 | 0 | **380** | 100.0% |
| `spain-laliga_2025-2026_btts.json` | 380 | 154 | 0 | 0 | 0 | 0 | 0 | **380** | 100.0% |
| `germany-bundesliga_2022-2023_btts.json` | 308 | 135 | 2 | 2 | 0 | 0 | 0 | **304** | 98.7% |
| `germany-bundesliga_2023-2024_btts.json` | 308 | 136 | 0 | 2 | 0 | 0 | 0 | **306** | 99.4% |
| `germany-bundesliga_2024-2025_btts.json` | 308 | 141 | 1 | 2 | 0 | 0 | 0 | **305** | 99.0% |
| `germany-bundesliga_2025-2026_btts.json` | 308 | 137 | 0 | 2 | 0 | 0 | 0 | **306** | 99.4% |
| `france-ligue-1_2022-2023_btts.json` | 380 | 148 | 0 | 0 | 0 | 0 | 0 | **380** | 100.0% |
| `france-ligue-1_2023-2024_btts.json` | 310 | 135 | 0 | 4 | 0 | 0 | 0 | **306** | 98.7% |
| `france-ligue-1_2024-2025_btts.json` | 309 | 137 | 0 | 4 | 0 | 0 | 0 | **305** | 98.7% |
| `france-ligue-1_2025-2026_btts.json` | 310 | 138 | 1 | 4 | 0 | 0 | 0 | **305** | 98.4% |

Totale: 7102 righe, 7073 incrociate (99.6%). Le righe non incrociate sono in gran parte partite di Coppa/altre divisioni catturate dallo scraping h2h di Oddsportal (squadre mai presenti nei CSV della lega: vedi lista sotto) o copie di coppa con data incompatibile.

## Bookmaker usato

Riga per riga nel sidecar `gg_ng_calibration.json` (campo `bookmaker`). Per file:

| File | bet365 (priorita') | Fallback | Bookmaker fallback usati |
|---|---:|---:|---:|
| `italy-serie-a_2022-2023_btts.json` | 370 | 10 | 888sport (10) |
| `italy-serie-a_2023-2024_btts.json` | 378 | 0 | - |
| `italy-serie-a_2024-2025_btts.json` | 378 | 1 | BetflagIT (1) |
| `italy-serie-a_2025-2026_btts.json` | 380 | 0 | - |
| `england-premier-league_2022-2023_btts.json` | 370 | 10 | 888sport (10) |
| `england-premier-league_2023-2024_btts.json` | 380 | 0 | - |
| `england-premier-league_2024-2025_btts.json` | 380 | 0 | - |
| `england-premier-league_2025-2026_btts.json` | 377 | 3 | 888sport (3) |
| `spain-laliga_2022-2023_btts.json` | 380 | 0 | - |
| `spain-laliga_2023-2024_btts.json` | 379 | 0 | - |
| `spain-laliga_2024-2025_btts.json` | 380 | 0 | - |
| `spain-laliga_2025-2026_btts.json` | 379 | 1 | 888sport (1) |
| `germany-bundesliga_2022-2023_btts.json` | 296 | 8 | 888sport (8) |
| `germany-bundesliga_2023-2024_btts.json` | 306 | 0 | - |
| `germany-bundesliga_2024-2025_btts.json` | 305 | 0 | - |
| `germany-bundesliga_2025-2026_btts.json` | 306 | 0 | - |
| `france-ligue-1_2022-2023_btts.json` | 370 | 10 | 888sport (10) |
| `france-ligue-1_2023-2024_btts.json` | 306 | 0 | - |
| `france-ligue-1_2024-2025_btts.json` | 305 | 0 | - |
| `france-ligue-1_2025-2026_btts.json` | 305 | 0 | - |

**Fallback totale: 43/7073 righe (0.6%)** — il bet365 e' presente e usabile in tutte le altre. Bookmaker fallback incontrati: 888sport (42), BetflagIT (1).

## Coppie duplicate nella stessa stagione — NON risolte automaticamente

| File | Coppia | Esemplari scartati | Motivo |
|---|---|---:|---|
| `italy-serie-a_2022-2023_btts.json` | Spezia - Verona | 1 | duplicato nella stessa stagione: tenuto solo l'esemplare con data coerente col CSV |

## Squadre in coppie mai incrociate (coppe / altre divisioni)

Squadre che compaiono nei file quote ma non esistono nei CSV della lega-stagione corrispondente (tipicamente partite di Coppa catturate dallo scraping h2h):

St Etienne (6), Metz (5), Rodez (4), Bochum (2), Dunkerque (2), Dusseldorf (2), Elversberg (2), Hamburg (2), Heidenheim (2), Nice (2), Paderborn (2), Reims (2), Stuttgart (2), Wolfsburg (2), Guingamp (1), Paris (1), Red Star (1)

## Calibrazione: modello vs mercato (Brier / LogLoss / hit-rate)

Mercato: P_fair(GG) de-vigata della quota scelta. Hit-rate: quota di previsioni corrette al cutoff 0.5. Brier/LogLoss su esito binario GG=1.

| Campione | n | Brier modello | Brier mercato | LogLoss modello | LogLoss mercato | Hit-rate modello | Hit-rate mercato | Prob. media modello | Prob. media mercato | Tasso reale GG |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Serie A** | 1517 | 0.2529 | 0.2489 | 0.7009 | 0.6910 | 51.2% | 53.5% | 49.0% | 49.1% | 49.8% |
| — 2022/23 | 380 | 0.2580 | 0.2495 | 0.7166 | 0.6922 | 47.9% | 54.5% | 48.0% | 50.4% | 50.3% |
| — 2023/24 | 378 | 0.2509 | 0.2493 | 0.6951 | 0.6918 | 50.5% | 51.1% | 48.9% | 49.6% | 52.4% |
| — 2024/25 | 379 | 0.2564 | 0.2475 | 0.7062 | 0.6881 | 48.3% | 55.7% | 49.9% | 49.2% | 51.5% |
| — 2025/26 | 380 | 0.2463 | 0.2493 | 0.6856 | 0.6917 | 57.9% | 52.6% | 49.4% | 47.2% | 45.3% |
| **Premier League** | 1520 | 0.2452 | 0.2436 | 0.6840 | 0.6802 | 57.2% | 56.1% | 55.8% | 54.4% | 56.6% |
| — 2022/23 | 380 | 0.2522 | 0.2487 | 0.6989 | 0.6905 | 53.2% | 51.3% | 52.5% | 52.0% | 51.6% |
| — 2023/24 | 380 | 0.2353 | 0.2363 | 0.6632 | 0.6655 | 60.8% | 60.3% | 55.9% | 55.3% | 61.6% |
| — 2024/25 | 380 | 0.2460 | 0.2452 | 0.6853 | 0.6838 | 57.9% | 56.1% | 57.8% | 56.1% | 57.4% |
| — 2025/26 | 380 | 0.2475 | 0.2440 | 0.6884 | 0.6811 | 57.1% | 56.6% | 57.1% | 54.2% | 56.1% |
| **La Liga** | 1519 | 0.2483 | 0.2433 | 0.6914 | 0.6796 | 54.1% | 56.7% | 48.6% | 48.7% | 52.6% |
| — 2022/23 | 380 | 0.2506 | 0.2442 | 0.7012 | 0.6815 | 53.2% | 57.4% | 46.6% | 47.7% | 50.3% |
| — 2023/24 | 379 | 0.2448 | 0.2417 | 0.6827 | 0.6764 | 55.9% | 58.8% | 49.3% | 48.9% | 49.3% |
| — 2024/25 | 380 | 0.2480 | 0.2457 | 0.6892 | 0.6845 | 55.5% | 55.3% | 48.8% | 47.8% | 54.2% |
| — 2025/26 | 380 | 0.2498 | 0.2417 | 0.6927 | 0.6762 | 51.8% | 55.3% | 49.9% | 50.6% | 56.6% |
| **Bundesliga** | 1221 | 0.2391 | 0.2370 | 0.6732 | 0.6667 | 59.8% | 60.2% | 59.7% | 57.2% | 59.9% |
| — 2022/23 | 304 | 0.2447 | 0.2427 | 0.6910 | 0.6785 | 58.9% | 57.9% | 59.3% | 56.1% | 58.9% |
| — 2023/24 | 306 | 0.2317 | 0.2277 | 0.6560 | 0.6477 | 62.4% | 66.0% | 59.3% | 57.0% | 61.8% |
| — 2024/25 | 305 | 0.2412 | 0.2377 | 0.6752 | 0.6681 | 57.4% | 57.0% | 60.2% | 57.1% | 57.0% |
| — 2025/26 | 306 | 0.2388 | 0.2398 | 0.6706 | 0.6726 | 60.5% | 59.8% | 60.1% | 58.6% | 61.8% |
| **Ligue 1** | 1296 | 0.2485 | 0.2453 | 0.6922 | 0.6837 | 54.1% | 56.4% | 54.8% | 53.1% | 55.2% |
| — 2022/23 | 380 | 0.2418 | 0.2444 | 0.6833 | 0.6818 | 59.2% | 55.0% | 57.1% | 52.5% | 58.2% |
| — 2023/24 | 306 | 0.2534 | 0.2470 | 0.7002 | 0.6872 | 50.0% | 56.2% | 53.4% | 52.5% | 53.9% |
| — 2024/25 | 305 | 0.2488 | 0.2436 | 0.6909 | 0.6803 | 53.4% | 57.4% | 53.3% | 53.7% | 57.0% |
| — 2025/26 | 305 | 0.2515 | 0.2463 | 0.6964 | 0.6858 | 52.5% | 57.4% | 54.8% | 53.9% | 50.8% |
| **AGGREGATO** | 7073 | 0.2471 | 0.2438 | 0.6888 | 0.6807 | 55.1% | 56.4% | 53.3% | 52.3% | 54.6% |

### Tabelle di calibrazione (bins di ou_gg_calibration.py) — aggregato

| Bucket P(GG) | n | P media modello | Tasso reale | P media mercato | Tasso reale mercato |
|---|---:|---:|---:|---:|---:|
| 0-40% | 194 | 36.6% | 46.9% | 37.5% | 42.3% |
| 40-45% | 645 | 42.9% | 47.6% | 42.9% | 45.5% |
| 45-50% | 1516 | 47.7% | 50.2% | 47.1% | 48.2% |
| 50-55% | 1827 | 52.5% | 53.8% | 52.4% | 54.0% |
| 55-60% | 1540 | 57.4% | 58.0% | 57.3% | 60.6% |
| 60-101% | 1351 | 63.4% | 61.2% | 63.4% | 67.5% |

## ROI / edge a puntata fissa

Il modello scommette il lato con edge positivo oltre la soglia; vincita a quota reale; stake 10. ROI = bankroll / totale puntato. Campioni con n < 30 scommesse non sono affidabili.

| Campione | Soglia edge | Scommesse | Win rate | ROI | Bankroll (unita') |
|---|---:|---:|---:|---:|---:|
| **Serie A** | 0% | 1517 | 47.5% | -8.03% | -121.8 |
| **Serie A** | 2% | 1038 | 46.2% | -9.59% | -99.5 |
| **Serie A** | 5% | 485 | 46.8% | -6.32% | -30.6 |
| **Premier League** | 0% | 1520 | 49.8% | -5.41% | -82.2 |
| **Premier League** | 2% | 1045 | 50.4% | -3.42% | -35.7 |
| **Premier League** | 5% | 493 | 47.5% | -6.63% | -32.7 |
| **La Liga** | 0% | 1519 | 46.3% | -9.40% | -142.8 |
| **La Liga** | 2% | 998 | 43.6% | -12.96% | -129.3 |
| **La Liga** | 5% | 419 | 40.8% | -14.71% | -61.6 |
| **Bundesliga** | 0% | 1221 | 52.8% | -4.52% | -55.2 |
| **Bundesliga** | 2% | 877 | 53.1% | -5.06% | -44.4 |
| **Bundesliga** | 5% | 461 | 52.3% | -6.52% | -30.1 |
| **Ligue 1** | 0% | 1296 | 47.8% | -9.08% | -117.7 |
| **Ligue 1** | 2% | 937 | 48.3% | -7.70% | -72.2 |
| **Ligue 1** | 5% | 470 | 50.4% | -2.66% | -12.5 |
| **AGGREGATO** | 0% | 7073 | 48.7% | -7.35% | -519.7 |
| **AGGREGATO** | 2% | 4895 | 48.2% | -7.79% | -381.1 |
| **AGGREGATO** | 5% | 2328 | 47.7% | -7.20% | -167.6 |

### ROI per stagione (soglia 0, aggregato)

| Stagione | Scommesse | Win rate | ROI |
|---|---:|---:|---:|
| 2022/23 | 1824 | 50.7% | -4.57% |
| 2023/24 | 1749 | 47.4% | -9.45% |
| 2024/25 | 1749 | 48.0% | -8.53% |
| 2025/26 | 1751 | 48.7% | -6.96% |

## Limiti dichiarati

1. **Coppie di coppa non datate**: una partita di Coppa con lo stesso orientamento di quella di campionato, senza `match_date` nel JSON e senza gemella datata nello stesso file, e' indistinguibile e verrebbe incrociata al campionato. La stima dell'effetto e' il tasso di `date_mismatch` tra righe datate (tabella copertura): e' un limite del dato, non del join.
2. **Cold start 2022/23**: il walk-forward parte dal DB vuoto (il progetto non conserva storico anteriore); le medie gol di lega e i fallback gol sono poco informativi nelle prime giornate. In produzione quelle medie usano l'intero DB disponibile oggi.
3. **xG rivisti**: l'archivio conserva gli xG Understat all'ultimo valore; una ricostruzione point-in-time usa xG potenzialmente piu' recenti di quelli visibili all'epoca (limite gia' documentato in `xg_archive.py`).
4. **Quote pre-match non timestampate**: i file non permettono di verificare l'istante esatto di raccozione della quota; si assume apertura/pre-chiusura oddsportal come da scraping.
5. Il ROI con soglia 0 e' la convenzione dei backtest del repo, NON una strategia consigliata: un edge calcolato sul de-vig di un solo bookmaker include il rumore di quotazione.

