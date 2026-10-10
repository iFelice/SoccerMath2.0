## 4. Punto 4 — fit della griglia su una linea totals qualunque

Generato da `audit/linee_totali_probe.py` il 2026-10-10T19:37:34Z · linee e quote totals dalla sonda in `audit/data/totals_probe/` (2026-10-10T17:03Z) · terna 1X2 Pinnacle da `SoccerMath/database/live_odds.json` (2026-10-10T09:08:52Z) · nessuna nuova chiamata a The Odds API, nessuna chiave, nessuna modifica a `SoccerMath/`.

### 4.1 Estensione del fit (audit/griglia_core.py)

Il terzo vincolo del fit non è più la sola P(Over 2,5) ma la **probabilità giusta** di una linea qualsiasi, calcolata con le regole di pagamento del mercato:

| tipo di linea | regola | probabilità giusta usata nel fit |
|---|---|---|
| mezza (1,5 / 2,5 / 3,5) | vinta sopra la linea, persa sotto | P(gol totali > linea) |
| intera (2 / 3) | rimborso se i gol totali sono uguali alla linea | P(sopra) / (1 − P(uguale)) |
| a quarti (2,25 / 2,75) | mezza puntata su ciascuna delle due linee adiacenti | quota equa da EV nullo: p = W / (W + Lp) |

`W` = frazione di puntata che vince, `Lp` = frazione che perde, il resto è rimborsato. Con questa definizione p(sopra) + p(sotto) = 1 per ogni tipo di linea, quindi il de-vig a due vie è applicabile senza correzioni. Test di andata e ritorno su parametri noti per ogni tipo di linea: `audit/test_griglia_core_linee.py` (81 test; 96 in tutto insieme a `audit/test_griglia_core.py` e `audit/test_griglia_varianti.py`), residuo richiesto < 1e-9 e quote eque verificate con tabelle di profitto scritte a mano.

### 4.2 Verifica su dati reali

Eventi della sonda: **82**. Eventi con la terna 1X2 Pinnacle disponibile: **77** (aggancio per `id`). Eventi **confrontabili** (Pinnacle con linea ≠ 2,5 e almeno 3 altri libri con la 2,5): **42**.

