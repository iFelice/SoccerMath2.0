# Motore live di produzione vs replica offline (testa Totali) — audit sola lettura

*Generato: 2026-09-14T10:46:14+00:00 — script `audit/diagnose_motore_live_vs_replica.py`, nessuna scrittura su SoccerMath/.*

## Oggetto e protocollo

I 4 audit precedenti camminano sui CSV con una REPLICA della logica di `app.get_league_engine()` che legge l'istantanea xG statica (`xg_*.json`), senza shrinkage e senza la sorgente point-in-time. Questo script chiama invece **direttamente il motore reale**:

1. `app.get_league_engine(camp_key)` eseguito letteralmente, una volta per ogni data di validation 2024/25 e test 2025/26, in versione point-in-time: i CSV della lega vengono troncati in memoria (intercettando `pd.read_csv`, nessuna scrittura) alle partite dei giorni precedenti, e il cutoff viene iniettato nella VERA `xg_archive.season_point_in_time_averages` (fonte **F_season**, politica `previous_day`). Quindi passano in produzione invariati **shrinkage** `_shrunk_ratio` (PRIOR_MATCHES=6), l'ancora di lega derivata dal dizionario F_season, il gate `_league_mean_gate`, il fallback gol pooled, la sanitizzazione e i fattori di forma 1X2.
2. Per ogni partita si chiama `app.get_full_poisson_two_heads()` (da cui la testa Totali usa `att0_pure/def0_pure`) e si leggono lambda home/away (clippati da `_clip_lambda`, range [exp(−6), exp(3)]), P(Over2.5) e P(GG).
3. Le predizioni live vengono allineate per (data, casa, trasferta) a quelle della replica modello B di `diagnose_form_totali.py` — la stessa base dati dei 4 audit — su 3504 partite.

## Conformita' (verificata, non dichiarata)

| Controllo | Esito |
|---|---:|
| Replica qui vs `diagnose_form_totali.run_models` modello B, max \|scarto\| P(Over) | 0.0e+00 |
| idem, max \|scarto\| P(GG) | 0.0e+00 |
| idem, max \|scarto\| lambda totale (casa+trasf.) | 0.0e+00 |
| Motore di probabilita' `app._poisson_market` vs `backtest.get_full_poisson` sugli stessi lambda | 2.4e-07 |
| Chiusura lambda→prob. del wrapper live (max errore interno) | 0.0e+00 |
| **Validazione harness: replay a oggi vs engine di produzione non patchato, max scarto su tutte le stats** | **0.0e+00** |
| Squadre-lato assenti nell'engine al cutoff (default neutri 1.0 del wrapper di produzione) | 14 |
| Chiamate a `get_league_engine` (una per data) | 1172 |
| Tempo totale replay | 223 s |

La riga di validazione harness e' il controllo chiave: a cutoff "oggi" (tutto lo storico visibile) il replay deve riprodurre la produzione bit-esatta. Lo scarto 0.0 e' quindi la prova che l'intercettazione di `pd.read_csv` e l'iniezione del cutoff non alterano la pipeline; ogni scarto che segue su date storiche e' reale, non un artefatto del replay. Il confronto tra i due motori Poisson (`app._poisson_market` vs `backtest_experiment_all.get_full_poisson`) sugli stessi lambda non e' nullo per ~2e-07: e' il diverso ordine di somma dei PMF (somma Python con generatore vs numpy), precisione di macchina, non differenza di logica.

I 14 casi di squadra-lato assente dal dizionario del motore al cutoff sono tutti e 14 neopromosse alla prima giornata di stagione (es. Parma, Venezia, Ipswich, Holstein Kiel nel 2024/25; Pisa, Amburgo, Oviedo nel 2025/26): non esistono ancora nel DB troncato e la produzione stessa, senza alcun intervento dell'audit, le tratta con ratio neutro 1.0 nel wrapper; non e' un artefatto del replay.

Parita' di universo dati tra engine reale e caricamento della replica (stato attuale, nessun troncamento):

