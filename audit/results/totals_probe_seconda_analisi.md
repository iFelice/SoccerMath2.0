# Seconda sonda totals — analisi offline

## Regola preregistrata (prima dei risultati)

Si considerano solo gli eventi NON INIZIATI con calcio d'inizio entro 7 giorni
dopo la chiamata: un evento con `commence_time` ≤ istante della chiamata è già
iniziato (come nella produzione delle quote 1X2) e viene escluso e contato a
parte. La regola (a)(b)(c) si applica solo agli eventi non iniziati.

- **(a) Copertura:** passa se almeno l'85% degli eventi ha una linea totals utilizzabile: Pinnacle con qualunque linea oppure almeno 3 bookmaker con la linea 2,5.
- **(b) Concordanza:** sugli eventi con Pinnacle su una linea diversa da 2,5 e almeno 3 altri bookmaker con la 2,5, si confrontano le due griglie. Passa se la mediana della differenza assoluta su P(Over 2,5) è ≤ 1,5 punti percentuali e il 90° percentile è ≤ 3 punti, con almeno 20 eventi confrontabili. Con meno di 20 eventi l'esito è «non decidibile».
- **(c) Proposta:** totals con fit generalizzato è proponibile per la produzione solo se (a) e (b) passano entrambe.

La regola non si applica allo snapshot del 10/10. Le differenze sono assolute; il 90° percentile usa il quantile lineare di NumPy. La linea di un bookmaker, se multipla, è la più bassa linea valida. Il fit usa la terna 1X2 Pinnacle de-vigata proporzionalmente e, per la griglia di consenso, la mediana delle probabilità 2,5 degli altri bookmaker de-vigate proporzionalmente.

## Snapshot e fonti

- Snapshot analizzato: `/home/runner/work/SoccerMath2.0/SoccerMath2.0/audit/data/totals_probe/2026-10-16_1320` (un solo run).
- Ultima chiamata totals: `2026-10-16T13:20:26Z`.
- Snapshot 1X2 Pinnacle: `2026-10-16T13:17:55Z` — file `/home/runner/work/SoccerMath2.0/SoccerMath2.0/SoccerMath/database/live_odds.json` (prima analisi: pin appena registrato, commit fff0fa52 della storia git); abbinamento per id evento.
- Eventi già iniziati alla chiamata (`commence_time` ≤ istante della chiamata): **0** — esclusi dall'analisi, come nella produzione delle quote 1X2.
- Eventi entro 7 giorni senza terna 1X2 Pinnacle utilizzabile: 0.

## Risultati

### (a) Copertura

| eventi nella finestra | con linea utilizzabile | copertura | soglia | esito |
|---:|---:|---:|---:|---|
| 49 | 49 | 100,00% | 85% | PASSA |

### (b) Concordanza

| confrontabili | mediana | 90° percentile | soglie | esito |
|---:|---:|---:|---|---|
| 40 | 0,75 pt | 1,47 pt | ≤1,5 pt / ≤3 pt; n≥20 | PASSA |

### (c) Proponibilità

**PROPONIBILE** (serve il superamento congiunto di (a) e (b)).

- Pacchetti pinnati senza terna 1X2 Pinnacle (esclusi dai confrontabili): **0**

### Eventi confrontabili

