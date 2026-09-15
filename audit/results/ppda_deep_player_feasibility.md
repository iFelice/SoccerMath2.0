# Fattibilita' PPDA, deep completions e medie giocatore per partita — audit di sola acquisizione

Rapporto **generato** da `audit/ppda_deep_player_audit.py` sui dati acquisiti da `update_all_ppda_player_db.py` (stessa fonte Understat della pipeline xG, `soccerdata==1.9.1`).

Nessuna modifica a `SoccerMath/app.py`, `SoccerMath/config.py`, `SoccerMath/models/`, a formule, soglie (`0.55`/`0.60`/`0.25`), pesi (`0.6`/`0.4`) o `PRIOR_MATCHES`: **questi dati non sono collegati al motore Poisson/Elo**, ne' lo diventano con questo intervento.

- generato: `2026-09-15T16:46:45.790618+00:00`
- istante di riferimento per le eta': `2026-09-15T16:46:41.584562+00:00`
- dataset analizzati: `ppda_deep`, `player_match`
- leghe: `Serie A`, `Premier League`, `La Liga`, `Bundesliga`, `Ligue 1`
- esecuzione reale (workflow sola lettura): https://github.com/iFelice/SoccerMath2.0/actions/runs/34992936842
- artifact: `ppda-player-verify-34992936842`
- cartella dati analizzata: `/home/runner/work/_temp/ppda-player-out/database`
- archivio xG di riferimento (perimetro): `/home/runner/work/SoccerMath2.0/SoccerMath2.0/SoccerMath/database`
- report di acquisizione: `/home/runner/work/_temp/ppda-player-out/reports/acquisizione.json` (soccerdata 1.9.1, fallimenti: 0)

## 1. Sintesi