| partita | lega | linea Pinnacle | tipo | libri a 2,5 | P(Over 2,5) A / B (%) | Δ Over 2,5 (pt) | Δ Gol (pt) | Δ Over 1,5 (pt) | residuo A |
|---|---|---|---|---|---|---|---|---|---|
| Manchester United – Tottenham Hotspur | Premier League | 2.25 | a quarti | 5 | 44.49 / 39.95 | 4.54 | 4.33 | 4.41 | 3e-17 |
| Parma – Torino | Serie A | 2 | intera | 8 | 38.70 / 42.08 | 3.38 | 3.23 | 3.41 | 6e-17 |
| Frosinone – Sassuolo | Serie A | 3 | intera | 6 | 61.45 / 58.70 | 2.76 | 2.41 | 2.05 | 1e-16 |
| Sassuolo – AC Milan | Serie A | 2.75 | a quarti | 13 | 54.90 / 53.33 | 1.57 | 1.41 | 1.26 | 1e-16 |
| Torino – Udinese | Serie A | 2.25 | a quarti | 14 | 43.71 / 45.14 | 1.44 | 1.34 | 1.35 | 6e-17 |
| Lyon – Nice | Ligue 1 | 2.75 | a quarti | 9 | 57.45 / 56.02 | 1.43 | 1.30 | 1.10 | 6e-17 |
| Nice – Strasbourg | Ligue 1 | 2.75 | a quarti | 10 | 57.31 / 55.89 | 1.43 | 1.25 | 1.11 | 1e-16 |
| Tottenham Hotspur – Coventry City | Premier League | 3 | intera | 8 | 61.16 / 59.74 | 1.41 | 1.31 | 1.03 | 1e-16 |
| FC Schalke 04 – FSV Mainz 05 | Bundesliga | 3 | intera | 10 | 60.66 / 59.25 | 1.41 | 1.23 | 1.05 | 2e-16 |
| Brest – Angers | Ligue 1 | 2.75 | a quarti | 10 | 57.99 / 56.58 | 1.41 | 1.25 | 1.09 | 0e+00 |
| Troyes – Marseille | Ligue 1 | 3 | intera | 8 | 60.96 / 59.62 | 1.35 | 1.19 | 0.99 | 1e-16 |
| Leeds United – Manchester United | Premier League | 3 | intera | 10 | 58.88 / 57.56 | 1.32 | 1.16 | 1.01 | 6e-17 |
| Real Racing Club de Santander – Valencia | La Liga | 2.75 | a quarti | 11 | 56.97 / 55.70 | 1.27 | 1.12 | 1.00 | 6e-17 |
| Lecce – Bologna | Serie A | 2.25 | a quarti | 12 | 44.04 / 45.27 | 1.22 | 1.14 | 1.14 | 6e-17 |
| Fiorentina – Como | Serie A | 2.75 | a quarti | 9 | 57.45 / 56.28 | 1.17 | 1.03 | 0.91 | 1e-16 |
| Venezia – Napoli | Serie A | 2.75 | a quarti | 10 | 56.64 / 55.53 | 1.12 | 1.01 | 0.87 | 6e-17 |
| Bologna – Inter Milan | Serie A | 2.75 | a quarti | 10 | 57.79 / 56.75 | 1.04 | 0.95 | 0.80 | 0e+00 |
| Getafe – Rayo Vallecano | La Liga | 2 | intera | 8 | 37.83 / 38.65 | 0.82 | 0.80 | 0.86 | 6e-17 |
| Brighton and Hove Albion – Crystal Palace | Premier League | 3 | intera | 9 | 61.35 / 60.56 | 0.79 | 0.72 | 0.58 | 1e-16 |
| Como – AS Roma | Serie A | 3 | intera | 10 | 59.20 / 58.46 | 0.74 | 0.65 | 0.56 | 1e-16 |
| Fulham – Hull City | Premier League | 2.75 | a quarti | 11 | 54.54 / 55.28 | 0.74 | 0.67 | 0.59 | 6e-17 |
| Monza – Cagliari | Serie A | 2.25 | a quarti | 9 | 46.21 / 45.68 | 0.54 | 0.50 | 0.49 | 1e-16 |
| Paris FC – Rennes | Ligue 1 | 2.75 | a quarti | 9 | 57.79 / 57.29 | 0.50 | 0.44 | 0.39 | 6e-17 |
| Real Sociedad – Deportivo La Coruña | La Liga | 2.75 | a quarti | 12 | 55.25 / 54.77 | 0.48 | 0.44 | 0.38 | 1e-16 |
| Levante – Sevilla | La Liga | 2.25 | a quarti | 12 | 46.35 / 46.79 | 0.44 | 0.41 | 0.40 | 6e-17 |
| Newcastle United – Aston Villa | Premier League | 3 | intera | 11 | 59.57 / 59.18 | 0.39 | 0.34 | 0.29 | 6e-17 |
| Lille – Brest | Ligue 1 | 2.75 | a quarti | 9 | 56.76 / 57.14 | 0.39 | 0.35 | 0.30 | 1e-16 |
| Everton – Chelsea | Premier League | 2.75 | a quarti | 11 | 57.68 / 58.06 | 0.38 | 0.34 | 0.29 | 6e-17 |
| CA Osasuna – Real Racing Club de Santander | La Liga | 2.75 | a quarti | 9 | 53.96 / 54.32 | 0.37 | 0.33 | 0.30 | 6e-17 |
| AS Monaco – Toulouse | Ligue 1 | 3 | intera | 8 | 60.96 / 60.62 | 0.34 | 0.31 | 0.25 | 1e-16 |
| SC Freiburg – FC Schalke 04 | Bundesliga | 2.75 | a quarti | 11 | 58.44 / 58.14 | 0.30 | 0.27 | 0.23 | 3e-17 |
| Espanyol – Atlético Madrid | La Liga | 2.75 | a quarti | 10 | 53.37 / 53.58 | 0.21 | 0.19 | 0.17 | 6e-17 |
| Coventry City – Newcastle United | Premier League | 2.75 | a quarti | 12 | 56.97 / 56.78 | 0.19 | 0.17 | 0.15 | 6e-17 |
| Le Mans FC – Toulouse | Ligue 1 | 2.75 | a quarti | 10 | 54.19 / 54.38 | 0.19 | 0.17 | 0.15 | 1e-16 |
| Angers – Marseille | Ligue 1 | 3 | intera | 9 | 59.77 / 59.95 | 0.18 | 0.16 | 0.13 | 6e-17 |
| Liverpool – Manchester City | Premier League | 3 | intera | 10 | 59.49 / 59.67 | 0.17 | 0.15 | 0.13 | 6e-17 |
| Troyes – RC Lens | Ligue 1 | 3 | intera | 9 | 60.86 / 60.76 | 0.10 | 0.09 | 0.07 | 6e-17 |
| Celta Vigo – Alavés | La Liga | 2.25 | a quarti | 9 | 44.92 / 44.97 | 0.06 | 0.06 | 0.06 | 6e-17 |
| AS Roma – Genoa | Serie A | 2.75 | a quarti | 9 | 57.79 / 57.84 | 0.05 | 0.05 | 0.04 | 2e-16 |
| AC Milan – Atalanta BC | Serie A | 2.75 | a quarti | 9 | 54.42 / 54.38 | 0.05 | 0.04 | 0.04 | 6e-17 |
| Málaga – Real Sociedad | La Liga | 2.75 | a quarti | 9 | 53.84 / 53.81 | 0.04 | 0.03 | 0.03 | 1e-16 |
| Real Betis – CA Osasuna | La Liga | 2.75 | a quarti | 12 | 54.44 / 54.42 | 0.02 | 0.02 | 0.02 | 6e-17 |

