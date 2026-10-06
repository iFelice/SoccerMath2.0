# Fattibilita' feature squalifiche — conteggi, sorgenti, potenza

Generato: `2026-10-06T10:46:03+00:00` UTC
Commit: `af4924d35d3da9c4521f583bb651f63690c02153`

> Perimetro: sola lettura in `audit/`; nessun download di fonti nuove; nessuna modifica a `SoccerMath/`, lambda o rating.

## 0. Prerequisiti e ambiente

Evidenza raccolta dal checkout prima dell'analisi e dallo script:

| Check | Output |
|---|---|
| branch | arena/7ff66814-soccermath2-0 |
| HEAD | af4924d35d3da9c4521f583bb651f63690c02153 |
| repository shallow | false |
| origin/main...HEAD (al momento dello script) | (vuoto) |
| audit/elo_walker_core.py | presente |
| requirements-audit.txt | presente |
| audit/elo_weight_retune.py | presente |
| audit/results/elo_weight_retune.md | presente |

Nota prerequisito `elo_weight_retune`: il run preliminare ha cambiato solo `Generato` e `Commit`; il file e' stato ripristinato e non viene committato. I numeri del report non hanno diff.

## 1. Inventario repo sulle squalifiche e assenze

| Percorso | Esiste | Byte | Primo commit | Ultimo commit | Contenuto utile |
|---|---|---|---|---|---|
| audit/results/assenze_certe_valore_feasibility.md | si | 24977 | e235ac8085179f3c48162d35273c1bb207bfd52d	2026-09-19T22:25:11+00:00	Parte B v2 (rediretta): fatti | 8f9674d91cfb5fcdecb2ba99604e346cef3077f6	2026-09-19T23:14:31+00:00	Parte B (report): verdetto fi | regole squalifiche per lega, casi limite, ground truth candidate, limiti Ligue 1/WhoScored |
| audit/results/assenze_formazioni_probabili_feasibility.md | si | 22829 | e7535688ec580e26a1e48ce5e3b9f90c7ca28b6b	2026-09-19T21:52:28+00:00	Parte B: referto fattibilita' | e235ac8085179f3c48162d35273c1bb207bfd52d	2026-09-19T22:25:11+00:00	Parte B v2 (rediretta): fatti | ricerca fonti assenze/formazioni e profondita' storica |
| audit/results/assenze_formazioni_soccerdata_zero_cost_verification.md | si | 14095 | 93f2f57d6f00863dda89c525b3f463099e0a739c	2026-09-19T22:18:58+00:00	Parte B: approfondimento a co | 93f2f57d6f00863dda89c525b3f463099e0a739c	2026-09-19T22:18:58+00:00	Parte B: approfondimento a co | audit sorgente soccerdata 1.9.1: XI storiche e WhoScored missing players |
| audit/results/ppda_deep_player_feasibility.md | si | 22865 | 1acc16b251f164600d35cb6b96873f2541320ac0	2026-09-16T11:02:44+00:00	Referto di fattibilita' PPDA/ | 1acc16b251f164600d35cb6b96873f2541320ac0	2026-09-16T11:02:44+00:00	Referto di fattibilita' PPDA/ | copertura player_match/PPDA/deep generata da artifact esterno |
| audit/results/ppda_deep_player_feasibility.json | si | 171763 | 1acc16b251f164600d35cb6b96873f2541320ac0	2026-09-16T11:02:44+00:00	Referto di fattibilita' PPDA/ | 1acc16b251f164600d35cb6b96873f2541320ac0	2026-09-16T11:02:44+00:00	Referto di fattibilita' PPDA/ | dettaglio macchina del referto PPDA/player_match |
| audit/ppda_deep_player_audit.py | si | 55014 | 88b7938e9eb3b10eb70cfcbdbab96235aae72251	2026-09-16T11:02:44+00:00	Acquisizione PPDA/deep + gioc | 7bde972622c8b860866a4d4120be0437cbe497e3	2026-09-16T11:02:44+00:00	Acquisizione: retry del calen | script audit copertura player_match/PPDA/deep |
| audit/whoscored_missing_players_sample.py | si | 35740 | c5adc82e53e7ade2c48ac49fb10b8a9f211e00f6	2026-09-19T22:38:40+00:00	Parte B: verifica esplicita r | b0f7a84fda54facebc5eab68580d58d1f125e31a	2026-09-19T23:06:17+00:00	Parte B (sampling): via HTTP  | campionamento WhoScored missing players, no dati versionati |
| update_all_ppda_player_db.py | si | 66491 | 88b7938e9eb3b10eb70cfcbdbab96235aae72251	2026-09-16T11:02:44+00:00	Acquisizione PPDA/deep + gioc | e2de79a3071292b2c64df2979fb92872df65a592	2026-09-19T22:45:52+00:00	Sessione 1 Parte A (revisione | pipeline acquisizione Understat player_match con cartellini/minuti/ruolo |
| .github/workflows/ppda_player_verify.yml | si | 12380 | 88b7938e9eb3b10eb70cfcbdbab96235aae72251	2026-09-16T11:02:44+00:00	Acquisizione PPDA/deep + gioc | b79112f7e7f52d106cf215be8127ba35e75bd835	2026-09-19T22:26:04+00:00	Sessione 1 Parte A: automazio | workflow verifica acquisizione player_match come artifact non versionato |
| .github/workflows/whoscored_missing_sample.yml | si | 7651 | c5adc82e53e7ade2c48ac49fb10b8a9f211e00f6	2026-09-19T22:38:40+00:00	Parte B: verifica esplicita r | b0f7a84fda54facebc5eab68580d58d1f125e31a	2026-09-19T23:06:17+00:00	Parte B (sampling): via HTTP  | workflow campionamento WhoScored HARD_BLOCK documentato |

Regole per lega gia' documentate nel repo (fonte principale: `audit/results/assenze_certe_valore_feasibility.md`):

| Lega | Regola documentata |
|---|---|
| Serie A | accumulo progressivo 5, poi 4,4,3,2, poi ogni ammonizione; coppe separate; le ammonizioni inefficaci restano fino a fine stagione o trasferimento in altra Lega |
| Premier League | 5 gialli entro la 19a partita di campionato della squadra -> 1 turno; 10 entro la 32a -> 2 turni; 15 in stagione -> 3 turni; gialli per competizione, rossi domestici cross-competition |
| La Liga | 5 gialli nella stessa stagione/competizione -> 1 turno, cicli da 5; doppia ammonizione non conta per il ciclo; esenzione ultima giornata post-riforma art. 112.4 |
| Bundesliga | 5a, 10a, 15a ammonizione -> 1 turno; conteggio per competizione; reset a fine stagione |
| Ligue 1 | fino al 2024/25: 3 ammonizioni in finestra di 10 incontri ufficiali; dal 2025/26: regola a 5 gialli; coppe nazionali comunicanti, quindi fonte solo campionato sottocopre |

Casi limite / ambigui documentati o necessari da escludere dai conteggi principali:

- durata oltre un turno dei rossi diretti: non deducibile dai soli cartellini
- rossi da coppe nazionali in Premier League: possono essere scontati in campionato ma non sono nel dataset di campionato
- Ligue 1: fino al 2024/25 la finestra mobile comprende coppe nazionali; dal 2025/26 cambia il regime; con dati solo campionato la fonte sottostima vicino alla soglia
- La Liga: quinta gialla all'ultima giornata esclusa dalla squalifica successiva post art. 112.4
- trasferimenti e cambi lega: possono azzerare o rendere non confrontabile il ciclo secondo regole documentate; serve anagrafica/ground truth per verificarli

Ground truth candidate documentate ma non versionate come dati:

| Lega | Candidate |
|---|---|
| Serie A | comunicati ufficiali Giudice Sportivo Lega Serie A/FIGC, non presenti come dati nel repo |
| Premier League | pagina ufficiale Premier League suspensions/decisioni FA, non presente come dati nel repo |
| La Liga | resoluciones del Juez de Competicion RFEF, non presenti come dati nel repo |
| Bundesliga | decisioni Sportgericht DFB, non presenti come dati nel repo |
| Ligue 1 | decisioni Commission de Discipline LFP, non presenti come dati nel repo |

## 1.1 Fonti dati disponibili nel checkout

### CSV football-data (`SoccerMath/database/*_<stagione>.csv`)
| Lega | Stagione | Partite | HY/AY/HR/AR | Copertura team-card | Player-card | Buco noto |
|---|---|---|---|---|---|---|
| Serie A | 2022/23 | 380 | si | 100.0% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |
| Serie A | 2023/24 | 380 | si | 100.0% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |
| Serie A | 2024/25 | 380 | si | 100.0% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |
| Serie A | 2025/26 | 380 | si | 100.0% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |
| Premier League | 2022/23 | 380 | si | 100.0% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |
| Premier League | 2023/24 | 380 | si | 100.0% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |
| Premier League | 2024/25 | 380 | si | 100.0% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |
| Premier League | 2025/26 | 380 | si | 100.0% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |
| La Liga | 2022/23 | 380 | si | 100.0% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |
| La Liga | 2023/24 | 380 | si | 100.0% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |
| La Liga | 2024/25 | 380 | si | 100.0% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |
| La Liga | 2025/26 | 380 | si | 100.0% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |
| Bundesliga | 2022/23 | 306 | si | 100.0% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |
| Bundesliga | 2023/24 | 306 | si | 100.0% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |
| Bundesliga | 2024/25 | 306 | si | 99.7% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |
| Bundesliga | 2025/26 | 306 | si | 100.0% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |
| Ligue 1 | 2022/23 | 380 | si | 100.0% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |
| Ligue 1 | 2023/24 | 306 | si | 100.0% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |
| Ligue 1 | 2024/25 | 306 | si | 100.0% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |
| Ligue 1 | 2025/26 | 306 | si | 100.0% | no | solo aggregati squadra (HY/AY/HR/AR), nessun giocatore |

### Archivi xG Understat committati
| Lega | Stagione | Righe | Risultati | xG presenti | Player fields | Buco noto |
|---|---|---|---|---|---|---|
| Serie A | 2022/23 | 380 | 380 | 380 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |
| Serie A | 2023/24 | 380 | 380 | 380 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |
| Serie A | 2024/25 | 380 | 380 | 380 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |
| Serie A | 2025/26 | 380 | 380 | 380 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |
| Premier League | 2022/23 | 380 | 380 | 380 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |
| Premier League | 2023/24 | 380 | 380 | 380 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |
| Premier League | 2024/25 | 380 | 380 | 380 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |
| Premier League | 2025/26 | 380 | 380 | 380 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |
| La Liga | 2022/23 | 380 | 380 | 380 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |
| La Liga | 2023/24 | 380 | 380 | 380 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |
| La Liga | 2024/25 | 380 | 380 | 380 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |
| La Liga | 2025/26 | 380 | 380 | 380 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |
| Bundesliga | 2022/23 | 306 | 306 | 306 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |
| Bundesliga | 2023/24 | 306 | 306 | 306 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |
| Bundesliga | 2024/25 | 306 | 306 | 306 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |
| Bundesliga | 2025/26 | 306 | 306 | 306 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |
| Ligue 1 | 2022/23 | 380 | 380 | 380 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |
| Ligue 1 | 2023/24 | 306 | 306 | 306 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |
| Ligue 1 | 2024/25 | 306 | 306 | 306 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |
| Ligue 1 | 2025/26 | 306 | 306 | 306 | no | match id, data, squadre, gol, xG; nessun giocatore/cartellino/minuti/ruolo |

### `audit/data/*_btts.json`
| Lega | Stagione | Righe | match_date presenti | scraped min | scraped max | Buco noto |
|---|---|---|---|---|---|---|
| Serie A | 2022/23 | 381 | 150 | 2026-09-10 14:47:57 UTC | 2026-09-10 15:08:11 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |
| Serie A | 2023/24 | 380 | 153 | 2026-09-10 15:10:23 UTC | 2026-09-10 15:30:14 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |
| Serie A | 2024/25 | 380 | 155 | 2026-09-10 15:32:42 UTC | 2026-09-10 15:52:37 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |
| Serie A | 2025/26 | 380 | 155 | 2026-09-10 15:54:55 UTC | 2026-09-10 16:14:54 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |
| Premier League | 2022/23 | 380 | 153 | 2026-09-10 16:17:06 UTC | 2026-09-10 16:37:18 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |
| Premier League | 2023/24 | 380 | 160 | 2026-09-10 16:39:26 UTC | 2026-09-10 16:59:21 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |
| Premier League | 2024/25 | 380 | 146 | 2026-09-10 17:01:36 UTC | 2026-09-10 17:21:28 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |
| Premier League | 2025/26 | 380 | 144 | 2026-09-10 17:23:36 UTC | 2026-09-10 17:43:29 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |
| La Liga | 2022/23 | 380 | 150 | 2026-09-10 17:46:08 UTC | 2026-09-10 18:06:23 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |
| La Liga | 2023/24 | 380 | 141 | 2026-09-10 18:08:36 UTC | 2026-09-10 18:28:34 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |
| La Liga | 2024/25 | 380 | 151 | 2026-09-10 18:31:11 UTC | 2026-09-10 18:51:06 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |
| La Liga | 2025/26 | 380 | 154 | 2026-09-10 18:53:32 UTC | 2026-09-10 19:13:24 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |
| Bundesliga | 2022/23 | 308 | 135 | 2026-09-10 19:15:25 UTC | 2026-09-10 19:31:43 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |
| Bundesliga | 2023/24 | 308 | 136 | 2026-09-10 19:33:45 UTC | 2026-09-10 19:49:40 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |
| Bundesliga | 2024/25 | 308 | 141 | 2026-09-10 19:51:54 UTC | 2026-09-10 20:07:51 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |
| Bundesliga | 2025/26 | 308 | 137 | 2026-09-10 20:09:56 UTC | 2026-09-10 20:25:56 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |
| Ligue 1 | 2022/23 | 380 | 148 | 2026-09-10 20:28:08 UTC | 2026-09-10 20:48:19 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |
| Ligue 1 | 2023/24 | 310 | 135 | 2026-09-10 20:50:18 UTC | 2026-09-10 21:06:32 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |
| Ligue 1 | 2024/25 | 309 | 137 | 2026-09-10 21:08:32 UTC | 2026-09-10 21:24:43 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |
| Ligue 1 | 2025/26 | 310 | 138 | 2026-09-10 21:26:38 UTC | 2026-09-10 21:42:51 UTC | quote BTTS/OddsPortal; nessun cartellino, minuto, titolarita' o ruolo |

### Player-match Understat: referto presente, dati assenti nel checkout
| Lega | Stagione | Partite referto | Con righe nel run esterno | Righe giocatore nel run esterno | Copertura referto | File locale |
|---|---|---|---|---|---|---|
| Serie A | 2022/23 | 380 | 380 | 11885 | 100.0% | no |
| Serie A | 2023/24 | 380 | 380 | 11909 | 100.0% | no |
| Serie A | 2024/25 | 380 | 380 | 11888 | 100.0% | no |
| Serie A | 2025/26 | 380 | 380 | 11928 | 100.0% | no |
| Premier League | 2022/23 | 380 | 380 | 11345 | 100.0% | no |
| Premier League | 2023/24 | 380 | 380 | 11384 | 100.0% | no |
| Premier League | 2024/25 | 380 | 380 | 11567 | 100.0% | no |
| Premier League | 2025/26 | 380 | 380 | 11490 | 100.0% | no |
| La Liga | 2022/23 | 380 | 380 | 11837 | 100.0% | no |
| La Liga | 2023/24 | 380 | 380 | 11888 | 100.0% | no |
| La Liga | 2024/25 | 380 | 380 | 11900 | 100.0% | no |
| La Liga | 2025/26 | 380 | 380 | 11952 | 100.0% | no |
| Bundesliga | 2022/23 | 306 | 306 | 9479 | 100.0% | no |
| Bundesliga | 2023/24 | 306 | 306 | 9525 | 100.0% | no |
| Bundesliga | 2024/25 | 306 | 305 | 9497 | 99.7% | no |
| Bundesliga | 2025/26 | 306 | 306 | 9555 | 100.0% | no |
| Ligue 1 | 2022/23 | 380 | 380 | 11547 | 100.0% | no |
| Ligue 1 | 2023/24 | 306 | 306 | 9394 | 100.0% | no |
| Ligue 1 | 2024/25 | 306 | 306 | 9413 | 100.0% | no |
| Ligue 1 | 2025/26 | 306 | 306 | 9408 | 100.0% | no |

Campi necessari dichiarati dal codice `update_all_ppda_player_db.py` / `audit/ppda_deep_player_audit.py`:

| Necessita' | Campi / stato |
|---|---|
| cartellini per giocatore e partita | yellow_cards, red_cards |
| minuti giocati | minutes |
| titolarita' | non disponibile nel player_match Understat; si puo' inferire solo in modo imperfetto da minutes>=~90 o servirebbe lineup |
| ruolo | position |

## 2. Ricostruzione eventi certi

Stato: **NON VERIFICABILE**

Motivo verificabile: Nessun file player_match_<lega>.json e nessuna ground truth ufficiale nel checkout; le fonti committate non contengono identita' giocatore per cartellini/minuti/ruoli.

Conteggi eventi certi per lega/stagione: NON VERIFICABILE nel checkout corrente.

Violazioni condizione 'nota prima del kickoff della partita saltata': NON VERIFICABILE (serve data evento giocatore e partita saltata).

## 3. Validazione della sorgente

| Lega | Precision/Recall | Motivo | Violazioni presenza | Motivo controllo minimo |
|---|---|---|---|---|
| Serie A | NON VERIFICABILE | ground truth ufficiale non presente nel repo | NON VERIFICABILE | controllo minimo richiede player_match della partita saltata; file locale assente |
| Premier League | NON VERIFICABILE | ground truth ufficiale non presente nel repo | NON VERIFICABILE | controllo minimo richiede player_match della partita saltata; file locale assente |
| La Liga | NON VERIFICABILE | ground truth ufficiale non presente nel repo | NON VERIFICABILE | controllo minimo richiede player_match della partita saltata; file locale assente |
| Bundesliga | NON VERIFICABILE | ground truth ufficiale non presente nel repo | NON VERIFICABILE | controllo minimo richiede player_match della partita saltata; file locale assente |
| Ligue 1 | NON VERIFICABILE | ground truth ufficiale non presente nel repo | NON VERIFICABILE | controllo minimo richiede player_match della partita saltata; file locale assente |

## 4. Alto utilizzo

Definizione fissata: giocatore con almeno il 60% dei minuti disponibili nelle ultime 5 partite di campionato della sua squadra prima della partita saltata, usando solo dati precedenti al kickoff. Sensibilita': 40%.

Stato: **NON VERIFICABILE** nel checkout corrente, per assenza dei minuti per giocatore in file locali. Il referto `ppda_deep_player_feasibility` documenta che tali campi erano presenti in un artifact esterno, ma l'artifact non e' versionato nel repo.

## 5. Conteggi richiesti

| Lega | Stagione | Partite con squalificato certo | Partite con alto utilizzo >=60% | Distribuzione ruolo | Assenze multiple | Cluster squadre/giocatori | Motivo |
|---|---|---|---|---|---|---|---|
| Serie A | 2023/24 | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | player_match/ground truth assenti |
| Serie A | 2024/25 | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | player_match/ground truth assenti |
| Serie A | 2025/26 | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | player_match/ground truth assenti |
| Premier League | 2023/24 | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | player_match/ground truth assenti |
| Premier League | 2024/25 | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | player_match/ground truth assenti |
| Premier League | 2025/26 | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | player_match/ground truth assenti |
| La Liga | 2023/24 | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | player_match/ground truth assenti |
| La Liga | 2024/25 | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | player_match/ground truth assenti |
| La Liga | 2025/26 | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | player_match/ground truth assenti |
| Bundesliga | 2023/24 | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | player_match/ground truth assenti |
| Bundesliga | 2024/25 | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | player_match/ground truth assenti |
| Bundesliga | 2025/26 | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | player_match/ground truth assenti |
| Ligue 1 | 2023/24 | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | player_match/ground truth assenti |
| Ligue 1 | 2024/25 | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | player_match/ground truth assenti |
| Ligue 1 | 2025/26 | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | NON VERIFICABILE | player_match/ground truth assenti |

## 6. Potenza statistica

Punti d'iniezione dichiarati:
- A) 1X2: shock transitorio sul differenziale Elo `d_match = d + Δ_H − Δ_A`, metrica LogLoss 1X2.
- B) Totali: shock su lambda in scala logaritmica, metrica LogLoss Over/Under 2.5.