| Lega | righe replica | righe engine | data max replica | data max engine |
|---|---:|---:|---|---|
| Serie A | 1557 | 1557 | 2026-09-13 | 2026-09-13 |
| Premier League | 1559 | 1559 | 2026-09-13 | 2026-09-13 |
| La Liga | 1570 | 1570 | 2026-09-13 | 2026-09-13 |
| Bundesliga | 1251 | 1251 | 2026-09-13 | 2026-09-13 |
| Ligue 1 | 1334 | 1334 | 2026-09-13 | 2026-09-13 |

Copertura della fonte F_season (squadra presente negli archivi point-in-time al cutoff, quindi att0_pure/def0_pure da xG stagionale; gli altri vanno al fallback gol pooled con shrinkage):

| Lega | split | n | entrambe in F_season | almeno una al fallback |
|---|---|---:|---:|---:|
| Serie A | 2024/25 | 380 | 97.4% | 2.6% |
| Serie A | 2025/26 | 380 | 97.4% | 2.6% |
| Premier League | 2024/25 | 380 | 97.4% | 2.6% |
| Premier League | 2025/26 | 380 | 97.4% | 2.6% |
| La Liga | 2024/25 | 380 | 97.4% | 2.6% |
| La Liga | 2025/26 | 380 | 97.4% | 2.6% |
| Bundesliga | 2024/25 | 306 | 97.1% | 2.9% |
| Bundesliga | 2025/26 | 306 | 97.1% | 2.9% |
| Ligue 1 | 2024/25 | 306 | 97.1% | 2.9% |
| Ligue 1 | 2025/26 | 306 | 97.1% | 2.9% |

## PASSO 0 — Scarti live vs replica, partita per partita

### Lambda home e away (clippati; riportato il massimo dei due lati)

| Scope | split | max | p99 | p95 | mediana | media | RMS | scarto=0 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **AGGREGATO** | val+test | 5.09e+00 | 2.53e+00 | 1.56e+00 | 4.75e-01 | 5.43e-01 | 7.24e-01 | 0.0% |
| **AGGREGATO** | 2024/25 | 5.09e+00 | 2.55e+00 | 1.61e+00 | 4.65e-01 | 5.54e-01 | 7.45e-01 | 0.0% |
| **AGGREGATO** | 2025/26 | 4.21e+00 | 2.50e+00 | 1.48e+00 | 4.80e-01 | 5.31e-01 | 7.03e-01 | 0.0% |
| Serie A | val+test | 4.54e+00 | 2.74e+00 | 1.56e+00 | 5.02e-01 | 5.75e-01 | 7.73e-01 | 0.0% |
| Serie A | 2024/25 | 4.54e+00 | 2.89e+00 | 1.58e+00 | 5.12e-01 | 5.89e-01 | 7.97e-01 | 0.0% |
| Serie A | 2025/26 | 4.21e+00 | 2.58e+00 | 1.49e+00 | 4.91e-01 | 5.62e-01 | 7.48e-01 | 0.0% |
| Premier League | val+test | 2.20e+00 | 1.82e+00 | 1.42e+00 | 4.31e-01 | 4.80e-01 | 6.16e-01 | 0.0% |
| Premier League | 2024/25 | 2.20e+00 | 1.88e+00 | 1.52e+00 | 4.55e-01 | 5.31e-01 | 6.79e-01 | 0.0% |
| Premier League | 2025/26 | 2.18e+00 | 1.61e+00 | 1.13e+00 | 3.93e-01 | 4.29e-01 | 5.46e-01 | 0.0% |
| La Liga | val+test | 3.15e+00 | 2.36e+00 | 1.46e+00 | 4.42e-01 | 4.72e-01 | 6.33e-01 | 0.0% |
| La Liga | 2024/25 | 2.90e+00 | 2.36e+00 | 1.54e+00 | 4.24e-01 | 4.62e-01 | 6.23e-01 | 0.0% |
| La Liga | 2025/26 | 3.15e+00 | 2.36e+00 | 1.35e+00 | 4.52e-01 | 4.82e-01 | 6.44e-01 | 0.0% |
| Bundesliga | val+test | 5.09e+00 | 3.10e+00 | 2.02e+00 | 6.12e-01 | 6.73e-01 | 8.94e-01 | 0.0% |
| Bundesliga | 2024/25 | 5.09e+00 | 3.31e+00 | 2.03e+00 | 5.98e-01 | 6.79e-01 | 9.17e-01 | 0.0% |
| Bundesliga | 2025/26 | 3.88e+00 | 2.81e+00 | 1.97e+00 | 6.24e-01 | 6.68e-01 | 8.70e-01 | 0.0% |
| Ligue 1 | val+test | 3.21e+00 | 2.34e+00 | 1.48e+00 | 4.61e-01 | 5.36e-01 | 7.03e-01 | 0.0% |
| Ligue 1 | 2024/25 | 3.03e+00 | 2.22e+00 | 1.49e+00 | 4.18e-01 | 5.30e-01 | 7.04e-01 | 0.0% |
| Ligue 1 | 2025/26 | 3.21e+00 | 2.46e+00 | 1.46e+00 | 4.89e-01 | 5.43e-01 | 7.03e-01 | 0.0% |

