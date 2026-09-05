# Audit mapping nomi xG - 5 leghe, dati reali del repository

Nome canonico = `clean_name(nome CSV football-data)`, cioe' la chiave con cui `app.get_league_engine` e `models/elo_engine.py` indicizzano le squadre. Fonte unica di traduzione: `SoccerMath/team_names.py`.

**Sintesi:** 482/482 coppie (lega, stagione, squadra) risolte sul nome CSV corretto; 0 non risolte.

Stagioni analizzate: 2022, 2023, 2024, 2025, 2026 (stagione corrente: 2026, CSV `*_Live.csv`).

## Serie A

| Stagione | Squadre Understat | Squadre CSV | Corrispondenze | Alias espliciti | Collisioni | Non risolti |
|---|---|---|---|---|---|---|
| 2022 | 20 | 20 | 20/20 | 1 | 0 | 0 |
| 2023 | 20 | 20 | 20/20 | 1 | 0 | 0 |
| 2024 | 20 | 20 | 20/20 | 2 | 0 | 0 |
| 2025 | 20 | 20 | 20/20 | 2 | 0 | 0 |
| 2026 | 20 | 20 | 20/20 | 2 | 0 | 0 |

<details><summary>Alias e nomi CSV corrispondenti</summary>

| Titolo Understat | Nome canonico | Nomi grezzi nei CSV |
|---|---|---|
| `AC Milan` | `Milan` | `Milan` |
| `Atalanta` | `Atalanta` | `Atalanta` |
| `Bologna` | `Bologna` | `Bologna` |
| `Cagliari` | `Cagliari` | `Cagliari` |
| `Como` | `Como` | `Como` |
| `Cremonese` | `Cremonese` | `Cremonese` |
| `Empoli` | `Empoli` | `Empoli` |
| `Fiorentina` | `Fiorentina` | `Fiorentina` |
| `Frosinone` | `Frosinone` | `Frosinone` |
| `Genoa` | `Genoa` | `Genoa` |
| `Inter` | `Inter` | `Inter` |
| `Juventus` | `Juventus` | `Juventus` |
| `Lazio` | `Lazio` | `Lazio` |
| `Lecce` | `Lecce` | `Lecce` |
| `Monza` | `Monza` | `Monza` |
| `Napoli` | `Napoli` | `Napoli` |
| `Parma Calcio 1913` | `Parma` | `Parma` |
| `Pisa` | `Pisa` | `Pisa` |
| `Roma` | `Roma` | `Roma` |
| `Salernitana` | `Salernitana` | `Salernitana` |
| `Sampdoria` | `Sampdoria` | `Sampdoria` |
| `Sassuolo` | `Sassuolo` | `Sassuolo` |
| `Spezia` | `Spezia` | `Spezia` |
| `Torino` | `Torino` | `Torino` |
| `Udinese` | `Udinese` | `Udinese` |
| `Venezia` | `Venezia` | `Venezia` |
| `Verona` | `Verona` | `Verona` |

</details>

## Premier League

| Stagione | Squadre Understat | Squadre CSV | Corrispondenze | Alias espliciti | Collisioni | Non risolti |
|---|---|---|---|---|---|---|
| 2022 | 20 | 20 | 20/20 | 5 | 0 | 0 |
| 2023 | 20 | 20 | 20/20 | 5 | 0 | 0 |
| 2024 | 20 | 20 | 20/20 | 5 | 0 | 0 |
| 2025 | 20 | 20 | 20/20 | 5 | 0 | 0 |
| 2026 | 20 | 20 | 20/20 | 6 | 0 | 0 |

<details><summary>Alias e nomi CSV corrispondenti</summary>

| Titolo Understat | Nome canonico | Nomi grezzi nei CSV |
|---|---|---|
| `Arsenal` | `Arsenal` | `Arsenal` |
| `Aston Villa` | `Aston Villa` | `Aston Villa` |
| `Bournemouth` | `Bournemouth` | `Bournemouth` |
| `Brentford` | `Brentford` | `Brentford` |
| `Brighton` | `Brighton` | `Brighton`, `Brighton Hove` |
| `Burnley` | `Burnley` | `Burnley` |
| `Chelsea` | `Chelsea` | `Chelsea` |
| `Coventry` | `Coventry City` | `Coventry City` |
| `Crystal Palace` | `Crystal Palace` | `Crystal Palace` |
| `Everton` | `Everton` | `Everton` |
| `Fulham` | `Fulham` | `Fulham` |
| `Hull` | `Hull City` | `Hull City` |
| `Ipswich` | `Ipswich` | `Ipswich` |
| `Leeds` | `Leeds` | `Leeds`, `Leeds United` |
| `Leicester` | `Leicester` | `Leicester` |
| `Liverpool` | `Liverpool` | `Liverpool` |
| `Luton` | `Luton` | `Luton` |
| `Manchester City` | `Man City` | `Man City` |
| `Manchester United` | `Man United` | `Man United` |
| `Newcastle United` | `Newcastle` | `Newcastle` |
| `Nottingham Forest` | `Nott'm Forest` | `Nott'm Forest`, `Nottingham` |
| `Sheffield United` | `Sheffield United` | `Sheffield United` |
| `Southampton` | `Southampton` | `Southampton` |
| `Sunderland` | `Sunderland` | `Sunderland` |
| `Tottenham` | `Tottenham` | `Tottenham` |
| `West Ham` | `West Ham` | `West Ham` |
| `Wolverhampton Wanderers` | `Wolves` | `Wolves` |