| Punto | δ vero | Potenza α=5% | MDE 80% | Motivo |
|---|---|---|---|---|
| A | 15 Elo | NON VERIFICABILE | NON VERIFICABILE | matrice eventi alto utilizzo assente |
| A | 30 Elo | NON VERIFICABILE | NON VERIFICABILE | matrice eventi alto utilizzo assente |
| A | 50 Elo | NON VERIFICABILE | NON VERIFICABILE | matrice eventi alto utilizzo assente |
| B | 0.05 log-lambda | NON VERIFICABILE | NON VERIFICABILE | matrice eventi alto utilizzo e ruoli assente |
| B | 0.10 log-lambda | NON VERIFICABILE | NON VERIFICABILE | matrice eventi alto utilizzo e ruoli assente |
| B | 0.15 log-lambda | NON VERIFICABILE | NON VERIFICABILE | matrice eventi alto utilizzo e ruoli assente |

## 7. Prior e rapporto posterior/prior

Prior fissati: A) δ ~ N(0, 30²) punti Elo; B) δ ~ N(0, 0.10²) log-lambda.

| Punto | Rapporto sd posterior/prior | Stato |
|---|---|---|
| A | NON VERIFICABILE | numero eventi reali ad alto utilizzo non disponibile |
| B | NON VERIFICABILE | numero eventi reali ad alto utilizzo e ruoli non disponibile |