### Probabilita' P(Over 2.5)

| Scope | split | max | p99 | p95 | mediana | media | RMS | scarto=0 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **AGGREGATO** | val+test | 6.20e-01 | 4.51e-01 | 3.46e-01 | 1.22e-01 | 1.43e-01 | 1.77e-01 | 0.0% |
| **AGGREGATO** | 2024/25 | 5.63e-01 | 4.31e-01 | 3.47e-01 | 1.23e-01 | 1.43e-01 | 1.77e-01 | 0.0% |
| **AGGREGATO** | 2025/26 | 6.20e-01 | 4.58e-01 | 3.45e-01 | 1.21e-01 | 1.42e-01 | 1.77e-01 | 0.0% |
| Serie A | val+test | 5.42e-01 | 4.75e-01 | 3.79e-01 | 1.39e-01 | 1.61e-01 | 1.99e-01 | 0.0% |
| Serie A | 2024/25 | 5.42e-01 | 4.59e-01 | 3.49e-01 | 1.31e-01 | 1.55e-01 | 1.90e-01 | 0.0% |
| Serie A | 2025/26 | 5.12e-01 | 4.90e-01 | 4.01e-01 | 1.48e-01 | 1.68e-01 | 2.08e-01 | 0.0% |
| Premier League | val+test | 4.26e-01 | 3.48e-01 | 2.74e-01 | 1.01e-01 | 1.16e-01 | 1.43e-01 | 0.0% |
| Premier League | 2024/25 | 4.26e-01 | 3.51e-01 | 2.97e-01 | 1.14e-01 | 1.27e-01 | 1.54e-01 | 0.0% |
| Premier League | 2025/26 | 3.80e-01 | 3.17e-01 | 2.54e-01 | 8.73e-02 | 1.06e-01 | 1.31e-01 | 0.0% |
| La Liga | val+test | 3.79e-01 | 3.43e-01 | 2.72e-01 | 1.06e-01 | 1.19e-01 | 1.45e-01 | 0.0% |
| La Liga | 2024/25 | 3.79e-01 | 3.45e-01 | 2.65e-01 | 1.08e-01 | 1.19e-01 | 1.45e-01 | 0.0% |
| La Liga | 2025/26 | 3.48e-01 | 3.41e-01 | 2.72e-01 | 1.03e-01 | 1.19e-01 | 1.44e-01 | 0.0% |
| Bundesliga | val+test | 6.20e-01 | 4.99e-01 | 3.99e-01 | 1.59e-01 | 1.76e-01 | 2.14e-01 | 0.0% |
| Bundesliga | 2024/25 | 5.52e-01 | 4.82e-01 | 3.91e-01 | 1.59e-01 | 1.74e-01 | 2.11e-01 | 0.0% |
| Bundesliga | 2025/26 | 6.20e-01 | 5.37e-01 | 4.01e-01 | 1.59e-01 | 1.77e-01 | 2.16e-01 | 0.0% |
| Ligue 1 | val+test | 5.63e-01 | 4.16e-01 | 3.63e-01 | 1.29e-01 | 1.49e-01 | 1.82e-01 | 0.0% |
| Ligue 1 | 2024/25 | 5.63e-01 | 4.29e-01 | 3.70e-01 | 1.29e-01 | 1.50e-01 | 1.86e-01 | 0.0% |
| Ligue 1 | 2025/26 | 4.18e-01 | 4.09e-01 | 3.20e-01 | 1.29e-01 | 1.48e-01 | 1.78e-01 | 0.0% |

