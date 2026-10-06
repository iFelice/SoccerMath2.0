# Fattibilita' feature squalifiche — eventi certi, validazione, conteggi, potenza

**STATO ARTIFACT PLAYER_MATCH:** `ppda-player-verify-37461010400` da run `37461010400`, dimensione compressa `10030865` byte, creato `2026-10-06T12:51:23Z`, scadenza `2026-10-20T12:51:20Z`, expired=`False`. Scade entro 30 giorni rispetto al 2026-10-06: **SI**. Proposta non applicata: promuovere lo zip (~10030865 byte compresso) ad asset di release GitHub o storage oggetto esterno versionato, lasciando fuori git i JSON raw.

Generato: `2026-10-06T13:05:29+00:00` UTC. Commit base script: `a1bb305cc4c06816a6aec0676af18cd3c498b512`.

## 0. Evidenze comandi
| Esito | Comando | Evidenza |
|---|---|---|
| OK | gh run list --workflow ppda_player_verify.yml | run recupero fresco 37461010400 workflow Verifica PPDA/deep/giocatore |
| OK | gh api repos/iFelice/SoccerMath2.0/actions/runs/<run>/artifacts | artifact ppda-player-verify-37461010400 size=10030865 created=2026-10-06T12:51:23Z expires=2026-10-20T12:51:20Z expired=False |
| NON OK | gh run download 34992936842 --name ppda-player-verify-34992936842 | no valid artifacts found to download; API run artifacts total_count=0 (artifact PR#23 non piu' presente) |
| NON OK | gh run download 37461010400 --name ppda-player-verify-37461010400 | sandbox: Azure blob productionresultssa1.blob.core.windows.net -> EOF; download riuscito dentro GitHub Actions per l'analisi |
| NON OK | python update_all_ppda_player_db.py ... (sandbox) | sandbox: GitHub release asset TLS client e understat.com chiudono TLS (SSL_ERROR_SYSCALL/EOF); rigenerazione riuscita nel runner Actions |
| OK | python audit/squalifiche_feasibility.py --player-match-dir ... | report generato su dati player_match recuperati dall'artifact fresco |

## 1. Inventario fonte player_match
| Percorso/script | Fonte | Evidenza |
|---|---|---|
| update_all_ppda_player_db.py | Understat via soccerdata==1.9.1 | usa soccerdata.Understat.read_player_match_stats(); campi minutes, position, yellow_cards, red_cards |
| .github/workflows/ppda_player_verify.yml | workflow PR #23 | upload artifact ppda-player-verify-${{ github.run_id }} con reports/ e database/; retention-days: 14 |
| audit/ppda_deep_player_audit.py | audit copertura | referto storico 224902 righe giocatore nel run 34992936842 |

### Copertura file recuperati
| Lega | File | Byte | Righe | Partite distinte | Stagioni | Cartellini/minuti/ruolo |
|---|---|---|---|---|---|---|
| Serie A | audit/output/ppda-player-verify-37461010400/database/player_match_serie_a.json | 20739587 | 49200 | 1570 | 2022, 2023, 2024, 2025, 2026 | OK |
| Premier League | audit/output/ppda-player-verify-37461010400/database/player_match_premier_league.json | 20284879 | 47324 | 1570 | 2022, 2023, 2024, 2025, 2026 | OK |
| La Liga | audit/output/ppda-player-verify-37461010400/database/player_match_la_liga.json | 21110374 | 49766 | 1589 | 2022, 2023, 2024, 2025, 2026 | OK |
| Bundesliga | audit/output/ppda-player-verify-37461010400/database/player_match_bundesliga.json | 16943284 | 39192 | 1259 | 2022, 2023, 2024, 2025, 2026 | OK |
| Ligue 1 | audit/output/ppda-player-verify-37461010400/database/player_match_ligue_1.json | 17385200 | 41175 | 1343 | 2022, 2023, 2024, 2025, 2026 | OK |

Regole applicate: Serie A: gialli cumulativi 5,9,13,16,18, poi ogni ammonizione; coppe separate; Premier League: 5 gialli entro 19a partita squadra -> 1; 10 entro 32a -> 2; 15 -> 3; La Liga: cicli da 5; esenzione ultima giornata; doppia ammonizione esclusa/ambigua; Bundesliga: 5a, 10a, 15a... ammonizione -> 1 turno; Ligue 1: 2023/24-2024/25: 3 gialli in 10 incontri ufficiali; 2025/26: 5 gialli; coppe nazionali mancanti nel dataset

Limiti dichiarati: rosso diretto certo contato solo quando `red_cards>0` e `yellow_cards==0`; casi red+yellow esclusi come ambigui; Ligue 1 usa dato league-only e dichiara coppe nazionali mancanti; nessuna ground truth ufficiale versionata, validazione minima presenza/assenza su player_match.

## 2. Eventi certi ricostruiti
| Lega | Stagione | Eventi certi | High usage 60% | Violazioni known_at<kickoff |
|---|---|---|---|---|
| Serie A | 2023/24 | 192 | 145 | 0 |
| Serie A | 2024/25 | 159 | 105 | 0 |
| Serie A | 2025/26 | 150 | 112 | 0 |
| Premier League | 2023/24 | 101 | 77 | 0 |
| Premier League | 2024/25 | 93 | 65 | 0 |
| Premier League | 2025/26 | 62 | 47 | 0 |
| La Liga | 2023/24 | 205 | 140 | 0 |
| La Liga | 2024/25 | 201 | 140 | 0 |
| La Liga | 2025/26 | 206 | 136 | 0 |
| Bundesliga | 2023/24 | 158 | 128 | 0 |
| Bundesliga | 2024/25 | 122 | 91 | 0 |
| Bundesliga | 2025/26 | 116 | 87 | 0 |
| Ligue 1 | 2023/24 | 93 | 64 | 0 |
| Ligue 1 | 2024/25 | 85 | 48 | 0 |
| Ligue 1 | 2025/26 | 83 | 51 | 0 |

Casi ambigui esclusi: **71**. Prime righe: Bundesliga 2023 Tuta red_cards>0 con yellow_cards>0: diretto dopo giallo o doppia ammonizione non distinguibile in Understat; La Liga 2022 Fabrizio Angileri red_cards>0 con yellow_cards>0: diretto dopo giallo o doppia ammonizione non distinguibile in Understat; La Liga 2022 Kike Salas red_cards>0 con yellow_cards>0: diretto dopo giallo o doppia ammonizione non distinguibile in Understat; La Liga 2022 Raíllo red_cards>0 con yellow_cards>0: diretto dopo giallo o doppia ammonizione non distinguibile in Understat; La Liga 2022 Ferrán Torres 5a ammonizione Liga all'ultima giornata: esenzione art.112.4, nessun evento contato; La Liga 2022 Raphinha 5a ammonizione Liga all'ultima giornata: esenzione art.112.4, nessun evento contato; La Liga 2022 Tete Morente 5a ammonizione Liga all'ultima giornata: esenzione art.112.4, nessun evento contato; La Liga 2022 Samú Costa 5a ammonizione Liga all'ultima giornata: esenzione art.112.4, nessun evento contato

## 3. Validazione sorgente
| Lega | Candidati ricostruiti | Violazioni: giocatore risulta in campo | Precision minima presenza | Recall |
|---|---|---|---|---|
| Serie A | 567 | 66 | 88.4% | NON VERIFICABILE (ground truth ufficiale non versionata) |
| Premier League | 274 | 18 | 93.4% | NON VERIFICABILE (ground truth ufficiale non versionata) |
| La Liga | 668 | 56 | 91.6% | NON VERIFICABILE (ground truth ufficiale non versionata) |
| Bundesliga | 409 | 13 | 96.8% | NON VERIFICABILE (ground truth ufficiale non versionata) |
| Ligue 1 | 543 | 282 | 48.1% | NON VERIFICABILE (ground truth ufficiale non versionata) |
Candidati esclusi dai conteggi principali per violazione di validazione (il player_match mostra minuti nella partita da saltare): **435**.

## 4-5. Alto utilizzo e conteggi
Alto utilizzo = minuti giocati >=60% dei 450 minuti disponibili nelle ultime 5 partite di campionato della squadra prima della partita saltata; sensibilita' 40% calcolata negli output macchina.
| Lega | Stagione | Partite con >=1 squalificato | Partite con >=1 high60 | Ruoli eventi | Partite multi-assenti | Da entrambe le parti | Squadre | Giocatori |
|---|---|---|---|---|---|---|---|---|
| Serie A | 2023/24 | 144 | 119 | portiere:2, difensore:84, centrocampista:68, attaccante:17, non disponibile:21 | 38 | 28 | 20 | 167 |
| Serie A | 2024/25 | 135 | 93 | portiere:1, difensore:73, centrocampista:46, attaccante:10, non disponibile:29 | 21 | 9 | 20 | 146 |
| Serie A | 2025/26 | 119 | 94 | portiere:3, difensore:72, centrocampista:39, attaccante:17, non disponibile:19 | 26 | 13 | 20 | 136 |
| Premier League | 2023/24 | 82 | 63 | portiere:0, difensore:40, centrocampista:41, attaccante:8, non disponibile:12 | 18 | 7 | 20 | 85 |
| Premier League | 2024/25 | 81 | 58 | portiere:0, difensore:33, centrocampista:43, attaccante:3, non disponibile:14 | 10 | 3 | 19 | 81 |
| Premier League | 2025/26 | 56 | 45 | portiere:0, difensore:31, centrocampista:21, attaccante:3, non disponibile:7 | 5 | 0 | 19 | 53 |
| La Liga | 2023/24 | 150 | 113 | portiere:4, difensore:84, centrocampista:70, attaccante:19, non disponibile:28 | 43 | 20 | 20 | 165 |
| La Liga | 2024/25 | 152 | 115 | portiere:5, difensore:80, centrocampista:63, attaccante:15, non disponibile:38 | 38 | 16 | 20 | 155 |
| La Liga | 2025/26 | 153 | 108 | portiere:2, difensore:93, centrocampista:62, attaccante:9, non disponibile:40 | 44 | 24 | 20 | 164 |
| Bundesliga | 2023/24 | 115 | 100 | portiere:1, difensore:73, centrocampista:64, attaccante:7, non disponibile:13 | 36 | 16 | 18 | 136 |
| Bundesliga | 2024/25 | 99 | 78 | portiere:2, difensore:55, centrocampista:38, attaccante:11, non disponibile:16 | 22 | 12 | 18 | 101 |
| Bundesliga | 2025/26 | 97 | 77 | portiere:1, difensore:53, centrocampista:38, attaccante:4, non disponibile:20 | 17 | 12 | 18 | 97 |
| Ligue 1 | 2023/24 | 80 | 56 | portiere:2, difensore:46, centrocampista:23, attaccante:9, non disponibile:13 | 13 | 9 | 18 | 79 |
| Ligue 1 | 2024/25 | 72 | 42 | portiere:0, difensore:42, centrocampista:19, attaccante:6, non disponibile:18 | 12 | 8 | 18 | 77 |
| Ligue 1 | 2025/26 | 73 | 46 | portiere:3, difensore:49, centrocampista:21, attaccante:4, non disponibile:6 | 10 | 5 | 18 | 75 |

## 6. Potenza statistica
A) 1X2: shock transitorio sul differenziale Elo `d_match=d+Δ_H−Δ_A`, qui Δ effettivo = `δ*(away_high-home_high)`. Stima δ via griglia e test ΔLogLoss appaiato con bootstrap a blocchi squadra.
| δ vero | Potenza α=5% |
|---|---|
| 15 | 26.2% |
| 30 | 72.5% |
| 50 | 100.0% |
MDE 80% A: `50` punti Elo. Rapporto sd posterior/prior A: `0.317`.

B) Totali: shock log-lambda: attaccante assente -> lambda propria; portiere/difensore assente -> lambda avversaria. Centrocampisti esclusi dallo shock B e conteggiati nei ruoli.
| δ vero | Potenza α=5% |
|---|---|
| 0.05 | 10.0% |
| 0.1 | 41.2% |
| 0.15 | 80.0% |
MDE 80% B: `0.15` log-lambda. Rapporto sd posterior/prior B: `0.433`.

## 7-8. Prior e verdetto
| Punto | Prior | Regola GO | MDE | posterior/prior | Verdetto |
|---|---|---|---|---|---|
| A 1X2 | N(0,30^2) Elo | MDE<=30 e ratio<=0.7 | 50 | 0.317 | NO-GO |
| B Totali | N(0,0.10^2) | MDE<=0.10 e ratio<=0.7 | 0.15 | 0.433 | NO-GO |

Entrambi NO-GO: pista da mantenere in raccolta prospettica/validazione ground truth; non e' un effetto negativo.

## Chiusura
Report generato con dati player_match recuperati; il precedente report 'fonti assenti' e' sostituito.