</details>

## La Liga

| Stagione | Squadre Understat | Squadre CSV | Corrispondenze | Alias espliciti | Collisioni | Non risolti |
|---|---|---|---|---|---|---|
| 2022 | 20 | 20 | 20/20 | 8 | 0 | 0 |
| 2023 | 20 | 20 | 20/20 | 6 | 0 | 0 |
| 2024 | 20 | 20 | 20/20 | 8 | 0 | 0 |
| 2025 | 20 | 20 | 20/20 | 8 | 0 | 0 |
| 2026 | 20 | 20 | 20/20 | 10 | 0 | 0 |

<details><summary>Alias e nomi CSV corrispondenti</summary>

| Titolo Understat | Nome canonico | Nomi grezzi nei CSV |
|---|---|---|
| `Alaves` | `Alaves` | `Alaves`, `Alavés` |
| `Almeria` | `Almeria` | `Almeria` |
| `Athletic Club` | `Ath Bilbao` | `Ath Bilbao`, `Athletic` |
| `Atletico Madrid` | `Ath Madrid` | `Ath Madrid`, `Atleti` |
| `Barcelona` | `Barcelona` | `Barcelona`, `Barça` |
| `Cadiz` | `Cadiz` | `Cadiz` |
| `Celta Vigo` | `Celta` | `Celta` |
| `Deportivo La Coruna` | `Deportivo` | `Deportivo` |
| `Elche` | `Elche` | `Elche` |
| `Espanyol` | `Espanol` | `Espanol`, `Espanyol` |
| `Getafe` | `Getafe` | `Getafe` |
| `Girona` | `Girona` | `Girona` |
| `Granada` | `Granada` | `Granada` |
| `Las Palmas` | `Las Palmas` | `Las Palmas` |
| `Leganes` | `Leganes` | `Leganes` |
| `Levante` | `Levante` | `Levante` |
| `Malaga` | `Málaga` | `Málaga` |
| `Mallorca` | `Mallorca` | `Mallorca` |
| `Osasuna` | `Osasuna` | `Osasuna` |
| `Racing Santander` | `Santander` | `Santander` |
| `Rayo Vallecano` | `Vallecano` | `Rayo Vallecano`, `Vallecano` |
| `Real Betis` | `Betis` | `Betis` |
| `Real Madrid` | `Real Madrid` | `Real Madrid` |
| `Real Oviedo` | `Oviedo` | `Oviedo` |
| `Real Sociedad` | `Sociedad` | `Real Sociedad`, `Sociedad` |
| `Real Valladolid` | `Valladolid` | `Valladolid` |
| `Sevilla` | `Sevilla` | `Sevilla` |
| `Valencia` | `Valencia` | `Valencia` |
| `Villarreal` | `Villarreal` | `Villarreal` |

</details>

## Bundesliga

| Stagione | Squadre Understat | Squadre CSV | Corrispondenze | Alias espliciti | Collisioni | Non risolti |
|---|---|---|---|---|---|---|
| 2022 | 18 | 18 | 18/18 | 10 | 0 | 0 |
| 2023 | 18 | 18 | 18/18 | 10 | 0 | 0 |
| 2024 | 18 | 18 | 18/18 | 10 | 0 | 0 |
| 2025 | 18 | 18 | 18/18 | 12 | 0 | 0 |
| 2026 | 18 | 18 | 18/18 | 11 | 0 | 0 |

<details><summary>Alias e nomi CSV corrispondenti</summary>

| Titolo Understat | Nome canonico | Nomi grezzi nei CSV |
|---|---|---|
| `Augsburg` | `Augsburg` | `Augsburg` |
| `Bayer Leverkusen` | `Leverkusen` | `Leverkusen` |
| `Bayern Munich` | `Bayern` | `Bayern`, `Bayern Munich` |
| `Bochum` | `Bochum` | `Bochum` |
| `Borussia Dortmund` | `Dortmund` | `Dortmund` |
| `Borussia M.Gladbach` | `M'gladbach` | `M'gladbach` |
| `Darmstadt` | `Darmstadt` | `Darmstadt` |
| `Eintracht Frankfurt` | `Ein Frankfurt` | `Ein Frankfurt`, `Frankfurt` |
| `Elversberg` | `Elversberg` | `Elversberg` |
| `FC Cologne` | `Koln` | `FC Koln`, `Köln` |
| `FC Heidenheim` | `Heidenheim` | `Heidenheim` |
| `Freiburg` | `Freiburg` | `Freiburg` |
| `Hamburger SV` | `Hamburg` | `HSV`, `Hamburg` |
| `Hertha Berlin` | `Hertha` | `Hertha` |
| `Hoffenheim` | `Hoffenheim` | `Hoffenheim` |
| `Holstein Kiel` | `Holstein Kiel` | `Holstein Kiel` |
| `Mainz 05` | `Mainz` | `Mainz` |
| `Paderborn` | `SC Paderborn` | `SC Paderborn` |
| `RasenBallsport Leipzig` | `Leipzig` | `Leipzig`, `RB Leipzig` |
| `Schalke 04` | `Schalke 04` | `Schalke`, `Schalke 04` |
| `St. Pauli` | `St Pauli` | `St Pauli` |
| `Union Berlin` | `Union Berlin` | `Union Berlin` |
| `VfB Stuttgart` | `Stuttgart` | `Stuttgart` |
| `Werder Bremen` | `Werder Bremen` | `Bremen`, `Werder Bremen` |
| `Wolfsburg` | `Wolfsburg` | `Wolfsburg` |