### Probabilita' P(GG)

| Scope | split | max | p99 | p95 | mediana | media | RMS | scarto=0 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **AGGREGATO** | val+test | 6.47e-01 | 4.66e-01 | 3.58e-01 | 1.16e-01 | 1.40e-01 | 1.77e-01 | 0.0% |
| **AGGREGATO** | 2024/25 | 6.47e-01 | 4.55e-01 | 3.49e-01 | 1.14e-01 | 1.37e-01 | 1.74e-01 | 0.0% |
| **AGGREGATO** | 2025/26 | 5.54e-01 | 4.66e-01 | 3.69e-01 | 1.18e-01 | 1.43e-01 | 1.80e-01 | 0.0% |
| Serie A | val+test | 5.54e-01 | 4.95e-01 | 4.05e-01 | 1.43e-01 | 1.68e-01 | 2.09e-01 | 0.0% |
| Serie A | 2024/25 | 4.53e-01 | 4.32e-01 | 3.67e-01 | 1.42e-01 | 1.60e-01 | 1.96e-01 | 0.0% |
| Serie A | 2025/26 | 5.54e-01 | 5.08e-01 | 4.41e-01 | 1.46e-01 | 1.77e-01 | 2.21e-01 | 0.0% |
| Premier League | val+test | 4.96e-01 | 3.63e-01 | 2.84e-01 | 9.43e-02 | 1.12e-01 | 1.42e-01 | 0.0% |
| Premier League | 2024/25 | 4.96e-01 | 3.89e-01 | 2.96e-01 | 1.02e-01 | 1.20e-01 | 1.51e-01 | 0.0% |
| Premier League | 2025/26 | 4.11e-01 | 3.35e-01 | 2.76e-01 | 8.41e-02 | 1.03e-01 | 1.32e-01 | 0.0% |
| La Liga | val+test | 5.34e-01 | 3.24e-01 | 2.67e-01 | 9.80e-02 | 1.13e-01 | 1.39e-01 | 0.0% |
| La Liga | 2024/25 | 3.62e-01 | 3.07e-01 | 2.42e-01 | 9.55e-02 | 1.08e-01 | 1.30e-01 | 0.0% |
| La Liga | 2025/26 | 5.34e-01 | 3.35e-01 | 2.94e-01 | 1.01e-01 | 1.17e-01 | 1.46e-01 | 0.0% |
| Bundesliga | val+test | 6.47e-01 | 5.52e-01 | 4.14e-01 | 1.85e-01 | 2.00e-01 | 2.38e-01 | 0.0% |
| Bundesliga | 2024/25 | 6.47e-01 | 5.79e-01 | 4.20e-01 | 1.81e-01 | 1.99e-01 | 2.40e-01 | 0.0% |
| Bundesliga | 2025/26 | 5.35e-01 | 4.77e-01 | 4.13e-01 | 1.90e-01 | 2.01e-01 | 2.36e-01 | 0.0% |
| Ligue 1 | val+test | 6.04e-01 | 3.41e-01 | 2.70e-01 | 9.53e-02 | 1.12e-01 | 1.41e-01 | 0.0% |
| Ligue 1 | 2024/25 | 6.04e-01 | 3.75e-01 | 2.52e-01 | 8.16e-02 | 1.03e-01 | 1.34e-01 | 0.0% |
| Ligue 1 | 2025/26 | 3.70e-01 | 3.35e-01 | 2.82e-01 | 1.08e-01 | 1.22e-01 | 1.47e-01 | 0.0% |

Livello medio predetto (aggregato 5 leghe):

| Evento | split | live media | replica media | frequenza reale |
|---|---|---:|---:|---:|
| Over 2.5 | 2024/25 | 0.5311 | 0.5133 | 0.5342 |
| Over 2.5 | 2025/26 | 0.5275 | 0.5002 | 0.5303 |
| GG/NG | 2024/25 | 0.5380 | 0.4536 | 0.5525 |
| GG/NG | 2025/26 | 0.5404 | 0.4427 | 0.5388 |