Differenze fra la griglia A (linea Pinnacle, fit generalizzato) e la griglia B (linea 2,5 degli altri libri), in valore assoluto:

| mercato | n | mediana | massimo |
|---|---|---|---|
| P(Over 2,5) | 42 | 0.64 pt | 4.54 pt |
| P(Gol) | 42 | 0.57 pt | 4.33 pt |
| P(Over 1,5) | 42 | 0.53 pt | 4.41 pt |

**Esito della regola dichiarata (P4.4): NON utilizzabile.** Mediana 0.64 pt (soglia ≤ 1.5) e massimo 4.54 pt (soglia ≤ 4) su 42 eventi.


### 4.3 Conteggio: quanti eventi avrebbero una linea utilizzabile

Linea utilizzabile = almeno una linea totals di un tipo gestito dal fit (mezza, intera o a quarti) da almeno un bookmaker, **e** la terna 1X2 Pinnacle per lo stesso evento (senza 1X2 il fit non esiste). Solo conteggio: l'ingresso di totals in produzione si decide su una sonda nuova.

| misura | tutti gli eventi | entro 7 giorni |
|---|---|---|
| eventi della sonda | 82 | 53 |
| con almeno una linea totals di tipo gestito | 82 | — |
| con la terna 1X2 Pinnacle | 77 | — |
| **con una linea UTILIZZABILE (entrambi)** | **77** | **51** |

Linee esposte da Pinnacle sugli 82 eventi (valori grezzi): **1.5** × 1, **2.0** × 2, **2.25** × 6, **2.5** × 14, **2.75** × 22, **3.0** × 16, **3.25** × 6, **3.5** × 5, **3.75** × 5, **4.5** × 2, **4.75** × 1; Pinnacle assente: 2.


### 4.4 Limiti

- La terna 1X2 viene da uno snapshot **8 ore prima** della sonda totals (`live_odds.json` 2026-10-10T09:08:52Z contro 2026-10-10T17:03Z): le quote 1X2 nel frattempo hanno potuto muoversi. La differenza misurata fra A e B include questo disallineamento, che agisce però nella stessa direzione sulle due griglie (la terna è identica).
- Snapshot unico: 42 eventi confrontabili su 82. Con meno di 10 eventi la regola dichiara «non decidibile», che è l'esito atteso su una sola giornata tipo.
- Il consenso 2,5 e' la mediana delle P(Over 2,5) de-vigate dei libri: libri con margini molto diversi pesano tutti allo stesso modo.
- De-vig proporzionale su tutte le fonti (P4.3): la scelta del de-vig non è oggetto di questo punto (lo è del punto 1).
- Nessuna conseguenza sulla produzione: totals non entra in produzione con questo audit e la regola dell'85% della PR #59 resta non superata.