| evento | lega | linea Pinnacle | altri libri a 2,5 | P(Over 2,5) griglia Pinnacle | P(Over 2,5) griglia consenso | differenza assoluta |
|---|---|---:|---:|---:|---:|---:|
| Everton – Chelsea | Premier League | 2.75 | 13 | 57,88% | 57,18% | 0,70 pt |
| Brentford – Liverpool | Premier League | 3 | 7 | 61,84% | 60,75% | 1,09 pt |
| Fulham – Hull City | Premier League | 2.75 | 17 | 54,56% | 54,55% | 0,01 pt |
| Manchester City – Ipswich Town | Premier League | 3.5 | 3 | 69,16% | 68,97% | 0,19 pt |
| Newcastle United – Aston Villa | Premier League | 3 | 12 | 59,49% | 58,87% | 0,62 pt |
| Brighton and Hove Albion – Crystal Palace | Premier League | 3 | 10 | 60,67% | 60,45% | 0,22 pt |
| Leeds United – Manchester United | Premier League | 3 | 13 | 58,52% | 57,59% | 0,93 pt |
| Tottenham Hotspur – Coventry City | Premier League | 3 | 13 | 61,35% | 60,11% | 1,24 pt |
| Le Mans FC – Toulouse | Ligue 1 | 2.75 | 12 | 59,87% | 57,91% | 1,96 pt |
| Strasbourg – Paris Saint Germain | Ligue 1 | 3.5 | 3 | 71,50% | 71,18% | 0,32 pt |
| Lille – Brest | Ligue 1 | 2.75 | 13 | 57,31% | 56,30% | 1,01 pt |
| Troyes – RC Lens | Ligue 1 | 3 | 12 | 60,67% | 60,47% | 0,20 pt |
| Angers – Marseille | Ligue 1 | 3 | 12 | 59,89% | 59,54% | 0,35 pt |
| Paris FC – Rennes | Ligue 1 | 2.75 | 11 | 57,54% | 57,29% | 0,25 pt |
| Lyon – Nice | Ligue 1 | 2.75 | 12 | 58,11% | 57,30% | 0,80 pt |
| Eintracht Frankfurt – 1. FC Köln | Bundesliga | 3.5 | 3 | 73,14% | 71,89% | 1,25 pt |
| Elversberg – Augsburg | Bundesliga | 3.25 | 3 | 67,09% | 65,63% | 1,45 pt |
| Union Berlin – Borussia Dortmund | Bundesliga | 3.25 | 3 | 64,27% | 63,35% | 0,92 pt |
| FC Schalke 04 – FSV Mainz 05 | Bundesliga | 3 | 12 | 58,81% | 58,97% | 0,16 pt |
| Hamburger SV – VfB Stuttgart | Bundesliga | 3.5 | 3 | 69,28% | 68,18% | 1,10 pt |
| Werder Bremen – SC Paderborn | Bundesliga | 3 | 3 | 62,42% | 62,41% | 0,01 pt |
| Bayern Munich – RB Leipzig | Bundesliga | 4.5 | 3 | 85,10% | 84,27% | 0,83 pt |
| Bayer Leverkusen – SC Freiburg | Bundesliga | 3.25 | 3 | 65,63% | 64,73% | 0,90 pt |
| Borussia Monchengladbach – TSG Hoffenheim | Bundesliga | 3.5 | 3 | 69,17% | 68,65% | 0,52 pt |
| Frosinone – Sassuolo | Serie A | 3.25 | 3 | 66,88% | 66,03% | 0,84 pt |
| Venezia – Napoli | Serie A | 2.75 | 15 | 54,79% | 55,64% | 0,86 pt |
| Bologna – Inter Milan | Serie A | 2.75 | 13 | 55,94% | 56,86% | 0,92 pt |
| AS Roma – Genoa | Serie A | 2.75 | 15 | 52,82% | 53,14% | 0,32 pt |
| Fiorentina – Como | Serie A | 2.75 | 12 | 57,77% | 57,11% | 0,66 pt |
| AC Milan – Atalanta BC | Serie A | 2.75 | 14 | 54,79% | 54,51% | 0,28 pt |
| Monza – Cagliari | Serie A | 2.25 | 16 | 45,36% | 45,77% | 0,41 pt |
| Parma – Torino | Serie A | 2 | 13 | 38,67% | 40,26% | 1,59 pt |
| Espanyol – Atlético Madrid | La Liga | 2.75 | 13 | 52,82% | 53,65% | 0,82 pt |
| Villarreal – Elche CF | La Liga | 3.25 | 3 | 65,11% | 64,83% | 0,27 pt |
| Real Betis – Barcelona | La Liga | 3.75 | 3 | 76,94% | 76,70% | 0,23 pt |
| CA Osasuna – Real Racing Club de Santander | La Liga | 2.75 | 11 | 58,44% | 56,61% | 1,83 pt |
| Celta Vigo – Alavés | La Liga | 2.25 | 13 | 41,72% | 42,57% | 0,86 pt |
| Málaga – Real Sociedad | La Liga | 2.75 | 13 | 53,86% | 53,58% | 0,28 pt |
| Real Madrid – Sevilla | La Liga | 3.25 | 3 | 68,22% | 67,97% | 0,24 pt |
| Getafe – Rayo Vallecano | La Liga | 2 | 9 | 35,00% | 37,97% | 2,98 pt |