### Da dove nascono gli scarti (attribuzione sui ratio squadra)

Le medie-gol di lega (avg_h/avg_a, la base da cui parte ogni lambda) sono **bit-identiche** tra motore live e replica a ogni cutoff (max scarto 0.0e+00): il cammino sui CSV e' lo stesso. Gli scarti nascono tutti dai **ratio attacco/difesa** di `att0_pure/def0_pure`. Su 10 date campionate per lega (seed deterministico), ogni ratio squadra-stato viene scomposto in tre canali:

- **finestra/sorgente**: ratio F_season NON shrinkato (xG della sola stagione in corso al cutoff, dall'archivio point-in-time) meno il ratio della replica, che applica a TUTTO lo storico la singola istantanea `xg_*.json` (oggi: medie 2026/27 dopo 3 gare);
- **shrinkage**: effetto di `_shrunk_ratio` (PRIOR_MATCHES=6 verso la media di lega F_season) sul ratio point-in-time;
- **fallback**: squadre assenti da F_season, dove il live usa il pooled gol shrinkato su tutto il DB troncato e la replica il proprio rapporto gol running.

| Canale | n ratio-squadra | mediana scarto ratio | p95 | media |
|---|---:|---:|---:|---:|
| finestra/sorgente xG (F_season vs istantanea statica) | 960 | 0.354 | 0.898 | 0.401 |
| shrinkage PRIOR_MATCHES=6 | 960 | 0.059 | 0.382 | 0.103 |
| fallback gol pooled (~squadre senza F_season) | 268 | 0.118 | 0.537 | 0.203 |

Per lega, mediana |scarto ratio| dei tre canali (src / shr / fb):

| Lega | src mediana | shr mediana | fb mediana | fallback: n ratio |
|---|---:|---:|---:|---:|
| Serie A | 0.356 | 0.052 | 0.197 | 66 |
| Premier League | 0.273 | 0.062 | 0.242 | 47 |
| La Liga | 0.345 | 0.051 | 0.111 | 52 |
| Bundesliga | 0.439 | 0.081 | 0.313 | 47 |
| Ligue 1 | 0.386 | 0.057 | 0.172 | 56 |

Il canale dominante e' la **finestra/sorgente**: la replica valuta partite del 2024/25 e 2025/26 con ratio fotografati nell'autunno 2026 (stagione in corso, 3 gare), mentre il live usa gli xG reali della stagione di quella partita. Lo shrinkage pesa poco (mediana ~0.05) e agisce come stabilizzatore; il fallback interessa circa il 3% delle PARTITE (tabella copertura sopra).

## PASSO 1 — Murphy a 10 decili sul motore LIVE vs replica

Gli scarti del Passo 0 sono risultati non nulli, quindi si ripete la decomposizione esatta di `diagnose_bias_variance_totali.py` (stessa funzione `murphy`, stessi 10 decili a frequenza uguale) sulle probabilita' live. Versione grezza: come dimostrato nell'audit precedente, una calibrazione monotona lascia la Risoluzione invariata, quindi il confronto che decide il verdetto (RES) non dipende da beta.

### O/U2.5 — Over 2.5

**2024/25**

| Scope | sorgente | REL | RES | UNC | Brier | RES/UNC |
|---|---|---:|---:|---:|---:|---:|
| **AGGREGATO** | replica | 0.0259 | 0.0019 | 0.2488 | 0.2744 | 0.8% |
| **AGGREGATO** | LIVE | 0.0014 | 0.0066 | 0.2488 | 0.2438 | 2.7% |
| Serie A | replica | 0.0419 | 0.0036 | 0.2497 | 0.2896 | 1.4% |
| Serie A | LIVE | 0.0063 | 0.0058 | 0.2497 | 0.2507 | 2.3% |
| Premier League | replica | 0.0225 | 0.0050 | 0.2457 | 0.2634 | 2.0% |
| Premier League | LIVE | 0.0051 | 0.0020 | 0.2457 | 0.2482 | 0.8% |
| La Liga | replica | 0.0134 | 0.0068 | 0.2498 | 0.2572 | 2.7% |
| La Liga | LIVE | 0.0037 | 0.0118 | 0.2498 | 0.2416 | 4.7% |
| Bundesliga | replica | 0.0352 | 0.0038 | 0.2404 | 0.2738 | 1.6% |
| Bundesliga | LIVE | 0.0083 | 0.0154 | 0.2404 | 0.2341 | 6.4% |
| Ligue 1 | replica | 0.0543 | 0.0105 | 0.2469 | 0.2912 | 4.2% |
| Ligue 1 | LIVE | 0.0108 | 0.0152 | 0.2469 | 0.2424 | 6.2% |

**2025/26**

| Scope | sorgente | REL | RES | UNC | Brier | RES/UNC |
|---|---|---:|---:|---:|---:|---:|
| **AGGREGATO** | replica | 0.0231 | 0.0023 | 0.2491 | 0.2701 | 0.9% |
| **AGGREGATO** | LIVE | 0.0013 | 0.0046 | 0.2491 | 0.2452 | 1.9% |
| Serie A | replica | 0.0418 | 0.0035 | 0.2482 | 0.2900 | 1.4% |
| Serie A | LIVE | 0.0041 | 0.0032 | 0.2482 | 0.2490 | 1.3% |
| Premier League | replica | 0.0209 | 0.0041 | 0.2475 | 0.2659 | 1.6% |
| Premier League | LIVE | 0.0143 | 0.0095 | 0.2475 | 0.2530 | 3.8% |
| La Liga | replica | 0.0163 | 0.0116 | 0.2500 | 0.2538 | 4.7% |
| La Liga | LIVE | 0.0047 | 0.0073 | 0.2500 | 0.2461 | 2.9% |
| Bundesliga | replica | 0.0412 | 0.0047 | 0.2312 | 0.2686 | 2.0% |
| Bundesliga | LIVE | 0.0044 | 0.0064 | 0.2312 | 0.2291 | 2.8% |
| Ligue 1 | replica | 0.0271 | 0.0074 | 0.2493 | 0.2725 | 3.0% |
| Ligue 1 | LIVE | 0.0111 | 0.0145 | 0.2493 | 0.2454 | 5.8% |

### GG/NG — GG

**2024/25**

| Scope | sorgente | REL | RES | UNC | Brier | RES/UNC |
|---|---|---:|---:|---:|---:|---:|
| **AGGREGATO** | replica | 0.0329 | 0.0014 | 0.2472 | 0.2788 | 0.6% |
| **AGGREGATO** | LIVE | 0.0023 | 0.0017 | 0.2472 | 0.2482 | 0.7% |
| Serie A | replica | 0.0610 | 0.0108 | 0.2498 | 0.2987 | 4.3% |
| Serie A | LIVE | 0.0100 | 0.0039 | 0.2498 | 0.2562 | 1.6% |
| Premier League | replica | 0.0204 | 0.0063 | 0.2446 | 0.2571 | 2.6% |
| Premier League | LIVE | 0.0072 | 0.0047 | 0.2446 | 0.2471 | 1.9% |
| La Liga | replica | 0.0322 | 0.0009 | 0.2482 | 0.2785 | 0.3% |
| La Liga | LIVE | 0.0073 | 0.0076 | 0.2482 | 0.2475 | 3.1% |
| Bundesliga | replica | 0.0445 | 0.0076 | 0.2453 | 0.2822 | 3.1% |
| Bundesliga | LIVE | 0.0192 | 0.0241 | 0.2453 | 0.2405 | 9.8% |
| Ligue 1 | replica | 0.0427 | 0.0091 | 0.2453 | 0.2780 | 3.7% |
| Ligue 1 | LIVE | 0.0069 | 0.0043 | 0.2453 | 0.2479 | 1.8% |

**2025/26**

| Scope | sorgente | REL | RES | UNC | Brier | RES/UNC |
|---|---|---:|---:|---:|---:|---:|
| **AGGREGATO** | replica | 0.0272 | 0.0029 | 0.2485 | 0.2731 | 1.2% |
| **AGGREGATO** | LIVE | 0.0011 | 0.0023 | 0.2485 | 0.2469 | 0.9% |
| Serie A | replica | 0.0375 | 0.0014 | 0.2478 | 0.2845 | 0.5% |
| Serie A | LIVE | 0.0101 | 0.0101 | 0.2478 | 0.2479 | 4.1% |
| Premier League | replica | 0.0148 | 0.0025 | 0.2463 | 0.2603 | 1.0% |
| Premier League | LIVE | 0.0060 | 0.0049 | 0.2463 | 0.2473 | 2.0% |
| La Liga | replica | 0.0345 | 0.0119 | 0.2457 | 0.2683 | 4.9% |
| La Liga | LIVE | 0.0149 | 0.0117 | 0.2457 | 0.2488 | 4.7% |
| Bundesliga | replica | 0.0584 | 0.0051 | 0.2362 | 0.2908 | 2.2% |
| Bundesliga | LIVE | 0.0097 | 0.0085 | 0.2362 | 0.2383 | 3.6% |
| Ligue 1 | replica | 0.0186 | 0.0064 | 0.2500 | 0.2629 | 2.5% |
| Ligue 1 | LIVE | 0.0059 | 0.0044 | 0.2500 | 0.2513 | 1.7% |

### Bootstrap appaiato stratificato per lega (2000 ricampionamenti, seed deterministico)

Differenza **LIVE − replica** (aggregato 5 leghe); IC 95%.

| Evento | split | Δ(RES/UNC) | IC 95% | ΔBrier | IC 95% |
|---|---|---:|---|---:|---|
| O/U2.5 | 2024/25 | +1.90 p.p. | [+0.33; +3.62] p.p. | -0.0306 | [-0.0389; -0.0223] |
| O/U2.5 | 2025/26 | +0.91 p.p. | [-0.57; +2.52] p.p. | -0.0248 | [-0.0331; -0.0165] |
| GG/NG | 2024/25 | +0.10 p.p. | [-1.20; +1.37] p.p. | -0.0307 | [-0.0388; -0.0228] |
| GG/NG | 2025/26 | -0.21 p.p. | [-1.69; +1.21] p.p. | -0.0262 | [-0.0345; -0.0173] |

Replica Over: RES/UNC 0.8%/0.9% (val/test, come da audit precedente). LIVE Over: 2.7%/1.9%. GG LIVE: 0.7%/0.9% contro replica 0.6%/1.2%.

## Conclusione esplicita

**Passo 0.** La pipeline reale NON e' bit-identica alla replica, e la differenza non e' trascurabile partita per partita: mediana |scarto| 0.12 su P(Over) (p95 0.35, max 0.62) e 0.12 su P(GG) (p95 0.36). L'attribuzione sopra mostra che il motore e' esattamente lo stesso nei mezzi (medie-gol di lega, Poisson, clip, medie di bucket) ma usa una SORGENTE xG diversa e piu' corretta: i veri xG della stagione in corso al cutoff (F_season) con shrinkage, contro l'istantanea statica 2026/27 dopo 3 gare che la replica applica a tutto lo storico. Anche il livello ne guadagna: la media live (tabella sopra) cade quasi sulla frequenza reale, mentre la replica restava sotto di 2-10 punti percentuali.

**Passo 1.** La differenza ESISTE ma **non sposta il verdetto sulla pista 3**. La Risoluzione live di Over 2.5 e' circa il triplo della replica, 2.7%/1.9% dell'incertezza contro 0.8%/0.9%; il delta bootstrap (LIVE−replica, stratificato per lega, appaiato) e' [+0.33; +3.62] punti percentuali in validation (esclude lo zero) e [-0.57; +2.52] nel test (include lo zero). Su nessuno dei due split il live si avvicina alla soglia di segnale sostanziale del 5%: nel test il 95% superiore e' 3.4%. GG/NG resta nella stessa fascia (0.7%/0.9%). 

Due precisazioni oneste, in positivo per il motore reale:

1. **Il difetto di livello della testa grezza evidenziato dall'audit di calibrazione era in gran parte un artefatto della replica statica.** Sul motore live l'Affidabilita' grezza e' gia' 0.0014/0.0013 (replica 0.0259/0.0231) e il Brier grezzo live 0.2438/0.2452 e' GIA' sotto il predittore costante (0.2488/0.2491): F_season + shrinkage, senza alcun beta, elimina quasi tutto il bias di livello. La beta calibration storica, derivata sulla replica, non e' il ritratto del motore reale.
2. **Qualche cella per-lega supera il 5%** in uno o entrambi gli split (es. Ligue 1 Over 6.2%/5.8%, Bundesliga 6.4%/2.8% val/test), ma e' rumore da sotto-potenza: il bootstrap appaiato per-lega (stesso metodo) mette gli IC 95% del delta per la Ligue 1 a [-6.5; +10.2]/[-5.8; +10.7] punti percentuali (val/test), e gli IC includono lo zero per tutte le 5 leghe in entrambi gli split (0/10 intervalli strettamente positivi). Nessun campionato sostiene dunque il 5% in modo statistico: sono isole su 306-380 partite, non un segnale poolizzato, e non fanno base per la pista 3.

### VERDETTO: **il motore live e' migliore della replica (soprattutto di livello, un po' di piu' di risoluzione) ma resta sostanzialmente equivalente ai fini della pista 3: nessun segnale da suddividere in bucket, la pista 3 rischia di aggiungere solo rumore.**

La differenza reale trovata al Passo 0 NON rovescia il verdetto: la risoluzione del motore vero e' 2-3% dell'incertezza (contro ~1% della replica), un miglioramento relativo reale ma ancora troppo piccolo per un ordinamento in bucket/selezioni robusto, e nel test statisticamente indistinguibile dalla replica. La raccomandazione si aggiorna invece su un punto: le conclusioni di livello dell'audit di calibrazione vanno rivalutate sul motore live (che e' gia' ben livellato senza beta), mentre la pista 3 resta senza base finche' una fonte con risoluzione propria non porta RES/UNC stabilmente sopra soglia su entrambi gli split e in aggregato.

## Limiti dichiarati

1. **Cutoff a giorno, non a minuto**: il replay usa la politica `previous_day` (tutte le partite del giorno della partita sono escluse, sia da F_season sia dal DB), come il pre-partita reale al mattino; risultati di anticipi dello stesso giorno non entrano. E' la scelta conservativa della produzione.
2. **Nessun beta refit live**: il Passo 1 decompone le sole probabilita' grezze live/replica; la Risoluzione e' invariante per trasformazioni monotone (verificato nel precedente audit), quindi il confronto decisivo non dipende dalla calibrazione.
3. **Ambiente bare-mode**: `app.py` e' importato fuori da `streamlit run` (cache `@st.cache_data` svuotata prima di ogni taglio storico); le funzioni chiamate sono quelle letterali di produzione, ma il rendering UI non e' eseguito nel suo contesto.
4. **Nessuna quota**: si decompone accuratezza probabilistica, non convenienza economica.
5. **Istantanea xG della replica e' mobile**: `xg_*.json` contiene le medie della stagione 2026/27 dopo 3 gare (stato dei file il giorno dell'audit); la replica le applica come costanti a 2024/25 e 2025/26. E' il disegno ereditato dai 4 audit precedenti: qui se ne misura per la prima volta la distanza dal motore reale, ma non lo si modifica.
6. **Attribuzione su campione**: i tre canali (sorgente/shrinkage/fallback) sono quantificati su 10 date campionate per lega con seed fisso (50 date-motore); le coperture F_season e gli scarti partita-per-partita del Passo 0 sono invece esaustivi.

## Riferimenti incrociati

- `audit/results/bias_variance_totali_diagnosis.md`: Murphy sulla replica, soglia 5% e verdetto pista 3 (oggetto del confronto);
- `audit/results/pt19_cap_vs_fseason_clean.md`: scelta della fonte F_season rispetto alla finestra PT19_CAP;
- `audit/results/calibration_layer_diagnosis.md`: beta live-level;
- `audit/results/form_totali_diagnosis.md`: modello B replicato.