</details>

## Ligue 1

| Stagione | Squadre Understat | Squadre CSV | Corrispondenze | Alias espliciti | Collisioni | Non risolti |
|---|---|---|---|---|---|---|
| 2022 | 20 | 20 | 20/20 | 2 | 0 | 0 |
| 2023 | 18 | 18 | 18/18 | 2 | 0 | 0 |
| 2024 | 18 | 18 | 18/18 | 2 | 0 | 0 |
| 2025 | 18 | 18 | 18/18 | 2 | 0 | 0 |
| 2026 | 18 | 18 | 18/18 | 2 | 0 | 0 |

<details><summary>Alias e nomi CSV corrispondenti</summary>

| Titolo Understat | Nome canonico | Nomi grezzi nei CSV |
|---|---|---|
| `Ajaccio` | `Ajaccio` | `Ajaccio` |
| `Angers` | `Angers` | `Angers` |
| `Auxerre` | `Auxerre` | `Auxerre` |
| `Brest` | `Brest` | `Brest` |
| `Clermont Foot` | `Clermont` | `Clermont` |
| `Le Havre` | `Le Havre` | `Le Havre` |
| `Le Mans` | `Le Mans` | `Le Mans` |
| `Lens` | `Lens` | `Lens` |
| `Lille` | `Lille` | `Lille` |
| `Lorient` | `Lorient` | `Lorient` |
| `Lyon` | `Lyon` | `Lyon`, `Olympique Lyon` |
| `Marseille` | `Marseille` | `Marseille` |
| `Metz` | `Metz` | `Metz` |
| `Monaco` | `Monaco` | `Monaco` |
| `Montpellier` | `Montpellier` | `Montpellier` |
| `Nantes` | `Nantes` | `Nantes` |
| `Nice` | `Nice` | `Nice` |
| `Paris FC` | `Paris` | `Paris`, `Paris FC` |
| `Paris Saint Germain` | `PSG` | `PSG`, `Paris SG` |
| `Reims` | `Reims` | `Reims` |
| `Rennes` | `Rennes` | `Rennes`, `Stade Rennais` |
| `Saint-Etienne` | `St Etienne` | `St Etienne` |
| `Strasbourg` | `Strasbourg` | `Strasbourg` |
| `Toulouse` | `Toulouse` | `Toulouse` |
| `Troyes` | `Troyes` | `Troyes` |

</details>

## Anomalie e note

- Nessuna anomalia: tutti i titoli Understat degli archivi si risolvono in un nome presente nei CSV della stessa stagione, senza collisioni.

## Controlli espliciti richiesti

| Nome in ingresso | Nome canonico risolto | Presente nella tabella esplicita |
|---|---|---|
| `Bayer Leverkusen` | `Leverkusen` | si |
| `Bayer 04 Leverkusen` | `Leverkusen` | si |
| `Leverkusen` | `Leverkusen` | si |
| `Borussia Dortmund` | `Dortmund` | si |
| `Dortmund` | `Dortmund` | si |
| `Borussia M.Gladbach` | `M'gladbach` | si |
| `M'gladbach` | `M'gladbach` | si |
| `Borussia Mönchengladbach` | `M'gladbach` | si |
| `FC Cologne` | `Koln` | si |
| `Köln` | `Koln` | si |
| `FC Koln` | `Koln` | si |
| `RasenBallsport Leipzig` | `Leipzig` | si |
| `RB Leipzig` | `Leipzig` | si |
| `Leipzig` | `Leipzig` | si |
| `VfB Stuttgart` | `Stuttgart` | si |
| `Stuttgart` | `Stuttgart` | si |
| `Athletic Club` | `Ath Bilbao` | si |
| `Athletic Bilbao` | `Ath Bilbao` | si |
| `Ath Bilbao` | `Ath Bilbao` | si |
| `Hull` | `Hull City` | si |
| `Hull City` | `Hull City` | si |
| `Coventry` | `Coventry City` | si |
| `Coventry City` | `Coventry City` | si |
| `St. Pauli` | `St Pauli` | si |
| `St Pauli` | `St Pauli` | si |
| `Saint-Etienne` | `St Etienne` | si |
| `St Etienne` | `St Etienne` | si |
| `Paris Saint Germain` | `PSG` | si |
| `Paris FC` | `Paris` | si |