- perimetro di riferimento (partite concluse con xG nell'archivio xG): **7276**
- PPDA/deep **completi** su entrambi i lati: **7275** (100.0%); partite senza alcun record: **0**
- partite con statistiche giocatore: **7275** (100.0%), per **224902** righe giocatore-partita
- partite senza righe giocatore sull'istantanea fresca (perimetro fresco, non archivio): Serie A: 0, Premier League: 0, La Liga: 0, Bundesliga: 1, Ligue 1: 0

## 2. Copertura per lega e stagione (rispetto all'archivio xG)

Denominatore: partite **concluse con entrambi gli xG** nell'archivio xG committato (`SoccerMath/database/xG archivio <lega>.json`). Per PPDA e deep completions una partita e' "completa" solo se **tutti e quattro** i valori (2 lati x 2 campi) sono presenti.

### Serie A

Perimetro nell'archivio xG: **1560** partite concluse con xG (2022: 380, 2023: 380, 2024: 380, 2025: 380, 2026: 40).

- file: `ppda_deep_serie_a.json` (439.6 KiB, sha256 `2acfb99bf40a830e`, modificato `2026-09-15T16:08:04.770345+00:00`)

| Stagione | Concluse con xG | Con record | Complete | PPDA non calcolabile | Parziali (deep assente) | Record senza valori | Senza record | Copertura completa |
|---|---|---|---|---|---|---|---|---|
| 2022 | 380 | 380 | 380 | 0 | 0 | 0 | 0 | 100.0% |
| 2023 | 380 | 380 | 380 | 0 | 0 | 0 | 0 | 100.0% |
| 2024 | 380 | 380 | 380 | 0 | 0 | 0 | 0 | 100.0% |
| 2025 | 380 | 380 | 380 | 0 | 0 | 0 | 0 | 100.0% |
| 2026 | 40 | 40 | 40 | 0 | 0 | 0 | 0 | 100.0% |
| **totale** | **1560** | **1560** | **1560** | **0** | **0** | **0** | **0** | **100.0%** |

"PPDA non calcolabile" = deep completions presente su entrambi i lati e PPDA nullo: soccerdata 1.9.1 restituisce `pd.NA` quando il denominatore difensivo del PPDA e' 0. E' un caso strutturale della fonte, non un campo perduto, ed e' contato a parte.

Valori presenti sul perimetro committato, lato per lato (denominatore 1560): PPDA casa 1560, PPDA trasferta 1560, deep casa 1560, deep trasferta 1560.

Valori PPDA (tutte le squadre, tutte le stagioni): mediana 11.76, p05 5.73, p95 25.89, minimo 3.15, massimo 127.00, zeri 0.

Deep completions: mediana 5.00, minimo 0.00, massimo 27.00, zeri 86.

- file: `player_match_serie_a.json` (19.7 MiB, sha256 `734b90dc6f1050c4`)

| Stagione | Concluse con xG | Con righe giocatore | Righe | Copertura |
|---|---|---|---|---|
| 2022 | 380 | 380 | 11885 | 100.0% |
| 2023 | 380 | 380 | 11909 | 100.0% |
| 2024 | 380 | 380 | 11888 | 100.0% |
| 2025 | 380 | 380 | 11928 | 100.0% |
| 2026 | 40 | 40 | 1274 | 100.0% |
| **totale** | **1560** | **1560** | **48884** | **100.0%** |

### Premier League

Perimetro nell'archivio xG: **1560** partite concluse con xG (2022: 380, 2023: 380, 2024: 380, 2025: 380, 2026: 40).

- file: `ppda_deep_premier_league.json` (452.5 KiB, sha256 `dd51b5ec836a0197`, modificato `2026-09-15T16:08:03.780364+00:00`)

| Stagione | Concluse con xG | Con record | Complete | PPDA non calcolabile | Parziali (deep assente) | Record senza valori | Senza record | Copertura completa |
|---|---|---|---|---|---|---|---|---|
| 2022 | 380 | 380 | 380 | 0 | 0 | 0 | 0 | 100.0% |
| 2023 | 380 | 380 | 380 | 0 | 0 | 0 | 0 | 100.0% |
| 2024 | 380 | 380 | 380 | 0 | 0 | 0 | 0 | 100.0% |
| 2025 | 380 | 380 | 380 | 0 | 0 | 0 | 0 | 100.0% |
| 2026 | 40 | 40 | 40 | 0 | 0 | 0 | 0 | 100.0% |
| **totale** | **1560** | **1560** | **1560** | **0** | **0** | **0** | **0** | **100.0%** |

"PPDA non calcolabile" = deep completions presente su entrambi i lati e PPDA nullo: soccerdata 1.9.1 restituisce `pd.NA` quando il denominatore difensivo del PPDA e' 0. E' un caso strutturale della fonte, non un campo perduto, ed e' contato a parte.

Valori presenti sul perimetro committato, lato per lato (denominatore 1560): PPDA casa 1560, PPDA trasferta 1560, deep casa 1560, deep trasferta 1560.

Valori PPDA (tutte le squadre, tutte le stagioni): mediana 11.40, p05 5.40, p95 25.36, minimo 2.30, massimo 193.00, zeri 0.

Deep completions: mediana 7.00, minimo 0.00, massimo 37.00, zeri 44.

- file: `player_match_premier_league.json` (19.2 MiB, sha256 `f5caf6449f181799`)

| Stagione | Concluse con xG | Con righe giocatore | Righe | Copertura |
|---|---|---|---|---|
| 2022 | 380 | 380 | 11345 | 100.0% |
| 2023 | 380 | 380 | 11384 | 100.0% |
| 2024 | 380 | 380 | 11567 | 100.0% |
| 2025 | 380 | 380 | 11490 | 100.0% |
| 2026 | 40 | 40 | 1236 | 100.0% |
| **totale** | **1560** | **1560** | **47022** | **100.0%** |

### La Liga

Perimetro nell'archivio xG: **1571** partite concluse con xG (2022: 380, 2023: 380, 2024: 380, 2025: 380, 2026: 51).

- file: `ppda_deep_la_liga.json` (450.0 KiB, sha256 `57c71447ead0c3c8`, modificato `2026-09-15T16:21:30.787844+00:00`)

| Stagione | Concluse con xG | Con record | Complete | PPDA non calcolabile | Parziali (deep assente) | Record senza valori | Senza record | Copertura completa |
|---|---|---|---|---|---|---|---|---|
| 2022 | 380 | 380 | 380 | 0 | 0 | 0 | 0 | 100.0% |
| 2023 | 380 | 380 | 380 | 0 | 0 | 0 | 0 | 100.0% |
| 2024 | 380 | 380 | 380 | 0 | 0 | 0 | 0 | 100.0% |
| 2025 | 380 | 380 | 380 | 0 | 0 | 0 | 0 | 100.0% |
| 2026 | 51 | 51 | 51 | 0 | 0 | 0 | 0 | 100.0% |
| **totale** | **1571** | **1571** | **1571** | **0** | **0** | **0** | **0** | **100.0%** |

"PPDA non calcolabile" = deep completions presente su entrambi i lati e PPDA nullo: soccerdata 1.9.1 restituisce `pd.NA` quando il denominatore difensivo del PPDA e' 0. E' un caso strutturale della fonte, non un campo perduto, ed e' contato a parte.

Valori presenti sul perimetro committato, lato per lato (denominatore 1571): PPDA casa 1571, PPDA trasferta 1571, deep casa 1571, deep trasferta 1571.

Valori PPDA (tutte le squadre, tutte le stagioni): mediana 10.76, p05 5.05, p95 23.20, minimo 2.54, massimo 91.50, zeri 0.

Deep completions: mediana 5.00, minimo 0.00, massimo 33.00, zeri 93.

- file: `player_match_la_liga.json` (19.9 MiB, sha256 `2115787454fc8604`)

| Stagione | Concluse con xG | Con righe giocatore | Righe | Copertura |
|---|---|---|---|---|
| 2022 | 380 | 380 | 11837 | 100.0% |
| 2023 | 380 | 380 | 11888 | 100.0% |
| 2024 | 380 | 380 | 11900 | 100.0% |
| 2025 | 380 | 380 | 11952 | 100.0% |
| 2026 | 51 | 51 | 1617 | 100.0% |
| **totale** | **1571** | **1571** | **49194** | **100.0%** |

### Bundesliga

Perimetro nell'archivio xG: **1251** partite concluse con xG (2022: 306, 2023: 306, 2024: 306, 2025: 306, 2026: 27).

- file: `ppda_deep_bundesliga.json` (366.1 KiB, sha256 `0319d545ee4696a6`, modificato `2026-09-15T16:21:56.759345+00:00`)

| Stagione | Concluse con xG | Con record | Complete | PPDA non calcolabile | Parziali (deep assente) | Record senza valori | Senza record | Copertura completa |
|---|---|---|---|---|---|---|---|---|
| 2022 | 306 | 306 | 306 | 0 | 0 | 0 | 0 | 100.0% |
| 2023 | 306 | 306 | 306 | 0 | 0 | 0 | 0 | 100.0% |
| 2024 | 306 | 306 | 305 | 1 | 0 | 0 | 0 | 99.7% |
| 2025 | 306 | 306 | 306 | 0 | 0 | 0 | 0 | 100.0% |
| 2026 | 27 | 27 | 27 | 0 | 0 | 0 | 0 | 100.0% |
| **totale** | **1251** | **1251** | **1250** | **1** | **0** | **0** | **0** | **99.9%** |

"PPDA non calcolabile" = deep completions presente su entrambi i lati e PPDA nullo: soccerdata 1.9.1 restituisce `pd.NA` quando il denominatore difensivo del PPDA e' 0. E' un caso strutturale della fonte, non un campo perduto, ed e' contato a parte.

Valori presenti sul perimetro committato, lato per lato (denominatore 1251): PPDA casa 1250, PPDA trasferta 1250, deep casa 1251, deep trasferta 1251.

Valori PPDA (tutte le squadre, tutte le stagioni): mediana 12.46, p05 6.19, p95 26.88, minimo 3.00, massimo 105.00, zeri 0.

Deep completions: mediana 6.00, minimo 0.00, massimo 29.00, zeri 24.

- file: `player_match_bundesliga.json` (16.0 MiB, sha256 `f8ca51161a55136a`)

| Stagione | Concluse con xG | Con righe giocatore | Righe | Copertura |
|---|---|---|---|---|
| 2022 | 306 | 306 | 9479 | 100.0% |
| 2023 | 306 | 306 | 9525 | 100.0% |
| 2024 | 306 | 305 | 9497 | 99.7% |
| 2025 | 306 | 306 | 9555 | 100.0% |
| 2026 | 27 | 27 | 854 | 100.0% |
| **totale** | **1251** | **1250** | **38910** | **99.9%** |

### Ligue 1

Perimetro nell'archivio xG: **1334** partite concluse con xG (2022: 380, 2023: 306, 2024: 306, 2025: 306, 2026: 36).

- file: `ppda_deep_ligue_1.json` (376.9 KiB, sha256 `68f9bc12d2a9aee9`, modificato `2026-09-15T16:34:27.572843+00:00`)

| Stagione | Concluse con xG | Con record | Complete | PPDA non calcolabile | Parziali (deep assente) | Record senza valori | Senza record | Copertura completa |
|---|---|---|---|---|---|---|---|---|
| 2022 | 380 | 380 | 380 | 0 | 0 | 0 | 0 | 100.0% |
| 2023 | 306 | 306 | 306 | 0 | 0 | 0 | 0 | 100.0% |
| 2024 | 306 | 306 | 306 | 0 | 0 | 0 | 0 | 100.0% |
| 2025 | 306 | 306 | 306 | 0 | 0 | 0 | 0 | 100.0% |
| 2026 | 36 | 36 | 36 | 0 | 0 | 0 | 0 | 100.0% |
| **totale** | **1334** | **1334** | **1334** | **0** | **0** | **0** | **0** | **100.0%** |

"PPDA non calcolabile" = deep completions presente su entrambi i lati e PPDA nullo: soccerdata 1.9.1 restituisce `pd.NA` quando il denominatore difensivo del PPDA e' 0. E' un caso strutturale della fonte, non un campo perduto, ed e' contato a parte.

Valori presenti sul perimetro committato, lato per lato (denominatore 1334): PPDA casa 1334, PPDA trasferta 1334, deep casa 1334, deep trasferta 1334.

Valori PPDA (tutte le squadre, tutte le stagioni): mediana 11.26, p05 5.50, p95 25.93, minimo 2.58, massimo 100.00, zeri 0.

Deep completions: mediana 6.00, minimo 0.00, massimo 30.00, zeri 62.

- file: `player_match_ligue_1.json` (16.5 MiB, sha256 `57493c43c99a29fc`)

| Stagione | Concluse con xG | Con righe giocatore | Righe | Copertura |
|---|---|---|---|---|
| 2022 | 380 | 380 | 11547 | 100.0% |
| 2023 | 306 | 306 | 9394 | 100.0% |
| 2024 | 306 | 306 | 9413 | 100.0% |
| 2025 | 306 | 306 | 9408 | 100.0% |
| 2026 | 36 | 36 | 1130 | 100.0% |
| **totale** | **1334** | **1334** | **40892** | **100.0%** |

## 3. Point-in-time: stessa tempistica degli xG o in ritardo?

Due letture indipendenti, entrambe misurate:

1. **stessa sorgente, stessa istantanea** — `read_team_match_stats()` e `read_schedule()` leggono lo **stesso documento** `getLeagueData/<lega>/<stagione>` (`datesData` per il calendario, `teamsData.history` per PPDA/deep). Il confronto e' quindi fatto a livello di partita sull'istantanea fresca: se una partita ha gli xG ma non PPDA/deep, il ritardo e' di *campo*, non di *endpoint*;
2. **endpoint diverso** — `read_player_match_stats()` non usa il payload di lega: chiama `getMatchData/<id>`, **una richiesta HTTP per partita** (`rostersData`). Qui il ritardo puo' essere reale e va misurato.

### Serie A

- PPDA/deep: partite del perimetro committato assenti dal file: **0**; eta' mediana n/d giorni, p90 n/d, massima n/d; partite piu' vecchie di 1 giorno: **0**
- ultima data con PPDA/deep: `2026-09-14`
- statistiche giocatore: partite del perimetro committato senza righe: **0**; eta' mediana n/d giorni, massima n/d; partite piu' vecchie di 1 giorno: **0**
- ultima data con righe giocatore: `2026-09-14`
- istantanea fresca: 1900 partite a calendario, 1560 concluse con xG, ultima data giocata `2026-09-14 18:45:00`; acquisizione in 822.9 s
- ppda_deep, copertura sull'istantanea fresca: mancanti **0** su 1560 (frontiera 0, non frontiera 0, senza data 0); record completi 1560 (100.0%)
- player_match, copertura sull'istantanea fresca: mancanti **0** su 1560 (frontiera 0, non frontiera 0, senza data 0); partite restituite 1560

### Premier League

- PPDA/deep: partite del perimetro committato assenti dal file: **0**; eta' mediana n/d giorni, p90 n/d, massima n/d; partite piu' vecchie di 1 giorno: **0**
- ultima data con PPDA/deep: `2026-09-14`
- statistiche giocatore: partite del perimetro committato senza righe: **0**; eta' mediana n/d giorni, massima n/d; partite piu' vecchie di 1 giorno: **0**
- ultima data con righe giocatore: `2026-09-14`
- istantanea fresca: 1900 partite a calendario, 1560 concluse con xG, ultima data giocata `2026-09-14 19:00:00`; acquisizione in 808.0 s
- ppda_deep, copertura sull'istantanea fresca: mancanti **0** su 1560 (frontiera 0, non frontiera 0, senza data 0); record completi 1560 (100.0%)
- player_match, copertura sull'istantanea fresca: mancanti **0** su 1560 (frontiera 0, non frontiera 0, senza data 0); partite restituite 1560

### La Liga

- PPDA/deep: partite del perimetro committato assenti dal file: **0**; eta' mediana n/d giorni, p90 n/d, massima n/d; partite piu' vecchie di 1 giorno: **0**
- ultima data con PPDA/deep: `2026-09-14`
- statistiche giocatore: partite del perimetro committato senza righe: **0**; eta' mediana n/d giorni, massima n/d; partite piu' vecchie di 1 giorno: **0**
- ultima data con righe giocatore: `2026-09-14`
- istantanea fresca: 1900 partite a calendario, 1571 concluse con xG, ultima data giocata `2026-09-14 19:00:00`; acquisizione in 882.7 s
- ppda_deep, copertura sull'istantanea fresca: mancanti **0** su 1571 (frontiera 0, non frontiera 0, senza data 0); record completi 1571 (100.0%)
- player_match, copertura sull'istantanea fresca: mancanti **0** su 1571 (frontiera 0, non frontiera 0, senza data 0); partite restituite 1571; righe doppie tolte 91 su 49285 (0.2%, 3 partite)

### Bundesliga

- PPDA/deep: partite del perimetro committato assenti dal file: **0**; eta' mediana n/d giorni, p90 n/d, massima n/d; partite piu' vecchie di 1 giorno: **0**
- ultima data con PPDA/deep: `2026-09-13`
- statistiche giocatore: partite del perimetro committato senza righe: **1**; eta' mediana 583.1 giorni, massima 583.1; partite piu' vecchie di 1 giorno: **1**
- ultima data con righe giocatore: `2026-09-13`
- istantanea fresca: 1530 partite a calendario, 1251 concluse con xG, ultima data giocata `2026-09-13 15:30:00`; acquisizione in 763.5 s
- ppda_deep, copertura sull'istantanea fresca: mancanti **0** su 1251 (frontiera 0, non frontiera 0, senza data 0); record completi 1250 (99.9%); coppie con deep presente e PPDA assente (denominatore difensivo nullo): 2; tentativi di recupero 2
- player_match, copertura sull'istantanea fresca: mancanti **1** su 1251 (frontiera 0, non frontiera 1, senza data 0); partite restituite 1250; tentativi di recupero 2; partite illeggibili (payload che rompe soccerdata) 3
- partite illeggibili (id: errore): `27930`: AttributeError: 'list' object has no attribute 'values'; `27930`: AttributeError: 'list' object has no attribute 'values'; `27930`: AttributeError: 'list' object has no attribute 'values'
- esempi di partite mancanti sull'istantanea fresca (max 8): [2024] Holstein Kiel - Bochum (id 27930, 2025-02-09)

### Ligue 1

- PPDA/deep: partite del perimetro committato assenti dal file: **0**; eta' mediana n/d giorni, p90 n/d, massima n/d; partite piu' vecchie di 1 giorno: **0**
- ultima data con PPDA/deep: `2026-09-13`
- statistiche giocatore: partite del perimetro committato senza righe: **0**; eta' mediana n/d giorni, massima n/d; partite piu' vecchie di 1 giorno: **0**
- ultima data con righe giocatore: `2026-09-13`
- istantanea fresca: 1604 partite a calendario, 1334 concluse con xG, ultima data giocata `2026-09-13 18:45:00`; acquisizione in 744.6 s
- ppda_deep, copertura sull'istantanea fresca: mancanti **0** su 1334 (frontiera 0, non frontiera 0, senza data 0); record completi 1334 (100.0%)
- player_match, copertura sull'istantanea fresca: mancanti **0** su 1334 (frontiera 0, non frontiera 0, senza data 0); partite restituite 1334

## 4. Minuti giocati per partita (statistiche giocatore)

Serve a decidere se una media "per 90 minuti" e' utilizzabile cosi' com'e' o se serve un minutaggio minimo: le righe con 0 minuti non hanno un denominatore per-90, e le rose Understat includono chi non entra.

| Lega | Righe | Partite | Giocatori | Minuti p50 | Minuti p95 | Righe a 0 minuti | Giocatori/partita (p50) |
|---|---|---|---|---|---|---|---|
| Serie A | 48884 | 1560 | 2789 | 80.0 | 90.0 | 0 (0.0%) | 32.0 |
| Premier League | 47022 | 1560 | 2629 | 89.0 | 90.0 | 0 (0.0%) | 30.0 |
| La Liga | 49194 | 1571 | 2820 | 80.0 | 90.0 | 0 (0.0%) | 32.0 |
| Bundesliga | 38910 | 1250 | 2337 | 83.0 | 90.0 | 0 (0.0%) | 31.0 |
| Ligue 1 | 40892 | 1334 | 2618 | 84.0 | 90.0 | 0 (0.0%) | 31.0 |

Totale: 224902 righe giocatore-partita, 0 con 0 minuti (0.0%), 100.0% con minuti > 0 (le sole utilizzabili in una media per-90 senza moltiplicatori).

### Minutaggio minimo: quanto dato si perderebbe

Soglia sul **totale stagionale per giocatore** (somma dei minuti delle partite acquisite), calcolata su tutte le leghe insieme:

| Soglia minuti | Giocatori | Righe | Quota righe | Minuti | Quota minuti |
|---|---|---|---|---|---|
| >= 0 | 13193 | 224902 | 100.0% | 14377095 | 100.0% |
| >= 90 | 11103 | 220236 | 97.9% | 14319087 | 99.6% |
| >= 270 | 9277 | 211349 | 94.0% | 14013298 | 97.5% |
| >= 450 | 7943 | 201098 | 89.4% | 13554855 | 94.3% |
| >= 900 | 6381 | 177389 | 78.9% | 12523378 | 87.1% |

## 5. Nomi delle squadre (resolver condiviso della PR #15)

Nessuna tabella nuova: i file conservano i nomi grezzi di Understat e l'audit li risolve con `team_names.resolve_team_name` (unione di `TEAM_NAME_MAP` e `UNDERSTAT_NAME_MAP`). Un nome non risolto non viene indovinato.

| Lega | Dataset | Nomi grezzi | Non risolti | Collisioni |
|---|---|---|---|---|
| Serie A | ppda_deep | 27 | 0 | 0 |
| Serie A | player_match | 27 | 0 | 0 |
| Premier League | ppda_deep | 27 | 0 | 0 |
| Premier League | player_match | 27 | 0 | 0 |
| La Liga | ppda_deep | 29 | 0 | 0 |
| La Liga | player_match | 29 | 0 | 0 |
| Bundesliga | ppda_deep | 25 | 0 | 0 |
| Bundesliga | player_match | 25 | 0 | 0 |
| Ligue 1 | ppda_deep | 25 | 0 | 0 |
| Ligue 1 | player_match | 25 | 0 | 0 |


## 6. Cosa espone `soccerdata==1.9.1` e cosa non espone

Verificato sul sorgente della versione pinnata (`soccerdata/understat.py`), non dedotto dai risultati.

**Esposti**

- `Understat.read_team_match_stats()`: `*_ppda`, `*_deep_completions`, `*_xg`, `*_np_xg`, `*_expected_points`, `*_points`, `*_goals`
- `Understat.read_player_match_stats()`: `minutes`, `position`, `goals`, `own_goals`, `shots`, `xg`, `xg_chain`, `xg_buildup`, `assists`, `xa`, `key_passes`, `yellow_cards`, `red_cards`

**Non esposti (dichiarati, non aggirati con ripieghi silenziosi)**

- un canale d'errore per singola partita in ``read_player_match_stats()``: ``Understat._read_match`` inghiotte ``ConnectionError`` e restituisce ``None``, quindi la partita viene saltata in silenzio (qui contata come MANCANTE, mai come 0 righe)
- la data della partita nelle righe giocatore (bisogna derivarla dal prefisso di ``game``, oppure incrociare il calendario: entrambe le vie sono usate e confrontate)
- un rate limit per Understat: ``Understat._request_api`` chiama ``self._session.get()`` senza ``rate_limit`` ne' delay (a differenza di ``BaseRequestsReader._download_and_save``), quindi il ritmo dipende solo dalla latenza e dal parallelismo scelto
- i minuti ufficiali del campionato: ``minutes`` e' il campo ``time`` di Understat e include il recupero (valori > 90)
- qualsiasi forma di snapshot datato lato Understat: la disponibilita' storica reale dei dati non e' ricostruibile a posteriori

## 7. Costo dell'acquisizione (misurato)

| Lega | Secondi (lega) | Partite richieste (giocatore) | Righe | Tentativi di recupero | File PPDA/deep | File giocatore |
|---|---|---|---|---|---|---|
| Serie A | 822.9 | 1560 | 48884 | 0 | 439.6 KiB | 19.7 MiB |
| Premier League | 808.0 | 1560 | 47022 | 0 | 452.5 KiB | 19.2 MiB |
| La Liga | 882.7 | 1571 | 49194 | 0 | 450.0 KiB | 19.9 MiB |
| Bundesliga | 763.5 | 1251 | 38910 | 2 | 366.1 KiB | 16.0 MiB |
| Ligue 1 | 744.6 | 1334 | 40892 | 0 | 376.9 KiB | 16.5 MiB |

- `--parallel-leagues`: 2; `--retries`: 2; `--frontier-days`: 1.0; tolleranza partite non di frontiera: 0.01

Chiamate HTTP per lega (soccerdata 1.9.1): 1 payload di lega per `read_schedule()` + 1 per `read_team_match_stats()` (~4 MB ciascuno) + **1 richiesta per partita** per `read_player_match_stats()`.

## 8. Limiti dichiarati

- Understat non pubblica **snapshot datati**: la disponibilita' reale al momento della partita non e' ricostruibile a posteriori, si misura solo la frontiera (confronto fra il file acquisito e l'archivio xG committato, piu' il confronto a partita sull'istantanea fresca);
- gli xG di Understat possono essere **rivisti** dopo la partita: l'ultimo valore non e' quello pubblicato all'epoca;
- il ritardo misurato vale per **questo** istante di acquisizione: un buco su una partita vecchia e' strutturale, un buco sull'ultima giornata puo' essere solo un ritardo di pubblicazione;
- le righe doppie sulla chiave primaria sono **tolte e contate** (tenuta la riga piu' ricca): nascono da partite elencate due volte nel payload di lega, che soccerdata percorre due volte; sopra la soglia dichiarata la lega non viene pubblicata;
- `PPDA` nullo con `deep completions` presente su entrambi i lati e' il caso strutturale di `pd.NA` (denominatore difensivo 0): non e' un campo perduto, e' contato a parte e non entra fra le partite mancanti;
- `read_player_match_stats()` non distingue "payload assente" da `ConnectionError` inghiottito: le partite senza righe sono trattate come mancanti e riprovate, mai come 0 giocatori;
- la copertura e' misurata rispetto all'**archivio xG** (partite concluse con entrambi gli xG): partite assenti dall'archivio non entrano nel denominatore;
- le statistiche giocatore sono per **partita**, non per 90 minuti ufficiali: i minuti sono il campo `time` di Understat (include il recupero);
- nessuna soglia, formula o peso del motore e' stato toccato: nessuna delle tre feature e' collegata al motore Poisson/Elo in questa fase.