## 8. Regola di decisione

| Punto | Regola GO | Evidenza disponibile | Verdetto operativo |
|---|---|---|---|
| A 1X2 | MDE 80% <= 30 Elo e posterior/prior <= 0.7 | MDE e rapporto non calcolabili da fonti locali | NO-GO tecnico / NON VERIFICABILE |
| B Totali | MDE 80% <= 0.10 log-lambda e posterior/prior <= 0.7 | MDE e rapporto non calcolabili da fonti locali | NO-GO tecnico / NON VERIFICABILE |

Il verdetto sopra e' operativo per questa PR: non dichiara effetto negativo, dichiara che il campione verificabile dal repo non puo' rispondere.

## 9. Output e riproducibilita'

File prodotti:
- `audit/squalifiche_feasibility.py` — script sola lettura;
- `audit/results/squalifiche_feasibility.md` — questo report;
- `audit/output/squalifiche_feasibility_sources.json` — dettaglio macchina, ignorato da git.

Comando riproducibile:
```
python audit/squalifiche_feasibility.py
```

Stato git dopo generazione report (al momento dello script):
```
A  audit/results/squalifiche_feasibility.md
AM audit/squalifiche_feasibility.py
```

## Chiusura richiesta

- Inventario fonti: riportato in §1 e §1.1 con percorsi, commit, copertura e buchi.
- Eventi certi per lega/stagione: NON VERIFICABILE perché manca nel repo la fonte giocatore-partita con cartellini.
- Validazione sorgente: NON VERIFICABILE perché ground truth ufficiali e player_match locale sono assenti.
- Conteggi alto utilizzo: NON VERIFICABILE perché mancano minuti per giocatore in file locali.
- Potenza/MDE A e B: NON VERIFICABILE perché non esiste matrice eventi reali ad alto utilizzo.
- Rapporto posterior/prior: NON VERIFICABILE perché manca il numero eventi reali.
- Verdetto: A = NO-GO tecnico / NON VERIFICABILE; B = NO-GO tecnico / NON VERIFICABILE; pista in raccolta prospettica o previo versionamento della fonte player_match/ground truth.
