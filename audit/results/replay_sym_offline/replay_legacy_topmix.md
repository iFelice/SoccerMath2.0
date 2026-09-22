# Replay walk-forward Top Mix, due modelli (no-leakage)

Generato: 2026-09-20T19:34:36Z · finestra 2026-08-30 → 2026-09-20 · fixture: `csv` · ref snapshot: `origin/main` · modelli scritti: **Attuale + Legacy**

**Leak check complessivo: OK** · **finestra dichiarata ricostruibile: OK** · click simulati: 82 (scrivibili: 82) · righe destinate al Registro: 61 Attuale + 53 Legacy

Registro: {"scritto": false, "motivo": "dry-run offline, registro locale"}

- nota: finestra richiesta 2026-08-30 → 2026-09-20, limiti a istante [2026-08-30T11:27:06Z, 2026-09-18T21:51:58Z); primo istante onesto ricostruibile dal repo: 2026-08-30 (commit 48e7768, il primo con la stagione 2026/27 nei CSV live; prima di allora in git c'e' un'altra stagione)
- nota: 2 partite con kickoff incerto (mezzanotte UTC del giorno CSV, piu' conservativo): Levante-Ath Bilbao, Monaco-Lens
- nota: 26 fixture del pool con giornata dedotta dalle righe CSV vicine (offline)
- nota: 1496 fixture senza giornata: escluse dal pool da select_next_matchday_matches
- nota: 14 click con snapshot PRIVO dell'archivio xG (in git arriva il 01/09): la testa O/U ha usato il fallback, esattamente come la produzione con quei dati

## Click simulati

| T (UTC) | snapshot | commit time | bersagli | pool | selez. | sopra soglia att/leg | righe attuale | righe legacy | leak |
|---|---|---|---|---|---|---|---|---|---|
| 2026-08-30T12:59:59Z | `48e77686cd6d` | 2026-08-30T11:27:06Z | Paris-Nice (Ligue 1, 3-0)<br>Sunderland-Fulham (Premier League, 1-0)<br>Chelsea-Brighton (Premier League, 4-3)<br>Leeds-Brentford (Premier League, 1-1) | 1676 | 20 | 17/16 | Sunderland-Fulham UNDER_2.5 80.3% rank 5 ✅<br>Leeds-Brentford GG 68.4% rank 8 ✅<br>Chelsea-Brighton OVER_2.5 67.0% rank 9 ✅ | Sunderland-Fulham UNDER_2.5 80.3% rank 2 ✅<br>Leeds-Brentford GG 68.4% rank 7 ✅<br>Chelsea-Brighton OVER_2.5 67.0% rank 9 ✅ | OK |
| 2026-08-30T13:29:59Z | `5ff8911921a6` | 2026-08-30T13:22:15Z | Freiburg-Werder Bremen (Bundesliga, 4-1) | 1672 | 16 | 14/13 | Freiburg-Werder Bremen GG 62.1% rank 10 ✅ | Freiburg-Werder Bremen GG 62.1% rank 10 ✅ | OK |
| 2026-08-30T14:59:59Z | `5ff8911921a6` | 2026-08-30T13:22:15Z | Real Madrid-Málaga (La Liga, 4-0) | 1671 | 15 | 13/12 | Real Madrid-Málaga 1 82.9% rank 3 ✅ | Real Madrid-Málaga 1 78.5% rank 3 ✅ | OK |
| 2026-08-30T15:14:59Z | `5ff8911921a6` | 2026-08-30T13:22:15Z | Rennes-Le Mans (Ligue 1, 3-2) | 1670 | 14 | 12/11 | Rennes-Le Mans OVER_2.5 69.1% rank 5 ✅ | Rennes-Le Mans OVER_2.5 69.1% rank 4 ✅ | OK |
| 2026-08-30T15:29:59Z | `5ff8911921a6` | 2026-08-30T13:22:15Z | Augsburg-Schalke 04 (Bundesliga, 3-0)<br>Man United-Ipswich (Premier League, 5-2) | 1669 | 13 | 11/10 | Man United-Ipswich 1 83.7% rank 1 ✅<br>Augsburg-Schalke 04 1 56.8% rank 10 ✅ | Man United-Ipswich 1 79.0% rank 2 ✅<br>Augsburg-Schalke 04 1 58.8% rank 10 ✅ | OK |
| 2026-08-30T16:29:59Z | `8db1dafb038a` | 2026-08-30T15:34:10Z | Napoli-Como (Serie A, 1-2) | 1667 | 20 | 14/12 | — | — | OK |
| 2026-08-30T17:29:59Z | `8db1dafb038a` | 2026-08-30T15:34:10Z | Deportivo-Valencia (La Liga, 3-1) | 1666 | 19 | 14/12 | Deportivo-Valencia UNDER_2.5 64.9% rank 7 ❌ | Deportivo-Valencia UNDER_2.5 64.9% rank 7 ❌ | OK |
| 2026-08-30T18:44:59Z | `8db1dafb038a` | 2026-08-30T15:34:10Z | Monaco-Marseille (Ligue 1, 2-0)<br>Cagliari-Inter (Serie A, 0-1)<br>Lazio-Genoa (Serie A, 1-0) | 1665 | 18 | 13/11 | Cagliari-Inter 2 74.8% rank 5 ✅<br>Lazio-Genoa UNDER_2.5 61.2% rank 10 ✅<br>Monaco-Marseille GG 60.7% rank 11 ❌ | Cagliari-Inter 2 67.3% rank 6 ✅<br>Lazio-Genoa UNDER_2.5 61.2% rank 10 ✅<br>Monaco-Marseille GG 60.7% rank 11 ❌ | OK |
| 2026-08-30T19:29:59Z | `8db1dafb038a` | 2026-08-30T15:34:10Z | Celta-Ath Bilbao (La Liga, 0-2) | 1662 | 24 | 16/12 | Celta-Athletic Bilbao UNDER_2.5 64.7% rank 9 ✅ | Celta-Athletic Bilbao UNDER_2.5 64.7% rank 7 ✅ | OK |
| 2026-08-31T16:29:59Z | `decc891162c6` | 2026-08-31T01:51:19Z | Lecce-Roma (Serie A, 0-4) | 1661 | 23 | 17/14 | Lecce-Roma UNDER_2.5 62.3% rank 13 ❌ | Lecce-Roma UNDER_2.5 62.3% rank 11 ❌ | OK |
| 2026-08-31T17:29:59Z | `decc891162c6` | 2026-08-31T01:51:19Z | Osasuna-Getafe (La Liga, 1-0) | 1660 | 22 | 16/13 | Osasuna-Getafe UNDER_2.5 82.5% rank 3 ✅ | Osasuna-Getafe UNDER_2.5 82.5% rank 2 ✅ | OK |
| 2026-08-31T18:44:59Z | `2e447a7ec4cc` | 2026-08-31T18:27:28Z | Atalanta-Bologna (Serie A, 1-0) | 1659 | 21 | 15/12 | — | — | OK |
| 2026-08-31T18:59:59Z | `2e447a7ec4cc` | 2026-08-31T18:27:28Z | Aston Villa-Arsenal (Premier League, 0-1) | 1658 | 30 | 19/15 | Aston Villa-Arsenal 2 56.3% rank 18 ✅ | — | OK |
| 2026-08-31T19:29:59Z | `2e447a7ec4cc` | 2026-08-31T18:27:28Z | Barcelona-Vallecano (La Liga, 5-2) | 1657 | 39 | 26/22 | Barcelona-Vallecano 1 83.7% rank 2 ✅ | Barcelona-Vallecano 1 76.3% rank 4 ✅ | OK |
| 2026-09-03T18:44:59Z | `fb769b937d39` | 2026-09-03T15:19:54Z | Toulouse-Lille (Ligue 1, 0-1) | 1656 | 39 | 17/14 | — | — | OK |
| 2026-09-03T18:59:59Z | `fb769b937d39` | 2026-09-03T15:19:54Z | Sociedad-Celta (La Liga, 0-0) | 1655 | 38 | 17/14 | — | — | OK |
| 2026-09-04T16:59:59Z | `dc192d5eaa36` | 2026-09-04T16:50:17Z | Lyon-Auxerre (Ligue 1, 3-1) | 1654 | 47 | 21/17 | Lyon-Auxerre 1 65.8% rank 10 ✅ | Lyon-Auxerre 1 62.0% rank 11 ✅ | OK |
| 2026-09-04T18:29:59Z | `dc192d5eaa36` | 2026-09-04T16:50:17Z | Stuttgart-Koln (Bundesliga, 4-1) | 1653 | 46 | 20/16 | Stuttgart-Koln 1 76.2% rank 3 ✅ | Stuttgart-Koln 1 73.2% rank 3 ✅ | OK |
| 2026-09-04T18:44:59Z | `dc192d5eaa36` | 2026-09-04T16:50:17Z | Genoa-Como (Serie A, 1-4) | 1652 | 45 | 19/15 | — | — | OK |
| 2026-09-04T18:59:59Z | `dc192d5eaa36` | 2026-09-04T16:50:17Z | Betis-Real Madrid (La Liga, 1-0)<br>Ipswich-Liverpool (Premier League, 0-2) | 1651 | 44 | 19/15 | Ipswich-Liverpool 2 71.4% rank 6 ✅<br>Betis-Real Madrid 2 55.3% rank 19 ❌ | — | OK |
| 2026-09-04T19:04:59Z | `dc192d5eaa36` | 2026-09-04T16:50:17Z | PSG-Monaco (Ligue 1, 1-2) | 1649 | 42 | 17/15 | PSG-Monaco 1 67.4% rank 7 ❌ | PSG-Monaco 1 61.5% rank 10 ❌ | OK |
| 2026-09-05T11:29:59Z | `445c3af9fc8b` | 2026-09-05T10:34:13Z | Newcastle-Bournemouth (Premier League, 2-2) | 1648 | 41 | 16/14 | — | — | OK |
| 2026-09-05T12:59:59Z | `445c3af9fc8b` | 2026-09-05T10:34:13Z | Fiorentina-Torino (Serie A, 1-2) | 1647 | 40 | 16/14 | — | — | OK |
| 2026-09-05T13:29:59Z | `739b406ddf46` | 2026-09-05T13:16:50Z | Werder Bremen-Leipzig (Bundesliga, 3-1)<br>Leverkusen-Union Berlin (Bundesliga, 4-0)<br>Hoffenheim-Dortmund (Bundesliga, 2-3)<br>SC Paderborn-Freiburg (Bundesliga, 0-1)<br>M'gladbach-Elversberg (Bundesliga, 3-4) | 1646 | 39 | 16/14 | Leverkusen-Union Berlin 1 72.4% rank 4 ✅<br>Borussia Mönchengladbach-Elversberg GG 63.8% rank 8 ✅<br>Werder Bremen-Leipzig 2 57.6% rank 16 ❌ | Leverkusen-Union Berlin 1 67.9% rank 5 ✅<br>Borussia Mönchengladbach-Elversberg GG 63.8% rank 7 ✅ | OK |
| 2026-09-05T13:59:59Z | `739b406ddf46` | 2026-09-05T13:16:50Z | Man City-Coventry City (Premier League, 1-0)<br>Nott'm Forest-Tottenham (Premier League, 0-0)<br>Fulham-Crystal Palace (Premier League, 2-3)<br>Brentford-Sunderland (Premier League, 1-1)<br>Brighton-Leeds (Premier League, 1-1) | 1641 | 34 | 13/12 | Man City-Coventry City 1 82.6% rank 2 ✅ | Man City-Coventry City 1 78.8% rank 2 ✅ | OK |
| 2026-09-05T14:14:59Z | `bcb6b6099a6e` | 2026-09-05T14:04:27Z | Ath Bilbao-Ath Madrid (La Liga, 3-0) | 1636 | 29 | 12/11 | — | — | OK |
| 2026-09-05T15:14:59Z | `71127dc263ff` | 2026-09-05T14:19:14Z | Lens-Lorient (Ligue 1, 0-1) | 1635 | 28 | 12/11 | Lens-Lorient OVER_2.5 61.5% rank 7 ❌ | Lens-Lorient OVER_2.5 61.5% rank 7 ❌ | OK |
| 2026-09-05T15:59:59Z | `71127dc263ff` | 2026-09-05T14:19:14Z | Inter-Napoli (Serie A, 3-2) | 1634 | 27 | 11/10 | — | — | OK |
| 2026-09-05T16:29:59Z | `0695e9e611e4` | 2026-09-05T16:14:55Z | Schalke 04-Bayern (Bundesliga, 0-0)<br>Vallecano-Santander (La Liga, 3-2)<br>Hull City-Aston Villa (Premier League, 0-0) | 1633 | 26 | 8/8 | Schalke 04-Bayern 2 83.8% rank 1 ❌ | Schalke 04-Bayern 2 75.2% rank 1 ❌ | OK |
| 2026-09-05T18:44:59Z | `0695e9e611e4` | 2026-09-05T16:14:55Z | Nice-Le Mans (Ligue 1, 1-1)<br>Le Havre-Brest (Ligue 1, 1-2)<br>Roma-Atalanta (Serie A, 2-1) | 1630 | 23 | 7/7 | Nice-Le Mans GG 60.6% rank 6 ✅ | Nice-Le Mans GG 60.6% rank 6 ✅ | OK |
| 2026-09-05T18:59:59Z | `0695e9e611e4` | 2026-09-05T16:14:55Z | Villarreal-Deportivo (La Liga, 2-3) | 1627 | 20 | 6/6 | Villarreal-Deportivo 1 58.3% rank 6 ❌ | Villarreal-Deportivo 1 55.0% rank 6 ❌ | OK |
| 2026-09-06T12:59:59Z | `0e7560df1b50` | 2026-09-06T01:29:53Z | Troyes-Strasbourg (Ligue 1, 2-6)<br>Everton-Man United (Premier League, 2-2)<br>Frosinone-Venezia (Serie A, 3-2)<br>Parma-Monza (Serie A, 1-1) | 1626 | 19 | 5/5 | Everton-Man United GG 66.4% rank 3 ✅<br>Parma-Monza UNDER_2.5 60.7% rank 5 ✅ | Everton-Man United GG 66.4% rank 2 ✅<br>Parma-Monza UNDER_2.5 60.7% rank 5 ✅ | OK |
| 2026-09-06T13:29:59Z | `0e7560df1b50` | 2026-09-06T01:29:53Z | Hamburg-Mainz (Bundesliga, 0-5) | 1622 | 15 | 3/3 | — | — | OK |
| 2026-09-06T14:14:59Z | `0e7560df1b50` | 2026-09-06T01:29:53Z | Valencia-Barcelona (La Liga, 0-5) | 1621 | 14 | 3/3 | Valencia-Barcelona 2 69.4% rank 1 ✅ | Valencia-Barcelona 2 62.2% rank 3 ✅ | OK |
| 2026-09-06T15:14:59Z | `6a8bbb673394` | 2026-09-06T14:29:10Z | Angers-Rennes (Ligue 1, 1-2) | 1620 | 13 | 2/2 | — | — | OK |
| 2026-09-06T15:29:59Z | `6a8bbb673394` | 2026-09-06T14:29:10Z | Ein Frankfurt-Augsburg (Bundesliga, 1-4)<br>Arsenal-Chelsea (Premier League, 2-1) | 1619 | 12 | 2/2 | Eintracht Frankfurt-Augsburg GG 68.1% rank 1 ✅ | Eintracht Frankfurt-Augsburg GG 68.1% rank 1 ✅ | OK |
| 2026-09-06T15:59:59Z | `6a8bbb673394` | 2026-09-06T14:29:10Z | Bologna-Sassuolo (Serie A, 2-2) | 1617 | 29 | 14/13 | — | — | OK |
| 2026-09-06T16:29:59Z | `6a8bbb673394` | 2026-09-06T14:29:10Z | Málaga-Levante (La Liga, 0-0)<br>Alaves-Osasuna (La Liga, 5-2) | 1616 | 28 | 14/13 | — | — | OK |
| 2026-09-06T18:44:59Z | `6a8bbb673394` | 2026-09-06T14:29:10Z | Marseille-Paris (Ligue 1, 2-3)<br>Juventus-Milan (Serie A, 1-1) | 1614 | 26 | 14/13 | — | — | OK |
| 2026-09-06T18:59:59Z | `6a8bbb673394` | 2026-09-06T14:29:10Z | Espanol-Sevilla (La Liga, 1-1) | 1612 | 33 | 15/14 | — | — | OK |
| 2026-09-07T16:29:59Z | `e2d6ff1dd466` | 2026-09-07T01:28:09Z | Cagliari-Lecce (Serie A, 1-0) | 1611 | 32 | 15/14 | — | — | OK |
| 2026-09-07T16:59:59Z | `51f3059efa38` | 2026-09-07T16:43:51Z | Getafe-Celta (La Liga, 1-1) | 1610 | 31 | 15/14 | Getafe-Celta UNDER_2.5 62.5% rank 8 ✅ | Getafe-Celta UNDER_2.5 62.5% rank 7 ✅ | OK |
| 2026-09-07T18:44:59Z | `51f3059efa38` | 2026-09-07T16:43:51Z | Udinese-Lazio (Serie A, 1-2) | 1609 | 30 | 14/13 | — | — | OK |
| 2026-09-07T19:29:59Z | `51f3059efa38` | 2026-09-07T16:43:51Z | Elche-Sociedad (La Liga, 2-3) | 1608 | 39 | 17/15 | — | — | OK |
| 2026-09-11T18:29:59Z | `26fdb42833de` | 2026-09-11T12:34:46Z | Union Berlin-Schalke 04 (Bundesliga, 1-3) | 1607 | 48 | 20/17 | — | — | OK |
| 2026-09-11T18:44:59Z | `26fdb42833de` | 2026-09-11T12:34:46Z | Rennes-Marseille (Ligue 1, 1-0)<br>Venezia-Fiorentina (Serie A, 2-4) | 1606 | 47 | 20/17 | — | — | OK |
| 2026-09-11T18:59:59Z | `26fdb42833de` | 2026-09-11T12:34:46Z | Sevilla-Valencia (La Liga, 1-0) | 1604 | 45 | 20/17 | — | — | OK |
| 2026-09-12T11:59:59Z | `56779e32b964` | 2026-09-12T10:37:36Z | Santander-Alaves (La Liga, 2-1) | 1603 | 44 | 20/17 | — | — | OK |
| 2026-09-12T12:59:59Z | `56779e32b964` | 2026-09-12T10:37:36Z | Genoa-Frosinone (Serie A, 1-1) | 1602 | 43 | 20/17 | — | — | OK |
| 2026-09-12T13:29:59Z | `56779e32b964` | 2026-09-12T10:37:36Z | Freiburg-M'gladbach (Bundesliga, 5-0)<br>Hoffenheim-Stuttgart (Bundesliga, 2-1)<br>Mainz-Ein Frankfurt (Bundesliga, 1-3)<br>Augsburg-Leverkusen (Bundesliga, 2-2)<br>Dortmund-SC Paderborn (Bundesliga, 3-0) | 1601 | 42 | 20/17 | Dortmund-SC Paderborn 1 76.0% rank 3 ✅<br>Hoffenheim-Stuttgart OVER_2.5 70.1% rank 6 ✅<br>Augsburg-Leverkusen GG 67.0% rank 8 ✅<br>Freiburg-Borussia Mönchengladbach 1 60.3% rank 19 ✅ | Dortmund-SC Paderborn 1 76.2% rank 1 ✅<br>Hoffenheim-Stuttgart OVER_2.5 70.1% rank 3 ✅<br>Augsburg-Leverkusen GG 67.0% rank 5 ✅ | OK |
| 2026-09-12T13:59:59Z | `56779e32b964` | 2026-09-12T10:37:36Z | Bournemouth-Brentford (Premier League, 2-2)<br>Aston Villa-Nott'm Forest (Premier League, 1-2)<br>Chelsea-Hull City (Premier League, 2-2)<br>Crystal Palace-Ipswich (Premier League, 2-3)<br>Liverpool-Fulham (Premier League, 0-0) | 1596 | 37 | 16/14 | Crystal Palace-Ipswich GG 63.8% rank 6 ✅<br>Liverpool-Fulham 1 62.3% rank 10 ❌<br>Bournemouth-Brentford GG 60.4% rank 15 ✅ | Crystal Palace-Ipswich GG 63.8% rank 4 ✅<br>Bournemouth-Brentford GG 60.4% rank 10 ✅<br>Liverpool-Fulham 1 60.1% rank 11 ❌ | OK |
| 2026-09-12T14:14:59Z | `56779e32b964` | 2026-09-12T10:37:36Z | Osasuna-Espanol (La Liga, 0-2) | 1591 | 32 | 13/11 | — | — | OK |
| 2026-09-12T15:14:59Z | `aa84061d452c` | 2026-09-12T14:28:33Z | Strasbourg-Monaco (Ligue 1, 1-1) | 1590 | 31 | 13/11 | — | — | OK |
| 2026-09-12T15:59:59Z | `aa84061d452c` | 2026-09-12T14:28:33Z | Lazio-Milan (Serie A, 2-2) | 1589 | 30 | 13/11 | — | — | OK |
| 2026-09-12T16:29:59Z | `aa84061d452c` | 2026-09-12T14:28:33Z | Koln-Werder Bremen (Bundesliga, 1-1)<br>Ath Bilbao-Elche (La Liga, 1-1)<br>Tottenham-Everton (Premier League, 0-0) | 1588 | 29 | 13/11 | Koln-Werder Bremen GG 62.5% rank 7 ✅<br>Athletic Bilbao-Elche 1 59.4% rank 13 ❌ | Koln-Werder Bremen GG 62.5% rank 4 ✅<br>Athletic Bilbao-Elche 1 58.1% rank 10 ❌ | OK |
| 2026-09-12T18:44:59Z | `aa84061d452c` | 2026-09-12T14:28:33Z | Paris-Lyon (Ligue 1, 0-0)<br>Le Havre-Angers (Ligue 1, 0-0)<br>Auxerre-Nice (Ligue 1, 1-0)<br>Lorient-Toulouse (Ligue 1, 2-2)<br>Atalanta-Cagliari (Serie A, 1-2) | 1585 | 26 | 11/9 | — | — | OK |
| 2026-09-12T18:59:59Z | `aa84061d452c` | 2026-09-12T14:28:33Z | Real Madrid-Vallecano (La Liga, 4-1)<br>Sunderland-Arsenal (Premier League, 0-2) | 1580 | 21 | 11/9 | Real Madrid-Vallecano 1 77.9% rank 2 ✅<br>Sunderland-Arsenal 2 61.9% rank 10 ✅ | Sunderland-Arsenal 2 55.7% rank 9 ✅ | OK |
| 2026-09-13T11:59:59Z | `f6b56177690c` | 2026-09-13T01:36:13Z | Celta-Málaga (La Liga, 1-1) | 1578 | 19 | 9/8 | Celta-Málaga UNDER_2.5 62.4% rank 6 ✅ | Celta-Málaga UNDER_2.5 62.4% rank 4 ✅ | OK |
| 2026-09-13T12:59:59Z | `f6b56177690c` | 2026-09-13T01:36:13Z | Lille-Troyes (Ligue 1, 2-0)<br>Coventry City-Brighton (Premier League, 0-5)<br>Lecce-Monza (Serie A, 3-2) | 1577 | 18 | 8/7 | Coventry City-Brighton GG 62.1% rank 7 ❌ | Coventry City-Brighton GG 62.1% rank 5 ❌ | OK |
| 2026-09-13T13:29:59Z | `f6b56177690c` | 2026-09-13T01:36:13Z | Leipzig-Hamburg (Bundesliga, 5-0) | 1574 | 15 | 7/6 | Leipzig-Hamburg 1 68.5% rank 4 ✅ | Leipzig-Hamburg 1 58.7% rank 6 ✅ | OK |
| 2026-09-13T14:14:59Z | `f6b56177690c` | 2026-09-13T01:36:13Z | Levante-Barcelona (La Liga, 2-4) | 1573 | 14 | 6/5 | Levante-Barcelona 2 75.3% rank 2 ✅ | Levante-Barcelona 2 67.4% rank 2 ✅ | OK |
| 2026-09-13T15:14:59Z | `5b81d684d917` | 2026-09-13T15:09:41Z | Le Mans-Lens (Ligue 1, 2-2) | 1572 | 13 | 5/4 | — | — | OK |
| 2026-09-13T15:29:59Z | `5b81d684d917` | 2026-09-13T15:09:41Z | Elversberg-Bayern (Bundesliga, 1-2)<br>Man United-Man City (Premier League, 0-1) | 1571 | 12 | 5/4 | Elversberg-Bayern 2 73.1% rank 2 ✅<br>Man United-Man City GG 62.3% rank 4 ❌ | Elversberg-Bayern 2 66.7% rank 2 ✅<br>Man United-Man City GG 62.3% rank 3 ❌ | OK |
| 2026-09-13T15:59:59Z | `5b81d684d917` | 2026-09-13T15:09:41Z | Napoli-Bologna (Serie A, 1-0) | 1569 | 19 | 10/9 | — | — | OK |
| 2026-09-13T16:29:59Z | `5b81d684d917` | 2026-09-13T15:09:41Z | Getafe-Deportivo (La Liga, 1-1) | 1568 | 18 | 10/9 | — | — | OK |
| 2026-09-13T18:44:59Z | `5b81d684d917` | 2026-09-13T15:09:41Z | Brest-PSG (Ligue 1, 0-1)<br>Sassuolo-Juventus (Serie A, 3-2) | 1567 | 17 | 10/9 | — | — | OK |
| 2026-09-13T18:59:59Z | `5b81d684d917` | 2026-09-13T15:09:41Z | Sociedad-Ath Madrid (La Liga, 0-3) | 1565 | 24 | 10/9 | — | — | OK |
| 2026-09-14T16:29:59Z | `12f94e7d0de8` | 2026-09-14T01:54:49Z | Torino-Roma (Serie A, 0-2)<br>Como-Parma (Serie A, 2-1) | 1564 | 23 | 10/9 | Torino-Roma 2 63.3% rank 7 ✅ | — | OK |
| 2026-09-14T18:44:59Z | `70ad97670a22` | 2026-09-14T17:06:57Z | Inter-Udinese (Serie A, 5-3) | 1562 | 21 | 9/9 | Inter-Udinese 1 80.9% rank 2 ✅ | Inter-Udinese 1 72.5% rank 2 ✅ | OK |
| 2026-09-14T18:59:59Z | `70ad97670a22` | 2026-09-14T17:06:57Z | Villarreal-Betis (La Liga, 1-2)<br>Leeds-Newcastle (Premier League, 4-1) | 1561 | 30 | 11/11 | Villarreal-Betis OVER_2.5 61.1% rank 10 ✅ | Villarreal-Betis OVER_2.5 61.1% rank 9 ✅ | OK |
| 2026-09-15T16:59:59Z | `e1ee3719ca06` | 2026-09-15T10:32:41Z | Vallecano-Espanol (La Liga, 2-1) | 1559 | 47 | 20/18 | — | — | OK |
| 2026-09-15T17:59:59Z | `e1ee3719ca06` | 2026-09-15T10:32:41Z | Alaves-Valencia (La Liga, 0-1) | 1558 | 46 | 20/18 | — | — | OK |
| 2026-09-15T19:29:59Z | `e1ee3719ca06` | 2026-09-15T10:32:41Z | Elche-Real Madrid (La Liga, 2-3) | 1557 | 45 | 20/18 | Elche-Real Madrid 2 76.2% rank 4 ✅ | — | OK |
| 2026-09-15T23:59:59Z | `918ac0b61d89` | 2026-09-15T20:31:12Z | Levante-Ath Bilbao (La Liga, 0-0) | 1556 | 44 | 19/18 | — | — | OK |
| 2026-09-16T16:59:59Z | `67333b607cef` | 2026-09-16T12:01:43Z | Ath Madrid-Osasuna (La Liga, 4-0)<br>Deportivo-Sevilla (La Liga, 0-1) | 1555 | 43 | 19/18 | Atletico Madrid-Osasuna 1 66.8% rank 7 ✅ | Atletico Madrid-Osasuna 1 69.6% rank 5 ✅ | OK |
| 2026-09-16T19:29:59Z | `67333b607cef` | 2026-09-16T12:01:43Z | Barcelona-Santander (La Liga, 7-2) | 1553 | 41 | 18/17 | Barcelona-Racing Santander 1 86.6% rank 2 ✅ | Barcelona-Racing Santander 1 82.3% rank 2 ✅ | OK |
| 2026-09-17T16:59:59Z | `69f1d9597aec` | 2026-09-17T10:31:39Z | Betis-Getafe (La Liga, 1-0) | 1552 | 40 | 17/16 | Betis-Getafe 1 61.5% rank 13 ✅ | Betis-Getafe 1 59.8% rank 15 ✅ | OK |
| 2026-09-17T19:29:59Z | `69f1d9597aec` | 2026-09-17T10:31:39Z | Málaga-Villarreal (La Liga, 1-3) | 1551 | 39 | 16/15 | — | — | OK |
| 2026-09-17T23:59:59Z | `d446f2480d7c` | 2026-09-17T20:37:51Z | Monaco-Lens (Ligue 1, 2-1) | 1550 | 43 | 18/17 | — | — | OK |
| 2026-09-18T18:29:59Z | `5039d0f746fc` | 2026-09-18T15:17:03Z | Bayern-Union Berlin (Bundesliga, 7-0) | 1549 | 42 | 17/16 | Bayern-Union Berlin 1 89.0% rank 1 ✅ | Bayern-Union Berlin 1 86.2% rank 1 ✅ | OK (+1 righe future scartate) |
| 2026-09-18T18:44:59Z | `5039d0f746fc` | 2026-09-18T15:17:03Z | Monza-Sassuolo (Serie A, 2-1) | 1548 | 41 | 16/15 | — | — | OK (+1 righe future scartate) |
| 2026-09-18T18:59:59Z | `5039d0f746fc` | 2026-09-18T15:17:03Z | Espanol-Elche (La Liga, 1-3)<br>Brentford-Chelsea (Premier League, 3-0) | 1547 | 40 | 16/15 | Brentford-Chelsea GG 65.3% rank 6 ❌ | Brentford-Chelsea GG 65.3% rank 4 ❌ | OK (+1 righe future scartate) |

## Tabella leakage per click

| T | commit < T | bersaglio assente dal CSV | bersaglio assente da xG | cutoff xG = T | snapshot della stagione | righe future scartate | dettagli |
|---|---|---|---|---|---|---|---|
| 2026-08-30T12:59:59Z | True | True | True | True | True | — | — |
| 2026-08-30T13:29:59Z | True | True | True | True | True | — | — |
| 2026-08-30T14:59:59Z | True | True | True | True | True | — | — |
| 2026-08-30T15:14:59Z | True | True | True | True | True | — | — |
| 2026-08-30T15:29:59Z | True | True | True | True | True | — | — |
| 2026-08-30T16:29:59Z | True | True | True | True | True | — | — |
| 2026-08-30T17:29:59Z | True | True | True | True | True | — | — |
| 2026-08-30T18:44:59Z | True | True | True | True | True | — | — |
| 2026-08-30T19:29:59Z | True | True | True | True | True | — | — |
| 2026-08-31T16:29:59Z | True | True | True | True | True | — | — |
| 2026-08-31T17:29:59Z | True | True | True | True | True | — | — |
| 2026-08-31T18:44:59Z | True | True | True | True | True | — | — |
| 2026-08-31T18:59:59Z | True | True | True | True | True | — | — |
| 2026-08-31T19:29:59Z | True | True | True | True | True | — | — |
| 2026-09-03T18:44:59Z | True | True | True | True | True | — | — |
| 2026-09-03T18:59:59Z | True | True | True | True | True | — | — |
| 2026-09-04T16:59:59Z | True | True | True | True | True | — | — |
| 2026-09-04T18:29:59Z | True | True | True | True | True | — | — |
| 2026-09-04T18:44:59Z | True | True | True | True | True | — | — |
| 2026-09-04T18:59:59Z | True | True | True | True | True | — | — |
| 2026-09-04T19:04:59Z | True | True | True | True | True | — | — |
| 2026-09-05T11:29:59Z | True | True | True | True | True | — | — |
| 2026-09-05T12:59:59Z | True | True | True | True | True | — | — |
| 2026-09-05T13:29:59Z | True | True | True | True | True | — | — |
| 2026-09-05T13:59:59Z | True | True | True | True | True | — | — |
| 2026-09-05T14:14:59Z | True | True | True | True | True | — | — |
| 2026-09-05T15:14:59Z | True | True | True | True | True | — | — |
| 2026-09-05T15:59:59Z | True | True | True | True | True | — | — |
| 2026-09-05T16:29:59Z | True | True | True | True | True | — | — |
| 2026-09-05T18:44:59Z | True | True | True | True | True | — | — |
| 2026-09-05T18:59:59Z | True | True | True | True | True | — | — |
| 2026-09-06T12:59:59Z | True | True | True | True | True | — | — |
| 2026-09-06T13:29:59Z | True | True | True | True | True | — | — |
| 2026-09-06T14:14:59Z | True | True | True | True | True | — | — |
| 2026-09-06T15:14:59Z | True | True | True | True | True | — | — |
| 2026-09-06T15:29:59Z | True | True | True | True | True | — | — |
| 2026-09-06T15:59:59Z | True | True | True | True | True | — | — |
| 2026-09-06T16:29:59Z | True | True | True | True | True | — | — |
| 2026-09-06T18:44:59Z | True | True | True | True | True | — | — |
| 2026-09-06T18:59:59Z | True | True | True | True | True | — | — |
| 2026-09-07T16:29:59Z | True | True | True | True | True | — | — |
| 2026-09-07T16:59:59Z | True | True | True | True | True | — | — |
| 2026-09-07T18:44:59Z | True | True | True | True | True | — | — |
| 2026-09-07T19:29:59Z | True | True | True | True | True | — | — |
| 2026-09-11T18:29:59Z | True | True | True | True | True | — | — |
| 2026-09-11T18:44:59Z | True | True | True | True | True | — | — |
| 2026-09-11T18:59:59Z | True | True | True | True | True | — | — |
| 2026-09-12T11:59:59Z | True | True | True | True | True | — | — |
| 2026-09-12T12:59:59Z | True | True | True | True | True | — | — |
| 2026-09-12T13:29:59Z | True | True | True | True | True | — | — |
| 2026-09-12T13:59:59Z | True | True | True | True | True | — | — |
| 2026-09-12T14:14:59Z | True | True | True | True | True | — | — |
| 2026-09-12T15:14:59Z | True | True | True | True | True | — | — |
| 2026-09-12T15:59:59Z | True | True | True | True | True | — | — |
| 2026-09-12T16:29:59Z | True | True | True | True | True | — | — |
| 2026-09-12T18:44:59Z | True | True | True | True | True | — | — |
| 2026-09-12T18:59:59Z | True | True | True | True | True | — | — |
| 2026-09-13T11:59:59Z | True | True | True | True | True | — | — |
| 2026-09-13T12:59:59Z | True | True | True | True | True | — | — |
| 2026-09-13T13:29:59Z | True | True | True | True | True | — | — |
| 2026-09-13T14:14:59Z | True | True | True | True | True | — | — |
| 2026-09-13T15:14:59Z | True | True | True | True | True | — | — |
| 2026-09-13T15:29:59Z | True | True | True | True | True | — | — |
| 2026-09-13T15:59:59Z | True | True | True | True | True | — | — |
| 2026-09-13T16:29:59Z | True | True | True | True | True | — | — |
| 2026-09-13T18:44:59Z | True | True | True | True | True | — | — |
| 2026-09-13T18:59:59Z | True | True | True | True | True | — | — |
| 2026-09-14T16:29:59Z | True | True | True | True | True | — | — |
| 2026-09-14T18:44:59Z | True | True | True | True | True | — | — |
| 2026-09-14T18:59:59Z | True | True | True | True | True | — | — |
| 2026-09-15T16:59:59Z | True | True | True | True | True | — | — |
| 2026-09-15T17:59:59Z | True | True | True | True | True | — | — |
| 2026-09-15T19:29:59Z | True | True | True | True | True | — | — |
| 2026-09-15T23:59:59Z | True | True | True | True | True | — | — |
| 2026-09-16T16:59:59Z | True | True | True | True | True | — | — |
| 2026-09-16T19:29:59Z | True | True | True | True | True | — | — |
| 2026-09-17T16:59:59Z | True | True | True | True | True | — | — |
| 2026-09-17T19:29:59Z | True | True | True | True | True | — | — |
| 2026-09-17T23:59:59Z | True | True | True | True | True | — | — |
| 2026-09-18T18:29:59Z | True | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-18T18:44:59Z | True | True | True | True | True | {"LaLiga_Live.csv": 1} | — |
| 2026-09-18T18:59:59Z | True | True | True | True | True | {"LaLiga_Live.csv": 1} | — |

## Righe del modello attuale (Attuale) destinate al Registro

| data | lega | partita | mercato | prob | rank | esito | risultato | snapshot | salvato_il |
|---|---|---|---|---|---|---|---|---|---|
| 30/08/2026 15:00 | Premier League | Sunderland-Fulham | UNDER_2.5 | 80.3% | 5 | ✅ | 1-0 | `48e77686cd6d` | 30/08/2026 14:59 |
| 30/08/2026 15:00 | Premier League | Leeds-Brentford | GG | 68.4% | 8 | ✅ | 1-1 | `48e77686cd6d` | 30/08/2026 14:59 |
| 30/08/2026 15:00 | Premier League | Chelsea-Brighton | OVER_2.5 | 67.0% | 9 | ✅ | 4-3 | `48e77686cd6d` | 30/08/2026 14:59 |
| 30/08/2026 15:30 | Bundesliga | Freiburg-Werder Bremen | GG | 62.1% | 10 | ✅ | 4-1 | `5ff8911921a6` | 30/08/2026 15:29 |
| 30/08/2026 17:00 | La Liga | Real Madrid-Málaga | 1 | 82.9% | 3 | ✅ | 4-0 | `5ff8911921a6` | 30/08/2026 16:59 |
| 30/08/2026 17:15 | Ligue 1 | Rennes-Le Mans | OVER_2.5 | 69.1% | 5 | ✅ | 3-2 | `5ff8911921a6` | 30/08/2026 17:14 |
| 30/08/2026 17:30 | Premier League | Man United-Ipswich | 1 | 83.7% | 1 | ✅ | 5-2 | `5ff8911921a6` | 30/08/2026 17:29 |
| 30/08/2026 17:30 | Bundesliga | Augsburg-Schalke 04 | 1 | 56.8% | 10 | ✅ | 3-0 | `5ff8911921a6` | 30/08/2026 17:29 |
| 30/08/2026 19:30 | La Liga | Deportivo-Valencia | UNDER_2.5 | 64.9% | 7 | ❌ | 3-1 | `8db1dafb038a` | 30/08/2026 19:29 |
| 30/08/2026 20:45 | Serie A | Cagliari-Inter | 2 | 74.8% | 5 | ✅ | 0-1 | `8db1dafb038a` | 30/08/2026 20:44 |
| 30/08/2026 20:45 | Serie A | Lazio-Genoa | UNDER_2.5 | 61.2% | 10 | ✅ | 1-0 | `8db1dafb038a` | 30/08/2026 20:44 |
| 30/08/2026 20:45 | Ligue 1 | Monaco-Marseille | GG | 60.7% | 11 | ❌ | 2-0 | `8db1dafb038a` | 30/08/2026 20:44 |
| 30/08/2026 21:30 | La Liga | Celta-Athletic Bilbao | UNDER_2.5 | 64.7% | 9 | ✅ | 0-2 | `8db1dafb038a` | 30/08/2026 21:29 |
| 31/08/2026 18:30 | Serie A | Lecce-Roma | UNDER_2.5 | 62.3% | 13 | ❌ | 0-4 | `decc891162c6` | 31/08/2026 18:29 |
| 31/08/2026 19:30 | La Liga | Osasuna-Getafe | UNDER_2.5 | 82.5% | 3 | ✅ | 1-0 | `decc891162c6` | 31/08/2026 19:29 |
| 31/08/2026 21:00 | Premier League | Aston Villa-Arsenal | 2 | 56.3% | 18 | ✅ | 0-1 | `2e447a7ec4cc` | 31/08/2026 20:59 |
| 31/08/2026 21:30 | La Liga | Barcelona-Vallecano | 1 | 83.7% | 2 | ✅ | 5-2 | `2e447a7ec4cc` | 31/08/2026 21:29 |
| 04/09/2026 19:00 | Ligue 1 | Lyon-Auxerre | 1 | 65.8% | 10 | ✅ | 3-1 | `dc192d5eaa36` | 04/09/2026 18:59 |
| 04/09/2026 20:30 | Bundesliga | Stuttgart-Koln | 1 | 76.2% | 3 | ✅ | 4-1 | `dc192d5eaa36` | 04/09/2026 20:29 |
| 04/09/2026 21:00 | Premier League | Ipswich-Liverpool | 2 | 71.4% | 6 | ✅ | 0-2 | `dc192d5eaa36` | 04/09/2026 20:59 |
| 04/09/2026 21:00 | La Liga | Betis-Real Madrid | 2 | 55.3% | 19 | ❌ | 1-0 | `dc192d5eaa36` | 04/09/2026 20:59 |
| 04/09/2026 21:05 | Ligue 1 | PSG-Monaco | 1 | 67.4% | 7 | ❌ | 1-2 | `dc192d5eaa36` | 04/09/2026 21:04 |
| 05/09/2026 15:30 | Bundesliga | Leverkusen-Union Berlin | 1 | 72.4% | 4 | ✅ | 4-0 | `739b406ddf46` | 05/09/2026 15:29 |
| 05/09/2026 15:30 | Bundesliga | Borussia Mönchengladbach-Elversberg | GG | 63.8% | 8 | ✅ | 3-4 | `739b406ddf46` | 05/09/2026 15:29 |
| 05/09/2026 15:30 | Bundesliga | Werder Bremen-Leipzig | 2 | 57.6% | 16 | ❌ | 3-1 | `739b406ddf46` | 05/09/2026 15:29 |
| 05/09/2026 16:00 | Premier League | Man City-Coventry City | 1 | 82.6% | 2 | ✅ | 1-0 | `739b406ddf46` | 05/09/2026 15:59 |
| 05/09/2026 17:15 | Ligue 1 | Lens-Lorient | OVER_2.5 | 61.5% | 7 | ❌ | 0-1 | `71127dc263ff` | 05/09/2026 17:14 |
| 05/09/2026 18:30 | Bundesliga | Schalke 04-Bayern | 2 | 83.8% | 1 | ❌ | 0-0 | `0695e9e611e4` | 05/09/2026 18:29 |
| 05/09/2026 20:45 | Ligue 1 | Nice-Le Mans | GG | 60.6% | 6 | ✅ | 1-1 | `0695e9e611e4` | 05/09/2026 20:44 |
| 05/09/2026 21:00 | La Liga | Villarreal-Deportivo | 1 | 58.3% | 6 | ❌ | 2-3 | `0695e9e611e4` | 05/09/2026 20:59 |
| 06/09/2026 15:00 | Premier League | Everton-Man United | GG | 66.4% | 3 | ✅ | 2-2 | `0e7560df1b50` | 06/09/2026 14:59 |
| 06/09/2026 15:00 | Serie A | Parma-Monza | UNDER_2.5 | 60.7% | 5 | ✅ | 1-1 | `0e7560df1b50` | 06/09/2026 14:59 |
| 06/09/2026 16:15 | La Liga | Valencia-Barcelona | 2 | 69.4% | 1 | ✅ | 0-5 | `0e7560df1b50` | 06/09/2026 16:14 |
| 06/09/2026 17:30 | Bundesliga | Eintracht Frankfurt-Augsburg | GG | 68.1% | 1 | ✅ | 1-4 | `6a8bbb673394` | 06/09/2026 17:29 |
| 07/09/2026 19:00 | La Liga | Getafe-Celta | UNDER_2.5 | 62.5% | 8 | ✅ | 1-1 | `51f3059efa38` | 07/09/2026 18:59 |
| 12/09/2026 15:30 | Bundesliga | Dortmund-SC Paderborn | 1 | 76.0% | 3 | ✅ | 3-0 | `56779e32b964` | 12/09/2026 15:29 |
| 12/09/2026 15:30 | Bundesliga | Hoffenheim-Stuttgart | OVER_2.5 | 70.1% | 6 | ✅ | 2-1 | `56779e32b964` | 12/09/2026 15:29 |
| 12/09/2026 15:30 | Bundesliga | Augsburg-Leverkusen | GG | 67.0% | 8 | ✅ | 2-2 | `56779e32b964` | 12/09/2026 15:29 |
| 12/09/2026 15:30 | Bundesliga | Freiburg-Borussia Mönchengladbach | 1 | 60.3% | 19 | ✅ | 5-0 | `56779e32b964` | 12/09/2026 15:29 |
| 12/09/2026 16:00 | Premier League | Crystal Palace-Ipswich | GG | 63.8% | 6 | ✅ | 2-3 | `56779e32b964` | 12/09/2026 15:59 |
| 12/09/2026 16:00 | Premier League | Liverpool-Fulham | 1 | 62.3% | 10 | ❌ | 0-0 | `56779e32b964` | 12/09/2026 15:59 |
| 12/09/2026 16:00 | Premier League | Bournemouth-Brentford | GG | 60.4% | 15 | ✅ | 2-2 | `56779e32b964` | 12/09/2026 15:59 |
| 12/09/2026 18:30 | Bundesliga | Koln-Werder Bremen | GG | 62.5% | 7 | ✅ | 1-1 | `aa84061d452c` | 12/09/2026 18:29 |
| 12/09/2026 18:30 | La Liga | Athletic Bilbao-Elche | 1 | 59.4% | 13 | ❌ | 1-1 | `aa84061d452c` | 12/09/2026 18:29 |
| 12/09/2026 21:00 | La Liga | Real Madrid-Vallecano | 1 | 77.9% | 2 | ✅ | 4-1 | `aa84061d452c` | 12/09/2026 20:59 |
| 12/09/2026 21:00 | Premier League | Sunderland-Arsenal | 2 | 61.9% | 10 | ✅ | 0-2 | `aa84061d452c` | 12/09/2026 20:59 |
| 13/09/2026 14:00 | La Liga | Celta-Málaga | UNDER_2.5 | 62.4% | 6 | ✅ | 1-1 | `f6b56177690c` | 13/09/2026 13:59 |
| 13/09/2026 15:00 | Premier League | Coventry City-Brighton | GG | 62.1% | 7 | ❌ | 0-5 | `f6b56177690c` | 13/09/2026 14:59 |
| 13/09/2026 15:30 | Bundesliga | Leipzig-Hamburg | 1 | 68.5% | 4 | ✅ | 5-0 | `f6b56177690c` | 13/09/2026 15:29 |
| 13/09/2026 16:15 | La Liga | Levante-Barcelona | 2 | 75.3% | 2 | ✅ | 2-4 | `f6b56177690c` | 13/09/2026 16:14 |
| 13/09/2026 17:30 | Bundesliga | Elversberg-Bayern | 2 | 73.1% | 2 | ✅ | 1-2 | `5b81d684d917` | 13/09/2026 17:29 |
| 13/09/2026 17:30 | Premier League | Man United-Man City | GG | 62.3% | 4 | ❌ | 0-1 | `5b81d684d917` | 13/09/2026 17:29 |
| 14/09/2026 18:30 | Serie A | Torino-Roma | 2 | 63.3% | 7 | ✅ | 0-2 | `12f94e7d0de8` | 14/09/2026 18:29 |
| 14/09/2026 20:45 | Serie A | Inter-Udinese | 1 | 80.9% | 2 | ✅ | 5-3 | `70ad97670a22` | 14/09/2026 20:44 |
| 14/09/2026 21:00 | La Liga | Villarreal-Betis | OVER_2.5 | 61.1% | 10 | ✅ | 1-2 | `70ad97670a22` | 14/09/2026 20:59 |
| 15/09/2026 21:30 | La Liga | Elche-Real Madrid | 2 | 76.2% | 4 | ✅ | 2-3 | `e1ee3719ca06` | 15/09/2026 21:29 |
| 16/09/2026 19:00 | La Liga | Atletico Madrid-Osasuna | 1 | 66.8% | 7 | ✅ | 4-0 | `67333b607cef` | 16/09/2026 18:59 |
| 16/09/2026 21:30 | La Liga | Barcelona-Racing Santander | 1 | 86.6% | 2 | ✅ | 7-2 | `67333b607cef` | 16/09/2026 21:29 |
| 17/09/2026 19:00 | La Liga | Betis-Getafe | 1 | 61.5% | 13 | ✅ | 1-0 | `69f1d9597aec` | 17/09/2026 18:59 |
| 18/09/2026 20:30 | Bundesliga | Bayern-Union Berlin | 1 | 89.0% | 1 | ✅ | 7-0 | `5039d0f746fc` | 18/09/2026 20:29 |
| 18/09/2026 21:00 | Premier League | Brentford-Chelsea | GG | 65.3% | 6 | ❌ | 3-0 | `5039d0f746fc` | 18/09/2026 20:59 |

## Righe del modello legacy (Legacy) destinate al Registro

| data | lega | partita | mercato | prob | rank | esito | risultato | snapshot | salvato_il |
|---|---|---|---|---|---|---|---|---|---|
| 30/08/2026 15:00 | Premier League | Sunderland-Fulham | UNDER_2.5 | 80.3% | 2 | ✅ | 1-0 | `48e77686cd6d` | 30/08/2026 14:59 |
| 30/08/2026 15:00 | Premier League | Leeds-Brentford | GG | 68.4% | 7 | ✅ | 1-1 | `48e77686cd6d` | 30/08/2026 14:59 |
| 30/08/2026 15:00 | Premier League | Chelsea-Brighton | OVER_2.5 | 67.0% | 9 | ✅ | 4-3 | `48e77686cd6d` | 30/08/2026 14:59 |
| 30/08/2026 15:30 | Bundesliga | Freiburg-Werder Bremen | GG | 62.1% | 10 | ✅ | 4-1 | `5ff8911921a6` | 30/08/2026 15:29 |
| 30/08/2026 17:00 | La Liga | Real Madrid-Málaga | 1 | 78.5% | 3 | ✅ | 4-0 | `5ff8911921a6` | 30/08/2026 16:59 |
| 30/08/2026 17:15 | Ligue 1 | Rennes-Le Mans | OVER_2.5 | 69.1% | 4 | ✅ | 3-2 | `5ff8911921a6` | 30/08/2026 17:14 |
| 30/08/2026 17:30 | Premier League | Man United-Ipswich | 1 | 79.0% | 2 | ✅ | 5-2 | `5ff8911921a6` | 30/08/2026 17:29 |
| 30/08/2026 17:30 | Bundesliga | Augsburg-Schalke 04 | 1 | 58.8% | 10 | ✅ | 3-0 | `5ff8911921a6` | 30/08/2026 17:29 |
| 30/08/2026 19:30 | La Liga | Deportivo-Valencia | UNDER_2.5 | 64.9% | 7 | ❌ | 3-1 | `8db1dafb038a` | 30/08/2026 19:29 |
| 30/08/2026 20:45 | Serie A | Cagliari-Inter | 2 | 67.3% | 6 | ✅ | 0-1 | `8db1dafb038a` | 30/08/2026 20:44 |
| 30/08/2026 20:45 | Serie A | Lazio-Genoa | UNDER_2.5 | 61.2% | 10 | ✅ | 1-0 | `8db1dafb038a` | 30/08/2026 20:44 |
| 30/08/2026 20:45 | Ligue 1 | Monaco-Marseille | GG | 60.7% | 11 | ❌ | 2-0 | `8db1dafb038a` | 30/08/2026 20:44 |
| 30/08/2026 21:30 | La Liga | Celta-Athletic Bilbao | UNDER_2.5 | 64.7% | 7 | ✅ | 0-2 | `8db1dafb038a` | 30/08/2026 21:29 |
| 31/08/2026 18:30 | Serie A | Lecce-Roma | UNDER_2.5 | 62.3% | 11 | ❌ | 0-4 | `decc891162c6` | 31/08/2026 18:29 |
| 31/08/2026 19:30 | La Liga | Osasuna-Getafe | UNDER_2.5 | 82.5% | 2 | ✅ | 1-0 | `decc891162c6` | 31/08/2026 19:29 |
| 31/08/2026 21:30 | La Liga | Barcelona-Vallecano | 1 | 76.3% | 4 | ✅ | 5-2 | `2e447a7ec4cc` | 31/08/2026 21:29 |
| 04/09/2026 19:00 | Ligue 1 | Lyon-Auxerre | 1 | 62.0% | 11 | ✅ | 3-1 | `dc192d5eaa36` | 04/09/2026 18:59 |
| 04/09/2026 20:30 | Bundesliga | Stuttgart-Koln | 1 | 73.2% | 3 | ✅ | 4-1 | `dc192d5eaa36` | 04/09/2026 20:29 |
| 04/09/2026 21:05 | Ligue 1 | PSG-Monaco | 1 | 61.5% | 10 | ❌ | 1-2 | `dc192d5eaa36` | 04/09/2026 21:04 |
| 05/09/2026 15:30 | Bundesliga | Leverkusen-Union Berlin | 1 | 67.9% | 5 | ✅ | 4-0 | `739b406ddf46` | 05/09/2026 15:29 |
| 05/09/2026 15:30 | Bundesliga | Borussia Mönchengladbach-Elversberg | GG | 63.8% | 7 | ✅ | 3-4 | `739b406ddf46` | 05/09/2026 15:29 |
| 05/09/2026 16:00 | Premier League | Man City-Coventry City | 1 | 78.8% | 2 | ✅ | 1-0 | `739b406ddf46` | 05/09/2026 15:59 |
| 05/09/2026 17:15 | Ligue 1 | Lens-Lorient | OVER_2.5 | 61.5% | 7 | ❌ | 0-1 | `71127dc263ff` | 05/09/2026 17:14 |
| 05/09/2026 18:30 | Bundesliga | Schalke 04-Bayern | 2 | 75.2% | 1 | ❌ | 0-0 | `0695e9e611e4` | 05/09/2026 18:29 |
| 05/09/2026 20:45 | Ligue 1 | Nice-Le Mans | GG | 60.6% | 6 | ✅ | 1-1 | `0695e9e611e4` | 05/09/2026 20:44 |
| 05/09/2026 21:00 | La Liga | Villarreal-Deportivo | 1 | 55.0% | 6 | ❌ | 2-3 | `0695e9e611e4` | 05/09/2026 20:59 |
| 06/09/2026 15:00 | Premier League | Everton-Man United | GG | 66.4% | 2 | ✅ | 2-2 | `0e7560df1b50` | 06/09/2026 14:59 |
| 06/09/2026 15:00 | Serie A | Parma-Monza | UNDER_2.5 | 60.7% | 5 | ✅ | 1-1 | `0e7560df1b50` | 06/09/2026 14:59 |
| 06/09/2026 16:15 | La Liga | Valencia-Barcelona | 2 | 62.2% | 3 | ✅ | 0-5 | `0e7560df1b50` | 06/09/2026 16:14 |
| 06/09/2026 17:30 | Bundesliga | Eintracht Frankfurt-Augsburg | GG | 68.1% | 1 | ✅ | 1-4 | `6a8bbb673394` | 06/09/2026 17:29 |
| 07/09/2026 19:00 | La Liga | Getafe-Celta | UNDER_2.5 | 62.5% | 7 | ✅ | 1-1 | `51f3059efa38` | 07/09/2026 18:59 |
| 12/09/2026 15:30 | Bundesliga | Dortmund-SC Paderborn | 1 | 76.2% | 1 | ✅ | 3-0 | `56779e32b964` | 12/09/2026 15:29 |
| 12/09/2026 15:30 | Bundesliga | Hoffenheim-Stuttgart | OVER_2.5 | 70.1% | 3 | ✅ | 2-1 | `56779e32b964` | 12/09/2026 15:29 |
| 12/09/2026 15:30 | Bundesliga | Augsburg-Leverkusen | GG | 67.0% | 5 | ✅ | 2-2 | `56779e32b964` | 12/09/2026 15:29 |
| 12/09/2026 16:00 | Premier League | Crystal Palace-Ipswich | GG | 63.8% | 4 | ✅ | 2-3 | `56779e32b964` | 12/09/2026 15:59 |
| 12/09/2026 16:00 | Premier League | Bournemouth-Brentford | GG | 60.4% | 10 | ✅ | 2-2 | `56779e32b964` | 12/09/2026 15:59 |
| 12/09/2026 16:00 | Premier League | Liverpool-Fulham | 1 | 60.1% | 11 | ❌ | 0-0 | `56779e32b964` | 12/09/2026 15:59 |
| 12/09/2026 18:30 | Bundesliga | Koln-Werder Bremen | GG | 62.5% | 4 | ✅ | 1-1 | `aa84061d452c` | 12/09/2026 18:29 |
| 12/09/2026 18:30 | La Liga | Athletic Bilbao-Elche | 1 | 58.1% | 10 | ❌ | 1-1 | `aa84061d452c` | 12/09/2026 18:29 |
| 12/09/2026 21:00 | Premier League | Sunderland-Arsenal | 2 | 55.7% | 9 | ✅ | 0-2 | `aa84061d452c` | 12/09/2026 20:59 |
| 13/09/2026 14:00 | La Liga | Celta-Málaga | UNDER_2.5 | 62.4% | 4 | ✅ | 1-1 | `f6b56177690c` | 13/09/2026 13:59 |
| 13/09/2026 15:00 | Premier League | Coventry City-Brighton | GG | 62.1% | 5 | ❌ | 0-5 | `f6b56177690c` | 13/09/2026 14:59 |
| 13/09/2026 15:30 | Bundesliga | Leipzig-Hamburg | 1 | 58.7% | 6 | ✅ | 5-0 | `f6b56177690c` | 13/09/2026 15:29 |
| 13/09/2026 16:15 | La Liga | Levante-Barcelona | 2 | 67.4% | 2 | ✅ | 2-4 | `f6b56177690c` | 13/09/2026 16:14 |
| 13/09/2026 17:30 | Bundesliga | Elversberg-Bayern | 2 | 66.7% | 2 | ✅ | 1-2 | `5b81d684d917` | 13/09/2026 17:29 |
| 13/09/2026 17:30 | Premier League | Man United-Man City | GG | 62.3% | 3 | ❌ | 0-1 | `5b81d684d917` | 13/09/2026 17:29 |
| 14/09/2026 20:45 | Serie A | Inter-Udinese | 1 | 72.5% | 2 | ✅ | 5-3 | `70ad97670a22` | 14/09/2026 20:44 |
| 14/09/2026 21:00 | La Liga | Villarreal-Betis | OVER_2.5 | 61.1% | 9 | ✅ | 1-2 | `70ad97670a22` | 14/09/2026 20:59 |
| 16/09/2026 19:00 | La Liga | Atletico Madrid-Osasuna | 1 | 69.6% | 5 | ✅ | 4-0 | `67333b607cef` | 16/09/2026 18:59 |
| 16/09/2026 21:30 | La Liga | Barcelona-Racing Santander | 1 | 82.3% | 2 | ✅ | 7-2 | `67333b607cef` | 16/09/2026 21:29 |
| 17/09/2026 19:00 | La Liga | Betis-Getafe | 1 | 59.8% | 15 | ✅ | 1-0 | `69f1d9597aec` | 17/09/2026 18:59 |
| 18/09/2026 20:30 | Bundesliga | Bayern-Union Berlin | 1 | 86.2% | 1 | ✅ | 7-0 | `5039d0f746fc` | 18/09/2026 20:29 |
| 18/09/2026 21:00 | Premier League | Brentford-Chelsea | GG | 65.3% | 4 | ❌ | 3-0 | `5039d0f746fc` | 18/09/2026 20:59 |

## Copertura per modello (stesso campione?)

```
Copertura Top Mix nel periodo 2026-08-30 → 2026-09-20:
- modello Attuale: 61 partite (61 righe)
- modello Legacy: 53 partite (53 righe)
- partite con ENTRAMBI i modelli: 53
- solo modello Attuale: 8 partite
    · Betis - Real Madrid (La Liga, 04/09/2026 21:00) 2 55.3% ❌
    · Real Madrid - Vallecano (La Liga, 12/09/2026 21:00) 1 77.9% ✅
    · Elche - Real Madrid (La Liga, 15/09/2026 21:30) 2 76.2% ✅
    · Aston Villa - Arsenal (Premier League, 31/08/2026 21:00) 2 56.3% ✅
    · Ipswich - Liverpool (Premier League, 04/09/2026 21:00) 2 71.4% ✅
    · Torino - Roma (Serie A, 14/09/2026 18:30) 2 63.3% ✅
    · Werder Bremen - Leipzig (Bundesliga, 05/09/2026 15:30) 2 57.6% ❌
    · Freiburg - Borussia Mönchengladbach (Bundesliga, 12/09/2026 15:30) 1 60.3% ✅
- i due campioni NON coincidono: le partite mancanti sono quelle sotto le soglie del selettore (0,55 1X2 / 0,60 Totali) o scartate dal veto di disaccordo per QUEL modello
```
